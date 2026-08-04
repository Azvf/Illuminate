"""Managed block merging shared by repository sync adapters.

The block is delimited by ``<!-- illuminate:begin ... -->`` and
``<!-- illuminate:end -->`` markers. ``merge_block`` replaces the content
between the markers when present, otherwise appends; ``remove_block``
strips the whole block. Adapters never touch user content outside the
markers.
"""

from pathlib import Path
from typing import List, Optional, Tuple

from .hashutil import hash_string

BEGIN_MARKER = "<!-- illuminate:begin"
END_MARKER = "<!-- illuminate:end -->"


def make_begin_marker(manifest: dict) -> str:
    """Build the opening marker, embedding pack id and version."""
    pack_id = manifest.get("id", "?")
    version = manifest.get("version", "?")
    return f"<!-- illuminate:begin\npack={pack_id}\nversion={version}\n-->"


def find_block_range(lines: List[str]) -> Optional[Tuple[int, int]]:
    """Find the first begin/end marker range.

    Returns (begin_index, end_index) or None if no complete block exists.
    """
    begin = None
    for i, line in enumerate(lines):
        if line.strip().startswith(BEGIN_MARKER):
            begin = i
        if begin is not None and line.strip() == END_MARKER:
            return (begin, i)
    return None


def find_all_block_ranges(lines: List[str]) -> List[Tuple[int, int]]:
    """Return every complete begin/end marker range, in order.

    A duplicate illuminate block must never silently fall through: callers
    that hash or remove a block must cover all of them, not just the first.
    """
    ranges: List[Tuple[int, int]] = []
    begin = None
    for i, line in enumerate(lines):
        if line.strip().startswith(BEGIN_MARKER):
            begin = i
        elif begin is not None and line.strip() == END_MARKER:
            ranges.append((begin, i))
            begin = None
    return ranges


def count_blocks(text: str) -> int:
    """Number of illuminate block begin markers in ``text``.

    Uses the same per-line match as :func:`find_block_range` so a literal
    ``BEGIN_MARKER`` substring inside a block body is not miscounted.
    """
    return sum(
        1 for line in text.split("\n") if line.strip().startswith(BEGIN_MARKER)
    )


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
    """Return text with every managed block and its markers removed."""
    lines = text.split("\n")
    ranges = find_all_block_ranges(lines)
    if not ranges:
        return text
    kept: List[str] = []
    prev_end = -1
    for begin_idx, end_idx in ranges:
        kept.extend(lines[prev_end + 1:begin_idx])
        prev_end = end_idx
    kept.extend(lines[prev_end + 1:])
    result = "\n".join(kept).strip("\n")
    return result + "\n" if result else ""


def extract_block_text(text: str) -> Optional[str]:
    """Return the full managed block(s) (markers + interior) if present, else None.

    Lets callers inspect the block in isolation from user content that may sit
    outside the markers. When multiple blocks exist, all of them are returned
    (concatenated) so hashing covers every block rather than silently dropping
    a duplicate.
    """
    lines = text.split("\n")
    ranges = find_all_block_ranges(lines)
    if not ranges:
        return None
    parts = []
    for begin_idx, end_idx in ranges:
        parts.append("\n".join(lines[begin_idx:end_idx + 1]))
    return "\n".join(parts)


def hash_block_text(text: str) -> Optional[str]:
    """Return the sha256 of the managed block in ``text``, or None if the text
    holds no complete illuminate block.

    Hashing only the block (not the whole file) lets user content outside the
    markers change freely without breaking Illuminate's ownership tracking.
    """
    block = extract_block_text(text)
    if block is None:
        return None
    return hash_string(block)
