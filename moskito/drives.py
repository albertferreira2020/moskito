"""Estados internos -- a parte que NAO esta no conectoma.

O FlyWire da a fiacao. Nao da o relogio circadiano, a pressao de sono, a fome
nem as aminas biogenicas: essas moleculas agem POR CIMA da fiacao, e e' delas
que saem "acordar, explorar, cansar".

A regra desta versao: **nenhum estado aqui produz velocidade**. Cada um injeta
corrente num nucleo REAL do conectoma -- s-LNv, LNd, ER5/dFB, PAM, PPL1,
OA-VUM -- e o que sai disso e' excitabilidade (brain.py). Se o robo anda ou
nao, e quao rapido, e' consequencia da rede. Nao existe mais `drive_forward()`,
nem qualquer numero aqui que vire m/s.

Tempo comprimido: um dia da mosca = DAY_MINUTES minutos de relogio de parede.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

DAY_MINUTES = 20.0
TIME_SCALE = 24 * 60 / DAY_MINUTES  # 72x: 1 s de parede = 72 s de mosca

# Correntes (mV) para as portas moduladoras. Sao ganhos de calibracao, como o
# W_SYN -- calibrados pela FAIXA DE AVANCO que produzem (scripts/calibrate.py),
# nao por plausibilidade da taxa media. Nenhum deles e' velocidade.
TONIC = 8.0      # aferencia mecanossensorial de fundo, CONSTANTE
M_CLOCK = 34.0   # relogio -> s-LNv / LNd / DN1p
M_OCT = 60.0     # octopamina -> OA-VUM/VPM
M_DA = 40.0      # dopamina de recompensa -> PAM
M_PUN = 30.0     # dopamina de punicao -> PPL1
M_SLEEP = 55.0   # homeostato -> ER5 + dFB

# Limiar de "esta' caminhando", em Hz da populacao descendente. NAO e' um
# gatilho: nada no controle testa isso para decidir andar. Serve para a fadiga
# saber que o circuito esta' trabalhando e para o log dizer o que acontece.
DRIVE_WALK = 0.9


def _clock(hour: float) -> tuple[float, float]:
    """Os dois picos do relogio da mosca: amanhecer (~7h) e entardecer (~19h).

    Nao e' uma curva inventada: sao os dois osciladores que a literatura
    separa. s-LNv (PDF) comanda o pico da manha, LNd o do entardecer, e a
    atividade bimodal cai da soma dos dois.
    """
    wrap = lambda h: (hour - h + 12) % 24 - 12  # distancia circular em horas
    return math.exp(-(wrap(7.0) ** 2) / 18.0), math.exp(-(wrap(19.0) ** 2) / 18.0)


@dataclass
class Drives:
    hour: float = 6.0          # hora do dia da mosca
    sleep: float = 0.0         # pressao de sono   [0,1]  (R5 / dFB)
    hunger: float = 0.3        # fome              [0,1]  (NPF / AKH)
    arousal: float = 0.0       # alerta            [0,1]  (octopamina)
    novelty: float = 1.0       # novidade do lugar [0,1]  (corpo cogumelar)
    frustration: float = 0.0   # "isso nao esta' dando certo" [0,1]
    social: float = 0.0        # vontade de achar alguem      [0,1]
    fatigue: float = 0.0       # custo metabolico acumulado   [0,1]

    t_wake: float = 16 * 3600.0    # s de mosca para saturar a pressao de sono
    t_sleep: float = 6 * 3600.0    # s de mosca para descarregar
    t_hunger: float = 6 * 3600.0
    t_arousal: float = 120.0       # octopamina decai em ~2 min
    t_frust_up: float = 3.0        # segundos de mosca preso ate' saturar
    t_frust_down: float = 8.0
    t_social: float = 2 * 3600.0
    t_fat_up: float = 5400.0       # s de mosca acumulando esforco
    t_fat_down: float = 1800.0     # s de mosca descarregando
    history: list = field(default_factory=list)

    def update(self, dt_wall: float, *, drive: float = 0.0, looming: float = 0.0,
               at_dock: bool = False, place_novelty: float | None = None,
               stuck: bool = False, met_someone: bool = False):
        """`dt_wall` em segundos de relogio de parede.

        `drive` e' a atividade da populacao descendente (Hz), nao a velocidade
        das rodas: o que cansa a mosca e' o circuito trabalhando. Ler a saida
        motora aqui fecharia um laco em cima do que queremos explicar.
        """
        dt = dt_wall * TIME_SCALE  # segundos de mosca
        self.hour = (self.hour + dt / 3600.0) % 24.0

        # Frustracao: sobe rapido enquanto empurra parede sem sair do lugar,
        # cai rapido assim que destrava. E' o sinal de "isso esta' chato".
        self.frustration += dt / (self.t_frust_up if stuck else -self.t_frust_down)
        self.frustration = min(1.0, max(0.0, self.frustration))

        self.social = 0.0 if met_someone else min(1.0, self.social + dt / self.t_social)

        # Fadiga: custo metabolico da marcha, como INTEGRADOR COM VAZAMENTO.
        # A versao anterior somava um passo fixo sempre que `drive > DRIVE_WALK`
        # e subtraia quando abaixo -- e como DRIVE_WALK cai em cima do ponto de
        # operacao, o bicho oscilava em torno do limiar, a fadiga saturava em
        # 12 s de parede e NUNCA descarregava. Medido em corrida real: fadiga
        # entre 0,80 e 1,00 por duas horas de mosca, com a torneira aminergica
        # fechada a 5% o tempo todo. O robo ficava permanentemente exausto e
        # arrastado, sem conseguir correr nem quando tudo mais pedia.
        # Agora acumula proporcional ao ESFORCO (quanto passa do piso de
        # marcha) e vaza sempre: o equilibrio e' esforco * t_down/t_up, entao
        # marcha moderada da' fadiga moderada, e so' esforco sustentado satura.
        esforco = max(0.0, drive - DRIVE_WALK)
        self.fatigue += dt * (esforco / self.t_fat_up - self.fatigue / self.t_fat_down)
        self.fatigue = min(1.0, max(0.0, self.fatigue))

        resting = drive <= DRIVE_WALK
        self.sleep += dt / (self.t_sleep if resting else self.t_wake) * (-1 if resting else 1)
        self.sleep = min(1.0, max(0.0, self.sleep))

        self.hunger = 0.0 if at_dock else min(1.0, self.hunger + dt / self.t_hunger * (1.0 if resting else 1.5))

        self.arousal = min(1.0, self.arousal * math.exp(-dt / self.t_arousal) + looming)
        if place_novelty is not None:
            self.novelty = place_novelty

        self.history.append((self.hour, self.sleep, self.hunger, self.arousal))

    # --- como os estados entram no conectoma ---

    def modulation(self) -> dict[str, float]:
        """Corrente (mV) para cada nucleo aminergico. A UNICA saida desta classe.

        Nenhum destes numeros vira velocidade. Eles fazem neuronios reais
        disparar; o resto e' a rede.

        - s-LNv / LNd: os dois osciladores do relogio, cada um no seu pico.
        - DN1p: integrador dorsal, saida do relogio para os circuitos de
          arousal -- soma os dois picos.
        - OA-VUM/VPM: octopamina. Sobe com alerta (sobressalto), com fome e com
          vontade social. E' o sinal de "vale a pena estar ativo".
        - PAM: dopamina de recompensa. A NOVIDADE do lugar e' o que a excita --
          e' o mecanismo de exploracao, e habitua sozinho quando o corpo
          cogumelar para de achar o lugar novo.
        - PPL1: dopamina de punicao. Sobe com frustracao.
        - ER5 + dFB: o freio. Pressao de sono E fadiga entram juntas; o R5
          acumula necessidade de sono com a vigilia e o dFB e' o interruptor.

        O SONO FECHA A TORNEIRA AMINERGICA, e nao so' excita o dFB. Medimos que
        excitar ER5+dFB nao chega aos descendentes -- com 55 mV neles a
        populacao nao cai (armadilha 5), porque o alvo do circuito de sono e' o
        sistema de arousal, nao o barramento motor. Com o freio so' pelo dFB,
        mosca DORMINDO recebia 36,6 mV de octopamina contra 52,2 da motivada, e
        a separacao entre os dois estados dava 0,003 Hz: nula. Suprimir a
        liberacao de amina e' o que o dFB/R5 de fato faz, e e' onde o efeito
        cabe. Continua sendo estado -> nucleo; nada disto toca motor.

        O alerta (octopamina de sobressalto) passa por cima: mosca dormindo
        acorda com tapa.
        """
        dawn, dusk = _clock(self.hour)
        # Quanto a maquinaria aminergica consegue liberar. Sono e fadiga fecham.
        desperto = max(1.0 - max(self.sleep, self.fatigue), self.arousal)
        explore = self.novelty * (0.5 + 0.5 * self.hunger)
        motivo = max(self.arousal, self.social, self.hunger)
        return {
            "SENSORY": TONIC,
            "CLOCK_M": M_CLOCK * dawn,
            "CLOCK_E": M_CLOCK * dusk,
            "CLOCK_D": M_CLOCK * max(dawn, dusk),
            "OCT": M_OCT * desperto * min(1.0, 0.15 + 0.85 * motivo),
            "DA_REW": M_DA * desperto * explore,
            "DA_PUN": M_PUN * desperto * self.frustration,
            "SLEEP": M_SLEEP * min(1.0, self.sleep + self.fatigue),
        }

    @property
    def awake(self) -> float:
        """Descritivo, para o log. Nao gateia motor nenhum -- quem faz isso
        agora e' o dFB inibindo dentro do conectoma."""
        dawn, dusk = _clock(self.hour)
        return max(0.0, 1.0 - max(self.sleep, self.fatigue)) * (0.45 + 0.55 * max(dawn, dusk))

    def asleep(self) -> bool:
        return self.sleep > 0.9 or self.awake < 0.1

    def __str__(self) -> str:
        return (f"{self.hour:05.2f}h sono={self.sleep:.2f} fome={self.hunger:.2f} "
                f"alerta={self.arousal:.2f} nov={self.novelty:.2f} frust={self.frustration:.2f} "
                f"social={self.social:.2f} fadiga={self.fatigue:.2f}")
