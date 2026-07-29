"""Repository inspection: detect project context files and capabilities."""

import json
import sys
from pathlib import Path


PROJECT_CONTEXT_CANDIDATES = [
    "AGENTS.md",
    "CLAUDE.md",
    "CONTRIBUTING.md",
]


def inspect_repo(repo_root):
    """Inspect a target repository and report what context is available."""
    repo_root = Path(repo_root).resolve()

    result = {
        "repo": str(repo_root),
        "is_git": (repo_root / ".git").exists(),
        "context_files": [],
        "guideline_dirs": [],
        "framework_dirs": [],
        "has_evidence_overlay": False,
    }

    for candidate in PROJECT_CONTEXT_CANDIDATES:
        path = repo_root / candidate
        if path.exists():
            result["context_files"].append(candidate)

    for doc_dir in ("docs/Guidelines", "docs/Framework", "docs/Research", "docs/Issues"):
        path = repo_root / doc_dir
        if path.exists() and any(path.glob("*.md")):
            if "Guidelines" in doc_dir:
                result["guideline_dirs"].append(doc_dir)
            elif "Framework" in doc_dir:
                result["framework_dirs"].append(doc_dir)

    overlay = repo_root / ".illuminate" / "evidence" / "patterns_overlay.json"
    result["has_evidence_overlay"] = overlay.exists()

    return result


def print_inspect_report(info, file=None):
    """Print a human-readable inspection report."""
    if file is None:
        file = sys.stdout

    print(f"  Repository: {info['repo']}", file=file)
    print(f"  Git repo:   {'yes' if info['is_git'] else 'no'}", file=file)
    print(file=file)

    if info["context_files"]:
        print("  Context files:", file=file)
        for f in info["context_files"]:
            print(f"    - {f}", file=file)
    else:
        print("  Context files: (none found)", file=file)

    if info["guideline_dirs"]:
        print("  Guideline dirs:", file=file)
        for d in info["guideline_dirs"]:
            print(f"    - {d}", file=file)

    if info["framework_dirs"]:
        print("  Framework dirs:", file=file)
        for d in info["framework_dirs"]:
            print(f"    - {d}", file=file)

    print(f"  Evidence overlay: {'yes' if info['has_evidence_overlay'] else 'no'}", file=file)
