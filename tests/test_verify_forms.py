"""G5/G9 number renderings: whole-euro amounts printed with two decimals. Run: python3 tests/test_verify_forms.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import verify  # noqa: E402


def test_two_decimal_whole_numbers():
    assert "320,00" in verify.forms(320) and "1.320,00" in verify.forms(1320)
    assert verify.spot_hit(320, "Benutzungsgebühr 320,00 € monatlich")
    assert verify.spot_hit(1320, "insgesamt 1.320,00 Euro")
    assert not verify.spot_hit(320.5, "Benutzungsgebühr 320,00 € monatlich")
    assert not verify.spot_hit(320, "Benutzungsgebühr 320,50 €")
    assert not verify.spot_hit(320, "1.320,00 Euro")
    assert verify.spot_hit(320.5, "320,50 €")



def test_unit_glyphs_normalised():
    n = verify.norm
    doc = n("Benutzungsgebühr je qm Wohnfläche 4,68 € monatlich; Garage je m2 2,50 EUR")
    assert n("je m² Wohnfläche 4,68 EUR") in doc        # quote ending/containing m² matches qm, € matches EUR
    assert n("Garage je m² 2,50 €") in doc               # thin space and m2 vs m²
    assert n("4,68€") == n("4,68 EUR") == "4,68 EUR"
    assert n("je m² Nutzfläche") not in doc               # wording still has to match
    assert n("Bequem") == "Bequem" and n("qmx") == "qmx"  # no substitution inside words
    assert not any(c.isdigit() for c in n("m²"))          # no digit introduced for G5 number search



def test_dash_whole_euros():
    assert verify.spot_hit(414, "Benutzungsgebühr 414,- € monatlich")
    assert verify.spot_hit(5, "Gebühr/Tag 5,-- EUR")
    assert verify.spot_hit(414, "414,–€") and verify.spot_hit(1414, "1.414,- Euro")
    assert verify.spot_hit(414, verify.norm("414,-\u00a0€"))
    assert not verify.spot_hit(414.5, "414,- €")
    assert not verify.spot_hit(14, "414,- €") and not verify.spot_hit(41, "414,- €")
    assert verify.spot_hit(68878046.19, "2024    68 878 046,19 Euro        44 383 556,73 Euro")
    assert not verify.spot_hit(878046.19, "2024    68 878 046,19 Euro")


if __name__ == "__main__":
    test_two_decimal_whole_numbers()
    print("PASS test_two_decimal_whole_numbers")
    test_unit_glyphs_normalised()
    print("PASS test_unit_glyphs_normalised")
    test_dash_whole_euros()
    print("PASS test_dash_whole_euros")
