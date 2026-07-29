"""Tests for knowledge store (pull/status/push)."""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from illuminate.knowledge_store import (
    knowledge_pull,
    knowledge_status,
    knowledge_push,
)

REPO_ROOT = Path(__file__).parent.parent


def _create_knowledge_file(root: Path, subdir: str, rel: str, content: str = "") -> Path:
    """Create a file under root/docs/<subdir>/ and return its path."""
    fpath = root / "docs" / subdir / rel
    fpath.parent.mkdir(parents=True, exist_ok=True)
    fpath.write_text(content or f"# {rel}\n\nContent for {rel}\n", encoding="utf-8")
    return fpath


class TestKnowledgeStore(unittest.TestCase):

    def setUp(self):
        self.repo = Path(tempfile.mkdtemp())
        self.store = Path(tempfile.mkdtemp())

        # Init git for HEAD resolution
        import subprocess
        try:
            subprocess.run(["git", "init"], cwd=str(self.repo),
                           capture_output=True, check=False)
            subprocess.run(["git", "config", "user.email", "test@test.com"],
                           cwd=str(self.repo), capture_output=True, check=False)
            subprocess.run(["git", "config", "user.name", "Test"],
                           cwd=str(self.repo), capture_output=True, check=False)
        except Exception:
            pass

    def _git_commit(self):
        import subprocess
        try:
            subprocess.run(["git", "add", "-A"], cwd=str(self.repo),
                           capture_output=True, check=False)
            subprocess.run(["git", "commit", "-m", "test"],
                           cwd=str(self.repo), capture_output=True, check=False)
        except Exception:
            pass

    # ── Pull ──

    def test_pull_creates_store_structure(self):
        _create_knowledge_file(self.repo, "Guidelines", "paths.md", "# Paths\n")
        result = knowledge_pull(self.repo, store=self.store)

        store_dir = self.store / "projects" / result["project_id"]
        self.assertTrue((store_dir / "project.json").exists())
        self.assertTrue((store_dir / "knowledge-lock.json").exists())
        self.assertTrue((store_dir / "documents" / "Guidelines" / "paths.md").exists())

    def test_pull_new_file(self):
        _create_knowledge_file(self.repo, "Framework", "module-map.md")
        result = knowledge_pull(self.repo, store=self.store)
        self.assertIn("Framework/module-map.md", result["new"])
        self.assertIn("Framework/module-map.md", result["pulled"])

    def test_pull_modified_file(self):
        _create_knowledge_file(self.repo, "Framework", "arch.md", "v1")
        knowledge_pull(self.repo, store=self.store)
        _create_knowledge_file(self.repo, "Framework", "arch.md", "v2")
        result = knowledge_pull(self.repo, store=self.store)
        self.assertIn("Framework/arch.md", result["modified"])
        self.assertIn("Framework/arch.md", result["pulled"])

    def test_pull_detects_conflict(self):
        _create_knowledge_file(self.repo, "Guidelines", "shared.md", "v1")
        result = knowledge_pull(self.repo, store=self.store)
        project_id = result["project_id"]

        # Modify in both places
        _create_knowledge_file(self.repo, "Guidelines", "shared.md", "project-v2")
        store_file = self.store / "projects" / project_id / "documents" / "Guidelines" / "shared.md"
        store_file.parent.mkdir(parents=True, exist_ok=True)
        store_file.write_text("store-v2", encoding="utf-8")

        result = knowledge_pull(self.repo, store=self.store)
        self.assertIn("Guidelines/shared.md", result["conflicted"])
        self.assertNotIn("Guidelines/shared.md", result["pulled"])

    def test_pull_idempotent(self):
        _create_knowledge_file(self.repo, "Guidelines", "doc.md")
        knowledge_pull(self.repo, store=self.store)
        result = knowledge_pull(self.repo, store=self.store)
        self.assertEqual(len(result["pulled"]), 0,
                         "Second pull should have no changes")

    # ── Status ──

    def test_status_shows_new(self):
        _create_knowledge_file(self.repo, "Framework", "new-doc.md")
        result = knowledge_status(self.repo, store=self.store)
        self.assertIn("Framework/new-doc.md", result["new"])

    def test_status_shows_modified(self):
        _create_knowledge_file(self.repo, "Guidelines", "mod.md", "v1")
        knowledge_pull(self.repo, store=self.store)
        _create_knowledge_file(self.repo, "Guidelines", "mod.md", "v2")
        result = knowledge_status(self.repo, store=self.store)
        self.assertIn("Guidelines/mod.md", result["modified"])

    def test_status_shows_deleted(self):
        _create_knowledge_file(self.repo, "Framework", "gone.md")
        knowledge_pull(self.repo, store=self.store)
        (self.repo / "docs" / "Framework" / "gone.md").unlink()
        result = knowledge_status(self.repo, store=self.store)
        self.assertIn("Framework/gone.md", result["deleted"])

    def test_status_shows_conflict(self):
        _create_knowledge_file(self.repo, "Framework", "c.md", "v1")
        result = knowledge_pull(self.repo, store=self.store)
        project_id = result["project_id"]
        _create_knowledge_file(self.repo, "Framework", "c.md", "project-v2")
        store_file = self.store / "projects" / project_id / "documents" / "Framework" / "c.md"
        store_file.parent.mkdir(parents=True, exist_ok=True)
        store_file.write_text("store-v2", encoding="utf-8")
        result = knowledge_status(self.repo, store=self.store)
        self.assertIn("Framework/c.md", result["conflicted"])
        self.assertTrue(result["has_conflicts"])

    def test_status_shows_synced(self):
        _create_knowledge_file(self.repo, "Guidelines", "synced.md")
        knowledge_pull(self.repo, store=self.store)
        result = knowledge_status(self.repo, store=self.store)
        self.assertIn("Guidelines/synced.md", result["synced"])

    # ── Push ──

    def test_push_restores_deleted_file(self):
        _create_knowledge_file(self.repo, "Guidelines", "backup.md", "important")
        knowledge_pull(self.repo, store=self.store)
        (self.repo / "docs" / "Guidelines" / "backup.md").unlink()

        result = knowledge_push(self.repo, store=self.store)
        self.assertIn("Guidelines/backup.md", result["pushed"])
        restored = self.repo / "docs" / "Guidelines" / "backup.md"
        self.assertTrue(restored.exists())
        self.assertEqual(restored.read_text(encoding="utf-8"), "important")

    def test_push_refuses_conflicts(self):
        _create_knowledge_file(self.repo, "Framework", "c.md", "v1")
        result = knowledge_pull(self.repo, store=self.store)
        project_id = result["project_id"]
        _create_knowledge_file(self.repo, "Framework", "c.md", "project-v2")
        store_file = self.store / "projects" / project_id / "documents" / "Framework" / "c.md"
        store_file.parent.mkdir(parents=True, exist_ok=True)
        store_file.write_text("store-v2", encoding="utf-8")

        result = knowledge_push(self.repo, store=self.store)
        self.assertIn("error", result)

    def test_push_force_overrides_conflicts(self):
        _create_knowledge_file(self.repo, "Framework", "c.md", "v1")
        result = knowledge_pull(self.repo, store=self.store)
        project_id = result["project_id"]
        _create_knowledge_file(self.repo, "Framework", "c.md", "project-v2")
        store_file = self.store / "projects" / project_id / "documents" / "Framework" / "c.md"
        store_file.parent.mkdir(parents=True, exist_ok=True)
        store_file.write_text("store-version", encoding="utf-8")

        result = knowledge_push(self.repo, store=self.store, force=True)
        self.assertNotIn("error", result)
        restored = self.repo / "docs" / "Framework" / "c.md"
        self.assertEqual(restored.read_text(encoding="utf-8"), "store-version")


if __name__ == "__main__":
    unittest.main()
