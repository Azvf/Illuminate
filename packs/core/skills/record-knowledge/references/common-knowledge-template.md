# 通用知识模板

通用知识不需要 Front Matter，也不需要每条规则拆文件。

```markdown
# <目录主题>

本文记录跨模块适用、且无法仅凭局部代码明确判断的<规则类别>。

## <规则分类标题>

- <一条规则>
- <另一条规则>

## 实现锚点

- `<源文件路径>`
```

## 示例

```markdown
# 路径与目录规范

本文记录跨模块适用、且无法仅凭局部代码明确判断的路径规则。

## Android 平台配置

- SDK Android 配置统一放在 `GPMSDKLib/Android/`。
- 不在仓库根目录保留第二份平台配置。
- Manifest 权限或组件声明问题优先检查该目录的源文件。

## 实现锚点

- `GPMSDKLib/Android/AndroidManifest.xml`
- `src/SimsModDesktop.Infrastructure/Cache/`
```

## 关键原则

- 只记录非显然规则。
- 每条尽量一到三行。
- 不写长篇背景。
- 不写任务历史。
