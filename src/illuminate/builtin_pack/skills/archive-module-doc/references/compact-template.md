# Compact 模块模板

Compact 使用扁平正文 Owner，不创建独立的旧式 Framework 文档：

```text
30-modules/<module>.md
70-metadata/modules/<id>/module.yaml
```

至少包含：

```markdown
# 模块名称

> 一句话职责。

## 模块定位与边界
## 主流程摘要
## 失败、重试与恢复
## 当前限制与待确认问题
```

内容较少时可以省略不适用章节，但 Markdown 仍然是人类可读的主文档，Manifest 的 `document` 必须指向它。
