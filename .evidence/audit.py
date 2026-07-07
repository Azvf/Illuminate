#!/usr/bin/env python3
"""Illuminate Evidence Auditor — main entry point.

Runs all evidence providers and aggregates results into evidence.json.
The output contains deterministic facts only (Layer 1 / Layer 2):
no scores, no risk assessments. The Agent reads these facts and makes
Layer 3 semantic judgments during the Audit step.

Usage:
    python .evidence/audit.py [options]

Options:
    --pretty        Pretty-print JSON output
    --output PATH   Output file path (default: evidence.json)
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
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from diff_provider import collect as collect_diff
from patterns_provider import collect as collect_patterns
from imports_provider import collect as collect_imports


def main():
    parser = argparse.ArgumentParser(
        description="Illuminate Evidence Auditor — deterministic facts about code changes"
    )
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output")
    parser.add_argument(
        "--output", "-o",
        default="evidence.json",
        help="Output file path (default: evidence.json)",
    )
    parser.add_argument(
        "--repo",
        default=".",
        help="Repository root path (default: current directory)",
    )
    parser.add_argument("--quiet", action="store_true", help="Suppress summary output")
    args = parser.parse_args()

    repo_root = Path(args.repo).resolve()

    # Collect evidence from all providers
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

    evidence = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "baseline": "HEAD (working-tree diff)",
        "repo": str(repo_root),
        "diff": diff_result,
        "patterns": patterns_result,
        "imports": imports_result,
    }

    if errors:
        evidence["errors"] = errors

    # Write JSON output
    indent = 2 if args.pretty else None
    output_path = Path(args.output)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(evidence, f, indent=indent, ensure_ascii=False)
        if indent is not None:
            f.write("\n")

    # Human-readable summary to stderr (does not interfere with piped JSON)
    if not args.quiet:
        _print_summary(evidence, file=sys.stderr)

    # Exit 1 only if all providers failed
    if len(errors) == 3:
        return 1
    return 0


def _print_summary(evidence, file):
    """Print a compact human-readable summary."""
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

    # Diff
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

    # Patterns
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

    # Imports
    imp_added = imports.get("added", [])
    imp_removed = imports.get("removed", [])
    print(f"  Imports: +{len(imp_added)}  -{len(imp_removed)}", file=file)
    for imp in imp_added:
        print(f"    + {imp['module']}  ({imp['language']})", file=file)
    for imp in imp_removed:
        print(f"    - {imp['module']}  ({imp['language']})", file=file)

    # Errors
    if errors:
        print(file=file)
        print(f"  Provider errors: {len(errors)}", file=file)
        for e in errors:
            print(f"    [{e['provider']}] {e['error']}", file=file)

    print(file=file)
    print(bar, file=file)
    print("  These are facts. Judgment is the Agent's responsibility.", file=file)
    print(bar, file=file)


if __name__ == "__main__":
    sys.exit(main())
