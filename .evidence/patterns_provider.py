#!/usr/bin/env python3
"""Evidence Provider: Pattern Detection

Scans added lines in the working-tree diff for naming patterns that may
indicate abstraction growth, feature flags, or fallback paths.

Detection is heuristic and language-agnostic. It reports *facts*
(matched lines, keywords, locations) — never judgments about whether
a pattern is justified.

Configuration is loaded in three layers (later merges over earlier):

  1. Built-in defaults (hardcoded below, always present)
  2. .evidence/patterns_config.json   — tool defaults, ships with Illuminate
  3. .evidence/patterns_overlay.json  — user customizations, project-specific

Lists are merged via union (deduped, order preserved).
Dicts are merged recursively. Scalars are overwritten.

This means the overlay file only needs to contain *new* entries — it
does not need to duplicate the defaults.

Standalone usage:
    python .evidence/patterns_provider.py [repo_root]
"""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from gitutil import get_added_lines


# ---------------------------------------------------------------------------
# Built-in defaults (always available as fallback)
# ---------------------------------------------------------------------------

_DEFAULT_CONFIG = {
    "abstraction_keywords": [
        "Factory", "Adapter", "Wrapper", "Registry",
        "Manager", "Provider", "Bridge", "Converter",
        "Proxy", "Decorator", "Strategy", "Handler",
        "Controller", "Builder", "Pipeline", "Chain",
        "Compat", "Legacy", "Retry", "Fallback",
    ],
    "definition_keywords": [
        "class", "struct", "interface", "trait",
        "enum", "object", "protocol", "extension",
    ],
    "feature_flag_patterns": [
        r"#if(?:def|ndef)?\b",
        r"#elif\b",
        r"feature_?flag",
        r"enable_?feature",
        r"is_?feature_?enabled",
        r"use_?new",
        r"use_?legacy",
        r"enable_?new",
        r"disable_?new",
        r"\bENABLE_",
        r"\bDISABLE_",
        r"getenv\s*\(",
        r"os\.environ",
        r"System\.getenv",
        r"ProcessInfo",
        r"\bFeatureFlag\b",
    ],
    "fallback_patterns": {
        "catch_keywords": ["catch", "except"],
        "null_coalesce_chain": r"\?\?.*\?\?",
    },
}


# ---------------------------------------------------------------------------
# Config loading and merging
# ---------------------------------------------------------------------------

def _load_json(path):
    """Load a JSON file. Returns None on error (warning to stderr)."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except OSError:
        return None
    except json.JSONDecodeError as e:
        print(f"Warning: invalid JSON in {path}: {e}", file=sys.stderr)
        return None


def _merge(base, overlay):
    """Deep-merge overlay into base.

    - Lists: union, deduped, base order preserved then overlay appended.
    - Dicts: recursive merge.
    - Scalars: overlay wins.
    - None in overlay: removes the key (opt-out).
    """
    if isinstance(base, list) and isinstance(overlay, list):
        seen = set()
        merged = []
        for item in base + overlay:
            key = json.dumps(item, sort_keys=True) if isinstance(item, (list, dict)) else item
            if key not in seen:
                seen.add(key)
                merged.append(item)
        return merged

    if isinstance(base, dict) and isinstance(overlay, dict):
        result = dict(base)
        for key, val in overlay.items():
            if val is None:
                result.pop(key, None)  # opt-out
            elif key in result:
                result[key] = _merge(result[key], val)
            else:
                result[key] = val
        return result

    # Scalar or type mismatch: overlay wins
    return overlay


def _load_config(repo_root):
    """Load pattern configuration with overlay support.

    Returns a tuple: (config, sources) where sources lists which files
    were actually loaded (for traceability in the evidence report).
    """
    import copy

    config = copy.deepcopy(_DEFAULT_CONFIG)
    sources = ["built-in defaults"]

    evidence_dir = Path(repo_root) / ".evidence"

    # Layer 2: tool defaults (patterns_config.json)
    config_path = evidence_dir / "patterns_config.json"
    loaded = _load_json(config_path)
    if loaded:
        config = _merge(config, loaded)
        sources.append(str(config_path))

    # Layer 3: user overlay (patterns_overlay.json)
    overlay_path = evidence_dir / "patterns_overlay.json"
    loaded = _load_json(overlay_path)
    if loaded:
        config = _merge(config, loaded)
        sources.append(str(overlay_path))

    return config, sources


# ---------------------------------------------------------------------------
# Compiled regex builders (rebuild from config each run)
# ---------------------------------------------------------------------------

def _build_definition_regex(config):
    """Build the type-definition regex from config keywords."""
    keywords = config["definition_keywords"]
    if not keywords:
        # Fallback so detection never breaks
        keywords = _DEFAULT_CONFIG["definition_keywords"]
    return re.compile(
        r"\b(?:data\s+)?(?:" + "|".join(keywords) + r")\b\s+(\w+)",
        re.IGNORECASE,
    )


def _build_feature_flag_regexes(config):
    """Compile feature-flag patterns from config."""
    patterns = config["feature_flag_patterns"]
    if not patterns:
        patterns = _DEFAULT_CONFIG["feature_flag_patterns"]
    return [re.compile(p, re.IGNORECASE) for p in patterns]


def _build_fallback_regexes(config):
    """Compile fallback-path regexes from config."""
    fb = config.get("fallback_patterns", {})

    catch_kw = fb.get("catch_keywords", ["catch", "except"])
    catch_re = re.compile(
        r"\b(?:" + "|".join(catch_kw) + r")\b",
        re.IGNORECASE,
    )

    null_coalesce_re = None
    nc_pattern = fb.get("null_coalesce_chain")
    if nc_pattern:
        null_coalesce_re = re.compile(nc_pattern)

    return catch_re, null_coalesce_re


# ---------------------------------------------------------------------------
# Detection functions
# ---------------------------------------------------------------------------

def _detect_abstractions(added_lines, config, definition_re):
    """Detect new type definitions whose names contain abstraction keywords."""
    keywords = config["abstraction_keywords"]
    results = []
    seen_names = set()

    for file_path, line_no, content in added_lines:
        stripped = content.strip()
        def_match = definition_re.search(stripped)
        if not def_match:
            continue

        name = def_match.group(1)
        for keyword in keywords:
            if keyword.lower() in name.lower():
                key = (name, file_path)
                if key in seen_names:
                    break
                seen_names.add(key)
                results.append({
                    "name": name,
                    "keyword": keyword,
                    "file": file_path,
                    "line": line_no,
                    "line_content": stripped,
                })
                break

    return results


def _detect_feature_flags(added_lines, regexes):
    """Detect lines that look like feature-flag usage."""
    results = []

    for file_path, line_no, content in added_lines:
        stripped = content.strip()
        # Skip comment-only lines to reduce noise
        if stripped.startswith("//"):
            continue
        if stripped.startswith("#") and not stripped.startswith("#if"):
            # Keep preprocessor #ifdef, skip #include etc.
            continue

        for regex in regexes:
            if regex.search(stripped):
                results.append({
                    "pattern": regex.pattern,
                    "file": file_path,
                    "line": line_no,
                    "line_content": stripped,
                })
                break

    return results


def _detect_fallback_paths(added_lines, catch_re, null_coalesce_re):
    """Detect new catch/except blocks and null-coalescing chains."""
    results = []

    for file_path, line_no, content in added_lines:
        stripped = content.strip()

        if catch_re.search(stripped):
            results.append({
                "type": "catch_block",
                "file": file_path,
                "line": line_no,
                "line_content": stripped,
            })
        elif null_coalesce_re and null_coalesce_re.search(stripped):
            results.append({
                "type": "null_coalesce_chain",
                "file": file_path,
                "line": line_no,
                "line_content": stripped,
            })

    return results


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def collect(repo_root):
    """Return pattern-detection results as a dict of facts."""
    repo_root = Path(repo_root)

    config, sources = _load_config(repo_root)
    added_lines = get_added_lines(repo_root)

    definition_re = _build_definition_regex(config)
    feature_flag_res = _build_feature_flag_regexes(config)
    catch_re, null_coalesce_re = _build_fallback_regexes(config)

    return {
        "new_abstractions": _detect_abstractions(added_lines, config, definition_re),
        "new_feature_flags": _detect_feature_flags(added_lines, feature_flag_res),
        "new_fallback_paths": _detect_fallback_paths(added_lines, catch_re, null_coalesce_re),
        "_config": {
            "sources": sources,
            "abstraction_keywords": config["abstraction_keywords"],
            "definition_keywords": config["definition_keywords"],
            "feature_flag_pattern_count": len(config["feature_flag_patterns"]),
            "fallback_patterns": config.get("fallback_patterns", {}),
        },
    }


if __name__ == "__main__":
    repo = sys.argv[1] if len(sys.argv) > 1 else "."
    print(json.dumps(collect(repo), indent=2, ensure_ascii=False))
