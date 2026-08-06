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

from .hashutil import hash_file, hash_directory, hash_string, lock_hash
from .lockfile import build_lock_envelope
from .managed_block import (
    BEGIN_MARKER as _BEGIN_MARKER,
    END_MARKER as _END_MARKER,
    merge_block,
    remove_block,
)
from .resolve import resolve_pack
from .sync_shared import (
    apply_knowledge_map,
    build_agents_block,
    check_knowledge_map,
    check_managed_file_hashes,
    ensure_regular_file,
    other_harness_declares_map,
    preflight_knowledge_map,
    remove_empty_parent_dirs,
    sync_managed_skill_tree,
)
from .validate import validate_pack


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
    lock = load_codex_lock(repo_root)
    managed_names = {e["name"] for e in lock.get("skills", [])} if lock else set()

    synced = sync_managed_skill_tree(
        pack_dir,
        repo_root / ".agents" / "skills",
        manifest,
        exposed,
        managed_names,
    )
    # Shared helper returns {name: {rel: hash}}; downstream lock build expects
    # the sorted list of relative paths.
    return {name: list(rel_hashes) for name, rel_hashes in synced.items()}


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
    knowledge_map_hash: Optional[str] = None,
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

    managed_artifacts = [
        "AGENTS.md",
        *[
            f".agents/skills/{entry['name']}/{rel}"
            for entry in skill_entries
            for rel in entry["files"]
        ],
    ]
    if knowledge_map_hash is not None:
        managed_artifacts.append(".illuminate/knowledge-map.md")

    lock = build_lock_envelope(
        harness="codex",
        pack={
            "id": manifest.get("id", "?"),
            "version": manifest.get("version", "?"),
            "hash": lock_hash(pack_hash),
        },
        target={"path": str(repo_root)},
        selection={"skills": sorted(exposed)},
        managed_artifacts=managed_artifacts,
        capabilities={"permissions": "declarative-only"},
    )
    lock.update({
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "exposed_skills": sorted(exposed),
        "agents_md_hash": agents_hash,
        "skills": skill_entries,
    })
    if knowledge_map_hash is not None:
        lock["knowledge_map_hash"] = knowledge_map_hash

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
    if not lock_path.is_file():
        raise ValueError(f"{lock_path} exists but is not a regular file")
    with open(lock_path, "r", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Main sync entry point
# ---------------------------------------------------------------------------

def sync_codex(
    pack_dir: Path,
    repo_root: Path,
    skill_filter: Optional[List[str]] = None,
    force: bool = False,
) -> dict:
    """Synchronize Illuminate Pack into a target repository for Codex App.

    ``force`` authorizes overwriting/deleting an existing knowledge map that no
    Illuminate lock owns (an unmanaged leftover). Without it such a map aborts
    preflight with ValueError.

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

    # 2. Resolve pack through the single shared resolution entry
    resolved = resolve_pack(pack_dir, str(repo_root), skill_filter)
    manifest = resolved["manifest"]
    contracts = resolved["contracts"]
    exposed = set(resolved["skills"]["exposed"])

    # 3. Phase 1 preflight: every expected write file must be a regular file
    #    and the knowledge map write/delete must pass before any repo
    #    modification, so a read-only map, an unmanaged leftover map, or an
    #    un-deletable stale map leaves no partial write behind.
    ensure_regular_file(repo_root / ".illuminate" / "codex-lock.json")
    ensure_regular_file(repo_root / "AGENTS.md")
    map_path = repo_root / ".illuminate" / "knowledge-map.md"
    map_text = preflight_knowledge_map(
        repo_root, map_path, force=force, harness="codex"
    )

    # 4. Sync .agents/skills/ first (lock-owned; project-owned skills
    # preserved; collisions fail closed before any repo modification)
    skill_files = _sync_skills(pack_dir, repo_root, manifest, exposed)

    # 5. Merge AGENTS.md
    agents_path = repo_root / "AGENTS.md"
    block_text = build_agents_block(pack_dir, manifest, exposed)
    new_content, agents_modified = merge_agents_block(agents_path, block_text)
    agents_path.write_text(new_content, encoding="utf-8")

    # 6. Generate agents/openai.yaml for each exposed skill
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

    # 7. Write or delete the Knowledge Map (preflighted in Phase 1) before
    # the lock. If there is no indexable knowledge, the stale map is removed
    # and no hash is recorded. The lock stores the hash of the canonical map
    # text, so check_sync can compare against a rebuilt text hash regardless
    # of the platform line endings of the on-disk file.
    apply_knowledge_map(map_path, map_text, force=force)
    knowledge_map_hash = hash_string(map_text) if map_text is not None else None

    # 8. Generate lock
    lock = _create_codex_lock(repo_root, pack_dir, manifest, exposed, skill_files, knowledge_map_hash)

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
        check_managed_file_hashes(
            repo_root, ".agents/skills", lock.get("skills", []), issues
        )

        # Verify the Knowledge Map against the lock's expected state (present
        # or absent). check is read-only: the shared helper rebuilds the map
        # text and compares its hash to the lock record, so a doc
        # added/moved/removed after sync is flagged even though the on-disk
        # map file was not regenerated.
        expected_map_hash = lock.get("knowledge_map_hash")
        check_knowledge_map(repo_root, expected_map_hash, ".illuminate/knowledge-map.md", issues)

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

    # Remove .agents/skills/ and empty parent dirs up to repo root
    if skills_dir.exists():
        removed.extend(remove_empty_parent_dirs(skills_dir, repo_root))

    # Remove the knowledge map when the lock records a hash AND no other
    # harness still owns it. The shared map may be written by cursor/codex/
    # codebuddy together, so cleaning one harness must not delete a map that
    # another harness still references.
    if (lock or {}).get("knowledge_map_hash") and not other_harness_declares_map(repo_root, "codex"):
        map_path = repo_root / ".illuminate" / "knowledge-map.md"
        if map_path.exists():
            map_path.unlink()
            removed.append(".illuminate/knowledge-map.md")

    # Remove codex-lock.json
    lock_path = repo_root / ".illuminate" / "codex-lock.json"
    if lock_path.exists():
        lock_path.unlink()
        removed.append(".illuminate/codex-lock.json")

    return {"removed_artifacts": removed}
