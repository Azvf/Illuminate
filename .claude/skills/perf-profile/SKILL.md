---
name: perf-profile
description: Profile long-running chains (startup, page load, list scroll, network requests), locate hotspot and root cause with a profiling-first workflow. Use when the task is to做性能分析、确认冷/热场景、用 profile 工具生成报告、缩小热点、区分 symptom / hotspot / root cause。
recommended_next: [backtrack-root-cause]
---

# Perf Profile

用这个 skill 做性能链路的排查：先固定场景、先拿证据、再缩热点、最后定根因。

## 触发条件

- 启动慢、冷启动/热启动场景
- 页面加载慢、白屏时间长
- 列表滚动卡顿、帧率掉帧
- 网络请求链路耗时异常
- 需要用 profile 工具生成报告、缩小热点、区分 symptom / hotspot / root cause

## 默认先读

- `docs/Guidelines/工程约定.md`

## 核心规则

1. **Profile 优先**：客观日志与阶段耗时优先于静态代码分析和体感判断
2. **脚本优先**：已有 profile 脚本优先于人工扫原始日志
3. **三级区分**：所有结论必须显式区分 symptom（现象）、hotspot（热点阶段）、root cause（根因）
4. **证据闭环**：没有 profile / 日志 / 报告支撑的 root cause 判断视为未完成
5. **场景隔离**：同一优化若同时影响多个场景（首开、搜索、列表滚动），必须拆场景分析，不用一个总感觉覆盖全部

## 工作流

1. **固定场景**：明确冷/热、首次/重复、具体操作链路
2. **锁定证据**：找到本次复现对应的日志、profile 文件
3. **跑脚本出报告**：优先用已有的 profile/分析脚本生成可读报告
4. **写三段结论**：当前现象、最重阶段、证据缺口
5. **缩小热点**：基于报告和日志把热点范围缩到具体 phase / batch / 时间窗
6. **定 root cause**：只有热点已锁定、日志已支撑时，才写根因判断
7. **决定后续**：修代码、补日志、补文档，而不是反过来先写方案

## 证据门禁

进入 root cause 结论前，以下条件必须全部满足：

- 已锁定对应的日志 / profile 文件
- 已跑分析报告（或已确认没有适用脚本）
- 已知道总耗时里最重的 1–3 个阶段
- 已区分慢的是单个阶段异常、多阶段一起抬升，还是前后台链路混淆
- 已区分 symptom、hotspot、root cause
- 已确认当前不是因为日志缺口导致的"假热点"

## 何时必须先补日志

以下任一情况，不要急着下结论，先补最小必要日志：

- 报告只有 request start / done，没有足够 phase 锚点
- 只能看到总耗时，看不到阶段切分
- 无法把 profile 时间窗映射回具体操作或 batch
- 无法区分前台触发和后台预热链路
- 现有日志只能说明"慢了"，不能说明"为什么慢"

补日志的目标：让下一轮报告能回答"哪段慢、输入规模多大、何时开始/结束、前台还是后台"。

## 完成前确认

- 复现场景（冷/热、首次/重复）
- 使用的日志/profile 文件
- 跑了哪支脚本、输出了哪份报告
- 最重阶段与当前缺失的日志锚点
- 当前结论级别（symptom / hotspot / root cause）

没有这些最小信息，排查视为未完成。

## 默认产出

- 场景与 profile 结论摘要
- 日志文件与脚本命令
- 热点阶段与 root cause 判断（或"未完成归因"的明确说明）
- 待补日志项或待确认假设
- 必要时迁移到 `docs/Issues` 或 `docs/Development`

## 边界

- 不负责常规功能开发——那属于对应实现类 skill
- 不负责功能链路分层排障——那属于 `layer-debug` 的职责
- 不负责 root cause 分析的流程框架——那属于 `backtrack-root-cause` 的职责；若反复打补丁陷入死循环，切到 `backtrack-root-cause`
- 如果任务核心已变成"根据已确认 root cause 直接改代码修复"，切回对应实现类 skill
