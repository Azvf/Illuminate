"""Tests for evidence audit."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from illuminate.evidence.audit import run_audit
from illuminate.evidence.patterns_provider import _load_config


class TestEvidence(unittest.TestCase):

    def test_load_config_uses_pack_defaults(self):
        config, sources = _load_config(Path("."))
        self.assertGreater(len(config["abstraction_keywords"]), 0)
        self.assertGreater(len(sources), 1)

    def test_run_audit_on_self(self):
        repo_root = Path(__file__).parent.parent
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "evidence.json"
            evidence = run_audit(repo_root, output_path=output, quiet=True)
            self.assertEqual(evidence["schema_version"], 1)
            self.assertIn("tool", evidence)
            self.assertIn("pack", evidence)
            self.assertEqual(evidence["tool"]["name"], "illuminate")

    def test_audit_output_file_written(self):
        repo_root = Path(__file__).parent.parent
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "sub" / "evidence.json"
            run_audit(repo_root, output_path=output, quiet=True)
            self.assertTrue(output.exists())
            data = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(data["schema_version"], 1)


if __name__ == "__main__":
    unittest.main()
