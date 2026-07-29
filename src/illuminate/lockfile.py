"""Lock file management for session mounts."""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict

from .hashutil import hash_file, lock_hash, hash_directory


def create_lock(
    session_dir: Path,
    session_id: str,
    pack_dir: Path,
) -> dict:
    """Create a mount-lock.json for a session.

    Computes SHA-256 for every file in the session directory and a pack-level
    lock hash from the pack source directory.
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


def verify_lock(session_dir: Path) -> bool:
    """Verify that all files in the lock match their current hashes."""
    lock = load_lock(session_dir)
    for entry in lock["files"]:
        file_path = session_dir / entry["path"]
        if not file_path.exists():
            return False
        if hash_file(file_path) != entry["sha256"]:
            return False
    return True
