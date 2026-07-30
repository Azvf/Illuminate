---
name: archive-module-doc
description: Organize verified knowledge for one module into a compact, standard, or extended Framework documentation set. Use when a module already has accumulated knowledge that needs stable ownership, chapter structure, indexing, or document splitting. Do not analyze the whole project or invent missing chapters.
---

# Archive Module Documentation

本 Skill 将单一模块已经存在且经过验证的知识，整理为结构清晰的 Framework 文档。

本 Skill 不负责从零逆向整个模块，也不负责整理整个项目。

## 文档模式

根据模块的知识主题数量和链路复杂度选择模式。

### Compact（默认）

适用于单一职责、单一链路的小模块。

输出单文件：

```
docs/Framework/<Module>.md
```

内容：

```markdown
# 模块名称

## 职责与边界
## 入口
## 核心链路
## 关键状态
## 风险与维护
## 实现锚点
```

不要强行创建目录。

### Standard

适用于包含多个核心组件或两到三条稳定链路的模块。

输出：

```
docs/Framework/<Module>/
├── README.md
├── 01-模块全景.md
├── 02-核心组件与职责.md
├── 03-关键功能链路.md
└── 04-风险与维护.md
```

未验证或不存在的章节可以省略。

### Extended

适用于包含多个子系统、复杂状态、跨端契约或多条独立链路的模块。

在 Standard 基础上按实际主题增加章节。

禁止为了形成固定数量而创建空洞章节。

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

README 只负责：

1. 一句话定位
2. 模块路径
3. 章节索引
4. 推荐阅读路径
5. 关联模块
6. 文档维护状态

不要在 README 中重复各章节的完整结论。

## 工作流

### 第一步：确定单一模块边界

必须先确定：模块名称、源码根目录、现有 Framework owner、相关知识文档。

只允许处理一个模块。如果用户说"整理所有系统"，先选择一个模块。

### 第二步：收集已有知识

知识来源优先级：

1. 当前模块已有 Framework 文档
2. `record-knowledge` 产生的增量内容
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

### 第七步：生成 README 和章节文件

编号固定阅读顺序，不把编号当版本。新增章节时按序追加，不要重新编号全部文件。

### 第八步：校验链接与事实

至少检查：

- README 中所有链接存在
- 章节之间无循环复制
- 源码路径存在
- 不使用易失效行号
- 模块名和源码目录一致
- 没有把通用规范写进模块文档
- 没有把模块职责写进 Guidelines
- 未验证内容明确标识

## 通用知识与模块知识的边界

归档时要明确：

**应移到 Guidelines：** 跨模块适用的规则（目录规范、命名规则、日志格式、配置约定）

**应留在模块文档：** 仅对当前模块成立的职责、链路和边界

判断问题：**"这个规则换到另一个模块仍然成立吗？"**

- 成立 → `docs/Guidelines/`
- 只对当前模块成立 → `docs/Framework/<Module>/`

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
