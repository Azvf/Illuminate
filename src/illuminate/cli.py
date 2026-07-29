"""Illuminate CLI — main entry point.

Commands:
    illuminate pack validate <pack_dir>
    illuminate repo inspect --repo <path>
    illuminate mount create --pack <dir> --repo <path> [--harness claude-code]
    illuminate mount verify <session-dir>
    illuminate mount remove <session-dir-or-id>
    illuminate run --pack <dir> --repo <path> [--harness claude-code] [--skill <id>...] [--dry-run]
    illuminate evidence audit --repo <path> [--pretty] [--output <path>]
    illuminate compat generate [--pack <dir>]
    illuminate compat check [--pack <dir>]
    illuminate sync codex --repo <path> [--pack <dir>] [--skill <id>...]
    illuminate sync check --repo <path> [--pack <dir>]
    illuminate sync clean --repo <path>
"""

import argparse
import json
import shutil
import sys
from pathlib import Path

from . import __version__
from .validate import validate_pack
from .inspect_repo import inspect_repo, print_inspect_report
from .materialize_claude import materialize_session, launch_session
from .evidence.audit import run_audit
from .lockfile import load_lock, verify_lock
from .compat import compat_generate, compat_check
from .sync_codex import sync_codex, check_sync, clean_sync


_SESSION_BASE = Path.home() / ".illuminate" / "sessions"


# ---------------------------------------------------------------------------
# CLI argument parsing
# ---------------------------------------------------------------------------

def _build_parser():
    parser = argparse.ArgumentParser(
        prog="illuminate",
        description="Illuminate Harness Knowledge Pack CLI",
    )
    parser.add_argument("--version", action="version", version=f"illuminate {__version__}")
    sub = parser.add_subparsers(dest="command", help="Available commands")

    # pack validate
    p = sub.add_parser("pack", help="Pack operations")
    ps = p.add_subparsers(dest="pack_command")
    v = ps.add_parser("validate", help="Validate a pack directory")
    v.add_argument("pack_dir", help="Path to the pack directory")

    # repo inspect
    p = sub.add_parser("repo", help="Repository operations")
    ps = p.add_subparsers(dest="repo_command")
    i = ps.add_parser("inspect", help="Inspect a target repository")
    i.add_argument("--repo", default=".", help="Repository root path")

    # mount create / verify / remove
    p = sub.add_parser("mount", help="Mount operations")
    ps = p.add_subparsers(dest="mount_command")

    c = ps.add_parser("create", help="Create a session mount")
    c.add_argument("--pack", required=True, help="Path to the pack directory")
    c.add_argument("--repo", required=True, help="Target repository path")
    c.add_argument("--harness", default="claude-code", choices=["claude-code", "codex"],
                   help="Target harness (default: claude-code)")
    c.add_argument("--skill", action="append", default=None,
                   help="Skill ID to expose (repeatable)")

    v = ps.add_parser("verify", help="Verify session mount integrity")
    v.add_argument("session_dir", help="Path to the session directory")

    r = ps.add_parser("remove", help="Remove a session and its external artifacts")
    r.add_argument("session_dir", help="Session directory path or session ID")

    # run
    p = sub.add_parser("run", help="Materialize and launch a session")
    p.add_argument("--pack", required=True, help="Path to the pack directory")
    p.add_argument("--repo", required=True, help="Target repository path")
    p.add_argument("--harness", default="claude-code", choices=["claude-code", "codex"],
                   help="Target harness (default: claude-code)")
    p.add_argument("--skill", action="append", default=None,
                   help="Skill ID to expose (repeatable)")
    p.add_argument("--dry-run", action="store_true",
                   help="Print launch command without executing")

    # evidence audit
    p = sub.add_parser("evidence", help="Evidence operations")
    ps = p.add_subparsers(dest="evidence_command")
    a = ps.add_parser("audit", help="Run evidence audit on a repository")
    a.add_argument("--repo", default=".", help="Repository root path")
    a.add_argument("--output", "-o", default=None, help="Output file path")
    a.add_argument("--pretty", action="store_true", help="Pretty-print JSON")
    a.add_argument("--quiet", action="store_true", help="Suppress summary")

    # compat
    p = sub.add_parser("compat", help="Legacy compatibility operations")
    ps = p.add_subparsers(dest="compat_command")
    cg = ps.add_parser("generate", help="Generate legacy compatibility dirs from canonical sources")
    cg.add_argument("--pack", default="packs/core", help="Pack directory path")
    cc = ps.add_parser("check", help="Check legacy compatibility dirs exist and are in sync")
    cc.add_argument("--pack", default="packs/core", help="Pack directory path")

    # sync codex / check / clean
    p = sub.add_parser("sync", help="Synchronize Pack into target repository")
    ps = p.add_subparsers(dest="sync_command")

    sc = ps.add_parser("codex", help="Synchronize for Codex App (AGENTS.md + .agents/skills + openai.yaml)")
    sc.add_argument("--pack", default="packs/core", help="Pack directory path")
    sc.add_argument("--repo", required=True, help="Target repository path")
    sc.add_argument("--skill", action="append", default=None,
                    help="Skill ID to sync (repeatable; default: all non-alias)")

    sch = ps.add_parser("check", help="Verify Codex sync integrity")
    sch.add_argument("--pack", default="packs/core", help="Pack directory path")
    sch.add_argument("--repo", required=True, help="Target repository path")

    scl = ps.add_parser("clean", help="Remove all Illuminate-synced artifacts from a repository")
    scl.add_argument("--repo", required=True, help="Target repository path")

    return parser


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def _validate_pack_and_repo(pack_dir, repo):
    """Validate pack and repo paths. Returns (exit_code, error_message) or (0, None)."""
    if not pack_dir.exists():
        print(f"Error: pack directory not found: {pack_dir}", file=sys.stderr)
        return 1
    if not repo.exists():
        print(f"Error: repository not found: {repo}", file=sys.stderr)
        return 1
    ok, errors = validate_pack(pack_dir)
    if not ok:
        print("Error: pack validation failed:", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1
    return 0


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

def _cmd_pack_validate(args):
    pack_dir = Path(args.pack_dir).resolve()
    if not pack_dir.exists():
        print(f"Error: pack directory not found: {pack_dir}", file=sys.stderr)
        return 1
    ok, errors = validate_pack(pack_dir)
    if ok:
        m = json.loads((pack_dir / "pack.json").read_text(encoding="utf-8"))
        print(f"  Pack: {m['id']} v{m['version']}", file=sys.stderr)
        print(f"  Skills: {len(m.get('skills', []))}", file=sys.stderr)
        print(f"  Validation: PASSED", file=sys.stderr)
        return 0
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

    exit_code = _validate_pack_and_repo(pack_dir, repo)
    if exit_code:
        return 1

    if args.harness == "codex":
        try:
            info = materialize_codex_session(pack_dir, str(repo), args.harness, skill_filter=args.skill)
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1

        mp = info["mount_plan"]
        print(f"Session materialized: {info['session_id']}", file=sys.stderr)
        print(f"  Harness: codex", file=sys.stderr)
        print(f"  Dir:     {info['session_dir']}", file=sys.stderr)
        print(f"  Profile: {info['profile_name']}", file=sys.stderr)
        print(f"  Repo:    {mp['repo']['path']}", file=sys.stderr)
        print(f"  Lock:    {info['lock']['pack_lock_hash']}", file=sys.stderr)
        print(f"  Skills:  {', '.join(mp['skills']['exposed'])}", file=sys.stderr)
        return 0

    # default: claude-code
    try:
        info = materialize_session(pack_dir, str(repo), args.harness, skill_filter=args.skill)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    mp = info["mount_plan"]
    print(f"Session materialized: {info['session_id']}", file=sys.stderr)
    print(f"  Harness: claude-code", file=sys.stderr)
    print(f"  Dir:     {info['session_dir']}", file=sys.stderr)
    print(f"  Repo:    {mp['repo']['path']}", file=sys.stderr)
    print(f"  Lock:    {info['lock']['pack_lock_hash']}", file=sys.stderr)
    print(f"  Skills:  {', '.join(mp['skills']['exposed'])}", file=sys.stderr)
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
    if result.get("external_mismatch"):
        print(f"  External hash mismatch ({len(result['external_mismatch'])}):", file=sys.stderr)
        for p in result["external_mismatch"]:
            print(f"    - {p}", file=sys.stderr)
    return 1


def _cmd_mount_remove(args):
    # Resolve session path: direct path or by ID
    session_path = Path(args.session_dir)
    if not session_path.exists():
        # Try as session ID under ~/.illuminate/sessions/
        session_path = _SESSION_BASE / args.session_dir
    if not session_path.exists():
        print(f"Error: session not found: {args.session_dir}", file=sys.stderr)
        return 1

    lock_path = session_path / "mount-lock.json"
    external_files = []
    if lock_path.exists():
        try:
            lock = load_lock(session_path)
            external_files = [
                (ext["role"], Path(ext["path"]))
                for ext in lock.get("external_files", [])
            ]
        except Exception:
            pass

    # Delete external files
    for role, ext_path in external_files:
        if ext_path.exists():
            ext_path.unlink()
            print(f"  Removed {role}: {ext_path}", file=sys.stderr)

    # Delete session directory
    shutil.rmtree(session_path)
    print(f"  Removed session: {session_path}", file=sys.stderr)
    return 0


def _cmd_run(args):
    pack_dir = Path(args.pack).resolve()
    repo = Path(args.repo).resolve()

    exit_code = _validate_pack_and_repo(pack_dir, repo)
    if exit_code:
        return 1

    if args.harness == "codex":
        try:
            info = materialize_codex_session(pack_dir, str(repo), args.harness, skill_filter=args.skill)
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1
        return launch_codex_session(info, dry_run=args.dry_run)

    # default: claude-code
    try:
        info = materialize_session(pack_dir, str(repo), args.harness, skill_filter=args.skill)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    return launch_session(info, dry_run=args.dry_run)


def _cmd_evidence_audit(args):
    repo_root = Path(args.repo).resolve()
    if not repo_root.exists():
        print(f"Error: repository not found: {repo_root}", file=sys.stderr)
        return 1
    output_path = Path(args.output) if args.output else None
    try:
        evidence = run_audit(
            repo_root=repo_root, output_path=output_path,
            pretty=args.pretty, quiet=args.quiet,
        )
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    errors = evidence.get("errors", [])
    if len(errors) == 3:
        return 1
    return 0


def _cmd_compat_generate(args):
    pack_dir = Path(args.pack).resolve()
    if not pack_dir.exists():
        print(f"Error: pack directory not found: {pack_dir}", file=sys.stderr)
        return 1
    try:
        count = compat_generate(pack_dir, Path.cwd())
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    print("Compatibility directories generated.", file=sys.stderr)
    print(f"  Files copied: {count}", file=sys.stderr)
    print(f"  From: {pack_dir}", file=sys.stderr)
    print(f"  To:   .claude/skills/", file=sys.stderr)
    return 0


def _cmd_compat_check(args):
    pack_dir = Path(args.pack).resolve()
    if not pack_dir.exists():
        print(f"Error: pack directory not found: {pack_dir}", file=sys.stderr)
        return 1
    ok, issues = compat_check(pack_dir, Path.cwd())
    if ok:
        print("Compatibility check: PASSED", file=sys.stderr)
        return 0
    print("Compatibility check: FAILED", file=sys.stderr)
    for issue in issues:
        print(f"  - {issue}", file=sys.stderr)
    return 1


def _cmd_sync_codex(args):
    pack_dir = Path(args.pack).resolve()
    repo = Path(args.repo).resolve()

    if not pack_dir.exists():
        print(f"Error: pack directory not found: {pack_dir}", file=sys.stderr)
        return 1
    if not repo.exists():
        print(f"Error: repository not found: {repo}", file=sys.stderr)
        return 1

    try:
        result = sync_codex(pack_dir, repo, skill_filter=args.skill)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    print(f"Codex sync: COMPLETE", file=sys.stderr)
    print(f"  Pack:     {result['pack_id']} v{result['pack_version']}", file=sys.stderr)
    print(f"  Skills:   {result['skill_count']} ({', '.join(result['exposed_skills'])})", file=sys.stderr)
    print(f"  Files:    {result['files_copied']} copied", file=sys.stderr)
    print(f"  AGENTS:   {'modified' if result['agents_modified'] else 'no change'}", file=sys.stderr)
    if result.get("stale_skills_removed"):
        print(f"  Stale:    removed {', '.join(result['stale_skills_removed'])}", file=sys.stderr)
    return 0


def _cmd_sync_check(args):
    pack_dir = Path(args.pack).resolve()
    repo = Path(args.repo).resolve()

    if not pack_dir.exists():
        print(f"Error: pack directory not found: {pack_dir}", file=sys.stderr)
        return 1
    if not repo.exists():
        print(f"Error: repository not found: {repo}", file=sys.stderr)
        return 1

    ok, issues = check_sync(pack_dir, repo)
    if ok:
        print("Sync check: PASSED", file=sys.stderr)
        return 0
    print("Sync check: FAILED", file=sys.stderr)
    for issue in issues:
        print(f"  - {issue}", file=sys.stderr)
    return 1


def _cmd_sync_clean(args):
    repo = Path(args.repo).resolve()
    if not repo.exists():
        print(f"Error: repository not found: {repo}", file=sys.stderr)
        return 1

    result = clean_sync(repo)
    removed = result.get("removed_artifacts", [])
    if removed:
        print("Clean: COMPLETE", file=sys.stderr)
        for item in removed:
            print(f"  Removed: {item}", file=sys.stderr)
    else:
        print("Clean: nothing to remove", file=sys.stderr)
    return 0


# ---------------------------------------------------------------------------
# Main dispatch
# ---------------------------------------------------------------------------

_DISPATCH = {
    ("pack", "validate"): _cmd_pack_validate,
    ("repo", "inspect"): _cmd_repo_inspect,
    ("mount", "create"): _cmd_mount_create,
    ("mount", "verify"): _cmd_mount_verify,
    ("mount", "remove"): _cmd_mount_remove,
    ("run",): _cmd_run,
    ("evidence", "audit"): _cmd_evidence_audit,
    ("compat", "generate"): _cmd_compat_generate,
    ("compat", "check"): _cmd_compat_check,
    ("sync", "codex"): _cmd_sync_codex,
    ("sync", "check"): _cmd_sync_check,
    ("sync", "clean"): _cmd_sync_clean,
}


def main():
    parser = _build_parser()
    args = parser.parse_args()

    if args.command is None:
        parser.print_help(sys.stderr)
        return 1

    key = (args.command, getattr(args, args.command + "_command", None))
    handler = _DISPATCH.get(key)
    if handler:
        return handler(args)

    parser.print_help(sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
