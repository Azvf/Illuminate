"""Command catalog shared by harness sync adapters.

Defines the doc-related command shortcuts generated into the repo. The
prompt text is the single source of truth; every harness adapter that emits
these command files must produce byte-identical content.
"""

from typing import Dict, NamedTuple


class CommandSpec(NamedTuple):
    """A command shortcut mapping to an exposed skill."""

    skill_id: str
    prompt: str


def build_command_catalog() -> Dict[str, CommandSpec]:
    """Return the catalog of doc-related command shortcuts.

    Commands are only synced when their associated skill is exposed.
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
                "用户补充要求：\n\n$ARGUMENTS"
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
                "用户指定模块：\n\n$ARGUMENTS"
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
                "用户指定范围：\n\n$ARGUMENTS"
            ),
        ),
    }
