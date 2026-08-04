"""Tests for Cursor sync (illuminate sync cursor)."""

import json
import os
import re
import stat
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
from illuminate.sync_codex import check_sync as check_codex_sync
from illuminate.sync_cursor import (
    sync_cursor,
    check_sync,
    clean_sync,
    doctor_sync,
)

REPO_ROOT = Path(__file__).parent.parent
CORE_PACK = REPO_ROOT / "packs" / "core"

_RULES_REL = ".cursor/rules/illuminate/core.mdc"


def _set_readonly(path: Path) -> None:
    """Make a file read-only on both Windows (attribute) and POSIX (mode)."""
    os.chmod(path, stat.S_IREAD | stat.S_IRGRP | stat.S_IROTH)


def _make_writable(path: Path) -> None:
    """Restore write permission so tempdir cleanup does not fail."""
    os.chmod(path, stat.S_IWRITE | stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)


class TestSyncCursor(unittest.TestCase):

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def _make_repo(self) -> Path:
        repo = self.tmpdir / "target-repo"
        repo.mkdir(parents=True, exist_ok=True)
        return repo

    # ── Rules artifact (.cursor/rules/illuminate/core.mdc) ──

    def test_sync_writes_cursor_rules_mdc_keeps_project_agents(self):
        """Cursor sync writes a dedicated .mdc and does NOT touch the root
        AGENTS.md by default."""
        repo = self._make_repo()
        agents_path = repo / "AGENTS.md"
        agents_path.write_text("# My Project\n\nCustom rules here.\n", encoding="utf-8")

        sync_cursor(CORE_PACK, repo)

        # AGENTS.md is untouched: project content only, no illuminate block.
        self.assertEqual(
            agents_path.read_text(encoding="utf-8"),
            "# My Project\n\nCustom rules here.\n",
        )
        self.assertNotIn(_BEGIN_MARKER, agents_path.read_text(encoding="utf-8"))

        # Rules .mdc exists with frontmatter + synchronized skills.
        rules_path = repo / _RULES_REL
        self.assertTrue(rules_path.exists())
        text = rules_path.read_text(encoding="utf-8")
        self.assertRegex(text, r"^---\ndescription: .+\n---")
        self.assertIn("Synchronized skills:", text)

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
        # Fail-before-write: no rules .mdc, no lock, no other skill dirs
        self.assertFalse(
            (repo / _RULES_REL).exists(),
            "Failed sync must not write the rules .mdc",
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
        sync_cursor(CORE_PACK, repo, skill_filter=["illuminate.layer-debug"])

        commands_dir = repo / ".cursor" / "commands"
        self.assertFalse((commands_dir / "record-knowledge.md").exists())
        self.assertFalse((commands_dir / "archive-module-doc.md").exists())
        self.assertFalse((commands_dir / "tidy-doc.md").exists())
        for name in ("finish-task", "knowledge-status", "propose-knowledge"):
            self.assertTrue((commands_dir / f"{name}.md").exists(),
                            f"Standalone command {name}.md should always be synced")

    def test_sync_commands_all_present_without_filter(self):
        """With no skill filter every command in the catalog is synced."""
        repo = self._make_repo()
        sync_cursor(CORE_PACK, repo)

        commands_dir = repo / ".cursor" / "commands"
        for name in ("record-knowledge", "archive-module-doc", "tidy-doc",
                     "finish-task", "knowledge-status", "propose-knowledge"):
            self.assertTrue((commands_dir / f"{name}.md").exists(),
                            f"Command {name}.md should exist with no filter")

    def test_first_sync_rejects_unmanaged_same_name_command(self):
        """A project-owned command sharing an Illuminate command's name must
        fail closed on first sync: nothing is written, not even other
        artifacts that would otherwise have been synced first."""
        repo = self._make_repo()
        proj_cmd = repo / ".cursor" / "commands" / "record-knowledge.md"
        proj_cmd.parent.mkdir(parents=True, exist_ok=True)
        original = "# project-owned record-knowledge\n"
        proj_cmd.write_text(original, encoding="utf-8")

        with self.assertRaises(ValueError) as ctx:
            sync_cursor(CORE_PACK, repo)
        self.assertIn("not Illuminate-managed", str(ctx.exception))

        # Fail-before-write: command intact, no skills, no rules, no lock
        self.assertEqual(
            proj_cmd.read_text(encoding="utf-8"), original,
            "Existing project command must be untouched after failed sync",
        )
        self.assertFalse(
            (repo / ".cursor" / "skills").exists(),
            "Failed sync must not write skills before the command collision",
        )
        self.assertFalse(
            (repo / _RULES_REL).exists(),
            "Failed sync must not write the rules .mdc",
        )
        self.assertFalse(
            (repo / ".illuminate").exists(),
            "Failed sync must not write a lock",
        )

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
        self.assertIn(_RULES_REL, managed)
        self.assertTrue(any(m.startswith(".cursor/skills/") for m in managed))
        self.assertTrue(any(m.startswith(".cursor/commands/") for m in managed))
        # Top-level contract keys
        self.assertIn("skills", lock)
        self.assertIn("commands", lock)
        self.assertIn("rules_md_hash", lock)
        self.assertIn("agents_compat", lock)
        self.assertFalse(lock["agents_compat"])

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
        # Rules .mdc removed (default mode never touches AGENTS.md)
        self.assertFalse((repo / _RULES_REL).exists())
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

        self.assertFalse(result["rules_modified"],
                         "Second sync must not modify the rules .mdc")
        second_lock = json.loads(
            (repo / ".illuminate" / "cursor-lock.json").read_text(encoding="utf-8")
        )
        first = json.loads(first_lock)
        # All determinable fields stay byte-stable; only created_at may differ
        for key in ("managed_artifacts", "skills", "commands", "rules_md_hash",
                    "exposed_skills", "selection", "capabilities", "pack",
                    "agents_compat"):
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

    def test_check_detects_removed_rules_mdc(self):
        repo = self._make_repo()
        sync_cursor(CORE_PACK, repo)
        (repo / _RULES_REL).unlink()

        ok, issues = check_sync(CORE_PACK, repo)
        self.assertFalse(ok)
        self.assertTrue(any("not found" in i for i in issues), issues)

    def test_check_detects_modified_rules_mdc(self):
        repo = self._make_repo()
        sync_cursor(CORE_PACK, repo)
        rules_path = repo / _RULES_REL
        text = rules_path.read_text(encoding="utf-8")
        rules_path.write_text(text.replace("Synchronized skills:", "Synchronized skillz:"),
                              encoding="utf-8")

        ok, issues = check_sync(CORE_PACK, repo)
        self.assertFalse(ok)
        self.assertTrue(any("hash mismatch" in i for i in issues), issues)

    def test_check_detects_missing_rules_mdc(self):
        repo = self._make_repo()
        sync_cursor(CORE_PACK, repo)
        (repo / _RULES_REL).unlink()

        ok, issues = check_sync(CORE_PACK, repo)
        self.assertFalse(ok)
        self.assertTrue(any(_RULES_REL in i for i in issues), issues)

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

    def test_clean_preserves_project_agents_md(self):
        """In default mode clean must never touch the root AGENTS.md, even if
        the lock does not reference a block."""
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
        self.assertNotIn("AGENTS", str(result.get("removed_artifacts")))

    def test_clean_removes_empty_cursor_dirs(self):
        repo = self._make_repo()
        sync_cursor(CORE_PACK, repo, skill_filter=["illuminate.record-knowledge"])
        # Only one command file; clean removes skills/commands and .cursor
        clean_sync(repo)

        self.assertFalse((repo / ".cursor").exists(),
                         "Empty .cursor directory should be cleaned up")

    # ── Cross-harness independence ──

    def test_codex_and_cursor_use_independent_skill_lists(self):
        """Cursor uses a dedicated .mdc, so Codex and Cursor choosing different
        skills do not overwrite each other."""
        repo = self._make_repo()
        agents_path = repo / "AGENTS.md"
        agents_path.write_text("# Project\n\nUser content.\n", encoding="utf-8")

        sync_codex_fn(CORE_PACK, repo, skill_filter=["illuminate.layer-debug"])
        sync_cursor(CORE_PACK, repo, skill_filter=["illuminate.record-knowledge"])

        # Codex AGENTS block carries filter A.
        agents_content = agents_path.read_text(encoding="utf-8")
        self.assertIn("# Project", agents_content)
        self.assertIn("User content.", agents_content)
        self.assertIn("Synchronized skills: illuminate.layer-debug", agents_content)
        # Cursor .mdc carries filter B.
        mdc_text = (repo / _RULES_REL).read_text(encoding="utf-8")
        self.assertIn("Synchronized skills: illuminate.record-knowledge", mdc_text)
        self.assertNotIn("illuminate.layer-debug", mdc_text)

        # Both checks pass independently.
        ok, issues = check_sync(CORE_PACK, repo)
        self.assertTrue(ok, f"Cursor check should pass: {issues}")
        ok, issues = check_codex_sync(CORE_PACK, repo)
        self.assertTrue(ok, f"Codex check should pass: {issues}")

    def test_clean_cursor_preserves_codex_agents_block(self):
        """Cleaning Cursor must not remove the Codex AGENTS.md block."""
        repo = self._make_repo()
        agents_path = repo / "AGENTS.md"
        agents_path.write_text("# Project\n", encoding="utf-8")

        sync_codex_fn(CORE_PACK, repo)
        sync_cursor(CORE_PACK, repo)
        self.assertIn(_BEGIN_MARKER, agents_path.read_text(encoding="utf-8"))

        clean_sync(repo)

        # Codex block survives Cursor clean; Codex check still passes.
        self.assertIn(_BEGIN_MARKER, agents_path.read_text(encoding="utf-8"))
        ok, issues = check_codex_sync(CORE_PACK, repo)
        self.assertTrue(ok, f"Codex check should pass after Cursor clean: {issues}")

    # ── agents_compat mode ──

    def test_agents_compat_merges_into_agents_md(self):
        repo = self._make_repo()
        agents_path = repo / "AGENTS.md"
        agents_path.write_text("# My Project\n\nCustom rules here.\n", encoding="utf-8")

        result = sync_cursor(CORE_PACK, repo, agents_compat=True)

        content = agents_path.read_text(encoding="utf-8")
        self.assertIn("# My Project", content)
        self.assertIn("Custom rules here.", content)
        self.assertIn(_BEGIN_MARKER, content)
        self.assertIn(_END_MARKER, content)
        # No dedicated .mdc in compat mode.
        self.assertFalse((repo / _RULES_REL).exists())
        # Lock records compat mode.
        lock = json.loads((repo / ".illuminate" / "cursor-lock.json").read_text(encoding="utf-8"))
        self.assertTrue(lock["agents_compat"])
        self.assertIn("agents_md_hash", lock)
        # Check follows the same path.
        ok, issues = check_sync(CORE_PACK, repo)
        self.assertTrue(ok, f"Compat check should pass: {issues}")

        # Clean in compat mode removes the AGENTS block but preserves project content.
        result = clean_sync(repo)
        after = agents_path.read_text(encoding="utf-8")
        self.assertNotIn(_BEGIN_MARKER, after)
        self.assertIn("# My Project", after)
        self.assertIn("Custom rules here.", after)

    def test_agents_compat_check_detects_modified_block(self):
        repo = self._make_repo()
        sync_cursor(CORE_PACK, repo, agents_compat=True)
        agents_path = repo / "AGENTS.md"
        content = agents_path.read_text(encoding="utf-8")
        agents_path.write_text(
            content.replace("Synchronized skills:", "Synchronized skillz:"),
            encoding="utf-8",
        )

        ok, issues = check_sync(CORE_PACK, repo)
        self.assertFalse(ok)
        self.assertTrue(any("hash mismatch" in i for i in issues), issues)

    def test_agents_compat_does_not_remove_codex_block_clean(self):
        """Compat-mode Cursor clean removes only its own block content when
        Codex also writes to the same AGENTS.md."""
        repo = self._make_repo()
        agents_path = repo / "AGENTS.md"
        agents_path.write_text("# Project\n", encoding="utf-8")

        sync_codex_fn(CORE_PACK, repo)
        sync_cursor(CORE_PACK, repo, agents_compat=True)
        self.assertEqual(agents_path.read_text(encoding="utf-8").count(_BEGIN_MARKER), 1)

        clean_sync(repo)
        self.assertNotIn(_BEGIN_MARKER, agents_path.read_text(encoding="utf-8"))

    # ── Doctor (read-only) ──

    def test_doctor_healthy_after_sync(self):
        repo = self._make_repo()
        sync_cursor(CORE_PACK, repo)

        report = doctor_sync(repo)
        self.assertTrue(report["lock_exists"])
        self.assertEqual(report["lock_errors"], [])
        self.assertEqual(report["mode"], "mdc")
        self.assertTrue(report["rules"]["exists"])
        self.assertTrue(report["rules"]["hash_matches"])
        self.assertEqual(report["skills"]["missing"], [])
        self.assertEqual(report["skills"]["hash_mismatch"], [])
        self.assertEqual(report["commands"]["missing"], [])
        self.assertEqual(report["commands"]["hash_mismatch"], [])
        self.assertEqual(report["errors"], [])

    def test_doctor_detects_missing_rules_mdc(self):
        repo = self._make_repo()
        sync_cursor(CORE_PACK, repo)
        (repo / _RULES_REL).unlink()

        report = doctor_sync(repo)
        self.assertTrue(report["lock_exists"])
        self.assertFalse(report["rules"]["exists"])
        self.assertFalse(report["rules"]["hash_matches"])

    def test_doctor_reports_missing_lock(self):
        repo = self._make_repo()
        report = doctor_sync(repo)
        self.assertFalse(report["lock_exists"])
        self.assertNotEqual(report["errors"], [])

    def test_doctor_never_writes_files(self):
        repo = self._make_repo()
        sync_cursor(CORE_PACK, repo)
        before = sorted(p.relative_to(repo).as_posix() for p in repo.rglob("*") if p.is_file())

        doctor_sync(repo)

        after = sorted(p.relative_to(repo).as_posix() for p in repo.rglob("*") if p.is_file())
        self.assertEqual(before, after, "Doctor must not modify the repo")

    # ── Empty skill filter ──

    def test_empty_skill_filter_raises(self):
        repo = self._make_repo()
        with self.assertRaises(ValueError):
            sync_cursor(CORE_PACK, repo, skill_filter=[])

    # ── Fail-before-write on stale-deletion targets (P0) ──

    def test_stale_command_readonly_fails_before_write(self):
        """A stale managed command that is read-only must fail the sync before
        any write, so the newly-exposed skill is not written."""
        repo = self._make_repo()
        sync_cursor(CORE_PACK, repo, skill_filter=["illuminate.record-knowledge"])
        stale_cmd = repo / ".cursor" / "commands" / "record-knowledge.md"
        self.assertTrue(stale_cmd.exists())
        _set_readonly(stale_cmd)
        try:
            with self.assertRaises(ValueError):
                sync_cursor(CORE_PACK, repo, skill_filter=["illuminate.layer-debug"])
            self.assertFalse(
                (repo / ".cursor" / "skills" / "layer-debug").exists(),
                "Fail-before-write: layer-debug must not be written when a "
                "stale command cannot be deleted",
            )
        finally:
            _make_writable(stale_cmd)

    def test_stale_skill_readonly_fails_before_write(self):
        """A stale managed skill whose file is read-only must fail the sync
        before any write."""
        repo = self._make_repo()
        sync_cursor(CORE_PACK, repo, skill_filter=["illuminate.perf-profile"])
        stale_file = repo / ".cursor" / "skills" / "perf-profile" / "SKILL.md"
        self.assertTrue(stale_file.exists())
        _set_readonly(stale_file)
        try:
            with self.assertRaises(ValueError):
                sync_cursor(CORE_PACK, repo, skill_filter=["illuminate.layer-debug"])
            self.assertFalse(
                (repo / ".cursor" / "skills" / "layer-debug").exists(),
                "Fail-before-write: layer-debug must not be written when a "
                "stale skill cannot be deleted",
            )
        finally:
            _make_writable(stale_file)

    # ── Fail-before-write on existing read-only target files (P1) ──

    def test_existing_rules_mdc_readonly_fails_before_write(self):
        """An existing (read-only) rules .mdc must fail the sync in preflight,
        before the stale command removal in Phase 2."""
        repo = self._make_repo()
        sync_cursor(CORE_PACK, repo)
        rules_path = repo / _RULES_REL
        self.assertTrue(rules_path.exists())
        _set_readonly(rules_path)
        try:
            with self.assertRaises(ValueError):
                sync_cursor(CORE_PACK, repo, skill_filter=["illuminate.layer-debug"])
            self.assertTrue(
                (repo / ".cursor" / "commands" / "record-knowledge.md").exists(),
                "Fail-before-write: stale command must not be removed when the "
                "rules file is read-only",
            )
        finally:
            _make_writable(rules_path)

    def test_existing_agents_md_readonly_fails_before_write(self):
        """In compat mode an existing read-only AGENTS.md must fail before any
        write."""
        repo = self._make_repo()
        sync_cursor(
            CORE_PACK, repo, agents_compat=True,
            skill_filter=["illuminate.record-knowledge"],
        )
        agents = repo / "AGENTS.md"
        _set_readonly(agents)
        try:
            with self.assertRaises(ValueError):
                sync_cursor(
                    CORE_PACK, repo, agents_compat=True,
                    skill_filter=["illuminate.layer-debug"],
                )
            self.assertFalse(
                (repo / ".cursor" / "skills" / "layer-debug").exists(),
                "Fail-before-write: layer-debug must not be written when "
                "AGENTS.md is read-only",
            )
        finally:
            _make_writable(agents)

    # ── Clean without lock keeps rules dir (P2) ──

    def test_clean_without_lock_keeps_rules_dir(self):
        """Without a lock, clean must not rmtree the rules directory (same rule
        as skills/commands)."""
        repo = self._make_repo()
        sync_cursor(CORE_PACK, repo)
        rules_dir = repo / ".cursor" / "rules" / "illuminate"
        lock = repo / ".illuminate" / "cursor-lock.json"
        lock.unlink()

        clean_sync(repo)

        self.assertTrue(
            rules_dir.exists(),
            "Clean without a lock must not rmtree the rules directory",
        )
        self.assertTrue((rules_dir / "core.mdc").exists())

    # ── compat -> default switch: AGENTS block residue (P2) ──

    def test_compat_to_default_switch_removes_own_agents_block(self):
        """Switching from agents_compat to default must remove the AGENTS block
        we previously wrote, so no residue is left for clean to trip over."""
        repo = self._make_repo()
        agents_path = repo / "AGENTS.md"
        agents_path.write_text("# Project\n", encoding="utf-8")
        sync_cursor(CORE_PACK, repo, agents_compat=True)
        self.assertIn(_BEGIN_MARKER, agents_path.read_text(encoding="utf-8"))

        sync_cursor(CORE_PACK, repo)
        content = agents_path.read_text(encoding="utf-8")
        self.assertNotIn(_BEGIN_MARKER, content)
        self.assertIn("# Project", content)
        # The .mdc was written in default mode.
        self.assertTrue((repo / _RULES_REL).exists())

        clean_sync(repo)
        self.assertNotIn(
            _BEGIN_MARKER, agents_path.read_text(encoding="utf-8"),
            "Clean after switch must not leave a stale AGENTS block",
        )

    def test_clean_default_removes_own_agents_block_via_hash(self):
        """If a default-mode lock still records agents_md_hash (defensive), clean
        removes our AGENTS block only when the file hash matches."""
        repo = self._make_repo()
        agents_path = repo / "AGENTS.md"
        agents_path.write_text("# Project\n", encoding="utf-8")
        sync_cursor(CORE_PACK, repo, agents_compat=True)
        lock = json.loads(
            (repo / ".illuminate" / "cursor-lock.json").read_text(encoding="utf-8")
        )
        lock["agents_compat"] = False  # default mode, but keep the hash record
        (repo / ".illuminate" / "cursor-lock.json").write_text(
            json.dumps(lock), encoding="utf-8"
        )
        self.assertIn(_BEGIN_MARKER, agents_path.read_text(encoding="utf-8"))

        clean_sync(repo)

        content = agents_path.read_text(encoding="utf-8")
        self.assertNotIn(_BEGIN_MARKER, content)
        self.assertIn("# Project", content)

    def test_clean_default_preserves_modified_agents_block(self):
        """When the AGENTS.md no longer matches the lock hash (user/Codex
        modified it), clean must NOT delete the block."""
        repo = self._make_repo()
        agents_path = repo / "AGENTS.md"
        agents_path.write_text("# Project\n", encoding="utf-8")
        sync_cursor(CORE_PACK, repo, agents_compat=True)
        content = agents_path.read_text(encoding="utf-8")
        agents_path.write_text(
            content.replace("Synchronized skills:", "Synchronized skillz:"),
            encoding="utf-8",
        )
        lock = json.loads(
            (repo / ".illuminate" / "cursor-lock.json").read_text(encoding="utf-8")
        )
        lock["agents_compat"] = False
        (repo / ".illuminate" / "cursor-lock.json").write_text(
            json.dumps(lock), encoding="utf-8"
        )

        clean_sync(repo)

        self.assertIn(
            _BEGIN_MARKER, agents_path.read_text(encoding="utf-8"),
            "A block modified since our sync must not be deleted",
        )

    # ── compat -> default lock idempotence (P2) ──

    def test_compat_to_default_switch_is_idempotent_in_lock(self):
        """After a compat -> default switch the lock flips agents_compat, clears
        agents_md_hash, keeps rules_md_hash, and check passes."""
        repo = self._make_repo()
        sync_cursor(CORE_PACK, repo, agents_compat=True)
        lock1 = json.loads(
            (repo / ".illuminate" / "cursor-lock.json").read_text(encoding="utf-8")
        )
        self.assertTrue(lock1["agents_compat"])
        self.assertIn("agents_md_hash", lock1)

        sync_cursor(CORE_PACK, repo)

        lock2 = json.loads(
            (repo / ".illuminate" / "cursor-lock.json").read_text(encoding="utf-8")
        )
        self.assertFalse(lock2["agents_compat"])
        self.assertNotIn("agents_md_hash", lock2)
        self.assertIn("rules_md_hash", lock2)
        self.assertNotIn(
            _BEGIN_MARKER, (repo / "AGENTS.md").read_text(encoding="utf-8")
        )
        ok, issues = check_sync(CORE_PACK, repo)
        self.assertTrue(ok, f"Check should pass after compat->default: {issues}")


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
            pack=str(CORE_PACK), repo=str(self._repo()), skill=None, agents_compat=False
        )
        self.assertEqual(cli._cmd_sync_cursor(args), 0)

    def test_cmd_sync_cursor_missing_pack_returns_1(self):
        args = SimpleNamespace(
            pack=str(self.tmpdir / "nope"), repo=str(self._repo()),
            skill=None, agents_compat=False,
        )
        self.assertEqual(cli._cmd_sync_cursor(args), 1)

    def test_cmd_sync_cursor_collision_returns_1(self):
        repo = self._repo()
        proj = repo / ".cursor" / "skills" / "layer-debug"
        proj.mkdir(parents=True)
        proj.joinpath("SKILL.md").write_text("# mine\n", encoding="utf-8")
        args = SimpleNamespace(pack=str(CORE_PACK), repo=str(repo), skill=None,
                               agents_compat=False)
        self.assertEqual(cli._cmd_sync_cursor(args), 1)

    def test_cmd_sync_cursor_agents_compat(self):
        repo = self._repo()
        args = SimpleNamespace(pack=str(CORE_PACK), repo=str(repo), skill=None,
                               agents_compat=True)
        self.assertEqual(cli._cmd_sync_cursor(args), 0)
        self.assertIn(_BEGIN_MARKER, (repo / "AGENTS.md").read_text(encoding="utf-8"))
        self.assertFalse((repo / _RULES_REL).exists())

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

    def test_cmd_sync_doctor_cursor_route(self):
        repo = self._repo()
        args = SimpleNamespace(repo=str(repo), harness="cursor")
        # No sync yet -> problems.
        self.assertEqual(cli._cmd_sync_doctor(args), 1)
        sync_cursor(CORE_PACK, repo)
        # Healthy -> 0.
        self.assertEqual(cli._cmd_sync_doctor(args), 0)
        (repo / _RULES_REL).unlink()
        # Missing rules file -> 1.
        self.assertEqual(cli._cmd_sync_doctor(args), 1)


if __name__ == "__main__":
    unittest.main()
