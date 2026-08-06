# Harness 同步（Harnesses）

`sync` 把知识包同步进目标 AI 编码助手，每个 harness 有独立的产物清单与 lock 文件。

所有 `sync` 命令的 `--repo` 默认当前目录、`--pack` 默认内置 Core Pack，可省略。

## Codex

```bash
illuminate sync codex                            # 同步全部非别名技能
illuminate sync codex --skill illuminate.perf-profile
illuminate sync check                            # 校验（自动识别 harness）
illuminate sync clean --harness codex            # 清理
```

生成的产物：

- `AGENTS.md` — Illuminate 策略块（通过 `<!-- illuminate:... -->` 标记合并，不触碰标记外内容）
- `.agents/skills/` — 选定的技能（lock 管护）
- `.agents/skills/*/agents/openai.yaml` — 每个技能的 App 元数据
- `.illuminate/knowledge-map.md` — Knowledge Map（flat-classified 布局时生成）
- `.illuminate/codex-lock.json` — 同步清单（带哈希与 `knowledge_map_hash`）

## CodeBuddy

```bash
illuminate sync codebuddy                        # 同步全部非别名技能
illuminate sync codebuddy --skill illuminate.record-knowledge
illuminate sync check
illuminate sync clean --harness codebuddy
```

生成的产物：

- `.codebuddy/rules/illuminate/` — 策略文件（按优先级排序）
- `.codebuddy/skills/` — 选定的技能（不会删除项目自有技能）
- `.codebuddy/commands/` — 快捷命令（`/record-knowledge`、`/archive-module-doc`、`/tidy-doc` 与技能绑定；`/finish-task`、`/knowledge-status`、`/propose-knowledge` 始终同步）
- `.codebuddy/CODEBUDDY.md` — 受管块（只替换 `<!-- illuminate:begin/end -->` 标记内内容）
- `.illuminate/knowledge-map.md` — Knowledge Map（flat-classified 布局时生成）
- `.illuminate/codebuddy-lock.json` — 同步清单（带哈希与 `knowledge_map_hash`）

不修改项目自有的 `.codebuddy` 内容。

## Cursor

```bash
# 默认模式：写入 .cursor/rules/illuminate/core.mdc
illuminate sync cursor

# 兼容模式：合并到根 AGENTS.md（与 Codex 共享 AGENTS.md 的项目）
illuminate sync cursor --agents-compat

# 校验 / 只读诊断 / 清理
illuminate sync check
illuminate sync doctor --harness cursor    # exit 0 健康，1 存在问题
illuminate sync clean --harness cursor
```

生成的产物（默认模式）：

- `.cursor/rules/illuminate/core.mdc` — 策略文件与同步技能列表（`alwaysApply: true`，治理策略始终进入 Cursor 上下文）
- `.cursor/skills/` — 选定的技能（不删除项目自有技能）
- `.cursor/commands/` — 快捷命令
- `.illuminate/knowledge-map.md` — Knowledge Map（flat-classified 布局时生成）
- `.illuminate/cursor-lock.json` — 同步清单（带哈希、`rules_md_hash` 与 `knowledge_map_hash`）

不修改项目自有的 `.cursor` 内容，不生成 `.cursor/cli.json` 或 `.agents/skills`。

## sync check / clean / doctor 语义

- **`sync check`**：校验某个 harness 的同步完整性。不带 `--harness` 时根据 `.illuminate/` 下已有的 lock 自动识别。检查内容包括：受管文件的哈希是否匹配、lock 是否记录 `knowledge_map_hash`、Knowledge Map 是否过期或异常（unmanaged 文件）。只读，不写盘。
- **`sync clean`**：移除 Illuminate 同步产物（lock 记录的文件），不触碰项目自有文件。`--harness` 指定目标，默认 `codex`。
- **`sync doctor`**：Cursor 专用的只读诊断，检查 lock 是否存在、规则文件哈希、技能/命令缺失或哈希不匹配、stale 产物。exit 0 = 健康，1 = 存在问题。

## lock 字段说明

各 harness 的 lock（`.illuminate/<harness>-lock.json`）为同步清单，包含：

- `pack`：pack id / version / hash（`pack_lock_hash`）
- `target.path`：目标仓库路径
- `exposed_skills`：已同步的技能列表
- 产物哈希：`rules_md_hash`（Cursor 默认模式）/ `agents_md_hash`（Cursor 兼容模式）
- `knowledge_map_hash`：Knowledge Map 的文本哈希（存在时记录）
- `created_at`：同步时间
- `agents_compat`（Cursor）：记录所选模式，使 check/clean 跟随 sync 使用的路径

## --agents-compat

Cursor 的 `--agents-compat` 把策略合并进根 `AGENTS.md` 的受管块，而非写入 `.cursor/rules/illuminate/core.mdc`。用于与 Codex 共享根 `AGENTS.md` 的项目。所选模式记录在 lock 的 `agents_compat` 字段，check/clean 会沿用该路径。
