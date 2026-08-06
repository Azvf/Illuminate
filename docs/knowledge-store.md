# 知识库备份与恢复（Knowledge Store）

本地备份与恢复工具。项目采用 `flat-classified` 布局时，可在仓库根放一个可选的 `knowledge-manifest.json`，其 roots 与 patterns 相对于 `docs/`。

`70-metadata` 把 Manifest 身份与校验 YAML 与人类可读 Markdown 分离存放。Git 负责历史、分支与协作；Store 只负责备份 / 差异 / 冲突 / 恢复。

## knowledge-manifest.json 示例

```json
{
  "roots": ["20-components", "30-modules", "40-journeys", "70-metadata", "README-HUMAN.md", "human-docs.json"],
  "include": ["**/*"],
  "exclude": ["80-evidence/**", "90-generated/**", "99-archive/**", "dist/**"]
}
```

## pull / status / push 语义

```bash
# 拉取项目知识到中央库（~/.illuminate/knowledge），保留三方基线以处理冲突与删除
illuminate knowledge pull --repo /path/to/project --manifest /path/to/project/knowledge-manifest.json

# 对比项目知识与中央库
illuminate knowledge status --repo /path/to/project --manifest /path/to/project/knowledge-manifest.json

# 把中央库文档安全地推回项目（自上次基线以来被改过的文件默认拒绝覆盖，需 --force）
illuminate knowledge push --repo /path/to/project --manifest /path/to/project/knowledge-manifest.json
```

- **`knowledge pull`**：把项目知识文件拉入中央库（默认 `~/.illuminate/knowledge`）。保留三方基线以处理冲突与删除。输出包含 New / Modified / Deleted / Conflicts / Pulled 计数。
- **`knowledge status`**：对比项目知识与中央库，报告 Synced / New / Modified / Store Modified / Deleted / Conflicts。
- **`knowledge push`**：把中央库文档推回项目（恢复）。自上次基线以来被改过的文件默认拒绝覆盖，需 `--force` 授权。

`--repo` 指定目标仓库；`--store <dir>` 可覆盖中央库目录（默认 `~/.illuminate/knowledge`）；`--manifest <json>` 指定 manifest 路径。
