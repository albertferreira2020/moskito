"""Estados internos -- a parte que NAO esta no conectoma.

O FlyWire da a fiacao. Nao da dopamina, octopamina, NPF, nem o relogio
circadiano. Esses sistemas agem por cima da fiacao mudando ganhos, e sao eles
que produzem "acordar, explorar, cansar". Sao cinco escalares.

Tempo comprimido: um dia da mosca = DAY_MINUTES minutos de relogio de parede.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

DAY_MINUTES = 20.0
TIME_SCALE = 24 * 60 / DAY_MINUTES  # 72x: 1 s de parede = 72 s de mosca


def _circadian(hour: float) -> float:
    """Atividade bimodal: pico ao amanhecer (~7h) e ao entardecer (~19h)."""
    wrap = lambda h: (hour - h + 12) % 24 - 12  # distancia circular em horas
    dawn = math.exp(-(wrap(7.0) ** 2) / 18.0)
    dusk = math.exp(-(wrap(19.0) ** 2) / 18.0)
    # O piso segura um andar decente fora dos picos. Quem apaga o bicho a
    # noite e' a pressao de sono, nao o relogio.
    return 0.45 + 0.55 * max(dawn, dusk)


@dataclass
class Drives:
    hour: float = 6.0          # hora do dia da mosca
    sleep: float = 0.0         # pressao de sono   [0,1]  (dFB / R2)
    hunger: float = 0.3        # fome              [0,1]  (NPF / AKH)
    arousal: float = 0.0       # alerta            [0,1]  (octopamina)
    novelty: float = 1.0       # novidade do lugar [0,1]  (corpo cogumelar)
    frustration: float = 0.0   # "isso nao esta' dando certo" [0,1]
    social: float = 0.0        # vontade de achar alguem      [0,1]

    t_wake: float = 16 * 3600.0    # s de mosca para saturar a pressao de sono
    t_sleep: float = 6 * 3600.0    # s de mosca para descarregar
    t_hunger: float = 6 * 3600.0
    t_arousal: float = 120.0       # octopamina decai em ~2 min
    t_frust_up: float = 3.0        # segundos de mosca preso ate' saturar
    t_frust_down: float = 8.0
    t_social: float = 2 * 3600.0
    history: list = field(default_factory=list)

    def update(self, dt_wall: float, *, moving: bool, looming: float = 0.0,
               at_dock: bool = False, place_novelty: float | None = None,
               stuck: bool = False, met_someone: bool = False):
        """`dt_wall` em segundos de relogio de parede."""
        dt = dt_wall * TIME_SCALE  # segundos de mosca
        self.hour = (self.hour + dt / 3600.0) % 24.0

        # Frustracao: sobe rapido enquanto empurra parede sem sair do lugar,
        # cai rapido assim que destrava. E' o sinal de "isso esta' chato".
        self.frustration += dt / (self.t_frust_up if stuck else -self.t_frust_down)
        self.frustration = min(1.0, max(0.0, self.frustration))

        self.social = 0.0 if met_someone else min(1.0, self.social + dt / self.t_social)

        resting = not moving
        self.sleep += dt / (self.t_sleep if resting else self.t_wake) * (-1 if resting else 1)
        self.sleep = min(1.0, max(0.0, self.sleep))

        self.hunger = 0.0 if at_dock else min(1.0, self.hunger + dt / self.t_hunger * (1.5 if moving else 1.0))

        self.arousal = min(1.0, self.arousal * math.exp(-dt / self.t_arousal) + looming)
        if place_novelty is not None:
            self.novelty = place_novelty

        self.history.append((self.hour, self.sleep, self.hunger, self.arousal))

    # --- como os estados modulam a fiacao ---

    @property
    def awake(self) -> float:
        """Quanto o bicho consegue agir. Sono alto fecha tudo."""
        return max(0.0, 1.0 - self.sleep) * _circadian(self.hour)

    @property
    def gain(self) -> float:
        """Ganho global -- octopamina deixa a rede inteira mais responsiva."""
        return 1.0 + 2.0 * self.arousal

    def drive_forward(self) -> float:
        """Empurra os DNs de caminhada. Curiosidade so' pesa se estiver acordado.

        Frustracao corta o avanco: nao adianta empurrar mais forte a parede.
        Vontade social sustenta um piso -- procurar alguem vence o tedio de um
        lugar ja' conhecido.
        """
        curiosity = 0.6 + 0.4 * max(self.novelty, 0.6 * self.social)
        # Corta o avanco, mas nao a ponto de nao conseguir SAIR: escapar de um
        # canto exige movimento, e 80% de corte deixava o bicho sem forca.
        return self.awake * curiosity * (1.0 - 0.45 * self.frustration)

    def drive_odor(self) -> float:
        """Abre a via do 'cheiro' (beacon da base). Mosca saciada ignora comida."""
        return self.awake * self.hunger

    def asleep(self) -> bool:
        return self.sleep > 0.9 or self.awake < 0.1

    def __str__(self) -> str:
        return (f"{self.hour:05.2f}h sono={self.sleep:.2f} fome={self.hunger:.2f} "
                f"alerta={self.arousal:.2f} nov={self.novelty:.2f} frust={self.frustration:.2f} "
                f"social={self.social:.2f} acordado={self.awake:.2f}")
