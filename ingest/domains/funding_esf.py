"""funding_esf -- ESF Plus "Liste der Vorhaben" of the Länder (Art. 49(3) Regulation (EU) 2021/1060): homelessness
operations with beneficiary, purpose, period, total eligible cost and (where given) the EU contribution.

Lists read (one XLSX each, found on the Land's own list page; research/funding_esf.md has the survey):
  NI europa-fuer-niedersachsen.niedersachsen.de (ESF+ 2021-2027, NBank)     BY www.esf.bayern.de
  NW www.mags.nrw                                                            TH www.esf-thueringen.de
  RP esf.rlp.de                                                              BE www.berlin.de (SenASGIVA)
  BB esf.brandenburg.de -- the list there is the ESF 2014-2020 Gesamtliste; the 2021-2027 list sits on
     mais2red.lvnbb.de, whose robots.txt disallows it, so it is never requested (only same-host links are taken).
  Not read: HH (esf-hamburg.de) and ST (eufonds.sachsen-anhalt.de) reset the connection; BW (no XLSX); HB
  (robots 403); federal ESF list (robots: /SiteGlobals/ disallowed).

Fetch: robots.txt of every host is read BEFORE any other request in this run (funding_officers.robots_gate,
fail-closed, also when the file is already in the disk cache), then crawl-delay or >= 1 s per host.

Amounts: award.betrag = the total (eligible) cost of the operation exactly as the list states it ("Gesamtkosten des
Vorhabens" / "Gesamtbetrag der förderfähigen Ausgaben" / "bewilligte förderfähige Gesamtkosten"); the EU
contribution is stored as given in funding_esf_vorhaben.eu_beitrag (NI, BE state it; BY, NW, TH, RP, BB give only
the co-financing rate, stored as text in kofi_satz, never multiplied out). The locator says which is which.

Filter (as Berlin/Hamburg, funding_manual.classify; adjustments documented in research/funding_esf.md):
  core      = homelessness core terms in the operation title (Bezeichnung des Vorhabens);
  adjacent  = the title has none, but the description names homeless people as the target group
              (TARGET_RE: "wohnungslose Frauen", "obdachlosen oder suchtkranken Menschen", "Menschen ohne Obdach")
              and no refugee context. ESF lists carry no granting authority, so the adjacent-only vocabulary
              (Suppenküche, Streetwork ...) that Berlin/Hamburg accept from a social authority is not used.
Berlin: kept rows are compared with the Berlin Zuwendungsdatenbank awards (funding_traeger) before writing; a row
with the same recipient + purpose and the same amount (+-1 EUR) or an overlapping year is a duplicate and is not
written (listed in funding_esf_vorhaben with status 'dup_zuwdb' and the ZUWDB award id).

Rules: organisations only (natural persons / sole traders skipped, not stored); protected shelters keep the money
at Land level only (no place, purpose redacted); orgs via common.ensure_org (schema 6, legal_form_norm from the
name; the lists carry no register or USt-ID); licence: none stated on any list page -> EU publication duty, facts
only, redistribute_fulltext=0 (Lead, 2026-11-23).

Worker entry points (never data/atlas.db):
  python3 -m ingest.domains.funding_esf --test
  python3 -m ingest.domains.funding_esf --selftest --db /tmp/x.db
The real DB is written only by the runner: python3 -m ingest.run funding_esf.
"""
from __future__ import annotations

import hashlib
import html as _html
import json
import re
import sqlite3
import sys
import time
from urllib.parse import urljoin, urlparse

from ingest import common

DOMAIN = "funding_esf"
ART49 = ("no licence stated on the list page; list of operations published under Art. 49(3) Regulation (EU) "
         "2021/1060 (EU transparency duty); facts only with citation, redistribute_fulltext=0")
ART115 = ("no licence stated on the list page; list of operations published under Art. 115(2) Regulation (EU) "
          "1303/2013 (ESF 2014-2020 transparency duty); facts only with citation, redistribute_fulltext=0")

LAENDER = {
    "NI": {"page": "https://www.europa-fuer-niedersachsen.niedersachsen.de/startseite/regionen_und_foerderung/"
                   "efre_und_esf/liste-der-vorhaben-152610.html",
           "link": r"Liste_der_Vorhaben_ESF_Stand_[\d.]+\.xlsx$", "period": "2021-2027",
           "publisher": "Land Niedersachsen, EU-Verwaltungsbehörde (Quelle: NBank)"},
    "BY": {"page": "https://www.esf.bayern.de/esf-bayern/zahlen/", "link": r"/liste_der_vorhaben\.xlsx$",
           "period": "2021-2027", "publisher": "Bayerisches Staatsministerium für Familie, Arbeit und Soziales, ESF-Verwaltungsbehörde"},
    "NW": {"page": "https://www.mags.nrw/esf-2021-2027-antrag", "link": r"esf_2021-2027_liste_der_vorhaben\.xlsx$",
           "period": "2021-2027", "publisher": "Ministerium für Arbeit, Gesundheit und Soziales NRW, ESF-Verwaltungsbehörde"},
    "TH": {"page": "https://www.esf-thueringen.de/liste-der-vorhaben-1", "link": r"Liste_der_Vorhaben[^/]*\.xlsx$",
           "period": "2021-2027", "publisher": "Freistaat Thüringen, Verwaltungsbehörde ESF"},
    "RP": {"page": "https://esf.rlp.de/service/liste-der-vorhaben", "link": r"Liste_der_Vorhaben[^/]*\.xlsx$",
           "period": "2021-2027", "publisher": "Land Rheinland-Pfalz, ESF-Verwaltungsbehörde (MASTD)"},
    "BE": {"page": "https://www.berlin.de/sen/wirtschaft/gruenden-und-foerdern/europaeische-strukturfonds/"
                   "esf-foerderperiode-2021-2027/buergerinnen-und-buerger/artikel.1215438.php",
           "link": r"liste_der_vorhaben\.xlsx(\?|$)", "period": "2021-2027",
           "publisher": "Land Berlin, ESF-Verwaltungsbehörde (Senatsverwaltung für Arbeit, Soziales, Gleichstellung, Integration, Vielfalt und Antidiskriminierung)"},
    "BB": {"page": "https://esf.brandenburg.de/esf/de/aktuelles/projekte-in-brandenburg/",
           "link": r"Liste_der_Vorhaben_\d+[^/]*\.xlsx$", "period": "2014-2020",
           "publisher": "Land Brandenburg, ESF-Verwaltungsbehörde (MSGIV)"},
}


# --------------------------------------------------------------------------------------------- #
# robots-first fetch
# --------------------------------------------------------------------------------------------- #
def esf_fetch(url: str, cfg: dict) -> bytes:
    """robots.txt of the host first (fresh in this run, fail-closed, also for cached files), then cache or a
    request at >= max(crawl-delay, 1 s) per host."""
    from ingest.domains import funding_officers as fo
    fx = cfg.get("esf_fixture")
    if fx is not None:
        if not fo.robots_ok(url, cfg):
            raise fo.RobotsRefused(f"robots.txt refuses {url}")
        cfg.setdefault("_esf_log", []).append(url)
        return fx[url]
    origin = fo._origin(url)
    first = origin not in fo._ROBOTS
    fo.robots_gate(url, cfg, domain=DOMAIN, cached_ok=False)
    force = bool(cfg.get("force"))
    if not force and common.cached_path(DOMAIN, url) is not None:
        return common.fetch(url, domain=DOMAIN)
    if first:
        fo._HOST_LAST[origin] = time.monotonic()
    robots = fo._ROBOTS.get(origin)
    delay = max(robots[1] or 0, 1.0) if isinstance(robots, tuple) else 1.0
    gap = time.monotonic() - fo._HOST_LAST.get(origin, 0.0)
    if gap < delay:
        time.sleep(delay - gap)
    try:
        return common.fetch(url, domain=DOMAIN, force=force)
    finally:
        fo._HOST_LAST[origin] = time.monotonic()


def discover(land: str, cfg: dict) -> tuple[str, str]:
    """The list page -> its XLSX link (same host only) and the page's Art. 49 statement, if any."""
    conf = LAENDER[land]
    t = esf_fetch(conf["page"], cfg).decode("utf-8", "replace")
    host = urlparse(conf["page"]).netloc
    links = []
    for h in re.findall(r'href="([^"]+)"', t):
        u = urljoin(conf["page"], _html.unescape(h))
        if urlparse(u).netloc == host and re.search(conf["link"], u, re.I) and u not in links:
            links.append(u)
    if not links:
        raise RuntimeError(f"{land}: no list XLSX on {conf['page']}")
    txt = re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", t)))
    m = re.search(r"[^.]{0,200}(?:Art(?:ikel|\.)\s*49\s*(?:Abs\.\s*3|\(3\)))[^.]{0,200}\.?", txt)
    return links[0], (m.group(0).strip() if m else "")


# --------------------------------------------------------------------------------------------- #
# header mapping (the lists share the Art. 49 columns but not their order or wording)
# --------------------------------------------------------------------------------------------- #
COLS = [  # key, regex on the lower-cased, whitespace-collapsed header cell; first matching column wins
    ("empf", r"begünstigt|zuwendungsempfänger|^beneficiary"),
    ("titel", r"bezeichnung des vorhabens|vorhabensbezeichnung|projekttitel|operation name"),
    ("zweck", r"zweck|zusammenfassung|projektkurzbeschreibung|purpose"),
    ("beginn", r"beginn|start"),
    ("ende", r"abschluss|ende|completion|end ?date"),
    ("gesamt", r"gesamtkosten|gesamtbetrag|förderfähige ge|total cost"),
    ("eu", r"unionsbeitrag|esf\+?-mittel|eu contribution"),
    ("satz", r"kofinanzierungssatz|kofi-satz|co-?financing rate"),
    ("id", r"code des vorhabens|projektnummer|aktenzeichen|operation id|projekt-? ?code|^id$"),
    ("ort", r"standortindikator|durchführungsort|ort des vorhabens|location"),
]


def _hnorm(s) -> str:
    return re.sub(r"\s+", " ", re.sub(r"(?<=\w)-\s+(?=[a-zäöü])", "", str(s or ""))).strip().lower()


def find_header(rows) -> tuple[int, dict[str, int]]:
    for i, r in enumerate(rows[:20]):
        hm: dict[str, int] = {}
        for ci, c in enumerate(r):
            h = _hnorm(c)
            if not h:
                continue
            for k, rx in COLS:
                if k not in hm and re.search(rx, h):
                    hm[k] = ci
                    break
        if "empf" in hm and "gesamt" in hm:
            return i, hm
    raise ValueError("no Liste-der-Vorhaben header (beneficiary + total cost) in the first 20 rows")


def _num(v) -> float | None:
    from ingest.domains import funding_manual as fman
    a = fman.amount(v)
    if a is None:
        a = fman._de_amount(re.sub(r"[€\s]", "", str(v or "")))
    return a


def _date(v) -> str | None:
    from ingest.domains import funding_manual as fman
    return fman._xl_date(v) if common.clean(v) else None


# --------------------------------------------------------------------------------------------- #
# filter
# --------------------------------------------------------------------------------------------- #
TARGET_RE = re.compile(
    r"\b(?:wohnungslos|obdachlos)\w*\s+(?:[\wäöüß*:/-]+\s+){0,2}?(?:menschen|frauen|m[äa]e?nner|personen|familien|"
    r"m[üu]e?tter|eu-b[üu]e?rger\w*|eu-migrant\w*)\b|\bmenschen ohne (?:obdach|wohnung)\b", re.I)


FLOAT_ARTIFACT = re.compile(r"\.\d*(?:0{6,}|9{6,})\d{0,3}$")


def classify(titel: str | None, zweck: str | None) -> tuple[str | None, list[str]]:
    from ingest.domains import funding_manual as fman
    from ingest.domains import funding_traeger as ft
    tier, terms = fman.classify(titel, None)
    if tier == "core":
        return "core", terms
    z = zweck or ""
    hits = sorted({m.group(0).lower() for m in TARGET_RE.finditer(z)})
    if hits and not ft.REFUGEE_RE.search(f"{titel or ''} {z}"):
        return "adjacent", hits
    return None, []


# --------------------------------------------------------------------------------------------- #
# Berlin: dedupe against the Berlin Zuwendungsdatenbank (funding_traeger awards)
# --------------------------------------------------------------------------------------------- #
def _toks(s) -> set[str]:
    return {t for t in re.findall(r"[a-zäöüß0-9]+", (s or "").lower()) if len(t) > 2}


def zuwdb_rows(conn) -> list[dict]:
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='source'").fetchone():
        return []
    return [dict(r) for r in conn.execute(
        "SELECT a.id, a.foerder_schluessel, a.empfaenger, a.empfaenger_norm, a.org_id, a.zweck, a.betrag, "
        "a.haushaltsjahr FROM award a JOIN source s ON s.id = a.source_id "
        "WHERE s.domain = 'funding_traeger' AND coalesce(a.foerderart, 'zuwendung') = 'zuwendung'")]


def zuwdb_match(z: list[dict], name: str, org_id: int | None, titel: str, gesamt: float | None,
                y0: int | None, y1: int | None) -> dict | None:
    nn = common.name_norm(name) or ""
    head = nn.split()[:2]
    tt = _toks(titel)
    cands = []
    for a in z:
        an = a["empfaenger_norm"] or common.name_norm(a["empfaenger"]) or ""
        same_rec = (an == nn) or (org_id is not None and a["org_id"] == org_id) or (head and an.split()[:2] == head)
        if not same_rec:
            continue
        at = _toks(a["zweck"])
        if not (tt and (tt == at or len(tt & at) / max(1, len(tt | at)) >= 0.6)):
            continue
        cands.append(a)
    # 1st: same amount (+-1 EUR, ZUWDB rounds to whole euros); 2nd: a ZUWDB year inside the ESF period
    for a in cands:
        if gesamt is not None and a["betrag"] is not None and abs(a["betrag"] - gesamt) <= 1.0:
            return a
    for a in cands:
        try:
            hj = int(str(a["haushaltsjahr"])[:4])
        except (TypeError, ValueError):
            continue
        if y0 is not None and y0 <= hj <= (y1 or y0):
            return a
    return None


# --------------------------------------------------------------------------------------------- #
# reader
# --------------------------------------------------------------------------------------------- #
DDL = """
CREATE TABLE IF NOT EXISTS funding_esf_vorhaben (
  award_key      TEXT PRIMARY KEY,      -- DE-ESF-<Land>:<operation id> (or :r<hash> when the list has no id)
  land           TEXT,
  periode        TEXT,                  -- 2021-2027 / 2014-2020
  vorhaben_id    TEXT,
  source_id      INTEGER,
  datei          TEXT,
  blatt          TEXT,
  zeile          INTEGER,
  empfaenger     TEXT,
  titel          TEXT,
  beginn         TEXT,
  ende           TEXT,
  gesamtkosten   REAL,                  -- as stated (total / total eligible cost) = award.betrag
  eu_beitrag     REAL,                  -- EU contribution as stated; NULL where the list gives only the rate
  kofi_satz      TEXT,                  -- Union co-financing rate as stated
  ort            TEXT,                  -- NULL for protected shelters
  tier           TEXT,
  matched_terms  TEXT,
  status         TEXT,                  -- award | dup_zuwdb | held_g9_float
  zuwdb_award_id INTEGER                -- Berlin: the Zuwendungsdatenbank award this row duplicates
);
"""


def run_land(conn, land: str, cfg: dict, z: list[dict]) -> dict:
    from ingest.domains.institutions_media_orgs import iter_xlsx_sheets
    from ingest.domains import funding_manual as fman
    from ingest.domains import funding_traeger as ft
    conf = LAENDER[land]
    url, stmt = discover(land, cfg)
    data = esf_fetch(url, cfg)
    sheets = iter_xlsx_sheets(data)
    sheet, rows = max(sheets.items(), key=lambda kv: len(kv[1]))
    hi, hm = find_header(rows)
    lic = (ART115 if conf["period"] == "2014-2020" else ART49) + (f'; page states: "{stmt}"' if stmt else "")
    fn = urlparse(url).path.rsplit("/", 1)[-1]
    st = {"rows": 0, "core": 0, "adjacent": 0, "kept": 0, "persons": 0, "protected": 0, "no_amount": 0,
          "dup_zuwdb": 0, "held_float": 0, "held": [], "eur": 0.0, "recipients": set(), "years": {}, "dups": [], "org_none": 0, "links": {}}
    sid = None

    def g(r, k):
        return r[hm[k]] if k in hm and hm[k] < len(r) else ""

    for ri in range(hi + 1, len(rows)):
        r = rows[ri]
        name = common.clean(g(r, "empf"))
        gesamt = _num(g(r, "gesamt"))
        if not name or gesamt is None:
            continue                                 # blank rows, the second (English/German) header row
        st["rows"] += 1
        titel, zweck = common.clean(g(r, "titel")) or "", common.clean(g(r, "zweck")) or ""
        tier, terms = classify(titel, zweck)
        if not tier:
            continue
        if fman.is_person(name):
            st["persons"] += 1
            continue
        protected = ft.is_protected(f"{titel} {zweck} {name}")
        st["protected"] += protected
        vid = common.clean(g(r, "id"))
        b0, b1 = _date(g(r, "beginn")), _date(g(r, "ende"))
        key = f"DE-ESF-{land}:" + (vid or "r" + hashlib.sha1(
            f"{name}|{titel}|{b0}|{gesamt}".encode()).hexdigest()[:12])
        y0 = int(b0[:4]) if b0 else None
        y1 = int(b1[:4]) if b1 else None
        if sid is None:
            sid = common.source_id_for(conn, url, DOMAIN, title=f"ESF Plus Liste der Vorhaben {land} ({conf['period']}), "
                                       f"{fn}", publisher=conf["publisher"], license=lic)
            conn.execute("UPDATE source SET redistribute_fulltext=0 WHERE id=?", (sid,))
        eu = _num(g(r, "eu")) if "eu" in hm else None
        side = {"award_key": key, "land": land, "periode": conf["period"], "vorhaben_id": vid, "source_id": sid,
                "datei": fn, "blatt": sheet, "zeile": ri + 1, "empfaenger": name,
                "titel": ft.redact_place(titel) if protected else titel, "beginn": b0, "ende": b1,
                "gesamtkosten": round(gesamt, 2), "eu_beitrag": None if eu is None else round(eu, 2),
                "kofi_satz": common.clean(g(r, "satz")), "ort": None if protected else common.clean(g(r, "ort")),
                "tier": tier, "matched_terms": json.dumps(terms, ensure_ascii=False)}
        if land == "BE":
            pre = common.find_org(conn, name, land)["org_id"]
            dup = zuwdb_match(z, name, pre, titel, gesamt, y0, y1)
            if dup:
                st["dup_zuwdb"] += 1
                st["dups"].append(f"row {ri + 1} {name} – {titel} (EUR {gesamt:,.2f}) = ZUWDB award {dup['id']} "
                                  f"({dup['foerder_schluessel']}, {dup['haushaltsjahr']}, EUR {dup['betrag']:,.2f})")
                common.upsert(conn, "funding_esf_vorhaben", {**side, "status": "dup_zuwdb", "zuwdb_award_id": dup["id"]},
                              keys=["award_key"])
                continue
        raw = str(common.clean(g(r, "gesamt")) or "")
        if FLOAT_ARTIFACT.search(raw) and not cfg.get("esf_float_ok", True):
            # the file stores e.g. 19980.240000000002; lead/core fcfbfa3 G9 matches such cells to the cent, so these
            # rows are written by default (esf_float_ok=True); esf_float_ok=False holds them (side table only)
            st["held_float"] += 1
            st["held"].append(f"row {ri + 1} {name} (cell {raw})")
            common.upsert(conn, "funding_esf_vorhaben", {**side, "status": "held_g9_float", "zuwdb_award_id": None},
                          keys=["award_key"])
            continue
        org_id = ft.ensure_org_xland(conn, name, land, sid, stats=st, is_protected=1 if ft.is_protected(name) else None,
                                     record_kind="award", record_key=key)
        st["org_none"] += org_id is None
        common.upsert(conn, "funding_esf_vorhaben", {**side, "status": "award", "zuwdb_award_id": None},
                      keys=["award_key"])
        col = common.xlsx_col(hm["gesamt"])
        eu_txt = (f"EU-Beitrag laut Liste EUR {eu:,.2f} (Spalte {common.xlsx_col(hm['eu'])})" if eu is not None
                  else f"EU-Beitrag nicht ausgewiesen, Kofinanzierungssatz {side['kofi_satz'] or '–'}")
        common.upsert(conn, "award", {
            "foerder_schluessel": key, "foerder_id": vid, "foerderart": "zuwendung",
            "zuwendungsgeber": conf["publisher"], "programm": f"ESF Plus {conf['period']} {land}" if conf["period"]
            == "2021-2027" else f"ESF {conf['period']} {land}",
            "zweck": side["titel"], "empfaenger": name, "empfaenger_norm": common.name_norm(name), "org_id": org_id,
            # the cell value exactly as stored in the file (e.g. 19980.240000000002): verify G9 matches the cell token;
            # round to cents once the Lead's numeric-cell G9 fix is on lead/core
            "betrag": round(gesamt, 2), "currency": "EUR", "haushaltsjahr": y0, "laufzeit_von": b0, "laufzeit_bis": b1,
            "ort_land": land, "is_est": 0,
            "quote": common.xlsx_cell_line(sheet, ri, hm["gesamt"], r),
            "locator": (f"{conf['page']} – Datei {url}, Blatt '{sheet}', Zeile {ri + 1}, Zelle {col}{ri + 1}: "
                        f"Gesamtkosten des Vorhabens (betrag; EUR, total eligible cost, operation period {b0 or '?'} bis {b1 or '?'}); {eu_txt}"),
            "source_id": sid}, keys=["foerder_schluessel"])
        lk = conn.execute("SELECT method FROM org_link WHERE record_kind='award' AND record_key=?", (key,)).fetchone()
        m = lk[0] if lk else "none"
        st["links"][m] = st["links"].get(m, 0) + 1
        st["kept"] += 1
        st[tier] += 1
        st["eur"] += gesamt
        st["recipients"].add(common.name_norm(name))
        if y0:
            st["years"][y0] = st["years"].get(y0, 0) + 1
    st["url"] = url
    return st


def run(conn, cfg=None) -> dict:
    cfg = cfg or {}
    conn.executescript(DDL)
    z = zuwdb_rows(conn)
    rows, notes, sources, stats = 0, [], [], {}
    for land in cfg.get("laender") or list(LAENDER):
        st = run_land(conn, land, cfg, z)
        stats[land] = st
        rows += st["kept"]
        sources.append((st["url"], ART115 if LAENDER[land]["period"] == "2014-2020" else ART49))
        notes.append(f"{land} {LAENDER[land]['period']}: {st['rows']} rows scanned, hits {st['core'] + st['adjacent'] + st['dup_zuwdb']} "
                     f"(kept core {st['core']}, adjacent {st['adjacent']}), {len(st['recipients'])} recipients, "
                     f"EUR {st['eur']:,.2f} (total cost), years "
                     + (",".join(f"{k}:{v}" for k, v in sorted(st["years"].items())) or "-")
                     + f", links {json.dumps(st['links'])}, persons {st['persons']}, protected {st['protected']}"
                     + (f", Berlin ZUWDB duplicates dropped {st['dup_zuwdb']} [" + "; ".join(st["dups"]) + "]"
                        if land == "BE" else "")
                     + f", cross-Land org matches {st.get('xland', 0)}"
                     + (f", held (float cell, G9) {st['held_float']} [" + "; ".join(st["held"]) + "]" if st["held_float"] else ""))
    cfg["_esf_stats"] = stats
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


def _reset_robots():
    from ingest.domains import funding_officers as fo
    fo._ROBOTS.clear()
    fo._HOST_LAST.clear()


_BE_HDR = ["Projektnummer", "Förderinstrument", "Zuwendungsempfänger (Name des Begünstigten)",
           "Projekttitel (Bezeichnung des Vorhabens)", "Projektkurzbeschreibung", "Durchführungsort Bezirk",
           "Durchführungsort Plz (Investitionsort)", "Datum Projektbeginn", "Datum Projektende", "Priorität",
           "Spezifisches Ziel", "Fonds", "Code Interventionsbereich", "Land (Standortindikator)",
           "zum Stichtag  bewilligte förderfähige Gesamtkosten", "zum Stichtag bewilligte ESF+-Mittel"]
_BE_EN = ["Operation ID", "Funding instrument", "Beneficary`s name", "Operation Name", "Purpose of the Operation",
          "Berlin District", "Location Indicator", "Operation Start Date", "Operation End Date", "Priority",
          "Specific Objective ", "Fund concerned", "Type of Intervention", "Country", "Total Cost of the Operation",
          "EU contribution"]


def _be_row(pid, empf, titel, desc, start, end, ges, eu):
    return [pid, "Lokal-Sozial-Innovativ (LSI)", empf, titel, desc, "Pankow", "10119", start, end, "1", "h", "ESF+",
            "163", "DE300", ges, eu]


_BE_ROWS = [
    _be_row("10211512", "BETA Bildung Entwicklung Training Arbeit gGmbH", "Solidarisch gegen Obdachlosigkeit im Bezirk Pankow",
            "Wir begleiten obdachlose Menschen in Arbeit.", "45566", "45747", "45866.720000000001", "18346.689999999999"),
    _be_row("10217997", "My Way Soziale Dienste gGmbH", "EvA- Empowerment durch verlässliche aufsuchende Arbeit",
            "Heranführung von schwer erreichbaren, wohnungslosen Frauen im Bezirk Neukölln an Arbeit.", "46023", "46203",
            "30517.2", "12206.88"),
    _be_row("10212533", "spok sport und kultur GmbH", "Sport und Integration",
            "Wohnungslose Menschen mit Fluchthintergrund brauchen Unterstützung.", "45627", "45808", "49808.41", "19635.7"),
    _be_row("10218066", "Stiftung SPI", "Neue Chancen in Mitte",
            "Von Armut, Wohnungslosigkeit, sozialer Ausgrenzung betroffene Menschen.", "46023", "46203", "46434.78", "18573.91"),
    _be_row("10208356", "Die Wille gGmbH", "optimal digital", "gemeinsam mit einer Anlaufstelle für obdachlose Frauen",
            "45627", "45808", "19980.240000000002", "7992.1"),
    _be_row("10299999", "Erika Mustermann", "Housing First Beratung", "Beratung", "46023", "46203", "1000", "400"),
    _be_row("10197227", "WeTeK Berlin gGmbH", "Starke Ausbildung", "Unterstützung Jugendlicher", "44958", "46418",
            "1405893.37", "562357.35"),
]
_BY_HDR = ["Name des\nBegünstigten\nbeneficiary name", "Bezeichnung des\nVorhabens\noperation name",
           "Projektnummer\noperation ID", "Zweck und Errungenschaften\ndes Projekts\n",
           "Datum des\nBeginns\ndes Vorhabens", "Datum des\nEndes des\nVorhabens",
           "Gesamtbetrag der\nförderfähigen Aus-\ngabe", "Unions-\nKofinanzie-\nrungssatz", "PLZ", "Spezifisches \nZiel",
           "Interventions-\nbereich"]
_BY_ROWS = [
    ["Diakonie Musterstadt e.V.", "Housing-First Musterstadt", "1-10.3-999001", "Wohnungen für obdachlose Menschen",
     "01.03.2024", "28.02.2026", "120000", "0.5", "80331", "SZ (l)", "163"],
    ["bfz gGmbH", "COLA - Coaching", "1-10.3-250334", "Langzeitarbeitslose", "45936", "46094", "177457.68", "0.5",
     "96052", "SZ (h)", "136"],
]

_PAGE_BE = LAENDER["BE"]["page"]
_PAGE_BY = LAENDER["BY"]["page"]
_X_BE = ("https://www.berlin.de/sen/wirtschaft/gruenden-und-foerdern/europaeische-strukturfonds/"
         "esf-foerderperiode-2021-2027/dokumente-a-z/20260731_liste_der_vorhaben.xlsx?ts=1")
_X_BY = "https://www.esf.bayern.de/imperia/md/images/stmas/esf_2022/liste_der_vorhaben.xlsx"
_X_BB_OTHER = "https://mais2red.lvnbb.de/sixcms/media.php/21/Liste_der_Vorhaben_20260831.xlsx"


def _fixture_cfg(**kw) -> dict:
    from ingest.domains.funding_hamburg import mini_xlsx
    be = mini_xlsx([["Liste der Vorhaben des Europäischen Sozialfonds Plus"] + [""] * 15,
                    ["Letzte Aktualisierung: 31.07.2026"] + [""] * 15, _BE_HDR, _BE_EN] + _BE_ROWS, sheet="Projektliste")
    by = mini_xlsx([["Europäischer Sozialfonds Plus (ESF+) 2021-2027"] + [""] * 10,
                    ["Stand 01.06.2026"] + [""] * 10, _BY_HDR] + _BY_ROWS, sheet="Vorhaben")
    page_be = (f'<html><a href="/sen/wirtschaft/gruenden-und-foerdern/europaeische-strukturfonds/esf-foerderperiode-'
               f'2021-2027/dokumente-a-z/20260731_liste_der_vorhaben.xlsx?ts=1">Liste</a></html>').encode()
    page_by = (b'<html><p>Liste der Vorhaben nach Ma\xc3\x9fgabe des Art. 49 (3) der Verordnung (EU) 2021/1060 '
               b'Stand: 01.06.2026</p><a href="/imperia/md/images/stmas/esf_2022/liste_der_vorhaben.xlsx">XLSX</a>'
               b'<a href="https://mais2red.lvnbb.de/sixcms/media.php/21/Liste_der_Vorhaben_20260831.xlsx">x</a></html>')
    robots = {"https://www.berlin.de": 404, "https://www.esf.bayern.de": "User-agent: *\nCrawl-delay: 1\n"}
    return {"robots_fixture": robots, "esf_fixture": {_PAGE_BE: page_be, _X_BE: be, _PAGE_BY: page_by, _X_BY: by},
            "laender": ["BY", "BE"], **kw}


def _seed_zuwdb(conn):
    """One Berlin Zuwendungsdatenbank award (domain funding_traeger) that duplicates the BETA ESF row."""
    sid = common.source_id_for(conn, "https://www.berlin.de/sen/finanzen/service/zuwendungsdatenbank/test",
                               "funding_traeger", title="ZUWDB test", publisher="Berlin", license="test")
    oid = common.ensure_org(conn, "BETA Bildung Entwicklung Training Arbeit gGmbH", "BE", sid)
    common.upsert(conn, "award", {"foerder_schluessel": "DE-BE-ZUWDB:test1", "foerderart": "zuwendung",
                                  "zweck": "Solidarisch gegen Obdachlosigkeit im Bezirk Pankow",
                                  "empfaenger": "BETA Bildung Entwicklung Training Arbeit gGmbH",
                                  "empfaenger_norm": common.name_norm("BETA Bildung Entwicklung Training Arbeit gGmbH"),
                                  "org_id": oid, "betrag": 45867.0, "currency": "EUR", "haushaltsjahr": 2025,
                                  "ort_land": "BE", "is_est": 0, "quote": "x", "locator": "x", "source_id": sid},
                  keys=["foerder_schluessel"])


def _test_header_and_classify():
    hi, hm = find_header([["t"], [""], _BE_HDR, _BE_EN])
    assert hi == 2 and hm["empf"] == 2 and hm["titel"] == 3 and hm["zweck"] == 4 and hm["beginn"] == 7 \
        and hm["ende"] == 8 and hm["gesamt"] == 14 and hm["eu"] == 15 and hm["id"] == 0, hm
    hi, hm = find_header([["x"], _BY_HDR])
    assert hm["gesamt"] == 6 and hm["satz"] == 7 and "eu" not in hm and hm["ende"] == 5 and hm["beginn"] == 4, hm
    nrw_en = ["Beneficiary", "Operation name", "Purpose and expected achievements ", "Start\ndate", "End\ndate",
              "Total cost \n(€)", "Fund", "Specific objective", "Union co-financing rate", "Location Indicator/\nPostal Code",
              "Location Indicator/\nLocation", "Country", "Interven-tion type", "ID"]
    hi, hm = find_header([nrw_en])
    assert hm["empf"] == 0 and hm["ende"] == 4 and hm["gesamt"] == 5 and hm["id"] == 13 and hm["satz"] == 8, hm
    assert classify("Solidarisch gegen Obdachlosigkeit in Pankow", "")[0] == "core"
    assert classify("Housing-First Musterstadt", "")[0] == "core"
    assert classify("EvA", "Ziel ist ..., wohnungslosen Frauen im Bezirk")[0] == "adjacent"
    assert classify("Sozialraum", "vulnerabler Gruppen wie obdachlosen oder suchtkranken Menschen")[0] == "adjacent"
    assert classify("Nachhaltige Integration Wohnungs- und Obddachloser", "mit Menschen ohne Obdach")[0] == "adjacent"
    assert classify("Sport", "Wohnungslose Menschen mit Fluchthintergrund")[0] is None          # refugee context
    assert classify("Roma", "von Armut, Wohnungslosigkeit, sozialer Ausgrenzung betroffene")[0] is None
    assert classify("Kooperation", "Suppenküche und Streetwork")[0] is None                    # no authority in ESF


def _test_reader():
    _reset_robots()
    conn = memory_conn()
    _seed_zuwdb(conn)
    cfg = _fixture_cfg()
    res = run(conn, cfg)
    st = cfg["_esf_stats"]
    assert st["BY"]["rows"] == 2 and st["BY"]["core"] == 1 and st["BY"]["kept"] == 1, st["BY"]
    assert st["BE"]["rows"] == 7 and st["BE"]["dup_zuwdb"] == 1 and st["BE"]["kept"] == 2 and st["BE"]["persons"] == 1, st["BE"]
    assert st["BE"]["held_float"] == 0 and conn.execute(
        "SELECT betrag FROM award WHERE foerder_schluessel='DE-ESF-BE:10208356'").fetchone()[0] == 19980.24
    _reset_robots()
    c2 = memory_conn()
    cfg2 = _fixture_cfg(esf_float_ok=False, laender=["BE"])
    run(c2, cfg2)
    assert cfg2["_esf_stats"]["BE"]["held_float"] == 2 and c2.execute(
        "SELECT status FROM funding_esf_vorhaben WHERE award_key='DE-ESF-BE:10208356'").fetchone()[0] == "held_g9_float"
    assert FLOAT_ARTIFACT.search("299839.96000000002") and FLOAT_ARTIFACT.search("45866.720000000001") \
        and FLOAT_ARTIFACT.search("0.58509999999999995") and not FLOAT_ARTIFACT.search("30517.2") \
        and not FLOAT_ARTIFACT.search("120000")
    a = conn.execute("SELECT * FROM award WHERE foerder_schluessel='DE-ESF-BY:1-10.3-999001'").fetchone()
    assert a["betrag"] == 120000 and a["laufzeit_von"] == "2024-03-01" and a["ort_land"] == "BY", dict(a)
    assert "EUR, total eligible cost, operation period 2024-03-01 bis 2026-02-28" in a["locator"], a["locator"]
    assert "Zelle G4" in a["locator"] and _X_BY in a["locator"] and "nicht ausgewiesen" in a["locator"], a["locator"]
    assert a["quote"].startswith("[Vorhaben!G4]"), a["quote"]
    b = conn.execute("SELECT * FROM award WHERE foerder_schluessel='DE-ESF-BE:10217997'").fetchone()
    assert b["betrag"] == 30517.2 and "EU-Beitrag laut Liste EUR 12,206.88" in b["locator"], b["locator"]
    v = conn.execute("SELECT * FROM funding_esf_vorhaben WHERE award_key='DE-ESF-BE:10211512'").fetchone()
    assert v["status"] == "dup_zuwdb" and v["eu_beitrag"] == 18346.69
    assert conn.execute("SELECT count(*) FROM award WHERE foerder_schluessel='DE-ESF-BE:10211512'").fetchone()[0] == 0
    assert conn.execute("SELECT count(*) FROM org WHERE name LIKE '%Mustermann%'").fetchone()[0] == 0
    assert conn.execute("SELECT redistribute_fulltext FROM source WHERE url=?", (_X_BY,)).fetchone()[0] == 0
    lic = conn.execute("SELECT license FROM source WHERE url=?", (_X_BY,)).fetchone()[0]
    assert "Art. 49(3)" in lic and "page states" in lic, lic
    assert _X_BB_OTHER not in cfg["_esf_log"]                     # other-host link never requested
    assert "duplicates dropped 1" in res["notes"], res["notes"]
    _reset_robots()


def _test_robots_fail_closed():
    _reset_robots()
    bad = _fixture_cfg(robots_fixture={"https://www.esf.bayern.de": "error", "https://www.berlin.de": 404},
                       laender=["BY"])
    try:
        run(memory_conn(), bad)
        raise AssertionError("fetched without robots.txt")
    except Exception as e:  # noqa: BLE001
        assert type(e).__name__ == "RobotsRefused", e
    assert not bad.get("_esf_log")
    _reset_robots()
    dis = _fixture_cfg(robots_fixture={"https://www.esf.bayern.de": "User-agent: *\nDisallow: /imperia/\n"},
                       laender=["BY"])
    try:
        run(memory_conn(), dis)
        raise AssertionError("disallowed file fetched")
    except Exception as e:  # noqa: BLE001
        assert type(e).__name__ == "RobotsRefused", e
    assert _X_BY not in dis.get("_esf_log", [])
    _reset_robots()


def _test_zuwdb_match():
    z = [{"id": 48, "foerder_schluessel": "a", "empfaenger": "BETA gGmbH", "empfaenger_norm": common.name_norm("BETA gGmbH"),
          "org_id": None, "zweck": "Solidarisch gegen Obdachlosigkeit im Bezirk Pankow", "betrag": 45867.0, "haushaltsjahr": 2025},
         {"id": 49, "foerder_schluessel": "b", "empfaenger": "BETA gGmbH", "empfaenger_norm": common.name_norm("BETA gGmbH"),
          "org_id": None, "zweck": "Solidarisch gegen Obdachlosigkeit in Pankow", "betrag": 294510.0, "haushaltsjahr": 2025}]
    assert zuwdb_match(z, "BETA gGmbH", None, "Solidarisch gegen Obdachlosigkeit in Pankow", 294509.49, 2025, 2027)["id"] == 49
    assert zuwdb_match(z, "BETA gGmbH", None, "Solidarisch gegen Obdachlosigkeit im Bezirk Pankow", 45866.72, 2024, 2025)["id"] == 48
    assert zuwdb_match(z, "Andere gGmbH", None, "Solidarisch gegen Obdachlosigkeit in Pankow", 294509.49, 2025, 2027) is None
    assert zuwdb_match(z, "BETA gGmbH", None, "Ganz anderes Projekt", 294509.49, 2025, 2027) is None
    assert zuwdb_match(z, "BETA gGmbH", None, "Solidarisch gegen Obdachlosigkeit in Pankow", 1.0, 2019, 2020) is None


TESTS = [_test_header_and_classify, _test_zuwdb_match, _test_reader, _test_robots_fail_closed]


def _run_tests():
    for t in TESTS:
        t()
        print("PASS", t.__name__)


def _selftest(db: str):
    """Live (robots-gated, cache-backed) run into a scratch DB; the runner's transaction is rolled back."""
    from ingest import run as runner
    from ingest.domains.funding_traeger import scratch_db_path
    conn = runner.open_db(scratch_db_path(["--selftest", "--db", db]))
    conn.execute("BEGIN IMMEDIATE")
    conn.runner_txn = True
    try:
        res = run(conn, {})
        print(f"[{DOMAIN}] selftest rows={res['rows']}")
        print(f"[{DOMAIN}]   {res['notes']}")
        assert conn.execute("SELECT count(*) FROM award WHERE foerder_schluessel LIKE 'DE-ESF-%' AND "
                            "(quote IS NULL OR betrag IS NULL)").fetchone()[0] == 0
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        conn.runner_txn = False
        conn.execute("ROLLBACK")
        conn.close()


def _cli(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="python3 -m ingest.domains.funding_esf", allow_abbrev=False,
                                 description="Worker tools. data/atlas.db is written only by "
                                             "`python3 -m ingest.run funding_esf`.")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--test", action="store_true", help="offline unit tests (in-memory SQLite)")
    mode.add_argument("--selftest", action="store_true", help="live run into a scratch DB (needs --db)")
    ap.add_argument("--db", help="--selftest: scratch DB path (never atlas.db)")
    a = ap.parse_args(argv)
    if a.db and not a.selftest:
        ap.error("--db is only valid with --selftest")
    if a.test:
        _run_tests()
    else:
        if not a.db:
            ap.error("--selftest needs --db <scratch path>")
        _selftest(a.db)
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
