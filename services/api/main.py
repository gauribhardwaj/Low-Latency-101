import os, json, uuid
from fastapi import FastAPI
from pydantic import BaseModel
from pydantic import Field
import redis

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
r = redis.Redis.from_url(REDIS_URL, decode_responses=True)

app = FastAPI(title="Latency Copilot API")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/health/worker")
def health_worker():
    hb = r.get("worker:heartbeat")
    qlen = r.llen("queue:jobs")
    return {"queue_len": qlen, "worker_heartbeat": hb}

class AnalyzeRequest(BaseModel):
    language: str
    code: str
    mode: str = "release_readiness"  # or "incident_copilot"
    context: dict = Field(default_factory=dict)  # repo/telemetry inputs later

@app.post("/jobs")
def create_job(req: AnalyzeRequest):
    job_id = str(uuid.uuid4())
    r.hset(f"job:{job_id}", mapping={
        "status": "queued",
        "language": req.language,
        "code": req.code,
        "mode": req.mode,
        "context": json.dumps(req.context),
    })
    r.lpush("queue:jobs", job_id)
    return {"job_id": job_id}

@app.get("/jobs/{job_id}")
def get_job(job_id: str):
    data = r.hgetall(f"job:{job_id}")
    if not data:
        return {"error": "not_found"}
    if "result" in data:
        try:
            data["result"] = json.loads(data["result"])
        except Exception:
            pass
    if "context" in data:
        try:
            data["context"] = json.loads(data["context"])
        except Exception:
            pass
    return data
