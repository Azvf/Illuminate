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
        # repo is now a dict with resolved path
        self.assertIn("path", plan["repo"])
        self.assertIsInstance(plan["repo"]["path"], str)
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

    def test_skill_filter_excludes_unselected_skills(self):
        plan = create_mount_plan(
            CORE_PACK, "/test/repo",
            skill_filter=["illuminate.layer-debug"],
        )
        exposed = plan["skills"]["exposed"]
        self.assertEqual(exposed, ["illuminate.layer-debug"])

        # resolve_file_list should only include layer-debug
        files = resolve_file_list(CORE_PACK, plan)
        skill_dests = [f["dest"] for f in files if ".claude/skills/" in f["dest"]]
        for d in skill_dests:
            self.assertTrue(
                d.startswith(".claude/skills/layer-debug/"),
                f"Unexpected skill file in filtered mount: {d}",
            )

    def test_unknown_skill_id_raises(self):
        with self.assertRaises(ValueError) as ctx:
            create_mount_plan(
                CORE_PACK, "/test/repo",
                skill_filter=["illuminate.nonexistent"],
            )
        self.assertIn("Unknown skill ID", str(ctx.exception))

    def test_activation_conflicting_skills_can_be_exposed(self):
        """activation_conflicts is activation-level metadata: both skills
        may still be exposed in the same mount."""
        plan = create_mount_plan(
            CORE_PACK, "/test/repo",
            skill_filter=["illuminate.layer-debug", "illuminate.perf-profile"],
        )
        exposed = plan["skills"]["exposed"]
        self.assertIn("illuminate.layer-debug", exposed)
        self.assertIn("illuminate.perf-profile", exposed)

    def test_alias_resolved_in_filter(self):
        # grill-me is an alias for grilling
        plan = create_mount_plan(
            CORE_PACK, "/test/repo",
            skill_filter=["illuminate.grill-me"],
        )
        exposed = plan["skills"]["exposed"]
        self.assertIn("illuminate.grilling", exposed)
        self.assertNotIn("illuminate.grill-me", exposed)

    def test_reference_paths_no_duplicate_directory(self):
        plan = create_mount_plan(CORE_PACK, "/test/repo")
        files = resolve_file_list(CORE_PACK, plan)
        ref_dests = [f["dest"] for f in files if "references/" in f["dest"]]
        for d in ref_dests:
            # Should not have references/references/… double nesting
            self.assertFalse(d.startswith("references/references/"),
                             f"Duplicate references/ directory: {d}")

    def test_evidence_paths_no_duplicate_directory(self):
        plan = create_mount_plan(CORE_PACK, "/test/repo")
        files = resolve_file_list(CORE_PACK, plan)
        ev_dests = [f["dest"] for f in files if "evidence/" in f["dest"]]
        for d in ev_dests:
            self.assertFalse(d.startswith("evidence/evidence/"),
                             f"Duplicate evidence/ directory: {d}")


if __name__ == "__main__":
    unittest.main()
