FROM python:3.11-slim
WORKDIR /app

COPY mcp/github/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY mcp/github/server.py /app/server.py

EXPOSE 8788
CMD ["uvicorn", "server:app", "--host=0.0.0.0", "--port=8788"]
