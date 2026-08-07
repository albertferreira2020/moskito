"""Runtime LIF orientado a eventos sobre o conectoma.

A atividade numa rede spiking e' esparsa: ~1% dos neuronios dispara por ms.
Entao nao se faz o produto matriz-vetor completo (3.7M arestas). Propaga-se
apenas as arestas de saida de quem disparou (~40k), o que e' ~100x mais barato
e e' o que permite tempo real numa CPU.

DUAS matrizes, dois regimes de tempo. A rapida (ACH/GABA/GLUT) e' ionotropica:
o transmissor abre um canal e a corrente chega em milissegundos. A moduladora
(DA/SER/OCT) e' metabotropica -- receptor acoplado a proteina G, cascata de
segundo mensageiro, efeito em SEGUNDOS. Ela nao despolariza o alvo: muda o
quanto ele responde ao resto. Por isso vira um campo lento de EXCITABILIDADE
(`exc`) que multiplica a corrente de entrada, e nao uma corrente somada.

E' essa separacao que permite locomocao emergente: nenhum neuronio "manda
andar". O campo modulador sobe, a rede inteira fica mais responsiva, e a
populacao descendente passa a se sustentar sozinha. O limiar de caminhada e' o
ponto onde a recorrencia se sustenta -- nao um `if` no software.
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

# Adaptacao LENTA (correntes de K+ dependentes de Ca2+ e bomba Na/K). E' a
# fadiga do neuronio, e ela tem escala de SEGUNDOS -- por isso e' separada da
# adaptacao rapida acima.
#
# Sem ela a rede latcha: medido, com tonico de 9 mV e um pulso de octopamina de
# 14 mV a populacao descendente sobe para ~2,3 Hz e FICA LA' mesmo depois que a
# octopamina volta a zero (1,908 Hz 10 s depois). Nenhum script do projeto
# tinha rodado a rede por mais de 1 s, entao o latch nunca aparecera: o W_SYN
# foi calibrado com 350 ms de simulacao.
# Com ela o estado alto se auto-termina, e a marcha vira SURTO -- que e' como a
# mosca de fato anda, em episodios, e nao num regime continuo.
TAU_SLOW = 4000.0 # ms
B_SLOW = 0.005    # mV por spike -- calibrado por scripts/search.py
V_TH = 7.0        # mV acima do repouso
T_REF = 2.2       # ms, periodo refratario
W_SYN = 0.18      # mV por sinapse -- o parametro mais sensivel do modelo.
                  # Calibrado pela LATERALIZACAO, nao pela taxa media: com 1.0 a
                  # rede da' ~11 Hz "plausiveis" mas com i_syn em -1800 mV, um
                  # regime saturado onde a injecao sensorial e' irrelevante.
                  # Em 0.18 o estimulo em H2 produz assimetria +0.23/-0.22
                  # espelhada nos descendentes. Ver scripts/calibrate.py.

# Campo modulador. TAU_MOD e' o que da' PERSISTENCIA: a amina acumulada leva
# segundos para decair, entao a rede "lembra" que estava motivada mesmo quando
# a entrada oscila. E' a integracao temporal que substitui qualquer timer.
TAU_MOD = 3000.0  # ms -- transmissao por volume, escala de segundos
W_MOD = 0.030     # concentracao por aferente modulador saturado
K_MOD = 1.30      # excitabilidade maxima que o campo consegue somar


class Brain:
    def __init__(self, w: csr_matrix, mod: csr_matrix | None = None,
                 w_syn: float = W_SYN, dt: float = DT, seed: int = 0):
        w = w.tocsr()
        self.indptr, self.indices, self.data = w.indptr, w.indices, w.data * w_syn
        self.n = w.shape[0]
        self.dt = dt

        # Matriz moduladora: mesma estrutura, escala e efeito diferentes.
        if mod is None:
            self.m_indptr = None
        else:
            mod = mod.tocsr()
            self.m_indptr, self.m_indices = mod.indptr, mod.indices
            # Normaliza por ALVO: o que importa e' a fracao dos receptores do
            # neuronio que estao ocupados, nao a contagem bruta de sinapses.
            # Sem isso o campo satura no primeiro segundo (medido: m_level em
            # 637 com tanh preso em 1,0) e a modulacao perde toda a dinamica.
            scale = np.asarray(abs(mod).sum(axis=0)).ravel()
            scale[scale == 0.0] = 1.0
            self.m_data = (mod.data / scale[mod.indices]) * W_MOD
        self.m_level = np.zeros(self.n, dtype=np.float32)   # concentracao local
        self.exc = np.ones(self.n, dtype=np.float32)        # excitabilidade
        self._gain, self._eg = 1.0, np.ones(self.n, dtype=np.float32)
        self.decay = np.float32(np.exp(-dt / TAU_M))
        self.syn_decay = np.float32(np.exp(-dt / TAU_SYN))
        self.adapt_decay = np.float32(np.exp(-dt / TAU_ADAPT))
        self.slow_decay = np.float32(np.exp(-dt / TAU_SLOW))
        self.ref_steps = int(T_REF / dt)

        self.v = np.zeros(self.n, dtype=np.float32)
        self.i_syn = np.zeros(self.n, dtype=np.float32)
        self.i_adapt = np.zeros(self.n, dtype=np.float32)
        self.i_slow = np.zeros(self.n, dtype=np.float32)
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
        self.i_slow *= self.slow_decay
        i = self.i_syn if inject is None else self.i_syn + inject
        # `_eg` = excitabilidade x ganho, um vetor so'. A excitabilidade e' o
        # unico caminho pelo qual os estados internos tocam a rede.
        if gain != self._gain:
            self._gain, self._eg = gain, self.exc * gain
        self.v += (1.0 - self.decay) * (self._eg * i - self.i_adapt - self.i_slow - self.v)
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
            self.i_slow[spk] += B_SLOW
            tgt, w = self._out_edges(self.indptr, self.indices, self.data, spk)
            self.i_syn += np.bincount(tgt, weights=w, minlength=self.n).astype(np.float32)
            if self.m_indptr is not None:
                # Liberacao de amina. Acumula concentracao, nao corrente: o
                # efeito e' aplicado em run(), na escala de segundos.
                tgt, w = self._out_edges(self.m_indptr, self.m_indices, self.m_data, spk)
                if tgt.size:
                    self.m_level += np.bincount(tgt, weights=w, minlength=self.n).astype(np.float32)

        self.rate *= self.rate_decay
        if spk.size:
            self.rate[spk] += 1.0 - self.rate_decay
        return spk

    def run(self, ms: float, **kw) -> int:
        """Simula `ms` de tempo biologico. Devolve o total de spikes.

        A excitabilidade e' recalculada uma vez por chamada, nao por passo: com
        TAU_MOD de 3 s, a concentracao de amina nao muda de forma apreciavel em
        5 ms de tempo biologico, e recalcular 139k tanh a cada 0,1 ms custaria
        mais que a propria rede. O `tanh` satura o campo -- receptor tem numero
        finito, entao mais amina nao vira excitabilidade sem limite.
        """
        self.m_level *= np.exp(-ms / TAU_MOD)
        np.tanh(self.m_level, out=self.exc)
        self.exc *= K_MOD
        self.exc += 1.0
        # Piso: serotonina levaria 1 - K_MOD a excitabilidade NEGATIVA, que
        # inverteria o sinal de cada sinapse em vez de silenciar o neuronio.
        # Inibicao por modulacao e' fechar a torneira, nao trocar a torneira.
        np.clip(self.exc, 0.05, None, out=self.exc)
        self._gain, self._eg = None, None   # forca recalculo de exc x ganho
        return sum(self.step(**kw).size for _ in range(int(ms / self.dt)))

    @staticmethod
    def _out_edges(indptr, indices, data, spk: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Concatena as arestas de saida dos neuronios em `spk` sem laco Python."""
        starts = indptr[spk]
        counts = indptr[spk + 1] - starts
        total = int(counts.sum())
        if total == 0:
            return np.zeros(0, np.int32), np.zeros(0, np.float32)
        offsets = np.concatenate(([0], np.cumsum(counts)[:-1]))
        flat = np.repeat(starts - offsets, counts) + np.arange(total)
        return indices[flat], data[flat]

    def pop_rate(self, idx) -> float:
        """Taxa media da populacao, em spikes/ms. Aceita lista ou array."""
        return float(self.rate[idx].mean() / self.dt) if idx is not None and len(idx) else 0.0
