#!/usr/bin/env python3
"""Create or upgrade data/atlas.db from ingest/schema.sql (takes the writer lock)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ingest.run import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main(["--schema"]))
