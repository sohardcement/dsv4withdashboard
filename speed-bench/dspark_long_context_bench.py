#!/usr/bin/env python3
"""Measure DSpark decode uplift at long-context frontiers through ds4-server."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import platform
import re
import signal
import shutil
import socket
import statistics
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODEL = Path(
    "/Users/shc/.lmstudio/models/huihui-ai/"
    "Huihui-DeepSeek-V4-Flash-0731-abliterated-GGUF/"
    "DeepSeek-V4-Flash-Q2-0731.gguf"
)
DEFAULT_SUPPORT = (
    REPO_ROOT / "gguf/DeepSeek-V4-Flash-0731-DSpark-abliterated-Q4K-support.gguf"
)
DEFAULT_SOURCE = REPO_ROOT / "speed-bench/promessi_sposi.txt"
TASK_SUFFIX = """

--- BENCHMARK TASK ---
Ignore the preceding document. Return only C99 source code. Implement a
self-contained fixed-capacity LRU cache for uint64_t keys and values, including
init, destroy, get, put, explicit allocation failure handling, eviction, and a
small main function with assertions. Do not abbreviate the implementation.
"""
CHAT_OVERHEAD_TOKENS = 12


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--support", type=Path, default=DEFAULT_SUPPORT)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--frontiers", default="30000,50000,75000,100000")
    parser.add_argument(
        "--workload",
        choices=("thinking-max-sampled", "thinking-max-greedy"),
        default="thinking-max-sampled",
    )
    parser.add_argument("--ctx", type=int, default=393216)
    parser.add_argument("--output-tokens", type=int, default=512)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--source-token-count", type=int, default=419509)
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument(
        "--modes",
        choices=("both", "baseline", "dspark"),
        default="both",
        help="run both sides of the comparison, or one side for tuning",
    )
    parser.add_argument(
        "--dspark-confidence",
        type=float,
        default=None,
        help="override the runtime confidence gate for tuning runs",
    )
    parser.add_argument(
        "--kv-dir",
        type=Path,
        help="reuse an external benchmark KV directory",
    )
    parser.add_argument(
        "--skip-cache-prepare",
        action="store_true",
        help="require the selected prompts to already exist in --kv-dir",
    )
    parser.add_argument("--keep-kv", action="store_true")
    return parser.parse_args()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def raw_token_count(model: Path, prompt: str, artifact_dir: Path) -> int:
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", suffix=".txt", prefix="calibrate-",
        dir=artifact_dir
    ) as prompt_file:
        prompt_file.write(prompt)
        prompt_file.flush()
        proc = subprocess.Popen(
            [
                str(REPO_ROOT / "ds4"), "--dump-tokens", "-m", str(model),
                "--prompt-file", prompt_file.name,
            ],
            cwd=REPO_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        assert proc.stdout is not None
        first_line = proc.stdout.readline()
        proc.terminate()
        try:
            proc.wait(timeout=10.0)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5.0)
    stripped = first_line.strip()
    if not stripped.startswith(b"[") or not stripped.endswith(b"]"):
        raise RuntimeError("failed to read tokenizer output during calibration")
    if stripped == b"[]":
        return 0
    return stripped.count(b",") + 1


def calibrated_prompt(source: str, target: int, model: Path,
                      source_token_count: int,
                      artifact_dir: Path) -> tuple[str, int, int]:
    raw_target = max(1, target - CHAT_OVERHEAD_TOKENS)
    suffix_estimate = 96
    wanted_source_tokens = max(1, raw_target - suffix_estimate)
    char_count = round(len(source) * wanted_source_tokens / source_token_count)
    char_count = min(max(char_count, 1), len(source))
    raw_count = 0
    for _ in range(3):
        prompt = source[:char_count] + TASK_SUFFIX
        raw_count = raw_token_count(model, prompt, artifact_dir)
        if abs(raw_count - raw_target) <= 8:
            return prompt, char_count, raw_count
        char_count = round(char_count * raw_target / max(raw_count, 1))
        char_count = min(max(char_count, 1), len(source))
    prompt = source[:char_count] + TASK_SUFFIX
    raw_count = raw_token_count(model, prompt, artifact_dir)
    return prompt, char_count, raw_count


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def http_json(url: str, payload: dict[str, Any] | None = None,
              timeout: float = 30.0) -> dict[str, Any]:
    data = None
    headers: dict[str, str] = {}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read()
    parsed = json.loads(body)
    if not isinstance(parsed, dict):
        raise RuntimeError(f"unexpected JSON response from {url}")
    return parsed


def http_chat_stream(url: str, payload: dict[str, Any],
                     timeout: float) -> tuple[dict[str, Any], float | None]:
    request_payload = dict(payload)
    request_payload["stream"] = True
    request_payload["stream_options"] = {"include_usage": True}
    data = json.dumps(request_payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}
    )
    started = time.monotonic()
    first_token_seconds: float | None = None
    content_parts: list[str] = []
    reasoning_parts: list[str] = []
    usage: dict[str, Any] = {}
    finish_reason: str | None = None
    response_id: str | None = None
    created: int | None = None
    model: str | None = None
    with urllib.request.urlopen(request, timeout=timeout) as response:
        for raw_line in response:
            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line.startswith("data: "):
                continue
            body = line[6:]
            if body == "[DONE]":
                break
            event = json.loads(body)
            response_id = event.get("id") or response_id
            created = event.get("created") or created
            model = event.get("model") or model
            if isinstance(event.get("usage"), dict):
                usage = event["usage"]
            choices = event.get("choices") or []
            if not choices:
                continue
            choice = choices[0]
            delta = choice.get("delta") or {}
            content = delta.get("content") or ""
            reasoning = delta.get("reasoning_content") or ""
            if content or reasoning:
                if first_token_seconds is None:
                    first_token_seconds = time.monotonic() - started
                if content:
                    content_parts.append(content)
                if reasoning:
                    reasoning_parts.append(reasoning)
            if choice.get("finish_reason") is not None:
                finish_reason = choice["finish_reason"]
    return {
        "id": response_id,
        "object": "chat.completion",
        "created": created,
        "model": model,
        "choices": [{
            "index": 0,
            "message": {
                "role": "assistant",
                "content": "".join(content_parts),
                "reasoning_content": "".join(reasoning_parts),
            },
            "finish_reason": finish_reason,
        }],
        "usage": usage,
    }, first_token_seconds


def wait_ready(port: int, proc: subprocess.Popen[bytes], timeout: float = 180.0) -> None:
    deadline = time.monotonic() + timeout
    url = f"http://127.0.0.1:{port}/v1/models"
    last_error = "server did not answer"
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"server exited early with status {proc.returncode}")
        try:
            http_json(url, timeout=1.0)
            return
        except (OSError, ValueError, urllib.error.URLError) as error:
            last_error = str(error)
            time.sleep(0.25)
    raise RuntimeError(f"server readiness timed out: {last_error}")


def stop_server(proc: subprocess.Popen[bytes]) -> int:
    if proc.poll() is None:
        proc.send_signal(signal.SIGINT)
    try:
        return proc.wait(timeout=45.0)
    except subprocess.TimeoutExpired:
        proc.terminate()
    try:
        return proc.wait(timeout=15.0)
    except subprocess.TimeoutExpired:
        proc.kill()
        return proc.wait(timeout=15.0)


def memory_snapshot() -> dict[str, Any]:
    snapshot: dict[str, Any] = {}
    pressure = command_output(["memory_pressure", "-Q"])
    swap = command_output(["sysctl", "-n", "vm.swapusage"])
    snapshot["memory_pressure"] = pressure
    snapshot["swapusage"] = swap
    if pressure:
        match = re.search(r"free percentage:\s*([0-9.]+)%", pressure)
        snapshot["free_percent"] = float(match.group(1)) if match else None
    if swap:
        match = re.search(r"used\s*=\s*([0-9.]+)M", swap)
        snapshot["swap_used_mb"] = float(match.group(1)) if match else None
    return snapshot


def start_server(mode: str, model: Path, support: Path, ctx: int, kv_dir: Path,
                 artifact_dir: Path, label: str,
                 dspark_confidence: float | None = None) -> tuple[
                     subprocess.Popen[bytes], int, Path, Any, dict[str, Any]
                 ]:
    port = find_free_port()
    log_path = artifact_dir / f"{label}.log"
    log_file = log_path.open("wb")
    env = os.environ.copy()
    env.update({
        "DS4_PROFILE": "agent",
        "DS4_HOST": "127.0.0.1",
        "DS4_PORT": str(port),
        "DS4_MODEL": str(model),
        "DS4_CTX": str(ctx),
        "DS4_KV_DIR": str(kv_dir),
        "DS4_KV_SPACE": "32768",
        "DS4_COLD_MAX": str(ctx - 1024),
        "DS4_TRACE": "",
        "DS4_CONFIG_SNAPSHOT": "",
        "DS4_TOKEN_HISTORY_FILE": str(artifact_dir / "token-usage.tsv"),
        "DS4_MTP_PATH": "",
        "DS4_DSPARK_STATS": "1" if mode == "dspark" else "0",
    })
    command = [str(REPO_ROOT / "start-server.sh")]
    if mode == "dspark":
        command.extend(["--mtp", str(support), "--dspark"])
        if dspark_confidence is not None:
            command.extend(["--dspark-confidence", str(dspark_confidence)])
    memory_before = memory_snapshot()
    proc = subprocess.Popen(
        command,
        cwd=REPO_ROOT,
        env=env,
        stdout=log_file,
        stderr=subprocess.STDOUT,
    )
    try:
        wait_ready(port, proc)
    except Exception:
        stop_server(proc)
        log_file.close()
        raise
    memory_after = memory_snapshot()
    free_percent = memory_after.get("free_percent")
    swap_before = memory_before.get("swap_used_mb")
    swap_after = memory_after.get("swap_used_mb")
    swap_growth = (
        swap_after - swap_before
        if isinstance(swap_before, float) and isinstance(swap_after, float)
        else None
    )
    memory = {
        "before": memory_before,
        "after": memory_after,
        "swap_growth_mb": swap_growth,
    }
    if ((isinstance(free_percent, float) and free_percent <= 5.0) or
            (isinstance(swap_growth, float) and swap_growth > 2048.0)):
        stop_server(proc)
        log_file.close()
        raise RuntimeError(
            f"Think Max memory gate failed: free={free_percent}% "
            f"swap_growth={swap_growth} MiB; see {log_path}"
        )
    return proc, port, log_path, log_file, memory


def parse_last(pattern: str, text: str) -> re.Match[str] | None:
    matches = list(re.finditer(pattern, text, re.MULTILINE))
    return matches[-1] if matches else None


def parse_log(log_path: Path) -> dict[str, Any]:
    text = log_path.read_text(encoding="utf-8", errors="replace")
    decode = parse_last(
        r"gen=(\d+).*?decoding chunk=([0-9.]+) t/s avg=([0-9.]+) t/s ([0-9.]+)s",
        text,
    )
    prefill = parse_last(r"prompt done ([0-9.]+)s", text)
    stats = parse_last(r"ds4: DSpark stats (?P<body>.*)$", text)
    result: dict[str, Any] = {
        "decode_tokens": int(decode.group(1)) if decode else None,
        "decode_chunk_tps": float(decode.group(2)) if decode else None,
        "decode_avg_tps": float(decode.group(3)) if decode else None,
        "decode_seconds": float(decode.group(4)) if decode else None,
        "prefill_seconds": float(prefill.group(1)) if prefill else None,
    }
    if stats:
        body = stats.group("body")
        for key in (
            "cycles", "first_tokens", "proposed", "accepted_draft", "full",
            "partial", "miss_first", "no_draft", "no_room", "invalid",
            "scheduler_skips", "tail_skips", "verifier_unavailable", "errors",
            "fallbacks",
            "verifier_exact", "sampled_accepts", "sampled_rejections",
            "sampled_corrections",
        ):
            match = re.search(rf"(?:^| ){key}=([0-9]+)", body)
            result[key] = int(match.group(1)) if match else None
        for key in (
            "accept_rate", "avg_accept", "proposal_coverage",
            "accepted_per_verify",
        ):
            match = re.search(rf"(?:^| ){key}=([0-9.]+)%?", body)
            result[key] = float(match.group(1)) if match else None
        match = re.search(r"(?:^| )net_saved=([-0-9.]+)", body)
        result["net_saved_ms"] = float(match.group(1)) if match else None
        for key in ("propose", "verify", "spec_total", "target", "saved"):
            match = re.search(rf"(?:^| ){key}=([-0-9.]+)", body)
            result[f"{key}_ms"] = float(match.group(1)) if match else None
        saved_ms = result.get("saved_ms")
        proposal_verify_ms = ((result.get("propose_ms") or 0.0) +
                              (result.get("verify_ms") or 0.0))
        total_extra_ms = ((result.get("propose_ms") or 0.0) +
                          (result.get("spec_total_ms") or 0.0))
        result["proposal_verify_saved_ratio"] = (
            proposal_verify_ms / saved_ms if saved_ms and saved_ms > 0 else None
        )
        result["total_extra_saved_ratio"] = (
            total_extra_ms / saved_ms if saved_ms and saved_ms > 0 else None
        )
        for key in (
            "draft_len_hist", "accepted_len_hist", "rejection_pos_hist",
            "position_accept", "confidence_accept", "length_stats",
        ):
            match = re.search(rf"(?:^| ){key}=([^ ]+)", body)
            result[key] = match.group(1) if match else None
    return result


def make_request(prompt: str, output_tokens: int,
                 workload: str) -> dict[str, Any]:
    request: dict[str, Any] = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": "You are a precise C99 coding assistant."},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": output_tokens,
        "seed": 42,
        "reasoning_effort": "max",
    }
    if workload == "thinking-max-greedy":
        request["temperature"] = 0
        request["top_p"] = 1
    return request


def run_request(mode: str, prompt: str, target: int, repeat: int,
                output_tokens: int, model: Path, support: Path, ctx: int, kv_dir: Path,
                artifact_dir: Path, workload: str,
                dspark_confidence: float | None = None) -> dict[str, Any]:
    label = f"{target // 1000:03d}k-r{repeat}-{mode}"
    proc, port, log_path, log_file, startup_memory = start_server(
        mode, model, support, ctx, kv_dir, artifact_dir, label,
        dspark_confidence
    )
    started = time.monotonic()
    response: dict[str, Any] | None = None
    ttft_seconds: float | None = None
    request_error: str | None = None
    try:
        response, ttft_seconds = http_chat_stream(
            f"http://127.0.0.1:{port}/v1/chat/completions",
            make_request(prompt, output_tokens, workload),
            timeout=1800.0,
        )
    except Exception as error:
        request_error = f"{type(error).__name__}: {error}"
    wall_seconds = time.monotonic() - started
    runtime_memory = memory_snapshot()
    exit_status = stop_server(proc)
    log_file.close()
    log_metrics = parse_log(log_path)
    if request_error:
        raise RuntimeError(f"{label} failed: {request_error}; see {log_path}")
    runtime_free = runtime_memory.get("free_percent")
    before_swap = startup_memory.get("before", {}).get("swap_used_mb")
    runtime_swap = runtime_memory.get("swap_used_mb")
    runtime_swap_growth = (
        runtime_swap - before_swap
        if isinstance(before_swap, float) and isinstance(runtime_swap, float)
        else None
    )
    if ((isinstance(runtime_free, float) and runtime_free <= 5.0) or
            (isinstance(runtime_swap_growth, float) and
             runtime_swap_growth > 2048.0)):
        raise RuntimeError(
            f"Think Max runtime memory gate failed: free={runtime_free}% "
            f"swap_growth={runtime_swap_growth} MiB; see {log_path}"
        )
    assert response is not None
    response_path = artifact_dir / f"{label}.response.json"
    response_path.write_text(
        json.dumps(response, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    usage = response.get("usage") or {}
    details = usage.get("prompt_tokens_details") or {}
    choices = response.get("choices") or []
    choice = choices[0] if choices else {}
    message = choice.get("message") or {}
    content = message.get("content") or ""
    reasoning_content = message.get("reasoning_content") or ""
    generated_text = reasoning_content + content
    return {
        "target_tokens": target,
        "repeat": repeat,
        "mode": mode,
        "wall_seconds": wall_seconds,
        "ttft_seconds": ttft_seconds,
        "server_exit_status": exit_status,
        "prompt_tokens": usage.get("prompt_tokens"),
        "cached_tokens": details.get("cached_tokens"),
        "cache_write_tokens": details.get("cache_write_tokens"),
        "completion_tokens": usage.get("completion_tokens"),
        "finish_reason": choice.get("finish_reason"),
        "content_sha256": sha256_text(generated_text),
        "content": content,
        "reasoning_content": reasoning_content,
        "log": str(log_path),
        "response": str(response_path),
        "startup_memory": startup_memory,
        "runtime_memory": runtime_memory,
        **log_metrics,
    }


def summarize_results(frontiers: list[int], runs: list[dict[str, Any]],
                      output_tokens: int, repeats: int,
                      modes: str) -> dict[str, Any]:
    frontier_rows: list[dict[str, Any]] = []
    uplifts: list[float] = []
    for target in frontiers:
        row: dict[str, Any] = {"target_tokens": target}
        medians: dict[str, float] = {}
        for mode in ("baseline", "dspark"):
            selected = [
                run for run in runs
                if run["target_tokens"] == target and run["mode"] == mode
            ]
            decode_values = [
                float(run["decode_avg_tps"]) for run in selected
                if run.get("decode_avg_tps") is not None
            ]
            ttft_values = [
                float(run["ttft_seconds"]) for run in selected
                if run.get("ttft_seconds") is not None
            ]
            if decode_values:
                medians[mode] = statistics.median(decode_values)
                row[f"{mode}_decode_tps_median"] = medians[mode]
            if ttft_values:
                row[f"{mode}_ttft_seconds_median"] = statistics.median(ttft_values)
        if medians.get("baseline", 0.0) > 0.0 and "dspark" in medians:
            uplift = 100.0 * (medians["dspark"] / medians["baseline"] - 1.0)
            row["decode_uplift_percent"] = uplift
            uplifts.append(uplift)
        frontier_rows.append(row)

    dspark_runs = [run for run in runs if run["mode"] == "dspark"]
    accepted = sum(int(run.get("accepted_draft") or 0) for run in dspark_runs)
    generated = sum(
        int(run.get("first_tokens") or 0) +
        int(run.get("accepted_draft") or 0) +
        int(run.get("sampled_corrections") or 0)
        for run in dspark_runs
    )
    verified = sum(
        int(run.get("full") or 0) + int(run.get("partial") or 0)
        for run in dspark_runs
    )
    saved_ms = sum(float(run.get("saved_ms") or 0.0) for run in dspark_runs)
    proposal_verify_ms = sum(
        float(run.get("propose_ms") or 0.0) +
        float(run.get("verify_ms") or 0.0)
        for run in dspark_runs
    )
    verifier_errors = sum(int(run.get("errors") or 0) for run in dspark_runs)
    verifier_unavailable = sum(
        int(run.get("verifier_unavailable") or 0) for run in dspark_runs
    )
    free_values: list[float] = []
    swap_growth_values: list[float] = []
    for run in runs:
        startup = run.get("startup_memory") or {}
        runtime = run.get("runtime_memory") or {}
        for snapshot in (startup.get("after") or {}, runtime):
            if isinstance(snapshot.get("free_percent"), float):
                free_values.append(snapshot["free_percent"])
        before_swap = (startup.get("before") or {}).get("swap_used_mb")
        runtime_swap = runtime.get("swap_used_mb")
        if isinstance(before_swap, float) and isinstance(runtime_swap, float):
            swap_growth_values.append(runtime_swap - before_swap)

    aggregate = {
        "frontier_uplift_median_percent": (
            statistics.median(uplifts) if uplifts else None
        ),
        "worst_frontier_uplift_percent": min(uplifts) if uplifts else None,
        "accepted_generated_percent": (
            100.0 * accepted / generated if generated else None
        ),
        "accepted_per_verify": accepted / verified if verified else None,
        "proposal_verify_saved_ratio": (
            proposal_verify_ms / saved_ms if saved_ms > 0.0 else None
        ),
        "verifier_errors": verifier_errors,
        "verifier_unavailable": verifier_unavailable,
        "minimum_free_percent": min(free_values) if free_values else None,
        "maximum_swap_growth_mb": (
            max(swap_growth_values) if swap_growth_values else None
        ),
    }
    formal = (
        modes == "both" and set(frontiers) == {30000, 50000, 75000, 100000} and
        output_tokens >= 512 and repeats >= 3
    )
    gate_checks = {
        "overall_uplift_at_least_5_percent": (
            aggregate["frontier_uplift_median_percent"] is not None and
            aggregate["frontier_uplift_median_percent"] >= 5.0
        ),
        "no_frontier_below_minus_2_percent": (
            aggregate["worst_frontier_uplift_percent"] is not None and
            aggregate["worst_frontier_uplift_percent"] >= -2.0
        ),
        "accepted_generated_at_least_45_percent": (
            aggregate["accepted_generated_percent"] is not None and
            aggregate["accepted_generated_percent"] >= 45.0
        ),
        "accepted_per_verify_at_least_2_5": (
            aggregate["accepted_per_verify"] is not None and
            aggregate["accepted_per_verify"] >= 2.5
        ),
        "proposal_verify_saved_ratio_at_most_0_7": (
            aggregate["proposal_verify_saved_ratio"] is not None and
            aggregate["proposal_verify_saved_ratio"] <= 0.7
        ),
        "verifier_errors_zero": verifier_errors == 0,
        "verifier_unavailable_zero": verifier_unavailable == 0,
        "memory_gate": (
            (aggregate["minimum_free_percent"] is None or
             aggregate["minimum_free_percent"] > 5.0) and
            (aggregate["maximum_swap_growth_mb"] is None or
             aggregate["maximum_swap_growth_mb"] <= 2048.0)
        ),
    }
    return {
        "formal_gate_evaluated": formal,
        "frontiers": frontier_rows,
        "aggregate": aggregate,
        "gate_checks": gate_checks,
        "gate_passed": formal and all(gate_checks.values()),
    }


def write_markdown_report(path: Path, summary: dict[str, Any]) -> None:
    lines = ["# DSpark Think Max 性能报告", ""]
    lines.append(
        "正式门禁：" +
        ("通过" if summary["gate_passed"] else
         "未通过" if summary["formal_gate_evaluated"] else "未执行（快速诊断）")
    )
    lines.extend(["", "| Frontier | Baseline tok/s | DSpark tok/s | 提升 | Baseline TTFT | DSpark TTFT |", "|---:|---:|---:|---:|---:|---:|"])
    for row in summary["frontiers"]:
        def value(key: str, digits: int = 2) -> str:
            item = row.get(key)
            return f"{item:.{digits}f}" if isinstance(item, (int, float)) else "—"
        lines.append(
            f"| {row['target_tokens']} | "
            f"{value('baseline_decode_tps_median')} | "
            f"{value('dspark_decode_tps_median')} | "
            f"{value('decode_uplift_percent')}% | "
            f"{value('baseline_ttft_seconds_median')}s | "
            f"{value('dspark_ttft_seconds_median')}s |"
        )
    lines.extend(["", "## 聚合指标", ""])
    for key, value in summary["aggregate"].items():
        rendered = f"{value:.3f}" if isinstance(value, float) else str(value)
        lines.append(f"- `{key}`: {rendered}")
    lines.extend(["", "## 门禁", ""])
    for key, passed in summary["gate_checks"].items():
        lines.append(f"- {'通过' if passed else '失败'}：`{key}`")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def prepare_cache(prompts: dict[int, str], output_tokens: int, model: Path,
                  support: Path, ctx: int, kv_dir: Path,
                  artifact_dir: Path, workload: str,
                  dspark_confidence: float | None = None) -> list[dict[str, Any]]:
    proc, port, log_path, log_file, startup_memory = start_server(
        "baseline", model, support, ctx, kv_dir, artifact_dir, "cache-prepare",
        dspark_confidence
    )
    prepared: list[dict[str, Any]] = []
    try:
        for target, prompt in prompts.items():
            started = time.monotonic()
            response = http_json(
                f"http://127.0.0.1:{port}/v1/chat/completions",
                make_request(prompt, min(output_tokens, 1), workload),
                timeout=1800.0,
            )
            usage = response.get("usage") or {}
            details = usage.get("prompt_tokens_details") or {}
            prepared.append({
                "target_tokens": target,
                "prompt_tokens": usage.get("prompt_tokens"),
                "cached_tokens": details.get("cached_tokens"),
                "cache_write_tokens": details.get("cache_write_tokens"),
                "wall_seconds": time.monotonic() - started,
                "startup_memory": startup_memory,
            })
            print(
                f"cache {target}: prompt={usage.get('prompt_tokens')} "
                f"cached={details.get('cached_tokens')} "
                f"wall={prepared[-1]['wall_seconds']:.2f}s",
                flush=True,
            )
    finally:
        stop_server(proc)
        log_file.close()
    return prepared


def command_output(command: list[str]) -> str | None:
    try:
        return subprocess.check_output(
            command, cwd=REPO_ROOT, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def main() -> int:
    args = parse_args()
    frontiers = [int(value) for value in args.frontiers.split(",") if value]
    for path in (args.model, args.support, args.source):
        if not path.is_file():
            raise SystemExit(f"missing required file: {path}")
    if max(frontiers) + args.output_tokens + 256 > args.ctx:
        raise SystemExit("--ctx is too small for the largest frontier")
    if args.ctx < 393216:
        raise SystemExit(
            "Think Max requires --ctx >= 393216; refusing to benchmark a silent fallback"
        )
    if args.repeats < 1:
        raise SystemExit("--repeats must be positive")
    if (args.dspark_confidence is not None and
            not 0.0 <= args.dspark_confidence <= 1.0):
        raise SystemExit("--dspark-confidence must be in [0, 1]")
    if args.skip_cache_prepare and args.kv_dir is None:
        raise SystemExit("--skip-cache-prepare requires --kv-dir")

    artifact_dir = args.artifact_dir.resolve()
    artifact_dir.mkdir(parents=True, exist_ok=True)
    kv_dir = (args.kv_dir.resolve() if args.kv_dir is not None
              else artifact_dir / "kv-cache")
    kv_dir.mkdir(parents=True, exist_ok=True)

    source = args.source.read_text(encoding="utf-8")
    source_tokens = args.source_token_count
    prompts: dict[int, str] = {}
    prompt_metadata: dict[int, dict[str, Any]] = {}
    for target in frontiers:
        print(f"calibrating {target} token prompt", flush=True)
        prompt, char_count, raw_count = calibrated_prompt(
            source, target, args.model.resolve(), source_tokens, artifact_dir
        )
        prompts[target] = prompt
        prompt_metadata[target] = {
            "source_characters": char_count,
            "prompt_characters": len(prompt),
            "raw_prompt_tokens": raw_count,
            "prompt_sha256": sha256_text(prompt),
        }

    prepared: list[dict[str, Any]] = []
    if not args.skip_cache_prepare:
        print("preparing shared disk KV cache", flush=True)
        prepared = prepare_cache(
            prompts, args.output_tokens, args.model.resolve(),
            args.support.resolve(), args.ctx, kv_dir, artifact_dir,
            args.workload, args.dspark_confidence
        )

    runs: list[dict[str, Any]] = []
    selected_modes = {
        "both": ("baseline", "dspark"),
        "baseline": ("baseline",),
        "dspark": ("dspark",),
    }[args.modes]
    for index, target in enumerate(frontiers):
        first = (("baseline", "dspark") if index % 2 == 0
                 else ("dspark", "baseline"))
        first = tuple(mode for mode in first if mode in selected_modes)
        for repeat in range(1, args.repeats + 1):
            order = first if repeat % 2 == 1 else tuple(reversed(first))
            for mode in order:
                print(f"running {target} tokens repeat {repeat} {mode}", flush=True)
                run = run_request(
                    mode, prompts[target], target, repeat, args.output_tokens,
                    args.model.resolve(), args.support.resolve(), args.ctx, kv_dir,
                    artifact_dir, args.workload, args.dspark_confidence
                )
                runs.append(run)
                print(
                    f"  prompt={run['prompt_tokens']} cached={run['cached_tokens']} "
                    f"decode={run['decode_avg_tps']} t/s "
                    f"accept={run.get('accept_rate')}% wall={run['wall_seconds']:.2f}s",
                    flush=True,
                )

    output_pairs: list[dict[str, Any]] = []
    for target in frontiers:
        for repeat in range(1, args.repeats + 1):
            pair = [
                run for run in runs
                if run["target_tokens"] == target and run["repeat"] == repeat
            ]
            hashes = {run["mode"]: run["content_sha256"] for run in pair}
            output_pairs.append({
                "target_tokens": target,
                "repeat": repeat,
                "hashes": hashes,
                "identical": len(set(hashes.values())) == 1,
            })

    result = {
        "schema": "ds4-dspark-long-context-benchmark-v2",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "git_commit": command_output(["git", "rev-parse", "HEAD"]),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "model": {
            "path": str(args.model.resolve()),
            "size_bytes": args.model.stat().st_size,
        },
        "support": {
            "path": str(args.support.resolve()),
            "size_bytes": args.support.stat().st_size,
        },
        "source": {
            "path": str(args.source.resolve()),
            "token_count": source_tokens,
            "size_bytes": args.source.stat().st_size,
        },
        "configuration": {
            "frontiers": frontiers,
            "ctx": args.ctx,
            "output_tokens": args.output_tokens,
            "repeats": args.repeats,
            "workload": args.workload,
            "temperature": 0 if args.workload == "thinking-max-greedy" else "server-default",
            "top_p": 1 if args.workload == "thinking-max-greedy" else "server-default",
            "min_p": "server-default",
            "reasoning_effort": "max",
            "dspark_confidence": args.dspark_confidence,
            "modes": args.modes,
            "ordering": "alternating AB/BA per frontier and repeat",
            "shared_disk_kv": True,
        },
        "prompts": prompt_metadata,
        "cache_prepare": prepared,
        "runs": runs,
        "output_pairs": output_pairs,
    }
    summary = summarize_results(
        frontiers, runs, args.output_tokens, args.repeats, args.modes
    )
    result["summary"] = summary
    result_path = artifact_dir / "results.json"
    result_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    csv_path = artifact_dir / "runs.csv"
    csv_fields = [
        "target_tokens", "repeat", "mode", "prompt_tokens", "cached_tokens",
        "completion_tokens", "wall_seconds", "ttft_seconds", "prefill_seconds",
        "decode_seconds", "decode_avg_tps", "proposed", "accepted_draft",
        "accept_rate", "avg_accept", "proposal_coverage",
        "accepted_per_verify", "scheduler_skips", "errors",
        "propose_ms", "verify_ms", "saved_ms",
        "proposal_verify_saved_ratio", "total_extra_saved_ratio",
        "net_saved_ms", "position_accept", "confidence_accept",
        "length_stats", "content_sha256",
    ]
    with csv_path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=csv_fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(runs)
    write_markdown_report(artifact_dir / "report.md", summary)
    if not args.keep_kv and args.kv_dir is None:
        shutil.rmtree(kv_dir)
        result["kv_cache_note"] = "Benchmark-only disk KV cache removed after the run."
        result_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(f"results: {result_path}", flush=True)
    if (args.workload == "thinking-max-greedy" and args.modes == "both" and
            not all(pair["identical"] for pair in output_pairs)):
        print("warning: one or more baseline/DSpark outputs differ", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
