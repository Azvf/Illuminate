---
name: record-knowledge
description: Incrementally record small, verified project knowledge discovered during development. Use when a task confirms a reusable convention, path rule, stable module responsibility, functional chain, boundary, or recurring failure mode. Update the smallest existing owner document; do not analyze or document the whole project.
---

# Record Knowledge

本 Skill 用于记录本次任务中新确认的最小可复用知识，不负责扫描或总结整个项目。

## 文档布局

项目采用 `flat-classified` 时：

- 组件/API 生命周期与实现边界 → `20-components/<component>.md`
- 单模块职责、完整链路、边界和失败恢复 → `30-modules/<module>.md`
- 跨模块顺序、交接和决策 → `40-journeys/<journey>.md`
- 身份、状态、Claim、Gap、Test、Evidence 和 source anchors → `70-metadata/`

组件和模块正文 Owner 由对应 Manifest 的 `document` 字段声明；Journey 由流程 Markdown 自身作为 Owner，例如模块文档可写为：

```yaml
id: hot-update
document: 30-modules/hot-update.md
```

`doc_refs` 统一使用相对于 `docs/` 根目录的路径，例如：

```yaml
doc_refs:
  - ref: 30-modules/hot-update.md#主流程摘要
    role: primary
```

正文不写机器 ID、状态、Hash 或审计结果。

## 触发方式

```text
$record-knowledge 记录刚确认的路径规范
$record-knowledge 把这次确认的后台下载链路补充到模块文档
$record-knowledge 记录 Manifest 配置来源和覆盖关系
```

## 值得记录的门槛

满足至少一项才记录：后续任务可能再次用到、不记录容易重复排查、是隐含但稳定的约束、代码本身不容易直接看出、涉及跨文件或跨组件链路、修正了现有文档中的错误认知、是模块稳定职责或已验证的高频失败模式。

不应记录：临时调试步骤、一次性的行号、当前分支中间实现、未验证猜测、简单函数即可看出的细节、任务流水账、完整源码解释或未来设计。

## 工作流

### 1. 限定最小事实

先明确本次要记录的一个路径规则、命名规则、配置顺序、模块入口、关键调用链或稳定失败模式。禁止顺便扫描整个仓库、补齐所有模块或重写全部文档。

### 2. 判断知识层级

| 特征 | 层级 | 目标 Owner |
|------|------|----------|
| 组件/API 生命周期和实现边界 | 组件知识 | `20-components/<component>.md` |
| 单一模块职责、边界和链路 | 模块知识 | `30-modules/<module>.md` |
| 跨模块完整顺序、交接和决策 | 业务流程 | `40-journeys/<journey>.md` |
| 可信度、证据、状态和测试 | 机器治理 | `70-metadata/` 下对应实体目录 |

### 3. 寻找已有 Owner

先检查对应分类目录、`human-docs.json` 和 `70-metadata` 中的 Manifest。已存在 Owner 就更新它；多个 Owner 只保留一个；没有 Owner 时创建最小 Markdown 和对应 Manifest。不要按目录名猜测 Owner。

### 4. 只写已验证事实

每条信息应能追溯到代码、配置、调用关系、日志、测试、构建脚本或现有稳定文档。YAML 条目通过带 `role: primary|context` 的 root-relative `doc_refs` 指向正文标题；每条 Claim、Gap、Test 恰好一个 `primary`，不记录易失效行号。

### 5. 最小化更新

默认只修改必要章节。只发现一个路径规范时，只增加对应小节；不要顺便统一全文语气、重排标题或重写背景介绍。

### 6. 同步 Manifest 和引用

新建或移动正文时更新 `document`；修改正文后检查相关 YAML 的 `doc_refs`；修改 Claim/Gap/Test 后确认文件和标题锚点仍存在。最后运行 `illuminate docs lint-human` 和 `illuminate docs lint-knowledge`。

## 与其他 Skill 的边界

- `record-knowledge`：维护一个最小事实和它的唯一正文 Owner。
- `archive-module-doc`：把一个模块积累的事实整理成结构化模块文档。
- `tidy-doc`：治理跨模块重复、过期路径、孤儿正文和索引问题。

不要在每次记录后自动执行其他整理 Skill。
