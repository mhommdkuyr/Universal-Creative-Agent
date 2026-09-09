import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "server"
if str(SERVER) not in sys.path:
    sys.path.insert(0, str(SERVER))

# Vercel functions have ephemeral writable storage; keep the API import-safe there.
os.environ.setdefault("UCOA_STATE_DB", "/tmp/ucoa-state.db")

from app import app  # noqa: E402,F401
