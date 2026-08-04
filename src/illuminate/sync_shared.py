"""Shared deterministic logic for harness sync adapters (Codex, CodeBuddy, ...).

These functions are the single source of truth for skill-tree sync, managed
file hash checks, empty-directory cleanup, and AGENTS.md block construction.
Behavior changes here must keep every harness adapter consistent — do not
special-case one adapter.
"""

import shutil
from pathlib import Path
from typing import Dict, List, Set

from .hashutil import hash_file
from .manifest import load_policy_index
from .managed_block import END_MARKER, make_begin_marker


def sync_managed_skill_tree(
    pack_dir: Path,
    dest_skills_dir: Path,
    manifest: dict,
    exposed: Set[str],
    managed_skills: Set[str],
) -> Dict[str, Dict[str, str]]:
    """Sync selected skills from the pack into ``dest_skills_dir``.

    Only skills recorded as Illuminate-managed are replaced or removed. A
    project-owned directory that shares a skill's name fails closed with
    ValueError before any write.

    Returns {skill_name: {file_rel: sha256}}.
    """
    # Pre-flight collision check: fail closed before touching the repo, so a
    # collision leaves no partial write behind.
    for entry in manifest.get("skills", []):
        if entry["id"] not in exposed:
            continue
        skill_name = entry["dir"].split("/")[-1]
        dest_dir = dest_skills_dir / skill_name
        if dest_dir.exists() and skill_name not in managed_skills:
            raise ValueError(
                f"Cannot sync skill '{skill_name}': "
                "destination already exists and is not Illuminate-managed"
            )

    dest_skills_dir.mkdir(parents=True, exist_ok=True)

    copied: Dict[str, Dict[str, str]] = {}
    synced_names = set()

    for entry in manifest.get("skills", []):
        if entry["id"] not in exposed:
            continue

        skill_dir = pack_dir / entry["dir"]
        if not skill_dir.exists():
            continue

        skill_name = entry["dir"].split("/")[-1]
        synced_names.add(skill_name)
        dest_dir = dest_skills_dir / skill_name

        # Clean only if previously managed (handles removed content)
        if skill_name in managed_skills and dest_dir.exists():
            shutil.rmtree(dest_dir)
        dest_dir.mkdir(parents=True, exist_ok=True)

        file_hashes: Dict[str, str] = {}
        for file_path in sorted(skill_dir.rglob("*")):
            if not file_path.is_file():
                continue
            rel = file_path.relative_to(skill_dir)
            destination = dest_dir / rel
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(file_path, destination)
            file_hashes[rel.as_posix()] = hash_file(destination)

        copied[skill_name] = file_hashes

    # Remove stale managed skills no longer exposed
    for name in managed_skills:
        if name not in synced_names:
            stale_dir = dest_skills_dir / name
            if stale_dir.exists():
                shutil.rmtree(stale_dir)

    return copied


def check_managed_file_hashes(
    repo_root: Path,
    dest_skills_dir_rel: str,
    lock_skills: List[dict],
    issues: List[str],
) -> None:
    """Verify lock-recorded skill files exist with unchanged hashes.

    Appends descriptive messages to ``issues`` for missing or mismatched
    files.
    """
    for skill_entry in lock_skills:
        skill_name = skill_entry["name"]
        for rel, expected_hash in skill_entry.get("files", {}).items():
            rel_path = f"{dest_skills_dir_rel}/{skill_name}/{rel}"
            fpath = repo_root / dest_skills_dir_rel / skill_name / rel
            if not fpath.exists():
                issues.append(f"Missing skill file: {rel_path}")
            else:
                actual_hash = hash_file(fpath)
                if actual_hash != expected_hash:
                    issues.append(f"Skill hash mismatch: {rel_path}")


def remove_empty_parent_dirs(path: Path, stop_at: Path) -> List[str]:
    """Remove empty directories walking upward from ``path`` until ``stop_at``.

    ``stop_at`` itself is never removed. Returns the removed directories as
    posix-relative paths (relative to ``stop_at``).
    """
    removed = []
    current = path
    while current != stop_at:
        try:
            current.rmdir()
        except OSError:
            break
        removed.append(current.relative_to(stop_at).as_posix())
        current = current.parent
    return removed


def compile_policy_text(pack_dir: Path, manifest: dict) -> str:
    """Compile policies into compact developer instructions."""
    policy_index = load_policy_index(pack_dir, manifest)

    policies = sorted(
        policy_index.get("policies", []),
        key=lambda p: p.get("priority", 0),
        reverse=True,
    )

    lines = [
        "## Illuminate Runtime Policies",
        "",
        "These instructions apply in addition to repository AGENTS.md files.",
        "",
    ]

    for policy in policies:
        policy_path = pack_dir / "policies" / policy["path"]
        if policy_path.exists():
            content = policy_path.read_text(encoding="utf-8")
            lines.append(content)
            lines.append("")

    return "\n".join(lines)


def build_agents_block(pack_dir: Path, manifest: dict, exposed: Set[str]) -> str:
    """Build the Illuminate AGENTS.md block.

    Only includes policies; skills are discovered by harnesses via their
    skills directory.
    """
    begin = make_begin_marker(manifest)
    policy_text = compile_policy_text(pack_dir, manifest)
    exposed_list = ", ".join(sorted(exposed))
    lines = [
        begin,
        "",
        policy_text,
        "",
        f"Synchronized skills: {exposed_list}",
        "",
        END_MARKER,
    ]
    return "\n".join(lines)
