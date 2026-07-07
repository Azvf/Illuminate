#!/usr/bin/env python3
"""Shared git utilities for evidence providers.

All providers use this to call git, ensuring consistent error handling
and cross-platform behavior (Windows / macOS / Linux).
"""

import os
import subprocess
from pathlib import Path


def run_git(args, repo_root):
    """Run a git command and return stdout as string.

    Raises RuntimeError if git is not found, repo is not a git repository,
    or the command fails.
    """
    env = os.environ.copy()
    env["GIT_PAGER"] = "cat"  # prevent pager hangs in non-interactive mode

    try:
        result = subprocess.run(
            ["git", "--no-pager"] + args,
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
        )
    except FileNotFoundError:
        raise RuntimeError(
            "git not found — please install git and ensure it is in PATH"
        )

    if result.returncode != 0:
        stderr = result.stderr.strip()
        if "not a git repository" in stderr.lower():
            raise RuntimeError(f"Not a git repository: {repo_root}")
        raise RuntimeError(
            f"git {' '.join(args)} failed (exit {result.returncode}): {stderr}"
        )

    return result.stdout


def get_untracked_files(repo_root):
    """Return list of untracked file paths (excluding .gitignored files)."""
    output = run_git(["ls-files", "--others", "--exclude-standard"], repo_root)
    return [line.strip() for line in output.splitlines() if line.strip()]


def _read_file_lines(repo_root, file_path):
    """Read a file and yield (line_number, content) tuples.

    Returns empty list for binary or unreadable files.
    """
    full_path = Path(repo_root) / file_path
    try:
        content = full_path.read_text(encoding="utf-8", errors="replace")
        return list(enumerate(content.splitlines(), 1))
    except OSError:
        return []


def get_added_lines(repo_root):
    """Return list of (file_path, line_number, content) for every added line.

    Combines two sources:
    1. `git diff --unified=0 HEAD` — added lines in tracked files
    2. Untracked files (entirely new, not yet in git index) — all lines count as added
    """
    import re

    diff = run_git(["diff", "--unified=0", "HEAD"], repo_root)

    added = []
    current_file = None
    current_line = 0

    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            current_file = line[6:]
            current_line = 0
        elif line.startswith("@@"):
            # Hunk header: @@ -old_start,old_count +new_start,new_count @@
            match = re.search(r"\+(\d+)", line)
            if match:
                current_line = int(match.group(1)) - 1
        elif line.startswith("+") and not line.startswith("+++"):
            current_line += 1
            added.append((current_file, current_line, line[1:]))

    # Also include untracked files (entirely new, not in git index)
    for file_path in get_untracked_files(repo_root):
        for line_no, content in _read_file_lines(repo_root, file_path):
            added.append((file_path, line_no, content))

    return added


def get_removed_lines(repo_root):
    """Return list of (file_path, line_number, content) for every removed line."""
    import re

    diff = run_git(["diff", "--unified=0", "HEAD"], repo_root)

    removed = []
    current_file = None
    current_line = 0

    for line in diff.splitlines():
        if line.startswith("--- a/"):
            current_file = line[6:]
            current_line = 0
        elif line.startswith("@@"):
            match = re.search(r"-(\d+)", line)
            if match:
                current_line = int(match.group(1)) - 1
        elif line.startswith("-") and not line.startswith("---"):
            current_line += 1
            removed.append((current_file, current_line, line[1:]))

    return removed
