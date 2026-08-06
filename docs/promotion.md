# 知识晋升（Knowledge Promotion Bridge）

把 Store（备份工具）中的知识晋升为 Harness Pack（Git 版本化、经评审的通用知识）的薄桥。

## 状态机

```
raw ──review──> reviewed ──promote──> promoted
 │                 │                      │
 └──reject──> rejected    └──superseded──> superseded
```

- `raw → reviewed → promoted`：正常晋升路径。
- `raw / reviewed → rejected`：拒绝候选。
- `promoted → superseded`：标记已晋升的产物为 superseded，并从 pack 移除产物。

注册表位于 `<store>/projects/<project-id>/promotions.json`。

## 命令示例

```bash
# 1. 从知识源创建候选（记录 git 远端、commit、docs 相对路径、anchor 与精确字节）
illuminate knowledge candidate --repo /path/to/project --source 30-modules/hot-update.md --target reference

# 2. 评审：绑定且只绑定一次 —— 要么绑定源码，要么用 --content 绑定泛化草稿
illuminate knowledge review --repo /path/to/project --id <candidate-id> --reviewer alice
illuminate knowledge review --repo /path/to/project --id <candidate-id> --reviewer alice --content generalized.md

# 3. 晋升进知识包（受 reviewed_sha256 守护：评审后改过的内容会被拒绝；先 --dry-run 预览计划）
illuminate knowledge promote --repo /path/to/project --id <candidate-id> --pack src/illuminate/builtin_pack --dry-run
illuminate knowledge promote --repo /path/to/project --id <candidate-id> --pack src/illuminate/builtin_pack

# 4. 拒绝候选，或把已晋升的标记为 superseded（并从 pack 移除产物）
illuminate knowledge reject --repo /path/to/project --id <candidate-id>
illuminate knowledge reject --repo /path/to/project --id <candidate-id> --superseded --pack src/illuminate/builtin_pack
```

## reviewed_sha256 守护

`promote` 受 `reviewed_sha256` 守护：评审后内容被改动过的候选会拒绝晋升。可用 `--dry-run` 先预览晋升计划。`--force` 可覆盖 pack 中已存在的目标文件。

## 晋升目标

- `reference` — 追加到 `pack.json.references`
- `policy` — 追加到 `policies/index.json`
- `skill` — 写 `skills/<name>/SKILL.md` + 最小 `contract.json`
- `evidence` — 设置 `pack.json.evidence.config`

写入后自动运行 `validate_pack`；校验失败则整体回滚（文件 + manifest + index）。

## ownership 与 superseded 约束

- 晋升不暂存、不提交：只写入 Pack 工作树，commit 与 PR 留给 Git 与人工。
- 更名升级用 `--replaces <id>` 声明前任，启用重命名 reference / policy 的 `--force` 升级。
- 未声明 owner 的产物拒绝被 `superseded` 删除。

`--store <dir>` 可覆盖中央库目录（默认 `~/.illuminate/knowledge`）。
