"""Lock file management for session mounts."""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Optional

from .hashutil import hash_file, lock_hash, hash_directory


def create_lock(
    session_dir: Path,
    session_id: str,
    pack_dir: Path,
    permission_info: Optional[dict] = None,
    external_files: Optional[List[tuple]] = None,
) -> dict:
    """Create a mount-lock.json for a session.

    Computes SHA-256 for every file in the session directory and a pack-level
    lock hash from the pack source directory.

    Args:
        session_dir: Session directory on disk.
        session_id: Unique session identifier.
        pack_dir: Pack directory (for pack-level lock hash).
        permission_info: Optional dict with declared_permissions,
                         enforced_permissions, and enforcement_status fields.
        external_files: Optional list of (role, Path) tuples for files
                        outside the session dir (e.g. codex profile).
    """
    files: List[Dict[str, str]] = []

    for file_path in sorted(session_dir.rglob("*")):
        if file_path.is_file():
            rel = file_path.relative_to(session_dir)
            files.append({
                "path": rel.as_posix(),
                "sha256": hash_file(file_path),
            })

    pack_hash = hash_directory(pack_dir)

    lock = {
        "schema_version": 1,
        "session_id": session_id,
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "files": files,
        "pack_lock_hash": lock_hash(pack_hash),
    }

    if permission_info:
        lock["declared_permissions"] = dict(permission_info.get("declared_permissions", {}))
        lock["enforced_permissions"] = dict(permission_info.get("enforced_permissions", {}))
        lock["unsupported_permissions"] = dict(
            permission_info.get("unsupported_permissions", {})
        )
        lock["enforcement_status"] = dict(permission_info.get("enforcement_status", {}))
        lock["exposed_skills"] = list(permission_info.get("exposed_skills", []))
        lock["file_count"] = len(files)

    if external_files:
        lock["external_files"] = [
            {
                "role": role,
                "path": str(path),
                "sha256": hash_file(path),
            }
            for role, path in external_files
        ]

    lock_path = session_dir / "mount-lock.json"
    with open(lock_path, "w", encoding="utf-8") as f:
        json.dump(lock, f, indent=2, ensure_ascii=False)
        f.write("\n")

    return lock


def load_lock(session_dir: Path) -> dict:
    """Load an existing mount-lock.json."""
    lock_path = session_dir / "mount-lock.json"
    with open(lock_path, "r", encoding="utf-8") as f:
        return json.load(f)


def verify_lock(session_dir: Path) -> dict:
    """Verify session mount integrity against mount-lock.json.

    Also verifies external files (e.g. codex profile) recorded in the lock.

    Returns a dict with:
      valid (bool): True if all hashes match and no extra files.
      mismatch (list): Files whose hash changed (session + external).
      missing (list): Files in lock but not on disk.
      extra (list): Files on disk but not in lock.
      external_mismatch (list): External files whose hash changed.
      total_checked (int): Number of locked files verified.
    """
    lock = load_lock(session_dir)
    locked = {e["path"]: e["sha256"] for e in lock["files"]}

    mismatch = []
    missing = []
    extra = []
    checked = 0

    for rel_path, expected_hash in locked.items():
        file_path = session_dir / rel_path
        if not file_path.exists():
            missing.append(rel_path)
            continue
        actual_hash = hash_file(file_path)
        if actual_hash == expected_hash:
            checked += 1
        else:
            mismatch.append(rel_path)

    # Detect files on disk not in lock (exclude the lock file itself)
    locked_set = set(locked.keys())
    for file_path in sorted(session_dir.rglob("*")):
        if not file_path.is_file():
            continue
        rel = file_path.relative_to(session_dir).as_posix()
        if rel == "mount-lock.json":
            continue
        if rel not in locked_set:
            extra.append(rel)

    # Verify external files
    external_mismatch = []
    for ext in lock.get("external_files", []):
        ext_path = Path(ext["path"])
        if not ext_path.exists():
            missing.append(f"[external] {ext['role']}: {ext['path']}")
            continue
        actual_hash = hash_file(ext_path)
        if actual_hash != ext["sha256"]:
            external_mismatch.append(f"[external] {ext['role']}: {ext['path']}")

    all_mismatch = mismatch + external_mismatch

    return {
        "valid": len(all_mismatch) == 0 and len(missing) == 0 and len(extra) == 0,
        "mismatch": mismatch,
        "missing": missing,
        "extra": extra,
        "external_mismatch": external_mismatch,
        "total_checked": checked,
    }
