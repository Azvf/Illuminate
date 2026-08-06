---
name: archive-module-doc
description: Organize verified knowledge for one module into a compact, standard, or extended module document. Use when a module already has accumulated knowledge that needs stable ownership, chapter structure, or indexing. Do not analyze the whole project or invent missing chapters.
---

# Archive Module Documentation

本 Skill 将单一模块已经存在且经过验证的知识，整理为结构清晰的人类正文。它不负责从零逆向整个模块，也不负责整理整个项目。

## 正文 Owner

`flat-classified` 布局中，模块正文是扁平 Markdown：

```text
30-modules/<module>.md
```

实际文件必须由 `70-metadata/modules/<id>/module.yaml` 的 `document` 字段声明；同一 Manifest 可通过 `documents` 声明平台补充正文。Claim、Gap、Test 和 Evidence 位于同一实体的 `70-metadata/modules/<id>/verification/`，通过带 `role: primary|context` 的 root-relative `doc_refs` 指向正文标题。

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

每次只处理一个模块，必须明确模块名称、源码根目录、现有正文 Owner 和本次允许归档的知识来源。

## 工作流

### 1. 确定单一模块边界

只允许处理一个模块。如果用户说“整理所有系统”，先选择一个模块。

### 2. 收集已有知识

知识来源优先级：

1. `module.yaml.document` 指向的当前正文
2. `70-metadata/modules/<id>/verification/` 中的验证数据
3. `record-knowledge` 产生的正文增量
4. Issues / Development 中已验证结论
5. 代码、配置、日志和测试，仅用于核对事实

归档 Skill 不是新的全模块逆向分析，不能因为章节缺失就主动读取整个源码树补齐。

### 3. 建立知识清单

将已有内容映射成条目并标记 `verified`、`partially-verified`、`stale`、`duplicate` 或 `unresolved`。只有 `verified` 和清楚标记的 `partially-verified` 可以进入正式正文。

### 4. 选择文档模式

| 条件 | 模式 |
|------|------|
| 知识主题 ≤ 4 且主链路 ≤ 1 | Compact |
| 知识主题 5～10 或独立链路 2～3 | Standard |
| 知识主题 > 10 或包含多子系统/跨端契约 | Extended |

这是指导性判断，不是硬性数学标准。

### 5. 生成归档计划

修改前明确新建、移动、删除和不处理的内容。不要同时迁移其他模块。

### 6. 建立唯一 Owner

同一事实只能有一个主要 Owner。其他正文只写 root-relative 链接，不复制完整说明。新增或移动正文时同步 `module.yaml.document`。

### 7. 更新模块正文

优先更新 Manifest 指向的 `30-modules/<module>.md`。平台差异、组件细节或独立专题应归入各自分类，不在模块目录下重新创建子树。

### 8. 校验链接与事实

至少检查正文链接、源码路径、模块名与源码目录、章节重复、验证条目的 `doc_refs`、标题锚点和人类正文中的机器 Meta。最后运行 `docs lint-human` 与 `docs lint-knowledge`。

## 分类边界

- 组件/API 生命周期和实现细节 → `20-components/`。
- 跨模块顺序、交接和决策 → `40-journeys/`。
- 模块内部完整链路和状态 → `30-modules/`。
- Claim、Evidence、Gap、Test 和 source anchor → `70-metadata/`。

判断问题：这个事实换到另一个模块仍然成立吗？成立时不要写入当前模块正文；只对当前模块成立时才归入 `30-modules/<module>.md`。

## 与其他 Skill 的关系

`record-knowledge` 记录日常开发中确认的最小事实；`archive-module-doc` 负责一个模块的结构化收口；`tidy-doc` 负责跨模块治理。发现跨模块问题时只记录并推荐 `tidy-doc`，不要扩大本次归档范围。
