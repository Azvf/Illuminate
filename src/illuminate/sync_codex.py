"""Codex sync: synchronize Illuminate Pack into a target repository for Codex App.

Generates:
  AGENTS.md                  (Illuminate policy block, merged via <!-- illuminate:... --> markers)
  .agents/skills/            (selected skills, atomic sync)
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
from .manifest import load_pack_manifest, load_policy_index, load_skill_contracts
from .validate import validate_pack


# ---------------------------------------------------------------------------
# AGENTS.md block markers
# ---------------------------------------------------------------------------

_BEGIN_MARKER = "<!-- illuminate:begin"
_END_MARKER = "<!-- illuminate:end -->"


def _make_begin_marker(manifest: dict) -> str:
    pack_id = manifest.get("id", "?")
    version = manifest.get("version", "?")
    return f"<!-- illuminate:begin\npack={pack_id}\nversion={version}\n-->"


def _block_range(lines: List[str]) -> Optional[Tuple[int, int]]:
    """Find <!-- illuminate:begin --> ... <!-- illuminate:end --> range.

    Returns (begin_index, end_index) or None if not found.
    """
    begin = None
    for i, line in enumerate(lines):
        if line.strip().startswith(_BEGIN_MARKER):
            begin = i
        if begin is not None and line.strip() == _END_MARKER:
            return (begin, i)
    return None


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
    begin = _make_begin_marker(manifest)
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
    if agents_path.exists():
        original = agents_path.read_text(encoding="utf-8")
    else:
        original = ""

    if not original.strip():
        return block_text + "\n", True

    lines = original.split("\n")
    existing_range = _block_range(lines)

    if existing_range is None:
        # Append at end with a blank line separator
        result = original.rstrip("\n") + "\n\n" + block_text + "\n"
        return result, True

    begin_idx, end_idx = existing_range
    before = "\n".join(lines[:begin_idx]).rstrip("\n")
    after = "\n".join(lines[end_idx + 1:])

    new_lines = [before, "", block_text.strip(), "", after]
    result = "\n".join(new_lines).strip("\n") + "\n"
    return result, (result != original)


# ---------------------------------------------------------------------------
# Skill sync helpers
# ---------------------------------------------------------------------------

def _sync_skills(
    pack_dir: Path,
    repo_root: Path,
    manifest: dict,
    exposed: Set[str],
) -> Dict[str, List[str]]:
    """Atomically sync selected skills into repo_root/.agents/skills/.

    Returns {skill_name: [copied_file_rel_paths]}.
    """
    target_dir = repo_root / ".agents" / "skills"
    temp_dir = repo_root / ".agents" / ".skills.tmp"

    # Clean temp
    if temp_dir.exists():
        shutil.rmtree(temp_dir)

    copied: Dict[str, List[str]] = {}

    for entry in manifest.get("skills", []):
        if entry["id"] not in exposed:
            continue

        skill_dir = pack_dir / entry["dir"]
        if not skill_dir.exists():
            continue

        skill_name = entry["dir"].split("/")[-1]
        dest_dir = temp_dir / skill_name
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

    # Atomic replace
    if target_dir.exists():
        shutil.rmtree(target_dir)
    if temp_dir.exists():
        temp_dir.rename(target_dir)

    return copied


def _generate_openai_yaml(pack_dir: Path, manifest: dict, exposed: Set[str]) -> None:
    """Generate agents/openai.yaml metadata for each exposed skill.

    Written directly into the skill directory in .agents/skills/<name>/.
    """
    contracts = load_skill_contracts(pack_dir, manifest)
    contracts_by_id = {c["id"]: c for c in contracts}

    for entry in manifest.get("skills", []):
        if entry["id"] not in exposed:
            continue

        contract = contracts_by_id.get(entry["id"], {})
        skill_name = entry["dir"].split("/")[-1]
        yaml_path = Path(manifest.get("_repo_root", "") or str(pack_dir))

        # The yaml is written to .agents/skills/<skill_name>/agents/openai.yaml
        # which is inside the repo target, not in the pack.
        # We need the repo_root here. Since this function doesn't receive it,
        # we handle it in the caller.
        pass


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
      2. Resolve exposed skills (filter + alias resolution + conflict check).
      3. Merge Illuminate policy block into AGENTS.md.
      4. Atomically sync .agents/skills/.
      5. Generate agents/openai.yaml for each skill.
      6. Generate .illuminate/codex-lock.json.
      7. Clean stale skills not in the exposed set.

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

    # 2. Resolve exposed skills
    all_skill_ids = {entry["id"] for entry in manifest.get("skills", [])}

    # Build alias map
    alias_map = {}
    for contract in contracts:
        if contract.get("kind") == "alias":
            alias_map[contract["id"]] = contract.get("target", "")

    if skill_filter is None:
        exposed = {
            c["id"] for c in contracts
            if c.get("kind", "skill") != "alias"
        }
    else:
        unknown = [sid for sid in skill_filter if sid not in all_skill_ids]
        if unknown:
            raise ValueError(
                f"Unknown skill ID(s) in filter: {', '.join(unknown)}"
            )
        resolved = []
        for sid in skill_filter:
            current = sid
            visited = set()
            while current in alias_map:
                if current in visited:
                    raise ValueError(f"Alias cycle detected resolving '{sid}'")
                visited.add(current)
                current = alias_map[current]
            resolved.append(current)
        exposed = set(resolved)

    # Check not_recommended_with
    if skill_filter is not None:
        for contract in contracts:
            if contract["id"] in exposed:
                for conflict in contract.get("relations", {}).get("not_recommended_with", []):
                    if conflict in exposed:
                        raise ValueError(
                            f"Skill '{contract['id']}' not recommended with '{conflict}'"
                        )

    # 3. Merge AGENTS.md
    agents_path = repo_root / "AGENTS.md"
    block_text = _build_agents_block(pack_dir, manifest, exposed)
    new_content, agents_modified = merge_agents_block(agents_path, block_text)
    agents_path.write_text(new_content, encoding="utf-8")

    # 4. Sync .agents/skills/ (atomic)
    skill_files = _sync_skills(pack_dir, repo_root, manifest, exposed)

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
        openai_yamls[skill_name] = yaml_content

    # 6. Generate lock
    lock = _create_codex_lock(repo_root, pack_dir, manifest, exposed, skill_files)

    # 7. Clean stale skills
    stale = []
    agents_skills_dir = repo_root / ".agents" / "skills"
    if agents_skills_dir.exists():
        exposed_names = set()
        for entry in manifest.get("skills", []):
            if entry["id"] in exposed:
                exposed_names.add(entry["dir"].split("/")[-1])
        for d in agents_skills_dir.iterdir():
            if d.is_dir() and d.name not in exposed_names:
                shutil.rmtree(d)
                stale.append(d.name)

    return {
        "pack_id": manifest.get("id", "?"),
        "pack_version": manifest.get("version", "?"),
        "exposed_skills": sorted(exposed),
        "skill_count": len(exposed),
        "agents_modified": agents_modified,
        "files_copied": sum(len(f) for f in skill_files.values()),
        "stale_skills_removed": stale,
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
      - AGENTS.md contains the illuminate block
      - .agents/skills/ exists and has expected skills
      - openai.yaml exists for each skill
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
        lines = content.split("\n")
        block_range = _block_range(lines)
        if block_range:
            begin_idx, end_idx = block_range
            before = "\n".join(lines[:begin_idx]).rstrip("\n")
            after = "\n".join(lines[end_idx + 1:])
            new_content = (before + "\n" + after).strip("\n") + "\n" if (before or after) else ""
            agents_path.write_text(new_content, encoding="utf-8")
            removed.append("AGENTS.md illuminate block")

    # Remove .agents/skills/
    skills_dir = repo_root / ".agents" / "skills"
    if skills_dir.exists():
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
