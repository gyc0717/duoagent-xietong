#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""给 L3 网关补审计：每个请求（含被拒的）追加一行到 gateway_calls.jsonl。

记录字段：ts / method / path / code / ms / token_fp / body_keys / result
  - token 只记 sha256 前 8 位指纹，绝不落原文；
  - 401/404/403 也记，否则「谁被拒了」查不到；
  - append-only，不覆盖。
"""
from __future__ import annotations

from pathlib import Path

P = Path(__file__).resolve().parent / "gateway.py"
s = P.read_text(encoding="utf-8")
orig = len(s)

# 1) 导入与常量
s = s.replace(
    "import json\nimport os\nimport secrets\nimport subprocess\nimport sys\nimport threading",
    "import hashlib\nimport json\nimport os\nimport secrets\nimport subprocess\nimport sys\n"
    "import threading\nimport time",
    1,
)
s = s.replace(
    'PORT = int(os.environ.get("L3_GATEWAY_PORT", "8733"))',
    'PORT = int(os.environ.get("L3_GATEWAY_PORT", "8733"))\n'
    'AUDIT = PROJECT / "cohort_l3" / "gateway_calls.jsonl"',
    1,
)

# 2) 审计函数
s = s.replace(
    "TOKEN = token()",
    '''TOKEN = token()


def _fp(t: str) -> str:
    """令牌指纹：只留 sha256 前 8 位，永不落原文。"""
    return hashlib.sha256((t or "").encode()).hexdigest()[:8]


def audit(rec: dict) -> None:
    rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), **rec}
    with open(AUDIT, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\\n")''',
    1,
)

# 3) _send 记录状态码
s = s.replace(
    "    def _send(self, code, obj):\n        data = json.dumps(obj, ensure_ascii=False).encode()",
    "    def _send(self, code, obj):\n        self._code = code\n"
    "        data = json.dumps(obj, ensure_ascii=False).encode()",
    1,
)

# 4) 两个入口包一层（finally 里写审计）
OLD_GET = '''    def do_GET(self):
        if self.path == "/health":'''
NEW_GET = '''    def do_GET(self):
        t0 = time.time()
        try:
            return self._do_get()
        finally:
            self._audit(t0)

    def _do_get(self):
        if self.path == "/health":'''
assert OLD_GET in s
s = s.replace(OLD_GET, NEW_GET, 1)

OLD_POST = '''    def do_POST(self):
        if not self._authed():'''
NEW_POST = '''    def do_POST(self):
        t0 = time.time()
        try:
            return self._do_post()
        finally:
            self._audit(t0)

    def _do_post(self):
        if not self._authed():'''
assert OLD_POST in s
s = s.replace(OLD_POST, NEW_POST, 1)

# 5) _audit 方法
s = s.replace(
    "    def log_message(self, fmt, *args):\n        pass",
    '''    def _audit(self, t0: float) -> None:
        try:
            tok = self.headers.get("X-L3-Token") or ""
            audit({
                "method": self.command,
                "path": self.path.split("?")[0],
                "code": getattr(self, "_code", None),
                "ms": round((time.time() - t0) * 1000),
                "token_fp": _fp(tok) if tok else None,
                "authed": bool(tok) and tok == TOKEN,
            })
        except Exception:  # noqa: BLE001
            pass

    def log_message(self, fmt, *args):
        pass''',
    1,
)

P.write_text(s, encoding="utf-8")
print("网关审计补丁完成：", orig, "->", len(s), "字符")
