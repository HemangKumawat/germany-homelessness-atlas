"""PKS victimisation of homeless people (Opferspezifik Obdachlosigkeit) only.

Area-level figures: Bund from official BKA T941 workbooks, Länder from the
Federal Government's answer in BT-Drs 21/2183, which publishes the official
PKS Land tables for 2022-2024. Tatverdächtige 'ohne festen Wohnsitz' are not
ingested. Crime is not framed as caused by homeless people.

PKS tables are under Datenlizenz Deutschland – Namensnennung – Version 2.0
with the required attribution 'PKS Bundeskriminalamt, Berichtsjahr, Version'.
The Bundestagsdrucksache imprint does not grant a general reuse licence, so
Land tables taken from 21/2183 are stored as facts, metadata and short § 51
quotes only (redistribute_fulltext=0).
"""

from __future__ import annotations

import re
from io import BytesIO
import zipfile
import xml.etree.ElementTree as ET

from ingest.common import clean, fetch, upsert
from ingest.domains.institutions_media_drogentote import (
    LAND_BY_NAME,
    RESERVED_LICENCE,
    fetch_document_text,
    pdf_text_from_bytes,
    store_cited_metric,
)
from ingest.domains.institutions_media_orgs import iter_xlsx_sheets

DOMAIN = "institutions_media"
PKS_LICENCE = "Datenlizenz Deutschland – Namensnennung – Version 2.0 (dl-de/by-2-0)"
PKS_LICENCE_URL = "https://www.govdata.de/dl-de/by-2-0"
PKS_FAQ = (
    "https://www.bka.de/DE/AktuelleInformationen/StatistikenLagebilder/"
    "PolizeilicheKriminalstatistik/FAQs/FAQs_node.html"
)
BUNDESTAG_IMPRESSUM = "https://www.bundestag.de/impressum"

# Official T941 Bund workbooks (Opferspezifik — Opfer wegen persönlicher Beeinträchtigung).
T941 = {
    2024: {
        "url": (
            "https://www.bka.de/SharedDocs/Downloads/DE/Publikationen/"
            "PolizeilicheKriminalstatistik/2024/Bund/Opfer/"
            "BU-O-14-T941-Beeintraechtigung_xls.xlsx?__blob=publicationFile&v=2"
        ),
        "version": "V1.0",
        "version_date": "07.02.2025",
        "title": "PKS 2024 Tabelle 941 — Opferspezifik, Opfer wegen persönlicher Beeinträchtigung",
    },
    2023: {
        "url": (
            "https://www.bka.de/SharedDocs/Downloads/DE/Publikationen/"
            "PolizeilicheKriminalstatistik/2023/Bund/Opfer/"
            "BU-O-14-T941-Beeintraechtigung_xls.xlsx?__blob=publicationFile&v=2"
        ),
        "version": "V1.0",
        "version_date": "19.02.2024",
        "title": "PKS 2023 Tabelle 941 — Opferspezifik, Opfer wegen persönlicher Beeinträchtigung",
    },
    2022: {
        "url": (
            "https://www.bka.de/SharedDocs/Downloads/DE/Publikationen/"
            "PolizeilicheKriminalstatistik/2022/Bund/Opfer/"
            "BU-O-14-T941-Beeintraechtigung_xls.xlsx?__blob=publicationFile&v=2"
        ),
        "version": "V1.0",
        "version_date": "14.02.2023",
        "title": "PKS 2022 Tabelle 941 — Opferspezifik, Opfer wegen persönlicher Beeinträchtigung",
    },
}

DRS_2183 = {
    "url": "https://dserver.bundestag.de/btd/21/021/2102183.pdf",
    "title": "BT-Drs 21/2183: Straftaten gegen obdach- und wohnungslose Menschen (Antwort der Bundesregierung)",
    "publisher": "Deutscher Bundestag / Bundesregierung",
    "published": "2025-10-10",
}

# Offence rows stored from T941 (Bund only). Keys are PKS Schlüssel.
T941_OFFENCE_METRICS = {
    "------": "pks_victims_obdachlosigkeit",
    "220000": "pks_victims_obdachlosigkeit_koerperverletzung",
    "892000": "pks_victims_obdachlosigkeit_gewaltkriminalitaet",
    "210000": "pks_victims_obdachlosigkeit_raub",
}

CAVEAT = (
    "PKS Opferspezifik 'Obdachlosigkeit' counts victimisations, not unique people: "
    "a person who was a victim more than once is counted more than once. Figures "
    "cover completed and attempted offences against highly personal legal interests "
    "(life, bodily integrity, freedom, honour, sexual self-determination). A case is "
    "counted only when police findings show the offence was motivated by, or factually "
    "linked to, the victim's homelessness (sachlicher Zusammenhang). This is area-level "
    "victimisation of homeless people, not offending by homeless people. "
    "Tatverdächtige 'ohne festen Wohnsitz' are not stored."
)


def _im():
    from ingest.domains import institutions_media as im
    return im


def _rh():
    from ingest.domains import institutions_media_rechnungshof as rh
    return rh


def xlsx_col_ref(ci: int, ri: int) -> str:
    from ingest.common import xlsx_col
    return f"{xlsx_col(ci)}{ri + 1}"


def pks_attribution(year: int, version: str) -> str:
    return f"PKS Bundeskriminalamt, {year}, {version}"


def t941_sheet_text(rows: list[list[str]]) -> str:
    """Linearise the official workbook so quotes can be checked against cell text."""
    lines = []
    for row in rows:
        cells = [clean(c) for c in row if clean(c)]
        if cells:
            lines.append(" ".join(cells))
    return "\n".join(lines)


def parse_t941_obdach_totals(rows: list[list[str]]) -> dict:
    """Return Bund totals and selected offence rows for Opferspezifik Obdachlosigkeit.

    Layout (verified on official 2022-2024 workbooks): row with 'Obdachlosigkeit'
    is the group header; the next row has insg./männl./weibl. repeated; the
    'Straftaten insgesamt' / Fallstatus 'insg.' row holds the headline counts
    in the Obdachlosigkeit columns (the last three value columns).
    """
    header_i = None
    oc = None
    for i, row in enumerate(rows):
        for j, cell in enumerate(row):
            label = clean(cell) or ""
            if label == "Obdachlosigkeit" or label.startswith("Obdachlosigkeit"):
                header_i, oc = i, j
                break
        if header_i is not None:
            break
    if header_i is None or oc is None:
        return {}
    out = {"offences": {}}
    out["oc"] = oc
    for ri, row in enumerate(rows[header_i + 1:], start=header_i + 1):
        if len(row) <= oc + 2:
            continue
        key = clean(row[0]) if row else ""
        offence = clean(row[1]) if len(row) > 1 else ""
        status = clean(row[2]) if len(row) > 2 else ""
        if status != "insg.":
            continue
        try:
            total = int(float(str(row[oc]).replace(" ", "").replace(".", ""))) if clean(row[oc]) else None
            male = int(float(str(row[oc + 1]).replace(" ", "").replace(".", ""))) if clean(row[oc + 1]) else None
            female = int(float(str(row[oc + 2]).replace(" ", "").replace(".", ""))) if clean(row[oc + 2]) else None
        except ValueError:
            continue
        rec = {"key": key or "------", "offence": offence, "total": total, "male": male, "female": female, "ri": ri}
        if offence == "Straftaten insgesamt" or (key in {None, "", "------"} and "Straftaten insgesamt" in (offence or "")):
            out["total"] = rec
        if key in T941_OFFENCE_METRICS:
            out["offences"][key] = rec
    return out


def parse_drs_land_tables(text: str) -> dict[int, list[dict]]:
    """Parse the official Land tables in BT-Drs 21/2183 for 2022-2024."""
    rh = _rh()
    hay = rh.fold_text(text)
    # Split by Berichtsjahr headings
    parts = re.split(r"Berichtsjahr\s+(20\d{2})", hay)
    # parts: preamble, year, body, year, body...
    out: dict[int, list[dict]] = {}
    # Prefer longer names first so Sachsen-Anhalt is not eaten by Sachsen.
    names = sorted(LAND_BY_NAME.keys(), key=len, reverse=True)
    name_re = "|".join(re.escape(n) for n in names)
    # Thousands in the Drs use a space (2 194). Do not let the first group
    # swallow the following columns (that would parse 2 194 1 as 21941).
    num = r"(?:[0-9]{1,3}(?:[ \u00a0][0-9]{3})+|[0-9]{1,4})"
    row_re = re.compile(
        rf"({name_re})\s+({num})\s+({num})\s+({num})"
    )
    if len(parts) < 3:
        return out
    for i in range(1, len(parts), 2):
        year = int(parts[i])
        body = parts[i + 1] if i + 1 < len(parts) else ""
        # Only the first table in each year (gesamt / männlich / weiblich),
        # not later Kreis tables.
        end = body.find("Landkreis")
        chunk = body[:end] if end >= 0 else body
        rows = []
        seen = set()
        for m in row_re.finditer(chunk):
            name, g, m_, f = m.group(1), m.group(2), m.group(3), m.group(4)
            code = LAND_BY_NAME[name]
            if code in seen:
                continue
            seen.add(code)
            def _n(s: str) -> int:
                return int(s.replace(" ", "").replace("\u00a0", ""))
            rows.append({
                "name": name,
                "entity_id": code,
                "entity_type": "bund" if code == "DE" else "land",
                "total": _n(g),
                "male": _n(m_),
                "female": _n(f),
            })
        # The year heading can reappear later in the same Drs (footnotes, other
        # tables). Keep the first complete Land table and never replace it with a
        # shorter later match.
        if year in out and len(out[year]) >= len(rows):
            continue
        if not rows:
            continue
        has_bund = any(r["entity_id"] == "DE" for r in rows)
        lands = [r for r in rows if r["entity_id"] != "DE"]
        if not has_bund and len(lands) < 10:
            continue
        out[year] = rows
    return out


def _register_pks(conn, url, *, title, year, version, sources) -> int:
    im = _im()
    return im._register_source(
        conn, url,
        title=title,
        publisher="Bundeskriminalamt",
        license_=PKS_LICENCE,
        license_url=PKS_LICENCE_URL,
        attribution=pks_attribution(year, version),
        notes=CAVEAT + " Official terms: " + PKS_FAQ,
        redistribute_fulltext=1,
        bucket=sources,
    )


def _register_drs(conn, sources) -> int:
    im = _im()
    return im._register_source(
        conn, DRS_2183["url"],
        title=DRS_2183["title"],
        publisher=DRS_2183["publisher"],
        license_=RESERVED_LICENCE,
        license_url=BUNDESTAG_IMPRESSUM,
        attribution="Deutscher Bundestag, Drucksache 21/2183; underlying figures: PKS Bundeskriminalamt",
        notes=(
            "Official government answer publishing PKS Land tables for Opferspezifik "
            "Obdachlosigkeit. Bundestag reuse terms are not clearly granted in the PDF; "
            "facts, metadata and short quotes only. " + CAVEAT
        ),
        redistribute_fulltext=0,
        bucket=sources,
    )


def _store_doc(conn, url, title, publisher, published, source_id, summary) -> None:
    upsert(conn, "doc", {
        "kind": "report",
        "title": title,
        "url": url,
        "herausgeber": publisher,
        "urheber": None,
        "veroeffentlicht": published,
        "land": "DE",
        "zusammenfassung": summary,
        "source_id": source_id,
    }, ["url"])


def ingest_pks(conn, cfg, sources, notes) -> int:
    """Store area-level PKS victimisation figures. Returns metric count."""
    del cfg
    stored = 0
    rh = _rh()

    # Bund from official T941 workbooks
    bund_totals = {}
    for year, meta in T941.items():
        try:
            raw = fetch(meta["url"], domain=DOMAIN)
        except Exception as exc:
            notes.append(f"pks T941 {year} failed: {type(exc).__name__}: {str(exc)[:180]}")
            continue
        if not raw.startswith(b"PK"):
            notes.append(f"pks T941 {year} is not an xlsx")
            continue
        sheets = iter_xlsx_sheets(raw)
        # Official sheet name is Tab941
        sheet_name = "Tab941" if "Tab941" in sheets else next(iter(sheets), "")
        rows = sheets.get(sheet_name) or []
        parsed = parse_t941_obdach_totals(rows)
        text = t941_sheet_text(rows)
        if "Tatverdächtige" in text and "ohne festen Wohnsitz" in text:
            notes.append(f"pks T941 {year} unexpected suspect table; skipped")
            continue
        if "Obdachlosigkeit" not in text:
            notes.append(f"pks T941 {year} has no Obdachlosigkeit column; skipped")
            continue
        sid = _register_pks(conn, meta["url"], title=meta["title"], year=year, version=meta["version"], sources=sources)
        _store_doc(
            conn, meta["url"], meta["title"], "Bundeskriminalamt",
            meta["version_date"], sid,
            "Bund: victims with Opferspezifik Obdachlosigkeit. " + CAVEAT,
        )
        total = parsed.get("total") or parsed.get("offences", {}).get("------")
        if not total:
            notes.append(f"pks T941 {year} totals not parsed")
            continue
        bund_totals[year] = total["total"]
        # Lead: quotes are cell-addressed lines of the archived workbook (common.xlsx_text),
        # never lines added to the text by this module, and never a bare number.
        from ingest.common import xlsx_cell_line, xlsx_text
        oc = parsed["oc"]
        trow = rows[total["ri"]]
        figures = [
            {"entity_type": "bund", "entity_id": "DE", "metric": "pks_victims_obdachlosigkeit",
             "year": year, "value": total["total"], "unit": "victims",
             "locator": f"Tabelle 941, Straftaten insgesamt, Fallstatus insg., Spalte Obdachlosigkeit, {meta['version']} erstellt am {meta['version_date']} (Zelle {sheet_name}!{xlsx_col_ref(oc, total['ri'])})",
             "quote": xlsx_cell_line(sheet_name, total["ri"], oc, trow),
             "note": CAVEAT},
            {"entity_type": "bund", "entity_id": "DE", "metric": "pks_victims_obdachlosigkeit_male",
             "year": year, "value": total["male"], "unit": "victims",
             "locator": f"Tabelle 941, Straftaten insgesamt, Fallstatus insg., Spalte Obdachlosigkeit männl., {meta['version']} (Zelle {sheet_name}!{xlsx_col_ref(oc + 1, total['ri'])})",
             "quote": xlsx_cell_line(sheet_name, total["ri"], oc + 1, trow),
             "note": CAVEAT},
            {"entity_type": "bund", "entity_id": "DE", "metric": "pks_victims_obdachlosigkeit_female",
             "year": year, "value": total["female"], "unit": "victims",
             "locator": f"Tabelle 941, Straftaten insgesamt, Fallstatus insg., Spalte Obdachlosigkeit weibl., {meta['version']} (Zelle {sheet_name}!{xlsx_col_ref(oc + 2, total['ri'])})",
             "quote": xlsx_cell_line(sheet_name, total["ri"], oc + 2, trow),
             "note": CAVEAT},
        ]
        for key, metric in T941_OFFENCE_METRICS.items():
            if key == "------":
                continue
            rec = parsed.get("offences", {}).get(key)
            if not rec:
                continue
            figures.append({
                "entity_type": "bund", "entity_id": "DE", "metric": metric,
                "year": year, "value": rec["total"], "unit": "victims",
                "locator": f"Tabelle 941, Schlüssel {key}, Fallstatus insg., Spalte Obdachlosigkeit (Zelle {sheet_name}!{xlsx_col_ref(oc, rec['ri'])})",
                "quote": xlsx_cell_line(sheet_name, rec["ri"], oc, rows[rec["ri"]]),
                "note": CAVEAT + " PKS offence groups can overlap; they are not additive.",
            })
        archived_text = xlsx_text(raw)
        for rec in figures:
            if store_cited_metric(conn, rec, source_id=sid, document_text=archived_text, notes=notes):
                stored += 1
        notes.append(
            f"pks T941 {year} Bund Opferspezifik Obdachlosigkeit insg.={total['total']} "
            f"(männl.={total['male']}, weibl.={total['female']})"
        )

    # Land tables from official government answer
    try:
        drs_text = fetch_document_text(DRS_2183["url"])
    except Exception as exc:
        notes.append(f"pks Drs 21/2183 failed: {type(exc).__name__}: {str(exc)[:180]}")
        drs_text = None
    if drs_text:
        sid = _register_drs(conn, sources)
        _store_doc(
            conn, DRS_2183["url"], DRS_2183["title"], DRS_2183["publisher"],
            DRS_2183["published"], sid,
            "Land-level PKS victims with Opferspezifik Obdachlosigkeit, 2022-2024. " + CAVEAT,
        )
        tables = parse_drs_land_tables(drs_text)
        for year, rows in sorted(tables.items()):
            lands = [r for r in rows if r["entity_id"] != "DE"]
            de = next((r for r in rows if r["entity_id"] == "DE"), None)
            notes.append(
                f"pks Drs 21/2183 {year}: {len(lands)} Länder"
                + (f", Bund {de['total']}" if de else "")
            )
            if de and year in bund_totals and de["total"] != bund_totals[year]:
                notes.append(
                    f"pks mismatch {year}: T941 Bund {bund_totals[year]} vs Drs {de['total']}"
                )
            for rec in rows:
                if rec["entity_id"] == "DE":
                    # Bund totals already stored from T941 (same numbers). Skip overwrite.
                    continue
                quote = f"{rec['name']} {rec['total']}"
                # Thousands in the PDF use a space (2 194); Land values under 1000 are plain.
                fig = {
                    "entity_type": "land", "entity_id": _im().metric_geo("land", rec["entity_id"])[1],
                    "metric": "pks_victims_obdachlosigkeit",
                    "year": year, "value": rec["total"], "unit": "victims",
                    "locator": f"BT-Drs 21/2183, Berichtsjahr {year}, Tabelle Anzahl der Opfer mit Opferspezifik „Obdachlosigkeit“",
                    "quote": quote, "note": CAVEAT,
                }
                male = {
                    **fig, "metric": "pks_victims_obdachlosigkeit_male",
                    "value": rec["male"],
                    "locator": f"BT-Drs 21/2183, Berichtsjahr {year}, Spalte männlich",
                    "quote": f"{rec['name']} {rec['total']} {rec['male']} {rec['female']}",
                }
                female = {
                    **fig, "metric": "pks_victims_obdachlosigkeit_female",
                    "value": rec["female"],
                    "locator": f"BT-Drs 21/2183, Berichtsjahr {year}, Spalte weiblich",
                    "quote": f"{rec['name']} {rec['total']} {rec['male']} {rec['female']}",
                }
                for item in (fig, male, female):
                    if store_cited_metric(conn, item, source_id=sid, document_text=drs_text, notes=notes):
                        stored += 1
        if 2025 not in tables:
            notes.append("pks: no official T941 2025 or Drs Land table for 2025 was found")
        notes.append(
            "pks: the top-25 Landkreis list in BT-Drs 21/2183 is a selected ranking, "
            "not a complete Kreis series, and was not ingested, to avoid 'Brennpunkte' framing. "
            "No Land-level machine-readable T941 workbook was found on the BKA Bund pages."
        )
    notes.append(f"pks metrics={stored}")
    return stored



if __name__ == "__main__":
    from ingest.common import no_direct_run
    raise SystemExit(no_direct_run("institutions_media"))
