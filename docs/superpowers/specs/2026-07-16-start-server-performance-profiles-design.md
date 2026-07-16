# Start Server Performance Profiles Design

## Context

`start-server.sh` is intentionally tuned for this 128 GB M3 Max and points at
the locally downloaded Huihui DeepSeek V4 Flash abliterated Q2 GGUF. That model
path is part of the machine configuration and must remain the default.

Two launcher defaults currently leave performance on the table:

- the explicit 4096-token prefill chunk bypasses the 5120-token M3 Max setting
  that won the matched long-prefill comparison; and
- the agent profile always maps the 3.8 GB MTP support GGUF even though the
  server uses speculative decoding only for temperature-zero generation.

`DEFAULT_CTX=51200` remains the selected default. A same-process allocation
check held prefill at 2048 tokens, decode at 128 tokens, and the prefill chunk at
5120 while alternating 51200 and 200000 contexts. The paired throughput deltas
were within run noise, while context buffers grew from 1355.75 MiB to 3975.90
MiB. The 51200 choice therefore preserves memory headroom without being
presented as a direct short-prompt throughput optimization.

## Selected Design

Keep three explicit profiles:

| Profile | Context | Prefill chunk | MTP | Intended workload |
| --- | ---: | ---: | --- | --- |
| `agent` | 51200 | 5120 | off | normal sampled coding-agent traffic |
| `greedy` | 51200 | 5120 | draft 2 | deterministic temperature-zero generation |
| `conservative` | 100000 | automatic | off | occasional API use with smaller disk cache |

The `agent` and `greedy` profiles share all cache and host settings. Only the
default MTP path differs. Explicit environment overrides retain precedence:

- `DS4_MODEL` can select another local GGUF;
- `DS4_CTX` and the saved context file retain their existing precedence;
- `DS4_PREFILL_CHUNK` can restore 4096 or select another measured chunk; and
- `DS4_MTP_PATH` can explicitly enable MTP for `agent` or disable it for
  `greedy` by setting an empty value.

No automatic model download, process restart, memory reclamation, or live
server mutation is part of this change.

## Verification

The server unit tests will execute the launcher through `DS4_DRY_RUN=1` and
assert the resolved command for both performance profiles. Shell syntax,
profile overrides, the server unit group, and the full project test target will
be run without starting a second model process.
