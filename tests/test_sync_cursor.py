"""Tests for Cursor sync (illuminate sync cursor)."""

import json
import re
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from illuminate import cli
from illuminate.managed_block import BEGIN_MARKER as _BEGIN_MARKER, END_MARKER as _END_MARKER
from illuminate.resolve import resolve_pack
from illuminate.sync_codex import sync_codex as sync_codex_fn
from illuminate.sync_cursor import (
    sync_cursor,
    check_sync,
    clean_sync,
)

REPO_ROOT = Path(__file__).parent.parent
CORE_PACK = REPO_ROOT / "packs" / "core"


class TestSyncCursor(unittest.TestCase):

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def _make_repo(self) -> Path:
        repo = self.tmpdir / "target-repo"
        repo.mkdir(parents=True, exist_ok=True)
        return repo

    # ── AGENTS.md block merge ──

    def test_sync_merges_agents_md_keeps_project_content(self):
        repo = self._make_repo()
        agents_path = repo / "AGENTS.md"
        agents_path.write_text("# My Project\n\nCustom rules here.\n", encoding="utf-8")

        sync_cursor(CORE_PACK, repo)

        content = agents_path.read_text(encoding="utf-8")
        self.assertIn("# My Project", content)
        self.assertIn("Custom rules here.", content)
        self.assertIn(_BEGIN_MARKER, content)
        self.assertIn(_END_MARKER, content)

    # ── Skills ──

    def test_sync_creates_cursor_skills(self):
        repo = self._make_repo()
        result = sync_cursor(CORE_PACK, repo)

        skills_dir = repo / ".cursor" / "skills"
        self.assertTrue(skills_dir.exists())
        self.assertTrue((skills_dir / "layer-debug" / "SKILL.md").exists())
        self.assertTrue((skills_dir / "record-knowledge" / "SKILL.md").exists())

    def test_sync_does_not_include_alias_skills(self):
        repo = self._make_repo()
        result = sync_cursor(CORE_PACK, repo)

        skills_dir = repo / ".cursor" / "skills"
        skill_dirs = [d.name for d in skills_dir.iterdir() if d.is_dir()]
        self.assertNotIn("grill-me", skill_dirs,
                         "Alias skills should not be synced")

    def test_sync_with_filter(self):
        repo = self._make_repo()
        result = sync_cursor(CORE_PACK, repo, skill_filter=["illuminate.layer-debug"])

        skills_dir = repo / ".cursor" / "skills"
        dirs = [d.name for d in skills_dir.iterdir() if d.is_dir()]
        self.assertIn("layer-debug", dirs)
        self.assertNotIn("perf-profile", dirs)

    # ── Ownership collisions (fail-before-write) ──

    def test_first_sync_rejects_unmanaged_same_name_skill(self):
        """A project-owned skill sharing an Illuminate skill's name must
        fail closed on first sync (no overwrite, no claiming)."""
        repo = self._make_repo()
        project_skill = repo / ".cursor" / "skills" / "layer-debug"
        project_skill.mkdir(parents=True)
        project_skill.joinpath("SKILL.md").write_text(
            "# project-owned layer-debug", encoding="utf-8"
        )

        with self.assertRaises(ValueError) as ctx:
            sync_cursor(CORE_PACK, repo)
        self.assertIn("not Illuminate-managed", str(ctx.exception))

    def test_failed_collision_never_claims_or_deletes_existing_skill(self):
        """After a failed collision, the existing skill is intact and the
        lock does not claim it. Sync must fail before writing anything."""
        repo = self._make_repo()
        project_skill = repo / ".cursor" / "skills" / "layer-debug"
        project_skill.mkdir(parents=True)
        original = "# project-owned layer-debug\nconfig: 42\n"
        project_skill.joinpath("SKILL.md").write_text(original, encoding="utf-8")
        project_skill.joinpath("project-config.json").write_text("{}", encoding="utf-8")

        with self.assertRaises(ValueError):
            sync_cursor(CORE_PACK, repo)

        self.assertEqual(
            project_skill.joinpath("SKILL.md").read_text(encoding="utf-8"),
            original,
            "Existing skill content must be untouched after failed sync",
        )
        self.assertTrue(project_skill.joinpath("project-config.json").exists())
        # Fail-before-write: no AGENTS.md, no lock, no other skill dirs
        self.assertFalse(
            (repo / "AGENTS.md").exists(),
            "Failed sync must not write AGENTS.md",
        )
        self.assertFalse(
            (repo / ".illuminate").exists(),
            "Failed sync must not write a lock claiming the colliding skill",
        )

    # ── Project content preservation ──

    def test_sync_does_not_delete_project_skills_or_commands(self):
        repo = self._make_repo()
        proj_skill = repo / ".cursor" / "skills" / "project-custom" / "SKILL.md"
        proj_skill.parent.mkdir(parents=True, exist_ok=True)
        proj_skill.write_text("# Custom Skill\n", encoding="utf-8")
        proj_cmd = repo / ".cursor" / "commands" / "project.md"
        proj_cmd.parent.mkdir(parents=True, exist_ok=True)
        proj_cmd.write_text("Custom command\n", encoding="utf-8")

        sync_cursor(CORE_PACK, repo)

        self.assertTrue(proj_skill.exists(),
                        "Project-owned skills should survive sync")
        self.assertTrue(proj_cmd.exists(),
                        "Project-owned commands should survive sync")

    # ── Commands ──

    def test_sync_commands_match_exposed_skills(self):
        repo = self._make_repo()
        result = sync_cursor(CORE_PACK, repo, skill_filter=["illuminate.record-knowledge"])

        commands_dir = repo / ".cursor" / "commands"
        self.assertTrue((commands_dir / "record-knowledge.md").exists())
        self.assertFalse((commands_dir / "archive-module-doc.md").exists())

    # ── Lock ──

    def test_sync_creates_lock(self):
        repo = self._make_repo()
        result = sync_cursor(CORE_PACK, repo)

        lock_path = repo / ".illuminate" / "cursor-lock.json"
        self.assertTrue(lock_path.exists())
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
        self.assertEqual(lock["schema_version"], 1)
        self.assertEqual(lock["harness"], "cursor")
        self.assertEqual(
            lock["capabilities"],
            {"permissions": "declarative-only", "commands": "beta"},
        )
        self.assertEqual(lock["selection"]["skills"], lock["exposed_skills"])
        managed = lock["managed_artifacts"]
        self.assertIn("AGENTS.md", managed)
        self.assertTrue(any(m.startswith(".cursor/skills/") for m in managed))
        self.assertTrue(any(m.startswith(".cursor/commands/") for m in managed))
        # Top-level contract keys
        self.assertIn("skills", lock)
        self.assertIn("commands", lock)
        self.assertIn("agents_md_hash", lock)

    # ── Check ──

    def test_check_passes_after_sync(self):
        repo = self._make_repo()
        sync_cursor(CORE_PACK, repo)
        ok, issues = check_sync(CORE_PACK, repo)
        self.assertTrue(ok, f"Check should pass: {issues}")

    def test_check_fails_without_sync(self):
        repo = self._make_repo()
        ok, issues = check_sync(CORE_PACK, repo)
        self.assertFalse(ok)

    def test_check_detects_missing_or_modified_skill(self):
        repo = self._make_repo()
        sync_cursor(CORE_PACK, repo)
        # Missing skill file
        sk = repo / ".cursor" / "skills" / "layer-debug" / "SKILL.md"
        sk.unlink()
        ok, issues = check_sync(CORE_PACK, repo)
        self.assertFalse(ok)

        # Re-sync then modify a command file
        sync_cursor(CORE_PACK, repo)
        cmd = repo / ".cursor" / "commands" / "record-knowledge.md"
        self.assertTrue(cmd.exists(), "record-knowledge command should exist")
        cmd.write_text("# tampered\n", encoding="utf-8")
        ok, issues = check_sync(CORE_PACK, repo)
        self.assertFalse(ok)

    # ── Clean ──

    def test_clean_removes_managed_artifacts(self):
        repo = self._make_repo()
        sync_cursor(CORE_PACK, repo)

        result = clean_sync(repo)
        self.assertIn("removed_artifacts", result)

        # Managed skills removed
        self.assertFalse((repo / ".cursor" / "skills" / "layer-debug").exists())
        # Managed commands removed
        self.assertFalse((repo / ".cursor" / "commands" / "record-knowledge.md").exists())
        # AGENTS.md illuminate block removed
        agents_path = repo / "AGENTS.md"
        content = agents_path.read_text(encoding="utf-8")
        self.assertNotIn(_BEGIN_MARKER, content)
        # Lock removed
        self.assertFalse((repo / ".illuminate" / "cursor-lock.json").exists())

    def test_clean_does_not_remove_project_content(self):
        repo = self._make_repo()
        proj_skill = repo / ".cursor" / "skills" / "project-custom" / "SKILL.md"
        proj_skill.parent.mkdir(parents=True, exist_ok=True)
        proj_skill.write_text("# Custom Skill\n", encoding="utf-8")
        proj_cmd = repo / ".cursor" / "commands" / "project.md"
        proj_cmd.parent.mkdir(parents=True, exist_ok=True)
        proj_cmd.write_text("Custom command\n", encoding="utf-8")

        sync_cursor(CORE_PACK, repo)
        clean_sync(repo)

        self.assertTrue(proj_skill.exists(),
                        "Project-owned skills should survive clean")
        self.assertTrue(proj_cmd.exists(),
                        "Project-owned commands should survive clean")

    def test_clean_on_unsynced_repo(self):
        repo = self._make_repo()
        repo.joinpath("AGENTS.md").write_text("# Clean\n", encoding="utf-8")
        result = clean_sync(repo)
        content = (repo / "AGENTS.md").read_text(encoding="utf-8")
        self.assertEqual(content.strip(), "# Clean")

    # ── Pack frontmatter contract ──

    def test_all_skills_have_cursor_frontmatter(self):
        """Every exposed (non-alias) skill source SKILL.md must carry
        non-empty name:/description: so the Cursor frontmatter can be emitted
        for everything the adapter will actually sync."""
        resolved = resolve_pack(CORE_PACK, "/tmp")
        exposed_ids = set(resolved["skills"]["exposed"])
        manifest = resolved["manifest"]
        exposed_dirs = [
            e["dir"] for e in manifest.get("skills", []) if e["id"] in exposed_ids
        ]
        self.assertGreater(len(exposed_dirs), 0)
        for skill_dir in exposed_dirs:
            skill_md = CORE_PACK / skill_dir / "SKILL.md"
            self.assertTrue(
                skill_md.exists(), f"Exposed skill missing SKILL.md: {skill_dir}"
            )
            text = skill_md.read_text(encoding="utf-8")
            m = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
            self.assertIsNotNone(
                m,
                f"{skill_md.relative_to(CORE_PACK)} lacks a frontmatter block",
            )
            frontmatter = m.group(1)
            for key in ("name", "description"):
                km = re.search(rf"(?m)^{key}:\s*(\S.*)$", frontmatter)
                self.assertIsNotNone(
                    km,
                    f"{skill_md.relative_to(CORE_PACK)} lacks a {key}: key",
                )
                self.assertNotEqual(
                    km.group(1).strip(), "",
                    f"{skill_md.relative_to(CORE_PACK)} has an empty {key}: value",
                )


    # ── Idempotence ──

    def test_sync_is_idempotent(self):
        repo = self._make_repo()
        sync_cursor(CORE_PACK, repo)
        first_lock = (repo / ".illuminate" / "cursor-lock.json").read_text(encoding="utf-8")

        result = sync_cursor(CORE_PACK, repo)

        self.assertFalse(result["agents_modified"],
                         "Second sync must not modify AGENTS.md")
        second_lock = json.loads(
            (repo / ".illuminate" / "cursor-lock.json").read_text(encoding="utf-8")
        )
        first = json.loads(first_lock)
        # All determinable fields stay byte-stable; only created_at may differ
        for key in ("managed_artifacts", "skills", "commands", "agents_md_hash",
                    "exposed_skills", "selection", "capabilities", "pack"):
            self.assertEqual(first.get(key), second_lock.get(key),
                             f"Lock field '{key}' changed on second sync")

    # ── Stale cleanup ──

    def test_sync_removes_stale_skill(self):
        repo = self._make_repo()
        sync_cursor(CORE_PACK, repo)
        stale = repo / ".cursor" / "skills" / "perf-profile"
        self.assertTrue(stale.exists())

        sync_cursor(CORE_PACK, repo, skill_filter=["illuminate.layer-debug"])

        self.assertFalse(stale.exists(),
                         "Skill no longer exposed must be removed")
        lock = json.loads(
            (repo / ".illuminate" / "cursor-lock.json").read_text(encoding="utf-8")
        )
        names = {e["name"] for e in lock["skills"]}
        self.assertNotIn("perf-profile", names)
        self.assertIn("layer-debug", names)
        ok, issues = check_sync(CORE_PACK, repo)
        self.assertTrue(ok, f"Check should pass after stale removal: {issues}")

    def test_sync_removes_stale_command(self):
        repo = self._make_repo()
        sync_cursor(CORE_PACK, repo)
        cmd = repo / ".cursor" / "commands" / "record-knowledge.md"
        self.assertTrue(cmd.exists())

        sync_cursor(CORE_PACK, repo, skill_filter=["illuminate.layer-debug"])

        self.assertFalse(cmd.exists(),
                         "Command whose skill is no longer exposed must be removed")
        ok, issues = check_sync(CORE_PACK, repo)
        self.assertTrue(ok, f"Check should pass after command removal: {issues}")

    # ── Check failure modes ──

    def test_check_detects_modified_skill_file(self):
        repo = self._make_repo()
        sync_cursor(CORE_PACK, repo)
        sk = repo / ".cursor" / "skills" / "layer-debug" / "SKILL.md"
        sk.write_text("# tampered\n", encoding="utf-8")

        ok, issues = check_sync(CORE_PACK, repo)
        self.assertFalse(ok)
        self.assertTrue(any("hash mismatch" in i for i in issues), issues)

    def test_check_detects_missing_command(self):
        repo = self._make_repo()
        sync_cursor(CORE_PACK, repo)
        cmd = repo / ".cursor" / "commands" / "record-knowledge.md"
        cmd.unlink()

        ok, issues = check_sync(CORE_PACK, repo)
        self.assertFalse(ok)
        self.assertTrue(any("Missing command" in i for i in issues), issues)

    def test_check_detects_removed_agents_block(self):
        repo = self._make_repo()
        sync_cursor(CORE_PACK, repo)
        agents_path = repo / "AGENTS.md"
        content = agents_path.read_text(encoding="utf-8")
        agents_path.write_text(
            content.replace(_BEGIN_MARKER, "").replace(_END_MARKER, ""),
            encoding="utf-8",
        )

        ok, issues = check_sync(CORE_PACK, repo)
        self.assertFalse(ok)
        self.assertTrue(any("block markers" in i for i in issues), issues)

    def test_check_detects_modified_agents_block(self):
        repo = self._make_repo()
        sync_cursor(CORE_PACK, repo)
        agents_path = repo / "AGENTS.md"
        content = agents_path.read_text(encoding="utf-8")
        agents_path.write_text(
            content.replace("Synchronized skills:", "Synchronized skillz:"),
            encoding="utf-8",
        )

        ok, issues = check_sync(CORE_PACK, repo)
        self.assertFalse(ok)
        self.assertTrue(any("hash mismatch" in i for i in issues), issues)

    def test_check_detects_missing_agents_md(self):
        repo = self._make_repo()
        sync_cursor(CORE_PACK, repo)
        (repo / "AGENTS.md").unlink()

        ok, issues = check_sync(CORE_PACK, repo)
        self.assertFalse(ok)
        self.assertTrue(any("AGENTS.md" in i for i in issues), issues)

    def test_check_detects_changed_source_pack(self):
        import shutil
        pack_copy = self.tmpdir / "pack-copy"
        shutil.copytree(CORE_PACK, pack_copy)
        repo = self._make_repo()
        sync_cursor(pack_copy, repo)
        # Mutate a policy so the pack source hash changes
        policy = next((pack_copy / "policies").glob("*.md"))
        policy.write_text(policy.read_text(encoding="utf-8") + "\nchanged\n",
                          encoding="utf-8")

        ok, issues = check_sync(pack_copy, repo)
        self.assertFalse(ok)
        self.assertTrue(any("Pack source changed" in i for i in issues), issues)

    # ── Clean boundary scenarios ──

    def test_clean_without_lock_keeps_managed_artifacts(self):
        """Without a lock, clean cannot know what is managed: it must leave
        .cursor content untouched and remove nothing destructive."""
        repo = self._make_repo()
        sync_cursor(CORE_PACK, repo)
        skill = repo / ".cursor" / "skills" / "layer-debug"
        lock = repo / ".illuminate" / "cursor-lock.json"
        lock.unlink()

        result = clean_sync(repo)

        self.assertTrue(skill.exists(),
                        "Clean without a lock must not guess what to delete")
        self.assertNotIn("layer-debug", str(result))

    def test_clean_without_agents_block(self):
        repo = self._make_repo()
        agents_path = repo / "AGENTS.md"
        agents_path.write_text("# Project only\n", encoding="utf-8")
        lock_dir = repo / ".illuminate"
        lock_dir.mkdir(parents=True)
        (lock_dir / "cursor-lock.json").write_text(
            json.dumps({"skills": [], "commands": {}}), encoding="utf-8"
        )

        result = clean_sync(repo)

        self.assertEqual(agents_path.read_text(encoding="utf-8").strip(),
                         "# Project only")
        self.assertNotIn("block", str(result.get("removed_artifacts")))

    def test_clean_removes_empty_cursor_dirs(self):
        repo = self._make_repo()
        sync_cursor(CORE_PACK, repo, skill_filter=["illuminate.record-knowledge"])
        # Only one command file; clean removes skills/commands and .cursor
        clean_sync(repo)

        self.assertFalse((repo / ".cursor").exists(),
                         "Empty .cursor directory should be cleaned up")

    # ── Cross-harness AGENTS.md sharing ──

    def test_codex_then_cursor_shares_agents_block(self):
        from illuminate.sync_codex import check_sync as check_codex_sync
        repo = self._make_repo()
        agents_path = repo / "AGENTS.md"
        agents_path.write_text("# Project\n\nUser content.\n", encoding="utf-8")

        sync_codex_fn(CORE_PACK, repo)
        sync_cursor(CORE_PACK, repo)

        content = agents_path.read_text(encoding="utf-8")
        self.assertIn("# Project", content)
        self.assertIn("User content.", content)
        self.assertEqual(content.count(_BEGIN_MARKER), 1,
                         "AGENTS.md must not contain duplicated illuminate blocks")
        self.assertTrue((repo / ".illuminate" / "codex-lock.json").exists())
        self.assertTrue((repo / ".illuminate" / "cursor-lock.json").exists())
        ok, issues = check_sync(CORE_PACK, repo)
        self.assertTrue(ok, f"Cursor check should pass: {issues}")
        ok, issues = check_codex_sync(CORE_PACK, repo)
        self.assertTrue(ok, f"Codex check should pass: {issues}")

    # ── Empty skill filter ──

    def test_empty_skill_filter_raises(self):
        repo = self._make_repo()
        with self.assertRaises(ValueError):
            sync_cursor(CORE_PACK, repo, skill_filter=[])


class TestCursorCli(unittest.TestCase):
    """Minimal CLI routing coverage for the cursor sync branch."""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def _repo(self) -> Path:
        repo = self.tmpdir / "target-repo"
        repo.mkdir(parents=True, exist_ok=True)
        return repo

    def test_cmd_sync_cursor_success(self):
        args = SimpleNamespace(
            pack=str(CORE_PACK), repo=str(self._repo()), skill=None
        )
        self.assertEqual(cli._cmd_sync_cursor(args), 0)

    def test_cmd_sync_cursor_missing_pack_returns_1(self):
        args = SimpleNamespace(
            pack=str(self.tmpdir / "nope"), repo=str(self._repo()), skill=None
        )
        self.assertEqual(cli._cmd_sync_cursor(args), 1)

    def test_cmd_sync_cursor_collision_returns_1(self):
        repo = self._repo()
        proj = repo / ".cursor" / "skills" / "layer-debug"
        proj.mkdir(parents=True)
        proj.joinpath("SKILL.md").write_text("# mine\n", encoding="utf-8")
        args = SimpleNamespace(pack=str(CORE_PACK), repo=str(repo), skill=None)
        self.assertEqual(cli._cmd_sync_cursor(args), 1)

    def test_cmd_sync_check_cursor_route(self):
        repo = self._repo()
        sync_cursor(CORE_PACK, repo)
        args = SimpleNamespace(
            pack=str(CORE_PACK), repo=str(repo), harness="cursor"
        )
        self.assertEqual(cli._cmd_sync_check(args), 0)
        sk = repo / ".cursor" / "skills" / "layer-debug" / "SKILL.md"
        sk.write_text("# tampered\n", encoding="utf-8")
        self.assertEqual(cli._cmd_sync_check(args), 1)

    def test_cmd_sync_clean_cursor_route(self):
        repo = self._repo()
        sync_cursor(CORE_PACK, repo)
        args = SimpleNamespace(repo=str(repo), harness="cursor")
        self.assertEqual(cli._cmd_sync_clean(args), 0)
        self.assertFalse((repo / ".illuminate" / "cursor-lock.json").exists())


if __name__ == "__main__":
    unittest.main()
