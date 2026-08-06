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

BRAIN_MS = 10.0        # tempo biologico simulado por passo de controle
PS_NEAR = 250.0        # leitura de proximidade que ja' conta como parede
PS_LOOM = 1800.0       # leitura frontal que dispara o reflexo de fuga
MAX_OMEGA = 6.28       # rad/s, limite do e-puck
WHEEL_R = 0.0205       # m


def main() -> None:
    robot = Robot()
    dt = int(robot.getBasicTimeStep())

    ps = []
    for i in range(8):
        s = robot.getDevice(f"ps{i}")
        s.enable(dt)
        ps.append(s)

    left = robot.getDevice("left wheel motor")
    right = robot.getDevice("right wheel motor")
    for m in (left, right):
        m.setPosition(float("inf"))
        m.setVelocity(0.0)

    print("carregando conectoma...", flush=True)
    w, _, ports = load(Path(__file__).resolve().parents[1] / "data/brain.npz")
    body = Body(Brain(w, seed=11), ports, Drives())
    print(f"pronto: {w.shape[0]:,} neuronios, dia da mosca = {DAY_MINUTES:.0f} min", flush=True)

    step = 0
    while robot.step(dt) != -1:
        v = np.array([s.getValue() for s in ps], dtype=np.float32)

        # e-puck: ps0/ps1/ps2 = direita (frente -> lado), ps5/ps6/ps7 = esquerda.
        # Proximidade e' um proxy para fluxo optico; a camera entra depois.
        flow_r = float(np.clip(v[[0, 1, 2]].max() / PS_NEAR, 0, 1))
        flow_l = float(np.clip(v[[5, 6, 7]].max() / PS_NEAR, 0, 1))
        loom_r = 1.0 if v[0] > PS_LOOM else 0.0
        loom_l = 1.0 if v[7] > PS_LOOM else 0.0

        body.sense(flow_left=flow_l, flow_right=flow_r,
                   looming_left=loom_l, looming_right=loom_r,
                   odor=body.drives.hunger)
        vl, vr = body.act(BRAIN_MS)

        speed = abs(vl + vr) / 2
        body.drives.update(dt / 1000.0, moving=speed > 0.01,
                           looming=max(loom_l, loom_r),
                           at_dock=body.drives.hunger > 0.9)

        left.setVelocity(float(np.clip(vl / WHEEL_R, -MAX_OMEGA, MAX_OMEGA)))
        right.setVelocity(float(np.clip(vr / WHEEL_R, -MAX_OMEGA, MAX_OMEGA)))

        step += 1
        if step % 50 == 0:
            r = body.rates()
            print(f"{body.drives}  DN L/R={r['DN_L']:5.2f}/{r['DN_R']:5.2f}Hz  "
                  f"fluxo E/D={flow_l:.2f}/{flow_r:.2f}  v={vl:+.3f}/{vr:+.3f}", flush=True)


if __name__ == "__main__":
    main()
