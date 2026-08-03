"""Cross-adapter consistency tests.

Core invariant: every adapter (session mount, Codex sync, CodeBuddy sync)
derives the same final skill set from the same pack + filter, because all
of them go through the single resolver
(illuminate.resolve.resolve_exposed_skills).

The adapters generate different physical files, but the logical model they
consume (exposed skills, policies, references, permissions) must be
identical. These are the golden contract tests that prevent the adapters
from drifting apart.
"""

import json
import sys
import tempfile
import unittest
from importlib.resources import files
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from illuminate.jsonschema import validate as validate_schema
from illuminate.materialize_claude import materialize_session
from illuminate.resolve import create_mount_plan
from illuminate.sync_codex import sync_codex
from illuminate.sync_codebuddy import sync_codebuddy

REPO_ROOT = Path(__file__).parent.parent
CORE_PACK = REPO_ROOT / "packs" / "core"


def _exposed_via_mount(skill_filter):
    plan = create_mount_plan(CORE_PACK, "/tmp/repo", skill_filter=skill_filter)
    return sorted(plan["skills"]["exposed"])


def _exposed_via_codex_sync(skill_filter):
    with tempfile.TemporaryDirectory() as tmp:
        result = sync_codex(CORE_PACK, Path(tmp), skill_filter=skill_filter)
        return sorted(result["exposed_skills"])


def _exposed_via_codebuddy_sync(skill_filter):
    with tempfile.TemporaryDirectory() as tmp:
        result = sync_codebuddy(CORE_PACK, Path(tmp), skill_filter=skill_filter)
        return sorted(result["exposed_skills"])


ADAPTERS = (
    _exposed_via_mount,
    _exposed_via_codex_sync,
    _exposed_via_codebuddy_sync,
)


def _logical_resolved(skill_filter=None):
    """The logical model every adapter consumes, from shared functions."""
    from illuminate.manifest import (
        load_pack_manifest,
        load_policy_index,
        load_skill_contracts,
    )
    from illuminate.resolve import resolve_exposed_skills

    manifest = load_pack_manifest(CORE_PACK)
    contracts = load_skill_contracts(CORE_PACK, manifest)
    exposed = resolve_exposed_skills(manifest, contracts, skill_filter)

    policies = sorted(
        load_policy_index(CORE_PACK, manifest).get("policies", []),
        key=lambda p: p.get("priority", 0),
        reverse=True,
    )

    perms = {"read": set(), "write": set(), "execute": set()}
    exposed_set = set(exposed)
    for contract in contracts:
        if contract["id"] not in exposed_set:
            continue
        for key in perms:
            perms[key].update(contract.get("permissions", {}).get(key, []))

    return {
        "exposed": list(exposed),
        "policy_ids": [p["id"] for p in policies],
        "reference_ids": [r["id"] for r in manifest.get("references", [])],
        "permissions": {k: sorted(v) for k, v in perms.items()},
    }


class TestAdapterConsistency(unittest.TestCase):

    def assert_exposed_consistent(self, skill_filter=None):
        expected = _exposed_via_mount(skill_filter)
        for adapter in ADAPTERS[1:]:
            actual = adapter(skill_filter)
            self.assertEqual(
                expected, actual,
                f"{adapter.__name__} diverged from resolver",
            )

    def test_default_exposed_set_consistent(self):
        self.assert_exposed_consistent(None)

    def test_single_skill_filter_consistent(self):
        self.assert_exposed_consistent(["illuminate.layer-debug"])

    def test_alias_filter_consistent(self):
        self.assert_exposed_consistent(["illuminate.grill-me"])

    def test_activation_conflicting_skills_coexist_everywhere(self):
        """activation_conflicts does not block exposure on any adapter."""
        expected = _exposed_via_mount(
            ["illuminate.layer-debug", "illuminate.perf-profile"]
        )
        self.assertIn("illuminate.layer-debug", expected)
        self.assertIn("illuminate.perf-profile", expected)
        self.assert_exposed_consistent(
            ["illuminate.layer-debug", "illuminate.perf-profile"]
        )

    def test_unknown_skill_raises_everywhere(self):
        for adapter in ADAPTERS:
            with self.assertRaises(ValueError):
                adapter(["illuminate.nonexistent"])


class TestLogicalGoldenModel(unittest.TestCase):
    """Adapters consume the same logical model (skills/policies/references/permissions)."""

    def test_mount_plan_matches_logical_model(self):
        logical = _logical_resolved(["illuminate.layer-debug"])
        plan = create_mount_plan(
            CORE_PACK, "/tmp/repo",
            skill_filter=["illuminate.layer-debug"],
        )
        self.assertEqual(plan["skills"]["exposed"], logical["exposed"])
        self.assertEqual(plan["policies"], logical["policy_ids"])

    def test_codex_sync_matches_logical_model(self):
        logical = _logical_resolved(["illuminate.layer-debug"])
        with tempfile.TemporaryDirectory() as tmp:
            result = sync_codex(
                CORE_PACK, Path(tmp),
                skill_filter=["illuminate.layer-debug"],
            )
            self.assertEqual(
                sorted(result["exposed_skills"]), sorted(logical["exposed"])
            )

    def test_codebuddy_sync_matches_logical_model(self):
        logical = _logical_resolved(["illuminate.layer-debug"])
        with tempfile.TemporaryDirectory() as tmp:
            result = sync_codebuddy(
                CORE_PACK, Path(tmp),
                skill_filter=["illuminate.layer-debug"],
            )
            self.assertEqual(
                sorted(result["exposed_skills"]), sorted(logical["exposed"])
            )
            # Rules are copied in priority order as 00-*, 01-*, ...
            rule_files = sorted(
                (Path(tmp) / ".codebuddy" / "rules" / "illuminate").glob("*.md")
            )
            self.assertEqual(len(rule_files), len(logical["policy_ids"]))
            prefixes = [f.name.split("-", 1)[0] for f in rule_files]
            self.assertEqual(
                prefixes, [f"{i:02d}" for i in range(len(rule_files))],
                "Rule filenames must encode policy priority order",
            )

    def test_session_lock_permissions_match_logical_model(self):
        logical = _logical_resolved()
        with tempfile.TemporaryDirectory() as tmp:
            info = materialize_session(CORE_PACK, tmp)
            lock = info["lock"]
            self.assertEqual(
                lock["declared_permissions"], logical["permissions"],
                "Mount lock permissions diverge from the logical model",
            )

    def test_mount_plan_references_match_logical_model(self):
        """Every pack reference must be present in the mount file list."""
        from illuminate.manifest import load_pack_manifest
        from illuminate.resolve import resolve_file_list

        manifest = load_pack_manifest(CORE_PACK)
        plan = create_mount_plan(CORE_PACK, "/tmp/repo")
        files = resolve_file_list(CORE_PACK, plan)
        ref_dests = sorted(f["dest"] for f in files if f["kind"] == "reference")
        expected = sorted(r["path"] for r in manifest.get("references", []))
        self.assertEqual(ref_dests, expected)

    def test_codex_physical_file_mapping(self):
        """Each exposed skill's actual synced files must equal the pack's
        skill files plus the generated agents/openai.yaml."""
        from illuminate.manifest import load_pack_manifest

        manifest = load_pack_manifest(CORE_PACK)
        with tempfile.TemporaryDirectory() as tmp:
            result = sync_codex(CORE_PACK, Path(tmp))
            exposed_ids = set(result["exposed_skills"])
            skills_root = Path(tmp) / ".agents" / "skills"
            for entry in manifest.get("skills", []):
                if entry["id"] not in exposed_ids:
                    continue
                skill_name = entry["dir"].split("/")[-1]
                src_dir = CORE_PACK / entry["dir"]
                expected = {
                    f.relative_to(src_dir).as_posix()
                    for f in src_dir.rglob("*") if f.is_file()
                }
                expected.add("agents/openai.yaml")
                dst_dir = skills_root / skill_name
                actual = {
                    f.relative_to(dst_dir).as_posix()
                    for f in dst_dir.rglob("*") if f.is_file()
                }
                self.assertEqual(
                    actual, expected,
                    f"Codex file mapping diverged for {skill_name}",
                )

    def test_codebuddy_rules_content_matches_policies(self):
        """Each rule file must be a verbatim copy of its source policy."""
        from illuminate.manifest import load_pack_manifest, load_policy_index

        manifest = load_pack_manifest(CORE_PACK)
        policies = sorted(
            load_policy_index(CORE_PACK, manifest).get("policies", []),
            key=lambda p: p.get("priority", 0),
            reverse=True,
        )
        with tempfile.TemporaryDirectory() as tmp:
            sync_codebuddy(CORE_PACK, Path(tmp))
            rules_dir = Path(tmp) / ".codebuddy" / "rules" / "illuminate"
            for i, policy in enumerate(policies):
                expected = (
                    CORE_PACK / "policies" / policy["path"]
                ).read_text(encoding="utf-8")
                rule_path = rules_dir / f"{i:02d}-{Path(policy['path']).stem}.md"
                self.assertTrue(rule_path.exists(), f"Missing rule for {policy['id']}")
                self.assertEqual(
                    rule_path.read_text(encoding="utf-8"), expected,
                    f"Rule {i:02d} content diverges from policy {policy['id']}",
                )


class TestSchemaConformance(unittest.TestCase):
    """Generated artifacts must conform to the bundled JSON Schemas."""

    def test_mount_plan_conforms_to_schema(self):
        schema = json.loads(
            files("illuminate.schemas").joinpath("mount-plan.schema.json")
            .read_text(encoding="utf-8")
        )
        with tempfile.TemporaryDirectory() as tmp:
            info = materialize_session(CORE_PACK, tmp)
            errors = validate_schema(info["mount_plan"], schema)
            self.assertEqual(errors, [], f"Mount plan fails schema: {errors}")

    def test_mount_lock_conforms_to_schema(self):
        schema = json.loads(
            files("illuminate.schemas").joinpath("mount-lock.schema.json")
            .read_text(encoding="utf-8")
        )
        with tempfile.TemporaryDirectory() as tmp:
            info = materialize_session(CORE_PACK, tmp)
            errors = validate_schema(info["lock"], schema)
            self.assertEqual(errors, [], f"Mount lock fails schema: {errors}")


if __name__ == "__main__":
    unittest.main()
