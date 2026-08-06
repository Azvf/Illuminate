"""Claude Code materializer: generates a session mount from a pack + mount plan."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional

from .resolve import create_mount_plan, resolve_file_list
from .lockfile import build_lock_envelope, create_lock
from .manifest import load_pack_manifest, load_policy_index, load_skill_contracts
from .hashutil import hash_directory, lock_hash
from .sync_shared import KNOWLEDGE_ROUTING_ORDER
from .validate import validate_pack


def _get_session_base():
    return Path.home() / ".illuminate" / "sessions"


def _get_repo_display(mount_plan) -> str:
    """Extract a displayable repo path from mount_plan, handling dict or string."""
    raw = mount_plan["repo"]
    if isinstance(raw, dict):
        return raw.get("path", str(raw))
    return str(raw)


def _generate_claude_md(pack_dir, mount_plan, has_map):
    manifest = load_pack_manifest(pack_dir)
    policy_index = load_policy_index(pack_dir, manifest)

    policies = sorted(
        policy_index.get("policies", []),
        key=lambda p: p.get("priority", 0),
        reverse=True,
    )

    lines = [
        "# Illuminate Session — Claude Code",
        "",
        f"Pack: {manifest['id']} v{manifest['version']}",
        f"Repo: {_get_repo_display(mount_plan)}",
        f"Session: {mount_plan['session_id']}",
        "",
        "## Policies (always active, in priority order)",
        "",
    ]

    for policy in policies:
        policy_path = pack_dir / "policies" / policy["path"]
        if policy_path.exists():
            content = policy_path.read_text(encoding="utf-8")
            lines.append(content)
            lines.append("")
            lines.append("---")
            lines.append("")

    lines.append("## Skills")
    lines.append("")
    lines.append("Skills are auto-discovered from `.claude/skills/`. Activate by task.")
    lines.append("")
    lines.append("## Project Knowledge")
    lines.append("")
    if has_map:
        lines.append(
            "Read `project-knowledge-map.md` before broad repository search."
        )
        lines.append("Paths inside the map are relative to the target repository root.")
    else:
        lines.append(
            "No project knowledge map is present. Search `docs/20-components`, "
            "`docs/30-modules`, and `docs/40-journeys` before expanding to source code."
        )
    lines.append("")
    lines.append(KNOWLEDGE_ROUTING_ORDER)
    lines.append("")

    return "\n".join(lines)


def _generate_claude_settings(mount_plan, contracts):
    deny = [
        "Read(./.env)",
        "Read(./.env.*)",
        "Read(./secrets/**)",
        "Bash(curl *)",
        "Bash(wget *)",
    ]
    # CodeGraph exposes only `codegraph_explore` by default; the narrower
    # tools (node/search/callers/callees/impact/files/status) only appear
    # after the user enables them via CODEGRAPH_MCP_TOOLS.
    allow = [
        "Bash(git diff:*)",
        "Bash(git status:*)",
        "Bash(git log:*)",
        "Bash(illuminate evidence audit:*)",
        "mcp__codegraph__codegraph_explore",
    ]
    for contract in contracts:
        for perm in contract.get("permissions", {}).get("execute", []):
            allow.append(f"Bash({perm}:*)")
    return {
        "permissions": {
            "deny": deny,
            "allow": list(dict.fromkeys(allow)),
        },
    }


def _gather_permissions(mount_plan, contracts) -> dict:
    """Aggregate declared and enforced permissions for the mount lock.

    claude-settings can only enforce Bash(execute) rules; read/write
    permissions are declared in contracts but not compiled into settings.
    Returns a dict with:
      declared_permissions:     All permissions from contracts
      enforced_permissions:     What is compiled into claude-settings
      unsupported_permissions:  Declared but not enforceable in this harness
      enforcement_status:       Per-category enforcement level
    """
    exposed = set(mount_plan["skills"]["exposed"])
    allow_exec = set()
    allow_read = set()
    allow_write = set()
    for contract in contracts:
        if contract["id"] not in exposed:
            continue
        for perm in contract.get("permissions", {}).get("execute", []):
            allow_exec.add(perm)
        for perm in contract.get("permissions", {}).get("read", []):
            allow_read.add(perm)
        for perm in contract.get("permissions", {}).get("write", []):
            allow_write.add(perm)
    return {
        "declared_permissions": {
            "read": sorted(allow_read),
            "write": sorted(allow_write),
            "execute": sorted(allow_exec),
        },
        "enforced_permissions": {
            "execute": sorted(allow_exec),
        },
        "unsupported_permissions": {
            "read": sorted(allow_read),
            "write": sorted(allow_write),
        },
        "enforcement_status": {
            "read": "not-enforced",
            "write": "not-enforced",
            "execute": "partial",
        },
        "exposed_skills": sorted(exposed),
    }


def materialize_session(pack_dir, repo, skill_filter=None):
    """Materialize a Claude Code session from a pack.

    Creates a session directory under ~/.illuminate/sessions/<session-id>/
    with CLAUDE.md, .claude/skills/, claude-settings.json, mount-plan.json,
    and mount-lock.json.

    Validates the pack before materialization.
    Permissions and file lists are scoped to the exposed skill set.

    Returns a dict with session info.
    """
    pack_dir = Path(pack_dir).resolve()

    # Validate pack before any IO
    ok, errors = validate_pack(pack_dir)
    if not ok:
        raise ValueError(
            "Pack validation failed — refusing to materialize:\n"
            + "\n".join(errors)
        )

    mount_plan = create_mount_plan(pack_dir, repo, skill_filter)
    session_id = mount_plan["session_id"]
    session_dir = _get_session_base() / session_id
    session_dir.mkdir(parents=True, exist_ok=True)

    # Determine whether the target repo yields a knowledge map before writing
    # CLAUDE.md, so its navigation section is conditional on map presence.
    from .knowledge_router import build_knowledge_map
    repo_path = Path(mount_plan["repo"]["path"]) if isinstance(mount_plan["repo"], dict) else Path(mount_plan["repo"])
    has_map = build_knowledge_map(repo_path) is not None

    # Generate CLAUDE.md
    claude_md = _generate_claude_md(pack_dir, mount_plan, has_map)
    (session_dir / "CLAUDE.md").write_text(claude_md, encoding="utf-8")

    # Copy files (skill filtering happens inside resolve_file_list)
    manifest = load_pack_manifest(pack_dir)
    contracts = load_skill_contracts(pack_dir, manifest)
    file_list = resolve_file_list(pack_dir, mount_plan)
    for file_entry in file_list:
        src = Path(file_entry["source"])
        dest = session_dir / file_entry["dest"]
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)

    # Knowledge Map: written into the session dir (never the target repo).
    # Returns None when the target repo has no indexable knowledge (no file).
    knowledge_map_written = False
    from .knowledge_router import write_knowledge_map
    if write_knowledge_map(repo_path, session_dir / "project-knowledge-map.md") is not None:
        knowledge_map_written = True

    # Use only exposed contracts for permissions
    exposed = set(mount_plan["skills"]["exposed"])
    active_contracts = [
        c for c in contracts if c["id"] in exposed
    ]

    # Generate claude-settings.json
    settings = _generate_claude_settings(mount_plan, active_contracts)
    settings_path = session_dir / "claude-settings.json"
    with open(settings_path, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2, ensure_ascii=False)
        f.write("\n")

    # Write mount-plan.json
    plan_path = session_dir / "mount-plan.json"
    with open(plan_path, "w", encoding="utf-8") as f:
        json.dump(mount_plan, f, indent=2, ensure_ascii=False)
        f.write("\n")

    # Collect declared and enforced permissions for lock
    permission_info = _gather_permissions(mount_plan, contracts)

    # Create mount-lock.json
    managed_artifacts = [entry["dest"] for entry in file_list]
    managed_artifacts.extend([
        "CLAUDE.md",
        "claude-settings.json",
        "mount-plan.json",
    ])
    if knowledge_map_written:
        managed_artifacts.append("project-knowledge-map.md")
    pack_hash = lock_hash(hash_directory(pack_dir))
    envelope = build_lock_envelope(
        harness="claude-code",
        pack={
            "id": manifest.get("id", "?"),
            "version": manifest.get("version", "?"),
            "hash": pack_hash,
        },
        target=mount_plan["repo"],
        selection={"skills": sorted(exposed)},
        managed_artifacts=managed_artifacts,
        capabilities={"permissions": permission_info["enforcement_status"]},
    )
    lock = create_lock(
        session_dir, session_id, pack_dir,
        permission_info=permission_info,
        envelope=envelope,
    )

    return {
        "session_id": session_id,
        "session_dir": str(session_dir),
        "mount_plan": mount_plan,
        "lock": lock,
    }


def _build_claude_command(session_dir):
    """Build the claude CLI command for launching the session."""
    session_dir = Path(session_dir)
    return [
        "claude",
        "--add-dir", str(session_dir),
        "--settings", str(session_dir / "claude-settings.json"),
    ]


def _build_env():
    """Build environment for the claude process."""
    env = os.environ.copy()
    env["CLAUDE_CODE_ADDITIONAL_DIRECTORIES_CLAUDE_MD"] = "1"
    return env


def launch_session(session_info, dry_run=False):
    """Launch a Claude Code session.

    In dry_run mode, prints the command for the user to run.
    Otherwise, spawns claude with cwd set to the target repository.
    """
    session_dir = Path(session_info["session_dir"])
    mount_plan = session_info["mount_plan"]
    repo_path = mount_plan["repo"]["path"] if isinstance(mount_plan["repo"], dict) else mount_plan["repo"]
    cmd = _build_claude_command(session_dir)
    env = _build_env()
    env_prefix = "CLAUDE_CODE_ADDITIONAL_DIRECTORIES_CLAUDE_MD=1"

    print(f"\nSession: {session_info['session_id']}", file=sys.stderr)
    print(f"  Dir:   {session_dir}", file=sys.stderr)
    print(f"  Repo:  {repo_path}", file=sys.stderr)
    print(f"  Lock:  {session_info['lock']['pack_lock_hash']}", file=sys.stderr)

    if dry_run:
        print(file=sys.stderr)
        print("Launch command (dry-run):", file=sys.stderr)
        print(file=sys.stderr)
        if sys.platform == "win32":
            print(f'  cd /d "{repo_path}"', file=sys.stderr)
            print(f'  $env:CLAUDE_CODE_ADDITIONAL_DIRECTORIES_CLAUDE_MD = "1"', file=sys.stderr)
            print(f'  claude --add-dir "{session_dir}" --settings "{session_dir}\\claude-settings.json"', file=sys.stderr)
        else:
            print(f'  cd "{repo_path}" && \\', file=sys.stderr)
            print(f'  {env_prefix} claude --add-dir "{session_dir}" --settings "{session_dir}/claude-settings.json"', file=sys.stderr)
        print(file=sys.stderr)
        return 0

    print(f"  Launching claude...", file=sys.stderr)
    print(file=sys.stderr)

    try:
        completed = subprocess.run(
            cmd,
            cwd=repo_path,
            env=env,
            check=False,
        )
        return completed.returncode
    except FileNotFoundError:
        print(
            "Error: 'claude' command not found. "
            "Make sure Claude Code CLI is installed and on PATH.",
            file=sys.stderr,
        )
        print(file=sys.stderr)
        print("Alternatively, use --dry-run to see the launch command:", file=sys.stderr)
        launch_session(session_info, dry_run=True)
        return 1
    except Exception as e:
        print(f"Error launching claude: {e}", file=sys.stderr)
        return 1
