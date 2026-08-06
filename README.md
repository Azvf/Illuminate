# Illuminate

Git 版本化的**工程知识包（Knowledge Pack）编译器**与**多 AI 编码助手（Harness）同步 CLI**。

它把「工程原则、技能流程、参考知识、确定性证据工具」打包成一个版本化的知识包，在不向目标项目拷贝散乱文件的前提下，把知识包编译并同步进目标项目的 AI 编码会话中。

整个 CLI 分为三层：

- **Core（核心）** — 编译知识包：`pack` / `repo` / `mount` / `run`
- **Harness Adapters（助手适配）** — 把知识包同步进目标 AI 编码助手：`claude` / `codex` / `codebuddy` / `cursor`
- **Governance Tools（治理工具）** — 维护与审计知识：`docs` 导出与检查、`evidence` 审计、`knowledge` 知识库、`compat` 兼容目录

## 快速开始

```bash
pip install -e .
illuminate pack validate packs/core          # 校验知识包
illuminate repo inspect --repo /path/to/your/project   # 检查目标仓库
illuminate run --pack packs/core --repo /path/to/your/project --dry-run  # 预览启动命令
```

## 它是什么

Illuminate 是一套**版本化**的工程知识集合（策略、技能、参考文档、证据工具）。通过 `run` 或 `sync` 命令，它可以挂载进任意目标项目的 AI 编码会话中，而无需把文件逐个复制进项目。Pack 更新只影响之后新建的 session，已生成的 session 不可变。

## 知识包（Pack）结构

知识包目录（如 `packs/core/`）由 `pack.json` 声明，包含四类知识边界：

| 边界 | 用途 | 编译产物 |
|------|------|----------|
| `policies/` | 始终生效的原则 | 编译进 `CLAUDE.md` / 规则文件 |
| `skills/` | 按任务激活的流程 | 自动被发现并挂载 |
| `references/` | 按需读取的知识 | 需要时读取 |
| `evidence/` | 确定性执行工具 | 通过 CLI 运行 |

内置技能（`--skill` 指定，可重复）：

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

---

## 关键 Workflow

### Workflow 1：校验知识包

每次改动知识包后，先校验再使用：

```bash
illuminate pack validate packs/core
```

### Workflow 2：编译并启动 Claude Code 会话

`run` 会先在 `~/.illuminate/sessions/<id>/` 物化一个不可变会话，再启动 Claude Code：

```bash
# 1. 物化会话（只生成，不启动）
illuminate mount create --pack packs/core --repo /path/to/project --skill illuminate.layer-debug

# 2. 校验会话完整性（哈希 + 文件检查）
illuminate mount verify ~/.illuminate/sessions/<session-id>/

# 3. 物化并启动（dry-run 只打印启动命令，不执行）
illuminate run --pack packs/core --repo /path/to/project --dry-run

# 4. 实际启动，并只挂载指定技能
illuminate run --pack packs/core --repo /path/to/project --skill illuminate.layer-debug --skill illuminate.grilling

# 5. 清理会话（同时删除其外部产物）
illuminate mount remove <session-dir-or-id>
```

生成的会话目录结构：

```
CLAUDE.md              # 由 policies 编译而来
.claude/skills/        # 技能文件（仅被暴露的技能）
claude-settings.json   # 权限规则（仅来自被暴露的技能）
mount-plan.json        # 解析结果（含 git 身份）
mount-lock.json        # 文件哈希 + pack 锁哈希 + 权限范围
project-knowledge-map.md  # Knowledge Map 的 session 内副本（与同步 Harness 共用同一 Map）
```

### Workflow 3：同步到 CodeBuddy

```bash
# 同步（只同步指定技能；不指定则同步全部非别名技能）
illuminate sync codebuddy --pack packs/core --repo /path/to/project
illuminate sync codebuddy --repo /path/to/project --skill illuminate.record-knowledge

# 校验同步完整性
illuminate sync check --repo /path/to/project --harness codebuddy

# 清理 Illuminate 同步产物
illuminate sync clean --repo /path/to/project --harness codebuddy
```

生成的产物：

- `.codebuddy/rules/illuminate/` — 策略文件（按优先级排序）
- `.codebuddy/skills/` — 选定的技能（不会删除项目自有技能）
- `.codebuddy/commands/` — 快捷命令（`/record-knowledge`、`/archive-module-doc`、`/tidy-doc` 与技能绑定；`/finish-task`、`/knowledge-status`、`/propose-knowledge` 始终同步）
- `.codebuddy/CODEBUDDY.md` — 受管块（只替换 `<!-- illuminate:begin/end -->` 标记内内容）
- `.illuminate/knowledge-map.md` — Knowledge Map（flat-classified 布局时生成）
- `.illuminate/codebuddy-lock.json` — 同步清单（带哈希与 `knowledge_map_hash`）

不修改项目自有的 `.codebuddy` 内容。

### Workflow 4：同步到 Cursor

```bash
# 默认模式：写入 .cursor/rules/illuminate/core.mdc
illuminate sync cursor --pack packs/core --repo /path/to/project
illuminate sync cursor --repo /path/to/project --skill illuminate.record-knowledge

# 兼容模式：合并到根 AGENTS.md（与 Codex 共享 AGENTS.md 的项目）
illuminate sync cursor --repo /path/to/project --agents-compat

# 校验同步完整性
illuminate sync check --repo /path/to/project --harness cursor

# 只读诊断（exit 0 = 健康，1 = 存在问题）
illuminate sync doctor --repo /path/to/project --harness cursor

# 清理
illuminate sync clean --repo /path/to/project --harness cursor
```

生成的产物（默认模式）：

- `.cursor/rules/illuminate/core.mdc` — 策略文件与同步技能列表（`alwaysApply: true`，治理策略始终进入 Cursor 上下文）
- `.cursor/skills/` — 选定的技能（不删除项目自有技能）
- `.cursor/commands/` — 快捷命令
- `.illuminate/knowledge-map.md` — Knowledge Map（flat-classified 布局时生成）
- `.illuminate/cursor-lock.json` — 同步清单（带哈希、`rules_md_hash` 与 `knowledge_map_hash`）

不修改项目自有的 `.cursor` 内容，不生成 `.cursor/cli.json` 或 `.agents/skills`。

### Workflow 5：同步到 Codex

```bash
# 同步（写入 AGENTS.md + .agents/skills + openai.yaml）
illuminate sync codex --pack packs/core --repo /path/to/project
illuminate sync codex --repo /path/to/project --skill illuminate.perf-profile

# 校验同步完整性
illuminate sync check --repo /path/to/project --harness codex

# 清理
illuminate sync clean --repo /path/to/project --harness codex
```

生成的产物：

- `AGENTS.md` — Illuminate 策略块（通过 `<!-- illuminate:... -->` 标记合并，不触碰标记外内容）
- `.agents/skills/` — 选定的技能（lock 管护）
- `.agents/skills/*/agents/openai.yaml` — 每个技能的 App 元数据
- `.illuminate/knowledge-map.md` — Knowledge Map（flat-classified 布局时生成）
- `.illuminate/codex-lock.json` — 同步清单（带哈希与 `knowledge_map_hash`）

### 跨 Harness：Project Knowledge Routing

当目标仓库采用 flat-classified 文档布局时，Illuminate 会生成 `.illuminate/knowledge-map.md`。

```markdown
## Project Knowledge Routing

When the target repository uses the flat-classified documentation layout,
Illuminate generates `.illuminate/knowledge-map.md`.

The map indexes Journeys, Modules, Components, and Metadata entry points.
Harness policies instruct agents to read it before broad source search.

Run `illuminate sync check` after documentation changes and re-run sync when
the map is reported stale.
```

Knowledge Map 从 `docs/README-HUMAN.md`、`docs/human-docs.json`、`docs/40-journeys/` 与 `docs/70-metadata/*/*.yaml` 生成，索引 Journeys / Modules / Components / Metadata 入口点。Harness 策略会指示 Agent 在广泛源码搜索前先读取该 Map。

多个同步 Harness（CodeBuddy / Cursor / Codex）共用同一份 `.illuminate/knowledge-map.md`；Claude 使用 session 内副本 `project-knowledge-map.md`，指向同一 Map 内容。每个 harness 的 lock 文件记录 `knowledge_map_hash`，用于 `sync check` 检测文档变化（基于文本 hash 比对）。

手工修改或放置的 Map 会被 `sync check` 判定为异常（unmanaged 文件）；若存在未被任何 harness lock 记录的 Map，需将其移动或使用 `--force` 处理，而非直接删除（Illuminate 不删除非自身管理的文件）。

### Workflow 6：证据审计（Evidence Audit）

用确定性脚本测量目标仓库的代码变更，输出事实报告（而非评分）：

```bash
illuminate evidence audit --repo /path/to/project --pretty
# 可指定知识包，绑定报告的 pack 身份
illuminate evidence audit --repo /path/to/project --pack packs/core --output report.json --pretty
```

报告输出：`<repo>/.illuminate/reports/evidence.json`

配置层（从低到高覆盖）：

1. 内置默认值
2. 知识包 `patterns_config.json`
3. 项目 `.illuminate/evidence/patterns_overlay.json`

### Workflow 7：人类可读文档导出与检查

以人类可读 Markdown 为源真理，声明与证据、测试元数据分离存放。在文档根目录旁放一个可选的 `human-docs.json`：

```json
{
  "layout": "flat-classified",
  "human_roots": {
    "components": "20-components",
    "modules": "30-modules",
    "journeys": "40-journeys"
  },
  "metadata_root": "70-metadata",
  "require_manifests": true,
  "doc_refs": "root-relative",
  "include": [
    "README-HUMAN.md",
    "20-components/*.md",
    "30-modules/*.md",
    "40-journeys/*.md"
  ],
  "exclude": [
    "70-metadata/**",
    "80-evidence/**",
    "90-generated/**",
    "99-archive/**"
  ],
  "readme": "README-HUMAN.md"
}
```

```bash
# 只复制配置选中的 Markdown，并把 README-HUMAN.md 映射为导出根目录的 README.md（不解析、不改写正文）
illuminate docs export-human --source /path/to/docs --output /path/to/human-docs --config /path/to/docs/human-docs.json

# 检查人类可读 Markdown 规则与本地链接
illuminate docs lint-human --source /path/to/docs --config /path/to/docs/human-docs.json

# 校验 Manifest owner、元数据 ID 与 YAML 的 doc_refs
illuminate docs lint-knowledge --source /path/to/docs
```

### Workflow 8：知识库备份与恢复（Knowledge Store）

本地备份与恢复工具。项目采用 `flat-classified` 布局时，可在仓库根放一个可选的 `knowledge-manifest.json`，其 roots 与 patterns 相对于 `docs/`：

```json
{
  "roots": ["20-components", "30-modules", "40-journeys", "70-metadata", "README-HUMAN.md", "human-docs.json"],
  "include": ["**/*"],
  "exclude": ["80-evidence/**", "90-generated/**", "99-archive/**", "dist/**"]
}
```

```bash
# 拉取项目知识到中央库（~/.illuminate/knowledge），保留三方基线以处理冲突与删除
illuminate knowledge pull --repo /path/to/project --manifest /path/to/project/knowledge-manifest.json

# 对比项目知识与中央库
illuminate knowledge status --repo /path/to/project --manifest /path/to/project/knowledge-manifest.json

# 把中央库文档安全地推回项目（自上次基线以来被改过的文件默认拒绝覆盖，需 --force）
illuminate knowledge push --repo /path/to/project --manifest /path/to/project/knowledge-manifest.json
```

`70-metadata` 把 Manifest 身份与校验 YAML 与人类可读 Markdown 分离存放。Git 负责历史、分支与协作；Store 只负责备份/差异/冲突/恢复。

### Workflow 9：知识晋升（Knowledge Promotion Bridge）

把 Store（备份工具）中的知识晋升为 Harness Pack（Git 版本化、经评审的通用知识）的薄桥。状态机：`raw → reviewed → promoted`，另有 `raw/reviewed → rejected`、`promoted → superseded`。注册表位于 `<store>/projects/<project-id>/promotions.json`。

```bash
# 1. 从知识源创建候选（记录 git 远端、commit、docs 相对路径、anchor 与精确字节）
illuminate knowledge candidate --repo /path/to/project --source 30-modules/hot-update.md --target reference

# 2. 评审：绑定且只绑定一次 —— 要么绑定源码，要么用 --content 绑定泛化草稿
illuminate knowledge review --repo /path/to/project --id <candidate-id> --reviewer alice
# illuminate knowledge review --repo /path/to/project --id <candidate-id> --reviewer alice --content generalized.md

# 3. 晋升进知识包（受 reviewed_sha256 守护：评审后改过的内容会被拒绝；先 --dry-run 预览计划）
illuminate knowledge promote --repo /path/to/project --id <candidate-id> --pack packs/core --dry-run
illuminate knowledge promote --repo /path/to/project --id <candidate-id> --pack packs/core

# 4. 拒绝候选，或把已晋升的标记为 superseded（并从 pack 移除产物）
illuminate knowledge reject --repo /path/to/project --id <candidate-id>
# illuminate knowledge reject --repo /path/to/project --id <candidate-id> --superseded --pack packs/core
```

关键约束：

- 晋升目标：`reference`（追加到 `pack.json.references`）、`policy`（追加到 `policies/index.json`）、`skill`（写 `skills/<name>/SKILL.md` + 最小 `contract.json`）、`evidence`（设置 `pack.json.evidence.config`）。
- 写入后自动运行 `validate_pack`；校验失败则整体回滚（文件 + manifest + index）。
- 晋升不暂存、不提交：只写入 Pack 工作树，commit 与 PR 留给 Git 与人工。
- 更名升级用 `--replaces <id>` 声明前任；未声明 owner 的产物拒绝被 `superseded` 删除。

### Workflow 10：生成兼容目录

为期望旧版 `.claude/skills/` 布局的工具生成兼容目录：

```bash
illuminate compat generate --pack packs/core
illuminate compat check --pack packs/core   # 校验与规范源一致（文件 + SHA-256）
```

---

## 权限模型

- 契约 `permissions.execute` 编译进 `claude-settings.json` 的 allow 规则。
- 契约 `permissions.read` 与 `permissions.write` 只在 lock 中声明，Claude Code 不强制执行。
- 只有被选中的（`--skill`）技能才参与会话。

## 项目结构

- `packs/core/` — 核心知识包（policies、skills、references、evidence 配置）
- `src/illuminate/` — CLI 实现（validate、resolve、materialize、evidence、sync、knowledge 等）
- `src/illuminate/schemas/` — pack / contract / mount-plan / mount-lock 的 JSON Schema（随包分发）
- `tests/` — 单元测试
- `evals/routing/` — 路由评估用例

## 安装

```bash
pip install -e .
```

命令行入口：`illuminate`（由 `pyproject.toml` 的 `[project.scripts]` 注册，Python >= 3.9，零运行时依赖）。
