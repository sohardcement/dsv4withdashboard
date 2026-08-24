#!/bin/bash
set -euo pipefail

root=$(cd "$(dirname "$0")/.." && pwd)
statusbar="$root/ds4-statusbar"

if [ ! -x "$statusbar" ]; then
	echo "ds4_statusbar_test: missing executable: $statusbar" >&2
	exit 1
fi

assert_render() {
	local name=$1 input=$2 expected=$3 actual
	actual=$(printf '%s\n' "$input" | "$statusbar" --render-status)
	if [ "$actual" != "$expected" ]; then
		printf 'ds4_statusbar_test: %s failed\nexpected: %s\nactual:   %s\n' \
			"$name" "$expected" "$actual" >&2
		exit 1
	fi
}

assert_render "decode shows both live rates" \
	'{"active":true,"phase":"decode","prefill":{"avg_tps":118.4},"decode":{"avg_tps":15.3}}' \
	'D 15.3 · P 118'

assert_render "prefill shows only the active phase" \
	'{"active":true,"phase":"prefill","prefill":{"avg_tps":1850.4},"decode":{"avg_tps":0}}' \
	'P 1.9k'

assert_render "idle does not present retained rates as live" \
	'{"active":false,"phase":"idle","prefill":{"avg_tps":118.4},"decode":{"avg_tps":15.3}}' \
	'DS4 空闲'

assert_render "invalid status is offline" \
	'{not-json}' \
	'DS4 离线'

echo "ds4_statusbar_test: all tests passed"
