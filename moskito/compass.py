"""Complexo central: bussola em anel + objetivo.

O circuito da mosca:

  EPG      mantem um "bump" de atividade num anel -- e' a direcao da cabeca
  PEN      giram o bump conforme a mosca gira (integracao de rotacao propria)
  Delta7   inibicao global, garante que exista UM bump so'
  PFL3     compara o bump com a direcao-OBJETIVO e desequilibra os
           descendentes para anular o erro

E' isso que faz a mosca ter rumo em vez de so' reagir. Sem esse circuito o
steering vira reflexo puro: desvia da parede, o obstaculo troca de lado,
desvia de volta -- e o bicho fica oscilando sem sair do lugar.

MENOTAXIA: a mosca nao escolhe um destino, escolhe um ANGULO e o segura por
longos trechos. E' o que produz deslocamento em linha reta e dispersao
eficiente. O objetivo so' muda quando ha' motivo: achou alguem, o lugar ficou
familiar, ou empacou.
"""

from __future__ import annotations

import numpy as np

N = 16                 # colunas do anel (a mosca tem 16 setores no corpo elipsoide)
WIDTH = 1.4            # concentracao do bump (von Mises); menor = bump mais largo
DRIFT = 0.004          # rad/s de deriva: integrador nenhum e' perfeito
HOLD_MIN = 8.0         # s de simulacao segurando o mesmo rumo, no minimo
BORED = 0.35           # abaixo disso o corpo cogumelar diz "ja' conheco"
ESCAPE_MIN = 3.0       # s: fuga e' manobra comprometida, nao gatilho continuo
TRIES = 2              # meias-voltas antes de escalar para re' em linha reta
REVERSE_S = 4.0        # s de re' reta: so' isso tira de fenda estreita
AVOID = 1.3            # peso do obstaculo no comando de curva


def wrap(a: float) -> float:
    """Angulo para [-pi, pi]."""
    return (a + np.pi) % (2 * np.pi) - np.pi


class Compass:
    def __init__(self, seed: int = 0):
        self.rng = np.random.default_rng(seed)
        self.angles = np.arange(N) * 2 * np.pi / N
        self.phase = 0.0                     # posicao do bump = direcao da cabeca
        self.goal = float(self.rng.uniform(-np.pi, np.pi))
        self.held = 0.0
        self.escaping = 0.0
        self.reversing = 0.0
        self.tries = 0

    # --- bussola ---

    def update(self, omega: float, dt: float) -> None:
        """`omega` em rad/s (positivo = anti-horario), `dt` em segundos.

        Modela o RESULTADO do anel EPG/PEN -- um bump cuja fase integra a
        rotacao propria -- e nao a dinamica de spikes dele. Os EPG, PEN e
        Delta7 estao no conectoma (47/24/42 neuronios) e um dia esta classe
        pode ser trocada pela rede de verdade; o resto do codigo nao muda.
        Rodar o anel por normalizacao discreta a cada passo nao funciona: a
        re-normalizacao come o deslocamento sub-coluna e o bump trava.
        """
        self.phase = wrap(self.phase + omega * dt
                          + self.rng.normal(0.0, DRIFT * np.sqrt(dt)))
        self.held += dt
        self.escaping = max(0.0, self.escaping - dt)
        self.reversing = max(0.0, self.reversing - dt)

    @property
    def ring(self) -> np.ndarray:
        """Perfil de atividade dos EPG: um bump von Mises centrado na fase."""
        r = np.exp(WIDTH * np.cos(self.angles - self.phase))
        return (r / r.sum()).astype(np.float32)

    @property
    def heading(self) -> float:
        """Direcao codificada pelo bump (media circular do anel)."""
        r = self.ring
        return float(np.arctan2((r * np.sin(self.angles)).sum(),
                                (r * np.cos(self.angles)).sum()))

    # --- objetivo ---

    def retarget(self, bearing: float | None = None) -> None:
        """Novo rumo. Com `bearing`, aponta para algo visto; senao, ao acaso."""
        self.goal = wrap(self.heading + bearing) if bearing is not None else \
            float(self.rng.uniform(-np.pi, np.pi))
        self.held = 0.0

    def turn_back(self) -> None:
        """Meia-volta com dispersao. E' o que a mosca faz em fundo de beco.

        Rumo NOVO ao acaso nao serve: num canto, metade dos angulos ainda
        aponta para a parede. Virar de costas para onde se estava indo sai
        sempre, e o espalhamento evita repetir a mesma trajetoria.

        Depois de TRIES tentativas sem sair, escala para re' RETA. Numa fenda
        mais estreita que o raio de manobra, virar e' exatamente o que trava:
        so' se sai voltando pelo eixo por onde se entrou. O MDN da mosca faz
        caminhada para tras sustentada -- e' esse programa.
        """
        self.tries += 1
        if self.tries > TRIES:
            self.reversing = REVERSE_S
            self.escaping = REVERSE_S
            self.tries = 0
            return
        self.goal = wrap(self.heading + np.pi + self.rng.uniform(-0.7, 0.7))
        self.held = 0.0
        self.escaping = ESCAPE_MIN

    def back_out(self) -> None:
        """Re' imediata, sem gastar as meias-voltas da escalada.

        E' para quando o campo visual CONGELA: se as rodas giram e nada muda,
        o robo nao esta' num beco largo onde virar resolve -- esta' encunhado,
        e girar ali so' raspa. A unica saida e' voltar pelo eixo por onde
        entrou. Nao ha' informacao a ganhar tentando virar antes.
        """
        self.reversing = REVERSE_S
        self.escaping = REVERSE_S
        self.tries = 0

    def decide(self, *, novelty: float, frustration: float,
               target_bearing: float | None = None, frozen: bool = False) -> None:
        """Muda de rumo so' quando ha' motivo. O resto do tempo, segura."""
        if frustration < 0.2:
            self.tries = 0                      # saiu: zera a escalada
        if self.escaping > 0.0:
            # Manobra de fuga em curso: NAO redecide. Redisparar a meia-volta a
            # cada segundo invertia o objetivo sem parar, o rumo nunca assentava
            # e o bicho remoia no lugar em vez de sair.
            return
        if frozen:
            # Cena parada com motor mandado: nao adianta escolher outro rumo,
            # nenhum rumo esta' sendo executado. Re' primeiro, rumo depois.
            self.back_out()
            return
        if frustration > 0.5:
            # Empacado nao espera o compromisso minimo de rumo: 8 s empurrando
            # canto e' exatamente o que trava.
            self.turn_back()
            return
        if target_bearing is not None:          # viu alguem: persegue, sempre
            self.goal = wrap(self.heading + target_bearing)
            self.held = 0.0
            return
        if self.held < HOLD_MIN:                # compromisso minimo com o rumo
            return
        if novelty < BORED:
            self.retarget()

    @property
    def error(self) -> float:
        """Quanto falta girar para alinhar com o objetivo, em [-pi, pi]."""
        return wrap(self.goal - self.heading)

    def steer(self, gain: float = 2.2, avoid: float = 0.0) -> tuple[float, float]:
        """Erro -> ativacao dos PFL3 esquerdo e direito. Sempre soma 1.

        Os DOIS lados ficam ativos e quem carrega o comando e' a DIFERENCA --
        e' assim no circuito real, e e' o que torna o controle proporcional.
        Injetar so' de um lado dava bang-bang: abaixo do limiar em erro pequeno,
        saturado em erro grande, e o bicho oscilava em volta do rumo.

        Erro positivo = objetivo a esquerda = girar anti-horario. Isso pede
        descendentes ESQUERDOS mais ativos, e quem faz isso e' o PFL3 DIREITO
        (medido: PFL3_R -> assimetria -0.83).
        """
        if self.reversing > 0.0:
            return 0.5, 0.5                     # re' reta: zero comando de curva

        # `avoid` entra como erro de rumo, nao por uma via propria: o H2 tem UM
        # neuronio por lado e satura em +-0.23 de assimetria, contra +-0.85 do
        # PFL3. Injetar mais no H2 nao aumenta nada. Desviar pelo mesmo canal do
        # rumo da' ao obstaculo a mesma autoridade de curva que o objetivo.
        e = float(np.clip(self.error / np.pi * gain + avoid * AVOID, -1.0, 1.0))
        return 0.5 - 0.5 * e, 0.5 + 0.5 * e

    def __str__(self) -> str:
        return (f"rumo={np.degrees(self.heading):+6.1f}° obj={np.degrees(self.goal):+6.1f}° "
                f"erro={np.degrees(self.error):+6.1f}°")
