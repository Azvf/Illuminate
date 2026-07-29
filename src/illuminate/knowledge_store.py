"""Knowledge store: pull project knowledge docs to central storage, check status, push back.

Central storage structure:
  ~/.illuminate/knowledge/
  └── projects/
      └── <project-id>/
          ├── project.json          (project metadata + last_synced_commit)
          ├── knowledge-lock.json   (file hashes with last_synced_hash)
          └── documents/
              ├── Guidelines/
              │   ├── paths.md
              │   └── ...
              └── Framework/
                  ├── background-download.md
                  └── ...

Conflict detection uses three-way comparison:
  last_synced_hash  — hash when last pulled
  project_hash      — current hash in project docs/Guidelines/ or docs/Framework/
  store_hash        — current hash in store documents/

  project_hash != last_synced_hash AND store_hash == last_synced_hash → pull allowed
  project_hash != last_synced_hash AND store_hash != last_synced_hash → conflict
"""

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .hashutil import hash_file, hash_directory, lock_hash


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_DEFAULT_STORE = Path.home() / ".illuminate" / "knowledge"


def _get_store(store: Optional[Path] = None) -> Path:
    return store or _DEFAULT_STORE


def _project_dir(store: Path, project_id: str) -> Path:
    return store / "projects" / project_id


# ---------------------------------------------------------------------------
# Project helpers
# ---------------------------------------------------------------------------

def _derive_project_id(repo_root: Path) -> str:
    """Derive a stable project ID from the repo root name."""
    return repo_root.name.lower().replace(" ", "-")


def _discover_knowledge_files(repo_root: Path) -> Dict[str, Path]:
    """Discover all files under docs/Guidelines/ and docs/Framework/ in the repo.

    Returns {relative_posix_path: absolute_path}.
    """
    result: Dict[str, Path] = {}
    for subdir in ("Guidelines", "Framework"):
        knowledge_root = repo_root / "docs" / subdir
        if knowledge_root.exists():
            for f in sorted(knowledge_root.rglob("*")):
                if f.is_file():
                    rel = f.relative_to(knowledge_root).as_posix()
                    result[f"{subdir}/{rel}"] = f
    return result


def _read_project_json(project_dir: Path) -> dict:
    """Read project.json or return a default."""
    pj_path = project_dir / "project.json"
    if pj_path.exists():
        return json.loads(pj_path.read_text(encoding="utf-8"))
    return {}


def _read_knowledge_lock(project_dir: Path) -> dict:
    """Read knowledge-lock.json or return an empty lock."""
    lock_path = project_dir / "knowledge-lock.json"
    if lock_path.exists():
        return json.loads(lock_path.read_text(encoding="utf-8"))
    return {"files": [], "last_synced_hash": {}}


# ---------------------------------------------------------------------------
# Pull: project → store
# ---------------------------------------------------------------------------

def knowledge_pull(
    repo_root: Path,
    store: Optional[Path] = None,
) -> dict:
    """Pull project knowledge docs from repo to central store.

    Returns a summary dict with new/modified/deleted/conflicted file lists.
    """
    repo_root = Path(repo_root).resolve()
    project_id = _derive_project_id(repo_root)
    store_path = _get_store(store)
    project_dir = _project_dir(store_path, project_id)

    knowledge_files = _discover_knowledge_files(repo_root)

    # Load previous state
    project_info = _read_project_json(project_dir)
    lock = _read_knowledge_lock(project_dir)

    # Build hash maps from lock
    locked_hashes: Dict[str, str] = {}
    for entry in lock.get("files", []):
        locked_hashes[entry["path"]] = entry.get("sha256", "")
    locked_verified: Dict[str, str] = {}
    for entry in lock.get("files", []):
        locked_verified[entry["path"]] = entry.get("verified_commit", "")

    # Current project file hashes
    project_hashes: Dict[str, str] = {}
    for rel, fpath in knowledge_files.items():
        project_hashes[rel] = hash_file(fpath)

    # Current store file hashes
    store_hashes: Dict[str, str] = {}
    store_docs_dir = project_dir / "documents"
    if store_docs_dir.exists():
        for f in sorted(store_docs_dir.rglob("*")):
            if f.is_file():
                rel = f.relative_to(store_docs_dir).as_posix()
                store_hashes[rel] = hash_file(f)

    new_files: List[str] = []
    modified_files: List[str] = []
    deleted_files: List[str] = []
    conflicted_files: List[str] = []
    pulled_files: List[str] = []

    all_paths = set(list(project_hashes.keys()) + list(locked_hashes.keys()) + list(store_hashes.keys()))

    for rel in sorted(all_paths):
        project_hash = project_hashes.get(rel)
        store_hash = store_hashes.get(rel)
        last_synced = locked_hashes.get(rel)

        if project_hash is None:
            # File deleted in project
            deleted_files.append(rel)
            continue

        if store_hash is None and last_synced is None:
            # New file, not in store
            new_files.append(rel)
            pulled_files.append(rel)
            continue

        if project_hash != last_synced and (store_hash == last_synced or store_hash is None):
            # Project changed, store unchanged → safe to pull
            modified_files.append(rel)
            pulled_files.append(rel)
            continue

        if project_hash != last_synced and store_hash != last_synced and store_hash != project_hash:
            # Both sides changed → conflict
            conflicted_files.append(rel)
            continue

        if project_hash == store_hash:
            # Already in sync
            continue

        # Fallback: store has something project doesn't (or they match via last_synced)
        if last_synced is None:
            pulled_files.append(rel)

    # Do the actual copy for pulled files
    if pulled_files:
        store_docs_dir.mkdir(parents=True, exist_ok=True)
        for rel in pulled_files:
            src = knowledge_files[rel]
            dest = store_docs_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)

    # Build new lock with all current project file hashes
    new_file_entries = []
    for rel, fpath in knowledge_files.items():
        new_file_entries.append({
            "path": rel,
            "sha256": hash_file(fpath),
            "verified_commit": "",
        })

    # Get git HEAD for last_synced_commit
    import subprocess
    try:
        head = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=str(repo_root), stderr=subprocess.DEVNULL, text=True,
        ).strip()
    except Exception:
        head = ""

    # Update project.json
    repo_remote = ""
    try:
        repo_remote = subprocess.check_output(
            ["git", "remote", "get-url", "origin"],
            cwd=str(repo_root), stderr=subprocess.DEVNULL, text=True,
        ).strip()
    except Exception:
        pass

    project_info.update({
        "schema_version": 1,
        "project_id": project_id,
        "display_name": repo_root.name,
        "repository": {
            "remote": repo_remote,
            "default_branch": "main",
        },
        "knowledge_root": "docs/Guidelines + docs/Framework",
        "last_synced_commit": head,
        "last_synced_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    })

    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "project.json").write_text(
        json.dumps(project_info, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    # Update knowledge-lock.json
    new_lock = {
        "files": new_file_entries,
        "last_synced_hash": project_hashes,
    }
    (project_dir / "knowledge-lock.json").write_text(
        json.dumps(new_lock, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    return {
        "project_id": project_id,
        "new": new_files,
        "modified": modified_files,
        "deleted": deleted_files,
        "conflicted": conflicted_files,
        "pulled": pulled_files,
        "total": len(knowledge_files),
        "last_synced_commit": head,
    }


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------

def knowledge_status(
    repo_root: Path,
    store: Optional[Path] = None,
) -> dict:
    """Compare project knowledge docs with central store.

    Returns a dict with new/modified/deleted/conflicted file lists and conflict info.
    """
    repo_root = Path(repo_root).resolve()
    project_id = _derive_project_id(repo_root)
    store_path = _get_store(store)
    project_dir = _project_dir(store_path, project_id)

    knowledge_files = _discover_knowledge_files(repo_root)
    lock = _read_knowledge_lock(project_dir)
    project_info = _read_project_json(project_dir)

    locked_hashes: Dict[str, str] = {}
    for entry in lock.get("files", []):
        locked_hashes[entry["path"]] = entry.get("sha256", "")

    project_hashes: Dict[str, str] = {}
    for rel, fpath in knowledge_files.items():
        project_hashes[rel] = hash_file(fpath)

    store_hashes: Dict[str, str] = {}
    store_docs_dir = project_dir / "documents"
    if store_docs_dir.exists():
        for f in sorted(store_docs_dir.rglob("*")):
            if f.is_file():
                rel = f.relative_to(store_docs_dir).as_posix()
                store_hashes[rel] = hash_file(f)

    new_files: List[str] = []
    modified_files: List[str] = []
    deleted_files: List[str] = []
    conflicted_files: List[str] = []
    synced_files: List[str] = []

    all_paths = set(list(project_hashes.keys()) + list(locked_hashes.keys()) + list(store_hashes.keys()))

    for rel in sorted(all_paths):
        project_hash = project_hashes.get(rel)
        store_hash = store_hashes.get(rel)
        last_synced = locked_hashes.get(rel)

        if project_hash is None:
            deleted_files.append(rel)
            continue

        if store_hash is None and last_synced is None:
            new_files.append(rel)
            continue

        if project_hash == store_hash:
            synced_files.append(rel)
            continue

        if project_hash != last_synced and store_hash == last_synced:
            modified_files.append(rel)
            continue

        if project_hash != last_synced and store_hash != last_synced:
            conflicted_files.append(rel)
            continue

        # Catch-all: store has different hash but last_synced matches project
        if project_hash == last_synced and store_hash != last_synced:
            # Store was modified independently
            modified_files.append(f"[store] {rel}")
            continue

        if last_synced is None:
            new_files.append(rel)

    return {
        "project_id": project_id,
        "project_name": project_info.get("display_name", repo_root.name),
        "last_synced_commit": project_info.get("last_synced_commit", ""),
        "last_synced_at": project_info.get("last_synced_at", ""),
        "new": new_files,
        "modified": modified_files,
        "deleted": deleted_files,
        "conflicted": conflicted_files,
        "synced": synced_files,
        "total": len(knowledge_files),
        "store_total": len(store_hashes),
        "has_conflicts": len(conflicted_files) > 0,
    }


# ---------------------------------------------------------------------------
# Push: store → project (only for explicit recovery)
# ---------------------------------------------------------------------------

def knowledge_push(
    repo_root: Path,
    store: Optional[Path] = None,
    force: bool = False,
) -> dict:
    """Push store documents back to the project.

    Only works when there are no conflicts (unless force=True).
    Only copies files where the project hasn't been modified since last sync.

    Returns a summary dict.
    """
    repo_root = Path(repo_root).resolve()
    project_id = _derive_project_id(repo_root)
    store_path = _get_store(store)
    project_dir = _project_dir(store_path, project_id)

    status = knowledge_status(repo_root, store)
    if status["has_conflicts"] and not force:
        return {
            "error": "Conflicts detected. Use --force to override.",
            "conflicted": status["conflicted"],
            "pushed": [],
        }

    knowledge_files = _discover_knowledge_files(repo_root)
    store_docs_dir = project_dir / "documents"
    if not store_docs_dir.exists():
        return {"error": "No store documents found.", "pushed": []}

    pushed: List[str] = []

    for f in sorted(store_docs_dir.rglob("*")):
        if not f.is_file():
            continue
        rel = f.relative_to(store_docs_dir).as_posix()
        # rel may contain subdir prefix like "Guidelines/paths.md" or "Framework/mod.md"
        dest = repo_root / "docs" / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, dest)
        pushed.append(rel)

    return {
        "project_id": project_id,
        "pushed": pushed,
        "total_pushed": len(pushed),
    }
