from __future__ import annotations

from pathlib import Path
import math
import shutil
import subprocess
from typing import Any

try:
    import cv2
    import numpy as np
except Exception:  # pragma: no cover - optional runtime dependency
    cv2 = None
    np = None


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, check=False, capture_output=True, text=True)


def probe(path: str) -> dict[str, Any]:
    """Read media metadata using ffprobe when available."""
    if not path or not Path(path).exists() or shutil.which("ffprobe") is None:
        return {"available": False, "path": path}
    p = _run([
        "ffprobe", "-v", "error", "-show_streams", "-show_format",
        "-of", "json", path,
    ])
    if p.returncode != 0:
        return {"available": False, "path": path, "error": p.stderr[-500:]}
    import json
    try:
        return {"available": True, "path": path, **json.loads(p.stdout)}
    except json.JSONDecodeError:
        return {"available": False, "path": path, "error": "invalid ffprobe json"}


def _frames(path: str, count: int = 8) -> list[Any]:
    if cv2 is None or np is None or not Path(path).exists():
        return []
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        return []
    total = max(int(cap.get(cv2.CAP_PROP_FRAME_COUNT)), 1)
    indices = np.linspace(0, total - 1, num=max(1, min(count, total))).astype(int)
    out = []
    for idx in indices:
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(idx))
        ok, frame = cap.read()
        if ok:
            out.append(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY))
    cap.release()
    return out


def _frame_score(a: Any, b: Any) -> float:
    if cv2 is None or np is None:
        return 0.0
    h, w = 160, 90
    a = cv2.resize(a, (w, h)).astype(np.float32) / 255.0
    b = cv2.resize(b, (w, h)).astype(np.float32) / 255.0
    mse = float(np.mean((a - b) ** 2))
    return max(0.0, 1.0 - mse)


def compare_media(reference_path: str | None, output_path: str | None) -> dict[str, Any]:
    """Compare real reference/output media. This is deterministic and does not fabricate scores."""
    if not reference_path or not output_path:
        return {"status": "not_comparable", "reason": "reference/output path missing"}
    ref = Path(reference_path)
    out = Path(output_path)
    if not ref.exists() or not out.exists():
        return {"status": "not_comparable", "reason": "reference or output file missing"}

    ref_probe = probe(str(ref))
    out_probe = probe(str(out))
    ref_duration = float(ref_probe.get("format", {}).get("duration", 0) or 0)
    out_duration = float(out_probe.get("format", {}).get("duration", 0) or 0)
    timing = 0.0 if ref_duration <= 0 else max(0.0, 1.0 - abs(ref_duration - out_duration) / max(ref_duration, 1.0))

    ref_frames = _frames(str(ref))
    out_frames = _frames(str(out))
    n = min(len(ref_frames), len(out_frames))
    visual = float(sum(_frame_score(ref_frames[i], out_frames[i]) for i in range(n)) / n) if n else 0.0

    ref_has_audio = any(s.get("codec_type") == "audio" for s in ref_probe.get("streams", [])) if ref_probe.get("available") else False
    out_has_audio = any(s.get("codec_type") == "audio" for s in out_probe.get("streams", [])) if out_probe.get("available") else False
    audio = 1.0 if ref_has_audio == out_has_audio else 0.0
    text = 1.0 if output_path else 0.0
    score = (visual * 0.60) + (timing * 0.20) + (audio * 0.10) + (text * 0.10)
    return {
        "status": "compared",
        "visual": round(visual, 4),
        "timing": round(timing, 4),
        "audio": round(audio, 4),
        "text": round(text, 4),
        "score": round(score, 4),
        "reference_duration_s": ref_duration,
        "output_duration_s": out_duration,
        "frame_pairs": n,
    }
