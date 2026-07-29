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

    def test_settings_has_permissions(self):
        info = materialize_session(CORE_PACK, str(self.tmpdir))
        settings_path = Path(info["session_dir"]) / "claude-settings.json"
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
        self.assertIn("permissions", settings)
        self.assertIn("deny", settings["permissions"])
        self.assertIn("allow", settings["permissions"])

    def test_lock_has_hash(self):
        info = materialize_session(CORE_PACK, str(self.tmpdir))
        lock = info["lock"]
        self.assertIn("pack_lock_hash", lock)
        self.assertTrue(lock["pack_lock_hash"].startswith("sha256:"))
        self.assertGreater(len(lock["files"]), 0)

    def test_lock_verifiable(self):
        info = materialize_session(CORE_PACK, str(self.tmpdir))
        session_dir = Path(info["session_dir"])
        self.assertTrue(verify_lock(session_dir))

    def test_mount_plan_has_session_id(self):
        info = materialize_session(CORE_PACK, str(self.tmpdir))
        plan = info["mount_plan"]
        self.assertIn("session_id", plan)
        self.assertEqual(plan["harness"], "claude-code")


if __name__ == "__main__":
    unittest.main()
