#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

MODEL="${DS4_MODEL:-/Users/shc/.lmstudio/models/antirez/glm-5.3-flash-gguf/GLM-5.3-Flash-Q2.gguf}"
HOST="${DS4_HOST:-127.0.0.1}"
PORT="${DS4_PORT:-8077}"
CTX="${DS4_CTX:-102400}"
THREADS="${DS4_THREADS:-8}"
TOKENS="${DS4_TOKENS:-2048}"
SESSIONS="${DS4_BATCHED_SESSION:-1}"
MIXED_PREFILL_QUANTUM="${DS4_MIXED_PREFILL_QUANTUM:-1024}"
KV_DIR="${DS4_KV_DIR:-$HOME/.ds4/glm53-server-kv}"
KV_SPACE_MB="${DS4_KV_SPACE_MB:-8192}"
FREQ_PEN="${DS4_FREQUENCY_PENALTY:-0.3}"
PRES_PEN="${DS4_PRESENCE_PENALTY:-0.0}"

if [[ ! -x "$ROOT_DIR/ds4-server" ]]; then
    echo "ds4-server not found: $ROOT_DIR/ds4-server" >&2
    echo "run 'make' first" >&2
    exit 2
fi

if [[ ! -f "$MODEL" ]]; then
    echo "model not found: $MODEL" >&2
    echo "set DS4_MODEL to a local GLM-5.3-Flash GGUF file" >&2
    exit 2
fi

mkdir -p "$KV_DIR"

echo "ds4 GLM 5.3 server: http://${HOST}:${PORT}" >&2
echo "model: $MODEL" >&2

exec "$ROOT_DIR/ds4-server" \
    --metal \
    --model "$MODEL" \
    --ctx "$CTX" \
    --tokens "$TOKENS" \
    --threads "$THREADS" \
    --host "$HOST" \
    --port "$PORT" \
    --batched-session "$SESSIONS" \
    --mixed-prefill-quantum "$MIXED_PREFILL_QUANTUM" \
    --kv-disk-dir "$KV_DIR" \
    --kv-disk-space-mb "$KV_SPACE_MB" \
    --frequency-penalty "$FREQ_PEN" \
    --presence-penalty "$PRES_PEN" \
    "$@"
