"""Faixa dinamica dos descendentes e teste de latch.

Responde as tres perguntas que decidem se o modelo presta:
  1. a rede fica numa taxa plausivel (~5-20 Hz) em vez de morrer ou saturar?
  2. looming lateralizado produz assimetria no par DNa02 (steering)?
  3. a atividade DECAI quando o estimulo some, ou a rede latcha?
"""

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from moskito.brain import Brain
from moskito.connectome import load

W, _, P = load()
CONDS = {
    "repouso": {},
    "explorar": {"DNp09": 11.0},
    "fluxo ESQ": {"DNp09": 11.0, "H2_L": 14.0},
    "fluxo DIR": {"DNp09": 11.0, "H2_R": 14.0},
    "loom ESQ": {"DNp09": 11.0, "LPLC2_L": 12.0},
}


def probe(w_syn: float, inj_map: dict) -> tuple[float, dict, float]:
    b = Brain(W, w_syn=w_syn, seed=3)
    inj = np.zeros(b.n, np.float32)
    for k, v in inj_map.items():
        if P.get(k):
            inj[P[k]] = v
    b.run(150.0, inject=inj)                       # warm-up
    b.run(200.0, inject=inj)                       # medida
    net = float(b.rate.mean()) / b.dt * 1000
    dns = {k: b.pop_rate(P.get(k, [])) * 1000 for k in ("DN_L", "DN_R", "MDN")}
    dns["assim"] = ((dns["DN_R"] - dns["DN_L"]) / max(dns["DN_R"] + dns["DN_L"], 1e-9))
    b.run(300.0, inject=None)                      # estimulo removido
    return net, dns, float(b.rate.mean()) / b.dt * 1000


if __name__ == "__main__":
    weights = [float(x) for x in sys.argv[1:]] or [0.6, 0.8, 1.0]
    for w_syn in weights:
        print(f"\n=== w_syn = {w_syn} ===")
        for name, inj_map in CONDS.items():
            net, d, tail = probe(w_syn, inj_map)
            print(f"  {name:<10} rede={net:6.1f}Hz  DN L/R={d['DN_L']:6.2f}/{d['DN_R']:6.2f}  "
                  f"assim={d['assim']:+.3f}  MDN={d['MDN']:5.1f}"
                  f"   -> sem estimulo: {tail:5.1f}Hz")
