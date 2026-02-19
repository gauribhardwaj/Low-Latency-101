import requests

for i in range(100):
    r = requests.get("http://example.com")  # network call in loop
    _ = r.status_code

