"""Cursor sync: synchronize Illuminate Pack into a target repository for Cursor.

Generates:
  .cursor/rules/illuminate/core.mdc   (Illuminate rules file, Cursor format)
  .cursor/skills/<name>/              (selected skills, managed via lock ownership)
  .cursor/commands/<name>.md          (doc-related skill shortcuts, beta)
  .illuminate/cursor-lock.json        (sync manifest with hashes)

Notes:
  - Cursor owns a dedicated rules file (`.cursor/rules/illuminate/core.mdc`)
    and does NOT manage the root AGENTS.md by default. This keeps Cursor's
    skill selection independent from the Codex/CodeBuddy AGENTS.md block, so
    different harnesses choosing different skills do not overwrite each other.
  - `agents_compat=True` restores the legacy behaviour of merging into the root
    AGENTS.md block, for projects that must share AGENTS.md with the Codex CLI.
    The chosen mode is recorded in the lock (`agents_compat`), so check/clean
    follow the same path that sync used.
  - `.cursor/commands` is in beta: commands are only registered, never
    executed, and the capability is marked "beta" in the lock.
  - Permissions are declarative-only: no executable policy is generated.
  - The adapter does NOT generate `.cursor/cli.json` or `.agents/skills`, and
    it does NOT rewrite SKILL.md bodies for Cursor (skills are copied verbatim).

Does NOT modify project content outside Illuminate-managed paths.
Does NOT delete project-owned skills/commands.
"""

import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from .command_catalog import build_command_catalog
from .sync_shared import (
    apply_knowledge_map,
    build_agents_block,
    check_knowledge_map,
    check_managed_file_hashes,
    ensure_writable,
    other_harness_declares_map,
    preflight_knowledge_map,
    preflight_managed_command_tree,
    preflight_managed_skill_tree,
    remove_empty_parent_dirs,
    sync_managed_command_tree,
    sync_managed_skill_tree,
)
from .hashutil import hash_file, hash_directory, hash_string, lock_hash
from .lockfile import build_lock_envelope
from .managed_block import (
    BEGIN_MARKER as _BEGIN_MARKER,
    count_blocks,
    hash_block_text,
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
_RULES_DIR = ".cursor/rules/illuminate"
_RULES_FILE = "core.mdc"
_RULES_REL = f"{_RULES_DIR}/{_RULES_FILE}"
_LOCK_DIR = ".illuminate"
_LOCK_FILE = "cursor-lock.json"


# ---------------------------------------------------------------------------
# Rules file (Cursor .mdc)
# ---------------------------------------------------------------------------

def _build_rules_mdc(block_text: str, description: str) -> str:
    """Wrap the shared Illuminate block body in a Cursor `.mdc` frontmatter.

    Uses `description` plus `alwaysApply: true`: the governance policy must
    reliably enter every Cursor context on each load, not only when a glob
    matches. `alwaysApply` is what guarantees this unconditional loading.
    """
    return (
        f"---\ndescription: {description}\nalwaysApply: true\n---\n\n"
        f"{block_text.strip()}\n"
    )


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

    Uses the shared command syncer: only files recorded as previously managed
    are replaced or removed, so a project-owned command sharing a name fails
    closed instead of being overwritten.

    Returns {filename: sha256}.
    """
    return sync_managed_command_tree(
        repo_root / _COMMANDS_DIR,
        _desired_commands(exposed),
        previous_commands or {},
    )


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


def _preflight_target_paths(repo_root: Path, lock: dict, agents_compat: bool) -> List[str]:
    """Verify every target Illuminate will actually write/delete under
    repo_root is writable (or creatable), including an already-existing target
    file itself (not just its parent directory). Fails closed before any write.

    The probe set is computed from the previous mode (recorded in ``lock``)
    and the target mode ``agents_compat``, so only paths this run really
    touches are probed. AGENTS.md is probed exactly when it is written
    (compat mode) or its old block is removed (switching compat -> default);
    core.mdc is probed exactly when it is written (default mode) or the old
    one is removed (switching default -> compat). An ordinary default sync
    therefore never probes a read-only AGENTS.md that it will not touch.

    The lock file itself is probed (not just its directory): on a second sync
    or a mode switch the lock already exists and is written in Phase 2, so a
    read-only lock must fail closed before any write. On a first sync the lock
    does not yet exist, so the probe falls back to the nearest existing
    ancestor (_LOCK_DIR)."""
    old_compat = bool(lock.get("agents_compat", False))
    artifacts = [
        _SKILLS_DIR,
        _COMMANDS_DIR,
        _LOCK_DIR,
        f"{_LOCK_DIR}/{_LOCK_FILE}",
    ]
    # AGENTS.md is written in compat mode and edited when its old block is
    # retired (compat -> default switch).
    if agents_compat or old_compat:
        artifacts.append("AGENTS.md")
    # core.mdc is written in default mode and removed when the old one is
    # retired (default -> compat switch).
    if not agents_compat or (agents_compat and not old_compat):
        artifacts.append(_RULES_REL)
    for rel in artifacts:
        ensure_writable(repo_root / rel)
    return artifacts


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
    agents_compat: bool,
    rules_artifact_hash: str,
    knowledge_map_hash: Optional[str] = None,
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

    rules_artifact = "AGENTS.md" if agents_compat else _RULES_REL
    managed_artifacts = [
        rules_artifact,
        *[
            f"{_SKILLS_DIR}/{entry['name']}/{rel}"
            for entry in skill_entries
            for rel in entry["files"]
        ],
        *[f"{_COMMANDS_DIR}/{name}" for name in command_hashes],
    ]
    if knowledge_map_hash is not None:
        managed_artifacts.append(f"{_LOCK_DIR}/knowledge-map.md")

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
        "agents_compat": agents_compat,
    })
    if agents_compat:
        lock["agents_md_hash"] = rules_artifact_hash
    else:
        lock["rules_md_hash"] = rules_artifact_hash
    if knowledge_map_hash is not None:
        lock["knowledge_map_hash"] = knowledge_map_hash

    lock_path = lock_dir / _LOCK_FILE
    with open(lock_path, "w", encoding="utf-8") as f:
        json.dump(lock, f, indent=2, ensure_ascii=False)
        f.write("\n")

    return lock


# ---------------------------------------------------------------------------
# Mode-switch cleanup
# ---------------------------------------------------------------------------

def _old_rules_mdc_state(repo_root: Path, lock: dict) -> str:
    """Classify the old core.mdc against the lock: 'clean' (unmodified, or no
    ownership record), 'conflict' (modified but still Illuminate-owned),
    'taken_over' (user replaced/removed the file entirely)."""
    rules_path = repo_root / _RULES_DIR / _RULES_FILE
    prev_hash = lock.get("rules_md_hash")
    if not rules_path.exists() or not prev_hash:
        return "clean"
    if hash_file(rules_path) == prev_hash:
        return "clean"
    if _BEGIN_MARKER in rules_path.read_text(encoding="utf-8"):
        return "conflict"
    return "taken_over"


def _old_agents_block_state(repo_root: Path, lock: dict) -> str:
    """Classify the old AGENTS.md illuminate block against the lock:
    'clean' (block hash matches, or no ownership record), 'conflict'
    (block modified but still present), 'taken_over' (no block found)."""
    prev_hash = lock.get("agents_md_hash")
    if not prev_hash:
        return "clean"
    agents_path = repo_root / "AGENTS.md"
    if not agents_path.exists():
        return "taken_over"
    content = agents_path.read_text(encoding="utf-8")
    # More than one illuminate block means the repository carries a duplicate
    # rule source. Never try to retire just the first block and leave the
    # second behind — that is exactly the double-rule-source defect. Abort so
    # the user can remove the duplicate by hand.
    if count_blocks(content) > 1:
        return "conflict"
    current_block_hash = hash_block_text(content)
    if current_block_hash is None:
        return "taken_over"
    if current_block_hash == prev_hash:
        return "clean"
    return "conflict"


def _preflight_mode_switch(repo_root: Path, lock: dict, agents_compat: bool) -> None:
    """Fail before any write if a mode switch cannot cleanly retire the old
    artifact.

    Retiring an old artifact that was modified but still carries Illuminate
    content would otherwise leave two live rule sources (the new mode plus the
    stale old one). Raising here, before the new mode is written, guarantees a
    switch either completes fully or leaves the repository untouched."""
    old_compat = bool(lock.get("agents_compat", False))
    if old_compat == agents_compat:
        return  # no switch: the old artifact is not being retired
    if agents_compat:
        # default -> compat: retiring the old core.mdc
        if _old_rules_mdc_state(repo_root, lock) == "conflict":
            raise ValueError(
                "Cannot switch to agents_compat: the existing core.mdc was "
                "modified but still contains Illuminate content. Remove or "
                "resolve the illuminate block before switching."
            )
    else:
        # compat -> default: retiring the old AGENTS.md block
        if _old_agents_block_state(repo_root, lock) == "conflict":
            raise ValueError(
                "Cannot switch to default mode: the existing AGENTS.md "
                "illuminate block was modified but still contains Illuminate "
                "content. Remove or resolve the block before switching."
            )


def _remove_old_rules_mdc(repo_root: Path, lock: dict) -> None:
    """Remove the default-mode core.mdc when switching to compat mode.

    Only acts when the lock records a prior core.mdc (rules_md_hash);
    otherwise core.mdc is never touched. Among recorded files, only one whose
    hash matches the lock is deleted. A file modified but still containing
    Illuminate content aborts the switch (conflict); a file the user replaced
    or removed is left alone (taken over).
    """
    if not lock.get("rules_md_hash"):
        return
    state = _old_rules_mdc_state(repo_root, lock)
    if state == "conflict":
        raise ValueError(
            f"Cannot remove old rules file {_RULES_REL}: it was modified but "
            "still contains Illuminate content"
        )
    if state == "taken_over":
        return
    rules_path = repo_root / _RULES_DIR / _RULES_FILE
    if rules_path.exists():
        try:
            rules_path.unlink()
        except OSError:
            raise ValueError(f"Cannot remove old rules file: {_RULES_REL}")


def _remove_old_agents_block(repo_root: Path, lock: dict) -> None:
    """Remove the compat-mode AGENTS.md block when switching to default mode.

    Only acts when the lock records a prior AGENTS.md block (agents_md_hash);
    otherwise AGENTS.md is never touched. Among recorded blocks, only one whose
    current block hash matches the lock is removed (unmodified since we wrote
    it). A block modified but still present aborts the switch (conflict); a
    block the user removed is left alone (taken over). User content outside
    the block never blocks removal."""
    if not lock.get("agents_md_hash"):
        return
    state = _old_agents_block_state(repo_root, lock)
    if state == "conflict":
        raise ValueError(
            "Cannot remove old AGENTS.md illuminate block: it was modified "
            "but still contains Illuminate content"
        )
    if state == "taken_over":
        return
    agents_path = repo_root / "AGENTS.md"
    content = agents_path.read_text(encoding="utf-8")
    new_content = remove_block(content)
    if new_content != content:
        agents_path.write_text(new_content, encoding="utf-8")


# ---------------------------------------------------------------------------
# Main sync entry point
# ---------------------------------------------------------------------------

def sync_cursor(
    pack_dir: Path,
    repo_root: Path,
    skill_filter: Optional[List[str]] = None,
    agents_compat: bool = False,
) -> dict:
    """Synchronize Illuminate Pack into a target repository for Cursor.

    Steps:
      1. Validate pack.
      2. Resolve exposed skills via the shared resolver (filter + alias +
         conflict checks).
      3. Phase 1 preflight: run every collision / writability check
         (skills, commands, lock) before writing anything.
      4. Phase 2 write: sync .cursor/skills/, sync .cursor/commands/ (beta),
         write the Cursor rules artifact (`.cursor/rules/illuminate/core.mdc`,
         or the root AGENTS.md block when `agents_compat=True`), and write
         .illuminate/cursor-lock.json.

    `agents_compat=True` merges into the root AGENTS.md instead of writing
    `.cursor/rules/illuminate/core.mdc`; use it only for projects that must
    share AGENTS.md with the Codex CLI.

    Any preflight failure raises ValueError with no file written.

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

    lock = _load_lock(repo_root)
    managed_skills = _managed_skills(lock)
    previous_commands = lock.get("commands")

    # 3. Phase 1 — preflight: run every collision / writability check before
    #    touching the repo, so any failure leaves no partial write behind.
    preflight_managed_skill_tree(
        repo_root / _SKILLS_DIR, manifest, exposed, managed_skills
    )
    desired_commands = _desired_commands(exposed)
    preflight_managed_command_tree(
        repo_root / _COMMANDS_DIR, desired_commands, previous_commands or {}
    )
    _preflight_target_paths(repo_root, lock, agents_compat)
    _preflight_mode_switch(repo_root, lock, agents_compat)
    map_path = repo_root / _LOCK_DIR / "knowledge-map.md"
    map_text = preflight_knowledge_map(repo_root, map_path)

    # 4. Phase 2 — write. The rules artifact is handled as a mode transaction:
    #    write the new-mode artifact first, then clean the old-mode artifact.
    #    This ordering guarantees the new mode is never left half-written:
    #    if old-artifact cleanup fails, the new mode is already effective and
    #    we raise to surface the incomplete cleanup rather than risk leaving
    #    both modes' artifacts unowned.
    skill_hashes = sync_managed_skill_tree(
        pack_dir,
        repo_root / _SKILLS_DIR,
        manifest,
        exposed,
        managed_skills,
    )
    command_hashes = _sync_commands(repo_root, exposed, previous_commands)

    # Write the rules artifact (dedicated .mdc, or AGENTS.md in compat mode).
    block_text = build_agents_block(pack_dir, manifest, exposed)
    if agents_compat:
        # New mode = AGENTS.md block. Write it, then remove the old core.mdc.
        agents_path = repo_root / "AGENTS.md"
        new_content, modified = merge_block(agents_path, block_text)
        agents_path.write_text(new_content, encoding="utf-8")
        # Record the block hash, not the whole-file hash, so user content
        # outside the markers can change without breaking ownership tracking.
        rules_artifact_hash = hash_block_text(new_content)
        _remove_old_rules_mdc(repo_root, lock)
    else:
        # New mode = core.mdc. Write it, then remove the old AGENTS.md block
        # we previously wrote, but only when its block hash still matches the
        # lock (never delete a block that Codex or the user has modified).
        rules_path = repo_root / _RULES_DIR / _RULES_FILE
        rules_path.parent.mkdir(parents=True, exist_ok=True)
        new_mdc = _build_rules_mdc(block_text, "Illuminate governance rules")
        old_mdc = rules_path.read_text(encoding="utf-8") if rules_path.exists() else None
        modified = (new_mdc != old_mdc)
        rules_path.write_text(new_mdc, encoding="utf-8")
        rules_artifact_hash = hash_file(rules_path)
        _remove_old_agents_block(repo_root, lock)

    # Write or delete the Knowledge Map (preflighted in Phase 1) before the
    # lock. If there is no indexable knowledge, the stale map is removed and
    # no hash is recorded. The lock stores the hash of the canonical map text,
    # so check_sync can compare against a rebuilt text hash regardless of the
    # platform line endings of the on-disk file.
    apply_knowledge_map(map_path, map_text)
    knowledge_map_hash = hash_string(map_text) if map_text is not None else None

    # Write lock
    _write_lock(
        repo_root,
        pack_dir,
        manifest,
        exposed,
        skill_hashes,
        command_hashes,
        agents_compat,
        rules_artifact_hash,
        knowledge_map_hash,
    )

    return {
        "pack_id": manifest.get("id", "?"),
        "pack_version": manifest.get("version", "?"),
        "exposed_skills": sorted(exposed),
        "skills_copied": len(skill_hashes),
        "commands_copied": len(command_hashes),
        "rules_modified": modified,
        "agents_compat": agents_compat,
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

    agents_compat = lock.get("agents_compat", False)

    # Check the rules artifact (dedicated .mdc, or AGENTS.md in compat mode).
    if agents_compat:
        agents_path = repo_root / "AGENTS.md"
        if not agents_path.exists():
            issues.append("AGENTS.md not found")
        else:
            content = agents_path.read_text(encoding="utf-8")
            if _BEGIN_MARKER not in content:
                issues.append("AGENTS.md missing illuminate block markers")
            if lock.get("agents_md_hash"):
                actual = hash_block_text(content)
                if actual != lock["agents_md_hash"]:
                    issues.append("AGENTS.md block hash mismatch — run sync again")
    else:
        rules_path = repo_root / _RULES_DIR / _RULES_FILE
        if not rules_path.exists():
            issues.append(f"{_RULES_REL} not found — run sync again")
        elif lock.get("rules_md_hash"):
            actual = hash_file(rules_path)
            if actual != lock["rules_md_hash"]:
                issues.append(f"{_RULES_REL} hash mismatch — run sync again")

    # Check the Knowledge Map against the lock's expected state (present or
    # absent). check is read-only: the shared helper rebuilds the map text and
    # compares its hash to the lock record, so a doc added/moved/removed after
    # sync is flagged even though the on-disk map file was not regenerated.
    expected_map_hash = lock.get("knowledge_map_hash")
    check_knowledge_map(repo_root, expected_map_hash, f"{_LOCK_DIR}/knowledge-map.md", issues)

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
# Doctor (read-only diagnostic)
# ---------------------------------------------------------------------------

def doctor_sync(repo_root: Path) -> dict:
    """Diagnose the Cursor sync without modifying any file.

    Returns a dict describing: whether a lock exists and is well-formed, which
    sync mode the lock records, whether the rules artifact exists and matches
    its lock hash, whether lock-recorded skills/commands are complete, and any
    stale (lock-recorded but now absent) artifacts. Never writes to disk.
    """
    repo_root = Path(repo_root).resolve()
    lock_path = repo_root / _LOCK_DIR / _LOCK_FILE
    report: dict = {
        "lock_exists": lock_path.exists(),
        "lock_errors": [],
        "mode": None,
        "rules": None,
        "skills": {"missing": [], "hash_mismatch": []},
        "commands": {"missing": [], "hash_mismatch": []},
        "stale": [],
        "errors": [],
    }

    if not lock_path.exists():
        report["errors"].append("cursor-lock.json not found — run 'illuminate sync cursor'")
        return report

    try:
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        report["lock_errors"].append("cursor-lock.json is not valid JSON")
        return report

    # Structural field completeness
    required = ["pack", "target", "selection", "managed_artifacts", "skills", "commands"]
    for field in required:
        if field not in lock:
            report["lock_errors"].append(f"lock missing field: {field}")
    if not isinstance(lock.get("skills"), list):
        report["lock_errors"].append("lock 'skills' is not a list")
    if not isinstance(lock.get("commands"), dict):
        report["lock_errors"].append("lock 'commands' is not a dict")

    agents_compat = bool(lock.get("agents_compat", False))
    report["mode"] = "agents" if agents_compat else "mdc"

    # Rules artifact
    if agents_compat:
        rules_path = repo_root / "AGENTS.md"
        key = "agents_md_hash"
        label = "AGENTS.md"
    else:
        rules_path = repo_root / _RULES_DIR / _RULES_FILE
        key = "rules_md_hash"
        label = _RULES_REL
    if not rules_path.exists():
        report["rules"] = {"path": label, "exists": False, "hash_matches": False, "always_apply": None}
    else:
        expected = lock.get(key)
        always_apply = None  # AGENTS.md is always loaded, so N/A in compat mode
        if agents_compat:
            # Compare the block hash, matching check_sync, so user content
            # outside the markers never causes a false mismatch.
            content = rules_path.read_text(encoding="utf-8")
            actual = hash_block_text(content)
        else:
            actual = hash_file(rules_path)
            text = rules_path.read_text(encoding="utf-8")
            always_apply = bool(re.search(r"(?m)^alwaysApply:\s*true", text))
        report["rules"] = {
            "path": label,
            "exists": True,
            "hash_matches": (expected == actual),
            "always_apply": always_apply,
        }
        if (
            not agents_compat
            and report["rules"]["always_apply"] is False
        ):
            report["errors"].append(
                f"{_RULES_REL} missing alwaysApply: true — Cursor will not "
                "auto-load governance policy"
            )

    # Skills
    for skill_entry in lock.get("skills", []):
        skill_name = skill_entry.get("name")
        for rel, expected_hash in skill_entry.get("files", {}).items():
            fpath = repo_root / _SKILLS_DIR / skill_name / rel
            if not fpath.exists():
                report["skills"]["missing"].append(f"{_SKILLS_DIR}/{skill_name}/{rel}")
            elif hash_file(fpath) != expected_hash:
                report["skills"]["hash_mismatch"].append(f"{_SKILLS_DIR}/{skill_name}/{rel}")

    # Commands
    for filename, expected_hash in lock.get("commands", {}).items():
        fpath = repo_root / _COMMANDS_DIR / filename
        if not fpath.exists():
            report["commands"]["missing"].append(f"{_COMMANDS_DIR}/{filename}")
        elif hash_file(fpath) != expected_hash:
            report["commands"]["hash_mismatch"].append(f"{_COMMANDS_DIR}/{filename}")

    # Stale: lock-recorded artifacts no longer on disk (rules artifact counted
    # above; skills/commands already reported). Report any managed_artifacts
    # entry that is absent, since that means a partial deletion happened.
    for rel in lock.get("managed_artifacts", []):
        if not (repo_root / rel).exists():
            report["stale"].append(rel)

    return report


# ---------------------------------------------------------------------------
# Clean
# ---------------------------------------------------------------------------

def clean_sync(repo_root: Path) -> dict:
    """Remove all Illuminate-synced artifacts from a repository.

    Removes:
      - .cursor/rules/illuminate/ (default mode) or the root AGENTS.md
        illuminate block (agents_compat mode, recorded in lock)
      - .cursor/skills/ entries recorded in lock
      - .cursor/commands/ entries recorded in lock
      - .illuminate/cursor-lock.json
      - empty .cursor/skills/ and .cursor/ directories (best-effort)

    In default (.mdc) mode the root AGENTS.md is normally never touched, so
    cleaning Cursor cannot break another harness's AGENTS.md block. The one
    exception: when the lock records a previous agents_compat run (an
    ``agents_md_hash``), the AGENTS.md block we wrote is removed too — but only
    after verifying the current AGENTS.md is byte-identical to that hash, so a
    block modified or written by Codex or the user is never deleted.

    Without a lock, clean cannot know what is managed: the rules directory is
    left untouched along with skills/commands.

    Does NOT remove project-owned .cursor content.
    """
    repo_root = Path(repo_root).resolve()
    removed = []

    lock = _load_lock(repo_root)
    lock_path = repo_root / _LOCK_DIR / _LOCK_FILE
    has_lock = lock_path.exists()
    agents_compat = bool(lock.get("agents_compat", False))

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

    # Remove the rules artifact. In .mdc mode this is the dedicated rules
    # directory; in compat mode it is the AGENTS.md illuminate block. Without
    # a lock we cannot know what is managed, so the rules directory is left
    # untouched (consistent with skills/commands).
    if agents_compat:
        agents_path = repo_root / "AGENTS.md"
        # Fail-safe: only remove the block we wrote when its current block hash
        # matches the lock-recorded hash. User content outside the block does
        # not block removal; a block whose hash no longer matches (modified by
        # Codex or the user) is never deleted. Without a recorded hash we
        # cannot prove ownership, so conservatively skip deletion.
        prev_hash = lock.get("agents_md_hash")
        if prev_hash and agents_path.exists():
            content = agents_path.read_text(encoding="utf-8")
            if hash_block_text(content) == prev_hash:
                new_content = remove_block(content)
                if new_content != content:
                    agents_path.write_text(new_content, encoding="utf-8")
                    removed.append("AGENTS.md illuminate block")
    elif has_lock:
        rules_dir = repo_root / _RULES_DIR
        if rules_dir.exists():
            shutil.rmtree(rules_dir)
            removed.append(str(_RULES_DIR))
        # A lock that records a previous agents_compat run (e.g. before the
        # mode was switched to default) may still own an AGENTS.md block.
        # Remove it only if its block hash matches the lock, so a block
        # written/modified by Codex or the user is never deleted.
        prev_agents_hash = lock.get("agents_md_hash")
        if prev_agents_hash:
            agents_path = repo_root / "AGENTS.md"
            if agents_path.exists():
                content = agents_path.read_text(encoding="utf-8")
                if hash_block_text(content) == prev_agents_hash:
                    new_content = remove_block(content)
                    if new_content != content:
                        agents_path.write_text(new_content, encoding="utf-8")
                        removed.append("AGENTS.md illuminate block")

    # Remove the knowledge map when the lock records a hash AND no other
    # harness still owns it. The shared map may be written by cursor/codex/
    # codebuddy together, so cleaning one harness must not delete a map that
    # another harness still references.
    if lock.get("knowledge_map_hash") and not other_harness_declares_map(repo_root, "cursor"):
        map_path = repo_root / _LOCK_DIR / "knowledge-map.md"
        if map_path.exists():
            map_path.unlink()
            removed.append(f"{_LOCK_DIR}/knowledge-map.md")

    # Remove lock
    lock_path = repo_root / _LOCK_DIR / _LOCK_FILE
    if lock_path.exists():
        lock_path.unlink()
        removed.append(f"{_LOCK_DIR}/{_LOCK_FILE}")

    # Best-effort cleanup of empty .cursor subdirs up to the repo root. In
    # default mode the rules leaf was already removed by rmtree above; prune
    # from its parent (.cursor/rules) so empty ancestors are cleaned too.
    for rel in (_SKILLS_DIR, _COMMANDS_DIR, _RULES_DIR):
        subdir = repo_root / rel
        if subdir.exists():
            removed.extend(remove_empty_parent_dirs(subdir, repo_root))
    rules_parent = repo_root / Path(_RULES_DIR).parent
    if rules_parent.exists():
        removed.extend(remove_empty_parent_dirs(rules_parent, repo_root))

    return {"removed_artifacts": removed}
