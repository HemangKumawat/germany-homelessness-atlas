"""Offline tests for ingest/domains/funding_mv.py (LAGuS M-V Zuwendungsverzeichnis)."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ingest.domains import funding_mv as fm  # noqa: E402


def test_classify():
    fm._test_classify()


def test_parser_wrapped_cells():
    fm._test_parser()


def test_reader():
    fm._test_reader()


def test_robots_fail_closed():
    fm._test_robots_fail_closed()


def test_tdb_parsers():
    fm._test_tdb_parsers()


def test_tdb_reader():
    fm._test_tdb_reader()


def test_tdb_robots_fail_closed():
    fm._test_tdb_robots_fail_closed()


def test_tdb_shelter_traeger():
    fm._test_tdb_shelter_traeger()


def test_cli_safety():
    def rc(*a):
        return subprocess.run([sys.executable, "-m", "ingest.domains.funding_mv", *a], cwd=ROOT,
                              capture_output=True, text=True).returncode
    assert rc() == 2
    assert rc("--bogus") == 2
    assert rc("--test", "--frobnicate") == 2
    assert rc("--selftest", "--db", str(ROOT / "data" / "atlas.db")) != 0


if __name__ == "__main__":
    for t in (test_classify, test_parser_wrapped_cells, test_reader, test_robots_fail_closed,
              test_tdb_parsers, test_tdb_reader, test_tdb_robots_fail_closed, test_tdb_shelter_traeger, test_cli_safety):
        t()
        print("PASS", t.__name__)
