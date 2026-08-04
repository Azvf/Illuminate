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
    promote_policy,
    promote_reference,
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
            if target == "skill":
                # Skills must carry a legal frontmatter or validate_pack fails.
                content = f"---\nname: doc-{i}\ndescription: Test skill {i}\n---\n# Doc {i}\n"
            else:
                content = ""
            _make_repo(repo, rel, content)
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

    # ── 8. draft-review (content bound at review, consumed at promote) ──

    def test_promote_with_content_path(self):
        # review --content binds a draft; promote writes that exact draft bytes.
        _make_repo(self.repo, content="# source\n")
        cand = knowledge_candidate(self.repo, "30-modules/demo.md", "reference",
                                   store=self.store)
        draft = Path(tempfile.mkdtemp()) / "draft.md"
        draft.write_text("# Generalized draft\n", encoding="utf-8")
        reviewed = knowledge_review(self.repo, cand["id"], store=self.store,
                                    content_path=draft)
        self.assertTrue(reviewed["generalized"])
        self.assertEqual(reviewed["reviewed_sha256"], _sha256(draft.read_text(encoding="utf-8")))
        # Draft snapshot stored under store promotions/<id>/draft.md at review.
        draft_copy = (self.store / "projects" / _derive_project_id(self.repo)
                      / "promotions" / cand["id"] / "draft.md")
        self.assertTrue(draft_copy.exists())
        self.assertEqual(draft_copy.read_text(encoding="utf-8"),
                         draft.read_text(encoding="utf-8"))

        result = knowledge_promote(self.repo, cand["id"], self.pack, store=self.store)
        self.assertTrue(result["generalized"])
        candidate = _find(self.store, self.repo, cand["id"])
        self.assertTrue(candidate["generalized"])
        # Pack file holds the reviewed draft content.
        self.assertEqual(
            (self.pack / "references" / "demo.md").read_text(encoding="utf-8"),
            draft.read_text(encoding="utf-8"),
        )

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
                                  supersede=True, pack_dir=self.pack)
        self.assertEqual(result["status"], "superseded")
        # The promoted artifact is removed from the pack on supersede.
        self.assertFalse((self.pack / "references" / "demo.md").exists())

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
        skill_content = "---\nname: my-skill\ndescription: Test skill\n---\n# My skill\n"
        _make_repo(repo, "30-modules/my-skill.md", skill_content)
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
        _make_repo(self.repo, "30-modules/demo.md",
                   "---\nname: demo\ndescription: Skill A\n---\n# Skill A\n")
        c1 = knowledge_candidate(self.repo, "30-modules/demo.md", "skill",
                                 store=self.store)
        knowledge_review(self.repo, c1["id"], store=self.store)
        knowledge_promote(self.repo, c1["id"], self.pack, store=self.store)

        content_b = "---\nname: demo\ndescription: Skill B\n---\n# Skill B\n"
        _make_repo(self.repo, "30-modules/other.md", content_b)
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
            content_b,
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
        # The staged policy file must be rolled back, leaving no residual.
        self.assertFalse((pack / "policies" / "rule.md").exists())

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
        _make_repo(repo, "30-modules/fresh.md",
                   "---\nname: fresh\ndescription: Fresh skill\n---\n# Fresh skill\n")
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


    # ── 23. P3: draft-review + candidate-id with content/target ──

    def test_review_content_binds_draft_hash(self):
        _make_repo(self.repo, content="# source\n")
        cand = knowledge_candidate(self.repo, "30-modules/demo.md", "reference",
                                   store=self.store)
        draft = Path(tempfile.mkdtemp()) / "draft.md"
        draft.write_text("# Reviewed draft\n", encoding="utf-8")
        reviewed = knowledge_review(self.repo, cand["id"], store=self.store,
                                    content_path=draft)
        self.assertEqual(reviewed["reviewed_sha256"],
                         _sha256(draft.read_text(encoding="utf-8")))
        self.assertTrue(reviewed["generalized"])

    def test_promote_skill_without_frontmatter_fails(self):
        repo = Path(tempfile.mkdtemp())
        pack = _make_pack(Path(tempfile.mkdtemp()))
        _make_repo(repo, "30-modules/nofm.md", "# No fm\n")
        cand = knowledge_candidate(repo, "30-modules/nofm.md", "skill",
                                   store=self.store)
        knowledge_review(repo, cand["id"], store=self.store)
        before = (pack / "pack.json").read_bytes()
        with self.assertRaises(PromotionError):
            knowledge_promote(repo, cand["id"], pack, store=self.store)
        # No residual in the pack: skill dir rolled back, manifest restored.
        self.assertFalse((pack / "skills" / "nofm").exists())
        self.assertEqual((pack / "pack.json").read_bytes(), before)
        candidate = _find(self.store, repo, cand["id"])
        self.assertEqual(candidate["status"], "reviewed")

    def test_candidate_id_changes_with_content(self):
        # Non-git repo: source_sha256 participates in the id, so editing the
        # file content yields a different candidate id.
        _make_repo(self.repo, content="# v1\n")
        first = knowledge_candidate(self.repo, "30-modules/demo.md", "reference",
                                    store=self.store)
        _make_repo(self.repo, content="# v2\n")
        second = knowledge_candidate(self.repo, "30-modules/demo.md", "reference",
                                     store=self.store)
        self.assertNotEqual(first["id"], second["id"])

    def test_candidate_id_differs_by_target(self):
        _make_repo(self.repo, content="# shared\n")
        as_reference = knowledge_candidate(self.repo, "30-modules/demo.md",
                                           "reference", store=self.store)
        as_policy = knowledge_candidate(self.repo, "30-modules/demo.md",
                                        "policy", store=self.store)
        self.assertNotEqual(as_reference["id"], as_policy["id"])

    # ── 24. P4: reference/policy --force in-place upgrade ──

    def test_promote_reference_force_upgrades_existing(self):
        _make_repo(self.repo, content="# v1\n")
        c1 = knowledge_candidate(self.repo, "30-modules/demo.md", "reference",
                                 store=self.store)
        knowledge_review(self.repo, c1["id"], store=self.store)
        knowledge_promote(self.repo, c1["id"], self.pack, store=self.store)
        target = self.pack / "references" / "demo.md"
        self.assertEqual(target.read_text(encoding="utf-8"), "# v1\n")

        # Changed content → different candidate id, same source path & target.
        _make_repo(self.repo, content="# v2\n")
        c2 = knowledge_candidate(self.repo, "30-modules/demo.md", "reference",
                                 store=self.store)
        self.assertNotEqual(c1["id"], c2["id"])
        knowledge_review(self.repo, c2["id"], store=self.store)
        # Without --force a same-id entry is still rejected.
        with self.assertRaises(PromotionError):
            knowledge_promote(self.repo, c2["id"], self.pack, store=self.store)
        # --force upgrades in place: single manifest entry, path unchanged,
        # content now the new reviewed bytes.
        result = knowledge_promote(self.repo, c2["id"], self.pack, store=self.store,
                                   force=True)
        self.assertEqual(result["status"], "promoted")
        manifest = json.loads((self.pack / "pack.json").read_text(encoding="utf-8"))
        self.assertEqual(len(manifest["references"]), 1)
        self.assertEqual(manifest["references"][0]["id"], "demo.pack.demo")
        self.assertEqual(manifest["references"][0]["path"], "references/demo.md")
        self.assertEqual(target.read_text(encoding="utf-8"), "# v2\n")

    def test_promote_policy_force_upgrades_existing(self):
        _make_repo(self.repo, "30-modules/rule.md", "# Rule v1\n")
        c1 = knowledge_candidate(self.repo, "30-modules/rule.md", "policy",
                                 store=self.store)
        knowledge_review(self.repo, c1["id"], store=self.store)
        knowledge_promote(self.repo, c1["id"], self.pack, store=self.store)

        _make_repo(self.repo, "30-modules/rule.md", "# Rule v2\n")
        c2 = knowledge_candidate(self.repo, "30-modules/rule.md", "policy",
                                 store=self.store)
        self.assertNotEqual(c1["id"], c2["id"])
        knowledge_review(self.repo, c2["id"], store=self.store)
        with self.assertRaises(PromotionError):
            knowledge_promote(self.repo, c2["id"], self.pack, store=self.store)
        result = knowledge_promote(self.repo, c2["id"], self.pack, store=self.store,
                                   force=True)
        self.assertEqual(result["status"], "promoted")
        index = json.loads(
            (self.pack / "policies" / "index.json").read_text(encoding="utf-8")
        )
        self.assertEqual(len(index["policies"]), 1)
        self.assertEqual(index["policies"][0]["id"], "demo.pack.rule")
        self.assertEqual(index["policies"][0]["path"], "rule.md")
        self.assertEqual(
            (self.pack / "policies" / "rule.md").read_text(encoding="utf-8"),
            "# Rule v2\n",
        )

    # ── 25. P5: supersede removes the pack artifact and binds registry ──

    def test_reject_supersede_removes_reference_from_pack(self):
        cand = self._reviewed_candidate()
        knowledge_promote(self.repo, cand["id"], self.pack, store=self.store)
        self.assertTrue((self.pack / "references" / "demo.md").exists())
        result = knowledge_reject(self.repo, cand["id"], store=self.store,
                                  supersede=True, pack_dir=self.pack)
        self.assertEqual(result["status"], "superseded")
        self.assertFalse((self.pack / "references" / "demo.md").exists())
        manifest = json.loads((self.pack / "pack.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["references"], [])
        ok, errors = validate_pack(self.pack)
        self.assertTrue(ok, errors)
        candidate = _find(self.store, self.repo, cand["id"])
        self.assertEqual(candidate["status"], "superseded")
        self.assertIsNotNone(candidate.get("superseded_at"))

    def test_reject_supersede_removes_policy_skill_evidence(self):
        # policy
        repo = Path(tempfile.mkdtemp())
        pack = _make_pack(Path(tempfile.mkdtemp()))
        _make_repo(repo, "30-modules/rule.md", "# Rule\n")
        c = knowledge_candidate(repo, "30-modules/rule.md", "policy",
                                store=self.store)
        knowledge_review(repo, c["id"], store=self.store)
        knowledge_promote(repo, c["id"], pack, store=self.store)
        self.assertTrue((pack / "policies" / "rule.md").exists())
        knowledge_reject(repo, c["id"], store=self.store, supersede=True, pack_dir=pack)
        self.assertFalse((pack / "policies" / "rule.md").exists())
        index = json.loads((pack / "policies" / "index.json").read_text(encoding="utf-8"))
        self.assertEqual(index["policies"], [])

        # skill (directory removed: SKILL.md + contract.json + manifest entry)
        repo2 = Path(tempfile.mkdtemp())
        pack2 = _make_pack(Path(tempfile.mkdtemp()))
        skill_content = "---\nname: my-skill\ndescription: Test skill\n---\n# My skill\n"
        _make_repo(repo2, "30-modules/my-skill.md", skill_content)
        c2 = knowledge_candidate(repo2, "30-modules/my-skill.md", "skill",
                                 store=self.store)
        knowledge_review(repo2, c2["id"], store=self.store)
        knowledge_promote(repo2, c2["id"], pack2, store=self.store)
        self.assertTrue((pack2 / "skills" / "my-skill" / "SKILL.md").exists())
        knowledge_reject(repo2, c2["id"], store=self.store, supersede=True, pack_dir=pack2)
        self.assertFalse((pack2 / "skills" / "my-skill").exists())
        manifest2 = json.loads((pack2 / "pack.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest2["skills"], [])

        # evidence (config cleared + file removed)
        repo3 = Path(tempfile.mkdtemp())
        pack3 = _make_pack(Path(tempfile.mkdtemp()))
        _make_repo(repo3, "30-modules/tracer.md", "# Tracer\n")
        c3 = knowledge_candidate(repo3, "30-modules/tracer.md", "evidence",
                                 store=self.store)
        knowledge_review(repo3, c3["id"], store=self.store)
        knowledge_promote(repo3, c3["id"], pack3, store=self.store)
        self.assertTrue((pack3 / "evidence" / "tracer.md").exists())
        knowledge_reject(repo3, c3["id"], store=self.store, supersede=True, pack_dir=pack3)
        self.assertFalse((pack3 / "evidence" / "tracer.md").exists())
        manifest3 = json.loads((pack3 / "pack.json").read_text(encoding="utf-8"))
        self.assertNotIn("config", manifest3.get("evidence", {}))
        ok3, errors3 = validate_pack(pack3)
        self.assertTrue(ok3, errors3)

    def test_reject_supersede_validate_failure_restores_pack(self):
        cand = self._reviewed_candidate()
        knowledge_promote(self.repo, cand["id"], self.pack, store=self.store)
        # Inject a broken reference (missing file) so validate_pack must fail
        # even after our reference is removed.
        manifest = json.loads((self.pack / "pack.json").read_text(encoding="utf-8"))
        manifest.setdefault("references", []).append(
            {"id": "demo.pack.broken", "path": "references/broken.md"}
        )
        (self.pack / "pack.json").write_text(json.dumps(manifest), encoding="utf-8")
        before = (self.pack / "pack.json").read_bytes()
        ref_file = self.pack / "references" / "demo.md"
        with self.assertRaises(PromotionError):
            knowledge_reject(self.repo, cand["id"], store=self.store,
                             supersede=True, pack_dir=self.pack)
        # Pack fully restored to the pre-supersede bytes (broken ref included).
        self.assertEqual((self.pack / "pack.json").read_bytes(), before)
        self.assertTrue(ref_file.exists())
        candidate = _find(self.store, self.repo, cand["id"])
        self.assertEqual(candidate["status"], "promoted")

    def test_reject_supersede_requires_promoted_and_pack(self):
        cand = self._reviewed_candidate()
        knowledge_promote(self.repo, cand["id"], self.pack, store=self.store)
        # Missing pack_dir is rejected for a promoted candidate.
        with self.assertRaises(PromotionError):
            knowledge_reject(self.repo, cand["id"], store=self.store, supersede=True)
        # Non-promoted status is rejected even with pack_dir.
        repo = Path(tempfile.mkdtemp())
        _make_repo(repo, "30-modules/other.md")
        raw = knowledge_candidate(repo, "30-modules/other.md", "reference",
                                  store=self.store)
        with self.assertRaises(PromotionError):
            knowledge_reject(repo, raw["id"], store=self.store, supersede=True,
                             pack_dir=Path(tempfile.mkdtemp()))

    # ── 26. P6: renamed reference/policy upgrade via explicit --replaces ──

    def test_promote_reference_force_change_basename_via_replaces(self):
        # v1 occupies references/demo.md (id demo.pack.demo). A successor
        # candidate declares --replaces c1 and force-upgrades the SAME artifact
        # to a new basename references/sub/b.md through the public
        # candidate/review/promote flow (no manual previous_target_path).
        pack = _make_pack(Path(tempfile.mkdtemp()))
        _make_repo(self.repo, "30-modules/demo.md", "# old\n")
        c1 = knowledge_candidate(self.repo, "30-modules/demo.md", "reference",
                                 store=self.store)
        knowledge_review(self.repo, c1["id"], store=self.store)
        knowledge_promote(self.repo, c1["id"], pack, store=self.store)
        self.assertEqual(
            (pack / "references" / "demo.md").read_text(encoding="utf-8"), "# old\n"
        )

        # Changed content -> a different candidate id, same source path/target.
        _make_repo(self.repo, "30-modules/demo.md", "# new\n")
        c2 = knowledge_candidate(self.repo, "30-modules/demo.md", "reference",
                                 store=self.store, replaces=c1["id"])
        self.assertNotEqual(c1["id"], c2["id"])
        knowledge_review(self.repo, c2["id"], store=self.store)
        result = knowledge_promote(self.repo, c2["id"], pack, store=self.store,
                                   target_path="references/sub/b.md", force=True)
        self.assertEqual(result["status"], "promoted")
        self.assertEqual(result["written"], "references/sub/b.md")
        manifest = json.loads((pack / "pack.json").read_text(encoding="utf-8"))
        self.assertEqual(len(manifest["references"]), 1)
        self.assertEqual(
            manifest["references"][0],
            {"id": "demo.pack.b", "path": "references/sub/b.md"},
        )
        self.assertFalse((pack / "references" / "demo.md").exists())
        self.assertEqual(
            (pack / "references" / "sub" / "b.md").read_text(encoding="utf-8"), "# new\n"
        )
        ok, errors = validate_pack(pack)
        self.assertTrue(ok, errors)
        # The replaced candidate is atomically marked superseded.
        c1_after = _find(self.store, self.repo, c1["id"])
        self.assertEqual(c1_after["status"], "superseded")
        self.assertEqual(c1_after.get("superseded_by"), c2["id"])
        # The successor recorded a published snapshot.
        c2_after = _find(self.store, self.repo, c2["id"])
        self.assertEqual(c2_after["published"]["entry_id"], "demo.pack.b")
        self.assertEqual(c2_after["published"]["target_path"], "references/sub/b.md")

    def test_promote_policy_force_change_basename_via_replaces(self):
        # v1 occupies policies/rule.md (id demo.pack.rule); a successor
        # candidate with --replaces c1 upgrades the same artifact in place to
        # policies/renamed.md through the public flow.
        pack = _make_pack(Path(tempfile.mkdtemp()))
        _make_repo(self.repo, "30-modules/rule.md", "# Rule v1\n")
        c1 = knowledge_candidate(self.repo, "30-modules/rule.md", "policy",
                                 store=self.store)
        knowledge_review(self.repo, c1["id"], store=self.store)
        knowledge_promote(self.repo, c1["id"], pack, store=self.store)

        _make_repo(self.repo, "30-modules/rule.md", "# Rule v2\n")
        c2 = knowledge_candidate(self.repo, "30-modules/rule.md", "policy",
                                 store=self.store, replaces=c1["id"])
        self.assertNotEqual(c1["id"], c2["id"])
        knowledge_review(self.repo, c2["id"], store=self.store)
        result = knowledge_promote(self.repo, c2["id"], pack, store=self.store,
                                   target_path="policies/renamed.md", force=True)
        self.assertEqual(result["written"], "policies/renamed.md")
        index = json.loads((pack / "policies" / "index.json").read_text(encoding="utf-8"))
        self.assertEqual(len(index["policies"]), 1)
        self.assertEqual(
            index["policies"][0],
            {"id": "demo.pack.renamed", "path": "renamed.md", "priority": 0},
        )
        self.assertFalse((pack / "policies" / "rule.md").exists())
        self.assertEqual(
            (pack / "policies" / "renamed.md").read_text(encoding="utf-8"), "# Rule v2\n"
        )
        ok, errors = validate_pack(pack)
        self.assertTrue(ok, errors)
        c1_after = _find(self.store, self.repo, c1["id"])
        self.assertEqual(c1_after["status"], "superseded")
        self.assertEqual(c1_after.get("superseded_by"), c2["id"])

    def test_replaces_refuses_overwriting_unrelated_reference(self):
        # A third-party entry already owns the new path/id; a renamed upgrade
        # with --replaces must refuse rather than overwrite it.
        pack = _make_pack(Path(tempfile.mkdtemp()))
        _make_repo(self.repo, "30-modules/demo.md", "# v1\n")
        c1 = knowledge_candidate(self.repo, "30-modules/demo.md", "reference",
                                 store=self.store)
        knowledge_review(self.repo, c1["id"], store=self.store)
        knowledge_promote(self.repo, c1["id"], pack, store=self.store)
        # A separate reference already occupies the target new path.
        _make_repo(self.repo, "30-modules/other.md", "# other\n")
        other = knowledge_candidate(self.repo, "30-modules/other.md", "reference",
                                    store=self.store)
        knowledge_review(self.repo, other["id"], store=self.store)
        knowledge_promote(self.repo, other["id"], pack, store=self.store,
                          target_path="references/b.md")
        # c2 tries to take over references/b.md as a rename of c1.
        _make_repo(self.repo, "30-modules/demo.md", "# v2\n")
        c2 = knowledge_candidate(self.repo, "30-modules/demo.md", "reference",
                                 store=self.store, replaces=c1["id"])
        knowledge_review(self.repo, c2["id"], store=self.store)
        with self.assertRaises(PromotionError):
            knowledge_promote(self.repo, c2["id"], pack, store=self.store,
                              target_path="references/b.md", force=True)
        # The unrelated reference is untouched.
        self.assertEqual(
            (pack / "references" / "b.md").read_text(encoding="utf-8"), "# other\n"
        )
        c2_after = _find(self.store, self.repo, c2["id"])
        self.assertEqual(c2_after["status"], "reviewed")

    def test_replaces_refuses_overwriting_unrelated_policy(self):
        # A third-party policy already owns the new path/id; a renamed upgrade
        # with --replaces must refuse rather than overwrite it.
        pack = _make_pack(Path(tempfile.mkdtemp()))
        _make_repo(self.repo, "30-modules/rule.md", "# Rule v1\n")
        c1 = knowledge_candidate(self.repo, "30-modules/rule.md", "policy",
                                 store=self.store)
        knowledge_review(self.repo, c1["id"], store=self.store)
        knowledge_promote(self.repo, c1["id"], pack, store=self.store)
        # A separate policy already occupies the target new path/id.
        _make_repo(self.repo, "30-modules/renamed.md", "# Other rule\n")
        other = knowledge_candidate(self.repo, "30-modules/renamed.md", "policy",
                                    store=self.store)
        knowledge_review(self.repo, other["id"], store=self.store)
        knowledge_promote(self.repo, other["id"], pack, store=self.store,
                          target_path="policies/renamed.md")
        # c2 tries to take over policies/renamed.md as a rename of c1.
        _make_repo(self.repo, "30-modules/rule.md", "# Rule v2\n")
        c2 = knowledge_candidate(self.repo, "30-modules/rule.md", "policy",
                                 store=self.store, replaces=c1["id"])
        knowledge_review(self.repo, c2["id"], store=self.store)
        with self.assertRaises(PromotionError):
            knowledge_promote(self.repo, c2["id"], pack, store=self.store,
                              target_path="policies/renamed.md", force=True)
        # The unrelated policy is untouched.
        self.assertEqual(
            (pack / "policies" / "renamed.md").read_text(encoding="utf-8"),
            "# Other rule\n",
        )
        c2_after = _find(self.store, self.repo, c2["id"])
        self.assertEqual(c2_after["status"], "reviewed")

    def test_replaces_requires_promoted_predecessor(self):
        # --replaces pointing at a non-promoted candidate is rejected at promote.
        _make_repo(self.repo, "30-modules/demo.md", "# v1\n")
        raw = knowledge_candidate(self.repo, "30-modules/demo.md", "reference",
                                  store=self.store)
        _make_repo(self.repo, "30-modules/demo.md", "# v2\n")
        c2 = knowledge_candidate(self.repo, "30-modules/demo.md", "reference",
                                 store=self.store, replaces=raw["id"])
        knowledge_review(self.repo, c2["id"], store=self.store)
        with self.assertRaises(PromotionError):
            knowledge_promote(self.repo, c2["id"], self.pack, store=self.store, force=True)

    # ── 26b. P0-1: ownership binding prevents deleting another version's bytes ──

    def test_supersede_refuses_when_artifact_taken_over_by_later_force(self):
        # v1 promote -> v2 --force overwrites the same path (same stem, same
        # manifest entry id). Superseding v1 must refuse: the artifact now holds
        # v2's bytes, which v1 no longer owns.
        cand = self._reviewed_candidate(content="# v1\n")
        knowledge_promote(self.repo, cand["id"], self.pack, store=self.store)
        _make_repo(self.repo, content="# v2\n")
        c2 = knowledge_candidate(self.repo, "30-modules/demo.md", "reference",
                                 store=self.store)
        knowledge_review(self.repo, c2["id"], store=self.store)
        knowledge_promote(self.repo, c2["id"], self.pack, store=self.store, force=True)
        self.assertEqual(
            (self.pack / "references" / "demo.md").read_text(encoding="utf-8"), "# v2\n"
        )
        # Superseding v1 refuses; the artifact (v2's content) is untouched.
        with self.assertRaises(PromotionError):
            knowledge_reject(self.repo, cand["id"], store=self.store,
                             supersede=True, pack_dir=self.pack)
        self.assertTrue((self.pack / "references" / "demo.md").exists())
        self.assertEqual(
            (self.pack / "references" / "demo.md").read_text(encoding="utf-8"), "# v2\n"
        )
        # v1 stays promoted (its artifact was not removed).
        self.assertEqual(
            _find(self.store, self.repo, cand["id"])["status"], "promoted"
        )
        # v2 still owns the artifact and superseding v2 removes it cleanly.
        result = knowledge_reject(self.repo, c2["id"], store=self.store,
                                  supersede=True, pack_dir=self.pack)
        self.assertEqual(result["status"], "superseded")
        self.assertFalse((self.pack / "references" / "demo.md").exists())
        manifest = json.loads((self.pack / "pack.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["references"], [])
        ok, errors = validate_pack(self.pack)
        self.assertTrue(ok, errors)

    def test_supersede_records_published_snapshot(self):
        # A successful promote records the published snapshot (pack id, entry
        # id, target path, content sha256, pack version).
        cand = self._reviewed_candidate(content="# snap\n")
        knowledge_promote(self.repo, cand["id"], self.pack, store=self.store)
        candidate = _find(self.store, self.repo, cand["id"])
        published = candidate.get("published")
        self.assertIsNotNone(published)
        self.assertEqual(published["pack_id"], "demo.pack")
        self.assertEqual(published["entry_id"], "demo.pack.demo")
        self.assertEqual(published["target_path"], "references/demo.md")
        self.assertEqual(published["content_sha256"], _sha256("# snap\n"))
        self.assertEqual(published["pack_version"], "0.1.0")
        # And a normal supersede (still owning the bytes) succeeds.
        result = knowledge_reject(self.repo, cand["id"], store=self.store,
                                  supersede=True, pack_dir=self.pack)
        self.assertEqual(result["status"], "superseded")

    # ── 27. P7: skill supersede rollback restores nested files ──

    def test_reject_supersede_skill_nested_dir_restored_on_validate_failure(self):
        repo = Path(tempfile.mkdtemp())
        pack = _make_pack(Path(tempfile.mkdtemp()))
        skill_content = "---\nname: nested-skill\ndescription: Test skill\n---\n# Skill\n"
        _make_repo(repo, "30-modules/nested-skill.md", skill_content)
        c = knowledge_candidate(repo, "30-modules/nested-skill.md", "skill",
                                store=self.store)
        knowledge_review(repo, c["id"], store=self.store)
        knowledge_promote(repo, c["id"], pack, store=self.store)
        # Manually extend the skill dir with a nested subdirectory file.
        nested = pack / "skills" / "nested-skill" / "sub" / "extra.md"
        nested.parent.mkdir(parents=True, exist_ok=True)
        nested.write_text("# extra\n", encoding="utf-8")
        # Inject a broken reference so validate_pack fails during supersede.
        manifest = json.loads((pack / "pack.json").read_text(encoding="utf-8"))
        manifest.setdefault("references", []).append(
            {"id": "demo.pack.broken", "path": "references/broken.md"}
        )
        (pack / "pack.json").write_text(json.dumps(manifest), encoding="utf-8")
        before_pack = (pack / "pack.json").read_bytes()

        with self.assertRaises(PromotionError):
            knowledge_reject(repo, c["id"], store=self.store, supersede=True,
                             pack_dir=pack)
        # The whole skill subtree (including the nested file) is restored.
        self.assertEqual((pack / "pack.json").read_bytes(), before_pack)
        self.assertTrue((pack / "skills" / "nested-skill" / "SKILL.md").exists())
        self.assertTrue(nested.exists())
        self.assertEqual(nested.read_text(encoding="utf-8"), "# extra\n")
        candidate = _find(self.store, repo, c["id"])
        self.assertEqual(candidate["status"], "promoted")


if __name__ == "__main__":
    unittest.main()
