"""Official Land Krankenhausplan psychiatric beds by hospital and Fachabteilung.

Land totals are always stored as AGS metrics. Per-hospital figures are linked
to a Wikidata facility only when the official hospital name uniquely matches a
psychiatric facility already in the database in the same Land. Quotes are taken
from the unmodified pdftotext -layout archive. No beds are guessed.
"""

from __future__ import annotations

import re

from ingest.common import clean, document_text, fetch, name_norm, raw_path, upsert
from ingest.domains.institutions_media_press import press_robots_status
from ingest.domains.institutions_media_rechnungshof import RESERVED_LICENCE, quote_in_text, trim_quote

DOMAIN = "institutions_media"

METRIC_PSY = "khplan_psych_beds"
METRIC_KJP = "khplan_kjp_beds"
METRIC_PSM = "khplan_psm_beds"
METRIC_PSY_DAY = "khplan_psych_day_places"
METRIC_KJP_DAY = "khplan_kjp_day_places"
METRIC_PSM_DAY = "khplan_psm_day_places"

SERIES_HH = "Krankenhausplan Hamburg, Betten-Soll 01.01.2026 (Einzelblätter der Fachgebiete)"
SERIES_NI = "Krankenhausplan Niedersachsen, betriebene Planbetten zum 01.01.2024"

AMTLICH = RESERVED_LICENCE
AMTSBLATT_LICENCE = (
    "Amtliches Werk, § 5 Abs. 1 UrhG: im Amtsblatt für Brandenburg amtlich bekanntgemacht; "
    "zitiert mit Fundstelle"
)

SERIES_BW = (
    "Krankenhausplan Baden-Württemberg 2026, landesweiter Bedarf 2025 "
    "Psychosomatische Medizin und Psychotherapie"
)
SERIES_BE = (
    "Krankenhausplan 2020 des Landes Berlin, prognostizierter gesamtstädtischer "
    "Bedarf 2025 (Betten/Plätze, nicht nach voll- und teilstationär getrennt)"
)
SERIES_BB = (
    "Vierter Krankenhausplan des Landes Brandenburg, Festlegungen 4. KH-Plan "
    "(Amtsblatt für Brandenburg Nr. 28 Ausgabe S vom 23. Juli 2021)"
)

BW_URL = (
    "https://sozialministerium.baden-wuerttemberg.de/fileadmin/redaktion/m-sm/intern/"
    "downloads/Downloads_Krankenhaeuser/Krankenhausplan-BW.pdf"
)
BE_URL = (
    "https://www.berlin.de/sen/gesundheit/gesundheitswesen/medizinische-versorgung/"
    "stationaere-versorgung/krankenhausplan/krankenhauplan_2020.pdf"
)
BB_URL = (
    "https://bravors.brandenburg.de/sixcms/media.php/66/"
    "28S-21%20-%20Seiten%20%20620-59%20-%20620-152.pdf"
)
BW_IMPRESSUM = "https://sozialministerium.baden-wuerttemberg.de/de/header-und-footer/impressum"
BE_IMPRESSUM = "https://www.berlin.de/rbmskzl/impressum/"
BB_IMPRESSUM = "https://bravors.brandenburg.de/de/impressum"


HH_URL = (
    "https://dokumente.hamburg.de/resource/blob/1153620/"
    "885b3af687957b1f147b6a9f7d26ff77/krankenhaus-einzelblaetter-01-2026-data.pdf"
)
NI_URL = "https://www.ms.niedersachsen.de/download/215740"

SOURCES = {
    "hh_kh2026": {
        "url": HH_URL,
        "title": "Einzelblätter der Krankenhäuser zu den Feststellungsbescheiden zum Stand 01.01.2026, Planperiode 2021 bis 2026 (redaktionell korrigierte Fassung)",
        "publisher": "Freie und Hansestadt Hamburg, Behörde für Arbeit, Gesundheit, Soziales, Familie und Integration",
        "published": "2026-01-01",
        "license": RESERVED_LICENCE,
        "license_url": "https://www.hamburg.de/impressum/",
        "attribution": "Freie und Hansestadt Hamburg, Krankenhausplan 2020, Zwischenfortschreibung, Stand 01.01.2026",
        "land": "HH",
    },
    "ni_kh2024": {
        "url": NI_URL,
        "title": "Krankenhausplanbetten / teilstationäre Plätze nach Fachrichtungen, Stand 1. Januar 2024 (Niedersächsisches Ministerium für Soziales, Arbeit, Gesundheit und Gleichstellung)",
        "publisher": "Niedersächsisches Ministerium für Soziales, Arbeit, Gesundheit und Gleichstellung",
        "published": "2024-01-01",
        "license": RESERVED_LICENCE,
        "license_url": "https://www.ms.niedersachsen.de/impressum/",
        "attribution": "Niedersächsisches Ministerium für Soziales, Arbeit, Gesundheit und Gleichstellung, Krankenhausplan, Stand 01.01.2024",
        "land": "NI",
    },
    "bw_kh2026": {
        "url": BW_URL,
        "title": "Krankenhausplan Baden-Württemberg 2026",
        "publisher": "Ministerium für Soziales, Gesundheit und Integration Baden-Württemberg",
        "published": "2026",
        "license": RESERVED_LICENCE,
        "license_url": BW_IMPRESSUM,
        "attribution": "Ministerium für Soziales, Gesundheit und Integration Baden-Württemberg, Krankenhausplan 2026",
        "land": "BW",
    },
    "be_kh2020": {
        "url": BE_URL,
        "title": "Krankenhausplan 2020 des Landes Berlin (Senatsbeschluss 14.09.2021)",
        "publisher": "Senatsverwaltung für Gesundheit, Pflege und Gleichstellung Berlin",
        "published": "2021-09-14",
        "license": RESERVED_LICENCE,
        "license_url": BE_IMPRESSUM,
        "attribution": "Senatsverwaltung für Gesundheit, Pflege und Gleichstellung, Krankenhausplan 2020 des Landes Berlin",
        "land": "BE",
    },
    "bb_kh4": {
        "url": BB_URL,
        "title": "Tabellenteil zum Vierten Krankenhausplan des Landes Brandenburg, Amtsblatt für Brandenburg Nr. 28 (Ausgabe S) vom 23. Juli 2021, Seiten 620/59–620/152",
        "publisher": "Ministerium für Soziales, Gesundheit, Integration und Verbraucherschutz des Landes Brandenburg",
        "published": "2021-07-23",
        "license": AMTSBLATT_LICENCE,
        "license_url": BB_IMPRESSUM,
        "attribution": "Amtsblatt für Brandenburg Nr. 28 (Ausgabe S) vom 23. Juli 2021, Tabellenteil Vierter Krankenhausplan",
        "land": "BB",
    },
}

FACHGEBIET_METRIC = {
    ("390", "beds"): METRIC_KJP,
    ("820", "beds"): METRIC_PSY,
    ("830", "beds"): METRIC_PSM,
    ("390", "places"): METRIC_KJP_DAY,
    ("820", "places"): METRIC_PSY_DAY,
    ("830", "places"): METRIC_PSM_DAY,
}

FACHGEBIET_LABEL = {
    "390": "Kinder- und Jugendpsychiatrie",
    "820": "Psychiatrie und Psychotherapie",
    "830": "Psychosomatische Medizin und Psychotherapie",
}

_HOSPITAL_RE = re.compile(
    r"^(?P<code>\d+)\s+(?P<name>.+?)\s+"
    r"(?P<a>\d{1,3}(?:\.\d{3})*|\d+)\s+"
    r"(?P<b>\d{1,3}(?:\.\d{3})*|\d+)\s+"
    r"(?P<c>\d{1,3}(?:\.\d{3})*|\d+)\s+"
    r"(?P<d>\d{1,3}(?:\.\d{3})*|\d+)\s+"
    r"(?P<e>\d{1,3}(?:\.\d{3})*|\d+)\s*$"
)
_TOTAL_RE = re.compile(
    r"^Insgesamt (vollstationär|teilstationär)\s+"
    r"(?P<a>\d{1,3}(?:\.\d{3})*|\d+)\s+"
    r"(?P<b>\d{1,3}(?:\.\d{3})*|\d+)\s+"
    r"(?P<c>\d{1,3}(?:\.\d{3})*|\d+)\s+"
    r"(?P<d>\d{1,3}(?:\.\d{3})*|\d+)\s+"
    r"(?P<e>\d{1,3}(?:\.\d{3})*|\d+)\s*$"
)
_CODE_TITLE = {
    "390": "Kinder- und Jugendpsychiatrie",
    "820": "Psychiatrie- und Psychotherapie",  # hyphen as printed on the 820 sheet
    "830": "Psychosomatische Medizin und Psychotherapie",
}


def _im():
    from ingest.domains import institutions_media as im
    return im


def parse_de_int(text: str) -> int:
    return int(text.replace(".", ""))


def parse_hamburg_fachgebiet_sheet(text: str, *, code: str, kind: str) -> list[dict]:
    """Parse one Anlage-4 Fachgebiet sheet. kind is 'beds' (vollstationär) or 'places'."""
    rows = []
    in_section = None
    for raw in (text or "").splitlines():
        line = raw.strip()
        if line.startswith("Insgesamt vollstationär"):
            in_section = "beds"
            m = _TOTAL_RE.match(line)
            if m and kind == "beds":
                rows.append({
                    "hospital_name": None,
                    "is_total": True,
                    "value": parse_de_int(m.group("d")),
                    "quote": line,
                    "kind": "beds",
                    "code": code,
                })
            continue
        if line.startswith("Insgesamt teilstationär"):
            in_section = "places"
            m = _TOTAL_RE.match(line)
            if m and kind == "places":
                rows.append({
                    "hospital_name": None,
                    "is_total": True,
                    "value": parse_de_int(m.group("d")),
                    "quote": line,
                    "kind": "places",
                    "code": code,
                })
            continue
        if line.startswith("Teilstationäre Behandlungsplätze"):
            in_section = "places"
            continue
        if in_section not in {"beds", "places"} or in_section != kind:
            # Hospital lines appear under the matching section header; for beds
            # they start after the Betten-Soll header, before the first total.
            if kind == "beds" and in_section is None:
                in_section = "beds"  # first block is vollstationär
            elif in_section != kind:
                continue
        m = _HOSPITAL_RE.match(line)
        if not m:
            continue
        value = parse_de_int(m.group("d"))
        if value <= 0:
            continue
        rows.append({
            "hospital_name": clean(m.group("name")),
            "hospital_code": m.group("code"),
            "is_total": False,
            "value": value,
            "quote": line,
            "kind": kind,
            "code": code,
        })
    return rows


def split_hamburg_fachgebiet_pages(text: str) -> dict[str, str]:
    """Return layout text for Fachgebiet codes 390, 820 and 830."""
    out: dict[str, str] = {}
    for page in (text or "").split("\f"):
        m = re.search(r"Fachgebiet:\s+(390|820|830)\b", page)
        if m:
            out[m.group(1)] = page
    return out


def hamburg_figures(text: str) -> list[dict]:
    pages = split_hamburg_fachgebiet_pages(text)
    figures = []
    locators = {"390": "PDF-S. 87, Anlage 4, Fachgebiet 390", "820": "PDF-S. 92, Anlage 4, Fachgebiet 820", "830": "PDF-S. 93, Anlage 4, Fachgebiet 830"}
    for code, page in pages.items():
        for kind in ("beds", "places"):
            metric = FACHGEBIET_METRIC[(code, kind)]
            for rec in parse_hamburg_fachgebiet_sheet(page, code=code, kind=kind):
                figures.append({
                    **rec,
                    "source": "hh_kh2026",
                    "land": "HH",
                    "year": 2026,
                    "period": "2026-01-01",
                    "metric": metric,
                    "unit": "beds" if kind == "beds" else "day_places",
                    "locator": locators[code] + (", vollstationäre Betten-Soll 01.01.2026" if kind == "beds" else ", teilstationäre Plätze-Soll 01.01.2026"),
                    "note": SERIES_HH,
                })
    return figures


def parse_niedersachsen_land_total(text: str) -> list[dict]:
    """Official Land total line (typo 'Kapaziäten' as printed)."""
    target = None
    for line in (text or "").splitlines():
        if "Summe Niedersachsen (nur betriebene Kapaziäten)" in line:
            target = line
            break
    if not target:
        return []
    numbers = [parse_de_int(n) for n in re.findall(r"\d{1,3}(?:\.\d{3})+|\d+", target)]
    # Skip the leading region-style tokens; the total line has no KHNR, only the 34 capacity figures.
    # The first number on this line is AUG=258.
    if len(numbers) < 34:
        return []
    # If a stray page number got prepended, take the last 34.
    nums = numbers[-34:]
    kjp, psy, psm = nums[20], nums[21], nums[22]
    kjp_d, psy_d, psm_d = nums[30], nums[31], nums[32]
    specs = [
        (METRIC_KJP, kjp, "beds"),
        (METRIC_PSY, psy, "beds"),
        (METRIC_PSM, psm, "beds"),
        (METRIC_KJP_DAY, kjp_d, "day_places"),
        (METRIC_PSY_DAY, psy_d, "day_places"),
        (METRIC_PSM_DAY, psm_d, "day_places"),
    ]
    out = []
    for metric, value, unit in specs:
        out.append({
            "source": "ni_kh2024",
            "land": "NI",
            "year": 2024,
            "period": "2024-01-01",
            "metric": metric,
            "value": value,
            "unit": unit,
            "is_total": True,
            "hospital_name": None,
            "quote": target.strip(),
            "locator": "PDF, Zeile 'Summe Niedersachsen (nur betriebene Kapaziäten)', Stand 01.01.2024",
            "note": SERIES_NI,
        })
    return out


def _land_total(*, source, land, year, period, metric, value, unit, quote, locator, note) -> dict:
    return {
        "source": source,
        "land": land,
        "year": year,
        "period": period,
        "metric": metric,
        "value": value,
        "unit": unit,
        "is_total": True,
        "hospital_name": None,
        "quote": quote,
        "locator": locator,
        "note": note,
        "entity_type": "land",
        "entity_id": land,
    }


def baden_wuerttemberg_psm_land(text: str) -> list[dict]:
    """Quote-safe 2025 Land Bedarf for Psychosomatik only (PDF-S. 50)."""
    quote = (
        "Aus diesem Bedarf werden landesweit 1.566 Betten und 517 Plätze festgelegt "
        "(insgesamt 2.083 Betten/Plätze)"
    )
    if not quote_in_text(quote, text):
        return []
    locator = (
        "Krankenhausplan Baden-Württemberg 2026, PDF-S. 50, "
        "Psychosomatische Medizin und Psychotherapie, Bedarf 2025"
    )
    common = dict(
        source="bw_kh2026", land="BW", year=2025, period="2025",
        quote=quote, locator=locator, note=SERIES_BW,
    )
    return [
        _land_total(**common, metric=METRIC_PSM, value=1566, unit="beds"),
        _land_total(**common, metric=METRIC_PSM_DAY, value=517, unit="day_places"),
    ]


def berlin_bedarf_2025(text: str) -> list[dict]:
    """Plan 2020 Bedarf 2025: combined Betten/Plätze, not split voll/teil."""
    quote = (
        "Gemäß den Bevölkerungsprognosewerten für das Jahr 2025 ergibt sich für den Berliner "
        "Krankenhausplan 2020 ein prognostizierter gesamtstädtischer Bedarf in den Fächern "
        "Psychiatrie und Psychotherapie von 3.436, Psychosomatik und -psychotherapie von 547 "
        "sowie Kinder- und Jugendpsychiatrie und -psychotherapie von 601 Betten/Plätzen."
    )
    if not quote_in_text(quote, text):
        return []
    locator = (
        "Krankenhausplan 2020 des Landes Berlin, PDF-S. 73, "
        "prognostizierter gesamtstädtischer Bedarf 2025"
    )
    common = dict(
        source="be_kh2020", land="BE", year=2025, period="2025",
        quote=quote, locator=locator, note=SERIES_BE, unit="beds_or_places",
    )
    return [
        _land_total(**common, metric=METRIC_PSY, value=3436),
        _land_total(**common, metric=METRIC_PSM, value=547),
        _land_total(**common, metric=METRIC_KJP, value=601),
    ]


def brandenburg_land_festlegungen(text: str) -> list[dict]:
    """4. KH-Plan Land Festlegungen from the Amtsblatt table annex (PDF-S. 19–20)."""
    specs = [
        (
            METRIC_KJP, 255, "beds",
            "Kinder- und Jugendpsychiatrie und -psychotherapie                      233           245           255",
            "Amtsblatt-Tabellenteil PDF-S. 19, Land Brandenburg, Spalte 4. KH-Plan, Planbetten Kinder- und Jugendpsychiatrie",
        ),
        (
            METRIC_PSY, 1821, "beds",
            "Psychiatrie und Psychotherapie         1.753         1.708         1.821              0          113          113",
            "Amtsblatt-Tabellenteil PDF-S. 19, Land Brandenburg, Spalte 4. KH-Plan, Planbetten Psychiatrie und Psychotherapie",
        ),
        (
            METRIC_PSM, 253, "beds",
            "Psychosomatische Medizin und Psychotherapie                             0           226           253",
            "Amtsblatt-Tabellenteil PDF-S. 19, Land Brandenburg, Spalte 4. KH-Plan, Planbetten Psychosomatische Medizin",
        ),
        (
            METRIC_KJP_DAY, 202, "day_places",
            "TK Kinder- und Jugendpsychiatrie und -psychotherapie                114           126           202",
            "Amtsblatt-Tabellenteil PDF-S. 19, Land Brandenburg, Spalte 4. KH-Plan, Tagesklinikplätze KJP",
        ),
        (
            METRIC_PSY_DAY, 850, "day_places",
            "TK Psychiatrie und Psychotherapie                                     780            793            850",
            "Amtsblatt-Tabellenteil PDF-S. 20, Land Brandenburg, Spalte 4. KH-Plan, Tagesklinikplätze Psychiatrie",
        ),
        (
            METRIC_PSM_DAY, 142, "day_places",
            "TK Psychosomatische Medizin und Psychotherapie                          0            120            142",
            "Amtsblatt-Tabellenteil PDF-S. 20, Land Brandenburg, Spalte 4. KH-Plan, Tagesklinikplätze Psychosomatik",
        ),
    ]
    out = []
    for metric, value, unit, quote, locator in specs:
        if not quote_in_text(quote, text):
            continue
        out.append(_land_total(
            source="bb_kh4", land="BB", year=2021, period="2021-07-23",
            metric=metric, value=value, unit=unit, quote=quote,
            locator=locator, note=SERIES_BB,
        ))
    return out



# Official Kreis AGS for hospital *site* towns on the 4. KH-Plan sheets
# (left-hand address, not the Träger headquarters).
BB_CITY_KREIS = {
    "neuruppin": "12068",          # Ostprignitz-Ruppin
    "perleberg": "12070",          # Prignitz
    "hennigsdorf": "12065",        # Oberhavel
    "oranienburg": "12065",        # Oberhavel
    "angermünde": "12073",         # Uckermark
    "eberswalde": "12060",         # Barnim
    "potsdam": "12054",            # kreisfreie Stadt Potsdam
    "treuenbrietzen": "12069",     # Potsdam-Mittelmark
    "brandenburg an der havel": "12051",
    "brandenburg a. d. havel": "12051",
    "cottbus": "12052",
    "spremberg": "12071",          # Spree-Neiße
    "senftenberg": "12066",        # Oberspreewald-Lausitz
    "elsterwerda": "12062",        # Elbe-Elster
    "finsterwalde": "12062",
    "herzberg": "12062",
    "lauchhammer": "12066",
    "lübben": "12061",             # Dahme-Spreewald
    "teupitz": "12061",            # Dahme-Spreewald
    "frankfurt (oder)": "12053",
    "eisenhüttenstadt": "12067",   # Oder-Spree
    "rüdersdorf": "12064",         # Märkisch-Oderland
}

BB_FACH_BEDS = [
    ("Kinder- und Jugendpsychiatrie und -psychotherapie", "390", METRIC_KJP, "beds"),
    ("Psychiatrie und Psychotherapie", "820", METRIC_PSY, "beds"),
    ("Psychosomatische Medizin und Psychotherapie", "830", METRIC_PSM, "beds"),
]
BB_FACH_DAY = [
    ("Tagesklinikplätze – Kinder- und Jugendpsychiatrie und -psychotherapie", "390", METRIC_KJP_DAY, "places"),
    ("Tagesklinikplätze – Psychiatrie und Psychotherapie", "820", METRIC_PSY_DAY, "places"),
    ("Tagesklinikplätze – Psychosomatische Medizin und Psychotherapie", "830", METRIC_PSM_DAY, "places"),
]

_PLZ_CITY_RE = re.compile(
    r"\b(\d{5})\s+([A-ZÄÖÜ][A-Za-zÄÖÜäöüß(). /-]+)"
)
_GARBLED_RE = re.compile(
    r"psychotherapieJugend|Krankenhaus Kliniken",
    re.I,
)
_GARBLED_CELL_RE = re.compile(r"\b\d+-(?:\s|$)")


def legal_form_from_traeger(text: str) -> str | None:
    """Legal form only when the Träger line states one; never inferred from 'Öffentlicher Träger'."""
    blob = " ".join((text or "").split())
    if re.search(r"\bgGmbH\b", blob):
        return "gGmbH"
    if re.search(r"\bGmbH\b", blob):
        return "GmbH"
    if re.search(r"\bmbH\b", blob):
        return "mbH"
    if re.search(r"\be\.?\s*V\.?\b", blob, re.I):
        return "e.V."
    return None


def _normalize_bb_city(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").strip()).casefold()


def lookup_bb_kreis(city: str) -> str | None:
    key = _normalize_bb_city(city)
    if key in BB_CITY_KREIS:
        return BB_CITY_KREIS[key]
    # "Rüdersdorf bei Berlin" etc.
    for name, ags in BB_CITY_KREIS.items():
        if key.startswith(name + " ") or key.endswith(" " + name):
            return ags
    return None


def first_plan_value(rest: str) -> int | None:
    """First numeric cell on a Fachabteilung line (4. KH-Plan gesamt).

    Single-column sheets have one number (optional footnote '138 5)').
    Multi-site sheets have three cells: gesamt, then 'davon vollstationär'
    per site. The first cell is the hospital total. Lines with no number,
    only a dash, garbled tokens such as '70-', or unexpected words (other
    than a trailing 'Standort … N') are rejected.
    """
    rest = (rest or "").strip()
    if not rest:
        return None
    if re.search(r"\d+-", rest):
        return None
    standort = re.fullmatch(
        r"Standort\s+[A-Za-zÄÖÜäöüß(). /-]+?\s+(\d+)\s*$",
        rest,
    )
    if standort:
        value = int(standort.group(1))
        return value if value > 0 else None
    values: list[int | None] = []
    parts = re.split(r"\s{2,}", rest)
    for tok in parts:
        tok = tok.strip()
        if not tok:
            continue
        if tok in {"-", "–"}:
            values.append(None)
            continue
        m = re.fullmatch(r"(\d+)(?:\s+\d+\))?", tok)
        if m:
            values.append(int(m.group(1)))
            continue
        return None
    if not values or values[0] is None:
        return None
    return values[0] if values[0] > 0 else None


def _left_site_cities(header_lines: list[str]) -> list[tuple[str, str]]:
    """PLZ and city from the left-hand (hospital site) column only."""
    found: list[tuple[str, str]] = []
    for ln in header_lines:
        for m in _PLZ_CITY_RE.finditer(ln):
            # Right-hand Träger address sits far to the right on two-column sheets.
            if m.start() > 40 and not _PLZ_CITY_RE.search(ln[: m.start()]):
                continue
            city = m.group(2).strip()
            city = re.split(r"\s{2,}", city)[0].strip()
            found.append((m.group(1), city))
            break  # one city per line: the leftmost
    return found


def _collect_traeger(lines: list[str]) -> str:
    chunks = []
    grabbing = False
    for ln in lines:
        if "Träger:" in ln:
            grabbing = True
            chunks.append(ln.split("Träger:", 1)[1].strip())
            continue
        if grabbing:
            extra = ln.strip()
            right = re.split(r"\s{2,}", extra)[-1].strip() if extra else ""
            # GmbH sometimes wraps onto the next right-hand line, possibly after the rest of the name.
            if re.fullmatch(r"(g?G?mbH|e\.?\s*V\.?)", extra, re.I) or re.search(
                r"\b(gGmbH|GmbH|mbH|e\.\s*V\.)\s*$", right, re.I
            ):
                chunks.append(right)
            grabbing = False
    return " ".join(c for c in chunks if c)


def parse_brandenburg_hospital_sheets(text: str) -> list[dict]:
    """Per-hospital psych/KJP/psm Planbetten and day places from annex p.34+."""
    out: list[dict] = []
    pages = (text or "").split("\f")
    for n, page in enumerate(pages, 1):
        if "Plan-Betten" not in page or "Träger:" not in page:
            continue
        if _GARBLED_RE.search(page):
            continue
        lines = [ln.rstrip() for ln in page.splitlines()]
        nonempty = [ln for ln in lines if ln.strip()]
        if not nonempty:
            continue
        name = nonempty[0].strip()
        if name.startswith(("TK ", "3. ", "Land ", "Versorgungsgebiet")):
            continue
        header, body = [], []
        in_body = False
        for ln in lines:
            if not in_body and ln.strip().startswith("Fachabteilung"):
                in_body = True
                continue
            (body if in_body else header).append(ln)
        if any(
            _GARBLED_CELL_RE.search(ln)
            and any(
                key in ln
                for key in (
                    "Psychiatrie",
                    "Psychosomatische",
                    "Jugendpsychiatrie",
                    "Tagesklinikplätze",
                )
            )
            for ln in body
        ):
            continue
        traeger = _collect_traeger(header)
        legal = legal_form_from_traeger(traeger)
        sites = _left_site_cities(header)
        kreise = []
        for _plz, city in sites:
            ags = lookup_bb_kreis(city)
            if ags and ags not in kreise:
                kreise.append(ags)
        kreis_ags = kreise[0] if len(kreise) == 1 else None
        ort = sites[0][1] if sites else None
        labels = list(BB_FACH_DAY) + list(BB_FACH_BEDS)
        seen = set()
        for ln in body:
            s = ln.strip()
            if s.startswith(("davon Standort", "- davon", "– davon")):
                continue
            for label, code, metric, kind in labels:
                if not s.startswith(label):
                    continue
                rest = s[len(label):].strip()
                value = first_plan_value(rest)
                if not value:
                    break
                if metric in seen:
                    break
                seen.add(metric)
                unit = "beds" if kind == "beds" else "day_places"
                out.append({
                    "source": "bb_kh4",
                    "land": "BB",
                    "year": 2021,
                    "period": "2021-07-23",
                    "metric": metric,
                    "value": value,
                    "unit": unit,
                    "is_total": False,
                    "hospital_name": name,
                    "hospital_code": None,
                    "legal_form": legal,
                    "kreis_ags": kreis_ags,
                    "ort": ort,
                    "traeger": traeger or None,
                    "create_org": True,
                    "record_key": f"bb_kh4:{name_norm(name)}",
                    "code": code,
                    "kind": kind,
                    "quote": ln,
                    "locator": (
                        f"Amtsblatt-Tabellenteil PDF-S. {n}, {name}, "
                        f"4. KH-Plan {FACHGEBIET_LABEL[code]}"
                        + (", vollstationäre Planbetten" if kind == "beds" else ", Tagesklinikplätze")
                    ),
                    "note": SERIES_BB,
                })
                break
    return out


SERIES_SH = (
    "Krankenhausplan 2017 des Landes Schleswig-Holstein, Teil A "
    "(Aktuell-Zahlen der Planperiode 2017 und Angebot 2015)"
)
SERIES_HB = (
    "Krankenhausrahmenplan 2022-2024 für das Land Bremen, "
    "Tabelle 4 Behandlungskapazitäten nach Fachgebiet, Spalte 2022"
)
SERIES_SL2018 = (
    "Krankenhausplan für das Saarland 2018 bis 2025, Festlegung "
    "Planbetten und Plätze zum 31.12.2017 und 31.12.2025"
)
SERIES_SL2027 = (
    "Krankenhausplan für das Saarland 2027-2035, "
    "Versorgungsangebot 2023 und Planungsentscheidung der Fachabteilungen"
)

SH_TEIL_A_URL = (
    "https://www.schleswig-holstein.de/DE/fachinhalte/K/krankenhaeuser/Downloads/"
    "Krankenhausplan_2017_Teil_A.pdf?__blob=publicationFile&v=1"
)
SH_ANLAGEN_URL = (
    "https://www.schleswig-holstein.de/DE/fachinhalte/K/krankenhaeuser/Downloads/"
    "Krankenhausplan_2017_Anlagen.pdf?__blob=publicationFile&v=1"
)
SH_BESONDERER_URL = (
    "https://www.schleswig-holstein.de/DE/fachinhalte/K/krankenhaeuser/Downloads/"
    "Krankenhausplan_2017_BesondererTeil.pdf?__blob=publicationFile&v=1"
)
HB_PLAN_URL = (
    "https://www.gesundheit.bremen.de/sixcms/media.php/13/"
    "01_Krankenhausrahmenplan_2022_2024.pdf"
)
SL2018_LANDING = (
    "https://www.saarland.de/SharedDocs/Downloads/DE/msgff/tp_gesundheitprävention/"
    "downloads_servicegesundheit/downloads_salkrankenhauswesen/download_krankenhausplan_18-25"
)
SL2027_LANDING = (
    "https://www.saarland.de/SharedDocs/Downloads/DE/masfg/gesundheit/dld_krankenhausplan_2027_2035"
)

ARCHIVE_KEYS = (
    "sh_kh2017_a",
    "sh_kh2017_anlagen",
    "sh_kh2017_besonderer",
    "hb_kh2022",
    "sl_kh2018",
    "sl_kh2027",
)

# Populated into SOURCES by the applier.
ARCHIVE_SOURCES = {
    "sh_kh2017_a": {
        "url": SH_TEIL_A_URL,
        "archive_file": "sh_krankenhausplan_2017_teil_a.pdf",
        "title": "Krankenhausplan 2017 des Landes Schleswig-Holstein, Teil A",
        "publisher": "Land Schleswig-Holstein",
        "published": "2017",
        "license": RESERVED_LICENCE,
        "license_url": SH_TEIL_A_URL,
        "attribution": "Land Schleswig-Holstein, Krankenhausplan 2017, Teil A",
        "land": "SH",
    },
    "sh_kh2017_anlagen": {
        "url": SH_ANLAGEN_URL,
        "archive_file": "sh_krankenhausplan_2017_anlagen.pdf",
        "title": "Krankenhausplan 2017 des Landes Schleswig-Holstein, Anlagen",
        "publisher": "Land Schleswig-Holstein",
        "published": "2017",
        "license": RESERVED_LICENCE,
        "license_url": SH_ANLAGEN_URL,
        "attribution": "Land Schleswig-Holstein, Krankenhausplan 2017, Anlagen",
        "land": "SH",
    },
    "sh_kh2017_besonderer": {
        "url": SH_BESONDERER_URL,
        "archive_file": "sh_krankenhausplan_2017_besonderer_teil.pdf",
        "title": "Krankenhausplan 2017 des Landes Schleswig-Holstein, Besonderer Teil",
        "publisher": "Land Schleswig-Holstein",
        "published": "2017",
        "license": RESERVED_LICENCE,
        "license_url": SH_BESONDERER_URL,
        "attribution": "Land Schleswig-Holstein, Krankenhausplan 2017, Besonderer Teil",
        "land": "SH",
    },
    "hb_kh2022": {
        "url": HB_PLAN_URL,
        "archive_file": "bremen_krankenhausrahmenplan_2022_2024.pdf",
        "title": "Krankenhausrahmenplan 2022-2024 für das Land Bremen (Die Senatorin für Gesundheit, Frauen und Verbraucherschutz, 13. Februar 2023)",
        "publisher": "Die Senatorin für Gesundheit, Frauen und Verbraucherschutz der Freien Hansestadt Bremen",
        "published": "2023-02-13",
        "license": RESERVED_LICENCE,
        "license_url": HB_PLAN_URL,
        "attribution": "Die Senatorin für Gesundheit, Frauen und Verbraucherschutz, Krankenhausrahmenplan 2022-2024 für das Land Bremen",
        "land": "HB",
    },
    "sl_kh2018": {
        "url": SL2018_LANDING,
        "archive_file": "saarland_krankenhausplan_2018_2025.pdf",
        "title": "Krankenhausplan für das Saarland 2018 bis 2025",
        "publisher": "Saarland, Ministerium für Soziales, Gesundheit, Frauen und Familie",
        "published": "2018",
        "license": RESERVED_LICENCE,
        "license_url": SL2018_LANDING,
        "attribution": "Saarland, Krankenhausplan 2018 bis 2025",
        "land": "SL",
    },
    "sl_kh2027": {
        "url": SL2027_LANDING,
        "archive_file": "saarland_krankenhausplan_2027_2035.pdf",
        "title": "Krankenhausplan für das Saarland 2027-2035",
        "publisher": "Saarland, Ministerium für Arbeit, Soziales, Frauen und Gesundheit",
        "published": "2027",
        "license": RESERVED_LICENCE,
        "license_url": SL2027_LANDING,
        "attribution": "Saarland, Krankenhausplan 2027-2035",
        "land": "SL",
    },
}


def _year_series_value(numbers: list[int]) -> int | None:
    """2010-2022 time series: the 13th number is the 2022 column, not Veränderung."""
    if len(numbers) >= 13:
        return numbers[12]
    return None


def _line_numbers(line: str) -> list[int]:
    return [parse_de_int(tok) for tok in re.findall(r"\d{1,3}(?:\.\d{3})+|\d+", line)]


def _pdf_page_and_line(text: str, needle: str) -> tuple[int, int] | None:
    for i, page in enumerate((text or "").split("\f"), 1):
        for n, ln in enumerate(page.splitlines(), 1):
            if needle in ln:
                return i, n
    # folded fallback: first page containing the folded quote
    from ingest.domains.institutions_media_rechnungshof import fold_text
    q = fold_text(needle).casefold()
    for i, page in enumerate((text or "").split("\f"), 1):
        if q and q in fold_text(page).casefold():
            return i, 0
    return None


def _locator(url: str, pdf_page: int | None, line: int | None, where: str) -> str:
    bits = [url, where]
    if pdf_page:
        bits.append(f"PDF-S. {pdf_page}")
    if line:
        bits.append(f"Zeile {line}")
    return ", ".join(bits)


def schleswig_holstein_teil_a_land(text: str) -> list[dict]:
    """Quote-safe SH Land totals: Aktuell (2017) and 2015 Angebot. No per-hospital rows."""
    specs = [
        # year, period, metric, value, unit, quote, where
        (2017, "2017", METRIC_KJP, 244, "beds",
         "Aktuell stehen 244 Planbetten und 167 tagesklinische Plätze zur Verfügung.",
         "Teil A, Abschnitt 11.17 Kinder- und Jugendpsychiatrie, Aktuell-Stand"),
        (2017, "2017", METRIC_KJP_DAY, 167, "day_places",
         "Aktuell stehen 244 Planbetten und 167 tagesklinische Plätze zur Verfügung.",
         "Teil A, Abschnitt 11.17 Kinder- und Jugendpsychiatrie, Aktuell-Stand"),
        (2017, "2017", METRIC_PSY, 1981, "beds",
         "Aktuell stehen 1.981 Planbetten und 746 tagesklinische Plätze zur Verfügung.",
         "Teil A, Abschnitt 11.18 Psychiatrie und Psychotherapie, Aktuell-Stand"),
        (2017, "2017", METRIC_PSY_DAY, 746, "day_places",
         "Aktuell stehen 1.981 Planbetten und 746 tagesklinische Plätze zur Verfügung.",
         "Teil A, Abschnitt 11.18 Psychiatrie und Psychotherapie, Aktuell-Stand"),
        (2017, "2017", METRIC_PSM, 450, "beds",
         "Aktuell stehen 450 Planbetten und 107 tagesklinische Plätze zur Verfügung.",
         "Teil A, Abschnitt 11.19 Psychotherapeutische Medizin / Psychosomatik, Aktuell-Stand"),
        (2017, "2017", METRIC_PSM_DAY, 107, "day_places",
         "Aktuell stehen 450 Planbetten und 107 tagesklinische Plätze zur Verfügung.",
         "Teil A, Abschnitt 11.19 Psychotherapeutische Medizin / Psychosomatik, Aktuell-Stand"),
        (2015, "2015", METRIC_KJP, 239, "beds",
         "Im Jahr 2015 standen für die stationäre Versorgung im Bereich Kinder- und "
         "Jugendpsychiatrie und- psychotherapie 239 Planbetten zur Verfügung.",
         "Teil A, Abschnitt 11.17, Angebot 2015"),
        (2015, "2015", METRIC_PSY, 1962, "beds",
         "Im Jahr 2015 standen für die stationäre Versorgung im Bereich Psychiatrie und "
         "Psychotherapie 1.962 Planbetten zur Verfügung.",
         "Teil A, Abschnitt 11.18, Angebot 2015"),
        (2015, "2015", METRIC_PSM, 448, "beds",
         "Im Jahr 2015 standen für die stationäre Versorgung im Bereich Psychotherapeutische "
         "Medizin / Psychosomatik 448 Planbetten zur Verfügung.",
         "Teil A, Abschnitt 11.19, Angebot 2015"),
        (2015, "2015", METRIC_KJP_DAY, 150, "day_places",
         "Acht Kliniken betreiben an 12 Standorten psychiatrische Tageskliniken für Kinder und "
         "Jugendliche mit 150 Plätzen (Stand 2015)",
         "Teil A, Abschnitt 9.4, tagesklinische KJP-Plätze Stand 2015"),
        (2015, "2015", METRIC_PSY_DAY, 700, "day_places",
         "2015 wurden insgesamt 700 Plätze im teilstationären Setting ausgewiesen.",
         "Teil A, Abschnitt 9.2.2 Psychiatrische Tageskliniken, Angebot 2015"),
    ]
    out = []
    for year, period, metric, value, unit, quote, where in specs:
        if not quote_in_text(quote, text):
            continue
        loc = _pdf_page_and_line(text, quote.split(".")[0][:80] if False else quote)
        # prefer a distinctive snippet for page lookup
        snippet = quote if quote in (text or "") else quote[:60]
        found = _pdf_page_and_line(text, snippet) or _pdf_page_and_line(text, quote[-40:])
        pdf_s, line = (found or (None, None))
        out.append(_land_total(
            source="sh_kh2017_a", land="SH", year=year, period=period,
            metric=metric, value=value, unit=unit, quote=quote,
            locator=_locator(SH_TEIL_A_URL, pdf_s, line, where),
            note=SERIES_SH,
        ))
    return out


_HB_LAND_LABELS = (
    ("Kinder- und Jugendpsychiatrie", METRIC_KJP, "beds", "390"),
    ("Psychiatrie und Psychotherapie", METRIC_PSY, "beds", "820"),
    ("Psychosomatik und Psychotherapie", METRIC_PSM, "beds", "830"),
    ("TK Kinder-/Jugendpsychiatrie", METRIC_KJP_DAY, "day_places", "390"),
    ("TK Psychiatrie und Psychotherapie", METRIC_PSY_DAY, "day_places", "820"),
)


def bremen_rahmenplan_land(text: str) -> list[dict]:
    """Land Bremen 2022 capacities from Tabelle 4 (not the Stadt Bremen sheets)."""
    pages = (text or "").split("\f")
    target = None
    page_no = line0 = None
    for i, page in enumerate(pages, 1):
        if "Tabelle 4:" in page and "Land Bremen (Fortsetzung)" in page:
            target = page
            page_no = i
            break
    if not target:
        return []
    out = []
    for n, ln in enumerate(target.splitlines(), 1):
        s = ln.strip()
        for label, metric, unit, _code in _HB_LAND_LABELS:
            if not s.startswith(label):
                continue
            rest = s[len(label):].strip()
            if rest[:1].isalpha():
                continue
            value = _year_series_value(_line_numbers(ln))
            if value is None:
                break
            out.append(_land_total(
                source="hb_kh2022", land="HB", year=2022, period="2022",
                metric=metric, value=value, unit=unit, quote=ln.rstrip(),
                locator=_locator(
                    HB_PLAN_URL, page_no, n,
                    "Tabelle 4, Behandlungskapazitäten nach Fachgebiet - Land Bremen, Spalte 2022",
                ),
                note=SERIES_HB,
            ))
            break
    return out


_HB_HOSP_TITLE = re.compile(
    r"Tabelle\s+(\d+): Entwicklung der Behandlungskapazitäten nach Fachgebiet im Zeitverlauf, (.+)"
)
_HB_KREIS = (
    ("Bremerhaven", "04012", "Bremerhaven"),
    ("Bremen", "04011", "Bremen"),
)


def _hb_hospital_meta(title: str) -> tuple[str, str | None, str | None, str | None]:
    raw = re.sub(r"\s*\(Fortsetzung\)\s*$", "", title).strip()
    if ":" in raw:
        traeger, name = raw.split(":", 1)
        name, traeger = name.strip(), traeger.strip()
    else:
        name, traeger = raw, raw
    legal = legal_form_from_traeger(raw)
    kreis = ort = None
    # Prefer the more specific city when both strings occur (Bremerhaven contains no 'Bremen' as a token issue:
    # 'Bremerhaven' contains 'Bremen' as prefix). Check Bremerhaven first.
    for city, ags, ort_name in _HB_KREIS:
        if re.search(rf"\b{re.escape(city)}\b", raw):
            kreis, ort = ags, ort_name
            break
    return name, legal, kreis, ort


def bremen_rahmenplan_hospitals(text: str) -> list[dict]:
    """Per-hospital 2022 psych capacities from the clean 13-year Fachgebiet tables."""
    pages = (text or "").split("\f")
    by_tab: dict[str, dict] = {}
    for i, page in enumerate(pages, 1):
        lines = page.splitlines()
        if len(lines) < 20:
            continue
        current = None
        for n, ln in enumerate(lines, 1):
            m = _HB_HOSP_TITLE.search(ln)
            if m:
                tab = m.group(1)
                title = re.sub(r"\s*\(Fortsetzung\)\s*$", "", m.group(2)).strip()
                current = by_tab.setdefault(tab, {"tab": tab, "title": title, "rows": []})
                current["title"] = title
            if not current:
                continue
            s = ln.strip()
            for label, metric, unit, code in _HB_LAND_LABELS:
                if not s.startswith(label):
                    continue
                rest = s[len(label):].strip()
                if not rest or rest[:1].isalpha():
                    continue
                nums = _line_numbers(ln)
                value = _year_series_value(nums)
                if value is None or value == 0:
                    break
                kind = "beds" if unit == "beds" else "places"
                current["rows"].append({
                    "metric": metric, "value": value, "unit": unit,
                    "code": code, "kind": kind, "quote": ln.rstrip(),
                    "page": i, "line": n,
                })
                break
    out = []
    for rec in by_tab.values():
        if not rec["rows"]:
            continue
        name, legal, kreis, ort = _hb_hospital_meta(rec["title"])
        for row in rec["rows"]:
            out.append({
                "source": "hb_kh2022",
                "land": "HB",
                "year": 2022,
                "period": "2022",
                "metric": row["metric"],
                "value": row["value"],
                "unit": row["unit"],
                "is_total": False,
                "hospital_name": name,
                "hospital_code": None,
                "legal_form": legal,
                "kreis_ags": kreis,
                "ort": ort,
                "create_org": True,
                "record_key": f"hb_kh2022:{name_norm(name)}",
                "code": row["code"],
                "kind": row["kind"],
                "quote": row["quote"],
                "locator": _locator(
                    HB_PLAN_URL, row["page"], row["line"],
                    f"Tabelle {rec['tab']}, {name}, Spalte 2022, "
                    f"{FACHGEBIET_LABEL[row['code']]}",
                ),
                "note": SERIES_HB,
            })
    return out


_SL2018_FEST = (
    ("sl_kh2018", 2017, "2017-12-31", METRIC_KJP, 55, "beds",
     "Planbetten 31.12.2017            55             Plätze 31.12.2017       60",
     "Festlegung Kinder- und Jugendpsychiatrie, Planbetten 31.12.2017"),
    ("sl_kh2018", 2017, "2017-12-31", METRIC_KJP_DAY, 60, "day_places",
     "Planbetten 31.12.2017            55             Plätze 31.12.2017       60",
     "Festlegung Kinder- und Jugendpsychiatrie, Plätze 31.12.2017"),
    ("sl_kh2018", 2025, "2025-12-31", METRIC_KJP, 71, "beds",
     "Planbetten 31.12.2025            71             Plätze 31.12.2025       73",
     "Festlegung Kinder- und Jugendpsychiatrie, Planbetten 31.12.2025"),
    ("sl_kh2018", 2025, "2025-12-31", METRIC_KJP_DAY, 73, "day_places",
     "Planbetten 31.12.2025            71             Plätze 31.12.2025       73",
     "Festlegung Kinder- und Jugendpsychiatrie, Plätze 31.12.2025"),
    ("sl_kh2018", 2017, "2017-12-31", METRIC_PSY, 643, "beds",
     "Planbetten 31.12.2017           643             Plätze 31.12.2017       248",
     "Festlegung Psychiatrie und Psychotherapie, Planbetten 31.12.2017"),
    ("sl_kh2018", 2017, "2017-12-31", METRIC_PSY_DAY, 248, "day_places",
     "Planbetten 31.12.2017           643             Plätze 31.12.2017       248",
     "Festlegung Psychiatrie und Psychotherapie, Plätze 31.12.2017"),
    ("sl_kh2018", 2025, "2025-12-31", METRIC_PSY, 690, "beds",
     "Planbetten 31.12.2025           690             Plätze 31.12.2025       289",
     "Festlegung Psychiatrie und Psychotherapie, Planbetten 31.12.2025"),
    ("sl_kh2018", 2025, "2025-12-31", METRIC_PSY_DAY, 289, "day_places",
     "Planbetten 31.12.2025           690             Plätze 31.12.2025       289",
     "Festlegung Psychiatrie und Psychotherapie, Plätze 31.12.2025"),
    ("sl_kh2018", 2017, "2017-12-31", METRIC_PSM, 86, "beds",
     "Planbetten 31.12.2017         86              Plätze 31.12.2017       10",
     "Festlegung Psychosomatische Medizin, Planbetten 31.12.2017"),
    ("sl_kh2018", 2017, "2017-12-31", METRIC_PSM_DAY, 10, "day_places",
     "Planbetten 31.12.2017         86              Plätze 31.12.2017       10",
     "Festlegung Psychosomatische Medizin, Plätze 31.12.2017"),
    ("sl_kh2018", 2025, "2025-12-31", METRIC_PSM, 90, "beds",
     "Planbetten 31.12.2025         90              Plätze 31.12.2025       12",
     "Festlegung Psychosomatische Medizin, Planbetten 31.12.2025"),
    ("sl_kh2018", 2025, "2025-12-31", METRIC_PSM_DAY, 12, "day_places",
     "Planbetten 31.12.2025         90              Plätze 31.12.2025       12",
     "Festlegung Psychosomatische Medizin, Plätze 31.12.2025"),
)


def saarland_2018_land(text: str) -> list[dict]:
    """Land Festlegungen 31.12.2017 and 31.12.2025. Standort tables are not quote-safe."""
    out = []
    for source, year, period, metric, value, unit, quote, where in _SL2018_FEST:
        if not quote_in_text(quote, text):
            continue
        found = _pdf_page_and_line(text, quote)
        pdf_s, line = (found or (None, None))
        out.append(_land_total(
            source=source, land="SL", year=year, period=period,
            metric=metric, value=value, unit=unit, quote=quote,
            locator=_locator(SL2018_LANDING, pdf_s, line, where),
            note=SERIES_SL2018,
        ))
    return out


_SL2027_LAND = (
    (METRIC_KJP, 73, "beds",
     "Im Jahr 2023 standen im Saarland insgesamt 73 Planbetten zur Verfügung.",
     "Abschnitt 8.62.1, Versorgungsangebot 2023, Planbetten KJP"),
    (METRIC_KJP_DAY, 77, "day_places",
     "Darüber hinaus wurden im Saarland in der Fachabteilung Kinder- und Jugendpsychiatrie "
     "und -psychotherapie 77 tagesklinische Behandlungsplätze vorgehalten.",
     "Abschnitt 8.62.1, Versorgungsangebot 2023, tagesklinische Plätze KJP"),
    (METRIC_PSY, 739, "beds",
     "Im Jahr 2023 standen im Saarland insgesamt 739 Planbetten zur Verfügung.",
     "Abschnitt 8.63.1, Versorgungsangebot 2023, Planbetten Psychiatrie"),
    (METRIC_PSY_DAY, 314, "day_places",
     "Darüber hinaus wurden im Saarland in der Fachabteilung Psychiatrie und Psychotherapie "
     "314 tagesklinische Behandlungsplätze vorgehalten.",
     "Abschnitt 8.63.1, Versorgungsangebot 2023, tagesklinische Plätze Psychiatrie"),
    (METRIC_PSM, 126, "beds",
     "Im Jahr 2023 standen im Saarland insgesamt 126 Planbetten zur Verfügung.",
     "Abschnitt 8.64.1, Versorgungsangebot 2023, Planbetten Psychosomatik"),
    (METRIC_PSM_DAY, 24, "day_places",
     "Darüber hinaus wurden im Saarland in der Fachabteilung Psychosomatische Medizin und "
     "Psychotherapie 24 tagesklinische Behandlungsplätze vorgehalten",
     "Abschnitt 8.64.1, Versorgungsangebot 2023, tagesklinische Plätze Psychosomatik"),
)


def saarland_2027_land(text: str) -> list[dict]:
    out = []
    for metric, value, unit, quote, where in _SL2027_LAND:
        if not quote_in_text(quote, text):
            continue
        found = _pdf_page_and_line(text, quote[:50]) or _pdf_page_and_line(text, str(value) + " Planbetten" if unit == "beds" else f"{value} tagesklinische")
        pdf_s, line = (found or (None, None))
        out.append(_land_total(
            source="sl_kh2027", land="SL", year=2023, period="2023",
            metric=metric, value=value, unit=unit, quote=quote,
            locator=_locator(SL2027_LANDING, pdf_s, line, where),
            note=SERIES_SL2027,
        ))
    return out


_SL_ASSIGN_HEADER = {
    "Fachabteilung Kinder- und Jugendpsychiatrie und -psychotherapie": ("390", "KJP"),
    "Fachabteilung Psychiatrie und Psychotherapie": ("820", "PSY"),
    "Fachabteilung Psychosomatische Medizin und Psychotherapie": ("830", "PSM"),
}
_SL_ROW = re.compile(
    r"^(?P<name>\S.*?)\s+(?P<beds>\d+)\s+(?P<places>\d+)(?:\s+(?P<note>.*))?$"
)
_SL_CITY_KREIS = (
    (r"\bNeunkirchen\b", "10043", "Neunkirchen"),
    (r"\bMerzig\b", "10044", "Merzig"),
    (r"\bSt\.\s*Wendel\b", "10046", "St. Wendel"),
    (r"\bVölklingen\b", "10041", "Völklingen"),
    (r"\bSaarbrücken\b", "10041", "Saarbrücken"),
    (r"\bPüttlingen\b", "10041", "Püttlingen"),
    (r"\bBerus\b", "10045", "Berus"),
)


def _sl_kreis(name: str) -> tuple[str | None, str | None]:
    for pat, ags, ort in _SL_CITY_KREIS:
        if re.search(pat, name):
            return ags, ort
    return None, None


def saarland_2027_hospitals(text: str) -> list[dict]:
    """Planungsentscheidung tables with a single Planbetten/Planplätze pair on one line.

    Wrapped rows (Johannesbad Saarschleife) are skipped as not quote-safe.
    """
    out: list[dict] = []
    pages = (text or "").split("\f")
    code = fach = None
    for i, page in enumerate(pages, 1):
        lines = [ln.rstrip() for ln in page.splitlines()]
        for n, ln in enumerate(lines, 1):
            s = ln.strip()
            if s in _SL_ASSIGN_HEADER and n < len(lines) and "Krankenhausstandort" in (lines[n] if n < len(lines) else ""):
                # header is the line itself; next line should mention Krankenhausstandort
                pass
            if s in _SL_ASSIGN_HEADER:
                # only treat as the assignment table when the following non-empty line is the column header
                nxt = next((x.strip() for x in lines[n:] if x.strip()), "")
                if nxt.startswith("Krankenhausstandort"):
                    code, fach = _SL_ASSIGN_HEADER[s]
                continue
            if s.startswith("Abbildung") or s.startswith("8.6"):
                code = fach = None
                continue
            if not code or not s or s.startswith("Krankenhausstandort") or s.startswith("Planbetten"):
                continue
            m = _SL_ROW.match(s)
            if not m:
                continue
            name = m.group("name").strip()
            if name in {"Krankenhausstandort", "HA", "BA", "Summe", "TK"}:
                continue
            beds = int(m.group("beds"))
            places = int(m.group("places"))
            remark = (m.group("note") or "").strip()
            year = 2028 if "01.01.2028" in remark else 2027
            kreis, ort = _sl_kreis(name)
            legal = legal_form_from_traeger(name)
            pairs = []
            if beds:
                pairs.append((METRIC_PSY if code == "820" else METRIC_KJP if code == "390" else METRIC_PSM,
                              beds, "beds", "beds"))
            if places:
                pairs.append((METRIC_PSY_DAY if code == "820" else METRIC_KJP_DAY if code == "390" else METRIC_PSM_DAY,
                              places, "day_places", "places"))
            for metric, value, unit, kind in pairs:
                out.append({
                    "source": "sl_kh2027",
                    "land": "SL",
                    "year": year,
                    "period": str(year),
                    "metric": metric,
                    "value": value,
                    "unit": unit,
                    "is_total": False,
                    "hospital_name": name,
                    "hospital_code": None,
                    "legal_form": legal,
                    "kreis_ags": kreis,
                    "ort": ort,
                    "create_org": True,
                    "record_key": f"sl_kh2027:{name_norm(name)}",
                    "code": code,
                    "kind": kind,
                    "quote": ln,
                    "locator": _locator(
                        SL2027_LANDING, i, n,
                        f"Planungsentscheidung Fachabteilung {FACHGEBIET_LABEL[code]}, {name}",
                    ),
                    "note": SERIES_SL2027,
                })
    return out


class ArchiveIntegrityError(RuntimeError):
    """Raised when a manual-archive Krankenhausplan is missing from SHA256SUMS or the hash mismatches."""


def read_archived_plan_bytes(cfg, filename: str) -> bytes:
    """Bytes of an archived plan after the sha256 matched SHA256SUMS. No network."""
    from ingest.domains import institutions_media_manual_archive as archive
    root = archive.archive_dir(cfg)
    sums = archive.load_checksums(root)
    if filename not in sums:
        raise ArchiveIntegrityError(f"{filename}: no SHA256SUMS entry in {root}")
    return archive.read_archived(root, filename)


def _load_archived_document(source_key: str, cfg) -> str:
    """Read a hand-archived plan after sha256 verification. Never fetches, never reads robots."""
    from ingest.domains import institutions_media_manual_archive as archive
    meta = SOURCES[source_key]
    data = read_archived_plan_bytes(cfg, meta["archive_file"])
    dest = archive.seed_cache(meta["url"], data, content_type="application/pdf")
    text = archive.pdf_text(dest)
    if not text:
        raise RuntimeError(f"no extractable layout text for archived {meta['archive_file']}")
    return text



SOURCES.update(ARCHIVE_SOURCES)


def khplan_robots_status(url: str) -> tuple[bool, str, float | None]:
    """Fail-closed robots.txt decision, reusing the press/counts_law checker."""
    return press_robots_status(url)


class RobotsBlocked(RuntimeError):
    """Raised when fail-closed robots.txt says this official URL must be skipped."""


def ensure_hospital_org(conn, name: str, land: str, source_id: int, *, legal_form=None, record_key=None):
    """Schema v6 org for a named hospital in a Krankenhausplan. Origin link on create."""
    from ingest.common import ensure_org
    key = record_key or f"khplan:{land}:{name_norm(name)}"
    return ensure_org(
        conn, name, land, source_id,
        legal_form=legal_form,
        record_kind="khplan_hospital",
        record_key=key,
    )


def ensure_khplan_table(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS institutions_media_khplan (
          id INTEGER PRIMARY KEY,
          official_key TEXT NOT NULL UNIQUE,
          hospital_name TEXT,
          land TEXT,
          fachgebiet TEXT,
          kind TEXT,
          year INTEGER,
          value REAL,
          einheit TEXT,
          facility_id INTEGER,
          qid TEXT,
          linked INTEGER NOT NULL DEFAULT 0,
          quote TEXT,
          locator TEXT,
          source_id INTEGER NOT NULL,
          org_id INTEGER,
          kreis_ags TEXT,
          FOREIGN KEY(facility_id) REFERENCES facility(id),
          FOREIGN KEY(source_id) REFERENCES source(id)
        )
        """
    )
    cols = {r[1] for r in conn.execute("PRAGMA table_info(institutions_media_khplan)")}
    if "org_id" not in cols:
        conn.execute("ALTER TABLE institutions_media_khplan ADD COLUMN org_id INTEGER")
    if "kreis_ags" not in cols:
        conn.execute("ALTER TABLE institutions_media_khplan ADD COLUMN kreis_ags TEXT")


def unique_psychiatric_facility(conn, name: str, land: str):
    """Return (facility_id, qid) only when the official name uniquely matches."""
    target = name_norm(name)
    if not target or land not in {"HH", "NI", "BE", "BY", "BW", "HB", "HE", "MV", "NW", "RP", "SL", "SN", "ST", "SH", "TH", "BB"}:
        return None
    rows = conn.execute(
        """
        SELECT f.id, f.name_norm, x.qid
          FROM facility f
          LEFT JOIN institutions_media_facility x ON x.facility_id=f.id
         WHERE f.land=?
           AND f.kind IN ('psychiatric', 'psych_unit')
           AND ifnull(f.is_protected, 0)=0
        """,
        (land,),
    ).fetchall()
    exact = [r for r in rows if r["name_norm"] == target]
    if len(exact) == 1 and exact[0]["qid"]:
        return exact[0]["id"], exact[0]["qid"]
    contained = []
    for r in rows:
        other = r["name_norm"] or ""
        if not other:
            continue
        if target == other or target in other or other in target:
            contained.append(r)
    if len(contained) == 1 and contained[0]["qid"]:
        return contained[0]["id"], contained[0]["qid"]
    return None


def store_cited_metric(conn, rec: dict, *, source_id: int, document_text: str, notes: list[str]) -> bool:
    quote = trim_quote(rec.get("quote"))
    metric = clean(rec.get("metric"))
    year = rec.get("year")
    value = rec.get("value")
    entity_type = clean(rec.get("entity_type"))
    entity_id = clean(rec.get("entity_id"))
    if not quote or not metric or year is None or value is None or not entity_type or not entity_id:
        notes.append(f"skipped khplan metric without quote/value/name/year: {metric}")
        return False
    try:
        amount = float(value)
    except (TypeError, ValueError):
        notes.append(f"skipped non-numeric khplan metric {metric}")
        return False
    if not quote_in_text(quote, document_text):
        notes.append(
            f"{entity_type}:{entity_id} {metric} {year} not stored; "
            "quote was not found in the cited document text"
        )
        return False
    if entity_type in {"land", "kreis", "gemeinde"}:
        entity_type, entity_id = _im().metric_geo(entity_type, entity_id)
    upsert(conn, "metric", {
        "entity_type": entity_type,
        "entity_id": entity_id,
        "metric": metric,
        "value": amount,
        "einheit": clean(rec.get("unit")) or "beds",
        "year": int(year),
        "period": clean(rec.get("period")),
        "is_est": 0,
        "is_rounded": 0,
        "anmerkung": clean(rec.get("note")),
        "quote": quote,
        "locator": clean(rec.get("locator")),
        "source_id": source_id,
    }, ["entity_type", "entity_id", "metric", "year"])
    return True


def _register(conn, source_key: str, sources) -> int:
    meta = SOURCES[source_key]
    return _im()._register_source(
        conn, meta["url"],
        title=meta["title"],
        publisher=meta["publisher"],
        license_=meta["license"],
        license_url=meta.get("license_url"),
        attribution=meta["attribution"],
        notes="Facts, metadata and short quotes only; full plan text is not redistributed.",
        redistribute_fulltext=0,
        bucket=sources,
    )


def _store_doc(conn, source_key: str, source_id: int) -> None:
    meta = SOURCES[source_key]
    upsert(conn, "doc", {
        "kind": "report",
        "title": meta["title"],
        "url": meta["url"],
        "herausgeber": meta["publisher"],
        "urheber": None,
        "veroeffentlicht": meta.get("published"),
        "land": meta.get("land") or "DE",
        "zusammenfassung": "Official Krankenhausplan psychiatric bed figures; facts and short quotes only.",
        "source_id": source_id,
    }, ["url"])


def _load_document(source_key: str, *, force: bool, cfg=None) -> str:
    meta = SOURCES[source_key]
    if source_key in ARCHIVE_KEYS or meta.get("archive_file"):
        return _load_archived_document(source_key, cfg or {})
    ok, reason, _delay = khplan_robots_status(meta["url"])
    if not ok:
        raise RobotsBlocked(f"robots fail-closed skip {meta['url']}: {reason}")
    fetch(meta["url"], domain=DOMAIN, force=force)
    path = raw_path(DOMAIN, meta["url"])
    text = document_text(path)
    if not text:
        raise RuntimeError(f"no extractable layout text for {meta['url']}")
    return text


def ingest_hospital_plans(conn, cfg, sources, notes) -> int:
    """Fetch official plans and store cited psychiatric bed figures. Returns metric count."""
    force = bool(cfg.get("force"))
    ensure_khplan_table(conn)
    texts = {}
    source_ids = {}
    fixture_texts = (cfg or {}).get("khplan_texts") or {}
    for key in SOURCES:
        try:
            if key in fixture_texts:
                texts[key] = fixture_texts[key]
            else:
                texts[key] = _load_document(key, force=force, cfg=cfg)
        except RobotsBlocked as exc:
            notes.append(str(exc))
            continue
        except FileNotFoundError as exc:
            from ingest.domains import institutions_media_manual_archive as archive
            root = archive.archive_dir(cfg)
            if key in ARCHIVE_KEYS and not root.is_dir():
                notes.append(f"hospital plan archive missing for {key}: {exc}")
                continue
            raise
        except ArchiveIntegrityError:
            raise
        source_ids[key] = _register(conn, key, sources)
        _store_doc(conn, key, source_ids[key])

    figures = []
    if "hh_kh2026" in texts:
        figures.extend(hamburg_figures(texts["hh_kh2026"]))
    if "ni_kh2024" in texts:
        figures.extend(parse_niedersachsen_land_total(texts["ni_kh2024"]))
    if "bw_kh2026" in texts:
        figures.extend(baden_wuerttemberg_psm_land(texts["bw_kh2026"]))
    if "be_kh2020" in texts:
        figures.extend(berlin_bedarf_2025(texts["be_kh2020"]))
    if "bb_kh4" in texts:
        figures.extend(brandenburg_land_festlegungen(texts["bb_kh4"]))
        figures.extend(parse_brandenburg_hospital_sheets(texts["bb_kh4"]))
    if "sh_kh2017_a" in texts:
        figures.extend(schleswig_holstein_teil_a_land(texts["sh_kh2017_a"]))
    if "hb_kh2022" in texts:
        figures.extend(bremen_rahmenplan_land(texts["hb_kh2022"]))
        figures.extend(bremen_rahmenplan_hospitals(texts["hb_kh2022"]))
    if "sl_kh2018" in texts:
        figures.extend(saarland_2018_land(texts["sl_kh2018"]))
    if "sl_kh2027" in texts:
        figures.extend(saarland_2027_land(texts["sl_kh2027"]))
        figures.extend(saarland_2027_hospitals(texts["sl_kh2027"]))
    stored = 0
    missing = 0
    linked = 0
    hospital_rows = 0
    org_cache = {}
    for rec in figures:
        key = rec["source"]
        if key not in texts:
            notes.append(
                f"skipped khplan metric {rec.get('metric')}; "
                "source was not loaded (robots fail-closed or fetch skipped)"
            )
            missing += 1
            continue
        text = texts[key]
        if rec.get("is_total"):
            rec["entity_type"] = "land"
            rec["entity_id"] = rec["land"]
            if store_cited_metric(conn, rec, source_id=source_ids[key], document_text=text, notes=notes):
                stored += 1
            else:
                missing += 1
            continue
        hospital_rows += 1
        official_key = f"{rec['land']}-KH:{rec.get('hospital_code') or name_norm(rec['hospital_name'])}:{rec['code']}:{rec['kind']}"
        org_id = None
        if rec.get("create_org") and rec.get("hospital_name"):
            cache_key = rec.get("record_key") or f"khplan:{rec['land']}:{name_norm(rec['hospital_name'])}"
            if cache_key not in org_cache:
                org_cache[cache_key] = ensure_hospital_org(
                    conn, rec["hospital_name"], rec["land"], source_ids[key],
                    legal_form=rec.get("legal_form"),
                    record_key=cache_key,
                )
            org_id = org_cache[cache_key]
        match = unique_psychiatric_facility(conn, rec["hospital_name"], rec["land"])
        facility_id = qid = None
        if match:
            facility_id, qid = match
            rec["entity_type"] = "facility"
            rec["entity_id"] = qid
            if store_cited_metric(conn, rec, source_id=source_ids[key], document_text=text, notes=notes):
                stored += 1
                linked += 1
            else:
                missing += 1
        elif not quote_in_text(rec.get("quote"), text):
            notes.append(
                f"khplan hospital {rec['hospital_name']} {rec['metric']} not stored; "
                "quote was not found in the cited document text"
            )
            missing += 1
            continue
        upsert(conn, "institutions_media_khplan", {
            "official_key": official_key,
            "hospital_name": rec["hospital_name"],
            "land": rec["land"],
            "fachgebiet": rec["code"] + " " + FACHGEBIET_LABEL[rec["code"]],
            "kind": rec["kind"],
            "year": rec["year"],
            "value": rec["value"],
            "einheit": rec["unit"],
            "facility_id": facility_id,
            "qid": qid,
            "linked": 1 if qid else 0,
            "org_id": org_id,
            "kreis_ags": rec.get("kreis_ags"),
            "quote": trim_quote(rec.get("quote")),
            "locator": rec["locator"],
            "source_id": source_ids[key],
        }, ["official_key"])
    notes.append(
        f"hospital_plans metrics={stored} quote_missing={missing} hospital_rows={hospital_rows} "
        f"linked_to_wikidata={linked}. Land totals: Hamburg Betten-Soll 01.01.2026, "
        "Niedersachsen betriebene Planbetten 01.01.2024, Baden-Württemberg Psychosomatik "
        "Bedarf 2025 (1.566 Betten / 517 Plätze), Berlin Plan 2020 Bedarf 2025 "
        "(Betten/Plätze combined) and Brandenburg 4. KH-Plan 2021 Amtsblatt Festlegungen. "
        "Per-hospital Hamburg figures are stored in institutions_media_khplan and linked to "
        "a Wikidata psychiatric facility only where the official name uniquely matches in the "
        "same Land; unmatched official hospital rows are kept in the sidecar without a facility id. "
        "New hospital organisations go through ensure_org with legal_form_norm and an origin "
        "link. Brandenburg per-hospital psychiatry rows (4. KH-Plan Festlegungen) are stored "
        "in the sidecar with Kreis AGS and an org id; they are not written as Kreis metrics "
        "(that would collide on year). Berlin Anlage 1 and Baden-Württemberg have no "
        "quote-safe per-hospital psych rows in this pass (see research). "
        "These Planbetten are a different series from Destatis Grunddaten (aufgestellte Betten). "
        "Manual-archive plans (SH 2017 Teil A Land totals; Bremen Rahmenplan 2022 Land totals "
        "and per-hospital rows; Saarland 2018 Land Festlegungen; Saarland 2027 Land 2023 totals "
        "and clean Planungsentscheidung hospital rows) are sha256-checked and never fetched. "
        "SH Anlagen/Besonderer Teil and Saarland 2018 Standort tables are registered as sources "
        "but have no quote-safe per-hospital rows. "
        "Skipped or not stored this pass: see research/institutions_media.md."
    )
    return stored


if __name__ == "__main__":
    from ingest.common import no_direct_run
    raise SystemExit(no_direct_run("institutions_media"))
