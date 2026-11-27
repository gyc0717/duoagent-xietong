#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""口径规则引擎（任务 4）

从 N1Q 那次的教训固化出来，供所有「数值提取/引用校验」环节复用：

  规则 1  指标词与数值必须同句
  规则 2  退货率类指标，数值必须**紧邻**指标词（防目录、表格抬头误判）
  规则 3  三组口径互不替代：退货率 / 退货行为 / 投诉售后
  规则 4  目录/示意/导航类句子直接排除
  规则 5  答案里出现的百分比，必须能在已抓取文本里找到出处（不信模型自述）

用法：
    from caliber import extract, judge_answer
    hits = extract(page_text)                 # {口径: [命中句]}
    bad  = judge_answer(answer, texts)         # [(数值, 原因)]
"""
from __future__ import annotations

import re
import sys

GROUPS: list[tuple[str, tuple[str, ...]]] = [
    ("退货率", ("退货率", "退货比率", "退货比例为")),
    ("退货行为", ("退换货", "退货")),
    ("投诉售后", ("投诉", "售后")),
]

NUM = re.compile(r"\d[\d,.]*\s*(?:%|％|个百分点|万|亿|单|件|起|倍)")
PCT = re.compile(r"(\d[\d,.]*)\s*(?:%|％)")

# 数值必须紧挨指标词：词在前（退货率达 3.1%）或数在前（3.1% 的退货率）
RR_PROX = re.compile(
    r"退货率[^。；;\n]{0,6}?(?:为|达|约|是|：|:)?\s*\d[\d,.]*\s*(?:%|％|个百分点)"
    r"|(\d[\d,.]*\s*(?:%|％|个百分点))\s*的?退货率"
)

JUNK_MARKS = ("已知事实", "示意", "以下数据对比", "目录", "摘要：", "点击查看", "登录后", "版权所有")
SENT_SPLIT = re.compile(r"(?<=[。！？；;!?])|\n+")


def sentences(text: str) -> list[str]:
    out = []
    for s in SENT_SPLIT.split(text or ""):
        s = re.sub(r"\s+", " ", s or "").strip()
        if len(s) >= 8:
            out.append(s)
    return out


def classify(sentence: str) -> str | None:
    """返回该句所属口径；退货率必须满足「数值紧邻」，否则不算。"""
    if not NUM.search(sentence):
        return None
    for group, kws in GROUPS:
        if not any(k in sentence for k in kws):
            continue
        if group == "退货率" and not RR_PROX.search(sentence):
            continue
        if any(j in sentence for j in JUNK_MARKS):
            continue
        return group
    return None


def extract(text: str) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {g: [] for g, _ in GROUPS}
    for s in sentences(text):
        g = classify(s)
        if g:
            out[g].append(s[:160])
    return out


def judge_answer(answer: str, evidence_texts: list[str]) -> list[tuple[str, str]]:
    """答案里的百分比必须能在证据文本中找到；否则算编造。"""
    joined = "\n".join(evidence_texts)
    bad = []
    for m in PCT.finditer(answer or ""):
        raw = m.group(1)
        if raw not in joined:
            bad.append((raw, "证据文本里找不到这个数值"))
    return bad


def caliber_label(sentence: str) -> str | None:
    return classify(sentence)


# ------------------------------- 自测 -------------------------------
CASES = [
    ("退货率紧邻数值", "本届双11家电品类退货率为3.2%，高于往年。", "退货率"),
    ("数值在前的写法", "3.2% 的退货率，是今年家电大促的常态。", "退货率"),
    ("目录式误判（应 None）", "AI 家电的退货率与换货率各城市门店的 AI 家电可售率", None),
    ("示意表（应 None）", "以下数据对比了典型家电厂商，综合毛利率28%，营销费用率8%", None),
    ("投诉口径", "日用电器投诉量环比增长32.66%，创近三年新高。", "投诉售后"),
    ("退货行为口径", "大促后退换货申请量达 1.2 万件，部分门店排队处理。", "退货行为"),
]


def selftest() -> int:
    ok = 0
    for name, text, expect in CASES:
        got = (extract(text) and next((g for g, v in extract(text).items() if v), None))
        good = got == expect
        ok += good
        print(f"{'✓' if good else '✗'} {name}: 期望 {expect} 实际 {got}")
    bad = judge_answer("退货率约 9.99%，投诉 32.66%", ["投诉 32.66%"])
    good = len(bad) == 1 and bad[0][0] == "9.99"
    ok += good
    print(f"{'✓' if good else '✗'} 编造数值识别: {bad}")
    print(f"\n{ok}/{len(CASES) + 1} 通过")
    return 0 if ok == len(CASES) + 1 else 1


if __name__ == "__main__":
    sys.exit(selftest())
