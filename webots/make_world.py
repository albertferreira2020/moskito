"""Gera o mundo do moskito a partir do apartamento original do Webots.

Existe porque o Webots grava o estado assentado da simulacao dentro do .wbt
quando o mundo e' salvo -- campos `hidden`, posicao final, velocidade das
rodas. Depois disso o robo passa a "nascer" onde tinha travado, e moveis
aparecem deslocados. Regenerar e' mais confiavel que remendar:

    .venv/bin/python webots/make_world.py
"""

from __future__ import annotations

import sys
from pathlib import Path

WEBOTS = Path("/Applications/Webots.app/Contents")
SRC = WEBOTS / "projects/samples/environments/indoor/worlds/complete_apartment.wbt"
OUT = Path(__file__).resolve().parent / "worlds/moskito_apartment.wbt"
RAW = "https://raw.githubusercontent.com/cyberbotics/webots/R2025a/projects"

PROTOS = [f"{RAW}/robots/gctronic/e-puck/protos/E-puck.proto",
          f"{RAW}/humans/pedestrian/protos/Pedestrian.proto"]

# Centro da sala. LIVING_ROOM_1 esta' em (-1.91, 3.20) mas isso e' RELATIVO ao
# DEF FLOOR Solid, que fica em (-4.96, -6.5): a coordenada de mundo e' a soma.
# 69 cm de folga ate' o movel mais proximo.
ROBOT = '''
E-puck {
  translation -6.87 -3.30 0.01
  rotation 0 0 1 0
  name "moskito"
  controller "<extern>"
  version "2"
  camera_width 64
  camera_height 48
}
'''

# "Alguem" para procurar, num comodo diferente. Camisa vermelha porque o
# detector de alvo e' por cor -- no robo fisico vira um classificador na
# camera do ESP32 e o cerebro nao muda, so' essa porta.
PERSON = '''
Pedestrian {
  translation -1.31 -9.54 1.27
  rotation 0 0 1 2.2
  name "visitante"
  controller ""
  shirtColor 0.9 0.05 0.05
  enableBoundingObject TRUE
}
'''

if __name__ == "__main__":
    if not SRC.exists():
        sys.exit(f"nao achei o apartamento original em {SRC}")

    s = SRC.read_text()
    if "hidden " in s:
        sys.exit("o apartamento ORIGINAL do Webots foi salvo com estado; reinstale")

    cut = s.index("\n", s.rindex("EXTERNPROTO ")) + 1
    s = s[:cut] + "".join(f'EXTERNPROTO "{u}"\n' for u in PROTOS) + s[cut:] + ROBOT + PERSON

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(s)
    print(f"-> {OUT}  ({len(s.splitlines())} linhas, 0 campos hidden)")
