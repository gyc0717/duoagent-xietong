#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""网关加确定性步骤端点：/run/charts、/run/index、/run/report。

与 /model 同样的原则：脚本路径写死，请求只能选 name，不能指定脚本或任意路径。
返回 artifact（文件 + sha256），供 Honey 记进步骤。
"""
from pathlib import Path

P = Path(__file__).resolve().parent / "gateway.py"
s = P.read_text(encoding="utf-8")
n0 = len(s)

TABLE = '''
# ---------------- 确定性步骤：脚本路径写死 ----------------
STEPS = {
    "charts": {"script": "real/charts_real.py", "artifact": "real/out/chart_data.json"},
    "index":  {"script": "real/file_index.py",  "artifact": "real/out/file_index.json"},
    "report": {"script": "real/report.py",      "artifact": "real/out/final_report.md"},
}


def run_step(name: str) -> tuple[int, dict]:
    import hashlib
    cfg = STEPS.get(name)
    if not cfg:
        return 404, {"ok": False, "error": f"未知步骤 {name!r}；可用：{sorted(STEPS)}"}
    script = PROJECT / cfg["script"]
    if not script.exists():
        return 500, {"ok": False, "error": f"脚本缺失：{script}"}
    out = subprocess.run([sys.executable, str(script)], capture_output=True, text=True,
                         encoding="utf-8", errors="replace", timeout=300, cwd=str(PROJECT))
    art = PROJECT / cfg["artifact"]
    if out.returncode != 0:
        return 500, {"ok": False, "error": "脚本失败",
                     "detail": (out.stderr or out.stdout or "")[-300:]}
    if not art.exists():
        return 500, {"ok": False, "error": f"产物缺失：{art.name}"}
    sha = hashlib.sha256(art.read_bytes()).hexdigest()[:16]
    return 200, {"ok": True, "step": name, "artifact": f"{art.name}",
                 "uri": str(art.relative_to(PROJECT)).replace("\\\\", "/"),
                 "sha256": sha, "stdout_tail": (out.stdout or "").strip().splitlines()[-2:]}


'''

anchor = "class H(BaseHTTPRequestHandler):"
assert anchor in s
s = s.replace(anchor, TABLE + anchor, 1)

OLD = '''            if self.path == "/model":'''
NEW = '''            if self.path.startswith("/run/"):
                with LOCK:
                    code, payload = run_step(self.path[len("/run/"):])
                return self._send(code, payload)
            if self.path == "/model":'''
assert OLD in s
s = s.replace(OLD, NEW, 1)

P.write_text(s, encoding="utf-8")
print("确定性步骤端点补丁：", n0, "->", len(s), "字符")
