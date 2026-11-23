"""Offline tests for ingest/domains/funding_esf.py (ESF Plus Länder Liste der Vorhaben)."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ingest.domains import funding_esf as fe  # noqa: E402


def test_header_and_classify():
    fe._test_header_and_classify()


def test_zuwdb_match():
    fe._test_zuwdb_match()


def test_reader():
    fe._test_reader()


def test_robots_fail_closed():
    fe._test_robots_fail_closed()


def test_cli_safety():
    def rc(*a):
        return subprocess.run([sys.executable, "-m", "ingest.domains.funding_esf", *a], cwd=ROOT,
                              capture_output=True, text=True).returncode
    assert rc() == 2
    assert rc("--bogus") == 2
    assert rc("--selftest", "--db", str(ROOT / "data" / "atlas.db")) != 0


if __name__ == "__main__":
    for t in (test_header_and_classify, test_zuwdb_match, test_reader, test_robots_fail_closed, test_cli_safety):
        t()
        print("PASS", t.__name__)
