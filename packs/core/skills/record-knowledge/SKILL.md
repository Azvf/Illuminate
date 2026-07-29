---
name: record-knowledge
description: Incrementally record small, verified project knowledge discovered during development. Use when a task confirms a reusable convention, path rule, stable module responsibility, functional chain, boundary, or recurring failure mode. Update the smallest existing owner document; do not analyze or document the whole project.
---

# Record Knowledge

本 Skill 用于记录本次任务中新确认的最小可复用知识。

它不负责扫描或总结整个项目。

## 知识层级

### 第一层：通用知识

回答跨模块、跨任务长期成立的问题，例如：

- 路径与目录规范
- 命名规则
- 配置优先级
- 日志与测试约定
- 通用安全边界

存放位置：`docs/Guidelines/` 中已有的 owner 文档。

### 第二层：模块级知识

回答单一模块的稳定职责和功能链路，例如：

- 模块做什么
- 从哪里进入
- 经过哪些关键组件
- 关键边界
- 已验证失败模式
- 如何验证

存放位置：`docs/Framework/` 中对应模块文档。

## 触发方式

### 显式触发（推荐）

```
$record-knowledge 记录刚确认的路径规范
$record-knowledge 把这次确认的后台下载链路补充到模块文档
$record-knowledge 记录 Manifest 配置来源和覆盖关系
```

### 其他 Skill 推荐触发

当以下 Skill 发现架构边界、核心链路或根因变化时，可能推荐后续调用：

- `layer-debug` → 根因已验证 → 建议记录失败模式
- `impact-analysis` → 模块边界变化 → 建议更新模块职责

## 值得记录的门槛

满足**至少一项**才记录：

- 后续任务可能再次用到
- 不记录容易重复排查
- 是隐含但稳定的项目约束
- 代码本身不容易直接看出
- 涉及跨文件或跨组件链路
- 修正了现有文档中的错误认知
- 是模块稳定职责或边界
- 是已验证的高频失败模式

不应记录：

- 临时调试步骤
- 一次性的文件行号
- 当前分支中的中间实现
- 未验证猜测
- 可直接从一个简单函数看出的细节
- 某次任务的流水账
- 完整源码解释
- 尚未确定的未来设计

## 工作流

### 第一步：限定本次知识范围

先回答：本次要记录的最小事实是什么？

可能只是：一个路径规则、一个命名规则、一个配置覆盖顺序、一个模块入口、一个关键调用链、一个稳定失败模式。

禁止自动扩大为：顺便扫描整个仓库、顺便补齐所有模块、顺便重写全部文档。

### 第二步：判断知识层级

| 特征 | 层级 | 目标目录 |
|------|------|----------|
| 跨模块适用，表达"默认怎么做" | 通用知识 | `docs/Guidelines/` |
| 属于一个明确模块，描述职责/边界/链路 | 模块级知识 | `docs/Framework/` |

### 第三步：寻找已有 owner

按顺序检查：

1. 已有模块 Framework 文档
2. 已有对应 Guideline
3. 文档索引中指向的 owner
4. 相关 Skill 指定的文档入口

处理规则：

- 已有 owner → 更新现有文档
- 有多份重复 owner → 选择一个主 owner，消除新增重复
- 没有 owner → 创建最小文档

### 第四步：只写已验证事实

每条信息应能追溯到至少一种证据：代码、配置文件、调用关系、运行日志、测试结果、构建脚本、现有稳定文档。

在文档末尾保留简短实现锚点，不记录易失效的行号。

### 第五步：最小化更新

默认只修改必要章节。例如只发现了一个路径规范，就只添加：

```markdown
## 平台配置路径
```

不要顺便统一全文语气、重排所有标题或重写背景介绍。

### 第六步：同步最小索引

只有以下情况才更新索引：

- 新建了一个长期文档
- 文档 owner 发生迁移
- 文件路径变化
- 新模块文档需要被发现

只更新已有文档中的一个小章节时，不需要修改索引。

## 与 tidy-doc 的边界

```
record-knowledge
    │
    ├── 正常情况：只更新目标文档，结束
    │
    └── 发现文档体系混乱
             ↓
         推荐 tidy-doc
```

发现文档体系混乱（多份重复文档、owner 不清晰、索引失效、Guidelines 与 Framework 混杂）时可考虑调用 `tidy-doc`。

`tidy-doc` 负责多文档整理、消除重复、修复旧路径、统一 owner。但不要每次 `record-knowledge` 后自动执行。
