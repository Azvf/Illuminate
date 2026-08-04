"""Command catalog shared by harness sync adapters.

Defines the doc-related command shortcuts generated into the repo. The
prompt text is the single source of truth; every harness adapter that emits
these command files must produce byte-identical content.
"""

from typing import Dict, NamedTuple, Optional


class CommandSpec(NamedTuple):
    """A command shortcut.

    ``skill_id`` may be ``None`` for standalone commands that are always
    synced regardless of skill selection; non-``None`` commands are only
    synced when the associated skill is exposed.
    """

    skill_id: Optional[str]
    prompt: str


def build_command_catalog() -> Dict[str, CommandSpec]:
    """Return the catalog of command shortcuts.

    Commands with a ``skill_id`` are only synced when that skill is exposed;
    commands with ``skill_id=None`` are standalone and always synced.
    """
    return {
        "record-knowledge": CommandSpec(
            skill_id="illuminate.record-knowledge",
            prompt=(
                "使用 `record-knowledge` Skill。\n\n"
                "只记录本次开发中已经验证、未来可复用的最小事实。\n\n"
                "归档规则：\n\n"
                "- 组件/API 细节进入 `docs/20-components/`\n"
                "- 单模块职责和功能链路进入 `docs/30-modules/`\n"
                "- 跨模块流程进入 `docs/40-journeys/`\n"
                "- 身份和验证数据进入 `docs/70-metadata/`\n"
                "- 优先读取 Manifest.document，再更新已有 owner\n"
                "- 不扫描整个项目\n"
                "- 不补齐未经验证的内容\n"
                "- 不顺便整理无关文档\n\n"
                "用户补充要求（可选）：在此填写本次需要记录的具体内容或范围。"
            ),
        ),
        "archive-module-doc": CommandSpec(
            skill_id="illuminate.archive-module-doc",
            prompt=(
                "使用 `archive-module-doc` Skill。\n\n"
                "将单一模块已经存在且经过验证的知识，整理为 `docs/30-modules/<module>.md`。\n\n"
                "规则：\n\n"
                "- 只处理一个模块\n"
                "- 选择 Compact / Standard / Extended 模式\n"
                "- 先给出归档计划\n"
                "- 只归档已验证事实\n"
                "- 不为补齐模板而猜测\n\n"
                "用户指定模块（可选）：在此填写要归档的模块名或路径。"
            ),
        ),
        "tidy-doc": CommandSpec(
            skill_id="illuminate.tidy-doc",
            prompt=(
                "使用 `tidy-doc` Skill。\n\n"
                "跨模块、跨目录治理重复、过期、索引和 owner 问题。\n\n"
                "规则：\n\n"
                "- 不创建全量新文档\n"
                "- 不引入新事实\n"
                "- 同一事实只保留一个 owner\n"
                "- Guidelines 不重复 Framework 语义\n"
                "- 删除重复和过期内容\n"
                "- 修复失效路径和索引\n\n"
                "用户指定范围（可选）：在此填写需要整理的具体范围。"
            ),
        ),
        "finish-task": CommandSpec(
            skill_id=None,
            prompt=(
                "任务收尾时的知识回流编排。\n\n"
                "1. 总结本次任务中已经验证、未来可复用的最小事实。\n"
                "2. 直接归档可复用事实：\n\n"
                "归档规则：\n\n"
                "- 组件/API 细节进入 `docs/20-components/`\n"
                "- 单模块职责和功能链路进入 `docs/30-modules/`\n"
                "- 跨模块流程进入 `docs/40-journeys/`\n"
                "- 身份和验证数据进入 `docs/70-metadata/`\n"
                "- 只写已验证事实，不扫描全项目，不补齐未验证内容\n\n"
                "3. 确认没有未归档的可复用内容。\n\n"
                "示例（在仓库根目录运行）：\n\n"
                "```\n"
                "illuminate knowledge status --repo .\n"
                "```\n\n"
                "用户补充要求（可选）：在此填写本次任务收尾需要额外处理的内容。"
            ),
        ),
        "knowledge-status": CommandSpec(
            skill_id=None,
            prompt=(
                "查看 Illuminate 知识 Store 的当前状态。\n\n"
                "方向约定：\n\n"
                "- `pull` = 项目 → Store（备份项目文档到 Store）\n"
                "- `push` = Store → 项目（把 Store 较新的文档恢复到项目）\n\n"
                "1. 对比项目已配置知识与中心 Store 的同步差异。\n"
                "2. 项目文档有更新 → 按需 `knowledge pull`；中心 Store 有更新 → 按需 `knowledge push`。\n\n"
                "示例（在仓库根目录运行）：\n\n"
                "```\n"
                "illuminate knowledge status --repo .\n"
                "illuminate knowledge push --repo .\n"
                "```\n\n"
                "用户补充要求（可选）：在此填写本次需要查看的知识范围或 store 路径。"
            ),
        ),
        "propose-knowledge": CommandSpec(
            skill_id=None,
            prompt=(
                "发起一条知识候选，进入 candidate → review → promote 流程。\n\n"
                "1. 确认来源文档已存在于 `docs/` 下。\n"
                "2. 创建候选并绑定来源与目标类型。\n"
                "3. 说明后续 review / promote 步骤。\n\n"
                "目标类型：`policy`、`skill`、`reference`、`evidence`。\n\n"
                "示例（在仓库根目录运行，`--source` 相对 `docs/`）：\n\n"
                "```\n"
                "illuminate knowledge candidate --repo . --source 30-modules/demo.md --target reference\n"
                "illuminate knowledge review --repo . --id <id>\n"
                "illuminate knowledge promote --repo . --id <id> --pack packs/core\n"
                "```\n\n"
                "用户补充要求（可选）：在此填写要发起的来源路径、目标类型或备注。"
            ),
        ),
    }
