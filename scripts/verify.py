#!/usr/bin/env python3
"""germany-atlas completion gate (original implementation). Exit 0 only if every gate passes.

    python3 scripts/verify.py               # check data/atlas.db read-only
    python3 scripts/verify.py --db X.db     # check another file (e.g. a backup)
    python3 scripts/verify.py --selftest    # inject known-bad rows into a temp copy; expect FAIL
    python3 scripts/verify.py --ledger      # append the verdict to LEDGER.md / ledger.jsonl

Gates
  G1 integrity    integrity_check, foreign_key_check
  G2 provenance   every row of every core table has a source_id that exists
  G3 licences     every source has a licence, and its URL is listed in docs/SOURCES.md
                  (a listed URL may use <placeholder> or * for one path/query segment)
  G4 archive      every source has an archived copy on disk whose sha256 matches the row
  G5 numbers      every stored number occurs in its source's archived text, German formats included
                  (1.234,5 · 1 234 · 452 900 · 12,5); a quote, when given, occurs verbatim and contains it
  G6 estimates    is_est=1 wherever the quote, or the text around the number, says Schätzung /
                  geschätzt / Hochrechnung / hochgerechnet / modelliert
  G7 people       named people only in org_person, tied to an existing org, with a published title and
                  a source whose archived text names them (and contains the stored quote); no org row that
                  is really a private person; no private-life data
  G8 protection   no street address, postcode or coordinates for Frauenhäuser / protected shelters, nor for
                  women-, girls-, youth- or LGBTQ-only shelter provision (district level only)
  G9 spot-check   a deterministic sample of rows from every source traced to its document line
  G10 no republication  no archived document or full text in site/ or git
  G11 join integrity    (a) no hard id (register court+number, Berlin ZUWDB id, Lobbyregister, BA Nr., USt-IdNr,
                  LEI, QID) on more than one canonical org, no alias chains; (b) every org_person, award,
                  org_register, facility and org_link row points at an existing canonical org, and no award's
                  recipient register id belongs to another org; (c) no column's non-NULL count fell during an
                  ingest run (ingest_colstats before/after), unless docs/null_allowlist.tsv lists it with a reason
Also prints per-domain row counts, geographic coverage and site page counts (GOAL.md §Verified by).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE_DIR = ROOT / "site"  # G10 scans this; the selftest points it at a planted temp site
sys.path.insert(0, str(ROOT))
DB = ROOT / "data" / "atlas.db"
SOURCES_MD = ROOT / "docs" / "SOURCES.md"
SPOT_N = 5                                          # G9 rows sampled per source and table
EST_REVIEWED = ROOT / "docs" / "est_reviewed.tsv"   # Lead-reviewed G6 proximity false positives

CORE = ["geo_country", "geo_land", "geo_kreis", "geo_gemeinde", "org", "org_register", "org_person", "award",
        "zaehlung", "metric", "facility", "law", "media", "doc"]
# Kreis populations in new boundaries after a Kreis split (geo_bevoelkerung KREIS_SPLITS): the stored value is
# the exact sum of official Gemeinde figures, so it is not printed in the source. G5/G9 recompute it from the
# geo_gemeinde rows of the SAME source (each addend is itself G5-checked) and require exact equality.
SUM_OF_GEMEINDEN = {"einwohner_gebietsstand"}


def gemeinde_sum(q, kreis: str, source_id: int):
    r = q("SELECT count(*), sum(einwohner), sum(einwohner IS NULL) FROM geo_gemeinde WHERE kreis_ags=? AND source_id=?",
          kreis, source_id)[0]
    return (r[0] or 0), r[1], (r[2] or 0)


NUMERIC = {
    "zaehlung": ["insgesamt", "untergebracht", "ohne_unterkunft", "verdeckt", "minderjaehrige", "haushalte"],
    "metric": ["value"],
    "award": ["betrag"],
    "org": ["ertraege_eur", "aufwendungen_eur", "bilanzsumme_eur", "beschaeftigte"],
    "facility": ["betten", "haushalt_eur", "personal", "kosten_je_platz_eur"],
    "org_person": ["verguetung_eur"],
    "geo_land": ["einwohner", "flaeche_km2"], "geo_kreis": ["einwohner"], "geo_gemeinde": ["einwohner", "flaeche_km2"],
}

SP = "[ \u00a0\u2007\u2009\u202f]"
NUM_RE = re.compile(rf"(?<![\d,.])(?:\d{{1,3}}(?:(?:{SP}|\.)\d{{3}})+(?:,\d+)?|\d+(?:[.,]\d+)?)(?!\d)")
# "Einschätzung"/"einzuschätzen" (assessment) and "über-/unterschätzt" (a caveat) are not estimates
EST_RE = re.compile(r"(?i)(?<!ein)(?<!zu)(?<!über)(?<!ueber)(?<!unter)sch[äa]tz|hochgerechnet|hochrechnung|"
                    r"modelliert|extrapol|\bestimate")
PROTECTED_RE = re.compile(r"(?i)frauenh[äa]us|schutzwohnung|schutzhaus|zufluchtswohnung|m[äa]dchenhaus|"
                          r"frauenschutz|anonyme\s+unterkunft|gewaltschutzwohnung")
PROTECTED_OK_RE = re.compile(r"(?i)koordinierung|verband|landesarbeitsgemeinschaft|\blag\b|netzwerk|fachstelle")
ADDR_RE = re.compile(r"(?i)\b[\wäöüß.-]*(stra(ß|ss)e|str\.|weg|platz|allee|gasse|ring|damm|ufer|chaussee|steig)\s*\d+")
TITLE_RE = re.compile(r"^(Herr|Frau|Hr\.|Fr\.)\s", re.I)
ORGWORD_RE = re.compile(
    r"(?i)e\.\s?v\.|g?gmbh|\bug\b|\bag\b|stiftung|verein|verband|werk|hilfe|haus|zentrum|netz|initiative|bund|"
    r"stadt|kreis|gemeinde|amt|ministerium|senat|beh[öo]rde|bezirk|diakon|caritas|awo|parit|drk|kreuz|malteser|"
    r"johanniter|mission|zeitung|rundfunk|radio|magazin|verlag|medien|institut|universit|hochschule|kirche|"
    r"gemeinschaft|genossenschaft|gesellschaft|agentur|jobcenter|bank|fonds|forum|b[üu]ro|projekt|dienst|"
    r"sankt|st\.|tafel|wohn|wohlfahrt|obdach|soziale?|e\.g\.|eg\b|kg\b|partner|service|team|treff|laden|klinik|praxis|"
    r"jugend")
# women-/girls-/youth-/LGBTQ-only provision: locations only at district level (Chief of Staff, 2026-11-21)
GROUP_ONLY_RE = re.compile(r"(?i)(?<!lieb)frauen|m[äa]dchen|jugend|junge\s+(menschen|erwachsene|frauen|m[äa]nner)|minderj[äa]hrig|"
                           r"queer|lgbt|lsbt|\btrans\b|trans\*|transgender|schwul|lesb|non-?bin[äa]r|nicht-?bin[äa]r|\binter\*")
MIXED_GROUP_RE = re.compile(r"(?i)m[äa]nner\s+und\s+frauen|frauen\s+und\s+m[äa]nner|alle\s+geschlechter")
NON_SHELTER_KINDS = ("prison", "psychiatric")   # Wikidata JVAs / clinics publish their own public coordinates
PRIVATE_RE = re.compile(r"(?i)\bgeb(\.|oren)\s*(am\s*)?\d|privatanschrift|privatadresse|wohnhaft in|"
                        r"@(gmail|gmx|web|yahoo|outlook|hotmail|t-online|icloud)\.")


# ------------------------------------------------------------------ helpers
def json_numbers(text: str) -> set[float]:
    """If the archived text is JSON (API responses), every numeric value in it plus numbers inside its strings."""
    t = text.lstrip()
    if not t[:1] in ("{", "["):
        return set()
    try:
        doc = json.loads(t)
    except ValueError:
        return set()
    out: set[float] = set()
    stack = [doc]
    while stack:
        x = stack.pop()
        if isinstance(x, bool):
            continue
        if isinstance(x, (int, float)):
            out.add(float(x))
        elif isinstance(x, str):
            out |= numbers_in(x)
        elif isinstance(x, dict):
            stack.extend(x.values())
        elif isinstance(x, list):
            stack.extend(x)
    return out


def numbers_in(text: str) -> set[float]:
    """Every number in the text under German and English conventions (ambiguous forms both ways)."""
    out: set[float] = set()
    for m in NUM_RE.finditer(text):
        tok = m.group(0)
        # also every piece between separators: JSON arrays like [452910,46395] must not fuse
        for c in {tok, *re.split(SP, tok), *re.split(rf"[,]|{SP}", tok)}:
            c = re.sub(SP, "", c)
            if not c:
                continue
            try:
                if re.fullmatch(r"\d{1,3}(\.\d{3})+(,\d+)?", c):          # 1.234 / 1.234,5
                    out.add(float(c.replace(".", "").replace(",", ".")))
                    if c.count(".") == 1 and "," not in c:
                        out.add(float(c))                                  # or an English decimal
                elif "," in c:
                    out.add(float(c.replace(",", ".")))                    # German decimal comma
                    if re.fullmatch(r"\d{1,3}(,\d{3})+", c):
                        out.add(float(c.replace(",", "")))                 # English thousands
                else:
                    out.add(float(c))
            except ValueError:
                pass
    return out


SCALE_RE = re.compile(rf"(?<![\d.,])((?:\d{{1,3}}(?:(?:{SP}|\.)\d{{3}})+|\d+)(?:,\d+)?){SP}*"
                      r"(Mrd\.?|Milliarden|Mio\.?|Millionen|Tsd\.?|Tausend|T\s?€|TEUR)(?![\w])")
SCALE = {"mrd": 1e9, "milliarden": 1e9, "mio": 1e6, "millionen": 1e6, "tsd": 1e3, "tausend": 1e3, "t€": 1e3, "teur": 1e3}


def scaled_numbers(text: str) -> set[float]:
    """Amounts printed with a German scale word, read exactly: "10 Mrd. Euro" = 1e10, "9,8 Mio." = 9.8e6,
    "180.404 Tsd. Euro" = 180,404,000, "rd. 232 T€" = 232,000. Only the number directly before the word counts."""
    out: set[float] = set()
    for m in SCALE_RE.finditer(text or ""):
        mult = SCALE[re.sub(r"[\s.]", "", m.group(2)).lower()]
        num = re.sub(SP, "", m.group(1))
        try:
            val = float(num.replace(".", "").replace(",", ".")) if re.fullmatch(r"\d{1,3}(\.\d{3})+(,\d+)?", num) \
                else float(num.replace(",", "."))
        except ValueError:
            continue
        out.add(round(val * mult, 2))
    return out


_UNIT_SUBS = (
    (re.compile(r"(?<![A-Za-zÄÖÜäöüß])(?:m²|m\^2|m2|qm)(?![A-Za-zÄÖÜäöüß0-9])"), "qm"),  # square metres: m² · m2 · qm
    (re.compile(r"€"), "EUR"),                                                     # € and EUR are the same unit
    (re.compile(r"(?<=\d)(\s?)‡"), r"\1EUR"),                                       # pdftotext renders € as ‡ in some PDFs (Bremen Drs 19/894): "51,01 ‡" = "51,01 €"
    (re.compile(r"(?<=\d)(?=EUR)|(?<=EUR)(?=\d)"), " "),                             # 5€ / €5 -> 5 EUR / EUR 5
)


def norm(s: str) -> str:
    """Whitespace (incl. non-breaking, figure and thin spaces) collapsed; unit glyphs canonical (m²/m2 -> qm, € -> EUR),
    so a quote ending in 'm²' matches a document printing 'qm' or 'm2'. No digits are added by the substitutions."""
    s = re.sub(r"[\s\u00a0\u2007\u2009\u202f]+", " ", s or "")
    for rx, rep in _UNIT_SUBS:
        s = rx.sub(rep, s)
    return re.sub(" +", " ", s).strip()


def dehyphen(s: str) -> str:
    """Join PDF line-break hyphens in normalised text ("Psychi- atrie" -> "Psychiatrie")."""
    return re.sub(r"(\w)- (?=[a-zäöüß])", r"\1", s)


def forms(v: float) -> list[str]:
    if float(v).is_integer():
        i = int(v)
        g = f"{i:,}"
        # whole-euro amounts are often printed with two decimals (320,00 · 1.320,00) or a dash (414,- · 5,-- · 414,–)
        dotted = g.replace(",", ".")
        out = {str(i), dotted, g.replace(",", " "), g, f"{i},00", dotted + ",00"}
        for dash in (",-", ",--", ",–", ",—"):
            out |= {f"{i}{dash}", dotted + dash}
        return list(out)
    g = f"{v:,.2f}"                                   # 12,345.67 and 12.345,67 (amounts in EUR)
    return list({f"{v}".replace(".", ","), f"{v}", f"{v:.2f}", f"{v:.2f}".replace(".", ","),
                 g, g.replace(",", "X").replace(".", ",").replace("X", "."),
                 g.replace(",", " ").replace(".", ",")})          # 68 878 046,19 (space-grouped, as in Landtag tables)


def spot_patterns(v: float) -> list:
    """G9: renderings of v that must stand alone on a document line (no further digits or decimals)."""
    # a space-grouped form (68 878 046,19) must not start inside a longer space-grouped number
    return [re.compile(r"(?<![\d.,])" + (r"(?<!\d )" if " " in f else "") + re.escape(f) + r"(?![\d]|,\d| \d)" if " " in f
                       else r"(?<![\d.,])" + re.escape(f) + r"(?![\d]|,\d)") for f in forms(v)]


# an XLSX numeric cell rendered by common.xlsx_cell_line as '[Sheet!Q2327] <row text> = 149286.76999999999':
# the long decimal IS the stored binary double; it counts for G9 only on such a cell line and only to the cent
CELL_FLOAT_RE = re.compile(r"^\[[^\]!]+![A-Z]{1,3}\d+\] .* = (-?\d+\.\d+)$")


def cell_float_hit(v: float, line: str) -> bool:
    m = CELL_FLOAT_RE.match(line)
    if not m or float(v).is_integer() or round(v, 2) != v:
        return False
    t = m.group(1)
    return len(re.sub(r"\D", "", t).lstrip("0")) >= 15 and round(float(t), 2) == v


def spot_hit(v: float, line: str) -> bool:
    return any(p_.search(line) for p_ in spot_patterns(v))


REGISTER_SCHEMES = ("HRB", "HRA", "VR", "GnR", "PR")
REGISTER_NO_RE = re.compile(r"(?i)^(hrb|hra|vr|gnr|pr)[\s_:-]*\d+[a-z]?$")


def registered_orgs(q, tables) -> set[int]:
    """org ids holding a court-register number (HRB/HRA/VR/GnR/PR) in org_register, by scheme or by a
    publisher id that spells the register out (Berlin Zuwendungsdatenbank: hrb_115888, vr_021507)."""
    if "org_register" not in tables:
        return set()
    out = set()
    for x in q("SELECT org_id, scheme, number FROM org_register"):
        if x["scheme"] in REGISTER_SCHEMES and (x["number"] or "").strip() or REGISTER_NO_RE.match((x["number"] or "").strip()):
            out.add(x["org_id"])
    return out


PLACE_COL_RE = re.compile(r"(?i)^(anschrift|address\w*|street|strasse|plz|postcode|lat|lon|lng|coord\w*|geom\w*|"
                          r"\w*_city|city|ort|ort_\w*|\w*_nuts|nuts|place|\w*_place|office|dienststelle)$")


def protected_tables(q, tables) -> list[tuple[str, list[str]]]:
    """Every table (core or domain-private) with a `tags` column, plus its place-like columns."""
    out = []
    for t in sorted(tables):
        cols = [x[1] for x in q(f"PRAGMA table_info({t})")]
        if "tags" in cols:
            out.append((t, [c_ for c_ in cols if PLACE_COL_RE.match(c_)]))
    return out


def protected_source_ids(q, tables) -> set[int]:
    """Sources cited by a protected-shelter row: org/facility is_protected=1, or any tagged row with
    'protected_shelter'. Their archived copies may carry the shelter's address, so the site never mirrors them."""
    sids: set[int] = set()
    for t in ("org", "facility"):
        if t in tables:
            sids |= {x[0] for x in q(f"SELECT source_id FROM {t} WHERE is_protected=1 AND source_id IS NOT NULL")}
    for t, _ in protected_tables(q, tables):
        if "source_id" in {x[1] for x in q(f"PRAGMA table_info({t})")}:
            sids |= {x[0] for x in q(f"SELECT source_id FROM {t} WHERE tags LIKE '%protected_shelter%' AND source_id IS NOT NULL")}
    return sids


def url_listed(url: str, md: str, patterns: list[re.Pattern]) -> bool:
    return url in md or any(p.fullmatch(url) for p in patterns)


def md_patterns(md: str) -> list[re.Pattern]:
    pats = []
    for u in set(re.findall(r"https?://[^\s|)`'\"]+", md)):
        if "<" in u or "*" in u:
            rx = re.escape(u)
            rx = re.sub(r"<[^>]*>|\\\*", "[^/?&#]+", rx.replace("\\<", "<").replace("\\>", ">"))
            pats.append(re.compile(rx))
    return pats


class Report:
    def __init__(self):
        self.ok, self.bad, self.spot = [], {}, []

    def gate(self, name, problems, ok_msg):
        if problems:
            self.bad[name] = problems
        else:
            self.ok.append(f"{name}: {ok_msg}")

    def show(self) -> bool:
        for line in self.ok:
            print(f"  PASS  {line}")
        for g, probs in self.bad.items():
            print(f"  FAIL  {g}: {len(probs)} problem(s)")
            for p in probs[:20]:
                print(f"          - {p}")
            if len(probs) > 20:
                print(f"          … and {len(probs) - 20} more")
        good = not self.bad
        print("\nVERDICT:", "ALL GATES PASS" if good else "FAILED — " + ", ".join(self.bad))
        return good


# ------------------------------------------------------------------ the gate
def verify(db: Path, quiet_stats: bool = False) -> Report:
    r = Report()
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    q = lambda sql, *a: c.execute(sql, a).fetchall()  # noqa: E731
    tables = {x[0] for x in q("SELECT name FROM sqlite_master WHERE type='table'")}
    core = [t for t in CORE if t in tables]

    # G1
    ic = q("PRAGMA integrity_check")[0][0]
    fk = q("PRAGMA foreign_key_check")
    r.gate("G1 integrity", ([] if ic == "ok" else [f"integrity_check: {ic}"]) +
           [f"FK violation: {tuple(x)}" for x in fk[:50]], "integrity_check ok, no FK violations")

    # G2
    probs = []
    for t in core:
        n = q(f"SELECT count(*) FROM {t} WHERE source_id IS NULL OR source_id NOT IN (SELECT id FROM source)")[0][0]
        if n:
            probs.append(f"{t}: {n} row(s) without a valid source_id")
    r.gate("G2 provenance", probs, "every row in " + ", ".join(core) + " cites a source")

    # G3
    md = SOURCES_MD.read_text(encoding="utf-8") if SOURCES_MD.exists() else ""
    pats = md_patterns(md)
    probs = []
    for s in q("SELECT id, domain, url, license FROM source"):
        if not (s["license"] or "").strip():
            probs.append(f"source {s['id']} [{s['domain']}] has no licence: {s['url']}")
        elif re.match(r"(?i)\s*(todo|tbd|fixme|pending|unknown|n/?a)\b", s["license"]):
            probs.append(f"source {s['id']} [{s['domain']}] has a placeholder licence '{s['license'][:40]}': {s['url']}")
        if not url_listed(s["url"], md, pats):
            probs.append(f"source {s['id']} [{s['domain']}] not listed in docs/SOURCES.md: {s['url']}")
    r.gate("G3 licences", probs, f"{len(q('SELECT id FROM source'))} sources licensed and listed in docs/SOURCES.md")

    # G4 (+ load texts)
    probs, texts = [], {}
    for s in q("SELECT id, domain, url, sha256, local_path, text_path FROM source"):
        if not s["local_path"] or not (ROOT / s["local_path"]).exists():
            probs.append(f"source {s['id']} [{s['domain']}] has no archived copy: {s['url']}")
            continue
        h = hashlib.sha256((ROOT / s["local_path"]).read_bytes()).hexdigest()
        if h != s["sha256"]:
            probs.append(f"source {s['id']} sha256 mismatch ({h[:12]} on disk vs {str(s['sha256'])[:12]} in db)")
        if s["text_path"] and (ROOT / s["text_path"]).exists():
            texts[s["id"]] = (ROOT / s["text_path"]).read_text(encoding="utf-8", errors="replace")
    r.gate("G4 archive", probs, f"all archived copies present with matching sha256 ({len(texts)} with text)")

    # G5 + G6
    p5, p6 = [], []
    nums: dict[int, set[float]] = {}
    scaled: dict[int, set[float]] = {}
    dehy: dict[int, str] = {}
    flats: dict[int, str] = {}
    has_est = {sid: bool(EST_RE.search(t)) for sid, t in texts.items()}
    # reviewed exemptions: url <TAB> metric-or-column <TAB> value <TAB> reason (all four required)
    reviewed: set[tuple[str, str, float]] = set()
    if EST_REVIEWED.exists():
        for ln in EST_REVIEWED.read_text(encoding="utf-8").splitlines():
            if not ln.strip() or ln.startswith("#"):
                continue
            f_ = ln.split("\t")
            if len(f_) >= 4 and f_[3].strip():
                reviewed.add((f_[0].strip(), f_[1].strip(), round(float(f_[2]), 6)))
    urls = {x["id"]: x["url"] for x in q("SELECT id, url FROM source")}
    n_reviewed = 0
    checked = 0
    for t, cols in NUMERIC.items():
        if t not in tables:
            continue
        have = {x[1] for x in q(f"PRAGMA table_info({t})")}
        cols = [col for col in cols if col in have]
        extra = [x for x in ("quote", "is_est", "metric", "einheit") if x in have]
        if not cols:
            continue
        where = " OR ".join(f"{col} IS NOT NULL" for col in cols)
        for row in q(f"SELECT rowid AS rid, source_id, {', '.join(cols + extra)} FROM {t} WHERE {where}"):
            txt = texts.get(row["source_id"])
            vals = [(col, float(row[col])) for col in cols if row[col] is not None]
            tag = f"{t} rowid {row['rid']}"
            if txt is None:
                p5.append(f"{tag}: source {row['source_id']} has no archived text to check {', '.join(c_ for c_, _ in vals)}")
                continue
            sid = row["source_id"]
            if sid not in nums:                      # computed once per source (setdefault would re-scan every row)
                nums[sid] = {round(n, 6) for n in numbers_in(txt) | json_numbers(txt)}
                scaled[sid] = scaled_numbers(norm(txt))
            ns = nums[sid]
            quote = row["quote"] if "quote" in extra else None
            if t == "metric" and is_flag_row(row["metric"] if "metric" in extra else None, row["einheit"] if "einheit" in extra else None):
                # data-availability flag (0 = the official source says no data exist): not a number from the
                # source, so instead of the number checks it MUST carry a verbatim quote that says so
                checked += 1
                v = vals[0][1] if vals else None
                if v not in (0.0, 1.0):
                    p5.append(f"{tag}: availability flag must be 0 or 1, got {v}")
                elif v == 0.0 and not (quote and NO_DATA_RE.search(quote)):
                    p5.append(f"{tag}: availability flag 0 but the quote does not state that no data exist")
                elif quote:
                    if sid not in flats:
                        flats[sid] = norm(txt)
                    if norm(quote) not in flats[sid] and norm(quote) not in re.sub(r"(\w)- (?=[a-zäöüß])", r"\1", flats[sid]):
                        p5.append(f"{tag}: availability-flag quote not found verbatim in source {sid}")
                else:
                    p5.append(f"{tag}: availability flag without a quote")
                continue
            if t == "metric" and "metric" in extra and row["metric"] in SUM_OF_GEMEINDEN:
                checked += 1
                ent = q("SELECT entity_type, entity_id FROM metric WHERE rowid=?", row["rid"])[0]
                n_, tot, nulls = gemeinde_sum(q, ent[1], sid) if ent[0] == "kreis" else (0, None, 0)
                if ent[0] != "kreis" or not n_ or nulls or tot is None or round(float(tot), 6) != round(vals[0][1], 6):
                    p5.append(f"{tag}: {row['metric']}={vals[0][1]:g} is not the exact sum of the {n_} official Gemeinde "
                              f"rows of Kreis {ent[1]} in source {sid} ({tot})")
                if row["is_est"]:
                    p5.append(f"{tag}: a sum of official Gemeinde figures must not carry is_est=1")
                continue
            for col, v in vals:
                checked += 1
                if round(v, 6) not in ns and round(v, 2) not in scaled[sid]:
                    p5.append(f"{tag}: {col}={v:g} not found in archived source {row['source_id']}")
            flat = None
            if quote:
                if sid not in flats:
                    flats[sid] = norm(txt)
                flat = flats[sid]
                pos = flat.find(norm(quote))
                if pos < 0:
                    # a PDF line-break hyphen ("ent- standene") is not part of the printed word; the quote must
                    # still occur verbatim once those breaks are joined
                    if sid not in dehy:
                        dehy[sid] = dehyphen(flat)
                    pos = dehy[sid].find(norm(quote))
                    if pos < 0:
                        # the join must not break a quote's own suspended compound ("Kinder- und Jugend…"):
                        # join the quote the same way and look again (both sides transformed identically)
                        pos = dehy[sid].find(dehyphen(norm(quote)))
                    if pos >= 0:
                        flat = dehy[sid]
                qn = {round(n, 6) for n in numbers_in(quote)}
                if pos < 0:
                    p5.append(f"{tag}: quote not found verbatim in source {row['source_id']}")
                elif not any(round(v, 6) in qn or round(v, 2) in scaled_numbers(norm(quote)) or any(re.search(r"(?<![\d.,])" + re.escape(f) + r"(?![\d])", norm(quote))
                                                       for f in forms(v)) for _, v in vals):
                    # numbers_in() cannot split space-grouped table rows ("93 210 15 375 108 590"), so the
                    # quote also passes when one rendering of the stored value (108 590) occurs in it verbatim
                    p5.append(f"{tag}: quote does not contain the stored number")
                ctx = norm(quote) if pos < 0 else flat[max(0, pos - 250): pos + len(norm(quote)) + 250]
                if EST_RE.search(ctx) and "is_est" in extra and not row["is_est"]:
                    label = row["metric"] if "metric" in extra else None
                    if any((urls.get(sid), label, round(v, 6)) in reviewed for _, v in vals):
                        n_reviewed += 1
                    else:
                        p6.append(f"{tag}: quote/context says '{EST_RE.search(ctx).group(0)}' but is_est=0")
            elif "is_est" in extra and not row["is_est"] and has_est.get(row["source_id"]):
                if sid not in flats:
                    flats[sid] = norm(txt)
                flat = flats[sid]
                for col_, v in vals:
                    if abs(v) < 100:
                        continue
                    for f in forms(v):
                        for m in re.finditer(r"(?<![\d.,])" + re.escape(f) + r"(?![\d])", flat):
                            win = flat[max(0, m.start() - 200): m.end() + 200]
                            if EST_RE.search(win):
                                label = row["metric"] if "metric" in extra else col_
                                if (urls.get(row["source_id"]), label, round(v, 6)) in reviewed:
                                    n_reviewed += 1
                                    break
                                p6.append(f"{tag}: {v:g} appears next to '{EST_RE.search(win).group(0)}' in "
                                          f"source {row['source_id']} but is_est=0")
                                break
    r.gate("G5 numbers", p5, f"{checked} stored numbers found in their archived sources")
    r.gate("G6 estimates", p6, f"no unflagged estimates ({n_reviewed} Lead-reviewed proximity hits in docs/est_reviewed.tsv)")

    # G9 spot-check: a deterministic sample of rows from EVERY source, each traced back to its place in the document
    p9, spot = [], []
    kname = {k["ags"]: k["name"] for k in q("SELECT ags, name FROM geo_kreis")} if "geo_kreis" in tables else {}
    lines_by: dict[int, list[str]] = {}
    for src in q("SELECT id, url FROM source ORDER BY id"):
        sid, txt = src["id"], texts.get(src["id"])
        if txt is None:
            continue
        is_json = txt.lstrip()[:1] in "{[" and bool(json_numbers(txt))
        # name-on-the-same-line only means something when one document tabulates several Kreise
        multi_kreis = "metric" in tables and (q("SELECT count(DISTINCT entity_id) FROM metric WHERE source_id=? "
                                               "AND entity_type='kreis'", sid)[0][0] or 0) > 1
        sample = []
        if "metric" in tables:
            sample += [("metric", x) for x in q(
                "SELECT rowid AS rid, entity_type, entity_id, metric AS label, value AS v, "
                + ("quote" if "quote" in {c_[1] for c_ in q("PRAGMA table_info(metric)")} else "NULL") + " AS quote FROM metric "
                "WHERE source_id=? AND value IS NOT NULL AND coalesce(einheit,'') <> 'flag' "
                "AND metric NOT LIKE '%\\_data\\_available' ESCAPE '\\' ORDER BY (rowid * 2654435761) % 1000003 LIMIT ?", sid, SPOT_N)]
        if "award" in tables:
            sample += [("award", x) for x in q(
                "SELECT id AS rid, 'award' AS entity_type, empfaenger AS entity_id, 'betrag' AS label, "
                "betrag AS v, quote FROM award WHERE source_id=? AND betrag IS NOT NULL "
                "ORDER BY (id * 2654435761) % 1000003 LIMIT ?", sid, SPOT_N)]
        if "zaehlung" in tables:
            sample += [("zaehlung", x) for x in q(
                "SELECT rowid AS rid, geo_kind AS entity_type, geo_ags AS entity_id, 'untergebracht' AS label, untergebracht AS v "
                "FROM zaehlung WHERE source_id=? AND untergebracht IS NOT NULL ORDER BY (rowid * 2654435761) % 1000003 LIMIT ?",
                sid, SPOT_N)]
        if not sample:
            continue
        if sid not in lines_by:
            lines_by[sid] = txt.splitlines()
        lines = lines_by[sid]
        for t, x in sample:
            v = float(x["v"])
            if t == "metric" and x["label"] in SUM_OF_GEMEINDEN:
                tag = f"source {sid} metric rowid {x['rid']} {x['entity_type']}:{x['entity_id']} {x['label']}={v:g}"
                n_, tot, nulls = gemeinde_sum(q, x["entity_id"], sid)
                if n_ and not nulls and tot is not None and round(float(tot), 6) == round(v, 6):
                    spot.append(f"{tag} -> exact sum of {n_} official Gemeinde rows (geo_gemeinde, same source)")
                else:
                    p9.append(f"{tag}: not the exact sum of the official Gemeinde rows ({n_} rows, sum {tot})")
                continue
            pats = spot_patterns(v)
            hits = [n for n, ln in enumerate(lines) if any(p_.search(ln) for p_ in pats)]
            if not hits:                      # XLSX numeric cell stored as a binary float (149286.76999999999)
                hits = [n for n, ln in enumerate(lines) if cell_float_hit(v, ln)]
            if not hits and abs(v) >= 1000:   # amounts printed with a scale word ("9,8 Mio. Euro")
                hits = [n for n, ln in enumerate(lines) if round(v, 2) in scaled_numbers(norm(ln))]
            tag = f"source {sid} {t} rowid {x['rid']} {x['entity_type']}:{x['entity_id']} {x['label']}={v:g}"
            if is_json:
                ok = round(v, 6) in nums.get(sid, set())
                spot.append(f"{tag} -> {'in JSON cube' if ok else 'MISSING'}")
                if not ok:
                    p9.append(f"{tag}: value not in the archived JSON")
                continue
            if not hits:
                p9.append(f"{tag}: value form not found as a token in any line")
                continue
            qt = norm(x["quote"]) if t in ("metric", "award") and x["quote"] else ""
            if qt and len(qt) >= 6:
                # a stored quote pins the line: a bare "2" must not trace to a table-of-contents line
                at_quote = [n for n in hits if qt in norm(lines[n]) or norm(lines[n]) in qt and len(norm(lines[n])) >= 6]
                if at_quote:
                    hits = at_quote
            if multi_kreis and x["entity_type"] == "kreis" and x["entity_id"] in kname:
                core = re.split(r",", kname[x["entity_id"]])[0]
                core = re.sub(r"(?i)\b(stadt|kreis|landkreis|kreisfreie|st[äa]dteregion)\b", "", core).strip()
                near = [n for n in hits if any(core.lower() in lines[m].lower()
                                               for m in range(max(0, n - 1), min(len(lines), n + 2)))]
                if not near:
                    p9.append(f"{tag}: '{core}' never on the same table line as the value")
                    continue
                hits = near
            spot.append(f"{tag} -> line {hits[0] + 1}: {' '.join(lines[hits[0]].split())[:110]}")
    # law / court rows: the cited paragraph or file number must be in the archived text
    def squash(t_: str) -> str:
        return re.sub(r"\s+", "", t_ or "").lower().replace("\u00a0", "").replace("§§", "§")
    for t, label, sql in (("law", "citation", "SELECT id, citation AS a, source_id FROM law"),
                          ("doc", "title", "SELECT id, title AS a, source_id FROM doc")):
        if t not in tables:
            continue
        for x in q(sql):
            txt = texts.get(x["source_id"])
            if txt is None:
                p9.append(f"{t} {x['id']}: source {x['source_id']} has no archived text")
                continue
            anchors = re.findall(r"(?:§§?|Art\.)\s*\d+[a-z]?", x["a"] or "") if t == "law" else \
                re.findall(r"\d+\s+[A-Z][A-Za-z]{0,2}\s+\d+[./]\d+", x["a"] or "")   # 9 B 187/20, 1 C 4.20, 4 CE 24.60
            if not anchors:
                continue
            flat_ = squash(txt)
            miss = [a_ for a_ in anchors if squash(a_) not in flat_]
            if len(miss) == len(anchors):        # descriptive extras ("DVO zu §§ 67 ff.") may be absent; one must be there
                p9.append(f"{t} {x['id']} {x['a']!r}: {', '.join(miss)} not in archived source {x['source_id']}")
            else:
                found = [a_ for a_ in anchors if a_ not in miss]
                spot.append(f"source {x['source_id']} {t} {x['id']} {x['a']} -> {', '.join(found)} found"
                            + (f" (descriptive, not in text: {', '.join(miss)})" if miss else ""))
    # INGEST_CONTRACT §11: a lapsed rule keeps its row but must say since when and why
    if "law" in tables:
        for x in q("SELECT id, in_force_to, summary, source_id FROM law WHERE status='lapsed'"):
            if not re.fullmatch(r"\d{4}(-\d{2}-\d{2})?", x["in_force_to"] or ""):
                p9.append(f"law {x['id']}: status 'lapsed' needs in_force_to YYYY-MM-DD or YYYY, has {x['in_force_to']!r}")
            if not re.match(r"\[außer Kraft seit [^:\]]+: .*(§|Art\.)", x["summary"] or ""):
                p9.append(f"law {x['id']}: lapsed row's summary must start '[außer Kraft seit …: <basis citing § / Art.>'")
            else:
                spot.append(f"source {x['source_id']} law {x['id']} lapsed {x['in_force_to']} -> außer Kraft basis stated")
    r.spot = spot
    r.gate("G9 spot-check", p9, f"{len(spot)} sampled rows across {len({x.split()[1] for x in spot})} sources traced to their document line")

    # G7
    probs = []
    if "org" in tables:
        registered = registered_orgs(q, tables)
        for o in q("SELECT id, name, email FROM org"):
            nm = (o["name"] or "").strip()
            w = nm.split()
            if TITLE_RE.match(nm):
                probs.append(f"org {o['id']} '{nm}' starts with a personal salutation")
            elif 2 <= len(w) <= 3 and all(x[:1].isupper() and x.replace("-", "").isalpha() for x in w) \
                    and not ORGWORD_RE.search(nm) and o["id"] not in registered:
                # an org with a Handels-/Vereins-/Genossenschafts-/Partnerschaftsregister number is a legal
                # entity whatever its name sounds like ("Neue Chance", hrb_115888); without one it still fails
                probs.append(f"org {o['id']} '{nm}' looks like a private person's name, not an organisation")
            if PRIVATE_RE.search(f"{nm} {o['email'] or ''}"):
                probs.append(f"org {o['id']} '{nm}' carries private-person data")
    if "org_person" in tables:
        for p in q("SELECT p.id, p.org_id, p.funktion AS title, p.funktionstraeger AS person, p.source_id, o.id AS oid FROM org_person p "
                   "LEFT JOIN org o ON o.id = p.org_id"):
            if p["oid"] is None:
                probs.append(f"org_person {p['id']} ('{p['person']}') is not tied to an existing organisation")
            if not (p["title"] or "").strip():
                probs.append(f"org_person {p['id']} ('{p['person']}') has no published role title")
            if PRIVATE_RE.search(p["person"] or "") or ADDR_RE.search(p["person"] or ""):
                probs.append(f"org_person {p['id']} carries private-life data")
        # the one allowed path for a named person: its own source's archived text names them (every name
        # token; initials and degrees like 'Dr.' / 'C.' excepted) and, when a quote is stored, contains it
        cols = {c[1] for c in q("PRAGMA table_info(org_person)")}
        qcol = "p.quote" if "quote" in cols else "NULL"
        for p in q(f"SELECT p.id, p.funktionstraeger AS person, p.source_id, {qcol} AS quote FROM org_person p"):
            txt = texts.get(p["source_id"])
            if txt is None:
                probs.append(f"org_person {p['id']} ('{p['person']}'): source {p['source_id']} has no archived text")
                continue
            low = txt.lower()
            toks = [t_ for t_ in re.split(r"[\s]+", p["person"] or "") if t_ and not t_.endswith(".")]
            miss = [t_ for t_ in toks if t_.lower() not in low]
            if miss:
                probs.append(f"org_person {p['id']} ('{p['person']}'): {', '.join(miss)} not in archived source {p['source_id']}")
            if p["quote"] and norm(p["quote"]).lower() not in norm(txt).lower():
                probs.append(f"org_person {p['id']} ('{p['person']}'): quote not verbatim in archived source {p['source_id']}")
    r.gate("G7 people", probs, "people only as sourced organisation roles; no private individuals")

    # G8
    probs = []
    if "facility" in tables:
        for f in q("SELECT id, name, kind, is_protected, anschrift, plz, lat, lon FROM facility"):
            sens = f["is_protected"] or (f["kind"] or "") in ("frauenhaus", "schutzwohnung", "protected_shelter") \
                or (PROTECTED_RE.search(f["name"] or "") and not PROTECTED_OK_RE.search(f["name"] or ""))
            located = any(f[k] not in (None, "") for k in ("anschrift", "plz", "lat", "lon")) or ADDR_RE.search(f["name"] or "")
            if sens and located:
                probs.append(f"facility {f['id']} '{f['name']}' is a protected shelter with a street-level location")
            elif located and (f["kind"] or "") not in NON_SHELTER_KINDS and \
                    GROUP_ONLY_RE.search(f"{f['name'] or ''} {f['kind'] or ''}") and \
                    not MIXED_GROUP_RE.search(f["name"] or ""):
                probs.append(f"facility {f['id']} '{f['name']}' is women/youth/LGBTQ-only provision with a street "
                             f"address or coordinates (district level only)")
    if "org" in tables:
        for o in q("SELECT id, name, is_protected, strasse, plz, lat, lon FROM org"):
            sens = o["is_protected"] or (PROTECTED_RE.search(o["name"] or "") and not PROTECTED_OK_RE.search(o["name"] or ""))
            if sens and any(o[k] not in (None, "") for k in ("strasse", "plz", "lat", "lon")):
                probs.append(f"org {o['id']} '{o['name']}' looks like a protected shelter and has an address/coordinates")
    # tagged protected rows in any table (e.g. funding_traeger_ted_notice/_award, _zuwendung): no place fields at all
    for t, pcols in protected_tables(q, tables):
        for col in pcols:
            n_ = q(f"SELECT count(*) FROM {t} WHERE tags LIKE '%protected_shelter%' AND {col} IS NOT NULL AND {col} != ''")[0][0]
            if n_:
                probs.append(f"{t}: {n_} protected_shelter row(s) carry a place value in '{col}'")
    for t, _ in protected_tables(q, tables):
        tcols = [x[1] for x in q(f"PRAGMA table_info({t})") if x[1] in ("title", "lot_title", "description", "zweck", "name")]
        for col in tcols:
            for x in q(f"SELECT rowid AS rid, {col} AS v FROM {t} WHERE tags LIKE '%protected_shelter%' AND {col} IS NOT NULL"):
                if ADDR_RE.search(x["v"]) or re.search(r"(?<![\d.,])\b\d{5}\b(?![.,]\d)(?!\s*(?:€|EUR|Euro))", x["v"]):
                    probs.append(f"{t} rowid {x['rid']}: protected_shelter row names a street/postcode in '{col}'")
    psids = protected_source_ids(q, tables)
    if psids:
        mark = ",".join("?" * len(psids))
        for s_ in q(f"SELECT id, title FROM source WHERE id IN ({mark})", *psids):
            if ADDR_RE.search(s_["title"] or ""):
                probs.append(f"source {s_['id']}: title of a protected-shelter source names a street address")
    if "award" in tables and psids:
        mark = ",".join("?" * len(psids))
        for a in q(f"SELECT id, dienststelle, zweck FROM award WHERE source_id IN ({mark})", *psids):
            if (a["dienststelle"] or "").strip() or ADDR_RE.search(a["zweck"] or ""):
                probs.append(f"award {a['id']} cites a protected-shelter source and shows an office/street address")
    raw_dir = ROOT / "site" / "raw"
    if raw_dir.exists() and psids:
        mark = ",".join("?" * len(psids))
        for s_ in q(f"SELECT id, local_path, text_path FROM source WHERE id IN ({mark})", *psids):
            for pth in (s_["local_path"], s_["text_path"]):
                if pth and (raw_dir / Path(pth).name).exists():
                    probs.append(f"site/raw/{Path(pth).name}: archived copy of protected-shelter source {s_['id']} is published")
    r.gate("G8 protection", probs, "no protected-shelter addresses or coordinates (DB, tagged rows, site/raw)")

    # G10 no republication: archived source documents / extracted full texts never appear in site/ or in git
    probs = []
    hashes = {x[0] for x in q("SELECT sha256 FROM source WHERE sha256 IS NOT NULL")}
    for x in q("SELECT text_path FROM source WHERE text_path IS NOT NULL"):
        tp = ROOT / x[0]
        if tp.exists():
            hashes.add(hashlib.sha256(tp.read_bytes()).hexdigest())
    site = SITE_DIR
    if (site / "raw").exists():
        probs.append("site/raw/ exists: archived documents must not be mirrored on the site")
    if site.exists():
        for f in site.rglob("*"):
            if not f.is_file():
                continue
            head = f.open("rb").read(5)
            if head == b"%PDF-":
                probs.append(f"site file {f.relative_to(site)} is a PDF document")
            elif f.stat().st_size and hashlib.sha256(f.read_bytes()).hexdigest() in hashes:
                probs.append(f"site file {f.relative_to(site)} is a byte copy of an archived source")
    try:
        import subprocess
        tracked = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-z"], capture_output=True, check=True).stdout.split(b"\0")
        for t_ in (x.decode() for x in tracked if x):
            f = ROOT / t_
            if t_.startswith("data/raw/") and t_ != "data/raw/.gitkeep":
                probs.append(f"git tracks archived file {t_}")
            elif f.is_file() and f.stat().st_size and hashlib.sha256(f.read_bytes()).hexdigest() in hashes:
                probs.append(f"git-tracked {t_} is a byte copy of an archived source")
    except Exception as ex:  # noqa: BLE001
        probs.append(f"cannot list git-tracked files: {ex}")
    r.gate("G10 no republication", probs, "no archived source document or full text in site/ or in git")

    # G11 join integrity: one canonical org per hard id, references to canonical orgs only, no NULL regression
    from ingest import orglink
    p11, i11 = orglink.gate(c)
    r.gate("G11 join integrity", p11,
           f"{i11.get('canonical')} canonical orgs ({i11.get('aliases')} alias rows), 0 hard-id duplicates, 0 orphan or "
           f"alias references, {i11.get('links')} org_link rows of which {i11.get('flagged_links')} fuzzy links await review "
           f"(reports/join_gaps.md); " + (f"NULL baseline {i11.get('baseline_filled')}/{i11.get('baseline_columns')} columns filled "
           f"in {i11.get('baseline_tables')} tables at run #{i11.get('baseline_run')}, {i11.get('runs_checked')} run(s) checked, "
           f"{i11.get('allowed')} allowlisted drop(s)" if i11.get("baseline_run") else "no run snapshotted yet (ingest_colstats empty)"))

    if not quiet_stats:
        stats(c, tables)
    c.close()
    return r


def stats(c, tables) -> None:
    q = lambda sql, *a: c.execute(sql, a).fetchall()  # noqa: E731
    print("\nRows per domain (by source.domain):")
    per = defaultdict(dict)
    for t in CORE:
        if t in tables:
            for d, n in q(f"SELECT s.domain, count(*) FROM {t} x JOIN source s ON s.id = x.source_id GROUP BY 1"):
                per[d][t] = n
    for d in sorted(per):
        print(f"  {d:22s} " + "  ".join(f"{t}={n}" for t, n in sorted(per[d].items())))
    print(f"  {'(sources)':22s} " + "  ".join(f"{d}={n}" for d, n in q("SELECT domain, count(*) FROM source GROUP BY 1")))

    def cov(kind, table, n_all):
        have = q(f"SELECT count(DISTINCT geo_ags) FROM zaehlung WHERE geo_kind=?", kind)[0][0] if "zaehlung" in tables else 0
        rows = q(f"SELECT count(*) FROM {table}")[0][0] if table in tables else 0
        return f"{kind}: {rows} in gazetteer, {have}{'/' + str(n_all) if n_all else ''} with counts"
    print("Coverage:", " · ".join([cov("land", "geo_land", 16), cov("kreis", "geo_kreis", 400), cov("gemeinde", "geo_gemeinde", None)]))
    site = ROOT / "site"
    pages = len(list(site.rglob("*.html"))) if site.exists() else 0
    print(f"Site: {pages} HTML pages in site/")


# ------------------------------------------------------------------ selftest
NO_DATA_RE = re.compile(r"(?i)keine\s+(?:\w+\s+){0,2}(?:daten|angaben|erkenntnisse|zahlen|statistik)|"
                        r"liegen\s+.{0,80}?nicht\s+vor|nicht\s+(?:statistisch\s+)?erfasst|werden\s+nicht\s+(?:statistisch\s+)?erhoben")


def is_flag_row(metric, unit) -> bool:
    return (unit or "") == "flag" or (metric or "").endswith("_data_available")


def selftest(db: Path) -> int:
    with tempfile.TemporaryDirectory() as td:
        bad = Path(td) / "bad.db"
        src = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        src.execute(f"VACUUM INTO '{bad}'")
        src.close()
        c = sqlite3.connect(bad)
        c.execute("PRAGMA foreign_keys=OFF")
        sid = c.execute("SELECT id FROM source WHERE text_path IS NOT NULL ORDER BY id LIMIT 1").fetchone()[0]
        c.execute("INSERT INTO metric(entity_type, entity_id, metric, value, einheit, year, is_est, source_id) "
                  "VALUES ('de','DE','selftest_invented',987654321,'persons',2099,0,?)", (sid,))
        c.execute("INSERT INTO metric(entity_type, entity_id, metric, value, einheit, year, is_est, quote, source_id) "
                  "VALUES ('de','DE','selftest_estimate',1,'persons',2098,0,'rund 1 Person geschätzt',?)", (sid,))
        c.execute("INSERT INTO metric(entity_type, entity_id, metric, value, einheit, year, is_est, quote, source_id) "
                  "VALUES ('land','11','selftest_data_available',0,'flag',2097,0,'Daten liegen vor',?)", (sid,))
        gsid = c.execute("SELECT source_id FROM geo_gemeinde WHERE kreis_ags='06435' LIMIT 1").fetchone()
        if gsid:   # a Gebietsstand sum that is off by one must fail G5
            c.execute("INSERT OR REPLACE INTO metric(entity_type, entity_id, metric, value, einheit, year, is_est, source_id) "
                      "SELECT 'kreis','06435','einwohner_gebietsstand',sum(einwohner)+1,'persons',2096,0,? FROM geo_gemeinde "
                      "WHERE kreis_ags='06435' AND source_id=?", (gsid[0], gsid[0]))
        c.execute("INSERT INTO org(name, name_norm, land, source_id) VALUES ('Max Mustermann','MAX MUSTERMANN','BE',?)", (sid,))
        # G7 register exemption: a person-like name WITH a register number passes, one without fails (above)
        c.execute("INSERT INTO org(name, name_norm, land, source_id) VALUES ('Neue Probe','NEUE PROBE','BE',?)", (sid,))
        c.execute("INSERT INTO org_register(org_id, scheme, court, number, raw, source_id) "
                  "VALUES (last_insert_rowid(),'BE_ZUWDB','','hrb_999999','hrb_999999',?)", (sid,))
        c.execute("INSERT INTO org_person(org_id, funktionstraeger, funktionstraeger_norm, funktion, source_id) "
                  "VALUES (999999,'Erika Musterfrau','ERIKA MUSTERFRAU','Vorstand',?)", (sid,))
        c.execute("INSERT INTO facility(name, name_norm, kind, is_protected, land, ort, anschrift, source_id) "
                  "VALUES ('Frauenhaus Musterstadt','FRAUENHAUS MUSTERSTADT','shelter',0,'BE','Berlin','Musterstraße 12',?)", (sid,))
        c.execute("INSERT INTO facility(name, name_norm, kind, is_protected, land, ort, lat, lon, source_id) "
                  "VALUES ('Notübernachtung für junge Frauen','NOTUEBERNACHTUNG FUER JUNGE FRAUEN','notunterkunft',0,"
                  "'BE','Berlin',52.5,13.4,?)", (sid,))
        c.execute("INSERT INTO facility(name, name_norm, kind, is_protected, land, ort, lat, lon, source_id) "
                  "VALUES ('Jugendanstalt Probe','JUGENDANSTALT PROBE','prison',0,'BE','Berlin',52.5,13.4,?)", (sid,))
        c.execute("CREATE TABLE selftest_tagged(id INTEGER PRIMARY KEY, tags TEXT, winner_city TEXT, source_id INTEGER)")
        c.execute("INSERT INTO selftest_tagged(tags, winner_city, source_id) VALUES ('[\"protected_shelter\"]','Musterstadt',?)", (sid,))
        c.execute("INSERT INTO source(domain, url, title, publisher) VALUES ('selftest','https://example.invalid/x','x','x')")
        c.execute("INSERT INTO source(domain, url, title, publisher, license) VALUES "
                  "('selftest','https://example.invalid/todo','x','x','TODO: licence pending')")
        # G11: (a) one USt-IdNr on two canonical orgs, (b) an award left on an alias row, (c) a NULL regression
        from ingest import orglink
        orglink.ensure_schema(c)
        ins_org = "INSERT INTO org(name, name_norm, land, ust_id, source_id) VALUES (?,?,?,?,?)"
        d1 = c.execute(ins_org, ("Selftest Doppel Eins GmbH", "SELFTEST DOPPEL EINS", "BE", "DE999999998", sid)).lastrowid
        c.execute(ins_org, ("Selftest Doppel Zwei GmbH", "SELFTEST DOPPEL ZWEI", "BE", "DE 999 999 998", sid))
        al = c.execute(ins_org, ("Selftest Alias GmbH", "SELFTEST ALIAS", "BE", None, sid)).lastrowid
        c.execute("INSERT INTO award(foerder_schluessel, empfaenger, empfaenger_norm, org_id, source_id) "
                  "VALUES ('SELFTEST:alias','Selftest Alias GmbH','SELFTEST ALIAS',?,?)", (al, sid))
        c.execute("UPDATE org SET canonical_org_id=? WHERE id=?", (d1, al))     # the award now names an alias row
        rid = c.execute("INSERT INTO ingest_run(domain, status, ok) VALUES ('selftest','ok',1)").lastrowid
        c.executemany("INSERT INTO ingest_colstats(run_id, phase, tbl, col, nonnull) VALUES (?,?,?,?,?)",
                      [(rid, "before", "org", "webseite", 10), (rid, "after", "org", "webseite", 5),
                       (rid, "before", "org", "*", 10), (rid, "after", "org", "*", 10)])
        c.commit()
        c.close()
        # G10: a fake site that mirrors one archived document byte-for-byte
        global SITE_DIR
        fake = Path(td) / "site"
        (fake / "source").mkdir(parents=True)
        arch = next((ROOT / r_[0] for r_ in sqlite3.connect(bad).execute(
            "SELECT local_path FROM source WHERE local_path IS NOT NULL AND sha256 IS NOT NULL") if (ROOT / r_[0]).exists()), None)
        if arch is not None:
            (fake / "source" / "copy.bin").write_bytes(arch.read_bytes())
        (fake / "source" / "doc.html").write_bytes(b"%PDF-1.4 planted")
        saved_site, SITE_DIR = SITE_DIR, fake
        print("selftest: verifying a copy with 10 deliberately bad rows and a planted site mirror\n")
        try:
            rep = verify(bad, quiet_stats=True)
        finally:
            SITE_DIR = saved_site
        rep.show()
        want = {"G1 integrity", "G3 licences", "G4 archive", "G5 numbers", "G6 estimates", "G7 people", "G8 protection",
                "G10 no republication", "G11 join integrity"}
        got = set(rep.bad)
        g7 = rep.bad.get("G7 people", [])
        g7_ok = any("'Max Mustermann'" in p_ for p_ in g7) and not any("'Neue Probe'" in p_ for p_ in g7)
        g8 = rep.bad.get("G8 protection", [])
        g8_ok = any("selftest_tagged" in p_ for p_ in g8)
        g8_grp = any("'Notübernachtung für junge Frauen'" in p_ for p_ in g8) and not any("'Jugendanstalt Probe'" in p_ for p_ in g8)
        print(f"selftest: G8 catches a located women-only shelter and spares a public JVA: {g8_grp}")
        g8_ok = g8_ok and g8_grp
        print(f"selftest: G8 catches a place value on a tagged protected_shelter row: {g8_ok}")
        g5_flag = any("availability flag 0 but the quote" in p_ for p_ in rep.bad.get("G5 numbers", []))
        print(f"selftest: G5 rejects a 'no data' flag whose quote does not say so: {g5_flag}")
        g8_ok = g8_ok and g5_flag
        if gsid:
            g5_sum = any("is not the exact sum" in p_ for p_ in rep.bad.get("G5 numbers", []))
            print(f"selftest: G5 rejects a Gebietsstand population that is not the exact sum of its Gemeinden: {g5_sum}")
        else:   # a DB without geo_gemeinde rows for Kreis 06435 (e.g. a funding-only scratch DB) cannot plant the case
            g5_sum = True
            print("selftest: G5 Gebietsstand case skipped (no geo_gemeinde rows for Kreis 06435)")
        g8_ok = g8_ok and g5_sum
        g3_ok = any("placeholder licence" in p_ for p_ in rep.bad.get("G3 licences", []))
        print(f"selftest: G3 rejects a TODO licence: {g3_ok}")
        g10 = rep.bad.get("G10 no republication", [])
        g10_ok = any("byte copy" in p_ for p_ in g10) and any("PDF document" in p_ for p_ in g10)
        print(f"selftest: G10 catches an archived-source byte copy and a PDF on the site: {g10_ok}")
        forms_ok = (spot_hit(320, "Gebühr je Tag 320,00 EUR") and spot_hit(1320, "insgesamt 1.320,00 Euro")
                    and not spot_hit(320.5, "Gebühr je Tag 320,00 EUR") and not spot_hit(320, "320,50 EUR"))
        print(f"selftest: G9 matches 320 in '320,00' and 1320 in '1.320,00', not 320.5 in '320,00': {forms_ok}")
        doc = "je qm Wohnfläche 6,14\u00a0€ monatlich; Stellplatz je m2 2,50\u202fEUR"
        units_ok = (norm("Wohnfläche 6,14 EUR") in norm(doc) and norm("je m² Wohnfläche 6,14 €") in norm(doc)
                    and norm("je m²") in norm(doc) and norm("Stellplatz je m² 2,50 €") in norm(doc)
                    and norm("je m² Nutzfläche") not in norm(doc) and "2" not in norm("m²").replace("qm", "")
                    and norm("Bequem") == "Bequem")
        print(f"selftest: G5/G9 quotes match across m²/m2/qm, €/EUR and non-breaking/thin spaces: {units_ok}")
        dash_ok = (spot_hit(414, "Gebühr 414,- € monatlich") and spot_hit(5, "Tagessatz 5,-- EUR") and spot_hit(414, "414,–€")
                   and spot_hit(1414, "1.414,- Euro") and not spot_hit(414.5, "414,- €") and not spot_hit(14, "414,- €"))
        print(f"selftest: G9 matches whole euros written 414,- / 5,-- / 414,– (with or without €), not 414.5: {dash_ok}")
        glyph_ok = (norm("zwischen 51,01 € und 136,65 €.") in norm("zwischen 51,01 ‡ und 136,65 ‡.")
                    and {51.01, 136.65} <= numbers_in("zwischen 51,01 ‡ und 136,65 ‡.") and norm("Fußnote ‡ siehe Anm.") == "Fußnote ‡ siehe Anm.")
        print(f"selftest: G5/G9 read the pdftotext euro glyph ‡ after a number as €, and only there: {glyph_ok}")
        _doc = norm("TK Kinder- und Jugendpsychi-\natrie und -psychotherapie   114   126   202")
        _q = norm("TK Kinder- und Jugendpsychiatrie und -psychotherapie 114 126 202")
        hyph_ok = (_q not in _doc and _q not in dehyphen(_doc) and dehyphen(_q) in dehyphen(_doc)
                   and dehyphen(norm("Kinder- und Jugendpsychiatrie 114 126 203")) not in dehyphen(_doc))
        print(f"selftest: G5 joins a PDF line-break hyphen without breaking the quote's own 'Kinder- und': {hyph_ok}")
        cell_ok = (cell_float_hit(149286.77, "[Sheet1!Q2327] ZUW-2024-01524 Diakonisches Werk Hamburg = 149286.76999999999")
                   and not cell_float_hit(149286.77, "Zuwendungssumme 149286.76999999999 EUR")        # text document: exact only
                   and not cell_float_hit(149286.77, "[Sheet1!Q2327] ZUW-2024-01524 = 149286.7")
                   and not cell_float_hit(149286.78, "[Sheet1!Q2327] ZUW-2024-01524 = 149286.76999999999")
                   and not spot_hit(149286.77, "Zuwendungssumme 149286.76999999999 EUR"))
        print(f"selftest: G9 reads an XLSX float-artifact cell (149286.76999999999) as 149286.77, never in text documents: {cell_ok}")
        def _g7_person(nm):   # the G7 org-name rule above, without the register exemption
            w_ = nm.split()
            return 2 <= len(w_) <= 3 and all(x[:1].isupper() and x.replace("-", "").isalpha() for x in w_) and not ORGWORD_RE.search(nm)
        jug_ok = (not _g7_person("Evangelische Jugend Mecklenburg") and not _g7_person("DLRG-Jugend MV")
                  and bool(ORGWORD_RE.search("Ev. Jugend Mecklenburg")) and _g7_person("Anna Schmidt")
                  and _g7_person("Jörn Martin Scheuermann"))
        print(f"selftest: G7 treats 'Ev. Jugend Mecklenburg' / 'DLRG-Jugend MV' as organisations, 'Anna Schmidt' still as a person: {jug_ok}")
        dash_ok = dash_ok and glyph_ok and hyph_ok and cell_ok and jug_ok
        units_ok = units_ok and dash_ok
        forms_ok = forms_ok and units_ok
        g11 = rep.bad.get("G11 join integrity", [])
        g11_a = any(p_.startswith("(a) hard id UST:DE999999998 maps to 2") for p_ in g11)
        g11_b = any(p_.startswith("(b) award row") and "alias org 'Selftest Alias GmbH'" in p_ for p_ in g11)
        g11_b2 = any(p_.startswith("(b) org_person row") and "names no org" in p_ for p_ in g11)
        g11_c = any(p_.startswith("(c) NULL regression") and "org.webseite 10 -> 5" in p_ for p_ in g11)
        g11_ok = g11_a and g11_b and g11_b2 and g11_c
        print(f"selftest: G11 catches a shared USt-IdNr {g11_a}, an award on an alias row {g11_b}, "
              f"a role on a missing org {g11_b2}, a NULL regression {g11_c}")
        g7_ok = g7_ok and g8_ok and g3_ok and g10_ok and forms_ok and g11_ok
        print(f"\nselftest: expected failures {sorted(want)}\n          got               {sorted(got)}")
        print(f"selftest: G7 person-like name without register fails, with register hrb_ passes: {g7_ok}")
        if want <= got and g7_ok:
            print("SELFTEST PASS: the gate rejects every planted bad row")
            return 0
        print("SELFTEST FAIL: some bad rows slipped through:", sorted(want - got))
        return 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=DB)
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--ledger", action="store_true")
    ap.add_argument("--spot", action="store_true", help="print every G9 spot-check sample with its document line")
    a = ap.parse_args()
    if not a.db.exists():
        print(f"no database at {a.db}")
        return 1
    if a.selftest:
        return selftest(a.db)
    print(f"verify {a.db}")
    rep = verify(a.db)
    if a.spot:
        print("\nG9 spot-check samples:")
        for line in rep.spot:
            print("   ", line)
    print()
    good = rep.show()
    if a.ledger:
        from ingest.run import ledger
        ledger("verify", "PASS" if good else "FAIL", "-", a.db.name, "; ".join(rep.ok + [f"{k}: {len(v)}" for k, v in rep.bad.items()])[:400])
    return 0 if good else 1


if __name__ == "__main__":
    sys.exit(main())
