import logging
import os
import time
from typing import Any, Dict, List

import requests
import streamlit as st

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

API_BASE = os.getenv("API_BASE", "http://localhost:8000")
WORKER_HINT = "Run: docker compose ps && docker compose logs worker --tail 80"


def status_badge() -> None:
    try:
        health = requests.get(f"{API_BASE}/health", timeout=1).json()
        worker = requests.get(f"{API_BASE}/health/worker", timeout=1).json()
        worker_ok = worker.get("worker_heartbeat") is not None
        api_ok = health.get("status") == "ok"
        st.caption(
            f"API: {'OK' if api_ok else 'DOWN'} | "
            f"Worker: {'OK' if worker_ok else 'DOWN'} | Queue: {worker.get('queue_len', '?')}"
        )
    except Exception:
        st.caption("API: DOWN (backend not reachable)")


def show_job_error(resp: dict, job_id: str) -> None:
    st.error(resp.get("error", "Unknown error"))
    st.caption(f"Job ID: {resp.get('job_id', job_id)}")
    if resp.get("hint"):
        st.caption(resp["hint"])
    st.markdown(f"[Check backend health]({API_BASE}/health)")
    st.markdown(f"[Check worker health]({API_BASE}/health/worker)")
    if resp.get("trace"):
        st.code(resp["trace"])


def submit_code_job(language: str, code: str, mode: str) -> str:
    payload = {
        "language": language.lower(),
        "code": code,
        "mode": mode,
        "context": {"source": "code"},
    }
    response = requests.post(f"{API_BASE}/jobs", json=payload, timeout=30)
    response.raise_for_status()
    return response.json()["job_id"]


def submit_github_job(
    repo_url: str,
    ref: str,
    paths: List[str],
    extensions: List[str],
    max_files: int,
    base_ref: str,
    head_ref: str,
    mode: str,
) -> str:
    payload: Dict[str, Any] = {
        "repo_url": repo_url,
        "ref": ref,
        "paths": paths,
        "extensions": extensions,
        "max_files": max_files,
        "mode": mode,
    }
    if base_ref.strip():
        payload["base_ref"] = base_ref.strip()
    if head_ref.strip():
        payload["head_ref"] = head_ref.strip()

    response = requests.post(f"{API_BASE}/jobs/github", json=payload, timeout=30)
    response.raise_for_status()
    return response.json()["job_id"]


def poll_job(job_id: str, timeout_s: int = 90) -> dict:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            response = requests.get(f"{API_BASE}/jobs/{job_id}", timeout=10)
            response.raise_for_status()
            data = response.json()
            if data.get("status") in ("done", "error"):
                return data
        except Exception as exc:
            return {
                "status": "error",
                "job_id": job_id,
                "error": f"Failed while polling job {job_id}: {exc}",
                "hint": WORKER_HINT,
            }
        time.sleep(0.4)
    return {
        "status": "error",
        "job_id": job_id,
        "error": f"Timed out waiting for job {job_id}. Worker may be down.",
        "hint": WORKER_HINT,
    }


def parse_csv_lines(raw: str) -> List[str]:
    out: List[str] = []
    for line in raw.splitlines():
        for part in line.split(","):
            value = part.strip()
            if value:
                out.append(value)
    return out


def render_gate(out: Dict[str, Any]) -> None:
    gate = out.get("gate", "WARN")
    risk = int(out.get("risk_score", 0))
    if gate == "PASS":
        st.success(f"PASS - Risk Score: {risk}/100")
    elif gate == "WARN":
        st.warning(f"WARN - Risk Score: {risk}/100")
    else:
        st.error(f"FAIL - Risk Score: {risk}/100")


def format_issue_text(item: Any) -> str:
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        issue = str(item.get("issue", "")).strip()
        fix = str(item.get("fix", "")).strip()
        file_path = str(item.get("file", "")).strip()
        text = issue or str(item)
        if fix:
            text = f"{text} -> {fix}"
        if file_path:
            text = f"{file_path}: {text}"
        return text
    return str(item)


def render_github_results(out: Dict[str, Any]) -> None:
    github_meta = out.get("github", {})
    if github_meta:
        st.caption(
            "Repo: "
            f"{github_meta.get('repo', github_meta.get('repo_url', 'unknown'))} @ {github_meta.get('ref', 'main')} | "
            f"Analyzed files: {github_meta.get('analyzed_file_count', 0)}"
        )

    top_actions = out.get("top_actions", [])
    if top_actions:
        st.subheader("Top actions")
        for action in top_actions:
            st.markdown(f"- {action}")

    hotspots = out.get("hotspots", [])
    if hotspots:
        st.subheader("Hotspot files")
        rows = []
        for item in hotspots:
            rows.append(
                {
                    "path": item.get("path"),
                    "lang": item.get("language"),
                    "issues": item.get("issue_count", 0),
                    "major": item.get("major_count", 0),
                    "minor": item.get("minor_count", 0),
                    "risk_points": item.get("risk_points", 0),
                }
            )
        st.dataframe(rows, use_container_width=True, hide_index=True)

    files = out.get("files", [])
    if files:
        st.subheader("Drill-down")
        for file_item in files:
            title = (
                f"{file_item.get('path')} | "
                f"issues: {file_item.get('issue_count', 0)} "
                f"(major {file_item.get('major_count', 0)}, minor {file_item.get('minor_count', 0)})"
            )
            with st.expander(title):
                file_gpt = file_item.get("gpt")
                if file_gpt:
                    majors = file_gpt.get("major_issues", [])
                    minors = file_gpt.get("minor_issues", [])
                    if majors:
                        st.markdown("Major findings")
                        for finding in majors[:5]:
                            st.markdown(f"- {format_issue_text(finding)}")
                    if minors:
                        st.markdown("Minor findings")
                        for finding in minors[:5]:
                            st.markdown(f"- {format_issue_text(finding)}")
                st.caption("Static output")
                st.json(file_item.get("static", {}))


def render_code_results(out: Dict[str, Any]) -> None:
    gpt = out.get("gpt", {})
    major = gpt.get("major_issues", [])
    minor = gpt.get("minor_issues", [])
    clean = gpt.get("clean_findings", [])

    if major:
        st.subheader("Critical fixes required")
        for item in major:
            st.markdown(f"- {format_issue_text(item)}")

    if minor:
        st.subheader("Improvements recommended")
        for item in minor:
            st.markdown(f"- {format_issue_text(item)}")

    if not major and not minor:
        st.subheader("No immediate latency risks")
        for item in clean:
            st.markdown(f"- {item}")

    with st.expander("Deep technical breakdown"):
        st.write("Static analysis")
        st.json(out.get("static", {}))
        st.write("GPT raw output")
        st.json(gpt)


st.set_page_config(page_title="Low Latency 101", layout="wide")
st.title("Universal Low Latency Runbook")
st.caption("Paste code or analyze a public GitHub repo with scoped release gating.")

try:
    requests.get(f"{API_BASE}/health", timeout=2)
    st.caption("Backend: Connected")
except Exception:
    st.caption("Backend: Not reachable")

status_badge()

col_left, col_right = st.columns([1, 2], gap="large")

with col_left:
    st.subheader("Source")
    source_mode = st.radio("Analyze from", ["Paste code", "GitHub repo"], index=0)

    language = "Python"
    code_input = ""
    repo_url = ""
    ref = "main"
    max_files = 30
    dirs_raw = ""
    ext_raw = ".py,.java,.cpp"
    base_ref = ""
    head_ref = ""
    scope_mode = "Top N files"

    if source_mode == "Paste code":
        language = st.selectbox("Language", ["Python", "Java", "C++"], index=0)
        code_input = st.text_area(
            "Paste your code",
            height=420,
            placeholder="Paste your Python / Java / C++ snippet here...",
        )
    else:
        repo_url = st.text_input("Repo URL", placeholder="https://github.com/owner/repo")
        ref = st.text_input("Ref", value="main", help="Branch, tag, or commit SHA")
        scope_mode = st.radio("Scope", ["Top N files", "Only these directories"], index=0)
        max_files = int(st.number_input("Top N files", min_value=1, max_value=200, value=30, step=1))

        if scope_mode == "Only these directories":
            dirs_raw = st.text_area(
                "Directories",
                value="src/",
                height=100,
                help="Comma or newline separated, e.g. src/, app/",
            )

        ext_raw = st.text_input(
            "Extensions",
            value=".py,.java,.cpp",
            help="Comma separated. Example: .py,.java,.cpp",
        )

        st.caption("Optional PR diff scope")
        col_b, col_h = st.columns(2)
        with col_b:
            base_ref = st.text_input("Base ref", value="")
        with col_h:
            head_ref = st.text_input("Head ref", value="")

with col_right:
    st.header("Release Readiness Gate")
    run_btn = st.button("Run Release Gate", type="primary", use_container_width=True)

if run_btn:
    if source_mode == "Paste code":
        if not code_input.strip():
            st.warning("Paste your code first.")
        else:
            with st.spinner("Submitting code job..."):
                job_id = submit_code_job(language, code_input, mode="release_readiness")
            with st.spinner("Running release gate..."):
                resp = poll_job(job_id, timeout_s=90)

            if resp.get("status") == "error":
                show_job_error(resp, job_id)
            else:
                out = resp.get("result", {})
                render_gate(out)
                render_code_results(out)
    else:
        if not repo_url.strip():
            st.warning("Enter a GitHub repo URL first.")
        else:
            paths = parse_csv_lines(dirs_raw) if scope_mode == "Only these directories" else []
            extensions = parse_csv_lines(ext_raw)

            with st.spinner("Submitting GitHub repo job..."):
                job_id = submit_github_job(
                    repo_url=repo_url.strip(),
                    ref=ref.strip() or "main",
                    paths=paths,
                    extensions=extensions,
                    max_files=max_files,
                    base_ref=base_ref,
                    head_ref=head_ref,
                    mode="release_readiness",
                )
            with st.spinner("Fetching files and running release gate..."):
                resp = poll_job(job_id, timeout_s=180)

            if resp.get("status") == "error":
                show_job_error(resp, job_id)
            else:
                out = resp.get("result", {})
                render_gate(out)
                summary = out.get("gpt", {}).get("summary", "")
                if summary:
                    st.caption(summary)
                render_github_results(out)
                with st.expander("Deep technical breakdown"):
                    st.write("Static analysis")
                    st.json(out.get("static", {}))
                    st.write("GPT output")
                    st.json(out.get("gpt", {}))

st.markdown("---")
st.markdown("Built for Low-Latency-101")
