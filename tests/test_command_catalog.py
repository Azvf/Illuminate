"""Tests for the doc-related command catalog (command_catalog.py).

These verify the standalone/self-contained contract of the generated command
prompts: finish-task must not reference bound slash commands or skills that may
be absent under a minimal skill filter, and knowledge-status must describe the
correct pull/push direction.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from illuminate.command_catalog import build_command_catalog


class TestCommandCatalog(unittest.TestCase):

    def setUp(self):
        self.catalog = build_command_catalog()

    def test_standalone_commands_have_no_skill(self):
        """finish-task and knowledge-status are standalone: always synced
        regardless of skill selection, so skill_id must be None."""
        self.assertIsNone(self.catalog["finish-task"].skill_id)
        self.assertIsNone(self.catalog["knowledge-status"].skill_id)

    def test_finish_task_does_not_reference_bound_slash_commands(self):
        """finish-task must not reference /record-knowledge or
        /archive-module-doc, since those bound commands/skills may not exist
        under a minimal skill filter."""
        prompt = self.catalog["finish-task"].prompt
        self.assertNotIn("/record-knowledge", prompt)
        self.assertNotIn("/archive-module-doc", prompt)
        self.assertNotIn("`record-knowledge`", prompt)
        self.assertNotIn("`archive-module-doc`", prompt)

    def test_finish_task_describes_direct_archive_actions(self):
        """finish-task must embed direct archive targets rather than delegating
        to bound commands."""
        prompt = self.catalog["finish-task"].prompt
        self.assertIn("20-components", prompt)
        self.assertIn("30-modules", prompt)
        self.assertIn("40-journeys", prompt)
        self.assertIn("70-metadata", prompt)

    def test_finish_task_keeps_independent_cli_example(self):
        """finish-task keeps `illuminate knowledge status` as an example: it is
        an independent CLI command that does not depend on any skill."""
        self.assertIn("illuminate knowledge status --repo .",
                      self.catalog["finish-task"].prompt)

    def test_knowledge_status_describes_push_for_store_updates(self):
        """knowledge-status must map store updates to push (Store -> project),
        not pull."""
        prompt = self.catalog["knowledge-status"].prompt
        self.assertIn("push", prompt)
        self.assertIn("中心 Store 有更新 → 按需 `knowledge push`", prompt)
        self.assertNotIn("中心 Store 有更新，按需拉取", prompt)

    def test_knowledge_status_direction_convention(self):
        """knowledge-status documents pull = project -> Store and
        push = Store -> project."""
        prompt = self.catalog["knowledge-status"].prompt
        self.assertIn("pull` = 项目 → Store", prompt)
        self.assertIn("push` = Store → 项目", prompt)

    def test_knowledge_status_example_uses_push(self):
        """knowledge-status example must use `knowledge push` (Store has the
        newer document to restore), not pull."""
        prompt = self.catalog["knowledge-status"].prompt
        self.assertIn("illuminate knowledge push --repo .", prompt)
        self.assertNotIn("illuminate knowledge pull --repo .", prompt)

    def test_record_knowledge_binding_preserved(self):
        """record-knowledge must stay bound to its skill so it is only synced
        when the skill is exposed."""
        self.assertEqual(self.catalog["record-knowledge"].skill_id,
                         "illuminate.record-knowledge")


if __name__ == "__main__":
    unittest.main()
