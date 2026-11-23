"""Kreis split (Hanau 06415 kreisfrei from 2026): populations in the new boundaries, G5 sum rule, join gaps.
Run: python3 tests/test_kreis_split.py"""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from ingest import join_gaps, run  # noqa: E402
from ingest.domains import geo_bevoelkerung as gb  # noqa: E402
import verify  # noqa: E402


def scratch(td, hanau=98582, rest=(200000, 122593), old_total=421175):
    conn = run.open_db(Path(td) / "split.db")
    conn.execute("INSERT INTO source(id, domain, url, title, license) VALUES (1,'geo_bevoelkerung',?,'gv','x')", (gb.GV_URL,))
    conn.execute("INSERT INTO source(id, domain, url, title, license) VALUES (2,'geo_bevoelkerung','https://x.invalid/12411','12411','x')")
    conn.execute("INSERT INTO geo_land(ags, abbr, name, source_id) VALUES ('06','HE','Hessen',1)")
    for ags, name in (("06415", "Hanau"), ("06435", "Main-Kinzig-Kreis")):
        conn.execute("INSERT INTO geo_kreis(ags, land_ags, land, name, source_id) VALUES (?,?,?,?,1)", (ags, "06", "HE", name))
    conn.execute("INSERT INTO geo_gemeinde(ags, land_ags, kreis_ags, name, einwohner, source_id) "
                 "VALUES ('06415000','06','06415','Hanau',?,1)", (hanau,))
    for i, e in enumerate(rest, 1):
        conn.execute("INSERT INTO geo_gemeinde(ags, land_ags, kreis_ags, name, einwohner, source_id) "
                     "VALUES (?,?,?,?,?,1)", (f"06435{i:03d}", "06", "06435", f"G{i}", e))
    conn.execute("INSERT INTO metric(entity_type, entity_id, metric, year, value, einheit, source_id) "
                 "VALUES ('kreis','06435','einwohner',2025,?,'persons',2)", (old_total,))
    conn.execute("INSERT INTO metric(entity_type, entity_id, metric, year, value, einheit, source_id) "
                 "VALUES ('kreis','06415','housed_homeless',2026,920,'persons',2)")
    conn.execute("INSERT INTO metric(entity_type, entity_id, metric, year, value, einheit, source_id) "
                 "VALUES ('kreis','06435','housed_homeless',2026,1700,'persons',2)")
    return conn


def val(conn, ags, metric):
    r = conn.execute("SELECT value, is_est, source_id FROM metric WHERE entity_type='kreis' AND entity_id=? AND metric=? "
                     "AND year=2025", (ags, metric)).fetchone()
    return tuple(r) if r else None


class KreisSplit(unittest.TestCase):
    def test_writes_new_kreis_and_old_kreis_in_new_boundaries(self):
        with tempfile.TemporaryDirectory() as td:
            conn = scratch(td)
            notes = []
            self.assertEqual(gb.ingest_kreis_splits(conn, notes), 2)
            self.assertEqual(val(conn, "06415", "einwohner"), (98582.0, 0, 1))
            self.assertEqual(val(conn, "06435", "einwohner_gebietsstand"), (322593.0, 0, 1))
            self.assertEqual(val(conn, "06435", "einwohner")[0], 421175.0)          # 12411 row untouched
            note = conn.execute("SELECT anmerkung FROM metric WHERE metric='einwohner_gebietsstand'").fetchone()[0]
            self.assertIn("Summe der amtlichen Gemeindezahlen", note)
            self.assertIn("Keine Schätzung", note)
            gb.ingest_kreis_splits(conn, [])                                         # idempotent
            self.assertEqual(conn.execute("SELECT count(*) FROM metric WHERE metric LIKE 'einwohner%'").fetchone()[0], 3)

    def test_inconsistent_gebietsstand_writes_nothing(self):
        with tempfile.TemporaryDirectory() as td:
            conn = scratch(td, old_total=421176)
            with self.assertRaises(gb.ShapeError):
                gb.ingest_kreis_splits(conn, [])
            self.assertIsNone(val(conn, "06435", "einwohner_gebietsstand"))

    def test_verify_sum_rule_and_join_gaps(self):
        with tempfile.TemporaryDirectory() as td:
            conn = scratch(td)
            before = join_gaps.compute(conn)
            gb.ingest_kreis_splits(conn, [])
            q = lambda sql, *a: conn.execute(sql, a).fetchall()  # noqa: E731
            self.assertEqual(verify.gemeinde_sum(q, "06435", 1), (2, 322593, 0))
            self.assertEqual(verify.gemeinde_sum(q, "06435", 2)[0], 0)              # other source: no addends
            self.assertIn("einwohner_gebietsstand", verify.SUM_OF_GEMEINDEN)
            if before is not None:
                after = join_gaps.compute(conn)
                self.assertEqual(after["geo"]["kreis"]["no_population"], [])


if __name__ == "__main__":
    unittest.main()
