#!/usr/bin/env python3
import argparse
import json
import subprocess
import time
import urllib.error
import urllib.request


RAW_MARKER = "--- raw request json ---"


def extract_raw_requests(trace_path):
    requests = []
    try:
        fp = open(trace_path, "r", encoding="utf-8", errors="replace")
    except OSError:
        return requests
    with fp:
        lines = iter(fp)
        for line in lines:
            if line.rstrip("\n") != RAW_MARKER:
                continue
            buf = []
            for raw in lines:
                if raw.startswith("--- ") and buf:
                    break
                buf.append(raw)
                text = "".join(buf).strip()
                if not text:
                    continue
                try:
                    payload = json.loads(text)
                except json.JSONDecodeError:
                    continue
                requests.append(payload)
                break
    return requests


def infer_path(payload):
    if "input" in payload or "instructions" in payload:
        return "/v1/responses"
    if "prompt" in payload and "messages" not in payload:
        return "/v1/completions"
    tools = payload.get("tools")
    if isinstance(tools, list):
        for tool in tools:
            if isinstance(tool, dict) and "input_schema" in tool:
                return "/v1/messages"
    if "anthropic_version" in payload:
        return "/v1/messages"
    return "/v1/chat/completions"


def protocol_name(path):
    return {
        "/v1/chat/completions": "chat",
        "/v1/responses": "responses",
        "/v1/messages": "anthropic",
        "/v1/completions": "completion",
    }.get(path, path)


def normalize_payload(payload, path, max_tokens, temperature, stream):
    out = json.loads(json.dumps(payload))
    if not stream:
        out["stream"] = False
    if temperature is not None:
        out["temperature"] = temperature
    if max_tokens is not None:
        if path == "/v1/responses":
            out["max_output_tokens"] = max_tokens
        else:
            out["max_tokens"] = max_tokens
    return out


def post_json(base_url, path, payload, timeout):
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    req = urllib.request.Request(
        base_url.rstrip("/") + path,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    t0 = time.monotonic()
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read()
        status = resp.status
    return status, time.monotonic() - t0, len(body), len(data)


def check_profile():
    try:
        proc = subprocess.run(
            ["./agent-cache-check.sh", "--profile-only", "--strict"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
    except OSError as e:
        return 1, f"profile check failed to start: {e}\n"
    return proc.returncode, proc.stdout


def main():
    ap = argparse.ArgumentParser(
        description="Replay raw request JSON blocks captured in a ds4-server trace."
    )
    ap.add_argument("trace", nargs="?", default="/tmp/ds4-trace.jsonl")
    ap.add_argument("--run", action="store_true",
                    help="actually send requests; default only prints the plan")
    ap.add_argument("--base-url", default="http://127.0.0.1:8077")
    ap.add_argument("--path", choices=[
        "/v1/chat/completions", "/v1/responses", "/v1/messages", "/v1/completions"
    ], help="force all requests to one endpoint instead of inferring from JSON")
    ap.add_argument("--max-requests", type=int)
    ap.add_argument("--protocol", action="append",
                    choices=["chat", "responses", "anthropic", "completion"],
                    help="protocol to replay; repeatable; default keeps all")
    ap.add_argument("--skip-first", type=int, default=0,
                    help="skip this many kept requests after protocol/body filtering")
    ap.add_argument("--sample-step", type=int, default=1,
                    help="keep every Nth request after filtering")
    ap.add_argument("--max-body-bytes", type=int,
                    help="skip normalized requests above this body size")
    ap.add_argument("--max-tokens", type=int, default=1,
                    help="override output tokens; use 1 for KV/prefill, 32+ for MTP decode")
    ap.add_argument("--temperature", type=float,
                    help="override request temperature, e.g. 0 for argmax/MTP measurements")
    ap.add_argument("--keep-stream", action="store_true",
                    help="preserve stream=true instead of forcing non-streaming requests")
    ap.add_argument("--timeout", type=float, default=900.0)
    ap.add_argument("--sleep", type=float, default=0.2)
    ap.add_argument("--skip-profile-check", action="store_true")
    args = ap.parse_args()

    if args.sample_step <= 0:
        ap.error("--sample-step must be >= 1")
    raw = extract_raw_requests(args.trace)
    allowed = set(args.protocol or [])
    scanned = len(raw)
    skipped_protocol = 0
    skipped_size = 0
    plan = []
    for payload in raw:
        path = args.path or infer_path(payload)
        protocol = protocol_name(path)
        if allowed and protocol not in allowed:
            skipped_protocol += 1
            continue
        norm = normalize_payload(
            payload, path, args.max_tokens, args.temperature, args.keep_stream
        )
        body_len = len(json.dumps(norm, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        if args.max_body_bytes is not None and body_len > args.max_body_bytes:
            skipped_size += 1
            continue
        plan.append((path, norm))
    if args.skip_first:
        plan = plan[args.skip_first:]
    if args.sample_step > 1:
        plan = plan[::args.sample_step]
    if args.max_requests is not None:
        plan = plan[:args.max_requests]

    print("agent kv trace replay")
    print(f"trace={args.trace}")
    print(f"base_url={args.base_url}")
    print(
        f"scanned={scanned} requests={len(plan)} run={int(args.run)} "
        f"max_tokens={args.max_tokens} temperature={args.temperature}"
    )
    if skipped_protocol or skipped_size:
        print(f"skipped_protocol={skipped_protocol} skipped_size={skipped_size}")
    for i, (path, payload) in enumerate(plan, 1):
        body_len = len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        print(f"  {i:02d} path={path:20s} body_bytes={body_len}")

    if not args.run:
        print("dry run only; add --run to send requests")
        return 0
    if not plan:
        print("no raw request JSON blocks found")
        return 1
    if not args.skip_profile_check:
        rc, out = check_profile()
        if rc != 0:
            print("profile preflight failed; refusing to replay")
            print(out.rstrip())
            return rc

    failures = 0
    for i, (path, payload) in enumerate(plan, 1):
        try:
            status, elapsed, body_len, resp_len = post_json(args.base_url, path, payload, args.timeout)
            print(
                f"done {i:02d} path={path:20s} status={status} "
                f"elapsed={elapsed:.1f}s body_bytes={body_len} response_bytes={resp_len}"
            )
        except urllib.error.HTTPError as e:
            failures += 1
            detail = e.read().decode("utf-8", "replace")[:500]
            print(f"fail {i:02d} path={path} http={e.code} {detail}")
        except Exception as e:
            failures += 1
            print(f"fail {i:02d} path={path} error={e}")
        if args.sleep > 0:
            time.sleep(args.sleep)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
