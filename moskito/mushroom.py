"""Corpo cogumelar: novidade de lugar a partir da camera.

O circuito da mosca, na estrutura real:

  entrada de alta dimensao  ->  ~2000 celulas de Kenyon, cada uma amostrando
  poucas entradas ao acaso  ->  inibicao global (neuronio APL) deixa so' uns 5%
  ativos  ->  sinapse KC->MBON diz "isso ja' vi".

Aprendizado de UMA exposicao: dopamina deprime a sinapse nas celulas que
estavam ativas. Lugar revisitado para' de parecer novo. Nao ha' treino, nao ha'
gradiente, nao ha' dataset -- e' uma multiplicacao por (1-lr) nas KCs ativas.

O esquecimento lento e' de proposito: um canto que voce nao ve' ha' muito tempo
volta a ser interessante. E' o que impede o bicho de parar de explorar para
sempre depois de mapear a casa uma vez.
"""

from __future__ import annotations

import numpy as np

N_KC = 2000       # celulas de Kenyon
CLAW = 7          # entradas amostradas por celula (a mosca usa ~6-8)
SPARSITY = 0.05   # fracao que sobrevive a inibicao da APL
LR = 0.4          # depressao por exposicao
RECOVERY = 3e-4   # esquecimento por passo


class MushroomBody:
    def __init__(self, n_in: int, seed: int = 0):
        rng = np.random.default_rng(seed)
        self.claws = rng.integers(0, n_in, size=(N_KC, CLAW))
        self.w = np.ones(N_KC, dtype=np.float32)  # KC -> MBON
        self.k = max(1, int(N_KC * SPARSITY))

    def __call__(self, x: np.ndarray, learn: bool = True) -> float:
        """Devolve novidade em [0,1]. `x` e' o vetor sensorial (ex: camera).

        `learn` marca uma EXPOSICAO, nao um quadro. Chamar com learn=True a
        cada passo de controle deprime a mesma vista ~60 vezes por segundo e
        habitua o apartamento inteiro em segundos: medido em corrida real,
        `nov` ficou em 0,00 com 35-60% do mapa aprendido, o que desliga a via
        dopaminergica de exploracao inteira. Aprendizado de uma exposicao quer
        UMA exposicao -- quem decide isso e' quem chama, pelo fluxo de camera.
        """
        x = np.asarray(x, dtype=np.float32).ravel()
        x = (x - x.mean()) / (x.std() + 1e-6)     # invariante a iluminacao

        act = x[self.claws].sum(axis=1)            # ativacao das KCs
        on = np.argpartition(act, -self.k)[-self.k:]  # APL: so' as mais fortes
        novelty = float(self.w[on].mean())

        # Esquecimento e' do TEMPO, nao da exposicao: um canto que voce nao ve'
        # ha' muito tempo volta a ser interessante. Por isso fica fora do
        # `learn` -- preso dentro dele, parar de aprender parava de esquecer, e
        # o mapa nunca se recuperava.
        self.w += RECOVERY * (1.0 - self.w)
        if learn:
            self.w[on] *= 1.0 - LR
        return novelty

    @property
    def learned(self) -> float:
        """Fracao do espaco visual que ja' virou familiar."""
        return float(1.0 - self.w.mean())


def frame_features(image: bytes, width: int, height: int, grid: int = 16) -> np.ndarray:
    """BGRA do Webots -> vetor de luminancia grosseiro (grid x grid*3/4).

    Resolucao baixa de proposito: o que importa e' a assinatura do lugar, nao
    o detalhe. A mosca tambem nao enxerga detalhe.
    """
    a = np.frombuffer(image, dtype=np.uint8).reshape(height, width, 4)
    lum = a[:, :, :3].mean(axis=2)
    gh, gw = grid * 3 // 4, grid
    hs, ws = height // gh, width // gw
    return lum[: gh * hs, : gw * ws].reshape(gh, hs, gw, ws).mean(axis=(1, 3))
