"""Corpo do moskito no Webots -- extern controller.

Roda no venv do projeto (numpy/scipy), fora do processo do Webots. E' de
proposito: e' a mesma fronteira que o firmware do ESP32-S3 vai ocupar depois.
O controller so' traduz sensor <-> porta neural; nenhuma decisao mora aqui.

    bash webots/run.sh          (com o mundo aberto e a simulacao rodando)
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from controller import Robot

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from moskito.body import Body
from moskito.brain import Brain
from moskito.connectome import load
from moskito.drives import DAY_MINUTES, Drives
from moskito.mushroom import MushroomBody, frame_features

BRAIN_MS = 5.0         # tempo biologico por passo: metade do custo, loop 2x mais rapido
PS_NEAR = 250.0        # leitura de proximidade que ja' conta como parede
PS_LOOM = 1800.0       # leitura frontal que dispara o reflexo de fuga
PS_STUCK = 2600.0      # encostado na parede
MAX_OMEGA = 7.536      # rad/s, limite do e-puck v2
WHEEL_R = 0.0205       # m
MET_DIST = 0.30        # fracao da imagem ocupada que conta como "encontrou"


def find_target(image: bytes, w: int, h: int) -> tuple[float, float, float]:
    """Acha a camisa vermelha do pedestre. Devolve (esquerda, direita, tamanho).

    E' um detector de cor, nao visao de verdade. No robo fisico isso vira um
    classificador na camera do ESP32 -- o cerebro nao muda, so' esta porta.
    """
    a = np.frombuffer(image, dtype=np.uint8).reshape(h, w, 4).astype(np.int16)
    b, g, r = a[:, :, 0], a[:, :, 1], a[:, :, 2]
    mask = (r > 90) & (r - g > 45) & (r - b > 45)
    n = int(mask.sum())
    if n < 8:
        return 0.0, 0.0, 0.0
    cx = float(np.argwhere(mask)[:, 1].mean()) / w      # 0 = esquerda, 1 = direita
    size = n / (w * h)
    strength = min(1.0, size * 12)
    return (1.0 - cx) * strength, cx * strength, size


def main() -> None:
    robot = Robot()
    dt = int(robot.getBasicTimeStep())

    ps = []
    for i in range(8):
        s = robot.getDevice(f"ps{i}")
        s.enable(dt)
        ps.append(s)

    cam = robot.getDevice("camera")
    if cam is not None:
        cam.enable(dt)
        cw, ch = cam.getWidth(), cam.getHeight()
        print(f"camera {cw}x{ch}", flush=True)
    else:
        cw = ch = 0
        print("aviso: sem camera -- corpo cogumelar desligado", flush=True)

    left = robot.getDevice("left wheel motor")
    right = robot.getDevice("right wheel motor")
    for m in (left, right):
        m.setPosition(float("inf"))
        m.setVelocity(0.0)

    print("carregando conectoma...", flush=True)
    w, _, ports = load(Path(__file__).resolve().parents[1] / "data/brain.npz")
    body = Body(Brain(w, seed=11), ports, Drives(), seed=11)
    mb = MushroomBody(n_in=16 * 12, seed=11) if cam is not None else None
    print(f"pronto: {w.shape[0]:,} neuronios, dia da mosca = {DAY_MINUTES:.0f} min", flush=True)

    step, stuck_for = 0, 0
    while robot.step(dt) != -1:
        v = np.array([s.getValue() for s in ps], dtype=np.float32)

        # e-puck: ps0/ps1/ps2 = direita (frente -> lado), ps5/ps6/ps7 = esquerda.
        # Proximidade e' um proxy para fluxo optico ate' a camera virar sensor.
        flow_r = float(np.clip(v[[0, 1, 2]].max() / PS_NEAR, 0, 1))
        flow_l = float(np.clip(v[[5, 6, 7]].max() / PS_NEAR, 0, 1))
        loom_r = 1.0 if v[0] > PS_LOOM else 0.0
        loom_l = 1.0 if v[7] > PS_LOOM else 0.0

        # Preso: encostado na frente por varios passos seguidos.
        stuck_for = stuck_for + 1 if max(v[0], v[7]) > PS_STUCK else 0
        stuck = stuck_for > 8

        novelty, tgt_l, tgt_r, tgt_size = body.drives.novelty, 0.0, 0.0, 0.0
        if cam is not None and (img := cam.getImage()):
            novelty = mb(frame_features(img, cw, ch))
            tgt_l, tgt_r, tgt_size = find_target(img, cw, ch)

        body.sense(flow_left=flow_l, flow_right=flow_r,
                   looming_left=loom_l, looming_right=loom_r,
                   odor=body.drives.hunger, target_left=tgt_l, target_right=tgt_r)
        vl, vr = body.act(BRAIN_MS)

        speed = abs(vl + vr) / 2
        body.drives.update(dt / 1000.0, moving=speed > 0.01,
                           looming=max(loom_l, loom_r),
                           at_dock=body.drives.hunger > 0.9,
                           place_novelty=novelty, stuck=stuck,
                           met_someone=tgt_size > MET_DIST)

        left.setVelocity(float(np.clip(vl / WHEEL_R, -MAX_OMEGA, MAX_OMEGA)))
        right.setVelocity(float(np.clip(vr / WHEEL_R, -MAX_OMEGA, MAX_OMEGA)))

        step += 1
        if step % 50 == 0:
            r = body.rates()
            seen = f" ALGUEM({tgt_size:.2f})" if tgt_size > 0.01 else ""
            print(f"{body.drives}  DN={r['DN_L']:5.2f}/{r['DN_R']:5.2f}  "
                  f"prox E/D={flow_l:.2f}/{flow_r:.2f}{'  PRESO' if stuck else ''}"
                  f"  v={vl:+.3f}/{vr:+.3f}  mapa={mb.learned:.1%}{seen}"
                  if mb else f"{body.drives}  v={vl:+.3f}/{vr:+.3f}", flush=True)


if __name__ == "__main__":
    main()
