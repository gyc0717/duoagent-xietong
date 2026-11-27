#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把课程电商数据集（U 盘只读）转换成管线接入模板 CSV。

源：F:\\大二\\GYC\\项目6-3 pandas数据预处理—数据标准化\\data\\电商产品销售数据.csv
目标：real/data/课程电商数据集_退款.csv（UTF-8-SIG，8 列模板）

硬规矩：
  1. 只读源盘，绝不写回 U 盘；
  2. 缺失字段（退货原因 / 退款金额）留空，不编造；
  3. 1970 年占位日期、非法金额、无法识别的退款标志一律丢弃并记原因；
  4. 源文件 sha256、映射表、丢弃统计写进 real/out/convert_course_report.json。

用法：python real/convert_course_data.py [--src <csv>] [--out <csv>]
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_SRC = Path(r"F:\大二\GYC\项目6-3 pandas数据预处理—数据标准化\data\电商产品销售数据.csv")
DEFAULT_OUT = HERE / "data" / "课程电商数据集_退款.csv"
REPORT = HERE / "out" / "convert_course_report.json"

# 模板列 -> 源列；None 表示源数据无此列，留空（不编造）
MAP = {
    "订单号": "订单编号",
    "下单时间": "订单发生时间",
    "品类": "商品类别代码",
    "省份": "用户地区",
    "成交金额": "商品售出价格/美元",
    "是否退货": "订单是否退款",
    "退货原因": None,
    "退款金额": None,
}
TEMPLATE = list(MAP.keys())
CALIBER = "refunded"          # 源只有 是/否，无发起/完成阶段，不硬套
CURRENCY = "USD"


def parse_time(v: str) -> datetime | None:
    v = (v or "").strip()
    for fmt in ("%Y/%m/%d %H:%M", "%Y/%m/%d %H:%M:%S",
                "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(v, fmt)
        except ValueError:
            continue
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=str(DEFAULT_SRC))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    args = ap.parse_args()
    src, out = Path(args.src), Path(args.out)
    if not src.exists():
        raise SystemExit(f"找不到源文件：{src}")

    sha = hashlib.sha256(src.read_bytes()).hexdigest()
    raw = src.read_bytes()
    text = None
    for enc in ("utf-8-sig", "utf-8", "gbk", "gb18030"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise SystemExit("源文件解码失败")

    reader = csv.DictReader(text.splitlines())
    header = reader.fieldnames or []
    need = [v for v in MAP.values() if v]
    missing = [c for c in need if c not in header]
    if missing:
        raise SystemExit(f"源缺列：{missing}\n实际表头：{header}")

    kept = 0
    dropped = Counter()
    reasons: list[str] = []
    with out.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(TEMPLATE)
        for i, row in enumerate(reader, start=2):
            ret = (row.get("订单是否退款") or "").strip()
            if ret not in ("是", "否"):
                dropped["退款标志非法"] += 1
                if len(reasons) < 10:
                    reasons.append(f"第{i}行 订单是否退款={ret!r} 无法识别")
                continue
            t = parse_time(row.get("订单发生时间", ""))
            if t is None or t.year == 1970:
                dropped["日期占位或非法"] += 1
                if len(reasons) < 10:
                    reasons.append(f"第{i}行 订单发生时间={row.get('订单发生时间')!r} 为占位/非法")
                continue
            try:
                amt = float((row.get("商品售出价格/美元") or "").strip())
            except ValueError:
                dropped["金额非法"] += 1
                if len(reasons) < 10:
                    reasons.append(f"第{i}行 商品售出价格/美元={row.get('商品售出价格/美元')!r} 非法")
                continue
            if amt < 0:
                dropped["金额为负"] += 1
                continue
            w.writerow([
                (row.get("订单编号") or "").strip(),
                t.strftime("%Y/%m/%d %H:%M"),
                (row.get("商品类别代码") or "未分类").strip(),
                (row.get("用户地区") or "未知").strip(),
                f"{amt:.2f}",
                ret,
                "",   # 源无退货原因
                "",   # 源无退款金额
            ])
            kept += 1

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "source_path": str(src),
        "source_sha256": sha,
        "source_bytes": len(raw),
        "source_rows": sum(1 for _ in text.splitlines()) - 1,
        "output": str(out),
        "kept_rows": kept,
        "dropped": dict(dropped),
        "drop_examples": reasons,
        "mapping": MAP,
        "caliber": CALIBER,
        "caliber_note": "源字段 订单是否退款=是；无发起/完成阶段信息，声明为 refunded（已退款），不硬套 started/completed",
        "currency": CURRENCY,
        "missing_source_fields": [k for k, v in MAP.items() if v is None],
        "limits": ["地区为匿名 地区A/B…，非真实省份", "无退货原因与退款金额列，留空不编造",
                   "课程电商数据集，非本公司、非双11"],
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: report[k] for k in
                      ("source_sha256", "source_rows", "kept_rows", "dropped",
                       "caliber", "currency", "missing_source_fields")},
                     ensure_ascii=False, indent=2))
    print(f"输出：{out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
