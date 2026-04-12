# ⚡ Low Latency 101

A release-readiness gate for latency risk — paste code or point at a GitHub PR and get surgical, line-level fixes from a low-latency systems engineer AI.

Detects: hot-loop allocations · GC pressure · I/O stalls · lock contention · blocking calls · string concat loops · virtual dispatch · syscalls in loops

---

## 🌐 Live (Production)

| Service | URL |
|---|---|
| **UI (Streamlit Cloud)** | https://low-latency-101.streamlit.app |
| **API** | https://api-production-0435.up.railway.app |
| **API Health check** | https://api-production-0435.up.railway.app/health |
| **MCP Runbook** | https://mcp-runbook-production.up.railway.app |
| **MCP GitHub** | https://mcp-github-production.up.railway.app |
| **Railway dashboard** | https://railway.app (project: fearless-heart) |
| **Streamlit Cloud dashboard** | https://share.streamlit.io |
| **GitHub repo** | https://github.com/gauribhardwaj/Low-Latency-101 |

Active branch: `engine-refactor` — backend on Railway · frontend on Streamlit Cloud

---

## 🏗 Architecture

```
Streamlit UI  →  FastAPI (API :8000)  →  Redis queue  →  Worker
                                                           ├── Static analyzer
                                                           │     Python: built-in ast
                                                           │     Java:   javalang
                                                           │     C++:    tree-sitter-cpp
                                                           ├── MCP Runbook (:8787) — latency rules YAML
                                                           ├── MCP GitHub  (:8788) — repo/PR fetcher
                                                           └── LLM — DeepSeek v3 via OpenRouter
                                                                 · snippet-only input (not full file)
                                                                 · returns surgical line-level patches
                                                                 · ~$0.0001–0.0003 per query
```

---

## 🚀 Local Setup (any OS)

### What you need first

| Tool | Link | Notes |
|---|---|---|
| Docker Desktop | https://www.docker.com/products/docker-desktop/ | Must be **open and running** before step 3 |
| Python 3.11+ | https://www.python.org/downloads/ | For running the UI |
| OpenRouter key | https://openrouter.ai | Free tier works — DeepSeek is ~$0.0001/query |
| GitHub token | https://github.com/settings/tokens | Optional — no scopes needed, just increases rate limits |

---

### Step 1 — Clone the repo

```bash
git clone https://github.com/gauribhardwaj/Low-Latency-101.git
cd Low-Latency-101
git checkout engine-refactor
```

---

### Step 2 — Create your `.env` file

```bash
# in the repo root, create a file called .env
touch .env
```

Paste this into `.env` and fill in your keys:

```env
# Required — get a free key at https://openrouter.ai
OPENROUTER_API_KEY=sk-or-your-key-here

# Optional — increases GitHub API rate limit from 60 to 5000 req/hr
# Create at https://github.com/settings/tokens (no scopes needed for public repos)
GITHUB_TOKEN=ghp_your_token_here

# Optional — override the LLM model (default shown below)
# OPENROUTER_MODEL=deepseek/deepseek-chat-v3-0324
```

> ⚠️ Never commit `.env` — it's already in `.gitignore`

---

### Step 3 — Start the backend (Docker)

Make sure Docker Desktop is open and the whale icon is visible in your taskbar/menu bar, then:

```bash
docker compose up --build -d
```

This builds and starts 5 services:

| Service | Port | What it does |
|---|---|---|
| Redis | 6379 | Job queue |
| MCP Runbook | 8787 | Latency rules & playbooks |
| MCP GitHub | 8788 | Fetches repo/PR files from GitHub |
| API | 8000 | Job submit & poll (FastAPI) |
| Worker | — | Runs static analysis + LLM review |

Verify everything is healthy:

```bash
curl http://localhost:8000/health
# → {"status":"ok"}

curl http://localhost:8000/health/worker
# → {"worker_heartbeat": "...", "queue_len": 0}
```

---

### Step 4 — Start the UI

```bash
pip install -r requirements.txt
streamlit run ui/streamlit_app.py
```

Open **http://localhost:8501** — the API and Worker pills in the top right should both be green.

---

## 🍎 Mac Troubleshooting (Docker)

### Apple Silicon (M1 / M2 / M3) — image platform error

If you see `no matching manifest for linux/arm64` or a service crashes immediately:

```bash
# Add to ~/.zshrc (or ~/.bash_profile if using bash)
echo 'export DOCKER_DEFAULT_PLATFORM=linux/amd64' >> ~/.zshrc
source ~/.zshrc

# Then rebuild
docker compose down
docker compose up --build -d
```

### Docker Desktop not responding

1. Open **Docker Desktop** from `/Applications` — don't just run `docker` in terminal
2. Wait for the whale icon in the menu bar to **stop animating** (fully started)
3. Then run `docker compose up --build -d`

### Port already in use

```bash
# Check what's using port 8000
lsof -i :8000
kill -9 <PID>

# Then restart
docker compose up -d
```

### Nuclear reset — if everything is broken

```bash
docker compose down -v        # stop + remove volumes
docker system prune -f        # clean up dangling images
docker compose up --build -d  # fresh build
```

---

## 🧪 Test it works

### Paste code test

Open http://localhost:8501, select **Paste Code**, paste this:

```python
for i in range(1000):
    for j in range(100):
        print(i, j)
```

Expected result: **BLOCKED** · risk score 40–100 · critical I/O in tight loop · surgical fix with before/after patch

### API test (curl)

```bash
# Submit a job
curl -X POST http://localhost:8000/jobs \
  -H "Content-Type: application/json" \
  -d '{"language":"python","code":"for i in range(1000):\n    print(i)","mode":"release_readiness","context":{}}'

# Returns: {"job_id": "abc123"}

# Poll for result
curl http://localhost:8000/jobs/abc123
```

### GitHub PR test

In the UI switch to **GitHub PR Diff** and enter:
- Repo URL: `https://github.com/gauribhardwaj/Low-Latency-101`
- Base: `main`
- Head: `engine-refactor`

---

## 📁 Repo Layout

```
core/
  latency_engine/
    detectors.py       # AST-based issue detection per language
    gpt_review.py      # Snippet extraction + LLM prompt + patch output
    engine.py          # Orchestrator

services/
  api/                 # FastAPI — job submit & poll (port 8000)
  worker/              # Long-running worker — Redis consumer

mcp/
  runbook/             # Latency rules YAML served as API (port 8787)
  github/              # GitHub repo/PR file fetcher (port 8788)

ui/
  streamlit_app.py     # Two-panel Streamlit frontend

docker-compose.yml     # Local dev — all 5 services
render.yaml            # Render cloud deployment config
requirements.txt       # UI-only deps (Streamlit, requests)
.env.example           # Template for .env
```

---

## 🔑 All Environment Variables

| Variable | Service | Required | Default | Description |
|---|---|---|---|---|
| `OPENROUTER_API_KEY` | Worker | ✅ | — | LLM API key — get at openrouter.ai |
| `GITHUB_TOKEN` | MCP GitHub | Optional | — | GitHub PAT for higher rate limits |
| `OPENROUTER_MODEL` | Worker | Optional | `deepseek/deepseek-chat-v3-0324` | Override LLM model |
| `REDIS_URL` | API + Worker | Auto | `redis://redis:6379/0` | Set automatically by Docker / Railway |
| `MCP_RUNBOOK_URL` | Worker | Auto | `http://mcp_runbook:8787` | Set automatically by Docker |
| `MCP_GITHUB_URL` | Worker | Auto | `http://mcp_github:8788` | Set automatically by Docker |
| `API_BASE` | UI | Optional | `http://localhost:8000` | Override if API is not on localhost |

---

## ☁️ Deploy your own (Railway)

1. Fork the repo
2. Go to [railway.app](https://railway.app) → New Project → Deploy from GitHub
3. Add **4 services** pointing to these Dockerfiles (set Builder = Dockerfile, root context `/`):
   - `services/api/Dockerfile`
   - `services/worker/Dockerfile`
   - `mcp/runbook/Dockerfile`
   - `mcp/github/Dockerfile`
4. Add a **Redis** database plugin
5. Set env vars on each service — copy the Redis URL from the Redis service into API and Worker
6. On the Worker service add `OPENROUTER_API_KEY`
7. Copy the API public URL → go to [Streamlit Cloud](https://share.streamlit.io) → your app → Settings → Secrets → add `API_BASE = "https://your-api-url"`

---

## 💰 Cost

| Item | Cost |
|---|---|
| Railway (backend) | ~$0/mo on $5 free credit for light usage |
| Streamlit Cloud (UI) | Free |
| OpenRouter / DeepSeek | ~$0.0001–$0.0003 per analysis query |
| Upstash Redis (alternative) | Free tier — 10K commands/day |
