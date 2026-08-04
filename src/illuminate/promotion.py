"""Thin promotion registry bridging repository knowledge docs into the pack.

The knowledge store (knowledge_store.py) is a backup tool: it copies docs out
of the repository into a local cache. This module adds a small promotion
registry on top, tracking candidate docs that are candidates for being copied
into the harness knowledge pack (policies / skills / references / evidence).

Content-trust binding: a candidate is only promoted if the exact bytes being
written to the pack hash to the same ``reviewed_sha256`` that was recorded when
the candidate moved raw -> reviewed. This prevents "review A, promote B". The
state machine is unchanged (raw -> reviewed -> promoted); hash fields are data
enhancements, not a new state machine.

draft-review flow: ``knowledge_review`` may take a ``content_path`` to a
generalized draft. When given, the draft's bytes are snapshotted to
``promotions/<id>/draft.md`` and its hash is bound as ``reviewed_sha256``;
``knowledge_promote`` then writes that already-reviewed draft (or the current
source when the candidate was reviewed without a draft, validated to still
hash to the reviewed bytes). Either way, promote never accepts unreviewed
bytes.

Store remains the backup tool; this module only adds the promotion registry.
Source snapshots live in ``<store>/projects/<project-id>/promotions/<id>/`` as
``source.md`` (candidate creation) and ``draft.md`` (generalized review).

Superseding a promoted candidate removes its artifact from the pack (file +
manifest/index registration) and re-validates; the record is marked
``superseded`` only after the pack change succeeds. ``superseded`` therefore
means "Pack artifact removed + registry status", so old knowledge is no longer
consumed by the pack or Cursor.
"""

import hashlib
import json
import os
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from .knowledge_store import _get_store, _project_dir, _derive_project_id
from .validate import validate_pack


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


def _candidate_id(
    commit: Optional[str],
    repo_root: Path,
    source: str,
    anchor: Optional[str],
    target: str,
    source_sha256: str,
) -> str:
    seed = (
        f"{commit or ''}|{repo_root}|{source}|{anchor or ''}|{target}|{source_sha256}"
    )
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


def _read_pack_id(pack_dir: Path) -> str:
    """Return the pack id from pack.json (defaults to 'pack' like _derive_id)."""
    pack_json = pack_dir / "pack.json"
    try:
        data = json.loads(pack_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PromotionError(f"invalid pack.json: {pack_json}: {exc}") from exc
    if not isinstance(data, dict):
        raise PromotionError(f"invalid pack.json: {pack_json}")
    return str(data.get("id", "pack"))


def _resolve_within(root: Path, rel: str) -> str:
    """Resolve ``rel`` relative to ``root`` and reject path escape."""
    resolved = (root / rel).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise PromotionError(f"target_path escapes pack root: {rel}") from exc
    return resolved.relative_to(root.resolve()).as_posix()


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _snapshot_path(project_dir: Path, candidate_id: str, kind: str) -> Path:
    return project_dir / "promotions" / candidate_id / f"{kind}.md"


def _write_snapshot(project_dir: Path, candidate_id: str, content: str, kind: str) -> str:
    """Persist a content snapshot under promotions/<id>/<kind>.md.

    Snapshot write failures must be fatal (PromotionError): if we cannot keep a
    trustworthy copy of what was reviewed, we must not proceed to promote it.
    """
    path = _snapshot_path(project_dir, candidate_id, kind)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    except OSError as exc:
        raise PromotionError(f"failed to write {kind} snapshot {path}: {exc}") from exc
    return path.relative_to(project_dir).as_posix()


def _reviewed_content(repo_root: Path, project_dir: Path, record: dict) -> str:
    """Return the exact bytes that were reviewed: the source snapshot if it
    exists, otherwise the current source file (legacy registry entries created
    before snapshots existed)."""
    snapshot = _snapshot_path(project_dir, record["id"], "source")
    if snapshot.exists():
        return snapshot.read_text(encoding="utf-8")
    return _resolve_source(repo_root, record["source"]["path"]).read_text(encoding="utf-8")


def _sanitize_name(name: str) -> str:
    """Lowercase a name and collapse non [a-z0-9] runs to '-' for use in ids."""
    cleaned = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return cleaned or "item"


def _derive_id(manifest: dict, stem: str) -> str:
    """Derive a pack-local id from the pack id + a filename/skill stem."""
    pack_id = manifest.get("id", "pack")
    return f"{pack_id}.{_sanitize_name(stem)}"


def _reject_governance(rel: str) -> None:
    """Governance/index files are writer-owned; never promote into them, even
    with --force."""
    base = Path(rel).name
    if base == "pack.json" or base == "index.json" or rel.endswith(".schema.json"):
        raise PromotionError(f"refusing to overwrite governance file: {rel}")


def _target_written(pack_dir: Path, target: str, source_path: str, target_path: Optional[str]) -> str:
    """Resolve the pack-relative output path for a knowledge file, narrowed to
    the target's directory. --target-path cannot leave the target dir and cannot
    target a governance/index file."""
    subdir = _TARGET_DIRS[target]
    if target_path:
        rel = _resolve_within(pack_dir, target_path)
        if not (rel == subdir or rel.startswith(subdir + "/")):
            raise PromotionError(
                f"target_path must stay under {subdir}/ for target '{target}': {rel}"
            )
        if rel == subdir:
            raise PromotionError(
                f"target_path must point to a file, not a directory: {rel}"
            )
        _reject_governance(rel)
        return rel
    rel = (Path(subdir) / Path(source_path).name).as_posix()
    _reject_governance(rel)
    return rel


def _skill_written(pack_dir: Path, source_path: str, target_path: Optional[str]) -> tuple:
    """Resolve a skill's output layout. A skill lives in ``skills/<name>/`` and
    always contains SKILL.md + contract.json, so --target-path names the skill
    directory, not a file."""
    if target_path:
        rel = _resolve_within(pack_dir, target_path)
        if not (rel == "skills" or rel.startswith("skills/")):
            raise PromotionError(f"target_path must stay under skills/ for target 'skill': {rel}")
        if rel == "skills":
            raise PromotionError(
                f"target_path must name a skill directory, not the skills/ dir itself: {rel}"
            )
        name = _sanitize_name(Path(rel).name)
    else:
        name = _sanitize_name(Path(source_path).stem)
    return f"skills/{name}/SKILL.md", name


# ---------------------------------------------------------------------------
# Pack write + rollback helpers (shared by the four writers)
# ---------------------------------------------------------------------------

def _read_bytes_or_none(path: Path) -> Optional[bytes]:
    try:
        return path.read_bytes()
    except OSError:
        return None


def _read_json(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _read_json_governance(path: Path) -> dict:
    """Read a governance JSON file, surfacing malformed content as a
    PromotionError instead of letting JSONDecodeError escape uncaught.

    A promoted policy must never corrupt the policy index; if the index is
    invalid (or a previous mis-promotion wrote non-JSON into it), fail
    cleanly so the caller rolls back rather than crashing mid-write.
    """
    try:
        return _read_json(path)
    except (OSError, json.JSONDecodeError) as exc:
        raise PromotionError(f"invalid governance JSON {path}: {exc}") from exc


def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _content_sha256(path: Path) -> str:
    """Hash a file's text content (newline-normalized, matching write_text)."""
    return _sha256(path.read_text(encoding="utf-8"))


def _published_artifact(pack_dir: Path, record: dict) -> Path:
    """Return the absolute pack artifact path described by ``record``'s
    ``published`` snapshot. Raises PromotionError if the snapshot is absent or
    the record is malformed."""
    published = record.get("published")
    if not published:
        raise PromotionError(
            f"cannot verify artifact ownership: candidate {record.get('id')} "
            "has no published snapshot (re-promote or repair the registry)"
        )
    target = record.get("target")
    target_path = published.get("target_path")
    if target not in _TARGETS or not target_path:
        raise PromotionError(
            f"cannot verify artifact ownership: invalid target/target_path "
            f"(id={record.get('id')})"
        )
    return (pack_dir / target_path).resolve()


def _verify_ownership(pack_dir: Path, record: dict, published: dict) -> None:
    """Verify the pack artifact a candidate published is still the exact bytes
    it promoted.

    Binding is checked two ways: the manifest/index entry must still equal the
    published entry (id + path/dir), and the artifact file's current content
    must hash to the published ``content_sha256``. A mismatch means the
    artifact was taken over by a later promotion (e.g. a --force overwrite of
    the same path by an unrelated candidate), so this candidate no longer owns
    it. Raises PromotionError so the caller never deletes/upgrades bytes that
    are not its own. ``published`` is the snapshot dict to verify against.
    """
    pack_dir = Path(pack_dir)
    entry_id = published.get("entry_id")
    target_path = published.get("target_path")
    content_sha256 = published.get("content_sha256")
    if not entry_id or not target_path or not content_sha256:
        raise PromotionError(
            f"candidate {record.get('id')} published snapshot is incomplete; "
            "cannot verify artifact ownership"
        )

    manifest = _read_json(pack_dir / "pack.json")
    target = record.get("target")
    if target == "reference":
        entry = next(
            (r for r in manifest.get("references", []) if r.get("id") == entry_id), None
        )
        if entry is None or entry.get("path") != target_path:
            raise PromotionError(
                f"artifact no longer owned by candidate {record.get('id')}: "
                f"reference entry {entry_id} no longer maps to {target_path}; "
                "it has been taken over by a subsequent promotion"
            )
        file_path = pack_dir / entry["path"]
    elif target == "policy":
        index_rel = manifest.get("policies", {}).get("index", "policies/index.json")
        index = _read_json_governance(pack_dir / index_rel)
        entry = next(
            (p for p in index.get("policies", []) if p.get("id") == entry_id), None
        )
        rel = Path(target_path).relative_to("policies").as_posix()
        if entry is None or entry.get("path") != rel:
            raise PromotionError(
                f"artifact no longer owned by candidate {record.get('id')}: "
                f"policy entry {entry_id} no longer maps to {target_path}; "
                "it has been taken over by a subsequent promotion"
            )
        file_path = pack_dir / "policies" / entry["path"]
    elif target == "skill":
        entry = next(
            (s for s in manifest.get("skills", []) if s.get("id") == entry_id), None
        )
        dir_rel = Path(target_path).parent.as_posix()
        if entry is None or entry.get("dir") != dir_rel:
            raise PromotionError(
                f"artifact no longer owned by candidate {record.get('id')}: "
                f"skill entry {entry_id} no longer maps to {target_path}; "
                "it has been taken over by a subsequent promotion"
            )
        file_path = pack_dir / dir_rel / "SKILL.md"
    elif target == "evidence":
        if manifest.get("evidence", {}).get("config") != target_path:
            raise PromotionError(
                f"artifact no longer owned by candidate {record.get('id')}: "
                f"evidence config no longer points at {target_path}; "
                "it has been taken over by a subsequent promotion"
            )
        file_path = pack_dir / target_path
    else:
        raise PromotionError(f"invalid target: {target}")

    try:
        current_sha = _content_sha256(file_path)
    except OSError as exc:
        raise PromotionError(
            f"cannot read artifact {file_path} for ownership check: {exc}"
        ) from exc
    if current_sha != content_sha256:
        raise PromotionError(
            f"artifact no longer owned by candidate {record.get('id')}: "
            f"{file_path} content hash {current_sha[:12]} does not match "
            f"published {content_sha256[:12]}; it has been taken over by a "
            "subsequent promotion"
        )


def _assert_owns_published(pack_dir: Path, record: dict) -> None:
    """Verify the pack artifact a candidate published is still the exact bytes
    it promoted (see ``_verify_ownership``). Raises if the record has no
    ``published`` snapshot (legacy entries predating snapshot recording)."""
    pack_dir = Path(pack_dir)
    published = record.get("published")
    if not published:
        raise PromotionError(
            f"candidate {record.get('id')} has no published snapshot; "
            "cannot verify artifact ownership"
        )
    _verify_ownership(pack_dir, record, published)


def _rebuild_published(pack_dir: Path, record: dict) -> dict:
    """Reconstruct a ``published`` snapshot for a legacy promoted candidate that
    predates published-snapshot recording, so it can be superseded.

    Safety: this binds ONLY the manifest/index entry that currently maps to
    ``record['target_path']`` and the disk file at that path. It refuses if no
    entry maps to the path, or if the file's bytes no longer hash to the
    candidate's reviewed bytes (``reviewed_sha256``, falling back to
    ``source_sha256``) — a sign the artifact was taken over by a later
    promotion. The caller persists the rebuilt snapshot only after the removal
    succeeds, so a failed supersede never records a fabricated snapshot.
    """
    pack_dir = Path(pack_dir)
    target = record.get("target")
    target_path = record.get("target_path")
    if target not in _TARGETS or not target_path:
        raise PromotionError(
            f"cannot rebuild published snapshot for {record.get('id')}: "
            "record has no target/target_path"
        )
    manifest = _read_json(pack_dir / "pack.json")
    entry_id = None
    if target == "reference":
        entry = next(
            (r for r in manifest.get("references", [])
             if r.get("path") == target_path), None
        )
        if entry is None:
            raise PromotionError(
                f"cannot rebuild published snapshot for {record.get('id')}: "
                f"no reference entry maps to {target_path}; refusing to "
                "supersede an artifact this candidate does not own"
            )
        entry_id = entry.get("id")
        file_path = pack_dir / entry["path"]
    elif target == "policy":
        index_rel = manifest.get("policies", {}).get("index", "policies/index.json")
        index = _read_json_governance(pack_dir / index_rel)
        rel = Path(target_path).relative_to("policies").as_posix()
        entry = next(
            (p for p in index.get("policies", []) if p.get("path") == rel), None
        )
        if entry is None:
            raise PromotionError(
                f"cannot rebuild published snapshot for {record.get('id')}: "
                f"no policy entry maps to {target_path}; refusing to supersede "
                "an artifact this candidate does not own"
            )
        entry_id = entry.get("id")
        file_path = pack_dir / "policies" / entry["path"]
    elif target == "skill":
        dir_rel = Path(target_path).parent.as_posix()
        entry = next(
            (s for s in manifest.get("skills", []) if s.get("dir") == dir_rel), None
        )
        if entry is None:
            raise PromotionError(
                f"cannot rebuild published snapshot for {record.get('id')}: "
                f"no skill entry maps to {dir_rel}; refusing to supersede an "
                "artifact this candidate does not own"
            )
        entry_id = entry.get("id")
        file_path = pack_dir / dir_rel / "SKILL.md"
    elif target == "evidence":
        config = manifest.get("evidence", {}).get("config")
        if config != target_path:
            raise PromotionError(
                f"cannot rebuild published snapshot for {record.get('id')}: "
                f"evidence config no longer points at {target_path}; refusing "
                "to supersede an artifact this candidate does not own"
            )
        entry_id = target_path
        file_path = pack_dir / config
    else:  # pragma: no cover - guarded by _TARGETS
        raise PromotionError(f"invalid target: {target}")

    try:
        current_sha = _content_sha256(file_path)
    except OSError as exc:
        raise PromotionError(
            f"cannot read artifact {file_path} to rebuild published snapshot: {exc}"
        ) from exc
    expected = record.get("reviewed_sha256") or record.get("source_sha256")
    if expected and current_sha != expected:
        raise PromotionError(
            f"cannot rebuild published snapshot for {record.get('id')}: "
            f"{file_path} content hash {current_sha[:12]} does not match the "
            "candidate's reviewed bytes; refusing to supersede taken-over content"
        )
    return {
        "pack_id": _read_pack_id(pack_dir),
        "target_path": target_path,
        "entry_id": entry_id,
        "content_sha256": current_sha,
        "pack_version": record.get("pack_version") or _read_pack_version(pack_dir),
    }


def _assert_path_unclaimed(
    pack_dir: Path, target: str, written: str, replaced_record: dict
) -> None:
    """Guard a renamed upgrade: the new path/id must not already belong to a
    third-party entry. The only permitted existing claim is the one this
    candidate is replacing (whose published target_path is the old path). Any
    other entry claiming the new id or the new path is refused so --force can
    never overwrite an unrelated artifact."""
    pack_dir = Path(pack_dir)
    manifest = _read_json(pack_dir / "pack.json")
    old_target = replaced_record["published"]["target_path"]
    if written == old_target:
        return
    entry_id = _derive_id(manifest, Path(written).stem)
    if target == "reference":
        refs = manifest.get("references", [])
        claimants = [
            r for r in refs
            if r.get("path") != old_target
            and (r.get("id") == entry_id or r.get("path") == written)
        ]
        if claimants:
            c = claimants[0]
            raise PromotionError(
                f"cannot upgrade {replaced_record.get('id')}: new path {written} "
                f"(entry {entry_id}) is already owned by another reference "
                f"(id {c.get('id')}, path {c.get('path')}); refusing to overwrite "
                "an unrelated artifact"
            )
    elif target == "policy":
        index_rel = manifest.get("policies", {}).get("index", "policies/index.json")
        index = _read_json_governance(pack_dir / index_rel)
        rel = Path(written).relative_to("policies").as_posix()
        old_rel = Path(old_target).relative_to("policies").as_posix()
        policies = index.get("policies", [])
        claimants = [
            p for p in policies
            if p.get("path") != old_rel
            and (p.get("id") == entry_id or p.get("path") == rel)
        ]
        if claimants:
            c = claimants[0]
            raise PromotionError(
                f"cannot upgrade {replaced_record.get('id')}: new path {written} "
                f"(entry {entry_id}) is already owned by another policy "
                f"(id {c.get('id')}, path {c.get('path')}); refusing to overwrite "
                "an unrelated artifact"
            )


def _stage_file(pack_dir: Path, written: str, content: str, force: bool):
    """Write a single knowledge file, tracking it for rollback.

    Returns (created_paths, originals). ``created`` lists files that did not
    pre-exist (removed on rollback); ``originals`` maps modified files to their
    prior bytes (restored on rollback).
    """
    dest = pack_dir / written
    created: List[Path] = []
    originals: Dict[Path, Optional[bytes]] = {}
    if dest.exists():
        if not force:
            raise PromotionError(
                f"pack file already exists: {written} (use --force to overwrite)"
            )
        originals[dest] = dest.read_bytes()
    else:
        created.append(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(content, encoding="utf-8")
    return created, originals, dest


def _restore(created: List[Path], originals: Dict[Path, Optional[bytes]]) -> None:
    """Undo a pack change: remove created files, restore overwritten ones.

    Parent directories are recreated before writing so a removed subtree (e.g.
    a superseded skill directory with nested files) can be restored byte for
    byte even after its directories were deleted.
    """
    for path in created:
        if path.exists():
            path.unlink()
    for path, original in originals.items():
        if original is None:
            if path.exists():
                path.unlink()
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(original)


def _validate_or_rollback(pack_dir: Path, created: List[Path],
                          originals: Dict[Path, Optional[bytes]], written: str,
                          created_dirs: Optional[List[Path]] = None) -> None:
    """Run validate_pack; on failure roll back the whole change and raise.

    ``created_dirs`` lists directories that did not exist before this promote
    and may be removed (when empty) on rollback — used so a freshly created
    skill dir does not linger as an empty orphan after a failed validate.
    """
    ok, errors = validate_pack(pack_dir)
    if not ok:
        _restore(created, originals)
        for directory in created_dirs or []:
            if directory.exists():
                try:
                    directory.rmdir()
                except OSError:
                    # Not empty (unexpected): leave it; _restore already undid
                    # the file writes and the primary goal was met.
                    pass
        raise PromotionError(
            f"pack validation failed after promotion; changes rolled back: "
            f"{'; '.join(errors)}"
        )


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
    replaces=None,
) -> dict:
    """Register a raw promotion candidate for a docs/ file.

    Records ``source_sha256`` (hash of the source at creation) and persists a
    content snapshot to ``promotions/<id>/source.md`` so later review/promote
    can verify byte-for-byte fidelity.

    ``replaces`` optionally names an already-promoted candidate id this one is
    an explicit successor of (used for a renamed --force upgrade). The owning
    candidate is validated at promote time; here it is only stored.
    """
    repo_root = Path(repo_root).resolve()
    if target not in _TARGETS:
        raise PromotionError(f"invalid target: {target}")
    source_path = _resolve_source(repo_root, source)
    source_text = source_path.read_text(encoding="utf-8")
    source_sha256 = _sha256(source_text)

    project_id, project_dir, candidates = _load(store, repo_root)
    remote, commit = _git_source(repo_root)
    candidate_id = _candidate_id(commit, repo_root, source, anchor, target, source_sha256)
    for existing in candidates:
        if existing.get("id") == candidate_id:
            return existing
    now = _now()
    snapshot_file = _write_snapshot(project_dir, candidate_id, source_text, "source")

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
        "replaces": replaces,
        "reviewer": None,
        "notes": notes,
        "generalized": False,
        "source_sha256": source_sha256,
        "snapshot_file": snapshot_file,
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
    content_path: Optional[Path] = None,
) -> dict:
    """Move a candidate from raw to reviewed, binding the reviewed bytes.

    Without ``content_path`` the reviewed bytes are the source snapshot
    (falling back to the current source file for legacy registry entries), and
    the candidate is not ``generalized``. With ``content_path`` the given draft
    file is read, snapshotted to ``promotions/<id>/draft.md``, and its bytes
    become the reviewed content (the candidate is marked ``generalized``).
    Promote later refuses any bytes that do not hash to ``reviewed_sha256``.
    """
    repo_root = Path(repo_root).resolve()
    _, project_dir, candidates = _load(store, repo_root)
    record = _find(candidates, candidate_id)
    # A legacy candidate that is already ``reviewed`` but never bound a
    # ``reviewed_sha256`` is stuck: promote refuses empty hashes and the strict
    # ``raw`` check blocks re-review. Re-admit such candidates so the binding
    # can be completed. The state machine is unchanged; this only widens the
    # re-review entry point for that one legacy case.
    if record["status"] == "reviewed" and record.get("reviewed_sha256"):
        raise PromotionError(
            f"cannot review candidate in status 'reviewed' (already bound)"
        )
    if record["status"] not in ("raw", "reviewed"):
        raise PromotionError(
            f"cannot review candidate in status '{record['status']}' (expected 'raw')"
        )
    if content_path is not None:
        content_path = Path(content_path).resolve()
        try:
            content = content_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise PromotionError(
                f"cannot read content_path: {content_path}: {exc}"
            ) from exc
        draft_file = _write_snapshot(project_dir, candidate_id, content, "draft")
        record["draft_file"] = draft_file
        record["draft_sha256"] = _sha256(content)
        record["generalized"] = True
    else:
        content = _reviewed_content(repo_root, project_dir, record)
        record["generalized"] = False
    record["status"] = "reviewed"
    record["reviewed_sha256"] = _sha256(content)
    record["reviewed_at"] = _now()
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
    dry_run=False,
    force=False,
) -> dict:
    """Write a reviewed candidate's content into the pack.

    Content-trust binding: the bytes to be written must hash to
    ``reviewed_sha256``, otherwise promotion is rejected. The content is the
    already-reviewed draft snapshot (``draft_file``) when the candidate was
    reviewed with ``--content``, otherwise the current source document (so a
    source edit after review is caught and rejected). The draft is recorded by
    ``knowledge_review``; promote never writes or accepts a draft.

    Each target has a dedicated writer that registers the new file in the pack
    manifest and runs validate_pack, rolling back the whole change (files +
    manifest + index) if validation fails.
    """
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
    source_path = record["source"]["path"]

    # Resolve the content to write: the reviewed draft snapshot when the
    # candidate was reviewed with --content, otherwise the current source file
    # (which must still hash to the reviewed bytes, so a source edit after
    # review is caught and rejected).
    generalized = record.get("generalized", False)
    if generalized and record.get("draft_file"):
        content = (project_dir / record["draft_file"]).read_text(encoding="utf-8")
    else:
        content = _resolve_source(repo_root, source_path).read_text(encoding="utf-8")

    reviewed_sha256 = record.get("reviewed_sha256")
    if not reviewed_sha256:
        raise PromotionError("candidate has no reviewed_sha256; re-review before promoting")
    content_sha256 = _sha256(content)
    if content_sha256 != reviewed_sha256:
        raise PromotionError(
            "promotion content sha256 does not match reviewed_sha256 "
            f"({content_sha256[:12]} != {reviewed_sha256[:12]}); "
            "refusing to promote unreviewed bytes"
        )

    # Resolve output path per target (narrowed + governance-checked).
    if target == "skill":
        written, skill_name = _skill_written(pack_dir, source_path, target_path)
    else:
        written = _target_written(pack_dir, target, source_path, target_path)
        skill_name = None

    if dry_run:
        return {
            "candidate_id": candidate_id,
            "pack_version": pack_version,
            "written": written,
            "dry_run": True,
            "status": "reviewed",
            "generalized": generalized,
        }

    # Explicit rename upgrade: the candidate declares a predecessor with
    # --replaces. We resolve the predecessor's published artifact (must still
    # be owned by it), and thread its previous path into the writer so a
    # renamed --force upgrade updates the correct entry in place instead of
    # guessing from the new stem or overwriting an unrelated entry.
    replaces = record.get("replaces")
    previous_target_path = None
    replaced_record = None
    if replaces:
        if target not in ("reference", "policy"):
            raise PromotionError(
                f"--replaces is only supported for reference/policy targets "
                f"(target is '{target}')"
            )
        # A --replaces upgrade replaces the predecessor's entry in place (it
        # rewrites its id/path and removes the old artifact file). That is an
        # overwrite, which only --force authorizes; --replaces and --force are
        # orthogonal (explicit succession vs. permission to overwrite), but the
        # former always performs an overwrite of the predecessor, so both are
        # required. Without --force, the writer would otherwise append a second
        # entry and leave the predecessor's artifact orphaned and unsupersed.
        if not force:
            raise PromotionError(
                f"--replaces requires --force: upgrading the predecessor's pack "
                f"entry in place (id/path change) overwrites existing content, "
                f"which --force authorizes"
            )
        replaced_record = _find(candidates, replaces)
        if replaced_record["status"] != "promoted":
            raise PromotionError(
                f"replaced candidate '{replaces}' is in status "
                f"'{replaced_record['status']}', expected 'promoted'"
            )
        _assert_owns_published(pack_dir, replaced_record)
        previous_target_path = replaced_record["published"]["target_path"]
        # The new artifact path must not already belong to a third party.
        _assert_path_unclaimed(pack_dir, target, written, replaced_record)

    if target == "reference":
        written_result = promote_reference(pack_dir, written, content, force,
                                           pack_version, previous_target_path)
    elif target == "policy":
        written_result = promote_policy(pack_dir, written, content, force,
                                        pack_version, previous_target_path)
    elif target == "skill":
        written_result = promote_skill(pack_dir, skill_name, content, force,
                                       pack_version)
    elif target == "evidence":
        written_result = promote_evidence(pack_dir, written, content, force,
                                          pack_version)
    else:  # pragma: no cover - guarded earlier by _TARGETS
        raise PromotionError(f"invalid target: {target}")

    record["status"] = "promoted"
    record["target_path"] = written
    record["generalized"] = generalized
    record["pack_version"] = pack_version
    record["published"] = {
        "pack_id": _read_pack_id(pack_dir),
        "target_path": written,
        "entry_id": written_result["id"],
        "content_sha256": content_sha256,
        "pack_version": pack_version,
    }
    record["updated_at"] = _now()

    # A promoted successor atomically supersedes its declared predecessor: the
    # old entry was upgraded in place and the old candidate no longer owns the
    # artifact. Both registry writes are in the same list, so one _write_registry
    # persists the pair atomically.
    if replaced_record is not None:
        replaced_record["status"] = "superseded"
        replaced_record["superseded_at"] = _now()
        replaced_record["superseded_by"] = candidate_id
        replaced_record["updated_at"] = _now()

    _write_registry(project_dir, candidates)

    return {
        "candidate_id": candidate_id,
        "pack_version": pack_version,
        "written": written,
        "dry_run": False,
        "status": "promoted",
        "generalized": generalized,
        "replaces": replaces,
    }


# ---------------------------------------------------------------------------
# Per-target pack writers (four direct implementations, no dispatcher/registry)
# ---------------------------------------------------------------------------

def promote_reference(pack_dir, written, content, force, pack_version,
                      previous_target_path=None) -> dict:
    """Write a reference file and register it in ``pack.json.references``.

    The entry id is derived from the pack id + the filename stem and must be
    unique in the manifest. A duplicate id is rejected unless ``--force``, in
    which case the existing entry's ``path`` is updated to the new ``written``
    path (an in-place upgrade). If ``--target-path`` changed the basename, the
    new-id lookup misses, so under force we fall back to locating the entry
    this candidate previously promoted (``previous_target_path``) and upgrade
    its path + id in place; otherwise we append. If the old path differs from
    the new one, the old file is removed only after validate_pack succeeds.
    Runs validate_pack and rolls back on failure.
    """
    pack_dir = Path(pack_dir)
    created, originals, _ = _stage_file(pack_dir, written, content, force)
    pack_path = pack_dir / "pack.json"
    originals[pack_path] = _read_bytes_or_none(pack_path)
    manifest = _read_json(pack_path)
    ref_id = _derive_id(manifest, Path(written).stem)
    refs = manifest.setdefault("references", [])
    existing = next((r for r in refs if r.get("id") == ref_id), None)
    if existing is None and force and previous_target_path:
        existing = next((r for r in refs if r.get("path") == previous_target_path), None)
    old_path = existing.get("path") if existing else None
    if existing:
        if not force:
            _restore(created, originals)
            raise PromotionError(f"reference already registered in pack manifest: {ref_id}")
        existing["path"] = written
        existing["id"] = ref_id
    else:
        refs.append({"id": ref_id, "path": written})
    _write_json(pack_path, manifest)
    _validate_or_rollback(pack_dir, created, originals, written)
    # With --force the previous reference was replaced; if it is no longer
    # referenced by the manifest, remove the orphan file so a pack upgrade
    # does not leave dead references behind. Orphan removal is part of the
    # transaction: a failure rolls the whole promote back so pack and registry
    # never diverge.
    if old_path and old_path != written:
        orphan = (pack_dir / old_path).resolve()
        if orphan.is_file() and orphan.is_relative_to(pack_dir.resolve()):
            try:
                orphan.unlink()
            except OSError as exc:
                _restore(created, originals)
                raise PromotionError(
                    f"failed to remove orphaned reference {orphan}: {exc}; "
                    "promotion rolled back"
                ) from exc
    return {"written": written, "id": ref_id}


def promote_policy(pack_dir, written, content, force, pack_version,
                   previous_target_path=None) -> dict:
    """Write a policy file and register it in ``policies/index.json``.

    The policy is registered with priority 0 (lowest) so a new policy never
    shadows existing mandatory ones; id is derived from the pack id + filename
    stem. A duplicate id is rejected unless ``--force``, in which case the
    existing index entry's ``path`` is updated to the new ``written`` path (an
    in-place upgrade). If ``--target-path`` changed the basename, the new-id
    lookup misses, so under force we fall back to locating the entry this
    candidate previously promoted (``previous_target_path``) and upgrade its
    path + id in place; otherwise we append. If the old path differs from the
    new one, the old file is removed only after validate_pack succeeds. If the
    policy index is malformed, the already-staged policy file and originals are
    rolled back before re-raising. Runs validate_pack and rolls back.
    """
    pack_dir = Path(pack_dir)
    created, originals, _ = _stage_file(pack_dir, written, content, force)
    pack_path = pack_dir / "pack.json"
    originals[pack_path] = _read_bytes_or_none(pack_path)
    manifest = _read_json(pack_path)
    policies_meta = manifest.setdefault("policies", {})
    index_rel = policies_meta.setdefault("index", "policies/index.json")
    index_path = pack_dir / index_rel
    originals[index_path] = _read_bytes_or_none(index_path)
    if index_path.exists():
        try:
            index = _read_json_governance(index_path)
        except PromotionError:
            _restore(created, originals)
            raise
    else:
        index = {"schema_version": 1, "policies": []}
    policy_id = _derive_id(manifest, Path(written).stem)
    policies = index.setdefault("policies", [])
    existing = next((p for p in policies if p.get("id") == policy_id), None)
    if existing is None and force and previous_target_path:
        old_rel = Path(previous_target_path).relative_to("policies").as_posix()
        existing = next((p for p in policies if p.get("path") == old_rel), None)
    old_path = existing.get("path") if existing else None
    if existing:
        if not force:
            _restore(created, originals)
            raise PromotionError(f"policy already registered in index: {policy_id}")
        existing["path"] = Path(written).relative_to("policies").as_posix()
        existing["id"] = policy_id
    else:
        # Policy paths in the index are relative to the policies/ directory.
        policies.append(
            {
                "id": policy_id,
                "path": Path(written).relative_to("policies").as_posix(),
                "priority": 0,
            }
        )
    _write_json(index_path, index)
    _validate_or_rollback(pack_dir, created, originals, written)
    # With --force the previous policy was replaced; if it is no longer
    # referenced by the index, remove the orphan file so a pack upgrade does
    # not leave dead policies behind. Orphan removal is part of the transaction:
    # a failure rolls the whole promote back so pack and registry never diverge.
    if old_path and old_path != Path(written).relative_to("policies").as_posix():
        orphan = (pack_dir / "policies" / old_path).resolve()
        if orphan.is_file() and orphan.is_relative_to(pack_dir.resolve()):
            try:
                orphan.unlink()
            except OSError as exc:
                _restore(created, originals)
                raise PromotionError(
                    f"failed to remove orphaned policy {orphan}: {exc}; "
                    "promotion rolled back"
                ) from exc
    return {"written": written, "id": policy_id}


def promote_skill(pack_dir, name, content, force, pack_version) -> dict:
    """Write a skill: ``skills/<name>/SKILL.md`` + a minimal ``contract.json``,
    and register it in ``pack.json.skills``.

    contract.json satisfies skill-contract.schema.json (id = ``<pack-id>.<name>``,
    entry, kind="skill", activation). The schema forbids name/description fields,
    so none are emitted. If the same skill id already exists in the manifest (or
    the skill dir already exists), promotion is rejected unless ``--force``.
    Runs validate_pack and rolls back on failure.
    """
    pack_dir = Path(pack_dir)
    dir_rel = f"skills/{name}"
    skill_md = f"{dir_rel}/SKILL.md"
    skill_dir = pack_dir / dir_rel
    pack_path = pack_dir / "pack.json"
    originals: Dict[Path, Optional[bytes]] = {pack_path: _read_bytes_or_none(pack_path)}
    manifest = _read_json(pack_path)
    skill_id = _derive_id(manifest, name)
    existing = [e for e in manifest.get("skills", []) if e.get("id") == skill_id]
    if (skill_dir.exists() or existing) and not force:
        raise PromotionError(
            f"skill already present in pack: {skill_id} (use --force to overwrite)"
        )
    skill_dir_pre_existed = skill_dir.exists()
    for fname in ("SKILL.md", "contract.json"):
        originals.setdefault(skill_dir / fname, _read_bytes_or_none(skill_dir / fname))
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")
    (skill_dir / "contract.json").write_text(
        json.dumps(_minimal_contract(skill_id, pack_version), indent=2) + "\n",
        encoding="utf-8",
    )
    skills = manifest.setdefault("skills", [])
    if existing:
        for entry in skills:
            if entry.get("id") == skill_id:
                entry["dir"] = dir_rel
    else:
        skills.append({"id": skill_id, "dir": dir_rel})
    _write_json(pack_path, manifest)
    created_dirs = [skill_dir] if not skill_dir_pre_existed else None
    _validate_or_rollback(pack_dir, [], originals, skill_md, created_dirs=created_dirs)
    return {"written": skill_md, "id": skill_id}


def _minimal_contract(skill_id: str, pack_version: str) -> dict:
    """Minimal contract.json conforming to skill-contract.schema.json."""
    return {
        "schema_version": 1,
        "id": skill_id,
        "version": pack_version,
        "entry": "SKILL.md",
        "kind": "skill",
        "activation": {"mode": "explicit"},
    }


def promote_evidence(pack_dir, written, content, force, pack_version) -> dict:
    """Write an evidence config file and register it in ``pack.json.evidence.config``.

    If a config path is already declared in the manifest it is only replaced
    when ``--force`` is passed. Runs validate_pack and rolls back on failure.
    """
    pack_dir = Path(pack_dir)
    created, originals, _ = _stage_file(pack_dir, written, content, force)
    pack_path = pack_dir / "pack.json"
    originals[pack_path] = _read_bytes_or_none(pack_path)
    manifest = _read_json(pack_path)
    evidence = manifest.setdefault("evidence", {})
    existing_config = evidence.get("config")
    if existing_config and existing_config != written and not force:
        _restore(created, originals)
        raise PromotionError(
            f"evidence config already set to {existing_config}; "
            f"use --force to replace with {written}"
        )
    evidence["config"] = written
    _write_json(pack_path, manifest)
    _validate_or_rollback(pack_dir, created, originals, written)
    # With --force the previous config was replaced; if it is no longer
    # referenced by the manifest, remove the orphan file so a pack upgrade
    # does not leave dead configs behind. Orphan removal is part of the
    # transaction: a failure rolls the whole promote back.
    if existing_config and existing_config != written:
        orphan = (pack_dir / existing_config).resolve()
        if orphan.is_file() and orphan.is_relative_to(pack_dir.resolve()):
            try:
                orphan.unlink()
            except OSError as exc:
                _restore(created, originals)
                raise PromotionError(
                    f"failed to remove orphaned evidence config {orphan}: {exc}; "
                    "promotion rolled back"
                ) from exc
    return {"written": written, "id": written}


def _unlink_if_exists(path: Path) -> None:
    """Delete a file; no-op if it is absent. Never silently swallows an error:
    an OSError is surfaced as PromotionError so a partial supersede rolls back
    instead of leaving pack and registry out of sync."""
    try:
        if path.exists():
            path.unlink()
    except OSError as exc:
        raise PromotionError(f"failed to remove {path}: {exc}") from exc


def _precheck_removable(paths) -> None:
    """Verify every artifact path exists (or is an empty skill dir to remove)
    and is writable before deletion begins, so a supersede fails fast rather
    than half-deleting then rolling back mid-transaction."""
    for p in paths:
        if p is None:
            continue
        p = Path(p)
        if not p.exists():
            raise PromotionError(f"artifact to remove does not exist: {p}")
        if p.is_dir():
            continue
        if not os.access(p, os.W_OK):
            raise PromotionError(f"artifact is not writable, cannot remove: {p}")


def _unpromote(pack_dir: Path, record: dict) -> None:
    """Remove a promoted artifact from the pack (reverse of promote).

    Deletes the promoted file (or skill directory) and removes its manifest /
    index registration, recording originals first. Runs validate_pack and, on
    failure, restores every recorded original and re-raises, so a failed
    supersede leaves the pack untouched and the registry unpromoted.

    Ownership is bound: before removing anything, the current artifact is
    verified against the candidate's ``published`` snapshot (manifest entry and
    content hash). If it was taken over by a later promotion, supersede raises
    and never deletes bytes it does not own.
    """
    pack_dir = Path(pack_dir)
    target = record.get("target")
    if target not in _TARGETS:
        raise PromotionError(
            f"cannot locate pack artifact for supersede: record has no "
            f"target (id={record.get('id')})"
        )

    # Ownership binding (P0-1): the current manifest entry and artifact bytes
    # must still be this candidate's published ones, else refuse to delete.
    published = record.get("published")
    if published is None:
        # Legacy candidate promoted before published snapshots existed: rebuild
        # the snapshot from the current manifest entry at target_path + the
        # disk file, then verify ownership normally. Persisted only after the
        # removal succeeds (see the tail of this function).
        published = _rebuild_published(pack_dir, record)
        rebuilt_published = True
    else:
        rebuilt_published = False
    _verify_ownership(pack_dir, record, published)
    target_path = published["target_path"]
    entry_id = published["entry_id"]

    originals: Dict[Path, Optional[bytes]] = {}
    skill_dir: Optional[Path] = None

    pack_path = pack_dir / "pack.json"
    originals[pack_path] = _read_bytes_or_none(pack_path)
    manifest = _read_json(pack_path)

    to_remove: List[Path] = []

    if target == "reference":
        refs = manifest.setdefault("references", [])
        entry = next((r for r in refs if r.get("id") == entry_id), None)
        if entry is None:
            raise PromotionError(f"reference not registered in pack manifest: {entry_id}")
        file_path = pack_dir / entry["path"]
        originals[file_path] = _read_bytes_or_none(file_path)
        to_remove.append(file_path)
        _precheck_removable(to_remove)
        refs.remove(entry)
        _write_json(pack_path, manifest)
        try:
            _unlink_if_exists(file_path)
        except PromotionError:
            _restore([], originals)
            raise

    elif target == "policy":
        policies_meta = manifest.setdefault("policies", {})
        index_rel = policies_meta.setdefault("index", "policies/index.json")
        index_path = pack_dir / index_rel
        originals[index_path] = _read_bytes_or_none(index_path)
        index = _read_json_governance(index_path)
        policies = index.setdefault("policies", [])
        entry = next((p for p in policies if p.get("id") == entry_id), None)
        if entry is None:
            raise PromotionError(f"policy not registered in index: {entry_id}")
        file_path = pack_dir / "policies" / entry["path"]
        originals[file_path] = _read_bytes_or_none(file_path)
        to_remove.append(file_path)
        _precheck_removable(to_remove)
        policies.remove(entry)
        _write_json(index_path, index)
        try:
            _unlink_if_exists(file_path)
        except PromotionError:
            _restore([], originals)
            raise

    elif target == "skill":
        skills = manifest.setdefault("skills", [])
        entry = next((s for s in skills if s.get("id") == entry_id), None)
        if entry is None:
            raise PromotionError(f"skill not registered in pack manifest: {entry_id}")
        skill_dir = pack_dir / entry["dir"]
        if skill_dir.exists():
            to_remove.append(skill_dir)
            _precheck_removable(to_remove)
            for f in skill_dir.rglob("*"):
                if f.is_file():
                    originals[f] = _read_bytes_or_none(f)
        skills.remove(entry)
        _write_json(pack_path, manifest)
        if skill_dir.exists():
            try:
                shutil.rmtree(skill_dir)
            except OSError as exc:
                _restore([], originals)
                raise PromotionError(
                    f"failed to remove skill directory {skill_dir} during supersede "
                    f"({exc}); changes rolled back"
                ) from exc
            if skill_dir.exists():
                _restore([], originals)
                raise PromotionError(
                    f"failed to remove skill directory {skill_dir} during supersede; "
                    "changes rolled back"
                )

    elif target == "evidence":
        evidence = manifest.setdefault("evidence", {})
        config = evidence.get("config")
        if not config or config != target_path:
            raise PromotionError(
                f"evidence config not set to {target_path}: {config or '<none>'}"
            )
        file_path = pack_dir / config
        originals[file_path] = _read_bytes_or_none(file_path)
        to_remove.append(file_path)
        _precheck_removable(to_remove)
        del evidence["config"]
        _write_json(pack_path, manifest)
        try:
            _unlink_if_exists(file_path)
        except PromotionError:
            _restore([], originals)
            raise

    ok, errors = validate_pack(pack_dir)
    if not ok:
        # _restore recreates parent dirs, so a removed skill subtree is restored
        # byte-for-byte even if it contained nested directories.
        _restore([], originals)
        raise PromotionError(
            f"pack validation failed after supersede; changes rolled back: "
            f"{'; '.join(errors)}"
        )
    if rebuilt_published:
        # The removal succeeded; only now persist the reconstructed snapshot so
        # a failed supersede never records a fabricated published block. The
        # caller (knowledge_reject) saves the record after _unpromote returns.
        record["published"] = published


def knowledge_reject(
    repo_root,
    candidate_id,
    store=None,
    reviewer=None,
    supersede=False,
    notes=None,
    pack_dir=None,
) -> dict:
    """Reject a candidate, or supersede a promoted one.

    With ``supersede=True`` the promoted artifact is removed from ``pack_dir``
    (file + manifest/index registration) and the pack is re-validated; on
    success the record is marked ``superseded``. ``pack_dir`` is required for
    supersede. ``superseded`` therefore means "Pack artifact removed + registry
    status" — a superseded item is no longer consumed by the pack or Cursor.
    """
    repo_root = Path(repo_root).resolve()
    _, project_dir, candidates = _load(store, repo_root)
    record = _find(candidates, candidate_id)
    status = record["status"]

    if supersede:
        if status != "promoted":
            raise PromotionError(
                f"cannot supersede candidate in status '{status}' (only 'promoted')"
            )
        if pack_dir is None:
            raise PromotionError(
                "superseding a promoted candidate requires --pack "
                "(the promoted artifact is removed from the pack)"
            )
        _unpromote(pack_dir, record)
        record["status"] = "superseded"
        record["superseded_at"] = _now()
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
