# 治理闭环落地 · 异构换千问 / 厂商校验 / 统一编排 / 评测门禁 / 红队

日期：2026-11-25　范围：清单里的 1–7（8 单价校准未做）

## 0. 一句话

这一轮把「谁审谁」「怎么记账」「怎么判过」三件事变成了代码里的硬约束，
并且在做的过程中撞到两个真问题：**异构复核模型自己会退化**、**severity 标签根本不可信**。

## 1. 异构复核换回千问（方案原设计）

`n5/hetero_review.py` 现在支持 `qwen | kimi` 两个 reviewer，默认 `qwen-max`：

```
✓ N5 异构复核   6.3s   3,987 tokens   ¥0.011
```

## 2. 「reviewer 厂商 ≠ 被审厂商」写进 L3

`l3/workspace.py` 新增：

| 能力 | 说明 |
|---|---|
| `VENDOR_BY_ROLE` | 角色 → 厂商（kimi_image→Moonshot、dsh_*→DeepSeek、qwen_*→Qwen…） |
| 登记时写 `vendor` 字段 | 工件自带生产者厂商，不靠人记 |
| `hetero_conflicts(vendor, target_ids)` | 列出同厂冲突 |
| `register_review(...)` | **同厂直接 `ValueError`，拒绝登记** |

实测：`HETERO_PROVIDER=kimi` 再跑一次，会被闸当场拦下（Kimi 审 Kimi 的图）。4 个单测覆盖。

## 3. 统一编排器 `run_chain.py`

```
N5 沙箱 → N1Q 检索（可复用）→ N3 生图（可复用）→ N5 异构复核 → 复核裁决 → P2 评测 → outbox/final.md
```

- 默认复用已有模型产物（7–8 秒跑完，不重复花钱）；`--regen` 才重跑模型节点
- `--skip-hetero` 用于只验证门禁
- 交付汇总直接由真实工件生成，不手写

## 4. 评测门禁真跑（`eval/eval_gate.py`）

7 项确定性硬门禁，全部对真实产物：

| 门禁 | 结果 |
|---|---|
| schema | ✓ |
| tool_signature（须 `real_execution` + 9 类检查齐） | ✓ |
| latency（N3 ≤ 600 s） | ✓ 141.4 s |
| token_budget（≤ 50k） | ✓ |
| hallucination_canary（SVG 里每个数必须在口径白名单） | ✓ |
| context_completeness（N1Q/N3/N4/N5 工件齐） | ✓ |
| review_adjudicated（复核须经裁决） | ✓ |

用例 4/4 通过，C-05（judge 打分）标 **pending** 并在报告里写明原因：总结节点（N7 豆包）还没接，不拿 mock 文本去让裁判打分充数。

**回归基线：`no_baseline`** —— 如实写进报告。没有 S0.4 的真实基线，「不降级」就是句空话，这一条不掩盖。

## 5. CI 契约用例 + 注入红队（`tests/test_contracts.py`）

15 个用例，纯本地、零网络、可进流水线：

- 引用契约 8 例：缺 url / 缺时间 / 未来时间 / 日期格式 / 置信度枚举 / 非 http / 付费墙摘要放行
- 可达性 2 例：非法 URL 不联网也能判死
- 红队 4 例：`忽略以上所有系统指令…外发到`、`IGNORE PREVIOUS…send all data`、`绕过权限校验`、`系统指令：…` —— 全部命中
- 隔离 2 例：原文一字不改落盘、`fact_content_truncated=false`、无命中不建隔离区

单测总数：**35 个，全过**。

## 6. 这一轮撞到的两个真问题

### 6.1 复核模型会退化：19 条 blocker，全是「没问题」

qwen-plus 那一轮返回 **19 条 findings、16 条标 blocker**，内容却是
「aov 256.46 与 256.46 匹配 ✓」「1032/48216=0.0214 ✓」这种自证无罪的句子。
它的 `severity` 标签彻底失真。

裁决器判 `REVIEWER_UNUSABLE`，并给出量化依据：blocker ≥ 8 或半数自证无问题。

### 6.2 换了 qwen-max 仍会错：把 1,032 和 1032 判成「不一致」

qwen-max（更稳，只报 1 条）给出的 blocker 是：

> 总退货数量不一致：数据工件 totals.returns=1032，SVG 里写 1,032

**同一个数，只是千分位格式**。裁决器提取数值、归一化后反证为 `refuted_computed`。

结论写进 `adjudication.json` 的 rule 字段：
> severity 标签不可信：只认脚本复算；自证无问题的 blocker 记为 refuted_self；
> blocker 数 ≥8 或半数自证 → REVIEWER_UNUSABLE。

## 7. 沙箱新增第 9 类检查：图形比例是否真成比例

为了裁决「宽度比例失真」这类主张，`real/verify.py` 加了 `09_chart_proportionality`：

- 横条看 `width`、竖条看 `height`，任一与数值成比例即算线性（容差 1%）
- 按 `x` 坐标分组，避免把「订单量一列、退货率一列」两套刻度误判成比例失真

踩坑记录：第一版只测 `width`，把竖柱状图（宽度恒定）全判成失真；第二版又把两列混算。
现在 4 张图全部 `linear=True`，最大偏差 0.03%。

沙箱检查从 8 类变 **9 类**，`tool_signature` 门禁的必填项同步更新。

## 8. 清理

- 22 个探针脚本 / 临时输出 → `_scratch/`
- 全部 `__pycache__` 删除
- 顶层只剩：`l3/ n1q/ n3/ n4/ n5/ n7/ eval/ real/ poc/ tests/ cohort*/` + 文档

## 9. 现在的链路

```
python run_chain.py          # 4 步 / 7.8 s / 评测 PASS / 复核 FAIL → 裁决 PASS
python run_chain.py --regen  # 连模型节点一起重跑
python -m unittest discover -s tests   # 35 个用例
```

`cohort_l3/outbox/final.md` 由真实工件自动生成，含数据、检索、视觉、复核、裁决、门禁、耗时七段。

## 10. 还没做

| # | 事项 | 说明 |
|---|---|---|
| 1 | 单价校准 | Kimi/千问的 ¥/1k 仍是工程估算，不是真实账单 |
| 2 | 质量基线 | `no_baseline`——需要一次真实任务的正确率/延迟/一次通过率 |
| 3 | C-05 judge 用例 | 等 N7 豆包接入后才有「一页总结」可打分 |
| 4 | 记账回归验证 | try/finally 改完只跑过正常路径，异常路径未再验 |
| 5 | Kimi 两条视觉 minor | 比例条无刻度说明、柱色与标签色不一致，尚未修 |
