"""Institutions and media: DIP and Landtag papers, Wikidata facilities, Commons files.

Workers call ``run(conn, cfg)`` with a connection the caller opened. This module
never calls ``ingest.common.db`` or ``ingest.common.main`` and never opens
``data/atlas.db``. The Lead runs ``python3 -m ingest.run institutions_media``.

Landtag papers come from official machine-readable sources where they exist:
Berlin PARDOK (REST API, published key, dl-de/by-2-0 metadata), Brandenburg
ELVIS XML exports, and official recent-only RSS feeds (Bayern, Hamburg, and
Schleswig-Holstein if the published feed returns RSS). Other Länder are
documented as gaps.

Rechnungshof audits come from official Bundesrechnungshof and
Landesrechnungshof publication pages only. A PDF is stored only after it
returns HTTP 200 or 206 with a PDF content type or ``%PDF`` magic. Each
source has a licence: quoted official terms where an imprint states them,
or "amtliches Werk, § 5 UrhG" scoped to the cited report or document text
when the body states no terms. Bundestag DIP uses the archived DIP
Nutzungsbedingungen (Lead, 2026-11-21); a TODO licence is never stored. Euro amounts are stored in ``metric`` only with a
quote that appears in the cited document, plus a page locator. The official PARDOK key is taken from ``PARDOK_API_KEY``
or the Open Data page and is sent only as an ``X-API-Key`` header.

DIP metadata comes from the list API. A PDF URL is stored only as the API
published it, and only after a ranged GET returns HTTP 200 or 206 with a PDF
content type or ``%PDF`` magic. HTTP 404 HTML is not a PDF. Catalog pages that
return HTTP 200 are the public ``doc.url``. The API key is taken from
``DIP_API_KEY`` or the published help-api page and is sent only as an
``Authorization`` header.

Facility rows come from Wikidata items in Germany of the psychiatric-hospital
and prison classes checked in ``EXPECTED_LABELS``. Budget and per-bed cost stay
NULL. ``frauenhaus`` and ``protected_shelter`` rows keep address, lat and lon
NULL.
"""
from __future__ import annotations

import hashlib
import html
import json
import os
import re
import sqlite3
import sys
import time
import urllib.parse
import xml.etree.ElementTree as ET
from collections import defaultdict

import requests

from ingest import common
from ingest.common import ROOT, clean, fetch, name_norm, source_id_for, upsert, LAND_AGS
from ingest.domains.institutions_media_rechnungshof import RESERVED_LICENCE

DOMAIN = "institutions_media"

DIP_LIST = "https://search.dip.bundestag.de/api/v1/drucksache"
DIP_HELP = "https://content.dip.bundestag.de/content-api/v1/content/help-api"
DIP_HELP_PAGE = "https://dip.bundestag.de/über-dip/hilfe/api"
DIP_CONTACT = "parlamentsdokumentation@bundestag.de"
WIKIDATA_API = "https://www.wikidata.org/w/api.php"
WIKIDATA_SPARQL = "https://query.wikidata.org/sparql"
WIKIDATA_LICENCE_PAGE = "https://www.wikidata.org/wiki/Wikidata:Licensing"
WIKIDATA_LICENCE = "CC0 1.0"
WIKIDATA_ATTRIBUTION = "Wikidata contributors"
DIP_TERMS_PAGE = "https://dip.bundestag.de/über-dip/nutzungsbedingungen"
DIP_LICENCE_TODO = "TODO: DIP Nutzungsbedingungen pending Lead confirmation"   # kept for tests; never stored
# Lead, 2026-11-21: terms established from the archived PDF data/raw/licences/nutzungsbedingungen_dip.pdf
DIP_LICENCE = (
    "Nutzungsbedingungen für DIP (Deutscher Bundestag, Parlamentsdokumentation, Stand 6. März 2023), Nr. 4: "
    "API-Daten und aus einzelnen PDFs extrahierte Daten dürfen umfassend genutzt und weiterverarbeitet werden, "
    "Weitergabe mit Quellenangabe; Drucksachen-PDFs sind amtliche Werke (§ 5 Abs. 2 UrhG), dürfen nicht verändert "
    "werden, erkennbar auszugsweise Wiedergabe mit Quellenangabe zulässig")
DIP_LICENCE_URL = "https://dip.bundestag.de/documents/nutzungsbedingungen_dip.pdf"
DIP_ATTRIBUTION = "Deutscher Bundestag/Bundesrat – DIP"
PARDOK_LICENCE_URL = "https://www.govdata.de/dl-de/by-2-0"
PARDOK_ATTRIBUTION = "Parlamentsdokumentation, Abgeordnetenhaus von Berlin"
ELVIS_LICENCE = RESERVED_LICENCE
ELVIS_LICENCE_URL = (
    "https://www.parlamentsdokumentation.brandenburg.de/portal/opendata_dokumente.tt.html"
)
ELVIS_ATTRIBUTION = "Parlamentsdokumentation, Landtag Brandenburg"
BY_RSS_LICENCE = RESERVED_LICENCE
BY_RSS_LICENCE_URL = "https://www.bayern.landtag.de/service/impressum/"
BY_RSS_ATTRIBUTION = "Bayerischer Landtag"
SH_RSS_LICENCE = RESERVED_LICENCE
SH_RSS_LICENCE_URL = "https://www.landtag.ltsh.de/metainfo/impressum/"
SH_RSS_ATTRIBUTION = "Schleswig-Holsteinischer Landtag"
HH_RSS_LICENCE = RESERVED_LICENCE
HH_RSS_LICENCE_URL = "https://www.hamburgische-buergerschaft.de/impressum"
HH_RSS_ATTRIBUTION = "Hamburgische Bürgerschaft"
# Canonical URLs used only when Commons extmetadata has a free short name but no LicenseUrl
# (typical for "Public domain" files).
CANONICAL_LICENCE_URLS = {
    "CC0": "https://creativecommons.org/publicdomain/zero/1.0/",
    "CC0 1.0": "https://creativecommons.org/publicdomain/zero/1.0/",
    "Public domain": "https://creativecommons.org/publicdomain/mark/1.0/",
    "PD": "https://creativecommons.org/publicdomain/mark/1.0/",
    "CC BY 4.0": "https://creativecommons.org/licenses/by/4.0/",
    "CC BY 3.0": "https://creativecommons.org/licenses/by/3.0/",
    "CC BY 2.0": "https://creativecommons.org/licenses/by/2.0/",
    "CC BY-SA 4.0": "https://creativecommons.org/licenses/by-sa/4.0/",
    "CC BY-SA 3.0": "https://creativecommons.org/licenses/by-sa/3.0/",
    "CC BY-SA 3.0 de": "https://creativecommons.org/licenses/by-sa/3.0/de/",
    "CC BY-SA 2.0": "https://creativecommons.org/licenses/by-sa/2.0/",
    "GFDL 1.2": "https://www.gnu.org/licenses/old-licenses/fdl-1.2.html",
    "GFDL": "https://www.gnu.org/licenses/fdl.html",
}
PROTECTED_MEDIA_TERMS = (
    "frauenhaus", "frauenhäuser", "schutzwohnung", "schutzwohnungen",
    "protected_shelter", "protected shelter", "women's shelter", "womens shelter",
)
COMMONS_API = "https://commons.wikimedia.org/w/api.php"
_OFFLINE = [False]   # set only by the offline fixture path (tests): nothing is fetched there

# Official Land abbreviations from ingest/schema.sql. ISO 3166-2 suffixes are
# accepted only when they are in this set.
LANDS = {
    "SH", "HH", "NI", "HB", "NW", "HE", "RP", "BW",
    "BY", "SL", "BE", "BB", "MV", "SN", "ST", "TH",
}
CITY_STATES = {"BE", "HH"}
PROTECTED_KINDS = {"frauenhaus", "schutzwohnung", "protected_shelter"}
PUBLISHERS = {
    "BT": "Deutscher Bundestag",
    "BR": "Bundesrat",
    "BE": "Abgeordnetenhaus von Berlin",
    "BB": "Landtag Brandenburg",
    "BY": "Bayerischer Landtag",
    "HH": "Bürgerschaft der Freien und Hansestadt Hamburg",
    "SH": "Schleswig-Holsteinischer Landtag",
}

SEARCH_TERMS = (
    "Wohnungslosigkeit",
    "Obdachlosigkeit",
    "Wohnungslosenhilfe",
    "Kältehilfe",
    "Wohnungsnotfall",
    "Wohnungsnotfälle",
    "Housing First",
)

# Labels confirmed live on 2026-11-20 via wbgetentities (en and de).
# A class is queried only when a live label still matches.
EXPECTED_LABELS = {
    "Q183": {"germany", "deutschland"},
    "Q1221156": {"federated state of germany", "bundesland von deutschland"},
    "Q1451763": {"women's shelter", "frauenhaus"},
    "Q210999": {"psychiatric hospital", "psychiatrische klinik"},
    "Q1516931": {"lunatic asylum", "irrenanstalt"},
    "Q2539416": {"forensic psychiatric center"},
    "Q70450233": {"hospital psychiatric department"},
    "Q594128": {"correctional facility", "justizvollzugsanstalt"},
    "Q40357": {"prison", "gefängnis"},
    "Q18050": {"youth detention center", "jugendstrafanstalt"},
    "Q2945301": {"detention center", "untersuchungshaftanstalt"},
    "Q2305965": {"sozialtherapeutische anstalt"},
    "Q227691": {"house of correction", "zuchthaus"},
    "P6801": {"number of hospital beds", "bettenzahl"},
    "P576": {"dissolved, abolished or demolished", "auflösungsdatum"},
    "P3999": {"date of official closure", "schließungsdatum"},
    "P6375": {"street address", "adresse"},
    "P571": {"inception", "datum der gründung, entstehung, erbauung"},
    "P300": {"iso 3166-2 code", "iso-3166-2-code"},
    "P625": {"coordinate location", "geographische koordinaten"},
    "P856": {"official website", "offizielle website"},
    "P137": {"operator", "betreiber"},
}
KIND_OF = {
    "Q70450233": "psych_unit",
    "Q210999": "psychiatric",
    "Q1516931": "psychiatric",
    "Q2539416": "psychiatric",
    "Q594128": "prison",
    "Q40357": "prison",
    "Q18050": "prison",
    "Q2945301": "prison",
    "Q2305965": "prison",
    "Q227691": "prison",
}

COMMONS_CATEGORIES = (
    "Category:Homelessness in Germany",
    "Category:Housing First",
)
COMMONS_SEARCHES = (
    "intitle:Obdachlosigkeit",
    "intitle:Wohnungslosigkeit",
    "intitle:Kältehilfe",
    'intitle:"Housing First"',
)
SUBCAT_WORDS = (
    "homeless", "shelter", "obdach", "wohnungs", "germany", "deutschland",
    "hilfe", "stiftung", "treber", "kontakt", "werkheim", "retreat",
    "kälte", "kaelte", "housing",
)

_KEY_RE = re.compile(
    r"API-Key lautet:\s*(?:<br\s*/?>\s*)?([A-Za-z0-9]{4,}\.[A-Za-z0-9]{10,})"
)
_FREE_RE = re.compile(
    r"(cc\s*0\b|cc-?zero|creative commons zero|public domain|\bpd\b|"
    r"cc[- ]by[- ]sa|cc[- ]by\b|gfdl|gnu free documentation)",
    re.I,
)
_NONFREE_RE = re.compile(
    r"(non-?free|fair use|all rights reserved|non-?commercial|"
    r"cc[- ]by[- ]nc|cc[- ]by[- ]nd|no derivatives)",
    re.I,
)
_POINT_RE = re.compile(
    r"Point\(\s*([+-]?\d+(?:\.\d+)?)\s+([+-]?\d+(?:\.\d+)?)\s*\)",
    re.I,
)
_QID_RE = re.compile(r"^Q\d+$")
_PID_RE = re.compile(r"^P\d+$")

DRUCKSACHE_DDL = """
CREATE TABLE IF NOT EXISTS institutions_media_drucksache (
  dip_id TEXT PRIMARY KEY,
  dokumentnummer TEXT,
  drucksachetyp TEXT,
  wahlperiode INTEGER,
  herausgeber TEXT,
  titel TEXT,
  datum TEXT,
  urheber TEXT,
  pdf_url TEXT,
  pdf_status TEXT,
  catalog_url TEXT,
  matched_terms TEXT,
  land TEXT,
  origin TEXT,
  parliament TEXT,
  source_id INTEGER
);
"""

FACILITY_DDL = """
CREATE TABLE IF NOT EXISTS institutions_media_facility (
  qid TEXT PRIMARY KEY,
  facility_id INTEGER,
  kind TEXT,
  website TEXT,
  wikidata_url TEXT,
  source_id INTEGER
);
"""

FACILITY_COLS = (
    "name", "name_norm", "kind", "betriebsstatus", "eroeffnet", "geschlossen", "betten",
    "traeger", "land", "kreis_ags", "ort", "anschrift", "plz", "lat", "lon",
    "is_protected", "zielgruppe", "source_id", "is_est",
)


def metric_geo(entity_type: str | None, entity_id: str | None) -> tuple[str, str]:
    """Return metric geography with AGS written explicitly (schema 3).

    Land letter codes such as 'HH' are rejected by the DB trigger. Do not rely on
    upsert() mapping them; this helper writes the 2-digit Land AGS (or 5/8-digit
    Kreis/Gemeinde AGS) itself. Bund/de rows keep 'DE'.
    """
    typ = (entity_type or "").strip()
    ident = (entity_id or "").strip()
    if typ == "land":
        if ident in LAND_AGS:
            ident = LAND_AGS[ident]
        if not (len(ident) == 2 and ident.isdigit() and ident[0] in "01"):
            raise ValueError(f"metric land entity_id must be a 2-digit AGS, not {entity_id!r}")
        return typ, ident
    if typ == "kreis":
        if not (len(ident) == 5 and ident.isdigit() and ident[0] in "01"):
            raise ValueError(f"metric kreis entity_id must be a 5-digit AGS, not {entity_id!r}")
        return typ, ident
    if typ == "gemeinde":
        if not (len(ident) == 8 and ident.isdigit() and ident[0] in "01"):
            raise ValueError(f"metric gemeinde entity_id must be an 8-digit AGS, not {entity_id!r}")
        return typ, ident
    return typ, ident


def kreis_ags_from_wikidata_entity(data: dict) -> str | None:
    """Official Kreis AGS from archived Wikidata EntityData, or None if missing/ambiguous.

    Uses only P440 (German district key) or the first five digits of a unique P439
    (German municipality key). Never infers a Kreis from a place label or coordinates.
    """
    entities = (data.get("entities") or {}) if isinstance(data, dict) else {}
    if not entities:
        return None
    entity = next(iter(entities.values()))
    claims = entity.get("claims") or {}

    def _mains(prop: str) -> list[str]:
        out = []
        for claim in claims.get(prop) or []:
            val = ((claim.get("mainsnak") or {}).get("datavalue") or {}).get("value")
            if isinstance(val, str):
                out.append(val.strip())
            elif isinstance(val, dict) and "amount" not in val and "text" in val:
                out.append(str(val["text"]).strip())
        return out

    p440 = {v for v in _mains("P440") if len(v) == 5 and v.isdigit() and v[0] in "01"}
    if len(p440) == 1:
        return next(iter(p440))
    if p440:
        return None
    p439 = {v for v in _mains("P439") if len(v) == 8 and v.isdigit() and v[0] in "01"}
    kreis = {v[:5] for v in p439}
    if len(kreis) == 1:
        return next(iter(kreis))
    return None



class SourceStopped(Exception):
    def __init__(self, note: str):
        super().__init__(note)
        self.note = note


def _add_column(conn, table: str, column: str, decl: str) -> None:
    cols = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")


def ensure_tables(conn) -> None:
    ensure_source_extensions(conn)
    conn.executescript(DRUCKSACHE_DDL + FACILITY_DDL)
    for column, decl in (("land", "TEXT"), ("origin", "TEXT"), ("parliament", "TEXT")):
        _add_column(conn, "institutions_media_drucksache", column, decl)
    from ingest.domains.institutions_media_rechnungshof import ensure_audit_tables
    from ingest.domains.institutions_media_orgs import ensure_org_tables
    from ingest.domains.institutions_media_shelters import ensure_shelter_tables
    from ingest.domains.institutions_media_investigations import ensure_investigation_tables
    from ingest.domains.institutions_media_hospital_plans import ensure_khplan_table
    from ingest.domains.institutions_media_shelter_costs import ensure_shelter_cost_table
    ensure_audit_tables(conn)
    ensure_org_tables(conn)
    ensure_shelter_tables(conn)
    ensure_investigation_tables(conn)
    ensure_khplan_table(conn)
    ensure_shelter_cost_table(conn)
    from ingest.domains.institutions_media_press import ensure_press_columns
    ensure_press_columns(conn)


def matched_terms(*parts: str | None) -> list[str]:
    hay = " ".join(part or "" for part in parts).casefold()
    found = [term for term in SEARCH_TERMS if term.casefold() in hay]
    kept = []
    for term in found:
        longer = any(
            term.casefold() != other.casefold() and term.casefold() in other.casefold()
            for other in found
        )
        if not longer:
            kept.append(term)
    return kept


def licence_is_free(label: str | None) -> bool:
    if label is None or not str(label).strip():
        return False
    text = str(label)
    if _NONFREE_RE.search(text):
        return False
    return _FREE_RE.search(text) is not None


def canonical_licence_url(short_name: str | None, explicit: str | None = None) -> str | None:
    url = clean(explicit)
    if url and url.startswith("http"):
        return url
    if not short_name:
        return None
    return CANONICAL_LICENCE_URLS.get(short_name.strip()) or CANONICAL_LICENCE_URLS.get(short_name.strip().upper())


def origin_licence(origin: str | None, land: str | None = None) -> tuple[str | None, str | None, str | None]:
    """Return (license, license_url, attribution) for a parliamentary origin."""
    if origin == "bundestag_dip":
        return DIP_LICENCE, DIP_LICENCE_URL, DIP_ATTRIBUTION
    if origin == "landtag_pardok":
        return PARDOK_LICENCE, PARDOK_LICENCE_URL, PARDOK_ATTRIBUTION
    if origin == "landtag_elvis":
        return ELVIS_LICENCE, ELVIS_LICENCE_URL, ELVIS_ATTRIBUTION
    if origin == "landtag_rss":
        rows = {
            "BY": (BY_RSS_LICENCE, BY_RSS_LICENCE_URL, BY_RSS_ATTRIBUTION),
            "HH": (HH_RSS_LICENCE, HH_RSS_LICENCE_URL, HH_RSS_ATTRIBUTION),
            "SH": (SH_RSS_LICENCE, SH_RSS_LICENCE_URL, SH_RSS_ATTRIBUTION),
        }
        return rows.get(land or "", (None, None, None))
    return None, None, None


def media_is_protected(*parts: str | None) -> bool:
    hay = " ".join(part or "" for part in parts).casefold()
    return any(term in hay for term in PROTECTED_MEDIA_TERMS)


def drop_protected_geotags(summary: str | None, *, protected: bool) -> str | None:
    """Never keep coordinate figures in text attached to a protected place."""
    text = clean(summary)
    if not text or not protected:
        return text
    text = re.sub(
        r"(?i)(?:gps|lat|lon|latitude|longitude)\s*[=:]?\s*[-+]?\d+(?:[.,]\d+)?(?:\s*[,/;]\s*[-+]?\d+(?:[.,]\d+)?)?",
        "",
        text,
    )
    text = re.sub(r"\s{2,}", " ", text).strip(" ,;.-")
    return text or None


def pdf_verdict(status, content_type, magic: bytes | None) -> str:
    """Accept only HTTP 200/206 with a PDF type or %PDF magic. HTML is not a PDF."""
    if status not in (200, 206):
        return "unavailable"
    head = magic or b""
    if head.lstrip().lower().startswith((b"<", b"<!doc", b"<html")):
        return "unavailable"
    ctype = (content_type or "").split(";")[0].strip().lower()
    if head.startswith(b"%PDF") or ctype == "application/pdf":
        return "verified_pdf"
    return "unavailable"


def text_content(value) -> str | None:
    if value is None:
        return None
    raw = re.sub(r"<[^>]+>", " ", str(value))
    return clean(html.unescape(raw))


def year_of(value: str | None) -> int | None:
    if not value:
        return None
    match = re.match(r"^(-?\d{1,6})", str(value).strip())
    if not match:
        return None
    year = int(match.group(1))
    if year < 800 or year > 2100:
        return None
    return year


def one_year(values) -> int | None:
    years = {year_of(v) for v in values}
    years.discard(None)
    if len(years) == 1:
        return next(iter(years))
    return None


def parse_point(value: str | None):
    """Wikidata P625 WKT is longitude then latitude."""
    if not value:
        return None
    match = _POINT_RE.search(str(value).strip())
    if not match:
        return None
    lon = float(match.group(1))
    lat = float(match.group(2))
    if not (-180 <= lon <= 180 and -90 <= lat <= 90):
        return None
    return lat, lon


def sole(values) -> str | None:
    items = []
    for value in values:
        text = clean(value)
        if text and text not in items:
            items.append(text)
    if len(items) == 1:
        return items[0]
    return None


def pick_land_and_city(land_parts, parent_parts):
    """Map ISO 3166-2 codes onto official abbreviations. Do not invent an AGS.

    City is the single non-Land P131 label. Berlin and Hamburg, whose Land item
    is also the city, use that label when it is the only parent. Several parents
    (a city plus a Regierungsbezirk) leave city empty.
    """
    iso_by_qid = {}
    abbrs = []
    for part in land_parts:
        if "=" not in part:
            continue
        qid, iso = part.split("=", 1)
        qid = qid.strip()
        suffix = iso.strip().removeprefix("DE-")
        if iso.strip().startswith("DE-") and suffix in LANDS and qid not in iso_by_qid:
            iso_by_qid[qid] = suffix
            if suffix not in abbrs:
                abbrs.append(suffix)
    land = abbrs[0] if len(abbrs) == 1 else None
    non_land = []
    land_parents = []
    for part in parent_parts:
        if "=" not in part:
            continue
        qid, label = part.split("=", 1)
        qid = qid.strip()
        label = clean(label)
        if not label:
            continue
        if qid in iso_by_qid:
            land_parents.append((label, iso_by_qid[qid]))
        elif label not in non_land:
            non_land.append(label)
    if len(non_land) == 1:
        city = non_land[0]
    elif not non_land and len(land_parents) == 1 and land_parents[0][1] in CITY_STATES:
        city = land_parents[0][0]
    else:
        city = None
    return land, city


def licence_sentence(text: str | None) -> str | None:
    """Copy the CC0 sentence from the Wikidata licensing extract, if it is there.

    The live sentence contains ``i.e.``, so splitting on every period drops it.
    """
    if not text:
        return None
    flat = re.sub(r"\s+", " ", text).strip()
    exact = re.search(
        r"All structured data \(i\.e\. the main, Property, Lexeme, and EntitySchema namespaces\) "
        r"is released into the public domain under Creative Commons Zero\.",
        flat,
    )
    if exact:
        return exact.group(0)
    start = flat.lower().find("all structured data")
    marker = "Creative Commons Zero"
    end = flat.find(marker)
    if start >= 0 and end > start:
        sentence = flat[start:end + len(marker)]
        if end + len(marker) < len(flat) and flat[end + len(marker)] == ".":
            sentence += "."
        sentence = clean(sentence)
        if sentence and len(sentence) <= 400:
            return sentence
    return None


def published_dip_key(page_text: str) -> str | None:
    match = _KEY_RE.search(page_text or "")
    if not match:
        return None
    return match.group(1)


def _split_concat(value: str | None) -> list[str]:
    if not value:
        return []
    return [part for part in str(value).split("§§") if part]


def _redact(text: str, secret: str | None) -> str:
    if secret and secret in text:
        return "note redacted because it contained an API key"
    return text


def _labels_of(entity: dict) -> set[str]:
    labels = entity.get("labels") or {}
    found = set()
    for lang in ("en", "de"):
        value = ((labels.get(lang) or {}).get("value") or "").casefold()
        if value:
            found.add(value)
    return found


def _entity_labels(ids: list[str], *, force: bool) -> dict:
    clean_ids = [item for item in ids if _QID_RE.match(item) or _PID_RE.match(item)]
    url = (
        WIKIDATA_API
        + "?"
        + urllib.parse.urlencode({
            "action": "wbgetentities",
            "ids": "|".join(clean_ids),
            "props": "labels",
            "languages": "en|de",
            "format": "json",
        })
    )
    payload = json.loads(fetch(url, domain=DOMAIN, force=force, headers={"Accept": "application/json"}))
    return payload.get("entities") or {}


def _load_dip_key() -> tuple[str, str]:
    env = (os.environ.get("DIP_API_KEY") or "").strip()
    if env:
        return env, "env"
    common._polite_wait()
    response = requests.get(
        DIP_HELP,
        headers={"User-Agent": common.UA, "Accept": "application/json"},
        timeout=60,
    )
    common._log(DOMAIN, DIP_HELP, response.status_code, len(response.content))
    if response.status_code == 403:
        raise SourceStopped("DIP help-api returned HTTP 403; stopped this source")
    if response.status_code != 200:
        raise SourceStopped(f"DIP help-api returned HTTP {response.status_code}; no key loaded")
    key = published_dip_key(response.text)
    if not key:
        raise SourceStopped(
            "DIP help-api did not contain a published API key. "
            f"Unblock via {DIP_HELP_PAGE} or {DIP_CONTACT}"
        )
    return key, "help-api"


def _probe(url: str, *, want_pdf: bool, attempts: int = 4) -> dict:
    """Range or catalog GET with polite backoff on 429, 5xx and network errors."""
    headers = {"User-Agent": common.UA, "Accept": "*/*"}
    if want_pdf:
        headers["Range"] = "bytes=0-15"
    note = "pdf-range" if want_pdf else "catalog"
    last = {"status": None, "content_type": "", "magic": b"", "error": None}
    delay = 1.0
    for attempt in range(max(1, int(attempts))):
        if attempt:
            time.sleep(delay)
            delay = min(delay * 2, 16)
        common._polite_wait()
        try:
            with requests.get(url, headers=headers, timeout=30, stream=True, allow_redirects=True) as response:
                status = response.status_code
                ctype = response.headers.get("Content-Type", "")
                chunk = next(response.iter_content(64), b"") or b""
                if isinstance(chunk, str):
                    chunk = chunk.encode("utf-8", "replace")
                nbytes = int(response.headers.get("Content-Length") or len(chunk) or 0)
                retry_after = response.headers.get("Retry-After")
        except requests.RequestException as exc:
            common._log(DOMAIN, url, "error", 0, note=f"{note} {type(exc).__name__} attempt={attempt + 1}")
            last = {"status": None, "content_type": "", "magic": b"", "error": type(exc).__name__}
            continue
        common._log(DOMAIN, url, status, nbytes, note=f"{note} attempt={attempt + 1}")
        last = {
            "status": status,
            "content_type": ctype,
            "magic": bytes(chunk[:16]),
            "error": None,
        }
        if status in (429, 500, 502, 503, 504):
            if retry_after:
                try:
                    wait = min(float(retry_after), 30.0)
                    if wait > 0:
                        time.sleep(wait)
                except ValueError:
                    pass
            continue
        return last
    return last


def _urheber_text(document: dict) -> str | None:
    titles = []
    for item in document.get("urheber") or []:
        if isinstance(item, str):
            title = clean(item)
        elif isinstance(item, dict):
            title = clean(item.get("titel") or item.get("bezeichnung"))
        else:
            title = None
        if title and title not in titles:
            titles.append(title)
    return "; ".join(titles) or None


def _doc_summary(publisher, typ, nummer, datum, titel) -> str | None:
    bits = [clean(publisher), clean(typ)]
    if clean(nummer):
        bits.append(f"Drucksache {clean(nummer)}")
    if clean(datum):
        bits.append(clean(datum))
    head = ", ".join(bit for bit in bits if bit)
    title = clean(titel)
    if head and title:
        return f"{head}. {title}"
    return head or title


def ensure_source_extensions(conn) -> None:
    """Add source.redistribute_fulltext without editing ingest/schema.sql."""
    cols = {row[1] for row in conn.execute("PRAGMA table_info(source)")}
    if "redistribute_fulltext" not in cols:
        conn.execute(
            "ALTER TABLE source ADD COLUMN redistribute_fulltext INTEGER NOT NULL DEFAULT 1 "
            "CHECK (redistribute_fulltext IN (0, 1))"
        )


def _register_source(
    conn, url, *, title, publisher, license_, bucket, license_url=None,
    attribution=None, notes=None, redistribute_fulltext=None,
):
    license_ = clean(license_)
    if not license_:
        raise ValueError("source.license must not be NULL; refuse to register " + (url or "unknown-url"))
    ensure_source_extensions(conn)
    source_id = source_id_for(
        conn, url, DOMAIN, title=clean(title), publisher=publisher, license=license_,
        license_url=clean(license_url), attribution=text_content(attribution) or clean(attribution),
        notes=clean(notes),
    )
    if redistribute_fulltext is not None:
        conn.execute(
            "UPDATE source SET redistribute_fulltext=? WHERE id=?",
            (1 if int(redistribute_fulltext) else 0, source_id),
        )
    bucket.append((url, license_))
    return source_id


# ---- Lead, 2026-11-21: cite only what is archived ------------------------------------------------------- #
COMMONS_API = "https://commons.wikimedia.org/w/api.php"


def _archive(url: str | None) -> bool:
    """Fetch (or reuse the cached copy of) the exact URL a row will cite. False when it cannot be archived."""
    if not url:
        return False
    if _OFFLINE[0]:
        return True
    try:
        fetch(url, domain=DOMAIN)
        return True
    except Exception:  # noqa: BLE001 - the row is dropped, not cited unarchived
        return False


def _commons_meta_url(page_url: str) -> str | None:
    if "/wiki/" not in page_url:
        return None
    title = page_url.split("/wiki/", 1)[1]
    return (f"{COMMONS_API}?action=query&format=json&formatversion=2&prop=imageinfo"
            f"&iiprop=extmetadata%7Curl&titles={title}")


def _commons_licence_matches(api_url: str, licence: str) -> bool:
    """The archived per-file extmetadata must state the licence we store."""
    if _OFFLINE[0]:
        return True
    try:
        data = json.loads(fetch(api_url, domain=DOMAIN).decode("utf-8", "replace"))
        pages = (data.get("query") or {}).get("pages") or []
        meta = ((pages[0].get("imageinfo") or [{}])[0].get("extmetadata") or {}) if pages else {}
        short = clean(text_content((meta.get("LicenseShortName") or {}).get("value")))
    except Exception:  # noqa: BLE001
        return False
    return bool(short) and short.casefold() == (licence or "").casefold()


def store_drucksache(conn, rec: dict, *, license_, sources) -> bool:
    dip_id = clean(rec.get("dip_id"))
    if not dip_id:
        return False
    titel = clean(rec.get("titel"))
    nummer = clean(rec.get("dokumentnummer"))
    if not titel and not nummer:
        return False
    herausgeber = clean(rec.get("herausgeber"))
    publisher = clean(rec.get("publisher")) or PUBLISHERS.get(herausgeber or "")
    origin = clean(rec.get("origin")) or "bundestag_dip"
    land = clean(rec.get("land"))
    if not land:
        if origin == "bundestag_dip":
            land = "DE" if publisher else None
        elif herausgeber in LANDS:
            land = herausgeber
    if land and land != "DE" and land not in LANDS:
        land = None
    parliament = clean(rec.get("parliament")) or publisher
    catalog_url = clean(rec.get("catalog_url"))
    pdf_url = clean(rec.get("pdf_url"))
    if origin == "bundestag_dip":
        api_url = f"{DIP_LIST}/{dip_id}"
        catalog_url = catalog_url or f"https://dip.bundestag.de/drucksache/{dip_id}"
        source_url = catalog_url if rec.get("catalog_ok") else api_url
        doc_url = catalog_url if rec.get("catalog_ok") else api_url
    else:
        source_url = clean(rec.get("source_url")) or catalog_url or pdf_url
        if rec.get("catalog_ok") and catalog_url:
            doc_url = catalog_url
        elif rec.get("pdf_status") == "verified_pdf" and pdf_url:
            doc_url = pdf_url
        else:
            return False
        # Anfrage and Antwort (and similar pairs) often share one official PDF.
        # Keep a unique doc.url so both dates and types are stored.
        if doc_url and "#" not in doc_url:
            doc_url = f"{doc_url}#{dip_id}"
        if not source_url:
            source_url = catalog_url or pdf_url or doc_url
    if not source_url or not source_url.startswith("http"):
        return False
    # Lead: the cited source is the archived document itself: the verified PDF, or for an RSS item without a
    # PDF its catalog page. A DIP/PARDOK row whose document cannot be archived is not stored.
    if rec.get("pdf_status") == "verified_pdf" and pdf_url:
        source_url = pdf_url
    elif origin == "landtag_rss" and catalog_url:
        source_url = catalog_url
    else:
        return False
    if not _archive(source_url):
        return False
    default_lic, default_url, default_attr = origin_licence(origin, land)
    license_ = clean(license_) or default_lic
    license_url = clean(rec.get("license_url")) or default_url
    attribution = clean(rec.get("attribution")) or default_attr
    if not license_ or license_.upper().startswith("TODO"):
        return False            # Lead: no row without an established licence (ELVIS, HH, SH until confirmed)
    source_id = _register_source(
        conn, source_url, title=titel, publisher=publisher, license_=license_,
        license_url=license_url, attribution=attribution, bucket=sources,
        redistribute_fulltext=0 if license_ == RESERVED_LICENCE else None,
    )
    terms = rec.get("matched_terms")
    if terms is None:
        terms = matched_terms(titel)
    term_text = ", ".join(terms) if terms else None
    summary = _doc_summary(publisher, rec.get("drucksachetyp"), nummer, rec.get("datum"), titel)
    upsert(conn, "doc", {
        "kind": "report",
        "title": titel,
        "url": doc_url,
        "herausgeber": publisher,
        "urheber": clean(rec.get("urheber")),
        "veroeffentlicht": clean(rec.get("datum")),
        "land": land,
        "zusammenfassung": summary,
        "source_id": source_id,
    }, ["url"])
    upsert(conn, "institutions_media_drucksache", {
        "dip_id": dip_id,
        "dokumentnummer": nummer,
        "drucksachetyp": clean(rec.get("drucksachetyp")),
        "wahlperiode": rec.get("wahlperiode"),
        "herausgeber": herausgeber,
        "titel": titel,
        "datum": clean(rec.get("datum")),
        "urheber": clean(rec.get("urheber")),
        "pdf_url": pdf_url,
        "pdf_status": clean(rec.get("pdf_status")),
        "catalog_url": catalog_url,
        "matched_terms": term_text,
        "land": land,
        "origin": origin,
        "parliament": parliament,
        "source_id": source_id,
    }, ["dip_id"])
    return True


def store_facility(conn, rec: dict, *, license_, sources, notes: list[str]) -> bool:
    kind = clean(rec.get("kind")) or "other"
    name = clean(rec.get("name"))
    if not name or not name_norm(name):
        return False
    protected = kind in PROTECTED_KINDS
    address = None if protected else clean(rec.get("address"))
    plz = None if protected else clean(rec.get("plz"))
    lat = None if protected else rec.get("lat")
    lon = None if protected else rec.get("lon")
    land = rec.get("land") if rec.get("land") in LANDS else None
    city = clean(rec.get("city"))
    qid = clean(rec.get("qid"))
    entity_url = rec.get("wikidata_url") or (
        f"https://www.wikidata.org/wiki/Special:EntityData/{qid}.json" if qid else None
    )
    if not entity_url:
        return False
    license_ = clean(license_) or WIKIDATA_LICENCE
    source_id = _register_source(
        conn, entity_url, title=name, publisher="Wikidata", license_=license_,
        license_url=clean(rec.get("license_url")) or WIKIDATA_LICENCE_PAGE,
        attribution=clean(rec.get("attribution")) or WIKIDATA_ATTRIBUTION,
        bucket=sources,
    )
    row = {
        "name": name,
        "name_norm": name_norm(name),
        "kind": kind,
        "betriebsstatus": clean(rec.get("status")) or "unknown",
        "eroeffnet": rec.get("opened"),
        "geschlossen": rec.get("closed"),
        "betten": rec.get("beds"),
        "traeger": clean(rec.get("operator")),
        "land": land,
        "kreis_ags": None if protected else rec.get("kreis_ags"),
        "ort": city,
        "anschrift": address,
        "plz": plz,
        "lat": lat,
        "lon": lon,
        "is_protected": 1 if protected else 0,
        "zielgruppe": clean(rec.get("population_note")),
        "source_id": source_id,
        "is_est": 0,
    }
    if not protected and not row["kreis_ags"] and qid:
        # Only the official German district/municipality key on the archived entity.
        try:
            raw = fetch(entity_url, domain=DOMAIN)
            row["kreis_ags"] = kreis_ags_from_wikidata_entity(json.loads(raw.decode("utf-8", "replace")))
        except Exception:
            row["kreis_ags"] = None
    # Economics stay NULL unless a cited document was checked. This pass does not
    # copy Wikidata revenue or asset figures.
    existing_id = None
    if qid:
        found = conn.execute(
            "SELECT facility_id FROM institutions_media_facility WHERE qid=?",
            (qid,),
        ).fetchone()
        if found and found[0]:
            existing_id = found[0]
    facility_id = existing_id
    try:
        if existing_id:
            assignments = []
            values = []
            for column in FACILITY_COLS:
                if column in ("anschrift", "plz", "lat", "lon", "kreis_ags") and protected:
                    assignments.append(f"{column}=NULL")
                    continue
                if column == "is_protected" and protected:
                    assignments.append("is_protected=1")
                    continue
                value = row[column]
                if value is None:
                    continue
                assignments.append(f"{column}=?")
                values.append(value)
            values.append(existing_id)
            conn.execute(
                f"UPDATE facility SET {', '.join(assignments)} WHERE id=?",
                values,
            )
        else:
            # Protected rows explicitly store NULL address/lat/lon. Budget is not a column.
            columns = [
                column for column in FACILITY_COLS
                if row[column] is not None or (protected and column in ("anschrift", "plz", "lat", "lon", "kreis_ags"))
            ]
            conn.execute(
                f"INSERT INTO facility ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
                [row[column] for column in columns],
            )
            facility_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    except sqlite3.IntegrityError:
        notes.append(
            f"facility natural-key collision for {qid or name}; left the existing row in place"
        )
        facility_id = None
    website = clean(rec.get("website"))
    if website and not str(website).startswith("http"):
        website = None
    if qid:
        upsert(conn, "institutions_media_facility", {
            "qid": qid,
            "facility_id": facility_id,
            "kind": kind,
            "website": website,
            "wikidata_url": f"https://www.wikidata.org/wiki/{qid}",
            "source_id": source_id,
        }, ["qid"])
    return facility_id is not None


def store_media(conn, rec: dict, sources) -> bool:
    url = clean(rec.get("url"))
    license_ = clean(rec.get("license"))
    if not url or not licence_is_free(license_):
        return False
    kind = rec.get("kind")
    if kind not in ("image", "video"):
        return False
    title = clean(rec.get("title"))
    author = text_content(rec.get("author") or rec.get("credit"))
    attribution = clean(rec.get("attribution")) or author
    license_url = canonical_licence_url(license_, rec.get("license_url"))
    protected = bool(rec.get("is_protected")) or media_is_protected(
        title, rec.get("summary"), rec.get("categories"), author,
    )
    # Never persist Commons geotags for a protected place (or at all on media).
    summary = drop_protected_geotags(text_content(rec.get("summary")), protected=protected)
    place = None if protected else clean(rec.get("place"))
    # Lead: cite the archived per-file Commons extmetadata (licence, author) instead of the unarchived file page
    meta_url = _commons_meta_url(url)
    if not meta_url or not _archive(meta_url) or not _commons_licence_matches(meta_url, license_):
        return False
    source_id = _register_source(
        conn, meta_url, title=title, publisher="Wikimedia Commons",
        license_=license_, license_url=license_url, attribution=attribution,
        bucket=sources,
    )
    upsert(conn, "media", {
        "kind": kind,
        "title": title,
        "url": url,
        "vorschaubild": clean(rec.get("thumbnail")),
        "herausgeber": clean(rec.get("publisher")) or "Wikimedia Commons",
        "urheber": author,
        "veroeffentlicht": clean(rec.get("published")),
        "ort": place,
        "lizenz": license_,
        "zusammenfassung": summary,
        "source_id": source_id,
    }, ["url"])
    return True


def _ingest_fixture(conn, path: str, sources, notes) -> dict:
    with open(path, encoding="utf-8") as handle:
        payload = json.loads(handle.read())
    docs = facilities = media = 0
    for raw in payload.get("drucksachen") or []:
        urheber = _urheber_text(raw) if isinstance(raw.get("urheber"), list) else clean(raw.get("urheber"))
        fund = raw.get("fundstelle") or {}
        rec = {
            "dip_id": str(raw.get("id") or raw.get("dip_id")),
            "dokumentnummer": raw.get("dokumentnummer"),
            "drucksachetyp": raw.get("drucksachetyp"),
            "wahlperiode": raw.get("wahlperiode"),
            "herausgeber": raw.get("herausgeber"),
            "titel": raw.get("titel"),
            "datum": raw.get("datum"),
            "urheber": urheber,
            "pdf_url": fund.get("pdf_url") or raw.get("pdf_url"),
            "pdf_status": raw.get("pdf_status") or "unchecked",
            "catalog_url": raw.get("catalog_url"),
            "catalog_ok": raw.get("catalog_status") == 200,
            "land": raw.get("land"),
            "origin": raw.get("origin") or "bundestag_dip",
            "parliament": raw.get("parliament"),
            "source_url": raw.get("source_url"),
            "matched_terms": matched_terms(raw.get("titel"), raw.get("description")),
        }
        docs += int(store_drucksache(conn, rec, license_=raw.get("license"), sources=sources))
    for raw in payload.get("facilities") or []:
        facilities += int(store_facility(
            conn, raw,
            license_=raw.get("license") or WIKIDATA_LICENCE,
            sources=sources, notes=notes,
        ))
    for raw in payload.get("media") or []:
        media += int(store_media(conn, raw, sources))
    audits = 0
    if payload.get("audits"):
        from ingest.domains.institutions_media_rechnungshof import ingest_rechnungshof_catalog
        audits = ingest_rechnungshof_catalog(
            conn, {**{"skip_verify": True}, **{}}, sources, notes, catalog=payload["audits"]
        )
    notes.append(f"fixture={path}")
    notes.append(f"doc={docs} facility={facilities} media={media} drucksache={docs} audit={audits}")
    return {"docs": docs, "facilities": facilities, "media": media, "audits": audits}


def _dip_record(document: dict, *, secret: str, skip_verify: bool, pdf_blocked: list, catalog_blocked: list) -> dict:
    dip_id = str(document.get("id") or "").strip()
    fund = document.get("fundstelle") or {}
    pdf_url = clean(fund.get("pdf_url") or document.get("pdf_url"))
    catalog_url = f"https://dip.bundestag.de/drucksache/{dip_id}"
    if pdf_url and secret in pdf_url:
        pdf_url = None
    pdf_status = "no_url"
    if pdf_url and skip_verify:
        pdf_status = "unchecked"
    elif pdf_url and pdf_blocked[0]:
        pdf_status = "skipped_after_403"
    elif pdf_url:
        probed = _probe(pdf_url, want_pdf=True)
        if probed["status"] == 403:
            pdf_blocked[0] = True
            pdf_status = "skipped_after_403"
        else:
            pdf_status = pdf_verdict(probed["status"], probed["content_type"], probed["magic"])
    catalog_ok = False
    if skip_verify:
        catalog_ok = True
    elif catalog_blocked[0]:
        catalog_ok = False
    else:
        probed = _probe(catalog_url, want_pdf=False)
        if probed["status"] == 403:
            catalog_blocked[0] = True
        catalog_ok = probed["status"] == 200
    wahlperiode = document.get("wahlperiode")
    if not isinstance(wahlperiode, int):
        try:
            wahlperiode = int(wahlperiode) if wahlperiode is not None else None
        except (TypeError, ValueError):
            wahlperiode = None
    return {
        "dip_id": dip_id,
        "dokumentnummer": document.get("dokumentnummer"),
        "drucksachetyp": document.get("drucksachetyp"),
        "wahlperiode": wahlperiode,
        "herausgeber": document.get("herausgeber"),
        "titel": document.get("titel"),
        "datum": document.get("datum"),
        "urheber": _urheber_text(document),
        "pdf_url": pdf_url,
        "pdf_status": pdf_status,
        "catalog_url": catalog_url,
        "catalog_ok": catalog_ok,
        "land": "DE",
        "origin": "bundestag_dip",
        "parliament": PUBLISHERS.get(document.get("herausgeber") or ""),
        "matched_terms": matched_terms(document.get("titel")),
    }


def ingest_dip(conn, cfg, sources, notes) -> int:
    try:
        key, origin = _load_dip_key()
    except SourceStopped as exc:
        notes.append(_redact(exc.note, None))
        return 0
    notes.append(f"DIP key source={origin}")
    stored = 0
    seen_ids = set()
    seen_cursors = set()
    cursor = None
    pages = 0
    statuses = defaultdict(int)
    pdf_blocked = [False]
    catalog_blocked = [False]
    limit = cfg.get("limit")
    skip_verify = bool(cfg.get("skip_verify"))
    num_found = None
    while pages < 20:
        params = [("f.titel", term) for term in SEARCH_TERMS]
        params.append(("format", "json"))
        if cursor:
            params.append(("cursor", cursor))
        url = DIP_LIST + "?" + urllib.parse.urlencode(params, doseq=True)
        if key in url:
            raise RuntimeError("DIP key must not be placed in a URL")
        try:
            raw = fetch(
                url,
                domain=DOMAIN,
                force=bool(cfg.get("force")),
                headers={"Authorization": f"ApiKey {key}", "Accept": "application/json"},
            )
        except RuntimeError as exc:
            message = _redact(str(exc), key)
            if "HTTP 401" in str(exc):
                notes.append(
                    "DIP API returned HTTP 401. This source is blocked until a valid key is available. "
                    f"The published key is on {DIP_HELP_PAGE} (valid as stated there, currently through May 2027) "
                    f"or by writing to {DIP_CONTACT}."
                )
            elif "HTTP 403" in str(exc):
                notes.append("DIP API returned HTTP 403; stopped this source")
            else:
                notes.append(f"DIP list fetch failed: {message[:240]}")
            break
        payload = json.loads(raw)
        documents = payload.get("documents") or []
        if pages == 0:
            num_found = payload.get("numFound")
            notes.append(f"DIP numFound={num_found}")
            if isinstance(num_found, int) and num_found > 5000:
                notes.append("DIP numFound above 5000; title filter looks wrong, stopped without storing")
                break
        if not documents:
            break
        fresh = 0
        for document in documents:
            dip_id = str(document.get("id") or "")
            if not dip_id or dip_id in seen_ids:
                continue
            seen_ids.add(dip_id)
            fresh += 1
            if limit is not None and stored >= int(limit):
                break
            rec = _dip_record(
                document,
                secret=key,
                skip_verify=skip_verify,
                pdf_blocked=pdf_blocked,
                catalog_blocked=catalog_blocked,
            )
            if store_drucksache(conn, rec, license_=None, sources=sources):
                stored += 1
                statuses[rec["pdf_status"]] += 1
                if stored % 20 == 0:
                    print(f"DIP progress stored={stored}", flush=True)
        pages += 1
        new_cursor = payload.get("cursor")
        if limit is not None and stored >= int(limit):
            notes.append(f"DIP stopped at limit={limit}")
            break
        if not new_cursor or new_cursor == cursor or new_cursor in seen_cursors or fresh == 0:
            break
        seen_cursors.add(new_cursor)
        cursor = new_cursor
    if pdf_blocked[0]:
        notes.append("DIP PDF host returned HTTP 403; remaining PDF checks were skipped")
    if catalog_blocked[0]:
        notes.append("DIP catalog host returned HTTP 403; remaining catalog checks were skipped")
    status_text = ", ".join(f"{name}={count}" for name, count in sorted(statuses.items()))
    notes.append(f"DIP stored={stored} pages={pages} pdf[{status_text}]")
    return stored


def _confirmed_ids(force: bool, notes: list[str]) -> dict | None:
    try:
        entities = _entity_labels(list(EXPECTED_LABELS), force=force)
    except Exception as exc:
        notes.append(f"Wikidata label check failed ({type(exc).__name__}); facilities skipped")
        return None
    confirmed = {}
    mismatched = []
    for qid, accepted in EXPECTED_LABELS.items():
        entity = entities.get(qid) or {}
        if entity.get("missing"):
            mismatched.append(qid)
            continue
        labels = _labels_of(entity)
        if labels & accepted:
            confirmed[qid] = True
        else:
            mismatched.append(qid)
    if mismatched:
        notes.append("Wikidata label mismatch, not used: " + ", ".join(mismatched))
    if "Q183" not in confirmed or "Q1221156" not in confirmed:
        notes.append("Wikidata Germany or Land class label did not match; facilities skipped")
        return None
    return confirmed


def _facility_sparql(confirmed: dict) -> str:
    branches = []
    by_kind = defaultdict(list)
    for qid, kind in KIND_OF.items():
        if confirmed.get(qid) and _QID_RE.match(qid):
            by_kind[kind].append(qid)
    for kind in ("psych_unit", "psychiatric", "prison"):
        qids = by_kind.get(kind) or []
        if not qids:
            continue
        values = " ".join(f"wd:{qid}" for qid in qids)
        branches.append(
            "{ VALUES ?class { " + values + " } ?item wdt:P31 ?class . "
            + 'BIND("' + kind + '" AS ?kind) }'
        )
    if not branches:
        return ""
    shelter = ""
    if confirmed.get("Q1451763"):
        shelter = "FILTER NOT EXISTS { ?item wdt:P31 wd:Q1451763 }"
    optionals = [
        'OPTIONAL { ?item rdfs:label ?de FILTER(lang(?de)="de") }',
        'OPTIONAL { ?item rdfs:label ?en FILTER(lang(?en)="en") }',
    ]
    if confirmed.get("P300"):
        optionals.append(
            "OPTIONAL { ?item wdt:P131+ ?land . ?land wdt:P31 wd:Q1221156 . ?land wdt:P300 ?iso }"
        )
    optionals.append(
        "OPTIONAL { ?item wdt:P131 ?parent . "
        'OPTIONAL { ?parent rdfs:label ?parentDe FILTER(lang(?parentDe)="de") } }'
    )
    if confirmed.get("P625"):
        optionals.append("OPTIONAL { ?item wdt:P625 ?coord }")
    if confirmed.get("P6801"):
        optionals.append("OPTIONAL { ?item wdt:P6801 ?bed }")
    if confirmed.get("P571"):
        optionals.append("OPTIONAL { ?item wdt:P571 ?opened }")
    if confirmed.get("P576"):
        optionals.append("OPTIONAL { ?item wdt:P576 ?dissolved }")
    if confirmed.get("P3999"):
        optionals.append("OPTIONAL { ?item wdt:P3999 ?closedOn }")
    if confirmed.get("P6375"):
        optionals.append("OPTIONAL { ?item wdt:P6375 ?addr }")
    if confirmed.get("P856"):
        optionals.append("OPTIONAL { ?item wdt:P856 ?web }")
    if confirmed.get("P137"):
        optionals.append(
            "OPTIONAL { ?item wdt:P137 ?op . "
            'OPTIONAL { ?op rdfs:label ?opDe FILTER(lang(?opDe)="de") } '
            'OPTIONAL { ?op rdfs:label ?opEn FILTER(lang(?opEn)="en") } }'
        )
    select_tail = ""
    if confirmed.get("P300"):
        select_tail += '(GROUP_CONCAT(DISTINCT CONCAT(REPLACE(STR(?land),"http://www.wikidata.org/entity/",""),"=",?iso); separator="§§") AS ?landIsos) '
    select_tail += (
        '(GROUP_CONCAT(DISTINCT CONCAT(REPLACE(STR(?parent),"http://www.wikidata.org/entity/",""),"=",COALESCE(?parentDe,"")); separator="§§") AS ?parents) '
    )
    if confirmed.get("P625"):
        select_tail += '(GROUP_CONCAT(DISTINCT STR(?coord); separator="§§") AS ?coords) '
    if confirmed.get("P6801"):
        select_tail += '(GROUP_CONCAT(DISTINCT STR(?bed); separator="§§") AS ?beds) '
    if confirmed.get("P571"):
        select_tail += '(GROUP_CONCAT(DISTINCT STR(?opened); separator="§§") AS ?openeds) '
    if confirmed.get("P576"):
        select_tail += '(GROUP_CONCAT(DISTINCT STR(?dissolved); separator="§§") AS ?dissolveds) '
    if confirmed.get("P3999"):
        select_tail += '(GROUP_CONCAT(DISTINCT STR(?closedOn); separator="§§") AS ?closedons) '
    if confirmed.get("P6375"):
        select_tail += '(GROUP_CONCAT(DISTINCT ?addr; separator="§§") AS ?addrs) '
    if confirmed.get("P856"):
        select_tail += '(GROUP_CONCAT(DISTINCT ?web; separator="§§") AS ?webs) '
    if confirmed.get("P137"):
        select_tail += '(GROUP_CONCAT(DISTINCT ?opDe; separator="§§") AS ?opsDe) '
        select_tail += '(GROUP_CONCAT(DISTINCT ?opEn; separator="§§") AS ?opsEn) '
    return f"""
SELECT ?item ?kind ?de ?en {select_tail}
WHERE {{
  {{
    SELECT DISTINCT ?item ?kind WHERE {{
      {" UNION ".join(branches)}
      {shelter}
      {{ ?item wdt:P17 wd:Q183 }} UNION {{ ?item wdt:P131+ ?land0 . ?land0 wdt:P31 wd:Q1221156 }}
    }}
  }}
  {" ".join(optionals)}
}}
GROUP BY ?item ?kind ?de ?en
"""


def _wikidata_licence(force: bool) -> tuple[str, str] | None:
    """Return ("CC0 1.0", licensing-page URL) only after that page returns HTTP 200."""
    probed = _probe(WIKIDATA_LICENCE_PAGE, want_pdf=False)
    if probed["status"] != 200:
        return None
    return WIKIDATA_LICENCE, WIKIDATA_LICENCE_PAGE


def _merge_facilities(bindings) -> dict:
    items = {}
    for binding in bindings:
        values = {key: val.get("value") for key, val in binding.items()}
        qid = (values.get("item") or "").rsplit("/", 1)[-1]
        if not _QID_RE.match(qid):
            continue
        rec = items.setdefault(qid, {"kinds": set(), "de": None, "en": None, "parts": defaultdict(set)})
        if values.get("kind"):
            rec["kinds"].add(values["kind"])
        if values.get("de"):
            rec["de"] = rec["de"] or values["de"]
        if values.get("en"):
            rec["en"] = rec["en"] or values["en"]
        for key, raw in values.items():
            if key in ("item", "kind", "de", "en"):
                continue
            rec["parts"][key].update(_split_concat(raw))
    return items


def _facility_from_parts(qid: str, merged: dict) -> dict | None:
    name = clean(merged.get("de")) or clean(merged.get("en"))
    if not name:
        return None
    kinds = merged["kinds"]
    note = None
    if kinds == {"psych_unit"}:
        kind = "psych_unit"
    elif kinds == {"psychiatric"} or kinds == {"psychiatric", "psych_unit"}:
        kind = "psychiatric"
    elif kinds == {"prison"}:
        kind = "prison"
    elif "prison" in kinds and ({"psychiatric", "psych_unit"} & kinds):
        kind = "other"
        note = "Wikidata: instance of both a psychiatric class and a prison class"
    else:
        kind = "other"
    parts = merged["parts"]
    land, city = pick_land_and_city(parts.get("landIsos", ()), parts.get("parents", ()))
    point_values = list(parts.get("coords", ()))
    point = parse_point(point_values[0]) if len(point_values) == 1 else None
    bed_values = list(parts.get("beds", ()))
    beds = None
    if len(bed_values) == 1:
        try:
            beds = int(float(bed_values[0]))
        except ValueError:
            beds = None
    closed_on = one_year(parts.get("closedons", ()))
    dissolved = one_year(parts.get("dissolveds", ()))
    has_end = bool(parts.get("closedons") or parts.get("dissolveds"))
    if parts.get("closedons"):
        closed = closed_on
    else:
        closed = dissolved
    operators = [clean(v) for v in parts.get("opsDe", ()) if clean(v)]
    if not operators:
        operators = [clean(v) for v in parts.get("opsEn", ()) if clean(v)]
    websites = [v for v in parts.get("webs", ()) if str(v).startswith("http")]
    return {
        "qid": qid,
        "name": name,
        "kind": kind,
        "status": "closed" if has_end else "unknown",
        "opened": one_year(parts.get("openeds", ())),
        "closed": closed,
        "beds": beds if beds is None or beds >= 0 else None,
        "operator": "; ".join(sorted(set(operators))) or None,
        "land": land,
        "city": city,
        "address": sole(parts.get("addrs", ())),
        "lat": point[0] if point else None,
        "lon": point[1] if point else None,
        "website": websites[0] if len(websites) == 1 else None,
        "population_note": note,
        "multi_beds": len(bed_values) > 1,
        "multi_coords": len(point_values) > 1,
        "multi_webs": len(websites) > 1,
    }


def ingest_facilities(conn, cfg, sources, notes) -> int:
    confirmed = _confirmed_ids(bool(cfg.get("force")), notes)
    if not confirmed:
        return 0
    query = _facility_sparql(confirmed)
    if not query.strip():
        notes.append("Wikidata facility classes did not match live labels; nothing stored")
        return 0
    try:
        licensed = _wikidata_licence(bool(cfg.get("force")))
    except Exception as exc:
        licensed = None
        notes.append(f"Wikidata licence page failed ({type(exc).__name__}); facilities skipped")
    if not licensed:
        notes.append(
            f"Wikidata licence page {WIKIDATA_LICENCE_PAGE} did not return HTTP 200; "
            "facilities skipped so no source.license is left NULL"
        )
        return 0
    licence, licence_url = licensed
    notes.append(f"Wikidata licence={licence} url={licence_url}")
    try:
        raw = fetch(
            WIKIDATA_SPARQL,
            method="POST",
            data=urllib.parse.urlencode({"query": query}),
            headers={
                "Accept": "application/sparql-results+json",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            domain=DOMAIN,
            force=bool(cfg.get("force")),
            timeout=180,
        )
    except Exception as exc:
        message = str(exc)
        if "HTTP 403" in message:
            notes.append("Wikidata SPARQL returned HTTP 403; stopped this source")
        else:
            notes.append(f"Wikidata SPARQL failed: {message[:240]}")
        return 0
    payload = json.loads(raw)
    if payload.get("error") or "results" not in payload:
        notes.append("Wikidata SPARQL response had no results; facilities skipped")
        return 0
    bindings = (payload.get("results") or {}).get("bindings") or []
    merged = _merge_facilities(bindings)
    limit = cfg.get("limit")
    stored = 0
    skipped_name = multi_beds = multi_coords = multi_webs = 0
    kind_counts = defaultdict(int)
    for qid, item in merged.items():
        if limit is not None and stored >= int(limit):
            notes.append(f"facilities stopped at limit={limit}")
            break
        rec = _facility_from_parts(qid, item)
        if rec is None:
            skipped_name += 1
            continue
        multi_beds += int(bool(rec.pop("multi_beds")))
        multi_coords += int(bool(rec.pop("multi_coords")))
        multi_webs += int(bool(rec.pop("multi_webs")))
        rec["license_url"] = licence_url
        rec["attribution"] = WIKIDATA_ATTRIBUTION
        if store_facility(conn, rec, license_=licence, sources=sources, notes=notes):
            stored += 1
            kind_counts[rec["kind"]] += 1
    kind_text = ", ".join(f"{name}={count}" for name, count in sorted(kind_counts.items()))
    notes.append(
        f"Wikidata items={len(merged)} stored={stored} no_label={skipped_name} "
        f"kinds[{kind_text}] multi_bed_null={multi_beds} multi_coord_null={multi_coords} "
        f"multi_website_null={multi_webs}"
    )
    notes.append(
        "facility budget and annual_cost_per_bed left NULL; "
        "Wikidata revenue/asset statements were not copied because no cited EUR document was verified"
    )
    return stored


def _commons_kind(info: dict) -> str | None:
    mediatype = (info.get("mediatype") or "").upper()
    mime = (info.get("mime") or "").lower()
    if mediatype == "VIDEO" or mime.startswith("video/"):
        return "video"
    if mediatype in {"BITMAP", "DRAWING"} or mime.startswith("image/"):
        return "image"
    return None


def _extmeta(meta: dict, *keys: str) -> str | None:
    for key in keys:
        value = (meta.get(key) or {}).get("value") if isinstance(meta.get(key), dict) else meta.get(key)
        text = text_content(value) if value is not None else None
        if text:
            return text
    return None


def _commons_geotags(meta: dict):
    lat = _extmeta(meta, "GPSLatitude")
    lon = _extmeta(meta, "GPSLongitude")
    try:
        if lat is not None and lon is not None:
            return float(str(lat).replace(",", ".")), float(str(lon).replace(",", "."))
    except (TypeError, ValueError):
        return None
    return None


def _media_from_page(page: dict) -> tuple[dict | None, str | None]:
    """Return (record, skip_reason). skip_reason is set when the file is not stored."""
    info = ((page.get("imageinfo") or [None])[0]) or None
    if not info:
        return None, "no_info"
    meta = info.get("extmetadata") or {}
    license_ = _extmeta(meta, "LicenseShortName")
    if not license_:
        return None, "licence_missing"
    if not licence_is_free(license_):
        return None, "licence_nonfree"
    kind = _commons_kind(info)
    url = clean(info.get("descriptionurl"))
    if not kind or not url:
        return None, "not_media"
    title = page.get("title") or ""
    if title.startswith("File:"):
        title = title[5:]
    published = _extmeta(meta, "DateTimeOriginal", "DateTime")
    summary = _extmeta(meta, "ImageDescription")
    if summary and len(summary) > 500:
        summary = summary[:500]
    published_text = clean(published)
    if published_text and len(published_text) > 64:
        published_text = None
    author = _extmeta(meta, "Artist", "Credit")
    attribution = _extmeta(meta, "Attribution", "Credit", "Artist")
    categories = _extmeta(meta, "Categories")
    protected = media_is_protected(title, summary, categories, author, attribution)
    coords = _commons_geotags(meta)
    geotags_dropped = False
    if protected and coords:
        geotags_dropped = True
        coords = None
        summary = drop_protected_geotags(summary, protected=True)
    elif protected:
        summary = drop_protected_geotags(summary, protected=True)
    return {
        "title": clean(title),
        "url": url,
        "kind": kind,
        "license": clean(license_),
        "license_url": canonical_licence_url(license_, _extmeta(meta, "LicenseUrl")),
        "author": author,
        "attribution": attribution,
        "credit": _extmeta(meta, "Credit"),
        "published": published_text,
        "summary": summary,
        "categories": categories,
        "publisher": "Wikimedia Commons",
        "is_protected": protected,
        "geotags_dropped": geotags_dropped,
        # Geotags are parsed only so they can be dropped for protected files.
        # They are never written to media or source rows.
        "lat": None,
        "lon": None,
    }, None


def _commons_query(params: dict, *, force: bool) -> dict:
    url = COMMONS_API + "?" + urllib.parse.urlencode(params)
    raw = fetch(url, domain=DOMAIN, force=force, headers={"Accept": "application/json"})
    return json.loads(raw)


def _walk_commons(base: dict, *, force: bool, seen: set, sink: list, notes: list[str], label: str, skip_counts=None) -> None:
    cont = {}
    pages = 0
    while pages < 10:
        params = dict(base)
        params.update(cont)
        try:
            payload = _commons_query(params, force=force)
        except Exception as exc:
            message = str(exc)
            if "HTTP 403" in message:
                raise SourceStopped(f"Commons returned HTTP 403 during {label}") from exc
            notes.append(f"Commons {label} failed: {message[:200]}")
            return
        if payload.get("error"):
            code = (payload.get("error") or {}).get("code")
            notes.append(f"Commons {label} error={code}")
            return
        query = payload.get("query") or {}
        page_map = query.get("pages") or {}
        for page in page_map.values():
            rec, skip = _media_from_page(page)
            if rec is None:
                if skip_counts is not None:
                    skip_counts[skip or "unknown"] += 1
                continue
            if rec["url"] in seen:
                continue
            seen.add(rec["url"])
            sink.append(rec)
        pages += 1
        if "continue" not in payload:
            return
        cont = payload["continue"]
    notes.append(f"Commons {label} stopped after {pages} pages")


def _subcats(force: bool, notes: list[str]) -> list[str]:
    try:
        payload = _commons_query({
            "action": "query",
            "list": "categorymembers",
            "cmtitle": "Category:Homelessness in Germany",
            "cmtype": "subcat",
            "cmlimit": "50",
            "format": "json",
        }, force=force)
    except Exception as exc:
        notes.append(f"Commons subcats failed: {str(exc)[:160]}")
        return []
    found = []
    for member in (payload.get("query") or {}).get("categorymembers") or []:
        title = member.get("title") or ""
        if any(word in title.casefold() for word in SUBCAT_WORDS):
            found.append(title)
    return found


def ingest_media(conn, cfg, sources, notes) -> int:
    force = bool(cfg.get("force"))
    seen = set()
    records = []
    skip_counts = defaultdict(int)
    try:
        for category in COMMONS_CATEGORIES:
            _walk_commons({
                "action": "query",
                "generator": "categorymembers",
                "gcmtitle": category,
                "gcmtype": "file",
                "gcmlimit": "50",
                "prop": "imageinfo",
                "iiprop": "url|mime|mediatype|extmetadata",
                "format": "json",
            }, force=force, seen=seen, sink=records, notes=notes, label=category, skip_counts=skip_counts)
        for category in _subcats(force, notes):
            _walk_commons({
                "action": "query",
                "generator": "categorymembers",
                "gcmtitle": category,
                "gcmtype": "file",
                "gcmlimit": "50",
                "prop": "imageinfo",
                "iiprop": "url|mime|mediatype|extmetadata",
                "format": "json",
            }, force=force, seen=seen, sink=records, notes=notes, label=category, skip_counts=skip_counts)
        for search in COMMONS_SEARCHES:
            _walk_commons({
                "action": "query",
                "generator": "search",
                "gsrsearch": search,
                "gsrnamespace": "6",
                "gsrlimit": "50",
                "prop": "imageinfo",
                "iiprop": "url|mime|mediatype|extmetadata",
                "format": "json",
            }, force=force, seen=seen, sink=records, notes=notes, label=search, skip_counts=skip_counts)
    except SourceStopped as exc:
        notes.append(exc.note)
    limit = cfg.get("limit")
    stored = 0
    videos = 0
    protected_dropped = 0
    for rec in records:
        if rec.get("geotags_dropped"):
            protected_dropped += 1
        rec["lat"] = None
        rec["lon"] = None
        if limit is not None and stored >= int(limit):
            notes.append(f"media stopped at limit={limit}")
            break
        if store_media(conn, rec, sources):
            stored += 1
            videos += int(rec["kind"] == "video")
        else:
            skip_counts["store_rejected"] += 1
    skip_text = ", ".join(f"{name}={count}" for name, count in sorted(skip_counts.items())) or "none"
    notes.append(
        f"Commons kept={stored} skipped_licence={skip_counts['licence_missing'] + skip_counts['licence_nonfree']} "
        f"skipped_detail[{skip_text}] videos={videos} protected_geotags_dropped={protected_dropped} "
        "(metadata only, no media download; each stored file has licence, licence URL and attribution on its source row)"
    )
    return stored



PARDOK_DOCS = "https://pardok.parlament-berlin.de/portala/opendata.tt.html"
PARDOK_LIST = "https://pardok.parlament-berlin.de/api/v1/drucksache"
PARDOK_TERMS = "https://pardok.parlament-berlin.de/portala/local/OpenData_Nutzungsbedingungen.pdf"
PARDOK_LICENCE = "dl-de/by-2-0"
ELVIS_INDEX = (
    "https://www.parlamentsdokumentation.brandenburg.de/portal/opendata_dokumente.tt.html"
)
ELVIS_EXPORT = "https://www.parlamentsdokumentation.brandenburg.de/opendata/exportWP{wp}.xml"
ELVIS_WPS = tuple(range(1, 9))
ELVIS_STARWEB_INFIX = "/starweb/LBB/ELVIS/parladoku/"
ELVIS_PDF_INFIX = "/parladoku/"


def elvis_pdf_url(lok_url: str | None) -> str | None:
    """Map retired ELVIS /starweb/ LokURLs to the current official /parladoku/ path."""
    url = clean(lok_url)
    if not url:
        return None
    if ELVIS_STARWEB_INFIX in url:
        return url.replace(ELVIS_STARWEB_INFIX, ELVIS_PDF_INFIX, 1)
    return url
HH_RSS = "https://www.buergerschaft-hh.de/parldok/index.rss"
BY_RSS_PAGE = "https://www.bayern.landtag.de/parlament/dokumente/rss-feeds/"
SH_RSS_PAGE = "https://www.landtag.ltsh.de/aktuelles/parlafeed/"
NI_RSS_PAGE = "https://www.landtag-niedersachsen.de/rss-feeds/"
BW_RSS_PAGE = "https://www.landtag-bw.de/de/rss-feed-neue-drucksachen-509930"
BY_RSS_FEEDS = (
    (
        "ANFRAGE",
        "https://www.bayern.landtag.de/webangebot3/views/rssfeed/rssfeed.xhtml"
        "?art=ANFRAGE&titel=Drucksachen+von+Anfragen",
    ),
    (
        "ANTRAG",
        "https://www.bayern.landtag.de/webangebot3/views/rssfeed/rssfeed.xhtml"
        "?art=ANTRAG_EUVORHABEN&titel=Drucksachen+von+Antr%C3%A4gen+und+Europaangelegenheiten",
    ),
    (
        "GESETZ",
        "https://www.bayern.landtag.de/webangebot3/views/rssfeed/rssfeed.xhtml"
        "?art=GESETZ&titel=Drucksachen+von+Gesetzentw%C3%BCrfen",
    ),
)
SH_RSS_FEEDS = (
    (
        "drucksachen",
        "http://lissh.lvn.ltsh.de/shlt/rss/aborss002.xml",
    ),
    (
        "kleine_anfragen",
        "http://lissh.lvn.ltsh.de/shlt/rss/aborss003.xml",
    ),
)

_PARDOK_KEY_RE = re.compile(
    r"API-Key lautet:</div>\s*<div[^>]*>\s*([A-Za-z0-9_\-]{20,})\s*<",
    re.I,
)
_PARDOK_KEY_RE_ALT = re.compile(
    r"API-Key lautet:</div>\s*([A-Za-z0-9_\-]{20,})",
    re.I,
)
_DATE_ISO_RE = re.compile(r"^(\d{4})[.\-](\d{2})[.\-](\d{2})$")
_DATE_DE_RE = re.compile(r"^(\d{2})\.(\d{2})\.(\d{4})$")
_RFC_MONTHS = {
    "Jan": "01", "Feb": "02", "Mar": "03", "Apr": "04", "May": "05", "Jun": "06",
    "Jul": "07", "Aug": "08", "Sep": "09", "Oct": "10", "Nov": "11", "Dec": "12",
}


def published_pardok_key(page_text: str) -> str | None:
    """Read the published Berlin PARDOK key from the official Open Data page HTML."""
    if not page_text:
        return None
    match = _PARDOK_KEY_RE.search(page_text) or _PARDOK_KEY_RE_ALT.search(page_text)
    if match:
        return match.group(1)
    idx = page_text.find("API-Key lautet")
    if idx < 0:
        return None
    after = page_text[idx:idx + 2000]
    match = re.search(r">([A-Za-z0-9_\-]{20,})</", after)
    return match.group(1) if match else None


def normalize_date(value: str | None) -> str | None:
    text = clean(value)
    if not text:
        return None
    match = _DATE_ISO_RE.match(text)
    if match:
        return f"{match.group(1)}-{match.group(2)}-{match.group(3)}"
    match = _DATE_DE_RE.match(text)
    if match:
        return f"{match.group(3)}-{match.group(2)}-{match.group(1)}"
    rfc = re.match(
        r"^[A-Za-z]{3},?\s+(\d{1,2})\s+([A-Za-z]{3})\s+(\d{4})\b",
        text,
    )
    if rfc and rfc.group(2) in _RFC_MONTHS:
        return f"{rfc.group(3)}-{_RFC_MONTHS[rfc.group(2)]}-{int(rfc.group(1)):02d}"
    return text


def pardok_field(value, *keys: str) -> str | None:
    """Unwrap PARDOK/AGH list fields such as [{'main': '...', 't': '...'}]."""
    if value is None:
        return None
    if isinstance(value, str):
        return clean(value)
    items = value if isinstance(value, list) else [value]
    for item in items:
        if isinstance(item, str):
            text = clean(item)
            if text:
                return text
            continue
        if not isinstance(item, dict):
            continue
        for key in keys or ("t", "main"):
            text = clean(item.get(key))
            if text:
                return text
    return None


def pardok_wahlperiode(value) -> int | None:
    text = pardok_field(value, "main")
    if text is None:
        return None
    try:
        return int(text)
    except (TypeError, ValueError):
        return None


def _load_pardok_key() -> tuple[str, str]:
    env = (os.environ.get("PARDOK_API_KEY") or os.environ.get("BERLIN_PARDOK_API_KEY") or "").strip()
    if env:
        return env, "env"
    common._polite_wait()
    response = requests.get(
        PARDOK_DOCS,
        headers={"User-Agent": common.UA, "Accept": "text/html"},
        timeout=60,
    )
    common._log(DOMAIN, PARDOK_DOCS, response.status_code, len(response.content))
    if response.status_code == 403:
        raise SourceStopped("Berlin PARDOK opendata page returned HTTP 403; stopped this source")
    if response.status_code != 200:
        raise SourceStopped(
            f"Berlin PARDOK opendata page returned HTTP {response.status_code}; no key loaded"
        )
    key = published_pardok_key(response.text)
    if not key:
        raise SourceStopped(
            "Berlin PARDOK opendata page did not contain a published API key. "
            f"Unblock via {PARDOK_DOCS}"
        )
    return key, "opendata-page"


def _verify_pdf(url: str | None, *, skip_verify: bool, blocked: list) -> str:
    if not url:
        return "no_url"
    if skip_verify:
        return "unchecked"
    if blocked[0]:
        return "skipped_after_403"
    # Lead, 2026-11-21: an already archived copy with %PDF magic is the verified document; transient 429/503
    # from the host (PARDOK) are retried with backoff instead of silently dropping the paper.
    hit = common.cached_path(DOMAIN, url)
    if hit is not None:
        with hit.open("rb") as handle:
            if handle.read(5) == b"%PDF-":
                return "verified_pdf"
    probed = _probe(url, want_pdf=True)
    for wait in (5, 15, 45):
        if probed["status"] not in (429, 502, 503, 504):
            break
        import time as _time
        _time.sleep(wait)
        probed = _probe(url, want_pdf=True)
    if probed["status"] == 403:
        blocked[0] = True
        return "skipped_after_403"
    return pdf_verdict(probed["status"], probed["content_type"], probed["magic"])


def _catalog_ok(url: str | None, *, skip_verify: bool, blocked: list) -> bool:
    if not url:
        return False
    if skip_verify:
        return True
    if blocked[0]:
        return False
    probed = _probe(url, want_pdf=False)
    if probed["status"] == 403:
        blocked[0] = True
        return False
    return probed["status"] == 200


def _pardok_record(document: dict, *, secret: str, skip_verify: bool, pdf_blocked: list, catalog_blocked: list) -> dict | None:
    raw_id = pardok_field(document.get("id"), "main")
    if not raw_id:
        return None
    titel = pardok_field(document.get("titel"), "t", "main")
    nummer = pardok_field(document.get("dokumentnummer"), "main")
    pdf_url = pardok_field(document.get("pdf_url"), "main")
    if pdf_url and secret and secret in pdf_url:
        pdf_url = None
    pdf_status = _verify_pdf(pdf_url, skip_verify=skip_verify, blocked=pdf_blocked)
    catalog_url = pdf_url
    catalog_ok = False
    if pdf_status == "verified_pdf":
        catalog_ok = True
    elif catalog_url:
        catalog_ok = _catalog_ok(catalog_url, skip_verify=skip_verify, blocked=catalog_blocked)
    urheber = pardok_field(document.get("urheber_koerperschaft"), "main") or pardok_field(
        document.get("urheber"), "main", "t"
    )
    typ = pardok_field(document.get("drucksachentyp"), "main") or pardok_field(
        document.get("dokumentart"), "main"
    )
    return {
        "dip_id": f"BE-PARDOK:{raw_id}",
        "dokumentnummer": nummer,
        "drucksachetyp": typ,
        "wahlperiode": pardok_wahlperiode(document.get("wahlperiode")),
        "herausgeber": "BE",
        "land": "BE",
        "origin": "landtag_pardok",
        "parliament": "Abgeordnetenhaus von Berlin",
        "titel": titel,
        "datum": normalize_date(pardok_field(document.get("datum"), "main") or document.get("datum")),
        "urheber": urheber,
        "pdf_url": pdf_url,
        "pdf_status": pdf_status,
        "catalog_url": catalog_url,
        "catalog_ok": catalog_ok,
        "source_url": catalog_url or f"{PARDOK_LIST}",
        "matched_terms": matched_terms(titel),
    }


def ingest_pardok(conn, cfg, sources, notes) -> int:
    try:
        key, origin = _load_pardok_key()
    except SourceStopped as exc:
        notes.append(_redact(exc.note, None))
        return 0
    notes.append(f"PARDOK key source={origin}")
    stored = 0
    dropped: list[str] = []
    seen_ids = set()
    seen_cursors = set()
    cursor = None
    pages = 0
    statuses = defaultdict(int)
    pdf_blocked = [False]
    catalog_blocked = [False]
    limit = cfg.get("landtag_limit", cfg.get("limit"))
    skip_verify = bool(cfg.get("skip_verify"))
    num_found = None
    while pages < 30:
        params = [("f.titel", term) for term in SEARCH_TERMS]
        params.append(("format", "json"))
        params.append(("limit", "100"))
        if cursor:
            params.append(("cursor", cursor))
        url = PARDOK_LIST + "?" + urllib.parse.urlencode(params, doseq=True)
        if key in url:
            raise RuntimeError("PARDOK key must not be placed in a URL")
        try:
            raw = fetch(
                url,
                domain=DOMAIN,
                force=bool(cfg.get("force")),
                headers={"X-API-Key": key, "Accept": "application/json"},
            )
        except RuntimeError as exc:
            message = _redact(str(exc), key)
            if "HTTP 401" in str(exc) or "HTTP 403" in str(exc):
                notes.append(
                    f"Berlin PARDOK API returned an auth error; stopped this source. Key is published on {PARDOK_DOCS}."
                )
            else:
                notes.append(f"Berlin PARDOK list fetch failed: {message[:240]}")
            break
        payload = json.loads(raw)
        documents = payload.get("documents") or []
        if pages == 0:
            num_found = payload.get("numFound")
            notes.append(f"PARDOK numFound={num_found}")
            if isinstance(num_found, int) and num_found > 5000:
                notes.append("PARDOK numFound above 5000; title filter looks wrong, stopped without storing")
                break
        if not documents:
            break
        fresh = 0
        for document in documents:
            rec = _pardok_record(
                document,
                secret=key,
                skip_verify=skip_verify,
                pdf_blocked=pdf_blocked,
                catalog_blocked=catalog_blocked,
            )
            if not rec or rec["dip_id"] in seen_ids:
                continue
            seen_ids.add(rec["dip_id"])
            fresh += 1
            if limit is not None and stored >= int(limit):
                break
            if store_drucksache(conn, rec, license_=PARDOK_LICENCE, sources=sources):
                stored += 1
                statuses[rec["pdf_status"]] += 1
                if stored % 20 == 0:
                    print(f"PARDOK progress stored={stored}", flush=True)
            else:
                dropped.append(
                    f"{rec.get('dip_id')} {rec.get('dokumentnummer')} "
                    f"pdf_status={rec.get('pdf_status')} catalog_ok={rec.get('catalog_ok')}"
                )
        pages += 1
        new_cursor = payload.get("cursor")
        if limit is not None and stored >= int(limit):
            notes.append(f"PARDOK stopped at limit={limit}")
            break
        if not new_cursor or new_cursor == cursor or new_cursor in seen_cursors or fresh == 0:
            break
        seen_cursors.add(new_cursor)
        cursor = new_cursor
    if pdf_blocked[0]:
        notes.append("Berlin PARDOK PDF host returned HTTP 403; remaining PDF checks were skipped")
    if catalog_blocked[0]:
        notes.append("Berlin PARDOK catalog host returned HTTP 403; remaining catalog checks were skipped")
    status_text = ", ".join(f"{name}={count}" for name, count in sorted(statuses.items()))
    notes.append(f"PARDOK stored={stored} pages={pages} pdf[{status_text}]")
    if dropped:
        notes.append(f"PARDOK not stored ({len(dropped)}): " + "; ".join(dropped))
    return stored


def _elvis_text(el, tag: str) -> str | None:
    child = el.find(tag)
    if child is None or child.text is None:
        return None
    return clean(child.text)


def _elvis_record(doc_el, vorgang_el, *, skip_verify: bool, pdf_blocked: list, catalog_blocked: list) -> dict | None:
    titel = _elvis_text(doc_el, "Titel")
    if not matched_terms(titel):
        return None
    vnr = _elvis_text(vorgang_el, "VNr") or "unknown"
    reih = _elvis_text(doc_el, "ReihNr") or "0000"
    wp = _elvis_text(doc_el, "Wp")
    nummer = _elvis_text(doc_el, "DokNr") or _elvis_text(doc_el, "NrInTyp")
    typ = (
        _elvis_text(doc_el, "DokTypL")
        or _elvis_text(doc_el, "DokArtL")
        or _elvis_text(doc_el, "DokTyp")
    )
    pdf_url = elvis_pdf_url(_elvis_text(doc_el, "LokURL"))
    pdf_status = _verify_pdf(pdf_url, skip_verify=skip_verify, blocked=pdf_blocked)
    catalog_ok = False
    if pdf_status == "verified_pdf":
        catalog_ok = True
    elif pdf_url:
        catalog_ok = _catalog_ok(pdf_url, skip_verify=skip_verify, blocked=catalog_blocked)
    wahlperiode = None
    if wp:
        try:
            wahlperiode = int(wp)
        except (TypeError, ValueError):
            wahlperiode = None
    return {
        "dip_id": f"BB-ELVIS:{vnr}:{reih}",
        "dokumentnummer": nummer,
        "drucksachetyp": typ,
        "wahlperiode": wahlperiode,
        "herausgeber": "BB",
        "land": "BB",
        "origin": "landtag_elvis",
        "parliament": "Landtag Brandenburg",
        "titel": titel,
        "datum": normalize_date(_elvis_text(doc_el, "DokDat")),
        "urheber": _elvis_text(doc_el, "Urheber"),
        "pdf_url": pdf_url,
        "pdf_status": pdf_status,
        "catalog_url": pdf_url,
        "catalog_ok": catalog_ok,
        "source_url": pdf_url or ELVIS_INDEX,
        "matched_terms": matched_terms(titel),
    }


def _iter_elvis_documents(xml_bytes: bytes):
    # Official export declares a Parlamentsspiegel DTD; strip it so the parser
    # does not try to resolve a network document type.
    text = xml_bytes if isinstance(xml_bytes, (bytes, bytearray)) else str(xml_bytes).encode("utf-8")
    if text.startswith(b"\xef\xbb\xbf"):
        text = text[3:]
    stripped = re.sub(br"<!DOCTYPE[^>]*>", b"", text, count=1)
    root = ET.fromstring(stripped)
    for vorgang in root.findall("Vorgang"):
        if _elvis_text(vorgang, "VFunktion") == "delete":
            continue
        for doc in vorgang.findall("Dokument"):
            yield doc, vorgang


def ingest_elvis(conn, cfg, sources, notes) -> int:
    stored = 0
    statuses = defaultdict(int)
    per_wp = {}
    pdf_blocked = [False]
    catalog_blocked = [False]
    skip_verify = bool(cfg.get("skip_verify"))
    limit = cfg.get("landtag_limit", cfg.get("limit"))
    for wp in ELVIS_WPS:
        url = ELVIS_EXPORT.format(wp=wp)
        try:
            raw = fetch(url, domain=DOMAIN, force=bool(cfg.get("force")))
        except RuntimeError as exc:
            notes.append(f"Brandenburg ELVIS WP{wp} fetch failed: {str(exc)[:200]}")
            per_wp[wp] = 0
            continue
        kept = 0
        try:
            pairs = list(_iter_elvis_documents(raw if isinstance(raw, (bytes, bytearray)) else raw.encode("utf-8")))
        except ET.ParseError as exc:
            notes.append(f"Brandenburg ELVIS WP{wp} XML parse failed: {exc}")
            per_wp[wp] = 0
            continue
        for doc_el, vorgang_el in pairs:
            if limit is not None and stored >= int(limit):
                break
            titel = _elvis_text(doc_el, "Titel")
            if not matched_terms(titel):
                continue
            rec = _elvis_record(
                doc_el,
                vorgang_el,
                skip_verify=skip_verify,
                pdf_blocked=[False],
                catalog_blocked=[False],
            )
            if not rec:
                continue
            kept += 1
            statuses[rec["pdf_status"]] += 1
            if store_drucksache(conn, rec, license_=None, sources=sources):
                stored += 1
        per_wp[wp] = kept
        if limit is not None and stored >= int(limit):
            notes.append(f"ELVIS stopped at limit={limit}")
            break
    status_text = ", ".join(f"{name}={count}" for name, count in sorted(statuses.items())) or "none"
    wp_text = ", ".join(f"wp{wp}={per_wp[wp]}" for wp in sorted(per_wp))
    notes.append(
        f"ELVIS title_matches={sum(per_wp.values())} stored={stored} ({wp_text}) pdf[{status_text}]"
    )
    if stored == 0 and sum(per_wp.values()) > 0:
        notes.append(
            "Brandenburg ELVIS official PDF URLs returned no HTTP 200/206 PDF "
            "from this environment, so no BB rows were stored. Matches are listed in the research note."
        )
    elif stored:
        notes.append(
            "Brandenburg ELVIS PDF URLs are mapped from retired "
            "/starweb/LBB/ELVIS/parladoku/ LokURL paths to the current official /parladoku/ path."
        )
    return stored


def _rss_text(el) -> str | None:
    if el is None or el.text is None:
        return None
    return text_content(el.text)


def parse_rss_items(xml_bytes: bytes) -> list[dict]:
    text = xml_bytes if isinstance(xml_bytes, (bytes, bytearray)) else str(xml_bytes).encode("utf-8")
    if text.startswith(b"\xef\xbb\xbf"):
        text = text[3:]
    # RSS is XML; reject HTML error pages.
    head = text.lstrip()[:80].lower()
    if head.startswith(b"<html") or head.startswith(b"<!doctype html"):
        raise ValueError("response is HTML, not RSS")
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        stripped = re.sub(br"<!DOCTYPE[^>]*>", b"", text, count=1)
        root = ET.fromstring(stripped)
    items = []
    # Handle default-namespace RSS by ignoring namespaces in tag names.
    for item in root.iter():
        tag = item.tag.split("}")[-1].lower() if isinstance(item.tag, str) else ""
        if tag != "item":
            continue
        fields = {}
        for child in list(item):
            name = child.tag.split("}")[-1].lower() if isinstance(child.tag, str) else ""
            if name in {"title", "link", "description", "pubdate", "guid"}:
                fields[name] = _rss_text(child)
            if name == "enclosure":
                fields["enclosure"] = child.attrib.get("url")
        items.append(fields)
    return items


def _rss_subject(item: dict) -> tuple[str | None, str | None, str | None]:
    """Return (title, dokumentnummer, typ) from an official Landtag RSS item.

    Bayern titles are often just 'Initiativdrucksache 19/13306'; the subject is
    in the description. Prefer the subject as the stored title.
    """
    raw_title = clean(item.get("title"))
    desc = clean(item.get("description"))
    nummer = None
    typ = None
    if raw_title:
        match = re.match(r"^(Initiativdrucksache|Drucksache)\s+(\d+/\d+)\s*$", raw_title, re.I)
        if match:
            typ = match.group(1)
            nummer = match.group(2)
            return desc or raw_title, nummer, typ
        match = re.search(r"(\d+/\d+)", raw_title)
        if match:
            nummer = match.group(1)
    return raw_title or desc, nummer, typ



def _rss_doc_id(land: str, ident: str) -> str:
    match = re.search(r"gegenstandid=(\d+)", ident or "", re.I)
    if match:
        return f"{land}-RSS:{match.group(1)}"
    digest = hashlib.sha1((ident or "").encode("utf-8")).hexdigest()
    return f"{land}-RSS:{digest}"


def ingest_official_rss(conn, cfg, sources, notes, *, land: str, parliament: str, typ: str, url: str,
                        errors=None) -> int:
    skip_verify = bool(cfg.get("skip_verify"))
    limit = cfg.get("landtag_limit", cfg.get("limit"))
    pdf_blocked = [False]
    catalog_blocked = [False]
    try:
        raw = fetch(
            url,
            domain=DOMAIN,
            force=bool(cfg.get("force")),
            headers={"Accept": "application/rss+xml, application/xml, text/xml, */*"},
        )
    except RuntimeError as exc:
        message = f"{land} RSS {typ} fetch failed: {str(exc)[:200]}"
        notes.append(message)
        if errors is not None:
            errors.append(message)
        return 0
    payload = raw if isinstance(raw, (bytes, bytearray)) else raw.encode("utf-8")
    try:
        items = parse_rss_items(payload)
    except (ET.ParseError, ValueError) as exc:
        message = f"{land} RSS {typ} is not usable RSS ({exc})"
        notes.append(message)
        if errors is not None:
            errors.append(message)
        return 0
    stored = 0
    seen = set()
    statuses = defaultdict(int)
    for item in items:
        if limit is not None and stored >= int(limit):
            notes.append(f"{land} RSS {typ} stopped at limit={limit}")
            break
        titel, nummer, doc_typ = _rss_subject(item)
        terms = matched_terms(titel, item.get("description"), item.get("title"))
        if not terms:
            continue
        link = clean(item.get("link"))
        pdf_url = clean(item.get("enclosure"))
        if not link and not pdf_url:
            continue
        ident = link or pdf_url
        if ident in seen:
            continue
        seen.add(ident)
        pdf_status = _verify_pdf(pdf_url, skip_verify=skip_verify, blocked=pdf_blocked)
        catalog_url = link or pdf_url
        catalog_ok = _catalog_ok(catalog_url, skip_verify=skip_verify, blocked=catalog_blocked)
        if not catalog_ok and pdf_status == "verified_pdf":
            catalog_url = pdf_url
            catalog_ok = True
        rec = {
            "dip_id": _rss_doc_id(land, ident),
            "dokumentnummer": nummer,
            "drucksachetyp": doc_typ or typ,
            "wahlperiode": None,
            "herausgeber": land,
            "land": land,
            "origin": "landtag_rss",
            "parliament": parliament,
            "titel": titel,
            "datum": normalize_date(item.get("pubdate")),
            "urheber": None,
            "pdf_url": pdf_url,
            "pdf_status": pdf_status if pdf_url else "no_url",
            "catalog_url": catalog_url,
            "catalog_ok": catalog_ok,
            "source_url": catalog_url,
            "matched_terms": terms,
        }
        if store_drucksache(conn, rec, license_=None, sources=sources):
            stored += 1
            statuses[rec["pdf_status"]] += 1
    status_text = ", ".join(f"{name}={count}" for name, count in sorted(statuses.items())) or "none"
    notes.append(
        f"{land} RSS {typ} items={len(items)} stored={stored} pdf[{status_text}] (recent official feed, not a full archive)"
    )
    return stored


LANDTAG_GAPS = (
    "NW: Landtag NRW Parlamentsdatenbank is a public HTML search (sometimes called OPAL); no official REST or XML export was found.",
    "HE, RP, TH, HB, ST, SL: no official machine-readable parliament documentation API or bulk export was found; several run newsletter or HTML-only search services.",
    "HH is ingested only from the official ParlDok index.rss (recent items, not the archive).",
    "BY is ingested only from the official webangebot3 RSS feeds linked from the Landtag RSS page (recent window, not the archive).",
    "BB and BE have official full-export or API access and are ingested from those official sources.",
    "SN: the official EDAS HTML search is public; no official public API documentation for a JSON/XML interface was found, so Sachsen is a gap this pass.",
    "MV: the official site offers account-based document alerts, not a documented public RSS or API, so Mecklenburg-Vorpommern is a gap this pass.",
    "BW: the official 'RSS Feed - Neue Drucksachen' page returns HTML only; no machine-readable feed URL was advertised on that page.",
    "NI: the official RSS-Feeds page was in maintenance when checked, so Niedersachsen is unverified this pass.",
    "SH: official ParlaFeed RSS URLs on the Landtag site are ingested when they return RSS; coverage is the recent window only, not the archive.",
)


def ingest_landtag(conn, cfg, sources, notes, errors=None) -> dict:
    counts = {"BE": 0, "BB": 0, "BY": 0, "HH": 0, "SH": 0}
    errors = errors if errors is not None else []
    try:
        counts["BE"] = ingest_pardok(conn, cfg, sources, notes)
    except Exception as exc:
        message = f"Berlin PARDOK failed: {type(exc).__name__}: {_redact(str(exc), None)[:200]}"
        notes.append(message)
        errors.append(message)
    try:
        counts["BB"] = ingest_elvis(conn, cfg, sources, notes)
    except Exception as exc:
        message = f"Brandenburg ELVIS failed: {type(exc).__name__}: {str(exc)[:200]}"
        notes.append(message)
        errors.append(message)
    try:
        by_total = 0
        for typ, url in BY_RSS_FEEDS:
            by_total += ingest_official_rss(
                conn, cfg, sources, notes,
                land="BY",
                parliament="Bayerischer Landtag",
                typ=typ,
                url=url,
                errors=errors,
            )
        counts["BY"] = by_total
    except Exception as exc:
        message = f"Bayern RSS failed: {type(exc).__name__}: {str(exc)[:200]}"
        notes.append(message)
        errors.append(message)
    try:
        counts["HH"] = ingest_official_rss(
            conn, cfg, sources, notes,
            land="HH",
            parliament="Bürgerschaft der Freien und Hansestadt Hamburg",
            typ="parldok",
            url=HH_RSS,
            errors=errors,
        )
    except Exception as exc:
        message = f"Hamburg RSS failed: {type(exc).__name__}: {str(exc)[:200]}"
        notes.append(message)
        errors.append(message)
    try:
        sh_total = 0
        for typ, url in SH_RSS_FEEDS:
            sh_total += ingest_official_rss(
                conn, cfg, sources, notes,
                land="SH",
                parliament="Schleswig-Holsteinischer Landtag",
                typ=typ,
                url=url,
                errors=errors,
            )
        counts["SH"] = sh_total
    except Exception as exc:
        message = f"Schleswig-Holstein RSS failed: {type(exc).__name__}: {str(exc)[:200]}"
        notes.append(message)
        errors.append(message)
    notes.append("Landtag gaps: " + " ".join(LANDTAG_GAPS))
    notes.append(
        "Landtag counts: "
        + ", ".join(f"{land}={counts[land]}" for land in ("BE", "BB", "BY", "HH", "SH"))
    )
    notes.append(
        f"landtag_feed_errors={len(errors)}"
        + (": " + "; ".join(errors) if errors else "")
    )
    return counts


def run(conn, cfg) -> dict:
    """Ingest DIP and Landtag papers, Rechnungshof audits, Wikidata facilities and Commons media. No atlas.db."""
    cfg = cfg or {}
    ensure_tables(conn)
    notes: list[str] = []
    run_errors: list[str] = []
    sources: list[tuple] = []
    skip = {str(item) for item in (cfg.get("skip") or [])}
    if cfg.get("fixture"):
        _OFFLINE[0] = True
        try:
            counts = _ingest_fixture(conn, cfg["fixture"], sources, notes)
        finally:
            _OFFLINE[0] = False
        rows = counts["docs"] + counts["facilities"] + counts["media"] + counts.get("audits", 0)
        return {"rows": rows, "notes": " | ".join(notes), "sources": _unique_sources(sources)}
    docs = facilities = media = landtag = audits = orgs = shelters = investigations = 0
    if "dip" not in skip:
        try:
            docs = ingest_dip(conn, cfg, sources, notes)
        except Exception as exc:
            raise RuntimeError(f"DIP failed: {type(exc).__name__}: {str(exc)[:200]}") from exc
    if "facilities" not in skip:
        try:
            facilities = ingest_facilities(conn, cfg, sources, notes)
        except Exception as exc:
            raise RuntimeError(f"Wikidata facilities failed: {type(exc).__name__}: {str(exc)[:200]}") from exc
    if "media" not in skip:
        try:
            media = ingest_media(conn, cfg, sources, notes)
        except Exception as exc:
            raise RuntimeError(f"Commons failed: {type(exc).__name__}: {str(exc)[:200]}") from exc
    if "landtag" not in skip:
        try:
            per_land = ingest_landtag(conn, cfg, sources, notes, errors=run_errors)
            landtag = sum(per_land.values())
        except Exception as exc:
            raise RuntimeError(f"Landtag failed: {type(exc).__name__}: {_redact(str(exc), None)[:200]}") from exc
    if "rechnungshof" not in skip:
        try:
            from ingest.domains.institutions_media_rechnungshof import ingest_rechnungshof
            audits = ingest_rechnungshof(conn, cfg, sources, notes)
        except Exception as exc:
            raise RuntimeError(f"Rechnungshof failed: {type(exc).__name__}: {str(exc)[:200]}") from exc
    if "orgs" not in skip:
        try:
            from ingest.domains.institutions_media_orgs import ingest_orgs
            orgs = ingest_orgs(conn, cfg, sources, notes)
        except Exception as exc:
            raise RuntimeError(f"Organisations failed: {type(exc).__name__}: {str(exc)[:200]}") from exc
    if "shelters" not in skip:
        try:
            from ingest.domains.institutions_media_shelters import ingest_shelters
            shelters = ingest_shelters(conn, cfg, sources, notes)
        except Exception as exc:
            raise RuntimeError(f"Shelters failed: {type(exc).__name__}: {str(exc)[:200]}") from exc
    if "investigations" not in skip:
        try:
            from ingest.domains.institutions_media_investigations import ingest_investigations
            investigations = ingest_investigations(conn, cfg, sources, notes)
        except Exception as exc:
            raise RuntimeError(f"Investigations failed: {type(exc).__name__}: {str(exc)[:200]}") from exc
    drogentote = 0
    if "drogentote" not in skip:
        try:
            from ingest.domains.institutions_media_drogentote import ingest_drogentote
            drogentote = ingest_drogentote(conn, cfg, sources, notes)
        except Exception as exc:
            raise RuntimeError(f"Drogentote failed: {type(exc).__name__}: {str(exc)[:200]}") from exc
    pks = 0
    if "pks" not in skip:
        try:
            from ingest.domains.institutions_media_pks import ingest_pks
            pks = ingest_pks(conn, cfg, sources, notes)
        except Exception as exc:
            raise RuntimeError(f"PKS failed: {type(exc).__name__}: {str(exc)[:200]}") from exc
    jva_psych = 0
    if "jva_psych" not in skip:
        try:
            from ingest.domains.institutions_media_jva_psych import ingest_jva_psych
            jva_psych = ingest_jva_psych(conn, cfg, sources, notes)
        except Exception as exc:
            raise RuntimeError(f"JVA/psych failed: {type(exc).__name__}: {str(exc)[:200]}") from exc
    studies = 0
    if "studies" not in skip:
        try:
            from ingest.domains.institutions_media_studies import ingest_studies
            studies = ingest_studies(conn, cfg, sources, notes)
        except Exception as exc:
            raise RuntimeError(f"Studies failed: {type(exc).__name__}: {str(exc)[:200]}") from exc
    prison_costs = 0
    if "prison_costs" not in skip:
        try:
            from ingest.domains.institutions_media_prison_costs import ingest_prison_costs
            prison_costs = ingest_prison_costs(conn, cfg, sources, notes)
        except Exception as exc:
            raise RuntimeError(f"Prison costs failed: {type(exc).__name__}: {str(exc)[:200]}") from exc
    hospital_plans = 0
    if "hospital_plans" not in skip:
        try:
            from ingest.domains.institutions_media_hospital_plans import ingest_hospital_plans
            hospital_plans = ingest_hospital_plans(conn, cfg, sources, notes)
        except Exception as exc:
            raise RuntimeError(f"Hospital plans failed: {type(exc).__name__}: {str(exc)[:200]}") from exc
    shelter_costs = 0
    if "shelter_costs" not in skip:
        try:
            from ingest.domains.institutions_media_shelter_costs import ingest_shelter_costs
            shelter_costs = ingest_shelter_costs(conn, cfg, sources, notes)
        except Exception as exc:
            raise RuntimeError(f"Shelter costs failed: {type(exc).__name__}: {str(exc)[:200]}") from exc
    manual_archive = 0
    if "manual_archive" not in skip:
        try:
            from ingest.domains.institutions_media_manual_archive import ingest_manual_archive
            ma = ingest_manual_archive(conn, cfg, sources, notes)
            manual_archive = (ma.get("shelters") or 0) + (ma.get("metrics") or 0)
        except Exception as exc:
            raise RuntimeError(f"Manual archive failed: {type(exc).__name__}: {str(exc)[:200]}") from exc
    press_media = 0
    if "press" not in skip:
        try:
            from ingest.domains.institutions_media_press import ingest_press
            press_media = ingest_press(conn, cfg, sources, notes)
        except Exception as exc:
            raise RuntimeError(f"Press media failed: {type(exc).__name__}: {str(exc)[:200]}") from exc
    officers = 0
    if "officers" not in skip:
        try:
            from ingest.domains.institutions_media_officers import ingest_officers
            officers = ingest_officers(conn, cfg, sources, notes)
        except Exception as exc:
            raise RuntimeError(f"Officers ingest failed: {type(exc).__name__}: {str(exc)[:200]}") from exc
    notes.append(
        "Court decisions are out of scope for this domain (Counts & Law). "
        "No EUR facility budget or annual cost per bed was stored on facility rows."
    )
    rows = docs + facilities + media + landtag + audits + orgs + shelters + investigations + drogentote + pks + jva_psych + studies + prison_costs + hospital_plans + shelter_costs + manual_archive + press_media + officers
    notes.append(
        f"doc={docs} landtag={landtag} facility={facilities} media={media} "
        f"drucksache={docs + landtag} audit={audits} org={orgs} shelter={shelters} "
        f"investigation={investigations} drogentote={drogentote} pks={pks} jva_psych={jva_psych} "
        f"study={studies} prison_costs={prison_costs} hospital_plans={hospital_plans} shelter_costs={shelter_costs} manual_archive={manual_archive} press_media={press_media} officers={officers}"
    )
    if run_errors:
        notes.append(f"errors={len(run_errors)}")
    return {
        "rows": rows,
        "notes": " | ".join(notes),
        "sources": _unique_sources(sources),
        "errors": list(run_errors),
    }


def _unique_sources(sources: list[tuple]) -> list[tuple]:
    seen = set()
    out = []
    for url, license_ in sources:
        if url in seen:
            continue
        seen.add(url)
        out.append((url, license_))
    return out


def _load_schema(conn) -> None:
    conn.executescript((ROOT / "ingest" / "schema.sql").read_text(encoding="utf-8"))
    ensure_tables(conn)


def _print_counts(conn) -> None:
    for table in ("doc", "facility", "media", "institutions_media_drucksache",
                  "institutions_media_facility", "institutions_media_audit", "institutions_media_org", "institutions_media_shelter", "institutions_media_investigation", "institutions_media_study", "org", "metric", "source"):
        try:
            count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        except sqlite3.OperationalError:
            count = 0
        print(f"{table}: {count}")
    money = conn.execute(
        "SELECT COUNT(*) FROM facility WHERE haushalt_eur IS NOT NULL OR kosten_je_platz_eur IS NOT NULL"
    ).fetchone()[0]
    protected = conn.execute(
        """SELECT COUNT(*) FROM facility
           WHERE kind IN ('frauenhaus', 'schutzwohnung', 'protected_shelter')
             AND (anschrift IS NOT NULL OR plz IS NOT NULL OR lat IS NOT NULL OR lon IS NOT NULL OR kreis_ags IS NOT NULL)"""
    ).fetchone()[0]
    print(f"facility_money_rows: {money}")
    print(f"protected_with_location: {protected}")
    try:
        restricted_street = conn.execute(
            """SELECT COUNT(*) FROM institutions_media_shelter s
               JOIN facility f ON f.id=s.facility_id
               WHERE s.location_precision='district'
                 AND (f.anschrift IS NOT NULL OR f.plz IS NOT NULL
                      OR f.lat IS NOT NULL OR f.lon IS NOT NULL)"""
        ).fetchone()[0]
        restricted_district = conn.execute(
            "SELECT COUNT(*) FROM institutions_media_shelter WHERE location_precision='district'"
        ).fetchone()[0]
    except sqlite3.OperationalError:
        restricted_street = restricted_district = 0
    print(f"restricted_group_district_only: {restricted_district}")
    print(f"restricted_group_with_street: {restricted_street}")
    try:
        land_ags = conn.execute(
            "SELECT COUNT(*) FROM metric WHERE entity_type='land' AND length(entity_id)=2 AND entity_id GLOB '[01][0-9]'"
        ).fetchone()[0]
        land_letter = conn.execute(
            "SELECT COUNT(*) FROM metric WHERE entity_type='land' AND entity_id GLOB '[A-Z][A-Z]'"
        ).fetchone()[0]
        fac_ags = conn.execute("SELECT COUNT(*) FROM facility WHERE kreis_ags IS NOT NULL").fetchone()[0]
        fac_n = conn.execute("SELECT COUNT(*) FROM facility").fetchone()[0]
        org_ags = conn.execute("SELECT COUNT(*) FROM org WHERE kreis_ags IS NOT NULL").fetchone()[0]
        org_n = conn.execute("SELECT COUNT(*) FROM org").fetchone()[0]
        sh_ags = conn.execute(
            """SELECT COUNT(*) FROM institutions_media_shelter s
               JOIN facility f ON f.id=s.facility_id WHERE f.kreis_ags IS NOT NULL"""
        ).fetchone()[0]
        sh_n = conn.execute("SELECT COUNT(*) FROM institutions_media_shelter").fetchone()[0]
    except Exception:
        land_ags = land_letter = fac_ags = fac_n = org_ags = org_n = sh_ags = sh_n = 0
    print(f"metric_land_ags: {land_ags}")
    print(f"metric_land_letter: {land_letter}")
    print(f"facility_kreis_ags: {fac_ags}/{fac_n}")
    print(f"org_kreis_ags: {org_ags}/{org_n}")
    print(f"shelter_kreis_ags: {sh_ags}/{sh_n}")
    null_lic = conn.execute(
        "SELECT COUNT(*) FROM source WHERE license IS NULL OR trim(license) = ''"
    ).fetchone()[0]
    print(f"source_null_licence: {null_lic}")
    todo_lic = conn.execute(
        "SELECT COUNT(*) FROM source WHERE license LIKE 'TODO:%'"
    ).fetchone()[0]
    print(f"source_todo_licence: {todo_lic}")
    for row in conn.execute(
        "SELECT coalesce(license, 'NULL') AS license, COUNT(*) AS n FROM source GROUP BY 1 ORDER BY n DESC"
    ):
        print(f"source_licence {row['n']}\t{row['license']}")
    try:
        rows = conn.execute(
            """SELECT coalesce(land, '?') AS land, coalesce(origin, '?') AS origin, COUNT(*) AS n
               FROM institutions_media_drucksache
               GROUP BY 1, 2
               ORDER BY 1, 2"""
        ).fetchall()
    except sqlite3.OperationalError:
        rows = []
    for row in rows:
        print(f"drucksache_by_land_origin {row['land']} {row['origin']}: {row['n']}")
    try:
        arows = conn.execute(
            """SELECT coalesce(court_id, '?') AS court_id, coalesce(land, '?') AS land,
                      coalesce(report_kind, '?') AS report_kind, COUNT(*) AS n
               FROM institutions_media_audit
               GROUP BY 1, 2, 3
               ORDER BY 1, 3"""
        ).fetchall()
    except sqlite3.OperationalError:
        arows = []
    for row in arows:
        print(f"audit_by_court {row['court_id']} {row['land']} {row['report_kind']}: {row['n']}")
    try:
        mrows = conn.execute(
            """SELECT entity_type, entity_id, metric, year, value, einheit, locator
               FROM metric ORDER BY entity_id, metric, year"""
        ).fetchall()
    except sqlite3.OperationalError:
        mrows = []
    for row in mrows:
        print(
            f"metric {row['entity_type']}:{row['entity_id']} {row['metric']} {row['year']} "
            f"= {row['value']} {row['einheit']} ({row['locator']})"
        )


def _print_samples(conn, n=3) -> None:
    printed = 0
    for table in ("doc", "facility", "media"):
        rows = conn.execute(f"SELECT * FROM {table} LIMIT ?", (n,)).fetchall()
        for row in rows:
            if printed >= n:
                return
            print(dict(row))
            printed += 1


def selftest() -> int:
    atlas = ROOT / "data" / "atlas.db"
    before = atlas.exists()
    fixture = ROOT / "tests" / "fixture_institutions_media.json"
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    _load_schema(conn)
    cfg = {"fixture": str(fixture)} if fixture.exists() else {"limit": 2, "skip_verify": True}
    if not fixture.exists():
        print("fixture missing; selftest uses a tiny live limit")
    tables = ("doc", "facility", "media", "institutions_media_drucksache",
              "institutions_media_facility", "institutions_media_audit")

    def counts():
        return tuple(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in tables)

    first = run(conn, cfg)
    conn.commit()
    after_first = counts()
    second = run(conn, cfg)
    conn.commit()
    print(first["notes"])
    _print_counts(conn)
    _print_samples(conn, 3)
    if first["rows"] != second["rows"] or after_first != counts():
        print("idempotent: no", after_first, counts())
        return 1
    money = conn.execute(
        "SELECT COUNT(*) FROM facility WHERE haushalt_eur IS NOT NULL OR kosten_je_platz_eur IS NOT NULL"
    ).fetchone()[0]
    protected = conn.execute(
        """SELECT COUNT(*) FROM facility
           WHERE kind IN ('frauenhaus', 'schutzwohnung', 'protected_shelter')
             AND (anschrift IS NOT NULL OR plz IS NOT NULL OR lat IS NOT NULL OR lon IS NOT NULL OR kreis_ags IS NOT NULL)"""
    ).fetchone()[0]
    if money or protected:
        print("protected or money check failed", money, protected)
        return 1
    null_lic = conn.execute(
        "SELECT COUNT(*) FROM source WHERE license IS NULL OR trim(license) = ''"
    ).fetchone()[0]
    if null_lic:
        print("null licence sources:", null_lic)
        return 1
    print("idempotent: yes")
    if atlas.exists() and not before:
        print("atlas.db was created")
        return 1
    print("atlas.db created: no")
    return 0


def dry_run(*, skip=None) -> int:
    atlas = ROOT / "data" / "atlas.db"
    before = atlas.exists()
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    _load_schema(conn)
    cfg = {}
    if skip:
        cfg["skip"] = list(skip)
    result = run(conn, cfg)
    conn.commit()
    print(result["notes"])
    _print_counts(conn)
    _print_samples(conn, 3)
    print("--- verify candidates ---")
    for label, sql in (
        ("pdf", """SELECT d.dip_id, d.dokumentnummer, d.drucksachetyp, d.datum, d.titel,
                          d.pdf_status, d.pdf_url, d.catalog_url, d.herausgeber
                   FROM institutions_media_drucksache d
                   WHERE d.pdf_status='verified_pdf' LIMIT 1"""),
        ("no_pdf", """SELECT d.dip_id, d.dokumentnummer, d.drucksachetyp, d.datum, d.titel,
                             d.pdf_status, d.pdf_url, d.catalog_url
                      FROM institutions_media_drucksache d
                      WHERE d.pdf_status='unavailable' LIMIT 1"""),
        ("beds", """SELECT f.name, f.kind, f.land, f.ort, f.betten, f.betriebsstatus, f.eroeffnet,
                           f.anschrift, x.qid
                    FROM facility f
                    JOIN institutions_media_facility x ON x.facility_id=f.id
                    WHERE f.betten IS NOT NULL LIMIT 1"""),
        ("prison", """SELECT f.name, f.kind, f.land, f.ort, f.betriebsstatus, f.geschlossen, x.qid
                      FROM facility f
                      JOIN institutions_media_facility x ON x.facility_id=f.id
                      WHERE f.kind='prison' AND f.land IS NOT NULL LIMIT 1"""),
        ("media", """SELECT title, url, lizenz, kind, herausgeber FROM media LIMIT 1"""),
        ("landtag", """SELECT d.dip_id, d.land, d.origin, d.dokumentnummer, d.drucksachetyp,
                              d.datum, d.titel, d.pdf_status, d.pdf_url, d.catalog_url
                       FROM institutions_media_drucksache d
                       WHERE d.origin IS NOT NULL AND d.origin != 'bundestag_dip'
                       LIMIT 1"""),
        ("audit", """SELECT report_id, court_id, land, report_kind, title, chapter,
                            pdf_status, pdf_url, locator
                     FROM institutions_media_audit LIMIT 1"""),
        ("audit_metric", """SELECT entity_type, entity_id, metric, year, value, einheit,
                                   locator, quote
                            FROM metric LIMIT 1"""),
    ):
        row = conn.execute(sql).fetchone()
        print(label, dict(row) if row else None)
    if atlas.exists() and not before:
        print("atlas.db was created")
        return 1
    return 0


_DRY_ONLY = {
    "landtag": ["dip", "facilities", "media", "rechnungshof", "orgs", "shelters", "investigations", "drogentote", "pks", "jva_psych", "studies", "prison_costs", "hospital_plans", "shelter_costs", "lags", "manual_archive", "press", "officers"],
    "rechnungshof": ["dip", "facilities", "media", "landtag", "orgs", "shelters", "investigations", "drogentote", "pks", "jva_psych", "studies", "prison_costs", "hospital_plans", "shelter_costs", "lags", "manual_archive", "press", "officers"],
    "jobcenter": ["dip", "facilities", "media", "landtag", "rechnungshof", "umbrellas", "shelters", "investigations", "drogentote", "pks", "jva_psych", "studies", "prison_costs", "hospital_plans", "shelter_costs", "lags", "manual_archive", "press", "officers"],
    "umbrellas": ["dip", "facilities", "media", "landtag", "rechnungshof", "jobcenter", "shelters", "investigations", "drogentote", "pks", "jva_psych", "studies", "prison_costs", "hospital_plans", "shelter_costs", "lags", "manual_archive", "press", "officers"],
    "shelters": ["dip", "facilities", "media", "landtag", "rechnungshof", "orgs", "investigations", "drogentote", "pks", "jva_psych", "studies", "prison_costs", "hospital_plans", "shelter_costs", "lags", "manual_archive", "press", "officers"],
    "investigations": ["dip", "facilities", "media", "landtag", "rechnungshof", "orgs", "shelters", "drogentote", "pks", "jva_psych", "studies", "prison_costs", "hospital_plans", "shelter_costs", "lags", "manual_archive", "press", "officers"],
    "drogentote": ["dip", "facilities", "media", "landtag", "rechnungshof", "orgs", "shelters", "investigations", "pks", "jva_psych", "studies", "prison_costs", "hospital_plans", "shelter_costs", "lags", "manual_archive", "press", "officers"],
    "pks": ["dip", "facilities", "media", "landtag", "rechnungshof", "orgs", "shelters", "investigations", "drogentote", "jva_psych", "studies", "prison_costs", "hospital_plans", "shelter_costs", "lags", "manual_archive", "press", "officers"],
    "jva-psych": ["dip", "facilities", "media", "landtag", "rechnungshof", "orgs", "shelters", "investigations", "drogentote", "pks", "studies", "prison_costs", "hospital_plans", "shelter_costs", "lags", "manual_archive", "press", "officers"],
    "studies": ["dip", "facilities", "media", "landtag", "rechnungshof", "orgs", "shelters", "investigations", "drogentote", "pks", "jva_psych", "prison_costs", "hospital_plans", "shelter_costs", "lags", "manual_archive", "press", "officers"],
    "prison-costs": ["dip", "facilities", "media", "landtag", "rechnungshof", "orgs", "shelters", "investigations", "drogentote", "pks", "jva_psych", "studies", "hospital_plans", "shelter_costs", "lags", "manual_archive", "press", "officers"],
    "hospital-plans": ["dip", "facilities", "media", "landtag", "rechnungshof", "orgs", "shelters", "investigations", "drogentote", "pks", "jva_psych", "studies", "prison_costs", "shelter_costs", "lags", "manual_archive", "press", "officers"],
    "shelter-costs": ["dip", "facilities", "media", "landtag", "rechnungshof", "orgs", "shelters", "investigations", "drogentote", "pks", "jva_psych", "studies", "prison_costs", "hospital_plans", "lags", "manual_archive", "press", "officers"],
    "lags": ["dip", "facilities", "media", "landtag", "rechnungshof", "jobcenter", "umbrellas", "shelters", "investigations", "drogentote", "pks", "jva_psych", "studies", "prison_costs", "hospital_plans", "shelter_costs", "manual_archive", "press", "officers"],
    "manual-archive": ["dip", "facilities", "media", "landtag", "rechnungshof", "orgs", "shelters", "investigations", "drogentote", "pks", "jva_psych", "studies", "prison_costs", "hospital_plans", "shelter_costs", "lags", "press", "officers"],
    "press": ["dip", "facilities", "media", "landtag", "rechnungshof", "orgs", "shelters", "investigations", "drogentote", "pks", "jva_psych", "studies", "prison_costs", "hospital_plans", "shelter_costs", "lags", "manual_archive", "officers"],
    "officers": ["dip", "facilities", "media", "landtag", "rechnungshof", "orgs", "shelters", "investigations", "drogentote", "pks", "jva_psych", "studies", "prison_costs", "hospital_plans", "shelter_costs", "lags", "manual_archive", "press", "jobcenter", "umbrellas"],
}

def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(
        prog="python3 -m ingest.domains.institutions_media",
        allow_abbrev=False,
        description="Worker tools (in-memory DB only). data/atlas.db is written only by "
                    "`python3 -m ingest.run institutions_media`.",
    )
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--selftest", action="store_true", help="offline selftest, in-memory")
    mode.add_argument("--dry-run", action="store_true", help="live fetch into an in-memory DB")
    part = ap.add_mutually_exclusive_group()
    for key in _DRY_ONLY:
        part.add_argument(
            f"--{key}-only", dest="only", action="store_const", const=key,
            help=f"--dry-run: only the {key} part",
        )
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        sys.stderr.write(
            "Workers must not write data/atlas.db. "
            "The Lead runs: python3 -m ingest.run institutions_media\n"
        )
        return 2
    try:
        a = ap.parse_args(args)
    except SystemExit as exc:
        return int(exc.code or 2)
    if a.selftest:
        if a.only:
            sys.stderr.write("--<part>-only needs --dry-run\n")
            return 2
        return selftest()
    return dry_run(skip=_DRY_ONLY[a.only]) if a.only else dry_run()


if __name__ == "__main__":
    sys.exit(main())
