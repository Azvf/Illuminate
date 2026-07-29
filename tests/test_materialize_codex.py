"""Tests for Codex materializer and profile generation."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from illuminate.materialize_codex import materialize_codex_session
from illuminate.lockfile import verify_lock

REPO_ROOT = Path(__file__).parent.parent
CORE_PACK = REPO_ROOT / "packs" / "core"


class TestMaterializeCodex(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        # Save and override CODEX_HOME for test isolation
        self._orig_codex_home = os.environ.get("CODEX_HOME")
        self.codex_home = Path(tempfile.mkdtemp())
        os.environ["CODEX_HOME"] = str(self.codex_home)

    def tearDown(self):
        if self._orig_codex_home:
            os.environ["CODEX_HOME"] = self._orig_codex_home
        else:
            os.environ.pop("CODEX_HOME", None)

    def test_materialize_creates_session(self):
        info = materialize_codex_session(CORE_PACK, str(self.tmpdir))
        session_dir = Path(info["session_dir"])
        self.assertTrue(session_dir.exists())
        self.assertTrue((session_dir / "mount-plan.json").exists())
        self.assertTrue((session_dir / "mount-lock.json").exists())
        self.assertIn("profile_name", info)
        self.assertIn("profile_path", info)
        self.assertIn("command", info)

    def test_skills_copied_to_agents_dir(self):
        info = materialize_codex_session(CORE_PACK, str(self.tmpdir))
        session_dir = Path(info["session_dir"])
        skills_dir = session_dir / ".agents" / "skills"
        self.assertTrue(skills_dir.exists())
        skill_dirs = [d.name for d in skills_dir.iterdir() if d.is_dir()]
        self.assertIn("layer-debug", skill_dirs)
        self.assertIn("perf-profile", skill_dirs)

    def test_alias_skills_not_copied(self):
        info = materialize_codex_session(CORE_PACK, str(self.tmpdir))
        session_dir = Path(info["session_dir"])
        skills_dir = session_dir / ".agents" / "skills"
        skill_dirs = [d.name for d in skills_dir.iterdir() if d.is_dir()]
        self.assertNotIn("grill-me", skill_dirs,
                         "Alias skill 'grill-me' should not be materialized")

    def test_policy_instructions_written(self):
        info = materialize_codex_session(CORE_PACK, str(self.tmpdir))
        session_dir = Path(info["session_dir"])
        policy_file = session_dir / "policies" / "developer-instructions.md"
        self.assertTrue(policy_file.exists())
        content = policy_file.read_text(encoding="utf-8")
        self.assertIn("Illuminate Runtime Policy", content)

    def test_codex_profile_created(self):
        info = materialize_codex_session(CORE_PACK, str(self.tmpdir))
        profile_path = Path(info["profile_path"])
        self.assertTrue(profile_path.exists())
        content = profile_path.read_text(encoding="utf-8")
        self.assertIn("developer_instructions", content)
        self.assertIn("sandbox_mode", content)
        self.assertIn("approval_policy", content)
        self.assertIn("skills.config", content)

    def test_profile_has_no_extra_skills(self):
        info = materialize_codex_session(
            CORE_PACK, str(self.tmpdir),
            skill_filter=["illuminate.layer-debug"],
        )
        profile_path = Path(info["profile_path"])
        content = profile_path.read_text(encoding="utf-8")
        self.assertIn("layer-debug", content)
        self.assertNotIn("perf-profile", content)

    def test_profile_skills_point_to_session_dir(self):
        info = materialize_codex_session(CORE_PACK, str(self.tmpdir))
        profile_path = Path(info["profile_path"])
        content = profile_path.read_text(encoding="utf-8")
        # TOML escapes backslashes, so check for session ID as a stable anchor
        session_id = info["session_id"]
        self.assertIn(session_id, content,
                      "Profile skill paths must reference the session")

    def test_profile_is_valid_toml(self):
        """Verify generated profile can be parsed as TOML (Python 3.11+)."""
        info = materialize_codex_session(CORE_PACK, str(self.tmpdir))
        profile_path = Path(info["profile_path"])
        raw = profile_path.read_text(encoding="utf-8")
        # Python 3.11+ has tomllib; for 3.8-3.10 we do basic validation
        try:
            import tomllib
            parsed = tomllib.loads(raw)
            self.assertIn("developer_instructions", parsed)
            self.assertIn("sandbox_mode", parsed)
            self.assertIn("approval_policy", parsed)
        except ImportError:
            # Fallback: check TOML-like structure with string checks
            self.assertIn('developer_instructions = "', raw)
            self.assertIn('sandbox_mode = "workspace-write"', raw)
            self.assertIn('approval_policy = "on-request"', raw)

    def test_lock_has_external_files(self):
        info = materialize_codex_session(CORE_PACK, str(self.tmpdir))
        lock = info["lock"]
        self.assertIn("external_files", lock)
        self.assertGreater(len(lock["external_files"]), 0)
        ext = lock["external_files"][0]
        self.assertEqual(ext["role"], "codex-profile")
        self.assertIn("sha256", ext)

    def test_lock_verifiable(self):
        info = materialize_codex_session(CORE_PACK, str(self.tmpdir))
        session_dir = Path(info["session_dir"])
        result = verify_lock(session_dir)
        self.assertTrue(result["valid"], f"Lock verification failed: {result}")

    def test_mount_plan_has_correct_harness(self):
        info = materialize_codex_session(CORE_PACK, str(self.tmpdir))
        plan = info["mount_plan"]
        self.assertEqual(plan["harness"], "codex")

    def test_command_structure(self):
        info = materialize_codex_session(CORE_PACK, str(self.tmpdir))
        cmd = info["command"]
        self.assertEqual(cmd[0], "codex")
        self.assertEqual(cmd[1], "--profile")
        self.assertEqual(cmd[3], "--cd")

    def test_skill_filter_only_materializes_selected(self):
        info = materialize_codex_session(
            CORE_PACK, str(self.tmpdir),
            skill_filter=["illuminate.layer-debug"],
        )
        session_dir = Path(info["session_dir"])
        skills_dir = session_dir / ".agents" / "skills"
        dirs = [d.name for d in skills_dir.iterdir() if d.is_dir()]
        self.assertIn("layer-debug", dirs)
        self.assertNotIn("perf-profile", dirs)
        self.assertNotIn("grill-me", dirs)
        self.assertNotIn("grilling", dirs)

    def test_no_repo_modification(self):
        """Verify target repository is not modified by materialization."""
        repo_copy = Path(tempfile.mkdtemp())
        content_before = sorted(
            p.relative_to(repo_copy) for p in repo_copy.rglob("*") if p.is_file()
        )
        info = materialize_codex_session(CORE_PACK, str(repo_copy))
        content_after = sorted(
            p.relative_to(repo_copy) for p in repo_copy.rglob("*") if p.is_file()
        )
        self.assertEqual(content_before, content_after,
                         "Materialization must not modify target repository")


if __name__ == "__main__":
    unittest.main()
