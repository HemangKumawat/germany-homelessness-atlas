"""Offline tests for ingest/domains/funding_manual.py (manual-archive readers: Bremen ZEBRA, RLP MASTD)."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ingest.domains import funding_manual as fman  # noqa: E402


def test_xland_and_same_dataset_links():
    fman._test_xland_and_same_dataset_links()


def test_archive_mode_checksums():
    fman._test_archive_mode()


def test_classify():
    fman._test_classify()


def test_bremen_reader_no_network():
    fman._test_hb_reader()


def test_rlp_reader():
    fman._test_rlp_reader()


def test_cli_safety():
    def rc(*a):
        return subprocess.run([sys.executable, "-m", "ingest.domains.funding_manual", *a], cwd=ROOT,
                              capture_output=True, text=True).returncode
    assert rc() == 2
    assert rc("--bogus") == 2
    assert rc("--selftest", "--db", str(ROOT / "data" / "atlas.db")) != 0


if __name__ == "__main__":
    for t in (test_xland_and_same_dataset_links, test_archive_mode_checksums, test_classify, test_bremen_reader_no_network, test_rlp_reader, test_cli_safety):
        t()
        print("PASS", t.__name__)
