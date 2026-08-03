# Document Hierarchy

项目文档由人类正文层和机器治理层组成。具体项目可以通过 `knowledge-manifest.json` 调整根目录，但不得让同一事实拥有多个正文 Owner。

## 人类正文层

| 层级 | 目录 | 职责 |
|------|------|------|
| Components | `docs/20-components/` | 组件、API 生命周期与实现边界 |
| Modules | `docs/30-modules/` | 模块完整职责、链路、状态、失败恢复与排障；`<module>/README.md` 是正文 Owner |
| Journeys | `docs/40-journeys/` | 跨模块业务顺序、交接、决策和主要失败分支 |
| Guidelines | 项目声明的 Guidelines root | 跨模块默认做法、门禁和接入步骤 |
| Research | `docs/Research/` | SDK/API 逆向记录与平台行为对齐 |
| Issues | `docs/Issues/` | 平台适配问题与偶现失败记录 |
| Development | `docs/Development/Active/` | 推进中的主题 |
| Development | `docs/Development/Archived/` | 已完成主题的归档 |

`README-HUMAN.md` 是人类文档入口，`human-docs.json` 是导出清单；它们属于项目文档配置，不是机器 Claim 数据。

## 机器治理层

模块目录下的 `verification/` 保存：

- `claims.yaml`
- `evidence.yaml`
- `gaps.yaml`
- `tests.yaml`
- `source-anchors.yaml`

Claim、Gap、Test 等条目通过 `doc_refs` 指向正文文件和标题锚点。机器 ID、证据状态、Hash、测试记录和版本绑定信息不复制到人类 Markdown。

## Owner 规则

- 模块稳定职责、完整链路和边界只保留一个 `30-modules/<module>/README.md` Owner。
- 跨模块完整顺序只由 `40-journeys/` Guide Owner 负责；Guide 链接模块 README，不复制模块内部结论。
- Guidelines 不重复定义模块事实，只补跨模块默认做法、接入步骤和验证门禁。
- `20-components/` 只负责组件/API 细节；模块文档通过链接引用，不复制完整组件说明。
- Development 不承担长期基线；主题结束后默认先迁到 `Archived`。
- Verification YAML 是 Claim/Evidence/Gap/Test 的机器 Owner，不是人类正文 Owner。

## 核心规则

- 人类 Markdown 必须可独立阅读，不包含机器 Meta、Hash 或审计状态。
- 不在多个正文层重复维护同一事实；重复内容应改为链接。
- 修改正文后检查相关 YAML 的 `doc_refs`；修改 YAML 后检查文件和标题锚点仍然存在。
- `docs export-human` 只按 `human-docs.json` 复制文件，不解析或改写正文。
- `docs lint-human` 检查正文、链接和结构；`docs lint-knowledge` 检查 YAML 的 ID 与 `doc_refs`。
- 如果代码现实与 guideline 不一致，先指出不一致，再更新 guideline 或代码。
