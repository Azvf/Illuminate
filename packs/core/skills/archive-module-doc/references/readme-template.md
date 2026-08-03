# 模块正文模板

`30-modules/<module>.md` 是完整的人类正文 Owner；对应 `70-metadata/modules/<id>/module.yaml` 必须声明：

```yaml
id: <module>
document: 30-modules/<module>.md
```

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

- [组件文档](20-components/<component>.md)
- [流程文档](40-journeys/<journey>.md)
```

不要在 Markdown 中写 Claim ID、Evidence ID、Hash、测试记录或审计状态。对应机器信息放在 `70-metadata/modules/<id>/verification/`，通过 root-relative `doc_refs` 指向标题。
