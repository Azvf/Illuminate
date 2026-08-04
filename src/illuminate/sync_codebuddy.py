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
from typing import Dict, List, Optional, Set, Tuple

from .hashutil import hash_file, hash_directory, lock_hash
from .lockfile import build_lock_envelope
from .managed_block import (
    BEGIN_MARKER as _BEGIN_MARKER,
    END_MARKER as _END_MARKER,
    make_begin_marker,
    merge_block,
    remove_block,
)
from .command_catalog import build_command_catalog
from .manifest import load_policy_index
from .resolve import resolve_pack
from .sync_shared import (
    check_managed_file_hashes,
    ensure_writable,
    preflight_managed_command_tree,
    preflight_managed_skill_tree,
    sync_managed_command_tree,
    sync_managed_skill_tree,
)
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

def _preflight_target_paths(repo_root: Path) -> None:
    """Verify every target Illuminate will create/write under repo_root is
    writable (or creatable), including an already-existing target file itself
    (not just its parent directory). Fails closed before any write."""
    for rel in (_RULES_DIR, _SKILLS_DIR, _COMMANDS_DIR, ".codebuddy/CODEBUDDY.md", _LOCK_DIR):
        ensure_writable(repo_root / rel)


def _sync_rules(pack_dir: Path, repo_root: Path, manifest: dict) -> Dict[str, str]:
    """Sync policies into .codebuddy/rules/illuminate/ as priority-ordered files.

    The rules directory is namespace-reserved for Illuminate and is rebuilt in
    full; callers must run preflight before this so the wipe cannot destroy
    project content when a later artifact would fail.

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
    managed_skills: Set[str],
) -> Dict[str, Dict[str, str]]:
    """Sync selected skills into .codebuddy/skills/.

    Returns {skill_name: {file_rel: sha256}} for all synced skill files.
    """
    return sync_managed_skill_tree(
        pack_dir,
        repo_root / _SKILLS_DIR,
        manifest,
        exposed,
        managed_skills,
    )


# ---------------------------------------------------------------------------
# Commands sync
# ---------------------------------------------------------------------------

def _desired_commands(exposed: Set[str]) -> Dict[str, str]:
    """Map command filenames to content.

    Standalone commands (``skill_id is None``) are always included; commands
    bound to a skill are included only when that skill is exposed. The explicit
    ``None`` check is required because ``spec.skill_id in exposed`` would raise
    TypeError for ``None``.
    """
    return {
        f"{name}.md": spec.prompt
        for name, spec in build_command_catalog().items()
        if spec.skill_id is None or spec.skill_id in exposed
    }


def _sync_commands(
    repo_root: Path,
    exposed: Set[str],
    previous_commands: Optional[Dict[str, str]] = None,
) -> Dict[str, str]:
    """Sync command shortcuts for doc-related skills.

    Only syncs commands whose associated skill is exposed. Uses the shared
    command syncer: only files recorded as previously managed are replaced or
    removed, so a project-owned command sharing a name fails closed instead of
    being overwritten.

    Returns {filename: sha256}.
    """
    return sync_managed_command_tree(
        repo_root / _COMMANDS_DIR,
        _desired_commands(exposed),
        previous_commands or {},
    )


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
      3. Phase 1 preflight: run every collision / writability check (skills,
         commands, rules, CODEBUDDY.md, lock) before writing anything. The
         rules directory is rebuilt via rmtree, so it must not run until every
         other artifact has passed.
      4. Phase 2 write: rebuild .codebuddy/rules/illuminate/, sync
         .codebuddy/skills/ and .codebuddy/commands/, merge CODEBUDDY.md,
         write .illuminate/codebuddy-lock.json.

    Any preflight failure raises ValueError with no file written.

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
    exposed = set(resolved["skills"]["exposed"])

    lock = _load_lock(repo_root)
    managed_skills = {e["name"] for e in lock.get("skills", [])}
    previous_commands = lock.get("commands")

    # 3. Phase 1 — preflight: run every collision / writability check before
    #    touching the repo. In particular the rules directory is rebuilt via
    #    rmtree, so it must not run until every other artifact has passed.
    preflight_managed_skill_tree(
        repo_root / _SKILLS_DIR, manifest, exposed, managed_skills
    )
    desired_commands = _desired_commands(exposed)
    preflight_managed_command_tree(
        repo_root / _COMMANDS_DIR, desired_commands, previous_commands or {}
    )
    _preflight_target_paths(repo_root)

    # 4. Phase 2 — write.
    rule_hashes = _sync_rules(pack_dir, repo_root, manifest)
    skill_hashes = _sync_skills(
        pack_dir, repo_root, manifest, exposed, managed_skills
    )
    command_hashes = _sync_commands(repo_root, exposed, previous_commands)

    # Merge CODEBUDDY.md
    codebuddy_path = repo_root / ".codebuddy" / "CODEBUDDY.md"
    codebuddy_path.parent.mkdir(parents=True, exist_ok=True)
    block_text = _build_codebuddy_block(manifest, exposed)
    new_content, modified = merge_block(codebuddy_path, block_text)
    codebuddy_path.write_text(new_content, encoding="utf-8")
    codebuddy_hash = hash_file(codebuddy_path)

    # Write lock
    _write_lock(
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
    check_managed_file_hashes(
        repo_root, _SKILLS_DIR, lock.get("skills", []), issues
    )

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

    Without a lock, clean cannot know what is managed: the rules directory is
    left untouched along with skills/commands.

    Does NOT remove project-owned .codebuddy content.
    """
    repo_root = Path(repo_root).resolve()
    removed = []

    # Load lock to know managed items
    lock = _load_lock(repo_root)
    has_lock = (repo_root / _LOCK_DIR / "codebuddy-lock.json").exists()

    # Remove managed rules directory (only when a lock tells us it is managed)
    if has_lock:
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
