FROM python:3.11-slim
WORKDIR /app

COPY mcp/runbook/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY mcp/runbook/server.py /app/server.py
COPY mcp/runbook/runbook.yaml /app/runbook.yaml

EXPOSE 8787
CMD ["uvicorn", "server:app", "--host=0.0.0.0", "--port=8787"]