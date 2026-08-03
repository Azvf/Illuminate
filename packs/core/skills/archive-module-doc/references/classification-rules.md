# 模块文档分类规则

## 模块正文 Owner

所有模块级稳定职责、链路、边界和失败恢复统一归入：

```text
30-modules/<module>/README.md
```

README 是完整人类正文。不要把模块正文拆回旧式 `docs/Framework/<Module>.md` 或只负责索引的 README。

## 组件与流程边界

- 组件/API 生命周期和实现细节 → `20-components/`。
- 跨模块顺序、交接和决策 → `40-journeys/`。
- 模块内部的完整链路和状态 → `30-modules/<module>/README.md`。
- Android/iOS 等平台差异 → 模块目录下 `platforms/`。
- Claim、Evidence、Gap、Test 和 source anchor → `verification/*.yaml`。

## 判断问题

1. 这个事实换到另一个模块仍然成立吗？成立则进入 Guidelines owner。
2. 它描述组件 API 还是模块业务链路？前者进入 `20-components`，后者进入 `30-modules`。
3. 它描述多个模块的顺序吗？是则进入 `40-journeys`。
4. 它只是可信度、证据或测试元数据吗？是则只进入 Verification YAML。
