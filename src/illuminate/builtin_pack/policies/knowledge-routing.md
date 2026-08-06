# Project Knowledge Routing

## 路由规则

开始广泛搜索源码或分析实现前，先检查项目知识导航。

1. 若存在项目 Knowledge Map，优先读取。
2. 根据任务类型查找知识：
   - 组件/API/生命周期 → docs/20-components/
   - 单模块职责、状态和功能链路 → docs/30-modules/
   - 跨模块顺序和交接 → docs/40-journeys/
   - Claim、Gap、Test、Evidence → docs/70-metadata/
3. 跨模块问题先读 Journey，再沿链接进入 Module 和 Component。
4. 单模块问题先读 Manifest.document 指向的正文。
5. 有匹配知识时，不得先扫描整个仓库。
6. 若目标仓库存在 `.codegraph/`：
   - 架构、调用链、符号位置和改动影响问题，优先使用 CodeGraph MCP 工具
     （`codegraph_explore` 等）；不支持 MCP 的 Harness 使用
     `codegraph explore "<question>"`。
   - 不得在 CodeGraph 已返回完整上下文后，再进行全仓库 Grep/Read 重复探索。
   - CodeGraph 用于缩小源码范围，不替代日志、测试和最终源码验证。
   - 若 CodeGraph 返回索引延迟或 stale 提示，只直接读取被提示的文件。
7. 没有匹配项时，再搜索文档标题和正文，然后进入代码搜索。

## 知识边界

- Metadata 用于判断可信度，不代替人类正文。
- 文档用于缩小搜索范围，不构成证据；最终行为结论的验证遵循 `evidence-first`（通过代码、配置、日志或测试验证）。
