"""Shared validation for classified human documents and metadata owners."""

import re
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import unquote, urlsplit

FLAT_CLASSIFIED = "flat-classified"
DEFAULT_HUMAN_ROOTS = {
    "components": "20-components",
    "modules": "30-modules",
    "journeys": "40-journeys",
}
DEFAULT_METADATA_ROOT = "70-metadata"
_MANIFEST_FILES = {
    "components": "component.yaml",
    "modules": "module.yaml",
}
_SCALAR_RE = re.compile(r"^\s*(?:id|document)\s*:\s*(.*?)\s*(?:#.*)?$")


class LayoutError(ValueError):
    """Raised when a document layout profile is invalid."""


def normalize_layout(config: Optional[dict]) -> Optional[dict]:
    """Return the validated layout profile from a human-doc config."""
    config = config or {}
    name = config.get("layout")
    if name is None:
        return None
    if isinstance(name, dict):
        if name.get("name") != FLAT_CLASSIFIED:
            raise LayoutError(f"unsupported documentation layout: {name}")
        return name
    if name != FLAT_CLASSIFIED:
        raise LayoutError(f"unsupported documentation layout: {name}")

    human_roots = config.get("human_roots", DEFAULT_HUMAN_ROOTS)
    if not isinstance(human_roots, dict):
        raise LayoutError("human_roots must be an object")
    roots = dict(DEFAULT_HUMAN_ROOTS)
    for kind in roots:
        value = human_roots.get(kind, roots[kind])
        if not isinstance(value, str) or not value.strip():
            raise LayoutError(f"human_roots.{kind} must be a non-empty string")
        normalized = value.replace("\\", "/").strip("/")
        if normalized.startswith(".") or ":" in normalized:
            raise LayoutError(f"unsafe human root: {value}")
        if not normalized or ".." in normalized.split("/"):
            raise LayoutError(f"unsafe human root: {value}")
        roots[kind] = normalized

    metadata_root = config.get("metadata_root", DEFAULT_METADATA_ROOT)
    if not isinstance(metadata_root, str) or not metadata_root.strip():
        raise LayoutError("metadata_root must be a non-empty string")
    metadata_root = metadata_root.replace("\\", "/").strip("/")
    if metadata_root.startswith(".") or ":" in metadata_root:
        raise LayoutError(f"unsafe metadata root: {metadata_root}")
    if not metadata_root or ".." in metadata_root.split("/"):
        raise LayoutError(f"unsafe metadata root: {metadata_root}")
    if metadata_root in roots.values():
        raise LayoutError("metadata_root must differ from human roots")

    doc_refs = config.get("doc_refs", "root-relative")
    if doc_refs != "root-relative":
        raise LayoutError("flat-classified doc_refs must be root-relative")

    require_manifests = config.get("require_manifests", True)
    if not isinstance(require_manifests, bool):
        raise LayoutError("require_manifests must be a boolean")

    return {
        "name": FLAT_CLASSIFIED,
        "human_roots": roots,
        "metadata_root": metadata_root,
        "require_manifests": require_manifests,
        "doc_refs": doc_refs,
    }


def is_root_relative_path(value: str, layout: dict) -> bool:
    """Check that a path is relative to the docs root and starts in a human root."""
    normalized = value.replace("\\", "/")
    if not normalized or normalized.startswith(("/", "./")):
        return False
    parts = Path(normalized).parts
    if not parts or ".." in parts or parts[0] not in layout["human_roots"].values():
        return False
    return normalized == Path(*parts).as_posix()


def discover_manifests(docs_root: Path, layout: dict) -> List[dict]:
    """Find component and module manifests in a flat metadata root."""
    metadata_root = Path(docs_root) / layout["metadata_root"]
    manifests: List[dict] = []
    for kind, filename in _MANIFEST_FILES.items():
        kind_root = metadata_root / kind
        if not kind_root.is_dir():
            continue
        for manifest_path in sorted(kind_root.glob(f"*/{filename}")):
            manifests.append({
                "kind": kind,
                "id": manifest_path.parent.name,
                "path": manifest_path,
            })
    return manifests


def manifest_fields(path: Path) -> Dict[str, Optional[str]]:
    """Read the simple id/document scalar fields needed from a manifest."""
    fields: Dict[str, Optional[str]] = {"id": None, "document": None}
    for raw_line in Path(path).read_text(encoding="utf-8").splitlines():
        match = _SCALAR_RE.match(raw_line)
        if not match:
            continue
        key = raw_line.strip().split(":", 1)[0]
        value = match.group(1).strip()
        if value.startswith(("'", '"')) and value[-1:] == value[0]:
            value = value[1:-1]
        if key in fields and fields[key] is None:
            fields[key] = value or None
    return fields


def manifest_document_path(docs_root: Path, record: dict, layout: dict) -> tuple:
    """Return ``(document, error)`` for a discovered owner manifest."""
    path = record["path"]
    fields = manifest_fields(path)
    document = fields["document"]
    if not document:
        return None, "missing document"
    if not is_root_relative_path(document, layout):
        return None, f"document must be root-relative: {document}"
    expected_root = layout["human_roots"][record["kind"]]
    if Path(document).parts[0] != expected_root:
        return None, f"document is outside {expected_root}: {document}"
    resolved = (Path(docs_root) / document).resolve()
    docs_root = Path(docs_root).resolve()
    try:
        resolved.relative_to(docs_root)
    except ValueError:
        return None, f"document escapes documentation root: {document}"
    if resolved.suffix.lower() != ".md":
        return None, f"document must be Markdown: {document}"
    if not resolved.is_file():
        return None, f"document not found: {document}"
    return document, None


def resolve_root_relative_ref(ref: str, docs_root: Path, layout: dict) -> Optional[Path]:
    """Resolve a flat-layout ``doc_refs`` value, excluding external URLs."""
    parsed = urlsplit(ref.strip())
    if parsed.scheme or parsed.netloc:
        return None
    target = unquote(parsed.path)
    if not is_root_relative_path(target, layout):
        return None
    candidate = (Path(docs_root) / target).resolve()
    docs_root = Path(docs_root).resolve()
    try:
        candidate.relative_to(docs_root)
    except ValueError:
        return None
    return candidate
