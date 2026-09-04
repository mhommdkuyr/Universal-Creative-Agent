#!/usr/bin/env bash
set -euo pipefail

ROOT="${UCOA_LOCAL_HOME:-/opt/render/project/src/.ucoa-local}"
BIN="$ROOT/llama-server"
LLAMA_URL="${UCOA_LLAMA_URL:-https://github.com/ggml-org/llama.cpp/releases/download/b10586/llama-b10586-bin-ubuntu-x64.tar.gz}"
LLAMA_SHA256="${UCOA_LLAMA_SHA256:-8fc43441b4d00d050589891c81e6b97d06039735af5d954deacf480b4f1f6b73}"
# Render Free: 512 MB RAM / 0.1 CPU. TensorBlock's verified Q2_K build is ~339 MB,
# leaving materially more headroom than the official Qwen Q2_K file (~415 MB).
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
  -c "${UCOA_CONTEXT:-384}" \
  -n "${UCOA_MAX_TOKENS:-64}" \
  -t "${UCOA_THREADS:-1}" \
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

cd /opt/render/project/src/server
exec uvicorn app:app --host 0.0.0.0 --port "${PORT:-10000}"
