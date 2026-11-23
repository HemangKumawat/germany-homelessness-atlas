"""G7: an org with a court-register number is a legal entity whatever its name sounds like; a person-like
org name WITHOUT one still fails. Run: python3 tests/test_verify_g7.py"""
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import verify  # noqa: E402


def _db(td):
    p = Path(td) / "g7.db"
    c = sqlite3.connect(p)
    c.executescript((ROOT / "ingest" / "schema.sql").read_text(encoding="utf-8"))
    c.execute("INSERT INTO source(id, domain, url, title, license) VALUES (1,'t','https://example.invalid/a','a','x')")
    c.execute("INSERT INTO org(id, name, name_norm, land, source_id) VALUES (1,'Neue Chance','NEUE CHANCE','BE',1)")
    c.execute("INSERT INTO org_register(org_id, scheme, court, number, raw, source_id) "
              "VALUES (1,'BE_ZUWDB','','hrb_115888','hrb_115888',1)")
    c.execute("INSERT INTO org(id, name, name_norm, land, source_id) VALUES (2,'Hans Becker','HANS BECKER','BE',1)")
    c.execute("INSERT INTO org(id, name, name_norm, land, source_id) VALUES (3,'Erika Brandt','ERIKA BRANDT','BE',1)")
    c.execute("INSERT INTO org_register(org_id, scheme, court, number, raw, source_id) "
              "VALUES (3,'USt-IdNr','','DE123456789','DE123456789',1)")
    c.commit()
    c.close()
    return p


def test_g7_register_exemption():
    with tempfile.TemporaryDirectory() as td:
        rep = verify.verify(_db(td), quiet_stats=True)
        g7 = rep.bad.get("G7 people", [])
        assert not any("'Neue Chance'" in p for p in g7), g7   # HRB via the Berlin id: exempt
        assert any("'Hans Becker'" in p for p in g7), g7        # no register id: still fails
        assert any("'Erika Brandt'" in p for p in g7), g7       # a VAT id is not a court register


def test_g7_person_must_be_in_source():
    """org_person is the only place for names, and only with a source whose archived text names the person."""
    with tempfile.TemporaryDirectory(dir=ROOT / "data") as td:
        p = _db(td)
        doc = Path(td) / "imp.txt"
        doc.write_text("Impressum. Vorstand: Dr. Anna Beispiel. Geschäftsführung: Otto Muster", encoding="utf-8")
        rel = str(doc.relative_to(ROOT))
        c = sqlite3.connect(p)
        c.execute("UPDATE source SET local_path=?, text_path=?, sha256=? WHERE id=1",
                  (rel, rel, __import__("hashlib").sha256(doc.read_bytes()).hexdigest()))
        ins = ("INSERT INTO org_person(org_id, funktionstraeger, funktionstraeger_norm, funktion, quote, source_id) "
               "VALUES (1,?,?,?,?,1)")
        c.execute(ins, ("Dr. Anna Beispiel", "ANNA BEISPIEL", "Vorstand", "Vorstand: Dr. Anna Beispiel"))
        c.execute(ins, ("Otto Muster", "OTTO MUSTER", "Geschäftsführung", None))
        c.execute(ins, ("Erika Erfunden", "ERIKA ERFUNDEN", "Vorstand", None))           # not in the document
        c.execute(ins, ("Otto Muster", "OTTO MUSTER", "Vorstand", "Vorstand: Otto Muster"))  # quote not verbatim
        c.commit()
        c.close()
        g7 = verify.verify(p, quiet_stats=True).bad.get("G7 people", [])
        assert not any("Anna Beispiel" in x for x in g7), g7
        assert any("Erfunden" in x and "not in archived source" in x for x in g7), g7
        assert any("quote not verbatim" in x for x in g7), g7
        assert sum("Otto Muster" in x for x in g7) == 1, g7
        assert any("'Hans Becker'" in x for x in g7), g7          # org-name rule unchanged


if __name__ == "__main__":
    test_g7_register_exemption()
    print("PASS test_g7_register_exemption")
    test_g7_person_must_be_in_source()
    print("PASS test_g7_person_must_be_in_source")
