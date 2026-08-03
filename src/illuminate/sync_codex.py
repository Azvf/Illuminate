"""Codex sync: synchronize Illuminate Pack into a target repository for Codex App.

Generates:
  AGENTS.md                  (Illuminate policy block, merged via <!-- illuminate:... --> markers)
  .agents/skills/            (selected skills, lock-owned sync)
  .agents/skills/*/agents/openai.yaml  (App metadata for each skill)
  .illuminate/codex-lock.json         (sync manifest with hashes)

Does NOT modify user content outside <!-- illuminate:... --> markers.
"""

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from .hashutil import hash_file, hash_directory, lock_hash
from .managed_block import (
    BEGIN_MARKER as _BEGIN_MARKER,
    END_MARKER as _END_MARKER,
    make_begin_marker,
    merge_block,
    remove_block,
)
from .manifest import load_pack_manifest, load_policy_index, load_skill_contracts
from .resolve import resolve_exposed_skills
from .validate import validate_pack


def _compile_policy_text(pack_dir: Path, manifest: dict) -> str:
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


def _build_agents_block(pack_dir: Path, manifest: dict, exposed: Set[str]) -> str:
    """Build the Illuminate AGENTS.md block.

    Only includes policies; skills are discovered by Codex via .agents/skills/.
    """
    begin = make_begin_marker(manifest)
    policy_text = _compile_policy_text(pack_dir, manifest)
    exposed_list = ", ".join(sorted(exposed))
    lines = [
        begin,
        "",
        policy_text,
        "",
        f"Synchronized skills: {exposed_list}",
        "",
        _END_MARKER,
    ]
    return "\n".join(lines)


def merge_agents_block(agents_path: Path, block_text: str) -> Tuple[str, bool]:
    """Merge an Illuminate block into AGENTS.md content.

    If the block markers already exist, only the content between them is replaced.
    Otherwise, the block is appended at the end.

    Returns (new_content, was_modified).
    """
    return merge_block(agents_path, block_text)


# ---------------------------------------------------------------------------
# Skill sync helpers
# ---------------------------------------------------------------------------

def _sync_skills(
    pack_dir: Path,
    repo_root: Path,
    manifest: dict,
    exposed: Set[str],
) -> Dict[str, List[str]]:
    """Sync selected skills into repo_root/.agents/skills/.

    Only skills recorded in the previous codex-lock are treated as
    Illuminate-managed. A project-owned directory that shares a skill's
    name is never overwritten or claimed: sync fails closed with
    ValueError instead.

    Returns {skill_name: [copied_file_rel_paths]}.
    """
    target_dir = repo_root / ".agents" / "skills"

    lock = load_codex_lock(repo_root)
    managed_names = {e["name"] for e in lock.get("skills", [])} if lock else set()

    # Pre-flight collision check: fail closed before touching the repo, so a
    # collision leaves no partial write behind.
    for entry in manifest.get("skills", []):
        if entry["id"] not in exposed:
            continue
        skill_name = entry["dir"].split("/")[-1]
        dest_dir = target_dir / skill_name
        if dest_dir.exists() and skill_name not in managed_names:
            raise ValueError(
                f"Cannot sync skill '{skill_name}': "
                "destination already exists and is not Illuminate-managed"
            )

    target_dir.mkdir(parents=True, exist_ok=True)

    copied: Dict[str, List[str]] = {}
    synced_names = set()

    for entry in manifest.get("skills", []):
        if entry["id"] not in exposed:
            continue

        skill_dir = pack_dir / entry["dir"]
        if not skill_dir.exists():
            continue

        skill_name = entry["dir"].split("/")[-1]
        synced_names.add(skill_name)
        dest_dir = target_dir / skill_name

        # Clean only if previously managed (handles removed content)
        if skill_name in managed_names and dest_dir.exists():
            shutil.rmtree(dest_dir)
        dest_dir.mkdir(parents=True, exist_ok=True)

        skill_files: List[str] = []
        for file_path in sorted(skill_dir.rglob("*")):
            if not file_path.is_file():
                continue
            rel = file_path.relative_to(skill_dir)
            destination = dest_dir / rel
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(file_path, destination)
            skill_files.append(rel.as_posix())

        copied[skill_name] = skill_files

    # Remove stale managed skills no longer exposed
    for name in managed_names:
        if name not in synced_names:
            stale_dir = target_dir / name
            if stale_dir.exists():
                shutil.rmtree(stale_dir)

    return copied


def _build_openai_yaml(
    contract: dict,
    entry_sk_path: Optional[str] = None,
) -> str:
    """Build agents/openai.yaml content from contract metadata."""
    activation = contract.get("activation", {})
    mode = activation.get("mode", "auto")
    tags = activation.get("include_tags", [])
    relations = contract.get("relations", {})

    display_name = contract.get("id", "unknown").split(".")[-1] if "." in contract.get("id", "") else contract.get("id", "unknown")

    # Derive short description from contract tags or id
    if tags:
        short_desc = "; ".join(tags[:3])
    else:
        short_desc = contract.get("id", display_name)

    # Derive default prompt from SKILL.md entry if available
    default_prompt = f"使用 {display_name} 分析当前问题"

    yaml_lines = [
        "interface:",
        f"  display_name: \"{display_name}\"",
        f"  short_description: \"{short_desc}\"",
        f"  default_prompt: \"{default_prompt}\"",
        "",
        "policy:",
        f"  allow_implicit_invocation: {'true' if mode == 'auto' else 'false'}",
    ]

    return "\n".join(yaml_lines) + "\n"


# ---------------------------------------------------------------------------
# Codex lock
# ---------------------------------------------------------------------------

def _create_codex_lock(
    repo_root: Path,
    pack_dir: Path,
    manifest: dict,
    exposed: Set[str],
    skill_files: Dict[str, List[str]],
) -> dict:
    """Create .illuminate/codex-lock.json."""
    lock_dir = repo_root / ".illuminate"
    lock_dir.mkdir(parents=True, exist_ok=True)

    # Hash all synced skill files
    skill_entries = []
    for skill_name, files in skill_files.items():
        skill_root = repo_root / ".agents" / "skills" / skill_name
        file_hashes = {}
        for rel in sorted(files):
            fpath = skill_root / rel
            if fpath.exists():
                file_hashes[rel] = hash_file(fpath)
        skill_entries.append({
            "name": skill_name,
            "files": file_hashes,
        })

    agents_hash = ""
    agents_path = repo_root / "AGENTS.md"
    if agents_path.exists():
        agents_hash = hash_file(agents_path)

    pack_hash = hash_directory(pack_dir)

    lock = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "pack": {
            "id": manifest.get("id", "?"),
            "version": manifest.get("version", "?"),
            "hash": lock_hash(pack_hash),
        },
        "exposed_skills": sorted(exposed),
        "agents_md_hash": agents_hash,
        "skills": skill_entries,
    }

    lock_path = lock_dir / "codex-lock.json"
    with open(lock_path, "w", encoding="utf-8") as f:
        json.dump(lock, f, indent=2, ensure_ascii=False)
        f.write("\n")

    return lock


def load_codex_lock(repo_root: Path) -> Optional[dict]:
    """Load an existing codex-lock.json from the repo."""
    lock_path = repo_root / ".illuminate" / "codex-lock.json"
    if not lock_path.exists():
        return None
    with open(lock_path, "r", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Main sync entry point
# ---------------------------------------------------------------------------

def sync_codex(
    pack_dir: Path,
    repo_root: Path,
    skill_filter: Optional[List[str]] = None,
) -> dict:
    """Synchronize Illuminate Pack into a target repository for Codex App.

    Steps:
      1. Validate pack.
      2. Resolve exposed skills via the shared resolver (unknown-ID, alias,
         and cycle checks; activation_conflicts is activation-level, so
         exposure never rejects conflicting skills).
      3. Merge Illuminate policy block into AGENTS.md.
      4. Sync .agents/skills/ (lock-owned: only previously managed skills are
         replaced or removed; project-owned skills are preserved).
      5. Generate agents/openai.yaml for each skill and register it in the
         lock.
      6. Generate .illuminate/codex-lock.json.

    Returns a summary dict with sync results.
    """
    pack_dir = Path(pack_dir).resolve()
    repo_root = Path(repo_root).resolve()

    # 1. Validate pack
    ok, errors = validate_pack(pack_dir)
    if not ok:
        raise ValueError(
            "Pack validation failed:\n" + "\n".join(errors)
        )

    manifest = load_pack_manifest(pack_dir)
    contracts = load_skill_contracts(pack_dir, manifest)

    # 2. Resolve exposed skills via the single shared resolver
    exposed = set(resolve_exposed_skills(manifest, contracts, skill_filter))

    # 3. Sync .agents/skills/ first (lock-owned; project-owned skills
    # preserved; collisions fail closed before any repo modification)
    skill_files = _sync_skills(pack_dir, repo_root, manifest, exposed)

    # 4. Merge AGENTS.md
    agents_path = repo_root / "AGENTS.md"
    block_text = _build_agents_block(pack_dir, manifest, exposed)
    new_content, agents_modified = merge_agents_block(agents_path, block_text)
    agents_path.write_text(new_content, encoding="utf-8")

    # 5. Generate agents/openai.yaml for each exposed skill
    contracts_by_id = {c["id"]: c for c in contracts}
    openai_yamls: Dict[str, str] = {}
    for entry in manifest.get("skills", []):
        if entry["id"] not in exposed:
            continue
        contract = contracts_by_id.get(entry["id"], {})
        skill_name = entry["dir"].split("/")[-1]
        yaml_content = _build_openai_yaml(contract)
        yaml_dest = repo_root / ".agents" / "skills" / skill_name / "agents" / "openai.yaml"
        yaml_dest.parent.mkdir(parents=True, exist_ok=True)
        yaml_dest.write_text(yaml_content, encoding="utf-8")
        # Register in skill_files (idempotently) so the lock hashes this
        # generated artifact too
        yaml_files = skill_files.setdefault(skill_name, [])
        if "agents/openai.yaml" not in yaml_files:
            yaml_files.append("agents/openai.yaml")
        openai_yamls[skill_name] = yaml_content

    # 6. Generate lock
    lock = _create_codex_lock(repo_root, pack_dir, manifest, exposed, skill_files)

    return {
        "pack_id": manifest.get("id", "?"),
        "pack_version": manifest.get("version", "?"),
        "exposed_skills": sorted(exposed),
        "skill_count": len(exposed),
        "agents_modified": agents_modified,
        "files_copied": sum(len(f) for f in skill_files.values()),
    }


# ---------------------------------------------------------------------------
# Sync check
# ---------------------------------------------------------------------------

def check_sync(
    pack_dir: Path,
    repo_root: Path,
) -> Tuple[bool, List[str]]:
    """Verify the Codex sync is current and consistent.

    Checks:
      - source pack hash matches the one recorded at sync time
      - AGENTS.md contains the illuminate block
      - .agents/skills/ exists and has expected skills
      - every lock-recorded skill file (incl. agents/openai.yaml) exists
        with an unchanged hash
      - codex-lock.json exists and hashes match

    Returns (ok, list_of_issues).
    """
    issues: List[str] = []
    pack_dir = Path(pack_dir).resolve()
    repo_root = Path(repo_root).resolve()

    # Check AGENTS.md block
    agents_path = repo_root / "AGENTS.md"
    if not agents_path.exists():
        issues.append("AGENTS.md not found")
    else:
        content = agents_path.read_text(encoding="utf-8")
        if _BEGIN_MARKER not in content:
            issues.append("AGENTS.md missing illuminate block markers")

    # Check .agents/skills/
    skills_dir = repo_root / ".agents" / "skills"
    if not skills_dir.exists():
        issues.append(".agents/skills/ does not exist")
    elif not any(skills_dir.iterdir()):
        issues.append(".agents/skills/ is empty")

    # Check codex-lock.json
    lock = load_codex_lock(repo_root)
    if lock is None:
        issues.append("codex-lock.json not found")
    else:
        # Verify source pack unchanged
        current_pack_hash = lock_hash(hash_directory(pack_dir))
        if lock.get("pack", {}).get("hash") != current_pack_hash:
            issues.append("Pack source changed — run sync again")

        # Verify AGENTS.md hash
        if agents_path.exists():
            actual_hash = hash_file(agents_path)
            if lock.get("agents_md_hash") != actual_hash:
                issues.append("AGENTS.md hash mismatch — run sync again")

        # Verify skill files
        for skill_entry in lock.get("skills", []):
            skill_name = skill_entry["name"]
            for rel, expected_hash in skill_entry.get("files", {}).items():
                fpath = repo_root / ".agents" / "skills" / skill_name / rel
                if not fpath.exists():
                    issues.append(f"Missing skill file: .agents/skills/{skill_name}/{rel}")
                else:
                    actual_hash = hash_file(fpath)
                    if actual_hash != expected_hash:
                        issues.append(
                            f"Hash mismatch: .agents/skills/{skill_name}/{rel}"
                        )

    return (len(issues) == 0), issues


# ---------------------------------------------------------------------------
# Sync clean
# ---------------------------------------------------------------------------

def clean_sync(repo_root: Path) -> dict:
    """Remove all Illuminate-synced artifacts from a repository.

    Removes:
      - AGENTS.md illuminate block
      - .agents/skills/ directory
      - .illuminate/codex-lock.json

    Returns dict with removal summary.
    """
    repo_root = Path(repo_root).resolve()
    removed = []

    # Remove illuminate block from AGENTS.md
    agents_path = repo_root / "AGENTS.md"
    if agents_path.exists():
        content = agents_path.read_text(encoding="utf-8")
        new_content = remove_block(content)
        if new_content != content:
            agents_path.write_text(new_content, encoding="utf-8")
            removed.append("AGENTS.md illuminate block")

    # Remove managed skills (only those recorded in the lock)
    lock = load_codex_lock(repo_root)
    skills_dir = repo_root / ".agents" / "skills"
    for skill_entry in (lock or {}).get("skills", []):
        skill_path = skills_dir / skill_entry["name"]
        if skill_path.exists():
            shutil.rmtree(skill_path)
            removed.append(f".agents/skills/{skill_entry['name']}")

    # Remove .agents/skills/ if empty
    if skills_dir.exists() and not any(skills_dir.iterdir()):
        shutil.rmtree(skills_dir)
        removed.append(".agents/skills/")

    # Remove .agents/ if empty
    agents_dir = repo_root / ".agents"
    if agents_dir.exists() and not any(agents_dir.iterdir()):
        shutil.rmtree(agents_dir)
        removed.append(".agents/")

    # Remove codex-lock.json
    lock_path = repo_root / ".illuminate" / "codex-lock.json"
    if lock_path.exists():
        lock_path.unlink()
        removed.append(".illuminate/codex-lock.json")

    return {"removed_artifacts": removed}
