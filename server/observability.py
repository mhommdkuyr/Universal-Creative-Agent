"""Low-overhead observability for UCOA.

Sentry is optional: when SENTRY_DSN is absent the helpers are no-ops.
Secrets and user payloads are intentionally excluded from telemetry.
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from time import perf_counter
from typing import Any, Iterator

try:
    import sentry_sdk
except Exception:  # pragma: no cover - optional dependency
    sentry_sdk = None  # type: ignore[assignment]

_INITIALIZED = False


def init_sentry() -> bool:
    global _INITIALIZED
    dsn = os.getenv("SENTRY_DSN", "").strip()
    if _INITIALIZED or not dsn or sentry_sdk is None:
        return _INITIALIZED
    sentry_sdk.init(
        dsn=dsn,
        traces_sample_rate=float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0.1")),
        send_default_pii=False,
        environment=os.getenv("SENTRY_ENVIRONMENT", "production"),
        release=os.getenv("UCOA_RELEASE", "unknown"),
    )
    _INITIALIZED = True
    return True


@contextmanager
def span(op: str, description: str, **data: Any) -> Iterator[None]:
    """Create an optional timing span without recording sensitive fields."""
    start = perf_counter()
    tx = None
    child = None
    try:
        init_sentry()
        if sentry_sdk is not None and _INITIALIZED:
            tx = sentry_sdk.Hub.current.scope.transaction if sentry_sdk.Hub.current.scope else None
            if tx is not None:
                child = tx.start_child(op=op, description=description, data={k: v for k, v in data.items() if k not in {"key", "token", "authorization", "image", "payload"}})
                child.__enter__()
        yield
    except Exception as exc:
        if sentry_sdk is not None and _INITIALIZED:
            sentry_sdk.capture_exception(exc)
        raise
    finally:
        if child is not None:
            child.set_data("duration_ms", round((perf_counter() - start) * 1000, 2))
            child.__exit__(None, None, None)


def set_measurement(name: str, value: float, unit: str = "millisecond") -> None:
    if sentry_sdk is None or not _INITIALIZED:
        return
    try:
        sentry_sdk.set_measurement(name, value, unit)
    except Exception:
        return
