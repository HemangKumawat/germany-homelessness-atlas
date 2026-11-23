"""Offline checks for Wohlfahrtsverband Gremien officer ingest."""
import sqlite3
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ingest.common import ROOT as INGEST_ROOT, name_norm
from ingest.domains import institutions_media as mod
from ingest.domains import institutions_media_officers as officers


def memory_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript((INGEST_ROOT / "ingest" / "schema.sql").read_text(encoding="utf-8"))
    mod.ensure_tables(conn)
    return conn


def _source(conn, url="https://example.org/src"):
    conn.execute(
        "INSERT INTO source(domain, url, license, redistribute_fulltext) "
        "VALUES ('test', ?, 'Rechte vorbehalten', 0)",
        (url,),
    )
    return conn.execute("SELECT id FROM source WHERE url=?", (url,)).fetchone()[0]


def _org(conn, name, land, legal, source_id):
    from ingest import orglink
    conn.execute(
        "INSERT INTO org(name, name_norm, legal_form, legal_form_norm, land, currency, source_id) "
        "VALUES (?,?,?,?,?,?,?)",
        (name, name_norm(name), legal, orglink.legal_form_norm(name, legal), land, "EUR", source_id),
    )
    return conn.execute("SELECT id FROM org ORDER BY id DESC LIMIT 1").fetchone()[0]


BAGW_VORSTAND_HTML = """<!doctype html><html><body>
<h1>Der Vorstand der BAG W</h1>
<p>Folgende Personen gehören dem aktuellen Vorstand der BAG W an:</p>
<ul>
<li>Stephanie Kasten, Caritasverband für das Erzbistum Berlin e.V.</li>
<li>Susanne Hahmann (Diakonie Michaelshoven e.V., Die sozialen Hilfen gGmbH, Köln)</li>
</ul>
</body></html>
"""

BAGW_PRAESIDIUM_HTML = """<!doctype html><html><body>
<p>Die Mitglieder des Präsidiums:</p>
<p>Sabine Bösing, Berlin</p>
<p>Susanne Hahmann, Gummersbach, Vorsitzende</p>
</body></html>
"""

BAGFW_HTML = """<!doctype html><html><body>
<p>Das Präsidium besteht aus dem/der Präsidenten/in und den beiden Vizepräsident:innen.
Sie bilden den Vorstand im Sinne von § 26 BGB.
Präsident der BAGFW ist bis zum 31.12.2026 Achim Meyer auf der Heyde, Vorsitzender des Paritätischen Gesamtverbandes.
Vizepräsident:innen sind: Michael Groß, Präsident des Arbeiterwohlfahrt Bundesverbandes und Eva Maria Welskop-Deffaa, Deutscher Caritasverband.</p>
</body></html>
"""

AWO_VORSTAND_HTML = """<!doctype html><html><body>
<h1>Vorstand</h1>
<p>Vorstandsmitglieder</p>
<p>Claudia Mandrysch</p>
<p>Vorständin</p>
<p>vorstand@awo.org</p>
<p>Tel. +49 (0)30 26 309 192</p>
<p>Dr. Marvin Deversi</p>
<p>Vorstand</p>
<p>vorstand@awo.org</p>
<p>Tel. +49 (0)30 26 309 190</p>
<p>Weitere Ansprechpersonen</p>
<p>Erika Mustermann</p>
<p>Vorstandsassistentin</p>
<p>erika.mustermann@example.org</p>
</body></html>
"""


def _page(src, people):
    rec = dict(src)
    rec["people"] = people
    return rec


class OfficersGremienTests(unittest.TestCase):
    def test_seed_catalog_has_no_impressum_url(self):
        for url in officers.seed_urls():
            self.assertNotIn("impressum", url.lower(), url)
        officers.assert_no_impressum_seeds()

    def test_module_refuses_direct_run(self):
        import subprocess
        r = subprocess.run(
            [sys.executable, "-m", "ingest.domains.institutions_media_officers"],
            cwd=ROOT, capture_output=True, text=True,
        )
        self.assertEqual(r.returncode, 2)
        self.assertIn("REFUSED", r.stderr)

    def test_existing_org_person_row_is_never_updated(self):
        """(a) Insert only: an existing F&T row keeps its org_id, quote and funktion."""
        conn = memory_db()
        sid = _source(conn)
        org_a = _org(conn, "Bundesarbeitsgemeinschaft Wohnungslosenhilfe e.V.", "BE", "e.V.", sid)
        org_b_name = "Bundesarbeitsgemeinschaft Wohnungslosenhilfe e.V."
        conn.execute(
            "INSERT INTO org_person(org_id, org_bezeichnung, funktionstraeger, funktionstraeger_norm, "
            "funktion, jahr, quote, stand, source_id) VALUES (?,?,?,?,?,?,?,?,?)",
            (org_a, org_b_name, "Stephanie Kasten", officers.person_key("Stephanie Kasten"),
             "Vorstand", 2026, "ORIGINAL QUOTE Stephanie Kasten Vorstand", "2026-01-01", sid),
        )
        before = dict(conn.execute("SELECT * FROM org_person").fetchone())
        page = _page(officers.PAGES[0], officers.PAGES[0]["people"])
        cfg = {
            "officers_pages": [page],
            "officers_fixture": {page["url"]: BAGW_VORSTAND_HTML.encode()},
            "officers_stand": "2026-11-23",
        }
        n = officers.ingest_officers(conn, cfg, [], [])
        self.assertEqual(n, 0)
        after = dict(conn.execute("SELECT * FROM org_person").fetchone())
        self.assertEqual(after["id"], before["id"])
        self.assertEqual(after["org_id"], org_a)
        self.assertEqual(after["quote"], before["quote"])
        self.assertEqual(after["funktion"], before["funktion"])
        self.assertEqual(conn.execute("SELECT count(*) FROM org_person").fetchone()[0], 1)

    def test_resolves_existing_org_by_alias_not_duplicate(self):
        """(b) AWO stored as 'AWO Bundesverband e.V.' is reused; no second org is created."""
        conn = memory_db()
        sid = _source(conn)
        existing = _org(conn, "AWO Bundesverband e.V.", None, "e.V.", sid)
        page = _page(officers.PAGES[6], officers.PAGES[6]["people"][:1])
        cfg = {
            "officers_pages": [page],
            "officers_fixture": {page["url"]: AWO_VORSTAND_HTML.encode()},
        }
        n = officers.ingest_officers(conn, cfg, [], [])
        self.assertEqual(n, 1)
        orgs = list(conn.execute("SELECT id, name, land FROM org"))
        self.assertEqual(len(orgs), 1, [tuple(o) for o in orgs])
        self.assertEqual(orgs[0]["id"], existing)
        self.assertEqual(conn.execute("SELECT org_id FROM org_person").fetchone()[0], existing)

    def test_normalised_name_and_funktion_dedupe(self):
        """(c) Dr./Prof. titles, case, whitespace and gendered roles count as the same role."""
        self.assertEqual(officers.person_key("Dr. Marvin Deversi"), officers.person_key("Marvin Deversi"))
        self.assertEqual(officers.funktion_key("Präsidentin"), officers.funktion_key("Präsident"))
        self.assertEqual(officers.funktion_key("Vorständin"), officers.funktion_key("Vorstand"))
        self.assertEqual(
            officers.funktion_key("Vorsitzende des Präsidiums"),
            officers.funktion_key("Vorsitzender des Präsidiums"),
        )
        conn = memory_db()
        sid = _source(conn)
        org_id = _org(conn, "Arbeiterwohlfahrt Bundesverband e. V.", "DE", "e.V.", sid)
        conn.execute(
            "INSERT INTO org_person(org_id, org_bezeichnung, funktionstraeger, funktionstraeger_norm, "
            "funktion, jahr, quote, source_id) VALUES (?,?,?,?,?,?,?,?)",
            (org_id, "Arbeiterwohlfahrt Bundesverband e. V.", "Dr. Marvin Deversi",
             "MARVIN DEVERSI", "Vorstand", 2026, "Dr. Marvin Deversi Vorstand", sid),
        )
        page = _page(officers.PAGES[6], [
            {"name": "Marvin Deversi", "funktion": "Vorständin",
             "quote": "Dr. Marvin Deversi Vorstand"},
        ])
        cfg = {
            "officers_pages": [page],
            "officers_fixture": {page["url"]: AWO_VORSTAND_HTML.encode()},
        }
        n = officers.ingest_officers(conn, cfg, [], [])
        self.assertEqual(n, 0)
        self.assertEqual(conn.execute("SELECT count(*) FROM org_person").fetchone()[0], 1)

    def test_quote_must_contain_name_and_role(self):
        """(d) Rows whose quote lacks the name or the role are dropped."""
        self.assertFalse(officers.quote_has_name_and_role(
            "Michael Groß", "Vorsitzender des Präsidiums",
            "seit Juni 2021 Vorsitzender des Präsidiums des AWO Bundesverbandes e.V.",
        ))
        self.assertFalse(officers.quote_has_name_and_role(
            "Sabine Bösing", "Mitglied des Präsidiums",
            "Sabine Bösing, Berlin",
        ))
        self.assertTrue(officers.quote_has_name_and_role(
            "Sabine Bösing", "Mitglied des Präsidiums",
            "Die Mitglieder des Präsidiums: Sabine Bösing",
        ))
        conn = memory_db()
        page = _page(officers.PAGES[5], [
            {"name": "Michael Groß", "funktion": "Vorsitzender des Präsidiums",
             "quote": "seit Juni 2021 Vorsitzender des Präsidiums des AWO Bundesverbandes e.V."},
        ])
        html = (
            "<html><body><p>seit Juni 2021 Vorsitzender des Präsidiums des AWO "
            "Bundesverbandes e.V.</p><p>Michael Groß</p></body></html>"
        )
        cfg = {"officers_pages": [page], "officers_fixture": {page["url"]: html.encode()}}
        n = officers.ingest_officers(conn, cfg, [], [])
        self.assertEqual(n, 0)
        self.assertEqual(conn.execute("SELECT count(*) FROM org_person").fetchone()[0], 0)

    def test_praesidium_quotes_exclude_home_cities(self):
        """(e) Präsidium quotes store name plus role only; city tails are not stored."""
        conn = memory_db()
        page = _page(officers.PAGES[1], [
            {"name": "Sabine Bösing", "funktion": "Mitglied des Präsidiums",
             "quote": "Sabine Bösing, Berlin"},
            {"name": "Sabine Bösing", "funktion": "Mitglied des Präsidiums",
             "quote": "Die Mitglieder des Präsidiums: Sabine Bösing"},
        ])
        cfg = {
            "officers_pages": [page],
            "officers_fixture": {page["url"]: BAGW_PRAESIDIUM_HTML.encode()},
        }
        n = officers.ingest_officers(conn, cfg, [], [])
        self.assertEqual(n, 1)
        row = conn.execute("SELECT quote, funktionstraeger, funktion FROM org_person").fetchone()
        self.assertEqual(row["funktionstraeger"], "Sabine Bösing")
        self.assertNotIn("Berlin", row["quote"])
        self.assertIn("Sabine Bösing", row["quote"])
        self.assertIn("Präsidium", row["quote"])

    def test_awo_vorstand_stores_roles_without_contact_or_staff(self):
        conn = memory_db()
        sources, notes = [], []
        page = _page(officers.PAGES[6], officers.PAGES[6]["people"] + [
            {"name": "Erika Mustermann", "funktion": "Vorstandsassistentin",
             "quote": "Erika Mustermann Vorstandsassistentin"},
            {"name": "Claudia Mandrysch", "funktion": "Vorständin",
             "quote": "Claudia Mandrysch Vorständin vorstand@awo.org"},
        ])
        cfg = {
            "officers_pages": [page],
            "officers_fixture": {page["url"]: AWO_VORSTAND_HTML.encode()},
        }
        n = officers.ingest_officers(conn, cfg, sources, notes)
        self.assertEqual(n, 2)
        people = [r["funktionstraeger"] for r in conn.execute("SELECT funktionstraeger FROM org_person")]
        self.assertEqual(sorted(people), ["Claudia Mandrysch", "Marvin Deversi"])
        roles = {r["funktionstraeger"]: r["rollenklasse"]
                 for r in conn.execute("SELECT funktionstraeger, rollenklasse FROM org_person")}
        self.assertEqual(roles["Claudia Mandrysch"], "vorstand")
        self.assertEqual(roles["Marvin Deversi"], "vorstand")
        for r in conn.execute("SELECT * FROM org_person"):
            blob = f"{r['funktionstraeger']} {r['funktion']} {r['quote']}"
            self.assertIsNone(officers.CONTACT_RE.search(blob), blob)
            self.assertNotIn("@", r["quote"])
            self.assertNotIn("Tel.", r["quote"])

    def test_officers_do_not_attach_to_ggmbh_of_same_name(self):
        conn = memory_db()
        from ingest import orglink
        name = "Arbeiterwohlfahrt Bundesverband e. V."
        sid = _source(conn, "https://example.org/ggmbh")
        _org(conn, name, "DE", "gGmbH", sid)
        gmbh_id = conn.execute("SELECT id FROM org").fetchone()[0]
        page = _page(officers.PAGES[6], officers.PAGES[6]["people"][:1])
        cfg = {
            "officers_pages": [page],
            "officers_fixture": {page["url"]: AWO_VORSTAND_HTML.encode()},
        }
        n = officers.ingest_officers(conn, cfg, [], [])
        self.assertEqual(n, 1)
        row = conn.execute("SELECT org_id FROM org_person").fetchone()
        self.assertNotEqual(row["org_id"], gmbh_id)
        ev = conn.execute("SELECT legal_form_norm FROM org WHERE id=?", (row["org_id"],)).fetchone()
        self.assertEqual(ev["legal_form_norm"], orglink.legal_form_norm(name, "e.V."))

    def test_bad_quote_is_skipped(self):
        conn = memory_db()
        page = _page(officers.PAGES[0], [
            {"name": "Stephanie Kasten", "funktion": "Vorstand",
             "quote": "Dieser Satz steht nicht auf der Seite."},
        ])
        cfg = {
            "officers_pages": [page],
            "officers_fixture": {page["url"]: BAGW_VORSTAND_HTML.encode()},
        }
        n = officers.ingest_officers(conn, cfg, [], [])
        self.assertEqual(n, 0)
        self.assertEqual(conn.execute("SELECT count(*) FROM org_person").fetchone()[0], 0)

    def test_officers_only_flag_and_skip_lists(self):
        self.assertIn("officers", mod._DRY_ONLY)
        self.assertNotIn("officers", mod._DRY_ONLY["officers"])
        self.assertIn("officers", mod._DRY_ONLY["press"])
        self.assertIn("press", mod._DRY_ONLY["officers"])
        self.assertEqual(mod.main(["--officers-only"]), 2)
        self.assertEqual(mod.main(["--dry-run", "--officers-only", "--nope"]), 2)


if __name__ == "__main__":
    unittest.main()
