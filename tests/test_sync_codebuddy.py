"""Tests for CodeBuddy sync (illuminate sync codebuddy)."""

import json
import os
import stat
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
CORE_PACK = Path(__file__).parent.parent / "src" / "illuminate" / "builtin_pack"


def _set_readonly(path: Path) -> None:
    """Make a file read-only on both Windows (attribute) and POSIX (mode)."""
    os.chmod(path, stat.S_IREAD | stat.S_IRGRP | stat.S_IROTH)


def _make_writable(path: Path) -> None:
    """Restore write permission so tempdir cleanup does not fail."""
    os.chmod(path, stat.S_IWRITE | stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)


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
        # The exposed skill's command exists.
        self.assertTrue((commands_dir / "record-knowledge.md").exists())
        # Skills that are not exposed produce no command.
        self.assertFalse((commands_dir / "archive-module-doc.md").exists())
        self.assertFalse((commands_dir / "tidy-doc.md").exists())
        # Standalone commands are always synced, independent of skill filter.
        for name in ("finish-task", "knowledge-status", "propose-knowledge"):
            self.assertTrue((commands_dir / f"{name}.md").exists(),
                            f"Standalone command {name}.md should always be synced")

    def test_sync_commands_standalone_survive_minimal_filter(self):
        """Standalone commands must be synced even under a minimal skill filter
        that exposes none of the doc-related skills."""
        repo = self._make_repo()
        sync_codebuddy(CORE_PACK, repo, skill_filter=["illuminate.layer-debug"])

        commands_dir = repo / ".codebuddy" / "commands"
        self.assertFalse((commands_dir / "record-knowledge.md").exists())
        self.assertFalse((commands_dir / "archive-module-doc.md").exists())
        self.assertFalse((commands_dir / "tidy-doc.md").exists())
        for name in ("finish-task", "knowledge-status", "propose-knowledge"):
            self.assertTrue((commands_dir / f"{name}.md").exists(),
                            f"Standalone command {name}.md should always be synced")

    def test_sync_commands_all_present_without_filter(self):
        """With no skill filter every command in the catalog is synced."""
        repo = self._make_repo()
        sync_codebuddy(CORE_PACK, repo)

        commands_dir = repo / ".codebuddy" / "commands"
        for name in ("record-knowledge", "archive-module-doc", "tidy-doc",
                     "finish-task", "knowledge-status", "propose-knowledge"):
            self.assertTrue((commands_dir / f"{name}.md").exists(),
                            f"Command {name}.md should exist with no filter")

    def test_first_sync_rejects_unmanaged_same_name_command(self):
        """A project-owned command sharing an Illuminate command's name must
        fail closed on first sync: nothing is written, not even the rules
        directory that otherwise gets rebuilt first."""
        repo = self._make_repo()
        proj_cmd = repo / ".codebuddy" / "commands" / "record-knowledge.md"
        proj_cmd.parent.mkdir(parents=True, exist_ok=True)
        original = "# project-owned record-knowledge\n"
        proj_cmd.write_text(original, encoding="utf-8")

        with self.assertRaises(ValueError) as ctx:
            sync_codebuddy(CORE_PACK, repo)
        self.assertIn("not Illuminate-managed", str(ctx.exception))

        # Fail-before-write: command intact, no rules, no skills, no
        # CODEBUDDY.md, no lock
        self.assertEqual(
            proj_cmd.read_text(encoding="utf-8"), original,
            "Existing project command must be untouched after failed sync",
        )
        self.assertFalse(
            (repo / ".codebuddy" / "rules").exists(),
            "Failed sync must not rebuild rules before the command collision",
        )
        self.assertFalse(
            (repo / ".codebuddy" / "skills").exists(),
            "Failed sync must not write skills before the command collision",
        )
        self.assertFalse(
            (repo / ".codebuddy" / "CODEBUDDY.md").exists(),
            "Failed sync must not write CODEBUDDY.md",
        )
        self.assertFalse(
            (repo / ".illuminate").exists(),
            "Failed sync must not write a lock",
        )

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
        self.assertEqual(lock["schema_version"], 1)
        self.assertEqual(lock["harness"], "codebuddy")
        self.assertEqual(lock["target"]["path"], str(repo.resolve()))
        self.assertEqual(lock["selection"]["skills"], lock["exposed_skills"])
        self.assertIn(".codebuddy/CODEBUDDY.md", lock["managed_artifacts"])
        self.assertEqual(lock["capabilities"], {"permissions": "declarative-only"})

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

    def test_first_sync_rejects_unmanaged_same_name_skill(self):
        """A project-owned skill sharing an Illuminate skill's name must
        fail closed on first sync (no overwrite, no claiming)."""
        repo = self._make_repo()
        project_skill = repo / ".codebuddy" / "skills" / "layer-debug"
        project_skill.mkdir(parents=True)
        project_skill.joinpath("SKILL.md").write_text(
            "# project-owned layer-debug", encoding="utf-8"
        )

        with self.assertRaises(ValueError) as ctx:
            sync_codebuddy(CORE_PACK, repo)
        self.assertIn("not Illuminate-managed", str(ctx.exception))

    def test_failed_collision_never_claims_or_deletes_existing_skill(self):
        repo = self._make_repo()
        project_skill = repo / ".codebuddy" / "skills" / "layer-debug"
        project_skill.mkdir(parents=True)
        original = "# project-owned layer-debug\nconfig: 42\n"
        project_skill.joinpath("SKILL.md").write_text(original, encoding="utf-8")
        project_skill.joinpath("project-config.json").write_text("{}", encoding="utf-8")

        with self.assertRaises(ValueError):
            sync_codebuddy(CORE_PACK, repo)

        self.assertEqual(
            project_skill.joinpath("SKILL.md").read_text(encoding="utf-8"),
            original,
            "Existing skill content must be untouched after failed sync",
        )
        self.assertTrue(project_skill.joinpath("project-config.json").exists())
        # Fail-before-write: no rules, no CODEBUDDY.md, no lock, no other
        # skill dirs
        self.assertFalse(
            (repo / ".codebuddy" / "rules").exists(),
            "Failed sync must not rebuild rules before the skill collision",
        )
        self.assertFalse(
            (repo / ".codebuddy" / "CODEBUDDY.md").exists(),
            "Failed sync must not write CODEBUDDY.md",
        )
        self.assertFalse(
            (repo / ".illuminate").exists(),
            "Failed sync must not write a lock claiming the colliding skill",
        )

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

    # ── Fail-before-write on stale-deletion targets (P0) ──

    def test_stale_command_readonly_fails_before_write(self):
        repo = self._make_repo()
        sync_codebuddy(CORE_PACK, repo, skill_filter=["illuminate.record-knowledge"])
        stale_cmd = repo / ".codebuddy" / "commands" / "record-knowledge.md"
        self.assertTrue(stale_cmd.exists())
        _set_readonly(stale_cmd)
        try:
            with self.assertRaises(ValueError):
                sync_codebuddy(CORE_PACK, repo, skill_filter=["illuminate.layer-debug"])
            self.assertFalse(
                (repo / ".codebuddy" / "skills" / "layer-debug").exists(),
                "Fail-before-write: layer-debug must not be written when a "
                "stale command cannot be deleted",
            )
        finally:
            _make_writable(stale_cmd)

    def test_stale_skill_readonly_fails_before_write(self):
        repo = self._make_repo()
        sync_codebuddy(CORE_PACK, repo, skill_filter=["illuminate.perf-profile"])
        stale_file = repo / ".codebuddy" / "skills" / "perf-profile" / "SKILL.md"
        self.assertTrue(stale_file.exists())
        _set_readonly(stale_file)
        try:
            with self.assertRaises(ValueError):
                sync_codebuddy(CORE_PACK, repo, skill_filter=["illuminate.layer-debug"])
            self.assertFalse(
                (repo / ".codebuddy" / "skills" / "layer-debug").exists(),
                "Fail-before-write: layer-debug must not be written when a "
                "stale skill cannot be deleted",
            )
        finally:
            _make_writable(stale_file)

    # ── Fail-before-write on existing read-only target file (P1) ──

    def test_existing_codebuddy_md_readonly_fails_before_write(self):
        repo = self._make_repo()
        sync_codebuddy(CORE_PACK, repo, skill_filter=["illuminate.record-knowledge"])
        cb = repo / ".codebuddy" / "CODEBUDDY.md"
        _set_readonly(cb)
        try:
            with self.assertRaises(ValueError):
                sync_codebuddy(CORE_PACK, repo, skill_filter=["illuminate.layer-debug"])
            self.assertFalse(
                (repo / ".codebuddy" / "skills" / "layer-debug").exists(),
                "Fail-before-write: layer-debug must not be written when "
                "CODEBUDDY.md is read-only",
            )
        finally:
            _make_writable(cb)

    # ── Clean without lock keeps rules dir (P2) ──

    def test_clean_without_lock_keeps_rules_dir(self):
        repo = self._make_repo()
        sync_codebuddy(CORE_PACK, repo)
        rules_dir = repo / ".codebuddy" / "rules" / "illuminate"
        lock = repo / ".illuminate" / "codebuddy-lock.json"
        lock.unlink()

        clean_sync(repo)

        self.assertTrue(
            rules_dir.exists(),
            "Clean without a lock must not rmtree the rules directory",
        )


if __name__ == "__main__":
    unittest.main()
