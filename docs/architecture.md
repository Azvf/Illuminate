# 架构（Architecture）

Illuminate 是一个 Git 版本化的**工程知识包（Knowledge Pack）编译器**与**多 AI 编码助手（Harness）同步 CLI**。

它把「工程原则、技能流程、参考知识、确定性证据工具」打包成一个版本化的知识包，在不向目标项目拷贝散乱文件的前提下，编译并同步进目标项目的 AI 编码会话。Pack 更新只影响之后新建的 session，已生成的 session 不可变。

## 三层架构

- **Core（核心）** — 编译知识包：`pack` / `repo` / `mount` / `run`
- **Harness Adapters（助手适配）** — 把知识包同步进目标 AI 编码助手：`sync codex` / `codebuddy` / `cursor` / `check` / `clean` / `doctor`
- **Governance Tools（治理工具）** — 维护与审计知识：`docs` 导出与检查、`evidence` 审计、`knowledge` 知识库、`compat` 兼容目录

## Pack 结构

知识包目录（如内置的 `src/illuminate/builtin_pack/`）由 `pack.json` 声明，包含四类知识边界：

| 边界 | 用途 | 编译产物 |
|------|------|----------|
| `policies/` | 始终生效的原则 | 编译进 `CLAUDE.md` / 规则文件 |
| `skills/` | 按任务激活的流程 | 自动被发现并挂载 |
| `references/` | 按需读取的知识 | 需要时读取 |
| `evidence/` | 确定性执行工具 | 通过 CLI 运行 |

## 技能清单

`pack.json` 声明 12 个技能：

| 技能 ID | 用途 |
|---------|------|
| `illuminate.layer-debug` | 功能链路排障 |
| `illuminate.impact-analysis` | 改动前影响评估 |
| `illuminate.perf-profile` | 性能分析 |
| `illuminate.behavior-verification` | 行为正确性验证 |
| `illuminate.backtrack-root-cause` | 排障陷入死循环时回溯根因 |
| `illuminate.simplify-code` | 代码精简诊断 |
| `illuminate.grilling` | 设计压力测试 |
| `illuminate.ref-align` | 对接第三方 SDK / API 逆向对齐 |
| `illuminate.record-knowledge` | 记录已验证知识 |
| `illuminate.archive-module-doc` | 模块文档归档 |
| `illuminate.tidy-doc` | 文档整理 |
| `illuminate.grill-me` | `grilling` 的别名入口（`/grilling` 会话） |

用 `--skill <id>` 指定要暴露/同步的技能，可重复。

## Claude session mount 生命周期

`run` 会先在 `~/.illuminate/sessions/<id>/` 物化一个不可变会话，再启动 Claude Code：

```bash
# 1. 物化会话（只生成，不启动）
illuminate mount create --pack src/illuminate/builtin_pack --skill illuminate.layer-debug

# 2. 校验会话完整性（哈希 + 文件检查）
illuminate mount verify ~/.illuminate/sessions/<session-id>/

# 3. 物化并启动（dry-run 只打印启动命令，不执行）
illuminate run --dry-run

# 4. 实际启动，并只挂载指定技能
illuminate run --skill illuminate.layer-debug --skill illuminate.grilling

# 5. 清理会话（同时删除其外部产物）
illuminate mount remove <session-dir-or-id>
```

`run` 无参数时 `--pack` 默认内置 Core Pack、`--repo` 默认 `.`。如需指定仓库，等价写法为 `--repo <path>`。

生成的会话目录结构：

```
CLAUDE.md                # 由 policies 编译而来
.claude/skills/          # 技能文件（仅被暴露的技能）
claude-settings.json     # 权限规则（仅来自被暴露的技能）
mount-plan.json          # 解析结果（含 git 身份）
mount-lock.json          # 文件哈希 + pack 锁哈希 + 权限范围
project-knowledge-map.md # Knowledge Map 的 session 内副本（与同步 Harness 共用同一 Map）
```

`mount verify` 检查 lock 记录的每个文件的哈希，发现缺失 / 篡改 / 多余文件时报错。

## 权限模型

- 契约 `permissions.execute` 编译进 `claude-settings.json` 的 allow 规则。
- 契约 `permissions.read` 与 `permissions.write` 只在 lock 中声明，Claude Code 不强制执行。
- 只有被选中的（`--skill`）技能才参与会话。
