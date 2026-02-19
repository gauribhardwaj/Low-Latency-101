import os, yaml
from fastapi import FastAPI

app = FastAPI(title="Runbook MCP (MVP)")

def load():
    path = os.getenv("RUNBOOK_PATH", "/app/runbook.yaml")
    with open(path, "r") as f:
        return yaml.safe_load(f)

@app.get("/rules")
def rules():
    return load()

@app.get("/playbook")
def playbook(signature: str):
    data = load()
    items = data.get("playbooks", [])
    for p in items:
        if p.get("signature") == signature:
            return p
    return {"signature": signature, "steps": []}