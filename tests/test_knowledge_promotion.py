"""Tests for knowledge promotion (candidate/review/promote/reject).

Contract lives in src/illuminate/promotion.py. Store layout mirrors
knowledge_store: <store>/projects/<project-id>/promotions.json holds a
``schema_version`` + ``candidates`` list; generalized content (if any) is
written to <store>/projects/<project-id>/promotions/<id>.md.

All tests pass an explicit ``store=<tmp>/store`` so they never touch the real
default store under the home directory.
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from illuminate.promotion import (  # noqa: E402
    PromotionError,
    _derive_project_id,
    _sha256,
    knowledge_candidate,
    knowledge_promote,
    knowledge_reject,
    knowledge_review,
)
from illuminate.validate import validate_pack  # noqa: E402


def _make_repo(root: Path, rel: str = "30-modules/demo.md", content: str = "") -> Path:
    """Construct repo_root/docs/<rel> and return the file path."""
    fpath = root / "docs" / rel
    fpath.parent.mkdir(parents=True, exist_ok=True)
    fpath.write_text(content or f"# {Path(rel).name}\n\nKnowledge content.\n", encoding="utf-8")
    return fpath


def _make_pack(root: Path, version: str = "0.1.0") -> Path:
    """Construct a minimal legal pack dir and return it.

    Promote now runs validate_pack after writing, which requires a manifest with
    schema_version/id/name/skills plus a resolvable policies index. An empty
    but structurally complete pack lets every target writer register and pass
    validation.
    """
    pack_dir = root / "pack"
    pack_dir.mkdir(parents=True, exist_ok=True)
    (pack_dir / "pack.json").write_text(json.dumps({
        "schema_version": 1,
        "id": "demo.pack",
        "version": version,
        "name": "demo-pack",
        "skills": [],
        "references": [],
        "policies": {"index": "policies/index.json"},
        "evidence": {},
    }), encoding="utf-8")
    pol_dir = pack_dir / "policies"
    pol_dir.mkdir(parents=True, exist_ok=True)
    (pol_dir / "index.json").write_text(
        json.dumps({"schema_version": 1, "policies": []}), encoding="utf-8"
    )
    return pack_dir


def _registry(store: Path, repo: Path) -> dict:
    """Read the raw promotions registry JSON for a repo."""
    path = store / "projects" / _derive_project_id(repo) / "promotions.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _candidates(store: Path, repo: Path) -> list:
    return _registry(store, repo)["candidates"]


def _find(store: Path, repo: Path, candidate_id: str) -> dict:
    for record in _candidates(store, repo):
        if record["id"] == candidate_id:
            return record
    raise AssertionError(f"candidate {candidate_id} not found in registry")


class TestKnowledgePromotion(unittest.TestCase):

    def setUp(self):
        self.repo = Path(tempfile.mkdtemp())
        self.store = Path(tempfile.mkdtemp())
        self.pack = _make_pack(Path(tempfile.mkdtemp()))
        # Non-git repo by default: source.commit/repo must be None, no error.

    def _git_init_and_commit(self):
        try:
            subprocess.run(["git", "init"], cwd=str(self.repo),
                           capture_output=True, check=False)
            subprocess.run(["git", "config", "user.email", "test@test.com"],
                           cwd=str(self.repo), capture_output=True, check=False)
            subprocess.run(["git", "config", "user.name", "Test"],
                           cwd=str(self.repo), capture_output=True, check=False)
            subprocess.run(["git", "add", "-A"], cwd=str(self.repo),
                           capture_output=True, check=False)
            subprocess.run(["git", "commit", "-m", "seed"],
                           cwd=str(self.repo), capture_output=True, check=False)
        except Exception:
            pass

    def _reviewed_candidate(self, rel="30-modules/demo.md", target="reference",
                            content=""):
        _make_repo(self.repo, rel, content)
        cand = knowledge_candidate(self.repo, rel, target, store=self.store)
        knowledge_review(self.repo, cand["id"], store=self.store)
        return cand

    # ── 1. candidate creates raw record ──

    def test_candidate_creates_raw_record(self):
        _make_repo(self.repo)
        result = knowledge_candidate(self.repo, "30-modules/demo.md", "reference",
                                     store=self.store)
        self.assertEqual(result["status"], "raw")
        reg = _registry(self.store, self.repo)
        self.assertEqual(reg["schema_version"], 1)
        candidate = _find(self.store, self.repo, result["id"])
        self.assertEqual(candidate["status"], "raw")
        self.assertEqual(candidate["source"]["path"], "30-modules/demo.md")
        self.assertEqual(candidate["target"], "reference")

    # ── 2. candidate determinism ──

    def test_candidate_id_is_deterministic(self):
        _make_repo(self.repo)
        first = knowledge_candidate(self.repo, "30-modules/demo.md", "reference",
                                    store=self.store)
        second = knowledge_candidate(self.repo, "30-modules/demo.md", "reference",
                                     store=self.store)
        self.assertEqual(first["id"], second["id"])

    def test_candidate_idempotent_returns_existing(self):
        _make_repo(self.repo)
        first = knowledge_candidate(self.repo, "30-modules/demo.md", "reference",
                                    store=self.store)
        second = knowledge_candidate(self.repo, "30-modules/demo.md", "reference",
                                     store=self.store)
        self.assertEqual(first, second)
        self.assertEqual(len(_candidates(self.store, self.repo)), 1,
                         "re-candidacy must not duplicate records")

    # ── 3. candidate validation errors ──

    def test_candidate_missing_source_raises(self):
        with self.assertRaises(PromotionError):
            knowledge_candidate(self.repo, "30-modules/absent.md", "reference",
                                store=self.store)

    def test_candidate_invalid_target_raises(self):
        _make_repo(self.repo)
        with self.assertRaises(PromotionError):
            knowledge_candidate(self.repo, "30-modules/demo.md", "gadget",
                                store=self.store)

    # ── 4. non-git / git source identity ──

    def test_candidate_non_git_repo(self):
        _make_repo(self.repo)
        result = knowledge_candidate(self.repo, "30-modules/demo.md", "reference",
                                     store=self.store)
        candidate = _find(self.store, self.repo, result["id"])
        self.assertIsNone(candidate["source"]["commit"])
        self.assertIsNone(candidate["source"]["repo"])

    def test_candidate_git_repo_has_commit(self):
        _make_repo(self.repo)
        self._git_init_and_commit()
        result = knowledge_candidate(self.repo, "30-modules/demo.md", "reference",
                                     store=self.store)
        candidate = _find(self.store, self.repo, result["id"])
        self.assertIsNotNone(candidate["source"]["commit"])

    # ── 5. review transitions and guards ──

    def test_review_raw_to_reviewed_records_reviewer(self):
        _make_repo(self.repo)
        cand = knowledge_candidate(self.repo, "30-modules/demo.md", "reference",
                                   store=self.store)
        reviewed = knowledge_review(self.repo, cand["id"], store=self.store,
                                    reviewer="alice")
        self.assertEqual(reviewed["status"], "reviewed")
        self.assertEqual(reviewed["reviewer"], "alice")
        candidate = _find(self.store, self.repo, cand["id"])
        self.assertEqual(candidate["status"], "reviewed")
        self.assertEqual(candidate["reviewer"], "alice")

    def test_review_twice_raises(self):
        _make_repo(self.repo)
        cand = knowledge_candidate(self.repo, "30-modules/demo.md", "reference",
                                   store=self.store)
        knowledge_review(self.repo, cand["id"], store=self.store)
        with self.assertRaises(PromotionError):
            knowledge_review(self.repo, cand["id"], store=self.store)

    # ── 6. promote on raw raises ──

    def test_promote_raw_raises(self):
        _make_repo(self.repo)
        cand = knowledge_candidate(self.repo, "30-modules/demo.md", "reference",
                                   store=self.store)
        with self.assertRaises(PromotionError):
            knowledge_promote(self.repo, cand["id"], self.pack, store=self.store)

    # ── 7. review then promote writes into pack dirs ──

    def test_promote_writes_pack_and_updates_status(self):
        cand = self._reviewed_candidate()
        result = knowledge_promote(self.repo, cand["id"], self.pack, store=self.store)
        self.assertEqual(result["pack_version"], "0.1.0")
        self.assertFalse(result["dry_run"])
        self.assertEqual(result["status"], "promoted")
        self.assertFalse(result["generalized"])
        candidate = _find(self.store, self.repo, cand["id"])
        self.assertEqual(candidate["status"], "promoted")
        self.assertEqual(candidate["pack_version"], "0.1.0")
        # target=reference maps to references/ in the pack; default uses the
        # source basename (pack stays flat).
        self.assertEqual(result["written"], "references/demo.md")
        self.assertTrue((self.pack / "references" / "demo.md").exists())

    def test_promote_target_dir_mapping(self):
        cases = {
            "policy": "policies",
            "skill": "skills",
            "reference": "references",
            "evidence": "evidence",
        }
        for i, (target, subdir) in enumerate(cases.items()):
            repo = Path(tempfile.mkdtemp())
            pack = _make_pack(Path(tempfile.mkdtemp()))
            rel = f"30-modules/doc-{i}.md"
            _make_repo(repo, rel)
            cand = knowledge_candidate(repo, rel, target, store=self.store)
            knowledge_review(repo, cand["id"], store=self.store)
            result = knowledge_promote(repo, cand["id"], pack, store=self.store)
            if target == "skill":
                # a skill is a directory with SKILL.md, not a single file.
                self.assertEqual(result["written"], f"skills/doc-{i}/SKILL.md")
                self.assertTrue((pack / "skills" / f"doc-{i}" / "SKILL.md").exists())
            else:
                self.assertEqual(result["written"], f"{subdir}/doc-{i}.md")
                self.assertTrue(
                    (pack / subdir / f"doc-{i}.md").exists(),
                    f"{target} should map to {subdir}/",
                )

    # ── 8. content_path generalization ──

    def test_promote_with_content_path(self):
        # The reviewed bytes are pinned: promote refuses any content that does
        # not hash to reviewed_sha256, so a valid --content must equal the
        # reviewed snapshot. Here we review "# Demo\n" and pass identical bytes.
        cand = self._reviewed_candidate(content="# Demo\n")
        content = Path(tempfile.mkdtemp()) / "generalized.md"
        content.write_text("# Demo\n", encoding="utf-8")
        result = knowledge_promote(self.repo, cand["id"], self.pack, store=self.store,
                                   content_path=content)
        self.assertTrue(result["generalized"])
        candidate = _find(self.store, self.repo, cand["id"])
        self.assertTrue(candidate["generalized"])
        # Pack file holds the (reviewed) content
        self.assertEqual(
            (self.pack / "references" / "demo.md").read_text(encoding="utf-8"),
            content.read_text(encoding="utf-8"),
        )
        # Generalized draft snapshot stored under store promotions/<id>/draft.md
        promoted_copy = (self.store / "projects" / _derive_project_id(self.repo)
                         / "promotions" / cand["id"] / "draft.md")
        self.assertEqual(promoted_copy.read_text(encoding="utf-8"),
                         content.read_text(encoding="utf-8"))

    def test_promote_rejects_content_different_from_reviewed(self):
        cand = self._reviewed_candidate()  # binds default source content
        other = Path(tempfile.mkdtemp()) / "draft.md"
        other.write_text("# A different, unreviewed draft\n", encoding="utf-8")
        with self.assertRaises(PromotionError):
            knowledge_promote(self.repo, cand["id"], self.pack, store=self.store,
                              content_path=other)

    def test_promote_without_content_uses_source_doc(self):
        cand = self._reviewed_candidate(content="# Original source\n")
        result = knowledge_promote(self.repo, cand["id"], self.pack, store=self.store)
        self.assertFalse(result["generalized"])
        candidate = _find(self.store, self.repo, cand["id"])
        self.assertFalse(candidate["generalized"])
        self.assertEqual(
            (self.pack / "references" / "demo.md").read_text(encoding="utf-8"),
            "# Original source\n",
        )

    # ── 9. target_path custom location ──

    def test_promote_with_target_path(self):
        cand = self._reviewed_candidate()
        # --target-path is narrowed to the target's directory (references/ for a
        # reference); a nested path inside that directory is allowed.
        result = knowledge_promote(self.repo, cand["id"], self.pack, store=self.store,
                                   target_path="references/guides/landing.md")
        self.assertEqual(result["written"], "references/guides/landing.md")
        self.assertTrue((self.pack / "references" / "guides" / "landing.md").exists())

    def test_promote_target_path_outside_target_dir_raises(self):
        cand = self._reviewed_candidate()
        with self.assertRaises(PromotionError):
            knowledge_promote(self.repo, cand["id"], self.pack, store=self.store,
                              target_path="policies/escaped.md")

    def test_promote_target_path_governance_rejected(self):
        cand = self._reviewed_candidate()
        for gov in ("pack.json", "policies/index.json", "schemas/pack.schema.json"):
            with self.assertRaises(PromotionError):
                knowledge_promote(self.repo, cand["id"], self.pack, store=self.store,
                                  target_path=gov, force=True)

    # ── 9b. promote refuses to overwrite existing pack files ──

    def test_promote_refuses_existing_pack_file(self):
        cand = self._reviewed_candidate()
        target = self.pack / "references" / "demo.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("EXISTING PACK CONTENT\n", encoding="utf-8")
        with self.assertRaises(PromotionError):
            knowledge_promote(self.repo, cand["id"], self.pack, store=self.store)
        self.assertEqual(target.read_text(encoding="utf-8"), "EXISTING PACK CONTENT\n")

    def test_promote_force_overwrites_existing_pack_file(self):
        cand = self._reviewed_candidate()
        target = self.pack / "references" / "demo.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("EXISTING PACK CONTENT\n", encoding="utf-8")
        result = knowledge_promote(self.repo, cand["id"], self.pack, store=self.store,
                                   force=True)
        self.assertEqual(result["status"], "promoted")
        self.assertNotEqual(target.read_text(encoding="utf-8"), "EXISTING PACK CONTENT\n")

    # ── 10. dry_run ──

    def test_promote_dry_run_writes_nothing(self):
        cand = self._reviewed_candidate()
        result = knowledge_promote(self.repo, cand["id"], self.pack, store=self.store,
                                   dry_run=True)
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["status"], "reviewed")
        self.assertFalse(result["generalized"])
        candidate = _find(self.store, self.repo, cand["id"])
        self.assertEqual(candidate["status"], "reviewed",
                         "status must not change on dry run")
        self.assertFalse((self.pack / "references").exists(),
                         "no files may be written to pack on dry run")

    # ── 11. reject transitions ──

    def test_reject_raw_to_rejected(self):
        repo = Path(tempfile.mkdtemp())
        _make_repo(repo, "30-modules/other.md")
        raw = knowledge_candidate(repo, "30-modules/other.md", "reference",
                                  store=self.store)
        result = knowledge_reject(repo, raw["id"], store=self.store, reviewer="bob")
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(result["reviewer"], "bob")

    def test_reject_reviewed_to_rejected(self):
        cand = self._reviewed_candidate()
        result = knowledge_reject(self.repo, cand["id"], store=self.store)
        self.assertEqual(result["status"], "rejected")

    def test_reject_supersede_promoted_to_superseded(self):
        cand = self._reviewed_candidate()
        knowledge_promote(self.repo, cand["id"], self.pack, store=self.store)
        result = knowledge_reject(self.repo, cand["id"], store=self.store,
                                  supersede=True)
        self.assertEqual(result["status"], "superseded")

    def test_supersede_raw_raises(self):
        _make_repo(self.repo)
        raw = knowledge_candidate(self.repo, "30-modules/demo.md", "reference",
                                  store=self.store)
        with self.assertRaises(PromotionError):
            knowledge_reject(self.repo, raw["id"], store=self.store, supersede=True)

    def test_supersede_reviewed_raises(self):
        cand = self._reviewed_candidate()
        with self.assertRaises(PromotionError):
            knowledge_reject(self.repo, cand["id"], store=self.store, supersede=True)

    # ── 12. unknown candidate id ──

    def test_unknown_candidate_raises(self):
        _make_repo(self.repo)
        knowledge_candidate(self.repo, "30-modules/demo.md", "reference",
                            store=self.store)
        with self.assertRaises(PromotionError):
            knowledge_review(self.repo, "does-not-exist", store=self.store)
        with self.assertRaises(PromotionError):
            knowledge_promote(self.repo, "does-not-exist", self.pack, store=self.store)
        with self.assertRaises(PromotionError):
            knowledge_reject(self.repo, "does-not-exist", store=self.store)

    # ── 13. nonexistent pack dir / invalid pack ──

    def test_promote_missing_pack_dir_raises(self):
        cand = self._reviewed_candidate()
        missing = Path(tempfile.mkdtemp()) / "no-pack"
        with self.assertRaises(PromotionError):
            knowledge_promote(self.repo, cand["id"], missing, store=self.store)

    def test_pack_without_pack_json_raises(self):
        cand = self._reviewed_candidate()
        bad_pack = Path(tempfile.mkdtemp()) / "pack"
        bad_pack.mkdir(parents=True, exist_ok=True)
        with self.assertRaises(PromotionError):
            knowledge_promote(self.repo, cand["id"], bad_pack, store=self.store)

    # ── 14. corrupt registry ──

    def test_corrupt_registry_raises_not_crash(self):
        _make_repo(self.repo)
        reg_path = (self.store / "projects" / _derive_project_id(self.repo)
                    / "promotions.json")
        reg_path.parent.mkdir(parents=True, exist_ok=True)
        reg_path.write_text("{not valid json", encoding="utf-8")
        with self.assertRaises(PromotionError):
            knowledge_candidate(self.repo, "30-modules/demo.md", "reference",
                                store=self.store)
        with self.assertRaises(PromotionError):
            knowledge_review(self.repo, "any", store=self.store)

    # ── 15. content-trust binding (hash) ──

    def test_promote_rejects_changed_source_after_review(self):
        fpath = _make_repo(self.repo, content="# v1\n")
        cand = knowledge_candidate(self.repo, "30-modules/demo.md", "reference",
                                   store=self.store)
        knowledge_review(self.repo, cand["id"], store=self.store)
        fpath.write_text("# v2\n", encoding="utf-8")  # source changed post-review
        with self.assertRaises(PromotionError):
            knowledge_promote(self.repo, cand["id"], self.pack, store=self.store)
        # candidate stays reviewed; nothing written to the pack
        candidate = _find(self.store, self.repo, cand["id"])
        self.assertEqual(candidate["status"], "reviewed")

    def test_candidate_snapshot_written_and_hash_recorded(self):
        _make_repo(self.repo, content="# snap\n")
        cand = knowledge_candidate(self.repo, "30-modules/demo.md", "reference",
                                   store=self.store)
        snapshot = (self.store / "projects" / _derive_project_id(self.repo)
                    / "promotions" / cand["id"] / "source.md")
        self.assertTrue(snapshot.exists())
        self.assertEqual(snapshot.read_text(encoding="utf-8"), "# snap\n")
        candidate = _find(self.store, self.repo, cand["id"])
        self.assertEqual(candidate["source_sha256"], _sha256("# snap\n"))

    def test_review_records_reviewed_sha256(self):
        _make_repo(self.repo, content="# reviewed\n")
        cand = knowledge_candidate(self.repo, "30-modules/demo.md", "reference",
                                   store=self.store)
        reviewed = knowledge_review(self.repo, cand["id"], store=self.store,
                                    reviewer="alice")
        self.assertEqual(reviewed["reviewed_sha256"], _sha256("# reviewed\n"))
        self.assertIsNotNone(reviewed["reviewed_at"])

    # ── 16. per-target pack writer registration ──

    def test_promote_reference_registers_in_manifest(self):
        cand = self._reviewed_candidate()
        knowledge_promote(self.repo, cand["id"], self.pack, store=self.store)
        manifest = json.loads((self.pack / "pack.json").read_text(encoding="utf-8"))
        self.assertIn(
            {"id": "demo.pack.demo", "path": "references/demo.md"},
            manifest["references"],
        )
        ok, errors = validate_pack(self.pack)
        self.assertTrue(ok, errors)

    def test_promote_skill_registers_manifest_and_contract(self):
        repo = Path(tempfile.mkdtemp())
        pack = _make_pack(Path(tempfile.mkdtemp()))
        _make_repo(repo, "30-modules/my-skill.md", "# My skill\n")
        cand = knowledge_candidate(repo, "30-modules/my-skill.md", "skill",
                                   store=self.store)
        knowledge_review(repo, cand["id"], store=self.store)
        result = knowledge_promote(repo, cand["id"], pack, store=self.store)
        self.assertEqual(result["written"], "skills/my-skill/SKILL.md")
        self.assertTrue((pack / "skills" / "my-skill" / "SKILL.md").exists())
        self.assertTrue((pack / "skills" / "my-skill" / "contract.json").exists())
        contract = json.loads(
            (pack / "skills" / "my-skill" / "contract.json").read_text(encoding="utf-8")
        )
        self.assertEqual(contract["id"], "demo.pack.my-skill")
        self.assertEqual(contract["kind"], "skill")
        manifest = json.loads((pack / "pack.json").read_text(encoding="utf-8"))
        self.assertIn({"id": "demo.pack.my-skill", "dir": "skills/my-skill"},
                      manifest["skills"])
        ok, errors = validate_pack(pack)
        self.assertTrue(ok, errors)

    def test_promote_skill_same_name_requires_force(self):
        _make_repo(self.repo, "30-modules/demo.md", "# Skill A\n")
        c1 = knowledge_candidate(self.repo, "30-modules/demo.md", "skill",
                                 store=self.store)
        knowledge_review(self.repo, c1["id"], store=self.store)
        knowledge_promote(self.repo, c1["id"], self.pack, store=self.store)

        _make_repo(self.repo, "30-modules/other.md", "# Skill B\n")
        c2 = knowledge_candidate(self.repo, "30-modules/other.md", "skill",
                                 store=self.store)
        knowledge_review(self.repo, c2["id"], store=self.store)
        # c2 targets the same skill name "demo" via target_path; default rejects.
        with self.assertRaises(PromotionError):
            knowledge_promote(self.repo, c2["id"], self.pack, store=self.store,
                              target_path="skills/demo")
        # --force overwrites in place.
        result = knowledge_promote(self.repo, c2["id"], self.pack, store=self.store,
                                   target_path="skills/demo", force=True)
        self.assertEqual(result["status"], "promoted")
        self.assertEqual(
            (self.pack / "skills" / "demo" / "SKILL.md").read_text(encoding="utf-8"),
            "# Skill B\n",
        )

    def test_promote_policy_registers_in_index(self):
        repo = Path(tempfile.mkdtemp())
        pack = _make_pack(Path(tempfile.mkdtemp()))
        _make_repo(repo, "30-modules/rule.md", "# Rule\n")
        cand = knowledge_candidate(repo, "30-modules/rule.md", "policy",
                                   store=self.store)
        knowledge_review(repo, cand["id"], store=self.store)
        knowledge_promote(repo, cand["id"], pack, store=self.store)
        index = json.loads(
            (pack / "policies" / "index.json").read_text(encoding="utf-8")
        )
        self.assertIn(
            {"id": "demo.pack.rule", "path": "rule.md", "priority": 0},
            index["policies"],
        )
        ok, errors = validate_pack(pack)
        self.assertTrue(ok, errors)

    def test_promote_evidence_registers_config(self):
        repo = Path(tempfile.mkdtemp())
        pack = _make_pack(Path(tempfile.mkdtemp()))
        _make_repo(repo, "30-modules/tracer.md", "# Tracer\n")
        cand = knowledge_candidate(repo, "30-modules/tracer.md", "evidence",
                                   store=self.store)
        knowledge_review(repo, cand["id"], store=self.store)
        knowledge_promote(repo, cand["id"], pack, store=self.store)
        manifest = json.loads((pack / "pack.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["evidence"]["config"], "evidence/tracer.md")
        ok, errors = validate_pack(pack)
        self.assertTrue(ok, errors)

    # ── 17. validate-failure rollback ──

    def test_promote_rolls_back_on_validate_failure(self):
        cand = self._reviewed_candidate()
        # Inject a broken reference (missing file) so validate_pack must fail
        # even after our writer registers a valid reference.
        manifest = json.loads((self.pack / "pack.json").read_text(encoding="utf-8"))
        manifest.setdefault("references", []).append(
            {"id": "demo.pack.broken", "path": "references/broken.md"}
        )
        (self.pack / "pack.json").write_text(json.dumps(manifest), encoding="utf-8")
        before = (self.pack / "pack.json").read_bytes()
        with self.assertRaises(PromotionError):
            knowledge_promote(self.repo, cand["id"], self.pack, store=self.store)
        # Registry unchanged: still reviewed.
        candidate = _find(self.store, self.repo, cand["id"])
        self.assertEqual(candidate["status"], "reviewed")
        # pack.json fully restored (our reference was not registered).
        self.assertEqual((self.pack / "pack.json").read_bytes(), before)
        # No reference file left behind.
        self.assertFalse((self.pack / "references" / "demo.md").exists())

    # ── Adversarial / extra cases ──

    def test_reject_already_rejected_raises(self):
        repo = Path(tempfile.mkdtemp())
        _make_repo(repo, "30-modules/x.md")
        raw = knowledge_candidate(repo, "30-modules/x.md", "reference", store=self.store)
        knowledge_reject(repo, raw["id"], store=self.store)
        with self.assertRaises(PromotionError):
            knowledge_reject(repo, raw["id"], store=self.store)

    def test_promote_already_promoted_raises(self):
        cand = self._reviewed_candidate()
        knowledge_promote(self.repo, cand["id"], self.pack, store=self.store)
        with self.assertRaises(PromotionError):
            knowledge_promote(self.repo, cand["id"], self.pack, store=self.store)

    def test_review_empty_id_raises(self):
        _make_repo(self.repo)
        knowledge_candidate(self.repo, "30-modules/demo.md", "reference", store=self.store)
        with self.assertRaises(PromotionError):
            knowledge_review(self.repo, "", store=self.store)

    def test_candidate_notes_are_preserved(self):
        _make_repo(self.repo)
        result = knowledge_candidate(self.repo, "30-modules/demo.md", "reference",
                                     store=self.store, notes="why this matters")
        candidate = _find(self.store, self.repo, result["id"])
        self.assertEqual(candidate["notes"], "why this matters")

    def test_timestamps_are_iso8601(self):
        _make_repo(self.repo)
        result = knowledge_candidate(self.repo, "30-modules/demo.md", "reference",
                                     store=self.store)
        candidate = _find(self.store, self.repo, result["id"])
        from datetime import datetime
        for field in ("created_at", "updated_at"):
            # isoformat with timezone offset; round-trips via fromisoformat
            datetime.fromisoformat(candidate[field])
        self.assertIn("T", candidate["created_at"])

    def test_anchor_changes_candidate_id(self):
        _make_repo(self.repo)
        base = knowledge_candidate(self.repo, "30-modules/demo.md", "reference",
                                   store=self.store)
        anchored = knowledge_candidate(self.repo, "30-modules/demo.md", "reference",
                                       store=self.store, anchor="sec-2")
        self.assertNotEqual(base["id"], anchored["id"])

    # ── 18. P1-A: default branch must run governance check ──

    def test_promote_default_path_governance_index_json_rejected(self):
        # A source named index.json (markdown) targeting policy must not be
        # written to the governance file policies/index.json via the DEFAULT
        # (no --target-path) branch, even with --force.
        repo = Path(tempfile.mkdtemp())
        pack = _make_pack(Path(tempfile.mkdtemp()))
        _make_repo(repo, "30-modules/index.json", "# markdown, not json\n")
        cand = knowledge_candidate(repo, "30-modules/index.json", "policy",
                                   store=self.store)
        knowledge_review(repo, cand["id"], store=self.store)
        with self.assertRaises(PromotionError):
            knowledge_promote(repo, cand["id"], pack, store=self.store, force=True)
        # The governance file must remain intact and valid.
        index_path = pack / "policies" / "index.json"
        self.assertEqual(
            json.loads(index_path.read_text(encoding="utf-8")),
            {"schema_version": 1, "policies": []},
        )
        candidate = _find(self.store, repo, cand["id"])
        self.assertEqual(candidate["status"], "reviewed")

    def test_promote_governance_pack_json_and_schema_default_rejected(self):
        # basename pack.json / *.schema.json / index.json are rejected on the
        # default branch too (here forced through references dir).
        repo = Path(tempfile.mkdtemp())
        pack = _make_pack(Path(tempfile.mkdtemp()))
        for fname in ("pack.json", "tracer.schema.json", "index.json"):
            _make_repo(repo, f"30-modules/{fname}", "# content\n")
            cand = knowledge_candidate(repo, f"30-modules/{fname}", "reference",
                                       store=self.store)
            knowledge_review(repo, cand["id"], store=self.store)
            with self.assertRaises(PromotionError):
                knowledge_promote(repo, cand["id"], pack, store=self.store, force=True)
            self.assertFalse((pack / "references" / fname).exists())

    def test_promote_policy_corrupt_index_raises_not_crash(self):
        # If the policy index is malformed, promote must raise PromotionError
        # rather than let JSONDecodeError escape uncaught.
        repo = Path(tempfile.mkdtemp())
        pack = _make_pack(Path(tempfile.mkdtemp()))
        _make_repo(repo, "30-modules/rule.md", "# Rule\n")
        cand = knowledge_candidate(repo, "30-modules/rule.md", "policy",
                                   store=self.store)
        knowledge_review(repo, cand["id"], store=self.store)
        (pack / "policies" / "index.json").write_text("{not valid", encoding="utf-8")
        with self.assertRaises(PromotionError):
            knowledge_promote(repo, cand["id"], pack, store=self.store)

    # ── 19. P1-B: skill validate failure removes newly created dir ──

    def test_promote_skill_validate_failure_removes_new_dir(self):
        repo = Path(tempfile.mkdtemp())
        pack = _make_pack(Path(tempfile.mkdtemp()))
        # Inject a broken reference so validate_pack must fail even though the
        # promoted skill itself is structurally valid.
        manifest = json.loads((pack / "pack.json").read_text(encoding="utf-8"))
        manifest.setdefault("references", []).append(
            {"id": "demo.pack.broken", "path": "references/broken.md"}
        )
        (pack / "pack.json").write_text(json.dumps(manifest), encoding="utf-8")
        _make_repo(repo, "30-modules/fresh.md", "# Fresh skill\n")
        cand = knowledge_candidate(repo, "30-modules/fresh.md", "skill",
                                   store=self.store)
        knowledge_review(repo, cand["id"], store=self.store)
        with self.assertRaises(PromotionError):
            knowledge_promote(repo, cand["id"], pack, store=self.store)
        # The freshly created dir must not linger as an empty orphan.
        self.assertFalse((pack / "skills" / "fresh").exists())

    # ── 20. P1-C: --target-path pointing at a directory is rejected ──

    def test_promote_target_path_policies_dir_rejected(self):
        cand = self._reviewed_candidate(target="policy",
                                        rel="30-modules/rule.md")
        for force in (False, True):
            with self.assertRaises(PromotionError):
                knowledge_promote(self.repo, cand["id"], self.pack,
                                  store=self.store, target_path="policies",
                                  force=force)
        self.assertFalse((self.pack / "policies" / "rule.md").exists())

    def test_promote_target_path_skills_dir_rejected(self):
        cand = self._reviewed_candidate(target="skill",
                                        rel="30-modules/sk.md")
        with self.assertRaises(PromotionError):
            knowledge_promote(self.repo, cand["id"], self.pack,
                              store=self.store, target_path="skills")
        self.assertFalse((self.pack / "skills").exists())

    # ── 21. P2-D: legacy reviewed candidate without sha256 can be re-reviewed ──

    def test_legacy_reviewed_without_sha256_can_repromote(self):
        _make_repo(self.repo, "30-modules/legacy.md", "# Legacy\n")
        cand = knowledge_candidate(self.repo, "30-modules/legacy.md", "reference",
                                   store=self.store)
        # Simulate a legacy registry entry: already reviewed but never bound.
        record = _find(self.store, self.repo, cand["id"])
        record["status"] = "reviewed"
        record["reviewed_sha256"] = None
        record["reviewer"] = "legacy-bot"
        import illuminate.promotion as promotion
        promotion._write_registry(
            self.store / "projects" / _derive_project_id(self.repo),
            [r for r in _candidates(self.store, self.repo) if r["id"] == record["id"]],
        )
        # Re-review completes the binding.
        reviewed = knowledge_review(self.repo, cand["id"], store=self.store,
                                    reviewer="alice")
        self.assertEqual(reviewed["status"], "reviewed")
        self.assertIsNotNone(reviewed["reviewed_sha256"])
        # And it can now be promoted.
        result = knowledge_promote(self.repo, cand["id"], self.pack, store=self.store)
        self.assertEqual(result["status"], "promoted")

    def test_review_bound_reviewed_still_rejected(self):
        cand = self._reviewed_candidate()
        with self.assertRaises(PromotionError):
            knowledge_review(self.repo, cand["id"], store=self.store)

    # ── 22. P2-E: evidence --force replacement removes orphan config ──

    def test_evidence_force_replace_removes_orphan_config(self):
        repo = Path(tempfile.mkdtemp())
        pack = _make_pack(Path(tempfile.mkdtemp()))
        # First evidence config.
        _make_repo(repo, "30-modules/old.md", "# Old tracer\n")
        c1 = knowledge_candidate(repo, "30-modules/old.md", "evidence",
                                 store=self.store)
        knowledge_review(repo, c1["id"], store=self.store)
        knowledge_promote(repo, c1["id"], pack, store=self.store)
        old_path = pack / "evidence" / "old.md"
        self.assertTrue(old_path.exists())
        # Replace with a new config via --force.
        _make_repo(repo, "30-modules/new.md", "# New tracer\n")
        c2 = knowledge_candidate(repo, "30-modules/new.md", "evidence",
                                 store=self.store)
        knowledge_review(repo, c2["id"], store=self.store)
        result = knowledge_promote(repo, c2["id"], pack, store=self.store, force=True)
        self.assertEqual(result["status"], "promoted")
        manifest = json.loads((pack / "pack.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["evidence"]["config"], "evidence/new.md")
        # Old config is no longer referenced and must be removed.
        self.assertFalse(old_path.exists())
        self.assertTrue((pack / "evidence" / "new.md").exists())


if __name__ == "__main__":
    unittest.main()
