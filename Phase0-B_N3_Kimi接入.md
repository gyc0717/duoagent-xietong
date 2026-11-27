# N3 接入记录 · Kimi 真调生图（v1.6 第一个真模型节点）

日期：2026-11-25　模型：`kimi-k3`（Moonshot）　接口：`https://api.moonshot.cn/v1`
代码：`n3/kimi_client.py`（客户端）/ `n3/n3_visuals.py`（N3 节点）

## 1. 结论先说

N3 不再是一句 mock 文案：**Kimi 真的按 structured_data 画出了两张可编辑 SVG，我只做质检和渲染。**

| 产出 | 内容 | 文件 | 登记 |
|---|---|---|---|
| 图表 | 三区间订单量柱状图 | `n3/out/n3_chart.svg` / `.png`（19 KB） | `N3_kimi_chart.v2` |
| 信息图 | 总览卡片（3 大数 + 3 行分区） | `n3/out/n3_infographic.svg` / `.png`（36 KB） | `N3_kimi_infographic.v2` |

数值一致性：图里的 15,340 / 27,148 / 5,728 / 48,216 / ¥256.46 / 2.14% / 1.54% / 2.31% / 2.95% / 694 / 1,032 全部与 `real/out/structured_data.json` **逐位相同**，不是「看起来差不多」。

## 2. 节点契约（真跑出来的，不是设计稿）

```
structured_data.json  →  prompt（数值锁死 + 输出格式硬规则）  →  Kimi(kimi-k3)
                      →  本地质检（XML / viewBox / 标签 / data-value 白名单）
                      →  不合格就带着错误打回重生成（最多 3 次）
                      →  Edge 无头渲染 PNG（证明「真能渲染」）
                      →  登记进 L3（sha256 / version / trust_level / channel）
```

质检四关：
1. `lxml` 解析必须是合法 XML；
2. 根元素 `svg` 必须带 `viewBox`；
3. 三个区间标签 `¥0–199 / ¥200–399 / ¥400+` 必须出现；
4. 每个 `<rect data-value>` 的值必须落在 `structured_data` 白名单里（越界即打回）。

## 3. 真实打回记录（这不是编的效果）

真跑过程里一共失败了 8 次，每类都对应一个真问题：

| # | 现象 | 根因 | 处理 |
|---|---|---|---|
| 1 | `data-value` 出现 0.0154 / 0.0231 / 0.0295 被判越界 | **我的白名单过窄**（只收了百分数，没收原始比率），不是模型的错 | 白名单同时收原值、百分数、四舍五入形态 |
| 2 | `AttValue: ' expected` | 模型在文字里写了未转义的 `&` | 加 `repair_amp()` 自动修，修完再过 XML 校验 |
| 3 | 输出到一半就断，`Premature end of data` | `max_tokens=8000` 被 **reasoning tokens** 吃光（kimi-k3 是思考模型） | 提到 16000，并把 `finish_reason=length` 纳入质检 |
| 4 | 单次调用 162 s 撞我 180 s 超时 | 思考模型正常耗时 | 超时提到 420 s，超时纳入重试 |
| 5 | 空内容返回 | `max_tokens=64` 全被 reasoning 用完 | 同上，加大预算 |

结论：**kimi-k3 一次成功率高，但「思考 token 会吃掉输出预算」和「XML 转义」是两个必踩的坑**，没有质检关就会把坏 SVG 直接当成品交付。

## 4. 调用参数与实测

```python
model="kimi-k3"   temperature=1.0（服务端硬校验，传别的直接 400）
max_tokens=16000  timeout=420s  retries=2
```

最后一轮实测：

| 项 | 图表 | 信息图 |
|---|---|---|
| 字符数 | 2,834 | 3,082 |
| 尝试次数 | 1 | 1 |
| reasoning tokens | 1,655 | 4,328 |
| 总 tokens | —（该轮未入账） | 6,225（in 584 / out 5,641） |
| 耗时 | ~60 s | 141.4 s |
| 估算成本 | — | ¥0.0926 |

⚠️ 记账缺口：前面几轮打回发生在异常路径，脚本抛错退出前没写台账，那部分 token 没记进 `ledger.jsonl`。已改成 **每个视觉层 try/finally 记账**（失败、超时也记），后续不会再漏。

## 5. 现在的真实度

| 节点 | 状态 |
|---|---|
| N1 WorkBuddy | mock（缺 MCP/API） |
| N1Q 千问 | mock（缺百炼 key） |
| N2 Harness 编程 | 数据层真实（48,216 行真跑） |
| **N3 Kimi 生图** | **真实（kimi-k3，SVG + PNG）** |
| N4 Marvis | 真实（758.9 MB 索引 + 切片 + 按需全文） |
| N5 一审 | 真实（8 类确定性检查 + 硬校验） |
| N6/N7/N8 | mock（缺 WorkBuddy / 豆包） |
| L3 中转 | 真实（登记表 21 工件，21/21 核验通过） |

## 6. 怎么跑

```powershell
$env:MOONSHOT_API_KEY="你的 key"      # 不要写进代码 / 不要提交
python n3\n3_visuals.py                # 图表 + 信息图
python n3\n3_visuals.py infographic    # 只跑一张
python n3\kimi_client.py               # 连通性自测
```

## 7. 下一步

N3 通了，剩下三个真模型节点只差 key：豆包（N7 三审）、千问（N1Q 检索 + N5 异构复核）。
给我任一个，我按同一套路接：真调 → 契约校验 → 不合格打回 → 登记 L3 → 记账。
WorkBuddy 侧若能开 MCP，N1/N6/N8 也能一起换掉。
