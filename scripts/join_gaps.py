#!/usr/bin/env python3
"""Write reports/join_gaps.md (read-only on the DB).  python3 -m scripts.join_gaps [--db X] [--stdout]"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ingest.join_gaps import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
