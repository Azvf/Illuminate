"""Tests for Claude Code materializer."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from illuminate.materialize_claude import materialize_session
from illuminate.lockfile import verify_lock

REPO_ROOT = Path(__file__).parent.parent
CORE_PACK = REPO_ROOT / "packs" / "core"


class TestMaterializeClaude(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def test_materialize_creates_session(self):
        info = materialize_session(CORE_PACK, str(self.tmpdir))
        session_dir = Path(info["session_dir"])
        self.assertTrue(session_dir.exists())
        self.assertTrue((session_dir / "CLAUDE.md").exists())
        self.assertTrue((session_dir / "mount-plan.json").exists())
        self.assertTrue((session_dir / "mount-lock.json").exists())
        self.assertTrue((session_dir / "claude-settings.json").exists())

    def test_claude_md_contains_policies(self):
        info = materialize_session(CORE_PACK, str(self.tmpdir))
        claude_md = Path(info["session_dir"]) / "CLAUDE.md"
        content = claude_md.read_text(encoding="utf-8")
        self.assertIn("Evidence First", content)
        self.assertIn("Root Cause First", content)
        self.assertIn("Occam Engineering", content)

    def test_skills_copied(self):
        info = materialize_session(CORE_PACK, str(self.tmpdir))
        session_dir = Path(info["session_dir"])
        skills_dir = session_dir / ".claude" / "skills"
        self.assertTrue(skills_dir.exists())
        skill_dirs = [d.name for d in skills_dir.iterdir() if d.is_dir()]
        self.assertIn("layer-debug", skill_dirs)
        self.assertIn("perf-profile", skill_dirs)

    def test_alias_skills_not_copied(self):
        """Alias skills (e.g. grill-me) must not appear in the session."""
        info = materialize_session(CORE_PACK, str(self.tmpdir))
        session_dir = Path(info["session_dir"])
        skills_dir = session_dir / ".claude" / "skills"
        skill_dirs = [d.name for d in skills_dir.iterdir() if d.is_dir()]
        self.assertNotIn("grill-me", skill_dirs,
                         "Alias skill 'grill-me' should not be materialized")

    def test_skill_filter_only_materializes_selected(self):
        info = materialize_session(
            CORE_PACK, str(self.tmpdir),
            skill_filter=["illuminate.layer-debug"],
        )
        session_dir = Path(info["session_dir"])
        plan_path = session_dir / "mount-plan.json"
        plan = json.loads(plan_path.read_text(encoding="utf-8"))

        # Plan declares only layer-debug
        self.assertEqual(plan["skills"]["exposed"], ["illuminate.layer-debug"])

        # Actual filesystem matches plan
        skills_dir = session_dir / ".claude" / "skills"
        dirs = [d.name for d in skills_dir.iterdir() if d.is_dir()]
        self.assertIn("layer-debug", dirs)
        self.assertNotIn("perf-profile", dirs)
        self.assertNotIn("grill-me", dirs)
        self.assertNotIn("grilling", dirs)

    def test_settings_has_permissions(self):
        info = materialize_session(CORE_PACK, str(self.tmpdir))
        settings_path = Path(info["session_dir"]) / "claude-settings.json"
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
        self.assertIn("permissions", settings)
        self.assertIn("deny", settings["permissions"])
        self.assertIn("allow", settings["permissions"])

    def test_permissions_only_from_exposed_skills(self):
        """Only expose layer-debug; settings must not include permissions
        from perf-profile or other unexposed skills."""
        info = materialize_session(
            CORE_PACK, str(self.tmpdir),
            skill_filter=["illuminate.layer-debug"],
        )
        settings_path = Path(info["session_dir"]) / "claude-settings.json"
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
        allow = settings["permissions"]["allow"]
        allow_str = " ".join(allow)

        # layer-debug allows scripts/test/**
        self.assertIn("scripts/test/**", allow_str,
                      "Exposed skill permissions should be present")

        # perf-profile has no execute permissions, so this is a no-op check.
        # But simplify-code has grep/rg - ensure they're absent.
        self.assertNotIn("Bash(grep:*)", allow_str,
                         "Unexposed skill permissions must not be present")

    def test_lock_has_hash(self):
        info = materialize_session(CORE_PACK, str(self.tmpdir))
        lock = info["lock"]
        self.assertIn("pack_lock_hash", lock)
        self.assertTrue(lock["pack_lock_hash"].startswith("sha256:"))
        self.assertGreater(len(lock["files"]), 0)

    def test_lock_contains_declared_permissions(self):
        """Lock file should record declared and enforced permissions separately."""
        info = materialize_session(CORE_PACK, str(self.tmpdir))
        lock = info["lock"]
        self.assertIn("declared_permissions", lock)
        self.assertIn("enforced_permissions", lock)
        self.assertIn("enforcement_status", lock)
        self.assertIn("exposed_skills", lock)
        dp = lock["declared_permissions"]
        self.assertIn("read", dp)
        self.assertIn("write", dp)
        self.assertIn("execute", dp)

    def test_lock_verifiable(self):
        info = materialize_session(CORE_PACK, str(self.tmpdir))
        session_dir = Path(info["session_dir"])
        result = verify_lock(session_dir)
        self.assertTrue(result["valid"], f"Lock verification failed: {result}")

    def test_mount_plan_has_session_id(self):
        info = materialize_session(CORE_PACK, str(self.tmpdir))
        plan = info["mount_plan"]
        self.assertIn("session_id", plan)
        self.assertEqual(plan["harness"], "claude-code")

    def test_mount_plan_repo_has_git_info(self):
        """When materializing from a real repo (self), repo info includes git metadata."""
        info = materialize_session(CORE_PACK, str(REPO_ROOT))
        plan = info["mount_plan"]
        repo_info = plan["repo"]
        self.assertIn("path", repo_info)
        self.assertEqual(repo_info["path"], str(REPO_ROOT.resolve()))


if __name__ == "__main__":
    unittest.main()
