"""Offline tests for ingest/domains/funding_hamburg.py (in-memory SQLite, robots/HTTP fixtures, no network).
Run: python3 -m pytest -q tests/test_funding_hamburg.py   or   python3 tests/test_funding_hamburg.py
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from ingest.domains import funding_hamburg as fh  # noqa: E402


def test_classify():
    fh._test_classify()


def test_discovery_robots_first_and_no_api():
    fh._test_discovery_and_api()


def test_reader():
    fh._test_reader()


def test_existing_org_namesakes():
    fh._test_existing_org_namesakes()


def test_cli_safety():
    def rc(*a):
        return subprocess.run([sys.executable, "-m", "ingest.domains.funding_hamburg", *a], cwd=ROOT,
                              capture_output=True, text=True).returncode
    assert rc() == 2
    assert rc("--bogus") == 2
    assert rc("--test", "--frobnicate") == 2
    assert rc("--selftest", "--db", str(ROOT / "data" / "atlas.db")) != 0


if __name__ == "__main__":
    for t in (test_classify, test_discovery_robots_first_and_no_api, test_reader, test_existing_org_namesakes,
              test_cli_safety):
        t()
        print("PASS", t.__name__)
