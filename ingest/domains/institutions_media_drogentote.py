"""Official drug-death (Rauschgifttote / Drogentote) figures for the institutions/media domain.

Sources are the BKA Bundeslagebild Rauschgiftkriminalität and the tables published
by the Federal Government Commissioner for Addiction and Drug Issues
(Quelle: Bundeskriminalamt Wiesbaden). Every stored number must appear in the
cited document together with a locator and a short quote. These publications do
not report deaths among wohnungslose people specifically; that is recorded as a
gap, not as a zero.

BKA and Drogenbeauftragter imprints reserve rights in website and publication
texts, so only facts, metadata and short § 51 quotes are stored
(redistribute_fulltext=0).
"""

from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path

from ingest.common import clean, fetch, upsert

DOMAIN = "institutions_media"

BKA_IMPRESSUM = "https://www.bka.de/DE/Service/Impressum/impressum_node.html"
CDB_IMPRESSUM = "https://www.bundesdrogenbeauftragter.de/impressum/"
RESERVED_LICENCE = (
    "Rechte vorbehalten (Impressum zitiert); nur Fakten, Metadaten und Kurzzitate "
    "nach § 51 UrhG, Volltext nicht weiterverbreitet"
)
RESERVED_LICENCE_NOTE = (
    "BKA imprint (Urheberrecht): contents of the website are copyrighted; "
    "reproduction outside the limits of copyright requires the author's written "
    "consent; copies are permitted only for private use. The Drogenbeauftragter "
    "imprint does not grant a general text reuse licence. Facts, metadata and "
    "short quotes only."
)

LAND_BY_NAME = {
    "Baden-Württemberg": "BW",
    "Bayern": "BY",
    "Berlin": "BE",
    "Brandenburg": "BB",
    "Bremen": "HB",
    "Hamburg": "HH",
    "Hessen": "HE",
    "Mecklenburg-Vorpommern": "MV",
    "Niedersachsen": "NI",
    "Nordrhein-Westfalen": "NW",
    "Rheinland-Pfalz": "RP",
    "Saarland": "SL",
    "Sachsen": "SN",
    "Sachsen-Anhalt": "ST",
    "Schleswig-Holstein": "SH",
    "Thüringen": "TH",
    "Deutschland": "DE",
    "Bundesrepublik Deutschland": "DE",
    "Summe": "DE",
}

SOURCES = {
    "lagebild_2025": {
        "url": (
            "https://www.bka.de/SharedDocs/Downloads/DE/Publikationen/"
            "JahresberichteUndLagebilder/Rauschgiftkriminalitaet/"
            "2025RauschgiftBundeslagebild.pdf?__blob=publicationFile&v=5"
        ),
        "title": "Rauschgiftkriminalität: Bundeslagebild 2025",
        "publisher": "Bundeskriminalamt",
        "published": "2026",
        "license_url": BKA_IMPRESSUM,
        "attribution": "Bundeskriminalamt, Bundeslagebild Rauschgiftkriminalität 2025",
    },
    "lagebild_2024": {
        "url": (
            "https://www.bka.de/SharedDocs/Downloads/DE/Publikationen/"
            "JahresberichteUndLagebilder/Rauschgiftkriminalitaet/"
            "2024RauschgiftBundeslagebild.pdf?__blob=publicationFile&v=7"
        ),
        "title": "Rauschgiftkriminalität: Bundeslagebild 2024",
        "publisher": "Bundeskriminalamt",
        "published": "2025-10-24",
        "license_url": BKA_IMPRESSUM,
        "attribution": "Bundeskriminalamt, Bundeslagebild Rauschgiftkriminalität 2024",
    },
    "lagebild_2023": {
        "url": (
            "https://www.bka.de/SharedDocs/Downloads/DE/Publikationen/"
            "JahresberichteUndLagebilder/Rauschgiftkriminalitaet/"
            "2023RauschgiftBundeslagebild.pdf?__blob=publicationFile&v=6"
        ),
        "title": "Rauschgiftkriminalität: Bundeslagebild 2023",
        "publisher": "Bundeskriminalamt",
        "published": "2024",
        "license_url": BKA_IMPRESSUM,
        "attribution": "Bundeskriminalamt, Bundeslagebild Rauschgiftkriminalität 2023",
    },
    "lagebild_2022": {
        "url": (
            "https://www.bka.de/SharedDocs/Downloads/DE/Publikationen/"
            "JahresberichteUndLagebilder/Rauschgiftkriminalitaet/"
            "2022RauschgiftBundeslagebild.pdf?__blob=publicationFile&v=2"
        ),
        "title": "Rauschgiftkriminalität: Bundeslagebild 2022",
        "publisher": "Bundeskriminalamt",
        "published": "2023",
        "license_url": BKA_IMPRESSUM,
        "attribution": "Bundeskriminalamt, Bundeslagebild Rauschgiftkriminalität 2022",
    },
    "cdr_2025": {
        "url": (
            "https://www.bundesdrogenbeauftragter.de/assets/Presse/2026/"
            "260707_Drogenbedingte_Todesfaelle_2025_Tabelle.pdf"
        ),
        "title": "Drogenbedingte Todesfälle 2025 (Tabelle, Quelle: BKA Wiesbaden)",
        "publisher": "Beauftragter der Bundesregierung für Sucht- und Drogenfragen",
        "published": "2026-07-07",
        "license_url": CDB_IMPRESSUM,
        "attribution": "Beauftragter der Bundesregierung für Sucht- und Drogenfragen, Quelle: Bundeskriminalamt Wiesbaden",
    },
    "cdr_2024": {
        "url": (
            "https://www.bundesdrogenbeauftragter.de/assets/Presse/2025/"
            "CDR_2024_RG_Todesfaelle.pdf"
        ),
        "title": "Rauschgifttodesfälle 2024 (Tabelle, Quelle: BKA Wiesbaden)",
        "publisher": "Beauftragter der Bundesregierung für Sucht- und Drogenfragen",
        "published": "2025",
        "license_url": CDB_IMPRESSUM,
        "attribution": "Beauftragter der Bundesregierung für Sucht- und Drogenfragen, Quelle: Bundeskriminalamt Wiesbaden",
    },
    "cdr_land_2022": {
        "url": (
            "https://www.bundesdrogenbeauftragter.de/assets/Presse/2023/"
            "CDR_RG-Tote_nach_Bundesl%C3%A4ndern.pdf"
        ),
        "title": "Anzahl der Rauschgifttoten nach Bundesländern 2022 (Quelle: BKA Wiesbaden)",
        "publisher": "Beauftragter der Bundesregierung für Sucht- und Drogenfragen",
        "published": "2023-05-11",
        "license_url": CDB_IMPRESSUM,
        "attribution": "Beauftragter der Bundesregierung für Sucht- und Drogenfragen, Quelle: Bundeskriminalamt Wiesbaden",
        "notes": (
            "PDF table heading is 'Anzahl der Rauschgifttoten' and does not itself "
            "print the year; the official 11.05.2023 press release '2022 erneuter "
            "Anstieg bei Zahl der Drogentoten' publishes this file as 'Rauschgift-Tote "
            "nach Bundesländern' for 2022. The sums match the 2022 BKA Lagebild "
            "(1.990; Nordrhein-Westfalen 703, Bayern 277, Berlin 230)."
        ),
    },
}

# Curated figures. Quotes must appear in the official document text after fetch.
FIGURES: list[dict] = [
    # 2025 national — Lagebild p. 23
    {"source": "lagebild_2025", "entity_type": "bund", "entity_id": "DE", "metric": "drug_deaths",
     "year": 2025, "value": 2150, "unit": "persons", "locator": "S. 23, Abschnitt 2.4 Rauschgifttote",
     "quote": "Im Jahr 2025 wurden in Deutschland polizeilich insgesamt 2.150 drogenbedingte Todesfälle registriert."},
    {"source": "lagebild_2025", "entity_type": "bund", "entity_id": "DE", "metric": "drug_deaths_male",
     "year": 2025, "value": 1777, "unit": "persons", "locator": "S. 23, Abschnitt 2.4 Rauschgifttote",
     "quote": "Unter den Drogentoten des Jahres 2025 waren 1.777 Männer (82,7 %) und 373 Frauen (17,3 %)."},
    {"source": "lagebild_2025", "entity_type": "bund", "entity_id": "DE", "metric": "drug_deaths_female",
     "year": 2025, "value": 373, "unit": "persons", "locator": "S. 23, Abschnitt 2.4 Rauschgifttote",
     "quote": "Unter den Drogentoten des Jahres 2025 waren 1.777 Männer (82,7 %) und 373 Frauen (17,3 %)."},
    {"source": "cdr_2025", "entity_type": "bund", "entity_id": "DE", "metric": "drug_deaths_mean_age",
     "year": 2025, "value": 40.61, "unit": "years", "locator": "Tabelle, Zeile Durchschnittsalter aller RG-Toten",
     "quote": "Durchschnittsalter aller RG-Toten 40,61"},
    # 2024 national — Lagebild p. 21 and CDR table
    {"source": "lagebild_2024", "entity_type": "bund", "entity_id": "DE", "metric": "drug_deaths",
     "year": 2024, "value": 2137, "unit": "persons", "locator": "S. 21",
     "quote": "Im Jahr 2024 wurden in Deutschland polizeilich insgesamt 2.137 drogenbedingte Todesfälle registriert."},
    {"source": "lagebild_2024", "entity_type": "bund", "entity_id": "DE", "metric": "drug_deaths_male",
     "year": 2024, "value": 1747, "unit": "persons", "locator": "S. 21",
     "quote": "Unter den Drogentoten des Jahres 2024 waren 1.747 Männer (81,8 %) und 390 Frauen."},
    {"source": "lagebild_2024", "entity_type": "bund", "entity_id": "DE", "metric": "drug_deaths_female",
     "year": 2024, "value": 390, "unit": "persons", "locator": "S. 21",
     "quote": "Unter den Drogentoten des Jahres 2024 waren 1.747 Männer (81,8 %) und 390 Frauen."},
    {"source": "cdr_2024", "entity_type": "bund", "entity_id": "DE", "metric": "drug_deaths_mean_age",
     "year": 2024, "value": 40.7, "unit": "years", "locator": "Tabelle, Zeile Durchschnittsalter aller RG-Toten",
     "quote": "Durchschnittsalter aller RG-Toten 40,7"},
    # 2024 Land highlights from Lagebild running text (no complete official Land table found)
    {"source": "lagebild_2024", "entity_type": "land", "entity_id": "05", "metric": "drug_deaths",
     "year": 2024, "value": 769, "unit": "persons", "locator": "S. 21",
     "quote": "Nordrhein-Westfalen (769 Tote) und Bayern (214 Tote) sowie in Berlin (294 Tote)"},
    {"source": "lagebild_2024", "entity_type": "land", "entity_id": "09", "metric": "drug_deaths",
     "year": 2024, "value": 214, "unit": "persons", "locator": "S. 21",
     "quote": "Nordrhein-Westfalen (769 Tote) und Bayern (214 Tote) sowie in Berlin (294 Tote)"},
    {"source": "lagebild_2024", "entity_type": "land", "entity_id": "11", "metric": "drug_deaths",
     "year": 2024, "value": 294, "unit": "persons", "locator": "S. 21",
     "quote": "Nordrhein-Westfalen (769 Tote) und Bayern (214 Tote) sowie in Berlin (294 Tote)"},
    {"source": "lagebild_2024", "entity_type": "land", "entity_id": "14", "metric": "drug_deaths",
     "year": 2024, "value": 28, "unit": "persons", "locator": "S. 21",
     "quote": "Sachsen (28 Rauschgifttote, + 40 %)"},
    {"source": "lagebild_2024", "entity_type": "land", "entity_id": "08", "metric": "drug_deaths",
     "year": 2024, "value": 195, "unit": "persons", "locator": "S. 21",
     "quote": "Baden-Württemberg (195 Rauschgifttote, + 38,3 %)"},
    {"source": "lagebild_2024", "entity_type": "land", "entity_id": "04", "metric": "drug_deaths",
     "year": 2024, "value": 35, "unit": "persons", "locator": "S. 21",
     "quote": "Bremen (35 Rauschgifttote, + 29,6 %)"},
    {"source": "lagebild_2024", "entity_type": "land", "entity_id": "07", "metric": "drug_deaths",
     "year": 2024, "value": 33, "unit": "persons", "locator": "S. 21",
     "quote": "Rheinland-Pfalz (33 Tote, - 43,1 %)"},
    {"source": "lagebild_2024", "entity_type": "land", "entity_id": "12", "metric": "drug_deaths",
     "year": 2024, "value": 17, "unit": "persons", "locator": "S. 21",
     "quote": "Brandenburg (17 Tote, - 37 %)"},
    # 2023 national + partial Land — Lagebild p. 23
    {"source": "lagebild_2023", "entity_type": "bund", "entity_id": "DE", "metric": "drug_deaths",
     "year": 2023, "value": 2227, "unit": "persons", "locator": "S. 23, Abschnitt Rauschgifttote",
     "quote": "Deutschland 2.227 drogenbedingte Todesfälle polizeilich registriert."},
    {"source": "lagebild_2023", "entity_type": "bund", "entity_id": "DE", "metric": "drug_deaths_male",
     "year": 2023, "value": 1844, "unit": "persons", "locator": "S. 23, Abschnitt Rauschgifttote",
     "quote": "Unter den Drogentoten des Jahres 2023 waren 1.844 Männer (82,8 %) und 383 Frauen (17,2 %)."},
    {"source": "lagebild_2023", "entity_type": "bund", "entity_id": "DE", "metric": "drug_deaths_female",
     "year": 2023, "value": 383, "unit": "persons", "locator": "S. 23, Abschnitt Rauschgifttote",
     "quote": "Unter den Drogentoten des Jahres 2023 waren 1.844 Männer (82,8 %) und 383 Frauen (17,2 %)."},
    {"source": "lagebild_2023", "entity_type": "land", "entity_id": "05", "metric": "drug_deaths",
     "year": 2023, "value": 872, "unit": "persons", "locator": "S. 23",
     "quote": "Nordrhein-Westfalen (872), Berlin (271) und Bayern (257)"},
    {"source": "lagebild_2023", "entity_type": "land", "entity_id": "11", "metric": "drug_deaths",
     "year": 2023, "value": 271, "unit": "persons", "locator": "S. 23",
     "quote": "Nordrhein-Westfalen (872), Berlin (271) und Bayern (257)"},
    {"source": "lagebild_2023", "entity_type": "land", "entity_id": "09", "metric": "drug_deaths",
     "year": 2023, "value": 257, "unit": "persons", "locator": "S. 23",
     "quote": "Nordrhein-Westfalen (872), Berlin (271) und Bayern (257)"},
    {"source": "lagebild_2023", "entity_type": "land", "entity_id": "15", "metric": "drug_deaths",
     "year": 2023, "value": 52, "unit": "persons", "locator": "S. 23",
     "quote": "Sachsen-Anhalt (52; + 178,9 %)"},
    {"source": "lagebild_2023", "entity_type": "land", "entity_id": "01", "metric": "drug_deaths",
     "year": 2023, "value": 42, "unit": "persons", "locator": "S. 23",
     "quote": "Schleswig-Holstein (42; -25 %)"},
    # 2022 national — Lagebild p. 22
    {"source": "lagebild_2022", "entity_type": "bund", "entity_id": "DE", "metric": "drug_deaths",
     "year": 2022, "value": 1990, "unit": "persons", "locator": "S. 22, Abschnitt Rauschgifttote",
     "quote": "1.990 Rauschgifttote registriert, was im Vergleich zum Vorjahr einer Zunahme um 9 % (2021: 1.826)"},
    {"source": "lagebild_2022", "entity_type": "bund", "entity_id": "DE", "metric": "drug_deaths_male",
     "year": 2022, "value": 1648, "unit": "persons", "locator": "S. 22",
     "quote": "Jahres 2022 waren 1.648"},
    {"source": "lagebild_2022", "entity_type": "bund", "entity_id": "DE", "metric": "drug_deaths_female",
     "year": 2022, "value": 342, "unit": "persons", "locator": "S. 22",
     "quote": "Männer (83 %) und 342 Frauen."},
    {"source": "lagebild_2022", "entity_type": "bund", "entity_id": "DE", "metric": "drug_deaths_mean_age",
     "year": 2022, "value": 40.6, "unit": "years", "locator": "S. 22",
     "quote": "Durchschnittsalter lag bei 40,6 Jahren."},
]

LAND_2022_NOTE = (
    "Complete official Land table published with the 11.05.2023 press release "
    "for reporting year 2022. The PDF itself has no year in the table heading."
)


def _im():
    from ingest.domains import institutions_media as im
    return im


def _rh():
    from ingest.domains import institutions_media_rechnungshof as rh
    return rh


def pdf_text_from_bytes(data: bytes) -> str | None:
    if not data or not data.startswith(b"%PDF"):
        return None
    with tempfile.TemporaryDirectory(prefix="im-pdf-") as tmp:
        path = Path(tmp) / "doc.pdf"
        path.write_bytes(data)
        txt = Path(tmp) / "doc.txt"
        try:
            subprocess.run(
                ["pdftotext", "-layout", str(path), str(txt)],
                check=False, capture_output=True, timeout=120,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        if not txt.exists():
            return None
        return txt.read_text(encoding="utf-8", errors="replace")


def fetch_document_text(url: str) -> str:
    raw = fetch(url, domain=DOMAIN)
    if raw.startswith(b"%PDF"):
        text = pdf_text_from_bytes(raw)
        if not text:
            raise RuntimeError(f"pdftotext failed for {url}")
        return text
    return raw.decode("utf-8", "replace")


def parse_land_death_table(text: str) -> dict[str, int]:
    """Parse the official 'Anzahl der Rauschgifttoten' Land table (16 Länder + Summe)."""
    rh = _rh()
    hay = rh.fold_text(text)
    out: dict[str, int] = {}
    for name, code in LAND_BY_NAME.items():
        if name == "Deutschland" or name == "Bundesrepublik Deutschland":
            continue
        m = re.search(rf"{re.escape(name)}\s+([0-9]{{1,5}})\b", hay)
        if m:
            out[code] = int(m.group(1))
    return out


def store_cited_metric(conn, rec: dict, *, source_id: int, document_text: str, notes: list[str]) -> bool:
    """Store one metric only when the short quote is present in the cited document."""
    rh = _rh()
    quote = rh.trim_quote(rec.get("quote"))
    metric = clean(rec.get("metric"))
    year = rec.get("year")
    value = rec.get("value")
    entity_type = clean(rec.get("entity_type"))
    entity_id = clean(rec.get("entity_id"))
    if not quote or not metric or year is None or value is None or not entity_type or not entity_id:
        notes.append(f"skipped metric without quote/value/name/year: {metric}")
        return False
    try:
        amount = float(value)
    except (TypeError, ValueError):
        notes.append(f"skipped non-numeric metric {metric}")
        return False
    if not rh.quote_in_text(quote, document_text):
        notes.append(
            f"{entity_type}:{entity_id} {metric} {year} not stored; "
            "quote was not found in the cited document text"
        )
        return False
    entity_type, entity_id = _im().metric_geo(entity_type, entity_id)
    upsert(conn, "metric", {
        "entity_type": entity_type,
        "entity_id": entity_id,
        "metric": metric,
        "value": amount,
        "einheit": clean(rec.get("unit")) or "persons",
        "year": int(year),
        "period": clean(rec.get("period")),
        "is_est": int(rec.get("is_est") or 0),
        "is_rounded": int(rec.get("is_rounded") or 0),
        "anmerkung": clean(rec.get("note")),
        "quote": quote,
        "locator": clean(rec.get("locator")),
        "source_id": source_id,
    }, ["entity_type", "entity_id", "metric", "year"])
    return True


def _register(conn, source_key: str, sources, notes: list[str]) -> int:
    im = _im()
    meta = SOURCES[source_key]
    return im._register_source(
        conn, meta["url"],
        title=meta["title"],
        publisher=meta["publisher"],
        license_=RESERVED_LICENCE,
        license_url=meta["license_url"],
        attribution=meta["attribution"],
        notes=meta.get("notes") or RESERVED_LICENCE_NOTE,
        redistribute_fulltext=0,
        bucket=sources,
    )


def _store_source_doc(conn, source_key: str, source_id: int) -> None:
    meta = SOURCES[source_key]
    land = "DE"
    upsert(conn, "doc", {
        "kind": "report",
        "title": meta["title"],
        "url": meta["url"],
        "herausgeber": meta["publisher"],
        "urheber": None,
        "veroeffentlicht": meta.get("published"),
        "land": land,
        "zusammenfassung": "Official drug-death statistics; facts and short quotes only.",
        "source_id": source_id,
    }, ["url"])


def _land_2022_figures(table: dict[str, int]) -> list[dict]:
    out = []
    for code, value in sorted(table.items(), key=lambda kv: kv[0]):
        # Recover a name for the quote
        name = next(n for n, c in LAND_BY_NAME.items() if c == code and n not in {"Deutschland", "Bundesrepublik Deutschland"})
        out.append({
            "source": "cdr_land_2022",
            "entity_type": "bund" if code == "DE" else "land",
            "entity_id": code if code == "DE" else _im().metric_geo("land", code)[1],
            "metric": "drug_deaths",
            "year": 2022,
            "value": value,
            "unit": "persons",
            "locator": "Tabelle 'Anzahl der Rauschgifttoten'; year from official 11.05.2023 press release",
            "quote": f"{name} {value}",
            "note": LAND_2022_NOTE if code == "DE" else None,
        })
    return out


def ingest_drogentote(conn, cfg, sources, notes) -> int:
    """Fetch official reports and store cited drug-death figures. Returns metric count."""
    del cfg  # no live switches yet; catalog is fixed official sources
    texts: dict[str, str] = {}
    source_ids: dict[str, int] = {}
    stored = 0
    for key, meta in SOURCES.items():
        try:
            texts[key] = fetch_document_text(meta["url"])
        except Exception as exc:
            notes.append(f"drogentote source {key} failed: {type(exc).__name__}: {str(exc)[:180]}")
            continue
        source_ids[key] = _register(conn, key, sources, notes)
        _store_source_doc(conn, key, source_ids[key])

    figures = list(FIGURES)
    if "cdr_land_2022" in texts:
        table = parse_land_death_table(texts["cdr_land_2022"])
        if table.get("DE") != 1990 or len([k for k in table if k != "DE"]) != 16:
            notes.append(
                f"cdr_land_2022 parse unexpected: {len(table)} values, sum/DE={table.get('DE')}"
            )
        else:
            # Prefer the complete official Land table for 2022 Land + DE totals.
            figures = [f for f in figures if not (f["year"] == 2022 and f["metric"] == "drug_deaths" and f["entity_id"] == "DE")]
            figures.extend(_land_2022_figures(table))
            notes.append("drogentote 2022 Land table stored for all 16 Länder plus Summe 1990")

    for rec in figures:
        key = rec["source"]
        if key not in source_ids or key not in texts:
            notes.append(f"drogentote skipped {key} {rec.get('metric')} {rec.get('year')}: source not fetched")
            continue
        if store_cited_metric(conn, rec, source_id=source_ids[key], document_text=texts[key], notes=notes):
            stored += 1

    # Homelessness-specific deaths are not in these official reports.
    homeless_hits = 0
    for key, text in texts.items():
        low = text.casefold()
        if "obdachlos" in low or "wohnungslos" in low:
            homeless_hits += 1
            notes.append(f"drogentote {key} mentions homelessness wording; no specific death count was stored from it")
    if homeless_hits == 0:
        notes.append(
            "drogentote: official BKA Lagebilder 2022-2025 and Drogenbeauftragter tables "
            "do not report drug deaths among wohnungslose people specifically"
        )
    notes.append(
        "drogentote caveat: since 2022 the BKA and IFT München changed how causes of "
        "death are counted; totals remain comparable at headline level, but cause "
        "breakdowns are not directly comparable with years before 2022. Land figures "
        "can be revised after the 31.01 reporting date. 2025 Lagebild and 2023/2024 "
        "Lagebilder have no complete 16-Land table in extractable text (2025: national "
        "only; 2023-2024: only the Länder named in running text)."
    )
    notes.append(f"drogentote metrics={stored}")
    return stored



if __name__ == "__main__":
    from ingest.common import no_direct_run
    raise SystemExit(no_direct_run("institutions_media"))
