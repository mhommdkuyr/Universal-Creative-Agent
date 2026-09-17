import json
import os
import sqlite3
import time
from fastapi.testclient import TestClient

os.environ["UCOA_AGENT_TOKEN"] = "test-agent-token"
os.environ["UCOA_STATE_DB"] = "/tmp/test_bridge_state.db"
os.environ["UCOA_REMOTE_OPS_DB"] = "/tmp/test_bridge_ops.db"

import app
import app_v3
import device_bridge
import remote_ops

client = TestClient(app.app)
ADMIN_HEADERS = {"Authorization": "Bearer test-agent-token"}


def test_device_bridge_full_lifecycle():
    install_id = "test_samsung_df8146c4"

    # Create client session
    sess_res = client.post("/v1/client/session", json={"install_id": install_id, "app_version": "1.0.0", "platform": "android"})
    assert sess_res.status_code == 200
    token = sess_res.json()["session_token"]
    CLIENT_HEADERS = {"Authorization": f"Bearer {token}"}

    # Queue command as admin
    q_res = client.post(f"/v1/admin/devices/{install_id}/commands", json={"kind": "task", "task": "افتح تطبيق الإعدادات"}, headers=ADMIN_HEADERS)
    assert q_res.status_code == 200
    cmd_id = q_res.json()["command_id"]
    assert q_res.json()["status"] == "queued"

    # Client fetches next command
    next_res = client.get("/v1/client/commands/next", headers=CLIENT_HEADERS)
    assert next_res.status_code == 200
    cmd = next_res.json()["command"]
    assert cmd is not None
    assert cmd["id"] == cmd_id
    assert cmd["payload"]["task"] == "افتح تطبيق الإعدادات"

    # Step 0: Step decision before app is open
    step0_res = client.post("/v1/agent/step", json={"task": "افتح تطبيق الإعدادات", "step": 0, "foreground_package": "com.whatsapp", "ui_tree": "[]"}, headers=CLIENT_HEADERS)
    assert step0_res.status_code == 200
    res0 = step0_res.json()["result"]
    assert res0["action"] == "open_app_by_name"

    # Step 1: Step decision after app is open in foreground
    step1_res = client.post("/v1/agent/step", json={"task": "افتح تطبيق الإعدادات", "step": 1, "foreground_package": "com.android.settings", "ui_tree": "[Settings]"}, headers=CLIENT_HEADERS)
    assert step1_res.status_code == 200
    res1 = step1_res.json()["result"]
    assert res1["action"] == "done"
    assert res1["done"] is True

    # Complete command
    comp_res = client.post(f"/v1/client/commands/{cmd_id}/result", json={"install_id": install_id, "status": "completed", "result": {"final_foreground": "com.android.settings"}}, headers=CLIENT_HEADERS)
    assert comp_res.status_code == 200
    assert comp_res.json()["status"] == "completed"

    # Admin inspects command
    insp_res = client.get(f"/v1/admin/devices/{install_id}/commands/{cmd_id}", headers=ADMIN_HEADERS)
    assert insp_res.status_code == 200
    command_data = insp_res.json()["command"]
    assert command_data["status"] == "completed"
    assert command_data["result"]["final_foreground"] == "com.android.settings"


def test_stale_command_timeout():
    install_id = "test_samsung_stale"

    # Create client session
    sess_res = client.post("/v1/client/session", json={"install_id": install_id, "app_version": "1.0.0", "platform": "android"})
    token = sess_res.json()["session_token"]
    CLIENT_HEADERS = {"Authorization": f"Bearer {token}"}

    # Queue command as admin
    q_res = client.post(f"/v1/admin/devices/{install_id}/commands", json={"kind": "task", "task": "افتح تطبيق الإعدادات"}, headers=ADMIN_HEADERS)
    cmd_id = q_res.json()["command_id"]

    # Claim command
    next_res = client.get("/v1/client/commands/next", headers=CLIENT_HEADERS)
    assert next_res.json()["command"]["id"] == cmd_id

    # Manually backdate claimed_at in DB
    db_path = device_bridge.DB_PATH
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE device_commands SET claimed_at = ? WHERE id = ?", (time.time() - 400, cmd_id))
    conn.commit()
    conn.close()

    # Inspect command triggering _requeue_stale
    insp_res = client.get(f"/v1/admin/devices/{install_id}/commands/{cmd_id}", headers=ADMIN_HEADERS)
    assert insp_res.status_code == 200
    command_data = insp_res.json()["command"]
    assert command_data["status"] == "failed"
    assert "timed out" in command_data["result"]["error"]
