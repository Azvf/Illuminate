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
6. 没有匹配项时，再搜索文档标题和正文，然后进入代码搜索。

## 知识边界

- Metadata 用于判断可信度，不代替人类正文。
- 文档用于缩小搜索范围，不构成证据；最终行为结论的验证遵循 `evidence-first`（通过代码、配置、日志或测试验证）。
