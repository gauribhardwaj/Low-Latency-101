import logging
from typing import Dict

from .detectors import PythonDetector, JavaDetector, CppDetector

logger = logging.getLogger(__name__)


class LatencyAnalyzer:
    def __init__(self, language: str):
        self.language = language

    def analyze(self, code: str) -> Dict:
        lang = (self.language or "").lower()
        logger.info("LatencyAnalyzer: analyze start (language=%s)", lang)

        detector_res = None
        if lang == "python":
            detector_res = PythonDetector(code).analyze()
        elif lang == "java":
            detector_res = JavaDetector(code).analyze()
        elif lang in ("c++", "cpp", "cxx"):
            detector_res = CppDetector(code).analyze()

        issues = []
        positive_signals = []
        score = 100

        if detector_res is not None:
            logger.info(
                "LatencyAnalyzer: detector done (issues=%d, positives=%d)",
                len(detector_res.issues),
                len(detector_res.positive_signals),
            )
            for it in detector_res.issues:
                penalty = int(it.get("penalty", 0))
                score -= penalty
                issues.append({
                    "rule":    it.get("rule", "Detector finding"),
                    "message": it.get("message", ""),
                    "penalty": penalty,
                    "line":    it.get("line"),
                })
            positive_signals.extend(detector_res.positive_signals)

        result = {
            "issues":  issues,
            "score":   max(score, 0),
            "signals": {"positive": positive_signals},
        }

        logger.info(
            "LatencyAnalyzer: done (score=%d, issues=%d, positives=%d)",
            result["score"], len(issues), len(positive_signals),
        )
        return result
