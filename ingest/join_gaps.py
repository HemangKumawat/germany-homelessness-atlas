"""reports/join_gaps.md: what the joins between sources leave open (org level and published roles only).

Written by ingest.run after every run and on demand:  python3 -m scripts.join_gaps [--db X.db] [--stdout]
"""
from __future__ import annotations

import sqlite3
from collections import defaultdict
from pathlib import Path

from ingest import orglink

ROOT = Path(__file__).resolve().parent.parent
REPORT = ROOT / "reports" / "join_gaps.md"
FUZZY_MIN = 0.90          # name similarity for a same-Land, same-legal-form duplicate candidate
#                           (pairs holding different numbers in the same register are not candidates)
LIST_MAX = 200


def _t(conn) -> set[str]:
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def compute(conn) -> dict:
    g = orglink.Graph(conn)
    tabs = _t(conn)
    canon = g.canonical_ids()
    members = g.members()
    hard = g.hard_index()
    gk = {c: g.group_keys(c) for c in canon}
    out = {"orgs": len(g.orgs), "canonical": len(canon), "aliases": len(g.orgs) - len(canon)}

    # 1. canonical orgs with awards but no register id (court register, Berlin ZUWDB id, Lobbyregister, BA Nr.)
    aw = defaultdict(lambda: [0, 0.0])
    for oid, n, s in conn.execute("SELECT org_id, count(*), coalesce(sum(betrag),0) FROM award WHERE org_id IS NOT NULL GROUP BY 1"):
        c = g.canon(oid)
        if c is not None:
            aw[c][0] += n
            aw[c][1] += s
    no_reg = []
    for c, (n, s) in sorted(aw.items(), key=lambda x: (-x[1][0], x[0])):
        keys = gk.get(c, set())
        if not any(orglink.method_for_key(k) == "register_id" for k in keys):
            o = g.orgs[c]
            no_reg.append(dict(id=c, name=o["name"], land=o["land"], awards=n, total=s,
                               ust=any(k.startswith("UST:") for k in keys), system=orglink.source_system(o["source_url"], o["domain"])))
    out["awards_no_register"] = no_reg

    # 2. Kreise / Gemeinden / Länder with counts but no population (geo.einwohner or a metric 'einwohner')
    pop = defaultdict(set)
    for et, eid, y in conn.execute("SELECT entity_type, entity_id, year FROM metric WHERE metric IN ('einwohner', "
                                   "'einwohner_gebietsstand')"):
        pop[(et, eid)].add(y)
    geo_gaps = {}
    for kind, table in (("land", "geo_land"), ("kreis", "geo_kreis"), ("gemeinde", "geo_gemeinde")):
        if table not in tabs:
            continue
        names = {a: (n, e) for a, n, e in conn.execute(f"SELECT ags, name, einwohner FROM {table}")}
        counted = defaultdict(set)
        if "zaehlung" in tabs:
            for a, y in conn.execute("SELECT geo_ags, berichtsjahr FROM zaehlung WHERE geo_kind=?", (kind,)):
                counted[a].add(("zaehlung", y))
        for a, m, y in conn.execute("SELECT entity_id, metric, year FROM metric WHERE entity_type=? AND metric NOT IN ('einwohner', 'einwohner_gebietsstand')", (kind,)):
            counted[a].add(("metric", y))
        none, missing_year = [], []
        for a, cs in sorted(counted.items()):
            name, einw = names.get(a, (None, None))
            if einw is None and not pop.get((kind, a)):
                none.append(dict(ags=a, name=name, counts=len(cs), in_gazetteer=a in names))
            else:
                ys = sorted({y for src, y in cs if src == "zaehlung" and y})
                have = pop.get((kind, a), set())
                lack = [y for y in ys if einw is None and (y - 1) not in have and y not in have]
                if lack:
                    missing_year.append(dict(ags=a, name=name, years=lack))
        geo_gaps[kind] = dict(no_population=none, zaehlung_years_without_population=missing_year)
    out["geo"] = geo_gaps

    # 3. org_person rows with no valid org link (missing or alias org) — no person names in this report
    bad_people = []
    for pid, oid, bez, fn, rk in conn.execute("SELECT id, org_id, org_bezeichnung, funktion, rollenklasse FROM org_person"):
        if oid not in g.orgs:
            bad_people.append(dict(id=pid, org_id=oid, org=bez, funktion=fn, why="org missing"))
        elif not g.is_canonical(oid):
            bad_people.append(dict(id=pid, org_id=oid, org=bez, funktion=fn, why=f"alias of #{g.orgs[oid]['canonical_org_id']}"))
    out["people_unlinked"] = bad_people

    # 4. duplicate canonical-org candidates
    dup_hard = [dict(key=k, orgs=sorted(cs)) for k, cs in sorted(hard.items()) if len(cs) > 1]
    loose = defaultdict(set)
    for c in canon:
        for k in gk[c]:
            lk = orglink.loose_register(k)
            if lk:
                loose[lk].add(c)
    dup_loose = [dict(key=k, orgs=sorted(cs)) for k, cs in sorted(loose.items()) if len(cs) > 1]
    by_land = defaultdict(list)
    for c in canon:
        o = g.orgs[c]
        by_land[o["land"]].append((c, o["name_norm"], orglink.legal_kind(o["name"], o["legal_form"])))
    fuzzy = []
    for land, rows in by_land.items():
        if land is None:
            continue
        for i in range(len(rows)):
            for j in range(i + 1, len(rows)):
                a, b = rows[i], rows[j]
                if a[2] != b[2] or not a[1] or not b[1]:
                    continue
                if abs(len(a[1]) - len(b[1])) > 0.2 * max(len(a[1]), len(b[1])) and not (a[1] in b[1] or b[1] in a[1]):
                    continue
                sa, sb = defaultdict(set), defaultdict(set)
                for k in gk[a[0]]:
                    sa[k.split(":", 1)[0]].add(k)
                for k in gk[b[0]]:
                    sb[k.split(":", 1)[0]].add(k)
                if any(not (sa[x] & sb[x]) for x in set(sa) & set(sb)):
                    continue                     # different numbers in the same register: different entities
                sim = orglink.similarity(a[1], b[1])
                if sim >= FUZZY_MIN:
                    fuzzy.append(dict(a=a[0], b=b[0], land=land, kind=a[2], sim=round(sim, 3)))
    same_name = defaultdict(list)
    for c in canon:
        same_name[g.orgs[c]["name_norm"]].append(c)
    cross = [dict(name_norm=n, orgs=sorted(cs)) for n, cs in sorted(same_name.items()) if len(cs) > 1 and n]
    out["dup_hard"], out["dup_loose"], out["dup_fuzzy"], out["dup_same_name"] = dup_hard, dup_loose, fuzzy, cross

    # 5. fuzzy-only links awaiting review
    out["fuzzy_links"] = [dict(kind=k, key=key, org_id=oid, name=nm, conf=cf, note=nt) for k, key, oid, nm, cf, nt in conn.execute(
        "SELECT record_kind, record_key, org_id, record_name, confidence, note FROM org_link "
        "WHERE flagged=1 AND reviewed=0 ORDER BY confidence, record_kind, record_key")] if "org_link" in tabs else []
    out["links_by_method"] = dict(conn.execute("SELECT method, count(*) FROM org_link GROUP BY 1").fetchall()) if "org_link" in tabs else {}
    out["merged"] = [dict(alias=a, canonical=c, method=m, note=n) for a, c, m, n in conn.execute(
        "SELECT o.id, o.canonical_org_id, l.method, l.note FROM org o LEFT JOIN org_link l ON l.record_kind='org' "
        "AND l.record_key=CAST(o.id AS TEXT) WHERE o.canonical_org_id IS NOT NULL ORDER BY o.canonical_org_id, o.id")] if g.v5 else []
    out["ust_conflicts"] = [x for x in orglink.award_conflicts(conn, g) if x["method"] != "register_id"]
    out["_g"] = g
    return out


def headline(d: dict) -> str:
    geo = d["geo"]
    return (f"{d['canonical']} canonical orgs ({d['aliases']} alias rows); {len(d['awards_no_register'])} with awards but no register id; "
            f"Kreise {len(geo.get('kreis', {}).get('no_population', []))} / Gemeinden {len(geo.get('gemeinde', {}).get('no_population', []))} "
            f"with counts but no population; {len(d['people_unlinked'])} org_person rows without a valid org; "
            f"duplicate candidates hard {len(d['dup_hard'])} / court-unknown {len(d['dup_loose'])} / fuzzy {len(d['dup_fuzzy'])} / "
            f"same name {len(d['dup_same_name'])}; {len(d['fuzzy_links'])} fuzzy links awaiting review")


def render(d: dict, when: str) -> str:
    g = d["_g"]
    nm = lambda i: f"#{i} {g.orgs[i]['name']}" if i in g.orgs else f"#{i} (missing)"  # noqa: E731
    cell = lambda s: str(s if s is not None else "").replace("|", "\\|").replace("\n", " ")  # noqa: E731
    geo = d["geo"]
    L = ["# Join gaps", "", f"Generated {when} from data/atlas.db (`python3 -m scripts.join_gaps`; also after every ingest run).",
         "Organisation-level data and published roles only: no person names, no addresses.", "",
         "| check | count |", "|---|---|",
         f"| orgs (rows) / canonical / alias rows | {d['orgs']} / {d['canonical']} / {d['aliases']} |",
         f"| org_link rows by method | {', '.join(f'{k} {v}' for k, v in sorted(d['links_by_method'].items())) or '0'} |",
         f"| canonical orgs with awards but no register id | {len(d['awards_no_register'])} |"]
    for kind in ("land", "kreis", "gemeinde"):
        if kind in geo:
            L.append(f"| {kind}: with zaehlung/metric counts but no population | {len(geo[kind]['no_population'])} |")
            L.append(f"| {kind}: zaehlung years without population (Y or Y-1) | {len(geo[kind]['zaehlung_years_without_population'])} |")
    L += [f"| org_person rows without a valid org link | {len(d['people_unlinked'])} |",
          f"| duplicate candidates: same hard id on >1 canonical org | {len(d['dup_hard'])} |",
          f"| duplicate candidates: same register number, court differs or not stated | {len(d['dup_loose'])} |",
          f"| duplicate candidates: name similarity ≥ {FUZZY_MIN} + same Land + same legal form | {len(d['dup_fuzzy'])} |",
          f"| duplicate candidates: same normalised name, different Land | {len(d['dup_same_name'])} |",
          f"| fuzzy (name-only) links awaiting review | {len(d['fuzzy_links'])} |",
          f"| awards whose USt-IdNr belongs to another canonical org (VAT group? review) | {len(d['ust_conflicts'])} |", ""]

    def section(title, rows, head, fmt):
        L.extend([f"## {title} ({len(rows)})", ""])
        if not rows:
            L.extend(["None.", ""])
            return
        L.extend(["| " + " | ".join(head) + " |", "|" + "---|" * len(head)])
        L.extend("| " + " | ".join(cell(x) for x in fmt(r)) + " |" for r in rows[:LIST_MAX])
        if len(rows) > LIST_MAX:
            L.append(f"| … {len(rows) - LIST_MAX} more |" + " |" * (len(head) - 1))
        L.append("")

    section("Same hard id on more than one canonical org (G11a fails on these)", d["dup_hard"], ["hard id", "orgs"],
            lambda r: [r["key"], "; ".join(nm(i) for i in r["orgs"])])
    section("Orgs with awards but no register id", d["awards_no_register"], ["org", "Land", "source system", "awards", "sum EUR", "USt-IdNr"],
            lambda r: [nm(r["id"]), r["land"], r["system"], r["awards"], f"{r['total']:,.0f}".replace(",", "."), "yes" if r["ust"] else "no"])
    for kind in ("land", "kreis", "gemeinde"):
        if kind in geo:
            section(f"{kind.capitalize()}: counts but no population", geo[kind]["no_population"], ["AGS", "name", "count rows", "in gazetteer"],
                    lambda r: [r["ags"], r["name"], r["counts"], "yes" if r["in_gazetteer"] else "no"])
            section(f"{kind.capitalize()}: zaehlung years without a population for Y or Y-1", geo[kind]["zaehlung_years_without_population"],
                    ["AGS", "name", "years"], lambda r: [r["ags"], r["name"], ", ".join(map(str, r["years"]))])
    section("org_person rows without a valid org link", d["people_unlinked"], ["row", "org_id", "org as printed", "published function", "why"],
            lambda r: [r["id"], r["org_id"], r["org"], r["funktion"], r["why"]])
    section("Same register number, court differs or not stated (review; never merged automatically)", d["dup_loose"],
            ["register number", "orgs"], lambda r: [r["key"], "; ".join(nm(i) for i in r["orgs"])])
    section(f"Name similarity ≥ {FUZZY_MIN}, same Land and legal form (review)", d["dup_fuzzy"], ["org A", "org B", "Land", "legal form", "similarity"],
            lambda r: [nm(r["a"]), nm(r["b"]), r["land"], r["kind"], r["sim"]])
    section("Same normalised name in different Länder (review)", d["dup_same_name"], ["normalised name", "orgs (Land, ort)"],
            lambda r: [r["name_norm"], "; ".join(f"{nm(i)} ({g.orgs[i]['land'] or '-'}, {g.orgs[i]['ort'] or '-'})" for i in r["orgs"])])
    section("Fuzzy (name-only) links awaiting review", d["fuzzy_links"], ["record", "name in record", "linked to", "confidence", "note"],
            lambda r: [f"{r['kind']} {r['key']}", r["name"], nm(r["org_id"]), r["conf"], r["note"]])
    section("Awards whose recipient USt-IdNr belongs to another canonical org (review; a VAT group shares one number)",
            d["ust_conflicts"], ["award", "name in record", "points to", "USt-IdNr holder"],
            lambda r: [r["key"], r["empfaenger"], nm(r["org_id"]), nm(r["owner"])])
    section("Alias rows merged into a canonical org", d["merged"], ["alias", "canonical", "method", "reason"],
            lambda r: [nm(r["alias"]), nm(r["canonical"]), r["method"], r["note"]])
    return "\n".join(L) + "\n"


def write(conn, path: Path | None = None) -> str:
    from ingest.common import now
    path = path or REPORT
    d = compute(conn)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render(d, now()), encoding="utf-8")
    return headline(d)


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="python3 -m scripts.join_gaps", allow_abbrev=False, description=__doc__)
    ap.add_argument("--db", type=Path, default=ROOT / "data" / "atlas.db")
    ap.add_argument("--out", type=Path, default=None, help="default reports/join_gaps.md")
    ap.add_argument("--stdout", action="store_true", help="print the report instead of writing it")
    a = ap.parse_args(argv)
    conn = sqlite3.connect(f"file:{a.db}?mode=ro", uri=True)
    if a.stdout:
        from ingest.common import now
        print(render(compute(conn), now()))
    else:
        print(write(conn, a.out))
        print(f"wrote {a.out or REPORT}")
    conn.close()
    return 0
