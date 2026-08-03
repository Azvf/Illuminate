"""Generic lint for machine-side knowledge metadata and doc references."""

import re
from pathlib import Path
from typing import Dict, Iterable, List, Optional
from urllib.parse import unquote, urlsplit

from .document_layout import (
    discover_manifests,
    is_root_relative_path,
    manifest_document_path,
    normalize_layout,
    resolve_root_relative_ref,
)
from .docs_export import load_config
from .docs_lint import _heading_anchors
from .docs_export import _is_within

_METADATA_FILES = ("claims.yaml", "gaps.yaml", "tests.yaml")
_ID_INLINE_RE = re.compile(r"^\s*-\s+id:\s*([^\s#]+)")
_DOC_RE = re.compile(r"^\s+-\s+(.+?)\s*$")


def _strip_yaml_value(value: str) -> str:
    value = value.strip()
    if value.startswith(("'", '"')) and value[-1:] == value[0]:
        return value[1:-1]
    return value


def _metadata_entries(path: Path):
    """Read the small YAML subset needed for id/doc_refs without PyYAML."""
    current_id: Optional[str] = None
    in_doc_refs = False
    doc_refs: List[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.rstrip()
        inline = _ID_INLINE_RE.match(line)
        if inline:
            if current_id is not None:
                yield current_id, list(doc_refs)
            current_id = _strip_yaml_value(inline.group(1))
            doc_refs = []
            in_doc_refs = False
            continue
        if current_id is None:
            continue
        inline_refs = re.match(r"^\s*doc_refs:\s*\[(.*)\]\s*$", line)
        if inline_refs:
            doc_refs.extend(
                _strip_yaml_value(item)
                for item in inline_refs.group(1).split(",")
                if item.strip()
            )
            in_doc_refs = False
            continue
        if re.match(r"^\s*doc_refs:\s*$", line):
            in_doc_refs = True
            continue
        if in_doc_refs:
            match = _DOC_RE.match(line)
            if match:
                doc_refs.append(_strip_yaml_value(match.group(1)))
                continue
            if line and not line.startswith(" "):
                in_doc_refs = False
    if current_id is not None:
        yield current_id, list(doc_refs)


def _resolve_doc_ref(
    metadata_path: Path,
    ref: str,
    docs_root: Path,
    layout: Optional[dict] = None,
) -> Optional[Path]:
    target = ref.strip()
    parsed = urlsplit(target)
    if parsed.scheme or parsed.netloc:
        return None
    if layout:
        return resolve_root_relative_ref(target, docs_root, layout)

    target_path = unquote(parsed.path)
    candidates = []
    if target_path:
        candidates.append(metadata_path.parent / target_path)
        # Verification files commonly use README.md as shorthand for the
        # owning module README one directory above verification/.
        candidates.append(metadata_path.parent.parent / target_path)
        candidates.append(docs_root / target_path)
    else:
        candidates.append(metadata_path.parent / "README.md")
        candidates.append(metadata_path.parent.parent / "README.md")
    for candidate in candidates:
        resolved = Path(candidate).resolve()
        if _is_within(resolved, docs_root) and resolved.is_file():
            return resolved
    first = Path(candidates[0]).resolve()
    return first if _is_within(first, docs_root) else None


def _lint_flat_owners(docs_root: Path, layout: dict) -> List[str]:
    errors: List[str] = []
    owners: Dict[str, Path] = {}
    manifests = discover_manifests(docs_root, layout)
    for record in manifests:
        manifest_path = record["path"]
        try:
            document, error = manifest_document_path(docs_root, record, layout)
        except OSError as exc:
            errors.append(f"{manifest_path.relative_to(docs_root)}: cannot read manifest: {exc}")
            continue
        if error:
            errors.append(f"{manifest_path.relative_to(docs_root)}: {error}")
            continue
        if document in owners:
            errors.append(
                f"{manifest_path.relative_to(docs_root)}: duplicate document owner {document} "
                f"(first in {owners[document].relative_to(docs_root)})"
            )
        else:
            owners[document] = manifest_path

    if layout["require_manifests"]:
        for kind in ("components", "modules"):
            root_name = layout["human_roots"][kind]
            human_root = docs_root / root_name
            if not human_root.is_dir():
                continue
            for document_path in sorted(human_root.rglob("*.md")):
                document = document_path.relative_to(docs_root).as_posix()
                if document not in owners:
                    errors.append(f"{document}: orphan human document without Manifest.document")
    return errors


def lint_knowledge(docs_root: Path, config_path: Optional[Path] = None) -> List[str]:
    """Validate metadata IDs, doc_refs, and optional flat-layout owners."""
    docs_root = Path(docs_root).resolve()
    if not docs_root.is_dir():
        return [f"documentation root not found: {docs_root}"]

    if config_path is None:
        candidate = docs_root / "human-docs.json"
        config_path = candidate if candidate.is_file() else None
    try:
        config = load_config(config_path)
        layout = normalize_layout(config)
    except ValueError as exc:
        return [str(exc)]

    errors: List[str] = []
    if layout:
        errors.extend(_lint_flat_owners(docs_root, layout))

    seen_ids: Dict[str, Path] = {}
    metadata_files = [
        path for path in sorted(docs_root.rglob("*.yaml"))
        if path.name in _METADATA_FILES
    ]
    for metadata_path in metadata_files:
        for item_id, refs in _metadata_entries(metadata_path):
            if item_id in seen_ids:
                errors.append(
                    f"{metadata_path.relative_to(docs_root)}: duplicate id {item_id} "
                    f"(first in {seen_ids[item_id].relative_to(docs_root)})"
                )
            else:
                seen_ids[item_id] = metadata_path
            if not refs:
                errors.append(
                    f"{metadata_path.relative_to(docs_root)}: {item_id} has no doc_refs"
                )
            for ref in refs:
                parsed = urlsplit(ref.strip())
                if layout and not is_root_relative_path(unquote(parsed.path), layout):
                    errors.append(
                        f"{metadata_path.relative_to(docs_root)}: {item_id} "
                        f"doc_ref must be root-relative: {ref}"
                    )
                    continue
                resolved = _resolve_doc_ref(metadata_path, ref, docs_root, layout)
                if resolved is None or not resolved.is_file():
                    errors.append(
                        f"{metadata_path.relative_to(docs_root)}: {item_id} "
                        f"has invalid doc_ref: {ref}"
                    )
                    continue
                fragment = urlsplit(ref).fragment
                if fragment and fragment not in _heading_anchors(resolved.read_text(encoding="utf-8")):
                    errors.append(
                        f"{metadata_path.relative_to(docs_root)}: {item_id} "
                        f"has missing heading anchor: {ref}"
                    )

    return errors


def format_knowledge_lint_errors(errors: List[str]) -> str:
    if not errors:
        return "Knowledge documentation lint: PASS"
    lines = [f"Knowledge documentation lint: FAIL ({len(errors)} issue(s))"]
    lines.extend(f"  - {error}" for error in errors)
    return "\n".join(lines)
