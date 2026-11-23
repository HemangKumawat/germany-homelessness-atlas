"""Offline tests for ingest/domains/funding_officers.py (in-memory SQLite from ingest/schema.sql, no network)."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from ingest.domains import funding_officers as fo  # noqa: E402


def test_lobbyregister():
    fo._test_lobbyregister()


def test_impressum():
    fo._test_impressum()


def test_rollenklasse():
    assert fo.rollenklasse("Kaufmännische Vorständin") == "vorstand"
    assert fo.rollenklasse("Geschäftsführerin") == "geschaeftsfuehrung"
    assert fo.rollenklasse("Vorsitzende des Präsidiums") == "praesidium"
    assert fo.rollenklasse("Vizepräsdient") == "vorstand" and fo.rollenklasse("Schatzmeister") == "vorstand"
    assert fo.rollenklasse("Generalsekretär") == "geschaeftsfuehrung"


def test_legal_kind_and_namesake_quote():
    assert fo.legal_kind("Malteser Hilfsdienst e.V.") == "ev" and fo.legal_kind("Malteser Hilfsdienst gGmbH") == "gmbh"
    assert fo.legal_kind("Tafel Deutschland") is None
    raw = ('{"donors":[{"lastName":"Schwarz","firstName":"Otto"}],"legalRepresentatives":[{"lastName":"Schwarz",'
           '"firstName":"Hanna","function":"Vorstand","contactDetails":{}}]}')
    q = fo._raw_quote(raw, {"lastName": "Schwarz", "firstName": "Hanna", "function": "Vorstand"})
    assert q == '"lastName":"Schwarz","firstName":"Hanna","function":"Vorstand"', q
    e = {"lobbyistIdentity": {"identity": "ORGANIZATION", "name": "Allianz pro Schiene e.V."},
         "activitiesAndInterests": {"activityDescription": "Mitglieder: Verbände und die Bahnhofsmission Deutschland"}}
    assert fo.lr_relevant(e, set()) is None


def test_cli_safety():
    def rc(*a):
        return subprocess.run([sys.executable, "-m", "ingest.domains.funding_officers", *a], cwd=ROOT,
                              capture_output=True, text=True).returncode
    assert rc() == 2 and rc("--bogus") == 2 and rc("--test", "--x") == 2
    for bad in (str(ROOT / "data" / "atlas.db"), "/home/x/projects/germany-atlas-lead/data/a.db"):
        try:
            fo.scratch_db_path(["x", "--db", bad])
            raise AssertionError(bad)
        except SystemExit:
            pass


def test_robots_gate():
    fo._test_robots_gate()


def test_org_facts_only():
    fo._test_org_facts_only()


def test_protected_traeger():
    fo._test_protected_traeger()


def test_seed_quotes_contain_label():
    fo._test_seed_quotes_contain_label()


def test_no_ust_id():
    fo._test_no_ust_id()


def test_lr_retry():
    fo._test_lr_retry()


def test_itz():
    fo._test_itz()


def test_soft_hyphen():
    fo._test_soft_hyphen()


def test_register_links():
    fo._test_register_links()


def test_robots_first():
    fo._test_robots_first()


if __name__ == "__main__":
    for t in (test_rollenklasse, test_legal_kind_and_namesake_quote, test_lobbyregister, test_impressum, test_cli_safety,
              test_robots_gate, test_org_facts_only, test_protected_traeger,
              test_seed_quotes_contain_label, test_no_ust_id, test_lr_retry, test_itz, test_soft_hyphen, test_register_links, test_robots_first):
        t()
        print("PASS", t.__name__)
