"""Conectoma FlyWire (FAFB v783) -> matriz esparsa assinada.

A matriz e' guardada em CSR indexada por PRE (linha = neuronio pre-sinaptico),
porque o runtime propaga eventos: dado o conjunto de neuronios que dispararam,
ele precisa das arestas de SAIDA deles.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.sparse import csr_matrix

# Sinal sinaptico a partir do neurotransmissor previsto.
# Em Drosophila, glutamato e' majoritariamente inibitorio (receptores GluCl).
# Os moduladores nao sao conexoes ponto-a-ponto: eles viram os estados internos
# em drives.py, entao saem da matriz.
NT_SIGN = {"ACH": 1.0, "GABA": -1.0, "GLUT": -1.0, "DA": 0.0, "SER": 0.0, "OCT": 0.0}

# Portas de entrada e saida do cerebro.
# Saida: neuronios descendentes (o barramento motor da mosca).
# Entrada: H2 e HS sao celulas tangenciais da placa lobular -- fluxo optico
# horizontal, a via de virada. H2 projeta CONTRALATERAL (scripts/trace.py mede
# assimetria +0.60), entao estimulo a esquerda vira para a direita: desvio.
# LPLC2/LC4 sao looming -> fibra gigante -> fuga, NAO steering: influencia nos
# descendentes 60x menor que H2 e do lado errado. Ficam como canal de parada.
# PFL3 e' a saida de steering do complexo central: compara a direcao atual
# (bump dos EPG) com a direcao-objetivo e desequilibra os descendentes para
# anular o erro. E' o que faz a mosca ter RUMO em vez de so' reagir.
PORT_TYPES = ("DNa02", "DNa01", "DNp09", "MDN",
              "H2", "HSE", "HSN", "HSS",
              "PFL3", "PFL2", "EPG",
              "LPLC2", "LC4", "LC11", "LC6", "LC16")


def build(data_dir: str | Path = "data", out: str | Path = "data/brain.npz") -> dict:
    data_dir, out = Path(data_dir), Path(out)

    conn = pd.read_csv(
        data_dir / "connections.csv",
        usecols=["pre_root_id", "post_root_id", "syn_count", "nt_type"],
        dtype={"pre_root_id": np.int64, "post_root_id": np.int64, "syn_count": np.int32},
    )
    print(f"arestas brutas: {len(conn):,}")
    print(conn.nt_type.value_counts().to_string())

    sign = conn.nt_type.str.upper().map(NT_SIGN).fillna(0.0).to_numpy(np.float32)
    weight = conn.syn_count.to_numpy(np.float32) * sign

    keep = weight != 0.0
    conn, weight = conn[keep], weight[keep]
    print(f"arestas com sinal: {len(conn):,}  ({(~keep).sum():,} moduladoras descartadas)")

    # Indice global: todo neuronio do dataset, mesmo os sem aresta.
    cls = pd.read_csv(data_dir / "classification.csv", usecols=["root_id", "super_class", "side"])
    root_ids = np.sort(cls.root_id.unique())
    pos = pd.Series(np.arange(len(root_ids), dtype=np.int32), index=root_ids)

    pre = pos.reindex(conn.pre_root_id).to_numpy()
    post = pos.reindex(conn.post_root_id).to_numpy()
    ok = ~(np.isnan(pre) | np.isnan(post))
    pre, post, weight = pre[ok].astype(np.int32), post[ok].astype(np.int32), weight[ok]

    n = len(root_ids)
    w = csr_matrix((weight, (pre, post)), shape=(n, n), dtype=np.float32)
    w.sum_duplicates()
    print(f"matriz: {n:,} x {n:,}, {w.nnz:,} nao-zeros, {w.data.nbytes / 2**20:.0f} MB")

    ports = _resolve_ports(data_dir, cls, pos)
    np.savez_compressed(
        out,
        indptr=w.indptr, indices=w.indices, data=w.data, root_ids=root_ids,
        super_class=cls.set_index("root_id").super_class.reindex(root_ids).fillna("").to_numpy(str),
    )
    (out.parent / "ports.json").write_text(json.dumps(ports, indent=2))
    print(f"-> {out}  +  {out.parent / 'ports.json'}")
    return ports


def _resolve_ports(data_dir: Path, cls: pd.DataFrame, pos: pd.Series) -> dict[str, list[int]]:
    """root_id -> indice, agrupado por tipo celular e lado."""
    types = pd.read_csv(data_dir / "consolidated_cell_types.csv", usecols=["root_id", "primary_type"])
    types = types.merge(cls[["root_id", "side"]], on="root_id", how="left")

    ports: dict[str, list[int]] = {}
    for t in PORT_TYPES:
        sel = types[types.primary_type == t]
        if sel.empty:
            print(f"  ! {t}: nao encontrado em consolidated_cell_types")
            continue
        for side, tag in (("left", "L"), ("right", "R")):
            idx = pos.reindex(sel[sel.side == side].root_id).dropna().astype(int).tolist()
            if idx:
                ports[f"{t}_{tag}"] = idx
        ports[t] = pos.reindex(sel.root_id).dropna().astype(int).tolist()
        print(f"  {t}: {len(ports[t])} neuronios")

    # Tipos como DNa02 tem UM neuronio por lado -- leitor binario e instavel.
    # A populacao descendente inteira (~1300) da um sinal de steering com media.
    desc = cls[cls.super_class == "descending"]
    for side, tag in (("left", "L"), ("right", "R")):
        ports[f"DN_{tag}"] = pos.reindex(desc[desc.side == side].root_id).dropna().astype(int).tolist()
    ports["DN"] = pos.reindex(desc.root_id).dropna().astype(int).tolist()
    print(f"  descendentes: {len(ports['DN_L'])} esq / {len(ports['DN_R'])} dir")
    return ports


def load(path: str | Path = "data/brain.npz") -> tuple[csr_matrix, np.ndarray, dict]:
    path = Path(path)
    z = np.load(path, allow_pickle=False)
    n = len(z["root_ids"])
    w = csr_matrix((z["data"], z["indices"], z["indptr"]), shape=(n, n))
    ports = json.loads((path.parent / "ports.json").read_text())
    return w, z["root_ids"], ports
