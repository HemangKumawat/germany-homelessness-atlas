"""Offline checks for hand-archived SH, Bremen and Saarland Krankenhauspläne."""
import hashlib
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ingest.common import ROOT as INGEST_ROOT
from ingest.domains import institutions_media as mod
from ingest.domains import institutions_media_hospital_plans as hp
from ingest.domains.institutions_media_rechnungshof import quote_in_text, RESERVED_LICENCE


def memory_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript((INGEST_ROOT / "ingest" / "schema.sql").read_text(encoding="utf-8"))
    mod.ensure_tables(conn)
    return conn


# Minimal excerpts (layout as in pdftotext -layout of the archived PDFs).
SH_TEXT = """\
Krankenhausplan 2017 des Landes Schleswig-Holstein
\f
Acht Kliniken betreiben an 12 Standorten psychiatrische Tageskliniken für Kinder und
Jugendliche mit 150 Plätzen (Stand 2015) und in der Regel jeweils einer psychiatrischen
Institutsambulanz.
\f
2015 wurden insgesamt 700 Plätze im teilstationären Setting ausgewiesen. Die Zahl der
Standorte für die teilstationäre psychiatrische Versorgung hat – unter Berücksichtigung der
noch in Bau befindlichen Tageskliniken - eine bedarfsgerechte Versorgungsdichte erreicht.
\f
Im Jahr 2015 standen für die stationäre Versorgung im Bereich Kinder- und
Jugendpsychiatrie und- psychotherapie 239 Planbetten zur Verfügung. Diese verteilten sich
auf fünf Abteilungen.

Aktuell stehen 244 Planbetten und 167 tagesklinische Plätze zur Verfügung.
\f
Im Jahr 2015 standen für die stationäre Versorgung im Bereich Psychiatrie und
Psychotherapie 1.962 Planbetten zur Verfügung. Diese verteilten sich auf 19 Abteilungen.

Aktuell stehen 1.981 Planbetten und 746 tagesklinische Plätze zur Verfügung.
\f
Im Jahr 2015 standen für die stationäre Versorgung im Bereich Psychotherapeutische
Medizin / Psychosomatik 448 Planbetten zur Verfügung. Diese verteilten sich auf 14
Abteilungen.

Aktuell stehen 450 Planbetten und 107 tagesklinische Plätze zur Verfügung.
"""

HB_LAND = """\
Tabelle 4: Entwicklung der voll- und teilstationären Behandlungskapazitäten im Zeitverlauf nach Fachgebiet, 2010-2022, Land Bremen (Fortsetzung)
                                                                                             Behandlungskapazitäten nach Fachgebiet - Land Bremen                                        Veränderung
   Fachgebiet
                                                   2010       2011        2012       2013       2014        2015       2016       2017        2018      2019    2020    2021    2022    abs.    in %
   Kinder- und Jugendpsychiatrie                     50         50          50         50          50         50         50         50             50     50      50      50      50       0      0,0%
   Psychiatrie und Psychotherapie                   555        588         588        578        583         573        572        594         591       581     571     563     563       8      1,4%
   Psychosomatik und Psychotherapie                  18         30          18         18          30         30         30         30             30     30      30      30      30      12     66,7%
   TK Kinder-/Jugendpsychiatrie                      18         38          38         38          43         43         43         43             43     43      43      43      43      25    138,9%
   TK Psychiatrie und Psychotherapie                174        180         180        200        200         214        219        235         235       242     252     268     268      94     54,0%
"""

HB_HOSP = """\
\f
""" + "x\n" * 20 + """
Tabelle 56: Entwicklung der Behandlungskapazitäten nach Fachgebiet im Zeitverlauf, AMEOS Krankenhausgesellschaft Bremen mbH: AMEOS Klinikum Bremen (Fortsetzung)
   Psychiatrie und Psychotherapie                179          206         206         196          196          196         195         201          201      201       201    201    201
   TK Psychiatrie und Psychotherapie                0           0           0          20           20           20          25          35           35       35       35     35     35
""" + "y\n" * 20 + """
Tabelle 60: Entwicklung der Behandlungskapazitäten nach Fachgebiet im Zeitverlauf, Gesundheit Nord gGmbH: Klinikum Bremen-Ost (Fortsetzung)
   Kinder- und Jugendpsychiatrie                     50          50          50           50          50           50          50             50         50       50     50     50     50
   Psychiatrie und Psychotherapie                   250         250         250          250         250          240         240          240          240       230    220    220    220
   Psychosomatik und Psychotherapie                  18          30          18           18          30           30          30             30         30       30     30     30     30
   TK Kinder-/Jugendpsychiatrie                       8          18          18           18          23           23          23             23         23       23     23     23     23
   TK Psychiatrie und Psychotherapie                126         126         126          126         126          136         136          136          136       143    153    153    153
"""

SL2018 = """\
Festlegung:
Planbetten 31.12.2017            55             Plätze 31.12.2017       60
Planbetten 31.12.2025            71             Plätze 31.12.2025       73
\f
Festlegung:
Planbetten 31.12.2017           643             Plätze 31.12.2017       248
Planbetten 31.12.2025           690             Plätze 31.12.2025       289
\f
Festlegung:
Planbetten 31.12.2017         86              Plätze 31.12.2017       10
Planbetten 31.12.2025         90              Plätze 31.12.2025       12
"""

SL2027 = """\
8.62.1 Bisherige Versorgungssituation
Im Jahr 2023 standen im Saarland insgesamt 73 Planbetten zur Verfügung. Die geringste
Bettenkapazität einer Einrichtung betrug dabei 30 Planbetten, während die höchste Betten-
kapazität 43 Planbetten umfasste. Darüber hinaus wurden im Saarland in der Fachabtei-
lung Kinder- und Jugendpsychiatrie und -psychotherapie 77 tagesklinische Behandlungs-
plätze vorgehalten.

Fachabteilung Kinder- und Jugendpsychiatrie und -psychotherapie
Krankenhausstandort                               Planbetten Planplätze                                           Bemerkungen

Marienhaus Klinikum Neunkirchen                          0             10                                         ab 01.01.2028
SHG-Kliniken Sonnenberg                                 43             61    davon 33 Plätze Tagesklinik Merzig und 10 Plätze Tagesklinik St. Wendel
Universitätsklinikum des Saarlandes                     28             18
    Abbildung 368 - Eigene Darstellung - Zuweisung Fachabteilung Kinder- und Jugendpsychiatrie und -psychotherapie

8.63.1 Bisherige Versorgungssituation
Im Jahr 2023 standen im Saarland insgesamt 739 Planbetten zur Verfügung. Die geringste
Bettenkapazität einer Einrichtung betrug dabei 57 Planbetten, während die höchste Betten-
kapazität 236 Planbetten umfasste. Darüber hinaus wurden im Saarland in der Fachabtei-
lung Psychiatrie und Psychotherapie 314 tagesklinische Behandlungsplätze vorgehalten.

Fachabteilung Psychiatrie und Psychotherapie
Krankenhausstandort                                                          Planbetten Planplätze                               Bemerkungen

Diakonie Kliniken Fliedner Neunkirchen                                          135            27
Klinikum Merzig                                                                  0             33
Universitätsklinikum des Saarlandes                                             116            47
                    Abbildung 381 - Eigene Darstellung - Zuweisung Fachabteilung Psychiatrie und Psychotherapie

8.64.1 Bisherige Versorgungssituation
Im Jahr 2023 standen im Saarland insgesamt 126 Planbetten zur Verfügung. Die geringste
Bettenkapazität einer Einrichtung betrug dabei 15 Planbetten, während die höchste Betten-
kapazität 38 Planbetten umfasste. Darüber hinaus wurden im Saarland in der Fachabtei-
lung Psychosomatische Medizin und Psychotherapie 24 tagesklinische Behandlungsplätze
vorgehalten sowie eine Einrichtung mit Psychosomatischer Institutsambulanz.

Fachabteilung Psychosomatische Medizin und Psychotherapie
Krankenhausstandort                            Planbetten Planplätze                    Bemerkungen

CaritasKlinikum Saarbrücken, St. Josef             38         30       ab dem Jahr 2033 am CaritasKlinikum St. Theresia

Johannesbad Saarschleife Fachkrankenhaus für
                                                   15         0
Psychosomatische Medizin und Psychotherapie

Knappschaft Kliniken Püttlingen                    30         12

MEDIAN Klinik Berus                                36         0

    Abbildung 393 - Eigene Darstellung - Zuweisung Fachabteilung Psychosomatische Medizin und Psychotherapie
"""


class HospitalArchiveTests(unittest.TestCase):
    def test_all_archive_sources_are_rights_reserved(self):
        for key in hp.ARCHIVE_KEYS:
            meta = hp.SOURCES[key]
            self.assertEqual(meta["license"], RESERVED_LICENCE, key)
            self.assertNotIn("§ 5 Abs", meta["license"], key)
            self.assertTrue(meta.get("archive_file"), key)
            self.assertTrue(meta["url"].startswith("https://"), key)

    def test_schleswig_holstein_land_totals(self):
        figs = hp.schleswig_holstein_teil_a_land(SH_TEXT)
        by = {(f["year"], f["metric"]): f for f in figs}
        self.assertEqual(by[(2017, "khplan_kjp_beds")]["value"], 244)
        self.assertEqual(by[(2017, "khplan_kjp_day_places")]["value"], 167)
        self.assertEqual(by[(2017, "khplan_psych_beds")]["value"], 1981)
        self.assertEqual(by[(2017, "khplan_psych_day_places")]["value"], 746)
        self.assertEqual(by[(2017, "khplan_psm_beds")]["value"], 450)
        self.assertEqual(by[(2017, "khplan_psm_day_places")]["value"], 107)
        self.assertEqual(by[(2015, "khplan_kjp_beds")]["value"], 239)
        self.assertEqual(by[(2015, "khplan_kjp_day_places")]["value"], 150)
        self.assertEqual(by[(2015, "khplan_psych_beds")]["value"], 1962)
        self.assertEqual(by[(2015, "khplan_psych_day_places")]["value"], 700)
        self.assertEqual(by[(2015, "khplan_psm_beds")]["value"], 448)
        self.assertNotIn((2015, "khplan_psm_day_places"), by)
        self.assertEqual(len(figs), 11)
        for rec in figs:
            self.assertTrue(rec["is_total"])
            self.assertEqual(rec["land"], "SH")
            self.assertTrue(quote_in_text(rec["quote"], SH_TEXT))
            token = f"{rec['value']:,}".replace(",", ".") if rec["value"] >= 1000 else str(rec["value"])
            self.assertIn(token, rec["quote"])
            self.assertIn("schleswig-holstein.de", rec["locator"])
            self.assertIn("PDF-S.", rec["locator"])

    def test_bremen_land_uses_2022_column_not_veraenderung(self):
        figs = hp.bremen_rahmenplan_land(HB_LAND)
        by = {f["metric"]: f for f in figs}
        self.assertEqual(by["khplan_kjp_beds"]["value"], 50)
        self.assertEqual(by["khplan_psych_beds"]["value"], 563)
        self.assertEqual(by["khplan_psm_beds"]["value"], 30)
        self.assertEqual(by["khplan_kjp_day_places"]["value"], 43)
        self.assertEqual(by["khplan_psych_day_places"]["value"], 268)
        self.assertNotIn("khplan_psm_day_places", by)
        for rec in figs:
            self.assertTrue(quote_in_text(rec["quote"], HB_LAND))
            self.assertEqual(rec["year"], 2022)
            self.assertIn("gesundheit.bremen.de", rec["locator"])
            # 2022 is the 13th year, not the trailing Veränderung (0 / 8 / 12 / 25 / 94)
            self.assertNotEqual(rec["value"], 0)
            self.assertNotEqual(rec["value"], 8)
            self.assertNotEqual(rec["value"], 12)

    def test_bremen_hospitals_sum_to_land_and_create_org(self):
        hospitals = hp.bremen_rahmenplan_hospitals("\f" + "z\n" * 25 + HB_LAND + HB_HOSP)
        # fixture only includes AMEOS and Bremen-Ost
        names = {r["hospital_name"] for r in hospitals}
        self.assertEqual(names, {"AMEOS Klinikum Bremen", "Klinikum Bremen-Ost"})
        ost = [r for r in hospitals if r["hospital_name"] == "Klinikum Bremen-Ost"]
        by = {r["metric"]: r for r in ost}
        self.assertEqual(by["khplan_kjp_beds"]["value"], 50)
        self.assertEqual(by["khplan_psych_beds"]["value"], 220)
        self.assertEqual(by["khplan_psm_beds"]["value"], 30)
        self.assertEqual(by["khplan_psych_beds"]["legal_form"], "gGmbH")
        self.assertEqual(by["khplan_psych_beds"]["kreis_ags"], "04011")
        ameos = [r for r in hospitals if r["hospital_name"] == "AMEOS Klinikum Bremen"]
        self.assertEqual(ameos[0]["legal_form"], "mbH")
        for rec in hospitals:
            self.assertTrue(rec["create_org"])
            self.assertTrue(quote_in_text(rec["quote"], HB_HOSP))

    def test_saarland_2018_festlegungen(self):
        figs = hp.saarland_2018_land(SL2018)
        by = {(f["year"], f["metric"]): f["value"] for f in figs}
        self.assertEqual(by[(2017, "khplan_kjp_beds")], 55)
        self.assertEqual(by[(2017, "khplan_kjp_day_places")], 60)
        self.assertEqual(by[(2025, "khplan_kjp_beds")], 71)
        self.assertEqual(by[(2025, "khplan_kjp_day_places")], 73)
        self.assertEqual(by[(2017, "khplan_psych_beds")], 643)
        self.assertEqual(by[(2017, "khplan_psych_day_places")], 248)
        self.assertEqual(by[(2025, "khplan_psych_beds")], 690)
        self.assertEqual(by[(2025, "khplan_psych_day_places")], 289)
        self.assertEqual(by[(2017, "khplan_psm_beds")], 86)
        self.assertEqual(by[(2017, "khplan_psm_day_places")], 10)
        self.assertEqual(by[(2025, "khplan_psm_beds")], 90)
        self.assertEqual(by[(2025, "khplan_psm_day_places")], 12)
        self.assertEqual(len(figs), 12)
        for rec in figs:
            self.assertTrue(quote_in_text(rec["quote"], SL2018))
            self.assertIn("saarland.de", rec["locator"])

    def test_saarland_2027_land_and_clean_hospitals(self):
        land = hp.saarland_2027_land(SL2027)
        by = {f["metric"]: f["value"] for f in land}
        self.assertEqual(by, {
            "khplan_kjp_beds": 73,
            "khplan_kjp_day_places": 77,
            "khplan_psych_beds": 739,
            "khplan_psych_day_places": 314,
            "khplan_psm_beds": 126,
            "khplan_psm_day_places": 24,
        })
        for rec in land:
            self.assertTrue(quote_in_text(rec["quote"], SL2027), rec["quote"])
            self.assertEqual(rec["year"], 2023)

        hospitals = hp.saarland_2027_hospitals(SL2027)
        names = {r["hospital_name"] for r in hospitals}
        self.assertIn("SHG-Kliniken Sonnenberg", names)
        self.assertIn("Knappschaft Kliniken Püttlingen", names)
        self.assertIn("MEDIAN Klinik Berus", names)
        self.assertNotIn("Johannesbad Saarschleife Fachkrankenhaus für", names)
        self.assertFalse(any("Johannesbad" in n for n in names))
        mk = [r for r in hospitals if r["hospital_name"] == "Marienhaus Klinikum Neunkirchen"]
        self.assertEqual(len(mk), 1)
        self.assertEqual(mk[0]["metric"], "khplan_kjp_day_places")
        self.assertEqual(mk[0]["value"], 10)
        self.assertEqual(mk[0]["year"], 2028)
        merzig = [r for r in hospitals if r["hospital_name"] == "Klinikum Merzig"]
        self.assertEqual(merzig[0]["metric"], "khplan_psych_day_places")
        self.assertEqual(merzig[0]["value"], 33)
        self.assertEqual(merzig[0]["kreis_ags"], "10044")
        berus = [r for r in hospitals if r["hospital_name"] == "MEDIAN Klinik Berus"]
        self.assertEqual(berus[0]["value"], 36)
        self.assertEqual(berus[0]["kreis_ags"], "10045")
        for rec in hospitals:
            self.assertTrue(quote_in_text(rec["quote"], SL2027), rec["quote"])
            self.assertTrue(rec["create_org"])

    def test_ingest_stores_land_and_orgs_without_fetch(self):
        conn = memory_db()
        notes, sources = [], []
        texts = {
            "sh_kh2017_a": SH_TEXT,
            "sh_kh2017_anlagen": "Anlagen ohne zitierfähige Krankenhauszeilen.",
            "sh_kh2017_besonderer": "Besonderer Teil ohne zitierfähige Krankenhauszeilen.",
            "hb_kh2022": "\f" + "z\n" * 25 + HB_LAND + HB_HOSP,
            "sl_kh2018": SL2018,
            "sl_kh2027": SL2027,
        }

        def boom(*args, **kwargs):
            raise AssertionError(f"network must not be used: {args!r} {kwargs!r}")

        with patch.object(hp, "fetch", boom), patch.object(hp, "khplan_robots_status", boom):
            def load(key, force=False, cfg=None):
                if key in texts:
                    return texts[key]
                raise hp.RobotsBlocked(f"skip {key} in test")
            with patch.object(hp, "_load_document", load):
                stored = hp.ingest_hospital_plans(conn, {"khplan_texts": texts}, sources, notes)
        self.assertGreaterEqual(stored, 11 + 5 + 12 + 6)
        sh = list(conn.execute("SELECT metric, year, value FROM metric WHERE entity_id='01'"))
        self.assertTrue(any(r["metric"] == "khplan_psych_beds" and r["year"] == 2017 and r["value"] == 1981 for r in sh))
        hb = conn.execute(
            "SELECT value FROM metric WHERE entity_id='04' AND metric='khplan_psych_beds' AND year=2022"
        ).fetchone()
        self.assertEqual(hb["value"], 563)
        orgs = [r["name"] for r in conn.execute("SELECT name FROM org")]
        self.assertIn("AMEOS Klinikum Bremen", orgs)
        self.assertIn("Klinikum Bremen-Ost", orgs)
        self.assertIn("SHG-Kliniken Sonnenberg", orgs)
        self.assertFalse(any("Johannesbad" in n for n in orgs))
        licences = {r["license"] for r in conn.execute("SELECT license FROM source")}
        for lic in licences:
            self.assertNotIn("§ 5 Abs", lic)

    def test_archive_bytes_check_sha256_and_make_no_network(self):
        payload = b"%PDF-1.4 test plan\n"
        digest = hashlib.sha256(payload).hexdigest()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "sh_krankenhausplan_2017_teil_a.pdf").write_bytes(payload)
            (root / "SHA256SUMS").write_text(f"{digest}  sh_krankenhausplan_2017_teil_a.pdf\n")
            cfg = {"manual_archive": str(root)}
            def boom(*a, **k):
                raise AssertionError("network")
            with patch("ingest.common.fetch", boom), patch.object(hp, "fetch", boom):
                data = hp.read_archived_plan_bytes(cfg, "sh_krankenhausplan_2017_teil_a.pdf")
            self.assertEqual(data, payload)
            (root / "SHA256SUMS").write_text(f"{'0'*64}  sh_krankenhausplan_2017_teil_a.pdf\n")
            with self.assertRaises((hp.ArchiveIntegrityError, ValueError)):
                hp.read_archived_plan_bytes(cfg, "sh_krankenhausplan_2017_teil_a.pdf")
            with self.assertRaises(hp.ArchiveIntegrityError):
                hp.read_archived_plan_bytes(cfg, "missing.pdf")


if __name__ == "__main__":
    unittest.main()
