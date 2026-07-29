# 知识存放规则

## 通用知识 → docs/Guidelines/

存放跨模块适用、表达"默认怎么做"的施工规则和规范。

默认文件建议：

| 文件 | 内容 |
|------|------|
| `paths.md` | 路径与目录规范 |
| `naming.md` | 命名规则 |
| `logging.md` | 日志格式与级别 |
| `configuration.md` | 配置优先级与来源 |
| `testing.md` | 构建与测试入口 |
| `engineering.md` | 通用工程约定 |

**不要**为一条小规则创建孤立文件。更新已有文件中的对应章节。

## 模块级知识 → docs/Framework/

存放单一模块的稳定职责和功能链路。

建议默认单文件：

```
docs/Framework/<module-name>.md
```

当且仅当一个模块存在多个明显独立、且每条链路都足够复杂时，才拆为目录：

```
docs/Framework/<module-name>/
├── overview.md
└── flows/
    └── <flow-name>.md
```

**不要**一开始创建目录树。

## 与现有文档模型一致

此划分与 `tidy-doc` 的文档 owner 模型一致：

- Guidelines：回答"默认怎么做"和施工约束
- Framework：回答当前稳定基线和模块职责

两者不重复定义框架语义。
