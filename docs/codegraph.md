# CodeGraph（源码图谱）

[CodeGraph](https://github.com/colbymchenry/codegraph) 是为 AI 编码助手提供源码图谱查询的本地工具。

## Illuminate 的角色

Illuminate **不安装、不配置、不索引** CodeGraph，只负责**发现、验证并指导 Agent 正确使用它**：

- `illuminate codegraph check` 做只读诊断：CLI 是否安装、索引是否存在、`codegraph status` 是否正常。
- 知识路由在 Metadata 之后、源码验证之前加入 CodeGraph 层；CodeGraph 用于缩小源码范围，**不替代**日志、测试和最终源码验证。

## 安装与初始化

```bash
# 机器级（只执行一次）：安装 CLI + 配置 Claude / Cursor / Codex 的 MCP
irm https://raw.githubusercontent.com/colbymchenry/codegraph/main/install.ps1 | iex
codegraph install --target=claude,cursor,codex --location=global --yes

# 项目级：每个目标仓库初始化一次
codegraph init
codegraph status

# Illuminate 只读诊断
illuminate codegraph check
```

## 注意事项

- CodeBuddy 不在 CodeGraph 官方支持列表，使用 `codegraph explore "<question>"` / `codegraph impact <symbol>`。
- 详细集成说明见 `src/illuminate/builtin_pack/references/codegraph-integration.md`。
