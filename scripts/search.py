"""Busca do ponto de operacao do avanco emergente.

Quatro parametros acoplados, e nenhum deles pode ser calibrado sozinho:

  W_SYN   escala da sinapse rapida -- mexe em TUDO, inclusive na lateralizacao
  TONIC   aferencia mecanossensorial de fundo -- o piso sobre o qual se modula
  B_SLOW  adaptacao lenta -- e' o que impede o latch, mas demais mata a rede
  K_MOD   alcance do campo modulador -- quanto o estado interno consegue mudar

O objetivo tem quatro termos, e o ponto so' presta se passar nos quatro:

  1. SEPARACAO   explorando tem de disparar bem mais que dormindo
  2. PARADA      dormindo tem de ficar abaixo do piso de recrutamento
  3. SEM LATCH   tirado o estimulo, a rede volta ao basal em segundos
  4. LATERAL     a assimetria do PFL3 sobrevive com a rede acordada

Duas etapas de proposito: a etapa 1 e' barata e mata a maioria dos candidatos;
so' os sobreviventes pagam o traco longo de latch e o teste de lateralizacao.
Sem isso a busca inteira levaria dez horas em vez de meia.

    .venv/bin/python scripts/search.py            # grade completa
    .venv/bin/python scripts/search.py --quick    # grade reduzida, ~5 min
    .venv/bin/python scripts/search.py --jobs 4
"""

from __future__ import annotations

import argparse
import csv
import itertools
import sys
import time
from multiprocessing import Pool
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

RAIZ = Path(__file__).resolve().parents[1]
NPZ = RAIZ / "data/brain.npz"
SAIDA = RAIZ / "data/search.csv"

# Estados que precisam ficar em pontos opostos. Se estes dois nao separam,
# nenhum outro separa.
MOTIVADO = dict(hour=7.0, sleep=0.0, hunger=0.8, novelty=1.0)
DORMINDO = dict(hour=2.0, sleep=1.0, hunger=0.4, novelty=0.5, fatigue=0.9)

# Criterios de aprovacao na etapa 1.
LO_MAX = 0.90       # Hz: dormindo tem de ficar abaixo disto
HI_MIN = 1.60       # Hz: explorando tem de passar disto
SEP_MIN = 0.80      # Hz: separacao minima que vale investigar

_G: dict = {}


def _init(path: str):
    from moskito.connectome import load
    W, MOD, _, P = load(path)
    _G["W"], _G["MOD"] = W, MOD
    _G["P"] = {k: np.asarray(v, dtype=np.int32) for k, v in P.items()}


def _aplica(w_syn, tonic, b_slow, k_mod):
    """Instala os parametros nos modulos. Sao lidos como globais em tempo de uso."""
    import moskito.brain as B
    import moskito.drives as D
    B.B_SLOW, B.K_MOD, D.TONIC = b_slow, k_mod, tonic
    return w_syn


def _corre(w_syn, estado, secs, pfl=None, seed=3, oct_off_em=None):
    """Roda o cerebro com um estado interno. Devolve o traco de DN soma (Hz)."""
    from moskito.brain import Brain
    from moskito.drives import Drives
    P = _G["P"]
    b = Brain(_G["W"], _G["MOD"], w_syn=w_syn, seed=seed)
    d = Drives(**estado)

    def injecao(sem_oct=False):
        v = np.zeros(b.n, np.float32)
        for k, mv in d.modulation().items():
            if mv and k in P and len(P[k]) and not (sem_oct and k == "OCT"):
                v[P[k]] += mv
        if pfl:
            v[P["PFL3_L"]] += pfl[0]
            v[P["PFL3_R"]] += pfl[1]
        return v

    inj, inj_off = injecao(), injecao(sem_oct=True)
    n_off = int(oct_off_em * 200) if oct_off_em else None
    a, dl_dr = [], []
    for i in range(int(secs * 200)):          # 200 passos de 5 ms por segundo
        b.run(5.0, inject=inj if n_off is None or i < n_off else inj_off, noise=0.02)
        l, r = b.pop_rate(P["DN_L"]) * 1000, b.pop_rate(P["DN_R"]) * 1000
        a.append(l + r)
        dl_dr.append((l, r))
    return np.array(a), np.array(dl_dr)


def etapa1(args) -> dict:
    """Barato: separacao entre motivado e dormindo, mais deriva como pista de latch."""
    w_syn, tonic, b_slow, k_mod = args
    _aplica(w_syn, tonic, b_slow, k_mod)
    t0 = time.time()
    out = {"w_syn": w_syn, "tonic": tonic, "b_slow": b_slow, "k_mod": k_mod}
    for nome, estado in (("hi", MOTIVADO), ("lo", DORMINDO)):
        a, _ = _corre(w_syn, estado, secs=12.0)
        out[nome] = float(a[-int(len(a) * 0.4):].mean())
        # deriva: se o fim e' muito maior que o meio, esta' subindo sozinho
        meio = float(a[int(len(a) * .4):int(len(a) * .6)].mean())
        out[f"{nome}_deriva"] = out[nome] - meio
    out["sep"] = out["hi"] - out["lo"]
    out["passa"] = int(out["lo"] < LO_MAX and out["hi"] > HI_MIN and out["sep"] > SEP_MIN)
    out["s"] = round(time.time() - t0, 1)
    return out


def etapa2(args) -> dict:
    """Caro: latch de verdade (20 s com a octopamina caindo) e lateralizacao."""
    w_syn, tonic, b_slow, k_mod = args
    _aplica(w_syn, tonic, b_slow, k_mod)
    t0 = time.time()
    out = {"w_syn": w_syn, "tonic": tonic, "b_slow": b_slow, "k_mod": k_mod}

    # LATCH: 8 s motivado, depois a octopamina sai. Volta ao basal?
    a, _ = _corre(w_syn, MOTIVADO, secs=20.0, oct_off_em=8.0)
    com = float(a[int(6 * 200):int(8 * 200)].mean())
    depois = float(a[-int(2 * 200):].mean())
    out["com_oct"], out["pos_oct"] = com, depois
    out["latch"] = int(depois > 0.6 * com)

    # LATERALIZACAO: o PFL3 ainda desequilibra os descendentes acordado?
    lados = []
    for pfl in ((26.0, 10.0), (10.0, 26.0)):
        _, dd = _corre(w_syn, MOTIVADO, secs=6.0, pfl=pfl)
        dl, dr = dd[-int(len(dd) * .4):].mean(axis=0)
        lados.append((dr - dl) / max(dr + dl, 1e-9))
    out["assim_p"], out["assim_n"] = lados
    out["faixa"] = lados[0] - lados[1]
    out["ok"] = int(not out["latch"] and out["faixa"] > 0.40)
    out["s"] = round(time.time() - t0, 1)
    return out


def grade(quick: bool):
    if quick:
        return list(itertools.product([0.18], [9.0, 11.0], [0.01, 0.03], [1.3, 2.5]))
    return list(itertools.product(
        [0.14, 0.18, 0.22],            # W_SYN
        [8.0, 9.0, 10.0, 11.0],        # TONIC
        [0.005, 0.01, 0.02, 0.04],     # B_SLOW
        [1.3, 2.5],                    # K_MOD
    ))


def roda(fase, combos, jobs, campos):
    linhas = []
    with Pool(jobs, initializer=_init, initargs=(str(NPZ),)) as pool:
        for i, r in enumerate(pool.imap_unordered(fase, combos), 1):
            linhas.append(r)
            print(f"[{i:3d}/{len(combos)}] " +
                  "  ".join(f"{k}={r[k]:g}" if isinstance(r[k], float) else f"{k}={r[k]}"
                            for k in campos), flush=True)
    return linhas


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--quick", action="store_true")
    p.add_argument("--jobs", type=int, default=6)
    a = p.parse_args()

    combos = grade(a.quick)
    t0 = time.time()
    print(f"=== etapa 1: {len(combos)} pontos, {a.jobs} processos ===", flush=True)
    r1 = roda(etapa1, combos, a.jobs,
              ("w_syn", "tonic", "b_slow", "k_mod", "hi", "lo", "sep", "passa"))

    r1.sort(key=lambda r: -r["sep"])
    vivos = [r for r in r1 if r["passa"]]
    print(f"\n--- etapa 1: {len(vivos)} de {len(r1)} passam "
          f"(lo<{LO_MAX} e hi>{HI_MIN} e sep>{SEP_MIN}) ---", flush=True)
    for r in r1[:10]:
        print(f"  w_syn={r['w_syn']:.2f} tonic={r['tonic']:.0f} b_slow={r['b_slow']:.3f} "
              f"k_mod={r['k_mod']:.1f} | hi={r['hi']:.3f} lo={r['lo']:.3f} "
              f"sep={r['sep']:+.3f} {'PASSA' if r['passa'] else ''}", flush=True)

    r2 = []
    if vivos:
        # TODOS os sobreviventes, nao os N com maior separacao. Ordenar por
        # separacao enviesa para `hi` alto, e `hi` alto e' justamente o que
        # latcha: na primeira rodada isso descartou em silencio o grupo
        # w_syn=0,14 com b_slow alto, que era o unico candidato plausivel.
        alvo = [(r["w_syn"], r["tonic"], r["b_slow"], r["k_mod"]) for r in vivos[:36]]
        print(f"\n=== etapa 2: {len(alvo)} sobreviventes (latch + lateralizacao) ===",
              flush=True)
        r2 = roda(etapa2, alvo, min(a.jobs, len(alvo)),
                  ("w_syn", "tonic", "b_slow", "k_mod", "com_oct", "pos_oct",
                   "latch", "faixa", "ok"))
        r2.sort(key=lambda r: (-r["ok"], -r["faixa"]))
        print("\n--- veredito ---", flush=True)
        for r in r2:
            print(f"  w_syn={r['w_syn']:.2f} tonic={r['tonic']:.0f} "
                  f"b_slow={r['b_slow']:.3f} k_mod={r['k_mod']:.1f} | "
                  f"latch={'SIM' if r['latch'] else 'nao'} faixa={r['faixa']:.3f} "
                  f"{'<-- SERVE' if r['ok'] else ''}", flush=True)

    with SAIDA.open("w", newline="") as f:
        cols = sorted({k for r in r1 + r2 for k in r})
        wtr = csv.DictWriter(f, fieldnames=cols)
        wtr.writeheader()
        wtr.writerows(r1 + r2)
    print(f"\n-> {SAIDA}   ({time.time() - t0:.0f}s)", flush=True)
