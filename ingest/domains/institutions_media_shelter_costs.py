"""Official city/Land shelter costs per place or night (Drucksachen, Kostensätze).

Quotes are taken from the unmodified pdftotext -layout archive. Costs are stored
at city or Land AGS only. Women-/youth-/LGBTQ-only Träger stay at that level
with no street address. Hamburg örU rates are labelled as publicly-law
follow-on accommodation, not as Kältehilfe or Wohnungsnotfallhilfe.
"""

from __future__ import annotations

from ingest.common import clean, document_text, fetch, raw_path, upsert
from ingest.domains.institutions_media_press import press_robots_status
from ingest.domains.institutions_media_rechnungshof import RESERVED_LICENCE, quote_in_text, trim_quote

DOMAIN = "institutions_media"

AMTLICH = RESERVED_LICENCE
SATZUNG_LICENCE = (
    "Amtliches Werk, § 5 Abs. 1 UrhG: kommunale Satzung, amtlich bekanntgemacht; "
    "zitiert mit Fundstelle"
)
VORLAGE_LICENCE = (
    "Rechte vorbehalten: Rats-/Beschlussvorlage, kein Gesetz, keine Verordnung und kein Amtsblatt, "
    "daher nicht § 5 UrhG (Lead 2026-11-23: § 5 nur für Gesetze, Verordnungen, Erlasse, Amtsblätter "
    "und Gerichtsentscheidungen); nur Fakten, Metadaten und Kurzzitate nach § 51 UrhG, "
    "Volltext nicht weiterverbreitet"
)
DRUCKSACHE_LICENCE = (
    "Rechte vorbehalten: Parlamentsdrucksache der Bremischen Bürgerschaft, kein Gesetz, keine "
    "Verordnung und kein Amtsblatt, daher nicht § 5 UrhG (Lead 2026-11-23: § 5 nur für Gesetze, "
    "Verordnungen, Erlasse, Amtsblätter und Gerichtsentscheidungen); nur Fakten, Metadaten und "
    "Kurzzitate nach § 51 UrhG, Volltext nicht weiterverbreitet"
)

KOELN_IMPRESSUM = "https://www.stadt-koeln.de/service/kontakt/impressum"
BREMEN_IMPRESSUM = "https://static.bremische-buergerschaft.de/index02b6.html?id=93"
LEIPZIG_IMPRESSUM = "https://www.leipzig.de/impressum"
DRESDEN_IMPRESSUM = "https://www.dresden.de/impressum"
STUTTGART_IMPRESSUM = "https://www.stuttgart.de/impressum"
DUESSELDORF_IMPRESSUM = "https://www.duesseldorf.de/infonav/impressum"
KARLSRUHE_IMPRESSUM = "https://www.karlsruhe.de/impressum"
MANNHEIM_IMPRESSUM = "https://www.mannheim.de/impressum"

BE_URL = "https://pardok.parlament-berlin.de/starweb/adis/citat/VT/19/SchrAnfr/S19-22334.pdf"
MU_URL = "https://risi.muenchen.de/risi/dokument/v/9095607"
HH_URL = (
    "https://www.buergerschaft-hh.de/parldok/dokument/94592/"
    "23_01321_haushaltsplan_2025_2026_nachbewilligung_nach_35_der_landeshaushaltsordnung_"
    "fuer_das_haushaltsjahr_2025_in_den_einzelplaenen_4_behoerde_fuer_gesundheit.pdf"
)

SERIES_BE = "Berlin Senat, Drs 19/22334, Wohnungsnotfallhilfe (Antwort 28.04.2025)"
SERIES_MU = "Landeshauptstadt München, Sozialreferat, Anfrage 20-26/F 01095, Antwort 22.05.2025"
SERIES_HH = (
    "Hamburg Bürgerschaft Drs 23/1321, Kostensätze der öffentlich-rechtlichen "
    "Folgeunterbringung (örU; nicht Kältehilfe / Wohnungsnotfallhilfe). "
    "Notstandorte include Erstaufnahme places (footnote: four EA sites with 1.547 places and three örU sites with 196)."
)

SOURCES = {
    "be_s19_22334": {
        "url": BE_URL,
        "title": "Abgeordnetenhaus Berlin Drs 19/22334: Was kostet was in der Wohnungsnotfallhilfe? (Antwort 28.04.2025)",
        "publisher": "Senatsverwaltung für Arbeit, Soziales, Gleichstellung, Integration, Vielfalt und Antidiskriminierung",
        "published": "2025-04-28",
        "license": "dl-de/by-2-0",
        "license_url": "https://www.govdata.de/dl-de/by-2-0",
        "attribution": "Parlamentsdokumentation, Abgeordnetenhaus von Berlin, Drs 19/22334",
        "land": "BE",
    },
    "mu_f01095": {
        "url": MU_URL,
        "title": "Landeshauptstadt München, Sozialreferat, Schriftliche Anfrage 20-26/F 01095, Antwort 22.05.2025 (Bettplatzentgelte und Unterkünfte)",
        "publisher": "Landeshauptstadt München, Sozialreferat",
        "published": "2025-05-22",
        "license": RESERVED_LICENCE,
        "license_url": "https://stadt.muenchen.de/infos/impressum.html",
        "attribution": "Landeshauptstadt München, Sozialreferat, Antwort 22.05.2025 auf Anfrage 20-26/F 01095",
        "land": "BY",
    },
    "hh_23_1321": {
        "url": HH_URL,
        "title": "Bürgerschaft Hamburg Drs 23/1321, Nachbewilligung 2025, Einzelplan 4: Kostensätze und Kennzahlen der öffentlich-rechtlichen Unterbringung",
        "publisher": "Bürgerschaft der Freien und Hansestadt Hamburg / Senat",
        "published": "2025",
        "license": RESERVED_LICENCE,
        "license_url": "https://www.buergerschaft-hh.de/parldok/lizenz.html",
        "attribution": "Bürgerschaft der Freien und Hansestadt Hamburg, Drs 23/1321",
        "land": "HH",
    },
    "koeln_satzung_2024": {
        "url": "https://www.stadt-koeln.de/mediaasset/content/satzungen/satzung_zur_aenderung_der_gebuehrensatzung_obdachloseneinrichtungen_2024_04_05.pdf",
        "title": "Stadt Köln: Satzung zur Änderung der Satzung über die Erhebung von Gebühren für die Inanspruchnahme von Einrichtungen für obdachlose Personen vom 05. April 2024",
        "publisher": "Stadt Köln",
        "published": "2024-04-05",
        "license": SATZUNG_LICENCE,
        "license_url": KOELN_IMPRESSUM,
        "attribution": "Stadt Köln, Gebührensatzung Einrichtungen für obdachlose Personen, Änderung vom 05.04.2024 (ABl. Bekanntmachung 16.04.2024)",
        "land": "NW",
    },
    "koeln_satzung_2018": {
        "url": "https://www.stadt-koeln.de/mediaasset/content/satzungen/gebuehrensatzung_inanspruchnahme_einrichtungen_obdachlose_18-07-2018.pdf",
        "title": "Stadt Köln: Satzung über die Erhebung von Gebühren für die Inanspruchnahme von Einrichtungen für obdachlose Personen vom 18. Juli 2018",
        "publisher": "Stadt Köln",
        "published": "2018-07-18",
        "license": SATZUNG_LICENCE,
        "license_url": KOELN_IMPRESSUM,
        "attribution": "Stadt Köln, Gebührensatzung Einrichtungen für obdachlose Personen vom 18.07.2018 (ABl StK 2018, S. 298)",
        "land": "NW",
    },
    "koeln_vorlage_2690": {
        "url": "https://ratsinformation.stadt-koeln.de/getfile.asp?id=973457&type=do",
        "title": "Stadt Köln, RIS Beschlussvorlage 2690/2023/1 (März 2024): Änderung der Gebührensatzung für Einrichtungen für obdachlose Personen",
        "publisher": "Stadt Köln, Rat / Verwaltung",
        "published": "2024-03",
        "license": VORLAGE_LICENCE,
        "license_url": KOELN_IMPRESSUM,
        "attribution": "Stadt Köln, Beschlussvorlage 2690/2023/1",
        "land": "NW",
    },
    "hb_19_894": {
        "url": "https://static.bremische-buergerschaft.de/dokumente/wp19/land/drucksache/D19L0894.pdf",
        "title": "Bremische Bürgerschaft Drs 19/894: Antwort des Senats vom 10. Januar 2017 zu Kostensätzen der Wohnungslosen-Notunterkünfte",
        "publisher": "Senat der Freien Hansestadt Bremen / Bremische Bürgerschaft",
        "published": "2017-01-10",
        "license": DRUCKSACHE_LICENCE,
        "license_url": BREMEN_IMPRESSUM,
        "attribution": "Bremische Bürgerschaft, Drs 19/894, Antwort des Senats vom 10.01.2017",
        "land": "HB",
    },
    "leipzig_5_08": {
        "url": "https://www.leipzig.de/service-portal/satzungen/details/satzung/5-08/download",
        "title": "Stadt Leipzig, Satzung 5-08: Benutzungs- und Gebührensatzung für Unterkünfte für Wohnungslose, Asylbewerber und Spätaussiedler sowie andere ausländische Personen (in Kraft 01.07.2025)",
        "publisher": "Stadt Leipzig",
        "published": "2025-07-01",
        "license": SATZUNG_LICENCE,
        "license_url": LEIPZIG_IMPRESSUM,
        "attribution": "Stadt Leipzig, Satzung 5-08, Gebührenverzeichnis",
        "land": "SN",
    },
    "dresden_unterbringung": {
        "url": "https://www.dresden.de/media/pdf/satzungen/satzung-unterbringung.pdf",
        "title": "Landeshauptstadt Dresden, Ortsrecht 5.8: Satzung für die Unterbringung besonderer Bedarfsgruppen (Unterbringungssatzung) vom 10. April 2025",
        "publisher": "Landeshauptstadt Dresden",
        "published": "2025-04-10",
        "license": SATZUNG_LICENCE,
        "license_url": DRESDEN_IMPRESSUM,
        "attribution": "Landeshauptstadt Dresden, 5.8 Unterbringungssatzung vom 10.04.2025, Anlage 2 Gebührenverzeichnis (Amtsblatt e35-04-2025 vom 24.04.2025)",
        "land": "SN",
    },
    "stuttgart_4_12": {
        "url": "https://www.stuttgart.de/medien/ibs/4-12.pdf",
        "title": "Landeshauptstadt Stuttgart, Stadtrecht 4/12: Satzung über die Benutzung von Unterkünften des Sozialamts für Wohnungslose vom 17. Oktober 2019",
        "publisher": "Landeshauptstadt Stuttgart",
        "published": "2019-10-17",
        "license": SATZUNG_LICENCE,
        "license_url": STUTTGART_IMPRESSUM,
        "attribution": "Landeshauptstadt Stuttgart, Stadtrecht 4/12, Amtsblatt Nr. 43 vom 24.10.2019",
        "land": "BW",
    },
    "duesseldorf_54101": {
        "url": "https://www.duesseldorf.de/stadtrecht/5/54-migration-und-integration/54101-satzung-fuer-uebergangsheime-und-obdachlosenunterkuenfte-der-landeshauptstadt-duesseldorf",
        "title": "Landeshauptstadt Düsseldorf, Stadtrecht 54.101: Satzung für Übergangsheime und Obdachlosenunterkünfte vom 14. Januar 2008 (Gebühren zuletzt geändert 14.12.2017, in Kraft 01.01.2018)",
        "publisher": "Landeshauptstadt Düsseldorf",
        "published": "2018-01-01",
        "license": SATZUNG_LICENCE,
        "license_url": DUESSELDORF_IMPRESSUM,
        "attribution": "Landeshauptstadt Düsseldorf, Stadtrecht 54.101, § 3 Benutzungsgebühr (In-Kraft-Treten der Gebührenänderung 01.01.2018)",
        "land": "NW",
    },
    "karlsruhe_4_2": {
        "url": "https://www.karlsruhe.de/fileadmin/user_upload/01_Stadt_Rathaus/013_Verwaltung_und_Stadtpolitik/Stadtrecht/4_Soziale_Sicherung/4-2_Obdachlosenunterkuenfte.pdf",
        "title": "Stadt Karlsruhe, Stadtrecht 4/2: Satzung über die Unterhaltung von Obdachlosenunterkünften (Stand 1. Juli 2024)",
        "publisher": "Stadt Karlsruhe",
        "published": "2024-07-01",
        "license": SATZUNG_LICENCE,
        "license_url": KARLSRUHE_IMPRESSUM,
        "attribution": "Stadt Karlsruhe, Stadtrecht 4/2, § 3 Benutzungsgebühren (Stand 01.07.2024)",
        "land": "BW",
    },
    "mannheim_5_03": {
        "url": "https://www.mannheim.de/sites/default/files/page/2841/s05-03_102012.pdf",
        "title": "Stadt Mannheim, Stadtrecht 5.03: Gebührensatzung für die Unterkünfte der Wohnungslosenhilfe (in Kraft 01.09.2012)",
        "publisher": "Stadt Mannheim",
        "published": "2012-09-01",
        "license": SATZUNG_LICENCE,
        "license_url": MANNHEIM_IMPRESSUM,
        "attribution": "Stadt Mannheim, Stadtrecht 5.03, § 7 Gebührentarif (Amtsblatt Nr. 41 vom 10.10.2012)",
        "land": "BW",
    },
}

# Geography: city-states as Land AGS; Munich as official Kreisschlüssel of the kreisfreie Stadt.
GEO = {
    "BE": {"entity_type": "land", "entity_id": "11", "land": "BE", "kreis_ags": "11000"},
    "HH": {"entity_type": "land", "entity_id": "02", "land": "HH", "kreis_ags": "02000"},
    "MU": {"entity_type": "kreis", "entity_id": "09162", "land": "BY", "kreis_ags": "09162"},
    "K": {"entity_type": "kreis", "entity_id": "05315", "land": "NW", "kreis_ags": "05315"},
    "HB": {"entity_type": "kreis", "entity_id": "04011", "land": "HB", "kreis_ags": "04011"},
    "L": {"entity_type": "kreis", "entity_id": "14713", "land": "SN", "kreis_ags": "14713"},
    "DD": {"entity_type": "kreis", "entity_id": "14612", "land": "SN", "kreis_ags": "14612"},
    "S": {"entity_type": "kreis", "entity_id": "08111", "land": "BW", "kreis_ags": "08111"},
    "D": {"entity_type": "kreis", "entity_id": "05111", "land": "NW", "kreis_ags": "05111"},
    "KA": {"entity_type": "kreis", "entity_id": "08212", "land": "BW", "kreis_ags": "08212"},
    "MA": {"entity_type": "kreis", "entity_id": "08222", "land": "BW", "kreis_ags": "08222"},
}


def _im():
    from ingest.domains import institutions_media as im
    return im


def berlin_figures() -> list[dict]:
    return [
        dict(source="be_s19_22334", geo="BE", year=2025, period="Kältehilfe-Saison 2024/2025 (Antwort 28.04.2025)",
             metric="kaeltehilfe_avg_eur_per_place_day", value=31, unit="eur_per_platz_per_day", is_est=1, is_rounded=0,
             quote="In der vergangenen Saison betrugen die durchschnittlichen Kosten pro Platz rund 31,- €, der Medianwert lag bei rund 29,- €.",
             locator="PDF-S. 2, Zu 2.", note=SERIES_BE),
        dict(source="be_s19_22334", geo="BE", year=2025, period="Kältehilfe-Saison 2024/2025 (Antwort 28.04.2025)",
             metric="kaeltehilfe_median_eur_per_place_day", value=29, unit="eur_per_platz_per_day", is_est=1, is_rounded=0,
             quote="In der vergangenen Saison betrugen die durchschnittlichen Kosten pro Platz rund 31,- €, der Medianwert lag bei rund 29,- €.",
             locator="PDF-S. 2, Zu 2.", note=SERIES_BE),
        dict(source="be_s19_22334", geo="BE", year=2025, period="2025",
             metric="wnh_247_hallesches_ufer_eur_per_place_day", value=104, unit="eur_per_platz_per_day", is_est=1, is_rounded=0,
             quote="Für 2025 liegt die Plansumme der Kosten pro Platz am Tag bei rund 104,- €",
             locator="PDF-S. 2, Zu 3.", note=SERIES_BE + "; 24/7-Unterkunft am Halleschen Ufer (official label only, no street stored)."),
        dict(source="be_s19_22334", geo="BE", year=2025, period="2025",
             metric="wnh_247_hallesches_ufer_total_eur", value=2476379.31, unit="eur", is_est=0, is_rounded=0,
             quote="Gesamtkosten der 24/7 für 2025: 2.476.379,31€",
             locator="PDF-S. 2, Zu 3.", note=SERIES_BE),
        dict(source="be_s19_22334", geo="BE", year=2025, period="2025",
             metric="wnh_247_hallesches_ufer_places", value=65, unit="places", is_est=0, is_rounded=0,
             quote="für die ganzjährige Aufnahme und Unterbringung, Verpflegung und psychosoziale Beratung von 65 Personen",
             locator="PDF-S. 3, Zu 3.", note=SERIES_BE),
        dict(source="be_s19_22334", geo="BE", year=2024, period="2024",
             metric="wnh_247_hallesches_ufer_eur_per_place_day", value=102, unit="eur_per_platz_per_day", is_est=1, is_rounded=0,
             quote="In 2024 lag der Betrag bei rund 102,- €.",
             locator="PDF-S. 3, Zu 3.", note=SERIES_BE + "; 24/7-Unterkunft am Halleschen Ufer."),
        # ganzjährige NÜ, 2025 project table: each quote includes Träger, Plansumme and Tagessatz.
        *[_nu(*row) for row in _BERLIN_NU],
        dict(source="be_s19_22334", geo="BE", year=2023, period="2023",
             metric="wnh_s67_wuw_eur_per_day", value=26.19, unit="eur_per_day", is_est=0, is_rounded=0,
             quote="Wohnungserhalt und 26,19 € Wohnungserlangung (WuW)",
             locator="PDF-S. 4, Zu 5., Leistungstyp WuW", note=SERIES_BE + "; § 67 SGB XII Hilfen, durchschnittliche Leistungspauschale 2023."),
        dict(source="be_s19_22334", geo="BE", year=2023, period="2023",
             metric="wnh_s67_bew_eur_per_day", value=33.35, unit="eur_per_day", is_est=0, is_rounded=0,
             quote="Betreutes Einzelwohnen (BEW) 33,35 €",
             locator="PDF-S. 4, Zu 5., Leistungstyp BEW", note=SERIES_BE + "; § 67 SGB XII Hilfen, durchschnittliche Leistungspauschale 2023."),
        dict(source="be_s19_22334", geo="BE", year=2023, period="2023",
             metric="wnh_s67_beg_eur_per_day", value=40.09, unit="eur_per_day", is_est=0, is_rounded=0,
             quote="Betreutes Gruppenwohnen 40,09 € (BEG)",
             locator="PDF-S. 4, Zu 5., Leistungstyp BEG", note=SERIES_BE + "; § 67 SGB XII Hilfen, durchschnittliche Leistungspauschale 2023."),
        dict(source="be_s19_22334", geo="BE", year=2023, period="2023",
             metric="wnh_s67_ugh_eur_per_day", value=63.16, unit="eur_per_day", is_est=0, is_rounded=0,
             quote="Übergangshaus (ÜGH) 63,16 €",
             locator="PDF-S. 4, Zu 5., Leistungstyp ÜGH", note=SERIES_BE + "; § 67 SGB XII Hilfen, durchschnittliche Leistungspauschale 2023."),
        dict(source="be_s19_22334", geo="BE", year=2023, period="2023",
             metric="wnh_s67_krisen_clearing_eur_per_day", value=200, unit="eur_per_day", is_est=1, is_rounded=0,
             quote="Krisen- und Clearinghäuser knapp über 200,- €",
             locator="PDF-S. 4, Zu 5., Krisen- und Clearinghäuser", note=SERIES_BE + "; official wording 'knapp über 200,- €', stored as 200 with is_est=1."),
    ]


# (slug, traeger, plansumme_eur, tagessatz, quote, restricted)
# AWO quote spans two layout lines and is checked after whitespace folding.
_BERLIN_NU = [
    ("stadtmission_a", "Verein für Berliner Stadtmission", 1082732, 41,
     "Verein für Berliner Stadtmission 1.082.732 € 41 €", 0),
    ("strassenfeger", "Straßenfeger e. V.", 552769, 49,
     "Straßenfeger e. V. 552.769 € 49 €", 0),
    ("stadtmission_b", "Verein für Berliner Stadtmission", 1272950, 50,
     "Verein für Berliner Stadtmission 1.272.950 € 50 €", 0),
    ("awo_spree_wuhle", "AWO Arbeiterwohlfahrt Kreisverband Berlin Spree-Wuhle e. V.", 237608, 65,
     "AWO Arbeiterwohlfahrt Kreisverband Berlin Spree-Wuhle e. 237.608 € V. 65 €", 0),
    ("gebewo", "GEBEWO pro gGmbH", 319884, 97,
     "GEBEWO pro gGmbH 319.884 € 97 €", 0),
    ("koepjohann", "Koepjohann´sche Stiftung", 340137, 93,
     "Koepjohann´sche Stiftung 340.137 € 93 €", 0),
    ("skf", "Sozialdienst Katholischer Frauen e. V. Berlin", 672200, 61,
     "Sozialdienst Katholischer Frauen e. V. Berlin 672.200 € 61 €", 1),
    ("diakonie_stadtmitte", "Diakonisches Werk Berlin Stadtmitte e. V.", 698132, 64,
     "Diakonisches Werk Berlin Stadtmitte e. V. 698.132 € 64 €", 0),
    ("ejf", "Evangelisches Jugend- und Fürsorgewerk gAG", 1016642, 63,
     "Evangelisches Jugend- und Fürsorgewerk gAG 1.016.642 € 63 €", 0),
    ("johanniter_ohlauer", "Johanniter e.V. (Ohlauer 365)", 1600000, 50,
     "Johanniter e.V. (Ohlauer 365) 1.600.000 € 50 €", 0),
]


def _nu(slug, traeger, plansumme, tagessatz, quote, restricted) -> dict:
    return dict(
        source="be_s19_22334", geo="BE", year=2025, period="2025",
        metric=f"wnh_nu_tagessatz_{slug}_eur", value=tagessatz, unit="eur_per_platz_per_day",
        is_est=0, is_rounded=0, quote=quote,
        locator="PDF-S. 3, Zu 4., Tabelle Förderhöhe / Plansumme 2025",
        note=SERIES_BE + f"; ganzjährige Notunterkunft, Plansumme {plansumme} €, Tagessatz {tagessatz} €.",
        sidecar=True, traeger=traeger, plansumme=plansumme, restricted=restricted,
        offer_label=f"{traeger} (Plansumme {plansumme} €)",
    )


def munich_figures() -> list[dict]:
    common = dict(source="mu_f01095", geo="MU", year=2025, period="2025-05-22", is_est=0, is_rounded=0, note=SERIES_MU)
    return [
        dict(common, metric="muenchen_unterkuenfte_objects", value=58, unit="objects",
             quote="Des Weiteren gibt es vier sonstige Unterkünfte. Insgesamt handelt es sich um 58 Objekte.",
             locator="PDF-S. 2, Antwort zu Frage 1"),
        # Lead review 2026-11-21: muenchen_notquartiere_municipal dropped, the document gives the count only as a word (G5 needs digits)
        dict(common, metric="muenchen_flexi_heime", value=13, unit="objects",
             quote="Darunter fallen städtische Notquartiere (acht), Flexi-Heime der freien Träger (13), Clearinghäuser (sieben) und die gewerblichen Beherbergungsbetriebe (26).",
             locator="PDF-S. 2, Antwort zu Frage 1"),
        # Lead review 2026-11-21: muenchen_clearinghaeuser dropped, the document gives the count only as a word (G5 needs digits)
        dict(common, metric="muenchen_beherbergungsbetriebe", value=26, unit="objects",
             quote="Darunter fallen städtische Notquartiere (acht), Flexi-Heime der freien Träger (13), Clearinghäuser (sieben) und die gewerblichen Beherbergungsbetriebe (26).",
             locator="PDF-S. 2, Antwort zu Frage 1"),
        # Lead review 2026-11-21: muenchen_sonstige_unterkuenfte dropped, the document gives the count only as a word (G5 needs digits)
        dict(common, metric="muenchen_commercial_budget_eur", value=40500000, unit="eur",
             quote="Insgesamt steht der Landeshauptstadt München zur Finanzierung der Bettplätze in den gewerblichen Objekten ein Budget von 40.500.000 € zur Verfügung.",
             locator="PDF-S. 2, Antwort zu Frage 2"),
        dict(common, metric="muenchen_bettplatzentgelt_avg_eur_per_month", value=674, unit="eur_per_month",
             quote="Das durchschnittliche Bettplatzentgelt im Bestand der Beherbergungsbetriebe liegt derzeit bei 674,00 €.",
             locator="PDF-S. 2, Antwort zu Frage 4",
             note=SERIES_MU + "; monthly Bettplatzentgelt, not a nightly rate."),
        dict(common, metric="muenchen_bettplatzentgelt_cap_shared_eur_per_month", value=750, unit="eur_per_month",
             quote="Die Bettplatzentgelte waren dabei zuletzt gedeckelt auf 750,00 € (Wohnräume mit Gemeinschaftsanlagen) bzw. 800,00 € (abgeschlossene Wohnbereiche).",
             locator="PDF-S. 2, Antwort zu Frage 4",
             note=SERIES_MU + "; monthly cap, not a nightly rate."),
        dict(common, metric="muenchen_bettplatzentgelt_cap_selfcontained_eur_per_month", value=800, unit="eur_per_month",
             quote="Die Bettplatzentgelte waren dabei zuletzt gedeckelt auf 750,00 € (Wohnräume mit Gemeinschaftsanlagen) bzw. 800,00 € (abgeschlossene Wohnbereiche).",
             locator="PDF-S. 2, Antwort zu Frage 4",
             note=SERIES_MU + "; monthly cap, not a nightly rate."),
        dict(common, metric="muenchen_erwerbstaetigenhaus_single_eur_per_month", value=500, unit="eur_per_month",
             quote="500,00 € bei Einzelbelegung und 350,00 € p. P. bei Doppelbelegung.",
             locator="PDF-S. 3, Antwort zu Frage 6",
             note=SERIES_MU + "; monthly Bettplatzentgelt in Erwerbstätigenhäusern, not a nightly rate."),
        dict(common, metric="muenchen_erwerbstaetigenhaus_double_eur_per_month", value=350, unit="eur_per_month",
             quote="500,00 € bei Einzelbelegung und 350,00 € p. P. bei Doppelbelegung.",
             locator="PDF-S. 3, Antwort zu Frage 6",
             note=SERIES_MU + "; monthly Bettplatzentgelt in Erwerbstätigenhäusern, per person, not a nightly rate."),
        # Lead review 2026-11-21: muenchen_self_operated_objects dropped, the document gives the count only as a word (G5 needs digits)
        ]


def hamburg_figures() -> list[dict]:
    common = dict(source="hh_23_1321", geo="HH")
    return [
        dict(common, year=2025, period="2025", metric="oeru_hotel_eur_per_day", value=81, unit="eur_per_day",
             is_est=0, is_rounded=1,
             quote="Summe Hotelstandorte 173.800 5.873 81,-",
             locator="PDF-S. 6, Tabelle 3, Summe Hotelstandorte, Kostensatz je Tag 2025 (gerundet)",
             note=SERIES_HH),
        dict(common, year=2025, period="2025", metric="oeru_hotel_places", value=5873, unit="places",
             is_est=0, is_rounded=0,
             quote="Summe Hotelstandorte 173.800 5.873 81,-",
             locator="PDF-S. 6, Tabelle 3, prognostizierte durchschnittliche Platzkapazität 2025",
             note=SERIES_HH),
        dict(common, year=2025, period="2025", metric="oeru_hotel_transfer_tsd_eur", value=173800, unit="tsd_eur",
             is_est=0, is_rounded=0,
             quote="Summe Hotelstandorte 173.800 5.873 81,-",
             locator="PDF-S. 6, Tabelle 3, prognostizierte Kosten für Transferleistungen 2025 in Tsd. Euro",
             note=SERIES_HH),
        dict(common, year=2025, period="2025", metric="oeru_interims_eur_per_day", value=41, unit="eur_per_day",
             is_est=0, is_rounded=1,
             quote="Summe Interimsstand- 77.200 5.104 41,- orte",
             locator="PDF-S. 6, Tabelle 3, Summe Interimsstandorte, Kostensatz je Tag 2025 (gerundet)",
             note=SERIES_HH),
        dict(common, year=2025, period="2025", metric="oeru_interims_places", value=5104, unit="places",
             is_est=0, is_rounded=0,
             quote="Summe Interimsstand- 77.200 5.104 41,- orte",
             locator="PDF-S. 6, Tabelle 3, prognostizierte durchschnittliche Platzkapazität 2025",
             note=SERIES_HH),
        dict(common, year=2025, period="2025", metric="oeru_notstandorte_eur_per_day", value=43, unit="eur_per_day",
             is_est=0, is_rounded=1,
             quote="Summe Notstandorte 32.800 2.107 43,-",
             locator="PDF-S. 6, Tabelle 3, Summe Notstandorte, Kostensatz je Tag 2025 (gerundet)",
             note=SERIES_HH),
        dict(common, year=2025, period="2025", metric="oeru_notstandorte_places", value=2107, unit="places",
             is_est=0, is_rounded=0,
             quote="Summe Notstandorte 32.800 2.107 43,-",
             locator="PDF-S. 6, Tabelle 3, prognostizierte durchschnittliche Platzkapazität 2025",
             note=SERIES_HH),
        dict(common, year=2025, period="2025", metric="oeru_total_transfer_tsd_eur", value=180000, unit="tsd_eur",
             is_est=0, is_rounded=0,
             quote="Insgesamt 180.000 13.083",
             locator="PDF-S. 6, Tabelle 3, Insgesamt, Transferleistungen 2025 in Tsd. Euro",
             note=SERIES_HH),
        dict(common, year=2025, period="2025", metric="oeru_total_places", value=13083, unit="places",
             is_est=0, is_rounded=0,
             quote="Insgesamt 180.000 13.083",
             locator="PDF-S. 6, Tabelle 3, Insgesamt, prognostizierte durchschnittliche Platzkapazität 2025",
             note=SERIES_HH),
        dict(common, year=2025, period="2025", metric="oeru_mehrbedarf_tsd_eur", value=119500, unit="tsd_eur",
             is_est=0, is_rounded=0,
             quote="Mehrbedarf 119.500",
             locator="PDF-S. 6, Tabelle 3, Mehrbedarf",
             note=SERIES_HH),
        dict(common, year=2024, period="2024", metric="oeru_hotel_eur_per_day", value=83, unit="eur_per_day",
             is_est=0, is_rounded=1,
             quote="orte (2024: 83,- Euro) und die Interimsstandorte",
             locator="PDF-S. 6, Text nach Tabelle 3 (two-column layout), 2024 Kostensatz",
             note=SERIES_HH),
        dict(common, year=2024, period="2024", metric="oeru_interims_eur_per_day", value=48, unit="eur_per_day",
             is_est=0, is_rounded=1,
             quote="(2024: 48,- Euro) einschließlich Catering",
             locator="PDF-S. 6, Text nach Tabelle 3 (two-column layout), 2024 Kostensatz",
             note=SERIES_HH),
        dict(common, year=2025, period="2025", metric="pg253_wohnungslose_places", value=5050, unit="places",
             is_est=0, is_rounded=0,
             quote="B_253_03_011 Anzahl der durch Wohnungslose genutzten Plätze ANZ 5.050,00 0,00 5.050,00 5.050,00 0,00 5.050,00",
             locator="PDF-S. 19, Kennzahlen der Produktgruppe 253.03, Fort. Plan neu 2025",
             note=SERIES_HH + " Kennzahl of PG 253.03 Wohnungslosenhilfe u. öffentl. Unt."),
    ]



SERIES_K24 = "Stadt Köln, Gebührensatzung Einrichtungen für obdachlose Personen, Änderung vom 05.04.2024"
SERIES_K18 = "Stadt Köln, Gebührensatzung Einrichtungen für obdachlose Personen vom 18.07.2018"
SERIES_HB = "Bremische Bürgerschaft Drs 19/894, Senatsantwort 10.01.2017, Kostensätze 2017 (nicht die 2013er Tagessätze und nicht die Nettoaufwendungen 2023/2024)"
SERIES_L = "Stadt Leipzig, Satzung 5-08, Gebührenverzeichnis (in Kraft 01.07.2025)"
SERIES_DD = "Landeshauptstadt Dresden, 5.8 Unterbringungssatzung vom 10.04.2025, Anlage 2, Personenkreis § 1 Abs. 2 Buchstabe a)"
SERIES_S = "Landeshauptstadt Stuttgart, Stadtrecht 4/12 vom 17.10.2019, § 13"
SERIES_D = "Landeshauptstadt Düsseldorf, Stadtrecht 54.101, § 3 (Gebühren in Kraft 01.01.2018); Ziff. 3 = Obdachlose"
SERIES_KA = "Stadt Karlsruhe, Stadtrecht 4/2, § 3 (Stand 01.07.2024)"
SERIES_MA = "Stadt Mannheim, Stadtrecht 5.03, § 7 (in Kraft 01.09.2012)"


def cologne_figures() -> list[dict]:
    k24 = dict(source="koeln_satzung_2024", geo="K", year=2024, period="2024")
    k18 = dict(source="koeln_satzung_2018", geo="K", year=2018, period="2018")
    return [
        dict(k24, metric="koeln_amsterdamer_str_eur_per_person_per_month", value=50,
             unit="eur_per_person_per_month",
             quote="Die Benutzungsgebühr für das Projekt Amsterdamer Str. 149, 50735 Köln, beträgt 50,00 € monatlich pro Personen.",
             locator="PDF-S. 3, § 3 Abs. 4",
             note=SERIES_K24 + "; monthly fee per person, not a nightly rate."),
        dict(k24, metric="koeln_winterberger_str_9_eur_per_m2_per_month", value=12.50,
             unit="eur_per_m2_per_month",
             quote="Die Benutzungsgebühr für das Wohn- und Arbeitsprojekt in der Winterberger Str. 9 beträgt monatlich 12,50 € pro qm.",
             locator="PDF-S. 3, § 3 Abs. 5",
             note=SERIES_K24 + "; official unit is per m² per month, not converted to a per-place rate."),
        dict(k24, metric="koeln_brand_katastrophenschutz_eur_per_m2_per_month", value=11.53,
             unit="eur_per_m2_per_month",
             quote="a) Brühler Str. 267-269, 50968 Köln 11,53 €/qm monatlich",
             locator="PDF-S. 3, § 3 Abs. 6 lit. a",
             note=SERIES_K24 + "; same 11,53 €/qm monthly rate also at Boltensternstr. 2-4; official unit is per m² per month."),
        dict(k24, metric="koeln_einfachst_baracken_eur_per_m2_per_month", value=4.10,
             unit="eur_per_m2_per_month",
             quote="Die Benutzungsgebühr für die Einfachst-Baracken in der Siedlungsanlage Egonstraße/Stammheimer Ring beträgt monatlich 4,10 € pro qm.",
             locator="PDF-S. 3, § 3 Abs. 7",
             note=SERIES_K24 + "; official unit is per m² per month, not converted to a per-place rate."),
        dict(k24, metric="koeln_wohnen_auf_zeit_eur_per_m2_per_month", value=12.90,
             unit="eur_per_m2_per_month",
             quote="beträgt monatlich 12,90 € plus 0,92 € Heizosten pro qm",
             locator="PDF-S. 3, § 3 Abs. 8",
             note=SERIES_K24 + "; official wording is 'Heizosten'; unit is per m² per month."),
        dict(k24, metric="koeln_wohnen_auf_zeit_heating_eur_per_m2_per_month", value=0.92,
             unit="eur_per_m2_per_month",
             quote="beträgt monatlich 12,90 € plus 0,92 € Heizosten pro qm",
             locator="PDF-S. 3, § 3 Abs. 8",
             note=SERIES_K24 + "; heating component; official wording is 'Heizosten'; unit is per m² per month."),
        dict(k24, metric="koeln_wohnen_auf_zeit_furniture_eur_per_unit_per_month", value=33.58,
             unit="eur_per_unit_per_month",
             quote="Möblierungspauschale in Höhe von monatlich 33,58 € pro Unterkunft.",
             locator="PDF-S. 3, § 3 Abs. 8",
             note=SERIES_K24 + "; monthly furniture flat rate per Unterkunft, not a full place rate."),
        dict(k24, metric="koeln_anlage_min_gesamt_eur_per_m2_per_month", value=5.20,
             unit="eur_per_m2_per_month",
             quote="Escher Str. 154 5,20 € 0,00 € 5,20 €",
             locator="PDF-S. 5, Anlage, Gesamtgebühr je qm/Monat",
             note=SERIES_K24 + "; lowest Gesamtgebühr in the official annex (also Lilienthalstr. 34 and Xantener Str. 72); unit is per m² per month."),
        dict(k24, metric="koeln_anlage_max_gesamt_eur_per_m2_per_month", value=14.20,
             unit="eur_per_m2_per_month",
             quote="Ostmerheimer Str. 712 12,20 € 2,00 € 14,20 €",
             locator="PDF-S. 6, Anlage, Gesamtgebühr je qm/Monat",
             note=SERIES_K24 + "; highest Gesamtgebühr in the official annex; unit is per m² per month."),
        dict(k18, metric="koeln_amsterdamer_str_eur_per_person_per_month", value=50,
             unit="eur_per_person_per_month",
             quote="Die Benutzungsgebühr für das Projekt Amsterdamer Str. 149, 50735 Köln, beträgt 50,00 € pro Person.",
             locator="PDF-S. 2, § 3 Abs. 3",
             note=SERIES_K18 + "; in the monthly Gebührenhöhe section; not a nightly rate."),
        dict(k18, metric="koeln_brand_katastrophenschutz_bruehler_eur_per_m2_per_month", value=10.03,
             unit="eur_per_m2_per_month",
             quote="a) Brühler Str. 267-269, 50968 Köln 10,03 EUR/qm monatlich",
             locator="PDF-S. 2, § 3 Abs. 4 lit. a",
             note=SERIES_K18 + "; official unit is per m² per month."),
        dict(k18, metric="koeln_brand_katastrophenschutz_boltenstern_eur_per_m2_per_month", value=5.21,
             unit="eur_per_m2_per_month",
             quote="b) Boltensternstr. 2 - 4, 50735 Köln 5,21 EUR/qm monatlich",
             locator="PDF-S. 2, § 3 Abs. 4 lit. b",
             note=SERIES_K18 + "; official unit is per m² per month."),
        dict(k18, metric="koeln_anlage_min_gesamt_eur_per_m2_per_month", value=4.55,
             unit="eur_per_m2_per_month",
             quote="Escher Str. 154 4,29 € 0,26 € 4,55 €",
             locator="PDF-S. 3, Anlage, Gesamtgebühr je qm/Monat",
             note=SERIES_K18 + "; lowest Gesamtgebühr in the official annex; unit is per m² per month."),
        dict(k18, metric="koeln_anlage_max_gesamt_eur_per_m2_per_month", value=12.59,
             unit="eur_per_m2_per_month",
             quote="Ostmerheimer Str. 712 7,58 € 5,01 € 12,59 €",
             locator="PDF-S. 3, Anlage, Gesamtgebühr je qm/Monat",
             note=SERIES_K18 + "; highest Gesamtgebühr in the official annex; unit is per m² per month."),
    ]


def bremen_2017_figures() -> list[dict]:
    common = dict(source="hb_19_894", geo="HB", year=2017, period="2017")
    range_q = "zwischen 51,01 ‡ und 136,65 ‡."
    hotel_q = "Kosten von 16 ‡ bis ca. 40 ‡ an, im Einzelfall bis 45 ‡ pro Person und Nacht."
    note = SERIES_HB + "; unit is per person per night as the Senate answers it. pdftotext -layout of the official PDF renders the euro sign as ‡."
    return [
        dict(common, metric="hb_nu_eur_per_person_per_night_min", value=51.01,
             unit="eur_per_person_per_night", quote=range_q,
             locator="PDF-S. 3, Antwort zu Frage 5", note=note),
        dict(common, metric="hb_nu_eur_per_person_per_night_max", value=136.65,
             unit="eur_per_person_per_night", quote=range_q,
             locator="PDF-S. 3, Antwort zu Frage 5", note=note),
        dict(common, metric="hb_hotel_pension_eur_per_person_per_night_min", value=16,
             unit="eur_per_person_per_night", is_est=1, quote=hotel_q,
             locator="PDF-S. 3, Antwort zu Frage 5", note=note),
        dict(common, metric="hb_hotel_pension_eur_per_person_per_night_ca_max", value=40,
             unit="eur_per_person_per_night", is_est=1, quote=hotel_q,
             locator="PDF-S. 3, Antwort zu Frage 5",
             note=note + " The document says 'ca. 40'."),
        dict(common, metric="hb_hotel_pension_eur_per_person_per_night_einzel", value=45,
             unit="eur_per_person_per_night", is_est=1, quote=hotel_q,
             locator="PDF-S. 3, Antwort zu Frage 5",
             note=note + " 'im Einzelfall'."),
    ]


def leipzig_figures() -> list[dict]:
    return [
        dict(source="leipzig_5_08", geo="L", year=2025, period="2025",
             metric="leipzig_gemeinschaftsunterkunft_eur_per_person_per_night",
             value=5, unit="eur_per_person_per_night",
             quote="Gemeinschaftsunterkunft für Wohnungslose Personen gem. § 1 5,00 Euro Abs. 2 pro Person und Nacht",
             locator="PDF-S. 12, Gebührenverzeichnis",
             note=SERIES_L + "; per person per night for the communal homeless shelter, not a monthly rate."),
    ]


def dresden_figures() -> list[dict]:
    common = dict(source="dresden_unterbringung", geo="DD", year=2025, period="2025")
    note = SERIES_DD + "; fees for involuntarily homeless persons."
    return [
        dict(common, metric="dresden_uebergangswohnheim_eur_per_person_per_month",
             value=1104.03, unit="eur_per_person_per_month",
             quote="1.1 Nutzung von Unterbringungseinrichtungen nach § 3 1.104,03 EUR",
             locator="PDF-S. 20, Anlage 2 Gebührenverzeichnis Nr. 1.1",
             note=note + " Übergangswohnheime (§ 3); per person per month, not a nightly rate."),
        dict(common, metric="dresden_gewaehrleistungswohnung_eur_per_person_per_month",
             value=431.90, unit="eur_per_person_per_month",
             quote="Nutzung von Unterbringungseinrichtungen nach §§ 4, 431,90 EUR",
             locator="PDF-S. 20, Anlage 2 Gebührenverzeichnis Nr. 1.2",
             note=note + " Gewährleistungswohnungen / sonstige nach §§ 4, 6 Abs. 2; per person per month."),
        dict(common, metric="dresden_hoehere_gewalt_eur_per_person_per_day",
             value=20, unit="eur_per_person_per_day",
             quote="1.3 Nutzung von Unterbringungseinrichtungen nach § 5 20,00 EUR pro Tag",
             locator="PDF-S. 20, Anlage 2 Gebührenverzeichnis Nr. 1.3",
             note=note + " Unterbringung infolge höherer Gewalt (§ 5); official unit is per person per day, not per month."),
    ]


def stuttgart_figures() -> list[dict]:
    common = dict(source="stuttgart_4_12", geo="S", year=2019, period="2019")
    note = SERIES_S + "; official unit is per m² per month, not converted to a per-place rate."
    return [
        dict(common, metric="stuttgart_wohnung_eur_per_m2_per_month", value=15.23,
             unit="eur_per_m2_per_month",
             quote="in den Wohnungen nach § 1 Abs. 4 Satz 2 15,23 EUR/qm",
             locator="PDF-S. 7, § 13 Abs. 2 Nr. 1", note=note),
        dict(common, metric="stuttgart_wohnheim_eur_per_m2_per_month", value=10.52,
             unit="eur_per_m2_per_month",
             quote="in Wohnheimen nach § 1 Abs. 4 Satz 3 10,52 EUR/qm",
             locator="PDF-S. 7, § 13 Abs. 2 Nr. 1", note=note),
        dict(common, metric="stuttgart_wohnung_selfpay_eur_per_m2_per_month", value=11.40,
             unit="eur_per_m2_per_month",
             quote="in den Wohnungen nach § 1 Abs. 4 Satz 2 11,40 EUR/qm",
             locator="PDF-S. 7, § 13 Abs. 2 Nr. 2",
             note=note + " Reduced Selbstzahler rate."),
        dict(common, metric="stuttgart_wohnheim_selfpay_eur_per_m2_per_month", value=7.40,
             unit="eur_per_m2_per_month",
             quote="in Wohnheimen nach § 1 Abs. 4 Satz 3 7,40 EUR/qm",
             locator="PDF-S. 7, § 13 Abs. 2 Nr. 2",
             note=note + " Reduced Selbstzahler rate."),
    ]


def duesseldorf_figures() -> list[dict]:
    common = dict(source="duesseldorf_54101", geo="D", year=2018, period="2018")
    note = SERIES_D + "; official unit is per m² per month, not converted to a per-place rate."
    return [
        dict(common, metric="duesseldorf_obdach_standard_eur_per_m2_per_month", value=6.25,
             unit="eur_per_m2_per_month",
             quote="in Unterkünften für Personen nach § 1 (1) Ziff. 3 - Standard 6,25 EUR",
             locator="HTML, § 3 Abs. 2 lit. c", note=note),
        dict(common, metric="duesseldorf_obdach_gehoben_eur_per_m2_per_month", value=6.80,
             unit="eur_per_m2_per_month",
             quote="- gehobener Standard 6,80 EUR",
             locator="HTML, § 3 Abs. 2 lit. c", note=note),
        dict(common, metric="duesseldorf_obdach_neben_eur_per_m2_per_month", value=1.92,
             unit="eur_per_m2_per_month",
             quote="(c) in Unterkünften für Personen nach § 1 (1) Ziff. 3 - Nebenkostenpauschale 1,92 EUR",
             locator="HTML, § 3 Abs. 3 lit. c", note=note),
        dict(common, metric="duesseldorf_obdach_heiz_eur_per_m2_per_month", value=1.10,
             unit="eur_per_m2_per_month",
             quote="Ziff. 3 - Nebenkostenpauschale 1,92 EUR - Heizkostenpauschale 1,10 EUR",
             locator="HTML, § 3 Abs. 3 lit. c", note=note),
    ]


def karlsruhe_figures() -> list[dict]:
    common = dict(source="karlsruhe_4_2", geo="KA", year=2024, period="2024")
    note = SERIES_KA + "; official unit is per place or person per calendar month."
    return [
        dict(common, metric="karlsruhe_einzelzimmer_eur_per_place_per_month", value=500,
             unit="eur_per_place_per_month",
             quote="Die Benutzungsgebühren betragen je Unterbringungsplatz und Kalendermonat: 1. für ein Einzelzimmer 500 Euro",
             locator="PDF-S. 2, § 3 Abs. 2 Nr. 1", note=note),
        dict(common, metric="karlsruhe_mehrbett_eur_per_person_per_month", value=400,
             unit="eur_per_person_per_month",
             quote="2. für ein Mehrbettzimmer 400 Euro pro Person",
             locator="PDF-S. 2, § 3 Abs. 2 Nr. 2", note=note),
        dict(common, metric="karlsruhe_mehrbett_further_eur_per_person_per_month", value=250,
             unit="eur_per_person_per_month",
             quote="ab der zweiten Person für jede weitere Person 250 Euro.",
             locator="PDF-S. 2, § 3 Abs. 3",
             note=note + " Reduced rate for further persons in an SGB/AsylbLG Bedarfsgemeinschaft."),
        dict(common, metric="karlsruhe_family_cap_eur_per_month", value=1000,
             unit="eur_per_month",
             quote="insgesamt maximal 1.000 Euro.",
             locator="PDF-S. 2, § 3 Abs. 4",
             note=note + " Family cap for SGB/AsylbLG households with at least one minor child."),
    ]


def mannheim_figures() -> list[dict]:
    common = dict(source="mannheim_5_03", geo="MA", year=2012, period="2012")
    return [
        dict(common, metric="mannheim_eur_per_m2_per_person_per_month", value=16,
             unit="eur_per_m2_per_person_per_month",
             quote="je Person und Monat pro selbstbewohntem Quadratmeter 16,00 €.",
             locator="PDF-S. 2, § 7 Abs. 1",
             note=SERIES_MA + "; official unit is per person per month per self-occupied m², not converted to a flat per-place rate."),
        dict(common, metric="mannheim_notuebernachtung_eur_per_person_per_day", value=21,
             unit="eur_per_person_per_day",
             quote="Für die Notübernachtungsstelle sind je Person und Tag für Nachtessen, Übernachtung und Frühstück 21,00 € zu entrichten.",
             locator="PDF-S. 2, § 7 Abs. 3",
             note=SERIES_MA + "; per person per day in the emergency overnight shelter, including supper, lodging and breakfast."),
    ]


def all_figures() -> list[dict]:
    return (
        berlin_figures() + munich_figures() + hamburg_figures()
        + cologne_figures() + bremen_2017_figures() + leipzig_figures()
        + dresden_figures() + stuttgart_figures() + duesseldorf_figures()
        + karlsruhe_figures() + mannheim_figures()
    )


def ensure_shelter_cost_table(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS institutions_media_shelter_cost (
          id INTEGER PRIMARY KEY,
          official_key TEXT NOT NULL UNIQUE,
          traeger TEXT,
          offer_label TEXT,
          land TEXT,
          kreis_ags TEXT,
          year INTEGER,
          value REAL,
          einheit TEXT,
          plansumme_eur REAL,
          restricted_group INTEGER NOT NULL DEFAULT 0,
          quote TEXT,
          locator TEXT,
          source_id INTEGER NOT NULL,
          FOREIGN KEY(source_id) REFERENCES source(id)
        )
        """
    )


def _fmt_value(value) -> str:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return ""
    return str(int(v)) if v.is_integer() else f"{v:.2f}".replace(".", ",")


def store_cited_metric(conn, rec: dict, *, source_id: int, document_text: str, notes: list[str]) -> bool:
    quote = trim_quote(rec.get("quote"))
    full = clean(rec.get("quote"))
    if quote and full and quote != full and len(full) <= 240 and _fmt_value(rec.get("value")) not in quote:
        # Lead review 2026-11-21: trim_quote splits table rows at 'e. V.'; keep the short verbatim row so the
        # stored quote still shows the value it evidences.
        quote = full
    metric = clean(rec.get("metric"))
    year = rec.get("year")
    value = rec.get("value")
    entity_type = clean(rec.get("entity_type"))
    entity_id = clean(rec.get("entity_id"))
    if not quote or not metric or year is None or value is None or not entity_type or not entity_id:
        notes.append(f"skipped shelter-cost metric without quote/value/name/year: {metric}")
        return False
    try:
        amount = float(value)
    except (TypeError, ValueError):
        notes.append(f"skipped non-numeric shelter-cost metric {metric}")
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
        "einheit": clean(rec.get("unit")) or "eur",
        "year": int(year),
        "period": clean(rec.get("period")),
        "is_est": 1 if rec.get("is_est") else 0,
        "is_rounded": 1 if rec.get("is_rounded") else 0,
        "anmerkung": clean(rec.get("note")),
        "quote": quote,
        "locator": clean(rec.get("locator")),
        "source_id": source_id,
    }, ["entity_type", "entity_id", "metric", "year"])
    return True


def _with_geo(rec: dict) -> dict:
    geo = GEO[rec["geo"]]
    out = dict(rec)
    out["entity_type"] = geo["entity_type"]
    out["entity_id"] = geo["entity_id"]
    out["land"] = geo["land"]
    out["kreis_ags"] = geo["kreis_ags"]
    return out


def _register(conn, source_key: str, sources) -> int:
    meta = SOURCES[source_key]
    return _im()._register_source(
        conn, meta["url"],
        title=meta["title"],
        publisher=meta["publisher"],
        license_=meta["license"],
        license_url=meta.get("license_url"),
        attribution=meta["attribution"],
        notes="Facts, metadata and short quotes only; full text is not redistributed.",
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
        "zusammenfassung": "Official shelter or public-accommodation cost figures; facts and short quotes only.",
        "source_id": source_id,
    }, ["url"])


def cost_robots_status(url: str) -> tuple[bool, str, float | None]:
    """Fail-closed robots.txt decision, reusing the press/counts_law checker."""
    return press_robots_status(url)


class RobotsBlocked(RuntimeError):
    """Raised when fail-closed robots.txt says this official URL must be skipped."""


def _load_document(source_key: str, *, force: bool) -> str:
    meta = SOURCES[source_key]
    ok, reason, _delay = cost_robots_status(meta["url"])
    if not ok:
        raise RobotsBlocked(f"robots fail-closed skip {meta['url']}: {reason}")
    fetch(meta["url"], domain=DOMAIN, force=force)
    path = raw_path(DOMAIN, meta["url"])
    text = document_text(path)
    if not text:
        raise RuntimeError(f"no extractable layout text for {meta['url']}")
    return text


def ingest_shelter_costs(conn, cfg, sources, notes) -> int:
    force = bool(cfg.get("force"))
    ensure_shelter_cost_table(conn)
    texts, source_ids = {}, {}
    for key in SOURCES:
        try:
            texts[key] = _load_document(key, force=force)
        except RobotsBlocked as exc:
            notes.append(str(exc))
            continue
        source_ids[key] = _register(conn, key, sources)
        _store_doc(conn, key, source_ids[key])

    stored = missing = sidecar = 0
    for raw in all_figures():
        rec = _with_geo(raw)
        key = rec["source"]
        if key not in texts:
            notes.append(
                f"skipped shelter-cost metric {rec.get('metric')}; "
                "source was not loaded (robots fail-closed or fetch skipped)"
            )
            missing += 1
            continue
        text = texts[key]
        if store_cited_metric(conn, rec, source_id=source_ids[key], document_text=text, notes=notes):
            stored += 1
        else:
            missing += 1
            continue
        if rec.get("sidecar"):
            official_key = f"{rec['land']}-SC:{rec['metric']}:{rec['year']}"
            upsert(conn, "institutions_media_shelter_cost", {
                "official_key": official_key,
                "traeger": rec.get("traeger"),
                "offer_label": rec.get("offer_label"),
                "land": rec["land"],
                "kreis_ags": rec["kreis_ags"],
                "year": rec["year"],
                "value": rec["value"],
                "einheit": rec["unit"],
                "plansumme_eur": rec.get("plansumme"),
                "restricted_group": 1 if rec.get("restricted") else 0,
                "quote": trim_quote(rec.get("quote")),
                "locator": rec["locator"],
                "source_id": source_ids[key],
            }, ["official_key"])
            sidecar += 1
    notes.append(
        f"shelter_costs metrics={stored} quote_missing={missing} sidecar={sidecar}. "
        "Berlin Drs 19/22334 (Wohnungsnotfallhilfe / Kältehilfe / § 67), Munich Sozialreferat "
        "F 01095 (monthly Bettplatzentgelte, not converted to a nightly rate), and Hamburg "
        "Drs 23/1321 örU Kostensätze (explicitly not labelled as Kältehilfe). "
        "ASOG daily costs in Berlin are an official gap (Senate has no data). "
        "Berlin Kältehilfe, NU Tagessätze and the 24/7 Hallesches Ufer are per Platz per Tag as the Senate answers them "
        "(unit eur_per_platz_per_day, Lead review); Munich stays per month; Hamburg örU per day. "
        "Köln 2018/2024 fee statutes (Kreis 05315; per-person monthly and official per-m² monthly rates), "
        "Bremen Drs 19/894 2017 nightly Kostensätze (Kreis 04011; not duplicating 2013 daily Entgelte or 2023/2024 net costs), "
        "Leipzig 5-08, Dresden 5.8, Stuttgart 4/12, Düsseldorf 54.101, plus Karlsruhe 4/2 and Mannheim 5.03. "
        "Units are taken verbatim (per person per night/day/month, per place per month, or per m² per month) and are not converted. "
        "Satzung sources use § 5 Abs. 1; the Köln RIS Vorlage and Bremen Drs use reserved rights, rf=0. "
        "SKF and other restricted-group Träger stay at city AGS with no street address; "
        "'Ohlauer 365' and 'Hallesches Ufer' remain in the official labels and quotes only."
    )
    return stored


if __name__ == "__main__":
    from ingest.common import no_direct_run
    raise SystemExit(no_direct_run("institutions_media"))
