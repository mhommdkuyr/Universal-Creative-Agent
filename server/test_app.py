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
    assert response.json()['ok'] is True


def test_step_rejects_invalid_model_result(monkeypatch):
    monkeypatch.setattr(app, 'model_call', lambda *args, **kwargs: '{"action":"invented"}')
    response = client.post('/v1/agent/step', json={'task': 'افتح تطبيقًا', 'ui_tree': '[]'})
    assert response.status_code == 200
    job = wait_job(response.json()['job_id'])
    assert job['action'] == 'observe'


def test_plan_parses_model_json(monkeypatch):
    monkeypatch.setattr(app, 'model_call', lambda *args, **kwargs: '{"summary":"خطة عامة","steps":["افتح الهدف","نفذ المهمة","تحقق"]}')
    response = client.post('/v1/agent/plan', json={'task': 'نفذ مهمة'})
    assert response.status_code == 200
    result = wait_job(response.json()['job_id'])
    assert result['steps'][-1] == 'تحقق'
