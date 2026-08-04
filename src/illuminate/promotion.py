"""Thin promotion registry bridging repository knowledge docs into the pack.

The knowledge store (knowledge_store.py) is a backup tool: it copies docs out
of the repository into a local cache. This module adds a small promotion
registry on top, tracking candidate docs that are candidates for being copied
into the harness knowledge pack (policies / skills / references / evidence).

It does NOT manage content or workflow beyond a flat candidate ledger. A
candidate is a record in ``<store>/projects/<project-id>/promotions.json``,
and generalized content (if any) is written to
``<store>/projects/<project-id>/promotions/<id>.md``.

Store remains the backup tool; this module only adds the promotion registry.
"""

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from .knowledge_store import _get_store, _project_dir, _derive_project_id


class PromotionError(ValueError):
    """Raised for invalid state transitions or malformed registries."""


_TARGETS = {"policy", "skill", "reference", "evidence"}
_TARGET_DIRS = {
    "policy": "policies",
    "skill": "skills",
    "reference": "references",
    "evidence": "evidence",
}

_REGISTRY_SCHEMA_VERSION = 1


# ---------------------------------------------------------------------------
# Registry I/O (same style as knowledge_store lock files)
# ---------------------------------------------------------------------------

def _registry_path(project_dir: Path) -> Path:
    return project_dir / "promotions.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _read_registry(project_dir: Path) -> List[dict]:
    path = _registry_path(project_dir)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PromotionError(f"invalid promotions registry: {path}: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("candidates", []), list):
        raise PromotionError(f"invalid promotions registry: {path}")
    return data["candidates"]


def _write_registry(project_dir: Path, candidates: List[dict]) -> None:
    project_dir.mkdir(parents=True, exist_ok=True)
    payload = {"schema_version": _REGISTRY_SCHEMA_VERSION, "candidates": candidates}
    _registry_path(project_dir).write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
    )


def _load(store: Optional[Path], repo_root: Path):
    store_path = _get_store(store)
    project_id = _derive_project_id(repo_root)
    project_dir = _project_dir(store_path, project_id)
    return project_id, project_dir, _read_registry(project_dir)


def _find(candidates: List[dict], candidate_id: str) -> dict:
    for record in candidates:
        if record.get("id") == candidate_id:
            return record
    raise PromotionError(f"candidate not found: {candidate_id}")


def _save(project_dir: Path, candidates: List[dict], record: dict) -> None:
    for index, existing in enumerate(candidates):
        if existing.get("id") == record["id"]:
            candidates[index] = record
            break
    _write_registry(project_dir, candidates)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _git_capture(repo_root: Path, args: List[str]) -> Optional[str]:
    """Best-effort git query; never raises. Returns stripped output or None."""
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root)] + args,
            capture_output=True, text=True, check=False,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except OSError:
        pass
    return None


def _git_source(repo_root: Path) -> tuple:
    remote = _git_capture(repo_root, ["remote", "get-url", "origin"])
    commit = _git_capture(repo_root, ["rev-parse", "HEAD"])
    return remote, commit


def _candidate_id(commit: Optional[str], repo_root: Path, source: str, anchor: Optional[str]) -> str:
    seed = f"{commit or ''}|{repo_root}|{source}|{anchor or ''}"
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]


def _resolve_source(repo_root: Path, source: str) -> Path:
    docs_root = (repo_root / "docs").resolve()
    candidate = (docs_root / source).resolve()
    try:
        candidate.relative_to(docs_root)
    except ValueError as exc:
        raise PromotionError(f"source escapes docs/: {source}") from exc
    if not candidate.is_file():
        raise PromotionError(f"source does not exist: {source}")
    return candidate


def _read_pack_version(pack_dir: Path) -> str:
    if not pack_dir.is_dir():
        raise PromotionError(f"pack dir not found: {pack_dir}")
    pack_json = pack_dir / "pack.json"
    if not pack_json.is_file():
        raise PromotionError(f"pack.json not found: {pack_dir}")
    try:
        data = json.loads(pack_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PromotionError(f"invalid pack.json: {pack_json}: {exc}") from exc
    if not isinstance(data, dict) or "version" not in data:
        raise PromotionError(f"pack.json has no version: {pack_json}")
    return str(data["version"])


def _resolve_within(root: Path, rel: str) -> str:
    """Resolve ``rel`` relative to ``root`` and reject path escape."""
    resolved = (root / rel).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise PromotionError(f"target_path escapes pack root: {rel}") from exc
    return resolved.relative_to(root.resolve()).as_posix()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def knowledge_candidate(
    repo_root,
    source,
    target,
    store=None,
    anchor=None,
    notes=None,
) -> dict:
    """Register a raw promotion candidate for a docs/ file."""
    repo_root = Path(repo_root).resolve()
    if target not in _TARGETS:
        raise PromotionError(f"invalid target: {target}")
    _resolve_source(repo_root, source)

    project_id, project_dir, candidates = _load(store, repo_root)
    remote, commit = _git_source(repo_root)
    candidate_id = _candidate_id(commit, repo_root, source, anchor)
    for existing in candidates:
        if existing.get("id") == candidate_id:
            return existing
    now = _now()

    record = {
        "id": candidate_id,
        "status": "raw",
        "source": {
            "repo": remote,
            "commit": commit,
            "path": source,
            "anchor": anchor,
        },
        "target": target,
        "target_path": None,
        "reviewer": None,
        "notes": notes,
        "generalized": False,
        "content_file": None,
        "pack_version": None,
        "created_at": now,
        "updated_at": now,
    }
    candidates.append(record)
    _write_registry(project_dir, candidates)
    return record


def knowledge_review(
    repo_root,
    candidate_id,
    store=None,
    reviewer=None,
    notes=None,
) -> dict:
    """Move a candidate from raw to reviewed."""
    repo_root = Path(repo_root).resolve()
    _, project_dir, candidates = _load(store, repo_root)
    record = _find(candidates, candidate_id)
    if record["status"] != "raw":
        raise PromotionError(
            f"cannot review candidate in status '{record['status']}' (expected 'raw')"
        )
    record["status"] = "reviewed"
    record["reviewer"] = reviewer
    if notes is not None:
        record["notes"] = notes
    record["updated_at"] = _now()
    _save(project_dir, candidates, record)
    return record


def knowledge_promote(
    repo_root,
    candidate_id,
    pack_dir,
    store=None,
    target_path=None,
    content_path=None,
    dry_run=False,
    force=False,
) -> dict:
    """Write a reviewed candidate's content into the pack."""
    repo_root = Path(repo_root).resolve()
    pack_dir = Path(pack_dir).resolve()
    pack_version = _read_pack_version(pack_dir)

    _, project_dir, candidates = _load(store, repo_root)
    record = _find(candidates, candidate_id)
    if record["status"] != "reviewed":
        raise PromotionError(
            f"cannot promote candidate in status '{record['status']}' (expected 'reviewed')"
        )

    target = record["target"]
    target_dir = _TARGET_DIRS[target]
    source_path = record["source"]["path"]

    # Resolve output path relative to pack root, then ensure it stays inside pack.
    if target_path:
        # target_path is a full override relative to the pack root.
        written = _resolve_within(pack_dir, target_path)
    else:
        # Default: basename under the target directory (keeps the pack flat).
        written = (Path(target_dir) / Path(source_path).name).as_posix()

    # Resolve content source.
    generalized = False
    if content_path is not None:
        content_path = Path(content_path).resolve()
        try:
            content = content_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise PromotionError(f"cannot read content_path: {content_path}: {exc}") from exc
        generalized = True
    else:
        content = _resolve_source(repo_root, source_path).read_text(encoding="utf-8")

    destination = pack_dir / written
    if destination.exists() and not force:
        raise PromotionError(
            f"pack file already exists: {written} (use --force to overwrite)"
        )

    if dry_run:
        return {
            "candidate_id": candidate_id,
            "pack_version": pack_version,
            "written": written,
            "dry_run": True,
            "status": "reviewed",
            "generalized": generalized,
        }

    # Persist generalized content snapshot before writing.
    content_file = None
    if generalized:
        promotions_dir = project_dir / "promotions"
        promotions_dir.mkdir(parents=True, exist_ok=True)
        content_file = (promotions_dir / f"{candidate_id}.md").as_posix()
        (promotions_dir / f"{candidate_id}.md").write_text(content, encoding="utf-8")

    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(content, encoding="utf-8")

    record["status"] = "promoted"
    record["target_path"] = written
    record["content_file"] = content_file
    record["generalized"] = generalized
    record["pack_version"] = pack_version
    record["updated_at"] = _now()
    _save(project_dir, candidates, record)

    return {
        "candidate_id": candidate_id,
        "pack_version": pack_version,
        "written": written,
        "dry_run": False,
        "status": "promoted",
        "generalized": generalized,
    }


def knowledge_reject(
    repo_root,
    candidate_id,
    store=None,
    reviewer=None,
    supersede=False,
    notes=None,
) -> dict:
    """Reject a candidate, or supersede a promoted one."""
    repo_root = Path(repo_root).resolve()
    _, project_dir, candidates = _load(store, repo_root)
    record = _find(candidates, candidate_id)
    status = record["status"]

    if supersede:
        if status != "promoted":
            raise PromotionError(
                f"cannot supersede candidate in status '{status}' (only 'promoted')"
            )
        record["status"] = "superseded"
    else:
        if status not in {"raw", "reviewed"}:
            raise PromotionError(
                f"cannot reject candidate in status '{status}' (expected 'raw' or 'reviewed')"
            )
        record["status"] = "rejected"

    if reviewer is not None:
        record["reviewer"] = reviewer
    if notes is not None:
        record["notes"] = notes
    record["updated_at"] = _now()
    _save(project_dir, candidates, record)
    return record
