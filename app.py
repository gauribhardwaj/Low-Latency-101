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

# Page setup
st.set_page_config(page_title="Low Latency 101", layout="wide")
st.title("🚀 Universal Low Latency Runbook")
st.subheader("🔍 Paste your code below for a low-latency performance review")

# Language & Code
language = st.selectbox("Select Programming Language", ["Python", "Java", "C++"])
code_input = st.text_area("Paste your code here", height=300)

# Track button click via session_state
if "analyze_clicked" not in st.session_state:
    st.session_state["analyze_clicked"] = False

# Main button
if st.button("🧠 Analyze Code"):
    st.session_state["analyze_clicked"] = True

# After Analyze Button is clicked
if st.session_state["analyze_clicked"]:

    if not code_input.strip():
        st.warning("⚠️ Please paste some code before analyzing.")
        st.session_state["analyze_clicked"] = False  # Reset state
    else:
        analyzer = LatencyAnalyzer(language)
        results = analyzer.analyze(code_input)

        st.success("✅ Static Analysis Completed!")

        if results["issues"]:
            st.markdown("### 🔥 Latency Issues Detected")
            for issue in results["issues"]:
                st.error(f"🚨 {issue['rule']}: {issue['message']}")
        else:
            st.success("🎉 No major latency issues detected!")

        st.markdown(f"### 🧪 Performance Score: `{results['score']}/100`")

        # GPT Review checkbox appears AFTER static analysis
        enable_gpt = st.checkbox("🤖 Enhance with GPT Review (DeepSeek via OpenRouter)")

        if enable_gpt:
            logger.info("🤖 GPT checkbox is selected, calling LLM...")
            if not api_key:
                st.error("❌ API key not found.")
            else:
                with st.spinner("💬 Asking DeepSeek for a review..."):
                    try:
                        gpt_response = query_llm_with_code(code_input, language)
                        if gpt_response.startswith("❌"):
                            st.error(gpt_response)
                        else:
                            st.markdown("### 🤖 DeepSeek LLM Suggestions")
                            st.code(gpt_response)
                    except Exception as e:
                        st.error(f"❌ GPT call failed: {e}")
                        logger.exception("GPT call failed")

# Footer
st.markdown("---")
st.markdown("Built with ❤️ by Gauri | [GitHub Repo](https://github.com/gauribhardwaj/Low-Latency-101)")
