#!/usr/bin/env bash
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
port=${DS4_DASHBOARD_TEST_PORT:-8766}
cache=${npm_config_cache:-"$root/output/playwright/npm-cache"}
mkdir -p "$root/output/playwright"
python3 "$root/tests/dashboard_fixture.py" "$root/ds4_server.c" "$port" &
fixture=$!
trap 'kill "$fixture" 2>/dev/null || true' EXIT
for _ in $(seq 1 50); do curl -fsS "http://127.0.0.1:$port/fixture/state" >/dev/null 2>&1 && break; sleep .1; done
export npm_config_cache="$cache"
cli=(npx --yes --package @playwright/cli playwright-cli -s=ds4-dashboard-test)
"${cli[@]}" open "http://127.0.0.1:$port" >/dev/null
trap '"${cli[@]}" close >/dev/null 2>&1 || true; kill "$fixture" 2>/dev/null || true' EXIT
set +e
run_output=$("${cli[@]}" run-code --filename "$root/tests/dashboard_ui_test.js" 2>&1)
run_status=$?
set -e
printf '%s\n' "$run_output"
if [[ "$run_status" -ne 0 || "$run_output" == *"### Error"* ]]; then
  exit 1
fi
