"""Generic lint for machine-side knowledge metadata and doc references."""

import re
from pathlib import Path
from typing import Dict, Iterable, List, Optional
from urllib.parse import unquote, urlsplit

from .document_layout import (
    discover_manifests,
    is_root_relative_path,
    manifest_document_paths,
    normalize_layout,
    resolve_root_relative_ref,
)
from .docs_export import _is_within, load_config
from .docs_lint import (
    _ANCHOR_ID_RE,
    _document_anchors,
    _explicit_anchor_ids,
    _explicit_anchor_issues,
)

_METADATA_FILES = ("claims.yaml", "gaps.yaml", "tests.yaml")
_ID_INLINE_RE = re.compile(r"^\s*-\s+id:\s*([^\s#]+)")
_DOC_RE = re.compile(r"^(?P<indent>\s*)-\s+(?P<value>.+?)\s*$")


def _strip_yaml_comment(value: str) -> str:
    quote = None
    escaped = False
    for index, character in enumerate(value):
        if character in ("'", '"') and not escaped:
            if quote == character:
                quote = None
            elif quote is None:
                quote = character
        elif character == "#" and quote is None and (
            index == 0 or value[index - 1].isspace()
        ):
            return value[:index].rstrip()
        escaped = character == "\\" and not escaped
        if character != "\\":
            escaped = False
    return value.strip()


def _strip_yaml_value(value: str) -> str:
    value = _strip_yaml_comment(value).strip()
    if value.startswith(("'", '"')) and value[-1:] == value[0]:
        return value[1:-1]
    return value


def _split_top_level(value: str, separator: str = ",") -> List[str]:
    parts: List[str] = []
    start = 0
    depth = 0
    quote = None
    escaped = False
    for index, character in enumerate(value):
        if character in ("'", '"') and not escaped:
            if quote == character:
                quote = None
            elif quote is None:
                quote = character
        elif quote is None and character in "[{":
            depth += 1
        elif quote is None and character in "]}":
            depth = max(0, depth - 1)
        elif quote is None and character == separator and depth == 0:
            parts.append(value[start:index].strip())
            start = index + 1
        escaped = character == "\\" and not escaped
        if character != "\\":
            escaped = False
    parts.append(value[start:].strip())
    return [part for part in parts if part]


def _parse_mapping(value: str) -> dict:
    value = _strip_yaml_comment(value).strip()
    if value.startswith("{") and value.endswith("}"):
        value = value[1:-1]
    result = {}
    for field in _split_top_level(value):
        if ":" not in field:
            continue
        key, field_value = field.split(":", 1)
        result[_strip_yaml_value(key)] = _strip_yaml_value(field_value)
    return result


def _flush_doc_ref(refs: List[dict], current: Optional[dict]) -> None:
    if current is not None:
        refs.append(current)


def _parse_ref_item(value: str) -> dict:
    value = _strip_yaml_comment(value).strip()
    if value.startswith("{") and value.endswith("}"):
        mapping = _parse_mapping(value)
        return {"ref": mapping.get("ref"), "role": mapping.get("role")}
    if re.match(r"^(?:ref|role)\s*:", value):
        mapping = _parse_mapping(value)
        return {"ref": mapping.get("ref"), "role": mapping.get("role")}
    return {"ref": _strip_yaml_value(value), "role": "primary"}


def _metadata_entries(path: Path):
    """Read scalar and ``{ref, role}`` doc_refs without a YAML dependency."""
    current_id: Optional[str] = None
    in_doc_refs = False
    doc_refs_indent = -1
    doc_refs: List[dict] = []
    current_ref: Optional[dict] = None

    def finish_ref() -> None:
        nonlocal current_ref
        _flush_doc_ref(doc_refs, current_ref)
        current_ref = None

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        inline = _ID_INLINE_RE.match(line)
        if inline:
            finish_ref()
            if current_id is not None:
                yield current_id, list(doc_refs)
            current_id = _strip_yaml_value(inline.group(1))
            doc_refs = []
            in_doc_refs = False
            continue
        if current_id is None:
            continue

        doc_match = re.match(r"^(?P<indent>\s*)doc_refs\s*:\s*(.*?)\s*$", line)
        if doc_match:
            finish_ref()
            doc_refs_indent = len(doc_match.group("indent"))
            inline_refs = _strip_yaml_comment(doc_match.group(2))
            if inline_refs.startswith("[") and inline_refs.endswith("]"):
                doc_refs.extend(
                    _parse_ref_item(item)
                    for item in _split_top_level(inline_refs[1:-1])
                )
                in_doc_refs = False
            else:
                in_doc_refs = True
            continue

        if not in_doc_refs:
            continue
        item = _DOC_RE.match(line)
        if item and len(item.group("indent")) > doc_refs_indent:
            finish_ref()
            current_ref = _parse_ref_item(item.group("value"))
            continue
        field = re.match(r"^\s*(ref|role)\s*:\s*(.*?)\s*$", line)
        if field and current_ref is not None:
            current_ref[field.group(1)] = _strip_yaml_value(field.group(2))
            continue
        if len(line) - len(line.lstrip()) <= doc_refs_indent:
            finish_ref()
            in_doc_refs = False
        else:
            finish_ref()
            in_doc_refs = False

    finish_ref()
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


def _flat_owner_data(docs_root: Path, layout: dict):
    errors: List[str] = []
    owners: Dict[str, Path] = {}
    manifest_documents: Dict[Path, List[str]] = {}
    manifests = discover_manifests(docs_root, layout)
    for record in manifests:
        manifest_path = record["path"]
        try:
            documents, manifest_errors = manifest_document_paths(docs_root, record, layout)
        except OSError as exc:
            errors.append(f"{manifest_path.relative_to(docs_root)}: cannot read manifest: {exc}")
            continue
        for error in manifest_errors:
            errors.append(f"{manifest_path.relative_to(docs_root)}: {error}")
        manifest_documents[manifest_path] = documents
        for document in documents:
            if document in owners:
                errors.append(
                    f"{manifest_path.relative_to(docs_root)}: duplicate document owner {document} "
                    f"(first in {owners[document].relative_to(docs_root)})"
                )
            else:
                owners[document] = manifest_path

    if layout["require_manifests"]:
        for kind in ("components", "modules"):
            human_root = docs_root / layout["human_roots"][kind]
            if not human_root.is_dir():
                continue
            for document_path in sorted(human_root.rglob("*.md")):
                if document_path.name == "README.md":
                    continue
                document = document_path.relative_to(docs_root).as_posix()
                if document not in owners:
                    errors.append(f"{document}: orphan human document without Manifest.document")
    return errors, owners, manifest_documents


def _lint_flat_owners(docs_root: Path, layout: dict) -> List[str]:
    return _flat_owner_data(docs_root, layout)[0]


def _manifest_for_metadata(metadata_path: Path, manifest_documents: Dict[Path, List[str]]) -> Optional[Path]:
    candidates = [
        manifest_path
        for manifest_path in manifest_documents
        if _is_within(metadata_path.resolve(), manifest_path.parent.resolve())
    ]
    return max(candidates, key=lambda path: len(path.parts)) if candidates else None


def _lint_explicit_anchors(
    docs_root: Path, layout: dict, configured_readme: Optional[str] = None
) -> List[str]:
    errors: List[str] = []
    seen: Dict[str, Path] = {}
    paths = set()
    for root_name in layout["human_roots"].values():
        human_root = docs_root / root_name
        if human_root.is_dir():
            paths.update(human_root.rglob("*.md"))
    if configured_readme:
        readme = (docs_root / configured_readme).resolve()
        if _is_within(readme, docs_root) and readme.is_file():
            paths.add(readme)
    for path in sorted(paths):
        relative = path.relative_to(docs_root).as_posix()
        text = path.read_text(encoding="utf-8")
        errors.extend(f"{relative}: {issue}" for issue in _explicit_anchor_issues(text))
        for anchor_id in _explicit_anchor_ids(text):
            if not _ANCHOR_ID_RE.fullmatch(anchor_id):
                continue
            if anchor_id in seen:
                errors.append(
                    f"{relative}: duplicate explicit anchor id {anchor_id} "
                    f"(first in {seen[anchor_id].relative_to(docs_root)})"
                )
            else:
                seen[anchor_id] = path
    return errors


def lint_knowledge(docs_root: Path, config_path: Optional[Path] = None) -> List[str]:
    """Validate metadata IDs, structured doc_refs, anchors, and flat owners."""
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
    owners: Dict[str, Path] = {}
    manifest_documents: Dict[Path, List[str]] = {}
    if layout:
        owner_errors, owners, manifest_documents = _flat_owner_data(docs_root, layout)
        errors.extend(owner_errors)
        errors.extend(_lint_explicit_anchors(docs_root, layout, config.get("readme")))

    seen_ids: Dict[str, Path] = {}
    metadata_files = [
        path for path in sorted(docs_root.rglob("*.yaml"))
        if path.name in _METADATA_FILES
    ]
    for metadata_path in metadata_files:
        manifest_path = _manifest_for_metadata(metadata_path, manifest_documents)
        for item_id, refs in _metadata_entries(metadata_path):
            relative_metadata = metadata_path.relative_to(docs_root)
            if item_id in seen_ids:
                errors.append(
                    f"{relative_metadata}: duplicate id {item_id} "
                    f"(first in {seen_ids[item_id].relative_to(docs_root)})"
                )
            else:
                seen_ids[item_id] = metadata_path
            if not refs:
                errors.append(f"{relative_metadata}: {item_id} has no doc_refs")
                continue

            primary_count = 0
            for ref_entry in refs:
                if not isinstance(ref_entry, dict):
                    errors.append(f"{relative_metadata}: {item_id} has invalid doc_ref entry")
                    continue
                ref = ref_entry.get("ref")
                role = ref_entry.get("role")
                if not isinstance(ref, str) or not ref.strip():
                    errors.append(f"{relative_metadata}: {item_id} doc_ref is missing ref")
                    continue
                if role not in ("primary", "context"):
                    errors.append(
                        f"{relative_metadata}: {item_id} doc_ref role must be primary or context"
                    )
                    continue
                if role == "primary":
                    primary_count += 1

                parsed = urlsplit(ref.strip())
                target_path = unquote(parsed.path)
                if layout and not is_root_relative_path(target_path, layout):
                    errors.append(
                        f"{relative_metadata}: {item_id} doc_ref must be root-relative: {ref}"
                    )
                    continue
                resolved = _resolve_doc_ref(metadata_path, ref, docs_root, layout)
                if resolved is None or not resolved.is_file():
                    errors.append(f"{relative_metadata}: {item_id} has invalid doc_ref: {ref}")
                    continue
                if resolved.suffix.lower() != ".md":
                    errors.append(
                        f"{relative_metadata}: {item_id} doc_ref must target Markdown: {ref}"
                    )
                    continue
                target_relative = resolved.relative_to(docs_root).as_posix()
                if role == "primary" and manifest_path is not None:
                    allowed = manifest_documents.get(manifest_path, [])
                    if target_relative not in allowed:
                        errors.append(
                            f"{relative_metadata}: {item_id} primary doc_ref is not owned by "
                            f"{manifest_path.relative_to(docs_root)}: {ref}"
                        )
                fragment = unquote(parsed.fragment)
                if fragment and fragment not in _document_anchors(
                    resolved.read_text(encoding="utf-8")
                ):
                    errors.append(
                        f"{relative_metadata}: {item_id} has missing heading anchor: {ref}"
                    )

            if primary_count == 0:
                errors.append(f"{relative_metadata}: {item_id} must have exactly one primary doc_ref")
            elif primary_count > 1:
                errors.append(
                    f"{relative_metadata}: {item_id} must have exactly one primary doc_ref"
                )

    return errors


def format_knowledge_lint_errors(errors: List[str]) -> str:
    if not errors:
        return "Knowledge documentation lint: PASS"
    lines = [f"Knowledge documentation lint: FAIL ({len(errors)} issue(s))"]
    lines.extend(f"  - {error}" for error in errors)
    return "\n".join(lines)
