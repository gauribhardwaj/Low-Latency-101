import re

data = ["abc123", "def456"] * 100

for s in data:
    pat = re.compile(r"\d+")
    if pat.search(s):
        pass

