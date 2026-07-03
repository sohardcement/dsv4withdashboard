#!/usr/bin/env python3
import argparse
import json
import subprocess
import time
import urllib.error
import urllib.request


TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "path": {"type": "string"},
        "query": {"type": "string"},
        "limit": {"type": "integer"},
    },
    "required": ["path"],
}


def stable_block(repeats):
    lines = [
        "You are a local coding agent attached to the ds4 repository.",
        "Preserve tool-call syntax, keep responses concise, and prefer exact file references.",
        "The following stable project context intentionally stays byte-identical across requests.",
    ]
    for i in range(repeats):
        lines.append(
            f"stable-context-{i:04d}: ds4 agent workload cache marker; "
            "system prompt, skill list, tool schema, repository policy, and memory briefing remain fixed."
        )
    return "\n".join(lines)


def volatile_block(label):
    return "\n".join([
        f"volatile-session-label: {label}",
        f"volatile-clock-bucket: {label}-0001",
        "volatile-task: inspect the current workspace and answer with one short sentence.",
    ])


def openai_tools(n):
    return [
        {
            "type": "function",
            "function": {
                "name": f"agent_tool_{i}",
                "description": f"Representative coding-agent tool {i}.",
                "parameters": TOOL_SCHEMA,
            },
        }
        for i in range(n)
    ]


def anthropic_tools(n):
    return [
        {
            "name": f"agent_tool_{i}",
            "description": f"Representative coding-agent tool {i}.",
            "input_schema": TOOL_SCHEMA,
        }
        for i in range(n)
    ]


def requests_for(protocol, stable, tools, label, tool_choice, max_tokens):
    system = stable + "\n\n" + volatile_block(label)
    user = (
        "Return exactly one short sentence naming the active cache test label: "
        f"{label}."
    )
    if protocol == "chat":
        return "/v1/chat/completions", {
            "model": "deepseek-v4-flash",
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "tools": openai_tools(tools),
            "tool_choice": tool_choice,
            "max_tokens": max_tokens,
            "temperature": 0,
            "stream": False,
            "thinking": False,
        }
    if protocol == "responses":
        return "/v1/responses", {
            "model": "deepseek-v4-flash",
            "instructions": system,
            "input": user,
            "tools": openai_tools(tools),
            "tool_choice": tool_choice,
            "max_output_tokens": max_tokens,
            "temperature": 0,
            "stream": False,
            "reasoning": {"effort": "none"},
        }
    if protocol == "anthropic":
        return "/v1/messages", {
            "model": "deepseek-v4-flash",
            "system": system,
            "messages": [{"role": "user", "content": user}],
            "tools": anthropic_tools(tools),
            "tool_choice": {"type": tool_choice},
            "max_tokens": max_tokens,
            "temperature": 0,
            "stream": False,
            "thinking": {"type": "disabled"},
        }
    raise ValueError(protocol)


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
    return status, time.monotonic() - t0, len(data)


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
        description="Run a small mixed-agent workload to validate ds4 KV cache tuning."
    )
    ap.add_argument("--run", action="store_true",
                    help="actually send requests; default only prints the plan")
    ap.add_argument("--base-url", default="http://127.0.0.1:8077")
    ap.add_argument("--stable-repeats", type=int, default=360)
    ap.add_argument("--tools", type=int, default=16)
    ap.add_argument("--max-tokens", type=int, default=1,
                    help="output tokens per request; keep 1 for KV/prefill, use 32+ for MTP decode metrics")
    ap.add_argument("--tool-choice", choices=["auto", "none"], default="auto",
                    help="auto renders tool schemas into the prompt; none is a no-tool-prefix control")
    ap.add_argument("--timeout", type=float, default=900.0)
    ap.add_argument("--sleep", type=float, default=0.2)
    ap.add_argument("--skip-profile-check", action="store_true",
                    help="allow --run even when the live server does not match start-server.sh")
    ap.add_argument("--protocol", action="append",
                    choices=["chat", "responses", "anthropic"],
                    help="protocol to run; repeatable; default runs all three")
    ap.add_argument("--label", action="append",
                    help="volatile labels to replay; default warms A, switches to B, then returns to A")
    args = ap.parse_args()

    protocols = args.protocol or ["chat", "responses", "anthropic"]
    labels = args.label or ["A", "A", "B", "A"]
    stable = stable_block(args.stable_repeats)

    plan = []
    for protocol in protocols:
        for label in labels:
            path, payload = requests_for(protocol, stable, args.tools, label,
                                         args.tool_choice, args.max_tokens)
            body_len = len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
            plan.append((protocol, label, path, payload, body_len))

    print("agent kv workload")
    print(f"base_url={args.base_url}")
    print(
        f"stable_repeats={args.stable_repeats} tools={args.tools} "
        f"tool_choice={args.tool_choice} max_tokens={args.max_tokens}"
    )
    print(f"requests={len(plan)} run={int(args.run)}")
    for i, (protocol, label, path, _payload, body_len) in enumerate(plan, 1):
        print(f"  {i:02d} protocol={protocol:9s} label={label} path={path} body_bytes={body_len}")

    if not args.run:
        print("dry run only; add --run to send requests")
        return 0

    if not args.skip_profile_check:
        rc, out = check_profile()
        if rc != 0:
            print("profile preflight failed; refusing to send workload")
            print(out.rstrip())
            print("restart with DS4_TRACE_RESET=1 ./start-server.sh, or pass --skip-profile-check for a baseline run")
            return rc

    failures = 0
    for i, (protocol, label, path, payload, body_len) in enumerate(plan, 1):
        try:
            status, elapsed, resp_len = post_json(args.base_url, path, payload, args.timeout)
            print(
                f"done {i:02d} protocol={protocol:9s} label={label} "
                f"status={status} elapsed={elapsed:.1f}s body_bytes={body_len} response_bytes={resp_len}"
            )
        except urllib.error.HTTPError as e:
            failures += 1
            detail = e.read().decode("utf-8", "replace")[:500]
            print(f"fail {i:02d} protocol={protocol} label={label} http={e.code} {detail}")
        except Exception as e:
            failures += 1
            print(f"fail {i:02d} protocol={protocol} label={label} error={e}")
        if args.sleep > 0:
            time.sleep(args.sleep)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
