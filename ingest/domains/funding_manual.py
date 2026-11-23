"""funding_manual -- grants from hand-archived official files (manual-archive source mode): Bremen, Rheinland-Pfalz.

Why manual: the hosts answer robots.txt with HTTP 403 to automated clients, so our gate reads them as "refused" and
this module NEVER requests them (not even robots.txt). The Lead archived the specific public files once, by browser,
on 2026-11-23 into ~/projects/_manual_archive/funding_traeger/ with SHA256SUMS, SIZES and PROVENANCE.md (source URL,
retrieval date, licence text per file). Lead decision 2026-11-23: a one-off manual archive is allowed, as for
Darmstadt and Landshut.

Manual-archive source mode (archive_read / archive_source):
  * reads only from the archive directory (cfg['manual_archive'] or the default);
  * every file's sha256 is checked against SHA256SUMS before parsing; a missing entry or a mismatch fails the run;
  * the verified bytes are copied into the data/raw cache under the file's official URL (meta: retrieved_at from
    PROVENANCE, note 'manual archive') so the source row carries sha256/local_path (verify G4) and quotes are
    checked against exactly these bytes; the official URL is never fetched;
  * source.notes says 'manual archive' with the dataset page; the award locator cites dataset page + file + row.

Sources:
  hb_zuwendungen  Bremen, Zuwendungen Quartalsberichte (ZEBRA) 2024 Q1 – 2026 Q3, XLSX (CSV only to cross-check).
                  Licence (dataset field): Creative Commons Namensnennung (CC BY 3.0).
                  The quarterly reports are cumulative per "Jahr Maßnahmebeginn" and restate grants: dedupe by
                  Bremen's grant id GKZ (Geschäftskennzeichen), the row of the latest report (Berichtsdatum) wins.
  rlp_mastd       Rheinland-Pfalz, MASTD Zuwendungsübersicht 2024 nach § 7 Abs. 1 Nr. 11 LTranspG, PDF.
                  Licence: Datenlizenz Deutschland Namensnennung 2.0.

Filter and privacy as funding_hamburg: homelessness core terms in any Ressort; adjacent terms (street work, soup
kitchen, emergency shelter) only from the social authority and without refugee or youth context; organisations
only (natural persons / sole traders / GbR skipped, not stored); protected shelters keep the money but no place
(Stadtteil) and a redacted purpose; orgs via common.ensure_org (schema 6, legal_form_norm, no tags in name_norm).

Worker entry points (never data/atlas.db):
  python3 -m ingest.domains.funding_manual --test
  python3 -m ingest.domains.funding_manual --selftest --db /tmp/x.db
The real DB is written only by the runner: python3 -m ingest.run funding_manual.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import sqlite3
import sys
from pathlib import Path

from ingest import common

DOMAIN = "funding_manual"
ARCHIVE_DEFAULT = Path.home() / "projects/_manual_archive/funding_traeger"
RETRIEVED = "2026-11-23T19:03:00+01:00"
MODE_NOTE = "manual archive (browser, Lead, 2026-11-23; robots.txt 403 to automated clients); sha256 verified against SHA256SUMS; host never fetched"


class ArchiveError(RuntimeError):
    pass


# --------------------------------------------------------------------------------------------- #
# manual-archive source mode
# --------------------------------------------------------------------------------------------- #
def archive_dir(cfg) -> Path:
    return Path((cfg or {}).get("manual_archive") or ARCHIVE_DEFAULT).expanduser()


def load_checksums(root: Path) -> dict[str, str]:
    p = root / "SHA256SUMS"
    if not p.is_file():
        raise ArchiveError(f"no SHA256SUMS in {root}")
    out = {}
    for ln in p.read_text(encoding="utf-8").splitlines():
        parts = ln.strip().split(None, 1)
        if len(parts) == 2 and not parts[0].startswith("#"):
            out[parts[1].strip().lstrip("*")] = parts[0].lower()
    return out


def archive_read(root: Path, filename: str, sums: dict[str, str] | None = None) -> bytes:
    """Bytes of an archived file after its sha256 matched SHA256SUMS (missing entry or mismatch: ArchiveError)."""
    sums = sums if sums is not None else load_checksums(root)
    p = root / filename
    if not p.is_file():
        raise ArchiveError(f"manual archive file missing: {p}")
    if filename not in sums:
        raise ArchiveError(f"{filename}: no SHA256SUMS entry")
    data = p.read_bytes()
    got = hashlib.sha256(data).hexdigest()
    if got != sums[filename]:
        raise ArchiveError(f"{filename}: sha256 {got} != SHA256SUMS {sums[filename]}")
    return data


def archive_source(conn, url: str, data: bytes, *, content_type: str, title: str, publisher: str, license: str,
                   dataset_page: str, filename: str) -> int:
    """Seed the raw cache under the official URL with the verified bytes and register the source (never fetches)."""
    dest = common.raw_path(DOMAIN, url)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.exists() or dest.read_bytes() != data:
        dest.write_bytes(data)
    dest.with_suffix(".meta.json").write_text(json.dumps({
        "url": url, "method": "GET", "status": 200, "retrieved_at": RETRIEVED, "content_type": content_type,
        "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
        "note": f"seeded from verified manual archive file {filename}; official host not fetched"}, ensure_ascii=False),
        encoding="utf-8")
    return common.source_id_for(conn, url, DOMAIN, title=title, publisher=publisher, license=license,
                                notes=f"{MODE_NOTE}; dataset page {dataset_page}; file {filename}")


# --------------------------------------------------------------------------------------------- #
# filter (Hamburg rules + Bremen terms)
# --------------------------------------------------------------------------------------------- #
def _ft():
    from ingest.domains import funding_traeger as ft
    return ft


CORE_EXTRA = re.compile("|".join([
    r"winternot\w*", r"tagesaufenthalt\w*", r"[üu]e?bernachtungsst[äa]e?tte\w*", r"krankenstube\w*",
    r"stra[ßs]s?enzeitung\w*", r"zeitschrift der stra[ßs]e", r"obdach\b", r"k[äa]e?lteregel\w*",
    r"erfrierungsschutz", r"notschlafst\w*", r"housing[\s-]?first"]), re.I)
ADJ_EXTRA = re.compile(r"tagestreff\w*|streetwork|aufsuchende\s+stra[ßs]s?ensozialarbeit", re.I)
SOCIAL_AUTHORITY = re.compile(r"soziales|sozialbeh[öo]e?rde", re.I)
YOUTH_RE = re.compile(r"jugend\w*|clique\w*|m[äa]e?dchen\w*|kinder\w*", re.I)
MIGRANT_RE = re.compile(r"zugewandert\w*|neuzugewandert\w*|eu-b[üu]e?rger\w*", re.I)


def classify(zweck: str | None, behoerde: str | None, empfaenger: str | None = None) -> tuple[str | None, list[str]]:
    ft = _ft()
    z = zweck or ""
    core = sorted({m.group(0).lower() for rx in (ft.BZ_CORE, CORE_EXTRA) for m in rx.finditer(z)})
    adj = sorted({m.group(0).lower() for rx in (ft.BZ_ADJACENT, ADJ_EXTRA) for m in rx.finditer(z)})
    if core:
        return "core", core + adj
    if adj and not ft.REFUGEE_RE.search(z) and not MIGRANT_RE.search(z) and not YOUTH_RE.search(f"{z} {empfaenger or ''}") \
            and SOCIAL_AUTHORITY.search(behoerde or ""):
        return "adjacent", adj
    return None, []


# Lead 2026-11-23: a Bremen row matched only by a generic service word (Suppenküche, Streetwork) counts only when
# the cited row itself names homelessness ("Günstiger Mittagstisch ältere Menschen in der Suppenküche", EUR 35,000,
# and "Streetwork mal anders - Im Wasser statt an Land", EUR 740.10, are excluded)
HB_GENERIC = re.compile(r"suppenk[üu]e?che\w*|streetwork", re.I)
HB_HOMELESS = re.compile(r"wohnungslos\w*|obdachlos\w*|obdach\b|wohnungsnot\w*|wohnungsnotfall\w*|ohne\s+(feste\s+)?wohnung|"
                         r"stra[ßs]s?enobdach\w*|housing[\s-]?first|k[äa]e?lteregel\w*|erfrierungsschutz|notschlaf\w*|"
                         r"winternot\w*|tagesaufenthalt\w*|[üu]e?bernachtungsst[äa]e?tte\w*", re.I)


def hb_borderline(zweck: str | None, terms: list[str]) -> bool:
    return bool(terms) and all(HB_GENERIC.fullmatch(t) for t in terms) and not HB_HOMELESS.search(zweck or "")


ORG_NAME = re.compile(r"k[öo]e?rperschaft des [öo]e?ffentlichen rechts|anstalt des [öo]e?ffentlichen rechts|"
                      r"heilsarmee|kirchenbezirk|kirchengemeinde|pfarrei", re.I)


def is_person(name: str | None) -> bool:
    ft = _ft()
    n = common.clean(name) or ""
    if n and ORG_NAME.search(n) and not ft._SOLE_TRADER.search(n):
        return False
    return ft.ted_is_person(n)


def amount(raw) -> float | None:
    s = common.clean(raw)
    if s is None or not re.fullmatch(r"-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?", str(s)):
        return None
    return float(s)


# --------------------------------------------------------------------------------------------- #
# Bremen
# --------------------------------------------------------------------------------------------- #
HB_HOST = "https://www.finanzen.bremen.de/sixcms/media.php/bremen02.a.13.de/download/"
HB_PAGES = {"2024": "https://www.transparenz.bremen.de/daten/zuwendungen-quartalsberichte-2024-226023",
            "2025": "https://www.transparenz.bremen.de/daten/zuwendungen-quartalsberichte-2025-268960",
            "2026": "https://www.transparenz.bremen.de/daten/zuwendungen-quartalsberichte-2026-326296"}
HB_LICENSE = ("Creative Commons Namensnennung (CC BY 3.0) (dataset field 'Lizenz' on the Bremen Transparenzportal "
              "dataset page); attribution: Freie Hansestadt Bremen, Die Senatorin für Finanzen")
HB_PUBLISHER = "Freie Hansestadt Bremen, Die Senatorin für Finanzen (Transparenzportal Bremen, ZEBRA)"
HB_LAND, HB_LAND_AGS = "HB", "04"
HB_COLS = {"ressort": "ressort/dienststelle", "programm": "förderprogramm", "gkz": "gkz", "hh": "hh-stelle(n)",
           "zweck": "zuwendungszweck", "empf": "antragsteller / zuwendungsempfänger", "stadtteil": "stadtteil",
           "art": "zuwendungsart", "fin": "finanzierungsart", "summe": "zuwendungs- summe",
           "gezahlt": "bereits gezahlt", "offen": "noch zahlbar"}


def hb_header(rows) -> tuple[int, dict[str, int], dict[str, str]]:
    meta = {}
    for i, r in enumerate(rows):
        h = [re.sub(r"\s+", " ", (c or "")).strip().lower() for c in r]
        if h and h[0].startswith("ressort"):
            m = {k: h.index(v) for k, v in HB_COLS.items() if v in h}
            miss = [v for k, v in HB_COLS.items() if k in ("gkz", "zweck", "empf", "summe", "ressort") and k not in m]
            if miss:
                raise ArchiveError(f"Bremen XLSX: columns missing {miss}")
            return i, m, meta
        if r and r[0]:
            meta[common.clean(r[0])] = common.clean(r[1]) if len(r) > 1 else None
    raise ArchiveError("Bremen XLSX: header row not found")


def _xl_date(v) -> str | None:
    import datetime as _dt
    try:
        return (_dt.date(1899, 12, 30) + _dt.timedelta(days=float(v))).isoformat()
    except (TypeError, ValueError):
        m = re.match(r"(\d{1,2})\.(\d{1,2})\.(\d{4})$", common.clean(v) or "")
        return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}" if m else None


def hb_files(root: Path) -> list[str]:
    return sorted(p.name for p in root.glob("*.xlsx"))


def _csv_rows(data: bytes) -> list[list[str]]:
    for enc in ("utf-8", "cp1252"):
        try:
            t = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    return list(csv.reader(io.StringIO(t), delimiter=";"))


def _de_amount(s) -> float | None:
    s = (s or "").strip().replace("€", "").strip()
    if not re.fullmatch(r"-?[\d.]*\d(?:,\d+)?|-?\d+(?:\.\d+)?", s):
        return None
    return float(s.replace(".", "").replace(",", ".")) if "," in s or re.search(r"\.\d{3}(?!\d)", s) else float(s)


HB_DDL = """
CREATE TABLE IF NOT EXISTS funding_manual_hb (
  gkz            TEXT PRIMARY KEY,      -- Bremen Geschäftskennzeichen (grant id)
  source_id      INTEGER,               -- the report whose row is kept (latest Berichtsdatum)
  datei          TEXT,
  zeile          INTEGER,
  berichtsdatum  TEXT,
  jahr           TEXT,                  -- Jahr Maßnahmebeginn
  ressort        TEXT,
  programm       TEXT,
  zweck          TEXT,
  empfaenger     TEXT,
  stadtteil      TEXT,                  -- NULL on protected rows
  zuwendungsart  TEXT,
  summe          REAL,
  gezahlt        REAL,
  reports        INTEGER,               -- number of report rows restating this GKZ
  tier           TEXT,
  matched_terms  TEXT,
  tags           TEXT,
  csv_check      TEXT                   -- ok | mismatch | absent
);
"""


def run_hb(conn, cfg: dict) -> dict:
    from ingest.domains.institutions_media_orgs import iter_xlsx_sheets
    ft = _ft()
    conn.executescript(HB_DDL)
    root = archive_dir(cfg)
    sums = load_checksums(root)
    files = cfg.get("hb_files") or hb_files(root)
    if not files:
        raise ArchiveError(f"no Bremen XLSX in {root}")
    reports = []                       # (berichtsdatum, file, sheet, rows, hm, meta, data)
    for fn in files:
        data = archive_read(root, fn, sums)
        sheet, rows = next(iter(iter_xlsx_sheets(data).items()))
        hi, hm, meta = hb_header(rows)
        reports.append({"file": fn, "data": data, "sheet": sheet, "rows": rows, "hi": hi, "hm": hm,
                        "datum": _xl_date(meta.get("Berichtsdatum")), "jahr": meta.get("Jahr Maßnahmebeginn")})
    reports.sort(key=lambda r: (r["datum"] or "", r["file"]))
    st = {"files": len(reports), "rows": 0, "gkz": 0, "restated": 0, "in_file_dups_identical": 0,
          "in_file_dups_conflict": 0, "core": 0, "adjacent": 0, "persons": 0, "protected": 0, "org_none": 0,
          "csv_ok": 0, "csv_mismatch": 0, "csv_absent": 0, "no_amount": 0}
    # 1. every GKZ -> its rows over all reports; the latest report (Berichtsdatum) wins
    best: dict[str, tuple[dict, int]] = {}
    in_reports: dict[str, set] = {}
    for rep in reports:
        g = lambda r, k, rep=rep: (r[rep["hm"][k]] if k in rep["hm"] and rep["hm"][k] < len(r) else "")  # noqa: E731
        rep["g"] = g
        here: dict[str, int] = {}
        for ri in range(rep["hi"] + 1, len(rep["rows"])):
            r = rep["rows"][ri]
            gkz = common.clean(g(r, "gkz"))
            if not gkz:
                continue
            st["rows"] += 1
            in_reports.setdefault(gkz, set()).add(rep["file"])
            if gkz in here:
                prev = rep["rows"][here[gkz]]
                if [common.clean(x) for x in prev] == [common.clean(x) for x in r]:
                    st["in_file_dups_identical"] += 1
                    continue
                st["in_file_dups_conflict"] += 1      # same GKZ, different row in one report: the larger sum is kept
                if (amount(g(r, "summe")) or 0) <= (amount(g(prev, "summe")) or 0):
                    continue
            here[gkz] = ri
        for gkz, ri in here.items():
            best[gkz] = (rep, ri)
    count = {k: len(v) for k, v in in_reports.items()}
    st["gkz"] = len(best)
    st["restated"] = sum(1 for v in count.values() if v > 1)
    sids: dict[str, int] = {}
    total, orgs, years = 0.0, set(), {}
    kept = 0
    for gkz, (rep, ri) in best.items():
        g, r = rep["g"], rep["rows"][ri]
        zweck = common.clean(g(r, "zweck"))
        tier, terms = classify(zweck, common.clean(g(r, "ressort")), common.clean(g(r, "empf")))
        if not tier:
            continue
        if hb_borderline(zweck, terms):
            st["lead_borderline"] = st.get("lead_borderline", 0) + 1
            continue
        name = common.clean(g(r, "empf"))
        if not name or is_person(name):
            st["persons"] += 1
            continue
        betrag = amount(g(r, "summe"))
        if betrag is None:
            st["no_amount"] += 1
            continue
        protected = ft.is_protected(f"{zweck} {name}")
        st["protected"] += protected
        tags = (["refugee"] if ft.REFUGEE_RE.search(zweck or "") else []) + (["protected_shelter"] if protected else [])
        fn = rep["file"]
        url = HB_HOST + fn
        page = HB_PAGES.get(rep["jahr"] or "", HB_PAGES["2026"])
        if fn not in sids:
            sids[fn] = archive_source(conn, url, rep["data"], content_type="application/vnd.openxmlformats-officedocument."
                                      "spreadsheetml.sheet", title=f"Bremen – Zuwendungen Quartalsbericht {fn} (Jahr "
                                      f"Maßnahmebeginn {rep['jahr']}, Berichtsdatum {rep['datum']}), XLSX",
                                      publisher=HB_PUBLISHER, license=HB_LICENSE, dataset_page=page, filename=fn)
        sid = sids[fn]
        # CSV cross-check (same report, same GKZ, same amount)
        csv_fn = fn[:-5] + ".csv"
        chk = "absent"
        if csv_fn in sums and (root / csv_fn).is_file():
            for cr in _csv_rows(archive_read(root, csv_fn, sums)):
                if gkz in [common.clean(c) for c in cr]:
                    vals = [_de_amount(c) for c in cr]
                    chk = "ok" if any(v is not None and abs(v - betrag) < 0.005 for v in vals) else "mismatch"
                    if chk == "ok":
                        break
        st[f"csv_{chk}"] += 1
        org_id = ft.ensure_org_xland(conn, name, HB_LAND, sid, stats=st, is_protected=1 if ft.is_protected(name) else None)
        st["org_none"] += org_id is None
        col = common.xlsx_col(rep["hm"]["summe"])
        jahr = rep["jahr"]
        common.upsert(conn, "funding_manual_hb", {
            "gkz": gkz, "source_id": sid, "datei": fn, "zeile": ri + 1, "berichtsdatum": rep["datum"], "jahr": jahr,
            "ressort": common.clean(g(r, "ressort")), "programm": common.clean(g(r, "programm")),
            "zweck": ft.redact_place(zweck) if protected else zweck, "empfaenger": name,
            "stadtteil": None if protected else common.clean(g(r, "stadtteil")),
            "zuwendungsart": common.clean(g(r, "art")), "summe": betrag, "gezahlt": amount(g(r, "gezahlt")),
            "reports": count.get(gkz, 1), "tier": tier, "matched_terms": json.dumps(terms, ensure_ascii=False),
            "tags": json.dumps(tags), "csv_check": chk}, keys=["gkz"])
        common.upsert(conn, "award", {
            "foerder_schluessel": f"DE-HB-ZEBRA:{gkz}", "foerder_id": gkz, "foerderart": "zuwendung",
            "zuwendungsgeber": common.clean(g(r, "ressort")), "programm": common.clean(g(r, "programm")),
            "zweck": ft.redact_place(zweck) if protected else zweck, "empfaenger": name,
            "empfaenger_norm": common.name_norm(name), "org_id": org_id, "betrag": betrag, "currency": "EUR",
            "haushaltsjahr": jahr, "ort_land": HB_LAND, "is_est": 0,
            "quote": common.xlsx_cell_line(rep["sheet"], ri, rep["hm"]["summe"], r),
            "locator": (f"{page} – Datei {fn} ({MODE_NOTE.split(';')[0]}), Blatt '{rep['sheet']}', Zeile {ri + 1}, "
                        f"Zelle {col}{ri + 1} (EUR, Zuwendungssumme bewilligt, Jahr Maßnahmebeginn {jahr}); GKZ {gkz}; Berichtsdatum {rep['datum']}; "
                        f"{count.get(gkz, 1)} Quartalsbericht(e) nennen diese GKZ, der neueste zählt"),
            "source_id": sid}, keys=["foerder_schluessel"])
        kept += 1
        st[tier] += 1
        total += betrag
        orgs.add(common.name_norm(name))
        years[jahr] = years.get(jahr, 0) + 1
    notes = (f"hb_zuwendungen: {st['files']} quarterly XLSX ({MODE_NOTE.split(';')[0]}), {st['rows']} report rows, "
             f"{st['gkz']} distinct GKZ ({st['restated']} restated in >1 report; in-file duplicates identical "
             f"{st['in_file_dups_identical']}, conflicting {st['in_file_dups_conflict']}); kept {kept} awards (core "
             f"{st['core']}, adjacent {st['adjacent']}), {len(orgs)} recipients, EUR {total:,.2f}; years "
             + ", ".join(f"{k}:{v}" for k, v in sorted(years.items()))
             + f"; skipped persons {st['persons']}, no amount {st['no_amount']}; protected {st['protected']}; org key "
             f"taken {st['org_none']}; CSV cross-check ok {st['csv_ok']}, mismatch {st['csv_mismatch']}, absent "
             f"{st['csv_absent']}")
    notes += f"; cross-Land org matches {st.get('xland', 0)}"
    return {"rows": kept, "notes": notes, "sources": [(HB_HOST + "<file>", HB_LICENSE)], "stats": st}


# --------------------------------------------------------------------------------------------- #
# Rheinland-Pfalz (MASTD Zuwendungsübersicht, PDF layout table)
# --------------------------------------------------------------------------------------------- #
RLP_FILE = "zuwendungsubersicht_mastd_2024.pdf"
RLP_URL = ("https://upload.open.rlp.de/eakte/9d8d6a4d-9d69-42a9-92e9-4b844cb6966c/resource/"
           "1bfedca8-4bc1-463d-a00a-219d1b699dfd/download/zuwendungsubersicht_mastd_2024.pdf")
RLP_PAGE = "https://open.rlp.de/de/suchergebnisse/dataset/zuwendungsubersicht-mastd-2024"
RLP_LICENSE = "Datenlizenz Deutschland Namensnennung 2.0 (dl-de/by-2-0); attribution: Land Rheinland-Pfalz, MASTD (open.rlp.de)"
RLP_GEBER = "Ministerium für Arbeit, Soziales, Transformation und Digitalisierung Rheinland-Pfalz (MASTD)"
RLP_LAND = "RP"


def rlp_rows(pdf: bytes) -> list[dict]:
    from ingest.domains import funding_mv as mv
    out = []
    for pi, ws in enumerate(mv.bbox_pages(pdf)):
        anchors = sorted([w for w in ws if w[4] == "Epl."], key=mv._ym)
        if not anchors:
            continue
        ay = [mv._ym(a) for a in anchors]
        lines = []
        for a in anchors:
            ln = sorted((w for w in ws if abs(mv._ym(w) - mv._ym(a)) < 4), key=lambda w: w[0])
            d = [w for w in ln if mv.DATE.match(w[4])]
            am = [w for w in ln if mv.AMOUNT.match(w[4])]
            art = [w for w in ln if re.fullmatch(r"[A-Z]", w[4]) and d and w[0] > d[0][2]]
            lines.append((ln, d, am, art))
        ok = [x for x in lines if x[1] and x[2] and x[3]]
        if not ok:
            continue
        x_name0 = min(x[1][0][2] for x in ok) + 2
        x_name1 = min(x[3][0][0] for x in ok) - 2
        x_zweck0 = max(x[2][0][2] for x in ok) + 2
        ytop = max((w[3] for w in ws if w[4] in ("Zuwendungsempfänger", "Höhe")), default=0)
        body = [w for w in ws if w[1] >= ytop]
        names = mv._assign(mv._cell_lines([w for w in body if x_name0 <= w[0] and w[2] <= x_name1]), ay)
        zw = mv._assign(mv._cell_lines([w for w in body if w[0] >= x_zweck0]), ay)
        for k, (ln, d, am, art) in enumerate(lines):
            out.append({"page": pi + 1, "datum": mv._iso(d[0][4]) if d else None, "betrag_text": am[0][4] if am else None,
                        "art": art[0][4] if art else None, "empfaenger": mv._join(names[k]), "zweck": mv._join(zw[k]),
                        "titel": " ".join(w[4] for w in ln if d and w[2] < d[0][0])})
    return out


def run_rlp(conn, cfg: dict) -> dict:
    from ingest.domains import funding_mv as mv
    ft = _ft()
    root = archive_dir(cfg)
    data = archive_read(root, RLP_FILE)
    rows = rlp_rows(data)
    tlines = mv.layout_text(data).splitlines()
    st = {"rows": len(rows), "core": 0, "adjacent": 0, "persons": 0, "protected": 0, "unparsed": 0, "org_none": 0}
    sid = None
    kept, total, orgs = 0, 0.0, set()
    for i, r in enumerate(rows, 1):
        betrag = mv.amount(r["betrag_text"])
        if betrag is None or not r["empfaenger"]:
            st["unparsed"] += 1
            continue
        tier, terms = classify(r["zweck"], RLP_GEBER, r["empfaenger"])
        if not tier:
            continue
        name = r["empfaenger"]
        if is_person(name):
            st["persons"] += 1
            continue
        quote = next((common.clean(ln) for ln in tlines if "Epl." in ln and r["betrag_text"] in ln
                      and (r["datum"] and ".".join(reversed(r["datum"].split("-"))) in ln)), None)
        if quote is None:
            st["unparsed"] += 1
            continue
        if sid is None:
            sid = archive_source(conn, RLP_URL, data, content_type="application/pdf",
                                 title="Rheinland-Pfalz – MASTD Zuwendungsübersicht 2024 (§ 7 Abs. 1 Nr. 11 LTranspG), PDF",
                                 publisher=RLP_GEBER, license=RLP_LICENSE, dataset_page=RLP_PAGE, filename=RLP_FILE)
        protected = ft.is_protected(f"{r['zweck']} {name}")
        st["protected"] += protected
        org_id = ft.ensure_org_xland(conn, name, RLP_LAND, sid, stats=st, is_protected=1 if ft.is_protected(name) else None)
        st["org_none"] += org_id is None
        common.upsert(conn, "award", {
            "foerder_schluessel": f"DE-RP-MASTD-2024:{i}", "foerder_id": f"MASTD-2024-{i}", "foerderart": "zuwendung",
            "zuwendungsgeber": RLP_GEBER, "programm": r["titel"] or None,
            "zweck": ft.redact_place(r["zweck"]) if protected else r["zweck"], "empfaenger": name,
            "empfaenger_norm": common.name_norm(name), "org_id": org_id, "betrag": betrag, "currency": "EUR",
            "haushaltsjahr": "2024", "laufzeit_von": r["datum"], "ort_land": RLP_LAND, "is_est": 0, "quote": quote,
            "locator": f"{RLP_PAGE} – Datei {RLP_FILE} (manual archive), Seite {r['page']}, Bewilligung vom {r['datum']} "
                       f"(EUR, Höhe der Zuwendung, Zuwendungsübersicht 2024; Zuwendungsart {r['art']})",
            "source_id": sid}, keys=["foerder_schluessel"])
        kept += 1
        st[tier] += 1
        total += betrag
        orgs.add(common.name_norm(name))
    notes = (f"rlp_mastd: {RLP_FILE} (manual archive), {st['rows']} grants parsed; kept {kept} (core {st['core']}, "
             f"adjacent {st['adjacent']}), {len(orgs)} recipients, EUR {total:,.2f}, year 2024; skipped persons "
             f"{st['persons']}, unparsed {st['unparsed']}; protected {st['protected']}")
    notes += f"; cross-Land org matches {st.get('xland', 0)}"
    return {"rows": kept, "notes": notes, "sources": [(RLP_URL, RLP_LICENSE)] if sid else [], "stats": st}


SOURCES = {"hb_zuwendungen": run_hb, "rlp_mastd": run_rlp}


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


_HB_HDR = ["Ressort/Dienststelle", "Förderprogramm", "GKZ", "HH-Stelle(n)", "Zuwendungszweck",
           "Antragsteller / Zuwendungsempfänger", "Stadtteil", "Zuwendungsart", "Finanzierungsart", "Zuwendungs-\nsumme",
           "bereits gezahlt", "noch zahlbar", "Besserstellungsverbot eingehalten?"]
SOZ = "41 - Die Senatorin für Arbeit, Soziales, Jugend und Integration"


def _hb_row(gkz, zweck, empf, summe, ressort=SOZ, stadtteil="Mitte"):
    return [ressort, "400_Wohnungshilfe", gkz, "3402.68410-0", zweck, empf, stadtteil, "Projektförderung",
            "Fehlbedarfsfinanzierung", summe, summe, "0", "ja"]


def _hb_xlsx(jahr, datum_serial, rows):
    from ingest.domains.funding_hamburg import mini_xlsx
    head = [["Quartalsbericht Transparenzportal"] + [""] * 12, [""] * 13, ["Jahr Maßnahmebeginn", jahr] + [""] * 11,
            ["Status", "bewilligte Anträge"] + [""] * 11, ["Berichtsdatum", datum_serial] + [""] * 11, [""] * 13, _HB_HDR]
    return mini_xlsx(head + rows, sheet="Quartalsbericht Transparenzport")


def _hb_csv(rows):
    out = io.StringIO()
    w = csv.writer(out, delimiter=";")
    for r in rows:
        w.writerow([str(c).replace(".", ",") if re.fullmatch(r"\d+\.\d+", str(c)) else c for c in r])
    return out.getvalue().encode("cp1252")


def _fixture_archive(tmp: Path, *, corrupt: str | None = None, rlp: bytes | None = None) -> Path:
    q1 = [_hb_row("400/3-02/Kälte/2025", "Kälteregelung - Erfrierungsschutz für obdachlose Menschen", "Verein für Innere Mission in Bremen", "100000"),
          _hb_row("400/3-02/Kälte/2025", "Kälteregelung - Erfrierungsschutz für obdachlose Menschen", "Verein für Innere Mission in Bremen", "100000"),
          _hb_row("400/Streetwork/2025", "Streetwork Kattenturm", "Verein zur Förderung akzeptierender Jugendarbeit e.V.", "15000"),
          _hb_row("250/Kultur/2025", "Literaturtreff für obdachlose Frauen", "Erika Muster", "1680", ressort="22 - Der Senator für Kultur"),
          _hb_row("400/SK/2025", "Suppenküche am Bahnhof für obdachlose Menschen", "Die Bremer Suppenengel e.V.", "10000")]
    q2 = [_hb_row("400/3-02/Kälte/2025", "Kälteregelung - Erfrierungsschutz für obdachlose Menschen", "Verein für Innere Mission in Bremen", "120320.44"),
          _hb_row("400/FH/2025", "Schutzwohnung für wohnungslose Frauen, Musterstraße 3", "Frauenhaus Bremen e.V.", "5000", stadtteil="Findorff"),
          _hb_row("400/Theater/2025", "Theaterprojekt", "Bremer Theater e.V.", "900")]
    files = {"q1-2025.xlsx": _hb_xlsx("2025", "45749", q1), "q1-2025.csv": _hb_csv(q1),
             "q2-2025.xlsx": _hb_xlsx("2025", "45839", q2), "q2-2025.csv": _hb_csv(q2)}
    if rlp is not None:
        files[RLP_FILE] = rlp
    tmp.mkdir(parents=True, exist_ok=True)
    for fn, b in files.items():
        (tmp / fn).write_bytes(b)
    sums = {fn: hashlib.sha256(b).hexdigest() for fn, b in files.items()}
    if corrupt:
        sums[corrupt] = "0" * 64
    (tmp / "SHA256SUMS").write_text("".join(f"{h}  {fn}\n" for fn, h in sums.items()), encoding="utf-8")
    return tmp


def _rlp_pdf() -> bytes:
    from ingest.domains.funding_mv import mini_pdf

    def row(y, titel, datum, name_lines, art, betrag, zweck_lines):
        it = [(20, y, "Epl."), (45, y, "06"), (90, y, "MASTD"), (150, y, "06 02"), (190, y, titel), (240, y, datum),
              (470, y, art), (500, y, betrag)]
        for col, x in ((name_lines, 300), (zweck_lines, 560)):
            for i, t in enumerate(col):
                it.append((x, y + (i - (len(col) - 1) / 2) * 11, t))
        return it
    p = [(20, 40, "Ministerium für Arbeit, Soziales, Transformation und Digitalisierung"),
         (300, 70, "Zuwendungsempfänger"), (500, 70, "Höhe"), (560, 70, "Zweck der Zuwendung")]
    p += row(110, "684 53", "11.12.2024", ["Prot. Kirchenbezirk", "Ludwigshafen"], "P", "1.000,00",
             ["Lebensmittelverteilung für die", "Suppenküche Ludwigshafen"])
    p += row(150, "684 19", "27.06.2024", ["Arbeitskammer des Saarlandes"], "P", "37.500,00", ["Task Force Grenzgänger 3.0"])
    p += row(190, "684 50", "01.03.2024", ["Wohnungslosenhilfe Musterstadt e.V."], "P", "12.345,67",
             ["Beratung wohnungsloser Menschen"])
    return mini_pdf([p])


def _test_archive_mode():
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        root = _fixture_archive(Path(d) / "a")
        assert archive_read(root, "q1-2025.xlsx")[:2] == b"PK"
        bad = _fixture_archive(Path(d) / "b", corrupt="q2-2025.xlsx")
        try:
            run(memory_conn(), {"manual_archive": str(bad), "sources": ["hb_zuwendungen"]})
            raise AssertionError("mismatching sha256 parsed")
        except ArchiveError as e:
            assert "sha256" in str(e)
        (root / "extra.xlsx").write_bytes(b"x")
        try:
            archive_read(root, "extra.xlsx")
            raise AssertionError("file without SHA256SUMS entry parsed")
        except ArchiveError as e:
            assert "no SHA256SUMS entry" in str(e)


def _test_classify():
    assert classify("Kälteregelung - Erfrierungsschutz", SOZ)[0] == "core"
    assert classify("Projekt: Housing-First Bremen", SOZ)[0] == "core"
    assert classify("Streetwork Kattenturm", SOZ, "Verein zur Förderung akzeptierender Jugendarbeit e.V.")[0] is None
    assert classify("Kompan - Digital Streetwork für EU-Zugewanderte", SOZ)[0] is None
    assert classify("Team Nord aufsuchende Straßensozialarbeit", SOZ, "Caritasverband Bremen-Nord e.V.")[0] == "adjacent"
    assert classify("Suppenküche", "51 - Die Senatorin für Gesundheit")[0] is None
    assert hb_borderline("Günstiger Mittagstisch ältere Menschen in der Suppenküche", ["suppenküche"])
    assert hb_borderline("Streetwork mal anders - Im Wasser statt an Land", ["streetwork"])
    assert not hb_borderline("Suppenküche für obdachlose Menschen", ["suppenküche"])
    assert not hb_borderline("Kälteregelung - Erfrierungsschutz", ["erfrierungsschutz", "kälteregelung"])
    assert classify("Theaterprojekt", SOZ) == (None, [])
    assert not is_person("Prot. Kirchenbezirk Ludwigshafen") and is_person("Erika Muster")


def _test_hb_reader():
    import tempfile
    from urllib import request
    orig = request.urlopen
    request.urlopen = lambda *a, **k: (_ for _ in ()).throw(AssertionError("network used"))  # manual mode never fetches
    try:
        with tempfile.TemporaryDirectory() as d:
            root = _fixture_archive(Path(d) / "a")
            conn = memory_conn()
            res = run(conn, {"manual_archive": str(root), "sources": ["hb_zuwendungen"]})
            aw = {r["foerder_id"]: dict(r) for r in conn.execute("SELECT * FROM award")}
            assert set(aw) == {"400/3-02/Kälte/2025", "400/SK/2025", "400/FH/2025"}, sorted(aw)
            k = aw["400/3-02/Kälte/2025"]
            assert k["betrag"] == 120320.44 and k["haushaltsjahr"] == "2025" and k["ort_land"] == "HB"   # latest report wins
            assert k["source_id"] == conn.execute("SELECT id FROM source WHERE url=?", (HB_HOST + "q2-2025.xlsx",)).fetchone()[0]
            assert "q2-2025.xlsx" in k["locator"] and HB_PAGES["2025"] in k["locator"] and "manual archive" in k["locator"]
            assert "2 Quartalsbericht(e)" in k["locator"]
            assert "(EUR, Zuwendungssumme bewilligt, Jahr Maßnahmebeginn " in k["locator"], k["locator"]
            assert k["quote"].startswith("[Quartalsbericht Transparenzport!J8]"), k["quote"]
            p = aw["400/FH/2025"]
            assert "Musterstraße" not in (p["zweck"] or "")
            side = {r["gkz"]: dict(r) for r in conn.execute("SELECT * FROM funding_manual_hb")}
            assert side["400/FH/2025"]["stadtteil"] is None and "protected_shelter" in side["400/FH/2025"]["tags"]
            assert side["400/3-02/Kälte/2025"]["reports"] == 2 and side["400/3-02/Kälte/2025"]["csv_check"] == "ok"
            src = conn.execute("SELECT * FROM source WHERE url=?", (HB_HOST + "q2-2025.xlsx",)).fetchone()
            assert src["sha256"] == hashlib.sha256((root / "q2-2025.xlsx").read_bytes()).hexdigest()
            assert "CC BY 3.0" in src["license"] and "manual archive" in src["notes"]
            assert "Erika" not in json.dumps([dict(r) for r in conn.execute("SELECT * FROM org")], ensure_ascii=False)
            assert "in-file duplicates identical 1" in res["notes"] and "skipped persons 1" in res["notes"], res["notes"]
            orgs = {r["name"]: dict(r) for r in conn.execute("SELECT * FROM org")}
            assert orgs["Verein für Innere Mission in Bremen"]["land"] == "HB"
            assert orgs["Frauenhaus Bremen e.V."]["is_protected"] == 1
            assert all(o["name_norm"] == common.name_norm(o["name"]) for o in orgs.values())
            run(conn, {"manual_archive": str(root), "sources": ["hb_zuwendungen"]})
            assert conn.execute("SELECT count(*) FROM award").fetchone()[0] == 3
    finally:
        request.urlopen = orig


def _test_rlp_reader():
    import tempfile
    from ingest.domains import funding_mv as mv
    with tempfile.TemporaryDirectory() as d:
        pdf = _rlp_pdf()
        rows = rlp_rows(pdf)
        assert [r["empfaenger"] for r in rows] == ["Prot. Kirchenbezirk Ludwigshafen", "Arbeitskammer des Saarlandes",
                                                  "Wohnungslosenhilfe Musterstadt e.V."], rows
        assert rows[0]["zweck"] == "Lebensmittelverteilung für die Suppenküche Ludwigshafen" and rows[0]["datum"] == "2024-12-11"
        root = _fixture_archive(Path(d) / "a", rlp=pdf)
        conn = memory_conn()
        res = run(conn, {"manual_archive": str(root), "sources": ["rlp_mastd"]})
        aw = {r["empfaenger"]: dict(r) for r in conn.execute("SELECT * FROM award")}
        assert set(aw) == {"Prot. Kirchenbezirk Ludwigshafen", "Wohnungslosenhilfe Musterstadt e.V."}, set(aw)
        a = aw["Wohnungslosenhilfe Musterstadt e.V."]
        assert a["betrag"] == 12345.67 and a["ort_land"] == "RP" and "12.345,67" in a["quote"]
        lines = [common.clean(x) for x in mv.layout_text(pdf).splitlines()]
        assert all(x["quote"] in lines for x in aw.values())
        assert "Seite 1" in a["locator"] and RLP_PAGE in a["locator"]
        assert "kept 2 (core 1, adjacent 1)" in res["notes"], res["notes"]


def _test_xland_and_same_dataset_links():
    """A national body already in the atlas (other Land) is reused, not re-created for HB; awards from another
    quarterly report of the same dataset link to the org this domain created as origin, not a flagged name match."""
    from ingest import orglink
    ft = _ft()
    conn = memory_conn()
    s0 = common.source_id_for(conn, "https://example.org/lobbyregister/bagw", "funding_officers", title="t",
                              publisher="p", license="l")
    bagw = common.ensure_org(conn, "Bundesarbeitsgemeinschaft Wohnungslosenhilfe e.V.", "BE", s0)
    st = {}
    assert ft.ensure_org_xland(conn, "Bundesarbeitsgemeinschaft Wohnungslosenhilfe e.V.", "HB", s0, stats=st) == bagw
    assert st == {"xland": 1}
    assert conn.execute("SELECT count(*) FROM org WHERE land='HB'").fetchone()[0] == 0
    # two namesakes in other Länder: ambiguous -> a new HB row, never a pick
    common.ensure_org(conn, "Tafel e.V.", "BE", s0)
    common.ensure_org(conn, "Tafel e.V.", "HH", s0)
    t_hb = ft.ensure_org_xland(conn, "Tafel e.V.", "HB", s0, stats=st)
    assert conn.execute("SELECT land FROM org WHERE id=?", (t_hb,)).fetchone()[0] == "HB" and st["xland"] == 1
    # same dataset, two files: org created from file A, award from file B -> origin after sync
    sa = common.source_id_for(conn, HB_HOST + "q1.xlsx", DOMAIN, title="a", publisher="p", license="l")
    sb = common.source_id_for(conn, HB_HOST + "q2.xlsx", DOMAIN, title="b", publisher="p", license="l")
    oid = ft.ensure_org_xland(conn, "Hoppenbank e.V.", "HB", sa)
    for k, sid in (("A", sa), ("B", sb)):
        common.upsert(conn, "award", {"foerder_schluessel": f"DE-HB-ZEBRA:{k}", "foerderart": "zuwendung",
                                      "empfaenger": "Hoppenbank e.V.", "empfaenger_norm": common.name_norm("Hoppenbank e.V."),
                                      "org_id": oid, "betrag": 1.0, "currency": "EUR", "ort_land": "HB", "is_est": 0,
                                      "quote": "x", "locator": "x", "source_id": sid}, keys=["foerder_schluessel"])
    orglink.sync(conn)
    links = {r[0]: (r[1], r[2]) for r in conn.execute(
        "SELECT record_key, method, flagged FROM org_link WHERE record_kind='award'")}
    assert links["DE-HB-ZEBRA:A"] == ("origin", 0) and links["DE-HB-ZEBRA:B"] == ("origin", 0), links


TESTS = [_test_xland_and_same_dataset_links, _test_archive_mode, _test_classify, _test_hb_reader, _test_rlp_reader]


def _run_tests():
    for t in TESTS:
        t()
        print("PASS", t.__name__)


def _selftest(argv):
    """Full run from the manual archive into a scratch DB; the runner's transaction is rolled back."""
    from ingest import run as runner
    from ingest.domains.funding_traeger import scratch_db_path
    conn = runner.open_db(scratch_db_path(argv))
    conn.execute("BEGIN IMMEDIATE")
    conn.runner_txn = True
    try:
        res = run(conn, {})
        print(f"[{DOMAIN}] selftest rows={res['rows']}")
        print(f"[{DOMAIN}]   {res['notes']}")
        assert res["rows"] > 0
        assert conn.execute("SELECT count(*) FROM award WHERE (foerder_schluessel LIKE 'DE-HB-ZEBRA:%' OR "
                            "foerder_schluessel LIKE 'DE-RP-MASTD-%') AND (quote IS NULL OR betrag IS NULL)").fetchone()[0] == 0
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        conn.runner_txn = False
        conn.execute("ROLLBACK")
        conn.close()


def _cli(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="python3 -m ingest.domains.funding_manual", allow_abbrev=False,
                                 description="Worker tools. data/atlas.db is written only by "
                                             "`python3 -m ingest.run funding_manual`.")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--test", action="store_true", help="offline unit tests (in-memory SQLite)")
    mode.add_argument("--selftest", action="store_true", help="manual-archive run into a scratch DB (needs --db)")
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
