---
name: simplify-code
description: 代码精简诊断与链路缩短 — 判断何时消除冗余传递、提取单例、缩短调用链
---

# simplify-code: 代码精简 Skill

## 两种精简路径

| 路径 | 做法 | 适用场景 |
|---|---|---|
| **A** | 去掉 Request DTO 中多余的字段 | 该字段不属于请求上下文 |
| **B** | 抽成 `{Name}Provider` + DI 注入 | 数据生命周期长、传递链深 |

两条路径可组合使用。

---

## 硬性指标

以下模式必须精简。

### 指标 1：多重 fallback 链

```kotlin
// ❌ N 个 fallback = N 种静默行为差异
val value = request.someContext?.someProperty
          ?: settings.someSection?.someProperty
          ?: hardcodedDefault
```

```kotlin
// √ Provider 内部收拢所有 fallback，消费者不感知
interface MyContextProvider { val current: MyContext }
```

### 指标 2：多策略链路转换

```kotlin
// ❌ 每层手动附加上下文，链路越长越容易遗漏
val dto = mapToDto(entity)
dto.someContext = config.someContext
val request = SomeRequest(data = dto, someContext = dto.someContext)
```

```kotlin
// √ 消费者直取，不依赖上游传递
val context = provider.current
```

### 指标 3：新老链路并行运行

```kotlin
// ❌ 双倍分支覆盖，迁移结束不敢删"万一还在用"的老路径
if (context == null) context = provider.current
```

```kotlin
// √ 留一条路
val context = provider.current
```

### 指标 4：同值穿过多层中间件/过滤器

```kotlin
// ❌ 类型不安全，中间层可能忘设或覆盖
context["SomeKey"] = config.someContext
val ctx = context["SomeKey"]
```

```kotlin
// √ Handler/Service 直接 inject Provider
class MyHandler(private val provider: MyContextProvider) { ... }
```

### 指标 5：多配置参数注入

```kotlin
// ❌ 多个配置对象传达同一信号
class Foo(
  private val configA: ConfigA,
  private val configB: ConfigB,
  private val configC: ConfigC
)
```

```kotlin
// √ 合并为聚合 Provider
interface AggregatedConfigProvider { val current: AggregatedConfig }
```

### 指标 6：同层逻辑碎片化

```kotlin
// ❌ 同一工具方法在 N 个文件各有副本，独立漂移
// FileUploader.kt:       extensions = listOf(".jpg", ".png")              // 缺 .webp
// ImagePicker.kt:        extensions = listOf(".jpg", ".png", ".webp")     // 缺 Directory.Exists
// MediaApi.kt:           extensions = listOf(".jpg", ".png")              // 啥都缺
```

```kotlin
// √ internal 单一来源，一处维护
internal object MediaFileResolver {
  fun findMediaFiles(root: File, key: String): List<File> { ... }
}
val files = MediaFileResolver.findMediaFiles(root, key)
```

| 对比 | Provider (指标 1-5) | Shared Utility (指标 6) |
|---|---|---|
| 关注点 | 数据从哪来、往哪传 | 算法写在哪、谁在用 |
| 有状态 | 是（缓存、fallback） | 否（纯函数） |
| 抽象手段 | 接口 + DI | `internal` |
| 测试方式 | mock 接口 | 直接调用 |

---

## 决策树

```
指标 1-2 命中 → 数据属于全局上下文？
  ├─ YES → 路径 B：提取 Provider，收拢 fallback/转换逻辑
  └─ NO  → 可能属于请求上下文

指标 3-4 命中 → 链路设计问题
  └─ 路径 B：Provider 注入到最终消费者，删除中间层透传

指标 5 命中 → 合并为聚合 Provider

指标 6 命中 → 逻辑是纯函数？
  ├─ YES → internal utility，删除各文件中的私有副本
  └─ NO  → 依赖以参数传入方法；需注入则走 DI

都不命中 → stop（代码可能已足够精简）
```

---

## 实践要点

### 路径 B 实施步骤
1. 核心层定义 `{Name}Provider { val current: T }`
2. 基础设施层实现，收拢所有 fallback/缓存/懒加载
3. DI 注册为 Singleton
4. 从 Request DTO 移除字段（路径 A）
5. 消费者改为注入 Provider
6. Grep 确认零遗留

### Shared Utility 实施步骤（指标 6）
1. 确认条件：≥ 2 副本、同层、纯函数
2. 创建 `internal` 类/对象，收拢逻辑
3. 替换所有调用方，删除私有副本
4. 边界：有 DI 依赖 → 走标准服务；跨层 → 定义接口

### 验证清单
- 构建全项目 + 运行测试套件
- Grep 确认旧字段/方法名零引用
- 指标 3 场景：确认老链路已彻底删除

---

## Anti-Patterns

- **❌ fallback 策略散落在 N 个 Provider** — 聚合到一个 Provider，暴露单一 `current`
- **❌ Provider 做成全局变量** — 必须接口 + DI，测试可 mock
- **❌ 新老路径并行超过一个迭代** — 迁移完立即清理老路径，不留兼容代码
- **❌ 路径 A 和 B 只做一半** — 既删 request 字段又改注入才算完整
