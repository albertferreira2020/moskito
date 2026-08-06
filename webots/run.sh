#!/usr/bin/env bash
# Sobe o corpo do moskito como extern controller do Webots.
#
# Uso:
#   1. abra webots/worlds/moskito_apartment.wbt no Webots
#   2. deixe a simulacao rodando (play)
#   3. bash webots/run.sh
#
# O cerebro roda AQUI, no venv do projeto, fora do processo do Webots -- a mesma
# fronteira que o firmware do ESP32-S3 vai ocupar depois.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WEBOTS="${WEBOTS_APP:-/Applications/Webots.app}/Contents"

[ -d "$WEBOTS" ] || { echo "Webots nao encontrado em $WEBOTS (defina WEBOTS_APP)"; exit 1; }
[ -f "$ROOT/data/brain.npz" ] || { echo "falta data/brain.npz -- rode scripts/build.py"; exit 1; }

export WEBOTS_HOME="$WEBOTS"
export PYTHONPATH="$WEBOTS/lib/controller/python:${PYTHONPATH:-}"
export DYLD_LIBRARY_PATH="$WEBOTS/lib/controller:${DYLD_LIBRARY_PATH:-}"
export WEBOTS_CONTROLLER_URL="${WEBOTS_CONTROLLER_URL:-ipc://1234/moskito}"

exec "$ROOT/.venv/bin/python" "$ROOT/webots/moskito_body.py"
