"""Configuration-driven export of human-readable Markdown documents.

The source Markdown is the human-facing truth. This module deliberately does
not parse, rewrite, merge, or interpret Markdown; it only selects files from
a manifest and copies them while preserving their relative paths.
"""

import json
import re
import shutil
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set

from .document_layout import LayoutError, normalize_layout

DEFAULT_INCLUDE = (
    "README-HUMAN.md",
    "20-components/**/*.md",
    "30-modules/**/*.md",
    "40-journeys/**/*.md",
)
DEFAULT_EXCLUDE = (
    "**/verification/**",
    "80-evidence/**",
    "90-generated/**",
    "99-archive/**",
)
DEFAULT_README = "README-HUMAN.md"


class DocsExportError(ValueError):
    """Raised when a human-document export cannot be created safely."""


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _validate_patterns(patterns: Iterable[str], field: str) -> List[str]:
    result = []
    for pattern in patterns:
        if not isinstance(pattern, str) or not pattern.strip():
            raise DocsExportError(f"{field} patterns must be non-empty strings")
        normalized = pattern.replace("\\", "/")
        if normalized.startswith("/") or ".." in normalized.split("/"):
            raise DocsExportError(f"unsafe {field} pattern: {pattern}")
        result.append(normalized)
    return result


def _validate_readme_config(readme: Optional[str]) -> Optional[str]:
    if readme is None:
        return None
    normalized = readme.replace("\\", "/")
    if (
        not normalized
        or normalized.startswith("/")
        or re.match(r"^[A-Za-z]:/", normalized)
        or ".." in normalized.split("/")
    ):
        raise DocsExportError(f"unsafe readme path: {readme}")
    return normalized


def load_config(config_path: Optional[Path]) -> Dict[str, object]:
    """Load and validate a JSON human-doc export configuration."""
    if config_path is None:
        return {
            "include": list(DEFAULT_INCLUDE),
            "exclude": list(DEFAULT_EXCLUDE),
            "readme": DEFAULT_README,
        }
    try:
        with Path(config_path).open("r", encoding="utf-8") as stream:
            config = json.load(stream)
    except (OSError, json.JSONDecodeError) as exc:
        raise DocsExportError(f"cannot read config: {config_path}: {exc}") from exc
    if not isinstance(config, dict):
        raise DocsExportError("human-docs config must be a JSON object")

    include = config.get("include", DEFAULT_INCLUDE)
    exclude = config.get("exclude", DEFAULT_EXCLUDE)
    readme = config.get("readme", DEFAULT_README)
    if not isinstance(include, list) or not include:
        raise DocsExportError("config.include must be a non-empty array")
    if not isinstance(exclude, list):
        raise DocsExportError("config.exclude must be an array")
    if readme is not None and not isinstance(readme, str):
        raise DocsExportError("config.readme must be a string or null")
    try:
        layout = normalize_layout(config)
    except LayoutError as exc:
        raise DocsExportError(str(exc)) from exc
    return {
        "include": _validate_patterns(include, "include"),
        "exclude": _validate_patterns(exclude, "exclude"),
        "readme": _validate_readme_config(readme),
        "layout": layout,
    }


def _matches(relative: Path, patterns: Iterable[str]) -> bool:
    value = relative.as_posix()
    return any(fnmatchcase(value, pattern) for pattern in patterns)


def _collect_files(source_root: Path, include: Iterable[str], exclude: Iterable[str]) -> Set[Path]:
    selected: Set[Path] = set()
    for pattern in include:
        for candidate in source_root.glob(pattern):
            if not candidate.is_file() or candidate.suffix.lower() != ".md":
                continue
            resolved = candidate.resolve()
            if not _is_within(resolved, source_root):
                raise DocsExportError(f"include pattern escaped source root: {pattern}")
            relative = resolved.relative_to(source_root)
            if not _matches(relative, exclude):
                selected.add(resolved)
    return selected


def _readme_source(source_root: Path, configured_readme: Optional[str]) -> Optional[Path]:
    if configured_readme is None:
        return None
    candidate = (source_root / configured_readme).resolve()
    if not _is_within(candidate, source_root) or not candidate.is_file():
        raise DocsExportError(f"human readme not found: {configured_readme}")
    if candidate.suffix.lower() != ".md":
        raise DocsExportError(f"human readme must be Markdown: {configured_readme}")
    return candidate


def export_human(
    source_root: Path,
    output_root: Path,
    config_path: Optional[Path] = None,
    force: bool = False,
) -> Dict[str, object]:
    """Copy the configured human-document files without changing content.

    ``config_path`` is optional for library callers; the CLI resolves the
    conventional ``<source>/human-docs.json`` location before calling here.
    """
    source_root = Path(source_root).resolve()
    output_root = Path(output_root).resolve()
    if not source_root.is_dir():
        raise DocsExportError(f"source directory not found: {source_root}")
    if _is_within(output_root, source_root):
        raise DocsExportError("output directory must not be inside source directory")
    replace_output = False
    if output_root.exists():
        if not output_root.is_dir():
            raise DocsExportError(f"output path is not a directory: {output_root}")
        replace_output = any(output_root.iterdir())
        if replace_output and not force:
            raise DocsExportError(
                f"output directory is not empty: {output_root} (use --force to replace it)"
            )

    # Build and validate the complete copy plan before replacing an existing
    # output. A bad config or destination collision must not destroy a valid
    # previous export, even with --force.
    config = load_config(config_path)
    include = _validate_patterns(config["include"], "include")
    exclude = _validate_patterns(config["exclude"], "exclude")
    selected = _collect_files(source_root, include, exclude)
    readme = _readme_source(source_root, config.get("readme"))
    if readme is not None:
        selected.add(readme)
    if not selected:
        raise DocsExportError("configuration selected no Markdown files")

    copy_plan = []
    destinations: Dict[Path, Path] = {}
    for source_path in sorted(selected, key=lambda p: p.relative_to(source_root).as_posix()):
        relative = source_path.relative_to(source_root)
        destination_relative = Path("README.md") if readme == source_path else relative
        if destination_relative in destinations and destinations[destination_relative] != source_path:
            previous = destinations[destination_relative].relative_to(source_root)
            raise DocsExportError(
                f"multiple source files map to {destination_relative}: "
                f"{previous} and {relative}"
            )
        destinations[destination_relative] = source_path
        copy_plan.append((source_path, destination_relative))

    if replace_output:
        shutil.rmtree(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    copied: List[str] = []
    for source_path, destination_relative in copy_plan:
        destination = output_root / destination_relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, destination)
        copied.append(destination_relative.as_posix())

    return {
        "source": str(source_root),
        "output": str(output_root),
        "config": str(config_path.resolve()) if config_path else None,
        "files": copied,
        "file_count": len(copied),
    }
