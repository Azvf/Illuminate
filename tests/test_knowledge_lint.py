import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from illuminate.knowledge_lint import lint_knowledge


class TestKnowledgeLint(unittest.TestCase):
    def test_doc_refs_and_anchors_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            module = root / "30-modules" / "demo"
            module.mkdir(parents=True)
            (module / "README.md").write_text("# Demo\n\n## 主流程摘要\n", encoding="utf-8")
            (module / "verification").mkdir()
            (module / "verification" / "claims.yaml").write_text(
                "- id: CL-DEMO-001\n"
                "  doc_refs:\n"
                "    - ../README.md#主流程摘要\n",
                encoding="utf-8",
            )
            self.assertEqual(lint_knowledge(root), [])

    def test_missing_refs_and_anchor_are_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            module = root / "30-modules" / "demo" / "verification"
            module.mkdir(parents=True)
            (module.parent / "README.md").write_text("# Demo\n", encoding="utf-8")
            (module / "claims.yaml").write_text(
                "- id: CL-DEMO-001\n"
                "  doc_refs:\n"
                "    - ../README.md#missing\n"
                "- id: CL-DEMO-002\n"
                "  statement: no ref\n",
                encoding="utf-8",
            )
            errors = lint_knowledge(root)
            self.assertTrue(any("missing heading anchor" in e for e in errors))
            self.assertTrue(any("has no doc_refs" in e for e in errors))

    def test_duplicate_ids_are_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = root / "30-modules" / "a" / "verification"
            second = root / "30-modules" / "b" / "verification"
            first.mkdir(parents=True)
            second.mkdir(parents=True)
            content = "- id: DUP-001\n  doc_refs:\n    - ../README.md\n"
            (first / "claims.yaml").write_text(content, encoding="utf-8")
            (second / "gaps.yaml").write_text(content, encoding="utf-8")
            errors = lint_knowledge(root)
            self.assertTrue(any("duplicate id DUP-001" in e for e in errors))


if __name__ == "__main__":
    unittest.main()
