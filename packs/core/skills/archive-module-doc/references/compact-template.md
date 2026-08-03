# Compact 模块模板

Compact 不再创建独立的 `docs/Framework/<Module>.md`。即使模块只有一条链路，也使用完整正文 Owner：

```text
30-modules/<module>/README.md
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

内容较少时可以省略不适用章节，但 README 仍然是人类可读的主文档。
