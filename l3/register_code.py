#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 N2（DeepSeek 编程）的真实产物登记进 L3 —— 代码也是工件，也要 sha256。

之前 N2 只存在于"我写了几个脚本"，登记表里没有记录，验收第 1 项因此判 N2 缺失。
跑法：python l3/register_code.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / "l3"))

from workspace import Workspace, sha256_file  # noqa: E402

CODE = [
    ("data_exec", "real/data_exec.py", "结构化数据执行器（P3 落地）"),
    ("charts", "real/charts.py", "确定性 SVG 渲染器（N3 兜底）"),
    ("sandbox_verify", "real/verify.py", "9 类确定性检查执行器（P1 落地）"),
    ("scale_fix", "n3/fix_scale.py", "信息图刻度标注修复"),
]


def main() -> int:
    ws = Workspace(PROJECT / "cohort_l3").ensure()
    made = []
    for name, rel, desc in CODE:
        p = PROJECT / rel
        if not p.exists():
            print(f"跳过（不存在）：{rel}")
            continue
        # 认领记录必须先有（L3_REQUIRE_CLAIM 打开时的前置条件）
        claim = ws.root / "claims" / "N2.json"
        if not claim.exists():
            claim.parent.mkdir(parents=True, exist_ok=True)
            claim.write_text(json.dumps(
                {"node": "N2", "role": "dsh_coder", "vendor": "DeepSeek",
                 "context_mode": "FULL", "truncation": False,
                 "fulltext_on_demand": True, "trust_channel_separation": True},
                ensure_ascii=False, indent=2), encoding="utf-8")
        rec = ws.register(node="N2", role="dsh_coder", name=name,
                          payload={"file": rel, "sha256": sha256_file(p),
                                   "bytes": p.stat().st_size, "desc": desc},
                          content_mode="FULLTEXT", trust_level="trusted", channel="both",
                          provenance="DeepSeek/N2 编程")
        made.append((name, rec["id"], rec["vendor"]))
        print(f"✓ {name:16} {rec['id']}  {sha256_file(p)[:12]}  {p.stat().st_size} B")
    print(json.dumps({"registered": len(made), "vendor": "DeepSeek"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
