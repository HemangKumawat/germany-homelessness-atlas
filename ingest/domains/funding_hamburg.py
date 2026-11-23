"""funding_hamburg -- Hamburg Zuwendungen for homelessness work (Transparenzportal Hamburg, Finanzbehörde).

Source: the Finanzbehörde's "Zuwendungsvorgänge" datasets on the Transparenzportal Hamburg
(https://suche.transparenz.hamburg.de). Each dataset holds ONE XLSX with every Bescheid of the city's
grant system INEZ since 2015 (one row per Bescheid: Zuwendungs-, Änderungs-, Teil-, Rückforderungsbescheid ...).
The quarterly/annual datasets are cumulative snapshots, so this reader uses only the NEWEST one; summing
several snapshots would count the same Bescheid many times (research/funding_hamburg.md).

How the file is found (robots-first; INGEST_CONTRACT §2, worker rules):
  1. robots.txt of suche.transparenz.hamburg.de is read before any other request (Crawl-Delay 10 s honoured,
     /api/ and the other disallowed paths are never requested: CKAN API links on the pages are ignored);
  2. the portal's HTML search /dataset?q=Zuwendungsvorgänge (all result pages) -> dataset slugs
     zuwendungsvorgaenge-<Jahr>[-quartal-<n>] -> the newest;
  3. that dataset's HTML page -> its one resource link on daten.transparenz.hamburg.de (robots.txt of that host
     read first; it answers 404 = no rules) and the licence printed on the page;
  4. the XLSX (archived under data/raw/funding_hamburg, cited by every amount with sheet, row and cell).

Filter (documented in research/funding_hamburg.md), on the Zuwendungszweck text like the Berlin reader:
  core      homelessness terms (funding_traeger.BZ_CORE + Hamburg terms: Winternotprogramm, Tagesaufenthalt-
            stätte, Übernachtungsstätte, Krankenstube, Straßenzeitung ...) -> kept, any Behörde;
  adjacent  Straßensozialarbeit, Notunterkunft, Notunterbringung, Suppenküche, Tagestreff ... ->
            kept only when the granting Behörde is the social authority (name contains "Soziales") and the
            text names no refugee context (a Bezirksamt's youth street work or a refugee camp is not counted).
One award per Zuwendungsvorgang (INEZ-Nummer): the amount of its latest amount-bearing Bescheid (Änderungs-
bescheide restate the full Zuwendungssumme); every kept Bescheid is also stored in funding_hamburg_bescheid.

Rules kept: organisations only (natural persons / sole traders / GbR skipped, funding_traeger.ted_is_person);
protected shelters keep the money but no Dienststelle / place (Land level only); orgs only via
common.ensure_org (schema 6, legal_form_norm from the name, no tags in name_norm); nothing estimated.

Worker entry points (never data/atlas.db):
  python3 -m ingest.domains.funding_hamburg --test                      offline tests
  python3 -m ingest.domains.funding_hamburg --selftest --db /tmp/x.db   live sample, scratch DB, rolled back
The real DB is written only by the runner: python3 -m ingest.run funding_hamburg.
"""
from __future__ import annotations

import datetime as _dt
import html as _html
import json
import re
import sqlite3
import sys
import time
from urllib.parse import urlparse

from ingest import common

DOMAIN = "funding_hamburg"
PORTAL = "https://suche.transparenz.hamburg.de"
SEARCH = PORTAL + "/dataset?q=Zuwendungsvorg%C3%A4nge"
DATASET = PORTAL + "/dataset/{slug}"
RES_HOST = "daten.transparenz.hamburg.de"
PUBLISHER = "Freie und Hansestadt Hamburg, Finanzbehörde (Transparenzportal Hamburg)"
HH_LAND, HH_KREIS_AGS, HH_GEMEINDE_AGS = "HH", "02000", "02000000"   # Stadtstaat: Land = Kreis = Gemeinde

_SLUG = re.compile(r"/dataset/(zuwendungsvorgaenge-(\d{4})(?:-quartal-(\d)\d*)?)(?=[\"'#?])")


class ApiPathRefused(RuntimeError):
    pass


# --------------------------------------------------------------------------------------------- #
# robots-first fetch (shared gate of the funding modules) + crawl delay
# --------------------------------------------------------------------------------------------- #
def _is_api(url: str) -> bool:
    return "/api/" in (urlparse(url).path or "") + "/"


def hh_fetch(url: str, cfg: dict) -> bytes:
    """Fixture, disk cache, or a robots-gated live request. /api/ paths are refused outright (portal robots.txt
    disallows them; they are never requested, not even as probes)."""
    from ingest.domains import funding_officers as fo
    if _is_api(url):
        raise ApiPathRefused(f"/api/ path refused: {url}")
    fx = cfg.get("hh_fixture")
    if fx is not None:
        if not fo.robots_ok(url, cfg):
            raise fo.RobotsRefused(f"robots.txt refuses {url}")
        cfg.setdefault("_hh_log", []).append(url)
        return fx[url]
    force = bool(cfg.get("force"))
    if not force and common.cached_path(DOMAIN, url) is not None:
        return common.fetch(url, domain=DOMAIN)
    origin = fo._origin(url)
    first = origin not in fo._ROBOTS
    fo.robots_gate(url, cfg, domain=DOMAIN, cached_ok=False)       # reads robots.txt first; raises if refused
    if first:
        fo._HOST_LAST[origin] = time.monotonic()                  # the robots.txt read counts for the delay
    robots = fo._ROBOTS.get(origin)
    delay = max(robots[1] or 0, 1.0) if isinstance(robots, tuple) else 1.0
    gap = time.monotonic() - fo._HOST_LAST.get(origin, 0.0)
    if gap < delay:
        time.sleep(delay - gap)
    try:
        return common.fetch(url, domain=DOMAIN, force=force)
    finally:
        fo._HOST_LAST[origin] = time.monotonic()


# --------------------------------------------------------------------------------------------- #
# discovery: HTML search pages -> newest dataset -> its XLSX resource and licence
# --------------------------------------------------------------------------------------------- #
def dataset_slugs(html_text: str) -> dict[str, tuple[int, int]]:
    """slug -> (year, quarter); an annual dataset ('zuwendungsvorgaenge-2025') ranks after Q4 (quarter 5)."""
    out = {}
    for m in _SLUG.finditer(html_text):
        out[m.group(1)] = (int(m.group(2)), int(m.group(3)) if m.group(3) else 5)
    return out


def search_pages(html_text: str) -> list[int]:
    return sorted({int(n) for n in re.findall(r"[?&](?:amp;)?page=(\d+)", html_text)})


def page_field(text: str, label: str) -> str | None:
    m = re.search(rf"(?m)(?:^|\s){re.escape(label)}\n(.+)$", text)
    return common.clean(m.group(1)) if m else None


def dataset_info(html_bytes: bytes, slug: str) -> dict:
    t = html_bytes.decode("utf-8", "replace")
    links = [_html.unescape(h) for h in re.findall(r'href="([^"]+)"', t)]
    res = [h for h in links if urlparse(h).netloc == RES_HOST and re.search(r"(?i)\.xlsx$", h) and not _is_api(h)]
    txt = common.html_to_text(t)
    zb = re.search(r"Zeitbezug\nvon\n([\d.]+)\nbis\n([\d.]+)", txt)
    return {"slug": slug, "page": DATASET.format(slug=slug), "xlsx": res[0] if res else None,
            "license": page_field(txt, "Lizenz"), "attribution": page_field(txt, "Namensnennung"),
            "publisher": page_field(txt, "Veröffentlichende Stelle"),
            "published": page_field(txt, "Veröffentlichungsdatum"),
            "period": f"{zb.group(1)}–{zb.group(2)}" if zb else None}


def discover(cfg: dict) -> dict:
    """Newest Zuwendungsvorgänge dataset via robots-allowed HTML pages only. Raises if none exposes an XLSX."""
    if cfg.get("hh_dataset"):
        slugs = {cfg["hh_dataset"]: (0, 0)}
    else:
        first = hh_fetch(SEARCH, cfg).decode("utf-8", "replace")
        slugs = dataset_slugs(first)
        for p in [p for p in search_pages(first) if p > 1][: int(cfg.get("hh_max_pages", 10))]:
            slugs.update(dataset_slugs(hh_fetch(f"{SEARCH}&page={p}", cfg).decode("utf-8", "replace")))
    if not slugs:
        raise RuntimeError("no Zuwendungsvorgänge dataset found on the portal's search pages")
    tried = []
    for slug in sorted(slugs, key=lambda s: slugs[s], reverse=True)[:3]:
        info = dataset_info(hh_fetch(DATASET.format(slug=slug), cfg), slug)
        if info["xlsx"]:
            info["candidates"] = len(slugs)
            return info
        tried.append(slug)
    raise RuntimeError(f"no robots-allowed XLSX link on the newest dataset pages {tried}")


# --------------------------------------------------------------------------------------------- #
# filter
# --------------------------------------------------------------------------------------------- #
def _ft():
    from ingest.domains import funding_traeger as ft
    return ft


HH_CORE_EXTRA = re.compile("|".join([
    r"winternot\w*", r"tagesaufenthalt\w*", r"[üu]e?bernachtungsst[äa]e?tte\w*", r"krankenstube\w*",
    r"stra[ßs]s?enzeitung\w*", r"hinz\s*&\s*kunzt", r"mitternachtsbus\w*", r"obdach\b"]), re.I)
# "öffentlich-rechtliche Unterbringung" / "Wohnunterkunft" are NOT adjacent terms on their own: Hamburg houses
# refugees and homeless people in the same system and the grants on these words (play schemes, childcare and
# counselling in Wohnunterkünfte) are refugee follow-up work; they count only next to a core term.
HH_ADJ_EXTRA = re.compile("|".join([r"tagestreff\w*"]), re.I)
# names funding_traeger.ted_is_person would call private (no legal-form token) that are plainly organisations
# ("Housing First Hamburg" stays skipped: no organisation token, and verify G7 reads such a name as a person's)
HH_ORG_NAME = re.compile(r"k[öo]e?rperschaft des [öo]e?ffentlichen rechts|anstalt des [öo]e?ffentlichen rechts|"
                         r"heilsarmee", re.I)


def is_person(name: str | None) -> bool:
    """Privacy guard: natural persons / sole traders / GbR are skipped (funding_traeger.ted_is_person), except names
    that spell out a public-law form (the Salvation Army's 'Körperschaft des öffentlichen Rechts')."""
    n = common.clean(name) or ""
    if n and HH_ORG_NAME.search(n) and not _ft()._SOLE_TRADER.search(n):
        return False
    return _ft().ted_is_person(n)


SOCIAL_AUTHORITY = re.compile(r"soziales|sozialbeh[öo]e?rde", re.I)


def classify(zweck: str | None, behoerde: str | None) -> tuple[str | None, list[str]]:
    ft = _ft()
    z = zweck or ""
    core = sorted({m.group(0).lower() for rx in (ft.BZ_CORE, HH_CORE_EXTRA) for m in rx.finditer(z)})
    adj = sorted({m.group(0).lower() for rx in (ft.BZ_ADJACENT, HH_ADJ_EXTRA) for m in rx.finditer(z)})
    if core:
        return "core", core + adj
    if adj and not ft.REFUGEE_RE.search(z) and SOCIAL_AUTHORITY.search(behoerde or ""):
        return "adjacent", adj
    return None, []


# --------------------------------------------------------------------------------------------- #
# XLSX rows
# --------------------------------------------------------------------------------------------- #
COLS = {"inez": "INEZ-Nummer", "datum": "Bescheiddatum", "art": "Bescheidart", "empf": "Zuwendungsempfänger",
        "behoerde": "Behörde", "dienststelle": "Dienststelle", "akz": "AKZ", "von": "ZuwendungszeitraumVon",
        "bis": "ZuwendungszeitraumBis", "zweck": "Zuwendungszweck", "foerderungsart": "Förderungsart",
        "finanzierungsart": "Finanzierungsart", "finanzierungsform": "Finanzierungsform",
        "betrieb": "Betriebskostenanteil", "invest": "Investitionskostenanteil", "rueck": "Rückforderungen",
        "summe": "Zuwendungssumme"}
AMOUNT_ARTS = re.compile(r"^(zuwendungsbescheid|änderungsbescheid|teilbescheid|zuwendungsvertrag|änderungsvertrag|"
                         r"empfängerwechsel)$", re.I)


def header_map(header: list[str]) -> dict[str, int]:
    norm = [re.sub(r"^summe von\s+", "", (h or "").strip(), flags=re.I).lower() for h in header]
    out = {}
    for k, label in COLS.items():
        if label.lower() in norm:
            out[k] = norm.index(label.lower())
    missing = [COLS[k] for k in ("inez", "datum", "art", "empf", "behoerde", "zweck", "summe") if k not in out]
    if missing:
        raise RuntimeError(f"Zuwendungsvorgänge XLSX: columns missing {missing} (header {header[:17]})")
    return out


def xl_date(v) -> str | None:
    try:
        return (_dt.date(1899, 12, 30) + _dt.timedelta(days=int(float(v)))).isoformat()
    except (TypeError, ValueError):
        v = common.clean(v)
        m = re.match(r"(\d{1,2})\.(\d{1,2})\.(\d{4})$", v or "")
        return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}" if m else None


def amount(raw) -> float | None:
    """The cell value exactly as stored (G5/G9 find it verbatim in the archived text); None if not a number."""
    s = common.clean(raw)
    if s is None or not re.fullmatch(r"-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?", str(s)):
        return None
    return float(s)


def clean_name(v) -> str | None:
    n = common.clean(v)
    if n and len(n) > 2 and n[0] == n[-1] == '"':
        n = common.clean(n[1:-1])
    return n


DDL = """
CREATE TABLE IF NOT EXISTS funding_hamburg_bescheid (
  source_id        INTEGER NOT NULL,      -- the archived XLSX
  zeile            INTEGER NOT NULL,      -- 1-based row in the sheet (header = row 1)
  sheet            TEXT,
  inez             TEXT NOT NULL,         -- INEZ-Nummer = Zuwendungsvorgang
  bescheiddatum    TEXT,
  bescheidart      TEXT,
  empfaenger       TEXT,
  empfaenger_norm  TEXT,
  behoerde         TEXT,
  dienststelle     TEXT,                  -- NULL on protected-shelter rows
  von              TEXT,
  bis              TEXT,
  zweck            TEXT,
  foerderungsart   TEXT,
  finanzierungsart TEXT,
  finanzierungsform TEXT,
  betriebskosten   REAL,
  investitionskosten REAL,
  rueckforderungen REAL,
  zuwendungssumme  REAL,
  currency         TEXT DEFAULT 'EUR',
  tier             TEXT,                  -- core | adjacent (of the Vorgang)
  matched_terms    TEXT,                  -- JSON list
  tags             TEXT,                  -- JSON list: refugee, protected_shelter
  is_award_row     INTEGER DEFAULT 0,     -- 1 = the Bescheid whose Zuwendungssumme the award row carries
  PRIMARY KEY (source_id, zeile)
);
CREATE INDEX IF NOT EXISTS ix_fhb_inez ON funding_hamburg_bescheid(inez);
CREATE INDEX IF NOT EXISTS ix_fhb_norm ON funding_hamburg_bescheid(empfaenger_norm);
"""


def run_hamburg(conn, cfg: dict) -> dict:
    from ingest.domains.institutions_media_orgs import iter_xlsx_sheets
    ft = _ft()
    conn.executescript(DDL)
    info = cfg.get("hh_info") or discover(cfg)
    url = info["xlsx"]
    data = cfg["hh_xlsx"] if cfg.get("hh_xlsx") is not None else hh_fetch(url, cfg)
    lic = info.get("license") or "see dataset page"
    license_ = (f"{lic} (Transparenzportal Hamburg, dataset '{info['slug']}' {info['page']}); attribution: "
                f"{info.get('attribution') or 'Freie und Hansestadt Hamburg'}, {info.get('publisher') or 'Finanzbehörde'}")
    sid = common.source_id_for(conn, url, DOMAIN, title=f"Transparenzportal Hamburg – {info['slug']}: Zuwendungsvorgänge "
                               f"(Bescheide {info.get('period') or ''}), XLSX", publisher=PUBLISHER, license=license_)
    sheets = iter_xlsx_sheets(data)
    sheet, rows = next(iter(sheets.items()))
    hm = header_map(rows[0])
    g = lambda r, k: (r[hm[k]] if k in hm and hm[k] < len(r) else "")  # noqa: E731

    # 1. group Bescheide by Vorgang; a Vorgang is in scope when any of its Bescheide matches
    vorg: dict[str, list[int]] = {}
    for ri in range(1, len(rows)):
        inez = common.clean(g(rows[ri], "inez"))
        if inez:
            vorg.setdefault(inez, []).append(ri)
    stats = {"bescheide": len(rows) - 1, "vorgaenge": len(vorg), "core": 0, "adjacent": 0, "persons": 0,
             "no_amount_row": 0, "protected": 0, "bescheide_kept": 0, "org_none": 0}
    total, orgs, years = 0.0, set(), {}
    limit = cfg.get("hh_limit")
    kept = 0
    for inez, ris in vorg.items():
        best_tier, terms = None, set()
        for ri in ris:
            t, ts = classify(common.clean(g(rows[ri], "zweck")), common.clean(g(rows[ri], "behoerde")))
            if t:
                terms.update(ts)
                best_tier = "core" if "core" in (t, best_tier) else t
        if not best_tier:
            continue
        cand = [ri for ri in ris if AMOUNT_ARTS.match(common.clean(g(rows[ri], "art")) or "")
                and amount(g(rows[ri], "summe")) is not None]
        if not cand:
            stats["no_amount_row"] += 1
            continue
        # latest Bescheid; same day -> the longer period, then the earlier file row (the file lists newest first)
        lead = max(cand, key=lambda ri: (xl_date(g(rows[ri], "datum")) or "", xl_date(g(rows[ri], "bis")) or "", -ri))
        r = rows[lead]
        name = clean_name(g(r, "empf"))
        if is_person(name):
            stats["persons"] += 1
            continue
        texts = " ".join(common.clean(g(rows[ri], "zweck")) or "" for ri in ris) + " " + " ".join(
            clean_name(g(rows[ri], "empf")) or "" for ri in ris)
        protected = ft.is_protected(texts)
        tags = (["refugee"] if ft.REFUGEE_RE.search(texts) else []) + (["protected_shelter"] if protected else [])
        stats["protected"] += protected
        nn = common.name_norm(name)
        org_id = ft.ensure_org_xland(conn, name, HH_LAND, sid, stats=stats, is_protected=1 if ft.is_protected(name) else None)
        stats["org_none"] += org_id is None
        for ri in ris:
            rr = rows[ri]
            z = common.clean(g(rr, "zweck"))
            common.upsert(conn, "funding_hamburg_bescheid", {
                "source_id": sid, "zeile": ri + 1, "sheet": sheet, "inez": inez,
                "bescheiddatum": xl_date(g(rr, "datum")), "bescheidart": common.clean(g(rr, "art")),
                "empfaenger": clean_name(g(rr, "empf")), "empfaenger_norm": common.name_norm(clean_name(g(rr, "empf"))),
                "behoerde": common.clean(g(rr, "behoerde")),
                "dienststelle": None if protected else common.clean(g(rr, "dienststelle")),
                "von": xl_date(g(rr, "von")), "bis": xl_date(g(rr, "bis")),
                "zweck": ft.redact_place(z) if protected else z,
                "foerderungsart": common.clean(g(rr, "foerderungsart")),
                "finanzierungsart": common.clean(g(rr, "finanzierungsart")),
                "finanzierungsform": common.clean(g(rr, "finanzierungsform")),
                "betriebskosten": amount(g(rr, "betrieb")), "investitionskosten": amount(g(rr, "invest")),
                "rueckforderungen": amount(g(rr, "rueck")), "zuwendungssumme": amount(g(rr, "summe")),
                "currency": "EUR", "tier": best_tier, "matched_terms": json.dumps(sorted(terms), ensure_ascii=False),
                "tags": json.dumps(tags), "is_award_row": 1 if ri == lead else 0}, keys=["source_id", "zeile"])
            stats["bescheide_kept"] += 1
        betrag = amount(g(r, "summe"))
        von, bis = xl_date(g(r, "von")), xl_date(g(r, "bis"))
        datum, art = xl_date(g(r, "datum")), common.clean(g(r, "art"))
        zweck = common.clean(g(r, "zweck"))
        col = common.xlsx_col(hm["summe"])
        common.upsert(conn, "award", {
            "foerder_schluessel": f"DE-HH-ZUW:{inez}", "foerder_id": inez, "foerderart": "zuwendung",
            "zuwendungsgeber": common.clean(g(r, "behoerde")),
            "dienststelle": None if protected else common.clean(g(r, "dienststelle")),
            "programm": common.clean(g(r, "foerderungsart")), "zweck": ft.redact_place(zweck) if protected else zweck,
            "empfaenger": name, "empfaenger_norm": nn, "org_id": org_id, "betrag": betrag, "currency": "EUR",
            "haushaltsjahr": von[:4] if von and bis and von[:4] == bis[:4] else None,
            "laufzeit_von": von, "laufzeit_bis": bis, "ort_land": HH_LAND,
            "ort_kreis": None if protected else HH_KREIS_AGS, "ort_gemeinde": None if protected else HH_GEMEINDE_AGS,
            "is_est": 0, "quote": common.xlsx_cell_line(sheet, lead, hm["summe"], r),
            "locator": (f"{url} – Blatt '{sheet}', Zeile {lead + 1}, Zelle {col}{lead + 1} (EUR, Zuwendungssumme bewilligt, Zeitraum {von or '?'} bis {bis or '?'}); "
                        f"{art} vom {datum}; latest of {len(ris)} Bescheid(e) of INEZ {inez}"),
            "source_id": sid}, keys=["foerder_schluessel"])
        kept += 1
        stats[best_tier] += 1
        total += betrag or 0
        orgs.add(nn)
        y = (von or "")[:4]
        years[y] = years.get(y, 0) + 1
        if limit and kept >= int(limit):
            break
    notes = (f"hamburg_zuwendungen: dataset {info['slug']} ({info.get('period')}, {info.get('license')}; "
             f"{info.get('candidates', 1)} datasets seen), {stats['bescheide']} Bescheide / {stats['vorgaenge']} Vorgänge "
             f"in file; kept {kept} Vorgänge (core={stats['core']}, adjacent={stats['adjacent']}), "
             f"{stats['bescheide_kept']} Bescheide, {len(orgs)} recipients, EUR {total:,.2f}; skipped {stats['persons']} "
             f"natural-person / no-organisation-token rows, {stats['no_amount_row']} Vorgänge without an amount-bearing Bescheid; protected "
             f"{stats['protected']}; org key taken (no org) {stats['org_none']}; start years "
             + ", ".join(f"{k}:{v}" for k, v in sorted(years.items())))
    notes += f"; cross-Land org matches {stats.get('xland', 0)}"
    return {"rows": kept, "notes": notes, "sources": [(url, license_)], "stats": stats}


SOURCES = {"hamburg_zuwendungen": run_hamburg}


def run(conn, cfg=None) -> dict:
    cfg = cfg or {}
    rows, notes, sources = 0, [], []
    for n in cfg.get("sources") or list(SOURCES):
        res = SOURCES[n](conn, cfg)
        rows += res["rows"]
        notes.append(res["notes"])
        sources += res["sources"]
    return {"rows": rows, "notes": " | ".join(notes), "sources": sources}


# --------------------------------------------------------------------------------------------- #
# offline tests
# --------------------------------------------------------------------------------------------- #
def memory_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(common.SCHEMA.read_text(encoding="utf-8"))
    return conn


def mini_xlsx(rows: list[list], sheet: str = "Sheet1") -> bytes:
    """Smallest valid XLSX (inline strings, numeric cells as <v>) for the offline tests."""
    import io
    import zipfile
    from xml.sax.saxutils import escape

    def cell(ri, ci, v):
        ref = f"{common.xlsx_col(ci)}{ri + 1}"
        if isinstance(v, (int, float)) or (isinstance(v, str) and re.fullmatch(r"-?\d+(\.\d+)?", v)):
            return f'<c r="{ref}"><v>{v}</v></c>'
        return f'<c r="{ref}" t="inlineStr"><is><t>{escape(str(v))}</t></is></c>' if v != "" else ""
    body = "".join(f'<row r="{ri + 1}">' + "".join(cell(ri, ci, v) for ci, v in enumerate(r)) + "</row>"
                   for ri, r in enumerate(rows))
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    rns = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/'
                   'package/2006/content-types"/>')
        z.writestr("xl/workbook.xml", f'<?xml version="1.0"?><workbook {ns} {rns}><sheets><sheet name="{sheet}" '
                   'sheetId="1" r:id="rId1"/></sheets></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels", '<?xml version="1.0"?><Relationships xmlns="http://schemas.'
                   'openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.'
                   'openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
                   '</Relationships>')
        z.writestr("xl/worksheets/sheet1.xml", f'<?xml version="1.0"?><worksheet {ns}><sheetData>{body}</sheetData>'
                   '</worksheet>')
    return buf.getvalue()


_HDR = ["INEZ-Nummer", "Bescheiddatum", "Bescheidart", "Zuwendungsempfänger", "Behörde", "Dienststelle", "AKZ",
        "ZuwendungszeitraumVon", "ZuwendungszeitraumBis", "Zuwendungszweck", "Förderungsart", "Finanzierungsart",
        "Finanzierungsform", "Summe von Betriebskostenanteil", "Summe von Investitionskostenanteil",
        "Summe von Rückforderungen", "Summe von Zuwendungssumme"]
SOZ = "Behörde für Arbeit, Gesundheit, Soziales, Familie und Integration"


def _r(inez, datum, art, empf, beh, zweck, summe, von="45658", bis="46022", dst="Amt SI"):
    return [inez, datum, art, empf, beh, dst, f"AKZ-{inez}", von, bis, zweck, "Projektförderung",
            "Fehlbedarfsfinanzierung", "Nicht rückzahlbarer Zuschuss", "", "", "", summe]


_FIX_ROWS = [_HDR,
             _r("ZUW-1", "46020", "Änderungsbescheid", "Tagestreff Musterhilfe e.V.", SOZ,
                "Betrieb des Tagesaufenthalts für obdachlose Menschen", "283502.03000000003"),
             _r("ZUW-1", "45700", "Zuwendungsbescheid", "Tagestreff Musterhilfe e.V.", SOZ,
                "Betrieb des Tagesaufenthalts für obdachlose Menschen", "250000"),
             _r("ZUW-1", "45800", "Rückforderungsbescheid", "Tagestreff Musterhilfe e.V.", SOZ,
                "Betrieb des Tagesaufenthalts für obdachlose Menschen", "999"),
             _r("ZUW-2", "45700", "Zuwendungsbescheid", "Streetwork Nord gGmbH", "Bezirksamt Hamburg-Nord",
                "Straßensozialarbeit für Jugendliche", "50000"),
             _r("ZUW-3", "45700", "Zuwendungsbescheid", "Streetwork Hilfe gGmbH", SOZ,
                "Straßensozialarbeit am Hauptbahnhof", "70000"),
             _r("ZUW-4", "45700", "Zuwendungsbescheid", "Max Mustermann", SOZ, "Winternotprogramm Beratung", "1000"),
             _r("ZUW-5", "45700", "Zuwendungsbescheid", "Frauenhaus Verein Hamburg e.V.", SOZ,
                "Notübernachtung für wohnungslose Frauen im Frauenhaus Musterweg 5", "80000"),
             _r("ZUW-6", "45700", "Zuwendungsbescheid", "Unterkunftshilfe e.V.", SOZ,
                "Sozialberatung in der öffentlich-rechtlichen Unterbringung für Geflüchtete", "30000"),
             _r("ZUW-7", "45700", "Zuwendungsbescheid", "Kulturverein e.V.", "Behörde für Kultur und Medien",
                "Theaterprojekt", "5000")]

_DS_PAGE = (b'<html><body><h2>Ver\xc3\xb6ffentlichende Stelle</h2><p>Finanzbeh\xc3\xb6rde</p>'
            b'<h2>Zeitbezug</h2><p>von</p><p>01.01.2015</p><p>bis</p><p>31.12.2025</p>'
            b'<a href="http://suche.transparenz.hamburg.de/api/3/action/package_show?id=zuwendungsvorgaenge-2025">api</a>'
            b'<a href="https://daten.transparenz.hamburg.de/X.svc/abc/Upload__Zuwendungsbericht2025INEZ.XLSX">dl</a>'
            b'<h2>Lizenz</h2><p>Creative Commons CCZero</p><h2>Namensnennung</h2><p>Freie und Hansestadt Hamburg</p>'
            b'</body></html>')
_SEARCH_1 = (b'<a href="/dataset/zuwendungsvorgaenge-2024-quartal-4">a</a><a href="/dataset/zuwendungsvorgaenge-2021-'
             b'quartal-11">b</a><a href="/dataset/?q=Zuwendungsvorg%C3%A4nge&amp;page=2">2</a>')
_SEARCH_2 = b'<a href="/dataset/zuwendungsvorgaenge-2025">c</a><a href="/dataset/zuwendungsvorgaenge-2018-quartal-31">d</a>'
_ROBOTS = {PORTAL: "User-agent: *\nDisallow: /api/\nDisallow: /dataset/rate/\nCrawl-Delay: 10\n",
           "https://" + RES_HOST: 404}
_XURL = "https://daten.transparenz.hamburg.de/X.svc/abc/Upload__Zuwendungsbericht2025INEZ.XLSX"


def _fixture_cfg(**kw) -> dict:
    return {"robots_fixture": dict(_ROBOTS), "hh_fixture": {
        SEARCH: _SEARCH_1, SEARCH + "&page=2": _SEARCH_2,
        DATASET.format(slug="zuwendungsvorgaenge-2025"): _DS_PAGE, _XURL: mini_xlsx(_FIX_ROWS)}, **kw}


def _reset_robots():
    from ingest.domains import funding_officers as fo
    fo._ROBOTS.clear()
    fo._HOST_LAST.clear()


def _test_classify():
    assert classify("Betrieb einer Tagesaufenthaltsstätte", "Bezirksamt Altona")[0] == "core"
    assert classify("Krankenstube für Obdachlose", "Bezirksamt Altona")[0] == "core"
    assert classify("Straßensozialarbeit in Neugraben", "Bezirksamt Harburg")[0] is None      # youth street work
    assert classify("Straßensozialarbeit am Hauptbahnhof", SOZ)[0] == "adjacent"
    assert classify("Sozialberatung in der öffentlich-rechtlichen Unterbringung für Geflüchtete", SOZ)[0] is None
    assert classify("Spielaktionen in Unterkünften", "Behörde für Schule und Berufsbildung")[0] is None
    assert classify("Spielaktionen in Unterkünften der öffentlich-rechtlichen Unterbringung", SOZ)[0] is None
    assert classify("Kinderbetreuung in der Wohnunterkunft (WUK) Waldweg", SOZ)[0] is None
    assert classify("Beratung wohnungsloser Menschen in der öffentlich-rechtlichen Unterbringung", SOZ)[0] == "core"
    assert classify("ambulante Suchthilfe", SOZ)[0] is None                                   # not in scope
    assert classify("Theaterprojekt", "Behörde für Kultur und Medien") == (None, [])
    assert not is_person("Die Heilsarmee in Deutschland Körperschaft des öffentlichen Rechts")
    assert is_person("Housing First Hamburg")            # privacy wins without an organisation token (G7 agrees)
    assert is_person("Max Mustermann") and is_person("Erika Muster e.K.") and is_person("Hamburg Hausmeister Max Muster GbR")


def _test_discovery_and_api():
    _reset_robots()
    cfg = _fixture_cfg()
    info = discover(cfg)
    assert info["slug"] == "zuwendungsvorgaenge-2025" and info["xlsx"] == _XURL, info
    assert info["license"] == "Creative Commons CCZero" and info["period"] == "01.01.2015–31.12.2025", info
    assert info["candidates"] == 4
    assert not any("/api/" in u for u in cfg["_hh_log"])                  # the API link on the page is never followed
    for u in (PORTAL + "/api/3/action/package_search?q=x", "http://suche.transparenz.hamburg.de/api/3/action/x"):
        try:
            hh_fetch(u, cfg)
            raise AssertionError("api path fetched")
        except ApiPathRefused:
            pass
    from ingest.domains import funding_officers as fo
    try:                                                                   # robots-disallowed path
        hh_fetch(PORTAL + "/dataset/rate/x", cfg)
        raise AssertionError("disallowed path fetched")
    except fo.RobotsRefused:
        pass
    _reset_robots()
    bad = _fixture_cfg(robots_fixture={PORTAL: "error"})                   # unreadable robots.txt: fail closed
    try:
        discover(bad)
        raise AssertionError("fetched without robots.txt")
    except Exception as e:  # noqa: BLE001
        assert type(e).__name__ == "RobotsRefused", e
    assert not bad.get("_hh_log")
    assert dataset_slugs('href="/dataset/zuwendungsvorgaenge-2020-quartal-31"') == {
        "zuwendungsvorgaenge-2020-quartal-31": (2020, 3)}
    _reset_robots()


def _test_reader():
    _reset_robots()
    conn = memory_conn()
    res = run(conn, _fixture_cfg())
    aw = {r["foerder_id"]: dict(r) for r in conn.execute("SELECT * FROM award")}
    assert set(aw) == {"ZUW-1", "ZUW-3", "ZUW-5"}, sorted(aw)              # Bezirk street work, person, refugee, culture out
    a = aw["ZUW-1"]
    assert a["betrag"] == float("283502.03000000003") and a["currency"] == "EUR" and a["is_est"] == 0
    assert a["empfaenger"] == "Tagestreff Musterhilfe e.V." and a["ort_kreis"] == HH_KREIS_AGS
    lines = common.xlsx_text(mini_xlsx(_FIX_ROWS)).splitlines()
    assert a["quote"] in lines and a["quote"].startswith("[Sheet1!Q2] "), a["quote"]   # latest Änderungsbescheid, row 2
    assert "Zeile 2" in a["locator"] and _XURL in a["locator"]
    assert a["laufzeit_von"] == "2025-01-01" and a["haushaltsjahr"] == "2025"
    p = aw["ZUW-5"]                                                        # protected shelter: money kept, no place
    assert p["ort_kreis"] is None and p["dienststelle"] is None and "Musterweg" not in (p["zweck"] or "")
    tags = {json.loads(r[0]).__contains__("protected_shelter") for r in conn.execute(
        "SELECT tags FROM funding_hamburg_bescheid WHERE inez='ZUW-5'")}
    assert tags == {True}
    assert conn.execute("SELECT count(*) FROM funding_hamburg_bescheid WHERE inez='ZUW-1'").fetchone()[0] == 3
    assert conn.execute("SELECT is_award_row FROM funding_hamburg_bescheid WHERE inez='ZUW-1' AND zeile=2").fetchone()[0] == 1
    orgs = {r["name"]: dict(r) for r in conn.execute("SELECT * FROM org")}
    assert orgs["Tagestreff Musterhilfe e.V."]["legal_form_norm"] == "ev"
    assert orgs["Streetwork Hilfe gGmbH"]["legal_form_norm"] == "ggmbh"
    assert orgs["Frauenhaus Verein Hamburg e.V."]["is_protected"] == 1
    assert all(o["name_norm"] == common.name_norm(o["name"]) for o in orgs.values())   # no tags in name_norm
    assert "Max Mustermann" not in orgs and "Max Mustermann" not in json.dumps(res)
    assert "skipped 1 natural-person / no-organisation-token rows" in res["notes"], res["notes"]
    # re-run is idempotent
    run(conn, _fixture_cfg())
    assert conn.execute("SELECT count(*) FROM award").fetchone()[0] == 3
    assert conn.execute("SELECT count(*) FROM org").fetchone()[0] == 3
    _reset_robots()


def _test_existing_org_namesakes():
    """v6: an existing e.V. and gGmbH of one name -> an unknown-form record gets a new, flagged row."""
    _reset_robots()
    conn = memory_conn()
    sid = conn.execute("INSERT INTO source(url, domain, title) VALUES ('https://example.org/x', 'funding_hamburg', 'x')").lastrowid
    for nm, lf in (("Diakonie Musterstadt e.V.", "ev"), ("Diakonie Musterstadt gGmbH", "ggmbh")):
        conn.execute("INSERT INTO org(name, name_norm, legal_form_norm, land, source_id, currency) VALUES (?,?,?,?,?,'EUR')",
                     (nm, common.name_norm(nm), lf, "HH", sid))
    rows = [_HDR, _r("ZUW-9", "45700", "Zuwendungsbescheid", "Diakonie Musterstadt", SOZ, "Hilfe für wohnungslose Menschen", "1200")]
    cfg = _fixture_cfg()
    cfg["hh_fixture"][_XURL] = mini_xlsx(rows)
    run(conn, cfg)
    oid = conn.execute("SELECT org_id FROM award WHERE foerder_id='ZUW-9'").fetchone()[0]
    if common.name_norm("Diakonie Musterstadt") == common.name_norm("Diakonie Musterstadt e.V."):
        assert conn.execute("SELECT legal_form_norm FROM org WHERE id=?", (oid,)).fetchone()[0] is None
        assert conn.execute("SELECT count(*) FROM org_link WHERE org_id=? AND method='name_fuzzy'", (oid,)).fetchone()[0] == 1
    _reset_robots()


TESTS = [_test_classify, _test_discovery_and_api, _test_reader, _test_existing_org_namesakes]


def _run_tests():
    for t in TESTS:
        t()
        print("PASS", t.__name__)


SELFTEST_CFG = {"hh_limit": 25}


def _selftest(argv):
    """Live sample (robots-first discovery, newest XLSX) into a scratch DB; the runner's transaction is rolled back."""
    from ingest import run as runner
    from ingest.domains.funding_traeger import scratch_db_path
    conn = runner.open_db(scratch_db_path(argv))
    conn.execute("BEGIN IMMEDIATE")
    conn.runner_txn = True
    try:
        res = run(conn, dict(SELFTEST_CFG))
        print(f"[{DOMAIN}] selftest rows={res['rows']}")
        print(f"[{DOMAIN}]   {res['notes']}")
        for r in conn.execute("SELECT a.foerder_schluessel, a.empfaenger, a.zuwendungsgeber, a.betrag, a.laufzeit_von, "
                              "a.laufzeit_bis, a.quote, s.url FROM award a JOIN source s ON s.id=a.source_id "
                              "WHERE a.foerder_schluessel LIKE 'DE-HH-ZUW:%' ORDER BY random() LIMIT 3"):
            print("   ", dict(r))
        assert conn.execute("SELECT count(*) FROM award WHERE foerder_schluessel LIKE 'DE-HH-ZUW:%' "
                            "AND (quote IS NULL OR locator IS NULL OR betrag IS NULL)").fetchone()[0] == 0
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        conn.runner_txn = False
        conn.execute("ROLLBACK")
        conn.close()


def _cli(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="python3 -m ingest.domains.funding_hamburg", allow_abbrev=False,
                                 description="Worker tools. data/atlas.db is written only by "
                                             "`python3 -m ingest.run funding_hamburg`.")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--test", action="store_true", help="offline unit tests (in-memory SQLite)")
    mode.add_argument("--selftest", action="store_true", help="live sample into a scratch DB (needs --db)")
    ap.add_argument("--db", help="--selftest: scratch DB path (never atlas.db)")
    a = ap.parse_args(argv)
    if a.db and not a.selftest:
        ap.error("--db is only valid with --selftest")
    if a.test:
        _run_tests()
    else:
        if not a.db:
            ap.error("--selftest needs --db <scratch path>")
        _selftest(["--selftest", "--db", a.db])
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
