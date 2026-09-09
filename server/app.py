"""Production entrypoint for UCOA V4 with live provider routing."""
import json
import os

import app_v4_runtime  # noqa: F401,E402
import app_v3
import openai_provider
import provider_router
from observability import init_sentry

init_sentry()
OPENAI_PRIMARY = os.getenv("UCOA_OPENAI_PRIMARY", "false").lower() == "true"
_LEGACY_REASONING = app_v3.reasoning
_LEGACY_VISUAL = app_v3.visual
VISION_ENABLED = app_v3.VISION_ENABLED


def _provider_reasoning(system, user):
    if OPENAI_PRIMARY and openai_provider.configured():
        try:return openai_provider.reasoning(system, user), "openai"
        except Exception:pass
    try:return provider_router.reasoning(system, user)
    except Exception:return _LEGACY_REASONING(system, user)


def _provider_visual(task, ui_tree, image):
    if OPENAI_PRIMARY and openai_provider.configured():
        try:
            system=("You are UCOA visual perception. Inspect only the current Android screenshot and UI tree. "
                    "Return ONLY valid JSON: {\"screen_summary\":string,\"elements\":[{\"text\":string,\"role\":string,\"x\":number,\"y\":number}],\"visible_goal_state\":string,\"confidence\":number}. "
                    "Never invent unseen elements. Coordinates must be normalized to 0..1000.")
            user=json.dumps({"task":task,"ui_tree":ui_tree[:18000]},ensure_ascii=False)
            return app_v3.extract_json(openai_provider.visual(system,user,image)),"openai"
        except Exception:pass
    try:return provider_router.visual(task,ui_tree,image)
    except Exception:return _LEGACY_VISUAL(task,ui_tree,image)

reasoning=_provider_reasoning
call_vision=_provider_visual
app_v3.reasoning=lambda system,user: reasoning(system,user)
app_v3.visual=lambda task,ui_tree,image: call_vision(task,ui_tree,image)

@app_v3.app.get("/v1/providers/probe")
def providers_probe():
    result=provider_router.safe_text_probe()
    try:
        _,provider=reasoning("Return ONLY JSON.","Return exactly {\"ok\":true}.")
        result["runtime"]={"ok":True,"provider":provider}
        if provider=="openai":result["runtime"]["model"]=openai_provider.MODEL
        result["ok"]=True
    except Exception as exc:result["runtime"]={"ok":False,"error":type(exc).__name__}
    return result

@app_v3.app.get("/v1/providers/models")
def providers_models():
    data=[]
    for p in provider_router.PROVIDERS:
        try:base,key,model,vision,key_name=provider_router._cfg(p)
        except Exception:continue
        data.append({"id":f"{p['name']}:{model}","provider":p["name"],"model":model,"vision":vision,"configured":True,"base_url":base})
    return {"object":"list","data":data}

app=app_v3.app
