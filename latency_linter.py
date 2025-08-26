import re

rulebook = {
    "Python": [
        {
            "rule": "Print in Loop",
            "pattern": r"for\s+\w+\s+in\s+.*:\s*\n\s*print",
            "penalty": 10,
            "message": "Avoid printing in loops — it causes I/O delay."
        }
    ],
    "Java": [
        {
            "rule": "GC Allocation in Loop",
            "pattern": r"for\s*\(.*\)\s*\{[^}]*new\s+\w+",
            "penalty": 20,
            "message": "Avoid using `new` inside loops. Pre-allocate or use pooling."
        }
    ],
    "C++": [
        {
            "rule": "Malloc in Loop",
            "pattern": r"for\s*\(.*\)\s*\{[^}]*malloc",
            "penalty": 25,
            "message": "Avoid `malloc` in hot paths — use stack or pooling."
        }
    ]
}

def analyze_code(code, language):
    issues = []
    score = 100

    for rule in rulebook.get(language, []):
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
