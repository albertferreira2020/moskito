# Changelog

Não há tags no repositório até aqui; esta é a primeira versão numerada, e a
numeração começa em 0.3.0 por convenção — 0.1 foi o conectoma rodando, 0.2 o
steering validado no Webots.

## 0.3.0 — 2026-08-07

### Locomoção emergente: o avanço sai do conectoma

Até aqui o robô andava porque o software mandava: `V_CRUISE * drive_forward()`
em `body.py`, mais uma injeção de 11 mV direto no `DNp09` — o descendente de
caminhada — proporcional a um escalar de "curiosidade". O steering vinha do
conectoma; o avanço, não. Esta versão remove os dois.

**A velocidade agora é uma leitura da rede, não uma escolha.** A mesma
população descendente dá as duas coisas:

```
forward = K_V * max(0, (DN_L + DN_R) - VNC_RECRUIT)   # modo comum
turn    = f((DN_R - DN_L) / (DN_R + DN_L))            # modo diferencial
```

Nenhum estado interno alcança motor. `Drives.modulation()` devolve apenas
corrente em mV para núcleos que existem no FlyWire, e a excitação tem de
atravessar 139.255 neurônios para virar movimento. Se a rede está quieta, o
robô fica parado e não há como contornar isso pelo software.

### Adicionado

- **Segunda matriz no conectoma: o campo modulador.** As arestas
  DA/SER/OCT eram descartadas no `build`. Agora viram uma matriz separada
  (16.482 arestas, 704 fontes) que **não injeta corrente** — receptor de amina
  biogênica é metabotrópico, age em segundos e muda a *excitabilidade* do alvo.
  Vira um campo lento (`Brain.exc`, τ = 3 s) que multiplica a corrente de
  entrada. É esse τ que dá persistência e integração temporal, no lugar de
  qualquer temporizador.
- **Portas moduladoras** (`PORT_GROUPS` em `connectome.py`): s-LNv (8), LNd
  (12), DN1p (41), OA-VUM/VPM (17), PAM (307), PPL1 (16), ER5+dFB (160). Cada
  estado interno injeta no núcleo que a literatura associa a ele.
- **Aferência tônica constante** nos 17.550 mecanossensoriais. Não é comando de
  andar: é o piso aferente sobre o qual a modulação age, e é o que faltava —
  com ele o `DNp09` passa a disparar a 19,45 Hz, contra "não dispara nem com
  injeção acima do limiar" na versão anterior.
- **Adaptação lenta** (`TAU_SLOW` = 4 s, `B_SLOW`) no LIF: correntes de K⁺
  dependentes de Ca²⁺ e bomba Na/K. É a fadiga do neurônio, e é o que impede a
  rede de latchar.
- **Estado `fatigue`** em `Drives`, alimentado pela atividade do *circuito*
  (não pela velocidade das rodas — ler a saída motora fecharia um laço em cima
  do que se quer explicar).
- **`VNC_RECRUIT`**: piso de recrutamento da marcha. O FAFB é um conectoma de
  cérebro; o gerador de padrão fica no cordão nervoso ventral, que não está no
  dataset. É retificação contínua, não um `if anda`.
- **Detector de "não estou saindo do lugar" por visão** (cópia eferente ×
  fluxo óptico) e `Compass.back_out()`, que escala direto para ré quando a cena
  congela.

### Removido

- `drive_forward()` e `V_CRUISE`.
- A injeção em `DNp09` proporcional a estado interno.
- Os gates de `awake` sobre PFL3 e H2 — quem cala o steering agora é o dFB,
  dentro da rede.
- O teste de progresso por infravermelho, que lia ruído (ver Corrigido).

### Corrigido

- **A rede latchava e ninguém tinha visto.** Todo script do projeto rodava
  menos de 1 s — o `W_SYN = 0,18` foi calibrado com 350 ms. Em 20 s aparece
  outra coisa: um pulso de octopamina leva a população descendente a ~2,3 Hz e
  ela **fica lá** depois que o pulso acaba (1,908 Hz dez segundos depois). É
  biestável, e o ER5/dFB não traz de volta nem a 28 mV. Defeito pré-existente,
  exposto por rodar mais tempo, não introduzido aqui.
- **Detecção de robô preso.** O teste antigo comparava leituras de
  infravermelho consecutivas com limiar de 12 contagens. A terceira coluna do
  `lookupTable` é ruído *relativo*: a 1,5 cm o desvio de uma amostra já é ~24
  contagens. O teste lia ruído puro, o contador zerava e a frustração nunca
  subia — por isso o robô ficava encarando parede com as rodas girando.
- `ports.json` não guarda mais os 103 mil índices de SENSORY/OPTIC; `load()`
  os deriva do `super_class`.

### Ponto de operação (convergido por `scripts/search.py`)

`W_SYN`=0,18 · `TONIC`=8 · `B_SLOW`=0,005 · `K_MOD`=1,3

A busca varre quatro parâmetros acoplados com objetivo de quatro termos —
separação entre estados, parada de verdade, ausência de latch em 20 s e
lateralização preservada. Dos 96 pontos, 32 passam na separação e **3** passam
nos quatro. O vencedor mantém o `W_SYN` historicamente calibrado e dá a melhor
lateralização das 48 medições.

Comportamento resultante, de `scripts/calibrate.py`:

| estado interno | DN soma | v |
|---|---|---|
| explorando (lugar novo, com fome) | 2,113 Hz | 14,0 cm/s |
| recém-acordado | 1,840 Hz | 11,2 cm/s |
| sobressaltado (dormindo + tapa) | 1,609 Hz | 8,9 cm/s |
| lugar conhecido (habituado) | 1,507 Hz | 7,8 cm/s |
| saciado / tédio | 0,463 Hz | **parado** |
| exausto | 0,433 Hz | **parado** |
| dormindo | 0,433 Hz | **parado** |

Os 11,2 cm/s do recém-acordado batem com o cruzeiro medido antes de qualquer
disto existir. Sem latch: 0,000 Hz a 1 s, 2 s e 4 s depois de tirar a
modulação. Lateralização do PFL3: faixa 0,615–0,790.

Duas coisas que a busca ensinou, e que estao registradas no CLAUDE.md:

- **A busca apontou para fora dos próprios parâmetros.** Na primeira rodada a
  separação deu 0,003–0,33 Hz em todos os pontos, o que significava que
  nenhuma calibração resolveria. Era defeito no mapeamento estado → núcleo:
  mosca dormindo recebia 36,6 mV de octopamina.
- **Ordenar sobreviventes por separação enviesa.** Separação alta correlaciona
  com `hi` alto, e `hi` alto é justamente o que latcha; a primeira seleção
  descartou em silêncio o único grupo plausível. A etapa 2 agora testa todos.

### Compatibilidade

`connectome.load()` passou a devolver **quatro** valores
(`w, mod, root_ids, ports`). É preciso rodar `scripts/build.py` de novo — um
`brain.npz` anterior não tem a matriz moduladora e o `load()` recusa com
mensagem explícita.
