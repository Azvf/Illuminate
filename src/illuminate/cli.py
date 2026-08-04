"""Illuminate CLI — main entry point.

Commands:
    illuminate pack validate <pack_dir>
    illuminate repo inspect --repo <path>
    illuminate mount create --pack <dir> --repo <path> [--skill <id>...]
    illuminate mount verify <session-dir>
    illuminate mount remove <session-dir-or-id>
    illuminate run --pack <dir> --repo <path> [--skill <id>...] [--dry-run]
    illuminate evidence audit --repo <path> [--pretty] [--output <path>]
    illuminate compat generate [--pack <dir>]
    illuminate compat check [--pack <dir>]
    illuminate sync codex --repo <path> [--pack <dir>] [--skill <id>...]
    illuminate sync codebuddy --repo <path> [--pack <dir>] [--skill <id>...]
    illuminate sync cursor --repo <path> [--pack <dir>] [--skill <id>...] [--agents-compat]
    illuminate sync check --repo <path> [--pack <dir>]
    illuminate sync clean --repo <path>
    illuminate sync doctor --repo <path> --harness cursor
    illuminate knowledge pull --repo <path> [--store <dir>] [--manifest <json>]
    illuminate knowledge status --repo <path> [--store <dir>] [--manifest <json>]
    illuminate knowledge push --repo <path> [--store <dir>] [--manifest <json>] [--force]
    illuminate knowledge candidate --repo <path> --source <path> --target <kind> [--anchor <ref>] [--notes <text>] [--store <dir>]
    illuminate knowledge review --repo <path> --id <id> [--reviewer <name>] [--notes <text>] [--store <dir>]
    illuminate knowledge promote --repo <path> --id <id> --pack <dir> [--target-path <path>] [--content <path>] [--dry-run] [--force] [--store <dir>]
    illuminate knowledge reject --repo <path> --id <id> [--reviewer <name>] [--superseded] [--notes <text>] [--store <dir>]
    illuminate docs export-human --source <dir> --output <dir> [--config <json>]
    illuminate docs lint-human --source <dir> [--config <json>] [--all-markdown]
    illuminate docs lint-knowledge --source <dir> [--config <json>]
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
from .sync_codex import sync_codex, check_sync as check_codex_sync, clean_sync as clean_codex_sync
from .sync_codebuddy import sync_codebuddy, check_sync as check_codebuddy_sync, clean_sync as clean_codebuddy_sync
from .sync_cursor import (
    sync_cursor,
    check_sync as check_cursor_sync,
    clean_sync as clean_cursor_sync,
    doctor_sync as doctor_cursor_sync,
)
from .knowledge_store import knowledge_pull, knowledge_status, knowledge_push
from .promotion import (
    PromotionError,
    knowledge_candidate,
    knowledge_review,
    knowledge_promote,
    knowledge_reject,
)
from .docs_export import export_human, DocsExportError
from .docs_lint import format_lint_errors, lint_human
from .knowledge_lint import format_knowledge_lint_errors, lint_knowledge


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

    c = ps.add_parser("create", help="Create a Claude Code session mount")
    c.add_argument("--pack", required=True, help="Path to the pack directory")
    c.add_argument("--repo", required=True, help="Target repository path")
    c.add_argument("--skill", action="append", default=None,
                   help="Skill ID to expose (repeatable)")

    v = ps.add_parser("verify", help="Verify session mount integrity")
    v.add_argument("session_dir", help="Path to the session directory")

    r = ps.add_parser("remove", help="Remove a session and its external artifacts")
    r.add_argument("session_dir", help="Session directory path or session ID")

    # run
    p = sub.add_parser("run", help="Materialize and launch a Claude Code session")
    p.add_argument("--pack", required=True, help="Path to the pack directory")
    p.add_argument("--repo", required=True, help="Target repository path")
    p.add_argument("--skill", action="append", default=None,
                   help="Skill ID to expose (repeatable)")
    p.add_argument("--dry-run", action="store_true",
                   help="Print launch command without executing")

    # evidence audit
    p = sub.add_parser("evidence", help="Evidence operations")
    ps = p.add_subparsers(dest="evidence_command")
    a = ps.add_parser("audit", help="Run evidence audit on a repository")
    a.add_argument("--repo", default=".", help="Repository root path")
    a.add_argument("--pack", default=None,
                   help="Pack directory to bind the report's pack identity to")
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

    # sync codex / codebuddy / check / clean
    p = sub.add_parser("sync", help="Synchronize Pack into target repository")
    ps = p.add_subparsers(dest="sync_command")

    sc = ps.add_parser("codex", help="Synchronize for Codex App (AGENTS.md + .agents/skills + openai.yaml)")
    sc.add_argument("--pack", default="packs/core", help="Pack directory path")
    sc.add_argument("--repo", required=True, help="Target repository path")
    sc.add_argument("--skill", action="append", default=None,
                    help="Skill ID to sync (repeatable; default: all non-alias)")

    scb = ps.add_parser("codebuddy", help="Synchronize for CodeBuddy (.codebuddy/rules/illuminate/ + skills + commands)")
    scb.add_argument("--pack", default="packs/core", help="Pack directory path")
    scb.add_argument("--repo", required=True, help="Target repository path")
    scb.add_argument("--skill", action="append", default=None,
                     help="Skill ID to sync (repeatable; default: all non-alias)")

    scu = ps.add_parser("cursor", help="Synchronize for Cursor (.cursor/rules + .cursor/skills + commands)")
    scu.add_argument("--pack", default="packs/core", help="Pack directory path")
    scu.add_argument("--repo", required=True, help="Target repository path")
    scu.add_argument("--skill", action="append", default=None,
                     help="Skill ID to sync (repeatable; default: all non-alias)")
    scu.add_argument("--agents-compat", action="store_true",
                     help="Merge into the root AGENTS.md instead of writing "
                          ".cursor/rules/illuminate/core.mdc (for projects sharing AGENTS.md with Codex)")

    sch = ps.add_parser("check", help="Verify sync integrity for Codex, CodeBuddy, or Cursor")
    sch.add_argument("--pack", default="packs/core", help="Pack directory path")
    sch.add_argument("--repo", required=True, help="Target repository path")
    sch.add_argument("--harness", choices=["codex", "codebuddy", "cursor"], default="codex",
                     help="Harness to check (default: codex)")

    scl = ps.add_parser("clean", help="Remove all Illuminate-synced artifacts from a repository")
    scl.add_argument("--repo", required=True, help="Target repository path")
    scl.add_argument("--harness", choices=["codex", "codebuddy", "cursor"], default="codex",
                     help="Harness to clean (default: codex)")

    sdo = ps.add_parser("doctor", help="Read-only diagnostic of a repository sync state")
    sdo.add_argument("--repo", required=True, help="Target repository path")
    sdo.add_argument("--harness", choices=["cursor"], default="cursor",
                     help="Harness to diagnose (only 'cursor' is currently supported)")

    # knowledge pull / status / push
    p = sub.add_parser("knowledge", help="Knowledge store operations")
    ps = p.add_subparsers(dest="knowledge_command")

    kp = ps.add_parser("pull", help="Pull project knowledge docs to central store")
    kp.add_argument("--repo", required=True, help="Target repository path")
    kp.add_argument("--store", default=None, help="Central store directory (default: ~/.illuminate/knowledge)")
    kp.add_argument("--manifest", default=None, help="Knowledge manifest JSON path")

    ks = ps.add_parser("status", help="Compare project knowledge docs with central store")
    ks.add_argument("--repo", required=True, help="Target repository path")
    ks.add_argument("--store", default=None, help="Central store directory (default: ~/.illuminate/knowledge)")
    ks.add_argument("--manifest", default=None, help="Knowledge manifest JSON path")

    kpush = ps.add_parser("push", help="Push store documents back to project (recovery)")
    kpush.add_argument("--repo", required=True, help="Target repository path")
    kpush.add_argument("--store", default=None, help="Central store directory (default: ~/.illuminate/knowledge)")
    kpush.add_argument("--manifest", default=None, help="Knowledge manifest JSON path")
    kpush.add_argument("--force", action="store_true", help="Override conflicts")

    kc = ps.add_parser("candidate", help="Create a promotion candidate from a knowledge source")
    kc.add_argument("--repo", required=True, help="Target repository path")
    kc.add_argument("--source", required=True, help="Source knowledge path relative to repo/docs/")
    kc.add_argument("--target", required=True, choices=["policy", "skill", "reference", "evidence"],
                    help="Target pack content kind")
    kc.add_argument("--anchor", default=None, help="Anchor reference for the candidate")
    kc.add_argument("--notes", default=None, help="Free-form notes for the candidate")
    kc.add_argument("--store", default=None, help="Central store directory (default: ~/.illuminate/knowledge)")

    kr = ps.add_parser("review", help="Record a review verdict for a candidate")
    kr.add_argument("--repo", required=True, help="Target repository path")
    kr.add_argument("--id", required=True, help="Candidate ID")
    kr.add_argument("--reviewer", default=None, help="Reviewer name")
    kr.add_argument("--notes", default=None, help="Review notes")
    kr.add_argument("--store", default=None, help="Central store directory (default: ~/.illuminate/knowledge)")

    kpm = ps.add_parser("promote", help="Promote a reviewed candidate into a pack")
    kpm.add_argument("--repo", required=True, help="Target repository path")
    kpm.add_argument("--id", required=True, help="Candidate ID")
    kpm.add_argument("--pack", required=True, help="Pack directory to promote into")
    kpm.add_argument("--target-path", default=None, help="Pack-relative target path (default: <kind>s/<source path>)")
    kpm.add_argument("--content", default=None, help="Generalized content file path (CWD-relative; default: candidate source doc)")
    kpm.add_argument("--dry-run", action="store_true", help="Print the promotion plan without writing")
    kpm.add_argument("--force", action="store_true", help="Overwrite an existing pack file")
    kpm.add_argument("--store", default=None, help="Central store directory (default: ~/.illuminate/knowledge)")

    krj = ps.add_parser("reject", help="Reject a candidate (optionally superseded)")
    krj.add_argument("--repo", required=True, help="Target repository path")
    krj.add_argument("--id", required=True, help="Candidate ID")
    krj.add_argument("--reviewer", default=None, help="Reviewer name")
    krj.add_argument("--superseded", action="store_true", help="Mark the candidate as superseded")
    krj.add_argument("--notes", default=None, help="Rejection notes")
    krj.add_argument("--store", default=None, help="Central store directory (default: ~/.illuminate/knowledge)")

    # docs export-human / lint-human
    p = sub.add_parser("docs", help="Documentation operations")
    ps = p.add_subparsers(dest="docs_command")
    de = ps.add_parser("export-human", help="Copy configured human-readable Markdown docs")
    de.add_argument("--source", required=True, help="Documentation source root")
    de.add_argument("--output", required=True, help="Export output directory")
    de.add_argument("--config", default=None, help="JSON config path (default: <source>/human-docs.json if present)")
    de.add_argument("--force", action="store_true", help="Replace a non-empty output directory")
    dl = ps.add_parser("lint-human", help="Lint human-readable Markdown docs")
    dl.add_argument("--source", required=True, help="Documentation root or export directory")
    dl.add_argument("--config", default=None, help="JSON config path")
    dl.add_argument("--all-markdown", action="store_true", help="Lint every Markdown file below source")
    dk = ps.add_parser("lint-knowledge", help="Lint knowledge metadata and doc_refs")
    dk.add_argument("--source", required=True, help="Documentation root")
    dk.add_argument("--config", default=None, help="JSON config path")

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

    try:
        info = materialize_session(pack_dir, str(repo), skill_filter=args.skill)
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

    try:
        info = materialize_session(pack_dir, str(repo), skill_filter=args.skill)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    return launch_session(info, dry_run=args.dry_run)


def _cmd_evidence_audit(args):
    repo_root = Path(args.repo).resolve()
    if not repo_root.exists():
        print(f"Error: repository not found: {repo_root}", file=sys.stderr)
        return 1
    pack_dir = None
    if args.pack:
        pack_dir = Path(args.pack).resolve()
        if not pack_dir.exists():
            print(f"Error: pack directory not found: {pack_dir}", file=sys.stderr)
            return 1
        ok, pack_errors = validate_pack(pack_dir)
        if not ok:
            print(f"Error: --pack is not a valid pack: {pack_dir}", file=sys.stderr)
            for err in pack_errors[:5]:
                print(f"  - {err}", file=sys.stderr)
            return 1
    output_path = Path(args.output) if args.output else None
    try:
        evidence = run_audit(
            repo_root=repo_root, output_path=output_path,
            pretty=args.pretty, quiet=args.quiet,
            pack_dir=pack_dir,
        )
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    errors = evidence.get("errors", [])
    if errors:
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


def _cmd_sync_codebuddy(args):
    pack_dir = Path(args.pack).resolve()
    repo = Path(args.repo).resolve()

    if not pack_dir.exists():
        print(f"Error: pack directory not found: {pack_dir}", file=sys.stderr)
        return 1
    if not repo.exists():
        print(f"Error: repository not found: {repo}", file=sys.stderr)
        return 1

    try:
        result = sync_codebuddy(pack_dir, repo, skill_filter=args.skill)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    print(f"CodeBuddy sync: COMPLETE", file=sys.stderr)
    print(f"  Pack:     {result['pack_id']} v{result['pack_version']}", file=sys.stderr)
    print(f"  Skills:   {', '.join(result['exposed_skills'])}", file=sys.stderr)
    print(f"  Rules:    {result['rules_copied']} files", file=sys.stderr)
    print(f"  Skills:   {result['skills_copied']} synced", file=sys.stderr)
    print(f"  Commands: {result['commands_copied']} synced", file=sys.stderr)
    print(f"  CODEBUDDY:{' modified' if result['codebuddy_modified'] else ' no change'}", file=sys.stderr)
    return 0


def _cmd_sync_cursor(args):
    pack_dir = Path(args.pack).resolve()
    repo = Path(args.repo).resolve()

    if not pack_dir.exists():
        print(f"Error: pack directory not found: {pack_dir}", file=sys.stderr)
        return 1
    if not repo.exists():
        print(f"Error: repository not found: {repo}", file=sys.stderr)
        return 1

    try:
        result = sync_cursor(
            pack_dir, repo, skill_filter=args.skill, agents_compat=args.agents_compat
        )
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    mode = "AGENTS.md" if result["agents_compat"] else ".cursor/rules/illuminate/core.mdc"
    print(f"Cursor sync: COMPLETE", file=sys.stderr)
    print(f"  Pack:     {result['pack_id']} v{result['pack_version']}", file=sys.stderr)
    print(f"  Skills:   {', '.join(result['exposed_skills'])}", file=sys.stderr)
    print(f"  Skills:   {result['skills_copied']} synced", file=sys.stderr)
    print(f"  Commands: {result['commands_copied']} synced", file=sys.stderr)
    print(f"  Rules:    {mode} {'written' if result['rules_modified'] else 'no change'}", file=sys.stderr)
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

    if getattr(args, 'harness', 'codex') == 'codebuddy':
        ok, issues = check_codebuddy_sync(pack_dir, repo)
        label = "CodeBuddy"
    elif getattr(args, 'harness', 'codex') == 'cursor':
        ok, issues = check_cursor_sync(pack_dir, repo)
        label = "Cursor"
    else:
        ok, issues = check_codex_sync(pack_dir, repo)
        label = "Codex"

    if ok:
        print(f"Sync check ({label}): PASSED", file=sys.stderr)
        return 0
    print(f"Sync check ({label}): FAILED", file=sys.stderr)
    for issue in issues:
        print(f"  - {issue}", file=sys.stderr)
    return 1


def _cmd_sync_clean(args):
    repo = Path(args.repo).resolve()
    if not repo.exists():
        print(f"Error: repository not found: {repo}", file=sys.stderr)
        return 1

    if getattr(args, 'harness', 'codex') == 'codebuddy':
        result = clean_codebuddy_sync(repo)
        label = "CodeBuddy"
    elif getattr(args, 'harness', 'codex') == 'cursor':
        result = clean_cursor_sync(repo)
        label = "Cursor"
    else:
        result = clean_codex_sync(repo)
        label = "Codex"

    removed = result.get("removed_artifacts", [])
    if removed:
        print(f"Clean ({label}): COMPLETE", file=sys.stderr)
        for item in removed:
            print(f"  Removed: {item}", file=sys.stderr)
    else:
        print(f"Clean ({label}): nothing to remove", file=sys.stderr)
    return 0


def _cmd_sync_doctor(args):
    repo = Path(args.repo).resolve()
    if not repo.exists():
        print(f"Error: repository not found: {repo}", file=sys.stderr)
        return 1

    report = doctor_cursor_sync(repo)

    print(f"Cursor sync doctor: {repo}", file=sys.stderr)
    print(f"  Lock present:  {report['lock_exists']}", file=sys.stderr)
    if report["lock_errors"]:
        for err in report["lock_errors"]:
            print(f"  Lock error:    {err}", file=sys.stderr)
    if report["mode"]:
        print(f"  Mode:          {report['mode']}", file=sys.stderr)
    if report["rules"] is not None:
        r = report["rules"]
        print(f"  Rules file:    {r['path']}", file=sys.stderr)
        print(f"    exists:      {r['exists']}", file=sys.stderr)
        if r["exists"]:
            print(f"    hash match:  {r['hash_matches']}", file=sys.stderr)
    if report["skills"]["missing"] or report["skills"]["hash_mismatch"]:
        for p in report["skills"]["missing"]:
            print(f"  Missing skill: {p}", file=sys.stderr)
        for p in report["skills"]["hash_mismatch"]:
            print(f"  Skill mismatch:{p}", file=sys.stderr)
    if report["commands"]["missing"] or report["commands"]["hash_mismatch"]:
        for p in report["commands"]["missing"]:
            print(f"  Missing cmd:   {p}", file=sys.stderr)
        for p in report["commands"]["hash_mismatch"]:
            print(f"  Cmd mismatch:  {p}", file=sys.stderr)
    for p in report["stale"]:
        print(f"  Stale:         {p}", file=sys.stderr)

    healthy = (
        report["lock_exists"]
        and not report["lock_errors"]
        and report["rules"] is not None
        and report["rules"]["exists"]
        and report["rules"]["hash_matches"]
        and not report["skills"]["missing"]
        and not report["skills"]["hash_mismatch"]
        and not report["commands"]["missing"]
        and not report["commands"]["hash_mismatch"]
    )
    if healthy:
        print(f"Cursor sync doctor: HEALTHY", file=sys.stderr)
        return 0
    print(f"Cursor sync doctor: PROBLEMS DETECTED", file=sys.stderr)
    return 1


def _cmd_knowledge_pull(args):
    repo = Path(args.repo).resolve()
    if not repo.exists():
        print(f"Error: repository not found: {repo}", file=sys.stderr)
        return 1
    store = Path(args.store) if args.store else None
    manifest = Path(args.manifest).resolve() if args.manifest else None

    try:
        result = knowledge_pull(repo, store=store, manifest_path=manifest)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    print(f"Knowledge pull: COMPLETE", file=sys.stderr)
    print(f"  Project:  {result['project_id']}", file=sys.stderr)
    print(f"  Total:    {result['total']} configured knowledge files", file=sys.stderr)
    print(f"  New:      {len(result['new'])}", file=sys.stderr)
    print(f"  Modified: {len(result['modified'])}", file=sys.stderr)
    print(f"  Deleted:  {len(result['deleted'])}", file=sys.stderr)
    print(f"  Conflicts:{len(result['conflicted'])}", file=sys.stderr)
    print(f"  Pulled:   {len(result['pulled'])}", file=sys.stderr)
    return 0


def _cmd_knowledge_status(args):
    repo = Path(args.repo).resolve()
    if not repo.exists():
        print(f"Error: repository not found: {repo}", file=sys.stderr)
        return 1
    store = Path(args.store) if args.store else None
    manifest = Path(args.manifest).resolve() if args.manifest else None

    try:
        result = knowledge_status(repo, store=store, manifest_path=manifest)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    print(f"Knowledge status for {result['project_name']}", file=sys.stderr)
    print(f"  Project: {result['project_id']}", file=sys.stderr)
    print(f"  Synced:  {len(result['synced'])}", file=sys.stderr)
    print(f"  New:     {len(result['new'])}", file=sys.stderr)
    if result['new']:
        for p in result['new']:
            print(f"    + {p}", file=sys.stderr)
    print(f"  Modified: {len(result['modified'])}", file=sys.stderr)
    if result['modified']:
        for p in result['modified']:
            print(f"    ~ {p}", file=sys.stderr)
    print(f"  Store modified: {len(result['store_modified'])}", file=sys.stderr)
    if result['store_modified']:
        for p in result['store_modified']:
            print(f"    ~ {p}", file=sys.stderr)
    print(f"  Deleted: {len(result['deleted'])}", file=sys.stderr)
    if result['deleted']:
        for p in result['deleted']:
            print(f"    - {p}", file=sys.stderr)
    if result['conflicted']:
        print(f"  Conflicts: {len(result['conflicted'])}", file=sys.stderr)
        for p in result['conflicted']:
            print(f"    ! {p}", file=sys.stderr)
    return 0


def _cmd_docs_export_human(args):
    source_root = Path(args.source).resolve()
    output_root = Path(args.output).resolve()
    config_path = Path(args.config).resolve() if args.config else None
    if config_path is None:
        candidate = source_root / "human-docs.json"
        config_path = candidate if candidate.is_file() else None
    try:
        result = export_human(
            source_root,
            output_root,
            config_path=config_path,
            force=args.force,
        )
    except DocsExportError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    print("Human documentation export: COMPLETE", file=sys.stderr)
    print(f"  Source:   {result['source']}", file=sys.stderr)
    print(f"  Output:   {result['output']}", file=sys.stderr)
    print(f"  Files:    {result['file_count']}", file=sys.stderr)
    return 0


def _cmd_docs_lint_human(args):
    source_root = Path(args.source).resolve()
    config_path = Path(args.config).resolve() if args.config else None
    if config_path is None and not args.all_markdown:
        candidate = source_root / "human-docs.json"
        config_path = candidate if candidate.is_file() else None
    errors = lint_human(
        source_root,
        config_path=config_path,
        all_markdown=args.all_markdown,
    )
    print(format_lint_errors(errors), file=sys.stderr)
    return 1 if errors else 0


def _cmd_docs_lint_knowledge(args):
    config_path = Path(args.config).resolve() if args.config else None
    errors = lint_knowledge(Path(args.source).resolve(), config_path=config_path)
    print(format_knowledge_lint_errors(errors), file=sys.stderr)
    return 1 if errors else 0


def _cmd_knowledge_push(args):
    repo = Path(args.repo).resolve()
    if not repo.exists():
        print(f"Error: repository not found: {repo}", file=sys.stderr)
        return 1
    store = Path(args.store) if args.store else None
    manifest = Path(args.manifest).resolve() if args.manifest else None

    try:
        result = knowledge_push(repo, store=store, force=args.force, manifest_path=manifest)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    if "error" in result:
        print(f"Push: FAILED - {result['error']}", file=sys.stderr)
        if "conflicted" in result:
            for p in result["conflicted"]:
                print(f"  ! {p}", file=sys.stderr)
        return 1

    print(f"Knowledge push: COMPLETE", file=sys.stderr)
    print(f"  Project:   {result['project_id']}", file=sys.stderr)
    print(f"  Restored:  {result['total_pushed']} files", file=sys.stderr)
    return 0


def _cmd_knowledge_candidate(args):
    repo = Path(args.repo).resolve()
    if not repo.exists():
        print(f"Error: repository not found: {repo}", file=sys.stderr)
        return 1
    store = Path(args.store) if args.store else None

    try:
        result = knowledge_candidate(
            repo,
            args.source,
            args.target,
            store=store,
            anchor=args.anchor,
            notes=args.notes,
        )
    except PromotionError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    print(f"Knowledge candidate: CREATED", file=sys.stderr)
    print(f"  Candidate:{result.get('id')}", file=sys.stderr)
    print(f"  Status:   {result.get('status')}", file=sys.stderr)
    return 0


def _cmd_knowledge_review(args):
    repo = Path(args.repo).resolve()
    if not repo.exists():
        print(f"Error: repository not found: {repo}", file=sys.stderr)
        return 1
    store = Path(args.store) if args.store else None

    try:
        result = knowledge_review(
            repo,
            args.id,
            store=store,
            reviewer=args.reviewer,
            notes=args.notes,
        )
    except PromotionError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    print(f"Knowledge review: RECORDED", file=sys.stderr)
    print(f"  Candidate:{result.get('id')}", file=sys.stderr)
    print(f"  Status:   {result.get('status')}", file=sys.stderr)
    return 0


def _cmd_knowledge_promote(args):
    repo = Path(args.repo).resolve()
    if not repo.exists():
        print(f"Error: repository not found: {repo}", file=sys.stderr)
        return 1
    pack_dir = Path(args.pack).resolve()
    if not pack_dir.exists():
        print(f"Error: pack directory not found: {pack_dir}", file=sys.stderr)
        return 1
    store = Path(args.store) if args.store else None
    content_path = Path(args.content).resolve() if args.content else None

    try:
        result = knowledge_promote(
            repo,
            args.id,
            pack_dir,
            store=store,
            target_path=args.target_path,
            content_path=content_path,
            dry_run=args.dry_run,
            force=args.force,
        )
    except PromotionError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    if args.dry_run:
        print(f"Knowledge promote: PLAN (dry-run)", file=sys.stderr)
    else:
        print(f"Knowledge promote: COMPLETE", file=sys.stderr)
    print(f"  Candidate:{result.get('candidate_id')}", file=sys.stderr)
    print(f"  Pack:     v{result.get('pack_version')}", file=sys.stderr)
    print(f"  Written:  {result.get('written')}", file=sys.stderr)
    print(f"  Status:   {result.get('status')}", file=sys.stderr)
    return 0


def _cmd_knowledge_reject(args):
    repo = Path(args.repo).resolve()
    if not repo.exists():
        print(f"Error: repository not found: {repo}", file=sys.stderr)
        return 1
    store = Path(args.store) if args.store else None

    try:
        result = knowledge_reject(
            repo,
            args.id,
            store=store,
            reviewer=args.reviewer,
            supersede=args.superseded,
            notes=args.notes,
        )
    except PromotionError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    print(f"Knowledge reject: COMPLETE", file=sys.stderr)
    print(f"  Candidate:{result.get('id')}", file=sys.stderr)
    print(f"  Status:   {result.get('status')}", file=sys.stderr)
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
    ("sync", "codebuddy"): _cmd_sync_codebuddy,
    ("sync", "cursor"): _cmd_sync_cursor,
    ("sync", "check"): _cmd_sync_check,
    ("sync", "clean"): _cmd_sync_clean,
    ("sync", "doctor"): _cmd_sync_doctor,
    ("knowledge", "pull"): _cmd_knowledge_pull,
    ("knowledge", "status"): _cmd_knowledge_status,
    ("knowledge", "push"): _cmd_knowledge_push,
    ("knowledge", "candidate"): _cmd_knowledge_candidate,
    ("knowledge", "review"): _cmd_knowledge_review,
    ("knowledge", "promote"): _cmd_knowledge_promote,
    ("knowledge", "reject"): _cmd_knowledge_reject,
    ("docs", "export-human"): _cmd_docs_export_human,
    ("docs", "lint-human"): _cmd_docs_lint_human,
    ("docs", "lint-knowledge"): _cmd_docs_lint_knowledge,
}


def main():
    parser = _build_parser()
    args = parser.parse_args()

    if args.command is None:
        parser.print_help(sys.stderr)
        return 1

    nested_command = getattr(args, args.command + "_command", None)
    key = (args.command,) if nested_command is None else (args.command, nested_command)
    handler = _DISPATCH.get(key)
    if handler:
        return handler(args)

    if nested_command is None:
        print(f"Error: command '{args.command}' requires a subcommand.", file=sys.stderr)
    else:
        print(f"Error: unsupported command: {' '.join(key)}", file=sys.stderr)
    return 2
