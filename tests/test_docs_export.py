import json
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from illuminate.cli import _build_parser, _cmd_docs_export_human, _cmd_docs_lint_human
from illuminate.docs_export import DocsExportError, export_human
from illuminate.docs_lint import lint_human


class TestDocsExport(unittest.TestCase):
    def _source(self, root: Path) -> Path:
        source = root / "knowledge"
        (source / "30-modules" / "demo" / "verification").mkdir(parents=True)
        (source / "40-journeys").mkdir(parents=True)
        (source / "20-components" / "service").mkdir(parents=True)
        (source / "README-HUMAN.md").write_text(
            "# Human docs\n\n[Module](30-modules/demo/README.md)\n"
            "[Component](20-components/service/README.md)\n",
            encoding="utf-8",
        )
        (source / "30-modules" / "README.md").write_text(
            "# Modules\n\n[Demo](demo/README.md)\n", encoding="utf-8"
        )
        (source / "30-modules" / "demo" / "README.md").write_text(
            "# Demo\n\n[Audit](verification/claims.yaml)\n",
            encoding="utf-8",
        )
        (source / "30-modules" / "demo" / "verification" / "claims.yaml").write_text(
            "- id: CL-DEMO\n", encoding="utf-8"
        )
        (source / "40-journeys" / "README.md").write_text(
            "# Journeys\n\n[Start](01-start.md)\n", encoding="utf-8"
        )
        (source / "40-journeys" / "01-start.md").write_text(
            "# Start\n\n[Demo](../30-modules/demo/README.md)\n", encoding="utf-8"
        )
        (source / "20-components" / "service" / "README.md").write_text(
            "# Service\n", encoding="utf-8"
        )
        return source

    def test_copies_configured_files_without_rewriting_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._source(root)
            output = root / "export"
            result = export_human(source, output)

            self.assertEqual(result["file_count"], 6)
            self.assertTrue((output / "README.md").exists())
            self.assertFalse((output / "README-HUMAN.md").exists())
            self.assertFalse((output / "30-modules" / "demo" / "verification").exists())
            original = (source / "30-modules" / "demo" / "README.md").read_text(encoding="utf-8")
            exported = (output / "30-modules" / "demo" / "README.md").read_text(encoding="utf-8")
            self.assertEqual(exported, original)
            self.assertEqual(result["files"].count("README.md"), 1)

    def test_json_config_controls_include_exclude_and_readme(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._source(root)
            config = root / "human-docs.json"
            config.write_text(json.dumps({
                "include": ["README-HUMAN.md", "30-modules/*/README.md"],
                "exclude": [],
                "readme": "README-HUMAN.md",
            }), encoding="utf-8")
            output = root / "export"
            result = export_human(source, output, config_path=config)
            self.assertEqual(result["file_count"], 2)
            self.assertTrue((output / "README.md").exists())
            self.assertTrue((output / "30-modules" / "demo" / "README.md").exists())
            self.assertFalse((output / "40-journeys").exists())

    def test_rejects_destination_collision(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._source(root)
            (source / "README.md").write_text("# conflicting root\n", encoding="utf-8")
            config = root / "human-docs.json"
            output = root / "export"
            output.mkdir()
            previous = output / "previous.md"
            previous.write_text("previous export", encoding="utf-8")
            config.write_text(json.dumps({
                "include": ["README-HUMAN.md", "README.md"],
                "exclude": [],
                "readme": "README-HUMAN.md",
            }), encoding="utf-8")
            with self.assertRaises(DocsExportError):
                export_human(source, output, config_path=config, force=True)
            self.assertEqual(previous.read_text(encoding="utf-8"), "previous export")

    def test_rejects_non_empty_output_without_force(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._source(root)
            output = root / "export"
            output.mkdir()
            (output / "existing.md").write_text("keep", encoding="utf-8")
            with self.assertRaises(DocsExportError):
                export_human(source, output)
            export_human(source, output, force=True)
            self.assertFalse((output / "existing.md").exists())

    def test_rejects_output_inside_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._source(root)
            with self.assertRaises(DocsExportError):
                export_human(source, source / "dist")

    def test_cli_parser_routes_export_and_lint_arguments(self):
        parser = _build_parser()
        export_args = parser.parse_args([
            "docs", "export-human",
            "--source", "source",
            "--output", "output",
            "--config", "human-docs.json",
            "--force",
        ])
        self.assertEqual(export_args.docs_command, "export-human")
        self.assertEqual(export_args.config, "human-docs.json")
        lint_args = parser.parse_args([
            "docs", "lint-human", "--source", "source", "--all-markdown"
        ])
        self.assertEqual(lint_args.docs_command, "lint-human")
        self.assertTrue(lint_args.all_markdown)
        knowledge_args = parser.parse_args([
            "docs", "lint-knowledge", "--source", "docs"
        ])
        self.assertEqual(knowledge_args.docs_command, "lint-knowledge")

    def test_cli_handler_exports_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._source(root)
            output = root / "export"
            result = _cmd_docs_export_human(Namespace(
                source=str(source), output=str(output), config=None, force=False,
            ))
            self.assertEqual(result, 0)
            self.assertTrue((output / "README.md").exists())


class TestHumanDocsLint(unittest.TestCase):
    def _clean_source(self, root: Path) -> Path:
        source = root / "knowledge"
        (source / "30-modules" / "demo").mkdir(parents=True)
        (source / "40-journeys").mkdir(parents=True)
        (source / "README-HUMAN.md").write_text(
            "# Human\n\n[Guide](40-journeys/01.md)\n", encoding="utf-8"
        )
        sections = [
            "模块定位与边界", "主流程", "参与组件", "失败", "恢复",
            "模块交接", "日志", "当前限制",
        ]
        (source / "30-modules" / "demo" / "README.md").write_text(
            "# Demo\n\n" + "\n".join(f"## {section}" for section in sections),
            encoding="utf-8",
        )
        (source / "40-journeys" / "01.md").write_text(
            "# Journey\n\n见 [Demo](../30-modules/demo/README.md)。\n",
            encoding="utf-8",
        )
        return source

    def test_clean_human_docs_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = self._clean_source(Path(tmp))
            self.assertEqual(lint_human(source), [])

    def test_lint_rejects_meta_term_and_forbidden_link(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = self._clean_source(Path(tmp))
            module = source / "30-modules" / "demo" / "README.md"
            module.write_text(
                module.read_text(encoding="utf-8")
                + "\nCL-DEMO [audit](verification/claims.yaml)\n",
                encoding="utf-8",
            )
            errors = lint_human(source)
            self.assertTrue(any("forbidden human-doc term" in error for error in errors))
            self.assertTrue(any("excluded material" in error for error in errors))

    def test_lint_requires_an_actual_module_readme_link(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = self._clean_source(Path(tmp))
            guide = source / "40-journeys" / "01.md"
            guide.write_text("# Journey\n\nSee the 30-modules/ directory.\n", encoding="utf-8")
            errors = lint_human(source)
            self.assertTrue(any("existing module README" in error for error in errors))

    def test_lint_checks_markdown_heading_fragments(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = self._clean_source(Path(tmp))
            guide = source / "40-journeys" / "01.md"
            guide.write_text(
                "# Journey\n\n[Demo](../30-modules/demo/README.md#missing-section)\n",
                encoding="utf-8",
            )
            errors = lint_human(source)
            self.assertTrue(any("missing heading anchor" in error for error in errors))

    def test_cli_handler_returns_failure_for_invalid_human_docs(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = self._clean_source(Path(tmp))
            module = source / "30-modules" / "demo" / "README.md"
            module.write_text(module.read_text(encoding="utf-8") + "\nP0\n", encoding="utf-8")
            result = _cmd_docs_lint_human(Namespace(
                source=str(source), config=None, all_markdown=False,
            ))
            self.assertEqual(result, 1)

    def test_flat_classified_layout_uses_flat_module_documents(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "docs"
            (source / "20-components").mkdir(parents=True)
            (source / "30-modules").mkdir()
            (source / "40-journeys").mkdir()
            (source / "README-HUMAN.md").write_text(
                "# Human\n\n[Module](30-modules/demo.md)\n", encoding="utf-8"
            )
            sections = [
                "模块定位与边界", "主流程", "参与组件", "失败", "恢复",
                "模块交接", "日志", "当前限制",
            ]
            (source / "30-modules" / "demo.md").write_text(
                "# Demo\n\n" + "\n".join(f"## {section}" for section in sections),
                encoding="utf-8",
            )
            (source / "40-journeys" / "download.md").write_text(
                "# Download\n\n[Demo](../30-modules/demo.md)\n", encoding="utf-8"
            )
            (source / "20-components" / "service.md").write_text(
                "# Service\n", encoding="utf-8"
            )
            (source / "human-docs.json").write_text(json.dumps({
                "layout": "flat-classified",
                "human_roots": {
                    "components": "20-components",
                    "modules": "30-modules",
                    "journeys": "40-journeys",
                },
                "metadata_root": "70-metadata",
                "require_manifests": True,
                "doc_refs": "root-relative",
                "include": [
                    "README-HUMAN.md",
                    "20-components/*.md",
                    "30-modules/*.md",
                    "40-journeys/*.md",
                ],
                "exclude": [],
                "readme": "README-HUMAN.md",
            }), encoding="utf-8")
            self.assertEqual(lint_human(source), [])


if __name__ == "__main__":
    unittest.main()
