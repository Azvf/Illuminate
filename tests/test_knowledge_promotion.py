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
    knowledge_candidate,
    knowledge_promote,
    knowledge_reject,
    knowledge_review,
)


def _make_repo(root: Path, rel: str = "30-modules/demo.md", content: str = "") -> Path:
    """Construct repo_root/docs/<rel> and return the file path."""
    fpath = root / "docs" / rel
    fpath.parent.mkdir(parents=True, exist_ok=True)
    fpath.write_text(content or f"# {Path(rel).name}\n\nKnowledge content.\n", encoding="utf-8")
    return fpath


def _make_pack(root: Path, version: str = "0.1.0") -> Path:
    """Construct pack_dir/pack.json and return the pack dir."""
    pack_dir = root / "pack"
    pack_dir.mkdir(parents=True, exist_ok=True)
    (pack_dir / "pack.json").write_text(
        json.dumps({"name": "demo-pack", "version": version}), encoding="utf-8"
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
            self.assertEqual(result["written"], f"{subdir}/doc-{i}.md")
            self.assertTrue(
                (pack / subdir / f"doc-{i}.md").exists(),
                f"{target} should map to {subdir}/",
            )

    # ── 8. content_path generalization ──

    def test_promote_with_content_path(self):
        cand = self._reviewed_candidate()
        content = Path(tempfile.mkdtemp()) / "generalized.md"
        content.write_text("# Generalized\n\nDraft.\n", encoding="utf-8")
        result = knowledge_promote(self.repo, cand["id"], self.pack, store=self.store,
                                   content_path=content)
        self.assertTrue(result["generalized"])
        candidate = _find(self.store, self.repo, cand["id"])
        self.assertTrue(candidate["generalized"])
        # Pack file holds the generalized content
        self.assertEqual(
            (self.pack / "references" / "demo.md").read_text(encoding="utf-8"),
            content.read_text(encoding="utf-8"),
        )
        # Content copy stored under store promotions/<id>.md
        promoted_copy = (self.store / "projects" / _derive_project_id(self.repo)
                         / "promotions" / f"{cand['id']}.md")
        self.assertEqual(promoted_copy.read_text(encoding="utf-8"),
                         content.read_text(encoding="utf-8"))

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
        result = knowledge_promote(self.repo, cand["id"], self.pack, store=self.store,
                                   target_path="custom/landing.md")
        self.assertEqual(result["written"], "custom/landing.md")
        self.assertTrue((self.pack / "custom" / "landing.md").exists())

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


if __name__ == "__main__":
    unittest.main()
