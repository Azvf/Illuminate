"""Tests for the CodeGraph CLI boundary (illuminate.codegraph)."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from illuminate.codegraph import check_codegraph


def _repo_with_graph() -> Path:
    repo = Path(tempfile.mkdtemp())
    (repo / ".codegraph").mkdir()
    return repo


def _bare_repo() -> Path:
    return Path(tempfile.mkdtemp())


class TestCodegraphCheck(unittest.TestCase):

    def test_cli_missing(self):
        with mock.patch("illuminate.codegraph.shutil.which", return_value=None):
            report = check_codegraph(_bare_repo())
        self.assertFalse(report["cli_available"])
        self.assertTrue(any("not found on PATH" in i for i in report["issues"]))
        self.assertFalse(report["graph_dir_exists"])
        self.assertIsNone(report["status"])

    def test_cli_present_but_not_initialized(self):
        with mock.patch("illuminate.codegraph.shutil.which", return_value="/usr/bin/codegraph"):
            report = check_codegraph(_bare_repo())
        self.assertTrue(report["cli_available"])
        self.assertFalse(report["graph_dir_exists"])
        self.assertTrue(any("codegraph init" in i for i in report["issues"]))

    def test_status_failure(self):
        proc = mock.Mock(returncode=1, stdout="", stderr="boom")
        with mock.patch("illuminate.codegraph.shutil.which", return_value="codegraph"), \
             mock.patch("illuminate.codegraph.subprocess.run", return_value=proc):
            report = check_codegraph(_repo_with_graph())
        self.assertEqual(report["status_error"], "boom")
        self.assertTrue(any("exited 1" in i for i in report["issues"]))

    def test_status_timeout(self):
        def _raise(*args, **kwargs):
            raise subprocess.TimeoutExpired("codegraph", 10)
        with mock.patch("illuminate.codegraph.shutil.which", return_value="codegraph"), \
             mock.patch("illuminate.codegraph.subprocess.run", side_effect=_raise):
            report = check_codegraph(_repo_with_graph())
        self.assertTrue(report["status_error"])
        self.assertTrue(any("probe failed" in i for i in report["issues"]))

    def test_status_non_json(self):
        proc = mock.Mock(returncode=0, stdout="not json", stderr="")
        with mock.patch("illuminate.codegraph.shutil.which", return_value="codegraph"), \
             mock.patch("illuminate.codegraph.subprocess.run", return_value=proc):
            report = check_codegraph(_repo_with_graph())
        self.assertTrue(any("non-JSON" in i for i in report["issues"]))
        self.assertIsNone(report["status"])

    def test_status_oserror(self):
        def _raise(*args, **kwargs):
            raise OSError("cwd not found")
        with mock.patch("illuminate.codegraph.shutil.which", return_value="codegraph"), \
             mock.patch("illuminate.codegraph.subprocess.run", side_effect=_raise):
            report = check_codegraph(_repo_with_graph())
        self.assertTrue(report["status_error"])
        self.assertTrue(any("probe failed" in i for i in report["issues"]))

    def test_status_invalid_timeout_value(self):
        def _raise(*args, **kwargs):
            raise ValueError("timeout must be positive")
        with mock.patch("illuminate.codegraph.shutil.which", return_value="codegraph"), \
             mock.patch("illuminate.codegraph.subprocess.run", side_effect=_raise):
            report = check_codegraph(_repo_with_graph())
        self.assertTrue(report["status_error"])
        self.assertTrue(any("probe failed" in i for i in report["issues"]))

    def test_status_top_level_not_object(self):
        proc = mock.Mock(returncode=0, stdout="[1,2,3]", stderr="")
        with mock.patch("illuminate.codegraph.shutil.which", return_value="codegraph"), \
             mock.patch("illuminate.codegraph.subprocess.run", return_value=proc):
            report = check_codegraph(_repo_with_graph())
        self.assertTrue(any("non-object" in i for i in report["issues"]))
        self.assertIsNone(report["status"])

    def test_healthy(self):
        status = {"files": 10, "symbols": 5, "last_sync": "2026-08-06T00:00:00Z"}
        proc = mock.Mock(returncode=0, stdout=json.dumps(status), stderr="")
        with mock.patch("illuminate.codegraph.shutil.which", return_value="codegraph"), \
             mock.patch("illuminate.codegraph.subprocess.run", return_value=proc):
            report = check_codegraph(_repo_with_graph())
        self.assertEqual(report["issues"], [])
        self.assertTrue(report["cli_available"])
        self.assertTrue(report["graph_dir_exists"])
        self.assertEqual(report["status"], status)
        self.assertIsNone(report["status_error"])


if __name__ == "__main__":
    unittest.main()
