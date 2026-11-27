# WorkBuddy MCP 接入 · L3 暴露成工具

日期：2026-11-25

## 1. 先回答你的问题：能开，而且不用你点菜单

WorkBuddy 官方有 MCP 支持，配置方式是**文件**（[MCP 文档](https://www.workbuddy.cn/docs/workbuddy/From-Beginner-to-Expert-Guide/Function-Description/MCP-Guide)）：

| 级别 | 路径 |
|---|---|
| 用户级 | `~/.workbuddy/mcp.json` |
| 项目级 | `<项目>/.workbuddy/mcp.json` |

你机器上 `~/.workbuddy/` 已经存在（桌面端装过），里面本来就有别的 MCP 工具记录（miora、腾讯文档、邮箱、云数据库等），但**没有 mcp.json**——所以之前一直是"内置的那几个"，没有自定义入口。

我直接把配置写进去了。

## 2. 写了什么

### 2.1 L3 MCP Server（`l3/mcp_server.py`）

MCP over stdio，暴露 5 个工具：

| 工具 | 作用 |
|---|---|
| `l3_task_status` | 查当前任务、工件数、各节点产出、评测/验收结论、完整性核验 |
| `l3_register` | 登记工件（sha256 / 版本 / 信任等级 / 通道） |
| `l3_run_sandbox` | 跑 N5 的 9 类确定性检查并登记证据 |
| `l3_hetero_review` | 触发千问异构复核 + 裁决 |
| `l3_publish` | 发布交付稿；消费过不可信内容时必须 `confirm=true` |

**P0 闸和硬垂询在 MCP 这一层同样生效**——不是绕过协议就没人管了：

```
P0 gate: 拒绝登记：违反 P0：untrusted 工件不得进入指令通道   isError=True
hard inquiry: 本链消费过 9 个不可信工件，发布需要确认后再调并传 confirm=true  isError=True
```

### 2.2 stdio 协议实测（不是只跑单元函数）

```
init:  {"name": "dsh-l3", "version": "1.0.0"}
tools: ['l3_task_status', 'l3_register', 'l3_run_sandbox', 'l3_hetero_review', 'l3_publish']
status ok: True | isError: False   → 工件 77 个，N1/N1Q/N2/N3/N4/N5/N7 全在
```

### 2.3 配置

`~/.workbuddy/mcp.json`：

```json
{
  "mcpServers": {
    "dsh-l3": {
      "command": "C:\\Users\\gyc20\\.dsh\\dsh-runtimes\\dsh-primary-runtime\\dependencies\\python\\python.exe",
      "args": ["D:\\数据\\deepseek-harness\\default-workspace\\multi-agent\\l3\\mcp_server.py"]
    }
  }
}
```

**密钥没写进这份配置**——它可能被云端同步/上报。密钥放在项目里的 `.secrets.json`，服务器启动时自己读进环境变量。

## 3. 还差一步：重启 WorkBuddy

WorkBuddy 正在跑（5 个进程，你那边在写方案），`mcp-tool-list.json` 还是 19:05 的旧版本，没加载到 dsh-l3。

**我没有杀你的进程**——你正在里面写东西，杀掉可能丢稿。

等你方便时重启一次 WorkBuddy，然后：
- 侧边栏 **插件 → MCP 服务器**，应该看到 `dsh-l3` 绿灯；
- 或者跟我说一声，我去看 `~/.workbuddy/mcp-tool-list.json` 里有没有 `l3_task_status`，有就是加载成功。

## 4. 加载成功后能做什么

这才是 N1/N6/N8 变真的路径——**WorkBuddy 当指挥，我当执行**，而不是我冒充它：

| 你在 WorkBuddy 里说 | 实际发生 |
|---|---|
| "用 l3_task_status 看看当前进度" | 它调我的工具，读到 77 个工件、门禁 11/11 |
| "把这份二审意见登记进 L3，节点 N6" | 它调 `l3_register`，工件带 sha256 和 WorkBuddy 的 vendor 落盘 |
| "跑一遍沙箱" | 它调 `l3_run_sandbox`，我这边真编译真跑单测 |
| "可以发布" | 它调 `l3_publish(confirm=true)`，硬垂询放行，`final.md` 生成 |

到那时验收第 1 项（9/9 节点）才有可能真过——N6/N8 的产出会是 WorkBuddy 调工具产生的，不是我写的。

## 5. 风险提示

- 这份 `mcp.json` 是**用户级**，会影响你所有 WorkBuddy 项目；不想要了直接删这个文件即可。
- 服务器会执行本地 Python 脚本（就是我们的 L3 代码），只在本机跑，不联网（除非你调 `l3_hetero_review`，它会用百炼 key 联网）。
- `.secrets.json` 里有三个 key 明文，建议用完轮换。
