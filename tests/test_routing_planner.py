"""Routing planner unit tests (P1-4).

These tests exercise the first-round knowledge *read order* planner
(``illuminate.knowledge_router.route_read_order``): given a task request and a
target repo's knowledge state, the planner must recommend the correct read
sequence per the Knowledge Map "How to route" policy, and must satisfy routing
constraints (no re-reading a missing map; no whole-repo source scan before
consulting an existing map match).

Unlike the old "Agent Behavior Eval" tests, the planner input is NOT hand-built
from an invented ``knowledge_state`` with a real-Map-impossible ``keywords``
field. Instead each case describes a minimal docs repository; the test runs the
real ``build_knowledge_map`` and parses its output back into the planner input
structure. This keeps the unit tests driven by the actual Map output.

Driven by evals/routing/behavior-cases.json; each case carries a minimal
``repo``, an expected_read_sequence (exact order) and named constraints.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from illuminate.knowledge_router import build_knowledge_map, route_read_order

REPO_ROOT = Path(__file__).parent.parent
BEHAVIOR_CASES = REPO_ROOT / "evals" / "routing" / "behavior-cases.json"
SKILL_CASES = REPO_ROOT / "evals" / "routing" / "cases.json"


def _planner_state_from_map(repo: Path) -> dict:
    """Build the planner input structure from the real Knowledge Map text.

    ``build_knowledge_map`` emits a deterministic Markdown index. Parse it back
    into the ``route_read_order`` input shape, so the planner unit tests are
    driven by the true Map output rather than an invented fixture. The Map
    carries no ``keywords`` field; matching relies on journey title / module and
    component ids only.
    """
    text = build_knowledge_map(repo)
    if text is None:
        return {"has_map": False, "journeys": [], "modules": [], "components": []}

    sections: dict = {"Journeys": [], "Modules": [], "Components": []}
    section = None
    for line in text.splitlines():
        if line.startswith("## "):
            section = line[3:].strip()
            continue
        if section not in sections or not line:
            continue
        if line.startswith("- ") and not line.startswith("  "):
            sections[section].append({"_key": line[2:].strip()})
        elif line.startswith("  - Related modules:"):
            # Journey module file paths -> module ids (filename stem).
            current = sections[section][-1]
            mods = [
                Path(part.strip()).stem
                for part in line[len("  - Related modules:"):].split(",")
                if part.strip()
            ]
            current["modules"] = mods

    journeys = [
        {"title": e["_key"], "modules": e.get("modules", [])}
        for e in sections["Journeys"]
    ]
    modules = [{"id": e["_key"]} for e in sections["Modules"]]
    components = [{"id": e["_key"]} for e in sections["Components"]]
    return {
        "has_map": True,
        "journeys": journeys,
        "modules": modules,
        "components": components,
    }


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _build_repo_from_case(repo_spec: dict, root: Path) -> None:
    """Materialize a minimal docs repository described by a behavior-case."""
    for fname, content in (repo_spec.get("journeys") or {}).items():
        _write(root / "docs" / "40-journeys" / fname, content)

    for mod_id, mod in (repo_spec.get("modules") or {}).items():
        document = mod["document"]
        _write(
            root / "docs" / "70-metadata" / "modules" / mod_id / "module.yaml",
            f"id: {mod_id}\ndocument: {document}\n",
        )
        # Module body is indexed only for its section headings; sections are not
        # part of the planner input, so an empty body is sufficient.
        _write(root / "docs" / document, mod.get("body", "# M\n\n## Section\n"))

    for comp_id, comp in (repo_spec.get("components") or {}).items():
        document = comp["document"]
        _write(
            root / "docs" / "70-metadata" / "components" / comp_id / "component.yaml",
            f"id: {comp_id}\ndocument: {document}\n",
        )
        _write(root / "docs" / document, comp.get("body", "# C\n\n## Section\n"))


def _no_repeat_missing(seq, state):
    """When no map exists, never read the map, and never repeat a read attempt
    of the same (missing) resource back-to-back."""
    if not state.get("has_map") and "map" in seq:
        return False
    return all(a != b for a, b in zip(seq, seq[1:]))


def _no_full_repo_scan_first(seq, state):
    """When the map exists, the first read must be the map, not a whole-repo
    source scan."""
    if not state.get("has_map"):
        return True
    return len(seq) >= 1 and seq[0] == "map"


CONSTRAINTS = {
    "no_repeat_missing": _no_repeat_missing,
    "no_full_repo_scan_first": _no_full_repo_scan_first,
}


class TestRoutingPlanner(unittest.TestCase):

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    @classmethod
    def setUpClass(cls):
        cls.cases = json.loads(BEHAVIOR_CASES.read_text(encoding="utf-8"))

    def _route_from_case(self, case):
        repo = self.tmpdir / f"repo-{case.get('id', 'case')}"
        repo.mkdir(parents=True, exist_ok=True)
        _build_repo_from_case(case.get("repo") or {}, repo)
        state = _planner_state_from_map(repo)
        return route_read_order(case["request"], state), state

    def test_behavior_cases_are_present(self):
        self.assertGreater(len(self.cases), 0)

    def test_cases_carry_minimal_repo_not_handbuilt_state(self):
        # Guard against regression back to the invented "knowledge_state" shape:
        # every map-driven case must describe a minimal docs repo, and none may
        # hand-write a real-Map-impossible "keywords" field.
        for i, case in enumerate(self.cases):
            with self.subTest(case=case.get("id", i)):
                self.assertIn("repo", case)
                self.assertNotIn("knowledge_state", case)

    def test_recommended_read_sequence_matches_expected(self):
        for i, case in enumerate(self.cases):
            with self.subTest(case=case.get("id", i), request=case["request"]):
                seq, _ = self._route_from_case(case)
                self.assertEqual(seq, case["expected_read_sequence"])

    def test_cases_satisfy_declared_constraints(self):
        for i, case in enumerate(self.cases):
            with self.subTest(case=case.get("id", i)):
                seq, state = self._route_from_case(case)
                for constraint in case.get("constraints", []):
                    check = CONSTRAINTS.get(constraint)
                    self.assertIsNotNone(check, f"unknown constraint {constraint}")
                    self.assertTrue(
                        check(seq, state),
                        f"case {case.get('id', i)} violated {constraint}",
                    )

    def test_map_match_never_starts_with_repo_scan(self):
        # A map present with a match must route through the map, never begin
        # with a whole-repo source scan (regression guard).
        for i, case in enumerate(self.cases):
            with self.subTest(case=case.get("id", i)):
                seq, state = self._route_from_case(case)
                if not state.get("has_map"):
                    continue
                self.assertEqual(seq[0], "map")

    def test_existing_skill_routing_cases_stay_valid(self):
        # The routing planner eval must not break the existing skill-mapping
        # eval: cases.json remains loadable JSON.
        json.loads(SKILL_CASES.read_text(encoding="utf-8"))

    # ── Fix-level routing regressions (route_read_order) ──

    def test_component_is_not_shadowed_by_module_keyword(self):
        # A module keyword ("生命周期") must not shadow a specific component /
        # lifecycle request (policy rule 2: component/API/lifecycle). The state
        # is written in real-Map shape (ids only, no keywords).
        state = {
            "has_map": True,
            "journeys": [],
            "modules": [{"id": "bg-download"}],
            "components": [{"id": "BgDownloadService"}],
        }
        self.assertEqual(
            route_read_order("BgDownloadService 的生命周期是什么", state),
            ["map", "component"],
        )

    def test_journey_with_stale_module_omits_module_step(self):
        # A journey referencing a module id not present in the index must not
        # emit a step pointing at a non-existent resource.
        state = {
            "has_map": True,
            "journeys": [{"title": "后台下载完整链路", "modules": ["ghost-module"]}],
            "modules": [],
            "components": [],
        }
        self.assertEqual(
            route_read_order("后台下载完整链路", state),
            ["map", "journey"],
        )

    def test_no_map_still_routes_matched_knowledge(self):
        # Without a map, matched knowledge must still be routed (policy rules
        # 5/6) instead of short-circuiting to a repo scan. This branch cannot be
        # produced by the real Map builder (any module manifest generates a map),
        # so it is asserted directly against route_read_order.
        state = {
            "has_map": False,
            "journeys": [],
            "modules": [{"id": "bg-download"}],
            "components": [],
        }
        self.assertEqual(
            route_read_order("bg-download 模块实现细节", state),
            ["module"],
        )

    def test_verify_matches_uppercase_insensitively(self):
        # "VERIFIED"/"Evidence" in any case must trigger the verify branch.
        state = {
            "has_map": True,
            "journeys": [],
            "modules": [{"id": "bg-download"}],
            "components": [],
        }
        self.assertEqual(
            route_read_order("Is this Conclusion VERIFIED?", state),
            ["map", "module", "metadata"],
        )


if __name__ == "__main__":
    unittest.main()
