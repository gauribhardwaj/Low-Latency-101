import json
import re

class LatencyAnalyzer:
    def __init__(self, language):
        self.language = language
        self.rules = self.load_rules(language)

    def load_rules(self, lang):
        path = f"latency_engine/rules/{lang.lower()}_rules.json"
        with open(path, "r") as f:
            return json.load(f)

    def analyze(self, code):
        issues = []
        score = 100

        for rule in self.rules:
            if re.search(rule["pattern"], code, re.MULTILINE):
                score -= rule["penalty"]
                issues.append({
                    "rule": rule["rule"],
                    "message": rule["message"]
                })

        return {
            "issues": issues,
            "score": max(score, 0)
        }
