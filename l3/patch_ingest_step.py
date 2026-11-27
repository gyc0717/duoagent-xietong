#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""补上 /run/ingest：文件限定在 real/data 下，口径必须显式。"""
from pathlib import Path

P = Path(__file__).resolve().parent / "gateway.py"
s = P.read_text(encoding="utf-8")
n0 = len(s)

s = s.replace(
    '    "report": {"script": "real/report.py",      "artifact": "real/out/final_report.md"},',
    '    "report": {"script": "real/report.py",      "artifact": "real/out/final_report.md"},\n'
    '    "ingest": {"script": "real/ingest.py",      "artifact": "real/out/ingest_report.json"},',
    1,
)

OLD = '''def run_step(name: str) -> tuple[int, dict]:'''
NEW = '''DATA_ROOT = PROJECT / "real" / "data"


def run_step(name: str, body: dict | None = None) -> tuple[int, dict]:'''
assert OLD in s
s = s.replace(OLD, NEW, 1)

OLD2 = '''    out = subprocess.run([sys.executable, str(script)], capture_output=True, text=True,:'''
OLD2 = '''    out = subprocess.run([sys.executable, str(script)], capture_output=True, text=True,
                         encoding="utf-8", errors="replace", timeout=300, cwd=str(PROJECT))'''
NEW2 = '''    args = [sys.executable, str(script)]
    if name == "ingest":
        body = body or {}
        fname = str(body.get("file") or "").strip()
        caliber = str(body.get("caliber") or "").strip()
        if not fname or not caliber:
            return 400, {"ok": False, "error": "ingest 需要 file 与 caliber（started/completed）"}
        target = (DATA_ROOT / fname).resolve()
        if DATA_ROOT.resolve() not in target.parents:
            return 403, {"ok": False, "error": "只允许 real/data 下的文件"}
        if not target.exists():
            return 404, {"ok": False, "error": f"文件不存在：{target.name}"}
        if caliber not in ("started", "completed"):
            return 400, {"ok": False, "error": "caliber 只能是 started / completed"}
        args += [str(target), "--caliber", caliber]
    out = subprocess.run(args, capture_output=True, text=True,
                         encoding="utf-8", errors="replace", timeout=300, cwd=str(PROJECT))'''
assert OLD2 in s
s = s.replace(OLD2, NEW2, 1)

s = s.replace('                    code, payload = run_step(self.path[len("/run/"):])',
              '                    code, payload = run_step(self.path[len("/run/"):], body)', 1)

P.write_text(s, encoding="utf-8")
print("ingest 端点补丁：", n0, "->", len(s), "字符")
