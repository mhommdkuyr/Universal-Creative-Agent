"""Production entrypoint for UCOA V4 + OmniRoute."""
import sys

import app_v4_runtime  # noqa: F401,E402
import app_v3
import omniroute_bridge

omniroute_bridge.install()
sys.modules[__name__] = app_v3
