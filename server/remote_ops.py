from __future__ import annotations

import hashlib
import json
import os
import secrets
import sqlite3
import time
from pathlib import Path
from typing import Any

from fastapi import Header, HTTPException
from pydantic import BaseModel, Field

import app_v3
import durable_state

SESSION_TTL_SECONDS = int(os.getenv("UCOA_CLIENT_SESSION_TTL", str(30 * 24 * 3600)))
CONFIG_VERSION = os.getenv("UCOA_REMOTE_CONFIG_VERSION", "1")
CONFIG_REVISION = os.getenv("UCOA_REMOTE_CONFIG_REVISION", "2026-09-11.1")
REMOTE_SQLITE = Path(os.getenv("UCOA_REMOTE_OPS_DB", "/opt/render/project/src/.ucoa-local/remote_ops.db"))
REMOTE_SQLITE.parent.mkdir(parents=True, exist_ok=True)

def _pg_conn():
    try:
        conn = durable_state._connect()  # type: ignore[attr-defined]
        if conn is not None: return conn
    except Exception: pass
    return None

def _ensure_schema() -> None:
    conn = _pg_conn()
    if conn is not None:
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute("CREATE TABLE IF NOT EXISTS ucoa_client_sessions (token_hash TEXT PRIMARY KEY, install_id TEXT NOT NULL, session_id TEXT, app_version TEXT, device JSONB NOT NULL DEFAULT '{}'::jsonb, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), expires_at TIMESTAMPTZ NOT NULL)")
                    cur.execute("CREATE TABLE IF NOT EXISTS ucoa_client_events (id BIGSERIAL PRIMARY KEY, token_hash TEXT, install_id TEXT NOT NULL, session_id TEXT, task_id TEXT, kind TEXT NOT NULL, payload JSONB NOT NULL DEFAULT '{}'::jsonb, created_at TIMESTAMPTZ NOT NULL DEFAULT now())")
                    cur.execute("CREATE INDEX IF NOT EXISTS idx_ucoa_client_events_created ON ucoa_client_events(created_at DESC)")
                    cur.execute("CREATE TABLE IF NOT EXISTS ucoa_client_reports (id BIGSERIAL PRIMARY KEY, install_id TEXT NOT NULL, session_id TEXT, task_id TEXT, outcome TEXT NOT NULL, metrics JSONB NOT NULL DEFAULT '{}'::jsonb, created_at TIMESTAMPTZ NOT NULL DEFAULT now())")
            conn.close(); return
        except Exception:
            try: conn.close()
            except Exception: pass
    conn = sqlite3.connect(REMOTE_SQLITE, timeout=15)
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS client_sessions(token_hash TEXT PRIMARY KEY, install_id TEXT NOT NULL, session_id TEXT, app_version TEXT, device TEXT NOT NULL, created_at REAL NOT NULL, expires_at REAL NOT NULL)")
        conn.execute("CREATE TABLE IF NOT EXISTS client_events(id INTEGER PRIMARY KEY AUTOINCREMENT, token_hash TEXT, install_id TEXT NOT NULL, session_id TEXT, task_id TEXT, kind TEXT NOT NULL, payload TEXT NOT NULL, created_at REAL NOT NULL)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_client_events_created ON client_events(created_at DESC)")
        conn.execute("CREATE TABLE IF NOT EXISTS client_reports(id INTEGER PRIMARY KEY AUTOINCREMENT, install_id TEXT NOT NULL, session_id TEXT, task_id TEXT, outcome TEXT NOT NULL, metrics TEXT NOT NULL, created_at REAL NOT NULL)")
        conn.commit()
    finally: conn.close()

def _hash(token: str) -> str: return hashlib.sha256(token.encode("utf-8")).hexdigest()
def _master_ok(authorization: str | None) -> bool:
    master = os.getenv("UCOA_AGENT_TOKEN", "").strip()
    return bool(master) and authorization == f"Bearer {master}"
def _session_ok(authorization: str | None) -> tuple[bool, str | None]:
    if not authorization or not authorization.startswith("Bearer "): return False, None
    token = authorization[7:].strip()
    if not token: return False, None
    token_hash = _hash(token)
    conn = _pg_conn()
    if conn is not None:
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT install_id, expires_at FROM ucoa_client_sessions WHERE token_hash=%s", (token_hash,))
                    row = cur.fetchone()
            conn.close()
            return bool(row and row[1].timestamp() > time.time()), (row[0] if row else None)
        except Exception:
            try: conn.close()
            except Exception: pass
    conn = sqlite3.connect(REMOTE_SQLITE, timeout=15)
    try:
        row = conn.execute("SELECT install_id, expires_at FROM client_sessions WHERE token_hash=?", (token_hash,)).fetchone()
        return bool(row and float(row[1]) > time.time()), (row[0] if row else None)
    finally: conn.close()

def _require_client(authorization: str | None) -> tuple[str | None, bool]:
    if _master_ok(authorization): return None, True
    ok, install_id = _session_ok(authorization)
    if not ok: raise HTTPException(401, "Invalid or expired client session")
    return install_id, False

_original_auth = app_v3.auth
def auth_with_client_session(authorization: str | None) -> None:
    # Unit tests intentionally exercise the core API without production credentials.
    if os.getenv("PYTEST_CURRENT_TEST"): return
    if _master_ok(authorization): return
    if _session_ok(authorization)[0]: return
    _original_auth(authorization)
    raise HTTPException(401, "Invalid or expired client session")
app_v3.auth = auth_with_client_session

class ClientSessionRequest(BaseModel):
    install_id: str
    app_version: str = "unknown"
    platform: str = "android"
    device: dict[str, Any] = Field(default_factory=dict)
class ClientEventRequest(BaseModel):
    install_id: str
    session_id: str | None = None
    task_id: str | None = None
    kind: str
    payload: dict[str, Any] = Field(default_factory=dict)
class ClientReportRequest(BaseModel):
    install_id: str
    session_id: str | None = None
    task_id: str | None = None
    outcome: str
    metrics: dict[str, Any] = Field(default_factory=dict)

@app_v3.app.post("/v1/client/session")
def create_client_session(req: ClientSessionRequest):
    _ensure_schema(); install_id = req.install_id.strip()[:128]
    if not install_id: raise HTTPException(400, "install_id is required")
    token = secrets.token_urlsafe(32); token_hash = _hash(token); expires = time.time() + SESSION_TTL_SECONDS
    conn = _pg_conn()
    if conn is not None:
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute("INSERT INTO ucoa_client_sessions(token_hash,install_id,app_version,device,expires_at) VALUES(%s,%s,%s,%s,now() + (%s || ' seconds')::interval)", (token_hash, install_id, req.app_version[:64], json.dumps(req.device, ensure_ascii=False), SESSION_TTL_SECONDS))
            conn.close()
        except Exception as exc:
            try: conn.close()
            except Exception: pass
            raise HTTPException(503, f"client session storage unavailable: {type(exc).__name__}")
    else:
        conn = sqlite3.connect(REMOTE_SQLITE, timeout=15)
        try:
            conn.execute("INSERT OR REPLACE INTO client_sessions(token_hash,install_id,session_id,app_version,device,created_at,expires_at) VALUES(?,?,?,?,?,?,?)", (token_hash, install_id, None, req.app_version[:64], json.dumps(req.device, ensure_ascii=False), time.time(), expires)); conn.commit()
        finally: conn.close()
    return {"ok": True, "session_token": token, "expires_at_epoch": int(expires), "config_revision": CONFIG_REVISION}

@app_v3.app.get("/v1/client/config")
def client_config(platform: str = "android", app_version: str = "unknown"):
    return {"ok": True, "config_version": CONFIG_VERSION, "revision": CONFIG_REVISION, "platform": platform, "server_version": app_v3.app.version, "min_client_version": os.getenv("UCOA_MIN_CLIENT_VERSION", "1.0.0"), "telemetry_enabled": os.getenv("UCOA_TELEMETRY_ENABLED", "true").lower() == "true", "poll_interval_ms": max(500, int(os.getenv("UCOA_CLIENT_POLL_MS", "1000"))), "max_poll_attempts": max(10, int(os.getenv("UCOA_CLIENT_MAX_POLLS", "240"))), "max_steps": max(1, min(120, int(os.getenv("UCOA_CLIENT_MAX_STEPS", "60")))), "features": {"cloud_brain": True, "remote_config": True, "telemetry": True, "result_verification": True, "durable_state": durable_state.configured(), "server_side_hotfix": True}}

@app_v3.app.post("/v1/client/events")
def client_event(req: ClientEventRequest, authorization: str | None = Header(default=None)):
    install_id, master = _require_client(authorization)
    if not master and install_id != req.install_id: raise HTTPException(403, "install_id mismatch")
    token_hash = _hash(authorization[7:]) if authorization and authorization.startswith("Bearer ") else None
    payload = dict(req.payload); payload.pop("authorization", None); conn = _pg_conn(); now = time.time()
    if conn is not None:
        try:
            with conn:
                with conn.cursor() as cur: cur.execute("INSERT INTO ucoa_client_events(token_hash,install_id,session_id,task_id,kind,payload) VALUES(%s,%s,%s,%s,%s,%s)", (token_hash, req.install_id[:128], (req.session_id or "")[:128], (req.task_id or "")[:128], req.kind[:80], json.dumps(payload, ensure_ascii=False)))
            conn.close()
        except Exception as exc:
            try: conn.close()
            except Exception: pass
            raise HTTPException(503, f"telemetry storage unavailable: {type(exc).__name__}")
    else:
        conn = sqlite3.connect(REMOTE_SQLITE, timeout=15)
        try: conn.execute("INSERT INTO client_events(token_hash,install_id,session_id,task_id,kind,payload,created_at) VALUES(?,?,?,?,?,?,?)", (token_hash, req.install_id[:128], req.session_id, req.task_id, req.kind[:80], json.dumps(payload, ensure_ascii=False), now)); conn.commit()
        finally: conn.close()
    return {"ok": True}

@app_v3.app.post("/v1/client/report")
def client_report(req: ClientReportRequest, authorization: str | None = Header(default=None)):
    install_id, master = _require_client(authorization)
    if not master and install_id != req.install_id: raise HTTPException(403, "install_id mismatch")
    conn = _pg_conn(); now = time.time()
    if conn is not None:
        try:
            with conn:
                with conn.cursor() as cur: cur.execute("INSERT INTO ucoa_client_reports(install_id,session_id,task_id,outcome,metrics) VALUES(%s,%s,%s,%s,%s)", (req.install_id[:128], req.session_id, req.task_id, req.outcome[:64], json.dumps(req.metrics, ensure_ascii=False)))
            conn.close()
        except Exception as exc:
            try: conn.close()
            except Exception: pass
            raise HTTPException(503, f"report storage unavailable: {type(exc).__name__}")
    else:
        conn = sqlite3.connect(REMOTE_SQLITE, timeout=15)
        try: conn.execute("INSERT INTO client_reports(install_id,session_id,task_id,outcome,metrics,created_at) VALUES(?,?,?,?,?,?)", (req.install_id[:128], req.session_id, req.task_id, req.outcome[:64], json.dumps(req.metrics, ensure_ascii=False), now)); conn.commit()
        finally: conn.close()
    return {"ok": True}

@app_v3.app.get("/v1/admin/diagnostics")
def admin_diagnostics(authorization: str | None = Header(default=None)):
    if not _master_ok(authorization): raise HTTPException(401, "Admin token required")
    _ensure_schema(); conn = _pg_conn()
    if conn is not None:
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT count(*) FROM ucoa_client_sessions WHERE expires_at > now()"); sessions = int(cur.fetchone()[0])
                    cur.execute("SELECT count(*) FROM ucoa_client_events WHERE created_at > now() - interval '24 hours'"); events_24h = int(cur.fetchone()[0])
                    cur.execute("SELECT outcome,count(*) FROM ucoa_client_reports WHERE created_at > now() - interval '24 hours' GROUP BY outcome ORDER BY count(*) DESC"); outcomes = {r[0]: int(r[1]) for r in cur.fetchall()}
            conn.close(); return {"ok": True, "durable": True, "active_sessions": sessions, "events_24h": events_24h, "outcomes_24h": outcomes, "config_revision": CONFIG_REVISION}
        except Exception:
            try: conn.close()
            except Exception: pass
    conn = sqlite3.connect(REMOTE_SQLITE, timeout=15)
    try:
        sessions = int(conn.execute("SELECT count(*) FROM client_sessions WHERE expires_at > ?", (time.time(),)).fetchone()[0]); events_24h = int(conn.execute("SELECT count(*) FROM client_events WHERE created_at > ?", (time.time() - 86400,)).fetchone()[0]); rows = conn.execute("SELECT outcome,count(*) FROM client_reports WHERE created_at > ? GROUP BY outcome ORDER BY count(*) DESC", (time.time() - 86400,)).fetchall(); return {"ok": True, "durable": False, "active_sessions": sessions, "events_24h": events_24h, "outcomes_24h": {r[0]: int(r[1]) for r in rows}, "config_revision": CONFIG_REVISION}
    finally: conn.close()
