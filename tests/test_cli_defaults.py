"""Tests for CLI argument defaults and `sync check` harness auto-detection.

Covers:
  - `--repo` defaults to "." for commands that now omit it.
  - `run --pack` defaults to the built-in Core Pack (while `mount create --pack`
    stays required).
  - `sync check` without `--harness` auto-detects synced harnesses from
    <repo>/.illuminate/ lock files.
"""

import argparse
import io
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from illuminate import cli
from illuminate.sync_codebuddy import sync_codebuddy
from illuminate.sync_codex import sync_codex
from illuminate.sync_cursor import sync_cursor

REPO_ROOT = Path(__file__).parent.parent
CORE_PACK = Path(__file__).parent.parent / "src" / "illuminate" / "builtin_pack"


class TestCliDefaults(unittest.TestCase):

    def _parse(self, argv):
        return cli._build_parser().parse_args(argv)

    # --repo default "."

    def test_repo_default_is_dot(self):
        cases = [
            ["mount", "create", "--pack", "x"],
            ["run"],
            ["sync", "codex"],
            ["sync", "codebuddy"],
            ["sync", "cursor"],
            ["sync", "check"],
            ["sync", "clean"],
            ["sync", "doctor"],
            ["codegraph", "check"],
            ["knowledge", "pull"],
            ["knowledge", "status"],
            ["knowledge", "push"],
            ["knowledge", "candidate", "--source", "x", "--target", "policy"],
            ["knowledge", "review", "--id", "x"],
            ["knowledge", "promote", "--id", "x", "--pack", "x"],
            ["knowledge", "reject", "--id", "x"],
            ["repo", "inspect"],
            ["evidence", "audit"],
        ]
        for argv in cases:
            args = self._parse(argv)
            self.assertEqual(
                args.repo, ".",
                f"{argv!r}: expected --repo default '.', got {args.repo!r}",
            )

    # --pack defaults

    def test_run_pack_default(self):
        self.assertIsNone(self._parse(["run"]).pack)

    def test_mount_create_pack_still_required(self):
        with self.assertRaises(SystemExit):
            self._parse(["mount", "create"])

    def test_mount_create_repo_still_resolvable(self):
        # --repo is optional now; supplying it explicitly must be accepted.
        args = self._parse(["mount", "create", "--pack", "x", "--repo", "/some/repo"])
        self.assertEqual(args.repo, "/some/repo")

    # sync check --harness default None

    def test_sync_check_harness_default_none(self):
        self.assertIsNone(self._parse(["sync", "check"]).harness)


class TestSyncCheckAutoDetect(unittest.TestCase):

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def _make_repo(self) -> Path:
        repo = self.tmpdir / "target-repo"
        repo.mkdir(parents=True, exist_ok=True)
        return repo

    def _run_check(self, repo: Path):
        args = argparse.Namespace(pack=str(CORE_PACK), repo=str(repo), harness=None)
        err = io.StringIO()
        with redirect_stderr(err):
            code = cli._cmd_sync_check(args)
        return code, err.getvalue()

    def test_single_lock_checks_only_that_harness(self):
        repo = self._make_repo()
        sync_codex(CORE_PACK, repo)
        self.assertTrue((repo / ".illuminate" / "codex-lock.json").exists())
        self.assertFalse((repo / ".illuminate" / "cursor-lock.json").exists())

        code, out = self._run_check(repo)
        self.assertEqual(code, 0)
        self.assertIn("Sync check (Codex): PASSED", out)
        self.assertNotIn("Sync check (Cursor):", out)
        self.assertNotIn("Sync check (CodeBuddy):", out)

    def test_multiple_locks_checks_all(self):
        repo = self._make_repo()
        sync_codex(CORE_PACK, repo)
        sync_cursor(CORE_PACK, repo)
        self.assertTrue((repo / ".illuminate" / "codex-lock.json").exists())
        self.assertTrue((repo / ".illuminate" / "cursor-lock.json").exists())

        code, out = self._run_check(repo)
        self.assertEqual(code, 0)
        self.assertIn("Sync check (Codex): PASSED", out)
        self.assertIn("Sync check (Cursor): PASSED", out)

    def test_no_lock_returns_one_with_prompt(self):
        repo = self._make_repo()
        code, out = self._run_check(repo)
        self.assertEqual(code, 1)
        self.assertIn("No harness synced yet", out)

    def test_explicit_harness_keeps_single_behavior(self):
        repo = self._make_repo()
        sync_cursor(CORE_PACK, repo)
        args = argparse.Namespace(pack=str(CORE_PACK), repo=str(repo), harness="cursor")
        err = io.StringIO()
        with redirect_stderr(err):
            code = cli._cmd_sync_check(args)
        self.assertEqual(code, 0)
        self.assertIn("Sync check (Cursor): PASSED", err.getvalue())

    def test_corrupt_lock_fails_closed_without_traceback(self):
        repo = self._make_repo()
        sync_codex(CORE_PACK, repo)
        lock_path = repo / ".illuminate" / "codex-lock.json"
        lock_path.write_text("{ not valid json", encoding="utf-8")

        code, out = self._run_check(repo)
        self.assertEqual(code, 1)
        self.assertIn("Sync check (Codex): FAILED", out)
        self.assertNotIn("Traceback", out)

    def test_multiple_locks_partial_failure_returns_one(self):
        repo = self._make_repo()
        sync_codex(CORE_PACK, repo)
        sync_cursor(CORE_PACK, repo)
        # Break the Codex sync by removing one managed skill file.
        skill_file = next((repo / ".agents" / "skills").glob("*/*.md"))
        skill_file.unlink()

        code, out = self._run_check(repo)
        self.assertEqual(code, 1)
        self.assertIn("Sync check (Codex): FAILED", out)
        self.assertIn("Sync check (Cursor): PASSED", out)

    def test_codebuddy_lock_auto_detect_label(self):
        repo = self._make_repo()
        sync_codebuddy(CORE_PACK, repo)

        code, out = self._run_check(repo)
        self.assertEqual(code, 0)
        self.assertIn("Sync check (CodeBuddy): PASSED", out)

    def test_check_with_missing_pack_returns_one(self):
        repo = self._make_repo()
        sync_codex(CORE_PACK, repo)
        args = argparse.Namespace(pack=str(repo / "no-such-pack"), repo=str(repo), harness=None)
        err = io.StringIO()
        with redirect_stderr(err):
            code = cli._cmd_sync_check(args)
        self.assertEqual(code, 1)
        self.assertIn("pack directory not found", err.getvalue())

    def test_illuminate_as_regular_file_gives_clear_error(self):
        repo = self._make_repo()
        (repo / ".illuminate").write_text("x", encoding="utf-8")

        code, out = self._run_check(repo)
        self.assertEqual(code, 1)
        self.assertIn("exists but is not a directory", out)

    def test_detect_synced_harnesses_empty_repo(self):
        repo = self._make_repo()
        self.assertEqual(cli._detect_synced_harnesses(repo), [])
