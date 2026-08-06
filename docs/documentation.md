# 人类可读文档（Documentation）

以人类可读 Markdown 为源真理，声明与证据、测试元数据分离存放。文档根目录旁可放一个可选的 `human-docs.json` 声明布局与 include / exclude 规则。

## human-docs.json 配置示例

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

## 导出与检查命令

```bash
# 只复制配置选中的 Markdown，并把 README-HUMAN.md 映射为导出根目录的 README.md（不解析、不改写正文）
illuminate docs export-human --source /path/to/docs --output /path/to/human-docs

# 检查人类可读 Markdown 规则与本地链接（--config 默认取 <source>/human-docs.json）
illuminate docs lint-human --source /path/to/docs

# 校验 Manifest owner、元数据 ID 与 YAML 的 doc_refs
illuminate docs lint-knowledge --source /path/to/docs
```

- `docs export-human`：把配置 include 选中的文件复制到输出目录，README 源映射为输出根的 `README.md`。`--force` 可覆盖非空输出目录。
- `docs lint-human`：检查 Markdown 规则与本地链接完整性。`--all-markdown` 可检查 source 下所有 Markdown。
- `docs lint-knowledge`：校验 Manifest owner、元数据 ID 与 YAML 的 `doc_refs` 一致性。

`--config <json>` 可显式指定配置文件；未指定时默认读取 `<source>/human-docs.json`（若存在）。

## Knowledge Routing

当目标仓库采用 flat-classified 文档布局时，Illuminate 生成 `.illuminate/knowledge-map.md`。路由顺序：

1. Journey（跨模块行为）
2. Module（模块内职责）
3. Component（组件实现）
4. Metadata（元数据 / 身份）
5. Source（源码）

Knowledge Map 从 `docs/40-journeys/*.md`、`docs/70-metadata/modules/*/module.yaml`、`docs/70-metadata/components/*/component.yaml` 生成（若 `docs/README-HUMAN.md` 存在则作为入口列出）。Harness 策略会指示 Agent 在广泛源码搜索前先读取该 Map。

多个同步 Harness（CodeBuddy / Cursor / Codex）共用同一份 `.illuminate/knowledge-map.md`；Claude 使用 session 内副本 `project-knowledge-map.md`，指向同一 Map 内容。每个 harness 的 lock 记录 `knowledge_map_hash`，`sync check` 据此检测文档变化（基于文本 hash 比对）。

手工修改或放置的 Map 会被 `sync check` 判定为异常（unmanaged 文件）；若存在未被任何 harness lock 记录的 Map，需将其移动或使用 `--force` 处理，而非直接删除（Illuminate 不删除非自身管理的文件）。
