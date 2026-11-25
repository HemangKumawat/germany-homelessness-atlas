"""Wire the Lead's Bremen/Frankfurt manual archive into institutions_media.

Reads only local files under ~/projects/_manual_archive/institutions_media/
(or cfg['manual_archive']). The official source URL is stored; the files are
never re-fetched. This module must never request sd.bremische-buergerschaft.de
PDFs or stvv.frankfurt.de/download.

Quotes come from the unmodified archived PDF (pdftotext -layout) or, for
Frankfurt/Bremen HTML captures, from the visible rendered text only.
"""
from __future__ import annotations

import hashlib
import json
import re
from html.parser import HTMLParser
from pathlib import Path

from ingest import common
from ingest.common import clean, document_text, upsert
from ingest.domains.institutions_media_rechnungshof import (
    RESERVED_LICENCE,
    quote_in_text,
    trim_quote,
)
from ingest.domains.institutions_media_shelters import store_official_facility

DOMAIN = "institutions_media"
ARCHIVE_DEFAULT = Path.home() / "projects/_manual_archive/institutions_media"
PROVENANCE = "manual archive via browser/box, 2026-11-21; local file only, never re-fetched"

# Official URLs as published. Do not fetch these from this module.
URL_BREMEN_SERVICE = (
    "https://www.service.bremen.de/dienstleistungen/"
    "notunterkunft-als-wohnungslose-person-nachfragen-11450"
)
URL_BREMEN_SOZIALES = "https://www.soziales.bremen.de/soziales/wohnungslosenhilfe-126027"
URL_BREMEN_ZFW = (
    "https://www.amtfuersozialedienste.bremen.de/erwachsene/"
    "zentrale-fachstelle-wohnen-11198"
)
URL_FFM_LIST = (
    "https://frankfurt.de/leistungen/Notlagen-und-Opferhilfen-8958513/"
    "Finanzielle-und-sonstige-Hilfen-8958541/Notschlafstellen"
)
URL_FFM_KAELTEBUS = (
    "https://frankfurt.de/themen/soziales-und-gesellschaft/"
    "notlagen-und-hilfen/in-notlagen/kaeltebus"
)
URL_FFM_PM = "https://frankfurt.de/de-de/aktuelle-meldung/dezernat-viii/schlafplaetze-fuer-obdachlose/"
URL_HB_SENAT_2025 = (
    "https://www.rathaus.bremen.de/sixcms/media.php/13/"
    "20250819_top_22_Wohnungs_und_Obdachlosigkeit.pdf"
)
URL_HB_SENAT_2030 = (
    "https://www.rathaus.bremen.de/sixcms/media.php/13/"
    "top%2011_20240423_Beendigung_von_Wohnungs_und_Obdachlosigkeit_N.pdf"
)
URL_HB_SENAT_2013 = (
    "https://www.soziales.bremen.de/sixcms/media.php/13/"
    "Mehr+Transparenz+bei+den+Angeboten+und+Kosten+der+Wohnungslosenhilfe.pdf"
)
URL_VL_1210 = (
    "https://sd.bremische-buergerschaft.de/sdnetrim/"
    "UGhVM0hpd2NXNFdFcExjZRqJi2_bo6AeOa2nQOVq-sexF-o1P2dFKO76dTyARjnT/"
    "Beschlussvorlage_Ausschuesse-Deputationen_VL_20-1210.pdf"
)
URL_VL_7270 = (
    "https://sd.bremische-buergerschaft.de/sdnetrim/"
    "UGhVM0hpd2NXNFdFcExjZZB7EJQ4UxlGTaLNwm4P-vajKNS-iUJAGGKfBgGyUCxh/"
    "Beschlussvorlage_Ausschuesse-Deputationen_VL_20-7270.pdf"
)
URL_FFM_SATZUNG = (
    "https://frankfurt.de/-/media/frankfurtde/service-und-rathaus/verwaltung/"
    "aemter-und-institutionen/rechtsamt/pdf/satzungen/unterbringungsgebuehrensatzung.pdf"
)
URL_FFM_M71 = "https://www.stvv.frankfurt.de/download/M_71_2026.pdf"

BREMEN_IMPRESSUM = "https://www.service.bremen.de/impressum-122389"
RATHAUS_IMPRESSUM = "https://www.rathaus.bremen.de/impressum-14646"
SOZIALES_IMPRESSUM = "https://www.soziales.bremen.de/impressum"
FFM_IMPRESSUM = "https://frankfurt.de/service-und-rathaus/aktuelles/impressum"

AMT_SENAT = (
    "Rechte vorbehalten: Senatsvorlage/Mitteilung des Senats, kein Gesetz, keine Verordnung und kein Amtsblatt, daher nicht § 5 UrhG (Lead 2026-11-23: § 5 nur für Gesetze, Verordnungen, Erlasse, Amtsblätter und Gerichtsentscheidungen); nur Fakten, Metadaten und Kurzzitate nach § 51 UrhG, Volltext nicht weiterverbreitet"
)
AMT_BUERG = (
    "Rechte vorbehalten: Parlamentsdrucksache der Bremischen Bürgerschaft, kein Gesetz, keine Verordnung und kein Amtsblatt, daher nicht § 5 UrhG (Lead 2026-11-23: § 5 nur für Gesetze, Verordnungen, Erlasse, Amtsblätter und Gerichtsentscheidungen); nur Fakten, Metadaten und Kurzzitate nach § 51 UrhG, Volltext nicht weiterverbreitet"
)
AMT_SATZUNG = (
    "Amtliches Werk, § 5 Abs. 1 UrhG: kommunale Satzung, amtlich bekanntgemacht; "
    "zitiert mit Fundstelle"
)
AMT_MAGISTRAT = (
    "Rechte vorbehalten: Magistratsvorlage, kein Gesetz, keine Verordnung und kein Amtsblatt, daher nicht § 5 UrhG (Lead 2026-11-23: § 5 nur für Gesetze, Verordnungen, Erlasse, Amtsblätter und Gerichtsentscheidungen); nur Fakten, Metadaten und Kurzzitate nach § 51 UrhG, Volltext nicht weiterverbreitet"
)

FILES = {
    "bremen_service": "bremen_service_notunterkunft.html",
    "bremen_soziales": "bremen_soziales_wohnungslosenhilfe.html",
    "bremen_zfw": "bremen_afsd_zfw.html",
    "ffm_list": "ffm_notschlafstellen.html",
    "ffm_kaeltebus": "ffm_kaeltebus.html",
    "ffm_pm": "ffm_pm_schlafplaetze_2026-11-04.html",
    "hb_2025": "hb_senat_20250819_wohnungslosigkeit.pdf",
    "hb_2030": "hb_senat_2030.pdf",
    "hb_2013": "hb_senat_2013_transparenz_kosten.pdf",
    "vl_1210": "hb_VL_20-1210.pdf",
    "vl_7270": "hb_VL_20-7270.pdf",
    "ffm_satzung": "ffm_unterbringungsgebuehrensatzung.pdf",
    "ffm_m71": "ffm_M71_2026.pdf",
}

# Official URL, title, publisher, licence, licence URL, content type — keyed like FILES.
SOURCE_META = {
    "bremen_service": (
        URL_BREMEN_SERVICE,
        "Notunterkunft als wohnungslose Person nachfragen / Notunterbringung nachfragen",
        "Freie Hansestadt Bremen, Amt für Soziale Dienste",
        RESERVED_LICENCE, BREMEN_IMPRESSUM, "text/html",
    ),
    "bremen_soziales": (
        URL_BREMEN_SOZIALES,
        "Wohnungslosenhilfe, Senatorin für Arbeit, Soziales, Jugend und Integration",
        "Freie Hansestadt Bremen, Senatorin für Arbeit, Soziales, Jugend und Integration",
        RESERVED_LICENCE, SOZIALES_IMPRESSUM, "text/html",
    ),
    "bremen_zfw": (
        URL_BREMEN_ZFW,
        "Zentrale Fachstelle Wohnen, Amt für Soziale Dienste Bremen",
        "Freie Hansestadt Bremen, Amt für Soziale Dienste",
        RESERVED_LICENCE, "https://www.amtfuersozialedienste.bremen.de/impressum", "text/html",
    ),
    "ffm_list": (
        URL_FFM_LIST,
        "Notschlafstellen, Stadt Frankfurt am Main",
        "Stadt Frankfurt am Main",
        RESERVED_LICENCE, FFM_IMPRESSUM, "text/html",
    ),
    "ffm_kaeltebus": (
        URL_FFM_KAELTEBUS,
        "Kältebus, Stadt Frankfurt am Main",
        "Stadt Frankfurt am Main",
        RESERVED_LICENCE, FFM_IMPRESSUM, "text/html",
    ),
    "ffm_pm": (
        URL_FFM_PM,
        "Frankfurt hält für Obdachlose 630 Schlafplätze vor (Dezernat VIII, 4.11.2026)",
        "Stadt Frankfurt am Main",
        RESERVED_LICENCE, FFM_IMPRESSUM, "text/html",
    ),
    "hb_2025": (
        URL_HB_SENAT_2025,
        "Senatsantwort 19.08.2025, Wohnungs- und Obdachlosigkeit (jährliche Nettokosten)",
        "Freie Hansestadt Bremen, Senat",
        AMT_SENAT, RATHAUS_IMPRESSUM, "application/pdf",
    ),
    "hb_2030": (
        URL_HB_SENAT_2030,
        "Senatsvorlage 23.04.2024, Beendigung von Wohnungs- und Obdachlosigkeit",
        "Freie Hansestadt Bremen, Senat",
        AMT_SENAT, RATHAUS_IMPRESSUM, "application/pdf",
    ),
    "hb_2013": (
        URL_HB_SENAT_2013,
        "Senatsantwort 2013, Mehr Transparenz bei den Angeboten und Kosten der Wohnungslosenhilfe",
        "Freie Hansestadt Bremen, Senat",
        AMT_SENAT, SOZIALES_IMPRESSUM, "application/pdf",
    ),
    "vl_1210": (
        URL_VL_1210,
        "Deputationsvorlage VL 20/1210, Notunterkünfte für Obdachlose",
        "Bremische Bürgerschaft",
        AMT_BUERG, "https://www.bremische-buergerschaft.de/impressum", "application/pdf",
    ),
    "vl_7270": (
        URL_VL_7270,
        "Deputationsvorlage VL 20/7270, Sachstandsbericht zur Unterbringung in Notunterkünften",
        "Bremische Bürgerschaft",
        AMT_BUERG, "https://www.bremische-buergerschaft.de/impressum", "application/pdf",
    ),
    "ffm_satzung": (
        URL_FFM_SATZUNG,
        "Unterbringungsgebührensatzung der Stadt Frankfurt am Main, Gebührenverzeichnis",
        "Stadt Frankfurt am Main",
        AMT_SATZUNG, FFM_IMPRESSUM, "application/pdf",
    ),
    "ffm_m71": (
        URL_FFM_M71,
        "Frankfurt Magistratsvorlage M 71/2026, Unterbringungsgebührensatzung",
        "Stadt Frankfurt am Main",
        AMT_MAGISTRAT, FFM_IMPRESSUM, "application/pdf",
    ),
}

BLOCKED_FETCH_PREFIXES = (
    "https://sd.bremische-buergerschaft.de/",
    "http://sd.bremische-buergerschaft.de/",
    "https://www.stvv.frankfurt.de/download/",
    "https://stvv.frankfurt.de/download/",
    "http://www.stvv.frankfurt.de/download/",
    "http://stvv.frankfurt.de/download/",
)

# Official overnight offers on the Bremen service page (catalogued set).
BREMEN_OFFERS = (
    {
        "name": "Notunterkunft für Männer Rembertiring",
        "address": "Rembertiring 49",
        "plz": "28195",
        "population_note": "für Männer; Notaufnahme rund um die Uhr.",
        "needles": ("Notunterkunft für Männer", "Rembertiring 49"),
    },
    {
        "name": "Notunterkunft für Frauen",
        "population_note": "für Frauen; Notaufnahme rund um die Uhr.",
        "needles": ("Notunterkunft für Frauen",),
    },
    {
        "name": "Sleep Inn Bremen",
        "address": "Oberneulander Landstr. 19",
        "plz": "28355",
        "population_note": "für Drogenkonsumentinnen und Drogenkonsumenten.",
        "needles": ("Sleep Inn", "Oberneulander Landstr"),
    },
    {
        "name": "La Campagne",
        "address": "Ahlringstr. 2 - 4",
        "plz": "28309",
        "population_note": "für Drogenkonsumentinnen und Drogenkonsumenten.",
        "needles": ("La Campagne", "Ahlringstr"),
    },
)

# Official Frankfurt Notschlafstellen list. Hannah is women-only (district level).
# Drogennotdienst is operated by Jugendberatung und Jugendhilfe e.V.; Jugend in
# the operator name is coarsened by the existing restricted-group rule.
FRANKFURT_OFFERS = (
    {
        "name": "Übernachtungsstätte Ostpark",
        "address": "Ostparkstr. 16",
        "plz": "60385",
        "operator": "Frankfurter Verein für soziale Heimstätten e. V.",
        "population_note": "Notübernachtungsstätte für obdachlose Menschen.",
        "needles": ("Übernachtungsstätte Ostpark", "Ostparkstr. 16"),
    },
    {
        "name": "Aufnahme- und Übergangsheim Rudolfstraße",
        "address": "Rudolfstr. 18",
        "plz": "60327",
        "operator": "Frankfurter Verein für soziale Heimstätten e. V.",
        "population_note": "Notübernachtungsstätte für obdachlose Menschen.",
        "needles": ("Aufnahme- und Übergangsheim Rudolfstraße", "Rudolfstr. 18"),
    },
    {
        "name": "Sozialzentrum am Burghof",
        "address": "Am Burghof 43-45",
        "plz": "60437",
        "operator": "Frankfurter Verein für soziale Heimstätten e. V.",
        "population_note": "Notübernachtungsstätte für obdachlose Menschen.",
        "needles": ("Sozialzentrum am Burghof", "Am Burghof 43-45"),
    },
    {
        "name": "Hannah-Wohnen für Frauen",
        "operator": "Diakonisches Werk",
        "population_note": "für Frauen.",
        "needles": ("Hannah-Wohnen für Frauen",),
    },
    {
        "name": "Weser 5 Diakoniezentrum",
        "address": "Weserstr. 5",
        "plz": "60329",
        "operator": "Diakonisches Werk",
        "population_note": "Übergangswohnhaus und Notübernachtung.",
        "needles": ("Weser 5 Diakoniezentrum", "Weserstr. 5"),
    },
    {
        "name": "Eastside",
        "address": "Schielestraße 22-26",
        "plz": "60314",
        "operator": "Integrative Drogenhilfe e. V. (idh)",
        "population_note": "für suchtkranke und obdachlose Menschen (m/w/d).",
        "needles": ("Eastside", "Schielestraße 22-26"),
    },
    {
        "name": "Drogennotdienst",
        "address": "Elbestr. 38",
        "plz": "60329",
        "operator": "Jugendberatung und Jugendhilfe e.V.",
        "population_note": "für suchtkranke und obdachlose Menschen (m/w/d).",
        "needles": ("Drogennotdienst", "Elbestr. 38"),
    },
    {
        "name": "La Strada",
        "address": "Mainzer Landstr. 93",
        "plz": "60329",
        "operator": "AIDS-Hilfe Frankfurt e. V.",
        "population_note": "für suchtkranke und obdachlose Menschen (m/w/d).",
        "needles": ("La Strada", "Mainzer Landstr. 93"),
    },
)

QUOTE_FFM_PLACES = "Frankfurt hält für Obdachlose 630 Schlafplätze vor"
QUOTE_HB_2023 = (
    "Die Nettokosten für die Unterbringung in Notunterkünften, betreuten Einrichtungen "
    "sowie Hotels und Pensionen betrugen in Bremen im Jahr 2023 für Unterbringung und "
    "Betreuung € 4.043.506."
)
QUOTE_HB_2024 = "Im Jahr 2024 beliefen sich diese Kosten auf € 4.465.032."
QUOTE_HBHV_2023 = (
    "In Bremerhaven beliefen sich die Kosten für die Notunterkunft für Männer im Jahr "
    "2023 auf rund 280.000 €."
)


def _im():
    from ingest.domains import institutions_media as im
    return im


class _VisibleText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.chunks: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "noscript"}:
            self.skip += 1
        if tag in {"p", "div", "li", "tr", "h1", "h2", "h3", "h4", "br", "section", "article", "td"}:
            self.chunks.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript"} and self.skip:
            self.skip -= 1
        if tag in {"p", "div", "li", "tr", "h1", "h2", "h3", "h4", "section", "article"}:
            self.chunks.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.chunks.append(data)


def visible_html_text(raw: bytes) -> str:
    """Visible text of a rendered-page capture. Quotes must appear in this text."""
    parser = _VisibleText()
    parser.feed(raw.decode("utf-8", "replace"))
    parser.close()
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in "".join(parser.chunks).splitlines()]
    return "\n".join(ln for ln in lines if ln)


def is_blocked_fetch_url(url: str) -> bool:
    low = (url or "").strip().lower()
    return any(low.startswith(prefix) for prefix in BLOCKED_FETCH_PREFIXES)


def archive_dir(cfg) -> Path:
    raw = (cfg or {}).get("manual_archive") or ARCHIVE_DEFAULT
    return Path(raw).expanduser()


def load_checksums(root: Path) -> dict[str, str]:
    path = root / "SHA256SUMS"
    if not path.is_file():
        return {}
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) >= 2:
            out[parts[-1]] = parts[0]
    return out


def read_archived(root: Path, filename: str) -> bytes:
    path = root / filename
    if not path.is_file():
        raise FileNotFoundError(f"manual archive file missing: {path}")
    data = path.read_bytes()
    expected = load_checksums(root).get(filename)
    if expected:
        got = hashlib.sha256(data).hexdigest()
        if got != expected:
            raise ValueError(f"{filename} sha256 {got} != SHA256SUMS {expected}")
    return data


def seed_cache(url: str, data: bytes, *, content_type: str) -> Path:
    """Copy archive bytes into data/raw so source_id_for fills sha256. Never fetches."""
    dest = common.raw_path(DOMAIN, url)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.exists() or dest.read_bytes() != data:
        dest.write_bytes(data)
    dest.with_suffix(".meta.json").write_text(json.dumps({
        "url": url, "method": "GET", "status": 200, "retrieved_at": common.now(),
        "content_type": content_type, "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "note": "seeded from verified manual archive; official host was not fetched",
    }, ensure_ascii=False), encoding="utf-8")
    return dest


def pdf_text(path: Path) -> str:
    text = document_text(path) or ""
    return text


def line_with(text: str, *needles: str) -> str | None:
    for line in (text or "").splitlines():
        if all(n in line for n in needles):
            return line.strip()
    return None


def _source(conn, key: str, sources, root: Path):
    url, title, publisher, license_, license_url, content_type = SOURCE_META[key]
    data = read_archived(root, FILES[key])
    seed_cache(url, data, content_type=content_type)
    return _im()._register_source(
        conn, url,
        title=title,
        publisher=publisher,
        license_=license_,
        bucket=sources,
        license_url=license_url,
        attribution=publisher,
        notes=clean(PROVENANCE),
        redistribute_fulltext=0,
    )


def store_bremen_offers(conn, text: str, *, sources, root: Path) -> int:
    stored = 0
    _source(conn, "bremen_service", sources, root)
    for offer in BREMEN_OFFERS:
        if not all(n in text for n in offer["needles"]):
            continue
        rec = {
            "official_key": "HB-SERVICE:" + offer["name"],
            "name": offer["name"],
            "kind": "notunterkunft",
            "address": offer.get("address"),
            "plz": offer.get("plz"),
            "city": "Bremen",
            "land": "HB",
            "population_note": offer["population_note"],
            "official_url": URL_BREMEN_SERVICE,
            "source_url": URL_BREMEN_SERVICE,
            "source_name": "bremen_service",
            "source_title": SOURCE_META["bremen_service"][1],
            "publisher": SOURCE_META["bremen_service"][2],
            "license": RESERVED_LICENCE,
            "license_url": BREMEN_IMPRESSUM,
            "source_notes": PROVENANCE,
            "redistribute_fulltext": 0,
        }
        if store_official_facility(conn, rec, sources=sources):
            stored += 1
    return stored


def store_frankfurt_offers(conn, text: str, *, sources, root: Path) -> int:
    stored = 0
    _source(conn, "ffm_list", sources, root)
    for offer in FRANKFURT_OFFERS:
        if not all(n in text for n in offer["needles"]):
            continue
        rec = {
            "official_key": "HE-FFM:" + offer["name"],
            "name": offer["name"],
            "kind": "notunterkunft",
            "address": offer.get("address"),
            "plz": offer.get("plz"),
            "city": "Frankfurt am Main",
            "land": "HE",
            "operator": offer.get("operator"),
            "population_note": offer["population_note"],
            "official_url": URL_FFM_LIST,
            "source_url": URL_FFM_LIST,
            "source_name": "ffm_notschlafstellen",
            "source_title": SOURCE_META["ffm_list"][1],
            "publisher": SOURCE_META["ffm_list"][2],
            "license": RESERVED_LICENCE,
            "license_url": FFM_IMPRESSUM,
            "source_notes": PROVENANCE + "; quote from visible rendered text only",
            "redistribute_fulltext": 0,
        }
        if store_official_facility(conn, rec, sources=sources):
            stored += 1
    return stored


def _metric(conn, text, *, source_id, metric, value, year, entity_type, entity_id, unit, quote, locator, note, is_est=0) -> bool:
    if not quote or not quote_in_text(quote, text):
        return False
    upsert(conn, "metric", {
        "source_id": source_id,
        "metric": metric,
        "year": year,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "value": value,
        "einheit": unit,
        "is_est": is_est,
        "is_rounded": 1 if is_est else 0,
        "quote": trim_quote(quote),
        "locator": locator,
        "anmerkung": note,
    }, ["entity_type", "entity_id", "metric", "year"])
    return True


def _fee_line(text: str, heading: str, amount: str) -> str | None:
    in_block = False
    for line in (text or "").splitlines():
        if heading in line:
            in_block = True
            continue
        if in_block and heading.split()[0] not in heading and re.match(r"\s*\d+\.\s+", line):
            break
        if in_block and amount in line and "Ein-Personen-Haushalt" in line:
            return line.strip()
    return None


def store_cost_metrics(conn, sources, root: Path) -> int:
    stored = 0
    raw = read_archived(root, FILES["ffm_pm"])
    text = visible_html_text(raw)
    if QUOTE_FFM_PLACES in text:
        sid = _source(conn, "ffm_pm", sources, root)
        if _metric(
            conn, text, source_id=sid, metric="ffm_notuebernachtung_places", value=630,
            year=2026, entity_type="kreis", entity_id="06412", unit="places",
            quote=QUOTE_FFM_PLACES, locator="visible text, headline 04.11.2026",
            note="Stadt Frankfurt, Dezernat VIII press page, winter 2026/27 official capacity",
        ):
            stored += 1

    text = pdf_text(root / FILES["hb_2025"])
    sid = _source(conn, "hb_2025", sources, root)
    # Lead 2026-11-23: these are Bremen-city (Kreis 04011) costs; the rows an earlier run stored on Land 04 go
    conn.execute("DELETE FROM metric WHERE metric='hb_nu_net_cost_eur' AND entity_type='land' AND entity_id='04'")
    if _metric(
        conn, text, source_id=sid, metric="hb_nu_net_cost_eur", value=4043506,
        year=2023, entity_type="kreis", entity_id="04011", unit="eur_per_year",
        quote=QUOTE_HB_2023, locator="PDF layout, Zu Frage 3, line containing 4.043.506",
        note="Bremen city, net costs of Notunterkünfte, betreute Einrichtungen, hotels and pensions, 2023",
    ):
        stored += 1
    if _metric(
        conn, text, source_id=sid, metric="hb_nu_net_cost_eur", value=4465032,
        year=2024, entity_type="kreis", entity_id="04011", unit="eur_per_year",
        quote=QUOTE_HB_2024, locator="PDF layout, Zu Frage 3, line containing 4.465.032",
        note="Bremen city, net costs of Notunterkünfte, betreute Einrichtungen, hotels and pensions, 2024",
    ):
        stored += 1
    if _metric(
        conn, text, source_id=sid, metric="hbhv_men_nu_cost_eur", value=280000,
        year=2023, entity_type="kreis", entity_id="04012", unit="eur",
        quote=QUOTE_HBHV_2023, locator="PDF layout, Zu Frage 3, line containing 280.000",
        note="Bremerhaven, official 'rund 280.000 €' for the men's Notunterkunft 2023",
        is_est=1,
    ):
        stored += 1

    text = pdf_text(root / FILES["hb_2013"])
    sid = _source(conn, "hb_2013", sources, root)
    daily = (
        ("hb_nu_daily_entgelt_jakobushaus_eur", "Jakobushaus", 51.73, "51,73"),
        ("hb_nu_daily_entgelt_frauen_eur", "Frauennotunterkunft", 87.92, "87,92"),
        ("hb_nu_daily_entgelt_lacampagne_eur", "La Campagne", 48.86, "48,86"),
        ("hb_nu_daily_entgelt_sleepinn_eur", "Sleep Inn", 52.39, "52,39"),
    )
    for metric, name, value, needle in daily:
        quote = line_with(text, name, needle)
        if quote and _metric(
            conn, text, source_id=sid, metric=metric, value=value,
            year=2013, entity_type="land", entity_id="04", unit="eur_per_place_day",
            quote=quote, locator=f"PDF Anlage 1 line containing {name} {needle}",
            note=f"Bremen Senate 2013 daily Entgelt for {name}; Land-level, no street address",
        ):
            stored += 1

    text = pdf_text(root / FILES["ffm_satzung"])
    sid = _source(conn, "ffm_satzung", sources, root)
    fees = (
        ("ffm_fee_zwischen_1p_eur_per_month", 635.0, "Zwischengenutzter Wohnraum", "635,00"),
        ("ffm_fee_sonstige_1p_eur_per_month", 810.0, "Sonstige Unterkunft", "810,00"),
    )
    for metric, value, heading, amount in fees:
        quote = _fee_line(text, heading, amount)
        if quote and _metric(
            conn, text, source_id=sid, metric=metric, value=value,
            year=2026, entity_type="kreis", entity_id="06412", unit="eur_per_month",
            quote=quote, locator=f"PDF Gebührenverzeichnis, {heading}, {amount} €",
            note="Frankfurt Unterbringungsgebührensatzung, monthly fee per one-person household",
        ):
            stored += 1

    for key in ("vl_1210", "vl_7270", "ffm_m71", "hb_2030", "bremen_soziales", "bremen_zfw", "ffm_kaeltebus"):
        if (root / FILES[key]).is_file():
            _source(conn, key, sources, root)
    return stored


def ingest_manual_archive(conn, cfg, sources, notes) -> dict:
    """Store Bremen/Frankfurt shelters and official costs from the Lead archive only."""
    root = archive_dir(cfg)
    result = {"shelters": 0, "metrics": 0, "missing": []}
    if not root.is_dir():
        notes.append(f"Manual archive directory missing: {root}")
        return result
    try:
        service = visible_html_text(read_archived(root, FILES["bremen_service"]))
        result["shelters"] += store_bremen_offers(conn, service, sources=sources, root=root)
    except Exception as exc:
        notes.append(f"Bremen service archive failed: {type(exc).__name__}: {str(exc)[:200]}")
        result["missing"].append(FILES["bremen_service"])
    try:
        ffm = visible_html_text(read_archived(root, FILES["ffm_list"]))
        result["shelters"] += store_frankfurt_offers(conn, ffm, sources=sources, root=root)
    except Exception as exc:
        notes.append(f"Frankfurt Notschlafstellen archive failed: {type(exc).__name__}: {str(exc)[:200]}")
        result["missing"].append(FILES["ffm_list"])
    try:
        result["metrics"] = store_cost_metrics(conn, sources, root)
    except Exception as exc:
        notes.append(f"Manual-archive costs failed: {type(exc).__name__}: {str(exc)[:200]}")
    notes.append(
        f"Manual archive {root}: shelters={result['shelters']} metrics={result['metrics']} "
        f"missing={result['missing'] or 'none'}. Files were read locally only; "
        "sd.bremische-buergerschaft.de PDFs and stvv.frankfurt.de/download were not fetched."
    )
    return result


if __name__ == "__main__":
    from ingest.common import no_direct_run
    raise SystemExit(no_direct_run("institutions_media"))
