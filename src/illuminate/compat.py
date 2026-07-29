"""Legacy compatibility directory generation and verification."""

import shutil
from pathlib import Path
from typing import Dict, List, Tuple

from .hashutil import hash_file
from .manifest import load_pack_manifest


def compat_generate(pack_dir: Path, repo_root: Path) -> int:
    """Generate legacy compatibility dirs from canonical sources.

    Creates:
      .claude/skills/    → from packs/<pack>/skills/

    Clears any stale files before regenerating.
    Uses recursive copy (same as session materializer).

    Returns the number of files copied.
    """
    manifest = load_pack_manifest(pack_dir)

    # ── .claude/skills/ ← packs/<pack>/skills/ ──
    claude_skills_dir = repo_root / ".claude" / "skills"

    # Clean slate to avoid stale files
    if claude_skills_dir.exists():
        shutil.rmtree(claude_skills_dir)
    claude_skills_dir.mkdir(parents=True, exist_ok=True)

    count = 0
    for entry in manifest.get("skills", []):
        skill_dir = pack_dir / entry["dir"]
        if not skill_dir.exists():
            continue
        skill_name = entry["dir"].split("/")[-1]
        dest_dir = claude_skills_dir / skill_name
        dest_dir.mkdir(parents=True, exist_ok=True)

        # Recursive copy, matching session materializer behavior
        for file_path in sorted(skill_dir.rglob("*")):
            if not file_path.is_file():
                continue
            relative = file_path.relative_to(skill_dir)
            destination = dest_dir / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(file_path, destination)
            count += 1

    return count


def _build_file_map(root: Path) -> Dict[str, Path]:
    """Build a dict of {relative_posix_path: absolute_path} for all files."""
    result = {}
    if not root.exists():
        return result
    for f in sorted(root.rglob("*")):
        if f.is_file():
            result[f.relative_to(root).as_posix()] = f
    return result


def compat_check(pack_dir: Path, repo_root: Path) -> Tuple[bool, List[str]]:
    """Verify legacy compatibility dirs match canonical sources.

    Compares file lists and SHA-256 hashes between:
      packs/<pack>/skills/   (canonical)
      .claude/skills/        (legacy)

    Returns (ok, list_of_issues).
    """
    issues: List[str] = []
    manifest = load_pack_manifest(pack_dir)

    # Build expected file map from canonical skill dirs
    expected_map: Dict[str, Path] = {}
    for entry in manifest.get("skills", []):
        skill_dir = pack_dir / entry["dir"]
        if not skill_dir.exists():
            continue
        skill_name = entry["dir"].split("/")[-1]
        for f in sorted(skill_dir.rglob("*")):
            if not f.is_file():
                continue
            rel = f.relative_to(skill_dir)
            expected_map[f"{skill_name}/{rel.as_posix()}"] = f

    # Build actual file map from legacy dir
    claude_skills_dir = repo_root / ".claude" / "skills"
    if not claude_skills_dir.exists():
        issues.append(
            ".claude/skills/ does not exist — run 'illuminate compat generate'"
        )
        return False, issues

    actual_map = _build_file_map(claude_skills_dir)

    # Compare
    expected_keys = set(expected_map.keys())
    actual_keys = set(actual_map.keys())

    missing = expected_keys - actual_keys
    extra = actual_keys - expected_keys

    mismatch = []
    for key in expected_keys & actual_keys:
        expected_hash = hash_file(expected_map[key])
        actual_hash = hash_file(actual_map[key])
        if expected_hash != actual_hash:
            mismatch.append(key)

    if missing:
        issues.append(f"Missing files ({len(missing)}): {', '.join(sorted(missing))}")
    if extra:
        issues.append(f"Extra files ({len(extra)}): {', '.join(sorted(extra))}")
    if mismatch:
        issues.append(f"Hash mismatch ({len(mismatch)}): {', '.join(sorted(mismatch))}")

    return (len(issues) == 0), issues
