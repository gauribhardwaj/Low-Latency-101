import json
import os
import uuid
from typing import List, Optional

from fastapi import FastAPI
import redis
from pydantic import BaseModel, Field

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


class GithubAnalyzeRequest(BaseModel):
    repo_url: str
    ref: str = "main"
    paths: List[str] = Field(default_factory=list)
    extensions: List[str] = Field(default_factory=list)
    max_files: int = Field(default=30, ge=1, le=200)
    base_ref: Optional[str] = None
    head_ref: Optional[str] = None
    mode: str = "release_readiness"


def enqueue_job(language: str, code: str, mode: str, context: dict) -> str:
    job_id = str(uuid.uuid4())
    r.hset(
        f"job:{job_id}",
        mapping={
            "status": "queued",
            "language": language,
            "code": code,
            "mode": mode,
            "context": json.dumps(context),
        },
    )
    r.lpush("queue:jobs", job_id)
    return job_id


@app.post("/jobs")
def create_job(req: AnalyzeRequest):
    context = dict(req.context or {})
    context.setdefault("source", "code")
    job_id = enqueue_job(
        language=req.language,
        code=req.code,
        mode=req.mode,
        context=context,
    )
    return {"job_id": job_id}


@app.post("/jobs/github")
def create_github_job(req: GithubAnalyzeRequest):
    context = {
        "source": "github",
        "repo_url": req.repo_url,
        "ref": req.ref,
        "paths": req.paths,
        "extensions": req.extensions,
        "max_files": req.max_files,
    }
    if req.base_ref:
        context["base_ref"] = req.base_ref
    if req.head_ref:
        context["head_ref"] = req.head_ref

    job_id = enqueue_job(
        language="python",
        code="",
        mode=req.mode,
        context=context,
    )
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
