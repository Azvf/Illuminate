---
name: behavior-verification
description: Verify behavioral correctness of code changes by modeling the behavior space and hunting for missing cases. Use when 新功能、行为修改、bugfix 需要验证修改是否改变正确行为——从需求推导行为空间，主动寻找能推翻实现的证据，而非确认已有测试通过。
recommended_next: [layer-debug, impact-analysis]
---

# Behavior Verification

用这个 skill 验证代码修改是否改变正确行为。

**核心立场**：Agent 不应该证明自己正确，而应该主动寻找能推翻自己的证据。测试来自行为空间模型，不来自代码实现。

## 触发条件

满足以下任一即激活：

- 任务产生行为变更（新功能、行为修改、状态机变更）
- 任务修复 bug（回归风险）
- 用户明确要求行为验证

不触发：

- 纯重构（行为不变，`simplify-code` 已覆盖结构）
- 文档 / 配置变更
- 纯结构精简

## 核心规则

1. **测试来自行为空间模型，不来自代码实现**

   错误：读代码 → 写测试覆盖代码分支
   正确：从需求推导行为空间 → 识别风险区域 → 推导应有用例

   后者会暴露代码从未考虑的状态；前者只会复述代码已有的分支，测试与代码共享同一误解。

2. **先建模，再写测试**

   ```
   需求 → 行为空间模型 → Verification Gap Analysis → 验证用例
   ```

   跳过行为空间建模直接写测试，等于假设需求已完整——但需求通常不完整。

3. **主动寻找反证，而非确认正确**

   不是"检查实现是否正确"，而是"假设实现有 bug，尝试找到它"。
   支撑证据容易找；反证才能区分"碰巧没暴露"和"确实没问题"。

## 工作流

### 步骤 1：行为空间建模

不要直接写测试。先列举需求隐含的所有状态、转换、边界与失败路径。

以"玩家死亡后复活"为例：

```
死亡状态
  ├─ 正常死亡（满血 → 0）
  ├─ 网络断开期间的死亡
  ├─ 重复死亡事件（已死再死）
  ├─ 死亡过程中退出再重连
  └─ 多玩家同步（他人视角的死亡时机）
```

需求只说"死亡后复活"，但行为空间包含 5 种状态。漏掉任何一种都可能埋 bug。

### 步骤 2：Verification Checklist

对行为空间每一区域，逐项检查：

| 维度 | 追问 |
|------|------|
| State changes | 状态转换是否完整？reset 是否彻底？旧状态有无残留？ |
| Boundary conditions | 边界值（0、max、空、满）行为是否正确？off-by-one？ |
| Failure paths | 失败时是否回滚？部分失败？重试？ |
| Concurrency | 并发调用是否安全？竞态？重入？ |
| Recovery | 异常后能否恢复？重启后状态是否一致？ |
| Backward compatibility | 旧数据 / 旧调用方是否仍工作？序列化兼容？ |

### 步骤 3：风险区域识别

标注每个行为空间区域的风险等级：

- 高风险：状态变更、并发、失败恢复、跨模块同步
- 中风险：边界、格式解析、外部输入
- 低风险：纯计算、无副作用转换

### 步骤 4：缺失用例枚举

对比"行为空间应有用例"与"现有测试 / 现有代码已覆盖"，列出 gap：

```
应有但缺失：
  - 死亡过程中退出的复活处理
  - 并发死亡事件的状态一致性
  - 重连后的死亡状态同步

已有但薄弱：
  - 正常死亡只测了满血 → 0，没测 1HP → 0
```

### 步骤 5：输出

```
Verification Risks:
  - [高风险] 重连后死亡状态可能不一致（Step 2 Concurrency 未覆盖）
  - [中风险] 复活时 HP 未 reset（Step 2 State changes 未覆盖）

Missing Cases:
  - 死亡过程中退出再重连
  - 重复死亡事件
  - 多玩家同步时机

Required Tests:
  - test_respawn_after_disconnect
  - test_double_death_event_idempotent
  - test_multiplayer_death_sync
```

## 完成前确认

- 行为空间建模是否覆盖了需求未明说但隐含的状态
- Verification Checklist 六维度是否逐项走过
- 缺失用例是否来自行为空间推导，而非代码分支复述
- 高风险区域是否都有对应验证

## 默认产出

- 行为空间模型（状态 / 转换 / 边界 / 失败路径）
- Verification Risks（按风险等级标注）
- Missing Cases（应有但缺失的用例）
- Required Tests（建议补写的测试名与验证目标）

## 边界

- 不负责结构复杂度——那是 `simplify-code` + Evidence Layer
- 不负责排障已有 bug——那是 `layer-debug`（本 skill 主动找潜在问题，`layer-debug` 被动排已暴露问题）
- 不负责跨模块影响范围评估——那是 `impact-analysis`
- 不负责设计阶段方案追问——那是 `grilling`

发现的行为风险确认为 bug → `layer-debug`
行为变更涉及跨模块 → `impact-analysis`
