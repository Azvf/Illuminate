"""Tests for Codex sync (illuminate sync codex)."""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from illuminate.sync_codex import (
    sync_codex,
    check_sync,
    clean_sync,
    merge_agents_block,
    load_codex_lock,
    _BEGIN_MARKER,
    _END_MARKER,
)

REPO_ROOT = Path(__file__).parent.parent
CORE_PACK = Path(__file__).parent.parent / "src" / "illuminate" / "builtin_pack"


class TestSyncCodex(unittest.TestCase):

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def _make_repo(self) -> Path:
        """Create a minimal git-like repo structure."""
        repo = self.tmpdir / "target-repo"
        repo.mkdir(parents=True, exist_ok=True)
        return repo

    # ── AGENTS.md block merge ──

    def test_merge_block_appends_when_no_markers(self):
        content = "# My Project\n\nExisting rules here.\n"
        agents_path = self.tmpdir / "AGENTS.md"
        agents_path.write_text(content, encoding="utf-8")

        block = "<!-- illuminate:begin\npack=test\nversion=1\n-->\n\n## Illuminate\n\nDo X.\n\n<!-- illuminate:end -->"
        new_content, modified = merge_agents_block(agents_path, block)

        self.assertTrue(modified)
        self.assertIn(_BEGIN_MARKER, new_content)
        self.assertIn(_END_MARKER, new_content)
        self.assertIn("Existing rules here.", new_content)

    def test_merge_block_replaces_existing(self):
        content = "# My Project\n\n<!-- illuminate:begin\npack=old\nversion=0\n-->\n\nOLD\n\n<!-- illuminate:end -->\n\nKeep me.\n"
        agents_path = self.tmpdir / "AGENTS.md"
        agents_path.write_text(content, encoding="utf-8")

        block = "<!-- illuminate:begin\npack=new\nversion=1\n-->\n\nNEW\n\n<!-- illuminate:end -->"
        new_content, modified = merge_agents_block(agents_path, block)

        self.assertTrue(modified)
        self.assertIn("NEW", new_content)
        self.assertNotIn("OLD", new_content)
        self.assertIn("Keep me.", new_content)

    def test_merge_block_noop_on_identical(self):
        block = "<!-- illuminate:begin\npack=test\nversion=1\n-->\n\nSome rules.\n\n<!-- illuminate:end -->"
        agents_path = self.tmpdir / "AGENTS.md"
        agents_path.write_text("# Project\n\n" + block + "\n", encoding="utf-8")

        new_content, modified = merge_agents_block(agents_path, block)
        # The block is identical; merge should produce same content
        self.assertFalse(modified)

    def test_merge_creates_file_if_missing(self):
        agents_path = self.tmpdir / "AGENTS.md"
        block = "<!-- illuminate:begin\npack=test\nversion=1\n-->\n\n## Rules\n\n<!-- illuminate:end -->"
        new_content, modified = merge_agents_block(agents_path, block)
        self.assertTrue(modified)
        self.assertIn("## Rules", new_content)

    # ── Full sync ──

    def test_sync_creates_agents_md_block(self):
        repo = self._make_repo()
        result = sync_codex(CORE_PACK, repo)

        agents_path = repo / "AGENTS.md"
        self.assertTrue(agents_path.exists())
        content = agents_path.read_text(encoding="utf-8")
        self.assertIn(_BEGIN_MARKER, content)
        self.assertIn("Illuminate Runtime Policies", content)
        self.assertIn(_END_MARKER, content)

    def test_sync_creates_agents_skills(self):
        repo = self._make_repo()
        result = sync_codex(CORE_PACK, repo)

        skills_dir = repo / ".agents" / "skills"
        self.assertTrue(skills_dir.exists())
        self.assertTrue((skills_dir / "layer-debug" / "SKILL.md").exists())

    def test_sync_does_not_include_alias_skills(self):
        repo = self._make_repo()
        result = sync_codex(CORE_PACK, repo)

        skills_dir = repo / ".agents" / "skills"
        skill_dirs = [d.name for d in skills_dir.iterdir() if d.is_dir()]
        self.assertNotIn("grill-me", skill_dirs,
                         "Alias skills should not be synced")

    def test_sync_with_filter(self):
        repo = self._make_repo()
        result = sync_codex(CORE_PACK, repo, skill_filter=["illuminate.layer-debug"])

        skills_dir = repo / ".agents" / "skills"
        dirs = [d.name for d in skills_dir.iterdir() if d.is_dir()]
        self.assertIn("layer-debug", dirs)
        self.assertNotIn("perf-profile", dirs)

    def test_sync_creates_openai_yaml(self):
        repo = self._make_repo()
        result = sync_codex(CORE_PACK, repo)

        yaml_path = repo / ".agents" / "skills" / "layer-debug" / "agents" / "openai.yaml"
        self.assertTrue(yaml_path.exists(), "openai.yaml should be created")
        content = yaml_path.read_text(encoding="utf-8")
        self.assertIn("display_name", content)
        self.assertIn("allow_implicit_invocation", content)
        self.assertIn("default_prompt", content)

    def test_sync_creates_codex_lock(self):
        repo = self._make_repo()
        result = sync_codex(CORE_PACK, repo)

        lock_path = repo / ".illuminate" / "codex-lock.json"
        self.assertTrue(lock_path.exists())
        lock = load_codex_lock(repo)
        self.assertIsNotNone(lock)
        self.assertEqual(lock["pack"]["id"], "illuminate.core")
        self.assertIn("exposed_skills", lock)
        self.assertIn("agents_md_hash", lock)
        self.assertIn("skills", lock)
        self.assertEqual(lock["schema_version"], 1)
        self.assertEqual(lock["harness"], "codex")
        self.assertEqual(lock["target"]["path"], str(repo.resolve()))
        self.assertEqual(lock["selection"]["skills"], lock["exposed_skills"])
        self.assertIn("AGENTS.md", lock["managed_artifacts"])

    def test_sync_does_not_modify_existing_user_content(self):
        repo = self._make_repo()
        agents_path = repo / "AGENTS.md"
        agents_path.write_text("# My Project\n\nCustom rules here.\n", encoding="utf-8")

        sync_codex(CORE_PACK, repo)

        content = agents_path.read_text(encoding="utf-8")
        self.assertIn("# My Project", content)
        self.assertIn("Custom rules here.", content)
        self.assertIn("Illuminate Runtime Policies", content)

    def test_sync_idempotent(self):
        repo = self._make_repo()
        sync_codex(CORE_PACK, repo)
        result2 = sync_codex(CORE_PACK, repo)
        self.assertFalse(result2["agents_modified"],
                         "Second sync should not modify AGENTS.md")

    def test_sync_removes_stale_skills(self):
        repo = self._make_repo()
        # First sync with all skills
        sync_codex(CORE_PACK, repo)

        # Second sync with only one skill
        sync_codex(CORE_PACK, repo, skill_filter=["illuminate.layer-debug"])

        skills_dir = repo / ".agents" / "skills"
        dirs = [d.name for d in skills_dir.iterdir() if d.is_dir()]
        self.assertIn("layer-debug", dirs)
        self.assertNotIn("perf-profile", dirs,
                         "Stale skills should be removed on re-sync")

    def test_sync_preserves_project_owned_skills(self):
        """Lock-based ownership: a project-owned skill under .agents/skills/
        must survive first sync (regression guard for the old full-dir wipe)."""
        repo = self._make_repo()
        project_skill = repo / ".agents" / "skills" / "my-own-skill"
        project_skill.mkdir(parents=True)
        (project_skill / "SKILL.md").write_text("# project skill", encoding="utf-8")

        sync_codex(CORE_PACK, repo)

        self.assertTrue(
            (repo / ".agents" / "skills" / "my-own-skill" / "SKILL.md").exists(),
            "Project-owned skill must not be deleted on first sync",
        )

    def test_clean_preserves_project_owned_skills(self):
        """clean_sync must only remove lock-managed skills."""
        repo = self._make_repo()
        project_skill = repo / ".agents" / "skills" / "my-own-skill"
        project_skill.mkdir(parents=True)
        (project_skill / "SKILL.md").write_text("# project skill", encoding="utf-8")

        sync_codex(CORE_PACK, repo)
        clean_sync(repo)

        self.assertTrue(
            (repo / ".agents" / "skills" / "my-own-skill" / "SKILL.md").exists(),
            "clean_sync must not delete project-owned skills",
        )

    # ── Check ──

    def test_check_passes_after_sync(self):
        repo = self._make_repo()
        sync_codex(CORE_PACK, repo)
        ok, issues = check_sync(CORE_PACK, repo)
        self.assertTrue(ok, f"Check should pass: {issues}")

    def test_check_fails_without_sync(self):
        repo = self._make_repo()
        ok, issues = check_sync(CORE_PACK, repo)
        self.assertFalse(ok)

    def test_check_detects_tampered_agents(self):
        repo = self._make_repo()
        sync_codex(CORE_PACK, repo)
        agents_path = repo / "AGENTS.md"
        agents_path.write_text("# Tampered\n", encoding="utf-8")
        ok, issues = check_sync(CORE_PACK, repo)
        self.assertFalse(ok)
        self.assertTrue(any("hash mismatch" in i.lower() for i in issues))

    def test_check_detects_missing_skill_file(self):
        repo = self._make_repo()
        sync_codex(CORE_PACK, repo)
        sk_path = repo / ".agents" / "skills" / "layer-debug" / "SKILL.md"
        sk_path.unlink()
        ok, issues = check_sync(CORE_PACK, repo)
        self.assertFalse(ok)
        self.assertTrue(any("missing" in i.lower() for i in issues))

    def test_check_detects_missing_openai_yaml(self):
        repo = self._make_repo()
        sync_codex(CORE_PACK, repo)
        yaml_path = repo / ".agents" / "skills" / "layer-debug" / "agents" / "openai.yaml"
        yaml_path.unlink()
        ok, issues = check_sync(CORE_PACK, repo)
        self.assertFalse(ok)
        self.assertTrue(
            any("missing skill file" in i.lower() for i in issues),
            f"Missing openai.yaml not detected: {issues}",
        )

    def test_check_detects_tampered_openai_yaml(self):
        repo = self._make_repo()
        sync_codex(CORE_PACK, repo)
        yaml_path = repo / ".agents" / "skills" / "layer-debug" / "agents" / "openai.yaml"
        yaml_path.write_text("# tampered\n", encoding="utf-8")
        ok, issues = check_sync(CORE_PACK, repo)
        self.assertFalse(ok)
        self.assertTrue(
            any("hash mismatch" in i.lower() for i in issues),
            f"Tampered openai.yaml not detected: {issues}",
        )

    def test_check_detects_changed_source_pack(self):
        """Changing the pack source after sync must be reported by check_sync."""
        repo = self._make_repo()
        tmp_pack = self.tmpdir / "pack-copy"
        import shutil
        shutil.copytree(CORE_PACK, tmp_pack)
        sync_codex(tmp_pack, repo)
        # Mutate the pack source after sync
        target = tmp_pack / "skills" / "layer-debug" / "SKILL.md"
        target.write_text(target.read_text(encoding="utf-8") + "\n# changed\n", encoding="utf-8")
        ok, issues = check_sync(tmp_pack, repo)
        self.assertFalse(ok)
        self.assertTrue(
            any("pack source changed" in i.lower() for i in issues),
            f"Changed pack not detected: {issues}",
        )

    # ── Ownership collisions ──

    def test_first_sync_rejects_unmanaged_same_name_skill(self):
        """A project-owned skill sharing an Illuminate skill's name must
        fail closed on first sync (no overwrite, no claiming)."""
        repo = self._make_repo()
        project_skill = repo / ".agents" / "skills" / "layer-debug"
        project_skill.mkdir(parents=True)
        (project_skill / "SKILL.md").write_text("# project-owned layer-debug", encoding="utf-8")

        with self.assertRaises(ValueError) as ctx:
            sync_codex(CORE_PACK, repo)
        self.assertIn("not Illuminate-managed", str(ctx.exception))

    def test_failed_collision_never_claims_or_deletes_existing_skill(self):
        """After a failed collision, the existing skill is intact and the
        lock does not claim it."""
        repo = self._make_repo()
        project_skill = repo / ".agents" / "skills" / "layer-debug"
        project_skill.mkdir(parents=True)
        original = "# project-owned layer-debug\nconfig: 42\n"
        (project_skill / "SKILL.md").write_text(original, encoding="utf-8")
        (project_skill / "project-config.json").write_text("{}", encoding="utf-8")

        with self.assertRaises(ValueError):
            sync_codex(CORE_PACK, repo)

        self.assertEqual(
            (project_skill / "SKILL.md").read_text(encoding="utf-8"), original,
            "Existing skill content must be untouched after failed sync",
        )
        self.assertTrue((project_skill / "project-config.json").exists())
        # Fail-before-write: no AGENTS.md, no lock, no extra skill dirs
        self.assertFalse(
            (repo / "AGENTS.md").exists(),
            "Failed sync must not write AGENTS.md",
        )
        self.assertFalse(
            (repo / ".illuminate").exists(),
            "Failed sync must not write a lock claiming the colliding skill",
        )
        skill_dirs = [
            d.name for d in (repo / ".agents" / "skills").iterdir() if d.is_dir()
        ]
        self.assertEqual(
            skill_dirs, ["layer-debug"],
            "Failed sync must not copy any Illuminate skills",
        )

    # ── Clean ──

    def test_clean_removes_all_artifacts(self):
        repo = self._make_repo()
        sync_codex(CORE_PACK, repo)

        result = clean_sync(repo)
        self.assertIn("removed_artifacts", result)

        # Check AGENTS.md no longer has block
        agents_path = repo / "AGENTS.md"
        content = agents_path.read_text(encoding="utf-8")
        self.assertNotIn(_BEGIN_MARKER, content)

        # Check .agents/ removed
        self.assertFalse((repo / ".agents").exists())

        # Check codex-lock removed
        self.assertFalse((repo / ".illuminate" / "codex-lock.json").exists())

    def test_clean_on_unsynced_repo(self):
        repo = self._make_repo()
        repo.joinpath("AGENTS.md").write_text("# Clean\n", encoding="utf-8")
        result = clean_sync(repo)
        # Should not fail; AGENTS.md should remain
        content = (repo / "AGENTS.md").read_text(encoding="utf-8")
        self.assertEqual(content.strip(), "# Clean")


if __name__ == "__main__":
    unittest.main()
