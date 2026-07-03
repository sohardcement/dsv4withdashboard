#!/usr/bin/env python3
import argparse
import os
import shlex
import subprocess
import sys


def run(cmd, stdout_path=None):
    if stdout_path:
        os.makedirs(os.path.dirname(stdout_path) or ".", exist_ok=True)
        print("+", " ".join(shlex.quote(x) for x in cmd), ">", stdout_path, flush=True)
        with open(stdout_path, "w", encoding="utf-8") as fp:
            proc = subprocess.run(cmd, stdout=fp, text=True, check=False)
    else:
        print("+", " ".join(shlex.quote(x) for x in cmd), flush=True)
        proc = subprocess.run(cmd, text=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"command failed rc={proc.returncode}: {' '.join(cmd)}")


def live_pids():
    proc = subprocess.run(
        ["pgrep", "-x", "ds4-server"],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        check=False,
    )
    return [pid for pid in proc.stdout.split() if pid.isdigit()]


def summary_cmd(trace, kv_dir, server_log):
    cmd = [
        "./trace-cache-summary.py",
        trace,
        "--kv-dir",
        os.path.expanduser(kv_dir),
        "--live-config",
        "--json",
    ]
    if server_log:
        cmd += ["--server-log", server_log]
    return cmd


def main():
    ap = argparse.ArgumentParser(
        description="Capture a read-only baseline for the currently running ds4-server."
    )
    ap.add_argument("--out-dir", default="/tmp/ds4-live-baseline")
    ap.add_argument("--label", default="live-old")
    ap.add_argument("--trace", default="/tmp/ds4-trace.jsonl")
    ap.add_argument("--kv-dir", default="~/.ds4/server-kv")
    ap.add_argument("--server-log",
                    help="optional server log to parse for MTP metrics")
    ap.add_argument("--run-workload", action="store_true",
                    help="send the workload after the before snapshot; default is read-only")
    ap.add_argument("--workload",
                    default="./agent-kv-workload.py --run --skip-profile-check",
                    help="shell-style workload command; used only with --run-workload")
    ap.add_argument("--compare", action="store_true",
                    help="compare before/after when --run-workload is used")
    args = ap.parse_args()

    pids = live_pids()
    if not pids:
        print("no ds4-server process found", file=sys.stderr)
        return 1

    os.makedirs(args.out_dir, exist_ok=True)
    before = os.path.join(args.out_dir, f"{args.label}-before.json")
    after = os.path.join(args.out_dir, f"{args.label}-after.json")

    print("live ds4-server pid(s):", ",".join(pids), flush=True)
    run(summary_cmd(args.trace, args.kv_dir, args.server_log), before)

    if not args.run_workload:
        print(f"captured read-only baseline: {before}")
        print("add --run-workload to send the synthetic agent workload to the live server")
        return 0

    workload = shlex.split(args.workload)
    run(workload)
    run(summary_cmd(args.trace, args.kv_dir, args.server_log), after)

    if args.compare:
        run([
            "./agent-kv-compare.py",
            "--baseline", f"{args.label}-before={before}",
            f"{args.label}-after={after}",
        ])
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as e:
        print(str(e), file=sys.stderr)
        raise SystemExit(1)
