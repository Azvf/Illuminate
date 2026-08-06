"""Tests for the knowledge map generator (illuminate.knowledge_router)."""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from illuminate.knowledge_router import build_knowledge_map, write_knowledge_map


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


class TestKnowledgeRouter(unittest.TestCase):

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def _make_repo(self) -> Path:
        repo = self.tmpdir / "target-repo"
        repo.mkdir(parents=True, exist_ok=True)
        return repo

    def _make_knowledgeable_repo(self) -> Path:
        repo = self._make_repo()
        _write(repo / "docs" / "README-HUMAN.md", "# Human readme\n")
        _write(
            repo / "docs" / "40-journeys" / "bg.md",
            "# Background load\n\n"
            "Loads the [hot-update](docs/30-modules/hot-update.md) module.\n",
        )
        _write(
            repo / "docs" / "70-metadata" / "modules" / "hot-update" / "module.yaml",
            "# module manifest\nid: hot-update\ndocument: 30-modules/hot-update.md\n",
        )
        _write(
            repo / "docs" / "30-modules" / "hot-update.md",
            "# Hot Update\n\n## Overview\n\n## State\n",
        )
        _write(
            repo / "docs" / "70-metadata" / "components" / "bg" / "component.yaml",
            "id: bg-loader\ndocument: 20-components/bg-loader.md\n",
        )
        _write(
            repo / "docs" / "20-components" / "bg-loader.md",
            "# BG Loader\n\n## Lifecycle\n",
        )
        return repo

    def test_builds_map_with_journeys_modules_components(self):
        repo = self._make_knowledgeable_repo()
        text = build_knowledge_map(repo)
        self.assertIsNotNone(text)
        self.assertIn("Entry: docs/README-HUMAN.md", text)
        self.assertIn("## Journeys", text)
        self.assertIn("- Background load", text)
        self.assertIn("Document: docs/40-journeys/bg.md", text)
        self.assertIn("Covers: Loads the [hot-update]", text)
        self.assertIn("Related modules: hot-update.md", text)
        self.assertIn("## Modules", text)
        self.assertIn("- hot-update", text)
        self.assertIn("Sections: Overview、State", text)
        self.assertIn("## Components", text)
        self.assertIn("- bg-loader", text)
        self.assertIn("Sections: Lifecycle", text)

    def test_no_docs_returns_none(self):
        repo = self._make_repo()
        self.assertIsNone(build_knowledge_map(repo))
        dest = repo / "output" / "map.md"
        self.assertIsNone(write_knowledge_map(repo, dest))
        self.assertFalse(dest.exists())

    def test_write_map_creates_dest(self):
        repo = self._make_knowledgeable_repo()
        dest = repo / "docs" / "knowledge-map.md"
        text = write_knowledge_map(repo, dest)
        self.assertIsNotNone(text)
        self.assertTrue(dest.exists())
        self.assertEqual(text, build_knowledge_map(repo))

    def test_missing_document_skips_sections(self):
        repo = self._make_repo()
        _write(
            repo / "docs" / "70-metadata" / "modules" / "ghost" / "module.yaml",
            "id: ghost\ndocument: 30-modules/ghost.md\n",
        )
        text = build_knowledge_map(repo)
        self.assertIsNotNone(text)
        self.assertIn("- ghost", text)
        self.assertNotIn("Sections:", text)

    def test_manifest_missing_document_skips_entry(self):
        repo = self._make_repo()
        _write(
            repo / "docs" / "70-metadata" / "modules" / "ghost" / "module.yaml",
            "id: ghost\n",
        )
        self.assertIsNone(build_knowledge_map(repo))

    def test_manifest_scalars_clean_comment_and_quotes(self):
        repo = self._make_repo()
        _write(
            repo / "docs" / "70-metadata" / "modules" / "hot-update" / "module.yaml",
            'id: hot-update # stable id\ndocument: "30-modules/hot-update.md"\n',
        )
        _write(
            repo / "docs" / "30-modules" / "hot-update.md",
            "# Hot Update\n\n## Overview\n",
        )
        text = build_knowledge_map(repo)
        self.assertIsNotNone(text)
        self.assertIn("- hot-update", text)
        self.assertIn("Document: docs/30-modules/hot-update.md", text)
        self.assertIn("Sections: Overview", text)

    def test_headings_ignore_leading_and_trailing_whitespace(self):
        repo = self._make_repo()
        _write(
            repo / "docs" / "70-metadata" / "modules" / "m" / "module.yaml",
            "id: m\ndocument: 30-modules/m.md\n",
        )
        _write(
            repo / "docs" / "30-modules" / "m.md",
            "# M\n\n##  State  \n",
        )
        text = build_knowledge_map(repo)
        self.assertIsNotNone(text)
        self.assertIn("Sections: State", text)

    def test_empty_docs_dir_returns_none(self):
        repo = self._make_repo()
        (repo / "docs").mkdir(parents=True, exist_ok=True)
        self.assertIsNone(build_knowledge_map(repo))

    def test_journey_backslash_module_links(self):
        repo = self._make_repo()
        _write(
            repo / "docs" / "40-journeys" / "bg.md",
            "# Background\n\nSee [mod](docs/30-modules\\sub\\m.md).\n",
        )
        text = build_knowledge_map(repo)
        self.assertIsNotNone(text)
        self.assertIn("Related modules: sub/m.md", text)

    def test_deterministic_order(self):
        repo = self._make_knowledgeable_repo()
        first = build_knowledge_map(repo)
        second = build_knowledge_map(repo)
        self.assertEqual(first, second)

    def test_invalid_document_paths_skipped(self):
        repo = self._make_repo()
        _write(
            repo / "docs" / "70-metadata" / "modules" / "ok" / "module.yaml",
            "id: ok\ndocument: 30-modules/ok.md\n",
        )
        _write(
            repo / "docs" / "30-modules" / "ok.md",
            "# OK\n\n## Section\n",
        )
        _write(
            repo / "docs" / "70-metadata" / "modules" / "traversal" / "module.yaml",
            "id: traversal\ndocument: ../../outside.md\n",
        )
        _write(
            repo / "docs" / "70-metadata" / "modules" / "abs" / "module.yaml",
            "id: abs\ndocument: /etc/passwd\n",
        )
        _write(
            repo / "docs" / "70-metadata" / "modules" / "wrongroot" / "module.yaml",
            "id: wrongroot\ndocument: 20-components/x.md\n",
        )
        text = build_knowledge_map(repo)
        self.assertIsNotNone(text)
        self.assertIn("- ok", text)
        self.assertIn("Document: docs/30-modules/ok.md", text)
        self.assertNotIn("- traversal", text)
        self.assertNotIn("- abs", text)
        self.assertNotIn("- wrongroot", text)

    def test_glob_indexes_only_expected_manifest(self):
        repo = self._make_repo()
        _write(
            repo / "docs" / "70-metadata" / "modules" / "m" / "module.yaml",
            "id: m\ndocument: 30-modules/m.md\n",
        )
        _write(
            repo / "docs" / "30-modules" / "m.md",
            "# M\n\n## S\n",
        )
        _write(
            repo / "docs" / "70-metadata" / "modules" / "stray" / "notes.yaml",
            "id: stray\ndocument: 30-modules/stray.md\n",
        )
        _write(
            repo / "docs" / "70-metadata" / "components" / "comp" / "notes.yaml",
            "id: comp\ndocument: 20-components/comp.md\n",
        )
        text = build_knowledge_map(repo)
        self.assertIsNotNone(text)
        self.assertIn("- m", text)
        self.assertNotIn("- stray", text)
        self.assertNotIn("- comp", text)

    def test_journey_relative_and_direct_module_links(self):
        repo = self._make_repo()
        _write(
            repo / "docs" / "40-journeys" / "bg.md",
            "# Background\n\n"
            "Relative: [hot-update](../30-modules/hot-update.md)\n"
            "Direct: [other](docs/30-modules/other.md)\n"
            "External: [web](https://example.com/x.md)\n"
            "Anchor: [in](#local)\n"
            "Mail: [mail](mailto:a@b.com)\n",
        )
        text = build_knowledge_map(repo)
        self.assertIsNotNone(text)
        self.assertIn("Related modules: hot-update.md, other.md", text)


if __name__ == "__main__":
    unittest.main()
