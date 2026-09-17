from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parents[1] / "server"
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

import app
from fastapi.testclient import TestClient

client = TestClient(app.app)


def test_device_bridge_command_lifecycle():
    install_id = f"test-samsung-sm-g970u-{uuid.uuid4().hex[:8]}"
    admin_token = "test-admin-token-secret"
    os.environ["UCOA_AGENT_TOKEN"] = admin_token

    # 1. Create client session
    session_res = client.post("/v1/client/session", json={
        "install_id": install_id,
        "app_version": "1.0.0",
        "platform": "android",
        "device": {"model": "SM-G970U", "manufacturer": "samsung"}
    })
    assert session_res.status_code == 200
    session_data = session_res.json()
    assert session_data.get("ok") is True
    session_token = session_data["session_token"]

    headers = {"Authorization": f"Bearer {session_token}"}
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    # 2. Queue command
    task_text = "افتح تطبيق الإعدادات"
    queue_res = client.post(
        f"/v1/admin/devices/{install_id}/commands",
        headers=admin_headers,
        json={"kind": "task", "task": task_text}
    )
    assert queue_res.status_code == 200
    queue_data = queue_res.json()
    assert queue_data.get("ok") is True
    command_id = queue_data["command_id"]
    assert queue_data["status"] == "queued"

    # 3. Client polls next command (claims it)
    next_res = client.get("/v1/client/commands/next", headers=headers)
    assert next_res.status_code == 200
    next_data = next_res.json()
    assert next_data.get("ok") is True
    command = next_data.get("command")
    assert command is not None
    assert command["id"] == command_id
    assert command["payload"]["task"] == task_text

    # 4. Client requests plan (200)
    plan_res = client.post("/v1/agent/plan", headers=headers, json={"task": task_text})
    assert plan_res.status_code == 200
    plan_data = plan_res.json()
    assert plan_data.get("status") in {"completed", "pending"}
    if plan_data.get("status") == "completed":
        plan_result = plan_data.get("result", {})
    else:
        job_id = plan_data.get("job_id")
        job_res = client.get(f"/v1/agent/jobs/{job_id}", headers=headers)
        assert job_res.status_code == 200
        plan_result = job_res.json().get("result", {})
    assert "steps" in plan_result

    # 5. Client requests step (200)
    step_res = client.post("/v1/agent/step", headers=headers, json={
        "task": task_text,
        "step": 0,
        "ui_tree": '[{"text":"Settings","class":"android.widget.TextView"}]',
        "capabilities": ["open_app_by_name", "click_any_text", "done"]
    })
    assert step_res.status_code == 200
    step_data = step_res.json()
    assert step_data.get("status") in {"completed", "pending"}

    # 6. Client verifies result (200)
    verify_res = client.post("/v1/agent/verify-result", headers=headers, json={
        "task": task_text,
        "action": {"action": "open_app_by_name", "params": {"app_name": "Settings"}},
        "before_ui_tree": "[]",
        "after_ui_tree": '[{"text":"Settings"}]'
    })
    assert verify_res.status_code == 200
    verify_data = verify_res.json()
    assert verify_data.get("verified") is True

    # 7. Client reports command completion (200)
    result_res = client.post(
        f"/v1/client/commands/{command_id}/result",
        headers=headers,
        json={
            "install_id": install_id,
            "status": "completed",
            "result": {"task": task_text, "steps": 1, "final_foreground": "com.android.settings"}
        }
    )
    assert result_res.status_code == 200
    assert result_res.json().get("status") == "completed"

    # 8. Inspect command record -> status is completed
    inspect_res = client.get(
        f"/v1/admin/devices/{install_id}/commands/{command_id}",
        headers=admin_headers
    )
    assert inspect_res.status_code == 200
    inspect_data = inspect_res.json()
    assert inspect_data["command"]["status"] == "completed"
