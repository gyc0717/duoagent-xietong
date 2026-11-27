#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P2 · LLM-as-judge（锁定 rubric）—— 只看一页总结的切题度与忠实度

规矩（方案里的评测纪律）：
  - 裁判厂商 ≠ 产出方厂商（总结是豆包写的，裁判用千问）
  - 模型与 rubric 锁版本，temperature 固定，结果落盘可追溯
  - 分数只作信号；运行时拦截仍由确定性门禁做

跑法：python eval/judge.py
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / "n1q"))

import qwen_client  # noqa: E402

RUBRIC = "rubric-v1.6-lock"
JUDGE_MODEL = "qwen-plus"

SYSTEM = f"""你是离线裁判，rubric 版本 {RUBRIC}，被评对象是一段面向人的一页总结。
只输出 JSON：{{"score":1-5,"faithfulness":"high|medium|low","relevance":"high|medium|low","issues":["..."]}}
评分标准（锁定，不得自创）：
5 = 数字与工件完全一致、口径正确、切题、无冗余
4 = 数字与工件一致、口径正确，仅措辞/结构有小瑕疵
3 = 数字全对但偏离重点或有误导性表述
2 = 出现与工件不一致的数字或口径
1 = 大面积错误或答非所问
 faithfulness：总结里任何数字能否追溯到工件；relevance：是否回应了任务（Q4 经营复盘）。"""


def main() -> int:
    sd = json.loads((PROJECT / "real" / "out" / "structured_data.json").read_text(encoding="utf-8"))
    n7 = json.loads((PROJECT / "n7" / "out" / "n7_report.json").read_text(encoding="utf-8"))
    summary = n7["summary_md"]

    usage = qwen_client.Usage()
    res = qwen_client.chat([
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": json.dumps({"summary": summary, "structured_data": sd},
                                               ensure_ascii=False)},
    ], model=JUDGE_MODEL, max_tokens=600, usage=usage)

    m = re.search(r"\{.*\}", res["content"], re.S)
    verdict = json.loads(m.group(0)) if m else {"score": 0, "error": "裁判没有输出合法 JSON"}
    verdict.update({
        "judge_model": JUDGE_MODEL,
        "judge_model_pinned": True,
        "rubric_version": RUBRIC,
        "temperature": 0.3,
        "judged_summary_sha": __import__("hashlib").sha256(summary.encode()).hexdigest()[:16],
        "judged_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "usage": {"tokens": usage.total_tokens, "latency_ms": usage.latency_ms,
                  "est_cny": usage.cost_cny(JUDGE_MODEL)},
    })
    out = PROJECT / "eval" / "judge_report.json"
    out.write_text(json.dumps(verdict, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(verdict, ensure_ascii=False, indent=2))
    return 0 if verdict.get("score", 0) >= 4 else 1


if __name__ == "__main__":
    raise SystemExit(main())
