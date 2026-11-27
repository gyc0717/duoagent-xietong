#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""导出 Harness 会话为可读 Markdown + 原始解压 JSONL（只读源数据）。

用法：
  python export_harness_sessions.py
输出目录：
  D:\\数据\\deepseek-harness\\default-workspace\\multi-agent\\session_exports\\
"""
import json
import pathlib
import datetime
import zstandard as zstd

BASE = pathlib.Path(r"C:\Users\gyc20\.dsh\sessions\--D-~6570~636E-deepseek-harness-default-workspace--")
OUT = pathlib.Path(r"D:\数据\deepseek-harness\default-workspace\multi-agent\session_exports")
SESSIONS = [
    ("fedad433-c2fe-486d-9725-72b6e2efc28b", "父会话"),
    ("fefaa54f-0d79-4803-9232-6b648e7d48fe", "分叉会话"),
]


def ts(ms):
    if not ms:
        return ""
    try:
        return datetime.datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(ms)


def text_of(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        out = []
        for part in content:
            if isinstance(part, dict):
                t = part.get("text") or part.get("content") or ""
                if t:
                    out.append(str(t))
            elif part:
                out.append(str(part))
        return "\n".join(out)
    return str(content or "")


def message_parts(d):
    """把消息拆成 (正文, 思考, 其他) 三段，避免导成原始 dict 字符串。"""
    if not isinstance(d, dict):
        return text_of(d), "", ""
    msg = d.get("message")
    content = msg.get("content") if isinstance(msg, dict) else d.get("content")
    body, think, other = [], [], []
    if isinstance(content, str):
        body.append(content)
    elif isinstance(content, list):
        for part in content:
            if isinstance(part, dict):
                ptype = part.get("type", "")
                txt = part.get("text") or part.get("content") or ""
                if ptype == "reasoning" or ptype == "thinking":
                    if txt:
                        think.append(str(txt))
                elif ptype in ("tool-call", "tool_use", "text"):
                    if txt and ptype == "text":
                        body.append(str(txt))
                    elif txt:
                        other.append(str(txt))
                elif txt:
                    body.append(str(txt))
            elif part:
                body.append(str(part))
    elif content:
        body.append(text_of(content))
    return "\n".join(body).strip(), "\n".join(think).strip(), "\n".join(other).strip()


def data_text(d):
    body, think, other = message_parts(d)
    parts = []
    if think:
        parts.append("[思考] " + think)
    if body:
        parts.append(body)
    if other:
        parts.append(other)
    return "\n\n".join(parts)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    index = []
    for sid, label in SESSIONS:
        src = BASE / ("session-" + sid) / "session.v4.jsonl.zstd"
        raw = zstd.ZstdDecompressor().stream_reader(open(src, "rb")).read()
        lines = [l for l in raw.decode("utf-8", "replace").splitlines() if l.strip()]
        head = json.loads(lines[0])
        (OUT / ("session-" + sid + ".jsonl")).write_bytes(raw)

        md = []
        md.append("# Harness 会话导出 · " + label)
        md.append("")
        md.append("- 会话 ID：`" + sid + "`")
        md.append("- 创建时间：" + ts(head.get("createdAt")))
        md.append("- 父会话：" + str(head.get("parentSession") or "无（根会话）"))
        md.append("- 工作目录：" + str(head.get("cwd") or ""))
        md.append("- 事件数：" + str(len(lines) - 1))
        md.append("- 源文件：`" + str(src) + "`")
        md.append("")
        md.append("---")
        md.append("")

        n_user = n_asst = n_tool = 0
        for line in lines[1:]:
            try:
                ev = json.loads(line)
            except Exception:
                continue
            typ = ev.get("type", "")
            t = ts(ev.get("time") or ev.get("createdAt"))
            d = ev.get("data") or {}
            body = data_text(d).strip()

            if typ == "user/message":
                n_user += 1
                md.append("## [" + t + "] 用户")
                md.append("")
                md.append(body)
                md.append("")
            elif typ == "assistant/message":
                n_asst += 1
                md.append("## [" + t + "] 助手")
                md.append("")
                md.append(body)
                md.append("")
            elif typ == "tool/call":
                n_tool += 1
                name = d.get("name") or d.get("tool") or d.get("toolName") or "tool"
                args = d.get("arguments") or d.get("args") or ""
                argtxt = json.dumps(args, ensure_ascii=False) if not isinstance(args, str) else args
                md.append("<details><summary>[" + t + "] 工具调用 · " + str(name) + "</summary>")
                md.append("")
                md.append("```")
                md.append(argtxt[:4000])
                md.append("```")
                md.append("</details>")
                md.append("")
            elif typ == "tool/result":
                call_id = (d.get("message") or {}).get("toolCallId") or d.get("toolCallId") or ""
                rbody, _, _ = message_parts(d)
                if not rbody:
                    rbody = json.dumps(d.get("result") or d.get("content") or "", ensure_ascii=False)
                call_label = " · " + str(call_id)[:20] if call_id else ""
                md.append("<details><summary>[" + t + "] 工具结果" + call_label + "</summary>")
                md.append("")
                md.append("```")
                md.append(rbody[:4000])
                md.append("```")
                md.append("</details>")
                md.append("")

        md.append("---")
        md.append("")
        md.append("统计：用户消息 " + str(n_user) + " 条，助手消息 " + str(n_asst) +
                  " 条，工具调用 " + str(n_tool) + " 次。")
        out_md = OUT / ("session-" + sid + ".md")
        out_md.write_text("\n".join(md), encoding="utf-8")
        index.append((label, sid, out_md.name, "session-" + sid + ".jsonl",
                      n_user, n_asst, n_tool, out_md.stat().st_size))
        print("exported", label, sid, "user", n_user, "asst", n_asst, "tools", n_tool)

    lines = ["# Harness 会话导出索引", "",
             "源目录：`" + str(BASE) + "`", "",
             "| 会话 | ID | 可读文件 | 原始文件 | 用户 | 助手 | 工具 | MD 大小 |",
             "|---|---|---|---|---:|---:|---:|---:|"]
    for row in index:
        lines.append("| " + " | ".join(str(x) for x in row) + " |")
    (OUT / "INDEX.md").write_text("\n".join(lines), encoding="utf-8")
    print("index", OUT / "INDEX.md")


if __name__ == "__main__":
    main()
