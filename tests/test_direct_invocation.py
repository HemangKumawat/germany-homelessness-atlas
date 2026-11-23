"""Domain modules started directly must never open data/atlas.db (runner-only writes).

1. Every ingest/domains module: an unknown flag exits non-zero (argparse, exit 2), no args exits non-zero,
   and neither touches the writer lock or the DB.
2. The central guard: with a domain module as __main__, run.open_db() refuses the canonical DB (and any
   file named atlas.db) before creating or opening it, while a scratch path still works.
"""
import os
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from ingest import common, run  # noqa: E402

MODULES = sorted(p.stem for p in (ROOT / "ingest" / "domains").glob("*.py") if p.stem != "__init__")


# an offline mode per module with worker tools; with an unknown flag next to it nothing may run
VALID_MODE = {"funding_traeger": "--test", "counts_law": "--shape-test", "institutions_media": "--selftest",
              "funding_hamburg": "--test", "funding_mv": "--test", "funding_manual": "--test",
              "funding_esf": "--test"}


def _stamp(p: Path):
    return (p.stat().st_mtime_ns, p.stat().st_size) if p.exists() else None


class DirectInvocationTests(unittest.TestCase):
    def _run(self, mod, *args):
        return subprocess.run([sys.executable, "-m", f"ingest.domains.{mod}", *args], cwd=ROOT,
                              capture_output=True, text=True, timeout=120)

    def test_every_module_rejects_unknown_flags_and_bare_runs(self):
        db, lock = common.DB, common.LOCK
        before = (_stamp(db), _stamp(Path(str(db) + "-wal")), _stamp(lock))
        self.assertGreater(len(MODULES), 5)
        for mod in MODULES:
            with self.subTest(mod=mod, case="unknown flag"):
                r = self._run(mod, "--definitely-not-a-flag")
                self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
                self.assertIn("error:", r.stderr)
                self.assertNotIn("migrate:", r.stderr)
            if mod in VALID_MODE:
                with self.subTest(mod=mod, case="valid mode + unknown flag"):
                    r = self._run(mod, VALID_MODE[mod], "--definitely-not-a-flag")
                    self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
                    self.assertIn("unrecognized arguments", r.stderr)
            with self.subTest(mod=mod, case="abbreviated flag"):
                r = self._run(mod, "--sel")        # allow_abbrev=False: no prefix matching
                self.assertNotEqual(r.returncode, 0)
            with self.subTest(mod=mod, case="no arguments"):
                r = self._run(mod)
                self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)
                self.assertNotIn("migrate:", r.stderr)
        after = (_stamp(db), _stamp(Path(str(db) + "-wal")), _stamp(lock))
        self.assertEqual(before, after, "a direct module run touched data/atlas.db or the writer lock")

    def test_runner_guard_refuses_canonical_db(self):
        fake = types.ModuleType("__main__")
        fake.__spec__ = types.SimpleNamespace(name="ingest.domains.example")
        real_main, real_db = sys.modules["__main__"], common.DB
        with tempfile.TemporaryDirectory() as td:
            canon = Path(td) / "data" / "atlas.db"
            try:
                sys.modules["__main__"] = fake
                common.DB = canon
                self.assertEqual(common.direct_domain_invocation(), "ingest.domains.example")
                with self.assertRaises(SystemExit) as cm:
                    run.open_db()
                self.assertIn("REFUSED", str(cm.exception))
                with self.assertRaises(SystemExit):
                    run.open_db(Path(td) / "elsewhere" / "atlas.db")   # any atlas.db, e.g. another worktree
                self.assertFalse(canon.exists())
                scratch = run.open_db(Path(td) / "scratch.db")          # worker scratch DBs stay allowed
                self.assertEqual(scratch.execute("PRAGMA user_version").fetchone()[0] >= 2, True)
                scratch.close()
            finally:
                sys.modules["__main__"] = real_main
                common.DB = real_db
        self.assertIsNone(common.direct_domain_invocation())

    def test_former_plain_run_entry_refuses(self):
        self.assertEqual(common.main("funding_traeger"), 2)


if __name__ == "__main__":
    unittest.main()
