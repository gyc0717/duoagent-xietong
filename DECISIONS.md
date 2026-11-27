# 设计决定记录（DECISIONS）

> 只记录「有争议、被否决过、或容易被后人改回去」的决定。每条都写清现状、理由、以及推翻它需要付什么代价。

## D-001 图表由确定性代码生成，模型不得改数

**现状**
- `real/charts.py` 从 `real/out/structured_data.json` 读数
- `real/charts_real.py` 从 `real/out/ingest_report.json` 读数
- 两张图的数值直接写进 SVG 的 `data-value`，供沙箱逐值核对（`09_chart_proportionality`）

**理由**
数字必须锁在数据文件里。一旦让模型生成图表数值，就会回到「模型说多少就是多少」，
沙箱只能校形状、校不了真假；这与「脚本产事实、模型判事实」的原则冲突。

**若要让模型参与（允许的边界）**
只能写**标题、图注、解读文字**，且数值必须从 `ingest_report.json` 注入模板，
模型输出不得包含任何数字。违反即判失败，不进入下一审。

**推翻代价**
沙箱 9 类检查里的「图表 vs 数据」「比例关系」两项会同时失效，
且 N1Q 那类「把目录数字当证据」的误判会从检索层扩散到图表层。

## D-002 外部内容只能以 untrusted/data_only 进入

**现状**：网关 `/register` 强制 `trust_level=untrusted` + `channel=data_only`；
登记成功后编排层进入 tainted 态，后续步骤默认 blocked，除非 `allow_tainted=true` **且写了 reason**。

**理由**：P0 的信任隔离，不能靠编排配置自觉。

## D-003 成本分两口径，不混算

**现状**
- `provider_reported`：供应商响应里直接带回金额，才算「真实」
- `token_pricing`：只有 token，用价格表算出金额 → 仍属「估算」
- UI 顶部显示 `¥真实 / ¥估算` 两个数；单轮硬上限 ¥2，超了 402 停链

**理由**：把估算显示成账单，等于伪造财务数据。

## D-004 模型步骤只传 alias

**现状**：`/model` 只收 `moonshot-lite` / `bailian-flash` / `ark-lite` 等别名；
endpoint 与 model_id 写死在网关内；未知 alias 一律 403。

**理由**：否则编排层改一个字段就能让网关请求任意地址，subprocess 那套白名单等于白做。

## D-005 数据目录只放真数据

**现状**：`real/data/` 只应放真实业务文件与模板；合成样本放 `_scratch/`。
`file_index.py` 跳过文件名含「模板/示例/sample/demo/test」以及 0 行的 CSV。

**理由**：N4 索引会被 N8 报告当附件列出，合成文件混进去就成了「看起来有数据」。

## D-006 交付收口：3 项可验收 + 1 项阻塞，口径进字段

**现状（A 方案收口）**

交付就绪固定为五项，其中两项**永远显示为阻塞或不可用，不清零、不删除**：

| 项 | 状态 |
|---|---|
| 真实数据链路（UCI 公开数据集） | ✅ 1/1 |
| 八步全真（N1…N8，N6/N7 真调模型） | ✅ 8/8 |
| 成本口径（估算已记 + 日终对账） | ✅ 1/1（`token_pricing`，偏差待次日快照） |
| 真实计费 `provider_reported` | ⛔ 不可用（三家供应商均不回传金额） |
| 本公司业务数据 | ⛔ 阻塞 · 外部依赖 · 需用户提供内部导出 |

**为什么不是「删掉本公司数据」**
删掉会让进度页变成 4/4 全绿，而最重要的那项根本没做——这与「为了过链改题」是同一件事。
保留并标 blocked，缺口始终可见。

**口径必须进字段，不只写在报告正文**

- `ingest_report.json` 新增 `source.provenance`：
  `dataset / is_company_data / category / period / return_definition / caliber_code`
- 字段 `return_rate_pct` 改名为 **`return_line_share_pct`**：
  UCI 的 2.74% 是「退货行占订单行的比例」，不是订单退货率。
- 下游（图表、报告、二审三审提示词）全部读新字段；数字带着限定条件走，不靠人记得读报告头。

**成本对账（`real/reconcile.py`）**

- 只输出「`token_pricing` 估算合计 vs 余额差（次日快照）」的偏差率，不把估算升级为真实；
- 阈值 30% 是经验值，输出里 `threshold_pct=null` + `calibration=pending_calibration`，不作为验收线；
- append-only 写 `cohort_l3/cost_reconcile.jsonl`，一次一行，含账期、调用数、估算合计、余额差、偏差率、来源。

**推翻代价**
删掉 blocked 项 → 缺口隐身；把 `return_line_share_pct` 改回 `return_rate_pct` →
下游只截数字不截上下文时，2.74% 会被当成订单退货率，重演 N1Q 那类误判。

## D-007 真实计费只能隔夜对账，不能实时

**实测结论（2026-11-26）**

1. 供应商都不回传金额，`provider_reported` 不可用；
2. 余额接口（Moonshot `/v1/users/me/balance`）有缓存延迟：
   - 跑完立刻查差额 = ¥0.00（链路内 1 次 kimi 调用，估算 ¥0.02469）；
   - 隔夜（01:25 → 10:16）再查，差额才显现 ¥0.25019；
3. 探过 `/v1/users/me/usage`、`/v1/usage`、`/v1/billing/usage`、`/v1/users/me/billing`，全部 404；
   没有可在分钟级取到的真实扣费接口。

**因此**

- `reconcile.py --run <run_id>` 保留，但结果是 `zero_delta_cache_delay`，证明**分钟级窗口测不到**；
- 有效对账只能是 `--report --period`（隔夜快照），且必须人工确认窗口内该账户无其他调用；
- 偏差率只作**校准线索**，`calibration` 保持 `pending_calibration`，价格表要等 3–5 天同口径样本才动；
- 进度页展示「有偏差率的那条」对账行，零差额行不覆盖它。

**推翻代价**
若有人把 `--run` 的零差额当成「本次没花钱」，或把隔夜差额当成「只有本项目在跑」，
就会得出错误的单价结论——这正是上一版 -14.42% 之外的第二类口径错误。

## D-008 换数据源：v1.0 封版归档，v1.1 用课程电商数据集

**决定（2026-11-26 10:35）**

- v1.0-verification（UCI，20,000 行，GBP）封版归档到 `releases/v1.0-verification/`，**不覆盖**；
  UCI 原文件从 `real/data/` 移出，避免 N4 索引把它误列为 v1.1 附件。
- v1.1 用 U 盘只读扫描到的课程电商数据集：
  `F:\大二\GYC\项目6-3 pandas数据预处理—数据标准化\data\电商产品销售数据.csv`
  → 转换脚本 `real/convert_course_data.py` → `real/data/课程电商数据集_退款.csv`
- 源字段 `订单是否退款` 只有「是/否」，无发起/完成阶段 → 口径声明 **`refunded`（已退款）**，
  **不硬套** `started` / `completed`；指标名保持 `return_line_share_pct`，语义为「已退款订单行占比」。
- 币种 **USD**；`用户地区` 是匿名分区（地区A/B…），不是真实省份；
  源无 `退货原因` / `退款金额` 列 → **留空，不编造**（退款金额合计因此为 0，二审已指出该风险）。
- 丢弃 3,609 行 `1970/1/1` 占位日期；清洗后 360,863 行，退款行占比 4.5316%，
  GMV $89,993,969.58，AOV $249.39，时间 2023-01-05 → 2023-11-21。

**不变量**

- 八步全真 8/8，N6 Moonshot / N7 Ark 均真调模型；沙箱 9/9 `real_execution`；
- 两项阻塞保持：`provider_reported` 不可用、本公司业务数据 blocked；
- 进度页横幅从 `ingest_report.json` 动态读数据集说明，避免再次写死过时文案。

**环境适配（非判据变更）**

- `real/verify.py` 的 SVG 解析从 `lxml` 改为标准库 `xml.etree.ElementTree as etree`，
  只换解析器，`fromstring / iter / get` 接口与三处检查判据完全不变；9/9 结果可复现。
- **测试隔离修复**：`run_tests.py` 的「数据接入管线」原先跑 `real/ingest.py` 默认输出，
  会把交付产物 `real/out/ingest_report.json` / `clean_orders.csv` 覆盖成合成样本（本次实测复现）。
  给 `ingest.py` 加 `--out-dir`，测试改写到 `_scratch/test_out/`，交付产物不再被测试污染；
  重跑 `run_tests.py --quick` 3/3 通过，且 `ingest_report.json` 保持课程数据。
- **并发锁偶发 FileNotFoundError 已修（D-009）**：真根因不在 registry 临时文件，而在
  `Workspace.lock()` 的 `FileExistsError` 分支：`stat()` 与 `unlink()` 之间锁文件被别的线程
  释放，`stat()` 抛 `FileNotFoundError`。修复两处：`stat()` 加 `except FileNotFoundError: continue`
  （竞争则重试拿锁，不去 stat 已消失的路径）；`_write_registry()` 临时文件名带 pid+thread id，
  `ensure()` 移进锁内。10 次并发测试 + 30 次重复单测全过。

**推翻代价**
把 `refunded` 当订单退货率、把课程数据集当本公司/双11 数据、或用 v1.1 覆盖 v1.0，
都会让「公开数据集验证」和「业务结论」重新混为一谈——N1Q 那类误判就是这么来的。

## D-010 三项遗留的收口决定（2026-11-26 10:52）

**① 真实计费 provider_reported —— 保持 blocked + 对账自动化（用户裁决）**

- 三家供应商不回传金额，`provider_reported` **永久不可用**，不改判据、不伪造字段；
- `real/reconcile.py` 新增 `--daily`：取当日余额快照 + 有昨日快照时自动出隔夜对账，
  append-only 写 `cost_reconcile.jsonl`；无昨日快照时跳过，不拿缺窗口的余额冒充偏差；
- 已挂每日 09:00 自动化任务「L3 成本日终对账」（id `85f60c7d-…`）。
- **校准仍 `pending_calibration`**：需 3–5 天同口径样本，价格表不动；偏差只作线索，不作验收线。

**② 本公司业务数据 —— 用户决定豁免，但绝不改成"本公司"（主控守住的底线）**

- 用户选了"用课程数据顶替"，**按字面执行等于把 `is_company_data=false` 改成 true**
  ——这是伪造数据归属，正是 N1Q 那类误判的起点，**不做**；
- 等价但诚实的做法：进度页该项从 `blocked`（⛔ 阻塞）改为 `waived`（⊘ 豁免）：
  **不再卡交付**，但显示灰色、0/1、文案写「按决定以课程数据集交付（非本公司数据）；不构成业务结论」；
- `ingest_report.json` 的 `source.provenance.is_company_data` 保持 `false`，
  `dataset` 字段保持「课程电商数据集（pandas 数据预处理课程）」，一个字没改；
- 综合仍是 92%（过程 100% / 交付 83%），**没有全绿**——豁免不等于完成。

**③ 偶发单测 FileNotFoundError —— 已修（并入 D-009）**

`Workspace.lock()` 的 `stat()` 竞争已修，30 次重复单测全过；完整回归 3/3。

**推翻代价**
把豁免改成绿色/1/1、或把 `is_company_data` 改 true —— 缺口隐身且归属造假，
任何人截一张全绿图就能把 2009 年礼品杂货 / 课程数据集当成"本公司双11家电结论"，
这是整套链路建立以来唯一必须守住的红线。


