import json
import os
import re
import logging
from typing import Dict, List

from .detectors import PythonDetector, JavaDetector, CppDetector
from .providers.semgrep_provider import run_semgrep

logger = logging.getLogger(__name__)

class LatencyAnalyzer:
    def __init__(self, language):
        self.language = language
        self.rules = self.load_rules(language)

    def load_rules(self, lang):
        lname = (lang or "").lower()
        if lname in ("c++", "cxx"):
            lname = "cpp"
        path = f"latency_engine/rules/{lname}_rules.json"
        with open(path, "r") as f:
            rules = json.load(f)
        try:
            logger.info("LatencyAnalyzer: loaded %d rules for %s from %s", len(rules), lname, path)
        except Exception:
            pass
        return rules

    def analyze(self, code: str) -> Dict:
        issues: List[Dict] = []
        positive_signals: List[str] = []
        score = 100

        logger.info("LatencyAnalyzer: analyze start (language=%s)", self.language)

        # Pipeline selection: default to detectors-only for Python; detector+regex for others.
        lang = (self.language or "").lower()
        default_pipeline = "detector" if lang == "python" else "detector+regex"
        pipeline = os.getenv("LATENCY_PIPELINE", default_pipeline)
        steps = [s.strip().lower() for s in pipeline.replace(",", "+").split("+") if s.strip()]
        logger.info("LatencyAnalyzer: pipeline=%s", "+".join(steps))

        # Step: semgrep (if configured)
        if "semgrep" in steps:
            sg = run_semgrep(self.language, code, rules_dir=os.getenv("SEMGREP_RULES_DIR"))
            if sg is None:
                logger.info("LatencyAnalyzer: semgrep skipped (not available)")
            else:
                logger.info("LatencyAnalyzer: semgrep issues=%d", len(sg.get("issues", [])))
                for it in sg.get("issues", []):
                    penalty = int(it.get("penalty", 0))
                    score -= penalty
                    issues.append({
                        "rule": it.get("rule", "Semgrep finding"),
                        "message": it.get("message", ""),
                        "penalty": penalty,
                    })

        # Step: detector (language-specific)
        if "detector" in steps:
            detector_res = None
            if lang == "python":
                detector_res = PythonDetector(code).analyze()
            elif lang == "java":
                detector_res = JavaDetector(code).analyze()
            elif lang in ("c++", "cpp", "cxx"):
                detector_res = CppDetector(code).analyze()

            if detector_res is not None:
                logger.info(
                    "LatencyAnalyzer: detector phase (issues=%d, positives=%d)",
                    len(detector_res.issues),
                    len(detector_res.positive_signals),
                )
                for it in detector_res.issues:
                    penalty = int(it.get("penalty", 0))
                    score -= penalty
                    issues.append({
                        "rule": it.get("rule", "Detector finding"),
                        "message": it.get("message", ""),
                        "penalty": penalty,
                    })
                positive_signals.extend(detector_res.positive_signals)

        # Step: regex (legacy rules)
        if "regex" in steps:
            matched_rules = 0
            for rule in self.rules:
                try:
                    if re.search(rule["pattern"], code, re.MULTILINE):
                        penalty = int(rule.get("penalty", 0))
                        score -= penalty
                        issues.append({
                            "rule": rule.get("rule", "Pattern match"),
                            "message": rule.get("message", "Matched rule pattern."),
                            "penalty": penalty,
                        })
                        matched_rules += 1
                except re.error:
                    continue
            logger.info("LatencyAnalyzer: regex phase matched %d rules", matched_rules)

        final = {
            "issues": issues,
            "score": max(score, 0),
            "signals": {
                "positive": positive_signals,
            },
        }

        logger.info(
            "LatencyAnalyzer: analyze end (final_score=%d, total_issues=%d, positives=%d)",
            final["score"],
            len(issues),
            len(positive_signals),
        )

        return final
