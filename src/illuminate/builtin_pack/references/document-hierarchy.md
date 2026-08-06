# Document Hierarchy

项目文档由人类正文层和机器治理层组成。`flat-classified` 布局下，人类正文按分类扁平存放，正文 Owner 由 `70-metadata` 中的 Manifest 明确声明。

## Layout Profile

项目在 `human-docs.json` 中声明：

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
  "doc_refs": "root-relative"
}
```

`20/30/40` 目录只存人类 Markdown；不按模块再创建子目录。所有 `doc_refs` 都相对于 `docs/` 根目录，例如 `30-modules/hot-update.md#安装判断四路径`。

## 人类正文层

| 层级 | 目录 | 职责 |
|------|------|------|
| Components | `docs/20-components/*.md` | 组件、API 生命周期与实现边界 |
| Modules | `docs/30-modules/*.md` | 模块完整职责、链路、状态、失败恢复与排障 |
| Journeys | `docs/40-journeys/*.md` | 跨模块业务顺序、交接、决策和主要失败分支 |
| 入口 | `docs/README-HUMAN.md` | 人类文档入口 |

每份组件和模块正文必须由对应 Manifest 的 `document` 字段拥有：

```yaml
id: hot-update
document: 30-modules/hot-update.md
```

Manifest 文件位于 `docs/70-metadata/components/<id>/component.yaml` 或 `modules/<id>/module.yaml`。`document` 必须是 `docs/` 根相对路径、指向真实 Markdown，并与 Manifest 类型对应的正文分类一致。Journey 是流程正文 Owner，不要求额外的 `journey.yaml`。

## 机器治理层

`docs/70-metadata/` 保存身份、状态和验证数据：

- `components/<id>/component.yaml`
- `modules/<id>/module.yaml`
- 各实体目录下的 `verification/claims.yaml`、`gaps.yaml`、`tests.yaml`、`evidence.yaml` 和 source anchors

Claim、Gap、Test 等条目通过 root-relative `doc_refs` 指向正文文件和标题锚点；每条记录必须恰好一个 `primary`，可有零到多个 `context`。模块主 Manifest 的 `document` 是主正文，`documents` 是同一模块拥有的平台补充正文。稳定显式锚点使用 `<a id="[a-z0-9]+(?:-[a-z0-9]+)*"></a>`，且知识库内唯一。机器 ID、证据状态、Hash、测试记录和版本绑定信息不复制到人类 Markdown。

## Owner 规则

- 每个组件和模块正文只由一个 Manifest 的 `document` 字段拥有。
- 不允许两个 Manifest 拥有同一 `document`。
- `20-components/` 和 `30-modules/` 下未被 Manifest 拥有的 Markdown 是孤儿正文，必须补充 Owner 或删除。
- `40-journeys/` 下的流程 Markdown 由流程文件自身作为 Owner。
- 跨模块完整顺序只由 `40-journeys/*.md` Owner 负责；Journey 链接模块文档，不复制模块内部结论。
- Verification YAML 是机器治理数据的 Owner，不是人类正文 Owner。

## 核心规则

- 人类 Markdown 必须可独立阅读，不包含机器 Meta、Hash 或审计状态。
- 不在多个正文层重复维护同一事实；重复内容应改为链接。
- 修改正文后检查相关 YAML 的 `doc_refs`；修改 YAML 后检查文件和标题锚点仍然存在。
- `docs export-human` 只按 `human-docs.json` 复制文件，不解析或改写正文。
- `docs lint-human` 检查正文、链接和结构；`docs lint-knowledge` 检查 Manifest Owner、YAML ID 与 root-relative `doc_refs`。
- `knowledge-manifest.json` 可以把 `70-metadata` 与需要备份的正文根加入 Knowledge Store；Git 仍负责历史和协作。
