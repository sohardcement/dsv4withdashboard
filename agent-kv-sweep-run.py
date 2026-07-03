#!/usr/bin/env python3
import argparse
import os
import shlex
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request


def live_server_pids():
    proc = subprocess.run(
        ["pgrep", "-x", "ds4-server"],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        check=False,
    )
    return [int(x) for x in proc.stdout.split() if x.strip().isdigit()]


def terminate_pid(pid, timeout):
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.2)
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def stop_process(proc, timeout):
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=timeout)


def run_checked(cmd, env, log_prefix=None):
    print("+", " ".join(cmd), flush=True)
    proc = subprocess.run(cmd, env=env, text=True, check=False)
    if proc.returncode != 0:
        where = f" ({log_prefix})" if log_prefix else ""
        raise RuntimeError(f"command failed{where}: {' '.join(cmd)} rc={proc.returncode}")


def capture_live_baseline(args):
    path = args.live_baseline_path
    cmd = [
        "./trace-cache-summary.py",
        args.live_baseline_trace,
        "--kv-dir",
        os.path.expanduser(args.live_baseline_kv_dir),
        "--live-config",
        "--json",
    ]
    if args.dry_run:
        print("+", " ".join(cmd), ">", path, flush=True)
        return f"live-old={path}"
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fp:
        print("+", " ".join(cmd), ">", path, flush=True)
        proc = subprocess.run(cmd, stdout=fp, text=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"live baseline capture failed rc={proc.returncode}")
    return f"live-old={path}"


def add_unique_baseline(baselines, spec):
    if spec not in baselines:
        baselines.append(spec)


def wait_ready(base_url, proc, timeout):
    url = base_url.rstrip("/") + "/v1/models"
    deadline = time.monotonic() + timeout
    last_err = None
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"ds4-server exited early rc={proc.returncode}")
        try:
            with urllib.request.urlopen(url, timeout=2.0) as resp:
                if 200 <= resp.status < 500:
                    return
        except (OSError, urllib.error.URLError) as e:
            last_err = e
        time.sleep(1.0)
    raise RuntimeError(f"server did not become ready at {url}: {last_err}")


def qenv(env):
    return " ".join(f"{k}={v}" for k, v in sorted(env.items()) if k.startswith("DS4_"))


def result_ready(path):
    return os.path.isfile(path) and os.path.getsize(path) > 0


def check_candidate_limit(args, total, pending):
    if args.max_candidates > 0 and pending > args.max_candidates:
        print(
            f"refusing to run {pending} pending candidates "
            f"(total={total}) because --max-candidates={args.max_candidates}",
            file=sys.stderr,
        )
        print(
            "narrow the matrix, add --skip-existing, or raise --max-candidates "
            "(use 0 to disable the guard).",
            file=sys.stderr,
        )
        return False
    return True


def candidate_matrix(args, intervals, prefill_chunks, boundary_aligns, cold_maxes, cache_mins):
    mtp_modes = ["on"]
    if args.include_mtp_off:
        mtp_modes.append("off")
    return [
        (interval, prefill_chunk, boundary_align, cold_max, cache_min, mode)
        for interval in intervals
        for prefill_chunk in prefill_chunks
        for boundary_align in boundary_aligns
        for cold_max in cold_maxes
        for cache_min in cache_mins
        for mode in mtp_modes
    ]


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


def candidate_env(args, interval, prefill_chunk, boundary_align, cold_max, cache_min, mtp_mode,
                  multi_prefill, multi_align, multi_cold, multi_cache_min, multi_mtp):
    label = candidate_label(
        interval, prefill_chunk, boundary_align, cold_max, cache_min, mtp_mode,
        multi_prefill, multi_align, multi_cold, multi_cache_min, multi_mtp,
    )
    kv_dir = args.kv_dir or (
        os.path.expanduser("~/.ds4/server-kv") if args.shared_kv_dir
        else os.path.join(args.results_dir, f"kv-{label}")
    )
    trace = args.trace or os.path.join(args.results_dir, f"{label}.trace.jsonl")
    server_log = os.path.join(args.results_dir, f"{label}.server.log")
    env = os.environ.copy()
    env.update({
        "DS4_TRACE": trace,
        "DS4_KV_DIR": kv_dir,
        "DS4_CONTINUED_INTERVAL": str(interval),
        "DS4_PREFILL_CHUNK": str(prefill_chunk),
        "DS4_BOUNDARY_ALIGN": str(boundary_align),
        "DS4_COLD_MAX": str(cold_max),
        "DS4_CACHE_MIN": str(cache_min),
        "DS4_CONFIG_SNAPSHOT": f"{trace}.config",
    })
    if mtp_mode == "off":
        env["DS4_MTP_PATH"] = ""
    if args.mtp_metrics:
        env["DS4_MTP_METRICS"] = "1"
        env["DS4_SERVER_LOG"] = server_log
    elif args.server_log:
        env["DS4_SERVER_LOG"] = server_log
    return label, env, kv_dir, trace, server_log


def candidate_result_path(args, interval, prefill_chunk, boundary_align, cold_max, cache_min,
                          mtp_mode, multi_prefill, multi_align, multi_cold,
                          multi_cache_min, multi_mtp):
    label = candidate_label(
        interval, prefill_chunk, boundary_align, cold_max, cache_min, mtp_mode,
        multi_prefill, multi_align, multi_cold, multi_cache_min, multi_mtp,
    )
    return os.path.join(args.results_dir, f"{label}.json")


def start_candidate_server(args, env, reset_trace):
    start_env = env.copy()
    if reset_trace:
        start_env["DS4_TRACE_RESET"] = "1"
    return subprocess.Popen(["./start-server.sh"], env=start_env)


def run_candidate_workload(args, proc, env, workload, label):
    wait_ready(args.base_url, proc, args.start_timeout)
    run_checked(["./agent-cache-check.sh", "--profile-only", "--strict"], env)
    run_checked(workload, env, label)


def workload_args(args, spec):
    workload = shlex.split(spec)
    if args.mtp_metrics and workload == ["./agent-kv-workload.py", "--run"]:
        workload += ["--max-tokens", str(args.mtp_workload_tokens)]
    return workload


def run_candidate(args, interval, prefill_chunk, boundary_align, cold_max, cache_min,
                  mtp_mode, multi_prefill, multi_align, multi_cold,
                  multi_cache_min, multi_mtp, is_last):
    label, env, kv_dir, trace, server_log = candidate_env(
        args, interval, prefill_chunk, boundary_align, cold_max, cache_min, mtp_mode,
        multi_prefill, multi_align, multi_cold, multi_cache_min, multi_mtp,
    )
    result = candidate_result_path(
        args, interval, prefill_chunk, boundary_align, cold_max, cache_min, mtp_mode,
        multi_prefill, multi_align, multi_cold, multi_cache_min, multi_mtp,
    )

    workload = workload_args(args, args.workload)
    replay_workload = workload_args(args, args.replay_workload or args.workload)

    print(f"\n== {label} ==", flush=True)
    print(qenv(env), flush=True)

    if args.skip_existing and not args.dry_run and result_ready(result):
        print(f"skip existing result: {result}", flush=True)
        return

    if args.dry_run:
        print("+ DS4_TRACE_RESET=1 ./start-server.sh", flush=True)
        print("+ ./agent-cache-check.sh --profile-only --strict", flush=True)
        print("+", " ".join(workload), flush=True)
        if args.restart_replay:
            print("+ stop candidate server", flush=True)
            print("+ ./start-server.sh", flush=True)
            print("+ ./agent-cache-check.sh --profile-only --strict", flush=True)
            print("+", " ".join(replay_workload), flush=True)
        extra = ["--server-log", server_log] if args.mtp_metrics or args.server_log else []
        print("+ ./trace-cache-summary.py", trace, "--kv-dir", kv_dir, *extra, "--json", ">", result, flush=True)
        return

    os.makedirs(args.results_dir, exist_ok=True)
    os.makedirs(kv_dir, exist_ok=True)

    proc = start_candidate_server(args, env, reset_trace=True)
    try:
        run_candidate_workload(args, proc, env, workload, label)
        if args.restart_replay:
            stop_process(proc, args.stop_timeout)
            proc = start_candidate_server(args, env, reset_trace=False)
            run_candidate_workload(args, proc, env, replay_workload, f"{label}:replay")
        summary_cmd = ["./trace-cache-summary.py", trace, "--kv-dir", kv_dir]
        if args.mtp_metrics or args.server_log:
            summary_cmd += ["--server-log", server_log]
        summary_cmd += ["--json"]
        with open(result, "w", encoding="utf-8") as fp:
            print("+", " ".join(summary_cmd), ">", result, flush=True)
            out = subprocess.run(summary_cmd, env=env, stdout=fp, text=True, check=False)
        if out.returncode != 0:
            raise RuntimeError(f"summary failed rc={out.returncode}")
    finally:
        if args.keep_server and is_last:
            print(f"leaving server running for {label} pid={proc.pid}", flush=True)
        else:
            stop_process(proc, args.stop_timeout)


def main():
    ap = argparse.ArgumentParser(
        description="Run ds4 agent KV cache sweep candidates safely."
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
    ap.add_argument("--trace",
                    help="shared trace path; default uses one trace per candidate under results-dir")
    ap.add_argument("--kv-dir",
                    help="shared KV dir; default isolates each candidate under results-dir")
    ap.add_argument("--shared-kv-dir", action="store_true",
                    help="use ~/.ds4/server-kv for every candidate")
    ap.add_argument("--workload", default="./agent-kv-workload.py --run",
                    help="workload command as a shell-style string")
    ap.add_argument("--replay-workload",
                    help="restart-replay workload command; default reuses --workload")
    ap.add_argument("--base-url", default="http://127.0.0.1:8077")
    ap.add_argument("--start-timeout", type=float, default=900.0)
    ap.add_argument("--stop-timeout", type=float, default=30.0)
    ap.add_argument("--mtp-metrics", action="store_true",
                    help="enable DS4_MTP_TIMING/CONF_LOG and parse server logs")
    ap.add_argument("--server-log", action="store_true",
                    help="capture server log without enabling MTP timing/conf metrics")
    ap.add_argument("--mtp-workload-tokens", type=int, default=32)
    ap.add_argument("--include-mtp-off", action="store_true",
                    help="also run each interval with DS4_MTP_PATH= to measure no-MTP baseline")
    ap.add_argument("--replace-live", action="store_true",
                    help="terminate existing ds4-server processes before running")
    ap.add_argument("--keep-server", action="store_true",
                    help="leave the last candidate server running instead of stopping it")
    ap.add_argument("--no-strict-results", action="store_true",
                    help="do not fail final comparison when result sufficiency gates fail")
    ap.add_argument("--no-default-protocol-gates", action="store_true",
                    help="do not require chat/responses/anthropic protocol coverage for the default workload")
    ap.add_argument("--require-protocol", action="append", default=[],
                    choices=["chat", "responses", "anthropic", "completion"],
                    help="additional protocol coverage gate for final comparison; repeatable")
    ap.add_argument("--skip-existing", action="store_true",
                    help="skip candidate runs whose JSON result already exists and is non-empty")
    ap.add_argument("--compare-baseline", action="append", default=[],
                    help="baseline JSON to pass to agent-kv-compare as --baseline; repeatable; optionally label=path")
    ap.add_argument("--capture-live-baseline", action="store_true",
                    help="capture the currently running ds4-server as live-old baseline before replacing it")
    ap.add_argument("--live-baseline-path", default="/tmp/ds4-live-old-baseline.json")
    ap.add_argument("--live-baseline-trace", default="/tmp/ds4-trace.jsonl")
    ap.add_argument("--live-baseline-kv-dir", default="~/.ds4/server-kv")
    ap.add_argument("--max-candidates", type=int, default=32,
                    help="maximum pending candidates to run; use 0 to disable; default: 32")
    ap.add_argument("--restart-replay", action="store_true",
                    help="after the first workload, restart the candidate with the same KV dir and run the workload again")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    args.results_dir = args.results_dir.rstrip("/")
    candidates = args.candidate or [4096]
    prefill_chunks = args.prefill_chunk or [4096]
    boundary_aligns = args.boundary_align or [2048]
    cold_maxes = args.cold_max or [98304]
    cache_mins = args.cache_min or [1024]
    matrix = candidate_matrix(args, candidates, prefill_chunks, boundary_aligns, cold_maxes, cache_mins)
    multi_prefill = len(prefill_chunks) > 1
    multi_align = len(boundary_aligns) > 1
    multi_cold = len(cold_maxes) > 1
    multi_cache_min = len(cache_mins) > 1
    multi_mtp = args.include_mtp_off
    results = [
        candidate_result_path(
            args, interval, prefill_chunk, boundary_align, cold_max, cache_min, mtp_mode,
            multi_prefill, multi_align, multi_cold, multi_cache_min, multi_mtp,
        )
        for interval, prefill_chunk, boundary_align, cold_max, cache_min, mtp_mode in matrix
    ]
    pending = [
        result for result in results
        if not args.skip_existing or not result_ready(result)
    ]
    print(f"candidate_count total={len(matrix)} pending={len(pending)}", flush=True)
    if not check_candidate_limit(args, len(matrix), len(pending)):
        return 2

    pids = live_server_pids()
    if args.keep_server and len(pending) > 1:
        print("--keep-server is only supported with a single candidate variant", file=sys.stderr)
        return 2

    compare_baselines = []
    for baseline in args.compare_baseline:
        add_unique_baseline(compare_baselines, baseline)
    if args.capture_live_baseline:
        add_unique_baseline(compare_baselines, capture_live_baseline(args))

    if pids and pending and not args.replace_live and not args.dry_run:
        print(
            "refusing to run sweep while ds4-server is already running: "
            + ",".join(str(p) for p in pids),
            file=sys.stderr,
        )
        print("stop it yourself when clients are idle, or pass --replace-live explicitly.", file=sys.stderr)
        return 1
    if pids and pending and args.replace_live and not args.dry_run:
        for pid in pids:
            print(f"terminating existing ds4-server pid={pid}", flush=True)
            terminate_pid(pid, args.stop_timeout)

    for idx, (interval, prefill_chunk, boundary_align, cold_max, cache_min, mtp_mode) in enumerate(matrix):
        run_candidate(
            args, interval, prefill_chunk, boundary_align, cold_max, cache_min, mtp_mode,
            multi_prefill, multi_align, multi_cold, multi_cache_min, multi_mtp,
            idx == len(matrix) - 1,
        )

    compare_cmd = ["./agent-kv-compare.py"]
    for baseline in compare_baselines:
        compare_cmd += ["--baseline", baseline]
    compare_cmd += results
    if not args.no_strict_results:
        compare_cmd += ["--strict", "--min-completed", "1", "--require-auto-frontier"]
        required_protocols = list(args.require_protocol)
        if (
            not args.no_default_protocol_gates and
            args.workload == "./agent-kv-workload.py --run"
        ):
            for protocol in ["chat", "responses", "anthropic"]:
                if protocol not in required_protocols:
                    required_protocols.append(protocol)
        for protocol in required_protocols:
            compare_cmd += ["--require-protocol", protocol]
        if args.restart_replay:
            compare_cmd += ["--require-disk-text"]
        if args.mtp_metrics:
            compare_cmd += ["--require-mtp-attempts-when-enabled"]
    if not args.dry_run:
        run_checked(compare_cmd, os.environ.copy())
    else:
        print("+", " ".join(compare_cmd), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
