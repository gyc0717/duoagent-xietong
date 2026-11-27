#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""file_index：空 CSV 与非真实数据（模板/示例）不进索引。

理由：N4 索引会被 N8 报告当附件列出来。模板和合成样本一旦混进去，
报告里就会出现「看起来像数据、其实没有数据」的条目。
"""
from pathlib import Path

P = Path(__file__).resolve().parent / "file_index.py"
s = P.read_text(encoding="utf-8")

OLD = '''    files = []
    for p in sorted(d.rglob("*")):
        if not p.is_file():
            continue
        data = p.read_bytes()
        files.append({"name": p.name, "rel": str(p.relative_to(d)).replace("\\\\", "/"),
                      "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()[:16],
                      "csv_rows": rows_of(p)})'''
NEW = '''    SKIP_MARKS = ("模板", "示例", "sample", "demo", "test")
    files = []
    skipped = []
    for p in sorted(d.rglob("*")):
        if not p.is_file():
            continue
        if any(m in p.name.lower() or m in p.name for m in SKIP_MARKS):
            skipped.append({"name": p.name, "reason": "文件名含模板/示例标记"})
            continue
        rows = rows_of(p)
        if p.suffix.lower() == ".csv" and not rows:
            skipped.append({"name": p.name, "reason": "空 CSV（0 数据行）"})
            continue
        data = p.read_bytes()
        files.append({"name": p.name, "rel": str(p.relative_to(d)).replace("\\\\", "/"),
                      "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()[:16],
                      "csv_rows": rows})'''
assert OLD in s, "找不到索引循环"
s = s.replace(OLD, NEW, 1)

s = s.replace(
    '    payload = {"ok": True, "dir": str(d), "count": len(files), "files": files}',
    '    payload = {"ok": True, "dir": str(d), "count": len(files),\n'
    '               "skipped": skipped, "files": files}',
    1,
)
s = s.replace(
    '    print(json.dumps({"ok": True, "dir": str(d), "count": len(files)}, ensure_ascii=False))',
    '    print(json.dumps({"ok": True, "dir": str(d), "count": len(files),\n'
    '                      "skipped": [x["name"] for x in skipped]}, ensure_ascii=False))',
    1,
)

P.write_text(s, encoding="utf-8")
print("file_index 已跳过模板/示例/空 CSV")
