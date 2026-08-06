# Mandatory Workflow

每项任务都必须遵循以下流程，不可跳过：

```
1. Understand（理解）
   └─ 明确需求，识别隐含假设，反问澄清不确定点

2. Analyze（分析）
   └─ 收集证据，检查日志/代码/数据，形成有依据的结论
   └─ 行为变更任务：实现前从需求推导行为契约
      （expected_behavior / failure_condition / regression_case）
      验证标准来自需求而非实现，避免测试与代码共享同一误解
   └─ 纯重构 / 文档 / 配置任务不强制行为契约

3. Implement（实现）
   └─ 遵循奥卡姆工程原则，最小化必要复杂度

4. Adversarial Review（对抗式自审）
   └─ 假设实现有 bug，主动寻找能推翻实现的证据
   └─ 不是"检查是否正确"，而是"尝试证明它错了"
   └─ 同时审视结构复杂度，删除不必要抽象

5. Evidence（证据收集）
   └─ 运行 illuminate evidence audit，获取确定性事实报告
   └─ Evidence Report 提供层 1 事实，Agent 不再自审复杂度
   └─ 行为变更任务：触发 behavior-verification skill 推导行为风险与缺失用例

6. Audit（审计）
   └─ 基于结构事实（Evidence Report）+ 行为风险（behavior-verification 产出）做层 3 判断
   └─ 附带复杂性审计，记录最终结果
```

## Meta Rule

当两项原则看似冲突时，按以下优先级执行：

```
证据先于评估（最高）
  ↓
根因优先
  ↓
奥卡姆工程
  ↓
日志优先（最低）
```

例如：奥卡姆工程说"删代码"，但证据先于评估说"先分析"。

此时应先完成证据收集，再决定是否删除。

## 强制审计

修改代码的响应必须包含复杂性审计，否则任务视为未完成。

审计内容：

- 新增抽象（Factory / Adapter / Wrapper / Registry）：[数量，逐个列出] — Evidence Report 提供
- 新增 fallback 路径：[数量] — Evidence Report 提供
- 新增 feature flag：[数量] — Evidence Report 提供
- 删除的代码：[行数] — Evidence Report 提供
- 新增注释中复述代码实现语义的（非解释 why / 约束 / trade-off）：[数量] — LLM 判断（层 3，无法脚本化）

前四项由 `illuminate evidence audit` 输出的 Evidence Report 提供，Agent 直接引用事实。
第五项是语义判断（层 3），由 Agent 基于代码内容判断，但必须引用 Evidence Report 中的其他事实作为上下文。

如果新增抽象 > 0，必须逐个说明为什么不能删除或简化。无法说明的，删掉。

## 合规确认

完成前逐项确认：

- 无不必要的抽象
- 无投机性工程
- 无不必要的 fallback
- 已评估现有代码复用可能
- 已考虑过更简单的方案

任何一项为"否"，重新开始设计流程，而非修补当前方案。
