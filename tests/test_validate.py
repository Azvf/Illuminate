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


if __name__ == "__main__":
    unittest.main()
