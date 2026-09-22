import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "server"
if str(SERVER) not in sys.path:
    sys.path.insert(0, str(SERVER))

# Vercel functions have ephemeral writable storage. Durable state uses DATABASE_URL;
# SQLite is only a safe fallback for a single invocation/container.
os.environ.setdefault("UCOA_STATE_DB", "/tmp/ucoa-state.db")
os.environ.setdefault("UCOA_REMOTE_OPS_DB", "/tmp/ucoa-remote-ops.db")
os.environ.setdefault("UCOA_REMOTE_OPS_DB", "/tmp/ucoa-remote-ops.db")

from app import app  # noqa: E402,F401
