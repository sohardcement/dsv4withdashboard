#!/bin/bash
set -euo pipefail

PORT=${1:-${DS4_PORT:-8077}}

if ! command -v lsof >/dev/null 2>&1; then
  echo "fail: lsof not found; cannot prove ds4-server is idle" >&2
  exit 2
fi

listeners=$(lsof -nP -iTCP:"$PORT" -sTCP:LISTEN 2>/dev/null || true)
active=$(lsof -nP -iTCP:"$PORT" -sTCP:ESTABLISHED 2>/dev/null || true)

if [ -z "$listeners" ]; then
  echo "no listener on tcp:$PORT"
  exit 0
fi

echo "listener on tcp:$PORT:"
printf '%s\n' "$listeners"

if [ -n "$active" ]; then
  echo
  echo "active tcp connections on tcp:$PORT:" >&2
  printf '%s\n' "$active" >&2
  echo "fail: ds4-server is not idle; retry later or set DS4_SKIP_IDLE_CHECK=1 to override" >&2
  exit 1
fi

echo "idle: no established tcp connections on tcp:$PORT"
