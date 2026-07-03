#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")"

TRACE=${DS4_TRACE:-/tmp/ds4-trace.jsonl}
KV_DIR=${DS4_KV_DIR:-"$HOME/.ds4/server-kv"}
LAST=${DS4_SUMMARY_LAST:-12}
STRICT=${DS4_CHECK_STRICT:-0}
PROFILE_ONLY=0

while [ "$#" -gt 0 ]; do
    case "$1" in
        --strict)
            STRICT=1
            ;;
        --profile-only)
            PROFILE_ONLY=1
            ;;
        *)
            echo "usage: $0 [--strict] [--profile-only]" >&2
            exit 2
            ;;
    esac
    shift
done

failed=0

desired_arg_value() {
    local flag=$1
    printf '%s\n' "$desired" | awk -v flag="$flag" '{
        for (i = 1; i <= NF; i++) {
            if ($i == flag && i < NF) {
                print $(i + 1)
                exit
            }
        }
    }'
}

live_arg_values() {
    local flag=$1
    printf '%s\n' "$live" | awk -v flag="$flag" '{
        for (i = 1; i <= NF; i++) {
            if ($i == flag && i < NF) {
                print $(i + 1)
            }
        }
    }' | sort -u
}

aligned_step() {
    local interval=$1
    local align=$2
    if [ -z "$interval" ] || [ "$interval" -le 0 ]; then
        echo 0
        return 0
    fi
    if [ -n "$align" ] && [ "$align" -gt 0 ]; then
        echo $(( ((interval + align - 1) / align) * align ))
    else
        echo "$interval"
    fi
}

check_expected_arg() {
    local flag=$1
    local label=${2:-$flag}
    local value
    value=$(desired_arg_value "$flag")
    if [ -z "$value" ]; then
        return 0
    fi

    if [ -z "$live" ]; then
        printf '  fail %-42s expected=%s actual=no-live-server\n' "$label" "$value"
        failed=1
        return 0
    fi

    local actual
    actual=$(live_arg_values "$flag")
    if printf '%s\n' "$actual" | grep -Fxq -- "$value"; then
        printf '  ok   %-42s %s\n' "$label" "$value"
    else
        printf '  fail %-42s expected=%s actual=%s\n' "$label" "$value" "${actual:-missing}"
        failed=1
    fi
}

echo "== live ds4-server =="
pids=$(pgrep -x 'ds4-server' || true)
if [ -n "$pids" ]; then
    live=$(ps -p "$(printf '%s\n' "$pids" | paste -sd, -)" -o pid=,command=)
else
    live=
fi
if [ -n "$live" ]; then
    echo "$live"
else
    echo "no ds4-server process found"
fi

echo
echo "== desired start-server command =="
desired=$(DS4_DRY_RUN=1 ./start-server.sh)
echo "$desired"

echo
echo "== desired profile applied? =="
check_expected_arg --ctx ctx
check_expected_arg --model model
check_expected_arg --threads threads
check_expected_arg --host host
check_expected_arg --port port
check_expected_arg --kv-disk-dir kv-disk-dir
check_expected_arg --kv-disk-space-mb kv-disk-space-mb
check_expected_arg --kv-cache-min-tokens kv-cache-min-tokens
check_expected_arg --kv-cache-cold-max-tokens kv-cache-cold-max-tokens
check_expected_arg --kv-cache-continued-interval-tokens kv-cache-continued-interval-tokens
check_expected_arg --kv-cache-boundary-trim-tokens kv-cache-boundary-trim-tokens
check_expected_arg --kv-cache-boundary-align-tokens kv-cache-boundary-align-tokens
check_expected_arg --tool-memory-max-ids tool-memory-max-ids
check_expected_arg --prefill-chunk prefill-chunk
check_expected_arg --mtp mtp
check_expected_arg --mtp-draft mtp-draft
check_expected_arg --mtp-margin mtp-margin
check_expected_arg --trace trace

if [ "$failed" != 0 ]; then
    echo "no - restart with ./start-server.sh when it is safe to interrupt clients"
else
    echo "yes"
fi

if [ "$PROFILE_ONLY" != 0 ]; then
    if [ "$STRICT" != 0 ] && [ "$failed" != 0 ]; then
        echo
        echo "profile check failed"
        exit 1
    fi
    exit 0
fi

echo
echo "== cache summary =="
summary_args=("$TRACE" --kv-dir "$KV_DIR" --last "$LAST")
if [ "$STRICT" != 0 ]; then
    continued_interval=$(desired_arg_value --kv-cache-continued-interval-tokens)
    boundary_align=$(desired_arg_value --kv-cache-boundary-align-tokens)
    continued_step=$(aligned_step "${continued_interval:-0}" "${boundary_align:-0}")
    summary_args+=(
        --gate
        --min-completed-requests 1
    )
    if [ "$continued_step" -gt 0 ]; then
        summary_args+=(
            --require-continued-frontier "$continued_step"
            --require-continued-frontier "$((continued_step * 2))"
        )
    fi
fi

if ! ./trace-cache-summary.py "${summary_args[@]}"; then
    failed=1
fi

echo
echo "== measurement gates =="
cat <<'EOF'
After restarting with the agent profile and running a mixed agent workload:
- Synthetic workload: ./agent-kv-workload.py --run
- Good: latest KV frontiers include 4096 or 8192 token continued checkpoints.
- Good: cache_source=disk-text appears after a restart or after switching back to a previous agent session.
- Good: cache_source=none requests are no longer dominated by first_mismatch_token around 5k-9k.
- If none remains high and first_mismatch_token is below 4096, KV tuning alone cannot recover much; the client prompt must move volatile blocks later or stabilize their ordering.
- If none remains high and first_mismatch_token is above 4096 but no disk-text appears, inspect KV frontiers and budget/eviction before changing model/runtime settings.
EOF

if [ "$STRICT" != 0 ] && [ "$failed" != 0 ]; then
    echo
    echo "strict check failed"
    exit 1
fi
