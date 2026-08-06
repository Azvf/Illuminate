# Pack 开发（Pack Development）

面向知识包贡献者的指南：校验、兼容目录、resolve 与项目结构。

## pack validate

每次改动知识包后，先校验再使用：

```bash
illuminate pack validate src/illuminate/builtin_pack
```

校验 `pack.json` 声明的 policies / skills / references / evidence 边界是否合法、文件是否存在。校验通过时输出 Pack id / version 与技能数；失败时列出错误清单并返回非零退出码。

## compat generate / check

为期望旧版 `.claude/skills/` 布局的工具生成兼容目录：

```bash
illuminate compat generate          # 生成兼容目录（默认 pack：内置 Core Pack）
illuminate compat check             # 校验与规范源一致（文件 + SHA-256）
```

- `compat generate`：从规范源把技能文件复制到 `.claude/skills/`。
- `compat check`：校验兼容目录与规范源一致（逐文件 + SHA-256）。`--pack <dir>` 可指定 pack。

## resolve

`resolve`（`src/illuminate/resolve.py`）解析知识包，生成 mount-plan（含 git 身份）。它在 `run` / `mount create` 时被调用，决定会话挂载的技能、权限与文件。

## 项目目录结构

```
src/illuminate/builtin_pack/  # 内置 Core Pack（policies、skills、references、evidence 配置，随包分发）
src/illuminate/               # CLI 实现（validate、resolve、materialize、evidence、sync、knowledge 等）
src/illuminate/schemas/   # pack / contract / mount-plan / mount-lock 的 JSON Schema（随包分发）
tests/               # 单元测试
evals/routing/       # 路由评估用例
```

## 开发流程

```bash
pip install -e .             # 安装（零运行时依赖，Python >= 3.9）
illuminate pack validate src/illuminate/builtin_pack
python -m pytest tests/ -q
```
