# 模块文档分类规则

## 模块正文 Owner

模块级稳定职责、链路、边界和失败恢复统一归入：

```text
30-modules/<module>.md
```

实际 Owner 由 `70-metadata/modules/<id>/module.yaml` 的 `document` 字段声明。不要按模块目录推导 Owner，也不要创建旧式 `docs/Framework/<Module>.md`。

## 组件与流程边界

- 组件/API 生命周期和实现细节 → `20-components/<component>.md`。
- 跨模块顺序、交接和决策 → `40-journeys/<journey>.md`。
- 模块内部完整链路和状态 → `30-modules/<module>.md`。
- Claim、Evidence、Gap、Test 和 source anchor → `70-metadata/<kind>/<id>/verification/`。

## 判断问题

1. 这个事实换到另一个模块仍然成立吗？成立则不要写入当前模块正文。
2. 它描述组件 API 还是模块业务链路？前者进入 `20-components`，后者进入 `30-modules`。
3. 它描述多个模块的顺序吗？是则进入 `40-journeys`。
4. 它只是可信度、证据或测试元数据吗？是则只进入 `70-metadata`。
