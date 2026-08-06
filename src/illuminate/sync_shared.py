"""Shared deterministic logic for harness sync adapters (Codex, CodeBuddy, ...).

These functions are the single source of truth for skill-tree sync, managed
file hash checks, empty-directory cleanup, and AGENTS.md block construction.
Behavior changes here must keep every harness adapter consistent — do not
special-case one adapter.
"""

import json
import os
import shutil
from pathlib import Path
from typing import Dict, List, Optional, Set

from .hashutil import hash_file, hash_string
from .knowledge_router import build_knowledge_map
from .manifest import load_policy_index
from .managed_block import END_MARKER, make_begin_marker


# The routing order shared by every harness block. Claude uses a session-local
# map path but must carry the same routing order.
KNOWLEDGE_ROUTING_ORDER = """Routing order:
1. Journey for cross-module behavior
2. Module owner document for module behavior
3. Component document for API/lifecycle detail
4. Metadata for claim state, tests, gaps, and evidence
5. CodeGraph for symbol location, call chains, and impact scope
6. Source code and logs for final verification"""

PROJECT_KNOWLEDGE_BLOCK = """## Project Knowledge

If `.illuminate/knowledge-map.md` exists, read it before broad source search.
Otherwise search `docs/20-components`, `docs/30-modules`, and
`docs/40-journeys` before expanding to source code.

{KNOWLEDGE_ROUTING_ORDER}

If the target repository has a `.codegraph/` index:

- Prefer CodeGraph for symbol location, call chains, and impact scope. Use the
  CodeGraph MCP tools when available; otherwise call
  `codegraph explore "<question>"`.
- Do not re-run whole-repository Grep/Read after CodeGraph has already
  returned the relevant context.
- CodeGraph narrows the source scope; it does not replace logs, tests, or
  final source verification.
- When CodeGraph reports stale or delayed index hints, read only the files it
  points to.""".format(KNOWLEDGE_ROUTING_ORDER=KNOWLEDGE_ROUTING_ORDER)


def check_knowledge_map(
    repo_root: Path,
    expected_hash: Optional[str],
    map_rel: str,
    issues: List[str],
) -> None:
    """Append Knowledge Map staleness issues for the four explicit states.

    The lock's ``expected_hash`` (present/None) declares whether the map
    *should* exist; ``build_knowledge_map`` reflects whether the map *can*
    currently be generated. The four combinations are:

    - lock expects absent + currently generatable  -> stale (doc appeared)
    - lock expects present + currently not generatable -> stale (docs removed)
    - lock expects present + currently generatable -> compare rebuilt hash and
      the on-disk file hash against the lock record
    - lock expects absent + currently not generatable -> healthy

    check is read-only. The on-disk file hash is compared too (P1-1) so a
    tampered map file is flagged even when the rebuilt text matches.
    """
    try:
        rebuilt = build_knowledge_map(repo_root)
    except ValueError as exc:
        # Fail-closed only on the write path: check is read-only diagnostics,
        # so an unreadable knowledge source becomes a reported issue instead
        # of a traceback.
        issues.append(str(exc))
        return
    map_path = repo_root / map_rel
    lock_expects_map = expected_hash is not None
    currently_generatable = rebuilt is not None

    if not lock_expects_map and currently_generatable:
        # Docs appeared after a sync that recorded no map; the lock must be
        # refreshed to pick up the new map.
        issues.append("Knowledge map now derivable but not synced — run sync again")
        return
    if lock_expects_map and not currently_generatable:
        # Docs were removed after sync; the map is no longer derivable.
        issues.append("Knowledge map no longer derivable")
        return
    if not lock_expects_map and not currently_generatable:
        # The lock does not expect a map and none can be derived, but a stale
        # or hand-placed map may still linger on disk. PROJECT_KNOWLEDGE_BLOCK
        # reads `.illuminate/knowledge-map.md` whenever it exists, so a leftover
        # file would be consumed as authoritative despite the lock not expecting
        # it. Flag it so it can be cleaned or re-synced.
        if map_path.exists():
            issues.append(
                f"Knowledge map present but not expected: {map_rel} — stale file"
            )
        return
    # lock_expects_map and currently_generatable: compare hashes.
    if not map_path.exists():
        issues.append(f"Missing knowledge map: {map_rel}")
    elif hash_string(map_path.read_text(encoding="utf-8")) != expected_hash:
        # Read as text so universal newline translation makes a freshly
        # written file (platform line endings) hash like the canonical text.
        # A file whose content was edited/tampered still yields a mismatch.
        issues.append("Knowledge map file hash mismatch — file was modified")
    if hash_string(rebuilt) != expected_hash:
        issues.append("Knowledge map hash mismatch — run sync again")


def ensure_regular_file(path: Path) -> None:
    """Fail closed when an Illuminate write target exists but is not a regular
    file.

    A directory (or other non-regular file) occupying a path Illuminate would
    overwrite as a file must abort preflight before any write, so the sync
    never corrupts or partially overwrites such a target.
    """
    if path.exists() and not path.is_file():
        raise ValueError(f"{path} exists but is not a regular file")


def preflight_knowledge_map(
    repo_root: Path,
    map_path: Path,
    force: bool = False,
    harness: Optional[str] = None,
) -> Optional[str]:
    """Phase-1 probe for the knowledge map write/delete before any write.

    Computes the rebuilt map text (read-only) and probes writability of the
    write target or the stale map to be deleted, failing closed with ValueError
    before any other artifact is written. Returns the rebuilt map text (None
    when the map is absent) for use in Phase 2.

    An existing map that no Illuminate lock owns (``_lock_records_map`` for any
    lock in the .illuminate dir, or ``other_harness_declares_map`` for a
    remaining harness's lock) is treated as unmanaged and refused unless
    ``force`` authorizes overwrite. A non-regular-file write target also fails
    closed first.
    """
    ensure_regular_file(map_path)
    text = build_knowledge_map(repo_root)
    if text is not None or map_path.exists():
        if map_path.exists() and not force and not _map_is_owned(repo_root, harness):
            raise ValueError(
                f"{map_path} exists but is not managed by any Illuminate lock; "
                "move it aside or run with --force to overwrite it"
            )
        ensure_writable(map_path)
    return text


def _map_is_owned(repo_root: Path, harness: Optional[str]) -> bool:
    """Whether any harness lock declares ownership of the shared knowledge map.

    Combines the two ownership determinations: any lock (in the same
    .illuminate dir) recording a ``knowledge_map_hash``, or any *other*
    harness's lock still declaring a map (which also fails safe toward
    ownership when a remaining harness's lock cannot be parsed).
    """
    if _lock_records_map(repo_root / ".illuminate"):
        return True
    if harness is not None and other_harness_declares_map(repo_root, harness):
        return True
    return False


def apply_knowledge_map(
    map_path: Path, map_text: Optional[str], force: bool = False
) -> bool:
    """Phase-2 write or delete of the knowledge map using Phase-1's
    ``map_text``. Returns True when a stale map was deleted.

    A stale map is only deleted when Illuminate can prove it owns it: some
    harness lock (in the same .illuminate dir) records a ``knowledge_map_hash``
    from an earlier sync, or ``force`` authorizes removal of an unmanaged
    leftover. A map that no Illuminate sync ever recorded (e.g. a hand-placed
    file) is preserved rather than unlinked unless ``force`` is set, matching
    the codebase rule of never deleting content Illuminate does not own.
    """
    if map_text is not None:
        map_path.parent.mkdir(parents=True, exist_ok=True)
        map_path.write_text(map_text, encoding="utf-8")
        return False
    if map_path.exists() and (_lock_records_map(map_path.parent) or force):
        map_path.unlink()
        return True
    return False


def _lock_records_map(lock_dir: Path) -> bool:
    """Whether any harness lock in ``lock_dir`` records a ``knowledge_map_hash``.

    Used by ``apply_knowledge_map`` to confirm Illuminate previously managed the
    map before deleting it. A lock that fails to parse is ignored (treated as
    not recording a hash) so an uncertain record never causes a hand-placed map
    to be deleted.
    """
    for lock_file in HARNESS_LOCK_FILES.values():
        lock_path = lock_dir / lock_file
        if not lock_path.exists():
            continue
        try:
            lock = json.loads(lock_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if lock.get("knowledge_map_hash"):
            return True
    return False


HARNESS_LOCK_FILES = {
    "cursor": "cursor-lock.json",
    "codex": "codex-lock.json",
    "codebuddy": "codebuddy-lock.json",
}


def other_harness_declares_map(repo_root: Path, harness: str) -> bool:
    """Whether any OTHER harness's lock still declares a knowledge map.

    Used by clean_sync: the current harness's own lock is about to be deleted,
    so the shared map must be kept whenever any remaining harness still owns
    it. A lock that fails to parse is conservatively treated as possibly
    declaring a map (return True): clean must not delete a shared map it cannot
    verify is unowned by every remaining harness.
    """
    for name, lock_file in HARNESS_LOCK_FILES.items():
        if name == harness:
            continue
        lock_path = repo_root / ".illuminate" / lock_file
        if not lock_path.exists():
            continue
        try:
            lock = json.loads(lock_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            # Fail-safe: cannot prove this harness does not own the map, so
            # report that it may. Deleting the shared map here would break a
            # harness that still references it.
            return True
        if lock.get("knowledge_map_hash"):
            return True
    return False


def ensure_writable(path: Path) -> None:
    """Fail-closed writability probe for a path Illuminate will write or delete.

    Raises ValueError if the path cannot be written/deleted. The probe never
    modifies lasting content: an existing file is append-opened and closed
    (no bytes written), an existing directory gets a temporary probe file that
    is created and removed, and a not-yet-existing path probes its nearest
    existing ancestor directory the same way.

    Append-opening an existing file is a deliberate proxy for deletability:
    on Windows a read-only file can be neither appended to nor unlinked, so a
    single probe covers both the write path and the stale-deletion path. On
    POSIX this is conservative (a file deletable via a writable parent may be
    reported read-only); fail-closed is preferred over a partial write.
    """
    probe_name = f".illuminate-probe-{os.getpid()}"
    if path.exists():
        if path.is_dir():
            probe = path / probe_name
            try:
                with open(probe, "a"):
                    pass
            except OSError:
                raise ValueError(f"Not writable: {path}")
            finally:
                try:
                    probe.unlink()
                except OSError:
                    pass
        else:
            try:
                with open(path, "a"):
                    pass
            except OSError:
                raise ValueError(f"Not writable: {path}")
    else:
        parent = path.parent
        while not parent.exists():
            parent = parent.parent
        probe = parent / probe_name
        try:
            with open(probe, "a"):
                pass
        except OSError:
            raise ValueError(f"Not writable: {parent}")
        finally:
            try:
                probe.unlink()
            except OSError:
                pass


def preflight_managed_skill_tree(
    dest_skills_dir: Path,
    manifest: dict,
    exposed: Set[str],
    managed_skills: Set[str],
) -> None:
    """Fail closed on any project-owned skill colliding with an exposed one,
    or on any stale managed skill that can no longer be deleted.

    Raises ValueError before any write so a collision or an un-deletable stale
    directory leaves no partial write behind. No lasting filesystem changes.
    """
    for entry in manifest.get("skills", []):
        if entry["id"] not in exposed:
            continue
        skill_name = entry["dir"].split("/")[-1]
        dest_dir = dest_skills_dir / skill_name
        if dest_dir.exists() and skill_name not in managed_skills:
            raise ValueError(
                f"Cannot sync skill '{skill_name}': "
                "destination already exists and is not Illuminate-managed"
            )

    # Stale-deletion writability: skill dirs previously managed but no longer
    # exposed will be rmtree'd. Probe every contained file (and the dir itself)
    # so a read-only leftover fails before anything is written, not after.
    synced_names = {
        entry["dir"].split("/")[-1]
        for entry in manifest.get("skills", [])
        if entry["id"] in exposed
    }
    for name in managed_skills:
        if name in synced_names:
            continue
        stale_dir = dest_skills_dir / name
        if stale_dir.exists():
            for child in stale_dir.rglob("*"):
                if child.is_file():
                    ensure_writable(child)
            ensure_writable(stale_dir)


def sync_managed_skill_tree(
    pack_dir: Path,
    dest_skills_dir: Path,
    manifest: dict,
    exposed: Set[str],
    managed_skills: Set[str],
) -> Dict[str, Dict[str, str]]:
    """Sync selected skills from the pack into ``dest_skills_dir``.

    Only skills recorded as Illuminate-managed are replaced or removed. A
    project-owned directory that shares a skill's name fails closed with
    ValueError before any write.

    Returns {skill_name: {file_rel: sha256}}.
    """
    preflight_managed_skill_tree(dest_skills_dir, manifest, exposed, managed_skills)

    dest_skills_dir.mkdir(parents=True, exist_ok=True)

    copied: Dict[str, Dict[str, str]] = {}
    synced_names = set()

    for entry in manifest.get("skills", []):
        if entry["id"] not in exposed:
            continue

        skill_dir = pack_dir / entry["dir"]
        if not skill_dir.exists():
            continue

        skill_name = entry["dir"].split("/")[-1]
        synced_names.add(skill_name)
        dest_dir = dest_skills_dir / skill_name

        # Clean only if previously managed (handles removed content)
        if skill_name in managed_skills and dest_dir.exists():
            shutil.rmtree(dest_dir)
        dest_dir.mkdir(parents=True, exist_ok=True)

        file_hashes: Dict[str, str] = {}
        for file_path in sorted(skill_dir.rglob("*")):
            if not file_path.is_file():
                continue
            rel = file_path.relative_to(skill_dir)
            destination = dest_dir / rel
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(file_path, destination)
            file_hashes[rel.as_posix()] = hash_file(destination)

        copied[skill_name] = file_hashes

    # Remove stale managed skills no longer exposed
    for name in managed_skills:
        if name not in synced_names:
            stale_dir = dest_skills_dir / name
            if stale_dir.exists():
                shutil.rmtree(stale_dir)

    return copied


def preflight_managed_command_tree(
    target_dir: Path,
    desired_commands: Dict[str, str],
    previous_managed_commands: Dict[str, str],
) -> None:
    """Fail closed on any project-owned command colliding with a desired one,
    or on any stale managed command that can no longer be deleted.

    Raises ValueError before any write. No lasting filesystem changes.
    """
    prev_managed = previous_managed_commands or {}
    for filename in desired_commands:
        dest = target_dir / filename
        if dest.exists() and filename not in prev_managed:
            raise ValueError(
                f"Cannot sync command '{filename}': "
                "destination already exists and is not Illuminate-managed"
            )

    # Stale-deletion writability: files previously managed but no longer
    # generated will be unlinked. Probe them so a read-only leftover fails
    # before anything is written, not after.
    for filename in prev_managed:
        if filename not in desired_commands:
            stale = target_dir / filename
            if stale.exists():
                ensure_writable(stale)


def sync_managed_command_tree(
    target_dir: Path,
    desired_commands: Dict[str, str],
    previous_managed_commands: Dict[str, str],
) -> Dict[str, str]:
    """Sync command shortcut files into ``target_dir``.

    Only files recorded as Illuminate-managed in ``previous_managed_commands``
    are replaced or removed. A project-owned file that shares a command's
    name fails closed with ValueError before any write. Files previously
    managed but no longer generated are removed (stale cleanup).

    ``desired_commands`` maps filename -> content. Returns
    {filename: sha256} for every synced command.
    """
    preflight_managed_command_tree(target_dir, desired_commands, previous_managed_commands)

    prev_managed = previous_managed_commands or {}

    target_dir.mkdir(parents=True, exist_ok=True)

    hashes: Dict[str, str] = {}
    for filename, content in desired_commands.items():
        dest = target_dir / filename
        dest.write_text(content, encoding="utf-8")
        hashes[filename] = hash_file(dest)

    # Remove stale managed commands no longer generated
    for filename in prev_managed:
        if filename not in desired_commands:
            stale = target_dir / filename
            if stale.exists():
                stale.unlink()

    return hashes


def check_managed_file_hashes(
    repo_root: Path,
    dest_skills_dir_rel: str,
    lock_skills: List[dict],
    issues: List[str],
) -> None:
    """Verify lock-recorded skill files exist with unchanged hashes.

    Appends descriptive messages to ``issues`` for missing or mismatched
    files.
    """
    for skill_entry in lock_skills:
        skill_name = skill_entry["name"]
        for rel, expected_hash in skill_entry.get("files", {}).items():
            rel_path = f"{dest_skills_dir_rel}/{skill_name}/{rel}"
            fpath = repo_root / dest_skills_dir_rel / skill_name / rel
            if not fpath.exists():
                issues.append(f"Missing skill file: {rel_path}")
            else:
                actual_hash = hash_file(fpath)
                if actual_hash != expected_hash:
                    issues.append(f"Skill hash mismatch: {rel_path}")


def remove_empty_parent_dirs(path: Path, stop_at: Path) -> List[str]:
    """Remove empty directories walking upward from ``path`` until ``stop_at``.

    ``stop_at`` itself is never removed. Returns the removed directories as
    posix-relative paths (relative to ``stop_at``).
    """
    removed = []
    current = path
    while current != stop_at:
        try:
            current.rmdir()
        except OSError:
            break
        removed.append(current.relative_to(stop_at).as_posix())
        current = current.parent
    return removed


def compile_policy_text(pack_dir: Path, manifest: dict) -> str:
    """Compile policies into compact developer instructions."""
    policy_index = load_policy_index(pack_dir, manifest)

    policies = sorted(
        policy_index.get("policies", []),
        key=lambda p: p.get("priority", 0),
        reverse=True,
    )

    lines = [
        "## Illuminate Runtime Policies",
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


def build_agents_block(pack_dir: Path, manifest: dict, exposed: Set[str]) -> str:
    """Build the Illuminate AGENTS.md block.

    Only includes policies; skills are discovered by harnesses via their
    skills directory.
    """
    begin = make_begin_marker(manifest)
    policy_text = compile_policy_text(pack_dir, manifest)
    exposed_list = ", ".join(sorted(exposed))
    lines = [
        begin,
        "",
        policy_text,
        "",
        PROJECT_KNOWLEDGE_BLOCK,
        "",
        f"Synchronized skills: {exposed_list}",
        "",
        END_MARKER,
    ]
    return "\n".join(lines)
