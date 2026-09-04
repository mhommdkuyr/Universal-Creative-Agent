#!/usr/bin/env bash
set -euo pipefail

ROOT="${UCOA_LOCAL_HOME:-/opt/render/project/src/.ucoa-local}"
BIN="$ROOT/llama-server"
MODEL="$ROOT/SmolVLM-256M-Instruct-Q8_0.gguf"
MMPROJ="$ROOT/mmproj-SmolVLM-256M-Instruct-Q8_0.gguf"
LLAMA_URL="${UCOA_LLAMA_URL:-https://github.com/ggml-org/llama.cpp/releases/download/b10586/llama-b10586-bin-ubuntu-x64.tar.gz}"
MODEL_URL="${UCOA_MODEL_URL:-https://huggingface.co/ggml-org/SmolVLM-256M-Instruct-GGUF/resolve/main/SmolVLM-256M-Instruct-Q8_0.gguf?download=true}"
MMPROJ_URL="${UCOA_MMPROJ_URL:-https://huggingface.co/ggml-org/SmolVLM-256M-Instruct-GGUF/resolve/main/mmproj-SmolVLM-256M-Instruct-Q8_0.gguf?download=true}"
MODEL_SHA256="${UCOA_MODEL_SHA256:-2a31195d3769c0b0fd0a4906201666108834848db768af11de1d2cef7cd35e65}"
MMPROJ_SHA256="${UCOA_MMPROJ_SHA256:-7e943f7c53f0382a6fc41b6ee0c2def63ba4fded9ab8ed039cc9e2ab905e0edd}"
LLAMA_SHA256="${UCOA_LLAMA_SHA256:-8fc43441b4d00d050589891c81e6b97d06039755af5d954deacf480b4f1f6b73}"

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

# The release may contain shared libraries beside llama-server. Keep them visible.
export LD_LIBRARY_PATH="$ROOT:${LD_LIBRARY_PATH:-}"

if [[ ! -f "$MODEL" ]]; then
  curl -fL --retry 3 --connect-timeout 20 "$MODEL_URL" -o "$MODEL.part"
  echo "$MODEL_SHA256  $MODEL.part" | sha256sum -c -
  mv "$MODEL.part" "$MODEL"
fi

if [[ ! -f "$MMPROJ" ]]; then
  curl -fL --retry 3 --connect-timeout 20 "$MMPROJ_URL" -o "$MMPROJ.part"
  echo "$MMPROJ_SHA256  $MMPROJ.part" | sha256sum -c -
  mv "$MMPROJ.part" "$MMPROJ"
fi

export UCOA_MODEL_BASE_URL="${UCOA_MODEL_BASE_URL:-http://127.0.0.1:8001/v1}"
export UCOA_MODEL_NAME="${UCOA_MODEL_NAME:-SmolVLM-256M-Instruct-Q8_0}"
export UCOA_LOCAL_MODEL="${UCOA_LOCAL_MODEL:-true}"
LOG="$ROOT/llama-server.log"
: > "$LOG"

# Fail early with a visible diagnostic if the native binary itself cannot execute.
if ! "$BIN" --version >> "$LOG" 2>&1; then
  cat "$LOG"
  exit 1
fi

"$BIN" \
  -m "$MODEL" \
  --mmproj "$MMPROJ" \
  --no-mmproj-offload \
  --host 127.0.0.1 \
  --port 8001 \
  --alias "$UCOA_MODEL_NAME" \
  -c "${UCOA_CONTEXT:-1536}" \
  -n "${UCOA_MAX_TOKENS:-384}" \
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
  tail -n 300 "$LOG" || true
  exit 1
fi

exec uvicorn app:app --host 0.0.0.0 --port "${PORT:-10000}"
