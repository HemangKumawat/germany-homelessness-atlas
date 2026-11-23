"""Rechnungshof audit reports for the institutions_media domain.

Official Bundesrechnungshof and Landesrechnungshof publications only.
A PDF is stored only after it returns HTTP 200 (or 206) with a PDF content
type or ``%PDF`` magic. Euro amounts are stored only when the cited
document text actually contains the quote, with a page locator.
Licences are never NULL. Where an imprint states reuse terms, the licence
field quotes them and keeps the official URL. Where a court states no
terms for the report, the licence is "amtliches Werk, § 5 UrhG" scoped to
the cited report text only.

This module never opens data/atlas.db.
"""
from __future__ import annotations

import hashlib
import re
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import quote, urljoin

import requests

from ingest import common
from ingest.common import clean, upsert


# Same core topic list as institutions_media.SEARCH_TERMS, plus audit-specific phrasing.
# Kept here so this module can be imported without a circular import.
AUDIT_DDL = """
CREATE TABLE IF NOT EXISTS institutions_media_audit (
  report_id TEXT PRIMARY KEY,
  doc_id INTEGER,
  land TEXT,
  court TEXT,
  court_id TEXT,
  report_kind TEXT,
  title TEXT,
  chapter TEXT,
  published TEXT,
  pdf_url TEXT,
  pdf_status TEXT,
  catalog_url TEXT,
  locator TEXT,
  matched_terms TEXT,
  source_id INTEGER
);
"""


# Core topic terms plus KdU / official-accommodation phrasing used in audit titles.
AUDIT_TERMS = (
    "Wohnungslosigkeit",
    "Obdachlosigkeit",
    "Wohnungslosenhilfe",
    "Kältehilfe",
    "Wohnungsnotfall",
    "Wohnungsnotfälle",
    "Housing First",
    "wohnungslose Menschen",
    "Unterbringung Wohnungsloser",
    "Unterbringung wohnungsloser Menschen",
    "Obdachlosenhilfe",
    "obdachlose Menschen",
    "öffentlich-rechtliche Unterbringung",
    "ordnungsrechtliche Unterbringung",
    "Kosten der Unterkunft",
    "Unterkunft und Heizung",
    "Wohnungslosenpolitik",
)

# Title-only KdU reports are in scope ("Kosten der Unterkunft where relevant").
# Exclude clearly off-topic uses of "Unterkunft" (ship crews, besondere Wohnform).
KDU_TITLE_RE = re.compile(
    r"kosten der unterkunft|unterkunft und heizung|kdu-leistungen|kdu leistungen",
    re.I,
)
KDU_EXCLUDE_TITLE_RE = re.compile(
    r"besondere[n]?\s+wohnform|besatzungen|schiff",
    re.I,
)
CORE_HOMELESS_RE = re.compile(
    r"wohnung\s*s?[\-\s]*los|obdach\s*[\-\s]*los|wohnungsnotfall|"
    r"k[\wä]ltehilfe|housing\s*first|wohnungslosenhilfe|"
    r"öffentlich[-\s]*rechtliche[nrs]?\s+unterbringung|"
    r"ordnungsrechtliche[n]?\s+unterbringung",
    re.I,
)

BRH_BASE = "https://bundesrechnungshof.de"
BRH_SEARCH = "https://bundesrechnungshof.de/veroeffentlichungen/berichtssuche"
BRH_IMPRESSUM = "https://bundesrechnungshof.de/impressum"
BRH_LICENCE = (
    "urheberrechtlich geschützt. Official imprint: 'Texte, Grafiken, Filme und Bilder "
    "sind urheberrechtlich geschützt. Alle über den persönlichen Gebrauch hinausgehenden "
    "Nutzungen, insbesondere die kommerzielle Nutzung und Verbreitung, sind nicht gestattet. "
    "Sie bedürfen der ausdrücklichen Genehmigung durch den Präsidenten des Bundesrechnungshofes "
    "bzw. den angegebenen Rechteinhaber.'"
)
BRH_LICENCE_URL = BRH_IMPRESSUM
RESERVED_LICENCE = (
    "Rechte vorbehalten (Impressum zitiert); nur Fakten, Metadaten und Kurzzitate "
    "nach § 51 UrhG, Volltext nicht weiterverbreitet"
)
# Courts whose official imprint explicitly claims rights: do not assert § 5 UrhG.
RESERVED_COURT_IDS = frozenset({
    "BRH", "RH-BE", "RH-BB", "ORH-BY", "RH-BW", "RH-HB", "RH-HE",
    "LRH-NI", "LRH-NW", "RH-RP", "RH-SN", "LRH-ST", "LRH-SH", "TRH-TH",
})
MAX_QUOTE_SENTENCES = 2

BREMEN_JB2024_URL = (
    "https://www.rechnungshof.bremen.de/sixcms/media.php/13/"
    "2024-03-07_RH-Jahresberichte-2024_Land-und-Stadt-barrierefrei.pdf"
)
BREMEN_JB2024_ARCHIVE = Path.home() / "projects/_manual_archive/institutions_media/rh_bremen_jb2024.pdf"
BREMEN_JB2024_SHA256 = "1d5a8bfa3e5a6200b190455c0eadb1bde150a15533d95499070301272bfd53a6"
BREMEN_JB2024_SIZE = 7_007_314
BREMEN_JB2024_PROVENANCE = (
    "Manual archive of the official PDF. Local path: "
    "~/projects/_manual_archive/institutions_media/rh_bremen_jb2024.pdf; "
    "sha256=1d5a8bfa3e5a6200b190455c0eadb1bde150a15533d95499070301272bfd53a6; "
    "size=7007314 bytes. Fetched by the Atlas Lead from another IP with the "
    "honest project User-Agent, because the official host returns HTTP 403 to deck. "
    "source.license applies to the cited report text only as noted. "
    "The archived PDF stays local for verification only and must never be republished."
)

# Official courts: used for licence/attribution and to document coverage gaps.
COURTS = (
    {
        "id": "BRH",
        "land": "DE",
        "name": "Bundesrechnungshof",
        "publisher": "Bundesrechnungshof",
        "site": "https://www.bundesrechnungshof.de/",
        "publications": "https://bundesrechnungshof.de/veroeffentlichungen",
        "impressum": BRH_IMPRESSUM,
        "licence": BRH_LICENCE,
        "licence_url": BRH_LICENCE_URL,
        "attribution": "Bundesrechnungshof",
    },
    {
        "id": "RH-BE",
        "land": "BE",
        "name": "Rechnungshof von Berlin",
        "publisher": "Rechnungshof von Berlin",
        "site": "https://www.berlin.de/rechnungshof/",
        "publications": "https://www.berlin.de/rechnungshof/veroeffentlichungen/artikel.1338795.php",
        "impressum": "https://www.berlin.de/rechnungshof/veroeffentlichungen/archiv/artikel.385436.php",
        "licence": (
            "amtliches Werk, § 5 UrhG, scoped to the cited Jahresbericht text only; "
            "the Jahresbericht PDF and publications page state no reuse terms. "
            "Site impressum: 'Die Gestaltung des Angebots sowie die inhaltlichen Beiträge "
            "sind urheberrechtlich geschützt. Veränderungen dürfen hieran nicht vorgenommen "
            "werden. Verwendung und Vervielfältigung sind nur zu privaten Zwecken gestattet.'"
        ),
        "licence_url": "https://www.berlin.de/rechnungshof/veroeffentlichungen/archiv/artikel.385436.php",
        "attribution": "Rechnungshof von Berlin",
    },
    {
        "id": "RH-BB",
        "land": "BB",
        "name": "Landesrechnungshof Brandenburg",
        "publisher": "Landesrechnungshof Brandenburg",
        "site": "https://www.lrh-brandenburg.de/lrh/de/",
        "publications": "https://www.lrh-brandenburg.de/lrh/de/veroeffentlichungen/",
        "impressum": "https://www.lrh-brandenburg.de/lrh/de/impressum/",
        "licence": (
            "amtliches Werk, § 5 UrhG, scoped to the cited report text only; "
            "the official publications page states no reuse terms for the Jahresbericht text. "
            "Site impressum: published website contents 'unterliegen dem Urheberrecht' and "
            "non-statutory use needs prior written consent."
        ),
        "licence_url": "https://www.lrh-brandenburg.de/lrh/de/impressum/",
        "attribution": "Landesrechnungshof Brandenburg",
    },
    {
        "id": "ORH-BY",
        "land": "BY",
        "name": "Bayerischer Oberster Rechnungshof",
        "publisher": "Bayerischer Oberster Rechnungshof",
        "site": "https://www.orh.bayern.de/",
        "publications": "https://www.orh.bayern.de/berichte/jahresberichte/",
        "impressum": "https://www.orh.bayern.de/meta/impressum/index.html",
        "licence": (
            "amtliches Werk, § 5 UrhG, scoped to the cited report text only; "
            "the official Jahresberichte page states no reuse terms for the report text. "
            "Site impressum limits internet-page content to private and other own use under § 53 UrhG."
        ),
        "licence_url": "https://www.orh.bayern.de/meta/impressum/index.html",
        "attribution": "Bayerischer Oberster Rechnungshof",
    },
    {
        "id": "RH-BW",
        "land": "BW",
        "name": "Rechnungshof Baden-Württemberg",
        "publisher": "Rechnungshof Baden-Württemberg",
        "site": "https://rechnungshof.baden-wuerttemberg.de/",
        "publications": "https://rechnungshof.baden-wuerttemberg.de/",
        "impressum": "https://rechnungshof.baden-wuerttemberg.de/impressum/",
        "licence": (
            "amtliches Werk, § 5 UrhG, scoped to the cited report text only; "
            "the official site states no reuse terms for the Jahresbericht text. "
            "Site impressum places website content under German copyright, with copies only for "
            "private use unless the author consents in writing."
        ),
        "licence_url": "https://rechnungshof.baden-wuerttemberg.de/impressum/",
        "attribution": "Rechnungshof Baden-Württemberg",
    },
    {
        "id": "RH-HB",
        "land": "HB",
        "name": "Rechnungshof der Freien Hansestadt Bremen",
        "publisher": "Rechnungshof der Freien Hansestadt Bremen",
        "site": "https://www.rechnungshof.bremen.de/",
        "publications": "https://www.rechnungshof.bremen.de/berichte-presse/aktuelle-jahresberichte/jahresberichte-2024-12720",
        "impressum": "https://www.rechnungshof.bremen.de/impressum",
        "licence": (
            "amtliches Werk, § 5 UrhG, scoped to the cited Jahresbericht text only. "
            "The official PDF states no licence. Site impressum: 'Sämtliche Inhalte stehen "
            "unter einer Creative Commons Namensnennung - Nicht kommerziell - Keine Bearbeitungen "
            "Lizenz, sofern nicht im jeweiligen Seitenfuß bzw. beim einzelnen Inhalt, der Grafik "
            "oder innerhalb der Datei eine abweichende Lizenz angegeben ist.'"
        ),
        "licence_url": "https://www.rechnungshof.bremen.de/impressum",
        "attribution": "Rechnungshof der Freien Hansestadt Bremen",
    },
    {
        "id": "RH-HH",
        "land": "HH",
        "name": "Rechnungshof der Freien und Hansestadt Hamburg",
        "publisher": "Rechnungshof der Freien und Hansestadt Hamburg",
        "site": "https://www.hamburg.de/politik-und-verwaltung/behoerden/rechnungshof",
        "publications": "https://www.hamburg.de/politik-und-verwaltung/behoerden/rechnungshof/jahresberichte-933522",
        "impressum": "https://www.hamburg.de/impressum",
        "licence": (
            "amtliches Werk, § 5 UrhG, scoped to the cited Jahresbericht text only; "
            "the official Jahresberichte page and hamburg.de impressum state no reuse terms "
            "for the report text"
        ),
        "licence_url": "https://www.hamburg.de/politik-und-verwaltung/behoerden/rechnungshof/jahresberichte-933522",
        "attribution": "Rechnungshof der Freien und Hansestadt Hamburg",
    },
    {
        "id": "RH-HE",
        "land": "HE",
        "name": "Hessischer Rechnungshof",
        "publisher": "Hessischer Rechnungshof",
        "site": "https://rechnungshof.hessen.de/",
        "publications": "https://rechnungshof.hessen.de/",
        "impressum": "https://rechnungshof.hessen.de/impressum",
        "licence": (
            "amtliches Werk, § 5 UrhG, scoped to the cited report text only; "
            "the official site states no reuse terms for the Jahresbericht text. "
            "Site impressum protects website contributions and allows private copies under § 53 UrhG."
        ),
        "licence_url": "https://rechnungshof.hessen.de/impressum",
        "attribution": "Hessischer Rechnungshof",
    },
    {
        "id": "LRH-MV",
        "land": "MV",
        "name": "Landesrechnungshof Mecklenburg-Vorpommern",
        "publisher": "Landesrechnungshof Mecklenburg-Vorpommern",
        "site": "https://www.lrh-mv.de/",
        "publications": "https://www.lrh-mv.de/",
        "impressum": "https://www.lrh-mv.de/Service/Impressum/",
        "licence": (
            "amtliches Werk, § 5 UrhG, scoped to the cited report text only; "
            "the official site and impressum state no reuse terms for the Jahresbericht text"
        ),
        "licence_url": "https://www.lrh-mv.de/Service/Impressum/",
        "attribution": "Landesrechnungshof Mecklenburg-Vorpommern",
    },
    {
        "id": "LRH-NI",
        "land": "NI",
        "name": "Niedersächsischer Landesrechnungshof",
        "publisher": "Niedersächsischer Landesrechnungshof",
        "site": "https://www.lrh.niedersachsen.de/",
        "publications": "https://www.lrh.niedersachsen.de/startseite/veroffentlichungen/jahresberichte/",
        "impressum": "https://www.lrh.niedersachsen.de/startservice/service/impressum/impressum-55747.html",
        "licence": (
            "amtliches Werk, § 5 UrhG, scoped to the cited report text only; "
            "the official Jahresberichte page states no reuse terms for the report text. "
            "Site impressum reserves copyright in self-created website objects."
        ),
        "licence_url": "https://www.lrh.niedersachsen.de/startservice/service/impressum/impressum-55747.html",
        "attribution": "Niedersächsischer Landesrechnungshof",
    },
    {
        "id": "LRH-NW",
        "land": "NW",
        "name": "Landesrechnungshof Nordrhein-Westfalen",
        "publisher": "Landesrechnungshof Nordrhein-Westfalen",
        "site": "https://lrh.nrw.de/",
        "publications": "https://lrh.nrw.de/veroeffentlichungen/",
        "impressum": "https://lrh.nrw.de/impressum/",
        "licence": (
            "amtliches Werk, § 5 UrhG, scoped to the cited report text only; "
            "the official publications page states no reuse terms for the Jahresbericht text. "
            "Site impressum requires prior permission for website content; press reprints of "
            "press releases and speeches are permitted with Quellenangabe."
        ),
        "licence_url": "https://lrh.nrw.de/impressum/",
        "attribution": "Landesrechnungshof Nordrhein-Westfalen",
    },
    {
        "id": "RH-RP",
        "land": "RP",
        "name": "Rechnungshof Rheinland-Pfalz",
        "publisher": "Rechnungshof Rheinland-Pfalz",
        "site": "https://rechnungshof.rlp.de/",
        "publications": "https://rechnungshof.rlp.de/",
        "impressum": "https://rechnungshof.rlp.de/ueber-uns/impressum",
        "licence": (
            "amtliches Werk, § 5 UrhG, scoped to the cited report text only; "
            "the official site states no reuse terms for the Jahresbericht text. "
            "Site impressum forbids downloading website texts or images for further use without agreement."
        ),
        "licence_url": "https://rechnungshof.rlp.de/ueber-uns/impressum",
        "attribution": "Rechnungshof Rheinland-Pfalz",
    },
    {
        "id": "RH-SL",
        "land": "SL",
        "name": "Rechnungshof des Saarlandes",
        "publisher": "Rechnungshof des Saarlandes",
        "site": "https://www.rechnungshof.saarland.de/",
        "publications": "https://www.rechnungshof.saarland.de/",
        "impressum": "https://www.rechnungshof.saarland.de/footer/impressum",
        "licence": (
            "amtliches Werk, § 5 UrhG, scoped to the cited report text only; "
            "the official site and impressum state no reuse terms for the Jahresbericht text"
        ),
        "licence_url": "https://www.rechnungshof.saarland.de/footer/impressum",
        "attribution": "Rechnungshof des Saarlandes",
    },
    {
        "id": "RH-SN",
        "land": "SN",
        "name": "Sächsischer Rechnungshof",
        "publisher": "Sächsischer Rechnungshof",
        "site": "https://www.rechnungshof.sachsen.de/",
        "publications": "https://www.rechnungshof.sachsen.de/jahresberichte.html",
        "impressum": "https://www.rechnungshof.sachsen.de/impressum.html",
        "licence": (
            "amtliches Werk, § 5 UrhG, scoped to the cited report text only; "
            "the official Jahresberichte page states no reuse terms for the report text. "
            "Site impressum requires prior editorial permission for website pages."
        ),
        "licence_url": "https://www.rechnungshof.sachsen.de/impressum.html",
        "attribution": "Sächsischer Rechnungshof",
    },
    {
        "id": "LRH-ST",
        "land": "ST",
        "name": "Landesrechnungshof Sachsen-Anhalt",
        "publisher": "Landesrechnungshof Sachsen-Anhalt",
        "site": "https://lrh.sachsen-anhalt.de/",
        "publications": "https://lrh.sachsen-anhalt.de/",
        "impressum": "https://lrh.sachsen-anhalt.de/stellenangebote-service/impressum",
        "licence": (
            "amtliches Werk, § 5 UrhG, scoped to the cited report text only; "
            "the official site states no reuse terms for the Jahresbericht text. "
            "The Landesportal impressum permits private reuse of editorial website content and "
            "requires consent for public or commercial use."
        ),
        "licence_url": "https://lrh.sachsen-anhalt.de/stellenangebote-service/impressum",
        "attribution": "Landesrechnungshof Sachsen-Anhalt",
    },
    {
        "id": "LRH-SH",
        "land": "SH",
        "name": "Landesrechnungshof Schleswig-Holstein",
        "publisher": "Landesrechnungshof Schleswig-Holstein",
        "site": "https://landesrechnungshof-sh.de/",
        "publications": "https://landesrechnungshof-sh.de/de/bemerkungen",
        "impressum": "https://landesrechnungshof-sh.de/de/impressum",
        "licence": (
            "amtliches Werk, § 5 UrhG, scoped to the cited report text only; "
            "the official Bemerkungen page states no reuse terms for the report text. "
            "Site impressum allows only private copies of the website unless the court consents in writing."
        ),
        "licence_url": "https://landesrechnungshof-sh.de/de/impressum",
        "attribution": "Landesrechnungshof Schleswig-Holstein",
    },
    {
        "id": "TRH-TH",
        "land": "TH",
        "name": "Thüringer Rechnungshof",
        "publisher": "Thüringer Rechnungshof",
        "site": "https://www.thueringer-rechnungshof.de/",
        "publications": "https://www.thueringer-rechnungshof.de/",
        "impressum": "https://www.thueringer-rechnungshof.de/impressum/",
        "licence": (
            "amtliches Werk, § 5 UrhG, scoped to the cited report text only; "
            "the official site states no reuse terms for the Jahresbericht text. "
            "Site impressum places website content under German copyright and limits downloads to private use."
        ),
        "licence_url": "https://www.thueringer-rechnungshof.de/impressum/",
        "attribution": "Thüringer Rechnungshof",
    },
)

COURT_BY_ID = {row["id"]: row for row in COURTS}
for _row in COURTS:
    if _row["id"] in RESERVED_COURT_IDS:
        _row["licence"] = RESERVED_LICENCE
        _row["reserved_rights"] = True
        _row["redistribute_fulltext"] = 0
    else:
        _row.setdefault("reserved_rights", False)
        _row.setdefault("redistribute_fulltext", 1)


def _im():
    from ingest.domains import institutions_media as im
    return im



def court_licence(court_id: str) -> tuple[str, str, str]:
    row = COURT_BY_ID[court_id]
    return row["licence"], row["licence_url"], row["attribution"]


def fold_text(value: str | None) -> str:
    """Collapse whitespace and join hyphenation at line breaks so quotes can be checked."""
    if not value:
        return ""
    text = re.sub(r"(\w)[\-\u00ad\u2010\u2011]\s+", r"\1", value)
    text = text.replace("\u00ad", "")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


_ABBREV_END = re.compile(
    r"\b(?:Mio|Mrd|Tsd|Tz|Abs|Art|Nr|Dr|S|rd|bzw|usw|ca|vgl|inkl|ff)\.$",
    re.I,
)


def trim_quote(quote: str | None, *, max_sentences: int = MAX_QUOTE_SENTENCES) -> str | None:
    """Keep at most two sentences for a § 51 UrhG locator quote; never a paragraph."""
    text = clean(quote)
    if not text:
        return None
    if "\n\n" in text:
        text = text.split("\n\n", 1)[0].strip()
    pieces: list[str] = []
    buf: list[str] = []
    parts = re.split(r"(?<=[.!?])\s+", text)
    for part in parts:
        token = part.strip()
        if not token:
            continue
        buf.append(token)
        if _ABBREV_END.search(token):
            continue
        pieces.append(" ".join(buf))
        buf = []
        if len(pieces) >= max_sentences:
            break
    if buf and len(pieces) < max_sentences:
        pieces.append(" ".join(buf))
    return " ".join(pieces).strip() or text


def quote_in_text(quote: str | None, document_text: str | None) -> bool:
    q = fold_text(quote)
    hay = fold_text(document_text)
    if not q or not hay:
        return False
    return q.casefold() in hay.casefold()


def audit_terms(*parts: str | None) -> list[str]:
    hay = fold_text(" ".join(part or "" for part in parts)).casefold()
    found = [term for term in AUDIT_TERMS if term.casefold() in hay]
    kept = []
    for term in found:
        longer = any(
            term.casefold() != other.casefold() and term.casefold() in other.casefold()
            for other in found
        )
        if not longer:
            kept.append(term)
    return kept


def title_is_kdu(title: str | None) -> bool:
    text = title or ""
    return bool(KDU_TITLE_RE.search(text)) and not KDU_EXCLUDE_TITLE_RE.search(text)


def audit_is_substantive(title: str | None, document_text: str | None = None, chapter: str | None = None) -> bool:
    """Keep dedicated homelessness/KdU audits; drop incidental glossary or one-off mentions."""
    heading = " ".join(part for part in (title, chapter) if part)
    if title_is_kdu(heading) or CORE_HOMELESS_RE.search(heading or ""):
        return True
    body = fold_text(document_text)
    if not body:
        return False
    hits = list(CORE_HOMELESS_RE.finditer(body))
    return len(hits) >= 5


def _metric_entity(land: str | None) -> tuple[str, str]:
    if land and land != "DE":
        from ingest.common import LAND_AGS
        if land in LAND_AGS:
            return "land", LAND_AGS[land]
        if len(land) == 2 and land.isdigit() and land[0] in "01":
            return "land", land
        raise ValueError(f"metric land entity_id must be a 2-digit AGS, not {land!r}")
    return "de", "DE"


# Verified official reports. Metrics are stored only if the quote is found in the PDF text.
CATALOG = (
    {
        "report_id": "BRH:KDU-2019",
        "court_id": "BRH",
        "report_kind": "pruefungsmitteilung",
        "title": "Beteiligung des Bundes an den Leistungen für Unterkunft und Heizung",
        "published": "2019-12-19",
        "catalog_url": "https://bundesrechnungshof.de/berichte/beteiligung-des-bundes-an-den-leistungen-fuer-unterkunft-und-heizung",
        "pdf_url": "https://bundesrechnungshof.de/fileadmin/import/___Alte_Struktur/Downloads/DE/Berichte/2019/leistungen-fuer-unterkunft-und-heizung-volltext-leistungen-fuer-unterkunft-und-heizung-volltext.pdf",
        "locator": None,
        "chapter": None,
        "metrics": (),
    },
    {
        "report_id": "BRH:KDU-2020-I",
        "court_id": "BRH",
        "report_kind": "pruefungsmitteilung",
        "title": "Leistungen für Unterkunft und Heizung im Rechtskreis des SGB II Teil I: Geflüchtete",
        "published": "2020-06-23",
        "catalog_url": "https://bundesrechnungshof.de/berichte/leistungen-fuer-unterkunft-und-heizung-im-rechtskreis-des-sgb-ii-teil-i-gefluechtete",
        "pdf_url": "https://bundesrechnungshof.de/fileadmin/import/___Alte_Struktur/Downloads/DE/Berichte/2020/leistungen-fuer-unterkunft-und-heizung-gefluechteter-volltext-leistungen-fuer-unterkunft-und-heizung-gefluechteter-volltext.pdf",
        "metrics": (),
    },
    {
        "report_id": "BRH:KDU-2020-II",
        "court_id": "BRH",
        "report_kind": "pruefungsmitteilung",
        "title": "Leistungen für Unterkunft und Heizung im Rechtskreis des SGB II Teil II: Nicht Geflüchtete",
        "published": "2020-06-23",
        "catalog_url": "https://bundesrechnungshof.de/berichte/leistungen-fuer-unterkunft-und-heizung-im-rechtskreis-des-sgb-ii-teil-ii-nicht-gefluechtete",
        "pdf_url": "https://bundesrechnungshof.de/fileadmin/import/___Alte_Struktur/Downloads/DE/Berichte/2020/leistungen-fuer-unterkunft-und-heizung-nicht-gefluechteter-volltext-leistungen-fuer-unterkunft-und-heizung-nicht-gefluechteter-volltext.pdf",
        "metrics": (),
    },
    {
        "report_id": "BRH:KDU-2023-B28",
        "court_id": "BRH",
        "report_kind": "bemerkung",
        "title": "Bemerkungen 2022 zur Haushalts- und Wirtschaftsführung des Bundes – Ergänzungsband – (BT-Drs 20/6530), Bemerkung 28",
        "chapter": "Bemerkung 28: Leistungen für Unterkunft und Heizung",
        "published": "2023-04-18",
        "catalog_url": "https://dip.bundestag.de/drucksache/267178",
        "pdf_url": "https://dserver.bundestag.de/btd/20/065/2006530.pdf",
        "locator": "BT-Drs 20/6530, S. 48, Bemerkung 28",
        "license": "TODO: DIP Nutzungsbedingungen pending Lead confirmation",
        "license_url": "https://dip.bundestag.de/über-dip/nutzungsbedingungen",
        "attribution": "Deutscher Bundestag / Bundesrechnungshof",
        "redistribute_fulltext": 1,
        "provenance": (
            "Cited from the official Bundestag printing (Unterrichtung, BT-Drs 20/6530, "
            "DIP id 267178, published 2023-04-18, urheber Bundesrechnungshof) under DIP terms, "
            "not from the BRH website PDF. Quotes checked in the official dserver PDF."
        ),
        "metrics": (
            {
                "metric": "de_kdu_federal_annual_eur",
                "value": 10_000_000_000.0,
                "unit": "EUR",
                "year": 2022,
                "is_rounded": 1,
                "quote": "Bund trägt jährlich KdU-Leistungen von 10 Mrd. Euro",
                "locator": "BT-Drs 20/6530, S. 48, Bemerkung 28",
                "note": "Printed as 'jährlich' 10 Mrd. Euro in BT-Drs 20/6530, Bemerkung 28.",
            },
            {
                "metric": "de_kdu_federal_disadvantage_prevented_eur",
                "value": 9_800_000.0,
                "unit": "EUR",
                "year": 2022,
                "is_rounded": 1,
                "quote": "einen finanziellen Nachteil für den Bund von 9,8 Mio. Euro.",
                "locator": "BT-Drs 20/6530, S. 48, Bemerkung 28",
                "note": "Printed in the preamble of Bemerkung 28 in BT-Drs 20/6530.",
            },
        ),
    },
    {
        "report_id": "BRH:KDU-2024",
        "court_id": "BRH",
        "report_kind": "beratungsbericht",
        "title": "Gewährung von Leistungen für Unterkunft und Heizung durch die Jobcenter",
        "published": "2024-09-13",
        "catalog_url": "https://bundesrechnungshof.de/berichte/gewaehrung-von-leistungen-fuer-unterkunft-und-heizung-durch-die-jobcenter",
        "pdf_url": "https://bundesrechnungshof.de/fileadmin/import/___Alte_Struktur/Downloads/DE/Berichte/2024/leistungen-unterkunft-und-heizung-volltext-leistungen-unterkunft-und-heizung-volltext.pdf",
        "metrics": (),
    },
    {
        "report_id": "RH-BE:JB-2019",
        "court_id": "RH-BE",
        "report_kind": "jahresbericht",
        "title": "Jahresbericht 2019",
        "chapter": "T 14 Unterbringung Wohnungsloser; T 15 Förderung der Wohnungslosenhilfe im Integrierten Sozialprogramm",
        "published": "2019-04-02",
        "catalog_url": "https://www.berlin.de/rechnungshof/veroeffentlichungen/artikel.1338795.php",
        "pdf_url": "https://www.berlin.de/rechnungshof/_assets/jahresbericht-2019.pdf",
        "locator": "S. 185–207",
        "metrics": (
            {
                "metric": "be_isp_wohnungslosenhilfe_plan_eur",
                "value": 2_937_885.99,
                "unit": "EUR",
                "year": 2015,
                "is_rounded": 0,
                "quote": "2015                2.937.885,99 €",
                "locator": "S. 201, Ansicht 60",
                "note": "Ansicht 60: Entwicklung der Fördermittel, Wohnungslosenhilfe im ISP (Plan).",
            },
            {
                "metric": "be_isp_wohnungslosenhilfe_plan_eur",
                "value": 4_106_026.67,
                "unit": "EUR",
                "year": 2016,
                "is_rounded": 0,
                "quote": "2016                  1150       68406              17.317.000 €                      4.106.026,67 €",
                "locator": "S. 197, Ansicht 59",
                "note": "Ansicht 59: davon Wohnungslosenhilfe (Plan). The 17.317.000 € column is the wider ISP approach, not stored.",
            },
            {
                "metric": "be_isp_wohnungslosenhilfe_plan_eur",
                "value": 4_174_127.76,
                "unit": "EUR",
                "year": 2017,
                "is_rounded": 0,
                "quote": "2017                  1150       68406              17.609.000 €                      4.174.127,76 €",
                "locator": "S. 197, Ansicht 59",
                "note": "Ansicht 59: davon Wohnungslosenhilfe (Plan).",
            },
            {
                "metric": "be_isp_wohnungslosenhilfe_plan_eur",
                "value": 8_130_474.69,
                "unit": "EUR",
                "year": 2018,
                "is_rounded": 0,
                "quote": "2018                  1150       68406              27.558.000 €                      8.130.474,69 €",
                "locator": "S. 197, Ansicht 59",
                "note": "Ansicht 59: davon Wohnungslosenhilfe (Plan).",
            },
        ),
    },
    {
        "report_id": "RH-HH:JB-2025",
        "court_id": "RH-HH",
        "report_kind": "jahresbericht",
        "title": "Jahresbericht 2025",
        "chapter": "Nachbewilligungen 2023 (PG 253.03 Wohnungslosenhilfe); Bereitstellung von Unterbringungsstandorten",
        "published": "2025",
        "catalog_url": "https://www.hamburg.de/politik-und-verwaltung/behoerden/rechnungshof/pressemitteilungen/rechnungshof-veroeffentlicht-jahresbericht-2025--1014296",
        "pdf_url": "https://dokumente.hamburg.de/resource/blob/1014440/53428c1587d263b4aeb16f6a8d4c92b5/jahresbericht-2025-pdf-data.pdf",
        "locator": "S. 55, 91",
        "metrics": (
            {
                "metric": "hh_pg25303_transfer_authorisation_eur",
                "value": 180_404_000.0,
                "unit": "EUR",
                "year": 2023,
                "is_rounded": 0,
                "quote": "in der PG 253.03 „Wohnungslosenhilfe und öffentliche Unterbringung“ in Höhe von 180.404 Tsd. Euro für Kosten aus Transferleistungen benötigt würden",
                "locator": "S. 55, Tz. 100",
                "note": "Nachbewilligungsbedarf stated by the Sozialbehörde and recorded by the Rechnungshof.",
            },
        ),
    },
    {
        "report_id": "RH-HH:JB-2026",
        "court_id": "RH-HH",
        "report_kind": "jahresbericht",
        "title": "Jahresbericht 2026",
        "chapter": "Finanzierung der öffentlich-rechtlichen Unterbringung",
        "published": "2026",
        "catalog_url": "https://www.hamburg.de/politik-und-verwaltung/behoerden/rechnungshof/pressemitteilungen/rechnungshof-veroeffentlicht-jahresbericht-2026-1137152",
        "pdf_url": "https://www.hamburg.de/resource/blob/1136702/fea817cea7e98dd41c12b1573eb18107/jahresbericht-2026-pdf-data.pdf",
        "locator": "S. 158–164",
        "metrics": (
            {
                "metric": "hh_oeru_additional_transfer_bedarf_eur",
                "value": 127_400_000.0,
                "unit": "EUR",
                "year": 2023,
                "is_rounded": 1,
                "quote": "einen Mehrbedarf in Höhe von 127,4 Mio. Euro",
                "locator": "S. 164, Tz. 591",
                "note": "Nachbewilligungsdrucksache 22/13026, as recorded in the Jahresbericht.",
            },
        ),
    },
    {
        "report_id": "RH-HH:BA-2026",
        "court_id": "RH-HH",
        "report_kind": "beratungsbericht",
        "title": "Bericht zur Haushaltslage 2026 (Beratende Äußerung)",
        "chapter": "4.2.2 Wohnungslosenhilfe und öffentlich-rechtliche Unterbringung",
        "published": "2026",
        "catalog_url": "https://www.hamburg.de/politik-und-verwaltung/behoerden/rechnungshof/veroeffentlichungen/beratende-aeusserung-haushaltslage-2026-1207348",
        "pdf_url": "https://dokumente.hamburg.de/resource/blob/1207456/f34e32de7e93405ffb55b206fe5690c4/beratendeaeusserung-2026-haushaltslage-pdf-data.pdf",
        "locator": "S. 28–30",
        "metrics": (
            {
                "metric": "hh_pg25303_transfer_eur",
                "value": 45_000_000.0,
                "unit": "EUR",
                "year": 2019,
                "is_rounded": 1,
                "quote": "sind im Zeitraum von 2019 bis 2025 von 45 Mio. Euro auf 289 Mio. Euro gestiegen",
                "locator": "S. 28, Abschnitt 4.2.2",
                "note": "Transferleistungen in PG 253.03, starting year of the printed range.",
            },
            {
                "metric": "hh_pg25303_transfer_eur",
                "value": 289_000_000.0,
                "unit": "EUR",
                "year": 2025,
                "is_rounded": 1,
                "quote": "sind im Zeitraum von 2019 bis 2025 von 45 Mio. Euro auf 289 Mio. Euro gestiegen",
                "locator": "S. 28, Abschnitt 4.2.2",
                "note": "Transferleistungen in PG 253.03, end year of the printed range (also the 2025 Ist on S. 30).",
            },
            {
                "metric": "hh_pg25303_transfer_plan_eur",
                "value": 221_000_000.0,
                "unit": "EUR",
                "year": 2027,
                "is_rounded": 1,
                "quote": "221 Mio. Euro im Jahr 2027",
                "locator": "S. 30, Abschnitt 4.2.2",
            },
            {
                "metric": "hh_pg25303_transfer_plan_eur",
                "value": 222_000_000.0,
                "unit": "EUR",
                "year": 2028,
                "is_rounded": 1,
                "quote": "222 Mio. Euro in 2028",
                "locator": "S. 30, Abschnitt 4.2.2",
            },
        ),
    },
    {
        "report_id": "RH-HB:JB-2024",
        "court_id": "RH-HB",
        "report_kind": "jahresbericht",
        "title": "Jahresberichte 2024 (Land und Stadt)",
        "chapter": "Projekt Housing First",
        "published": "2024-03-07",
        "catalog_url": "https://www.rechnungshof.bremen.de/berichte-presse/aktuelle-jahresberichte/jahresberichte-2024-12720",
        "pdf_url": BREMEN_JB2024_URL,
        "locator": "Stadt, S. 63–65 (Tz. 238–251)",
        "local_archive": str(BREMEN_JB2024_ARCHIVE),
        "local_archive_sha256": BREMEN_JB2024_SHA256,
        "local_archive_size": BREMEN_JB2024_SIZE,
        "provenance": BREMEN_JB2024_PROVENANCE,
        "metrics": (
            {
                "metric": "hb_housing_first_grant_eur",
                "value": 232_000.0,
                "unit": "EUR",
                "year": 2021,
                "is_rounded": 1,
                "quote": "Für das Jahr 2021 gewährte das Ressort dem Trägerverbund eine Zuwendung in Höhe von rd. 232 T€",
                "locator": "Stadt, S. 65, Tz. 250",
                "note": "Printed as 'rd. 232 T€'.",
            },
            {
                "metric": "hb_housing_first_overpayment_eur",
                "value": 72_000.0,
                "unit": "EUR",
                "year": 2021,
                "is_rounded": 1,
                "quote": "Die dadurch entstandene Überzahlung der Zuwendung in Höhe von rd. 72 T€",
                "locator": "Stadt, S. 65, Tz. 250",
                "note": "Printed as 'rd. 72 T€'.",
            },
            {
                "metric": "hb_housing_first_grant_eur",
                "value": 400_000.0,
                "unit": "EUR",
                "year": 2022,
                "is_rounded": 1,
                "quote": "Für das Jahr 2022 bewilligte das Ressort eine Zuwendung in Höhe von 400 T€",
                "locator": "Stadt, S. 65, Tz. 251",
            },
        ),
    },
)


def ensure_audit_tables(conn) -> None:
    conn.executescript(AUDIT_DDL)


def _summary(rec: dict) -> str:
    bits = [rec.get("title") or ""]
    if rec.get("chapter"):
        bits.append(rec["chapter"])
    if rec.get("locator"):
        bits.append(f"Locator: {rec['locator']}")
    terms = rec.get("matched_terms") or []
    if isinstance(terms, str):
        terms = [t.strip() for t in terms.split(",") if t.strip()]
    if terms:
        bits.append("Matched: " + ", ".join(terms))
    return " — ".join(b for b in bits if b)


def store_audit(conn, rec: dict, *, sources, document_text: str | None = None) -> bool:
    """Insert one official audit PDF as doc + institutions_media_audit. Licence is required."""
    report_id = clean(rec.get("report_id"))
    pdf_url = clean(rec.get("pdf_url"))
    title = clean(rec.get("title"))
    if not report_id or not pdf_url or not title:
        return False
    if rec.get("pdf_status") and rec.get("pdf_status") != "verified_pdf":
        return False
    court_id = clean(rec.get("court_id"))
    if not court_id or court_id not in COURT_BY_ID:
        return False
    court = COURT_BY_ID[court_id]
    land = clean(rec.get("land")) or court["land"]
    licence, licence_url, attribution = court_licence(court_id)
    licence = clean(rec.get("license")) or licence
    licence_url = clean(rec.get("license_url")) or licence_url
    attribution = clean(rec.get("attribution")) or attribution
    if not licence:
        raise ValueError("source.license must not be NULL; refuse to register " + pdf_url)
    if licence.upper().startswith("TODO"):
        # Lead, 2026-11-21: a Bundestag printing (dserver) is under the established DIP terms; anything else
        # with a placeholder licence is excluded.
        if "dserver.bundestag.de/" not in pdf_url:
            return False
        im = _im()
        licence, licence_url = im.DIP_LICENCE, im.DIP_LICENCE_URL
        attribution = "Deutscher Bundestag/Bundesrat – DIP (Unterrichtung durch den Bundesrechnungshof)"
    chapter = clean(rec.get("chapter"))
    terms = rec.get("matched_terms")
    if not terms:
        terms = audit_terms(title, chapter, rec.get("summary"), document_text)
    if isinstance(terms, list):
        terms_text = ", ".join(terms) if terms else None
    else:
        terms_text = clean(terms)
    heading_ok = audit_is_substantive(title, document_text, chapter)
    if not heading_ok and not rec.get("skip_substantive_check"):
        return False
    catalog_url = clean(rec.get("catalog_url"))
    # Lead, 2026-11-21: cite the archived PDF itself (figures and quotes are checked against it), never the
    # unarchived catalog page. A verified manual archive is seeded into the fetch cache when deck gets 403.
    if not _archive_pdf(rec, pdf_url):
        return False
    source_url = pdf_url
    if rec.get("redistribute_fulltext") is not None:
        redistribute = 1 if rec.get("redistribute_fulltext") else 0
    else:
        redistribute = 0 if court.get("reserved_rights") else 1
    source_id = _im()._register_source(
        conn, source_url,
        title=title,
        publisher=court["publisher"],
        license_=licence,
        bucket=sources,
        license_url=licence_url,
        attribution=attribution,
        notes=(
            f"rechnungshof {court_id} {rec.get('report_kind') or ''}".strip()
            + (f". {rec['provenance']}" if rec.get("provenance") else "")
        ),
        redistribute_fulltext=redistribute,
    )
    doc_url = pdf_url
    summary = clean(rec.get("summary")) or _summary({**rec, "matched_terms": terms})
    doc_rowid = upsert(conn, "doc", {
        "kind": "audit",
        "title": title if not chapter else f"{title} — {chapter}",
        "url": doc_url,
        "herausgeber": court["publisher"],
        "urheber": court["name"],
        "veroeffentlicht": clean(rec.get("published")),
        "land": land,
        "ort": None if land == "DE" else land,
        "zusammenfassung": summary,
        "source_id": source_id,
    }, ["url"])
    # doc.id may differ from rowid if the table has an id; fetch it.
    doc_id = conn.execute("SELECT id FROM doc WHERE url=?", (doc_url,)).fetchone()["id"]
    upsert(conn, "institutions_media_audit", {
        "report_id": report_id,
        "doc_id": doc_id,
        "land": land,
        "court": court["name"],
        "court_id": court_id,
        "report_kind": clean(rec.get("report_kind")),
        "title": title,
        "chapter": chapter,
        "published": clean(rec.get("published")),
        "pdf_url": pdf_url,
        "pdf_status": rec.get("pdf_status") or "verified_pdf",
        "catalog_url": catalog_url,
        "locator": clean(rec.get("locator")),
        "matched_terms": terms_text,
        "source_id": source_id,
    }, ["report_id"])
    _ = doc_rowid
    return True



def _archive_pdf(rec: dict, pdf_url: str) -> bool:
    """Archive the exact PDF URL a row will cite under data/raw/institutions_media; False drops the row."""
    import json as _json
    from ingest import common as _common
    im = _im()
    if im._OFFLINE[0]:
        return True
    if _common.cached_path(im.DOMAIN, pdf_url) is not None:
        return True
    if im._archive(pdf_url):
        return True
    if rec.get("local_archive") and verify_local_archive(rec) == "verified_pdf":
        data = Path(rec["local_archive"]).read_bytes()
        dest = _common.raw_path(im.DOMAIN, pdf_url)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        dest.with_suffix(".meta.json").write_text(_json.dumps({
            "url": pdf_url, "method": "GET", "status": 200, "retrieved_at": _common.now(),
            "content_type": "application/pdf", "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "note": "seeded from verified manual archive (official host returns 403 to deck)"},
            ensure_ascii=False), encoding="utf-8")
        return True
    return False

def store_audit_metrics(conn, rec: dict, *, source_id: int, document_text: str | None, notes: list[str]) -> int:
    """Store euro (or other) metrics only when the quote is present in the document text."""
    land = clean(rec.get("land")) or COURT_BY_ID[rec["court_id"]]["land"]
    entity_type, entity_id = _metric_entity(land)
    stored = 0
    for raw in rec.get("metrics") or []:
        quote = trim_quote(raw.get("quote"))
        value = raw.get("value")
        metric = clean(raw.get("metric"))
        year = raw.get("year")
        if quote is None or value is None or not metric or year is None:
            notes.append(f"{rec.get('report_id')}: skipped metric without quote, value, name or year")
            continue
        try:
            amount = float(value)
        except (TypeError, ValueError):
            notes.append(f"{rec.get('report_id')}: skipped non-numeric metric {metric}")
            continue
        if document_text is None or not quote_in_text(quote, document_text):
            notes.append(
                f"{rec.get('report_id')}: euro metric {metric} {year} not stored; "
                "quote was not found in the cited document text"
            )
            continue
        upsert(conn, "metric", {
            "entity_type": entity_type,
            "entity_id": entity_id,
            "metric": metric,
            "value": amount,
            "einheit": clean(raw.get("unit")) or "EUR",
            "year": int(year),
            "period": clean(raw.get("period")),
            "is_est": int(raw.get("is_est") or 0),
            "is_rounded": int(raw.get("is_rounded") or 0),
            "anmerkung": clean(raw.get("note")),
            "quote": quote,
            "locator": clean(raw.get("locator")) or clean(rec.get("locator")),
            "source_id": source_id,
        }, ["entity_type", "entity_id", "metric", "year"])
        stored += 1
    return stored


def _pdf_text_from_bytes(data: bytes) -> str | None:
    if not data or not data.startswith(b"%PDF"):
        return None
    with tempfile.TemporaryDirectory(prefix="rh-pdf-") as tmp:
        path = Path(tmp) / "report.pdf"
        path.write_bytes(data)
        txt = Path(tmp) / "report.txt"
        try:
            subprocess.run(
                ["pdftotext", "-layout", str(path), str(txt)],
                check=False,
                capture_output=True,
                timeout=120,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        if not txt.exists():
            return None
        return txt.read_text(encoding="utf-8", errors="replace")


def fetch_pdf_text(url: str, *, skip_verify: bool, provided: str | None = None) -> str | None:
    if provided:
        return provided
    if skip_verify:
        return None
    # Lead, 2026-11-21: read the archived copy (the same bytes verify checks quotes against); fetch() caches it.
    try:
        hit = common.cached_path(_im().DOMAIN, url)
        data = hit.read_bytes() if hit is not None else common.fetch(url, domain=_im().DOMAIN, retries=5)
        if data[:5] == b"%PDF-":
            text = _pdf_text_from_bytes(data)
            if text:
                return text
    except Exception:  # noqa: BLE001 - fall back to the direct GET below
        pass
    common._polite_wait()
    headers = {"User-Agent": common.UA, "Accept": "application/pdf,*/*"}
    response = None
    for attempt in range(4):
        try:
            response = requests.get(url, headers=headers, timeout=90, allow_redirects=True)
        except requests.RequestException:
            common._polite_wait()
            continue
        if response.status_code in (200, 206):
            text = _pdf_text_from_bytes(response.content)
            if text:
                return text
        if response.status_code not in (429, 500, 502, 503, 504) and attempt >= 2:
            return None
        common._polite_wait()
    return None


def verify_local_archive(rec: dict) -> str | None:
    """Return 'verified_pdf' when a manual archive matches size, sha256 and %PDF magic."""
    path = rec.get("local_archive")
    sha = rec.get("local_archive_sha256")
    size = rec.get("local_archive_size")
    if not path or not sha or size is None:
        return None
    pdf = Path(path).expanduser()
    try:
        actual = pdf.stat().st_size
    except OSError:
        return None
    if actual != int(size):
        return None
    digest = hashlib.sha256()
    try:
        with pdf.open("rb") as handle:
            magic = handle.read(8)
            if not magic.startswith(b"%PDF"):
                return None
            digest.update(magic)
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        return None
    if digest.hexdigest().lower() != str(sha).lower():
        return None
    return "verified_pdf"


def fetch_pdf_text_from_path(path: str | None) -> str | None:
    if not path:
        return None
    pdf = Path(path).expanduser()
    if not pdf.is_file():
        return None
    try:
        return _pdf_text_from_bytes(pdf.read_bytes())
    except OSError:
        return None


def verify_catalog_pdf(url: str, *, skip_verify: bool, attempts: int = 4) -> str:
    if skip_verify:
        return "unchecked"
    if not url:
        return "no_url"
    probed = {}
    for attempt in range(max(1, int(attempts))):
        probed = _im()._probe(url, want_pdf=True)
        status = probed.get("status")
        verdict = _im().pdf_verdict(status, probed.get("content_type"), probed.get("magic"))
        if verdict == "verified_pdf":
            return verdict
        if attempt == 1:
            probed = _im()._probe(url, want_pdf=False)
            verdict = _im().pdf_verdict(
                probed.get("status"), probed.get("content_type"), probed.get("magic")
            )
            if verdict == "verified_pdf":
                return verdict
        if status not in (None, 429, 403, 500, 502, 503, 504) and verdict != "unavailable":
            return verdict
        common._polite_wait()
    return _im().pdf_verdict(probed.get("status"), probed.get("content_type"), probed.get("magic"))


def ingest_rechnungshof_catalog(conn, cfg, sources, notes, *, catalog=None) -> int:
    """Store the curated official catalog after PDF verification and quote checks."""
    ensure_audit_tables(conn)
    skip_verify = bool(cfg.get("skip_verify"))
    limit = cfg.get("limit")
    stored = 0
    metrics = 0
    skipped_pdf = 0
    rows = list(catalog if catalog is not None else CATALOG)
    if isinstance(limit, int) and "fixture" not in (cfg or {}):
        rows = rows[: max(0, limit)]
    for rec in rows:
        rec = dict(rec)
        pdf_url = rec.get("pdf_url")
        status = rec.get("pdf_status")
        used_archive = False
        if status != "verified_pdf" and rec.get("local_archive") and not skip_verify:
            if verify_local_archive(rec) == "verified_pdf":
                used_archive = True
                remote = verify_catalog_pdf(pdf_url, skip_verify=False, attempts=1)
                status = "verified_pdf"
                rec["_used_local_archive"] = True
                notes.append(
                    f"{rec.get('report_id')}: official URL {pdf_url} returned {remote} "
                    f"from this host; stored from manual archive {rec.get('local_archive')} "
                    f"(sha256={rec.get('local_archive_sha256')}, "
                    f"size={rec.get('local_archive_size')} bytes). {rec.get('provenance') or ''}"
                )
        if status != "verified_pdf":
            status = verify_catalog_pdf(pdf_url, skip_verify=skip_verify)
        rec["pdf_status"] = status if status == "verified_pdf" or skip_verify else status
        if skip_verify and rec.get("pdf_status") != "verified_pdf":
            rec["pdf_status"] = "verified_pdf"
        if rec["pdf_status"] != "verified_pdf":
            skipped_pdf += 1
            notes.append(
                f"{rec.get('report_id')}: official PDF not stored ({rec['pdf_status']}): {pdf_url}"
            )
            continue
        document_text = rec.get("document_text")
        if rec.get("metrics") and document_text is None:
            if used_archive:
                document_text = fetch_pdf_text_from_path(rec.get("local_archive"))
            else:
                document_text = fetch_pdf_text(
                    pdf_url, skip_verify=skip_verify, provided=rec.get("document_text")
                )
                if not document_text and rec.get("local_archive"):
                    document_text = fetch_pdf_text_from_path(rec.get("local_archive"))
        heading_text = document_text
        rec["matched_terms"] = rec.get("matched_terms") or audit_terms(
            rec.get("title"), rec.get("chapter"), heading_text
        )
        if store_audit(conn, rec, sources=sources, document_text=heading_text or rec.get("title")):
            stored += 1
            source_id = conn.execute(
                "SELECT source_id FROM institutions_media_audit WHERE report_id=?",
                (rec["report_id"],),
            ).fetchone()["source_id"]
            if rec.get("metrics"):
                metrics += store_audit_metrics(
                    conn, rec, source_id=source_id, document_text=document_text, notes=notes
                )
    notes.append(
        f"rechnungshof catalog stored={stored} metrics={metrics} pdf_rejected={skipped_pdf}"
    )
    return stored


def parse_brh_search_results(html_text: str) -> list[dict]:
    """Parse Typo3 Solr result titles from the official Berichtssuche HTML."""
    rows = []
    for match in re.finditer(
        r'<h[23][^>]*>\s*<a[^>]+href="([^"]+)"[^>]*>([\s\S]*?)</a>',
        html_text or "",
        re.I,
    ):
        href = match.group(1)
        title = re.sub(r"<[^>]+>", " ", match.group(2))
        title = re.sub(r"\s+", " ", title).strip()
        if "/berichte/" not in href or "suche" in href.lower():
            continue
        rows.append({"title": title, "catalog_url": urljoin(BRH_BASE, href)})
    return rows


def brh_search_queries() -> list[str]:
    return [
        "Obdachlosigkeit",
        "Wohnungslosenhilfe",
        "wohnungslose Menschen",
        "Kosten der Unterkunft",
        "Unterkunft und Heizung",
    ]


def discover_brh_title_hits(html_pages: list[str]) -> list[dict]:
    """Keep BRH search hits whose titles are dedicated KdU or homelessness reports."""
    seen = set()
    out = []
    for html_text in html_pages:
        for rec in parse_brh_search_results(html_text):
            url = rec["catalog_url"]
            if url in seen:
                continue
            title = rec["title"]
            if not (title_is_kdu(title) or CORE_HOMELESS_RE.search(title or "")):
                continue
            seen.add(url)
            out.append(rec)
    return out


def ingest_rechnungshof(conn, cfg, sources, notes) -> int:
    """Ingest official audit reports. Catalog first; live search only adds notes unless configured."""
    ensure_audit_tables(conn)
    stored = ingest_rechnungshof_catalog(conn, cfg, sources, notes)
    # Per-court counts for the handoff / dry-run notes.
    try:
        rows = conn.execute(
            """SELECT court_id, land, COUNT(*) AS n
               FROM institutions_media_audit
               GROUP BY 1, 2
               ORDER BY 1"""
        ).fetchall()
    except Exception:
        rows = []
    parts = [f"{row['court_id']}({row['land']})={row['n']}" for row in rows]
    if parts:
        notes.append("rechnungshof_by_court " + ", ".join(parts))
    else:
        notes.append("rechnungshof_by_court none")
    # Coverage reminder for Länder without a stored report.
    have = {row["court_id"] for row in rows}
    missing = [c["id"] + "(" + c["land"] + ")" for c in COURTS if c["id"] not in have]
    if missing:
        notes.append(
            "rechnungshof gaps (no verified on-topic official PDF stored): " + ", ".join(missing)
        )
    return stored



if __name__ == "__main__":
    from ingest.common import no_direct_run
    raise SystemExit(no_direct_run("institutions_media"))
