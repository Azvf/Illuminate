# Standard 模块模板

Standard 只有一个正文 Owner：

```text
30-modules/<module>.md
```

对应 Manifest：

```text
70-metadata/modules/<id>/module.yaml
```

Manifest 的 `document` 必须指向该 Markdown。正文承载完整模块链路；平台差异或独立专题归入相应分类目录，不在 `30-modules/<module>/` 下创建子树。

推荐章节：

```markdown
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
```

验证信息留在 `70-metadata/modules/<id>/verification/`，通过 root-relative `doc_refs` 链接正文。
