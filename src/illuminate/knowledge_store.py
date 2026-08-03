"""Local knowledge backup with change detection and protected recovery.

The store keeps one copy of configured knowledge documents outside the repository:

    ~/.illuminate/knowledge/projects/<project-id>/
        knowledge-lock.json
        documents/...

Git remains the source of version history. This module only provides a local
backup, status comparison, and explicit recovery path.
"""

import fnmatch
import hashlib
import json
import shutil
from pathlib import Path
from typing import Dict, List, Optional

from .hashutil import hash_file


_DEFAULT_STORE = Path.home() / ".illuminate" / "knowledge"
_DEFAULT_KNOWLEDGE_MANIFEST = {
    "roots": ["Guidelines", "Framework"],
    "include": ["**/*"],
    "exclude": [],
}


def _get_store(store: Optional[Path] = None) -> Path:
    return Path(store) if store is not None else _DEFAULT_STORE


def _project_dir(store: Path, project_id: str) -> Path:
    return store / "projects" / project_id


def _derive_project_id(repo_root: Path) -> str:
    """Use the repository name plus its absolute path identity."""
    name = repo_root.name.lower().replace(" ", "-") or "project"
    path_hash = hashlib.sha256(str(repo_root.resolve()).encode("utf-8")).hexdigest()[:12]
    return f"{name}-{path_hash}"


def _knowledge_manifest(repo_root: Path, manifest_path: Optional[Path] = None) -> dict:
    candidates = []
    if manifest_path is not None:
        candidates.append(Path(manifest_path))
    candidates.extend([
        repo_root / "knowledge-manifest.json",
        repo_root / "docs" / "knowledge-manifest.json",
    ])
    for candidate in candidates:
        if candidate.is_file():
            try:
                data = json.loads(candidate.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ValueError(f"invalid knowledge manifest: {candidate}: {exc}") from exc
            if not isinstance(data, dict):
                raise ValueError(f"knowledge manifest must be an object: {candidate}")
            return data
    return dict(_DEFAULT_KNOWLEDGE_MANIFEST)


def _discover_knowledge_files(
    repo_root: Path,
    manifest_path: Optional[Path] = None,
) -> Dict[str, Path]:
    """Return configured files keyed by paths relative to ``docs/``."""
    docs_root = (repo_root / "docs").resolve()
    manifest = _knowledge_manifest(repo_root, manifest_path)
    roots = manifest.get("roots", _DEFAULT_KNOWLEDGE_MANIFEST["roots"])
    include = manifest.get("include", ["**/*"])
    exclude = manifest.get("exclude", [])
    if not all(isinstance(value, list) for value in (roots, include, exclude)):
        raise ValueError("knowledge manifest roots/include/exclude must be arrays")

    result: Dict[str, Path] = {}
    for root in roots:
        root_path = (docs_root / root).resolve()
        try:
            root_path.relative_to(docs_root)
        except ValueError as exc:
            raise ValueError(f"knowledge root escapes docs/: {root}") from exc

        if root_path.is_file():
            candidates = [root_path]
        elif root_path.is_dir():
            candidates = [
                path
                for pattern in include
                for path in root_path.glob(pattern)
            ]
        else:
            continue

        for file_path in candidates:
            if not file_path.is_file():
                continue
            rel = file_path.relative_to(docs_root).as_posix()
            if any(fnmatch.fnmatchcase(rel, pattern) for pattern in exclude):
                continue
            result[rel] = file_path
    return result


def _read_lock(project_dir: Path) -> dict:
    lock_path = project_dir / "knowledge-lock.json"
    if not lock_path.exists():
        return {"files": []}
    try:
        data = json.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid knowledge lock: {lock_path}: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("files", []), list):
        raise ValueError(f"invalid knowledge lock: {lock_path}")
    return data


def _hash_documents(documents_dir: Path) -> Dict[str, str]:
    if not documents_dir.exists():
        return {}
    return {
        path.relative_to(documents_dir).as_posix(): hash_file(path)
        for path in sorted(documents_dir.rglob("*"))
        if path.is_file()
    }


def _locked_hashes(lock: dict) -> Dict[str, str]:
    return {
        entry["path"]: entry.get("sha256", "")
        for entry in lock.get("files", [])
        if isinstance(entry, dict) and "path" in entry
    }


def _write_lock(project_dir: Path, hashes: Dict[str, str]) -> None:
    project_dir.mkdir(parents=True, exist_ok=True)
    entries = [
        {"path": path, "sha256": sha256}
        for path, sha256 in sorted(hashes.items())
    ]
    (project_dir / "knowledge-lock.json").write_text(
        json.dumps({"schema_version": 1, "files": entries}, indent=2) + "\n",
        encoding="utf-8",
    )


def _snapshot(repo_root: Path, project_dir: Path, manifest_path: Optional[Path]):
    project_files = _discover_knowledge_files(repo_root, manifest_path)
    project_hashes = {
        rel: hash_file(path) for rel, path in project_files.items()
    }
    store_hashes = _hash_documents(project_dir / "documents")
    baseline = _locked_hashes(_read_lock(project_dir))
    return project_files, project_hashes, store_hashes, baseline


def _compare(
    project_hashes: Dict[str, str],
    store_hashes: Dict[str, str],
    baseline: Dict[str, str],
) -> dict:
    new_files: List[str] = []
    modified_files: List[str] = []
    store_modified_files: List[str] = []
    deleted_files: List[str] = []
    conflicted_files: List[str] = []
    synced_files: List[str] = []

    all_paths = set(project_hashes) | set(store_hashes) | set(baseline)
    for rel in sorted(all_paths):
        project_hash = project_hashes.get(rel)
        store_hash = store_hashes.get(rel)
        last_synced = baseline.get(rel)

        if project_hash is None:
            deleted_files.append(rel)
            continue
        if project_hash == store_hash:
            synced_files.append(rel)
            continue
        if last_synced is None:
            if store_hash is None:
                new_files.append(rel)
            else:
                conflicted_files.append(rel)
            continue

        project_changed = project_hash != last_synced
        store_changed = store_hash != last_synced
        if project_changed and not store_changed:
            modified_files.append(rel)
        elif not project_changed and store_changed:
            store_modified_files.append(rel)
        elif project_changed and store_changed:
            conflicted_files.append(rel)
        else:
            deleted_files.append(rel)

    return {
        "new": new_files,
        "modified": modified_files,
        "store_modified": store_modified_files,
        "deleted": deleted_files,
        "conflicted": conflicted_files,
        "synced": synced_files,
    }


def knowledge_pull(
    repo_root: Path,
    store: Optional[Path] = None,
    manifest_path: Optional[Path] = None,
) -> dict:
    """Copy project knowledge into the local store when it is safe."""
    repo_root = Path(repo_root).resolve()
    project_id = _derive_project_id(repo_root)
    project_dir = _project_dir(_get_store(store), project_id)
    project_files, project_hashes, store_hashes, baseline = _snapshot(
        repo_root, project_dir, manifest_path
    )
    changes = _compare(project_hashes, store_hashes, baseline)

    pulled: List[str] = []
    missing_from_store = [
        rel for rel in changes["store_modified"]
        if rel not in store_hashes
    ]
    for rel in sorted(set(changes["new"] + changes["modified"] + missing_from_store)):
        source = project_files[rel]
        destination = project_dir / "documents" / rel
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        pulled.append(rel)

    updated_hashes = _hash_documents(project_dir / "documents")
    for rel in changes["synced"] + pulled:
        updated_hashes[rel] = project_hashes[rel]
    remaining_store_changes = set(changes["store_modified"]) - set(missing_from_store)
    if not changes["conflicted"] and not remaining_store_changes:
        _write_lock(project_dir, updated_hashes)

    return {
        "project_id": project_id,
        "new": changes["new"],
        "modified": changes["modified"],
        "store_modified": changes["store_modified"],
        "deleted": changes["deleted"],
        "conflicted": changes["conflicted"],
        "pulled": pulled,
        "total": len(project_files),
    }


def knowledge_status(
    repo_root: Path,
    store: Optional[Path] = None,
    manifest_path: Optional[Path] = None,
) -> dict:
    """Compare project files, the local copy, and the last safe baseline."""
    repo_root = Path(repo_root).resolve()
    project_id = _derive_project_id(repo_root)
    project_dir = _project_dir(_get_store(store), project_id)
    project_files, project_hashes, store_hashes, baseline = _snapshot(
        repo_root, project_dir, manifest_path
    )
    changes = _compare(project_hashes, store_hashes, baseline)
    return {
        "project_id": project_id,
        "project_name": repo_root.name,
        **changes,
        "total": len(project_files),
        "store_total": len(store_hashes),
        "has_conflicts": bool(changes["conflicted"]),
    }


def knowledge_push(
    repo_root: Path,
    store: Optional[Path] = None,
    force: bool = False,
    manifest_path: Optional[Path] = None,
) -> dict:
    """Restore local store documents into the repository after conflict checks."""
    repo_root = Path(repo_root).resolve()
    project_id = _derive_project_id(repo_root)
    project_dir = _project_dir(_get_store(store), project_id)
    documents_dir = project_dir / "documents"
    store_hashes = _hash_documents(documents_dir)
    if not store_hashes:
        return {"project_id": project_id, "error": "No store documents found.", "pushed": []}

    status = knowledge_status(repo_root, store, manifest_path)
    if status["has_conflicts"] and not force:
        return {
            "project_id": project_id,
            "error": "Conflicts detected. Use --force to override.",
            "conflicted": status["conflicted"],
            "pushed": [],
        }

    _, project_hashes, _, baseline = _snapshot(repo_root, project_dir, manifest_path)
    pushed: List[str] = []
    skipped: List[str] = []
    for rel in sorted(store_hashes):
        source = documents_dir / rel
        destination = repo_root / "docs" / rel
        if not force and destination.exists() and baseline.get(rel) != project_hashes.get(rel):
            skipped.append(rel)
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        pushed.append(rel)

    _write_lock(project_dir, store_hashes)
    return {
        "project_id": project_id,
        "pushed": pushed,
        "skipped": skipped,
        "total_pushed": len(pushed),
    }
