from pathlib import Path
import sys
import time

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent))
import app  # noqa: E402

client = TestClient(app.app)


def wait_job(job_id: str):
    for _ in range(100):
        response = client.get(f'/v1/agent/jobs/{job_id}')
        assert response.status_code == 200
        body = response.json()
        if body['status'] == 'completed':
            return body['result']
        if body['status'] == 'failed':
            raise AssertionError(body.get('error', 'job failed'))
        time.sleep(0.01)
    raise AssertionError('job did not complete')


def test_health_unconfigured():
    response = client.get('/health')
    assert response.status_code == 200
    body = response.json()
    assert body['ok'] is True
    assert body['routing'] is True
    assert body['verifier'] is True
    assert body['state_persistence'] is True


def test_step_rejects_invalid_model_result(monkeypatch):
    monkeypatch.setattr(app, 'reasoning', lambda *args, **kwargs: ('{"action":"invented"}', 'test'))
    response = client.post('/v1/agent/step', json={'task': 'افتح تطبيقًا', 'ui_tree': '[]'})
    assert response.status_code == 200
    job = wait_job(response.json()['job_id'])
    assert job['action'] == 'observe'
    assert job['verification']['allowed'] is True


def test_plan_parses_model_json(monkeypatch):
    monkeypatch.setattr(app, 'reasoning', lambda *args, **kwargs: ('{"summary":"خطة عامة","steps":["افتح الهدف","نفذ المهمة","تحقق"]}', 'test'))
    response = client.post('/v1/agent/plan', json={'task': 'نفذ مهمة'})
    assert response.status_code == 200
    result = wait_job(response.json()['job_id'])
    assert result['steps'][-1] == 'تحقق'
    assert result['provider'] == 'test'


def test_session_persistence():
    created = client.post('/v1/agent/sessions', json={'title': 'اختبار'}).json()['session_id']
    assert created
    saved = client.get(f'/v1/agent/sessions/{created}').json()
    assert saved['session_id'] == created


def test_sensitive_action_requires_confirmation():
    result = client.post('/v1/agent/verify', json={
        'task': 'أرسل رمز التحقق',
        'decision': {'action': 'type_into_any', 'params': {'text': '123456'}}
    }).json()
    assert result['requires_confirmation'] is True
    assert result['allowed'] is False


def test_visual_observation_is_separate_from_action(monkeypatch):
    monkeypatch.setattr(app, 'VISION_ENABLED', True)
    monkeypatch.setattr(app, 'call_vision', lambda *args, **kwargs: ('زر Continue ظاهر في منتصف الشاشة', 'vision-test'))
    monkeypatch.setattr(app, 'reasoning', lambda *args, **kwargs: ('{"action":"click_any_text","params":{"text":"Continue"},"message":"اختيار الزر","done":false}', 'reasoning-test'))
    response = client.post('/v1/agent/step', json={'task': 'تابع', 'ui_tree': '[]', 'screenshot_base64': 'aGVsbG8='})
    result = wait_job(response.json()['job_id'])
    assert result['visual_observation'] == 'زر Continue ظاهر في منتصف الشاشة'
    assert result['vision_provider'] == 'vision-test'
    assert result['provider'] == 'reasoning-test'
    assert result['action'] == 'click_any_text'
