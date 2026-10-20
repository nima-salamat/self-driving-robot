"""Compare single-process and --multiprocess runtime on a Linux robot.

This runner always adds --without-arduino: it is for camera/perception
benchmarking only and never opens the Arduino serial connection. Stop any
other robot process before running so both variants can exclusively use the
camera. The --multiprocess flag currently enables both the shared-memory
camera worker and the process-backed sign detector.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import queue
import re
import signal
import statistics
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone


_PAIR_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)=([^\s]+)")
_PERFORMANCE_PREFIXES = (
    "performance:",
    "performance sources:",
    "performance vision stages:",
    "performance sign stages:",
    "performance runtime stages:",
)


def parse_performance_line(line: str) -> dict[str, float | str]:
    """Parse key=value fields from a performance logger line."""
    if not line.startswith(_PERFORMANCE_PREFIXES):
        return {}
    parsed: dict[str, float | str] = {}
    for key, raw in _PAIR_RE.findall(line):
        try:
            value = float(raw)
        except ValueError:
            parsed[key] = raw
            continue
        if math.isfinite(value):
            parsed[key] = value
    return parsed


def summarize_values(values: list[float]) -> dict[str, float | int] | None:
    """Summarize a list of finite numeric samples without assuming a sample rate."""
    clean = [float(value) for value in values if math.isfinite(float(value))]
    if not clean:
        return None
    ordered = sorted(clean)

    def nearest_rank(percent: float) -> float:
        index = min(len(ordered) - 1, max(0, math.ceil(len(ordered) * percent) - 1))
        return ordered[index]

    return {
        "count": len(ordered),
        "mean": sum(ordered) / len(ordered),
        "median": float(statistics.median(ordered)),
        "p95": nearest_rank(0.95),
        "max": ordered[-1],
    }


def _read_proc_stats(proc_root: Path) -> dict[int, dict[str, int]]:
    """Read Linux /proc stats; no third-party process-inspection library needed."""
    stats: dict[int, dict[str, int]] = {}
    try:
        entries = list(proc_root.iterdir())
    except OSError:
        return stats

    for entry in entries:
        if not entry.name.isdigit():
            continue
        try:
            raw = (entry / "stat").read_text(encoding="utf-8")
            closing = raw.rfind(")")
            if closing < 0:
                continue
            # Fields after ')' begin with field 3 (state).
            fields = raw[closing + 2 :].split()
            if len(fields) < 22:
                continue
            pid = int(entry.name)
            stats[pid] = {
                "ppid": int(fields[1]),             # field 4
                "cpu_ticks": int(fields[11]) + int(fields[12]),  # fields 14+15
                "rss_bytes": max(0, int(fields[21])) * os.sysconf("SC_PAGE_SIZE"),
            }
        except (OSError, ValueError, IndexError):
            continue
    return stats


def _process_tree_totals(root_pid: int, proc_root: Path = Path("/proc")) -> dict[str, int] | None:
    """Return total CPU ticks and resident bytes for root plus live descendants."""
    stats = _read_proc_stats(proc_root)
    if root_pid not in stats:
        return None

    descendants = {root_pid}
    changed = True
    while changed:
        changed = False
        for pid, item in stats.items():
            if item["ppid"] in descendants and pid not in descendants:
                descendants.add(pid)
                changed = True

    return {
        "cpu_ticks": sum(stats[pid]["cpu_ticks"] for pid in descendants),
        "rss_bytes": sum(stats[pid]["rss_bytes"] for pid in descendants),
        "process_count": len(descendants),
    }


def _proc_tree_sample(root_pid: int) -> dict[str, int] | None:
    try:
        return _process_tree_totals(root_pid)
    except (OSError, ValueError):
        return None


def _metric_summary(samples: list[dict[str, float | str]]) -> dict[str, dict[str, float | int]]:
    numeric: dict[str, list[float]] = {}
    for sample in samples:
        for key, value in sample.items():
            if isinstance(value, (int, float)) and math.isfinite(float(value)):
                numeric.setdefault(key, []).append(float(value))
    return {
        key: summary
        for key, values in numeric.items()
        if (summary := summarize_values(values)) is not None
    }


def _reader(pipe, output_queue: queue.Queue) -> None:
    try:
        for line in pipe:
            output_queue.put((time.monotonic(), line.rstrip("\r\n")))
    finally:
        output_queue.put((time.monotonic(), None))


def _make_command(mode: str, target_fps: float, multiprocess: bool, sign_threads: int | None) -> list[str]:
    root = Path(__file__).resolve().parents[2]
    command = [
        sys.executable,
        str(root / "python" / "main.py"),
        "--mode", mode,
        "--without-arduino",
        "--performance",
        "--target-fps", str(target_fps),
        "--log-level", "INFO",
    ]
    if multiprocess:
        command.append("--multiprocess")
        if sign_threads is not None:
            command.extend(["--sign-intra-op-threads", str(sign_threads)])
    return command


def run_trial(
    *,
    mode: str,
    target_fps: float,
    multiprocess: bool,
    warmup_seconds: float,
    duration_seconds: float,
    sign_threads: int | None = None,
) -> dict:
    command = _make_command(mode, target_fps, multiprocess, sign_threads)
    root = Path(__file__).resolve().parents[2]
    environment = os.environ.copy()
    environment["PYTHONUNBUFFERED"] = "1"

    started = time.monotonic()
    measured_from = started + warmup_seconds
    ends_at = measured_from + duration_seconds
    output_queue: queue.Queue = queue.Queue()
    lines: list[str] = []
    perf_samples: list[dict[str, float | str]] = []
    cpu_samples: list[float] = []
    rss_samples_mb: list[float] = []
    process_samples: list[int] = []
    previous_tree = None
    previous_sample_at = None
    reader_finished = False
    launch_error = None
    return_code = None

    print(
        f"[benchmark] mode={mode} variant={'multiprocess' if multiprocess else 'single-process'} "
        f"warmup={warmup_seconds:.0f}s measured={duration_seconds:.0f}s",
        flush=True,
    )
    print("[benchmark] " + " ".join(command), flush=True)

    try:
        process = subprocess.Popen(
            command,
            cwd=root,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
            bufsize=1,
        )
    except OSError as exc:
        return {
            "mode": mode,
            "variant": "multiprocess" if multiprocess else "single-process",
            "status": "launch_error",
            "error": f"{type(exc).__name__}: {exc}",
            "command": command,
        }

    assert process.stdout is not None
    reader = threading.Thread(
        target=_reader, args=(process.stdout, output_queue), daemon=True
    )
    reader.start()

    next_proc_sample = started
    try:
        while time.monotonic() < ends_at and process.poll() is None:
            now = time.monotonic()
            while True:
                try:
                    line_at, line = output_queue.get_nowait()
                except queue.Empty:
                    break
                if line is None:
                    reader_finished = True
                    continue
                lines.append(line)
                if len(lines) > 500:
                    del lines[: len(lines) - 500]
                if line_at >= measured_from and line.startswith(_PERFORMANCE_PREFIXES):
                    parsed = parse_performance_line(line)
                    if parsed:
                        perf_samples.append(parsed)

            if now >= next_proc_sample:
                current = _proc_tree_sample(process.pid)
                if current is not None:
                    if previous_tree is not None and previous_sample_at is not None:
                        interval = now - previous_sample_at
                        delta_ticks = max(0, current["cpu_ticks"] - previous_tree["cpu_ticks"])
                        if interval > 0 and now >= measured_from:
                            try:
                                ticks_per_second = os.sysconf("SC_CLK_TCK")
                            except (ValueError, OSError):
                                ticks_per_second = 100
                            cpu_samples.append((delta_ticks / ticks_per_second) / interval * 100.0)
                    if now >= measured_from:
                        rss_samples_mb.append(current["rss_bytes"] / (1024.0 * 1024.0))
                        process_samples.append(current["process_count"])
                    previous_tree = current
                    previous_sample_at = now
                next_proc_sample = now + 1.0

            time.sleep(0.025)

        # Request graceful shutdown through the application's SIGINT handler.
        if process.poll() is None:
            process.send_signal(signal.SIGINT)
            try:
                return_code = process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    return_code = process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    return_code = process.wait(timeout=2)
        else:
            return_code = process.returncode
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        reader.join(timeout=2.0)
        while True:
            try:
                line_at, line = output_queue.get_nowait()
            except queue.Empty:
                break
            if line is None:
                reader_finished = True
                continue
            lines.append(line)
            if len(lines) > 500:
                del lines[: len(lines) - 500]
            if line_at >= measured_from and line.startswith(_PERFORMANCE_PREFIXES):
                parsed = parse_performance_line(line)
                if parsed:
                    perf_samples.append(parsed)
        if process.stdout:
            process.stdout.close()

    statuses = [
        line.split("performance sources:", 1)[1].strip()
        for line in lines
        if "performance sources:" in line
    ]
    return {
        "mode": mode,
        "variant": "multiprocess" if multiprocess else "single-process",
        "target_fps": target_fps,
        "warmup_seconds": warmup_seconds,
        "duration_seconds": duration_seconds,
        "status": "completed" if return_code == 0 else "exited",
        "exit_code": return_code,
        "performance_samples": len(perf_samples),
        "metrics": _metric_summary(perf_samples),
        "process_tree_cpu_pct": summarize_values(cpu_samples),
        "process_tree_rss_mb": summarize_values(rss_samples_mb),
        "process_tree_count": summarize_values([float(x) for x in process_samples]),
        "latest_worker_status": statuses[-1] if statuses else None,
        "performance_lines": [
            line for line in lines if line.startswith(_PERFORMANCE_PREFIXES)
        ],
        "last_log_lines": lines[-60:],
        "command": command,
        "reader_finished": reader_finished,
        "launch_error": launch_error,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Compare normal and --multiprocess robot runtime performance on Linux. "
            "The runner always uses --without-arduino."
        )
    )
    parser.add_argument("--mode", choices=("city", "race"), default="city")
    parser.add_argument("--target-fps", type=float, default=30.0)
    parser.add_argument("--warmup-seconds", type=float, default=10.0)
    parser.add_argument("--duration-seconds", type=float, default=30.0)
    parser.add_argument("--rounds", type=int, default=2, help="Paired comparisons; run order alternates.")
    parser.add_argument("--sign-intra-op-threads", type=int, default=None)
    parser.add_argument("--output", type=Path, default=None, help="JSON output path (default: output/multiprocessing-benchmark-<timestamp>.json)")
    args = parser.parse_args(argv)

    if not sys.platform.startswith("linux") or not Path("/proc/self/stat").exists():
        parser.error("This benchmark runner requires Linux /proc (for Raspberry Pi OS).")
    if not math.isfinite(args.target_fps) or args.target_fps <= 0:
        parser.error("--target-fps must be positive and finite.")
    if args.warmup_seconds < 0 or not math.isfinite(args.warmup_seconds):
        parser.error("--warmup-seconds must be finite and non-negative.")
    if args.duration_seconds < 5 or not math.isfinite(args.duration_seconds):
        parser.error("--duration-seconds must be at least 5.")
    if args.rounds < 1:
        parser.error("--rounds must be at least 1.")
    if args.sign_intra_op_threads is not None and args.sign_intra_op_threads < 1:
        parser.error("--sign-intra-op-threads must be positive.")
    if args.sign_intra_op_threads is not None and not args.sign_intra_op_threads:
        parser.error("--sign-intra-op-threads requires the multiprocess variant.")

    trials = []
    for round_index in range(args.rounds):
        variants = (False, True) if round_index % 2 == 0 else (True, False)
        for multiprocess in variants:
            if multiprocess and args.sign_intra_op_threads is not None:
                sign_threads = args.sign_intra_op_threads
            else:
                sign_threads = None
            trial = run_trial(
                mode=args.mode,
                target_fps=args.target_fps,
                multiprocess=multiprocess,
                warmup_seconds=args.warmup_seconds,
                duration_seconds=args.duration_seconds,
                sign_threads=sign_threads,
            )
            trials.append(trial)
            metric = trial.get("metrics", {})
            fps = metric.get("fps", {}).get("median")
            loop_p95 = metric.get("loop_p95_ms", {}).get("median")
            cpu = (trial.get("process_tree_cpu_pct") or {}).get("median")
            rss = (trial.get("process_tree_rss_mb") or {}).get("median")
            print(
                f"[result] {trial['variant']} status={trial['status']} "
                f"fps_median={fps if fps is not None else 'n/a'} "
                f"loop_p95_ms_median={loop_p95 if loop_p95 is not None else 'n/a'} "
                f"process_tree_cpu_pct_median={cpu if cpu is not None else 'n/a'} "
                f"process_tree_rss_mb_median={rss if rss is not None else 'n/a'}",
                flush=True,
            )

    def variant_summary(name: str) -> dict:
        selected = [trial for trial in trials if trial["variant"] == name and trial["status"] == "completed"]
        summaries: dict[str, object] = {"successful_trials": len(selected)}
        keys = sorted({key for trial in selected for key in trial.get("metrics", {})})
        for key in keys:
            medians = [
                float(trial["metrics"][key]["median"])
                for trial in selected if key in trial.get("metrics", {})
            ]
            summaries[key] = summarize_values(medians)
        for key in ("process_tree_cpu_pct", "process_tree_rss_mb", "process_tree_count"):
            medians = [
                float(trial[key]["median"])
                for trial in selected if trial.get(key)
            ]
            summaries[key] = summarize_values(medians)
        return summaries

    root = Path(__file__).resolve().parents[2]
    output_path = args.output or (
        root / "output" /
        ("multiprocessing-benchmark-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + ".json")
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "schema_version": 1,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "host": {
            "platform": sys.platform,
            "python": sys.version,
            "machine": os.uname().machine if hasattr(os, "uname") else None,
            "cpu_count": os.cpu_count(),
        },
        "configuration": {
            "mode": args.mode,
            "target_fps": args.target_fps,
            "warmup_seconds": args.warmup_seconds,
            "duration_seconds": args.duration_seconds,
            "rounds": args.rounds,
            "without_arduino": True,
            "multiprocess_combines_camera_and_sign_worker": True,
        },
        "summaries": {
            "single-process": variant_summary("single-process"),
            "multiprocess": variant_summary("multiprocess"),
        },
        "trials": trials,
    }
    output_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(f"[benchmark] JSON report: {output_path}", flush=True)

    successful = all(
        report["summaries"][name]["successful_trials"] == args.rounds
        for name in ("single-process", "multiprocess")
    )
    return 0 if successful else 2


if __name__ == "__main__":
    raise SystemExit(main())
