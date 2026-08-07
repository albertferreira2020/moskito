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
NT_SIGN = {"ACH": 1.0, "GABA": -1.0, "GLUT": -1.0, "DA": 0.0, "SER": 0.0, "OCT": 0.0}

# Segunda matriz: as arestas moduladoras que a matriz rapida descarta. Elas NAO
# carregam comando -- os receptores de amina biogenica sao metabotropicos
# (GPCR), agem em segundos e mudam a EXCITABILIDADE do alvo em vez de
# despolariza-lo. Por isso entram num campo lento separado (brain.py) e nao na
# corrente sinaptica.
#
# O criterio e' o NT de consenso do neuronio PRE, e o neuronio precisa ser
# central. Usar a predicao por SINAPSE nao funciona: ela marca como aminergica
# qualquer sinapse solta de mecanorreceptor (BM_InOm), fotorreceptor e ORN, e
# medimos o estrago -- com 18.771 fontes o campo virava um laco
# sensorial -> excitabilidade -> sensorial que se auto-alimentava, e o estado
# "saciado/tedio", que deveria ficar parado, andava 70,5% do tempo.
# Restringindo a 704 neuronios centrais de consenso aminergico sobram os
# nucleos de verdade: PAM (261), PPL1 (16), OA-VUM/VPM (17), PPM12 (12).
# O relogio nao aparece aqui de proposito -- s-LNv e' peptidergico (PDF) e LNd
# glutamatergico, entao o relogio age pela matriz RAPIDA, como deve.
#   OCT +1  octopamina: o sinal de "estar ativo". Aumenta ganho sensorial e
#           sustenta locomocao (Suver 2012; Schretter 2020).
#   DA  +1  dopamina: engajamento/vigor e persistencia do estado motor.
#   SER -1  serotonina: promove quiescencia e LENTIFICA a caminhada em
#           Drosophila (Howard 2019); e' o freio, nao o acelerador.
MOD_SIGN = {"OCT": 1.0, "DA": 1.0, "SER": -1.0}

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

# Portas MODULADORAS: onde os estados internos entram no conectoma. Nenhuma
# delas manda em motor -- todas injetam corrente em neuronios reais, e o efeito
# no comportamento sai da fiacao. Sao os nucleos que a literatura identifica
# como geradores dos estados que o conectoma nao contem.
#   CLOCK_M  s-LNv, marca-passo de PDF: pico locomotor da manha (Grima 2004)
#   CLOCK_E  LNd: pico do entardecer -- juntos dao a atividade bimodal
#   CLOCK_D  DN1p/DN2/LPN: integradores dorsais, saida do relogio p/ arousal
#   SLEEP    ER5 (R5) + dFB (FB6/FB7): homeostato de sono. R5 acumula pressao
#            com a vigilia (Liu 2016; Raccuglia 2019); o dFB e' o interruptor
#            de sono (Donlea 2011). Sao o FREIO da locomocao.
#   DA_REW   PAM: dopamina de recompensa/novidade -- vigor e exploracao
#   DA_PUN   PPL1: dopamina de punicao -- aversao, empurra evitacao
#   OCT      OA-VUM/VPM: octopamina. O sinal de "iniciar e sustentar atividade"
#            (Schretter 2020: octopamina promove locomocao em Drosophila)
PORT_GROUPS = {
    "CLOCK_M": r"^s-LNv$",
    "CLOCK_E": r"^LNd",
    "CLOCK_D": r"^DN1p|^DN1a$|^DN2$|^LPN$",
    "SLEEP":   r"^ER5$|^FB6|^FB7",
    "DA_REW":  r"^PAM",
    "DA_PUN":  r"^PPL10",
    "OCT":     r"^OA-VUM|^OA-VPM",
    "MBON":    r"^MBON",
    "DNa":     r"^DNa0",
}


def build(data_dir: str | Path = "data", out: str | Path = "data/brain.npz") -> dict:
    data_dir, out = Path(data_dir), Path(out)

    conn = pd.read_csv(
        data_dir / "connections.csv",
        usecols=["pre_root_id", "post_root_id", "syn_count", "nt_type"],
        dtype={"pre_root_id": np.int64, "post_root_id": np.int64, "syn_count": np.int32},
    )
    print(f"arestas brutas: {len(conn):,}")
    print(conn.nt_type.value_counts().to_string())

    nt = conn.nt_type.str.upper()
    # Indice global: todo neuronio do dataset, mesmo os sem aresta.
    cls = pd.read_csv(data_dir / "classification.csv", usecols=["root_id", "super_class", "side"])
    root_ids = np.sort(cls.root_id.unique())
    pos = pd.Series(np.arange(len(root_ids), dtype=np.int32), index=root_ids)
    n = len(root_ids)

    def matrix(sign: np.ndarray, label: str) -> csr_matrix:
        weight = conn.syn_count.to_numpy(np.float32) * sign
        keep = weight != 0.0
        pre = pos.reindex(conn.pre_root_id[keep]).to_numpy()
        post = pos.reindex(conn.post_root_id[keep]).to_numpy()
        wt = weight[keep]
        ok = ~(np.isnan(pre) | np.isnan(post))
        m = csr_matrix((wt[ok], (pre[ok].astype(np.int32), post[ok].astype(np.int32))),
                       shape=(n, n), dtype=np.float32)
        m.sum_duplicates()
        print(f"{label}: {m.nnz:,} nao-zeros, {m.data.nbytes / 2**20:.0f} MB")
        return m

    w = matrix(nt.map(NT_SIGN).fillna(0.0).to_numpy(np.float32),
               "matriz rapida (ACH/GABA/GLUT, por sinapse)")

    # Moduladora: sinal pelo NT de CONSENSO do neuronio pre-sinaptico, e so'
    # para neuronios centrais -- um nucleo aminergico e' central por definicao.
    neu = pd.read_csv(data_dir / "neurons.csv", usecols=["root_id", "nt_type"])
    neu = neu.merge(cls[["root_id", "super_class"]], on="root_id", how="left")
    amin = neu[neu.nt_type.isin(MOD_SIGN) & (neu.super_class == "central")]
    print(f"fontes aminergicas centrais: {len(amin):,} "
          f"({dict(amin.nt_type.value_counts())})")
    src = pd.Series(amin.nt_type.map(MOD_SIGN).to_numpy(np.float32), index=amin.root_id)
    mod = matrix(src.reindex(conn.pre_root_id).fillna(0.0).to_numpy(np.float32),
                 "matriz moduladora (aminergicos centrais)")

    ports = _resolve_ports(data_dir, cls, pos)
    np.savez_compressed(
        out,
        indptr=w.indptr, indices=w.indices, data=w.data, root_ids=root_ids,
        mod_indptr=mod.indptr, mod_indices=mod.indices, mod_data=mod.data,
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

    # Portas moduladoras, por expressao regular sobre o tipo primario.
    pt = types.primary_type.astype(str)
    for name, pat in PORT_GROUPS.items():
        sel = types[pt.str.match(pat, na=False)]
        ports[name] = pos.reindex(sel.root_id).dropna().astype(int).tolist()
        print(f"  {name}: {len(ports[name])} neuronios ({sel.primary_type.nunique()} tipos)")

    # SENSORY/OPTIC nao entram aqui de proposito: sao 103 mil indices e sairiam
    # do super_class de qualquer jeito. `load()` os deriva do npz.
    return ports


def load(path: str | Path = "data/brain.npz") -> tuple[csr_matrix, csr_matrix, np.ndarray, dict]:
    """Devolve (rapida, moduladora, root_ids, portas)."""
    path = Path(path)
    z = np.load(path, allow_pickle=False)
    n = len(z["root_ids"])
    w = csr_matrix((z["data"], z["indices"], z["indptr"]), shape=(n, n))
    if "mod_data" not in z:
        raise SystemExit(f"{path} e' de uma versao anterior (sem matriz moduladora). "
                         "Rode: .venv/bin/python scripts/build.py")
    mod = csr_matrix((z["mod_data"], z["mod_indices"], z["mod_indptr"]), shape=(n, n))
    ports = json.loads((path.parent / "ports.json").read_text())

    # O canal aferente tonico: mecanorreceptores e propriorreceptores disparam o
    # tempo todo na mosca acordada. NAO e' comando de andar -- e' o piso
    # aferente sobre o qual a modulacao age. Derivado aqui em vez de gravado:
    # sao 103 mil indices que sairiam do super_class de qualquer jeito.
    sc = z["super_class"]
    for name, classes in (("SENSORY", ("sensory", "sensory_ascending")),
                          ("OPTIC", ("optic", "visual_projection"))):
        ports[name] = np.flatnonzero(np.isin(sc, classes)).tolist()
    return w, mod, z["root_ids"], ports
