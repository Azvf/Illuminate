---
name: archive-module-doc
description: Organize verified knowledge for one module into a compact, standard, or extended Framework documentation set. Use when a module already has accumulated knowledge that needs stable ownership, chapter structure, indexing, or document splitting. Do not analyze the whole project or invent missing chapters.
---

# Archive Module Documentation

本 Skill 将单一模块已经存在且经过验证的知识，整理为结构清晰的 Framework 文档。

本 Skill 不负责从零逆向整个模块，也不负责整理整个项目。

## 文档模式

当前默认模型只有一个人类正文 Owner：

```text
30-modules/<module>/README.md
```

README 必须承载完整、连续的人类可读模块文档，而不是只负责索引。根据内容复杂度可以在同一模块目录下增加平台或专题 Markdown，但新增文件必须由 README 链接并有明确 Owner。

建议章节：

```markdown
# 模块名称

> 一句话职责。

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

未验证或不存在的内容可以省略；禁止为了形成固定数量创建空洞章节。

## 输入范围

每次只处理一个模块。

必须明确：

- 模块名称
- 源码根目录
- 现有 owner 文档
- 本次允许归档的知识来源

## 章节分类

### 必选章节

每个模块至少应有：

- **模块全景**：职责、边界、位置、依赖关系
- **核心链路**：入口、关键组件、状态流转、输出
- **风险与维护**：隐含约束、联动检查项、历史兼容分支

### 可选章节

只有确实存在时才创建：

- 数据模型 / 网络同步 / 生命周期 / 缓存
- 跨端契约 / 编辑器工具 / 配置体系
- 性能模型 / 与其他模块的闭环
- 故障模式 / 测试与验证

## README 的职责

README 是模块完整人类文档的唯一正文 Owner，至少包含定位、边界、主流程、失败恢复和当前限制。它可以链接平台文档、组件文档和验证 YAML，但不复制 Claim ID、Evidence ID、Hash 或测试记录。

跨模块完整顺序由 `40-journeys/` Owner 负责；Guide 链接回本 README，不在 Guide 重复本模块完整结论。

## 工作流

### 第一步：确定单一模块边界

必须先确定：模块名称、源码根目录、现有 Framework owner、相关知识文档。

只允许处理一个模块。如果用户说"整理所有系统"，先选择一个模块。

### 第二步：收集已有知识

知识来源优先级：

1. 当前模块已有 `30-modules/<module>/README.md`
2. `record-knowledge` 产生的正文增量与 `verification/*.yaml`
3. Issues / Development 中已验证结论
4. 代码和配置，仅用于核对
5. 日志与测试，仅用于验证

归档 Skill 不是新的全模块逆向分析。可以核对事实，但不能因为某章节缺失就主动读取整个源码树补齐。

### 第三步：建立知识清单

将已有内容映射成条目，每条知识标记状态：

- `verified` — 已验证
- `partially-verified` — 部分验证
- `stale` — 已过期
- `duplicate` — 重复
- `unresolved` — 未解决

只有 `verified` 和清楚标记的 `partially-verified` 可以进入正式文档。

### 第四步：选择文档模式

| 条件 | 模式 |
|------|------|
| 知识主题 ≤ 4 且主链路 ≤ 1 | Compact |
| 知识主题 5～10 或独立链路 2～3 | Standard |
| 知识主题 > 10 或包含多子系统/跨端契约 | Extended |

这是指导性判断，不是硬性数学标准。

### 第五步：生成归档计划

在修改文件前先给出计划，明确：

- 新建什么
- 移动什么
- 删除什么
- 哪些内容不处理

### 第六步：建立唯一 owner

同一事实只能有一个主要 owner。其他章节只写链接，不要重复复制说明。

### 第七步：更新完整 README 和必要专题文件

优先更新 `30-modules/<module>/README.md`。只有平台差异或独立专题确实需要时才新增子文档，并从 README 建立稳定链接。不要为了归档而拆分已经可读的正文。

### 第八步：校验链接与事实

至少检查：

- README 中所有链接存在
- 章节之间无循环复制
- 源码路径存在
- 不使用易失效行号
- 模块名和源码目录一致
- 没有把通用规范写进模块文档
- 没有把模块职责写进 Guidelines
- Claim、Gap、Test 均有 `doc_refs` 指向正文标题
- 未验证内容明确标识
- Markdown 正文不包含机器 Meta ID、Hash 或审计状态

## 通用知识与模块知识的边界

归档时要明确：

**应移到 Guidelines：** 跨模块适用的规则（目录规范、命名规则、日志格式、配置约定）

**应留在模块文档：** 仅对当前模块成立的职责、链路和边界。新布局中使用 `30-modules/<module>/README.md` 作为 Owner。

判断问题：**"这个规则换到另一个模块仍然成立吗？"**

- 成立 → `docs/Guidelines/`
- 只对当前模块成立 → `30-modules/<module>/README.md`

## 与其他 Skill 的关系

```
record-knowledge
    ↓
日常开发中记录最小稳定事实

archive-module-doc
    ↓
当模块知识达到一定规模后，整理成结构化文档集

tidy-doc
    ↓
跨模块、跨目录治理重复、过期、索引和 owner 问题
```

- 小知识增量由 `record-knowledge` 维护
- 跨模块文档治理由 `tidy-doc` 处理
- 本 Skill 只负责一个模块内部的结构归档

如果归档过程中发现跨模块问题，只记录并推荐 `tidy-doc`，不要顺手扩大处理范围。
