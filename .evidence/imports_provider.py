#!/usr/bin/env python3
"""Evidence Provider: Import / Dependency Changes

Tracks added and removed import/include statements in the working-tree diff.
Supports: Python, Kotlin/Java, C/C++, TypeScript/JavaScript, Go, Rust, Swift.

Reports facts only: which modules were added/removed. No judgment on whether
a dependency is justified.

Standalone usage:
    python .evidence/imports_provider.py [repo_root]
"""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from gitutil import get_added_lines, get_removed_lines

# ---------------------------------------------------------------------------
# Language detection by file extension
# ---------------------------------------------------------------------------

_LANG_BY_EXT = {
    ".py": "python",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".java": "java",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
    ".hpp": "cpp",
    ".hh": "cpp",
    ".rs": "rust",
    ".go": "go",
    ".swift": "swift",
}

# ---------------------------------------------------------------------------
# Import regex patterns per language
# ---------------------------------------------------------------------------

_IMPORT_PATTERNS = {
    "python": [
        re.compile(r"^\s*import\s+(\S+)"),
        re.compile(r"^\s*from\s+([\w.]+)\s+import\b"),
    ],
    "kotlin": [
        re.compile(r"^\s*import\s+([\w.]+)"),
    ],
    "java": [
        re.compile(r"^\s*import\s+(?:static\s+)?([\w.]+)"),
    ],
    "typescript": [
        re.compile(r"""^\s*import\s+.*\s+from\s+['"]([^'"]+)['"]"""),
        re.compile(r"""^\s*import\s+['"]([^'"]+)['"]"""),
        re.compile(r"""^\s*require\s*\(\s*['"]([^'"]+)['"]\s*\)"""),
        re.compile(r"""^\s*import\s*\(\s*['"]([^'"]+)['"]\s*\)"""),
    ],
    "javascript": [
        re.compile(r"""^\s*import\s+.*\s+from\s+['"]([^'"]+)['"]"""),
        re.compile(r"""^\s*import\s+['"]([^'"]+)['"]"""),
        re.compile(r"""^\s*require\s*\(\s*['"]([^'"]+)['"]\s*\)"""),
        re.compile(r"""^\s*import\s*\(\s*['"]([^'"]+)['"]\s*\)"""),
    ],
    "c": [
        re.compile(r'^\s*#include\s*[<"]([^>"]+)[>"]'),
    ],
    "cpp": [
        re.compile(r'^\s*#include\s*[<"]([^>"]+)[>"]'),
    ],
    "rust": [
        re.compile(r"^\s*use\s+([\w:]+)"),
    ],
    "go": [
        re.compile(r'^\s*import\s+"([^"]+)"'),
        # Import-block lines:  "github.com/foo/bar"
        re.compile(r'^\s*"((?:github\.com|golang\.org|gopkg\.in|gitlab\.com)/[^"]+)"'),
    ],
    "swift": [
        re.compile(r"^\s*import\s+(\w+)"),
    ],
}


def _detect_lang(file_path):
    """Return language string for a file path, or None if unsupported."""
    if not file_path:
        return None
    ext = Path(file_path).suffix.lower()
    return _LANG_BY_EXT.get(ext)


def _match_imports(lines):
    """Return list of {module, language, file, line} for matching import lines."""
    results = []

    for file_path, line_no, content in lines:
        lang = _detect_lang(file_path)
        if not lang:
            continue

        patterns = _IMPORT_PATTERNS.get(lang, [])
        for regex in patterns:
            match = regex.match(content)
            if match:
                results.append({
                    "module": match.group(1),
                    "language": lang,
                    "file": file_path,
                    "line": line_no,
                })
                break  # one match per line

    return results


def collect(repo_root):
    """Return import changes as a dict of facts."""
    repo_root = Path(repo_root)

    added = _match_imports(get_added_lines(repo_root))
    removed = _match_imports(get_removed_lines(repo_root))

    return {
        "added": added,
        "removed": removed,
        "net_change": len(added) - len(removed),
    }


if __name__ == "__main__":
    repo = sys.argv[1] if len(sys.argv) > 1 else "."
    print(json.dumps(collect(repo), indent=2, ensure_ascii=False))
