#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""N4 本地文件索引（Marvis 职责的本地实现）。

扫描指定目录（默认 real/data），输出每个文件的大小、sha256、CSV 行数，
供后续步骤按哈希引用——不把大文件内容读进上下文。

目录被限制在 multi-agent/ 之下，拒绝任意路径。
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent          # multi-agent/
OUT = Path(__file__).resolve().parent / "out" / "file_index.json"
DEFAULT_DIR = PROJECT / "real" / "data"
ALLOWED_ROOT = PROJECT.resolve()


def rows_of(p: Path) -> int | None:
    if p.suffix.lower() != ".csv":
        return None
    for enc in ("utf-8-sig", "gbk"):
        try:
            text = p.read_text(encoding=enc)
            return max(0, len(list(csv.reader(io.StringIO(text)))) - 1)
        except UnicodeDecodeError:
            continue
        except Exception:  # noqa: BLE001
            return None
    return None


def main(target: str | None = None) -> int:
    d = Path(target).resolve() if target else DEFAULT_DIR.resolve()
    if ALLOWED_ROOT not in d.parents and d != ALLOWED_ROOT:
        raise SystemExit(f"拒绝索引 multi-agent 之外的目录：{d}")
    if not d.exists():
        print(json.dumps({"ok": False, "error": f"目录不存在：{d}"}, ensure_ascii=False))
        return 2

    SKIP_MARKS = ("模板", "示例", "sample", "demo", "test")
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
        files.append({"name": p.name, "rel": str(p.relative_to(d)).replace("\\", "/"),
                      "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()[:16],
                      "csv_rows": rows})

    payload = {"ok": True, "dir": str(d), "count": len(files),
               "skipped": skipped, "files": files}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"ok": True, "dir": str(d), "count": len(files),
                      "skipped": [x["name"] for x in skipped]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    import sys
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else None))
