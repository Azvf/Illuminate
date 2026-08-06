# CodeGraph Integration

CodeGraph（`colbymchenry/codegraph`）是为 AI 编码助手提供源码图谱查询的本地工具。
Illuminate 不安装、不配置、不索引 CodeGraph：安装是机器级操作，索引由 CodeGraph
自己的 watcher 维护。Illuminate 只负责**发现、验证并指导 Agent 正确使用它**。

## 分层定位

```
Illuminate Knowledge Map / 项目文档
        ↓
CodeGraph：符号定位、调用链、影响范围
        ↓
直接读取关键源码 / 配置 / 日志
        ↓
Illuminate Evidence + Behavior Verification
```

- Illuminate 决定 Agent 按什么流程分析。
- Knowledge Map 告诉 Agent 先读哪些项目知识。
- CodeGraph 帮助 Agent 快速定位哪些源码相关。
- Evidence 验证实际改动事实。
- 日志与测试验证运行时行为。

CodeGraph 不是 Harness Adapter：它不消费 Pack，只给 Harness 提供源码图谱查询能力，
因此不进 `sync_codex.py` / `sync_cursor.py` 这类 Adapter 内部。

## 安装（机器级，只执行一次）

首次安装入口（未安装 CLI 时）：`npx @colbymchenry/codegraph`，或使用平台
安装脚本（Windows: `install.ps1`；macOS/Linux: `install.sh`）。`codegraph
install` 是安装完成后的 Agent 配置子命令，不是从零安装命令。

Windows PowerShell：

```powershell
irm https://raw.githubusercontent.com/colbymchenry/codegraph/main/install.ps1 | iex
```

配置支持的 Harness（CodeBuddy 不在官方支持列表）：

```powershell
codegraph install --target=claude,cursor,codex --location=global --yes
```

| Harness     | 接入方式              |
| ----------- | --------------------- |
| Claude Code | CodeGraph MCP         |
| Codex       | CodeGraph MCP         |
| Cursor      | CodeGraph MCP         |
| CodeBuddy   | `codegraph explore` CLI |

## 项目初始化（每个目标仓库一次）

```powershell
codegraph init D:\Repo\TargetProject
codegraph status D:\Repo\TargetProject
```

- 在项目根目录建立 `.codegraph/`（本地 SQLite 图谱），watcher 自动增量同步。
- 目标项目 `.gitignore` 应包含 `.codegraph/`。
- 仅当需要排除已提交的第三方代码或自定义扩展名时，才提交 `codegraph.json`。

## Illuminate 集成

```powershell
illuminate codegraph check --repo D:\Repo\TargetProject
```

`check` 是只读诊断：验证 CLI 是否安装、`.codegraph/` 是否初始化、`codegraph status --json`
是否正常。健康时退出码 0，否则 1 并列出问题。

Illuminate 不会：

- 自动下载或安装 CodeGraph。
- 为任何 Harness 编写 MCP 配置（由 CodeGraph 安装器管理自己的标记区块，Illuminate
  与它各自维护各自的区域，互不解析重写）。
- 把 `.codegraph/` 复制进 Claude session（图谱是可变的项目本地运行时数据）。
- 把 CodeGraph DB hash 写入 Illuminate lock（watcher 自动同步会产生无意义 stale）。
- 在每次 `illuminate run` 时执行完整索引。

## 知识路由

`KNOWLEDGE_ROUTING_ORDER` 在 Metadata 之后、Source code 之前加入 CodeGraph 层：
符号定位、调用链、影响范围优先用 CodeGraph 缩小范围，最终行为结论仍需代码、配置、
日志或测试验证。

CodeGraph 默认只公开 `codegraph_explore`。

其他窄工具（`codegraph_node`、`codegraph_search`、`codegraph_callers`、
`codegraph_callees`、`codegraph_impact`、`codegraph_files`、
`codegraph_status`）只有在用户通过 `CODEGRAPH_MCP_TOOLS` 显式启用后
才会出现在 MCP 工具列表中。claude-settings 只放行默认公开的
`codegraph_explore`（最小权限，非 wildcard）。

## CodeBuddy（无 MCP）

CodeGraph MCP 不可用但 `.codegraph/` 存在时：

- `codegraph explore "<question>"`
- `codegraph impact <symbol>`
- `codegraph status`

官方 CLI 还提供 `node`、`callers`、`callees` 命令。

不要把"没有 MCP"当成"没有 CodeGraph 能力"。
