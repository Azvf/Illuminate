"""Tests for CodeBuddy sync (illuminate sync codebuddy)."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from illuminate.sync_codebuddy import (
    sync_codebuddy,
    check_sync,
    clean_sync,
    _BEGIN_MARKER,
    _END_MARKER,
)

REPO_ROOT = Path(__file__).parent.parent
CORE_PACK = REPO_ROOT / "packs" / "core"


class TestSyncCodeBuddy(unittest.TestCase):

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def _make_repo(self) -> Path:
        repo = self.tmpdir / "target-repo"
        repo.mkdir(parents=True, exist_ok=True)
        return repo

    def test_sync_creates_codebuddy_md_block(self):
        repo = self._make_repo()
        result = sync_codebuddy(CORE_PACK, repo)

        cb_path = repo / ".codebuddy" / "CODEBUDDY.md"
        self.assertTrue(cb_path.exists())
        content = cb_path.read_text(encoding="utf-8")
        self.assertIn(_BEGIN_MARKER, content)
        self.assertIn("Illuminate Integration", content)
        self.assertIn(_END_MARKER, content)

    def test_sync_creates_rules(self):
        repo = self._make_repo()
        result = sync_codebuddy(CORE_PACK, repo)

        rules_dir = repo / ".codebuddy" / "rules" / "illuminate"
        self.assertTrue(rules_dir.exists())
        # Should have at least one policy file
        md_files = list(rules_dir.glob("*.md"))
        self.assertGreater(len(md_files), 0)
        # Files should be priority-ordered (00-*, 10-*, ...)
        self.assertTrue(any(f.name.startswith("00-") for f in md_files))

    def test_sync_creates_skills(self):
        repo = self._make_repo()
        result = sync_codebuddy(CORE_PACK, repo)

        skills_dir = repo / ".codebuddy" / "skills"
        self.assertTrue(skills_dir.exists())
        self.assertTrue((skills_dir / "layer-debug" / "SKILL.md").exists())
        self.assertTrue((skills_dir / "record-knowledge" / "SKILL.md").exists())

    def test_sync_does_not_include_alias_skills(self):
        repo = self._make_repo()
        result = sync_codebuddy(CORE_PACK, repo)

        skills_dir = repo / ".codebuddy" / "skills"
        skill_dirs = [d.name for d in skills_dir.iterdir() if d.is_dir()]
        self.assertNotIn("grill-me", skill_dirs,
                         "Alias skills should not be synced")

    def test_sync_with_filter(self):
        repo = self._make_repo()
        result = sync_codebuddy(CORE_PACK, repo, skill_filter=["illuminate.layer-debug"])

        skills_dir = repo / ".codebuddy" / "skills"
        dirs = [d.name for d in skills_dir.iterdir() if d.is_dir()]
        self.assertIn("layer-debug", dirs)
        self.assertNotIn("perf-profile", dirs)

    def test_sync_creates_commands(self):
        repo = self._make_repo()
        result = sync_codebuddy(CORE_PACK, repo)

        commands_dir = repo / ".codebuddy" / "commands"
        self.assertTrue(commands_dir.exists())
        cmd_files = list(commands_dir.glob("*.md"))
        self.assertGreater(len(cmd_files), 0)

    def test_sync_commands_match_exposed_skills(self):
        repo = self._make_repo()
        result = sync_codebuddy(CORE_PACK, repo, skill_filter=["illuminate.record-knowledge"])

        commands_dir = repo / ".codebuddy" / "commands"
        self.assertTrue((commands_dir / "record-knowledge.md").exists())
        self.assertFalse((commands_dir / "archive-module-doc.md").exists())

    def test_sync_creates_lock(self):
        repo = self._make_repo()
        result = sync_codebuddy(CORE_PACK, repo)

        lock_path = repo / ".illuminate" / "codebuddy-lock.json"
        self.assertTrue(lock_path.exists())
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
        self.assertIn("exposed_skills", lock)
        self.assertIn("rules", lock)
        self.assertIn("skills", lock)
        self.assertIn("commands", lock)
        self.assertIn("codebuddy_md_hash", lock)

    def test_sync_does_not_modify_existing_user_content(self):
        repo = self._make_repo()
        cb_path = repo / ".codebuddy" / "CODEBUDDY.md"
        cb_path.parent.mkdir(parents=True, exist_ok=True)
        cb_path.write_text("# My Project\n\nCustom rules here.\n", encoding="utf-8")

        sync_codebuddy(CORE_PACK, repo)

        content = cb_path.read_text(encoding="utf-8")
        self.assertIn("# My Project", content)
        self.assertIn("Custom rules here.", content)
        self.assertIn("Illuminate Integration", content)

    def test_sync_does_not_delete_project_skills(self):
        repo = self._make_repo()
        # Create a project-owned skill
        proj_skill = repo / ".codebuddy" / "skills" / "project-custom" / "SKILL.md"
        proj_skill.parent.mkdir(parents=True, exist_ok=True)
        proj_skill.write_text("# Custom Skill\n", encoding="utf-8")

        sync_codebuddy(CORE_PACK, repo)

        self.assertTrue(proj_skill.exists(),
                        "Project-owned skills should survive sync")

    def test_check_passes_after_sync(self):
        repo = self._make_repo()
        sync_codebuddy(CORE_PACK, repo)
        ok, issues = check_sync(CORE_PACK, repo)
        self.assertTrue(ok, f"Check should pass: {issues}")

    def test_check_fails_without_sync(self):
        repo = self._make_repo()
        ok, issues = check_sync(CORE_PACK, repo)
        self.assertFalse(ok)

    def test_check_detects_missing_rule(self):
        repo = self._make_repo()
        sync_codebuddy(CORE_PACK, repo)
        rule = repo / ".codebuddy" / "rules" / "illuminate" / "00-evidence-first.md"
        rule.unlink()
        ok, issues = check_sync(CORE_PACK, repo)
        self.assertFalse(ok)

    def test_clean_removes_managed_artifacts(self):
        repo = self._make_repo()
        sync_codebuddy(CORE_PACK, repo)

        result = clean_sync(repo)
        self.assertIn("removed_artifacts", result)
        self.assertFalse((repo / ".codebuddy" / "rules" / "illuminate").exists())
        self.assertFalse((repo / ".illuminate" / "codebuddy-lock.json").exists())

    def test_clean_does_not_remove_project_content(self):
        repo = self._make_repo()
        # Create project-owned content outside managed paths
        proj_rule = repo / ".codebuddy" / "rules" / "project-rule.md"
        proj_rule.parent.mkdir(parents=True, exist_ok=True)
        proj_rule.write_text("# Project Rule\n", encoding="utf-8")

        sync_codebuddy(CORE_PACK, repo)
        clean_sync(repo)

        # Project-owned rule outside illuminate/ should survive
        self.assertTrue(proj_rule.exists())

    def test_clean_on_unsynced_repo(self):
        repo = self._make_repo()
        repo.joinpath("CODEBUDDY.md").write_text("# Clean\n", encoding="utf-8")
        result = clean_sync(repo)
        content = (repo / "CODEBUDDY.md").read_text(encoding="utf-8")
        self.assertEqual(content.strip(), "# Clean")


if __name__ == "__main__":
    unittest.main()
