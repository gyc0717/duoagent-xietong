#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 L3 工作区 + N5 真实沙箱 + N4 本地索引跑成一次真实链路（非 mock）。

跑法：python run_l3.py [被索引的目录]
默认索引 multi-agent/real/out（小、快）；想验大文件就传 music-hub/dist/installer。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT / "l3"))
sys.path.insert(0, str(PROJECT / "n4"))

import n5_executor  # noqa: E402
from indexer import BIG_THRESHOLD, build_index, summary_card  # noqa: E402
from workspace import Workspace, sha256_file  # noqa: E402

TASK = {
    "task_id": "T-20261125-002",
    "goal": "产出新品 Q4 竞品与经营复盘（代码/数据结果 + 图表 + 一页总结）",
    "note": "L3 真实工作区落地验证：登记表 + 文件锁 + sha256 + 真沙箱 + 本地索引",
}


def main() -> int:
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else PROJECT / "real" / "out"
    ws = Workspace(PROJECT / (sys.argv[2] if len(sys.argv) > 2 else "cohort_l3")).init()
    print(f"L3 工作区：{ws.root}")

    # N1 派单（指令通道，可信）
    ws.register(node="N1", role="workbuddy_dispatch", name="dispatch", payload=TASK,
                content_mode="FULLTEXT", trust_level="trusted", channel="instruction",
                provenance="WorkBuddy/N1")

    # N1Q 外部资料（不可信，只进数据通道）+ P0 硬闸验证
    try:
        ws.register(node="N1Q", role="qwen_search", name="bad", payload={"x": 1},
                    trust_level="untrusted", channel="instruction")
        print("✗ P0 闸没拦住")
        return 1
    except ValueError as e:
        print(f"✓ P0 闸拦住：{e}")
    ws.register(node="N1Q", role="qwen_search", name="sources",
                payload={"trust_level": "untrusted", "channel": "data_only",
                         "sources": [{"id": "S-01", "url": "https://example.org/industry/q3-returns"},
                                     {"id": "S-02", "url": "https://example.org/news/competitor-a",
                                      "quarantined": True}]},
                trust_level="untrusted", channel="data_only", provenance="Qwen/N1Q")

    # N3 视觉层：真实 SVG 文件登记（按文件 sha256）
    charts = sorted((PROJECT / "real" / "out" / "charts").glob("*.svg"))
    for c in charts:
        ws.register(node="N3", role="kimi_image", name=c.stem,
                    payload={"file": c.name, "sha256": sha256_file(c), "bytes": c.stat().st_size},
                    trust_level="trusted", channel="both", provenance="N3/真实 SVG")
    print(f"✓ N3 登记 {len(charts)} 张 SVG")

    # N5 真沙箱（executor 内已做「不许 mock」校验）
    out = n5_executor.execute(ws)
    ev = out["evidence"]
    print(f"✓ N5 沙箱：{ev['evidence_source']} / {ev['elapsed_ms']}ms / 工件 {out['record']['uri']}")

    # N4 本地索引（真实目录；大文件只给摘要卡，全文按需）
    idx = build_index(target, PROJECT / "n4" / f"index_{target.name}.json")
    cards = [summary_card(e) for e in idx["entries"][:5]]
    ws.register(node="N4", role="marvis_device", name="local_index",
                payload={"root": idx["root"], "files": idx["files"],
                         "total_bytes": idx["total_bytes"], "big_files": idx["big_files"],
                         "chunk_bytes": idx["policy"]["chunk_bytes"], "top": cards},
                trust_level="trusted", channel="both", provenance="Marvis/N4 本地索引")
    print(f"✓ N4 索引：{idx['files']} 文件 / {idx['total_bytes']/1048576:.1f} MB / "
          f"大文件 {idx['big_files']} 个（阈值 {BIG_THRESHOLD>>20} MB）")

    # 完整性核验
    v = ws.verify()
    print(f"{'✓' if v['pass'] else '✗'} 完整性核验：{v['ok']}/{v['total']} 通过"
          f"（缺失 {len(v['missing'])} / 被改 {len(v['tampered'])}）")

    s = ws.summary()
    print(json.dumps(s, ensure_ascii=False, indent=2))
    (PROJECT / "cohort_l3" / "outbox" / "l3_run_report.json").write_text(
        json.dumps({"summary": s, "verify": v, "task": TASK}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    return 0 if v["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
