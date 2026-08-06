# 知识存放与 Owner 规则

## 人类正文与机器治理分离

- `20-components/<component>.md`：组件/API 生命周期与实现边界。
- `30-modules/<module>.md`：模块级完整人类正文。
- `40-journeys/<journey>.md`：跨模块业务流程，只描述顺序、交接和决策。
- `70-metadata/`：身份、状态、Claim、Evidence、Gap、Test 和 source anchor。
- `README-HUMAN.md`：人类文档入口；`human-docs.json`：导出清单。

正文 Owner 不根据目录猜测。组件、模块和 Journey 必须由对应 Manifest 的 `document` 字段声明：

```yaml
id: example
document: 30-modules/example.md
```

## doc_refs

每个 Claim、Gap、Test 条目都应通过 YAML 的 `doc_refs` 指向正文 Owner，并使用 `docs/` 根相对路径：

```yaml
- id: CL-EXAMPLE-001
  doc_refs:
    - ref: 30-modules/example.md#主流程摘要
      role: primary
```

`doc_refs` 必须指向真实 Markdown 文件和存在的标题锚点。正文不直接承载 Claim ID、Evidence ID、Hash 或状态字段。

## Owner 处理规则

1. 先读取 Manifest 的 `document`，再更新已有正文。
2. 多份 Manifest 不得拥有同一 `document`。
3. 没有 Owner 时创建最小分类 Markdown 和对应 Manifest。
4. 修改正文后同步相关 YAML 的 `doc_refs`；修改 Claim/Gap/Test 后确认引用仍然有效。
5. 不为一条小规则创建孤立文件，也不把验证元数据复制到 Markdown。
