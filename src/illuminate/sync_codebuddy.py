"""CodeBuddy sync: synchronize Illuminate Pack into a target repository for CodeBuddy.

Generates:
  .codebuddy/CODEBUDDY.md           (Illuminate managed block, entry only)
  .codebuddy/rules/illuminate/      (policies as separate files, priority-ordered)
  .codebuddy/skills/                (selected skills, managed via lock ownership)
  .illuminate/codebuddy-lock.json   (sync manifest with hashes)

Does NOT modify project content outside Illuminate-managed paths.
Does NOT delete project-owned skills/rules/commands.
"""

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Set, Tuple

from .hashutil import hash_file, hash_directory, lock_hash
from .lockfile import build_lock_envelope
from .managed_block import (
    BEGIN_MARKER as _BEGIN_MARKER,
    END_MARKER as _END_MARKER,
    make_begin_marker,
    merge_block,
    remove_block,
)
from .manifest import load_policy_index
from .resolve import resolve_pack
from .validate import validate_pack


# ---------------------------------------------------------------------------
# Managed paths (Illuminate owns these entirely)
# ---------------------------------------------------------------------------

_RULES_DIR = ".codebuddy/rules/illuminate"
_SKILLS_DIR = ".codebuddy/skills"
_COMMANDS_DIR = ".codebuddy/commands"
_LOCK_DIR = ".illuminate"


# ---------------------------------------------------------------------------
# Rules sync
# ---------------------------------------------------------------------------

def _sync_rules(pack_dir: Path, repo_root: Path, manifest: dict) -> Dict[str, str]:
    """Sync policies into .codebuddy/rules/illuminate/ as priority-ordered files.

    Returns {filename: sha256} for all synced rule files.
    """
    policy_index = load_policy_index(pack_dir, manifest)
    policies = sorted(
        policy_index.get("policies", []),
        key=lambda p: p.get("priority", 0),
        reverse=True,
    )

    rules_dir = repo_root / _RULES_DIR
    if rules_dir.exists():
        shutil.rmtree(rules_dir)
    rules_dir.mkdir(parents=True, exist_ok=True)

    hashes: Dict[str, str] = {}
    for i, policy in enumerate(policies):
        src = pack_dir / "policies" / policy["path"]
        if not src.exists():
            continue
        # Use priority-ordered naming: 00-*, 10-*, 20-*, etc.
        prio = f"{i:02d}"
        filename = f"{prio}-{Path(policy['path']).stem}.md"
        dest = rules_dir / filename
        shutil.copy2(src, dest)
        hashes[filename] = hash_file(dest)

    return hashes


# ---------------------------------------------------------------------------
# Skills sync
# ---------------------------------------------------------------------------

def _sync_skills(
    pack_dir: Path,
    repo_root: Path,
    manifest: dict,
    exposed: Set[str],
) -> Dict[str, Dict[str, str]]:
    """Sync selected skills into .codebuddy/skills/.

    Returns {skill_name: {file_rel: sha256}} for all synced skill files.
    """
    skills_dir = repo_root / _SKILLS_DIR

    # Load existing lock to know which skills Illuminate manages
    lock = _load_lock(repo_root)
    managed_skills = {e["name"] for e in lock.get("skills", [])}

    # Pre-flight collision check: fail closed before touching the repo, so a
    # project-owned directory that shares a skill's name is never overwritten.
    for entry in manifest.get("skills", []):
        if entry["id"] not in exposed:
            continue
        skill_name = entry["dir"].split("/")[-1]
        dest_dir = skills_dir / skill_name
        if dest_dir.exists() and skill_name not in managed_skills:
            raise ValueError(
                f"Cannot sync skill '{skill_name}': "
                "destination already exists and is not Illuminate-managed"
            )

    skills_dir.mkdir(parents=True, exist_ok=True)
    synced: Dict[str, Dict[str, str]] = {}

    for entry in manifest.get("skills", []):
        if entry["id"] not in exposed:
            continue
        skill_dir = pack_dir / entry["dir"]
        if not skill_dir.exists():
            continue
        skill_name = entry["dir"].split("/")[-1]
        dest_dir = skills_dir / skill_name

        # Clean only if this skill was previously managed (to handle content removal)
        if skill_name in managed_skills and dest_dir.exists():
            shutil.rmtree(dest_dir)
        dest_dir.mkdir(parents=True, exist_ok=True)

        file_hashes: Dict[str, str] = {}
        for f in sorted(skill_dir.rglob("*")):
            if not f.is_file():
                continue
            rel = f.relative_to(skill_dir)
            dest = dest_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, dest)
            file_hashes[rel.as_posix()] = hash_file(dest)

        synced[skill_name] = file_hashes

    # Remove stale skills (those in lock but no longer exposed)
    for skill_name in managed_skills:
        skill_path = skills_dir / skill_name
        if skill_path.exists() and skill_name not in synced:
            shutil.rmtree(skill_path)

    return synced


# ---------------------------------------------------------------------------
# Commands sync
# ---------------------------------------------------------------------------

def _sync_commands(
    repo_root: Path,
    exposed: Set[str],
    manifest: dict,
    contracts: list,
) -> Dict[str, str]:
    """Sync command shortcuts for doc-related skills.

    Currently generates commands for:
      - record-knowledge
      - archive-module-doc
      - tidy-doc

    Returns {filename: sha256}.
    """
    contracts_by_id = {c["id"]: c for c in contracts}

    commands: Dict[str, dict] = {
        "record-knowledge": {
            "name": "record-knowledge",
            "skill_id": "illuminate.record-knowledge",
            "prompt": (
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
        },
        "archive-module-doc": {
            "name": "archive-module-doc",
            "skill_id": "illuminate.archive-module-doc",
            "prompt": (
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
        },
        "tidy-doc": {
            "name": "tidy-doc",
            "skill_id": "illuminate.tidy-doc",
            "prompt": (
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
        },
    }

    # Only sync commands for skills that are exposed
    commands_dir = repo_root / _COMMANDS_DIR
    commands_dir.mkdir(parents=True, exist_ok=True)

    hashes: Dict[str, str] = {}
    for cmd_name, cmd_info in commands.items():
        skill_id = cmd_info["skill_id"]
        if skill_id not in exposed:
            continue
        cmd_path = commands_dir / f"{cmd_name}.md"
        cmd_path.write_text(cmd_info["prompt"], encoding="utf-8")
        hashes[f"{cmd_name}.md"] = hash_file(cmd_path)

    return hashes


# ---------------------------------------------------------------------------
# CODEBUDDY.md block merge
# ---------------------------------------------------------------------------

def _build_codebuddy_block(manifest: dict, exposed: Set[str]) -> str:
    """Build the Illuminate CODEBUDDY.md block."""
    begin = make_begin_marker(manifest)
    exposed_list = ", ".join(sorted(exposed))
    lines = [
        begin,
        "",
        "# Illuminate Integration",
        "",
        "通用治理规则位于：",
        "",
        "- `.codebuddy/rules/illuminate/`",
        "",
        "可复用工作流位于：",
        "",
        "- `.codebuddy/skills/`",
        "",
        "项目稳定知识位于：",
        "",
        "- `docs/20-components/`",
        "- `docs/30-modules/`",
        "- `docs/40-journeys/`",
        "- `docs/70-metadata/`",
        "",
        "开发中发现可长期复用的小型事实时，使用 `/record-knowledge`。",
        "当单一模块文档需要形成结构体系时，使用 `/archive-module-doc`。",
        "跨模块清理重复、过期路径或索引时，使用 `/tidy-doc`。",
        "",
        f"Synchronized skills: {exposed_list}",
        "",
        _END_MARKER,
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Lock management
# ---------------------------------------------------------------------------

def _load_lock(repo_root: Path) -> dict:
    """Load existing codebuddy-lock.json or return empty."""
    lock_path = repo_root / _LOCK_DIR / "codebuddy-lock.json"
    if lock_path.exists():
        return json.loads(lock_path.read_text(encoding="utf-8"))
    return {"skills": []}


def _write_lock(
    pack_dir: Path,
    repo_root: Path,
    manifest: dict,
    exposed: Set[str],
    rule_hashes: Dict[str, str],
    skill_hashes: Dict[str, Dict[str, str]],
    command_hashes: Dict[str, str],
    codebuddy_hash: str,
) -> dict:
    """Write codebuddy-lock.json."""
    lock_dir = repo_root / _LOCK_DIR
    lock_dir.mkdir(parents=True, exist_ok=True)

    pack_hash = hash_directory(pack_dir)

    skill_entries = []
    for skill_name, file_hashes in skill_hashes.items():
        skill_entries.append({
            "name": skill_name,
            "id": f"illuminate.{skill_name}",
            "files": file_hashes,
        })

    lock = build_lock_envelope(
        harness="codebuddy",
        pack={
            "id": manifest.get("id", "?"),
            "version": manifest.get("version", "?"),
            "hash": lock_hash(pack_hash),
        },
        target={"path": str(repo_root)},
        selection={"skills": sorted(exposed)},
        managed_artifacts=[
            ".codebuddy/CODEBUDDY.md",
            *[f".codebuddy/rules/illuminate/{name}" for name in rule_hashes],
            *[
                f".codebuddy/skills/{entry['name']}/{rel}"
                for entry in skill_entries
                for rel in entry["files"]
            ],
            *[f".codebuddy/commands/{name}" for name in command_hashes],
        ],
        capabilities={"permissions": "declarative-only"},
    )
    lock.update({
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "exposed_skills": sorted(exposed),
        "rules": rule_hashes,
        "skills": skill_entries,
        "commands": command_hashes,
        "codebuddy_md_hash": codebuddy_hash,
    })

    lock_path = lock_dir / "codebuddy-lock.json"
    with open(lock_path, "w", encoding="utf-8") as f:
        json.dump(lock, f, indent=2, ensure_ascii=False)
        f.write("\n")

    return lock


# ---------------------------------------------------------------------------
# Main sync entry point
# ---------------------------------------------------------------------------

def sync_codebuddy(
    pack_dir: Path,
    repo_root: Path,
    skill_filter: Optional[List[str]] = None,
) -> dict:
    """Synchronize Illuminate Pack into a target repository for CodeBuddy.

    Steps:
      1. Validate pack.
      2. Resolve exposed skills (filter + alias + conflict check).
      3. Sync .codebuddy/rules/illuminate/ (priority-ordered policy files).
      4. Sync .codebuddy/skills/ (selected skills, managed via lock ownership).
      5. Sync .codebuddy/commands/ (record-knowledge / archive-module-doc / tidy-doc).
      6. Merge CODEBUDDY.md managed block.
      7. Write .illuminate/codebuddy-lock.json.

    Returns a summary dict.
    """
    pack_dir = Path(pack_dir).resolve()
    repo_root = Path(repo_root).resolve()

    # 1. Validate
    ok, errors = validate_pack(pack_dir)
    if not ok:
        raise ValueError("Pack validation failed:\n" + "\n".join(errors))

    # 2. Resolve pack through the single shared resolution entry
    resolved = resolve_pack(pack_dir, str(repo_root), skill_filter)
    manifest = resolved["manifest"]
    contracts = resolved["contracts"]
    exposed = set(resolved["skills"]["exposed"])

    # 3. Sync rules
    rule_hashes = _sync_rules(pack_dir, repo_root, manifest)

    # 4. Sync skills
    skill_hashes = _sync_skills(pack_dir, repo_root, manifest, exposed)

    # 5. Sync commands
    command_hashes = _sync_commands(repo_root, exposed, manifest, contracts)

    # 6. Merge CODEBUDDY.md
    codebuddy_path = repo_root / ".codebuddy" / "CODEBUDDY.md"
    codebuddy_path.parent.mkdir(parents=True, exist_ok=True)
    block_text = _build_codebuddy_block(manifest, exposed)
    new_content, modified = merge_block(codebuddy_path, block_text)
    codebuddy_path.write_text(new_content, encoding="utf-8")
    codebuddy_hash = hash_file(codebuddy_path)

    # 7. Write lock
    lock = _write_lock(
        pack_dir, repo_root, manifest, exposed,
        rule_hashes, skill_hashes, command_hashes,
        codebuddy_hash,
    )

    return {
        "pack_id": manifest.get("id", "?"),
        "pack_version": manifest.get("version", "?"),
        "exposed_skills": sorted(exposed),
        "rules_copied": len(rule_hashes),
        "skills_copied": len(skill_hashes),
        "commands_copied": len(command_hashes),
        "codebuddy_modified": modified,
    }


# ---------------------------------------------------------------------------
# Check
# ---------------------------------------------------------------------------

def check_sync(pack_dir: Path, repo_root: Path) -> Tuple[bool, List[str]]:
    """Verify the CodeBuddy sync is current and consistent."""
    issues: List[str] = []
    pack_dir = Path(pack_dir).resolve()
    repo_root = Path(repo_root).resolve()

    lock_path = repo_root / _LOCK_DIR / "codebuddy-lock.json"
    if not lock_path.exists():
        return False, ["codebuddy-lock.json not found — run 'illuminate sync codebuddy'"]

    lock = json.loads(lock_path.read_text(encoding="utf-8"))

    # Check rules
    for filename, expected_hash in lock.get("rules", {}).items():
        fpath = repo_root / _RULES_DIR / filename
        if not fpath.exists():
            issues.append(f"Missing rule: {_RULES_DIR}/{filename}")
        else:
            actual = hash_file(fpath)
            if actual != expected_hash:
                issues.append(f"Rule hash mismatch: {_RULES_DIR}/{filename}")

    # Check skills
    for skill_entry in lock.get("skills", []):
        skill_name = skill_entry["name"]
        for rel, expected_hash in skill_entry.get("files", {}).items():
            fpath = repo_root / _SKILLS_DIR / skill_name / rel
            if not fpath.exists():
                issues.append(f"Missing skill file: {_SKILLS_DIR}/{skill_name}/{rel}")
            else:
                actual = hash_file(fpath)
                if actual != expected_hash:
                    issues.append(f"Skill hash mismatch: {_SKILLS_DIR}/{skill_name}/{rel}")

    # Check commands
    for filename, expected_hash in lock.get("commands", {}).items():
        fpath = repo_root / _COMMANDS_DIR / filename
        if not fpath.exists():
            issues.append(f"Missing command: {_COMMANDS_DIR}/{filename}")
        else:
            actual = hash_file(fpath)
            if actual != expected_hash:
                issues.append(f"Command hash mismatch: {_COMMANDS_DIR}/{filename}")

    # Check CODEBUDDY.md block
    codebuddy_path = repo_root / ".codebuddy" / "CODEBUDDY.md"
    if not codebuddy_path.exists():
        issues.append("CODEBUDDY.md not found")
    elif lock.get("codebuddy_md_hash"):
        actual = hash_file(codebuddy_path)
        if actual != lock["codebuddy_md_hash"]:
            issues.append("CODEBUDDY.md hash mismatch")

    return (len(issues) == 0), issues


# ---------------------------------------------------------------------------
# Clean
# ---------------------------------------------------------------------------

def clean_sync(repo_root: Path) -> dict:
    """Remove all Illuminate-synced artifacts from a repository.

    Removes:
      - .codebuddy/rules/illuminate/
      - .codebuddy/skills/ entries recorded in lock
      - .codebuddy/commands/ entries recorded in lock
      - .codebuddy/CODEBUDDY.md illuminate block
      - .illuminate/codebuddy-lock.json

    Does NOT remove project-owned .codebuddy content.
    """
    repo_root = Path(repo_root).resolve()
    removed = []

    # Load lock to know managed items
    lock = _load_lock(repo_root)

    # Remove managed rules directory
    rules_dir = repo_root / _RULES_DIR
    if rules_dir.exists():
        shutil.rmtree(rules_dir)
        removed.append(str(_RULES_DIR))

    # Remove managed skills (only those in lock)
    for skill_entry in lock.get("skills", []):
        skill_path = repo_root / _SKILLS_DIR / skill_entry["name"]
        if skill_path.exists():
            shutil.rmtree(skill_path)
            removed.append(f"{_SKILLS_DIR}/{skill_entry['name']}")

    # Remove managed commands (only those in lock)
    for filename in lock.get("commands", {}):
        cmd_path = repo_root / _COMMANDS_DIR / filename
        if cmd_path.exists():
            cmd_path.unlink()
            removed.append(f"{_COMMANDS_DIR}/{filename}")

    # Remove CODEBUDDY.md block
    codebuddy_path = repo_root / ".codebuddy" / "CODEBUDDY.md"
    if codebuddy_path.exists():
        content = codebuddy_path.read_text(encoding="utf-8")
        new_content = remove_block(content)
        if new_content != content:
            codebuddy_path.write_text(new_content, encoding="utf-8")
            removed.append("CODEBUDDY.md illuminate block")

    # Remove lock
    lock_path = repo_root / _LOCK_DIR / "codebuddy-lock.json"
    if lock_path.exists():
        lock_path.unlink()
        removed.append(".illuminate/codebuddy-lock.json")

    return {"removed_artifacts": removed}
