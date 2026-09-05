"""Production entrypoint for the UCOA V4 multimodal brain."""
import sys

import app_v4_runtime  # noqa: F401,E402
import app_v3

sys.modules[__name__] = app_v3
