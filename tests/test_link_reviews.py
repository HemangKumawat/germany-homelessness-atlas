"""Lead review of flagged org links (docs/link_reviews.tsv). Run: python3 tests/test_link_reviews.py"""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
from ingest import common, orglink  # noqa: E402
from test_g11_join_integrity import award, org, scratch  # noqa: E402


def rv(kind, key, oid, norm, verdict, method="manual", ev="evidence"):
    return dict(kind=kind, key=key, org_id=oid, org_norm=norm, verdict=verdict, method=method, evidence=ev)


class LinkReviews(unittest.TestCase):
    def test_legal_kind_ev_abbreviation_is_not_a_verein(self):
        # "Ev." = evangelisch; it made a KdöR parish look like an e.V. and flagged a correct ZUWDB award link
        self.assertEqual(orglink.legal_kind("Ev. Kirchengemeinde Zum Guten Hirten"), "KdöR")
        self.assertEqual(orglink.legal_kind("Kirchengemeinde zum Guten Hirten"), "KdöR")
        for n in ("jhj Hamburg e.V", "Mook wat e.V.", "Gangway e. V.", "Foo eV", "Eingetragener Verein Bar"):
            self.assertEqual(orglink.legal_kind(n), "e.V.", n)

    def test_confirm_survives_resync_and_module_relink_but_not_a_new_org(self):
        with tempfile.TemporaryDirectory() as td:
            c = scratch(td)
            a = org(c, "Omega Hilfe gGmbH", "HH")
            award(c, "TED:9:LOT:OMEGA", a, "Omega Hilfe gGmbH", sid=2)
            common.link_org(c, record_kind="impressum", record_key="https://omega.invalid/impressum#Omega", org_id=a,
                            method="name_fuzzy", confidence=0.9, source_id=2, record_name="Omega Hilfe gGmbH")
            orglink.sync(c)
            norm = common.name_norm("Omega Hilfe gGmbH")
            res = orglink.apply_link_reviews(c, [rv("award", "TED:9:LOT:OMEGA", a, norm, "confirm"),
                                                 rv("impressum", "https://omega.invalid/impressum#Omega", a, norm, "confirm", "origin")])
            self.assertEqual(res["confirmed"], 2)
            orglink.sync(c)                                                       # sync keeps the reviewed award link
            common.link_org(c, record_kind="impressum", record_key="https://omega.invalid/impressum#Omega", org_id=a,
                            method="name_fuzzy", confidence=0.9, source_id=2)     # module re-run: not downgraded
            got = dict(((k, (m, f, r)) for k, m, f, r in (tuple(x) for x in c.execute(
                "SELECT record_kind, method, flagged, reviewed FROM org_link WHERE record_kind IN ('award','impressum')"))))
            self.assertEqual(got, {"award": ("manual", 0, 1), "impressum": ("origin", 0, 1)})
            self.assertEqual(orglink.gate(c)[0], [])
            b = org(c, "Omega Hilfe gGmbH", "BE")                                  # a module now matches another org
            common.link_org(c, record_kind="impressum", record_key="https://omega.invalid/impressum#Omega", org_id=b,
                            method="name_fuzzy", confidence=0.9, source_id=2)
            self.assertEqual(tuple(c.execute("SELECT org_id, method, flagged, reviewed FROM org_link WHERE record_kind='impressum'").fetchone()),
                             (b, "name_fuzzy", 1, 0))
            c.execute("UPDATE award SET org_id=? WHERE foerder_schluessel='TED:9:LOT:OMEGA'", (b,))
            orglink.sync(c)                                                       # award moved: re-flagged, not kept as manual
            self.assertEqual(tuple(c.execute("SELECT org_id, method, flagged FROM org_link WHERE record_kind='award'").fetchone()),
                             (b, "name_fuzzy", 1))

    def test_reject_unlinks_the_award_unsure_and_stale_lines_untouched(self):
        with tempfile.TemporaryDirectory() as td:
            c = scratch(td)
            a = org(c, "Sigma Dienste e. V.", "BE")
            award(c, "TED:7:LOT:SIGMA", a, "Sigma Dienste e.V.", sid=2)
            award(c, "TED:8:LOT:SIGMA", a, "Sigma Dienste e.V.", sid=2)
            orglink.sync(c)
            norm = common.name_norm("Sigma Dienste e. V.")
            res = orglink.apply_link_reviews(c, [rv("award", "TED:7:LOT:SIGMA", a, norm, "reject"),
                                                 rv("award", "TED:8:LOT:SIGMA", a, norm, "unsure"),
                                                 rv("award", "TED:8:LOT:SIGMA", a, "OTHER NAME", "confirm")])
            self.assertEqual((res["rejected"], res["unsure"], res["skipped_keys"]), (1, 1, ["award:TED:8:LOT:SIGMA"]))
            self.assertIsNone(c.execute("SELECT org_id FROM award WHERE foerder_schluessel='TED:7:LOT:SIGMA'").fetchone()[0])
            orglink.sync(c)
            self.assertEqual([tuple(x) for x in c.execute("SELECT record_key, flagged FROM org_link WHERE record_kind='award'")],
                             [("TED:8:LOT:SIGMA", 1)])

    def test_repo_file_parses_and_every_line_has_evidence(self):
        rows = orglink.read_link_reviews()
        self.assertTrue(rows)
        for r in rows:
            self.assertTrue(len(r["evidence"]) > 20, r)
            if r["verdict"] == "confirm":
                self.assertIn(r["method"], orglink.REVIEW_METHODS)


if __name__ == "__main__":
    unittest.main(verbosity=1)
