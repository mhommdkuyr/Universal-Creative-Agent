import json
from .models import Action


def encode_android_action(action: Action) -> str:
    allowed = {
        'tap', 'swipe', 'long_press', 'type_text', 'click_text', 'back', 'home',
        'open_app', 'screenshot', 'open_url', 'open_app_by_name', 'click_any_text',
        'type_into_any', 'observe', 'wait'
    }
    if action.type not in allowed:
        raise ValueError(f'unsupported Android action: {action.type}')
    return json.dumps({'action': action.type, **action.args}, ensure_ascii=False)
