# 知识存放与 Owner 规则

## 人类正文与机器治理分离

- `20-components/`：组件/API 生命周期与实现边界。
- `30-modules/`：模块级完整人类主文档，`<module>/README.md` 是正文 Owner。
- `40-journeys/`：跨模块业务流程，只描述顺序、交接和决策，并链接到模块 README。
- `verification/`：Claim、Evidence、Gap、Test 和 source anchor 等机器治理 YAML，不写入正文。
- `README-HUMAN.md`：人类文档入口；`human-docs.json`：导出清单。

## 通用知识

跨模块适用、表达“默认怎么做”的规则，应写入项目约定的 Guidelines owner；如果项目采用新的知识库布局，则写入明确配置的治理根目录，不要擅自创建第二套 Guidelines。

## 模块级知识

模块稳定职责、完整链路、边界、失败恢复和排障信息，写入：

```text
30-modules/<module>/README.md
```

README 本身是完整人类正文，不再拆成只负责索引的壳。平台差异可以放在模块目录下的 `platforms/` 文档中。

## 跨模块流程

完整业务顺序只由 `40-journeys/` 的 Guide 负责。Guide 可以链接模块 README，但不要复制模块内部的完整结论。

## doc_refs

每个 Claim、Gap、Test 条目都应通过 YAML 的 `doc_refs` 指向正文 Owner：

```yaml
- id: CL-EXAMPLE-001
  doc_refs:
    - ../../30-modules/example/README.md#主流程摘要
```

`doc_refs` 必须指向真实 Markdown 文件和存在的标题锚点。正文不直接承载 Claim ID、Evidence ID、Hash 或状态字段。

## Owner 处理规则

1. 已有正文 Owner → 更新现有文档。
2. 多份重复 Owner → 选择一个主 Owner，其他位置只保留链接。
3. 没有 Owner → 创建最小的 `30-modules/<module>/README.md` 或对应 Guide。
4. 修改正文后同步对应 YAML 的 `doc_refs`；修改 Claim/Gap/Test 后确认引用仍然有效。
5. 不为一条小规则创建孤立文件，也不把验证元数据复制到 Markdown。
