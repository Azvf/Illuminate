"""Human-readable Markdown linting kept separate from export copying."""

import re
from pathlib import Path
from typing import Iterable, List, Optional
from urllib.parse import urlsplit

from .docs_export import _collect_files, _is_within, load_config

DEFAULT_BANNED_TERMS = (
    "CL-",
    "EV-",
    "GAP-",
    "TR-",
    "haveRev",
    "headChange",
    "SHA256",
    "legacy_id",
    "PENDING_BINDING",
    "LINT OK",
    "Phase 1",
    "Phase 2",
    "P0",
    "P1",
    "subagent",
)
DEFAULT_FORBIDDEN_PATHS = (
    "verification",
    "80-evidence",
    "90-generated",
    "99-archive",
)
DEFAULT_MODULE_SECTIONS = (
    "模块定位与边界",
    "主流程",
    "参与组件",
    "失败",
    "恢复",
    "模块交接",
    "日志",
    "当前限制",
)
_LINK_RE = re.compile(r"(?<!！)(?<!\!)\[([^\]]+)\]\(([^)]+)\)")


def _local_path(raw_target: str) -> Optional[str]:
    target = raw_target.strip()
    if target.startswith("<") and ">" in target:
        target = target[1:target.index(">")]
    else:
        target = target.split()[0] if target else ""
    parsed = urlsplit(target)
    if parsed.scheme or parsed.netloc or target.startswith("#"):
        return None
    return parsed.path


def _selected_files(root: Path, config_path: Optional[Path], all_markdown: bool) -> List[Path]:
    if all_markdown:
        return sorted(root.rglob("*.md"))
    config = load_config(config_path)
    selected = _collect_files(root, config["include"], config["exclude"])
    readme = config.get("readme")
    if readme:
        readme_path = (root / readme).resolve()
        if readme_path.is_file():
            selected.add(readme_path)
    return sorted(selected, key=lambda path: path.relative_to(root).as_posix())


def lint_human(
    root: Path,
    config_path: Optional[Path] = None,
    all_markdown: bool = False,
    banned_terms: Iterable[str] = DEFAULT_BANNED_TERMS,
    forbidden_paths: Iterable[str] = DEFAULT_FORBIDDEN_PATHS,
    required_module_sections: Iterable[str] = DEFAULT_MODULE_SECTIONS,
) -> List[str]:
    """Return human-document lint errors; an empty list means clean."""
    root = Path(root).resolve()
    if not root.is_dir():
        return [f"root directory not found: {root}"]

    files = _selected_files(root, config_path, all_markdown)
    if not files:
        return ["no Markdown files selected"]
    selected = set(files)
    errors: List[str] = []
    banned = tuple(banned_terms)
    forbidden = tuple(forbidden_paths)

    for path in files:
        relative = path.relative_to(root).as_posix()
        text = path.read_text(encoding="utf-8")
        for term in banned:
            if term in text:
                errors.append(f"{relative}: forbidden human-doc term: {term}")

        guide_has_module_link = False

        def check_link(match: re.Match) -> str:
            nonlocal guide_has_module_link
            raw_target = match.group(2)
            local_path = _local_path(raw_target)
            if local_path is None:
                return match.group(0)
            target = (path.parent / local_path).resolve() if local_path else path
            if not _is_within(target, root):
                errors.append(f"{relative}: link escapes documentation root: {raw_target}")
                return match.group(0)
            target_relative = target.relative_to(root).as_posix()
            if any(
                part in forbidden
                for part in Path(target_relative).parts
            ):
                errors.append(f"{relative}: link points to excluded material: {raw_target}")
            if not target.exists():
                errors.append(f"{relative}: broken local link: {raw_target}")
            elif target.suffix.lower() == ".md" and target not in selected and not all_markdown:
                errors.append(f"{relative}: Markdown link is outside export selection: {raw_target}")
            if (
                target.exists()
                and target.suffix.lower() == ".md"
                and target.name == "README.md"
                and target_relative.startswith("30-modules/")
            ):
                guide_has_module_link = True
            return match.group(0)

        _LINK_RE.sub(check_link, text)

        relative_parts = Path(relative).parts
        if (
            len(relative_parts) >= 3
            and relative_parts[0] == "30-modules"
            and path.name == "README.md"
        ):
            headings = text.lower()
            for section in required_module_sections:
                if section.lower() not in headings:
                    errors.append(f"{relative}: missing required section: {section}")

        if (
            relative.startswith("40-journeys/")
            and path.name != "README.md"
            and not guide_has_module_link
        ):
            errors.append(f"{relative}: guide must link to an existing module README")

    return errors


def format_lint_errors(errors: List[str]) -> str:
    if not errors:
        return "Human documentation lint: PASS"
    lines = [f"Human documentation lint: FAIL ({len(errors)} issue(s))"]
    lines.extend(f"  - {error}" for error in errors)
    return "\n".join(lines)
