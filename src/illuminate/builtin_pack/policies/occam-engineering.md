# Occam Engineering

## 哲学

最好的实现通常是移除复杂度的实现，而不是管理复杂度的实现。

解决任何问题时，优先选择：

- 删除代码而非新增代码
- 移除抽象而非引入新抽象
- 删除 fallback 路径而非维护多种行为
- 单一显式实现而非可配置架构
- 显式假设而非投机性前瞻设计

复杂度是 bug，除非已被证明是必要的。

## 决策 Workflow

```
Step 1: 现有代码能否解决？
  ├─ YES → 复用，不写新代码
  └─ NO  → Step 2

Step 2: 能否通过简化现有代码解决？
  ├─ YES → 删除/简化现有代码，不新增
  └─ NO  → Step 3

Step 3: 是否需要新抽象？
  ├─ YES → 证明其必要性（必须有具体场景）
  │        ├─ 能证明 → 实现，但保持最小化
  │        └─ 不能证明 → 拒绝，回到 Step 2 寻找更简单方案
  └─ NO  → 用最直接的方式实现
```

## 拒绝条件

拒绝任何引入以下模式的方案，除非每一项都有显式证明的必要性：

- Factory
- Adapter
- Registry
- Wrapper
- 兼容层
- 重试链
- Fallback 树
- Feature flag

如果无法证明某个抽象是必要的，拒绝它。

不是"尽量避免"，而是"直接拒绝"。

## 禁止投机性工程

永远不要因为以下原因而实现某件事：

- 以后可能有用
- 将来可能有其他 provider
- 某人可能需要自定义
- 未来兼容性
- 假设性可扩展性

除非用户明确要求，否则假设当前需求就是正确的。

## 反模式库

**反模式 1：过度抽象链**

```
ProviderFactory → FactoryManager → ProviderRegistry → FallbackProvider → RetryProvider → Adapter → Executor
```

正确做法：`Provider`

**反模式 2：防御性 Fallback**

```
try { result = primarySource.get(); }
catch { try { result = fallbackSource.get(); }
catch { result = default; } }
```

正确做法：`validate(primarySource); result = primarySource.get();`

**反模式 3：兼容层堆叠**

```
LegacyAdapter → CompatibilityWrapper → NewApiBridge → LegacyConverter
```

正确做法：直接实现新接口，删除旧代码

## 重构规则

修改现有代码时，不要只做新增。同时寻找以下机会：

- 删除死代码
- 合并重复逻辑
- 移除不必要的抽象
- 合并多个分支
- 简化 API

每次改动都应该让代码库比改动前更简洁。

## 注释与结构（Refactor Before Comment）

遇到需要注释才能理解的代码段时，默认行为不是"添加解释性注释"，而是"定位复杂度来源并降低结构复杂度"。

先回答：

- 能否通过命名表达意图？
- 能否提取函数让职责单一化？
- 能否通过结构调整消除歧义？

只有当复杂度源自外部约束（协议、硬件、历史决策）而非结构问题时，才用注释记录原因。

注释应解释 why / 约束 / trade-off / 外部要求，不应复述代码已表达的实现细节。

> 完整注释决策树与 Comment Smells 分类见 `references/code-clarity.md`。

## 完成标准

设计完成当且仅当：

- 无不合理的抽象残留
- 无不合理的 fallback 残留
- 已考虑过更简单的替代方案
- 已评估过现有代码复用可能
