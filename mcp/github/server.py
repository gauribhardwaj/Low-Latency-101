import base64
import os
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import requests
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

GITHUB_API_BASE = os.getenv("GITHUB_API_BASE", "https://api.github.com").rstrip("/")
REQUEST_TIMEOUT_SEC = int(os.getenv("GITHUB_TIMEOUT_SEC", "20"))

app = FastAPI(title="GitHub MCP (Public Repos)")


class RepoTreeRequest(BaseModel):
    repo: Optional[str] = None
    repo_url: Optional[str] = None
    ref: str = "main"


class RepoFileRequest(BaseModel):
    repo: Optional[str] = None
    repo_url: Optional[str] = None
    ref: str = "main"
    path: str
    max_bytes: int = 200000


class RepoChangedFilesRequest(BaseModel):
    repo: Optional[str] = None
    repo_url: Optional[str] = None
    base_ref: str
    head_ref: str


class RepoSearchRequest(BaseModel):
    repo: Optional[str] = None
    repo_url: Optional[str] = None
    query: str
    per_page: int = 20


def _repo_value(repo: Optional[str], repo_url: Optional[str]) -> str:
    value = (repo or repo_url or "").strip()
    if not value:
        raise HTTPException(status_code=400, detail="Missing repo/repo_url")
    return value


def _parse_repo(repo_value: str) -> Tuple[str, str]:
    value = repo_value.strip()
    if "://" in value:
        parsed = urlparse(value)
        host = (parsed.netloc or "").lower()
        if host.startswith("www."):
            host = host[4:]
        if host != "github.com":
            raise HTTPException(status_code=400, detail="Repo URL must be github.com")
        path = (parsed.path or "").strip("/")
        if path.endswith(".git"):
            path = path[:-4]
        parts = path.split("/")
        if len(parts) < 2:
            raise HTTPException(status_code=400, detail="Invalid GitHub repo URL")
        return parts[0], parts[1]

    if value.endswith(".git"):
        value = value[:-4]
    parts = value.split("/")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise HTTPException(status_code=400, detail="Repo must be in owner/repo format")
    return parts[0], parts[1]


def _github_headers() -> Dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = (os.getenv("GITHUB_TOKEN") or "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _github_get(path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    url = f"{GITHUB_API_BASE}{path}"
    resp = requests.get(url, headers=_github_headers(), params=params, timeout=REQUEST_TIMEOUT_SEC)
    if resp.status_code // 100 != 2:
        try:
            payload = resp.json()
            detail = payload.get("message") or payload
        except Exception:
            detail = resp.text
        raise HTTPException(status_code=resp.status_code, detail=f"GitHub API error: {detail}")
    try:
        return resp.json()
    except Exception:
        raise HTTPException(status_code=502, detail="GitHub API returned invalid JSON")


def _resolve_tree_sha(owner: str, repo: str, ref: str) -> str:
    commit = _github_get(f"/repos/{owner}/{repo}/commits/{ref}")
    tree_sha = ((commit.get("commit") or {}).get("tree") or {}).get("sha")
    if not tree_sha:
        raise HTTPException(status_code=502, detail="Could not resolve tree SHA from ref")
    return tree_sha


def _decode_blob_text(raw_bytes: bytes) -> Tuple[str, bool]:
    # Basic binary heuristic to avoid feeding binary into analysis.
    if b"\x00" in raw_bytes:
        return "", True
    return raw_bytes.decode("utf-8", errors="replace"), False


def list_repo_tree(repo_value: str, ref: str) -> Dict[str, Any]:
    owner, repo = _parse_repo(repo_value)
    tree_sha = _resolve_tree_sha(owner, repo, ref)
    tree = _github_get(
        f"/repos/{owner}/{repo}/git/trees/{tree_sha}",
        params={"recursive": 1},
    )
    entries = tree.get("tree") or []
    files = [
        {
            "path": item.get("path"),
            "size": item.get("size") or 0,
            "sha": item.get("sha"),
        }
        for item in entries
        if item.get("type") == "blob"
    ]
    return {
        "repo": f"{owner}/{repo}",
        "ref": ref,
        "file_count": len(files),
        "truncated": bool(tree.get("truncated")),
        "files": files,
    }


def get_file(repo_value: str, ref: str, path: str, max_bytes: int) -> Dict[str, Any]:
    owner, repo = _parse_repo(repo_value)
    payload = _github_get(f"/repos/{owner}/{repo}/contents/{path}", params={"ref": ref})
    if isinstance(payload, list):
        raise HTTPException(status_code=400, detail="Requested path is a directory, not a file")

    content_b64 = payload.get("content")
    encoding = payload.get("encoding")
    raw_bytes = b""
    if encoding == "base64" and isinstance(content_b64, str):
        try:
            raw_bytes = base64.b64decode(content_b64, validate=False)
        except Exception:
            raise HTTPException(status_code=502, detail="Unable to decode base64 file content")
    else:
        download_url = payload.get("download_url")
        if not download_url:
            raise HTTPException(status_code=502, detail="No content/download_url returned by GitHub")
        raw_resp = requests.get(download_url, timeout=REQUEST_TIMEOUT_SEC)
        if raw_resp.status_code // 100 != 2:
            raise HTTPException(status_code=raw_resp.status_code, detail="Failed to download file content")
        raw_bytes = raw_resp.content

    original_len = len(raw_bytes)
    if max_bytes > 0 and len(raw_bytes) > max_bytes:
        raw_bytes = raw_bytes[:max_bytes]
    text, is_binary = _decode_blob_text(raw_bytes)
    return {
        "repo": f"{owner}/{repo}",
        "ref": ref,
        "path": path,
        "sha": payload.get("sha"),
        "size": payload.get("size") or original_len,
        "content": text,
        "is_binary": is_binary,
        "truncated": original_len > len(raw_bytes),
        "bytes_returned": len(raw_bytes),
    }


@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.post("/repo/tree")
def repo_tree(req: RepoTreeRequest) -> Dict[str, Any]:
    repo_value = _repo_value(req.repo, req.repo_url)
    return list_repo_tree(repo_value, req.ref)


@app.post("/repo/file")
def repo_file(req: RepoFileRequest) -> Dict[str, Any]:
    repo_value = _repo_value(req.repo, req.repo_url)
    return get_file(repo_value, req.ref, req.path, req.max_bytes)


@app.post("/repo/changed_files")
def repo_changed_files(req: RepoChangedFilesRequest) -> Dict[str, Any]:
    repo_value = _repo_value(req.repo, req.repo_url)
    owner, repo = _parse_repo(repo_value)
    compare = _github_get(
        f"/repos/{owner}/{repo}/compare/{req.base_ref}...{req.head_ref}",
    )
    files = compare.get("files") or []
    return {
        "repo": f"{owner}/{repo}",
        "base_ref": req.base_ref,
        "head_ref": req.head_ref,
        "changed_files": [
            {
                "filename": item.get("filename"),
                "status": item.get("status"),
                "additions": item.get("additions"),
                "deletions": item.get("deletions"),
                "changes": item.get("changes"),
            }
            for item in files
        ],
    }


@app.post("/repo/search")
def repo_search(req: RepoSearchRequest) -> Dict[str, Any]:
    repo_value = _repo_value(req.repo, req.repo_url)
    owner, repo = _parse_repo(repo_value)
    per_page = min(max(req.per_page, 1), 50)
    q = f"{req.query} repo:{owner}/{repo}"
    payload = _github_get("/search/code", params={"q": q, "per_page": per_page})
    items = payload.get("items") or []
    return {
        "repo": f"{owner}/{repo}",
        "query": req.query,
        "total_count": payload.get("total_count", 0),
        "items": [
            {
                "name": item.get("name"),
                "path": item.get("path"),
                "sha": item.get("sha"),
                "url": item.get("html_url"),
            }
            for item in items
        ],
    }


# Tool-style aliases.
@app.post("/list_repo_tree")
def list_repo_tree_tool(req: RepoTreeRequest) -> Dict[str, Any]:
    return repo_tree(req)


@app.post("/get_file")
def get_file_tool(req: RepoFileRequest) -> Dict[str, Any]:
    return repo_file(req)


@app.post("/get_changed_files")
def get_changed_files_tool(req: RepoChangedFilesRequest) -> Dict[str, Any]:
    return repo_changed_files(req)


@app.post("/search")
def search_tool(req: RepoSearchRequest) -> Dict[str, Any]:
    return repo_search(req)
