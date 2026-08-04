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


class TestPackSemanticUniqueness(unittest.TestCase):
    """Semantic completeness checks: id/path uniqueness and unknown top-level fields."""

    def _make_pack(self, manifest, skills=None, policies=None) -> Path:
        import tempfile
        root = Path(tempfile.mkdtemp())
        pack_dir = root / "pack"
        for sid, sdir in (skills or []):
            skill_path = pack_dir / sdir
            skill_path.mkdir(parents=True, exist_ok=True)
            (skill_path / "SKILL.md").write_text(
                "---\nname: demo\ndescription: A demo skill\n---\n# Demo\n",
                encoding="utf-8")
            (skill_path / "contract.json").write_text(json.dumps({
                "schema_version": 1,
                "id": sid,
                "version": "0.1.0",
                "entry": "SKILL.md",
                "kind": "skill",
                "activation": {"mode": "explicit"},
            }), encoding="utf-8")
        manifest.setdefault("schema_version", 1)
        manifest.setdefault("id", "demo.pack")
        manifest.setdefault("version", "0.1.0")
        manifest.setdefault("name", "demo-pack")
        manifest.setdefault("skills", [{"id": s, "dir": d} for s, d in (skills or [])])
        manifest.setdefault("references", [])
        manifest.setdefault("evidence", {})
        if policies is not None:
            pol = pack_dir / "policies"
            pol.mkdir(parents=True)
            manifest.setdefault("policies", {"index": "policies/index.json"})
            (pol / "index.json").write_text(
                json.dumps({"schema_version": 1, "policies": policies}),
                encoding="utf-8")
            for p in policies:
                pfile = pol / p["path"]
                if not pfile.exists():
                    pfile.write_text("# Policy\n", encoding="utf-8")
        else:
            pol = pack_dir / "policies"
            pol.mkdir(parents=True)
            manifest.setdefault("policies", {"index": "policies/index.json"})
            (pol / "index.json").write_text(
                json.dumps({"schema_version": 1, "policies": []}),
                encoding="utf-8")
        (pack_dir / "pack.json").write_text(json.dumps(manifest), encoding="utf-8")
        return pack_dir

    def test_duplicate_skill_id_fails(self):
        pack_dir = self._make_pack({}, skills=[
            ("demo.skill.a", "skills/a"),
            ("demo.skill.a", "skills/b"),
        ])
        ok, errors = validate_pack(pack_dir)
        self.assertFalse(ok)
        self.assertTrue(any("duplicate skill id: demo.skill.a" in e for e in errors), errors)

    def test_duplicate_skill_dir_fails(self):
        pack_dir = self._make_pack({}, skills=[
            ("demo.skill.a", "skills/shared"),
            ("demo.skill.b", "skills/shared"),
        ])
        ok, errors = validate_pack(pack_dir)
        self.assertFalse(ok)
        self.assertTrue(any("duplicate skill dir: skills/shared" in e for e in errors), errors)

    def test_duplicate_reference_id_fails(self):
        pack_dir = self._make_pack({})
        ref_dir = pack_dir / "references"
        ref_dir.mkdir()
        (ref_dir / "r.md").write_text("# R\n", encoding="utf-8")
        (pack_dir / "pack.json").write_text(json.dumps({
            "schema_version": 1,
            "id": "demo.pack",
            "version": "0.1.0",
            "name": "demo-pack",
            "skills": [],
            "references": [
                {"id": "demo.ref", "path": "references/r.md"},
                {"id": "demo.ref", "path": "references/r.md"},
            ],
            "evidence": {},
            "policies": {"index": "policies/index.json"},
        }), encoding="utf-8")
        ok, errors = validate_pack(pack_dir)
        self.assertFalse(ok)
        self.assertTrue(any("duplicate reference id: demo.ref" in e for e in errors), errors)
        self.assertTrue(any("duplicate reference path: references/r.md" in e for e in errors), errors)

    def test_duplicate_policy_id_and_path_fail(self):
        pack_dir = self._make_pack({}, policies=[
            {"id": "demo.policy", "path": "p.md", "priority": 100},
            {"id": "demo.policy", "path": "p.md", "priority": 200},
        ])
        ok, errors = validate_pack(pack_dir)
        self.assertFalse(ok)
        self.assertTrue(any("duplicate policy id: demo.policy" in e for e in errors), errors)
        self.assertTrue(any("duplicate policy path: p.md" in e for e in errors), errors)

    def test_policy_missing_priority_or_id_fails(self):
        pack_dir = self._make_pack({}, policies=[
            {"id": "demo.policy", "path": "p.md", "priority": 100},
            {"path": "q.md", "priority": 50},
        ])
        ok, errors = validate_pack(pack_dir)
        self.assertFalse(ok)
        self.assertTrue(any("missing or invalid id" in e for e in errors), errors)

    def test_unknown_top_level_field_fails(self):
        pack_dir = self._make_pack({})
        manifest = json.loads((pack_dir / "pack.json").read_text(encoding="utf-8"))
        manifest["frobnicate"] = "nope"
        (pack_dir / "pack.json").write_text(json.dumps(manifest), encoding="utf-8")
        ok, errors = validate_pack(pack_dir)
        self.assertFalse(ok)
        self.assertTrue(any("unknown top-level field: frobnicate" in e for e in errors), errors)

    def _make_pack_with_skill_entries(self, skill_entries) -> Path:
        """Build a minimal pack whose skills[] entries are given verbatim.

        Unlike _make_pack, this lets a test inject a numeric id, an empty id,
        or other malformed skill entries without assuming string ids.
        """
        import tempfile
        root = Path(tempfile.mkdtemp())
        pack_dir = root / "pack"
        for sid, sdir in skill_entries:
            skill_path = pack_dir / sdir
            skill_path.mkdir(parents=True, exist_ok=True)
            (skill_path / "SKILL.md").write_text(
                "---\nname: demo\ndescription: A demo skill\n---\n# Demo\n",
                encoding="utf-8")
            cid = sid if isinstance(sid, str) else "demo"
            (skill_path / "contract.json").write_text(json.dumps({
                "schema_version": 1,
                "id": cid,
                "version": "0.1.0",
                "entry": "SKILL.md",
                "kind": "skill",
                "activation": {"mode": "explicit"},
            }), encoding="utf-8")
        pol = pack_dir / "policies"
        pol.mkdir(parents=True)
        (pol / "index.json").write_text(
            json.dumps({"schema_version": 1, "policies": []}), encoding="utf-8")
        (pack_dir / "pack.json").write_text(json.dumps({
            "schema_version": 1,
            "id": "demo.pack",
            "version": "0.1.0",
            "name": "demo-pack",
            "skills": skill_entries,
            "references": [],
            "evidence": {},
            "policies": {"index": "policies/index.json"},
        }), encoding="utf-8")
        return pack_dir

    def test_numeric_skill_id_reports_clean_error(self):
        """A numeric skill id must fail cleanly, not crash on sid.split('.')."""
        pack_dir = self._make_pack_with_skill_entries([
            {"id": 5, "dir": "skills/demo"},
        ])
        ok, errors = validate_pack(pack_dir)
        self.assertFalse(ok)
        self.assertTrue(any("id must be a string" in e for e in errors), errors)

    def test_empty_skill_id_reports_clean_error(self):
        """An empty skill id follows the existing missing-id path, no crash."""
        pack_dir = self._make_pack_with_skill_entries([
            {"id": "", "dir": "skills/demo"},
        ])
        ok, errors = validate_pack(pack_dir)
        self.assertFalse(ok)
        self.assertTrue(any("missing id" in e for e in errors), errors)

    def test_policy_boolean_priority_fails(self):
        """priority: true/false must not silently pass the int check."""
        pack_dir = self._make_pack({}, policies=[
            {"id": "demo.policy", "path": "p.md", "priority": True},
        ])
        ok, errors = validate_pack(pack_dir)
        self.assertFalse(ok)
        self.assertTrue(any("invalid priority" in e for e in errors), errors)

    def test_dot_slash_reference_path_detected_as_duplicate(self):
        """references/./r.md and references/r.md are the same file."""
        pack_dir = self._make_pack({})
        ref_dir = pack_dir / "references"
        ref_dir.mkdir()
        (ref_dir / "r.md").write_text("# R\n", encoding="utf-8")
        (pack_dir / "pack.json").write_text(json.dumps({
            "schema_version": 1,
            "id": "demo.pack",
            "version": "0.1.0",
            "name": "demo-pack",
            "skills": [],
            "references": [
                {"id": "demo.ref.a", "path": "references/./r.md"},
                {"id": "demo.ref.b", "path": "references/r.md"},
            ],
            "evidence": {},
            "policies": {"index": "policies/index.json"},
        }), encoding="utf-8")
        ok, errors = validate_pack(pack_dir)
        self.assertFalse(ok)
        self.assertTrue(any("duplicate reference path" in e for e in errors), errors)

    def test_case_different_reference_paths_not_duplicate(self):
        """Case differences (R.md vs r.md) are NOT duplicates on Linux."""
        pack_dir = self._make_pack({})
        ref_dir = pack_dir / "references"
        ref_dir.mkdir()
        (ref_dir / "r.md").write_text("# R\n", encoding="utf-8")
        (pack_dir / "pack.json").write_text(json.dumps({
            "schema_version": 1,
            "id": "demo.pack",
            "version": "0.1.0",
            "name": "demo-pack",
            "skills": [],
            "references": [
                {"id": "demo.ref.a", "path": "references/r.md"},
                {"id": "demo.ref.b", "path": "references/R.md"},
            ],
            "evidence": {},
            "policies": {"index": "policies/index.json"},
        }), encoding="utf-8")
        ok, errors = validate_pack(pack_dir)
        self.assertFalse(any("duplicate reference path" in e for e in errors), errors)

    def test_legal_core_style_pack_validates(self):
        pack_dir = self._make_pack({}, skills=[
            ("demo.skill.a", "skills/a"),
        ], policies=[
            {"id": "demo.policy", "path": "p.md", "priority": 100},
        ])
        ok, errors = validate_pack(pack_dir)
        self.assertTrue(ok, errors)


if __name__ == "__main__":
    unittest.main()
