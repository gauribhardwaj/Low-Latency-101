# Low-Latency-101

Low-Latency-101 is a release-readiness gate for latency risk.

It combines:
- Static code checks (Python, Java, C++)
- LLM review for latency-focused findings
- A simple queue-based backend for async analysis
- MCP services for runbooks and public GitHub repository ingestion

## Repo Layout

- `core/latency_engine/` - static analyzer + GPT review logic
- `services/api/` - FastAPI service for job submission/polling
- `services/worker/` - worker that runs static + GPT analysis
- `mcp/runbook/` - runbook rules service (FastAPI)
- `mcp/github/` - GitHub MCP service (FastAPI) for public repo tree/file access
- `ui/streamlit_app.py` - Streamlit frontend for the release gate
- `app_legacy.py` - older single-process Streamlit app

## Quick Start

### 1) Prerequisites

- Docker Desktop
- Python 3.11+ (for local UI)
- OpenRouter API key

### 2) Add `.env`

Create `.env` in repo root:

```env
OPENROUTER_API_KEY=sk-or-your-key
# Optional, increases GitHub API limits for MCP GitHub service:
GITHUB_TOKEN=ghp_or_github_pat
```

### 3) Start backend services

```bash
docker compose up --build -d
```

This starts:
- Redis on `localhost:6379`
- Runbook MCP service on `localhost:8787`
- GitHub MCP service on `localhost:8788`
- API on `localhost:8000`
- Worker (background)

### 4) Start UI

```bash
pip install -r requirements.txt
streamlit run ui/streamlit_app.py
```

Optional if API is not on localhost:

```bash
set API_BASE=http://localhost:8000
```

## Basic API Usage

Health checks:

```bash
curl http://localhost:8000/health
curl http://localhost:8000/health/worker
```

Create a job:

```bash
curl -X POST http://localhost:8000/jobs \
  -H "Content-Type: application/json" \
  -d '{"language":"python","code":"print(1)","mode":"release_readiness","context":{}}'
```

Poll result:

```bash
curl http://localhost:8000/jobs/<job_id>
```

Create a GitHub repo job:

```bash
curl -X POST http://localhost:8000/jobs/github \
  -H "Content-Type: application/json" \
  -d '{"repo_url":"https://github.com/psf/requests","ref":"main","paths":["requests/"],"extensions":[".py"],"max_files":30}'
```

## Stop

```bash
docker compose down
```
