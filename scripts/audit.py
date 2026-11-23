#!/usr/bin/env python3
"""Plausibility audit of data/atlas.db (read-only). Complements verify.py's hard gates with
warnings a reviewer should look at before a publish. Exit 1 if any PROBLEM is found.

    python3 scripts/audit.py
"""
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "atlas.db"

CHECKS = [
    # (severity, label, SQL returning offending rows; first column is a count or an id)
    ("PROBLEM", "minderjaehrige exceed untergebracht",
     "SELECT geo_ags, berichtsjahr FROM zaehlung WHERE minderjaehrige > untergebracht"),
    ("PROBLEM", "zaehlung.insgesamt set from the untergebracht-only Destatis series",
     "SELECT z.geo_ags, z.berichtsjahr FROM zaehlung z JOIN source s ON s.id=z.source_id WHERE z.insgesamt IS NOT NULL AND s.url LIKE '%22971%'"),
    ("PROBLEM", "metric entity not in the gazetteer",
     "SELECT entity_type, entity_id FROM metric WHERE (entity_type='land' AND entity_id NOT IN (SELECT ags FROM geo_land)) "
     "OR (entity_type='kreis' AND entity_id NOT IN (SELECT ags FROM geo_kreis))"),
    ("PROBLEM", "zaehlung geography not in the gazetteer",
     "SELECT geo_ags, geo_kind FROM zaehlung WHERE (geo_kind='land' AND geo_ags NOT IN (SELECT ags FROM geo_land)) "
     "OR (geo_kind='kreis' AND geo_ags NOT IN (SELECT ags FROM geo_kreis))"),
    ("PROBLEM", "award amounts <= 0", "SELECT foerder_schluessel FROM award WHERE betrag <= 0"),
    ("PROBLEM", "non-EUR award without a stated reason", "SELECT foerder_schluessel FROM award WHERE currency <> 'EUR'"),
    ("WARN", "canonical organisations that share a name_norm across Länder (possible merge; see reports/join_gaps.md)",
     "SELECT name_norm, count(*) FROM org WHERE canonical_org_id IS NULL GROUP BY name_norm HAVING count(DISTINCT land) > 1"),
    ("WARN", "Land sum differs from the Bund figure by more than rounding (16 x 5)",
     "SELECT d.year, d.value, sum(l.value) FROM metric d JOIN metric l ON l.metric=d.metric AND l.year=d.year AND l.entity_type='land' "
     "WHERE d.entity_type='de' AND d.metric='housed_homeless' GROUP BY d.year HAVING abs(d.value - sum(l.value)) > 80"),
    ("WARN", "Kreise without geometry", "SELECT ags FROM geo_kreis WHERE geometry IS NULL"),
    ("WARN", "sources registered by one domain but cited by rows of another",
     "SELECT s.id, s.domain FROM source s JOIN metric m ON m.source_id=s.id GROUP BY s.id HAVING count(DISTINCT s.domain) > 1"),
]


def main() -> int:
    if not DB.exists():
        print("no database")
        return 2
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    bad = 0
    for sev, label, sql in CHECKS:
        try:
            rows = c.execute(sql).fetchall()
        except sqlite3.Error as e:
            print(f"  ERROR    {label}: {e}")
            bad += 1
            continue
        if rows:
            print(f"  {sev:8s} {label}: {len(rows)} · e.g. {rows[:3]}")
            bad += sev == "PROBLEM"
        else:
            print(f"  ok       {label}")
    print("\naudit:", "clean" if not bad else f"{bad} problem group(s)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
