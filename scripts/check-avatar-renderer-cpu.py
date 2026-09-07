#!/usr/bin/env python3
"""Fail when the zara-avatar Electron process tree burns CPU while idle."""

from __future__ import annotations

import argparse
import json
import math
import os
import select
import signal
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RENDERER = ROOT / "plugins" / "zara-avatar" / "renderer"


@dataclass(frozen=True)
class Sample:
    state: str
    average_cpu_percent: float
    p95_cpu_percent: float
    samples: int
    max_average_cpu_percent: float
    max_p95_cpu_percent: float
    passed: bool


def process_ticks(pid: int) -> int:
    try:
        raw = Path(f"/proc/{pid}/stat").read_text()
    except (FileNotFoundError, ProcessLookupError):
        return 0
    end = raw.rfind(")")
    fields = raw[end + 2 :].split()
    return int(fields[11]) + int(fields[12])


def child_pids(pid: int) -> tuple[int, ...]:
    try:
        text = Path(f"/proc/{pid}/task/{pid}/children").read_text().strip()
    except (FileNotFoundError, ProcessLookupError):
        return ()
    return tuple(int(value) for value in text.split()) if text else ()


def tree_ticks(root_pid: int) -> int:
    pending = [root_pid]
    seen: set[int] = set()
    total = 0
    while pending:
        pid = pending.pop()
        if pid in seen:
            continue
        seen.add(pid)
        total += process_ticks(pid)
        pending.extend(child_pids(pid))
    return total


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    return ordered[max(0, math.ceil(len(ordered) * fraction) - 1)]


def sample_cpu(pid: int, seconds: float, interval: float) -> tuple[float, float, int]:
    clock_ticks = os.sysconf("SC_CLK_TCK")
    start_time = time.monotonic()
    start_ticks = tree_ticks(pid)
    previous_time = start_time
    previous_ticks = start_ticks
    intervals: list[float] = []

    while time.monotonic() - start_time < seconds:
        time.sleep(interval)
        now = time.monotonic()
        current_ticks = tree_ticks(pid)
        elapsed = now - previous_time
        delta = max(0, current_ticks - previous_ticks)
        intervals.append((delta / clock_ticks) / elapsed * 100.0)
        previous_time = now
        previous_ticks = current_ticks

    total_elapsed = previous_time - start_time
    total_delta = max(0, previous_ticks - start_ticks)
    average = (total_delta / clock_ticks) / total_elapsed * 100.0
    return average, percentile(intervals, 0.95), len(intervals)


def read_document(process: subprocess.Popen[str], timeout: float, log) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"renderer exited with code {process.returncode}")
        remaining = max(0.0, deadline - time.monotonic())
        readable, _, _ = select.select([process.stdout], [], [], min(0.25, remaining))
        if not readable:
            continue
        line = process.stdout.readline()
        if not line:
            continue
        log.write(line)
        log.flush()
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            continue
    raise TimeoutError("timed out waiting for renderer protocol output")


def wait_for(process: subprocess.Popen[str], predicate, timeout: float, log) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        document = read_document(process, max(0.1, deadline - time.monotonic()), log)
        if predicate(document):
            return document
    raise TimeoutError("timed out waiting for renderer state")


def send(process: subprocess.Popen[str], document: dict) -> None:
    process.stdin.write(json.dumps(document) + "\n")
    process.stdin.flush()


def stop(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    try:
        send(process, {"id": 9999, "command": "Shutdown", "params": {}})
        process.wait(timeout=3)
    except (BrokenPipeError, subprocess.TimeoutExpired):
        process.send_signal(signal.SIGTERM)
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample-seconds", type=float, default=6.0)
    parser.add_argument("--warmup-seconds", type=float, default=2.0)
    parser.add_argument("--interval-seconds", type=float, default=0.25)
    parser.add_argument("--max-average-cpu-percent", type=float, default=20.0)
    parser.add_argument("--max-p95-cpu-percent", type=float, default=45.0)
    args = parser.parse_args()

    if sys.platform != "linux":
        raise SystemExit("CPU budget requires Linux /proc")
    electron = RENDERER / "node_modules" / ".bin" / "electron"
    if not electron.exists():
        raise SystemExit(f"missing Electron binary: {electron}; run npm ci first")

    artifact_dir = Path(os.environ.get("ARTIFACT_DIR", ROOT / "artifacts"))
    artifact_dir.mkdir(parents=True, exist_ok=True)
    protocol_log = (artifact_dir / "avatar-renderer-protocol.log").open("w")
    stderr_log = (artifact_dir / "avatar-renderer-stderr.log").open("w")

    process = subprocess.Popen(
        [str(electron), "--no-sandbox", "main.mjs"],
        cwd=RENDERER,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=stderr_log,
        text=True,
        bufsize=1,
        start_new_session=True,
    )
    results: list[Sample] = []
    try:
        wait_for(process, lambda doc: doc.get("event") == "ready", 20.0, protocol_log)
        time.sleep(args.warmup_seconds)

        for state, command in (
            ("hidden-empty", None),
            ("visible-empty", {"id": 1, "command": "ShowWindow", "params": {}}),
            ("hidden-after-show", {"id": 2, "command": "HideWindow", "params": {}}),
        ):
            if command is not None:
                send(process, command)
                request_id = command["id"]
                wait_for(
                    process,
                    lambda doc, request_id=request_id: doc.get("id") == request_id and doc.get("ok") is True,
                    10.0,
                    protocol_log,
                )
                time.sleep(args.warmup_seconds)
            average, p95, count = sample_cpu(
                process.pid,
                args.sample_seconds,
                args.interval_seconds,
            )
            passed = average <= args.max_average_cpu_percent and p95 <= args.max_p95_cpu_percent
            results.append(
                Sample(
                    state=state,
                    average_cpu_percent=round(average, 2),
                    p95_cpu_percent=round(p95, 2),
                    samples=count,
                    max_average_cpu_percent=args.max_average_cpu_percent,
                    max_p95_cpu_percent=args.max_p95_cpu_percent,
                    passed=passed,
                )
            )
    finally:
        stop(process)
        protocol_log.close()
        stderr_log.close()

    report = artifact_dir / "avatar-renderer-cpu.json"
    report.write_text(json.dumps([asdict(result) for result in results], indent=2) + "\n")
    for result in results:
        status = "PASS" if result.passed else "FAIL"
        print(
            f"{status} {result.state}: avg={result.average_cpu_percent:.2f}% "
            f"p95={result.p95_cpu_percent:.2f}%"
        )
    return 0 if all(result.passed for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
