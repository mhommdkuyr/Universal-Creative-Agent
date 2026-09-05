"""Production entrypoint for UCOA V4 with live provider routing."""
import sys

import app_v4_runtime  # noqa: F401,E402
import app_v3
import provider_router


def _provider_reasoning(system, user):
    return provider_router.reasoning(system, user)


def _provider_visual(task, ui_tree, image):
    return provider_router.visual(task, ui_tree, image)


def _provider_call_vision(task, ui_tree, image):
    return provider_router.visual(task, ui_tree, image)


# Patch the V3 hooks only after V4 captures their legacy references. This makes
# V4 deliberately enter its compatibility/model-routing path without recursion.
app_v3.reasoning = _provider_reasoning
app_v3.visual = _provider_visual
app_v3.call_vision = _provider_call_vision


@app_v3.app.get("/v1/providers/probe")
def providers_probe():
    return provider_router.safe_text_probe()


# Keep the old bridge importable for backward compatibility, but V4 production
# routing is now provided directly by the multi-provider router above.
sys.modules[__name__] = app_v3
