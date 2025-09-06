import streamlit as st
from latency_engine import LatencyAnalyzer
from latency_engine.gpt_review import query_llm_with_code
from dotenv import load_dotenv
import os
import logging

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load env vars
load_dotenv()
api_key = os.getenv("OPENROUTER_API_KEY")

#  Streamlit Page Config
st.set_page_config(page_title="Low Latency 101", layout="wide")

# --- Title ---
st.markdown("## 🚀 Universal Low Latency Runbook")
st.markdown("Optimize your code for speed, memory, and execution in one click.")


# --- Layout ---
col1, col2 = st.columns([1.5, 2.5])

# --- Left: Code Editor ---
with col1:
    st.markdown("### 📝 Code Snippet")
    language = st.selectbox("Language", ["Python", "Java", "C++"])
    code_input = st.text_area("Paste your code below", height=450, placeholder="Write or paste your code here...")

    run_analysis = st.button("🔍 Analyze Code")

# --- Right: Tabs ---
with col2:
    tab1, tab2, tab3 = st.tabs(["🧪 Static Analyzer", "🤖 GPT Reviewer", "⚙️ Run Code"])

    # --- Tab 1: Static Analyzer ---
    with tab1:
        if run_analysis:
            if not code_input.strip():
                st.warning("⚠️ Paste your code first.")
            else:
                analyzer = LatencyAnalyzer(language)
                results = analyzer.analyze(code_input)

                st.success("✅ Static Analysis Completed")
                st.markdown(f"**Score:** `{results['score']}/100`")

                if results["issues"]:
                    with st.expander("⚠️ Detected Issues"):
                        for issue in results["issues"]:
                            st.error(f"{issue['rule']}: {issue['message']}")
                else:
                    st.success("🎉 No major issues found.")

    # --- Tab 2: GPT Reviewer ---
    with tab2:
        if run_analysis:
            if not code_input.strip():
                st.warning("⚠️ Paste your code first.")
            elif not api_key:
                st.error("❌ API key missing in `.env`.")
            else:
                with st.spinner("Asking GPT to review..."):
                    gpt_response = query_llm_with_code(code_input, language)

                if gpt_response.startswith("✅"):
                    st.success(gpt_response)
                elif gpt_response.startswith("❌"):
                    st.error(gpt_response)
                else:
                    st.markdown("### 🧠 Suggestions")
                    st.code(gpt_response, language='markdown')

    # --- Tab 3: Runtime Tester (placeholder for Phase 2) ---
    with tab3:
        st.info("⚙️ Runtime test environment coming soon in Sprint 2 Phase 2.")
        st.markdown("- Secure code runner")
        st.markdown("- Output + Error box")
        st.markdown("- Input parameters")