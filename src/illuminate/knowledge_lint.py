"""Generic lint for machine-side knowledge metadata and doc references."""

import re
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set
from urllib.parse import unquote, urlsplit

from .docs_lint import _is_within, _heading_anchors

_METADATA_FILES = ("claims.yaml", "gaps.yaml", "tests.yaml")
_ID_RE = re.compile(r"^\s*-\s+id:\s*(\S+)\s*$")
_DOC_RE = re.compile(r"^\s+-\s+(.+?)\s*$")
_ID_INLINE_RE = re.compile(r"^\s*-\s+id:\s*([^\s#]+)")


def _strip_yaml_value(value: str) -> str:
    value = value.strip()
    if value.startswith(("'", '"')) and value[-1:] == value[0]:
        return value[1:-1]
    return value


def _metadata_entries(path: Path):
    """Read the small YAML subset needed for id/doc_refs without PyYAML."""
    current_id: Optional[str] = None
    in_doc_refs = False
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.rstrip()
        inline = _ID_INLINE_RE.match(line)
        if inline:
            if current_id is not None:
                yield current_id, list(doc_refs)
            current_id = _strip_yaml_value(inline.group(1))
            doc_refs: List[str] = []
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


def _resolve_doc_ref(metadata_path: Path, ref: str, docs_root: Path) -> Optional[Path]:
    target = ref.strip()
    parsed = urlsplit(target)
    if parsed.scheme or parsed.netloc:
        return None
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


def lint_knowledge(docs_root: Path) -> List[str]:
    """Validate metadata IDs and doc_refs for a documentation root."""
    docs_root = Path(docs_root).resolve()
    if not docs_root.is_dir():
        return [f"documentation root not found: {docs_root}"]

    errors: List[str] = []
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
                resolved = _resolve_doc_ref(metadata_path, ref, docs_root)
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
