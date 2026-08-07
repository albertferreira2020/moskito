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

### Não converge ainda

A arquitetura está implementada; o **ponto de operação não está calibrado**.
Medido com traço de 40 s:

| estado interno | DN soma | v média |
|---|---|---|
| explorando | 1,521 Hz | 7,76 cm/s |
| lugar velho | 1,477 Hz | 7,43 cm/s |
| dormindo | 1,361 Hz | 6,29 cm/s |

Os estados não diferenciam — mosca dormindo anda a 6,3 cm/s. São quatro
parâmetros acoplados (`W_SYN`, `TONIC`, `B_SLOW`, `K_MOD`) e três regimes,
nenhum certo: sem `B_SLOW` a rede latcha; em 0,15 ela morre (0,08 Hz); em 0,02
fica monoestável mas surda ao estado. Falta a busca nesse espaço, com objetivo
explícito — separação entre estados **e** ausência de latch em 20 s **e**
lateralização preservada. Cada avaliação custa ~40 s de parede.

O que **está** medido e funcionando: a lateralização do PFL3 sobrevive com a
rede acordada (faixa 0,62–0,84), a resposta descendente ao tônico é graduada
(8 mV → 0,47 Hz; 11 mV → 1,17 Hz), e o pipeline roda ponta a ponta.

### Compatibilidade

`connectome.load()` passou a devolver **quatro** valores
(`w, mod, root_ids, ports`). É preciso rodar `scripts/build.py` de novo — um
`brain.npz` anterior não tem a matriz moduladora e o `load()` recusa com
mensagem explícita.
