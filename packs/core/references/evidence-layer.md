# Evidence Layer

Illuminate 的 Verification Layer —— 用确定性工具测量代码变更，替代 LLM 自审。

## 设计哲学

```
LLM 负责创造
Tools 负责测量
LLM 根据测量结果修正
```

而不是：

```
LLM 创造
LLM 评价自己创造得好不好
```

后者必然退化为自我辩护。

## 三层模型

| 层级 | 职责 | 执行者 | 示例 |
|------|------|--------|------|
| Layer 1 | 确定性事实 | Tools (Evidence 脚本) | LOC delta、file count、新增 class/interface、import 变化 |
| Layer 2 | 半确定性结构信号 | Tools 检测 + LLM 判定 | catch 链深度、`??` 链、命名模式匹配 |
| Layer 3 | 语义判断 | LLM (基于 Layer 1+2 证据) | 抽象是否必要？注释是在 narrating 还是 explaining why？ |

**Evidence Layer 覆盖 Layer 1 和 Layer 2。Layer 3 仍由 LLM 负责，但必须引用 Evidence Report 中的事实作为依据。**

## 设计原则

- **Evidence 而非 Score**：输出只包含事实，不包含分数或风险评估。避免 Goodhart's law。
- **确定性**：同一输入始终产生同一输出，不依赖 LLM 判断。
- **零依赖**：仅使用 Python 标准库 + git。

## 配置层级

Evidence 工具按以下顺序加载配置，后者合并到前者之上：

| 顺序 | 来源 | 角色 |
|------|------|------|
| 1 | 代码内 `_DEFAULT_CONFIG` | 兜底默认 |
| 2 | Pack 自带 `patterns_config.json` | 工具默认配置 |
| 3 | 目标项目 `.illuminate/evidence/patterns_overlay.json` | 用户自定义 |

**合并语义**：列表追加并去重（默认在前，overlay 追加在后）；字典递归合并；标量覆盖；`null` 表示移除某项（opt-out）。

## 使用方法

```bash
illuminate evidence audit --repo .
```

输出默认写入 `<repo>/.illuminate/reports/evidence.json` + 人类可读摘要（stderr）。

报告中包含 Pack 版本和 lock hash，确保每份 Evidence 都能追溯到具体 Pack 版本。

## 覆盖的审计项

| 审计项 | 覆盖层 | Provider |
|--------|--------|----------|
| 新增抽象 (Factory/Adapter/Wrapper/Registry) | Layer 1 | patterns_provider |
| 新增 feature flag | Layer 1 | patterns_provider |
| 新增 fallback 路径 | Layer 1-2 | patterns_provider |
| 删除的代码行数 | Layer 1 | diff_provider |
| 注释复述代码实现语义 | Layer 3 | LLM only (无法脚本化) |

## Evidence Diversity

比 100% test coverage 更重要的目标是 Evidence Diversity——一次修改由多种独立证据类型支撑，而非由大量同质测试覆盖。

| 证据类型 | 当前覆盖 | 提供者 |
|---------|---------|--------|
| 结构复杂度（diff / patterns / imports） | 是 | `illuminate evidence audit` |
| 行为风险（缺失用例、边界、失败路径） | 是 | `behavior-verification` skill（Layer 3） |
| 行为正确性（unit / integration test 结果） | 否 | 按需，需可执行测试 |
| 变异测试 | 否 | 按需，语言相关，核心逻辑触发 |
| 属性测试 | 否 | 按需，parser / serializer / math 触发 |
| 静态分析（clang-tidy / ruff / mypy） | 否 | 按需，语言相关 |

扩展原则不变：按需添加，不预先实现。新增证据类型必须证明它覆盖了现有类型无法覆盖的盲区。

## Baseline 策略

使用 `git diff HEAD`（working tree vs 最后一次 commit），覆盖 Agent 刚做完的未提交修改。不需要 Agent 配合做 snapshot。
