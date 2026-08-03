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

    def _flat_root(self, root: Path) -> Path:
        docs = root / "docs"
        for name in ("20-components", "30-modules", "40-journeys"):
            (docs / name).mkdir(parents=True)
        (docs / "30-modules" / "demo.md").write_text(
            "# Demo\n\n## 主流程摘要\n", encoding="utf-8"
        )
        (docs / "20-components" / "service.md").write_text(
            "# Service\n", encoding="utf-8"
        )
        (docs / "40-journeys" / "download.md").write_text(
            "# Download\n", encoding="utf-8"
        )
        metadata = docs / "70-metadata"
        (metadata / "modules" / "demo").mkdir(parents=True)
        (metadata / "components" / "service").mkdir(parents=True)
        (metadata / "modules" / "demo" / "module.yaml").write_text(
            "id: demo\ndocument: 30-modules/demo.md\n", encoding="utf-8"
        )
        (metadata / "components" / "service" / "component.yaml").write_text(
            "id: service\ndocument: 20-components/service.md\n", encoding="utf-8"
        )
        (metadata / "modules" / "demo" / "verification").mkdir()
        (metadata / "modules" / "demo" / "verification" / "claims.yaml").write_text(
            "- id: CL-DEMO-001\n"
            "  doc_refs:\n"
            "    - 30-modules/demo.md#主流程摘要\n",
            encoding="utf-8",
        )
        (docs / "human-docs.json").write_text(
            '{"layout":"flat-classified","require_manifests":true,"include":["README-HUMAN.md","20-components/*.md","30-modules/*.md","40-journeys/*.md"],"exclude":[],"readme":"README-HUMAN.md"}',
            encoding="utf-8",
        )
        return docs

    def test_flat_classified_manifest_owners_and_refs_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(lint_knowledge(self._flat_root(Path(tmp))), [])

    def test_flat_classified_rejects_orphan_and_relative_ref(self):
        with tempfile.TemporaryDirectory() as tmp:
            docs = self._flat_root(Path(tmp))
            (docs / "30-modules" / "orphan.md").write_text("# Orphan\n", encoding="utf-8")
            claims = docs / "70-metadata" / "modules" / "demo" / "verification" / "claims.yaml"
            claims.write_text(
                "- id: CL-DEMO-001\n  doc_refs:\n    - ../../../../30-modules/demo.md\n",
                encoding="utf-8",
            )
            errors = lint_knowledge(docs)
            self.assertTrue(any("orphan human document" in error for error in errors))
            self.assertTrue(any("must be root-relative" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
