"""Lead: site rendering rules for availability flags and the two psychiatric-bed series."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import build_site  # noqa: E402
from ingest.common import xlsx_cell_line, xlsx_col  # noqa: E402


class SiteRenderTests(unittest.TestCase):
    def test_flag_zero_is_no_data_never_zero(self):
        r = {"metric": "jva_release_homeless_data_available", "value": 0.0, "einheit": "flag"}
        out = build_site.mval(r)
        self.assertIn("no data", out)
        self.assertNotRegex(out, r"(?<![\w])0(?![\w])")

    def test_flag_unit_without_suffix(self):
        self.assertIn("no data", build_site.mval({"metric": "x", "value": 0, "einheit": "flag"}))

    def test_ordinary_zero_still_renders(self):
        self.assertEqual(build_site.mval({"metric": "drug_deaths", "value": 0, "einheit": "persons"}), "0")

    def test_psych_series_labelled_separately(self):
        a = build_site.METRIC_LABEL["psychiatric_care_hospital_beds"]
        for m in ("hospital_beds_allgemeine_psychiatrie", "hospital_beds_kinder_jugendpsychiatrie", "hospital_beds_psychosomatik"):
            b = build_site.METRIC_LABEL[m]
            self.assertIn("23111-07", b)
            self.assertIn("separate", b)
            self.assertNotIn("23111-07", a)
        self.assertIn("21/6258", a)

    def test_xlsx_cell_line(self):
        self.assertEqual(xlsx_col(0), "A")
        self.assertEqual(xlsx_col(26), "AA")
        self.assertEqual(xlsx_cell_line("T", 40, 1, ["Allgemeine Psychiatrie", "57090", "7227"]),
                         "[T!B41] Allgemeine Psychiatrie = 57090")


class SeriesLabelTests(unittest.TestCase):
    def test_series_prefix_labels_distinct(self):
        a, b, c = build_site.mlabel("wb_hidden"), build_site.mlabel("bagw_homeless_year"), build_site.mlabel("fb534_range_low")
        self.assertIn("Wohnungslosenbericht", a)
        self.assertIn("BAG W", b)
        self.assertIn("534", c)
        self.assertEqual(len({a.split(":")[0], b.split(":")[0], c.split(":")[0]}), 3)



class UnitLabelTests(unittest.TestCase):
    def test_money_units_carry_their_period(self):
        u = build_site.unit_label
        self.assertEqual(u("eur_per_night"), "€ je Nacht")
        self.assertEqual(u("eur_per_day"), "€ je Tag")
        self.assertEqual(u("eur_per_month"), "€ je Monat")
        self.assertEqual(u("EUR/m2/Monat"), "€ je m² / Monat")
        self.assertEqual(u("persons"), "")
        row = {"metric": "x_eur_per_night", "value": 31, "einheit": "eur_per_night"}
        self.assertEqual(build_site.mval(row), "31 € je Nacht")
        self.assertNotEqual(build_site.mval(dict(row, einheit="eur_per_month")), build_site.mval(row))


if __name__ == "__main__":
    unittest.main()
