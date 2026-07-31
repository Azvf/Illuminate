"""Cross-adapter consistency tests.

Core invariant: every adapter (session mount, Codex sync, CodeBuddy sync)
must derive the same final skill set from the same pack + filter, because
all of them go through the single resolver
(illuminate.resolve.resolve_exposed_skills).

This is the golden contract test that prevents the adapters from drifting
apart in skill selection / alias / conflict semantics.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from illuminate.resolve import create_mount_plan
from illuminate.sync_codex import sync_codex
from illuminate.sync_codebuddy import sync_codebuddy

REPO_ROOT = Path(__file__).parent.parent
CORE_PACK = REPO_ROOT / "packs" / "core"


def _exposed_via_mount(skill_filter):
    plan = create_mount_plan(CORE_PACK, "/tmp/repo", skill_filter=skill_filter)
    return sorted(plan["skills"]["exposed"])


def _exposed_via_codex_sync(skill_filter):
    with tempfile.TemporaryDirectory() as tmp:
        result = sync_codex(CORE_PACK, Path(tmp), skill_filter=skill_filter)
        return sorted(result["exposed_skills"])


def _exposed_via_codebuddy_sync(skill_filter):
    with tempfile.TemporaryDirectory() as tmp:
        result = sync_codebuddy(CORE_PACK, Path(tmp), skill_filter=skill_filter)
        return sorted(result["exposed_skills"])


ADAPTERS = (
    _exposed_via_mount,
    _exposed_via_codex_sync,
    _exposed_via_codebuddy_sync,
)


class TestAdapterConsistency(unittest.TestCase):

    def assert_consistent(self, skill_filter=None):
        expected = _exposed_via_mount(skill_filter)
        for adapter in ADAPTERS[1:]:
            actual = adapter(skill_filter)
            self.assertEqual(
                expected, actual,
                f"{adapter.__name__} diverged from resolver",
            )

    def test_default_exposed_set_consistent(self):
        self.assert_consistent(None)

    def test_single_skill_filter_consistent(self):
        self.assert_consistent(["illuminate.layer-debug"])

    def test_alias_filter_consistent(self):
        self.assert_consistent(["illuminate.grill-me"])

    def test_conflict_raises_everywhere(self):
        for adapter in ADAPTERS:
            with self.assertRaises(ValueError) as ctx:
                adapter(["illuminate.layer-debug", "illuminate.perf-profile"])
            self.assertIn("not recommended with", str(ctx.exception))

    def test_unknown_skill_raises_everywhere(self):
        for adapter in ADAPTERS:
            with self.assertRaises(ValueError):
                adapter(["illuminate.nonexistent"])


if __name__ == "__main__":
    unittest.main()
