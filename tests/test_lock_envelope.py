"""Cross-adapter tests for the public lock envelope."""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from illuminate.materialize_claude import materialize_session
from illuminate.sync_codebuddy import sync_codebuddy
from illuminate.sync_codex import sync_codex


REPO_ROOT = Path(__file__).parent.parent
CORE_PACK = REPO_ROOT / "packs" / "core"
COMMON_FIELDS = {
    "schema_version",
    "harness",
    "pack",
    "target",
    "selection",
    "managed_artifacts",
}


class TestLockEnvelope(unittest.TestCase):
    def test_all_adapter_locks_include_common_envelope(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            claude_repo = root / "claude-repo"
            codex_repo = root / "codex-repo"
            codebuddy_repo = root / "codebuddy-repo"
            claude_repo.mkdir()
            codex_repo.mkdir()
            codebuddy_repo.mkdir()
            session_base = root / "sessions"

            with patch(
                "illuminate.materialize_claude._get_session_base",
                return_value=session_base,
            ):
                claude_info = materialize_session(CORE_PACK, str(claude_repo))
            sync_codex(CORE_PACK, codex_repo)
            sync_codebuddy(CORE_PACK, codebuddy_repo)

            locks = [
                claude_info["lock"],
                json.loads(
                    (codex_repo / ".illuminate" / "codex-lock.json").read_text(
                        encoding="utf-8"
                    )
                ),
                json.loads(
                    (codebuddy_repo / ".illuminate" / "codebuddy-lock.json").read_text(
                        encoding="utf-8"
                    )
                ),
            ]
            self.assertEqual(
                [lock["harness"] for lock in locks],
                ["claude-code", "codex", "codebuddy"],
            )

            for lock in locks:
                self.assertTrue(COMMON_FIELDS.issubset(lock))
                self.assertEqual(lock["schema_version"], 1)
                self.assertEqual(
                    set(lock["pack"]), {"id", "version", "hash"}
                )
                self.assertTrue(lock["pack"]["hash"].startswith("sha256:"))
                self.assertIsInstance(lock["target"], dict)
                self.assertIn("path", lock["target"])
                self.assertEqual(
                    lock["selection"]["skills"], lock["exposed_skills"]
                )
                self.assertEqual(
                    lock["managed_artifacts"],
                    sorted(set(lock["managed_artifacts"])),
                )
                self.assertTrue(lock["managed_artifacts"])

            self.assertEqual(
                [lock["target"]["path"] for lock in locks],
                [
                    str(claude_repo.resolve()),
                    str(codex_repo.resolve()),
                    str(codebuddy_repo.resolve()),
                ],
            )

    def test_capabilities_present_in_every_adapter_lock(self):
        """capabilities must be present in all three locks: Claude reports
        permission enforcement status, sync adapters are declarative-only."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            codex_repo = root / "codex-repo"
            codebuddy_repo = root / "codebuddy-repo"
            claude_repo = root / "claude-repo"
            codex_repo.mkdir()
            codebuddy_repo.mkdir()
            claude_repo.mkdir()
            session_base = root / "sessions"
            with patch(
                "illuminate.materialize_claude._get_session_base",
                return_value=session_base,
            ):
                claude_info = materialize_session(CORE_PACK, str(claude_repo))
            sync_codex(CORE_PACK, codex_repo)
            sync_codebuddy(CORE_PACK, codebuddy_repo)

            locks = [
                claude_info["lock"],
                json.loads(
                    (codex_repo / ".illuminate" / "codex-lock.json").read_text(
                        encoding="utf-8"
                    )
                ),
                json.loads(
                    (codebuddy_repo / ".illuminate" / "codebuddy-lock.json").read_text(
                        encoding="utf-8"
                    )
                ),
            ]
            for lock in locks:
                self.assertIn("capabilities", lock)
                self.assertIn("permissions", lock["capabilities"])
            self.assertEqual(
                locks[1]["capabilities"], {"permissions": "declarative-only"}
            )
            self.assertEqual(
                locks[2]["capabilities"], {"permissions": "declarative-only"}
            )
            self.assertIsInstance(
                locks[0]["capabilities"]["permissions"], dict,
                "Claude capabilities must carry the enforcement_status map",
            )


if __name__ == "__main__":
    unittest.main()
