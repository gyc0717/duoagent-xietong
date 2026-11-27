#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把公开真实数据集 UCI Online Retail II 映射成本项目的订单明细格式。

这是**真实交易数据**（英国在线零售商 2009–2011 的逐行交易，含退货/取消），
不是合成数据，可用来把「数据接入 → 指标 → 图表 → 报告」整条链跑通。
但它不是家电、不是双11、也不是本公司数据——交付时必须如实标注。

映射：
  Invoice          -> 订单号（C 开头 = 取消/退货）
  InvoiceDate      -> 下单时间
  Description      -> 品类（无描述时用 StockCode）
  Country          -> 省份（英国以外按国家名）
  Quantity*Price   -> 成交金额（退货行为负值取绝对值）
  Quantity<0 或 C  -> 是否退货 = 是
  原因             -> 公开数据没有，统一写「未标注」
"""
from __future__ import annotations

import csv
import io
import sys
import urllib.request
import zipfile
from pathlib import Path

OUT = Path(__file__).resolve().parent / "data" / "公开数据集_UCI_OnlineRetail.csv"
URL = "https://archive.ics.uci.edu/static/public/502/online+retail+ii.zip"
MAX_ROWS = 20000          # 控制体积，够跑通即可


def main() -> int:
    print("下载 UCI Online Retail II …")
    req = urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0"})
    blob = urllib.request.urlopen(req, timeout=180).read()
    print(f"  {len(blob)/1024/1024:.1f} MB")
    zf = zipfile.ZipFile(io.BytesIO(blob))
    name = next(n for n in zf.namelist() if n.lower().endswith(".xlsx"))
    xlsx = OUT.parent / "_uci_tmp.xlsx"
    OUT.parent.mkdir(parents=True, exist_ok=True)
    xlsx.write_bytes(zf.read(name))

    try:
        import openpyxl
    except ImportError:
        print("需要 openpyxl 读取 xlsx")
        return 2
    wb = openpyxl.load_workbook(xlsx, read_only=True, data_only=True)
    ws = wb[wb.sheetnames[0]]
    rows = ws.iter_rows(values_only=True)
    header = [str(c or "") for c in next(rows)]
    idx = {h: i for i, h in enumerate(header)}
    need = ["Invoice", "StockCode", "Description", "Quantity", "InvoiceDate", "Price", "Country"]
    missing = [n for n in need if n not in idx]
    if missing:
        print("表头缺列:", missing, header)
        return 3

    out = []
    for r in rows:
        if len(out) >= MAX_ROWS:
            break
        inv = str(r[idx["Invoice"]] or "").strip()
        if not inv:
            continue
        try:
            qty = float(r[idx["Quantity"]] or 0)
            price = float(r[idx["Price"]] or 0)
        except (TypeError, ValueError):
            continue
        if qty == 0:
            continue
        desc = str(r[idx["Description"]] or idx and r[idx["StockCode"]] or "").strip()[:40] or "未分类"
        when = r[idx["InvoiceDate"]]
        ts = when.strftime("%Y-%m-%d %H:%M:%S") if hasattr(when, "strftime") else str(when)
        returned = inv.upper().startswith("C") or qty < 0
        amount = abs(qty * price)
        out.append([inv, ts, desc, str(r[idx["Country"]] or "未知"),
                    f"{amount:.2f}", "是" if returned else "否",
                    "未标注（公开数据无退货原因）" if returned else "",
                    f"{amount:.2f}" if returned else "0"])

    with OUT.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["订单号", "下单时间", "品类", "省份", "成交金额", "是否退货", "退货原因", "退款金额"])
        w.writerows(out)

    try:
        wb.close()
        xlsx.unlink(missing_ok=True)
    except Exception:
        pass
    ret = sum(1 for r in out if r[5] == "是")
    print(f"写出 {OUT}  行数={len(out)}  退货行={ret}  退货率={ret/len(out)*100:.2f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
