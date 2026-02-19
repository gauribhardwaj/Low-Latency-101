import os, time, json, traceback
import redis
import requests

# Import your existing engine + GPT review from core
from core.latency_engine.engine import LatencyAnalyzer
from core.latency_engine.gpt_review import query_llm_with_code

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
MCP_RUNBOOK_URL = os.getenv("MCP_RUNBOOK_URL", "http://mcp_runbook:8787")
HEARTBEAT_KEY = "worker:heartbeat"

r = redis.Redis.from_url(REDIS_URL, decode_responses=True)

def mcp_get_runbook_rules():
    # MVP: simple HTTP endpoint from our MCP server
    resp = requests.get(f"{MCP_RUNBOOK_URL}/rules", timeout=10)
    resp.raise_for_status()
    return resp.json()

def compute_risk(static_results, gpt_results):
    # MVP scoring (simple, sponsor-readable)
    # Later you’ll weight by p99 impact, severity, churn, etc.
    score = 0
    static_issues = (static_results or {}).get("issues", [])
    for item in static_issues:
        sev = (item.get("severity") or "").lower()
        score += 20 if sev == "major" else 10 if sev == "minor" else 5
    if gpt_results and gpt_results.get("major_issues"):
        score += 20 * len(gpt_results["major_issues"])
    if gpt_results and gpt_results.get("minor_issues"):
        score += 10 * len(gpt_results["minor_issues"])
    return min(score, 100)

def run_one(job_id: str):
    job_key = f"job:{job_id}"
    r.hset(job_key, "status", "running")

    language = r.hget(job_key, "language") or "python"
    code = r.hget(job_key, "code") or ""
    mode = r.hget(job_key, "mode") or "release_readiness"

    context_raw = r.hget(job_key, "context") or "{}"
    try:
        context = json.loads(context_raw)
    except Exception:
        context = {}

    try:
        runbook = mcp_get_runbook_rules()

        analyzer = LatencyAnalyzer(language=language)
        static_out = analyzer.analyze(code)  # uses your existing detector stack

        gpt_raw = query_llm_with_code(code, language=language)
        if isinstance(gpt_raw, str):
            try:
                gpt_out = json.loads(gpt_raw)
            except Exception:
                gpt_out = {
                    "summary": gpt_raw,
                    "no_changes": False,
                    "clean_findings": [],
                    "minor_issues": [],
                    "major_issues": [],
                    "rewritten": "",
                    "confidence": 0.0,
                }
        elif isinstance(gpt_raw, dict):
            gpt_out = gpt_raw
        else:
            gpt_out = {
                "summary": str(gpt_raw),
                "no_changes": False,
                "clean_findings": [],
                "minor_issues": [],
                "major_issues": [],
                "rewritten": "",
                "confidence": 0.0,
            }

        risk = compute_risk(static_out, gpt_out)
        gate = "FAIL" if risk >= 70 else "WARN" if risk >= 35 else "PASS"

        result = {
            "mode": mode,
            "gate": gate,
            "risk_score": risk,
            "runbook_rules_loaded": len(runbook.get("rules", [])),
            "static": static_out,
            "gpt": gpt_out,
            "context": context
        }

        r.hset(job_key, mapping={
            "status": "done",
            "result": json.dumps(result),
        })
    except Exception as e:
        r.hset(job_key, mapping={
            "status": "error",
            "error": str(e),
            "trace": traceback.format_exc()
        })

def loop():
    next_heartbeat = 0.0
    while True:
        now = time.time()
        if now >= next_heartbeat:
            r.set(HEARTBEAT_KEY, str(now), ex=10)
            next_heartbeat = now + 2.0

        job_id = r.rpop("queue:jobs")
        if not job_id:
            time.sleep(0.25)
            continue
        run_one(job_id)
        r.set(HEARTBEAT_KEY, str(time.time()), ex=10)

if __name__ == "__main__":
    loop()
