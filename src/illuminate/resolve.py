"""Resolve a pack into a mount plan: which policies, skills, and files to mount."""

import subprocess
import uuid
from pathlib import Path
from typing import List, Dict

from .manifest import (
    load_pack_manifest,
    load_policy_index,
    load_skill_contracts,
)


def _resolve_repo(repo: str) -> dict:
    """Resolve repo path and collect git identity info.

    Returns dict with at minimum {"path": "..."} plus git_root/head/remote
    when available.
    """
    repo_path = Path(repo).expanduser().resolve()
    info = {"path": str(repo_path)}
    if not repo_path.is_dir():
        return info
    try:
        git_root = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=str(repo_path), stderr=subprocess.DEVNULL, text=True
        ).strip()
        git_head = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=str(repo_path), stderr=subprocess.DEVNULL, text=True
        ).strip()
        info.update({
            "git_root": git_root,
            "head": git_head,
        })
        remote = subprocess.check_output(
            ["git", "remote", "get-url", "origin"],
            cwd=str(repo_path), stderr=subprocess.DEVNULL, text=True
        ).strip()
        info["remote"] = remote
    except Exception:
        pass
    return info


def resolve_exposed_skills(
    manifest: dict,
    contracts: list,
    skill_filter: List[str] = None,
) -> List[str]:
    """Resolve the set of skill IDs to expose from a filter.

    Single resolution entry point shared by every adapter (session mounts
    and repository syncs). Handles alias resolution, unknown-ID validation,
    deduplication, and conflict detection. Returns a list of resolved skill
    IDs in deterministic order.

    Raises:
        ValueError: If skill_filter contains unknown IDs, alias cycles,
                    alias targets that do not exist, or is empty.
    """
    # Build alias map
    alias_map = {}
    for contract in contracts:
        if contract.get("kind") == "alias":
            alias_map[contract["id"]] = contract.get("target", "")

    all_skill_ids = {entry["id"] for entry in manifest.get("skills", [])}

    if skill_filter is None:
        return [
            c["id"] for c in contracts
            if c.get("kind", "skill") != "alias"
        ]

    if not skill_filter:
        raise ValueError(
            "skill_filter must be None (expose all) or contain at least one skill ID"
        )

    # Validate filter IDs exist
    unknown = [sid for sid in skill_filter if sid not in all_skill_ids]
    if unknown:
        raise ValueError(
            f"Unknown skill ID(s) in filter: {', '.join(unknown)}"
        )

    # Resolve aliases → targets
    resolved = []
    for sid in skill_filter:
        current = sid
        visited = set()
        while current in alias_map:
            if current in visited:
                raise ValueError(
                    f"Alias cycle detected resolving '{sid}'"
                )
            visited.add(current)
            current = alias_map[current]
        resolved.append(current)

    # Validate every alias resolves to a real skill
    missing = [rid for rid in resolved if rid not in all_skill_ids]
    if missing:
        raise ValueError(
            f"Alias target(s) do not exist in pack: {', '.join(missing)}"
        )

    # Deduplicate (multiple aliases may resolve to same target)
    return list(dict.fromkeys(resolved))


def resolve_pack(
    pack_dir: Path,
    repo: str,
    skill_filter: List[str] = None,
) -> dict:
    """Resolve pack inputs into one canonical, adapter-neutral structure.

    The returned value contains the loaded manifest and contracts, policies in
    priority order, selected skills, and the pack/repository identities used by
    downstream mount or sync adapters.
    """
    pack_path = Path(pack_dir).expanduser().resolve()
    manifest = load_pack_manifest(pack_path)
    policy_index = load_policy_index(pack_path, manifest)
    contracts = load_skill_contracts(pack_path, manifest)
    policies = sorted(
        policy_index.get("policies", []),
        key=lambda policy: policy.get("priority", 0),
        reverse=True,
    )
    exposed = resolve_exposed_skills(manifest, contracts, skill_filter)

    return {
        "pack_dir": str(pack_path),
        "manifest": manifest,
        "policy_index": policy_index,
        "policies": policies,
        "contracts": contracts,
        "pack": {
            "id": manifest["id"],
            "version": manifest["version"],
        },
        "repo": _resolve_repo(repo),
        "skills": {"exposed": exposed},
    }


def create_mount_plan(
    pack_dir: Path,
    repo: str,
    skill_filter: List[str] = None,
) -> dict:
    """Create a mount plan from a pack directory.

    Args:
        pack_dir: Path to the pack root (containing pack.json).
        repo: Target repository path.
        skill_filter: Optional list of skill ids to expose.
            If None, all non-alias skills are exposed.
            Aliases are resolved to their targets.

    Raises:
        ValueError: If skill_filter contains unknown IDs or alias cycles.
    """
    resolved = resolve_pack(pack_dir, repo, skill_filter)
    policy_ids = [policy["id"] for policy in resolved["policies"]]

    plan = {
        "schema_version": 1,
        "session_id": str(uuid.uuid4()),
        "repo": resolved["repo"],
        "harness": "claude-code",
        "packs": [resolved["pack"]],
        "policies": policy_ids,
        "skills": resolved["skills"],
    }

    return plan


def resolve_file_list(
    pack_dir: Path,
    mount_plan: dict,
) -> List[Dict[str, str]]:
    """Resolve the complete list of files to mount for a plan.

    Returns a list of {source, dest, kind} dicts where:
      source: absolute path in the pack
      dest:   relative path in the session mount
      kind:   "policy" | "skill" | "reference" | "evidence"

    Only skills listed in mount_plan["skills"]["exposed"] are included.

    Args:
        pack_dir: Path to the pack root.
        mount_plan: The Claude Code mount plan dict.
    """
    manifest = load_pack_manifest(pack_dir)
    policy_index = load_policy_index(pack_dir, manifest)

    exposed = set(mount_plan["skills"]["exposed"])

    files: List[Dict[str, str]] = []

    # Policy files
    for policy in policy_index.get("policies", []):
        src = pack_dir / "policies" / policy["path"]
        if src.exists():
            files.append({
                "source": str(src),
                "dest": f"policies/{policy['path']}",
                "kind": "policy",
            })

    # Skill files — only exposed skills
    for entry in manifest.get("skills", []):
        if entry["id"] not in exposed:
            continue
        skill_dir = pack_dir / entry["dir"]
        if not skill_dir.exists():
            continue
        for file_path in sorted(skill_dir.rglob("*")):
            if file_path.is_file():
                skill_name = entry["dir"].split("/")[-1]
                rel = file_path.relative_to(skill_dir)
                files.append({
                    "source": str(file_path),
                    "dest": f".claude/skills/{skill_name}/{rel}",
                    "kind": "skill",
                })

    # Reference files
    for ref_entry in manifest.get("references", []):
        src = pack_dir / ref_entry["path"]
        if src.exists():
            files.append({
                "source": str(src),
                "dest": ref_entry["path"],
                "kind": "reference",
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
                    "dest": rel,
                    "kind": "evidence",
                })

    return files
