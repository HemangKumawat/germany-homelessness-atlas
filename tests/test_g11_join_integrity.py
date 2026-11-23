"""G11 join integrity + org entity resolution (schema 5). Run: python3 tests/test_g11_join_integrity.py"""
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from ingest import common, join_gaps, orglink, run  # noqa: E402
from ingest.domains import lead_org_resolution  # noqa: E402


def scratch(td):
    conn = run.open_db(Path(td) / "g11.db")
    conn.execute("INSERT INTO source(id, domain, url, title, license) VALUES (1,'t','https://example.invalid/a','a','x')")
    conn.execute("INSERT INTO source(id, domain, url, title, license) VALUES (2,'t','https://example.invalid/b','b','x')")
    return conn


def org(conn, name, land="BE", **kw):
    cols = {"name": name, "name_norm": common.name_norm(name), "land": land, "source_id": 1, **kw}
    return conn.execute(f"INSERT INTO org({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", list(cols.values())).lastrowid


def award(conn, key, org_id, name, reg=None, eid=None, sid=1):
    return conn.execute("INSERT INTO award(foerder_schluessel, empfaenger, empfaenger_norm, empfaenger_register, empfaenger_id, "
                        "org_id, source_id) VALUES (?,?,?,?,?,?,?)", (key, name, common.name_norm(name), reg, eid, org_id, sid)).lastrowid


def g11(conn):
    return orglink.gate(conn)


class Normalisation(unittest.TestCase):
    def test_register_keys(self):
        k = orglink.parse_court_register
        self.assertEqual(k("HRB 245577 B AG Charlottenburg")[0], "HRB:245577:CHARLOTTENBURG")
        self.assertEqual(k("HRB 245577B")[0], "HRB:245577:CHARLOTTENBURG")          # suffix B = AG Charlottenburg
        self.assertEqual(k("HRB 26997 (AG Köln)")[0], "HRB:26997:KOELN")
        self.assertEqual(k("HRB 14122 Münster")[0], "HRB:14122:MUENSTER")
        self.assertEqual(k("HRB202174")[0], k("HRB 202174")[0])
        self.assertEqual(k("Amtsgericht Charlottenburg VR 021507 B")[0], "VR:21507:CHARLOTTENBURG")
        self.assertEqual(orglink.register_keys("vr_021507"), [("register_id", "BE_ZUWDB:vr_021507")])
        self.assertEqual(orglink.register_keys("kör_100050"), [("register_id", "BE_ZUWDB:kör_100050")])
        self.assertEqual(orglink.register_keys("R001276"), [("register_id", "LobbyR:R001276")])
        self.assertEqual(orglink.register_keys("11902"), [])                          # digits alone are no register
        self.assertEqual(orglink.register_keys("11902", ba_traeger=True), [("register_id", "BA_JC:11902")])
        self.assertEqual(orglink.ust_key("DE 257 193 663"), "UST:DE257193663")
        self.assertIsNone(orglink.ust_key("Keine Angabe"))
        self.assertIsNone(orglink.ust_key("0"))
        self.assertEqual(orglink.qid_key("https://www.wikidata.org/wiki/Q42"), "QID:Q42")
        self.assertEqual(orglink.loose_register("BE_ZUWDB:vr_021507"), "VR:21507")
        self.assertEqual(orglink.loose_register("VR:21507:CHARLOTTENBURG"), "VR:21507")


class Gate(unittest.TestCase):
    def test_clean_db_passes_and_schema_is_v5_or_later(self):
        with tempfile.TemporaryDirectory() as td:
            c = scratch(td)
            self.assertGreaterEqual(c.execute("PRAGMA user_version").fetchone()[0], 5)
            self.assertTrue(orglink.has_v5(c))
            a = org(c, "Alpha Hilfe e. V.", register_id="vr_000001")
            award(c, "DE-BE-ZUW:1", a, "Alpha Hilfe e. V.", reg="vr_000001")
            orglink.sync(c)
            probs, info = g11(c)
            self.assertEqual(probs, [])
            self.assertEqual(info["hard_id_duplicates"], 0)
            self.assertEqual(c.execute("SELECT method FROM org_link WHERE record_kind='award'").fetchone()[0], "register_id")

    def test_a_shared_hard_id_fails_then_lead_merge_fixes(self):
        with tempfile.TemporaryDirectory() as td:
            c = scratch(td)
            a = org(c, "Beta Soziale Dienste gGmbH", register_id="hrb_000777")
            b = org(c, "Beta Soziale Dienste gGmbH, Projekt X", register_id="hrb_000777")
            c.execute("INSERT INTO org_register(org_id, scheme, court, number, raw, source_id) VALUES (?,?,?,?,?,1)",
                      (a, "BE_ZUWDB", "", "hrb_000777", "hrb_000777"))
            award(c, "DE-BE-ZUW:2", b, "Beta Soziale Dienste gGmbH, Projekt X", reg="hrb_000777")
            c.execute("INSERT INTO org_person(org_id, funktionstraeger, funktionstraeger_norm, funktion, source_id) "
                      "VALUES (?,?,?,?,1)", (b, "Erika Beispiel", "ERIKA BEISPIEL", "Geschäftsführerin"))
            probs, info = g11(c)
            self.assertTrue(any(p.startswith("(a) hard id BE_ZUWDB:hrb_000777 maps to 2") for p in probs), probs)
            res = lead_org_resolution.run(c, {})
            self.assertIn(f"{b}->{a}", res["notes"])
            probs, info = g11(c)
            self.assertEqual(probs, [])
            self.assertEqual(info["aliases"], 1)
            self.assertEqual(c.execute("SELECT canonical_org_id FROM org WHERE id=?", (b,)).fetchone()[0], a)
            self.assertEqual(c.execute("SELECT org_id FROM award").fetchone()[0], a)
            self.assertEqual(c.execute("SELECT org_id FROM org_person").fetchone()[0], a)
            self.assertEqual(c.execute("SELECT count(*) FROM org").fetchone()[0], 2)     # alias row kept
            lk = c.execute("SELECT org_id, method, id_value, note FROM org_link WHERE record_kind='org' AND record_key=?",
                           (str(b),)).fetchone()
            self.assertEqual((lk[0], lk[1], lk[2]), (a, "register_id", "BE_ZUWDB:hrb_000777"))
            # later writes that name the alias are re-pointed by the triggers
            award(c, "DE-BE-ZUW:3", b, "Beta Soziale Dienste gGmbH, Projekt X", reg="hrb_000777")
            common.upsert(c, "org_person", {"org_id": b, "org_bezeichnung": "Beta", "funktionstraeger": "Otto Muster",
                                            "funktionstraeger_norm": "OTTO MUSTER", "funktion": "Vorstand", "source_id": 1},
                          keys=["funktionstraeger_norm", "org_bezeichnung", "jahr", "funktion"])
            self.assertEqual({r[0] for r in c.execute("SELECT org_id FROM award")}, {a})
            self.assertEqual({r[0] for r in c.execute("SELECT org_id FROM org_person")}, {a})
            self.assertEqual(common.canonical_org(c, b), a)
            self.assertEqual(common.resolve_org(c, register="hrb_000777"), a)
            with self.assertRaises(sqlite3.IntegrityError):          # no alias chains
                c.execute("UPDATE org SET canonical_org_id=? WHERE id=?", (b, org(c, "Gamma GmbH")))

    def test_ust_shared_by_two_canonical_orgs_fails(self):
        with tempfile.TemporaryDirectory() as td:
            c = scratch(td)
            org(c, "Delta Catering GmbH", "SN", ust_id="DE257193663")
            org(c, "Delta Catering GmbH &amp; Co", None, ust_id="DE 257193663")
            probs, _ = g11(c)
            self.assertTrue(any("(a) hard id UST:DE257193663 maps to 2" in p for p in probs), probs)

    def test_name_match_never_merges(self):
        with tempfile.TemporaryDirectory() as td:
            c = scratch(td)
            a = org(c, "Epsilon Hilfe e. V.", "BE")
            b = org(c, "Epsilon Hilfe e. V.", "HH")
            award(c, "TED:1:LOT:EPSILON", b, "Epsilon Hilfe e.V.", sid=2)
            self.assertEqual(orglink.plan_hard_merges(c), [])
            orglink.sync(c)
            m, f, conf = c.execute("SELECT method, flagged, confidence FROM org_link WHERE record_kind='award'").fetchone()
            self.assertEqual((m, f), ("name_fuzzy", 1))
            self.assertLess(conf, 1.0)
            with self.assertRaises(ValueError):
                orglink.merge(c, b, a, method="name_fuzzy", confidence=0.9, reason="names match")
            gm = org(c, "Epsilon Dienste gGmbH", "HH")
            award(c, "TED:2:LOT:EPSILON", gm, "Epsilon Dienste e.V.", sid=2)       # e.V. in the notice, gGmbH org
            orglink.sync(c)
            conf, note = c.execute("SELECT confidence, note FROM org_link WHERE record_key='TED:2:LOT:EPSILON'").fetchone()
            self.assertLessEqual(conf, 0.5)
            self.assertIn("legal form differs", note)
            c.execute("DELETE FROM award WHERE foerder_schluessel='TED:2:LOT:EPSILON'")
            orglink.sync(c)
            d = join_gaps.compute(c)
            self.assertEqual(d["dup_same_name"], [{"name_norm": "EPSILON HILFE", "orgs": [a, b]}])
            self.assertEqual(len(d["fuzzy_links"]), 1)
            self.assertEqual(g11(c)[0], [])                                        # flagged, not a failure

    def test_link_helper(self):
        with tempfile.TemporaryDirectory() as td:
            c = scratch(td)
            a = org(c, "Zeta gGmbH")
            lid = common.link_org(c, record_kind="wikidata", record_key="Q123", org_id=a, method="name_fuzzy",
                                  confidence=0.8, source_id=1, record_name="Zeta")
            self.assertEqual(c.execute("SELECT flagged FROM org_link WHERE id=?", (lid,)).fetchone()[0], 1)
            with self.assertRaises(ValueError):
                common.link_org(c, record_kind="wikidata", record_key="Q124", org_id=a, method="wikidata_qid",
                                confidence=1, source_id=1)                       # hard method needs its id
            with self.assertRaises(ValueError):
                common.link_org(c, record_kind="x", record_key="1", org_id=a, method="guess", confidence=1, source_id=1)
            common.link_org(c, record_kind="wikidata", record_key="Q125", org_id=a, method="wikidata_qid",
                            confidence=1, source_id=1, id_value=orglink.qid_key("Q125"))
            self.assertEqual(common.resolve_org(c, qid="Q125"), a)
            b = org(c, "Zeta Zwei gGmbH")
            common.link_org(c, record_kind="wikidata", record_key="Q126", org_id=b, method="wikidata_qid",
                            confidence=1, source_id=1, id_value="QID:Q125")
            probs, _ = g11(c)
            self.assertTrue(any("(a) hard id QID:Q125 maps to 2" in p for p in probs), probs)
            with self.assertRaises(ValueError):
                common.resolve_org(c, qid="Q125")

    def test_b_orphans_and_alias_references(self):
        with tempfile.TemporaryDirectory() as td:
            c = scratch(td)
            a = org(c, "Eta e. V.")
            b = org(c, "Eta Zwei e. V.")
            award(c, "X:1", b, "Eta Zwei e. V.")
            c.execute("UPDATE org SET canonical_org_id=? WHERE id=?", (a, b))     # award left on the alias
            c.execute("PRAGMA foreign_keys=OFF")
            c.execute("INSERT INTO org_person(org_id, funktionstraeger, funktionstraeger_norm, funktion, source_id) "
                      "VALUES (999,'Erika Beispiel','ERIKA BEISPIEL','Vorstand',1)")
            c.execute("INSERT INTO org_register(org_id, scheme, court, number, raw, source_id) VALUES (998,'LobbyR','','R000001','R000001',1)")
            probs, info = g11(c)
            self.assertTrue(any(p.startswith("(b) award row") and "alias org 'Eta Zwei e. V.'" in p for p in probs), probs)
            self.assertTrue(any(p.startswith("(b) org_person row") and "names no org" in p for p in probs), probs)
            self.assertTrue(any(p.startswith("(b) org_register row") and "names no org" in p for p in probs), probs)
            out = Path(td) / "gaps.md"
            join_gaps.write(c, out)
            txt = out.read_text(encoding="utf-8")
            self.assertIn("| org_person rows without a valid org link | 1 |", txt)
            self.assertNotIn("Erika", txt)                                        # no person names in the report

    def test_b_award_register_conflict_fixed_ust_conflict_reported(self):
        with tempfile.TemporaryDirectory() as td:
            c = scratch(td)
            gmbh = org(c, "Theta gGmbH", register_id="hrb_000555")
            ev = org(c, "Theta Verein e. V.", register_id="vr_000444")
            aw = award(c, "DE-BE-ZUW:9", ev, "Theta gGmbH", reg="hrb_000555")     # a name match picked the e. V.
            parent = org(c, "Iota GmbH", ust_id="DE111111111")
            sub = org(c, "Iota Pflege gGmbH", register_id="HRB 1 B")
            award(c, "TED:9:L:IOTA", sub, "Iota Pflege gGmbH", eid="DE111111111")    # VAT group number
            probs, _ = g11(c)
            self.assertTrue(any("award DE-BE-ZUW:9: recipient id 'BE_ZUWDB:hrb_000555'" in p for p in probs), probs)
            self.assertFalse(any("TED:9" in p for p in probs), probs)
            lead_org_resolution.run(c, {})
            self.assertEqual(c.execute("SELECT org_id FROM award WHERE id=?", (aw,)).fetchone()[0], gmbh)
            self.assertEqual(g11(c)[0], [])
            self.assertEqual(len(join_gaps.compute(c)["ust_conflicts"]), 1)
            self.assertEqual(c.execute("SELECT canonical_org_id FROM org WHERE id=?", (sub,)).fetchone()[0], None)
            del parent

    def test_c_null_regression_and_allowlist(self):
        with tempfile.TemporaryDirectory() as td:
            c = scratch(td)
            a = org(c, "Kappa e. V.", webseite="https://kappa.example")
            rid = c.execute("INSERT INTO ingest_run(domain, status) VALUES ('demo','ok')").lastrowid
            orglink.snapshot(c, rid, "before")
            c.execute("UPDATE org SET webseite=NULL WHERE id=?", (a,))
            orglink.snapshot(c, rid, "after")
            probs, info = orglink.null_regressions(c, allow=[])
            self.assertEqual(len(probs), 1, probs)
            self.assertIn("org.webseite 1 -> 0", probs[0])
            ok, info = orglink.null_regressions(c, allow=[dict(run="*", domain="demo", table="org", column="webseite",
                                                               max_drop=1, reason="reviewed")])
            self.assertEqual(ok, [])
            self.assertEqual(info["allowed"], 1)
            narrow, _ = orglink.null_regressions(c, allow=[dict(run="*", domain="other", table="org", column="*",
                                                                max_drop=5, reason="other domain")])
            self.assertEqual(len(narrow), 1)
            p = Path(td) / "allow.tsv"
            p.write_text("run\tdomain\ttable\tcolumn\tmax_drop\treason\n*\tdemo\torg\twebseite\t1\t\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                orglink.read_allowlist(p)                                         # a reason is mandatory
            self.assertTrue(all(e["reason"] for e in orglink.read_allowlist()))   # the shipped allowlist parses

    def test_runner_snapshots_syncs_and_writes_report(self):
        with tempfile.TemporaryDirectory() as td:
            c = scratch(td)
            org(c, "Lambda e. V.", register_id="vr_000123")
            org(c, "Lambda Verein e. V.", register_id="vr_000123")
            c.close()
            saved = (common.LOCK, run.ledger, join_gaps.REPORT, list(run._held))
            try:
                run._held.clear()
                common.LOCK = Path(td) / "atlas.lock"
                run.ledger = lambda *a, **k: None
                join_gaps.REPORT = Path(td) / "join_gaps.md"
                rc = run.run_domain("lead_org_resolution", {}, db_path=Path(td) / "g11.db")
                self.assertEqual(rc, 0)
            finally:
                for fh in run._held:
                    fh.close()
                run._held[:] = saved[3]
                common.LOCK, run.ledger, join_gaps.REPORT = saved[0], saved[1], saved[2]
            c = sqlite3.connect(Path(td) / "g11.db")
            phases = {r[0] for r in c.execute("SELECT phase FROM ingest_colstats")}
            self.assertEqual(phases, {"before", "after"})
            self.assertEqual(c.execute("SELECT count(*) FROM org WHERE canonical_org_id IS NOT NULL").fetchone()[0], 1)
            self.assertEqual(orglink.gate(c)[0], [])
            txt = (Path(td) / "join_gaps.md").read_text(encoding="utf-8")
            self.assertIn("| orgs (rows) / canonical / alias rows | 2 / 1 / 1 |", txt)


if __name__ == "__main__":
    unittest.main(verbosity=1)
