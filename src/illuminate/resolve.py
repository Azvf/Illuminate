"""Resolve a pack into a mount plan: which policies, skills, and files to mount."""

import json
import uuid
from pathlib import Path
from typing import List, Dict

from .manifest import (
    load_pack_manifest,
    load_policy_index,
    load_skill_contracts,
    get_skill_dirs,
    get_policy_files,
    get_reference_files,
)


def create_mount_plan(
    pack_dir: Path,
    repo: str,
    harness: str = "claude-code",
    skill_filter: List[str] = None,
) -> dict:
    """Create a mount plan from a pack directory.

    Args:
        pack_dir: Path to the pack root (containing pack.json).
        repo: Target repository path.
        harness: Target harness name.
        skill_filter: Optional list of skill ids to expose. If None, all non-alias skills are exposed.
    """
    manifest = load_pack_manifest(pack_dir)
    policy_index = load_policy_index(pack_dir, manifest)
    contracts = load_skill_contracts(pack_dir, manifest)

    # Determine exposed skills
    if skill_filter is None:
        exposed = [
            c["id"] for c in contracts
            if c.get("kind", "skill") != "alias"
        ]
    else:
        exposed = skill_filter

    # Collect policy ids in priority order
    policies = sorted(
        policy_index.get("policies", []),
        key=lambda p: p.get("priority", 0),
        reverse=True,
    )
    policy_ids = [p["id"] for p in policies]

    plan = {
        "schema_version": 1,
        "session_id": str(uuid.uuid4()),
        "repo": str(repo),
        "harness": harness,
        "packs": [
            {
                "id": manifest["id"],
                "version": manifest["version"],
            }
        ],
        "policies": policy_ids,
        "skills": {
            "exposed": exposed,
        },
    }

    return plan


def resolve_file_list(pack_dir: Path, mount_plan: dict) -> List[Dict[str, str]]:
    """Resolve the complete list of files to mount for a plan.

    Returns a list of {source, dest} dicts where source is the absolute path
    in the pack and dest is the relative path in the session mount.
    """
    manifest = load_pack_manifest(pack_dir)
    policy_index = load_policy_index(pack_dir, manifest)
    contracts = load_skill_contracts(pack_dir, manifest)

    files: List[Dict[str, str]] = []

    # Policy files
    for policy in policy_index.get("policies", []):
        src = pack_dir / "policies" / policy["path"]
        if src.exists():
            files.append({
                "source": str(src),
                "dest": f"policies/{policy['path']}",
            })

    # Skill files (SKILL.md + contract.json + any references/ subdirs)
    for entry in manifest.get("skills", []):
        skill_dir = pack_dir / entry["dir"]
        if not skill_dir.exists():
            continue
        for file_path in sorted(skill_dir.rglob("*")):
            if file_path.is_file():
                rel = file_path.relative_to(pack_dir)
                files.append({
                    "source": str(file_path),
                    "dest": f".claude/skills/{entry['dir'].split('/')[-1]}/{file_path.relative_to(skill_dir)}",
                })

    # Reference files
    for ref_entry in manifest.get("references", []):
        src = pack_dir / ref_entry["path"]
        if src.exists():
            files.append({
                "source": str(src),
                "dest": f"references/{ref_entry['path']}",
            })

    # Evidence config
    evidence = manifest.get("evidence", {})
    for key in ("config", "overlay_example"):
        rel = evidence.get(key)
        if rel:
            src = pack_dir / rel
            if src.exists():
                files.append({
                    "source": str(src),
                    "dest": f"evidence/{rel}",
                })

    return files
