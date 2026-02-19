import json
import logging
import os
import shutil
import subprocess
import tempfile
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


def _which_semgrep() -> Optional[str]:
    path = os.getenv("SEMGREP_BIN")
    if path and os.path.isfile(path):
        return path
    return shutil.which("semgrep")


def run_semgrep(language: str, code: str, rules_dir: Optional[str] = None) -> Optional[Dict]:
    """Run semgrep on the snippet if semgrep and rules are available.

    Returns a dict with keys: issues (list of {rule, message, penalty}).
    Returns None if semgrep is not available or misconfigured.
    """
    semgrep_bin = _which_semgrep()
    if not semgrep_bin:
        logger.info("Semgrep: binary not found; skipping")
        return None

    rules_dir = rules_dir or os.getenv("SEMGREP_RULES_DIR")
    if not rules_dir or not os.path.isdir(rules_dir):
        logger.info("Semgrep: rules directory missing; set SEMGREP_RULES_DIR; skipping")
        return None

    # Map language label to semgrep language hint if needed (not strictly required when using rules by path)
    lang_hint = language.lower()

    with tempfile.TemporaryDirectory(prefix="ll101_") as td:
        # Write code to a temp file with appropriate extension for semgrep
        ext = {
            "python": ".py",
            "java": ".java",
            "c++": ".cc",
            "cpp": ".cc",
            "cxx": ".cc",
        }.get(lang_hint, ".txt")
        tmp_src = os.path.join(td, f"snippet{ext}")
        with open(tmp_src, "w", encoding="utf-8", errors="ignore") as f:
            f.write(code)

        cmd = [
            semgrep_bin,
            "--config",
            rules_dir,
            "--json",
            "--quiet",
            tmp_src,
        ]

        try:
            logger.info("Semgrep: running on %s with rules %s", tmp_src, rules_dir)
            out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True)
        except subprocess.CalledProcessError as e:
            logger.warning("Semgrep failed: %s", e.output[:400])
            return None
        except Exception as e:
            logger.warning("Semgrep error: %s", e)
            return None

    try:
        data = json.loads(out)
    except Exception:
        logger.warning("Semgrep returned non-JSON output")
        return None

    results = data.get("results") or []
    if not results:
        return {"issues": []}

    # Map semgrep severity to penalty
    sev_to_pen = {
        "INFO": int(os.getenv("SEMGREP_PENALTY_INFO", "3")),
        "WARNING": int(os.getenv("SEMGREP_PENALTY_WARNING", "6")),
        "ERROR": int(os.getenv("SEMGREP_PENALTY_ERROR", "10")),
    }

    issues: List[Dict] = []
    for r in results:
        check_id = r.get("check_id", "semgrep-rule")
        extra = r.get("extra", {})
        msg = extra.get("message") or extra.get("metavars_message") or "Semgrep finding"
        sev = (extra.get("severity") or "INFO").upper()
        pen = sev_to_pen.get(sev, 5)
        issues.append({
            "rule": str(check_id),
            "message": str(msg),
            "penalty": int(pen),
        })

    logger.info("Semgrep: findings=%d", len(issues))
    return {"issues": issues}

