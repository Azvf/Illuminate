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
| Layer 1 | 确定性事实 | Tools (本目录脚本) | LOC delta、file count、新增 class/interface、import 变化 |
| Layer 2 | 半确定性结构信号 | Tools 检测 + LLM 判定 | catch 链深度、`??` 链、命名模式匹配 |
| Layer 3 | 语义判断 | LLM (基于 Layer 1+2 证据) | 抽象是否必要？注释是在 narrating 还是 explaining why？ |

**Evidence Layer 覆盖 Layer 1 和 Layer 2。Layer 3 仍由 LLM 负责，但必须引用 Evidence Report 中的事实作为依据。**

## 文件结构

```
.evidence/
├── audit.py                      # 主入口 —— 运行所有 provider，输出 evidence.json
├── gitutil.py                    # 共享 git 工具（跨平台）
├── diff_provider.py              # LOC / file count 统计
├── patterns_provider.py          # 抽象 / feature flag / fallback 检测
├── patterns_config.json          # 默认检测配置（工具自带，可参考）
├── patterns_overlay.example.json # 用户自定义配置模板
├── imports_provider.py           # import / include 依赖变化
└── README.md                     # 本文件
```

## 配置与扩展

### 三层配置加载

`patterns_provider.py` 按以下顺序加载配置，后者合并到前者之上：

| 顺序 | 文件 | 角色 | 何时修改 |
|------|------|------|---------|
| 1 | 代码内 `_DEFAULT_CONFIG` | 兜底默认 | 几乎不改 |
| 2 | `.evidence/patterns_config.json` | 工具自带默认 | 工具升级时随版本更新 |
| 3 | `.evidence/patterns_overlay.json` | **用户自定义** | **频繁修改** |

**合并语义**：列表追加并去重（默认在前，overlay 追加在后）；字典递归合并；标量覆盖；`null` 表示移除某项（opt-out）。

这意味着 overlay 文件**只需要写新增项**，不需要复制整个默认配置。

### 如何扩展抽象关键词

场景：团队约定禁止 `Dispatcher` 和 `Coordinator` 命名。

1. 复制模板：
```bash
cp .evidence/patterns_overlay.example.json .evidence/patterns_overlay.json
```

2. 编辑 `patterns_overlay.json`：
```json
{
  "abstraction_keywords": [
    "Dispatcher",
    "Coordinator"
  ]
}
```

3. 运行审计，新关键词立即生效：
```bash
python .evidence/audit.py --pretty --repo .
```

Evidence Report 会记录生效的关键词列表和配置来源（`_config.sources`），确保可追溯。

### 配置文件格式

```json
{
  "abstraction_keywords": ["Factory", "Adapter", "Dispatcher"],
  "definition_keywords": ["class", "struct", "interface"],
  "feature_flag_patterns": ["#if(?:def|ndef)?\\b", "feature_?flag"],
  "fallback_patterns": {
    "catch_keywords": ["catch", "except"],
    "null_coalesce_chain": "\\?\\?.*\\?\\?"
  }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `abstraction_keywords` | 字符串列表 | 子串匹配（大小写不敏感）。最常扩展。 |
| `definition_keywords` | 字符串列表 | 类型定义关键字（class/struct/...）。很少扩展。 |
| `feature_flag_patterns` | 正则字符串列表 | 每条编译为正则。注意 JSON 中 `\` 需双写。 |
| `fallback_patterns.catch_keywords` | 字符串列表 | catch/except/rescue 等。 |
| `fallback_patterns.null_coalesce_chain` | 正则字符串 | 设为 `null` 可禁用此项。 |

## 使用方法

### 完整审计

```bash
python .evidence/audit.py --pretty --repo .
```

输出 `evidence.json` + 人类可读摘要（stderr）。

### 单独运行某个 provider

```bash
python .evidence/diff_provider.py .
python .evidence/patterns_provider.py .
python .evidence/imports_provider.py .
```

### 与 Mandatory Workflow 集成

```
1. Understand
2. Analyze（行为变更任务：推导行为契约）
3. Implement
4. Adversarial Review（假设有 bug，找它）
5. Run Evidence Providers  ←  python .evidence/audit.py
   [+ behavior-verification skill 推导行为风险，条件触发]
6. Audit (基于结构事实 + 行为风险做层 3 判断，而非凭空自报)
```

## 输出格式

`evidence.json` 只包含事实，不包含分数或风险评估：

```json
{
  "schema_version": 1,
  "generated_at": "2026-07-07T10:48:00Z",
  "baseline": "HEAD (working-tree diff)",
  "diff": {
    "files": {"added": 2, "modified": 1, "deleted": 0, "renamed": 0},
    "lines": {"added": 450, "removed": 80, "net": 370},
    "by_file": [...]
  },
  "patterns": {
    "new_abstractions": [
      {"name": "RendererFactory", "keyword": "Factory", "file": "...", "line": 42}
    ],
    "new_feature_flags": [...],
    "new_fallback_paths": [...],
    "_config": {
      "sources": ["built-in defaults", "patterns_config.json", "patterns_overlay.json"],
      "abstraction_keywords": ["Factory", "Adapter", "Dispatcher"],
      "definition_keywords": ["class", "struct", "..."],
      "feature_flag_pattern_count": 16,
      "fallback_patterns": {"catch_keywords": ["catch", "except"], "..."}
    }
  },
  "imports": {
    "added": [{"module": "kotlinx.coroutines.flow", "language": "kotlin", ...}],
    "removed": [...],
    "net_change": 3
  }
}
```

**没有 `risk` 字段，没有 `score`。** 判断留给 LLM。

## 为什么是 Evidence 而非 Score

Score（0-100 分）会触发 Goodhart's law：Agent 优化分数而非代码质量。

但 Evidence 本身也可能成为代理目标。如果 Agent 知道 `new_abstractions > 0` 会触发警告，它可能为了避免 flag 而拒绝所有抽象——包括必要的抽象。

缓解方式：Evidence Report 只陈述事实（`new_classes: [RendererFactory]`），不做评估（`risk: high`）。必要性判断由 LLM 在 Audit 步骤基于上下文完成。

## Evidence Diversity

比 100% test coverage 更重要的目标是 Evidence Diversity——一次修改由多种独立证据类型支撑，而非由大量同质测试覆盖。

同质测试的局限：AI 可以生成 1000 个测试全部通过，但它们可能共享同一个对需求的误解。证据类型多样性优先于证据数量。

| 证据类型 | 当前覆盖 | 提供者 | 扩展方向 |
|---------|---------|--------|---------|
| 结构复杂度（diff / patterns / imports） | ✓ | `audit.py` | — |
| 行为风险（缺失用例、边界、失败路径） | ✓ | `behavior-verification` skill（Layer 3） | — |
| 行为正确性（unit / integration test 结果） | ✗ | — | 按需，需可执行测试 |
| 变异测试 | ✗ | — | 按需，语言相关，核心逻辑触发 |
| 属性测试 | ✗ | — | 按需，parser / serializer / math 触发 |
| 静态分析（clang-tidy / ruff / mypy） | ✗ | — | 按需，语言相关 |

**Evidence Layer（本目录）与 behavior-verification 的分工**：

| 来源 | 输出类型 | 层级 | 进入 Audit 的方式 |
|------|---------|------|------------------|
| `audit.py` | 确定性结构事实 | Layer 1-2 | `evidence.json` |
| `behavior-verification` skill | 行为风险与缺失用例（语义判断） | Layer 3 | skill 产出文本 |

行为风险是 LLM 推导的，不是确定性事实，**不进 `evidence.json`**——那会破坏 Layer 1 的纯净性。如果 behavior-verification 产出了可执行测试且跑出 PASS/FAIL，那个结果可作为新的 Evidence Provider 加入 `audit.py`，但属未来工作。

扩展原则不变：按需添加，不预先实现。新增证据类型必须证明它覆盖了现有类型无法覆盖的盲区。

## 覆盖的审计项

| AGENTS.md 审计项 | 覆盖层 | Provider |
|------------------|--------|----------|
| 新增抽象 (Factory/Adapter/Wrapper/Registry) | Layer 1 | patterns_provider |
| 新增 feature flag | Layer 1 | patterns_provider |
| 新增 fallback 路径 | Layer 1-2 | patterns_provider |
| 删除的代码行数 | Layer 1 | diff_provider |
| 注释复述代码实现语义 | **Layer 3** | LLM only (无法脚本化) |

最后一项是语义判断，没有任何 AST 解析器能区分"narrating code"和"explaining why"。这正是三层模型的价值：Tools 做能做的，LLM 做必须做的，但 LLM 的判断基于 Tools 提供的事实。

## 依赖

- Python 3.8+
- git（在 PATH 中）
- 无第三方 Python 包（仅标准库）

## Baseline 策略

使用 `git diff HEAD`（working tree vs 最后一次 commit），覆盖 Agent 刚做完的未提交修改。不需要 Agent 配合做 snapshot。

## 扩展方向（按需添加，不要预先实现）

结构类：
- AST 级结构分析（需要 tree-sitter，语言相关）
- Cyclomatic complexity delta
- 依赖图变化可视化
- CI 集成（pre-commit hook）

行为类（见 Evidence Diversity 表格）：
- test_result_provider：接入 behavior-verification 产出的可执行测试结果（PASS/FAIL 为确定性事实）
- 变异测试：核心逻辑 / bugfix / parser / math / state machine 触发，非全量
- 属性测试：parser / serializer / math / algorithm 领域触发
