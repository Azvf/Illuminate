"""Shared validation for classified human documents and metadata owners."""

import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple
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
_SCALAR_RE = re.compile(r"^(?P<indent>\s*)(?P<key>id|document)\s*:\s*(?P<value>.*?)\s*(?:#.*)?$")
_LIST_ITEM_RE = re.compile(r"^(?P<indent>\s*)-\s+(?P<value>.*?)\s*$")


def _strip_yaml_comment(value: str) -> str:
    quote = None
    for index, character in enumerate(value):
        if character in ("'", '"'):
            if quote == character:
                quote = None
            elif quote is None:
                quote = character
        elif character == "#" and quote is None and (
            index == 0 or value[index - 1].isspace()
        ):
            return value[:index].rstrip()
    return value.strip()


class LayoutError(ValueError):
    """Raised when a document layout profile is invalid."""


def normalize_layout(config: Optional[dict]) -> Optional[dict]:
    """Return the validated layout profile from a human-doc config."""
    config = config or {}
    name_value = config.get("layout")
    if name_value is None:
        return None
    if isinstance(name_value, dict):
        layout_config = name_value
        name = layout_config.get("name")
    else:
        layout_config = config
        name = name_value
    if name != FLAT_CLASSIFIED:
        raise LayoutError(f"unsupported documentation layout: {name_value}")

    def option(key: str, default):
        if key in layout_config:
            return layout_config[key]
        return config.get(key, default)

    human_roots = option("human_roots", DEFAULT_HUMAN_ROOTS)
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

    metadata_root = option("metadata_root", DEFAULT_METADATA_ROOT)
    if not isinstance(metadata_root, str) or not metadata_root.strip():
        raise LayoutError("metadata_root must be a non-empty string")
    metadata_root = metadata_root.replace("\\", "/").strip("/")
    if metadata_root.startswith(".") or ":" in metadata_root:
        raise LayoutError(f"unsafe metadata root: {metadata_root}")
    if not metadata_root or ".." in metadata_root.split("/"):
        raise LayoutError(f"unsafe metadata root: {metadata_root}")
    if metadata_root in roots.values():
        raise LayoutError("metadata_root must differ from human roots")

    root_parts = {kind: tuple(value.split("/")) for kind, value in roots.items()}
    for kind, parts in root_parts.items():
        for other_kind, other_parts in root_parts.items():
            if kind != other_kind and (
                parts[: len(other_parts)] == other_parts
                or other_parts[: len(parts)] == parts
            ):
                raise LayoutError("human roots must not overlap or nest")
    metadata_parts = tuple(metadata_root.split("/"))
    if any(
        metadata_parts[: len(parts)] == parts
        or parts[: len(metadata_parts)] == metadata_parts
        for parts in root_parts.values()
    ):
        raise LayoutError("metadata_root must not overlap or nest human roots")

    doc_refs = option("doc_refs", "root-relative")
    if doc_refs != "root-relative":
        raise LayoutError("flat-classified doc_refs must be root-relative")

    require_manifests = option("require_manifests", True)
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


def _unquote(value: str) -> str:
    value = value.strip()
    if value.startswith(("'", '"')) and value[-1:] == value[0]:
        return value[1:-1]
    return value


def manifest_fields(path: Path) -> Dict[str, object]:
    """Read the manifest identity, primary document, and auxiliary documents."""
    fields: Dict[str, object] = {"id": None, "document": None, "documents": []}
    in_documents = False
    documents_indent = -1
    for raw_line in Path(path).read_text(encoding="utf-8").splitlines():
        scalar = _SCALAR_RE.match(raw_line)
        if scalar:
            key = scalar.group("key")
            if fields[key] is None:
                fields[key] = _unquote(_strip_yaml_comment(scalar.group("value"))) or None
            in_documents = False
            continue

        stripped = raw_line.strip()
        documents_match = re.match(r"^documents\s*:\s*(.*?)\s*$", stripped)
        if documents_match:
            documents_indent = len(raw_line) - len(raw_line.lstrip())
            inline = _strip_yaml_comment(documents_match.group(1))
            if inline.startswith("[") and inline.endswith("]"):
                fields["documents"] = [
                    _unquote(_strip_yaml_comment(item))
                    for item in inline[1:-1].split(",")
                    if item.strip()
                ]
                in_documents = False
            else:
                fields["documents"] = []
                in_documents = True
            continue

        if in_documents:
            item = _LIST_ITEM_RE.match(raw_line)
            if item and len(item.group("indent")) > documents_indent:
                value = _unquote(_strip_yaml_comment(item.group("value")))
                if value:
                    fields["documents"].append(value)
                continue
            if stripped and len(raw_line) - len(raw_line.lstrip()) <= documents_indent:
                in_documents = False
    return fields


def manifest_document_paths(
    docs_root: Path, record: dict, layout: dict
) -> Tuple[List[str], List[str]]:
    """Return ``(owned_documents, errors)`` for one owner manifest."""
    fields = manifest_fields(record["path"])
    primary = fields["document"]
    auxiliary = fields["documents"]
    errors: List[str] = []
    manifest_id = fields["id"]
    if not manifest_id:
        errors.append("missing id")
    elif manifest_id != record["id"]:
        errors.append(
            f"id does not match entity directory {record['id']}: {manifest_id}"
        )
    if not primary:
        errors.append("missing document")
        return [], errors
    if not isinstance(auxiliary, list):
        errors.append("documents must be a list")
        auxiliary = []

    documents: List[str] = []
    for label, document in [("document", primary)] + [
        ("documents", value) for value in auxiliary
    ]:
        if not isinstance(document, str) or not document:
            errors.append(f"{label} contains an empty path")
            continue
        if not is_root_relative_path(document, layout):
            errors.append(f"{label} must be root-relative: {document}")
            continue
        expected_root = layout["human_roots"][record["kind"]]
        if Path(document).parts[0] != expected_root:
            errors.append(f"{label} is outside {expected_root}: {document}")
            continue
        resolved = (Path(docs_root) / document).resolve()
        docs_root_resolved = Path(docs_root).resolve()
        try:
            resolved.relative_to(docs_root_resolved)
        except ValueError:
            errors.append(f"{label} escapes documentation root: {document}")
            continue
        if resolved.suffix.lower() != ".md":
            errors.append(f"{label} must be Markdown: {document}")
            continue
        if not resolved.is_file():
            errors.append(f"{label} not found: {document}")
            continue
        if document in documents:
            errors.append(f"duplicate owned document: {document}")
            continue
        documents.append(document)
    return documents, errors


def manifest_document_path(docs_root: Path, record: dict, layout: dict) -> tuple:
    """Return ``(primary_document, error)`` for compatibility."""
    fields = manifest_fields(record["path"])
    documents, errors = manifest_document_paths(docs_root, record, layout)
    primary = fields["document"]
    if errors:
        return None, "; ".join(errors)
    return primary if documents else None, None


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
