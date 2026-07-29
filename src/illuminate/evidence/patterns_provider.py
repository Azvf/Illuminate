#!/usr/bin/env python3
"""Evidence Provider: Pattern Detection

Scans added lines in the working-tree diff for naming patterns that may
indicate abstraction growth, feature flags, or fallback paths.

Detection is heuristic and language-agnostic. It reports *facts*
(matched lines, keywords, locations) — never judgments about whether
a pattern is justified.

Configuration is loaded in three layers (later merges over earlier):

  1. Built-in defaults (hardcoded below, always present)
  2. Pack config (patterns_config.json, ships with Illuminate)
  3. Project overlay (.illuminate/evidence/patterns_overlay.json in target repo)

Lists are merged via union (deduped, order preserved).
Dicts are merged recursively. Scalars are overwritten.
"""

import json
import re
import sys
from pathlib import Path

from .gitutil import get_added_lines


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


def _load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except OSError:
        return None
    except json.JSONDecodeError as e:
        print(f"Warning: invalid JSON in {path}: {e}", file=sys.stderr)
        return None


def _merge(base, overlay):
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
                result.pop(key, None)
            elif key in result:
                result[key] = _merge(result[key], val)
            else:
                result[key] = val
        return result

    return overlay


def _load_config(repo_root):
    """Load pattern configuration with pack defaults and project overlay.

    Returns a tuple: (config, sources) where sources lists which files
    were actually loaded (for traceability in the evidence report).

    Config layers:
      1. Built-in _DEFAULT_CONFIG
      2. Pack config: <package_dir>/patterns_config.json (ships with Illuminate)
      3. Project overlay: <repo>/.illuminate/evidence/patterns_overlay.json
    """
    import copy

    config = copy.deepcopy(_DEFAULT_CONFIG)
    sources = ["built-in defaults"]

    # Layer 2: pack config (ships with Illuminate, next to this file)
    pack_config = Path(__file__).resolve().parent / "patterns_config.json"
    loaded = _load_json(pack_config)
    if loaded:
        config = _merge(config, loaded)
        sources.append(str(pack_config))

    # Layer 3: project overlay (in target repo)
    project_overlay = Path(repo_root) / ".illuminate" / "evidence" / "patterns_overlay.json"
    loaded = _load_json(project_overlay)
    if loaded:
        config = _merge(config, loaded)
        sources.append(str(project_overlay))

    return config, sources


def _build_definition_regex(config):
    keywords = config["definition_keywords"]
    if not keywords:
        keywords = _DEFAULT_CONFIG["definition_keywords"]
    return re.compile(
        r"\b(?:data\s+)?(?:" + "|".join(keywords) + r")\b\s+(\w+)",
        re.IGNORECASE,
    )


def _build_feature_flag_regexes(config):
    patterns = config["feature_flag_patterns"]
    if not patterns:
        patterns = _DEFAULT_CONFIG["feature_flag_patterns"]
    return [re.compile(p, re.IGNORECASE) for p in patterns]


def _build_fallback_regexes(config):
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


def _detect_abstractions(added_lines, config, definition_re):
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
    results = []

    for file_path, line_no, content in added_lines:
        stripped = content.strip()
        if stripped.startswith("//"):
            continue
        if stripped.startswith("#") and not stripped.startswith("#if"):
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


def collect(repo_root):
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
