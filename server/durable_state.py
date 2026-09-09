from __future__ import annotations
import json, os, time
from typing import Any

try:
    import psycopg
except Exception:
    psycopg = None


def configured() -> bool:
    return bool(os.getenv("DATABASE_URL", "").strip()) and psycopg is not None


def _connect():
    if not configured():
        return None
    return psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=5)


def ensure_schema() -> bool:
    conn = _connect()
    if conn is None:
        return False
    with conn:
        with conn.cursor() as cur:
            cur.execute("CREATE TABLE IF NOT EXISTS ucoa_tasks (task_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, task_text TEXT NOT NULL, status TEXT NOT NULL, current_step INTEGER NOT NULL DEFAULT 0, checkpoint JSONB, plan JSONB, result JSONB, updated_at TIMESTAMPTZ NOT NULL DEFAULT now(), created_at TIMESTAMPTZ NOT NULL DEFAULT now())")
            cur.execute("CREATE TABLE IF NOT EXISTS ucoa_events (id BIGSERIAL PRIMARY KEY, task_id TEXT NOT NULL, event_type TEXT NOT NULL, payload JSONB NOT NULL DEFAULT '{}'::jsonb, created_at TIMESTAMPTZ NOT NULL DEFAULT now())")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_ucoa_events_task_created ON ucoa_events(task_id, created_at DESC)")
    return True


def save_state(task_id: str, session_id: str, task: str, step: int, status: str, state: dict[str, Any]) -> bool:
    conn = _connect()
    if conn is None:
        return False
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("INSERT INTO ucoa_tasks(task_id,session_id,task_text,status,current_step,plan,result) VALUES(%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(task_id) DO UPDATE SET session_id=excluded.session_id,task_text=excluded.task_text,status=excluded.status,current_step=excluded.current_step,plan=excluded.plan,result=excluded.result,updated_at=now()", (task_id,session_id,task,status,step,json.dumps(state.get('plan')) if state.get('plan') is not None else None,json.dumps(state)))
                cur.execute("INSERT INTO ucoa_events(task_id,event_type,payload) VALUES(%s,%s,%s)", (task_id,status,json.dumps({'step':step,'session_id':session_id})))
        return True
    except Exception:
        return False


def load_state(task_id: str) -> dict[str, Any] | None:
    conn = _connect()
    if conn is None:
        return None
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("SELECT task_id,session_id,task_text,status,current_step,result,updated_at FROM ucoa_tasks WHERE task_id=%s", (task_id,))
                row=cur.fetchone()
        if not row:return None
        return {'task_id':row[0],'session_id':row[1],'task':row[2],'status':row[3],'step':row[4],'result':row[5],'updated_at':row[6].isoformat() if row[6] else None}
    except Exception:
        return None


def recent_events(task_id: str, limit: int = 100) -> list[dict[str, Any]]:
    conn = _connect()
    if conn is None:return []
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("SELECT event_type,payload,created_at FROM ucoa_events WHERE task_id=%s ORDER BY created_at DESC LIMIT %s", (task_id,max(1,min(limit,500))))
                return [{'event_type':r[0],'payload':r[1],'created_at':r[2].isoformat() if r[2] else None} for r in cur.fetchall()]
    except Exception:
        return []
