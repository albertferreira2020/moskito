"""Adaptador entre o cerebro da mosca e um robo de tracao diferencial.

Entrada: features visuais -> neuronios de projecao do lobulo optico (LPLC2/LC11).
Saida:  neuronios descendentes -> velocidade das rodas.

O par DNa02 e' o steering da mosca: ela vira para o lado do DNa02 mais ativo.
Isso mapeia direto em v_esq/v_dir, sem inventar nada.
"""

from __future__ import annotations

import numpy as np

from .brain import Brain
from .drives import Drives

# Ganhos do adaptador. Calibracao, nao anatomia.
K_LINEAR = 8.0
K_ANGULAR = 1.2
K_REVERSE = 2.0
V_MAX = 0.25
# Vies em repouso da assimetria descendente. Medido com scripts/calibrate.py e
# subtraido, senao o robo anda torto de fabrica.
TURN_BIAS = 0.083


class Body:
    def __init__(self, brain: Brain, ports: dict[str, list[int]], drives: Drives | None = None):
        self.brain, self.ports = brain, ports
        self.drives = drives or Drives()
        self.inject = np.zeros(brain.n, dtype=np.float32)

    def sense(self, *, looming_left: float = 0.0, looming_right: float = 0.0,
              object_left: float = 0.0, object_right: float = 0.0, odor: float = 0.0):
        """Injeta nas portas. Valores em mV (limiar do neuronio = 7 mV)."""
        self.inject[:] = 0.0
        # Reflexo de looming: NAO passa pelos estados internos. Mosca sonolenta
        # tambem foge de tapa.
        self._put("LPLC2_L", looming_left * 12.0)
        self._put("LPLC2_R", looming_right * 12.0)
        self._put("LC11_L", object_left * 8.0)
        self._put("LC11_R", object_right * 8.0)

        # Porta olfativa: o beacon da base entra como "cheiro de comida" e a fome
        # e' que abre o canal. Falta resolver os ORNs -- por ora entra pela LC11.
        self._put("LC11", odor * 10.0 * self.drives.drive_odor())

        # Vies de exploracao. Isto NAO esta' no conectoma: representa a entrada
        # neuromoduladora/central que faz a mosca andar sem estimulo externo.
        # DNp09 e' o descendente "broadcaster" de caminhada para frente.
        self._put("DNp09", 11.0 * self.drives.drive_forward())

    def _put(self, port: str, value: float):
        if value and (idx := self.ports.get(port)):
            self.inject[idx] += value

    def act(self, ms: float = 10.0, noise: float = 0.02) -> tuple[float, float]:
        """Roda `ms` de tempo biologico e le' os descendentes. Devolve (v_esq, v_dir)."""
        self.brain.run(ms, inject=self.inject, gain=self.drives.gain, noise=noise)
        r = lambda k: self.brain.pop_rate(self.ports.get(k, []))

        # Steering pela populacao descendente inteira, nao pelo par DNa02:
        # DNa02 tem UM neuronio por lado e o leitor fica binario e instavel.
        dl, dr = r("DN_L"), r("DN_R")
        # Steering tambem e' comportamento: bicho dormindo nao vira. O alerta
        # segura um piso, senao um sobressalto nao conseguiria desviar.
        steer_gate = max(self.drives.awake, self.drives.arousal)
        turn = K_ANGULAR * steer_gate * ((dr - dl) / max(dr + dl, 1e-9) - TURN_BIAS)

        forward = K_LINEAR * (dl + dr) / 2 * self.drives.drive_forward()
        reverse = K_REVERSE * r("MDN")

        v = float(np.clip(forward - reverse, -V_MAX, V_MAX))
        return float(np.clip(v - turn, -V_MAX, V_MAX)), float(np.clip(v + turn, -V_MAX, V_MAX))

    def rates(self) -> dict[str, float]:
        keys = ("DN_L", "DN_R", "DNa02_L", "DNa02_R", "MDN")
        return {k: self.brain.pop_rate(self.ports.get(k, [])) * 1000 for k in keys}
