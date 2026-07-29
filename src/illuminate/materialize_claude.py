"""Claude Code materializer: generates a session mount from a pack + mount plan."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, List

from .resolve import create_mount_plan, resolve_file_list
from .lockfile import create_lock
from .manifest import load_pack_manifest, load_policy_index, load_skill_contracts
from .hashutil import hash_directory, lock_hash


def _get_session_base():
    return Path.home() / ".illuminate" / "sessions"


def _generate_claude_md(pack_dir, mount_plan):
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
        f"Repo: {mount_plan['repo']}",
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

    return "\n".join(lines)


def _generate_claude_settings(mount_plan, contracts):
    deny = [
        "Read(./.env)",
        "Read(./.env.*)",
        "Read(./secrets/**)",
        "Bash(curl *)",
        "Bash(wget *)",
    ]
    allow = [
        "Bash(git diff:*)",
        "Bash(git status:*)",
        "Bash(git log:*)",
        "Bash(illuminate evidence audit:*)",
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


def materialize_session(pack_dir, repo, harness="claude-code", skill_filter=None):
    """Materialize a Claude Code session from a pack.

    Creates a session directory under ~/.illuminate/sessions/<session-id>/
    with CLAUDE.md, .claude/skills/, claude-settings.json, mount-plan.json,
    and mount-lock.json.

    Returns a dict with session info.
    """
    pack_dir = Path(pack_dir).resolve()

    mount_plan = create_mount_plan(pack_dir, repo, harness, skill_filter)
    session_id = mount_plan["session_id"]
    session_dir = _get_session_base() / session_id
    session_dir.mkdir(parents=True, exist_ok=True)

    # Generate CLAUDE.md
    claude_md = _generate_claude_md(pack_dir, mount_plan)
    (session_dir / "CLAUDE.md").write_text(claude_md, encoding="utf-8")

    # Copy skill files
    manifest = load_pack_manifest(pack_dir)
    contracts = load_skill_contracts(pack_dir, manifest)
    file_list = resolve_file_list(pack_dir, mount_plan)
    for file_entry in file_list:
        src = Path(file_entry["source"])
        dest = session_dir / file_entry["dest"]
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)

    # Generate claude-settings.json
    settings = _generate_claude_settings(mount_plan, contracts)
    settings_path = session_dir / "claude-settings.json"
    with open(settings_path, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2, ensure_ascii=False)
        f.write("\n")

    # Write mount-plan.json
    plan_path = session_dir / "mount-plan.json"
    with open(plan_path, "w", encoding="utf-8") as f:
        json.dump(mount_plan, f, indent=2, ensure_ascii=False)
        f.write("\n")

    # Create mount-lock.json
    lock = create_lock(session_dir, session_id, pack_dir)

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


def launch_session(session_info):
    """Launch a Claude Code session.

    Prints the command for the user to run (first version does not
    auto-spawn to avoid blocking).
    """
    session_dir = session_info["session_dir"]
    cmd = _build_claude_command(session_dir)
    env = _build_env()

    # Print the command for the user to run
    env_prefix = "CLAUDE_CODE_ADDITIONAL_DIRECTORIES_CLAUDE_MD=1"
    print("\nSession materialized successfully.", file=sys.stderr)
    print(f"  Session: {session_info['session_id']}", file=sys.stderr)
    print(f"  Dir:     {session_dir}", file=sys.stderr)
    print(f"  Lock:    {session_info['lock']['pack_lock_hash']}", file=sys.stderr)
    print(file=sys.stderr)
    print("Run this command to start:", file=sys.stderr)
    print(file=sys.stderr)

    if sys.platform == "win32":
        print(f'  $env:CLAUDE_CODE_ADDITIONAL_DIRECTORIES_CLAUDE_MD = "1"', file=sys.stderr)
        print(f'  claude --add-dir "{session_dir}" --settings "{session_dir}\\claude-settings.json"', file=sys.stderr)
    else:
        print(f'  {env_prefix} claude --add-dir "{session_dir}" --settings "{session_dir}/claude-settings.json"', file=sys.stderr)

    print(file=sys.stderr)
