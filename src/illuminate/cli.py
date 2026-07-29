"""Illuminate CLI — main entry point.

Commands:
    illuminate pack validate <pack_dir>
    illuminate repo inspect --repo <path>
    illuminate mount create --pack <dir> --repo <path> [--harness claude-code]
    illuminate mount verify <session-dir>
    illuminate run --pack <dir> --repo <path> [--harness claude-code] [--skill <id>...] [--dry-run]
    illuminate evidence audit --repo <path> [--pretty] [--output <path>]
    illuminate compat generate [--pack <dir>]
    illuminate compat check [--pack <dir>]
"""

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .validate import validate_pack
from .inspect_repo import inspect_repo, print_inspect_report
from .materialize_claude import materialize_session, launch_session
from .evidence.audit import run_audit
from .lockfile import load_lock, verify_lock
from .compat import compat_generate, compat_check


def main():
    parser = argparse.ArgumentParser(
        prog="illuminate",
        description="Illuminate Harness Knowledge Pack CLI",
    )
    parser.add_argument("--version", action="version", version=f"illuminate {__version__}")

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # ── pack validate ──
    pack_parser = subparsers.add_parser("pack", help="Pack operations")
    pack_sub = pack_parser.add_subparsers(dest="pack_command")
    validate_parser = pack_sub.add_parser("validate", help="Validate a pack directory")
    validate_parser.add_argument("pack_dir", help="Path to the pack directory")

    # ── repo inspect ──
    repo_parser = subparsers.add_parser("repo", help="Repository operations")
    repo_sub = repo_parser.add_subparsers(dest="repo_command")
    inspect_parser = repo_sub.add_parser("inspect", help="Inspect a target repository")
    inspect_parser.add_argument("--repo", default=".", help="Repository root path")

    # ── mount create / verify ──
    mount_parser = subparsers.add_parser("mount", help="Mount operations")
    mount_sub = mount_parser.add_subparsers(dest="mount_command")

    create_parser = mount_sub.add_parser("create", help="Create a session mount")
    create_parser.add_argument("--pack", required=True, help="Path to the pack directory")
    create_parser.add_argument("--repo", required=True, help="Target repository path")
    create_parser.add_argument("--harness", default="claude-code", help="Target harness")
    create_parser.add_argument("--skill", action="append", default=None,
                               help="Skill ID to expose (repeatable)")

    verify_parser = mount_sub.add_parser("verify", help="Verify session mount integrity")
    verify_parser.add_argument("session_dir", help="Path to the session directory")

    # ── run ──
    run_parser = subparsers.add_parser("run", help="Materialize and launch a session")
    run_parser.add_argument("--pack", required=True, help="Path to the pack directory")
    run_parser.add_argument("--repo", required=True, help="Target repository path")
    run_parser.add_argument("--harness", default="claude-code", help="Target harness")
    run_parser.add_argument("--skill", action="append", default=None,
                            help="Skill ID to expose (repeatable)")
    run_parser.add_argument("--dry-run", action="store_true",
                            help="Print launch command without executing")

    # ── evidence audit ──
    evidence_parser = subparsers.add_parser("evidence", help="Evidence operations")
    evidence_sub = evidence_parser.add_subparsers(dest="evidence_command")
    audit_parser = evidence_sub.add_parser("audit", help="Run evidence audit on a repository")
    audit_parser.add_argument("--repo", default=".", help="Repository root path")
    audit_parser.add_argument("--output", "-o", default=None, help="Output file path")
    audit_parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON")
    audit_parser.add_argument("--quiet", action="store_true", help="Suppress summary")

    # ── compat ──
    compat_parser = subparsers.add_parser("compat", help="Legacy compatibility operations")
    compat_sub = compat_parser.add_subparsers(dest="compat_command")

    compat_gen_parser = compat_sub.add_parser("generate",
                                              help="Generate legacy compatibility dirs from canonical sources")
    compat_gen_parser.add_argument("--pack", default="packs/core", help="Pack directory path")

    compat_chk_parser = compat_sub.add_parser("check",
                                              help="Check legacy compatibility dirs exist and are in sync")
    compat_chk_parser.add_argument("--pack", default="packs/core", help="Pack directory path")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help(sys.stderr)
        return 1

    # Route commands
    dispatch = {
        ("pack", "validate"): lambda: _cmd_pack_validate(args),
        ("repo", "inspect"): lambda: _cmd_repo_inspect(args),
        ("mount", "create"): lambda: _cmd_mount_create(args),
        ("mount", "verify"): lambda: _cmd_mount_verify(args),
        ("run",): lambda: _cmd_run(args),
        ("evidence", "audit"): lambda: _cmd_evidence_audit(args),
        ("compat", "generate"): lambda: _cmd_compat_generate(args),
        ("compat", "check"): lambda: _cmd_compat_check(args),
    }

    key = (args.command, getattr(args, args.command + "_command", None))
    if key in dispatch:
        return dispatch[key]()

    parser.print_help(sys.stderr)
    return 1


def _cmd_pack_validate(args):
    pack_dir = Path(args.pack_dir).resolve()
    if not pack_dir.exists():
        print(f"Error: pack directory not found: {pack_dir}", file=sys.stderr)
        return 1

    ok, errors = validate_pack(pack_dir)

    if ok:
        manifest = json.loads((pack_dir / "pack.json").read_text(encoding="utf-8"))
        print(f"  Pack: {manifest['id']} v{manifest['version']}", file=sys.stderr)
        print(f"  Skills: {len(manifest.get('skills', []))}", file=sys.stderr)
        print(f"  Validation: PASSED", file=sys.stderr)
        return 0
    else:
        print(f"  Validation: FAILED", file=sys.stderr)
        print(f"  {len(errors)} error(s):", file=sys.stderr)
        for err in errors:
            print(f"    - {err}", file=sys.stderr)
        return 1


def _cmd_repo_inspect(args):
    repo_root = Path(args.repo).resolve()
    if not repo_root.exists():
        print(f"Error: repository not found: {repo_root}", file=sys.stderr)
        return 1

    info = inspect_repo(repo_root)
    print_inspect_report(info, file=sys.stderr)
    return 0


def _cmd_mount_create(args):
    pack_dir = Path(args.pack).resolve()
    repo = Path(args.repo).resolve()

    if not pack_dir.exists():
        print(f"Error: pack directory not found: {pack_dir}", file=sys.stderr)
        return 1
    if not repo.exists():
        print(f"Error: repository not found: {repo}", file=sys.stderr)
        return 1

    ok, errors = validate_pack(pack_dir)
    if not ok:
        print(f"Error: pack validation failed:", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    try:
        session_info = materialize_session(
            pack_dir, str(repo), args.harness,
            skill_filter=args.skill,
        )
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    # Print session summary (no launch command)
    mount_plan = session_info["mount_plan"]
    exposed = mount_plan["skills"]["exposed"]
    print(f"Session materialized: {session_info['session_id']}", file=sys.stderr)
    print(f"  Dir:   {session_info['session_dir']}", file=sys.stderr)
    print(f"  Repo:  {mount_plan['repo']['path']}", file=sys.stderr)
    print(f"  Lock:  {session_info['lock']['pack_lock_hash']}", file=sys.stderr)
    print(f"  Skills ({len(exposed)}): {', '.join(exposed)}", file=sys.stderr)
    return 0


def _cmd_mount_verify(args):
    session_dir = Path(args.session_dir).resolve()
    lock_path = session_dir / "mount-lock.json"

    if not lock_path.exists():
        print(f"Error: mount-lock.json not found in {session_dir}", file=sys.stderr)
        return 1

    try:
        result = verify_lock(session_dir)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    if result["valid"]:
        print(f"Verification: PASSED", file=sys.stderr)
        print(f"  Files checked: {result['total_checked']}", file=sys.stderr)
        return 0
    else:
        print(f"Verification: FAILED", file=sys.stderr)
        if result["mismatch"]:
            print(f"  Hash mismatch ({len(result['mismatch'])}):", file=sys.stderr)
            for p in result["mismatch"]:
                print(f"    - {p}", file=sys.stderr)
        if result["missing"]:
            print(f"  Missing ({len(result['missing'])}):", file=sys.stderr)
            for p in result["missing"]:
                print(f"    - {p}", file=sys.stderr)
        if result["extra"]:
            print(f"  Extra files ({len(result['extra'])}):", file=sys.stderr)
            for p in result["extra"]:
                print(f"    - {p}", file=sys.stderr)
        return 1


def _cmd_run(args):
    pack_dir = Path(args.pack).resolve()
    repo = Path(args.repo).resolve()

    if not pack_dir.exists():
        print(f"Error: pack directory not found: {pack_dir}", file=sys.stderr)
        return 1
    if not repo.exists():
        print(f"Error: repository not found: {repo}", file=sys.stderr)
        return 1

    ok, errors = validate_pack(pack_dir)
    if not ok:
        print(f"Error: pack validation failed:", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    try:
        session_info = materialize_session(
            pack_dir, str(repo), args.harness,
            skill_filter=args.skill,
        )
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    return launch_session(session_info, dry_run=args.dry_run)


def _cmd_evidence_audit(args):
    repo_root = Path(args.repo).resolve()
    if not repo_root.exists():
        print(f"Error: repository not found: {repo_root}", file=sys.stderr)
        return 1

    output_path = Path(args.output) if args.output else None

    try:
        evidence = run_audit(
            repo_root=repo_root,
            output_path=output_path,
            pretty=args.pretty,
            quiet=args.quiet,
        )
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    # Exit 1 only if all providers failed
    errors = evidence.get("errors", [])
    if len(errors) == 3:
        return 1
    return 0


def _cmd_compat_generate(args):
    pack_dir = Path(args.pack).resolve()
    repo_root = Path.cwd()

    if not pack_dir.exists():
        print(f"Error: pack directory not found: {pack_dir}", file=sys.stderr)
        return 1

    try:
        count = compat_generate(pack_dir, repo_root)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    print(f"Compatibility directories generated.", file=sys.stderr)
    print(f"  Files copied: {count}", file=sys.stderr)
    print(f"  From: {pack_dir}", file=sys.stderr)
    print(f"  To:   .claude/skills/", file=sys.stderr)
    return 0


def _cmd_compat_check(args):
    pack_dir = Path(args.pack).resolve()
    repo_root = Path.cwd()

    if not pack_dir.exists():
        print(f"Error: pack directory not found: {pack_dir}", file=sys.stderr)
        return 1

    ok, issues = compat_check(pack_dir, repo_root)
    if ok:
        print(f"Compatibility check: PASSED", file=sys.stderr)
        return 0
    else:
        print(f"Compatibility check: FAILED", file=sys.stderr)
        for issue in issues:
            print(f"  - {issue}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
