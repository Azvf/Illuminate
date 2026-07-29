# Document Hierarchy

文档分层规则与职责划分。

## 文档分级

| 级别 | 目录 | 职责 |
|------|------|------|
| Framework | `docs/Framework/` | 稳定事实与共享语义的 SSOT |
| Guidelines | `docs/Guidelines/` | 默认做法、门禁和接入步骤 |
| Research | `docs/Research/` | SDK/API 逆向记录、平台行为对齐 |
| Issues | `docs/Issues/` | 平台适配问题、偶现失败记录 |
| Development | `docs/Development/Active/` | 推进中的主题 |
| Development | `docs/Development/Archived/` | 已完成主题的归档 |

## Owner 规则

- 架构事实、稳定职责、共享协议、框架语义，只保留一个 `Framework` owner
- `Guideline` 不重复定义框架语义，只补默认做法、接入步骤、删旧要求、验证门禁
- `Development` 不承担长期基线；主题结束后默认先迁到 `Archived`
- 只有用户明确要求时，才将 `Development/Archived` 内容迁移到 `Framework`

## 核心规则

- 不在 Framework 和 Guidelines 两边重复维护同一套语义
- 如果代码现实与 guideline 不一致，先指出不一致，再更新 guideline 或代码
- 修改文件时避免一次性大批量 edit；优先按单文件或少量相关文件分批提交补丁
- 如果改动改变了后续默认做法，同步更新对应 guideline、skill 或索引文档

## 日志规则

日志输出必须使用仓库当前的日志框架，禁止使用 `Console.WriteLine`、`print`、`Log.d` 等临时调试输出作为正式日志。
