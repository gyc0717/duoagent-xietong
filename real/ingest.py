#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""订单数据接入管线（B 阶段的核心件）

输入：`订单号,下单时间,品类,省份,成交金额,是否退货,退货原因,退款金额`
输出：清洗后的明细 + 指标汇总 + 口径记录 + 源文件哈希

三条硬规矩（沿用 N1Q 的教训）：
  1. 退货口径必须显式声明（started=发起退货 / completed=退货完成 / refunded=已退款），不声明就拒绝运行；
  2. 缺列、类型不符、金额为负 → 报错并列出前 10 行问题，不静默丢数据；
  3. 输出里记录源文件 sha256 与口径，任何数字都能回溯到「哪份文件、什么口径」。

用法：
    python real/ingest.py <csv> --caliber started [--encoding auto]
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

OUT = Path(__file__).resolve().parent / "out"
REQUIRED = ["订单号", "下单时间", "品类", "省份", "成交金额", "是否退货", "退货原因", "退款金额"]
CALIBERS = {"started": "发起退货", "completed": "退货完成", "refunded": "已退款"}
TRUE_SET = {"是", "1", "true", "TRUE", "y", "Y", "已退", "退货"}
FALSE_SET = {"否", "0", "false", "FALSE", "n", "N", "未退", "空"}


def read_text(path: Path, encoding: str = "auto") -> tuple[str, str]:
    raw = path.read_bytes()
    encs = [encoding] if encoding != "auto" else ["utf-8-sig", "utf-8", "gbk", "gb18030"]
    for enc in encs:
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            continue
    raise SystemExit(f"无法解码 {path}（试过 {encs}），请另存为 CSV UTF-8")


def to_bool(v: str) -> bool | None:
    v = (v or "").strip()
    if v in TRUE_SET:
        return True
    if v in FALSE_SET:
        return False
    return None


def to_money(v: str) -> float | None:
    v = (v or "").strip().replace("¥", "").replace(",", "")
    if not v:
        return None
    try:
        return float(v)
    except ValueError:
        return None


def parse_time(v: str) -> datetime | None:
    v = (v or "").strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M:%S",
                "%Y/%m/%d %H:%M", "%Y/%m/%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(v, fmt)
        except ValueError:
            continue
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("csv_path")
    ap.add_argument("--caliber", required=True, choices=sorted(CALIBERS),
                    help="started=发起退货 / completed=退货完成 / refunded=已退款")
    ap.add_argument("--encoding", default="auto")
    ap.add_argument("--currency", default="CNY", choices=["CNY", "GBP", "USD"])
    ap.add_argument("--dataset-label", default="", help="数据集名称，写进 provenance")
    ap.add_argument("--category-label", default="未标注", help="行业/品类，写进 provenance")
    ap.add_argument("--is-company-data", action="store_true",
                    help="是否本公司业务数据（默认 false）")
    ap.add_argument("--out-dir", default=str(OUT),
                    help="输出目录（默认 real/out；测试请指向 _scratch/test_out，勿覆盖交付产物）")
    args = ap.parse_args()
    out_dir = Path(args.out_dir)

    src = Path(args.csv_path)
    if not src.exists():
        raise SystemExit(f"找不到文件：{src}")
    sha = hashlib.sha256(src.read_bytes()).hexdigest()
    text, enc = read_text(src, args.encoding)

    rows = list(csv.DictReader(io.StringIO(text)))
    if not rows:
        raise SystemExit("CSV 没有数据行")
    header = list(rows[0].keys())
    missing = [c for c in REQUIRED if c not in header]
    if missing:
        raise SystemExit(f"缺列：{missing}\n实际表头：{header}")

    problems: list[str] = []
    clean = []
    for i, r in enumerate(rows, start=2):
        ret = to_bool(r["是否退货"])
        amt = to_money(r["成交金额"])
        refund = to_money(r["退款金额"]) or 0.0
        t = parse_time(r["下单时间"])
        if ret is None:
            problems.append(f"第{i}行 是否退货={r['是否退货']!r} 无法识别")
            continue
        if amt is None or amt < 0:
            problems.append(f"第{i}行 成交金额={r['成交金额']!r} 非法")
            continue
        if t is None:
            problems.append(f"第{i}行 下单时间={r['下单时间']!r} 无法解析")
            continue
        clean.append({"订单号": (r["订单号"] or "").strip(), "下单时间": t,
                      "品类": (r["品类"] or "未分类").strip(),
                      "省份": (r["省份"] or "未知").strip(),
                      "成交金额": amt, "是否退货": ret,
                      "退货原因": (r["退货原因"] or "").strip(), "退款金额": refund})

    if not clean:
        raise SystemExit("清洗后没有可用行：" + "; ".join(problems[:10]))

    orders = len(clean)
    gmv = sum(r["成交金额"] for r in clean)
    returned = [r for r in clean if r["是否退货"]]
    refund_amt = sum(r["退款金额"] for r in returned)
    by_cat = defaultdict(lambda: {"orders": 0, "gmv": 0.0, "ret": 0, "refund": 0.0})
    by_prov = defaultdict(lambda: {"orders": 0, "gmv": 0.0, "ret": 0, "refund": 0.0})
    for r in clean:
        for bucket in (by_cat[r["品类"]], by_prov[r["省份"]]):
            bucket["orders"] += 1
            bucket["gmv"] += r["成交金额"]
            if r["是否退货"]:
                bucket["ret"] += 1
                bucket["refund"] += r["退款金额"]

    def rate(d):
        return round(d["ret"] / d["orders"] * 100, 4) if d["orders"] else 0.0

    from_time = min(r["下单时间"] for r in clean)
    to_time = max(r["下单时间"] for r in clean)
    ret_def = {
        "started": "发起退货（以退货单/取消发票行计）",
        "completed": "退货完成（以退款完成为准）",
        "refunded": "已退款（源字段 订单是否退款=是，无发起/完成阶段信息）",
    }[args.caliber]
    denom = ("；分母为订单行，指标为已退款订单行占比（非严格订单退货率）"
             if args.caliber == "refunded" else "；分母为订单行，非订单数")
    report = {
        "source": {"file": src.name, "sha256": sha, "encoding": enc, "rows": len(rows),
                   "currency": args.currency,
                   "provenance": {
                       "dataset": args.dataset_label or src.stem,
                       "is_company_data": bool(args.is_company_data),
                       "category": args.category_label,
                       "period": f"{from_time:%Y-%m} ~ {to_time:%Y-%m}",
                       "return_definition": ret_def + denom,
                       "caliber_code": args.caliber,
                   }},
        "caliber": {"code": args.caliber, "label": CALIBERS[args.caliber],
                    "note": ("退款行占比 = 已退款订单行 / 订单行（非订单退货率）"
                             if args.caliber == "refunded"
                             else "退货率 = 该口径下退货单数 / 订单数")},
        "clean": {"rows": orders, "dropped": len(problems), "problems": problems[:10]},
        "time_range": {"from": min(r["下单时间"] for r in clean).isoformat(sep=" "),
                       "to": max(r["下单时间"] for r in clean).isoformat(sep=" ")},
        "totals": {"orders": orders, "gmv": round(gmv, 2),
                   "return_orders": len(returned),
                   "return_line_share_pct": round(len(returned) / orders * 100, 4),
                   "refund_amount": round(refund_amt, 2),
                   "aov": round(gmv / orders, 2)},
        "by_category": {k: {**v, "gmv": round(v["gmv"], 2), "refund": round(v["refund"], 2),
                            "return_line_share_pct": rate(v)} for k, v in sorted(by_cat.items())},
        "by_province": {k: {**v, "gmv": round(v["gmv"], 2), "refund": round(v["refund"], 2),
                            "return_line_share_pct": rate(v)} for k, v in sorted(by_prov.items())},
        "reasons": dict(Counter(r["退货原因"] for r in returned).most_common(10)),
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "ingest_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    with (out_dir / "clean_orders.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["订单号", "下单时间", "品类", "省份", "成交金额", "是否退货", "退货原因", "退款金额"])
        for r in clean:
            w.writerow([r["订单号"], r["下单时间"].isoformat(sep=" "), r["品类"], r["省份"],
                        r["成交金额"], "是" if r["是否退货"] else "否", r["退货原因"], r["退款金额"]])

    print(json.dumps({k: report[k] for k in ("source", "caliber", "clean", "time_range", "totals")},
                     ensure_ascii=False, indent=2))
    print(f"\n口径={CALIBERS[args.caliber]}  源文件 sha256={sha[:16]}…")
    print(f"输出：{out_dir / 'ingest_report.json'}")
    if problems:
        print(f"⚠ 丢弃 {len(problems)} 行，示例：{problems[:3]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
