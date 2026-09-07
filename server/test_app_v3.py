from fastapi.testclient import TestClient

import app_v3

client = TestClient(app_v3.app)


def wait_job(job_id: str):
    for _ in range(200):
        x = client.get(f'/v1/agent/jobs/{job_id}').json()
        if x['status'] == 'completed':
            return x['result']
        if x['status'] == 'failed':
            raise AssertionError(x.get('error'))
    raise AssertionError('timeout')


def test_v3_health():
    x = client.get('/health').json()
    assert x['version'] == '3.0.0'
    assert x['routing'] is False
    assert x['verifier'] is True
    assert x['state_persistence'] is True


def test_v3_visual_then_reasoning_pipeline(monkeypatch):
    monkeypatch.setattr(app_v3, 'VISION_ENABLED', True)
    monkeypatch.setattr(app_v3, 'visual', lambda task, ui, image: ({
        'screen_summary': 'Continue button visible',
        'elements': [{'text': 'Continue', 'role': 'button', 'x': 100, 'y': 200}],
        'confidence': 0.95,
    }, 'vision-test'))
    monkeypatch.setattr(app_v3, 'reasoning', lambda system, user: (
        '{"action":"click_any_text","params":{"texts":["Continue"]},"message":"click visible button","done":false,"wait_after_ms":700}',
        'reasoning-test',
    ))
    r = client.post('/v1/agent/step', json={'task': 'continue', 'ui_tree': '[]', 'screenshot_base64': 'aGVsbG8='})
    x = wait_job(r.json()['job_id'])
    assert x['vision_provider'] == 'vision-test'
    assert x['action'] in {'click_any_text', 'observe'}
    assert x['visual_observation']['screen_summary'] == 'Continue button visible'
    assert x['provider'] in {'reasoning-test', 'repair'}


def test_v3_result_verifier():
    x = client.post('/v1/agent/verify-result', json={
        'task': 'press Continue',
        'action': {'action': 'click_any_text', 'params': {'texts': ['Continue']}},
        'before_ui_tree': '[{"text":"Continue"}]',
        'after_ui_tree': '[{"text":"Next step"}]'
    }).json()
    assert x['verified'] is True


def test_v3_safety_gate():
    x = client.post('/v1/agent/verify', json={
        'task': 'أرسل رمز التحقق',
        'decision': {'action': 'type_into_any', 'params': {'text': '123456'}}
    }).json()
    assert x['allowed'] is False
    assert x['requires_confirmation'] is True
