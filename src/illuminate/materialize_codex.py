"""Codex materializer: generates a session mount + Codex profile from a pack."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

from .resolve import create_mount_plan, resolve_file_list
from .lockfile import create_lock
from .manifest import load_pack_manifest, load_policy_index, load_skill_contracts
from .validate import validate_pack
from .codex_profile import build_codex_profile_content


def _get_session_base():
    return Path.home() / ".illuminate" / "sessions"


def _get_codex_home():
    """Return the user's Codex config directory."""
    env_home = os.environ.get("CODEX_HOME")
    if env_home:
        return Path(env_home)
    return Path.home() / ".codex"


def _get_repo_display(mount_plan) -> str:
    raw = mount_plan["repo"]
    if isinstance(raw, dict):
        return raw.get("path", str(raw))
    return str(raw)


def _load_policy_instructions(pack_dir, mount_plan) -> str:
    """Compile policies into a compact developer instruction text."""
    manifest = load_pack_manifest(pack_dir)
    policy_index = load_policy_index(pack_dir, manifest)

    policies = sorted(
        policy_index.get("policies", []),
        key=lambda p: p.get("priority", 0),
        reverse=True,
    )

    lines = [
        "# Illuminate Runtime Policy",
        "",
        "These instructions apply in addition to repository AGENTS.md files.",
        "",
    ]

    for policy in policies:
        policy_path = pack_dir / "policies" / policy["path"]
        if policy_path.exists():
            content = policy_path.read_text(encoding="utf-8")
            lines.append(content)
            lines.append("")

    return "\n".join(lines)


def materialize_codex_session(
    pack_dir,
    repo,
    harness="codex",
    skill_filter=None,
):
    """Materialize a Codex session from a pack.

    Creates a session directory under ~/.illuminate/sessions/<session-id>/
    with policies/, .agents/skills/, references/, evidence/, mount-plan.json,
    and mount-lock.json.

    Also generates a Codex profile at ~/.codex/illuminate-<session-id>.config.toml
    with developer_instructions, skills.config, sandbox_mode, and approval_policy.

    Does NOT modify the target repository or the user's ~/.codex/config.toml.

    Returns a dict with session info including profile_name, profile_path, and command.
    """
    pack_dir = Path(pack_dir).resolve()

    # Validate pack
    ok, errors = validate_pack(pack_dir)
    if not ok:
        raise ValueError(
            "Pack validation failed — refusing to materialize:\n"
            + "\n".join(errors)
        )

    mount_plan = create_mount_plan(pack_dir, repo, harness, skill_filter)
    session_id = mount_plan["session_id"]
    repo_path = Path(repo).expanduser().resolve()
    session_dir = _get_session_base() / session_id
    profile_name = f"illuminate-{session_id}"
    codex_home = _get_codex_home()
    profile_path = codex_home / f"{profile_name}.config.toml"

    session_dir.mkdir(parents=True, exist_ok=True)

    # Copy skill files, references, evidence to session
    manifest = load_pack_manifest(pack_dir)
    file_list = resolve_file_list(
        pack_dir, mount_plan,
        skill_mount_base=".agents/skills",
    )
    for file_entry in file_list:
        src = Path(file_entry["source"])
        dest = session_dir / file_entry["dest"]
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)

    # Compile policy into developer-instructions.md (session audit copy)
    instructions = _load_policy_instructions(pack_dir, mount_plan)
    policy_dest = session_dir / "policies" / "developer-instructions.md"
    policy_dest.parent.mkdir(parents=True, exist_ok=True)
    policy_dest.write_text(instructions, encoding="utf-8")

    # Determine exposed skills
    exposed = set(mount_plan["skills"]["exposed"])

    # Build Codex profile
    codex_home.mkdir(parents=True, exist_ok=True)
    profile_toml = build_codex_profile_content(
        repo=repo_path,
        session_dir=session_dir,
        instructions=instructions,
        mount_plan=mount_plan,
        exposed_skill_ids=exposed,
    )
    profile_path.write_text(profile_toml, encoding="utf-8")

    # Write mount-plan.json
    plan_path = session_dir / "mount-plan.json"
    with open(plan_path, "w", encoding="utf-8") as f:
        import json
        json.dump(mount_plan, f, indent=2, ensure_ascii=False)
        f.write("\n")

    # Create lock with external file (the codex profile)
    lock = create_lock(
        session_dir, session_id, pack_dir,
        external_files=[
            ("codex-profile", profile_path),
        ],
    )

    return {
        "session_id": session_id,
        "session_dir": str(session_dir),
        "profile_name": profile_name,
        "profile_path": str(profile_path),
        "mount_plan": mount_plan,
        "lock": lock,
        "command": ["codex", "--profile", profile_name, "--cd", str(repo_path)],
    }


def launch_codex_session(session_info, dry_run=False):
    """Launch a Codex session.

    In dry_run mode, prints the command for the user to run.
    Otherwise, spawns codex with --profile and --cd.
    """
    repo_path = session_info["mount_plan"]["repo"]
    if isinstance(repo_path, dict):
        repo_path = repo_path.get("path", "")
    cmd = session_info["command"]

    print(f"\nSession: {session_info['session_id']}", file=sys.stderr)
    print(f"  Harness: codex", file=sys.stderr)
    print(f"  Profile: {session_info['profile_name']}", file=sys.stderr)
    print(f"  Dir:     {session_info['session_dir']}", file=sys.stderr)
    print(f"  Repo:    {repo_path}", file=sys.stderr)
    print(f"  Skills:  {len(session_info['mount_plan']['skills']['exposed'])}", file=sys.stderr)

    if dry_run:
        print(file=sys.stderr)
        print("Launch command (dry-run):", file=sys.stderr)
        print(file=sys.stderr)
        print("  " + " ".join(cmd), file=sys.stderr)
        print(file=sys.stderr)
        return 0

    print(f"  Launching codex...", file=sys.stderr)
    print(file=sys.stderr)

    try:
        completed = subprocess.run(
            cmd,
            cwd=repo_path,
            check=False,
        )
        return completed.returncode
    except FileNotFoundError:
        print(
            "Error: 'codex' command not found. "
            "Make sure Codex CLI is installed and on PATH.",
            file=sys.stderr,
        )
        print(file=sys.stderr)
        print("Alternatively, use --dry-run to see the launch command:", file=sys.stderr)
        launch_codex_session(session_info, dry_run=True)
        return 1
    except Exception as e:
        print(f"Error launching codex: {e}", file=sys.stderr)
        return 1
