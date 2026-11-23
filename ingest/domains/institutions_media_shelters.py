"""Official Kältehilfe / Notunterkunft directories for institutions_media.

Public emergency and low-threshold offers published by official municipal or
Senate-commissioned sources. Frauenhaus / Schutzwohnung / other protected
shelters never store address, postcode or coordinates. Women-only, youth-only
and LGBTQ-only offers are stored at Bezirk/Stadtteil level only, with a link
to the official city page; mixed and general Notunterkünfte keep the published
street address.

This module never opens data/atlas.db and does not invent AGS codes.
"""
from __future__ import annotations

import io
import json
import re
import subprocess
import tempfile
import zipfile
from html import unescape
from urllib.parse import urljoin

from ingest import common
from ingest.common import clean, name_norm, upsert
from ingest.domains.institutions_media_rechnungshof import RESERVED_LICENCE

DOMAIN = "institutions_media"

SHELTER_DDL = """
CREATE TABLE IF NOT EXISTS institutions_media_shelter (
  official_key TEXT PRIMARY KEY,
  facility_id INTEGER,
  city TEXT,
  kind TEXT,
  operator TEXT,
  source_name TEXT,
  official_url TEXT,
  source_id INTEGER
);
"""

# Explicit Frauenhaus / secret-shelter terms. Public "Notübernachtung für Frauen"
# on an official Kältehilfe list is a notunterkunft, not a Frauenhaus.
PROTECTED_NAME_RE = re.compile(
    r"(?i)\bfrauenhaus\b|\bfrauenschutzhaus\b|\bschutzwohnung\b|"
    r"\bzuflucht(?:swohnung|shaus)\b|\bgewaltschutz(?:haus|einrichtung)\b|"
    r"\bprotected[\s-]?shelter\b"
)

# Public women-/youth-/LGBTQ-only emergency offers (not secret Frauenhäuser).
# Street, PLZ and coordinates are withheld; Bezirk/Stadtteil may be kept.
MIXED_GROUP_RE = re.compile(
    r"(?i)\bmänner\s+und\s+frauen\b|\bfrauen\s+und\s+männer\b|"
    r"\balle(?:r)?\s+geschlechter\b|\bgemischt\b"
)
WOMEN_ONLY_RE = re.compile(
    r"(?i)\bf(?:ü|ue)r(?:\s+[\w*]+){0,3}\s+frauen\*?\b|\bnur\s+frauen\*?\b|"
    r"\bausschließlich\s+frauen\b|\bfrauenobdach\b|"
    r"\bfrauennot(?:schlaf|übernacht|unterkunft)\b|"
    r"\bübernachtungsstätte\s+für\s+frauen\b|"
    r"\bfrauenzimmer\b|\bfrauenprojekte\b|\bfrauen[\s-]?wohn[\s-]?projekt\b|"
    r"\bnotschlafstellen\s+für\s+frauen\b|\bmädchen(?:not|obdach|haus)?"
)
YOUTH_ONLY_RE = re.compile(
    r"(?i)\bjugendnotschlaf(?:stelle)?\b|\bnotschlafstelle\s+für\s+junge\b|"
    r"\bfür\s+jugendliche\b|\bfür\s+junge\s+erwachsene\b|"
    r"\bfür\s+jungerwachsene\b|\bjungerwachsene\b|"
    r"\bjunge\s+wohnhilfe\b|"
    r"\b18\s*bis\s*26\b|\b18\s*[-–tobis]+\s*27\b|"
    r"\bjugend(?:lichen)?(?:not)?(?:übernacht|unterkunft|obdach)\b"
)
LGBTQ_ONLY_RE = re.compile(
    r"(?i)\blgbtq?\w*\b|\blsbt\w*\b|\bqueer\b|\bflint[aä*]?\b|"
    r"\btrans(?:gender|sexuell|\*)?\b|\bschwul[-\s]?lesbisch\b"
)

BERLIN_LIST = "https://kaeltehilfe-berlin.de/kaeltehilfe-angebot"
BERLIN_IMPRESSUM = "https://kaeltehilfe-berlin.de/impressum"
BERLIN_SENATE = (
    "https://www.berlin.de/sen/soziales/besondere-lebenssituationen/"
    "wohnungslose/notversorgung/kaeltehilfe-1293250.php"
)
HAMBURG_WFS = "https://geodienste.hamburg.de/HH_WFS_Uebernachtungsangebote"
HAMBURG_GEOJSON = (
    "https://geodienste.hamburg.de/download?"
    "url=https://geodienste.hamburg.de/HH_WFS_Uebernachtungsangebote&f=json"
)
HAMBURG_WNP = (
    "https://www.hamburg.de/politik-und-verwaltung/behoerden/sozialbehoerde/"
    "themen/soziales/obdachlosigkeit/winternotprogramm/winternotprogramm-43050"
)
MUNICH_PDF = (
    "https://stadt.muenchen.de/dam/Home/Stadtverwaltung/Sozialreferat/"
    "wohnungsamt/Wohnungslosigkeit-akut/LHM_Angebote_fuer_Obdachlose.pdf"
)
MUNICH_PAGE = "https://stadt.muenchen.de/service/info/notdienste-und-hilfen-fur-wohnungslose/10129/n0/"
COLOGNE_PAGE = "https://www.stadt-koeln.de/service/produkte/00871/index.html"

DL_DE_BY_20 = (
    "Datenlizenz Deutschland – Namensnennung – Version 2.0 (dl-de/by-2-0). "
    "Official Hamburg geodata: no access constraints stated in the WFS capabilities; "
    "dataset published by the Sozialbehörde / LGV."
)
DL_DE_BY_URL = "https://www.govdata.de/dl-de/by-2-0"
HH_ATTRIBUTION = (
    "Freie und Hansestadt Hamburg, Behörde für Gesundheit, Soziales und Integration "
    "/ Landesbetrieb Geoinformation und Vermessung"
)

KIND_FROM_FILTER = {
    "schlafplatz": "notunterkunft",
    "notschlafstelle": "notunterkunft",
    "notunterkunft": "notunterkunft",
    "notübernachtung": "notunterkunft",
    "notuebernachtung": "notunterkunft",
    "übernachtungsschutz": "notunterkunft",
    "uebernachtungsschutz": "notunterkunft",
    "frauenobdach": "notunterkunft",
    "unterkunftsheim": "shelter",
    "übernachtung": "notunterkunft",
    "uebernachtung": "notunterkunft",
    "tagestreff": "tagesaufenthalt",
    "teestube": "tagesaufenthalt",
    "tagesaufenthalt": "tagesaufenthalt",
    "nachtcafé": "tagesaufenthalt",
    "nachtcafe": "tagesaufenthalt",
    "begegnungszentrum": "tagesaufenthalt",
    "clearingstelle": "beratungsstelle",
    "fachdienst": "beratungsstelle",
    "arztpraxis": "beratungsstelle",
    "bahnhofsmission": "beratungsstelle",
    "beratung": "beratungsstelle",
}
HH_KIND = {
    "Übernachtungsstätten": "notunterkunft",
    "Tagesaufenthaltsstätte": "tagesaufenthalt",
    "Beratung & Begegnung": "beratungsstelle",
    "Wohnprojekt": "shelter",
    "Übergangswohnen": "shelter",
    "Leistung gem. §§ 67 ff SGB XII mit  vorübergehendem Wohnen": "shelter",
    "Leistung gem. §§ 67 ff SGB XII mit vorübergehendem Wohnen": "shelter",
}


def _im():
    from ingest.domains import institutions_media as module
    return module


def _fetch(url: str, *, force: bool = False) -> bytes:
    return common.fetch(url, domain=DOMAIN, force=force)


def official_slug(prefix: str, *parts: str | None) -> str:
    """Stable official_key suffix; name_norm is uppercase so the slug must fold case."""
    blob = " ".join(part for part in parts if part)
    slug = re.sub(r"[^a-z0-9]+", "-", (name_norm(blob) or "x").casefold()).strip("-")
    return f"{prefix}{slug}"


def ensure_shelter_tables(conn) -> None:
    conn.executescript(SHELTER_DDL)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(institutions_media_shelter)")}
    if "district" not in cols:
        conn.execute("ALTER TABLE institutions_media_shelter ADD COLUMN district TEXT")
    if "location_precision" not in cols:
        conn.execute("ALTER TABLE institutions_media_shelter ADD COLUMN location_precision TEXT")
    _im().ensure_source_extensions(conn)


def is_protected_shelter(kind: str | None, *parts: str | None) -> bool:
    kind_c = (kind or "").casefold()
    if kind_c in _im().PROTECTED_KINDS:
        return True
    hay = " ".join(part or "" for part in parts)
    return bool(PROTECTED_NAME_RE.search(hay))


_LEAD_GROUP_RE = re.compile(
    r"(?i)(?<!lieb)frauen|m[äa]dchen|jugend|jungerwachsen|junge\s+(menschen|erwachsene|frauen|m[äa]nner|wohnhilfe)|minderj[äa]hrig|"
    r"queer|lgbt|lsbt|\btrans\b|trans\*|transgender|schwul|lesb|non-?bin[äa]r|nicht-?bin[äa]r|\binter\*")


def is_restricted_group_shelter(*parts: str | None) -> bool:
    """Women-only, youth-only or LGBTQ-only public offers (not mixed)."""
    hay = " ".join(part or "" for part in parts)
    if not hay or MIXED_GROUP_RE.search(hay):
        return False
    return bool(WOMEN_ONLY_RE.search(hay) or YOUTH_ONLY_RE.search(hay) or LGBTQ_ONLY_RE.search(hay))


def extract_district(rec: dict) -> str | None:
    """Bezirk/Stadtteil as published by the official source, never a street."""
    if clean(rec.get("district")):
        return clean(rec.get("district"))
    note = rec.get("population_note") or ""
    m = re.search(r"Bezirk\s+([^·,;|]+)", note, re.I)
    if m:
        return clean(m.group(1))
    address = rec.get("address") or ""
    m = re.search(r"Köln-([A-Za-zÄÖÜäöüß][A-Za-zÄÖÜäöüß/\-]*)", address)
    if m:
        return clean("Köln-" + m.group(1))
    name = rec.get("name") or ""
    # Official name sometimes includes a Stadtteil (e.g. Wilhelmsburg).
    m = re.search(r"\b(Wilhelmsburg|Kreuzberg|Neukölln|Moabit)\b", name, re.I)
    if m:
        return m.group(1)
    return None


def kind_from_text(*parts: str | None) -> str:
    hay = " ".join(part or "" for part in parts).casefold()
    for needle, kind in KIND_FROM_FILTER.items():
        if needle in hay:
            return kind
    if "wohnprojekt" in hay or "übergangswohnen" in hay or "67" in hay:
        return "shelter"
    return "other"


def extract_beds(*parts: str | None) -> int | None:
    hay = " ".join(part or "" for part in parts)
    matches = re.findall(r"(?<!\d)(\d{1,4})\s*(?:plätze|plaetze|bettplätze|bettplaetze|betten)\b", hay, re.I)
    if not matches:
        return None
    value = int(matches[0])
    return value if 0 < value < 5000 else None


def extract_plz_city(address: str | None, default_city: str | None = None) -> tuple[str | None, str | None]:
    text = clean(address)
    if not text:
        return None, default_city
    m = re.search(r"\b(\d{5})\s+([A-ZÄÖÜa-zäöüß][^,]*)", text)
    if not m:
        return None, default_city
    city = clean(re.split(r"[-,]", m.group(2))[0])
    return m.group(1), city or default_city


def parse_point(geom) -> tuple[float | None, float | None]:
    if isinstance(geom, dict):
        coords = geom.get("coordinates")
        if isinstance(coords, (list, tuple)) and len(coords) >= 2:
            try:
                lon, lat = float(coords[0]), float(coords[1])
                if -90 <= lat <= 90 and -180 <= lon <= 180:
                    return lat, lon
            except (TypeError, ValueError):
                return None, None
    if isinstance(geom, str):
        m = re.search(r"POINT\s*\(\s*([+-]?\d+(?:\.\d+)?)\s+([+-]?\d+(?:\.\d+)?)\s*\)", geom, re.I)
        if m:
            try:
                lon, lat = float(m.group(1)), float(m.group(2))
                if -90 <= lat <= 90 and -180 <= lon <= 180:
                    return lat, lon
            except ValueError:
                return None, None
    return None, None


def _field_map(block: str) -> dict[str, str]:
    fields = {}
    for m in re.finditer(
        r'class="field-entry\s+([^"]+)"[^>]*>.*?class="field-value\s*"[^>]*>(.*?)</span>',
        block,
        re.S | re.I,
    ):
        key = clean(m.group(1))
        val = clean(re.sub(r"<[^>]+>", " ", unescape(m.group(2))))
        if key and val:
            fields[key] = val
    return fields


def parse_berlin_kaeltehilfe(html_text: str, *, page_url: str) -> list[dict]:
    rows = []
    for m in re.finditer(
        r'<(?:article|div)\b[^>]*typeof="Article"[^>]*>(.*?)</(?:article|div)>',
        html_text or "",
        re.S | re.I,
    ):
        block = m.group(1)
        href_m = re.search(r'<a[^>]+href="([^"]+)"[^>]*>\s*([^<]+)\s*</a>', block, re.I)
        if not href_m:
            continue
        href = unescape(href_m.group(1)).strip()
        name = clean(unescape(href_m.group(2)))
        if not name or not href:
            continue
        url = urljoin("https://kaeltehilfe-berlin.de/", href)
        fields = _field_map(block)
        kind = kind_from_text(fields.get("filter"), fields.get("kategorie"), fields.get("symbol"), name)
        rec = {
            "official_key": official_slug("BE-KH:", name, url),
            "name": name,
            "kind": kind,
            "operator": fields.get("traeger"),
            "address": fields.get("adresse"),
            "city": "Berlin",
            "land": "BE",
            "official_url": url,
            "source_url": BERLIN_LIST,
            "source_name": "berlin_kaeltehilfe",
            "district": clean(fields.get("bezirk")),
            "population_note": clean(" · ".join(
                part for part in (
                    ("Bezirk " + fields["bezirk"]) if fields.get("bezirk") else None,
                    fields.get("oeffnungszeiten"),
                    fields.get("geschlecht"),
                ) if part
            )),
            "beds": extract_beds(fields.get("beschreibung"), fields.get("besonderes")),
        }
        plz, city = extract_plz_city(fields.get("adresse"), "Berlin")
        rec["plz"] = plz
        if city:
            rec["city"] = city
        try:
            rec["lat"] = float(fields["latitude"].replace(",", ".")) if fields.get("latitude") else None
            rec["lon"] = float(fields["longitude"].replace(",", ".")) if fields.get("longitude") else None
        except ValueError:
            rec["lat"] = rec["lon"] = None
        rec["website"] = fields.get("webseite")
        rows.append(rec)
    return rows


def parse_hamburg_geojson(data: bytes) -> list[dict]:
    payload = data
    if data.startswith(b"PK"):
        zf = zipfile.ZipFile(io.BytesIO(data))
        name = next(
            (n for n in zf.namelist() if n.endswith("EPSG_4326.json") or n.endswith("EPSG_4326.geojson")),
            None,
        )
        if not name:
            name = next((n for n in zf.namelist() if n.endswith(".json") and "25832" not in n), None)
        if not name:
            return []
        payload = zf.read(name)
    obj = json.loads(payload)
    rows = []
    for feat in obj.get("features") or []:
        props = feat.get("properties") or {}
        name = clean(props.get("einrichtungsname"))
        if not name:
            continue
        art = clean(props.get("art"))
        kind = HH_KIND.get(art, kind_from_text(art, name))
        address = clean(props.get("adresse"))
        ort = clean(props.get("ort")) or "Hamburg"
        plz, city = extract_plz_city(ort, "Hamburg")
        if not plz:
            plz, city = extract_plz_city(address, "Hamburg")
        lat = lon = None
        lat, lon = parse_point(feat.get("geometry"))
        if lat is None:
            lat, lon = parse_point(props.get("geom"))
        beds = None
        try:
            if props.get("plaetze") not in (None, ""):
                beds = int(float(str(props.get("plaetze")).replace(",", ".")))
        except ValueError:
            beds = extract_beds(str(props.get("plaetze") or ""), name)
        rows.append({
            "official_key": official_slug("HH-OD:", name, address, ort),
            "name": name,
            "kind": kind,
            "address": ", ".join(part for part in (address, ort) if part),
            "plz": plz,
            "city": city or "Hamburg",
            "land": "HH",
            "lat": lat,
            "lon": lon,
            "beds": beds if beds and 0 < beds < 5000 else None,
            "official_url": HAMBURG_WFS,
            "source_url": HAMBURG_GEOJSON,
            "source_name": "hamburg_opendata",
            "population_note": clean(" · ".join(part for part in (art, clean(props.get("zusatzinfo"))) if part)),
        })
    return rows


def _compact_lines(html_text: str) -> list[str]:
    text = re.sub(r"<script[\s\S]*?</script>|<style[\s\S]*?</style>", " ", html_text or "", flags=re.I)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"</(?:p|div|li|h[1-6]|tr|section|article)>", "\n", text, flags=re.I)
    text = unescape(re.sub(r"<[^>]+>", " ", text))
    lines = [clean(re.sub(r"[ \t]+", " ", ln)) for ln in text.splitlines()]
    return [ln for ln in lines if ln]


def parse_cologne_notschlafstellen(html_text: str) -> list[dict]:
    """Official Stadt Köln product page: one offer per 'Weitere Informationen …' block."""
    lines = _compact_lines(html_text)
    info_re = re.compile(
        r"^Weitere Informationen (?:über (?:das|die|den) |zum Angebot des )(.+)$",
        re.I,
    )
    plz_re = re.compile(r"^(\d{5})\s+(Köln\S*)$")
    street_re = re.compile(
        r"^([A-ZÄÖÜ][A-Za-zÄÖÜäöüß. \-]+)\s+(\d+[a-zA-Z]?(?:\s*-\s*\d+[a-zA-Z]?)?)$"
    )
    org_re = re.compile(
        r"e\.\s*V\.|gGmbH|Stiftung|Diakonie|Sozialdienst|Johannesbund|"
        r"Don-Bosco|Spiritaner|Caritas|Stadt Köln",
        re.I,
    )
    heading_re = re.compile(r"^(Notschlafstellen?(?: für| \().+)$", re.I)
    headings = [(idx, ln) for idx, ln in enumerate(lines) if heading_re.match(ln)]
    rows = []
    seen = set()
    for i, line in enumerate(lines):
        info = info_re.match(line)
        if not info:
            continue
        name = clean(info.group(1))
        if not name:
            continue
        street = plz = city_part = operator = group = None
        for j in range(i - 1, max(-1, i - 12), -1):
            plz_m = plz_re.match(lines[j])
            if plz_m and j > 0 and street_re.match(lines[j - 1]):
                plz = plz_m.group(1)
                city_part = plz_m.group(2)
                street = clean(lines[j - 1])
                for k in range(j - 2, max(-1, j - 10), -1):
                    cand = lines[k]
                    if org_re.search(cand):
                        operator = operator or cand
                break
        if not street or not plz:
            continue
        earlier = [ln for idx, ln in headings if idx < i]
        group = earlier[-1] if earlier else None
        district = None
        if city_part and city_part.startswith("Köln-"):
            district = clean(city_part)
        key = official_slug("K-N:", name, street, plz)
        if key in seen:
            continue
        seen.add(key)
        rows.append({
            "official_key": key,
            "name": name,
            "kind": "notunterkunft",
            "operator": operator,
            "address": f"{street}, {plz} {city_part}",
            "plz": plz,
            "city": "Köln",
            "land": "NW",
            "district": district,
            "official_url": COLOGNE_PAGE,
            "source_url": COLOGNE_PAGE,
            "source_name": "koeln_notschlafstellen",
            "population_note": group,
        })
    return rows


def pdf_to_text(data: bytes) -> str:
    with tempfile.NamedTemporaryFile(suffix=".pdf") as handle:
        handle.write(data)
        handle.flush()
        proc = subprocess.run(
            ["pdftotext", "-layout", handle.name, "-"],
            capture_output=True,
            check=False,
        )
        return (proc.stdout or b"").decode("utf-8", "replace")


def parse_munich_offers(text: str) -> list[dict]:
    """Pull official address blocks from the city PDF (Stand August 2026)."""
    # A street is one compound *straße token, or one proper name plus Straße/Str.
    addr_re = re.compile(
        r"((?:[A-ZÄÖÜ][A-Za-zÄÖÜäöüß.\-]+(?:straße|strasse|str\.|platz|weg|ring|gasse|allee|ufer|hof))"
        r"|(?:[A-ZÄÖÜ][A-Za-zÄÖÜäöüß.\-]+\s+(?:Straße|Strasse|Str\.|Platz|Weg|Ring|Gasse|Allee|Ufer|Hof)))"
        r"\s+(\d+[a-z]?(?:\s*(?:bis|-|–)\s*\d+[a-z]?)?)"
        r"\s*,?\s*(?:[^\n]{0,40}\n)?[^\n\d]{0,40}(8\d{4})\s+München",
        re.I,
    )
    offer_re = re.compile(
        r"(?<![A-Za-zÄÖÜäöüß])"
        r"(Amt für|Abt\.|Schiller|FamAra|Teestube|Tagestreff|Obdachlosenhilfe|"
        r"Frauenobdach|Bahnhofsmission|Unterkunftsheim|Arztpraxis|open\.med|"
        r"Malteser Medizin|Clearingstelle|Fachdienst|Beratungsstelle|"
        r"Begegnungszentrum|Wärmebus|Behandlungsbus|Übernachtungsschutz|"
        r"Haus an der)",
        re.I,
    )
    skip_hours = re.compile(
        r"Telefon|E-Mail|Öffnungszeiten|Erreichbarkeit|Stand:|^Tel\.|Mobil:|^Fax:|"
        r"Montag|Dienstag|Mittwoch|Donnerstag|Freitag|Samstag|Sonntag|"
        r"^Täglich|^rund um|Sprechstunden",
        re.I,
    )
    org_re = re.compile(
        r"Landeshauptstadt München|Hilfswerk München|Benediktinerabtei|"
        r"IN VIA|Männerfürsorgeverein|Ärzte der Welt|Malteser|"
        r"Condrobs|Sozialdienst Katholischer Frauen|Beratungsdienst|"
        r"Caritas|Projekteverein|gGmbH|e\.\s*V\.",
        re.I,
    )
    name_prefix = re.compile(
        r"^(?:Evangelisches(?:\s+Hilfswerk(?:\s+München)?)?|Landeshauptstadt|"
        r"Katholischer(?:\s+Verband)?|Gemeinnützige GmbH(?:\s+des Projektevereins)?|"
        r"Benediktinerabtei(?:\s+St\.\s+Bonifaz)?|IN VIA München e\.\s*V\.|"
        r"Ärzte der Welt e\.\s*V\.|Condrobs e\.\s*V\.|"
        r"Sozialdienst(?:\s+Katholischer Frauen)?|Evangelischer|München)\s+",
        re.I,
    )
    strong = re.compile(
        r"Frauenobdach|Teestube|Tagestreff|FamAra|Schiller|Bahnhofsmission|"
        r"open\.med|Clearingstelle|Haneberghaus|Unterkunftsheim|Begegnungszentrum|"
        r"Fachdienst|Amt für|Malteser Medizin|Obdachlosenhilfe|"
        r"Übernachtungsschutz|Haus an der",
        re.I,
    )

    def title_score(line: str) -> int:
        if skip_hours.search(line) or "@" in line or "http" in line.casefold():
            return 0
        if re.match(r"^(?:und |mit |im |für |•)", line, re.I):
            return 0
        if strong.search(line):
            return 3
        if offer_re.search(line):
            return 1
        return 0

    rows = []
    seen_addr = set()
    last_end = 0
    for m in addr_re.finditer(text or ""):
        street = clean(f"{m.group(1)} {m.group(2)}")
        plz = m.group(3)
        addr_key = official_slug("", street, plz)
        window = text[last_end:m.start()]
        last_end = m.end()
        window_lines = [clean(ln) for ln in window.splitlines() if clean(ln)]
        titles = [(title_score(ln), ln) for ln in window_lines if title_score(ln) > 0]
        if titles and re.search(r"Wärmebus|Behandlungsbus", titles[-1][1], re.I):
            continue
        if addr_key in seen_addr:
            continue
        name = None
        if titles:
            strong_titles = [ln for s, ln in titles if s >= 3]
            name = strong_titles[0] if strong_titles else titles[0][1]
        if not name:
            continue
        name = clean(name_prefix.sub("", name)) or name
        name = re.sub(r"(Malteser Medizin für)\s+\1", r"\1", name)
        # Prefer a longer official title that contains a short heading (e.g. D3).
        if name and titles:
            longer = next((ln for s, ln in titles if s >= 3 and name in ln and len(ln) > len(name) + 8), None)
            if longer:
                name = clean(name_prefix.sub("", longer)) or longer
        name = name.replace("Malteser Medizin für Malteser Medizin für", "Malteser Medizin für")
        if re.search(r"Wärmebus|Behandlungsbus", name, re.I):
            continue
        seen_addr.add(addr_key)
        operator = None
        for ln in window_lines:
            if "@" in ln or skip_hours.search(ln) or re.search(r"(?:straße|str\.)\s+\d", ln, re.I):
                continue
            if org_re.search(ln):
                operator = clean(ln)
                if (
                    len(operator) > 90
                    or operator.casefold().startswith("erfolgt")
                    or "durch die" in operator.casefold()
                ):
                    continue
                operator = clean(name_prefix.sub("", operator)) or operator
                if len(operator) > 80:
                    operator = operator[:80].rsplit(" ", 1)[0]
                break
        kind = kind_from_text(name)
        if kind == "other" and re.search(r"amt für|abt\.|medizin|obdachlosenhilfe", name, re.I):
            kind = "beratungsstelle" if re.search(r"amt für|abt\.|medizin", name, re.I) else "tagesaufenthalt"
        title_blob = " ".join(ln for _, ln in titles)
        if "übernachtungsschutz" in (name + " " + title_blob).casefold() or "frauenobdach" in name.casefold():
            kind = "notunterkunft"
        if any("unterkunftsheim" in ln.casefold() for _, ln in titles):
            kind = "shelter"
        if "open.med" in name.casefold():
            kind = "beratungsstelle"
        rows.append({
            "official_key": official_slug("M-PDF:", name, street, plz),
            "name": name,
            "kind": kind,
            "operator": operator,
            "address": f"{street}, {plz} München",
            "plz": plz,
            "city": "München",
            "land": "BY",
            "official_url": MUNICH_PDF,
            "source_url": MUNICH_PDF,
            "source_name": "muenchen_angebote_pdf",
        })
    return rows




# Official Kreisschlüssel of the kreisfreie Stadt whose directory we read.
# City-level only; never a Bezirk or Ortsteil. Restricted-group official offers may
# keep this city-level key. Protected (is_protected=1) rows must not store any AGS.
CITY_KREIS_AGS = {
    ("Berlin", "BE"): "11000",
    ("Hamburg", "HH"): "02000",
    ("München", "BY"): "09162",
    ("Köln", "NW"): "05315",
    # Extra official city lists (i); kreisfreie Stadt / Region keys, not Ortsteile.
    ("Bremen", "HB"): "04011",
    ("Dortmund", "NW"): "05913",
    ("Dresden", "SN"): "14612",
    ("Düsseldorf", "NW"): "05111",
    ("Essen", "NW"): "05113",
    ("Frankfurt am Main", "HE"): "06412",
    ("Hannover", "NI"): "03241",  # Stadt Hannover lies in Region Hannover
    ("Leipzig", "SN"): "14713",
    ("Nürnberg", "BY"): "09564",
    ("Stuttgart", "BW"): "08111",
}


def official_city_kreis_ags(city: str | None, land: str | None) -> str | None:
    """Kreis AGS when the official source is that city's own list; no name lookup, no guessing."""
    if not city or not land:
        return None
    return CITY_KREIS_AGS.get((city.strip(), land.strip()))

def store_official_facility(conn, rec: dict, *, sources) -> bool:
    ensure_shelter_tables(conn)
    name = clean(rec.get("name"))
    land = rec.get("land") if rec.get("land") in _im().LANDS else None
    source_url = clean(rec.get("source_url") or rec.get("official_url"))
    licence = clean(rec.get("license"))
    official_key = clean(rec.get("official_key"))
    kind = clean(rec.get("kind")) or "other"
    if not name or not name_norm(name) or not land or not source_url or not licence or not official_key:
        return False
    protected = is_protected_shelter(kind, name, rec.get("operator"), rec.get("population_note"))
    restricted = (not protected) and is_restricted_group_shelter(
        name, rec.get("operator"), rec.get("population_note"), rec.get("district"),
    )
    if (
        not protected and not restricted
        and (_LEAD_GROUP_RE.search(name or "") or _LEAD_GROUP_RE.search(rec.get("operator") or ""))
        and not MIXED_GROUP_RE.search(name or "")
    ):
        # Lead, 2026-11-21: a target-group word in the published name or operator
        # (e.g. "Jugendhilfe e.V.") is treated as restricted too, matching verify G8;
        # over-protection is the safe side. Mixed wording in the target-group note
        # must not keep a street address when the operator itself is a youth service.
        restricted = True
    if protected:
        kind = kind if kind in _im().PROTECTED_KINDS else "protected_shelter"
    district = None if protected else extract_district(rec)
    coarse = protected or restricted
    address = None if coarse else clean(rec.get("address"))
    plz = None if coarse else clean(rec.get("plz"))
    lat = lon = None
    if not coarse:
        try:
            lat = float(rec["lat"]) if rec.get("lat") is not None else None
            lon = float(rec["lon"]) if rec.get("lon") is not None else None
        except (TypeError, ValueError):
            lat = lon = None
    official_url = clean(rec.get("official_url")) or source_url
    note_bits = [clean(rec.get("population_note"))]
    if restricted and district:
        note_bits.insert(0, "Ortsebene: " + district)
    elif restricted:
        note_bits.insert(0, "Ortsebene: Stadt (keine offizielle Bezirk/Stadtteil-Angabe)")
    population_note = clean(" · ".join(bit for bit in note_bits if bit))
    if protected:
        precision = "protected"
    elif restricted:
        precision = "district"
    else:
        precision = "street"
    if restricted and not official_url:
        return False
    source_id = _im()._register_source(
        conn, source_url,
        title=rec.get("source_title") or name,
        publisher=rec.get("publisher") or "official directory",
        license_=licence,
        bucket=sources,
        license_url=clean(rec.get("license_url")),
        attribution=clean(rec.get("attribution")),
        notes=clean(rec.get("source_notes")),
        redistribute_fulltext=0 if rec.get("redistribute_fulltext") == 0 else 1,
    )
    upsert(conn, "facility", {
        "name": name,
        "name_norm": name_norm(name),
        "kind": kind,
        "betriebsstatus": clean(rec.get("status")) or "active",
        "betten": rec.get("beds"),
        "traeger": clean(rec.get("operator")),
        "land": land,
        "kreis_ags": None if protected else official_city_kreis_ags(rec.get("city"), land),
        "ort": clean(rec.get("city")),
        "anschrift": address,
        "plz": plz,
        "lat": lat,
        "lon": lon,
        "is_protected": 1 if protected else 0,
        "zielgruppe": population_note,
        "source_id": source_id,
        "is_est": 0,
    }, ["name_norm", "land", "ort"])
    row = conn.execute(
        "SELECT id FROM facility WHERE name_norm=? AND land=? AND ifnull(ort,'')=ifnull(?, '')",
        (name_norm(name), land, clean(rec.get("city"))),
    ).fetchone()
    if not row:
        return False
    if coarse:
        # Lead 2026-11-23: upsert never overwrites with NULL, so an address stored by an earlier run
        # survived the city/district coarsening. Clear it explicitly for restricted/protected offers.
        conn.execute(
            "UPDATE facility SET anschrift=NULL, plz=NULL, lat=NULL, lon=NULL WHERE id=? AND "
            "(anschrift IS NOT NULL OR plz IS NOT NULL OR lat IS NOT NULL OR lon IS NOT NULL)",
            (row["id"],),
        )
    upsert(conn, "institutions_media_shelter", {
        "official_key": official_key,
        "facility_id": row["id"],
        "city": clean(rec.get("city")),
        "kind": kind,
        "operator": clean(rec.get("operator")),
        "source_name": clean(rec.get("source_name")),
        "official_url": official_url,
        "district": district,
        "location_precision": precision,
        "source_id": source_id,
    }, ["official_key"])
    return True


def _source_kwargs(name: str) -> dict:
    if name == "berlin_kaeltehilfe":
        return {
            "license": RESERVED_LICENCE,
            "license_url": BERLIN_IMPRESSUM,
            "attribution": "Koordinierungsstelle der Berliner Kältehilfe / Senatsverwaltung für Soziales",
            "publisher": "Koordinierungsstelle der Berliner Kältehilfe",
            "source_title": "Angebote der Berliner Kältehilfe",
            "source_notes": "Official Senate-commissioned directory; imprint reserves copyright",
            "redistribute_fulltext": 0,
        }
    if name == "hamburg_opendata":
        return {
            "license": DL_DE_BY_20,
            "license_url": DL_DE_BY_URL,
            "attribution": HH_ATTRIBUTION,
            "publisher": "Behörde für Gesundheit, Soziales und Integration, Hamburg",
            "source_title": "Übernachtungs- und Versorgungsangebote für obdachlose und wohnungslose Menschen Hamburg",
            "source_notes": "Official open geodata, WFS access unconstrained",
            "redistribute_fulltext": 1,
        }
    if name == "muenchen_lhm_pdf":
        return {
            "license": RESERVED_LICENCE,
            "license_url": MUNICH_PAGE,
            "attribution": "Landeshauptstadt München, Sozialreferat / Amt für Wohnen und Migration",
            "publisher": "Landeshauptstadt München",
            "source_title": "Angebote für obdachlose Menschen in München (Stand August 2026)",
            "source_notes": "Official city PDF; no open reuse licence found on the publication page",
            "redistribute_fulltext": 0,
        }
    if name == "koeln_notschlafstellen":
        return {
            "license": RESERVED_LICENCE,
            "license_url": COLOGNE_PAGE,
            "attribution": "Stadt Köln",
            "publisher": "Stadt Köln",
            "source_title": "Notschlafstellen der Stadt Köln",
            "source_notes": "Official municipal product page; imprint page returned HTTP 403 from this environment",
            "redistribute_fulltext": 0,
        }
    raise ValueError(name)


def ingest_berlin(conn, cfg, sources, notes) -> int:
    force = bool(cfg.get("force"))
    stored = 0
    seen = set()
    start = 0
    empty = 0
    while start <= 80:
        url = BERLIN_LIST if start == 0 else f"{BERLIN_LIST}?start={start}"
        try:
            raw = _fetch(url, force=force)
        except Exception as exc:
            notes.append(f"Berlin Kältehilfe page start={start} failed: {type(exc).__name__}")
            break
        html = raw.decode("utf-8", "replace")
        recs = parse_berlin_kaeltehilfe(html, page_url=url)
        if not recs:
            empty += 1
            if empty >= 2 or start > 0:
                break
        new = 0
        for rec in recs:
            if rec["official_key"] in seen:
                continue
            seen.add(rec["official_key"])
            rec.update(_source_kwargs("berlin_kaeltehilfe"))
            rec["source_url"] = url   # Lead: the exact archived page this offer was read from
            if store_official_facility(conn, rec, sources=sources):
                stored += 1
                new += 1
        if start == 0 and not recs:
            notes.append("Berlin Kältehilfe list page produced no offers")
            break
        start += 5
    notes.append(f"Berlin Kältehilfe stored={stored} official offers from kaeltehilfe-berlin.de")
    return stored


def ingest_hamburg(conn, cfg, sources, notes) -> int:
    force = bool(cfg.get("force"))
    try:
        raw = _fetch(HAMBURG_GEOJSON, force=force)
    except Exception as exc:
        notes.append(f"Hamburg open-data GeoJSON failed: {type(exc).__name__}: {str(exc)[:160]}")
        return 0
    recs = parse_hamburg_geojson(raw)
    stored = 0
    for rec in recs:
        rec.update(_source_kwargs("hamburg_opendata"))
        rec["source_url"] = HAMBURG_GEOJSON   # Lead: cite the archived download, link the official WFS
        rec["official_url"] = HAMBURG_WFS
        if store_official_facility(conn, rec, sources=sources):
            stored += 1
    notes.append(f"Hamburg official open data stored={stored} offers (Sozialbehörde / LGV GeoJSON)")
    return stored


def ingest_munich(conn, cfg, sources, notes) -> int:
    force = bool(cfg.get("force"))
    try:
        raw = _fetch(MUNICH_PDF, force=force)
    except Exception as exc:
        notes.append(f"Munich official PDF failed: {type(exc).__name__}")
        return 0
    if not (raw.lstrip().startswith(b"%PDF")):
        notes.append("Munich official PDF was not a PDF")
        return 0
    recs = parse_munich_offers(pdf_to_text(raw))
    stored = 0
    for rec in recs:
        rec.update(_source_kwargs("muenchen_lhm_pdf"))
        if store_official_facility(conn, rec, sources=sources):
            stored += 1
    notes.append(f"München official city PDF stored={stored} address-level offers (Stand August 2026)")
    return stored


def ingest_cologne(conn, cfg, sources, notes) -> int:
    force = bool(cfg.get("force"))
    try:
        raw = _fetch(COLOGNE_PAGE, force=force)
    except Exception as exc:
        notes.append(f"Cologne official Notschlafstellen page failed: {type(exc).__name__}")
        return 0
    recs = parse_cologne_notschlafstellen(raw.decode("utf-8", "replace"))
    stored = 0
    for rec in recs:
        rec.update(_source_kwargs("koeln_notschlafstellen"))
        if store_official_facility(conn, rec, sources=sources):
            stored += 1
    notes.append(f"Köln official Notschlafstellen stored={stored}")
    return stored


def ingest_shelters(conn, cfg, sources, notes) -> int:
    ensure_shelter_tables(conn)
    skip = set(cfg.get("skip") or [])
    stored = 0
    if "berlin" not in skip:
        stored += ingest_berlin(conn, cfg, sources, notes)
    if "hamburg" not in skip:
        stored += ingest_hamburg(conn, cfg, sources, notes)
    if "munich" not in skip:
        stored += ingest_munich(conn, cfg, sources, notes)
    if "cologne" not in skip:
        stored += ingest_cologne(conn, cfg, sources, notes)
    if "more_cities" not in skip:
        from ingest.domains.institutions_media_shelters_more import ingest_more_city_shelters
        stored += ingest_more_city_shelters(conn, cfg, sources, notes)
    notes.append(
        "Kältehilfe gaps: Frankfurt official pages were retried once and are recorded "
        "in the more-cities ingest notes (historically HTTP 403). "
        "No official open-data Kältehilfe export was found on daten.berlin.de (the Senate points to "
        "kaeltehilfe-berlin.de). "
        "Landesarbeitsgemeinschaften Wohnungslosenhilfe are not in a single official national directory "
        "and were not added this pass."
    )
    return stored



if __name__ == "__main__":
    from ingest.common import no_direct_run
    raise SystemExit(no_direct_run("institutions_media"))
