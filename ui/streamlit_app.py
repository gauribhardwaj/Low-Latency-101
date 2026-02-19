import logging
import os
import time

import requests
import streamlit as st

# ---------- Logging ----------
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
            f"API: {'✅' if api_ok else '❌'} | "
            f"Worker: {'✅' if worker_ok else '❌'} | Queue: {worker.get('queue_len', '?')}"
        )
    except Exception:
        st.caption("API: ❌ (backend not reachable)")


def show_job_error(resp: dict, job_id: str) -> None:
    st.error(resp.get("error", "Unknown error"))
    st.caption(f"Job ID: {resp.get('job_id', job_id)}")
    if resp.get("hint"):
        st.caption(resp["hint"])
    st.markdown(f"[Check backend health]({API_BASE}/health)")
    st.markdown(f"[Check worker health]({API_BASE}/health/worker)")
    if resp.get("trace"):
        st.code(resp["trace"])


def submit_job(language: str, code: str, mode: str) -> str:
    payload = {
        "language": language.lower(),
        "code": code,
        "mode": mode,
        "context": {},
    }
    response = requests.post(f"{API_BASE}/jobs", json=payload, timeout=30)
    response.raise_for_status()
    return response.json()["job_id"]


def poll_job(job_id: str, timeout_s: int = 60) -> dict:
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
        time.sleep(0.3)
    return {
        "status": "error",
        "job_id": job_id,
        "error": f"Timed out waiting for job {job_id}. Worker may be down.",
        "hint": WORKER_HINT,
    }


# ---------- Page ----------
st.set_page_config(page_title="Low Latency 101", layout="wide")
st.title("Universal Low Latency Runbook")
st.caption("Paste code, run the release gate, and decide if it should merge.")

try:
    requests.get(f"{API_BASE}/health", timeout=2)
    st.caption("Backend: ✅ Connected")
except Exception:
    st.caption("Backend: ❌ Not reachable")

status_badge()

# ---------- Layout ----------
col_left, col_right = st.columns([1, 2], gap="large")

# ---------- Left: Editor ----------
with col_left:
    st.subheader("Code")
    language = st.selectbox("Language", ["Python", "Java", "C++"], index=0)
    code_input = st.text_area(
        "Paste your code",
        height=420,
        placeholder="Paste your Python / Java / C++ snippet here...",
    )

# ---------- Right: Release Gate ----------
with col_right:
    st.header("🚦 Release Readiness Gate")
    run_btn = st.button("🚦 Run Release Gate", type="primary", use_container_width=True)

if run_btn:
    if not code_input.strip():
        st.warning("Paste your code first.")
    else:
        with st.spinner("Submitting job to release gate worker..."):
            job_id = submit_job(language, code_input, mode="release_readiness")

        with st.spinner("Running release readiness gate..."):
            resp = poll_job(job_id, timeout_s=90)

        if resp.get("status") == "error":
            show_job_error(resp, job_id)
        else:
            out = resp["result"]

            gate = out["gate"]
            risk = out["risk_score"]
            gpt = out["gpt"]
            static = out["static"]

            if gate == "PASS":
                st.success(f"🟢 PASS — Risk Score: {risk}/100")
            elif gate == "WARN":
                st.warning(f"🟡 WARN — Risk Score: {risk}/100")
            else:
                st.error(f"🔴 FAIL — Risk Score: {risk}/100")

            major = gpt.get("major_issues", [])
            minor = gpt.get("minor_issues", [])
            clean = gpt.get("clean_findings", [])

            if major:
                st.subheader("🔴 Critical Fixes Required")
                for m in major:
                    st.markdown(f"- {m if isinstance(m, str) else m.get('issue', '')}")

            if minor:
                st.subheader("🟡 Improvements Recommended")
                for m in minor:
                    st.markdown(f"- {m if isinstance(m, str) else m.get('issue', '')}")

            if not major and not minor:
                st.subheader("🟢 No Immediate Latency Risks")
                for c in clean:
                    st.markdown(f"- {c}")

            with st.expander("🔎 Deep Technical Breakdown"):
                st.write("Static Analysis")
                st.json(static)
                st.write("GPT Raw Output")
                st.json(gpt)

# ---------- Footer ----------
st.markdown("---")
st.markdown("Built with ❤️ by Gauri • [GitHub](https://github.com/gauribhardwaj/Low-Latency-101)")
