import streamlit as st
from latency_engine import LatencyAnalyzer

st.set_page_config(page_title="Low Latency 101", layout="wide")

st.title("🚀 Universal Low Latency Runbook")
st.subheader("🔍 Paste code below to analyze for performance bottlenecks")

# Language selection
language = st.selectbox("Select Programming Language", ["Python", "Java", "C++"])

# Code input
code_input = st.text_area("Paste your code here", height=300, placeholder="Paste your snippet here...")

if st.button("Analyze Code"):
    if not code_input.strip():
        st.warning("⚠️ Please paste some code before analyzing.")
    else:
        analyzer = LatencyAnalyzer(language)
        results = analyzer.analyze(code_input)
        st.success("✅ Analysis Complete!")

        for res in results["issues"]:
            st.error(f"🚨 {res['rule']}: {res['message']}")

        st.markdown(f"### 🧪 Performance Score: `{results['score']}/100`")
