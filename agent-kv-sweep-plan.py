#!/usr/bin/env python3
import argparse
import os
import shlex


def q(s):
    return shlex.quote(str(s))


def candidate_label(interval, prefill_chunk, boundary_align, cold_max, cache_min, mtp_mode,
                    multi_prefill, multi_align, multi_cold, multi_cache_min, multi_mtp):
    label = f"interval-{interval}"
    if multi_prefill:
        label += f"-chunk-{prefill_chunk}"
    if multi_align:
        label += f"-align-{boundary_align}"
    if multi_cold:
        label += f"-cold-{cold_max}"
    if multi_cache_min:
        label += f"-min-{cache_min}"
    if multi_mtp:
        label += f"-mtp-{mtp_mode}"
    return label


def workload_for(args, spec):
    workload = spec
    if args.mtp_metrics and workload == "./agent-kv-workload.py --run":
        workload = f"{workload} --max-tokens {args.mtp_workload_tokens}"
    return workload


def main():
    ap = argparse.ArgumentParser(
        description="Print a safe manual sweep plan for ds4 agent KV cache candidates."
    )
    ap.add_argument("--candidate", type=int, action="append",
                    help="continued interval candidate; repeatable; default: 4096")
    ap.add_argument("--results-dir", default="/tmp/ds4-agent-kv-runs")
    ap.add_argument("--prefill-chunk", type=int, action="append",
                    help="prefill chunk candidate; repeatable; default: 4096")
    ap.add_argument("--boundary-align", type=int, action="append",
                    help="boundary alignment candidate; repeatable; default: 2048")
    ap.add_argument("--cold-max", type=int, action="append",
                    help="kv-cache-cold-max candidate; repeatable; default: 98304")
    ap.add_argument("--cache-min", type=int, action="append",
                    help="kv-cache-min candidate; repeatable; default: 1024")
    ap.add_argument("--trace", default="/tmp/ds4-trace.jsonl")
    ap.add_argument("--kv-dir", default=None,
                    help="shared KV dir; default isolates each candidate under results-dir")
    ap.add_argument("--workload", default="./agent-kv-workload.py --run")
    ap.add_argument("--replay-workload",
                    help="restart-replay workload command; default reuses --workload")
    ap.add_argument("--mtp-workload-tokens", type=int, default=32,
                    help="when --mtp-metrics uses the default workload, request this many output tokens")
    ap.add_argument("--mtp-metrics", action="store_true",
                    help="enable DS4_MTP_TIMING/CONF_LOG through start-server.sh and parse server logs")
    ap.add_argument("--include-mtp-off", action="store_true",
                    help="also print a DS4_MTP_PATH= no-MTP baseline for each interval")
    ap.add_argument("--restart-replay", action="store_true",
                    help="print a restart and replay phase before summarizing")
    ap.add_argument("--no-default-protocol-gates", action="store_true",
                    help="do not require chat/responses/anthropic protocol coverage for the default workload")
    ap.add_argument("--require-protocol", action="append", default=[],
                    choices=["chat", "responses", "anthropic", "completion"],
                    help="additional protocol coverage gate for final comparison; repeatable")
    ap.add_argument("--compare-baseline", action="append", default=[],
                    help="baseline JSON to pass to agent-kv-compare as --baseline; repeatable; optionally label=path")
    ap.add_argument("--shared-kv-dir", action="store_true",
                    help="use ~/.ds4/server-kv for every candidate instead of isolated dirs")
    args = ap.parse_args()

    candidates = args.candidate or [4096]
    prefill_chunks = args.prefill_chunk or [4096]
    boundary_aligns = args.boundary_align or [2048]
    cold_maxes = args.cold_max or [98304]
    cache_mins = args.cache_min or [1024]
    results_dir = args.results_dir.rstrip("/")
    workload = workload_for(args, args.workload)
    replay_workload = workload_for(args, args.replay_workload or args.workload)

    print("# DS4 agent KV cache sweep plan")
    print("# Run one block at a time, only after active agent clients are idle.")
    print(f"mkdir -p {q(results_dir)}")
    print()

    mtp_modes = ["on"] + (["off"] if args.include_mtp_off else [])
    multi_prefill = len(prefill_chunks) > 1
    multi_align = len(boundary_aligns) > 1
    multi_cold = len(cold_maxes) > 1
    multi_cache_min = len(cache_mins) > 1
    multi_mtp = args.include_mtp_off

    for interval in candidates:
        for prefill_chunk in prefill_chunks:
            for boundary_align in boundary_aligns:
                for cold_max in cold_maxes:
                    for cache_min in cache_mins:
                        for mtp_mode in mtp_modes:
                            label = candidate_label(
                                interval, prefill_chunk, boundary_align, cold_max, cache_min, mtp_mode,
                                multi_prefill, multi_align, multi_cold, multi_cache_min, multi_mtp,
                            )
                            result = f"{results_dir}/{label}.json"
                            server_log = f"{results_dir}/{label}.server.log"
                            if args.kv_dir:
                                kv_dir = args.kv_dir
                            elif args.shared_kv_dir:
                                kv_dir = os.path.expanduser("~/.ds4/server-kv")
                            else:
                                kv_dir = f"{results_dir}/kv-{label}"
                            env = (
                                f"DS4_TRACE={q(args.trace)} "
                                f"DS4_KV_DIR={q(kv_dir)} "
                                f"DS4_CONTINUED_INTERVAL={interval} "
                                f"DS4_PREFILL_CHUNK={prefill_chunk} "
                                f"DS4_BOUNDARY_ALIGN={boundary_align} "
                                f"DS4_COLD_MAX={cold_max} "
                                f"DS4_CACHE_MIN={cache_min}"
                            )
                            if mtp_mode == "off":
                                env = f"{env} DS4_MTP_PATH="
                            start_env = env
                            summary_extra = ""
                            if args.mtp_metrics:
                                start_env = f"{env} DS4_MTP_METRICS=1 DS4_SERVER_LOG={q(server_log)}"
                                summary_extra = f" --server-log {q(server_log)}"
                            print(f"# Candidate: {label}")
                            print("# 1. Stop the current ds4-server when it is safe.")
                            print("# 2. Start this candidate in a fresh terminal:")
                            print(
                                "DS4_TRACE_RESET=1 "
                                f"{start_env} "
                                "./start-server.sh"
                            )
                            print("# 3. In another terminal, verify profile and run the workload:")
                            print(f"{env} ./agent-cache-check.sh --profile-only --strict")
                            print(f"{env} {workload}")
                            step = 4
                            if args.restart_replay:
                                print("# 4. Stop this candidate, restart it with the same KV dir, then replay:")
                                print("#    Do not set DS4_TRACE_RESET for this restart.")
                                print(f"{start_env} ./start-server.sh")
                                print(f"{env} ./agent-cache-check.sh --profile-only --strict")
                                print(f"{env} {replay_workload}")
                                step = 5
                            print(f"# {step}. Save metrics for comparison:")
                            print(
                                f"{env} ./trace-cache-summary.py {q(args.trace)} "
                                f"--kv-dir {q(kv_dir)}{summary_extra} --json > {q(result)}"
                            )
                            print()

    joined = " ".join(
        q(
            f"{results_dir}/"
            f"{candidate_label(interval, prefill_chunk, boundary_align, cold_max, cache_min, mtp_mode, multi_prefill, multi_align, multi_cold, multi_cache_min, multi_mtp)}.json"
        )
        for interval in candidates
        for prefill_chunk in prefill_chunks
        for boundary_align in boundary_aligns
        for cold_max in cold_maxes
        for cache_min in cache_mins
        for mtp_mode in mtp_modes
    )
    print("# Compare all completed candidates:")
    baseline_args = " ".join(
        f"--baseline {q(baseline)}" for baseline in args.compare_baseline
    )
    compare = "./agent-kv-compare.py"
    if baseline_args:
        compare += f" {baseline_args}"
    compare += f" {joined} --strict --min-completed 1 --require-auto-frontier"
    required_protocols = list(args.require_protocol)
    if not args.no_default_protocol_gates and args.workload == "./agent-kv-workload.py --run":
        for protocol in ["chat", "responses", "anthropic"]:
            if protocol not in required_protocols:
                required_protocols.append(protocol)
    for protocol in required_protocols:
        compare += f" --require-protocol {q(protocol)}"
    if args.restart_replay:
        compare += " --require-disk-text"
    if args.mtp_metrics:
        compare += " --require-mtp-attempts-when-enabled"
    print(compare)


if __name__ == "__main__":
    raise SystemExit(main())
