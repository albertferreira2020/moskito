"""CSVs do Codex -> data/brain.npz + data/ports.json"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from moskito.connectome import build

if __name__ == "__main__":
    build()
