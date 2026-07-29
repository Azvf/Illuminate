"""Illuminate CLI — main entry point.

Commands:
    illuminate pack validate <pack_dir>
    illuminate repo inspect --repo <path>
    illuminate mount create --pack <dir> --repo <path> [--harness claude-code]
    illuminate run --pack <dir> --repo <path> [--harness claude-code]
    illuminate evidence audit --repo <path> [--pretty] [--output <path>]
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


def main():
    parser = argparse.ArgumentParser(
        prog="illuminate",
        description="Illuminate Harness Knowledge Pack CLI",
    )
    parser.add_argument("--version", action="version", version=f"illuminate {__version__}")

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # pack validate
    pack_parser = subparsers.add_parser("pack", help="Pack operations")
    pack_sub = pack_parser.add_subparsers(dest="pack_command")
    validate_parser = pack_sub.add_parser("validate", help="Validate a pack directory")
    validate_parser.add_argument("pack_dir", help="Path to the pack directory")

    # repo inspect
    repo_parser = subparsers.add_parser("repo", help="Repository operations")
    repo_sub = repo_parser.add_subparsers(dest="repo_command")
    inspect_parser = repo_sub.add_parser("inspect", help="Inspect a target repository")
    inspect_parser.add_argument("--repo", default=".", help="Repository root path")

    # mount create
    mount_parser = subparsers.add_parser("mount", help="Mount operations")
    mount_sub = mount_parser.add_subparsers(dest="mount_command")
    create_parser = mount_sub.add_parser("create", help="Create a session mount")
    create_parser.add_argument("--pack", required=True, help="Path to the pack directory")
    create_parser.add_argument("--repo", required=True, help="Target repository path")
    create_parser.add_argument("--harness", default="claude-code", help="Target harness")

    # run
    run_parser = subparsers.add_parser("run", help="Materialize and launch a session")
    run_parser.add_argument("--pack", required=True, help="Path to the pack directory")
    run_parser.add_argument("--repo", required=True, help="Target repository path")
    run_parser.add_argument("--harness", default="claude-code", help="Target harness")

    # evidence audit
    evidence_parser = subparsers.add_parser("evidence", help="Evidence operations")
    evidence_sub = evidence_parser.add_subparsers(dest="evidence_command")
    audit_parser = evidence_sub.add_parser("audit", help="Run evidence audit on a repository")
    audit_parser.add_argument("--repo", default=".", help="Repository root path")
    audit_parser.add_argument("--output", "-o", default=None, help="Output file path")
    audit_parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON")
    audit_parser.add_argument("--quiet", action="store_true", help="Suppress summary")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help(sys.stderr)
        return 1

    if args.command == "pack" and args.pack_command == "validate":
        return _cmd_pack_validate(args)
    elif args.command == "repo" and args.repo_command == "inspect":
        return _cmd_repo_inspect(args)
    elif args.command == "mount" and args.mount_command == "create":
        return _cmd_mount_create(args)
    elif args.command == "run":
        return _cmd_run(args)
    elif args.command == "evidence" and args.evidence_command == "audit":
        return _cmd_evidence_audit(args)
    else:
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

    session_info = materialize_session(pack_dir, str(repo), args.harness)
    launch_session(session_info)
    return 0


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

    session_info = materialize_session(pack_dir, str(repo), args.harness)
    launch_session(session_info)
    return 0


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


if __name__ == "__main__":
    sys.exit(main())
