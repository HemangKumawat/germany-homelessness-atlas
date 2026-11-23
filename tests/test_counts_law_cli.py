"""Offline CLI tests for ingest/domains/counts_law.py (no network, no DB writes).
Run: python3 -m pytest -q tests/test_counts_law_cli.py   or   python3 tests/test_counts_law_cli.py
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _run(*args):
    return subprocess.run([sys.executable, "-m", "ingest.domains.counts_law", *args], cwd=ROOT,
                          capture_output=True, text=True, timeout=120)


def _atlas_untouched(fn):
    db = ROOT / "data" / "atlas.db"
    before = db.stat().st_mtime_ns if db.exists() else None
    fn()
    after = db.stat().st_mtime_ns if db.exists() else None
    assert before == after, "data/atlas.db was touched"


def test_unknown_flag_exits_nonzero():
    def f():
        r = _run("--db", "/tmp/counts_law_cli_test.db", "--no-such-flag")
        assert r.returncode != 0 and "unrecognized arguments" in r.stderr, (r.returncode, r.stderr[-300:])
        assert not Path("/tmp/counts_law_cli_test.db").exists()
    _atlas_untouched(f)


def test_abbreviated_flag_rejected():
    r = _run("--db", "/tmp/counts_law_cli_test.db", "--self")
    assert r.returncode != 0


def test_missing_db_refused():
    def f():
        r = _run("--selftest")
        assert r.returncode != 0 and ("refusing to run without --db" in r.stderr or "--db <scratch path> is required" in r.stderr), r.stderr[-300:]
    _atlas_untouched(f)


def test_atlas_db_refused():
    def f():
        for target in (ROOT / "data" / "atlas.db", Path("/tmp/x/atlas.db"), Path("data/./atlas.db")):
            r = _run("--db", str(target))
            assert r.returncode != 0 and "refusing to write" in r.stderr, (target, r.stderr[-300:])
    _atlas_untouched(f)


def test_symlink_to_atlas_db_refused():
    real = ROOT / "data" / "atlas.db"
    if not real.exists():
        return
    link = Path("/tmp/counts_law_cli_link.db")
    link.unlink(missing_ok=True)
    link.symlink_to(real)
    try:
        def f():
            r = _run("--db", str(link))
            assert r.returncode != 0 and "refusing to write" in r.stderr
        _atlas_untouched(f)
    finally:
        link.unlink(missing_ok=True)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn(); print("PASS", name)
