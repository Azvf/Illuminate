# Illuminate

让 AI 编码助手**优先使用项目知识，再进入源码搜索**的工程知识包编译器与多 Harness 同步 CLI。

支持 Cursor、Codex、CodeBuddy、Claude Code。它把「工程原则、技能流程、参考知识、确定性证据工具」打包成一个 Git 版本化的知识包，在不向目标项目拷贝散乱文件的前提下，同步进目标项目的 AI 编码会话。

## 30 秒开始

```bash
pip install -e .
```

在目标项目根目录执行同步（`--repo` 默认当前目录，可省略）：

| 编码助手 | 命令 |
|---------|------|
| Cursor | `illuminate sync cursor` |
| Codex | `illuminate sync codex` |
| CodeBuddy | `illuminate sync codebuddy` |
| Claude Code | `illuminate run` |

检查同步是否完整：

```bash
illuminate sync check
```

不带 `--harness` 时，`sync check` 会根据 `.illuminate/` 下已有的 lock 自动识别目标 harness。

## 日常使用

```bash
illuminate sync cursor        # 重新同步（幂等，安全可重复）
illuminate sync check         # 校验同步完整性（lock + 哈希 + Knowledge Map）
illuminate sync clean --harness cursor   # 清理 Illuminate 同步产物（不触碰项目自有文件）
```

Pack 更新后重新同步即可，已生成的 Claude session 不可变。

## 它做了什么

- **注入规则与技能**：把 policies / skills / references / evidence 编译进目标助手的规则文件与会话。
- **生成 Knowledge Map**：flat-classified 布局下生成 `.illuminate/knowledge-map.md`，索引 Journey / Module / Component / Metadata。
- **引导优先读文档**：Harness 策略指示 Agent 在广泛源码搜索前先读取 Knowledge Map。
- **Lock + Hash 检测过期**：每个 harness 有 lock 文件记录哈希，`sync check` 据此判断同步是否过期。
- **不覆盖未托管文件**：只写 Illuminate 管理的内容，绝不删除或覆盖项目自有的非托管文件。

## 常用操作

| 操作 | 命令 | 说明 |
|------|------|------|
| 重新同步 | `illuminate sync <harness>` | 幂等，重复执行安全 |
| 检查 | `illuminate sync check` | 自动识别 harness，验证完整性 |
| 清理 | `illuminate sync clean --harness <harness>` | 移除 Illuminate 产物 |
| 只读诊断 | `illuminate sync doctor --harness cursor` | Cursor 专用，exit 0 健康 / 1 有问题 |

`--force` **仅当** `sync` 报 `.illuminate/knowledge-map.md` "exists but is not managed by any Illuminate lock" 时，用于授权覆盖这个未托管的知识地图文件。

## CodeGraph（源码图谱）

[CodeGraph](https://github.com/colbymchenry/codegraph) 是为 AI 编码助手提供源码图谱查询的本地工具。Illuminate 不安装、不配置、不索引 CodeGraph，只负责**发现、验证并指导 Agent 正确使用它**。

```bash
# 机器级（只执行一次）：安装 CLI + 配置 Claude/Cursor/Codex 的 MCP
#   irm https://raw.githubusercontent.com/colbymchenry/codegraph/main/install.ps1 | iex
#   codegraph install --target=claude,cursor,codex --location=global --yes

# 项目级：每个目标仓库初始化一次
codegraph init
codegraph status

# Illuminate 只读诊断：CLI 是否安装、索引是否存在、status 是否正常
illuminate codegraph check
```

- CodeBuddy 不在 CodeGraph 官方支持列表，使用 `codegraph explore "<question>"` / `codegraph impact <symbol>`。
- 知识路由在 Metadata 之后、源码验证之前加入 CodeGraph 层；CodeGraph 用于缩小源码范围，不替代日志、测试和最终源码验证。
- 详见 `packs/core/references/codegraph-integration.md`。

## 高级能力

详细文档见 `docs/`：

- [docs/architecture.md](docs/architecture.md) — 三层架构、Pack 结构、四大知识边界、Claude session mount 生命周期、权限模型
- [docs/harnesses.md](docs/harnesses.md) — Codex / CodeBuddy / Cursor 产物清单、sync check / clean / doctor、lock 字段
- [docs/documentation.md](docs/documentation.md) — 人类可读文档规范、docs export / lint、Knowledge Routing
- [docs/evidence.md](docs/evidence.md) — Evidence Layer 三层模型、evidence audit、报告与配置覆盖层
- [docs/knowledge-store.md](docs/knowledge-store.md) — 知识库备份恢复、pull / status / push
- [docs/promotion.md](docs/promotion.md) — 知识晋升桥（状态机、candidate / review / promote / reject）
- [docs/pack-development.md](docs/pack-development.md) — pack validate、compat、resolve、项目结构（贡献者）

## 开发

```bash
illuminate pack validate packs/core   # 校验知识包
python -m pytest tests/ -q            # 运行测试
```

命令行入口 `illuminate` 由 `pyproject.toml` 的 `[project.scripts]` 注册，Python >= 3.9，零运行时依赖。
