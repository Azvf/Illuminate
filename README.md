# Illuminate

Git-versioned Harness Knowledge Pack + executable mount CLI for Claude Code.

## Quick Start

```bash
pip install -e .
illuminate pack validate packs/core
    illuminate run --pack packs/core --repo /path/to/your/project
    illuminate evidence audit --repo /path/to/project --pretty
    illuminate docs export-human --source /path/to/docs --output /path/to/human-docs --config /path/to/docs/human-docs.json
    illuminate docs lint-human --source /path/to/docs --config /path/to/docs/human-docs.json
```

## What This Is

A versioned collection of engineering policies, skills, references, and evidence tools that mount into any target project's AI coding session without copying files into the project.

## Human Documentation Export

Keep human-readable Markdown as the source truth and store claims, evidence, and test metadata separately. Place an optional `human-docs.json` beside the documentation root:

```json
{
  "layout": "flat-classified",
  "human_roots": {
    "components": "20-components",
    "modules": "30-modules",
    "journeys": "40-journeys"
  },
  "metadata_root": "70-metadata",
  "require_manifests": true,
  "doc_refs": "root-relative",
  "include": [
    "README-HUMAN.md",
    "20-components/*.md",
    "30-modules/*.md",
    "40-journeys/*.md"
  ],
  "exclude": [
    "70-metadata/**",
    "80-evidence/**",
    "90-generated/**",
    "99-archive/**"
  ],
  "readme": "README-HUMAN.md"
}
```

`docs export-human` only copies selected Markdown and maps `README-HUMAN.md` to the export root `README.md`; it does not parse or rewrite正文. Run `docs lint-human` separately after cleaning the source Markdown.

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
| `illuminate docs export-human --source <dir> --output <dir> [--config <json>]` | Copy configured human-readable Markdown without rewriting content |
| `illuminate docs lint-human --source <dir> [--config <json>] [--all-markdown]` | Check human Markdown rules and local links |
| `illuminate compat generate [--pack <dir>]` | Generate legacy compatibility dirs from canonical sources |
| `illuminate compat check [--pack <dir>]` | Check compatibility dirs match canonical sources (files + SHA-256) |
| `illuminate sync codex --repo <path> [--pack <dir>] [--skill <id>...]` | Sync pack into target repo for Codex App |
| `illuminate sync codebuddy --repo <path> [--pack <dir>] [--skill <id>...]` | Sync pack into target repo for CodeBuddy |
| `illuminate sync cursor --repo <path> [--pack <dir>] [--skill <id>...] [--agents-compat]` | Sync pack into target repo for Cursor |
| `illuminate sync check --repo <path> [--pack <dir>] [--harness codex\|codebuddy\|cursor]` | Verify sync integrity |
| `illuminate sync clean --repo <path> [--harness codex\|codebuddy\|cursor]` | Remove Illuminate-synced artifacts |
| `illuminate sync doctor --repo <path> --harness cursor` | Read-only Cursor sync diagnostics (exit 0 = healthy, 1 = issues) |
| `illuminate knowledge pull --repo <path> [--store <dir>] [--manifest <json>]` | Pull configured project knowledge to central store |
| `illuminate knowledge status --repo <path> [--store <dir>] [--manifest <json>]` | Compare configured project knowledge with central store |
| `illuminate knowledge push --repo <path> [--store <dir>] [--manifest <json>] [--force]` | Push store documents back to project safely |
| `illuminate knowledge candidate --repo <path> --source <path> --target <kind> [--anchor <ref>] [--notes <text>] [--store <dir>]` | Create a promotion candidate from a knowledge source with provenance |
| `illuminate knowledge review --repo <path> --id <id> [--reviewer <name>] [--notes <text>] [--store <dir>]` | Move a candidate from `raw` to `reviewed` |
| `illuminate knowledge promote --repo <path> --id <id> --pack <dir> [--target-path <path>] [--content <file>] [--dry-run] [--force] [--store <dir>]` | Promote a reviewed candidate into the Harness Pack (generalized via `--content`) |
| `illuminate knowledge reject --repo <path> --id <id> [--reviewer <name>] [--superseded] [--notes <text>] [--store <dir>]` | Reject a `raw`/`reviewed` candidate or mark a promoted one `superseded` |
| `illuminate docs lint-knowledge --source <dir> [--config <json>]` | Validate Manifest owners, metadata IDs, and YAML `doc_refs` |

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
- `.codebuddy/commands/` — Shortcuts: `/record-knowledge`, `/archive-module-doc`, `/tidy-doc` (skill-bound, synced when the skill is exposed), and `/finish-task`, `/knowledge-status`, `/propose-knowledge` (standalone, always synced)
- `.codebuddy/CODEBUDDY.md` — Managed block (replaces only `<!-- illuminate:begin/end -->`)

Sync, verify, and clean:

```bash
illuminate sync codebuddy --repo /path/to/project --skill illuminate.record-knowledge
illuminate sync check --repo /path/to/project --harness codebuddy
illuminate sync clean --repo /path/to/project --harness codebuddy
```

Does NOT modify project-owned `.codebuddy` content. See `sync_codebuddy.py` for details.

## Cursor Integration

Sync Illuminate Pack into a project for Cursor:

```bash
illuminate sync cursor --pack packs/core --repo /path/to/project
```

Generates (default mode):
- `.cursor/rules/illuminate/core.mdc` — Policy files and Synchronized skills list
- `.cursor/skills/` — Selected skills (does not delete project-owned skills)
- `.cursor/commands/` — Shortcuts (beta): `/record-knowledge`, `/archive-module-doc`, `/tidy-doc` (skill-bound, synced when the skill is exposed), and `/finish-task`, `/knowledge-status`, `/propose-knowledge` (standalone, always synced)
- `.illuminate/cursor-lock.json` — Sync manifest with hashes (pack, skills, commands, `rules_md_hash`)

Cursor does NOT modify the root `AGENTS.md` by default. Pass `--agents-compat` to keep the legacy behavior of merging an Illuminate managed block into the root `AGENTS.md` (shared with the Codex CLI); the lock records the `agents_compat` flag and uses `agents_md_hash` accordingly, and `check`/`clean` follow the same path.

Sync, verify, diagnose, and clean:

```bash
illuminate sync cursor --repo /path/to/project --skill illuminate.record-knowledge
illuminate sync check --repo /path/to/project --harness cursor
illuminate sync doctor --repo /path/to/project --harness cursor
illuminate sync clean --repo /path/to/project --harness cursor
```

`sync doctor` is read-only Cursor diagnostics: exit code 0 means healthy, 1 means issues were found (cursor harness only). Does NOT modify project-owned `.cursor` content, and does not generate `.cursor/cli.json` or `.agents/skills`. Skills are copied verbatim — SKILL.md bodies are not rewritten for Cursor. See `sync_cursor.py` for details.

## Knowledge Store

Knowledge Store is a local backup and recovery tool. Add an optional `knowledge-manifest.json` at the repository root when the project uses the `flat-classified` layout; its roots and patterns are relative to `docs/`:

```json
{
  "roots": ["20-components", "30-modules", "40-journeys", "70-metadata", "README-HUMAN.md", "human-docs.json"],
  "include": ["**/*"],
  "exclude": ["80-evidence/**", "90-generated/**", "99-archive/**", "dist/**"]
}
```

`70-metadata` keeps Manifest identity and verification YAML separate from human Markdown documents. Without a manifest, the legacy default roots `Guidelines` and `Framework` remain supported. The store keeps documents and a hash baseline under `~/.illuminate/knowledge`; Git remains responsible for history, branches, and collaboration.

```bash
illuminate knowledge pull --repo /path/to/project --manifest /path/to/project/knowledge-manifest.json
illuminate knowledge status --repo /path/to/project --manifest /path/to/project/knowledge-manifest.json
illuminate knowledge push --repo /path/to/project --manifest /path/to/project/knowledge-manifest.json
illuminate docs lint-knowledge --source /path/to/project/docs
```

Pull keeps the previous three-way baseline for conflicts and deletions. Push refuses to overwrite a project file that changed since the last baseline unless `--force` is supplied.

### Knowledge Promotion Bridge

Knowledge Promotion Bridge is a thin bridge between the Store (backup tool) and the Harness Pack (Git-versioned, reviewed general knowledge). The Store still only handles backup/diff/conflict/restore; it does not perform cross-project generalization or publishing.

Promotion state follows `raw → reviewed → promoted`, with `raw`/`reviewed → rejected` and `promoted → superseded`. The registry lives at `<store>/projects/<project-id>/promotions.json` (beside `knowledge-lock.json`), with content snapshots stored under `promotions/<id>/source.md` (creation) and `promotions/<id>/draft.md` (generalized review).

The four commands:
- `candidate` captures a source document with provenance (git remote, commit, docs-relative path, anchor) and snapshots its exact bytes to `promotions/<id>/source.md` (`source_sha256`). The candidate id is derived from `commit + repo + path + anchor + target + source_sha256`, so the same source can be promoted to different targets, and changed content (even uncommitted, or in a non-git project) yields a new candidate for a v1 → v2 → supersede cycle.
- `review` marks a candidate `reviewed` and pins `reviewed_sha256` to the hash of the exact bytes under review. By default those are the source snapshot; with `--content <file>` the bytes under review are a generalized draft, which is snapshotted to `promotions/<id>/draft.md` and bound as the reviewed content (the candidate is marked `generalized`).
- `promote` writes content into a Harness Pack (`<pack>/policies|skills|references|evidence/`) and registers it in the pack manifest. It only consumes already-reviewed bytes — the draft snapshot for a `generalized` candidate, otherwise the current source document — and is guarded by `reviewed_sha256`: anything that does not hash to the value recorded at review is rejected ("refusing to promote unreviewed bytes"), so a source edit after review fails promotion. This closes the draft-review loop: `raw → review --content draft → promote` promotes exactly the reviewed draft.
- `reject` marks a `raw`/`reviewed` candidate `rejected`; with `--superseded` it marks a `promoted` candidate `superseded`.

Manifest registration per target:
- `reference` — appended to `pack.json.references`.
- `policy` — appended to `policies/index.json` (priority 0, lowest).
- `skill` — writes `skills/<name>/SKILL.md` + a minimal `contract.json` and registers in `pack.json.skills`. The source must itself be a valid SKILL.md with `name:`/`description:` frontmatter: `validate_pack` rejects any skill whose `SKILL.md` lacks them, so a promoted skill is guaranteed discoverable by Cursor.
- `evidence` — sets `pack.json.evidence.config`.

After writing, `promote` runs `validate_pack`; if validation fails the whole change (files + manifest + index) is rolled back. `--target-path` is narrowed to the target's directory (`references/`, `policies/`, `skills/`, `evidence/`) and cannot target governance/index files (`pack.json`, `*.schema.json`, `index.json`) even with `--force`. An existing pack file is only overwritten with `--force`; `--dry-run` writes nothing.

Promotion does not stage or commit. `promote` only writes into the Pack working tree; commits and PRs are left to Git and humans.

```bash
illuminate knowledge candidate --repo /path/to/project --source 30-modules/hot-update.md --target reference
illuminate knowledge review --repo /path/to/project --id <candidate-id> --reviewer alice
illuminate knowledge review --repo /path/to/project --id <candidate-id> --content generalized.md
illuminate knowledge promote --repo /path/to/project --id <candidate-id> --pack packs/core
illuminate knowledge reject --repo /path/to/project --id <candidate-id>
```
