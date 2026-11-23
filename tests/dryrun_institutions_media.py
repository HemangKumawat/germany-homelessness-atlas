"""Live dry run into an in-memory database. Does not open data/atlas.db."""
import sys

from ingest.domains.institutions_media import dry_run

if __name__ == "__main__":
    sys.exit(dry_run())
