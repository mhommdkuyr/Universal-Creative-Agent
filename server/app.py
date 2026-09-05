"""Production entrypoint for UCOA V4 with live provider routing."""
import sys

import app_v4_runtime  # noqa: F401,E402
import app_v3
import provider_router


def _provider_reasoning(system, user):
    return provider_router.reasoning(system, user)


def _provider_visual(task, ui_tree, image):
    return provider_router.visual(task, ui_tree, image)

# Import V4 before patching so its legacy references remain stable. Patch only
# the normal reasoning/visual hooks; keep call_vision untouched so existing
# tests and downstream integrations can override it safely.
app_v3.reasoning = _provider_reasoning
app_v3.visual = _provider_visual


@app_v3.app.get("/v1/providers/probe")
def providers_probe():
    return provider_router.safe_text_probe()


sys.modules[__name__] = app_v3
