#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""预算持久化：单轮花费落盘，重启后仍然生效，便于事后举证 402。

为什么需要：预算上限如果只存在内存里，重启即清零，401/402 这条路径就无法用
真实 HTTP 请求复盘。落盘后 gateway_calls.jsonl 里的 402 可被独立复现。
"""
from pathlib import Path

P = Path(__file__).resolve().parent / "gateway.py"
s = P.read_text(encoding="utf-8")
n0 = len(s)

s = s.replace(
    'RUN_BUDGET_CNY = 2.0          # 单轮硬上限\nRUN_SPENT: dict[str, float] = {}\nMODEL_CALLS: dict[str, int] = {}',
    'RUN_BUDGET_CNY = 2.0          # 单轮硬上限\nBUDGET_FILE = WS_ROOT / "model_budget.json"\n\n\n'
    'def _load_budget() -> dict:\n'
    '    try:\n'
    '        return json.loads(BUDGET_FILE.read_text(encoding="utf-8"))\n'
    '    except Exception:\n'
    '        return {}\n'
    '\n'
    '\n'
    'def _save_budget(data: dict) -> None:\n'
    '    try:\n'
    '        BUDGET_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")\n'
    '    except Exception:\n'
    '        pass\n'
    '\n'
    '\n'
    'RUN_SPENT: dict[str, float] = _load_budget()\nMODEL_CALLS: dict[str, int] = {}',
    1,
)

s = s.replace(
    '    RUN_SPENT[run_id] = round(RUN_SPENT.get(run_id, 0.0) + cost_cny, 6)\n'
    '    MODEL_CALLS[run_id] = MODEL_CALLS.get(run_id, 0) + 1',
    '    RUN_SPENT[run_id] = round(RUN_SPENT.get(run_id, 0.0) + cost_cny, 6)\n'
    '    MODEL_CALLS[run_id] = MODEL_CALLS.get(run_id, 0) + 1\n'
    '    _save_budget(RUN_SPENT)',
    1,
)

P.write_text(s, encoding="utf-8")
print("预算持久化补丁：", n0, "->", len(s), "字符")
