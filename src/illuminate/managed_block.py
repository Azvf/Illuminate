"""Managed block merging shared by repository sync adapters.

The block is delimited by ``<!-- illuminate:begin ... -->`` and
``<!-- illuminate:end -->`` markers. ``merge_block`` replaces the content
between the markers when present, otherwise appends; ``remove_block``
strips the whole block. Adapters never touch user content outside the
markers.
"""

from pathlib import Path
from typing import List, Optional, Tuple

BEGIN_MARKER = "<!-- illuminate:begin"
END_MARKER = "<!-- illuminate:end -->"


def make_begin_marker(manifest: dict) -> str:
    """Build the opening marker, embedding pack id and version."""
    pack_id = manifest.get("id", "?")
    version = manifest.get("version", "?")
    return f"<!-- illuminate:begin\npack={pack_id}\nversion={version}\n-->"


def find_block_range(lines: List[str]) -> Optional[Tuple[int, int]]:
    """Find the begin/end marker range.

    Returns (begin_index, end_index) or None if no complete block exists.
    """
    begin = None
    for i, line in enumerate(lines):
        if line.strip().startswith(BEGIN_MARKER):
            begin = i
        if begin is not None and line.strip() == END_MARKER:
            return (begin, i)
    return None


def merge_block(file_path: Path, block_text: str) -> Tuple[str, bool]:
    """Merge a managed block into a file, replacing any existing block.

    Returns (new_content, was_modified).
    """
    if file_path.exists():
        original = file_path.read_text(encoding="utf-8")
    else:
        original = ""

    if not original.strip():
        return block_text + "\n", True

    lines = original.split("\n")
    existing_range = find_block_range(lines)

    if existing_range is None:
        # Append at end with a blank line separator
        result = original.rstrip("\n") + "\n\n" + block_text + "\n"
        return result, True

    begin_idx, end_idx = existing_range
    before = "\n".join(lines[:begin_idx]).rstrip("\n")
    after = "\n".join(lines[end_idx + 1:])

    new_lines = [before, "", block_text.strip(), "", after]
    result = "\n".join(new_lines).strip("\n") + "\n"
    return result, (result != original)


def remove_block(text: str) -> str:
    """Return text with the managed block and its markers removed."""
    lines = text.split("\n")
    existing_range = find_block_range(lines)
    if existing_range is None:
        return text
    begin_idx, end_idx = existing_range
    before = "\n".join(lines[:begin_idx]).rstrip("\n")
    after = "\n".join(lines[end_idx + 1:])
    return (before + "\n" + after).strip("\n") + "\n" if (before or after) else ""
