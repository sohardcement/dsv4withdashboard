#!/usr/bin/env python3
import argparse
import json
import os
import re
import shlex
import struct
import subprocess
from collections import Counter, defaultdict


REQ_RE = re.compile(r"^===== request (\d+) (.*?) =====")
END_RE = re.compile(r"^===== end request (\d+) =====")
RAW_MARKER = "--- raw request json ---"
MTP_TIMING_RE = re.compile(r"ds4: mtp timing (\S+) (.*)$")
MTP_CONF_RE = re.compile(r"ds4: mtp conf (.*)$")
MTP_KV_RE = re.compile(r"([a-zA-Z0-9_]+)=(-?[0-9]+(?:\.[0-9]+)?)")

REASON = {
    0: "unknown",
    1: "cold",
    2: "continued",
    3: "evict",
    4: "shutdown",
    5: "agent-system",
    6: "agent-session",
}

EXT = {
    1 << 0: "tool-map",
    1 << 1: "responses-visible",
    1 << 2: "thinking-visible",
    1 << 3: "session-title",
}


def infer_protocol(payload):
    if not isinstance(payload, dict):
        return "unknown"
    if "input" in payload or "instructions" in payload:
        return "responses"
    if "prompt" in payload and "messages" not in payload:
        return "completion"
    tools = payload.get("tools")
    if isinstance(tools, list):
        for tool in tools:
            if isinstance(tool, dict) and "input_schema" in tool:
                return "anthropic"
    if "anthropic_version" in payload:
        return "anthropic"
    return "chat"


def parse_trace(path):
    requests = []
    cur = None
    raw_buf = None
    try:
        fp = open(path, "rb")
    except OSError:
        return requests
    with fp:
        for raw in fp:
            line = raw.decode("utf-8", "replace").rstrip("\n")
            if raw_buf is not None:
                if line.startswith("--- ") and raw_buf:
                    raw_buf = None
                else:
                    raw_buf.append(line)
                    text = "\n".join(raw_buf).strip()
                    if text:
                        try:
                            payload = json.loads(text)
                        except json.JSONDecodeError:
                            continue
                        cur["protocol"] = infer_protocol(payload)
                        raw_buf = None
                    continue
            m = REQ_RE.match(line)
            if m:
                if cur is not None:
                    requests.append(cur)
                cur = {"id": int(m.group(1)), "ts": m.group(2), "ended": False}
                continue
            if cur is None:
                continue
            if line == RAW_MARKER:
                raw_buf = []
                continue
            m = END_RE.match(line)
            if m:
                cur["ended"] = True
                continue
            if ":" not in line:
                continue
            key, val = line.split(":", 1)
            key = key.strip()
            val = val.strip()
            if key in {
                "prompt_tokens",
                "effective_prompt_tokens",
                "cached_tokens",
                "disk_cached_tokens",
                "live_tokens_before",
                "live_prompt_common",
                "first_mismatch_token",
                "generated_tokens",
            }:
                try:
                    cur[key] = int(val)
                except ValueError:
                    pass
            elif key == "elapsed_sec":
                try:
                    cur[key] = float(val)
                except ValueError:
                    pass
            elif key in {"cache_source", "memory_miss_reason"}:
                cur[key] = val
    if cur is not None:
        requests.append(cur)
    return requests


def parse_config(path):
    values = {}
    if not path:
        return values
    try:
        fp = open(path, "r", encoding="utf-8")
    except OSError:
        return values
    with fp:
        for line in fp:
            line = line.rstrip("\n")
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            values[key] = val
    return values


LIVE_FLAG_MAP = {
    "--model": "model",
    "--ctx": "ctx",
    "--threads": "threads",
    "--host": "host",
    "--port": "port",
    "--trace": "trace",
    "--kv-disk-dir": "kv_dir",
    "--kv-disk-space-mb": "kv_space_mb",
    "--kv-cache-min-tokens": "cache_min",
    "--kv-cache-cold-max-tokens": "cold_max",
    "--kv-cache-continued-interval-tokens": "continued_interval",
    "--kv-cache-boundary-trim-tokens": "boundary_trim",
    "--kv-cache-boundary-align-tokens": "boundary_align",
    "--tool-memory-max-ids": "tool_memory_max_ids",
    "--prefill-chunk": "prefill_chunk",
    "--mtp": "mtp_path",
    "--mtp-draft": "mtp_draft",
    "--mtp-margin": "mtp_margin",
}


def parse_live_config():
    try:
        pgrep = subprocess.run(
            ["pgrep", "-x", "ds4-server"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            check=False,
        )
    except OSError:
        return {}
    pids = [pid for pid in pgrep.stdout.split() if pid.isdigit()]
    if not pids:
        return {}
    try:
        proc = subprocess.run(
            ["ps", "-p", ",".join(pids), "-o", "pid=,command="],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            check=False,
        )
    except OSError:
        return {}
    rows = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    if not rows:
        return {}
    row = rows[0]
    pid, _, command = row.partition(" ")
    try:
        parts = shlex.split(command)
    except ValueError:
        parts = command.split()
    cfg = {
        "live_pid": pid.strip(),
        "command_line": command,
    }
    i = 0
    while i < len(parts):
        part = parts[i]
        key = LIVE_FLAG_MAP.get(part)
        if key and i + 1 < len(parts):
            cfg[key] = parts[i + 1]
            i += 2
            continue
        i += 1
    return cfg


def merge_missing_config(primary, fallback):
    merged = dict(primary)
    for key, val in fallback.items():
        if key not in merged or merged.get(key) in (None, ""):
            merged[key] = val
    return merged


def parse_mtp_log(path):
    rows = []
    conf_rows = []
    first_misses = 0
    verifier_fallbacks = 0
    if not path:
        return {
            "path": path,
            "attempts": 0,
            "drafted_tokens": 0,
            "committed_tokens": 0,
            "acceptance_rate": 0.0,
            "full_accepts": 0,
            "partial_accepts": 0,
            "first_misses": 0,
            "verifier_fallbacks": 0,
            "modes": {},
            "avg_total_ms": 0.0,
            "avg_draft_ms": 0.0,
            "avg_verify_ms": 0.0,
            "avg_snapshot_ms": 0.0,
            "avg_replay_ms": 0.0,
            "avg_prefix_ms": 0.0,
            "conf": {
                "count": 0,
                "avg_margin": 0.0,
                "min_margin": None,
                "max_margin": None,
            },
        }
    try:
        fp = open(path, "rb")
    except OSError:
        return {
            "path": path,
            "attempts": 0,
            "drafted_tokens": 0,
            "committed_tokens": 0,
            "acceptance_rate": 0.0,
            "full_accepts": 0,
            "partial_accepts": 0,
            "first_misses": 0,
            "verifier_fallbacks": 0,
            "modes": {},
            "avg_total_ms": 0.0,
            "avg_draft_ms": 0.0,
            "avg_verify_ms": 0.0,
            "avg_snapshot_ms": 0.0,
            "avg_replay_ms": 0.0,
            "avg_prefix_ms": 0.0,
            "conf": {
                "count": 0,
                "avg_margin": 0.0,
                "min_margin": None,
                "max_margin": None,
            },
        }
    with fp:
        for raw in fp:
            line = raw.decode("utf-8", "replace").strip()
            if "ds4: mtp spec miss first" in line:
                first_misses += 1
            if "mtp spec micro verifier failed" in line or "decode2 verifier failed" in line:
                verifier_fallbacks += 1
            m = MTP_TIMING_RE.search(line)
            if m:
                mode = m.group(1)
                vals = {k: float(v) for k, v in MTP_KV_RE.findall(m.group(2))}
                drafted = int(vals.get("drafted", 0))
                committed = int(vals.get("committed", vals.get("verified", 0)))
                rows.append({
                    "mode": mode,
                    "drafted": drafted,
                    "committed": committed,
                    "draft_ms": vals.get("draft", 0.0),
                    "snapshot_ms": vals.get("snapshot", 0.0),
                    "verify_ms": vals.get("verify", 0.0),
                    "prefix_ms": vals.get("prefix", 0.0),
                    "replay_ms": vals.get("replay", vals.get("exact_replay", 0.0)),
                    "total_ms": vals.get("total", 0.0),
                })
                continue
            m = MTP_CONF_RE.search(line)
            if m:
                vals = {k: float(v) for k, v in MTP_KV_RE.findall(m.group(1))}
                if "margin" in vals:
                    conf_rows.append(vals)

    drafted = sum(r["drafted"] for r in rows)
    committed = sum(r["committed"] for r in rows)
    margins = [r["margin"] for r in conf_rows if "margin" in r]
    modes = Counter(r["mode"] for r in rows)
    return {
        "path": path,
        "attempts": len(rows),
        "drafted_tokens": drafted,
        "committed_tokens": committed,
        "acceptance_rate": committed / drafted if drafted else 0.0,
        "full_accepts": len([r for r in rows if r["drafted"] > 0 and r["committed"] >= r["drafted"]]),
        "partial_accepts": len([r for r in rows if r["drafted"] > 0 and r["committed"] < r["drafted"]]),
        "first_misses": first_misses,
        "verifier_fallbacks": verifier_fallbacks,
        "modes": dict(sorted(modes.items())),
        "avg_total_ms": mean([r["total_ms"] for r in rows]),
        "avg_draft_ms": mean([r["draft_ms"] for r in rows]),
        "avg_verify_ms": mean([r["verify_ms"] for r in rows]),
        "avg_snapshot_ms": mean([r["snapshot_ms"] for r in rows]),
        "avg_replay_ms": mean([r["replay_ms"] for r in rows]),
        "avg_prefix_ms": mean([r["prefix_ms"] for r in rows]),
        "conf": {
            "count": len(conf_rows),
            "avg_margin": mean(margins),
            "min_margin": min(margins) if margins else None,
            "max_margin": max(margins) if margins else None,
        },
    }


def parse_kv_dir(path):
    rows = []
    if not path:
        return rows
    try:
        names = os.listdir(path)
    except OSError:
        return rows
    for name in names:
        if not name.endswith(".kv"):
            continue
        full = os.path.join(path, name)
        try:
            st = os.stat(full)
            with open(full, "rb") as fp:
                hdr = fp.read(48)
                text_len_b = fp.read(4)
        except OSError:
            continue
        if len(hdr) != 48 or len(text_len_b) != 4:
            continue
        if hdr[:4] != b"KVC\x01" or hdr[20] != 2:
            continue
        quant = hdr[4]
        reason = hdr[5]
        ext_flags = hdr[6]
        model_id = hdr[7]
        tokens, hits, ctx_size = struct.unpack_from("<III", hdr, 8)
        created_at = struct.unpack_from("<Q", hdr, 24)[0]
        last_used = struct.unpack_from("<Q", hdr, 32)[0]
        payload_bytes = struct.unpack_from("<Q", hdr, 40)[0]
        text_bytes = struct.unpack("<I", text_len_b)[0]
        rows.append({
            "path": full,
            "name": name,
            "size": st.st_size,
            "mtime": st.st_mtime,
            "quant": quant,
            "reason": reason,
            "reason_name": REASON.get(reason, "unknown"),
            "ext_flags": ext_flags,
            "ext": ",".join(v for bit, v in EXT.items() if ext_flags & bit) or "-",
            "model_id": model_id,
            "tokens": tokens,
            "hits": hits,
            "ctx_size": ctx_size,
            "created_at": created_at,
            "last_used": last_used,
            "payload_bytes": payload_bytes,
            "text_bytes": text_bytes,
        })
    return rows


def mean(xs):
    return sum(xs) / len(xs) if xs else 0.0


def percentile(xs, pct):
    if not xs:
        return 0.0
    xs = sorted(xs)
    idx = int(round((len(xs) - 1) * pct / 100.0))
    return xs[idx]


def fmt_tokens(n):
    if n is None:
        return "-"
    if abs(n) >= 1000:
        return f"{n / 1000:.1f}k"
    return str(n)


def aligned_step(interval, align):
    if interval <= 0:
        return 0
    if align > 0:
        interval = ((interval + align - 1) // align) * align
    return interval


def interval_candidate_metrics(requests, compare_intervals, boundary_align):
    mismatches = [r["first_mismatch_token"] for r in requests if "first_mismatch_token" in r]
    prompts = [r.get("prompt_tokens", 0) for r in requests if r.get("prompt_tokens", 0) > 0]
    out = []
    if not compare_intervals or not mismatches:
        return out
    for interval in compare_intervals:
        step = aligned_step(interval, boundary_align)
        if step <= 0:
            continue
        covered = []
        missed = 0
        for mismatch in mismatches:
            if step < mismatch:
                covered.append(((mismatch - 1) // step) * step)
            else:
                missed += 1

        checkpoint_counts = [prompt // step for prompt in prompts]
        checkpoint_token_positions = [
            step * count * (count + 1) // 2
            for count in checkpoint_counts
        ]
        total_checkpoints = sum(checkpoint_counts)
        out.append({
            "interval": interval,
            "aligned_step": step,
            "covered": len(covered),
            "total": len(mismatches),
            "missed": missed,
            "coverage": len(covered) / len(mismatches) if mismatches else 0.0,
            "avg_prefix_tokens": mean(covered),
            "min_prefix_tokens": min(covered) if covered else 0,
            "estimated_checkpoints": total_checkpoints,
            "avg_checkpoints_per_request": mean(checkpoint_counts),
            "max_checkpoints_per_request": max(checkpoint_counts) if checkpoint_counts else 0,
            "estimated_checkpoint_token_positions": sum(checkpoint_token_positions),
            "avg_checkpoint_token_positions_per_request": mean(checkpoint_token_positions),
        })
    return out


def summarize(requests, slow_threshold, early_threshold, last, kv_dir=None,
              compare_intervals=None, boundary_align=2048, server_log=None):
    completed = [r for r in requests if "elapsed_sec" in r]
    total_gen = sum(r.get("generated_tokens", 0) for r in completed)
    total_elapsed = sum(r.get("elapsed_sec", 0.0) for r in completed)
    print(f"requests: {len(requests)} completed: {len(completed)}")
    if completed:
        print(
            "elapsed: "
            f"avg={mean([r['elapsed_sec'] for r in completed]):.1f}s "
            f"p50={percentile([r['elapsed_sec'] for r in completed], 50):.1f}s "
            f"p90={percentile([r['elapsed_sec'] for r in completed], 90):.1f}s "
            f"max={max(r['elapsed_sec'] for r in completed):.1f}s"
        )
        print(f"overall generated tokens/sec: {total_gen / total_elapsed if total_elapsed else 0.0:.2f}")

    by_source = defaultdict(list)
    for r in completed:
        by_source[r.get("cache_source", "unknown")].append(r)
    print("\ncache sources:")
    for source in sorted(by_source):
        rows = by_source[source]
        print(
            f"  {source:12s} count={len(rows):3d} "
            f"avg_elapsed={mean([r['elapsed_sec'] for r in rows]):6.1f}s "
            f"avg_prompt={fmt_tokens(int(mean([r.get('prompt_tokens', 0) for r in rows]))):>6s} "
            f"avg_cached={fmt_tokens(int(mean([r.get('cached_tokens', 0) for r in rows]))):>6s}"
        )

    by_protocol = defaultdict(list)
    for r in completed:
        by_protocol[r.get("protocol", "unknown")].append(r)
    if by_protocol:
        print("\nprotocols:")
        for protocol in sorted(by_protocol):
            rows = by_protocol[protocol]
            none_count = len([r for r in rows if r.get("cache_source") == "none"])
            disk_count = len([r for r in rows if r.get("cache_source") == "disk-text"])
            print(
                f"  {protocol:12s} count={len(rows):3d} "
                f"avg_elapsed={mean([r['elapsed_sec'] for r in rows]):6.1f}s "
                f"none={none_count / len(rows) if rows else 0.0:5.0%} "
                f"disk={disk_count:3d} "
                f"avg_prompt={fmt_tokens(int(mean([r.get('prompt_tokens', 0) for r in rows]))):>6s}"
            )

    miss = Counter(r.get("memory_miss_reason", "") for r in requests if r.get("memory_miss_reason"))
    if miss:
        print("\nmiss reasons:")
        for reason, count in miss.most_common():
            print(f"  {reason:20s} {count}")

    mismatches = [r["first_mismatch_token"] for r in requests if "first_mismatch_token" in r]
    early = [r for r in requests if r.get("first_mismatch_token", early_threshold + 1) <= early_threshold]
    if mismatches:
        print(
            "\nfirst mismatch: "
            f"count={len(mismatches)} "
            f"avg={mean(mismatches):.0f} "
            f"min={min(mismatches)} "
            f"early<={early_threshold}={len(early)}"
        )
        min_mm = min(mismatches)
        useful = [n for n in (2048, 4096, 8192, 12288, 16384) if n < min_mm]
        if useful:
            print(
                "checkpoint hint: "
                f"earliest mismatch is {min_mm}; "
                f"a continued interval of {useful[-1]} or smaller can leave a reusable disk prefix before it"
            )
        else:
            print(
                "checkpoint hint: earliest mismatch is before 2048 tokens; "
                "KV tuning alone can only save a very small prefix"
            )

    if compare_intervals and mismatches:
        print("\ncontinued interval candidates:")
        for row in interval_candidate_metrics(requests, compare_intervals, boundary_align):
            print(
                f"  interval={row['interval']:5d} aligned_step={row['aligned_step']:5d} "
                f"covered={row['covered']:3d}/{row['total']:3d} "
                f"missed={row['missed']:3d} "
                f"avg_prefix={fmt_tokens(int(row['avg_prefix_tokens'])):>6s} "
                f"min_prefix={fmt_tokens(row['min_prefix_tokens']):>6s} "
                f"avg_ckpt={row['avg_checkpoints_per_request']:4.1f} "
                f"avg_write={fmt_tokens(int(row['avg_checkpoint_token_positions_per_request'])):>6s}"
            )

    slow = [r for r in completed if r["elapsed_sec"] >= slow_threshold]
    print(f"\nslow requests >= {slow_threshold:.0f}s: {len(slow)}")
    for r in slow[-last:]:
        print(
            f"  req={r.get('id')} ts={r.get('ts')} "
            f"protocol={r.get('protocol', '-')} "
            f"elapsed={r.get('elapsed_sec', 0.0):.1f}s "
            f"source={r.get('cache_source', '-')} "
            f"prompt={fmt_tokens(r.get('prompt_tokens'))} "
            f"cached={fmt_tokens(r.get('cached_tokens'))} "
            f"first={fmt_tokens(r.get('first_mismatch_token'))} "
            f"gen={fmt_tokens(r.get('generated_tokens'))}"
        )

    print(f"\nlast {last} requests:")
    for r in requests[-last:]:
        elapsed = r.get("elapsed_sec")
        elapsed_s = f"{elapsed:.1f}s" if elapsed is not None else "-"
        print(
            f"  req={r.get('id')} ended={int(r.get('ended', False))} "
            f"protocol={r.get('protocol', '-'):10s} "
            f"elapsed={elapsed_s:>7s} "
            f"source={r.get('cache_source', '-'):12s} "
            f"prompt={fmt_tokens(r.get('prompt_tokens')):>6s} "
            f"cached={fmt_tokens(r.get('cached_tokens')):>6s} "
            f"first={fmt_tokens(r.get('first_mismatch_token')):>6s}"
        )

    if kv_dir:
        rows = parse_kv_dir(kv_dir)
        print(f"\nkv dir: {kv_dir}")
        print(f"kv files: {len(rows)}")
        if rows:
            by_reason = Counter(r["reason_name"] for r in rows)
            print("kv reasons:")
            for reason, count in by_reason.most_common():
                print(f"  {reason:14s} {count}")

            by_tokens = Counter(r["tokens"] for r in rows)
            print("kv token frontiers:")
            for tokens, count in sorted(by_tokens.items())[:24]:
                print(f"  {tokens:7d} ({fmt_tokens(tokens):>6s}) {count}")
            if len(by_tokens) > 24:
                print(f"  ... {len(by_tokens) - 24} more")

            if mismatches:
                min_mm = min(mismatches)
                before = [r for r in rows if 0 < r["tokens"] < min_mm]
                if before:
                    best = max(before, key=lambda r: r["tokens"])
                    print(
                        "kv coverage before earliest mismatch: "
                        f"best={best['tokens']} tokens "
                        f"reason={best['reason_name']} "
                        f"size={best['size'] / (1024 * 1024):.1f}MiB"
                    )
                else:
                    print(
                        "kv coverage before earliest mismatch: none; "
                        "disk cache cannot help those early-divergence requests yet"
                    )

            print(f"latest {min(last, len(rows))} kv files:")
            for r in sorted(rows, key=lambda x: x["mtime"], reverse=True)[:last]:
                print(
                    f"  tokens={fmt_tokens(r['tokens']):>6s} "
                    f"reason={r['reason_name']:10s} "
                    f"hits={r['hits']:3d} "
                    f"ctx={fmt_tokens(r['ctx_size']):>6s} "
                    f"text={fmt_tokens(r['text_bytes']):>6s} "
                    f"size={r['size'] / (1024 * 1024):7.1f}MiB "
                    f"ext={r['ext']}"
                )

    mtp = parse_mtp_log(server_log)
    if server_log:
        print(f"\nmtp log: {server_log}")
        print(
            "mtp: "
            f"attempts={mtp['attempts']} "
            f"drafted={mtp['drafted_tokens']} "
            f"committed={mtp['committed_tokens']} "
            f"acceptance={mtp['acceptance_rate'] * 100:.1f}% "
            f"full={mtp['full_accepts']} "
            f"partial={mtp['partial_accepts']} "
            f"first_misses={mtp['first_misses']} "
            f"fallbacks={mtp['verifier_fallbacks']}"
        )
        if mtp["attempts"]:
            print(
                "mtp timing: "
                f"avg_total={mtp['avg_total_ms']:.2f}ms "
                f"draft={mtp['avg_draft_ms']:.2f}ms "
                f"verify={mtp['avg_verify_ms']:.2f}ms "
                f"snapshot={mtp['avg_snapshot_ms']:.2f}ms "
                f"replay={mtp['avg_replay_ms']:.2f}ms "
                f"prefix={mtp['avg_prefix_ms']:.2f}ms"
            )
            modes = " ".join(f"{k}={v}" for k, v in mtp["modes"].items())
            if modes:
                print(f"mtp modes: {modes}")


def config_value(config, key, env_name=None, default=None, allow_empty=False):
    if env_name:
        if env_name in os.environ:
            val = os.environ.get(env_name)
            if allow_empty or val not in (None, ""):
                return val
    if allow_empty and key in config:
        return config.get(key, "")
    else:
        val = config.get(key)
        if val not in (None, ""):
            return val
    return default


def collect_metrics(requests, kv_dir=None, compare_intervals=None,
                    boundary_align=2048, early_threshold=12000,
                    config=None, server_log=None):
    config = config or {}
    completed = [r for r in requests if "elapsed_sec" in r]
    elapsed = [r["elapsed_sec"] for r in completed]
    total_gen = sum(r.get("generated_tokens", 0) for r in completed)
    total_elapsed = sum(elapsed)

    by_source = defaultdict(list)
    for r in completed:
        by_source[r.get("cache_source", "unknown")].append(r)

    source_metrics = {}
    for source, rows in sorted(by_source.items()):
        source_metrics[source] = {
            "count": len(rows),
            "avg_elapsed_sec": mean([r["elapsed_sec"] for r in rows]),
            "avg_prompt_tokens": mean([r.get("prompt_tokens", 0) for r in rows]),
            "avg_cached_tokens": mean([r.get("cached_tokens", 0) for r in rows]),
            "avg_disk_cached_tokens": mean([r.get("disk_cached_tokens", 0) for r in rows]),
        }

    protocol_metrics = {}
    by_protocol = defaultdict(list)
    for r in completed:
        by_protocol[r.get("protocol", "unknown")].append(r)
    for protocol, rows in sorted(by_protocol.items()):
        by_proto_source = Counter(r.get("cache_source", "unknown") for r in rows)
        none = by_proto_source.get("none", 0)
        protocol_metrics[protocol] = {
            "count": len(rows),
            "avg_elapsed_sec": mean([r["elapsed_sec"] for r in rows]),
            "p90_elapsed_sec": percentile([r["elapsed_sec"] for r in rows], 90),
            "avg_prompt_tokens": mean([r.get("prompt_tokens", 0) for r in rows]),
            "avg_cached_tokens": mean([r.get("cached_tokens", 0) for r in rows]),
            "none_rate": none / len(rows) if rows else 0.0,
            "disk_text_count": by_proto_source.get("disk-text", 0),
            "cache_sources": dict(by_proto_source),
        }

    mismatches = [r["first_mismatch_token"] for r in requests if "first_mismatch_token" in r]
    interval_metrics = interval_candidate_metrics(requests, compare_intervals, boundary_align)

    rows = parse_kv_dir(kv_dir) if kv_dir else []
    by_reason = Counter(r["reason_name"] for r in rows)
    by_tokens = Counter(r["tokens"] for r in rows)
    continued_frontiers = sorted(
        t for t, _count in by_tokens.items()
        if any(r["tokens"] == t and r["reason_name"] == "continued" for r in rows)
    )

    none_count = source_metrics.get("none", {}).get("count", 0)
    disk_text_count = source_metrics.get("disk-text", {}).get("count", 0)
    mtp = parse_mtp_log(server_log or config_value(config, "server_log"))
    return {
        "config": {
            "live_pid": config_value(config, "live_pid"),
            "started_at": config_value(config, "started_at"),
            "cwd": config_value(config, "cwd"),
            "command_line": config_value(config, "command_line"),
            "profile": config_value(config, "profile", "DS4_PROFILE", "agent"),
            "model": config_value(config, "model", "DS4_MODEL"),
            "ctx": config_value(config, "ctx", "DS4_CTX"),
            "threads": config_value(config, "threads", "DS4_THREADS"),
            "host": config_value(config, "host", "DS4_HOST"),
            "port": config_value(config, "port", "DS4_PORT"),
            "prefill_chunk": config_value(config, "prefill_chunk", "DS4_PREFILL_CHUNK"),
            "continued_interval": config_value(config, "continued_interval", "DS4_CONTINUED_INTERVAL"),
            "boundary_align": config_value(config, "boundary_align", "DS4_BOUNDARY_ALIGN"),
            "boundary_trim": config_value(config, "boundary_trim", "DS4_BOUNDARY_TRIM"),
            "cold_max": config_value(config, "cold_max", "DS4_COLD_MAX"),
            "cache_min": config_value(config, "cache_min", "DS4_CACHE_MIN"),
            "kv_dir": config_value(config, "kv_dir", "DS4_KV_DIR", kv_dir),
            "kv_space_mb": config_value(config, "kv_space_mb", "DS4_KV_SPACE"),
            "tool_memory_max_ids": config_value(config, "tool_memory_max_ids", "DS4_TOOL_MEMORY_MAX"),
            "mtp_path": config_value(config, "mtp_path", "DS4_MTP_PATH", allow_empty=True),
            "mtp_draft": config_value(config, "mtp_draft", "DS4_MTP_DRAFT"),
            "mtp_margin": config_value(config, "mtp_margin", "DS4_MTP_MARGIN"),
            "trace": config_value(config, "trace", "DS4_TRACE"),
            "server_log": server_log or config_value(config, "server_log", "DS4_SERVER_LOG"),
            "mtp_metrics": config_value(config, "mtp_metrics", "DS4_MTP_METRICS"),
            "config_snapshot": config_value(config, "config_snapshot", "DS4_CONFIG_SNAPSHOT"),
        },
        "requests": len(requests),
        "completed": len(completed),
        "elapsed": {
            "avg_sec": mean(elapsed),
            "p50_sec": percentile(elapsed, 50),
            "p90_sec": percentile(elapsed, 90),
            "max_sec": max(elapsed) if elapsed else 0.0,
        },
        "generated_tokens": total_gen,
        "generated_tokens_per_sec": total_gen / total_elapsed if total_elapsed else 0.0,
        "cache_sources": source_metrics,
        "protocols": protocol_metrics,
        "none_rate": none_count / len(completed) if completed else 0.0,
        "disk_text_count": disk_text_count,
        "miss_reasons": dict(Counter(
            r.get("memory_miss_reason", "") for r in requests
            if r.get("memory_miss_reason")
        )),
        "first_mismatch": {
            "count": len(mismatches),
            "avg": mean(mismatches),
            "min": min(mismatches) if mismatches else None,
            "max": max(mismatches) if mismatches else None,
            "early_threshold": early_threshold,
            "early_count": len([m for m in mismatches if m <= early_threshold]),
        },
        "continued_interval_candidates": interval_metrics,
        "kv": {
            "dir": kv_dir,
            "files": len(rows),
            "reasons": dict(by_reason),
            "token_frontiers": dict(sorted(by_tokens.items())),
            "continued_frontiers": continued_frontiers,
            "total_bytes": sum(r["size"] for r in rows),
        },
        "mtp": mtp,
    }


def run_gates(requests, kv_dir, min_requests, require_continued_frontier,
              require_disk_text, max_none_rate):
    failed = False
    completed = [r for r in requests if "elapsed_sec" in r]
    rows = parse_kv_dir(kv_dir) if kv_dir else []

    print("\ngates:")
    if len(completed) >= min_requests:
        print(f"  ok completed_requests={len(completed)} >= {min_requests}")
    else:
        print(f"  fail completed_requests={len(completed)} < {min_requests}")
        failed = True

    if require_continued_frontier:
        continued_tokens = {r["tokens"] for r in rows if r["reason_name"] == "continued"}
        matched = sorted(t for t in require_continued_frontier if t in continued_tokens)
        expected = ",".join(str(t) for t in require_continued_frontier)
        if matched:
            print(f"  ok continued_frontier matched={','.join(str(t) for t in matched)} expected_any={expected}")
        else:
            print(f"  fail continued_frontier missing expected_any={expected}")
            failed = True

    if require_disk_text:
        disk_text = [r for r in completed if r.get("cache_source") == "disk-text"]
        if disk_text:
            print(f"  ok disk_text_requests={len(disk_text)}")
        else:
            print("  fail disk_text_requests=0")
            failed = True

    if max_none_rate is not None and completed:
        none_count = len([r for r in completed if r.get("cache_source") == "none"])
        none_rate = none_count / len(completed)
        if none_rate <= max_none_rate:
            print(f"  ok none_rate={none_rate:.2f} <= {max_none_rate:.2f}")
        else:
            print(f"  fail none_rate={none_rate:.2f} > {max_none_rate:.2f}")
            failed = True

    return 1 if failed else 0


def main():
    ap = argparse.ArgumentParser(description="Summarize ds4-server trace cache behavior.")
    ap.add_argument("trace", nargs="?", default="/tmp/ds4-trace.jsonl")
    ap.add_argument("--slow-threshold", type=float, default=60.0)
    ap.add_argument("--early-threshold", type=int, default=12000)
    ap.add_argument("--last", type=int, default=12)
    ap.add_argument("--kv-dir", default=os.environ.get("DS4_KV_DIR", os.path.expanduser("~/.ds4/server-kv")))
    ap.add_argument("--compare-interval", type=int, action="append",
                    default=[2048, 4096, 8192, 10000, 16384])
    ap.add_argument("--boundary-align", type=int, default=2048)
    ap.add_argument("--gate", action="store_true",
                    help="print gate results and exit nonzero when any requested gate fails")
    ap.add_argument("--min-completed-requests", type=int, default=1)
    ap.add_argument("--require-continued-frontier", type=int, action="append", default=[])
    ap.add_argument("--require-disk-text", action="store_true")
    ap.add_argument("--max-none-rate", type=float)
    ap.add_argument("--json", action="store_true",
                    help="emit machine-readable metrics instead of the text report")
    ap.add_argument("--config",
                    help="start-server config sidecar; default is TRACE.config")
    ap.add_argument("--live-config", action="store_true",
                    help="fill missing config fields from the running ds4-server command line")
    ap.add_argument("--server-log",
                    help="server stderr/stdout log with DS4_MTP_METRICS=1 timing lines")
    args = ap.parse_args()
    requests = parse_trace(args.trace)
    config_path = args.config if args.config is not None else f"{args.trace}.config"
    config = parse_config(config_path)
    if args.live_config:
        config = merge_missing_config(config, parse_live_config())
    if args.json:
        metrics = collect_metrics(requests, args.kv_dir, args.compare_interval,
                                  args.boundary_align, args.early_threshold,
                                  config, args.server_log)
        print(json.dumps(metrics, indent=2, sort_keys=True))
        return
    summarize(requests, args.slow_threshold, args.early_threshold,
              args.last, args.kv_dir, args.compare_interval, args.boundary_align,
              args.server_log or config_value(config, "server_log"))
    if args.gate:
        raise SystemExit(run_gates(requests, args.kv_dir,
                                   args.min_completed_requests,
                                   args.require_continued_frontier,
                                   args.require_disk_text,
                                   args.max_none_rate))


if __name__ == "__main__":
    main()
