# Start Server Performance Profiles Design

## Context

`start-server.sh` is intentionally tuned for this 128 GB M3 Max and points at
the locally downloaded Huihui DeepSeek V4 Flash abliterated Q2 GGUF. That model
path is part of the machine configuration and must remain the default.

The launcher profile decisions are based on two measured results:

- the 5120-token M3 Max prefill chunk won the matched long-prefill comparison;
  and
- both the preview MTP path and the later exact 0731 DSpark path failed the
  user-visible speed gate, so speculative support weights must stay opt-in.

Normal reasoning now uses a 110592-token allocation, which covers the measured
100k frontier without paying the 393216-token Think Max footprint. Think Max is
kept as an explicit context override rather than a launcher default.

## Selected Design

Keep three explicit profiles:

| Profile | Context | Prefill chunk | MTP | Intended workload |
| --- | ---: | ---: | --- | --- |
| `agent` | 110592 | 5120 | off | normal sampled coding-agent traffic |
| `greedy` | 110592 | 5120 | off | compatibility alias for temperature-zero clients |
| `conservative` | 110592 | 5120 | off | occasional API use with smaller disk cache |

The `agent` and `greedy` profiles share all cache and host settings. No normal
profile maps speculative support weights. Explicit environment overrides retain
precedence:

- `DS4_MODEL` can select another local GGUF;
- `DS4_CTX` and the saved context file retain their existing precedence;
- `DS4_PREFILL_CHUNK` can restore 4096 or select another measured chunk; and
- `DS4_MTP_PATH` or explicit `--mtp ... --dspark` arguments remain available
  for diagnostic speculation runs.

No automatic model download, process restart, memory reclamation, or live
server mutation is part of this change.

## Verification

The server unit tests will execute the launcher through `DS4_DRY_RUN=1` and
assert the resolved command for both performance profiles. Shell syntax,
profile overrides, the server unit group, and the full project test target will
be run without starting a second model process.
