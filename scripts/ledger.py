#!/usr/bin/env python3
"""Append a ledger row (LEDGER.md + ledger.jsonl), e.g. for merges and review verdicts.

    python3 scripts/ledger.py <domain> <verdict> <rows> <evidence> [note ...]
    verdict: KEEP | REJECT | PARKED | DONE | BLOCKED | MERGED | INGESTED | PASS | FAIL
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ingest.run import ledger  # noqa: E402

VERDICTS = {"KEEP", "REJECT", "PARKED", "DONE", "BLOCKED", "MERGED", "INGESTED", "PASS", "FAIL"}

if __name__ == "__main__":
    if len(sys.argv) < 5 or sys.argv[2].upper() not in VERDICTS:
        sys.exit(__doc__)
    ledger(sys.argv[1], sys.argv[2].upper(), sys.argv[3], sys.argv[4], " ".join(sys.argv[5:]))
    print("ledger: appended")
