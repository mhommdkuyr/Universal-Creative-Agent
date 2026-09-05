"""Production entrypoint for the UCOA V3 brain.

The test suite and older integrations import ``app`` and patch runtime
providers directly.  Re-export the actual V3 runtime module so those patches
operate on the same module globals used by the FastAPI endpoints.
"""
import sys

import app_v3_runtime

sys.modules[__name__] = app_v3_runtime
