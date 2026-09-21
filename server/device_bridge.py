from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

import jwt
from jwt import PyJWKClient
from fastapi import Header, HTTPException
from pydantic import BaseModel, Field

import app_v3
from remote_ops import _master_ok, _pg_conn, _require_client

# Live-phone QA trigger: keep the stable Render Brain Smoke workflow exercising the deployed bridge.

DB_PATH = Path(os.getenv("UCOA_REMOTE_OPS_DB", "/opt/render/project/src/.ucoa-local/remote_ops.db"))
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
COMMAND_TTL = max(60, int(os.getenv("UCOA_COMMAND_TTL_SECONDS", "900")))
CLAIM_TTL = max(30, int(os.getenv("UCOA_COMMAND_CLAIM_TTL_SECONDS", "120")))
DEVICE_ONLINE_TTL_SECONDS = max(15, int(os.getenv("UCOA_DEVICE_ONLINE_TTL_SECONDS", "45")))

GITHUB_OIDC_ISSUER = "https://token.actions.githubusercontent.com"
GITHUB_OIDC_AUDIENCE = "ucoa-live-phone"
GITHUB_QA_REPOSITORY = "mhommdkuyr/Universal-Creative-Agent"
GITHUB_QA_WORKFLOW = os.getenv("UCOA_GITHUB_QA_WORKFLOW", "CI")
GITHUB_QA_WORKFLOW_ALIASES = {"CI", "Final Release Gate", "Live Phone Cloud E2E", "Render Bridge Smoke Check", "Render Bridge Manual Diagnostic", "UCOA Live Phone QA", "Render Brain Smoke", ".github/workflows/render-bridge-smoke.yml"}
_GITHUB_JWK_CLIENT = PyJWKClient(f"{GITHUB_OIDC_ISSUER}/.well-known/jwks")

def _github_oidc_claims(authorization: str | None) -> dict[str, Any]:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "GitHub OIDC token required")
    token = authorization[7:].strip()
    try:
        signing_key = _GITHUB_JWK_CLIENT.get_signing_key_from_jwt(token).key
        claims = jwt.decode(token, signing_key, algorithms=["RS256"], audience=GITHUB_OIDC_AUDIENCE, issuer=GITHUB_OIDC_ISSUER)
    except Exception as exc:
        raise HTTPException(401, f"Invalid GitHub OIDC token: {type(exc).__name__}")
    if claims.get("repository") != GITHUB_QA_REPOSITORY:
        raise HTTPException(403, "Repository is not authorized for phone QA")
    if claims.get("ref") != "refs/heads/main":
        raise HTTPException(403, "Only main branch may run phone QA")
    workflow = str(claims.get("workflow", ""))
    if workflow not in GITHUB_QA_WORKFLOW_ALIASES:
        raise HTTPException(403, "Workflow is not authorized for phone QA")
    workflow_ref = str(claims.get("job_workflow_ref", ""))
    allowed_refs = (
        "/.github/workflows/final-release-gate.yml@refs/heads/main",
        "/.github/workflows/phone-live-e2e.yml@refs/heads/main",
        "/.github/workflows/render-bridge-smoke.yml@refs/heads/main",
        "/.github/workflows/ci.yml@refs/heads/main",
        "/.github/workflows/ucoa-live-qa.yml@refs/heads/main",
        "/.github/workflows/render-brain-smoke.yml@refs/heads/main",
    )
    if not any(workflow_ref.endswith(ref) for ref in allowed_refs):
        raise HTTPException(403, "Unexpected QA workflow reference")
    return claims

def _active_device_ids() -> list[str]:
    _ensure_schema()
    conn = _pg_conn()
    if conn is not None:
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT DISTINCT install_id FROM ucoa_client_sessions WHERE expires_at > now() AND last_seen_at > now() - (%s || ' seconds')::interval ORDER BY last_seen_at DESC", (DEVICE_ONLINE_TTL_SECONDS,))
                    devices = [r[0] for r in cur.fetchall()]
            conn.close()
            return devices
        except Exception:
            try: conn.close()
            except Exception: pass
    conn = sqlite3.connect(DB_PATH, timeout=15)
    try:
        return [r[0] for r in conn.execute("SELECT DISTINCT install_id FROM client_sessions WHERE expires_at > ? AND last_seen_at > ? ORDER BY last_seen_at DESC", (time.time(), time.time() - DEVICE_ONLINE_TTL_SECONDS)).fetchall()]
    finally:
        conn.close()

def _preferred_active_device_id() -> str | None:
    """
    Prefer the newest physical Samsung/SM-* Android session for live-phone QA.
    Emulator-like sessions are fallback only.
    """
    conn = _pg_conn()
    if conn is not None:
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT install_id, device, created_at, last_seen_at "
                        "FROM ucoa_client_sessions WHERE expires_at > now() "
                        "AND last_seen_at > now() - (%s || ' seconds')::interval "
                        "ORDER BY last_seen_at DESC",
                        (DEVICE_ONLINE_TTL_SECONDS,)
                    )
                    rows = cur.fetchall()
            conn.close()
            fallback = rows[0][0] if rows else None
            for install_id, device, _created_at, _last_seen_at in rows:
                meta = device if isinstance(device, dict) else {}
                manufacturer = str(meta.get("manufacturer", "")).lower()
                model = str(meta.get("model", "")).lower()
                if manufacturer == "samsung" or model.startswith("sm-"):
                    return install_id
            return fallback
        except Exception:
            try: conn.close()
            except Exception: pass
    conn = sqlite3.connect(DB_PATH, timeout=15)
    try:
        rows = conn.execute(
            "SELECT install_id, device, created_at, last_seen_at FROM client_sessions "
            "WHERE expires_at > ? AND last_seen_at > ? ORDER BY last_seen_at DESC",
            (time.time(), time.time() - DEVICE_ONLINE_TTL_SECONDS),
        ).fetchall()
        fallback = rows[0][0] if rows else None
        for install_id, device, _created_at, _last_seen_at in rows:
            try:
                meta = json.loads(device) if isinstance(device, str) else (device or {})
            except Exception:
                meta = {}
            manufacturer = str(meta.get("manufacturer", "")).lower()
            model = str(meta.get("model", "")).lower()
            if manufacturer == "samsung" or model.startswith("sm-"):
                return install_id
        return fallback
    finally:
        conn.close()

def _insert_command(install_id: str, req: DeviceCommandRequest) -> dict[str, Any]:
    install_id = install_id.strip()[:128]
    if not install_id or len(req.task.strip()) < 1:
        raise HTTPException(400, "install_id and task are required")
    if req.kind != "task":
        raise HTTPException(400, "Unsupported command kind")
    command_id = uuid.uuid4().hex
    payload = {"task": req.task[:12000], "attachments": req.attachments[:20], "metadata": req.metadata}
    conn = _pg_conn()
    if conn is not None:
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute("INSERT INTO ucoa_device_commands(id,install_id,kind,payload,created_at,result) VALUES(%s,%s,%s,%s,now(),'{}')", (command_id, install_id, req.kind, json.dumps(payload, ensure_ascii=False)))
            conn.close()
            return {"ok": True, "install_id": install_id, "command_id": command_id, "status": "queued", "expires_in": COMMAND_TTL}
        except Exception as exc:
            try: conn.close()
            except Exception: pass
            raise HTTPException(503, f"command storage unavailable: {type(exc).__name__}")
    conn = sqlite3.connect(DB_PATH, timeout=15)
    try:
        conn.execute("INSERT INTO device_commands(id,install_id,kind,payload,status,created_at,claimed_at,completed_at,result) VALUES(?,?,?,?,?,?,?,?,?)", (command_id, install_id, req.kind, json.dumps(payload, ensure_ascii=False), "queued", time.time(), None, None, "{}"))
        conn.commit()
    finally:
        conn.close()
    return {"ok": True, "install_id": install_id, "command_id": command_id, "status": "queued", "expires_in": COMMAND_TTL}


def _ensure_schema() -> None:
    conn = _pg_conn()
    if conn is not None:
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute("CREATE TABLE IF NOT EXISTS ucoa_device_commands (id TEXT PRIMARY KEY, install_id TEXT NOT NULL, kind TEXT NOT NULL, payload JSONB NOT NULL DEFAULT '{}'::jsonb, status TEXT NOT NULL DEFAULT 'queued', created_at TIMESTAMPTZ NOT NULL DEFAULT now(), claimed_at TIMESTAMPTZ, completed_at TIMESTAMPTZ, result JSONB NOT NULL DEFAULT '{}'::jsonb)")
                    cur.execute("CREATE INDEX IF NOT EXISTS idx_ucoa_device_commands_queue ON ucoa_device_commands(install_id,status,created_at)")
            conn.close(); return
        except Exception:
            try: conn.close()
            except Exception: pass
    conn = sqlite3.connect(DB_PATH, timeout=15)
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS device_commands(id TEXT PRIMARY KEY, install_id TEXT NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'queued', created_at REAL NOT NULL, claimed_at REAL, completed_at REAL, result TEXT NOT NULL)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_device_commands_queue ON device_commands(install_id,status,created_at)")
        conn.commit()
    finally: conn.close()


def _requeue_stale() -> None:
    conn = _pg_conn()
    if conn is not None:
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute("UPDATE ucoa_device_commands SET status='queued', claimed_at=NULL WHERE status='claimed' AND claimed_at < now() - (%s || ' seconds')::interval", (CLAIM_TTL,))
            conn.close(); return
        except Exception:
            try: conn.close()
            except Exception: pass
    conn = sqlite3.connect(DB_PATH, timeout=15)
    try:
        conn.execute("UPDATE device_commands SET status='queued', claimed_at=NULL WHERE status='claimed' AND claimed_at < ?", (time.time() - CLAIM_TTL,))
        conn.commit()
    finally: conn.close()


class DeviceCommandRequest(BaseModel):
    kind: str = "task"
    task: str
    attachments: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class DeviceCommandResult(BaseModel):
    install_id: str
    status: str
    result: dict[str, Any] = Field(default_factory=dict)


@app_v3.app.post("/v1/admin/devices/{install_id}/commands")
def queue_device_command(install_id: str, req: DeviceCommandRequest, authorization: str | None = Header(default=None)):
    if not _master_ok(authorization):
        raise HTTPException(401, "Admin token required")
    return _insert_command(install_id, req)

@app_v3.app.get("/v1/qa/phone/devices")
def qa_phone_devices(authorization: str | None = Header(default=None)):
    _github_oidc_claims(authorization)
    return {"ok": True, "devices": _active_device_ids()}

@app_v3.app.post("/v1/qa/phone/commands")
def qa_queue_phone_command(req: DeviceCommandRequest, authorization: str | None = Header(default=None)):
    _github_oidc_claims(authorization)
    devices = _active_device_ids()
    if not devices:
        raise HTTPException(409, "No active Android device session found")
    install_id = _preferred_active_device_id() or devices[-1]
    return _insert_command(install_id, req)

@app_v3.app.get("/v1/qa/phone/commands/{command_id}")
def qa_inspect_phone_command(command_id: str, authorization: str | None = Header(default=None)):
    _github_oidc_claims(authorization)
    _ensure_schema()
    conn = _pg_conn()
    if conn is not None:
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT id,install_id,kind,payload,status,created_at,claimed_at,completed_at,result FROM ucoa_device_commands WHERE id=%s", (command_id,))
                    row = cur.fetchone()
            conn.close()
            if not row:
                raise HTTPException(404, "Command not found")
            return {"ok": True, "command": {
                "id": row[0], "install_id": row[1], "kind": row[2], "payload": row[3], "status": row[4],
                "created_at": row[5].isoformat(), "claimed_at": row[6].isoformat() if row[6] else None,
                "completed_at": row[7].isoformat() if row[7] else None, "result": row[8]
            }}
        except HTTPException:
            raise
        except Exception:
            try: conn.close()
            except Exception: pass
    conn = sqlite3.connect(DB_PATH, timeout=15)
    try:
        row = conn.execute("SELECT id,install_id,kind,payload,status,created_at,claimed_at,completed_at,result FROM device_commands WHERE id=?", (command_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Command not found")
        return {"ok": True, "command": {
            "id": row[0], "install_id": row[1], "kind": row[2], "payload": json.loads(row[3]), "status": row[4],
            "created_at": row[5], "claimed_at": row[6], "completed_at": row[7], "result": json.loads(row[8])
        }}
    finally:
        conn.close()

@app_v3.app.get("/v1/client/commands/next")
def next_device_command(authorization: str | None = Header(default=None)):
    install_id, _ = _require_client(authorization)
    if not install_id: raise HTTPException(403, "Client session required")
    _ensure_schema(); _requeue_stale(); conn = _pg_conn()
    if conn is not None:
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT id,kind,payload,created_at FROM ucoa_device_commands WHERE install_id=%s AND status='queued' AND created_at > now() - (%s || ' seconds')::interval ORDER BY created_at ASC LIMIT 1 FOR UPDATE SKIP LOCKED", (install_id, COMMAND_TTL))
                    row = cur.fetchone()
                    if not row: return {"ok": True, "command": None}
                    cur.execute("UPDATE ucoa_device_commands SET status='claimed',claimed_at=now() WHERE id=%s", (row[0],))
            conn.close(); return {"ok": True, "command": {"id": row[0], "kind": row[1], "payload": row[2], "created_at": row[3].isoformat()}}
        except Exception as exc:
            try: conn.close()
            except Exception: pass
            raise HTTPException(503, f"command queue unavailable: {type(exc).__name__}")
    conn = sqlite3.connect(DB_PATH, timeout=15)
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT id,kind,payload,created_at FROM device_commands WHERE install_id=? AND status='queued' AND created_at > ? ORDER BY created_at ASC LIMIT 1", (install_id, time.time() - COMMAND_TTL)).fetchone()
        if not row:
            conn.commit(); return {"ok": True, "command": None}
        conn.execute("UPDATE device_commands SET status='claimed',claimed_at=? WHERE id=?", (time.time(), row[0])); conn.commit()
        return {"ok": True, "command": {"id": row[0], "kind": row[1], "payload": json.loads(row[2]), "created_at": row[3]}}
    finally: conn.close()


@app_v3.app.post("/v1/client/commands/{command_id}/result")
def complete_device_command(command_id: str, req: DeviceCommandResult, authorization: str | None = Header(default=None)):
    install_id, _ = _require_client(authorization)
    if not install_id or install_id != req.install_id: raise HTTPException(403, "install_id mismatch")
    status = req.status.strip().lower()
    if status not in {"completed", "failed", "cancelled"}: raise HTTPException(400, "Invalid command status")
    _ensure_schema(); result = json.dumps(req.result, ensure_ascii=False)[:50000]; conn = _pg_conn()
    if conn is not None:
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute("UPDATE ucoa_device_commands SET status=%s,completed_at=now(),result=%s::jsonb WHERE id=%s AND install_id=%s", (status, result, command_id, install_id))
                    if cur.rowcount != 1: raise HTTPException(404, "Command not found")
            conn.close(); return {"ok": True, "command_id": command_id, "status": status}
        except HTTPException: raise
        except Exception as exc:
            try: conn.close()
            except Exception: pass
            raise HTTPException(503, f"command storage unavailable: {type(exc).__name__}")
    conn = sqlite3.connect(DB_PATH, timeout=15)
    try:
        cur = conn.execute("UPDATE device_commands SET status=?,completed_at=?,result=? WHERE id=? AND install_id=?", (status, time.time(), result, command_id, install_id)); conn.commit()
        if cur.rowcount != 1: raise HTTPException(404, "Command not found")
    finally: conn.close()
    return {"ok": True, "command_id": command_id, "status": status}


@app_v3.app.get("/v1/admin/devices/{install_id}/commands/{command_id}")
def inspect_device_command(install_id: str, command_id: str, authorization: str | None = Header(default=None)):
    if not _master_ok(authorization): raise HTTPException(401, "Admin token required")
    _ensure_schema(); conn = _pg_conn()
    if conn is not None:
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT id,install_id,kind,payload,status,created_at,claimed_at,completed_at,result FROM ucoa_device_commands WHERE id=%s AND install_id=%s", (command_id, install_id)); row = cur.fetchone()
            conn.close()
            if not row: raise HTTPException(404, "Command not found")
            return {"ok": True, "command": {"id": row[0], "install_id": row[1], "kind": row[2], "payload": row[3], "status": row[4], "created_at": row[5].isoformat(), "claimed_at": row[6].isoformat() if row[6] else None, "completed_at": row[7].isoformat() if row[7] else None, "result": row[8]}}
        except HTTPException: raise
        except Exception:
            try: conn.close()
            except Exception: pass
    conn = sqlite3.connect(DB_PATH, timeout=15)
    try:
        row = conn.execute("SELECT id,install_id,kind,payload,status,created_at,claimed_at,completed_at,result FROM device_commands WHERE id=? AND install_id=?", (command_id, install_id)).fetchone()
        if not row: raise HTTPException(404, "Command not found")
        return {"ok": True, "command": {"id": row[0], "install_id": row[1], "kind": row[2], "payload": json.loads(row[3]), "status": row[4], "created_at": row[5], "claimed_at": row[6], "completed_at": row[7], "result": json.loads(row[8])}}
    finally: conn.close()


@app_v3.app.get("/v1/admin/devices")
def list_known_devices(authorization: str | None = Header(default=None)):
    if not _master_ok(authorization): raise HTTPException(401, "Admin token required")
    _ensure_schema(); conn = _pg_conn()
    if conn is not None:
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT DISTINCT install_id FROM ucoa_client_sessions WHERE expires_at > now() ORDER BY install_id"); devices = [r[0] for r in cur.fetchall()]
            conn.close(); return {"ok": True, "devices": devices}
        except Exception:
            try: conn.close()
            except Exception: pass
    conn = sqlite3.connect(DB_PATH, timeout=15)
    try:
        devices = [r[0] for r in conn.execute("SELECT DISTINCT install_id FROM client_sessions WHERE expires_at > ? ORDER BY install_id", (time.time(),)).fetchall()]
        return {"ok": True, "devices": devices}
    finally: conn.close()
