# ⚡ Low Latency 101

A release-readiness gate for latency risk — paste code or point at a GitHub PR and get surgical, line-level fixes from a low-latency systems engineer AI.

Detects: hot-loop allocations · GC pressure · I/O stalls · lock contention · blocking calls · string concat loops · virtual dispatch · syscalls in loops

---

## 🌐 Live (Production)

| Service | URL |
|---|---|
| **UI (Streamlit Cloud)** | https://low-latency-101.streamlit.app |
| **API** | https://api-production-0435.up.railway.app |
| **API Health** | https://api-production-0435.up.railway.app/health |
| **MCP Runbook** | https://mcp-runbook-production.up.railway.app |
| **MCP GitHub** | https://mcp-github-production.up.railway.app |

Backend runs on [Railway](https://railway.app) · Frontend on [Streamlit Cloud](https://share.streamlit.io) · Branch: `engine-refactor`

---

## 🏗 Architecture

```
Streamlit UI  →  FastAPI (API)  →  Redis queue  →  Worker
                                                      ├── Static analyzer (Python AST / javalang / tree-sitter-cpp)
                                                      ├── MCP Runbook (latency rules)
                                                      ├── MCP GitHub (repo/PR fetcher)
                                                      └── LLM (DeepSeek via OpenRouter)
```

---

## 🚀 Local Setup

### Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) — **must be running** before step 3
- Python 3.11+
- An [OpenRouter](https://openrouter.ai) API key (free tier works)

### Step 1 — Clone

```bash
git clone https://github.com/gauribhardwaj/Low-Latency-101.git
cd Low-Latency-101
git checkout engine-refactor
```

### Step 2 — Create `.env`

```bash
cp .env.example .env   # or create manually
```

Edit `.env`:

```env
OPENROUTER_API_KEY=sk-or-your-key-here
GITHUB_TOKEN=ghp_your_token   # optional — increases GitHub API rate limits
```

### Step 3 — Start backend

```bash
docker compose up --build -d
```

This starts 5 services:

| Service | Port |
|---|---|
| Redis | 6379 |
| MCP Runbook | 8787 |
| MCP GitHub | 8788 |
| API | 8000 |
| Worker | — |

Verify everything is up:

```bash
curl http://localhost:8000/health
curl http://localhost:8000/health/worker
```

Expected: `{"status":"ok"}` and worker heartbeat present.

### Step 4 — Start UI

```bash
pip install -r requirements.txt
streamlit run ui/streamlit_app.py
```

Open http://localhost:8501 — API and Worker pills should be green.

---

## 🍎 Mac Setup (Docker not working?)

### Apple Silicon (M1/M2/M3)

If you see `no matching manifest for linux/arm64` or services crash immediately:

```bash
# Add this to your shell profile (~/.zshrc or ~/.bash_profile)
export DOCKER_DEFAULT_PLATFORM=linux/amd64
```

Then restart terminal and run `docker compose up --build -d` again.

### Docker Desktop not starting

1. Open **Docker Desktop** from Applications (not just the CLI)
2. Wait for the whale icon in the menu bar to stop animating
3. Then run `docker compose up`

### Port already in use

```bash
# Find and kill whatever is on port 8000
lsof -i :8000
kill -9 <PID>
```

### Full reset if things are broken

```bash
docker compose down -v
docker system prune -f
docker compose up --build -d
```

---

## 🧪 Test it works

**Paste code test** — paste this into the UI:

```python
for i in range(1000):
    for j in range(100):
        print(i, j)
```

Expected: **FAIL** · critical I/O in tight loop · surgical fix shown

**API test:**

```bash
curl -X POST http://localhost:8000/jobs \
  -H "Content-Type: application/json" \
  -d '{"language":"python","code":"for i in range(1000):\n    print(i)","mode":"release_readiness","context":{}}'
```

---

## 📁 Repo Layout

```
core/latency_engine/     # Static analyzer + LLM review
  detectors.py           # Python AST / javalang / tree-sitter-cpp detectors
  gpt_review.py          # Snippet-based LLM prompt + surgical patch output
  engine.py              # Orchestrator

services/api/            # FastAPI — job submit + poll
services/worker/         # Long-running worker — pulls from Redis, runs analysis

mcp/runbook/             # Latency rules & playbooks (FastAPI)
mcp/github/              # GitHub repo/PR fetcher (FastAPI)

ui/streamlit_app.py      # Two-panel Streamlit frontend

docker-compose.yml       # Local dev — all 5 services
render.yaml              # Render deployment config
```

---

## 🔑 Environment Variables

| Variable | Required | Description |
|---|---|---|
| `OPENROUTER_API_KEY` | ✅ | LLM API key from openrouter.ai |
| `GITHUB_TOKEN` | Optional | GitHub PAT — higher API rate limits |
| `OPENROUTER_MODEL` | Optional | Default: `deepseek/deepseek-chat-v3-0324` |
| `API_BASE` | Optional | Override API URL (default: `http://localhost:8000`) |

---

## 💰 Cost

Each analysis uses ~300–700 tokens via DeepSeek v3 on OpenRouter.
**Typical cost: $0.0001–0.0003 per query.** Shown live in the UI after each run.
