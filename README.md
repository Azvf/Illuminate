# Illuminate

让 AI 编码助手**优先使用项目知识，再进入源码搜索**的工程知识包编译器与多 Harness 同步 CLI。

支持 Cursor、Codex、CodeBuddy、Claude Code。

## 开始使用

```bash
pip install -e .
```

在目标项目根目录执行同步（`--repo` 默认当前目录、`--pack` 默认内置 Core Pack，均可省略）：

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

不带 `--harness` 时，`sync check` 根据 `.illuminate/` 下的 lock 自动识别目标 harness。

## 它做了什么

- **注入规则与技能**：把 policies / skills / references / evidence 编译进目标助手的规则文件与会话。
- **生成 Knowledge Map**：生成 `.illuminate/knowledge-map.md`，索引 Journey / Module / Component / Metadata。
- **引导优先读文档**：Harness 策略指示 Agent 在广泛源码搜索前先读取 Knowledge Map。
- **Lock + Hash 检测过期**：每个 harness 有 lock 文件记录哈希，`sync check` 据此判断同步是否过期。
- **默认拒绝覆盖未托管文件**：只写 Illuminate 管理的内容；仅当 `sync` 报 `.illuminate/knowledge-map.md` 未被任何 lock 托管时，可用 `--force` 授权覆盖。

## 高级能力

详细文档见 `docs/`：

- [docs/architecture.md](docs/architecture.md) — 三层架构、Pack 结构、Claude session 生命周期、权限模型
- [docs/harnesses.md](docs/harnesses.md) — 各 Harness 产物、`sync check` / `clean` / `doctor`、lock 字段
- [docs/documentation.md](docs/documentation.md) — 人类可读文档规范、docs export / lint、Knowledge Routing
- [docs/evidence.md](docs/evidence.md) — Evidence Layer、evidence audit、配置覆盖层
- [docs/knowledge-store.md](docs/knowledge-store.md) — 知识库备份恢复
- [docs/promotion.md](docs/promotion.md) — 知识晋升桥
- [docs/pack-development.md](docs/pack-development.md) — pack validate、compat、resolve（贡献者）
- [docs/codegraph.md](docs/codegraph.md) — 可选：接入 CodeGraph 缩小源码检索范围

## 开发

```bash
illuminate pack validate src/illuminate/builtin_pack   # 校验内置知识包
python -m pytest tests/ -q                              # 运行测试
```

命令行入口 `illuminate` 由 `pyproject.toml` 的 `[project.scripts]` 注册，Python >= 3.9，零运行时依赖。
