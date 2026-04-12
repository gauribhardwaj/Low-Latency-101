#!/usr/bin/env python3
"""
Low Latency 101 — Production Profiler Agent (Option A: local PID attach)

Attaches to a live Python process via py-spy, extracts hotspots, reads
source context, and submits to the Latency Copilot API for LLM analysis.

Usage:
    pip install py-spy requests
    python profiler_agent.py --pid <PID> --lang python --duration 30
    python profiler_agent.py --pid <PID> --lang python --duration 30 --api https://api-production-0435.up.railway.app

Requirements:
    - py-spy must be installed: pip install py-spy
    - macOS: run without sudo if target process owned by same user
    - Linux: run as root OR grant cap_sys_ptrace:
        sudo setcap cap_sys_ptrace=eip $(which py-spy)
    - Windows: run as Administrator

Java / C++ support:
    Java -> use async-profiler (jfr_agent.py, coming in Phase B)
    C++  -> use perf (perf_agent.py, coming in Phase B)
    For now, --lang java/cpp will raise a clear error.
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from typing import Any, Dict, List, Optional

try:
    import requests
except ImportError:
    print("ERROR: requests not installed. Run: pip install requests")
    sys.exit(1)


# ── Speedscope parsing ────────────────────────────────────────────────────────

def parse_speedscope(path: str, top_n: int = 10) -> List[Dict[str, Any]]:
    """
    Parse py-spy speedscope JSON and return the top N hotspots by inclusive time.

    Speedscope format:
        shared.frames  — list of {name, file, line}
        profiles[0].samples  — list of stacks; each stack is a list of frame indices
                               where index 0 = top-of-stack (leaf/on-CPU frame)
        profiles[0].weights  — wall-clock weight per sample (py-spy: 1 per sample)

    Inclusive time: a frame's weight across all samples where it appears ANYWHERE
    in the stack (not just at the top). Deduplicated per sample to handle recursion.
    Inclusive time is more useful than self-time for identifying refactor targets.
    """
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    frames  = data["shared"]["frames"]
    profile = data["profiles"][0]
    samples = profile["samples"]
    weights = profile.get("weights", [1] * len(samples))
    total_w = sum(weights) or 1

    inclusive: Dict[int, float] = {}
    for sample, w in zip(samples, weights):
        seen: set = set()
        for idx in sample:
            if idx not in seen:
                inclusive[idx] = inclusive.get(idx, 0.0) + w
                seen.add(idx)

    ranked = sorted(inclusive.items(), key=lambda kv: kv[1], reverse=True)[:top_n]

    return [
        {
            "function":    frames[i].get("name", "<unknown>"),
            "file":        frames[i].get("file", ""),
            "line":        int(frames[i].get("line") or 0),
            "pct_samples": round(w / total_w * 100, 1),
        }
        for i, w in ranked
    ]


# ── Source context ─────────────────────────────────────────────────────────────

def read_source_context(file_path: str, center_line: int, context: int = 20) -> str:
    """
    Read ±context lines around center_line (1-indexed).
    Returns empty string if file is not accessible.
    """
    if not file_path or not os.path.isfile(file_path):
        return ""
    try:
        with open(file_path, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        lo = max(0, center_line - context - 1)
        hi = min(len(lines), center_line + context)
        return "\n".join(
            f"{lo + i + 1:4d}: {lines[lo + i].rstrip()}"
            for i in range(hi - lo)
        )
    except Exception:
        return ""


# ── py-spy runner ─────────────────────────────────────────────────────────────

def run_pyspy(pid: int, duration: int, output_path: str) -> None:
    """
    Run py-spy in speedscope mode.
    --nonblocking: reads stack frames without pausing the target process.
    Essential for production — without it py-spy sends SIGSTOP at 100 Hz.
    """
    cmd = [
        "py-spy", "record",
        "--pid", str(pid),
        "--format", "speedscope",
        "--output", output_path,
        "--duration", str(duration),
        "--nonblocking",
    ]
    print(f"[profiler] Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"py-spy failed (exit {result.returncode}):\n{result.stderr.strip()}\n\n"
            "Common fixes:\n"
            "  Linux:   sudo python profiler_agent.py ...\n"
            "           OR: sudo setcap cap_sys_ptrace=eip $(which py-spy)\n"
            "  macOS:   make sure target process is owned by your user\n"
            "  Windows: run as Administrator"
        )


# ── API helpers ───────────────────────────────────────────────────────────────

def submit_job(api_base: str, lang: str, hotspots: List[Dict]) -> str:
    payload = {
        "language": lang,
        "code": "",
        "mode": "runtime_profile",
        "context": {
            "source": "runtime_profile",
            "hotspots": hotspots,
        },
    }
    resp = requests.post(f"{api_base}/jobs", json=payload, timeout=30)
    resp.raise_for_status()
    return resp.json()["job_id"]


def poll_job(api_base: str, job_id: str, timeout: int = 180) -> Dict:
    end = time.time() + timeout
    dots = 0
    while time.time() < end:
        try:
            d = requests.get(f"{api_base}/jobs/{job_id}", timeout=10).json()
            if d.get("status") in ("done", "error"):
                print()
                return d
        except Exception:
            pass
        print(".", end="", flush=True)
        dots += 1
        time.sleep(1.5)
    raise TimeoutError(f"Job {job_id} did not complete within {timeout}s")


# ── Output printer ────────────────────────────────────────────────────────────

def print_results(out: Dict) -> None:
    summary = out.get("summary", "")
    fixes   = out.get("hotspot_fixes", [])
    usage   = out.get("_usage", {})

    print("\n" + "=" * 70)
    print("  LOW LATENCY 101 — PRODUCTION PROFILE ANALYSIS")
    print("=" * 70)

    if summary:
        print(f"\n  Summary: {summary}\n")

    if not fixes:
        print("  No hotspot fixes returned.")
    else:
        for i, fix in enumerate(fixes, 1):
            fn  = fix.get("function", "?")
            pct = fix.get("pct_samples", "?")
            fp  = fix.get("file", "")
            ln  = fix.get("line", "?")
            why = fix.get("why", "")
            how = fix.get("fix", "")
            patch = fix.get("patch", "")

            print(f"  [{i}] {pct}%  {fn}")
            if fp:
                print(f"       {fp}:{ln}")
            if why:
                print(f"       WHY:   {why}")
            if how:
                print(f"       FIX:   {how}")
            if patch:
                print(f"       PATCH:\n{patch}")
            print()

    if usage:
        pt   = usage.get("prompt_tokens", 0)
        ct   = usage.get("completion_tokens", 0)
        cost = usage.get("cost_usd", 0)
        print(f"  Tokens: {pt+ct} ({pt} in / {ct} out) · ${cost:.5f}")

    print("=" * 70 + "\n")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Low Latency 101 — Production Profiler Agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python profiler_agent.py --pid 12345 --duration 30
  python profiler_agent.py --pid 12345 --lang python --duration 60 --top-n 5
  python profiler_agent.py --pid 12345 --api https://api-production-0435.up.railway.app
        """,
    )
    parser.add_argument("--pid",      type=int, required=True,  help="PID of the target process")
    parser.add_argument("--lang",     default="python",         help="Language: python (default)")
    parser.add_argument("--duration", type=int, default=30,     help="Profiling duration in seconds (default: 30)")
    parser.add_argument("--top-n",    type=int, default=5,      help="Number of hotspots to analyze (default: 5)")
    parser.add_argument("--api",      default="http://localhost:8000", help="API base URL")
    parser.add_argument("--no-source", action="store_true",     help="Skip reading local source files")
    args = parser.parse_args()

    lang = args.lang.lower()

    if lang not in ("python",):
        print(f"ERROR: --lang {lang} not yet supported in Phase A.")
        print("  Python -> use this script with py-spy")
        print("  Java   -> coming in Phase B (jfr_agent.py with async-profiler)")
        print("  C++    -> coming in Phase B (perf_agent.py with perf/eBPF)")
        sys.exit(1)

    # Check py-spy is installed
    check = subprocess.run(["py-spy", "--version"], capture_output=True, text=True)
    if check.returncode != 0:
        print("ERROR: py-spy not found. Install it:")
        print("  pip install py-spy")
        sys.exit(1)

    print(f"[profiler] Target PID: {args.pid}  Language: {lang}  Duration: {args.duration}s")
    print(f"[profiler] API: {args.api}")

    # Profile
    with tempfile.NamedTemporaryFile(suffix=".speedscope.json", delete=False) as tmp:
        outfile = tmp.name

    try:
        run_pyspy(args.pid, args.duration, outfile)

        print("[profiler] Parsing hotspots...")
        hotspots = parse_speedscope(outfile, top_n=args.top_n)

        if not hotspots:
            print("[profiler] No hotspots found. The process may have been idle.")
            sys.exit(0)

        print(f"[profiler] Top {len(hotspots)} hotspots:")
        for hs in hotspots:
            print(f"   {hs['pct_samples']:5.1f}%  {hs['function']}  ({hs['file']}:{hs['line']})")

        # Enrich with source context
        if not args.no_source:
            for hs in hotspots:
                hs["source_context"] = read_source_context(hs["file"], hs["line"])
                if hs["source_context"]:
                    print(f"[profiler]   ✓ source context read for {hs['function']}")
                else:
                    hs["source_context"] = ""

        # Submit
        print(f"\n[profiler] Submitting to {args.api}...")
        job_id = submit_job(args.api, lang, hotspots)
        print(f"[profiler] Job queued: {job_id}")
        print("[profiler] Waiting for analysis", end="", flush=True)

        result = poll_job(args.api, job_id)

        if result.get("status") == "error":
            print(f"ERROR: {result.get('error')}")
            sys.exit(1)

        print_results(result.get("result", {}))

    finally:
        try:
            os.unlink(outfile)
        except Exception:
            pass


if __name__ == "__main__":
    main()
