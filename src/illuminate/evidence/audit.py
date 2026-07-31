#!/usr/bin/env python3
"""Illuminate Evidence Auditor — main entry point.

Runs all evidence providers and aggregates results into evidence.json.
The output contains deterministic facts only (Layer 1 / Layer 2):
no scores, no risk assessments. The Agent reads these facts and makes
Layer 3 semantic judgments during the Audit step.

Usage:
    illuminate evidence audit [options]

Options:
    --pretty        Pretty-print JSON output
    --output PATH   Output file path (default: <repo>/.illuminate/reports/evidence.json)
    --repo PATH     Repository root (default: current directory)
    --quiet         Suppress summary output

Exit codes:
    0  Success
    1  Error (not a git repo, git not found, etc.)

Design principles:
    - Facts, not scores (avoid Goodhart's law)
    - Deterministic and reproducible
    - Language-agnostic where possible
    - Zero external dependencies (standard library only)
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from importlib import metadata as importlib_metadata
from pathlib import Path
from typing import Optional

from .diff_provider import collect as collect_diff
from .patterns_provider import collect as collect_patterns
from .imports_provider import collect as collect_imports
from .gitutil import get_head_commit


def _tool_version() -> str:
    """Read the tool version from installed package metadata."""
    try:
        return importlib_metadata.version("illuminate-harness")
    except Exception:
        return "unknown"


def _pack_identity(pack_dir: Optional[Path]):
    """Read pack id/version from the current pack.json, if available.

    Returns (id, version); both are "unbound" when no pack is supplied,
    which is a deliberate state (the report is not tied to a pack) rather
    than a read failure.
    """
    if pack_dir is None:
        return ("unbound", "unbound")
    pack_json = Path(pack_dir) / "pack.json"
    if not pack_json.exists():
        return ("unbound", "unbound")
    try:
        with open(pack_json, "r", encoding="utf-8") as f:
            data = json.load(f)
        return (data.get("id", "unbound"), data.get("version", "unbound"))
    except Exception:
        return ("unbound", "unbound")


def _default_output_path(repo_root):
    return repo_root / ".illuminate" / "reports" / "evidence.json"


def run_audit(repo_root, output_path=None, pretty=False,
              quiet=False, pack_lock_hash=None, pack_dir=None):
    """Run the evidence audit and write results to output_path.

    Args:
        pack_dir: Optional path to a pack whose pack.json supplies the
                  pack identity in the report.

    Returns the evidence dict.
    """
    repo_root = Path(repo_root).resolve()
    if output_path is None:
        output_path = _default_output_path(repo_root)
    else:
        output_path = Path(output_path)

    errors = []
    diff_result = {}
    patterns_result = {}
    imports_result = {}

    try:
        diff_result = collect_diff(repo_root)
    except Exception as e:
        errors.append({"provider": "diff", "error": str(e)})

    try:
        patterns_result = collect_patterns(repo_root)
    except Exception as e:
        errors.append({"provider": "patterns", "error": str(e)})

    try:
        imports_result = collect_imports(repo_root)
    except Exception as e:
        errors.append({"provider": "imports", "error": str(e)})

    head_commit = get_head_commit(repo_root)

    pack_id, pack_version = _pack_identity(pack_dir)

    evidence = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "tool": {
            "name": "illuminate",
            "version": _tool_version(),
        },
        "pack": {
            "binding": "bound" if pack_dir is not None else "unbound",
            "id": pack_id,
            "version": pack_version,
            "lock_hash": pack_lock_hash or "unknown",
        },
        "baseline": {
            "type": "working-tree-vs-head",
            "commit": head_commit or "none",
        },
        "repo": str(repo_root),
        "diff": diff_result,
        "patterns": patterns_result,
        "imports": imports_result,
    }

    if errors:
        evidence["errors"] = errors

    output_path.parent.mkdir(parents=True, exist_ok=True)

    indent = 2 if pretty else None
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(evidence, f, indent=indent, ensure_ascii=False)
        if indent is not None:
            f.write("\n")

    if not quiet:
        _print_summary(evidence, file=sys.stderr)

    return evidence


def _print_summary(evidence, file):
    diff = evidence.get("diff", {})
    patterns = evidence.get("patterns", {})
    imports = evidence.get("imports", {})
    errors = evidence.get("errors", [])

    files = diff.get("files", {})
    lines = diff.get("lines", {})

    bar = "=" * 64
    print(bar, file=file)
    print("  Illuminate Evidence Report", file=file)
    print(bar, file=file)
    print(file=file)

    tool = evidence.get("tool", {})
    pack = evidence.get("pack", {})
    print(f"  Tool:   {tool.get('name', '?')} v{tool.get('version', '?')}", file=file)
    if pack.get("binding") == "bound":
        print(f"  Pack:   {pack.get('id', '?')} v{pack.get('version', '?')}", file=file)
    else:
        print(f"  Pack:   unbound (pass --pack to bind)", file=file)
    print(f"  Lock:   {pack.get('lock_hash', '?')}", file=file)
    print(file=file)

    print(
        f"  Files:  +{files.get('added', 0)}  ~{files.get('modified', 0)}  "
        f"-{files.get('deleted', 0)}  >{files.get('renamed', 0)}",
        file=file,
    )
    print(
        f"  Lines:  +{lines.get('added', 0)}  -{lines.get('removed', 0)}  "
        f"(net {lines.get('net', 0):+,d})",
        file=file,
    )
    print(file=file)

    abstractions = patterns.get("new_abstractions", [])
    flags = patterns.get("new_feature_flags", [])
    fallbacks = patterns.get("new_fallback_paths", [])

    print(f"  New abstractions: {len(abstractions)}", file=file)
    for a in abstractions:
        print(f"    - {a['name']}  [{a['keyword']}]  {a['file']}:{a['line']}", file=file)

    print(f"  New feature flags: {len(flags)}", file=file)
    for f_item in flags:
        print(f"    - {f_item['file']}:{f_item['line']}", file=file)

    print(f"  New fallback paths: {len(fallbacks)}", file=file)
    for fb in fallbacks:
        print(f"    - [{fb['type']}]  {fb['file']}:{fb['line']}", file=file)
    print(file=file)

    imp_added = imports.get("added", [])
    imp_removed = imports.get("removed", [])
    print(f"  Imports: +{len(imp_added)}  -{len(imp_removed)}", file=file)
    for imp in imp_added:
        print(f"    + {imp['module']}  ({imp['language']})", file=file)
    for imp in imp_removed:
        print(f"    - {imp['module']}  ({imp['language']})", file=file)

    if errors:
        print(file=file)
        print(f"  Provider errors: {len(errors)}", file=file)
        for e in errors:
            print(f"    [{e['provider']}] {e['error']}", file=file)

    print(file=file)
    print(bar, file=file)
    print("  These are facts. Judgment is the Agent's responsibility.", file=file)
    print(bar, file=file)
