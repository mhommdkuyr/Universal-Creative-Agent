from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SERVER = ROOT / "server"
if str(SERVER) not in sys.path:
    sys.path.insert(0, str(SERVER))

# The production server runs from server/, where sitecustomize is automatic.
# CI pytest starts from the repository root, so load the same compatibility patch explicitly.
import sitecustomize  # noqa: E402,F401
