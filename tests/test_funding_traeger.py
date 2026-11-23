"""Offline tests for ingest/domains/funding_traeger.py (in-memory SQLite from ingest/schema.sql, no network).
Run: python3 -m pytest -q tests/test_funding_traeger.py   or   python3 tests/test_funding_traeger.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ingest.domains import funding_traeger as ft  # noqa: E402


def test_berlin_zuwendungen():
    ft._test_berlin()


def test_company_id():
    ft._test_company_id()


def test_ted():
    ft._test_ted()


def test_redact_place():
    # Lead: protected-shelter titles never name a street, house number or postcode
    assert ft.redact_place("Betreuungsdienstleistungen Unterkunft Höntroper Str. 99a") == \
        "Betreuungsdienstleistungen Unterkunft [Standort geschützt]"
    assert "Gilly" not in ft.redact_place("GU David-Gilly-Straße 5 und Peter-Huchel-Straße 4")
    assert "14471" not in ft.redact_place("an den Standorten in 14471 und Potsdam")
    assert ft.redact_place("bis zu 170 Bettplätzen für wohnungslose Frauen") == "bis zu 170 Bettplätzen für wohnungslose Frauen"


def test_cli_safety():
    import subprocess
    root = Path(__file__).resolve().parent.parent
    def rc(*a):
        return subprocess.run([sys.executable, "-m", "ingest.domains.funding_traeger", *a], cwd=root,
                              capture_output=True, text=True).returncode
    assert rc() == 2                      # no mode: usage, never the atlas.db writer
    assert rc("--bogus") == 2             # unknown flag
    assert rc("--test", "--frobnicate") == 2
    try:
        ft.scratch_db_path(["x", "--selftest", "--db", str(root / "data" / "atlas.db")])
        raise AssertionError("atlas.db accepted")
    except SystemExit:
        pass
    try:
        ft.scratch_db_path(["x", "--selftest", "--db", "/home/x/projects/germany-atlas-lead/data/x.db"])
        raise AssertionError("lead DB accepted")
    except SystemExit:
        pass
    assert ft.scratch_db_path(["x", "--selftest", "--db", "/tmp/fund_scratch.db"]).name == "fund_scratch.db"


def test_malteser_ev_not_on_ggmbh():
    """Lead review (TED 624927-2022 names 'Malteser Hilfsdienst e.V.', Freiburg): the e.V. award must never
    resolve to the gGmbH of the same name (org 162 in the Lead DB), whatever the Land or register."""
    from ingest import common
    conn = ft.memory_conn()
    sid = conn.execute("INSERT INTO source(url, domain, title) VALUES ('https://example.org/t', 'funding_traeger', 't')").lastrowid
    nn = common.name_norm("Malteser Hilfsdienst gGmbH")
    g = conn.execute("INSERT INTO org(name, name_norm, legal_form_norm, land, legal_form, register_id, source_id, currency) "
                     "VALUES ('Malteser Hilfsdienst gGmbH', ?, 'ggmbh', 'BW', 'gGmbH', 'HRB 26997 (AG Köln)', ?, 'EUR')",
                     (nn, sid)).lastrowid
    nn_ev = common.name_norm("Malteser Hilfsdienst e.V.")
    for land, any_land in (("BW", False), ("NW", False), ("BW", True)):
        oid, how = ft.resolve_or_find(conn, "Malteser Hilfsdienst e.V.", nn_ev, land, any_land=any_land)
        assert oid != g, (land, any_land, oid, how)
    oid = ft._ensure_org(conn, "Malteser Hilfsdienst e.V.", nn_ev, "BW", sid)
    assert oid and oid != g
    assert ft._ensure_org(conn, "Malteser Hilfsdienst e.V.", nn_ev, "BW", sid) == oid   # stable on re-run
    assert ft.resolve_or_find(conn, "Malteser Hilfsdienst gGmbH", nn, "BW")[0] == g


if __name__ == "__main__":
    test_cli_safety(); print("PASS test_cli_safety")
    test_redact_place(); print("PASS test_redact_place")
    test_berlin_zuwendungen(); print("PASS test_berlin_zuwendungen")
    test_ted(); print("PASS test_ted")
    test_company_id(); print("PASS test_company_id")
    test_malteser_ev_not_on_ggmbh(); print("PASS test_malteser_ev_not_on_ggmbh")
