#!/usr/bin/env bash
set -euo pipefail

ROOT="${UCOA_LOCAL_HOME:-/opt/render/project/src/.ucoa-local}"
BIN="$ROOT/llama-server"
LLAMA_URL="${UCOA_LLAMA_URL:-https://github.com/ggml-org/llama.cpp/releases/download/b10586/llama-b10586-bin-ubuntu-x64.tar.gz}"
LLAMA_SHA256="${UCOA_LLAMA_SHA256:-8fc43441b4d00d050589891c81e6b97d06039735af5d954deacf480b4f1f6b73}"
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
# Vision is supplied by the Hugging Face Qwen3-VL Space/router; the local Render LLM remains text-only.
export UCOA_LOCAL_VISION="${UCOA_LOCAL_VISION:-true}"
export UCOA_VISION_MODEL="${UCOA_VISION_MODEL:-Qwen/Qwen3-VL-2B-Instruct}"
export UCOA_VISION_SPACE_URL="${UCOA_VISION_SPACE_URL:-https://akhaliq-qwen3-vl-2b-instruct.hf.space}"
export UCOA_REASONING_MODEL="${UCOA_REASONING_MODEL:-Qwen/Qwen3-4B-Instruct-2507}"
LOG="$ROOT/llama-server.log"
: > "$LOG"

"$BIN" \
  -hf "$MODEL_REPO:$MODEL_TAG" \
  --host 127.0.0.1 \
  --port 8001 \
  --alias "$MODEL_NAME" \
  -c "${UCOA_CONTEXT:-192}" \
  -n "${UCOA_MAX_TOKENS:-64}" \
  -t "${UCOA_THREADS:-1}" \
  --cache-type-k "${UCOA_CACHE_TYPE_K:-q2_K}" \
  --cache-type-v "${UCOA_CACHE_TYPE_V:-q2_K}" \
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

cd /opt/render/project/src/server
exec uvicorn app:app --host 0.0.0.0 --port "${PORT:-10000}"
