"""Calibracao do AVANCO EMERGENTE e da lateralizacao.

Responde as perguntas que decidem se o modelo presta:
  1. a rede fica quieta quando nao ha' motivacao, e anda quando ha'?
  2. o freio (sono + fadiga, via ER5/dFB) realmente para a caminhada?
  3. a lateralizacao do PFL3 sobrevive com a rede acordada?
  4. a atividade DECAI quando a modulacao some, ou a rede latcha?

Nada aqui injeta velocidade. Todas as condicoes sao estados internos, e o que
se mede e' a taxa da populacao descendente que sai da rede.

    .venv/bin/python scripts/calibrate.py
"""

import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from moskito.body import K_V, VNC_RECRUIT
from moskito.brain import Brain
from moskito.connectome import load
from moskito.drives import DRIVE_WALK, Drives

W, MOD, _, P = load()

# Estados internos, nao injecoes. Cada um vira corrente em nucleo aminergico
# pela propria Drives.modulation().
ESTADOS = {
    "recem-acordado": dict(hour=7.0, sleep=0.0, hunger=0.3, novelty=1.0),
    "explorando":     dict(hour=7.0, sleep=0.0, hunger=0.8, novelty=1.0),
    "lugar conhecido":dict(hour=12.0, sleep=0.2, hunger=0.3, novelty=0.05),
    "saciado/tedio":  dict(hour=12.0, sleep=0.3, hunger=0.0, novelty=0.02),
    "exausto":        dict(hour=12.0, sleep=0.5, hunger=0.5, novelty=1.0, fatigue=1.0),
    "dormindo":       dict(hour=2.0, sleep=1.0, hunger=0.4, novelty=0.5),
    "sobressaltado":  dict(hour=2.0, sleep=1.0, hunger=0.4, novelty=0.5, arousal=1.0),
}


def rodar(d: Drives, secs: float = 5.0, ms: float = 5.0, pfl=None, seed: int = 3):
    """Roda o cerebro com os estados internos de `d`. Devolve (Hz, assimetria)."""
    b = Brain(W, MOD, seed=seed)
    inj = np.zeros(b.n, np.float32)
    for k, v in d.modulation().items():
        if v and P.get(k):
            inj[P[k]] += v
    if pfl:
        inj[P["PFL3_L"]] += pfl[0]
        inj[P["PFL3_R"]] += pfl[1]
    dn = []
    for _ in range(int(secs * 1000 / ms)):
        b.run(ms, inject=inj, noise=0.02)
        dn.append((b.pop_rate(P["DN_L"]) * 1000, b.pop_rate(P["DN_R"]) * 1000))
    dn = np.array(dn)[-int(secs * 1000 / ms * 0.35):]     # trecho estabilizado
    dl, dr = dn[:, 0].mean(), dn[:, 1].mean()
    total = dl + dr
    assim = (dr - dl) / total if total > 1e-9 else 0.0
    return total, assim, b


if __name__ == "__main__":
    t0 = time.time()
    print("=== 1. avanco por estado interno (nenhuma velocidade injetada) ===")
    print(f"{'estado':>17} {'DN soma':>9} {'recrutado':>10} {'v (cm/s)':>9}  marcha")
    for nome, kw in ESTADOS.items():
        total, _, _ = rodar(Drives(**kw))
        rec = max(0.0, total - VNC_RECRUIT)
        print(f"{nome:>17} {total:9.3f} {rec:10.3f} {K_V * rec * 100:9.2f}"
              f"  {'ANDA' if total > DRIVE_WALK else 'parado'}")

    print("\n=== 2. a lateralizacao do PFL3 sobrevive acordado? ===")
    print(f"{'estado':>17} {'PFL3 26/10':>11} {'18/18':>8} {'10/26':>8}   faixa")
    for nome in ("saciado/tedio", "explorando"):
        a = [rodar(Drives(**ESTADOS[nome]), pfl=p)[1]
             for p in ((26.0, 10.0), (18.0, 18.0), (10.0, 26.0))]
        print(f"{nome:>17} {a[0]:+11.3f} {a[1]:+8.3f} {a[2]:+8.3f}   {a[0] - a[2]:.3f}")

    print("\n=== 3. a rede latcha quando a modulacao some? ===")
    total, _, b = rodar(Drives(**ESTADOS["explorando"]))
    print(f"  com motivacao:   {total:6.3f} Hz")
    for s in (1, 2, 4):
        b.run(1000.0, inject=None, noise=0.02)
        t = b.pop_rate(P["DN_L"]) * 1000 + b.pop_rate(P["DN_R"]) * 1000
        print(f"  +{s}s sem nada:   {t:6.3f} Hz  exc(DN)={b.exc[np.array(P['DN'])].mean():.3f}")

    print(f"\n({time.time() - t0:.0f}s)")
