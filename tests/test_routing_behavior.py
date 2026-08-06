"""Behavior-level Routing Eval (P1-4).

The existing evals/routing/cases.json only verifies request -> skill mapping.
This eval verifies the knowledge *read order*: given a task request and a
target repo's knowledge state, the router must recommend the correct
first-round read sequence per the Knowledge Map "How to route" policy, and
must satisfy routing constraints (no re-reading a missing map; no whole-repo
source scan before consulting an existing map match).

Driven by evals/routing/behavior-cases.json; each case carries an
expected_read_sequence (exact order) and named constraints.
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from illuminate.knowledge_router import route_read_order

REPO_ROOT = Path(__file__).parent.parent
BEHAVIOR_CASES = REPO_ROOT / "evals" / "routing" / "behavior-cases.json"
SKILL_CASES = REPO_ROOT / "evals" / "routing" / "cases.json"


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


class TestRoutingBehavior(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases = json.loads(BEHAVIOR_CASES.read_text(encoding="utf-8"))

    def test_behavior_cases_are_present(self):
        self.assertGreater(len(self.cases), 0)

    def test_recommended_read_sequence_matches_expected(self):
        for i, case in enumerate(self.cases):
            with self.subTest(case=case.get("id", i), request=case["request"]):
                seq = route_read_order(case["request"], case["knowledge_state"])
                self.assertEqual(seq, case["expected_read_sequence"])

    def test_cases_satisfy_declared_constraints(self):
        for i, case in enumerate(self.cases):
            with self.subTest(case=case.get("id", i)):
                seq = route_read_order(case["request"], case["knowledge_state"])
                for constraint in case.get("constraints", []):
                    check = CONSTRAINTS.get(constraint)
                    self.assertIsNotNone(check, f"unknown constraint {constraint}")
                    self.assertTrue(
                        check(seq, case["knowledge_state"]),
                        f"case {case.get('id', i)} violated {constraint}",
                    )

    def test_map_match_never_starts_with_repo_scan(self):
        # A map present with a match must route through the map, never begin
        # with a whole-repo source scan (regression guard).
        for i, case in enumerate(self.cases):
            if not case["knowledge_state"].get("has_map"):
                continue
            with self.subTest(case=case.get("id", i)):
                seq = route_read_order(case["request"], case["knowledge_state"])
                self.assertEqual(seq[0], "map")

    def test_existing_skill_routing_cases_stay_valid(self):
        # The behavior eval must not break the existing skill-mapping eval:
        # cases.json remains loadable JSON.
        json.loads(SKILL_CASES.read_text(encoding="utf-8"))

    # ── Fix-level routing regressions (route_read_order) ──

    def test_component_is_not_shadowed_by_module_keyword(self):
        # A module keyword ("生命周期") must not shadow a specific component /
        # lifecycle request (policy rule 2: component/API/lifecycle).
        state = {
            "has_map": True,
            "journeys": [],
            "modules": [
                {"id": "bg-download", "keywords": ["下载", "生命周期"]}
            ],
            "components": [
                {"id": "BgDownloadService", "keywords": ["BgDownloadService", "生命周期"]}
            ],
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
            "journeys": [
                {
                    "title": "后台下载完整链路",
                    "keywords": ["后台下载", "完整链路"],
                    "modules": ["ghost-module"],
                }
            ],
            "modules": [],
            "components": [],
        }
        self.assertEqual(
            route_read_order("后台下载完整链路", state),
            ["map", "journey"],
        )

    def test_no_map_still_routes_matched_knowledge(self):
        # Without a map, matched knowledge must still be routed (policy rules
        # 5/6) instead of short-circuiting to a repo scan.
        state = {
            "has_map": False,
            "journeys": [],
            "modules": [
                {"id": "bg-download", "keywords": ["后台下载", "实现细节"]}
            ],
            "components": [],
        }
        self.assertEqual(
            route_read_order("后台下载模块实现细节", state),
            ["module"],
        )

    def test_verify_matches_uppercase_insensitively(self):
        # "VERIFIED"/"Evidence" in any case must trigger the verify branch.
        state = {
            "has_map": True,
            "journeys": [],
            "modules": [{"id": "bg-download", "keywords": ["下载"]}],
            "components": [],
        }
        self.assertEqual(
            route_read_order("Is this Conclusion VERIFIED?", state),
            ["map", "module", "metadata"],
        )


if __name__ == "__main__":
    unittest.main()
