"""Um dia comprimido da mosca, sem Webots.

Injeta looming e fome sinteticos, le' os descendentes, e plota:
estados internos -> taxas dos DNs -> velocidade das rodas.
E' o teste que mostra o bicho "decidindo" antes de existir robo.
"""

import argparse
import sys
import time
from pathlib import Path

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from moskito.body import Body
from moskito.brain import Brain
from moskito.connectome import load
from moskito.drives import DAY_MINUTES, Drives

p = argparse.ArgumentParser()
p.add_argument("--ticks", type=int, default=400, help="passos do loop de controle")
p.add_argument("--brain-ms", type=float, default=10.0, help="ms biologicos por passo")
p.add_argument("--out", default="demo.png")
a = p.parse_args()

w, _, ports = load()
body = Body(Brain(w, seed=7), ports, Drives())
rng = np.random.default_rng(7)

# O dia inteiro cabe em `ticks` passos de relogio de parede.
dt_wall = DAY_MINUTES * 60 / a.ticks

log = []
t0 = time.perf_counter()
for i in range(a.ticks):
    d = body.drives
    # Parede/obstaculo de um lado -> fluxo optico daquele lado (steering).
    # Sobressalto ocasional -> looming (reflexo de parada).
    flow_l = flow_r = loom_l = loom_r = 0.0
    if rng.random() < 0.35:
        side = rng.random() < 0.5
        flow_l, flow_r = (1.0, 0.0) if side else (0.0, 1.0)
    if rng.random() < 0.04:
        loom_l, loom_r = (1.0, 0.0) if rng.random() < 0.5 else (0.0, 1.0)

    body.sense(flow_left=flow_l, flow_right=flow_r,
               looming_left=loom_l, looming_right=loom_r, odor=d.hunger)
    vl, vr = body.act(a.brain_ms)

    speed = abs(vl + vr) / 2      # translacao liquida: girar no lugar nao e' "andar"
    moving = speed > 0.01
    at_dock = d.hunger > 0.9  # chegou na base seguindo o "cheiro" e recarregou
    d.update(dt_wall, moving=moving, looming=max(loom_l, loom_r), at_dock=at_dock,
             place_novelty=float(np.clip(0.5 + 0.5 * np.sin(i / 37.0), 0, 1)))

    r = body.rates()
    log.append((d.hour, d.sleep, d.hunger, d.arousal, d.awake,
                r["DN_L"], r["DN_R"], r["MDN"], vl, vr))
    if i % 50 == 0:
        print(f"{i:4d} {d}  DN L/R={r["DN_L"]:5.1f}/{r["DN_R"]:5.1f}Hz  v={vl:+.3f}/{vr:+.3f}")

el = time.perf_counter() - t0
bio = a.ticks * a.brain_ms / 1000
print(f"\n{a.ticks} passos em {el:.1f}s  ({bio:.1f}s de tempo biologico, RT x{bio/el:.2f})")

L = np.array(log)
fig, ax = plt.subplots(3, 1, figsize=(11, 8), sharex=True)
h = L[:, 0]
x = np.arange(len(L)) * DAY_MINUTES / len(L)

for j, (lab, c) in enumerate([("sono", "tab:blue"), ("fome", "tab:orange"),
                              ("alerta", "tab:red"), ("acordado", "tab:green")], start=1):
    ax[0].plot(x, L[:, j], color=c, label=lab, lw=1.5)
ax[0].set_ylabel("estados internos")
ax[0].legend(ncol=4, fontsize=8)
ax[0].set_title(f"moskito — um dia da mosca em {DAY_MINUTES:.0f} min")

ax[1].plot(x, L[:, 5], label="DN esq", lw=1)
ax[1].plot(x, L[:, 6], label="DN dir", lw=1)
ax[1].plot(x, L[:, 7], label="MDN", lw=1, alpha=0.7)
ax[1].set_ylabel("descendentes (Hz)")
ax[1].legend(ncol=3, fontsize=8)

ax[2].plot(x, L[:, 8], label="roda esq", lw=1)
ax[2].plot(x, L[:, 9], label="roda dir", lw=1)
ax[2].axhline(0, color="k", lw=0.5)
ax[2].set_ylabel("velocidade (m/s)")
ax[2].set_xlabel(f"minutos de parede  (0 → 24h da mosca)")
ax[2].legend(ncol=2, fontsize=8)

# Marca as horas do dia da mosca no eixo de cima.
axt = ax[0].twiny()
axt.set_xlim(ax[0].get_xlim())
axt.set_xticks(np.linspace(0, DAY_MINUTES, 7))
axt.set_xticklabels([f"{int(v)}h" for v in np.linspace(h[0], h[0] + 24, 7) % 24])

fig.tight_layout()
fig.savefig(a.out, dpi=130)
print(f"-> {a.out}")
