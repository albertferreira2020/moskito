"""Runtime LIF orientado a eventos sobre o conectoma.

A atividade numa rede spiking e' esparsa: ~1% dos neuronios dispara por ms.
Entao nao se faz o produto matriz-vetor completo (3.7M arestas). Propaga-se
apenas as arestas de saida de quem disparou (~40k), o que e' ~100x mais barato
e e' o que permite tempo real numa CPU.
"""

from __future__ import annotations

import numpy as np
from scipy.sparse import csr_matrix

# Parametros de calibracao. O conectoma da anatomia, nao fisiologia:
# nada abaixo vem dos CSVs, sao valores uniformes que voce ajusta.
DT = 0.1          # ms, passo de integracao
TAU_M = 20.0      # ms, constante de membrana
TAU_SYN = 5.0     # ms, decaimento da corrente sinaptica
TAU_ADAPT = 120.0 # ms, decaimento da adaptacao de frequencia
B_ADAPT = 1.6     # mV acumulados por spike -- impede a rede de latchar
V_TH = 7.0        # mV acima do repouso
T_REF = 2.2       # ms, periodo refratario
W_SYN = 0.18      # mV por sinapse -- o parametro mais sensivel do modelo.
                  # Calibrado pela LATERALIZACAO, nao pela taxa media: com 1.0 a
                  # rede da' ~11 Hz "plausiveis" mas com i_syn em -1800 mV, um
                  # regime saturado onde a injecao sensorial e' irrelevante.
                  # Em 0.18 o estimulo em H2 produz assimetria +0.23/-0.22
                  # espelhada nos descendentes. Ver scripts/calibrate.py.


class Brain:
    def __init__(self, w: csr_matrix, w_syn: float = W_SYN, dt: float = DT, seed: int = 0):
        w = w.tocsr()
        self.indptr, self.indices, self.data = w.indptr, w.indices, w.data * w_syn
        self.n = w.shape[0]
        self.dt = dt
        self.decay = np.float32(np.exp(-dt / TAU_M))
        self.syn_decay = np.float32(np.exp(-dt / TAU_SYN))
        self.adapt_decay = np.float32(np.exp(-dt / TAU_ADAPT))
        self.ref_steps = int(T_REF / dt)

        self.v = np.zeros(self.n, dtype=np.float32)
        self.i_syn = np.zeros(self.n, dtype=np.float32)
        self.i_adapt = np.zeros(self.n, dtype=np.float32)
        self.ref = np.zeros(self.n, dtype=np.int16)
        self.rate = np.zeros(self.n, dtype=np.float32)  # media movel de disparos
        self.rate_decay = np.float32(np.exp(-dt / 50.0))
        self.rng = np.random.default_rng(seed)

    def step(self, inject: np.ndarray | None = None, gain: float = 1.0, noise: float = 0.0):
        """Um passo de dt ms. `inject` e' corrente sinaptica em mV."""
        # Corrente sinaptica decai; a membrana persegue a corrente (Euler exponencial),
        # entao v em regime tende a i_syn -- limiar e corrente ficam na mesma unidade.
        self.i_syn *= self.syn_decay
        self.i_adapt *= self.adapt_decay
        i = self.i_syn if inject is None else self.i_syn + inject
        self.v += (1.0 - self.decay) * (gain * i - self.i_adapt - self.v)
        if noise:
            # Ruido num subconjunto: manter 139k gaussianas por passo dominaria o custo.
            k = 2048
            idx = self.rng.integers(0, self.n, k)
            self.v[idx] += self.rng.normal(0.0, noise, k).astype(np.float32)

        self.v[self.ref > 0] = 0.0
        self.ref[self.ref > 0] -= 1

        spk = np.flatnonzero(self.v >= V_TH).astype(np.int32)
        if spk.size:
            self.v[spk] = 0.0
            self.ref[spk] = self.ref_steps
            self.i_adapt[spk] += B_ADAPT
            tgt, w = self._out_edges(spk)
            self.i_syn += np.bincount(tgt, weights=w, minlength=self.n).astype(np.float32)

        self.rate *= self.rate_decay
        if spk.size:
            self.rate[spk] += 1.0 - self.rate_decay
        return spk

    def run(self, ms: float, **kw) -> int:
        """Simula `ms` de tempo biologico. Devolve o total de spikes."""
        return sum(self.step(**kw).size for _ in range(int(ms / self.dt)))

    def _out_edges(self, spk: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Concatena as arestas de saida dos neuronios em `spk` sem laco Python."""
        starts = self.indptr[spk]
        counts = self.indptr[spk + 1] - starts
        total = int(counts.sum())
        if total == 0:
            return np.zeros(0, np.int32), np.zeros(0, np.float32)
        offsets = np.concatenate(([0], np.cumsum(counts)[:-1]))
        flat = np.repeat(starts - offsets, counts) + np.arange(total)
        return self.indices[flat], self.data[flat]

    def pop_rate(self, idx: list[int]) -> float:
        """Taxa media da populacao, em spikes/ms."""
        return float(self.rate[idx].mean() / self.dt) if idx else 0.0
