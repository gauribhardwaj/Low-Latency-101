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
GEN_CFG = {"temperature": 0.2, "max_tokens": 900, "top_p": 0.9}
TIMEOUT_SEC = 30
MAX_RETRIES = 2
RETRY_BACKOFF_SEC = 1.5


# ---------- Helpers ----------
def _get_api_key() -> str:
    """Fetch the OpenRouter API key dynamically each call."""
    key = (os.getenv("OPENROUTER_API_KEY") or "").strip()
    if not key:
        try:
            import streamlit as st  # type: ignore
            key = (st.secrets.get("OPENROUTER_API_KEY") or "").strip()
        except Exception:
            pass
    return key


def _get_model() -> str:
    """Fetch model name or fallback to default."""
    return (os.getenv("OPENROUTER_MODEL") or OPENROUTER_MODEL_DEFAULT).strip()


def _post_with_retries(headers: Dict[str, str], body: Dict[str, Any]) -> requests.Response:
    """Make API calls with retries and exponential backoff."""
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
    """Try to extract JSON from model output (even if wrapped in extra text)."""
    try:
        return json.loads(text)
    except Exception:
        try:
            start = text.find("{")
            end = text.rfind("}")
            if start != -1 and end != -1:
                return json.loads(text[start : end + 1])
        except Exception:
            return None
    return None


def _normalize_result(obj: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize model output structure."""
    return {
        "summary": str(obj.get("summary", "")).strip(),
        "no_changes": bool(obj.get("no_changes", False)),
        "clean_findings": list(obj.get("clean_findings", []))[:10],
        "minor_issues": list(obj.get("minor_issues", []))[:10],
        "major_issues": list(obj.get("major_issues", []))[:10],
        "rewritten": str(obj.get("rewritten", "")).strip(),
        "confidence": float(obj.get("confidence", 0.0)),
    }


def _build_messages(code: str, language: str) -> List[Dict[str, str]]:
    """Build structured prompt per language."""
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

    system_msg = (
        "You are a battle-tested low-latency systems engineer. "
        "Be concise and return only valid JSON with no extra text."
    )

    user_msg = (
        f"Evaluate this {lang} code for latency issues only.\n\n"
        "Check for:\n"
        "- Allocation/GC pressure or frequent small allocations\n"
        "- I/O or syscalls in tight loops\n"
        "- Cache locality / false sharing\n"
        "- Branch misprediction risks\n"
        "- Lock contention / atomics misuse\n"
        "- CPU-unfriendly constructs\n"
        "- Algorithmic hotspots\n"
        "- Vectorization/batching opportunities\n\n"
        f"Language notes:\n{hints.get(lang, '')}\n\n"
        "Return STRICT JSON exactly in this schema:\n"
        "{\n"
        '  "summary": "...",\n'
        '  "no_changes": true|false,\n'
        '  "clean_findings": ["..."],\n'
        '  "minor_issues": [{"issue":"...","why":"...","fix":"...","snippet":"..."}],\n'
        '  "major_issues": [{"issue":"...","why":"...","fix":"...","snippet":"..."}],\n'
        '  "rewritten": "optimized code if meaningful, otherwise empty string",\n'
        '  "confidence": 0.0\n'
        "}\n\n"
        "Code:\n"
        f"```{lang_lower}\n{code}\n```\n"
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


def query_llm_with_code(code: str, language: str) -> str:
    """Call OpenRouter for a latency-focused review.

    Returns a JSON string (normalized) when possible, otherwise raw text. Hard errors
    return a string beginning with '❌' so the UI can display them directly.
    """
    key = _get_api_key()
    if not key:
        return "❌ Missing API key. Set OPENROUTER_API_KEY in .env or Streamlit secrets."

    model = _get_model()
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }

    messages = _build_messages(code, language)
    body: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": GEN_CFG.get("temperature", 0.2),
        "top_p": GEN_CFG.get("top_p", 0.9),
        "max_tokens": GEN_CFG.get("max_tokens", 900),
        # Ask for strict JSON if the provider supports it (OpenAI-compatible param).
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

    # Try to extract JSON and normalize it; otherwise, return a JSON fallback
    # so the UI can render structured sections instead of plain text.
    parsed = _safe_parse_json(text)
    if parsed is not None:
        try:
            normalized = _normalize_result(parsed)
            return json.dumps(normalized)
        except Exception:
            # Fall through to raw text if normalization fails
            pass

    # Fallback: wrap raw text into the expected JSON shape
    fallback = {
        "summary": text.strip()[:1200],
        "no_changes": False,
        "clean_findings": [],
        "minor_issues": [],
        "major_issues": [],
        "rewritten": "",
        "confidence": 0.0,
    }
    return json.dumps(fallback)
