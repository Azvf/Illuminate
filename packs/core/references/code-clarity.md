# Code Clarity Guideline

本文件是 Constitution「奥卡姆工程 · 注释与结构（Refactor Before Comment）」的参考材料。

Constitution 放核心规则一句话；本文件放完整决策树与 Comment Smells 分类，供写代码与自审时查阅。

## 1. 注释决策树

```
要加注释？
  │
  ▼
注释在解释 WHAT（代码做什么）？
  ├─ YES
  │   代码结构能否自表达？
  │     ├─ YES → 重构代码，不加注释
  │     └─ NO  → 先重构（改名 / 提函数 / 调结构），再看是否还需要注释
  └─ NO（在解释 WHY / 约束 / trade-off / 外部要求）
      → 保留注释
```

## 2. 注释应解释 / 不应解释

**应解释：**
- why（为什么这样做）
- 约束（协议、硬件、历史决策限制）
- trade-off（取舍点）
- 外部要求（规范、兼容性要求）

**不应解释：**
- 语法
- 显而易见的控制流
- 变量赋值
- 命名已表达清楚的函数行为

## 3. Comment Smells

### Smell 1：复述代码（Narrating）

```cpp
// Set value to true
enabled = true;
```

代码已表达，注释无价值 → 删除。

### Smell 2：历史注释（Historical）

```cpp
// Changed this because previous version crashed
```

记录的是变更史，不是当前约束 → 改为记录当前约束：

```cpp
// 保持初始化顺序：Renderer 需在 Scene 创建前获取 GPU 资源
```

### Smell 3：注释补偿（Compensation）

函数上方需长段注释才能解释它在做什么 → 说明函数职责爆炸。

```cpp
// This function handles authentication,
// validates tokens, refreshes expired sessions,
// updates cache, logs failures...
void HandleAuth()
```

→ 拆分：

```
ValidateToken()
RefreshSession()
UpdateCache()
```

（结构信号归 `simplify-code` 指标 7 处理）

## 4. Refactor Before Comment 流程

遇到复杂代码段：

```
复杂代码
  │
  ▼
定位复杂度来源
  │
  ├─ 结构问题（职责爆炸 / 命名含糊 / 分支过多）
  │   → 重构（拆函数 / 改名 / 收拢分支），不加注释
  │
  └─ 外部约束（协议 / 硬件 / 历史决策）
      → 用注释记录 why
```

## 5. 自审检查

完成代码前自审每条新增注释：

- 它解释的是 WHAT 还是 WHY？
- 如果删掉它，命名 / 结构能否替代？
- 如果不能，它记录的是外部约束吗？

三条任一不满足 → 删除注释或重构代码。
