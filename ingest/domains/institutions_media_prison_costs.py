"""Prison cost per Hafttag / Haftplatz from official Landtag and ministry documents.

Every euro figure is stored only when its short quote appears in the unmodified
archived PDF (pdftotext -layout). Competing official series are kept side by
side under distinct metric names and series labels. Metric geography is AGS.
"""

from __future__ import annotations

from ingest.common import clean, document_text, fetch, raw_path, upsert
from ingest.domains.institutions_media_rechnungshof import quote_in_text, trim_quote

DOMAIN = "institutions_media"

# Comparable Tageshaftkostensatz (THKS) from the official 16-Land table.
METRIC_THKS = "prison_thks_eur_per_day"
# A Land's own official THKS (may differ from the comparison table).
METRIC_THKS_OWN = "prison_thks_own_eur_per_day"
METRIC_THKS_CAPACITY = "prison_thks_capacity_eur_per_day"
METRIC_THKS_ACTUAL = "prison_thks_actual_eur_per_day"
METRIC_TOTAL_DAILY = "prison_total_daily_eur"
METRIC_TOTAL_DAILY_CAPACITY = "prison_total_daily_capacity_eur"
METRIC_TOTAL_DAILY_ACTUAL = "prison_total_daily_actual_eur"
METRIC_DAILY_BAU = "prison_construction_investment_daily_eur"
METRIC_DAILY_SACH = "prison_equipment_investment_daily_eur"
METRIC_MONTH = "prison_cost_per_month_eur"
METRIC_YEAR = "prison_cost_per_year_eur"
METRIC_TOTAL = "prison_total_cost_eur"

SERIES_MV = "THKS Bundesländervergleich (MV Drs 8/5062)"
SERIES_MV_OWN = "THKS / Gesamtkosten Justizvollzug (MV Drs 8/5062, eigene Angabe)"
SERIES_NRW = "Tageshaftkosten inkl. Baukostensatz ab 2014 (NRW Vorlage 18/5295)"
SERIES_HH = "THKS (Hamburg Drs 23/1111)"
SERIES_BY_TOTAL = "Gesamttageshaftkosten inkl. Investitionssätze (Bayern Landtag)"
SERIES_BY_THKS = "Tageshaftkosten ohne Investitionssätze (Bayern Landtag)"
SERIES_BE_CAP = "Tageshaftkosten nach Belegungsfähigkeit (Berlin Drs 19/23828)"
SERIES_BE_ACT = "Tageshaftkosten nach tatsächlichen Hafttagen (Berlin Drs 19/23828)"
SERIES_BE_TOTAL_CAP = "Gesamt-Tageshaftkosten nach Belegungsfähigkeit (Berlin Drs 19/23828)"
SERIES_BE_TOTAL_ACT = "Gesamt-Tageshaftkosten nach tatsächlichen Hafttagen (Berlin Drs 19/23828)"
SERIES_BE_COST = "Gesamtkosten abzgl. Erlöse (Berlin Drs 19/23828)"

AMTLICH_LANDTAG = (
    "amtliches Werk, § 5 UrhG, scoped to the cited Landtag document text only; "
    "the official PDF states no reuse terms"
)

MV_URL = (
    "https://www.dokumentation.landtag-mv.de/parldok/dokument/64894/"
    "8_5062_entwicklung_der_kosten_in_den_justizvollzugsanstalten_in_mecklenburg_vorpommern.pdf"
)
NRW_URL = "https://www.landtag.nrw.de/portal/WWW/dokumentenarchiv/Dokument/MMV18-5295.pdf"
BY_2023_URL = (
    "https://www.bayern.landtag.de/www/ElanTextAblage_WP19/Drucksachen/"
    "Schriftliche%20Anfragen/19_0004490.pdf"
)
BY_2024_URL = (
    "https://www.bayern.landtag.de/www/ElanTextAblage_WP19/Drucksachen/"
    "Schriftliche%20Anfragen/19_0008767.pdf"
)
BE_URL = "https://pardok.parlament-berlin.de/starweb/adis/citat/VT/19/SchrAnfr/S19-23828.pdf"
HH_URL = (
    "https://www.buergerschaft-hh.de/parldok/dokument/93981/"
    "23_01111_auslaenderanteil_in_hamburger_justizvollzugsanstalten_2025_"
    "aktuelle_entwicklung_kosten_und_abschiebungen.pdf"
)

SOURCES = {
    "mv_85062": {
        "url": MV_URL,
        "title": "Landtag MV Drs 8/5062: Entwicklung der Kosten in den Justizvollzugsanstalten in Mecklenburg-Vorpommern (Antwort der Landesregierung, 12.07.2025)",
        "publisher": "Landtag Mecklenburg-Vorpommern / Landesregierung Mecklenburg-Vorpommern",
        "published": "2025-07-14",
        "license": AMTLICH_LANDTAG,
        "license_url": MV_URL,
        "attribution": "Landtag Mecklenburg-Vorpommern, Drucksache 8/5062",
        "land": "MV",
    },
    "nrw_185295": {
        "url": NRW_URL,
        "title": "Landtag NRW Vorlage 18/5295: Bericht des Justizministeriums, Tageshaftkosten je Gefangene/r (08.07.2026)",
        "publisher": "Landtag Nordrhein-Westfalen / Ministerium der Justiz des Landes Nordrhein-Westfalen",
        "published": "2026-07-08",
        "license": AMTLICH_LANDTAG,
        "license_url": NRW_URL,
        "attribution": "Landtag Nordrhein-Westfalen, Vorlage 18/5295",
        "land": "NW",
    },
    "by_194490": {
        "url": BY_2023_URL,
        "title": "Bayerischer Landtag Drs 19/4490: Inhaftierungspraxis und Kostensituation, Antwort des Staatsministeriums der Justiz",
        "publisher": "Bayerischer Landtag / Bayerisches Staatsministerium der Justiz",
        "published": "2024",
        "license": (
            "amtliches Werk, § 5 Abs. 2 UrhG (kein urheberrechtlicher Schutz; "
            "Änderungsverbot § 62 Abs. 1 bis 3 UrhG und Gebot der Quellenangabe "
            "§ 63 Abs. 1 und 2 UrhG). Official imprint: 'Drucksachen und "
            "Plenarprotokolle des Bayerischen Landtags genießen als amtliche Werke "
            "im Sinne des § 5 Abs. 2 UrhG keinen urheberrechtlichen Schutz'"
        ),
        "license_url": "https://www.bayern.landtag.de/impressum/",
        "attribution": "Bayerischer Landtag, Drucksache 19/4490",
        "land": "BY",
    },
    "by_198767": {
        "url": BY_2024_URL,
        "title": "Bayerischer Landtag Drs 19/8767: Belegungssituation der Justizvollzugsanstalten in Bayern, Antwort des Staatsministeriums der Justiz vom 31.10.2025",
        "publisher": "Bayerischer Landtag / Bayerisches Staatsministerium der Justiz",
        "published": "2025-10-31",
        "license": (
            "amtliches Werk, § 5 Abs. 2 UrhG (kein urheberrechtlicher Schutz; "
            "Änderungsverbot § 62 Abs. 1 bis 3 UrhG und Gebot der Quellenangabe "
            "§ 63 Abs. 1 und 2 UrhG). Official imprint: 'Drucksachen und "
            "Plenarprotokolle des Bayerischen Landtags genießen als amtliche Werke "
            "im Sinne des § 5 Abs. 2 UrhG keinen urheberrechtlichen Schutz'"
        ),
        "license_url": "https://www.bayern.landtag.de/impressum/",
        "attribution": "Bayerischer Landtag, Drucksache 19/8767",
        "land": "BY",
    },
    "be_1923828": {
        "url": BE_URL,
        "title": "Abgeordnetenhaus Berlin Drs 19/23828: Ersatzfreiheitsstrafen im Land Berlin seit 2021, Antwort der Senatsverwaltung für Justiz und Verbraucherschutz",
        "publisher": "Abgeordnetenhaus von Berlin / Senatsverwaltung für Justiz und Verbraucherschutz",
        "published": "2025-09-25",
        "license": AMTLICH_LANDTAG,
        "license_url": BE_URL,
        "attribution": "Abgeordnetenhaus von Berlin, Drucksache 19/23828",
        "land": "BE",
    },
    "hh_231111": {
        "url": HH_URL,
        "title": "Bürgerschaft Hamburg Drs 23/1111: Tageshaftkostensatz 2022–2024, Antwort des Senats",
        "publisher": "Bürgerschaft der Freien und Hansestadt Hamburg / Senat",
        "published": "2025-08-15",
        "license": (
            "amtliches Werk, § 5 UrhG, scoped to the cited Bürgerschaft document text only"
        ),
        "license_url": "https://www.buergerschaft-hh.de/parldok/lizenz.html",
        "attribution": "Bürgerschaft der Freien und Hansestadt Hamburg, Drucksache 23/1111",
        "land": "HH",
    },
}

# Official 16-Land THKS table in MV Drs 8/5062, PDF-S. 6. Thüringen 2022 was not transmitted.
MV_COMPARISON = [
    ("Baden-Württemberg", "BW", 147.24, 154.66),
    ("Bayern", "BY", 152.47, 154.23),
    ("Berlin", "BE", 218.36, 220.80),
    ("Brandenburg", "BB", 185.86, 201.16),
    ("Bremen", "HB", 166.72, 153.11),
    ("Hamburg", "HH", 215.49, 213.11),
    ("Hessen", "HE", 178.02, 176.72),
    ("Mecklenburg-Vorpommern", "MV", 174.77, 180.84),
    ("Niedersachsen", "NI", 182.53, 178.49),
    ("Nordrhein-Westfalen", "NW", 186.73, 192.07),
    ("Rheinland-Pfalz", "RP", 165.53, 155.83),
    ("Saarland", "SL", 130.53, 138.05),
    ("Sachsen", "SN", 150.72, 157.31),
    ("Sachsen-Anhalt", "ST", 187.25, 203.90),
    ("Schleswig-Holstein", "SH", 254.37, 257.04),
    ("Thüringen", "TH", None, 183.16),
    ("Durchschnitt", "DE", 179.77, 182.53),
]


def _im():
    from ingest.domains import institutions_media as im
    return im


def _fmt_de(value: float) -> str:
    if abs(value - round(value, 2)) < 1e-9:
        text = f"{value:.2f}"
    else:
        text = str(value)
    return text.replace(".", ",")


def mv_comparison_figures() -> list[dict]:
    rows = []
    for name, land, v2022, v2023 in MV_COMPARISON:
        entity_type = "de" if land == "DE" else "land"
        entity_id = "DE" if land == "DE" else land
        if v2022 is not None and v2023 is not None:
            quote = f"{name} {_fmt_de(v2022)} {_fmt_de(v2023)}"
        elif v2023 is not None:
            quote = "Thüringen1                               -                             183,16"
        else:
            continue
        for year, value in ((2022, v2022), (2023, v2023)):
            if value is None:
                continue
            rows.append({
                "source": "mv_85062",
                "entity_type": entity_type,
                "entity_id": entity_id,
                "metric": METRIC_THKS,
                "year": year,
                "value": value,
                "unit": "EUR_per_day",
                "locator": "PDF-S. 6, Tabelle Bundesländervergleich der THKS",
                "quote": quote,
                "note": SERIES_MV,
                "is_est": 0,
            })
    return rows


def mv_own_figures() -> list[dict]:
    # PDF-S. 2 own table; 2024 THKS is not in the comparison table.
    table = [
        (2022, 67_474_173.41, 174.77, "2022    67 474 173,41 Euro        44 383 556,73 Euro          23 090 616,68 Euro          174,77 Euro"),
        (2023, 66_632_579.17, 180.84, "2023    66 632 579,17 Euro        44 030 609,87 Euro          22 601 969,30 Euro          180,84 Euro"),
        (2024, 68_878_046.19, 188.98, "2024    68 878 046,19 Euro        49 156 831,33 Euro          19 721 214,86 Euro          188,98 Euro"),
    ]
    rows = []
    for year, total, thks, quote in table:
        rows.append({
            "source": "mv_85062",
            "entity_type": "land",
            "entity_id": "MV",
            "metric": METRIC_TOTAL,
            "year": year,
            "value": total,
            "unit": "EUR",
            "locator": "PDF-S. 2, Tabelle Gesamtkosten und THKS Justizvollzug MV",
            "quote": quote,
            "note": SERIES_MV_OWN,
        })
        rows.append({
            "source": "mv_85062",
            "entity_type": "land",
            "entity_id": "MV",
            "metric": METRIC_THKS_OWN,
            "year": year,
            "value": thks,
            "unit": "EUR_per_day",
            "locator": "PDF-S. 2, Tabelle Gesamtkosten und THKS Justizvollzug MV",
            "quote": quote,
            "note": SERIES_MV_OWN,
        })
    return rows


# NRW Vorlage 18/5295, PDF-S. 4. Methodology includes Baukostensatz from 2014
# (same break is footnoted in Justiz NRW, Justiz in Zahlen). Store 2014-2025 only.
NRW_ROWS = [
    (2014, 127.99, 3839.70, 46716.35),
    (2015, 133.55, 4006.50, 48745.75),
    (2016, 131.09, 3932.70, 47847.85),
    (2017, 135.65, 4069.50, 49512.25),
    (2018, 139.84, 4195.20, 51041.60),
    (2019, 145.71, 4371.30, 53184.15),
    (2020, 169.41, 5082.30, 61834.65),
    (2021, 178.91, 5367.30, 65302.15),
    (2022, 191.21, 5736.30, 69791.65),
    (2023, 199.07, 5972.10, 72660.55),
    (2024, 202.73, 6081.90, 73996.45),
    (2025, 215.17, 6455.10, 78537.05),
]


def _nrw_quote(year: int, daily: float, month: float, yearly: float) -> str:
    # Verbatim layout uses a thousands-dot and a decimal comma, plus the euro sign.
    def money(value: float) -> str:
        formatted = f"{value:,.2f}"  # 6,081.90
        formatted = formatted.replace(",", "X").replace(".", ",").replace("X", ".")
        return formatted + " €"

    daily_s = f"{daily:.2f}".replace(".", ",") + " €"
    return f"{year}             {daily_s}                  {money(month)}             {money(yearly)}"


def nrw_figures() -> list[dict]:
    rows = []
    for year, daily, month, yearly in NRW_ROWS:
        quote = _nrw_quote(year, daily, month, yearly)
        loc = "PDF-S. 4, Tabelle Tageshaftkosten je Gefangenem/r"
        base = {
            "source": "nrw_185295",
            "entity_type": "land",
            "entity_id": "NW",
            "locator": loc,
            "quote": quote,
            "note": SERIES_NRW,
        }
        rows.append({**base, "metric": METRIC_THKS_OWN, "year": year, "value": daily, "unit": "EUR_per_day"})
        rows.append({**base, "metric": METRIC_MONTH, "year": year, "value": month, "unit": "EUR_per_month"})
        rows.append({**base, "metric": METRIC_YEAR, "year": year, "value": yearly, "unit": "EUR_per_year"})
    return rows


def bayern_figures() -> list[dict]:
    return [
        {
            "source": "by_194490",
            "entity_type": "land",
            "entity_id": "BY",
            "metric": METRIC_TOTAL_DAILY,
            "year": 2023,
            "value": 185.32,
            "unit": "EUR_per_day",
            "locator": "PDF-S. 6, Antwort zu Frage 3.1",
            "quote": "im Jahr 2023 185,32 Euro pro Tag und Gefangenem",
            "note": SERIES_BY_TOTAL,
        },
        {
            "source": "by_194490",
            "entity_type": "land",
            "entity_id": "BY",
            "metric": METRIC_THKS_OWN,
            "year": 2023,
            "value": 154.23,
            "unit": "EUR_per_day",
            "locator": "PDF-S. 6, Antwort zu Frage 3.1",
            "quote": "Tageshaftkosten (154,23 Euro)",
            "note": SERIES_BY_THKS,
        },
        {
            "source": "by_194490",
            "entity_type": "land",
            "entity_id": "BY",
            "metric": METRIC_DAILY_BAU,
            "year": 2023,
            "value": 23.86,
            "unit": "EUR_per_day",
            "locator": "PDF-S. 6, Antwort zu Frage 3.1",
            "quote": "Bau-Investitionskostensatz (23,86 Euro)",
            "note": SERIES_BY_TOTAL,
        },
        {
            "source": "by_194490",
            "entity_type": "land",
            "entity_id": "BY",
            "metric": METRIC_DAILY_SACH,
            "year": 2023,
            "value": 7.24,
            "unit": "EUR_per_day",
            "locator": "PDF-S. 6, Antwort zu Frage 3.1",
            "quote": "Sach-Investitionskostensatz (7,24 Euro)",
            "note": SERIES_BY_TOTAL,
        },
        {
            "source": "by_198767",
            "entity_type": "land",
            "entity_id": "BY",
            "metric": METRIC_TOTAL,
            "year": 2024,
            "value": 661_500_000,
            "unit": "EUR",
            "locator": "PDF-S. 5, Antwort zu Frage 5.1",
            "quote": "Haushaltsjahr 2024 661,5 Mio. Euro",
            "note": "Gesamtkosten Justizvollzug, Epl. 04 Kap. 04 05 (Bayern Drs 19/8767)",
            "is_rounded": 1,
        },
        {
            "source": "by_198767",
            "entity_type": "land",
            "entity_id": "BY",
            "metric": METRIC_TOTAL_DAILY,
            "year": 2024,
            "value": 192.95,
            "unit": "EUR_per_day",
            "locator": "PDF-S. 5, Antwort zu Frage 5.2",
            "quote": "im Jahr 2024 unabhängig von der konkreten Haftart 192,95 Euro",
            "note": SERIES_BY_TOTAL,
        },
        {
            "source": "by_198767",
            "entity_type": "land",
            "entity_id": "BY",
            "metric": METRIC_THKS_OWN,
            "year": 2024,
            "value": 159.70,
            "unit": "EUR_per_day",
            "locator": "PDF-S. 5, Antwort zu Frage 5.2",
            "quote": "Tageshaftkosten (159,70 Euro)",
            "note": SERIES_BY_THKS,
        },
        {
            "source": "by_198767",
            "entity_type": "land",
            "entity_id": "BY",
            "metric": METRIC_DAILY_BAU,
            "year": 2024,
            "value": 27.98,
            "unit": "EUR_per_day",
            "locator": "PDF-S. 5, Antwort zu Frage 5.2",
            "quote": "Bau-Investitionskostensatz (27,98 Euro)",
            "note": SERIES_BY_TOTAL,
        },
        {
            "source": "by_198767",
            "entity_type": "land",
            "entity_id": "BY",
            "metric": METRIC_DAILY_SACH,
            "year": 2024,
            "value": 5.27,
            "unit": "EUR_per_day",
            "locator": "PDF-S. 5, Antwort zu Frage 5.2",
            "quote": "Sach-Investitionskostensatz (5,27 Euro)",
            "note": SERIES_BY_TOTAL,
        },
    ]


def berlin_figures() -> list[dict]:
    # Two tables: 2021/22 on PDF-S. 6, 2023/24 on PDF-S. 7.
    # Quotes use the start of the published row (the full row is in the PDF).
    specs = [
        (2021, METRIC_THKS_CAPACITY, 185.19, "EUR_per_day", SERIES_BE_CAP, 6,
         "Tageshaftkosten                   185,19 €"),
        (2021, METRIC_THKS_ACTUAL, 218.73, "EUR_per_day", SERIES_BE_ACT, 6,
         "Tageshaftkosten                   185,19 €        218,73 €"),
        (2022, METRIC_THKS_CAPACITY, 182.87, "EUR_per_day", SERIES_BE_CAP, 6,
         "182,87 €        218,36 €"),
        (2022, METRIC_THKS_ACTUAL, 218.36, "EUR_per_day", SERIES_BE_ACT, 6,
         "182,87 €        218,36 €"),
        (2021, METRIC_TOTAL_DAILY_CAPACITY, 191.29, "EUR_per_day", SERIES_BE_TOTAL_CAP, 6,
         "Gesamt-Tageshaftkosten            191,29 €"),
        (2021, METRIC_TOTAL_DAILY_ACTUAL, 225.93, "EUR_per_day", SERIES_BE_TOTAL_ACT, 6,
         "Gesamt-Tageshaftkosten            191,29 €        225,93 €"),
        (2022, METRIC_TOTAL_DAILY_CAPACITY, 191.88, "EUR_per_day", SERIES_BE_TOTAL_CAP, 6,
         "191,88 €        229,12 €"),
        (2022, METRIC_TOTAL_DAILY_ACTUAL, 229.12, "EUR_per_day", SERIES_BE_TOTAL_ACT, 6,
         "191,88 €        229,12 €"),
        (2021, METRIC_TOTAL, 278_503_305.72, "EUR", SERIES_BE_COST, 6,
         "278.503.305,72 €"),
        (2022, METRIC_TOTAL, 287_863_448.46, "EUR", SERIES_BE_COST, 6,
         "287.863.448,46 €"),
        (2023, METRIC_THKS_CAPACITY, 185.96, "EUR_per_day", SERIES_BE_CAP, 7,
         "Tageshaftkosten                    185,96 €"),
        (2023, METRIC_THKS_ACTUAL, 220.80, "EUR_per_day", SERIES_BE_ACT, 7,
         "Tageshaftkosten                    185,96 €         220,80 €"),
        (2024, METRIC_THKS_CAPACITY, 185.25, "EUR_per_day", SERIES_BE_CAP, 7,
         "185,25 €         223,48 €"),
        (2024, METRIC_THKS_ACTUAL, 223.48, "EUR_per_day", SERIES_BE_ACT, 7,
         "185,25 €         223,48 €"),
        (2023, METRIC_TOTAL_DAILY_CAPACITY, 193.20, "EUR_per_day", SERIES_BE_TOTAL_CAP, 7,
         "Gesamt-Tageshaftkosten             193,20 €"),
        (2023, METRIC_TOTAL_DAILY_ACTUAL, 229.40, "EUR_per_day", SERIES_BE_TOTAL_ACT, 7,
         "Gesamt-Tageshaftkosten             193,20 €         229,40 €"),
        (2024, METRIC_TOTAL_DAILY_CAPACITY, 188.13, "EUR_per_day", SERIES_BE_TOTAL_CAP, 7,
         "188,13 €         226,97 €"),
        (2024, METRIC_TOTAL_DAILY_ACTUAL, 226.97, "EUR_per_day", SERIES_BE_TOTAL_ACT, 7,
         "188,13 €         226,97 €"),
        (2023, METRIC_TOTAL, 296_245_622.01, "EUR", SERIES_BE_COST, 7,
         "296.245.622,01 €"),
        (2024, METRIC_TOTAL, 303_450_850.32, "EUR", SERIES_BE_COST, 7,
         "303.450.850,32 €"),
    ]
    rows = []
    for year, metric, value, unit, note, page, quote in specs:
        # "278.503.305,72 €" is close to a bare number; keep the published typography
        # but attach the row label in the locator.
        rows.append({
            "source": "be_1923828",
            "entity_type": "land",
            "entity_id": "BE",
            "metric": metric,
            "year": year,
            "value": value,
            "unit": unit,
            "locator": f"PDF-S. {page}, Tabelle Tagessätze Haushaltsjahre 2021 bis 2024, Zu 4.",
            "quote": quote,
            "note": note,
        })
    return rows


def hamburg_figures() -> list[dict]:
    return [
        {
            "source": "hh_231111",
            "entity_type": "land",
            "entity_id": "HH",
            "metric": METRIC_THKS_OWN,
            "year": year,
            "value": value,
            "unit": "EUR_per_day",
            "locator": "PDF-S. 4, Tabelle 5, Antwort zu Frage 7",
            "quote": f"{year}     {str(value).replace('.', ',')}",
            "note": SERIES_HH,
        }
        for year, value in ((2022, 215.67), (2023, 213.11), (2024, 204.21))
    ]


def all_figures() -> list[dict]:
    return (
        mv_comparison_figures()
        + mv_own_figures()
        + nrw_figures()
        + bayern_figures()
        + berlin_figures()
        + hamburg_figures()
    )


def store_cited_metric(conn, rec: dict, *, source_id: int, document_text: str, notes: list[str]) -> bool:
    """Store one metric only when the short quote is in the unmodified archived PDF."""
    quote = trim_quote(rec.get("quote"))
    metric = clean(rec.get("metric"))
    year = rec.get("year")
    value = rec.get("value")
    entity_type = clean(rec.get("entity_type"))
    entity_id = clean(rec.get("entity_id"))
    if not quote or not metric or year is None or value is None or not entity_type or not entity_id:
        notes.append(f"skipped prison-cost metric without quote/value/name/year: {metric}")
        return False
    try:
        amount = float(value)
    except (TypeError, ValueError):
        notes.append(f"skipped non-numeric prison-cost metric {metric}")
        return False
    if not quote_in_text(quote, document_text):
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
        "einheit": clean(rec.get("unit")) or "EUR",
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


def _register(conn, source_key: str, sources) -> int:
    meta = SOURCES[source_key]
    redistrib = 0
    return _im()._register_source(
        conn, meta["url"],
        title=meta["title"],
        publisher=meta["publisher"],
        license_=meta["license"],
        license_url=meta.get("license_url"),
        attribution=meta["attribution"],
        notes="Facts, metadata and short quotes only; full report text is not redistributed.",
        redistribute_fulltext=redistrib,
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
        "zusammenfassung": "Official prison-cost figures; facts and short quotes only.",
        "source_id": source_id,
    }, ["url"])


def _load_document(source_key: str, *, force: bool) -> str:
    meta = SOURCES[source_key]
    raw = fetch(meta["url"], domain=DOMAIN, force=force)
    path = raw_path(DOMAIN, meta["url"])
    if path.exists() and path.read_bytes()[:4] != b"%PDF":
        # Should not happen for these official PDF URLs.
        path.write_bytes(raw)
    text = document_text(path)
    if not text:
        raise RuntimeError(f"no extractable layout text for {meta['url']}")
    return text


def ingest_prison_costs(conn, cfg, sources, notes) -> int:
    """Fetch official PDFs and store cited prison-cost figures. Returns metric count."""
    force = bool(cfg.get("force"))
    texts: dict[str, str] = {}
    source_ids: dict[str, int] = {}
    for key in SOURCES:
        texts[key] = _load_document(key, force=force)
        source_ids[key] = _register(conn, key, sources)
        _store_doc(conn, key, source_ids[key])
    stored = 0
    missing = 0
    for rec in all_figures():
        key = rec["source"]
        if store_cited_metric(conn, rec, source_id=source_ids[key], document_text=texts[key], notes=notes):
            stored += 1
        else:
            missing += 1
    notes.append(
        f"prison_costs metrics={stored} quote_missing={missing} sources={len(SOURCES)}. "
        "Comparable THKS series is MV Drs 8/5062 (16 Länder, 2022-2023; Thüringen 2022 not transmitted; "
        "2024 comparison incomplete according to that answer). "
        "A Land's own official figures are stored as a separate series where they exist, including "
        "when they differ (e.g. Hamburg 2022 THKS 215,67 vs 215,49 in the comparison table; "
        "NRW 2023 199,07 vs 192,07). Berlin publishes two official methods "
        "(Belegungsfähigkeit vs tatsächliche Hafttage). "
        "No official complete 16-Land THKS table for 2024 was found. "
        "These are institution costs, not a crime rate, and are not framed as caused by homeless people."
    )
    return stored


if __name__ == "__main__":
    from ingest.common import no_direct_run
    raise SystemExit(no_direct_run("institutions_media"))
