# Standard 模块模板

Standard 仍然只有一个正文 Owner：

```text
30-modules/<module>/README.md
```

README 承载完整模块链路；只有平台差异或确实独立的专题才创建子文档：

```text
30-modules/<module>/
├── README.md
└── platforms/
    ├── android.md
    └── ios.md
```

README 推荐章节：

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

验证信息留在 `verification/*.yaml`，通过 `doc_refs` 链接正文。
