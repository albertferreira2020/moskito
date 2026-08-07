"""Adaptador entre o cerebro da mosca e um robo de tracao diferencial.

Entrada -> portas do lobulo optico:
  H2      fluxo optico horizontal, CONTRALATERAL -- e' a via de virada
  LPLC2   looming -> fibra gigante -> fuga (parada, nao steering)
  LC11    canal de "cheiro" da base, aberto pela fome

Entrada -> nucleos aminergicos (drives.modulation()):
  s-LNv / LNd / DN1p   relogio circadiano
  OA-VUM / OA-VPM      octopamina: alerta, propensao a estar ativo
  PAM / PPL1           dopamina: novidade e punicao
  ER5 / dFB            homeostato de sono: o freio

Saida <- neuronios descendentes:
  DN_L + DN_R  a MESMA populacao da' as duas coisas:
                 SOMA      -> avanco
                 DIFERENCA -> curva (steering IPSILATERAL)
  MDN          moonwalker, marcha re' -- acionado pela frustracao

Ler avanco na soma e curva na diferenca nao e' truque de engenharia: e' como a
populacao descendente da mosca de fato codifica marcha, com o modo comum
carregando velocidade de avanco e o modo diferencial carregando rotacao.

NAO HA' COMANDO DE AVANCO NESTE ARQUIVO. `forward` e' uma leitura da taxa de
disparo, como um eletrodo -- nao um valor que o software escolhe. Se a rede
estiver quieta, o robo fica parado, e nenhum estado interno pode passar por
cima disso.
"""

from __future__ import annotations

import numpy as np

from .brain import Brain
from .drives import DRIVE_WALK, Drives

# Ganhos do adaptador. Calibracao, nao anatomia.
# V_MAX e' o teto FISICO do e-puck v2: 7.536 rad/s * 0.0205 m de roda. Mandar
# mais que isso nao acelera nada, so' satura -- e saturado o robo pivota em vez
# de fazer curva, porque uma roda vai ao maximo e a outra ao minimo.
K_V = 0.103               # m/s por Hz recrutado -- a escala de leitura
# O FAFB e' um conectoma de CEREBRO. O gerador de padrao da marcha nao esta'
# nele: fica no cordao nervoso ventral, que nao foi reconstruido aqui. O VNC
# nao repassa qualquer atividade descendente -- ele RECRUTA, e so' passa a
# produzir passo acima de um piso de drive. Sem esse piso o basal de 0,74 Hz
# (medido: rede acordada, sem motivacao nenhuma) viraria deslize permanente e o
# robo nunca ficaria parado de verdade.
# Nao e' um `if anda`: e' uma retificacao continua. Logo acima do piso o passo
# e' lento; nada muda de modo, nao ha' decisao binaria em lugar nenhum.
VNC_RECRUIT = 0.75        # Hz de populacao descendente para recrutar marcha
K_ANGULAR = 0.45          # curvatura: multiplica velocidade, nao e' velocidade
PIVOT = 0.25              # quanto de giro sobra com o robo parado (para destravar)
K_REVERSE = 0.004         # m/s por Hz de MDN
V_MAX = 0.154             # so' um padrao: quem manda e' motor.getMaxVelocity()
DRIVE_FLOOR = 0.25        # Hz: abaixo disso a diferenca L/R e' ruido, nao comando
# Vies em repouso da assimetria descendente. Em w_syn=0.18 a resposta ja' e'
# espelhada (+0.228 / -0.218), entao nao ha' vies a subtrair.
TURN_BIAS = 0.0


class Body:
    def __init__(self, brain: Brain, ports: dict[str, list[int]], drives: Drives | None = None,
                 seed: int = 0, v_max: float = V_MAX):
        # Indices como arrays, uma vez. A porta SENSORY tem 17.550 entradas e
        # e' injetada a cada passo: com lista Python o numpy reconverteria tudo
        # a cada chamada, o que sozinho custava mais que a rede.
        self.brain = brain
        self.ports = {k: np.asarray(v, dtype=np.int32) for k, v in ports.items()}
        self.v_max = v_max
        self.drives = drives or Drives()
        self.inject = np.zeros(brain.n, dtype=np.float32)
        self.rng = np.random.default_rng(seed)
        self._escape: str | None = None
        self.drive = 0.0        # ultima taxa da populacao descendente, em Hz

    def sense(self, *, flow_left: float = 0.0, flow_right: float = 0.0,
              looming_left: float = 0.0, looming_right: float = 0.0, odor: float = 0.0,
              target_left: float = 0.0, target_right: float = 0.0,
              goal_left: float = 0.0, goal_right: float = 0.0, reversing: bool = False):
        """Injeta nas portas. Valores em mV (limiar do neuronio = 7 mV)."""
        self.inject[:] = 0.0
        d = self.drives

        # ESTADOS INTERNOS -> NUCLEOS AMINERGICOS.
        # Aqui morava `DNp09 <- 11 mV * drive_forward()`: um comando de andar
        # disfarcado de estado interno, que injetava direto no descendente de
        # caminhada. Agora os estados so' alcancam neuronios moduladores, e o
        # avanco tem de atravessar a rede inteira para existir.
        for port, mv in d.modulation().items():
            self._put(port, mv)

        # DESTRAVAR. A mosca tem marcha re' propria: o MDN (moonwalker), que
        # ativa a caminhada para tras E inibe a de frente. E' literalmente o
        # circuito de sair de beco. Frustracao aciona ele.
        # Re' reta: MDN no talo e NENHUMA entrada lateral, senao as paredes dos
        # dois lados injetam H2 e ele torce enquanto recua -- que e' o que
        # entala de novo. Sair de fenda exige voltar pelo eixo de entrada.
        if reversing:
            self._put("MDN", 26.0)
            return
        self._put("MDN", 14.0 * d.frustration)

        # Escolhe UM lado para escapar e se compromete com ele enquanto durar a
        # frustracao. Sem isso o bicho fica oscilando na frente da parede.
        if d.frustration > 0.3:
            if self._escape is None:
                self._escape = "L" if self.rng.random() < 0.5 else "R"
            self._put(f"H2_{self._escape}", 30.0 * d.frustration)
        else:
            self._escape = None

        # APROXIMAR. H2 vira para o lado CONTRARIO ao estimulo (e' via de
        # desvio), entao para ir na direcao de alguem injeta-se do lado oposto.
        self._put("H2_R", target_left * 45.0 * d.social)
        self._put("H2_L", target_right * 45.0 * d.social)

        # RUMO. PFL3 e' a saida de steering do complexo central: compara o bump
        # dos EPG (direcao atual) com o objetivo e desequilibra os descendentes
        # para anular o erro. E' 3.7x mais forte que H2 com metade da injecao
        # (assimetria +0.85/-0.83 contra +0.23), e e' o que da' RUMO -- sem ele
        # o steering e' reflexo puro e o bicho oscila na frente da parede.
        # Os dois lados sempre acima do limiar (7 mV); o comando esta' na
        # diferenca. Alinhado = 18/18 e nao vira; erro maximo = 26/10.
        # Sem gate de sono: quem cala o steering agora e' o dFB, dentro da rede.
        if goal_left or goal_right:
            self._put("PFL3_L", 10.0 + 16.0 * goal_left)
            self._put("PFL3_R", 10.0 + 16.0 * goal_right)

        # DESVIO: H2 e' a celula tangencial da placa lobular que projeta
        # CONTRALATERAL. Fluxo optico a esquerda -> descendentes direitos ->
        # vira para a direita, ou seja, desvia. Medido em scripts/trace.py:
        # assimetria +0.60 no grafo, +0.23 no spiking.
        self._put("H2_L", flow_left * 40.0)
        self._put("H2_R", flow_right * 40.0)

        # LOOMING: via da fibra gigante = fuga, nao steering (trace.py mostra
        # influencia 60x menor que H2 e ipsilateral). Fica como canal de parada.
        # Reflexo: NAO passa pelos estados internos -- mosca sonolenta tambem
        # foge de tapa.
        self._put("LPLC2_L", looming_left * 12.0)
        self._put("LPLC2_R", looming_right * 12.0)

        # Porta olfativa: o beacon da base entra como "cheiro de comida" e a fome
        # e' que abre o canal. Falta resolver os ORNs -- por ora entra pela LC11.
        self._put("LC11", odor * 10.0 * self.drives.hunger)

    def _put(self, port: str, value: float):
        idx = self.ports.get(port)
        if value and idx is not None and len(idx):
            self.inject[idx] += value

    def act(self, ms: float = 10.0, noise: float = 0.02) -> tuple[float, float]:
        """Roda `ms` de tempo biologico e le' os descendentes. Devolve (v_esq, v_dir)."""
        self.brain.run(ms, inject=self.inject, noise=noise)
        r = lambda k: self.brain.pop_rate(self.ports.get(k, [])) * 1000.0   # Hz

        # Steering pela populacao descendente inteira, nao pelo par DNa02:
        # DNa02 tem UM neuronio por lado e o leitor fica binario e instavel.
        dl, dr = r("DN_L"), r("DN_R")
        self.drive = total = dl + dr

        # AVANCO = modo comum da populacao descendente, retificado pelo piso de
        # recrutamento do VNC. Uma leitura, nao um comando: `total` e' taxa de
        # disparo medida na rede. Rede quieta, robo parado -- e nenhum estado
        # interno consegue contornar isso.
        forward = K_V * max(0.0, total - VNC_RECRUIT)

        # Rede quieta: a razao (dr-dl)/(dr+dl) explode em ruido quando o
        # denominador vai a zero. Sem atividade descendente nao ha' comando
        # nenhum, nem de avanco nem de curva.
        assim = (dr - dl) / total - TURN_BIAS if total > DRIVE_FLOOR else 0.0

        reverse = K_REVERSE * r("MDN")
        v = float(np.clip(forward - reverse, -self.v_max, self.v_max))

        # O giro escala com a VELOCIDADE, senao o mesmo diferencial de rodas
        # vira arco quando rapido e piao quando devagar -- e o bicho passa a
        # girar mais do que anda toda vez que um drive baixa o avanco.
        # PIVOT deixa um resto de giro com o robo parado, para destravar.
        # Cruzeiro faz ARCO; frustrado pivota, que e' o que tira de beco.
        agility = 1.0 + 3.0 * self.drives.frustration
        turn = K_ANGULAR * agility * assim * (abs(v) + PIVOT * self.v_max)

        # Steering e' IPSILATERAL: descendentes mais ativos de um lado fazem a
        # mosca virar para AQUELE lado (DNa02 direito -> curva a direita).
        # Combinado com H2 sendo contralateral, fecha certo: obstaculo a
        # esquerda -> H2_L -> descendentes direitos -> vira a direita, desvia.
        vm = self.v_max
        return float(np.clip(v + turn, -vm, vm)), float(np.clip(v - turn, -vm, vm))

    def walking(self) -> bool:
        """Descritivo, para o log. Nada no controle depende disto."""
        return self.drive > DRIVE_WALK

    def rates(self) -> dict[str, float]:
        keys = ("DN_L", "DN_R", "DNa02_L", "DNa02_R", "MDN")
        return {k: self.brain.pop_rate(self.ports.get(k, [])) * 1000 for k in keys}
