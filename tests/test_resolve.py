"""Tests for mount plan resolution."""

import json
import sys
import unittest
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from illuminate.resolve import create_mount_plan, resolve_file_list

REPO_ROOT = Path(__file__).parent.parent
CORE_PACK = REPO_ROOT / "packs" / "core"


class TestResolve(unittest.TestCase):

    def test_create_mount_plan(self):
        plan = create_mount_plan(CORE_PACK, "/test/repo", "claude-code")
        self.assertEqual(plan["schema_version"], 1)
        self.assertEqual(plan["repo"], "/test/repo")
        self.assertEqual(plan["harness"], "claude-code")
        self.assertEqual(len(plan["packs"]), 1)
        self.assertEqual(plan["packs"][0]["id"], "illuminate.core")
        self.assertGreater(len(plan["policies"]), 0)
        self.assertIn("exposed", plan["skills"])
        self.assertGreater(len(plan["skills"]["exposed"]), 0)

    def test_exposed_skills_exclude_aliases(self):
        plan = create_mount_plan(CORE_PACK, "/test/repo")
        exposed = plan["skills"]["exposed"]
        self.assertNotIn("illuminate.grill-me", exposed)
        self.assertIn("illuminate.grilling", exposed)

    def test_session_id_is_uuid(self):
        plan = create_mount_plan(CORE_PACK, "/test/repo")
        uuid.UUID(plan["session_id"])

    def test_resolve_file_list_nonempty(self):
        plan = create_mount_plan(CORE_PACK, "/test/repo")
        files = resolve_file_list(CORE_PACK, plan)
        self.assertGreater(len(files), 0)

    def test_resolve_includes_skill_files(self):
        plan = create_mount_plan(CORE_PACK, "/test/repo")
        files = resolve_file_list(CORE_PACK, plan)
        dests = [f["dest"] for f in files]
        has_skill = any(".claude/skills/" in d for d in dests)
        self.assertTrue(has_skill, "File list should include skill files")

    def test_resolve_includes_policy_files(self):
        plan = create_mount_plan(CORE_PACK, "/test/repo")
        files = resolve_file_list(CORE_PACK, plan)
        dests = [f["dest"] for f in files]
        has_policy = any("policies/" in d for d in dests)
        self.assertTrue(has_policy, "File list should include policy files")


if __name__ == "__main__":
    unittest.main()
