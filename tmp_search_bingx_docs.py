import re

import httpx


URL = "https://bingx-api.github.io/docs/static/js/app.4dcba784df17c52faa47.js"
js = httpx.get(URL, timeout=30).text
print("length", len(js))
for pattern in ["demo", "Demo", "testnet", "Testnet", "VST", "vst", "open-api", "sandbox", "Sandbox"]:
    print(pattern, js.find(pattern))

urls = sorted(set(re.findall(r"https?://[^\"'\\]+", js)))
for url in urls[:100]:
    print(url)
