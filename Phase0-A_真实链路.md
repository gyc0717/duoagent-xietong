# 方案 A 落地记录 · 真实 L3 + 真实 N5 + 真实 N4

日期：2026-11-25　执行方：DeepSeek Harness
目录：`D:\数据\deepseek-harness\default-workspace\multi-agent`

这一步不碰外部模型，把「本机能做实的」做实：**中转层、证据层、本地资料层**。
原 PoC 的这三块分别是：`cohort/` 裸目录、写死的沙箱常量、MockLLM 一句文案。

## 1. L3 协同中间层（`l3/workspace.py`）

| 能力 | 实现 | 验收 |
|---|---|---|
| 8 子目录骨架 | `init()` 建 inbox/claims/artifacts/reviews/eval/memory/quarantine/outbox | ✅ |
| 工件登记表 | id / node / role / uri / **sha256** / **version** / content_mode / **trust_level** / **channel** / provenance / trace_id | 17 条 |
| 同名自动版本 | 同 node+name 再登记 → version+1，旧件保留 | 单测覆盖 |
| 文件锁 | `O_CREAT\|O_EXCL` + 超时 + 陈旧锁回收（默认 120s） | 单测：互斥 + 陈旧回收 |
| append-only 台账 | `ledger.jsonl`，每行带 ts/trace_id | 19 条 |
| 完整性核验 | 重算 sha256，区分 missing / tampered | 真实篡改演示见 §4 |
| **P0 硬闸** | `untrusted` + `instruction` 组合直接 `ValueError`；不是文档约定，是代码断言 | ✅ 拦住 |

P0 的 `trust_level` / `channel` 从「工件登记表上的备注」变成了**写入前的硬校验**——这是 v1.6 文档里 S1.13 第 1、3 条要求的真实形态。

## 2. N5 一审内调用点（`l3/n5_executor.py`）

把上一轮那个「先跑一次」的 `real/verify.py` 固化成一审内部调用点：

```
execute(ws) → run_verifier() → assert_real() → ws.register()
```

`assert_real()` 三条硬规则：
1. 8 个检查项缺一即 `SandboxViolation`；
2. `evidence_source != "real_execution"` 一律拒绝（防退回常量）；
3. 执行器退出码非 0 不放行。

实测：`real_execution / 379.3 ms`，工件 `artifacts/N5_execution_evidence.v1.json`，登记进登记表。
**这是方案里 P1 第一次真正挂进 N5**——原来它只是 `run_sandbox()` 里一个 `if`。

## 3. N4 本地资料与大文件（`n4/indexer.py`）

对真实目录跑了一次（`music-hub/dist/installer`，里面有真的大文件）：

```
221 文件 / 758.9 MB / 大文件 6 个（阈值 8 MB）/ 全量 sha256 用时 8.6s（含整条链路）
```

- 大文件按 4 MiB 切片建 `chunks`（offset/length），**不整份进上下文**；
- `summary_card()` 产出「摘要 + URI」双通道，大文件标 `content_mode=SUMMARY_PLUS_URI`；
- `load_fulltext(rel)` 按需读盘，默认**整份返回、不截断**（`truncated=False`），只有调用方显式传 `max_bytes` 才截；
- 跳 `.git` / `node_modules` / `__pycache__` 等噪声目录。

这对应方案里 Marvis 的「索引 / 切片 / 按需全文」，边界也守住了：**只在本机读，不出本地**。

## 4. 真实运行结果

### 4.1 小目录（项目自身产物）
```
✓ P0 闸拦住：untrusted 工件不得进入指令通道
✓ N3 登记 5 张 SVG
✓ N5 沙箱 real_execution / 721.2ms
✓ N4 索引 8 文件 / 1.5 MB
✓ 完整性核验 17/17
工件 17 · 节点 N1/N1Q/N3/N4/N5 · trusted 15 / untrusted 2 · 台账 19 条
```

### 4.2 大目录（真实 758.9 MB）
```
✓ N4 索引 221 文件 / 758.9 MB / 大文件 6 个
✓ 完整性核验 9/9
```

### 4.3 篡改检测（真事）
把 `artifacts/N1_dispatch.v1.json` 改成 `{"tampered":true}`：
```
verify → ok 16/17, tampered ["A-001"], pass=false
```
按原字节还原后：`ok 17/17, pass=true`。
—— 登记表不是记账，是**可验证**的。

### 4.4 单测
```
Ran 16 tests in 0.805s — OK
```
覆盖：目录骨架、sha256、版本递增、P0 闸、锁互斥、陈旧锁回收、篡改检测、缺失检测、台账有序、6 线程并发登记不撕登记表、索引跳目录、大文件切片、按需全文、显式截断标记、摘要卡通道。

## 5. 现在的真实度

| 节点 | 之前 | 现在 |
|---|---|---|
| N2 Harness 编程 | mock 文案 | 仍 mock（但数据层 `real/` 是真的） |
| N4 Marvis | mock 文案 | **真实索引 758.9 MB / 切片 / 按需全文** |
| N5 一审 | 写死常量 | **真实执行 + 硬校验 + 登记** |
| L3 中转 | `cohort/` 裸目录 | **登记表 + 锁 + sha256 + 台账 + P0 硬闸** |
| N1/N3/N6/N7/N8 | mock | 仍 mock（需要 WorkBuddy / Kimi / 豆包 API） |

## 6. 怎么跑

```powershell
cd D:\数据\deepseek-harness\default-workspace\multi-agent
python run_l3.py                                    # 小目录
python run_l3.py "…\music-hub\dist\installer" cohort_l3_big   # 真实大目录
python -m unittest discover -s tests -v             # 16 个单测
python l3\workspace.py verify cohort_l3             # 完整性核验
python poc\multi_agent_poc.py                       # 9 节点主链（含真沙箱）
```

## 7. 下一步（仍未解决）

换成真模型只剩一件事：**key**。给我 Kimi / 豆包 / 千问任一，我把 N3 / N7 / N1Q 换掉；
WorkBuddy 侧如果开 MCP，N1/N6/N8 也能从 mock 换成真调用。架构不用动——L3 的接口现在是真的了。
