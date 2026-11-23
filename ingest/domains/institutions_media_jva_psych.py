"""Official facts on JVA release / Übergangsmanagement and psychiatric hospital beds.

This slice stores cited official facts only. It does not overlap Counts & Law
(Destatis homelessness counts, Wohnungslosenbericht, law, courts). Destatis
Grunddaten der Krankenhäuser (statistic 23111) is a different product, used
here only for psychiatric and psychosomatic hospital beds, clearly labelled.

A change in officially published bed counts is not treated as a documented
hospital closure. Named psychiatric closures need their own official
Drucksache; none was stored in this slice. National psychiatric-care bed
counts in BT-Drs 21/6258 rose between 2014 and 2023.
"""

from __future__ import annotations

import re

from ingest.common import clean, fetch, upsert
from ingest.domains.institutions_media_drogentote import (
    LAND_BY_NAME,
    RESERVED_LICENCE,
    fetch_document_text,
    store_cited_metric,
)
from ingest.domains.institutions_media_orgs import iter_xlsx_sheets

DOMAIN = "institutions_media"
DEST_LICENCE = (
    "Datenlizenz Deutschland – Namensnennung – Version 2.0 (dl-de/by-2-0); "
    "publication imprint: 'Vervielfältigung und Verbreitung, auch auszugsweise, "
    "mit Quellenangabe gestattet.'"
)
DEST_LICENCE_URL = "https://www.govdata.de/dl-de/by-2-0"
BUNDESTAG_IMPRESSUM = "https://www.bundestag.de/impressum"

NRW_1283 = {
    "url": "https://www.landtag.nrw.de/portal/WWW/dokumentenarchiv/Dokument/MMD18-1283.pdf",
    "title": "Landtag NRW Drs 18/1283: Von der Haft in die Wohnungslosigkeit? (Antwort der Landesregierung)",
    "publisher": "Landtag Nordrhein-Westfalen / Landesregierung NRW",
    "published": "2022-10-19",
    "license": (
        "amtliches Werk, § 5 UrhG, scoped to the cited Landtag document text only; "
        "the official PDF states no reuse terms and the Landtag imprint URL "
        "previously tried was not available (HTTP 404)"
    ),
    "license_url": "https://www.landtag.nrw.de/portal/WWW/dokumentenarchiv/Dokument/MMD18-1283.pdf",
    "attribution": "Landtag Nordrhein-Westfalen, Drucksache 18/1283",
}

DRS_6258 = {
    "url": "https://dserver.bundestag.de/btd/21/062/2106258.pdf",
    "title": "BT-Drs 21/6258: psychiatrische und psychosomatische Versorgung (Antwort der Bundesregierung), Anlage 1",
    "publisher": "Deutscher Bundestag / Bundesregierung",
    "published": "2026",
    "license_url": BUNDESTAG_IMPRESSUM,
    "attribution": "Deutscher Bundestag, Drucksache 21/6258; Quelle der Tabelle: Statistisches Bundesamt, Grunddaten der Krankenhäuser, und Eurostat",
}

DESTATIS_23111 = {
    "url": (
        "https://www.destatis.de/DE/Themen/Gesellschaft-Umwelt/Gesundheit/Krankenhauser/"
        "Publikationen/Downloads-Krankenhaeuser/"
        "statistischer-bericht-grunddaten-krankenhaeuser-2120611247005.xlsx?__blob=publicationFile"
    ),
    "title": "Destatis Statistischer Bericht: Grunddaten der Krankenhäuser 2024 (Tabelle 23111-07)",
    "publisher": "Statistisches Bundesamt (Destatis)",
    "published": "2025",
    "attribution": "Statistisches Bundesamt (Destatis), Grunddaten der Krankenhäuser, 2024, Tabelle 23111-07",
}

# Fachabteilung labels in 23111-07 -> metric name
BED_METRICS = {
    "Allgemeine Psychiatrie": "hospital_beds_allgemeine_psychiatrie",
    "Kinder- und Jugendpsychiatrie": "hospital_beds_kinder_jugendpsychiatrie",
    "Psychosomatik/Psychotherapie": "hospital_beds_psychosomatik",
}

HEADER_LAND = [
    ("Deutschland", "DE"),
    ("Baden-Württemberg", "BW"),
    ("Bayern", "BY"),
    ("Berlin", "BE"),
    ("Brandenburg", "BB"),
    ("Bremen", "HB"),
    ("Hamburg", "HH"),
    ("Hessen", "HE"),
    ("Mecklenburg-Vorpommern", "MV"),
    ("Niedersachsen", "NI"),
    ("Nordrhein-Westfalen", "NW"),
    ("Rheinland-Pfalz", "RP"),
    ("Saarland", "SL"),
    ("Sachsen", "SN"),
    ("Sachsen-Anhalt", "ST"),
    ("Schleswig-Holstein", "SH"),
    ("Thüringen", "TH"),
]


def _im():
    from ingest.domains import institutions_media as im
    return im


def _rh():
    from ingest.domains import institutions_media_rechnungshof as rh
    return rh


def _register(conn, url, *, title, publisher, license_, license_url, attribution, notes_text, redistrib, sources) -> int:
    im = _im()
    return im._register_source(
        conn, url, title=title, publisher=publisher, license_=license_,
        license_url=license_url, attribution=attribution, notes=notes_text,
        redistribute_fulltext=redistrib, bucket=sources,
    )


def _store_doc(conn, url, title, publisher, published, source_id, summary, land="DE") -> None:
    upsert(conn, "doc", {
        "kind": "report", "title": title, "url": url, "herausgeber": publisher,
        "urheber": None, "veroeffentlicht": published, "land": land, "zusammenfassung": summary,
        "source_id": source_id,
    }, ["url"])


def parse_psych_care_beds_deutschland(text: str) -> dict[int, int]:
    """Parse BT-Drs 21/6258 Anlage 1, Germany row, years 2014-2023."""
    rh = _rh()
    hay = rh.fold_text(text)
    # 'Deutschland 102.916 103.992 ... 110.943'
    m = re.search(
        r"Deutschland\s+((?:[0-9]{1,3}(?:\.[0-9]{3})+\s+)+[0-9]{1,3}(?:\.[0-9]{3})+)",
        hay,
    )
    if not m:
        return {}
    values = [int(v.replace(".", "")) for v in m.group(1).split()]
    years = list(range(2014, 2014 + len(values)))
    if years[-1] != 2023 and len(values) != 10:
        return {}
    return dict(zip(years, values))


def parse_destatis_psych_beds(sheets: dict[str, list[list[str]]]) -> tuple[list[dict], str]:
    """Parse table 23111-07 (beds by Land and Fachabteilung, 2024)."""
    rows = sheets.get("23111-07") or []
    header_i = None
    for i, row in enumerate(rows):
        joined = " ".join(clean(c) or "" for c in row)
        if "Deutschland" in joined and "Bayern" in joined:
            header_i = i
            break
    if header_i is None:
        return [], ""
    header = rows[header_i]
    # Map columns by folding hyphenated header labels.
    rh = _rh()
    folded_header = [rh.fold_text(c).replace("- ", "").replace("-", "") for c in header]
    col_of: dict[str, int] = {}
    for name, code in HEADER_LAND:
        needle = rh.fold_text(name).replace("-", "").casefold()
        for j, cell in enumerate(folded_header):
            if cell.replace(" ", "").casefold() == needle.replace(" ", "") or cell.casefold() == name.casefold():
                col_of[code] = j
                break
            # hyphenation leftovers e.g. BadenWurttemberg, Niedersachsen from 'Nieder-sachsen'
            compact = cell.replace(" ", "").casefold()
            if needle.replace(" ", "") in compact and code not in col_of:
                # require start or uniqueness later
                pass
        if code not in col_of:
            for j, cell in enumerate(folded_header):
                compact = re.sub(r"[^a-zäöüß]", "", cell.casefold())
                want = re.sub(r"[^a-zäöüß]", "", name.casefold())
                if compact == want or compact.startswith(want[:8]):
                    col_of[code] = j
                    break
    figures = []
    extract_lines = []
    from ingest.common import xlsx_cell_line
    for ri, row in enumerate(rows[header_i + 1:], start=header_i + 1):
        label = clean(row[0]) if row else ""
        if label not in BED_METRICS:
            continue
        metric = BED_METRICS[label]
        for code, j in col_of.items():
            if j >= len(row) or not clean(row[j]):
                continue
            try:
                value = int(float(str(row[j]).replace(" ", "").replace(".", "")))
            except ValueError:
                continue
            name = next(n for n, c in HEADER_LAND if c == code)
            line = f"{label} {name} {value}"
            extract_lines.append(line)
            figures.append({
                "entity_type": "bund" if code == "DE" else "land",
                "entity_id": code if code == "DE" else _im().metric_geo("land", code)[1],
                "metric": metric,
                "year": 2024,
                "value": value,
                "unit": "beds",
                "locator": "Destatis Grunddaten der Krankenhäuser 2024, Tabelle 23111-07, aufgestellte Betten nach Fachabteilung und Land",
                "quote": xlsx_cell_line("23111-07", ri, j, row),
                "note": (
                    "Official 2024 bed snapshot by Fachabteilung. This is not a "
                    "documented hospital closure and is not a Destatis homelessness count."
                ),
            })
    return figures, "\n".join(extract_lines)


def ingest_jva_psych(conn, cfg, sources, notes) -> int:
    """Store JVA Übergangsmanagement facts and psychiatric bed figures. Returns metric count."""
    del cfg
    stored = 0

    # --- NRW Drs 18/1283 ---
    try:
        nrw_text = fetch_document_text(NRW_1283["url"])
    except Exception as exc:
        notes.append(f"jva NRW 18/1283 failed: {type(exc).__name__}: {str(exc)[:180]}")
        nrw_text = None
    if nrw_text:
        sid = _register(
            conn, NRW_1283["url"], title=NRW_1283["title"], publisher=NRW_1283["publisher"],
            license_=NRW_1283["license"], license_url=NRW_1283["license_url"],
            attribution=NRW_1283["attribution"],
            notes_text=(
                "Official Land government answer: no valid data on how many people "
                "leave prison without housing; Entlassungsanschriften are voluntary. "
                "Structured Übergangsmanagement has been rolled out since 2020. "
                "Where no housing can be arranged, a place in a local Notunterkunft is mediated."
            ),
            redistrib=1, sources=sources,
        )
        _store_doc(
            conn, NRW_1283["url"], NRW_1283["title"], NRW_1283["publisher"],
            NRW_1283["published"], sid,
            "No valid NRW data on releases from prison into homelessness (2022). "
            "Structured Übergangsmanagement since 2020.",
            land="NW",
        )
        rec = {
            "entity_type": "land", "entity_id": "05",
            "metric": "jva_release_homeless_data_available",
            "year": 2022, "value": 0, "unit": "flag",
            "locator": "Landtag NRW Drs 18/1283, S. 1, Antwort zu Frage 1",
            "quote": "Der Landesregierung liegen zur Beantwortung dieser Frage keine validen Daten vor.",
            "note": (
                "The Land government says Entlassungsanschriften collected during "
                "release planning are voluntary and are not a valid data basis. "
                "This is a documented official data gap, not a count of zero releases into homelessness."
            ),
        }
        if store_cited_metric(conn, rec, source_id=sid, document_text=nrw_text, notes=notes):
            stored += 1
        if "seit dem Jahr 2020 das strukturierte Übergangsmanagement" in _rh().fold_text(nrw_text):
            notes.append("jva NRW: structured Übergangsmanagement rolled out since 2020 (Drs 18/1283, Frage 2)")
        notes.append(
            "jva: no official national count of releases into homelessness was found. "
            "Other Länder were not ingested in this slice (gap)."
        )

    # --- BT-Drs 21/6258 national psychiatric-care beds 2014-2023 ---
    try:
        drs_text = fetch_document_text(DRS_6258["url"])
    except Exception as exc:
        notes.append(f"psych Drs 21/6258 failed: {type(exc).__name__}: {str(exc)[:180]}")
        drs_text = None
    if drs_text:
        sid = _register(
            conn, DRS_6258["url"], title=DRS_6258["title"], publisher=DRS_6258["publisher"],
            license_=RESERVED_LICENCE, license_url=DRS_6258["license_url"],
            attribution=DRS_6258["attribution"],
            notes_text=(
                "Official government answer, Anlage 1 Tabelle 1: hospital beds in "
                "psychiatric care in Germany 2014-2023, sourced from Destatis Grunddaten "
                "and Eurostat. Bundestag reuse terms are not clearly granted; facts and "
                "short quotes only. National counts rose over the period; this is not a "
                "closure series and not a Destatis homelessness statistic."
            ),
            redistrib=0, sources=sources,
        )
        _store_doc(
            conn, DRS_6258["url"], DRS_6258["title"], DRS_6258["publisher"],
            DRS_6258["published"], sid,
            "Psychiatric-care hospital beds in Germany, 2014-2023 (Destatis Grunddaten / Eurostat). "
            "National stock rose; not a documented closure series.",
        )
        series = parse_psych_care_beds_deutschland(drs_text)
        if series.get(2014) != 102916 or series.get(2023) != 110943:
            notes.append(f"psych Drs 21/6258 unexpected series: {series}")
        for year, value in series.items():
            # Quote uses the official thousands-dot form from the table row.
            dotted = f"{value:,}".replace(",", ".")
            rec = {
                "entity_type": "bund", "entity_id": "DE",
                "metric": "psychiatric_care_hospital_beds",
                "year": year, "value": value, "unit": "beds",
                "locator": "BT-Drs 21/6258, Anlage 1, Tabelle 1, Zeile Deutschland, Jahre 2014-2023",
                "quote": f"Deutschland {dotted}" if year == 2014 else dotted,
                "note": (
                    "Official beds in psychiatric care (Destatis Grunddaten / Eurostat, "
                    "Fachabteilungsgliederung of each year). National stock 2014-2023 "
                    "rose from 102.916 to 110.943; a decline in this series is not documented. "
                    "This is not a named hospital closure and not a homelessness count."
                ),
            }
            if year != 2014:
                # '102.916' etc. all appear in the Deutschland row; the first year
                # quote includes the country name, later years the dotted number.
                rec["quote"] = dotted
            if store_cited_metric(conn, rec, source_id=sid, document_text=drs_text, notes=notes):
                stored += 1
        if series:
            notes.append(
                f"psych care beds DE 2014={series.get(2014)} 2023={series.get(2023)} "
                f"(official national stock increased; no named closures stored)"
            )

    # --- Destatis 2024 Fachabteilung x Land snapshot ---
    try:
        raw = fetch(DESTATIS_23111["url"], domain=DOMAIN)
        sheets = iter_xlsx_sheets(raw) if raw.startswith(b"PK") else {}
    except Exception as exc:
        notes.append(f"psych Destatis 23111 failed: {type(exc).__name__}: {str(exc)[:180]}")
        sheets = {}
    if sheets:
        sid = _register(
            conn, DESTATIS_23111["url"], title=DESTATIS_23111["title"],
            publisher=DESTATIS_23111["publisher"], license_=DEST_LICENCE,
            license_url=DEST_LICENCE_URL, attribution=DESTATIS_23111["attribution"],
            notes_text=(
                "Destatis Grunddaten der Krankenhäuser 2024, table 23111-07 only "
                "(psychiatric / psychosomatic beds by Land). Not statistic 22971 and "
                "not the Wohnungslosenbericht. Imprint permits reproduction with attribution."
            ),
            redistrib=1, sources=sources,
        )
        _store_doc(
            conn, DESTATIS_23111["url"], DESTATIS_23111["title"],
            DESTATIS_23111["publisher"], DESTATIS_23111["published"], sid,
            "2024 hospital beds in Allgemeine Psychiatrie, Kinder- und Jugendpsychiatrie "
            "and Psychosomatik/Psychotherapie, by Land. Snapshot, not a closure series.",
        )
        figures, extract = parse_destatis_psych_beds(sheets)
        # Include official sheet cells plus the serialised 'label Land value' extract
        # built only from those cells, so quotes can be checked.
        # Lead: check quotes against the archived workbook's own rendering only (no added lines).
        from ingest.common import xlsx_text
        document_text = xlsx_text(raw)
        kept = 0
        for rec in figures:
            if store_cited_metric(conn, rec, source_id=sid, document_text=document_text, notes=notes):
                stored += 1
                kept += 1
        notes.append(f"psych Destatis 23111-07 stored={kept} bed figures for 2024")

    notes.append(
        "psych closures: no official Drucksache documenting a named psychiatric hospital "
        "closure was stored. The official national psychiatric-care bed series increased "
        "2014-2023. Do not infer closures from a snapshot or from a local dip (2020)."
    )
    notes.append(f"jva_psych metrics={stored}")
    return stored



if __name__ == "__main__":
    from ingest.common import no_direct_run
    raise SystemExit(no_direct_run("institutions_media"))
