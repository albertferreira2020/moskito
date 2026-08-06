# moskito

Um robô autônomo cujo cérebro é o conectoma real da mosca (FlyWire FAFB v783),
com os estados internos que o conectoma **não** contém.

Alvo final: robô físico com ESP32-S3 (corpo e reflexos) + cérebro rodando num
Mac M1 Max. Antes disso, tudo é validado no Webots com um apartamento simulado.

## Ideia

O conectoma dá a **fiação**: 139.255 neurônios, 2,66M conexões assinadas pelo
neurotransmissor previsto. Ele não dá dopamina, octopamina, NPF nem relógio
circadiano — e são esses sistemas, agindo por cima da fiação, que produzem
"acordar, explorar, cansar, procurar comida".

Então o projeto é feito de duas metades:

```
conectoma FlyWire   ->  moskito/connectome.py + brain.py   (a fiação, baixada)
estados internos    ->  moskito/drives.py                  (5 escalares, escritos)
portas I/O          ->  moskito/body.py                    (sensores <-> rodas)
```

**Portas.** O cérebro da mosca tem entradas e saídas nomeadas, e é por elas que
o robô se conecta — não se injeta pixel em fotorreceptor:

| Porta | Papel | Neurônios |
|---|---|---|
| `LPLC2_L/R` | looming (obstáculo se aproximando) | 108 / 102 |
| `LC11_L/R` | objeto pequeno em movimento | 66 / 61 |
| `DN_L/R` | população descendente = barramento motor | 647 / 650 |
| `MDN` | marcha ré (moonwalker) | 4 |
| `DNa02_L/R` | steering — **1 neurônio por lado** | 1 / 1 |

## Rodando

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
bash scripts/fetch_data.sh     # ~55 MB do espelho público do Codex
.venv/bin/python scripts/build.py       # CSVs -> data/brain.npz (~6 s)
.venv/bin/python scripts/calibrate.py   # faixa dinâmica e teste de latch
.venv/bin/python scripts/demo.py        # um dia da mosca em 20 min -> demo.png
```

## Estado atual

**Funciona:**

- Pipeline completo: CSV → matriz esparsa assinada → LIF → rodas.
- Runtime LIF orientado a eventos, ~0,18× tempo real no M1 Max (400 passos de
  controle com 10 ms biológicos cada em 22 s). Suficiente para um loop de
  decisão a ~7 Hz; reflexos ficam locais, nunca aqui.
- Rede numa faixa fisiologicamente plausível (~5–11 Hz médios), sem morrer nem
  saturar, graças à adaptação de frequência (`B_ADAPT`).
- O ciclo circadiano + pressão de sono produzem o padrão certo: ativo ao
  amanhecer e ao entardecer, quase parado de madrugada.

**Não funciona ainda — é o próximo trabalho real:**

- **A resposta lateralizada a looming é fraca.** Injetando nas LPLC2 de um lado,
  a assimetria normalizada da população descendente muda só ~0,08, e existe um
  viés de repouso (`TURN_BIAS`) da mesma ordem que precisa ser subtraído. O
  sinal diferencial tem a direção certa mas não é forte o bastante para dirigir.
- **`DNp09` fica mudo** mesmo com injeção direta acima do limiar — provavelmente
  inibição da rede. Por isso o avanço é lido da população descendente inteira, e
  não dele.
- Não há porta olfativa de verdade: o "cheiro" da base entra pelas LC11. Falta
  resolver os ORNs do lobo antenal.
- Sem complexo central (heading / ring attractor) nem corpo cogumelar
  (familiaridade de lugar). `novelty` hoje é um seno sintético no demo.
- Sem Webots ainda. O `Body` já fala em `(v_esq, v_dir)` para plugar direto.

**Parâmetros de calibração** (nada disso vem dos CSVs — o conectoma dá anatomia,
não fisiologia): `W_SYN`, `V_TH`, `TAU_M`, `TAU_SYN`, `B_ADAPT` em `brain.py`;
`K_LINEAR`, `K_ANGULAR`, `TURN_BIAS` em `body.py`. `W_SYN` é de longe o mais
sensível.

## Tempo comprimido

Um dia da mosca = 20 minutos de relógio de parede (`DAY_MINUTES` em
`drives.py`), fator 72×. Dá para ver o ciclo sono/vigília inteiro numa sessão.
O tempo biológico do cérebro e o tempo dos estados internos são escalas
separadas de propósito: o cérebro é o processo rápido, os estados são o
envelope lento.

## Dados

FlyWire FAFB v783, baixado do espelho público do Codex. Licença **CC BY-NC 4.0**
— uso não comercial. Citação conforme <https://flywire.ai/guidelines>.
Os CSVs não são versionados (~230 MB); use `scripts/fetch_data.sh`.
