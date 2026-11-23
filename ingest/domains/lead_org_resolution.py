"""Lead run: org entity resolution (schema 5). Writes only through `python3 -m ingest.run lead_org_resolution`.

    python3 -m ingest.run lead_org_resolution [--cfg '{"merge": false}']

1. backfill org_link for every org row, org_register row and award from stored data (no fetches);
2. merge canonical orgs that share a hard id (register court+number, Berlin ZUWDB id, Lobbyregister number,
   BA Träger-Nr, USt-IdNr, LEI, QID). Canonical = the org that owns the org_register row for that id, else the
   one with most references, else the lowest id. Alias rows are kept; references are re-pointed;
3. apply the reviewed manual merges in docs/org_merges.tsv (each row names both orgs by id AND name_norm, so a
   different database cannot be merged by accident);
4. re-point awards whose recipient register id (not a USt-IdNr, which VAT groups share) belongs to a different canonical org than the one a name match chose;
5. sync org_link again. Name matches are never merged: they stay flagged links in reports/join_gaps.md;
6. apply the Lead's decisions on flagged links in docs/link_reviews.tsv (confirm -> manual/origin, unflagged;
   reject -> link removed and the award left unlinked; unsure -> stays flagged). Evidence per line is in
   reports/fuzzy_review.md.
"""
from __future__ import annotations

import sys

from ingest import common, orglink

DOMAIN = "lead_org_resolution"


def run(conn, cfg: dict) -> dict:
    orglink.ensure_schema(conn)
    notes = []
    s0 = orglink.sync(conn)
    notes.append(f"backfill org_link {s0}")
    if cfg.get("merge", True):
        plan = orglink.plan_hard_merges(conn)
        for p in plan:
            orglink.merge(conn, p["alias"], p["canonical"], method=p["method"], confidence=1.0, id_value=p["key"],
                          reason=f"same hard id {p['key']} as #{p['canonical']} (deterministic hard-id merge)")
        notes.append(f"hard-id merges {len(plan)}: " + "; ".join(f"{p['alias']}->{p['canonical']} {p['key']}" for p in plan))
        manual, skipped = [], []
        for m in orglink.read_merges():
            a = conn.execute("SELECT name_norm FROM org WHERE id=?", (m["alias"],)).fetchone()
            c = conn.execute("SELECT name_norm FROM org WHERE id=?", (m["canonical"],)).fetchone()
            if not a or not c or a[0] != m["alias_norm"] or c[0] != m["canonical_norm"]:
                skipped.append(m["alias"])
                continue
            if orglink.canonical(conn, m["alias"]) == orglink.canonical(conn, m["canonical"]):
                continue
            orglink.merge(conn, m["alias"], m["canonical"], method="manual", confidence=0.95,
                          reason=f"Lead review (docs/org_merges.tsv): {m['reason']}")
            manual.append(f"{m['alias']}->{m['canonical']}")
        notes.append(f"manual merges {len(manual)}: {', '.join(manual)}" + (f"; skipped (name_norm mismatch) {skipped}" if skipped else ""))
        fixed = []
        for x in [x for x in orglink.award_conflicts(conn) if x["method"] == "register_id"]:
            conn.execute("UPDATE award SET org_id=? WHERE id=?", (x["owner"], x["award_id"]))
            fixed.append(f"{x['key']} {x['org_id']}->{x['owner']}")
        notes.append(f"award re-pointed to the holder of its recipient id {len(fixed)}: {', '.join(fixed)}")
    s1 = orglink.sync(conn)
    notes.append(f"org_link {s1}")
    if cfg.get("reviews", True):
        rv = orglink.apply_link_reviews(conn)
        sk = rv.pop("skipped_keys")
        notes.append(f"link reviews {rv}" + (f"; skipped (link gone, other org or name_norm mismatch) {sk[:10]}"
                                               f"{' …' if len(sk) > 10 else ''}" if sk else ""))
    return {"rows": conn.execute("SELECT count(*) FROM org_link").fetchone()[0], "notes": " | ".join(notes)}


if __name__ == "__main__":
    sys.exit(common.no_direct_run(DOMAIN))
