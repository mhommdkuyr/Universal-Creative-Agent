from fastapi.testclient import TestClient

from server import app

client = TestClient(app.app)


def test_health_unconfigured():
    response = client.get('/health')
    assert response.status_code == 200
    assert response.json()['ok'] is True


def test_step_rejects_invalid_model_result(monkeypatch):
    monkeypatch.setattr(app, 'model_call', lambda *args, **kwargs: '{"action":"invented"}')
    response = client.post('/v1/agent/step', json={'task': 'افتح تطبيقًا', 'ui_tree': '[]'})
    assert response.status_code == 200
    assert response.json()['action'] == 'observe'


def test_plan_parses_model_json(monkeypatch):
    monkeypatch.setattr(app, 'model_call', lambda *args, **kwargs: '{"summary":"خطة عامة","steps":["افتح الهدف","نفذ المهمة","تحقق"]}')
    response = client.post('/v1/agent/plan', json={'task': 'نفذ مهمة'})
    assert response.status_code == 200
    assert response.json()['steps'][-1] == 'تحقق'
