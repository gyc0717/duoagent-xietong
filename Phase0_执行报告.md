# Phase 0 执行报告 · 多智能体协同 v1.6

执行方：DeepSeek Harness（首席开发工程师 / 一审质检员）
执行时间：2026-11-25
工作目录：`D:\数据\deepseek-harness\default-workspace\multi-agent`

## 1. 读到的材料

从 WorkBuddy 资料库「多agent协同，全自动工作流」直接取原文（链接需登录，已用你的登录态读取）：

| 文件 | 内容 | 用途 |
|---|---|---|
| 多智能体协同方案.md（v1.6，9,873 字） | 六方分工、9 节点 DAG、三级审核链、八条硬规则、P0–P3 四项能力 | 方案正文 |
| 落地步骤.md（5,077 字） | Phase 0/1/2 步骤、S0.1–S1.16、15 项验收清单 | 执行依据 |
| 会话产物总结.md（3,543 字） | 12 轮演进、定稿口径、包内清单 | 背景 |
| 多智能体协同方案_v1.6_交付包.html | 可视化方案页 | 交付物 |
| final.md / L3_doubao.md / 会话产物总结.md | N8 交付、豆包三审、归档总结 | 产物样例 |
| multi_agent_poc.py（1,074 行，68,957 字节） | 可运行原型 | Phase 0 主件 |

## 2. 方案一句话

WorkBuddy 派单 → （N1 ∥ N1Q）→ （N2 Harness 编程 ∥ N3 Kimi 生图 ∥ N4 Marvis 本地大文件）→ N5 Harness 深度一审（同源 → 沙箱实证 → 千问异构 → 联合复审）→ N6 WorkBuddy 二审 → N7 豆包三审+总结 → N8 WorkBuddy 收口。三级审核串行不可换序；一切经 L3 中转（`cohort/`）；质量不降级是硬约束，token 只记账。

## 3. 已执行（Phase 0）

### S0.1 环境确认 ✅
`multi_agent_poc.py` 在本机 Python 3.12 上零依赖运行。

### S0.2 跑原型 ✅
```
exit=0   最终状态 DELIVERED
完成节点 9/9        登记工件 11 个
三级审核 N5 → N6 → N7 串行    督办拦截 1 次 / 硬垂询 1 次
上下文完整度 100%（注入 91,600 tokens，截断 0）
并行度 执行 3/3 · 入口 2/2    深度校验 4 轮 / 异构检出 1 处 / 门禁打回 2 次
P0 隔离 1 处（quarantine/S-02.raw.json）P1 8 类 P2 5/5 · 7/7 P3 48,216 行 / 差额 0
成本 ¥2.12680（预算 ¥80，2.66%）   审计 52 条 append-only
```

### S0.3 目录核对 ✅
`cohort/` 8 个子目录齐全（inbox / claims / artifacts / reviews / eval / memory / quarantine / outbox），33 个文件，另有 `ledger.jsonl`、`run_log.jsonl`。

### S0.4 质量基线
PoC 内 `EVAL_SET.baseline`：正确率 0.96 / 延迟 p95 4,200ms / 上下文完整度 1.00 / 首次正确率 0.92 —— **这是 mock 写死的值，不是本机实测**。真实基线要接真实模型后按 S0.4 用真实任务测（见 §5）。

## 4. 增量：把 P1 / P3 从 mock 换成真实执行

原型里 `run_sandbox()` 的 8 类检查是**硬编码字典**（`{"compile": "PASS", "unit_test": "12/12", ...}`），P3 的 48,216 行/差额 0 也是写死的常量。落地文档自己点破了这个洞：「一审 3 轮全在文本层模型互证，谁都没真跑过」。

我补了 `real/` 目录，真跑了一遍：

| 检查 | 方式 | 结果 |
|---|---|---|
| 01 编译 | `py_compile` 全部源码 | PASS（5 文件，0 错误） |
| 02 单测 | 真跑 unittest 13 例 | 13/13 PASS |
| 03 SVG 渲染 | lxml 解析 5 个 SVG，校验 svg/viewBox/width | 5/5 |
| 04 图表数值 | 逐条比对每个 `<rect data-value>` 与 structured_data | 100% 一致 |
| 05 数据脚本复算 | 独立重算（不复用 data_exec）与工件比对 | PASS |
| 06 对账 | 分区订单合计 vs 明细行数 | 差额 0 |
| 07 空值边界 | 真运行朴素实现 | 抛 TypeError（缺陷复现）→ 修复实现 PASS |
| 08 mock 自洽性 | mock totals vs 分区合计 | 检出 80,184 行不自洽 |

产物：`real/out/execution_evidence.json`（真实耗时 387ms、真实计数）、`real/out/structured_data.json`、`real/out/charts/*.svg`（5 张）、`real/out/ledger.csv`（48,216 行）。

### 已接回主链（v1.6.1）
把 `run_sandbox()` 改成优先调用 `real/verify.py`，缺真实执行器时才退回常量并把 `evidence_source` 标成 `mock_constants`。重跑 PoC（原版备份为 `poc/multi_agent_poc.v16pri.py`）：

```
最终状态 DELIVERED   完成节点 9/9   登记工件 11 个
确定性检查 8 类（真编译 PASS / 单测 13/13 / SVG 渲染 5/5 / 数据脚本复算 PASS）
证据来源   real_execution（384.2 ms，真实执行不是常量）
```

`cohort/artifacts/execution_evidence.json` 现在带 `evidence_source: real_execution` —— 一审结论有了可复算的底。

**真实数据与 mock 的差异**（这正是一审该抓的东西）：

| 指标 | mock 写死 | 真实执行 |
|---|---|---|
| 订单总数 | 128,400 | 48,216 |
| 分区订单 | 18,940 / 21,104 / 8,172 | 15,340 / 27,148 / 5,728 |
| 客单价 | ¥286 | ¥256.46 |
| 整体退货率 | 2.10% | 2.14% |
| 空值单量 | 未标注 | 694（按 0 计入并标注） |

mock 的 `totals.orders=128,400` 与 `sum_group_orders=48,216` 差 80,184 —— 纯文本复核没发现，沙箱复算钉死了。这说明 P1 不是锦上添花：**没有确定性证据，一审只能靠模型互证，同源的错会一起错过去。**

## 5. 还差什么（Phase 1 的前置）

| 节点 | 现状 | 缺什么 |
|---|---|---|
| N1/N6/N8 WorkBuddy | 我读到了你的资料库，但没有 MCP/API | WorkBuddy MCP 配置，或 API 凭据 |
| N2/N5 Harness | ✅ 真实可跑 | 无 |
| N3 Kimi | 无 | Kimi API key |
| N7 豆包 | 本机有豆包桌面版，无 API | 豆包/火山 Ark key |
| N1Q 千问 | 无 | 百炼 DashScope key |
| N4 Marvis | 可做真实本地大文件索引 | 给我要索引的目录 |

机器上目前只有一个 `DEEPSEEK_BASE_URL`，没有 Kimi / 豆包 / 千问的 key。

## 6. 今天还能干的（按性价比排序）

1. **真实 L3 工作区**：把 `cohort/` 换成带文件锁 + 版本号 + sha256 登记的真实工作区，工件落盘可复算（已有 80%）。
2. **真实图表链**：5 张 SVG 已真出，接上渲染校验（PNG 落盘比对）即可作为 N3 的可验证替代，先不等 Kimi。
3. **真实一审回路**：把 `verify.py` 挂成 N5 的 executor 调用点，替换 mock 的 `run_sandbox()`，让每次跑 PoC 都产出真实证据而不是常量。
4. **WorkBuddy MCP**：如果你在 WorkBuddy 里能开 MCP/自定义插件，把「分发 / 二审 / 收口」三个动作接过来，N1/N6/N8 就真实了。

## 7. 一句话结论

Phase 0 的「本机跑通」已经复现，并且把 P1/P3 从写死的常量换成了真实执行（8/8，387ms）。现在卡在「另外四方没有 API」——不是架构问题，是接入问题。
