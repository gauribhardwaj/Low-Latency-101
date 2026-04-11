import os
import json
import time
import logging
from typing import Any, Dict, Optional, List

import requests

# ---------- Logging ----------
logger = logging.getLogger(__name__)
if not logger.handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# ---------- Config ----------
OPENROUTER_ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_MODEL_DEFAULT = "deepseek/deepseek-chat-v3-0324"
GEN_CFG = {"temperature": 0.2, "max_tokens": 700, "top_p": 0.9}
TIMEOUT_SEC = 30
MAX_RETRIES = 2
RETRY_BACKOFF_SEC = 1.5

# Lines of context to include around each flagged line when building snippets
SNIPPET_CONTEXT = 12


# ---------- Helpers ----------
def _get_api_key() -> str:
    key = (os.getenv("OPENROUTER_API_KEY") or "").strip()
    if not key:
        try:
            import streamlit as st  # type: ignore
            key = (st.secrets.get("OPENROUTER_API_KEY") or "").strip()
        except Exception:
            pass
    return key


def _get_model() -> str:
    return (os.getenv("OPENROUTER_MODEL") or OPENROUTER_MODEL_DEFAULT).strip()


def _post_with_retries(headers: Dict[str, str], body: Dict[str, Any]) -> requests.Response:
    last_exc: Optional[BaseException] = None
    for attempt in range(1, MAX_RETRIES + 2):
        try:
            resp = requests.post(OPENROUTER_ENDPOINT, headers=headers, json=body, timeout=TIMEOUT_SEC)
            if resp.status_code // 100 == 2:
                return resp
            else:
                logger.warning(f"Non-200 response ({resp.status_code}): {resp.text}")
        except Exception as e:
            last_exc = e
            logger.warning(f"Retry {attempt}/{MAX_RETRIES + 1} failed: {e}")
            time.sleep(RETRY_BACKOFF_SEC * attempt)
    raise RuntimeError(f"OpenRouter call failed after retries: {last_exc}")


def _safe_parse_json(text: str) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(text)
    except Exception:
        try:
            start = text.find("{")
            end = text.rfind("}")
            if start != -1 and end != -1:
                return json.loads(text[start: end + 1])
        except Exception:
            return None
    return None


def _normalize_result(obj: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "summary": str(obj.get("summary", "")).strip(),
        "no_changes": bool(obj.get("no_changes", False)),
        "clean_findings": list(obj.get("clean_findings", []))[:10],
        "minor_issues": list(obj.get("minor_issues", []))[:10],
        "major_issues": list(obj.get("major_issues", []))[:10],
        "patches": list(obj.get("patches", []))[:15],
        "rewritten": "",  # no longer used — kept for backwards compat
        "confidence": float(obj.get("confidence", 0.0)),
    }


def _extract_snippets(code: str, flagged_lines: List[int], context: int = SNIPPET_CONTEXT) -> str:
    """Return only the lines around flagged issues instead of the full file.

    If the snippets cover >70% of the file anyway, just return the full code.
    Each snippet is prefixed with line numbers so the LLM can reference them.
    """
    code_lines = code.splitlines()
    n = len(code_lines)
    if not flagged_lines or n == 0:
        return "\n".join(f"{i+1:4d}: {ln}" for i, ln in enumerate(code_lines))

    # Build set of line indices to include
    indices: set = set()
    for ln in flagged_lines:
        lo = max(0, ln - context - 1)
        hi = min(n, ln + context)
        indices.update(range(lo, hi))

    # If snippets cover most of the file, send the whole thing (already small)
    if len(indices) >= n * 0.7:
        return "\n".join(f"{i+1:4d}: {ln}" for i, ln in enumerate(code_lines))

    # Build snippet with separators between non-contiguous ranges
    result: List[str] = []
    prev = -2
    for i in sorted(indices):
        if i > prev + 1:
            result.append(f"     # ... lines {prev + 2}–{i} omitted ...")
        result.append(f"{i+1:4d}: {code_lines[i]}")
        prev = i
    return "\n".join(result)


def _build_messages(code: str, language: str, flagged_lines: Optional[List[int]] = None) -> List[Dict[str, str]]:
    """Build a cost-efficient prompt.

    Instead of sending the full file, we send only the snippets around flagged lines.
    The LLM returns surgical patches (line number + original → replacement) rather
    than a full rewrite — much cheaper in both input and output tokens.
    """
    lang = (language or "").strip() or "Python"
    lang_lower = lang.lower()

    hints = {
        "Python": (
            "- Avoid print/log in hot loops; prefer buffering or batching.\n"
            "- Preallocate or use NumPy for vectorized operations.\n"
            "- Be mindful of the GIL in CPU-bound threads.\n"
        ),
        "Java": (
            "- Avoid synchronization in hot paths; minimize allocations/GC.\n"
            "- Use primitive collections/pooling and StringBuilder.\n"
            "- Prefer NIO; avoid blocking I/O in tight loops.\n"
        ),
        "C++": (
            "- Avoid reallocations; reserve; align/cache-friendly layouts.\n"
            "- Prefer move semantics; minimize virtual calls in hot loops.\n"
            "- Consider SIMD/vectorization and reduce branches.\n"
        ),
    }

    snippet = _extract_snippets(code, flagged_lines or [], SNIPPET_CONTEXT)
    lines_sent = snippet.count("\n") + 1
    total_lines = code.count("\n") + 1
    context_note = (
        f"(showing {lines_sent}/{total_lines} lines around flagged locations)"
        if lines_sent < total_lines else ""
    )

    system_msg = (
        "You are a battle-tested low-latency systems engineer. "
        "Be concise and return only valid JSON with no extra text."
    )

    user_msg = (
        f"Review this {lang} code for latency issues. {context_note}\n\n"
        "Check for:\n"
        "- Allocation/GC pressure\n"
        "- I/O or syscalls in tight loops\n"
        "- Lock contention / atomics misuse\n"
        "- Cache unfriendly access patterns\n"
        "- CPU-unfriendly constructs\n"
        "- Vectorization/batching opportunities\n\n"
        f"Language notes:\n{hints.get(lang, '')}\n"
        "Return STRICT JSON with this exact schema:\n"
        "{\n"
        '  "summary": "one sentence",\n'
        '  "no_changes": true|false,\n'
        '  "clean_findings": ["..."],\n'
        '  "minor_issues": [{"issue":"...","why":"...","fix":"...","snippet":"..."}],\n'
        '  "major_issues": [{"issue":"...","why":"...","fix":"...","snippet":"..."}],\n'
        '  "patches": [\n'
        '    {"line": <line_number>, "original": "<exact line from code>", "replacement": "<fixed line>", "why": "<short reason>"}\n'
        '  ],\n'
        '  "confidence": 0.0\n'
        "}\n\n"
        "Rules for patches:\n"
        "- One patch per issue found\n"
        "- 'original' must be the exact line from the code (copy it verbatim)\n"
        "- 'replacement' is the fixed single line (or a few lines if needed)\n"
        "- Skip patch if the fix requires a large architectural change\n\n"
        f"Code:\n```{lang_lower}\n{snippet}\n```\n"
    )

    return [
        {"role": "system", "content": system_msg},
        {"role": "user", "content": user_msg},
    ]


def _extract_choice_text(resp_json: Dict[str, Any]) -> str:
    try:
        choices = resp_json.get("choices") or []
        if not choices:
            return ""
        msg = choices[0].get("message") or {}
        content = msg.get("content")
        if isinstance(content, str):
            return content
    except Exception:
        pass
    return ""


def query_llm_with_code(code: str, language: str, flagged_lines: Optional[List[int]] = None) -> str:
    """Call OpenRouter for a latency-focused review.

    flagged_lines: line numbers from static analysis — used to send only
    the relevant code snippets instead of the full file, cutting token cost.

    Returns a JSON string (normalized) or raw text on error.
    """
    key = _get_api_key()
    if not key:
        return "❌ Missing API key. Set OPENROUTER_API_KEY in .env or Streamlit secrets."

    model = _get_model()
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }

    messages = _build_messages(code, language, flagged_lines)
    body: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": GEN_CFG.get("temperature", 0.2),
        "top_p": GEN_CFG.get("top_p", 0.9),
        "max_tokens": GEN_CFG.get("max_tokens", 700),
        "response_format": {"type": "json_object"},
    }

    try:
        resp = _post_with_retries(headers, body)
    except Exception as e:
        logger.error(f"OpenRouter request failed: {e}", exc_info=False)
        return f"❌ Network error contacting LLM: {e}"

    try:
        data = resp.json()
    except Exception:
        snippet = (resp.text or "")[:500]
        return f"❌ Invalid response from LLM: {snippet}"

    text = _extract_choice_text(data)
    if not text:
        return f"❌ Empty response from LLM: {json.dumps(data)[:400]}"

    parsed = _safe_parse_json(text)
    if parsed is not None:
        try:
            normalized = _normalize_result(parsed)
            return json.dumps(normalized)
        except Exception:
            pass

    fallback = {
        "summary": text.strip()[:1200],
        "no_changes": False,
        "clean_findings": [],
        "minor_issues": [],
        "major_issues": [],
        "patches": [],
        "rewritten": "",
        "confidence": 0.0,
    }
    return json.dumps(fallback)
