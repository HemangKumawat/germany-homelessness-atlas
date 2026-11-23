"""INGEST_CONTRACT §11 lapsed rules (counts_law _mu). Run: python3 tests/test_lapsed_law.py"""
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from ingest.domains import counts_law as cl  # noqa: E402

ARGS = ("t_key", "05916", "NW", "Herne", "https://example.invalid/x.pdf", "verordnung", "betteln", "cit", "title",
        "2017-03-02", "vom 21.12.2005", "consolidated", "summary")


class Lapsed(unittest.TestCase):
    def test_valid(self):
        m = cl._mu(*ARGS, ["a", "in Kraft seit 1985"], lapsed_on="2005-11-06", lapsed_basis="§ 32 Abs. 1 OBG NRW",
                   lapsed_needle="in Kraft seit 1985")
        self.assertEqual(m["lapsed_on"], "2005-11-06")
        self.assertEqual(cl.lapsed_label("2005-11-06"), "06.11.2005")
        self.assertEqual(cl.lapsed_label("2016"), "2016")

    def test_rejects_bad_rows(self):
        with self.assertRaises(ValueError):    # basis must cite § / Art.
            cl._mu(*ARGS, ["a"], lapsed_on="2016", lapsed_basis="old", lapsed_needle="a")
        with self.assertRaises(ValueError):    # deciding sentence must be a verified needle
            cl._mu(*ARGS, ["a"], lapsed_on="2016", lapsed_basis="Art. 50 Abs. 2 LStVG", lapsed_needle="b")
        with self.assertRaises(ValueError):    # date format
            cl._mu(*ARGS, ["a"], lapsed_on="Nov 2005", lapsed_basis="§ 32 OBG NRW", lapsed_needle="a")

    def test_the_lead_decisions(self):
        # Coburg back to in_force (b20 section analysis, accepted by the Lead 2026-11-23: § 3 is GO-Satzung law;
        # only the LStVG-based §§ 5-6 lapsed on 01.11.2016)
        got = {m["key"]: m["lapsed_on"] for m in cl.MUNI if m["lapsed_on"]}
        self.assertEqual(got, {"herne_strassenvo": "2026-01-03", "hagen_gebietsordnung": "2005-11-06"})
        self.assertIn("coburg_sicherheitsvo", {m["key"] for m in cl.MUNI if not m["lapsed_on"]})
        for m in cl.MUNI:
            if m["lapsed_on"]:
                self.assertIn(m["lapsed_needle"], m["needles"])
                self.assertTrue(re.search(r"§|Art\.", m["lapsed_basis"]))
            else:
                self.assertIsNone(m["lapsed_basis"])


if __name__ == "__main__":
    unittest.main()
