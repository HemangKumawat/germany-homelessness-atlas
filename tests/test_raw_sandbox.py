"""Lead 2026-11-23: selftests and unit tests never write to data/raw (the archived/cached sources)."""
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from ingest import common  # noqa: E402


def _snapshot(root: Path) -> dict:
    return {str(p): (p.stat().st_mtime_ns, p.stat().st_size) for p in root.rglob("*") if p.is_file()} if root.exists() else {}


class RawSandbox(unittest.TestCase):
    def test_sandbox_active_under_unittest(self):
        self.assertIsNotNone(common.RAW_SANDBOX)
        self.assertNotEqual(common.RAW, common.REAL_RAW)
        self.assertTrue(str(common.raw_path("x", "https://example.org/a")).startswith(str(common.RAW_SANDBOX)))

    def test_funding_manual_selftests_leave_real_raw_untouched(self):
        from ingest.domains import funding_manual as fm
        real = common.REAL_RAW / fm.DOMAIN
        before = _snapshot(real)
        for t in fm.TESTS:
            t()
        self.assertEqual(before, _snapshot(real), "a funding_manual selftest wrote into data/raw")



if __name__ == "__main__":
    unittest.main()
