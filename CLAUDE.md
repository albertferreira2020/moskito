# moskito

Robô autônomo cujo **steering vem do conectoma real da mosca** (FlyWire FAFB
v783), com os estados internos que o conectoma não contém. Validado no Webots;
alvo final é um ESP32-S3 com câmera para o corpo e o cérebro num Mac M1 Max.

---

## Economia de contexto: o que ler e o que NÃO ler

O código inteiro tem **1.242 linhas**. Os dados têm **245 MB**. Ler os dados
estoura o contexto sem entregar nada.

| Caminho | Tamanho | Ação |
|---|---|---|
| `moskito/*.py` | 714 linhas | **Leia tudo.** É o cérebro inteiro. |
| `webots/moskito_body.py` | 162 | Leia ao mexer em sensor/atuador |
| `scripts/{trace,calibrate}.py` | 121 | Leia ao calibrar |
| `webots/make_world.py`, `run.sh` | 129 | Leia só ao mexer no Webots |
| `data/*.csv` | **245 MB** | **NUNCA leia.** Consulte com pandas num script. |
| `data/brain.npz` | 10 MB | Binário. Use `connectome.load()`. |
| `data/ports.json` | 4.240 índices | Leia só as **chaves**: `python -c "import json;print(list(json.load(open('data/ports.json'))))"` |
| `webots/worlds/*.wbt` | 2.093 linhas | Mobília gerada. Use `grep`/`sed -n`, nunca leia inteiro. |
| `.venv/` | — | Ignore |

**Regra:** para qualquer pergunta sobre o conectoma (quantos neurônios do tipo
X, quem conecta em quem), escreva um script pandas de 5 linhas e leia a saída.
Nunca abra o CSV.

---

## Arquitetura

```mermaid
flowchart TD
    subgraph sensores["Sensores — webots/moskito_body.py"]
        PS["8 sensores de proximidade<br/>limiares do lookupTable"]
        CAM["Câmera 64x48"]
    end

    subgraph estados["Estados internos — drives.py (NÃO estão no conectoma)"]
        DR["circadiano · sono · fome · fadiga<br/>alerta · frustração · social"]
        MB["Corpo cogumelar<br/>novidade de lugar"]
        CX["Compass: bump de rumo<br/>+ menotaxia"]
    end

    subgraph nucleos["Núcleos moduladores — neurônios REAIS do conectoma"]
        CLK["s-LNv · 8 · manhã<br/>LNd · 12 · entardecer<br/>DN1p · 41"]
        OA["OA-VUM/VPM · 17<br/>octopamina"]
        DA["PAM · 307 (novidade)<br/>PPL1 · 16 (punição)"]
        SLP["ER5 + dFB · 160<br/>o freio"]
    end

    subgraph portas["Portas sensoriais do conectoma — body.py"]
        H2["H2 · fluxo óptico<br/>contralateral"]
        LPLC["LPLC2 · looming<br/>fuga, não steering"]
        PFL["PFL3 · rumo<br/>a porta forte"]
        MDN["MDN · marcha ré"]
    end

    TON["aferência tônica CONSTANTE<br/>17.550 mecanossensoriais · 8 mV<br/>NÃO é comando de andar"]

    subgraph rede["brain.py · 139.255 neurônios"]
        FAST["matriz RÁPIDA · 2,66M sinapses<br/>ionotrópica · ms · ACH/GABA/GLUT"]
        MODF["campo MODULADOR · 16.482 arestas<br/>metabotrópico · τ=3 s<br/>704 aminérgicos centrais<br/>→ excitabilidade, não corrente"]
        ADAPT["adaptação lenta · τ=4 s<br/>termina o surto sozinha"]
    end

    DN["população descendente<br/>647 esq / 650 dir"]
    SOMA["SOMA → avanço<br/>piso de recrutamento do VNC"]
    DIF["DIFERENÇA → curva"]
    RODAS["v_esq, v_dir"]

    CAM --> MB --> DR
    CAM -->|camisa vermelha| CX
    PS -->|flow_r - flow_l| CX
    PS --> H2 & LPLC
    DR --> CLK & OA & DA & SLP
    CX -->|erro de rumo + desvio| PFL
    DR -->|frustração| MDN
    CLK & OA & DA & SLP --> FAST
    TON --> FAST
    H2 & LPLC & PFL & MDN --> FAST
    OA & DA & SLP -.->|libera amina| MODF
    MODF -.->|multiplica entrada| FAST
    ADAPT -.->|freia| FAST
    FAST --> DN
    DN --> SOMA & DIF
    SOMA & DIF --> RODAS
    RODAS -.->|ω| CX
```

**A fronteira que importa:** `Body` fala em `(v_esq, v_dir)` e nada mais. O
controller do Webots é um adaptador fino, e o firmware do ESP32-S3 vai ocupar
exatamente o mesmo lugar. Nenhuma decisão mora no controller.

**A segunda fronteira, mais importante:** nenhum estado interno toca motor.
`drives.modulation()` só devolve corrente em mV para núcleos que existem no
FlyWire. A velocidade é lida da taxa de disparo dos descendentes — como um
eletrodo, não como uma escolha do software.

---

## O que é conectoma e o que não é

Ser honesto sobre isso no código e nas mensagens. Não inflar.

- **É conectoma:** todo o steering. Rumo e desvio entram pelo PFL3, propagam
  pela fiação real e saem nos descendentes.
- **É conectoma (novo):** o avanço. Não existe mais `V_CRUISE *
  drive_forward()`. A velocidade é `K_V * max(0, DN_soma - VNC_RECRUIT)`, uma
  leitura da população descendente. Os estados internos só alcançam neurônios
  moduladores identificados; para virar movimento, a excitação tem de
  atravessar a rede.
- **NÃO é conectoma:** os estados internos em si (relógio, sono, fome, fadiga,
  novidade) — o FlyWire dá fiação, não dá dopamina nem relógio. O anel de rumo
  — o `Compass` modela o *resultado* do anel EPG/PEN (fase que integra
  rotação), não a dinâmica de spikes. EPG, PEN e Delta7 estão no conectoma
  (47/24/42 neurônios) e a classe pode ser trocada pela rede real sem mexer no
  resto.
- **NÃO é conectoma, e é a peça honesta que falta:** o piso `VNC_RECRUIT`. O
  FAFB é um conectoma de **cérebro**; o gerador de padrão da marcha fica no
  cordão nervoso ventral, que não está no dataset. O piso modela o
  recrutamento que o VNC faria. É uma retificação contínua, não um `if anda`.

---

## Números medidos (não re-derive)

| Medida | Valor |
|---|---|
| `W_SYN` calibrado | 0,18 (confirmado pela busca) |
| Ponto de operação | `TONIC`=8, `B_SLOW`=0,005, `K_MOD`=1,3 |
| Assimetria DN: PFL3 20 mV | ±0,85 |
| Assimetria DN: H2 40 mV | ±0,23 (satura) |
| Custo do LIF | 15,7 ms de parede por 5 ms biológicos (M1 Max) |
| Simulação resultante | ~1,0× tempo real com passo de 16 ms |
| Velocidade máx. e-puck v2 | 0,154 m/s |
| Cruzeiro medido | 11,2 cm/s |
| Alinhar em 90° | ~2 s, 1,2° residual |
| Corpo cogumelar | 1,00 → 0,011 após 9 visitas |
| Arestas moduladoras (aminérgicos centrais) | 16.482, sobre 704 fontes |
| Alvos do campo modulador | 7.105 (5,1%); DN 19,5%, MDN 100% |
| `DNp09` com aferência tônica | 19,45 Hz (antes: não disparava) |
| DN soma vs tônico mecanossensorial | 8 mV → 0,47 Hz; 11 mV → 1,17 Hz |
| Lateralização PFL3 com rede acordada | faixa 0,62–0,84 (sobrevive) |
| Latch sem adaptação lenta | 2,3 Hz mantidos 10 s após remover OCT |
| Avanço: recém-acordado / explorando | 11,2 / 14,0 cm/s |
| Avanço: saciado, exausto, dormindo | 0,0 cm/s (parado) |
| Sobressalto acorda a mosca | 8,9 cm/s a partir de sono=1,0 |
| Lateralização no ponto final | 0,615–0,790 |
| Sem modulação | 0,000 Hz em 1 s, 2 s e 4 s |

---

## Armadilhas que já custaram caro

1. **Tipos celulares com 1 neurônio por lado saturam.** `DNa02`, `H2`, `DNp09`
   têm um só. Como *leitor* dão sinal binário instável; como *porta de entrada*
   saturam e injetar mais não muda nada. Prefira populações: `DN_L/DN_R` (647/650)
   para ler, `PFL3` (12/lado) para injetar.

2. **Não calibre pela taxa média da rede.** Com `W_SYN = 1.0` ela dava 11 Hz
   "plausíveis" com `i_syn` em −1800 mV contra limiar de 7 mV — regime saturado
   onde a injeção sensorial é irrelevante. Calibre pela **lateralização**
   (`scripts/calibrate.py`).

3. **Antes do spiking, rode `scripts/trace.py`.** Ele mede influência
   lateralizada no grafo em 1,3 s. Se não há caminho lateralizado, nenhum ajuste
   de `W_SYN` vai criar um. Foi assim que descobrimos que LPLC2 era a porta
   errada (fuga, não steering) e H2 a certa.

4. **A rede LATCHA, e nenhum script tinha rodado tempo suficiente para ver.**
   Todo script deste projeto rodava < 1 s (o `W_SYN = 0,18` foi calibrado com
   350 ms). Em 20 s de simulação aparece outra coisa: com tônico de 9 mV e um
   pulso de octopamina de 14 mV a população descendente sobe para ~2,3 Hz e
   **fica lá depois que a octopamina volta a zero** (1,908 Hz dez segundos
   depois). É biestável: OCT ≥ 10 mV é um interruptor de ida, e o ER5/dFB não
   traz de volta nem a 28 mV. Sem adaptação lenta a rede não tem como sair.
   **Regra: qualquer mudança no ponto de operação precisa de um traço de 20 s+,
   não de um `run()` de 300 ms.**

5. **Injetar forte num núcleo modulador o transforma em driver.** Com 34–60 mV
   em centenas de neurônios (limiar 7 mV) os núcleos aminérgicos passam a
   excitar a rede pela matriz *rápida* e afogam a modulação: medimos os quatro
   estados internos convergindo para 2,0–2,3 Hz, indistinguíveis. É a armadilha
   2 noutra roupa. Núcleo modulador quer injeção perto do limiar, não acima.

6. **Predição de neurotransmissor por SINAPSE não serve para achar modulador.**
   Ela marca como aminérgica qualquer sinapse solta de mecanorreceptor
   (BM_InOm), fotorreceptor e ORN — 18.771 "fontes". Isso fecha um laço
   sensorial → excitabilidade → sensorial que se auto-alimenta. Use o NT de
   **consenso do neurônio** (`neurons.csv`) e exija `super_class == central`:
   sobram 704, dominados por PAM (261), PPL1 (16), OA-VUM/VPM (17).

7. **Estado interno com limiar binario em cima do ponto de operacao latcha.**
   A fadiga somava passo fixo quando `drive > DRIVE_WALK` e subtraia abaixo.
   Como `DRIVE_WALK = 0,9` cai exatamente onde a soma descendente opera, o
   bicho oscilava em torno do limiar, a fadiga saturava em **12 s de parede** e
   nunca descarregava: medido em corrida real, fadiga entre 0,80 e 1,00 por
   duas horas de mosca, torneira aminergica a 5%, robo arrastado. Use
   **integrador com vazamento** proporcional ao esforco (`drive - DRIVE_WALK`),
   que vaza sempre e assenta em `esforco * t_down/t_up`.

8. **Aprendizado de uma exposicao quer UMA exposicao.** `mb()` era chamado com
   `learn=True` a cada passo de controle: a ~60 Hz a mesma vista era deprimida
   sessenta vezes por segundo e uma unica revisita derrubava a novidade de
   0,814 para 0,047. Com `nov = 0,00` a via dopaminergica de exploracao
   inteira desliga, e a camera passa a so' agir pelo detector de pessoa.
   Aprenda quando a cena MUDOU (`cam_flow > CAM_STILL`). E o esquecimento e' do
   TEMPO, nao da exposicao -- deixe o `RECOVERY` fora do `if learn`, senao
   parar de aprender para de esquecer.

9. **O infravermelho tem piso ambiente: `psmax` fica em 66-79 sem nada por
   perto.** Dividir por `PS_NEAR` sem subtrair esse piso dava `flow = 0,46` nos
   DOIS lados o tempo todo -- ~19 mV parasitas em cada H2, permanentemente.
   Use banda morta: `(psmax - PS_FLOOR) / (PS_NEAR - PS_FLOOR)`.

10. **Limiares de sensor saem do `lookupTable` do PROTO, não de chute.**
   E-puck: `0mm=4095 5mm=2133 1cm=1466 2cm=384 4cm=158`.

   A terceira coluna do `lookupTable` é **ruído relativo**, e ela invalida o IR
   como medidor de progresso: a 1,5 cm (601 contagens, ruído 0,0406) o desvio
   de uma amostra já é ~24 contagens, e a diferença entre dois passos tem
   desvio ~34. O antigo teste "não mudou" usava limiar 12 sobre o `.max()` dos
   8 sensores — lia ruído puro, o contador de preso zerava toda hora e a
   frustração nunca subia. **Progresso se mede pela câmera**, não pelo IR; do
   IR só sobra o contato (4095 com ruído 0,002 contra limiar 1200), que é
   imune.

11. **Detecção de "não estou saindo do lugar" é cópia eferente × fluxo óptico.**
   Mandei roda e a cena não mudou ⇒ preso, não importa o que o IR diz (debaixo
   da poltrona ele lê 2–5 cm e nunca acusa contato). Comparar com o quadro
   **anterior** não serve: a 11 cm/s são 1,8 mm por passo, deslocamento
   sub-pixel num muro liso, indistinguível de encunhado. A referência visual só
   avança quando a cena mudou de verdade, e `cam_flow` acumula desde a última
   mudança confirmada. Medido: encunhado dispara em 41 passos (~0,66 s) tanto
   em parede texturizada quanto lisa; deslize de 0,05 contagem/passo não
   dispara.

12. **Cena congelada escala direto para ré, sem gastar meia-volta.** Encunhado
   em vão estreito, girar só raspa — `Compass.back_out()` em vez da escalada
   `turn_back` → `turn_back` → ré, que desperdiça 6 s de manobra inútil.

13. **O Webots grava estado dentro do `.wbt`** ao salvar (campos `hidden`,
   posição final). O robô passa a nascer onde travou. Use `make_world.py`.

14. **O `.wbproj` guarda o estado da INTERFACE** e pode conter
   `centralWidgetVisible: 0` ou `renderingMode: WIREFRAME` — a janela abre em
   branco **sem nenhuma mensagem de erro**. Só resolve com o Webots fechado.

15. **Sintoma no simulador ≠ bug no código.** Antes de mexer na lógica, confirme
   que o mundo carrega (`webots --batch --stdout --mode=pause <world>`) e que o
   robô não está preso pela geometria. Já perdemos quatro rodadas por isso.

---

## Comandos

```bash
bash scripts/fetch_data.sh                 # 245 MB do espelho do Codex
.venv/bin/python scripts/build.py          # CSVs -> brain.npz (6 s)
.venv/bin/python scripts/trace.py          # que porta tem influência lateralizada
.venv/bin/python scripts/calibrate.py 0.18 # faixa dinâmica e lateralização
.venv/bin/python scripts/demo.py           # um dia da mosca, sem Webots -> demo.png
```

Webots (o `make_world.py` recusa rodar com o Webots aberto, de propósito):

```bash
pkill -f "Webots.app/Contents/MacOS/webots"
.venv/bin/python webots/make_world.py      # zera mundo E interface
open -a Webots webots/worlds/moskito_apartment.wbt
bash webots/run.sh                         # com a simulação em play
```

---

## Como me pedir trabalho aqui

O que funciona melhor neste projeto, na ordem:

1. **Diga o sintoma observado, não a causa suspeita.** "ele gira devagar perto
   da parede" rendeu mais que "aumente o ganho angular" — a causa real era
   autoridade de curva, não ganho.
2. **Mande o log.** A linha do `run.sh` tem `frust`, `sono`, `psmax`, `DN L/R` e
   `v=`. Com esses cinco dá para localizar o elo quebrado sem adivinhar.
3. **Peça medição antes de correção.** Todo número neste arquivo veio de um
   script que roda em segundos. Chute custa mais caro que medir.
4. **Um sintoma por vez.** Quando dois se misturam (travado + devagar), o
   segundo costuma ser consequência do primeiro.

---

## Estado atual e próximos passos

Funciona: steering pelo conectoma, ciclo circadiano, corpo cogumelar,
frustração → MDN, escalada de fuga (meia-volta → ré reta), busca por pessoa.

A locomoção emergente **fechou**: o avanço sai da população descendente, os
estados internos separam comportamento (11,2 cm/s acordado, 0,0 dormindo), não
há latch e a lateralização sobrevive. Ponto achado por `scripts/search.py`.

A hipótese antiga ("falta drive sensorial distribuído") **estava certa** e foi
confirmada: com aferência tônica nos 17.550 mecanossensoriais o `DNp09` dispara
a 19,45 Hz e a população descendente responde de forma graduada. A arquitetura
de avanço emergente está implementada (matriz moduladora, campo de
excitabilidade, leitura soma/diferença).

Aberto, em ordem de valor:

1. **Trocar o `Compass` pela rede EPG/PEN/Delta7 real.**
2. **Porta olfativa de verdade.** O "cheiro" da base entra pelas LC11; falta
   resolver os ORNs do lobo antenal.
3. **Validar no Webots.** A calibração é do cérebro isolado; falta o robô no
   apartamento com o laço sensorial fechado.
4. **Escala:** o e-puck tem 7 cm num apartamento real e encunha em vãos que um
   robô doméstico nem notaria. Decisão consciente de manter, não descuido.

## Dados

FlyWire FAFB v783 sob **CC BY-NC 4.0** — uso não comercial. Citação em
<https://flywire.ai/guidelines>. CSVs não versionados.
