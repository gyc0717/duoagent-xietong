#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""统一编排器 —— 把能真跑的节点串成一条链路（默认复用已有模型产物，不重复花钱）

链路：N1Q 检索 → N3 生图 → N5 沙箱实证 → N5 异构复核（异厂）→ P2 评测门禁 → 交付汇总

用法：
  python run_chain.py            # 复用已有 N1Q / N3 产物，只跑沙箱+复核+评测（~1-2 分钟）
  python run_chain.py --regen    # 连模型节点一起重跑（4-8 分钟，会花钱）
  python run_chain.py --skip-hetero   # 不加钱跑复核（评测会因缺复核而 FAIL，属预期）
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

PROJECT = Path(__file__).resolve().parent
PY = sys.executable
OUTBOX = PROJECT / "cohort_l3" / "outbox"


def run_step(name: str, cmd: list[str], env_extra: dict | None = None,
             allow_fail: bool = False) -> dict:
    env = os.environ.copy()
    if env_extra:
        env.update(env_extra)
    t0 = time.perf_counter()
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", env=env, cwd=str(PROJECT))
    ms = round((time.perf_counter() - t0) * 1000)
    ok = proc.returncode == 0
    tail = (proc.stdout or "").strip().splitlines()[-6:]
    print(f"{'✓' if ok else '✗'} {name:22} {ms:>7} ms  rc={proc.returncode}")
    for line in tail:
        print(f"    {line[:150]}")
    if proc.returncode != 0:
        for line in (proc.stderr or "").strip().splitlines()[-6:]:
            print(f"    ! {line[:150]}")
    if not ok and not allow_fail:
        raise SystemExit(f"步骤失败：{name}")
    return {"name": name, "ms": ms, "ok": ok, "rc": proc.returncode, "tail": tail}


def artifact_fresh(path: Path, max_age_min: int = 240) -> bool:
    if not path.exists():
        return False
    age = (time.time() - path.stat().st_mtime) / 60
    return age <= max_age_min


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--regen", action="store_true", help="重跑 N1Q/N3 模型节点")
    ap.add_argument("--skip-hetero", action="store_true")
    ap.add_argument("--approve-publish", action="store_true",
                    help="硬垂询：消费过不可信内容后，发布前必须显式确认")
    args = ap.parse_args()

    steps: list[dict] = []
    sys.path.insert(0, str(PROJECT / "l3"))
    from workspace import Workspace  # noqa: E402  （仅用于打点）
    Workspace(PROJECT / "cohort_l3").ensure().ledger({"kind": "chain_start",
                                                      "regen": bool(args.regen)})
    steps.append(run_step("N5 沙箱实证", [PY, str(PROJECT / "l3" / "n5_executor.py")]))

    need_n1q = args.regen or not artifact_fresh(PROJECT / "n1q" / "out" / "N1Q_sources.json")
    need_n3 = args.regen or not artifact_fresh(PROJECT / "n3" / "out" / "n3_infographic.svg")

    if need_n1q and need_n3:
        # 入口并行 2/2：检索 ∥ 生图，互不依赖，实测墙钟应明显小于两段之和
        from concurrent.futures import ThreadPoolExecutor
        t0 = time.perf_counter()
        with ThreadPoolExecutor(max_workers=2) as pool:
            f1 = pool.submit(run_step, "N1Q 千问检索", [PY, str(PROJECT / "n1q" / "n1q_search.py")])
            f2 = pool.submit(run_step, "N3 Kimi 生图", [PY, str(PROJECT / "n3" / "n3_visuals.py")])
            s1, s2 = f1.result(), f2.result()
        wall = round((time.perf_counter() - t0) * 1000)
        summed = s1["ms"] + s2["ms"]
        steps += [s1, s2]
        ws_ledger = Workspace(PROJECT / "cohort_l3").ensure()
        ws_ledger.ledger({"kind": "parallel_entry", "nodes": ["N1Q", "N3"],
                          "wall_ms": wall, "sum_ms": summed,
                          "speedup": round(summed / wall, 2) if wall else None})
        print(f"  并行 2/2：墙钟 {wall} ms，串行应为 {summed} ms，加速 {summed/wall:.2f}x")
    else:
        if need_n1q:
            steps.append(run_step("N1Q 千问检索", [PY, str(PROJECT / "n1q" / "n1q_search.py")]))
        else:
            print("· N1Q 复用已有检索产物（--regen 可重跑）")
        if need_n3:
            steps.append(run_step("N3 Kimi 生图", [PY, str(PROJECT / "n3" / "n3_visuals.py")]))
        else:
            print("· N3 复用已有视觉产物（--regen 可重跑）")

    if not args.skip_hetero:
        steps.append(run_step("N5 异构复核", [PY, str(PROJECT / "n5" / "hetero_review.py")],
                              env_extra={"HETERO_PROVIDER": "qwen"}))
        steps.append(run_step("复核结论裁决", [PY, str(PROJECT / "n5" / "adjudicate.py")],
                              allow_fail=True))
    else:
        print("· 跳过异构复核（评测会因此判 FAIL）")

    if os.environ.get("ARK_API_KEY"):
        steps.append(run_step("N7 豆包三审", [PY, str(PROJECT / "n7" / "n7_review.py")]))
        steps.append(run_step("C-05 裁判打分", [PY, str(PROJECT / "eval" / "judge.py")],
                              allow_fail=True))
    else:
        print("· 跳过 N7（没有 ARK_API_KEY）")

    steps.append(run_step("P2 评测门禁", [PY, str(PROJECT / "eval" / "eval_gate.py")],
                          allow_fail=True))

    # 汇总
    eval_rep = json.loads((PROJECT / "cohort_l3" / "eval" / "eval_report.json").read_text(encoding="utf-8"))
    sd = json.loads((PROJECT / "real" / "out" / "structured_data.json").read_text(encoding="utf-8"))
    het_path = PROJECT / "n5" / "out" / "hetero_review.json"
    het = json.loads(het_path.read_text(encoding="utf-8")) if het_path.exists() else {}
    n1q = json.loads((PROJECT / "n1q" / "out" / "N1Q_sources.json").read_text(encoding="utf-8"))

    OUTBOX.mkdir(parents=True, exist_ok=True)
    # 硬垂询：消费过不可信内容 → 发布前必须人工确认（这不是弹窗，是流水线的闸）
    ws_pub = Workspace(PROJECT / "cohort_l3").ensure()
    untrusted = [r for r in ws_pub._read_registry() if r["trust_level"] == "untrusted"]
    ws_pub.ledger({"kind": "hard_inquiry", "required": bool(untrusted),
                   "approved": bool(args.approve_publish), "untrusted_artifacts": len(untrusted)})
    if untrusted and not args.approve_publish:
        print(f"⏸ 硬垂询：本链消费过 {len(untrusted)} 个不可信工件，发布需显式 --approve-publish")
        print("   （final.md 未生成，前面各步的工件与台账都已落盘）")
        return 3
    lines = [
        "# 交付汇总（真实链路跑出来的）", "",
        f"时间：{datetime.now().astimezone().isoformat(timespec='seconds')}", "",
        "## 数据（N2/P3）",
        f"- 明细 {sd['rows']:,} 行，对账差额 {sd['reconciliation']['diff']}",
        f"- 客单价 ¥{sd['totals']['aov_cny']}，整体退货率 {sd['totals']['return_rate']*100:.2f}%",
        f"- 空值 {sd['totals']['null_amount_rows']} 单，按 0 计入并标注", "",
        "## 检索（N1Q）",
        f"- 来源 {n1q['citation_contract']['total']} 条，契约通过 {n1q['citation_contract']['pass']} 条",
        f"- URL 可达 {n1q['reachability']['reachable']}/{n1q['reachability']['checked']}",
        f"- 注入命中 {len(n1q['injection_scan']['hits'])}，隔离 {n1q['injection_scan']['quarantined'] or '无'}", "",
        "## 视觉（N3）",
        "- 图表与信息图各 1 张，SVG 可编辑，PNG 已渲染，数值逐位对齐 structured_data", "",
        "## 复核（N5）",
        f"- 异构复核：{het.get('reviewer', 'N/A')} / verdict={het.get('verdict', 'N/A')} / "
        f"findings={len(het.get('findings', []))}",
    ]
    for f in het.get("findings", []):
        lines.append(f"  - [{f['severity']}] {f['item']}")
    lines += ["", "## 复核结论的复核（裁决）", ]
    adj_p = PROJECT / "n5" / "out" / "adjudication.json"
    if adj_p.exists():
        adj = json.loads(adj_p.read_text(encoding="utf-8"))
        lines.append(f"- reviewer 自报：{adj.get('reviewer_verdict')} → 裁决：**{adj.get('final_verdict')}** "
                     f"（确认 {adj['summary']['confirmed']} / 反证 "
                     f"{adj['summary']['refuted_self'] + adj['summary']['refuted_computed']} / "
                     f"无法判定 {adj['summary']['unverifiable']}）")
        if adj.get("reviewer_degenerate"):
            lines.append("- ⚠ 复核方输出被判定为退化（blocker 泛滥/自相矛盾），本轮结论不可用")
    reg = eval_rep.get("regression", {})
    reg_line = (f"- 回归基线：{reg.get('status')}"
                + (f"（{reg['eval_set_id']}：正确率 {reg['baseline']['correctness']:.0%} / "
                   f"延迟 p95 {reg['baseline']['latency_p95_ms']}ms / "
                   f"完整度 {reg['baseline']['context_completeness']:.0%} / "
                   f"一次过 {reg['baseline']['first_attempt_accuracy']:.0%}）"
                   if reg.get("status") == "compared" else f"（{reg.get('reason', '')}）"))
    lines += ["", "## 评测门禁（P2）",
              f"- 硬门禁 {eval_rep['gates_passed']}，用例 {eval_rep['cases_passed']}",
              reg_line,
              "", "## 三审与总结（N7）", ]
    n7_p = PROJECT / "n7" / "out" / "n7_report.json"
    if n7_p.exists():
        n7 = json.loads(n7_p.read_text(encoding="utf-8"))
        lines += [f"- 豆包 verdict：**{n7.get('verdict')}**，异议 {len(n7.get('objections', []))} 条",
                  "", n7.get("summary_md", "")]
    else:
        lines.append("- 未接入（缺 ARK_API_KEY）")
    lines += ["", "## 步骤耗时", ]
    for s in steps:
        lines.append(f"- {s['name']}: {s['ms']} ms {'OK' if s['ok'] else 'FAIL'}")
    (OUTBOX / "final.md").write_text("\n".join(lines), encoding="utf-8")
    (OUTBOX / "chain_report.json").write_text(json.dumps(
        {"steps": steps, "eval": eval_rep["verdict"], "hetero": het.get("verdict")},
        ensure_ascii=False, indent=2), encoding="utf-8")

    total = sum(s["ms"] for s in steps)
    adj_path = PROJECT / "n5" / "out" / "adjudication.json"
    adj = json.loads(adj_path.read_text(encoding="utf-8")) if adj_path.exists() else {}
    print(f"\n链路完成：{len(steps)} 步 / {total/1000:.1f}s / 评测 {eval_rep['verdict']} / "
          f"复核 {het.get('verdict', 'N/A')} → 裁决 {adj.get('final_verdict', 'N/A')}")
    print(f"交付汇总：{OUTBOX / 'final.md'}")
    return 0 if eval_rep["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
