"""Boundary tests for the JSON Schema subset and restricted YAML parsers.

These lock in the fail-closed behaviour: schemas using unsupported keywords
must be rejected, and manifests/metadata using YAML constructs the hand-rolled
parsers cannot interpret must be reported instead of silently ignored. They
also guard against false positives on the existing legal file styles.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from illuminate.document_layout import detect_unsupported_yaml, manifest_fields
from illuminate.jsonschema import SchemaError, validate, validate_schema_keywords
from illuminate.knowledge_lint import lint_knowledge


def _pack_schema():
    import json
    from importlib.resources import files

    resource = files("illuminate").joinpath("schemas/pack.schema.json")
    return json.loads(resource.read_text(encoding="utf-8"))


class TestSchemaKeywordBoundary(unittest.TestCase):
    def test_unsupported_keywords_are_reported(self):
        schema = {
            "type": "object",
            "properties": {"name": {"type": "string", "minLength": 3}},
            "oneOf": [
                {"required": ["a"]},
                {"required": ["b"]},
            ],
            "uniqueItems": True,
            "format": "email",
        }
        found = validate_schema_keywords(schema)
        self.assertTrue(any("minLength" in item for item in found), found)
        self.assertTrue(any("oneOf" in item for item in found), found)
        self.assertTrue(any("uniqueItems" in item for item in found), found)
        self.assertTrue(any("format" in item for item in found), found)

    def test_unsupported_keyword_raises_on_validate(self):
        schema = {"type": "string", "minLength": 3}
        with self.assertRaises(SchemaError):
            validate("ab", schema)

    def test_unsupported_keyword_nested_under_properties(self):
        schema = {"type": "object", "properties": {"n": {"type": "string", "maxLength": 5}}}
        found = validate_schema_keywords(schema)
        self.assertTrue(any("properties.n.maxLength" in item for item in found), found)

    def test_bundled_pack_schema_passes(self):
        schema = _pack_schema()
        self.assertEqual(validate_schema_keywords(schema), [])
        # And it still validates a valid manifest without error.
        self.assertEqual(validate({"schema_version": 1, "id": "x", "version": "1.0.0", "name": "x", "skills": []}, schema), [])

    def test_supported_annotation_keywords_do_not_fail(self):
        schema = {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "title": "T",
            "description": "d",
            "type": "string",
            "default": "x",
        }
        self.assertEqual(validate_schema_keywords(schema), [])
        self.assertEqual(validate("hi", schema), [])

    def test_ref_target_keywords_are_checked(self):
        schema = {
            "type": "object",
            "properties": {"m": {"$ref": "#/definitions/mode"}},
            "definitions": {
                "mode": {"type": "string", "enum": ["a"], "minLength": 1},
            },
        }
        found = validate_schema_keywords(schema)
        self.assertTrue(any("minLength" in item for item in found), found)

    def test_additional_properties_schema_and_true_forms_are_rejected(self):
        schema_form = {"type": "object", "additionalProperties": {"type": "string"}}
        found = validate_schema_keywords(schema_form)
        self.assertTrue(found, found)
        self.assertTrue(
            any("additionalProperties" in item and "must be false" in item for item in found),
            found,
        )
        true_form = {"type": "object", "additionalProperties": True}
        self.assertTrue(validate_schema_keywords(true_form), true_form)

    def test_additional_properties_false_passes(self):
        schema = {"type": "object", "additionalProperties": False}
        self.assertEqual(validate_schema_keywords(schema), [])
        self.assertEqual(
            validate(
                {"a": 1},
                {"type": "object", "properties": {"a": {}}, "additionalProperties": False},
            ),
            [],
        )
        # With additionalProperties false, an undeclared key is still rejected.
        self.assertNotEqual(
            validate(
                {"a": 1, "b": 2},
                {"type": "object", "properties": {"a": {}}, "additionalProperties": False},
            ),
            [],
        )

    def test_additional_properties_schema_form_fails_closed_on_validate(self):
        schema = {"type": "object", "additionalProperties": {"type": "string"}}
        with self.assertRaises(SchemaError):
            validate({"k": "v"}, schema)

    def test_items_tuple_form_is_rejected(self):
        schema = {
            "type": "array",
            "items": [{"type": "string"}, {"type": "integer"}],
        }
        found = validate_schema_keywords(schema)
        self.assertTrue(any("items" in item and "tuple form" in item for item in found), found)

    def test_items_single_dict_passes(self):
        schema = {"type": "array", "items": {"type": "string"}}
        self.assertEqual(validate_schema_keywords(schema), [])
        self.assertEqual(validate(["a", "b"], schema), [])

    def test_items_tuple_form_fails_closed_on_validate(self):
        schema = {"type": "array", "items": [{"type": "string"}]}
        with self.assertRaises(SchemaError):
            validate(["a"], schema)

    def test_pattern_properties_is_reported_without_recursing_its_value(self):
        schema = {
            "type": "object",
            "patternProperties": {"^S_": {"type": "string", "maxLength": 5}},
        }
        found = validate_schema_keywords(schema)
        self.assertTrue(any("patternProperties" in item for item in found), found)
        # The keyword itself is reported (unsupported), but its schema value must
        # not be recursed, so its inner keywords are not reported separately.
        self.assertFalse(any("maxLength" in item for item in found), found)

    def test_properties_key_named_pattern_properties_is_not_flagged(self):
        schema = {"type": "object", "properties": {"patternProperties": {"type": "string"}}}
        self.assertEqual(validate_schema_keywords(schema), [])
        self.assertEqual(validate({"patternProperties": "x"}, schema), [])


class TestDetectUnsupportedYaml(unittest.TestCase):
    def test_legal_lines_are_clean(self):
        legal = [
            "id: demo",
            "document: 30-modules/demo.md",
            "documents:",
            "  - 30-modules/demo-platform.md",
            "- id: CL-DEMO-001",
            "  doc_refs:",
            "    - 30-modules/demo.md#主流程摘要",
            "    - ref: 30-modules/demo.md",
            "      role: primary",
            "    - {role: context, ref: 20-components/service.md}",
            "id: service # trailing comment",
            "references:",
            "  - 20-components/service.md",
        ]
        for line in legal:
            self.assertIsNone(detect_unsupported_yaml(line), line)

    def test_urls_and_markdown_links_are_not_flags(self):
        legal = [
            "- https://example.com/a?x=1&y=2",
            "document: 30-modules/demo.md#anchor",
            "ref: [text](https://example.com/path)",
        ]
        for line in legal:
            self.assertIsNone(detect_unsupported_yaml(line), line)

    def test_anchor_and_alias_are_detected(self):
        self.assertIsNotNone(detect_unsupported_yaml("id: &defaultId"))
        self.assertIsNotNone(detect_unsupported_yaml("document: *defaultId"))
        self.assertIsNotNone(detect_unsupported_yaml("  - ref: &shared"))

    def test_line_start_anchor_is_detected(self):
        self.assertIsNotNone(detect_unsupported_yaml("&foo bar"))
        self.assertIsNotNone(detect_unsupported_yaml("&foo"))
        self.assertIsNotNone(detect_unsupported_yaml("  &indented value"))

    def test_line_start_anchor_does_not_flag_markdown(self):
        # markdown unordered list: "*" followed by a space, not an identifier.
        self.assertIsNone(detect_unsupported_yaml("* item"))
        # markdown emphasis: line-start "*italic*" is not an anchored scalar.
        self.assertIsNone(detect_unsupported_yaml("*italic*"))

    def test_block_scalar_is_detected(self):
        self.assertIsNotNone(detect_unsupported_yaml("document: |"))
        self.assertIsNotNone(detect_unsupported_yaml("description: |2"))
        self.assertIsNotNone(detect_unsupported_yaml("notes: >-"))

    def test_block_scalar_combined_indicators_are_detected(self):
        # Combined indentation + chomping indicators are valid YAML and must
        # fail closed (not silently pass through).
        for line in (
            "statement: |2-",
            "notes: >2-",
            "doc: |2+",
            "notes: >2+",
            "doc: |-",
            "doc: |+",
            "doc: >+",
        ):
            self.assertIsNotNone(
                detect_unsupported_yaml(line),
                f"expected {line!r} to be reported as a block scalar",
            )

    def test_ordinary_indented_scalar_fields_are_clean(self):
        # Unknown indented scalar fields (e.g. claims.yaml business metadata)
        # are not a syntax error: the parser simply does not interpret them.
        legal = [
            "  statement: no ref",
            "    owner: alice",
            "  state: verified",
            "  evidence:",
            "    - 30-modules/demo.md",
        ]
        for line in legal:
            self.assertIsNone(detect_unsupported_yaml(line), line)


class TestManifestFailClosed(unittest.TestCase):
    def test_manifest_anchor_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "module.yaml"
            path.write_text("id: &ref demo\ndocument: 30-modules/demo.md\n", encoding="utf-8")
            _, errors = manifest_fields(path)
            self.assertTrue(any("anchor/alias" in error for error in errors), errors)

    def test_manifest_block_scalar_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "module.yaml"
            path.write_text("id: demo\ndocument: |\n  line1\n  line2\n", encoding="utf-8")
            _, errors = manifest_fields(path)
            self.assertTrue(any("block scalar" in error for error in errors), errors)

    def test_manifest_legal_file_has_no_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "component.yaml"
            path.write_text("id: service\ndocument: 20-components/service.md\n", encoding="utf-8")
            fields, errors = manifest_fields(path)
            self.assertEqual(errors, [])
            self.assertEqual(fields["id"], "service")
            self.assertEqual(fields["document"], "20-components/service.md")


def _flat_root(root: Path) -> Path:
    docs = root / "docs"
    for name in ("20-components", "30-modules", "40-journeys"):
        (docs / name).mkdir(parents=True)
    (docs / "30-modules" / "demo.md").write_text("# Demo\n\n## 主流程摘要\n", encoding="utf-8")
    (docs / "20-components" / "service.md").write_text("# Service\n", encoding="utf-8")
    (docs / "40-journeys" / "download.md").write_text("# Download\n", encoding="utf-8")
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
        "- id: CL-DEMO-001\n  doc_refs:\n    - 30-modules/demo.md#主流程摘要\n",
        encoding="utf-8",
    )
    (docs / "human-docs.json").write_text(
        '{"layout":"flat-classified","require_manifests":true,"include":["README-HUMAN.md","20-components/*.md","30-modules/*.md","40-journeys/*.md"],"exclude":[],"readme":"README-HUMAN.md"}',
        encoding="utf-8",
    )
    return docs


class TestKnowledgeLintFailClosed(unittest.TestCase):
    def test_legal_flat_docs_have_no_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(lint_knowledge(_flat_root(Path(tmp))), [])

    def test_metadata_block_scalar_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            docs = _flat_root(Path(tmp))
            claims = docs / "70-metadata" / "modules" / "demo" / "verification" / "claims.yaml"
            claims.write_text(
                "- id: CL-DEMO-001\n"
                "  doc_refs: |\n"
                "    - 30-modules/demo.md#主流程摘要\n",
                encoding="utf-8",
            )
            errors = lint_knowledge(docs)
            self.assertTrue(any("block scalar" in error for error in errors), errors)

    def test_metadata_alias_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            docs = _flat_root(Path(tmp))
            claims = docs / "70-metadata" / "modules" / "demo" / "verification" / "claims.yaml"
            claims.write_text(
                "- id: CL-DEMO-001\n"
                "  doc_refs:\n"
                "    - *primaryRef\n",
                encoding="utf-8",
            )
            errors = lint_knowledge(docs)
            self.assertTrue(any("anchor/alias" in error for error in errors), errors)

    def test_metadata_extra_scalar_fields_are_legal(self):
        # Business metadata fields (state/statement/owner/evidence) alongside a
        # doc_refs subtree are not a syntax error; doc_refs still resolves.
        with tempfile.TemporaryDirectory() as tmp:
            docs = _flat_root(Path(tmp))
            claims = docs / "70-metadata" / "modules" / "demo" / "verification" / "claims.yaml"
            claims.write_text(
                "- id: CL-DEMO-001\n"
                "  state: verified\n"
                "  statement: The system supports the demo flow.\n"
                "  owner: demo-team\n"
                "  evidence:\n"
                "    - 30-modules/demo.md#主流程摘要\n"
                "  doc_refs:\n"
                "    - ref: 30-modules/demo.md\n"
                "      role: primary\n"
                "      owner: alice\n",
                encoding="utf-8",
            )
            errors = lint_knowledge(docs)
            self.assertFalse(any("anchor/alias" in error for error in errors), errors)
            self.assertFalse(any("block scalar" in error for error in errors), errors)
            self.assertFalse(any("nested mapping" in error for error in errors), errors)


if __name__ == "__main__":
    unittest.main()
