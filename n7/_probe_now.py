import json, os, sys, urllib.request, urllib.error

KEY = os.environ["ARK_API_KEY"]
BASE = "https://ark.cn-beijing.volces.com/api/v3"

req = urllib.request.Request(BASE + "/models", headers={"Authorization": "Bearer " + KEY})
data = json.load(urllib.request.urlopen(req, timeout=60))["data"]
text_models = [m["id"] for m in data
               if (m.get("modalities") or {}).get("output_modalities") == ["text"]]

ok = []
for m in text_models:
    body = {"model": m, "messages": [{"role": "user", "content": "只回两个字：正常"}], "max_tokens": 32}
    r = urllib.request.Request(BASE + "/chat/completions", data=json.dumps(body).encode(),
                               headers={"Authorization": "Bearer " + KEY,
                                        "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(r, timeout=120) as resp:
            d = json.loads(resp.read())
        ok.append((m, (d["choices"][0]["message"].get("content") or "").strip()[:20], d.get("usage")))
        print("OK  ", m, "->", ok[-1][1], ok[-1][2])
    except urllib.error.HTTPError as e:
        t = e.read().decode("utf-8", "replace")
        code = "ModelNotOpen" if "ModelNotOpen" in t else f"HTTP{e.code}"
        print("FAIL", m, code)

print("\n可用模型:", [x[0] for x in ok])
