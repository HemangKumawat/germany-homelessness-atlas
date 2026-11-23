"""funding_mv -- Mecklenburg-Vorpommern Zuwendungen for homelessness work (LAGuS Zuwendungsverzeichnis, WoftG M-V).

Source: the Zuwendungsverzeichnis of the Landesamt für Gesundheit und Soziales Mecklenburg-Vorpommern (LAGuS,
Abteilung Förderangelegenheiten), published under § 12 Abs. 2 Wohlfahrtsfinanzierungs- und -transparenzgesetz
(WoftG M-V) on http://www.zuwendung-mv.de/ ("Zuwendungsdatenbank des Landes Mecklenburg-Vorpommern"): one PDF
listing every Zuwendung of the year to the Spitzenverbände and Träger of social work (lfd. Nr., Zuwendungs-
empfänger, Gegenstand / Zweck, Bewilligungszeitraum von–bis, Höhe der Zuwendung in EUR). The edition online on
2026-11-23 covers 2020 (663 grants, 68 pages). Why this source and not others: research/funding_nonberlin_survey.md.

How the file is found (robots-first; INGEST_CONTRACT §2, worker rules):
  1. robots.txt of www.zuwendung-mv.de is read before any other request (2026-11-23: no rules), 1 req/s;
  2. the start page -> its link to the PDF (zuwendung.pdf, relative) -> the PDF (archived under data/raw/funding_mv).

Parsing: the PDF is a layout table whose cells wrap over several lines and are vertically centred on the line that
holds "lfd. Nr.", the two dates and the amount (the anchor line). The reader takes word boxes (pdftotext -bbox),
finds per page the anchor lines, the date column (the last two dates on anchor lines) and the empty vertical gutter
between the Empfänger and the Zweck column, and gives every wrapped line to the anchor whose cell it belongs to (a
cell spans the same height above and below its anchor). The cited quote is the anchor line exactly as
pdftotext -layout renders it (the text verify archives), which holds the lfd. Nr., dates and amount.

Filter (research/funding_mv.md), on the Zweck text like Berlin/Hamburg: funding_traeger.BZ_CORE plus
"Straßenzeitung" / "Obdach..." (as in Hamburg) -> core; BZ_ADJACENT -> adjacent unless the text names a refugee
context. Every row (in scope or not) is kept in funding_mv_zuwendung for later use; award rows only for the scope.

Pass-through: the Spitzenverbände forward Liga funds to member organisations ("ASB OV Hagenow/Ludwigslust: ...",
"... organisiert vom Kreisdiakonischen Werk Greifswald e.V."). The award recipient is the one the document names
as Zuwendungsempfänger; the executing member is stored as text (durchfuehrung) only, no org row is inferred.

Rules kept: organisations only (natural persons / sole traders / GbR skipped, funding_traeger.ted_is_person, their
rows are not stored at all); protected shelters (Frauenhaus etc.) keep their money in the side table but neither
Zweck nor place (Land level only); orgs only via common.ensure_org (schema 6, legal_form_norm from the name, no tags
in name_norm); nothing estimated. Licence: none stated; statutory publication, facts only (see docs/SOURCES.md).

Worker entry points (never data/atlas.db):
  python3 -m ingest.domains.funding_mv --test                      offline tests
  python3 -m ingest.domains.funding_mv --selftest --db /tmp/x.db   live run, scratch DB, rolled back
The real DB is written only by the runner: python3 -m ingest.run funding_mv.
"""
from __future__ import annotations

import html as _html
import json
import re
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

from ingest import common

DOMAIN = "funding_mv"
INDEX = "http://www.zuwendung-mv.de/"
PUBLISHER = "Landesamt für Gesundheit und Soziales Mecklenburg-Vorpommern (LAGuS), Abteilung Förderangelegenheiten"
GEBER = "Landesamt für Gesundheit und Soziales Mecklenburg-Vorpommern (LAGuS)"
LICENSE = ("no licence stated; statutory publication under § 12 Abs. 2 WoftG M-V (Zuwendungsverzeichnis), "
           "used for facts only (recipient, purpose, period, amount) with citation; zuwendung-mv.de robots.txt: no rules")
MV_LAND = "MV"


# --------------------------------------------------------------------------------------------- #
# robots-first fetch (shared gate of the funding modules), >= 1 s per host
# --------------------------------------------------------------------------------------------- #
def mv_fetch(url: str, cfg: dict) -> bytes:
    from ingest.domains import funding_officers as fo
    fx = cfg.get("mv_fixture")
    if fx is not None:
        if not fo.robots_ok(url, cfg):
            raise fo.RobotsRefused(f"robots.txt refuses {url}")
        cfg.setdefault("_mv_log", []).append(url)
        return fx[url]
    force = bool(cfg.get("force"))
    if not force and common.cached_path(DOMAIN, url) is not None:
        return common.fetch(url, domain=DOMAIN)
    origin = fo._origin(url)
    first = origin not in fo._ROBOTS
    fo.robots_gate(url, cfg, domain=DOMAIN, cached_ok=False)
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


def discover(cfg: dict) -> str:
    """The PDF link on the start page (same host, *.pdf)."""
    t = mv_fetch(INDEX, cfg).decode("utf-8", "replace")
    links = [urljoin(INDEX, _html.unescape(h)) for h in re.findall(r'href="([^"]+)"', t)]
    pdfs = [u for u in links if re.search(r"(?i)\.pdf$", urlparse(u).path) and urlparse(u).netloc == urlparse(INDEX).netloc]
    if not pdfs:
        raise RuntimeError("no Zuwendungsverzeichnis PDF linked on " + INDEX)
    return pdfs[0]


# --------------------------------------------------------------------------------------------- #
# PDF table parser
# --------------------------------------------------------------------------------------------- #
DATE = re.compile(r"^\d{2}\.\d{2}\.\d{4}$")
AMOUNT = re.compile(r"^-?\d{1,3}(?:\.\d{3})*,\d{2}$")
_WORD = re.compile(r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">([^<]*)</word>')


def bbox_pages(pdf: bytes) -> list[list[tuple]]:
    with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
        f.write(pdf)
        f.flush()
        out = subprocess.run(["pdftotext", "-bbox", f.name, "-"], capture_output=True, check=True).stdout
    return [[(float(a), float(b), float(c), float(d), _html.unescape(t)) for a, b, c, d, t in _WORD.findall(pg)]
            for pg in re.findall(r"(?s)<page[^>]*>(.*?)</page>", out.decode("utf-8", "replace"))]


def layout_text(pdf: bytes) -> str:
    """The text verify archives for a PDF (common.document_text = pdftotext -layout)."""
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "x.pdf"
        p.write_bytes(pdf)
        return common.document_text(p, "application/pdf") or ""


def _ym(w):
    return (w[1] + w[3]) / 2


def _join(lines: list[str]) -> str:
    """Wrapped cell lines -> one string; 'Mecklenburg-' + 'Vorpommern' -> 'Mecklenburg-Vorpommern'."""
    out = ""
    for ln in lines:
        ln = ln.strip()
        if not ln:
            continue
        if out.endswith("-") and not out.endswith(" -") and ln[:1].isupper():
            out += ln
        else:
            out = f"{out} {ln}" if out else ln
    return common.clean(out) or ""


def _cell_lines(words: list[tuple]) -> list[tuple[float, str]]:
    ls: dict[float, list] = {}
    for w in words:
        y = _ym(w)
        k = next((k for k in ls if abs(k - y) < 2.5), y)
        ls.setdefault(k, []).append(w)
    return sorted((k, " ".join(x[4] for x in sorted(v))) for k, v in ls.items())


def _assign(lines: list[tuple[float, str]], ay: list[float]) -> list[list[str]]:
    """Give each wrapped line to its anchor: a cell's lines start above its anchor and reach as far below it."""
    out, i = [], 0
    for k, y in enumerate(ay):
        nxt = ay[k + 1] if k + 1 < len(ay) else 1e9
        rest = lines[i:]
        top = min([ly for ly, _ in rest if ly < y - 2.5], default=y)
        mine = [ln for ln in rest if ln[0] <= y + (y - top) + 2.5 and ln[0] < nxt - 2.5]
        out.append([t for _, t in mine])
        i += len(mine)
    return out


def parse_pages(pages: list[list[tuple]]) -> list[dict]:
    rows = []
    for pi, ws in enumerate(pages):
        dates = [w for w in ws if DATE.match(w[4])]
        nums = [w for w in ws if re.fullmatch(r"\d+\.", w[4]) and any(abs(_ym(d) - _ym(w)) < 4 for d in dates)]
        nums = [w for w in nums if w[0] <= min(n[0] for n in nums) + 20]          # lfd. Nr. = leftmost column
        if not nums:
            continue
        on_line = lambda a: sorted((w for w in ws if abs(_ym(w) - _ym(a)) < 4), key=lambda w: w[0])  # noqa: E731
        xdate = min([d for d in on_line(a) if DATE.match(d[4])][-2][0] for a in nums
                    if len([d for d in on_line(a) if DATE.match(d[4])]) >= 2)
        xnum = max(w[2] for w in nums)
        hdr = [w for w in ws if w[4] == "Höhe"]
        ytop = max((w[3] for w in ws if w[4] in ("von", "bis") and w[0] >= xdate - 5), default=0) if hdr else 0
        body = [w for w in ws if w[1] >= ytop and w[0] > xnum + 0.5 and w[2] < xdate - 1]
        cur, gaps = xnum, []
        for a, b in sorted((w[0], w[2]) for w in body):
            if a > cur and cur > xnum + 5:
                gaps.append((a - cur, cur, a))
            cur = max(cur, b)
        if not gaps:
            raise RuntimeError(f"page {pi + 1}: no gutter between Empfänger and Zweck column")
        _, g0, g1 = max(gaps)
        split = (g0 + g1) / 2
        anchors = sorted(nums, key=_ym)
        ay = [_ym(a) for a in anchors]
        names = _assign(_cell_lines([w for w in body if w[2] <= split]), ay)
        zwecke = _assign(_cell_lines([w for w in body if w[0] >= split]), ay)
        for k, a in enumerate(anchors):
            line = on_line(a)
            dd = [w[4] for w in line if DATE.match(w[4]) and w[0] >= xdate - 1]
            am = [w[4] for w in line if AMOUNT.match(w[4]) and w[0] > xdate]
            rows.append({"nr": int(a[4][:-1]), "page": pi + 1, "empfaenger": _join(names[k]), "zweck": _join(zwecke[k]),
                         "von": _iso(dd[0]) if len(dd) == 2 else None, "bis": _iso(dd[1]) if len(dd) == 2 else None,
                         "betrag_text": am[0] if len(am) == 1 else None})
    return rows


def _iso(d: str) -> str:
    dd, mm, yy = d.split(".")
    return f"{yy}-{mm}-{dd}"


def amount(s: str | None) -> float | None:
    return float(s.replace(".", "").replace(",", ".")) if s and AMOUNT.match(s) else None


def anchor_line(text_lines: list[str], nr: int, betrag_text: str) -> str | None:
    """The -layout line that starts with 'nr.' and holds the amount (the quote)."""
    for ln in text_lines:
        if re.match(rf"\s*{nr}\.\s", ln) and betrag_text in ln:
            return common.clean(ln)
    return None


# --------------------------------------------------------------------------------------------- #
# filter
# --------------------------------------------------------------------------------------------- #
def _ft():
    from ingest.domains import funding_traeger as ft
    return ft


# a Träger of a protected shelter (funding_officers.protected_traeger: "runs a protected facility") is skipped
# entirely by the Transparenzdatenbank reader; counselling for victims of violence alone does not make one.
SHELTER_RE = re.compile(r"frauenh[äa]e?us|frauenschutz|schutzwohnung|zuflucht|schutzunterkunft|"
                        r"m[äa]e?dchenh[äa]e?us|inobhutnahme", re.I)

MV_CORE_EXTRA = re.compile(r"stra[ßs]s?enzeitung\w*|obdach\b", re.I)


def classify(zweck: str | None) -> tuple[str | None, list[str]]:
    ft = _ft()
    z = zweck or ""
    core = sorted({m.group(0).lower() for rx in (ft.BZ_CORE, MV_CORE_EXTRA) for m in rx.finditer(z)})
    adj = sorted({m.group(0).lower() for m in ft.BZ_ADJACENT.finditer(z)})
    if core:
        return "core", core + adj
    if adj and not ft.REFUGEE_RE.search(z):
        return "adjacent", adj
    return None, []


_DURCH = [re.compile(r"^([^:]{3,90}?):\s"), re.compile(r"organisiert (?:vom|von der|von) (.+?)\.?$"),
          re.compile(r"durch\s*:\s*(.+?)\.?$")]


def durchfuehrung(zweck: str) -> str | None:
    for rx in _DURCH:
        m = rx.search(zweck or "")
        if m and re.search(r"\b(e\.\s?V\.|gGmbH|GmbH|OV|KV|Werk|Verband|Diakonie|Caritas|ASB|AWO|DRK)\b", m.group(1)):
            return common.clean(m.group(1))
    return None


# --------------------------------------------------------------------------------------------- #
# run
# --------------------------------------------------------------------------------------------- #
DDL = """
CREATE TABLE IF NOT EXISTS funding_mv_zuwendung (
  source_id      INTEGER NOT NULL,      -- the archived Zuwendungsverzeichnis PDF
  lfd_nr         INTEGER NOT NULL,      -- lfd. Nr. in the PDF
  seite          INTEGER,               -- PDF page
  empfaenger     TEXT,
  empfaenger_norm TEXT,
  zweck          TEXT,                  -- NULL on protected-shelter rows
  durchfuehrung  TEXT,                  -- executing member named in the Zweck (text only, no org inferred)
  von            TEXT,
  bis            TEXT,
  betrag         REAL,
  currency       TEXT DEFAULT 'EUR',
  tier           TEXT,                  -- core | adjacent | NULL (out of scope)
  matched_terms  TEXT,                  -- JSON list
  tags           TEXT,                  -- JSON list: refugee, protected_shelter
  quote          TEXT,                  -- the anchor line as rendered by pdftotext -layout
  schutzunterkunft INTEGER DEFAULT 0,   -- 1 = the Zweck names a protected shelter (Frauenhaus, Schutzwohnung ...)
  PRIMARY KEY (source_id, lfd_nr)
);
CREATE INDEX IF NOT EXISTS ix_fmv_norm ON funding_mv_zuwendung(empfaenger_norm);
"""


def is_person(name: str | None) -> bool:
    return _ft().ted_is_person(common.clean(name) or "")


def run_mv(conn, cfg: dict) -> dict:
    ft = _ft()
    conn.executescript(DDL)
    url = cfg.get("mv_pdf_url") or discover(cfg)
    pdf = mv_fetch(url, cfg)
    pages = bbox_pages(pdf)
    rows = parse_pages(pages)
    tlines = layout_text(pdf).splitlines()
    year = None
    m = re.search(r"für das Jahr (\d{4})", "\n".join(tlines[:40]))
    if m:
        year = m.group(1)
    sid = common.source_id_for(conn, url, DOMAIN, title=f"LAGuS M-V – Zuwendungsverzeichnis nach § 12 Abs. 2 WoftG M-V "
                               f"für das Jahr {year or '?'} (PDF)", publisher=PUBLISHER, license=LICENSE)
    conn.execute("UPDATE source SET redistribute_fulltext=0 WHERE id=?", (sid,))   # Lead: no licence stated -> facts only, rf=0
    nrs = [r["nr"] for r in rows]
    if len(set(nrs)) != len(nrs) or sorted(nrs) != list(range(1, len(nrs) + 1)):
        raise RuntimeError(f"Zuwendungsverzeichnis: lfd. Nr. not 1..n ({len(nrs)} rows)")
    stats = {"rows": len(rows), "core": 0, "adjacent": 0, "persons": 0, "protected": 0, "unparsed": 0,
             "org_none": 0, "side_rows": 0}
    kept, total, orgs = 0, 0.0, set()
    limit = cfg.get("mv_limit")
    for r in rows:
        name, zweck = r["empfaenger"], r["zweck"]
        betrag = amount(r["betrag_text"])
        quote = anchor_line(tlines, r["nr"], r["betrag_text"] or "\0") if betrag is not None else None
        if not name or betrag is None or quote is None or not r["von"]:
            stats["unparsed"] += 1
            continue
        if is_person(name):
            stats["persons"] += 1
            continue
        protected = ft.is_protected(f"{zweck} {name}")
        stats["protected"] += protected
        tier, terms = classify(zweck)
        tags = (["refugee"] if ft.REFUGEE_RE.search(zweck) else []) + (["protected_shelter"] if protected else [])
        nn = common.name_norm(name)
        common.upsert(conn, "funding_mv_zuwendung", {
            "source_id": sid, "lfd_nr": r["nr"], "seite": r["page"], "empfaenger": name, "empfaenger_norm": nn,
            "zweck": None if protected else zweck, "durchfuehrung": None if protected else durchfuehrung(zweck),
            "von": r["von"], "bis": r["bis"], "betrag": betrag, "currency": "EUR", "tier": tier,
            "matched_terms": json.dumps(terms, ensure_ascii=False), "tags": json.dumps(tags),
            "quote": None if protected else quote, "schutzunterkunft": 1 if SHELTER_RE.search(zweck or "") else 0},
            keys=["source_id", "lfd_nr"])
        stats["side_rows"] += 1
        if not tier or (limit and kept >= int(limit)):
            continue
        org_id = ft.ensure_org_xland(conn, name, MV_LAND, sid, stats=stats, is_protected=1 if ft.is_protected(name) else None)
        stats["org_none"] += org_id is None
        common.upsert(conn, "award", {
            "foerder_schluessel": f"DE-MV-LAGUS-ZV{year or ''}:{r['nr']}", "foerder_id": str(r["nr"]),
            "foerderart": "zuwendung", "zuwendungsgeber": GEBER, "programm": "Zuwendungen nach WoftG M-V",
            "zweck": ft.redact_place(zweck) if protected else zweck, "empfaenger": name, "empfaenger_norm": nn,
            "org_id": org_id, "betrag": betrag, "currency": "EUR",
            "haushaltsjahr": r["von"][:4] if r["bis"] and r["von"][:4] == r["bis"][:4] else None,
            "laufzeit_von": r["von"], "laufzeit_bis": r["bis"], "ort_land": MV_LAND, "is_est": 0,
            "quote": quote, "locator": f"{url} – Seite {r['page']}, lfd. Nr. {r['nr']} (EUR, Höhe der Zuwendung {year or ''}, Bewilligungszeitraum {r['von']} bis {r['bis']})"
                                       + (f"; durchgeführt von {durchfuehrung(zweck)} (laut Zweck)" if durchfuehrung(zweck) else ""),
            "source_id": sid}, keys=["foerder_schluessel"])
        kept += 1
        stats[tier] += 1
        total += betrag
        orgs.add(nn)
    notes = (f"mv_zuwendungsverzeichnis: {url} (Jahr {year}), {stats['rows']} lfd. Nr. parsed, {stats['side_rows']} "
             f"organisation rows stored in funding_mv_zuwendung; kept {kept} awards (core={stats['core']}, "
             f"adjacent={stats['adjacent']}), {len(orgs)} recipients, EUR {total:,.2f}; skipped {stats['persons']} "
             f"natural-person rows, {stats['unparsed']} unparsed; protected {stats['protected']}; org key taken "
             f"(no org) {stats['org_none']}")
    notes += f"; cross-Land org matches {stats.get('xland', 0)}"
    return {"rows": kept, "notes": notes, "sources": [(url, LICENSE)], "stats": stats}


# --------------------------------------------------------------------------------------------- #
# source 2: Transparenzdatenbank M-V (LAGuS, WoftG M-V) -- Träger identity + Entscheidungsträger
# --------------------------------------------------------------------------------------------- #
TDB = "https://www.transparenz-mv.de"
TDB_START = TDB + "/site/index"
TDB_LIST = TDB + "/site/index?page={n}&per-page=15"
TDB_ET = TDB + "/entscheidungstraeger/wizzard?id={id}"
TDB_PUBLISHER = "Landesamt für Gesundheit und Soziales Mecklenburg-Vorpommern (LAGuS) – Transparenzdatenbank des Landes M-V"
TDB_LICENSE = ("no licence stated; statutory publication by the Träger under the WoftG M-V (Transparenzdatenbank, LAGuS); "
               "facts only (names, register numbers, published roles) with citation, no full-text redistribution; "
               "transparenz-mv.de robots.txt: no Disallow rules")
OUTSIDE_MV = re.compile(r"au(?:ß|ss)erhalb von mecklenburg", re.I)
PERSON_FORM = re.compile(r"einzelunternehm|gewerbebetrieb|inhaberbetrieb|\bgbr\b|partnerschaft|\bohg\b", re.I)
_TR = re.compile(r'(?s)<tr data-key="([0-9a-f-]{36})">(.*?)</tr>')
_TD = re.compile(r"(?s)<td[^>]*>(.*?)</td>")
_TOTAL = re.compile(r"von\s*</b>\s*<b>\s*([\d.]+)\s*</b>|von\s+([\d.]+)\s+Einträgen", re.I)


def _cell(h: str) -> str | None:
    return common.clean(_html.unescape(re.sub(r"<[^>]+>", " ", h)))


def tdb_total(html_text: str) -> int | None:
    t = common.html_to_text(html_text)
    m = re.search(r"Zeige\s+\d+\s+bis\s+\d+\s+von\s+([\d.]+)\s+Einträgen", t)
    return int(m.group(1).replace(".", "")) if m else None


def tdb_list_rows(html_text: str) -> list[dict]:
    out = []
    for key, body in _TR.findall(html_text):
        c = [_cell(x) for x in _TD.findall(body)]
        if len(c) < 6:
            continue
        out.append({"id": key, "name": c[1], "register_raw": c[2], "rechtsform": c[3], "landkreis": c[4],
                    "spitzenverband": c[5]})
    return out


def tdb_officers(html_text: str) -> list[tuple[str, str]]:
    """(Name, Funktion) rows of an Entscheidungsträger page (table: #, Name, Funktion, Aktionen)."""
    i = html_text.find("<tbody")
    out = []
    for body in re.findall(r"(?s)<tr[^>]*>(.*?)</tr>", html_text[i:] if i >= 0 else ""):
        c = [_cell(x) for x in _TD.findall(body)]
        if len(c) >= 3 and c[1] and c[2]:
            out.append((c[1], c[2]))
    return out


def tdb_register(raw: str | None) -> dict | None:
    """The court register in the list cell, by the Impressum parser's rules: a court must be stated (or the Berlin
    suffix 'B' = AG Charlottenburg); a bare 'VR 1243' names no court and is not a hard id (kept as text only)."""
    from ingest.domains import funding_officers as fo
    regs = fo.impressum_registers(raw or "")
    return regs[0] if len(regs) == 1 else None


def person_shaped(name: str) -> bool:
    """2-3 capitalised words and no organisation word: verify G7 would read the name as a private person's."""
    w = name.split()
    return 2 <= len(w) <= 3 and all(x[:1].isupper() and x.replace("-", "").isalpha() for x in w)


_ORGWORD = None


def _g7_orgword(name: str) -> bool:
    """verify.py's ORGWORD_RE (read from scripts/verify.py, not copied), so a held-back name matches G7 exactly."""
    global _ORGWORD
    if _ORGWORD is None:
        import importlib.util
        p = Path(__file__).resolve().parents[2] / "scripts" / "verify.py"
        spec = importlib.util.spec_from_file_location("_atlas_verify", p)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _ORGWORD = mod.ORGWORD_RE
    return bool(_ORGWORD.search(name))


def _loose(raw: str | None) -> tuple[str, int] | None:
    m = re.search(r"(?<![A-Za-z])(VR|HRB|HRA|GnR|PR)\s*\.?\s*(\d{1,6})(?!\d)", raw or "")
    return (m.group(1), int(m.group(2))) if m else None


TDB_DDL = """
CREATE TABLE IF NOT EXISTS funding_mv_traeger (
  tdb_id         TEXT PRIMARY KEY,      -- Träger id in the Transparenzdatenbank (uuid)
  name           TEXT,
  register_raw   TEXT,                  -- 'Handelsregister-/ Vereinsnummer' as published (often without court)
  rechtsform     TEXT,
  landkreis      TEXT,
  spitzenverband TEXT,
  org_id         INTEGER,               -- NULL when skipped
  status         TEXT,                  -- register | name | new | flagged_new | protected | person | no_org | ambiguous | held_name_shape
  officers       INTEGER DEFAULT 0,     -- governance rows written from this Träger's page
  source_id      INTEGER                -- list page
);
"""


def run_tdb(conn, cfg: dict) -> dict:
    from ingest import orglink
    from ingest.domains import funding_officers as fo
    ft = _ft()
    conn.executescript(TDB_DDL)
    today = cfg.get("today") or time.strftime("%Y-%m-%d")
    first = mv_fetch(TDB_START, cfg).decode("utf-8", "replace")
    total = tdb_total(first) or 0
    pages = max(1, -(-total // 15))
    limit = cfg.get("mv_tdb_limit")
    st = {"traeger": 0, "list_pages": 0, "register": 0, "name": 0, "new": 0, "flagged_new": 0, "protected": 0,
          "person": 0, "no_org": 0, "ambiguous": 0, "registers_filled": 0, "register_no_court": 0, "officers": 0,
          "dup_officers": 0, "et_truncated": 0, "held_name_shape": 0, "non_governance": 0, "bad_name": 0, "et_errors": 0}
    seen = set()
    done = 0
    shelter_traeger = {r[0] for r in conn.execute(
        "SELECT empfaenger_norm FROM funding_mv_zuwendung WHERE schutzunterkunft=1")} if conn.execute(
        "SELECT 1 FROM sqlite_master WHERE name='funding_mv_zuwendung'").fetchone() else set()
    for n in range(1, pages + 1):
        url = TDB_LIST.format(n=n)
        html_b = mv_fetch(url, cfg)
        st["list_pages"] += 1
        lsid = common.source_id_for(conn, url, DOMAIN, title=f"Transparenzdatenbank M-V – Eingetragene Träger, Seite {n}",
                                    publisher=TDB_PUBLISHER, license=TDB_LICENSE)
        conn.execute("UPDATE source SET redistribute_fulltext=0 WHERE id=?", (lsid,))
        for r in tdb_list_rows(html_b.decode("utf-8", "replace")):
            if r["id"] in seen or (limit and done >= int(limit)):
                continue
            seen.add(r["id"])
            done += 1
            st["traeger"] += 1
            name = r["name"]
            land = None if OUTSIDE_MV.search(r["landkreis"] or "") else MV_LAND
            row = {**{k: r[k] for k in ("name", "register_raw", "rechtsform", "landkreis", "spitzenverband")},
                   "tdb_id": r["id"], "source_id": lsid, "org_id": None, "officers": 0}
            if not name or PERSON_FORM.search(r["rechtsform"] or "") or (ft.ted_is_person(name) and person_shaped(name)):
                st["person"] += 1
                common.upsert(conn, "funding_mv_traeger", {"tdb_id": r["id"], "status": "person", "source_id": lsid},
                              keys=["tdb_id"])
                continue
            if fo.PROTECTED_RE.search(name) or ft.is_protected(name) or common.name_norm(name) in shelter_traeger:
                st["protected"] += 1
                common.upsert(conn, "funding_mv_traeger", {"tdb_id": r["id"], "status": "protected", "source_id": lsid},
                              keys=["tdb_id"])
                continue
            reg = tdb_register(r["register_raw"])
            loose = _loose(r["register_raw"])
            if loose and not reg:
                st["register_no_court"] += 1
            # existing org (read-only) -> protected check before anything is written or fetched
            holder, how = (fo.register_holder(conn, reg["raw"]) if reg else (None, None))
            if holder == -1:
                st["ambiguous"] += 1
                common.upsert(conn, "funding_mv_traeger", {**row, "status": "ambiguous"}, keys=["tdb_id"])
                continue

            def compat(cid, _loose=loose):
                """A candidate holding a register of the same scheme with another number is another entity."""
                if not _loose:
                    return True
                for sch, num in conn.execute("SELECT scheme, number FROM org_register WHERE org_id=?", (cid,)):
                    d = re.sub(r"\D", "", str(num or ""))
                    if sch == _loose[0] and d and int(d) != _loose[1]:
                        return False
                return True
            pre = holder or common.find_org(conn, name, land, legal_form=r["rechtsform"], compatible=compat)["org_id"]
            if fo.protected_traeger(conn, pre, name):
                st["protected"] += 1
                common.upsert(conn, "funding_mv_traeger", {"tdb_id": r["id"], "status": "protected", "source_id": lsid},
                              keys=["tdb_id"])
                continue
            if not holder and not pre and not reg and person_shaped(name) and not _g7_orgword(name):
                # a new org whose name verify G7 reads as a person's (2-3 capitalised words, no organisation word,
                # no register): held back, listed for the Lead (proposed ORGWORD 'jugend'); not stored as an org
                st["held_name_shape"] += 1
                common.upsert(conn, "funding_mv_traeger", {**row, "status": "held_name_shape"}, keys=["tdb_id"])
                continue
            rk = f"mv_tdb:{r['id']}"
            if holder:
                oid, status = holder, "register"
                common.link_org(conn, record_kind="mv_tdb_traeger", record_key=rk, org_id=oid, method="register_id",
                                confidence=1.0, source_id=lsid, record_name=name,
                                id_value=orglink.parse_court_register(reg["raw"])[0],
                                note=f"Transparenzdatenbank M-V: Handelsregister-/Vereinsnummer \u201e{r['register_raw']}\u201c")
            else:
                n_before = conn.execute("SELECT count(*) FROM org").fetchone()[0]
                oid = common.ensure_org(conn, name, land, lsid, legal_form=r["rechtsform"], record_kind="mv_tdb_traeger",
                                        record_key=rk, compatible=compat)
                if oid is None:
                    st["no_org"] += 1
                    common.upsert(conn, "funding_mv_traeger", {**row, "status": "no_org"}, keys=["tdb_id"])
                    continue
                created = conn.execute("SELECT count(*) FROM org").fetchone()[0] > n_before
                fl = conn.execute("SELECT flagged FROM org_link WHERE record_kind='org_name' AND org_id=? AND flagged=1",
                                  (oid,)).fetchone() if created else None
                status = ("flagged_new" if fl else "new") if created else "name"
                if loose and not created:
                    # same scheme + number as the matched org's register (court-less on this side): confirmation in
                    # the note only; the link stays a flagged name_fuzzy (a court-less number never merges)
                    agree = [f"{s} {nu} ({c or 'Gericht?'})" for s, c, nu in conn.execute(
                        "SELECT scheme, court, number FROM org_register WHERE org_id=?", (oid,))
                        if s == loose[0] and re.sub(r"\D", "", str(nu)) and int(re.sub(r"\D", "", str(nu))) == loose[1]]
                    if agree:
                        conn.execute("UPDATE org_link SET note=coalesce(note,'') || ? WHERE record_kind='mv_tdb_traeger' "
                                     "AND record_key=?", (f"; published number '{r['register_raw']}' equals {agree[0]}", rk))
                if reg:
                    cur = conn.execute("INSERT OR IGNORE INTO org_register(org_id, scheme, court, number, raw, source_id) "
                                       "VALUES (?,?,?,?,?,?)", (oid, reg["scheme"], orglink.court_norm(reg["court"]), re.sub(r"\D", "", reg["number"]),
                                                                reg["raw"], lsid))
                    st["registers_filled"] += cur.rowcount
                    conn.execute("UPDATE org SET register_id=? WHERE id=? AND register_id IS NULL", (reg["raw"], oid))
            st[status] += 1
            row.update(org_id=oid, status=status)
            # Entscheidungsträger (published, vertretungsbefugt) -> org_person, governance roles only
            eurl = TDB_ET.format(id=r["id"])
            try:
                eh = mv_fetch(eurl, cfg)
            except Exception as e:  # noqa: BLE001
                if type(e).__name__ == "RobotsRefused":
                    raise
                st["et_errors"] += 1
                common.upsert(conn, "funding_mv_traeger", row, keys=["tdb_id"])
                continue
            eh_t = eh.decode("utf-8", "replace")
            people = tdb_officers(eh_t)
            if (tdb_total(eh_t) or 0) > len(people):
                st["et_truncated"] += 1                    # more entries than the first page shows (not followed)
            esid = None
            for person, funktion in people:
                klass = fo.rollenklasse(funktion)
                if klass not in fo.GOVERNANCE:
                    st["non_governance"] += 1
                    continue
                pn = fo._clean_person(person) if not fo._CONTACT_RE.search(person) else None
                if not pn or re.search(r"\d", pn) or PERSON_FORM.search(pn) or fo.legal_kind(pn):
                    st["bad_name"] += 1
                    continue
                if conn.execute("SELECT 1 FROM org_person WHERE org_id=? AND funktionstraeger_norm=? AND lower(funktion)=lower(?)",
                                (oid, common.name_norm(pn), funktion)).fetchone():
                    st["dup_officers"] += 1
                    continue
                if esid is None:
                    esid = common.source_id_for(conn, eurl, DOMAIN, title=f"Transparenzdatenbank M-V – Entscheidungsträger: {name}",
                                                publisher=TDB_PUBLISHER, license=TDB_LICENSE)
                    conn.execute("UPDATE source SET redistribute_fulltext=0 WHERE id=?", (esid,))
                if fo._add_person(conn, org_id=oid, org_name=name, person=pn, funktion=funktion, rolle=klass,
                                  jahr=int(today[:4]), sid=esid, quote=f"{person} {funktion}", stand=today,
                                  locator=f"{eurl} – Entscheidungsträger (vertretungsbefugt), abgerufen {today}"):
                    st["officers"] += 1
                    row["officers"] += 1
            common.upsert(conn, "funding_mv_traeger", row, keys=["tdb_id"])
        if limit and done >= int(limit):
            break
    notes = (f"mv_transparenzdatenbank: {total} Träger listed, {st['traeger']} read on {st['list_pages']} list pages; "
             f"orgs by register {st['register']}, by name {st['name']} (flagged name_fuzzy), new {st['new']}, new+flagged "
             f"(namesakes, unknown form) {st['flagged_new']}; skipped protected {st['protected']}, natural person / sole "
             f"trader {st['person']}, key taken {st['no_org']}, ambiguous register {st['ambiguous']}; registers filled "
             f"{st['registers_filled']} (numbers without a court, not stored as ids: {st['register_no_court']}); officers "
             f"added {st['officers']} (already present {st['dup_officers']}, non-governance roles skipped "
             f"{st['non_governance']}, names rejected {st['bad_name']}); page errors {st['et_errors']}, officer lists longer than one page {st['et_truncated']}; held back (name reads as a person's in G7, no register) {st['held_name_shape']}")
    return {"rows": st["officers"], "notes": notes, "sources": [(TDB_LIST.format(n=1), TDB_LICENSE),
                                                                (TDB_ET.format(id="<uuid>"), TDB_LICENSE)], "stats": st}


SOURCES = {"mv_zuwendungsverzeichnis": run_mv, "mv_transparenzdatenbank": run_tdb}


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


def mini_pdf(pages: list[list[tuple[float, float, str]]]) -> bytes:
    """Smallest valid PDF with text at (x, y-from-top) in Helvetica/WinAnsi, landscape A4, for the offline tests."""
    def esc(s):
        b = s.encode("cp1252")
        return "".join(chr(c) if 32 <= c < 127 and chr(c) not in "()\\" else f"\\{c:03o}" for c in b)
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", None,
            "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"]
    kids = []
    for items in pages:
        stream = "BT /F1 9 Tf " + " ".join(f"1 0 0 1 {x:.1f} {595 - y:.1f} Tm ({esc(t)}) Tj" for x, y, t in items) + " ET"
        objs.append(f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream")
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 842 595] /Resources << /Font << /F1 3 0 R >> >> "
                    f"/Contents {len(objs)} 0 R >>")
        kids.append(len(objs))
    objs[1] = f"<< /Type /Pages /Kids [{' '.join(f'{k} 0 R' for k in kids)}] /Count {len(kids)} >>"
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += f"{i} 0 obj\n{o}\nendobj\n".encode("latin-1")
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode() + b"".join(f"{o:010d} 00000 n \n".encode() for o in offs)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return out


def _row(nr, y, name_lines, zweck_lines, von, bis, betrag):
    """A table row: wrapped cells centred on the anchor line at y (12 pt line pitch)."""
    items = [(40, y, f"{nr}."), (560, y, von), (620, y, bis), (690, y, f"{betrag} €")]
    for col, x in ((name_lines, 90), (zweck_lines, 300)):
        n = len(col)
        for i, t in enumerate(col):
            items.append((x, y + (i - (n - 1) / 2) * 12, t))
    return items


_PDF_URL = "http://www.zuwendung-mv.de/zuwendung.pdf"
_INDEX_HTML = b'<html><a href="/">Start</a> <a href="zuwendung.pdf">Zuwendungsverzeichnis</a></html>'
_ROBOTS = {"http://www.zuwendung-mv.de": 404}


def _fixture_pdf() -> bytes:
    p1 = [(300, 40, "ZUWENDUNGSVERZEICHNIS"), (250, 55, "für das Jahr 2020"),
          (40, 80, "lfd. Nr."), (90, 80, "Zuwendungsempfänger"), (300, 80, "Gegenstand / Zweck der Förderung"),
          (560, 74, "Bewilligungszeitraum"), (560, 86, "von"), (620, 86, "bis"), (690, 80, "Höhe der Zuwendung")]
    p1 += _row(1, 120, ["STARK MACHEN e.V."], ["Frauenhaus Rostock, Musterstraße 5"], "01.04.2020", "30.06.2020", "1.649,19")
    p1 += _row(2, 150, ["Deutscher Paritätischer", "Wohlfahrtsverband Landesverband", "Mecklenburg-Vorpommern e.V."],
               ["ASB OV Hagenow/Ludwigslust:", "Wohnungsnotfallhilfe zur Beratung"], "01.01.2020", "31.12.2020", "16.000,00")
    p1 += _row(3, 190, ["Steffi Muster"], ["Hygiene- und Schutzausrüstung"], "01.04.2020", "31.12.2020", "906,52")
    p2 = _row(4, 60, ["Diakonisches Werk Mecklenburg-", "Vorpommern e.V."],
              ['"Soziales Haus Loitz"-Hilfe für wohnungslose', "Menschen organisiert vom",
               "Kreisdiakonischen Werk Greifswald e.V."], "01.01.2020", "31.12.2020", "15.000,00")
    p2 += _row(5, 110, ["Jugend-Musikkorps Rostock e.V."], ["Ferienlager in Waren, 26.07. - 31.07.2020"],
               "26.07.2020", "31.07.2020", "512,50")
    p2 += _row(6, 140, ["Wohltat e.V."], ['Betreuung der Verkäufer der Straßenzeitung "Strohhalm"'],
               "01.01.2020", "31.12.2020", "18.000,00")
    return mini_pdf([p1, p2])


def _fixture_cfg(**kw) -> dict:
    return {"robots_fixture": dict(_ROBOTS), "mv_fixture": {INDEX: _INDEX_HTML, _PDF_URL: _fixture_pdf()},
            "sources": ["mv_zuwendungsverzeichnis"], **kw}


def _reset_robots():
    from ingest.domains import funding_officers as fo
    fo._ROBOTS.clear()
    fo._HOST_LAST.clear()


def _test_classify():
    assert classify("Wohnungsnotfallhilfe zur sozialpädagogischen Beratung")[0] == "core"
    assert classify("Möglichkeit für Obdachlose zu duschen")[0] == "core"
    assert classify('Betreuung der Verkäufer der Straßenzeitung "Strohhalm"')[0] == "core"
    assert classify("Suppenküche in Schwerin")[0] == "adjacent"
    assert classify("Notunterkunft für Geflüchtete")[0] is None
    assert classify("Beratungsstelle für Betroffene häuslicher Gewalt") == (None, [])
    assert durchfuehrung("ASB OV Hagenow/Ludwigslust: Wohnungsnotfallhilfe") == "ASB OV Hagenow/Ludwigslust"
    assert durchfuehrung("Hilfe für wohnungslose Menschen organisiert vom Kreisdiakonischen Werk Greifswald e.V.") == \
        "Kreisdiakonischen Werk Greifswald e.V"
    assert durchfuehrung("Familienerholung in Rerik") is None
    assert _join(["Diakonisches Werk Mecklenburg-", "Vorpommern e.V."]) == "Diakonisches Werk Mecklenburg-Vorpommern e.V."
    assert _join(["ANKER gGmbH -", "Gesellschaft"]) == "ANKER gGmbH - Gesellschaft"
    assert amount("16.000,00") == 16000.0 and amount("906,52") == 906.52 and amount("x") is None


def _test_parser():
    rows = {r["nr"]: r for r in parse_pages(bbox_pages(_fixture_pdf()))}
    assert sorted(rows) == [1, 2, 3, 4, 5, 6], sorted(rows)
    assert rows[2]["empfaenger"] == "Deutscher Paritätischer Wohlfahrtsverband Landesverband Mecklenburg-Vorpommern e.V."
    assert rows[2]["zweck"] == "ASB OV Hagenow/Ludwigslust: Wohnungsnotfallhilfe zur Beratung", rows[2]
    assert rows[4]["empfaenger"] == "Diakonisches Werk Mecklenburg-Vorpommern e.V.", rows[4]
    assert rows[4]["zweck"].endswith("organisiert vom Kreisdiakonischen Werk Greifswald e.V."), rows[4]
    assert rows[5]["von"] == "2020-07-26" and rows[5]["bis"] == "2020-07-31"       # a date inside the Zweck is not the period
    assert rows[5]["zweck"] == "Ferienlager in Waren, 26.07. - 31.07.2020"
    assert rows[6]["betrag_text"] == "18.000,00" and rows[1]["betrag_text"] == "1.649,19"


def _test_reader():
    _reset_robots()
    conn = memory_conn()
    cfg = _fixture_cfg()
    res = run(conn, cfg)
    assert cfg["_mv_log"] == [INDEX, _PDF_URL]
    aw = {r["foerder_id"]: dict(r) for r in conn.execute("SELECT * FROM award")}
    assert set(aw) == {"2", "4", "6"}, sorted(aw)                    # Frauenhaus, person, holiday camp out
    a = aw["2"]
    assert a["betrag"] == 16000.0 and a["currency"] == "EUR" and a["is_est"] == 0 and a["ort_land"] == "MV"
    assert a["empfaenger"] == "Deutscher Paritätischer Wohlfahrtsverband Landesverband Mecklenburg-Vorpommern e.V."
    assert a["foerder_schluessel"] == "DE-MV-LAGUS-ZV2020:2" and a["haushaltsjahr"] == "2020"
    lines = [common.clean(x) for x in layout_text(_fixture_pdf()).splitlines()]
    assert a["quote"] in lines and "16.000,00" in a["quote"] and a["quote"].startswith("2."), a["quote"]
    assert "Seite 1, lfd. Nr. 2" in a["locator"] and "ASB OV Hagenow/Ludwigslust" in a["locator"]
    side = {r["lfd_nr"]: dict(r) for r in conn.execute("SELECT * FROM funding_mv_zuwendung")}
    assert 3 not in side                                               # natural person: not stored at all
    assert side[1]["zweck"] is None and side[1]["quote"] is None and "protected_shelter" in side[1]["tags"]
    assert side[1]["betrag"] == 1649.19 and side[1]["tier"] is None
    assert side[5]["tier"] is None and side[4]["durchfuehrung"] == "Kreisdiakonischen Werk Greifswald e.V"
    orgs = {r["name"]: dict(r) for r in conn.execute("SELECT * FROM org")}
    assert set(orgs) == {a["empfaenger"], "Diakonisches Werk Mecklenburg-Vorpommern e.V.", "Wohltat e.V."}, set(orgs)
    assert all(o["legal_form_norm"] == "ev" and o["land"] == "MV" for o in orgs.values())
    assert all(o["name_norm"] == common.name_norm(o["name"]) for o in orgs.values())
    assert "Steffi" not in json.dumps(res) and "Musterstraße" not in json.dumps([dict(r) for r in conn.execute(
        "SELECT * FROM funding_mv_zuwendung")], ensure_ascii=False)
    assert "skipped 1 natural-person rows" in res["notes"], res["notes"]
    # facts only: the module itself writes rf=0 on the LAGuS source (no licence stated), also after a re-run
    assert conn.execute("SELECT redistribute_fulltext FROM source WHERE url=?", (_PDF_URL,)).fetchone()[0] == 0
    run(conn, _fixture_cfg())                                          # idempotent
    assert conn.execute("SELECT redistribute_fulltext FROM source WHERE url=?", (_PDF_URL,)).fetchone()[0] == 0
    assert conn.execute("SELECT count(*) FROM award").fetchone()[0] == 3
    assert conn.execute("SELECT count(*) FROM org").fetchone()[0] == 3
    _reset_robots()


def _test_robots_fail_closed():
    _reset_robots()
    bad = _fixture_cfg(robots_fixture={"http://www.zuwendung-mv.de": "error"})
    try:
        run(memory_conn(), bad)
        raise AssertionError("fetched without robots.txt")
    except Exception as e:  # noqa: BLE001
        assert type(e).__name__ == "RobotsRefused", e
    assert not bad.get("_mv_log")
    _reset_robots()
    dis = _fixture_cfg(robots_fixture={"http://www.zuwendung-mv.de": "User-agent: *\nDisallow: /zuwendung.pdf\n"})
    try:
        run(memory_conn(), dis)
        raise AssertionError("disallowed PDF fetched")
    except Exception as e:  # noqa: BLE001
        assert type(e).__name__ == "RobotsRefused", e
    assert dis["_mv_log"] == [INDEX]
    _reset_robots()




# ---- Transparenzdatenbank fixtures/tests
def _tdb_list_html(rows, total):
    tr = "".join(f'<tr data-key="{k}"><td>{i + 1}</td>' + "".join(f"<td>{c}</td>" for c in cells)
                 + f'<td><a href="/traeger/wizzard?id={k}">x</a> </td></tr>\n' for i, (k, cells) in enumerate(rows))
    return (f'<html><div class="summary">Zeige <b>1 bis {len(rows)}</b> von <b>{total}</b> Einträgen.</div>'
            f"<table><thead><tr><th>#</th><th>Name</th></tr></thead><tbody>\n{tr}</tbody></table></html>").encode()


def _tdb_et_html(people):
    tr = "".join(f'<tr data-key="p{i}"><td>{i + 1}</td><td>{n}</td><td>{f}</td><td><a href="/x">v</a>  </td></tr>\n'
                 for i, (n, f) in enumerate(people))
    return (f'<html><div class="summary">Zeige <b>1 bis {len(people)}</b> von <b>{len(people)}</b> Einträgen.</div>'
            f"<table><thead><tr><th>#</th><th>Name</th><th>Funktion</th></tr></thead><tbody>\n{tr}</tbody></table></html>").encode()


_U = {k: f"{i:08d}-0000-0000-0000-000000000000" for i, k in enumerate(
    ["fsp", "caritas", "fhf", "person", "diakonie", "lebenshilfe", "kirche"], 1)}
_TDB_ROWS = [
    (_U["fsp"], ["Familiensozialprojekt Vorpommern e.V.", "1125", "eingetragener Verein (e.V.)", "Landkreis Vorpommern-Rügen", "Keine"]),
    (_U["caritas"], ["Caritas Altenhilfe gGmbH", "HRB 5485 B", "gGmbH", "Hauptsitz des Trägers außerhalb von Mecklenburg-Vorpommern", "Keine"]),
    (_U["fhf"], ["Frauen helfen Frauen e.V. Musterstadt", "VR 99", "e.V.", "Landkreis Rostock", "Keine"]),
    (_U["person"], ["Max Mustermann", "keine Nummer verfügbar", "Einzelunternehmen", "Landkreis Rostock", "Keine"]),
    (_U["diakonie"], ["Diakonisches Werk Mecklenburg-Vorpommern e.V.", "VR 1", "e.V.", "Landeshauptstadt Schwerin", "Diakonie"]),
]
_TDB_ROWS2 = [(_U["lebenshilfe"], ["Lebenshilfe Test gGmbH", "HRB 123 B", "gGmbH", "Landkreis Rostock", "Keine"]),
              (_U["kirche"], ["Musterkirche Testdorf e.V.", "VR 7 (AG Rostock)", "e.V.", "Landkreis Rostock", "Keine"])]


def _tdb_cfg(**kw) -> dict:
    fx = {TDB_START: _tdb_list_html(_TDB_ROWS, 20), TDB_LIST.format(n=1): _tdb_list_html(_TDB_ROWS, 20),
          TDB_LIST.format(n=2): _tdb_list_html(_TDB_ROWS2, 20),
          TDB_ET.format(id=_U["fsp"]): _tdb_et_html([("Anna Beispiel", "Vorstandsvorsitzende"),
                                                    ("Bernd Muster", "Einrichtungsleitung"),
                                                    ("Tel. 0381 123456", "Geschäftsführer")]),
          TDB_ET.format(id=_U["caritas"]): _tdb_et_html([("Dr. Clara Probe", "Geschäftsführerin ")]),
          TDB_ET.format(id=_U["diakonie"]): _tdb_et_html([("Paul Muster", "Vorstandsvorsitzender"),
                                                         ("Erika Beispiel", "Kaufmännischer Vorstand")]),
          TDB_ET.format(id=_U["lebenshilfe"]): _tdb_et_html([("Dora Test", "Geschäftsführerin")]),
          TDB_ET.format(id=_U["kirche"]): _tdb_et_html([])}
    return {"robots_fixture": {**_ROBOTS, TDB: 404}, "mv_fixture": fx, "sources": ["mv_transparenzdatenbank"],
            "today": "2026-11-23", **kw}


def _test_tdb_parsers():
    rows = tdb_list_rows(_tdb_list_html(_TDB_ROWS, 20).decode())
    assert [r["name"] for r in rows][:2] == ["Familiensozialprojekt Vorpommern e.V.", "Caritas Altenhilfe gGmbH"]
    assert rows[1]["register_raw"] == "HRB 5485 B" and tdb_total(_tdb_list_html(_TDB_ROWS, 355).decode()) == 355
    assert tdb_officers(_tdb_et_html([("A B", "Vorstand")]).decode()) == [("A B", "Vorstand")]
    assert tdb_register("VR 1243") is None                        # no court: not a hard id
    r = tdb_register("HRB 5485 B")
    assert r and r["scheme"] == "HRB" and r["court"] == "Charlottenburg"
    assert tdb_register("VR 7 (AG Rostock)")["court"] == "Rostock"
    assert person_shaped("Max Mustermann") and not person_shaped("Diakonisches Werk Mecklenburg-Vorpommern e.V.")


def _test_tdb_reader():
    _reset_robots()
    conn = memory_conn()
    sid0 = conn.execute("INSERT INTO source(url, domain, title) VALUES ('https://example.org/l', 'x', 'x')").lastrowid
    lh = conn.execute("INSERT INTO org(name, name_norm, legal_form_norm, land, source_id, currency) VALUES "
                      "('Lebenshilfe Test gemeinnützige GmbH', ?, 'ggmbh', 'MV', ?, 'EUR') RETURNING id",
                      (common.name_norm("Lebenshilfe Test gemeinnützige GmbH"), sid0)).fetchone()[0]
    conn.execute("INSERT INTO org_register(org_id, scheme, court, number, raw, source_id) VALUES (?, 'HRB', 'CHARLOTTENBURG', "
                 "'123', 'HRB 123 B', ?)", (lh, sid0))
    dk = conn.execute("INSERT INTO org(name, name_norm, legal_form_norm, land, source_id, currency) VALUES "
                      "('Diakonisches Werk Mecklenburg-Vorpommern e.V.', ?, 'ev', 'MV', ?, 'EUR') RETURNING id",
                      (common.name_norm("Diakonisches Werk Mecklenburg-Vorpommern e.V."), sid0)).fetchone()[0]
    conn.execute("INSERT INTO org_person(org_id, org_bezeichnung, funktionstraeger, funktionstraeger_norm, funktion, "
                 "rollenklasse, jahr, quote, stand, source_id) VALUES (?, 'Diakonie MV', 'Paul Muster', ?, "
                 "'Vorstandsvorsitzender', 'vorstand', 2025, 'Paul Muster Vorstandsvorsitzender', '2025-01-01', ?)",
                 (dk, common.name_norm("Paul Muster"), sid0))
    cfg = _tdb_cfg()
    res = run(conn, cfg)
    log = cfg["_mv_log"]
    assert TDB_ET.format(id=_U["fhf"]) not in log and TDB_ET.format(id=_U["person"]) not in log   # skipped entirely
    st = res["notes"]
    tr = {r["tdb_id"]: dict(r) for r in conn.execute("SELECT * FROM funding_mv_traeger")}
    assert tr[_U["fhf"]]["status"] == "protected" and tr[_U["fhf"]]["name"] is None
    assert tr[_U["person"]]["status"] == "person" and tr[_U["person"]]["name"] is None
    assert "Mustermann" not in json.dumps([dict(r) for r in conn.execute("SELECT * FROM org")], ensure_ascii=False)
    assert tr[_U["lebenshilfe"]]["status"] == "register" and tr[_U["lebenshilfe"]]["org_id"] == lh
    assert tr[_U["diakonie"]]["status"] == "name" and tr[_U["diakonie"]]["org_id"] == dk
    assert tr[_U["fsp"]]["status"] == "new" and tr[_U["caritas"]]["status"] == "new"
    links = {r["record_key"]: dict(r) for r in conn.execute("SELECT * FROM org_link WHERE record_kind='mv_tdb_traeger'")}
    assert links[f"mv_tdb:{_U['lebenshilfe']}"]["method"] == "register_id"
    assert links[f"mv_tdb:{_U['diakonie']}"]["method"] == "name_fuzzy" and links[f"mv_tdb:{_U['diakonie']}"]["flagged"] == 1
    assert links[f"mv_tdb:{_U['fsp']}"]["method"] == "origin"
    car = conn.execute("SELECT * FROM org WHERE name='Caritas Altenhilfe gGmbH'").fetchone()
    assert car["land"] is None and car["legal_form_norm"] == "ggmbh" and car["register_id"] == "HRB 5485 B (AG Charlottenburg)"
    regs = {(r["scheme"], r["court"], r["number"]) for r in conn.execute("SELECT * FROM org_register")}
    assert ("HRB", "CHARLOTTENBURG", "5485") in regs and ("VR", "ROSTOCK", "7") in regs, regs
    assert not any(r[0] == "VR" and r[2] in ("1", "1125") for r in regs)          # court-less numbers are no ids
    assert conn.execute("SELECT count(*) FROM org_register WHERE scheme='USt-IdNr'").fetchone()[0] == 0
    people = {(r["org_id"], r["funktionstraeger"], r["funktion"]): dict(r) for r in conn.execute("SELECT * FROM org_person")}
    assert (dk, "Erika Beispiel", "Kaufmännischer Vorstand") in people
    assert sum(1 for k in people if k[1] == "Paul Muster") == 1                   # dedup on (org, name, funktion)
    p = people[(dk, "Erika Beispiel", "Kaufmännischer Vorstand")]
    assert p["quote"] == "Erika Beispiel Kaufmännischer Vorstand" and p["stand"] == "2026-11-23" and p["jahr"] == 2026
    assert p["rollenklasse"] == "vorstand"
    c = [k for k in people if k[1] == "Dr. Clara Probe"]
    assert c and people[c[0]]["funktion"] == "Geschäftsführerin" and people[c[0]]["rollenklasse"] == "geschaeftsfuehrung"
    assert not any(k[1] == "Bernd Muster" for k in people)                        # Einrichtungsleitung: not governance
    assert not any("Tel" in k[1] for k in people)
    src = conn.execute("SELECT redistribute_fulltext FROM source WHERE domain=? AND url LIKE ?", (DOMAIN, TDB + "%")).fetchall()
    assert src and all(r[0] == 0 for r in src)          # list pages and Entscheidungsträger pages: facts only, rf=0
    assert conn.execute("SELECT count(*) FROM source WHERE domain=? AND redistribute_fulltext<>0", (DOMAIN,)).fetchone()[0] == 0
    # the archived page text (html_to_text, what verify G7 searches) contains every quote
    for (oid, n, f), row in people.items():
        if row["source_id"] == sid0:
            continue
        url = conn.execute("SELECT url FROM source WHERE id=?", (row["source_id"],)).fetchone()[0]
        txt = re.sub(r"\s+", " ", common.html_to_text(cfg["mv_fixture"][url]))
        assert row["quote"] in txt, (row["quote"], txt)
    assert "officers added 4" in st and "already present 1" in st and "skipped protected 1" in st and "natural person / sole trader 1" in st, st
    n_p, n_o = (conn.execute("SELECT count(*) FROM org_person").fetchone()[0], conn.execute("SELECT count(*) FROM org").fetchone()[0])
    _reset_robots()
    res2 = run(conn, _tdb_cfg())                                                  # idempotent
    assert conn.execute("SELECT count(*) FROM org_person").fetchone()[0] == n_p
    assert conn.execute("SELECT count(*) FROM org").fetchone()[0] == n_o
    assert "officers added 0" in res2["notes"], res2["notes"]
    _reset_robots()


def _test_tdb_robots_fail_closed():
    _reset_robots()
    bad = _tdb_cfg(robots_fixture={TDB: "error"})
    try:
        run(memory_conn(), bad)
        raise AssertionError("fetched without robots.txt")
    except Exception as e:  # noqa: BLE001
        assert type(e).__name__ == "RobotsRefused", e
    assert not bad.get("_mv_log")
    _reset_robots()
    dis = _tdb_cfg(robots_fixture={TDB: "User-agent: *\nDisallow: /entscheidungstraeger/\n"})
    try:
        run(memory_conn(), dis)
        raise AssertionError("disallowed officer page fetched")
    except Exception as e:  # noqa: BLE001
        assert type(e).__name__ == "RobotsRefused", e
    assert not any("/entscheidungstraeger/" in u for u in dis["_mv_log"])
    _reset_robots()


def _test_tdb_shelter_traeger():
    """A Träger that the Zuwendungsverzeichnis shows running a Frauenhaus is skipped entirely (no org, no page)."""
    _reset_robots()
    conn = memory_conn()
    cfg = _tdb_cfg(sources=["mv_zuwendungsverzeichnis", "mv_transparenzdatenbank"])
    sm = "99999999-0000-0000-0000-000000000000"
    rows = _TDB_ROWS + [(sm, ["STARK MACHEN e.V.", "VR 5", "e.V.", "Hanse- und Universitätsstadt Rostock", "Keine"])]
    cfg["mv_fixture"].update({INDEX: _INDEX_HTML, _PDF_URL: _fixture_pdf(), TDB_START: _tdb_list_html(rows, 20),
                              TDB_LIST.format(n=1): _tdb_list_html(rows, 20)})
    run(conn, cfg)
    assert TDB_ET.format(id=sm) not in cfg["_mv_log"]
    assert conn.execute("SELECT status FROM funding_mv_traeger WHERE tdb_id=?", (sm,)).fetchone()[0] == "protected"
    assert conn.execute("SELECT count(*) FROM org WHERE name LIKE 'STARK MACHEN%'").fetchone()[0] == 0
    _reset_robots()


TESTS = [_test_classify, _test_parser, _test_reader, _test_robots_fail_closed, _test_tdb_parsers, _test_tdb_reader,
         _test_tdb_robots_fail_closed, _test_tdb_shelter_traeger]


def _run_tests():
    for t in TESTS:
        t()
        print("PASS", t.__name__)


SELFTEST_CFG: dict = {}


def _selftest(argv):
    """Live run (robots-first) into a scratch DB; the runner's transaction is rolled back."""
    from ingest import run as runner
    from ingest.domains.funding_traeger import scratch_db_path
    conn = runner.open_db(scratch_db_path(argv))
    conn.execute("BEGIN IMMEDIATE")
    conn.runner_txn = True
    try:
        res = run(conn, dict(SELFTEST_CFG))
        print(f"[{DOMAIN}] selftest rows={res['rows']}")
        print(f"[{DOMAIN}]   {res['notes']}")
        for r in conn.execute("SELECT a.foerder_schluessel, a.empfaenger, a.betrag, a.laufzeit_von, a.laufzeit_bis, "
                              "a.quote FROM award a WHERE a.foerder_schluessel LIKE 'DE-MV-LAGUS-%' ORDER BY a.id"):
            print("   ", dict(r))
        assert res["rows"] > 0
        assert conn.execute("SELECT count(*) FROM award WHERE foerder_schluessel LIKE 'DE-MV-LAGUS-%' "
                            "AND (quote IS NULL OR locator IS NULL OR betrag IS NULL)").fetchone()[0] == 0
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        conn.runner_txn = False
        conn.execute("ROLLBACK")
        conn.close()


def _cli(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="python3 -m ingest.domains.funding_mv", allow_abbrev=False,
                                 description="Worker tools. data/atlas.db is written only by "
                                             "`python3 -m ingest.run funding_mv`.")
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
        _selftest(["--selftest", "--db", a.db])
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
