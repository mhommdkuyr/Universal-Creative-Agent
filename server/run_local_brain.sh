#!/usr/bin/env bash
set -euo pipefail

ROOT="${UCOA_LOCAL_HOME:-/opt/render/project/src/.ucoa-local}"
BIN="$ROOT/llama-server"
LLAMA_URL="${UCOA_LLAMA_URL:-https://github.com/ggml-org/llama.cpp/releases/download/b10586/llama-b10586-bin-ubuntu-x64.tar.gz}"
LLAMA_SHA256="${UCOA_LLAMA_SHA256:-8fc43441b4d00d050589891c81e6b97d06039735af5d954deacf480b4f1f6b73}"
# Stable Render Free candidate: Qwen2.5-0.5B-Instruct Q2_K (339 MB).
MODEL_NAME="${UCOA_MODEL_NAME:-Qwen2.5-0.5B-Instruct-Q2_K}"
MODEL_REPO="${UCOA_MODEL_REPO:-tensorblock/Qwen2.5-0.5B-Instruct-GGUF}"
MODEL_TAG="${UCOA_MODEL_TAG:-Q2_K}"

mkdir -p "$ROOT"
if [[ ! -x "$BIN" ]]; then
  tmp="$ROOT/llama.tar.gz"
  curl -fL --retry 3 --connect-timeout 20 "$LLAMA_URL" -o "$tmp"
  echo "$LLAMA_SHA256  $tmp" | sha256sum -c -
  tar -xzf "$tmp" -C "$ROOT"
  found="$(find "$ROOT" -type f -name llama-server -print -quit)"
  test -n "$found"
  cp -a "$(dirname "$found")"/. "$ROOT"/
  test -x "$BIN"
  rm -f "$tmp"
fi

export LD_LIBRARY_PATH="$ROOT:${LD_LIBRARY_PATH:-}"
export UCOA_MODEL_BASE_URL="${UCOA_MODEL_BASE_URL:-http://127.0.0.1:8001/v1}"
export UCOA_MODEL_NAME="$MODEL_NAME"
export UCOA_LOCAL_MODEL="true"
export UCOA_LOCAL_VISION="false"
LOG="$ROOT/llama-server.log"
: > "$LOG"

"$BIN" \
  -hf "$MODEL_REPO:$MODEL_TAG" \
  --host 127.0.0.1 \
  --port 8001 \
  --alias "$MODEL_NAME" \
  -c "${UCOA_CONTEXT:-256}" \
  -n "${UCOA_MAX_TOKENS:-48}" \
  -t "${UCOA_THREADS:-1}" \
  --cache-type-k "${UCOA_CACHE_TYPE_K:-q4_0}" \
  --cache-type-v "${UCOA_CACHE_TYPE_V:-q4_0}" \
  -np 1 \
  > "$LOG" 2>&1 &
LLAMA_PID=$!
cleanup() { kill "$LLAMA_PID" 2>/dev/null || true; }
trap cleanup EXIT INT TERM

for _ in $(seq 1 150); do
  if ! kill -0 "$LLAMA_PID" 2>/dev/null; then
    echo "LOCAL_BRAIN_PROCESS_EXITED"
    tail -n 200 "$LOG" || true
    exit 1
  fi
  if curl -fsS --max-time 2 "$UCOA_MODEL_BASE_URL/models" >/dev/null 2>&1; then
    echo "LOCAL_BRAIN_READY"
    break
  fi
  sleep 2
done

if ! curl -fsS --max-time 5 "$UCOA_MODEL_BASE_URL/models" >/dev/null 2>&1; then
  echo "LOCAL_BRAIN_TIMEOUT"
  tail -n 200 "$LOG" || true
  exit 1
fi

# Real startup inference probe. Public readiness is granted only after local inference works.
SELFTEST="$ROOT/selftest.json"
cat > "$ROOT/selftest-payload.json" <<JSON
{"model":"$MODEL_NAME","temperature":0,"max_tokens":24,"messages":[{"role":"system","content":"Answer briefly in Arabic."},{"role":"user","content":"قل فقط: أنا جاهز لتنفيذ مهمة على الهاتف."}]}
JSON
if curl -fsS --max-time 90 -H 'Content-Type: application/json' -X POST "$UCOA_MODEL_BASE_URL/chat/completions" --data-binary @"$ROOT/selftest-payload.json" -o "$SELFTEST"; then
  if python - "$SELFTEST" <<'PY'
import json, sys
x=json.load(open(sys.argv[1], encoding='utf-8'))
content=x.get('choices',[{}])[0].get('message',{}).get('content','').strip()
assert content
print('LOCAL_BRAIN_INFERENCE_OK', content)
PY
  then :; else
    echo "LOCAL_BRAIN_INFERENCE_INVALID"; cat "$SELFTEST" || true; tail -n 200 "$LOG" || true; exit 1
  fi
else
  echo "LOCAL_BRAIN_INFERENCE_FAILED"; cat "$SELFTEST" || true; tail -n 200 "$LOG" || true; exit 1
fi

# The full agent plan/step lifecycle is exercised externally by GitHub Actions after the port is open.
cd /opt/render/project/src/server
exec uvicorn app:app --host 0.0.0.0 --port "${PORT:-10000}"
