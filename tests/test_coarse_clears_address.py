"""Lead 2026-11-23: an offer that is coarsened to city/district level must lose a street address
stored by an earlier run (upsert never overwrites with NULL)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # runs without PYTHONPATH=. (python3 tests/<file>.py)


from ingest.domains import institutions_media_shelters as sh  # noqa: E402
from ingest.domains.institutions_media_rechnungshof import RESERVED_LICENCE
from tests.test_institutions_media import _Offline, memory_db


class CoarseClearsStaleAddress(_Offline, unittest.TestCase):
    def _rec(self, address):
        return {
            "official_key": "TEST-HH:young",
            "name": "Werkhaus Test (für Jungerwachsene 18-27 Jahre)",
            "kind": "notunterkunft", "land": "HH", "city": "Hamburg",
            "address": address, "plz": "20097",
            "source_url": "https://example.invalid/hh", "official_url": "https://example.invalid/hh",
            "license": RESERVED_LICENCE, "redistribute_fulltext": 0,
        }

    def test_stale_address_cleared(self):
        conn = memory_db()
        self.assertTrue(sh.store_official_facility(conn, self._rec("Teststr. 1"), sources=[]))
        name = self._rec(None)["name"]
        # simulate a row stored before the coarsening rule existed
        conn.execute("UPDATE facility SET anschrift='Teststr. 1, 20097 Hamburg', plz='20097', lat=53.5, lon=10.0 WHERE name=?", (name,))
        self.assertTrue(sh.store_official_facility(conn, self._rec("Teststr. 1"), sources=[]))
        row = conn.execute("SELECT anschrift, plz, lat, lon FROM facility WHERE name=?", (name,)).fetchone()
        self.assertEqual(tuple(row), (None, None, None, None))


if __name__ == "__main__":
    unittest.main()
