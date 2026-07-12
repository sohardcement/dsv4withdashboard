# M3 Max Metal Prefill and Decode Performance Design

## Objective

Improve both prefill and decode throughput for the default, fully resident
DeepSeek V4 Flash q2 Metal path on this machine: a 40-GPU-core Apple M3 Max
with 128 GB of unified memory. The current `ds4flash.gguf` is approximately
81 GB and fits in memory, so SSD streaming is outside this optimization cycle.

The optimization is successful only if, on the same model and benchmark
configuration, median prefill throughput and median decode throughput each
improve by at least 5% while correctness tests remain unchanged.

## Scope

This cycle covers:

- the production whole-model Metal graph path;
- the current Flash q2 model referenced by `ds4flash.gguf`;
- short, medium, and long context frontiers at 2K, 8K, and 32K tokens;
- M3 Max-specific kernel or dispatch choices selected at runtime; and
- profiling that is disabled by default and has no production overhead.

This cycle does not change model files, quantization semantics, tokenizer or
prompt rendering, the CPU/CUDA/ROCm backends, distributed inference, or SSD
streaming. Existing paths for other Apple GPUs remain available and unchanged
unless an optimization is independently proven beneficial on them.

## Chosen Approach

Use measurement-driven kernel and scheduling optimization. First establish a
repeatable whole-model baseline and identify the dominant prefill and decode
GPU stages. Then change one stage at a time and retain only changes that improve
whole-model throughput without correctness drift.

Parameter-only tuning is useful during diagnosis but is not the end design: a
permanent collection of environment-variable presets would be fragile and is
not an acceptable production result. A broad kernel rewrite is also deferred
because it would expand numerical and portability risk before the actual
bottlenecks are known.

## Measurement Design

Use `ds4-bench` with the same binary configuration, model file, prompt token
sequence, context frontiers, generation length, power state, and background
load for every comparison. Record:

- instantaneous `prefill_tps` for each newly processed interval;
- `gen_tps` from the fixed greedy non-EOS decode probe;
- KV-cache bytes and benchmark configuration;
- GPU time by existing FlashAttention, attention-output, and MoE stage timing
  hooks; and
- command-buffer or synchronization counts when dispatch overhead is under
  investigation.

Run candidates and controls in interleaved A/B/A/B order after model warmup.
Collect at least three valid measurements for each variant and compare medians.
Discard runs affected by thermal throttling, a changed power source, or material
background load. Preserve raw CSV output for the final report.

## Runtime Selection

Keep device selection centralized in `ds4_metal.m`. The selector may use Metal
feature-family support and stable device properties to choose an M3 Max-tuned
dispatch or pipeline. Hardware conditions must not be duplicated across kernel
call sites.

Environment variables may expose candidate paths while benchmarking. A retained
optimization must become a normal runtime-selected implementation, with at most
a diagnostic opt-out. It must not create a permanent semantic variant.

If a tuned pipeline cannot be created or the device does not match its stated
requirements, use the existing general path. The fallback must produce the same
observable API behavior.

## Prefill Workstream

Profile the complete prefill graph at 2K, 8K, and 32K frontiers. Rank stages by
total GPU time and optimize the highest contributors first, considering:

- quantized dense and MoE matrix multiplication tile and threadgroup shapes;
- sparse-compressed-attention index construction;
- FlashAttention block geometry and reduction work;
- attention-output projections; and
- unnecessary command encoding, buffer transitions, or synchronization.

Prefill chunk size may be swept to understand memory/occupancy behavior, but a
chunk change is retained only if it preserves the expected checkpoint/logit
path and improves all target measurements without excess memory pressure.

## Decode Workstream

Profile single-token decode separately at the same context frontiers. Rank and
optimize:

- routed and shared-expert quantized matvec kernels;
- split-K FlashAttention and its reduction;
- small projection and elementwise dispatch geometry; and
- CPU submission, command-buffer boundaries, and GPU synchronization overhead.

Decode changes must be judged on complete token latency. A faster isolated
kernel is insufficient if it increases dispatch count or slows another stage.

## Correctness and Failure Policy

Do not relax numerical tolerances to accept an optimization. A candidate is
rejected if it changes official logprob-vector tokens, exceeds existing kernel
numeric tolerances, causes unstable output, or fails any relevant regression.

Pipeline construction or capability-selection failures fall back to the
existing path. Profiling allocation or timestamp unavailability must disable
profiling rather than fail inference.

## Verification Gates

Verify retained changes in this order:

1. focused Metal kernel numeric tests for each modified kernel;
2. `--metal-kernels` and `--logprob-vectors` coverage;
3. the complete `make test` suite;
4. interleaved whole-model performance runs at 2K, 8K, and 32K; and
5. a final benchmark CSV and concise before/after report containing model
   quantization, machine/backend, commands, medians, percentage deltas, and any
   notable failed experiments.

Completion requires at least a 5% median improvement in both prefill and decode
throughput. No target frontier may show a repeatable material regression, and
all correctness gates must pass. If measurement shows that one metric cannot
reach the threshold without regressing the other, continue profiling rather
than declaring a partial success.

## Delivery Boundaries

Keep implementation changes minimal and focused. Remove rejected experiments
and dead flags. Preserve the mmap-backed model-loading behavior. The final
change set includes only retained production code, relevant tests, and the
benchmark evidence needed to reproduce the result.
