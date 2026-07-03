#!/usr/bin/env python3
import argparse
import json
import os


def load_case(spec):
    if "=" in spec:
        label, path = spec.split("=", 1)
    else:
        path = spec
        label = os.path.splitext(os.path.basename(path))[0]
    with open(path, "r", encoding="utf-8") as fp:
        data = json.load(fp)
    return label, data


def fmt_num(v, digits=1):
    if v is None:
        return "-"
    return f"{float(v):.{digits}f}"


def fmt_rate(v):
    return f"{float(v) * 100:.0f}%"


def fmt_frontiers(xs):
    if not xs:
        return "-"
    head = xs[:4]
    suffix = "" if len(xs) <= 4 else f"+{len(xs) - 4}"
    return ",".join(str(x) for x in head) + suffix


def short_protocol(name):
    return {
        "anthropic": "anth",
        "responses": "resp",
        "completion": "comp",
        "chat": "chat",
        "-": "-",
    }.get(name, name[:4])


def kv_reason(data, name):
    return int(data.get("kv", {}).get("reasons", {}).get(name, 0))


def cfg(data, key):
    val = data.get("config", {}).get(key)
    return "-" if val in (None, "") else str(val)


def env_cfg(data, key):
    val = data.get("config", {}).get(key)
    return None if val in (None, "") else str(val)


def worst_protocol_none(data):
    protocols = data.get("protocols", {})
    if not protocols:
        return data.get("none_rate", 1.0), "-"
    name, row = max(
        protocols.items(),
        key=lambda item: (item[1].get("none_rate", 0.0), item[1].get("p90_elapsed_sec", 0.0)),
    )
    return row.get("none_rate", 0.0), name


def worst_protocol_p90(data):
    protocols = data.get("protocols", {})
    if not protocols:
        return data.get("elapsed", {}).get("p90_sec", 0.0), "-"
    name, row = max(
        protocols.items(),
        key=lambda item: (item[1].get("p90_elapsed_sec", 0.0), item[1].get("none_rate", 0.0)),
    )
    return row.get("p90_elapsed_sec", 0.0), name


def selected_interval_metrics(data):
    def to_int(v):
        try:
            return int(v)
        except (TypeError, ValueError):
            return None

    interval = to_int(data.get("config", {}).get("continued_interval"))
    align = to_int(data.get("config", {}).get("boundary_align")) or 0
    if not interval or interval <= 0:
        return {}
    rows = data.get("continued_interval_candidates", [])
    for row in rows:
        if row.get("interval") == interval:
            return row
    step = ((interval + align - 1) // align) * align if align > 0 else interval
    for row in rows:
        if row.get("aligned_step") == step:
            return row
    return {}


def latency_bucket(v, quantum=0.5):
    try:
        value = float(v)
    except (TypeError, ValueError):
        return 0
    if value <= 0:
        return 0
    return int(value / quantum)


def score(data):
    elapsed = data.get("elapsed", {})
    completed = data.get("completed", 0)
    none_rate = data.get("none_rate", 1.0)
    proto_none, _proto_none_name = worst_protocol_none(data)
    proto_p90, _proto_p90_name = worst_protocol_p90(data)
    disk_text = data.get("disk_text_count", 0)
    mtp = data.get("mtp", {})
    mtp_accept = mtp.get("acceptance_rate", 0.0)
    p90 = elapsed.get("p90_sec", 0.0)
    avg = elapsed.get("avg_sec", 0.0)
    interval = selected_interval_metrics(data)
    avg_checkpoints = interval.get("avg_checkpoints_per_request", 0.0)
    avg_write = interval.get("avg_checkpoint_token_positions_per_request", 0.0)
    # Lower is better. The worst protocol matters because agent traffic mixes
    # OpenAI chat, Responses, and Anthropic-style clients. Latency is bucketed
    # so noise-level differences do not beat lower checkpoint write volume.
    return (
        1 if completed <= 0 else 0,
        proto_none,
        none_rate,
        -disk_text,
        -mtp_accept,
        latency_bucket(proto_p90),
        latency_bucket(p90),
        latency_bucket(avg),
        avg_checkpoints,
        avg_write,
        proto_p90,
        p90,
        avg,
    )


def int_cfg(data, key):
    val = data.get("config", {}).get(key)
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


def aligned_step(interval, align):
    if not interval or interval <= 0:
        return None
    if align and align > 0:
        return ((interval + align - 1) // align) * align
    return interval


def case_issues(data, args):
    issues = []
    completed = data.get("completed", 0)
    if completed < args.min_completed:
        issues.append(f"completed {completed} < {args.min_completed}")

    if args.max_none_rate is not None and completed > 0:
        none_rate = data.get("none_rate", 0.0)
        if none_rate > args.max_none_rate:
            issues.append(f"none_rate {none_rate:.2f} > {args.max_none_rate:.2f}")

    protocols = data.get("protocols", {})
    for protocol in args.require_protocol:
        if protocols.get(protocol, {}).get("count", 0) <= 0:
            issues.append(f"protocol {protocol} missing")

    if args.max_protocol_none_rate is not None and protocols:
        rate, name = worst_protocol_none(data)
        if rate > args.max_protocol_none_rate:
            issues.append(
                f"worst_protocol_none_rate {name}={rate:.2f} > {args.max_protocol_none_rate:.2f}"
            )

    if args.require_disk_text and data.get("disk_text_count", 0) <= 0:
        issues.append("disk_text_count is 0")

    mtp_enabled = bool(env_cfg(data, "mtp_path"))
    if args.require_mtp_attempts or (args.require_mtp_attempts_when_enabled and mtp_enabled):
        attempts = data.get("mtp", {}).get("attempts", 0)
        if attempts <= 0:
            issues.append("mtp attempts are 0")

    if args.min_mtp_acceptance is not None:
        rate = data.get("mtp", {}).get("acceptance_rate", 0.0)
        if rate < args.min_mtp_acceptance:
            issues.append(f"mtp acceptance {rate:.2f} < {args.min_mtp_acceptance:.2f}")

    if args.require_continued_frontier:
        expected = set(args.require_continued_frontier)
        frontiers = set(data.get("kv", {}).get("continued_frontiers", []))
        if not (expected & frontiers):
            issues.append(
                "continued frontier missing expected_any="
                + ",".join(str(x) for x in sorted(expected))
            )

    if args.require_auto_frontier:
        interval = int_cfg(data, "continued_interval")
        align = int_cfg(data, "boundary_align") or 0
        step = aligned_step(interval, align)
        frontiers = set(data.get("kv", {}).get("continued_frontiers", []))
        expected = {step, step * 2} if step else set()
        if expected and not (expected & frontiers):
            issues.append(
                "continued frontier missing auto expected_any="
                + ",".join(str(x) for x in sorted(expected))
            )

    return issues


def shell_quote(s):
    s = str(s)
    if not s:
        return "''"
    safe = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_./:-"
    if all(c in safe for c in s):
        return s
    return "'" + s.replace("'", "'\"'\"'") + "'"


def recommendation(label, data):
    config = data.get("config", {})
    mtp = data.get("mtp", {})
    env = {}
    mapping = {
        "DS4_CONTINUED_INTERVAL": "continued_interval",
        "DS4_PREFILL_CHUNK": "prefill_chunk",
        "DS4_BOUNDARY_ALIGN": "boundary_align",
        "DS4_COLD_MAX": "cold_max",
        "DS4_CACHE_MIN": "cache_min",
    }
    for env_name, key in mapping.items():
        val = env_cfg(data, key)
        if val:
            env[env_name] = val

    mtp_path = env_cfg(data, "mtp_path")
    mtp_disabled = "mtp_path" in config and config.get("mtp_path", None) == ""
    if mtp_disabled:
        env["DS4_MTP_PATH"] = ""
    mtp_note = "mtp=disabled" if mtp_disabled else "mtp=not_measured"
    if mtp.get("attempts", 0) > 0:
        accept = mtp.get("acceptance_rate", 0.0)
        mtp_note = f"mtp_acceptance={accept * 100:.1f}% attempts={mtp.get('attempts', 0)}"
        if mtp_path and accept > 0.0:
            env["DS4_MTP_PATH"] = mtp_path
            for env_name, key in {
                "DS4_MTP_DRAFT": "mtp_draft",
                "DS4_MTP_MARGIN": "mtp_margin",
            }.items():
                val = env_cfg(data, key)
                if val:
                    env[env_name] = val
        elif mtp_path:
            env["DS4_MTP_PATH"] = ""
            mtp_note += " disable_mtp_suggested"
    elif not mtp_disabled and env_cfg(data, "mtp_metrics") in ("1", "true", "yes"):
        mtp_note = "mtp_metrics_enabled_but_no_attempts"

    env_text = " ".join(f"{k}={shell_quote(v)}" for k, v in sorted(env.items()))
    command = f"{env_text} ./start-server.sh" if env_text else "./start-server.sh"
    return {
        "label": label,
        "env_text": env_text,
        "command": command,
        "mtp_note": mtp_note,
        "none_rate": data.get("none_rate", 0.0),
        "protocol_none": worst_protocol_none(data),
        "protocol_p90": worst_protocol_p90(data),
        "interval": selected_interval_metrics(data),
        "disk_text_count": data.get("disk_text_count", 0),
        "p90": data.get("elapsed", {}).get("p90_sec", 0.0),
    }


def main():
    ap = argparse.ArgumentParser(
        description="Compare JSON metrics emitted by trace-cache-summary.py --json."
    )
    ap.add_argument("result", nargs="+",
                    help="JSON result path, optionally label=path")
    ap.add_argument("--baseline", action="append", default=[],
                    help="baseline JSON to display but exclude from scoring, gates, and recommendation; optionally label=path")
    ap.add_argument("--min-completed", type=int, default=0)
    ap.add_argument("--max-none-rate", type=float)
    ap.add_argument("--require-protocol", action="append", default=[],
                    choices=["chat", "responses", "anthropic", "completion"],
                    help="require at least one completed request for this inferred protocol; repeatable")
    ap.add_argument("--max-protocol-none-rate", type=float,
                    help="fail when any protocol's none_rate is above this threshold")
    ap.add_argument("--require-disk-text", action="store_true")
    ap.add_argument("--require-mtp-attempts", action="store_true")
    ap.add_argument("--require-mtp-attempts-when-enabled", action="store_true",
                    help="require MTP attempts only for results whose config has mtp_path")
    ap.add_argument("--min-mtp-acceptance", type=float)
    ap.add_argument("--require-continued-frontier", type=int, action="append", default=[])
    ap.add_argument("--require-auto-frontier", action="store_true",
                    help="require one of interval/aligned frontiers implied by each result config")
    ap.add_argument("--strict", action="store_true",
                    help="exit nonzero when any requested gate fails")
    args = ap.parse_args()

    baselines = [load_case(spec) for spec in args.baseline]
    cases = [load_case(spec) for spec in args.result]
    cases.sort(key=lambda item: score(item[1]))
    display_cases = baselines + cases
    all_issues = {}
    label_width = min(40, max(20, *(len(label) for label, _ in display_cases)))

    print(
        f"{'label':{label_width}s} {'int':>6s} {'chunk':>6s} {'align':>6s} "
        f"{'cold':>6s} {'min':>5s} "
        f"{'done':>5s} {'avg':>8s} {'p90':>8s} "
        f"{'none':>6s} {'pnone':>6s} {'pp90':>9s} {'ckpt':>5s} {'write':>7s} "
        f"{'disk':>5s} {'mtp':>6s} {'mtp_n':>6s} "
        f"{'mm_min':>7s} {'kv_cont':>7s} {'kv_cold':>7s} {'kv_evict':>8s} "
        f"{'kv_files':>8s} frontiers"
    )
    baseline_labels = {label for label, _data in baselines}
    for label, data in display_cases:
        elapsed = data.get("elapsed", {})
        first = data.get("first_mismatch", {})
        kv = data.get("kv", {})
        mtp = data.get("mtp", {})
        proto_none_rate, proto_none_name = worst_protocol_none(data)
        proto_p90, proto_p90_name = worst_protocol_p90(data)
        interval = selected_interval_metrics(data)
        shown_label = label if len(label) <= label_width else label[:label_width - 1] + "~"
        print(
            f"{shown_label:{label_width}s} "
            f"{cfg(data, 'continued_interval')[:6]:>6s} "
            f"{cfg(data, 'prefill_chunk')[:6]:>6s} "
            f"{cfg(data, 'boundary_align')[:6]:>6s} "
            f"{cfg(data, 'cold_max')[:6]:>6s} "
            f"{cfg(data, 'cache_min')[:5]:>5s} "
            f"{data.get('completed', 0):5d} "
            f"{fmt_num(elapsed.get('avg_sec')):>8s} "
            f"{fmt_num(elapsed.get('p90_sec')):>8s} "
            f"{fmt_rate(data.get('none_rate', 0.0)):>6s} "
            f"{fmt_rate(proto_none_rate):>6s} "
            f"{(short_protocol(proto_p90_name) + ':' + fmt_num(proto_p90))[:9]:>9s} "
            f"{fmt_num(interval.get('avg_checkpoints_per_request'), 1):>5s} "
            f"{fmt_num(interval.get('avg_checkpoint_token_positions_per_request'), 0):>7s} "
            f"{data.get('disk_text_count', 0):5d} "
            f"{fmt_rate(mtp.get('acceptance_rate', 0.0)):>6s} "
            f"{mtp.get('attempts', 0):6d} "
            f"{str(first.get('min') or '-'):>7s} "
            f"{kv_reason(data, 'continued'):7d} "
            f"{kv_reason(data, 'cold'):7d} "
            f"{kv_reason(data, 'evict'):8d} "
            f"{kv.get('files', 0):8d} "
            f"{fmt_frontiers(kv.get('continued_frontiers', []))}"
        )
        issues = [] if label in baseline_labels else case_issues(data, args)
        if issues:
            all_issues[label] = issues

    best_label, best = cases[0]
    print()
    print(f"best_by_score={best_label}")
    rec = recommendation(best_label, best)
    warnings = []
    if best.get("completed", 0) <= 0:
        warnings.append("no_completed_workload_do_not_promote")
    if len(cases) < 2:
        warnings.append("single_measured_result_no_alternative")
    if warnings:
        for warning in warnings:
            print(f"recommendation_warning={warning}")
        if rec["env_text"]:
            print(f"observed_start_env={rec['env_text']}")
        print(f"observed_start_command={rec['command']}")
    else:
        if rec["env_text"]:
            print(f"recommended_start_env={rec['env_text']}")
        print(f"recommended_start_command={rec['command']}")
    print(
        "recommendation_basis="
        f"none={fmt_rate(rec['none_rate'])} "
        f"protocol_none={rec['protocol_none'][1]}:{fmt_rate(rec['protocol_none'][0])} "
        f"protocol_p90={rec['protocol_p90'][1]}:{fmt_num(rec['protocol_p90'][0])} "
        f"avg_ckpt={fmt_num(rec['interval'].get('avg_checkpoints_per_request'), 1)} "
        f"avg_write={fmt_num(rec['interval'].get('avg_checkpoint_token_positions_per_request'), 0)} "
        f"disk={rec['disk_text_count']} "
        f"p90={fmt_num(rec['p90'])} "
        f"{rec['mtp_note']}"
    )
    candidates = best.get("continued_interval_candidates", [])
    if candidates:
        top = max(
            candidates,
            key=lambda c: (
                c.get("coverage", 0.0),
                c.get("avg_prefix_tokens", 0.0),
                -c.get("avg_checkpoints_per_request", 0.0),
                -c.get("avg_checkpoint_token_positions_per_request", 0.0),
            ),
        )
        print(
            "best_interval_hint="
            f"{top.get('interval')} aligned={top.get('aligned_step')} "
            f"coverage={fmt_rate(top.get('coverage', 0.0))} "
            f"avg_prefix={fmt_num(top.get('avg_prefix_tokens', 0.0), 0)} "
            f"avg_ckpt={fmt_num(top.get('avg_checkpoints_per_request'), 1)} "
            f"avg_write={fmt_num(top.get('avg_checkpoint_token_positions_per_request'), 0)}"
        )

    if all_issues:
        print()
        print("gates:")
        for label, issues in all_issues.items():
            print(f"  fail {label}: {'; '.join(issues)}")
    elif (
        args.min_completed or args.max_none_rate is not None or args.require_disk_text or
        args.require_mtp_attempts or args.require_mtp_attempts_when_enabled or
        args.min_mtp_acceptance is not None or
        args.require_continued_frontier or args.require_auto_frontier or
        args.require_protocol or args.max_protocol_none_rate is not None
    ):
        print()
        print("gates: ok")

    if args.strict and all_issues:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
