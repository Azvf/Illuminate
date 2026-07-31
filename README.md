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
- `src/illuminate/schemas/` — JSON Schemas for pack/contract/mount-plan/mount-lock (bundled with the package)
- `tests/` — Unit tests
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
| `illuminate mount create --pack <dir> --repo <path>` | Create a session mount (materialize only) |
| `illuminate mount verify <session-dir>` | Verify session mount integrity (hash + file checks) |
| `illuminate run --pack <dir> --repo <path> [--skill <id>...]` | Materialize and launch Claude Code |
| `illuminate run --pack <dir> --repo <path> --dry-run` | Materialize and print launch command without executing |
| `illuminate evidence audit --repo <path>` | Run evidence audit |
| `illuminate compat generate [--pack <dir>]` | Generate legacy compatibility dirs from canonical sources |
| `illuminate compat check [--pack <dir>]` | Check compatibility dirs match canonical sources (files + SHA-256) |
| `illuminate sync codex --repo <path> [--pack <dir>] [--skill <id>...]` | Sync pack into target repo for Codex App |
| `illuminate sync codebuddy --repo <path> [--pack <dir>] [--skill <id>...]` | Sync pack into target repo for CodeBuddy |
| `illuminate sync check --repo <path> [--harness codex\|codebuddy]` | Verify sync integrity |
| `illuminate sync clean --repo <path> [--harness codex\|codebuddy]` | Remove Illuminate-synced artifacts |
| `illuminate knowledge pull --repo <path> [--store <dir>]` | Pull project knowledge to central store |
| `illuminate knowledge status --repo <path> [--store <dir>]` | Compare project knowledge with central store |
| `illuminate knowledge push --repo <path> [--store <dir>] [--force]` | Push store documents back to project |

### Skill Selection

Use `--skill` (repeatable) to mount only specific skills:

```bash
illuminate run --pack packs/core --repo /path/to/project --skill illuminate.layer-debug
illuminate run --pack packs/core --repo /path/to/project --skill illuminate.layer-debug --skill illuminate.grilling
```

When `--skill` is omitted, all non-alias skills are exposed. Aliases are resolved to their targets.

## Session Mount

`illuminate run` creates a session under `~/.illuminate/sessions/<id>/`:

```
CLAUDE.md              # Compiled from policies
.claude/skills/        # Skill files (only exposed skills)
claude-settings.json   # Permission rules (only from exposed skills)
mount-plan.json        # What was resolved (with git identity)
mount-lock.json        # File hashes + pack lock hash + permissions scope
```

The session is immutable — Pack updates only affect new sessions. Run `illuminate mount verify <session-dir>` to check integrity.

## Permission Model

- Contract `permissions.execute` is compiled into `claude-settings.json` allow rules.
- Contract `permissions.read` and `permissions.write` are declared in the lock but **not** enforced by Claude Code.
- Only permissions from selected (`--skill`) skills contribute to the session.

## Evidence Layer

```bash
illuminate evidence audit --repo /path/to/project --pretty
```

Output: `<repo>/.illuminate/reports/evidence.json`

Reports include tool/pack/baseline metadata for traceability. Config layers:
1. Built-in defaults
2. Pack `patterns_config.json`
3. Project `.illuminate/evidence/patterns_overlay.json`

## Compatibility

To generate legacy `.claude/skills/` (for tools that expect this layout):

```bash
illuminate compat generate --pack packs/core
illuminate compat check --pack packs/core
```

## CodeBuddy Integration

Sync Illuminate Pack into a project for CodeBuddy:

```bash
illuminate sync codebuddy --pack packs/core --repo /path/to/project
```

Generates:
- `.codebuddy/rules/illuminate/` — Policy files (priority-ordered)
- `.codebuddy/skills/` — Selected skills (does not delete project-owned skills)
- `.codebuddy/commands/` — Shortcuts: `/record-knowledge`, `/archive-module-doc`, `/tidy-doc`
- `.codebuddy/CODEBUDDY.md` — Managed block (replaces only `<!-- illuminate:begin/end -->`)

Sync, verify, and clean:

```bash
illuminate sync codebuddy --repo /path/to/project --skill illuminate.record-knowledge
illuminate sync check --repo /path/to/project --harness codebuddy
illuminate sync clean --repo /path/to/project --harness codebuddy
```

Does NOT modify project-owned `.codebuddy` content. See `sync_codebuddy.py` for details.

## Knowledge Store

Pull project knowledge docs from `docs/Guidelines/` and `docs/Framework/` to a central store:

```bash
illuminate knowledge pull --repo /path/to/project
illuminate knowledge status --repo /path/to/project
illuminate knowledge push --repo /path/to/project
```
