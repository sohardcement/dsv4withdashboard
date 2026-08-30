# Learnings

## [LRN-20260716-001] correction

**Logged**: 2026-07-16T00:00:00+08:00
**Priority**: high
**Status**: resolved
**Area**: tests

### Summary
Do not attribute throughput changes to maximum context size when benchmark rows also change the measured prompt frontier or incremental prefill length.

### Details
The `ds4-bench` CSV rows at 2K, 8K, and 32K were initially used to estimate the effect of `--ctx`. That comparison was confounded: both `ctx_tokens` (the live frontier) and `prefill_tokens` changed. It measures performance as occupied context grows, not the isolated effect of changing the session's allocated maximum context for the same workload.

### Suggested Action
For a maximum-context comparison, hold model, backend, prompt tokens, generated tokens, prefill chunk, thermal state, and benchmark ordering constant; create a fresh session for each `--ctx`/`--ctx-alloc` value and repeat enough times to report variance. Label frontier sweeps as occupied-context benchmarks only.

### Metadata
- Source: user_feedback
- Related Files: `ds4_bench.c`, `speed-bench/m3_max_optimized.csv`
- Tags: benchmarking, control-variables, context, performance

### Resolution
- **Resolved**: 2026-07-16T00:00:00+08:00
- **Notes**: Retracted the causal conclusion and separated allocated context capacity from occupied context length.

---

## [LRN-20260716-002] correction

**Logged**: 2026-07-16T12:19:39+08:00
**Priority**: high
**Status**: resolved
**Area**: backend

### Summary
HanaAgent's repeated short-prompt, long-output DSV4 calls were confirmed as background memory work whose 60-second client timeouts did not cancel queued or running DS4 requests.

### Details
Runtime monitoring showed bursts of non-streaming HanaAgent calls with roughly 700–1,000 prompt tokens and up to about 4,000 generated tokens. These were initially interpreted as ordinary long-form jobs. OpenHanako's usage ledger and logs confirmed that the 16-call burst contained 7 `memory/rolling_summary` calls, 1 `memory/compile_longterm` call, and 8 `memory/extract_facts` calls. Every client call ended as `LLM_TIMEOUT` after 60 seconds, while DS4 kept the non-streaming requests queued or generating and ultimately completed all 16, producing about 26,220 output tokens that the client no longer consumed. The final Hana timeout occurred around 11:41, but DS4 did not clear the abandoned backlog until about 12:04. Once the queue was empty, equivalent memory jobs completed successfully in 36.5 seconds and 25.1 seconds. Local Hana model metadata also declared `contextWindow: 1000000` and `maxTokens: 384000`, while DS4 was actually running with `--ctx 51200`.

### Suggested Action
Prioritize cooperative cancellation in `ds4-server`: reject queued jobs whose HTTP peer has disconnected and install a session cancellation callback for active prefill/decode. Keep foreground requests distinct from background memory work, align Hana's model `contextWindow` with the real DS4 limit, and avoid a global generation cap that could damage memory output quality. Hana-side timeout/concurrency tuning is secondary protection, not a substitute for server-side cancellation.

### Metadata
- Source: user_feedback
- Related Files: `ds4_server.c`, `start-server.sh`
- Tags: HanaAgent, memory, timeout, cancellation, queueing, performance

### Resolution
- **Resolved**: 2026-07-16T12:55:00+08:00
- **Notes**: Confirmed with OpenHanako source, local usage ledger, Hana logs, and DS4 call history; corrected the workload attribution and identified abandoned non-stream requests as the dominant cause.

---
