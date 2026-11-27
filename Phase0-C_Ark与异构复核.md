# 豆包（Ark）接入结果 + N5 异构复核真跑

日期：2026-11-25

## 1. Ark key：有效，但模型一个都没开通

用 `/api/v3/models` 能列出 55 个模型，但逐个试 17 个文本模型，**全部返回**：

```json
{"error":{"code":"ModelNotOpen",
 "message":"Your account 2134919495 has not activated the model doubao-seed-2-1-pro-260915.
            Please activate the model service in the Ark Console."}}
```

也就是说：**key 是真的，账号没开通模型服务**。这一步只能你去点：

> 火山方舟控制台 → 开通管理（模型广场）→ 找到 `doubao-seed-2-1-pro-260915`（或 `doubao-seed-2-1-lite-260915`）→ 开通

开通后我这边的 `n7/doubao_client.py` 直接就能用，不用改代码（把 `ARK_MODEL` 换成开通的那个即可）。
客户端已经做了友好处理：遇到 `ModelNotOpen` 不会抛一堆堆栈，而是直接告诉你「去控制台开通哪个模型」。

顺带说明：这个 key 能看到的模型不少（`doubao-seed-2-1-pro/lite`、`glm-5-x`、`deepseek-v4-x`、`kimi-k3-1-pro`、`qwen3-*`），开通哪个都能用；`qwen3-32b` 之类还能当 N1Q 的备选。

## 2. 既然豆包没通，先用 Kimi 把「异构复核」这一环真跑了

方案里 N5 一审四轮：同源 → 沙箱实证 → **千问异构复核** → 联合复审。
千问没 key，但「异构」的本质要求是 **reviewer 的厂商 ≠ 被审方的厂商**，所以先用 Kimi 顶上，代码放在 `n5/hetero_review.py`。

真跑结果（`artifacts/N5_hetero_review.v1.json`）：

```json
{"verdict": "PASS",
 "findings": [
   {"severity": "minor",
    "item": "信息图比例条按组内最大值归一且无刻度说明，满轨条易被误读",
    "evidence": "¥200–399 订单条 width=300 填满轨道、¥400+ 退货率条 width=100 填满轨道，
                 实际仅为组内最大值（27,148 / 2.95%），无坐标轴或比例注记"},
   {"severity": "minor",
    "item": "柱状图数值标签色与柱体填充色不一致",
    "evidence": "第 2 柱填充 #10B981 但标签 #059669；第 3 柱填充 #F59E0B 但标签 #D97706"}
 ]}
```

7,863 tokens / 72.8 s / 约 ¥0.157。**没有 blocker**：所有数值与 `structured_data.json` 逐位一致、口径没写错。
两条 minor 是视觉可读性问题，不是数据问题——但确实是同源审不出来的那类东西。

### ⚠️ 一个方案没写清的细节：异构是有方向的

这次被复核的是**N3（Kimi 生成）的图**，而我用的 reviewer 也是 **Kimi** —— 对 N3 来说这是**同源**，不是异构。
正确的对应关系是：

| 被审方 | 谁来做异构复核 |
|---|---|
| N2/N5（DeepSeek 系写代码、写结论） | Kimi / 豆包 / 千问（任一家） |
| N3（Kimi 生图） | DeepSeek（我）或 豆包 / 千问 |

所以刚才那次复核，严格说是「同源复核 N3」，价值打折。真正补上异构的，是**我用 DeepSeek 去审 Kimi 的图**（数值逐位核对那一步），以及后续豆包/千问去审 DeepSeek 写的代码。
建议把这句写进方案 S1.5 的检查点：**`reviewer.vendor != producer.vendor`，按工件记录里的 producer 字段自动校验**，而不是写死 `reviewer=qwen`。

## 3. 当前节点真实度

| 节点 | 状态 |
|---|---|
| N1 / N6 / N8 WorkBuddy | mock（缺 MCP/API） |
| N1Q 千问检索 | mock（缺百炼 key） |
| N2 编程 | 数据层真实 |
| **N3 Kimi 生图** | **真实** |
| N4 Marvis 本地资料 | 真实（758.9 MB） |
| **N5 沙箱** | **真实**（8 类确定性检查） |
| **N5 异构复核** | **真实**（Kimi 顶千问，已有代码，换 key 即换厂商） |
| N7 豆包 | 代码就绪，**卡在控制台未开通** |
| L3 中转 | 真实（22 工件核验） |

## 4. 下一步

1. 你去开通 `doubao-seed-2-1-pro-260915`，N7 三审+总结立刻能跑（我这边 30 分钟内出结果）。
2. 有条件再给一个百炼（DashScope）key，N1Q 检索 + N5 异构就能换回原设计。
3. 在那之前，我可以把「按 producer 自动选异构 reviewer」的校验写进 L3，防止同源互审悄悄通过——这是刚暴露出来的真缺陷。
