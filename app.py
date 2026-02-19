import json
import logging
import os

import streamlit as st
from dotenv import load_dotenv

from latency_engine import LatencyAnalyzer
from latency_engine.gpt_review import query_llm_with_code

# ---------- Logging ----------
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# ---------- Env ----------
load_dotenv()
api_key = os.getenv("OPENROUTER_API_KEY")


# ---------- Page ----------
st.set_page_config(page_title="Low Latency 101", layout="wide")
st.title("Universal Low Latency Runbook")
st.caption("Paste code → run static analysis → (optionally) ask GPT for latency-focused fixes")

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

# ---------- Right: Tabs ----------
with col_right:
    tab_static, tab_gpt, tab_runtime = st.tabs(
        ["Static Analyzer", "GPT Reviewer", "Run Code (coming soon)"]
    )

    # --- Tab 1: Static Analyzer ---
    with tab_static:
        analyze_btn = st.button("🔍 Run Static Analyzer", use_container_width=True)
        if analyze_btn:
            if not code_input.strip():
                st.warning("Paste your code first.")
            else:
                analyzer = LatencyAnalyzer(language)
                results = analyzer.analyze(code_input)

                st.success("Static analysis complete.")
                st.markdown(f"**Score:** `{results['score']}/100`")

                if results["issues"]:
                    with st.expander("Detected Issues", expanded=True):
                        for issue in results["issues"]:
                            st.error(f"• **{issue['rule']}** — {issue['message']}")
                else:
                    st.success("No major latency issues detected by the static rules.")

                # Positive signals
                try:
                    positives = (results.get("signals") or {}).get("positive") or []
                except Exception:
                    positives = []
                if positives:
                    with st.expander("Positive Signals (good patterns)", expanded=True):
                        for p in positives:
                            st.success(f"+ {p}")

    # --- Tab 2: GPT Reviewer ---
    with tab_gpt:
        gpt_btn = st.button("🤖 Run GPT Review", type="primary", use_container_width=True)
        if gpt_btn:
            if not code_input.strip():
                st.warning("Paste your code first.")
            elif not api_key:
                st.error("API key missing. Set `OPENROUTER_API_KEY` in your `.env` file.")
            else:
                with st.spinner("Asking the LLM for a concise latency review…"):
                    gpt_response = query_llm_with_code(code_input, language)

                # Hard errors (network/format) come back as "❌ ..."
                if isinstance(gpt_response, str) and gpt_response.startswith("❌"):
                    st.error(gpt_response)
                else:
                    # Try to parse structured JSON
                    try:
                        obj = json.loads(gpt_response)

                        # Summary / no_changes
                        if obj.get("no_changes", False):
                            st.success(f"✅ {obj.get('summary', 'Code looks good. No changes suggested.')}")
                        else:
                            st.markdown(f"**Summary:** {obj.get('summary', '').strip()}")

                        # Clean findings
                        clean = obj.get("clean_findings", [])
                        if clean:
                            with st.expander("🟢 Clean findings", expanded=True):
                                for c in clean:
                                    st.write(f"- {c}")

                        # Minor issues (tolerate strings or dicts)
                        minor = obj.get("minor_issues", [])
                        if minor:
                            with st.expander("🟡 Minor suggestions", expanded=True):
                                for m in minor:
                                    if isinstance(m, dict):
                                        issue = m.get("issue", "")
                                        why = m.get("why", "")
                                        fix = m.get("fix", "")
                                        st.markdown(f"- **{issue}** — {why}\n  - _Fix_: {fix}")
                                        if m.get("snippet"):
                                            st.code(m["snippet"], language=language.lower())
                                    else:
                                        st.write(f"- {m}")

                        # Major issues (tolerate strings or dicts)
                        major = obj.get("major_issues", [])
                        if major:
                            with st.expander("🔴 Major latency issues", expanded=True):
                                for m in major:
                                    if isinstance(m, dict):
                                        issue = m.get("issue", "")
                                        why = m.get("why", "")
                                        fix = m.get("fix", "")
                                        st.markdown(f"- **{issue}** — {why}\n  - _Fix_: {fix}")
                                        if m.get("snippet"):
                                            st.code(m["snippet"], language=language.lower())
                                    else:
                                        st.write(f"- {m}")

                        # Rewritten
                        if obj.get("rewritten"):
                            st.markdown("### ✍️ Rewritten (optimized)")
                            st.code(obj["rewritten"], language=language.lower())

                        # Narrative (raw markdown) if provided
                        if obj.get("raw_markdown"):
                            st.markdown("### 📝 Narrative")
                            st.markdown(obj["raw_markdown"]) 

                        # Confidence
                        if "confidence" in obj:
                            try:
                                st.caption(f"Model confidence: {float(obj['confidence']):.2f}")
                            except Exception:
                                pass

                    except Exception:
                        # Fallback: show raw text if model didn't return JSON
                        st.markdown("### LLM Suggestions")
                        st.markdown(gpt_response)

    # --- Tab 3: Runtime (placeholder) ---
    with tab_runtime:
        st.info("A secure sandbox to run code with input/output will land in the next sprint.")
        st.markdown("- Captures stdout/stderr and execution time\n- Test-case harness\n- Safe subprocess/container runtime")

# ---------- Footer ----------
st.markdown("---")
st.markdown("Built with ❤️ by Gauri • [GitHub](https://github.com/gauribhardwaj/Low-Latency-101)")

