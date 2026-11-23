"""Schema 6: the legal form is part of the org key (INGEST_CONTRACT §12). Run: python3 tests/test_org_legal_form.py"""
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
from ingest import common, migrate, orglink, run  # noqa: E402
from test_g11_join_integrity import scratch  # noqa: E402


def v5_schema() -> str:
    """ingest/schema.sql as it was at schema 5: inline UNIQUE(name_norm, land), no legal_form_norm."""
    s = common.SCHEMA.read_text(encoding="utf-8")
    lines = s.split("\n")
    out, skip = [], 0
    for ln in lines:
        if ln.startswith("  legal_form_norm "):
            skip = 1
            continue
        if skip:
            skip = 0
            continue
        if "org_eindeutig" in ln or ln.startswith("-- Schema 6: ein Träger"):
            continue
        if ln.startswith("  CHECK (is_protected = 0 OR (strasse IS NULL"):
            out.append("  UNIQUE (name_norm, land),")
        out.append(ln)
    s5 = "\n".join(out)
    assert "legal_form_norm" not in s5 and "UNIQUE (name_norm, land)" in s5
    return s5


class LegalFormKey(unittest.TestCase):
    def test_legal_form_norm(self):
        f = orglink.legal_form_norm
        cases = {"Malteser Hilfsdienst e.V.": "ev", "Malteser Hilfsdienst gGmbH": "ggmbh", "five walls GmbH": "gmbh",
                 "Stiftung SPI": "stiftung", "Ev. Kirchengemeinde Zum Guten Hirten": "kdoer", "Handwerkskammer KöR": "koer",
                 "Praxis Müller GbR": "gbr", "Bau eG": "eg", "Beispiel AG": "ag", "Zeta UG (haftungsbeschränkt)": "other",
                 "Bezirksamt Mitte": None, "Die Arbeiterwohlfahrt": None}
        for name, want in cases.items():
            self.assertEqual(f(name), want, name)
        self.assertEqual(f("Fixpunkt", "e.V."), "ev")                          # printed legal_form counts too
        self.assertTrue(set(v for v in cases.values() if v) <= set(orglink.LEGAL_FORM_NORMS))

    def test_ev_and_ggmbh_of_one_name_coexist(self):
        with tempfile.TemporaryDirectory() as td:
            c = scratch(td)
            self.assertEqual(c.execute("PRAGMA user_version").fetchone()[0], 6)
            g = common.ensure_org(c, "Malteser Hilfsdienst gGmbH", "BW", 1, register="HRB 26997 (AG Köln)")
            e = common.ensure_org(c, "Malteser Hilfsdienst e.V.", "BW", 1)
            self.assertNotEqual(g, e)
            rows = {tuple(r) for r in c.execute("SELECT name_norm, legal_form_norm, land FROM org")}
            self.assertEqual(rows, {("MALTESER HILFSDIENST", "ggmbh", "BW"), ("MALTESER HILFSDIENST", "ev", "BW")})
            self.assertEqual(common.ensure_org(c, "Malteser Hilfsdienst e.V.", "BW", 1), e)          # stable
            self.assertEqual(common.ensure_org(c, "Malteser Hilfsdienst gGmbH", "BW", 1), g)
            # the legacy upsert key (name_norm, land) now keys on the legal form as well
            u = common.upsert(c, "org", {"name": "Malteser Hilfsdienst e.V.", "name_norm": "MALTESER HILFSDIENST",
                                         "land": "BW", "webseite": "https://www.malteser.de", "source_id": 1},
                              ["name_norm", "land"])
            self.assertEqual(u, e)
            self.assertEqual(c.execute("SELECT webseite FROM org WHERE id=?", (g,)).fetchone()[0], None)
            with self.assertRaises(sqlite3.IntegrityError):
                c.execute("INSERT INTO org(name, name_norm, legal_form_norm, land, source_id) VALUES "
                          "('Malteser Hilfsdienst e. V.', 'MALTESER HILFSDIENST', 'ev', 'BW', 1)")
            # same family: 'GmbH' printed for the gGmbH reuses it; a known form reuses a lone unknown-form row
            self.assertEqual(common.ensure_org(c, "Malteser Hilfsdienst GmbH", "BW", 1), g)
            x = common.ensure_org(c, "Gamma Hilfe", "HH", 1)
            self.assertEqual(common.ensure_org(c, "Gamma Hilfe e.V.", "HH", 1), x)
            orglink.sync(c)
            self.assertEqual(orglink.gate(c)[0], [])

    def test_unknown_legal_form_matches_only_a_single_candidate(self):
        with tempfile.TemporaryDirectory() as td:
            c = scratch(td)
            only = common.ensure_org(c, "Fixpunkt gGmbH", "BE", 1)
            self.assertEqual(common.find_org(c, "Fixpunkt", "BE")["how"], "single")
            self.assertEqual(common.ensure_org(c, "Fixpunkt", "BE", 1, record_kind="org_name", record_key="FIXPUNKT|BE"), only)
            self.assertEqual(tuple(c.execute("SELECT method, flagged FROM org_link WHERE record_key='FIXPUNKT|BE'").fetchone()),
                             ("name_fuzzy", 1))
            g = common.ensure_org(c, "Malteser Hilfsdienst gGmbH", "BW", 1)
            e = common.ensure_org(c, "Malteser Hilfsdienst e.V.", "BW", 1)
            r = common.find_org(c, "Malteser Hilfsdienst", "BW")
            self.assertEqual((r["org_id"], r["how"], r["candidates"]), (None, "ambiguous", sorted([g, e])))
            n = common.ensure_org(c, "Malteser Hilfsdienst", "BW", 1)
            self.assertNotIn(n, (g, e))
            self.assertIsNone(c.execute("SELECT legal_form_norm FROM org WHERE id=?", (n,)).fetchone()[0])
            m, f, note = c.execute("SELECT method, flagged, note FROM org_link WHERE record_kind='org_name' AND org_id=?",
                                   (n,)).fetchone()
            self.assertEqual((m, f), ("name_fuzzy", 1))
            self.assertIn("legal form unknown", note)
            self.assertEqual(common.ensure_org(c, "Malteser Hilfsdienst", "BW", 1), n)            # its own exact key
            self.assertEqual(c.execute("SELECT count(*) FROM org WHERE name_norm='MALTESER HILFSDIENST'").fetchone()[0], 3)

    def test_rerun_of_the_creating_source_is_origin_not_fuzzy(self):
        """Lead 2026-11-23: an exact (name_norm, legal form, Land) hit on a row the SAME source created is that
        record again (a re-run), linked as origin; the same name from another source stays a flagged name_fuzzy."""
        with tempfile.TemporaryDirectory() as td:
            c = scratch(td)
            c.execute("INSERT OR IGNORE INTO source(id, url, title, license) VALUES (2, 'https://example.invalid/2', 't2', 'x')")
            o = common.ensure_org(c, "Arbeitskreis Wohnungsnot", "BE", 1)
            self.assertEqual(common.ensure_org(c, "Arbeitskreis Wohnungsnot", "BE", 1, record_kind="institutions_media_org",
                                               record_key="AK|BE|1"), o)
            self.assertEqual(tuple(c.execute("SELECT method, flagged FROM org_link WHERE record_key='AK|BE|1'").fetchone()),
                             ("origin", 0))
            self.assertEqual(common.ensure_org(c, "Arbeitskreis Wohnungsnot", "BE", 2, record_kind="institutions_media_org",
                                               record_key="AK|BE|2"), o)
            self.assertEqual(tuple(c.execute("SELECT method, flagged FROM org_link WHERE record_key='AK|BE|2'").fetchone()),
                             ("name_fuzzy", 1))
            self.assertEqual(orglink.gate(c)[0], [])

    def test_upgrade_6_rebuilds_org_keeping_rows_and_ids(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "v5.db"
            c = sqlite3.connect(p, isolation_level=None)
            c.execute("PRAGMA foreign_keys=ON")
            c.executescript(v5_schema())
            orglink.ensure_schema(c)
            c.execute("PRAGMA user_version=5")
            c.execute("INSERT INTO source(id, domain, url, title, license) VALUES (1,'t','https://example.invalid/a','a','x')")
            c.execute("INSERT INTO org(id, name, name_norm, land, legal_form, source_id) VALUES "
                      "(162, 'Malteser Hilfsdienst gGmbH', 'MALTESER HILFSDIENST', 'BW', NULL, 1), "
                      "(682, 'Malteser Hilfsdienst e.V.', 'MALTESER HILFSDIENST EV', 'BW', NULL, 1), "
                      "(7, 'Bezirksamt Mitte', 'BEZIRKSAMT MITTE', 'BE', NULL, 1)")
            c.execute("INSERT INTO award(foerder_schluessel, empfaenger, empfaenger_norm, org_id, source_id) VALUES "
                      "('TED:1:ITEM-1:MALTESER', 'Malteser Hilfsdienst e.V.', 'MALTESER HILFSDIENST', 682, 1)")
            n_trig = c.execute("SELECT count(*) FROM sqlite_master WHERE type='trigger'").fetchone()[0]
            c.close()
            conn = run.open_db(p)                                    # the runner upgrades before schema.sql runs
            self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], migrate.SCHEMA_VERSION)
            got = {r[0]: tuple(r)[1:] for r in conn.execute("SELECT id, name_norm, legal_form_norm FROM org")}
            self.assertEqual(got, {162: ("MALTESER HILFSDIENST", "ggmbh"), 682: ("MALTESER HILFSDIENST", "ev"),
                                   7: ("BEZIRKSAMT MITTE", None)})
            self.assertEqual(conn.execute("SELECT org_id FROM award").fetchone()[0], 682)
            self.assertEqual(conn.execute("SELECT count(*) FROM sqlite_master WHERE type='trigger'").fetchone()[0], n_trig)
            self.assertIn("coalesce(legal_form_norm", conn.execute(
                "SELECT sql FROM sqlite_master WHERE name='org_eindeutig'").fetchone()[0])
            self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])
            self.assertFalse(migrate.needs_v6(conn))
            conn.close()
            conn = run.open_db(p)                                    # idempotent
            self.assertEqual(conn.execute("SELECT count(*) FROM org").fetchone()[0], 3)


if __name__ == "__main__":
    unittest.main(verbosity=1)
