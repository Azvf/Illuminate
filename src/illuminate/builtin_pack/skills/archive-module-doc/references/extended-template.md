# Extended 模块模板

Extended 适用于多子系统、复杂状态、跨端契约或多条独立链路，但仍保持单一人类正文 Owner：

```text
30-modules/<module>.md
70-metadata/modules/<id>/module.yaml
```

模块 Markdown 描述完整模块全景和各链路摘要。平台实现、组件细节或独立专题放入 `20-components/` 或其他分类目录，并由正文建立稳定链接；不要在 `30-modules/` 下恢复模块子目录。

每个新增人类文档都必须由对应 Manifest 的 `document` 字段拥有，不能形成未连接的文档孤岛。Claim、Gap、Test 和 Evidence 由 `70-metadata/modules/<id>/verification/` 管理，正文只保留对人有价值的业务事实。
