# Routing Eval

Two layers validate the knowledge routing behavior of `knowledge_router.py`:

1. **Routing planner unit tests** (CI, `tests/test_routing_planner.py`)
2. **Real Agent Harness eval** (manual, needs a live Agent runtime — not in CI)

The layer 1 unit tests run on every CI invocation. Layer 2 requires an actual
Agent (Cursor / Codex / Claude) runtime, which CI does not provide, so it is a
documented, repeatable manual procedure only.

## Layer 1: Routing planner unit tests (CI)

The planner (`route_read_order`) decides the first-round read order for a task
request against a target repo's knowledge.

These tests are **not** self-verifying hand-built fixtures: each case in
`evals/routing/behavior-cases.json` describes a **minimal docs repository**
(`repo`), and the test runs the real `build_knowledge_map` on that repo, parses
its Markdown output back into the planner input (`_planner_state_from_map`),
and asserts the recommended read sequence.

```bash
cd h:/Repo/Illuminate
python -m pytest tests/test_routing_planner.py tests/test_knowledge_router.py -q
```

Each behavior case carries:

- `request` — the natural-language task.
- `expected_read_sequence` — the exact first-round read order (steps: `map`,
  `journey`, `module`, `component`, `metadata`, `docs`, `source`).
- `constraints` — named invariants the sequence must satisfy
  (`no_repeat_missing`, `no_full_repo_scan_first`).
- `repo` — the minimal docs tree that produces the real Map the planner sees.

The Map is generated from the standard Illuminate docs layout
(`docs/40-journeys/*.md`, `docs/70-metadata/{modules,components}/*/{module,component}.yaml`),
so a fixture repo is a compact stand-in for a real target repository.

## Layer 2: Real Agent Harness eval (manual)

This validates the planner's recommendations against a **real** Agent runtime.
CI has no Agent, so run this locally when you need end-to-end confidence.

### What it measures

Whether an Agent, given a task and a generated `knowledge-map.md`, reads the
docs in the order the planner recommends before touching source — i.e. it
consults the map, then the matching journey/module/component/metadata, and only
falls back to `docs`/`source` scanning when the map says there is nothing to
route to.

### Procedure

1. **Generate the map** for a fixture repo.

   ```bash
   python -m illuminate knowledge-map \
     --repo evals/routing/fixtures/minimal \
     --out /tmp/knowledge-map.md
   ```

   (Or reuse the repo described by any case in `behavior-cases.json` via the
   same materialization used in the layer 1 tests.)

2. **Seed a clean Agent session** pointing at the fixture repo, with the
   generated `knowledge-map.md` available at its expected location
   (`docs/knowledge-map.md`).

3. **Issue one task** from a case in `behavior-cases.json` (use its `request`),
   e.g. `"梳理 Android 后台下载完整链路"`.

4. **Record the Agent's first-round tool calls / file reads** in order.

5. **Assert** against the case's `expected_read_sequence`:

   - Step `map` → the Agent opened `knowledge-map.md` first.
   - Step `journey` → it opened `docs/40-journeys/<file>`.
   - Step `module` → it opened the matched `docs/30-modules/<file>`.
   - Step `component` → it opened the matched `docs/20-components/<file>`.
   - Step `metadata` → it queried `docs/70-metadata/`.
   - Steps `docs`/`source` → it fell back to scanning when the map had nothing.

6. **Check the constraints**:

   - `no_repeat_missing` — when no map exists, the Agent never reads a map and
     never repeats reading the same missing resource.
   - `no_full_repo_scan_first` — when a map exists, the Agent's first read is
     the map, never a whole-repo source scan.

### Reusing the fixtures

The minimal repos in `behavior-cases.json` are the canonical fixtures. To
materialize one on disk (same logic as the layer 1 tests) and generate its map,
run the layer 1 test with `--keep` or replicate `_build_repo_from_case` from
`tests/test_routing_planner.py`. The `repo` JSON under a case is the single
source of truth for both the planner unit test and the manual harness run, so
the two layers cannot drift apart.
