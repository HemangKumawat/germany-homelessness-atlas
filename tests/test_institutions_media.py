"""Offline checks for the institutions_media ingestor. No network, no atlas.db."""
import hashlib
import json
import re
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ingest.common import ROOT as INGEST_ROOT
from ingest.domains import institutions_media as mod
from ingest.domains import institutions_media_rechnungshof as rh
from ingest.domains.institutions_media import (
    DIP_LICENCE,
    DIP_LICENCE_TODO,
    PARDOK_LICENCE,
    WIKIDATA_LICENCE,
    canonical_licence_url,
    licence_is_free,
    licence_sentence,
    main,
    matched_terms,
    media_is_protected,
    normalize_date,
    origin_licence,
    pardok_field,
    parse_rss_items,
    pdf_verdict,
    pick_land_and_city,
    published_dip_key,
    published_pardok_key,
    run,
)


def memory_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript((INGEST_ROOT / "ingest" / "schema.sql").read_text(encoding="utf-8"))
    mod.ensure_tables(conn)
    return conn


class _Offline:
    """Lead: store_* now archive what they cite; offline tests run with the module's offline switch."""
    def setUp(self):
        import ingest.domains.institutions_media as _m
        _m._OFFLINE[0] = True

    def tearDown(self):
        import ingest.domains.institutions_media as _m
        _m._OFFLINE[0] = False


class PureTests(_Offline, unittest.TestCase):
    def test_pdf_verdict_rejects_html_and_404(self):
        self.assertEqual(pdf_verdict(206, "application/pdf", b"%PDF-1.7"), "verified_pdf")
        self.assertEqual(pdf_verdict(200, "application/octet-stream", b"%PDF-1.4"), "verified_pdf")
        self.assertEqual(pdf_verdict(404, "text/html; charset=utf-8", b"<html>\n<body"), "unavailable")
        self.assertEqual(pdf_verdict(200, "application/pdf", b"<!doctype html>"), "unavailable")
        self.assertEqual(pdf_verdict(200, "text/html", b"<html>"), "unavailable")
        self.assertEqual(pdf_verdict(403, "text/html", b""), "unavailable")

    def test_matched_terms_drop_shorter_stem(self):
        self.assertEqual(matched_terms("Wohnungslosigkeit in Großstädten"), ["Wohnungslosigkeit"])
        self.assertEqual(
            matched_terms("Housing First und Wohnungsnotfälle"),
            ["Wohnungsnotfälle", "Housing First"],
        )
        self.assertEqual(matched_terms("Haushalt 2024"), [])

    def test_licence_filter(self):
        self.assertTrue(licence_is_free("CC BY-SA 4.0"))
        self.assertTrue(licence_is_free("CC BY-SA 3.0 de"))
        self.assertTrue(licence_is_free("CC0"))
        self.assertTrue(licence_is_free("Public domain"))
        self.assertTrue(licence_is_free("GFDL 1.2"))
        self.assertFalse(licence_is_free(None))
        self.assertFalse(licence_is_free(""))
        self.assertFalse(licence_is_free("Non-free / fair use"))
        self.assertFalse(licence_is_free("CC BY-NC-SA 4.0"))
        self.assertFalse(licence_is_free("CC BY-ND 4.0"))

    def test_licence_sentence_keeps_ie(self):
        text = (
            "Wikidata's policy statement can be found at Wikidata:Copyright. "
            "All structured data (i.e. the main, Property, Lexeme, and EntitySchema namespaces) "
            "is released into the public domain under Creative Commons Zero. "
            "Text in other namespaces is copyrighted."
        )
        self.assertEqual(
            licence_sentence(text),
            "All structured data (i.e. the main, Property, Lexeme, and EntitySchema namespaces) "
            "is released into the public domain under Creative Commons Zero.",
        )
        self.assertIsNone(licence_sentence("no licence here"))

    def test_land_and_city(self):
        land, city = pick_land_and_city(
            ["Q980=DE-BY"],
            ["Q2978=Regensburg", "Q10555=Oberpfalz"],
        )
        self.assertEqual(land, "BY")
        self.assertIsNone(city)
        land, city = pick_land_and_city(["Q64=DE-BE"], ["Q64=Berlin"])
        self.assertEqual((land, city), ("BE", "Berlin"))
        land, city = pick_land_and_city(["Q1208=DE-BB"], ["Q625741=Lindow (Mark)"])
        self.assertEqual((land, city), ("BB", "Lindow (Mark)"))
        land, city = pick_land_and_city(["Q64=DE-BE", "Q980=DE-BY"], ["Q64=Berlin"])
        self.assertIsNone(land)
        self.assertEqual(city, "Berlin")

    def test_dip_key_parser_does_not_need_a_real_key(self):
        page = "<p>Der gültige API-Key lautet:<br />abcdEF12.ghijklmnopQRSTUV7890</p>"
        key = published_dip_key(page)
        self.assertEqual(key, "abcdEF12.ghijklmnopQRSTUV7890")  # gitleaks:allow (fake test key)
        self.assertIsNone(published_dip_key("<p>no key here</p>"))

    def test_module_has_no_embedded_key(self):
        text = (ROOT / "ingest" / "domains" / "institutions_media.py").read_text(encoding="utf-8")
        self.assertIsNone(re.search(r"""['\"][A-Za-z0-9]{5,}\.[A-Za-z0-9]{20,}['\"]""", text))
        self.assertIsNone(re.search(r"API_KEY\s*=\s*['\"][A-Za-z0-9_\-]{20,}['\"]", text))
        self.assertNotIn("data/atlas.db", text.split("never opens")[0])
        self.assertIn("common.db", text)



    def test_published_pardok_key(self):
        page = (
            '<div>Der zunächst bis Ende Dezember 2026 gültige API-Key lautet:</div>'
            '<div class="h5">abcdEFghijkLMNOPqrstUVWxyz0123456789_xx</div>'
        )
        self.assertEqual(published_pardok_key(page), "abcdEFghijkLMNOPqrstUVWxyz0123456789_xx")
        self.assertIsNone(published_pardok_key("<p>no key here</p>"))

    def test_pardok_field_and_dates(self):
        self.assertEqual(
            pardok_field([{"main": "", "t": "Wohnungslosigkeit in Berlin", "d": "Jugendamt"}], "t", "main"),
            "Wohnungslosigkeit in Berlin",
        )
        self.assertEqual(pardok_field([{"main": "27042"}], "main"), "27042")
        self.assertIsNone(pardok_field([{"main": ""}], "main"))
        self.assertEqual(normalize_date("2026.09.08"), "2026-09-08")
        self.assertEqual(normalize_date("19.03.1993"), "1993-03-19")
        self.assertEqual(normalize_date("Mon, 21 Sep 2026 09:15:24 GMT"), "2026-09-21")

    def test_rss_parser_uses_description_when_title_is_a_number(self):
        xml = b"""<?xml version='1.0' encoding='UTF-8'?>
<rss version='2.0'><channel>
<item>
  <title>Initiativdrucksache 19/13306</title>
  <link>https://example.invalid/by/gegenstandid=167484</link>
  <description>Obdachlosigkeit</description>
  <pubDate>Mon, 21 Sep 2026 09:15:24 GMT</pubDate>
</item>
<item>
  <title>Bericht der Haertefallkommission</title>
  <link>https://example.invalid/hh/1</link>
  <description>ohne Treffer</description>
</item>
</channel></rss>
"""
        items = parse_rss_items(xml)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["title"], "Initiativdrucksache 19/13306")
        self.assertEqual(items[0]["description"], "Obdachlosigkeit")
        self.assertEqual(matched_terms(items[0]["title"], items[0]["description"]), ["Obdachlosigkeit"])
        self.assertEqual(matched_terms(items[1]["title"], items[1]["description"]), [])
        with self.assertRaises(ValueError):
            parse_rss_items(b"<!doctype html><html><item><title>x</title></item></html>")

    def test_elvis_iter_skips_deleted_and_matches_title(self):
        xml = b"""<?xml version='1.0' encoding='utf-8' ?>
<!DOCTYPE Export PUBLIC "-//Landtag NRW//DTD Parlamentsspiegel Export 1.0//DE" "http://example.invalid/export1.dtd">
<Export aktualisiert="2026-11-20T02:24:11">
  <Vorgang><VNr>V-1</VNr><VFunktion>delete</VFunktion></Vorgang>
  <Vorgang>
    <VNr>V-2</VNr>
    <Dokument>
      <ReihNr>0001</ReihNr>
      <Wp>8</Wp>
      <DokTypL>Kleine Anfrage</DokTypL>
      <Titel>Wohnungslosigkeit im Land Brandenburg</Titel>
      <DokNr>08/2836</DokNr>
      <DokDat>20.05.2026</DokDat>
      <LokURL>https://example.invalid/bb/08-2836.pdf</LokURL>
    </Dokument>
    <Dokument>
      <ReihNr>0002</ReihNr>
      <Wp>8</Wp>
      <Titel>Haushaltsplan 2026</Titel>
      <DokNr>08/1</DokNr>
    </Dokument>
  </Vorgang>
</Export>
"""
        pairs = list(mod._iter_elvis_documents(xml))
        self.assertEqual(len(pairs), 2)
        rec = mod._elvis_record(pairs[0][0], pairs[0][1], skip_verify=True, pdf_blocked=[False], catalog_blocked=[False])
        self.assertEqual(rec["dip_id"], "BB-ELVIS:V-2:0001")
        self.assertEqual(rec["land"], "BB")
        self.assertEqual(rec["dokumentnummer"], "08/2836")
        self.assertEqual(rec["datum"], "2026-05-20")
        self.assertEqual(rec["matched_terms"], ["Wohnungslosigkeit"])
        self.assertIsNone(mod._elvis_record(pairs[1][0], pairs[1][1], skip_verify=True, pdf_blocked=[False], catalog_blocked=[False]))

    def test_elvis_maps_retired_starweb_pdf_url(self):
        old = (
            "https://www.parlamentsdokumentation.brandenburg.de/"
            "starweb/LBB/ELVIS/parladoku/w8/drs/ab_2800/2836.pdf"
        )
        new = (
            "https://www.parlamentsdokumentation.brandenburg.de/"
            "parladoku/w8/drs/ab_2800/2836.pdf"
        )
        self.assertEqual(mod.elvis_pdf_url(old), new)
        self.assertEqual(mod.elvis_pdf_url(new), new)
        apr_old = (
            "https://www.parlamentsdokumentation.brandenburg.de/"
            "starweb/LBB/ELVIS/parladoku/w8/apr/AASGZ/14.pdf"
        )
        apr_new = (
            "https://www.parlamentsdokumentation.brandenburg.de/"
            "parladoku/w8/apr/AASGZ/14.pdf"
        )
        self.assertEqual(mod.elvis_pdf_url(apr_old), apr_new)
        self.assertIsNone(mod.elvis_pdf_url(None))
        xml = b"""<?xml version='1.0' encoding='utf-8' ?>
<Export>
  <Vorgang>
    <VNr>V-2</VNr>
    <Dokument>
      <ReihNr>0001</ReihNr>
      <Wp>8</Wp>
      <DokTypL>Kleine Anfrage</DokTypL>
      <Titel>Wohnungslosigkeit im Land Brandenburg</Titel>
      <DokNr>08/2836</DokNr>
      <DokDat>20.05.2026</DokDat>
      <LokURL>https://www.parlamentsdokumentation.brandenburg.de/starweb/LBB/ELVIS/parladoku/w8/drs/ab_2800/2836.pdf</LokURL>
    </Dokument>
  </Vorgang>
</Export>
"""
        pairs = list(mod._iter_elvis_documents(xml))
        rec = mod._elvis_record(
            pairs[0][0], pairs[0][1],
            skip_verify=True, pdf_blocked=[False], catalog_blocked=[False],
        )
        self.assertEqual(rec["pdf_url"], new)
        self.assertEqual(rec["source_url"], new)

    def test_origin_and_canonical_licences(self):
        # Lead: real DIP terms (archived PDF), never the TODO placeholder
        self.assertEqual(origin_licence("bundestag_dip", "DE")[0], DIP_LICENCE)
        self.assertFalse(origin_licence("bundestag_dip")[0].startswith("TODO:"))
        from ingest.domains.institutions_media_rechnungshof import RESERVED_LICENCE
        self.assertEqual(origin_licence("landtag_rss", "BY")[0], RESERVED_LICENCE)
        self.assertEqual(origin_licence("landtag_pardok", "BE")[0], PARDOK_LICENCE)
        elvis_lic, elvis_url, elvis_attr = origin_licence("landtag_elvis", "BB")
        self.assertEqual(elvis_lic, RESERVED_LICENCE)
        self.assertNotIn("TODO", elvis_lic)
        self.assertNotIn("§ 5 UrhG", elvis_lic.replace("§ 51 UrhG", ""))
        self.assertIn("opendata_dokumente", elvis_url)
        self.assertIn("Brandenburg", elvis_attr)
        for land in ("BY", "HH", "SH"):
            lic, url, attr = origin_licence("landtag_rss", land)
            self.assertEqual(lic, RESERVED_LICENCE)
            self.assertNotIn("TODO", lic)
            self.assertTrue(url.startswith("http"))
            self.assertTrue(attr)
        self.assertEqual(
            canonical_licence_url("Public domain", None),
            "https://creativecommons.org/publicdomain/mark/1.0/",
        )
        self.assertEqual(
            canonical_licence_url("CC BY-SA 4.0", "https://creativecommons.org/licenses/by-sa/4.0/deed.de"),
            "https://creativecommons.org/licenses/by-sa/4.0/deed.de",
        )

    def test_protected_facility_drops_wikidata_coordinates(self):
        conn = memory_db()
        sources = []
        notes = []
        rec = {
            "qid": "Q900100",
            "name": "Beispiel Frauenhaus Nord",
            "kind": "frauenhaus",
            "land": "HH",
            "city": "Hamburg",
            "kreis_ags": "02000",
            "address": "Geheimweg 1",
            "plz": "20095",
            "lat": 53.55,
            "lon": 9.99,
            "status": "unknown",
        }
        self.assertTrue(mod.store_facility(conn, rec, license_=WIKIDATA_LICENCE, sources=sources, notes=notes))
        row = conn.execute(
            "SELECT anschrift, plz, lat, lon, kreis_ags, is_protected, source_id FROM facility WHERE name=?",
            ("Beispiel Frauenhaus Nord",),
        ).fetchone()
        self.assertEqual(row["is_protected"], 1)
        self.assertIsNone(row["anschrift"])
        self.assertIsNone(row["plz"])
        self.assertIsNone(row["lat"])
        self.assertIsNone(row["lon"])
        self.assertIsNone(row["kreis_ags"])
        lic = conn.execute("SELECT license, license_url, attribution FROM source WHERE id=?", (row["source_id"],)).fetchone()
        self.assertEqual(lic["license"], "CC0 1.0")
        self.assertEqual(lic["license_url"], "https://www.wikidata.org/wiki/Wikidata:Licensing")
        self.assertEqual(lic["attribution"], "Wikidata contributors")
        # A second write must not restore coordinates.
        rec["qid"] = "Q900100"
        rec["lat"] = 53.6
        rec["lon"] = 10.0
        rec["address"] = "Noch geheimer 2"
        rec["kreis_ags"] = "02000"
        self.assertTrue(mod.store_facility(conn, rec, license_=WIKIDATA_LICENCE, sources=sources, notes=notes))
        row2 = conn.execute(
            "SELECT anschrift, lat, lon, kreis_ags, is_protected FROM facility WHERE name=?",
            ("Beispiel Frauenhaus Nord",),
        ).fetchone()
        self.assertEqual(row2["is_protected"], 1)
        self.assertIsNone(row2["anschrift"])
        self.assertIsNone(row2["lat"])
        self.assertIsNone(row2["lon"])
        self.assertIsNone(row2["kreis_ags"])

    def test_protected_commons_geotags_are_dropped(self):
        page = {
            "title": "File:Frauenhaus Beispielstadt.jpg",
            "imageinfo": [{
                "mediatype": "BITMAP",
                "mime": "image/jpeg",
                "descriptionurl": "https://commons.wikimedia.org/wiki/File:Frauenhaus_Beispielstadt.jpg",
                "extmetadata": {
                    "LicenseShortName": {"value": "CC BY-SA 4.0"},
                    "LicenseUrl": {"value": "https://creativecommons.org/licenses/by-sa/4.0/"},
                    "Artist": {"value": "<a href=\"/wiki/User:Beispiel\">Beispiel</a>"},
                    "Credit": {"value": "Beispiel"},
                    "Attribution": {"value": "Beispiel / CC BY-SA 4.0"},
                    "ImageDescription": {"value": "A shelter. GPSLatitude 53.55 GPSLongitude 9.99"},
                    "Categories": {"value": "Frauenhaus in Hamburg"},
                    "GPSLatitude": {"value": "53.55"},
                    "GPSLongitude": {"value": "9.99"},
                },
            }],
        }
        rec, skip = mod._media_from_page(page)
        self.assertIsNone(skip)
        self.assertTrue(rec["is_protected"])
        self.assertTrue(rec["geotags_dropped"])
        self.assertIsNone(rec["lat"])
        self.assertIsNone(rec["lon"])
        self.assertNotIn("53.55", rec["summary"] or "")
        self.assertNotIn("9.99", rec["summary"] or "")
        self.assertTrue(media_is_protected(rec["title"], rec["categories"]))
        conn = memory_db()
        sources = []
        self.assertTrue(mod.store_media(conn, rec, sources))
        media = conn.execute("SELECT ort, lizenz, urheber, zusammenfassung FROM media").fetchone()
        self.assertIsNone(media["ort"])
        self.assertEqual(media["lizenz"], "CC BY-SA 4.0")
        self.assertEqual(media["urheber"], "Beispiel")
        self.assertNotIn("53.55", media["zusammenfassung"] or "")
        src = conn.execute("SELECT license, license_url, attribution FROM source").fetchone()
        self.assertEqual(src["license"], "CC BY-SA 4.0")
        self.assertEqual(src["license_url"], "https://creativecommons.org/licenses/by-sa/4.0/")
        self.assertEqual(src["attribution"], "Beispiel / CC BY-SA 4.0")
        # Linked to a protected facility by title/category, not only by kind on facility.
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM media WHERE lizenz IS NULL").fetchone()[0], 0)

    def test_commons_skips_missing_and_nonfree_licences(self):
        missing, skip_m = mod._media_from_page({
            "title": "File:NoLic.jpg",
            "imageinfo": [{
                "mediatype": "BITMAP",
                "descriptionurl": "https://commons.wikimedia.org/wiki/File:NoLic.jpg",
                "extmetadata": {"Artist": {"value": "X"}},
            }],
        })
        self.assertIsNone(missing)
        self.assertEqual(skip_m, "licence_missing")
        nonfree, skip_n = mod._media_from_page({
            "title": "File:Fair.jpg",
            "imageinfo": [{
                "mediatype": "BITMAP",
                "descriptionurl": "https://commons.wikimedia.org/wiki/File:Fair.jpg",
                "extmetadata": {
                    "LicenseShortName": {"value": "Non-free / fair use"},
                    "LicenseUrl": {"value": "https://example.invalid/fair"},
                },
            }],
        })
        self.assertIsNone(nonfree)
        self.assertEqual(skip_n, "licence_nonfree")
        self.assertFalse(mod.store_media(memory_db(), {
            "title": "Unlicensed",
            "url": "https://commons.wikimedia.org/wiki/File:NoLic.jpg",
            "kind": "image",
            "license": None,
        }, []))

    def test_commons_public_domain_gets_a_licence_url(self):
        rec, skip = mod._media_from_page({
            "title": "File:PD Example.jpg",
            "imageinfo": [{
                "mediatype": "BITMAP",
                "descriptionurl": "https://commons.wikimedia.org/wiki/File:PD_Example.jpg",
                "extmetadata": {
                    "LicenseShortName": {"value": "Public domain"},
                    "Artist": {"value": "Old photographer"},
                },
            }],
        })
        self.assertIsNone(skip)
        self.assertEqual(rec["license"], "Public domain")
        self.assertEqual(rec["license_url"], "https://creativecommons.org/publicdomain/mark/1.0/")
        self.assertFalse(rec["is_protected"])


class FixtureTests(_Offline, unittest.TestCase):
    def test_fixture_is_idempotent_and_redacts_protected_places(self):
        fixture = ROOT / "tests" / "fixture_institutions_media.json"
        conn = memory_db()
        with mock.patch("ingest.domains.institutions_media.fetch", side_effect=AssertionError("network")), \
             mock.patch("ingest.domains.institutions_media.requests.get", side_effect=AssertionError("network")):
            first = run(conn, {"fixture": str(fixture)})
            second = run(conn, {"fixture": str(fixture)})
        self.assertEqual(first["rows"], second["rows"])
        # Lead: rows whose cited document cannot be archived (e.g. DIP 900002, no verified PDF) are dropped
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM doc").fetchone()[0], 6)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM institutions_media_drucksache").fetchone()[0], 4)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM institutions_media_audit").fetchone()[0], 2)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM source WHERE license LIKE 'TODO%'").fetchone()[0], 0)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM facility").fetchone()[0], 5)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM media").fetchone()[0], 2)
        house = conn.execute(
            "SELECT anschrift, lat, lon FROM facility WHERE kind='frauenhaus'"
        ).fetchone()
        self.assertIsNone(house["anschrift"])
        self.assertIsNone(house["lat"])
        self.assertIsNone(house["lon"])
        money = conn.execute(
            "SELECT COUNT(*) FROM facility WHERE haushalt_eur IS NOT NULL OR kosten_je_platz_eur IS NOT NULL"
        ).fetchone()[0]
        self.assertEqual(money, 0)
        bad_land = conn.execute(
            "SELECT land FROM facility WHERE name='Klinik ohne gültiges Land'"
        ).fetchone()
        self.assertIsNone(bad_land["land"])
        nowhere = conn.execute(
            "SELECT COUNT(*) FROM facility WHERE name_norm IS NOT NULL AND ort IS NULL"
        ).fetchone()[0]
        self.assertGreaterEqual(nowhere, 1)
        second_nowhere = conn.execute(
            "SELECT COUNT(*) FROM facility WHERE name='Klinik ohne Ort'"
        ).fetchone()[0]
        self.assertEqual(second_nowhere, 1)
        # Lead: the Bundesrat fixture paper has no verified PDF, so it is not stored (nothing archivable to cite)
        self.assertIsNone(conn.execute("SELECT 1 FROM doc WHERE herausgeber='Bundesrat'").fetchone())
        be = conn.execute(
            "SELECT land, origin, dokumentnummer FROM institutions_media_drucksache WHERE dip_id='BE-PARDOK:D-900010'"
        ).fetchone()
        self.assertEqual(be["land"], "BE")
        self.assertEqual(be["origin"], "landtag_pardok")
        self.assertEqual(be["dokumentnummer"], "27042")
        lands = {
            row["land"]
            for row in conn.execute("SELECT land FROM institutions_media_drucksache")
        }
        self.assertEqual(lands, {"DE", "BE", "BY", "BB"})   # BB: Brandenburg Nutzungsbedingungen quoted (§ 5 Abs. 2)
        self.assertIsNone(conn.execute(
            "SELECT 1 FROM institutions_media_drucksache WHERE dokumentnummer='20/5'").fetchone())
        missing = conn.execute(
            "SELECT COUNT(*) FROM doc WHERE source_id IS NULL"
        ).fetchone()[0]
        self.assertEqual(missing, 0)
        api = conn.execute(
            """SELECT s.url FROM doc d JOIN source s ON s.id = d.source_id
               WHERE d.title LIKE 'Wohnungslosigkeit%'"""
        ).fetchone()
        self.assertTrue(api["url"].endswith(".pdf"), api["url"])   # Lead: the archived PDF is the cited source
        author = conn.execute("SELECT urheber FROM media WHERE kind='image'").fetchone()
        self.assertEqual(author["urheber"], "Beispiel")
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM media WHERE lizenz LIKE '%fair use%'").fetchone()[0],
            0,
        )
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM source WHERE license IS NULL OR trim(license)=''").fetchone()[0],
            0,
        )
        dip_lic = conn.execute(
            "SELECT s.license FROM source s JOIN institutions_media_drucksache d ON d.source_id=s.id WHERE d.dip_id='900001'"
        ).fetchone()
        self.assertEqual(dip_lic["license"], DIP_LICENCE)
        be_lic = conn.execute(
            """SELECT s.license, s.license_url, s.attribution
               FROM institutions_media_drucksache d JOIN source s ON s.id=d.source_id
               WHERE d.dip_id='BE-PARDOK:D-900010'"""
        ).fetchone()
        self.assertEqual(be_lic["license"], PARDOK_LICENCE)
        self.assertIn("dl-de/by-2-0", be_lic["license_url"])
        self.assertIn("Abgeordnetenhaus", be_lic["attribution"])
        wd = conn.execute(
            "SELECT license, license_url FROM source WHERE url LIKE '%EntityData%Q900001%'"
        ).fetchone()
        self.assertEqual(wd["license"], "CC0 1.0")
        commons = conn.execute(
            "SELECT license, license_url, attribution FROM source WHERE url LIKE '%Beispiel_Obdachlosigkeit.jpg'"
        ).fetchone()
        self.assertEqual(commons["license"], "CC BY-SA 4.0")
        self.assertEqual(commons["license_url"], "https://creativecommons.org/licenses/by-sa/4.0/")
        self.assertEqual(commons["attribution"], "Beispiel")
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM institutions_media_audit").fetchone()[0],
            2,
        )
        euro = conn.execute(
            """SELECT value, einheit, year, locator, quote FROM metric
               WHERE metric='be_isp_wohnungslosenhilfe_plan_eur' AND year=2018"""
        ).fetchone()
        self.assertEqual(euro["value"], 8130474.69)
        self.assertEqual(euro["einheit"], "EUR")
        self.assertIn("S. 197", euro["locator"])
        self.assertIn("8.130.474,69", euro["quote"])
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM metric WHERE metric='be_should_not_store_eur'").fetchone()[0],
            0,
        )
        be_audit = conn.execute(
            """SELECT s.license, s.license_url, a.land, a.court_id, a.pdf_status, d.kind
               FROM institutions_media_audit a
               JOIN source s ON s.id=a.source_id
               JOIN doc d ON d.id=a.doc_id
               WHERE a.report_id='RH-BE:FIXTURE-2019'"""
        ).fetchone()
        self.assertEqual(be_audit["license"], rh.RESERVED_LICENCE)
        self.assertNotIn("TODO", be_audit["license"])
        self.assertNotIn("§ 5 UrhG", be_audit["license"].replace("§ 51 UrhG", ""))
        self.assertTrue(be_audit["license_url"].startswith("https://www.berlin.de/rechnungshof/"))
        redist = conn.execute(
            "SELECT redistribute_fulltext FROM source WHERE id=?",
            (conn.execute("SELECT source_id FROM institutions_media_audit WHERE report_id='RH-BE:FIXTURE-2019'").fetchone()["source_id"],),
        ).fetchone()
        self.assertEqual(redist["redistribute_fulltext"], 0)
        self.assertEqual(be_audit["land"], "BE")
        self.assertEqual(be_audit["court_id"], "RH-BE")
        self.assertEqual(be_audit["kind"], "audit")
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM source WHERE license IS NULL OR trim(license)=''").fetchone()[0],
            0,
        )
        self.assertNotIn("abcdEF12", first["notes"])

    def test_natural_key_collision_does_not_duplicate(self):
        conn = memory_db()
        notes = []
        sources = []
        base = {
            "name": "Klinik Gleich",
            "kind": "psychiatric",
            "land": "HE",
            "city": "Kassel",
            "status": "unknown",
        }
        self.assertTrue(mod.store_facility(conn, {**base, "qid": "Q900010"}, license_=None, sources=sources, notes=notes))
        self.assertFalse(mod.store_facility(conn, {**base, "qid": "Q900011"}, license_=None, sources=sources, notes=notes))
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM facility").fetchone()[0], 1)
        self.assertTrue(any("collision" in note for note in notes))

    def test_shared_landtag_pdf_keeps_two_doc_rows(self):
        conn = memory_db()
        sources = []
        base = {
            "dokumentnummer": "27042",
            "titel": "Wohnungslosigkeit",
            "herausgeber": "BE",
            "land": "BE",
            "origin": "landtag_pardok",
            "catalog_url": "https://example.invalid/be/S19-27042.pdf",
            "pdf_url": "https://example.invalid/be/S19-27042.pdf",
            "catalog_ok": True,
            "pdf_status": "verified_pdf",
        }
        self.assertTrue(mod.store_drucksache(conn, {**base, "dip_id": "BE-PARDOK:D-1", "drucksachetyp": "Antwort", "datum": "2026-09-08"}, license_=None, sources=sources))
        self.assertTrue(mod.store_drucksache(conn, {**base, "dip_id": "BE-PARDOK:D-2", "drucksachetyp": "Schriftliche Anfrage", "datum": "2026-08-18"}, license_=None, sources=sources))
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM institutions_media_drucksache").fetchone()[0], 2)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM doc").fetchone()[0], 2)
        dates = {row["veroeffentlicht"] for row in conn.execute("SELECT veroeffentlicht FROM doc")}
        self.assertEqual(dates, {"2026-09-08", "2026-08-18"})

    def test_landtag_row_without_verified_url_is_rejected(self):

        conn = memory_db()
        sources = []
        rec = {
            "dip_id": "BE-PARDOK:D-1",
            "titel": "Wohnungslosigkeit",
            "herausgeber": "BE",
            "land": "BE",
            "origin": "landtag_pardok",
            "catalog_url": "https://example.invalid/missing.pdf",
            "catalog_ok": False,
            "pdf_status": "unavailable",
        }
        self.assertFalse(mod.store_drucksache(conn, rec, license_=None, sources=sources))
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM institutions_media_drucksache").fetchone()[0], 0)

    def test_cli_refuses_to_open_the_archive(self):
        db = ROOT / "data" / "atlas.db"
        before = (db.stat().st_mtime_ns, db.stat().st_size) if db.exists() else None
        code = main([])
        self.assertEqual(code, 2)
        proc = subprocess.run(
            [sys.executable, "-m", "ingest.domains.institutions_media"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 2)
        self.assertIn("atlas.db", proc.stderr)
        self.assertIn("ingest.run institutions_media", proc.stderr)
        # the Lead's archive exists; the CLI must not have created or touched it
        after = (db.stat().st_mtime_ns, db.stat().st_size) if db.exists() else None
        self.assertEqual(before, after)

    def test_cli_unknown_and_abbreviated_flags_exit_nonzero(self):
        db = ROOT / "data" / "atlas.db"
        before = (db.stat().st_mtime_ns, db.stat().st_size) if db.exists() else None
        for argv in (
            ["--definitely-not-a-flag"],
            ["--dry"],
            ["--selftest", "--wat"],
            ["--dry-run", "--studies"],
        ):
            self.assertEqual(main(argv), 2, argv)
            proc = subprocess.run(
                [sys.executable, "-m", "ingest.domains.institutions_media", *argv],
                cwd=ROOT,
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 2, argv)
            self.assertTrue(proc.stderr, argv)
        # A sub-module has no worker tools and must also refuse, without touching the archive.
        proc = subprocess.run(
            [sys.executable, "-m", "ingest.domains.institutions_media_studies", "--oops"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 2)
        self.assertTrue(proc.stderr)
        after = (db.stat().st_mtime_ns, db.stat().st_size) if db.exists() else None
        self.assertEqual(before, after)


    def test_metric_land_entity_id_is_written_as_ags(self):
        from ingest.domains.institutions_media import metric_geo
        from ingest.domains.institutions_media_rechnungshof import _metric_entity
        self.assertEqual(metric_geo("land", "HH"), ("land", "02"))
        self.assertEqual(metric_geo("land", "02"), ("land", "02"))
        self.assertEqual(metric_geo("bund", "DE"), ("bund", "DE"))
        self.assertEqual(_metric_entity("BE"), ("land", "11"))
        self.assertEqual(_metric_entity("DE"), ("de", "DE"))
        with self.assertRaises(ValueError):
            metric_geo("land", "Hamburg")
        conn = memory_db()
        from ingest.domains.institutions_media_drogentote import store_cited_metric
        # source row required
        conn.execute(
            "INSERT INTO source (url, domain, title, license) VALUES (?,?,?,?)",
            ("https://example.invalid/ags", "institutions_media", "AGS test", "CC0"),
        )
        source_id = conn.execute("SELECT id FROM source").fetchone()[0]
        text = "In Nordrhein-Westfalen wurden 100 Fälle registriert."
        notes = []
        self.assertTrue(store_cited_metric(conn, {
            "entity_type": "land", "entity_id": "NW",
            "metric": "ags_selftest_figure", "year": 2024,
            "value": 100, "unit": "persons",
            "locator": "S. 1",
            "quote": "In Nordrhein-Westfalen wurden 100 Fälle registriert.",
        }, source_id=source_id, document_text=text, notes=notes))
        row = conn.execute("SELECT entity_id FROM metric WHERE metric='ags_selftest_figure'").fetchone()
        self.assertEqual(row["entity_id"], "05")
        # letter codes must not survive in the table
        self.assertIsNone(conn.execute("SELECT 1 FROM metric WHERE entity_type='land' AND entity_id='NW'").fetchone())


    def test_official_city_shelter_gets_kreis_ags_but_not_a_finer_restricted_location(self):
        from ingest.domains import institutions_media_shelters as sh
        self.assertEqual(sh.official_city_kreis_ags("Berlin", "BE"), "11000")
        self.assertEqual(sh.official_city_kreis_ags("München", "BY"), "09162")
        self.assertIsNone(sh.official_city_kreis_ags("Mitte", "BE"))
        self.assertIsNone(sh.official_city_kreis_ags("Berlin", None))
        conn = memory_db()
        sources = []
        rec = {
            "official_key": "TEST-BE:restricted",
            "name": "Notübernachtung für Frauen Testags",
            "kind": "notunterkunft",
            "land": "BE",
            "city": "Berlin",
            "address": "Geheime Straße 1",
            "plz": "10115",
            "district": "Mitte",
            "source_url": "https://example.invalid/kaeltehilfe",
            "official_url": "https://example.invalid/kaeltehilfe",
            "license": sh.RESERVED_LICENCE if hasattr(sh, "RESERVED_LICENCE") else "reserved",
            "redistribute_fulltext": 0,
        }
        # use the same reserved licence string the module already has
        from ingest.domains.institutions_media_rechnungshof import RESERVED_LICENCE
        rec["license"] = RESERVED_LICENCE
        self.assertTrue(sh.store_official_facility(conn, rec, sources=sources))
        row = conn.execute(
            "SELECT land, kreis_ags, anschrift, plz, lat, lon FROM facility WHERE name=?",
            (rec["name"],),
        ).fetchone()
        self.assertEqual(row["land"], "BE")
        self.assertEqual(row["kreis_ags"], "11000")
        self.assertIsNone(row["anschrift"])
        self.assertIsNone(row["plz"])
        self.assertIsNone(row["lat"])

    def test_protected_shelter_stores_no_ags(self):
        """Secret Frauenhaus/Schutzwohnung rows must not keep city or any other AGS."""
        from ingest.domains import institutions_media_shelters as sh
        from ingest.domains.institutions_media_rechnungshof import RESERVED_LICENCE
        conn = memory_db()
        sources = []
        rec = {
            "official_key": "TEST-FH-AGS",
            "name": "Schutzwohnung Testags",
            "kind": "schutzwohnung",
            "land": "HH",
            "city": "Hamburg",
            "address": "Geheime Straße 9",
            "plz": "20095",
            "lat": 53.55,
            "lon": 9.99,
            "district": "Hamburg-Mitte",
            "source_url": "https://example.invalid/official-list",
            "official_url": "https://example.invalid/official-list",
            "license": RESERVED_LICENCE,
            "redistribute_fulltext": 0,
        }
        self.assertTrue(sh.store_official_facility(conn, rec, sources=sources))
        row = conn.execute(
            "SELECT is_protected, land, kreis_ags, ort, anschrift, plz, lat, lon FROM facility WHERE name=?",
            (rec["name"],),
        ).fetchone()
        self.assertEqual(row["is_protected"], 1)
        self.assertIsNone(row["kreis_ags"])
        self.assertIsNone(row["anschrift"])
        self.assertIsNone(row["plz"])
        self.assertIsNone(row["lat"])
        self.assertIsNone(row["lon"])
        # Restricted-group public offers still keep the official city-level Kreis key.
        pub = {
            "official_key": "TEST-NU-AGS",
            "name": "Notübernachtung für Frauen AgsCheck",
            "kind": "notunterkunft",
            "land": "HH",
            "city": "Hamburg",
            "address": "Öffentliche Straße 1",
            "plz": "20095",
            "district": "Altona",
            "source_url": "https://example.invalid/official-list",
            "official_url": "https://example.invalid/official-list",
            "license": RESERVED_LICENCE,
            "redistribute_fulltext": 0,
        }
        self.assertTrue(sh.store_official_facility(conn, pub, sources=sources))
        night = conn.execute(
            "SELECT is_protected, kreis_ags, anschrift FROM facility WHERE name=?",
            (pub["name"],),
        ).fetchone()
        self.assertEqual(night["is_protected"], 0)
        self.assertEqual(night["kreis_ags"], "02000")
        self.assertIsNone(night["anschrift"])


class RechnungshofTests(_Offline, unittest.TestCase):
    def test_rechnungshof_quote_and_substantive_filters(self):
        hyphenated = (
            "sind im Zeitraum von 2019 bis 2025 von 45 Mio. Euro auf 289 Mio. Euro "
            "gestie-\ngen."
        )
        self.assertTrue(rh.quote_in_text(
            "von 45 Mio. Euro auf 289 Mio. Euro gestiegen",
            hyphenated,
        ))
        soft = "Prüfungen bei 32 von insge\u00ad\nsamt 405 Kommunen verhinderten einen finanziellen Nachteil für den Bund von 9,8 Mio.\nEuro."
        self.assertTrue(rh.quote_in_text(
            "Prüfungen bei 32 von insgesamt 405 Kommunen verhinderten einen finanziellen Nachteil für den Bund von 9,8 Mio. Euro.",
            soft,
        ))
        self.assertFalse(rh.quote_in_text("12,3 Mio. Euro", "Kein Betrag in diesem Absatz."))
        self.assertTrue(rh.title_is_kdu("Gewährung von Leistungen für Unterkunft und Heizung durch die Jobcenter"))
        self.assertFalse(rh.title_is_kdu(
            "Bedarfe für Unterkunft und Heizung in der besonderen Wohnform nach § 42a SGB XII"
        ))
        self.assertTrue(rh.audit_is_substantive(
            "Jahresbericht 2019",
            chapter="Unterbringung Wohnungsloser im Land Berlin",
        ))
        self.assertFalse(rh.audit_is_substantive(
            "Jahresbericht 2018",
            document_text="KdU Kosten der Unterkunft\nUm Obdachlosigkeit zu vermeiden mietete die BIM eine Liegenschaft.",
        ))
        licence, url, attr = rh.court_licence("BRH")
        self.assertEqual(licence, rh.RESERVED_LICENCE)
        self.assertNotIn("TODO", licence)
        self.assertNotIn("§ 5 UrhG", licence.replace("§ 51 UrhG", ""))
        self.assertTrue(url.startswith("http"))
        self.assertEqual(attr, "Bundesrechnungshof")
        for court in rh.COURTS:
            self.assertTrue(court["licence"])
            if court["id"] != "BRH":
                # B28 may be stored under DIP TODO at ingest time; court catalogue itself is not DIP.
                self.assertNotIn("TODO", court["licence"])
            self.assertTrue(court["licence_url"].startswith("http"))
            if court["id"] in rh.RESERVED_COURT_IDS:
                self.assertEqual(court["licence"], rh.RESERVED_LICENCE)
                self.assertEqual(court["redistribute_fulltext"], 0)
                self.assertNotIn("§ 5 UrhG", court["licence"].replace("§ 51 UrhG", ""))
            else:
                self.assertIn("§ 5 UrhG", court["licence"])
                self.assertEqual(court.get("redistribute_fulltext"), 1)
        self.assertEqual(len(rh.COURTS), 17)

    def test_rechnungshof_rejects_unverified_pdf_and_missing_licence(self):
        conn = memory_db()
        sources = []
        rec = {
            "report_id": "RH-HH:FIXTURE-BAD",
            "court_id": "RH-HH",
            "report_kind": "jahresbericht",
            "title": "Jahresbericht mit öffentlich-rechtlicher Unterbringung",
            "pdf_url": "https://example.invalid/missing.pdf",
            "pdf_status": "unavailable",
            "document_text": "öffentlich-rechtliche Unterbringung wohnungsloser Menschen",
        }
        self.assertFalse(rh.store_audit(conn, rec, sources=sources, document_text=rec["document_text"]))
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM institutions_media_audit").fetchone()[0], 0)
        rec["pdf_status"] = "verified_pdf"
        rec["license"] = None
        # court licence is used when the record has none, and is never NULL.
        self.assertTrue(rh.store_audit(conn, rec, sources=sources, document_text=rec["document_text"]))
        lic = conn.execute("SELECT license FROM source").fetchone()
        self.assertTrue(lic["license"])
        self.assertNotIn("TODO", lic["license"])
        self.assertIn("§ 5 UrhG", lic["license"])

    def test_local_archive_sha_and_pdf_magic(self):
        data = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
        digest = __import__("hashlib").sha256(data).hexdigest()
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as handle:
            handle.write(data)
            path = handle.name
        rec = {
            "local_archive": path,
            "local_archive_sha256": digest,
            "local_archive_size": len(data),
        }
        self.assertEqual(rh.verify_local_archive(rec), "verified_pdf")
        rec["local_archive_sha256"] = "0" * 64
        self.assertIsNone(rh.verify_local_archive(rec))
        rec["local_archive_sha256"] = digest
        rec["local_archive_size"] = len(data) + 1
        self.assertIsNone(rh.verify_local_archive(rec))
        self.assertIsNone(rh.verify_local_archive({}))

    def test_trim_quote_caps_at_two_sentences(self):
        long = "Erster Satz. Zweiter Satz. Dritter Satz sollte entfallen."
        self.assertEqual(rh.trim_quote(long), "Erster Satz. Zweiter Satz.")
        self.assertEqual(
            rh.trim_quote("Bund trägt jährlich KdU-Leistungen von 10 Mrd. Euro"),
            "Bund trägt jährlich KdU-Leistungen von 10 Mrd. Euro",
        )
        self.assertIsNone(rh.trim_quote(None))
        self.assertEqual(rh.trim_quote("Nur ein Satz."), "Nur ein Satz.")

    def test_reserved_source_sets_redistribute_fulltext_zero(self):
        conn = memory_db()
        sources = []
        rec = {
            "report_id": "RH-HB:FIXTURE-RESERVED",
            "court_id": "RH-HB",
            "report_kind": "jahresbericht",
            "title": "Jahresbericht mit Housing First",
            "chapter": "Projekt Housing First",
            "pdf_url": "https://example.invalid/hb-fixture.pdf",
            "pdf_status": "verified_pdf",
            "document_text": "Housing First und eine Zuwendung in Höhe von rd. 232 T€.",
            "skip_substantive_check": True,
        }
        self.assertTrue(rh.store_audit(conn, rec, sources=sources, document_text=rec["document_text"]))
        row = conn.execute("SELECT license, redistribute_fulltext FROM source").fetchone()
        self.assertEqual(row["license"], rh.RESERVED_LICENCE)
        self.assertEqual(row["redistribute_fulltext"], 0)
        rec["report_id"] = "RH-HH:FIXTURE-OPEN"
        rec["court_id"] = "RH-HH"
        rec["pdf_url"] = "https://example.invalid/hh-fixture.pdf"
        rec["title"] = "Jahresbericht mit öffentlich-rechtlicher Unterbringung"
        self.assertTrue(rh.store_audit(conn, rec, sources=sources, document_text=rec["document_text"]))
        hh = conn.execute(
            "SELECT license, redistribute_fulltext FROM source WHERE url LIKE '%hh-fixture.pdf%'"
        ).fetchone()
        self.assertIn("§ 5 UrhG", hh["license"])
        self.assertEqual(hh["redistribute_fulltext"], 1)


    def test_official_ags5_and_land_code(self):
        from ingest.domains import institutions_media_orgs as orgs
        self.assertEqual(orgs.official_ags5("01001"), "01001")
        self.assertEqual(orgs.official_ags5("1001"), "01001")
        self.assertEqual(orgs.official_ags5(1001), "01001")
        self.assertEqual(orgs.official_ags5("1001.0"), "01001")
        self.assertIsNone(orgs.official_ags5("01001000"))  # Gemeinde, not Kreis
        self.assertIsNone(orgs.official_ags5("DE-01"))
        self.assertIsNone(orgs.official_ags5(""))
        self.assertEqual(orgs.land_code("Schleswig-Holstein"), "SH")
        self.assertEqual(orgs.land_code("TH"), "TH")
        self.assertIsNone(orgs.land_code("France"))

    def test_parse_jobcenter_tables_and_store(self):
        from ingest.domains import institutions_media_orgs as orgs
        zu = [
            ["Zuordnung Jobcenter", "", "", "", "", "", ""],
            ["Stand: 12.11.2026", "", "", "", "", "", ""],
            ["Träger-Nr.", "Jobcenterbezirk (Trägerbezirk der Grundsicherung)", "Träger-Typ",
             "RD-Bezirk 1)", "Kreisschlüssel", "Kreis", "Land"],
            ["11902", "Jobcenter Flensburg, Stadt", "11902", "Nord", "01001",
             "Flensburg, Stadt", "Schleswig-Holstein"],
            ["03208", "Jobcenter Landkreis Rostock", "03208", "Nord", "13072",
             "Landkreis Rostock", "Mecklenburg-Vorpommern"],
            ["03208", "Jobcenter Landkreis Rostock", "03208", "Nord", "13073",
             "Extra-Kreis", "Mecklenburg-Vorpommern"],
        ]
        typ = [
            ["Gebietsstruktur", "", "", "", ""],
            ["Typ 1)", "Träger-Nr.", "Jobcenterbezirk 2)", "RD-Bezirk 3)", "Land"],
            ["gE", "11902", "Jobcenter Flensburg, Stadt", "Nord", "Schleswig-Holstein"],
            ["zkT", "03208", "Jobcenter Landkreis Rostock", "Nord", "Mecklenburg-Vorpommern"],
        ]
        mappings = orgs.parse_jobcenter_zuordnung(zu)
        types = orgs.parse_jobcenter_types(typ)
        self.assertEqual(len(mappings), 3)
        self.assertEqual(mappings[0]["kreis_ags"], "01001")
        self.assertEqual(mappings[0]["land"], "SH")
        self.assertEqual(types["11902"], "gE")
        self.assertEqual(types["03208"], "zkT")
        conn = memory_db()
        sources = []
        rec = {
            "name": "Jobcenter Flensburg, Stadt",
            "traeger_nr": "11902",
            "land": "SH",
            "kreis": "Flensburg, Stadt",
            "kreis_ags": "01001",
            "subtype": "gE",
            "role": "jobcenter",
            "source_url": orgs.JOBCENTER_CATALOG,
            "license": orgs.STATISTIK_LICENCE,
            "license_url": orgs.STATISTIK_IMPRESSUM,
            "attribution": orgs.STATISTIK_ATTRIBUTION,
            "redistribute_fulltext": 1,
        }
        self.assertTrue(orgs.store_landscape_org(conn, rec, sources=sources))
        org = conn.execute("SELECT * FROM org").fetchone()
        self.assertEqual(org["org_type"], "government")
        self.assertEqual(org["land"], "SH")
        self.assertEqual(org["kreis_ags"], "01001")
        self.assertIsNone(org["register_id"])
        link = conn.execute(
            "SELECT * FROM org_link WHERE record_kind=? AND record_key=?",
            ("ba_jobcenter", "BA_JC:11902"),
        ).fetchone()
        self.assertIsNotNone(link)
        self.assertEqual(link["id_value"], "BA_JC:11902")
        self.assertEqual(link["method"], "register_id")
        self.assertEqual(link["flagged"], 0)
        self.assertEqual(link["org_id"], org["id"])
        ba_links = conn.execute(
            "SELECT method, id_value FROM org_link WHERE id_value=?",
            ("BA_JC:11902",),
        ).fetchall()
        self.assertEqual(len(ba_links), 1)
        self.assertEqual(ba_links[0]["method"], "register_id")
        self.assertFalse(any(r["method"] == "origin" for r in ba_links))
        origins = conn.execute(
            "SELECT method, confidence, flagged, id_value FROM org_link "
            "WHERE org_id=? AND method='origin'",
            (org["id"],),
        ).fetchall()
        self.assertEqual(len(origins), 1)
        self.assertEqual(origins[0]["confidence"], 1.0)
        self.assertEqual(origins[0]["flagged"], 0)
        self.assertIsNone(origins[0]["id_value"])
        # A leftover Träger-Nr in register_id from an earlier run is cleared, not left as a court id.
        conn.execute("UPDATE org SET register_id=? WHERE id=?", ("11902", org["id"]))
        self.assertTrue(orgs.store_landscape_org(conn, rec, sources=sources))
        org = conn.execute("SELECT * FROM org WHERE id=?", (org["id"],)).fetchone()
        self.assertIsNone(org["register_id"])
        src = conn.execute("SELECT * FROM source WHERE id=?", (org["source_id"],)).fetchone()
        self.assertIn("uneingeschränkt verwendet", src["license"])
        self.assertEqual(src["attribution"], "© Statistik der Bundesagentur für Arbeit")
        self.assertEqual(src["redistribute_fulltext"], 1)
        meta = conn.execute("SELECT * FROM institutions_media_org").fetchone()
        self.assertEqual(meta["role"], "jobcenter")
        self.assertEqual(meta["subtype"], "gE")
        # invented or malformed AGS is refused
        bad = dict(rec, name="Jobcenter Fiktiv", kreis_ags="99ABC")
        self.assertFalse(orgs.store_landscape_org(conn, bad, sources=sources))
        # missing licence refused
        try:
            orgs.store_landscape_org(conn, dict(rec, name="Jobcenter Ohne Lizenz", license=""), sources=sources)
            raised = False
        except ValueError:
            raised = True
        self.assertTrue(raised or conn.execute("SELECT COUNT(*) FROM org").fetchone()[0] == 1)





    def test_origin_link_and_v6_org_key_includes_legal_form(self):
        from ingest.common import name_norm
        from ingest.domains import institutions_media_orgs as orgs
        from ingest.domains.institutions_media_rechnungshof import RESERVED_LICENCE
        conn = memory_db()
        sources = []
        base = {
            "land": "DE",
            "role": "umbrella",
            "subtype": "korporatives_mitglied",
            "org_type": "nonprofit",
            "publisher": "Bundesarbeitsgemeinschaft Wohnungslosenhilfe e.V.",
            "license": RESERVED_LICENCE,
            "license_url": "https://www.bagw.de/de/impressum",
            "attribution": "Bundesarbeitsgemeinschaft Wohnungslosenhilfe e.V.",
            "redistribute_fulltext": 0,
        }
        ev_id = orgs.store_landscape_org(conn, {
            **base,
            "name": "Beispielhilfe e.V.",
            "legal_form": "e.V.",
            "website": "https://example.invalid/ev",
            "source_url": "https://example.invalid/bagw-ev",
            "source_title": "Mitgliedschaft Beispielhilfe e.V.",
        }, sources=sources)
        gmbh_id = orgs.store_landscape_org(conn, {
            **base,
            "name": "Beispielhilfe gGmbH",
            "legal_form": "gGmbH",
            "website": "https://example.invalid/gmbh",
            "source_url": "https://example.invalid/bagw-gmbh",
            "source_title": "Mitgliedschaft Beispielhilfe gGmbH",
        }, sources=sources)
        self.assertTrue(ev_id)
        self.assertTrue(gmbh_id)
        self.assertNotEqual(ev_id, gmbh_id)
        nn = name_norm("Beispielhilfe e.V.")
        self.assertEqual(nn, name_norm("Beispielhilfe gGmbH"))
        rows = conn.execute(
            "SELECT id, legal_form_norm FROM org WHERE name_norm=? AND land=?",
            (nn, "DE"),
        ).fetchall()
        self.assertEqual(len(rows), 2)
        self.assertEqual({r["legal_form_norm"] for r in rows}, {"ev", "ggmbh"})
        for oid in (ev_id, gmbh_id):
            links = conn.execute(
                "SELECT method, confidence, flagged FROM org_link WHERE org_id=?",
                (oid,),
            ).fetchall()
            origins = [r for r in links if r["method"] == "origin"]
            self.assertEqual(len(origins), 1, links)
            self.assertEqual(origins[0]["confidence"], 1.0)
            self.assertEqual(origins[0]["flagged"], 0)
            self.assertFalse(any(r["method"] == "name_fuzzy" for r in links))

    def test_bagw_korporative_parser_and_reserved_licence(self):
        from ingest.domains import institutions_media_orgs as orgs
        from ingest.domains.institutions_media_rechnungshof import RESERVED_LICENCE
        html = """
        <h2>Korporative Mitglieder</h2>
        <ul>
          <li><a href="https://www.diakonie.de/">Diakonie Deutschland - Evangelischer Bundesverband</a></li>
          <li><a href="https://www.caritas.de/">Deutscher Caritasverband e.V.</a></li>
        </ul>
        <h2>Mitglieder und Mitgliedseinrichtungen</h2>
        <p>240 Träger</p>
        <a href="http://www.feantsa.org">FEANTSA</a>
        """
        rows = orgs.parse_bagw_korporative(html)
        self.assertEqual([r["name"] for r in rows], [
            "Diakonie Deutschland - Evangelischer Bundesverband",
            "Deutscher Caritasverband e.V.",
        ])
        self.assertEqual(rows[0]["website"], "https://www.diakonie.de/")
        conn = memory_db()
        sources = []
        self.assertTrue(orgs.store_landscape_org(conn, {
            "name": orgs.BAGW_NAME,
            "land": "DE",
            "role": "umbrella",
            "subtype": "bundesverband",
            "org_type": "nonprofit",
            "legal_form": "e.V.",
            "website": orgs.BAGW_HOME,
            "source_url": orgs.BAGW_MEMBERSHIP,
            "license": RESERVED_LICENCE,
            "license_url": orgs.BAGW_IMPRESSUM,
            "attribution": orgs.BAGW_NAME,
            "redistribute_fulltext": 0,
        }, sources=sources))
        org = conn.execute("SELECT * FROM org").fetchone()
        self.assertEqual(org["land"], "DE")
        self.assertEqual(org["org_type"], "nonprofit")
        self.assertIsNone(org["strasse"])
        src = conn.execute("SELECT * FROM source WHERE id=?", (org["source_id"],)).fetchone()
        self.assertEqual(src["license"], RESERVED_LICENCE)
        self.assertEqual(src["redistribute_fulltext"], 0)
        self.assertNotIn("§ 5 UrhG", src["license"].replace("§ 51 UrhG", ""))




    def test_protected_and_restricted_group_location_policy(self):
        from ingest.domains import institutions_media_shelters as sh
        from ingest.domains.institutions_media_rechnungshof import RESERVED_LICENCE
        self.assertTrue(sh.is_protected_shelter("notunterkunft", "Frauenhaus Musterstadt"))
        self.assertTrue(sh.is_restricted_group_shelter("Notübernachtung für Frauen in Evas Haltestelle"))
        self.assertTrue(sh.is_restricted_group_shelter("Frauenobdach Karla 51"))
        self.assertTrue(sh.is_restricted_group_shelter("Notschlafstelle für junge Erwachsene", "18 bis 26"))
        self.assertTrue(sh.is_restricted_group_shelter("Queer Nest Notübernachtung"))
        self.assertFalse(sh.is_restricted_group_shelter("Notübernachtung Kubus Porschestrasse", "nur Männer"))
        self.assertFalse(sh.is_restricted_group_shelter(
            "Projekt Ankerplatz (für haftentlassene Männer und Frauen)"
        ))
        self.assertFalse(sh.is_restricted_group_shelter("Notübernachtung St. Marien Liebfrauen"))
        conn = memory_db()
        sources = []
        hidden = {
            "official_key": "TEST-FH-1",
            "name": "Frauenhaus Beispiel",
            "kind": "frauenhaus",
            "land": "BE",
            "city": "Berlin",
            "address": "Geheimstrasse 1, 10115 Berlin",
            "plz": "10115",
            "lat": 52.5,
            "lon": 13.4,
            "district": "Mitte",
            "source_url": "https://example.invalid/official-list",
            "official_url": "https://example.invalid/official-list",
            "source_name": "test",
            "license": RESERVED_LICENCE,
            "redistribute_fulltext": 0,
        }
        self.assertTrue(sh.store_official_facility(conn, hidden, sources=sources))
        row = conn.execute("SELECT * FROM facility WHERE name=?", ("Frauenhaus Beispiel",)).fetchone()
        self.assertEqual(row["is_protected"], 1)
        self.assertIsNone(row["anschrift"])
        self.assertIsNone(row["plz"])
        self.assertIsNone(row["lat"])
        self.assertIsNone(row["lon"])
        self.assertIsNone(row["kreis_ags"])
        side = conn.execute(
            "SELECT * FROM institutions_media_shelter WHERE official_key=?", ("TEST-FH-1",)
        ).fetchone()
        self.assertEqual(side["location_precision"], "protected")
        self.assertIsNone(side["district"])

        pub = {
            "official_key": "TEST-NU-F",
            "name": "Notuebernachtung fuer Frauen Test",
            "kind": "notunterkunft",
            "land": "BE",
            "city": "Berlin",
            "address": "Musterweg 2, 12043 Berlin",
            "plz": "12043",
            "lat": 52.48,
            "lon": 13.43,
            "district": "Neukölln",
            "source_url": "https://kaeltehilfe-berlin.de/kaeltehilfe-angebot",
            "official_url": "https://kaeltehilfe-berlin.de/kaeltehilfe-angebot/x",
            "source_name": "berlin_kaeltehilfe",
            "population_note": "nur Frauen",
            "license": RESERVED_LICENCE,
            "redistribute_fulltext": 0,
        }
        self.assertTrue(sh.store_official_facility(conn, pub, sources=sources))
        night = conn.execute("SELECT * FROM facility WHERE name=?", ("Notuebernachtung fuer Frauen Test",)).fetchone()
        self.assertEqual(night["is_protected"], 0)
        self.assertIsNone(night["anschrift"])
        self.assertIsNone(night["plz"])
        self.assertIsNone(night["lat"])
        self.assertIsNone(night["lon"])
        self.assertIn("Neukölln", night["zielgruppe"] or "")
        night_s = conn.execute(
            "SELECT * FROM institutions_media_shelter WHERE official_key=?", ("TEST-NU-F",)
        ).fetchone()
        self.assertEqual(night_s["location_precision"], "district")
        self.assertEqual(night_s["district"], "Neukölln")
        self.assertEqual(night_s["official_url"], "https://kaeltehilfe-berlin.de/kaeltehilfe-angebot/x")

        mixed = {
            "official_key": "TEST-NU-M",
            "name": "Notuebernachtung Kubus Test",
            "kind": "notunterkunft",
            "land": "BE",
            "city": "Berlin",
            "address": "Porschestr. 22-24, 12107 Berlin",
            "plz": "12107",
            "lat": 52.43,
            "lon": 13.37,
            "district": "Tempelhof-Schöneberg",
            "source_url": "https://kaeltehilfe-berlin.de/kaeltehilfe-angebot",
            "official_url": "https://kaeltehilfe-berlin.de/kaeltehilfe-angebot/y",
            "source_name": "berlin_kaeltehilfe",
            "population_note": "nur Männer",
            "license": RESERVED_LICENCE,
            "redistribute_fulltext": 0,
        }
        self.assertTrue(sh.store_official_facility(conn, mixed, sources=sources))
        men = conn.execute("SELECT * FROM facility WHERE name=?", ("Notuebernachtung Kubus Test",)).fetchone()
        self.assertEqual(men["anschrift"], "Porschestr. 22-24, 12107 Berlin")
        self.assertEqual(men["plz"], "12107")
        self.assertIsNotNone(men["lat"])
        men_s = conn.execute(
            "SELECT * FROM institutions_media_shelter WHERE official_key=?", ("TEST-NU-M",)
        ).fetchone()
        self.assertEqual(men_s["location_precision"], "street")

        youth = {
            "official_key": "TEST-YOUTH",
            "name": "Notschlafstelle für junge Erwachsene",
            "kind": "notunterkunft",
            "land": "NW",
            "city": "Köln",
            "address": "Tiefentalstraße 38, 51063 Köln-Mülheim",
            "plz": "51063",
            "district": "Köln-Mülheim",
            "source_url": "https://www.stadt-koeln.de/service/produkte/00871/index.html",
            "official_url": "https://www.stadt-koeln.de/service/produkte/00871/index.html",
            "source_name": "koeln_notschlafstellen",
            "population_note": "Notschlafstelle für junge Erwachsene (18 bis 26 Jahre)",
            "license": RESERVED_LICENCE,
            "redistribute_fulltext": 0,
        }
        self.assertTrue(sh.store_official_facility(conn, youth, sources=sources))
        yrow = conn.execute(
            "SELECT * FROM facility WHERE name=?", ("Notschlafstelle für junge Erwachsene",)
        ).fetchone()
        self.assertIsNone(yrow["anschrift"])
        self.assertIsNone(yrow["plz"])
        ys = conn.execute(
            "SELECT * FROM institutions_media_shelter WHERE official_key=?", ("TEST-YOUTH",)
        ).fetchone()
        self.assertEqual(ys["location_precision"], "district")
        self.assertEqual(ys["district"], "Köln-Mülheim")
        self.assertTrue(ys["official_url"].startswith("https://www.stadt-koeln.de/"))

        lgbt = {
            "official_key": "TEST-LGBT",
            "name": "Queer / FLINTA Notübernachtung",
            "kind": "notunterkunft",
            "land": "BE",
            "city": "Berlin",
            "address": "Geheimweg 9, 10115 Berlin",
            "plz": "10115",
            "lat": 52.5,
            "lon": 13.4,
            "district": "Mitte",
            "source_url": "https://kaeltehilfe-berlin.de/kaeltehilfe-angebot",
            "official_url": "https://kaeltehilfe-berlin.de/kaeltehilfe-angebot/q",
            "license": RESERVED_LICENCE,
            "redistribute_fulltext": 0,
        }
        self.assertTrue(sh.store_official_facility(conn, lgbt, sources=sources))
        lrow = conn.execute(
            "SELECT * FROM facility WHERE name=?", ("Queer / FLINTA Notübernachtung",)
        ).fetchone()
        self.assertIsNone(lrow["anschrift"])
        self.assertIsNone(lrow["lat"])


    def test_parse_berlin_and_hamburg_official_directories(self):
        from ingest.domains import institutions_media_shelters as sh
        html = (
            '<article typeof="Article">'
            '<h2><a href="/kaeltehilfe-angebot/notuebernachtung-kubus-porschestrasse">'
            "Notuebernachtung Kubus Porschestrasse</a></h2>"
            '<li class="field-entry filter "><span class="field-label ">Filter: </span>'
            '<span class="field-value ">Schlafplatz</span></li>'
            '<li class="field-entry traeger "><span class="field-label ">Traeger: </span>'
            '<span class="field-value ">Kubus gGmbH</span></li>'
            '<li class="field-entry ansprechperson "><span class="field-label ">Ansprechperson: </span>'
            '<span class="field-value ">Erika Mustermann</span></li>'
            '<li class="field-entry adresse "><span class="field-label ">Adresse: </span>'
            '<span class="field-value ">Porschestr. 22-24, 12107 Berlin</span></li>'
            '<li class="field-entry latitude "><span class="field-label ">Latitude: </span>'
            '<span class="field-value ">52.4346951</span></li>'
            '<li class="field-entry longitude "><span class="field-label ">Longitude: </span>'
            '<span class="field-value ">13.3745075</span></li>'
            '<li class="field-entry beschreibung "><span class="field-label ">Beschreibung: </span>'
            '<span class="field-value ">20 Plaetze</span></li>'
            "</article>"
        )
        rows = sh.parse_berlin_kaeltehilfe(html, page_url=sh.BERLIN_LIST)
        self.assertEqual(len(rows), 1)
        rec = rows[0]
        self.assertEqual(rec["kind"], "notunterkunft")
        self.assertEqual(rec["operator"], "Kubus gGmbH")
        self.assertEqual(rec["plz"], "12107")
        # beds pattern uses Plätze/Plaetze
        self.assertEqual(rec["beds"], 20)
        self.assertAlmostEqual(rec["lat"], 52.4346951)
        self.assertNotIn("Mustermann", str(rec))
        import json
        geo = {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [10.03, 53.55]},
                "properties": {
                    "einrichtungsname": "Winternotprogramm Friesenstrasse",
                    "art": "Übernachtungsstätten",
                    "adresse": "Friesenstrasse 22",
                    "ort": "20097 Hamburg",
                    "plaetze": 400,
                },
            }],
        }
        hh = sh.parse_hamburg_geojson(json.dumps(geo).encode())
        self.assertEqual(len(hh), 1)
        self.assertEqual(hh[0]["kind"], "notunterkunft")
        self.assertEqual(hh[0]["beds"], 400)
        self.assertEqual(hh[0]["plz"], "20097")
        self.assertAlmostEqual(hh[0]["lat"], 53.55)
        self.assertEqual(hh[0]["land"], "HH")



    def test_official_slug_and_city_parsers(self):
        from ingest.domains import institutions_media_shelters as sh
        a = sh.official_slug("BE-KH:", "Notübernachtung Kubus Porschestrasse")
        b = sh.official_slug("BE-KH:", "NOTUEBERNACHTUNG KUBUS PORSCHESTRASSE")
        self.assertEqual(a, b)
        self.assertTrue(a.startswith("BE-KH:"))
        self.assertIn("kubus", a)
        self.assertNotEqual(a, "BE-KH:")
        html = """
        <p>Notschlafstellen für Frauen</p>
        <p>Diakonie Michaelshoven e. V.</p>
        <p>Elisabeth-Fry-Haus</p>
        <p>Albert-Schweitzer-Straße 2</p>
        <p>50968 Köln-Raderthal</p>
        <p>Weitere Informationen über das Elisabeth-Fry-Haus</p>
        <p>Stadtplan</p>
        """
        rows = sh.parse_cologne_notschlafstellen(html)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["name"], "Elisabeth-Fry-Haus")
        self.assertEqual(rows[0]["operator"], "Diakonie Michaelshoven e. V.")
        self.assertIn("50968", rows[0]["address"])
        self.assertTrue(rows[0]["official_key"].startswith("K-N:elisabeth"))
        text = (
            "Evangelisches Hilfswerk München\n"
            "Frauenobdach Karla 51\n"
            "und Schutzraum für Frauen (Vierbettzimmer)\n"
            "Karlstraße 51\n"
            "80333 München\n"
            "Telefon: 089 54 91 51-0\n"
        )
        munich = sh.parse_munich_offers(text)
        self.assertEqual(len(munich), 1)
        self.assertEqual(munich[0]["name"], "Frauenobdach Karla 51")
        self.assertEqual(munich[0]["kind"], "notunterkunft")
        self.assertIn("Karlstraße 51", munich[0]["address"] or "")
        self.assertTrue(sh.is_restricted_group_shelter(munich[0]["name"]))
        self.assertFalse(sh.is_protected_shelter(munich[0]["kind"], munich[0]["name"]))



    def test_investigation_quote_and_private_names(self):
        from ingest.domains import institutions_media_investigations as inv
        from ingest.domains.institutions_media_rechnungshof import RESERVED_LICENCE
        self.assertFalse(inv.stored_fields_name_ok("Frank sitzt in der Tagesstätte"))
        self.assertTrue(inv.stored_fields_name_ok("Die Zahl der wohnungslosen Menschen steigt seit Jahren."))
        html = "<html><p>Die Zahl der wohnungslosen Menschen steigt seit Jahren. Mehr Text.</p></html>"
        self.assertTrue(inv.quote_in_page("Die Zahl der wohnungslosen Menschen steigt seit Jahren.", inv.page_text(html.encode())))
        self.assertFalse(inv.quote_in_page("Dieser Satz steht nicht auf der Seite.", inv.page_text(html.encode())))
        conn = memory_db()
        sources = []
        rec = {
            "url": "https://example.invalid/investigation",
            "outlet": "CORRECTIV",
            "title": "Testrecherche Wohnungslosigkeit",
            "published": "2023-03-17",
            "land": "DE",
            "quote": "Die Zahl der wohnungslosen Menschen steigt seit Jahren.",
            "license": RESERVED_LICENCE,
            "redistribute_fulltext": 0,
        }
        self.assertTrue(inv.store_investigation(conn, rec, sources=sources))
        doc = conn.execute("SELECT * FROM doc WHERE url=?", (rec["url"],)).fetchone()
        self.assertEqual(doc["kind"], "investigation")
        self.assertEqual(doc["zusammenfassung"], rec["quote"])
        self.assertIsNone(doc["urheber"])
        src = conn.execute("SELECT * FROM source WHERE url=?", (rec["url"],)).fetchone()
        self.assertEqual(src["license"], RESERVED_LICENCE)
        self.assertEqual(src["redistribute_fulltext"], 0)
        self.assertNotIn("CC BY", src["license"] or "")
        self.assertNotIn("Creative Commons", src["license"] or "")
        bad = dict(rec, url="https://example.invalid/named", quote="Ulf war 13 Jahre obdachlos.")
        self.assertFalse(inv.store_investigation(conn, bad, sources=sources))
        self.assertIsNone(conn.execute("SELECT 1 FROM doc WHERE url=?", (bad["url"],)).fetchone())
        # every catalog row itself must be clean and have a short quote
        self.assertGreaterEqual(len(inv.CATALOG), 20)
        self.assertLessEqual(len(inv.CATALOG), 40)
        for item in inv.CATALOG:
            self.assertTrue(inv.stored_fields_name_ok(item["title"], item["quote"], item["outlet"]))
            self.assertTrue(20 <= len(item["quote"]) <= 280)
            self.assertTrue(item["url"].startswith("https://"))
            self.assertTrue(item["published"])



class DrogentoteTests(unittest.TestCase):
    def test_parse_official_2022_land_table(self):
        from ingest.domains import institutions_media_drogentote as dg
        text = (
            "Anzahl der Rauschgifttoten\n"
            "Baden-Württemberg                                      179\n"
            "Bayern                                                 277\n"
            "Berlin                                                 230\n"
            "Brandenburg                                             24\n"
            "Bremen                                                  29\n"
            "Hamburg                                                 96\n"
            "Hessen                                                  97\n"
            "Mecklenburg-Vorpommern                                  11\n"
            "Niedersachsen                                          117\n"
            "Nordrhein-Westfalen                                    703\n"
            "Rheinland-Pfalz                                         52\n"
            "Saarland                                                43\n"
            "Sachsen                                                 24\n"
            "Sachsen-Anhalt                                          19\n"
            "Schleswig-Holstein                                      56\n"
            "Thüringen                                               33\n"
            "Summe                                                 1990\n"
        )
        table = dg.parse_land_death_table(text)
        self.assertEqual(len([k for k in table if k != "DE"]), 16)
        self.assertEqual(table["DE"], 1990)
        self.assertEqual(table["NW"], 703)
        self.assertEqual(table["BY"], 277)
        self.assertEqual(table["BE"], 230)
        self.assertEqual(table["MV"], 11)
        self.assertEqual(sum(v for k, v in table.items() if k != "DE"), 1990)

    def test_cited_metric_requires_quote_and_sets_reserved_licence(self):
        from ingest.domains import institutions_media_drogentote as dg
        conn = memory_db()
        sources = []
        sid = mod._register_source(
            conn, "https://example.invalid/lagebild.pdf",
            title="fixture lagebild", publisher="Bundeskriminalamt",
            license_=dg.RESERVED_LICENCE, license_url=dg.BKA_IMPRESSUM,
            attribution="Bundeskriminalamt", notes="fixture",
            redistribute_fulltext=0, bucket=sources,
        )
        document = "Im Jahr 2025 wurden in Deutschland polizeilich insgesamt 2.150 drogenbedingte Todesfälle registriert."
        ok = dg.store_cited_metric(conn, {
            "entity_type": "bund", "entity_id": "DE", "metric": "drug_deaths",
            "year": 2025, "value": 2150, "unit": "persons",
            "locator": "S. 23", "quote": document,
        }, source_id=sid, document_text=document, notes=[])
        self.assertTrue(ok)
        row = conn.execute("SELECT * FROM metric").fetchone()
        self.assertEqual(row["value"], 2150)
        self.assertEqual(row["locator"], "S. 23")
        self.assertTrue(row["quote"])
        missed = dg.store_cited_metric(conn, {
            "entity_type": "bund", "entity_id": "DE", "metric": "drug_deaths_male",
            "year": 2025, "value": 1777, "unit": "persons",
            "locator": "S. 23", "quote": "Diese Zahl steht nicht in dem Dokument.",
        }, source_id=sid, document_text=document, notes=[])
        self.assertFalse(missed)
        src = conn.execute("SELECT license, redistribute_fulltext FROM source").fetchone()
        self.assertEqual(src["license"], dg.RESERVED_LICENCE)
        self.assertEqual(src["redistribute_fulltext"], 0)
        self.assertNotIn("TODO", src["license"])
        self.assertNotIn("§ 5 UrhG", src["license"].replace("§ 51 UrhG", ""))

    def test_catalog_figures_have_locator_quote_and_no_homeless_deaths(self):
        from ingest.domains import institutions_media_drogentote as dg
        self.assertGreaterEqual(len(dg.FIGURES), 20)
        for rec in dg.FIGURES:
            self.assertTrue(rec["locator"])
            self.assertTrue(rec["quote"])
            self.assertIn(rec["source"], dg.SOURCES)
            self.assertIsInstance(rec["value"], (int, float))
            self.assertNotIn("TODO", rec.get("note") or "")
            low = (rec["quote"] + rec["metric"]).casefold()
            self.assertNotIn("obdachlos", low)
            self.assertNotIn("wohnungslos", low)
        for meta in dg.SOURCES.values():
            self.assertTrue(meta["url"].startswith("https://"))
            self.assertTrue("bka.de" in meta["url"] or "bundesdrogenbeauftragter.de" in meta["url"])



class PksVictimisationTests(unittest.TestCase):
    def test_parse_t941_obdach_totals(self):
        from ingest.domains import institutions_media_pks as pks
        # Minimal official-shaped grid: Obdachlosigkeit is the last group (3 columns).
        rows = [
            ["Polizeiliche Kriminalstatistik", "", "", "", "", "Tabelle 941"],
            ["Schlüssel", "Straftat", "Fall-status", "Andere", "", "", "Obdachlosigkeit", "", ""],
            ["", "", "", "insg.", "männl.", "weibl.", "insg.", "männl.", "weibl."],
            ["------", "Straftaten insgesamt", "voll.", "10", "8", "2", "2012", "1539", "473"],
            ["------", "Straftaten insgesamt", "vers.", "1", "1", "0", "182", "134", "48"],
            ["------", "Straftaten insgesamt", "insg.", "11", "9", "2", "2194", "1673", "521"],
            ["220000", "Körperverletzung §§ 223-227, 229, 231 StGB", "insg.", "5", "4", "1", "1644", "1305", "339"],
            ["892000", "Gewaltkriminalität", "insg.", "4", "3", "1", "955", "785", "170"],
            ["210000", "Raub, räuberische Erpressung und räuberischer Angriff auf Kraftfahrer", "insg.", "2", "2", "0", "209", "183", "26"],
        ]
        parsed = pks.parse_t941_obdach_totals(rows)
        self.assertEqual(parsed["total"]["total"], 2194)
        self.assertEqual(parsed["total"]["male"], 1673)
        self.assertEqual(parsed["total"]["female"], 521)
        self.assertEqual(parsed["offences"]["220000"]["total"], 1644)
        self.assertEqual(parsed["offences"]["892000"]["total"], 955)
        self.assertEqual(parsed["offences"]["210000"]["total"], 209)

    def test_parse_drs_land_tables_2022_2024(self):
        from ingest.domains import institutions_media_pks as pks
        text = """
        Berichtsjahr 2024
        Anzahl der Opfer mit Opferspezifik „Obdachlosigkeit“ gesamt männlich weiblich
        Berlin 498 380 118
        Nordrhein-Westfalen 351 258 93
        Sachsen 69 48 21
        Sachsen-Anhalt 12 12 0
        Bundesrepublik Deutschland 2 194 1 673 521
        Berichtsjahr 2023
        Anzahl der Opfer mit Opferspezifik „Obdachlosigkeit“ gesamt männlich weiblich
        Berlin 441 352 89
        Bundesrepublik Deutschland 2 180 1 706 474
        Berichtsjahr 2022
        Anzahl der Opfer mit Opferspezifik „Obdachlosigkeit“ gesamt männlich weiblich
        Berlin 421 337 84
        Bundesrepublik Deutschland 1 986 1 537 449
        Landkreis Anzahl an Fällen
        Berlin 486
        """
        tables = pks.parse_drs_land_tables(text)
        de24 = next(r for r in tables[2024] if r["entity_id"] == "DE")
        self.assertEqual(de24["total"], 2194)
        self.assertEqual(de24["male"], 1673)
        self.assertEqual(de24["female"], 521)
        be24 = next(r for r in tables[2024] if r["entity_id"] == "BE")
        self.assertEqual(be24["total"], 498)
        sn = next(r for r in tables[2024] if r["entity_id"] == "SN")
        self.assertEqual(sn["total"], 69)
        st = next(r for r in tables[2024] if r["entity_id"] == "ST")
        self.assertEqual(st["total"], 12)
        de22 = next(r for r in tables[2022] if r["entity_id"] == "DE")
        self.assertEqual(de22["total"], 1986)
        # Kreis appendix must not be parsed as a Land year
        self.assertEqual(set(tables), {2022, 2023, 2024})

    def test_module_does_not_ingest_suspects_without_fixed_address(self):
        from ingest.domains import institutions_media_pks as pks
        from pathlib import Path
        src = Path(pks.__file__).read_text(encoding="utf-8")
        self.assertIn("Opferspezifik", src)
        self.assertIn("Obdachlosigkeit", src)
        self.assertIn("Tatverdächtige", src)  # only in the denial/caveat
        self.assertIn("not ingested", src.casefold())
        self.assertNotIn("ohne_festen_wohnsitz", src.casefold())
        self.assertNotIn("pks_suspect", src)
        self.assertEqual(pks.PKS_LICENCE.startswith("Datenlizenz Deutschland"), True)
        self.assertIn("dl-de/by-2-0", pks.PKS_LICENCE)
        self.assertEqual(pks.pks_attribution(2024, "V1.0"), "PKS Bundeskriminalamt, 2024, V1.0")



class JvaPsychTests(unittest.TestCase):
    def test_parse_psych_care_beds_deutschland(self):
        from ingest.domains import institutions_media_jva_psych as jp
        text = (
            "Tabelle 1: Krankenhausbetten in der psychiatrischen Versorgung "
            "in Deutschland und im europäischen Vergleich in den Jahren 2014 bis 2023\n"
            "Land 2014 2015 2016 2017 2018 2019 2020 2021 2022 2023\n"
            "Deutschland 102.916 103.992 105.026 106.176 107.508 108.519 108.099 108.898 109.991 110.943\n"
            "Quelle: Statistisches Bundesamt, Grunddaten der Krankenhäuser\n"
        )
        series = jp.parse_psych_care_beds_deutschland(text)
        self.assertEqual(series[2014], 102916)
        self.assertEqual(series[2020], 108099)
        self.assertEqual(series[2023], 110943)
        self.assertEqual(len(series), 10)
        self.assertGreater(series[2023], series[2014])

    def test_nrw_gap_is_flag_zero_not_a_count_of_releases(self):
        from ingest.domains import institutions_media_jva_psych as jp
        conn = memory_db()
        sources = []
        sid = mod._register_source(
            conn, jp.NRW_1283["url"], title=jp.NRW_1283["title"],
            publisher=jp.NRW_1283["publisher"], license_=jp.NRW_1283["license"],
            license_url=jp.NRW_1283["license_url"], attribution=jp.NRW_1283["attribution"],
            notes="fixture", redistribute_fulltext=1, bucket=sources,
        )
        quote = "Der Landesregierung liegen zur Beantwortung dieser Frage keine validen Daten vor."
        ok = jp.store_cited_metric(conn, {
            "entity_type": "land", "entity_id": "05",
            "metric": "jva_release_homeless_data_available",
            "year": 2022, "value": 0, "unit": "flag",
            "locator": "Drs 18/1283, S. 1, Antwort zu Frage 1",
            "quote": quote,
            "note": "documented official data gap, not a count of zero releases",
        }, source_id=sid, document_text="Frage 1. " + quote + " Die Angaben basieren auf freiwilligen Angaben.", notes=[])
        self.assertTrue(ok)
        row = conn.execute("SELECT * FROM metric").fetchone()
        self.assertEqual(row["value"], 0)
        self.assertEqual(row["einheit"], "flag")
        self.assertIn("gap", row["anmerkung"])
        self.assertNotIn("TODO", jp.NRW_1283["license"])

    def test_module_does_not_treat_beds_as_closures_or_overlap_counts_law(self):
        from ingest.domains import institutions_media_jva_psych as jp
        from pathlib import Path
        src = Path(jp.__file__).read_text(encoding="utf-8")
        self.assertIn("documented hospital closure", src)
        self.assertIn("Wohnungslosenbericht", src)
        self.assertIn("22971", src)
        self.assertIn("23111", src)
        self.assertNotIn("TODO", jp.DEST_LICENCE)
        self.assertIn("dl-de/by-2-0", jp.DEST_LICENCE)

    def test_studies_catalogue_has_required_metadata_and_avoids_counts_law(self):
        from ingest.domains import institutions_media_studies as st
        from ingest.domains.institutions_media_rechnungshof import RESERVED_LICENCE
        self.assertGreaterEqual(len(st.CATALOG), 8)
        self.assertLessEqual(len(st.CATALOG), 20)
        seen_urls=set()
        for rec in st.CATALOG:
            self.assertTrue(st.required_metadata_ok(rec), rec.get("key"))
            self.assertTrue(st.stored_fields_name_ok(
                rec.get("title"), rec.get("author"), rec.get("quote"),
                rec.get("commissioning_body"), rec.get("authors_organisation"),
            ), rec.get("key"))
            self.assertNotIn(rec["url"], seen_urls)
            seen_urls.add(rec["url"])
            self.assertTrue(rec["url"].startswith("http"))
            self.assertIsInstance(rec["year"], int)
            self.assertTrue(rec["commissioning_body"])
            self.assertTrue(rec["authors_organisation"])
            self.assertTrue(rec["license"])
            self.assertNotIn("TODO", rec["license"])
            self.assertNotIn("wohnungslosenbericht-2024", rec["url"])
            self.assertNotIn("wohnungslosenbericht-2022", rec["url"])
            for metric in rec.get("metrics") or []:
                self.assertFalse(
                    st.figure_held_by_counts_law(metric.get("value"), metric.get("unit")),
                    f"{rec['key']} {metric['metric']}={metric['value']}",
                )
                self.assertTrue(20 <= len(metric["quote"]) <= 400, metric["metric"])
                self.assertTrue(metric.get("locator"))
        # known overlap figures must be blocked for person/household counts
        self.assertTrue(st.figure_held_by_counts_law(531601, "persons"))
        self.assertTrue(st.figure_held_by_counts_law(1976, "persons"))
        # FB 534 2018 range is stored as its own series, not treated as a counts_law overlap
        self.assertFalse(st.figure_held_by_counts_law(313000, "persons"))
        self.assertFalse(st.figure_held_by_counts_law(337000, "persons"))
        self.assertFalse(st.figure_held_by_counts_law(85, "percent"))
        self.assertFalse(st.figure_held_by_counts_law(151, "municipalities"))
        self.assertFalse(st.figure_held_by_counts_law(5.8, "per_1000_households"))
        self.assertIn("CC BY 4.0", [r["license"] for r in st.CATALOG])
        self.assertTrue(any(r["license"] == RESERVED_LICENCE for r in st.CATALOG))
        fb534 = next(r for r in st.CATALOG if r["key"] == "fb534")
        lows = [m for m in fb534["metrics"] if m["metric"] == "fb534_homeless_estimate_low"]
        highs = [m for m in fb534["metrics"] if m["metric"] == "fb534_homeless_estimate_high"]
        self.assertEqual(len(lows), 1)
        self.assertEqual(len(highs), 1)
        self.assertEqual(lows[0]["value"], 313000)
        self.assertEqual(highs[0]["value"], 337000)
        self.assertEqual(lows[0]["year"], 2018)
        self.assertEqual(highs[0]["year"], 2018)
        self.assertEqual(lows[0]["is_est"], 1)
        self.assertEqual(highs[0]["is_est"], 1)
        self.assertEqual(lows[0]["note"], "BMAS FB 534 Schätzung 2018")
        self.assertEqual(highs[0]["note"], "BMAS FB 534 Schätzung 2018")
        self.assertEqual(lows[0]["locator"], highs[0]["locator"])
        self.assertIn("313.000", lows[0]["quote"])
        self.assertIn("337.000", highs[0]["quote"])
        self.assertIn("31.05.2018", lows[0]["quote"])

    def test_store_study_writes_kind_licence_and_sidecar(self):
        from ingest.domains import institutions_media_studies as st
        from ingest.domains.institutions_media_rechnungshof import RESERVED_LICENCE
        conn = memory_db()
        sources = []
        rec = {
            "url": "https://example.invalid/study.pdf",
            "title": "Tesstudie zur Wohnungslosigkeit in einer Kommune",
            "year": 2021,
            "published": "2021-12",
            "land": "BE",
            "commissioning_body": "Senatsverwaltung für Integration, Arbeit und Soziales Berlin",
            "authors_organisation": "Alice Salomon Hochschule Berlin",
            "author": "Susanne Gerull (Alice Salomon Hochschule Berlin)",
            "publisher": "Senatsverwaltung für Integration, Arbeit und Soziales Berlin",
            "license": RESERVED_LICENCE,
            "license_url": "https://example.invalid/impressum",
            "redistribute_fulltext": 0,
            "quote": "Bis zum Ablauf der Modellprojektphase sind 44 Aufnahmen ins Projekt erfolgt.",
            "source_notes": "Short quotes only.",
        }
        self.assertTrue(st.store_study(conn, rec, sources=sources))
        doc = conn.execute("SELECT * FROM doc WHERE url=?", (rec["url"],)).fetchone()
        self.assertEqual(doc["kind"], "study")
        self.assertEqual(doc["urheber"], rec["author"])
        self.assertEqual(doc["zusammenfassung"], rec["quote"])
        side = conn.execute("SELECT * FROM institutions_media_study WHERE url=?", (rec["url"],)).fetchone()
        self.assertEqual(side["commissioning_body"], rec["commissioning_body"])
        self.assertEqual(side["authors_organisation"], rec["authors_organisation"])
        self.assertEqual(side["year"], 2021)
        src = conn.execute("SELECT * FROM source WHERE url=?", (rec["url"],)).fetchone()
        self.assertEqual(src["license"], RESERVED_LICENCE)
        self.assertEqual(src["redistribute_fulltext"], 0)
        self.assertNotIn("TODO", src["license"])
        # missing metadata is rejected
        bad = dict(rec, url="https://example.invalid/bad.pdf", commissioning_body="")
        self.assertFalse(st.store_study(conn, bad, sources=sources))
        self.assertIsNone(conn.execute("SELECT 1 FROM doc WHERE url=?", (bad["url"],)).fetchone())

    def test_store_cited_study_metric_respects_counts_law_block(self):
        from ingest.domains import institutions_media_studies as st
        from ingest.domains.institutions_media_drogentote import store_cited_metric
        from ingest.domains.institutions_media_rechnungshof import RESERVED_LICENCE
        conn = memory_db()
        sources = []
        rec = {
            "url": "https://example.invalid/overlap.pdf",
            "title": "Tesstudie ohne Dopplung",
            "year": 2022,
            "published": "2022",
            "land": "DE",
            "commissioning_body": "Bundesministerium für Arbeit und Soziales",
            "authors_organisation": "GISS e. V.",
            "author": "GISS e. V.",
            "publisher": "Bundesministerium für Arbeit und Soziales",
            "license": RESERVED_LICENCE,
            "redistribute_fulltext": 0,
            "quote": "In 151 deutschen Städten und Gemeinden wurde eine Stichprobe gezogen.",
        }
        self.assertTrue(st.store_study(conn, rec, sources=sources))
        source_id = conn.execute("SELECT source_id FROM doc WHERE url=?", (rec["url"],)).fetchone()[0]
        text = "In Deutschland waren 262.600 Menschen wohnungslos. In 151 deutschen Städten und Gemeinden wurde eine Stichprobe gezogen."
        notes = []
        blocked = {
            "entity_type": "de", "entity_id": "DE",
            "metric": "wb_total_homeless", "year": 2022,
            "value": 262600, "unit": "persons",
            "locator": "PDF-S. 1",
            "quote": "In Deutschland waren 262.600 Menschen wohnungslos.",
        }
        self.assertTrue(st.figure_held_by_counts_law(262600, "persons"))
        # ingest path must skip; store_cited_metric itself will still write if called, so we test the gate
        if st.figure_held_by_counts_law(blocked["value"], blocked["unit"]):
            notes.append("blocked")
        else:
            store_cited_metric(conn, blocked, source_id=source_id, document_text=text, notes=notes)
        self.assertEqual(notes, ["blocked"])
        self.assertIsNone(conn.execute("SELECT 1 FROM metric WHERE metric='wb_total_homeless'").fetchone())
        okm = {
            "entity_type": "de", "entity_id": "DE",
            "metric": "fb605_survey_municipalities", "year": 2022,
            "value": 151, "unit": "municipalities",
            "locator": "PDF-S. 5",
            "quote": "In 151 deutschen Städten und Gemeinden wurde eine Stichprobe gezogen.",
        }
        self.assertTrue(store_cited_metric(conn, okm, source_id=source_id, document_text=text, notes=notes))
        row = conn.execute("SELECT * FROM metric WHERE metric='fb605_survey_municipalities'").fetchone()
        self.assertEqual(row["value"], 151)
        self.assertEqual(row["einheit"], "municipalities")



class MoreCityShelterTests(_Offline, unittest.TestCase):

    def test_more_city_shelter_catalogue_privacy_and_needles(self):
        from ingest.domains import institutions_media_shelters as sh
        from ingest.domains import institutions_media_shelters_more as more
        from ingest.domains.institutions_media_rechnungshof import RESERVED_LICENCE

        keys = [more.official_key_for(o) for o in more.OFFERS]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertGreaterEqual(len(more.OFFERS), 60)
        self.assertIn("duesseldorf", more.SOURCES)
        self.assertIn("frankfurt.de", more.FRANKFURT_URL)

        folded = more.fold_page_text(
            "Die Notschlafstelle Ariadne für Frauen auf der Friedrich-Ebert-Str. 55 "
            "bietet Platz für 36 Personen."
        )
        self.assertFalse(more.needles_found(folded, ["Ariadne", "Friedrich-Ebert-Straße 55", "für Frauen"]))
        self.assertTrue(more.needles_found(folded, ["Graf-Adolf-Straße 73"]))

        restricted = street = 0
        for offer in more.OFFERS:
            rec = more.record_from_offer(offer, more.SOURCES[offer["source"]])
            self.assertTrue(rec["official_key"])
            self.assertTrue(rec["license"])
            self.assertNotIn("TODO", rec["license"])
            self.assertIsNone(rec.get("lat"))
            self.assertIsNone(rec.get("lon"))
            is_r = sh.is_restricted_group_shelter(
                rec["name"], rec.get("operator"), rec.get("population_note"), rec.get("district")
            )
            if is_r:
                restricted += 1
            else:
                street += 1
            if "für Frauen" in (rec["name"] + " " + (rec.get("population_note") or "")) and "Männer" not in (rec.get("population_note") or ""):
                if "Frauen und Männer" not in (rec.get("population_note") or "") and "Männer, Frauen" not in (rec.get("population_note") or ""):
                    self.assertTrue(is_r, rec["name"])
        self.assertGreaterEqual(restricted, 20)
        self.assertGreater(street, restricted)

        conn = memory_db()
        sources = []
        women = next(o for o in more.OFFERS if o["name"].startswith("Notschlafstelle Ariadne"))
        men = next(o for o in more.OFFERS if o["name"].startswith("Notunterkunft Harkort"))
        self.assertTrue(sh.store_official_facility(
            conn, more.record_from_offer(women, more.SOURCES[women["source"]]), sources=sources
        ))
        self.assertTrue(sh.store_official_facility(
            conn, more.record_from_offer(men, more.SOURCES[men["source"]]), sources=sources
        ))
        wrow = conn.execute(
            "SELECT f.*, s.location_precision, s.district, s.official_url "
            "FROM facility f JOIN institutions_media_shelter s ON s.facility_id=f.id "
            "WHERE f.name_norm=?",
            (sh.name_norm(women["name"]),),
        ).fetchone()
        mrow = conn.execute(
            "SELECT f.*, s.location_precision FROM facility f "
            "JOIN institutions_media_shelter s ON s.facility_id=f.id "
            "WHERE f.name_norm=?",
            (sh.name_norm(men["name"]),),
        ).fetchone()
        self.assertEqual(wrow["location_precision"], "district")
        self.assertIsNone(wrow["anschrift"])
        self.assertIsNone(wrow["plz"])
        self.assertIsNone(wrow["lat"])
        self.assertTrue(wrow["official_url"])
        self.assertEqual(mrow["location_precision"], "street")
        self.assertIn("Harkort", mrow["anschrift"] or "")
        src = conn.execute("SELECT * FROM source WHERE id=?", (wrow["source_id"],)).fetchone()
        self.assertEqual(src["license"], RESERVED_LICENCE)
        self.assertEqual(src["redistribute_fulltext"], 0)
        self.assertNotIn("TODO", src["license"])
        self.assertEqual(wrow["kreis_ags"], "05111")
        self.assertEqual(mrow["kreis_ags"], "05111")
        self.assertEqual(wrow["is_protected"], 0)

        for offer in more.OFFERS:
            rec = more.record_from_offer(offer, more.SOURCES[offer["source"]])
            self.assertTrue(sh.store_official_facility(conn, rec, sources=sources))
        rows = conn.execute(
            "SELECT name, land, ort, kreis_ags, anschrift, plz, lat, lon, is_protected "
            "FROM facility"
        ).fetchall()
        self.assertEqual(len(rows), len(more.OFFERS))
        for row in rows:
            if row["is_protected"]:
                self.assertIsNone(row["kreis_ags"], row["name"])
                self.assertIsNone(row["anschrift"], row["name"])
                self.assertIsNone(row["plz"], row["name"])
                self.assertIsNone(row["lat"], row["name"])
                self.assertIsNone(row["lon"], row["name"])
            else:
                expected = sh.official_city_kreis_ags(row["ort"], row["land"])
                self.assertEqual(row["kreis_ags"], expected, row["name"])

    def test_hf_frauen_in_support_note_includes_not_yet_housed(self):
        from ingest.domains import institutions_media_studies as st
        entry = next(item for item in st.CATALOG if item["key"] == "hf_frauen")
        metrics = {m["metric"]: m for m in entry["metrics"]}
        self.assertEqual(metrics["hf_frauen_admissions"]["value"], 75)
        self.assertEqual(metrics["hf_frauen_housed_women"]["value"], 38)
        self.assertEqual(metrics["hf_frauen_in_support"]["value"], 41)
        note = metrics["hf_frauen_in_support"]["note"]
        self.assertIn("not yet housed", note)
        self.assertIn("PDF-S. 30, Abschnitt 4.1", note)
        self.assertIn("zwei weitere Mietverträge", note)


class HospitalPlanTests(_Offline, unittest.TestCase):
    def test_hamburg_and_niedersachsen_parsers(self):
        from ingest.domains import institutions_media_hospital_plans as hp
        from ingest.domains.institutions_media_rechnungshof import quote_in_text

        page_820 = (
            "Fachgebiet: 820 Psychiatrie- und Psychotherapie\n"
            "01     Universitätsklinikum Hamburg-Eppendorf                                         200                200                200                  200               200\n"
            "07     Asklepios Klinik Nord                                                          705                705                705                  705               705\n"
            "Insgesamt vollstationär                                                             1.601              1.601              1.601                1.601             1.601\n"
            "Teilstationäre Behandlungsplätze\n"
            "07     Asklepios Klinik Nord                                                          308                308                308                  308               308\n"
            "Insgesamt teilstationär                                                               823                823                823                  823               823\n"
        )
        hh = "\f" + page_820
        figs = hp.hamburg_figures(hh)
        totals = {(f["metric"], f["value"]) for f in figs if f["is_total"]}
        self.assertEqual(totals, {("khplan_psych_beds", 1601), ("khplan_psych_day_places", 823)})
        nord = [f for f in figs if f.get("hospital_name") == "Asklepios Klinik Nord"]
        self.assertEqual({(f["metric"], f["value"]) for f in nord}, {("khplan_psych_beds", 705), ("khplan_psych_day_places", 308)})
        for rec in figs:
            self.assertTrue(quote_in_text(rec["quote"], hh))
            self.assertGreaterEqual(len(rec["quote"]), 8)

        ni_line = (
            "               Summe Niedersachsen (nur betriebene Kapaziäten)                      "
            "258   7.406       1.990   1.063    927    730     333       564 12.915      104    "
            "1.375    191   641    2.420    51   1.956   215   184       1.150   32.483   731    "
            "5.370   973    7.074   39.557    72      175         4   72    30      401 1.600   222   2.576"
        )
        ni_figs = hp.parse_niedersachsen_land_total(ni_line)
        by = {f["metric"]: f["value"] for f in ni_figs}
        self.assertEqual(by["khplan_kjp_beds"], 731)
        self.assertEqual(by["khplan_psych_beds"], 5370)
        self.assertEqual(by["khplan_psm_beds"], 973)
        self.assertEqual(by["khplan_kjp_day_places"], 401)
        self.assertEqual(by["khplan_psych_day_places"], 1600)
        self.assertEqual(by["khplan_psm_day_places"], 222)
        for rec in ni_figs:
            self.assertIn("Kapaziäten", rec["quote"])
            self.assertTrue(quote_in_text(rec["quote"], ni_line))

    def test_land_metrics_use_ags_and_quotes_must_match_archive(self):
        from ingest.domains import institutions_media_hospital_plans as hp

        conn = memory_db()
        notes = []
        conn.execute(
            "INSERT INTO source (id, url, domain, license) VALUES (1, ?, ?, ?)",
            ("https://example.invalid/hh", "institutions_media", "amtliches Werk, § 5 UrhG"),
        )
        document = "Insgesamt vollstationär                                                             1.601              1.601              1.601                1.601             1.601\n"
        rec = {
            "entity_type": "land",
            "entity_id": "HH",
            "metric": "khplan_psych_beds",
            "value": 1601,
            "unit": "beds",
            "year": 2026,
            "period": "2026-01-01",
            "quote": "Insgesamt vollstationär                                                             1.601              1.601              1.601                1.601             1.601",
            "locator": "PDF-S. 92, Anlage 4, Fachgebiet 820, vollstationäre Betten-Soll 01.01.2026",
            "note": hp.SERIES_HH,
        }
        self.assertTrue(hp.store_cited_metric(conn, rec, source_id=1, document_text=document, notes=notes))
        row = conn.execute("SELECT entity_type, entity_id, value FROM metric").fetchone()
        self.assertEqual(row["entity_type"], "land")
        self.assertEqual(row["entity_id"], "02")
        self.assertEqual(row["value"], 1601)
        letter = conn.execute(
            "SELECT COUNT(*) FROM metric WHERE entity_type='land' AND entity_id GLOB '[A-Z][A-Z]'"
        ).fetchone()[0]
        self.assertEqual(letter, 0)
        self.assertFalse(hp.store_cited_metric(
            conn, dict(rec, quote="this quote is not in the document"),
            source_id=1, document_text=document, notes=notes,
        ))

    def test_wikidata_link_only_when_unique(self):
        from ingest.common import name_norm
        from ingest.domains import institutions_media_hospital_plans as hp

        conn = memory_db()
        notes = []
        conn.execute(
            "INSERT INTO source (id, url, domain, license) VALUES (1, ?, ?, ?)",
            ("https://example.invalid/hh", "institutions_media", "amtliches Werk, § 5 UrhG"),
        )
        uke = "Universitätsklinikum Hamburg-Eppendorf"
        nord = "Asklepios Klinik Nord"
        other = "Asklepios Westklinikum Hamburg"
        for fid, name, qid in ((10, uke, "Q123"), (11, nord, "Q456"), (12, other, "Q789")):
            conn.execute(
                """
                INSERT INTO facility (id, name, name_norm, kind, land, is_protected, source_id)
                VALUES (?, ?, ?, 'psychiatric', 'HH', 0, 1)
                """,
                (fid, name, name_norm(name)),
            )
            conn.execute(
                "INSERT INTO institutions_media_facility (qid, facility_id, kind, source_id) VALUES (?, ?, 'psychiatric', 1)",
                (qid, fid),
            )
        document = (
            "01     Universitätsklinikum Hamburg-Eppendorf                                         200                200                200                  200               200\n"
        )
        self.assertEqual(hp.unique_psychiatric_facility(conn, uke, "HH"), (10, "Q123"))
        self.assertEqual(hp.unique_psychiatric_facility(conn, nord, "HH"), (11, "Q456"))
        self.assertIsNone(hp.unique_psychiatric_facility(conn, "Erfindungshospital", "HH"))
        self.assertIsNone(hp.unique_psychiatric_facility(conn, "Asklepios", "HH"))

        rec = {
            "entity_type": "facility",
            "entity_id": "Q123",
            "metric": "khplan_psych_beds",
            "value": 200,
            "unit": "beds",
            "year": 2026,
            "period": "2026-01-01",
            "quote": "01     Universitätsklinikum Hamburg-Eppendorf                                         200                200                200                  200               200",
            "locator": "PDF-S. 92",
            "note": hp.SERIES_HH,
        }
        self.assertTrue(hp.store_cited_metric(conn, rec, source_id=1, document_text=document, notes=notes))
        row = conn.execute(
            "SELECT entity_type, entity_id, value FROM metric WHERE metric='khplan_psych_beds'"
        ).fetchone()
        self.assertEqual((row["entity_type"], row["entity_id"], row["value"]), ("facility", "Q123", 200))



    def test_bw_berlin_brandenburg_land_totals_and_licences(self):
        from ingest.domains import institutions_media_hospital_plans as hp
        from ingest.domains.institutions_media_rechnungshof import quote_in_text

        bw = (
            "Aus diesem Be-\n"
            "darf werden landesweit 1.566 Betten und 517 Plätze festgelegt (insgesamt 2.083 Bet-\n"
            "ten/Plätze), was einem Anteil der teilstationären Versorgung i. H. v. 25 % entspricht.\n"
        )
        bw_figs = hp.baden_wuerttemberg_psm_land(bw)
        self.assertEqual({(f["metric"], f["value"], f["unit"]) for f in bw_figs}, {
            ("khplan_psm_beds", 1566, "beds"),
            ("khplan_psm_day_places", 517, "day_places"),
        })
        for rec in bw_figs:
            self.assertTrue(quote_in_text(rec["quote"], bw))
            self.assertEqual(rec["land"], "BW")
            self.assertEqual(rec["year"], 2025)
            self.assertTrue(rec["is_total"])

        be = (
            "Gemäß den Bevölkerungsprognosewerten für das Jahr 2025 ergibt sich für den Berliner\n"
            "Krankenhausplan 2020 ein prognostizierter gesamtstädtischer Bedarf in den Fächern Psychiatrie und\n"
            "Psychotherapie von 3.436, Psychosomatik und -psychotherapie von 547 sowie Kinder- und\n"
            "Jugendpsychiatrie und -psychotherapie von 601 Betten/Plätzen.\n"
            "Das sind insgesamt 4.584 Betten/Plätze.\n"
        )
        be_figs = hp.berlin_bedarf_2025(be)
        self.assertEqual({(f["metric"], f["value"], f["unit"]) for f in be_figs}, {
            ("khplan_psych_beds", 3436, "beds_or_places"),
            ("khplan_psm_beds", 547, "beds_or_places"),
            ("khplan_kjp_beds", 601, "beds_or_places"),
        })
        for rec in be_figs:
            self.assertTrue(quote_in_text(rec["quote"], be))
            self.assertEqual(rec["year"], 2025)

        bb = (
            "Kinder- und Jugendpsychiatrie\n"
            "und -psychotherapie                      233           245           255              0              10           10\n"
            "Psychiatrie und Psychotherapie         1.753         1.708         1.821              0          113          113\n"
            "Psychosomatische Medizin und\n"
            "Psychotherapie                             0           226           253              -2             29           27\n"
            "TK Kinder- und Jugendpsychi-\n"
            "atrie und -psychotherapie                114           126           202              0              76           76\n"
            "TK Psychiatrie und Psychothe-\n"
            "rapie                                     780            793            850              0            57             57\n"
            "TK Psychosomatische Medizin\n"
            "und Psychotherapie                          0            120            142              0            22             22\n"
        )
        bb_figs = hp.brandenburg_land_festlegungen(bb)
        self.assertEqual({(f["metric"], f["value"], f["unit"]) for f in bb_figs}, {
            ("khplan_kjp_beds", 255, "beds"),
            ("khplan_psych_beds", 1821, "beds"),
            ("khplan_psm_beds", 253, "beds"),
            ("khplan_kjp_day_places", 202, "day_places"),
            ("khplan_psych_day_places", 850, "day_places"),
            ("khplan_psm_day_places", 142, "day_places"),
        })
        def de_num(n):
            return f"{n:,}".replace(",", ".") if n >= 1000 else str(n)
        for rec in bb_figs:
            self.assertTrue(quote_in_text(rec["quote"], bb))
            self.assertEqual(rec["year"], 2021)
            self.assertIn(de_num(rec["value"]), rec["quote"])

        self.assertEqual(hp.SOURCES["bw_kh2026"]["license"], hp.RESERVED_LICENCE)
        self.assertEqual(hp.SOURCES["be_kh2020"]["license"], hp.RESERVED_LICENCE)
        self.assertIn("§ 5 Abs. 1 UrhG", hp.SOURCES["bb_kh4"]["license"])
        self.assertIn("Amtsblatt", hp.SOURCES["bb_kh4"]["license"])
        self.assertNotIn("§ 5 UrhG", hp.SOURCES["bw_kh2026"]["license"].replace("§ 51 UrhG", ""))
        self.assertNotIn("§ 5 UrhG", hp.SOURCES["be_kh2020"]["license"].replace("§ 51 UrhG", ""))
        self.assertEqual(hp.SOURCES["hh_kh2026"]["license"], hp.RESERVED_LICENCE)
        self.assertEqual(hp.SOURCES["ni_kh2024"]["license"], hp.RESERVED_LICENCE)

        # Land AGS mapping for the new totals
        conn = memory_db()
        notes = []
        conn.execute(
            "INSERT INTO source (id, url, domain, license) VALUES (1, ?, ?, ?)",
            ("https://example.invalid/bb", "institutions_media", hp.AMTSBLATT_LICENCE),
        )
        rec = dict(bb_figs[0])
        self.assertTrue(hp.store_cited_metric(conn, rec, source_id=1, document_text=bb, notes=notes))
        row = conn.execute("SELECT entity_type, entity_id, value, einheit FROM metric").fetchone()
        self.assertEqual((row["entity_type"], row["entity_id"]), ("land", "12"))
        self.assertEqual(row["value"], rec["value"])

        empty = hp.brandenburg_land_festlegungen("this document has no table")
        self.assertEqual(empty, [])

    def test_kreis_ags_accepted_for_khplan_metrics(self):
        from ingest.domains import institutions_media_hospital_plans as hp

        conn = memory_db()
        notes = []
        conn.execute(
            "INSERT INTO source (id, url, domain, license) VALUES (1, ?, ?, ?)",
            ("https://example.invalid/kreis", "institutions_media", "amtliches Werk, § 5 UrhG"),
        )
        document = "Beispielkrankenhaus 40 Planbetten"
        rec = {
            "entity_type": "kreis",
            "entity_id": "11000",
            "metric": "khplan_psych_beds",
            "value": 40,
            "unit": "beds",
            "year": 2021,
            "period": "2021",
            "quote": "Beispielkrankenhaus 40 Planbetten",
            "locator": "test",
            "note": "kreis test",
        }
        self.assertTrue(hp.store_cited_metric(conn, rec, source_id=1, document_text=document, notes=notes))
        row = conn.execute("SELECT entity_type, entity_id, value FROM metric").fetchone()
        self.assertEqual((row["entity_type"], row["entity_id"], row["value"]), ("kreis", "11000", 40))

    def test_ensure_hospital_org_sets_legal_form_and_origin_link(self):
        from ingest.domains import institutions_media_hospital_plans as hp

        conn = memory_db()
        conn.execute(
            "INSERT INTO source (id, url, domain, license) VALUES (1, ?, ?, ?)",
            ("https://example.invalid/org", "institutions_media", "amtliches Werk, § 5 UrhG"),
        )
        oid = hp.ensure_hospital_org(
            conn, "Beispiel Klinikum gGmbH", "BB", 1, legal_form="gGmbH",
        )
        self.assertIsNotNone(oid)
        org = conn.execute("SELECT name, legal_form_norm, land FROM org WHERE id=?", (oid,)).fetchone()
        self.assertEqual(org["legal_form_norm"], "ggmbh")
        self.assertEqual(org["land"], "BB")
        link = conn.execute(
            "SELECT method, confidence, flagged, record_kind FROM org_link WHERE org_id=?",
            (oid,),
        ).fetchone()
        self.assertEqual(link["method"], "origin")
        self.assertEqual(link["confidence"], 1.0)
        self.assertFalse(link["flagged"])
        self.assertEqual(link["record_kind"], "khplan_hospital")


    def test_brandenburg_per_hospital_psych_rows(self):
        from ingest.domains import institutions_media_hospital_plans as hp
        from ingest.domains.institutions_media_rechnungshof import quote_in_text

        ruppiner = (
            "Ruppiner Kliniken\n"
            "Krankenhaus der Schwerpunktversorgung\n"
            "                                                        Träger: Ruppiner Kliniken GmbH\n"
            "Fehrbelliner Straße 38                                          Fehrbelliner Straße 38\n"
            "16816 Neuruppin                                                 16816 Neuruppin\n"
            "                                                                Öffentlicher Träger\n"
            "Plan-Betten Stand 31. Juli 2021 gesamt (inkl. Tagesklinikplätze)                         836\n"
            "Plan-Betten – Vierter Krankenhausplan gesamt (inkl. Tagesklinikplätze)                   867\n"
            "Fachabteilung\n"
            "Kinder- und Jugendpsychiatrie und -psychotherapie                                         39 4)\n"
            "Psychiatrie und Psychotherapie                                                           138 5)\n"
            "Psychosomatische Medizin und Psychotherapie                                               18\n"
            "Tagesklinikplätze – Kinder- und Jugendpsychiatrie und -psychotherapie                     21\n"
            "Tagesklinikplätze – Psychiatrie und Psychotherapie                                        60\n"
            "   davon Standort Kyritz                                                                  19\n"
            "Tagesklinikplätze – Psychosomatische Medizin und Psychotherapie Standort Neuruppin        12\n"
        )
        treuen = (
            "Johanniter-Krankenhaus Treuenbrietzen\n"
            "Fachkrankenhaus\n"
            "                                                                    Träger: Johanniter GmbH\n"
            "Johanniterstraße 1                                                         Finckensteinallee 111\n"
            "14929 Treuenbrietzen                                                       12205 Berlin\n"
            "                                                                            Freigemeinnütziger Träger\n"
            "Plan-Betten – Vierter Krankenhausplan gesamt (inkl. Tagesklinikplätze)                                 391\n"
            "Fachabteilung\n"
            "Psychiatrie und Psychotherapie                                                                         46\n"
            "Psychosomatische Medizin und Psychotherapie                                                            18\n"
        )
        luebben = (
            "ASKLEPIOS Fachklinikum Lübben\n"
            "Fachkrankenhaus\n"
            "                                                                  Träger: ASKLEPIOS Fachkliniken Brandenburg GmbH\n"
            "Luckauer Straße 17                                                       Anton-Saefkow-Allee 2\n"
            "15907 Lübben                                                             14772 Brandenburg a. d. Havel\n"
            "                                                                          Privater Träger\n"
            "Plan-Betten – Vierter Krankenhausplan gesamt (inkl. Tagesklinikplätze)                                   344\n"
            "Fachabteilung\n"
            "Kinder- und Jugendpsychiatrie und -psychotherapie                                                        66\n"
            "Psychiatrie und Psychotherapie                                                                          109\n"
        )
        evb = (
            "Klinikum Ernst von Bergmann\n"
            "Krankenhaus der Schwerpunktversorgung\n"
            "Standort                                                        Träger: Klinikum Ernst von Bergmann gGmbH\n"
            "Charlottenstraße 72                                                     Charlottenstraße 72\n"
            "14467 Potsdam                                                           14467 Potsdam\n"
            "                                                                        Öffentlicher Träger\n"
            "Standort\n"
            "In der Aue 59 - 61\n"
            "14480 Potsdam\n"
            "Plan-Betten – Vierter Krankenhausplan gesamt                                 Charlottenstr.         In der Aue\n"
            "Fachabteilung\n"
            "Kinder- und Jugendpsychiatrie und -psychotherapie                 35              35                   -\n"
            "Psychiatrie und Psychotherapie                                   128                -               128\n"
            "Psychosomatische Medizin und Psychotherapie                       34              34                   -\n"
            "Tagesklinikplätze – Kinder- und Jugendpsychiatrie und\n"
            "Tagesklinikplätze – Psychiatrie und Psychotherapie Standort\n"
        )
        havelland = (
            "Havelland Kliniken\n"
            "Krankenhaus der Regelversorgung\n"
            "Havelland Kliniken                                               Träger: Havelland Kliniken GmbH\n"
            "Krankenhaus Kliniken\n"
            "Plan-Betten – Vierter Krankenhausplan gesamt\n"
            "Fachabteilung\n"
            "Psychiatrie und Psychotherapie                          70-                 70-                           -\n"
        )
        text = "\f".join([ruppiner, treuen, luebben, evb, havelland])
        figs = hp.parse_brandenburg_hospital_sheets(text)
        by_name = {}
        for rec in figs:
            by_name.setdefault(rec["hospital_name"], []).append(rec)
            self.assertTrue(quote_in_text(rec["quote"], text))
            self.assertIn(str(rec["value"]), rec["quote"])
            self.assertTrue(rec["create_org"])
            self.assertFalse(rec["is_total"])
            self.assertEqual(rec["year"], 2021)
            self.assertEqual(rec["source"], "bb_kh4")

        self.assertNotIn("Havelland Kliniken", by_name)

        rup = {r["metric"]: r for r in by_name["Ruppiner Kliniken"]}
        self.assertEqual(rup["khplan_kjp_beds"]["value"], 39)
        self.assertEqual(rup["khplan_psych_beds"]["value"], 138)
        self.assertEqual(rup["khplan_psm_beds"]["value"], 18)
        self.assertEqual(rup["khplan_kjp_day_places"]["value"], 21)
        self.assertEqual(rup["khplan_psych_day_places"]["value"], 60)
        self.assertEqual(rup["khplan_psm_day_places"]["value"], 12)
        self.assertEqual(rup["khplan_psych_beds"]["kreis_ags"], "12068")
        self.assertEqual(rup["khplan_psych_beds"]["ort"], "Neuruppin")
        self.assertEqual(rup["khplan_psych_beds"]["legal_form"], "GmbH")
        # site totals, not the 'davon Standort' split
        self.assertFalse(any("davon Standort" in r["quote"] for r in rup.values()))

        treu = {r["metric"]: r for r in by_name["Johanniter-Krankenhaus Treuenbrietzen"]}
        self.assertEqual(treu["khplan_psych_beds"]["value"], 46)
        self.assertEqual(treu["khplan_psych_beds"]["kreis_ags"], "12069")
        self.assertEqual(treu["khplan_psych_beds"]["ort"], "Treuenbrietzen")
        self.assertNotEqual(treu["khplan_psych_beds"]["ort"], "Berlin")

        lueb = {r["metric"]: r for r in by_name["ASKLEPIOS Fachklinikum Lübben"]}
        self.assertEqual(lueb["khplan_psych_beds"]["kreis_ags"], "12061")
        self.assertEqual(lueb["khplan_psych_beds"]["ort"], "Lübben")
        self.assertEqual(lueb["khplan_kjp_beds"]["value"], 66)
        self.assertEqual(lueb["khplan_psych_beds"]["legal_form"], "GmbH")

        ev = {r["metric"]: r for r in by_name["Klinikum Ernst von Bergmann"]}
        self.assertEqual(ev["khplan_kjp_beds"]["value"], 35)
        self.assertEqual(ev["khplan_psych_beds"]["value"], 128)
        self.assertEqual(ev["khplan_psm_beds"]["value"], 34)
        self.assertEqual(ev["khplan_psych_beds"]["kreis_ags"], "12054")
        self.assertNotIn("khplan_kjp_day_places", ev)
        self.assertNotIn("khplan_psych_day_places", ev)

        # Ingest: orgs + sidecar Kreis AGS, no colliding Kreis metrics
        conn = memory_db()
        notes = []
        hp.ensure_khplan_table(conn)
        conn.execute(
            "INSERT INTO source (id, url, domain, license) VALUES (1, ?, ?, ?)",
            ("https://example.invalid/bb-hosp", "institutions_media", hp.AMTSBLATT_LICENCE),
        )
        stored = 0
        org_ids = {}
        for rec in figs:
            official_key = (
                f"{rec['land']}-KH:{hp.name_norm(rec['hospital_name'])}:{rec['code']}:{rec['kind']}"
            )
            if rec["record_key"] not in org_ids:
                org_ids[rec["record_key"]] = hp.ensure_hospital_org(
                    conn, rec["hospital_name"], rec["land"], 1,
                    legal_form=rec.get("legal_form"),
                    record_key=rec["record_key"],
                )
            oid = org_ids[rec["record_key"]]
            from ingest.common import upsert
            upsert(conn, "institutions_media_khplan", {
                "official_key": official_key,
                "hospital_name": rec["hospital_name"],
                "land": rec["land"],
                "fachgebiet": rec["code"] + " " + hp.FACHGEBIET_LABEL[rec["code"]],
                "kind": rec["kind"],
                "year": rec["year"],
                "value": rec["value"],
                "einheit": rec["unit"],
                "facility_id": None,
                "qid": None,
                "linked": 0,
                "quote": rec["quote"],
                "locator": rec["locator"],
                "source_id": 1,
                "org_id": oid,
                "kreis_ags": rec.get("kreis_ags"),
            }, ["official_key"])
            stored += 1
        self.assertEqual(stored, len(figs))
        orgs = conn.execute("SELECT name, legal_form_norm, land FROM org ORDER BY name").fetchall()
        self.assertEqual(len(orgs), 4)
        rup_org = conn.execute(
            "SELECT id, legal_form_norm FROM org WHERE name=?", ("Ruppiner Kliniken",)
        ).fetchone()
        self.assertEqual(rup_org["legal_form_norm"], "gmbh")
        link = conn.execute(
            "SELECT method, confidence, flagged, record_kind FROM org_link "
            "WHERE org_id=? AND method='origin'",
            (rup_org["id"],),
        ).fetchone()
        self.assertEqual((link["method"], link["confidence"], link["flagged"], link["record_kind"]),
                         ("origin", 1.0, 0, "khplan_hospital"))
        # two hospitals must not collapse to one Kreis metric row
        self.assertEqual(conn.execute("SELECT COUNT(*) AS n FROM metric").fetchone()["n"], 0)
        lueb_row = conn.execute(
            "SELECT kreis_ags, org_id FROM institutions_media_khplan WHERE hospital_name LIKE '%Lübben%' LIMIT 1"
        ).fetchone()
        self.assertEqual(lueb_row["kreis_ags"], "12061")
        self.assertIsNotNone(lueb_row["org_id"])
        ev_org = conn.execute(
            "SELECT legal_form_norm FROM org WHERE name=?", ("Klinikum Ernst von Bergmann",)
        ).fetchone()
        self.assertEqual(ev_org["legal_form_norm"], "ggmbh")

    def test_load_document_fail_closed_on_robots(self):

        from unittest.mock import patch
        from ingest.domains import institutions_media_hospital_plans as hp

        with patch.object(hp, "khplan_robots_status", return_value=(False, "HTTP 403", None)):
            with self.assertRaises(hp.RobotsBlocked) as ctx:
                hp._load_document("bw_kh2026", force=False)
        self.assertIn("403", str(ctx.exception))
        self.assertIn("robots fail-closed", str(ctx.exception))


class ShelterCostTests(_Offline, unittest.TestCase):
    def test_catalog_quotes_are_not_bare_numbers_and_munich_is_monthly(self):
        from ingest.domains import institutions_media_shelter_costs as sc
        figs = sc.all_figures()
        self.assertGreaterEqual(len(figs), 40)
        for rec in figs:
            self.assertGreaterEqual(len(rec["quote"]), 8)
            self.assertTrue(
                rec["locator"].startswith("PDF-S.") or rec["locator"].startswith("HTML,"),
                rec["locator"],
            )
        munich = [r for r in figs if r["source"] == "mu_f01095"]
        self.assertTrue(all("eur_per_night" not in (r["unit"] or "") for r in munich if "entgelt" in r["metric"] or "erwerb" in r["metric"]))
        avg = next(r for r in munich if r["metric"] == "muenchen_bettplatzentgelt_avg_eur_per_month")
        self.assertEqual(avg["value"], 674)
        self.assertEqual(avg["unit"], "eur_per_month")
        self.assertIn("monthly", avg["note"].lower())
        hh = [r for r in figs if r["source"] == "hh_23_1321" and r["metric"] == "oeru_hotel_eur_per_day" and r["year"] == 2025]
        self.assertEqual(hh[0]["value"], 81)
        self.assertIn("örU", hh[0]["note"])
        self.assertNotIn("Kältehilfe", hh[0]["metric"])
        skf = next(r for r in figs if r["metric"] == "wnh_nu_tagessatz_skf_eur")
        self.assertEqual(skf["restricted"], 1)
        self.assertEqual(skf["value"], 61)
        two = [r for r in figs if "stadtmission" in r["metric"]]
        self.assertEqual({r["value"] for r in two}, {41, 50})

    def test_costs_use_ags_and_quotes_must_match_archive(self):
        from ingest.domains import institutions_media_shelter_costs as sc

        conn = memory_db()
        notes = []
        conn.execute(
            "INSERT INTO source (id, url, domain, license) VALUES (1, ?, ?, ?)",
            ("https://example.invalid/be", "institutions_media", "dl-de/by-2-0"),
        )
        rec = sc._with_geo(next(r for r in sc.berlin_figures() if r["metric"] == "kaeltehilfe_avg_eur_per_place_day"))
        document = rec["quote"] + "\n"
        self.assertTrue(sc.store_cited_metric(conn, rec, source_id=1, document_text=document, notes=notes))
        row = conn.execute("SELECT entity_type, entity_id, value, is_est FROM metric").fetchone()
        self.assertEqual((row["entity_type"], row["entity_id"]), ("land", "11"))
        self.assertEqual(row["value"], 31)
        self.assertEqual(row["is_est"], 1)
        mu = sc._with_geo(next(r for r in sc.munich_figures() if r["metric"] == "muenchen_bettplatzentgelt_avg_eur_per_month"))
        conn.execute(
            "INSERT INTO source (id, url, domain, license) VALUES (2, ?, ?, ?)",
            ("https://example.invalid/mu", "institutions_media", "amtliches Werk, § 5 UrhG"),
        )
        self.assertTrue(sc.store_cited_metric(conn, mu, source_id=2, document_text=mu["quote"] + "\n", notes=notes))
        mrow = conn.execute(
            "SELECT entity_type, entity_id, einheit FROM metric WHERE metric=?",
            ("muenchen_bettplatzentgelt_avg_eur_per_month",),
        ).fetchone()
        self.assertEqual((mrow["entity_type"], mrow["entity_id"], mrow["einheit"]), ("kreis", "09162", "eur_per_month"))
        letter = conn.execute(
            "SELECT COUNT(*) FROM metric WHERE entity_type='land' AND entity_id GLOB '[A-Z][A-Z]'"
        ).fetchone()[0]
        self.assertEqual(letter, 0)
        self.assertFalse(sc.store_cited_metric(
            conn, dict(rec, quote="this quote is not in the document"),
            source_id=1, document_text=document, notes=notes,
        ))

    def test_more_city_shelter_costs_use_kreis_ags_and_exact_units(self):
        from ingest.domains import institutions_media_shelter_costs as sc
        figs = [sc._with_geo(r) for r in sc.all_figures()]
        def one(metric, year):
            return next(r for r in figs if r["metric"] == metric and r["year"] == year)

        koeln = one("koeln_amsterdamer_str_eur_per_person_per_month", 2024)
        self.assertEqual((koeln["entity_type"], koeln["entity_id"]), ("kreis", "05315"))
        self.assertEqual(koeln["unit"], "eur_per_person_per_month")
        self.assertEqual(koeln["value"], 50)
        self.assertIn("50,00", koeln["quote"])
        self.assertIn("monatlich", koeln["quote"])

        k18 = one("koeln_amsterdamer_str_eur_per_person_per_month", 2018)
        self.assertEqual(k18["entity_id"], "05315")
        self.assertEqual(k18["value"], 50)

        hb_min = one("hb_nu_eur_per_person_per_night_min", 2017)
        hb_max = one("hb_nu_eur_per_person_per_night_max", 2017)
        self.assertEqual((hb_min["entity_type"], hb_min["entity_id"]), ("kreis", "04011"))
        self.assertEqual(hb_min["unit"], "eur_per_person_per_night")
        self.assertEqual(hb_min["value"], 51.01)
        self.assertEqual(hb_max["value"], 136.65)
        self.assertIn("51,01", hb_min["quote"])
        self.assertIn("136,65", hb_max["quote"])
        # Do not restate already-wired Bremen net costs or 2013 daily Entgelte.
        names = {r["metric"] for r in figs if r["geo"] == "HB"}
        self.assertTrue(names)
        self.assertTrue(all("net_cost" not in n and "2013" not in n for n in names))
        self.assertTrue(all(r["year"] == 2017 for r in figs if r["geo"] == "HB"))

        leipzig = one("leipzig_gemeinschaftsunterkunft_eur_per_person_per_night", 2025)
        self.assertEqual(leipzig["entity_id"], "14713")
        self.assertEqual(leipzig["unit"], "eur_per_person_per_night")
        self.assertEqual(leipzig["value"], 5)
        self.assertIn("5,00", leipzig["quote"])

        dd = one("dresden_uebergangswohnheim_eur_per_person_per_month", 2025)
        self.assertEqual(dd["entity_id"], "14612")
        self.assertEqual(dd["unit"], "eur_per_person_per_month")
        self.assertEqual(dd["value"], 1104.03)
        self.assertIn("1.104,03", dd["quote"])
        day = one("dresden_hoehere_gewalt_eur_per_person_per_day", 2025)
        self.assertEqual(day["unit"], "eur_per_person_per_day")
        self.assertEqual(day["value"], 20)

        st = one("stuttgart_wohnung_eur_per_m2_per_month", 2019)
        self.assertEqual(st["entity_id"], "08111")
        self.assertEqual(st["unit"], "eur_per_m2_per_month")
        self.assertEqual(st["value"], 15.23)

        dus = one("duesseldorf_obdach_standard_eur_per_m2_per_month", 2018)
        self.assertEqual(dus["entity_id"], "05111")
        self.assertEqual(dus["unit"], "eur_per_m2_per_month")
        self.assertTrue(dus["locator"].startswith("HTML,"))
        self.assertEqual(dus["value"], 6.25)

        ka = one("karlsruhe_einzelzimmer_eur_per_place_per_month", 2024)
        self.assertEqual(ka["entity_id"], "08212")
        self.assertEqual(ka["unit"], "eur_per_place_per_month")
        self.assertEqual(ka["value"], 500)
        ma = one("mannheim_notuebernachtung_eur_per_person_per_day", 2012)
        self.assertEqual(ma["entity_id"], "08222")
        self.assertEqual(ma["unit"], "eur_per_person_per_day")
        self.assertEqual(ma["value"], 21)

        for rec in figs:
            if rec["source"] in sc.SOURCES and rec["source"] not in {"be_s19_22334", "mu_f01095", "hh_23_1321"}:
                fmt = sc._fmt_value(rec["value"])
                folded_quote = rec["quote"].replace(".", "").replace(" ", "")
                self.assertTrue(
                    fmt in rec["quote"] or fmt.replace(",", ".") in rec["quote"]
                    or fmt.replace(",", "") in folded_quote
                    or (fmt == "1104,03" and "1.104,03" in rec["quote"])
                    or (fmt == "1000" and "1.000" in rec["quote"]),
                    f"{rec['metric']} quote must contain {fmt}: {rec['quote']}",
                )

    def test_new_shelter_cost_licences_and_fail_closed_robots(self):
        from ingest.domains import institutions_media_shelter_costs as sc
        self.assertIn("§ 5 Abs. 1 UrhG", sc.SOURCES["koeln_satzung_2024"]["license"])
        self.assertIn("§ 5 Abs. 1 UrhG", sc.SOURCES["koeln_satzung_2018"]["license"])
        self.assertIn("§ 5 Abs. 1 UrhG", sc.SOURCES["leipzig_5_08"]["license"])
        self.assertIn("§ 5 Abs. 1 UrhG", sc.SOURCES["dresden_unterbringung"]["license"])
        self.assertIn("§ 5 Abs. 1 UrhG", sc.SOURCES["stuttgart_4_12"]["license"])
        self.assertIn("§ 5 Abs. 1 UrhG", sc.SOURCES["duesseldorf_54101"]["license"])
        self.assertIn("§ 5 Abs. 1 UrhG", sc.SOURCES["karlsruhe_4_2"]["license"])
        self.assertIn("§ 5 Abs. 1 UrhG", sc.SOURCES["mannheim_5_03"]["license"])
        # Vorlage and Landtag paper are not statutes.
        self.assertNotIn("Amtliches Werk, § 5", sc.SOURCES["koeln_vorlage_2690"]["license"])
        self.assertIn("Rechte vorbehalten", sc.SOURCES["koeln_vorlage_2690"]["license"])
        self.assertNotIn("Amtliches Werk, § 5", sc.SOURCES["hb_19_894"]["license"])
        self.assertIn("Rechte vorbehalten", sc.SOURCES["hb_19_894"]["license"])
        self.assertEqual(
            sc.SOURCES["koeln_satzung_2024"]["license_url"],
            "https://www.stadt-koeln.de/service/kontakt/impressum",
        )
        # Fail-closed: a robots 403 skips the source instead of treating it as allowed.
        orig = sc.cost_robots_status
        sc.cost_robots_status = lambda url: (False, "robots.txt unreadable (HTTP 403)", None)
        try:
            # Do not open atlas.db; only exercise the loader decision.
            with self.assertRaises(sc.RobotsBlocked) as ctx:
                sc._load_document("koeln_satzung_2024", force=False)
            self.assertIn("fail-closed", str(ctx.exception))
            self.assertIn("403", str(ctx.exception))
        finally:
            sc.cost_robots_status = orig


class PrisonCostTests(_Offline, unittest.TestCase):
    def test_comparison_table_uses_ags_and_keeps_competing_series(self):
        from ingest.domains import institutions_media_prison_costs as pc
        from ingest.domains.institutions_media_rechnungshof import quote_in_text

        rows = pc.mv_comparison_figures()
        hamburg = [r for r in rows if r["entity_id"] == "HH"]
        self.assertEqual({r["year"] for r in hamburg}, {2022, 2023})
        self.assertEqual(next(r["value"] for r in hamburg if r["year"] == 2022), 215.49)
        th = [r for r in rows if r["entity_id"] == "TH"]
        self.assertEqual([r["year"] for r in th], [2023])
        de = [r for r in rows if r["entity_id"] == "DE"]
        self.assertTrue(all(r["entity_type"] == "de" for r in de))

        conn = memory_db()
        sources, notes = [], []
        # Use the comparison quote plus the Hamburg own-series quote in one document.
        document = (
            "    Hamburg                               215,49                           213,11\n"
            "    2022     215,67\n"
            "    2023     213,11\n"
        )
        self.assertTrue(quote_in_text("Hamburg 215,49 213,11", document))
        rec_cmp = next(r for r in hamburg if r["year"] == 2022)
        rec_own = next(r for r in pc.hamburg_figures() if r["year"] == 2022)
        sid = 1
        conn.execute(
            "INSERT INTO source (id, url, domain, license) VALUES (1, ?, ?, ?)",
            ("https://example.invalid/mv", "institutions_media", "amtliches Werk, § 5 UrhG"),
        )
        conn.execute(
            "INSERT INTO source (id, url, domain, license) VALUES (2, ?, ?, ?)",
            ("https://example.invalid/hh", "institutions_media", "amtliches Werk, § 5 UrhG"),
        )
        self.assertTrue(pc.store_cited_metric(conn, rec_cmp, source_id=1, document_text=document, notes=notes))
        self.assertTrue(pc.store_cited_metric(conn, rec_own, source_id=2, document_text=document, notes=notes))
        stored = conn.execute(
            "SELECT entity_type, entity_id, metric, year, value FROM metric ORDER BY metric, year"
        ).fetchall()
        self.assertEqual(len(stored), 2)
        by_metric = {row["metric"]: row for row in stored}
        self.assertEqual(by_metric["prison_thks_eur_per_day"]["entity_id"], "02")
        self.assertEqual(by_metric["prison_thks_eur_per_day"]["value"], 215.49)
        self.assertEqual(by_metric["prison_thks_own_eur_per_day"]["entity_id"], "02")
        self.assertEqual(by_metric["prison_thks_own_eur_per_day"]["value"], 215.67)
        letter = conn.execute(
            "SELECT COUNT(*) FROM metric WHERE entity_type='land' AND entity_id GLOB '[A-Z][A-Z]'"
        ).fetchone()[0]
        self.assertEqual(letter, 0)
        self.assertFalse(pc.store_cited_metric(
            conn, dict(rec_own, quote="this quote is not in the document"),
            source_id=2, document_text=document, notes=notes,
        ))

    def test_nrw_and_berlin_quotes_are_not_bare_numbers(self):
        from ingest.domains import institutions_media_prison_costs as pc
        for rec in pc.nrw_figures() + pc.berlin_figures() + pc.bayern_figures():
            self.assertTrue(rec["quote"])
            self.assertGreaterEqual(len(rec["quote"]), 8)
            self.assertTrue(rec["locator"].startswith("PDF-S."))




class LandUmbrellaTests(_Offline, unittest.TestCase):
    def test_lag_catalogue_has_licences_and_land_ags(self):
        from ingest.common import LAND_AGS
        from ingest.domains import institutions_media_lags as lags
        from ingest.domains.institutions_media_orgs import store_landscape_org

        names = [item["name"] for item in lags.CATALOG]
        self.assertEqual(len(names), len(set(names)))
        self.assertGreaterEqual(len(lags.CATALOG), 6)
        for item in lags.CATALOG:
            self.assertTrue(item["name"])
            self.assertIn(item["land"], LAND_AGS)
            self.assertEqual(lags.land_ags(item["land"]), LAND_AGS[item["land"]])
            self.assertTrue(item["source_url"].startswith("https://"))
            self.assertTrue(item["website"].startswith("https://"))
            self.assertTrue(item.get("license_url", "").startswith("https://"))
        self.assertTrue(lags.name_on_page(
            "Koordination Wohnungslosenhilfe Nordbayern",
            "Kontakt Koordination Wohnungslosenhilfe Nordbayern Pirckheimerstraße 6",
        ))
        self.assertFalse(lags.name_on_page("Koordination Wohnungslosenhilfe Nordbayern", "unrelated page"))
        # Party groups and unofficial sites are not in the official catalogue.
        blob = " ".join(names).casefold()
        self.assertNotIn("die linke", blob)
        self.assertNotIn("lag-gouwibw", " ".join(item["website"] for item in lags.CATALOG).casefold())

        conn = memory_db()
        sources = []
        item = next(i for i in lags.CATALOG if i["land"] == "BE")
        rec = {
            "name": item["name"],
            "land": item["land"],
            "role": "umbrella",
            "subtype": item["subtype"],
            "org_type": "nonprofit",
            "website": item["website"],
            "source_url": item["source_url"],
            "source_title": item["source_title"],
            "publisher": item["publisher"],
            "license": item.get("license") or "Rechte vorbehalten (Impressum zitiert); nur Fakten, Metadaten und Kurzzitate nach § 51 UrhG, Volltext nicht weiterverbreitet",
            "license_url": item["license_url"],
            "attribution": item["attribution"],
            "source_notes": item["source_notes"],
            "redistribute_fulltext": 0,
        }
        self.assertTrue(store_landscape_org(conn, rec, sources=sources))
        from ingest.common import name_norm
        org = conn.execute(
            "SELECT id, land, kreis_ags, webseite FROM org WHERE name_norm=? AND land=?",
            (name_norm(item["name"]), "BE"),
        ).fetchone()
        self.assertEqual(org["land"], "BE")
        self.assertIsNone(org["kreis_ags"])
        self.assertEqual(org["webseite"], item["website"])
        conn.execute(
            "UPDATE institutions_media_org SET land_ags=? WHERE org_id=?",
            (lags.land_ags("BE"), org["id"]),
        )
        side = conn.execute(
            "SELECT land, land_ags, kreis_ags, role FROM institutions_media_org WHERE org_id=?",
            (org["id"],),
        ).fetchone()
        self.assertEqual(side["land_ags"], "11")
        self.assertIsNone(side["kreis_ags"])
        self.assertEqual(side["role"], "umbrella")
        src = conn.execute("SELECT license FROM source WHERE url=?", (item["source_url"],)).fetchone()
        self.assertTrue(src["license"])
        self.assertNotIn("TODO", src["license"])
    def test_hamburg_young_adult_offers_are_district_level(self):
        from ingest.domains import institutions_media_shelters as sh
        from ingest.domains.institutions_media_rechnungshof import RESERVED_LICENCE
        self.assertTrue(sh.is_restricted_group_shelter("Junge Wohnhilfe"))
        self.assertTrue(sh.is_restricted_group_shelter(
            "Werkhaus Münzviertel (für Jungerwachsene 18-27 Jahre)"
        ))
        self.assertTrue(sh._LEAD_GROUP_RE.search("Junge Wohnhilfe"))
        conn = memory_db()
        sources = []
        for rec in (
            {
                "official_key": "HH-TEST:junge-wohnhilfe",
                "name": "Junge Wohnhilfe",
                "kind": "shelter",
                "address": "Güntherstraße 27, 22087 Hamburg",
                "plz": "22087",
                "city": "Hamburg",
                "land": "HH",
                "lat": 53.564272,
                "lon": 10.027563,
                "official_url": "https://geodienste.hamburg.de/HH_WFS_Uebernachtungsangebote",
                "source_url": "https://example.test/hh-opendata.json",
                "source_name": "hamburg_opendata",
                "license": RESERVED_LICENCE,
                "publisher": "Freie und Hansestadt Hamburg",
                "population_note": "Leistung gem. §§ 67 ff SGB XII mit vorübergehendem Wohnen",
            },
            {
                "official_key": "HH-TEST:werkhaus-muenzviertel",
                "name": "Werkhaus Münzviertel (für Jungerwachsene 18-27 Jahre)",
                "kind": "other",
                "address": "Rosenallee 11, 20097 Hamburg",
                "plz": "20097",
                "city": "Hamburg",
                "land": "HH",
                "lat": 53.549213,
                "lon": 10.014261,
                "official_url": "https://geodienste.hamburg.de/HH_WFS_Uebernachtungsangebote",
                "source_url": "https://example.test/hh-opendata.json",
                "source_name": "hamburg_opendata",
                "license": RESERVED_LICENCE,
                "publisher": "Freie und Hansestadt Hamburg",
                "population_note": "Tagesaufenthaltsstätte",
            },
        ):
            self.assertTrue(sh.store_official_facility(conn, rec, sources=sources))
            row = conn.execute(
                "SELECT anschrift, plz, lat, lon, zielgruppe FROM facility WHERE name=?",
                (rec["name"],),
            ).fetchone()
            self.assertIsNone(row["anschrift"])
            self.assertIsNone(row["plz"])
            self.assertIsNone(row["lat"])
            self.assertIsNone(row["lon"])
            self.assertIn("Ortsebene", row["zielgruppe"] or "")

    def test_shelter_cost_and_hospital_plan_licences(self):
        from ingest.domains.institutions_media_rechnungshof import RESERVED_LICENCE
        from ingest.domains import institutions_media_shelter_costs as sc
        from ingest.domains import institutions_media_hospital_plans as hp
        self.assertEqual(sc.SOURCES["mu_f01095"]["license"], RESERVED_LICENCE)
        self.assertEqual(
            sc.SOURCES["mu_f01095"]["license_url"],
            "https://stadt.muenchen.de/infos/impressum.html",
        )
        self.assertEqual(sc.SOURCES["hh_23_1321"]["license"], RESERVED_LICENCE)
        self.assertNotIn("§ 5 UrhG", sc.SOURCES["hh_23_1321"]["license"])
        self.assertEqual(
            sc.SOURCES["hh_23_1321"]["license_url"],
            "https://www.buergerschaft-hh.de/parldok/lizenz.html",
        )
        self.assertEqual(hp.SOURCES["hh_kh2026"]["license"], RESERVED_LICENCE)
        self.assertEqual(hp.SOURCES["ni_kh2024"]["license"], RESERVED_LICENCE)
        self.assertTrue(hp.SOURCES["hh_kh2026"]["license_url"].startswith("https://www.hamburg.de/"))
        self.assertTrue(hp.SOURCES["ni_kh2024"]["license_url"].startswith("https://www.ms.niedersachsen.de/"))
        for key in hp.ARCHIVE_KEYS:
            self.assertEqual(hp.SOURCES[key]["license"], RESERVED_LICENCE, key)
            self.assertNotIn("§ 5 Abs", hp.SOURCES[key]["license"], key)
        self.assertEqual(mod.ELVIS_LICENCE, RESERVED_LICENCE)
        self.assertEqual(mod.BY_RSS_LICENCE, RESERVED_LICENCE)
        self.assertEqual(mod.SH_RSS_LICENCE, RESERVED_LICENCE)
        self.assertEqual(mod.HH_RSS_LICENCE, RESERVED_LICENCE)

    def test_landtag_feed_failures_count_as_errors(self):
        def boom(*args, **kwargs):
            raise RuntimeError("HTTP 503")
        notes, errors, sources = [], [], []
        conn = memory_db()
        orig = mod.fetch
        mod.fetch = boom
        try:
            stored = mod.ingest_official_rss(
                conn, {"skip_verify": True}, sources, notes,
                land="HH", parliament="Bürgerschaft", typ="parldok",
                url="https://example.test/index.rss", errors=errors,
            )
        finally:
            mod.fetch = orig
        self.assertEqual(stored, 0)
        self.assertEqual(len(errors), 1)
        self.assertIn("HH RSS parldok fetch failed", errors[0])
        self.assertIn(errors[0], notes[0])
        notes, errors = [], []
        orig = mod.fetch
        orig_pardok = mod.ingest_pardok
        orig_elvis = mod.ingest_elvis
        mod.fetch = boom
        mod.ingest_pardok = lambda *a, **k: 0
        mod.ingest_elvis = lambda *a, **k: 0
        try:
            counts = mod.ingest_landtag(conn, {"skip_verify": True}, sources, notes, errors=errors)
        finally:
            mod.fetch = orig
            mod.ingest_pardok = orig_pardok
            mod.ingest_elvis = orig_elvis
        self.assertEqual(sum(counts.values()), 0)
        self.assertGreaterEqual(len(errors), 3)  # BY feeds + HH + SH
        self.assertTrue(any(n.startswith("landtag_feed_errors=") and n != "landtag_feed_errors=0" for n in notes))




class ManualArchiveTests(unittest.TestCase):
    def setUp(self):
        import ingest.domains.institutions_media as _m
        import ingest.common as _c
        _m._OFFLINE[0] = True
        self._fetch = _c.fetch
        def blocked(*args, **kwargs):
            raise AssertionError(f"fetch must not be called during manual-archive ingest: {args[:1]} {kwargs}")
        _c.fetch = blocked
        self._common = _c

    def tearDown(self):
        import ingest.domains.institutions_media as _m
        self._common.fetch = self._fetch
        _m._OFFLINE[0] = False

    def _html(self, body: str) -> bytes:
        return (
            "<!doctype html><html><head><title>t</title>"
            "<script>secret()</script><style>.x{}</style></head><body>"
            + body +
            "</body></html>"
        ).encode("utf-8")

    def _write_archive(self, root: Path, files: dict[str, bytes], checksum=True):
        root.mkdir(parents=True, exist_ok=True)
        sums = []
        for name, data in files.items():
            (root / name).write_bytes(data)
            sums.append(f"{hashlib.sha256(data).hexdigest()}  {name}")
        if checksum:
            (root / "SHA256SUMS").write_text("\n".join(sums) + "\n", encoding="utf-8")

    def test_visible_html_skips_script_and_keeps_text(self):
        from ingest.domains.institutions_media_manual_archive import visible_html_text
        text = visible_html_text(self._html("<h1>Notschlafstellen</h1><p>Ostparkstr. 16</p>"))
        self.assertIn("Notschlafstellen", text)
        self.assertIn("Ostparkstr. 16", text)
        self.assertNotIn("secret()", text)

    def test_blocked_fetch_urls(self):
        from ingest.domains.institutions_media_manual_archive import is_blocked_fetch_url
        self.assertTrue(is_blocked_fetch_url(
            "https://sd.bremische-buergerschaft.de/sdnetrim/foo/Beschlussvorlage.pdf"
        ))
        self.assertTrue(is_blocked_fetch_url("https://www.stvv.frankfurt.de/download/M_71_2026.pdf"))
        self.assertFalse(is_blocked_fetch_url("https://www.service.bremen.de/dienstleistungen/x"))
        self.assertFalse(is_blocked_fetch_url("https://frankfurt.de/leistungen/Notschlafstellen"))

    def test_sha256_mismatch_raises(self):
        from ingest.domains.institutions_media_manual_archive import read_archived
        root = Path(tempfile.mkdtemp())
        self._write_archive(root, {"x.html": b"<html>ok</html>"})
        (root / "SHA256SUMS").write_text("0" * 64 + "  x.html\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            read_archived(root, "x.html")

    def test_missing_archive_is_noted(self):
        from ingest.domains.institutions_media_manual_archive import ingest_manual_archive
        conn = memory_db()
        notes, sources = [], []
        result = ingest_manual_archive(conn, {"manual_archive": "/tmp/atlas-im-missing-archive-dir"}, sources, notes)
        self.assertEqual(result["shelters"], 0)
        self.assertTrue(any("missing" in n.lower() for n in notes))

    def test_bremen_and_frankfurt_offers_from_fixture(self):
        from ingest.domains.institutions_media_manual_archive import ingest_manual_archive, FILES
        root = Path(tempfile.mkdtemp())
        bremen = self._html(
            "<h1>Notunterbringung nachfragen</h1>"
            "<p>Männer - Notunterkunft für Männer, Rembertiring 49, 28195 Bremen</p>"
            "<p>Frauen - Notunterkunft für Frauen, Abbentorstr. 5, 28195 Bremen</p>"
            "<p>Sleep Inn, Oberneulander Landstr. 19, 28355 Bremen</p>"
            "<p>La Campagne, Ahlringstr. 2 - 4, 28309 Bremen</p>"
        )
        ffm = self._html(
            "<h1>Notschlafstellen</h1>"
            "<p>Frankfurter Verein für soziale Heimstätten e. V.</p>"
            "<p>Übernachtungsstätte Ostpark, Ostparkstr. 16, 60385 Frankfurt am Main</p>"
            "<p>Aufnahme- und Übergangsheim Rudolfstraße, Rudolfstr. 18, 60327 Frankfurt am Main</p>"
            "<p>Sozialzentrum am Burghof, Am Burghof 43-45, 60437 Frankfurt am Main</p>"
            "<p>Diakonisches Werk</p>"
            "<p>Hannah-Wohnen für Frauen, Kurt-Schumacher-Sr. 30-32, 60313 Frankfurt am Main</p>"
            "<p>Weser 5 Diakoniezentrum, Weserstr. 5, 60329 Frankfurt am Main</p>"
            "<p>Integrative Drogenhilfe e. V. (idh)</p>"
            "<p>Eastside, Schielestraße 22-26, 60314 Frankfurt am Main</p>"
            "<p>Jugendberatung und Jugendhilfe e.V.</p>"
            "<p>Drogennotdienst, Elbestr. 38, 60329 Frankfurt am Main</p>"
            "<p>AIDS-Hilfe Frankfurt e. V.</p>"
            "<p>La Strada, Mainzer Landstr. 93, 60329 Frankfurt am Main</p>"
        )
        self._write_archive(root, {
            FILES["bremen_service"]: bremen,
            FILES["ffm_list"]: ffm,
        })
        conn = memory_db()
        notes, sources = [], []
        result = ingest_manual_archive(conn, {"manual_archive": str(root)}, sources, notes)
        self.assertEqual(result["shelters"], 12, notes)
        rows = conn.execute(
            "SELECT f.name, f.anschrift, f.plz, f.lat, f.lon, f.kreis_ags, f.zielgruppe, f.ort, f.land, s.official_url "
            "FROM facility f JOIN institutions_media_shelter s ON s.facility_id=f.id"
        ).fetchall()
        by_name = {r["name"]: r for r in rows}
        self.assertEqual(len(by_name), 12)
        self.assertEqual(by_name["Notunterkunft für Männer Rembertiring"]["anschrift"], "Rembertiring 49")
        self.assertEqual(by_name["Notunterkunft für Männer Rembertiring"]["kreis_ags"], "04011")
        women = by_name["Notunterkunft für Frauen Abbentorstraße"]
        self.assertIsNone(women["anschrift"])
        self.assertIsNone(women["plz"])
        self.assertIsNone(women["lat"])
        self.assertIsNone(women["lon"])
        self.assertIn("Ortsebene", women["zielgruppe"] or "")
        hannah = by_name["Hannah-Wohnen für Frauen"]
        self.assertIsNone(hannah["anschrift"])
        self.assertIsNone(hannah["plz"])
        self.assertEqual(hannah["kreis_ags"], "06412")
        self.assertEqual(hannah["ort"], "Frankfurt am Main")
        dnd = by_name["Drogennotdienst"]
        self.assertIsNone(dnd["anschrift"])
        self.assertIsNone(dnd["plz"])
        self.assertIn("Ortsebene", dnd["zielgruppe"] or "")
        for r in rows:
            self.assertTrue(r["official_url"])
        lic = conn.execute("SELECT license, redistribute_fulltext FROM source").fetchall()
        self.assertTrue(lic)
        for row in lic:
            self.assertTrue(row["license"])
            self.assertEqual(row["redistribute_fulltext"], 0)

    def test_live_archive_costs_and_restricted_offers(self):
        from ingest.domains.institutions_media_manual_archive import (
            ARCHIVE_DEFAULT, ingest_manual_archive, QUOTE_FFM_PLACES,
        )
        if not ARCHIVE_DEFAULT.is_dir():
            self.skipTest("Lead manual archive not present on this machine")
        conn = memory_db()
        notes, sources = [], []
        result = ingest_manual_archive(conn, {"manual_archive": str(ARCHIVE_DEFAULT)}, sources, notes)
        self.assertGreaterEqual(result["shelters"], 12, notes)
        self.assertGreaterEqual(result["metrics"], 10, notes)
        women = conn.execute(
            "SELECT anschrift, plz, lat, lon, zielgruppe FROM facility WHERE name=?",
            ("Notunterkunft für Frauen Abbentorstraße",),
        ).fetchone()
        self.assertIsNotNone(women)
        self.assertIsNone(women["anschrift"])
        hannah = conn.execute(
            "SELECT anschrift, plz FROM facility WHERE name=?",
            ("Hannah-Wohnen für Frauen",),
        ).fetchone()
        self.assertIsNotNone(hannah)
        self.assertIsNone(hannah["anschrift"])
        dnd = conn.execute(
            "SELECT anschrift, plz FROM facility WHERE name=?",
            ("Drogennotdienst",),
        ).fetchone()
        self.assertIsNotNone(dnd)
        self.assertIsNone(dnd["anschrift"])
        places = conn.execute(
            "SELECT value, quote, entity_id, entity_type FROM metric WHERE metric='ffm_notuebernachtung_places'"
        ).fetchone()
        self.assertEqual(places["value"], 630)
        self.assertEqual(places["entity_type"], "kreis")
        self.assertEqual(places["entity_id"], "06412")
        self.assertIn(QUOTE_FFM_PLACES, places["quote"])
        net = conn.execute(
            "SELECT year, value, entity_type, entity_id, einheit FROM metric WHERE metric='hb_nu_net_cost_eur' ORDER BY year"
        ).fetchall()
        self.assertEqual([(r["year"], r["value"], r["entity_type"], r["entity_id"], r["einheit"]) for r in net], [
            (2023, 4043506, "kreis", "04011", "eur_per_year"),
            (2024, 4465032, "kreis", "04011", "eur_per_year"),
        ])
        rund = conn.execute(
            "SELECT value, is_est, entity_type, entity_id FROM metric WHERE metric='hbhv_men_nu_cost_eur'"
        ).fetchone()
        self.assertEqual(rund["value"], 280000)
        self.assertEqual(rund["is_est"], 1)
        self.assertEqual(rund["entity_type"], "kreis")
        self.assertEqual(rund["entity_id"], "04012")
        daily = conn.execute(
            "SELECT metric, value, einheit FROM metric WHERE metric LIKE 'hb_nu_daily_entgelt_%' ORDER BY metric"
        ).fetchall()
        self.assertEqual(len(daily), 4)
        self.assertTrue(all(r["einheit"] == "eur_per_place_day" for r in daily))
        fees = conn.execute(
            "SELECT metric, value FROM metric WHERE metric LIKE 'ffm_fee_%' ORDER BY metric"
        ).fetchall()
        self.assertEqual({r["metric"]: r["value"] for r in fees}, {
            "ffm_fee_sonstige_1p_eur_per_month": 810,
            "ffm_fee_zwischen_1p_eur_per_month": 635,
        })
        blocked = conn.execute(
            "SELECT url FROM source WHERE url LIKE '%sd.bremische-buergerschaft.de%' "
            "OR url LIKE '%stvv.frankfurt.de/download%'"
        ).fetchall()
        self.assertTrue(blocked)
        for row in blocked:
            src = conn.execute(
                "SELECT sha256, bytes, local_path, license FROM source WHERE url=?",
                (row["url"],),
            ).fetchone()
            self.assertTrue(src["sha256"])
            self.assertTrue(src["bytes"])
            self.assertTrue(src["license"])
        self.assertTrue(any("were not fetched" in n for n in notes))


class PressMediaTests(_Offline, unittest.TestCase):
    def test_quote_from_unmodified_page_and_private_names(self):
        from ingest.domains import institutions_media_press as press
        page = (
            "<html><body><article><p>Zu den häufigsten Auslösern von Wohnungslosigkeit "
            "zählen Mietschulden.</p>"
            "<p>Frau Helga S. lebt seit einem Jahr ohne Wohnung.</p>"
            "<p>Senatorin Elke Voitl stellte die Berliner Kältehilfe vor.</p>"
            "</article></body></html>"
        )
        text = press.page_text(page.encode("utf-8"))
        self.assertIn("häufigsten Auslösern von Wohnungslosigkeit", text)
        quote = press.pick_quote(text)
        self.assertIsNotNone(quote)
        self.assertIn("Wohnungslosigkeit", quote)
        self.assertNotIn("Helga", quote)
        self.assertTrue(press.quote_in_page(quote, text))
        self.assertTrue(press.looks_private("Frau Helga S. lebt seit einem Jahr ohne Wohnung."))
        self.assertFalse(press.looks_private("Senatorin Elke Voitl stellte die Berliner Kältehilfe vor."))
        self.assertFalse(press.fields_name_ok("Obdachlos in Berlin", "Frau Helga S. sucht Hilfe."))

    def test_tdm_reservation_and_robots_are_recorded(self):
        from ingest.domains import counts_law as cl
        from ingest.domains import institutions_media_press as press
        cl._ROBOTS.clear()
        cl._ROBOTS["https://reserved.example"] = ([], None)
        cl._ROBOTS["https://blocked.example"] = ([(False, "/")], None)
        cl._ROBOTS["https://ok.example"] = ([], None)
        pages = {
            "https://reserved.example/.well-known/tdmrep.json": b'[{"tdm-reservation": 1}]',
            "https://blocked.example/.well-known/tdmrep.json": b"not json",
            "https://ok.example/.well-known/tdmrep.json": b"not json",
        }
        def fake(url, force=False):
            if url in pages:
                return pages[url]
            raise RuntimeError(f"unexpected {url}")
        notes = []
        gate = press.HostGate(lambda url: fake(url), notes)
        gate._sleep = lambda _delay: None
        ok, reason = gate.allow("https://reserved.example/pm/wohnungslos.html")
        self.assertFalse(ok)
        self.assertIn("tdmrep", reason.lower())
        ok, reason = gate.allow("https://blocked.example/pm/wohnungslos.html")
        self.assertFalse(ok)
        self.assertIn("robots.txt disallows", reason)
        ok, reason = gate.allow("https://ok.example/pm/wohnungslos.html")
        self.assertTrue(ok)
        cl._ROBOTS.clear()

    def test_robots_fail_closed_on_403_and_404_means_no_rules(self):
        from ingest.domains import counts_law as cl
        from ingest.domains import institutions_media_press as press
        cl._ROBOTS.clear()
        cl._ROBOTS["https://www.saarland.de"] = "robots.txt unreadable (HTTP 403)"
        cl._ROBOTS["https://ok404.example"] = ([], None)
        ok, reason, delay = press.press_robots_status("https://www.saarland.de/stat/DE/aktuelles")
        self.assertFalse(ok)
        self.assertIn("403", reason)
        self.assertIsNone(delay)
        notes = []
        gate = press.HostGate(lambda url: (_ for _ in ()).throw(RuntimeError(url)), notes)
        gate._sleep = lambda _delay: None
        ok, reason = gate.allow("https://www.saarland.de/stat/DE/aktuelles")
        self.assertFalse(ok)
        self.assertIn("403", reason)
        ok, reason = gate.allow("https://www.saarland.de/other")
        self.assertFalse(ok)
        ok, reason, delay = press.press_robots_status("https://ok404.example/presse/index.html")
        self.assertTrue(ok, reason)
        cl._ROBOTS.clear()

    def test_store_article_licence_ags_and_dedupe(self):
        from ingest.domains import institutions_media_press as press
        conn = memory_db()
        sources = []
        rec = {
            "url": "https://stadt.muenchen.de/presse/kaeltehilfe-2026.html",
            "title": "Kältehilfe in München startet",
            "publisher": "Landeshauptstadt München",
            "published": "2026-11-01",
            "topic": "Kältehilfe",
            "license": press.FACTS_LICENCE,
            "license_url": "https://stadt.muenchen.de/infos/impressum.html",
            "land": "BY",
            "land_ags": "09",
            "kreis_ags": "09162",
            "ort": "München",
        }
        self.assertTrue(press.store_press_article(conn, rec, sources=sources))
        row = conn.execute("SELECT kind, land, land_ags, kreis_ags, ort, lizenz, zusammenfassung, source_id FROM media").fetchone()
        self.assertEqual(row["kind"], "article")
        self.assertEqual(row["land"], "BY")
        self.assertEqual(row["land_ags"], "09")
        self.assertEqual(row["kreis_ags"], "09162")
        self.assertEqual(row["ort"], "München")
        self.assertEqual(row["lizenz"], press.FACTS_LICENCE)
        self.assertEqual(row["zusammenfassung"], "Kältehilfe")
        self.assertNotIn("öffnet", row["zusammenfassung"] or "")
        src = conn.execute("SELECT url, license, redistribute_fulltext FROM source WHERE id=?", (row["source_id"],)).fetchone()
        self.assertEqual(src["url"], rec["license_url"])
        self.assertEqual(src["license"], press.FACTS_LICENCE)
        self.assertNotIn("TODO", src["license"])
        self.assertEqual(src["redistribute_fulltext"], 0)
        rec2 = dict(rec)
        rec2["url"] = "https://stadt.muenchen.de/presse/notunterkunft-2026.html"
        rec2["title"] = "Notunterkunft in München erweitert"
        rec2["topic"] = "Notunterkunft"
        self.assertTrue(press.store_press_article(conn, rec2, sources=sources))
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM source").fetchone()[0], 1)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM media WHERE kind='article'").fetchone()[0], 2)
        self.assertFalse(mod.store_media(conn, {
            "title": rec["title"], "url": rec["url"] + "/file", "kind": "article",
            "license": press.FACTS_LICENCE,
        }, sources))
        seen = press.existing_media_urls(conn)
        self.assertIn(rec["url"], seen)
        nat = dict(rec)
        nat["url"] = "https://www.destatis.de/DE/Presse/Pressemitteilungen/2026/11/PD26_wohnungslose.html"
        nat["title"] = "Zahl der wohnungslosen Menschen"
        nat["publisher"] = "Statistisches Bundesamt (Destatis)"
        nat["topic"] = "Wohnungslosigkeit"
        nat["license_url"] = "https://www.destatis.de/DE/Service/Impressum/_inhalt.html"
        nat["land"] = "DE"
        nat["land_ags"] = "09"
        nat["kreis_ags"] = "09162"
        nat["ort"] = "München"
        self.assertTrue(press.store_press_article(conn, nat, sources=sources))
        nrow = conn.execute("SELECT land, land_ags, kreis_ags, ort FROM media WHERE url=?", (nat["url"],)).fetchone()
        self.assertEqual(nrow["land"], "DE")
        self.assertIsNone(nrow["land_ags"])
        self.assertIsNone(nrow["kreis_ags"])
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM source").fetchone()[0], 2)

    def test_offline_ingest_and_press_only_flag(self):
        from ingest.domains import institutions_media_press as press
        conn = memory_db()
        sources, notes = [], []
        html = (
            "<html><head><title>Destatis: Wohnungslosigkeit 2025</title></head>"
            "<body><p>Im Jahr 2025 waren nach Destatis weniger Menschen von "
            "Wohnungslosigkeit betroffen als im Vorjahr.</p></body></html>"
        )
        stored = press.ingest_press(conn, {
            "press_pages": [{
                "url": "https://www.destatis.de/DE/Presse/Pressemitteilungen/2026/11/PD26_wohn.html",
                "raw": html,
                "publisher": "Statistisches Bundesamt (Destatis)",
                "published": "2026-11-10",
                "license_url": "https://www.destatis.de/DE/Service/Impressum/_inhalt.html",
                "land": "DE",
            }],
        }, sources, notes)
        self.assertEqual(stored, 1)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM media WHERE kind='article'").fetchone()[0], 1)
        row = conn.execute("SELECT zusammenfassung, title FROM media").fetchone()
        self.assertEqual(row["zusammenfassung"], "Wohnungslosigkeit")
        self.assertNotIn("betroffen", row["zusammenfassung"])
        self.assertIn("press", mod._DRY_ONLY)
        self.assertEqual(mod.main(["--press-only"]), 2)
        self.assertEqual(mod.main(["--dry-run", "--press-only", "--nope"]), 2)
        self.assertIn("media", mod._DRY_ONLY["press"])
        self.assertNotIn("press", mod._DRY_ONLY["press"])
        self.assertIn("press", mod._DRY_ONLY["lags"])


    def test_assign_geo_only_when_clearly_local(self):
        from ingest.domains import institutions_media_press as press
        city_feed = {"land": "BE", "kreis_ags": "11000", "ort": "Berlin", "publisher": "Berlin"}
        geo = press.assign_geo(city_feed, "Kältehilfe startet", "Die Kältehilfe öffnet Notunterkünfte.")
        self.assertEqual(geo["kreis_ags"], "11000")
        self.assertEqual(geo["land_ags"], "11")
        national = {"publisher": "tagesschau / ARD-aktuell", "land": "DE"}
        geo = press.assign_geo(
            national,
            "Zahl der Wohnungslosen in Deutschland gestiegen",
            "In Deutschland ist die Zahl der wohnungslosen Menschen erneut gestiegen. Auch in Berlin und München.",
        )
        self.assertEqual(geo["land"], "DE")
        self.assertIsNone(geo["land_ags"])
        self.assertIsNone(geo["kreis_ags"])
        geo = press.assign_geo(
            national,
            "Kältehilfe in München",
            "Die städtische Kältehilfe in München öffnet weitere Plätze.",
        )
        self.assertEqual(geo["land"], "BY")
        self.assertEqual(geo["kreis_ags"], "09162")


    def test_second_slice_feeds_and_repaired_rss_urls(self):
        from ingest.domains import institutions_media_press as press
        ids = {f["id"] for f in press.FEEDS}
        for fid in (
            "statistik-hb-rss", "statistik-sl-rss", "statistik-rlp-rss",
            "statistik-he-presse", "statistik-mv-presse", "bremen-senat-presse",
        ):
            self.assertIn(fid, ids)
        br = next(f for f in press.FEEDS if f["id"] == "br-rss")
        self.assertTrue(br["url"].endswith("nachrichten-bayerischer-rundfunk100~newsRss.xml"))
        self.assertEqual(br["license_url"], "https://www.br.de/unternehmen/service/impressum/index.html")
        rbb = next(f for f in press.FEEDS if f["id"] == "rbb-rss")
        self.assertEqual(rbb["url"], "https://www.rbb24.de/index.xml/feed=rss.xml")
        # Official RSS bytes parse into items (no network).
        sample = (
            "<?xml version=\"1.0\"?><rss version=\"2.0\"><channel>"
            "<item><title>Wohnungslosigkeit in Bremen</title>"
            "<link>https://www.statistik.bremen.de/presse/beispiel</link>"
            "</item></channel></rss>"
        ).encode("utf-8")
        items = press.parse_feed_items(sample)
        self.assertEqual(len(items), 1)
        self.assertIn("Wohnungslosigkeit", items[0]["title"])
        self.assertTrue(items[0]["url"].startswith("http"))


    def test_press_module_refuses_direct_run(self):
        db = ROOT / "data" / "atlas.db"
        before = (db.stat().st_mtime_ns, db.stat().st_size) if db.exists() else None
        proc = subprocess.run(
            [sys.executable, "-m", "ingest.domains.institutions_media_press"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 2)
        after = (db.stat().st_mtime_ns, db.stat().st_size) if db.exists() else None
        self.assertEqual(before, after)

    def test_has_topic_accepts_url_stems_and_wohnungsnot_with_obdach(self):
        from ingest.domains import institutions_media_press as press
        self.assertTrue(press.has_topic(
            "https://www.br.de/nachrichten/bayern/kaeltehilfe-in-muenchen,abc"
        ))
        self.assertTrue(press.has_topic("https://example.de/housingfirst-projekt-100.html"))
        self.assertTrue(press.has_topic("Wohnungsnot und Obdach in Berlin"))
        self.assertFalse(press.has_topic("Die Wohnungsnot auf dem Markt spitzt sich zu"))
        self.assertTrue(press.has_topic("/notunterkuenfte-oeffnen.html"))
        self.assertEqual(press.topic_tag("Kältehilfe in München startet"), "Kältehilfe")
        self.assertEqual(press.topic_tag("https://www.br.de/nachrichten/bayern/kaeltehilfe-in-muenchen,abc"), "Kältehilfe")

    def test_parse_sitemap_urlset_index_gzip_and_topic_filter(self):
        import gzip
        from ingest.domains import institutions_media_press as press
        urlset = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
            'xmlns:news="http://www.google.com/schemas/sitemap-news/0.9">'
            "<url><loc>https://www.ndr.de/nachrichten/hamburg/kaeltehilfe-startet-100.html</loc>"
            "<lastmod>2026-11-01T10:00:00+01:00</lastmod>"
            "<news:news><news:title>Kältehilfe startet</news:title>"
            "<news:publication_date>2026-11-01T10:00:00+01:00</news:publication_date>"
            "</news:news></url>"
            "<url><loc>https://www.ndr.de/nachrichten/hamburg/hafenfest-100.html</loc>"
            "<news:news><news:title>Hafenfest</news:title></news:news></url>"
            "<url><loc>https://www.destatis.de/EN/Press/2026/11/PE26_wohnungslos.html</loc>"
            "</url></urlset>"
        ).encode("utf-8")
        parsed = press.parse_sitemap(urlset)
        self.assertEqual(parsed["kind"], "urlset")
        self.assertEqual(len(parsed["entries"]), 3)
        hits = [e for e in parsed["entries"] if press.sitemap_on_topic(e)]
        self.assertEqual(len(hits), 1)
        self.assertIn("kaeltehilfe", hits[0]["url"])
        self.assertEqual(hits[0]["published"], "2026-11-01")
        self.assertEqual(press.parse_sitemap(gzip.compress(urlset))["kind"], "urlset")
        index = (
            '<?xml version="1.0"?><sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            "<sitemap><loc>https://www.ndr.de/sitemap/sitemap-ndr-info-100~sitemap_p-0.xml</loc></sitemap>"
            "<sitemap><loc>https://www.ndr.de/sitemap/sitemap-ndr-kultur-100~sitemap_p-0.xml</loc></sitemap>"
            "</sitemapindex>"
        ).encode("utf-8")
        idx = press.parse_sitemap(index)
        self.assertEqual(idx["kind"], "index")
        chosen = press.select_child_sitemaps(
            idx["entries"], {"max_sitemaps": 10, "child_must": r"sitemap-ndr-info"}
        )
        self.assertEqual(len(chosen), 1)
        self.assertIn("ndr-info", chosen[0]["url"])
        notes = []
        pages = {
            "https://www.example.de/index.xml": index,
            "https://www.ndr.de/sitemap/sitemap-ndr-info-100~sitemap_p-0.xml": urlset,
        }
        items = press.discover_from_sitemap(
            {
                "id": "ex",
                "url": "https://www.example.de/index.xml",
                "child_must": r"sitemap-ndr-info",
                "max_sitemaps": 5,
            },
            fetch_url=lambda u: pages[u],
            notes=notes,
        )
        self.assertEqual(len(items), 1)
        self.assertIn("kaeltehilfe", items[0]["url"])

    def test_robots_allow_wildcards_crawl_delay_and_tdmrep_cached(self):
        from ingest.domains import institutions_media_press as press
        destatis = (
            "User-agent: *\n"
            "Disallow: /SiteGlobals/\n"
            "Allow: /SiteGlobals/Forms/Suche/*_Formular.*\n"
            "Allow: /SiteGlobals/Functions/RSSFeed/DE/\n"
            "Crawl-delay: 30\n"
        )
        form = (
            "https://www.destatis.de/SiteGlobals/Forms/Suche/Presse/DE/"
            "Pressesuche_Formular.html?templateQueryString=Wohnungslosigkeit"
        )
        form_2 = (
            "https://www.destatis.de/SiteGlobals/Forms/Suche/Presse/DE/"
            "Pressesuche_Formular_2.html?templateQueryString=Wohnungslosigkeit"
        )
        rss = "https://www.destatis.de/SiteGlobals/Functions/RSSFeed/DE/RSSNewsfeed/Aktuell.xml"
        blocked = "https://www.destatis.de/SiteGlobals/foo"
        self.assertTrue(press.robots_path_allowed(destatis, form, "germany-atlas/1.0"))
        self.assertTrue(press.robots_path_allowed(destatis, rss, "germany-atlas/1.0"))
        self.assertFalse(press.robots_path_allowed(destatis, blocked, "germany-atlas/1.0"))
        # Literal robots pattern requires "_Formular." ; Formular_2.html does not match.
        self.assertFalse(press.robots_path_allowed(destatis, form_2, "germany-atlas/1.0"))
        from ingest.domains import counts_law as cl
        from ingest.domains.counts_law import _robots_parse
        cl._ROBOTS.clear()
        cl._ROBOTS["https://www.destatis.de"] = _robots_parse(destatis)
        pages = {"https://www.destatis.de/.well-known/tdmrep.json": b"not json"}
        calls = []

        def fake(url, force=False):
            calls.append(url)
            if url in pages:
                return pages[url]
            raise RuntimeError(f"unexpected {url}")

        notes = []
        gate = press.HostGate(lambda url: fake(url), notes)
        gate._sleep = lambda _delay: None
        ok, reason = gate.allow(rss)
        self.assertTrue(ok, reason)
        self.assertEqual(gate._crawl_delay.get("www.destatis.de"), 30.0)
        ok, reason = gate.allow(blocked)
        self.assertFalse(ok)
        self.assertIn("robots.txt disallows", reason)
        tdm_calls = [u for u in calls if u.endswith("tdmrep.json")]
        self.assertEqual(len(tdm_calls), 1)
        cl._ROBOTS.clear()

    def test_archive_sitemap_feed_ids(self):
        from ingest.domains import institutions_media_press as press
        ids = {f["id"] for f in press.FEEDS}
        for fid in (
            "tagesschau-sitemap", "br-article-archive", "ndr-sitemap",
            "wdr-sitemap", "mdr-sitemap", "hr-sitemap",
            "dlf-gesellschaft-sitemap", "dlf-politik-sitemap",
            "dlf-nachrichten-sitemap", "bt-sitemap", "destatis-pm-sitemap",
        ):
            self.assertIn(fid, ids)
        br = next(f for f in press.FEEDS if f["id"] == "br-article-archive")
        self.assertEqual(br["kind"], "sitemap")
        self.assertTrue(br["url"].endswith("article-archive.xml"))
        ts = next(f for f in press.FEEDS if f["id"] == "tagesschau-search")
        self.assertGreaterEqual(int(ts.get("max_search_requests") or 0), 18)
        self.assertGreaterEqual(int(ts.get("max_items") or 0), 80)

    def test_regional_local_sitemaps_and_loc_must(self):
        from ingest.domains import institutions_media_press as press
        from ingest.domains.institutions_media_rechnungshof import quote_in_text  # noqa: F401

        ids = {f["id"] for f in press.REGIONAL_LOCAL_FEEDS}
        expected = {
            "ndr-hamburg-sitemap", "br-muenchen-sitemap", "wdr-koeln-sitemap",
            "wdr-ruhr-sitemap", "hr-frankfurt-sitemap", "mdr-sachsen-sitemap",
            "swr-bw-sitemap", "dortmund-newsroom-sitemap",
            "stuttgart-presse-sitemap", "duesseldorf-news-sitemap",
        }
        self.assertEqual(ids, expected)
        for feed in press.REGIONAL_LOCAL_FEEDS:
            self.assertIn(feed["kind"], {"sitemap", "sitemap_index"})
            self.assertEqual(feed.get("license") or press.FACTS_LICENCE, press.FACTS_LICENCE)
            self.assertTrue(feed.get("license_url"))
            self.assertTrue(feed.get("source_url"))
            self.assertNotIn("§ 5", (feed.get("license") or press.FACTS_LICENCE))

        dortmund = next(f for f in press.REGIONAL_LOCAL_FEEDS if f["id"] == "dortmund-newsroom-sitemap")
        on = {"url": "https://www.dortmund.de/newsroom/presse-mitteilungen/stadt-dortmund-legt-einen-aktionsplan-gegen-obdachlosigkeit-vor.html"}
        off_service = {"url": "https://www.dortmund.de/themen/soziales/wohnungslosenhilfe/"}
        off_other = {"url": "https://www.dortmund.de/newsroom/nachrichten-dortmund.de/verkehrshinweise.html"}
        self.assertTrue(press.sitemap_entry_allowed(on, dortmund))
        self.assertFalse(press.sitemap_entry_allowed(off_service, dortmund))
        self.assertFalse(press.sitemap_entry_allowed(off_other, dortmund))

        ndr_hh = next(f for f in press.REGIONAL_LOCAL_FEEDS if f["id"] == "ndr-hamburg-sitemap")
        self.assertTrue(press.sitemap_entry_allowed(
            {"url": "https://www.ndr.de/nachrichten/hamburg/hilfe-fuer-obdachlose-in-hamburg,ham100.html"},
            ndr_hh,
        ))
        self.assertFalse(press.sitemap_entry_allowed(
            {"url": "https://www.ndr.de/nachrichten/niedersachsen/hilfe-fuer-obdachlose-in-hannover,nds100.html"},
            ndr_hh,
        ))

        mdr = next(f for f in press.REGIONAL_LOCAL_FEEDS if f["id"] == "mdr-sachsen-sitemap")
        self.assertTrue(press.sitemap_loc_allowed("https://www.mdr.de/nachrichten/sachsen/leipzig/jung-wohnungslos-leipzig,obdachlos-202.html", mdr))
        self.assertFalse(press.sitemap_loc_allowed("https://www.mdr.de/nachrichten/sachsen-anhalt/halle/obdachlos-100.html", mdr))

        geo = press.assign_geo(dortmund, "Aktionsplan gegen Obdachlosigkeit", None,
                               "https://www.dortmund.de/newsroom/presse-mitteilungen/aktionsplan.html")
        self.assertEqual(geo["kreis_ags"], "05913")
        self.assertEqual(geo["land"], "NW")
        koeln = next(f for f in press.REGIONAL_LOCAL_FEEDS if f["id"] == "wdr-koeln-sitemap")
        geo_k = press.assign_geo(
            koeln,
            "Köln: Obdachlose sorgen für Ärger in Fußgängerzonen",
            None,
            "https://www1.wdr.de/nrw/koeln/obdachlose-fussgaengerzone-koeln-aerger-handel-mieter-100.html",
        )
        self.assertEqual(geo_k["kreis_ags"], "05315")
        self.assertEqual(geo_k["land"], "NW")
        self.assertEqual(geo_k["ort"], "Köln")

        rows = [
            {"title": "Notschlafstelle bleibt in Betrieb", "url": "https://example.invalid/notschlafstelle"},
            {"title": "Aktionsplan gegen Obdachlosigkeit", "url": "https://example.invalid/obdachlosigkeit"},
            {"title": "Verkehrshinweise zum Weihnachtsmarkt", "url": "https://example.invalid/verkehr"},
        ]
        sample = press.sample_on_topic_rate(rows, k=25, seed=1)
        self.assertEqual(sample["checked"], 3)
        self.assertEqual(sample["on_topic"], 2)
        self.assertAlmostEqual(sample["rate"], 2 / 3)
        self.assertGreaterEqual(sample["rate"], 0.0)

    def test_regional_outlets_register_distinct_sources(self):
        from ingest.domains import institutions_media_press as press

        conn = memory_db()
        sources = []
        ndr = next(f for f in press.REGIONAL_LOCAL_FEEDS if f["id"] == "ndr-hamburg-sitemap")
        ruhr = next(f for f in press.REGIONAL_LOCAL_FEEDS if f["id"] == "wdr-ruhr-sitemap")
        koeln = next(f for f in press.REGIONAL_LOCAL_FEEDS if f["id"] == "wdr-koeln-sitemap")
        sid_hh = press.outlet_source_id(conn, ndr, sources)
        sid_ruhr = press.outlet_source_id(conn, ruhr, sources)
        sid_koeln = press.outlet_source_id(conn, koeln, sources)
        self.assertIsNotNone(sid_hh)
        self.assertNotEqual(sid_ruhr, sid_koeln)
        rows = conn.execute("SELECT url, title, redistribute_fulltext, license FROM source").fetchall()
        self.assertGreaterEqual(len(rows), 3)
        for row in rows:
            self.assertEqual(row["redistribute_fulltext"], 0)
            self.assertIn("Fakten", row["license"])
            self.assertNotIn("§ 5 UrhG", row["license"].replace("§ 51 UrhG", ""))

    def test_regional_desk_sitemaps_and_loc_must(self):
        from ingest.domains import institutions_media_press as press

        ids = {f["id"] for f in press.REGIONAL_DESK_FEEDS}
        expected = {
            "ndr-niedersachsen-sitemap", "ndr-sh-sitemap",
            "mdr-sachsen-anhalt-sitemap", "mdr-thueringen-sitemap",
            "swr-rp-sitemap", "sr-nachrichten-sitemap", "br-regional-sitemap",
        }
        self.assertEqual(ids, expected)
        for feed in press.REGIONAL_DESK_FEEDS:
            self.assertIn(feed["kind"], {"sitemap", "sitemap_index"})
            self.assertEqual(feed.get("license") or press.FACTS_LICENCE, press.FACTS_LICENCE)
            self.assertTrue(feed.get("license_url"))
            self.assertTrue(feed.get("source_url"))
            self.assertTrue(feed.get("loc_must"))
            self.assertNotIn("§ 5", (feed.get("license") or press.FACTS_LICENCE))

        nds = next(f for f in press.REGIONAL_DESK_FEEDS if f["id"] == "ndr-niedersachsen-sitemap")
        self.assertTrue(press.sitemap_entry_allowed(
            {"url": "https://www.ndr.de/nachrichten/niedersachsen/hilfe-fuer-obdachlose-in-hannover,nds100.html"},
            nds,
        ))
        self.assertFalse(press.sitemap_entry_allowed(
            {"url": "https://www.ndr.de/nachrichten/hamburg/hilfe-fuer-obdachlose-in-hamburg,ham100.html"},
            nds,
        ))
        self.assertFalse(press.sitemap_entry_allowed(
            {"url": "https://www.ndr.de/nachrichten/schleswig-holstein/kiel-kaeltehilfe,sh100.html"},
            nds,
        ))

        st = next(f for f in press.REGIONAL_DESK_FEEDS if f["id"] == "mdr-sachsen-anhalt-sitemap")
        self.assertTrue(press.sitemap_loc_allowed(
            "https://www.mdr.de/nachrichten/sachsen-anhalt/halle/obdachlos-100.html", st,
        ))
        self.assertFalse(press.sitemap_loc_allowed(
            "https://www.mdr.de/nachrichten/sachsen/leipzig/jung-wohnungslos-leipzig,obdachlos-202.html", st,
        ))

        sr = next(f for f in press.REGIONAL_DESK_FEEDS if f["id"] == "sr-nachrichten-sitemap")
        self.assertTrue(press.sitemap_loc_allowed(
            "https://www.sr.de/sr/home/nachrichten/politik_wirtschaft/obdachlosigkeit_saarbruecken_100.html", sr,
        ))
        self.assertFalse(press.sitemap_loc_allowed(
            "https://www.sr.de/sr/home/sport/saarland_hurricanes_100.html", sr,
        ))

        br = next(f for f in press.REGIONAL_DESK_FEEDS if f["id"] == "br-regional-sitemap")
        self.assertTrue(press.sitemap_loc_allowed(
            "https://www.br.de/nachrichten/bayern/obdachlose-in-nuernberg,xyz.html", br,
        ))
        self.assertFalse(press.sitemap_loc_allowed(
            "https://www.br.de/nachrichten/bayern/hitze-in-muenchen-obdachlose,abc.html", br,
        ))

        swr = next(f for f in press.REGIONAL_DESK_FEEDS if f["id"] == "swr-rp-sitemap")
        self.assertTrue(press.sitemap_loc_allowed(
            "https://www.swr.de/swraktuell/rheinland-pfalz/mainz/kaeltehilfe-obdachlose-100.html", swr,
        ))
        self.assertFalse(press.sitemap_loc_allowed(
            "https://www.swr.de/swraktuell/baden-wuerttemberg/stuttgart/kaeltehilfe-100.html", swr,
        ))

        geo = press.assign_geo(
            nds, "Obdachlose in Hannover brauchen Hilfe", None,
            "https://www.ndr.de/nachrichten/niedersachsen/hannover/obdachlose-hannover-100.html",
        )
        self.assertEqual(geo["kreis_ags"], "03241")
        self.assertEqual(geo["land"], "NI")
        self.assertEqual(geo["ort"], "Hannover")

        st = next(f for f in press.REGIONAL_DESK_FEEDS if f["id"] == "mdr-sachsen-anhalt-sitemap")
        geo_st = press.assign_geo(
            st,
            "Neuer Bus für Bedürftige in Halle",
            None,
            "https://www.mdr.de/nachrichten/sachsen-anhalt/halle/halle/kaeltebus-halle-armut-100.html",
        )
        self.assertEqual(geo_st["land"], "ST")
        self.assertEqual(geo_st["kreis_ags"], "15002")
        self.assertEqual(geo_st["ort"], "Halle (Saale)")
        geo_md = press.assign_geo(
            st,
            "Bahnhofsmission Magdeburg gibt Wohnungslosen Hilfe",
            None,
            "https://www.mdr.de/nachrichten/sachsen-anhalt/magdeburg/magdeburg/bahnhofsmission-wohnungslose-100.html",
        )
        self.assertEqual(geo_md["land"], "ST")
        self.assertEqual(geo_md["kreis_ags"], "15003")
        self.assertEqual(geo_md["ort"], "Magdeburg")
        sh = next(f for f in press.REGIONAL_DESK_FEEDS if f["id"] == "ndr-sh-sitemap")
        geo_essen_word = press.assign_geo(
            sh,
            "Corona: Warmes Essen für Obdachlose in Rendsburg",
            None,
            "https://www.ndr.de/nachrichten/schleswig-holstein/Corona-Warmes-Essen-fuer-Obdachlose,tafel530.html",
        )
        self.assertNotEqual(geo_essen_word.get("kreis_ags"), "05113")
        self.assertNotEqual(geo_essen_word.get("ort"), "Essen")
        self.assertEqual(geo_essen_word["land"], "SH")

    def test_regional_desk_outlets_register_distinct_sources(self):
        from ingest.domains import institutions_media_press as press

        conn = memory_db()
        sources = []
        nds = next(f for f in press.REGIONAL_DESK_FEEDS if f["id"] == "ndr-niedersachsen-sitemap")
        sh = next(f for f in press.REGIONAL_DESK_FEEDS if f["id"] == "ndr-sh-sitemap")
        mdr_st = next(f for f in press.REGIONAL_DESK_FEEDS if f["id"] == "mdr-sachsen-anhalt-sitemap")
        mdr_th = next(f for f in press.REGIONAL_DESK_FEEDS if f["id"] == "mdr-thueringen-sitemap")
        sid_nds = press.outlet_source_id(conn, nds, sources)
        sid_sh = press.outlet_source_id(conn, sh, sources)
        sid_st = press.outlet_source_id(conn, mdr_st, sources)
        sid_th = press.outlet_source_id(conn, mdr_th, sources)
        self.assertNotEqual(sid_nds, sid_sh)
        self.assertNotEqual(sid_st, sid_th)
        for row in conn.execute("SELECT redistribute_fulltext, license FROM source").fetchall():
            self.assertEqual(row["redistribute_fulltext"], 0)
            self.assertIn("Fakten", row["license"])
    def test_robots_read_before_sitemap_search_api_tdmrep_and_article(self):
        """Every press request path is robots-gated; a disallow means no request is made."""
        import urllib.request
        from ingest.domains import counts_law as cl
        from ingest.domains import institutions_media_press as press

        host = "https://press-gate.example"
        paths = {
            "sitemap": host + "/index~sitemap.xml",
            "search": host + "/suche?q=Wohnungslosigkeit",
            "api": host + "/api2u/search/?searchText=Wohnungslosigkeit",
            "tdmrep": host + "/.well-known/tdmrep.json",
            "article": host + "/artikel/kaeltehilfe.html",
        }

        class Resp:
            def __init__(self, url, body):
                self.url = url
                self.headers = {"Content-Type": "text/plain"}
                self._body = body

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def geturl(self):
                return self.url

            def read(self, n=-1):
                return self._body

        for kind, url in paths.items():
            cl._ROBOTS.clear()
            path = urllib.parse.urlparse(url).path
            robots_body = f"User-agent: *\nDisallow: {path}\n".encode()
            order = []
            orig_open = urllib.request.urlopen

            def fake_open(req, timeout=None):
                target = req.full_url if hasattr(req, "full_url") else req
                order.append(("robots", target))
                return Resp(target, robots_body)

            def fake_fetch(u, force=False):
                order.append(("get", u))
                return b"{}"

            notes = []
            gate = press.HostGate(fake_fetch, notes)
            gate._sleep = lambda _delay: None
            urllib.request.urlopen = fake_open
            try:
                if kind == "tdmrep":
                    gate.check_tdmrep(paths["article"])
                else:
                    try:
                        gate.fetch(url)
                    except press.RobotsRefused:
                        pass
                    else:
                        self.fail(f"{kind} was fetched despite robots disallow")
            finally:
                urllib.request.urlopen = orig_open
                cl._ROBOTS.clear()
            gets = [item for item in order if item[0] == "get"]
            self.assertEqual(gets, [], f"{kind} issued a request: {order}")
            self.assertTrue(order and order[0][0] == "robots", f"{kind} did not read robots first: {order}")
            self.assertTrue(str(order[0][1]).endswith("/robots.txt"), f"{kind} first request was {order[0]}")


if __name__ == "__main__":
    unittest.main()
