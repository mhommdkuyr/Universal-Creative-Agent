"""Production entrypoint for the UCOA V3 brain.

The historical test suite patches symbols on the ``app`` module itself.
Import the runtime first so its provider overrides are installed, then expose
the underlying V3 module so those patches affect the same globals used by the
FastAPI handlers.
"""
import sys

import app_v3_runtime  # noqa: F401,E402
import app_v3

sys.modules[__name__] = app_v3
