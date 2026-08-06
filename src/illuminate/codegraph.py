"""CodeGraph CLI boundary — discovery and verification only.

Illuminate never installs, configures, or indexes CodeGraph. The external
`codegraph` CLI (machine-level install) and the per-project `.codegraph/`
index (watcher-driven incremental sync) are owned by the developer and by
CodeGraph itself. This module only probes their state for diagnostics,
mirroring `sync doctor`.
"""

import json
import shutil
import subprocess
from pathlib import Path
from typing import Dict, List


def check_codegraph(repo_root: Path, timeout: float = 10.0) -> Dict[str, object]:
    """Read-only diagnostic of a repository's CodeGraph state.

    Returns a report dict with:
      cli_available    - whether `codegraph` is on PATH
      graph_dir        - str path of `.codegraph/` when present
      graph_dir_exists - whether the project index exists
      status           - parsed `codegraph status --json` output (or None)
      status_error     - probe error text (or None)
      issues           - human-readable problems; empty when healthy

    The report never modifies the repository or the CodeGraph index.
    """
    issues: List[str] = []
    report: Dict[str, object] = {
        "cli_available": False,
        "graph_dir": None,
        "graph_dir_exists": False,
        "status": None,
        "status_error": None,
        "issues": issues,
    }

    if shutil.which("codegraph") is None:
        issues.append(
            "CodeGraph CLI not found on PATH. Install CodeGraph first "
            "(e.g. `npx @colbymchenry/codegraph` or the platform install "
            "script), then run `codegraph install` to configure supported agents"
        )
        return report
    report["cli_available"] = True

    graph_dir = repo_root / ".codegraph"
    if not graph_dir.is_dir():
        issues.append("No `.codegraph/` index in this repository — run `codegraph init` first")
        return report
    report["graph_dir"] = str(graph_dir)
    report["graph_dir_exists"] = True

    try:
        proc = subprocess.run(
            ["codegraph", "status", "--json"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
        # ValueError covers an invalid timeout value; the probe is read-only,
        # so any failure is reported instead of raised.
        report["status_error"] = str(exc)
        issues.append(f"`codegraph status` probe failed: {exc}")
        return report

    if proc.returncode != 0:
        detail = proc.stderr.strip() or f"exit code {proc.returncode}"
        report["status_error"] = detail
        issues.append(f"`codegraph status` exited {proc.returncode}: {detail}")
        return report

    try:
        parsed = json.loads(proc.stdout)
    except json.JSONDecodeError:
        report["status_error"] = "status output was not valid JSON"
        issues.append("`codegraph status --json` returned non-JSON output")
        return report
    if not isinstance(parsed, dict):
        report["status_error"] = "status output was not an object"
        issues.append("`codegraph status --json` returned a non-object value")
        return report
    report["status"] = parsed
    return report
