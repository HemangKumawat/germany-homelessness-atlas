"""Organisations for the institutions_media domain.

Slice (a): Jobcenter by Kreis from the official Statistik der Bundesagentur für
Arbeit Gebietsstruktur / Zuordnung tables (Gebietsstand 12.11.2026).
Sozialämter have no single federal directory; Land lists are recorded as gaps
until an official source is ingested.

Slice (b): Wohnungslosenhilfe umbrella bodies, added in a later commit.

This module never opens data/atlas.db. It does not invent AGS codes.
"""
from __future__ import annotations

import re
import zipfile
from xml.etree import ElementTree as ET

from ingest import common
from ingest.common import clean, name_norm, upsert
from ingest.domains.institutions_media_rechnungshof import RESERVED_LICENCE

DOMAIN = "institutions_media"

ORG_DDL = """
CREATE TABLE IF NOT EXISTS institutions_media_org (
  org_id INTEGER PRIMARY KEY,
  role TEXT NOT NULL,
  subtype TEXT,
  traeger_nr TEXT,
  land TEXT,
  kreis_ags TEXT,
  official_url TEXT,
  source_id INTEGER
);
CREATE TABLE IF NOT EXISTS institutions_media_org_kreis (
  org_id INTEGER NOT NULL,
  kreis_ags TEXT NOT NULL,
  kreis_name TEXT,
  source_id INTEGER,
  UNIQUE (org_id, kreis_ags)
);
"""

JOBCENTER_CATALOG = (
    "https://statistik.arbeitsagentur.de/DE/Navigation/Grundlagen/"
    "Klassifikationen/Regionale-Gliederungen/"
    "Gebietsstruktur-Traeger-Grundsicherung-Nav.html"
)
JOBCENTER_ZUORDNUNG = (
    "https://statistik.arbeitsagentur.de/DE/Statischer-Content/Grundlagen/"
    "Klassifikationen/Regionale-Gliederungen/Generische-Publikationen/"
    "Zuordnung-Jobcenter.xlsx?__blob=publicationFile&v=3"
)
JOBCENTER_TYP = (
    "https://statistik.arbeitsagentur.de/DE/Statischer-Content/Grundlagen/"
    "Klassifikationen/Regionale-Gliederungen/"
    "Gebietsstruktur-Traeger-Grundsicherung/Generische-Publikationen/"
    "Gebietsstruktur-Traeger-Grundsicherung-XLS.xlsx?__blob=publicationFile&v=3"
)
STATISTIK_IMPRESSUM = (
    "https://statistik.arbeitsagentur.de/DE/Home/Service/Impressum/impressum_node.html"
)
STATISTIK_LICENCE = (
    "Statistik-Tabellen der BA, frei verwendbar mit Quellenangabe. Official imprint: "
    "'Daten und Tabellen, die die BA aufgrund ihrer gesetzlichen Verpflichtung zur "
    "Erstellung von Statistiken öffentlich zur Verfügung stellt, dürfen uneingeschränkt "
    "verwendet werden. Informationen dürfen (auch auszugsweise) gespeichert und mit "
    "Quellenangabe weitergegeben, vervielfältigt und verbreitet werden. Die Inhalte "
    "dürfen nicht verändert oder verfälscht werden.' "
    "Quellenangabe: © Statistik der Bundesagentur für Arbeit."
)
STATISTIK_ATTRIBUTION = "© Statistik der Bundesagentur für Arbeit"

LAND_BY_NAME = {
    "baden-württemberg": "BW",
    "baden-wuerttemberg": "BW",
    "bayern": "BY",
    "berlin": "BE",
    "brandenburg": "BB",
    "bremen": "HB",
    "hamburg": "HH",
    "hessen": "HE",
    "mecklenburg-vorpommern": "MV",
    "niedersachsen": "NI",
    "nordrhein-westfalen": "NW",
    "rheinland-pfalz": "RP",
    "saarland": "SL",
    "sachsen": "SN",
    "sachsen-anhalt": "ST",
    "schleswig-holstein": "SH",
    "thüringen": "TH",
    "thueringen": "TH",
}

_SS_NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
_REL_ID = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"


def _im():
    from ingest.domains import institutions_media as module
    return module


def ensure_org_tables(conn) -> None:
    conn.executescript(ORG_DDL)
    _im().ensure_source_extensions(conn)
    _im()._add_column(conn, "institutions_media_org", "land_ags", "TEXT")


def land_code(name: str | None) -> str | None:
    raw = clean(name)
    if not raw:
        return None
    if raw in _im().LANDS:
        return raw
    return LAND_BY_NAME.get(raw.casefold())


def official_ags5(value) -> str | None:
    """Return a 5-digit Kreis AGS only when the source supplies the official digits.

    Leading zeros dropped by a spreadsheet cell are restored; other lengths are rejected.
    """
    if value is None:
        return None
    raw = clean(str(value))
    if not raw:
        return None
    if re.fullmatch(r"\d+\.0", raw):
        raw = raw.split(".", 1)[0]
    if not re.fullmatch(r"\d{1,5}", raw):
        return None
    if len(raw) > 5:
        return None
    return raw.zfill(5)


def _col_row(cell_ref: str) -> tuple[int, int]:
    col = "".join(ch for ch in cell_ref if ch.isalpha())
    row = int("".join(ch for ch in cell_ref if ch.isdigit()))
    n = 0
    for ch in col:
        n = n * 26 + (ord(ch.upper()) - 64)
    return n - 1, row - 1


def iter_xlsx_sheets(data: bytes) -> dict[str, list[list[str]]]:
    """Minimal XLSX reader (stdlib only) for official BA Statistik workbooks."""
    from io import BytesIO
    zf = zipfile.ZipFile(BytesIO(data))
    shared = []
    if "xl/sharedStrings.xml" in zf.namelist():
        root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
        for si in root.findall("m:si", _SS_NS):
            shared.append("".join(t.text or "" for t in si.findall(".//m:t", _SS_NS)))
    wb = ET.fromstring(zf.read("xl/workbook.xml"))
    rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
    rid_to_target = {rel.attrib["Id"]: rel.attrib["Target"] for rel in rels}
    out: dict[str, list[list[str]]] = {}
    for sh in wb.findall("m:sheets/m:sheet", _SS_NS):
        name = sh.attrib.get("name") or "sheet"
        target = rid_to_target[sh.attrib[_REL_ID]]
        if not target.startswith("xl/"):
            target = "xl/" + target.lstrip("/")
        root = ET.fromstring(zf.read(target))
        grid = {}
        max_r = max_c = 0
        for c in root.findall("m:sheetData/m:row/m:c", _SS_NS):
            ref = c.attrib.get("r")
            if not ref:
                continue
            ci, ri = _col_row(ref)
            max_r, max_c = max(max_r, ri), max(max_c, ci)
            val = ""
            v = c.find("m:v", _SS_NS)
            is_el = c.find("m:is", _SS_NS)
            if c.attrib.get("t") == "s" and v is not None and v.text is not None:
                val = shared[int(v.text)]
            elif c.attrib.get("t") == "inlineStr" and is_el is not None:
                val = "".join(t.text or "" for t in is_el.findall(".//m:t", _SS_NS))
            elif v is not None and v.text is not None:
                val = v.text
            grid[(ri, ci)] = val
        out[name] = [[grid.get((r, c), "") for c in range(max_c + 1)] for r in range(max_r + 1)]
    zf.close()
    return out


def _header_index(row: list[str], *needles: str) -> int | None:
    lowered = [clean(c).casefold() if clean(c) else "" for c in row]
    for i, cell in enumerate(lowered):
        if all(n.casefold() in cell for n in needles):
            return i
    return None


def parse_jobcenter_zuordnung(rows: list[list[str]]) -> list[dict]:
    header_i = None
    for i, row in enumerate(rows):
        if _header_index(row, "kreisschlüssel") is not None and _header_index(row, "jobcenter") is not None:
            header_i = i
            break
    if header_i is None:
        return []
    header = rows[header_i]
    i_nr = _header_index(header, "träger-nr")
    i_name = _header_index(header, "jobcenter")
    i_ags = _header_index(header, "kreisschlüssel")
    i_kreis = _header_index(header, "kreis")
    # the Kreis name column is exactly "Kreis", not the split-flag columns
    if i_kreis is not None:
        for j, cell in enumerate(header):
            if clean(cell).casefold() == "kreis":
                i_kreis = j
                break
    i_land = _header_index(header, "land")
    if None in (i_nr, i_name, i_ags, i_land):
        return []
    out = []
    for row in rows[header_i + 1:]:
        if max((i_nr or 0), (i_name or 0), (i_ags or 0), (i_land or 0)) >= len(row):
            continue
        name = clean(row[i_name])
        nr = clean(str(row[i_nr]))
        ags = official_ags5(row[i_ags])
        land = land_code(row[i_land])
        kreis = clean(row[i_kreis]) if i_kreis is not None and i_kreis < len(row) else None
        if not name or not name.startswith("Jobcenter") or not nr or not ags or not land:
            continue
        if not re.fullmatch(r"\d{4,6}", nr):
            continue
        out.append({
            "name": name,
            "traeger_nr": nr.zfill(5) if len(nr) <= 5 else nr,
            "kreis_ags": ags,
            "kreis": kreis,
            "land": land,
            "land_name": clean(row[i_land]),
        })
    return out


def parse_jobcenter_types(rows: list[list[str]]) -> dict[str, str]:
    header_i = None
    for i, row in enumerate(rows):
        if _header_index(row, "träger-nr") is not None and _header_index(row, "typ") is not None:
            header_i = i
            break
    if header_i is None:
        return {}
    header = rows[header_i]
    i_typ = _header_index(header, "typ")
    i_nr = _header_index(header, "träger-nr")
    types = {}
    for row in rows[header_i + 1:]:
        if i_typ >= len(row) or i_nr >= len(row):
            continue
        typ = clean(row[i_typ])
        nr = clean(str(row[i_nr]))
        if typ in {"gE", "zkT", "zKT"} and nr and re.fullmatch(r"\d{4,6}", nr):
            types[nr.zfill(5) if len(nr) <= 5 else nr] = "zkT" if typ.lower() == "zkt" else typ
    return types


def _fetch(url: str, *, force: bool) -> bytes:
    return common.fetch(
        url,
        domain=DOMAIN,
        force=force,
        headers={"User-Agent": common.UA, "Accept": "*/*"},
        binary=True,
    )


def store_landscape_org(conn, rec: dict, *, sources) -> int | None:
    ensure_org_tables(conn)
    name = clean(rec.get("name"))
    land = rec.get("land") if rec.get("land") in (_im().LANDS | {"DE"}) else None
    source_url = clean(rec.get("source_url"))
    licence = clean(rec.get("license"))
    if not name or not name_norm(name) or not land or not source_url or not licence:
        return False
    if rec.get("kreis_ags") and not official_ags5(rec.get("kreis_ags")):
        return False
    kreis_ags = official_ags5(rec.get("kreis_ags")) if rec.get("kreis_ags") else None
    source_id = _im()._register_source(
        conn, source_url,
        title=rec.get("source_title") or name,
        publisher=rec.get("publisher") or "Statistik der Bundesagentur für Arbeit",
        license_=licence,
        bucket=sources,
        license_url=clean(rec.get("license_url")),
        attribution=clean(rec.get("attribution")),
        notes=clean(rec.get("source_notes")),
        redistribute_fulltext=0 if rec.get("redistribute_fulltext") == 0 else 1,
    )
    traeger = clean(rec.get("traeger_nr"))
    ba_nr = traeger if traeger and re.fullmatch(r"\d{4,6}", traeger) else None
    qid = clean(rec.get("wikidata_qid") or rec.get("qid"))
    # Court / Lobby / ZUWDB identifiers only. Never treat a BA Träger-Nr as register_id.
    register = clean(rec.get("register_id"))
    if register and ba_nr and register == ba_nr:
        register = None
    def _compatible(cid: int) -> bool:
        if not register:
            return True
        row = conn.execute("SELECT register_id FROM org WHERE id=?", (cid,)).fetchone()
        existing_reg = clean(row["register_id"] if row else None)
        return not (existing_reg and existing_reg != register)

    if ba_nr:
        record_kind, record_key = "ba_jobcenter", f"row:{ba_nr}"
    else:
        record_kind, record_key = "institutions_media_org", f"{name_norm(name)}|{land}|{source_url}"

    # Schema 6: use the id ensure_org returns. A new row from this record is
    # linked as method=origin at confidence 1.0, unflagged. A name-step match
    # is a flagged name_fuzzy link. Never look the org up again by name+Land.
    org_id = common.ensure_org(
        conn, name, land, source_id,
        legal_form=clean(rec.get("legal_form")) or None,
        register=register,
        ust_id=clean(rec.get("ust_id")),
        lei=clean(rec.get("lei")),
        qid=qid,
        ba_traeger=ba_nr,
        record_kind=record_kind,
        record_key=record_key,
        compatible=_compatible if register else None,
        org_type=rec.get("org_type") or "government",
        webseite=clean(rec.get("website")),
        kreis=clean(rec.get("kreis")) if kreis_ags and not rec.get("multi_kreis") else None,
        kreis_ags=None if rec.get("multi_kreis") else kreis_ags,
        registerstatus="active",
        is_protected=0,
        register_id=register,
    )
    if not org_id:
        return None
    # Never write a BA Träger-Nr into org.register_id. Clear leftover values from earlier runs
    # only when the stored value is exactly this official number (not a court register).
    if ba_nr:
        conn.execute(
            "UPDATE org SET register_id=NULL WHERE id=? AND register_id=?",
            (org_id, ba_nr),
        )
        common.link_org(
            conn, record_kind="ba_jobcenter", record_key=f"BA_JC:{ba_nr}",
            org_id=org_id, method="register_id", confidence=1.0, source_id=source_id,
            record_name=name, id_value=f"BA_JC:{ba_nr}",
        )
    if qid:
        from ingest import orglink
        qkey = orglink.qid_key(qid)
        if qkey:
            common.link_org(
                conn, record_kind="wikidata", record_key=qkey,
                org_id=org_id, method="wikidata_qid", confidence=1.0, source_id=source_id,
                record_name=name, id_value=qkey,
            )
    upsert(conn, "institutions_media_org", {
        "org_id": org_id,
        "role": rec.get("role") or "jobcenter",
        "subtype": clean(rec.get("subtype")),
        "traeger_nr": traeger,
        "land": land,
        "kreis_ags": None if rec.get("multi_kreis") else kreis_ags,
        "official_url": source_url,
        "source_id": source_id,
    }, ["org_id"])
    return org_id


def store_org_kreis(conn, org_id: int, kreis_ags: str, kreis_name: str | None, source_id: int) -> bool:
    ags = official_ags5(kreis_ags)
    if not ags or not org_id:
        return False
    upsert(conn, "institutions_media_org_kreis", {
        "org_id": org_id,
        "kreis_ags": ags,
        "kreis_name": clean(kreis_name),
        "source_id": source_id,
    }, ["org_id", "kreis_ags"])
    return True


def ingest_jobcenters(conn, cfg, sources, notes) -> int:
    ensure_org_tables(conn)
    force = bool(cfg.get("force"))
    try:
        typ_raw = _fetch(JOBCENTER_TYP, force=force)
        zu_raw = _fetch(JOBCENTER_ZUORDNUNG, force=force)
    except Exception as exc:
        notes.append(f"Jobcenter Statistik fetch failed: {type(exc).__name__}: {str(exc)[:200]}")
        return 0
    typ_sheets = iter_xlsx_sheets(typ_raw)
    zu_sheets = iter_xlsx_sheets(zu_raw)
    typ_rows = next(iter(typ_sheets.values()), [])
    # prefer the named sheet
    typ_rows = typ_sheets.get("SGB-II-Gebietsstruktur", typ_rows)
    zu_rows = zu_sheets.get("Regionale Zuordnung Jobcenter", next(iter(zu_sheets.values()), []))
    types = parse_jobcenter_types(typ_rows)
    mappings = parse_jobcenter_zuordnung(zu_rows)
    if not mappings:
        notes.append("Jobcenter Zuordnung table produced no official Kreis rows")
        return 0
    grouped: dict[str, list[dict]] = {}
    for rec in mappings:
        grouped.setdefault(rec["traeger_nr"], []).append(rec)
    stored = 0
    missing_typ = 0
    for nr, recs in grouped.items():
        typ = types.get(nr)
        if typ not in {"gE", "zkT"}:
            missing_typ += 1
        first = recs[0]
        lands = {r["land"] for r in recs}
        # A Jobcenter is unique per land in org; all official rows share one Land.
        if len(lands) != 1:
            notes.append(f"Jobcenter {nr} spans multiple Länder; not stored")
            continue
        multi = len({r["kreis_ags"] for r in recs}) > 1
        rec = {
            "name": first["name"],
            "traeger_nr": nr,
            "land": first["land"],
            "kreis": first["kreis"] if not multi else None,
            "kreis_ags": first["kreis_ags"] if not multi else None,
            "multi_kreis": multi,
            "subtype": typ,
            "role": "jobcenter",
            "org_type": "government",
            "source_url": JOBCENTER_ZUORDNUNG,   # Lead: cite the archived official XLSX, not the nav page
            "source_title": "Zuordnung Jobcenterbezirke zu Kreisen und Ländern (Statistik der BA)",
            "publisher": "Statistik der Bundesagentur für Arbeit",
            "license": STATISTIK_LICENCE,
            "license_url": STATISTIK_IMPRESSUM,
            "attribution": STATISTIK_ATTRIBUTION,
            "source_notes": "Gebietsstand 12.11.2026; official Statistik tables, AGS as published",
            "redistribute_fulltext": 1,
        }
        org_id = store_landscape_org(conn, rec, sources=sources)
        if not org_id:
            continue
        source_id = conn.execute(
            "SELECT source_id FROM org WHERE id=?", (org_id,)
        ).fetchone()["source_id"]
        for item in recs:
            store_org_kreis(conn, org_id, item["kreis_ags"], item["kreis"], source_id)
        stored += 1
    typ_counts = {}
    for nr in grouped:
        typ_counts[types.get(nr) or "unknown"] = typ_counts.get(types.get(nr) or "unknown", 0) + 1
    typ_text = ", ".join(f"{k}={v}" for k, v in sorted(typ_counts.items()))
    notes.append(
        f"Jobcenter stored={stored} unique Träger, mapping_rows={len(mappings)}, "
        f"types [{typ_text}], official Gebietsstand 12.11.2026"
    )
    notes.append(
        "Sozialämter: no single official federal directory of örtliche Träger der Sozialhilfe "
        "was found (SGB XII makes Kreise and kreisfreie Städte the local carriers, but that is "
        "not a published office list). Official Land directories exist (e.g. Service Brandenburg, "
        "BayernPortal, LAS Sachsen-Anhalt) and remain a gap this pass."
    )
    if missing_typ:
        notes.append(f"Jobcenter rows missing gE/zkT type: {missing_typ}")
    return stored



BAGW_MEMBERSHIP = "https://www.bagw.de/de/bag-w/mitgliedschaft"
BAGW_HOME = "https://www.bagw.de"
BAGW_IMPRESSUM = "https://www.bagw.de/de/impressum"
BAGW_NAME = "Bundesarbeitsgemeinschaft Wohnungslosenhilfe e.V."

UMBRELLA_SOURCE_NOTES = (
    "Organisation-level entry from the official BAG W membership page; "
    "no member-facility addresses stored"
)


def parse_bagw_korporative(html_text: str) -> list[dict]:
    """Official korporative members (name + href) from the BAG W Mitgliedschaft page."""
    import re
    from html import unescape
    text = html_text or ""
    start = text.casefold().find("korporative mitglieder")
    if start < 0:
        start = text.casefold().find("korporative")
    end = text.casefold().find("mitglieder und mitgliedseinrichtungen", start if start >= 0 else 0)
    chunk = text[start:end] if start >= 0 and end > start else text
    out = []
    seen = set()
    for m in re.finditer(r'<a[^>]+href="([^"]+)"[^>]*>\s*([^<]{3,200})\s*</a>', chunk, re.I):
        url = unescape(m.group(1)).strip()
        name = clean(unescape(m.group(2)))
        if not name or not url or url.startswith("#") or url.startswith("/de/"):
            continue
        if url.startswith("/"):
            url = "https://www.bagw.de" + url
        if not url.startswith("http"):
            continue
        key = (name_norm(name), url)
        if key in seen:
            continue
        seen.add(key)
        out.append({"name": name, "website": url})
    return out


def _website_ok(url: str, *, force: bool) -> bool:
    try:
        _fetch(url, force=force)
        return True
    except Exception:
        return False


def ingest_umbrellas(conn, cfg, sources, notes) -> int:
    """BAG W and its officially listed korporative member associations, organisation level only."""
    ensure_org_tables(conn)
    force = bool(cfg.get("force"))
    try:
        raw = _fetch(BAGW_MEMBERSHIP, force=force)
    except Exception as exc:
        notes.append(f"BAG W membership page failed: {type(exc).__name__}: {str(exc)[:160]}")
        return 0
    html = raw.decode("utf-8", "replace") if isinstance(raw, (bytes, bytearray)) else str(raw)
    members = parse_bagw_korporative(html)
    rows = [{"name": BAGW_NAME, "website": BAGW_HOME, "role": "umbrella", "subtype": "bundesverband"}]
    for mem in members:
        rows.append({**mem, "role": "umbrella", "subtype": "korporatives_mitglied"})
    stored = 0
    skipped = 0
    for rec in rows:
        website = rec.get("website")
        if website and not _website_ok(website, force=force):
            notes.append(f"Umbrella website not verified, stored without website: {rec['name']} {website}")
            website = None
            skipped += 1
        legal = "e.V." if "e.V." in rec["name"] or rec["name"] == BAGW_NAME else None
        ok = store_landscape_org(conn, {
            "name": rec["name"],
            "land": "DE",
            "role": rec["role"],
            "subtype": rec["subtype"],
            "org_type": "nonprofit",
            "legal_form": legal,
            "website": website,
            "source_url": BAGW_MEMBERSHIP,
            "source_title": "Mitgliedschaft in der BAG Wohnungslosenhilfe e.V.",
            "publisher": BAGW_NAME,
            "license": RESERVED_LICENCE,
            "license_url": BAGW_IMPRESSUM,
            "attribution": BAGW_NAME,
            "source_notes": UMBRELLA_SOURCE_NOTES,
            "redistribute_fulltext": 0,
        }, sources=sources)
        if ok:
            stored += 1
    notes.append(
        f"Wohnungslosenhilfe umbrellas stored={stored} (BAG W + korporative members from official membership page); "
        f"websites unverified={skipped}. The page states 240 Träger with 1015 Mitgliedseinrichtungen (Stand Juni 2026) "
        "but does not publish that member directory; those bodies were not stored. "
        "Landesarbeitsgemeinschaften are not listed on this official page; Land-level umbrellas are ingested separately from official Land sites."
    )
    return stored


def ingest_orgs(conn, cfg, sources, notes) -> int:
    skip = set(cfg.get("skip") or [])
    stored = 0
    if "jobcenter" not in skip:
        stored += ingest_jobcenters(conn, cfg, sources, notes)
    if "umbrellas" not in skip:
        stored += ingest_umbrellas(conn, cfg, sources, notes)
    if "lags" not in skip:
        from ingest.domains.institutions_media_lags import ingest_lags
        stored += ingest_lags(conn, cfg, sources, notes)
    return stored



if __name__ == "__main__":
    from ingest.common import no_direct_run
    raise SystemExit(no_direct_run("institutions_media"))
