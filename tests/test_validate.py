"""Tests for pack validation."""

import json
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from illuminate.validate import validate_pack

REPO_ROOT = Path(__file__).parent.parent
CORE_PACK = REPO_ROOT / "packs" / "core"


class TestPackValidation(unittest.TestCase):

    def test_core_pack_validates(self):
        ok, errors = validate_pack(CORE_PACK)
        if not ok:
            for e in errors:
                print(f"  VALIDATION ERROR: {e}")
        self.assertTrue(ok, f"Core pack validation failed: {errors}")

    def test_manifest_has_required_fields(self):
        manifest = json.loads((CORE_PACK / "pack.json").read_text(encoding="utf-8"))
        for field in ("schema_version", "id", "version", "name", "skills"):
            self.assertIn(field, manifest, f"Missing field: {field}")

    def test_all_skills_have_contracts(self):
        manifest = json.loads((CORE_PACK / "pack.json").read_text(encoding="utf-8"))
        for entry in manifest["skills"]:
            contract_path = CORE_PACK / entry["dir"] / "contract.json"
            self.assertTrue(contract_path.exists(), f"contract.json not found for {entry['id']}")

    def test_all_skills_have_skill_md(self):
        manifest = json.loads((CORE_PACK / "pack.json").read_text(encoding="utf-8"))
        for entry in manifest["skills"]:
            skill_md = CORE_PACK / entry["dir"] / "SKILL.md"
            self.assertTrue(skill_md.exists(), f"SKILL.md not found for {entry['id']}")

    def test_contract_ids_unique(self):
        manifest = json.loads((CORE_PACK / "pack.json").read_text(encoding="utf-8"))
        ids = []
        for entry in manifest["skills"]:
            contract = json.loads((CORE_PACK / entry["dir"] / "contract.json").read_text(encoding="utf-8"))
            ids.append(contract["id"])
        self.assertEqual(len(ids), len(set(ids)), f"Duplicate contract ids: {ids}")

    def test_recommended_next_references_valid(self):
        manifest = json.loads((CORE_PACK / "pack.json").read_text(encoding="utf-8"))
        skill_ids = {e["id"] for e in manifest["skills"]}
        for entry in manifest["skills"]:
            contract = json.loads((CORE_PACK / entry["dir"] / "contract.json").read_text(encoding="utf-8"))
            for ref in contract.get("relations", {}).get("recommended_next", []):
                self.assertIn(ref, skill_ids, f"Skill {entry['id']} references unknown skill: {ref}")

    def test_no_hardcoded_project_paths(self):
        for skill_dir in CORE_PACK.glob("skills/*/"):
            skill_md = skill_dir / "SKILL.md"
            if skill_md.exists():
                content = skill_md.read_text(encoding="utf-8")
                self.assertNotIn("工程约定.md", content, f"{skill_md} references hardcoded 工程约定.md")

    def test_policies_exist(self):
        index = json.loads((CORE_PACK / "policies" / "index.json").read_text(encoding="utf-8"))
        for policy in index["policies"]:
            path = CORE_PACK / "policies" / policy["path"]
            self.assertTrue(path.exists(), f"Policy file not found: {policy['path']}")


class TestContractSchema(unittest.TestCase):
    """Contracts must conform to schemas/skill-contract.schema.json."""

    def _load_contract_schema(self):
        from importlib.resources import files
        data = files("illuminate.schemas").joinpath("skill-contract.schema.json")
        return json.loads(data.read_text(encoding="utf-8"))

    def _load_contracts(self):
        from illuminate.manifest import load_pack_manifest, load_skill_contracts
        manifest = load_pack_manifest(CORE_PACK)
        return load_skill_contracts(CORE_PACK, manifest)

    def test_all_contracts_pass_schema(self):
        from illuminate.jsonschema import validate as validate_schema
        schema = self._load_contract_schema()
        for contract in self._load_contracts():
            errors = validate_schema(contract, schema)
            self.assertEqual(
                errors, [],
                f"Contract {contract['id']} fails schema: {errors}",
            )

    def test_schema_rejects_unknown_activation_mode(self):
        from illuminate.jsonschema import validate as validate_schema
        schema = self._load_contract_schema()
        contract = self._load_contracts()[0]
        contract["activation"]["mode"] = "sometimes"
        errors = validate_schema(contract, schema)
        self.assertTrue(any("enum" in e for e in errors), errors)

    def test_schema_rejects_legacy_relation_field(self):
        """Legacy conflicts_with / not_recommended_with must not return."""
        from illuminate.jsonschema import validate as validate_schema
        schema = self._load_contract_schema()
        contract = self._load_contracts()[0]
        contract["relations"]["not_recommended_with"] = []
        errors = validate_schema(contract, schema)
        self.assertTrue(
            any("additional property" in e for e in errors),
            f"Legacy relation field not rejected: {errors}",
        )


class TestSkillFrontmatter(unittest.TestCase):
    """validate_pack requires SKILL.md to carry a name/description frontmatter."""

    def _make_pack_with_skill(self, skill_md: str) -> Path:
        import tempfile
        root = Path(tempfile.mkdtemp())
        pack_dir = root / "pack"
        skills_dir = pack_dir / "skills" / "demo"
        skills_dir.mkdir(parents=True)
        (skills_dir / "SKILL.md").write_text(skill_md, encoding="utf-8")
        (skills_dir / "contract.json").write_text(json.dumps({
            "schema_version": 1,
            "id": "demo.pack.demo",
            "version": "0.1.0",
            "entry": "SKILL.md",
            "kind": "skill",
            "activation": {"mode": "explicit"},
        }), encoding="utf-8")
        (pack_dir / "pack.json").write_text(json.dumps({
            "schema_version": 1,
            "id": "demo.pack",
            "version": "0.1.0",
            "name": "demo-pack",
            "skills": [{"id": "demo.pack.demo", "dir": "skills/demo"}],
            "references": [],
            "policies": {"index": "policies/index.json"},
            "evidence": {},
        }), encoding="utf-8")
        pol = pack_dir / "policies"
        pol.mkdir()
        (pol / "index.json").write_text(
            json.dumps({"schema_version": 1, "policies": []}), encoding="utf-8")
        return pack_dir

    def test_skill_missing_frontmatter_fails(self):
        pack_dir = self._make_pack_with_skill("# No frontmatter\n")
        ok, errors = validate_pack(pack_dir)
        self.assertFalse(ok)
        self.assertTrue(any("frontmatter" in e for e in errors), errors)

    def test_skill_missing_name_or_description_fails(self):
        pack_dir = self._make_pack_with_skill(
            "---\nname: demo\n---\n# Missing description\n")
        ok, errors = validate_pack(pack_dir)
        self.assertFalse(ok)
        self.assertTrue(any("description" in e for e in errors), errors)

    def test_skill_legal_frontmatter_validates(self):
        pack_dir = self._make_pack_with_skill(
            "---\nname: demo\ndescription: A demo skill\n---\n# Demo\n")
        ok, errors = validate_pack(pack_dir)
        self.assertTrue(ok, errors)


if __name__ == "__main__":
    unittest.main()
