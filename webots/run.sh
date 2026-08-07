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
ROBOT="${ROBOT_NAME:-moskito}"

# O Webots sobe na 1234, mas cai para 1235, 1236... se ja' houver outra
# instancia aberta. Ele publica o socket em
#     /tmp/webots/<usuario>/<porta>/ipc/<robo>/extern
# -- usuario e porta vem ANTES do "ipc", nao depois.
if [ -z "${WEBOTS_CONTROLLER_URL:-}" ]; then
  PORT=""
  for d in /tmp/webots/"$USER"/*/ipc/"$ROBOT"; do
    [ -e "$d" ] || continue
    PORT="$(basename "$(dirname "$(dirname "$d")")")"
  done
  if [ -z "$PORT" ]; then
    echo "aviso: nao achei o socket de '$ROBOT'; o mundo esta' aberto e em play?"
    echo "       usando 1234 -- se travar, veja a porta no console do Webots e rode:"
    echo "       WEBOTS_CONTROLLER_URL=ipc://<porta>/$ROBOT bash webots/run.sh"
    PORT=1234
  else
    echo "webots encontrado na porta $PORT"
  fi
  export WEBOTS_CONTROLLER_URL="ipc://$PORT/$ROBOT"
fi

exec "$ROOT/.venv/bin/python" "$ROOT/webots/moskito_body.py"
