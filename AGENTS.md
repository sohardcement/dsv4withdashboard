# Repository Guidelines

DS4 (DwarfStar4) is a **DeepSeek V4 Flash specific** inference engine written in C. It is not a generic GGUF runner — its whole-model Metal graph path is the production target, with CUDA, ROCm, SSD streaming, distributed inference, and a CPU reference backend.

## Project Structure & Module Organization

- `ds4.c` / `ds4.h` — model loading, tokenizer, CPU reference, Metal graph scheduling, sessions, disk-cache serialization.
- `ds4_cli.c` — CLI entrypoint, linenoise REPL.
- `ds4_server.c` — OpenAI/Anthropic-compatible HTTP API, worker queue, streaming, tool-call mapping, KV cache policy.
- `ds4_agent.c` — agent runtime (edit/tools), built into `ds4-agent`.
- `ds4_metal.m` — Objective-C Metal runtime and kernel wrappers.
- `ds4_cuda.cu`, `ds4_rocm.cu` / `ds4_rocm.h` — CUDA and ROCm GPU backends.
- `ds4_distributed.c`, `ds4_ssd.c`, `ds4_kvstore.c` — distributed inference, SSD streaming of routed experts, persistent KV store.
- `metal/`, `rocm/` — compute kernels (`.metal`, `.cuh`).
- `tests/` — C test runner (`ds4_test.c`), agent tests (`ds4_agent_test.c`), kernel smoke tests, `test-vectors/` fixtures.
- `gguf-tools/` — quantization, imatrix, and quality-scoring tooling (offline model-building).
- `speed-bench/` — throughput benchmarking prompts and plotting.
- `misc/` — ignored experiments and notes (git-ignored).

## Build, Test, and Development Commands

Builds are driven by `make`; targets differ per platform (Metal on macOS, CUDA/ROCm on Linux).

- `make` — on macOS: build Metal `ds4`, `ds4-server`, `ds4-bench`, `ds4-eval`, `ds4-agent`. On Linux: prints backend-specific help.
- `make cpu` — CPU-only reference build (debug/diagnostics; do not run on macOS — kernel VM bug).
- `make cuda-spark | make cuda-generic | make cuda CUDA_ARCH=sm_120` — CUDA builds (DGX Spark/GB10, generic, or explicit arch).
- `make strix-halo` (alias `make rocm`) — ROCm build for gfx1151.
- `make test` — build and run `ds4_test` and `ds4_agent_test` (defaults to `--all`). Also runs `./ds4-eval --self-test-extractors` first.
- `make cuda-regression` — build and run the CUDA long-context smoke test.
- `make clean` — remove object files and binaries.

Local run: `./start-server.sh` boots `ds4-server` with profiles selected via `DS4_PROFILE` (`agent`/`greedy`/`conservative`, default `agent`). Model defaults to a local abliterated Q2 path; override with `DS4_MODEL`. Other knobs: `DS4_HOST`, `DS4_PORT`, `DS4_CTX`, `DS4_KV_DIR`, `DS4_KV_SPACE`, `DS4_TRACE`.

## Design Philosophy

- Keep the production path whole-model Metal graph inference; protect SSD streaming, CUDA, and distributed paths from collateral breakage.
- **Write elegant code.** Don't settle for the first thing that comes to mind. No fragile case-patching, no dead code, no implementation more complicated than it should be.
- Comment inference code where model mechanics, cache lifetime, memory policy, or API orchestration are not obvious from the local code. Prefer comments beside the implementation over separate design documents.
- Do not add permanent semantic variants behind flags. Diagnostic switches are fine when they validate the one release path.

## Coding Style & Naming Conventions

- C99 (`-std=c99`), compiled with `-O3 -ffast-math -Wall -Wextra`. Linux adds `-D_GNU_SOURCE`. No C++.
- Tabs for indentation in C; 4-space indent for Python tooling.
- Public API is `snake_case` with a `ds4_` prefix. Keep public APIs narrow; CLI/server code must not know tensor internals.
- Objective-C is `-fobjc-arc`, confined to `ds4_metal.m`.
- Keep the implementation small and minimal. No fragile case-patching, no dead code, no permanent semantic variants behind flags.

## Testing Guidelines

`tests/ds4_test.c` is the primary runner. Focused flags:

- `--server` — API parsing, chat rendering, streaming, tool calls (quick check for API/prompt changes).
- `--logprob-vectors` — compares token bytes and top-logprob slices against official DeepSeek V4 Flash vectors.
- `--long-context` — long-context fact recall regression.
- `--tool-call-quality` — DSML tool-call emission (fast and exact paths).
- `--metal-kernels` — isolated Metal kernel numeric checks.

Override fixtures with `DS4_TEST_MODEL`, `DS4_TEST_VECTOR_FILE`, `DS4_TEST_LONG_PROMPT`. For strict official-vector comparison, use `DS4_METAL_PREFILL_CHUNK=2048` (the test runner pins this automatically for `--logprob-vectors`). New tests follow `tests/<name>_test.c` and are added to the Makefile `test` target dependency line.

The test runner includes `ds4_server.c` via `#define DS4_SERVER_TEST`, so server tests exercise the real server-side code paths.

For quantization changes, score with `make -C gguf-tools quality-score` and compare `avg_nll`.

After every major change that could affect an inference backend, run the checklist in `QA_BEFORE_RELEASES.md` for affected paths. When CUDA is reachable, ask the user before testing on that machine.

## Debugging Tools

```sh
./ds4 --dump-tokens -p "..."          # tokenize only, no inference
./ds4 --dump-logprobs /tmp/out.json   # greedy continuation with top-k logprobs
./ds4 --dump-logits /tmp/logits.json --nothink -p "..."
./ds4-server --trace /tmp/ds4-trace.txt ...
```

## Commit & Pull Request Guidelines

Commits use concise imperative subjects, often scope-prefixed (e.g. `server:`, `fix(agent):`, `streaming:`). PRs touching any inference backend must include the commands run, machine/backend, model quant, and notable failures. Run `make test` (and the relevant backend regression) before opening a PR. For speed-sensitive changes attach a `ds4-bench` before/after CSV. Never regress speed for a non-correctness reason.

See `QA_BEFORE_RELEASES.md` for the full release gate checklist (Metal, CUDA, ROCm, distributed, disk KV, server APIs, agent, perf).

## Architecture & Safety Notes

- Preserve correctness before speed: no faster path with unexplained attention, KV cache, or logits drift.
- Model loading stays mmap-backed for the Metal default; SSD streaming reads routed experts into explicit buffers and overlaps loading with shared-expert inference.
- Do not run multiple huge model processes concurrently — the instance lock is intentional.
- **Never run the CPU inference path on macOS** (kernel VM bug). The CPU path is reference/debug only.
- When launching `ds4-server` or `ds4-agent` from a non-project directory, pass `--chdir /path/to/ds4` so relative `metal/*.metal` paths resolve.
- Distributed inference uses `--role coordinator` / `--role worker`, `--layers start:end` (inclusive, `end=output` for final layer+head), and TCP on a user-chosen port. Workers connect to the coordinator's `--listen addr port`. The coordinator keeps token history and can rebuild worker KV state by replaying the prefix.
- The disk KV cache (`--kv-disk-dir`) is a resumable prefix store for the server. Cache key is SHA1 of rendered text bytes; files are named `<sha1>.kv`. Disposable — remove and restart if cache looks suspicious.
- `--power N` (1–100) reduces GPU duty cycle for thermal/noise control by inserting sleeps between work units. Works across all binaries.
- Use `--ssd-streaming` for running models larger than RAM; the automatic cache budget is usually best. Explicit `--ssd-streaming-cache-experts NGB` overrides it. Start with `--nothink` for initial tuning.
- After any major change, re-test the Metal path, SSD streaming, and (if reachable) CUDA/distributed — see `QA_BEFORE_RELEASES.md` for the full release checklist.
