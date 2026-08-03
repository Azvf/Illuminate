# Extended 模块模板

Extended 适用于多子系统、复杂状态、跨端契约或多条独立链路的模块，但仍保持单一人类正文 Owner：

```text
30-modules/<module>/README.md
```

README 描述完整模块全景和各链路摘要；只有平台实现、组件细节或独立专题确实需要时才新增子文档：

```text
30-modules/<module>/
├── README.md
├── platforms/
│   ├── android.md
│   └── ios.md
└── topics/
    └── <topic>.md
```

每个新增文档必须由 README 链接，不能形成未连接的文档孤岛。Claim、Gap、Test 和 Evidence 仍由 `verification/*.yaml` 管理，正文只保留对人有价值的业务事实。
