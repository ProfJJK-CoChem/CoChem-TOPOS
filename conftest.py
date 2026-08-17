import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
ECOSYSTEM_ROOT = REPO_ROOT.parent

paths_to_add = [
    str(REPO_ROOT),
    str(ECOSYSTEM_ROOT / "CoChem-BASE"),
    str(ECOSYSTEM_ROOT / "CoChem-NODE"),
    str(ECOSYSTEM_ROOT),
]

for p in paths_to_add:
    if p not in sys.path:
        sys.path.insert(0, p)
