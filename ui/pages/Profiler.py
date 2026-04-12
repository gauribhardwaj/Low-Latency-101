"""
Low Latency 101 — Production Profiler Dashboard
A full-page dashboard for uploading and analyzing speedscope profiles.
"""
import json
import os
import time
from typing import Any, Dict, List

import requests
import streamlit as st

try:
    import plotly.graph_objects as go
    HAS_PLOTLY = True
except ImportError:
    HAS_PLOTLY = False

API_BASE  = os.getenv("API_BASE", "http://localhost:8000")
POLL_HINT = "docker compose logs worker --tail 80"

st.set_page_config(
    page_title="Profiler — Low Latency 101",
    layout="wide",
    page_icon="🔬",
    initial_sidebar_state="collapsed",
)

# ── Session state ──────────────────────────────────────────────────────────
for k, v in [("prof_result", None), ("prof_hotspots", None), ("prof_err", None),
             ("prof_lang", "Python"), ("prof_analyzed", False)]:
    if k not in st.session_state:
        st.session_state[k] = v

# ── CSS ────────────────────────────────────────────────────────────────────
st.markdown("""<style>
#MainMenu, footer, [data-testid="stToolbar"],
[data-testid="stDecoration"] { display:none !important; }
html,[data-testid="stAppViewContainer"]{background:#0d1117 !important;}
.main .block-container{padding:1rem 1.5rem 0 1.5rem !important;max-width:100% !important;}

[data-testid="stSelectbox"]>div>div,
[data-testid="stTextArea"] textarea,
[data-testid="stTextInput"]>div>div>input{
  background:#161b22 !important;border:1px solid #30363d !important;
  border-radius:8px !important;color:#e6edf3 !important;
  font-family:'JetBrains Mono',monospace !important;font-size:.83rem !important;}

[data-testid="stSelectbox"]>label p,
[data-testid="stTextArea"]>label p,
[data-testid="stTextInput"]>label p{
  font-size:.68rem !important;font-weight:700 !important;color:#484f58 !important;
  font-family:monospace !important;text-transform:uppercase !important;
  letter-spacing:.08em !important;}

div[data-testid="stButton"]>button{
  background:linear-gradient(135deg,#00d4ff,#00ff88) !important;
  color:#0d1117 !important;font-weight:800 !important;font-size:.9rem !important;
  border:none !important;border-radius:8px !important;
  padding:.6rem 1rem !important;width:100% !important;
  font-family:monospace !important;letter-spacing:.05em !important;
  transition:opacity .15s,transform .1s !important;margin-top:.5rem !important;}
div[data-testid="stButton"]>button:hover{opacity:.88 !important;transform:translateY(-1px) !important;}

/* metric card */
.mc{background:#161b22;border:1px solid #21262d;border-radius:10px;
    padding:1rem 1.2rem;text-align:center;}
.mc-val{font-size:2rem;font-weight:900;font-family:monospace;line-height:1.1;}
.mc-lab{font-size:.6rem;font-weight:700;letter-spacing:.12em;text-transform:uppercase;
        color:#484f58;font-family:monospace;margin-top:.3rem;}

/* hotspot fix card */
.hfc{background:#161b22;border:1px solid #21262d;border-left:3px solid #f85149;
     border-radius:8px;padding:.9rem 1.1rem;margin-bottom:.6rem;}
.hfc-head{display:flex;justify-content:space-between;align-items:center;margin-bottom:.5rem;}
.hfc-fn{font-size:.9rem;font-weight:700;color:#e6edf3;font-family:monospace;}
.hfc-pct{font-size:1.1rem;font-weight:900;font-family:monospace;}
.hfc-loc{font-size:.7rem;color:#484f58;font-family:monospace;margin-bottom:.6rem;}
.hfc-label{font-size:.6rem;font-weight:800;letter-spacing:.12em;text-transform:uppercase;
           font-family:monospace;margin:.5rem 0 .2rem;}
.hfc-label.why{color:#e3b341;}.hfc-label.fix{color:#00d4ff;}.hfc-label.patch{color:#3fb950;}
.hfc-text{font-size:.8rem;color:#8b949e;line-height:1.6;}

/* nav brand */
.brand{font-size:1rem;font-weight:800;
  background:linear-gradient(90deg,#00d4ff,#00ff88);
  -webkit-background-clip:text;-webkit-text-fill-color:transparent;
  background-clip:text;font-family:monospace;}
.pill{display:inline-flex;align-items:center;gap:.28rem;padding:.18rem .55rem;
      border-radius:999px;font-size:.65rem;font-weight:700;font-family:monospace;}
.ok{background:#0d2818;color:#3fb950;border:1px solid #238636;}
.dn{background:#3d1212;color:#f85149;border:1px solid #da3633;}
.qt{background:#161b22;color:#8b949e;border:1px solid #30363d;}
.dot{width:5px;height:5px;border-radius:50%;background:currentColor;}

/* cli box */
.cli-box{background:#0a1220;border:1px solid #1d3557;border-radius:8px;
         padding:.85rem 1rem;margin-bottom:.75rem;}
.cli-title{font-size:.65rem;font-weight:800;color:#00d4ff;font-family:monospace;
           letter-spacing:.1em;margin-bottom:.5rem;}
.cli-body{font-size:.74rem;color:#8b949e;font-family:monospace;line-height:1.9;}
.cli-cmd{color:#e6edf3;}

/* section label */
.sl{font-size:.6rem;font-weight:800;letter-spacing:.14em;text-transform:uppercase;
    font-family:monospace;margin:.9rem 0 .4rem;}
.sl.c{color:#f85149;}.sl.m{color:#e3b341;}.sl.g{color:#3fb950;}

[data-testid="stExpander"] details{background:#161b22 !important;border:1px solid #21262d !important;border-radius:8px !important;}
summary{font-family:monospace !important;font-size:.78rem !important;color:#8b949e !important;}
[data-testid="column"]:nth-child(2){border-left:1px solid #21262d !important;padding-left:1.5rem !important;}
</style>""", unsafe_allow_html=True)


# ── Helpers ────────────────────────────────────────────────────────────────
def _status():
    try:
        h = requests.get(f"{API_BASE}/health", timeout=1).json()
        w = requests.get(f"{API_BASE}/health/worker", timeout=1).json()
        return {"api": h.get("status") == "ok",
                "worker": w.get("worker_heartbeat") is not None}
    except Exception:
        return {"api": False, "worker": False}


def parse_speedscope(data: dict, top_n: int = 10) -> List[Dict[str, Any]]:
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
            "source_context": "",
        }
        for i, w in ranked
    ]


def submit_profile(lang: str, hotspots: list) -> str:
    r = requests.post(f"{API_BASE}/jobs", json={
        "language": lang.lower(), "code": "", "mode": "runtime_profile",
        "context": {"source": "runtime_profile", "hotspots": hotspots},
    }, timeout=30)
    r.raise_for_status()
    return r.json()["job_id"]


def poll(jid: str, timeout: int = 180) -> dict:
    end = time.time() + timeout
    while time.time() < end:
        try:
            d = requests.get(f"{API_BASE}/jobs/{jid}", timeout=10).json()
            if d.get("status") in ("done", "error"):
                return d
        except Exception as e:
            return {"status": "error", "error": str(e)}
        time.sleep(0.5)
    return {"status": "error", "error": "Timed out waiting for analysis."}


def _bar_color(pct: float) -> str:
    if pct >= 60:
        return "#f85149"
    if pct >= 25:
        return "#e3b341"
    return "#3fb950"


# ── Flame chart ────────────────────────────────────────────────────────────
def render_flame_chart(hotspots: List[Dict]) -> None:
    if not HAS_PLOTLY:
        st.warning("Install plotly for the flame chart: `pip install plotly`")
        return

    fns   = [h["function"][:40] for h in reversed(hotspots)]
    pcts  = [h["pct_samples"] for h in reversed(hotspots)]
    colors = [_bar_color(p) for p in pcts]
    labels = [f"{p}%" for p in pcts]

    fig = go.Figure(go.Bar(
        x=pcts,
        y=fns,
        orientation="h",
        marker_color=colors,
        text=labels,
        textposition="outside",
        textfont=dict(family="JetBrains Mono, monospace", size=11, color="#8b949e"),
        hovertemplate="<b>%{y}</b><br>%{x:.1f}% CPU<extra></extra>",
    ))

    fig.update_layout(
        paper_bgcolor="#0d1117",
        plot_bgcolor="#0d1117",
        margin=dict(l=0, r=60, t=10, b=10),
        height=max(160, len(hotspots) * 42),
        xaxis=dict(
            range=[0, 115],
            showgrid=True,
            gridcolor="#161b22",
            gridwidth=1,
            tickfont=dict(family="monospace", size=10, color="#484f58"),
            ticksuffix="%",
            zeroline=False,
            showline=False,
        ),
        yaxis=dict(
            tickfont=dict(family="JetBrains Mono, monospace", size=11, color="#8b949e"),
            showgrid=False,
            zeroline=False,
            showline=False,
        ),
        bargap=0.35,
        showlegend=False,
    )

    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


# ── Fix cards ──────────────────────────────────────────────────────────────
def render_fix_cards(fixes: List[Dict], lang: str) -> None:
    for fix in fixes:
        fn    = fix.get("function", "?")
        pct   = fix.get("pct_samples", "?")
        fp    = fix.get("file", "")
        ln    = fix.get("line", "")
        why   = fix.get("why", "")
        how   = fix.get("fix", "")
        patch = fix.get("patch", "")

        pct_f  = float(pct) if isinstance(pct, (int, float)) else 0
        col    = _bar_color(pct_f)

        loc_str = f"{fp}:{ln}" if fp and fp != "<string>" else ""

        st.markdown(f"""
        <div class="hfc">
          <div class="hfc-head">
            <span class="hfc-fn">{fn}</span>
            <span class="hfc-pct" style="color:{col}">{pct}%</span>
          </div>
          {"" if not loc_str else f'<div class="hfc-loc">{loc_str}</div>'}
        </div>
        """, unsafe_allow_html=True)

        if why:
            st.markdown('<div class="hfc-label why">WHY</div>', unsafe_allow_html=True)
            st.markdown(f'<div class="hfc-text">{why}</div>', unsafe_allow_html=True)
        if how:
            st.markdown('<div class="hfc-label fix">FIX</div>', unsafe_allow_html=True)
            st.markdown(f'<div class="hfc-text">{how}</div>', unsafe_allow_html=True)
        if patch and patch.strip() not in ("pass", ""):
            st.markdown('<div class="hfc-label patch">PATCH</div>', unsafe_allow_html=True)
            st.code(patch, language=lang or None)

        st.markdown('<div style="height:.4rem"></div>', unsafe_allow_html=True)


# ── NAV ─────────────────────────────────────────────────────────────────────
s = _status()
pill = lambda l, ok: f'<span class="pill {"ok" if ok else "dn"}"><span class="dot"></span>{l}</span>'
nav_l, nav_r = st.columns([1, 1])
with nav_l:
    st.markdown(
        '<div style="padding:.4rem 0">'
        '<span class="brand">⚡ Low Latency 101</span>'
        '<span style="color:#484f58;font-family:monospace;font-size:.75rem;margin-left:.6rem">'
        '/ Production Profiler</span></div>',
        unsafe_allow_html=True,
    )
with nav_r:
    st.markdown(
        f'<div style="display:flex;gap:.4rem;justify-content:flex-end;padding:.4rem 0">'
        f'{pill("API", s["api"])}{pill("Worker", s["worker"])}</div>',
        unsafe_allow_html=True,
    )

st.markdown('<div style="height:1px;background:#21262d;margin:.25rem 0 .9rem"></div>',
            unsafe_allow_html=True)

# ── MAIN ─────────────────────────────────────────────────────────────────────
left, right = st.columns([3, 7], gap="medium")

# ── LEFT — controls ──────────────────────────────────────────────────────────
with left:
    # CLI instructions
    st.markdown("""
    <div class="cli-box">
      <div class="cli-title">OPTION A — CLI (live process)</div>
      <div class="cli-body">
        On the machine running your service:<br>
        <span class="cli-cmd">pip install py-spy requests</span><br><br>
        <span class="cli-cmd">python services/profiler/profiler_agent.py \\<br>
        &nbsp;&nbsp;--pid &lt;PID&gt; --duration 30 \\<br>
        &nbsp;&nbsp;--api https://api-production-0435.up.railway.app</span><br><br>
        Or record a file for upload below:<br>
        <span class="cli-cmd">py-spy record --pid &lt;PID&gt; \\<br>
        &nbsp;&nbsp;--format speedscope \\<br>
        &nbsp;&nbsp;--output profile.json \\<br>
        &nbsp;&nbsp;--duration 30 --nonblocking</span>
      </div>
    </div>
    <div style="font-size:.65rem;font-weight:800;color:#484f58;font-family:monospace;
                letter-spacing:.1em;margin:.2rem 0 .5rem">
      OPTION B — UPLOAD SPEEDSCOPE JSON
    </div>
    """, unsafe_allow_html=True)

    prof_lang = st.selectbox("Language", ["Python", "Java", "C++"],
                             index=["Python","Java","C++"].index(st.session_state.prof_lang),
                             key="prof_lang_sel")
    st.session_state.prof_lang = prof_lang

    top_n = st.slider("Hotspots to analyze", 3, 15, 8)

    uploaded = st.file_uploader(
        "Drop speedscope JSON here",
        type=["json"],
        key="prof_upload",
        help="Generated by: py-spy record --format speedscope",
    )

    # Parse on upload (before clicking analyze)
    if uploaded is not None:
        try:
            raw = json.loads(uploaded.read())
            hotspots = parse_speedscope(raw, top_n=top_n)
            st.session_state.prof_hotspots = hotspots
            st.session_state.prof_analyzed = False
        except Exception as e:
            st.error(f"Failed to parse: {e}")
            st.session_state.prof_hotspots = None

    # Preview parsed hotspots before analysis
    if st.session_state.prof_hotspots and not st.session_state.prof_analyzed:
        hs = st.session_state.prof_hotspots
        st.markdown('<div class="sl m">◆ Parsed — ready to analyze</div>', unsafe_allow_html=True)
        for h in hs:
            col = _bar_color(h["pct_samples"])
            st.markdown(
                f'<div style="font-family:monospace;font-size:.75rem;padding:.12rem 0;">'
                f'<span style="color:{col};font-weight:700">{h["pct_samples"]:5.1f}%</span>'
                f'  <span style="color:#8b949e">{h["function"]}</span></div>',
                unsafe_allow_html=True,
            )

    if st.button("🔬  Analyze with LLM", key="run_prof"):
        if not st.session_state.prof_hotspots:
            st.warning("Upload a speedscope JSON file first.")
        else:
            with st.spinner("Analyzing hotspots..."):
                try:
                    jid  = submit_profile(prof_lang, st.session_state.prof_hotspots)
                    resp = poll(jid, 180)
                    if resp.get("status") == "error":
                        st.session_state.prof_err    = resp.get("error", "Unknown error")
                        st.session_state.prof_result = None
                    else:
                        r = resp.get("result", {})
                        r["language"] = prof_lang.lower()
                        st.session_state.prof_result  = r
                        st.session_state.prof_err     = None
                        st.session_state.prof_analyzed = True
                except Exception as e:
                    st.session_state.prof_err = str(e)
            st.rerun()

# ── RIGHT — results ───────────────────────────────────────────────────────────
with right:
    if st.session_state.prof_err:
        st.error(st.session_state.prof_err)

    elif st.session_state.prof_result:
        out   = st.session_state.prof_result
        fixes = out.get("hotspot_fixes", [])
        usage = out.get("_usage", {})
        lang  = out.get("language", "") or ""

        # ── Metric cards ─────────────────────────────────────────────────
        top_pct  = fixes[0]["pct_samples"] if fixes else "—"
        top_fn   = fixes[0]["function"][:22] if fixes else "—"
        n_fixes  = len(fixes)
        pt       = usage.get("prompt_tokens", 0)
        ct       = usage.get("completion_tokens", 0)
        cost     = usage.get("cost_usd", 0)
        cost_str = f"${cost:.5f}" if cost else "—"

        m1, m2, m3 = st.columns(3)
        with m1:
            st.markdown(
                f'<div class="mc"><div class="mc-val" style="color:#f85149">{top_pct}%</div>'
                f'<div class="mc-lab">top bottleneck</div>'
                f'<div style="font-size:.65rem;color:#484f58;font-family:monospace;'
                f'margin-top:.2rem;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">'
                f'{top_fn}</div></div>',
                unsafe_allow_html=True,
            )
        with m2:
            st.markdown(
                f'<div class="mc"><div class="mc-val" style="color:#e3b341">{n_fixes}</div>'
                f'<div class="mc-lab">hotspots analyzed</div>'
                f'<div style="font-size:.65rem;color:#484f58;font-family:monospace;margin-top:.2rem">'
                f'{pt+ct} tokens</div></div>',
                unsafe_allow_html=True,
            )
        with m3:
            st.markdown(
                f'<div class="mc"><div class="mc-val" style="color:#3fb950">{cost_str}</div>'
                f'<div class="mc-lab">query cost</div>'
                f'<div style="font-size:.65rem;color:#484f58;font-family:monospace;margin-top:.2rem">'
                f'{pt} in / {ct} out</div></div>',
                unsafe_allow_html=True,
            )

        st.markdown('<div style="height:.75rem"></div>', unsafe_allow_html=True)

        # ── Summary ───────────────────────────────────────────────────────
        summary = out.get("summary", "")
        if summary:
            st.markdown(
                f'<div style="background:#161b22;border:1px solid #21262d;border-radius:8px;'
                f'padding:.75rem 1rem;font-size:.82rem;color:#8b949e;font-family:monospace;'
                f'margin-bottom:.75rem">{summary}</div>',
                unsafe_allow_html=True,
            )

        # ── Flame chart ───────────────────────────────────────────────────
        hotspots_for_chart = st.session_state.prof_hotspots or []
        if hotspots_for_chart:
            st.markdown('<div class="sl c">⬤ CPU Time Distribution</div>', unsafe_allow_html=True)
            render_flame_chart(hotspots_for_chart)

        # ── Fix cards ─────────────────────────────────────────────────────
        if fixes:
            st.markdown('<div class="sl c" style="margin-top:1rem">⬤ Hotspot Fixes</div>',
                        unsafe_allow_html=True)
            render_fix_cards(fixes, lang)

        with st.expander("Raw JSON"):
            st.json(out)

    elif st.session_state.prof_hotspots and not st.session_state.prof_analyzed:
        # Flame preview before LLM analysis
        hs = st.session_state.prof_hotspots
        st.markdown('<div class="sl m">◆ CPU Time Distribution — click Analyze to get fixes</div>',
                    unsafe_allow_html=True)
        render_flame_chart(hs)

    else:
        st.markdown("""
        <div style="display:flex;flex-direction:column;align-items:center;justify-content:center;
                    min-height:65vh;text-align:center;gap:.6rem;">
          <div style="font-size:2.5rem;opacity:.1">🔬</div>
          <div style="font-size:.9rem;font-weight:700;color:#30363d;font-family:monospace">
            Upload a speedscope profile to begin
          </div>
          <div style="font-size:.74rem;color:#21262d;max-width:320px;line-height:1.7;">
            Generate one with<br>
            <span style="color:#30363d">py-spy record --format speedscope --output profile.json</span><br>
            or use the CLI agent to profile a live PID.
          </div>
        </div>
        """, unsafe_allow_html=True)

st.markdown('<div style="height:1px;background:#21262d;margin:1rem 0 0"></div>',
            unsafe_allow_html=True)
st.markdown(
    '<div style="text-align:center;padding:.75rem;color:#30363d;'
    'font-size:.65rem;font-family:monospace">'
    'Low-Latency-101 · built for engineers who care about microseconds</div>',
    unsafe_allow_html=True,
)
