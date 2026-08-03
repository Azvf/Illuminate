# Module README 模板

`30-modules/<module>/README.md` 是完整的人类正文 Owner，不是只包含索引的壳：

```markdown
# <Module>

> <一句话职责>

## 模块定位与边界

## 主流程摘要

## 参与组件

## 完整业务链路

## 状态、门禁与不变量

## 失败、重试与恢复

## 模块交接

## 日志与排障

## 已确认的业务事实

## 当前限制与待确认问题

## 深入阅读

- [组件文档](../../20-components/<component>/README.md)
- [平台差异](platforms/<platform>.md)
```

不要在 Markdown 中写 Claim ID、Evidence ID、Hash、测试记录或审计状态。对应机器信息放在模块 `verification/*.yaml`，通过 `doc_refs` 指向标题。
