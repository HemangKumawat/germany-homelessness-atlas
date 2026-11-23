#!/usr/bin/env python3
"""Build the static wiki + map into site/ (original implementation; atomic swap, shrink guard).

    python3 scripts/build_site.py [--force]

Read-only on data/atlas.db. Every number links to its source page (URL, retrieval date, licence,
sha256 of the locally archived copy (never republished), and the quote/locator where one is stored). Destatis 22971 figures are
labelled 'untergebracht (sheltered)' and are never presented as total homelessness.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import shutil
import sqlite3
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "atlas.db"
OUT, STAGE, PREV = ROOT / "site", ROOT / "site.staging", ROOT / "site.prev"
SRC = ROOT / "site_src"
MAX_COPY = 3_000_000
e = lambda s: html.escape("" if s is None else str(s))  # noqa: E731
_EURO_GLYPH = re.compile(r"(?<=\d)(\s?)‡")


def dq(s) -> str:
    """A stored verbatim quote for display: the stored text stays as archived (G9), but the pdftotext euro glyph
    ‡ after a number (Bremen Drs 19/894) is shown as €."""
    return e(_EURO_GLYPH.sub(r"\1€", "" if s is None else str(s)))



METRIC_LABEL = {
    "housed_homeless": "Untergebrachte wohnungslose Personen (untergebracht / sheltered; not total homelessness)",
    "housed_homeless__male": "… männlich", "housed_homeless__female": "… weiblich",
    "housed_homeless__sex_unknown": "… Geschlecht unbekannt", "housed_homeless__german": "… deutsche Staatsangehörigkeit",
    "housed_homeless__foreign": "… ausländische Staatsangehörigkeit", "housed_homeless__age_lt18": "… unter 18 Jahre",
    "housed_homeless__age_18_24": "… 18–24 Jahre", "housed_homeless__age_25_39": "… 25–39 Jahre",
    "housed_homeless__age_40_59": "… 40–59 Jahre", "housed_homeless__age_60plus": "… 60 Jahre und älter",
    "housed_homeless__age_unknown": "… Alter unbekannt",
}
METRIC_LABEL.update({
    # two different psychiatric-bed series: never merge them into one line
    "psychiatric_care_hospital_beds": "Betten in der psychiatrischen Versorgung – Reihe BT-Drs 21/6258, Anlage 1 (2014–2023)",
    "hospital_beds_allgemeine_psychiatrie": "Aufgestellte Betten Allgemeine Psychiatrie – Destatis 23111-07, 2024 (separate Reihe, nicht mit BT-Drs 21/6258 vergleichbar)",
    "hospital_beds_kinder_jugendpsychiatrie": "Aufgestellte Betten Kinder- und Jugendpsychiatrie – Destatis 23111-07, 2024 (separate Reihe)",
    "hospital_beds_psychosomatik": "Aufgestellte Betten Psychosomatik/Psychotherapie – Destatis 23111-07, 2024 (separate Reihe)",
    "jva_release_homeless_data_available": "Entlassungen aus der Haft in Wohnungslosigkeit – Datenlage",
})
SERIES = [  # national estimate series: shown side by side, each labelled, never merged or summed
    ("wb_", "Wohnungslosenbericht der Bundesregierung (Hochrechnung, Stichtag 31.01.)",
     ["wb_total_homeless", "wb_housed", "wb_unsheltered", "wb_hidden"]),
    ("bagw_", "BAG Wohnungslosenhilfe e.V. – Hochrechnung",
     ["bagw_homeless_year", "bagw_homeless_0630", "bagw_unsheltered_year"]),
    ("fb534_", "BMAS Forschungsbericht 534 (GISS), Schätzung", None),
]
METRIC_LABEL.update({
    "wb_total_homeless": "wohnungslose Personen insgesamt (untergebracht + verdeckt + ohne Unterkunft)",
    "wb_housed": "untergebrachte Wohnungslose", "wb_unsheltered": "ohne Unterkunft (Straße)",
    "wb_hidden": "verdeckt wohnungslos",
    "bagw_homeless_year": "wohnungslose Personen im Jahresverlauf", "bagw_homeless_0630": "wohnungslose Personen am 30.06.",
    "bagw_unsheltered_year": "ohne Unterkunft (Straße), Jahresverlauf",
})


def series_of(metric: str):
    return next(((pfx, name) for pfx, name, _ in SERIES if metric.startswith(pfx)), (None, None))


def mlabel(metric: str) -> str:
    _, name = series_of(metric)
    lab = METRIC_LABEL.get(metric, metric)
    return f"{name}: {lab}" if name else lab


EST_BADGE = "<span class=est title='Schätzung / estimate (is_est=1)'>† Schätzung</span> "
NO_DATA = "<span class='dim'>keine Daten (no data)</span>"


def is_flag(metric: str | None, unit: str | None) -> bool:
    return (unit or "") == "flag" or (metric or "").endswith("_data_available")


_UNIT_WORD = {"night": "Nacht", "nacht": "Nacht", "day": "Tag", "tag": "Tag", "hafttag": "Hafttag",
              "month": "Monat", "monat": "Monat", "year": "Jahr", "jahr": "Jahr", "m2": "m²", "m²": "m²", "qm": "m²",
              "person": "Person", "platz": "Platz", "place": "Platz", "bettplatz": "Bettplatz", "bed": "Bettplatz",
              "schlafplatz": "Schlafplatz", "haftplatz": "Haftplatz", "unit": "Unterkunft", "unterkunft": "Unterkunft"}


_COUNT_UNIT = {"beds": "Betten", "day_places": "Plätze (teilstationär)", "beds_or_places": "Betten oder Plätze"}


def unit_label(unit: str | None) -> str:
    """Money units render with their reference period spelt out (€ je Nacht / Tag / Monat), never bare,
    so nightly, daily and monthly rates cannot be read as one series. Count units render without a suffix."""
    u = (unit or "").strip()
    low = u.lower()
    if low in ("eur", "euro"):
        return "€"
    if low in ("tsd_eur", "tsd. eur", "teur"):
        return "Tsd. €"
    if low in ("percent", "pct", "%"):
        return "%"
    if low in _COUNT_UNIT:
        return _COUNT_UNIT[low]
    m = re.match(r"(?i)^eur(?:_per_|/)(.+)$", u)
    if not m:
        return ""
    parts = [p_ for p_ in re.split(r"_per_|/|_", m.group(1)) if p_]
    return "€ je " + " / ".join(_UNIT_WORD.get(p_.lower(), p_) for p_ in parts)


def mval(r) -> str:
    """A metric cell: availability flags render as 'no data' / 'data available', never as 0 or 1;
    money values carry their unit and reference period."""
    keys = r.keys() if hasattr(r, "keys") else r
    unit = r["einheit"] if "einheit" in keys else None
    if is_flag(r["metric"], unit):
        if r["value"] is None or float(r["value"]) == 0:
            return NO_DATA
        return "Daten vorhanden"
    lab = unit_label(unit) if r["value"] is not None else ""
    return fmt(r["value"]) + (f"\u00a0{lab}" if lab else "")


ZAEHL_LABEL = {"untergebracht": "untergebracht (sheltered, Destatis WoBerichtsG)", "ohne_unterkunft": "ohne Unterkunft (rough sleeping)",
               "verdeckt": "verdeckt wohnungslos (hidden)", "insgesamt": "insgesamt (all forms)",
               "minderjaehrige": "darunter unter 18 Jahre", "haushalte": "Haushalte"}
LEVEL = {"bund": "Bund", "land": "Land", "kreis": "Kreis / kreisfreie Stadt", "gemeinde": "Gemeinde"}


def fmt(v) -> str:
    if v is None:
        return "–"
    v = float(v)
    if v.is_integer():
        return f"{int(v):,}".replace(",", "\u202f")
    return f"{v:,.2f}".replace(",", "\u202f").replace(".", ",")


def rel(depth: int) -> str:
    return "." if depth == 0 else "/".join([".."] * depth)


def page(title, body, depth, crumbs=(), head="", tail=""):
    b = rel(depth)
    bc = " › ".join([f'<a href="{b}/index.html">atlas</a>'] + [f'<a href="{b}/{u}">{e(t)}</a>' if u else e(t) for t, u in crumbs])
    return f"""<!doctype html><html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(title)} · Germany Atlas</title><link rel="stylesheet" href="{b}/assets/atlas.css">{head}</head>
<body data-base="{b}"><header><a class="brand" href="{b}/index.html">germany-atlas <small>Wohnungslosigkeit-Atlas</small></a>
<nav><a href="{b}/places.html">places</a><a href="{b}/orgs.html">orgs</a><a href="{b}/people.html">people</a><a href="{b}/laws.html">laws</a><a href="{b}/facilities.html">facilities</a><a href="{b}/docs.html">docs</a><a href="{b}/media.html">media</a><a href="{b}/sources.html">sources</a></nav>
<input id="q" type="search" placeholder="/ search" autocomplete="off" aria-label="Search"><div id="results" role="listbox"></div></header>
<main><p class="crumbs dim">{bc}</p>{body}</main>
<footer>Public records only. Named people appear only in published roles. Protected shelters are shown without address or map pin.
<span class="est">†</span> estimate (is_est=1) · <span class="dim">~</span> rounded by the publisher · <kbd>?</kbd> keys ·
Karten: © <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>-Mitwirkende, Grenzen © <a href="https://www.bkg.bund.de">BKG</a> (2026) <a href="https://www.govdata.de/dl-de/by-2-0">dl-de/by-2-0</a> ·
Zahlen: Statistisches Bundesamt (Destatis) u. a., siehe <a href="{b}/sources.html">sources</a> · built {time.strftime('%Y-%m-%d %H:%M %Z')}</footer>
<div id="help"><div class="box"><b>Keys</b><br><kbd>/</kbd> search · <kbd>↑↓</kbd> pick · <kbd>Enter</kbd> open · <kbd>Esc</kbd> close<br>
<kbd>g h</kbd> home · <kbd>g p</kbd> places · <kbd>g o</kbd> orgs · <kbd>g l</kbd> laws · <kbd>g s</kbd> sources<br>
map: <kbd>l</kbd> Länder · <kbd>k</kbd> Kreise · <kbd>+</kbd>/<kbd>-</kbd> zoom · <kbd>0</kbd> reset</div></div>
{tail}<script src="{b}/assets/app.js"></script></body></html>"""


def fmt1(v) -> str:
    """One decimal, German comma (computed rates)."""
    return f"{v:,.1f}".replace(",", "\u202f").replace(".", ",")


CALC = "<span class='calc' title='berechnet beim Seitenbau aus zwei zitierten Zahlen; keine Quellzahl, nicht gespeichert'>berechnet</span>"


def src_link(sid, depth, extra=""):
    return f'<a class="src" href="{rel(depth)}/source/{sid}.html{extra}" title="source #{sid}">[{sid}]</a>'


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    t0 = time.time()
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    q = lambda sql, *x: c.execute(sql, x).fetchall()  # noqa: E731
    if STAGE.exists():
        shutil.rmtree(STAGE)
    for d in ("assets", "data", "place", "org", "person", "law", "source", "facility"):
        (STAGE / d).mkdir(parents=True)
    for f in ("atlas.css", "app.js"):
        shutil.copy(SRC / f, STAGE / "assets" / f)
    shutil.copytree(SRC / "vendor", STAGE / "assets" / "vendor")
    pages, search = 0, []

    def write(path, txt):
        nonlocal pages
        (STAGE / path).write_text(txt, encoding="utf-8")
        pages += 1

    # ---------------------------------------------------------------- places
    places = {}
    for r in q("SELECT code AS ags, name, lat, lon, geometry, source_id FROM geo_country"):
        places[r["ags"]] = dict(r, level="bund", parent=None, bez="Bundesrepublik")
    for r in q("SELECT ags, name, bez, abbr, lat, lon, geometry, source_id, geometry_source_id FROM geo_land"):
        places[r["ags"]] = dict(r, level="land", parent="DE")
    for r in q("SELECT ags, name, bez, kind, land_ags, lat, lon, geometry, source_id, geometry_source_id FROM geo_kreis"):
        places[r["ags"]] = dict(r, level="kreis", parent=r["land_ags"])
    gcols = {x[1] for x in q("PRAGMA table_info(geo_gemeinde)")}
    extra = ", einwohner, flaeche_km2, geometry_source_id" if "geometry_source_id" in gcols else ""
    for r in q(f"SELECT ags, name, kind, kreis_ags, lat, lon, source_id{extra} FROM geo_gemeinde"):
        places[r["ags"]] = dict(r, level="gemeinde", parent=r["kreis_ags"], geometry=None)
    gv_title = q("SELECT s.title FROM geo_gemeinde g JOIN source s ON s.id=g.source_id LIMIT 1")
    m_ = re.search(r"Bevölkerung (\d\d\.\d\d\.\d{4})", gv_title[0][0] if gv_title else "")
    gem_pop_date = m_.group(1) if m_ else None
    if "DE" not in places:
        places["DE"] = {"ags": "DE", "name": "Deutschland", "level": "bund", "parent": None, "geometry": None, "source_id": None}
    kids = defaultdict(list)
    for p in places.values():
        if p.get("parent") in places:
            kids[p["parent"]].append(p)

    # numbers per place
    ent = {"de": "DE", "bund": "DE"}
    land_ags = {x["abbr"]: x["ags"] for x in q("SELECT ags, abbr FROM geo_land")}   # IM rows use Land codes (HH, BE…)
    mrows = defaultdict(list)
    for r in q("SELECT entity_type, entity_id, metric, value, einheit, year, is_est, is_rounded, source_id FROM metric "
               "WHERE entity_type IN ('de','bund','land','kreis','gemeinde') ORDER BY metric, year"):
        key = ent.get(r["entity_type"]) or (land_ags.get(r["entity_id"], r["entity_id"]) if r["entity_type"] == "land" else r["entity_id"])
        mrows[key].append(r)
    pop = {}   # (place key, year) -> 'einwohner' row (Destatis 12411, Stichtag 31.12.)
    for r in q("SELECT entity_type, entity_id, year, value, source_id FROM metric WHERE metric='einwohner'"):
        pop[(ent.get(r["entity_type"]) or r["entity_id"], r["year"])] = r
    # after a Kreis split the old Kreis's 12411 figure on 31.12. still contains the departed city; the population
    # in the boundaries of the following Stichtag (exact sum of official Gemeinde figures) takes precedence
    pop_gs = {}
    for r in q("SELECT entity_type, entity_id, year, value, source_id FROM metric WHERE metric='einwohner_gebietsstand'"):
        pop_gs[(ent.get(r["entity_type"]) or r["entity_id"], r["year"])] = r

    def rate(count, ags, year):
        """Per 100 000 inhabitants, computed here and never stored: count on 31.01.<year> divided by the
        population on 31.12.<year-1> (the evening before the Stichtag), in the boundaries of that Stichtag."""
        p_ = pop_gs.get((ags, year - 1)) or pop.get((ags, year - 1))
        if count is None or not p_ or not p_["value"]:
            return None, None
        return count / p_["value"] * 1e5, p_

    prow = defaultdict(list)
    for r in q("SELECT * FROM zaehlung ORDER BY berichtsjahr"):
        prow[r["geo_ags"]].append(r)

    # choropleth: housed_homeless per year, per level
    choro = defaultdict(lambda: {"land": {}, "kreis": {}})
    for r in q("SELECT entity_type, entity_id, year, value, is_est FROM metric WHERE metric='housed_homeless' "
               "AND entity_type IN ('land','kreis')"):
        choro[str(r["year"])][r["entity_type"]][r["entity_id"]] = {"v": r["value"], "s": fmt(r["value"]), "e": r["is_est"]}
    rates = defaultdict(lambda: {"land": {}, "kreis": {}})
    for y_, lv in list(choro.items()):
        for lvl, d in lv.items():
            for ags, x in d.items():
                v_, _ = rate(x["v"], ags, int(y_))
                if v_ is not None:
                    rates[f"r{y_}"][lvl][ags] = {"v": v_, "s": f"{fmt1(v_)} je 100 000 Einw. (berechnet)", "e": x["e"]}
    for lvl in ("land", "kreis"):
        feats = [{"type": "Feature", "properties": {"ags": p["ags"], "name": p["name"]}, "geometry": json.loads(p["geometry"])}
                 for p in places.values() if p["level"] == lvl and p.get("geometry")]
        (STAGE / "data" / f"geo-{lvl}.json").write_text(json.dumps({"type": "FeatureCollection", "features": feats},
                                                                   separators=(",", ":")), encoding="utf-8")

    def numbers_block(ags, depth):
        out = ""
        pr = prow.get(ags, [])
        if pr:
            years = [r["berichtsjahr"] for r in pr]
            cols = [k for k in ("untergebracht", "minderjaehrige", "ohne_unterkunft", "verdeckt", "insgesamt", "haushalte")
                    if any(r[k] is not None for r in pr)]
            out += "<h2>Counts (Stichtag 31. Januar)</h2><div class='scroll'><table><tr><th></th>" + "".join(f"<th class='n'>{y}</th>" for y in years) + "</tr>"
            for k in cols:
                out += f"<tr><td>{e(ZAEHL_LABEL.get(k, k))}</td>" + "".join(
                    f"<td class='n'>{'<span class=est>†</span>' if r['is_est'] else ''}{fmt(r[k])} {src_link(r['source_id'], depth)}</td>"
                    if r[k] is not None else "<td class='n dim'>–</td>" for r in pr) + "</tr>"
            out += "</table></div><p class='dim'>‘untergebracht’ counts only people housed because they are homeless (Destatis, WoBerichtsG). " \
                   "It excludes rough sleepers and hidden homelessness and is not a total.</p>"
            rr = [(r, *rate(r["untergebracht"], ags, r["berichtsjahr"])) for r in pr]
            rr = [x for x in rr if x[1] is not None]
            if rr:
                out += ("<h2>Je 100 000 Einwohner " + CALC + "</h2><div class='scroll'><table><tr><th>Stichtag</th>"
                        "<th class='n'>untergebracht</th><th class='n'>Einwohner</th><th class='n'>je 100 000 Einw.</th></tr>"
                        + "".join(f"<tr><td>31.01.{r['berichtsjahr']}</td><td class='n'>{fmt(r['untergebracht'])} {src_link(r['source_id'], depth)}</td>"
                                  f"<td class='n'>{fmt(p_['value'])} <span class='dim'>31.12.{p_['year']}"
                                  f"{' · new boundaries, sum of official Gemeinde figures' if (ags, p_['year']) in pop_gs and pop_gs[(ags, p_['year'])] is p_ else ''}"
                                  f"</span> {src_link(p_['source_id'], depth)}</td>"
                                  f"<td class='n'>{CALC} {fmt1(v)}</td></tr>" for r, v, p_ in rr)
                        + "</table></div><p class='dim'><b>berechnet</b>: computed when the site is built from the two cited numbers "
                          "(untergebracht on 31 January ÷ population on the previous 31 December × 100 000). It is not a published figure "
                          "and is not stored in the database. Population: Destatis 12411, on the basis of Zensus 2011 up to 31.12.2021 and "
                          "Zensus 2022 from 31.12.2022, so the 2022 rate uses the older basis. After a Kreis boundary change (Hanau kreisfrei "
                          "from 01.01.2026) the population is taken in the boundaries of the Stichtag: the Destatis GV-ISys figure of "
                          "the Gemeinde(n) on 31.12., summed exactly for the remaining Kreis. Counts are by place of accommodation.</p>")
        mr = [r for r in mrows.get(ags, []) if r["metric"] not in ("einwohner", "einwohner_gebietsstand")]
        if ags == "DE" and mr:
            byk = {(r["metric"], r["year"]): r for r in mr}
            blk = ""
            for pfx, name, heads in SERIES:
                ms = heads or sorted({r["metric"] for r in mr if r["metric"].startswith(pfx) and "__" not in r["metric"]})
                rows_ = [byk[k] for k in sorted(byk) if k[0] in ms]
                if not rows_:
                    continue
                blk += f"<tr><th colspan=4>{e(name)}</th></tr>" + "".join(
                    f"<tr><td>{e(METRIC_LABEL.get(r['metric'], r['metric']))}</td><td>{r['year']}</td>"
                    f"<td class='n'>{EST_BADGE if r['is_est'] else ''}{mval(r)}</td><td>{src_link(r['source_id'], depth)}</td></tr>"
                    for r in rows_)
            if blk:
                out += ("<h2>National estimates by series</h2><p class='dim'>Each series has its own method, reference date and "
                        "definition. They are shown side by side, each with its series label and estimate badge; they are not "
                        "comparable, not added together and never merged into one number.</p>"
                        "<div class='scroll'><table><tr><th>measure</th><th>year</th><th class='n'>value</th><th></th></tr>"
                        + blk + "</table></div>")
        if mr:
            years = sorted({r["year"] for r in mr})
            by = defaultdict(dict)
            for r in mr:
                by[r["metric"]][r["year"]] = r
            out += "<h2>Breakdowns</h2><div class='scroll'><table><tr><th>metric</th>" + "".join(f"<th class='n'>{y}</th>" for y in years) + "</tr>"
            for m in sorted(by, key=lambda m: (m != "housed_homeless", m)):
                out += f"<tr><td>{e(mlabel(m))}</td>" + "".join(
                    (f"<td class='n'>{EST_BADGE if by[m][y]['is_est'] else ''}{mval(by[m][y])} {src_link(by[m][y]['source_id'], depth)}</td>"
                     if y in by[m] else "<td class='n dim'>–</td>") for y in years) + "</tr>"
            out += "</table></div>"
            if "psychiatric_care_hospital_beds" in by and any(k.startswith("hospital_beds_") for k in by):
                out += ("<p class='dim'>Psychiatric beds: BT-Drs 21/6258 (2014–2023, psychiatrische Versorgung insgesamt) and "
                        "Destatis 23111-07 (2024, aufgestellte Betten je Fachabteilung) are two different series with different "
                        "definitions; they are shown on separate lines and must not be read as one time series.</p>")
            if ags == "12" and any(m.startswith("khplan_") for m in by):
                out += ("<p class='dim'>Krankenhausplan rows are the plan's own Land Festlegungen (4. Krankenhausplan, "
                        "Amtsblatt 2021), e.g. 1,821 Planbetten Psychiatrie und Psychotherapie. The plan's per-hospital sheets "
                        "are not summed into these totals: Havelland Kliniken is not itemised (its sheet is not machine-readable), "
                        "so a sum over the itemised hospitals is not the Land total (adult psychiatry 1,751 of 1,821 beds; the "
                        "itemised Tagesklinikplätze also fall short of the plan totals).</p>")
            if any(is_flag(m, None) for m in by):
                out += "<p class='dim'>‘keine Daten’ means the official source states that no valid data exist; it is not a count of zero.</p>"
        if not out and len(ags) == 8:
            return "<p class='dim'>No homelessness figures at Gemeinde level yet (Destatis 22971 is published down to Kreise).</p>"
        return out or "<p class='dim'>No sourced numbers yet.</p>"

    orgs_by_kreis = defaultdict(list)
    canon_where = " WHERE canonical_org_id IS NULL" if "canonical_org_id" in {r[1] for r in c.execute("PRAGMA table_info(org)")} else ""
    for o in q("SELECT id, name, kreis_ags, land FROM org" + canon_where):
        if o["kreis_ags"]:
            orgs_by_kreis[o["kreis_ags"]].append(o)
    for p in places.values():
        crumbs = []
        anc = places.get(p.get("parent"))
        chain = []
        while anc:
            chain.append(anc)
            anc = places.get(anc.get("parent"))
        crumbs = [(x["name"], f"place/{x['ags']}.html") for x in reversed(chain)] + [(p["name"], None)]
        geo_src = p.get("geometry_source_id") or (p["source_id"] if p.get("geometry") else None)
        body = (f"<h1>{e(p['name'])}</h1><p class='sub'>{e(LEVEL[p['level']])} · {e(p.get('bez') or p.get('kind') or '')} · AGS <b>{e(p['ags'])}</b>"
                + (f" · {p['lat']:.4f}, {p['lon']:.4f}" if p.get("lat") else "")
                + (f" · record {src_link(p['source_id'], 1)}" if p.get("source_id") else "")
                + (f" · geometry {src_link(geo_src, 1)}" if geo_src else "") + "</p>")
        if p["level"] == "gemeinde" and p.get("einwohner") is not None:
            body += (f"<p>Einwohner{' am ' + gem_pop_date if gem_pop_date else ''}: <b>{fmt(p['einwohner'])}</b> {src_link(p['source_id'], 1)}"
                     + (f" · Fläche {fmt(p['flaeche_km2'])} km² {src_link(p['source_id'], 1)}" if p.get("flaeche_km2") is not None else "")
                     + "</p>")
        body += numbers_block(p["ags"], 1)
        if orgs_by_kreis.get(p["ags"]):
            body += "<h2>Organisations</h2><div class='cols'>" + "".join(f"<a href='../org/{o['id']}.html'>{e(o['name'])}</a>" for o in orgs_by_kreis[p["ags"]]) + "</div>"
        if kids.get(p["ags"]):
            ks = sorted(kids[p["ags"]], key=lambda k: k["name"] or "")
            body += f"<h2>{'Länder' if p['level']=='bund' else 'Kreise und kreisfreie Städte' if p['level']=='land' else 'Gemeinden'} ({len(ks)})</h2><div class='cols'>" + \
                "".join(f"<a href='../place/{k['ags']}.html'>{e(k['name'])} <span class='dim'>{k['ags']}</span></a>" for k in ks) + "</div>"
        write(f"place/{p['ags']}.html", page(p["name"], body, 1, crumbs))
        search.append({"k": p["level"], "t": p["name"] or p["ags"], "b": p["ags"], "u": f"place/{p['ags']}.html"})
    body = "<h1>Places</h1>"
    for lvl, title in (("bund", "Bund"), ("land", "Länder"), ("kreis", "Kreise und kreisfreie Städte"), ("gemeinde", "Gemeinden")):
        ps = sorted((p for p in places.values() if p["level"] == lvl), key=lambda p: (p.get("parent") or "", p["name"] or ""))
        if ps and lvl == "gemeinde":
            body += (f"<h2>{title} ({len(ps)})</h2><p class='dim'>Each Gemeinde is listed on its Kreis page and can be "
                     "found with search (<kbd>/</kbd>).</p>")
            loose = sorted((x for x in ps if x.get("parent") not in places), key=lambda x: x["ags"])
            if loose:
                body += ("<p>Not part of any Kreis in the gazetteer: " + ", ".join(
                    f"<a href='place/{x['ags']}.html'>{html.escape(x['name'])}</a> <span class='dim'>{x['ags']}</span>" for x in loose) + "</p>")
        elif ps:
            body += f"<h2>{title} ({len(ps)})</h2><div class='cols'>" + "".join(f"<a href='place/{p['ags']}.html'>{e(p['name'])} <span class='dim'>{p['ags']}</span></a>" for p in ps) + "</div>"
    write("places.html", page("Places", body, 0, [("places", None)]))

    # ---------------------------------------------------------------- organisations, people, awards
    orgs = q("SELECT * FROM org" + canon_where + " ORDER BY name")
    aliases = q("SELECT * FROM org WHERE canonical_org_id IS NOT NULL ORDER BY id") if canon_where else []
    alias_of = defaultdict(list)
    for a_ in aliases:
        alias_of[a_["canonical_org_id"]].append(a_)
    org_name = {o["id"]: o["name"] for o in orgs}
    for o in orgs:
        regs = q("SELECT * FROM org_register WHERE org_id=?", o["id"])
        ppl = q("SELECT * FROM org_person WHERE org_id=? ORDER BY CASE rollenklasse WHEN 'vorstand' THEN 1 WHEN 'geschaeftsfuehrung' THEN 1 WHEN 'praesidium' THEN 2 WHEN 'aufsichtsrat' THEN 3 WHEN 'kuratorium' THEN 3 WHEN 'sonstige' THEN 4 WHEN 'lobby_kontakt' THEN 9 ELSE 5 END, jahr DESC, funktion, funktionstraeger", o["id"])
        aw = q("SELECT * FROM award WHERE org_id=? ORDER BY haushaltsjahr DESC, betrag DESC", o["id"])
        loc = "" if o["is_protected"] else ", ".join(x for x in (o["strasse"], o["plz"], o["ort"]) if x)
        body = (f"<h1>{e(o['name'])}</h1><p class='sub'>{e(o['legal_form'] or o['org_type'] or '')} · {e(o['land'] or '')} "
                + (f"· {e(loc)} " if loc else "") + (f"· <a href='{e(o['webseite'] if re.match(r'(?i)https?://', o['webseite']) else 'https://' + o['webseite'])}' rel='noopener'>{e(o['webseite'])}</a> " if o["webseite"] else "")
                + f"· {src_link(o['source_id'], 1)}</p>")
        if alias_of.get(o["id"]):
            body += ("<h2>Also recorded as</h2><p class='dim'>The same organisation under another name or Land in another "
                     "source (merged on a shared register id, or after review).</p><table>" + "".join(
                         f"<tr><td><a href='{a_['id']}.html'>{e(a_['name'])}</a></td><td>{e(a_['land'] or '')}</td><td>{src_link(a_['source_id'],1)}</td></tr>"
                         for a_ in alias_of[o["id"]]) + "</table>")
        if regs:
            body += "<h2>Register</h2><table>" + "".join(f"<tr><td>{e(r['scheme'])}</td><td>{e(r['court'])}</td><td>{e(r['number'])}</td><td>{src_link(r['source_id'],1)}</td></tr>" for r in regs) + "</table>"
        if ppl:
            def _roles(rows):
                return ("<table><tr><th>name</th><th>published function</th><th>Stand</th><th class='n'>Vergütung</th><th></th></tr>" + "".join(
                    f"<tr><td><a href='../person/{p['id']}.html'>{e(p['funktionstraeger'])}</a></td><td>{e(p['funktion'])}</td>"
                    f"<td>{e(p['stand'] or p['jahr'] or '')}</td><td class='n'>{fmt(p['verguetung_eur']) if p['verguetung_eur'] else ''}</td>"
                    f"<td>{src_link(p['source_id'],1)}</td></tr>" for p in rows) + "</table>")
            gov = [p for p in ppl if p["rollenklasse"] != "lobby_kontakt"]
            lob = [p for p in ppl if p["rollenklasse"] == "lobby_kontakt"]
            if gov:
                body += f"<h2>Officers and board ({len(gov)})</h2>" + _roles(gov)
            if lob:
                body += (f"<h2>Persons entrusted with interest representation ({len(lob)})</h2><p class='dim'>As published in the "
                         "Lobbyregister des Deutschen Bundestages (LobbyRG); no contact details are stored.</p>") + _roles(lob)
        if aw:
            tot = sum(x["betrag"] or 0 for x in aw)
            body += f"<h2>Public money ({len(aw)} awards, {fmt(tot)} EUR)</h2><div class='scroll'><table><tr><th>year</th><th>funder</th><th>purpose</th><th class='n'>amount</th><th></th></tr>" + "".join(
                f"<tr><td>{e(x['haushaltsjahr'])}</td><td>{e(x['zuwendungsgeber'])}</td><td>{e((x['zweck'] or '')[:160])}</td><td class='n'>{fmt(x['betrag'])} {e(x['currency'])}</td><td>{src_link(x['source_id'],1)}</td></tr>" for x in aw[:500]) + "</table></div>"
        write(f"org/{o['id']}.html", page(o["name"], body, 1, [("orgs", "orgs.html"), (o["name"], None)]))
        search.append({"k": "org", "t": o["name"], "b": f"{o['land'] or ''} {o['register_id'] or ''}", "u": f"org/{o['id']}.html"})
    for a_ in aliases:
        cid = a_["canonical_org_id"]
        write(f"org/{a_['id']}.html", page(a_["name"], (
            f"<h1>{e(a_['name'])}</h1><p class='sub'>{e(a_['land'] or '')} · {src_link(a_['source_id'], 1)}</p>"
            f"<p>This record is the same organisation as <a href='{cid}.html'>{e(org_name.get(cid, str(cid)))}</a>; "
            "its roles and awards are listed there.</p>"), 1, [("orgs", "orgs.html"), (a_["name"], None)]))
    write("orgs.html", page("Organisations", "<h1>Organisations</h1>" + (
        "<div class='cols'>" + "".join(f"<a href='org/{o['id']}.html'>{e(o['name'])}</a>" for o in orgs) + "</div>" if orgs
        else "<p class='dim'>None yet (Funding &amp; Träger and Institutions &amp; Media domains).</p>"), 0, [("orgs", None)]))
    ppl = q("SELECT p.*, o.name AS oname FROM org_person p LEFT JOIN org o ON o.id=p.org_id ORDER BY p.funktionstraeger")
    for p in ppl:
        body = (f"<h1>{e(p['funktionstraeger'])}</h1><p class='sub'>{e(p['funktion'])} · <a href='../org/{p['org_id']}.html'>{e(p['oname'] or p['org_bezeichnung'])}</a> "
                f"{e(p['stand'] or p['jahr'] or '')} · {src_link(p['source_id'],1)}</p>"
                + (f"<blockquote>{dq(p['quote'])}</blockquote>" if p["quote"] else "")
                + f"<p class='dim'>Listed because this role is published in the cited source. {e(p['locator'] or '')}</p>")
        write(f"person/{p['id']}.html", page(p["funktionstraeger"], body, 1, [("people", "people.html"), (p["funktionstraeger"], None)]))
        search.append({"k": "person", "t": p["funktionstraeger"], "b": f"{p['funktion']} {p['oname'] or ''}", "u": f"person/{p['id']}.html"})
    write("people.html", page("People", "<h1>People in published roles</h1>" + (
        "<table>" + "".join(f"<tr><td><a href='person/{p['id']}.html'>{e(p['funktionstraeger'])}</a></td><td>{e(p['funktion'])}</td><td>{e(p['oname'])}</td></tr>" for p in ppl) + "</table>"
        if ppl else "<p class='dim'>None yet.</p>"), 0, [("people", None)]))

    # ---------------------------------------------------------------- facilities, laws, docs, media
    fac = q("SELECT * FROM facility ORDER BY name")
    for f in fac:
        loc = "Standort geschützt (city level only)" if f["is_protected"] else ", ".join(x for x in (f["anschrift"], f["plz"], f["ort"]) if x)
        body = f"<h1>{e(f['name'])}</h1><p class='sub'>{e(f['kind'])} · {e(f['land'])} · {e(loc or f['ort'])} · {src_link(f['source_id'],1)}</p>"
        write(f"facility/{f['id']}.html", page(f["name"], body, 1, [("facilities", "facilities.html"), (f["name"], None)]))
        search.append({"k": "facility", "t": f["name"], "b": f["kind"] or "", "u": f"facility/{f['id']}.html"})
    write("facilities.html", page("Facilities", "<h1>Facilities</h1>" + ("".join(f"<a href='facility/{f['id']}.html'>{e(f['name'])}</a><br>" for f in fac) or "<p class='dim'>None yet.</p>"), 0, [("facilities", None)]))
    laws = q("SELECT * FROM law ORDER BY jurisdiction, title")

    def lapsed_txt(l):
        """INGEST_CONTRACT §11: status 'lapsed' + in_force_to (YYYY-MM-DD or YYYY) -> 'außer Kraft seit …'."""
        if l["status"] != "lapsed":
            return ""
        on = l["in_force_to"] or ""
        return "außer Kraft seit " + (f"{on[8:10]}.{on[5:7]}.{on[:4]}" if len(on) == 10 else on)
    for l in laws:
        lt = lapsed_txt(l)
        body = (f"<h1>{e(l['short_name'] or l['title'])}</h1>"
                + (f"<p class='warn'><b>{e(lt)}</b> · historical record, not a current rule</p>" if lt else "")
                + f"<p class='sub'>{e(l['title'])} · {e(l['citation'])} · {e(l['jurisdiction'])} · {e(lt or l['status'])} {e(l['year'] or '')} · {src_link(l['source_id'],1)}</p>"
                f"<p>{e(l['summary'])}</p>" + (f"<p><a href='{e(l['url'])}'>{e(l['url'])}</a></p>" if l["url"] else ""))
        write(f"law/{l['id']}.html", page(l["title"] or "law", body, 1, [("laws", "laws.html"), (l["short_name"] or l["title"], None)]))
        search.append({"k": "law", "t": l["title"] or "", "b": l["citation"] or "", "u": f"law/{l['id']}.html"})
    write("laws.html", page("Laws", "<h1>Law &amp; policy</h1>" + ("".join(f"<a href='law/{l['id']}.html'>{e(l['jurisdiction'])} · {e(l['title'])}</a>"
                                                                   + (f" <span class='dim'>({e(lapsed_txt(l))})</span>" if lapsed_txt(l) else "") + "<br>" for l in laws) or "<p class='dim'>None yet (Counts &amp; Law, part 4).</p>"), 0, [("laws", None)]))
    docs = q("SELECT * FROM doc ORDER BY veroeffentlicht DESC")
    media = q("SELECT * FROM media ORDER BY veroeffentlicht DESC")
    write("docs.html", page("Documents", "<h1>Reports, audits, studies</h1>" + ("".join(f"<p><a href='{e(d['url'])}'>{e(d['title'])}</a> <span class='dim'>{e(d['herausgeber'])} {e(d['veroeffentlicht'])}</span> {src_link(d['source_id'],0)}</p>" for d in docs) or "<p class='dim'>None yet.</p>"), 0, [("docs", None)]))
    write("media.html", page("Media", "<h1>Media</h1>" + ("".join(f"<p><a href='{e(m['url'])}'>{e(m['title'])}</a> <span class='dim'>{e(m['herausgeber'])} {e(m['veroeffentlicht'])}</span> {src_link(m['source_id'],0)}</p>" for m in media) or "<p class='dim'>None yet.</p>"), 0, [("media", None)]))

    # ---------------------------------------------------------------- sources
    srcs = q("SELECT * FROM source ORDER BY domain, id")
    # archived copies of sources behind protected-shelter rows may print the shelter address: never mirror them
    sys.path.insert(0, str(ROOT / "scripts"))
    from verify import protected_source_ids  # noqa: E402
    _tables = {r_[0] for r_ in q("SELECT name FROM sqlite_master WHERE type='table'")}
    withheld = protected_source_ids(lambda sql, *a: q(sql, *a), _tables)
    cites = defaultdict(int)
    for t in ("zaehlung", "metric", "award", "org", "org_person", "facility", "law", "doc", "media", "geo_land", "geo_kreis"):
        for sid, n in q(f"SELECT source_id, count(*) FROM {t} GROUP BY 1"):
            cites[sid] += n
    for s in srcs:
        # Policy (Chief of Staff, 2026-11-21): archived source documents and full texts are never republished.
        # data/raw stays local; the site shows facts, metadata, short quotes and the official URL only.
        if s["local_path"] and (ROOT / s["local_path"]).exists():
            arch = "<span class='dim'>archived locally for verification (sha256 below); not republished here, see the official URL</span>"
        else:
            arch = "<span class='dim'>no archived copy</span>"
        rows = "".join(f"<tr><th>{k}</th><td>{v}</td></tr>" for k, v in (
            ("publisher", e(s["publisher"])), ("url", f"<a href='{e(s['url'])}' rel='noopener'>{e(s['url'])}</a>"),
            ("retrieved", e(s["retrieved_at"])), ("licence", e(s["license"]) + (f" · <a href='{e(s['license_url'])}'>terms</a>" if s["license_url"] else "")),
            ("Quellenvermerk", e(s["attribution"] or "")), ("sha256", f"<span class='dim'>{e(s['sha256'])} · {s['bytes'] or '?'} B</span>"),
            ("archive", arch), ("domain", e(s["domain"])), ("rows citing it", str(cites.get(s["id"], 0))), ("notes", e(s["notes"] or ""))))
        quoted = q("SELECT entity_type, entity_id, metric, year, value, einheit, is_est, quote, locator FROM metric WHERE source_id=? AND quote IS NOT NULL LIMIT 200", s["id"])
        qb = "".join(f"<div class='box'><b>{e(m['entity_id'])}</b> {e(mlabel(m['metric']))} {m['year']} = {'† Schätzung ' if m['is_est'] else ''}{mval(m)}<br><span class='dim'>{e(m['locator'])}</span><div class='quote'>„{dq(m['quote'])}“</div></div>" for m in quoted)
        write(f"source/{s['id']}.html", page(s["title"] or s["url"], f"<h1>{e(s['title'] or s['url'])}</h1><table>{rows}</table>{qb}", 1, [("sources", "sources.html"), (f"#{s['id']}", None)]))
        search.append({"k": "source", "t": s["title"] or s["url"], "b": s["publisher"] or "", "u": f"source/{s['id']}.html"})
    write("sources.html", page("Sources", "<h1>Sources</h1><table><tr><th>#</th><th>source</th><th>publisher</th><th>licence</th><th class='n'>rows</th></tr>" + "".join(
        f"<tr><td>{s['id']}</td><td><a href='source/{s['id']}.html'>{e(s['title'] or s['url'])}</a></td><td>{e(s['publisher'])}</td><td class='dim'>{e(s['license'])}</td><td class='n'>{cites.get(s['id'],0)}</td></tr>" for s in srcs) + "</table>", 0, [("sources", None)]))

    # ---------------------------------------------------------------- index
    years = sorted(choro, reverse=True)
    de = {r["berichtsjahr"]: r for r in prow.get("DE", [])}
    head = ""
    if de:
        y = max(de)
        r = de[y]
        head = (f"<div class='box'><span class='dim'>Untergebrachte wohnungslose Personen (sheltered — not total homelessness), Deutschland, Stichtag 31.01.{y}</span><br>"
                f"<span class='big'>{fmt(r['untergebracht'])}</span> {src_link(r['source_id'], 0)}"
                f"<br><span class='dim'>{' · '.join(str(yy) + ': ' + fmt(de[yy]['untergebracht']) for yy in sorted(de))}</span></div>")
    n = {t: q(f"SELECT count(*) FROM {t}")[0][0] for t in ("geo_land", "geo_kreis", "geo_gemeinde", "zaehlung", "metric", "org", "org_person", "award", "law", "source")}
    n["org"] = q("SELECT count(*) FROM org" + canon_where)[0][0]          # canonical orgs only
    n["law_lapsed"] = q("SELECT count(*) FROM law WHERE status='lapsed'")[0][0]
    n["law"] -= n["law_lapsed"]                                           # current rules only (INGEST_CONTRACT §11)
    opts = "".join(f"<option value='{y}'>untergebracht (sheltered) · 31.01.{y}</option>" for y in years) or "<option value=''>(no data)</option>"
    opts += "".join(f"<option value='r{y}'>je 100 000 Einw. · 31.01.{y} (berechnet)</option>" for y in years if f"r{y}" in rates)
    body = (f"<h1>Germany Atlas</h1><p class='sub'>Wohnungs- und Obdachlosigkeit in Deutschland: public record, map-driven, searchable. "
            f"{n['geo_land']} Länder · {n['geo_kreis']} Kreise · {n['geo_gemeinde']} Gemeinden · {n['zaehlung'] + n['metric']} sourced counts · {n['org']} orgs · {n['org_person']} published roles · "
            f"{n['award']} awards · {n['law']} laws in force" + (f" (+{n['law_lapsed']} lapsed, kept as history)" if n['law_lapsed'] else "") + f" · {n['source']} sources</p>{head}"
            "<div class='ctl'><button data-level='land' aria-pressed='true'><kbd>l</kbd> Länder</button><button data-level='kreis'><kbd>k</kbd> Kreise</button>"
            f"<select id='metric' aria-label='Stichtag'>{opts}</select><span id='cov' class='dim'></span></div>"
            "<div id='map' tabindex='0' aria-label='Karte'></div><div class='ctl'><div id='legend' class='legend'></div></div>"
            "<p class='dim'>Absolute numbers of people housed because they are homeless (Destatis Statistik untergebrachter wohnungsloser Personen), "
            "counted where the reporting body sits. Not rough sleeping or hidden homelessness. Destatis rounds each cell to a multiple of 5. "
            "The ‘je 100 000 Einw.’ options are computed when the site is built (berechnet) from these counts and the Destatis 12411 population "
            "on the previous 31 December; they are not published figures. "
            "Growth from 2022 to 2025 is largely better reporting and the inclusion of Ukrainian refugees, so it is not a trend in homelessness.</p>")
    tail = (f"<script id='obs-data' type='application/json'>{json.dumps({**choro, **rates}, ensure_ascii=False)}</script>"
            "<script src='./assets/vendor/leaflet.js'></script>")
    write("index.html", page("Karte", body, 0, (), head="<link rel='stylesheet' href='./assets/vendor/leaflet.css'>", tail=tail))
    (STAGE / "data" / "search.json").write_text(json.dumps(search, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    (STAGE / "robots.txt").write_text("User-agent: *\nDisallow: /\n")

    old = len(list(OUT.rglob("*.html"))) if OUT.exists() else 0
    if old > 50 and pages < old / 2 and not a.force:
        print(f"REFUSED: {pages} pages vs {old} currently published (>50 % shrink). Re-run with --force if intended.")
        return 1
    if PREV.exists():
        shutil.rmtree(PREV)
    if OUT.exists():
        OUT.rename(PREV)
    STAGE.rename(OUT)
    if PREV.exists():
        shutil.rmtree(PREV)
    print(f"site/: {pages} pages, {len(search)} search records, built in {time.time() - t0:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
