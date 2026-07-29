"""Legacy compatibility directory generation and verification."""

import shutil
from pathlib import Path
from typing import List, Tuple

from .manifest import load_pack_manifest


def compat_generate(pack_dir: Path, repo_root: Path) -> int:
    """Generate legacy compatibility dirs from canonical sources.

    Creates:
      .claude/skills/    → from packs/<pack>/skills/

    Returns the number of files copied.
    """
    manifest = load_pack_manifest(pack_dir)

    # ── .claude/skills/ ← packs/<pack>/skills/ ──
    claude_skills_dir = repo_root / ".claude" / "skills"
    claude_skills_dir.mkdir(parents=True, exist_ok=True)

    count = 0
    for entry in manifest.get("skills", []):
        skill_dir = pack_dir / entry["dir"]
        if not skill_dir.exists():
            continue
        skill_name = entry["dir"].split("/")[-1]
        dest_dir = claude_skills_dir / skill_name
        dest_dir.mkdir(parents=True, exist_ok=True)
        for file_path in skill_dir.iterdir():
            if file_path.is_file():
                shutil.copy2(file_path, dest_dir / file_path.name)
                count += 1

    return count


def compat_check(pack_dir: Path, repo_root: Path) -> Tuple[bool, List[str]]:
    """Verify legacy compatibility dirs exist and are not empty.

    Returns (ok, list_of_issues).
    """
    issues: List[str] = []

    claude_skills_dir = repo_root / ".claude" / "skills"
    if not claude_skills_dir.exists():
        issues.append(
            ".claude/skills/ does not exist — run 'illuminate compat generate'"
        )
    elif not any(claude_skills_dir.iterdir()):
        issues.append(".claude/skills/ is empty")

    return (len(issues) == 0), issues
