#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")"

# Profiles:
#   agent        Default for Claude Code / Codex / Hermes-style clients with
#                sampled generation, large prompts, tools, and long sessions.
#   greedy       Agent settings plus MTP for temperature-zero generation.
#   conservative Smaller cache footprint for occasional API use.
PROFILE=${DS4_PROFILE:-agent}
HOST=${DS4_HOST:-127.0.0.1}
PORT=${DS4_PORT:-8077}
TRACE=${DS4_TRACE-/tmp/ds4-trace.jsonl}
SERVER_LOG=${DS4_SERVER_LOG-}
MTP_METRICS=${DS4_MTP_METRICS:-0}
if [ -n "$TRACE" ]; then
    DEFAULT_CONFIG_SNAPSHOT="${TRACE}.config"
else
    DEFAULT_CONFIG_SNAPSHOT=
fi
CONFIG_SNAPSHOT=${DS4_CONFIG_SNAPSHOT-$DEFAULT_CONFIG_SNAPSHOT}
EXTRA_SSD_STREAMING=0
EXTRA_MTP=0

for arg in "$@"; do
    case "$arg" in
        --ssd-streaming)
            EXTRA_SSD_STREAMING=1
            ;;
        --mtp)
            EXTRA_MTP=1
            ;;
    esac
done

case "$PROFILE" in
    agent|greedy)
        DEFAULT_MODEL="/Users/shc/.lmstudio/models/huihui-ai/Huihui-DeepSeek-V4-Flash-abliterated-ds4-GGUF/Huihui-DeepSeek-V4-Flash-BF16-abliterated-ds4-Q2.gguf"
        DEFAULT_CTX=51200
        DEFAULT_THREADS=8
        # Matched M3 Max runs at a >16K context allocation favored 5120 over
        # 4096 for long prefill without the short-frontier regression of 6144.
        DEFAULT_PREFILL_CHUNK=5120
        DEFAULT_KV_DIR="$HOME/.ds4/server-kv"
        DEFAULT_KV_SPACE=163840
        DEFAULT_COLD_MAX=98304
        # Keep the measured 2048 disk-KV cadence. Prefill chunk boundaries may
        # coalesce writes, while the larger disk budget absorbs the checkpoints.
        DEFAULT_CONTINUED_INTERVAL=2048
        DEFAULT_CACHE_MIN=1024
        DEFAULT_BOUNDARY_TRIM=64
        DEFAULT_BOUNDARY_ALIGN=2048
        DEFAULT_TOOL_MEMORY_MAX=200000
        DEFAULT_MTP_PATH=
        if [ "$PROFILE" = greedy ]; then
            DEFAULT_MTP_PATH="gguf/DeepSeek-V4-Flash-MTP-Q4K-Q8_0-F32.gguf"
        fi
        DEFAULT_MTP_DRAFT=2
        DEFAULT_MTP_MARGIN=3.0
        ;;
    conservative)
        DEFAULT_MODEL="/Users/shc/.lmstudio/models/huihui-ai/Huihui-DeepSeek-V4-Flash-abliterated-ds4-GGUF/Huihui-DeepSeek-V4-Flash-BF16-abliterated-ds4-Q2.gguf"
        DEFAULT_CTX=100000
        DEFAULT_THREADS=8
        DEFAULT_PREFILL_CHUNK=0
        DEFAULT_KV_DIR="$HOME/.ds4/server-kv"
        DEFAULT_KV_SPACE=8192
        DEFAULT_COLD_MAX=50000
        DEFAULT_CONTINUED_INTERVAL=10000
        DEFAULT_CACHE_MIN=512
        DEFAULT_BOUNDARY_TRIM=32
        DEFAULT_BOUNDARY_ALIGN=2048
        DEFAULT_TOOL_MEMORY_MAX=100000
        DEFAULT_MTP_PATH=
        DEFAULT_MTP_DRAFT=1
        DEFAULT_MTP_MARGIN=3.0
        ;;
    *)
        echo "unknown DS4_PROFILE: $PROFILE (expected: agent, greedy, or conservative)" >&2
        exit 2
        ;;
esac

KV_SPACE_FILE=${DS4_KV_SPACE_FILE:-$HOME/.ds4/kv-space-mb}
case "$KV_SPACE_FILE" in
    *$'\r'*|*$'\n'*)
        echo "invalid DS4_KV_SPACE_FILE: path must not contain CR or LF" >&2
        exit 2
        ;;
esac
SAVED_KV_SPACE=
kv_space_valid() {
    local value=$1 normalized
    [[ "$value" =~ ^[0-9]+$ ]] || return 1
    normalized=${value#"${value%%[!0]*}"}
    [ -n "$normalized" ] || normalized=0
    [ ${#normalized} -lt 10 ] || {
        [ ${#normalized} -eq 10 ] && [[ ! "$normalized" > 2147483647 ]]
    } || return 1
    [ "$normalized" -ge 256 ]
}

if [ -e "$KV_SPACE_FILE" ]; then
    if [ -r "$KV_SPACE_FILE" ]; then
        SAVED_KV_SPACE=$(<"$KV_SPACE_FILE")
        if ! kv_space_valid "$SAVED_KV_SPACE"; then
            echo "ignoring invalid KV capacity in $KV_SPACE_FILE (expected integer >= 256 MiB)" >&2
            SAVED_KV_SPACE=
        fi
    else
        echo "ignoring unreadable KV capacity file: $KV_SPACE_FILE" >&2
    fi
fi

CTX_FILE=${DS4_CTX_FILE:-$HOME/.ds4/context-tokens}
case "$CTX_FILE" in
    *$'\r'*|*$'\n'*)
        echo "invalid DS4_CTX_FILE: path must not contain CR or LF" >&2
        exit 2
        ;;
esac
context_valid() {
    local value=$1 normalized
    [[ "$value" =~ ^[0-9]+$ ]] || return 1
    normalized=${value#"${value%%[!0]*}"}
    [ -n "$normalized" ] || normalized=0
    [ ${#normalized} -lt 10 ] || {
        [ ${#normalized} -eq 10 ] && [[ ! "$normalized" > 2147483647 ]]
    } || return 1
    [ "$normalized" -ge 4096 ]
}
SAVED_CTX=
if [ -e "$CTX_FILE" ]; then
    if [ -r "$CTX_FILE" ]; then
        SAVED_CTX=$(<"$CTX_FILE")
        if ! context_valid "$SAVED_CTX"; then
            echo "ignoring invalid saved context in $CTX_FILE (expected integer 4096..2147483647)" >&2
            SAVED_CTX=
        fi
    else
        echo "ignoring unreadable saved context file: $CTX_FILE" >&2
    fi
fi

MODEL=${DS4_MODEL-$DEFAULT_MODEL}
if [ -n "${DS4_CTX+x}" ]; then
    if context_valid "$DS4_CTX"; then
        CTX=$DS4_CTX
    else
        echo "ignoring invalid DS4_CTX (expected integer 4096..2147483647)" >&2
        CTX=${SAVED_CTX:-$DEFAULT_CTX}
    fi
else
    CTX=${SAVED_CTX:-$DEFAULT_CTX}
fi
THREADS=${DS4_THREADS:-$DEFAULT_THREADS}
PREFILL_CHUNK=${DS4_PREFILL_CHUNK:-$DEFAULT_PREFILL_CHUNK}
KV_DIR=${DS4_KV_DIR:-$DEFAULT_KV_DIR}
if [ -n "${DS4_KV_SPACE+x}" ]; then
    if kv_space_valid "$DS4_KV_SPACE"; then
        KV_SPACE=$DS4_KV_SPACE
    else
        echo "ignoring invalid DS4_KV_SPACE (expected integer >= 256 MiB)" >&2
        KV_SPACE=${SAVED_KV_SPACE:-$DEFAULT_KV_SPACE}
    fi
else
    KV_SPACE=${SAVED_KV_SPACE:-$DEFAULT_KV_SPACE}
fi
COLD_MAX=${DS4_COLD_MAX:-$DEFAULT_COLD_MAX}
CONTINUED_INTERVAL=${DS4_CONTINUED_INTERVAL:-$DEFAULT_CONTINUED_INTERVAL}
CACHE_MIN=${DS4_CACHE_MIN:-$DEFAULT_CACHE_MIN}
BOUNDARY_TRIM=${DS4_BOUNDARY_TRIM:-$DEFAULT_BOUNDARY_TRIM}
BOUNDARY_ALIGN=${DS4_BOUNDARY_ALIGN:-$DEFAULT_BOUNDARY_ALIGN}
TOOL_MEMORY_MAX=${DS4_TOOL_MEMORY_MAX:-$DEFAULT_TOOL_MEMORY_MAX}
if [ "$HOST" = "0.0.0.0" ] || [ "$HOST" = "::" ]; then
    DASHBOARD_HOST=127.0.0.1
else
    DASHBOARD_HOST=$HOST
fi
DASHBOARD_URL="http://${DASHBOARD_HOST}:${PORT}/"
if [ -n "$DEFAULT_MTP_PATH" ] && [ ! -f "$DEFAULT_MTP_PATH" ]; then
    DEFAULT_MTP_PATH=
fi
MTP_PATH_SET=${DS4_MTP_PATH+x}
MTP_PATH=${DS4_MTP_PATH-$DEFAULT_MTP_PATH}
MTP_DRAFT=${DS4_MTP_DRAFT:-$DEFAULT_MTP_DRAFT}
MTP_MARGIN=${DS4_MTP_MARGIN:-$DEFAULT_MTP_MARGIN}

if [ -n "$MODEL" ] && [ ! -f "$MODEL" ]; then
    echo "model not found: $MODEL" >&2
    echo "DS4_MODEL must point to a local GGUF file; Hugging Face safetensors repos such as DeepSeek-V4-Flash-DSpark are not direct ds4-server --model inputs." >&2
    exit 2
fi

if [ "$EXTRA_MTP" != 0 ]; then
    MTP_PATH=
fi

if [ "$EXTRA_SSD_STREAMING" != 0 ] && [ -n "$MTP_PATH" ]; then
    if [ -n "$MTP_PATH_SET" ]; then
        echo "DS4_MTP_PATH cannot be combined with --ssd-streaming; unset it or remove --ssd-streaming" >&2
        exit 2
    fi
    # ds4 currently rejects --ssd-streaming with --mtp. Keep ad-hoc streaming
    # tests from accidentally inheriting the agent profile's default MTP.
    MTP_PATH=
fi

args=(
    ./ds4-server
    --ctx "$CTX"
    --threads "$THREADS"
    --host "$HOST"
    --port "$PORT"
    --kv-disk-dir "$KV_DIR"
    --kv-disk-space-mb "$KV_SPACE"
    --kv-cache-min-tokens "$CACHE_MIN"
    --kv-cache-cold-max-tokens "$COLD_MAX"
    --kv-cache-continued-interval-tokens "$CONTINUED_INTERVAL"
    --kv-cache-boundary-trim-tokens "$BOUNDARY_TRIM"
    --kv-cache-boundary-align-tokens "$BOUNDARY_ALIGN"
    --tool-memory-max-ids "$TOOL_MEMORY_MAX"
)

if [ -n "$PREFILL_CHUNK" ] && [ "$PREFILL_CHUNK" != 0 ]; then
    args+=(--prefill-chunk "$PREFILL_CHUNK")
fi

if [ -n "$MODEL" ]; then
    args+=(--model "$MODEL")
fi

if [ -n "$MTP_PATH" ]; then
    if [ ! -f "$MTP_PATH" ]; then
        echo "MTP model not found: $MTP_PATH" >&2
        exit 2
    fi
    args+=(--mtp "$MTP_PATH" --mtp-draft "$MTP_DRAFT" --mtp-margin "$MTP_MARGIN")
fi

if [ -n "$TRACE" ]; then
    args+=(--trace "$TRACE")
fi

if [ "${DS4_DRY_RUN:-0}" != 0 ]; then
    printf '%q ' "${args[@]}" "$@"
    printf '\n'
    exit 0
fi

mkdir -p "$KV_DIR"

if [ "${DS4_TRACE_RESET:-0}" != 0 ] && [ -n "$TRACE" ]; then
    : > "$TRACE"
fi

if [ -n "$CONFIG_SNAPSHOT" ]; then
    mkdir -p "$(dirname "$CONFIG_SNAPSHOT")"
    printf -v COMMAND_LINE '%q ' "${args[@]}" "$@"
    {
        printf 'started_at=%s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
        printf 'cwd=%s\n' "$(pwd)"
        printf 'command_line=%s\n' "$COMMAND_LINE"
        printf 'profile=%s\n' "$PROFILE"
        printf 'model=%s\n' "$MODEL"
        printf 'ctx=%s\n' "$CTX"
		printf 'ctx_file=%s\n' "$CTX_FILE"
        printf 'threads=%s\n' "$THREADS"
        printf 'host=%s\n' "$HOST"
        printf 'port=%s\n' "$PORT"
        printf 'dashboard_url=%s\n' "$DASHBOARD_URL"
        printf 'trace=%s\n' "$TRACE"
        printf 'server_log=%s\n' "$SERVER_LOG"
        printf 'kv_dir=%s\n' "$KV_DIR"
        printf 'kv_space_file=%s\n' "$KV_SPACE_FILE"
        printf 'kv_space_mb=%s\n' "$KV_SPACE"
        printf 'cache_min=%s\n' "$CACHE_MIN"
        printf 'cold_max=%s\n' "$COLD_MAX"
        printf 'continued_interval=%s\n' "$CONTINUED_INTERVAL"
        printf 'boundary_trim=%s\n' "$BOUNDARY_TRIM"
        printf 'boundary_align=%s\n' "$BOUNDARY_ALIGN"
        printf 'tool_memory_max_ids=%s\n' "$TOOL_MEMORY_MAX"
        printf 'prefill_chunk=%s\n' "$PREFILL_CHUNK"
        printf 'mtp_path=%s\n' "$MTP_PATH"
        printf 'mtp_draft=%s\n' "$MTP_DRAFT"
        printf 'mtp_margin=%s\n' "$MTP_MARGIN"
        printf 'mtp_metrics=%s\n' "$MTP_METRICS"
        printf 'config_snapshot=%s\n' "$CONFIG_SNAPSHOT"
    } > "$CONFIG_SNAPSHOT"
fi

if [ "$MTP_METRICS" != 0 ]; then
    export DS4_MTP_TIMING=${DS4_MTP_TIMING:-1}
    export DS4_MTP_CONF_LOG=${DS4_MTP_CONF_LOG:-1}
fi

echo "ds4 dashboard: $DASHBOARD_URL" >&2

if [ -n "$SERVER_LOG" ]; then
    mkdir -p "$(dirname "$SERVER_LOG")"
    exec "${args[@]}" "$@" >> "$SERVER_LOG" 2>&1
fi

exec "${args[@]}" "$@"
