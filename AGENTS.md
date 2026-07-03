# Repository Guidelines

DS4 (DwarfStar4) is a **DeepSeek V4 Flash specific** inference engine written in C. It is not a generic GGUF runner — its whole-model Metal graph path is the production target, with CUDA, ROCm, SSD streaming, distributed inference, and a CPU reference backend.

## Project Structure & Module Organization

- `ds4.c` / `ds4.h` — model loading, tokenizer, CPU reference, Metal graph scheduling, sessions, disk-cache serialization.
- `ds4_cli.c` — CLI entrypoint, linenoise REPL, interactive transcript handling.
- `ds4_server.c` — OpenAI/Anthropic-compatible HTTP API, worker queue, streaming, tool-call mapping, KV cache policy.
- `ds4_agent.c` — agent runtime (edit/tools), built into `ds4-agent`.
- `ds4_metal.m` — Objective-C Metal runtime and kernel wrappers (Objective-C only where Metal requires it).
- `ds4_cuda.cu`, `ds4_rocm.cu` / `ds4_rocm.h` — CUDA and ROCm GPU backends.
- `ds4_distributed.c`, `ds4_ssd.c`, `ds4_kvstore.c` — distributed inference, SSD streaming of routed experts, persistent KV store.
- `metal/`, `rocm/` — compute kernels (`.metal`, `.cuh`).
- `tests/` — C test runner (`ds4_test.c`), agent tests (`ds4_agent_test.c`), kernel smoke tests, and `test-vectors/` fixtures.
- `gguf-tools/` — quantization, imatrix, and quality-scoring tooling.
- `speed-bench/` — throughput benchmarking prompts and plotting.
- `misc/` — ignored experiments and notes (git-ignored).

## Build, Test, and Development Commands

Builds are driven by `make`; targets differ per platform (Metal on macOS, CUDA/ROCm on Linux).

- `make` — on macOS: build Metal `ds4`, `ds4-server`, `ds4-bench`, `ds4-eval`, `ds4-agent`. On Linux: prints backend-specific help.
- `make cpu` — CPU-only reference build of all binaries.
- `make cuda-spark | make cuda-generic | make cuda CUDA_ARCH=sm_120` — CUDA builds (DGX Spark/GB10, generic, or explicit arch).
- `make strix-halo` (alias `make rocm`) — ROCm build for gfx1151.
- `make test` — build and run `ds4_test` (defaults to `--all`).
- `make cuda-regression` — build and run the CUDA long-context smoke test.
- `make clean` — remove object files and binaries.

Local run: `./start-server.sh` boots `ds4-server` with the default `ds4flash.gguf` symlink.

## Coding Style & Naming Conventions

- C99 (`-std=c99`), compiled with `-O3 -ffast-math -Wall -Wextra`. Linux adds `-D_GNU_SOURCE`. No C++.
- Tabs for indentation in C; 4-space indent for Python tooling.
- Public API is `snake_case` with a `ds4_` prefix (e.g. `ds4_engine_open`, `ds4_tokens_push`). Keep public APIs narrow; CLI/server code must not know tensor internals.
- Objective-C is `-fobjc-arc`, confined to Metal wrappers.
- Keep the implementation small and minimal. No fragile case-patching, no dead code, no permanent semantic variants behind flags.

## Testing Guidelines

`tests/ds4_test.c` is the primary runner. Focused flags:

- `--server` — API parsing, chat rendering, streaming, tool calls (quick check for API/prompt changes).
- `--logprob-vectors` — compares token bytes and top-logprob slices against official DeepSeek V4 Flash vectors.
- `--long-context` — long-context fact recall regression.
- `--tool-call-quality` — DSML tool-call emission (fast and exact paths).
- `--metal-kernels` — isolated Metal kernel numeric checks.

Override fixtures with `DS4_TEST_MODEL`, `DS4_TEST_VECTOR_FILE`, `DS4_TEST_LONG_PROMPT`. New tests follow `tests/<name>_test.c` and are added to the Makefile `test` target. For quantization changes, score with `make -C gguf-tools quality-score` and compare `avg_nll` before/after.

## Commit & Pull Request Guidelines

Commits use concise imperative subjects, often scope-prefixed (e.g. `server:`, `fix(agent):`, `streaming:`). Examples from history: `Fix CPU build after streaming refactor`, `server: recover tool calls started inside an unclosed <think>`.

PRs touching any inference backend must include the commands run, machine/backend, model quant, and notable failures. Run `make test` (and the relevant backend regression) before opening a PR. For speed-sensitive changes attach a `ds4-bench` before/after CSV. Never regress speed for a non-correctness reason.

## Architecture & Safety Notes

- Preserve correctness before speed: no faster path with unexplained attention, KV cache, or logits drift.
- Model loading stays mmap-backed for the Metal default; SSD streaming reads routed experts into explicit buffers and overlaps loading with shared-expert inference.
- Do not run multiple huge model processes concurrently — the instance lock is intentional.
- Avoid large CPU inference runs on macOS (kernel VM bug). The CPU path is reference/debug only.
- After any major change, re-test the Metal path, SSD streaming, and (if reachable) CUDA/distributed — see `AGENT.md` and `CONTRIBUTING.md`.
