import logging
import os
import time

import requests
import streamlit as st

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

API_BASE  = os.getenv("API_BASE", "http://localhost:8000")
POLL_HINT = "docker compose logs worker --tail 80"

st.set_page_config(page_title="Low Latency 101", layout="wide",
                   page_icon="⚡", initial_sidebar_state="collapsed")

# ── Session state ──────────────────────────────────────────────────────────
for k, v in [("result", None), ("source_tag", None), ("err", None)]:
    if k not in st.session_state:
        st.session_state[k] = v

# ── CSS ────────────────────────────────────────────────────────────────────
st.markdown("""<style>
/* base */
#MainMenu, footer, [data-testid="stToolbar"],
[data-testid="stDecoration"] { display:none !important; }
html,[data-testid="stAppViewContainer"]{background:#0d1117 !important;}
.main .block-container{padding:1rem 1.5rem 0 1.5rem !important;max-width:100% !important;}

/* inputs */
[data-testid="stSelectbox"]>div>div,
[data-testid="stTextArea"] textarea,
[data-testid="stTextInput"]>div>div>input,
[data-testid="stNumberInput"] input{
  background:#161b22 !important;border:1px solid #30363d !important;
  border-radius:8px !important;color:#e6edf3 !important;
  font-family:'JetBrains Mono',monospace !important;font-size:.83rem !important;}
[data-testid="stTextArea"] textarea:focus,
[data-testid="stTextInput"]>div>div>input:focus{
  border-color:#00d4ff !important;box-shadow:0 0 0 2px rgba(0,212,255,.12) !important;}

/* labels */
[data-testid="stSelectbox"]>label p,
[data-testid="stTextArea"]>label p,
[data-testid="stTextInput"]>label p,
[data-testid="stNumberInput"]>label p{
  font-size:.68rem !important;font-weight:700 !important;color:#484f58 !important;
  font-family:monospace !important;text-transform:uppercase !important;
  letter-spacing:.08em !important;}

/* run button */
div[data-testid="stButton"]>button{
  background:linear-gradient(135deg,#00d4ff,#00ff88) !important;
  color:#0d1117 !important;font-weight:800 !important;font-size:.9rem !important;
  border:none !important;border-radius:8px !important;
  padding:.6rem 1rem !important;width:100% !important;
  font-family:monospace !important;letter-spacing:.05em !important;
  transition:opacity .15s,transform .1s !important;margin-top:.5rem !important;}
div[data-testid="stButton"]>button:hover{opacity:.88 !important;transform:translateY(-1px) !important;}

/* segmented control (radio) */
div[data-testid="stRadio"]>label{display:none !important;}
div[data-testid="stRadio"] div[role="radiogroup"]{
  background:#161b22;border:1px solid #30363d;border-radius:9px;
  padding:3px;gap:3px;width:100%;}
div[data-testid="stRadio"] div[role="radiogroup"] label{
  flex:1 !important;justify-content:center !important;border-radius:7px !important;
  padding:.42rem .75rem !important;font-family:monospace !important;
  font-weight:700 !important;font-size:.8rem !important;color:#8b949e !important;
  cursor:pointer !important;transition:all .15s !important;}
div[data-testid="stRadio"] div[role="radiogroup"] label:has(input:checked){
  background:#21262d !important;color:#e6edf3 !important;}
div[data-testid="stRadio"] div[role="radiogroup"] input[type="radio"]{display:none !important;}

/* score block */
.sb{border-radius:10px;padding:1.1rem 1.4rem;display:flex;
    align-items:center;justify-content:space-between;margin-bottom:.85rem;}
.sb.pass{background:#0a1f14;border:1.5px solid #238636;}
.sb.warn{background:#1c1600;border:1.5px solid #9e6a03;}
.sb.fail{background:#230d0e;border:1.5px solid #da3633;}
.verdict{font-size:.6rem;font-weight:800;letter-spacing:.18em;font-family:monospace;}
.verdict.pass{color:#3fb950;}.verdict.warn{color:#e3b341;}.verdict.fail{color:#f85149;}
.score-n{font-size:2.6rem;font-weight:900;font-family:monospace;line-height:1;}
.score-n.pass{color:#3fb950;}.score-n.warn{color:#e3b341;}.score-n.fail{color:#f85149;}
.bar-bg{height:3px;background:#21262d;border-radius:3px;margin-top:.75rem;}
.bar-fg{height:3px;border-radius:3px;}

/* section label */
.sl{font-size:.6rem;font-weight:800;letter-spacing:.14em;text-transform:uppercase;
    font-family:monospace;margin:.9rem 0 .4rem;}
.sl.c{color:#f85149;}.sl.m{color:#e3b341;}.sl.g{color:#3fb950;}

/* issue card */
.ic{display:grid;grid-template-columns:1rem 1fr;gap:.55rem;
    background:#161b22;border:1px solid #21262d;border-radius:8px;
    padding:.7rem .9rem;margin-bottom:.35rem;}
.ic.c{border-left:3px solid #f85149;}.ic.m{border-left:3px solid #e3b341;}
.ic.g{border-left:3px solid #3fb950;}
.it{font-weight:600;color:#e6edf3;font-size:.85rem;}
.if{color:#8b949e;font-size:.76rem;margin-top:.15rem;}
.is{font-family:monospace;font-size:.7rem;color:#f0883e;
    background:#0d1117;border-radius:4px;padding:.15rem .4rem;
    margin-top:.25rem;display:inline-block;}

/* rewrite header */
.rh{font-size:.6rem;font-weight:800;letter-spacing:.14em;text-transform:uppercase;
    color:#00d4ff;font-family:monospace;margin:.9rem 0 .4rem;}

/* empty state */
.es{display:flex;flex-direction:column;align-items:center;justify-content:center;
    min-height:70vh;text-align:center;gap:.6rem;}
.es-icon{font-size:2.2rem;opacity:.15;}
.es-t{font-size:.9rem;font-weight:700;color:#30363d;font-family:monospace;}
.es-s{font-size:.74rem;color:#21262d;max-width:260px;line-height:1.6;}
.chips{display:flex;flex-wrap:wrap;gap:.35rem;justify-content:center;margin-top:.4rem;}
.chip{background:#0d1117;border:1px solid #21262d;border-radius:999px;
      padding:.18rem .6rem;font-size:.65rem;font-family:monospace;color:#30363d;}

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

/* col divider */
[data-testid="column"]:nth-child(2){border-left:1px solid #21262d !important;padding-left:1.5rem !important;}

/* expander */
[data-testid="stExpander"] details{background:#161b22 !important;border:1px solid #21262d !important;border-radius:8px !important;}
summary{font-family:monospace !important;font-size:.78rem !important;color:#8b949e !important;}
</style>""", unsafe_allow_html=True)


# ── API helpers ─────────────────────────────────────────────────────────────
def _status():
    try:
        h = requests.get(f"{API_BASE}/health", timeout=1).json()
        w = requests.get(f"{API_BASE}/health/worker", timeout=1).json()
        return {"api": h.get("status")=="ok",
                "worker": w.get("worker_heartbeat") is not None,
                "queue": w.get("queue_len","?")}
    except Exception:
        return {"api":False,"worker":False,"queue":"?"}

def submit_code(lang, code):
    r = requests.post(f"{API_BASE}/jobs", json={
        "language":lang.lower(),"code":code,
        "mode":"release_readiness","context":{"source":"code"}}, timeout=30)
    r.raise_for_status(); return r.json()["job_id"]

def submit_pr(repo,base,head,max_f,exts):
    r = requests.post(f"{API_BASE}/jobs", json={
        "language":"python","code":"","mode":"release_readiness",
        "context":{"source":"github_pr","repo_url":repo,
                   "base":base,"head":head,"max_files":max_f,
                   "extensions":exts,"max_bytes":200000}}, timeout=30)
    r.raise_for_status(); return r.json()["job_id"]

def poll(jid, timeout=90):
    end = time.time()+timeout
    while time.time()<end:
        try:
            d = requests.get(f"{API_BASE}/jobs/{jid}",timeout=10).json()
            if d.get("status") in ("done","error"): return d
        except Exception as e:
            return {"status":"error","error":str(e),"hint":POLL_HINT}
        time.sleep(0.4)
    return {"status":"error","error":"Timed out.","hint":POLL_HINT}

def parse_ext(s):
    return [p.strip() for ln in s.splitlines() for p in ln.split(",") if p.strip()]


# ── Render ──────────────────────────────────────────────────────────────────
def card(item, kind):
    icon = {"c":"⬤","m":"◆","g":"✔"}.get(kind,"·")
    col  = {"c":"#f85149","m":"#e3b341","g":"#3fb950"}.get(kind,"#8b949e")
    if isinstance(item,str):
        return f'<div class="ic {kind}"><span style="color:{col};font-size:.75rem">{icon}</span><div class="it">{item}</div></div>'
    t = item.get("issue",str(item)); fix=item.get("fix",""); snip=item.get("snippet",""); f=item.get("file","")
    pre  = f'<span style="color:#8b949e;font-size:.72rem">{f}: </span>' if f else ""
    fh   = f'<div class="if">→ {fix}</div>' if fix else ""
    sh   = f'<div class="is">{snip}</div>' if snip else ""
    return f'<div class="ic {kind}"><span style="color:{col};font-size:.75rem">{icon}</span><div><div class="it">{pre}{t}</div>{fh}{sh}</div></div>'

def render_score(gate, risk):
    cls = gate.lower()
    col = {"pass":"#3fb950","warn":"#e3b341","fail":"#f85149"}.get(cls,"#8b949e")
    tag = {"pass":"CLEARED","warn":"REVIEW","fail":"BLOCKED"}.get(cls,gate)
    sub = {"pass":"No critical latency issues.","warn":"Issues need attention.",
           "fail":"Critical violations — do not ship."}.get(cls,"")
    st.markdown(f"""
    <div class="sb {cls}">
      <div>
        <div class="verdict {cls}">RELEASE GATE · {tag}</div>
        <div style="font-size:.75rem;color:#8b949e;font-family:monospace;margin-top:.2rem">{sub}</div>
      </div>
      <div style="text-align:right">
        <span class="score-n {cls}">{risk}</span>
        <span style="font-size:.9rem;color:#484f58;font-family:monospace"> /100</span>
        <div style="font-size:.6rem;color:#484f58;font-family:monospace">risk score</div>
      </div>
    </div>
    <div class="bar-bg"><div class="bar-fg" style="width:{risk}%;background:{col}"></div></div>
    """, unsafe_allow_html=True)

def render_code_results(out):
    gpt   = out.get("gpt",{})
    major = gpt.get("major_issues",[])
    minor = gpt.get("minor_issues",[])
    clean = gpt.get("clean_findings",[])
    if major:
        st.markdown('<div class="sl c">⬤ Critical — fix before merge</div>', unsafe_allow_html=True)
        st.markdown("".join(card(i,"c") for i in major), unsafe_allow_html=True)
    if minor:
        st.markdown('<div class="sl m">◆ Improvements</div>', unsafe_allow_html=True)
        st.markdown("".join(card(i,"m") for i in minor), unsafe_allow_html=True)
    if not major and not minor and clean:
        st.markdown('<div class="sl g">✔ All clear</div>', unsafe_allow_html=True)
        st.markdown("".join(card(i,"g") for i in clean), unsafe_allow_html=True)
    rw = gpt.get("rewritten","")
    if rw:
        st.markdown('<div class="rh">✦ Suggested rewrite</div>', unsafe_allow_html=True)
        st.code(rw, language=out.get("language","") or None)
    with st.expander("Raw output"):
        ca,cb = st.columns(2)
        with ca: st.caption("Static"); st.json(out.get("static",{}))
        with cb: st.caption("LLM");    st.json(gpt)

def render_pr_results(out):
    st.caption(f"`{out.get('repo','?')}` · `{out.get('base','?')}` → `{out.get('head','?')}`")
    top = out.get("top_actions",[])
    if top:
        st.markdown('<div class="sl c">⬤ Top actions</div>', unsafe_allow_html=True)
        st.markdown("".join(card(a,"c") for a in top), unsafe_allow_html=True)
    hs = out.get("hotspots",[])
    if hs:
        st.markdown('<div class="sl m">◆ Hotspot files</div>', unsafe_allow_html=True)
        st.dataframe([{"file":h.get("path"),"lang":h.get("language"),
                       "issues":h.get("issue_count",0),"risk":h.get("risk_points",0)}
                      for h in hs], use_container_width=True, hide_index=True)
    for f in sorted(out.get("per_file",[]),key=lambda x:int(x.get("issue_count") or 0),reverse=True):
        with st.expander(f"{f.get('path')} · {f.get('issue_count',0)} issues"):
            if not f.get("skipped"): st.json(f.get("static",{}))
    with st.expander("Full LLM output"): st.json(out.get("gpt",{}))

def render_empty():
    st.markdown("""
    <div class="es">
      <div class="es-icon">⚡</div>
      <div class="es-t">Results appear here</div>
      <div class="es-s">Paste code or point at a GitHub PR and hit Run.</div>
      <div class="chips">
        <span class="chip">hot-loop allocations</span>
        <span class="chip">GC pressure</span>
        <span class="chip">I/O stalls</span>
        <span class="chip">lock contention</span>
        <span class="chip">Thread.sleep</span>
        <span class="chip">shared_ptr cost</span>
        <span class="chip">virtual dispatch</span>
        <span class="chip">string concat loops</span>
      </div>
    </div>""", unsafe_allow_html=True)


# ── NAV ─────────────────────────────────────────────────────────────────────
s = _status()
pill = lambda l,ok: f'<span class="pill {"ok" if ok else "dn"}"><span class="dot"></span>{l}</span>'
nav_l, nav_r = st.columns([1,1])
with nav_l:
    st.markdown(f'<div style="padding:.4rem 0"><span class="brand">⚡ Low Latency 101</span></div>',
                unsafe_allow_html=True)
with nav_r:
    st.markdown(f'<div style="display:flex;gap:.4rem;justify-content:flex-end;padding:.4rem 0">'
                f'{pill("API",s["api"])}{pill("Worker",s["worker"])}'
                f'<span class="pill qt">Q: {s["queue"]}</span></div>',
                unsafe_allow_html=True)

st.markdown('<div style="height:1px;background:#21262d;margin:.25rem 0 .75rem"></div>',
            unsafe_allow_html=True)

# ── MAIN COLUMNS ─────────────────────────────────────────────────────────────
left, right = st.columns([4, 6], gap="medium")

# ── LEFT ─────────────────────────────────────────────────────────────────────
with left:
    mode = st.radio("src", ["Paste Code", "GitHub PR Diff"],
                    horizontal=True, label_visibility="collapsed")

    if mode == "Paste Code":
        lang = st.selectbox("Language", ["Python","Java","C++"], label_visibility="visible")
        code = st.text_area("Code snippet", height=260,
                            placeholder="Paste Python / Java / C++ here...",
                            label_visibility="visible")
        if st.button("⚡  Run Release Gate", key="rc"):
            if not code.strip():
                st.warning("Paste some code first.")
            else:
                with st.spinner("Running analysis..."):
                    jid  = submit_code(lang, code)
                    resp = poll(jid, 90)
                if resp.get("status") == "error":
                    st.session_state.err    = resp.get("error")
                    st.session_state.result = None
                else:
                    r = resp.get("result",{})
                    r["language"] = lang.lower()
                    st.session_state.result     = r
                    st.session_state.source_tag = "code"
                    st.session_state.err        = None
                st.rerun()
    else:
        repo = st.text_input("Repo URL", placeholder="https://github.com/owner/repo")
        c1,c2 = st.columns(2)
        with c1: base = st.text_input("Base ref", value="main")
        with c2: head = st.text_input("Head ref / SHA", placeholder="feature-branch")
        mf  = int(st.number_input("Max files", 1, 200, 30))
        ext = st.text_input("Extensions", value=".py,.java,.cpp")
        if st.button("⚡  Run Release Gate", key="rp"):
            if not repo.strip():
                st.warning("Enter a repo URL.")
            elif not base.strip() or not head.strip():
                st.warning("Base and head refs required.")
            else:
                with st.spinner("Fetching PR and analyzing..."):
                    jid  = submit_pr(repo.strip(),base.strip(),head.strip(),mf,parse_ext(ext))
                    resp = poll(jid, 180)
                if resp.get("status") == "error":
                    st.session_state.err    = resp.get("error")
                    st.session_state.result = None
                else:
                    st.session_state.result     = resp.get("result",{})
                    st.session_state.source_tag = "pr"
                    st.session_state.err        = None
                st.rerun()

# ── RIGHT ─────────────────────────────────────────────────────────────────────
with right:
    if st.session_state.err:
        st.error(st.session_state.err)
    elif st.session_state.result is None:
        render_empty()
    else:
        out  = st.session_state.result
        gate = out.get("gate","WARN")
        risk = int(out.get("risk_score",0))
        render_score(gate, risk)
        if st.session_state.source_tag == "code":
            render_code_results(out)
        else:
            render_pr_results(out)

st.markdown('<div style="height:1px;background:#21262d;margin:1rem 0 0"></div>',
            unsafe_allow_html=True)
st.markdown('<div style="text-align:center;padding:.75rem;color:#30363d;'
            'font-size:.65rem;font-family:monospace">'
            'Low-Latency-101 · built for engineers who care about microseconds</div>',
            unsafe_allow_html=True)
