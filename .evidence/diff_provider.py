#!/usr/bin/env python3
"""Evidence Provider: Git Diff Statistics

Collects deterministic facts about working-tree changes vs HEAD:
  - File counts  (added / modified / deleted / renamed)
  - Line counts  (added / removed / net)
  - Per-file breakdown

Layer 1 only — pure facts, no judgment.

Standalone usage:
    python .evidence/diff_provider.py [repo_root]
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from gitutil import run_git, get_untracked_files, _read_file_lines


def collect(repo_root):
    """Return diff statistics as a dict of facts."""
    repo_root = Path(repo_root)

    # --numstat:  added\tremoved\tpath   (binary → -\t-\tpath)
    numstat_raw = run_git(["diff", "--numstat", "HEAD"], repo_root).strip()
    # --name-status:  status\tpath  (rename → R100\told\tnew)
    name_status_raw = run_git(["diff", "--name-status", "HEAD"], repo_root).strip()

    files = {"added": 0, "modified": 0, "deleted": 0, "renamed": 0}
    lines = {"added": 0, "removed": 0, "net": 0}
    by_file = []

    # Build numstat lookup: path → (added, removed)
    numstat_map = {}
    for line in numstat_raw.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        added_str, removed_str, path = parts[0], parts[1], parts[2]
        added = int(added_str) if added_str.lstrip("-").isdigit() else 0
        removed = int(removed_str) if removed_str.lstrip("-").isdigit() else 0
        numstat_map[path] = (added, removed)

    # Parse name-status
    for line in name_status_raw.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        status_char = parts[0][0].upper()  # R100 → R, A → A, etc.
        # For renames/copies, the last field is the destination path
        path = parts[-1]

        if status_char == "A":
            files["added"] += 1
        elif status_char == "M":
            files["modified"] += 1
        elif status_char == "D":
            files["deleted"] += 1
        elif status_char in ("R", "C"):
            files["renamed"] += 1
        else:
            # T (type change), etc. — treat as modified
            files["modified"] += 1

        added, removed = numstat_map.get(path, (0, 0))
        lines["added"] += added
        lines["removed"] += removed
        by_file.append({
            "path": path,
            "status": status_char,
            "lines_added": added,
            "lines_removed": removed,
        })

    # Include untracked files (entirely new, not yet in git index)
    for file_path in get_untracked_files(repo_root):
        file_lines = _read_file_lines(repo_root, file_path)
        line_count = len(file_lines)
        files["added"] += 1
        lines["added"] += line_count
        by_file.append({
            "path": file_path,
            "status": "A",
            "lines_added": line_count,
            "lines_removed": 0,
        })

    lines["net"] = lines["added"] - lines["removed"]

    return {
        "files": files,
        "lines": lines,
        "by_file": by_file,
    }


if __name__ == "__main__":
    repo = sys.argv[1] if len(sys.argv) > 1 else "."
    print(json.dumps(collect(repo), indent=2, ensure_ascii=False))
