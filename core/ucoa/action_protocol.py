import json
from .models import Action

def encode_android_action(action: Action) -> str:
    allowed={'tap','swipe','long_press','type_text','click_text','back','home','open_app','screenshot'}
    if action.type not in allowed:
        raise ValueError(f'unsupported Android action: {action.type}')
    return json.dumps({'action':action.type, **action.args}, ensure_ascii=False)
