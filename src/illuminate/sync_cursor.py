"""Cursor sync: synchronize Illuminate Pack into a target repository for Cursor.

Generates:
  AGENTS.md                         (Illuminate managed block, merged via markers)
  .cursor/skills/<name>/            (selected skills, managed via lock ownership)
  .cursor/commands/<name>.md        (doc-related skill shortcuts, beta)
  .illuminate/cursor-lock.json      (sync manifest with hashes)

Notes:
  - This adapter shares the root AGENTS.md illuminate block with the Codex
    adapter. The block content is harness-agnostic, and the last writer wins
    (either adapter re-merges the same block when it runs). Because the lock
    records the hash of the whole AGENTS.md, syncing/cleaning one harness can
    make the other harness's `sync check` fail until it is re-synced; this is
    expected and documented here rather than special-cased per harness.
  - `.cursor/commands` is in beta: commands are only registered, never
    executed, and the capability is marked "beta" in the lock.
  - Permissions are declarative-only: no executable policy is generated.
  - The adapter does NOT generate `.cursor/rules`, `.cursor/cli.json`, or
    `.agents/skills`, and it does NOT rewrite SKILL.md bodies for Cursor
    (skills are copied verbatim).

Does NOT modify project content outside Illuminate-managed paths.
Does NOT delete project-owned skills/commands.
"""

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from .command_catalog import build_command_catalog
from .sync_shared import (
    build_agents_block,
    check_managed_file_hashes,
    remove_empty_parent_dirs,
    sync_managed_skill_tree,
)
from .hashutil import hash_file, hash_directory, lock_hash
from .lockfile import build_lock_envelope
from .managed_block import (
    BEGIN_MARKER as _BEGIN_MARKER,
    merge_block,
    remove_block,
)
from .resolve import resolve_pack
from .validate import validate_pack


# ---------------------------------------------------------------------------
# Managed paths (Illuminate owns these entirely)
# ---------------------------------------------------------------------------

_SKILLS_DIR = ".cursor/skills"
_COMMANDS_DIR = ".cursor/commands"
_LOCK_DIR = ".illuminate"
_LOCK_FILE = "cursor-lock.json"


# ---------------------------------------------------------------------------
# Lock management
# ---------------------------------------------------------------------------

def _load_lock(repo_root: Path) -> dict:
    """Load existing cursor-lock.json or return empty."""
    lock_path = repo_root / _LOCK_DIR / _LOCK_FILE
    if lock_path.exists():
        return json.loads(lock_path.read_text(encoding="utf-8"))
    return {"skills": []}


def _managed_skills(lock: dict) -> Set[str]:
    """Names of skills already recorded as Illuminate-managed."""
    return {e["name"] for e in lock.get("skills", [])}


# ---------------------------------------------------------------------------
# Commands sync
# ---------------------------------------------------------------------------

def _sync_commands(
    repo_root: Path,
    exposed: Set[str],
    previous_commands: Optional[Dict[str, str]] = None,
) -> Dict[str, str]:
    """Sync command shortcuts for exposed doc-related skills.

    Only commands whose skill is exposed are written. SKILL.md bodies are
    never rewritten; the command merely carries the skill's prompt.

    Commands recorded in a previous lock but no longer generated are removed,
    so a stale command that points at a no-longer-exposed skill cannot linger
    in `.cursor/commands/`.

    Returns {filename: sha256}.
    """
    commands_dir = repo_root / _COMMANDS_DIR
    commands_dir.mkdir(parents=True, exist_ok=True)

    hashes: Dict[str, str] = {}
    written: Set[str] = set()
    for name, spec in build_command_catalog().items():
        if spec.skill_id not in exposed:
            continue
        cmd_path = commands_dir / f"{name}.md"
        cmd_path.write_text(spec.prompt, encoding="utf-8")
        hashes[f"{name}.md"] = hash_file(cmd_path)
        written.add(f"{name}.md")

    # Remove stale managed commands no longer generated
    for filename in (previous_commands or {}):
        if filename not in written:
            cmd_path = commands_dir / filename
            if cmd_path.exists():
                cmd_path.unlink()

    return hashes


# ---------------------------------------------------------------------------
# Lock writer
# ---------------------------------------------------------------------------

def _write_lock(
    repo_root: Path,
    pack_dir: Path,
    manifest: dict,
    exposed: Set[str],
    skill_hashes: Dict[str, Dict[str, str]],
    command_hashes: Dict[str, str],
    agents_hash: str,
) -> dict:
    """Write .illuminate/cursor-lock.json."""
    lock_dir = repo_root / _LOCK_DIR
    lock_dir.mkdir(parents=True, exist_ok=True)

    pack_hash = hash_directory(pack_dir)

    skill_entries = [
        {
            "name": name,
            "id": f"illuminate.{name}",
            "files": file_hashes,
        }
        for name, file_hashes in skill_hashes.items()
    ]

    managed_artifacts = [
        "AGENTS.md",
        *[
            f"{_SKILLS_DIR}/{entry['name']}/{rel}"
            for entry in skill_entries
            for rel in entry["files"]
        ],
        *[f"{_COMMANDS_DIR}/{name}" for name in command_hashes],
    ]

    lock = build_lock_envelope(
        harness="cursor",
        pack={
            "id": manifest.get("id", "?"),
            "version": manifest.get("version", "?"),
            "hash": lock_hash(pack_hash),
        },
        target={"path": str(repo_root)},
        selection={"skills": sorted(exposed)},
        managed_artifacts=managed_artifacts,
        capabilities={
            "permissions": "declarative-only",
            "commands": "beta",
        },
    )
    lock.update({
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "exposed_skills": sorted(exposed),
        "skills": skill_entries,
        "commands": command_hashes,
        "agents_md_hash": agents_hash,
    })

    lock_path = lock_dir / _LOCK_FILE
    with open(lock_path, "w", encoding="utf-8") as f:
        json.dump(lock, f, indent=2, ensure_ascii=False)
        f.write("\n")

    return lock


# ---------------------------------------------------------------------------
# Main sync entry point
# ---------------------------------------------------------------------------

def sync_cursor(
    pack_dir: Path,
    repo_root: Path,
    skill_filter: Optional[List[str]] = None,
) -> dict:
    """Synchronize Illuminate Pack into a target repository for Cursor.

    Steps:
      1. Validate pack.
      2. Resolve exposed skills via the shared resolver (filter + alias +
         conflict checks).
      3. Sync .cursor/skills/ (pre-flight collision check, lock-owned).
      4. Sync .cursor/commands/ (beta, doc-related skill shortcuts).
      5. Merge AGENTS.md illuminate block.
      6. Write .illuminate/cursor-lock.json.

    Returns a summary dict.
    """
    pack_dir = Path(pack_dir).resolve()
    repo_root = Path(repo_root).resolve()

    # 1. Validate
    ok, errors = validate_pack(pack_dir)
    if not ok:
        raise ValueError("Pack validation failed:\n" + "\n".join(errors))

    # 2. Resolve through the single shared resolution entry
    resolved = resolve_pack(pack_dir, str(repo_root), skill_filter)
    manifest = resolved["manifest"]
    exposed = set(resolved["skills"]["exposed"])

    # 3. Sync skills (pre-flight collision check is built into the shared
    #    helper; fails closed before any repo modification)
    lock = _load_lock(repo_root)
    managed_skills = _managed_skills(lock)
    skill_hashes = sync_managed_skill_tree(
        pack_dir,
        repo_root / _SKILLS_DIR,
        manifest,
        exposed,
        managed_skills,
    )

    # 4. Sync commands (beta); stale commands from a previous lock are removed
    command_hashes = _sync_commands(repo_root, exposed, lock.get("commands"))

    # 5. Merge AGENTS.md
    agents_path = repo_root / "AGENTS.md"
    block_text = build_agents_block(pack_dir, manifest, exposed)
    new_content, agents_modified = merge_block(agents_path, block_text)
    agents_path.write_text(new_content, encoding="utf-8")
    agents_hash = hash_file(agents_path)

    # 6. Write lock
    _write_lock(
        repo_root,
        pack_dir,
        manifest,
        exposed,
        skill_hashes,
        command_hashes,
        agents_hash,
    )

    return {
        "pack_id": manifest.get("id", "?"),
        "pack_version": manifest.get("version", "?"),
        "exposed_skills": sorted(exposed),
        "skills_copied": len(skill_hashes),
        "commands_copied": len(command_hashes),
        "agents_modified": agents_modified,
    }


# ---------------------------------------------------------------------------
# Check
# ---------------------------------------------------------------------------

def check_sync(pack_dir: Path, repo_root: Path) -> Tuple[bool, List[str]]:
    """Verify the Cursor sync is current and consistent."""
    issues: List[str] = []
    pack_dir = Path(pack_dir).resolve()
    repo_root = Path(repo_root).resolve()

    lock_path = repo_root / _LOCK_DIR / _LOCK_FILE
    if not lock_path.exists():
        return False, ["cursor-lock.json not found — run 'illuminate sync cursor'"]

    lock = json.loads(lock_path.read_text(encoding="utf-8"))

    # Verify source pack unchanged
    current_pack_hash = lock_hash(hash_directory(pack_dir))
    if lock.get("pack", {}).get("hash") != current_pack_hash:
        issues.append("Pack source changed — run sync again")

    # Check AGENTS.md block + hash
    agents_path = repo_root / "AGENTS.md"
    if not agents_path.exists():
        issues.append("AGENTS.md not found")
    else:
        content = agents_path.read_text(encoding="utf-8")
        if _BEGIN_MARKER not in content:
            issues.append("AGENTS.md missing illuminate block markers")
        if lock.get("agents_md_hash"):
            actual = hash_file(agents_path)
            if actual != lock["agents_md_hash"]:
                issues.append("AGENTS.md hash mismatch — run sync again")

    # Check skills via the shared helper
    check_managed_file_hashes(
        repo_root,
        _SKILLS_DIR,
        lock.get("skills", []),
        issues,
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

    return (len(issues) == 0), issues


# ---------------------------------------------------------------------------
# Clean
# ---------------------------------------------------------------------------

def clean_sync(repo_root: Path) -> dict:
    """Remove all Illuminate-synced artifacts from a repository.

    Removes:
      - .cursor/skills/ entries recorded in lock
      - .cursor/commands/ entries recorded in lock
      - AGENTS.md illuminate block
      - .illuminate/cursor-lock.json
      - empty .cursor/skills/ and .cursor/ directories (best-effort)

    Does NOT remove project-owned .cursor content.
    """
    repo_root = Path(repo_root).resolve()
    removed = []

    lock = _load_lock(repo_root)

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

    # Remove AGENTS.md block
    agents_path = repo_root / "AGENTS.md"
    if agents_path.exists():
        content = agents_path.read_text(encoding="utf-8")
        new_content = remove_block(content)
        if new_content != content:
            agents_path.write_text(new_content, encoding="utf-8")
            removed.append("AGENTS.md illuminate block")

    # Remove lock
    lock_path = repo_root / _LOCK_DIR / _LOCK_FILE
    if lock_path.exists():
        lock_path.unlink()
        removed.append(f"{_LOCK_DIR}/{_LOCK_FILE}")

    # Best-effort cleanup of empty .cursor subdirs up to the repo root
    skills_dir = repo_root / _SKILLS_DIR
    if skills_dir.exists():
        removed.extend(remove_empty_parent_dirs(skills_dir, repo_root))
    commands_dir = repo_root / _COMMANDS_DIR
    if commands_dir.exists():
        removed.extend(remove_empty_parent_dirs(commands_dir, repo_root))

    return {"removed_artifacts": removed}
