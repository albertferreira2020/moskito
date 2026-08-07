"""Qual porta de entrada tem influencia LATERALIZADA nos descendentes?

Propagacao linear assinada no grafo, normalizada pelo total de entrada de cada
neuronio (cada linha vira "fracao da entrada"). Responde em segundos o que o
spiking levaria minutos para responder: se nao ha caminho lateralizado no grafo,
nenhuma calibracao de W_SYN vai criar um.

Indice de assimetria: (influencia em DN_R - em DN_L) / (soma). Estimulando o
lado ESQUERDO, um steering contralateral saudavel da' indice POSITIVO.
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.sparse import csr_matrix

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from moskito.connectome import load

HOPS = 5
SOURCES = ["LPLC2", "LPLC1", "LC4", "LC6", "LC11", "LC16", "LC18",
           "HSE", "HSN", "HSS", "H2", "VS1", "PFL3", "PFL2"]


def side_index(data_dir="data") -> dict[str, pd.DataFrame]:
    t = pd.read_csv(f"{data_dir}/consolidated_cell_types.csv", usecols=["root_id", "primary_type"])
    c = pd.read_csv(f"{data_dir}/classification.csv", usecols=["root_id", "super_class", "side"])
    return t.merge(c, on="root_id")


def normalize(w: csr_matrix) -> csr_matrix:
    """Cada neuronio pos-sinaptico recebe peso total 1 (em modulo)."""
    col = np.asarray(abs(w).sum(axis=0)).ravel()
    col[col == 0] = 1.0
    n = w.copy().tocsr()
    n.data = n.data / col[n.indices]
    return n


if __name__ == "__main__":
    w, mod, root_ids, ports = load()
    meta = side_index()
    pos = pd.Series(np.arange(len(root_ids)), index=root_ids)
    wn = normalize(w)

    dn_l, dn_r = np.array(ports["DN_L"]), np.array(ports["DN_R"])
    print(f"{'fonte(esq)':<10}{'n':>4} {'->DN_L':>9}{'->DN_R':>9}{'assim':>8}  por hop")
    for name in SOURCES:
        sel = meta[(meta.primary_type == name) & (meta.side == "left")]
        idx = pos.reindex(sel.root_id).dropna().astype(int).to_numpy()
        if idx.size == 0:
            continue

        x = np.zeros(w.shape[0], dtype=np.float64)
        x[idx] = 1.0 / idx.size
        acc_l = acc_r = 0.0
        per_hop = []
        for _ in range(HOPS):
            x = x @ wn
            l, r = float(np.abs(x[dn_l]).sum()), float(np.abs(x[dn_r]).sum())
            acc_l, acc_r = acc_l + l, acc_r + r
            per_hop.append((r - l) / (r + l) if (r + l) > 1e-12 else 0.0)

        asym = (acc_r - acc_l) / (acc_r + acc_l) if (acc_r + acc_l) > 1e-12 else 0.0
        hops = " ".join(f"{v:+.2f}" for v in per_hop)
        print(f"{name:<10}{idx.size:>4} {acc_l:9.4f}{acc_r:9.4f}{asym:+8.3f}  {hops}")
