# Agent KV Cache Tuning

This note records the current sweet-spot candidate for DS4 when serving coding
agents such as Claude Code, Codex, ChatWise, and HermesAgent. These clients tend
to send large system prompts, tool schemas, skill lists, and changing memory
blocks. The main latency problem is therefore early prompt divergence causing a
full prefill, not raw decode speed.

## Current Agent Profile

Use `./start-server.sh` with the default `DS4_PROFILE=agent`:

```sh
./start-server.sh
```

Important defaults:

```text
--model ds4flash.gguf
--ctx 204800
--kv-disk-dir ~/.ds4/server-kv
--kv-disk-space-mb 81920
--kv-cache-cold-max-tokens 98304
--kv-cache-continued-interval-tokens 4096
--kv-cache-boundary-trim-tokens 64
--kv-cache-boundary-align-tokens 2048
--tool-memory-max-ids 200000
--prefill-chunk 4096
--mtp gguf/DeepSeek-V4-Flash-MTP-Q4K-Q8_0-F32.gguf
--mtp-draft 4
--mtp-margin 3.0
--trace /tmp/ds4-trace.jsonl
```

## Model Choice

The default `ds4flash.gguf` symlink should remain explicit in `start-server.sh`
so tuning results always identify the main model being served. On this machine it
points at:

```text
gguf/DeepSeek-V4-Flash-IQ2XXS-w2Q2K-AProjQ8-SExpQ8-OutQ8-chat-v2.gguf
```

That is already the 2-bit/IQ2XXS Flash GGUF from
[`antirez/deepseek-v4-gguf`](https://huggingface.co/antirez/deepseek-v4-gguf).
The same repository also publishes the optional
`DeepSeek-V4-Flash-MTP-Q4K-Q8_0-F32.gguf` speculative-decoding model used by the
agent profile.

[`deepseek-ai/DeepSeek-V4-Flash-DSpark`](https://huggingface.co/deepseek-ai/DeepSeek-V4-Flash-DSpark)
is not a drop-in GGUF replacement for `ds4-server`; its files are safetensors
checkpoint shards plus an additional speculative decoding module. The upstream
README also describes it as the same checkpoint with speculative decoding
attached, not a new base model. In this repo, the practical speed question is
therefore whether the local MTP GGUF improves decode on real agent workloads,
not whether pointing `DS4_MODEL` at the DSpark Hugging Face repo will work.

Use `DS4_MODEL=/path/to/local.gguf ./start-server.sh` only for local GGUF files.
The start script fails early if the path does not exist, because an invalid model
path would otherwise make profile checks and sweep results ambiguous.

The start script writes a sidecar config snapshot next to the trace
(`/tmp/ds4-trace.jsonl.config` by default). `trace-cache-summary.py --json`
loads that sidecar automatically so saved metrics retain the startup profile
even when summarized from a different shell. The snapshot also records
`started_at`, `cwd`, and the full `command_line` for traceability.

The 4096 continued interval is intentional. Agent traces showed repeated
`first_mismatch_token` values around 5k-9k tokens. With the old 10000 interval,
the aligned checkpoint step was 10240, so disk KV checkpoints landed after the
dynamic skill/system block divergence and could not help. A 4096 interval leaves
a reusable checkpoint before both 5k and 9k divergence points, while keeping file
count manageable under the 80 GiB cache budget.

The MTP options are enabled only when the local MTP GGUF exists. They target
decode throughput; they do not fix prompt prefill misses. Disable them with:

```sh
DS4_MTP_PATH= ./start-server.sh
```

For short measurement runs, enable MTP stderr metrics and capture the server log:

```sh
DS4_MTP_METRICS=1 DS4_SERVER_LOG=/tmp/ds4-server.log ./start-server.sh
```

This exports `DS4_MTP_TIMING=1` and `DS4_MTP_CONF_LOG=1` for the server process
unless those variables are already set. `trace-cache-summary.py --server-log`
parses the resulting `ds4: mtp timing ...` lines and reports draft attempts,
drafted/committed tokens, acceptance rate, full/partial accepts, and average
draft/verify/snapshot/replay timings. Keep it off for normal long-running agent
service unless you are actively measuring; it logs per speculative decode
attempt.

`--ssd-streaming` is currently incompatible with `--mtp` in the engine. The
start script therefore drops the default MTP option when `--ssd-streaming` is
passed as an extra argument:

```sh
DS4_DRY_RUN=1 ./start-server.sh --ssd-streaming
```

If `DS4_MTP_PATH` is explicitly set together with `--ssd-streaming`, the script
fails early instead of letting `ds4-server` fail during model initialization.

## Safe Measurement Loop

Do not restart the server while an agent client is mid-request. When it is safe:

```sh
DS4_TRACE_RESET=1 ./start-server.sh
```

Then run a representative mixed workload:

- one Claude Code session with tools enabled
- one Codex session with its normal project prompt
- one HermesAgent or ChatWise-style session if available
- at least one session switch or restart-like replay to test disk cache reuse

For a repeatable synthetic workload that exercises those three client shapes,
first inspect the plan:

```sh
./agent-kv-workload.py
```

Then run it explicitly:

```sh
./agent-kv-workload.py --run
```

`--run` first checks `./agent-cache-check.sh --profile-only --strict` and refuses
to send requests if the live server does not match `start-server.sh`. For an
intentional old-profile baseline, bypass the guard explicitly:

```sh
./agent-kv-workload.py --run --skip-profile-check
```

The workload sends OpenAI chat, OpenAI Responses, and Anthropic Messages
requests with a large stable system/tool prefix and volatile labels in the tail
(`A, A, B, A`). It uses one output token per request so the trace mostly measures
prefill and cache reuse instead of decode throughput.
By default it uses `tool_choice=auto` so tool schemas are rendered into the
prompt, matching normal agent clients. Use `--tool-choice none` only as a
no-tool-prefix control.
For decode or MTP measurements, request a longer output:

```sh
./agent-kv-workload.py --run --max-tokens 32
```

Inspect the result:

```sh
./agent-cache-check.sh
```

Before running any heavy workload, you can check only the live startup flags:

```sh
./agent-cache-check.sh --profile-only --strict
```

After one representative workload has completed, use strict mode as a quick
pass/fail check:

```sh
./agent-cache-check.sh --strict
```

Strict mode compares the live `ds4-server` process against the exact command
printed by `DS4_DRY_RUN=1 ./start-server.sh`, then fails if any expected startup
flag is missing or different. It also fails if no completed requests are present
in the trace, or if the KV directory does not yet contain one of the first two
aligned `continued` checkpoints implied by the target startup command. For the
default agent profile, those checkpoints are `4096` and `8192`. It intentionally
does not require `disk-text` by default because that usually needs a
restart-like replay or a session switch back to an already cached prompt.

Or directly:

```sh
./trace-cache-summary.py /tmp/ds4-trace.jsonl --last 20
```

The summary infers `chat`, `responses`, and `anthropic` from the raw request JSON
blocks in the trace and prints a per-protocol latency/cache-source breakdown.

With MTP measurement logs:

```sh
./trace-cache-summary.py /tmp/ds4-trace.jsonl --server-log /tmp/ds4-server.log --last 20
```

For a read-only baseline of the currently running server, fill missing config
fields from the live `ds4-server` command line:

```sh
./trace-cache-summary.py /tmp/ds4-trace.jsonl --kv-dir ~/.ds4/server-kv --live-config --json > /tmp/ds4-live-old-baseline.json
./agent-kv-compare.py live-old=/tmp/ds4-live-old-baseline.json
```

The safer wrapper is:

```sh
./agent-live-baseline.py
```

It writes `/tmp/ds4-live-baseline/live-old-before.json` by default and does not
send any model requests. To intentionally probe the live server without changing
its startup parameters, run:

```sh
./agent-live-baseline.py --run-workload --compare
```

That command captures a before snapshot, runs
`./agent-kv-workload.py --run --skip-profile-check`, captures an after snapshot,
and compares the two. Use it only when the current agent clients are idle enough
for a short synthetic workload.

If the trace is empty, treat this only as a KV-frontier baseline. It can show
which checkpoint frontiers the old profile wrote, but it cannot prove latency,
`cache_source`, or MTP behavior.
The current old-profile multi-protocol baseline is saved at
`/tmp/ds4-live-baseline/live-old-all-after.json`. It used short OpenAI chat,
OpenAI Responses, and Anthropic Messages requests with labels `A,A,B,A`,
`max_tokens=1`, and no profile restart. Observed old-profile behavior:

```text
continued_interval=10000 cold_max=65536
completed=12 avg=20.1s p90=61.2s none=33% disk-text=8
cache_source=none avg_elapsed=59.3s
cache_source=disk-text avg_elapsed=0.5s
chat:       count=4 avg=30.4s none=50% disk=2
responses:  count=4 avg=0.6s  none=0%  disk=4
anthropic:  count=4 avg=29.3s none=50% disk=2
continued_frontiers=20480,40960,61440,81920
best_interval_hint=4096 covered 10 of 12 first-mismatch points
2048 cost: avg_ckpt=6.0 avg_write=43.0k token-positions/request
4096 cost: avg_ckpt=3.0 avg_write=24.6k token-positions/request
```

This is a useful baseline but not the sweet spot: it has no MTP metrics, only one
short synthetic workload, and no measured new-profile candidate yet.
The old trace now supports `4096` as the first real candidate over `2048`: both
cover the same 10/12 mismatch points in the baseline, but `4096` cuts the
estimated checkpoint count in half and reduces the write-cost proxy by about
43%.

The measured restart-replay sweep on 2026-06-28 compared `2048`, `4096`, and
`8192` with `prefill_chunk=4096`, `boundary_align=2048`, `cold_max=98304`, and
`cache_min=1024`:

```text
interval-2048: avg=1.1s p90=3.0s none=0% disk=12 frontiers=4096,8192,12288 avg_ckpt=6.0 avg_write=43.0k
interval-4096: avg=1.1s p90=2.9s none=0% disk=12 frontiers=4096,8192,12288 avg_ckpt=3.0 avg_write=24.6k
interval-8192: avg=7.4s p90=28.0s none=0% disk=12 frontiers=8192            avg_ckpt=1.0 avg_write=8.2k
```

`2048` and `4096` produced the same actual continued frontiers because the
prefill chunk is 4096. The small p90 differences between them are noise-level
for this workload, so the default stays at `4096` to avoid unnecessary
checkpoint write amplification. `8192` is too coarse: replayed `B` branches for
chat, Responses, and Anthropic clients fell back to the 8192-token frontier and
needed roughly 27-29 seconds of additional prefill.
During a sweep, pass the same file as a display-only baseline so strict gates and
recommendations still apply only to the measured candidates:

```sh
./agent-kv-sweep-run.py --candidate 4096 --restart-replay --capture-live-baseline --replace-live
./agent-kv-sweep-run.py --candidate 4096 --restart-replay --compare-baseline live-old=/tmp/ds4-live-baseline/live-old-all-after.json --replace-live
./agent-kv-sweep-plan.py --candidate 4096 --restart-replay --compare-baseline live-old=/tmp/ds4-live-baseline/live-old-all-after.json
```

## Candidate Sweep

Use the default `4096` candidate first. It is the current start-script profile
and the old trace shows the same mismatch coverage as `2048` with materially
lower checkpoint write cost. Run one full safe measurement loop and save a JSON
summary:

```sh
./agent-kv-sweep-plan.py

# Boundary validation after the first 4096 run:
./agent-kv-sweep-plan.py --candidate 4096 --candidate 2048 --candidate 8192
```

To run the same loop automatically, use the safe runner:

```sh
./agent-kv-4096-sweetspot.sh
# Equivalent explicit form:
./agent-kv-sweep-run.py --restart-replay --compare-baseline live-old=/tmp/ds4-live-baseline/live-old-all-after.json
```

The runner refuses to start if any `ds4-server` is already running. This is the
default guard against interrupting active agent clients. When clients are idle
and you intentionally want the runner to stop the old server first, pass
`--replace-live` explicitly:

```sh
./agent-kv-4096-sweetspot.sh --replace-live
# Equivalent explicit form:
./agent-kv-sweep-run.py --restart-replay --compare-baseline live-old=/tmp/ds4-live-baseline/live-old-all-after.json --replace-live
```

`agent-kv-4096-sweetspot.sh` defaults to dry-run unless `--replace-live` is
present. It also honors `DS4_AGENT_BASELINE=/path/to/baseline.json` when using a
different saved old-profile baseline. When `--replace-live` is present, it first
runs `./agent-server-idle-check.sh` and refuses to continue if port 8077 has
established TCP connections. Set `DS4_SKIP_IDLE_CHECK=1` only when you
intentionally want to override that guard. The runner's `--keep-server` mode is
intentionally not used here; after a successful replace-live sweep, the wrapper
starts the production 4096 server in a detached tmux session named
`ds4-live-4096` so it remains online after the comparison.

Use `--dry-run` first to inspect the exact per-candidate environment and output
paths. The runner defaults to isolated KV directories and per-candidate trace
files under `/tmp/ds4-agent-kv-runs/`, so experimental sweeps do not overwrite
the production trace or pollute the long-lived production KV cache.
The runner prints `candidate_count total=... pending=...` before doing any
server work. It refuses to run more than 32 pending candidates by default; raise
`--max-candidates` for an intentional large sweep, or use `--max-candidates 0`
to disable the guard.
At the end, the runner compares results with strict sufficiency gates:
`completed >= 1`, a continued frontier matching each candidate's aligned
interval, and, for the default synthetic workload, coverage of `chat`,
`responses`, and `anthropic` protocol shapes. When `--mtp-metrics` is enabled,
strict mode also requires at least one MTP attempt. If you are intentionally
running a tiny/custom workload that cannot satisfy those checks, pass
`--no-strict-results` and inspect the JSON manually. Use
`--no-default-protocol-gates` only when the workload deliberately narrows to one
protocol.
To prove that disk KV survives a process restart, add `--restart-replay`. For
each candidate the runner warms the cache, stops only that candidate process,
starts the same profile again with the same KV directory, reruns the workload,
and then summarizes the combined trace. In strict mode this also requires at
least one `cache_source=disk-text` hit:

```sh
./agent-kv-sweep-run.py --candidate 4096 --restart-replay --replace-live
```

If `4096` passes but you still need to check the edges, run:

```sh
./agent-kv-sweep-run.py --candidate 4096 --candidate 2048 --candidate 8192 --restart-replay --compare-baseline live-old=/tmp/ds4-live-baseline/live-old-all-after.json --replace-live
```

By default the replay phase reuses `--workload`. To validate a different replay
shape after warmup, pass `--replay-workload`. For example, warm with the
synthetic agent workload and replay selected raw requests from a captured trace:

```sh
./agent-kv-sweep-run.py \
  --candidate 4096 \
  --restart-replay \
  --replay-workload './agent-kv-replay.py /tmp/ds4-trace.jsonl --run --protocol chat --max-requests 8 --max-tokens 1' \
  --replace-live
```

If a long sweep is interrupted after some candidates completed, resume with
`--skip-existing`; the runner skips non-empty JSON result files and still runs
the final comparison across the full result list:

```sh
./agent-kv-sweep-run.py --candidate 4096 --candidate 2048 --candidate 8192 --mtp-metrics --replace-live --skip-existing
```

To narrow the synthetic workload, pass a shell-style command string:

```sh
./agent-kv-sweep-run.py --candidate 4096 --workload './agent-kv-workload.py --run --protocol chat'
```

When you provide a custom workload, the runner uses it exactly. Add
`--max-tokens 32` yourself if that custom workload is meant to measure MTP.

Both the manual plan and the runner can expand the search into a small parameter
matrix. Keep this narrow; every extra dimension restarts the full model:

```sh
./agent-kv-sweep-run.py \
  --candidate 2048 --candidate 4096 \
  --prefill-chunk 2048 --prefill-chunk 4096 \
  --boundary-align 1024 --boundary-align 2048 \
  --dry-run
```

This is useful only after the interval-only run shows that `2048` and `4096` are
close. The matrix answers whether smaller prefill chunks or tighter boundary
alignment improve reuse before the common 5k-9k agent-prompt divergence. The
default remains `prefill_chunk=4096` and `boundary_align=2048` because that keeps
cache files and scheduler overhead bounded. Candidate filenames include
`chunk-*` and `align-*` only when those dimensions have multiple values, so the
old interval-only result names stay stable.

After interval/chunk/align have narrowed to one or two close candidates, test KV
retention pressure with `--cold-max` and `--cache-min`:

```sh
./agent-kv-sweep-run.py \
  --candidate 4096 \
  --cold-max 65536 --cold-max 98304 \
  --cache-min 512 --cache-min 1024 \
  --mtp-metrics --include-mtp-off --dry-run
```

`cold_max` changes how much cold prompt history is retained before eviction; too
low can lose useful agent-session prefixes, while too high can waste disk budget
on stale sessions. `cache_min` avoids writing tiny prefixes; lower values can
help short tool-schema prompts but may add noise. Keep these as a second-stage
sweep unless trace evidence shows eviction or too-short-prefix misses.

To replay real agent request shapes captured in a previous trace, use
`agent-kv-replay.py` as the workload:

```sh
./agent-kv-replay.py /tmp/ds4-trace.jsonl
./agent-kv-sweep-run.py --candidate 4096 --workload './agent-kv-replay.py /tmp/ds4-trace.jsonl --run --max-tokens 1'
```

For long traces, narrow the replay before putting it into a sweep:

```sh
./agent-kv-replay.py /tmp/ds4-trace.jsonl --protocol responses --max-requests 8
./agent-kv-replay.py /tmp/ds4-trace.jsonl --protocol chat --sample-step 3 --max-body-bytes 500000
```

For MTP decode measurement on replayed requests, force deterministic decoding
and a longer output:

```sh
./agent-kv-sweep-run.py --candidate 4096 --mtp-metrics --workload './agent-kv-replay.py /tmp/ds4-trace.jsonl --run --max-tokens 32 --temperature 0'
```

Add `--mtp-metrics` when comparing MTP settings or confirming whether the
default MTP path is actually helping:

```sh
./agent-kv-sweep-plan.py --candidate 4096 --candidate 8192 --mtp-metrics
```

Add `--include-mtp-off` when you need a direct no-MTP baseline. Candidate names
then include `-mtp-on` or `-mtp-off`, and MTP-off candidates run with
`DS4_MTP_PATH=`:

```sh
./agent-kv-sweep-run.py --candidate 4096 --mtp-metrics --include-mtp-off --replace-live
```

With `--mtp-metrics`, the plan keeps the normal KV settings but changes the
default synthetic workload to `./agent-kv-workload.py --run --max-tokens 32`,
because a one-token completion exits before useful speculative decode attempts.
Override `--mtp-workload-tokens` or `--workload` if you want a different decode
length.

The plan generator prints commands only; it does not stop or start the server.
Run one candidate block at a time after active agent clients are idle. Each block
restarts with a different `DS4_CONTINUED_INTERVAL`, runs the synthetic workload,
and writes a JSON summary under `/tmp/ds4-agent-kv-runs/`.
The same candidate environment is applied to start, profile-check, workload, and
summary commands so workload preflight validates the intended candidate instead
of the default profile. By default each candidate uses an isolated KV directory
under the results directory to avoid old frontiers contaminating the comparison;
pass `--shared-kv-dir` to compare against the long-lived production cache.
The JSON summary includes the key `DS4_*` tuning environment, so compare output
still shows interval/chunk/align even if result files are renamed.
When `--mtp-metrics` is used, each candidate also writes
`interval-*.server.log`; the saved JSON includes MTP acceptance and timing
metrics parsed from that log.

Compare saved runs:

```sh
./agent-kv-compare.py /tmp/ds4-agent-kv-runs/*.json
```

`agent-kv-compare.py` prints `recommended_start_env` and
`recommended_start_command` for the best-scoring result. Use that command to
start the selected production profile after reviewing the gates and the
`recommendation_basis` line. If `--mtp-metrics` was enabled but the basis says
`mtp_metrics_enabled_but_no_attempts`, the workload did not actually measure
MTP; rerun with a longer decode before making an MTP decision.
The compare table includes both overall `none` and worst-protocol `pnone/pp90`,
plus `ckpt/write` for the candidate's own continued interval. Prefer a candidate
that improves the slowest protocol without paying unnecessary checkpoint write
amplification.

For a manual strict check equivalent to the runner's default:

```sh
./agent-kv-compare.py /tmp/ds4-agent-kv-runs/*.json --strict --min-completed 1 --require-auto-frontier --require-mtp-attempts
```

Prefer the candidate with low `none` rate, visible `disk` reuse after replay,
lower p90 latency, useful MTP acceptance if MTP is enabled, and continued
frontiers before the common first-mismatch range. If `2048` improves miss
coverage but creates too much cache write volume or disk churn, keep `4096`. If
`8192` misses divergence around 5k, it is too late for normal agent prompts.

## Interpreting Results

Good signs:

- `agent-cache-check.sh` reports `desired profile applied? yes`.
- KV frontiers include `4096` or `8192` token `continued` checkpoints.
- `cache_source=disk-text` appears after a restart or after switching back to a
  previous agent session.
- `cache_source=none` average latency drops compared with the old 10000 interval
  run.

Still bad:

- `cache_source=none` remains frequent and `first_mismatch_token` is below 4096.
  KV tuning can only save a small prefix; the client prompt needs more stable
  early ordering or volatile blocks moved later.
- `cache_source=none` remains frequent, `first_mismatch_token` is above 4096, and
  there are no matching disk frontiers before the mismatch. Check the KV frontier
  list and budget/eviction behavior before changing model settings.
- KV files are present but `hits` stay zero after restart-like replays. That means
  the stored prefix text still does not match the client replay.

## Useful Overrides

Print the exact command without starting:

```sh
DS4_DRY_RUN=1 ./start-server.sh
```

Use the smaller profile:

```sh
DS4_PROFILE=conservative ./start-server.sh
```

Disable trace for normal use:

```sh
DS4_TRACE= ./start-server.sh
```

Try a more aggressive checkpoint interval only if traces show divergence before
4096 and disk space/write volume remain acceptable:

```sh
DS4_CONTINUED_INTERVAL=2048 DS4_PREFILL_CHUNK=4096 ./start-server.sh
```
