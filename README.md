# Illuminate

Git-versioned Harness Knowledge Pack + executable mount CLI for Claude Code.

## Quick Start

```bash
pip install -e .
illuminate pack validate packs/core
illuminate run --pack packs/core --repo /path/to/your/project
illuminate evidence audit --repo /path/to/project --pretty
```

## What This Is

A versioned collection of engineering policies, skills, references, and evidence tools that mount into any target project's AI coding session without copying files into the project.

## Structure

- `packs/core/` — The core knowledge pack (policies, skills, references, evidence config)
- `src/illuminate/` — CLI implementation (validate, resolve, materialize, evidence)
- `schemas/` — JSON Schemas for pack/contract/mount-plan/mount-lock
- `tests/` — 24 unit tests
- `evals/routing/` — Routing evaluation cases

## Four Knowledge Boundaries

| Boundary | Purpose |
|----------|---------|
| `policies/` | Always-active principles (compiled into CLAUDE.md) |
| `skills/` | Task-activated procedural flows (auto-discovered by Claude) |
| `references/` | On-demand knowledge (read when needed) |
| `evidence/` | Deterministic execution tools (run via CLI) |

## CLI Commands

| Command | Description |
|---------|-------------|
| `illuminate pack validate <dir>` | Validate a pack directory |
| `illuminate repo inspect --repo <path>` | Inspect a target repository |
| `illuminate mount create --pack <dir> --repo <path>` | Create a session mount |
| `illuminate run --pack <dir> --repo <path>` | Materialize + print launch command |
| `illuminate evidence audit --repo <path>` | Run evidence audit |

## Session Mount

`illuminate run` creates a session under `~/.illuminate/sessions/<id>/`:

```
CLAUDE.md              # Compiled from policies
.claude/skills/        # Copied skill files
claude-settings.json   # Permission rules
mount-plan.json        # What was resolved
mount-lock.json        # File hashes + pack lock hash
```

The session is immutable — Pack updates only affect new sessions.

## Evidence Layer

```bash
illuminate evidence audit --repo /path/to/project --pretty
```

Output: `<repo>/.illuminate/reports/evidence.json`

Reports include tool/pack/baseline metadata for traceability. Config layers:
1. Built-in defaults
2. Pack `patterns_config.json`
3. Project `.illuminate/evidence/patterns_overlay.json`
