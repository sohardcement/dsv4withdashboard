#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")"

BASELINE=${DS4_AGENT_BASELINE:-/tmp/ds4-live-baseline/live-old-all-after.json}
ARGS=(
  --restart-replay
  --compare-baseline "live-old=$BASELINE"
)

replace_live=0
dry_run=0
extra=()
while [ "$#" -gt 0 ]; do
  case "$1" in
    --replace-live)
      replace_live=1
      extra+=("$1")
      ;;
    --keep-server)
      # The runner's foreground child can die when the controlling PTY closes.
      # This wrapper starts the production server in tmux after a successful run.
      ;;
    --dry-run)
      dry_run=1
      extra+=("$1")
      ;;
    --)
      shift
      while [ "$#" -gt 0 ]; do
        extra+=("$1")
        shift
      done
      break
      ;;
    *)
      extra+=("$1")
      ;;
  esac
  shift
done

if [ "$replace_live" = 0 ]; then
  dry_run=1
  extra+=(--dry-run)
elif [ "${DS4_SKIP_IDLE_CHECK:-0}" != 1 ]; then
  ./agent-server-idle-check.sh "${DS4_PORT:-8077}"
fi

./agent-kv-sweep-run.py "${ARGS[@]}" "${extra[@]}"

if [ "$replace_live" = 1 ] && [ "$dry_run" = 0 ]; then
  if pgrep -x ds4-server >/dev/null 2>&1; then
    echo "ds4-server is already running after sweep; leaving it in place"
    exit 0
  fi

  if ! command -v tmux >/dev/null 2>&1; then
    echo "fail: tmux not found; cannot detach production 4096 server" >&2
    exit 1
  fi

  session=${DS4_LIVE_TMUX_SESSION:-ds4-live-4096}
  tmux kill-session -t "$session" 2>/dev/null || true
  rm -f /tmp/ds4.lock
  tmux new-session -d -s "$session" -c "$(pwd)" \
    "DS4_TRACE=/tmp/ds4-trace.jsonl DS4_KV_DIR=\$HOME/.ds4/server-kv DS4_CONTINUED_INTERVAL=4096 DS4_PREFILL_CHUNK=4096 DS4_BOUNDARY_ALIGN=2048 DS4_COLD_MAX=98304 DS4_CACHE_MIN=1024 ./start-server.sh"
  echo "started production 4096 server in tmux session: $session"
fi
