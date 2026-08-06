#!/usr/bin/env bash
# Baixa o conectoma FlyWire FAFB v783 do espelho publico do Codex.
# Licenca CC BY-NC 4.0 -- uso nao comercial. https://flywire.ai/guidelines
set -euo pipefail

BASE=https://storage.googleapis.com/flywire-data/codex/data/fafb/783
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/data"
mkdir -p "$DIR"

for f in connections classification labels neurons consolidated_cell_types; do
  if [ -f "$DIR/$f.csv" ]; then
    echo "ok   $f.csv"
    continue
  fi
  echo "-->  $f.csv.gz"
  curl -fsSL -o "$DIR/$f.csv.gz" "$BASE/$f.csv.gz"
  gunzip -f "$DIR/$f.csv.gz"
done

du -sh "$DIR"
