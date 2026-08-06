# Evidence Layer（证据审计）

Evidence Layer 是 Illuminate 的 Verification Layer —— 用确定性工具测量代码变更，替代 LLM 自审复杂度。

## 三层模型

| 层级 | 职责 | 执行者 |
|------|------|--------|
| Layer 1 | 确定性事实 | Evidence Providers（脚本） |
| Layer 2 | 半确定性结构信号 | Evidence Providers 检测 + LLM 判定 |
| Layer 3 | 语义判断 | LLM（基于 Layer 1 + 2 证据） |

Evidence Providers 覆盖 Layer 1 和 Layer 2。Layer 3 仍由 LLM 负责，但必须引用 Evidence Report 中的事实作为依据。

设计原则：

- **Evidence 而非 Score**：输出只包含事实，不包含分数或风险评估，避免 Goodhart's law。
- **确定性**：同一输入始终产生同一输出，不依赖 LLM 判断。
- **零依赖**：仅使用 Python 标准库 + git。

## evidence audit 命令

```bash
illuminate evidence audit --pretty
# 可指定知识包，绑定报告的 pack 身份
illuminate evidence audit --pack src/illuminate/builtin_pack --output report.json --pretty
```

`--repo` 默认当前目录，可省略；`--pack` 可绑定报告的 pack 身份。

## 报告输出

报告输出到 `<repo>/.illuminate/reports/evidence.json`。

`--pretty` 格式化输出，`--quiet` 抑制摘要。报告包含审计到的 errors，若存在 errors 命令返回非零退出码。

## 配置覆盖层

配置从低到高覆盖：

1. 内置默认值
2. Illuminate 包内置 `patterns_config.json`（随包分发，位于 `src/illuminate/evidence/patterns_config.json`）
3. 项目 `.illuminate/evidence/patterns_overlay.json`

后一层覆盖前一层。例如项目可用 `patterns_overlay.json` 覆盖包默认的检测模式，而无需改动内置或包内配置。
