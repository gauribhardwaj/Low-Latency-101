import json
import os
import time
import traceback
from typing import Any, Dict, List, Optional, Tuple

import redis
import requests

from core.latency_engine.engine import LatencyAnalyzer
from core.latency_engine.gpt_review import query_llm_with_code

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
MCP_RUNBOOK_URL = os.getenv("MCP_RUNBOOK_URL", "http://mcp_runbook:8787")
MCP_GITHUB_URL = os.getenv("MCP_GITHUB_URL", "http://mcp_github:8788")
HEARTBEAT_KEY = "worker:heartbeat"

MAX_TOTAL_FETCH_BYTES = int(os.getenv("GITHUB_MAX_TOTAL_BYTES", "900000"))
MAX_FILE_FETCH_BYTES = int(os.getenv("GITHUB_MAX_FILE_BYTES", "120000"))
DEFAULT_MAX_FILES = int(os.getenv("GITHUB_DEFAULT_MAX_FILES", "30"))
DEFAULT_GPT_HOTSPOTS = int(os.getenv("GITHUB_DEFAULT_GPT_HOTSPOTS", "3"))
MAX_LLM_CHARS = int(os.getenv("MAX_LLM_CHARS", "20000"))

r = redis.Redis.from_url(REDIS_URL, decode_responses=True)

EXT_TO_LANGUAGE = {
    ".py": "python",
    ".java": "java",
    ".cpp": "c++",
    ".cc": "c++",
    ".cxx": "c++",
    ".hpp": "c++",
    ".hh": "c++",
    ".h": "c++",
}


def mcp_get_runbook_rules() -> Dict[str, Any]:
    resp = requests.get(f"{MCP_RUNBOOK_URL}/rules", timeout=10)
    resp.raise_for_status()
    return resp.json()


def _mcp_github_post(path: str, payload: Dict[str, Any], timeout_sec: int = 30) -> Dict[str, Any]:
    resp = requests.post(f"{MCP_GITHUB_URL}{path}", json=payload, timeout=timeout_sec)
    resp.raise_for_status()
    return resp.json()


def _normalize_gpt_result(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, dict):
        parsed = raw
    elif isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except Exception:
            parsed = {"summary": raw}
    else:
        parsed = {"summary": str(raw)}

    return {
        "summary": str(parsed.get("summary", "")).strip(),
        "no_changes": bool(parsed.get("no_changes", False)),
        "clean_findings": list(parsed.get("clean_findings", [])),
        "minor_issues": list(parsed.get("minor_issues", [])),
        "major_issues": list(parsed.get("major_issues", [])),
        "rewritten": str(parsed.get("rewritten", "")).strip(),
        "confidence": float(parsed.get("confidence", 0.0)),
    }


def _severity_from_issue(issue: Dict[str, Any]) -> str:
    sev = (issue.get("severity") or "").lower().strip()
    if sev in {"major", "minor"}:
        return sev
    penalty = int(issue.get("penalty", 0) or 0)
    if penalty >= 10:
        return "major"
    if penalty >= 6:
        return "minor"
    return "info"


def compute_risk(static_results: Optional[Dict[str, Any]], gpt_results: Optional[Dict[str, Any]]) -> int:
    score = 0
    static_issues = (static_results or {}).get("issues", [])
    for item in static_issues:
        sev = _severity_from_issue(item)
        if sev == "major":
            score += 20
        elif sev == "minor":
            score += 10
        else:
            score += 5

    if gpt_results and gpt_results.get("major_issues"):
        score += 20 * len(gpt_results["major_issues"])
    if gpt_results and gpt_results.get("minor_issues"):
        score += 10 * len(gpt_results["minor_issues"])
    return min(score, 100)


def _gate_for_risk(risk_score: int) -> str:
    if risk_score >= 70:
        return "FAIL"
    if risk_score >= 35:
        return "WARN"
    return "PASS"


def _extension(path: str) -> str:
    idx = path.rfind(".")
    if idx < 0:
        return ""
    return path[idx:].lower()


def _language_for_path(path: str) -> Optional[str]:
    return EXT_TO_LANGUAGE.get(_extension(path))


def _normalize_extensions(exts: Any) -> List[str]:
    out: List[str] = []
    for ext in exts or []:
        value = str(ext).strip().lower()
        if not value:
            continue
        if not value.startswith("."):
            value = f".{value}"
        out.append(value)
    return sorted(set(out))


def _normalize_paths(paths: Any) -> List[str]:
    out: List[str] = []
    for item in paths or []:
        value = str(item).strip().lstrip("./")
        if not value:
            continue
        out.append(value.rstrip("/"))
    return sorted(set(out))


def _path_in_scope(path: str, scope_paths: List[str]) -> bool:
    if not scope_paths:
        return True
    clean = path.lstrip("./")
    for prefix in scope_paths:
        if clean == prefix or clean.startswith(prefix + "/"):
            return True
    return False


def _path_has_extension(path: str, extensions: List[str]) -> bool:
    if not extensions:
        return True
    lower = path.lower()
    return any(lower.endswith(ext) for ext in extensions)


def _file_risk_points(issue_count: int, major_count: int, minor_count: int) -> int:
    return major_count * 20 + minor_count * 10 + max(issue_count - major_count - minor_count, 0) * 5


def _clip_for_llm(text: str) -> str:
    if len(text) <= MAX_LLM_CHARS:
        return text
    return text[:MAX_LLM_CHARS]


def _build_top_actions(file_results: List[Dict[str, Any]], global_gpt: Dict[str, Any]) -> List[str]:
    actions: List[str] = []

    for item in global_gpt.get("major_issues", []):
        if isinstance(item, dict):
            issue = str(item.get("issue", "")).strip()
            fix = str(item.get("fix", "")).strip()
            file_path = str(item.get("file", "")).strip()
            msg = issue if not fix else f"{issue} -> {fix}"
            if file_path:
                msg = f"{file_path}: {msg}"
            if msg:
                actions.append(msg)
        elif isinstance(item, str) and item.strip():
            actions.append(item.strip())

    for item in global_gpt.get("minor_issues", []):
        if len(actions) >= 8:
            break
        if isinstance(item, dict):
            issue = str(item.get("issue", "")).strip()
            fix = str(item.get("fix", "")).strip()
            file_path = str(item.get("file", "")).strip()
            msg = issue if not fix else f"{issue} -> {fix}"
            if file_path:
                msg = f"{file_path}: {msg}"
            if msg:
                actions.append(msg)
        elif isinstance(item, str) and item.strip():
            actions.append(item.strip())

    if len(actions) < 8:
        for file_item in file_results:
            for issue in file_item.get("static", {}).get("issues", []):
                sev = _severity_from_issue(issue)
                if sev not in {"major", "minor"}:
                    continue
                msg = f"{file_item['path']}: {issue.get('message', issue.get('rule', 'Issue'))}"
                actions.append(msg)
                if len(actions) >= 8:
                    break
            if len(actions) >= 8:
                break

    deduped: List[str] = []
    seen = set()
    for item in actions:
        if item not in seen:
            seen.add(item)
            deduped.append(item)
    return deduped[:8]


def _analyze_inline_code(language: str, code: str, mode: str, context: Dict[str, Any], runbook: Dict[str, Any]) -> Dict[str, Any]:
    analyzer = LatencyAnalyzer(language=language)
    static_out = analyzer.analyze(code)
    gpt_out = _normalize_gpt_result(query_llm_with_code(_clip_for_llm(code), language=language))

    risk = compute_risk(static_out, gpt_out)
    gate = _gate_for_risk(risk)

    return {
        "mode": mode,
        "source": "code",
        "gate": gate,
        "risk_score": risk,
        "runbook_rules_loaded": len(runbook.get("rules", [])),
        "top_actions": _build_top_actions(
            [{"path": "snippet", "static": static_out}],
            gpt_out,
        ),
        "hotspots": [
            {
                "path": "snippet",
                "language": language,
                "issue_count": len(static_out.get("issues", [])),
                "major_count": len([i for i in static_out.get("issues", []) if _severity_from_issue(i) == "major"]),
                "minor_count": len([i for i in static_out.get("issues", []) if _severity_from_issue(i) == "minor"]),
            }
        ],
        "files": [
            {
                "path": "snippet",
                "language": language,
                "static": static_out,
                "gpt": gpt_out,
            }
        ],
        "static": static_out,
        "gpt": gpt_out,
        "context": context,
    }


def _select_repo_files(
    repo_url: str,
    tree_files: List[Dict[str, Any]],
    scope_paths: List[str],
    extensions: List[str],
    max_files: int,
    base_ref: str,
    head_ref: str,
) -> Tuple[List[str], int]:
    candidate_paths: List[str]

    if base_ref and head_ref:
        changed = _mcp_github_post(
            "/repo/changed_files",
            {
                "repo_url": repo_url,
                "base_ref": base_ref,
                "head_ref": head_ref,
            },
            timeout_sec=40,
        )
        candidate_paths = [
            str(item.get("filename"))
            for item in changed.get("changed_files", [])
            if str(item.get("status", "")).lower() != "removed"
        ]
    else:
        candidate_paths = [str(item.get("path")) for item in tree_files]

    filtered = [
        path
        for path in candidate_paths
        if path
        and _path_in_scope(path, scope_paths)
        and _path_has_extension(path, extensions)
        and _language_for_path(path) is not None
    ]
    filtered = sorted(set(filtered))
    if max_files > 0:
        filtered = filtered[:max_files]
    return filtered, len(candidate_paths)


def _aggregate_gpt_issue_items(items: List[Any], path: str, bucket: List[Any], max_items: int) -> None:
    for item in items:
        if len(bucket) >= max_items:
            return
        if isinstance(item, dict):
            enriched = dict(item)
            enriched["file"] = path
            bucket.append(enriched)
        else:
            bucket.append({"file": path, "issue": str(item)})


def _analyze_github_repo(mode: str, context: Dict[str, Any], runbook: Dict[str, Any]) -> Dict[str, Any]:
    repo_url = str(context.get("repo_url", "")).strip()
    if not repo_url:
        raise ValueError("context.repo_url is required for GitHub source jobs")

    ref = str(context.get("ref", "main")).strip() or "main"
    base_ref = str(context.get("base_ref", "")).strip()
    head_ref = str(context.get("head_ref", "")).strip()
    scope_paths = _normalize_paths(context.get("paths", []))
    extensions = _normalize_extensions(context.get("extensions", []))
    max_files = int(context.get("max_files") or DEFAULT_MAX_FILES)
    gpt_hotspots = max(0, int(context.get("gpt_hotspots") or DEFAULT_GPT_HOTSPOTS))

    tree = _mcp_github_post("/repo/tree", {"repo_url": repo_url, "ref": ref}, timeout_sec=45)
    tree_files = tree.get("files", [])

    selected_files, candidate_count = _select_repo_files(
        repo_url=repo_url,
        tree_files=tree_files,
        scope_paths=scope_paths,
        extensions=extensions,
        max_files=max_files,
        base_ref=base_ref,
        head_ref=head_ref,
    )

    analyzer_cache: Dict[str, LatencyAnalyzer] = {}
    file_results: List[Dict[str, Any]] = []
    skipped_files: List[Dict[str, str]] = []
    global_issues: List[Dict[str, Any]] = []
    global_positive: List[str] = []
    total_bytes = 0

    for path in selected_files:
        if total_bytes >= MAX_TOTAL_FETCH_BYTES:
            skipped_files.append({"path": path, "reason": "total_byte_cap_reached"})
            continue

        remaining_budget = max(MAX_TOTAL_FETCH_BYTES - total_bytes, 0)
        per_file_cap = min(MAX_FILE_FETCH_BYTES, remaining_budget)
        if per_file_cap <= 0:
            skipped_files.append({"path": path, "reason": "byte_budget_exhausted"})
            continue

        try:
            file_payload = _mcp_github_post(
                "/repo/file",
                {
                    "repo_url": repo_url,
                    "ref": ref,
                    "path": path,
                    "max_bytes": per_file_cap,
                },
                timeout_sec=40,
            )
        except Exception as exc:
            skipped_files.append({"path": path, "reason": f"fetch_failed: {exc}"})
            continue

        if file_payload.get("is_binary"):
            skipped_files.append({"path": path, "reason": "binary"})
            continue

        content = str(file_payload.get("content") or "")
        if not content.strip():
            skipped_files.append({"path": path, "reason": "empty"})
            continue

        language = _language_for_path(path)
        if not language:
            skipped_files.append({"path": path, "reason": "unsupported_extension"})
            continue

        analyzer = analyzer_cache.get(language)
        if analyzer is None:
            analyzer = LatencyAnalyzer(language=language)
            analyzer_cache[language] = analyzer

        try:
            static_out = analyzer.analyze(content)
        except Exception as exc:
            skipped_files.append({"path": path, "reason": f"analysis_failed: {exc}"})
            continue
        for issue in static_out.get("issues", []):
            enriched_issue = dict(issue)
            enriched_issue["file"] = path
            if not enriched_issue.get("severity"):
                enriched_issue["severity"] = _severity_from_issue(enriched_issue)
            global_issues.append(enriched_issue)

        for sig in static_out.get("signals", {}).get("positive", []):
            global_positive.append(str(sig))

        major_count = len([i for i in static_out.get("issues", []) if _severity_from_issue(i) == "major"])
        minor_count = len([i for i in static_out.get("issues", []) if _severity_from_issue(i) == "minor"])
        issue_count = len(static_out.get("issues", []))
        risk_points = _file_risk_points(issue_count, major_count, minor_count)

        file_entry = {
            "path": path,
            "language": language,
            "bytes": int(file_payload.get("bytes_returned") or 0),
            "truncated": bool(file_payload.get("truncated")),
            "issue_count": issue_count,
            "major_count": major_count,
            "minor_count": minor_count,
            "risk_points": risk_points,
            "static": static_out,
            "gpt": None,
            "_content": content,
        }
        file_results.append(file_entry)
        total_bytes += int(file_payload.get("bytes_returned") or 0)

    file_results.sort(key=lambda item: item["risk_points"], reverse=True)
    gpt_major: List[Any] = []
    gpt_minor: List[Any] = []
    gpt_clean: List[Any] = []
    for hotspot in file_results[:gpt_hotspots]:
        gpt_out = _normalize_gpt_result(
            query_llm_with_code(_clip_for_llm(hotspot["_content"]), language=hotspot["language"])
        )
        hotspot["gpt"] = gpt_out
        _aggregate_gpt_issue_items(gpt_out.get("major_issues", []), hotspot["path"], gpt_major, max_items=10)
        _aggregate_gpt_issue_items(gpt_out.get("minor_issues", []), hotspot["path"], gpt_minor, max_items=10)
        for item in gpt_out.get("clean_findings", []):
            if len(gpt_clean) >= 10:
                break
            if isinstance(item, str):
                gpt_clean.append(f"{hotspot['path']}: {item}")
            else:
                gpt_clean.append(item)

    combined_static = {
        "issues": global_issues,
        "score": max(0, 100 - min(sum(int(i.get("penalty", 0) or 0) for i in global_issues), 100)),
        "signals": {"positive": sorted(set(global_positive))},
    }

    combined_gpt = {
        "summary": (
            f"Scanned {len(file_results)} files from {tree.get('repo', repo_url)} @ {ref}. "
            f"Detected {len(global_issues)} static issues."
        ),
        "no_changes": len(global_issues) == 0 and not gpt_major and not gpt_minor,
        "clean_findings": gpt_clean,
        "minor_issues": gpt_minor,
        "major_issues": gpt_major,
        "rewritten": "",
        "confidence": 0.65 if file_results else 0.0,
    }

    risk_score = compute_risk(combined_static, combined_gpt)
    gate = _gate_for_risk(risk_score)

    hotspots = [
        {
            "path": item["path"],
            "language": item["language"],
            "issue_count": item["issue_count"],
            "major_count": item["major_count"],
            "minor_count": item["minor_count"],
            "risk_points": item["risk_points"],
        }
        for item in file_results
    ]

    for item in file_results:
        item.pop("_content", None)

    return {
        "mode": mode,
        "source": "github",
        "gate": gate,
        "risk_score": risk_score,
        "runbook_rules_loaded": len(runbook.get("rules", [])),
        "top_actions": _build_top_actions(file_results, combined_gpt),
        "hotspots": hotspots,
        "files": file_results,
        "static": combined_static,
        "gpt": combined_gpt,
        "github": {
            "repo_url": repo_url,
            "repo": tree.get("repo"),
            "ref": ref,
            "base_ref": base_ref or None,
            "head_ref": head_ref or None,
            "scope": {
                "paths": scope_paths,
                "extensions": extensions,
                "max_files": max_files,
            },
            "tree_file_count": int(tree.get("file_count") or 0),
            "candidate_file_count": candidate_count,
            "selected_file_count": len(selected_files),
            "analyzed_file_count": len(file_results),
            "fetched_bytes": total_bytes,
            "skipped_files": skipped_files,
        },
        "context": context,
    }


def run_one(job_id: str) -> None:
    job_key = f"job:{job_id}"
    r.hset(job_key, "status", "running")

    language = (r.hget(job_key, "language") or "python").lower()
    code = r.hget(job_key, "code") or ""
    mode = r.hget(job_key, "mode") or "release_readiness"

    context_raw = r.hget(job_key, "context") or "{}"
    try:
        context = json.loads(context_raw)
    except Exception:
        context = {}

    try:
        runbook = mcp_get_runbook_rules()
        source = str((context or {}).get("source", "code")).lower().strip()

        if source == "github":
            result = _analyze_github_repo(mode=mode, context=context, runbook=runbook)
        else:
            result = _analyze_inline_code(
                language=language,
                code=code,
                mode=mode,
                context=context,
                runbook=runbook,
            )

        r.hset(
            job_key,
            mapping={
                "status": "done",
                "result": json.dumps(result),
            },
        )
    except Exception as exc:
        r.hset(
            job_key,
            mapping={
                "status": "error",
                "error": str(exc),
                "trace": traceback.format_exc(),
            },
        )


def loop() -> None:
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

