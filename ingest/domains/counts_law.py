"""counts_law -- Germany counts and law layer (queue item 02-counts_law).

Part 1 (this file, implemented): Destatis "Statistik untergebrachter wohnungsloser Personen" (EVAS 22971).
Part 2 (implemented): BMWSB Wohnungslosenbericht 2022 + 2024 and BAG W Hochrechnung 2018-2024 -> metric
        (estimates is_est=1; each figure verified against the text of its archived PDF page before insert).
Part 3 (implemented): Länder/city counts Destatis does not publish -> metric with own source_id, is_est=0:
        NRW Wohnungsnotfallberichterstattung 2024 (Land + 53 Kreise + 5 Reg.-Bez., Stichtag 30.06., 2015-2024;
        annex tables parsed from the archived PDF) and Berlin "Nacht der Solidarität" 29./30.01.2020.
        Never written to pit; metric names nrw_* / be_* never collide with Destatis housed_homeless*.
Part 4 (implemented): law rows (SGB XII §§ 67-69 + DVO, SGB II § 22, WoBerichtsG, Land general clauses behind
        ordnungsrechtliche Unterbringung where an archivable official text exists, NAP 2024 + Länder plans) and
        court decisions -> doc(kind='court'); each written only if verbatim phrases are found in the archived source.

--- Part 1: Destatis 22971 -------------------------------------------------------------------------

What it is
  The federal statistic of *housed* homeless people under the Wohnungslosenberichterstattungsgesetz
  (WoBerichtsG, 2020). Annual, Stichtag 31 January (night of 31 Jan -> 1 Feb), first wave 2022.
  It counts only people placed by municipalities (ordnungsrechtlich), in SGB XII §§67ff facilities /
  "Betreutes Wohnen" of freie Träger, or via other municipal funding (e.g. Kältehilfe). It does NOT
  count people sleeping rough ("ohne Unterkunft") or staying with friends/family ("verdeckt") -- those
  are only estimated in the biennial BMWSB Wohnungslosenbericht (separate module).

Source (public, no login)
  GENESIS-Online (Destatis) tables:
    22971-0001  Deutschland  x Stichtag x Nationalität x Geschlecht x Altersgruppen
    22971-0050  Bundesländer x Stichtag x Nationalität x Geschlecht x Altersgruppen
    22971-0080  Kreise       x Stichtag x Nationalität x Geschlecht x Altersgruppen
  read as JSON from the same anonymous endpoints the public GENESIS-Online web table view loads
  (https://genesis.destatis.de/genesis/api/rest/tables/<code>/data and .../structure). The classic
  GENESIS webservice (genesisWS/rest/2020) accepts the GAST login but refuses data calls (Code 15)
  without a registered account, so it is not used. Human-readable page for every table:
  https://genesis.destatis.de/datenbank/online/statistic/22971/table/<code>

Licence: Datenlizenz Deutschland – Namensnennung – Version 2.0 (dl-de/by-2-0), © Statistisches
Bundesamt (Destatis).

What it writes (all official published counts, is_est=0)
  metric  entity_type='de'     entity_id='DE'
          entity_type='land'   entity_id=<2-digit Land AGS>    e.g. '08'
          entity_type='kreis'  entity_id=<5-digit Kreis AGS>   e.g. '09162' 
          metric names (unit='persons', year = Stichtag year, note names the Stichtag + table):
            housed_homeless                       total
            housed_homeless__male / __female / __sex_unknown
            housed_homeless__german / __foreign   (nationality "unknown/stateless" is not a table value)
            housed_homeless__age_lt18 / __age_18_24 / __age_25_39 / __age_40_59 / __age_60plus / __age_unknown
  pit     geo_ags 'DE' | <AGS2> | <AGS5>, geo_kind bund | land | kreis, year = Stichtag year:
          sheltered = housed homeless persons (untergebracht), children = persons under 18,
          total and unsheltered left NULL (this statistic does not count rough sleepers or hidden
          homelessness, so it is not a total), is_est=0, source_id = the GENESIS table.
  geo_land / geo_kreis  INSERT OR IGNORE only (ags, name, abbr / land_ags, land, kind) so the Kreis and
          Land keys exist; rows already created by another domain (BKG VG250) are never touched.
  source  also the five Destatis press releases (2022-2026), fetched and archived as a cross-check of the
          national total (the rounded "rund NNN NNN" figure must agree with the GENESIS value to ±1,000).
  counts_law_destatis_cell  every published cell of the three cubes (full nat x sex x age cross-tab)

Status flags: GENESIS 'e' = value, '-' = nothing (exactly 0). Any other flag ('.', 'x', '/', '...')
is stored in the cell table with value NULL and never turned into a metric. Destatis rounds every cell
to a multiple of 5 (confidentiality), so Land/Kreis sums differ from the national total by a few
persons; the national row is taken from 22971-0001 directly, never summed.

Kreise: 22971-0080 lists 477 Kreis codes including pre-reform codes ("(bis 20.10.2009)" etc.);
codes without a single 'e' cell in any year are historic and are skipped.

Run:  python3 -m ingest.domains.counts_law [--selftest] [--db PATH] [--no-kreise] [--refresh] [--no-estimates] [--no-law] [--shape-test]
  --db PATH   write to PATH instead of data/atlas.db (workers: always use a scratch DB)
  --refresh   ignore the data/raw cache and re-download (GENESIS revises cells; lastChange is noted)
"""
from __future__ import annotations

import json
import re
import sys
import unicodedata
from collections import defaultdict

from ingest import common
from ingest.common import fetch as _cached_fetch, save_raw, source_id_for, upsert

DOMAIN = "counts_law"

# ---- run-time robots.txt gate (Lead review 2026-11-23) --------------------------------------------------------
# Every network request of this module goes through fetch() below. Before the first request to a host it reads
# that host's robots.txt with the project UA and fails closed: a disallowed path, or a robots.txt that cannot be
# read (network error, 5xx, 401/403, redirect off the host, undecodable), means the host is skipped and logged.
# A 404/410 robots.txt is "no rules" (RFC 9309 § 2.3.1.3). Crawl-delay is honoured per host (never below the
# 1 req/s floor of common.fetch). Cached raw files are served without a request and need no robots check.
ROBOTS_AGENT = "germany-atlas"
_ROBOTS: dict = {}       # "scheme://host" -> (rules, crawl_delay) | Exception text (host skipped)
_HOST_LAST: dict = {}    # "scheme://host" -> monotonic time of the last request


class RobotsRefused(RuntimeError):
    """A host's robots.txt disallows the path or could not be read; nothing was fetched."""


def _robots_parse(text: str):
    """Rules of the group that names our agent (else the '*' group): [(allow, pattern)], crawl-delay or None."""
    groups, agents, rules, delay, in_rules = [], [], [], None, False
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        field, value = (x.strip() for x in line.split(":", 1))
        field = field.lower()
        if field == "user-agent":
            if in_rules:
                groups.append((agents, rules, delay))
                agents, rules, delay, in_rules = [], [], None, False
            agents.append(value.lower())
        elif field in ("allow", "disallow"):
            in_rules = True
            if value:
                rules.append((field == "allow", value))
        elif field == "crawl-delay":
            in_rules = True
            try:
                delay = float(value)
            except ValueError:
                pass
    if agents:
        groups.append((agents, rules, delay))
    mine = [g for g in groups if ROBOTS_AGENT in g[0]]
    star = [g for g in groups if "*" in g[0]]
    chosen = mine or star
    out_rules = [r for g in chosen for r in g[1]]
    delays = [g[2] for g in chosen if g[2] is not None]
    return out_rules, (max(delays) if delays else None)


def _robots_allows(rules, path: str) -> bool:
    """Longest matching pattern wins ('*' wildcard, '$' end anchor); on a tie Allow wins; no match = allowed."""
    import urllib.parse as _up
    path = _up.unquote(path)
    best = None
    for allow, pat in rules:
        rx = "^" + re.escape(_up.unquote(pat)).replace(r"\*", ".*")
        if rx.endswith(r"\$"):
            rx = rx[:-2] + "$"
        if re.match(rx, path):
            key = (len(pat), allow)
            if best is None or key > best:
                best = key
    return True if best is None else best[1]


def _robots_for(origin: str):
    import time as _t
    import urllib.error
    import urllib.parse
    import urllib.request
    if origin in _ROBOTS:
        return _ROBOTS[origin]
    url = origin + "/robots.txt"
    common._polite_wait()
    try:
        req = urllib.request.Request(url, headers={"User-Agent": common.UA, "Accept": "text/plain,*/*"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            final = resp.geturl()
            fhost = urllib.parse.urlsplit(final).netloc.lower()
            ohost = urllib.parse.urlsplit(origin).netloc.lower()
            if fhost.removeprefix("www.") != ohost.removeprefix("www."):
                raise RobotsRefused(f"robots.txt redirected off the site to {final}")
            body = resp.read(512 * 1024)
            ctype = resp.headers.get("Content-Type", "")
        try:
            text = body.decode("utf-8")
        except UnicodeDecodeError:
            text = body.decode("latin-1")
        if "html" in ctype.lower() or text.lstrip()[:1] == "<":
            # served an HTML page (e.g. a redirect to the home page): the site has no robots.txt, so no rules
            _ROBOTS[origin] = ([], None)
            common._log(DOMAIN, url, 200, len(body), f"no robots.txt (HTML page at {final}): no rules")
        else:
            _ROBOTS[origin] = _robots_parse(text)
            common._log(DOMAIN, url, 200, len(body), "robots.txt read")
    except urllib.error.HTTPError as e:
        if e.code in (404, 410):
            _ROBOTS[origin] = ([], None)
            common._log(DOMAIN, url, e.code, 0, "no robots.txt: no rules (RFC 9309)")
        else:
            _ROBOTS[origin] = f"robots.txt unreadable (HTTP {e.code})"
    except RobotsRefused as e:
        _ROBOTS[origin] = str(e)
    except Exception as e:  # noqa: network/TLS/timeouts: fail closed
        _ROBOTS[origin] = f"robots.txt unreadable ({e!r:.120})"
    _HOST_LAST[origin] = _t.monotonic()
    return _ROBOTS[origin]


def fetch(url: str, **kw) -> bytes:
    """common.fetch behind the per-host robots.txt gate (cache hits need no request and no robots check)."""
    import time as _t
    import urllib.parse as _up
    if not kw.get("force") and common.cached_path(kw.get("domain", "misc"), url, kw.get("method", "GET"),
                                                  kw.get("data")) is not None:
        return _cached_fetch(url, **kw)
    parts = _up.urlsplit(url)
    origin = f"{parts.scheme}://{parts.netloc}"
    robots = _robots_for(origin)
    if isinstance(robots, str):
        common._log(DOMAIN, url, "robots-skip", 0, robots)
        print(f"[{DOMAIN}] skip host {parts.netloc}: {robots}", file=sys.stderr)
        raise RobotsRefused(f"{parts.netloc}: {robots}")
    rules, delay = robots
    path = parts.path or "/"
    if parts.query:
        path += "?" + parts.query
    if not _robots_allows(rules, path):
        common._log(DOMAIN, url, "robots-disallowed", 0, "robots.txt disallows this path for the project UA")
        print(f"[{DOMAIN}] skip (robots.txt disallows): {url}", file=sys.stderr)
        raise RobotsRefused(f"robots.txt of {parts.netloc} disallows {parts.path}")
    if delay:
        gap = _t.monotonic() - _HOST_LAST.get(origin, 0.0)
        if gap < delay:
            _t.sleep(delay - gap)
    try:
        return _cached_fetch(url, **kw)
    finally:
        _HOST_LAST[origin] = _t.monotonic()

API = "https://genesis.destatis.de/genesis/api/rest"
PAGE = "https://genesis.destatis.de/datenbank/online/statistic/22971/table/{code}"
PUBLISHER = "Statistisches Bundesamt (Destatis)"
LICENSE = "Datenlizenz Deutschland – Namensnennung – Version 2.0 (dl-de/by-2-0), © Statistisches Bundesamt (Destatis)"

# table code -> (entity_type, region variable, region code -> entity id)
TABLES = {
    "22971-0001": ("de", "DINSG"),
    "22971-0050": ("land", "DLAND"),
    "22971-0080": ("kreis", "KREISE"),
}

PRESS = {
    2022: "https://www.destatis.de/DE/Presse/Pressemitteilungen/2022/07/PD22_299_229.html",
    2023: "https://www.destatis.de/DE/Presse/Pressemitteilungen/2023/08/PD23_305_229.html",
    2024: "https://www.destatis.de/DE/Presse/Pressemitteilungen/2024/07/PD24_282_229.html",
    2025: "https://www.destatis.de/DE/Presse/Pressemitteilungen/2025/07/PD25_246_229.html",
    2026: "https://www.destatis.de/DE/Presse/Pressemitteilungen/2026/06/PD26_222_229.html",
}

ABBR = {"01": "SH", "02": "HH", "03": "NI", "04": "HB", "05": "NW", "06": "HE", "07": "RP", "08": "BW",
        "09": "BY", "10": "SL", "11": "BE", "12": "BB", "13": "MV", "14": "SN", "15": "ST", "16": "TH"}
LAND = {"01": "Schleswig-Holstein", "02": "Hamburg", "03": "Niedersachsen", "04": "Bremen",
        "05": "Nordrhein-Westfalen", "06": "Hessen", "07": "Rheinland-Pfalz", "08": "Baden-Württemberg",
        "09": "Bayern", "10": "Saarland", "11": "Berlin", "12": "Brandenburg",
        "13": "Mecklenburg-Vorpommern", "14": "Sachsen", "15": "Sachsen-Anhalt", "16": "Thüringen"}

T = "%TOTAL%"
SEX = {"GESM": "male", "GESW": "female", "UNBEKANNT": "sex_unknown"}
NAT = {"NATD": "german", "NATA": "foreign"}
AGE = {"ALT000B18": "age_lt18", "ALT018B25": "age_18_24", "ALT025B40": "age_25_39",
       "ALT040B60": "age_40_59", "ALT060UM": "age_60plus", "UNBEKANNT": "age_unknown"}
BASE = "housed_homeless"

CELL_DDL = """
CREATE TABLE IF NOT EXISTS counts_law_destatis_cell (
  table_code  TEXT NOT NULL,
  level       TEXT NOT NULL,      -- de | land | kreis
  region_code TEXT NOT NULL,      -- DE | 2-digit Land AGS | 5-digit Kreis AGS
  region_name TEXT,
  stichtag    TEXT NOT NULL,      -- YYYY-01-31
  nat         TEXT NOT NULL,      -- NATD | NATA | %TOTAL%
  sex         TEXT NOT NULL,      -- GESM | GESW | UNBEKANNT | %TOTAL%
  age         TEXT NOT NULL,      -- ALT000B18 .. ALT060UM | UNBEKANNT | %TOTAL%
  value       REAL,               -- NULL when the cell is suppressed / not available
  status      TEXT,               -- GENESIS quality flag: e (value) | - (zero) | . x / ...
  source_id   INTEGER,
  PRIMARY KEY (table_code, region_code, stichtag, nat, sex, age)
);
"""


_FORCE = [False]


def _get_json(url: str):
    return json.loads(fetch(url, domain=DOMAIN, headers={"Accept": "application/json"}, force=_FORCE[0]))


def decode_cube(data: dict, structure: dict, region_var: str):
    """Yield (region_code, region_label, stichtag, nat, sex, age, value, status) for every cell."""
    ds = data["data"][0]
    ids, sizes = ds["id"], ds["size"]
    inv = {k: {i: c for c, i in ds["dimension"][k]["category"]["index"].items()}
           for k in ids if k in ds.get("dimension", {})}
    labels = structure.get("variableValues", {})
    values, status = ds["value"], ds.get("status") or ["e"] * len(ds["value"])
    for n, (v, st) in enumerate(zip(values, status)):
        idx, r = [], n
        for sz in reversed(sizes):
            idx.append(r % sz)
            r //= sz
        idx.reverse()
        key = {k: (inv[k][i] if k in inv else None) for k, i in zip(ids, idx)}
        reg = key.get(region_var) or "DE"
        if region_var == "DINSG":
            reg = "DE"
        lab = (labels.get(key.get(region_var) or "", {}).get("label") or {}).get("de")
        yield (reg, lab, key["STAG"], key["NAT"], key["GES02"], key["ALT026"], v, st)



# --- Fail-loud shape guard for the anonymous GENESIS JSON (Lead request 2026-11-21) -------------------
# The /api/rest/tables/<code>/data endpoint is undocumented. If its shape drifts, the ingest must stop
# with a clear message instead of silently writing zero or wrong rows.
class GenesisShapeError(RuntimeError):
    """Raised when a GENESIS cube or press release no longer looks like what this module was written for."""


EXPECTED_STAG = {f"{y}-01-31" for y in PRESS}           # one press release per Stichtag; extend both together
EXPECTED_CATS = {"NAT": {T, *NAT}, "GES02": {T, *SEX}, "ALT026": {T, *AGE}}
MIN_REGIONS = {"de": 1, "land": 16, "kreis": 390}          # live regions with at least one value
PRESS_TOL = 1000                                           # press releases round to the nearest thousand


def validate_cube(code: str, data, structure) -> None:
    etype, region_var = TABLES[code]

    def bad(msg):
        raise GenesisShapeError(f"GENESIS {code}: {msg} -- endpoint shape changed? Refusing to ingest. "
                                f"Check {API}/tables/{code}/data by hand and update counts_law.py.")
    if not isinstance(data, dict) or not isinstance(data.get("data"), list) or not data["data"]:
        bad("response has no non-empty 'data' list")
    if not isinstance(structure, dict):
        bad("structure response is not a JSON object")
    ds = data["data"][0]
    for k in ("id", "size", "dimension", "value"):
        if k not in ds:
            bad(f"cube is missing key '{k}' (has {sorted(ds)})")
    ids, sizes, dims = ds["id"], ds["size"], ds["dimension"]
    if len(ids) != len(sizes):
        bad(f"len(id)={len(ids)} != len(size)={len(sizes)}")
    need = {"STAG", "NAT", "GES02", "ALT026", region_var}
    missing = need - set(ids)
    if missing:
        bad(f"missing dimension(s) {sorted(missing)} (has {ids})")
    for k, sz in zip(ids, sizes):
        idx = (dims.get(k) or {}).get("category", {}).get("index")
        if not isinstance(idx, dict) or len(idx) != sz:
            bad(f"dimension {k}: category index has {len(idx) if isinstance(idx, dict) else 'no'} entries, size says {sz}")
    total = 1
    for sz in sizes:
        total *= sz
    if len(ds["value"]) != total:
        bad(f"{len(ds['value'])} values but dimensions multiply to {total}")
    st = ds.get("status")
    if st is not None and len(st) != total:
        bad(f"{len(st)} status flags for {total} values")
    stag = set(dims["STAG"]["category"]["index"])
    if stag != EXPECTED_STAG:
        bad(f"unexpected Stichtag set: new {sorted(stag - EXPECTED_STAG)}, missing {sorted(EXPECTED_STAG - stag)} "
            f"(a new Stichtag needs its press-release URL in PRESS)")
    for k, want in EXPECTED_CATS.items():
        got = set(dims[k]["category"]["index"])
        if got != want:
            bad(f"dimension {k} categories changed: {sorted(got)} != {sorted(want)}")
    status = st or ["e"] * total
    n_val = sum(1 for v, f in zip(ds["value"], status) if f == "e" and isinstance(v, (int, float)) and v > 0)
    if n_val == 0:
        bad("zero non-empty cells")
    # regions with any value
    inv = {i: c for c, i in dims[region_var]["category"]["index"].items()}
    pos = ids.index(region_var)
    stride = 1
    for sz in sizes[pos + 1:]:
        stride *= sz
    live = {inv[(n // stride) % sizes[pos]] for n, f in enumerate(status) if f in ("e", "-")}
    if len(live) < MIN_REGIONS[etype]:
        bad(f"only {len(live)} {etype} regions carry values, expected >= {MIN_REGIONS[etype]}")
    if etype == "land" and live != set(LAND):
        bad(f"Länder codes changed: {sorted(live ^ set(LAND))}")


def check_press(year: int, rounded, exact) -> None:
    if rounded is None:
        raise GenesisShapeError(f"press release {year} ({PRESS[year]}): total not found -- page layout changed?")
    if exact is None:
        raise GenesisShapeError(f"22971-0001 has no national total for {year} to compare with the press release")
    if abs(rounded - exact) > PRESS_TOL:
        raise GenesisShapeError(f"national total {year}: GENESIS {exact:,.0f} vs press release {rounded:,} "
                                f"(tolerance {PRESS_TOL}) -- cube values look wrong, refusing to continue")

def _metric_value(v, st):
    if st == "e":
        return v
    if st == "-":
        return 0.0
    return None


# --- Kreis code changes inside the 22971-0080 window (Stichtage 2022-2026), Lead request 2026-11-21 --------
# The cube lists 477 KREISE codes: today's Kreise plus historic ones labelled "(bis dd.mm.yyyy)" / "(b.dd.mm.yyyy)".
#  * 16056 "Eisenach, kreisfreie Stadt (bis 30.06.2021)" still carries a value on 31.01.2022 (10 persons, '-' after).
#    Eisenach was incorporated into the Wartburgkreis (16063) on 01.07.2021 (TLS). Results are shown by place of
#    accommodation (Destatis quality report), so the 2022 16056 persons are in today's Wartburgkreis territory:
#    metric/pit for 16063 = published 16063 cell + published 16056 cell, with a note; the raw 16056 cells stay as
#    published in counts_law_destatis_cell; no geo/metric/pit row is kept for the dissolved code.
#  * 06415 Hanau became kreisfrei on 01.01.2026 (Hessen Innenministerium); its '-' before 2026 means "unit did not
#    exist" (it was part of Main-Kinzig-Kreis 06435), so no rows are written for 2022-2025.
#  * 09475 Hof (Landkreis) and 16062 Nordhausen are current Kreise published as '-' (= "nichts vorhanden") on every
#    Stichtag. They are kept as 0 with a note; the statistic suppresses nothing (5er-Rundung only), see research.
KREIS_FOLD = {"16056": ("16063", "2021-07-01", "Eisenach, kreisfreie Stadt (bis 30.06.2021)")}
KREIS_FROM = {"06415": "2026-01-01"}
KREIS_DASH_ALL = {"09475", "16062"}
_HISTORIC = re.compile(r"\((?:bis|b\.)\s*\d{1,2}\.\d{1,2}\.\d{4}\)")
LIC_TLS = "Thüringer Landesamt für Statistik; Vervielfältigung und Verbreitung mit Quellenangabe gestattet"
LIC_HMDIS = "Rechte vorbehalten: Hessisches Ministerium des Innern, amtliche Webseite ohne offene Lizenz; nur Fundstelle und kurzes Zitat mit Quellenangabe (§ 51 UrhG)"
KREIS_EVIDENCE = [
    # (key, url, title, publisher, licence, needles)
    ("destatis_22971_info", f"{API}/statistics/22971/information",
     "GENESIS-Online 22971: Statistik untergebrachter wohnungsloser Personen – Informationen (Qualitätsbericht)",
     PUBLISHER, LICENSE,
     ["Geheimhaltungsverfahrens der 5er-Rundung",
      "auf Grundlage des Ortes der Unterbringung der wohnungslosen Personen"]),
    ("destatis_zeichen", "https://www.destatis.de/DE/Methoden/WISTA-Wirtschaft-und-Statistik/2026/04/wista-042026.pdf?__blob=publicationFile",
     "WISTA Wirtschaft und Statistik 4/2026 – Zeichenerklärung", PUBLISHER, LICENSE,
     ["ZEICHENERKLÄRUNG", "nichts vorhanden", "Zahlenwert unbekannt oder geheim zu halten"]),
    ("tls_eisenach", "https://statistik.thueringen.de/Datenbank/gebiet3.asp?nr=56000",
     "TLS Gebietsveränderungen: Kreisfreie Stadt 56000 Eisenach, Stadt", "Thüringer Landesamt für Statistik", LIC_TLS,
     ["Eingliederung in einen Landkreis (Status der kreisfreien Stadt wird aufgegeben)", "63105 Eisenach, Stadt", "01.07.2021"]),
    ("he_hanau", "https://innen.hessen.de/kommunales/kommunen/gemeinden-und-landkreise",
     "Hessisches Ministerium des Innern: Gemeinden und Landkreise (Hanau-Auskreisung)", "Hessisches Ministerium des Innern",
     LIC_HMDIS, ["Die Stadt Hanau wurde mit Wirkung zum 1. Januar 2026",
                 "zur kreisfreien Stadt erklärt und aus dem Main-Kinzig-Kreis ausgegliedert"]),
]


def kreis_evidence(conn, problems: list) -> None:
    """Archive + verify the documents behind KREIS_FOLD / KREIS_FROM / KREIS_DASH_ALL (fail loud on a changed text)."""
    for key, url, title, pub, lic, needles in KREIS_EVIDENCE:
        try:
            raw = fetch(url, domain=DOMAIN, force=_FORCE[0])
        except Exception as e:  # noqa: unreachable evidence is reported, the published cells are still stored
            problems.append(f"{key}:fetch-failed({e!r:.80})")
            continue
        if raw[:1] == b"{":  # GENESIS information JSON: search the German description text
            text = " ".join(json.loads(raw).get("description", {}).get("de", "").split())
        else:
            text = _doc_text(raw)
        save_raw(DOMAIN, f"kreis_{key}.{'pdf' if raw[:4] == b'%PDF' else ('json' if raw[:1] == b'{' else 'html')}", raw)
        missing = [n for n in needles if n not in text]
        if missing:
            raise GenesisShapeError(f"Kreis evidence {key}: phrase not found {missing[0]!r} -- re-check KREIS_* rules")
        source_id_for(conn, url, DOMAIN, title=title, publisher=pub, license=lic)


def ingest_table(conn, code: str, counts: dict) -> int:
    etype, region_var = TABLES[code]
    data_url = f"{API}/tables/{code}/data"
    struct_url = f"{API}/tables/{code}/structure"
    structure = _get_json(struct_url)
    data = _get_json(data_url)
    validate_cube(code, data, structure)  # raises GenesisShapeError before anything is written
    title = (structure.get("table", {}).get("label") or {}).get("de", code).replace("\n", " ")
    last_change = structure.get("table", {}).get("lastChange")
    sid = source_id_for(conn, data_url, DOMAIN, title=f"GENESIS-Online {code}: {title}",
                        publisher=PUBLISHER, license=LICENSE)
    source_id_for(conn, struct_url, DOMAIN, title=f"GENESIS-Online {code} structure (labels)",
                  publisher=PUBLISHER, license=LICENSE)
    page = PAGE.format(code=code)

    cells = list(decode_cube(data, structure, region_var))
    fold_add = defaultdict(float)  # (target, metric, stichtag) -> persons published under a dissolved code
    if etype == "kreis":
        historic = {c[0] for c in cells if _HISTORIC.search(c[1] or "")}
        with_data = {c[0] for c in cells if c[7] == "e"}
        unmapped = sorted((with_data & historic) - set(KREIS_FOLD))
        if unmapped:
            raise GenesisShapeError(f"GENESIS {code}: historic Kreis code(s) {unmapped} carry data but have no mapping")
        for reg, frm in KREIS_FROM.items():
            early = [c for c in cells if c[0] == reg and c[2] < frm and c[7] == "e"]
            if early:
                raise GenesisShapeError(f"GENESIS {code}: {reg} has data before {frm} -- check KREIS_FROM")
        dash_all = {c[0] for c in cells if c[0] not in historic} - with_data
        if dash_all != KREIS_DASH_ALL:
            raise GenesisShapeError(f"GENESIS {code}: Kreise published '-' on every Stichtag changed: {sorted(dash_all)}")
        # remove rows an earlier version of this module wrote for a dissolved code (own rows only)
        for old in KREIS_FOLD:
            for t, k in (("metric", "entity_id"), ("zaehlung", "geo_ags")):
                conn.execute(f"DELETE FROM {t} WHERE {k}=? AND source_id IN (SELECT id FROM source WHERE domain=?)",
                             (old, DOMAIN))
            conn.execute("DELETE FROM geo_kreis WHERE ags=? AND source_id IN (SELECT id FROM source WHERE domain=?)",
                         (old, DOMAIN))
        for reg, frm in KREIS_FROM.items():  # rows written for a unit before it existed (own rows only)
            conn.execute("DELETE FROM metric WHERE entity_type='kreis' AND entity_id=? AND year<? AND source_id IN "
                         "(SELECT id FROM source WHERE domain=?)", (reg, int(frm[:4]), DOMAIN))
            conn.execute("DELETE FROM zaehlung WHERE geo_kind='kreis' AND geo_ags=? AND berichtsjahr<? AND source_id IN "
                         "(SELECT id FROM source WHERE domain=?)", (reg, int(frm[:4]), DOMAIN))
    n = 0
    regions_seen = set()
    for reg, lab, stag, nat, sex, age, v, st in cells:
        if etype == "kreis":
            if reg in historic and reg not in KREIS_FOLD:
                continue
        upsert(conn, "counts_law_destatis_cell",
               {"table_code": code, "level": etype, "region_code": reg, "region_name": lab,
                "stichtag": stag, "nat": nat, "sex": sex, "age": age,
                "value": _metric_value(v, st), "status": st, "source_id": sid},
               keys=["table_code", "region_code", "stichtag", "nat", "sex", "age"])
        counts["cells"] += 1
        if etype == "kreis" and reg in KREIS_FROM and stag < KREIS_FROM[reg]:
            continue  # raw cell kept as published; the unit did not exist yet, so no metric/pit row
        if etype == "kreis" and reg in KREIS_FOLD:
            pass  # no geo row for a dissolved code
        else:
            regions_seen.add((reg, lab))
        # margins -> metric rows
        name = None
        if nat == T and sex == T and age == T:
            name = BASE
        elif nat == T and age == T and sex in SEX:
            name = f"{BASE}__{SEX[sex]}"
        elif sex == T and age == T and nat in NAT:
            name = f"{BASE}__{NAT[nat]}"
        elif nat == T and sex == T and age in AGE:
            name = f"{BASE}__{AGE[age]}"
        if name is None:
            continue
        val = _metric_value(v, st)
        if val is None:
            counts["suppressed"] += 1
            continue
        if etype == "kreis" and reg in KREIS_FOLD:
            fold_add[(KREIS_FOLD[reg][0], name, stag, reg)] += val
            continue
        eid = "DE" if etype == "de" else reg
        upsert(conn, "metric",
               {"entity_type": etype, "entity_id": eid, "metric": name, "value": val,
                "einheit": "persons", "year": int(stag[:4]), "is_est": 0,
                "anmerkung": (f"Destatis Statistik untergebrachter wohnungsloser Personen, Stichtag "
                         f"{stag[8:10]}.{stag[5:7]}.{stag[:4]}, GENESIS {code} (status '{st}'; cells rounded "
                         f"to multiples of 5); table page {page}; table lastChange {last_change}"
                         + ("; published as '-' (nichts vorhanden) on every Stichtag 2022-2026"
                            if etype == "kreis" and reg in KREIS_DASH_ALL else "")),
                "source_id": sid},
               keys=["entity_type", "entity_id", "metric", "year"])
        counts["metric"] += 1
        n += 1
        if name in (BASE, f"{BASE}__age_lt18"):
            geo_kind = {"de": "bund", "land": "land", "kreis": "kreis"}[etype]
            col = "untergebracht" if name == BASE else "minderjaehrige"
            upsert(conn, "zaehlung", {"geo_ags": eid, "geo_kind": geo_kind, "berichtsjahr": int(stag[:4]),
                                 col: int(val), "is_est": 0, "source_id": sid},
                   keys=["geo_ags", "geo_kind", "berichtsjahr"])
            counts["pit_cells"] += 1
    # schema 3: geography belongs to the Lead's geo domains (geo_bkg, geo_bevoelkerung). This module writes no
    # geo_* rows at all; it only reports codes it published that the Lead's geo does not (yet) have.
    geo_table = {"land": "geo_land", "kreis": "geo_kreis"}.get(etype)
    if geo_table and conn.execute(f"SELECT 1 FROM {geo_table} LIMIT 1").fetchone() is not None:
        absent = sorted(reg for reg, _ in regions_seen
                        if conn.execute(f"SELECT 1 FROM {geo_table} WHERE ags=?", (reg,)).fetchone() is None)
        if absent:
            counts.setdefault("geo_absent", []).extend(absent)
    for (target, name, stag, old), add in fold_add.items():
        if not add:
            continue
        year = int(stag[:4])
        row = conn.execute("SELECT value FROM metric WHERE entity_type='kreis' AND entity_id=? AND metric=? AND year=?",
                           (target, name, year)).fetchone()
        if row is None:
            raise GenesisShapeError(f"GENESIS {code}: fold target {target} {name} {year} missing")
        tot = row[0] + add
        why = (f"; value = {row[0]:.0f} published for {target} + {add:.0f} published under the dissolved code {old} "
               f"({KREIS_FOLD[old][2]}), incorporated into {target} on {KREIS_FOLD[old][1]} (TLS); results are by place "
               f"of accommodation; sum of two 5-rounded cells (max. deviation 4)")
        conn.execute("UPDATE metric SET value=?, anmerkung=anmerkung||? WHERE entity_type='kreis' AND entity_id=? AND metric=? "
                     "AND year=?", (tot, why, target, name, year))
        if name in (BASE, f"{BASE}__age_lt18"):
            col = "untergebracht" if name == BASE else "minderjaehrige"
            conn.execute(f"UPDATE zaehlung SET {col}=? WHERE geo_ags=? AND geo_kind='kreis' AND berichtsjahr=?", (int(tot), target, year))
        counts["kreis_folded"] += 1
    if n == 0:
        raise GenesisShapeError(f"GENESIS {code}: decoded 0 metric rows -- refusing to return an empty result")
    return n


# --- Part 2: estimates (BMWSB Wohnungslosenbericht, BAG W Hochrechnung) ------------------------------
#
# Every figure below is written only if its exact printed form (German thousands separator, e.g.
# "47.270") is found on the stated page of the archived PDF (pdftotext -layout, page = PDF page index,
# 1-based). Anything not found is skipped and reported in notes -- nothing is typed in unchecked.
# All rows go to `metric` (never `pit`): the Destatis pit rows stay the only pit source.

PUB_BMWSB = "Bundesministerium für Wohnen, Stadtentwicklung und Bauwesen (BMWSB)"
PUB_BAGW = "Bundesarbeitsgemeinschaft Wohnungslosenhilfe e. V. (BAG W)"
# Licence audit 2026-11-23 (Lead): § 5 UrhG only for statutes, ordinances, Erlasse, court decisions and official
# gazettes. Reports, plans, Drucksachen and statistics brochures without an open licence are "Rechte vorbehalten":
# the atlas keeps numbers with locator, own summary and a short attributed quote (§ 51 UrhG), never the full text,
# and run() sets redistribute_fulltext=0 on every source whose licence says "Rechte vorbehalten".
RIGHTS_RESERVED = "Rechte vorbehalten"
_KEEP_NUM = ("; im Atlas nur Zahlen mit Fundstelle, eigene Zusammenfassung und kurzes Zitat mit Quellenangabe "
             "(§ 51 UrhG), kein Volltext")
LIC_BUND = ("Rechte vorbehalten: Bericht im Auftrag der Bundesregierung (Ministeriumsveröffentlichung), kein Gesetz, "
            "keine Verordnung und kein Erlass, daher nicht § 5 Abs. 1 UrhG; kein offener Lizenzhinweis" + _KEEP_NUM)
LIC_BAGW = "Rechte vorbehalten: © BAG W; Pressemitteilung/Pressemappe zur freien Verwendung durch Medien; zitiert mit Quellenangabe"

DOCS = {
    "wb2024": ("https://www.bmwsb.bund.de/SharedDocs/downloads/DE/veroeffentlichungen/wohnen/"
               "wohnungslosenbericht-2024.pdf?__blob=publicationFile&v=1",
               "Wohnungslosenbericht der Bundesregierung 2024 (GISS/Verian, Befragung 1.-7. Februar 2024)",
               PUB_BMWSB, LIC_BUND),
    "wb2022": ("https://www.bmwsb.bund.de/SharedDocs/downloads/DE/veroeffentlichungen/wohnen/"
               "wohnungslosenbericht-2022.pdf?__blob=publicationFile&v=2",
               "Ausmaß und Struktur von Wohnungslosigkeit: Der Wohnungslosenbericht 2022 (GISS/Kantar, 1.-7. Februar 2022)",
               "Bundesministerium für Arbeit und Soziales (BMAS); hosted by BMWSB", LIC_BUND),
    "bagw2025": ("https://www.bagw.de/fileadmin/bagw/media/Doc/PRM/PRM_25_BAG_W_Hochrechnung_2025_Pressemappe.pdf",
                 "BAG W Pressemappe 17.11.2025: Hochrechnung Zahl der wohnungslosen Menschen 2023/2024",
                 PUB_BAGW, LIC_BAGW),
    "bagw2023": ("https://www.bagw.de/fileadmin/bagw/media/Doc/PRM/"
                 "PRM_PM_BAG_W_Pressemappe_Hochrechnung_Zahl_der_wohnungslosen_Menschen.pdf",
                 "BAG W Pressemappe 07.11.2023: Hochrechnung Zahl der wohnungslosen Menschen 2021/2022",
                 PUB_BAGW, LIC_BAGW),
    "bagw2021": ("https://www.bagw.de/fileadmin/bagw/media/Doc/PRM/PRM_2021_12_21_BAGW_Schaetzung.pdf",
                 "BAG W Pressemitteilung 21.12.2021: Schätzung Zahl der Wohnungslosen 2018-2020",
                 PUB_BAGW, LIC_BAGW),
}

# Land groups printed in Wohnungslosenbericht 2024 Tabelle 3-3 (not single Länder: own entity_type,
# entity_id = '+'-joined Land AGS, so no AGS is invented).

# ---- Part 3: Länder / city counts that Destatis does not publish (own source_id, never into pit) ----
PUB_MAGS = "Ministerium für Arbeit, Gesundheit und Soziales des Landes Nordrhein-Westfalen (MAGS NRW); Daten: IT.NRW"
PUB_AGH = "Abgeordnetenhaus Berlin / Senatsverwaltung für Integration, Arbeit und Soziales"
LIC_LAND = ("Rechte vorbehalten: Bericht/Drucksache einer Landesbehörde oder eines Landesparlaments, kein Gesetz, "
            "keine Verordnung und kein Erlass, daher nicht § 5 Abs. 1 UrhG; kein offener Lizenzhinweis" + _KEEP_NUM)
LIC_MUC = ("Rechte vorbehalten: Sitzungsvorlage der Landeshauptstadt München (Ratsinformationssystem), kein Gesetz und "
           "keine Satzung, daher nicht § 5 Abs. 1 UrhG; kein offener Lizenzhinweis" + _KEEP_NUM)
DOCS.update({
    "nrw_wnb2024": ("https://mags.nrw/system/files/media/document/file/mags-wnb-nrw-2024.pdf",
                    "Integrierte Wohnungsnotfall-Berichterstattung 2024 in Nordrhein-Westfalen (Stichtag 30.06.2024)",
                    PUB_MAGS, LIC_LAND),
    "be_nds2020": ("https://pardok.parlament-berlin.de/starweb/adis/citat/VT/19/SchrAnfr/S19-10884.pdf",
                   "Abgeordnetenhaus Berlin Drucksache 19/10884: Schriftliche Anfrage '1. und 2. Nacht der Solidarität', "
                   "Antwort der Senatsverwaltung vom 24.02.2022",
                   PUB_AGH, LIC_LAND),
})


# ---- Part 3b: Hamburg, München, Baden-Württemberg ----
PUB_HH = "Freie und Hansestadt Hamburg, BASFI (Auftraggeber); Bericht: GOE Gesellschaft für Organisation und Entscheidung, Bielefeld"
PUB_MUC = "Landeshauptstadt München, Sozialreferat (Ratsinformationssystem RIS)"
PUB_BWSM = "Ministerium für Arbeit und Sozialordnung, Familie, Frauen und Senioren Baden-Württemberg; Bericht: GISS e.V."
PUB_LIGA = "Liga der freien Wohlfahrtspflege in Baden-Württemberg e.V."
LIC_STUDY = "Rechte vorbehalten: amtlich beauftragte Studie / Verbandsbericht, frei veröffentlicht, ohne offene Lizenz" + _KEEP_NUM
DOCS.update({
    "hh_goe2018": ("https://www.goe-bielefeld.de/download/Auswertungsbericht_Obdach-,_Wohnungslosigkeit_Hamburg_2018.pdf",
                   "Befragung obdachloser, auf der Straße lebender Menschen und wohnungsloser, öffentlich-rechtlich "
                   "untergebrachter Haushalte 2018 in Hamburg (GOE, Nov. 2018, im Auftrag der BASFI)", PUB_HH, LIC_STUDY),
    "muc_pc2025": ("https://risi.muenchen.de/risi/dokument/v/9783666",
                   "Landeshauptstadt München: Produktcontrolling des Sozialreferates zum Stand 31.12.2025", PUB_MUC, LIC_MUC),
    "bw_giss2015": ("https://www.giss-ev.de/filestorage/publikationen/bericht-wohnungslosigkeit-in-baden-wuerttemberg.pdf",
                    "Wohnungslosigkeit in Baden-Württemberg. Untersuchung zu Umfang, Struktur und Hilfen für Menschen in "
                    "Wohnungsnotlagen (GISS 2015, Stichtag 01.10.2014)", PUB_BWSM, LIC_STUDY),
    "bw_liga2024": ("https://liga-bw.de/wp-content/uploads/2025/02/2025_02_20_ligabw_Bericht_Stichtagserhebung_2024.pdf",
                    "Liga Stichtagserhebung 2024: Erhebung im Hilfesystem nach §§ 67 ff. SGB XII in Baden-Württemberg "
                    "(Stichtag 27.09.2024)", PUB_LIGA, LIC_STUDY),
})

LG = {"SH/NI/HB": ("land_group", "01+03+04"), "HH": ("land", "02"), "NW": ("land", "05"),
      "HE/RP/SL": ("land_group", "06+07+10"), "BW": ("land", "08"), "BY": ("land", "09"),
      "BE": ("land", "11"), "OST": ("land_group", "12+13+14+15+16")}
GK = {"1-5": "GKPOL1-5", "6": "GKPOL6", "7": "GKPOL7"}

# (doc, pdf_page, metric, entity_type, entity_id, year, value, is_est, needle_or_None, note)
_D = ("de", "DE")
FIGURES = []


def _f(doc, page, metric, ent, year, value, is_est=1, needle=None, note="", unit="persons"):
    FIGURES.append((doc, page, metric, ent[0], ent[1], year, value, is_est, needle, note, unit))


# Wohnungslosenbericht 2024, Tabelle 5-1 (p. 86): the three groups and the de-duplicated total
_t51 = "Wohnungslosenbericht 2024, Tabelle 5-1 (S. 86)"
_f("wb2024", 86, "wb_housed", _D, 2024, 439466, 0, note=f"{_t51}: untergebrachte wohnungslose Personen (Destatis 31.01.2024, as printed in the report)")
_f("wb2024", 86, "wb_housed__minors", _D, 2024, 128705, 0, note=f"{_t51}: davon untergebrachte Minderjährige")
_f("wb2024", 86, "wb_unsheltered", _D, 2024, 47270, note=f"{_t51}: wohnungslose Personen ohne Unterkunft, 1.-7.2.2024, incl. all minors (2.051)")
_f("wb2024", 86, "wb_unsheltered__housed_0131", _D, 2024, 10939, note=f"{_t51}: davon am 31. Januar untergebracht (double count with Destatis)")
_f("wb2024", 86, "wb_unsheltered__minors", _D, 2024, 2051, note=f"{_t51}: davon wohnungslose Minderjährige ohne Unterkunft")
_f("wb2024", 86, "wb_hidden", _D, 2024, 60435, note=f"{_t51}: verdeckt wohnungslose Personen, 1.-7.2.2024, incl. all minors (6.602)")
_f("wb2024", 86, "wb_hidden__housed_0131", _D, 2024, 4631, note=f"{_t51}: davon am 31. Januar untergebracht (double count with Destatis)")
_f("wb2024", 86, "wb_hidden__minors", _D, 2024, 6602, note=f"{_t51}: davon verdeckt wohnungslose Minderjährige")
_f("wb2024", 86, "wb_total_homeless", _D, 2024, 531601, note=f"{_t51}: Insgesamt (housed + unsheltered + hidden, minus 15.570 double counts)")
_f("wb2024", 23, "wb_double_count_0131", _D, 2024, 15570, note="Wohnungslosenbericht 2024, S. 23: Schnittmenge mit der Destatis-Statistik (10.939 ohne Unterkunft + 4.631 verdeckt)")
# Tabelle 3-1 (p. 22)
_t31 = "Wohnungslosenbericht 2024, Tabelle 3-1 (S. 22)"
_f("wb2024", 22, "wb_unsheltered__adults", _D, 2024, 45219, note=f"{_t31}: Erwachsene ohne Unterkunft")
_f("wb2024", 22, "wb_hidden__adults", _D, 2024, 53833, note=f"{_t31}: verdeckt wohnungslose Erwachsene")
_f("wb2024", 22, "wb_unsheltered__minors_with_parents", _D, 2024, 1932, note=f"{_t31}: Minderjährige mit Eltern lebend (not surveyed themselves)")
_f("wb2024", 22, "wb_hidden__minors_with_parents", _D, 2024, 6566, note=f"{_t31}: Minderjährige mit Eltern lebend (not surveyed themselves)")
_f("wb2024", 22, "wb_unsheltered_or_hidden", _D, 2024, 107705, note=f"{_t31}: nicht institutionell untergebrachte Wohnungslose insgesamt")
# Tabelle 3-2 (p. 22): by Gemeindegrößenklasse (excl. 8.498 minors living with parents)
_t32 = "Wohnungslosenbericht 2024, Tabelle 3-2 (S. 22), excl. minors living with parents"
_f("wb2024", 22, "wb_unsheltered_surveyed", _D, 2024, 45338, note=f"{_t32}: ohne Unterkunft, Insgesamt")
_f("wb2024", 22, "wb_hidden_surveyed", _D, 2024, 53869, note=f"{_t32}: verdeckt, Insgesamt")
_f("wb2024", 22, "wb_unsheltered_or_hidden_surveyed", _D, 2024, 99207, note=f"{_t32}: Insgesamt")
for gk, (u, h, t) in {"1-5": (12006, 28324, 40330), "6": (13311, 14768, 28079), "7": (20021, 10777, 30798)}.items():
    ent = ("de_gkpol", GK[gk])
    _f("wb2024", 22, "wb_unsheltered_surveyed", ent, 2024, u, note=f"{_t32}: GKPOL {gk}")
    _f("wb2024", 22, "wb_hidden_surveyed", ent, 2024, h, note=f"{_t32}: GKPOL {gk}")
    _f("wb2024", 22, "wb_unsheltered_or_hidden_surveyed", ent, 2024, t, note=f"{_t32}: GKPOL {gk}")
# Tabelle 3-3 (p. 24): by Land (grouped)
_t33 = "Wohnungslosenbericht 2024, Tabelle 3-3 (S. 24), Bundesländer gruppiert, excl. minors living with parents"
for g, (u, h, t) in {"SH/NI/HB": (8604, 19521, 28126), "HH": (3787, 1685, 5471), "NW": (10705, 13387, 24091),
                     "HE/RP/SL": (4201, 3165, 7366), "BW": (3505, 3501, 7006), "BY": (5763, 7558, 13321),
                     "BE": (6032, 2364, 8396), "OST": (2740, 2689, 5430)}.items():
    lab = "Ostdeutschland ohne Berlin (BB, MV, SN, ST, TH)" if g == "OST" else g
    _f("wb2024", 24, "wb_unsheltered_surveyed", LG[g], 2024, u, note=f"{_t33}: {lab}")
    _f("wb2024", 24, "wb_hidden_surveyed", LG[g], 2024, h, note=f"{_t33}: {lab}")
    _f("wb2024", 24, "wb_unsheltered_or_hidden_surveyed", LG[g], 2024, t, note=f"{_t33}: {lab}")
# Tabelle 3-4 (p. 27): sex and age (respondents with valid sex/age answers only)
_t34 = "Wohnungslosenbericht 2024, Tabelle 3-4 (S. 27), only respondents with sex+age given"
for grp, vals in {"wb_unsheltered_resp": dict(total=42394, male=33384, female=8599, diverse=411,
                                              age_lt25=3642, age_25_29=3655, age_30_39=10781,
                                              age_40_49=11419, age_50_64=10815, age_65plus=2082),
                  "wb_hidden_resp": dict(total=52270, male=29538, female=22547, diverse=185,
                                         age_lt25=14554, age_25_29=7718, age_30_39=10504,
                                         age_40_49=9223, age_50_64=9203, age_65plus=1068)}.items():
    for k, v in vals.items():
        _f("wb2024", 27, grp if k == "total" else f"{grp}__{k}", _D, 2024, v, note=f"{_t34}: {k}")

# Wohnungslosenbericht 2022 (BMAS), Tabelle 5.1.1 (PDF p. 57, printed p. 55) -- rounded as printed
_t511 = "Wohnungslosenbericht 2022, Tabelle 5.1.1 (PDF S. 57 / gedruckt S. 55), gerundet"
_f("wb2022", 57, "wb_housed", _D, 2022, 178100, 0, note=f"{_t511}: untergebrachte wohnungslose Personen (Destatis 31.01.2022, rounded)")
_f("wb2022", 57, "wb_unsheltered", _D, 2022, 37400, note=f"{_t511}: ohne Unterkunft, 1.-7.2.2022, EXCLUDING 1.100 minors living with parents (2024 figure includes them)")
_f("wb2022", 57, "wb_unsheltered__housed_0131", _D, 2022, 6000, note=f"{_t511}: davon am 31. Januar untergebracht")
_f("wb2022", 57, "wb_unsheltered__minors_with_parents", _D, 2022, 1100, note=f"{_t511}: wohnungslose Minderjährige ohne Unterkunft (with parents, not surveyed)")
_f("wb2022", 57, "wb_hidden", _D, 2022, 49300, note=f"{_t511}: verdeckt wohnungslos, EXCLUDING 5.500 minors living with parents")
_f("wb2022", 57, "wb_hidden__housed_0131", _D, 2022, 2800, note=f"{_t511}: davon am 31. Januar untergebracht")
_f("wb2022", 57, "wb_hidden__minors_with_parents", _D, 2022, 5500, note=f"{_t511}: verdeckt wohnungslose Minderjährige (with parents, not surveyed)")
_f("wb2022", 57, "wb_total_homeless", _D, 2022, 262600, note=f"{_t511}: Insgesamt (three groups + 6.600 minors - 8.800 double counts)")
_f("wb2022", 11, "wb_double_count_0131", _D, 2022, 8800, note="Wohnungslosenbericht 2022, Zusammenfassung (PDF S. 11): rund 8.800 Doppelerfassungen")
_f("wb2022", 25, "wb_unsheltered_or_hidden_surveyed", _D, 2022, 86700, note="Wohnungslosenbericht 2022, Kap. 3 (PDF S. 25): rund 86.700 (37.400 + 49.300), excl. 6.600 minors")

# BAG W Hochrechnung (own method: Jahresgesamtzahl over a calendar year + Stichtag 30 June; based on
# NRW Wohnungsnotfallberichterstattung, BAG W Wohnungsnotfalldefinition) -- all is_est=1
_b25 = "BAG W Pressemappe 17.11.2025, S. 1"
_f("bagw2025", 1, "bagw_homeless_year", _D, 2024, 1029000, note=f"{_b25}: Jahresgesamtzahl 2024 (mindestens)")
_f("bagw2025", 1, "bagw_homeless_year", _D, 2023, 928000, note=f"{_b25}: Jahresgesamtzahl 2023")
_f("bagw2025", 1, "bagw_unsheltered_year", _D, 2024, 56000, note=f"{_b25}: rund, ohne Unterkunft auf der Straße, im Jahr 2024")
_f("bagw2025", 1, "bagw_unsheltered_year", _D, 2023, 54000, note=f"{_b25}: ohne Unterkunft, 2023")
_f("bagw2025", 1, "bagw_homeless_0630", _D, 2024, 760000, note=f"{_b25}: Stichtag 30.06.2024")
_f("bagw2025", 1, "bagw_homeless_0630", _D, 2023, 681000, note=f"{_b25}: Stichtag 30.06.2023")
_f("bagw2025", 1, "bagw_homeless_year__ordnungsrechtlich", _D, 2024, 840000, note=f"{_b25}: circa, ordnungsrechtlich durch Städte und Kommunen untergebracht")
_f("bagw2025", 1, "bagw_homeless_year__adults", _D, 2024, 765000, needle="rund 765.000", note=f"{_b25}: Erwachsene")
_f("bagw2025", 1, "bagw_homeless_year__adult_men", _D, 2024, 465000, note=f"{_b25}: Männer")
_f("bagw2025", 1, "bagw_homeless_year__adult_women", _D, 2024, 300000, note=f"{_b25}: Frauen")
_f("bagw2025", 1, "bagw_homeless_year__minors", _D, 2024, 264000, note=f"{_b25}: Kinder und Jugendliche unter 18")
_f("bagw2025", 1, "bagw_homeless_year__non_german", _D, 2024, 820000, note=f"{_b25}: keine deutsche Staatsbürgerschaft")
_f("bagw2025", 1, "bagw_homeless_year__eu", _D, 2024, 55000, note=f"{_b25}: EU-Staatsbürgerschaft")
_f("bagw2025", 1, "bagw_homeless_year__non_eu_or_stateless", _D, 2024, 765000, needle="765.000 Personen mit einer anderen", note=f"{_b25}: andere Staatsbürgerschaft oder staatenlos")
_f("bagw2025", 1, "bagw_homeless_year__german", _D, 2024, 209000, note=f"{_b25}: deutsche Staatsangehörigkeit")
_f("bagw2025", 1, "bagw_homeless_year__single_person_hh", _D, 2024, 412500, note=f"{_b25}: in Einpersonenhaushalten")
_f("bagw2025", 1, "bagw_homeless_year__multi_person_hh", _D, 2024, 616500, note=f"{_b25}: in Mehrpersonenhaushalten")
_b23 = "BAG W Pressemappe 07.11.2023, S. 1"
_f("bagw2023", 1, "bagw_homeless_year", _D, 2022, 607000, note=f"{_b23}: Jahresgesamtzahl 2022")
_f("bagw2023", 1, "bagw_homeless_year", _D, 2021, 383000, note=f"{_b23}: Jahresgesamtzahl 2021")
_f("bagw2023", 1, "bagw_unsheltered_year", _D, 2022, 50000, note=f"{_b23}: ca., ohne Unterkunft, 2022")
_f("bagw2023", 1, "bagw_homeless_0630", _D, 2022, 447000, note=f"{_b23}: Stichtag 30.06.2022")
_f("bagw2023", 1, "bagw_homeless_0630", _D, 2021, 268000, note=f"{_b23}: Stichtag 30.06.2021")
_b21 = "BAG W Pressemitteilung 21.12.2021 (older method: Hilfesystem + anerkannte Geflüchtete)"
for y, (yr_total, st) in {2018: (678000, 543000), 2019: (584000, 451000), 2020: (417000, 306000)}.items():
    _f("bagw2021", 5, "bagw_homeless_year", _D, y, yr_total, note=f"{_b21}, Tabelle S. 5: Alle Wohnungslosen, Jahresgesamtzahl {y}")
    _f("bagw2021", 5, "bagw_homeless_0630", _D, y, st, note=f"{_b21}, Tabelle S. 5: Alle Wohnungslosen, Stichtag 30.06.{y}")
_f("bagw2021", 3, "bagw_unsheltered_year", _D, 2020, 45000, note=f"{_b21}, S. 3: ca. ohne jede Unterkunft auf der Straße im Laufe eines Jahres")



# NRW Wohnungsnotfallberichterstattung 2024 (Stichtag 30. Juni; counts reported by Kommunen and freie Träger).
# Different reference date and concept from Destatis 22971 (31 Jan, housed only) -> separate metric names.
_NW = ("land", "05")
_n2 = "NRW WNB 2024, Tab. 2 (S. 9), Stichtag 30.06."
for _y, (_k, _ft, _tot) in {2015: (10282, 10714, 20996), 2016: (11637, 13408, 25045), 2017: (19459, 12827, 32286),
                            2018: (30736, 13698, 44434), 2019: (32623, 13987, 46610), 2020: (36082, 13905, 49987),
                            2021: (34405, 13880, 48285), 2022: (63555, 14795, 78350), 2023: (93210, 15375, 108590),
                            2024: (106330, 15840, 122170)}.items():
    _sp = lambda v: f"{v:,}".replace(",", " ")
    _f("nrw_wnb2024", 9, "nrw_homeless_0630", _NW, _y, _tot, 0, needle=f"{_y} {_sp(_k)} {_sp(_ft)} {_sp(_tot)}",
       note=f"{_n2}: wohnungslose Personen insgesamt")
    _f("nrw_wnb2024", 9, "nrw_homeless_0630__kommunal", _NW, _y, _k, 0, needle=f"{_y} {_sp(_k)} {_sp(_ft)} {_sp(_tot)}",
       note=f"{_n2}: von Kommunen gemeldet (kommunal und ordnungsrechtlich untergebracht)")
    _f("nrw_wnb2024", 9, "nrw_homeless_0630__freie_traeger", _NW, _y, _ft, 0, needle=f"{_y} {_sp(_k)} {_sp(_ft)} {_sp(_tot)}",
       note=f"{_n2}: von freien Trägern der Wohnungslosenhilfe gemeldet")
_n3 = "NRW WNB 2024, Tab. 3 (S. 10), Stichtag 30.06."
for _m, _lbl, _v24, _v23 in [("informal", "informell untergekommen", 7890, 7810),
                             ("unsheltered", "ohne Unterkunft", 1795, 1565),
                             ("freie_traeger_housed", "von freien Trägern untergebracht", 5080, 4840),
                             ("other_institution", "sonstige institutionelle Unterbringung", 420, 370),
                             ("type_unknown", "ohne Angaben zur Unterbringung", 660, 790)]:
    _nd = f"{_v24:,}".replace(",", " ")
    _nd2 = f"{_v23:,}".replace(",", " ")
    _f("nrw_wnb2024", 10, f"nrw_homeless_0630__{_m}", _NW, 2024, _v24, 0, needle=_nd, note=f"{_n3}: {_lbl}")
    _f("nrw_wnb2024", 10, f"nrw_homeless_0630__{_m}", _NW, 2023, _v23, 0, needle=_nd2, note=f"{_n3}: {_lbl} (Vorjahr)")

# Berlin, 1. Nacht der Solidarität, night 29./30.01.2020: a street + facility count, not an estimate.
_BE = ("land", "11")
_nb = "Drs. 19/10884 Antwort zu 2. (S. 3): 1. Nacht der Solidarität 29./30.01.2020"
_f("be_nds2020", 3, "be_nds_rough_sleepers_counted", _BE, 2020, 1976, 0, needle="insgesamt 1.976 obdachlose Menschen gezählt",
   note=f"{_nb}: obdachlose Menschen gezählt, insgesamt")
for _m, _v, _nd, _lbl in [("street", 807, "807 Menschen bei der Straßenzählung", "Straßenzählung im öffentlichen Raum"),
                          ("hospital_er", 15, "15 obdachlose Menschen in Rettungsstellen", "Rettungsstellen der Krankenhäuser"),
                          ("transit", 158, "158 Obdachlose im ÖPNV", "ÖPNV (112 S-Bahn, 46 BVG)"),
                          ("police_custody", 12, "12 in Polizeigewahrsam", "Polizeigewahrsam"),
                          ("kaeltehilfe", 942, "942 in Einrichtungen der Kältehilfe", "Einrichtungen der Kältehilfe"),
                          ("warmeraum", 42, "42 im Warte- und Wärmeraum", "Warte- und Wärmeraum Gitschiner Straße"),
                          ("street_inside_ring", 540, "540 inner", "Straße, innerhalb des S-Bahnrings"),
                          ("street_outside_ring", 267, "267 außerhalb", "Straße, außerhalb des S-Bahnrings")]:
    _f("be_nds2020", 3, f"be_nds_rough_sleepers_counted__{_m}", _BE, 2020, _v, 0, needle=_nd, note=f"{_nb}: {_lbl}")


# Hamburg 2018 (GOE report p. 14 = printed p. 12, Tab. 2 + Tab. 3). Street count = people met and identified in the
# week 19.-25.03.2018 (a minimum, not an estimate); housed = Stichtag 18.02.2018 (Wohnunterkünfte) / 31.03. (§ 67).
_HH = ("land", "02")
_nh = "GOE Hamburg 2018, Tab. 3 (PDF S. 14)"
for _y, (_st, _hm, _hf, _s67, _hs, _tot) in {2018: (1910, 2902, 1562, 202, 4666, 6576),
                                             2009: (1029, 1442, 284, 211, 2924, 3953)}.items():
    _f("hh_goe2018", 14, "hh_rough_sleepers_counted", _HH, _y, _st, 0, note=f"{_nh}: auf der Straße lebende Obdachlose, "
       f"Mindestzahl ({'3. Märzwoche 2018' if _y == 2018 else 'letzte Märzwoche 2009'})")
    _f("hh_goe2018", 14, "hh_housed_homeless_single", _HH, _y, _hs, 0, note=f"{_nh}: untergebrachte Personen gesamt "
       "(alleinstehende Wohnungslose in Wohnunterkünften/Übernachtungsstätten/Wohnprojekten + stationär § 67 SGB XII; "
       "ohne Geflüchtete und Familien in öffentlich-rechtlicher Unterbringung)")
    _f("hh_goe2018", 14, "hh_housed_homeless_single__male", _HH, _y, _hm, 0, needle=f"{_hm:,} Männer".replace(",", "."), note=f"{_nh}: davon Männer in Wohnunterkünften")
    _f("hh_goe2018", 14, "hh_housed_homeless_single__female", _HH, _y, _hf, 0, needle=f"{_hf:,} Frauen".replace(",", "."), note=f"{_nh}: davon Frauen in Wohnunterkünften")
    _f("hh_goe2018", 14, "hh_housed_homeless_single__s67_stationary", _HH, _y, _s67, 0, needle=f"{_s67}", note=f"{_nh}: davon stationär nach §§ 67 ff. SGB XII")
    _f("hh_goe2018", 14, "hh_homeless_total", _HH, _y, _tot, 0, note=f"{_nh}: Personen insgesamt (untergebracht + Straße)")

# München, Sozialreferat Produktcontrolling 31.12.2025, PDF p. 12. The headline total includes a street ESTIMATE
# ("Straßenschätzung") -> is_est=1; the Sofortunterbringung subtotal is a register count -> is_est=0.
_MUC = ("kreis", "09162")
_nm = "LHM Sozialreferat, Produktcontrolling Stand 31.12.2025 (PDF S. 12), Stichtag 31.12."
_f("muc_pc2025", 12, "muc_acute_homeless", _MUC, 2024, 11271, 1, note=f"{_nm}: akut Wohnungslose im Sofortunterbringungssystem inkl. "
   "Statuswechsler, Fehlbeleger, priv. Notquartiere, Straßenschätzung und Geflüchtete aus der Ukraine (contains an estimate)")
_f("muc_pc2025", 12, "muc_acute_homeless", _MUC, 2025, 11136, 1, note=f"{_nm}: dito, 31.12.2025")
for _y, _v in zip(range(2018, 2022), (8759, 8593, 8393, 7873)):
    _f("muc_pc2025", 12, "muc_acute_homeless", _MUC, _y, _v, 1, note=f"{_nm}: dito, chart 'Entwicklung der letzten Jahre'")
for _y, _v in zip(range(2018, 2026), (5525, 5278, 5248, 4955, 4892, 4947, 4978, 4802)):
    _f("muc_pc2025", 12, "muc_acute_homeless__sofortunterbringung", _MUC, _y, _v, 0,
       note=f"{_nm}: davon in Beherbergungsbetrieben, Notquartieren, Clearinghäusern, Flexiheimen, Wohnprojekten "
            f"({'table' if _y >= 2024 else 'chart'})")

# Baden-Württemberg: GISS 2015 study (Stichtag 01.10.2014), summary PDF p. 11.
_BW = ("land", "08")
_ng = "GISS BW 2015, Zusammenfassung (PDF S. 11), Stichtag 01.10.2014"
_f("bw_giss2015", 11, "bw_homeless_1001", _BW, 2014, 22789, 1, note=f"{_ng}: ordnungsrechtlich untergebrachte + bei Trägern nach "
   "§§ 67 ff. SGB XII anhängige Wohnungslose (includes 3.619 extrapolated persons -> estimate)")
_f("bw_giss2015", 11, "bw_homeless_1001__ordnungsrecht", _BW, 2014, 14320, 1, note=f"{_ng}: ordnungsrechtlich untergebracht, "
   "10.701 registriert + 3.619 hochgerechnet")
_f("bw_giss2015", 11, "bw_homeless_1001__ordnungsrecht_registered", _BW, 2014, 10701, 0, note=f"{_ng}: in 543 Orten registriert")
_f("bw_giss2015", 11, "bw_homeless_1001__s67_homeless", _BW, 2014, 8469, 0, note=f"{_ng}: wohnungslose Personen in 327 Angeboten "
   "nach §§ 67 ff. SGB XII (von 12.788 erfassten)")
_f("bw_giss2015", 11, "bw_homeless_year__ordnungsrecht", _BW, 2014, 22500, 1, needle="rd. 22.500",
   note=f"{_ng}: hochgerechnete Gesamtzahl ordnungsrechtlich Untergebrachter im Gesamtjahr 2014")
# Liga Stichtagserhebung (persons in §§ 67 ff. SGB XII help, NOT all homeless), Abb. 1 PDF p. 7.
_nl = "Liga BW Stichtagserhebung 2024, Abb. 1 (PDF S. 7), Stichtag jeweils September"
for _y, _t, _w in zip(range(2015, 2025), (11537, 11949, 11788, 12147, 12270, 11421, 11619, 12413, 12688, 13394),
                      (3133, 3230, 3268, 3316, 3240, 2984, 3168, 3606, 3650, 3861)):
    _f("bw_liga2024", 7, "bw_liga_s67_clients", _BW, _y, _t, 0, note=f"{_nl}: Hilfesuchende in Einrichtungen der Wohnungslosen- "
       "und Straffälligenhilfe (§§ 67 ff. SGB XII), participating providers only")
    _f("bw_liga2024", 7, "bw_liga_s67_clients__female", _BW, _y, _w, 0, note=f"{_nl}: davon Frauen")
_f("bw_liga2024", 3, "bw_liga_s67_clients__male", _BW, 2024, 9515, 0, note="Liga BW 2024, Zusammenfassung (PDF S. 3): Männer")
_f("bw_liga2024", 3, "bw_liga_s67_clients__age_lt25", _BW, 2024, 1043, 0, note="Liga BW 2024, Zusammenfassung (PDF S. 3): unter 25 Jahre")

# NRW annex tables 11-13: every Kreis / kreisfreie Stadt, Stichtag 30.06.2015-2024. Parsed from the archived PDF.
NRW_TABLES = {"Tab. 11:": ("nrw_homeless_0630", "insgesamt", (26, 27)),
              "Tab. 12:": ("nrw_homeless_0630__kommunal", "kommunal und ordnungsrechtlich untergebracht", (28, 29)),
              "Tab. 13:": ("nrw_homeless_0630__freie_traeger", "von freien Trägern gemeldet", (30, 31))}
NRW_YEARS = list(range(2024, 2014, -1))  # column order as printed
# AGS5 from the Destatis 22971-0080 region classification (labels matched 53/53 on 2026-11-20).
NRW_AGS = {"Stadt Düsseldorf": "05111", "Stadt Duisburg": "05112", "Stadt Essen": "05113", "Stadt Krefeld": "05114",
           "Stadt Mönchengladbach": "05116", "Stadt Mülheim an der Ruhr": "05117", "Stadt Oberhausen": "05119",
           "Stadt Remscheid": "05120", "Stadt Solingen": "05122", "Stadt Wuppertal": "05124", "Kreis Kleve": "05154",
           "Kreis Mettmann": "05158", "Rhein-Kreis Neuss": "05162", "Kreis Viersen": "05166", "Kreis Wesel": "05170",
           "Stadt Bonn": "05314", "Stadt Köln": "05315", "Stadt Leverkusen": "05316", "Städteregion Aachen": "05334",
           "Kreis Düren": "05358", "Rhein-Erft-Kreis": "05362", "Kreis Euskirchen": "05366", "Kreis Heinsberg": "05370",
           "Oberbergischer Kreis": "05374", "Rheinisch-Bergischer Kreis": "05378", "Rhein-Sieg-Kreis": "05382",
           "Stadt Bottrop": "05512", "Stadt Gelsenkirchen": "05513", "Stadt Münster": "05515", "Kreis Borken": "05554",
           "Kreis Coesfeld": "05558", "Kreis Recklinghausen": "05562", "Kreis Steinfurt": "05566",
           "Kreis Warendorf": "05570", "Stadt Bielefeld": "05711", "Kreis Gütersloh": "05754", "Kreis Herford": "05758",
           "Kreis Höxter": "05762", "Kreis Lippe": "05766", "Kreis Minden-Lübbecke": "05770",
           "Kreis Paderborn": "05774", "Stadt Bochum": "05911", "Stadt Dortmund": "05913", "Stadt Hagen": "05914",
           "Stadt Hamm": "05915", "Stadt Herne": "05916", "Ennepe-Ruhr-Kreis": "05954", "Hochsauerlandkreis": "05958",
           "Märkischer Kreis": "05962", "Kreis Olpe": "05966", "Kreis Siegen-Wittgenstein": "05970",
           "Kreis Soest": "05974", "Kreis Unna": "05978"}
NRW_REGBEZ = {"Reg.-Bez. Düsseldorf": "051", "Reg.-Bez. Köln": "053", "Reg.-Bez. Münster": "055",
              "Reg.-Bez. Detmold": "057", "Reg.-Bez. Arnsberg": "059"}
_PAGES: dict = {}
_SIDS: dict = {}


# ---- Frankfurt am Main: Kommunale Wohnraumversorgung, Jahresbericht 2024 (manual archive) ----
# The report is the social-housing register of the Amt für Wohnungswesen. Its figures count REGISTERED HOUSEHOLDS
# (unit 'households'), not persons and not all homeless people in the city; never into pit.
FFM_URL = ("https://frankfurt.de/-/media/frankfurtde/service-und-rathaus/verwaltung/aemter-und-institutionen/"
           "amt-fuer-wohnungswesen/pdf/64_3/64_3_2024_bericht-kommunale-wohnraumversorgung.pdf")
DOCS["ffm_wohnraum2024"] = (FFM_URL, "Kommunale Wohnraumversorgung – Jahresbericht 2024",
                            "Stadt Frankfurt am Main, Amt für Wohnungswesen",
                            "Rechte vorbehalten: amtliche Veröffentlichung der Stadt Frankfurt am Main (kommunaler Jahresbericht); "
                            "nur Zahlen mit Fundstelle und kurzem Zitat gespeichert (Lead, 2026-11-21: LIC_LAND "
                            "nennt Landesbehörde/Landesparlament und passt nicht auf eine Kommune)")
DOC_LOCAL = {"ffm_wohnraum2024": ("ffm_wohnraum2024.pdf", "manual archive via browser, 2026-11-21 (Lead); sha256 "
                                  "7251a252…cd264; frankfurt.de returns 403 to the project UA")}
_FFM = ("kreis", "06412")
_n13 = "Frankfurt, Jahresbericht 2024, 2.1 Anzahl an Wohnungssuchenden (S. 13), Stichtag 31.12.2024"
_f("ffm_wohnraum2024", 13, "ffm_register_households", _FFM, 2024, 7513, 0, needle="31.12.2024 7.513 19.845",
   note=f"{_n13}: registrierte sozialwohnungsberechtigte wohnungssuchende Haushalte", unit="households")
_f("ffm_wohnraum2024", 13, "ffm_register_persons", _FFM, 2024, 19845, 0, needle="31.12.2024 7.513 19.845",
   note=f"{_n13}: Personen in diesen Haushalten")
_n16 = ("Frankfurt, Jahresbericht 2024, 2.6.1 Einordnung in Dringlichkeitsstufe 1 nach aktueller Wohnsituation "
        "(S. 16; registrierte Haushalte, Dringlichkeit jeweils zum 31.12.)")
for _sz, _v in [("1", 138), ("2", 2)]:
    _f("ffm_wohnraum2024", 16, f"ffm_register_u1_obdachlos__hh_size_{_sz}", _FFM, 2024, _v, 0,
       needle="Obdachlose Personen 138 2 - - -", note=f"{_n16}: 'Obdachlose Personen', Haushaltsgröße {_sz}",
       unit="households")
for _sz, _v in [("1", 1435), ("2", 232), ("3", 157), ("4", 169), ("5plus", 390)]:
    _f("ffm_wohnraum2024", 16, f"ffm_register_u1_untergebracht__hh_size_{_sz}", _FFM, 2024, _v, 0,
       needle="Untergebrachte Personen 1.435 232 157 169 390",
       note=f"{_n16}: 'Untergebrachte Personen', Haushaltsgröße {_sz.replace('plus', '+')}", unit="households")


def ingest_nrw_kreise(conn, counts) -> list[str]:
    """Parse NRW WNB 2024 annex tables 11-13 row by row; '.' = keine Angabe -> no row."""
    import re
    problems = []
    pages = _PAGES.get("nrw_wnb2024")
    if not pages:
        return ["nrw_wnb2024:not-loaded"]
    cell = re.compile(r"^(\d{1,3}(?: \d{3})*|\.)$")
    for tab, (metric, label, pnums) in NRW_TABLES.items():
        seen = set()
        for pn in pnums:
            for line in pages[pn - 1].split("\n"):
                parts = [x.strip() for x in re.split(r"\s{2,}", line.strip()) if x.strip()]
                if not parts or parts[0] not in NRW_AGS and parts[0] not in NRW_REGBEZ and parts[0] != "Nordrhein-Westfalen":
                    continue
                name, vals = parts[0], parts[1:]
                if len(vals) != 10 or not all(cell.match(v) for v in vals):
                    problems.append(f"nrw:{tab}:p{pn}:{name}:unparsed({len(vals)} cells)")
                    counts["est_skipped"] += 1
                    continue
                if name in NRW_AGS:
                    etype, eid = "kreis", NRW_AGS[name]
                elif name in NRW_REGBEZ:
                    etype, eid = "regbez", NRW_REGBEZ[name]
                else:
                    etype, eid = "land", "05"
                seen.add(name)
                for year, v in zip(NRW_YEARS, vals):
                    if v == ".":
                        continue
                    upsert(conn, "metric",
                           {"entity_type": etype, "entity_id": eid, "metric": metric, "value": float(v.replace(" ", "")),
                            "einheit": "persons", "year": year, "is_est": 0,
                            "anmerkung": f"NRW WNB 2024, {tab.rstrip(':')} ({label}), {name}, Stichtag 30.06.{year}. "
                                    f"PDF page {pn} of {DOCS['nrw_wnb2024'][0]}",
                            "source_id": _SIDS["nrw_wnb2024"]},
                           keys=["entity_type", "entity_id", "metric", "year"])
                    counts["land_metric"] += 1
        missing = (set(NRW_AGS) | set(NRW_REGBEZ)) - seen
        if missing:
            problems.append(f"nrw:{tab}:missing:{sorted(missing)}")
    return problems

def _pdf_pages(raw: bytes) -> list[str]:
    import subprocess, tempfile
    with tempfile.NamedTemporaryFile(suffix=".pdf") as tf:
        tf.write(raw)
        tf.flush()
        out = subprocess.run(["pdftotext", "-layout", tf.name, "-"], capture_output=True, check=True).stdout
    return out.decode("utf-8", "replace").split("\f")  # layout kept; needle checks collapse whitespace


def _de_num(v) -> str:
    return f"{int(v):,}".replace(",", ".")


def ingest_estimates(conn, counts) -> list[str]:
    pages, sids, problems = {}, {}, []
    for key, (url, title, pub, lic) in DOCS.items():
        if key in DOC_LOCAL:  # archived by hand by the Lead; never fetched by us
            fname, how = DOC_LOCAL[key]
            raw = _load(url, fname)
            if raw is None:
                problems.append(f"{key}:manual-archive-missing({fname})")
                continue
            pages[key] = _PAGES[key] = _pdf_pages(raw)
            sids[key] = _SIDS[key] = _register_local(conn, url, fname, title, pub, lic, how)
            continue
        try:
            raw = fetch(url, domain=DOMAIN, force=_FORCE[0])
        except Exception as e:  # noqa: one missing document must not block the others
            problems.append(f"{key}:fetch-failed({e!r:.80})")
            continue
        if not raw.startswith(b"%PDF"):
            problems.append(f"{key}:not-a-pdf")
            continue
        save_raw(DOMAIN, f"{key}.pdf", raw)  # human-readable copy next to the sha1 cache file
        pages[key] = _PAGES[key] = _pdf_pages(raw)
        sids[key] = _SIDS[key] = source_id_for(conn, url, DOMAIN, title=title, publisher=pub, license=lic)
    for doc, page, metric, etype, eid, year, value, is_est, needle, note, unit in FIGURES:
        if doc not in pages:
            continue
        needle = needle or _de_num(value)
        text = pages[doc][page - 1] if page - 1 < len(pages[doc]) else ""
        if " ".join(needle.split()) not in " ".join(text.split()):
            problems.append(f"{doc}:p{page}:{metric}:{eid}:{year}:'{needle}'-not-found")
            counts["est_skipped"] += 1
            continue
        upsert(conn, "metric",
               {"entity_type": etype, "entity_id": eid, "metric": metric, "value": float(value),
                "einheit": unit, "year": year, "is_est": is_est,
                "anmerkung": f"{note}. PDF page {page} of {DOCS[doc][0]}", "quote": " ".join(needle.split()),
                "locator": f"PDF p. {page}", "source_id": sids[doc]},
               keys=["entity_type", "entity_id", "metric", "year"])
        counts["est_metric"] += 1
    return problems



# --- Part 4: law rows (law) and court decisions (doc, kind='court') ---------------------------------
# Every row is written only if ALL its needles (verbatim phrases of the statute / decision / plan) are found
# in the fetched and archived source text. Summaries paraphrase only what those phrases say.
# Länder whose consolidated statutes exist only on juris JS portals (with a TDM reservation meta tag) are NOT
# scraped; see research/counts_law.md "Part 4 — not ingested".
GII = "https://www.gesetze-im-internet.de"
LIC_STATUTE = "Amtliches Werk, gemeinfrei nach § 5 Abs. 1 UrhG"
LAW = [
    # (key, url, jurisdiction, topic, citation, title, summary, status, year, publisher, needles)
    ("sgb12_67", f"{GII}/sgb_12/__67.html", "DE", "sgb_xii_67", "§ 67 SGB XII", "SGB XII § 67 Leistungsberechtigte",
     "Persons whose particular living conditions are combined with social difficulties receive benefits to overcome "
     "these difficulties (Hilfe zur Überwindung besonderer sozialer Schwierigkeiten) when they cannot do so on their "
     "own.", "enacted", 2003, "Bundesministerium der Justiz",
     ["§ 67 Leistungsberechtigte", "Personen, bei denen besondere Lebensverhältnisse mit sozialen Schwierigkeiten verbunden sind"]),
    ("sgb12_68", f"{GII}/sgb_12/__68.html", "DE", "sgb_xii_67", "§ 68 SGB XII", "SGB XII § 68 Umfang der Leistungen",
     "The benefits comprise all measures necessary to avert, remove or mitigate the difficulties, in particular counselling "
     "and personal support, help with training and employment, and measures to keep and obtain housing.", "enacted", 2003,
     "Bundesministerium der Justiz", ["§ 68 Umfang der Leistungen", "Maßnahmen bei der Erhaltung und Beschaffung einer Wohnung"]),
    ("sgb12_69", f"{GII}/sgb_12/__69.html", "DE", "sgb_xii_67", "§ 69 SGB XII", "SGB XII § 69 Verordnungsermächtigung",
     "Authorises the Federal Ministry of Labour and Social Affairs, with Bundesrat consent, to delimit the § 67 group "
     "and the type and scope of § 68 measures by ordinance.", "enacted", 2003, "Bundesministerium der Justiz",
     ["§ 69 Verordnungsermächtigung", "Abgrenzung des Personenkreises nach § 67"]),
    ("dvo_67", f"{GII}/bshg_72dv_2001/BJNR017900001.html", "DE", "sgb_xii_67",
     "DVO zu §§ 67 ff. SGB XII (BSHG§72DV 2001)", "Verordnung zur Durchführung der Hilfe zur Überwindung besonderer sozialer Schwierigkeiten",
     "Defines 'besondere soziale Schwierigkeiten' (§ 1) and the measures, including counselling and personal support and "
     "measures to keep and obtain a dwelling (§ 4).", "enacted", 2001, "Bundesministerium der Justiz",
     ["§ 1 Persönliche Voraussetzungen", "§ 4 Erhaltung und Beschaffung einer Wohnung"]),
    ("sgb2_22", f"{GII}/sgb_2/__22.html", "DE", "other", "§ 22 SGB II", "SGB II § 22 Bedarfe für Unterkunft und Heizung (KdU)",
     "Housing and heating costs are recognised at actual cost where appropriate (one-year Karenzzeit); rent arrears may "
     "be taken over and should be when otherwise homelessness threatens (Abs. 8).", "enacted", 2026, "Bundesministerium der Justiz",
     ["§ 22 Bedarfe für Unterkunft und Heizung", "Bedarfe für Unterkunft und Heizung werden in Höhe der tatsächlichen Aufwendungen anerkannt",
      "sonst Wohnungslosigkeit einzutreten droht"]),
    ("woberichtsg", f"{GII}/woberichtsg/BJNR043710020.html", "DE", "other", "WoBerichtsG",
     "Wohnungslosenberichterstattungsgesetz",
     "Creates the federal statistic of housed homeless persons run by Destatis (annual Stichtag 31 January, first 2022) "
     "and obliges the federal government to publish a report every two years on homeless people living temporarily "
     "with others or without any shelter.", "enacted", 2020, "Bundesministerium der Justiz",
     ["als Bundesstatistik durchgeführt", "zum Stichtag 31. Januar, erstmals für das Jahr 2022",
      "Die Bundesregierung veröffentlicht alle zwei Jahre einen Bericht"]),
    # Land general clauses = legal basis of ordnungsrechtliche Unterbringung of involuntarily homeless persons
    ("by_lstvg7", "https://www.gesetze-bayern.de/Content/Document/BayLStVG-7", "BY", "ordnungsrecht", "Art. 7 Abs. 2 Nr. 3 LStVG",
     "Bayern: Landesstraf- und Verordnungsgesetz Art. 7 Befugnisse der Sicherheitsbehörden",
     "Where no special authorisation exists, security authorities may issue orders for the individual case to avert "
     "dangers to life, health or freedom of persons (general clause).", "enacted", None, "Bayerische Staatskanzlei (BAYERN.RECHT)",
     ["Art. 7 Befugnisse der Sicherheitsbehörden", "Gefahren abzuwehren oder Störungen zu beseitigen, die Leben, Gesundheit oder die Freiheit von Menschen"]),
    ("bb_obg", "https://bravors.brandenburg.de/gesetze/obg", "BB", "ordnungsrecht", "§ 13 OBG Bbg",
     "Brandenburg: Ordnungsbehördengesetz § 13 Voraussetzungen des Eingreifens",
     "General clause: Ordnungsbehörden may take the necessary measures to avert a concrete danger to public safety or order.",
     "enacted", None, "Land Brandenburg (BRAVORS)",
     ["§ 13 Voraussetzungen des Eingreifens (1) Die Ordnungsbehörden können die notwendigen Maßnahmen treffen, um eine im einzelnen Falle bestehende Gefahr"]),
    ("nw_obg", "https://recht.nrw.de/system/files/pdf/state-law-and-regulations/2026/06/30/765c5e/01-07-2026-obg-ordnungsbehoerdengesetz.pdf",
     "NW", "ordnungsrecht", "§ 14 Abs. 1 OBG NRW", "Nordrhein-Westfalen: Ordnungsbehördengesetz § 14 Voraussetzungen des Eingreifens",
     "General clause (version valid from 01.07.2026); NRW courts derive from it a claim of involuntarily homeless "
     "persons to humane accommodation (see doc rows OVG NRW 9 B 187/20, VG Köln 22 L 1420/24, VG Arnsberg 6 L 898/19).",
     "enacted", 2026, "Land Nordrhein-Westfalen (recht.nrw.de)",
     ["Die Ordnungsbehörden können die notwendigen Maßnahmen treffen, um eine im einzelnen Falle bestehende Gefahr für die öffentliche Sicherheit oder Ordnung (Gefahr) abzuwehren",
      "Gültig ab: 01.07.2026"]),
    ("sn_pbg", "https://www.revosax.sachsen.de/vorschrift_gesamt/18194/47458.pdf", "SN", "ordnungsrecht", "§ 12 Abs. 1 SächsPBG",
     "Sachsen: Polizeibehördengesetz § 12 Allgemeine Befugnisse",
     "General clause for the Polizeibehörden (incl. the Gemeinden as Ortspolizeibehörden): necessary measures to avert a "
     "danger to public safety or order.", "enacted", None, "Freistaat Sachsen (REVOSax)",
     ["Die Polizeibehörden können die notwendigen Maßnahmen treffen, um eine Gefahr für die öffentliche Sicherheit oder Ordnung abzuwehren",
      "die Gemeinden als Ortspolizeibehörden"]),
    ("hb_polg", "https://www.transparenz.bremen.de/sixcms/detail.php?gsid=bremen203.c.338897.de&template=00_html_to_pdf_d",
     "HB", "ordnungsrecht", "§ 10 Abs. 1 BremPolG", "Bremen: Polizeigesetz § 10 Allgemeine Befugnisse",
     "General clause (version in force from 20.06.2026): the police may take the necessary "
     "measures to avert a concrete danger to public safety.", "enacted", 2026, "Freie Hansestadt Bremen (Transparenzportal)",
     ["Die Polizei darf die notwendigen Maßnahmen treffen, um eine im einzelnen Fall bestehende Gefahr für die öffentliche Sicherheit abzuwehren",
      "Inkrafttreten: 20.06.2026"]),
    ("bw_polg", "https://www.landtag-bw.de/resource/blob/72948/94250fb4c10ed7593c4c0a5f9928631c/GBl202035.pdf", "BW",
     "ordnungsrecht", "§ 3 PolG BW (GBl. 2020 Nr. 35)", "Baden-Württemberg: Polizeigesetz vom 6. Oktober 2020, § 3 Polizeiliche Maßnahmen",
     "General clause as promulgated in GBl. 2020 Nr. 35: the police take the measures that appear necessary at their "
     "dutiful discretion. Later amendments not checked against an archived text.",
     "enacted", 2020, "Landtag von Baden-Württemberg (Gesetzblatt)",
     ["diejenigen Maßnahmen zu treffen, die ihr nach pflichtmäßigem Ermessen erforderlich erscheinen", "Polizeiliche Maßnahmen"]),
    ("ni_npog", "https://www.niedersachsen.de/download/66067", "NI", "ordnungsrecht", "§ 11 NPOG",
     "Niedersachsen: Niedersächsisches Polizei- und Ordnungsbehördengesetz (NPOG) § 11 Allgemeine Befugnisse",
     "General clause: administrative authorities and police may take the necessary measures to avert a danger. Wording "
     "verified in the Neubekanntmachung of the Nds. SOG (Nds. GVBl. 2005 S. 9); the act was renamed NPOG by the law in "
     "Nds. GVBl. 2019 Nr. 8 (Art. 1 Nr. 1, new heading). Amendments after May 2019 not verified against an archived text.",
     "enacted", 2019, "Land Niedersachsen (Nds. GVBl.)",
     ["Die Verwaltungsbehörden und die Polizei können die notwendigen Maßnahmen treffen, um eine Gefahr abzuwehren, soweit"]),
    ("he_hsog", "https://starweb.hessen.de/cache/GVBL/2005/00002.pdf", "HE", "ordnungsrecht", "§ 11 HSOG",
     "Hessen: Hessisches Gesetz über die öffentliche Sicherheit und Ordnung § 11 Allgemeine Befugnisse",
     "General clause as in the Neufassung of 14 January 2005 (GVBl. I 2005 Nr. 2 S. 14): Gefahrenabwehr- and police "
     "authorities may take the necessary measures to avert a danger to public safety or order in the individual case. "
     "Later amendments not verified against an archived text.", "enacted", 2005, "Land Hessen (Gesetz- und Verordnungsblatt, starweb.hessen.de)",
     ["§ 11 Allgemeine Befugnisse", "die erforderlichen Maßnahmen treffen, um eine im einzelnen Falle bestehende Gefahr für die öffentliche Sicherheit oder Ordnung (Gefahr) abzuwehren"]),
    ("mv_sog", "https://land-mv.de/sites/default/files/documents/Sicherheits-Ordnungsgesetz-MV.pdf", "MV", "ordnungsrecht",
     "§ 13 SOG M-V", "Mecklenburg-Vorpommern: Sicherheits- und Ordnungsgesetz § 13 Allgemeine Befugnisse",
     "General clause as enacted by the law of 27 April 2020 (GVOBl. M-V S. 334), in force 5 June 2020, in the print of "
     "the Ministerium für Inneres und Europa: Ordnungsbehörden and police take the necessary measures to avert dangers "
     "to public safety or order. Later amendments not verified.", "enacted", 2020,
     "Land Mecklenburg-Vorpommern, Ministerium für Inneres und Europa (Regierungsportal land-mv.de)",
     ["§ 13 Allgemeine Befugnisse Die Ordnungsbehörden und die Polizei haben im Rahmen der geltenden Gesetze die nach pflichtgemäßem Ermessen notwendigen"]),
    ("be_asog", "https://www.berlin.de/sen/justiz/service/gesetze-und-verordnungen/2006/mdb-senatsverwaltungen-justiz-gvbl2006-seiten_929___956_heft_nr._34_vom_14.10.2006.pdf?ts=1612427805",
     "BE", "ordnungsrecht", "§ 17 Abs. 1 ASOG Bln", "Berlin: Allgemeines Sicherheits- und Ordnungsgesetz § 17 Allgemeine Befugnisse",
     "General clause as in the Neubekanntmachung of 11 October 2006 (GVBl. 2006 Nr. 34 S. 930): Ordnungsbehörden and "
     "police may take the necessary measures to avert a danger to public safety or order in the individual case, "
     "unless §§ 18-51 regulate their powers specifically. Later amendments not verified.", "enacted", 2006,
     "Land Berlin, Senatsverwaltung für Justiz (Gesetz- und Verordnungsblatt für Berlin)",
     ["Die Ordnungsbehörden und die Polizei können die notwendigen Maßnahmen treffen, um eine im einzelnen Falle bestehende Gefahr für die öffentliche Sicherheit oder Ordnung (Gefahr) abzuwehren, soweit nicht die §§ 18 bis 51 ihre Befugnisse besonders regeln"]),
    ("sh_lvwg", "https://verkuendungsportal.schleswig-holstein.de/mm/gvobl_jahrgang_1992/GVOBl_1992.pdf", "SH",
     "ordnungsrecht", "§ 174 LVwG SH", "Schleswig-Holstein: Landesverwaltungsgesetz § 174 Allgemeiner Grundsatz",
     "General clause as in the Neufassung of 2 June 1992 (GVOBl. Schl.-H. 1992 Nr. 12 S. 243): Ordnungsbehörden and "
     "police take the necessary measures to avert dangers to public safety. Later amendments not verified.",
     "enacted", 1992, "Land Schleswig-Holstein, Innenminister (Gesetz- und Verordnungsblatt, Verkündungsportal)",
     ["§ 174 Allgemeiner Grundsatz Die Ordnungsbehörden und die Polizei haben im Rahmen der geltenden Gesetze die nach pflichtgemäßem Ermessen notwendigen Maßnahmen zu treffen, um von der Allgemeinheit oder der einzelnen Person Gefahren abzuwehren, durch die die öffentliche Sicherheit bedroht wird",
      "Bekanntmachung der Neufassung des Landesverwaltungsgesetzes"]),
    # action plans
    ("nap2024", "https://www.bmwsb.bund.de/SharedDocs/downloads/DE/publikationen/wohnen/NAP.pdf?__blob=publicationFile",
     "DE", "aktionsplan", "NAP 2024", "Gemeinsam für ein Zuhause – Nationaler Aktionsplan gegen Wohnungslosigkeit 2024",
     "Federal action plan (cabinet, April 2024): all actors work so that every homeless person or person threatened with "
     "homelessness receives a suitable housing offer by 2030; implemented through a Nationales Forum gegen Wohnungslosigkeit.",
     "enacted", 2024, PUB_BMWSB,
     ["Nationaler Aktionsplan gegen Wohnungslosigkeit 2024", "bis 2030 ein passendes Wohnungsangebot erhält",
      "Nationales Forum gegen Wohnungslosigkeit"]),
    ("be_leitlinien2026", "https://www.berlin.de/sen/soziales/besondere-lebenssituationen/wohnungslose/wohnungslosenpolitik/leitlinien/leitlinien2026-1679155.php",
     "BE", "aktionsplan", "Leitlinien der Wohnungsnotfallhilfe und Wohnungslosenpolitik 2026",
     "Berlin: Leitlinien der Wohnungsnotfallhilfe und Wohnungslosenpolitik (Senatsbeschluss 9. Juni 2026)",
     "Berlin's senate adopted new guidelines on 9 June 2026 replacing those of 2019: prevention first, stronger "
     "Fachstellen Soziale Wohnhilfe, city-wide steering, target-group specific counselling and accommodation.",
     "enacted", 2026, "Senatsverwaltung für Arbeit, Soziales, Gleichstellung, Integration, Vielfalt und Antidiskriminierung Berlin",
     ["Der Senat von Berlin hat am 9. Juni 2026 die neuen", "Fachstellen Soziale Wohnhilfe"]),
    ("nw_endlich", "https://www.mags.nrw/endlich-ein-zuhause", "NW", "aktionsplan", "Landesinitiative „Endlich ein ZUHAUSE!“",
     "Nordrhein-Westfalen: Landesinitiative gegen Wohnungslosigkeit „Endlich ein ZUHAUSE!“",
     "NRW state initiative (since winter 2019/2020): cooperation agreement with the housing industry, 'Kümmerer' "
     "projects, projects for young homeless people, Housing First and addiction counselling funding.", "enacted", 2019,
     "MAGS NRW", ["Endlich ein ZUHAUSE!", "Kooperationsvereinbarung mit der Wohnungswirtschaft", "Housing First"]),
    ("nw_hf", "https://www.mags.nrw/system/files/media/document/file/housing-first_umsetzungskonzept_broschuere_mags-nrw.pdf",
     "NW", "housing_first", "Housing First NRW Umsetzungskonzept", "Housing First in Nordrhein-Westfalen – Umsetzungskonzept",
     "MAGS NRW implementation concept for a needs-based roll-out of Housing First in NRW.", "enacted", None, "MAGS NRW",
     ["Housing First in Nordrhein-Westfalen", "Umsetzungskonzept für eine bedarfsgerechte Implementierung"]),
    ("he_strategie2026", "https://soziales.hessen.de/sites/soziales.hessen.de/files/2026-09/20260831_landesstrategie_hessen.pdf",
     "HE", "aktionsplan", "Landesstrategie Hessen zur Prävention und Bekämpfung von Wohnungslosigkeit",
     "Landesstrategie Hessen zur Prävention und Bekämpfung von Wohnungs- und Obdachlosigkeit",
     "Hessian state strategy: funds, among others, six Fachstellen for preventive housing protection, six Housing "
     "First projects and two interface-management projects; the six Housing First model projects run 2026–2028 with "
     "about EUR 2.5 million and provide housing without preconditions.", "enacted", 2026,
     "Hessisches Ministerium für Arbeit, Integration, Jugend und Soziales",
     ["Landesstrategie Hessen zur Prävention und Bekämpfung von Wohnungs- und Obdachlosigkeit",
      "Gefördert werden u.a. sechs Fachstellen zur präventiven Wohnraumsicherung, sechs Housing-First-Projekte und zwei Projekte zum Schnittstellenmanagement",
      "im Zeitraum von 2026 bis 2028, mit insgesamt rund 2,5 Millionen Euro",
      "Die Projekte akquirieren Wohnraum und stellen ihn den Betroffenen ohne weitere Vorbedingungen zur Verfügung"]),
    ("ni_landesprogramm", "https://soziales.niedersachsen.de/download/223407",
     "NI", "aktionsplan", "Niedersächsisches Landesprogramm zur Überwindung von Wohnungslosigkeit",
     "Niedersächsisches Landesprogramm zur Hilfe für Menschen, bei denen besondere Lebensumstände mit sozialen "
     "Schwierigkeiten verbunden sind, und zur Überwindung von Wohnungslosigkeit",
     "Lower Saxony's programme for the §§ 67 ff. SGB XII support system; municipal emergency accommodation is outside "
     "its scope. It sees no need for a separate Housing First service type and anchors the Housing First principles "
     "in the existing system instead.", "enacted", 2025, "Niedersächsisches Ministerium für Soziales, Arbeit, Gesundheit und Gleichstellung",
     ["Niedersächsisches Landesprogramm zur Hilfe für Menschen, bei denen besondere Lebensumstände mit sozialen Schwierigkeiten verbunden sind, und zur Überwindung von Wohnungslosigkeit",
      "Eines eigenen Leistungstyps „Housing First“ bedarf es demgegenüber nicht",
      "Vielmehr sollten die Housing-First-Prinzipien im bestehenden System klar verankert und umgesetzt werden"]),
    ("hh_drs21_16901", "https://www.buergerschaft-hh.de/parldok/dokument/66469/fortentwicklung_der_wohnungslosenhilfe_in_hamburg_sachstand_seit_vorlage_des_gesamtkonzepts_wohnungslosenhilfe_zugleich_stellungnahme_des_senats_zu_de.pdf",
     "HH", "aktionsplan", "Bürgerschaft Drs. 21/16901",
     "Fortentwicklung der Wohnungslosenhilfe in Hamburg – Sachstand seit Vorlage des Gesamtkonzepts Wohnungslosenhilfe (Mitteilung des Senats an die Bürgerschaft)",
     "Hamburg Senate report (16.04.2019) on implementing and developing the Gesamtkonzept Wohnungslosenhilfe "
     "(2012, Drs. 20/5867): prevention, low-threshold help incl. the winter emergency programme, health, public "
     "accommodation by f&w fördern und wohnen AöR and housing supply.",
     "enacted", 2019, "Senat der Freien und Hansestadt Hamburg (Bürgerschaftsdrucksache)",
     ["Drucksache 21/16901", "Fortentwicklung der Wohnungslosenhilfe in Hamburg – Sachstand seit Vorlage des Gesamtkonzepts Wohnungslosenhilfe"]),
    ("rp_aktionsplan_armut", "https://masffj.rlp.de/fileadmin/06/04_Soziales/Soziales_Dokumente/Aktionsplan_Armutsbeka__mpfung_11122020.pdf",
     "RP", "aktionsplan", "Aktionsplan zur Armutsbekämpfung Rheinland-Pfalz (Dezember 2020)",
     "Aktionsplan zur Armutsbekämpfung Rheinland-Pfalz – Handlungsfeld Wohnen und Quartier (3.3 Maßnahmen zur Prävention und Überwindung von Wohnungslosigkeit)",
     "Rhineland-Palatinate's anti-poverty action plan (Dec 2020) includes a homelessness chapter: measures to "
     "prevent and overcome homelessness and, as follow-up to the participation process, specialised counselling "
     "centres for securing housing (Fachberatungsstellen zur Wohnraumsicherung). No separate homelessness plan.",
     "enacted", 2020, "Ministerium für Soziales, Arbeit, Gesundheit und Demografie Rheinland-Pfalz",
     ["AKTIONSPLAN ZUR ARMUTSBEKÄMPFUNG", "3.3 Maßnahmen zur Prävention und Überwindung von Wohnungslosigkeit",
      "Anschlussmaßnahme an den Beteiligungsprozess: Fachberatungsstellen zur Wohnraumsicherung"]),
    ("sh_drs20_4332", "https://www.landtag.ltsh.de/infothek/wahl20/drucks/04300/drucksache-20-04332.pdf",
     "SH", "aktionsplan", "Landtag SH Drs. 20/4332",
     "Bericht der Landesregierung zur Situation wohnungs- und obdachloser Menschen in Schleswig-Holstein",
     "Government report to the Landtag (14.04.2026) on the situation of homeless and roofless people in "
     "Schleswig-Holstein (data, services, measures), requested by Drs. 20/4001. A report, not a strategy: SH has "
     "no separate Land homelessness strategy.",
     "enacted", 2026, "Landesregierung Schleswig-Holstein – Ministerin für Inneres, Kommunales, Wohnen und Sport",
     ["Drucksache 20/4332", "Bericht der Landesregierung zur Situation wohnungs- und obdachloser Menschen in Schleswig-Holstein"]),
    ("th_strategie_entwurf", "https://soziales.thueringen.de/fileadmin/user_upload/Veranstaltungen_und_Sonderseiten/Fachtag_Wohnungslosigkeit/2024-03-15_Entwurf_Strategie_Wohnungslosigkeit.pdf",
     "TH", "aktionsplan", "Entwurf Thüringer Strategie gegen Wohnungslosigkeit (Stand 15.03.2024)",
     "Entwurf Thüringer Strategie gegen Wohnungslosigkeit",
     "Draft Thuringian strategy (15.03.2024): to overcome homelessness by 2030, shift from mitigating "
     "consequences to prevention, with securing existing housing at the centre. Draft only; not adopted.",
     "draft", 2024, "Thüringer Ministerium für Arbeit, Soziales, Gesundheit, Frauen und Familie",
     ["Entwurf Thüringer Strategie gegen Wohnungslosigkeit", "Stand 15. März 2024",
      "bis zum Jahr 2030 zu überwinden ist es notwendig, von einer vorran"]),
    ("sn_empfehlungen2021", "https://www.revosax.sachsen.de/vorschrift_gesamt/19244/48637.pdf",
     "SN", "aktionsplan", "Gemeinsame Empfehlungen SMS/SMR/SMI zu Wohnungsnotfällen vom 10.03.2021",
     "Gemeinsame Empfehlungen des Sächsischen Staatsministeriums für Soziales und Gesellschaftlichen Zusammenhalt, des Sächsischen Staatsministeriums für Regionalentwicklung und des Sächsischen Staatsministeriums des Innern zur Vermeidung und Beseitigung von Wohnungsnotfällen",
     "Saxony's joint ministerial recommendations (10.03.2021) to municipalities on cooperation, definitions, "
     "preventing and overcoming housing emergencies and accommodating homeless people. Guidance, not a "
     "strategy; Saxony has no separate Land homelessness strategy.",
     "enacted", 2021, "Sächsische Staatsministerien SMS, SMR, SMI (REVOSax)",
     ["zur Vermeidung und Beseitigung von Wohnungsnotfällen Vom 10. März 2021",
      "IV. Vermeidung von Wohnungsnotfällen V. Überwindung von Wohnungsnotfällen VI. Unterbringung von Wohnungslosen"]),
    ("hb_senat_2030", "https://www.rathaus.bremen.de/sixcms/media.php/13/top%2011_20240423_Beendigung_von_Wohnungs_und_Obdachlosigkeit_N.pdf",
     "HB", "aktionsplan", "Mitteilung des Senats vom 23.04.2024 (Große Anfrage CDU, Drs. 21/295)",
     "Wie gestaltet Bremen seinen Beitrag zur Beendigung von Wohnungs- und Obdachlosigkeit in Deutschland bis zum Jahr 2030? (Mitteilung des Senats an die Bremische Bürgerschaft)",
     "Bremen Senate answer (23.04.2024) setting out the Land's contribution to ending homelessness by 2030: new "
     "affordable housing, access to the housing market, prevention, street work, emergency accommodation and "
     "transfer of Housing First into regular SGB XII funding. Policy statement, not a separate action plan.",
     "enacted", 2024, "Senat der Freien Hansestadt Bremen",
     ["Mitteilung des Senats an die Bremische Bürgerschaft (Landtag) vom 23. April 2024",
      "Wie gestaltet Bremen seinen Beitrag zur Beendigung von Wohnungs- und Obdachlosigkeit in Deutschland bis zum Jahr 2030?"]),
    ("by_aktionsplan", "https://www.stmas.bayern.de/themen/soziale-hilfen/obdachlosenhilfe/",
     "BY", "aktionsplan", "Aktionsplan „Hilfe bei Obdachlosigkeit“",
     "Bayern: Aktionsplan „Hilfe bei Obdachlosigkeit“ (StMAS web page)",
     "Bavarian action plan funding concrete projects for homeless people, usually with start-up funding for two years; "
     "the page also names the joint ministerial Empfehlungen für das Obdach- und Wohnungslosenwesen of October 2023.",
     "enacted", None, "Bayerisches Staatsministerium für Familie, Arbeit und Soziales",
     ["Mit dem Aktionsplan stärkt Bayern konkrete Projekte, die wohnungs- und obdachlosen Menschen helfen",
      "Diese Initiativen bekommen meist eine Anschubfinanzierung für zwei Jahre",
      "haben die Empfehlungen im Oktober 2023 gemeinsam herausgegeben"]),
    ("bw_hf", "https://sozialministerium.baden-wuerttemberg.de/de/soziales/leistungen-unterstuetzung/soziale-leistungen/housing-first",
     "BW", "housing_first", "Housing-First-Modellprojekte Baden-Württemberg 2024–2026",
     "Baden-Württemberg: Housing First (Sozialministerium web page and Förderaufruf 2023)",
     "The BW social ministry funds six projects testing the Housing First approach in 2024–2026, jointly with the "
     "Vector Stiftung; the 2023 call refers to the coalition goal of overcoming homelessness in BW.", "enacted", 2024,
     "Ministerium für Soziales, Gesundheit und Integration Baden-Württemberg",
     ["Das Sozialministerium fördert im Zeitraum von 2024 bis 2026 in Kooperation mit der Vector Stiftung sechs Projekte im Land, die den Housing-First-Ansatz erproben"]),
]
# Version of every law row (Lead decision 2026-11-21): as_of = the date the archived text states; kind =
# "consolidated" (an official consolidated text) or "original" (the promulgated text, without later amendments) or
# "plan" (a policy document, not a statute). as_of_text must occur verbatim in the version source (the row's own
# source unless version_url is given). extra = further archived sources whose needles must also be found.
# local = the file is archived by hand (site refuses our honest UA); if absent the row is skipped with a log note.
SGB12_FULL = f"{GII}/sgb_12/BJNR302300003.html"
SGB2_FULL = f"{GII}/sgb_2/BJNR295500003.html"
NI_GVBL_2019 = "https://www.niedersachsen.de/download/144204/Nds._GVBl._Nr._8_2019_vom_23.05.2019_S._87-107.pdf"
# Licence/terms per plan source (audited 2026-11-21). Plans and reports are no Gesetz/Verordnung/Erlass, so
# § 5 Abs. 1 UrhG does not apply to them; the atlas stores title, date, own summary and a short verified quote.
_KEEP = "; im Atlas nur Titel, Datum, eigene Zusammenfassung und kurzes Zitat mit Quellenangabe (§ 51 UrhG), kein Volltext"
_DRS = ("Rechte vorbehalten: Parlamentsdrucksache, kein Gesetz und kein Amtsblatt; § 5 Abs. 2 UrhG wird nicht in Anspruch genommen "
        "(Lead 2026-11-23: § 5 nur für Gesetze, Verordnungen, Erlasse und Amtsblätter); Quellenangabe nach § 63 UrhG")
LIC_PLAN = ("Rechte vorbehalten: amtliche Veröffentlichung (Plan/Bericht), kein Gesetz, keine Verordnung und kein Erlass, "
            "daher nicht § 5 Abs. 1 UrhG; kein offener Lizenzhinweis des Herausgebers" + _KEEP)
PLAN_LIC = {
    "hh_drs21_16901": "Bürgerschaftsdrucksache 21/16901 (Mitteilung des Senats): " + _DRS
                      + "; die Parlamentsdatenbank erlaubt Aufrufen, Speichern und Ausdrucken "
                        "(https://www.hamburgische-buergerschaft.de/recherche-info/parlamentsdatenbank)" + _KEEP,
    "sh_drs20_4332": "Landtagsdrucksache 20/4332 (Bericht der Landesregierung): " + _DRS
                     + "; landtag.ltsh.de nennt Nutzungsbedingungen nur für Bilder "
                       "(https://www.landtag.ltsh.de/metainfo/nutzungsbedingungen-bilder/)" + _KEEP,
    "hb_senat_2030": "Mitteilung des Senats an die Bremische Bürgerschaft vom 23.04.2024: " + _DRS
                     + "; als Senatsunterlage veröffentlicht (https://www.rathaus.bremen.de/senatsunterlagen-57451), "
                       "Impressum ohne Nachnutzungsbedingungen (https://www.rathaus.bremen.de/impressum-744)" + _KEEP,
    "rp_aktionsplan_armut": "© Landesregierung Rheinland-Pfalz (Druckschrift der Öffentlichkeitsarbeit, MSAGD 2020); "
                            "Impressum masffj.rlp.de: zum Download gekennzeichnete Dokumente frei herunterladbar, "
                            "Weiterverwendung von Texten nur nach Absprache (https://masffj.rlp.de/ueber-uns/impressum)" + _KEEP,
    "th_strategie_entwurf": "© Thüringer Ministerium für Soziales, Gesundheit, Arbeit und Familie; Impressum: Inhalte "
                            "urheberrechtlich geschützt, Downloads nur für privaten, nicht kommerziellen Gebrauch "
                            "(https://soziales.thueringen.de/impressum); lokal archiviert, nicht veröffentlicht" + _KEEP,
    "sn_empfehlungen2021": "Gemeinsame Empfehlungen der Staatsministerien SMS, SMR, SMI vom 10.03.2021 (Verwaltungsvorschrift, "
                           "im VwV-Verzeichnis SächsABl. SDr. geführt): amtlicher Erlass, amtliches Werk nach § 5 Abs. 1 UrhG; "
                           "REVOSax-Impressum ohne Nachnutzungsbedingungen (https://www.revosax.sachsen.de/impressum)",
}
LAW_META = {
    "sgb12_67": dict(as_of="2026-07-24", kind="consolidated", version_url=SGB12_FULL, as_of_text="Zuletzt geändert durch Art. 2d G v. 24.7.2026 I Nr. 228"),
    "sgb12_68": dict(as_of="2026-07-24", kind="consolidated", version_url=SGB12_FULL, as_of_text="Zuletzt geändert durch Art. 2d G v. 24.7.2026 I Nr. 228"),
    "sgb12_69": dict(as_of="2026-07-24", kind="consolidated", version_url=SGB12_FULL, as_of_text="Zuletzt geändert durch Art. 2d G v. 24.7.2026 I Nr. 228"),
    "dvo_67": dict(as_of="2003-12-27", kind="consolidated", as_of_text="Stand: Geändert durch Art. 14 G v. 27.12.2003 I 3022"),
    "sgb2_22": dict(as_of="2026-04-16", kind="consolidated", version_url=SGB2_FULL, as_of_text="zuletzt geändert durch Art. 1a G v. 16.4.2026 I Nr. 107"),
    "woberichtsg": dict(as_of="2022-12-05", kind="consolidated", as_of_text="Stand: Geändert durch Art. 2 G v. 5.12.2022 I 2160"),
    "by_lstvg7": dict(as_of="2024-12-17", kind="consolidated", as_of_text="Text gilt ab: 17.12.2024"),
    "bb_obg": dict(as_of="2024-03-05", kind="consolidated", as_of_text="zuletzt geändert durch Artikel 41 des Gesetzes vom 5. März 2024"),
    "nw_obg": dict(as_of="2026-07-01", kind="consolidated", as_of_text="Gültig ab: 01.07.2026"),
    "sn_pbg": dict(as_of="2024-09-01", kind="consolidated", as_of_text="Fassung vom 01.09.2024"),
    "hb_polg": dict(as_of="2026-06-20", kind="consolidated", as_of_text="Inkrafttreten: 20.06.2026", local="law_hb_polg.pdf"),
    "bw_polg": dict(as_of="2020-10-06", kind="original", as_of_text="Vom 6. Oktober 2020 Polizeigesetz (PolG)",
                    note="original, without later amendments (no official free consolidated text outside the juris portal)"),
    "ni_npog": dict(as_of="2019-05-23", kind="original", as_of_text="Ausgegeben in Hannover am 23. Mai 2019", version_url=NI_GVBL_2019,
                    extra=[(NI_GVBL_2019, ["Die Überschrift erhält folgende Fassung", "Ordnungsbehördengesetz (NPOG)"])],
                    note="original texts: Neubekanntmachung 2005 + renaming 2019; later amendments not included"),
    "he_hsog": dict(as_of="2005-01-14", kind="original", as_of_text="Vom 14. Januar 2005", note="original, without later amendments"),
    "mv_sog": dict(as_of="2020-06-05", kind="original", as_of_text="am 5. Juni 2020 in Kraft getreten",
                   note="ministry print of the law as promulgated; without later amendments"),
    "be_asog": dict(as_of="2006-08-09", kind="original", as_of_text="in der seit dem 9. August 2006 geltenden Fassung bekannt gemacht",
                    note="Neubekanntmachung 2006; without later amendments"),
    "sh_lvwg": dict(as_of="1992-06-01", kind="original", as_of_text="in der ab 1. Juni 1992 geltenden Fassung bekanntgemacht",
                    local="law_sh_lvwg_excerpt.pdf", ocr_tool="publisher's OCR text layer (IT-Service SGS dDocuScan SH V3.0 / Kofax Capture PDF Generator)",
                    note="Neubekanntmachung 1992; without later amendments; excerpt (PDF pp. 259 + 303 of the 552-page volume)"),
    "nap2024": dict(as_of="2024", kind="plan", as_of_text="Nationaler Aktionsplan gegen Wohnungslosigkeit 2024"),
    "be_leitlinien2026": dict(as_of="2026-06-09", kind="plan", as_of_text="Der Senat von Berlin hat am 9. Juni 2026 die neuen"),
    "nw_endlich": dict(as_of=None, kind="plan", as_of_text=None, note="web page; no date printed, see fetch date"),
    "nw_hf": dict(as_of=None, kind="plan", as_of_text=None, note="brochure; no date printed"),
    "he_strategie2026": dict(as_of="2026-09-15", kind="plan", as_of_text=None,
                             note="no date printed; as_of = PDF CreationDate and HTTP Last-Modified 2026-09-15 (file name 20260831)"),
    "ni_landesprogramm": dict(as_of="2025-11-18", kind="plan", as_of_text=None,
                              note="no date printed; as_of = PDF CreationDate 2025-11-18"),
    "hh_drs21_16901": dict(as_of="2019-04-16", kind="plan", as_of_text="Drucksache 21/16901 21. Wahlperiode 16. 04. 19"),
    "rp_aktionsplan_armut": dict(as_of="2020-12", kind="plan", as_of_text="Dezember 2020 Diese Druckschrift wird im Rahmen der Öffentlichkeitsarbeit der Landesregierung Rheinland-Pfalz herausgegeben"),
    "sh_drs20_4332": dict(as_of="2026-04-14", kind="plan", as_of_text="Drucksache 20/4332 20. Wahlperiode 14. April 2026"),
    "th_strategie_entwurf": dict(as_of="2024-03-15", kind="plan", as_of_text="Stand 15. März 2024", note="draft, not adopted"),
    "sn_empfehlungen2021": dict(as_of="2021-03-10", kind="plan", as_of_text="Vom 10. März 2021"),
    "hb_senat_2030": dict(as_of="2024-04-23", kind="plan", as_of_text="Mitteilung des Senats an die Bremische Bürgerschaft (Landtag) vom 23. April 2024",
                          local="hb_senat_2030.pdf"),
    "by_aktionsplan": dict(as_of="2026-11-21", kind="plan", as_of_text=None,
                           note="web page without a date; as_of = retrieval date; plan running since 2019 per StMAS"),
    "bw_hf": dict(as_of="2026-11-21", kind="plan", as_of_text=None, note="web page retrieved 2026-11-21; call of 2023",
                  extra=[("https://sozialministerium.baden-wuerttemberg.de/fileadmin/redaktion/m-sm/intern/downloads/Foerderaufrufe/230829_Foerderaufruf_Modellprojekte_Housing_First_BW.pdf",
                          ["Modellprojekte in Baden-Württemberg zum Housing First-Ansatz",
                           "das Ziel formuliert, die Wohnungslosigkeit in Baden-Württemberg zu überwinden"])]),
}
# Files the Lead archives by hand (the publisher refuses the honest project UA; we never spoof a browser UA).
MANUAL_ARCHIVE = {
    "law_hb_polg.pdf": "https://www.transparenz.bremen.de/sixcms/detail.php?gsid=bremen203.c.338897.de&template=00_html_to_pdf_d",
    "hb_senat_2030.pdf": "https://www.rathaus.bremen.de/sixcms/media.php/13/top%2011_20240423_Beendigung_von_Wohnungs_und_Obdachlosigkeit_N.pdf",
    "ffm_wohnraum2024.pdf": "https://frankfurt.de/-/media/frankfurtde/service-und-rathaus/verwaltung/aemter-und-institutionen/amt-fuer-wohnungswesen/pdf/64_3/64_3_2024_bericht-kommunale-wohnraumversorgung.pdf",
    "muni_bremen_ortsgesetz_ordnung.pdf": "https://www.transparenz.bremen.de/sixcms/detail.php?gsid=bremen203.c.267198.de&template=00_html_to_pdf_d",
    "ffm_gefahrenabwehrvo.pdf": "https://frankfurt.de/-/media/frankfurtde/service-und-rathaus/verwaltung/aemter-und-institutionen/rechtsamt/pdf/satzungen/gefahrenabwehrverordnung.pdf",
    "muni_bremerhaven_ortsgesetz_ordnung.pdf": "https://www.transparenz.bremen.de/sixcms/detail.php?gsid=bremen2014_tp.c.72517.de&template=00_html_to_pdf_d",
    "muni_chemnitz_obdach.pdf": "https://www.chemnitz.de/fileadmin/chemnitz/media/rathaus/satzungen/50_760.pdf",
    "muni_chemnitz_polvo.pdf": "https://www.chemnitz.de/fileadmin/chemnitz/media/rathaus/satzungen/32_100_20250117.pdf",
    "muni_flensburg_obdach_geb.pdf": "https://www.flensburg.de/PDF/Satzung_über_die_Erhebung_von_Benutzungsgebühren_für_die_Unterbringung_Obdachloser_in_der_Stadt_Flensburg.PDF?ObjSvrID=2306&ObjID=4263&ObjLa=1&Ext=PDF",
    "muni_landau_obdach.pdf": "https://www.landau.de/output/download.php?file=%2Fmedia%2Fcustom%2F2644_3102_1.PDF%3F1782899248&fn=Obdachlosensatzung_2026",
    "muni_landau_gavo.pdf": "https://www.landau.de/output/download.php?file=%2Fmedia%2Fcustom%2F1815_4432_1.PDF%3F1594306775&fn=03-05_Neufassung_Gefahrenabwehrverordnung",
    "muni_neustadt_weinstrasse_gavo.pdf": "https://www.neustadt.eu/output/download.php?fid=2579.60.1.PDF",
    "muni_ulm_polizeiverordnung.pdf": "https://www.ulm.de/-/media/ulm/zdv/downloads/satzungen/oeffentliche-sicherheit-und-ordnung/101-polizeiverordnung.pdf",
    "muni_remscheid_obdach.pdf": "https://remscheid.de/politik-verwaltung/ortsrecht/download-pool/0.03_510_Obdachlosenunterkuenfte_Satzung.pdf",
    "muni_remscheid_obdach_geb.pdf": "https://remscheid.de/politik-verwaltung/ortsrecht/download-pool/0.03_511_Obdachlosenunterkuenfte_Gebuehrensatzung.pdf",
    "muni_frankfurt_lag_hsog_gebuehren_2026.pdf": "https://frankfurt.de/-/media/frankfurtde/service-und-rathaus/verwaltung/aemter-und-institutionen/rechtsamt/pdf/satzungen/unterbringungsgebuehrensatzung.pdf",
    "muni_gera_unterbringung_geb.pdf": "https://cms.gera.de/fileadmin/gera_de/Stadtverwaltung/1000/1040_Stadtrat_Ortsteilraete/Ortsrecht_Soziales/Unterbringungsgebuehrensatzung_15.07.2022.pdf",
    "muni_erlangen_verfuegungswohnungen.pdf": "https://erlangen.de/uwao-api/faila/files/bypath/Dokumente/Stadtrecht/240.00_verfuegungswohnungssatzung.pdf?q=normal&s=list&tn=1",
    "muni_erlangen_verfuegungswohnungen_geb_2025.pdf": "https://erlangen.de/uwao-api/faila/files/bypath/Dokumente/Stadtrecht/240_10_verfuegungswohnung_gebuheren_2025.pdf?q=normal&s=list&tn=1",
    "muni_ingolstadt_sns.pdf": "https://www.ingolstadt.de/output/download.php?fid=465.1195.1.PDF",
    "muni_ingolstadt_gruenanlagen.pdf": "https://www.ingolstadt.de/output/download.php?fid=465.1139.1.PDF",
    "muni_moenchengladbach_strassen_anlagen_vo.pdf": "https://www.moenchengladbach.de/fileadmin/news_import/Ortsrecht/30-ff/32.1_-_Geltungsdauer_bis_Dezember_2035.pdf",
    "muni_gera_alkoholverbot_heinrichstrasse.pdf": "https://cms.gera.de/fileadmin/gera_de/Stadtverwaltung/1000/1040_Stadtrat_Ortsteilraete/Ortsrecht_oeffentliche_Sicherheit_und_Ordnung/Verbot_des_Alkoholgenusses_in_der_Heinrichstrasse_25.07.2018.pdf",
    "muni_gera_stadtordnung.pdf": "https://cms.gera.de/fileadmin/gera_de/Stadtverwaltung/1000/1040_Stadtrat_Ortsteilraete/Ortsrecht_oeffentliche_Sicherheit_und_Ordnung/Stadtordnung.pdf",
    "muni_darmstadt_376.pdf": "https://www.darmstadt.de/fileadmin/Dateistruktur2024/04_RATHAUS/04_Stadtrecht-Satzungen/Alphabetisches_Sachregister/300_bis_399/376.pdf",
    "muni_darmstadt_374_neu.pdf": "https://www.darmstadt.de/fileadmin/Dateistruktur2024/04_RATHAUS/04_Stadtrecht-Satzungen/Alphabetisches_Sachregister/300_bis_399/374_neu.pdf",
    "muni_landshut_obdach.pdf": "https://landshut.de/sites/default/files/filemanager/Benutzerdaten/La55/Sozialverwaltung%20und%20Jugendhilfe/Satzung%20Obdachlosenunterk%C3%BCnfte.pdf",
    "muni_landshut_sisa.pdf": "https://landshut.de/sites/default/files/filemanager/Benutzerdaten/La55/Rechtspflege/Sicherheitssatzung-SiSa.pdf",
    "muni_landshut_sondernutzung.pdf": "https://landshut.de/sites/default/files/filemanager/Benutzerdaten/La55/Bauverwaltung/Sondernutzungssatzung.pdf",
    "muni_bayreuth_sns.pdf": "manual archive via browser, 2026-11-23 (Lead); sha256 bf372c4c…ad10; robots.txt of formular-server.de "
                             "answers HTTP 418 (read as disallow, fail closed), so the host does not permit automated fetching and the "
                             "file was archived once by hand and is read from the archive only",
    "muni_bayreuth_obdach.pdf": "manual archive via browser, 2026-11-23 (Lead); sha256 b85bae3a…e6854; Bayreuther Stadtrecht 743, "
                                "Gebührensatzung vom 29.11.2017, Amtsblatt der Stadt Bayreuth Nr. 20 vom 15.12.2017; robots.txt of "
                                "formular-server.de answers HTTP 418 (read as disallow, fail closed), so the host does not permit "
                                "automated fetching and the file was archived once by hand and is read from the archive only",
    "muni_gladbeck_obdach_gebuehren.pdf": "manual archive via browser, 2026-11-23 (Lead); sha256 cd1a6d4c…188abe; Satzung vom "
                                          "02.06.2022; the city's Ortsrecht page answers 404 to the project UA",
    "muni_bayreuth_sns.pdf": "https://formular-server.de/BT_FS/findform?areashortname=bt_oe&formtecid=2&shortname=Sondernutzungssatzun",
    "muni_bayreuth_obdach.pdf": "https://formular-server.de/BT_FS/findform?areashortname=bt_oe&formtecid=2&shortname=743",
    "muni_gladbeck_obdach_gebuehren.pdf": "https://www.gladbeck.de/uploads/Benutzung_der_Obdachlosenunterkuenfte_43d09e74e0.pdf",
}
MANUAL_NOTE = {
    "muni_darmstadt_376.pdf": "manual archive via browser, 2026-11-23 (Lead); sha256 53e31a82…; robots.txt of www.darmstadt.de disallows /fileadmin",
    "muni_darmstadt_374_neu.pdf": "manual archive via browser, 2026-11-23 (Lead); sha256 38983373…; robots.txt of www.darmstadt.de disallows /fileadmin",
    "muni_landshut_obdach.pdf": "manual archive via browser, 2026-11-23 (Lead); sha256 0d6f3bbf…; robots.txt of landshut.de disallows /sites/default/files/; the host's robots.txt disallows automated fetching of this path, so the file was archived once by hand and is read from the archive only",
    "muni_landshut_sisa.pdf": "manual archive via browser, 2026-11-23 (Lead); sha256 6bd3d9c8…; robots.txt of landshut.de disallows /sites/default/files/; the host's robots.txt disallows automated fetching of this path, so the file was archived once by hand and is read from the archive only",
    "muni_landshut_sondernutzung.pdf": "manual archive via browser, 2026-11-23 (Lead); sha256 e9f034fd…; robots.txt of landshut.de disallows /sites/default/files/; the host's robots.txt disallows automated fetching of this path, so the file was archived once by hand and is read from the archive only",
    "muni_bremen_ortsgesetz_ordnung.pdf": "manual archive by the Lead with the project UA from another IP, 2026-11-21; "
                                          "transparenz.bremen.de renders the PDF per request (fresh CreationDate), so the "
                                          "filename is pinned, not the hash",
    "ffm_gefahrenabwehrvo.pdf": "manual archive via browser, 2026-11-21 (Lead); frankfurt.de returns 403 to the project UA",
    "muni_bremerhaven_ortsgesetz_ordnung.pdf": "manual archive by the Lead, 2026-11-21 (gsid c.72517, current version); "
                                               "transparenz.bremen.de answers 403 to the project UA from the deck and renders the PDF "
                                               "per request, so the filename is pinned, not the hash",
    "muni_chemnitz_obdach.pdf": "manual archive via browser, 2026-11-21 (Lead), from the 50.760 link on "
                                "https://www.chemnitz.de/de/rathaus/satzungen; www.chemnitz.de refuses the project UA",
    "muni_chemnitz_polvo.pdf": "manual archive via browser, 2026-11-21 (Lead), from the 32.100 link on "
                               "https://www.chemnitz.de/de/rathaus/satzungen; www.chemnitz.de refuses the project UA",
    "law_sh_lvwg_excerpt.pdf": "excerpt cut with qpdf 12.4.2 (PDF pages 259 = GVOBl. S. 243 title of the Neufassung, "
                               "303 = § 174) from the full volume GVOBl_1992.pdf (552 pages, 519,748,079 bytes, sha256 "
                               "b17cf8c7bd0ae180c4b43943eb26d5cce9beb90731f9d390241945d0fb626063, Last-Modified "
                               "2025-05-26), downloaded once with the project UA on 2026-11-21; excerpt sha256 60aff24f…795d",
    "law_hb_polg.pdf": "manual archive by the Lead with the project UA from another IP, 2026-11-21 (sha256 b5eecc7c…c378)",
    "ffm_wohnraum2024.pdf": "manual archive via browser, 2026-11-21 (Lead); sha256 7251a252…cd264; frankfurt.de "
                            "returns 403 to the project UA",
    "muni_flensburg_obdach_geb.pdf": "manual archive via browser/box, 2026-11-21 (Lead); sha256 d07eb9d4…d15a; robots.txt of www.flensburg.de disallows the document path",
    "muni_landau_obdach.pdf": "manual archive via browser/box, 2026-11-21 (Lead); sha256 f482b79e…41a8; robots.txt disallows /output/download.php",
    "muni_landau_gavo.pdf": "manual archive via browser/box, 2026-11-21 (Lead); sha256 3b6a42f4…70f5; robots.txt disallows /output/download.php",
    "muni_neustadt_weinstrasse_gavo.pdf": "manual archive via browser/box, 2026-11-21 (Lead); sha256 e62b13d6…b4ab; robots.txt disallows /output/download.php",
    "muni_ulm_polizeiverordnung.pdf": "manual archive via browser/box, 2026-11-21 (Lead); sha256 8834727d…c9c6; ulm.de answers 403 to the project UA",
    "muni_remscheid_obdach.pdf": "manual archive via browser/box, 2026-11-21 (Lead); sha256 5420708b…bd5b; remscheid.de answers Cloudflare 403 to the project UA",
    "muni_remscheid_obdach_geb.pdf": "manual archive via browser/box, 2026-11-21 (Lead); sha256 dd5a6202…0d6d; remscheid.de answers Cloudflare 403 to the project UA",
    "muni_frankfurt_lag_hsog_gebuehren_2026.pdf": "manual archive via browser/box, 2026-11-21 (Lead); sha256 ca2b33a1…b730; frankfurt.de returns 403 to the project UA",
    "muni_gera_unterbringung_geb.pdf": "manual archive via browser/box, 2026-11-21 (Lead); sha256 2427f354…164b; robots.txt of cms.gera.de disallows all paths",
    "muni_erlangen_verfuegungswohnungen.pdf": "manual archive via browser/box, 2026-11-21 (Lead); sha256 237ee0fe…b36c; robots.txt disallows /uwao-api/ for the project UA",
    "muni_erlangen_verfuegungswohnungen_geb_2025.pdf": "manual archive via browser/box, 2026-11-21 (Lead); sha256 11934f84…4cd2; robots.txt disallows /uwao-api/ for the project UA",
    "muni_ingolstadt_sns.pdf": "manual archive via browser/box, 2026-11-21 (Lead); sha256 587fc879…284e; robots.txt disallows /output/download.php",
    "muni_ingolstadt_gruenanlagen.pdf": "manual archive via browser/box, 2026-11-21 (Lead); sha256 52451411…e3bf; robots.txt disallows /output/download.php",
    "muni_moenchengladbach_strassen_anlagen_vo.pdf": "manual archive via browser/box, 2026-11-21 (Lead); sha256 da5fbeb1…3b27; robots.txt disallows /fileadmin/",
    "muni_gera_alkoholverbot_heinrichstrasse.pdf": "manual archive via browser/box, 2026-11-21 (Lead); sha256 fa1ee09c…5a04; robots.txt of cms.gera.de disallows all paths",
    "muni_gera_stadtordnung.pdf": "manual archive via browser/box, 2026-11-21 (Lead); sha256 a8d2ffbd…2c5f; robots.txt of cms.gera.de disallows all paths",
}
_TEXT_CACHE = {}
# Municipal ordinances we could not read with the honest project UA; for the Lead to archive by hand (then add a
# `_mu(..., local=<file>)` entry with needles checked against the archived file). Not fetched, not ingested.
MUNI_MANUAL_WANTED = {
    # filename: (gem8, city, exact url, reason, part)  part a = shelter statute, b = begging/camping/alcohol rule
    # 2026-11-21: the 15 files requested earlier were archived by the Lead and are wired as _mu(local=...) entries
    # (Flensburg SNS: scan without text layer, blocked; Mönchengladbach Übergangsunterkünfte: refugee-only, not ingested).
    # 2026-11-23: the 2 Gera (b) files were archived by the Lead and are wired as gera_alkoholverbot / gera_stadtordnung.
    # 2026-11-23 (b20): muni_bayreuth_sns.pdf is archived and wired as bayreuth_sns; nothing is pending.
}


COURT = [
    # (key, url, court, citation, date, land, summary, needles)
    ("ovg_nrw_9b187_20", "https://nrwe.justiz.nrw.de/ovgs/ovg_nrw/j2020/9_B_187_20_Beschluss_20200306.html",
     "Oberverwaltungsgericht NRW", "OVG NRW, Beschl. v. 06.03.2020 – 9 B 187/20", "2020-03-06", "NW",
     "City of Köln ordered by interim injunction to provide a homeless family accommodation meeting the standards for "
     "the accommodation of homeless persons; the claim under § 14 Abs. 1 OBG NRW is directed at a humane accommodation "
     "protecting against the weather and leaving room for the most basic needs.",
     ["ECLI:DE:OVGNRW:2020:0306.9B187.20.00", "Der Unterbringungsanspruch eines Obdachlosen nach § 14 Abs. 1 OBG NRW ist grundsätzlich auf die Unterbringung in einer menschenwürdigen Unterkunft gerichtet"]),
    ("vg_koeln_22l1420_24", "https://nrwe.justiz.nrw.de/ovgs/vg_koeln/j2024/22_L_1420_24_Beschluss_20240801.html",
     "Verwaltungsgericht Köln", "VG Köln, Beschl. v. 01.08.2024 – 22 L 1420/24", "2024-08-01", "NW",
     "Interim relief refused: the § 14 Abs. 1 OBG NRW claim is in principle directed only at a humane accommodation, not "
     "at a specific one (here: continued use of the previous flat).",
     ["ECLI:DE:VGK:2024:0801.22L1420.24.00", "ist aber grundsätzlich nicht auf eine bestimmte Unterkunft geric"]),
    ("vg_arnsberg_6l898_19", "https://nrwe.justiz.nrw.de/ovgs/vg_arnsberg/j2019/6_L_898_19_Beschluss_20190619.html",
     "Verwaltungsgericht Arnsberg", "VG Arnsberg, Beschl. v. 19.06.2019 – 6 L 898/19", "2019-06-19", "NW",
     "Municipality ordered to accommodate the applicant; involuntarily homeless persons have a claim against the "
     "municipality where they actually stay to full-day humane accommodation.",
     ["ECLI:DE:VGAR:2019:0619.6L898.19.00", "Unfreiwillig Obdachlose – wie die Antragstellerin – haben grundsätzlich einen Anspruch gegen die Gemeinde"]),
    # bverwg.de: the court's own open site (robots: Allow /, Content-Signal search=yes, ai-train=no, use=reference;
    # no tdm-reservation header). Used for reference/citation only.
    ("bverwg_1c4_20", "https://www.bverwg.de/180221U1C4.20.0",
     "Bundesverwaltungsgericht", "BVerwG, Urt. v. 18.02.2021 – 1 C 4.20", "2021-02-18", None,
     "Asylum law (internal protection, Art. 3 ECHR): securing the basic need of housing, in particular protection from "
     "bad weather, does not require a flat of one's own as long as access to changing accommodation avoids "
     "homelessness with sufficient certainty; collective shelters offering safe, weatherproof and humane "
     "accommodation are not excluded. Related standard, not a municipal duty-to-house case.",
     ["ECLI:DE:BVerwG:2021:180221U1C4.20.0",
      "eine eigene, dauerhaft zur alleinigen Verfügung stehende Wohnung ist nicht erforderlich, wenn durch den Zugang zu wechselnden Unterkünften Obdachlosigkeit hinreichend sicher vermieden werden kann"]),
    ("bverwg_4c9_18", "https://www.bverwg.de/210219U4C9.18.0",
     "Bundesverwaltungsgericht", "BVerwG, Urt. v. 21.02.2019 – 4 C 9.18", "2019-02-21", None,
     "Planning law (§ 246 Abs. 9 BauGB): only projects through which the public sector exercises its responsibility "
     "for accommodating refugees and asylum seekers are privileged; private projects only if agreed with or "
     "comparably secured for that public task. Related (public accommodation duty), not homelessness law proper.",
     ["ECLI:DE:BVerwG:2019:210219U4C9.18.0",
      "dienen nur Vorhaben, mit denen die öffentliche Hand ihre Unterbringungsverantwortung wahrnimmt"]),
    ("bverwg_5c7_20", "https://www.bverwg.de/de/240621U5C7.20.0",
     "Bundesverwaltungsgericht", "BVerwG, Urt. v. 24.06.2021 – 5 C 7.20", "2021-06-24", None,
     "Youth-welfare cost dispute (SGB VIII §§ 19, 86; SGB X § 105): local competence for a youth-welfare measure "
     "that follows a joint mother/father-and-child housing measure under § 19 SGB VIII is governed by § 86 SGB VIII. "
     "The facts involve a mother who took a private flat in the facility to avoid homelessness; related (housing "
     "of families in need), not a municipal duty-to-house case.",
     ["ECLI:DE:BVerwG:2021:240621U5C7.20.0",
      "Die örtliche Zuständigkeit eines Trägers der Kinder- und Jugendhilfe bestimmt sich für eine Leistung der Kinder- und Jugendhilfe, die einer Leistung nach § 19 SGB VIII nachfolgt, regelmäßig nach § 86 SGB VIII",
      "bezog in der Einrichtung zur Vermeidung von Obdachlosigkeit eine private Wohnung"]),
    # bsg.bund.de: the court's own site (robots: Allow for /SharedDocs/, Crawl-delay 30; no tdm header).
    ("bsg_b14as19_20", "https://www.bsg.bund.de/SharedDocs/Entscheidungen/DE/2021/2021_05_19_B_14_AS_19_20_R.html",
     "Bundessozialgericht", "BSG, Urt. v. 19.05.2021 – B 14 AS 19/20 R", "2021-05-19", None,
     "Basic income support (SGB II § 22): fees charged afterwards for using municipal/state accommodation (here a "
     "reception facility, after refugee recognition) count as housing need in the month they fall due, not in the "
     "months of use. Relevant to how shelter fees (Benutzungsgebühren) are covered by the Jobcenter.",
     ["ECLI:DE:BSG:2021:190521UB14AS1920R0",
      "Nachträglich für die Nutzung von Wohnraum in Aufnahmeeinrichtungen erhobene Gebühren sind bei späterer Fälligkeit keine dem Zeitpunkt der tatsächlichen Nutzung zuzuordnende Bedarfe, sondern im Monat ihrer Fälligkeit beim Arbeitslosengeld II zu berücksichtigen"]),
    # gesetze-bayern.de (Bürgerservice BAYERN.RECHT, official Bavarian portal): robots Allow /, no tdm header.
    # Its Nutzungshinweise say the editorial Leitsätze are not free under § 5 UrhG, so needles and summaries are
    # taken from the court's own Gründe only, never from the Leitsätze/Schlagworte.
    ("bayvgh_4ce24_60", "https://www.gesetze-bayern.de/Content/Pdf/Y-300-Z-BECKRS-B-2024-N-3506",
     "Bayerischer Verwaltungsgerichtshof", "BayVGH, Beschl. v. 15.02.2024 – 4 CE 24.60", "2024-02-15", "BY",
     "Complaint of the municipality rejected: family reunification of a recognised refugee without the housing "
     "requirement does not release municipalities from their duty under Art. 6, Art. 7 Abs. 2 Nr. 3 LStVG to avert "
     "the danger of homelessness; the municipality where the family stays is locally competent.",
     ["VGH München, Beschluss v. 15.02.2024 – 4 CE 24.60",
      "hat entgegen der Annahme der Antragsgegnerin nicht zur Folge, dass in derartigen Fällen die Gemeinden von ihrer landesrechtlich begründeten Pflicht zur Gefahrenabwehr nach Art. 6, Art. 7 Abs. 2 Nr. 3 LStVG entbunden wären",
      "ist auch keine andere Gemeinde als die Antragsgegnerin für die Obdachlosenunterbringung nach Art. 3 Abs. 1 Nr. 4 BayVwVfG örtlich zuständig"]),
    ("bayvgh_4ce24_627", "https://www.gesetze-bayern.de/Content/Pdf/Y-300-Z-BECKRS-B-2024-N-12209",
     "Bayerischer Verwaltungsgerichtshof", "BayVGH, Beschl. v. 30.04.2024 – 4 CE 24.627", "2024-04-30", "BY",
     "Local competence for housing a homeless person follows the place where the person currently stays and where "
     "the danger to life and health arises, not the place where homelessness first occurred.",
     ["VGH München, Beschluss v. 30.04.2024 – 4 CE 24.627",
      "sondern nach dem Ort, an dem er sich gerade aufhält und an dem die mit der Obdachlosigkeit verbundene Gefahr für Leben und Gesundheit aktuell auftritt (BayVGH"]),
]

LIC_COURT = "Gerichtsentscheidung, amtliches Werk (§ 5 Abs. 1 UrhG); nur Fundstelle, Datum und eigene Zusammenfassung gespeichert"
COURT_LIC = {
    "bverwg_1c4_20": LIC_COURT + "; bverwg.de robots Content-Signal: search=yes, ai-train=no, use=reference (Nutzung: Referenz/Zitat)",
    "bverwg_4c9_18": LIC_COURT + "; bverwg.de robots Content-Signal: search=yes, ai-train=no, use=reference (Nutzung: Referenz/Zitat)",
    "bverwg_5c7_20": LIC_COURT + "; bverwg.de robots Content-Signal: search=yes, ai-train=no, use=reference (Nutzung: Referenz/Zitat)",
    "bsg_b14as19_20": LIC_COURT + "; bsg.bund.de robots: /SharedDocs/ allowed, Crawl-delay 30",
    "bayvgh_4ce24_60": LIC_COURT + "; gesetze-bayern.de Nutzungshinweise: redaktionelle Leitsätze nicht gemeinfrei, nicht übernommen",
    "bayvgh_4ce24_627": LIC_COURT + "; gesetze-bayern.de Nutzungshinweise: redaktionelle Leitsätze nicht gemeinfrei, nicht übernommen",
}


def _doc_text(raw: bytes) -> str:
    """Whitespace-collapsed text of a PDF (layout + reading order, de-hyphenated) or an HTML page."""
    import html as _h, subprocess, tempfile, unicodedata
    if raw[:4] == b"%PDF":
        out = []
        with tempfile.NamedTemporaryFile(suffix=".pdf") as tf:
            tf.write(raw)
            tf.flush()
            for args in (["-layout"], []):
                t = subprocess.run(["pdftotext", *args, tf.name, "-"], capture_output=True, check=True).stdout
                t = t.decode("utf-8", "replace").replace("\u00ad\n", "").replace("\u00ad", "")  # soft hyphens (HE)
                out.append(" ".join(t.replace("-\n", "").split()))
        return unicodedata.normalize("NFKC", "\n".join(out))  # NFKC folds ligatures (ﬂ, ﬀ) of some prints
    try:
        s = raw.decode("utf-8")
    except UnicodeDecodeError:
        s = raw.decode("latin-1")
    s = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", s)
    return " ".join(_h.unescape(re.sub(r"<[^>]+>", " ", s)).split())


def _load(url, local=None):
    """Raw bytes of a source: hand-archived file if `local` is given (None if not there yet), else fetch()."""
    if local:
        path = common._cow(common.RAW / DOMAIN / local)
        if not path.exists():
            common._log(DOMAIN, url, "manual-archive-missing", 0, f"expected {path}")
            print(f"[{DOMAIN}] skip: manual archive {path} not present ({url})", file=sys.stderr)
            return None
        return path.read_bytes()
    return fetch(url, domain=DOMAIN, force=_FORCE[0])


def _register_local(conn, url, fname, title, pub, lic, how):
    """Register a hand-archived file (data/raw/counts_law/<fname>) under its original URL; never fetches."""
    path = common._cow(common.RAW / DOMAIN / fname)
    assert path.exists(), path
    return common.archive(conn, url, domain=DOMAIN, filename=fname, title=title, publisher=pub, license=lic,
                          notes=how)


def _text_of(url, local=None):
    if url not in _TEXT_CACHE:
        raw = _load(url, local)
        _TEXT_CACHE[url] = (raw, None if raw is None else _doc_text(raw))
    return _TEXT_CACHE[url]


def _fetch_verified(conn, key, url, title, publisher, needles, problems, local=None, extra=(), as_of_text=None,
                    version_url=None, license=None, extra_license=None):
    license = license or LIC_STATUTE
    try:
        raw, text = _text_of(url, local)
        if raw is None:
            problems.append(f"{key}:manual-archive-missing({local})")
            return None
        if not local:
            save_raw(DOMAIN, f"law_{key}.{'pdf' if raw[:4] == b'%PDF' else 'html'}", raw)
        checks = [(url, text, needles)]
        xlocal = {}
        for x in extra:
            xurl, xneedles = x[0], x[1]
            xl = x[2] if len(x) > 2 else None  # optional hand-archived file for the extra source (never fetched)
            xraw, xtext = _text_of(xurl, xl)
            if xraw is None:
                problems.append(f"{key}:manual-archive-missing({xl})")
                return None
            if xl:
                xlocal[xurl] = xl
            else:
                save_raw(DOMAIN, f"law_{key}_extra.{'pdf' if xraw[:4] == b'%PDF' else 'html'}", xraw)
            checks.append((xurl, xtext, xneedles))
        if as_of_text:
            vurl = version_url or url
            vraw, vtext = _text_of(vurl, local if vurl == url else None)
            if vurl != url:
                save_raw(DOMAIN, f"law_{key}_version.{'pdf' if vraw[:4] == b'%PDF' else 'html'}", vraw)
            checks.append((vurl, vtext, [as_of_text]))
    except Exception as e:  # noqa: one unreachable statute must not block the others; reported in notes
        problems.append(f"{key}:fetch-failed({e!r:.80})")
        return None
    for curl, ctext, cneedles in checks:
        # needles are verbatim (e.g. "m²"); the text is NFKC-folded by _doc_text, so fold the needle the same way
        missing = [n for n in cneedles if " ".join(unicodedata.normalize("NFKC", n).split()) not in ctext]
        if missing:
            problems.append(f"{key}:needle-not-found:{missing[0][:60]!r}")
            return None
        if curl != url and curl in xlocal:
            _register_local(conn, curl, xlocal[curl], f"{title} (version/amendment source)", publisher,
                            extra_license or LIC_STATUTE, MANUAL_NOTE.get(xlocal[curl]))
        elif curl != url:
            source_id_for(conn, curl, DOMAIN, title=f"{title} (version/amendment source)", publisher=publisher,
                          license=extra_license or LIC_STATUTE)
    if local:
        return _register_local(conn, url, local, title, publisher, license, MANUAL_NOTE.get(local))
    return source_id_for(conn, url, DOMAIN, title=title, publisher=publisher, license=license)


# ---------------------------------------------------------------------------------------------------------------
# Part 5: municipal law (Lead 2026-11-21, laws parity): shelter statutes (Satzungen über Obdachlosenunterkünfte,
# Benutzungs- und Gebührensatzungen) and local ordinances on begging / lagern / alcohol, from official city sites,
# Ortsrecht portals or Amtsblätter. One law row per document (kind satzung|verordnung, jurisdiction = AGS of the
# kreisfreie Stadt / Gemeinde), written only if every needle (title, version text, each fee quote) is found verbatim.
# Fees go to `metric` (entity kreis = the kreisfreie Stadt) with quote + locator; the value must occur in the quote.
MUNI_PUBLISHER = {"Düsseldorf": "Landeshauptstadt Düsseldorf", "München": "Landeshauptstadt München",
                  "Stuttgart": "Landeshauptstadt Stuttgart", "Dresden": "Landeshauptstadt Dresden",
                  "Mainz": "Landeshauptstadt Mainz", "Magdeburg": "Landeshauptstadt Magdeburg",
                  "Erfurt": "Landeshauptstadt Erfurt", "Potsdam": "Landeshauptstadt Potsdam",
                  "Hannover": "Landeshauptstadt Hannover", "Wiesbaden": "Landeshauptstadt Wiesbaden",
                  "Kiel": "Landeshauptstadt Kiel", "Tübingen": "Universitätsstadt Tübingen", "Saarbrücken": "Landeshauptstadt Saarbrücken",
                  "Schwerin": "Landeshauptstadt Schwerin", "Bonn": "Bundesstadt Bonn",
                  "Darmstadt": "Wissenschaftsstadt Darmstadt", "Solingen": "Klingenstadt Solingen",
                  "Hamburg": "Freie und Hansestadt Hamburg (Senat)", "Bremen": "Stadtgemeinde Bremen (Senat)"}


def muni_publisher(city):
    return MUNI_PUBLISHER.get(city, f"Stadt {city}")


LIC_MUNI = ("Amtliches Werk (§ 5 Abs. 1 UrhG): kommunale Satzung/Verordnung, amtlich bekanntgemacht; "
            "zitiert mit Fundstelle")
MUNI_TOPICS = {"obdach": "shelter statute (Benutzung/Errichtung von Obdachlosenunterkünften)",
               "obdach_gebuehr": "shelter fee statute (Gebühren für Obdachlosenunterkünfte)",
               "betteln": "begging rule", "lagern": "camping/lying-down (Lagern/Nächtigen) rule",
               "alkohol": "public alcohol rule", "sondernutzung": "street special-use rule"}


def _mu(key, ags, land, city, url, kind, topic, citation, title, as_of, as_of_text, text_kind, summary, needles,
        fees=(), note=None, in_force_from=None, local=None, gem=None, lic=None, extra=(), version_url=None,
        lapsed_on=None, lapsed_basis=None, lapsed_needle=None, ends_on=None, ends_needle=None):
    """`ags` is the 5-digit Kreis AGS; `gem` the 8-digit Gemeinde AGS of the issuing city (schema 3). For a
    kreisfreie Stadt the Gemeinde AGS is the Kreis AGS + '000' (GV-ISys, checked against geo_gemeinde at run
    time); a kreisangehörige city must pass `gem` explicitly.

    Lapsed rules (Lead 2026-11-23, INGEST_CONTRACT §11): a rule that is no longer in force but kept as a
    historical record passes lapsed_on ('YYYY-MM-DD', or 'YYYY' when only the year is determinable),
    lapsed_basis (why: the statute section that ends it, e.g. '§ 32 Abs. 1 OBG NRW', and/or the document's own
    end clause) and lapsed_needle (the deciding sentence, which must be one of `needles`, so it is verified in
    the archived text). The row is written with law.status='lapsed', law.in_force_to=lapsed_on and a summary
    that starts '[außer Kraft seit …: <basis>]'.

    Fixed-term rules (Lead 2026-11-23, b20; same mechanism, status stays 'in_force'): a rule whose own end
    clause names a calendar date passes ends_on and ends_needle (the end clause, one of `needles`, or the
    as_of_text when the date was set by the amendment that is the version source). ends_on uses the same
    convention as lapsed_on: the first day the rule is no longer in force ('gilt bis 31.12.2026' / 'mit Ablauf
    des 31.12.2026 außer Kraft' -> 2027-01-01; 'tritt am 31.12.2027 außer Kraft' -> 2027-12-31). It is written to
    law.in_force_to with a summary prefix '[befristet, außer Kraft ab …; end clause: „…“]'. Relative terms
    ('20 Jahre nach Inkrafttreten') are filled only when the same clause states the entry date (Magdeburg);
    statutory maximum terms (§ 32 OBG NRW, Art. 50 LStVG ...) are not filled."""
    gem = gem or ags + "000"
    if lapsed_on or lapsed_basis or lapsed_needle:
        import re as _re
        if not (lapsed_on and _re.fullmatch(r"\d{4}(-\d{2}-\d{2})?", lapsed_on)):
            raise ValueError(f"{key}: lapsed_on must be YYYY-MM-DD or YYYY, got {lapsed_on!r}")
        if not (lapsed_basis and _re.search(r"§|Art\.", lapsed_basis)):
            raise ValueError(f"{key}: lapsed_basis must cite the statute section (§ / Art.)")
        if lapsed_needle not in needles:
            raise ValueError(f"{key}: lapsed_needle must be one of the row's needles (verified in the document)")
    if ends_on or ends_needle:
        import re as _re
        if lapsed_on:
            raise ValueError(f"{key}: ends_on is for rules still in force; a lapsed rule uses lapsed_on")
        if not (ends_on and _re.fullmatch(r"\d{4}-\d{2}-\d{2}", ends_on)):
            raise ValueError(f"{key}: ends_on must be YYYY-MM-DD, got {ends_on!r}")
        if not (ends_needle in needles or ends_needle == as_of_text):
            raise ValueError(f"{key}: ends_needle must be one of the row's needles or its as_of_text")
    if not (len(ags) == 5 and len(gem) == 8 and gem.isdigit() and gem[:5] == ags):
        raise ValueError(f"{key}: Kreis AGS {ags!r} / Gemeinde AGS {gem!r} inconsistent")
    return dict(key=key, ags=ags, gem=gem, land=land, city=city, url=url, kind=kind, topic=topic, citation=citation,
                title=title, as_of=as_of, as_of_text=as_of_text, text_kind=text_kind, summary=summary,
                needles=list(needles), fees=list(fees), note=note, in_force_from=in_force_from, local=local,
                lic=lic or LIC_MUNI, extra=[(x[0], list(x[1]), *x[2:]) for x in extra],
                version_url=version_url, lapsed_on=lapsed_on, lapsed_basis=lapsed_basis, lapsed_needle=lapsed_needle,
                ends_on=ends_on, ends_needle=ends_needle)


def lapsed_label(on: str) -> str:
    return f"{on[8:10]}.{on[5:7]}.{on[:4]}" if len(on) == 10 else on


def _fee(metric, value, unit, quote, locator, year=None):
    return (metric, value, unit, quote, locator, year)


MUNI = [
    # ---- batch 1 (NRW) ----
    _mu("koeln_obdach_geb", "05315", "NW", "Köln",
        "https://www.stadt-koeln.de/mediaasset/content/satzungen/satzung_zur_aenderung_der_gebuehrensatzung_obdachloseneinrichtungen_2024_04_05.pdf",
        "satzung", "obdach_gebuehr", "Gebührensatzung Obdachloseneinrichtungen Köln (Änderung 05.04.2024)",
        "Satzung zur Änderung der Satzung der Stadt Köln über die Erhebung von Gebühren für die Inanspruchnahme von "
        "Einrichtungen für obdachlose Personen vom 05. April 2024",
        "2024-04-05", "Öffentliche Bekanntmachung vom 16. April 2024", "original",
        "Fees for municipal homeless facilities: base fee per m² of floor space and month plus heating fee "
        "(rates per facility in the annex); flat rates for named projects; in force on publication.",
        ["Satzung zur Änderung der Satzung der Stadt Köln über die Erhebung von Gebühren für die Inanspruchnahme von Einrichtungen für obdachlose Personen vom 05. April 2024",
         "Diese Satzung tritt am Tage ihrer öffentlichen Bekanntmachung in Kraft"],
        fees=[_fee("obdach_gebuehr_eur_m2_monat__koeln_brand_katastrophenschutz", 11.53, "EUR/m2/Monat",
                   "a) Brühler Str. 267-269, 50968 Köln 11,53 €/qm monatlich", "§ 3 Abs. 6 lit. a"),
              _fee("obdach_gebuehr_eur_m2_monat__koeln_einfachst_baracken", 4.10, "EUR/m2/Monat",
                   "Die Benutzungsgebühr für die Einfachst-Baracken in der Siedlungsanlage Egonstraße/Stammheimer Ring beträgt monatlich 4,10 € pro qm", "§ 3 Abs. 7")],
        note="amending statute that restates §§ 1-6; base statute 18.07.2018 (ABl StK 2018, S. 298)",
        in_force_from="2024-04-16"),
    _mu("duesseldorf_obdach", "05111", "NW", "Düsseldorf",
        "https://www.duesseldorf.de/stadtrecht/5/54-migration-und-integration/54101-satzung-fuer-uebergangsheime-und-obdachlosenunterkuenfte-der-landeshauptstadt-duesseldorf",
        "satzung", "obdach,obdach_gebuehr", "Düsseldorfer Stadtrecht 54.101",
        "Satzung für Übergangsheime und Obdachlosenunterkünfte der Landeshauptstadt Düsseldorf vom 14. Januar 2008",
        "2026-09", "Redaktioneller Stand: September 2026", "consolidated",
        "Public institution for temporary housing of homeless persons (§ 14 OBG NRW) and others; allocation by "
        "revocable written decision, no claim to a specific unit; monthly fee per m² plus flat rates for "
        "running and heating costs.",
        ["Satzung für Übergangsheime und Obdachlosenunterkünfte der Landeshauptstadt Düsseldorf",
         "Ein Anspruch auf Einweisung in eine bestimmte Unterkunft oder einzeln angemietete Wohnung oder auf ein Verbleiben in einer bestimmten Unterkunft oder einzeln angemieteten Wohnung besteht nicht"],
        fees=[_fee("obdach_gebuehr_grund_eur_m2_monat", 6.25, "EUR/m2/Monat",
                   "(c) in Unterkünften für Personen nach § 1 (1) Ziff. 3 - Standard 6,25 EUR", "§ 3 Abs. 2 lit. c"),
              _fee("obdach_gebuehr_grund_eur_m2_monat__gehoben", 6.80, "EUR/m2/Monat",
                   "- gehobener Standard 6,80 EUR", "§ 3 Abs. 2 lit. c"),
              _fee("obdach_nebenkosten_eur_m2_monat", 1.92, "EUR/m2/Monat",
                   "(c) in Unterkünften für Personen nach § 1 (1) Ziff. 3 - Nebenkostenpauschale 1,92 EUR", "§ 3 Abs. 3 lit. c"),
              _fee("obdach_heizkosten_eur_m2_monat", 1.10, "EUR/m2/Monat",
                   "Ziff. 3 - Nebenkostenpauschale 1,92 EUR - Heizkostenpauschale 1,10 EUR", "§ 3 Abs. 3 lit. c")],
        note="Stadtrecht online (consolidated by the city)"),
    _mu("duisburg_obdach_geb", "05112", "NW", "Duisburg",
        "https://www.duisburg.de/rathaus/rathausundpolitik/ortsrecht/S50.02-Obdachlosengebuehrensatzung_01.11.2019.pdf",
        "satzung", "obdach_gebuehr", "Duisburger Ortsrecht 50.02 Obdachlosengebührensatzung",
        "Satzung über die Erhebung von Gebühren für die Benutzung von städtischen Obdachlosenunterkünften der Stadt Duisburg vom 30.09.2019",
        "2019-09-30", "Der Rat der Stadt hat in seiner Sitzung am 30.09.2019 die nachfolgende Satzung beschlossen", "original",
        "Monthly fee per started m² for municipal homeless shelters, plus heating, water/waste and electricity fees.",
        ["Satzung über die Erhebung von Gebühren für die Benutzung von städtischen Obdachlosenunterkünften der Stadt Duisburg"],
        fees=[_fee("obdach_gebuehr_grund_eur_m2_monat", 5.22, "EUR/m2/Monat",
                   "4. Sonstige Unterkünfte 5,22 € je angefangenem qm/Monat", "§ 3 lit. a Nr. 4"),
              _fee("obdach_heizkosten_eur_m2_monat", 1.13, "EUR/m2/Monat",
                   "b) Die Gebühr für die Heizung beträgt 1,13 € je angefangenem qm/Monat", "§ 3 lit. b"),
              _fee("obdach_nebenkosten_eur_m2_monat", 1.76, "EUR/m2/Monat",
                   "c) Die Gebühr für die Wasserversorgung sowie die gesamte Entsorgung beträgt 1,76 € je angefangenem qm/Monat", "§ 3 lit. c")],
        note="file name says in force 01.11.2019", in_force_from="2019-11-01"),
    _mu("bochum_obdach_geb", "05911", "NW", "Bochum",
        "https://www.bochum.de/c125830c0042ab74/vwcontentbykey/w2amv9nq926bocmde/$file/gebuehrensatzung_wohnunterkuenfte.pdf",
        "satzung", "obdach,obdach_gebuehr", "Gebührensatzung Wohnunterkünfte Bochum",
        "Satzung über die Gebührenerhebung für die Benutzung der Wohnunterkünfte der Stadt Bochum von Aussiedlern, "
        "Flüchtlingen, Zuwanderern sowie von Obdach-/Wohnungslosigkeit betroffenen Personen (Gebührensatzung Wohnunterkünfte) vom 23. Mai 2017",
        "2025-12-18", "In der Fassung der Zweiten Änderungssatzung zur Gebührensatzung Wohnunterkünfte vom 18. Dezember 2025",
        "consolidated",
        "Municipal housing units for homeless persons (OBG) and refugees as public institutions; right to be housed "
        "for those who cannot find housing, no claim to a specific unit; flat monthly fee per user including all "
        "running costs, reduced by income steps.",
        ["Gebührensatzung Wohnunterkünfte) vom 23. Mai 2017",
         "Ein Anspruch auf Aufnahme in eine bestimmte Wohnunterkunft oder auf ein weiteres Verbleiben in einer bestimmten Wohnunterkunft besteht nicht"],
        fees=[_fee("obdach_gebuehr_eur_person_monat", 370.00, "EUR/Person/Monat",
                   "(2) Die Höhe der Benutzungsgebühr beträgt 370,00 € monatlich pro Nutzerin/Nutzer", "§ 7 Abs. 2", 2026)],
        note="consolidated by the city (Fassung der 2. Änderungssatzung)"),
    _mu("wuppertal_obdach_geb", "05124", "NW", "Wuppertal",
        "https://www.wuppertal.de/rathaus-buergerservice/verwaltung/politik/stadtrecht-dokumente/5-11.pdf",
        "satzung", "obdach_gebuehr", "Wuppertaler Stadtrecht 5-11 Gebührensatzung Übergangs- und Obdachloseneinrichtungen",
        "Satzung über die Erhebung von Gebühren für die Benutzung von Übergangseinrichtungen für ausländische "
        "Flüchtlinge und Aussiedler sowie von Obdachloseneinrichtungen der Stadt Wuppertal vom 20.05.2010",
        "2025-07-11", "7. Änderung vom 11.07.2025, „Der Stadtbote“ Nr. 25/2025 vom 30.07.2025", "consolidated",
        "Monthly fees for homeless facilities per m² or per bed place (tariff annex to § 3 Abs. 4).",
        ["Gebührensatzung Übergangseinrichtungen und Obdachloseneinrichtungen vom 20.05.2010",
         "Gebührentarif zu § 3 Abs. 4 der Satzung über die Erhebung von Gebühren für die Benutzung von Übergangseinrichtungen"],
        fees=[_fee("obdach_gebuehr_eur_m2_monat", 9.32, "EUR/m2/Monat", "Obdachloseneinrichtungen 9,32 427,04", "Anlage Gebührentarif", 2025),
              _fee("obdach_gebuehr_eur_bettplatz_monat", 427.04, "EUR/Bettplatz/Monat", "Obdachloseneinrichtungen 9,32 427,04", "Anlage Gebührentarif", 2025)],
        note="city consolidation, valid from 01.08.2025 (heading is letter-spaced in the PDF, so not used as needle)",
        in_force_from="2025-08-01"),
    _mu("bielefeld_obdach", "05711", "NW", "Bielefeld",
        "https://www.bielefeld.de/sites/default/files/datei/2024/III-4_0224.pdf",
        "satzung", "obdach,obdach_gebuehr", "Bielefelder Ortsrecht III-4",
        "Benutzungs- und Gebührensatzung der Stadt Bielefeld für städtische Unterkünfte für Flüchtlinge und Obdachlose",
        "2024-02-01", "Diese Satzung tritt am 01.02.2024 in Kraft", "original",
        "Use and fee statute for municipal accommodation of refugees and homeless persons: fee per head and day for "
        "transitional hostels and transitional flats, plus electricity and heating flat rates; replaces the 2015 "
        "statute on accommodation for homeless persons.",
        ["Benutzungs- und Gebührensatzung der Stadt Bielefeld für städtische Unterkünfte für Flüchtlinge und Obdachlose"],
        fees=[_fee("obdach_gebuehr_eur_person_tag__uebergangswohnheim", 11.16, "EUR/Person/Tag",
                   "(2) Die Benutzungsgebühr beträgt pro Kopf und Tag 11,16 Euro für Übergangswohnheime", "§ 4 Abs. 2"),
              _fee("obdach_gebuehr_eur_person_tag__uebergangswohnung", 7.29, "EUR/Person/Tag",
                   "11,16 Euro für Übergangswohnheime und 7,29 Euro für Übergangswohnungen", "§ 4 Abs. 2")],
        in_force_from="2024-02-01"),
    _mu("bonn_obdach_geb", "05314", "NW", "Bonn",
        "https://www.bonn.de/service-bieten/stadtpolitik-ortsrecht/ortsrecht/recht-sicherheit/gebuehrenordnung-fuer-die-benutzung-der-obdachlosenunterkuenfte.php?loc=de",
        "satzung", "obdach_gebuehr", "Bonner Ortsrecht 32-04-1",
        "Gebührenordnung für die Benutzung der Obdachlosenunterkünfte in der Bundesstadt Bonn Vom 16. Dezember 1970",
        "2021-07-28", "28.07.2021 (ABl. S. 798) 29.07.2021 § 2", "consolidated",
        "Monthly fees per m² of floor space for each municipal homeless shelter, plus running-cost charges set "
        "annually from the previous year's accounts.",
        ["Gebührenordnung für die Benutzung der Obdachlosenunterkünfte in der Bundesstadt Bonn",
         "(1) Die Gebühren betragen monatlich je qm Wohnfläche für die Unterkunft"],
        fees=[_fee("obdach_gebuehr_eur_m2_monat", 4.86, "EUR/m2/Monat", "5. Rhenusallee 1 4,86 Euro", "§ 2 Abs. 1 Nr. 5", 2021)],
        note="city consolidation with amendment list; a merged statute from 2027 is adopted but not yet in force",
        in_force_from="2021-07-29"),
    _mu("muenster_obdach_geb", "05515", "NW", "Münster",
        "https://www.stadt-muenster.de/recht/ortsrecht/satzungen/detailansicht/satzungsnummer/50.01",
        "satzung", "obdach,obdach_gebuehr", "Münsteraner Ortsrecht 50.01",
        "Satzung für die Benutzung der städtischen Übergangseinrichtungen für Flüchtlinge und Wohnungslose der Stadt Münster vom 17.02.2023",
        "2023-04-01", "Diese Satzung tritt am 01.04.2023 in Kraft", "original",
        "Use and fee statute for municipal transitional accommodation of refugees and homeless persons: monthly base "
        "fee per user (base rent per m² x 12 m²) plus a consumption fee.",
        ["Satzung für die Benutzung der städtischen Übergangseinrichtungen für Flüchtlinge und Wohnungslose der Stadt Münster 50.01 vom 17.02.2023 (Amtsblatt der Stadt Münster 2023 Nr. 4 S. 30)"],
        fees=[_fee("obdach_gebuehr_eur_person_monat__grund", 136.20, "EUR/Person/Monat", "Basismiete x 12 qm 136,20 €", "Anlage Gebührenkalkulation", 2023),
              _fee("obdach_gebuehr_eur_person_monat__verbrauch", 63.93, "EUR/Person/Monat", "Je Nutzer/Monat 63,93 €", "Anlage Gebührenkalkulation", 2023),
              _fee("obdach_gebuehr_eur_person_monat", 200.13, "EUR/Person/Monat", "Gesamtgebühr (Grund- und Verbrauchsgebühr) 200,13 €", "Anlage Gebührenkalkulation", 2023)],
        in_force_from="2023-04-01"),
    _mu("krefeld_obdach", "05114", "NW", "Krefeld",
        "https://service.krefeld.de/system/files/2024-05/3.40-satzung_der_stadt-krefeld_ueber_die_benutzung_von_obdachlosenunterkuenften.pdf",
        "satzung", "obdach,obdach_gebuehr", "Krefelder Ortsrecht 3.40",
        "Satzung der Stadt Krefeld über die Benutzung von Obdachlosenunterkünften vom 10.12.2010",
        "2011-01-01", "Die Satzung tritt am 01.01.2011 in Kraft", "original",
        "Municipal homeless shelters for temporary and makeshift housing as non-legal public institutions; "
        "admission by the Fachbereich; fee tariff with base fees per m² per shelter plus running costs.",
        ["Satzung der Stadt Krefeld über die Benutzung von Obdachlosenunterkünften vom 10.12.2010 (Krefelder Amtsblatt Nr. 51 vom 23.12.2010, S. 315-317)",
         "Zur vorübergehenden und notdürftigen Unterbringung Obdachloser unterhält die Stadt Krefeld im Stadtgebiet Obdachlosenunterkünfte"],
        fees=[_fee("obdach_grundgebuehr_eur_m2", 2.90, "EUR/m2", "Nauenweg 24 2,90", "Gebührentarif Nr. 3", 2011)],
        note="text as published on the city's Ortsrecht page (2010 statute; later amendments, if any, not shown)",
        in_force_from="2011-01-01"),
    # ---- batch 2 (BY, BW) ----
    _mu("muenchen_notquartiere", "09162", "BY", "München",
        "https://stadt.muenchen.de/rathaus/stadtrecht/vorschrift/852.pdf",
        "satzung", "obdach", "Münchner Stadtrecht 852 Notquartiere-Benutzungssatzung",
        "Satzung über die Benutzung der Notquartiere der Landeshauptstadt München (Notquartiere-Benutzungssatzung) vom 16. Dezember 2003",
        "2014-04-15", "Änderungen: 17.12.2010 (MüABl. S. 449) 03.04.2013 (MüABl. S. 161) 15.04.2014 (MüABl. S. 449)", "consolidated",
        "Use statute for the city's emergency quarters (furnished bed places) for homeless persons or persons "
        "threatened with homelessness as public institutions.",
        ["Satzung über die Benutzung der Notquartiere der Landeshauptstadt München (Notquartiere-Benutzungssatzung) vom 16. Dezember 2003",
         "Diese Satzung regelt die Benutzung der städtischen Notquartiere"],
        note="Stadtrecht print with amendment list"),
    _mu("muenchen_notquartiere_geb", "09162", "BY", "München",
        "https://stadt.muenchen.de/rathaus/stadtrecht/vorschrift/853.pdf",
        "satzung", "obdach_gebuehr", "Münchner Stadtrecht 853 Notquartiere-Gebührensatzung",
        "Satzung über die Gebühren für die Benutzung der Notquartiere der Landeshauptstadt München (Notquartiere-Gebührensatzung) vom 16. Dezember 2003",
        "2018-01-01", "Notquartiere-GebührenS 853 Stand: 01.01.2018", "consolidated",
        "Daily fee per bed place in the city's emergency quarters by room type (all-inclusive: water, electricity, "
        "heating, furniture); 15 % less for multi-bed and simpler rooms.",
        ["Satzung über die Gebühren für die Benutzung der Notquartiere der Landeshauptstadt München (Notquartiere-Gebührensatzung) vom 16. Dezember 2003",
         "Änderungen: 15.04.2014 (MüABl. S. 450) 13.12.2017 (MüABl. S. 546)"],
        fees=[_fee("obdach_gebuehr_eur_bettplatz_tag__einzelzimmer_bad", 14.41, "EUR/Bettplatz/Tag",
                   "14,41 Euro", "§ 4 Tagesgebühr lit. a", 2018),
              _fee("obdach_gebuehr_eur_bettplatz_tag__zweibett_gemeinschaftsbad", 11.11, "EUR/Bettplatz/Tag",
                   "11,11 Euro", "§ 4 Tagesgebühr lit. d", 2018)],
        note="Stadtrecht print, Stand 01.01.2018; fee table is multi-column, so quotes are the cell values"),
    _mu("stuttgart_obdach", "08111", "BW", "Stuttgart",
        "https://www.stuttgart.de/medien/ibs/4-12.pdf",
        "satzung", "obdach,obdach_gebuehr", "Stuttgarter Stadtrecht 4/12",
        "Satzung über die Benutzung von Unterkünften des Sozialamts für Wohnungslose vom 17. Oktober 2019",
        "2019-12", "Stuttgarter Stadtrecht 22. Erg.-Lfg. (Dezember 2019)", "consolidated",
        "Use and fee statute for the social office's accommodation for homeless persons (flats and hostels); "
        "public-law use relationship; monthly fee per m² with a reduced rate for self-payers on request.",
        ["Bekannt gemacht im Amtsblatt der Landeshauptstadt Stuttgart Nr. 43 vom 24. Oktober 2019",
         "4/12 Satzung über die Benutzung von Unterkünften des Sozialamts für Wohnungslose",
         "Das Benutzungsverhältnis ist öffentlich-rechtlich"],
        fees=[_fee("obdach_gebuehr_eur_m2_monat__wohnung", 15.23, "EUR/m2/Monat",
                   "in den Wohnungen nach § 1 Abs. 4 Satz 2 15,23 EUR/qm", "Gebührenregelung Abs. 2 Nr. 1", 2019),
              _fee("obdach_gebuehr_eur_m2_monat__wohnheim", 10.52, "EUR/m2/Monat",
                   "in Wohnheimen nach § 1 Abs. 4 Satz 3 10,52 EUR/qm", "Gebührenregelung Abs. 2 Nr. 1", 2019)],
        note="Stadtrecht loose-leaf print (22. Ergänzungslieferung)"),
    _mu("leipzig_obdach", "14713", "SN", "Leipzig",
        "https://www.leipzig.de/service-portal/satzungen/details/satzung/5-08/download",
        "satzung", "obdach,obdach_gebuehr", "Leipziger Satzung 5-08 Benutzungs- und Gebührensatzung",
        "Satzung über die Benutzung und die Gebühren in Unterkünften für Wohnungslose, Asylbewerber und "
        "Spätaussiedler sowie andere ausländische Personen in Leipzig (Benutzungs- und Gebührensatzung)",
        "2025-07-01", "(1) Diese Satzung tritt am 01.07.2025 in Kraft", "original",
        "Use and fee statute for municipal accommodation of homeless persons, asylum seekers and others; a place "
        "in a communal shelter for homeless persons costs a fee per person and night.",
        ["Satzung über die Benutzung und die Gebühren in Unterkünften für Wohnungslose, Asylbewerber und Spätaussiedler sowie andere ausländische Personen in Leipzig (Benutzungs- und Gebührensatzung)"],
        fees=[_fee("obdach_gebuehr_eur_person_nacht__gemeinschaftsunterkunft", 5.00, "EUR/Person/Nacht",
                   "Gemeinschaftsunterkunft für Wohnungslose Personen gem. § 1 5,00 Euro", "Gebührenverzeichnis", 2025)],
        in_force_from="2025-07-01"),
    _mu("dresden_obdach", "14612", "SN", "Dresden",
        "https://www.dresden.de/media/pdf/satzungen/satzung-unterbringung.pdf",
        "satzung", "obdach,obdach_gebuehr", "Dresdner Ortsrecht 5.8 Unterbringungssatzung",
        "Satzung der Landeshauptstadt Dresden für die Unterbringung besonderer Bedarfsgruppen (5.8 Unterbringungssatzung) vom 10. April 2025",
        "2025-04-24", "Veröffentlicht im Dresdner Amtsblatt Nr. e35-04-2025 vom 24. April 2025", "original",
        "Accommodation of special need groups incl. involuntarily homeless persons (§§ 2, 12 SächsPBG) in "
        "transitional hostels, guarantee flats and other units; fees per person and month by type of unit.",
        ["(5.8 Unterbringungssatzung) vom 10. April 2025",
         "der Personenkreis, der unfreiwillig wohnungslos ist und daher gemäß §§ 2, 12 des Sächsischen Polizeibehördengesetzes"],
        fees=[_fee("obdach_gebuehr_eur_person_monat__uebergangswohnheim", 1104.03, "EUR/Person/Monat",
                   "1.1 Nutzung von Unterbringungseinrichtungen nach § 3 1.104,03 EUR", "Anlage 2 Gebührenverzeichnis Nr. 1.1", 2025),
              _fee("obdach_gebuehr_eur_person_monat__gewaehrleistungswohnung", 431.90, "EUR/Person/Monat",
                   "Nutzung von Unterbringungseinrichtungen nach §§ 4, 431,90 EUR", "Anlage 2 Gebührenverzeichnis Nr. 1.2", 2025)],
        note="fee row 1.x = persons under § 1 Abs. 2 lit. a (involuntarily homeless)", in_force_from="2025-04-25"),
    _mu("karlsruhe_obdach", "08212", "BW", "Karlsruhe",
        "https://www.karlsruhe.de/fileadmin/user_upload/01_Stadt_Rathaus/013_Verwaltung_und_Stadtpolitik/Stadtrecht/4_Soziale_Sicherung/4-2_Obdachlosenunterkuenfte.pdf",
        "satzung", "obdach,obdach_gebuehr", "Karlsruher Stadtrecht 4/2",
        "Satzung der Stadt Karlsruhe über die Unterhaltung von Obdachlosenunterkünften vom 26. Oktober 1993",
        "2024-06-18", "zuletzt geändert durch Satzung vom 18. Juni 2024 (Online-Bekanntmachung vom 27. Juni 2024)", "consolidated",
        "Municipal homeless shelters with a house-rules annex; monthly fee per place (single room, multi-bed room), "
        "reduced per further person for SGB/AsylbLG households, family cap.",
        ["Satzung der Stadt Karlsruhe über die Unterhaltung von Obdachlosenunterkünften vom 26. Oktober 1993 (Amtsblatt vom 5. November 1993)"],
        fees=[_fee("obdach_gebuehr_eur_platz_monat__einzelzimmer", 500, "EUR/Platz/Monat", "1. für ein Einzelzimmer 500 Euro", "§ 3 Abs. 2 Nr. 1", 2024),
              _fee("obdach_gebuehr_eur_person_monat__mehrbettzimmer", 400, "EUR/Person/Monat", "2. für ein Mehrbettzimmer 400 Euro pro Person", "§ 3 Abs. 2 Nr. 2", 2024)],
        in_force_from="2024-07-01"),
    _mu("mannheim_obdach_geb", "08222", "BW", "Mannheim",
        "https://www.mannheim.de/sites/default/files/page/2841/s05-03_102012.pdf",
        "satzung", "obdach_gebuehr", "Mannheimer Stadtrecht 5.03",
        "Gebührensatzung für die Unterkünfte der Wohnungslosenhilfe der Stadt Mannheim",
        "2012-09-01", "Inkrafttreten am 01.09.2012 (Amtsblatt Nr. 41 v. 10.10.2012)", "original",
        "Fees for the homeless-aid accommodation: per person and month per self-occupied m² (all-inclusive), and a "
        "daily rate in the emergency overnight shelter including supper, bed and breakfast.",
        ["Stadtrecht der Stadt Mannheim 5.03 Gebührensatzung für die Unterkünfte der Wohnungslosenhilfe der Stadt Mannheim"],
        fees=[_fee("obdach_gebuehr_eur_m2_person_monat", 16.00, "EUR/m2/Person/Monat",
                   "je Person und Monat pro selbstbewohntem Quadratmeter 16,00 €", "§ 7 Abs. 1", 2012),
              _fee("obdach_notuebernachtung_eur_person_tag", 21.00, "EUR/Person/Tag",
                   "(3) Für die Notübernachtungsstelle sind je Person und Tag für Nachtessen, Übernachtung und Frühstück 21,00 € zu entrichten", "§ 7 Abs. 3", 2012)],
        in_force_from="2012-09-01"),
    _mu("augsburg_obdach", "09761", "BY", "Augsburg",
        "https://www.augsburg.de/fileadmin/user_upload/buergerservice_rathaus/rathaus/stadtrecht/pdf/50/5000.pdf",
        "satzung", "obdach", "Augsburger Stadtrecht 5000 Obdachlosenunterbringungssatzung",
        "Satzung über die Obdachlosenunterbringung in Augsburg (Obdachlosenunterbringungssatzung) vom 18.04.2019",
        "2019-05-03", "(Obdachlosenunterbringungssatzung) vom 18.04.2019 (ABl. vom 03.05.2019, S. 142)", "original",
        "Use statute for the city's homeless shelters (hostels and flats) as public institutions.",
        ["SATZUNG ÜBER DIE OBDACHLOSENUNTERBRINGUNG IN AUGSBURG",
         "Diese Satzung regelt die Benutzung der städtischen Obdachlosenunterunterkünfte"]),
    _mu("augsburg_obdach_geb", "09761", "BY", "Augsburg",
        "https://www.augsburg.de/fileadmin/user_upload/buergerservice_rathaus/rathaus/stadtrecht/pdf/50/5001.pdf",
        "satzung", "obdach_gebuehr", "Augsburger Stadtrecht 5001 Obdachlosengebührensatzung",
        "Satzung über die Erhebung von Gebühren für Obdachlosenwohngelegenheiten in Augsburg (Obdachlosengebührensatzung) vom 18.12.2024",
        "2025-02-01", "Die Satzung tritt zum 01.02.2025 in Kraft", "original",
        "Fees for homeless transitional hostels per person and month and for transitional flats per m² and month.",
        ["SATZUNG ÜBER DIE ERHEBUNG VON GEBÜHREN FÜR OBDACHLOSENWOHNGELEGENHEITEN IN AUGSBURG (OBDACHLOSENGEBÜHRENSATZUNG) vom 18.12.2024 (ABl. vom 31.01.2025, S. 19)"],
        fees=[_fee("obdach_gebuehr_eur_person_monat__uebergangswohnheim", 330.00, "EUR/Person/Monat",
                   "beträgt die Gebühr je Person und Monat 330,00 Euro", "§ 2 Abs. 2", 2025),
              _fee("obdach_gebuehr_eur_m2_monat__uebergangswohnung", 13.27, "EUR/m2/Monat",
                   "beträgt die Gebühr je qm und Monat 13,27 Euro", "§ 2 Abs. 3", 2025)],
        in_force_from="2025-02-01"),
    _mu("freiburg_obdach", "08311", "BW", "Freiburg im Breisgau",
        "https://www.freiburg.de/pb/site/Freiburg/get/documents_E1329572864/freiburg/daten/ortsrecht/21%20Soziales%20und%20Jugendhilfe/OrtsR_21_01.pdf",
        "satzung", "obdach,obdach_gebuehr", "Ortsrecht Freiburg 21.1",
        "Satzung der Stadt Freiburg i. Br. über die Benutzung und über die Erhebung von Gebühren der Unterkünfte der Stadt Freiburg i. Br. für wohnungslose Personen vom 28. November 2017",
        "2024-01-01", "Die Änderungssatzung vom 24.10.2023 ist öffentlich bekanntgemacht am 25.11.2023 und am 01.01.2024 in Kraft getreten", "consolidated",
        "Combined use and fee statute for emergency shelters, hostels and flats for homeless people: fee per person "
        "and night in emergency shelters; monthly standard fees in hostels (single / shared room); flats by floor area.",
        ["über die Benutzung und über die Erhebung von Gebühren der Unterkünfte der Stadt Freiburg i. Br. für wohnungslose Personen vom 28. November 2017 in der Fassung der Satzungen vom 20. Oktober 2020 und vom 24. Oktober 2023"],
        fees=[_fee("obdach_notunterkunft_eur_person_nacht", 10.00, "EUR/Person/Nacht",
                   "Für Notunterkünfte beträgt die Gebühr: 1. je Person und Übernachtung 10,00 EUR", "§ 17 Nr. 1", 2024),
              _fee("obdach_gebuehr_eur_person_monat__wohnheim_einzelzimmer", 600.00, "EUR/Person/Monat",
                   "Einzelzimmer 600,00 EUR", "§ 18 Abs. 2", 2024),
              _fee("obdach_gebuehr_eur_person_monat__wohnheim_mehrbettzimmer", 420.00, "EUR/Person/Monat",
                   "Einzelperson Mehrbettzimmer 420,00 EUR", "§ 18 Abs. 2", 2024)],
        note="consolidated reading copy incl. amendments of 20.10.2020 and 24.10.2023"),
    _mu("braunschweig_obdach_geb", "03101", "NI", "Braunschweig",
        "https://www.braunschweig.de/politik_verwaltung/politik/stadtrecht/5_02_Gebuehrensatzung_Wohnungslose.pdf",
        "satzung", "obdach_gebuehr", "Braunschweiger Stadtrecht 5.02 Gebührensatzung Wohnungslosenunterbringung",
        "Satzung über die Erhebung von Gebühren für die vorübergehende Unterbringung von wohnungslosen Personen in den Unterkünften für Wohnungslose und in Übergangswohnheimen in der Stadt Braunschweig (Gebührensatzung Wohnungslosenunterbringung)",
        "2005-01-01", "Die Satzung tritt am 1. Januar 2005 in Kraft", "original",
        "Daily fee per person in shared and decentralised homeless accommodation; monthly fee per m² in assisted "
        "living and the transitional hostel.",
        ["(Gebührensatzung Wohnungslosenunterbringung)",
         "Die Satzung tritt am 1. Januar 2005 in Kraft"],
        fees=[_fee("obdach_gebuehr_eur_person_tag__gemeinschaftsunterkunft", 10.00, "EUR/Person/Tag",
                   "für die Unterbringung in Gemeinschaftsunterkünften pro Person 10,00 € täglich", "§ 5 Abs. 1 Nr. 1", 2005),
              _fee("obdach_gebuehr_eur_person_tag__dezentral", 9.00, "EUR/Person/Tag",
                   "für die dezentrale Unterbringung pro Person 9,00 € täglich", "§ 5 Abs. 1 Nr. 3", 2005),
              _fee("obdach_gebuehr_eur_m2_monat__uebergangswohnheim", 12.50, "EUR/m2/Monat",
                   "für die Unterbringung im Übergangswohnheim monatlich 12,50 €", "§ 5 Abs. 1 Nr. 4", 2005)],
        note="text as published in the city's Stadtrecht (signed 27.12.2004); no later amendment shown there",
        in_force_from="2005-01-01"),
    _mu("mainz_obdach", "07315", "RP", "Mainz",
        "https://www.mainz.de/verzeichnisse/ortsrecht/satzung-der-landeshauptstadt-mainz-ueber-die-nutzung-der-staedtischen-unterkuenfte-fuer-die-unterbringung-obdachloser-menschen-vom-1.7.2025.php.media/168157/satzung-ueber-nutzung-der-staedtischen-Unterkuenfte-fuer-Unterbringung-obdachloser-Menschen-vom-1-7-2025.pdf",
        "satzung", "obdach,obdach_gebuehr", "Ortsrecht Mainz: Unterkunftssatzung obdachlose Menschen vom 01.07.2025",
        "Satzung der Landeshauptstadt Mainz über die Nutzung der städtischen Unterkünfte für die Unterbringung obdachloser Menschen vom 01.07.2025",
        "2025-07-01", "Diese Satzung tritt am 01.07.2025 in Kraft", "original",
        "Use and fee statute for municipal homeless shelters; daily fee per person from 1.60 EUR (emergency bed / "
        "night room) up to 11.20 EUR (Unterkunft Plus); monthly fee is a multiple of the daily rate.",
        ["Satzung der Landeshauptstadt Mainz über die Nutzung der städtischen Unterkünfte für die Unterbringung obdachloser Menschen vom 01.07.2025"],
        fees=[_fee("obdach_notschlafplatz_eur_person_tag", 1.60, "EUR/Person/Tag",
                   "Notschlafplatz Haus 6411 1,60 Euro", "Anlage zu § 16", 2025),
              _fee("obdach_gebuehr_eur_person_tag__uebergangsunterkunft", 8.00, "EUR/Person/Tag",
                   "Übergangsunterkunft 8,00 Euro", "Anlage zu § 16", 2025),
              _fee("obdach_gebuehr_eur_person_tag__unterkunft_plus", 11.20, "EUR/Person/Tag",
                   "Unterkunft Plus 11,20 Euro", "Anlage zu § 16", 2025)],
        in_force_from="2025-07-01"),
    _mu("magdeburg_obdach_aend1", "15003", "ST", "Magdeburg",
        "https://www.magdeburg.de/loadDocument.phtml?FID=698.15679.1&Ext=PDF",
        "satzung", "obdach_gebuehr", "Amtsblatt Magdeburg Nr. 35/2020, S. 567",
        "1. Änderungssatzung zur Satzung über die Benutzung der Obdachlosenunterkünfte und die Erhebung von Gebühren zu deren Nutzung durch obdachlose Einzelpersonen oder Familien in der Landeshauptstadt Magdeburg (Benutzungs- und Gebührensatzung für Obdachlosenunterkünfte)",
        "2020-12-29", "Amtsblatt der Landeshauptstadt Magdeburg Nr. 35 vom 29. Dezember 2020", "original",
        "Amendment replacing the fee schedule (Anlage zu § 7 Abs. 3) of the 2016 use and fee statute: daily rate "
        "per facility.",
        ["Die bisherige Anlage zu § 7 Abs. 3 der Satzung wird wie folgt neu gefasst: Gebührenverzeichnis"],
        fees=[_fee("obdach_gebuehr_eur_tag__soziale_wohneinrichtung", 23.57, "EUR/Tag",
                   "Gemeinschaftseinrichtung \"Soziale Wohneinrichtung für Frauen, Familien und Männer\" 23,57 EUR", "Anlage zu § 7 Abs. 3", 2020),
              _fee("obdach_gebuehr_eur_tag__gu_muenchenhofstrasse", 16.94, "EUR/Tag",
                   "Gemeinschaftsunterkunft Münchenhofstraße 49 16,94 EUR", "Anlage zu § 7 Abs. 3", 2020),
              _fee("obdach_gebuehr_eur_tag__gu_bahnikstrasse", 18.73, "EUR/Tag",
                   "Gemeinschaftsunterkunft Bahnikstraße 1a 18,73 EUR", "Anlage zu § 7 Abs. 3", 2020)],
        note="base statute Amtsblatt 22/2016 (fee schedule replaced by this amendment)",
        in_force_from="2020-12-30"),
    _mu("halle_obdach", "15002", "ST", "Halle (Saale)",
        "https://halle.de/fileadmin/Binaries/Verwaltung/Stadtpolitik_und_Ortsrecht/Satzungen_und_Verordnungen/GB_IV_Bildung_Soziales/FB_Soziales/SR_502-2_Unterbringung_Obdachloser_und_Gefluechteter.pdf",
        "satzung", "obdach,obdach_gebuehr", "Hallesches Stadtrecht SR 5.02-2",
        "Satzung über die Unterbringung Obdachloser und Geflüchteter in der Stadt Halle (Saale)",
        "2025-10-30", "veröffentlicht im Amtsblatt der Stadt Halle (Saale) Nr. 24 vom 30. Oktober 2025", "original",
        "Use statute for accommodation of homeless people and refugees; replaces the 2002 'Haus der Wohnhilfe' "
        "statute; monthly fees in the Haus der Wohnhilfe by household size.",
        ["SR 5.02-2 Satzung über die Unterbringung Obdachloser und Geflüchteter in der Stadt Halle (Saale)"],
        fees=[_fee("obdach_gebuehr_eur_monat__haus_der_wohnhilfe_einzelperson", 294.30, "EUR/Monat",
                   "Monatliche Benutzungsgebühr Einzelperson 294,30 Euro", "Haus der Wohnhilfe, Gebührentabelle", 2025),
              _fee("obdach_gebuehr_eur_monat__haus_der_wohnhilfe_2_personen", 538.80, "EUR/Monat",
                   "2 Personen 538,80 Euro", "Haus der Wohnhilfe, Gebührentabelle", 2025),
              _fee("obdach_gebuehr_eur_monat__haus_der_wohnhilfe_je_weitere_person", 106.10, "EUR/Monat",
                   "jede weitere Person 106,10 Euro", "Haus der Wohnhilfe, Gebührentabelle", 2025)],
        in_force_from="2025-10-31"),
    _mu("erfurt_obdach", "16051", "TH", "Erfurt",
        "https://www.erfurt.de/mam/ef/rathaus/stadtrecht/5/5067.pdf",
        "satzung", "obdach", "Erfurter Stadtrecht 5.067 Unterbringungssatzung vom 12.07.2017",
        "Satzung über die Benutzung von öffentlichen Einrichtungen bei der Unterbringung besonderer Bedarfsgruppen in der Landeshauptstadt Erfurt (Unterbringungssatzung)",
        "2017-08-18", "Veröffentlicht im Amtsblatt der Stadt Erfurt am 18. August 2017", "original",
        "Use statute for municipal accommodation of 'special needs groups', expressly including involuntarily "
        "homeless people placed under the Thuringian OBG (§ 1 Abs. 2 lit. a); replaced the 2010 "
        "Obdachlosenunterkunftssatzung. Fees are in a separate Unterbringungsgebührensatzung (not archived).",
        ["der Personenkreis, der unfreiwillig wohnungslos ist und daher gemäß §§ 1, 4, 5 und 54 des Thüringer Gesetzes über die Aufgaben und Befugnisse der Ordnungsbehörden"],
        in_force_from="2017-08-19"),
    _mu("hagen_obdach_geb", "05914", "NW", "Hagen",
        "https://www.hagen.de/dateien/aus-dem-rathaus/politik-und-gremien/stadtrecht/f/225601-gebuehrenordnung-fluechtlinge-aussiedler-und-obdachlose.pdf",
        "satzung", "obdach_gebuehr", "Hagener Stadtrecht 22.56.01",
        "Satzung vom 20.12.2023 über die Erhebung von Gebühren für die Unterbringung von Flüchtlingen, Aussiedler*innen und Obdachlosen in der Stadt Hagen",
        "2024-01-01", "Diese Satzung tritt am 01.01.2024 in Kraft", "original",
        "Fees for municipal accommodation of refugees, resettlers and homeless people: per m² and month in flats, "
        "per person and month in shared facilities, and the men's shelter (Männerasyl) per night incl. meals.",
        ["22.56.01 Satzung vom 20.12.2023 über die Erhebung von Gebühren für die Unterbringung von Flüchtlingen, Aussiedler*innen und Obdachlosen in der Stadt Hagen"],
        fees=[_fee("obdach_gebuehr_eur_m2_monat__wohnung", 7.79, "EUR/m2/Monat",
                   "in einer Wohnung 7,79 € je Quadratmeter Wohnfläche", "Gebührentarif III a", 2024),
              _fee("obdach_gebuehr_eur_person_monat__gemeinschaftseinrichtung", 218.31, "EUR/Person/Monat",
                   "in einer Gemeinschaftseinrichtung 218,31 € für jede untergebrachte Person", "Gebührentarif III b", 2024),
              _fee("obdach_notuebernachtung_eur_person_nacht__maennerasyl", 11.30, "EUR/Person/Nacht",
                   "eine Gebühr in Höhe von 11,30 € pro Übernachtung an", "Gebührentarif III c", 2024)],
        in_force_from="2024-01-01"),
    _mu("heidelberg_obdach", "08221", "BW", "Heidelberg",
        "https://www.heidelberg.de/site/Heidelberg2021/get/documents_E810693811/heidelberg/Objektdatenbank/30/PDF/30_pdf_ortsr_5-10_Obdachlosenunterkunftssatzung.pdf",
        "satzung", "obdach,obdach_gebuehr", "Heidelberger Ortsrecht 5.10 Obdachlosenunterkunftssatzung (OUS)",
        "Satzung über die Benutzung von Obdachlosenunterkünften (Obdachlosenunterkunftssatzung - OUS) vom 01. Juli 2010",
        "2024-11-06", "Satzung vom 17. Oktober 2024 (Heidelberger Stadtblatt vom 06.11.2024)", "consolidated",
        "Use and fee statute for homeless shelters and follow-up refugee housing: monthly fees per m² by type of "
        "accommodation, higher for recipients of SGB II/XII/AsylbLG benefits than for self-payers.",
        ["Satzung über die Benutzung von Obdachlosenunterkünften (Obdachlosenunterkunftssatzung - OUS) vom 01. Juli 2010 (Heidelberger Stadtblatt vom 07. Juli 2010)"],
        fees=[_fee("obdach_gebuehr_eur_m2_monat__gemeinschaftsunterkunft_leistungsbezug", 13.43, "EUR/m2/Monat",
                   "13,43 € / qm", "§ 13 Abs. 2 Nr. 1 lit. a", 2024),
              _fee("obdach_gebuehr_eur_m2_monat__gemeinschaftsunterkunft_selbstzahler", 12.09, "EUR/m2/Monat",
                   "12,09 € / qm", "§ 13 Abs. 2 Nr. 2 lit. a", 2024)],
        note="consolidated text incl. amendments of 05.06.2014, 08.10.2020 and 17.10.2024; new rates from 01.01.2027 are in council (Drs. 0226/2026/BV), not yet promulgated"),
    _mu("herne_obdach_geb", "05916", "NW", "Herne",
        "https://www.herne.de/PDF/Ortsrecht/3-Rechts-Sicherheits-und-Ordnungsrecht/3_14.pdf.pdf",
        "satzung", "obdach_gebuehr", "Herner Ortsrecht 3.14",
        "Gebührensatzung für die Obdachlosenunterkünfte und das Obdachlosenasyl der Stadt Herne vom 08.04.2010",
        "2010-04-22", "Die öffentliche Bekanntmachung erfolgte in den Herner Ausgaben der WAZ am 22.04.2010", "original",
        "Flat monthly fee for people placed by police order in the Buschkampstraße shelters (incl. running and energy "
        "costs) and a nightly fee per person in the homeless night shelter (Obdachlosenasyl).",
        ["Gebührensatzung für die Obdachlosenunterkünfte und das Obdachlosenasyl der Stadt Herne vom 08.04.2010"],
        fees=[_fee("obdach_gebuehr_eur_person_monat__pauschal", 95, "EUR/Person/Monat",
                   "beträgt pauschal 95 € monatlich für durch Ordnungsver", "§ 2 Abs. 1", 2010),
              _fee("obdach_notuebernachtung_eur_person_nacht", 2, "EUR/Person/Nacht",
                   "Die Gebühr für die Benutzung des Obdachlosenasyls beträgt pro Nacht und Person 2 €", "§ 2 Abs. 2", 2010)],
        in_force_from="2010-04-23"),
    _mu("leverkusen_obdach_geb", "05316", "NW", "Leverkusen",
        "https://www.leverkusen.de/service/veroeffentlichungen/satzungen-verordnungen/dez-3/3502-Gebuehrensatzung-Fluechtlingsunterkuenfte.pdf",
        "satzung", "obdach_gebuehr", "Leverkusener Ortsrecht 3/50/2",
        "Satzung über die Erhebung von Nutzungsgebühren für die vorläufige Unterbringung von ausländischen Flüchtlingen, (Spät-)Aussiedlern und Obdachlosen in von der Stadt Leverkusen betriebenen Unterkünften vom 17. Dezember 2025",
        "2026-01-01", "Diese Satzung tritt am 01.01.2026 in Kraft", "original",
        "Monthly fees by household size (incl. electricity flat rate) for municipal accommodation of refugees, "
        "resettlers and homeless people; capped from 10 persons.",
        ["Satzung über die Erhebung von Nutzungsgebühren für die vorläufige Unterbringung von ausländischen Flüchtlingen, (Spät-)Aussiedlern und Obdachlosen in von der Stadt Leverkusen betriebenen Unterkünften vom 17. Dezember 2025"],
        fees=[_fee("obdach_gebuehr_eur_monat__1_person_inkl_strom", 546, "EUR/Monat",
                   "546,00 €", "Anlage Gebührentabelle, 1 Person", 2026),
              _fee("obdach_gebuehr_eur_monat__deckel_ab_10_personen", 1845, "EUR/Monat",
                   "Ab 10 Personen ist die Benutzungsgebühr auf 1.845,00 € gedeckelt", "Anlage Nr. 2", 2026)],
        in_force_from="2026-01-01"),
    _mu("solingen_obdach_geb", "05122", "NW", "Solingen",
        "https://slgn.io/uploads/64_02_26fa893e46.pdf",
        "satzung", "obdach_gebuehr", "Solinger Ortsrecht 64/02",
        "Satzung über die Erhebung von Gebühren zur Benutzung der Obdachlosenunterkünfte der Klingenstadt Solingen",
        "2025-12-19", "(in der Fassung der V. Änderungssatzung vom 19.12.2025)", "consolidated",
        "Monthly fees per m² for the named homeless shelters (base fee plus flat rates for running costs and "
        "electricity) and for shelter flats (base fee plus running costs).",
        ["Satzung über die Erhebung von Gebühren zur Benutzung der Obdachlosenunterkünfte der Klingenstadt Solingen (in der Fassung der V. Änderungssatzung vom 19.12.2025)"],
        fees=[_fee("obdach_grundgebuehr_eur_m2_monat__unterkunft", 14.66, "EUR/m2/Monat",
                   "14,66 €/qm", "§ 3 Abs. 1", 2026),
              _fee("obdach_grundgebuehr_eur_m2_monat__wohnung", 5.48, "EUR/m2/Monat",
                   "Grundgebühr 5,48 €/qm", "§ 3 Abs. 2", 2026)],
        note="host slgn.io is the city's own document server, linked from solingen.de/inhalt/ortsrecht (Ortsrecht Kapitel 6); base statute in force 01.08.2017"),
    _mu("regensburg_notw_gs", "09362", "BY", "Regensburg",
        "https://www.regensburg.de/stadtrecht/233994/satzung-ueber-die-erhebung-von-gebuehren-fuer-die-benutzung-der-notwohnanlagen-der-stadt-regensburg-notwohnanlagen-gebuehrensatzung-notw-gs-vom-24-oktober-2024.html",
        "satzung", "obdach_gebuehr", "Regensburger Stadtrecht 10.1.2 Notw.-GS",
        "Satzung über die Erhebung von Gebühren für die Benutzung der Notwohnanlagen der Stadt Regensburg (Notwohnanlagen-Gebührensatzung – Notw.-GS) vom 24. Oktober 2024",
        "2024-12-01", "(1) Diese Satzung tritt am 01. Dezember 2024 in Kraft", "original",
        "Fees for emergency flats (Notwohnungen) per m² and month by equipment category (I-III); emergency beds in "
        "shared shelters (Notschlafstellen) are free of charge.",
        ["(Notwohnanlagen-Gebührensatzung – Notw.-GS) vom 24. Oktober 2024 ( AMBl. Nr. 46 vom 11. November 2024 )",
         "Für die Benutzung von Notschlafstellen in Gemeinschaftsunterkünften werden keine Gebühren erhoben"],
        fees=[_fee("obdach_gebuehr_eur_m2_monat__notwohnung_kategorie_i", 7.30, "EUR/m2/Monat",
                   "7,30 Euro", "§ 4 Abs. 1 Gebührensatz je Quadratmeter monatlich, Kategorie I (table cell)", 2024),
              _fee("obdach_gebuehr_eur_m2_monat__notwohnung_kategorie_iii", 10.40, "EUR/m2/Monat",
                   "10,40 Euro", "§ 4 Abs. 1 Gebührensatz je Quadratmeter monatlich, Kategorie III (table cell)", 2024)],
        in_force_from="2024-12-01"),
    _mu("potsdam_obdach_geb", "12054", "BB", "Potsdam",
        "https://www.potsdam.de/system/files/documents/Satzung_Gebuehren_Obdachlosenunterkuenfte.pdf",
        "satzung", "obdach_gebuehr", "Potsdamer Stadtrecht: Gebührensatzung Unterbringung Wohnungsloser vom 21.01.2005",
        "Satzung über die Erhebung von Gebühren für die Benutzung von Einrichtungen zur vorläufigen Unterbringung von wohnungslosen Einzelpersonen oder Familien der Landeshauptstadt Potsdam vom 21.01.05",
        "2005-02-24", "Öffentlich bekannt gemacht am 24. Februar 2005 im Amtsblatt für die Landeshauptsta", "original",
        "Monthly fee per person in the homeless hostel (Obdachlosenheim) and a cap per m² (gross warm rent) in "
        "guarantee flats (Gewährleistungswohnungen).",
        ["Satzung über die Erhebung von Gebühren für die Benutzung von Einrichtungen zur vorläufigen Unterbringung von wohnungslosen Einzelpersonen oder Familien der Landeshauptstadt Potsdam vom 21.01.05"],
        fees=[_fee("obdach_gebuehr_eur_person_monat__obdachlosenheim", 278.62, "EUR/Person/Monat",
                   "für die Unterbringung im Obdachlosenheim 278,62 EURO pro Monat und Person", "§ 5 Abs. 3 lit. a", 2005),
              _fee("obdach_gebuehr_max_eur_m2_monat__gewaehrleistungswohnung", 7.40, "EUR/m2/Monat",
                   "maximal 7,40 EURO Bruttowarmmiete pro qm Wohnfläche", "§ 5 Abs. 3 lit. b", 2005)],
        note="the city states its PDFs are for information; the binding text is the Amtsblatt publication of 24.02.2005",
        in_force_from="2005-02-25"),
    _mu("osnabrueck_gog", "03404", "NI", "Osnabrück",
        "https://demokratisch.osnabrueck.de/fileadmin/demokratisch/Ortsrecht/II_Finanzen/2_Gebuehren_und_Beitraege_/II_2-13.pdf",
        "satzung", "obdach_gebuehr", "Osnabrücker Ortsrecht II 2.13 (GOG), Amtsblatt 2026, S. 50 f.",
        "Satzung der Stadt Osnabrück vom 21. April 2026 über die Erhebung von Gebühren für die Unterbringung obdachloser und geflüchteter Personen in den Unterkünften der Stadt Osnabrück (GOG)",
        "2026-07-01", "Diese Satzung tritt zum 1. Juli 2026 in Kraft", "original",
        "Monthly fees for municipal accommodation of homeless and refugee households by household size, plus an "
        "energy flat rate per person where energy is not billed directly; flat per-person fees in special and "
        "emergency shelters (Notunterkünfte).",
        ["Satzung der Stadt Osnabrück vom 21. April 2026 über die Erhebung von Gebühren für die Unterbringung obdachloser und geflüchteter Personen in den Unterkünften der Stadt Osnabrück (GOG)"],
        fees=[_fee("obdach_gebuehr_eur_monat__einzelperson", 375.49, "EUR/Monat",
                   "Einzelperson 375,49 Euro", "Anlage 1 Gebührenverzeichnis", 2026),
              _fee("obdach_energiekosten_eur_person_monat", 100.25, "EUR/Person/Monat",
                   "Jede Person 100,25 Euro", "Anlage 1 Gebührenverzeichnis", 2026),
              _fee("obdach_notunterkunft_eur_person_monat", 203.57, "EUR/Person/Monat",
                   "Jede Person 203,57 Euro", "Anlage 1 Gebührenverzeichnis (Notunterkünfte)", 2026)],
        in_force_from="2026-07-01"),
    _mu("oldenburg_obdach", "03403", "NI", "Oldenburg (Oldenburg)",
        "https://www.oldenburg.de/fileadmin/oldenburg/Benutzer/Dateien/22_Rechtsamt/3.21_20241125_K_b.pdf",
        "satzung", "obdach,obdach_gebuehr", "Oldenburger Stadtrecht 3.21",
        "Satzung der Stadt Oldenburg (Oldb) über die Unterbringung von Obdachlosen in der Stadt Oldenburg (Oldb)",
        "2024-11-25", "zuletzt geändert durch Satzung vom 25. November 2024, Amtsblatt für die Stadt Oldenburg Nr. 28 vom 13. Dezember 2024", "consolidated",
        "Use and fee statute for homeless accommodation: fee per night in the overnight hostel (Sandweg 26, all "
        "costs included) and monthly fee per m² in the shelter (Sandweg 28, electricity paid by the user). Version "
        "in force since 01.01.2025.",
        ["Die Satzung gilt in dieser Fassung seit dem 1. Januar 2025"],
        fees=[_fee("obdach_notuebernachtung_eur_nacht", 7.50, "EUR/Nacht",
                   "Die Gebühr pro Übernachtung beträgt 7,50 €", "Gebührenregelung Abs. 1", 2025),
              _fee("obdach_gebuehr_eur_m2_monat", 11.00, "EUR/m2/Monat",
                   "Nutzfläche beträgt 11,00 €", "Gebührenregelung Abs. 2", 2025)],
        note="non-official consolidated reading copy published by the city (binding: Amtsblatt)"),
    _mu("heilbronn_obdach", "08121", "BW", "Heilbronn",
        "https://www.heilbronn.de/fileadmin/daten/stadtheilbronn/formulare/rathaus/stadtrecht/1_Oeffentliche_Sicherheit_und_Ordnung/1_5_Satzung_ueber_die_Benutzung_der_Obdachlosenunterkuenfte.pdf",
        "satzung", "obdach,obdach_gebuehr", "Heilbronner Stadtrecht 1/5",
        "Satzung über die Benutzung der Obdachlosenunterkünfte der Stadt Heilbronn vom 25. Juli 1998",
        "2010-01-01", "17.12.09 (Stadtztg. Nr. 26 v. 31.12.09), in Kraft ab 01.01.10", "consolidated",
        "Use and fee statute for homeless shelters: annual fee per m² of living space (plus running-cost advances) "
        "and an annual fee in the municipal homeless hostel for a one-person household plus a supplement per further "
        "person. Last amended 17.12.2009, in force 01.01.2010.",
        ["Satzung über die Benutzung der Obdachlosenunterkünfte der Stadt Heilbronn vom 25. Juli 1998"],
        fees=[_fee("obdach_gebuehr_eur_m2_jahr", 75.30, "EUR/m2/Jahr",
                   "Wohnfläche jährlich 75,30 Euro", "§ 13 Abs. 2", 2010),
              _fee("obdach_gebuehr_eur_jahr__obdachlosenheim_1_person", 4140, "EUR/Jahr",
                   "jährlich für einen Ein-Personenhaushalt 4.140,00 Euro", "§ 13 Abs. 3", 2010)]),
    _mu("trier_obdach", "07211", "RP", "Trier",
        "https://www.trier.de/media/www.trier.de/org/med_3407/8067_satzung_obdachlosenunterkuenfte.pdf",
        "satzung", "obdach,obdach_gebuehr", "Trierer Stadtrecht: Obdachlosen- und Gemeinschaftsunterkünfte-Satzung vom 27.09.2018",
        "Satzung der Stadt Trier über die Benutzung von Obdachlosenunterkünften und Gemeinschaftsunterkünften in der Stadt Trier",
        "2018-09-27", "Trier, den 27.09.2018 gez. Wolfram Leibe, Oberbürgermeister", "original",
        "Use and fee statute for homeless and shared accommodation: monthly flat fee incl. running costs by size "
        "of the household (Bedarfsgemeinschaft), from one person to more than five.",
        ["Satzung der Stadt Trier über die Benutzung von Obdachlosenunterkünften und Gemeinschaftsunterkünften in der Stadt Trier"],
        fees=[_fee("obdach_gebuehr_eur_monat__einzelperson", 320, "EUR/Monat",
                   "a) Einzelpersonen: 320,00 €", "Anlage zu §§ 5 und 15, Abs. 2 lit. a", 2018),
              _fee("obdach_gebuehr_eur_monat__mehr_als_5_personen", 1090, "EUR/Monat",
                   "f) Bedarfsgemeinschaften mit mehr als fünf Personen: 1.090,00 €", "Anlage zu §§ 5 und 15, Abs. 2 lit. f", 2018)]),
    _mu("darmstadt_obdach", "06411", "HE", "Darmstadt",
        "https://www.darmstadt.de/fileadmin/Dateistruktur2024/04_RATHAUS/04_Stadtrecht-Satzungen/Alphabetisches_Sachregister/300_bis_399/376.pdf",
        "satzung", "obdach,obdach_gebuehr", "Darmstädter Stadtrecht 376 Obdachlosenunterkunftssatzung",
        "Satzung für die Benutzung der Obdachlosenunterkünfte der Wissenschaftsstadt Darmstadt – Obdachlosenunterkunftssatzung – Vom 11.11.2011",
        "2019-05-01", "Zuletzt geändert durch Satzung vom 27.03.2019, veröffentlicht im Darmstädter Echo am 04.04.2019, in Kraft getreten am 01.05.2019", "consolidated",
        "Use and fee statute for homeless shelters: monthly fee per person in a shelter, higher in the mother-and-child "
        "unit.",
        ["Satzung für die Benutzung der Obdachlosenunterkünfte der Wissenschaftsstadt Darmstadt – Obdachlosenunterkunftssatzung – Vom 11.11.2011"],
        fees=[_fee("obdach_gebuehr_eur_person_monat", 332.26, "EUR/Person/Monat",
                   "beträgt pro Person 332,26 Euro", "§ 8 Abs. 6", 2019),
              _fee("obdach_gebuehr_eur_person_monat__mutter_kind", 848.36, "EUR/Person/Monat",
                   "beträgt pro Person 848,36 Euro", "§ 8 Abs. 6", 2019)],
        in_force_from="2019-05-01", local="muni_darmstadt_376.pdf",
        note="manual archive via browser, 2026-11-23 (Lead); robots.txt of www.darmstadt.de disallows /fileadmin for all agents, so the file is read from the archive only"),
    _mu("cottbus_obdach_pdf", "12052", "BB", "Cottbus",
        "https://cottbus.de/satzungen/Gebuehrensatzung_fuer_Obdachlosenunterkuenfte_in_Cottbus-2.pdf",
        "satzung", "obdach_gebuehr", "Cottbuser Ortsrecht: Gebührensatzung Obdachlosenunterkünfte (Amtsblatt Nr. 14/2017)",
        "Satzung über die Erhebung von Gebühren für die Nutzung der Obdachlosenunterkünfte in der Stadt Cottbus/Chóśebuz",
        "2018-01-01", "Diese Satzung tritt am 01.01.2018 in Kraft", "original",
        "Daily fee per place in the municipal 'Haus der Wohnhilfe' including electricity, cable, running and heating "
        "costs; city-rented flats charged separately.",
        ["Satzung über die Erhebung von Gebühren für die Nutzung der Obdachlosenunterkünfte in der Stadt Cottbus/Chóśebuz"],
        fees=[_fee("obdach_gebuehr_eur_platz_tag__haus_der_wohnhilfe", 17.33, "EUR/Platz/Tag",
                   "Betriebs- und Heizkosten 17,33 €/Tag", "§ 2 Abs. 1", 2018)],
        note="published in Amtsblatt Nr. 14/2017 of 16.12.2017 per the city's Ortsrecht page",
        in_force_from="2018-01-01"),
    # ---- batch 6 (schema 3: kreisangehörige large cities with explicit Gemeinde AGS, remaining kreisfreie) ----
    _mu("hannover_obdach_geb", "03241", "NI", "Hannover",
        "https://www.hannover.de/content/download/1027435/file/Geb-Obdachl-INTRANET.pdf",
        "satzung", "obdach_gebuehr", "Gebührensatzung Unterbringung (Abl. Hann. 06.10.2024, Nr. 34, S. 221)",
        "Satzung über die Erhebung von Gebühren für die Unterbringung obdachloser und geflüchteter Personen in den Unterkünften der Landeshauptstadt Hannover (Gebührensatzung Unterbringung)",
        "2024-10-06", "Abl. Hann. 06. Oktober 2024, Nr. 34, S. 221", "original",
        "Monthly fee by household size for all municipal accommodation (Notunterkünfte, Wohnheime, Wohnprojekte, "
        "Wohnungen), Anlage 1: 458 EUR for one person up to 869 EUR for five, +92 EUR per further person; income-based "
        "reduction on application (Anlage 2).",
        ["(Notunterkünfte, Wohnheime, Wohnprojekte, Wohnungen) werden in Abhängigkeit von der Haushaltsgröße folgende monatliche Gebühren erhoben"],
        fees=[_fee("obdach_gebuehr_eur_monat__einzelperson", 458, "EUR/Monat", "Einzelperson 458 €", "Anlage 1", 2024),
              _fee("obdach_gebuehr_eur_monat__5_personen", 869, "EUR/Monat", "5 Personen 869 €", "Anlage 1", 2024)],
        gem="03241001"),
    _mu("saarbruecken_obdach_geb", "10041", "SL", "Saarbrücken",
        "https://www.saarbruecken.de/media/download-61d2cb9fb96e9",
        "satzung", "obdach_gebuehr", "Saarbrücker Ortsrecht: Gebührensatzung Unterkünfte für Geflüchtete und obdachlos gewordene Personen (Stadtratsbeschluss 07.12.2021)",
        "Satzung über die Erhebung von Gebühren für die Benutzung von Unterkünften für Geflüchtete und obdachlos gewordene Personen in der Landeshauptstadt Saarbrücken",
        "2022-01-01", "tritt zum 01.01.2022 in Kraft", "original",
        "Monthly fee per sleeping place in shared accommodation: 241.20 EUR for adults, 180.90 EUR for minors from 11 "
        "and partners, 120.60 EUR for children up to 10; operating and energy costs charged in addition.",
        ["hat der Stadtrat in seiner Sitzung am 07.12.2021 folgende Satzung über die Benutzung von Unterkünften für Geflüchtete und obdachlos gewordene Personen erlassen"],
        fees=[_fee("obdach_gebuehr_eur_platz_monat__volljaehrige", 241.20, "EUR/Schlafplatz/Monat",
                   "Die monatliche Benutzungsgebühr für einen Schlafplatz beträgt für Volljährige Personen 241,20 EUR", "Anlage 1 Nr. 2.1.1", 2022)],
        in_force_from="2022-01-01", gem="10041100"),
    _mu("paderborn_obdach_geb", "05774", "NW", "Paderborn",
        "https://www.paderborn.de/rathaus-service/stadtverwaltung/satzungen/soziales-jugend.php.media/321123/Satzung-ueber-die-Erhebung-von-Gebuehren-fuer-die-Benutzung-der-Wohnunterkuenfte-fuer-Obdachlose-ab-01.07.2026.pdf",
        "satzung", "obdach_gebuehr", "Paderborner Ortsrecht 326 Gebührensatzung Wohnunterkünfte für Obdachlose vom 25.02.1980 i.d.F. der 3. Änderung vom 03.06.2026",
        "Satzung über die Erhebung von Gebühren für die Benutzung der Wohnunterkünfte für Obdachlose in der Stadt Paderborn",
        "2026-07-01", "3. Änderungssatzung vom 03.06.2026, in Kraft ab 01.07.2026", "consolidated",
        "Monthly fee per m² of usable floor space: 4.20 EUR in basic-standard and 4.68 EUR in normal-standard "
        "accommodation (electricity not included).",
        ["SATZUNG über die Erhebung von Gebühren für die Benutzung der Wohnunterkünfte für Obdachlose in der Stadt Paderborn vom 25.02.1980"],
        fees=[_fee("obdach_gebuehr_eur_m2_monat__einfacher_standard", 4.20, "EUR/m²/Monat", "Wohnunterkünfte mit einfachem Standard 4,20 EUR", "§ 2", 2026),
              _fee("obdach_gebuehr_eur_m2_monat__normaler_standard", 4.68, "EUR/m²/Monat", "Wohnunterkünfte mit normalem Standard 4,68 EUR", "§ 2", 2026)],
        in_force_from="2026-07-01", gem="05774032"),
    _mu("neuss_obdach", "05162", "NW", "Neuss",
        "https://www.neuss.de/fileadmin/Redaktion/downloads/ortsrecht/50-01_nutzung-der-obdachlosenunterkuenfte.pdf",
        "satzung", "obdach,obdach_gebuehr", "Neusser Ortsrecht 50/01 vom 12.11.1996 i.d.F. der 8. Änderungssatzung vom 05.07.2019",
        "Satzung über die Nutzung der Obdachlosenunterkünfte der Stadt Neuss",
        "2019-07-05", "Satzung über die Nutzung der Obdachlosenunterkünfte der Stadt Neuss vom 12. November 1996 (in der Fassung der 8. Änderungssatzung vom 5. Juli 2019)", "consolidated",
        "Use of municipal shelters (no tenancy; residents can be moved); fee 6.14 EUR per m² and month plus a utilities "
        "surcharge (VKZ) in the three listed shelters; the overnight shelter is free of charge.",
        ["Durch die Zuweisung von Obdach in einer Obdachlosenunterkunft wird kein Mietverhältnis begründet"],
        fees=[_fee("obdach_gebuehr_eur_m2_monat", 6.14, "EUR/m²/Monat", "Neuss, An der Schleppbahn 7 6,14 EUR zzgl. VKZ", "§ 3 Abs. 1", 2019)],
        gem="05162024"),
    _mu("recklinghausen_obdach_geb", "05562", "NW", "Recklinghausen",
        "https://www.recklinghausen.de/Inhalte/Startseite/Leben_Wohnen/Dokumente/_Gebuehrensatzung%20Nr%2059%20vom%2016122025.pdf",
        "satzung", "obdach_gebuehr", "Recklinghausener Ortsrecht Nr. 59: 1. Änderung vom 16.12.2025 der Satzung und Gebührensatzung Übergangsheime vom 03.12.2024",
        "Satzung vom 16.12.2025 zur ersten Änderung der Satzung und Gebührensatzung für die Übergangsheime und sonstigen Einrichtungen zur vorläufigen Unterbringung von Aussiedlern, Übersiedlern und ausländischen Flüchtlingen sowie wohnungslosen Personen vom 03.12.2024",
        "2026-01-01", "Diese Satzung tritt am 01.01.2026 in Kraft", "original",
        "Monthly fee per place by accommodation category (basic + supplementary fee): category I (shared "
        "accommodation) 392.04 EUR; category II (flat-like) up to 421.74 EUR.",
        ["Satzung vom 16.12.2025 zur ersten Änderung der Satzung und Gebührensatzung für die Übergangsheime"],
        fees=[_fee("obdach_gebuehr_eur_platz_monat__sammelunterkunft", 392.04, "EUR/Platz/Monat",
                   "Kategorie I (Sammelunterkünfte) 297,00 € 95,04 € 392,04 €", "§ 1 (Gebührentabelle)", 2026)],
        note="amending statute; the base statute of 03.12.2024 is not archived in this row",
        in_force_from="2026-01-01", gem="05562032"),
    _mu("bergischgladbach_obdach_geb", "05378", "NW", "Bergisch Gladbach",
        "https://www.bergischgladbach.de/50-4.pdfx?forced=true",
        "satzung", "obdach,obdach_gebuehr", "Bergisch Gladbacher Ortsrecht 50.4 vom 15.12.2021 i.d.F. der IV. Nachtragssatzung vom 17.12.2025",
        "Benutzungs- und Gebührensatzung der Stadt Bergisch Gladbach für städtische Unterkünfte für Flüchtlinge, Aussiedler, Obdachlose und Nichtsesshafte",
        "2026-01-01", "Die IV. Nachtragssatzung vom 17.12.2025 wurde am 18.12.2025 im Amtsblatt der Stadt Bergisch Gladbach veröffentlicht und ist am 01.01.2026 in Kraft getreten", "consolidated",
        "Use and fees of municipal accommodation for refugees and homeless people: 370 EUR per person and calendar "
        "month including operating costs, capped at the Rheinisch-Bergischer Kreis limits for housing costs.",
        ["vom 15.12.2021 in der Fassung der IV. Nachtragssatzung"],
        fees=[_fee("obdach_gebuehr_eur_person_monat", 370, "EUR/Person/Monat",
                   "370,00 Euro. Die Höhe der Benutzungsgebühr", "§ 3 Abs. 2", 2026)],
        in_force_from="2026-01-01", gem="05378004"),
    _mu("siegen_obdach", "05970", "NW", "Siegen",
        "https://www.siegen.de/fileadmin/user_upload/Dokumente/RathausUndPolitik/Ortsrecht/32_030.pdf",
        "satzung", "obdach,obdach_gebuehr", "Siegener Ortsrecht 32.030 (Ratsbeschluss 15.12.1998, 1. Änderung 22.10.2001)",
        "Satzung über die Errichtung, Unterhaltung und gebührenpflichtige Benutzung von Wohngebäuden zur Unterbringung obdachloser Personen in der Stadt Siegen",
        "2002-01-01", "Die 1. Änderungssatzung vom 22.10.2001 tritt am 01.01.2002 in Kraft", "consolidated",
        "Municipal buildings for homeless people: fee 3.00 EUR per m² of living space in all buildings, monthly amount "
        "rounded up to full euros; operating costs passed on pro rata.",
        ["Diese Satzung tritt am 01.01.1999 in Kraft"],
        fees=[_fee("obdach_gebuehr_eur_m2_monat", 3.00, "EUR/m²/Monat", "§ 2 der Satzung 3,00 EUR", "§ 5 Abs. 3", 2002)],
        gem="05970040"),
    _mu("guetersloh_obdach_geb", "05754", "NW", "Gütersloh",
        "https://www.guetersloh.de/de-wAssets/docs/ortsrecht/Benutzungs-und-Gebuehrensatzung-fuer-Unterkuenfte-der-Stadt-Guetersloh_3.-Aenderungssatzung.pdf",
        "satzung", "obdach,obdach_gebuehr", "Gütersloher Ortsrecht: Benutzungs- und Gebührensatzung Unterkünfte vom 15.12.2017 i.d.F. der 9. Änderungssatzung vom 14.11.2025 (Amtsblatt 21/2025)",
        "Benutzungs- und Gebührensatzung für Unterkünfte der Stadt Gütersloh für Flüchtlinge und Obdachlose",
        "2026-01-01", "vom 15.12.2017 unter Einarbeitung der 9. Änderungssatzung vom 14.11.2025", "consolidated",
        "Use and fees of municipal accommodation for refugees and homeless people: 356 EUR per resident and month "
        "including operating costs (lower rate in BImA buildings, Anlage 2).",
        ["Benutzungs- und Gebührensatzung für Unterkünfte der Stadt Gütersloh für Flüchtlinge und Obdachlose vom 15.12.2017"],
        fees=[_fee("obdach_gebuehr_eur_person_monat", 356, "EUR/Person/Monat",
                   "beträgt je Bewohner und je Kalendermonat 356,-Euro", "§ 3 Abs. 2", 2026)],
        in_force_from="2026-01-01", gem="05754008"),
    _mu("pforzheim_obdach_geb", "08231", "BW", "Pforzheim",
        "https://cdn.pforzheim-web.de/fileadmin/user_upload/hauptamt/stadtrecht/4_SOZSICH/4-5.pdf",
        "satzung", "obdach_gebuehr", "Pforzheimer Stadtrecht 4.5 (Gemeinderat 03.06.2025, Bekanntmachung 14.06.2025)",
        "Gebührensatzung der Stadt Pforzheim für die Benutzung der Notunterkünfte und für die Unterkünfte der Anschlussunterbringung für Flüchtlinge der Stadt Pforzheim",
        "2025-07-01", "Diese Satzung tritt am 01.07.2025 in Kraft", "original",
        "Fees for emergency (homeless) accommodation and refugee follow-up housing: cold accommodation fee and "
        "operating-cost fee per m² by category of building (Anlage), plus a flat electricity fee of 35 EUR per person "
        "and month.",
        ["Gebührensatzung der Stadt Pforzheim für die Benutzung der Notunterkünfte und für die Unterkünfte der Anschlussunterbringung"],
        fees=[_fee("obdach_stromgebuehr_eur_person_monat", 35, "EUR/Person/Monat",
                   "Pro Person und Monat beträgt die Stromgebühr 35,- €", "Anlage zu § 2 (§ 2 Abs. 3)", 2025)],
        in_force_from="2025-07-01"),
    _mu("fuerth_obdach_geb", "09563", "BY", "Fürth",
        "https://www.fuerth.de/fileadmin/redaktion/01-Rathaus/Ortsrecht/50_2_gebuehrensatzung_obdachlosenunterkuenfte.pdf",
        "satzung", "obdach_gebuehr", "Fürther Ortsrecht 50-2 vom 28.04.2009 i.d.F. der Änderungssatzung vom 04.11.2011",
        "Gebührensatzung über die Benutzung der Obdachlosenunterkünfte der Stadt Fürth",
        "2011-11-23", "i.d.F. der Änderungssatzung vom 4. November 2011 (Stadtzeitung Nr. 21 vom 23. November 2011)", "consolidated",
        "Monthly fees per m² in the municipal shelters (e.g. Oststraße 112: 5 EUR base, 4 EUR operating costs, "
        "2 EUR heating); flat 100 EUR per month in shared accommodation.",
        ["Gebührensatzung über die Benutzung der Obdachlosenunterkünfte der Stadt Fürth vom 28. April 2009"],
        fees=[_fee("obdach_gebuehr_eur_monat__gemeinschaftsunterkunft_pauschal", 100, "EUR/Monat",
                   "Die Pauschalentschädigung für Gemeinschaftsunterkünfte beträgt monatlich 100 Euro", "§ 4 Abs. 3", 2011)]),
    _mu("wolfsburg_obdach_geb", "03103", "NI", "Wolfsburg",
        "https://www.wolfsburg.de/-/media/wolfsburg/statistik_daten_fakten/satzungen_verordnungen/gebhrensatzung_wohnungslosenunterbringung_20230630.pdf",
        "satzung", "obdach_gebuehr", "Wolfsburger Ortsrecht: Gebührensatzung Wohnungslosenunterbringung vom 30.06.2023",
        "Satzung über die Erhebung von Gebühren für die vorübergehende Unterbringung von wohnungslosen Personen in den Unterkünften für Wohnungslose und in Übergangswohnungen in der Stadt Wolfsburg (Gebührensatzung Wohnungslosenunterbringung)",
        "2023-09-01", "Diese Satzung tritt am 01.09.2023 in Kraft", "original",
        "Shelter Borsigstraße 19–29: 8.50 EUR per m² and month incl. district heating, electricity and water; "
        "overnight shelter: 2.00 EUR per person and day; separate rates for transitional flats.",
        ["(Gebührensatzung Wohnungslosenunterbringung)"],
        fees=[_fee("obdach_gebuehr_eur_m2_monat__borsigstrasse_19_29", 8.50, "EUR/m²/Monat",
                   "Borsigstraße 19 bis 29 beträgt monatlich 8,50 € pro Quadratmeter Wohnfläche", "§ 4 Abs. 1", 2023),
              _fee("obdach_notuebernachtung_eur_person_tag", 2.00, "EUR/Person/Tag",
                   "Nutzungsgebühr in Höhe von 2,00 € pro Person und pro Tag erhoben", "§ 4 Abs. 3", 2023)],
        in_force_from="2023-09-01"),
    _mu("kaiserslautern_obdach_geb", "07312", "RP", "Kaiserslautern",
        "https://www.kaiserslautern.de/mb/themen/stadtverwaltung/ortsrecht/pdf/6_911_gebuehrensatzung_obdachlosenunterkuenfte.pdf",
        "satzung", "obdach_gebuehr", "Kaiserslauterer Ortsrecht 6.911 Gebührensatzung Obdachlosenunterkünfte vom 07.02.2008",
        "Satzung der Stadt Kaiserslautern zur Erhebung von Gebühren für die Obdachlosenunterkünfte der Stadt Kaiserslautern (Gebührensatzung)",
        "2008-02-07", "(Gebührensatzung) vom 07.02.2008", "original",
        "Monthly fee per m² for each municipal shelter site (2.45–2.70 EUR, e.g. Alte Brücke 1-7: 2.55 EUR) plus "
        "operating-cost flat rates; promulgated 15.02.2008.",
        ["hat der Stadtrat am 28.01.2008 folgende Satzung bes"],
        fees=[_fee("obdach_gebuehr_eur_m2_monat__alte_bruecke", 2.55, "EUR/m²/Monat", "a) Alte Brücke 1-7 2,55 Euro", "§ 5 Abs. 1 lit. a", 2008),
              _fee("obdach_gebuehr_eur_m2_monat__nordbahnstrasse", 2.70, "EUR/m²/Monat", "g) Nordbahnstraße 57-61 2,70 Euro", "§ 5 Abs. 1 lit. g", 2008)]),
    # ---- (b) local public-order ordinances: begging / lagern / sleeping / alcohol ----
    _mu("koeln_kso", "05315", "NW", "Köln",
        "https://www.stadt-koeln.de/mediaasset/content/satzungen/koelner-stadtordnung_20250909.pdf",
        "verordnung", "betteln,lagern,alkohol", "Kölner Stadtordnung (KSO) vom 14.04.2014 i.d.F. der 5. Änderung vom 09.09.2025",
        "Satzung und ordnungsbehördliche Verordnung über die öffentliche Sicherheit und Ordnung für das Gebiet der Stadt Köln (Kölner Stadtordnung - KSO -)",
        "2025-09-09", "(Kölner Stadtordnung - KSO) vom 09. September 2025", "consolidated",
        "Bans aggressive, obstructive or deceptive begging and begging with children (§ 11); outside designated areas "
        "it is forbidden to camp (lagern) or set up or use a sleeping place in public areas, and tenting/overnighting "
        "in green spaces (§ 11 Abs. 4); alcohol and drug use banned at entrances of kindergartens and schools (§ 11a).",
        ["aggressives Betteln oder aggressive Verkaufspraktiken",
         "ist es verboten, zu lagern oder einen Schlafplatz einzurichten oder zu nutzen",
         "§ 11a Alkohol- und Drogenkonsum in unmittelbarer Umgebung von Kindergärten und Schulen"],
        note="consolidated reading copy published by the city"),
    _mu("duesseldorf_strassenordnung", "05111", "NW", "Düsseldorf",
        "https://www.duesseldorf.de/stadtrecht/3/32/32-101",
        "verordnung", "betteln,lagern,alkohol", "Düsseldorfer Stadtrecht 32.101 (Düsseldorfer Straßenordnung) vom 04.10.2006",
        "Ordnungsbehördliche Verordnung zur Aufrechterhaltung der öffentlichen Sicherheit und Ordnung in der Landeshauptstadt Düsseldorf (Düsseldorfer Straßenordnung)",
        "2007-03-01", "Redaktioneller Stand: März 2007", "consolidated",
        "Bans aggressive begging (blocking, using dogs, following, touching) and group 'Lagern' that regularly "
        "obstructs public use of streets; in parks, camping/lagern only where permitted and alcohol consumption "
        "where it disturbs others is prohibited. Valid 01.01.2007 to 31.12.2026.",
        ["insbesondere aggressives Betteln (unmittelbares Einwirken auf Passanten durch In-den-Weg-Stellen, Einsatz von Hunden als Druckmittel, Verfolgen oder Anfassen)",
         "Diese Verordnung tritt am 01.01. 2007 in Kraft und gilt bis zum 31. 12. 2026",
         # b19 lapse test (Lead 2026-11-23): deciding sentence
         "Diese Verordnung tritt am 01.01. 2007 in Kraft und gilt bis zum 31. 12. 2026"],
        note="expires 31.12.2026; a successor 'Düsseldorfer Straßen- und Grünflächenordnung' (5 m begging ban around outdoor dining from 2027) was adopted by the council but is not yet promulgated in the Stadtrecht",
        in_force_from="2007-01-01",
        ends_on='2027-01-01', ends_needle='Diese Verordnung tritt am 01.01. 2007 in Kraft und gilt bis zum 31. 12. 2026'),
    _mu("stuttgart_stranlpolvo", "08111", "BW", "Stuttgart",
        "https://www.stuttgart.de/medien/ibs/1-1.pdf",
        "verordnung", "lagern", "Stuttgarter Stadtrecht 1/1 StrAnlPolVO vom 09.05.2019",
        "Polizeiverordnung zur Aufrechterhaltung der öffentlichen Sicherheit und Ordnung auf und an öffentlichen Straßen und in öffentlichen Anlagen in Stuttgart (Straßen- und Anlagen-Polizeiverordnung - StrAnlPolVO -)",
        "2019-06-21", "vom 9. Mai 2019 Bekannt gemacht im Amtsblatt Nr. 25 vom 21. Juni 2019", "original",
        "Police ordinance banning sleeping overnight (Nächtigen) on public streets between 20:00 and 06:00 (§ 2 Nr. 1), "
        "among other street and park rules.",
        ["Auf öffentlichen Straßen ist untersagt 1. das Nächtigen in der Zeit von 20 bis 6 Uhr"],
        in_force_from="2019-06-22"),
    _mu("bochum_bosvo", "05911", "NW", "Bochum",
        "https://www.bochum.de/C125830C0042AB74/vwContentByKey/N26R26QP189HGILDE/$FILE/bosvo.pdf",
        "verordnung", "betteln,lagern", "Bochumer Sicherheitsverordnung (BOSVO) vom 05.06.2025 i.d.F. vom 20.05.2026",
        "Ordnungsbehördliche Verordnung über die Aufrechterhaltung der öffentlichen Sicherheit und Ordnung in der Stadt Bochum (Bochumer Sicherheitsverordnung - BOSVO)",
        "2026-05-20", "(Bochumer Sicherheitsverordnung - BOSVO) Vom 05.06.2025 in der Fassung der Ersten Änderungssatzung Vom 20.05.2026", "consolidated",
        "Bans aggressive begging and begging involving children (§ 3 Abs. 1 Nr. 6), group 'Lagern' that excludes "
        "passers-by from public use (§ 3 Abs. 1 Nr. 2), and camping, lagern and sleeping on traffic areas and in "
        "parks outside designated areas (§ 12).",
        ["das aggressive Betteln sowie das Betteln unter Beteiligung von Kindern oder Jugendlichen",
         "Das Lagern, Campieren und das Nächtigen auf Verkehrsflächen oder in Anlagen im Sinne des § 2 Absätze 1 und 2 ist verboten"]),
    _mu("karlsruhe_stranlpolv", "08212", "BW", "Karlsruhe",
        "https://www.karlsruhe.de/fileadmin/user_upload/01_Stadt_Rathaus/013_Verwaltung_und_Stadtpolitik/Stadtrecht/1_OEffentliche_Sicherheit_und_Ordnung/1-1_Strassenpolizeiverordnung.pdf",
        "verordnung", "betteln,lagern,alkohol", "Karlsruher Stadtrecht 1/1 StrAnlPolV vom 20.05.2014",
        "Polizeiverordnung der Stadt Karlsruhe zur Aufrechterhaltung der öffentlichen Sicherheit und Ordnung auf öffentlichen Straßen und Anlagen und zur Abwehr von umweltschädlichem Verhalten (Straßen- und Anlagenpolizeiverordnung, StRAnlPolV)",
        "2026-01-27", "zuletzt geändert durch Polizeiverordnung vom 26. Januar 2026 (Online Bekanntmachung vom 27. Januar 2026)", "consolidated",
        "On public streets and in parks: bans sleeping overnight and camping (§ 3 Abs. 1 Nr. 1); begging that is "
        "repeated, intrusive, aggressive, intimidating, involves holding or blocking people, feigned disability or "
        "minors (Nr. 2, tightened in 2026); settling in groups mainly to drink alcohol where alcohol-related "
        "aggressive behaviour obstructs others (Nr. 12).",
        ["1. das Nächtigen und Zelten, 2. um Geld- oder Sachleistungen zu bitten, wenn dies a. durch wiederholtes, aufdringliches oder aggressives Ansprechen von Personen"],
        note="consolidated text incl. the amendment of 26.01.2026"),
    _mu("muenster_ordnungsvo", "05515", "NW", "Münster",
        "https://www.stadt-muenster.de/recht/ortsrecht/satzungen/detailansicht/satzungsnummer/32.01",
        "verordnung", "betteln,lagern,alkohol", "Münsteraner Ortsrecht 32.01 (Straßen-, Anlagen- und Aaseeordnung) vom 20.11.2016",
        "Ordnungsbehördliche Verordnung über die Aufrechterhaltung der öffentlichen Sicherheit und Ordnung (Straßen-, Anlagen- und Aaseeordnung)",
        "2016-11-20", "(Straßen-, Anlagen- und Aaseeordnung) 32.01 vom 20.11.2016 (Amtsblatt der Stadt Münster 2016 S. 199)", "original",
        "Bans behaviour that more than slightly obstructs or harasses others in streets and parks, e.g. disruptive "
        "'Lagern', aggressive begging or alcohol-related disturbances (§ 12); permanent camping and permanent "
        "overnighting on green spaces banned (§ 10). In force 01.01.2017 to 31.12.2036.",
        ["z.B. durch störendes Lagern, aggressives Betteln oder durch Alkoholgenuss bedingte Störungen",
         "das dauerhafte Zelten und dauerhafte Übernachten darauf sind verboten",
         "Diese Verordnung tritt am 1.1.2017 in Kraft und mit Ablauf des 31.12.2036 außer Kraft"],
        in_force_from="2017-01-01",
        ends_on='2037-01-01', ends_needle='Diese Verordnung tritt am 1.1.2017 in Kraft und mit Ablauf des 31.12.2036 außer Kraft'),
    _mu("bielefeld_obvo", "05711", "NW", "Bielefeld",
        "https://www.bielefeld.de/sites/default/files/datei/2025/III-1-OBVO-Internet.pdf",
        "verordnung", "betteln,lagern,alkohol", "Bielefelder Ortsrecht III-1 OBVO vom 27.06.2008",
        "Ordnungsbehördliche Verordnung zur Aufrechterhaltung der öffentlichen Sicherheit und Ordnung im Gebiet der Stadt Bielefeld",
        "2025-06-12", "Vom 27.06.2008 in der Fassung vom 12.06.2025", "consolidated",
        "On traffic areas and in parks bans in particular: 'Lagern' by groups that gather regularly at the same "
        "places and obstruct passers-by; aggressive begging (touching, holding, blocking, pursuing, dogs, "
        "acting together); overnighting; alcohol-related disturbances. Expires 31.12.2027.",
        ["das Lagern in Personengruppen, wenn sich diese an denselben Orten regelmäßig",
         "b) das aggressive Betteln, z. B. durch Anfassen, Festhalten",
         "das Stören in Verbindung mit dem Genuss von Alkohol",
         "Sie tritt am 31.12.2027 außer Kraft"],
        ends_on='2027-12-31', ends_needle='Sie tritt am 31.12.2027 außer Kraft'),
    _mu("bonn_strassenordnung", "05314", "NW", "Bonn",
        "https://www.bonn.de/service-bieten/stadtpolitik-ortsrecht/ortsrecht/recht-sicherheit/strassenordnung.php",
        "verordnung", "betteln,lagern,alkohol", "Bonner Ortsrecht 32-01 StrO vom 19.12.2008",
        "Ordnungsbehördliche Verordnung über die Aufrechterhaltung der öffentlichen Sicherheit und Ordnung im Gebiet der Bundesstadt Bonn (Bonner Straßenordnung – StrO)",
        "2019-02-20", "20.02.2019 (ABl. S. 79) 06.03.2019 §§ 5, 9", "consolidated",
        "Bans behaviour in public places that obstructs or harasses others more than unavoidable, e.g. disruptive "
        "drinking, drunkenness, aggressive begging, use as a 'Lagerplatz'; camping outside campsites banned in "
        "parks; begging with children banned throughout (§ 3 Abs. 6). Last amendment 20.02.2019, in force 06.03.2019.",
        ["störender Alkoholgenuss, Trunkenheit, aggressives Betteln, die Nutzung als Lagerplatz",
         "Das Betteln mit Kindern ist im Geltungsbereich dieser Verordnung verboten", 'Diese Verordnung tritt am 1. Januar 2009 in Kraft. Sie tritt am 31. Dezember 2028 außer Kraft'],
        ends_on='2028-12-31', ends_needle='Diese Verordnung tritt am 1. Januar 2009 in Kraft. Sie tritt am 31. Dezember 2028 außer Kraft'),
    _mu("magdeburg_gefavo", "15003", "ST", "Magdeburg",
        "https://www.magdeburg.de/PDF/Gefahrenabwehrverordnung_Amtsblatt_21_2022.PDF?Ext=PDF&ObjID=53138&ObjLa=1&ObjSvrID=37&WTR=1&_ts=1675688556",
        "verordnung", "betteln,lagern,alkohol", "Amtsblatt der Landeshauptstadt Magdeburg Nr. 21 vom 27. Juni 2022 S. 287",
        "Gefahrenabwehrverordnung der Landeshauptstadt Magdeburg über die Abwehr von Gefahren für die öffentliche Sicherheit und Ordnung durch die Nutzung von Straßen, Grünanlagen, Einrichtungen und Gewässer u. a.",
        "2022-06-27", "Amtsblatt der Landeshauptstadt Magdeburg Nr. 21 vom 27. Juni 2022 Seite 287", "original",
        "§ 2 Abs. 1: bans camping or overnighting on streets; lying around or lingering to drink alcohol where "
        "alcohol-related effects impair others; aggressive, intrusive or obstructive begging and begging with "
        "children. In force 13.07.2022 for ten years.",
        ["a.) auf Straßen zu kampieren oder zu übernachten",
         "zum Zwecke des Konsums von Alkohol auf Straßen oder in Grünanlagen zu lagern oder dauerhaft zu verweilen",
         "mit Kindern zu betteln",
         "Diese Verordnung tritt am 13. Juli 2022 in Kraft", '(1) Diese Verordnung tritt am 13. Juli 2022 in Kraft. (2) Diese Verordnung tritt zehn Jahre nach ihrem Inkrafttreten außer Kraft'],
        in_force_from="2022-07-13",
        ends_on='2032-07-13', ends_needle='(1) Diese Verordnung tritt am 13. Juli 2022 in Kraft. (2) Diese Verordnung tritt zehn Jahre nach ihrem Inkrafttreten außer Kraft'),
    _mu("halle_gefavo", "15002", "ST", "Halle (Saale)",
        "https://halle.de/fileadmin/Binaries/Verwaltung/Stadtpolitik_und_Ortsrecht/Satzungen_und_Verordnungen/GB_OB/FB_Sicherheit/SR_301-1_Gefahrenabwehrverordnung.pdf",
        "verordnung", "betteln,lagern,alkohol", "Hallesches Stadtrecht SR 3.01-1 vom 30.10.2017 (ABl. Nr. 21 vom 21.11.2017)",
        "Gefahrenabwehrverordnung der Stadt Halle (Saale) über den Schutz von Fußgängerinnen und Fußgängern, über das aggressive Betteln u. a.",
        "2017-11-21", "veröffentlicht im Amtsblatt der Stadt Halle (Saale) Nr. 21 vom 21. November 2017", "original",
        "Bans aggressive begging (§ 5: blocking, following, body contact, intimidation); bans sleeping overnight and "
        "camping in public parks (§ 13 Nr. 1); bans alcohol consumption that harasses others (§ 15). In force one "
        "week after promulgation, for ten years.",
        ["Das aggressive Betteln ist verboten",
         "In den öffentlichen Anlagen ist untersagt: 1. das Nächtigen und Zelten",
         "Konsum von Alkohol und anderen berauschenden Mitteln"]),
    _mu("leipzig_polvo", "14713", "SN", "Leipzig",
        "https://www.leipzig.de/service-portal/satzungen/details/satzung/3-01/download",
        "verordnung", "lagern,alkohol", "Leipziger Satzung 3-01 Polizeiverordnung (Beschluss VII-DS-00299)",
        "Polizeiverordnung über öffentliche Sicherheit und Ordnung in der Stadt Leipzig",
        "2020-06-06", "veröffentlicht im Leipziger Amts-Blatt Nr. 11 vom 06.06.2020", "original",
        "Bans 'Lagern' (makeshift settling in one place for the purpose of shelter) on public streets and in public "
        "green spaces, and aggressive or intrusive behaviour, in particular caused by alcohol or drug use, that "
        "harasses others or obstructs public use. (An aggressive-begging clause was dropped by the council.)",
        ["Auf öffentlichen Straßen oder in öffentlichen Grün- und Erholungsanlagen ist es untersagt, zu lagern. Lagern ist das behelfsmäßige Einrichten an einer Stelle zum Zwecke der Unterkunft",
         "Die vorstehende Polizeiverordnung tritt am Tage nach ihrer öffentlichen Bekanntmachung am 07.06.2020 in Kraft"],
        in_force_from="2020-06-07"),
    _mu("dresden_polvo", "14612", "SN", "Dresden",
        "https://www.dresden.de/media/pdf/satzungen/polizeiverordnung.pdf",
        "verordnung", "betteln,lagern", "Dresdner Ortsrecht 3.14 PolVO Sicherheit und Ordnung vom 25.01.2018",
        "Polizeiverordnung der Landeshauptstadt Dresden als Kreispolizeibehörde zur Abwehr von Gefahren für die öffentliche Sicherheit und Ordnung in Dresden (PolVO Sicherheit und Ordnung)",
        "2024-06-18", "und zuletzt in Nr. e30-06-2024 vom 18. Juni 2024", "consolidated",
        "In public areas it is forbidden to camp (lagern) or sleep overnight (nächtigen) and to beg aggressively "
        "(§ 12 lit. a, c); begging as or with a child under 14 is banned (§ 13).",
        ["Im öffentlichen Bereich ist es untersagt: a) zu lagern oder zu nächtigen",
         "Im öffentlichen Bereich ist es untersagt als Kind oder in Begleitung eines Kindes zu betteln"]),
    _mu("mannheim_polvo", "08222", "BW", "Mannheim",
        "https://www.mannheim.de/sites/default/files/2021-11/s03-01.pdf",
        "verordnung", "betteln,lagern,alkohol", "Mannheimer Stadtrecht 3.01 Allgemeine Polizeiverordnung",
        "Polizeiverordnung zur Aufrechterhaltung von Sicherheit und Ordnung auf öffentlichen Straßen und Anlagen und zur Abwehr von verhaltensbedingten Gefahren im Stadtkreis Mannheim (Allgemeine Polizeiverordnung)",
        "2021-11-12", "Inkrafttreten am 12.11.2021 (Amtsblatt Nr. 114 v. 11.11.2021)", "original",
        "On streets, in parks and underground facilities: bans sleeping outdoors (and living in vehicles) and "
        "intrusive or harassing begging or begging with minors (§ 3 Abs. 1); alcohol banned on and near "
        "playgrounds; lagern or lingering to drink in public-transport shelters banned.",
        ["das Nächtigen im Freien sowie das Nächtigen zu Unterkunfts- und Wohnzwecken in Kraftfahrzeugen und Anhängern",
         "Auf Kinderspielplätzen und sonstigen Spielanlagen sowie in deren unmittelbarer Nähe sind der Konsum alkoholischer Getränke und die Abgabe solcher Getränke verboten"],
        in_force_from="2021-11-12"),
    _mu("duisburg_sov", "05112", "NW", "Duisburg",
        "https://www.duisburg.de/allgemein/fachbereiche/mit-hunden-gassi-gehen.php.media/14450/S32.01_Sicherheits-_u._Ordnungsverordnung_neu__ab_01.03.2019_.pdf",
        "verordnung", "betteln,lagern", "Duisburger Ortsrecht 32.01 Sicherheits- und Ordnungsverordnung vom 25.09.2012",
        "Ordnungsbehördliche Verordnung zur Aufrechterhaltung der öffentlichen Sicherheit und Ordnung im Stadtgebiet Duisburg (Sicherheits- und Ordnungsverordnung)",
        "2019-02-28", "Amtsblatt für die Stadt Duisburg Nr. 6 vom 28.02.2019, S. 59", "consolidated",
        "Bans aggressive begging and aggressive sales practices and the use of traffic areas or parks as a camp or "
        "sleeping place; the separate alcohol ban (§ 2a) was repealed in 2018. Valid until 30.09.2032.",
        ["aggressives Betteln und/oder aggressive Verkaufspraktiken",
         "Benutzung als Lager- oder Schlafplatz",
         "4. Änderung vom 09.10.2018, in Kraft getreten am 16.10.2018 § 2a Alkoholkonsumverbot wird gestrichen", 'Diese Verordnung tritt am Tage nach ihrer Verkündung in Kraft und gilt bis 30. September 2032'],
        note="consolidated text with amendment notes up to Amtsblatt 6/2019; the Ortsrecht index links an un-annotated copy of the 2012 base text",
        ends_on='2032-10-01', ends_needle='Diese Verordnung tritt am Tage nach ihrer Verkündung in Kraft und gilt bis 30. September 2032'),
    # ---- batch 7 (2026-11-21): ordinances of further large cities ----
    _mu("hannover_sogvo", "03241", "NI", "Hannover",
        "https://www.hannover.de/content/download/824533/file/VO-%C3%B6ffentliche+Sicherheit+und+Ordnung-28-05-2026-INTRANET.pdf",
        "verordnung", "betteln,lagern,alkohol", "Verordnung über die öffentliche Sicherheit und Ordnung in der Landeshauptstadt Hannover, Abl. RH / LHH 2026 Nr. 23 S. 415",
        "Verordnung über die öffentliche Sicherheit und Ordnung in der Landeshauptstadt Hannover",
        "2026-06-11", "Abl. RH / LHH 11.06.2026, Nr. 23, S. 415", "original",
        "On public streets and in parks bans organised, intrusive and aggressive begging and any begging by, with or "
        "using children, even if silent (§ 5); bans disturbances linked to alcohol or drug use and permanent 'Lagern' "
        "that obstructs passers-by (§ 3). In force the day after promulgation, for 10 years.",
        ["Das Betteln von Kindern, in Begleitung von Kindern oder unter Zuhilfenahme von Kindern",
         "b) das dauerhafte Lagern, wenn und soweit dabei Passant*innen",
         "Sie tritt 10 Jahre nach ihrem Inkrafttreten außer Kraft"],
        in_force_from="2026-06-12", gem="03241001"),
    _mu("essen_obvo", "05113", "NW", "Essen",
        "https://media.essen.de/media/wwwessende/aemter/15/SR101neu.pdf",
        "verordnung", "betteln,lagern,alkohol", "Essener Ortsrecht 1.01 Ordnungsbehördliche Verordnung vom 11.07.2025 i.d.F. vom 09.10.2026",
        "Ordnungsbehördliche Verordnung zur Aufrechterhaltung der öffentlichen Sicherheit und Ordnung im Stadtgebiet Essen",
        "2026-10-09", "vom 11. Juli 2025 zuletzt geändert am 09.10.2026", "consolidated",
        "Bans organised and aggressive begging, begging that endangers traffic, feigned need, silent begging using "
        "children or animals, and any begging within 5 m of outdoor dining; bans recurring stationary gatherings "
        "('Lagern') that restrict public use and alcohol-related disturbances (§ 4). Valid until 31.12.2032.",
        ["Betteln im Umkreis von fünf Metern um Außengastronomien",
         "Wiederkehrende ortsfeste Ansammlungen von Personen (Lagern)",
         "Störungen, vor allem unter Alkoholeinwirkung",
         "und gilt bis zum 31.12.2032", 'im Amtsblatt der Stadt Essen in Kraft und gilt bis zum 31.12.2032'],
        note="the city's media copy; the 5 m outdoor-dining begging ban is the 2026 amendment",
        ends_on='2033-01-01', ends_needle='im Amtsblatt der Stadt Essen in Kraft und gilt bis zum 31.12.2032'),
    _mu("nuernberg_sns", "09564", "BY", "Nürnberg",
        "https://www.nuernberg.de/imperia/md/zentral/dokumente/stadtrecht/230_710.pdf",
        "satzung", "sondernutzung,betteln,lagern,alkohol", "Nürnberger Stadtrecht 230.710 Sondernutzungssatzung (SNS) vom 15.12.2016",
        "Satzung über Sondernutzungen an öffentlichen Straßen (Sondernutzungssatzung – SNS)",
        "2023-06-30", "geändert durch Satzung vom 30. Juni 2023 (Amtsblatt S. 275)", "consolidated",
        "Street special-use statute: no special-use permit is granted (§ 8 Abs. 1) for sleeping or 'Lagern' in the "
        "pedestrian zones and the Hauptbahnhof underpass, for lingering to drink alcohol outside licensed outdoor "
        "seating in listed areas, or for begging in any form.",
        ["für das Nächtigen oder Lagern in den Fußgängerzonen und in der Fußgängerunterführung am Hauptbahnhof",
         "für das Verweilen zum Zwecke des Genusses alkoholischer Getränke außerhalb zugelassener",
         "für das Betteln in jeglicher Form"]),
    _mu("muenchen_alkoholverbot", "09162", "BY", "München",
        "https://stadt.muenchen.de/rathaus/stadtrecht/vorschrift/330.pdf",
        "verordnung", "alkohol", "Münchner Stadtrecht 330 Alkoholverbots-Verordnung vom 24.04.2024",
        "Verordnung der Landeshauptstadt München über das Verbot des Verzehrs und des Mitführens alkoholischer Getränke auf öffentlichen Flächen im Bereich des Hauptbahnhofes",
        "2026-03-11", "Stand: 11.03.2026", "consolidated",
        "Bans drinking, and carrying alcohol intended for consumption there, on public areas around the "
        "Hauptbahnhof (§ 2). In force 01.05.2024 until 01.05.2028; area amended 24.02.2026.",
        ["Im Geltungsbereich der Verordnung ist es verboten, a) alkoholische Getränke zu verzehren",
         "Die Verordnung tritt am 01.05.2024 in Kraft; sie tritt am 01.05.2028 außer Kraft"],
        note="Munich has no begging ordinance; begging is restricted by a general order (Allgemeinverfügung), not ingested",
        in_force_from="2024-05-01",
        ends_on='2028-05-01', ends_needle='Die Verordnung tritt am 01.05.2024 in Kraft; sie tritt am 01.05.2028 außer Kraft'),
    _mu("bremen_ortsgesetz_ordnung", "04011", "HB", "Bremen",
        "https://www.transparenz.bremen.de/sixcms/detail.php?gsid=bremen203.c.267198.de&template=00_html_to_pdf_d",
        "satzung", "betteln,lagern,alkohol", "Bremisches Ortsgesetz über die öffentliche Ordnung vom 27.09.1994 (Brem.GBl. 1994, 277), Gliederungsnummer 2183-a-2",
        "Ortsgesetz über die öffentliche Ordnung",
        "2026-03-24", "zuletzt geändert durch Ortsgesetz vom 24. März 2026 (Brem.GBl. S. 310)", "consolidated",
        "City ordinance (Ortsgesetz of the Stadtbürgerschaft) banning begging with or by children, organised begging "
        "and intrusive/aggressive begging (§ 1); 'Lagern' or lingering to use narcotics in a way that affects others "
        "(§ 2); and settling permanently on streets or benches to drink alcohol so that others are obstructed (§ 3).",
        ["Die Bettelei in Begleitung von Kindern oder durch Kinder ist untersagt",
         "Das organisierte oder bandenmäßige Betteln ist untersagt",
         "Es ist untersagt, sich dauerhaft zum Zwecke des Alkoholkonsums auf Straßen"],
        note="consolidated text from the Transparenzportal Bremen (Gesetzesportal export); the host returns 403 to the "
             "project UA from the deck, so it is read from a manual archive (as law_hb_polg)",
        local="muni_bremen_ortsgesetz_ordnung.pdf"),
    _mu("hamburg_alkverbv_stgeorg", "02000", "HH", "Hamburg",
        "https://www.luewu.de/wp-content/uploads/2026/07/GVBL_HH_2026-24.pdf",
        "verordnung", "alkohol", "HmbGVBl. 2026 Nr. 24 S. 199: Verordnung vom 28.07.2026 (Gliederungsnummer 2012-1-7)",
        "Verordnung über das Verbot des Verzehrs und des Mitführens alkoholischer Getränke auf öffentlichen Flächen im Stadtteil St. Georg",
        "2026-07-31", "HmbGVBl. Nr. 24 FREITAG, DEN 31. JULI 2026", "original",
        "Senate ordinance banning drinking, and carrying alcohol intended for consumption there, on public areas in "
        "St. Georg (Hansaplatz, upper Steindamm, ZOB surroundings). In force 01.08.2026 until 31.07.2027.",
        ["Verordnung über das Verbot des Verzehrs und des Mitführens alkoholischer Getränke auf öffentlichen Flächen im Stadtteil St. Georg",
         "Gegeben in der Versammlung des Senats, Hamburg, den 28. Juli 2026", 'Diese Verordnung tritt am 1. August 2026 in Kraft und mit Ablauf des 31. Juli 2027 außer Kraft'],
        note="official Gesetz- und Verordnungsblatt issue as published by its printer Lütcke & Wulff (luewu.de; robots allow, "
             "no TDM reservation; Impressum forbids commercial reuse). Hamburg has no begging ordinance; the Hauptbahnhof "
             "alcohol ordinance is a separate row (hamburg_alkverbv_hbf)",
        in_force_from="2026-08-01",
        lic="Amtliches Werk (§ 5 Abs. 1 UrhG): Verordnung des Senats der Freien und Hansestadt Hamburg, amtlich verkündet im "
            "HmbGVBl.; Ausgabe des Verlags Lütcke & Wulff (luewu.de, Impressum: keine gewerbliche Nutzung ohne Zustimmung); zitiert mit Fundstelle",
        ends_on='2027-08-01', ends_needle='Diese Verordnung tritt am 1. August 2026 in Kraft und mit Ablauf des 31. Juli 2027 außer Kraft'),
    _mu("wiesbaden_gefahrenabwehrvo", "06414", "HE", "Wiesbaden",
        "https://www.wiesbaden.de/medien/downloads/rathaus/3-2.1-Gefahrenabwehrverordnung.pdf",
        "verordnung", "betteln,lagern,alkohol", "Wiesbadener Stadtrecht 3-2.1 Gefahrenabwehrverordnung vom 12.12.2002",
        "Gefahrenabwehrverordnung über die Aufrechterhaltung der Sicherheit und Ordnung in der Landeshauptstadt Wiesbaden",
        "2013-01-16", "veröffentlicht am 16. Januar 2013 im Wiesbadener Kurier und Wiesbadener Tagblatt", "consolidated",
        "Bans aggressive begging by insistent or persistent approaching, sending children to beg and organised "
        "begging (§ 4 Abs. 1); alcohol banned on playgrounds, ball courts, school yards and two memorial sites "
        "(§ 4 Abs. 2); overnighting in tents or vehicles outside designated sites banned (§ 4 Abs. 3).",
        ["Das aggressive Betteln durch nachdrückliches oder hartnäckiges Ansprechen von Personen, das Betteln durch das Vorschicken von Kindern sowie das organisierte Betteln ist verboten",
         "Das Übernachten in Zelten, Kraftfahrzeugen, Wohnwagen oder ähnlichen transportablen Unterkünften",
         # b19 lapse test (Lead 2026-11-23): deciding sentence
         "Ursprüngliche Fassung veröffentlicht am 31. Januar 2003"],
        note="loose-leaf reading copy, 10. Ergänzungslieferung 2013"),
    _mu("freiburg_polvo", "08311", "BW", "Freiburg im Breisgau",
        "https://www.freiburg.de/pb/site/Freiburg/get/documents/freiburg/daten/ortsrecht/06%20Oeffentliche%20Ordnung/OrtsR_06_01.pdf",
        "verordnung", "betteln,lagern", "Freiburger Ortsrecht 6.1 Polizeiverordnung vom 29.09.2009 i.d.F. vom 27.07.2021",
        "Polizeiverordnung zur Sicherung der öffentlichen Ordnung und gegen umweltschädliches Verhalten in der Stadt Freiburg i. Br.",
        "2021-09-24", "Die Änderung der Polizeiverordnung vom 27.07.2021 ist öffentlich bekannt gemacht im Amtsblatt vom 24.09.2021", "consolidated",
        "Bans harassing begging, in particular by intrusive approaching or stopping passers-by, and begging with "
        "children (§ 11); bans sleeping overnight (Nächtigen) on public streets, in parks and public facilities "
        "(§ 12 Abs. 1 Nr. 2).",
        ["Ebenso ist das Betteln in Begleitung von Kindern verboten",
         "ist untersagt: 1. Personen grob ungehörig zu belästigen oder zu behindern. 2. Das Nächtigen"]),
    _mu("augsburg_sondernutzung", "09761", "BY", "Augsburg",
        "https://www.augsburg.de/fileadmin/user_upload/buergerservice_rathaus/rathaus/stadtrecht/pdf/66/6600.pdf",
        "satzung", "sondernutzung,betteln,lagern,alkohol", "Augsburger Stadtrecht 6600 Satzung über Straßensondernutzungen vom 27.11.2017 (ABl. 2017 S. 371)",
        "Satzung über Straßensondernutzungen in der Stadt Augsburg",
        "2024-04-19", "19.04.2024, S. 142", "consolidated",
        "Street special-use statute: a permit is as a rule not granted (§ 7 Abs. 2) for sleeping and 'Lagern', for "
        "settling to drink alcohol outside licensed seating where it unreasonably impairs others, or for organised, "
        "aggressive, traffic-impairing, deceptive begging or begging feigning an artistic performance.",
        ["Die Erlaubnis kann in der Regel nicht erteilt werden, (a) für das Nächtigen und Lagern",
         "durch gezielten Körperkontakt oder Verstellen des Weges erfolgt (nötigendes und aggressives Betteln)"],
        note="consolidated text; last amendment listed: Amtsblatt 19.04.2024 S. 142, effective 20.04.2024"),
    _mu("gelsenkirchen_obvo", "05513", "NW", "Gelsenkirchen",
        "https://www.gelsenkirchen.de/de/_meta/buergerservice/anhang/3333-ge_obvo_2022.pdf",
        "verordnung", "betteln,lagern,alkohol", "Gelsenkirchener Ortsrecht ObVO GE vom 01.03.2022",
        "Ordnungsbehördliche Verordnung über die Aufrechterhaltung der öffentlichen Sicherheit und Ordnung im Gebiet der Stadt Gelsenkirchen (ObVO GE)",
        "2022-03-01", "(ObVO GE) vom 01.03.2022", "original",
        "Bans aggressive begging (touching, holding, pursuing, persistent approaching, using animals) and further "
        "begging forms, alcohol- or drug-related disturbances and sleeping overnight, especially on benches (§ 3 Abs. 2).",
        ["aggressives Betteln (Aggressiv im Sinne dieser Verordnung ist das Betteln insbesondere dann",
         "in Verbindung mit dem Konsum von Alkohol oder anderen berauschenden Mitteln 4. das Nächtigen, insbesondere auf Bänken und Stühlen",
         "Diese Verordnung tritt am 12.03.2022 in Kraft"],
        note="press reports a revision adopted by the council in Oct 2026; the city's Ortsrecht still links this 2022 text",
        in_force_from="2022-03-12"),
    _mu("mainz_gefavo", "07315", "RP", "Mainz",
        "https://www.mainz.de/verzeichnisse/ortsrecht/gefahrenabwehrverordnung-zur-aufrechterhaltung-der-sicherheit-und-ordnung-auf-oeffentlichen-strassen-und-in-oeffentlichen-anlagen-vom-1-4-2011.php.media/166695/gefahrenabwehrverordnung-zur-aufrechterhaltung-der-sicherheit-und-ordnung-auf-oeffentlichen-strassen-und-in-oeffentlichen-anlagen-vom-1-4-2011.pdf",
        "verordnung", "betteln,lagern,alkohol", "Mainzer Ortsrecht: Gefahrenabwehrverordnung vom 16.02.2011",
        "Gefahrenabwehrverordnung zur Aufrechterhaltung der Sicherheit und Ordnung auf öffentlichen Straßen und in öffentlichen Anlagen",
        "2011-02-16", "in öffentlichen Anlagen vom 16.02.2011", "original",
        "Bans camping outside designated areas, aggressive/intrusive/organised begging or begging with minors, and "
        "lingering drunk or settling to drink where it harasses others (§ 2 Abs. 1); defines a 'Person ohne festen "
        "Wohnsitz' (§ 1 Abs. 4) who may be ordered to prove accommodation or registration with a homeless service "
        "within 24 hours (§ 4). In force 01.04.2011 to 31.03.2031.",
        ["in aggressiver, aufdringlicher, bedrängender, behindernder oder störender Form sowie mit oder durch Minderjährige oder organisiert zu betteln",
         "außerhalb der ausdrücklich dazu ausgewiesenen Flächen zu zelten",
         "Personen ohne festen Wohnsitz kann aufgegeben werden, dass sie innerhalb von 24 Stunden eine geordnete Unterkunft nachweisen",
         "tritt am 01.04.2011 in Kraft und am 31.03.2031 außer Kraft", 'Diese Gefahrenabwehrverordnung tritt am 01.04.2011 in Kraft und am 31.03.2031 außer Kraft'],
        in_force_from="2011-04-01",
        ends_on='2031-03-31', ends_needle='Diese Gefahrenabwehrverordnung tritt am 01.04.2011 in Kraft und am 31.03.2031 außer Kraft'),
    _mu("erfurt_stadtordnung", "16051", "TH", "Erfurt",
        "https://www.erfurt.de/mam/ef/rathaus/stadtrecht/3/3241.pdf",
        "verordnung", "lagern,alkohol", "Erfurter Stadtrecht 3.241 Stadtordnung vom 16.03.2023",
        "Ordnungsbehördliche Verordnung zur Aufrechterhaltung der öffentlichen Sicherheit und Ordnung in der Landeshauptstadt Erfurt (Stadtordnung)",
        "2023-03-29", "Veröffentlicht im Amtsblatt der Landeshauptstadt Erfurt am 29.03.2023", "original",
        "Bans 'Lagern' by groups of 3 or more who regularly gather at the same place and obstruct passers-by, and "
        "alcohol-related disturbances (§ 8); alcohol ban near facilities used mainly by children and young people "
        "(§ 8a). No begging clause. Valid for 20 years.",
        ["Lagern von Personengruppen (mindestens 3 Personen), wenn sich diese an demselben Ort regelmäßig ansammeln",
         "§ 8a Alkoholverzehr in der Öffentlichkeit",
         "Diese Verordnung gilt für die Dauer von 20 Jahren"],
        in_force_from="2023-03-30"),
    _mu("dortmund_obvo", "05913", "NW", "Dortmund",
        "https://www.dortmund.de/dortmund/projekte/rathaus/publikationen/downloads/dobeka-29-2026_web.pdf",
        "verordnung", "betteln,lagern", "Dortmunder Bekanntmachungen (Amtsblatt) Nr. 29/2026 S. 634: Ordnungsbehördliche Verordnung vom 21.07.2026",
        "Ordnungsbehördliche Verordnung über die Aufrechterhaltung der öffentlichen Sicherheit und Ordnung in der Stadt Dortmund",
        "2026-07-24", "Amtsblatt der Stadt Dortmund Nr. 29 – 82. Jahrgang Freitag, 24.07.2026", "original",
        "Bans camping, lagern and overnighting on streets and in parks outside areas released for it, and aggressive "
        "begging by direct person-to-person pressure (e.g. with a dog, blocking the way, touching) (§ 7 Abs. 1); "
        "any begging within 5 m of outdoor dining. In force 01.08.2026, limited to 31.12.2033.",
        ["Ordnungsbehördliche Verordnung über die Aufrechterhaltung der öffentlichen Sicherheit und Ordnung in der Stadt Dortmund vom 21.07.2026",
         "freigegebenen Flächen zu lagern, zu campieren",
         "auf Straßen und in Anlagen durch unmittelbares Einwirken von Person zu Person aggressiv zu betteln",
         "kreis von fünf Metern um Außengastronomien jegliches"],
        note="promulgation in the city's Amtsblatt (two-column layout; needles avoid column breaks); the Ortsrecht page links only a signed scan without text layer",
        in_force_from="2026-08-01"),
    _mu("kassel_gefavo", "06611", "HE", "Kassel",
        "https://www.kassel.de/satzungen/3.01-gefahrenabwehrverordnung.php",
        "verordnung", "betteln,lagern,alkohol", "Kasseler Stadtrecht 3.01 Gefahrenabwehrverordnung vom 14.09.2015",
        "Gefahrenabwehrverordnung über die Aufrechterhaltung der Sicherheit und Ordnung auf und an den Straßen und sonstigen öffentlichen Flächen im Gebiet der Stadt Kassel",
        "2015-09-14", "Gefahrenabwehrverordnung vom 14. September 2015 am 7. Oktober 2015", "consolidated",
        "Bans any behaviour on streets and public areas that endangers or unavoidably obstructs others, e.g. "
        "drunkenness-related disturbances, disruptive 'Lagern' or sleeping overnight, aggressive or organised begging (§ 8).",
        ["störendes Lagern oder Nächtigen, aggressives oder organisiertes Betteln"],
        note="HTML reading copy on kassel.de", in_force_from="2015-10-07"),
    # ---- batch 8 (2026-11-21): further ordinances / Sondernutzungssatzungen ----
    _mu("hamburg_alkverbv_hbf", "02000", "HH", "Hamburg",
        "https://www.luewu.de/wp-content/uploads/2025/08/GVBL_HH_2024-10.pdf",
        "verordnung", "alkohol", "HmbGVBl. 2024 Nr. 10 S. 80: Verordnung vom 26.03.2024 (Gliederungsnummer 2012-1-5), geändert durch Verordnung vom 10.03.2026 (HmbGVBl. 2026 Nr. 10 S. 104)",
        "Verordnung über das Verbot des Verzehrs und des Mitführens alkoholischer Getränke auf öffentlichen Flächen im Bereich des Hauptbahnhofes",
        "2026-03-10", "„31. März 2026“ durch die Textstelle „31. März 2029“ ersetzt. Gegeben in der Versammlung des Senats, Hamburg, den 10. März 2026", "original",
        "Senate ordinance banning drinking, and carrying alcohol intended for consumption there, in the area around "
        "Hamburg Hauptbahnhof outside buildings and licensed outdoor restaurant areas (§§ 1-2); fine up to 200 EUR "
        "(§ 3). In force 01.04.2024; the amendment of 10.03.2026 extends it from 31.03.2026 to 31.03.2029 (§ 4).",
        ["Verordnung über das Verbot des Verzehrs und des Mitführens alkoholischer Getränke auf öffentlichen Flächen im Bereich des Hauptbahnhofes",
         "Gegeben in der Versammlung des Senats, Hamburg, den 26. März 2024",
         "Diese Verordnung tritt am 1. April 2024 in Kraft"],
        version_url="https://www.luewu.de/wp-content/uploads/2026/03/GVBL_HH_2026-10.pdf",
        note="base text HmbGVBl. 2024 Nr. 10 plus the 2026 amendment (HmbGVBl. 2026 Nr. 10, archived as the amendment "
             "source); no official consolidated text. Issues as published by the printer Lütcke & Wulff (luewu.de; robots "
             "allow, no TDM reservation; Impressum forbids commercial reuse)",
        in_force_from="2024-04-01",
        lic="Amtliches Werk (§ 5 Abs. 1 UrhG): Verordnung des Senats der Freien und Hansestadt Hamburg, amtlich verkündet im "
            "HmbGVBl.; Ausgabe des Verlags Lütcke & Wulff (luewu.de, Impressum: keine gewerbliche Nutzung ohne Zustimmung); zitiert mit Fundstelle",
        ends_on='2029-04-01', ends_needle="„31. März 2026“ durch die Textstelle „31. März 2029“ ersetzt. Gegeben in der Versammlung des Senats, Hamburg, den 10. März 2026"),
    _mu("bremerhaven_ortsgesetz_ordnung", "04012", "HB", "Bremerhaven",
        "https://www.transparenz.bremen.de/sixcms/detail.php?gsid=bremen2014_tp.c.72517.de&template=00_html_to_pdf_d",
        "verordnung", "betteln,alkohol", "Ortsgesetz über die öffentliche Ordnung in der Stadt Bremerhaven (Brem.GBl. 2004, 1), zuletzt geändert durch Ortsgesetz vom 03.09.2026 (Brem.GBl. S. 661)",
        "Ortsgesetz über die öffentliche Ordnung in der Stadt Bremerhaven",
        "2026-09-03", "zuletzt geändert durch Ortsgesetz vom 03.09.2026 (Brem.GBl. S. 661)", "consolidated",
        "Bans using children for begging and aggressive begging, in particular pressing, holding or touching people "
        "(§ 10); bans settling down permanently on streets, publicly accessible areas or benches to drink alcohol where "
        "this unreasonably impairs use by others (§ 13 Nr. 1). This version has no lagern/sleeping clause.",
        ["§ 10 Missbräuchliche Formen der Bettelei (1) Der Missbrauch von Kindern zur Bettelei ist untersagt",
         "Ferner ist die aggressive Bettelei untersagt, insbesondere soweit Personen bedrängt, festgehalten oder berührt werden",
         "1. sich dauerhaft zum Zwecke des Alkoholkonsums auf Straßen, der Öffentlichkeit zugänglichen Flächen oder Bänken niederzulassen und dadurch die Nutzung durch andere unzumutbar zu beeinträchtigen",
         "Inkrafttreten: 28.07.2012"],
        note="manual archive by the Lead, 2026-11-21: transparenz.bremen.de record gsid c.72517 (current; Inkrafttreten "
             "28.07.2012, last amended 03.09.2026). The PDF carries watermark fragments; needles are taken from clean passages. "
             "The validity range could not be cross-checked on the 72517 HTML page: a single honest-UA request from the box got "
             "an HTTP 302 with no content and was not retried, so the dates rest on the PDF header. The older record c.72514 "
             "(in force 25.03.2003) is kept only for reference and is not ingested",
        local="muni_bremerhaven_ortsgesetz_ordnung.pdf"),
    # ---- batch 11 (2026-11-21): systematic pass over the 107 kreisfreie Städte ----
    _mu("delmenhorst_obdach_geb", "03401", "NI", "Delmenhorst",
        "https://www.delmenhorst.de/medien/bindata/rathaus-online/satzungen/920UnterbringungsgebS251020.pdf",
        "satzung", "obdach_gebuehr", "Delmenhorster Ortsrecht 9-20 Unterbringungsgebührensatzung vom 27.04.2020 i.d.F. der 3. Änderungssatzung vom 20.10.2025",
        "Satzung der Stadt Delmenhorst über die Erhebung von Gebühren für die Benutzung von Obdachlosen- und Flüchtlingsunterkünfte",
        "2025-10-31", "die 3. Änderungssatzung vom 20.10.2025, verkündet im Amtsblatt für die Stadt Delmenhorst Nr. 34 vom 30.10.2025, S. 4", "consolidated",
        "Fee statute for homeless and refugee accommodation: monthly fee per m² for flats (homeless rate), surcharges "
        "for heating and electricity, and a monthly fee per sleeping place in shared accommodation.",
        ["Für stadteigene und angemietete Gemeinschaftsunterkünfte beträgt die Benutzungsgebühr je Schlafplatz 198,96 Euro"],
        fees=[_fee("obdach_gebuehr_eur_m2_monat", 10.83, "EUR/m2/Monat",
                   "1.1 für Obdachlosenunterkünfte 10,83 Euro je qm", "§ 3 Abs. 1 Nr. 1.1", 2025),
              _fee("obdach_gebuehr_eur_platz_monat__gemeinschaftsunterkunft", 198.96, "EUR/Platz/Monat",
                   "platz 198,96 Euro. In diesem Betrag sind die Kosten", "§ 3 Abs. 3 (je Schlafplatz; two-column layout splits the sentence)", 2025)]),
    _mu("emden_obdach_geb", "03402", "NI", "Emden",
        "https://www.emden.de/fileadmin/media/stadtemden/PDF/Verwaltung/Ortsrecht/52_2_gebuehren.pdf",
        "satzung", "obdach_gebuehr", "Emder Ortsrecht 52-2 Gebührensatzung Obdachlosenunterkünfte vom 27.04.2005 i.d.F. vom 18.12.2014",
        "Satzung über die Erhebung von Gebühren für die Benutzung von Obdachlosenunterkünften in der Stadt Emden",
        "2014-12-20", "in der Fassung vom 18.12.2014 (Amtsblatt LKR. Aurich/Stadt Emden 2014 S. 819 / in Kraft seit 20.12.2014)", "consolidated",
        "Fee statute for the homeless shelters: daily fee per person for a bed in the overnight shelter 'Alte Liebe'; "
        "in the Graf-Enno-Straße shelters 1/30 of the monthly rent the city pays per day.",
        ["beträgt die Gebühr für jeden Tag der Unterkunftsbereitstellung 1/30 des Monatsbetrages"],
        fees=[_fee("obdach_notuebernachtung_eur_person_tag", 5, "EUR/Person/Tag",
                   "beträgt die Gebühr je Person 5,-- Euro netto täglich", "§ 2 Abs. 1 (Übernachtungseinrichtung „Alte Liebe“)", 2014)]),
    _mu("worms_obdach", "07319", "RP", "Worms",
        "https://www.worms.de/neu-de-wAssets/docs/buergerservice/ortsrecht-satzungen/7700_Satzung_Benutzung-Obdachlosenunterkuenfte.pdf",
        "satzung", "obdach", "Wormser Ortsrecht 7/70/0 Obdachlosenunterkunftssatzung vom 27.01.1997",
        "Satzung über die Benutzung von Obdachlosenunterkünften in der Stadt Worms",
        "1997-01-27", "SATZUNG über die Benutzung von Obdachlosenunterkünften in der Stadt Worms vom 27.Januar 1997", "original",
        "Use statute for the city's homeless shelters (public-law use, allocation, duties); fees per month based on the "
        "rental value, capped at the city's expected costs; no fixed amounts printed.",
        ["(1) Für die Benutzung der zugewiesenen Unterkünfte erhebt die Stadt Benutzungsgebühren."]),
    _mu("worms_gefavo", "07319", "RP", "Worms",
        "https://www.worms.de/neu-de-wAssets/docs/buergerservice/ortsrecht-satzungen/1240_Gefahrenabwehrverordnung.pdf",
        "verordnung", "betteln,alkohol", "Wormser Ortsrecht 1/24/0 Gefahrenabwehrverordnung vom 07.09.2007 (Amtsblatt Nr. 40/2007)",
        "Gefahrenabwehrverordnung zur Aufrechterhaltung der öffentlichen Sicherheit und Ordnung auf öffentlichen Straßen und in öffentlichen Anlagen der Stadt Worms",
        "2007-09-28", "Veröffentlicht am 28.09.2007 im Amtsblatt Nr. 40/2007. In Kraft getreten mit Wirkung vom 05.10.2007", "original",
        "On public streets and in public facilities bans aggressive or disruptive begging, also with or by minors or "
        "animals, lingering visibly drunk in a way that disturbs public order, and settling down to consume alcohol "
        "where the resulting behaviour harasses or endangers others.",
        ["1. in aggressiver oder störender Form, auch mit oder mittels Minderjähriger oder Tieren, zu betteln",
         "2. im Zustand deutlicher Trunkenheit zu verweilen und hierdurch die öffentliche Ordnung zu stören",
         "sich zum Konsum von Alkohol oder anderen berauschenden Mitteln niederzulassen"],
        in_force_from="2007-10-05", note="RLP Gefahrenabwehrverordnungen lapse 20 years after entry into force (§ 46 Abs. 2 POG)"),
    _mu("kaiserslautern_gefavo", "07312", "RP", "Kaiserslautern",
        "https://www.kaiserslautern.de/mb/themen/stadtverwaltung/ortsrecht/pdf/3.1_gefahrenabwehrverordnung_sicherheit_und_ordnung_stra%C3%9Fen_und_anlagen_neufassung.pdf",
        "verordnung", "betteln,lagern,alkohol", "Kaiserslauterer Ortsrecht 3.1 Gefahrenabwehrverordnung vom 04.02.2019",
        "Gefahrenabwehrverordnung zur Aufrechterhaltung der öffentlichen Sicherheit und Ordnung auf öffentlichen Straßen und in öffentlichen Anlagen der Stadt Kaiserslautern",
        "2019-02-04", "Kaiserslautern, 4.2.2019 Stadtverwaltung Kaiserslautern", "original",
        "On public streets and in parks bans aggressive or disruptive begging or begging involving minors; in parks "
        "bans camping or setting up caravans or motorhomes outside designated areas; bans harassing others as a result "
        "of alcohol or drug consumption. Lapses 20 years after entry into force.",
        ["1. In aggressiver oder störender Form oder unter Mitwirkung Minderjähriger, zu betteln",
         "1. außerhalb der für diesen Zweck ausgewiesenen Flächen zu zelten, oder Wohnwagen oder Wohnmobile aufzustellen",
         "aufgrund des Konsums von Alkohol oder anderer berauschender Mittel durch Anpöbeln"]),
    _mu("bamberg_obdach_geb", "09461", "BY", "Bamberg",
        "https://www.stadt.bamberg.de/media/custom/329_71_1.PDF",
        "satzung", "obdach_gebuehr", "Bamberger Stadtrecht ObdUGebS vom 10.01.2017, zuletzt geändert durch Satzung vom 06.02.2025",
        "Gebührensatzung über die Benutzung der Obdachlosenunterkünfte der Stadt Bamberg (Obdachlosenunterkunftsgebührensatzung – ObdUGebS)",
        "2025-02-21", "zuletzt geändert durch Satzung vom 06. Februar 2025 (Amtsblatt der Stadt Bamberg - vom 21. Februar 2025 Nr. 4)", "consolidated",
        "Monthly fee per m² of living space for the three city homeless shelters (Theresienstraße 2, Kapellenstraße 28, "
        "Altenburger Straße 42); individually rented flats used as shelters are charged at their gross rent.",
        ["Die monatlichen Benutzungsgebühren betragen je Quadratmeter Wohnfläche für die Obdachlosenunterkunft"],
        fees=[_fee("obdach_gebuehr_eur_m2_monat__theresienstrasse", 9.62, "EUR/m2/Monat",
                   "Theresienstraße 2 9,62 €", "§ 4 Abs. 1", 2025),
              _fee("obdach_gebuehr_eur_m2_monat__kapellenstrasse", 7.52, "EUR/m2/Monat",
                   "Kapellenstraße 28 7,52 €", "§ 4 Abs. 1", 2025),
              _fee("obdach_gebuehr_eur_m2_monat__altenburger_strasse", 12.26, "EUR/m2/Monat",
                   "Altenburger Straße 42 12,26 €", "§ 4 Abs. 1", 2025)]),
    _mu("bayreuth_obdach_geb", "09462", "BY", "Bayreuth",
        "https://formular-server.de/BT_FS/findform?areashortname=bt_oe&formtecid=2&shortname=743",
        "satzung", "obdach_gebuehr", "Bayreuther Stadtrecht 743 Gebührensatzung für die Obdachlosenunterkünfte vom 29.11.2017 (Amtsblatt Nr. 20 vom 15.12.2017)",
        "Gebührensatzung für die Obdachlosenunterkünfte der Stadt Bayreuth",
        "2017-12-15", "Veröffentlicht: Amtsblatt der Stadt Bayreuth Nr. 20 vom 15. Dez. 2017", "original",
        "Monthly fee per bed including all utilities in the two city homeless shelters (Cosima-Wagner-Straße 7, "
        "Lenbachstraße 22); rented flats or rooms at gross cold rent plus surcharges; 1/30 per day for part months.",
        ["Bayreuth, den 29. November 2017",
         "Diese Satzung tritt am Ersten des auf die Veröffentlichung im Amtsblatt der Stadt Bayreuth folgenden Monats in Kraft"],
        fees=[_fee("obdach_gebuehr_eur_platz_monat", 150.00, "EUR/Platz/Monat",
                   "die Cosima-Wagner-Straße 7 je Bett, Mitbenutzung Wärmestube, Küche und Bad einschließlich aller Nebenkosten monatlich 150,00 €",
                   "§ 3", 2017),
              _fee("obdach_gebuehr_eur_platz_monat__lenbachstrasse", 150.00, "EUR/Platz/Monat",
                   "die Lenbachstraße 22 je Bett, Mitbenutzung Küche und Bad einschließlich aller Nebenkosten monatlich 150,00 €",
                   "§ 3", 2017)],
        note="official Stadtrecht PDF served by the city's form server formular-server.de (linked from bayreuth.de Stadtrecht 7); "
             "b20: manual archive via browser, 2026-11-23 (Lead), file muni_bayreuth_obdach.pdf -- robots.txt of formular-server.de "
             "answers HTTP 418, so the host does not permit automated fetching and the file was archived once by hand and is read "
             "from the archive only; in force on the first of the month after publication (15.12.2017), i.e. 01.01.2018",
        in_force_from="2018-01-01", local="muni_bayreuth_obdach.pdf"),
    _mu("rosenheim_obdach_geb", "09163", "BY", "Rosenheim",
        "https://www.rosenheim.de/fileadmin/Politik-und-Verwaltung/Ortsrecht/Soziales/Satzung_fuer_Amtsblatt_und_Homepage.pdf",
        "satzung", "obdach_gebuehr", "Rosenheimer Ortsrecht Unterkunftsanlagengebührensatzung vom 26.02.2026",
        "Gebührensatzung zur Satzung über die Benutzung der Unterkunftsanlagen der Stadt Rosenheim, Unterkunftsanlagengebührensatzung",
        "2026-02-26", "Unterkunftsanlagengebührensatzung Vom 26.02.2026", "original",
        "Fees for the city's accommodation facilities, which under the Unterkunftsanlagensatzung serve the temporary "
        "housing of local residents who are or are about to become homeless: flat monthly fee per unit in two "
        "facilities, per-person rates for shared accommodation and per-flat rates for single units (Anlage 1).",
        ["Gleichzeitig treten die Bestimmungen der Unterkunftsanlagengebührensatzung vom 27. Februar 2025 außer Kraft"],
        fees=[_fee("obdach_gebuehr_eur_wohneinheit_monat", 400.00, "EUR/Wohneinheit/Monat",
                   "Brunnholzstraße 57 und Traberhofstraße 48 beträgt die Gebühr je Wohneinheit monatlich 400,00 Euro", "§ 2 Abs. 1", 2026)],
        extra=[("https://www.rosenheim.de/fileadmin/Politik-und-Verwaltung/Ortsrecht/Ortsrecht/850a.pdf",
                ["zur vorübergehenden Unterbringung von ortsansässigen Personen, die obdachlos sind oder denen Obdachlosigkeit droht"])]),
    _mu("passau_obdach_geb", "09262", "BY", "Passau",
        "https://www.passau.de/fileadmin/Homepage_Stadt_Passau/2._Rathaus_und_Buergerservice/Politik/Stadtrecht__Satzungen___Verordnungen_/24-11-11_Lesefassung_Gebuehrensatzung_Obdachlosenunterkuenfte_1_.pdf",
        "satzung", "obdach_gebuehr", "Passauer Stadtrecht Obdachlosengebührensatzung vom 03.07.2017 i.d.F. der Änderung vom 11.11.2024 (Lesefassung)",
        "Satzung über die Erhebung von Gebühren für die Obdachlosenunterkünfte in Passau (Obdachlosengebührensatzung)",
        "2024-11-20", "sowie vom 11.11.2024 (Amtsblatt Nr. 25 vom 20.11.2024)", "consolidated",
        "Fee per m² for the homeless hostel rooms at Danziger Straße (resulting monthly amounts per room size listed) and "
        "a daily fee per user for a bed in the short-stay room. Reading version; only the gazette notices are binding.",
        ["Für einen Schlafplatz im Kurzzeitzimmer wird pro Tag und Benutzer ein Betrag in Höhe von 6,06 EUR berechnet"],
        fees=[_fee("obdach_gebuehr_eur_m2_monat", 25.81, "EUR/m2/Monat",
                   "Für die Benutzung des Obdachlosenwohnheims Danziger Straße 18 beträgt die Gebühr 25,81 EUR pro qm", "§ 4 Abs. 1", 2024),
              _fee("obdach_notuebernachtung_eur_person_tag", 6.06, "EUR/Person/Tag",
                   "pro Tag und Benutzer ein Betrag in Höhe von 6,06 EUR", "§ 4 Abs. 5", 2024)]),
    _mu("schweinfurt_obdach_geb", "09662", "BY", "Schweinfurt",
        "https://www.schweinfurt.de/media/www.schweinfurt.de/org/med_3976/30629_gebuehrensatzung_finale_version.pdf",
        "satzung", "obdach_gebuehr", "Schweinfurter Stadtrecht Gebührensatzung Obdachlosenunterkunft vom 07.12.2018 (SWTB vom 31.12.2018, S. 19)",
        "Gebührensatzung für die Benutzung der Obdachlosenunterkunft der Stadt Schweinfurt",
        "2018-12-31", "Vom 07.12.2018 (SWTB vom 31.12.2018, S. 19)", "original",
        "Monthly fee per m² of living space in the city homeless shelter; a higher rate applies where the allocation "
        "rested on false statements or the occupant owns property.",
        ["Schweinfurt, 07.12.2018 STADT SCHWEINFURT"],
        fees=[_fee("obdach_gebuehr_eur_m2_monat", 5.00, "EUR/m2/Monat",
                   "Die Gebühr beträgt monatlich je Quadratmeter Wohnfläche 5,00 Euro", "§ 3 Abs. 1", 2018)],
        note="the box host fails TLS for schweinfurt.de; raw fetched from the deck with the same honest UA (robots allow /media/)"),
    _mu("coburg_obdach_geb", "09463", "BY", "Coburg",
        "https://www.coburg.de/medien/dokumente/stadtpolitik/stadtrecht/132-ObuGebS.pdf",
        "satzung", "obdach_gebuehr", "Coburger Stadtrecht 132 ObuGebS vom 24.10.2014, zuletzt geändert durch 1. Änderungssatzung vom 21.07.2016",
        "Satzung über die Erhebung von Gebühren für die Obdachlosenunterkünfte der Stadt Coburg (ObuGebS)",
        "2016-08-01", "zuletzt geändert durch 1. Änderungssatzung vom 21.07.2016 (Coburger Amtsblatt Nr. 27 vom 29.07.2016) in der vom 01.08.2016 an gültigen Fassung", "consolidated",
        "Fee per night in the city homeless shelters, reduced for children and young people under 18.",
        ["Für die Benutzung der Obdachlosenunterkünfte ist eine Gebühr von 10,00 Euro je Übernachtung zu zahlen"],
        fees=[_fee("obdach_notuebernachtung_eur_person_nacht", 10.00, "EUR/Person/Nacht",
                   "eine Gebühr von 10,00 Euro je Übernachtung zu zahlen", "§ 3", 2016),
              _fee("obdach_notuebernachtung_eur_person_nacht__unter18", 5.00, "EUR/Person/Nacht",
                   "ist eine reduzierte Gebühr von 5,00 Euro je Übernachtung zu zahlen", "§ 3", 2016)]),
    _mu("schwabach_obdach_geb", "09565", "BY", "Schwabach",
        "https://www.schwabach.de/images/referate/referat_2/ortsrecht/Geb%C3%BChrensatzung_f%C3%BCr_die_Obdachlosenunterk%C3%BCnfte.pdf",
        "satzung", "obdach_gebuehr", "Schwabacher Ortsrecht ObUGebS vom 24.08.2004, Stand 2. Änderungssatzung vom 26.08.2024",
        "Gebührensatzung für die Obdachlosenunterkünfte der Stadt Schwabach (Obdachlosenunterkünftegebührensatzung – ObUGebS)",
        "2024-08-26", "(Stand: 2. Satzung zur Änderung der Satzung für die Erhebung von Gebühren für die Übergangswohnanlage der Stadt Schwabach vom 26.08.2024)", "consolidated",
        "Monthly fee per m² for the transitional housing complex Schwalbenweg 2–8 and for the emergency flat "
        "Konrad-Adenauer-Str. 49 b used to house homeless people.",
        ["Schwabach, 24.08.2004"],
        fees=[_fee("obdach_gebuehr_eur_m2_monat__uebergangswohnanlage", 7.40, "EUR/m2/Monat",
                   "„Schwalbenweg 2 – 8“ werden auf monatlich 7,40 € je Quadratmeter festgesetzt", "§ 3 Abs. 1", 2024),
              _fee("obdach_gebuehr_eur_m2_monat__notwohnung", 13.60, "EUR/m2/Monat",
                   "„Konrad-Adenauer-Str. 49 b“ werden auf monatlich 13,60 € je Quadratmeter festgesetzt", "§ 3 Abs. 2", 2024)]),
    _mu("kempten_obdach_geb", "09763", "BY", "Kempten (Allgäu)",
        "https://kempten.de/file/II-28_Obdachlosenunterkunftsgeb%c3%bchrensatzung.pdf",
        "satzung", "obdach_gebuehr", "Kemptener Stadtrecht II/28 Obdachlosenunterkunftsgebührensatzung (OGS) vom 14.04.2021, Anlage Stand 01.05.2023",
        "Gebührensatzung zur Satzung über die Benutzung der Obdachlosenunterkünfte der Stadt Kempten (Allgäu) (Obdachlosenunterkunftsgebührensatzung - OGS)",
        "2023-05-01", "Aktualisierungsstand: 01.05.2023", "consolidated",
        "Fee statute for the city homeless shelters; the annex sets a monthly use fee per housing unit plus a flat "
        "utilities charge per unit.",
        ["(Obdachlosenunterkunftsgebührensatzung - OGS) Vom 14. April 2021"],
        fees=[_fee("obdach_gebuehr_eur_wohneinheit_monat", 64.00, "EUR/Wohneinheit/Monat",
                   "Nutzungsgebühr pro Wohneinheit/Monat 64,00 €", "Anlage", 2023),
              _fee("obdach_nebenkosten_eur_wohneinheit_monat", 116.00, "EUR/Wohneinheit/Monat",
                   "Nebenkostenpauschale pro Wohneinheit/Monat 116,00 €", "Anlage", 2023),
              _fee("obdach_gebuehr_gesamt_eur_wohneinheit_monat", 180.00, "EUR/Wohneinheit/Monat",
                   "Nutzungsgebühr gesamt/Monat 180,00 €", "Anlage", 2023)]),
    # ---- batch 12 (2026-11-21): kreisfreie sweep continued ----
    _mu("frankenthal_wohnheim", "07311", "RP", "Frankenthal (Pfalz)",
        "https://www.frankenthal.de/stadt-frankenthal/de/rathaus/verwaltung/ortsrecht/dateien-ortsrecht/5-01-wohnheimsatzung.pdf",
        "satzung", "obdach", "Frankenthaler Ortsrecht 5/1 Wohnheimsatzung (WohnheimS) vom 16.09.2015",
        "Satzung zur Unterbringung obdachloser Personen sowie zur Unterbringung Leistungsberechtigter nach dem Asylbewerberleistungsgesetz (AsylbLG) in den städtischen Wohnheimen Mahlastraße 35, Albertstraße 18, Hammstraße 12 und Heßheimer Straße 46 (Wohnheimsatzung – WohnheimS)",
        "2015-09-16", "Frankenthal (Pfalz), den 16.09.2015", "original",
        "Use statute for the four city hostels that temporarily house homeless people (and asylum-seekers): public-law "
        "use, start and end of use, duties; fees per the separate fee statute.",
        ["Die Nutzung der Wohnheime ist gebührenpflichtig. Die Höhe der Gebühren richtet sich nach der jeweils geltenden Gebührensatzung"]),
    _mu("frankenthal_gefavo", "07311", "RP", "Frankenthal (Pfalz)",
        "https://www.frankenthal.de/stadt-frankenthal/de/rathaus/verwaltung/ortsrecht/dateien-ortsrecht/3-02-gefahrenabwehrverordnung.pdf",
        "verordnung", "betteln,alkohol", "Frankenthaler Ortsrecht 3/2 Gefahrenabwehrverordnung (GAVO Str. u. Anl.) vom 24.09.2020",
        "Gefahrenabwehrverordnung zur Aufrechterhaltung der öffentlichen Sicherheit und Ordnung auf öffentlichen Straßen und in öffentlichen Anlagen der Stadt Frankenthal (Pfalz)",
        "2020-09-24", "Frankenthal (Pfalz), 24.09.2020 STADTVERWALTUNG FRANKENTHAL (PFALZ)", "original",
        "On public streets and in parks bans aggressive or disruptive begging, including with or by minors, and harassing "
        "others in particular as a result of alcohol or drug consumption. In force 25.09.2020 until 24.09.2040.",
        ["1. in aggressiver oder störender Form, insbesondere auch mit oder durch Minderjährige, zu betteln",
         "andere Personen oder die Allgemeinheit insbesondere aufgrund des Konsums von Alkohol oder berauschenden Mitteln insbesondere durch Anpöbeln",
         "Diese Gefahrenabwehrverordnung tritt am 25.09.2020 in Kraft und mit Ablauf des 24.09.2040 außer Kraft"],
        in_force_from="2020-09-25",
        ends_on='2040-09-25', ends_needle='Diese Gefahrenabwehrverordnung tritt am 25.09.2020 in Kraft und mit Ablauf des 24.09.2040 außer Kraft'),
    _mu("pirmasens_obdach_geb", "07317", "RP", "Pirmasens",
        "https://www.pirmasens.de/downloads/ortsrecht/obdachlosenunterkunft-2021.pdf",
        "satzung", "obdach_gebuehr", "Pirmasenser Ortsrecht Gebührensatzung Obdachlosenunterkünfte vom 08.03.2021",
        "Satzung über die Erhebung von Gebühren für die Benutzung von Obdachlosenunterkünften der Stadt Pirmasens",
        "2021-03-09", "Pirmasens, den 09.03.2021", "original",
        "Fee statute for the city homeless shelters: fee based on floor area (or actual rent/hotel cost for rented "
        "units) plus operating costs; the amounts themselves are set in the budget statute, not in this text.",
        ["Die Gebühr für die Benutzung der Unterkünfte einschließlich der Betriebskosten ist der Haushaltssatzung in ihrer gültigen Fassung zu entnehmen",
         "OBDACHLOSENUNTERKÜNFTEN DER STADT PIRMASENS Vom 08.03.2021"]),
    _mu("zweibruecken_gefavo", "07320", "RP", "Zweibrücken",
        "https://www.zweibruecken.de/de/verwaltung/aemter/rechtsamt/ortsrecht-satzungen/gefahrenabwehrverordnung-3.1.1-zur-aufrechterhaltung-der-oeffentlichen-sicherheit-und-ordnung-auf-oeffentlichen-strassen.pdf",
        "verordnung", "betteln,lagern,alkohol", "Zweibrücker Ortsrecht 3.1-1 Gefahrenabwehrverordnung (Stadtratszustimmung 18.05.2022), in Kraft 01.07.2022",
        "Gefahrenabwehrverordnung zur Aufrechterhaltung der öffentlichen Sicherheit und Ordnung auf öffentlichen Straßen und in öffentlichen Anlagen der Stadt Zweibrücken",
        "2022-07-01", "Diese Gefahrenabwehrverordnung tritt am 1. Juli 2022 in Kraft und mit Ablauf des 30.06.2042 außer Kraft", "original",
        "On public streets and in parks bans aggressive or disruptive begging and harassing others as a result of "
        "alcohol or drug consumption; in parks bans camping or setting up caravans or motorhomes. In force until 30.06.2042.",
        ["1. in aggressiver oder störender Form zu betteln",
         "andere Personen oder die Allgemeinheit aufgrund des Konsums von Alkohol oder anderen berauschenden Mitteln durch Anpöbeln",
         "1. zu zelten oder Wohnwagen bzw. Wohnmobile aufzustellen", 'Diese Gefahrenabwehrverordnung tritt am 1. Juli 2022 in Kraft und mit Ablauf des 30.06.2042 außer Kraft'],
        in_force_from="2022-07-01",
        ends_on='2042-07-01', ends_needle='Diese Gefahrenabwehrverordnung tritt am 1. Juli 2022 in Kraft und mit Ablauf des 30.06.2042 außer Kraft'),
    _mu("badenbaden_polvo_alk", "08211", "BW", "Baden-Baden",
        "https://www.baden-baden.de/site/Baden-Baden/get/params_E1393278018_Dattachment/3857760/01-08%20Polizeiverordnung%20Alkohol%20und%20Betteln.pdf",
        "verordnung", "betteln,alkohol", "Baden-Badener Ortsrecht 01-08 Polizeiverordnung Alkoholmissbrauch und aggressives Betteln vom 12.03.2013",
        "Polizeiverordnung der Ortspolizeibehörde Baden-Baden zum Schutz vor erheblichen Belästigungen der Allgemeinheit durch Alkoholmissbrauch und aggressives sowie gewerbsmäßiges Betteln",
        "2013-04-04", "Diese Satzung wurde am 04. April 2013 in der BNN und im BT öffentlich bekannt gemacht", "original",
        "Bans aggressive or commercial begging and inciting minors to it, and lingering or settling outside licensed "
        "outdoor bar areas mainly to drink alcohol where the effects are liable to significantly harass, obstruct or "
        "endanger others.",
        ["das aggressive oder gewerbsmäßige Betteln sowie das Anstiften von Minderjährigen zu diesen Arten des Bettelns",
         "das Verweilen oder Niederlassen außerhalb von Freiausschankflächen ausschließlich oder überwiegend zum Zwecke des Alkoholgenusses",
         "Ausgefertigt: Baden-Baden, den 12.03.2013"]),
    _mu("badenbaden_obdach_geb", "08211", "BW", "Baden-Baden",
        "https://www.baden-baden.de/site/Baden-Baden/get/params_E1580391962_Dattachment/3856830/Satzung%20der%20Stadt%20Baden-Baden%20%c3%bcber%20die%20Erhebung%20von%20Geb%c3%bchren%20f%c3%bcr%20die%20Benutzung%20der%20Obdachlosen-%20und%20Fl%c3%bcchtlingsunterk%c3%bcnfte%20(05.12.2024).pdf",
        "satzung", "obdach_gebuehr", "Baden-Badener Ortsrecht Gebührensatzung Obdachlosen- und Flüchtlingsunterkünfte vom 25.11.2024, in Kraft 01.04.2025",
        "Satzung der Stadt Baden-Baden über die Erhebung von Gebühren für die Benutzung der Obdachlosen- und Flüchtlingsunterkünfte",
        "2024-11-25", "Baden-Baden, 25. November 2024", "original",
        "Monthly fee per place incl. administration and operating costs: separate rates for initial refugee housing, "
        "follow-up housing and housing under homelessness law; caps for households of 2–8 persons.",
        ["Diese Satzung tritt zum 01.04.2025 in Kraft"],
        fees=[_fee("obdach_gebuehr_eur_person_monat", 414, "EUR/Person/Monat",
                   "für eine Person in obdachlosenrechtlicher Unterbringung 414,- €", "§ 4 Abs. 2", 2025)],
        in_force_from="2025-04-01"),
    _mu("heilbronn_polvo", "08121", "BW", "Heilbronn",
        "https://www.heilbronn.de/fileadmin/daten/stadtheilbronn/formulare/rathaus/stadtrecht/1_Oeffentliche_Sicherheit_und_Ordnung/1_2_Allgemeine_Polizeiverordnung.pdf",
        "verordnung", "betteln,lagern,alkohol", "Heilbronner Stadtrecht 1/2 Allgemeine Polizeiverordnung (APoVO) vom 18.12.2015, geändert durch Verordnung vom 22.06.2020",
        "Polizeiverordnung der Stadt Heilbronn zur Aufrechterhaltung der öffentlichen Sicherheit und Ordnung und zur Abwehr von umweltschädlichem Verhalten (APoVO)",
        "2020-07-01", "Geändert durch Verordnung vom 22.06.20 (Amtsbl. Nr. 13 vom 01.07.20), in Kraft ab 02.07.20", "consolidated",
        "On public streets and in green spaces bans begging that seeks physical closeness or is otherwise particularly "
        "intrusive, commercially organised begging and begging with or by minors; tents, caravans and motorhomes may "
        "not be used for stays outside campsites; no alcohol on playgrounds or school grounds.",
        ["das die körperliche Nähe suchende oder sonst besonders aufdringliche Betteln, das gewerbs mäßig organisierte Betteln oder das Betteln mittels oder mit Minderjährigen",
         "Zelte, Wohnwagen und Wohnmobile dürfen außerhalb baurechtlich genehmigter Campingplätze zum Aufenthalt von Menschen",
         "darf kein Alkohol konsumiert oder mitgeführt werden"]),
    _mu("pforzheim_polvo", "08231", "BW", "Pforzheim",
        "https://www.pforzheim.de/fileadmin/user_upload/hauptamt/stadtrecht/1_SICHORD/1-7.pdf",
        "verordnung", "betteln,lagern,alkohol", "Pforzheimer Stadtrecht 1.7 Polizeiverordnung (Gemeinderat 14.02.2023, bekannt gemacht 15.03.2023)",
        "Polizeiverordnung der Ortspolizeibehörde Pforzheim zur Erhaltung der öffentlichen Sicherheit und Ordnung und gegen umweltschädliches Verhalten",
        "2023-03-15", "Bekanntmachung: 15.03.2023 Inkrafttreten: 16.03.2023", "original",
        "Bans aggressive, insulting, commercial, physically close or otherwise particularly intrusive begging and inciting "
        "minors to it; bans alcohol on and within 50 m of playgrounds and on nursery and school grounds; tenting and "
        "camping on any plot only with the local police authority's permission.",
        ["das aggressive, beleidigende, gewerbsmäßige und das die körperliche Nähe suchende oder sonst besonders aufdringliche Betteln",
         "Auf sämtlichen Grundstücken ist das Zelten und Campen nur mit Erlaubnis der Ortspolizeibehörde gestattet",
         "das Konsumieren von Alkohol und das Rauchen auf Kinderspielplätzen, an Spielpunkten und innerhalb eines Radius von 50 Metern"],
        in_force_from="2023-03-16"),
    _mu("trier_gefavo", "07211", "RP", "Trier",
        "https://www.trier.de/media/www.trier.de/org/med_3407/8070_gefahrenabwehrverordnung.pdf",
        "verordnung", "betteln,lagern,alkohol", "Trierer Stadtrecht Gefahrenabwehrverordnung vom 09.09.2019 (ausgefertigt 08.10.2019)",
        "Gefahrenabwehrverordnung zur Aufrechterhaltung der öffentlichen Sicherheit und Ordnung auf öffentlichen Straßen und in öffentlichen Anlagen in der Stadt Trier",
        "2019-10-08", "Trier, 08. Oktober 2019 Stadtverwaltung Trier als Ordnungsbehörde", "original",
        "Bans begging aggressively by acting directly on people (blocking their way, touching them), harassing others as "
        "a result of alcohol or drug consumption, and camping or tenting outside designated campsites (sleeping in "
        "vehicles only once to restore fitness to drive).",
        ["aggressiv, durch unmittelbares Einwirken auf Personen, wie in den Weg stellen oder Anfassen, zu betteln",
         "außerhalb von ausgewiesenen Campingplätzen zu campen oder zu zelten",
         "andere Personen oder die Allgemeinheit aufgrund des Konsums von Alkohol oder berauschenden Mitteln durch Anpöbeln"]),
    _mu("darmstadt_gefavo", "06411", "HE", "Darmstadt",
        "https://www.darmstadt.de/fileadmin/Dateistruktur2024/04_RATHAUS/04_Stadtrecht-Satzungen/Alphabetisches_Sachregister/300_bis_399/374_neu.pdf",
        "verordnung", "betteln,lagern,alkohol", "Darmstädter Stadtrecht 374 Gefahrenabwehrverordnung (Präventionskonvention) vom 19.12.2007, zuletzt geändert durch Verordnung vom 14.05.2025",
        "Gefahrenabwehrverordnung zur Aufrechterhaltung der öffentlichen Sicherheit und Ordnung in der Wissenschaftsstadt Darmstadt",
        "2025-05-15", "zuletzt geändert durch Verordnung vom 14.05.2025, veröffentlicht im Darmstädter Echo am 15.05.2025, in Kraft getreten am 16.05.2025", "consolidated",
        "Bans begging by addressing people, organised begging and begging by or with children or animals; bans people "
        "who disturb others through alcohol or drug use, litter or excessive noise from lying around or lingering "
        "permanently in the covered area, in particular in public-transport shelters.",
        ["(3) Das Betteln durch Ansprechen von Personen, das organisierte Betteln sowie das Betteln durch oder mit Kindern und mit Tieren ist verboten",
         "ist das Lagern oder dauerhafte Verweilen im Geltungsbereich dieser Präventionskonvention, insbesondere in Wartehäuschen des ÖPNV, verboten",
         "Diese Verordnung tritt am 01.01.2021 in Kraft. Sie tritt am 31.12.2035 außer Kraft"],
        in_force_from="2025-05-16", local="muni_darmstadt_374_neu.pdf",
        # Lead 2026-11-23: own end clause (§ 11 Abs. 1); "tritt am 31.12.2035 außer Kraft" = first day out 2035-12-31
        ends_on="2035-12-31", ends_needle="Diese Verordnung tritt am 01.01.2021 in Kraft. Sie tritt am 31.12.2035 außer Kraft",
        note="manual archive via browser, 2026-11-23 (Lead); robots.txt of www.darmstadt.de disallows /fileadmin for all agents, so the file is read from the archive only; an amendment allowing a single calm request for money again was adopted in November 2026 (press); not yet in the city's consolidated PDF, which is the version ingested"),
    _mu("wolfsburg_vo_sicherheit", "03103", "NI", "Wolfsburg",
        "https://www.wolfsburg.de/-/media/wolfsburg/statistik_daten_fakten/satzungen_verordnungen/recht_sicherheit_ordnung/30_verordnung-oeffentliche-sicherheit.pdf",
        "verordnung", "betteln,lagern", "Wolfsburger Ortsrecht 30 Verordnung über die öffentliche Sicherheit vom 22.01.2019",
        "Verordnung über die öffentliche Sicherheit der Stadt Wolfsburg",
        "2019-01-22", "Wolfsburg, 22.01.2019 Stadt Wolfsburg", "original",
        "Bans begging by acting directly on other people and staying overnight or camping on public streets or in "
        "public facilities; alcohol banned only on playgrounds and school yards. Lapses 20 years after entry into force.",
        ["Das Betteln durch unmittelbares Einwirken auf andere Personen ist nicht gestattet",
         "Auf öffentlichen Straßen oder in öffentlichen Anlagen zu übernachten oder zu zelten",
         "Diese Verordnung tritt 20 Jahre nach ihrem Inkrafttreten außer Kraft"]),
    # ---- batch 13 (2026-11-21): kreisfreie sweep, east ----
    _mu("weimar_unterbringung", "16055", "TH", "Weimar",
        "https://stadt.weimar.de/de/datei/download/id/77867,48/55_1_unterbringungssatzung2025.pdf",
        "satzung", "obdach", "Weimarer Ortsrecht 55.1 Unterbringungssatzung (Stadtratsbeschluss 25.06.2025, Rathauskurier Nr. 11/25 vom 17.09.2025)",
        "Satzung über die Benutzung von öffentlichen Einrichtungen bei der Unterbringung besonderer Bedarfsgruppen in der Stadt Weimar (Unterbringungssatzung)",
        "2025-09-17", "Veröffentlicht im Rathauskurier, Amtsblatt der Stadt Weimar, Nr. 11/25 vom 17.09.2025, S. 20", "original",
        "Use statute for the city's accommodation, whose users include people who are involuntarily homeless and placed "
        "under Thuringian police law; replaces the Obdachlosenunterkunftssatzung of 22.01.2017.",
        ["der Personenkreis, der unfreiwillig obdachlos ist",
         "(Obdachlosenunterkunftssatzung) vom 22.01.2017 außer Kraft"]),
    _mu("weimar_ordnungsbehvo", "16055", "TH", "Weimar",
        "https://stadt.weimar.de/de/datei/download/id/7520,48/32_12_ordnungsbehvo2021.pdf",
        "verordnung", "betteln", "Weimarer Ortsrecht 32.12 Ordnungsbehördliche Verordnung, 1. Änderung vom 21.08.2026 (Rathauskurier Nr. 09/2026 vom 30.09.2026)",
        "Ordnungsbehördliche Verordnung zur Abwehr von Gefahren und zur Aufrechterhaltung der öffentlichen Sicherheit und Ordnung in der Stadt Weimar",
        "2026-09-30", "Veröffentlicht im Rathauskurier, Amtsblatt der Stadt Weimar, Nr. 09/2026 vom 30.09.2026", "consolidated",
        "Bans active begging on streets and in parks, defined as addressing, holding, following or pursuing people, "
        "blocking their way or entrances, using animals or minors, feigning disability, or organised/joint pressure.",
        ["§ 14 Betteln (1) Auf Straßen und in Anlagen ist es verboten, aktiv zu betteln",
         "1. durch Ansprechen, Festhalten, Nachlaufen oder Verfolgen von Personen",
         "Weimar, den 21.08.2026"]),
    _mu("jena_ordnungsbehvo", "16053", "TH", "Jena",
        "https://rathaus.jena.de/system/files/2019-08/c09.pdf",
        "verordnung", "betteln,lagern", "Jenaer Ortsrecht C9 Ordnungsbehördliche Verordnung vom 25.07.2017 (Amtsblatt Nr. 31/17), geändert 24.08.2018 (Amtsblatt Nr. 35/18)",
        "Ordnungsbehördliche Verordnung zur Aufrechterhaltung der öffentlichen Sicherheit und Ordnung in der Stadt Jena",
        "2018-08-30", "Satzung vom 24.08.2018 (Amtsblatt Nr. 35/18 vom 30.08.2018, S. 322)", "consolidated",
        "Bans aggressive begging (blocking, following or touching passers-by, using animals or children as pressure) "
        "and groups lying around at the same places regularly in a way that obstructs passers-by; alcohol banned only "
        "on playgrounds. Valid until 31.12.2032.",
        ["a) das aggressive Betteln (etwa durch unmittelbares Einwirken auf Passanten",
         "b) das Lagern von Personengruppen, wenn sich diese an den selben Orten regelmäßig ansammeln",
         "Diese Verordnung gilt bis zum 31.12.2032"],
        ends_on='2033-01-01', ends_needle='Diese Verordnung gilt bis zum 31.12.2032'),
    _mu("dessau_gefavo", "15001", "ST", "Dessau-Roßlau",
        "https://verwaltung.dessau-rosslau.de/fileadmin/Verwaltungsportal_Dessau-Rosslau/Stadt_Buerger/Buergerservice/Stadtrecht/Gefahrenabwehrverordnung/24.03.2022_gefahrenabwehrverordnung_2017.pdf",
        "verordnung", "alkohol", "Dessau-Roßlauer Stadtrecht Gefahrenabwehrverordnung vom 29.06.2017 (Amtsblatt 08/17, S. 37-40)",
        "Gefahrenabwehrverordnung der Stadt Dessau-Roßlau",
        "2017-07-29", "Dessau-Roßlau, 29.06.2017", "original",
        "Bans settling or staying on public streets, in public toilets, parks and playgrounds to drink alcohol in a way "
        "that may endanger others through harassment, noise, litter, urinating or vomiting. No begging rule.",
        ["sich derart zum Konsum von Alkohol niederzulassen oder aufzuhalten, dass dort in Folge andere Personen oder die Allgemeinheit"],
        note="the file name carries 24.03.2022 but the header table gives the 2017 enactment (signed 29.06.2017, gazette 08/17, in force 05.08.2017)"),
    _mu("cottbus_stadtordnung", "12052", "BB", "Cottbus/Chóśebuz",
        "https://cottbus.de/satzungen/Stadtordnung-Cottbus-2023-1.pdf",
        "verordnung", "betteln,lagern,alkohol", "Cottbuser Ortsrecht Stadtordnung (Ordnungsbehördliche Verordnung) vom 06.09.2023",
        "Ordnungsbehördliche Verordnung über die Aufrechterhaltung der öffentlichen Ordnung, Sicherheit und Sauberkeit in der Stadt Cottbus/Chóśebuz (Stadtordnung)",
        "2023-09-06", "Cottbus/Chóśebuz, 06.09.2023", "original",
        "Bans lying around, camping or sleeping on traffic areas or in parks outside designated areas, aggressive "
        "begging (touching, holding, blocking, intrusive addressing, pursuing, using animals, joint action), and "
        "disturbing others in connection with alcohol or drug use.",
        ["a) auf Verkehrsflächen oder in Anlagen, auf hierfür nicht besonders freigegebenen Flächen zu lagern, zu campieren, zu übernachten",
         "b) das aggressive Betteln, z. B. durch Anfassen, Festhalten, Versperren des Weges",
         "e) das Stören in Verbindung mit dem Genuss von Alkohol oder anderen berauschenden Mitteln"]),
    _mu("brandenburg_obdach_geb", "12051", "BB", "Brandenburg an der Havel",
        "https://www.stadt-brandenburg.de/fileadmin/pdf/10/Buero_SVV/Satzungen/Obdachlosenunterk%C3%BCnfte16.pdf",
        "satzung", "obdach_gebuehr", "Brandenburger Ortsrecht Gebühren- und Benutzersatzung für Obdachlosenunterkünfte vom 18.08.2000, zuletzt geändert durch Satzung vom 04.11.2016",
        "Satzung über die Erhebung von Gebühren und die Inanspruchnahme der Wohnunterkünfte für Obdachlose in der Stadt Brandenburg an der Havel (Gebühren- und Benutzersatzung für Obdachlosenunterkünfte)",
        "2016-11-14", "vom 04.11.2016 (ABl. Nr. 24 vom 14.11.2016)", "consolidated",
        "Use and fee statute for the homeless accommodation; the annex lists monthly and daily rates per shelter, shared "
        "flat and flat, starting with the homeless hostel Otto-Gartz-Str. 22 a.",
        ["Gebührenverzeichnis Gebührentatbestand: Gebührensatz Gebührensatz Inanspruchnahme der Unterkunft pro Monat pro Tag"],
        fees=[_fee("obdach_gebuehr_eur_monat__obdachlosenhaus", 135.70, "EUR/Monat",
                   "135,70 €", "Anlage zu § 10 Abs. 1 (Otto-Gartz-Str. 22 a, Obdachlosenhaus, pro Monat)", 2016),
              _fee("obdach_gebuehr_eur_tag__obdachlosenhaus", 4.40, "EUR/Tag",
                   "4,40 €", "Anlage zu § 10 Abs. 1 (Otto-Gartz-Str. 22 a, Obdachlosenhaus, pro Tag)", 2016)]),
    _mu("schwerin_strgruen", "13004", "MV", "Schwerin",
        "https://www.schwerin.de/export/sites/default/.galleries/Dokumente/Bekanntmachungen/Bekanntmachungen-2025/Strassen-und-Gruenflaechensatzung-2025.pdf",
        "satzung", "lagern,alkohol,sondernutzung", "Schweriner Ortsrecht Straßen- und Grünflächensatzung, in Kraft 01.08.2025",
        "Satzung für Sondernutzungen an öffentlichen Straßen, Wegen, Plätzen und Grünflächen in der Landeshauptstadt Schwerin (Straßen- und Grünflächensatzung)",
        "2025-08-01", "Diese Straßen- und Grünflächensatzung tritt zum 01.08.2025 in Kraft", "original",
        "Special-use statute for streets and green spaces; in green spaces bans camping in tents or caravans and staying "
        "there to drink alcohol where this impairs public safety and order; alcohol and smoking banned on playgrounds. "
        "No begging rule (aggressive begging handled under § 118 OWiG).",
        ["10. zu zelten bzw. in Wohnwagen zu campieren",
         "12. sich zum Zwecke des Alkoholgenusses aufzuhalten, soweit dadurch die öffentliche Sicherheit und Ordnung beeinträchtigt werden"]),
    # ---- batch 14 (2026-11-21): close the not-checked cells, Bavaria ----
    _mu("straubing_obdach_geb", "09263", "BY", "Straubing",
        "https://www.straubing.de/m_5480_dl",
        "satzung", "obdach_gebuehr", "Straubinger Stadtrecht 23.1.31 Gebührensatzung für die Obdachlosenunterkünfte vom 21.05.2024 (ABl S. 260)",
        "Gebührensatzung für die Obdachlosenunterkünfte",
        "2024-05-23", "Bekanntmachung: 23. Mai 2024 (ABl S. 260)", "original",
        "Fee statute for the city homeless shelters: rented buildings and flats at the rent the landlord charges; the "
        "shared shelters for men and women at a fixed daily rate, giving a monthly fee per resident.",
        ["Straubing, den 21.05.2024"],
        fees=[_fee("obdach_gebuehr_eur_person_tag__gemeinschaftsunterkunft", 12.00, "EUR/Person/Tag",
                   "bemessen sich nach einem festgelegten Tagessatz in Höhe von 12,00 €", "§ 4 Abs. 2", 2024),
              _fee("obdach_gebuehr_eur_person_monat__gemeinschaftsunterkunft", 360.00, "EUR/Person/Monat",
                   "Die monatliche Benutzungsgebühr pro Bewohner beträgt demnach 360,00 €", "§ 4 Abs. 2", 2024)],
        note="the box host fails TLS for straubing.de; raw fetched from the deck with the same honest UA after reading robots.txt"),
    _mu("straubing_sns", "09263", "BY", "Straubing",
        "https://www.straubing.de/m_1149_dl",
        "satzung", "betteln,lagern,alkohol,sondernutzung", "Straubinger Stadtrecht 20.2.30 Verkehrsraumsondernutzungssatzung vom 23.06.1983 i.d.F. der Änderungssatzung vom 22.07.2025 (ABl 32/2025)",
        "Satzung der Stadt Straubing über die Erlaubnisse und Gebühren für Sondernutzungen an öffentlichem Verkehrsraum (Verkehrsraumsondernutzungssatzung)",
        "2025-07-22", "i.d.F. der Änderungssatzung vom 22.07.2025 (ABl 32/2025)", "consolidated",
        "Special-use statute for streets: no permit is granted for sleeping in the pedestrian zones, for begging in any "
        "form, or for settling down to drink alcohol outside licensed outdoor bar areas.",
        ["a) für das Nächtigen in den Fußgängerbereichen, b) für das Betteln in jeglicher Form, c) für das Niederlassen zum Alkoholgenuß außerhalb zugelassener Freischankflächen"],
        note="the box host fails TLS for straubing.de; raw fetched from the deck with the same honest UA after reading robots.txt"),
    _mu("amberg_obdach", "09361", "BY", "Amberg",
        "https://amberg.de/fileadmin/Stadtrecht/3106.pdf",
        "satzung", "obdach", "Amberger Stadtrecht 3-1-06 Obdachlosensatzung (Amtsblatt Nr. 23 vom 19.12.2025)",
        "Satzung über den Unterhalt und die Benutzung der Obdachlosenunterkünfte der Stadt Amberg (Obdachlosensatzung)",
        "2025-12-19", "Bekannt gemacht im Amtsblatt der Stadt Amberg Nr. 23 vom 19.12.2025", "original",
        "Use statute for the two city homeless shelters (hotel/pension rooms) for adults who are or are about to become "
        "homeless once all other help is exhausted; admission by written order, normally limited to four weeks; "
        "fees under a separate fee statute.",
        ["Die Unterkünfte dienen der vorübergehenden Unterbringung von volljährigen Personen, die obdachlos sind oder denen Obdachlosigkeit droht",
         "Die Aufnahme in eine Unterkunft ist grundsätzlich auf maximal 4 Wochen befristet"]),
    _mu("amberg_sns", "09361", "BY", "Amberg",
        "https://amberg.de/fileadmin/Stadtrecht/5304.pdf",
        "satzung", "betteln,lagern,alkohol,sondernutzung", "Amberger Stadtrecht 5-3-04 Sondernutzungssatzung vom 22.05.2017, zuletzt geändert (Amtsblatt Nr. 9 vom 04.05.2026)",
        "Satzung über Sondernutzungen an öffentlichen Straßen und Plätzen der Stadt Amberg (Sondernutzungssatzung)",
        "2026-05-04", "zuletzt geändert im Amtsblatt der Stadt Amberg Nr. 9 vom 4. Mai 2026", "consolidated",
        "Special-use statute: a permit is as a rule not granted for lying around and sleeping, begging in any form, or "
        "settling down to drink alcohol outside licensed outdoor bar areas.",
        ["Die Sondernutzungserlaubnis wird in der Regel nicht erteilt für a) das Lagern und Nächtigen, b) das Betteln in jeglicher Form",
         "c) das Niederlassen zum Alkoholgenuss außerhalb erlaubter Freischankflächen"]),
    _mu("weiden_notquartier_geb", "09363", "BY", "Weiden i.d.OPf.",
        "https://www.weiden.de/fileadmin/user_upload/A_Stadt-Rathaus-Buerger/A03_Rathaus/Stadtrecht/S821.pdf",
        "satzung", "obdach_gebuehr", "Weidener Stadtrecht S821 Notquartiere-Gebührensatzung (ABl Nr. 3/2019, geändert ABl Nr. 49/2021 und Nr. 4/2025)",
        "Satzung über die Gebühren für die Benutzung der Notquartiere der Stadt Weiden i.d.OPf. (Notquartiere-Gebührensatzung)",
        "2025-03-03", "ABl. Nr. 4 vom 03.03.2025", "consolidated",
        "Daily fee per bed incl. all utilities in the city's homeless emergency shelter (Ursula-Barrois-Haus); for "
        "households of two or more the fee is capped at two beds.",
        ["Für jeden vollen Monat der Benutzung werden 30 Tagessätze pro Bettplatz berechnet"],
        fees=[_fee("obdach_gebuehr_eur_platz_tag", 12.44, "EUR/Platz/Tag",
                   "für einen Bettplatz 12,44 Euro täglich", "§ 4 Abs. 1", 2025)],
        extra=[("https://www.weiden.de/fileadmin/user_upload/A_Stadt-Rathaus-Buerger/A03_Rathaus/Stadtrecht/S820.pdf",
                ["denen Obdachlosigkeit droht und bei denen alle anderen Hilfen nachweislich erschöpft sind"])]),
    _mu("hof_sns", "09464", "BY", "Hof",
        "https://www.hof.de/fileadmin/user_upload/pdf/Ortsrecht/634-2.pdf",
        "satzung", "betteln,lagern,alkohol,sondernutzung", "Hofer Ortsrecht 634/2 Sondernutzungssatzung vom 06.12.2012, zuletzt geändert durch Satzung vom 02.07.2025",
        "Satzung zur Regelung der Benutzung von öffentlichen Verkehrsflächen in der Stadt Hof (Sondernutzungssatzung)",
        "2025-07-02", "Vom 06. Dezember 2012 zuletzt geändert durch Satzung vom 02. Juli 2025", "consolidated",
        "Bans begging and settling down to drink alcohol outside restaurant terraces in the old town and at the bus "
        "station, begging in listed streets of the Neustadt, and sleeping or lying around in the old town and Neustadt "
        "areas; fines up to EUR 1,000.",
        ["Im Altstadtbereich (Kategorie A) und im Bereich des Busbahnhofes sind das Betteln sowie das Niederlassen zum Alkoholgenuss außerhalb von Freisitzen gastronomischer Betriebe verboten",
         "kehrsflächen der Kategorien A – B (Altstadtbereich und Neustadtbereich) ist das Nächtigen oder Lagern verboten"]),
    _mu("memmingen_obdach_geb", "09764", "BY", "Memmingen",
        "https://stadtrecht.memmingen.de/fileadmin/Stadtrecht/MStR/1000/1801.pdf",
        "satzung", "obdach_gebuehr", "Memminger Stadtrecht 1801 Obdachlosenunterkunftsgebührensatzung (OGS) vom 16.05.1995, geändert 11.07.2001 und 14.03.2003",
        "Gebührensatzung zur Obdachlosenunterkunftsbenutzungssatzung der Stadt Memmingen (Obdachlosenunterkunftsgebührensatzung - OGS)",
        "2003-03-21", "14.03.2003 22 21.03.2003 01.05.2003", "consolidated",
        "Monthly fee per m² of floor area incl. service charges (without heating and electricity): rooms in the shared "
        "shelter (Erlenweg 10) and rooms in single flats without or with bathroom.",
        ["Die Gebühr beträgt im Monat je angefangenem Quadratmeter Nutzfläche einschließlich Nebenkosten (ohne Heizung und Strom)"],
        fees=[_fee("obdach_gebuehr_eur_m2_monat__gemeinschaftsanlage", 2.90, "EUR/m2/Monat",
                   "für Räume in der gemeinsamen Anlage 2,90 €", "§ 4 Abs. 1 Nr. 1", 2003),
              _fee("obdach_gebuehr_eur_m2_monat__wohnung_ohne_bad", 3.50, "EUR/m2/Monat",
                   "a) ohne Bad 3,50 €", "§ 4 Abs. 1 Nr. 2 a", 2003),
              _fee("obdach_gebuehr_eur_m2_monat__wohnung_mit_bad", 4.50, "EUR/m2/Monat",
                   "b) mit Bad 4,50 €", "§ 4 Abs. 1 Nr. 2 b", 2003)]),
    _mu("memmingen_sns", "09764", "BY", "Memmingen",
        "https://stadtrecht.memmingen.de/fileadmin/Stadtrecht/MStR/6000/6601.pdf",
        "satzung", "betteln,lagern,alkohol,sondernutzung", "Memminger Stadtrecht 6601 Sondernutzungsgebührensatzung (SNGS) vom 14.10.2015, geändert 11.12.2024",
        "Satzung über die Sondernutzungen an öffentlichen Straßen und die Erhebung von Sondernutzungsgebühren in der Stadt Memmingen (Sondernutzungsgebührensatzung - SNGS)",
        "2024-12-13", "11.12.2024 33/2024 13.12.2024 14.12.2024", "consolidated",
        "Special-use statute: a permit must be refused for lingering mainly to drink alcohol outside licensed outdoor bar "
        "areas, for lying around and sleeping, and for begging that is aggressive, organised or otherwise disturbs "
        "public order.",
        ["für das Lagern und Nächtigen",
         "für das Betteln, soweit es in aggressiver Form oder organisiert betrieben wird oder sonst die öffentliche Sicherheit und Ordnung stört"]),
    _mu("wuerzburg_verfuegung", "09663", "BY", "Würzburg",
        "https://www.wuerzburg.de/m_10792_dl",
        "satzung", "obdach", "Würzburger Stadtrecht 5.5 Satzung über die Benutzung und Verwaltung der Verfügungswohnungen vom 08.07.1981 (MP und FVBl Nr. 159/81)",
        "Satzung über die Benutzung und Verwaltung der Verfügungswohnungen der Stadt Würzburg",
        "1981-07-08", "vom 8. Juli 1981 (MP und FVBl Nr. 159/81)", "original",
        "Use statute for the city's emergency flats kept to house homeless people: admission under homelessness "
        "assistance by allocation order, public-law use, house rules; fees under a separate fee statute (amounts not "
        "in this text).",
        ["Um die Unterbringung von Obdachlosen sicherzustellen, unterhält die Stadt Würz"],
        note="the box host fails TLS for wuerzburg.de; raw fetched from the deck with the same honest UA. Two-column layout; "
             "listed as current in the city's Stadtrecht (5.5). The separate fee statute was not located"),
    _mu("bamberg_fussgaengerbereich", "09461", "BY", "Bamberg",
        "https://www.stadt.bamberg.de/media/custom/332_66_1.PDF",
        "satzung", "betteln,lagern,alkohol,sondernutzung", "Bamberger Stadtrecht 31.001.1 Fußgängerbereich-Satzung vom 04.12.2001, zuletzt geändert durch Satzung vom 30.10.2019",
        "Satzung über die Sondernutzungen im Fußgängerbereich Innenstadt (Fußgängerbereich-Satzung)",
        "2019-11-08", "zuletzt geändert durch Satzung vom 30.10.2019 (Rathaus Journal - Amtsblatt der Stadt Bamberg - vom 08.11.2019 – Nr. 20)", "consolidated",
        "In the inner-city pedestrian zone no special-use permit is granted for sleeping, for begging in any form, or "
        "for lingering while drinking alcohol outside licensed outdoor bar areas.",
        ["a) für das Nächtigen im Fußgängerbereich, b) für das Betteln in jeglicher Form",
         "d) für das Verweilen bei gleichzeitigem Alkoholgenuss außerhalb der bestimmungsgemäßen Nutzung der zugelassenen Freischankflächen"]),
    _mu("bayreuth_sns", "09462", "BY", "Bayreuth",
        "https://formular-server.de/BT_FS/findform?areashortname=bt_oe&formtecid=2&shortname=Sondernutzungssatzun",
        "satzung", "betteln,lagern,alkohol,sondernutzung", "Bayreuther Stadtrecht 615 Sondernutzungssatzung vom 19.05.2010 (Amtsblatt Nr. 8 vom 11.06.2010)",
        "Satzung über Sondernutzungen an öffentlichen Straßen in der Stadt Bayreuth (Sondernutzungssatzung)",
        "2010-06-11", "Veröffentlicht: Amtsblatt der Stadt Bayreuth Nr. 8 vom 11. Juni 2010", "original",
        "Special-use statute: a permit is refused for begging in any form, for sleeping and lying around, and for "
        "settling down to drink alcohol outside licensed outdoor bar areas.",
        ["c) für das Betteln in jeglicher Form",
         "f) für das Nächtigen und Lagern; g) für das Niederlassen zum Zwecke des Genusses alkoholischer Getränke außerhalb zugela",
         "Bayreuth, den 19. Mai 2010"],
        note="official Stadtrecht PDF served by the city's form server formular-server.de (linked from bayreuth.de Stadtrecht); "
             "b19: robots.txt of formular-server.de answers HTTP 418, so the run-time check fails closed and the host does not "
             "permit automated fetching -- the file was archived once by hand (Lead, 2026-11-23) and is read from the archive only",
        local="muni_bayreuth_sns.pdf"),
    _mu("rosenheim_suedtiroler_platz", "09163", "BY", "Rosenheim",
        "https://www.rosenheim.de/fileadmin/user_upload/Satzung_Suedtiroler_Platz.pdf",
        "satzung", "betteln,alkohol", "Rosenheimer Ortsrecht Satzung über die Benutzung des Bahnhofsvorplatzes (Südtiroler-Platz) vom 04.07.2023",
        "Satzung über die Benutzung des Bahnhofsvorplatzes (Südtiroler-Platz)",
        "2023-07-04", "Rosenheim, 04.07.2023", "original",
        "On the station forecourt bans active or passive begging and drinking alcohol outside licensed outdoor bar areas.",
        ["3. aktives oder passives Betteln", "7. Alkoholkonsum außerhalb genehmigter"]),
    # ---- batch 15 (2026-11-21): remaining not-checked (b) cells ----
    _mu("kempten_sns", "09763", "BY", "Kempten (Allgäu)",
        "https://www.kempten.de/file/I-20_Sondernutzungssatzung.pdf",
        "satzung", "betteln,lagern,alkohol,sondernutzung", "Kemptener Stadtrecht I/20 Sondernutzungssatzung vom 20.12.1982, zuletzt geändert 02.09.2016 (StABl KE 24/16)",
        "Satzung über Sondernutzungen in der Stadt Kempten (Allgäu) (Sondernutzungssatzung)",
        "2016-09-02", "02. September 2016 (StABl KE 24/16)", "consolidated",
        "In the core town no special-use permit is granted for begging where it disturbs public safety and order, for "
        "settling down to drink alcohol outside licensed outdoor bar areas, or for lying around and sleeping.",
        ["a) für das Betteln, soweit damit eine Störung der öffentlichen Sicherheit und Ordnung verbunden ist",
         "b) für das Niederlassen zum Alkoholgenuss außerhalb zugelassener Freischankflächen, c) für das Lagern und Nächtigen"]),
    _mu("passau_alkoholv", "09262", "BY", "Passau",
        "https://www.passau.de/fileadmin/Homepage_Stadt_Passau/2._Rathaus_und_Buergerservice/Politik/Stadtrecht__Satzungen___Verordnungen_/23-12-04_Lesefassung_AlkoholV-ZOB.pdf",
        "verordnung", "alkohol", "Passauer Stadtrecht AlkoholV vom 04.12.2023 (Lesefassung)",
        "Verordnung der Stadt Passau über das Verbot des Verzehrs und des Mitführens alkoholischer Getränke auf öffentlichen Flächen (AlkoholV)",
        "2023-12-04", "Passau, den 04.12.2023", "consolidated",
        "All-day ban on drinking or carrying alcohol for consumption at the central bus station, Dr.-Hans-Kapfinger-Straße "
        "and the adjoining part of Ludwigsplatz; valid for four years from promulgation.",
        ["Im Geltungsbereich dieser Verordnung ist es verboten alkoholische Getränke zu verzehren",
         "Die Geltungsdauer dieser Verordnung beträgt vier Jahre"],
        note="reading version (Lesefassung); the Amtsblatt promulgation is authoritative. Lapses four years after entry into force "
             "(about December 2027). The Sondernutzungssatzung of 21.11.2024 has no begging/lying rule; begging is addressed by an "
             "Allgemeinverfügung of 25.10.2022 that the city publishes only as a scanned PDF without a text layer (not ingested)"),
    _mu("coburg_sicherheitsvo", "09463", "BY", "Coburg",
        "https://www.coburg.de/medien/dokumente/stadtpolitik/stadtrecht/170_SicherheitsVO.pdf",
        "verordnung", "betteln,lagern,alkohol,sondernutzung", "Coburger Stadtrecht 170 Gemeindeverordnung über Sicherheit, Ordnung, Reinhaltung und Ruhe vom 25.10.1996, zuletzt geändert durch Euro-AnpSV (Amtsblatt Nr. 40 vom 09.11.2001)",
        "Gemeindeverordnung über Sicherheit, Ordnung, Reinhaltung und Ruhe in der Stadt Coburg",
        "2001-11-09", "Coburger Amtsblatt Nr. 40 vom 09.11.2001 S. 109", "consolidated",
        "Combined municipal rule: § 3 states that no special-use permit is granted for lying around and sleeping, for "
        "settling down to drink alcohol outside licensed outdoor seating, or for begging in any form.",
        ["a) für das Lagern und Nächtigen, b) für das Niederlassen zum Alkoholgenuss außerhalb von Freisitzen gastronomischer Betriebe, c) für das Betteln in jeder Form",
         # b19 lapse test (Lead 2026-11-23): deciding sentence
         "Diese Verordnung tritt am Tage nach ihrer öffentlichen Bekanntmachung in Kraft. Coburg, 25.10.1996",
         # b20 section-by-section check: the legal basis of § 3 (the row's content) and of the LStVG parts
         "vom 25.10.1996 (Coburger Amtsblatt S. 142 Nr. 44 vom 31.10.1996)",
         "3. Zuwiderhandlungen gegen § 3 dieser Verordnung, insbesondere unerlaubtes Lagern, Nächtigen, Betteln und Niederlassen zum Alkoholgenuss, nach Art. 23, 24 Abs. 1 Nr. 1, Abs. 2 Satz 2 Gemeindeordnung",
         "5. Zuwiderhandlungen gegen § 5 dieser Verordnung, Taubenfütterungsverbot, nach Art. 16 Abs. 2 Landesstraf- und Verordnungsgesetz",
         "6. Zuwiderhandlungen gegen § 6 dieser Verordnung, öffentliche Anschläge, nach Art. 28 Abs. 2 Landesstraf- und Verordnungsgesetz"],
        # b20 (Lead 2026-11-23): checked section by section -- the row's content (§ 3, refusal of Sondernutzung for lying,
        # sleeping, drinking, begging) is Satzung law under Art. 23, 24 GO (penalty § 7 Nr. 3) on the Sondernutzung basis
        # of the BayStrWG; Art. 50 LStVG does not reach it (Art. 50 Abs. 3), so the row is in force, not lapsed. Only the
        # LStVG-based §§ 5 (pigeon feeding, Art. 16 LStVG) and 6 (posters, Art. 28 LStVG) lapsed on 01.11.2016 (20 years
        # after entry into force on the day after publication on 31.10.1996); they carry none of the row's topics, so no
        # split row was made and the row key is unchanged.
        note="mixed statute/ordinance on several legal bases (BayStrWG Art. 66, BayWG, GO Art. 23/24, BayImSchG, LStVG). The row's "
             "content, § 3 (no Sondernutzungserlaubnis for Lagern/Nächtigen, Alkoholgenuss, Betteln), rests on Art. 23, 24 GO "
             "(Satzung; fine under § 7 Nr. 3) and is not subject to the 20-year limit of Art. 50 LStVG (Art. 50 Abs. 3); only the "
             "LStVG-based §§ 5-6 (pigeon feeding, posters; § 7 Nr. 5-6) lapsed on 01.11.2016 (published 31.10.1996, in force the day "
             "after). The city lists the text as current Stadtrecht no. 170; no repeal of § 3 was found"),
    _mu("schwabach_sns", "09565", "BY", "Schwabach",
        "https://www.schwabach.de/images/referate/referat_2/ortsrecht/SoNS-2.%C3%84nderung.pdf",
        "satzung", "betteln,lagern,alkohol,sondernutzung", "Schwabacher Ortsrecht Sondernutzungssatzung (SoNS) vom 07.06.2021, Stand 2. Änderungssatzung vom 24.03.2026",
        "Satzung über Sondernutzungen an öffentlichen Straßen (Sondernutzungssatzung – SoNS)",
        "2026-03-24", "(Stand: 2. Satzung zur Änderung der Satzung über Sondernutzungen an öffentlichen Straßen in der Stadt Schwabach vom 24.03.2026)", "consolidated",
        "Settling down to drink alcohol outside licensed outdoor bar areas counts as special use; a permit must be refused "
        "for sleeping or lying around in pedestrian zones, for lingering to drink alcohol there, and for begging in any form.",
        ["4. für das Nächtigen oder Lagern innerhalb ausgewiesener Fußgängerzonen",
         "6. für das Betteln in jeglicher Form"]),
    _mu("hanau_gavo", "06415", "HE", "Hanau",
        "https://www.hanau.de/mam/gefahrenabwehrverordnung_-_internetdokument.pdf",
        "verordnung", "betteln,lagern,alkohol", "Hanauer Stadtrecht Gefahrenabwehrverordnung vom 21.07.2015, 1. Änderung vom 28.03.2025 (in Kraft 10.04.2025)",
        "Gefahrenabwehrverordnung der Stadt Hanau",
        "2025-04-10", "1. Änderung 24.03.2025 28.03.2025 09.04.2025 10.04.2025", "consolidated",
        "HSOG hazard-prevention ordinance: bans lying around or lingering in a way that disturbs others in order to drink "
        "alcohol outside licensed areas; on inner-town streets, pedestrian zones and in parks bans lying around, sleeping "
        "and harassing people to beg (incl. begging with children or by faking a disability).",
        ["zum Zwecke des Konsums von alkoholischen Getränken – außerhalb gastronomisch genutzter Flächen – ist verboten",
         "ist es untersagt zu lagern, zu nächtigen und zum Zwecke der Bettelei Personen in belästigender Weise anzusprechen"]),
    _mu("muelheim_obvo", "05117", "NW", "Mülheim an der Ruhr",
        "https://cms.muelheim-ruhr.de/ortsrecht/ordnungsbehoerdliche-verordnung-ueber-die-aufrechterhaltung-der-oeffentlichen-sicherheit",
        "verordnung", "betteln", "Mülheimer Ortsrecht Ordnungsbehördliche Verordnung vom 21.12.2020 zur Änderung der OBVO vom 20.12.2010",
        "Ordnungsbehördliche Verordnung über die Aufrechterhaltung der öffentlichen Sicherheit und Ordnung im Gebiet der Stadt Mülheim an der Ruhr",
        "2020-12-21", "Mülheim an der Ruhr, 21. Dezember 2020", "consolidated",
        "Bans aggressive begging (touching, holding, blocking, pursuing, persistent addressing) on roads and in parks, and "
        "silent begging involving children or by children; no lying-around or general alcohol rule. Valid until 31.12.2030.",
        ["(1) Auf Verkehrsflächen und in Anlagen ist aggressive Bettelei untersagt",
         "das stille Betteln unter Beteiligung von Kindern und Jugendlichen und das Betteln von Kindern und Jugendlichen verboten",
         "gilt bis zum 31. Dezember 2030", 'in Kraft und gilt bis zum 31. Dezember 2030'],
        note="HTML text on the city's Ortsrecht page",
        ends_on='2031-01-01', ends_needle='in Kraft und gilt bis zum 31. Dezember 2030'),
    _mu("bottrop_obvo", "05512", "NW", "Bottrop",
        "https://www.bottrop.de/downloads/downloads/rathaus/amtliche/Allgemeinverfuegung-OBVO.pdf",
        "verordnung", "betteln,lagern,alkohol", "Bottroper Ortsrecht Ordnungsbehördliche Verordnung vom 07.07.2026, ersetzt die Verordnung vom 12.09.2006 i.d.F. vom 20.11.2024",
        "Ordnungsbehördliche Verordnung zur Aufrechterhaltung der öffentlichen Sicherheit und Ordnung im Gebiet der Stadt Bottrop",
        "2026-07-07", "zuletzt geändert durch Verordnung vom 07.07.2026", "consolidated",
        "On roads and in parks bans conduct that endangers, obstructs or seriously harasses others, notably aggressive "
        "begging and silent begging with children, group lying-around that obstructs passers-by, alcohol-related "
        "disturbance, sleeping (also in vehicles) and setting up shelters with blankets or cardboard; alcohol banned on "
        "public-transport sites.",
        ["aufdringliches Betteln mittels Anfassen, Festhalten, Versperren des Weges",
         "das Lagern in Personengruppen, wenn sich diese an denselben Orten regelmäßig ansammeln",
         "4. das Nächtigen (auch in Fahrzeugen) 5. das Herrichten einer Behausung mit Decken, Zeltplanen, Matratzen, Kartonagen",
         # b19 lapse test (Lead 2026-11-23): deciding sentence
         "Gleichzeitig tritt die Verordnung über die Aufrechterhaltung der öffentlichen Sicherheit und Ordnung im Gebiet der Stadt Bottrop vom 12.09.2006, geändert durch Verordnung vom 20.11.2024, außer Kraft"],
        note="the city's file name says 'Allgemeinverfuegung' but the document is the ordinance; cited as a new ordinance of "
             "07.07.2026 (Lead b20): its § on Geltungsdauer repeals the ordinance of 12.09.2006 as amended on 20.11.2024, although the "
             "city's heading still reads 'vom 12.09.2006, zuletzt geändert durch Verordnung vom 07.07.2026' (row key unchanged, renamed in place)"),
    _mu("landshut_sisa", "09261", "BY", "Landshut",
        "https://landshut.de/sites/default/files/filemanager/Benutzerdaten/La55/Rechtspflege/Sicherheitssatzung-SiSa.pdf",
        "satzung", "betteln,lagern,alkohol", "Landshuter Stadtrecht Sicherheitssatzung (SiSa), Stand 16.11.2020",
        "Satzung über die Aufrechterhaltung der öffentlichen Sicherheit und Ordnung und die Benützung der Grün- und Erholungsanlagen, Kinderspielplätze und Freizeitanlagen in der Stadt Landshut (Sicherheitssatzung – SiSa)",
        "2020-11-16", "Stand: 16.11.2020", "consolidated",
        "Bans begging or lying around in the defined inner city, and staying around to drink alcohol where this may "
        "impair public safety and order. The Sondernutzungssatzung (Stand 09.12.2013) also refuses permits for lying "
        "around, begging in any form and settling down to drink outside licensed outdoor bar areas.",
        ["9. in der Landshuter Innenstadt zu betteln oder zu lagern",
         "6. sich zum Alkoholgenuss aufzuhalten oder zu verweilen, soweit dadurch die öffentli"],
        extra=[("https://landshut.de/sites/default/files/filemanager/Benutzerdaten/La55/Bauverwaltung/Sondernutzungssatzung.pdf",
                ["a) Das Lagern bzw. Betteln in jeglicher Form, b) das Niederlassen zum Alkoholgenuss außerhalb zugelassener Freischankflächen"],
                "muni_landshut_sondernutzung.pdf")],
        local="muni_landshut_sisa.pdf",
        note="manual archive via browser, 2026-11-23 (Lead); robots.txt of landshut.de disallows /sites/default/files/ for all agents, so both files are read from the archive only"),
    _mu("landshut_obdach", "09261", "BY", "Landshut",
        "https://landshut.de/sites/default/files/filemanager/Benutzerdaten/La55/Sozialverwaltung%20und%20Jugendhilfe/Satzung%20Obdachlosenunterk%C3%BCnfte.pdf",
        "satzung", "obdach", "Landshuter Stadtrecht Satzung über die Obdachlosenunterkünfte, Stand 12.11.2001",
        "Satzung über die Obdachlosenunterkünfte der Stadt Landshut",
        "2001-11-12", "Stand: 12.11.2001", "consolidated",
        "Use statute: the city runs named residential buildings and individually provided flats as a public facility, "
        "exclusively for temporary accommodation of homeless people.",
        ["Diese Wohngebäude sind ausschließlich als Obdachlosenunterkünfte zur vorü"],
        note="fees are in a separate Gebührensatzung whose online text (Stand 21.07.2017) predates the amendment of 28.04.2026 "
             "(Amtsblatt Nr. 15), so no fee rows are ingested; manual archive via browser, 2026-11-23 (Lead); robots.txt of landshut.de disallows /sites/default/files/ for all agents, so the file is read from the archive only",
        local="muni_landshut_obdach.pdf"),
    _mu("schweinfurt_sns", "09662", "BY", "Schweinfurt",
        "https://www.schweinfurt.de/m_54695_dl",
        "satzung", "betteln,lagern,alkohol,sondernutzung", "Schweinfurter Ortsrecht Sondernutzungssatzung vom 05.07.2001 (SWTZ 28.07.2001), geändert am 25.09.2001 und 26.05.2009",
        "Satzung der Stadt Schweinfurt über Sondernutzungen (Sondernutzungssatzung)",
        "2009-05-26", "geändert am 25.09.2001 und 26.05.2009", "consolidated",
        "On public roads bans sleeping, begging that seeks physical closeness or is otherwise particularly intrusive, and "
        "drinking alcohol outside outdoor bar areas where its effects can seriously bother the public. The Anlagensatzung "
        "of 30.06.2020 bans the same begging and drinking in public parks plus sleeping and camping there.",
        ["1. das Nächtigen, 2. das die körperliche Nähe suchende oder sonst besonders aufdringliche Betteln sowie das Anstiften",
         "4. der Alkoholkonsum außerhalb von Freiausschankflächen oder Einrichtungen, wie Grillstellen oder Ähnlichem"],
        note="the box host fails TLS for schweinfurt.de; raw files fetched once from the deck with the same honest UA after "
             "robots.txt. The PDF carries its text layer twice",
        extra=[("https://www.schweinfurt.de/m_1003_dl",
                ["Insbesondere ist in öffentlichen Anlagen untersagt: 1. das die körperliche Nähe suchende oder sonst besonders aufdringliche Betteln",
                 "8. das Nächtigen, Zelten und Aufstellen von Wohnwagen", "Schweinfurt, 30.06.2020"])]),
    _mu("ansbach_gruenanlagen", "09561", "BY", "Ansbach",
        "https://www.ansbach.de/media/custom/2595_83_1.PDF",
        "satzung", "betteln,lagern,alkohol", "Ansbacher Ortsrecht Grünanlagensatzung vom 31.07.2025",
        "Satzung der Stadt Ansbach über die Benutzung der öffentlichen Grünanlagen (Grünanlagensatzung)",
        "2025-07-31", "(Grünanlagensatzung) vom 31.07.2025", "original",
        "In public green spaces bans sleeping over, camping, begging in any form, and staying (settling down, lying "
        "around) to take drugs or alcohol. The Sondernutzungssatzung of 15.02.2007 refuses permits for sleeping or lying "
        "around in the pedestrian zone and station underpass, group drinking outside licensed areas, and active and "
        "organised begging.",
        ["g) das Übernachten, Zelten und Campen; h) das Betteln in jeglicher Form"],
        extra=[("https://www.ansbach.de/media/custom/2595_4156_1.PDF",
                ["f) für das aktive und organisierte Betteln", "Ansbach, den 15.02.2007"])]),
    _mu("aschaffenburg_obdach_geb", "09661", "BY", "Aschaffenburg",
        "https://www.aschaffenburg.de/loadDocument.phtml?FID=4173.132.1&Ext=PDF",
        "satzung", "obdach_gebuehr", "Aschaffenburger Stadtrecht 50.5 Gebührensatzung für Unterkünfte für Obdachlose vom 23.09.2016",
        "Gebührensatzung für Unterkünfte, in denen Obdachlose oder von Obdachlosigkeit bedrohten Personen untergebracht sind",
        "2016-09-23", "Vom 23.09.2016 (amtlich bekannt gemacht am 23.09.2016)", "original",
        "Monthly fees: in rented units up to 497 EUR for one person (417 basic + 80 heating), rising by household size; "
        "276.56 EUR per month in the men's and the women's transitional hostels. The use statute 50.4 (23.09.2016, "
        "amended 21.06.2018) runs the transitional hostel and rented units as a public facility.",
        ["Für die Benutzung der städtischen Obdachlosenunterkünfte im Sinne des § 1"],
        fees=[_fee("obdach_gebuehr_max_eur_monat__einzelperson_angemietet", 497.00, "EUR/Monat",
                   "Bei einer Person, maximal 497,00 EUR", "§ 4 Abs. 1", 2016),
              _fee("obdach_gebuehr_eur_person_monat__uebergangswohnheim", 276.56, "EUR/Person/Monat",
                   "jeweils monatlich 276,56", "§ 4 Abs. 2", 2016)],
        extra=[("https://www.aschaffenburg.de/loadDocument.phtml?FID=4173.131.1&Ext=PDF",
                ["geändert durch Satzung vom 21.06.2018 (amtlich bekannt gemacht am 29.06.2018)",
                 "ein Übergangswohnheim für Obdachlose als öffentliche Einrichtung"])]),
    _mu("aschaffenburg_sns", "09661", "BY", "Aschaffenburg",
        "https://www.aschaffenburg.de/loadDocument.phtml?FID=4173.143.1&Ext=PDF",
        "satzung", "betteln,lagern,alkohol,sondernutzung", "Aschaffenburger Stadtrecht 60.2 Sondernutzungssatzung vom 19.07.2012 (bekannt gemacht 10.08.2012)",
        "Satzung der Stadt Aschaffenburg für Sondernutzungen an öffentlichen Verkehrsflächen und die Gebühren hierfür",
        "2012-08-10", "Vom 19.07.2012 (amtlich bekannt gemacht am 10.08.2012)", "original",
        "Sleeping, begging, and settling down mainly to drink alcohol outside licensed outdoor bar areas are not "
        "permissible special uses of public roads.",
        ["(3) Nicht erlaubnisfähig sind a) das Nächtigen, b) das Betteln, c) das Sich-Niederlassen ausschließlich oder überwiegend zum Zwecke des Alkoholgenusses"]),
    _mu("kaufbeuren_obdach_geb", "09762", "BY", "Kaufbeuren",
        "https://www.kaufbeuren.de/DownloadCount.aspx?raid=87625&docid=7172&rn=597e76c4-2c52-4c14-aae6-1b7685913769",
        "satzung", "obdach_gebuehr", "Kaufbeurer Stadtrecht 731 Obdachlosenunterkunftsgebührensatzung (OGS) vom 22.11.2017, geändert durch Satzung vom 05.06.2024 (ABl. Nr. 11/2024)",
        "Gebührensatzung zur Satzung über die Benutzung der Obdachlosenunterkünfte der Stadt Kaufbeuren (Obdachlosenunterkunftsgebührensatzung – OGS)",
        "2024-06-05", "Geändert durch Satzung vom 05.06.2024 (ABl. Nr. 11/2024)", "consolidated",
        "Fees by floor area or actual building costs: family flats Bachschmidstraße 2 at 7.70 EUR per started m² per "
        "month incl. service charges (without utilities), plus utility flat rates per person; fixed monthly fees for "
        "other units. The use statute 730 (OBS, 22.11.2017) governs the shelters.",
        ["Die Gebühr für die Benutzung der Obdachlosenunterkunft bemisst sich nach der Nutzfläche"],
        fees=[_fee("obdach_gebuehr_eur_m2_monat__wohnung", 7.70, "EUR/m²/Monat",
                   "für Wohnungen 7,70 EUR", "§ 4 Nr. 1", 2024)],
        extra=[("https://www.kaufbeuren.de/DownloadCount.aspx?raid=71317&docid=7171&rn=de3a8eb0-6e35-4fe9-91c7-82960b5c3058",
                ["(OBDACHLOSENUNTERKUNFTSBENUTZUNGSSATZUNG – OBS) Vom 22.11.2017"])]),
    _mu("kaufbeuren_sns", "09762", "BY", "Kaufbeuren",
        "https://www.kaufbeuren.de/DownloadCount.aspx?raid=87621&docid=11462&rn=791e03b9-a58d-4619-b02d-8e8c3f277236",
        "satzung", "betteln,lagern,alkohol,sondernutzung", "Kaufbeurer Stadtrecht 650 Sondernutzungssatzung vom 21.02.2018, zuletzt geändert 05.06.2024 (ABl. Nr. 11/2024)",
        "Satzung über die Sondernutzungen an öffentlichen Straßen und die Erhebung von Sondernutzungsgebühren in der Stadt Kaufbeuren (Sondernutzungssatzung)",
        "2024-06-05", "vom 05.06.2024 (ABl. Nr. 11/2024)", "consolidated",
        "A special-use permit must be refused for lying around and sleeping, for settling down mainly to drink alcohol "
        "outside licensed outdoor bar areas, and for begging that is aggressive, organised or otherwise disturbs public "
        "safety and order.",
        ["(5) Die Sondernutzungserlaubnis wird nicht erteilt und muss versagt werden 1. für das Lagern und Nächtigen",
         "3. für das Betteln, soweit es in aggressiver Form oder organisiert betrieben wird"]),
    _mu("dessau_obdach_geb", "15001", "ST", "Dessau-Roßlau",
        "https://verwaltung.dessau-rosslau.de/fileadmin/Verwaltungsportal_Dessau-Rosslau/Stadt_Buerger/Buergerservice/Stadtrecht/Obdachlosenunterbringung/24.03.2022_obdachlosenunterkuenfte_gebuehrensatzung.pdf",
        "satzung", "obdach_gebuehr", "Stadtrecht Dessau-Roßlau Gebührensatzung Obdachlosenunterkünfte vom 10.10.2002 (Amtsblatt 11/02 vom 26.10.2002)",
        "Satzung über die Erhebung von Gebühren für die Benutzung der Obdachlosenunterkünfte in der Stadt Dessau",
        "2002-10-26", "26. Oktober 2002 11/02 S. 2 27. Oktober 2002", "original",
        "Fees for basic city flats per m² (2.00 EUR without, 3.00 EUR with service charges), rent-equivalent charge for "
        "requisitioned flats, and 3.60 EUR per bed and night in the shared shelter. The use statute (Amtsblatt 12/02, "
        "in force 01.12.2002) covers temporary accommodation of homeless people.",
        ["Die Stadt erhebt gemäß der Satzung über die Unterbringung von Obdachlosen für die Benutzung der Unterkünfte Gebühren"],
        fees=[_fee("obdach_gebuehr_eur_m2_monat__schlichtwohnung_mit_betriebskosten", 3.00, "EUR/m²/Monat",
                   "mit Betriebskosten 3,00 EUR", "§ 2 Abs. 2", 2002),
              _fee("obdach_gebuehr_eur_bett_nacht__gemeinschaftsunterkunft", 3.60, "EUR/Bett/Nacht",
                   "pro Bett: 3,60 EUR", "§ 4 Abs. 1", 2002)],
        note="statute of the former city of Dessau (before the 2007 merger), still listed in the current Stadtrecht of "
             "Dessau-Roßlau; the posted text is marked as reading material ('Lese- und Arbeitsmaterial')",
        extra=[("https://verwaltung.dessau-rosslau.de/fileadmin/Verwaltungsportal_Dessau-Rosslau/Stadt_Buerger/Buergerservice/Stadtrecht/Obdachlosenunterbringung/24.03.2022_obdachlosenunterbringung_satzung.pdf",
                ["Satzung über die Unterbringung Obdachloser in der kreisfreien Stadt Dessau"])]),
    _mu("suhl_unterbringung_geb", "16054", "TH", "Suhl",
        "https://www.suhl.eu/_files/ugd/0cdbf2_b1bf548f52cd4d689ea501af1671a895.pdf",
        "satzung", "obdach_gebuehr", "Suhler Stadtrecht Unterbringungsgebührensatzung vom 16.05.2025 (veröffentlicht 31.05.2025)",
        "Benutzungsgebührensatzung für öffentliche Einrichtungen bei der Unterbringung besonderer Bedarfsgruppen in der Stadt Suhl (Unterbringungsgebührensatzung)",
        "2025-05-31", "vom 16.05.2025 veröffentlicht am 31.05.2025", "original",
        "Fees for the shelter (Obdachlosenherberge) under § 2(1)(a) of the use statute: 19.50 EUR per person and day or "
        "585.00 EUR per person and month; single units at the contracted rent. The Unterbringungssatzung of the same "
        "date lists homeless people among the groups housed.",
        ["Die Gebühren für die Unterbringung gemäß § 2 Abs. 1a) der Unterbringungssatzung betragen"],
        fees=[_fee("obdach_gebuehr_eur_person_tag", 19.50, "EUR/Person/Tag",
                   "19,50 EUR pro Tag und Person", "§ 4 Abs. 1 a", 2025),
              _fee("obdach_gebuehr_eur_person_monat", 585.00, "EUR/Person/Monat",
                   "585,00 EUR pro Monat und Person", "§ 4 Abs. 1 b", 2025)],
        extra=[("https://www.suhl.eu/_files/ugd/0cdbf2_396ff4c835a24713b684cf24a6c6104c.pdf",
                ["(Unterbringungssatzung) vom 16.05.2025 veröffentlicht am 31.05.2025"])]),
    _mu("suhl_stadtordnung", "16054", "TH", "Suhl",
        "https://www.suhl.eu/_files/ugd/1b847c_1b955112902448ec8aea4331954e0555.pdf",
        "verordnung", "betteln,lagern,alkohol", "Suhler Stadtrecht Ordnungsbehördliche Verordnung (Stadtordnung) vom 01.12.2015 i.d.F. vom 07.12.2020",
        "Ordnungsbehördliche Verordnung der Stadt Suhl über die Abwehr von Gefahren durch Verunreinigungen, störendes Verhalten in der Öffentlichkeit u.a. (Stadtordnung)",
        "2020-12-07", "Ordnungsbehördliche Verordnung der Stadt Suhl vom 01.12.2015 in der Fassung vom 07.12.2020", "consolidated",
        "Bans conduct in public that endangers, obstructs or bothers others, notably lying around or lingering while "
        "drinking or using drugs where it impairs public use, aggressive begging (blocking, touching, using animals), and "
        "sleeping. Valid until 31.12.2031.",
        ["a) das Lagern oder dauerhafte Verweilen in Verbindung mit Alkohol- oder anderen Rauschmittel",
         "d) das Nächtigen", "Diese Verordnung gilt bis zum 31.12.2031"],
        ends_on='2032-01-01', ends_needle='Diese Verordnung gilt bis zum 31.12.2031'),
    _mu("weiden_sns", "09363", "BY", "Weiden i.d.OPf.",
        "https://www.weiden.de/fileadmin/user_upload/A_Stadt-Rathaus-Buerger/A03_Rathaus/Stadtrecht/S320.pdf",
        "satzung", "betteln,alkohol,sondernutzung", "Weidener Stadtrecht S320 Sondernutzungssatzung vom 05.03.2021",
        "Satzung der Stadt Weiden i.d.OPf. über die Benutzung öffentlichen gemeindlichen Verkehrsgrundes (Sondernutzungssatzung – SondernutzungsS)",
        "2021-03-05", "(Sondernutzungssatzung – SondernutzungsS) Vom 05.03.2021", "original",
        "A special-use permit is refused for active begging. The Grünanlagensatzung (S730, 23.12.2003) bans staying in "
        "parks, especially in groups, mainly to drink alcohol outside licensed outdoor seating, and camping or sleeping "
        "without permission.",
        ["e) für aktives Betteln"],
        extra=[("https://www.weiden.de/fileadmin/user_upload/A_Stadt-Rathaus-Buerger/A03_Rathaus/Stadtrecht/S730.pdf",
                ["Zwecke des Genusses von alkoholischen Getränken außerhalb von gaststättenrechtlich konzessionierten",
                 "9. das Zelten, Aufstellen von Wohnwagen und Nächtigen ohne Erlaubnis"])]),
    _mu("wilhelmshaven_anlagen", "03405", "NI", "Wilhelmshaven",
        "https://www.wilhelmshaven.de/medien/satzungen/900000067_sr32_06_satzung_ueber_die_benutzung_oeffentlicher_anlagen_der_stadt_wilhelmshaven_2016.pdf",
        "satzung", "betteln,lagern,alkohol", "Wilhelmshavener Stadtrecht Sr32-06 Satzung über die Benutzung von öffentlichen Anlagen vom 14.12.2016",
        "Satzung über die Benutzung von öffentlichen Anlagen der Stadt Wilhelmshaven",
        "2016-12-14", "Wilhelmshaven, den 14.12.2016", "original",
        "In public parks bans aggressive and persistent begging, long-term settling such as camping, sleeping, lying "
        "around and overnight stays, and staying to drink alcohol or while visibly drunk where others are bothered.",
        ["13. Aggressives und hartnäckiges Betteln ist verboten",
         "Das andauernde Niederlassen wie z.B. das Campieren, Schlafen, Lagern und Übernachten ist in den Anlagen verboten"]),
    _mu("berlin_untgebo", "11000", "BE", "Berlin",
        "https://www.berlin.de/sen/soziales/besondere-lebenssituationen/wohnungslose/unterbringung/be_untgebo_zweite_aenderung_16122025.pdf",
        "verordnung", "obdach_gebuehr", "Zweite Verordnung zur Änderung der Unterbringungsgebührenordnung vom 16.12.2025 (GVBl. Berlin Nr. 36 vom 23.12.2025, S. 664)",
        "Zweite Verordnung zur Änderung der Unterbringungsgebührenordnung",
        "2025-12-23", "81. Jahrgang Nr. 36 23. Dezember 2025", "original",
        "Land ordinance on fees for publicly arranged accommodation of homeless people (UntGebO of 16.07.2024, in force "
        "01.01.2025); from 01.01.2026 the standard fee is 855 EUR per person and month, reduced to 342 EUR on application "
        "within income limits. Per the Senate's page it applies first to the LFU's accommodation; district ASOG shelters "
        "are to be brought in step by step.",
        ["Zweite Verordnung zur Änderung der Unterbringungsgebührenordnung Vom 16. Dezember 2025"],
        fees=[_fee("obdach_gebuehr_eur_person_monat", 855, "EUR/Person/Monat",
                   "„855“ und das Semikolon am Ende", "Art. 1 Nr. 3 a (Anlage Nr. 1)", 2026),
              _fee("obdach_gebuehr_ermaessigt_eur_person_monat", 342, "EUR/Person/Monat",
                   "Eine ermäßigte Gebühr in Höhe von 342 Euro", "Art. 1 Nr. 3 b (Anlage Nr. 2)", 2026)],
        in_force_from="2026-01-01",
        note="amending ordinance from the GVBl. as posted by the Senate department on berlin.de (two-column layout); the "
             "consolidated text is only on gesetze.berlin.de (juris, excluded)",
        extra=[("https://www.berlin.de/sen/soziales/besondere-lebenssituationen/wohnungslose/unterbringung/be_untgebo_16072024.pdf",
                ["(Unterbringungsgebührenordnung – UntGebO) Vom 16. Juli 2024"]),
               ("https://www.berlin.de/sen/soziales/besondere-lebenssituationen/wohnungslose/unterbringung/untgebo-1464244.php",
                ["sollen schrittweise auch die sogenannten ASOG-Unterkünfte zur ordnungsrechtlichen Unterbringung wohnungsloser Menschen"])]),
    # ---- batch 16 (2026-11-21): retries of found-but-not-done cells ----
    _mu("ffo_obdach_geb", "12053", "BB", "Frankfurt (Oder)",
        "https://www.frankfurt-oder.de/loadDocument.phtml?FID=4071.743.1&Ext=PDF",
        "satzung", "obdach_gebuehr", "Ortsrecht Frankfurt (Oder) Nutzungs- und Gebührensatzung der Unterkunft für Wohnungslose An den Seefichten 20 vom 04.08.2025 (rückwirkend ab 01.06.2025)",
        "Satzung über die Nutzung und die Erhebung von Gebühren in der Unterkunft für Wohnungslose am Standort An den Seefichten 20 in der Stadt Frankfurt (Oder)",
        "2025-08-04", "Frankfurt (Oder), den 04.08.2025", "original",
        "Use and fee statute for the city's homeless shelter: 21.92 EUR per day and place after an allocation decision, "
        "9.89 EUR per night and place as night shelter (Nachtasyl).",
        ["Diese Satzung tritt rückwirkend zum 01.06.2025 in Kraft"],
        fees=[_fee("obdach_gebuehr_eur_platz_tag", 21.92, "EUR/Platz/Tag",
                   "beträgt pro Tag und Platz 21,92", "§ 11 Abs. 2", 2025),
              _fee("obdach_notuebernachtung_eur_platz_nacht", 9.89, "EUR/Platz/Nacht",
                   "als Nachtasyl beträgt pro Nacht und Platz 9,89", "§ 11 Abs. 3", 2025)],
        in_force_from="2025-06-01"),
    _mu("ffo_stadtordnung", "12053", "BB", "Frankfurt (Oder)",
        "https://www.frankfurt-oder.de/loadDocument.phtml?FID=4071.221.1&Ext=PDF",
        "verordnung", "lagern", "Ortsrecht Frankfurt (Oder) Stadtordnung 2020, Lesefassung mit Erster und Zweiter Änderung (06.12.2024)",
        "Ordnungsbehördliche Verordnung über die Aufrechterhaltung der öffentlichen Sicherheit und Ordnung für das Gebiet der Stadt Frankfurt (Oder) – Stadtordnung",
        "2024-12-06", "Frankfurt (Oder), 06.12.2024", "consolidated",
        "In public parks and facilities bans sleeping and putting up or using tents outside designated sites. The "
        "street/park alcohol ban of § 5 was limited to 31.12.2025 and has lapsed; no begging rule.",
        ["f) zu nächtigen, Zelte aufzustellen oder zu benutzen, außer auf dafür vorgesehenen Plätzen",
         "(2) § 5 und § 13 Abs. 1 Nummer 17 gelten befristet bis zum 31.12.2025"],
        note="reading version (Lesefassung) posted by the city; the Amtsblatt promulgations are authoritative"),
    _mu("pirmasens_gavo", "07317", "RP", "Pirmasens",
        "https://www.pirmasens.de/downloads/ortsrecht/gefahrenabwehrverordnung-2021f?cid=16nj",
        "verordnung", "betteln", "Pirmasenser Ortsrecht Gefahrenabwehrverordnung vom 22.10.2020, ergänzt 19.05.2021 und 16.12.2021",
        "Gefahrenabwehrverordnung über die Aufrechterhaltung der öffentlichen Sicherheit und Ordnung in der Stadt Pirmasens",
        "2021-12-20", "§ 3 und § 10 geändert durch Ergänzung der Gefahrenabwehrverordnung vom 16.12.2021", "consolidated",
        "Bans harassing or endangering others or disturbing public order by aggressive or disruptive begging, "
        "addressing people at close quarters, abuse, noise or obstruction. In force 23.10.2020 to 22.10.2040.",
        ["durch aggressives oder störendes Betteln, körpernahes Ansprechen",
         "tritt am 23.10.2020 in Kraft und mit Ablauf des 22.10.2040 außer Kraft"],
        ends_on='2040-10-23', ends_needle='tritt am 23.10.2020 in Kraft und mit Ablauf des 22.10.2040 außer Kraft'),
    _mu("hamm_stao", "05915", "NW", "Hamm",
        "https://www.hamm.de/satzungen/satzungen/detail/291",
        "verordnung", "betteln,lagern,alkohol", "Hammer Ortsrecht Straßen- und Anlagenordnung vom 14.12.2021 einschl. 1. Änderung vom 07.06.2023 (in Kraft 10.06.2023)",
        "Ordnungsbehördliche Verordnung über die Aufrechterhaltung der öffentlichen Sicherheit und Ordnung auf den Straßen und in den Anlagen im Gebiet der Stadt Hamm (Straßen- und Anlagenordnung)",
        "2023-06-09", "vom 07.06.2023 (Verkündung am 09.06.2023, Inkrafttreten am 10.06.2023)", "consolidated",
        "Bans behaviour that more than slightly obstructs or bothers others on roads and in parks, notably "
        "alcohol-related disturbance and intrusive or aggressive begging; roads and parks may not be used for lying "
        "around and sleeping unless expressly allowed.",
        ["(4) Anlagen und Straßen dürfen nicht zum Lagern und Nächtigen genutzt werden",
         "insbesondere durch Konsum alkoholischer Getränke oder anderer Rauschmittel bedingte Störungen, aufdringliches oder aggressives Betteln"],
        note="HTML text on the city's Satzungen detail page (current version incl. the 2023 amendment)"),
    # kreisangehörige cities over ~80k (gem set explicitly; checked against geo at run time)
    _mu("witten_unterbringung", "05954", "NW", "Witten",
        "https://www.witten.de/downloads/datei/MjU2YWYwZjBjMjRmZDkxZXlzSjlxUUFCaEozcTFYQjBDTVBiVzNlSjczZEl2VldmK0tJc3BCcFgrRldsOVh6b04zbGpqZDdLVTRoc00vbnA3SFRsRVgwUVRXamJHd3RBS0d0T2cvVDkzWEd1RVZFc0gwdkxULzZ4M1FjMFRlM0tJMFh3QmdoWUlpMi80elFEL3NVWWNwcXdDVjI0ajRGZ0dWc1E4Rm8xbExzMU9EMXA4Z210cTNpVXZ4SUR1Q1NTcW4zbjVNZWEzdWN6TG9ZeE9Xbk93RU80Vlc5MEpQS2JZUjR3cWZ6bUxOUy94QTJ1TTFNemJmRzRRWi9LTXVPL3lWS3Q1TjErN2oxZTg4ZUVLTEorNmw0U2lDTzlrNWp2VmpqT2t3PT0",
        "satzung", "obdach,obdach_gebuehr", "Wittener Ortsrecht 5.12 Satzung über die Unterbringung von Personen und Festsetzung der Benutzungsgebühren vom 18.02.2025 (in Kraft 01.01.2025)",
        "Satzung der Stadt Witten über die Unterbringung von Personen und Festsetzung der zu erhebenden Benutzungsgebühren",
        "2025-02-18", "Benutzungsgebühren vom 18.02.2025", "original",
        "Use and fee statute for shared shelters and buildings for temporary accommodation of homeless people under "
        "§ 14 OBG (and refugees). Fee schedule (Anlage 2): monthly per m² 11.91 EUR basic + 3.91 EUR consumption in the "
        "shared shelter, 10.81 + 7.44 EUR in flat-type units.",
        ["für die vorübergehende Unterbringung obdachloser Personen gemäß § 14 Ordnungsbehördengesetz",
         "Die Satzung tritt am 01.01.2025 in Kraf"],
        extra=[("https://www.witten.de/downloads/datei/ZjVkZmQyZjViNzk5OWVlN21NMFVQaEdUVVY0RllGTjlzbE9ucHBMWHJYRlI1WXZ6UjZHNUpsN0RHS1NrNVBCQ21OVFlCYzIvOG92V2E4Uk5rdFlsUXIyWHJBQ0ZOb3FFeTFOeTJ3dXUxaDFmMzBndmZCMllUaFhwSWdEeGFiL1JQc1JiZ0VOSnl5WEZlRE9l",
                ["anrechenbarer Wohnfläche 11,91 Euro zuzüglich Verbrauchskosten von monatlich 3,91 Euro"])],
        in_force_from="2025-01-01", gem="05954036"),
    _mu("iserlohn_obdach_geb", "05962", "NW", "Iserlohn",
        "https://www.iserlohn.de/fileadmin/user_upload/Dokumente/Rathaus_Online/Satzungen_und_Verordnungen/Satzung_ueber_die_Erhebung_von_Gebuehren_fuer_die_Benutzung_der_Obdachlosenunterkuenfte_der_Stadt_Iserlohn.pdf",
        "satzung", "obdach_gebuehr", "Iserlohner Ortsrecht 32.42 Gebührensatzung Obdachlosenunterkünfte vom 09.12.1975, zuletzt geändert 19.12.2007",
        "Satzung über die Erhebung von Gebühren für die Benutzung der Obdachlosenunterkünfte der Stadt Iserlohn",
        "2007-12-19", "19. Dezember 2007", "consolidated",
        "Monthly fee per m² of allocated floor space: 9.91 EUR at Oestricher Str. 124 and 12.42 EUR at Mendener "
        "Landstraße 6; 4.00 EUR per person and night in the night shelter (Obdachlosenasyl).",
        ["Für die Benutzung der von der Stadt unterhaltenen Obdachlosenunterkünfte und der Schlafplätze zum Zweck der Übernachtung"],
        fees=[_fee("obdach_gebuehr_eur_m2_monat__oestricher_str", 9.91, "EUR/m²/Monat", "Oestricher Str. 124 9,91", "§ 2 Abs. 1", 2007),
              _fee("obdach_gebuehr_eur_m2_monat__mendener_landstr", 12.42, "EUR/m²/Monat", "Mendener Landstraße 6 12,42", "§ 2 Abs. 1", 2007),
              _fee("obdach_notuebernachtung_eur_person_nacht", 4.00, "EUR/Person/Nacht", "je Person und Übernachtung 4,00", "§ 2 Abs. 3", 2007)],
        note="the consolidated text lists council decisions up to 18.12.2007. Re-checked 2026-11-23: the city's "
             "Gebühren- und Beitragssatzungen page still links this same file (unchanged, Last-Modified 21.10.2020) and "
             "no later amendment is listed, so the 2007 fees are the latest published; a change promulgated only in the "
             "Amtsblatt cannot be ruled out",
        gem="05962024"),
    _mu("reutlingen_unterkuenfte_geb", "08415", "BW", "Reutlingen",
        "https://www.reutlingen.de/ceasy/serve/usage/main.php?view=publish&item=statute&id=1008",
        "satzung", "obdach,obdach_gebuehr", "Reutlinger Stadtrecht SR 1.60 Benutzungs- und Gebührensatzung Unterkünfte für Obdachlose und Anschlussunterbringung vom 28.02.2023, zuletzt geändert 28.04.2026",
        "Benutzungs- und Gebührensatzung für die Unterkünfte zur Unterbringung von Obdachlosen und zur Anschlussunterbringung von Flüchtlingen",
        "2026-04-28", "vom 28.02.2023, zuletzt geändert am 28.04.2026", "consolidated",
        "Use and fee statute for homeless and refugee follow-up accommodation: shared shelters 480 EUR per bed and month "
        "for adults and 330 EUR for minors (incl. running costs); other flats and rooms 16.83 EUR per m² and month.",
        ["Benutzungs- und Gebührensatzung für die Unterkünfte zur Unterbringung von Obdachlosen und zur Anschlussunterbringung von Flüchtlingen vom 28.02.2023"],
        fees=[_fee("obdach_gebuehr_eur_bett_monat__gemeinschaftsunterkunft_erwachsene", 480.00, "EUR/Bett/Monat",
                   "Personen ab Vollendung des 18. Lebensjahres: 480,00", "§ 16 Abs. 2", 2026),
              _fee("obdach_gebuehr_eur_m2_monat__wohnung", 16.83, "EUR/m²/Monat",
                   "beträgt je m²-Wohnfläche und Kalendermonat: 16,83 Euro", "§ 16 Abs. 4", 2026)],
        gem="08415061"),
    _mu("ratingen_unterkuenfte", "05158", "NW", "Ratingen",
        "https://www.stadt-ratingen.de/fileadmin/user_upload/Bilder/33/Rechtsamt/Ortsrecht/5-Soziales_Jugend_und_Gesundheit/515_Satzung_der_Stadt_Ratingen_ueber_die_Benutzung_und_Erhebung_von_Gebuehren_der_Unterkuenfte_fuer_Fluechtlinge_und_Obdachlose.pdf",
        "satzung", "obdach,obdach_gebuehr", "Ratinger Ortsrecht 515 FlüObUntBGSR vom 16.07.2019 (Amtsblatt Ratingen 2019, S. 178), in Kraft 01.09.2019",
        "Satzung der Stadt Ratingen über die Benutzung und Erhebung von Gebühren der Unterkünfte für Flüchtlinge und Obdachlose",
        "2019-07-16", "in der Fassung vom 16.07.2019", "original",
        "Use and fee statute for shelters for homeless people under § 14 OBG (group a) and refugees (group b). Monthly "
        "fee per person for group a: 128.76 EUR base + 106.81 EUR consumption, rounded total 236 EUR; group b: 244 EUR.",
        ["Obdachlose, die gem. § 14 des Ordnungsbehördengesetzes (OBG)"],
        fees=[_fee("obdach_gebuehr_eur_person_monat", 236.00, "EUR/Person/Monat",
                   "Die monatliche Gesamtgebühr beträgt somit gerundet 236,00 Euro pro Person", "§ 8 Abs. 2", 2019)],
        in_force_from="2019-09-01", gem="05158028"),
    _mu("lueneburg_unterbringung_geb", "03355", "NI", "Lüneburg",
        "https://www.hansestadt-lueneburg.de/_Resources/Persistent/7/f/9/5/7f95ffe8b656a368528dadcde6d109e6681bba24/50_06%20Geb%C3%BChrensatzung%20Unterbringung.pdf",
        "satzung", "obdach_gebuehr", "Lüneburger Ortsrecht 50-06 Gebührensatzung Unterbringung obdachloser und geflüchteter Personen vom 12.12.2025 (in Kraft 01.01.2026)",
        "Satzung über die Erhebung von Gebühren für die Unterbringung obdachloser und geflüchteter Personen in den Unterkünften der Hansestadt Lüneburg",
        "2025-12-12", "Lüneburg, den 12.12.2025", "original",
        "Monthly fees per person: shared accommodation/housing projects 290 EUR use fee + 98 EUR running costs; emergency "
        "shelters (Notunterkünfte) 549 EUR + 162 EUR; optional full board charged at the Regelbedarf food share.",
        ["Satzung über die Erhebung von Gebühren für die Unterbringung obdachloser und geflüchteter Personen in den Unterkünften der Hansestadt Lüneburg"],
        fees=[_fee("obdach_gebuehr_eur_person_monat__gemeinschaftsunterkunft", 290.00, "EUR/Person/Monat",
                   "1.1. Benutzungsgebühr 290,00 Euro", "Gebührenverzeichnis Nr. 1.1", 2026),
              _fee("obdach_gebuehr_eur_person_monat__notunterkunft", 549.00, "EUR/Person/Monat",
                   "2.1. Benutzungsgebühr 549,00 Euro", "Gebührenverzeichnis Nr. 2.1", 2026)],
        in_force_from="2026-01-01", gem="03355022"),
    _mu("minden_obdach", "05770", "NW", "Minden",
        "https://www.minden.de/dokumente/satzungen/oeffentliche-sicherheit-und-ordnung/3.07-obdachlosenunterkuenfte.pdf?cid=1d44",
        "satzung", "obdach,obdach_gebuehr", "Mindener Stadtrecht 3.7 Satzung Obdachlosenunterkünfte und Benutzungsgebühren vom 20.05.1997, § 7 zuletzt geändert 16.12.2025 (in Kraft 01.01.2026)",
        "Satzung über die Errichtung und Unterhaltung von Obdachlosenunterkünften und die Erhebung von Benutzungsgebühren in der Stadt Minden",
        "2025-12-16", "16.12.25", "consolidated",
        "Shelters for the temporary accommodation of homeless people (Am Weserstadion, Bruchstraße, Schülerweg, "
        "Windmühlenstraße); monthly fee per m² of allocated floor space set per building, e.g. 10.04 EUR at Am Weserstadion 4 "
        "and 15.73 EUR at Bruchstraße 5a/5b.",
        ["Zur vorübergehenden Unterbringung obdachloser Personen unterhält die Stadt Minden"],
        fees=[_fee("obdach_gebuehr_eur_m2_monat__am_weserstadion_4", 10.04, "EUR/m²/Monat", "Am Weserstadion 4 10,04 EUR", "§ 7 Abs. 3", 2026),
              _fee("obdach_gebuehr_eur_m2_monat__bruchstrasse_5", 15.73, "EUR/m²/Monat", "Bruchstraße 5a und 5b 15,73 EUR", "§ 7 Abs. 3", 2026)],
        in_force_from="2026-01-01", gem="05770024"),
    _mu("norderstedt_notunterkunft_geb", "01060", "SH", "Norderstedt",
        "https://www.norderstedt.de/media/custom/3224_9597_1.PDF?1732865028",
        "satzung", "obdach_gebuehr", "Norderstedter Ortsrecht 3/01/2 Notunterkunftsgebührensatzung vom 17.07.2015 i.d.F. der Dritten Nachtragssatzung (in Kraft 01.01.2025)",
        "Satzung über die Erhebung von Benutzungsgebühren für die Notunterkünfte der Stadt Norderstedt (Notunterkunftsgebührensatzung)",
        "2025-01-01", "Textstand: Dritte Nachtragssatzung Inkrafttreten: 01.01.2025", "consolidated",
        "Use fee for municipal emergency shelters (Notunterkünfte): 552.05 EUR per person and month including heating and "
        "running costs.",
        ["Satzung über die Erhebung von Benutzungsgebühren für die Not unterkünfte der Stadt Norderstedt"],
        fees=[_fee("obdach_gebuehr_eur_person_monat", 552.05, "EUR/Person/Monat",
                   "Die Benutzungsgebühr beträgt für jede Person 552,05 € monatlich", "§ 2 Abs. 1", 2025)],
        note="as_of is the in-force date of the Third Nachtragssatzung stated in the text; its signing date is not given in the PDF",
        in_force_from="2025-01-01", gem="01060063"),
    _mu("velbert_unterkuenfte_geb", "05158", "NW", "Velbert",
        "https://www.velbert.de/fileadmin/user_upload/Rathaus_und_Politik/Ortsrecht/Gebuehrensatzung_Fluechtlingsunterkuenfte.pdf",
        "satzung", "obdach,obdach_gebuehr", "Benutzungs- und Gebührensatzung der Stadt Velbert für Unterkünfte für Flüchtlinge, Spätaussiedler und Obdachlose vom 29.10.2025 (in Kraft 01.09.2025)",
        "Benutzungs- und Gebührensatzung der Stadt Velbert für Unterkünfte für Flüchtlinge, Spätaussiedler und Obdachlose",
        "2025-10-29", "Obdachlose vom 29.10.2025", "original",
        "Use and fee statute for shelters for refugees, ethnic German resettlers and homeless people. Annex 1: monthly base "
        "fee per m² 6.00 or 6.75 EUR depending on the building, plus 3.50 EUR/m² water/general electricity and household "
        "electricity charges.",
        ["Benutzungs- und Gebührensatzung der Stadt Velbert für Unterkünfte für Flüchtlinge, Spätaussiedler und Obdachlose vom 29.10.2025"],
        fees=[_fee("obdach_gebuehr_eur_m2_monat__grundgebuehr_kuhler_str", 6.00, "EUR/m²/Monat", "Kuhler Str. 21-23 6,00 €", "Anlage 1", 2025),
              _fee("obdach_gebuehr_eur_m2_monat__grundgebuehr_heidestr", 6.75, "EUR/m²/Monat", "Heidestr. 82 6,75 €", "Anlage 1", 2025)],
        in_force_from="2025-09-01", gem="05158032"),
    # ---- batch 17 (2026-11-21): open cells, kreisangehörige (a), (b) for kreisangehörige ----
    _mu("speyer_obdach", "07318", "RP", "Speyer",
        "https://www.speyer.de/de/rathaus/verwaltung/ortsrechtssammlung/2.4.13-obdachlosenunterkuenfte-2026.pdf?cid=4fcg",
        "satzung", "obdach,obdach_gebuehr", "Speyerer Ortsrecht 2.4.13 Satzung über die Benutzung von Obdachlosenunterkünften und Unterkünfte für Schutzsuchende vom 24.04.2026",
        "Satzung der Stadt Speyer über die Benutzung von Obdachlosenunterkünften und Unterkünfte für Schutzsuchende",
        "2026-04-24", "Speyer, den 24.04.2026", "original",
        "Use statute for shelters for homeless people and refugee accommodation (replaces the statute of 29.07.2005). "
        "Defines homelessness, assignment by written order, relocation rules; fees are set per case from the city's actual "
        "costs for the assigned unit (no fixed rate in the statute), normally as a monthly fee.",
        ["Obdachlos ist derjenige, der nicht Tag und Nacht über eine Unterkunft verfügt",
         "richten sich im Einzelfall nach den Aufwendungen, die der Stadtverwaltung Speyer für die jeweils zugewiesene Unterkunft entstehen"],
        note="in force on the day after publication (Amtsblatt Nr. 016/2026 of 24.04.2026 per the city's Amtsblatt index); no fixed fee amounts"),
    _mu("kiel_obdach_geb", "01002", "SH", "Kiel",
        "https://www.kiel.de/de/_data/ortsrecht_bekanntmachungen/root/download.php?typ=lf&fid=de910441d1ec7a38b3745a713bb45cce",
        "satzung", "obdach_gebuehr", "Kieler Ortsrecht Gebührensatzung für Ersatzwohnungen und Gemeinschaftsunterkünfte vom 19.08.2008 i.d.F. der 1. Nachtragssatzung vom 27.10.2016 (Lesefassung)",
        "Gebührensatzung für Ersatzwohnungen und Gemeinschaftsunterkünfte der Landeshauptstadt Kiel",
        "2016-10-27", "in der Fassung der 1. Nachtragssatzung vom 27.10.2016", "consolidated",
        "Fee statute for replacement flats and shared shelters used for the temporary police-law accommodation of people "
        "affected by acute homelessness (§§ 174, 176 LVwG SH). Replacement flats: actual cold rent, heating and running "
        "costs; shared shelters: a daily rate computed as monthly costs / 30 days / available beds (no fixed amount).",
        ["der vorübergehenden ordnungsbehördlichen Unterbringung aktuell von Wohnungslosigkeit betroffenen Personen (akute Wohnungsnotfälle)",
         "Kosten / 30 Tage / Anzahl der zur Verfügung stehenden Betten"],
        note="city's text-layer reading copy (typ=lf); replaces the earlier poor scan of the 2008 original"),
    _mu("ludwigshafen_gavo", "07314", "RP", "Ludwigshafen am Rhein",
        "https://ludwigshafen.de/fileadmin/ludwigshafen/verwaltung_und_politik/stadtverwaltung_rathaus/Ortsrecht/1-15.pdf",
        "verordnung", "betteln,lagern,alkohol", "Ludwigshafener Ortsrecht 1-15 Gefahrenabwehrverordnung Straßen und Anlagen vom 27.04.2026 (Amtsblatt Nr. 29 vom 06.05.2026), in Kraft 01.05.2026 bis 31.12.2046",
        "Gefahrenabwehrverordnung zur Aufrechterhaltung der Sicherheit und Ordnung auf öffentlichen Straßen und in öffentlichen Anlagen",
        "2026-04-27", "öffentlichen Anlagen vom 27.04.2026", "original",
        "City-wide hazard-prevention ordinance for public streets and green spaces: bans lying around (lagern) and camping "
        "outside designated areas, begging in an aggressive or disruptive form, and settling down to consume alcohol or "
        "other intoxicants so that others are disturbed (pestering, shouting, leaving bottles).",
        ["1. zu lagern oder außerhalb der ausdrücklich dazu ausgewiesenen Flächen zu zelten",
         "2. in aggressiver oder störender Form zu betteln",
         "Diese Gefahrenabwehrverordnung tritt am 01.05.2026 in Kraft und am 31.12.2046 außer Kraft"],
        in_force_from="2026-05-01",
        ends_on='2046-12-31', ends_needle='Diese Gefahrenabwehrverordnung tritt am 01.05.2026 in Kraft und am 31.12.2046 außer Kraft'),
    _mu("koblenz_gavo", "07111", "RP", "Koblenz",
        "https://www.koblenz.de/downloads/aemter-und-eigenbetriebe/buero-ob/ortsrecht/04-strassen-und-verkehrswesen/04-04-gefahrenabwehrverordnung.pdf?cid=28d",
        "verordnung", "betteln,lagern,alkohol", "Koblenzer Ortsrecht 04-04 Gefahrenabwehrverordnung Straßen und Anlagen vom 17.09.2007, in Kraft 01.10.2007 bis 30.09.2027",
        "Gefahrenabwehrverordnung zur Aufrechterhaltung der öffentlichen Sicherheit und Ordnung auf öffentlichen Straßen und in öffentlichen Anlagen der Stadt Koblenz",
        "2007-09-17", "Koblenz, den 17.09.2007", "original",
        "City-wide hazard-prevention ordinance: bans aggressive, intrusive, pressing or obstructive begging (incl. begging "
        "with or by minors and organised begging), settling down to drink alcohol so that others are disturbed, camping "
        "and setting up camping furniture on public streets, and sleeping in vehicles outside designated sites.",
        ["in aggressiver, aufdringlicher, bedrängender oder behindernder Form zu betteln",
         "sich derart zum Konsum von Alkohol oder anderen berauschenden Mitteln niederzulassen",
         "Auf öffentlichen Straßen ist es verboten zu zelten",
         "tritt am 01.10.2007 in Kraft und mit Ablauf des 30.09.2027 außer Kraft", 'Diese Gefahrenabwehrverordnung tritt am 01.10.2007 in Kraft und mit Ablauf des 30.09.2027 außer Kraft'],
        in_force_from="2007-10-01",
        ends_on='2027-10-01', ends_needle='Diese Gefahrenabwehrverordnung tritt am 01.10.2007 in Kraft und mit Ablauf des 30.09.2027 außer Kraft'),
    _mu("offenbach_strassenordnung", "06413", "HE", "Offenbach am Main",
        "https://www.offenbach.de/medien/bindata/of/stadtrecht-sicherheit-ordnung/3.200-Gefahrenabwehrverordnung.pdf",
        "verordnung", "betteln,lagern", "Offenbacher Stadtrecht 3.200 Gefahrenabwehrverordnung (Offenbacher Straßenordnung), Neufassung beschlossen 15.03.2018",
        "Gefahrenabwehrverordnung über die Aufrechterhaltung der Sicherheit und Ordnung auf und an den Straßen und in den Anlagen der Stadt Offenbach am Main (Offenbacher Straßenordnung)",
        "2018-03-15", "in ihrer Sitzung am 15.03.2018", "original",
        "City-wide street ordinance (§ 21): bans any grossly disruptive behaviour on public streets and in green spaces, "
        "naming as examples aggressive begging, begging while faking a physical ailment, lying around and sleeping rough "
        "(Lagern und Nächtigen) and intoxicated behaviour; valid for at most 30 years.",
        ["jedes grob störende Verhalten untersagt", "a) Aggressives Betteln", "c) Lagern und Nächtigen",
         "gilt längstens 30 Jahre"],
        note="the city's PDF is a 2018 scan with an embedded OCR text layer; the signature date is OCR-garbled, so as_of is "
             "the council resolution date printed in the preamble (in force on the day after publication)"),
    # -- manual archive (Lead, via browser/box, 2026-11-21): the 15 MUNI_MANUAL_WANTED files --
    _mu("flensburg_obdach_geb", "01001", "SH", "Flensburg",
        "https://www.flensburg.de/PDF/Satzung_über_die_Erhebung_von_Benutzungsgebühren_für_die_Unterbringung_Obdachloser_in_der_Stadt_Flensburg.PDF?ObjSvrID=2306&ObjID=4263&ObjLa=1&Ext=PDF",
        "satzung", "obdach_gebuehr", "Flensburger Ortsrecht 500.5 Gebührensatzung Unterbringung Obdachloser vom 02.03.2017 (in Kraft 01.04.2017)",
        "Satzung über die Erhebung von Benutzungsgebühren für die Unterbringung Obdachloser in der Stadt Flensburg",
        "2017-03-02", "Flensburg, den 02.03.2017", "original",
        "Fee statute for the city's shelter for the temporary accommodation of homeless people: a fixed daily rate of "
        "12.00 EUR per person and night (22.00 EUR per night for the family unit), utilities included; the first night "
        "(and a directly following weekend if it starts on a Friday) is free.",
        ["zur vorübergehenden Unterbringung obdachloser Personen", "Diese Satzung tritt am 01.04.2017 in Kraft"],
        fees=[_fee("obdach_gebuehr_eur_person_nacht", 12.00, "EUR/Person/Nacht",
                   "Der Tageskostensatz beträgt pro Person und Übernachtung 12,00 Euro", "§ 2 Abs. 2", 2017),
              _fee("obdach_gebuehr_eur_nacht__familienunterkunft", 22.00, "EUR/Nacht",
                   "Der Tageskostensatz für die Familienunterkunft beträgt pro Nacht 22,00 Euro", "§ 2 Abs. 3", 2017)],
        note="manual archive via browser/box, 2026-11-21 (Lead); flensburg.de robots.txt disallows the document path",
        in_force_from="2017-04-01", local="muni_flensburg_obdach_geb.pdf"),
    _mu("landau_obdach", "07313", "RP", "Landau in der Pfalz",
        "https://www.landau.de/output/download.php?file=%2Fmedia%2Fcustom%2F2644_3102_1.PDF%3F1782899248&fn=Obdachlosensatzung_2026",
        "satzung", "obdach,obdach_gebuehr", "Landauer Stadtrecht 30.20.07.10 Obdachlosensatzung vom 24.06.2026 (in Kraft 01.07.2026)",
        "Satzung der Stadt Landau in der Pfalz über die Benutzung von Unterkünften für Obdachlose, Asylbegehrende und Geflüchtete (Obdachlosensatzung)",
        "2026-06-24", "Landau in der Pfalz, 24.06.2026", "original",
        "Joint use and fee statute for one public facility serving homeless people, asylum seekers and refugees "
        "(replaces the homeless-shelter statute of 29.08.2018). Fees are cost-based: shared shelters per assigned place "
        "and month from the actual allocable costs of each shelter; individually rented flats at cold rent plus costs. "
        "No fixed amount in the statute.",
        ["betreibt Unterkünfte für Obdachlose, Asylbegehrende und Geflüchtete als eine gemeinsame öffentliche Einrichtung",
         "Diese Satzung tritt am 01. Juli 2026 in Kraft"],
        note="manual archive via browser/box, 2026-11-21 (Lead); scope covers homeless people, asylum seekers and refugees in one facility",
        in_force_from="2026-07-01", local="muni_landau_obdach.pdf"),
    _mu("landau_gavo", "07313", "RP", "Landau in der Pfalz",
        "https://www.landau.de/output/download.php?file=%2Fmedia%2Fcustom%2F1815_4432_1.PDF%3F1594306775&fn=03-05_Neufassung_Gefahrenabwehrverordnung",
        "verordnung", "betteln,lagern", "Landauer Stadtrecht 30.20.03.04 Gefahrenabwehrverordnung Straßen und Anlagen vom 05.02.2015, in Kraft 01.03.2015 bis 31.12.2034",
        "Gefahrenabwehrverordnung zur Aufrechterhaltung der öffentlichen Sicherheit und Ordnung auf öffentlichen Straßen und in öffentlichen Anlagen der Stadt Landau in der Pfalz",
        "2015-02-05", "Landau in der Pfalz, 05.02.2015", "original",
        "City-wide hazard-prevention ordinance: bans aggressive begging (persistent accosting, begging by or with children) "
        "and organised begging on public streets and in green spaces, and camping or setting up caravans in green spaces.",
        ["8. aggressiv zu betteln", "9. organisiert zu betteln", "3. zu zelten oder Wohnwagen, Wohnmobile o. ä. aufzustellen",
         "tritt am 01.03.2015 in Kraft und mit Ablauf des 31.12.2034 außer Kraft"],
        note="manual archive via browser/box, 2026-11-21 (Lead); the download is named 'Neufassung' but the text is the GAVO "
             "of 05.02.2015, current per its own validity clause (to 31.12.2034)",
        in_force_from="2015-03-01", local="muni_landau_gavo.pdf",
        ends_on='2035-01-01', ends_needle='tritt am 01.03.2015 in Kraft und mit Ablauf des 31.12.2034 außer Kraft'),
    _mu("neustadt_weinstrasse_gavo", "07316", "RP", "Neustadt an der Weinstraße",
        "https://www.neustadt.eu/output/download.php?fid=2579.60.1.PDF",
        "verordnung", "betteln,alkohol", "Neustadter Gefahrenabwehrverordnung (GAVO) vom 25.06.2018 (Amtsblatt Nr. 29 vom 28.06.2018), in Kraft 01.07.2018 für 20 Jahre",
        "Gefahrenabwehrverordnung zur Aufrechterhaltung der öffentlichen Sicherheit und Ordnung auf öffentlichen Straßen und in öffentlichen Anlagen der Stadt Neustadt an der Weinstraße",
        "2018-06-25", "Neustadt an der Weinstraße, 25. Juni 2018", "original",
        "City-wide hazard-prevention ordinance: bans begging in an aggressive or disruptive form, organised begging and "
        "begging involving minors, and disturbing others under the influence of alcohol (pestering, shouting, leaving "
        "bottles); valid for 20 years from 01.07.2018.",
        ["1. das Betteln in aggressiver oder störender Form sowie organisiertes Betteln",
         "aufgrund von Alkohol oder berauschenden Mitteln durch Anpöbeln",
         "Ihre Geltungsdauer beträgt 20 Jahre ab Inkrafttreten"],
        note="manual archive via browser/box, 2026-11-21 (Lead)",
        in_force_from="2018-07-01", local="muni_neustadt_weinstrasse_gavo.pdf"),
    _mu("ulm_polizeiverordnung", "08421", "BW", "Ulm",
        "https://www.ulm.de/-/media/ulm/zdv/downloads/satzungen/oeffentliche-sicherheit-und-ordnung/101-polizeiverordnung.pdf",
        "verordnung", "betteln,lagern", "Ulmer Ortsrecht 101 Polizeiverordnung öffentliche Sicherheit und Ordnung vom 20.11.2013",
        "Polizeiverordnung der Stadt Ulm zur Aufrechterhaltung der öffentlichen Sicherheit und Ordnung und gegen umweltschädliches Verhalten",
        "2013-11-20", "Ulm, den 20. November 2013", "original",
        "City police ordinance (§ 16): on public streets, pavements and in green spaces bans sleeping rough (das Nächtigen), "
        "begging that seeks physical closeness or is otherwise especially intrusive (and inciting minors to it), and public "
        "drug use; § 17 bans setting up tents and caravans.",
        ["Auf öffentlichen Straßen und Gehwegen sowie in Grün- und Erholungsanlagen ist untersagt: 1. das Nächtigen",
         "das die körperliche Nähe suchende oder sonst besonders aufdringliche Betteln"],
        note="manual archive via browser/box, 2026-11-21 (Lead); the PDF carries a '/2016' page stamp of the city's collection",
        local="muni_ulm_polizeiverordnung.pdf"),
    _mu("remscheid_obdach", "05120", "NW", "Remscheid",
        "https://remscheid.de/politik-verwaltung/ortsrecht/download-pool/0.03_510_Obdachlosenunterkuenfte_Satzung.pdf",
        "satzung", "obdach", "Remscheider Ortsrecht 5.10 Satzung über die Obdachlosenunterkünfte vom 19.12.1974, Änderungen bis Satzung vom 21.02.1990 berücksichtigt",
        "Satzung über die Obdachlosenunterkünfte der Stadt Remscheid",
        "1990-02-21", "zuletzt durch Satzung vom 21.02.1990", "consolidated",
        "Use statute for the city's homeless shelters (assignment, use, eviction); in force since 01.01.1975, consolidated "
        "with all amendments up to the statute of 21.02.1990 (collection supplement 08/96).",
        ["Satzung über die Obdachlosenunterkünfte der Stadt Remscheid vom 19.12.1974", "Diese Satzung tritt am 1. Januar 1975 in Kraft"],
        note="manual archive via browser/box, 2026-11-21 (Lead); remscheid.de answers 403 (Cloudflare) to the project UA",
        in_force_from="1975-01-01", local="muni_remscheid_obdach.pdf"),
    _mu("remscheid_obdach_geb", "05120", "NW", "Remscheid",
        "https://remscheid.de/politik-verwaltung/ortsrecht/download-pool/0.03_511_Obdachlosenunterkuenfte_Gebuehrensatzung.pdf",
        "satzung", "obdach_gebuehr", "Remscheider Ortsrecht 5.11 Gebührensatzung für die Obdachlosenunterkünfte vom 29.09.2014 (in Kraft 01.10.2014)",
        "Gebührensatzung für die Obdachlosenunterkünfte der Stadt Remscheid",
        "2014-09-29", "Remscheid, den 29.09.2014", "original",
        "Monthly fees per person: 364.00 EUR in one shelter and 115.00 EUR in the municipal hostel "
        "(utilities and furniture included); city-provided flats 6.00 EUR per m² and month (unfurnished, "
        "without electricity and decentral heating).",
        ["Gebührensatzung für die Obdachlosenunterkünfte der Stadt Remscheid vom 29.09.2014"],
        fees=[_fee("obdach_gebuehr_eur_person_monat__unterkunft_2_1_1", 364.00, "EUR/Person/Monat",
                   "monatlich 364,00 € pro Person", "Nr. 2.1.1", 2014),
              _fee("obdach_gebuehr_eur_person_monat__wohnheim_2_1_2", 115.00, "EUR/Person/Monat",
                   "monatlich 115,00 € pro Person", "Nr. 2.1.2", 2014),
              _fee("obdach_gebuehr_eur_m2_monat__wohnung", 6.00, "EUR/m²/Monat",
                   "Gebühr in Höhe von monatlich 6,00 € je Quadratmeter Wohnfläche", "Nr. 2.2", 2014)],
        note="manual archive via browser/box, 2026-11-21 (Lead); remscheid.de answers 403 (Cloudflare) to the project UA",
        in_force_from="2014-10-01", local="muni_remscheid_obdach_geb.pdf"),
    _mu("frankfurt_unterbringungsgeb", "06412", "HE", "Frankfurt am Main",
        "https://frankfurt.de/-/media/frankfurtde/service-und-rathaus/verwaltung/aemter-und-institutionen/rechtsamt/pdf/satzungen/unterbringungsgebuehrensatzung.pdf",
        "satzung", "obdach_gebuehr", "Frankfurter Unterbringungsgebührensatzung (LAufnG sowie obdachlose und wohnungslose Personen), beschlossen 25.06.2026 (§ 239), rückwirkend in Kraft 12.11.2019",
        "Satzung über die Erhebung von Gebühren für die Unterbringung von Personen im Sinne des Hessischen Landesaufnahmegesetzes sowie sonstigen obdachlosen und wohnungslosen Personen (Unterbringungsgebührensatzung)",
        "2026-06-25", "in ihrer Sitzung am 25.06.2026", "original",
        "Fee statute for accommodating refugees under the LAufnG and other homeless people. Monthly fee per household: "
        "temporarily used housing 635 EUR for one person up to 1,655 EUR for five (+176 EUR per further member); other "
        "accommodation 810 EUR for one person. Retroactively in force from 12.11.2019 (§ 3 Abs. 2 KAG); the old schedule "
        "applied until 31.12.2025.",
        ["sowie sonstigen obdachlosen und wohnungslosen Personen (Unterbringungsgebührensatzung)",
         "Die Satzung tritt nach § 3 Abs. 2 KAG am 12.11.2019 in Kraft"],
        fees=[_fee("obdach_gebuehr_eur_haushalt_monat__zwischengenutzt_1_person", 635.00, "EUR/Haushalt/Monat",
                   "Ein-Personen-Haushalt 635,00 €", "Anlage Gebührenverzeichnis Nr. 1", 2026),
              _fee("obdach_gebuehr_eur_haushalt_monat__sonstige_1_person", 810.00, "EUR/Haushalt/Monat",
                   "Ein-Personen-Haushalt 810,00 €", "Anlage Gebührenverzeichnis Nr. 2", 2026)],
        note="manual archive via browser/box, 2026-11-21 (Lead); frankfurt.de returns 403 to the project UA; same file as the "
             "institutions_media worker's ffm_unterbringungsgebuehrensatzung.pdf",
        local="muni_frankfurt_lag_hsog_gebuehren_2026.pdf"),
    _mu("gera_unterbringung_geb", "16052", "TH", "Gera",
        "https://cms.gera.de/fileadmin/gera_de/Stadtverwaltung/1000/1040_Stadtrat_Ortsteilraete/Ortsrecht_Soziales/Unterbringungsgebuehrensatzung_15.07.2022.pdf",
        "satzung", "obdach_gebuehr", "Gera Unterbringungsgebührensatzung 71/2022 vom 15.07.2022 (Amtsblatt 28/2022 vom 20.07.2022, in Kraft 01.08.2022)",
        "Benutzungsgebührensatzung für öffentliche Einrichtungen bei der Unterbringung besonderer Bedarfsgruppen in Gera (Unterbringungsgebührensatzung)",
        "2022-07-15", "vom 15. Juli 2022", "original",
        "Fee statute for municipal accommodation of special-needs groups (homeless people and people leaving AsylbLG "
        "benefits). Shared shelter type I incl. emergency sleeping places: 157 EUR per person and month or 5.23 EUR per "
        "day, plus household electricity; individual flats at the contractual rent.",
        ["Obdachlose und von Obdachlosigkeit bedrohte Personen (Ausnahmefälle – Notschlafstelle)"],
        fees=[_fee("obdach_gebuehr_eur_person_tag__gemeinschaftsunterkunft_typ_1", 5.23, "EUR/Person/Tag",
                   "157 5,23 23 0,77", "Anlage Gebührenverzeichnis Nr. 1.1 (row: EUR/month, EUR/day, household electricity EUR/month, EUR/day)", 2022)],
        note="manual archive via browser/box, 2026-11-21 (Lead); robots.txt of cms.gera.de disallows all paths",
        in_force_from="2022-08-01", local="muni_gera_unterbringung_geb.pdf"),
    _mu("gera_alkoholverbot", "16052", "TH", "Gera",
        "https://cms.gera.de/fileadmin/gera_de/Stadtverwaltung/1000/1040_Stadtrat_Ortsteilraete/Ortsrecht_oeffentliche_Sicherheit_und_Ordnung/Verbot_des_Alkoholgenusses_in_der_Heinrichstrasse_25.07.2018.pdf",
        "verordnung", "alkohol", "Gera Ordnungsbehördliche Verordnung (Alkoholverbot) vom 25.07.2017 (Amtsblatt 30/2017 vom 29.07.2017), in Kraft 30.07.2017 bis 31.12.2026",
        "Ordnungsbehördliche Verordnung über das Verbot des Alkoholkonsums in öffentlichen Anlagen und auf bestimmten öffentlichen Verkehrsflächen zur Aufrechterhaltung der öffentlichen Sicherheit und Ordnung im Stadtgebiet Gera",
        "2017-07-25", "Anlage zur Ordnungsbehördlichen Verordnung vom 25. Juli 2017", "original",
        "Despite its general title, the only ban (§ 1) covers the Heinrichstraße central interchange (Zentrale "
        "Umsteigestelle): drinking alcohol in public is not allowed there, except on licensed outdoor seating and from "
        "31 Dec 12:00 to 1 Jan 12:00; fine up to 5,000 EUR. Valid until 31.12.2026.",
        ["In der Heinrichstraße, Zentrale Umsteigestelle, ist es nicht gestattet, Alkohol in der Öffentlichkeit zu konsumieren",
         "Die Verordnung tritt am 30. Juli 2017 in Kraft. Sie gilt bis zum 31. Dezember 2026"],
        note="manual archive via browser/box, 2026-11-21 (Lead); robots.txt of cms.gera.de disallows all paths; the "
             "file name says 25.07.2018, the text and the city's register table say 25.07.2017; lapses 31.12.2026",
        in_force_from="2017-07-30", local="muni_gera_alkoholverbot_heinrichstrasse.pdf",
        ends_on='2027-01-01', ends_needle='Die Verordnung tritt am 30. Juli 2017 in Kraft. Sie gilt bis zum 31. Dezember 2026'),
    _mu("gera_stadtordnung", "16052", "TH", "Gera",
        "https://cms.gera.de/fileadmin/gera_de/Stadtverwaltung/1000/1040_Stadtrat_Ortsteilraete/Ortsrecht_oeffentliche_Sicherheit_und_Ordnung/Stadtordnung.pdf",
        "verordnung", "betteln", "Gera Stadtordnung, Neufassung vom 13.12.2018 (Amtsblatt 50/2018 vom 19.12.2018), in Kraft 01.01.2019",
        "Ordnungsbehördliche Verordnung zur Aufrechterhaltung der öffentlichen Sicherheit und Ordnung in der Stadt Gera (Stadtordnung)",
        "2018-12-13", "13.12.2018 50/2018 vom 19.12.2018 01.01.2019 Neufassung", "original",
        "City-wide public-order ordinance (§ 4): on streets and in public spaces bans any behaviour that unreasonably "
        "impairs others' use, in particular aggressive begging (accosting and following people, narrowing entrances). "
        "No rule on lying around or on alcohol.",
        ["Auf Straßen und in öffentlichen Anlagen ist jedes Verhalten untersagt",
         "das aggressive Betteln, wobei aggressives Betteln insbesondere das Ansprechen"],
        note="manual archive via browser/box, 2026-11-21 (Lead); robots.txt of cms.gera.de disallows all paths; the "
             "city's copy elides the text of § 11 (Inkrafttreten und Geltungsdauer), so the end date is not stated; in "
             "force from 01.01.2019 per the city's register table",
        in_force_from="2019-01-01", local="muni_gera_stadtordnung.pdf"),
    _mu("erlangen_verfuegungswohnungen", "09562", "BY", "Erlangen",
        "https://erlangen.de/uwao-api/faila/files/bypath/Dokumente/Stadtrecht/240.00_verfuegungswohnungssatzung.pdf?q=normal&s=list&tn=1",
        "satzung", "obdach", "Erlanger Stadtrecht 240.00 Satzung für die städtischen Verfügungswohnungen vom 29.04.2021 (Die amtlichen Seiten Nr. 10 vom 20.05.2021)",
        "Satzung für die städtischen Verfügungswohnungen",
        "2021-04-29", "Verfügungswohnungen vom 29.04.2021", "original",
        "Use statute for municipal emergency flats (Verfügungswohnungen) for the temporary accommodation of families and "
        "individuals who are homeless or directly threatened with homelessness; in force 21.05.2021.",
        ["die obdachlos oder unmittelbar von Obdachlosigkeit bedroht"],
        note="manual archive via browser/box, 2026-11-21 (Lead); erlangen.de refuses automated access",
        in_force_from="2021-05-21", local="muni_erlangen_verfuegungswohnungen.pdf"),
    _mu("erlangen_verfuegungswohnungen_geb", "09562", "BY", "Erlangen",
        "https://erlangen.de/uwao-api/faila/files/bypath/Dokumente/Stadtrecht/240_10_verfuegungswohnung_gebuheren_2025.pdf?q=normal&s=list&tn=1",
        "satzung", "obdach_gebuehr", "Erlanger Stadtrecht 240.10 Gebührensatzung Verfügungswohnungen vom 29.04.2021 i.d.F. vom 22.05.2025 (in Kraft 01.10.2025)",
        "Gebührensatzung zur Satzung für die städtischen Verfügungswohnungen",
        "2025-05-22", "i. d. F. vom 22.05.2025", "consolidated",
        "Monthly base fee per m² by category: A 10.90, B 10.20, C 9.90, D 9.50 EUR (plus 1.00–1.15 EUR heating); multi-bed "
        "rooms (category E) 3.00 EUR per person and night; emergency placement in a guesthouse 30.00 EUR per person and "
        "night; electricity flat rate 30.00 EUR per person and month.",
        ["Gebührensatzung zur Satzung für die städtischen Verfügungswohnungen vom 29.04.2021 i. d. F. vom 22.05.2025"],
        fees=[_fee("obdach_gebuehr_eur_m2_monat__kategorie_a", 10.90, "EUR/m²/Monat", "(Kategorie A) Grundgebühr € 10,90", "§ 3 Abs. 2 Nr. 1", 2025),
              _fee("obdach_gebuehr_eur_m2_monat__kategorie_d", 9.50, "EUR/m²/Monat", "(Kategorie D) Grundgebühr: € 9,50", "§ 3 Abs. 2 Nr. 4", 2025),
              _fee("obdach_gebuehr_eur_person_nacht__kategorie_e", 3.00, "EUR/Person/Nacht", "(Kategorie E) Grundgebühr € 3,00", "§ 3 Abs. 2 Nr. 5", 2025),
              _fee("obdach_notuebernachtung_eur_person_nacht__beherbergungsbetrieb", 30.00, "EUR/Person/Nacht",
                   "Gesamtgebühr von € 30,00 pro Person und Nacht", "§ 3 Abs. 4", 2025)],
        note="manual archive via browser/box, 2026-11-21 (Lead); erlangen.de refuses automated access",
        in_force_from="2025-10-01", local="muni_erlangen_verfuegungswohnungen_geb_2025.pdf"),
    _mu("ingolstadt_sns", "09161", "BY", "Ingolstadt",
        "https://www.ingolstadt.de/output/download.php?fid=465.1195.1.PDF",
        "satzung", "betteln,lagern,alkohol,sondernutzung", "Ingolstädter Ortsrecht 900 Sondernutzungssatzung vom 10.03.1983, zuletzt geändert 13.01.2025",
        "Satzung über die Erlaubnisse und Gebühren für Sondernutzungen an öffentlichen Verkehrsflächen in der Stadt Ingolstadt - Sondernutzungssatzung (SNS)",
        "2025-01-13", "zuletzt geändert durch Satzung vom 13. Januar 2025", "consolidated",
        "Street special-use statute (§ 2a): no special-use permit is granted for sleeping and lying around (Nächtigen und "
        "Lagern), active/aggressive begging, or settling down outside licensed outdoor seating to drink alcohol.",
        ["a) für das Nächtigen und Lagern b) für aktives Betteln",
         "zum Zwecke des Alkoholgenusses"],
        note="manual archive via browser/box, 2026-11-21 (Lead); ingolstadt.de refuses automated access",
        local="muni_ingolstadt_sns.pdf"),
    _mu("ingolstadt_gruenanlagen", "09161", "BY", "Ingolstadt",
        "https://www.ingolstadt.de/output/download.php?fid=465.1139.1.PDF",
        "satzung", "betteln,lagern,alkohol", "Ingolstädter Ortsrecht 410 Grünanlagensatzung vom 04.09.2024 (AM Nr. 37 vom 18.09.2024)",
        "Satzung über die Benutzung der Städtischen Grünanlagen (Grünanlagensatzung)",
        "2024-09-04", "Vom 4. September 2024", "original",
        "Green-space statute: in municipal parks bans begging in any form, sleeping rough and setting up tents, storing "
        "objects, and settling down outside beer gardens or barbecue sites to drink alcohol.",
        ["10.das Betteln in jeglicher Form", "das Aufstellen von Zelten und Wohnwagen sowie das Nächtigen",
         "das Niederlassen oder das Verweilen außerhalb von Freischankflächen oder Einrichtungen wie Grillstellen zum Zwecke des Alkoholgenusses"],
        note="manual archive via browser/box, 2026-11-21 (Lead); ingolstadt.de refuses automated access; the PDF's last "
             "page is a scanned plan with a garbled text layer",
        local="muni_ingolstadt_gruenanlagen.pdf"),
    _mu("moenchengladbach_strassen_anlagen_vo", "05116", "NW", "Mönchengladbach",
        "https://www.moenchengladbach.de/fileadmin/news_import/Ortsrecht/30-ff/32.1_-_Geltungsdauer_bis_Dezember_2035.pdf",
        "verordnung", "betteln,lagern,alkohol", "Mönchengladbacher Straßen- und Anlagenverordnung vom 17.12.2015 (Abl. MG S. 269)",
        "Ordnungsbehördliche Verordnung über die Aufrechterhaltung der öffentlichen Sicherheit und Ordnung auf den Straßen und in den Anlagen im Stadtgebiet Mönchengladbach (Straßen- und Anlagenverordnung)",
        "2015-12-17", "vom 17. Dezember 2015", "original",
        "City-wide street ordinance: on streets and in green spaces bans staying overnight, disturbing others through "
        "intrusiveness, aggressive begging or drinking alcohol (with bawling, pestering, leaving bottles), and lying around "
        "in groups at bus stops so they cannot be used.",
        ["Auf Straßen und in Anlagen ist es insbesondere verboten, 1. zu übernachten",
         "aggressives Betteln (z.B. unmittelbares Einwirken auf Passanten",
         "in Personengruppen zu lagern"],
        note="manual archive via browser/box, 2026-11-21 (Lead); the city's file name states validity until December 2035",
        local="muni_moenchengladbach_strassen_anlagen_vo.pdf"),
    # -- kreisangehörige cities (a), gem explicit --
    _mu("dueren_uebergangsheime_geb", "05358", "NW", "Düren",
        "https://www.dueren.de/assets/userfiles/pdfbereich_verwaltunundpolitik/satzungen_ordnungen/s5/S5-02_%C3%9Cbergangsheime_ab_01.07.2024.pdf",
        "satzung", "obdach,obdach_gebuehr", "Dürener Ortsrecht S5-02 Benutzungs- und Gebührensatzung Übergangsheime und Obdachlosenunterkünfte vom 02.05.2024 (in Kraft 01.07.2024)",
        "Benutzungs- und Gebührensatzung für städtische Übergangsheime für Spätaussiedler, Zuwanderer, ausländische Flüchtlinge und Schutzberechtigte und Obdachlosenunterkünfte der Stadt Düren",
        "2024-05-02", "Obdachlosenunterkünfte der Stadt Düren vom 02.05.2024", "original",
        "Use and fee statute for refugee transitional homes and homeless shelters. Base fee per m² and month in homeless "
        "shelters: category 1 15.05 EUR, category 2 11.30 EUR, category 3 9.92 EUR, plus heating 1.11 EUR/m², water 10 EUR "
        "and electricity 29.09 EUR per person and month.",
        ["Obdachlosenunterkünfte der Stadt Düren vom 02.05.2024"],
        fees=[_fee("obdach_gebuehr_eur_m2_monat__kategorie_1", 15.05, "EUR/m²/Monat",
                   "Obdachlosenunterkünften der 1. Kategorie 15,05 €", "§ 5 Abs. 2 b", 2024),
              _fee("obdach_gebuehr_eur_m2_monat__kategorie_3", 9.92, "EUR/m²/Monat",
                   "3. Kategorie 9,92 €", "§ 5 Abs. 2 b", 2024)],
        in_force_from="2024-07-01", gem="05358008"),
    _mu("troisdorf_unterkuenfte", "05382", "NW", "Troisdorf",
        "https://www.troisdorf.de/de/rathaus-service/stadtrat-und-ausschuesse/ortsrecht/5-3.pdf",
        "satzung", "obdach,obdach_gebuehr", "Troisdorfer Ortsrecht 5-3 Satzung Unterkünfte für obdachlose Personen, Aussiedler und Flüchtlinge vom 15.06.2023 i.d.F. der 2. Änderung vom 25.02.2026 (in Kraft 01.03.2026)",
        "Satzung der Stadt Troisdorf über die Unterhaltung, Benutzung und Erhebung von Gebühren der Unterkünfte für obdachlose Personen, Aussiedler und Flüchtlinge",
        "2026-02-25", "2. Änderung vom 25. Februar 2026", "consolidated",
        "Use and fee statute for shelters for homeless people (OBG), resettlers, refugees and asylum seekers: base fee "
        "17.30 EUR per m² and month plus running costs 3.46, heating 1.78 and electricity 1.57 EUR per m² and month.",
        ["Obdachlosen nach dem Ordnungsbehördengesetz als öffentliche Einrichtungen"],
        fees=[_fee("obdach_gebuehr_eur_m2_monat__grundgebuehr", 17.30, "EUR/m²/Monat",
                   "Grundgebühr: 17,30 € pro m²/Monat", "Anlage", 2026)],
        in_force_from="2026-03-01", gem="05382068"),
    _mu("zwickau_obdach", "14524", "SN", "Zwickau",
        "https://www.zwickau.de/media/downloads/image/01_buerger/ortsrecht/5_6_Obdachlosensatzung_idF_1_Aend_v_09_12_19.pdf",
        "satzung", "obdach,obdach_gebuehr", "Zwickauer Ortsrecht 5.6.1 Obdachlosensatzung vom 09.11.2009 i.d.F. der 1. Änderungssatzung vom 09.12.2019",
        "Satzung über die Unterhaltung und Benutzung von Obdachlosenunterkünften sowie die Gebührenerhebung der Stadt Zwickau",
        "2019-12-09", "in der Fassung der 1. Änderungssatzung vom 09.12.2019", "consolidated",
        "Use and fee statute for the city's homeless shelters (repealed with effect from 01.01.2027): 8.00 EUR per night in the shared shelter and "
        "6.80 EUR per m² and month in the family accommodation.",
        ["Satzung über die Unterhaltung und Benutzung von Obdachlosenunterkünften sowie die Gebührenerhebung der Stadt Zwickau vom 09.11.2009"],
        fees=[_fee("obdach_gebuehr_eur_nacht__gemeinschaftsunterkunft", 8.00, "EUR/Nacht",
                   "Übernachtung und Nutzung 8,00 €", "Gebührenverzeichnis zu § 7 Abs. 1 Nr. 1", 2019),
              _fee("obdach_gebuehr_eur_m2_monat__wohnunterkunft", 6.80, "EUR/m²/Monat",
                   "je m²/monatlich 6,80 €", "Gebührenverzeichnis zu § 7 Abs. 1 Nr. 2", 2019)],
        note="repealed with effect from 01.01.2027 by the Aufhebungssatzung of 04.11.2026 (council decision 29.10.2026; "
             "archived as the extra source) when the two shelters pass to a charity operator; the fees apply to "
             "31.12.2026 only",
        extra=[("https://www.zwickau.de/media/downloads/image/01_buerger/ortsrecht/5_6_Aufhebung-Obdachlosensatzung_11_11_26.pdf",
                ["in der Fassung der 1. Änderungssatzung vom 09.12.2019 wird aufgehoben",
                 "Diese Satzung tritt mit Wirkung zum 01.01.2027 in Kraft"])],
        gem="14524330"),
    _mu("luenen_unterbringung", "05978", "NW", "Lünen",
        "https://www.luenen.de/de-wAssets/docs/PDFs/ortsrecht/Unterbringung_Gefluechtete_und_Wohnungslose_2017.pdf",
        "satzung", "obdach,obdach_gebuehr", "Lüner Ortsrecht Benutzungs- und Gebührensatzung für Geflüchtete und Wohnungslose vom 15.12.2017 (in Kraft 01.01.2018)",
        "Benutzungs- und Gebührensatzung für Geflüchtete und Wohnungslose der Stadt Lünen",
        "2017-12-15", "Wohnungslose der Stadt Lünen vom 15.12.2017", "original",
        "Use and fee statute for shelters for refugees and homeless people under § 14 OBG: 18.13 EUR per m² of usable "
        "floor space and month including running costs (plus a share of common areas).",
        ["von Obdachlosen, die gem. § 14 des Ordnungsbehördengesetzes (OBG)", "Diese Satzung tritt am 01.01.2018 in Kraft"],
        fees=[_fee("obdach_gebuehr_eur_m2_monat", 18.13, "EUR/m²/Monat",
                   "je qm Nutzfläche und Kalendermonat 18,13 Euro", "§ 4 Abs. 2", 2017)],
        in_force_from="2018-01-01", gem="05978024"),
    _mu("luenen_obvo", "05978", "NW", "Lünen",
        "https://www.luenen.de/de-wAssets/docs/PDFs/ortsrecht/Ordnungsbehoerdliche_Verordnung_der_Stadt_Luenen_2021.pdf",
        "verordnung", "betteln,lagern,alkohol", "Lüner Ordnungsbehördliche Verordnung vom 08.05.2018 in der ab 16.07.2021 gültigen Fassung",
        "Ordnungsbehördliche Verordnung der Stadt Lünen über die Aufrechterhaltung der öffentlichen Sicherheit und Ordnung in der Stadt Lünen",
        "2021-07-16", "in der ab dem 16.07.2021 gültigen Fassung", "consolidated",
        "City-wide public-order ordinance: bans aggressive begging (e.g. with a dog, blocking the way, accosting or "
        "touching) and begging by or with children, lying around, camping or sleeping on streets and in green spaces, and "
        "recurring gatherings that harass passers-by through excessive alcohol use; alcohol is banned on playgrounds.",
        ["aggressiv zu betteln", "Belästigungen von Passanten bei übermäßigem Genuss von Alkohol", "e) auf Verkehrsflächen oder in Anlagen zu lagern, zu campieren oder zu nächtigen"],
        gem="05978024"),
    # ---- batch 10 (2026-11-21): (a) shelter statutes of kreisangehörige cities > ~80k ----
    _mu("esslingen_obdach", "08116", "BW", "Esslingen am Neckar",
        "https://www.esslingen.de/site/Esslingen_Layout_2022/get/documents_E-1496772018/es/Datenquelle-Esslingen-2022/Ortsrecht/1_Sicherheit_Ordnung/Ortsrecht%20ES%201-7.pdf",
        "satzung", "obdach,obdach_gebuehr", "Esslinger Ortsrecht 1/7 Obdachlosenunterkunftssatzung, Neufassung vom 22.02.2016",
        "Satzung über die Benutzung der Obdachlosenunterkünfte der Stadt Esslingen am Neckar",
        "2016-04-01", "Neufassung vom 22.02.2016 Bekannt gemacht in der Esslinger Zeitung am 01.04.2016", "original",
        "Use and fee statute for homeless shelters: monthly fee per m² for flats and per place in hostels (use "
        "compensation plus running costs). The statute indexes these amounts yearly to the Baden-Württemberg "
        "consumer price index, so the printed figures are the 2016 base values.",
        ["Die Benutzungsgebühren werden auf der Grundlage der Preisentwicklung nach dem Verbraucherindex für Baden-Württemberg jedes Jahr fortgeschrieben"],
        fees=[_fee("obdach_gebuehr_eur_m2_monat", 14.70, "EUR/m2/Monat",
                   "Benutzungsgebühr 14,70 287,23", "§ 5 Abs. 3 (Wohnungen)", 2016),
              _fee("obdach_gebuehr_eur_platz_monat", 287.23, "EUR/Platz/Monat",
                   "Benutzungsgebühr 14,70 287,23", "§ 5 Abs. 3 (Wohnheime)", 2016)],
        note="2016 base values; the current indexed amounts are not printed in the statute",
        gem="08116019"),
    _mu("ludwigsburg_obdach", "08118", "BW", "Ludwigsburg",
        "https://www.ludwigsburg.de/site/Ludwigsburg-Internet-2020/get/params_E1974670171/18107606/Satzung%20%C3%BCber%20die%20Benutzung%20von%20Obdachlosenunterk%C3%BCnften%20der%20Stadt%20Ludwigsburg%20.pdf",
        "satzung", "obdach,obdach_gebuehr", "Ludwigsburger Stadtrecht: Obdachlosenunterkunftssatzung vom 29.06.2022",
        "Satzung über die Benutzung von Obdachlosenunterkünften der Stadt Ludwigsburg in der Teinacher Straße und Riedle",
        "2022-09-01", "Die Benutzungsgebühr beträgt ab 01.09.2022", "original",
        "Use and fee statute for the two homeless shelters (Riedle, Teinacher Straße): monthly fee per person "
        "including heating and utilities; self-payers without benefit entitlement can apply for a 12-month reduction.",
        ["in seiner Sitzung vom 29.06.2022 folgende Satzung beschlossen"],
        fees=[_fee("obdach_gebuehr_eur_person_monat__riedle", 461.00, "EUR/Person/Monat",
                   "Gebühr pro Person und Monat (warm) 461,00 € 591,00 €", "§ 15 Abs. 2 (Unterkunft Riedle)", 2022),
              _fee("obdach_gebuehr_eur_person_monat__teinacher_strasse", 591.00, "EUR/Person/Monat",
                   "Gebühr pro Person und Monat (warm) 461,00 € 591,00 €", "§ 15 Abs. 2 (Unterkunft Teinacher Straße)", 2022)],
        gem="08118048"),
    _mu("tuebingen_obdach", "08416", "BW", "Tübingen",
        "https://www.tuebingen.de/verwaltung/uploads/satzung_unterkuenfte_wohnungslose_gefluechtete.pdf",
        "satzung", "obdach,obdach_gebuehr", "Tübinger Ortsrecht: Unterkunftsbenutzungs- und Gebührensatzung vom 22.03.2018 i.d.F. vom 24.07.2025",
        "Satzung über die Benutzung der Unterkünfte der Universitätsstadt Tübingen für Wohnungslose und Geflüchtete sowie die Gebühren für deren Benutzung (Unterkunftsbenutzungs- und Gebührensatzung)",
        "2025-07-24", "vom 22. März 2018 in der Fassung vom 24. Juli 2025", "consolidated",
        "Use and fee statute for accommodation of homeless people and refugees: monthly use fee and a separate "
        "running-cost flat rate per m², by building category (A homeless, B refugees, C containers).",
        ["Diese Satzung tritt am 1. Januar 2018 in Kraft"],
        fees=[_fee("obdach_gebuehr_eur_m2_monat", 14.93, "EUR/m2/Monat",
                   "Die Benutzungsgebühr beträgt für Wohnungen und Räume für Wohnungslose (Gebäudekategorie A) 14,93 €/m²", "§ 14 (Kategorie A)", 2025),
              _fee("obdach_nebenkosten_eur_m2_monat", 7.97, "EUR/m2/Monat",
                   "Die Nebenkostenpauschale beträgt für Wohnungen und Räume für Wohnungslose (Gebäudekategorie A) 7,97 €/m²", "§ 14 (Kategorie A)", 2025)],
        gem="08416041"),
    _mu("konstanz_obdach", "08335", "BW", "Konstanz",
        "https://www.konstanz.de/site/Konstanz/get/documents_E-684171181/konstanz/Dateien/Service/Ortsrecht/III%20Recht,%20Sicherheit%20und%20Ordnung/III_24%20Satzung%20%c3%bcber%20die%20Benutzung%20von%20Obdachlosen-%20und%20Fl%c3%bcchtlingsunterk%c3%bcnften%20der%20Stadt%20Konstanz%20ab%2001.01.2025.pdf",
        "satzung", "obdach,obdach_gebuehr", "Konstanzer Ortsrecht III/24 Unterkunftssatzung, Neufassung ab 01.01.2025",
        "Satzung über die Benutzung von Wohnungslosen- und Flüchtlingsunterkünften der Stadt Konstanz",
        "2024-09-25", "Die Neufassung dieser Satzung tritt am 01.01.2025 in Kraft. Konstanz, den 25.09.2024", "original",
        "Use and fee statute for homeless and refugee accommodation: monthly fee per person in the public-order "
        "shared shelters Haidelmoosweg 15 and Hafenstraße 25 (adults, minors; family cap 2,010 EUR), with a reduced "
        "rate under § 16a.",
        ["Erwachsene 405 € • Minderjährige: 220 € Für Familien mit minderjährigen Kindern beträgt die Maximalgebühr 2.010 €"],
        fees=[_fee("obdach_gebuehr_eur_person_monat__erwachsene", 405, "EUR/Person/Monat",
                   "Erwachsene 405 €", "§ 16 Abs. 2 a (Haidelmoosweg 15, Hafenstraße 25)", 2025),
              _fee("obdach_gebuehr_eur_person_monat__minderjaehrige", 220, "EUR/Person/Monat",
                   "Minderjährige: 220 €", "§ 16 Abs. 2 a (Haidelmoosweg 15, Hafenstraße 25)", 2025)],
        in_force_from="2025-01-01", gem="08335043"),
    _mu("goettingen_obdach_geb", "03159", "NI", "Göttingen",
        "https://www.goettingen.de/downloads/datei/ZDFjNDM4MTA5MjhhNTBhN01WQ0F5SEpnUTF3T2NMaVA1aE52UkFkTUN0WGdrYzd6cUtlR3BUeVhoRlpMbXFSQjVLTTU3VFBiaS9zODhqQVZXcE1KK1diNUZBcWJUbWsxTi81cmlRU2hiZXpHOHFYVXc1SGhPUVhWdlRSZzVzSDdCdTYwMmNnSjBTVUZRN3FlYmFFenNNa3lGSGxydE41K0htdVZnY1VibkFpOGRGdUVxOG1nRWNBR2ZwcmFxdXE5WXdzY3ROUWdFVHlXTUVCUDVRSjN5RmtXaFMzWTY1QTVKOUR4alMvYWFvaUpOb0ExTFZ3YS9SM21hSnM9",
        "satzung", "obdach_gebuehr", "Göttinger Stadtrecht 4-8-2 Gebührensatzung Unterkünfte für wohnungslose Menschen vom 18.11.2019",
        "Satzung über die Erhebung von Gebühren für die Nutzung der Unterkünfte für wohnungslose Menschen der Stadt Göttingen",
        "2019-11-26", "Göttingen, den 18.11.2019 Stadt Göttingen i.V. gezeichnet Schmetz *) Veröffentlicht im Amtsblatt Nr. 25 vom 26.11.2019", "original",
        "Fee statute for the city's accommodation for homeless people: monthly fee per person including running "
        "costs in shared shelters; per-m² fees for city flats listed by address.",
        ["Satzung über die Erhebung von Gebühren für die Nutzung der Unterkünfte für wohnungslose Menschen der Stadt Göttingen"],
        fees=[_fee("obdach_gebuehr_eur_person_monat", 260.00, "EUR/Person/Monat",
                   "Die Nutzungsgebühr beträgt einschließlich der Nebenkosten pro Person und Monat für Gemeinschaftsunterkünfte: 260,00 €", "§ 3 (Gemeinschaftsunterkünfte)", 2019)],
        gem="03159016"),
    # ---- batch 9 (2026-11-21): further (b) ordinances ----
    _mu("wuerzburg_sicherheitssatzung", "09663", "BY", "Würzburg",
        "https://www.wuerzburg.de/media/www.wuerzburg.de/org/med_9025/429723_konsolidierte_lesefassung_sicherheitssatzung_stand_august_2022.pdf",
        "satzung", "betteln,lagern,alkohol", "Würzburger Stadtrecht 3.2.8 Sicherheitssatzung vom 06.04.2006 i.d.F. vom 14.07.2022",
        "Satzung über die Aufrechterhaltung der öffentlichen Sicherheit und Ordnung in der Stadt Würzburg (Sicherheitssatzung)",
        "2022-07-26", "Änderung vom 14. Juli 2022 (MP und VBl Nr. 170 vom 26.07.2022)", "consolidated",
        "On streets, paths, squares and in parks bans overnighting or camping outside designated areas, begging in "
        "any form, and staying to drink alcohol outside licensed outdoor areas where this can impair public safety "
        "(§ 4 Abs. 1 Nr. 2, 3, 7); bans 'Lagern' on public streets, paths and squares (§ 4 Abs. 7); alcohol and "
        "carrying alcohol banned on Wagnerplatz (§ 4 Abs. 6).",
        ["2. zu nächtigen oder zu zelten, ausgenommen auf den hierfür ausdrücklich vorgesehenen Flächen, 3. zu betteln in jeglicher Form",
         "sich zum Alkoholgenuss außerhalb von Freischankflächen aufzuhalten oder zu verweilen, soweit dadurch die öffentliche Sicherheit und Ordnung beeinträchtigt werden kann",
         "(7) Es ist untersagt, auf öffentlichen Straßen, Wegen und Plätzen zu lagern."],
        note="consolidated reading copy (konsolidierte Lesefassung, Stand August 2022) published by the city; www.wuerzburg.de "
             "drops the TLS handshake from the box but serves the deck normally"),
    _mu("regensburg_gruenanls", "09362", "BY", "Regensburg",
        "https://www.regensburg.de/stadtrecht/233940/satzung-fuer-die-benutzung-der-oeffentlichen-gruenanlagen-und-spielanlagen-der-stadt-regensburg-gruenanlagensatzung-gruenanls-vom-25-juli-2019.html",
        "satzung", "betteln,lagern,alkohol", "Regensburger Stadtrecht 19.5.1 Grünanlagensatzung vom 25.07.2019 i.d.F. vom 10.02.2026",
        "Satzung für die Benutzung der öffentlichen Grünanlagen und Spielanlagen der Stadt Regensburg (Grünanlagensatzung - GrünanlS)",
        "2026-03-30", "geändert durch Satzung vom 10. Februar 2026, AMBl. Nr. 14 vom 30. März 2026", "consolidated",
        "In public parks and playgrounds bans begging in any form, setting up tents or caravans, overnighting, and "
        "alcohol or drug use that harasses third parties more than objectively unavoidable; no alcohol on playgrounds.",
        ["zu betteln in jeglicher Form.",
         "Zelte und Wohnwagen aufzustellen. zu nächtigen.",
         "der Alkoholgenuss oder Genuss anderer berauschender Mittel, soweit Dritte dadurch mehr als objektiv unvermeidbar belästigt werden"],
        note="HTML 'Stadtrecht online' on regensburg.de (not the official promulgation; binding is the Amtsblatt). Parks "
             "only; Regensburg has no street begging ordinance in its Stadtrecht"),
    _mu("fuerth_sondernutzung", "09563", "BY", "Fürth",
        "https://www.fuerth.de/fileadmin/redaktion/01-Rathaus/Ortsrecht/21_1_sondernutzungssatzung_der_stadt_fuerth.pdf",
        "satzung", "sondernutzung,betteln,lagern,alkohol", "Fürther Ortsrecht 21-1 Sondernutzungssatzung vom 04.01.1979 i.d.F. vom 06.10.2023",
        "Satzung für Sondernutzung an öffentlichen Straßen in der Baulast der Stadt Fürth (Sondernutzungssatzung)",
        "2023-10-25", "6. Oktober 2023 (INFÜ Nr. 19 vom 25. Oktober 2023)", "consolidated",
        "Street special-use statute: settling down to drink alcohol outside licensed outdoor areas, sitting and lying "
        "on streets or pavements, and begging in any form count as special use (§ 2 Abs. 3), for which no permit is "
        "granted (§ 3 Abs. 2).",
        ["1. das Niederlassen zum Zwecke des Alkoholgenusses",
         "2. das Sitzen und Liegen auf den Straßen oder Gehwegflächen 3. das Betteln in jeglicher Form",
         "(2) Für die in § 2 Abs. 3 aufgeführten Sondernutzungen wird keine Erlaubnis erteilt."]),
    _mu("solingen_strassenordnung", "05122", "NW", "Solingen",
        "https://solingen.de/uploads/33_31_26023f0c72.pdf",
        "verordnung", "betteln,lagern,alkohol", "Solinger Ortsrecht 32/10 Straßenordnung vom 14.02.2019",
        "Ordnungsbehördliche Verordnung zur Aufrechterhaltung der öffentlichen Sicherheit und Ordnung auf den Straßen und in den Anlagen des Gebietes der Klingenstadt Solingen (Straßenordnung)",
        "2019-02-14", "(Straßenordnung) vom 14. Februar 2019", "original",
        "Bans aggressive and intrusive begging (e.g. touching, holding, blocking the way, intrusive addressing); "
        "overnighting, tents and camping on streets and in parks only at released places (§ 11 Abs. 4); any alcohol, "
        "nicotine or drug use on playgrounds and similar areas.",
        ["1. Aggressives und aufdringliches Betteln und / oder aggressive und bedrängende Verkaufspraktiken, z.B. mittels Anfassen, Festhalten, Versperren des Weges",
         "(4) In den Straßen und Anlagen ist das Übernachten, Zelten und Campieren nur an dafür freigegebenen Stellen erlaubt.",
         "ist jeglicher Konsum von Alkohol, Nikotin und Drogen untersagt"]),
    _mu("saarbruecken_polvo", "10041", "SL", "Saarbrücken",
        "https://www.saarbruecken.de/media/download-535a4143ac534",
        "verordnung", "betteln,lagern,alkohol", "Saarbrücker Ortsrecht: Polizeiverordnung vom 11.04.2007 i.d.F. vom 25.05.2015",
        "Polizeiverordnung über die Aufrechterhaltung der Sicherheit und Ordnung auf Straßen und in Anlagen der Landeshauptstadt Saarbrücken",
        "2015-05-25", "in der Fassung vom 25.05.2015", "consolidated",
        "In public parks and on streets bans overnighting and camping outside released areas, 'Lagern' and permanent "
        "lingering while drunk in a way that affects third parties, and organised begging, begging by close bodily "
        "approach, obstructing traffic, feigning need, with children or with circus animals.",
        ["das Lagern und dauerhafte Verweilen im Zustand von Trunkenheit in einer für Dritte beeinträchtigenden Art",
         "bandenmäßiges bzw. organisiertes Betteln, das Betteln durch gezieltes körpernahes Ansprechen von Personen",
         "Betteln unter Zuhilfenahme von Kindern"],
        note="the city's PDF is a scan with an embedded OCR text layer (some OCR errors, e.g. in the title); the needles "
             "are taken from clean passages of that layer. Title as printed (OCR-garbled in the text layer)",
        gem="10041100"),
    _mu("chemnitz_obdach", "14511", "SN", "Chemnitz",
        "https://www.chemnitz.de/fileadmin/chemnitz/media/rathaus/satzungen/50_760.pdf",
        "satzung", "obdach,obdach_gebuehr", "Chemnitzer Ortsrecht 50.760 Unterbringungssatzung",
        "Satzung der Stadt Chemnitz über die vorübergehende Unterbringung von Personen mit besonderen sozialen Schwierigkeiten und über die Gebührenerhebung",
        "2021-07-17", "1. Änderung 02.06.21 02.07.21 16.07.21 17.07.21 Nr. 28/21", "consolidated",
        "Use and fee statute for housing projects, hostels, decentralised housing and the overnight shelter "
        "(Übernachtungsstätte) for homeless people: monthly fee per place, a reduced monthly rate under § 13 Abs. 3, "
        "and a daily fee in the overnight shelter. Version: 1st amendment adopted 02.06.2021, published Amtsblatt "
        "Nr. 28/21 (16.07.2021), in force 17.07.2021 (chronology table in the document).",
        ["Satzung der Stadt Chemnitz über die vorübergehende Unterbringung von Personen mit besonderen sozialen Schwierigkeiten und über die Gebührenerhebung"],
        fees=[_fee("obdach_gebuehr_eur_platz_monat", 390.00, "EUR/Platz/Monat",
                   "Gebühr/Monat/Platz Ermäßigte Gebühr/Monat/Platz nach § 13 Abs. 3 390,00 €", "Anlage Gebührenverzeichnis Nr. 1", 2021),
              _fee("obdach_gebuehr_eur_platz_monat__ermaessigt", 180.00, "EUR/Platz/Monat",
                   "390,00 € 180,00 €", "Anlage Gebührenverzeichnis Nr. 1 (ermäßigt nach § 13 Abs. 3)", 2021),
              _fee("obdach_notuebernachtung_eur_platz_tag", 5.00, "EUR/Platz/Tag",
                   "Gebühr/Tag/Platz 5,00 €", "Anlage Gebührenverzeichnis Nr. 2", 2021)],
        note="manual archive via browser, 2026-11-21 (Lead); www.chemnitz.de refuses the project UA. Text 'Juli 2021'",
        in_force_from="2021-07-17", local="muni_chemnitz_obdach.pdf"),
    _mu("chemnitz_polvo", "14511", "SN", "Chemnitz",
        "https://www.chemnitz.de/fileadmin/chemnitz/media/rathaus/satzungen/32_100_20250117.pdf",
        "verordnung", "betteln", "Chemnitzer Ortsrecht 32.100 Polizeiverordnung vom 11.12.2024 (Amtsblatt Nr. 03/25)",
        "Polizeiverordnung der Stadt Chemnitz zur Aufrechterhaltung der öffentlichen Sicherheit und Ordnung in Chemnitz",
        "2025-01-17", "Verordnung 11.12.24 03.01.25 16.01.25 17.01.25 Nr. 03/25", "original",
        "On public streets, parks and publicly accessible areas bans aggressive, organised or traffic-obstructing "
        "begging (§ 3 Abs. 5) and begging by or accompanied by children under 14 (§ 3 Abs. 5a); bans intrusive or "
        "aggressive behaviour, e.g. after alcohol, that significantly harasses others. Neufassung adopted "
        "11.12.2024, signed 03.01.2025, published Amtsblatt Nr. 03/25 on 16.01.2025, in force 17.01.2025.",
        ["ist es untersagt, aggressiv oder organisiert oder verkehrsbehindernd zu betteln",
         "Das Betteln durch Kinder oder in Begleitung von Kindern ist untersagt",
         "Chemnitz, den 3. Januar 2025"],
        note="manual archive via browser, 2026-11-21 (Lead); www.chemnitz.de refuses the project UA. Document header 'Stand: Dezember 2024'",
        in_force_from="2025-01-17", local="muni_chemnitz_polvo.pdf"),
    _mu("ffm_gefahrenabwehrvo", "06412", "HE", "Frankfurt am Main",
        "https://frankfurt.de/-/media/frankfurtde/service-und-rathaus/verwaltung/aemter-und-institutionen/rechtsamt/pdf/satzungen/gefahrenabwehrverordnung.pdf",
        "verordnung", "betteln,lagern,alkohol", "Frankfurter Gefahrenabwehrverordnung vom 26.06.2014 (Magistrat 08.07.2014), Lesefassung ab 16.07.2025",
        "Gefahrenabwehrverordnung über die Aufrechterhaltung der öffentlichen Sicherheit und Ordnung auf und an den Straßen, Grün- und Spielanlagen, auf Gewässern, im Wald sowie den unterirdischen Anlagen in der Stadt Frankfurt am Main",
        "2025-07-16", "Lesefassung der ab 16.07.2025 geltenden Gefahrenabwehrverordnung", "consolidated",
        "Bans aggressive, intrusive or pressing begging and begging by, with or using minors (§ 7 Abs. 3); 'Lagern' or "
        "permanent lingering that affects others for the purpose of narcotics use (§ 7 Abs. 2); alcohol on playgrounds "
        "and school yards (§ 7 Abs. 1); in underground facilities alcohol and sitting, lying or 'Lagern' on entrances "
        "and stairs (§ 8). Amended by council decisions of 24.02.2022 and 03.07.2025.",
        ["Aggressives, aufdringliches, bedrängendes Betteln, insbesondere in behindernder Form oder durch nachdrückliches oder hartnäckiges Ansprechen von Personen zum Zwecke der Bettelei, sowie das Betteln von, mit oder mittels Minderjährigen ist verboten",
         "Das Lagern oder das dauerhafte Verweilen von Personen im Geltungsbereich dieser Verordnung in einer für Dritte beeinträchtigenden Art zum Zwecke des Konsums von Betäubungsmitteln",
         "das Sitzen, Liegen oder Lagern auf Zu- und Abgängen, vor Türen und auf Treppen",
         "durch Beschluss der Stadtverordnetenversammlung vom 24.02.2022 und 03.07.2025 geändert"],
        note="manual archive via browser, 2026-11-21 (Lead); frankfurt.de returns 403 to the project UA",
        local="ffm_gefahrenabwehrvo.pdf"),
    _mu("kiel_sondernutzung", "01002", "SH", "Kiel",
        "https://www.kiel.de/de/_data/ortsrecht_bekanntmachungen/root/download.php?fid=6a92ae8aa0498fe0b036a5ef99cac2d1&typ=bm",
        "satzung", "sondernutzung,betteln,lagern,alkohol", "Kieler Ortsrecht: Sondernutzungs- und Gebührensatzung vom 28.05.2025",
        "Satzung über Erlaubnisse und Gebühren für Sondernutzungen an öffentlichen Straßen, Wegen und Plätzen in der Landeshauptstadt Kiel",
        "2025-05-28", "Kiel, den 28.05.2025", "original",
        "Street special-use statute: settling down (Niederlassen) that blocks or unreasonably harasses passers-by, in "
        "particular while consuming alcohol or drugs, is not Gemeingebrauch (§ 2 Abs. 1); no special-use permit is "
        "granted for begging, but begging from a self-chosen spot without approaching, obstructing, threatening or "
        "touching passers-by is tolerated (§ 3 Abs. 4).",
        ["Eine Sondernutzungserlaubnis wird nicht erteilt für das Betteln",
         "Der Mitgebrauch anderer wird zum Beispiel durch ein Niederlassen erheblich beeinträchtigt oder ausgeschlossen",
         "Dies gilt insbesondere auch dann, wenn dabei Alkohol oder andere Rauschmittel konsumiert werden"],
        note="a 1st amendment (Drs. 1126/2026) was on the council agenda; not in this text"),
    _mu("braunschweig_sondernutzung", "03101", "NI", "Braunschweig",
        "https://www.braunschweig.de/politik_verwaltung/politik/stadtrecht/6_03_Sondernutzungssatzung_04.09.2018.pdf",
        "satzung", "sondernutzung,betteln,lagern", "Braunschweiger Stadtrecht 6.03 Sondernutzungssatzung vom 19.03.2002 i.d.F. vom 04.09.2018",
        "Satzung über die Sondernutzung an Ortsstraßen und Ortsdurchfahrten in der Stadt Braunschweig (Sondernutzungssatzung)",
        "2018-09-21", "in der Fassung der Achten Änderungssatzung vom 4. September 2018; Amtsblatt Nr. 9 vom 21. September 2018, S. 61", "consolidated",
        "Street special-use statute: 'Lagern' (permanent lingering beyond rest or social interaction, as a rule over "
        "60 minutes, that restricts others) and aggressive, commercial or organised begging need a permit (§ 5 Abs. 1 "
        "j, k), which as a rule is not granted (§ 5a).",
        ["Ein dauerhaftes Verweilen ist gegeben, wenn diese Nutzung über ein Ausruhen oder eine soziale Interaktion hinausgeht",
         "k) das aggressive, das gewerbsmäßige und das organisierte Betteln",
         "c) für das aggressive, das gewerbsmäßige und das organisierte Betteln im Sinne des § 5 Abs. 1 Buchstabe k) dieser Satzung"]),
    _mu("leverkusen_stadtordnung", "05316", "NW", "Leverkusen",
        "https://www.leverkusen.de/service/veroeffentlichungen/satzungen-verordnungen/dez-2/Stadtordnung.pdf",
        "verordnung", "betteln,lagern", "Amtsblatt der Stadt Leverkusen Nr. 47/2023 S. 448: Leverkusener Stadtordnung vom 11.12.2023",
        "Ordnungsbehördliche Verordnung zur Aufrechterhaltung der öffentlichen Sicherheit und Ordnung auf den Straßen und in den Anlagen der Stadt Leverkusen (Leverkusener Stadtordnung)",
        "2023-12-18", "Seite 448 Amtsblatt der Stadt Leverkusen Nr. 47 18. Dezember 2023", "original",
        "Bans aggressive begging, organised begging, begging that obstructs traffic, and begging with or by children "
        "or with animals; bans using parks and pedestrian areas as camp or sleeping places (§ 14).",
        ["Betteln unter Mitwirkung von Kindern oder durch Kinder",
         "und Fußgängerbereiche als Lager- oder Schlafplätze zu verwenden"]),
    _mu("krefeld_obvo", "05114", "NW", "Krefeld",
        "https://service.krefeld.de/system/files/2025-04/3.00%20Ordnungsbeh%C3%B6rdliche%20Verf%C3%BCgung%2020230928_Version.pdf",
        "verordnung", "betteln,lagern,alkohol", "Krefelder Ortsrecht 3.00 Ordnungsbehördliche Verordnung vom 22.09.2023 (Krefelder Amtsblatt Nr. 39 vom 28.09.2023, S. 378), ersetzt die Verordnung vom 26.05.2000",
        "Ordnungsbehördliche Verordnung über die öffentliche Sicherheit und Ordnung auf den Verkehrsflächen und Anlagen in der Stadt Krefeld",
        "2023-09-28", "in der Fassung der 6. Änderungsverordnung vom 22.09.2023 (Krefelder Amtsblatt Nr. 39 vom 28.09.2023; S. 378)", "consolidated",
        "Bans camping, lagern or overnighting (also in vehicles) and lingering visibly drunk or for drinking sessions "
        "on traffic areas and in parks (§ 2 Abs. 5); alcohol and drug use near entrances of kindergartens, "
        "playgrounds, schools, youth and cultural facilities (§ 2 Abs. 2); intrusive to aggressive begging "
        "('Nein heißt Nein'), organised begging and further forms (§ 2 Abs. 5 Nr. 5).",
        ["das Zelten, Lagern oder Übernachten (auch in Wohnwagen, Wohnmobilen, Kfz. u. ä.)",
         "in betrunkenem Zustand mit erkennbaren Ausfallerscheinungen oder zur Abhaltung von Trinkgelagen",
         "aufdringliches bis hin zu aggressivem Betteln (erneute Ansprache trotz vorheriger Ablehnung – Nein heißt Nein)",
         # b19 lapse test (Lead 2026-11-23): deciding sentence
         "Gleichzeitig tritt die Ordnungsbehördliche Verordnung über die Aufrechterhaltung der öffentlichen Sicherheit und Ordnung im Stadtgebiet Krefeld vom 26.05.2000 außer Kraft"],
        note="cited as a new ordinance of 22.09.2023 (Lead b20): its final clause repeals the ordinance of 26.05.2000, so the "
             "20-year term of § 32 OBG NRW runs from 2023; the city's heading still lists it as the 6. Änderungsverordnung of the 2000 "
             "text (row key unchanged, renamed in place)"),
    _mu("oberhausen_ovo", "05119", "NW", "Oberhausen",
        "https://www.oberhausen.de/de/index/rathaus/verwaltung/soziales-gesundheit-wohnen-und-recht/recht/ortsrecht_der_stadt_oberhausen/ortsrecht-material/171214_ovo_oeff_sich_u_ord_mit_anlagen_01012018.pdf",
        "verordnung", "betteln,lagern,alkohol", "Oberhausener Ortsrecht: OVO vom 14.12.2017 (Sonderamtsblatt 20/2017 S. 269)",
        "Ordnungsbehördliche Verordnung über die Aufrechterhaltung der öffentlichen Sicherheit und Ordnung im Gebiet der Stadt Oberhausen",
        "2017-12-21", "Amtsblatt für die Stadt Oberhausen, Sonderamtsblatt 20/2017 vom 21.12.2017, Seite 269 – 274", "original",
        "On streets and in parks bans camping and overnighting, aggressive begging, feigned need, animals as pressure "
        "and silent begging involving children, group 'Lagern' that obstructs passers-by, and alcohol-related "
        "disturbances (§ 1 Abs. 1); in public-transport facilities use as a resting or camp place and alcohol (§ 2). "
        "Valid until 31.12.2027.",
        ["1. das Campieren und Nächtigen",
         "sowie das stille Betteln unter Beteiligung von Kindern",
         "das Lagern in Personengruppen, wenn sich diese an denselben Orten ansammeln",
         "und gilt bis zum 31. Dezember 2027", 'in Kraft und gilt bis zum 31. Dezember 2027'],
        ends_on='2028-01-01', ends_needle='in Kraft und gilt bis zum 31. Dezember 2027'),
    _mu("hagen_gebietsordnung", "05914", "NW", "Hagen",
        "https://www.hagen.de/dateien/aus-dem-rathaus/politik-und-gremien/stadtrecht/s/323201-gebietsordnung-stand-mai-2025.pdf",
        "verordnung", "betteln,lagern,alkohol", "Hagener Stadtrecht 32.32.01 Gebietsordnung vom 24.10.1985 i.d.F. des VII. Nachtrags vom 30.07.2018",
        "Ordnungsbehördliche Verordnung über die Aufrechterhaltung der öffentlichen Sicherheit und Ordnung im Gebiet der Stadt Hagen (Gebietsordnung-GebietsO)",
        "2018-08-03", "7. Nachtrag vom 30. Juli 2018, öffentlich bekannt gemacht am 03. August 2018, in Kraft getreten am 10. August 2018", "consolidated",
        "Bans disturbing alcohol use, drunkenness, aggressive begging and intrusiveness in public, and recurring "
        "stationary gatherings that cause regular disturbances (§ 4 Abs. 2); lagern, camping or overnighting in parks "
        "outside released areas and drinking alcohol in parks outside licensed areas (§ 4 Abs. 1).",
        ["störender Alkoholgenuss, Trunkenheit, aggressives Betteln und Aufdringlichkeit, sind in der Öffentlichkeit nicht gestattet",
         "in Anlagen auf hierfür nicht besonders freigegebenen Flächen zu lagern, zu campieren oder zu übernachten",
         # b19 lapse test (Lead 2026-11-23): deciding sentence
         "Öffentlich bekannt gemacht am 29. Oktober 1985, in Kraft seit dem 6. November 1985"],
        lapsed_on="2005-11-06", lapsed_needle="Öffentlich bekannt gemacht am 29. Oktober 1985, in Kraft seit dem 6. November 1985",
        lapsed_basis=("§ 32 Abs. 1 OBG NRW: an ordnungsbehördliche Verordnung without its own term lapses 20 years after entry into "
                      "force; in force since 06.11.1985, the I.–VII. Nachtrag are amendments and do not restart the term "
                      "(Lead decision 2026-11-23: kept as a historical record)"),
        note="file name says 'Stand Mai 2025'; the text's own version note is the 7th amendment of 2018; a full revision was proposed to the council in Dec 2025 (not checked)"),
    _mu("heidelberg_polvo", "08221", "BW", "Heidelberg",
        "https://www.heidelberg.de/site/Heidelberg2021/get/documents_E-1587363070/heidelberg/Objektdatenbank/30/PDF/30_pdf_ortsr_3-1-1_Allgemeine_Polizeiverordnung.pdf",
        "verordnung", "betteln,lagern,alkohol", "Heidelberger Ortsrecht 3.1.1 Allgemeine Polizeiverordnung vom 18.03.2021",
        "Polizeiverordnung zur Aufrechterhaltung der öffentlichen Sicherheit und Ordnung und gegen umweltschädliches Verhalten in der Stadt Heidelberg (Allgemeine Polizeiverordnung - PolVO)",
        "2021-04-14", "vom 18. März 2021 (Heidelberger Stadtblatt vom 14. April 2021)", "original",
        "On public streets, in parks and facilities bans begging that seeks physical closeness, insults or harasses, "
        "commercially organised begging and inciting minors, as well as particularly intrusive or aggressive begging; "
        "storing objects of any kind without permission; staying there visibly drunk or intoxicated where others are "
        "harassed. In force 18.05.2021.",
        ["das die körperliche Nähe suchende, beleidigende, belästigende oder gewerbsmäßig organisierte Betteln",
         "ohne Genehmigung der Stadt Heidelberg Gegenstände jeder Art zu lagern",
         "sich dort in erkennbar betrunkenem",
         "Diese Polizeiverordnung tritt am 18. Mai 2021 in Kraft"],
        in_force_from="2021-05-18"),
    _mu("potsdam_stadtordnung", "12054", "BB", "Potsdam",
        "https://www.potsdam.de/system/files/document/Stadtordnung%202024_07_22.pdf",
        "verordnung", "lagern", "Potsdamer Stadtordnung vom 21.05.2024 (Amtsblatt 17/2024 S. 19 ff.)",
        "Ordnungsbehördliche Verordnung zur Abwehr von Gefahren für die öffentliche Sicherheit oder Ordnung im Bereich der Verkehrsflächen und öffentlichen Anlagen im Gebiet der Landeshauptstadt Potsdam (Stadtordnung)",
        "2024-09-19", "Rechtsverbindlicher Text der Stadtordnung im Amtsblatt der Landeshauptstadt Potsdam Nr. 17/2024 vom 19.09.2024", "consolidated",
        "Bans setting up tents, motorhomes and trailers for living or overnighting in public traffic space outside "
        "approved campsites. The ordinance has no begging or alcohol clause.",
        ["Wohnmobile, Wohnanhänger und Zelte dürfen außerhalb baurechtlich genehmigter Campingplätze zu Wohn- und Übernachtungszwecken im öffentlichen Verkehrsraum nicht ab- und aufgestellt werden"],
        note="reading copy (Lesefassung) published by the city"),
    _mu("herne_strassenvo", "05916", "NW", "Herne",
        "https://www.herne.de/PDF/Ortsrecht/3-Rechts-Sicherheits-und-Ordnungsrecht/3_01.pdf.pdf",
        "verordnung", "betteln,lagern,alkohol", "Herner Ortsrecht 3.1 Ordnungsbehördliche Straßenverordnung vom 21.12.2005 i.d.F. vom 02.03.2017",
        "Ordnungsbehördliche Verordnung über die Aufrechterhaltung der öffentlichen Sicherheit und Ordnung im Stadtgebiet Herne - Ordnungsbehördliche Straßenverordnung",
        "2017-03-02", "vom 21.12.2005 in der Fassung der Änderungsverordnung vom 02.03.2017", "consolidated",
        "Bans lagern, camping or overnighting on streets or in parks outside released areas; recurring gatherings "
        "causing disturbances e.g. through excessive alcohol; aggressive begging; begging by or with children under 14 (§ 5).",
        ["auf Straßen oder in Anlagen auf hierfür nicht besonders freigegebenen Flächen zu lagern, zu campieren oder zu übernachten",
         "Aggressives Betteln durch Anfassen, Festhalten, Versperren des Weges, bedrängendes oder hartnäckiges Ansprechen ist verboten",
         "Das Betteln durch Kinder und in Begleitung von Kindern ist verboten",
         # b19 lapse test (Lead 2026-11-23): deciding sentence
         "Die öffentliche Bekanntmachung der Ordnungsbehördlichen Straßenverordnung erfolgte in den Herner Ausgaben der WAZ am 02.01.2006",
         "Diese Ordnungsbehördliche Verordnung tritt am Tage nach ihrer Verkündigung in Kraft"],
        lapsed_on="2026-01-03",
        lapsed_needle="Die öffentliche Bekanntmachung der Ordnungsbehördlichen Straßenverordnung erfolgte in den Herner Ausgaben der WAZ am 02.01.2006",
        lapsed_basis=("§ 32 Abs. 1 OBG NRW: an ordnungsbehördliche Verordnung without its own term lapses 20 years after entry into "
                      "force; published 02.01.2006, in force the day after (03.01.2006), the 2017 change is an amendment and does not "
                      "restart the term (Lead decision 2026-11-23: kept as a historical record)")),
    # ---- batch 18 (a): kreisangehörige cities over ~80k (2026-11-23; robots per host checked with the module's
    #      longest-match parser, fail closed) ----
    _mu("aachen_unterk", "05334", "NW", "Aachen",
        "https://www.aachen.de/in-aachen-leben/politik-und-verwaltung/stadtrecht/soziales/benutzungs-und-gebuehrensatzung-fuer-die-staedtischen-unterkuenfte-zur-unterbringung-22-04-2024.pdf?cid=4i7",
        "satzung", "obdach,obdach_gebuehr", "Stadtrecht Aachen (Soziales): Benutzungs- und Gebührensatzung für die städtischen Unterkünfte vom 22.04.2024 (in Kraft 01.07.2024)",
        "Benutzungs- und Gebührensatzung der Stadt Aachen für die städtischen Unterkünfte zur Unterbringung von geflüchteten Menschen, wohnungslosen Menschen und Spätaussiedler*innen",
        "2024-04-22", "vom 22. April 2024", "original",
        "Use and fee statute for the city's accommodation for refugees, homeless people placed under § 14 OBG and late "
        "resettlers: base fee 12.79 EUR per m² and month in transitional homes (tariff A) and 8.89 EUR in flats "
        "(tariff B), plus consumption fees.",
        ["von obdachlosen Menschen, die gem. § 14 des Ordnungsbehördengesetzes (OBG)",
         "Diese Satzung tritt am 01.07.2024 in Kraft"],
        fees=[_fee("obdach_gebuehr_grund_eur_m2_monat__tarif_a_uebergangswohneinrichtungen", 12.79, "EUR/m²/Monat",
                   "im Gebührentarif „A“ Übergangswohneinrichtungen 12,79 Euro", "§ 7 Abs. 2a", 2024),
              _fee("obdach_gebuehr_grund_eur_m2_monat__tarif_b_wohnungen", 8.89, "EUR/m²/Monat",
                   "im Gebührentarif „B“ Wohnungen 8,89 Euro", "§ 7 Abs. 2a", 2024)],
        in_force_from="2024-07-01", gem="05334002"),
    _mu("hildesheim_obdach", "03254", "NI", "Hildesheim",
        "https://www.stadt-hildesheim.de/downloads/datei/YmEzOGE2Y2U4YWZjYTVhZElpM2FuMjQzSFRVMFUzQWdVQk8rdEYwOVE1YW1WR1JHcDB1R2NYNERaNGxKQWxka2JmaXEvU3lUZVhsOWx0TjgrZ2JSZFpvSDNHeGtFelpxU1p5L0cvNW50aThCakJ1MEp6V1NJMHpMYnlFcWV2YTBqajlQOElqVVUyb1E0VUQvZTAxRGh4Y1Q1aERzM3EwWVlZeE9rbk5PYlE2a29UMDd5U3hYcVNLNjk3TzMvNWFWN1BBSm1KRHFzNGxxS2ZSdGtFY1JCdXdEbHFSYmQ3ZEJHaVk0MkE9PQ",
        "satzung", "obdach", "Stadtrecht Hildesheim 40.01 Satzung über die Benutzung der Notunterkünfte vom 18.12.2023 (Amtsblatt für den Landkreis Hildesheim 2023 S. 883, in Kraft 01.03.2024)",
        "Satzung über die Benutzung der Notunterkünfte der Stadt Hildesheim",
        "2023-12-18", "in seiner Sitzung am 18.12.2023", "original",
        "Use statute for the city's emergency shelters for homeless people (also resettlers, asylum seekers and "
        "refugees): admission by placement order, duty to seek own housing, storage of belongings.",
        ["zur vorübergehenden Unterbringung wohnungsloser Personen",
         "Amtsblatt für den Landkreis Hildesheim 2023, S. 883, in Kraft seit 01.03.2024"],
        in_force_from="2024-03-01", gem="03254021",
        note="the city's Stadtrecht collection is a non-official reprint; the Amtsblatt für den Landkreis Hildesheim "
             "is authoritative (stated on the collection page)"),
    _mu("hildesheim_obdach_geb", "03254", "NI", "Hildesheim",
        "https://www.stadt-hildesheim.de/downloads/datei/NTY1ODk1ZTRhOTE3ZjUyZlo0RWxxalNKTUcvcTFVTFZRb3REMGJKdUpld0k1SUpSOVQrYkJnRG96QUk0aUkxcEtlYS9Ia2pXSnhBVVFTeVdFL05wbGhVd1F3SFFycjdXK1lPczJ1WlU3cUJOY0dyaGVwZlNsK0pHeUtteVRUR044WUZFbzgweDBESnpuU3RjdUpYY3lrWTAyQzdZVmpKdGxSaXlJT1h6RmNSL1Y3bmI3amxBYjRrN0RaTU1wSVRiekZ6Y1JkM01BaklGTnV1ankyWDJEZVp5dGFXOC9NY0R2NGI3Q3NEamtrR0RPU09EUVUwUFFOa1FWVFU9",
        "satzung", "obdach_gebuehr", "Stadtrecht Hildesheim 40.02 Satzung über die Benutzungsgebühren der Notunterkünfte vom 18.12.2023 (Amtsblatt für den Landkreis Hildesheim 2023 S. 889, in Kraft 01.03.2024)",
        "Satzung über die Benutzungsgebühren der Notunterkünfte der Stadt Hildesheim",
        "2023-12-18", "in seiner Sitzung am 18.12.2023", "original",
        "Fee statute for the city's emergency shelters: a monthly fee per place by household size (350 EUR for one "
        "person, 664 EUR for two), plus a flat electricity charge of 35 EUR per adult and 15 EUR per child.",
        ["Diese Gebührensatzung tritt am 01.03.2024 in Kraft",
         "Die Benutzungsgebühr wird als Monatsgebühr erhoben"],
        fees=[_fee("obdach_gebuehr_eur_platz_monat__1_person", 350.00, "EUR/Platz/Monat",
                   "mtl. Gebühr pro Platz/Person (abgerundet) 350,00 €", "Anlage 1", 2024),
              _fee("obdach_gebuehr_eur_haushalt_monat__2_personen", 664.00, "EUR/Haushalt/Monat",
                   "2-Personenhaushalt 664,00 €", "Anlage 1", 2024)],
        in_force_from="2024-03-01", gem="03254021",
        note="the city's Stadtrecht collection is a non-official reprint; the Amtsblatt für den Landkreis Hildesheim "
             "is authoritative (stated on the collection page)"),
    _mu("dorsten_uebergang", "05562", "NW", "Dorsten",
        "https://www.dorsten.de/_Resources/Persistent/0/4/0/6/0406cc2cd724b07dfae859feb0a1e87d361edc15/50_01%20Satzung%20%C3%9Cbergangsheime%2C%2010.%20%C3%84nderung_12_24.pdf",
        "satzung", "obdach,obdach_gebuehr", "Dorstener Ortsrecht 50 01 Satzung über die Unterhaltung von städtischen Unterkünften / Übergangsheimen vom 15.12.2005 i.d.F. der 10. Änderung vom 21.11.2024 (Amtsblatt Nr. 34 vom 09.12.2024)",
        "Satzung der Stadt Dorsten über die Unterhaltung von städtischen Unterkünften / Übergangsheimen und die Erhebung von Benutzungsgebühren",
        "2024-11-21", "10. Änderung der Satzung der Stadt Dorsten über die Unterhaltung von städtischen Unterkünften / Übergangsheimen und die Erhebung von Benutzungsgebühren vom 21.11.2024", "consolidated",
        "Use and fee statute for the city's accommodation for homeless people and refugees: fees per m² of living "
        "space and month set per building (8.00 to 15.00 EUR), 11.00 EUR in additionally rented flats.",
        ["Obdachlose Personen, die sich aus eigener Kraft nicht selbst eine andere Unterkunft/Wohnung beschaffen können",
         "Satzungsänderung öffentlich bekannt gemacht im Amtsblatt Nr. 34 vom 09.12.2024"],
        fees=[_fee("obdach_gebuehr_eur_m2_monat__angemietete_wohnung", 11.00, "EUR/m²/Monat",
                   "betragen 11,00 Euro pro m²", "§ 6 Abs. 4", 2024)],
        gem="05562012"),
    _mu("castrop_unterk", "05562", "NW", "Castrop-Rauxel",
        "https://www.castrop-rauxel.de/sites/default/files/2024-02/4-5_Benutzungs-%20und%20Geb%C3%BChrensatzung%20f%C3%BCr%20die%20st%C3%A4dtischen%20Unterk%C3%BCnfte%20f%C3%BCr%20Fl%C3%BCchtlinge%20und%20Obdachlose%202020.pdf",
        "satzung", "obdach,obdach_gebuehr", "Castrop-Rauxeler Ortsrecht 4-5 Benutzungs- und Gebührensatzung der städtischen Unterkünfte für Flüchtlinge und Obdachlose vom 02.03.2020 (in Kraft 01.04.2020)",
        "Benutzungs- und Gebührensatzung der städtischen Unterkünfte für Flüchtlinge und Obdachlose der Stadt Castrop-Rauxel",
        "2020-03-02", "Castrop-Rauxel, den 02. März 2020", "original",
        "Use and fee statute for the city's accommodation for refugees and homeless people: fees per 10 m² of "
        "allocated space, category 1 base fee 148.50 EUR plus consumption, running, heating and electricity "
        "charges; category 2 base fee 123.50 EUR.",
        ["Diese Satzung tritt am 01.04.2020 in Kraft"],
        fees=[_fee("obdach_gebuehr_grund_eur_10m2_monat__kategorie_1", 148.50, "EUR/10 m²/Monat",
                   "Grundgebühr 148,50 €", "§ 6 Abs. 1", 2020),
              _fee("obdach_gebuehr_grund_eur_10m2_monat__kategorie_2", 123.50, "EUR/10 m²/Monat",
                   "Grundgebühr 123,50 €", "§ 6 Abs. 1", 2020)],
        in_force_from="2020-04-01", gem="05562004",
        note="the fee is stated per 10 m² ('Die Gebühr für 10m² beträgt'); the fee debt arises per calendar month "
             "(§ 5 Abs. 4)"),
    # b20 (Lead 2026-11-23): Gladbeck (a), Lead's manual archive of the city upload (the Ortsrecht page answers 404)
    _mu("gladbeck_unterk", "05562", "NW", "Gladbeck",
        "https://www.gladbeck.de/uploads/Benutzung_der_Obdachlosenunterkuenfte_43d09e74e0.pdf",
        "satzung", "obdach,obdach_gebuehr",
        "Gladbecker Ortsrecht Satzung über die Benutzung von städtischen Unterkünften und die Erhebung von Benutzungsgebühren vom 02.06.2022",
        "Satzung über die Benutzung von städtischen Unterkünften der Stadt Gladbeck und die Erhebung von Benutzungsgebühren",
        "2022-06-02", "Gladbeck, den 02.06.2022 Bettina Weist - Bürgermeisterin", "original",
        "Use and fee statute for the city's accommodation for refugees and for homeless people under § 14 OBG "
        "(Übergangsheime, flats and rooms) as public institutions; allocation by revocable, time-limited administrative act; "
        "monthly fee per m² of living space plus a per-person fee for administration, furnishing and operation, by "
        "category A (permanent facilities), B (containers, makeshift housing) and C (rented flats).",
        ["Satzung über die Benutzung von städtischen Unterkünften der Stadt Gladbeck und die Erhebung von Benutzungsgebühren vom 02.06.2022",
         "c) Obdachlosen oder sonstigen Wohnungsnotfällen gemäß § 14 des Gesetzes über Aufbau und Befugnisse der Ordnungsbehörden",
         "(1) Diese Satzung tritt am Tag nach ihrer Bekanntmachung in Kraft. (2) Gleichzeitig tritt die Satzung über die Benutzung der Übergangsheime der Stadt Gladbeck und die Erhebung von Benutzungsgebühren vom 12.12.2017 außer Kraft"],
        fees=[_fee("obdach_gebuehr_eur_m2_monat__kategorie_a", 4.72, "EUR/m2/Monat",
                   "der Kategorie A (ständige Unterbringungseinrichtungen) 4,72 Euro", "§ 7 Abs. 3", 2022),
              _fee("obdach_gebuehr_eur_m2_monat__kategorie_b", 6.20, "EUR/m2/Monat",
                   "der Kategorie B (Container, provisorischer Wohnraum) 6,20 Euro", "§ 7 Abs. 3", 2022),
              _fee("obdach_gebuehr_eur_m2_monat__kategorie_c", 6.20, "EUR/m2/Monat",
                   "der Kategorie C (angemietete Wohnungen) 6,20 Euro", "§ 7 Abs. 3", 2022),
              _fee("obdach_gebuehr_eur_person_monat__kategorie_a", 172.92, "EUR/Person/Monat",
                   "der Kategorie A (ständige Unterbringungseinrichtungen) 172,92 Euro", "§ 7 Abs. 3", 2022),
              _fee("obdach_gebuehr_eur_person_monat__kategorie_b", 316.57, "EUR/Person/Monat",
                   "der Kategorie B (Container, provisorischer Wohnraum) 316,57 Euro", "§ 7 Abs. 3", 2022),
              _fee("obdach_gebuehr_eur_person_monat__kategorie_c", 115.02, "EUR/Person/Monat",
                   "der Kategorie C (angemietete Wohnungen) 115,02 Euro", "§ 7 Abs. 3", 2022)],
        note="manual archive via browser, 2026-11-23 (Lead), file muni_gladbeck_obdach_gebuehren.pdf; the city's "
             "Ortsrecht page answers 404 to the project UA, so the file is read from the archive only. Covers refugees "
             "and homeless people alike; the Bekanntmachung date is not in the archived text, so in_force_from is not set",
        local="muni_gladbeck_obdach_gebuehren.pdf", gem="05562014"),
    _mu("arnsberg_geb2026", "05958", "NW", "Arnsberg",
        "https://www.arnsberg.de/fileadmin/user_upload/Bilder_und_pdf-Dateien/1.5/amtliche-bekanntmachungen/2026/20260122_bekanntmachung_gebuehrenanpassung_unterkuenfte.pdf",
        "satzung", "obdach,obdach_gebuehr", "Öffentliche Bekanntmachung der Stadt Arnsberg vom 19.12.2025: Gebührenanpassung zum 01.01.2026 nach § 5 Abs. 4 der Satzung über die Benutzung von Obdachlosenunterkünften und Übergangsheimen (Stand 19.12.2016)",
        "Öffentliche Bekanntmachung der Stadt Arnsberg – Gebührenanpassung zum 01.01.2026 für die Benutzung der städtischen Obdachlosenunterkünfte und Übergangswohnheime",
        "2025-12-19", "Arnsberg, 19.12.2025", "original",
        "Annual fee notice under the shelter statute: from 01.01.2026 homeless shelters charge a base fee of 11.64 EUR "
        "per m² and month plus electricity 28.91 EUR and water 10.98 EUR per person and heating 1.39 EUR per m².",
        ["Gebührenanpassung zum 01.01.2026 für die Benutzung der städtischen Obdachlosenunterkünfte"],
        fees=[_fee("obdach_gebuehr_grund_eur_m2_monat", 11.64, "EUR/m²/Monat",
                   "Für Obdachlosenunterkünfte: Grundgebühr pro m2: 11,64 €", "Bekanntmachung zu § 5 Abs. 4", 2026)],
        in_force_from="2026-01-01", gem="05958004",
        lic=("Amtliches Werk (§ 5 Abs. 1 UrhG): öffentliche Bekanntmachung der Stadt Arnsberg (Gebührenanpassung "
             "nach § 5 Abs. 4 der Satzung) und kommunale Satzung; zitiert mit Fundstelle"),
        extra=[("https://www.arnsberg.de/fileadmin/user_upload/Bilder_und_pdf-Dateien/1.0.2/ortsrecht/obdachlosenunterkuenfte.pdf",
                ["Satzung über die Benutzung von Obdachlosenunterkünften und Übergangsheimen für ausländische Flüchtlinge und Spätaussiedler der Stadt Arnsberg"])]),
    _mu("bocholt_obdach", "05554", "NW", "Bocholt",
        "https://www.bocholt.de/bocholt_media/fachbereiche/fb12/ortsrecht-satzungen/sozial-jugend-und-sportverwaltung/satzung-der-stadt-bocholt-ueber-die-benutzung-und-benutzungsgebuehren-der-obdachlosenunterkuenfte-uebergangswohnungen-fuer-aus-und-uebersiedler-und-unterkuenfte-fuer-auslaendische-fluechtlinge.pdf?download=1",
        "satzung", "obdach,obdach_gebuehr", "Bocholter Ortsrecht 5.1 Satzung über die Benutzung und Benutzungsgebühren der Obdachlosenunterkünfte vom 10.11.2021 (in Kraft 01.12.2021)",
        "Satzung der Stadt Bocholt über die Benutzung und Benutzungsgebühren der Obdachlosenunterkünfte, Übergangswohnungen für Aus- und Übersiedler und Unterkünfte für ausländische Flüchtlinge",
        "2021-11-10", "vom 10.11.2021, in Kraft getreten am 01.12.2021", "original",
        "Use and fee statute for the city's homeless shelters, resettler flats and refugee accommodation: fee per "
        "person and month 157 EUR in shared homeless shelters (category 1), 109 EUR in single units (category 3), "
        "plus running-cost charges (102 and 77 EUR when issued).",
        ["Die Benutzungsgebühr wird pro Person berechnet"],
        fees=[_fee("obdach_gebuehr_eur_person_monat__kategorie_1_sammelunterkunft", 157.00, "EUR/Person/Monat",
                   "für eine Unterkunft der Kategorie 1: 157,00 €", "§ 5", 2021),
              _fee("obdach_gebuehr_eur_person_monat__kategorie_3_einzelunterkunft", 109.00, "EUR/Person/Monat",
                   "für eine Unterkunft der Kategorie 3: 109,00 €", "§ 5", 2021)],
        in_force_from="2021-12-01", gem="05554008"),
    _mu("moers_unterk", "05170", "NW", "Moers",
        "https://www.moers.de/system/files?file=2025-03/OR%2052-02%20Unterhaltung%20und%20Bereitstellung%20st%C3%A4dt.%20Unterk%C3%BCnfte_0.pdf",
        "satzung", "obdach,obdach_gebuehr", "Moerser Ortsrecht 50/02 Unterkunftssatzung vom 12.02.2025 (in Kraft 01.03.2025)",
        "Satzung der Stadt Moers über die Unterhaltung und Bereitstellung städtischer Unterkünfte für Obdachlose, Asylantragsteller, Spätaussiedler und Flüchtlinge (Unterkunftssatzung)",
        "2025-02-12", "(Unterkunftssatzung) vom 12.02.2025", "original",
        "Use and fee statute for the city's accommodation for homeless people, asylum seekers, late resettlers and "
        "refugees: monthly fee per person 347 EUR in the homeless shelters (incl. 46.50 EUR heating) and 268 EUR in "
        "refugee accommodation.",
        ["Diese Satzung tritt am 01.03.2025 in Kraft"],
        fees=[_fee("obdach_gebuehr_eur_person_monat__obdachlosenunterkuenfte", 347.00, "EUR/Person/Monat",
                   "Einzelpersonen 347,00 € pro Person", "Gebührentarif Nr. 1", 2025)],
        in_force_from="2025-03-01", gem="05170024"),
    # ---- batch 18 (b): ordinances of kreisangehörige cities covered for (a) ----
    _mu("moers_obvo", "05170", "NW", "Moers",
        "https://www.moers.de/system/files?file=2024-09/OR32-01%20Ordnungsb.verord.pdf",
        "verordnung", "lagern,alkohol", "Moerser Ortsrecht 32/01 Ordnungsbehördliche Verordnung vom 21.08.2024",
        "Ordnungsbehördliche Verordnung über die Aufrechterhaltung der öffentlichen Sicherheit und Ordnung im Gebiet der Stadt Moers",
        "2024-08-21", "im Gebiet der Stadt Moers vom 21.08.2024", "original",
        "City-wide public-order ordinance: bans lying around or sleeping in green spaces and on streets "
        "(§ 3 b) and drinking alcohol on playgrounds and school yards; no begging rule.",
        ["b) in den Anlagen und auf den Verkehrsflächen zu lagern oder zu übernachten",
         "Auf Spielplätzen sowie auf Schulhöfen sind der Verzehr von alkoholischen Getränken sowie das Rauchen nicht gestattet"],
        gem="05170024"),
    _mu("neuss_strassenordnung", "05162", "NW", "Neuss",
        "https://www.neuss.de/fileadmin/Redaktion/downloads/ortsrecht/32-01_strassenordnung.pdf",
        "verordnung", "betteln,lagern,alkohol", "Neusser Ortsrecht 32/01 Straßenordnung vom 20.03.2015 (in Kraft 01.04.2015), geändert durch die 1. Änderungsverordnung 2025 (Beschluss 04.07.2025)",
        "Ordnungsbehördliche Verordnung zur Aufrechterhaltung der öffentlichen Sicherheit und Ordnung auf den Straßen und in den angrenzenden bebauten Gebieten der Stadt Neuss (Straßenordnung der Stadt Neuss)",
        "2015-03-20", "(Straßenordnung der Stadt Neuss) vom 20. März 2015", "original",
        "Street ordinance: no lying around, camping or sleeping on streets and squares; bans aggressive begging and "
        "begging with children, group 'Lagern' that obstructs passers-by and alcohol-related disturbances. The 2025 "
        "amendment (archived as the extra source) re-words § 4 (3) and adds an alcohol and drug ban at "
        "kindergarten and school entrances.",
        ["Auf den Straßen und Plätzen darf nicht gelagert, campiert oder",
         "Störungen in Verbindung mit Alkoholgenuss",
         "Diese Verordnung tritt am 01. April 2015 in Kraft"],
        in_force_from="2015-04-01", gem="05162024",
        lic=("Amtliches Werk (§ 5 Abs. 1 UrhG): kommunale Verordnung und amtliche Bekanntmachung der Änderungsverordnung; "
             "zitiert mit Fundstelle"),
        extra=[("https://www.neuss.de/fileadmin/Redaktion/downloads/bekanntmachungen/2025/bekanntmachung-stadt-neuss_0600-2025_aenderung-strassenordnung.pdf",
                ["Betteln durch Einsetzen von Kindern",
                 "Im unmittelbaren Eingangsbereich von Kindergärten und Schulen ist das Konsumie"])]),
    _mu("guetersloh_obvo", "05754", "NW", "Gütersloh",
        "https://www.guetersloh.de/de-wAssets/docs/ortsrecht/Ordnungsbehoerdliche_Verordnung_zur_Aufrechterhaltung_der_oeffentlichen_Sicherheit_und_Ordnung.pdf",
        "verordnung", "betteln,lagern,alkohol", "Gütersloher Ortsrecht ObVO vom 03.05.2024 (Amtsblatt 10/2024 vom 17.05.2024; in Kraft 01.06.2024 bis 31.05.2034)",
        "Ordnungsbehördliche Verordnung zur Aufrechterhaltung der öffentlichen Sicherheit und Ordnung im Gebiet der Stadt Gütersloh (ObVO)",
        "2024-05-03", "(ObVO) vom 03.05.2024", "original",
        "City-wide public-order ordinance (valid to 31.05.2034): bans sleeping in green spaces, group 'Lagern' that "
        "obstructs passers-by, begging that is aggressive, organised, obstructs traffic, feigns need, involves minors "
        "or misuses animals, alcohol-related disturbances and alcohol on playgrounds.",
        ["7. das Betteln in folgenden Formen: 7.1. aggressiv / aufdringlich",
         "3. in den Anlagen zu übernachten",
         "das Stören in Verbindung mit dem Genuss von Alkohol oder anderen berauschenden Mitteln",
         "Diese Verordnung tritt am 01.06.2024 in Kraft. Sie tritt am 31.05.2034 außer Kraft"],
        in_force_from="2024-06-01", gem="05754008",
        ends_on='2034-05-31', ends_needle='Diese Verordnung tritt am 01.06.2024 in Kraft. Sie tritt am 31.05.2034 außer Kraft'),
    _mu("siegen_obvo", "05970", "NW", "Siegen",
        "https://www.siegen.de/fileadmin/user_upload/Dokumente/RathausUndPolitik/Ortsrecht/32_010.pdf",
        "verordnung", "betteln,alkohol", "Siegener Ortsrecht 32.010 Ordnungsbehördliche Verordnung i.d.F. der 1. Änderung (Ratsbeschluss 26.02.2025, in Kraft 01.04.2025, befristet bis 30.06.2041)",
        "Ordnungsbehördliche Verordnung über die Aufrechterhaltung der öffentlichen Sicherheit und Ordnung in der Universitätsstadt Siegen",
        "2025-03-17", "Siegen, 17. März 2025", "consolidated",
        "City-wide public-order ordinance (valid to 30.06.2041): conduct rule naming aggressive begging as harassment; "
        "drinking in groups of more than two in pedestrian zones and public squares is banned where it endangers "
        "public order; alcohol banned on playgrounds. No sleeping/camping rule.",
        ["aggressives Betteln", "ist der Aufenthalt zum Genuss alkoholischer Getränke in Gruppen von mehr als zwei Personen",
         "Sie ist bis zum 30. Juni 2041 befristet"],
        in_force_from="2025-04-01", gem="05970040"),
    _mu("recklinghausen_obvo", "05562", "NW", "Recklinghausen",
        "https://bso.gkd-re.de/bsointer320/DokumentServlet?dokumentenname=320l1946.pdf",
        "verordnung", "betteln,lagern,alkohol", "Recklinghäuser Ortsrecht Ordnungsbehördliche Verordnung vom 03.12.2024 (gilt 20 Jahre ab Inkrafttreten)",
        "Ordnungsbehördliche Verordnung über die Aufrechterhaltung der öffentlichen Sicherheit und Ordnung der Stadt Recklinghausen",
        "2024-12-03", "der Stadt Recklinghausen vom 03.12.2024", "original",
        "City-wide public-order ordinance (valid 20 years): bans aggressive begging and silent begging with children, "
        "group 'Lagern' that obstructs others, sleeping (also in vehicles) on streets and in green spaces, and "
        "alcohol-related disturbances; intoxicated persons may not stay on playgrounds.",
        ["aggressives Betteln durch Anfassen, Festhalten, Verfolgen",
         "das Stören in Verbindung mit dem Genuss von Alkohol oder anderen berauschenden Mitteln",
         "Sie verliert ihre Geltung 20 Jahre nach ihrem Inkrafttreten"],
        gem="05562032",
        note="served from the city's Bürgerservice document host bso.gkd-re.de (Gemeinsame Kommunale Datenverarbeitung "
             "Recklinghausen), the city's own Ortsrecht/Satzungen link target"),
    _mu("bergischgladbach_obvo", "05378", "NW", "Bergisch Gladbach",
        "https://www.bergischgladbach.de/32-8.pdfx",
        "verordnung", "betteln,lagern,alkohol", "Bergisch Gladbacher Ortsrecht 32.8 Ordnungsbehördliche Verordnung vom 15.02.2012 (in Kraft 02.03.2012) i.d.F. der 2. Änderungsverordnung vom 29.03.2023 (in Kraft 02.04.2023)",
        "Ordnungsbehördliche Verordnung über die Aufrechterhaltung der öffentlichen Sicherheit und Ordnung im Gebiet der Stadt Bergisch Gladbach",
        "2023-03-29", "Die 2. Änderungsverordnung vom 29.03.2023 wurde am 01.04.2023 im Amtsblatt der Stadt Bergisch Gladbach verkündet", "consolidated",
        "City-wide public-order ordinance: conduct rule naming aggressive begging (blocking, dogs as pressure, following, "
        "touching) and alcohol-related disturbances; bans sleeping in green spaces and alcohol on playgrounds.",
        ["3. in den Anlagen zu übernachten",
         "Der Konsum alkoholischer Getränke auf Kinderspielplätzen ist verboten",
         "ist ab 02.03.2012 in Kraft"],
        gem="05378004"),
    _mu("iserlohn_obvo", "05962", "NW", "Iserlohn",
        "https://www.iserlohn.de/fileadmin/user_upload/Dokumente/Aktuelles/32/Ordnungsbehoerdliche_Verordnung_2025.pdf",
        "verordnung", "betteln,lagern,alkohol", "Iserlohner Ordnungsbehördliche Verordnung (Ratsbeschluss 07.10.2025; verkündet im amtlichen Bekanntmachungsblatt des Märkischen Kreises, Nov. 2025)",
        "Ordnungsbehördliche Verordnung über die öffentliche Sicherheit und Ordnung im Stadtgebiet Iserlohn",
        "2025-10-07", "Gemäß Beschluss des Rates der Stadt Iserlohn vom 07.10.2025", "original",
        "City-wide public-order ordinance replacing that of 19.03.2024: bans sleeping on public streets and in green "
        "spaces, staying there intoxicated or for drinking binges, and aggressive begging (touching, blocking the way).",
        ["Das Übernachten auf öffentlichen Straßen und in Anlagen ist verboten",
         "Das Gleiche gilt auch für das Verweilen in berauschtem Zustand und zur Abhaltung von Trinkgelagen",
         "Aggressives Betteln (durch Anfassen, In-den-Weg-Stellen, unmittelbares Einwirken von Person zu Person) ist untersagt"],
        gem="05962024"),
    _mu("dueren_obvo", "05358", "NW", "Düren",
        "https://www.dueren.de/assets/userfiles/pdfbereich_verwaltunundpolitik/S3-07_Sicherheit_und_Ordnung.pdf",
        "verordnung", "betteln,lagern,alkohol", "Dürener Ortsrecht S3-07 Ordnungsbehördliche Verordnung vom 18.12.2025 (in Kraft 01.01.2026 bis 31.12.2045) unter Berücksichtigung der Änderung vom 24.08.2026",
        "Ordnungsbehördliche Verordnung zur Aufrechterhaltung der öffentlichen Sicherheit und Ordnung in der Stadt Düren",
        "2026-08-24", "unter Berücksichtigung der Änderung vom 24.08.2026", "consolidated",
        "City-wide public-order ordinance (valid to 31.12.2045): bans aggressive, accosting, organised begging and "
        "begging with children (and any begging within 5 m of licensed outdoor dining in the city centre), group "
        "'Lagern', alcohol-related disturbances and using streets and green spaces as a place to lie or rest.",
        ["1c. Betteln in Begleitung von Kindern und/oder Jugendlichen",
         "Straßen und Anlagen dürfen nicht als Lager- oder Ruheplatz gebraucht werden",
         "3. Störungen in Verbindung mit Alkoholgenuss",
         "Diese Verordnung tritt am 01.01.2026 in Kraft und am 31.12.2045 außer Kraft"],
        in_force_from="2026-01-01", gem="05358008",
        ends_on='2045-12-31', ends_needle='Diese Verordnung tritt am 01.01.2026 in Kraft und am 31.12.2045 außer Kraft'),
    _mu("troisdorf_obvo", "05382", "NW", "Troisdorf",
        "https://www.troisdorf.de/de/rathaus-service/stadtrat-und-ausschuesse/ortsrecht/3-2.pdf",
        "verordnung", "betteln,lagern,alkohol", "Troisdorfer Ortsrecht 3-2 Troisdorfer Straßenordnung vom 19.08.2008 (in Kraft 27.08.2008) i.d.F. der 3. Änderung vom 10.10.2017",
        "Ordnungsbehördliche Verordnung über die Aufrechterhaltung der öffentlichen Sicherheit und Ordnung im Gebiet der Stadt Troisdorf (Troisdorfer Straßenordnung)",
        "2017-10-10", "zuletzt geändert durch 3. Änderung vom 10. Oktober 2017", "consolidated",
        "Street ordinance (2008, valid to 2028 under § 32 OBG): bans permanent use of streets and green spaces as a "
        "place to store belongings or sleep, group 'Lagern', significant alcohol-related disturbances and aggressive begging.",
        ["dauerhaft als Lager oder Schlafplatz benutzt", "5. aggressives Betteln",
         "erhebliche Störungen in Verbindung mit Alkoholgenuss"],
        in_force_from="2008-08-27", gem="05382068"),
    _mu("ratingen_stadtordnung", "05158", "NW", "Ratingen",
        "https://www.stadt-ratingen.de/fileadmin/user_upload/Bilder/33/Rechtsamt/Ortsrecht/3-Recht_Sicherheit_und_Ordnung/300_Ordnungsbehoerdliche_Verordnung_zur_Aufrechterhaltung_der_oeffentlichen_Sicherheit_und_Ordnung_in_der_Stadt_Ratingen__Ratinger_Stadtordnung_.pdf",
        "verordnung", "betteln,lagern", "Ratinger Ortsrecht 300 Ratinger Stadtordnung (Ratsbeschluss 26.11.2019, in Kraft 23.01.2020)",
        "Ordnungsbehördliche Verordnung zur Aufrechterhaltung der öffentlichen Sicherheit und Ordnung in der Stadt Ratingen (Ratinger Stadtordnung)",
        "2019-11-26", "in der Fassung vom 26.11.2019", "original",
        "City-wide public-order ordinance: bans aggressive begging in many forms (touching, blocking, pressing, "
        "feigning need, with children or animals), recurring stationary gatherings ('Lagern') and camping or "
        "sleeping in green spaces; no alcohol rule.",
        ["1.) aggressives Betteln insbesondere durch Anfassen, Festhalten, Versperren des Weges",
         "3.) zu campen oder zu übernachten", "Diese Verordnung tritt am 23.01.2020 in Kraft"],
        in_force_from="2020-01-23", gem="05158028"),
    _mu("velbert_obvo", "05158", "NW", "Velbert",
        "https://www.velbert.de/fileadmin/user_upload/Rathaus_und_Politik/Ortsrecht/Ordnungsbehoerdliche_Verordnung_08_26.pdf",
        "verordnung", "betteln,lagern,alkohol", "Velberter Ortsrecht Ordnungsbehördliche Verordnung vom 03.08.2026 (Ratsbeschluss 14.07.2026)",
        "Ordnungsbehördliche Verordnung über die Aufrechterhaltung der öffentlichen Sicherheit und Ordnung im Gebiet der Stadt Velbert",
        "2026-08-03", "im Gebiet der Stadt Velbert vom 03.08.2026", "original",
        "City-wide public-order ordinance replacing that of 30.07.2025: bans aggressive begging (defined as touching, "
        "holding, blocking, following or persistently accosting), passive begging with children or animals, "
        "recurring stationary gatherings ('Lagern') and alcohol-related disturbances.",
        ["Aggressiv im Sinne dieser Verordnung ist die Bettelei unter anderem dann",
         "b) das passive Betteln unter Hinzunahme von Kindern und Tieren",
         "d) Störungen in Verbindung mit Alkoholgenuss"],
        gem="05158032"),
    _mu("witten_obvo", "05954", "NW", "Witten",
        "https://www.witten.de/downloads/datei/MDExNzIzMWZkNzFmMWI5MSswMjBPNGhyQ3pqb3dtR1RkZTZnZ3dUd3d2a2NDc1hWS3lMWE9XMElTcmo1amhlN3l3MEtkOThockhwSGcrZklmTDliTStWMjNiOU5VNDJ4SXlvQWhmeitHQnFPa0NDa29NZVNRNHFqZkxBNHYvaCtZSEg5Y2pmYU91ZnljNHRYdFQyWmxaY1ZCcThkd0M0dmZKaTAwcVRia25vQ05BZVBCdkJhRmo4RGRUUEJRUnJqMUw3Ylh6TGdnSFk4aldBWEhtYXhCSUJab0dMeXFQWHNkVVE1VnZIVmhJVzdJblBrdjEwK09qNWpaakpUYzNOMXdxVGd5ZTJidFgybmEzRWQ",
        "verordnung", "betteln,lagern,alkohol", "Wittener Ortsrecht 3.1 Ordnungsverordnung vom 05.04.2019 i.d.F. der Änderungsverordnung vom 07.10.2020",
        "Ordnungsbehördliche Verordnung zur Aufrechterhaltung der öffentlichen Sicherheit und Ordnung in der Stadt Witten (Ordnungsverordnung)",
        "2020-10-07", "in der Fassung der Änderungsverordnung vom 7.10.2020", "consolidated",
        "City-wide public-order ordinance: bans aggressive begging (touching, holding, blocking, following, with dogs), "
        "lying around and sleeping while drunk on streets and in green spaces; alcohol banned on playgrounds.",
        ["aufdringliches Betteln mittels Anfassen, Festhalten, Versperren des Weges",
         "Grölen, Lagern und Nächtigen in alkoholisiertem Zustand", "Alkoholkonsum ist verboten"],
        gem="05954036"),
    _mu("minden_obvo", "05770", "NW", "Minden",
        "https://www.minden.de/dokumente/satzungen/oeffentliche-sicherheit-und-ordnung/3.01-ordnungsbehoerdliche-verordnung-zur-aufrechterhaltung-der-oeffentlichen-sicherheit-und-ordnung-im-gebiet-der-stadt-minden.pdf?cid=6ep",
        "verordnung", "lagern,alkohol", "Mindener Stadtrecht 3.1 Ordnungsbehördliche Verordnung vom 17.03.2011",
        "Ordnungsbehördliche Verordnung der Stadt Minden zur Aufrechterhaltung der öffentlichen Sicherheit und Ordnung im Gebiet der Stadt Minden",
        "2011-03-17", "im Gebiet der Stadt Minden vom 17.03.2011", "original",
        "City-wide public-order ordinance (2011, valid to 2031 under § 32 OBG): bans sleeping on streets and in green "
        "spaces, drinking alcohol or lingering visibly intoxicated within 20 m of public-transport stops, and "
        "alcohol on playgrounds; no begging rule.",
        ["6. in den Anlagen und auf Verkehrsflächen zu übernachten",
         "alkoholische Getränke oder andere berauschende Mittel zu konsumieren",
         "Der Genuss alkoholischer Getränke und das Rauchen auf Kinderspielplätzen ist verboten"],
        gem="05770024"),
    _mu("esslingen_polvo", "08116", "BW", "Esslingen am Neckar",
        "https://www.esslingen.de/site/Esslingen_Layout_2022/get/documents_E2120429448/es/Datenquelle-Esslingen-2022/Ortsrecht/1_Sicherheit_Ordnung/1-2%20Polizeiverordnung.pdf",
        "verordnung", "betteln,lagern", "Esslinger Ortsrecht 1/2 Polizeiverordnung vom 12.03.2018, geändert am 16.03.2026",
        "Polizeiverordnung zur Erhaltung der öffentlichen Sicherheit und Ordnung und gegen umweltschädliches Verhalten",
        "2026-03-16", "vom 12.03.2018 geändert am 16.03.2026", "consolidated",
        "City-wide police ordinance: bans sleeping in public between 20:00 and 06:00, aggressive, insulting, "
        "proximity-seeking and 'Demutsbetteln' (kneeling) begging, inciting minors to beg and any begging by children "
        "and young people.",
        ["2. das Nächtigen in der Zeit von 20:00 bis 06:00 Uhr",
         "aggressives oder beleidigendes Betteln, die körperliche Nähe suchendes Betteln, Demutsbetteln"],
        gem="08116019"),
    _mu("esslingen_alkoholverbot", "08116", "BW", "Esslingen am Neckar",
        "https://www.esslingen.de/site/Esslingen_Layout_2022/get/documents_E-1967515528/es/Datenquelle-Esslingen-2022/Ortsrecht/1_Sicherheit_Ordnung/1-2a%20Polizeiverordnung%20Alkoholverbotszone%20.pdf",
        "verordnung", "alkohol", "Esslinger Ortsrecht 1/2a Polizeiverordnung Alkoholverbotszone vom 16.03.2026 (in Kraft 01.04.2026, befristet bis 15.11.2031)",
        "Polizeiverordnung der Stadt Esslingen am Neckar über ein Alkoholkonsumverbot auf dem Bahnhofplatz und ZOB und der Fleischmannstraße",
        "2026-03-16", "und der Fleischmannstraße vom 16. März 2026", "original",
        "Alcohol ban zone (station square, central bus station, Fleischmannstraße): drinking or carrying alcohol for "
        "drinking is banned outdoors from 1 March to 15 November, daily 12:00-01:00; valid to 15.11.2031.",
        ["Das Alkoholkonsumverbot gilt im Zeitraum vom 1. März bis zum 15. November jeden Jahres",
         "Diese Polizeiverordnung tritt am 1. April 2026 in Kraft und ist befristet bis zum 15. November 2031"],
        in_force_from="2026-04-01", gem="08116019",
        ends_on='2031-11-16', ends_needle='Diese Polizeiverordnung tritt am 1. April 2026 in Kraft und ist befristet bis zum 15. November 2031'),
    _mu("ludwigsburg_polvo", "08118", "BW", "Ludwigsburg",
        "https://www.ludwigsburg.de/site/Ludwigsburg-Internet-2020/get/params_E114581228/18106397/Polizeiverordnung_09_11_2014.pdf",
        "verordnung", "betteln,lagern,alkohol", "Ludwigsburger Stadtrecht Polizeiverordnung vom 08.10.2014 (gültig ab 09.11.2014)",
        "Polizeiverordnung der Stadt Ludwigsburg zur Sicherung der öffentlichen Ordnung und gegen umweltschädliches Verhalten",
        "2014-10-08", "Polizeiverordnung vom 08.10.2014", "original",
        "City-wide police ordinance (2014, within the 20-year limit): bans proximity-seeking, aggressive, insulting or "
        "organised begging and inciting minors to beg, sleeping in public between 21:00 and 06:00, and lingering or "
        "settling down mainly to drink alcohol where this significantly harasses others.",
        ["das die körperliche Nähe suchende oder das sonst besonders aufdringliche, aggressive, beleidigende oder gewerbsmäßige organisierte Betteln",
         "6. das Nächtigen in der Zeit von 21.00 Uhr bis 6.00 Uhr",
         "ausschließlich oder überwiegend zum Zwecke des Alkoholgenusses, wenn durch alkoholbedingte Ausfall- und Folgeerscheinungen Dritte erheblich belästigt werden"],
        gem="08118048"),
    _mu("konstanz_polvo", "08335", "BW", "Konstanz",
        "https://www.konstanz.de/site/Konstanz/get/documents_E1880184109/konstanz/Dateien/Service/Ortsrecht/III%20Recht,%20Sicherheit%20und%20Ordnung/III_01%20Umweltschutz-%20und%20Polizeiverordnung.pdf",
        "verordnung", "betteln,lagern", "Konstanzer Ortsrecht III/01 Umweltschutz- und Polizeiverordnung vom 18.03.2022 (Gemeinderat 17.03.2022)",
        "Umweltschutz- und Polizeiverordnung Stadt Konstanz",
        "2022-03-18", "Konstanz, den 18.03.2022", "original",
        "City-wide police ordinance: bans proximity-seeking or particularly intrusive begging, inciting minors to beg, "
        "commercial or organised begging and begging with pets without animal welfare, and camping or 'Lagern' outside "
        "designated sites; no alcohol rule.",
        ["das die körperliche Nähe suchende oder sonst besonders aufdringliche Betteln",
         "2. das gewerbsmäßige, bandenmäßige bzw. organisierte Betteln",
         "Es ist untersagt, außerhalb dafür besonders bestimmter und entsprechend gekennzeichneter Plätze zu zelten oder zu lagern"],
        gem="08335043"),
    _mu("reutlingen_polvo", "08415", "BW", "Reutlingen",
        "https://www.reutlingen.de/ceasy/resource/?download=1&id=44107",
        "verordnung", "betteln,lagern,alkohol", "Reutlinger Stadtrecht 1.10 Polizeiverordnung i.d.F. vom 16.05.2013 (in Kraft 01.10.2013)",
        "Polizeiverordnung zur Aufrechterhaltung der öffentlichen Sicherheit und Ordnung und gegen umweltschädliches Verhalten",
        "2013-05-16", "IN DER FASSUNG vom 16.05.2013", "original",
        "City-wide police ordinance (in force 01.10.2013, within the 20-year limit): bans sleeping in public between "
        "22:00 and 06:00, proximity-seeking or intrusive begging and inciting minors to beg; on playgrounds alcohol and "
        "the presence of visibly drunk people are banned.",
        ["1. das Nächtigen in der Zeit von 22:00 bis 06:00 Uhr",
         "das die körperliche Nähe suchende oder sonst besonders aufdringliche oder belästi",
         "Diese Polizeiverordnung tritt am 01.10.2013 in Kraft"],
        in_force_from="2013-10-01", gem="08415061"),
    _mu("goettingen_sov", "03159", "NI", "Göttingen",
        "https://www.goettingen.de/downloads/datei/ZGUzMGNhOWQ0NTZmNzBjN3pBcUNmUytwT29sWU5yVU14eFowYzVHL3dOTWJ2dm5jbERMN2VteEQvOTAvZW8rdUZZUU5VV0tNdS9FSWU3c2hGRzFnUU9Mb2hyZjEyOUF5TnJtZkJLYjRXK3JUVlgxeGluWHJ4NTFMMHJlS2J6ZXgvRXVmVVFwaUZVckxIWnQ0ZWYzTFN3STFXTnhKdE84anh0QWlhQzRjYVRodXdPVm41cUxYU1NFcDRsZWtwWEo4d2pTYXh4cFNST3ExVmxEZHJEQjczcE00MnNTODRjdkJMQXlqaVI0cExwTFdmWWRMYWhOOG90R1FKeG89",
        "verordnung", "lagern,alkohol", "Göttinger Stadtrecht 3.1 Verordnung zur Aufrechterhaltung der öffentlichen Sicherheit vom 17.06.2009 (Amtsblatt der Stadt Göttingen vom 30.07.2009, in Kraft 31.07.2009)",
        "Verordnung zur Aufrechterhaltung der öffentlichen Sicherheit in der Stadt Göttingen",
        "2009-06-17", "in der Stadt Göttingen vom 17. Juni 2009", "original",
        "City-wide public-safety ordinance (in force 31.07.2009; under § 61 NPOG it lapses 20 years after entry into "
        "force, i.e. 2029): bans sleeping or camping on public streets and in green spaces and drinking alcohol on "
        "playgrounds; no begging rule.",
        ["d) auf öffentlichen Straßen und in öffentlichen Anlagen zu übernachten oder zu zelten",
         "e) alkoholhaltige Getränke zu verzehren", "in Kraft getreten am 31.7.2009"],
        in_force_from="2009-07-31", gem="03159016"),
    _mu("lueneburg_alkohol_amtsblatt", "03355", "NI", "Lüneburg",
        "https://www.landkreis-lueneburg.de/_Resources/Persistent/7/f/8/d/7f8daf80f15c0f7b852915933aaaa9eded98feba/4a-2026_159-161_Online.pdf",
        "verordnung", "alkohol", "Amtsblatt für den Landkreis Lüneburg Nr. 4a/2026 vom 30.04.2026, S. 160: Alkoholkonsumbegrenzungsverordnung (AlkBegV) der Hansestadt Lüneburg vom 29.04.2026 (gültig bis 30.04.2027)",
        "Verordnung der Hansestadt Lüneburg zur Begrenzung des Alkoholkonsums in einem Teilbereich der Innenstadt (Alkoholkonsumbegrenzungsverordnung - AlkBegV)",
        "2026-04-29", "(Alkoholkonsumbegrenzungsverordnung - AlkBegV) Vom 29.04.2026", "original",
        "Alcohol ban zone (Am Sande and the St. Johannis forecourt): drinking, or carrying alcohol with evident intent "
        "to drink it there, is banned on working days 08:00-19:00; valid until 30.04.2027.",
        ["in der Zeit von 8.00 Uhr bis 19.00 Uhr verboten, 1. alkoholische Getränke zu konsumieren",
         "Diese Verordnung tritt am Tage nach ihrer Bekanntgabe in Kraft und mit Ablauf des 30.04.2027 außer Kraft"],
        gem="03355022",
        lic="Amtliches Werk (§ 5 Abs. 1 UrhG): Verordnung, verkündet im Amtsblatt für den Landkreis Lüneburg; zitiert mit Fundstelle",
        note="served from the Landkreis Lüneburg gazette (the Hansestadt's promulgation organ); the city's general SOV of "
             "20.10.1994 is not ingested because under § 61 NPOG it lapsed 20 years after entry into force",
        ends_on='2027-05-01', ends_needle='Diese Verordnung tritt am Tage nach ihrer Bekanntgabe in Kraft und mit Ablauf des 30.04.2027 außer Kraft'),
    _mu("zwickau_polvo", "14524", "SN", "Zwickau",
        "https://www.zwickau.de/media/downloads/image/01_buerger/ortsrecht/3_1_PolVO_idF_v_29_09_23.pdf",
        "verordnung", "betteln,lagern,alkohol", "Zwickauer Ortsrecht 3.1 Polizeiverordnung (PolVO) vom 29.09.2023 (in Kraft 07.10.2023)",
        "Polizeiverordnung gegen umweltschädliches Verhalten und Lärmbelästigung, zum Schutz vor öffentlichen Beeinträchtigungen und über das Anbringen von Hausnummern in der Stadt Zwickau (PolVO)",
        "2023-09-29", "in der Stadt Zwickau (PolVO) vom 29.09.2023", "original",
        "City-wide police ordinance: on streets and in green spaces bans intrusive or aggressive begging, harassing "
        "others while drunk, staying there visibly intoxicated, and lying around or sleeping outside designated areas; "
        "alcohol banned on playgrounds and sports grounds.",
        ["a) aufdringlich oder aggressiv zu betteln",
         "auf hierfür nicht besonders freigegebenen Flächen zu lagern oder dort zu übernachten",
         "sich in einem erkennbaren Rauschzustand, hervorgerufen durch Alkohol oder andere berauschende"],
        in_force_from="2023-10-07", gem="14524330"),
    _mu("zwickau_akv_marienplatz", "14524", "SN", "Zwickau",
        "https://www.zwickau.de/media/downloads/image/01_buerger/ortsrecht/3_20_PolVO_Alkoholkonsums_03_08_26.pdf",
        "verordnung", "alkohol", "Zwickauer Ortsrecht 3.20 AKV-PolVO Marienplatz vom 03.08.2026 (Stadtrat 30.07.2026; in Kraft 04.08.2026 bis 03.08.2028)",
        "Polizeiverordnung der Stadt Zwickau über das Verbot des Alkoholkonsums im Bereich des Marienplatzes (AKV-PolVO Marienplatz)",
        "2026-08-03", "(AKV-PolVO Marienplatz) vom 03.08.2026", "original",
        "Alcohol ban zone (Marienplatz and adjoining streets): drinking or carrying alcohol to drink there is banned "
        "outside licensed outdoor dining on working days 15:00-23:00; valid 04.08.2026 to 03.08.2028.",
        ["Die Verbote in Absatz 2 gelten an Werktagen in der Zeit von 15:00 Uhr bis 23:00 Uhr",
         "Diese Polizeiverordnung tritt mit Beginn des 04.08.2026 in Kraft und mit Ablauf des 03.08.2028 außer Kraft"],
        in_force_from="2026-08-04", gem="14524330",
        ends_on='2028-08-04', ends_needle='Diese Polizeiverordnung tritt mit Beginn des 04.08.2026 in Kraft und mit Ablauf des 03.08.2028 außer Kraft'),
    # ---- batch 19: (b) for kreisangehörige cities covered for (a) in b18 ----
    _mu("aachen_strassenvo", "05334", "NW", "Aachen",
        "https://www.aachen.de/in-aachen-leben/politik-und-verwaltung/stadtrecht/recht-und-ordnung/321.pdf?cid=loj",
        "verordnung", "betteln,lagern,alkohol", "Aachener Stadtrecht 32.1 Aachener Straßenverordnung, Neuerlass vom 10.10.2024 (Ratsbeschluss 09.10.2024), gilt bis 10.10.2034",
        "Ordnungsbehördliche Verordnung zur Aufrechterhaltung der öffentlichen Sicherheit und Ordnung auf den Straßen und in den Anlagen in der Stadt Aachen (Aachener Straßenverordnung)",
        "2024-10-10", "Sie gilt bis zum Ablauf des 10.10.2034", "original",
        "Bans begging by actively addressing people or aggressive behaviour, organised and commercial begging and begging "
        "with children or animals; alcohol consumption that leads to aggressive or endangering behaviour; lagern in groups "
        "that regularly gather at the same places and obstruct passers-by; and lying around and staying overnight (das "
        "Lagern und Übernachten) in the covered areas. Re-enacted in 2024 (the 2004 ordinance as amended in 2019 is "
        "repealed), valid until 10.10.2034.",
        ["Betteln durch aktives Ansprechen bzw. aggressives Verhalten gegenüber der angesprochenen Person",
         "2. Alkoholkonsum, wenn es hierdurch zu aggressiven oder in sonstiger Weise gefährdenden Verhaltensweisen kommt",
         "4. Lagern in Personengruppen, wenn sich diese an denselben Orten regelmäßig ansammeln",
         "8. das Lagern und Übernachten",
         "Diese Verordnung tritt eine Woche nach dem Tage ihrer Verkündung in Kraft. Sie gilt bis zum Ablauf des 10.10.2034. Gleichzeitig tritt die Ordnungsbehördliche Verordnung", 'Sie gilt bis zum Ablauf des 10.10.2034'],
        gem="05334002",
        ends_on='2034-10-11', ends_needle='Sie gilt bis zum Ablauf des 10.10.2034'),
    _mu("dorsten_obvo", "05562", "NW", "Dorsten",
        "https://www.dorsten.de/_Resources/Persistent/f/5/7/8/f57878d12e499b82dab7dffe8d422ca70dc759ef/32%2005%20Ordnungsbeh%C3%B6rdliche%20Verordnung%20%C3%BCber%20die%20Aufrechterhaltung%20der%20%C3%B6ffentlichen%20Sicherheit.pdf",
        "verordnung", "lagern,alkohol", "Dorstener Ortsrecht 32 05 Ordnungsbehördliche Verordnung vom 10.04.2013, zuletzt geändert am 19.12.2019",
        "Ordnungsbehördliche Verordnung über die Aufrechterhaltung der öffentlichen Sicherheit und Ordnung im Gebiet der Stadt Dorsten",
        "2019-12-19", "Stand: 12/19", "consolidated",
        "General conduct rule on roads and in public facilities naming excessive alcohol consumption as a nuisance; bans "
        "setting up tents, caravans and vehicles in public facilities. No begging rule.",
        ["Ordnungsbehördliche Verordnung über die Aufrechterhaltung der öffentlichen Si cherheit und Ordnung im Gebiet der Stadt Dorsten vom 10.04.2013",
         "insbesondere durch übermäßigen Alkoholkonsum",
         "Das Ab- bzw. Aufstellen von Kraftfahrzeugen, Anhängern, Wohnwagen, Zelten und Verkaufswagen in Anlagen ist verboten"],
        gem="05562012"),
    _mu("castrop_stro", "05562", "NW", "Castrop-Rauxel",
        "https://www.castrop-rauxel.de/sites/default/files/2024-02/1-1_Stra%C3%9Fenordnung%202020.pdf",
        "verordnung", "betteln,lagern,alkohol", "Castrop-Rauxeler Ortsrecht 1-1 Straßenordnung (StrO) vom 8. Juli 2019 (Neufassung), 1. Änderung vom 14.08.2020",
        "Ordnungsbehördliche Verordnung zur öffentlichen Sicherheit und Ordnung im Gebiet der Stadt Castrop-Rauxel (Straßenordnung -StrO-)",
        "2020-08-14", "vom 8. Juli 2019, mit 1. Änderung vom 14.08.2020", "consolidated",
        "Bans staying overnight on roads and in public facilities (fine 25 EUR in the annexed catalogue), aggressive "
        "begging and begging with children (20 EUR), and drinking alcohol outdoors within sight of schools, kindergartens "
        "and youth facilities during opening hours (55 EUR).",
        ["1. Das Übernachten auf Straßen und in Anlagen ist nicht gestattet",
         "(aggressives Betteln), so wie das Betteln unter Beteiligung von Kindern (stilles Betteln) auf Straßen und in Anlagen ist nicht gestattet",
         "Absatz 3: Genuss von Alkohol pp. in Sichtweite von Schulen, Kindergärten u. ä."],
        gem="05562004"),
    _mu("arnsberg_obvo", "05958", "NW", "Arnsberg",
        "https://www.arnsberg.de/fileadmin/user_upload/Bilder_und_pdf-Dateien/1.0.2/ortsrecht/ordnungsbehoerdliche-verordnung.pdf",
        "verordnung", "lagern,alkohol", "Arnsberger Ortsrecht Ordnungsbehördliche Verordnung vom 19.10.2026",
        "Ordnungsbehördliche Verordnung über die Aufrechterhaltung der öffentlichen Sicherheit und Ordnung im Gebiet der Stadt Arnsberg",
        "2026-10-19", "im Gebiet der Stadt Arnsberg vom 19.10.2026", "original",
        "Bans sleeping in caravans, motorhomes or tents in public facilities and on roads outside approved areas; on "
        "children's playgrounds and kick-about pitches bans consuming goods allowed only from age 16 (such as tobacco or "
        "alcohol). No begging rule.",
        ["Das Nächtigen in Wohnwagen, Wohnmobilen, Zelten sowie das Abstellen der Vorgenannten und von Verkaufswagen in Anlagen und auf Verkehrsflächen außerhalb zugelassener",
         "Der Verzehr von Genussmitteln (wie z.B. Tabakwaren oder Alkohol), die nur Personen ab 16 Jahren oder älter erlaubt sind, ist verboten"],
        gem="05958004"),
    _mu("bocholt_obvo", "05554", "NW", "Bocholt",
        "https://www.bocholt.de/bocholt_media/fachbereiche/fb12/ortsrecht-satzungen/rechts-sicherheits-und-ordnungsverwaltung/ordnungsbehoerdliche-verordnung-der-stadt-bocholt-zur-aufrechterhaltung-der-oeffentlichen-sicherheit-und-ordnung-im-gebiet-der-stadt-bocholt.pdf?download=1",
        "verordnung", "alkohol", "Bocholter Ortsrecht 3.1 Ordnungsbehördliche Verordnung (SichuO) vom 19.05.2021, letzte Änderung 18.09.2024",
        "Ordnungsbehördliche Verordnung der Stadt Bocholt zur Aufrechterhaltung der öffentlichen Sicherheit und Ordnung im Gebiet der Stadt Bocholt",
        "2024-09-18", "letzte Änderung: 18.09.2024", "consolidated",
        "Bans consuming alcohol and other harmful substances on children's and youth playgrounds. No begging or lagern rule.",
        ["Auf Kinder- und Jugendspielplätzen ist der Konsum von Alkohol",
         "vom 19.05.2021, in Kraft getreten am 01.06.2021"],
        in_force_from="2021-06-01", gem="05554008"),
    _mu("hildesheim_sov", "03254", "NI", "Hildesheim",
        "https://www.stadt-hildesheim.de/downloads/datei/N2ZiMzBmYTgxMjU1Njc5YkFtV250Rm9TVjRONEF2UkJmVUZ3Y1B3bzlJQk83Ui94ekNZbHVyUTdlN2hwelcrcUFSZjNxdFN1Z0ZWTkR3dEpzdFpOWk53Q0ZjYVZtL09DVlFVVXlDZXE1VTJwUVEwZXFKTDR3YXpJdXdZMkpOMnYzalJBS29BcGZ1OVh4U29US0Q4MzdXRnlBZExjaHZNRU1LQXZOcy9EQ0pyRTV4alkrcklzODNuMDQ5WWNIWlg1ZjdwL3NLT3hWdVNncitjbkJOc3lVbTlZY0x4T2ZhZGNvcTUyODhhcTVKOHovaFFGZ0lqUnNleldFNUU9",
        "verordnung", "alkohol", "Hildesheimer Stadtrecht 10.01 Verordnung über die Aufrechterhaltung der öffentlichen Sicherheit und Ordnung vom 15.05.2018 (Amtsblatt Landkreis Hildesheim 2018, S. 410) i.d.F. vom 12.07.2021",
        "Verordnung zur Aufrechterhaltung der öffentlichen Sicherheit und Ordnung in der Stadt Hildesheim",
        "2021-07-12", "in der Fassung vom 12.07.2021 (1. Änderung vom 12.07.2021, Amtsblatt Landkreis 2021, S. 397, in Kraft seit 15.07.2021)", "consolidated",
        "Bans drinking alcohol on playgrounds and kick-about pitches. No begging or lagern rule. In force since 31.05.2018 "
        "(replacing the 2001 ordinance), so within the 20-year limit of § 61 NPOG.",
        ["Es ist verboten, auf Spiel- und Bolzplätzen",
         "4. Alkohol oder alkoholhaltige Getränke zu konsumieren",
         "(Amtsblatt Landkreis Hildesheim 2018, S. 410, in Kraft seit 31.05.2018)",
         "Gleichzeitig tritt die Verordnung zur Aufrechterhaltung der öffentlichen Sicherheit und Ordnung in der Stadt Hildesheim vom 26.03.2001 in der Fassung vom 09.07.2012 außer Kraft"],
        in_force_from="2018-05-31", gem="03254021",
        note="Stadtrecht download URL is a session-independent token link from the 10 Recht/Ordnung list (stable across fetches)"),
]
_dupes = sorted({m["key"] for m in MUNI if [x["key"] for x in MUNI].count(m["key"]) > 1})
assert not _dupes, f"duplicate municipal keys: {_dupes}"


KIND_LABEL = {"consolidated": "consolidated text", "original": "original promulgated text", "plan": "policy document"}


def _de_variants(v):
    """German rendering candidates of a fee value (5.22 -> '5,22'; 50.0 -> '50,00' / '50')."""
    out = {f"{v:.2f}".replace(".", ","), f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")}
    if float(v).is_integer():
        out.add(str(int(v)))
    return out


def _gemeinde_check(conn, m):
    """None if m['gem'] is a Gemeinde in the Lead's geo_gemeinde (or that table is still empty); else a problem.
    This module never writes geo_* rows for Gemeinden: geography belongs to the Lead's geo domains."""
    if conn.execute("SELECT 1 FROM geo_gemeinde LIMIT 1").fetchone() is None:
        return None
    row = conn.execute("SELECT name FROM geo_gemeinde WHERE ags=?", (m["gem"],)).fetchone()
    if row is None:
        return f"{m['key']}:gemeinde-ags-unknown:{m['gem']}"
    want = m["city"].split(" (")[0].split()[0].lower()
    if want not in row[0].lower():
        return f"{m['key']}:gemeinde-name-mismatch:{m['gem']}={row[0]!r}"
    return None


# Sources this module no longer uses: their law rows, metrics and source rows are deleted on the next run.
DROPPED_SOURCES = {
    "https://d2vw8mc5mcb3gm.cloudfront.net/fileadmin/chemnitz/media/rathaus/satzungen/50_760.pdf":
        "Chemnitz: www.chemnitz.de refuses the project UA, so its CDN copy is not used in automation (Lead, 2026-11-21)",
}


def _drop_sources(conn, counts):
    n = 0
    for url in DROPPED_SOURCES:
        for (sid,) in conn.execute("SELECT id FROM source WHERE domain=? AND url=?", (DOMAIN, url)).fetchall():
            for (lid,) in conn.execute("SELECT id FROM law WHERE source_id=?", (sid,)).fetchall():
                conn.execute(f"DELETE FROM {DOMAIN}_law_meta WHERE law_id=?", (lid,))
            conn.execute("DELETE FROM law WHERE source_id=?", (sid,))
            conn.execute("DELETE FROM metric WHERE source_id=?", (sid,))
            conn.execute("DELETE FROM source WHERE id=?", (sid,))
            n += 1
    counts["sources_dropped"] = n


# Robots audit 2026-11-23 (longest-match rules, as fetch() now applies them): these sources were fetched in earlier
# batches although the host's robots.txt disallows the path for every agent (darmstadt.de: Disallow /fileadmin;
# landshut.de: Disallow /sites/default/files/). The old probe used urllib.robotparser, whose first-match order let an
# earlier "Allow: /" win. They are no longer ingested; they stay listed in MUNI so ingest_law does not prune rows a
# previous run wrote (pruning needs a Lead allowlist line) -- the Lead decides on those rows.
# Lead 2026-11-23: Darmstadt x2 and Landshut Obdach are now read from manual archives (local=, MANUAL_ARCHIVE);
# Landshut SiSa stays withdrawn until its extra source (Sondernutzungssatzung) can also be read from the archive.
# b19: Landshut SiSa and its extra source (Sondernutzungssatzung) are read from the manual archive too (extra sources
# accept local=), so nothing is withdrawn any more.
ROBOTS_WITHDRAWN = {}


def ingest_muni(conn, counts, problems):
    _drop_sources(conn, counts)
    gem_empty = conn.execute("SELECT 1 FROM geo_gemeinde LIMIT 1").fetchone() is None
    counts["muni_geo_unchecked"] = len(MUNI) if gem_empty else 0
    # schema 3: municipal rows moved from the Kreis AGS to the Gemeinde AGS -- drop this domain's old Kreis-level
    # fee metrics (law rows are pruned via `listed` in ingest_law)
    fee_names = sorted({f[0] for m in MUNI for f in m["fees"]})
    if fee_names:
        counts["muni_fee_moved"] = conn.execute(
            f"DELETE FROM metric WHERE entity_type='kreis' AND metric IN ({','.join('?' * len(fee_names))}) "
            "AND source_id IN (SELECT id FROM source WHERE domain=?)", (*fee_names, DOMAIN)).rowcount
    for m in MUNI:
        if m["key"] in ROBOTS_WITHDRAWN:
            problems.append(f"{m['key']}:robots-withdrawn")
            counts["muni_robots_withdrawn"] = counts.get("muni_robots_withdrawn", 0) + 1
            continue
        bad_geo = _gemeinde_check(conn, m)
        if bad_geo:
            problems.append(bad_geo)
            continue
        needles = m["needles"] + [q for _, _, _, q, _, _ in m["fees"]]
        bad = [f for f in m["fees"] if not any(c in f[3] for c in _de_variants(f[1]))]
        if bad:
            problems.append(f"{m['key']}:fee-value-not-in-quote:{bad[0][0]}")
            continue
        sid = _fetch_verified(conn, m["key"], m["url"], m["title"], muni_publisher(m["city"]), needles, problems,
                              local=m.get("local"), as_of_text=m["as_of_text"], license=m["lic"],
                              extra=m["extra"], extra_license=m["lic"], version_url=m["version_url"])
        if sid is None:
            continue
        topics = ", ".join(MUNI_TOPICS[t] for t in m["topic"].split(","))
        ver = (f"[{KIND_LABEL[m['text_kind']]}; as of {m['as_of']}" + (f"; {m['note']}" if m.get("note") else "")
               + f"; {m['city']}, Gemeinde AGS {m['gem']}] ")
        if m.get("lapsed_on"):
            ver = (f"[außer Kraft seit {lapsed_label(m['lapsed_on'])}: {m['lapsed_basis']}; deciding sentence: "
                   f"\u201e{m['lapsed_needle'][:160]}\u201c] " + ver)
            counts["muni_lapsed"] = counts.get("muni_lapsed", 0) + 1
        elif m.get("ends_on"):
            ver = (f"[befristet, außer Kraft ab {lapsed_label(m['ends_on'])}; end clause: "
                   f"\u201e{m['ends_needle'][:160]}\u201c] " + ver)
            counts["muni_fixed_term"] = counts.get("muni_fixed_term", 0) + 1
        # a row whose citation/title was corrected (e.g. re-read as a new ordinance, Lead b20) keeps its law id:
        # rename it in place by its stable law_key instead of letting the prune in ingest_law drop and re-add it
        old = conn.execute(f"SELECT lm.law_id FROM {DOMAIN}_law_meta lm JOIN law l ON l.id=lm.law_id WHERE lm.law_key=? "
                           "AND l.jurisdiction=? AND (l.citation<>? OR l.title<>?)",
                           (m["key"], m["gem"], m["citation"], m["title"])).fetchone()
        if old and not conn.execute("SELECT 1 FROM law WHERE jurisdiction=? AND citation=? AND title=?",
                                    (m["gem"], m["citation"], m["title"])).fetchone():
            conn.execute("UPDATE law SET citation=?, short_name=?, title=? WHERE id=?",
                         (m["citation"], m["citation"], m["title"], old[0]))
            counts["muni_renamed"] = counts.get("muni_renamed", 0) + 1
        upsert(conn, "law", {"jurisdiction": m["gem"], "jurisdiction_ags": m["gem"], "kind": m["kind"],
                             "topic": m["topic"], "short_name": m["citation"], "citation": m["citation"],
                             "title": m["title"], "summary": f"{ver}{topics}: {m['summary']} "
                             f"[verified phrase: \u201e{m['needles'][0][:120]}\u201c]",
                             "status": "lapsed" if m.get("lapsed_on") else "in_force", "year": int(m["as_of"][:4]),
                             "in_force_from": m.get("in_force_from"), "in_force_to": m.get("lapsed_on") or m.get("ends_on"),
                             "url": m["url"], "source_id": sid}, keys=["jurisdiction", "citation", "title"])
        law_id = conn.execute("SELECT id FROM law WHERE jurisdiction=? AND citation=? AND title=?",
                              (m["gem"], m["citation"], m["title"])).fetchone()[0]
        if not (m.get("lapsed_on") or m.get("ends_on")):
            # upsert skips None, so a status reversed to in force (Coburg, b20) must drop its old lapse date explicitly
            conn.execute("UPDATE law SET in_force_to=NULL WHERE id=? AND in_force_to IS NOT NULL", (law_id,))
        conn.execute(f"INSERT OR REPLACE INTO {DOMAIN}_law_meta(law_id,law_key,as_of,as_of_text,text_kind,note,local_file,"
                     "ocr,ocr_tool,needs_spot_check,version_url) VALUES(?,?,?,?,?,?,?,0,NULL,0,?)",
                     (law_id, m["key"], m["as_of"], m["as_of_text"], m["text_kind"], m.get("note"), m.get("local"), m["version_url"] or m["url"]))
        counts["law"] += 1
        counts["muni_law"] += 1
        for metric, value, unit, quote, loc, year in m["fees"]:
            upsert(conn, "metric", {"entity_type": "gemeinde", "entity_id": m["gem"], "metric": metric, "value": float(value),
                                    "einheit": unit, "year": year or int(m["as_of"][:4]), "is_est": 0,
                                    "anmerkung": f"{m['citation']} ({m['city']}), {loc}; as of {m['as_of']}",
                                    "quote": " ".join(quote.split()), "locator": loc, "source_id": sid},
                   keys=["entity_type", "entity_id", "metric", "year"])
            counts["muni_fee"] += 1


# Lead review 2026-11-21, narrowed 2026-11-23 (§ 5 UrhG only for statutes, Erlasse and official gazettes): only the
# Saxon Verwaltungsvorschrift (listed in the SächsABl. VwV register) keeps redistribute_fulltext=1; all other plans,
# including the HH and SH Drucksachen, are rights reserved (0).
PLAN_GEMEINFREI = {"sn_empfehlungen2021"}


def ingest_law(conn, counts) -> list[str]:
    problems = []
    conn.execute(f"""CREATE TABLE IF NOT EXISTS {DOMAIN}_law_meta (
        law_id INTEGER PRIMARY KEY, law_key TEXT UNIQUE, as_of TEXT, as_of_text TEXT, text_kind TEXT NOT NULL,
        note TEXT, local_file TEXT, ocr INTEGER NOT NULL DEFAULT 0, ocr_tool TEXT,
        needs_spot_check INTEGER NOT NULL DEFAULT 0, version_url TEXT)""")
    for key, url, jur, topic, cit, title, summary, status, year, pub, needles in LAW:
        m = LAW_META[key]
        lic = PLAN_LIC.get(key) or (LIC_PLAN if m["kind"] == "plan" else None)
        sid = _fetch_verified(conn, key, url, title, pub, needles, problems, local=m.get("local"),
                              extra=m.get("extra", ()), as_of_text=m.get("as_of_text"), version_url=m.get("version_url"),
                              license=lic, extra_license=lic)
        if sid is None:
            continue
        if m["kind"] == "plan" and key not in PLAN_GEMEINFREI:
            # plans are no statutes: facts, own summary and a short quote only, never the full text -- this also
            # holds for a plan's version / extra sources (Lead 2026-11-23: the BW Förderaufruf had defaulted to § 5)
            side = [u for u in [m.get("version_url")] + [x[0] for x in m.get("extra", ())] if u and u != url]
            conn.execute("UPDATE source SET redistribute_fulltext=0 WHERE id=?", (sid,))
            for u in side:
                conn.execute("UPDATE source SET redistribute_fulltext=0 WHERE domain=? AND url=?", (DOMAIN, u))
        ver = f"[{KIND_LABEL[m['kind']]}; as of {m['as_of'] or 'n/a'}" + (f"; {m['note']}" if m.get("note") else "") + "] "
        upsert(conn, "law", {"jurisdiction": jur, "topic": topic, "citation": cit, "title": title,
                             "summary": f"{ver}{summary} [verified phrase: \u201e{needles[0][:120]}\u201c]",
                             "status": status, "year": year, "url": url, "source_id": sid},
               keys=["jurisdiction", "citation", "title"])
        law_id = conn.execute("SELECT id FROM law WHERE jurisdiction=? AND citation=? AND title=?", (jur, cit, title)).fetchone()[0]
        conn.execute(f"INSERT OR REPLACE INTO {DOMAIN}_law_meta(law_id,law_key,as_of,as_of_text,text_kind,note,local_file,"
                     "ocr,ocr_tool,needs_spot_check,version_url) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                     (law_id, key, m["as_of"], m.get("as_of_text"), m["kind"], m.get("note"), m.get("local"),
                      1 if m.get("ocr_tool") else 0, m.get("ocr_tool"), 1 if m.get("ocr_tool") else 0,
                      m.get("version_url") or url))
        counts["law"] += 1
    ingest_muni(conn, counts, problems)
    # drop this domain's law rows whose (jurisdiction, citation, title) is no longer listed in LAW (e.g. the
    # Nds. SOG row renamed to NPOG). Rows merely skipped this run (fetch failure, missing manual file) are kept.
    listed = {(x[2], x[4], x[5]) for x in LAW} | {(m["gem"], m["citation"], m["title"]) for m in MUNI}
    counts["law_pruned"] = 0
    for lid, jur, cit, title in conn.execute("SELECT l.id, l.jurisdiction, l.citation, l.title FROM law l JOIN source s "
                                             "ON s.id=l.source_id WHERE s.domain=?", (DOMAIN,)).fetchall():
        if (jur, cit, title) not in listed:
            conn.execute("DELETE FROM law WHERE id=?", (lid,))
            conn.execute(f"DELETE FROM {DOMAIN}_law_meta WHERE law_id=?", (lid,))
            counts["law_pruned"] += 1
    for key, url, court, cit, date, land, summary, needles in COURT:
        sid = _fetch_verified(conn, key, url, cit, court, needles, problems, license=COURT_LIC.get(key, LIC_COURT))
        if sid is None:
            continue
        upsert(conn, "doc", {"kind": "court", "title": cit, "url": url, "herausgeber": court, "veroeffentlicht": date,
                             "land": land, "zusammenfassung": summary, "source_id": sid}, keys=["url"])
        counts["court"] += 1
    for name, murl in MANUAL_ARCHIVE.items():
        if not (common._cow(common.RAW / DOMAIN / name)).exists():
            problems.append(f"manual-archive-pending:{name}")
    return problems


def press_crosscheck(conn, counts) -> list[str]:
    """Fetch + archive the annual press releases; compare their rounded total with 22971-0001."""
    import re
    out = []
    for year, url in PRESS.items():
        try:
            html = fetch(url, domain=DOMAIN, force=_FORCE[0]).decode("utf-8", "replace")
        except Exception as e:
            raise GenesisShapeError(f"press release {year} could not be fetched ({url}): {e!r:.120}") from e
        source_id_for(conn, url, DOMAIN, title=f"Destatis Pressemitteilung, untergebrachte wohnungslose Personen {year}",
                      publisher=PUBLISHER, license=LICENSE)
        txt = re.sub(r"<[^>]+>", " ", html).replace("\u00a0", " ").replace("&nbsp;", " ").replace("&#160;", " ")
        m = re.search(r"Zum Stichtag 31\. Januar %d .{0,160}?(\d{3})\s(\d{3}) Personen" % year, txt, re.S)
        exact = conn.execute("SELECT value FROM metric WHERE entity_type='de' AND entity_id='DE' AND metric=? "
                             "AND year=?", (BASE, year)).fetchone()
        rounded = int(m.group(1) + m.group(2)) if m else None
        check_press(year, rounded, exact[0] if exact else None)  # raises on missing match or > tolerance
        counts["press_ok"] += 1
        out.append(f"{year}:{rounded}~{exact[0]:.0f}:ok")
    return out


def run(conn, cfg) -> dict:
    cfg = cfg or {}
    _FORCE[0] = bool(cfg.get("refresh"))  # re-download instead of using data/raw cache
    conn.executescript(CELL_DDL)
    counts = defaultdict(int)
    tables = list(TABLES)
    if cfg.get("no_kreise"):
        tables.remove("22971-0080")
    kreis_problems = []
    if "22971-0080" in tables:
        kreis_evidence(conn, kreis_problems)
    for code in tables:
        counts[code] = ingest_table(conn, code, counts)
        conn.commit()
    press = press_crosscheck(conn, counts)
    est_problems = [] if cfg.get("no_estimates") else ingest_estimates(conn, counts)
    land_problems = [] if cfg.get("no_estimates") else ingest_nrw_kreise(conn, counts)
    law_problems = [] if cfg.get("no_law") else ingest_law(conn, counts)
    # rights-reserved sources (reports, plans, Drucksachen, press kits): never redistribute the full text
    conn.execute("UPDATE source SET redistribute_fulltext=0 WHERE domain=? AND license LIKE ? AND redistribute_fulltext<>0",
                 (DOMAIN, f"{RIGHTS_RESERVED}%"))
    conn.commit()
    counts["pit"] = conn.execute("SELECT COUNT(*) FROM zaehlung p JOIN source s ON s.id=p.source_id "
                                 "WHERE s.domain=?", (DOMAIN,)).fetchone()[0]
    notes = (f"pit={counts['pit']} est_metric={counts['est_metric']} est_skipped={counts['est_skipped']} "
             f"est_problems={est_problems} land_metric={counts['land_metric']} land_problems={land_problems} law={counts['law']} law_pruned={counts['law_pruned']} court={counts['court']} law_problems={law_problems} muni_law={counts['muni_law']} muni_fee={counts['muni_fee']} muni_lapsed={counts.get('muni_lapsed', 0)} muni_fixed_term={counts.get('muni_fixed_term', 0)} muni_renamed={counts.get('muni_renamed', 0)} kreis_folded={counts['kreis_folded']} kreis_problems={kreis_problems} press_crosscheck=[{' '.join(press)}] " f"metric={counts['metric']} cells={counts['cells']} geo_written={counts['geo']} geo_absent={sorted(set(counts.get('geo_absent') or []))} muni_gemeinde_unchecked={counts.get('muni_geo_unchecked', 0)} muni_kreis_fee_rows_moved={counts.get('muni_fee_moved', 0)} muni_manual_wanted={len(MUNI_MANUAL_WANTED)} sources_dropped={counts.get('sources_dropped', 0)} "
             f"suppressed_margins={counts['suppressed']} "
             + " ".join(f"{c}:{counts[c]}" for c in tables))
    return {"rows": counts["metric"] + counts["geo"] + counts["pit"] + counts["est_metric"] + counts["land_metric"] + counts["law"] + counts["court"], "notes": notes,
            "sources": [(f"{API}/tables/{c}/data", LICENSE) for c in tables]
                       + [(u, LICENSE) for u in PRESS.values()]
                       + [(d[0], d[3]) for d in DOCS.values()]}



def _shape_tests() -> int:
    """Feed malformed copies of the cached 22971-0001/-0050 cubes to the guard; every one must raise."""
    import copy
    good = {c: (_get_json(f"{API}/tables/{c}/data"), _get_json(f"{API}/tables/{c}/structure"))
            for c in ("22971-0001", "22971-0050")}
    for c, (d, st) in good.items():
        validate_cube(c, d, st)  # the real cube must pass

    def m_missing_value(d): del d["data"][0]["value"]
    def m_missing_dim(d):
        ds = d["data"][0]; i = ds["id"].index("STAG"); ds["id"].pop(i); ds["size"].pop(i); del ds["dimension"]["STAG"]
    def m_renamed_dim(d):
        ds = d["data"][0]; ds["id"][ds["id"].index("ALT026")] = "ALT099"
    def m_stag_extra(d):
        ix = d["data"][0]["dimension"]["STAG"]["category"]["index"]; ix["2026-06-30"] = ix.pop("2026-01-31")
    def m_stag_missing(d):
        ds = d["data"][0]; ix = ds["dimension"]["STAG"]["category"]["index"]; ix.pop("2022-01-31")
    def m_short_values(d): d["data"][0]["value"] = d["data"][0]["value"][:-7]
    def m_zero_cells(d):
        ds = d["data"][0]; ds["value"] = [None] * len(ds["value"]); ds["status"] = ["."] * len(ds["value"])
    def m_empty(d): d["data"] = []
    def m_category(d):
        ix = d["data"][0]["dimension"]["GES02"]["category"]["index"]; ix["GESD"] = ix.pop("UNBEKANNT")
    def m_land_lost(d):
        ds = d["data"][0]; ds["status"] = ["." if (n % 16) == 0 else f for n, f in enumerate(ds["status"])]
    cases = [("22971-0001", f) for f in (m_missing_value, m_missing_dim, m_renamed_dim, m_stag_extra, m_stag_missing,
                                          m_short_values, m_zero_cells, m_empty, m_category)]
    cases.append(("22971-0050", m_land_lost))
    n = 0
    for code, mut in cases:
        d = copy.deepcopy(good[code][0])
        mut(d)
        try:
            validate_cube(code, d, good[code][1])
        except GenesisShapeError as e:
            n += 1
            print(f"   raised as expected [{mut.__name__}]: {str(e)[:110]}")
            continue
        raise AssertionError(f"malformed fixture {mut.__name__} was NOT rejected")
    # end-to-end: ingest_table must raise before touching the DB (conn=None proves nothing is written)
    bad = copy.deepcopy(good["22971-0001"][0]); m_zero_cells(bad)
    orig = globals()["_get_json"]
    globals()["_get_json"] = lambda url: bad if url.endswith("/data") else good["22971-0001"][1]
    try:
        ingest_table(None, "22971-0001", defaultdict(int))
        raise AssertionError("ingest_table accepted an all-empty cube")
    except GenesisShapeError as e:
        n += 1
        print(f"   ingest_table raised as expected: {str(e)[:110]}")
    finally:
        globals()["_get_json"] = orig
    for args in ((2024, None, 439465.0), (2024, 300000, 439465.0), (2024, 439000, None)):
        try:
            check_press(*args)
            raise AssertionError(f"check_press{args} did not raise")
        except GenesisShapeError as e:
            n += 1
            print(f"   check_press raised as expected: {str(e)[:110]}")
    check_press(2024, 439000, 439465.0)
    return n


def _selftest(conn):
    q = lambda s, *a: conn.execute(s, a).fetchall()
    print(f"[selftest] shape guard: {_shape_tests()} malformed fixtures rejected, real cubes accepted")
    print("[selftest] metric rows by level:",
          [tuple(r) for r in q("SELECT entity_type, COUNT(*) FROM metric WHERE metric LIKE 'housed_homeless%' "
                               "AND entity_type IN ('de','land','kreis') GROUP BY 1")])
    print("[selftest] national totals (22971-0001):")
    nat = {r[0]: r[1] for r in q("SELECT year, value FROM metric WHERE entity_type='de' AND metric=? ORDER BY year", BASE)}
    for y, v in nat.items():
        lsum = q("SELECT SUM(value) FROM metric WHERE entity_type='land' AND metric=? AND year=?", BASE, y)[0][0]
        ksum = q("SELECT SUM(value), COUNT(*) FROM metric WHERE entity_type='kreis' AND metric=? AND year=?", BASE, y)[0]
        print(f"   {y}: DE={v:,.0f}  sum(Länder)={lsum or 0:,.0f}  sum(Kreise)={ksum[0] or 0:,.0f} over {ksum[1]} Kreise")
        assert lsum is None or abs(lsum - v) <= 16 * 5, "Land sum deviates more than rounding allows"
        sex = q("SELECT SUM(value) FROM metric WHERE entity_type='de' AND year=? AND metric IN (?,?,?)",
                y, f"{BASE}__male", f"{BASE}__female", f"{BASE}__sex_unknown")[0][0]
        assert sex is None or abs(sex - v) <= 15, "sex breakdown does not add up"
    print("[selftest] pit rows by kind:", [tuple(r) for r in q(
        "SELECT geo_kind, COUNT(*), MIN(berichtsjahr), MAX(berichtsjahr) FROM zaehlung p JOIN source s ON s.id=p.source_id "
        "WHERE s.domain=? GROUP BY 1", DOMAIN)])
    print("[selftest] 3 sample pit rows:")
    for r in q("SELECT p.*, s.url FROM zaehlung p JOIN source s ON s.id=p.source_id WHERE s.domain=? "
               "ORDER BY RANDOM() LIMIT 3", DOMAIN):
        print("  ", {k: r[k] for k in r.keys() if r[k] is not None})
    print("[selftest] estimates (is_est=1) by metric family:", [tuple(r) for r in q(
        "SELECT substr(metric,1,instr(metric||'_','_')-1)||'_*', entity_type, COUNT(*), SUM(is_est) FROM metric m "
        "JOIN source s ON s.id=m.source_id WHERE s.domain=? AND (metric LIKE 'wb_%' OR metric LIKE 'bagw_%') "
        "GROUP BY 1,2", DOMAIN)])
    for r in q("SELECT metric, year, value, is_est FROM metric WHERE entity_type='de' AND metric IN "
               "('wb_unsheltered','wb_hidden','wb_total_homeless','bagw_homeless_year','bagw_unsheltered_year') "
               "ORDER BY metric, year"):
        print("   ", tuple(r))
    bad = q("SELECT COUNT(*) FROM zaehlung p JOIN source s ON s.id=p.source_id WHERE s.domain=? AND s.url NOT LIKE "
            "'https://genesis.destatis.de/%'", DOMAIN)[0][0]
    assert bad == 0, "pit must only carry Destatis rows"
    print("[selftest] part 3 Länder/city counts:", [tuple(r) for r in q(
        "SELECT metric, entity_type, COUNT(*), MIN(year), MAX(year), SUM(is_est) FROM metric m JOIN source s "
        "ON s.id=m.source_id WHERE s.domain=? AND (metric LIKE 'nrw_%' OR metric LIKE 'be_%') GROUP BY 1,2", DOMAIN)])
    for y in range(2015, 2025):
        land = q("SELECT value FROM metric WHERE entity_type='land' AND entity_id='05' AND metric='nrw_homeless_0630' "
                 "AND year=?", y)
        ks = q("SELECT SUM(value), COUNT(*) FROM metric WHERE entity_type='kreis' AND metric='nrw_homeless_0630' "
               "AND year=?", y)[0]
        if land and ks[1]:
            # the report rounds Kreis cells to 5 from 2021 on, so allow 53 x 2 persons of rounding drift
            assert abs(land[0][0] - ks[0]) <= 110, f"NRW {y}: Kreis sum {ks[0]} vs Land {land[0][0]}"
            print(f"   NRW {y}: Land={land[0][0]:,.0f} sum(Kreise)={ks[0]:,.0f} over {ks[1]}")
    koeln = q("SELECT value FROM metric WHERE entity_type='kreis' AND entity_id='05315' AND metric='nrw_homeless_0630' "
              "AND year=2024")
    assert koeln and koeln[0][0] == 10230, "Köln 2024 should read 10 230 (Tab. 11, p. 26)"
    gone = q("SELECT (SELECT COUNT(*) FROM metric WHERE entity_type='kreis' AND entity_id='16056') + "
             "(SELECT COUNT(*) FROM zaehlung WHERE geo_ags='16056') + (SELECT COUNT(*) FROM geo_kreis WHERE ags='16056')")[0][0]
    assert gone == 0, "dissolved 16056 must be folded into 16063"
    wb = q("SELECT berichtsjahr, untergebracht FROM zaehlung WHERE geo_ags='16063' ORDER BY berichtsjahr")
    print("[selftest] Wartburgkreis 16063 sheltered (2022 incl. former 16056):", [tuple(r) for r in wb])
    if wb:
        assert dict((r[0], r[1]) for r in wb).get(2022) == 20, "16063 2022 should be 10 + 10 (16056)"
    for ags in sorted(KREIS_DASH_ALL):
        r = q("SELECT COUNT(*), MAX(untergebracht) FROM zaehlung WHERE geo_ags=? AND geo_kind='kreis'", ags)[0]
        print(f"[selftest] {ags} pit rows={r[0]} max sheltered={r[1]}")
        assert r[0] in (0, 5) and (r[1] or 0) == 0
    hanau = [r[0] for r in q("SELECT berichtsjahr FROM zaehlung WHERE geo_ags='06415'")]
    assert all(y >= 2026 for y in hanau), "Hanau has no Kreis rows before 2026"
    print("[selftest] Kreise per Stichtag:", [tuple(r) for r in q(
        "SELECT berichtsjahr, COUNT(*) FROM zaehlung p JOIN source s ON s.id=p.source_id WHERE s.domain=? AND geo_kind='kreis' "
        "GROUP BY 1", DOMAIN)])
    print("[selftest] law rows by topic:", [tuple(r) for r in q(
        "SELECT topic, COUNT(*), GROUP_CONCAT(jurisdiction) FROM law l JOIN source s ON s.id=l.source_id "
        "WHERE s.domain=? GROUP BY 1", DOMAIN)])
    print("[selftest] court docs:", [tuple(r) for r in q(
        "SELECT d.title FROM doc d JOIN source s ON s.id=d.source_id WHERE s.domain=? AND d.kind='court'", DOMAIN)])
    # schema 3: AGS-only metric geography, municipal rows on the Gemeinde AGS, no geo rows of our own
    bad_ags = q("SELECT COUNT(*) FROM metric m JOIN source s ON s.id=m.source_id WHERE s.domain=? AND ("
                "(entity_type='land' AND NOT (length(entity_id)=2 AND entity_id GLOB '[01][0-9]')) OR "
                "(entity_type='kreis' AND NOT (length(entity_id)=5 AND entity_id GLOB '[01][0-9][0-9][0-9][0-9]')) OR "
                "(entity_type='gemeinde' AND NOT (length(entity_id)=8 AND entity_id GLOB '[01][0-9][0-9][0-9][0-9][0-9][0-9][0-9]')))",
                DOMAIN)[0][0]
    assert bad_ags == 0, f"{bad_ags} metric rows without a proper AGS"
    fee_names = sorted({f[0] for m in MUNI for f in m["fees"]})
    fee_geo = [tuple(r) for r in q("SELECT entity_type, length(entity_id), COUNT(*) FROM metric m JOIN source s ON "
                                   "s.id=m.source_id WHERE s.domain=? AND metric IN (" + ",".join("?" * len(fee_names))
                                   + ") GROUP BY 1, 2", DOMAIN, *fee_names)]
    assert all(t == "gemeinde" and n == 8 for t, n, _ in fee_geo), f"municipal fee metrics not on Gemeinde AGS: {fee_geo}"
    muni_jur = {(m["gem"], m["citation"], m["title"]) for m in MUNI}
    jur_bad = [r[0] for r in q("SELECT l.jurisdiction, l.jurisdiction_ags, l.citation, l.title FROM law l JOIN source s "
                               "ON s.id=l.source_id WHERE s.domain=?", DOMAIN)
               if (r[0], r[2], r[3]) in muni_jur and not (len(r[0]) == 8 and r[0] == r[1])]
    assert not jur_bad, f"municipal law rows not on the Gemeinde AGS: {jur_bad}"
    own_geo = sum(q(f"SELECT COUNT(*) FROM {t} g JOIN source s ON s.id=g.source_id WHERE s.domain=?", DOMAIN)[0][0]
                  for t in ("geo_land", "geo_kreis", "geo_gemeinde"))
    assert own_geo == 0, f"{own_geo} geo rows owned by {DOMAIN}"
    if q("SELECT COUNT(*) FROM geo_gemeinde")[0][0]:
        orphan = q("SELECT COUNT(*) FROM metric m JOIN source s ON s.id=m.source_id LEFT JOIN geo_gemeinde g ON "
                   "g.ags=m.entity_id WHERE s.domain=? AND m.entity_type='gemeinde' AND g.ags IS NULL", DOMAIN)[0][0]
        assert orphan == 0, f"{orphan} Gemeinde metrics without a geo_gemeinde row"
    print(f"[selftest] schema 3: metric AGS ok; municipal fee metrics {fee_geo}; municipal law rows on Gemeinde AGS; "
          f"own geo rows {own_geo}")
    nolaw = q("SELECT COUNT(*) FROM law l LEFT JOIN source s ON s.id=l.source_id WHERE s.id IS NULL AND l.citation "
              "IN (" + ",".join("?" * len(LAW)) + ")", *[x[4] for x in LAW])[0][0]
    assert nolaw == 0, "every law row must carry a source_id"
    print("[selftest] law versions:")
    for r in q(f"SELECT l.jurisdiction, l.citation, m.text_kind, m.as_of, m.local_file, m.needs_spot_check FROM law l "
               f"JOIN source s ON s.id=l.source_id LEFT JOIN {DOMAIN}_law_meta m ON m.law_id=l.id WHERE s.domain=? "
               "ORDER BY l.jurisdiction, l.citation", DOMAIN):
        print("   ", tuple(r))
        assert r["text_kind"] in ("consolidated", "original", "plan"), f"law row without version meta: {tuple(r)}"
    stale = q("SELECT COUNT(*) FROM law l JOIN source s ON s.id=l.source_id WHERE s.domain=? AND l.citation LIKE "
              "'%Nds. SOG%'", DOMAIN)[0][0]
    assert stale == 0, "renamed Nds. SOG row must be pruned"
    print("[selftest] 3 sample metric rows:")
    for r in q("SELECT m.entity_type, m.entity_id, COALESCE(k.name, l.name) AS name, m.metric, m.year, m.value, "
               "m.is_est, s.url FROM metric m JOIN source s ON s.id=m.source_id "
               "LEFT JOIN geo_kreis k ON m.entity_type='kreis' AND k.ags=m.entity_id "
               "LEFT JOIN geo_land l ON m.entity_type='land' AND l.ags=m.entity_id "
               "WHERE s.domain=? ORDER BY RANDOM() LIMIT 3", DOMAIN):
        print("  ", dict(r))


def _parse_args(argv):
    """Strict CLI: unknown flags exit non-zero (argparse exits 2)."""
    import argparse
    ap = argparse.ArgumentParser(prog=f"python3 -m ingest.domains.{DOMAIN}", allow_abbrev=False,
                                 description="Counts & Law module; scratch DBs only (the Lead uses ingest.run).")
    ap.add_argument("--db", help="scratch SQLite path (required unless --shape-test); never data/atlas.db")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--shape-test", action="store_true", help="offline GENESIS shape guard, no DB")
    ap.add_argument("--no-kreise", action="store_true")
    ap.add_argument("--no-estimates", action="store_true")
    ap.add_argument("--no-law", action="store_true")
    ap.add_argument("--refresh", action="store_true")
    return ap.parse_args(argv)


def _scratch_db(path_str):
    """Resolve --db and refuse anything that is (or links to) the real atlas DB."""
    from pathlib import Path
    if not path_str:
        sys.exit(f"[{DOMAIN}] refusing to run without --db <scratch path> (use ingest.run for the real DB)")
    p = Path(path_str).expanduser().resolve()
    real = (common.ROOT / "data" / "atlas.db").resolve()
    if p.name == "atlas.db" or p == real or (p.exists() and real.exists() and p.samefile(real)):
        sys.exit(f"[{DOMAIN}] refusing to write {p}")
    return p


def _main(argv):
    args = _parse_args(argv)
    if args.shape_test:  # offline: cached cubes + malformed fixtures, no DB
        print(f"[{DOMAIN}] shape guard OK: {_shape_tests()} malformed fixtures rejected")
        return
    scratch = _scratch_db(args.db)
    cfg = {"no_kreise": args.no_kreise, "refresh": args.refresh,
           "no_estimates": args.no_estimates, "no_law": args.no_law}
    # scratch DB only: open it directly (common.DB and data/atlas.lock stay untouched; run.open_db refuses atlas.db)
    from ingest import run as runner
    conn = runner.open_db(scratch)
    # one transaction like ingest.run does (per-statement autocommit + synchronous=FULL is very slow)
    conn.execute("BEGIN IMMEDIATE")
    conn.runner_txn = True
    try:
        res = run(conn, cfg)
        conn.execute("INSERT INTO ingest_run(domain,ts,rows,notes,ok) VALUES(?,?,?,?,1)",
                     (DOMAIN, common.now(), res["rows"], res["notes"]))
        conn.runner_txn = False
        conn.real_commit()
    except BaseException:
        conn.runner_txn = False
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    print(f"[{DOMAIN}] OK rows={res['rows']} db={scratch} {res['notes']}")
    if args.selftest:
        _selftest(conn)
    else:
        common.selftest_report(conn, DOMAIN, "metric", where="entity_type IN ('de','land','kreis')")


def _cli(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="python3 -m ingest.domains.counts_law", allow_abbrev=False,
                                 description="Worker tools. data/atlas.db is written only by "
                                             "`python3 -m ingest.run counts_law`.")
    ap.add_argument("--shape-test", action="store_true", help="offline shape guard (cached cubes, no DB)")
    ap.add_argument("--selftest", action="store_true", help="run, then print the selftest report")
    ap.add_argument("--db", help="scratch DB path (required unless --shape-test; never atlas.db)")
    for flag in ("--no-kreise", "--refresh", "--no-estimates", "--no-law"):
        ap.add_argument(flag, action="store_true")
    args = list(sys.argv[1:] if argv is None else argv)
    a = ap.parse_args(args)
    if not a.shape_test and not a.db:
        ap.error("--db <scratch path> is required (the Lead writes data/atlas.db via python3 -m ingest.run counts_law)")
    _main(args)
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
