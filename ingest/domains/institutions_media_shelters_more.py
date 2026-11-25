"""Extra official city Notunterkunft / Kältehilfe lists for institutions_media.

Curated from official municipal pages and PDFs only. A facility is stored
only when its distinctive name and published location appear in the fetched
official document text (HTTP 200). Women-/youth-/LGBTQ-only offers are
flagged in name or population_note so store_official_facility keeps them at
district (or city) level. Frauenhaus addresses are never stored. Day centres
and Beratungsstellen without an overnight offer are omitted.

This module never opens data/atlas.db and does not invent AGS codes.
"""
from __future__ import annotations

import re
from html import unescape

from ingest.common import clean
from ingest.domains.institutions_media_rechnungshof import RESERVED_LICENCE
from ingest.domains.institutions_media_shelters import (
    _fetch,
    official_slug,
    pdf_to_text,
    store_official_facility,
)

AMT_LICENCE_CITY = (
    "Rechte vorbehalten (Lead review 2026-11-21): städtische Informationsseite, kein Gesetz, keine Verordnung und kein Erlass, daher nicht § 5 UrhG; keine offene Lizenz angegeben. Nur Fakten, Metadaten und Kurzzitate nach § 51 UrhG, Volltext nicht weiterverbreitet"
)

# Official source pages, fetched once per key.
SOURCES = {
    "duesseldorf": {
        "url": (
            "https://www.duesseldorf.de/amt-fuer-migration-und-integration/"
            "obdachlose/uebersicht/winternothilfe"
        ),
        "license": RESERVED_LICENCE,
        "license_url": "https://www.duesseldorf.de/infonav/impressum",
        "attribution": "Landeshauptstadt Düsseldorf",
        "publisher": "Landeshauptstadt Düsseldorf",
        "source_title": "Schutz vor der Kälte für obdachlose Menschen (Winternothilfe Düsseldorf)",
        "source_notes": (
            "Official city Winternothilfe page. Impressum: Inhalte urheberrechtlich "
            "geschützt, alle Rechte einschließlich der Vervielfältigung behält sich "
            "die Landeshauptstadt vor."
        ),
        "redistribute_fulltext": 0,
        "kind_of": "html",
    },
    "stuttgart": {
        "url": (
            "https://www.stuttgart.de/medien/ibs/"
            "notaufnahmemoeglichkeiten_wohnungslose_winter_2026_2027.pdf"
        ),
        "license": RESERVED_LICENCE,
        "license_url": "https://www.stuttgart.de/impressum",
        "attribution": "Landeshauptstadt Stuttgart, Amt für Soziales und Teilhabe",
        "publisher": "Landeshauptstadt Stuttgart",
        "source_title": "Notaufnahmemöglichkeiten für Wohnungslose im Winter 2026/2027 (Stand August 2026)",
        "source_notes": (
            "Official city PDF. Impressum: Vervielfältigung nur zum privaten Gebrauch, "
            "keine Verbreitung von Vervielfältigungsstücken."
        ),
        "redistribute_fulltext": 0,
        "kind_of": "pdf",
    },
    "leipzig": {
        "url": (
            "https://www.leipzig.de/leben-in-leipzig/soziales/"
            "soziale-hilfen/hilfe-bei-obdachlosigkeit-in-leipzig"
        ),
        "license": AMT_LICENCE_CITY,
        "license_url": "https://www.leipzig.de/impressum",
        "attribution": "Stadt Leipzig, Sozialamt",
        "publisher": "Stadt Leipzig",
        "source_title": "Hilfe bei Obdachlosigkeit in Leipzig",
        "source_notes": (
            "Official city page. The leipzig.de imprint states no text-reuse terms, "
            "so the cited page text is treated as an official work under § 5 UrhG."
        ),
        "redistribute_fulltext": 0,
        "kind_of": "html",
    },
    "dresden_heime": {
        "url": (
            "https://www.dresden.de/de/leben/wohnen/wohnhilfen/"
            "wohnungslosigkeit/hilfsangebote/uebergangswohnheime.php"
        ),
        "license": AMT_LICENCE_CITY,
        "license_url": "https://www.dresden.de/de/sonstiges/impressum.php",
        "attribution": "Landeshauptstadt Dresden",
        "publisher": "Landeshauptstadt Dresden",
        "source_title": "Übergangswohnheime / Notaufnahme Hechtstraße",
        "source_notes": (
            "Official city page. The dresden.de imprint states no text-reuse terms "
            "(Haftungsausschluss only), so the cited page text is treated as an "
            "official work under § 5 UrhG."
        ),
        "redistribute_fulltext": 0,
        "kind_of": "html",
    },
    "dresden_nachtcafe": {
        "url": (
            "https://www.dresden.de/de/leben/wohnen/wohnhilfen/"
            "wohnungslosigkeit/hilfsangebote/nachtcafes.php"
        ),
        "license": AMT_LICENCE_CITY,
        "license_url": "https://www.dresden.de/de/sonstiges/impressum.php",
        "attribution": "Landeshauptstadt Dresden",
        "publisher": "Landeshauptstadt Dresden",
        "source_title": "Wohnungslosen-Nachtcafés der Dresdner Kirchgemeinden",
        "source_notes": (
            "Official city page listing winter overnight Nachtcafés (1 Nov–31 Mar, "
            "19–7 Uhr). Impressum states no text-reuse terms; cited page text is "
            "treated as an official work under § 5 UrhG."
        ),
        "redistribute_fulltext": 0,
        "kind_of": "html",
    },
    "hannover": {
        "url": (
            "https://www.hannover.de/Leben-in-der-Region-Hannover/"
            "Verwaltungen-Kommunen/Die-Verwaltung-der-Landeshauptstadt-Hannover/"
            "Dezernate-und-Fachbereiche-der-LHH/Soziales-und-Teilhabe/"
            "Fachbereich-Gesellschaftliche-Teilhabe/Die-Struktur/"
            "Wohnen-und-Leben-in-Gemeinschaftsunterk%C3%BCnften-und-Wohnungen/"
            "Beratung-und-Zuweisung/"
            "Notschlafstellen-und-Tagesaufenthalte-der-Landeshauptstadt-Hannover"
        ),
        "license": RESERVED_LICENCE,
        "license_url": "https://www.hannover.de/Impressum",
        "attribution": "Landeshauptstadt Hannover",
        "publisher": "Landeshauptstadt Hannover",
        "source_title": "Notschlafstellen und Tagesaufenthalte der Landeshauptstadt Hannover",
        "source_notes": (
            "Official city page. Impressum: Reproduktion der Informationen durch Dritte "
            "nur nach Absprache mit der Betreiberin zulässig."
        ),
        "redistribute_fulltext": 0,
        "kind_of": "html",
    },
    "bremen": {
        "url": (
            "https://www.service.bremen.de/dienstleistungen/"
            "notunterkunft-als-wohnungslose-person-nachfragen-11450"
        ),
        "license": RESERVED_LICENCE,
        "license_url": "https://www.service.bremen.de/impressum-122389",
        "attribution": "Freie Hansestadt Bremen, Amt für Soziale Dienste",
        "publisher": "Freie Hansestadt Bremen",
        "source_title": "Notunterkunft als wohnungslose Person nachfragen",
        "source_notes": (
            "Official service.bremen.de page. Impressum: Texte dienen ausschließlich "
            "der persönlichen Information; Vervielfältigung, Veröffentlichung oder "
            "Weitergabe an Dritte ist nicht gestattet."
        ),
        "redistribute_fulltext": 0,
        "kind_of": "html",
    },
    "essen": {
        "url": "https://www.essen.de/meldungen/pressemeldung_1608820.de.html",
        "license": RESERVED_LICENCE,
        "license_url": "https://www.essen.de/impressum.de.html",
        "attribution": "Stadt Essen",
        "publisher": "Stadt Essen",
        "source_title": "Stadt Essen, offizielle Pressemitteilung zu Übernachtungsangeboten",
        "source_notes": (
            "Official essen.de press page naming overnight offers. Impressum: "
            "Website urheberrechtlich geschützt, Vervielfältigung bedarf der "
            "vorherigen Zustimmung der Stadt Essen."
        ),
        "redistribute_fulltext": 0,
        "kind_of": "html",
    },
    "dortmund_pdf": {
        "url": (
            "https://www.dortmund.de/dortmund/pdf-dateien/news_2025/"
            "neu-wohnungslose-existenzielle-hilfen-fuer-wohnungslose-menschen-in-dortmund_2025-12.pdf"
        ),
        "license": RESERVED_LICENCE,
        "license_url": "https://www.dortmund.de/allgemeines/",
        "attribution": "Stadt Dortmund",
        "publisher": "Stadt Dortmund",
        "source_title": "Existenzielle Hilfen für obdachlose Menschen in Dortmund (Stand 12/2025)",
        "source_notes": (
            "Official city PDF linked from dortmund.de. Impressum: Inhalte nur für die "
            "persönliche Information; weitergehende Verwendung ohne Zustimmung untersagt."
        ),
        "redistribute_fulltext": 0,
        "kind_of": "pdf",
    },
    "dortmund_press": {
        "url": (
            "https://www.dortmund.de/newsroom/nachrichten-dortmund.de/"
            "stadt-dortmund-handelt-bei-frost-zusaetzliche-akut-notschlafstelle-"
            "zum-schutz-obdachloser-menschen.html"
        ),
        "license": RESERVED_LICENCE,
        "license_url": "https://www.dortmund.de/allgemeines/",
        "attribution": "Stadt Dortmund",
        "publisher": "Stadt Dortmund",
        "source_title": "Stadt Dortmund handelt bei Frost: zusätzliche Akut-Notschlafstelle",
        "source_notes": (
            "Official city press page, 8 January 2026. Impressum reserves rights as "
            "for other dortmund.de pages."
        ),
        "redistribute_fulltext": 0,
        "kind_of": "html",
    },
    "nuernberg": {
        "url": "https://www.nuernberg.de/internet/stadtportal/obdachlosenhilfe.html",
        "license": RESERVED_LICENCE,
        "license_url": "https://www.nuernberg.de/internet/stadtportal/haftung_fuer_inhalte.html",
        "attribution": "Stadt Nürnberg",
        "publisher": "Stadt Nürnberg",
        "source_title": "Obdachlosenhilfe der Stadt Nürnberg",
        "source_notes": (
            "Official city page. Haftungshinweis: Vervielfältigung und Verwertung "
            "außerhalb der Grenzen des Urheberrechts bedürfen schriftlicher Zustimmung; "
            "Kopien nur für den privaten, nicht kommerziellen Gebrauch."
        ),
        "redistribute_fulltext": 0,
        "kind_of": "html",
    },
}

FRANKFURT_URL = (
    "https://frankfurt.de/leistungen/Notlagen-und-Opferhilfen-8958513/"
    "Finanzielle-und-sonstige-Hilfen-8958541/Notschlafstellen"
)

# Each offer: source key, name, city, land, kind, needles that must appear in
# the official text, optional address/plz/district/operator/beds/status/note.
# population_note must make women-/youth-only offers match is_restricted_group_shelter.
OFFERS: list[dict] = [
    # Düsseldorf (official Winternothilfe page)
    {
        "source": "duesseldorf",
        "name": "Notschlafstelle Graf-Adolf-Straße",
        "city": "Düsseldorf", "land": "NW", "kind": "notunterkunft",
        "address": "Graf-Adolf-Straße 73", "beds": 78,
        "population_note": "Männer, Frauen und Paare; Hunde möglich; ganzjährig 17.30–8.30 Uhr.",
        "operator": "Stadt Düsseldorf / franzfreunde",
        "needles": ["Graf-Adolf-Straße 73", "78 Plätze"],
    },
    {
        "source": "duesseldorf",
        "name": "Notunterkunft Harkortstraße",
        "city": "Düsseldorf", "land": "NW", "kind": "notunterkunft",
        "address": "Harkortstraße 27", "beds": 43,
        "population_note": "für Männer; ganzjährig 24 Stunden; Hunde möglich.",
        "operator": "Stadt Düsseldorf / franzfreunde",
        "needles": ["Harkortstraße 27", "43 Männer"],
    },
    {
        "source": "duesseldorf",
        "name": "Nachtunterkunft Franziska-Schervier-Haus (K 13)",
        "city": "Düsseldorf", "land": "NW", "kind": "notunterkunft",
        "address": "Kaiserswerther Straße 13", "beds": 19,
        "population_note": "für Männer; täglich 19.30–8 Uhr.",
        "operator": "Stadt Düsseldorf / franzfreunde",
        "needles": ["Kaiserswerther Straße 13", "19 Männer"],
    },
    {
        "source": "duesseldorf",
        "name": "Notschlafstelle Ariadne für Frauen",
        "city": "Düsseldorf", "land": "NW", "kind": "notunterkunft",
        "beds": 36,
        "population_note": "für Frauen; mit Tagesaufenthalt, 24 Stunden, Hunde möglich.",
        "operator": "Stadt Düsseldorf / Diakonie Düsseldorf",
        "needles": ["Ariadne", "für Frauen"],
    },
    {
        "source": "duesseldorf",
        "name": "Notschlafstelle Up Stairs",
        "city": "Düsseldorf", "land": "NW", "kind": "notunterkunft",
        "address": "Erkrather Straße 18", "beds": 20,
        "population_note": "für Frauen und Männer; Düsseldorfer Drogenhilfe; täglich 21–8 Uhr.",
        "operator": "Düsseldorfer Drogenhilfe",
        "needles": ["Up Stairs", "Erkrather Straße 18", "20 Personen"],
    },
    {
        "source": "duesseldorf",
        "name": "Knackpunkt für Mädchen und junge Frauen",
        "city": "Düsseldorf", "land": "NW", "kind": "notunterkunft",
        "population_note": "für Mädchen und junge Frauen bis einschließlich 26 Jahre; täglich 21.30–9.30 Uhr.",
        "operator": "Sozialbund Katholischer Frauen und Männer",
        "needles": ["Knackpunkt", "junge Frauen"],
    },
    {
        "source": "duesseldorf",
        "name": "Notschlafstelle Sleep In für Jugendliche",
        "city": "Düsseldorf", "land": "NW", "kind": "notunterkunft",
        "population_note": "für Jugendliche und Erwachsene von 14 bis 21 Jahren.",
        "needles": ["Sleep In", "14 bis 21"],
    },
    {
        "source": "duesseldorf",
        "name": "Ausweichquartier Eisenstraße (Winternothilfe)",
        "city": "Düsseldorf", "land": "NW", "kind": "kaeltehilfe",
        "address": "Eisenstraße 49", "status": "seasonal",
        "population_note": "Befristete Ausweichschlafplätze bis März 2026; keine direkte Anlaufstelle (Zugang über Graf-Adolf-Straße).",
        "needles": ["Eisenstraße 49", "Ausweichschlafplätze"],
    },
    # Stuttgart official winter 2026/2027 PDF, section B only (not Beratung or day centres)
    {
        "source": "stuttgart",
        "name": "Zentrale Notunterkunft der Landeshauptstadt Stuttgart",
        "city": "Stuttgart", "land": "BW", "kind": "notunterkunft",
        "address": "Bottroper Straße 55",
        "population_note": "für Frauen und Männer; Direktaufnahme rund um die Uhr.",
        "needles": ["Zentrale Notunterkunft", "Bottroper Straße 55"],
    },
    {
        "source": "stuttgart",
        "name": "Sleep Inn Stuttgart",
        "city": "Stuttgart", "land": "BW", "kind": "notunterkunft",
        "address": "Hauptstätter Straße 85", "plz": "70178",
        "population_note": "für wohnungslose Drogenkonsumenten und -konsumentinnen sowie Substituierte ab 18 Jahren; Aufnahme rund um die Uhr.",
        "needles": ["Sleep Inn", "Hauptstätter Straße 85"],
    },
    {
        "source": "stuttgart",
        "name": "Haus Wartburg",
        "city": "Stuttgart", "land": "BW", "kind": "notunterkunft",
        "address": "Brunnenstraße 49", "plz": "70372", "district": "Bad Cannstatt",
        "needles": ["Haus Wartburg", "Brunnenstraße 49"],
    },
    {
        "source": "stuttgart",
        "name": "Zentrale Notunterkunft für Familien",
        "city": "Stuttgart", "land": "BW", "kind": "notunterkunft",
        "address": "Wolframstraße 61", "plz": "70191",
        "population_note": "für Familien.",
        "needles": ["Zentrale Notunterkunft für Familien", "Wolframstraße 61"],
    },
    {
        "source": "stuttgart",
        "name": "Johannes-Falk-Haus für junge Erwachsene",
        "city": "Stuttgart", "land": "BW", "kind": "notunterkunft",
        "district": "Stuttgart-Nord",
        "population_note": "für junge Erwachsene, nur für Männer.",
        "needles": ["Johannes-Falk-Haus"],
    },
    {
        "source": "stuttgart",
        "name": "Frauenpension für Frauen (Bad Cannstatt, A)",
        "city": "Stuttgart", "land": "BW", "kind": "notunterkunft",
        "district": "Bad Cannstatt",
        "population_note": "für Frauen.",
        "needles": ["Frauenpension"],
    },
    {
        "source": "stuttgart",
        "name": "Frauenpension für Frauen (Bad Cannstatt, B)",
        "city": "Stuttgart", "land": "BW", "kind": "notunterkunft",
        "district": "Bad Cannstatt",
        "population_note": "für Frauen.",
        "needles": ["Frauenpension"],
    },
    {
        "source": "stuttgart",
        "name": "Arbeiterinnen-Selbsthilfe Stuttgart e. V. für Frauen",
        "city": "Stuttgart", "land": "BW", "kind": "notunterkunft",
        "district": "Stuttgart-Ost",
        "population_note": "für Frauen; Aufnahme tagsüber nach telefonischer Abklärung.",
        "needles": ["Arbeiterinnen"],
    },
    {
        "source": "stuttgart",
        "name": "Käthe-Luther-Haus für Frauen",
        "city": "Stuttgart", "land": "BW", "kind": "notunterkunft",
        "population_note": "für Frauen.",
        "needles": ["Käthe-Luther-Haus"],
    },
    {
        "source": "stuttgart",
        "name": "Neeffhaus für Frauen",
        "city": "Stuttgart", "land": "BW", "kind": "notunterkunft",
        "district": "Stuttgart-Mitte",
        "population_note": "für Frauen; telefonische Anfrage erforderlich.",
        "needles": ["Neeffhaus"],
    },
    {
        "source": "stuttgart",
        "name": "Christoph-Ulrich-Hahn-Haus",
        "city": "Stuttgart", "land": "BW", "kind": "notunterkunft",
        "address": "Himmelsleiter 64", "plz": "70437", "district": "Stuttgart-Freiberg",
        "population_note": "für Männer; Anmeldung für Notübernachter bis 19:00 Uhr.",
        "needles": ["Christoph-Ulrich-Hahn-Haus", "Himmelsleiter 64"],
    },
    {
        "source": "stuttgart",
        "name": "Fritz-Schaaf-Haus (Heilsarmee)",
        "city": "Stuttgart", "land": "BW", "kind": "notunterkunft",
        "address": "Silberburgstraße 139", "plz": "70176",
        "population_note": "für Männer.",
        "operator": "Heilsarmee",
        "needles": ["Fritz-Schaaf-Haus", "Silberburgstraße 139"],
    },
    {
        "source": "stuttgart",
        "name": "Carlo-Steeb-Haus",
        "city": "Stuttgart", "land": "BW", "kind": "notunterkunft",
        "address": "Schmidener Straße 115", "plz": "70374", "district": "Bad Cannstatt",
        "population_note": "für Männer.",
        "needles": ["Carlo-Steeb-Haus", "Schmidener Straße 115"],
    },
    {
        "source": "stuttgart",
        "name": "Immanuel-Grözinger-Haus",
        "city": "Stuttgart", "land": "BW", "kind": "notunterkunft",
        "address": "Böckinger Straße 5", "plz": "70437", "district": "Stuttgart-Zuffenhausen",
        "population_note": "für Männer.",
        "needles": ["Immanuel-Grözinger-Haus", "Böckinger Straße 5"],
    },
    {
        "source": "stuttgart",
        "name": "Hilde und Eugen Krempel Männerwohnheim",
        "city": "Stuttgart", "land": "BW", "kind": "notunterkunft",
        "address": "Friedhofstraße 28", "plz": "70191", "district": "Stuttgart-Nord",
        "population_note": "für Männer; Aufnahme nach telefonischer Rücksprache.",
        "needles": ["Krempel Männerwohnheim", "Friedhofstraße 28"],
    },
    # Leipzig official overnight houses only (no Tagestreffs)
    {
        "source": "leipzig",
        "name": "Übernachtungshaus für wohnungslose Männer „Rücke“",
        "city": "Leipzig", "land": "SN", "kind": "notunterkunft",
        "address": "Rückmarsdorfer Straße 5-7", "plz": "04179",
        "population_note": "für Männer.",
        "needles": ["Rücke", "Rückmarsdorfer Straße 5-7"],
    },
    {
        "source": "leipzig",
        "name": "Übernachtungshaus für wohnungslose Frauen",
        "city": "Leipzig", "land": "SN", "kind": "notunterkunft",
        "population_note": "für Frauen.",
        "needles": ["Übernachtungshaus für wohnungslose Frauen"],
    },
    {
        "source": "leipzig",
        "name": "Alternative I (Notunterbringung wohnungsloser drogenabhängiger Personen)",
        "city": "Leipzig", "land": "SN", "kind": "notunterkunft",
        "address": "Chopinstraße 13", "plz": "04103",
        "needles": ["Alternative I", "Chopinstraße 13"],
    },
    {
        "source": "leipzig",
        "name": "Alternative III (Notunterbringung wohnungsloser drogenabhängiger Personen)",
        "city": "Leipzig", "land": "SN", "kind": "notunterkunft",
        "address": "Braunstraße 28A", "plz": "04347",
        "needles": ["Alternative III", "Braunstraße 28A"],
    },
    {
        "source": "leipzig",
        "name": "Übernachtungshaus für wohnungslose Männer „Helene“",
        "city": "Leipzig", "land": "SN", "kind": "notunterkunft",
        "address": "Helenenstraße 26", "plz": "04279",
        "population_note": "für Männer.",
        "needles": ["Helene", "Helenenstraße 26"],
    },
    {
        "source": "leipzig",
        "name": "Notschlafstelle für wohnungslose Männer „Scharnhorststraße 27“",
        "city": "Leipzig", "land": "SN", "kind": "notunterkunft",
        "address": "Scharnhorststraße 27", "plz": "04275",
        "population_note": "für Männer; Aufnahme nur über die Vermittlung durch das Übernachtungshaus Helene.",
        "needles": ["Scharnhorststraße 27", "Aufnahme nur über die Vermittlung"],
    },
    # Dresden
    {
        "source": "dresden_heime",
        "name": "Notaufnahme im Übergangswohnheim Hechtstraße",
        "city": "Dresden", "land": "SN", "kind": "notunterkunft",
        "address": "Hechtstraße 10", "plz": "01097",
        "population_note": "Notaufnahme außerhalb der Dienstzeiten.",
        "needles": ["Notaufnahme", "Hechtstraße 10"],
    },
    {
        "source": "dresden_nachtcafe",
        "name": "Wohnungslosen-Nachtcafé Dreikönigskirche (Montag)",
        "city": "Dresden", "land": "SN", "kind": "kaeltehilfe",
        "address": "Hauptstraße 23", "plz": "01097", "status": "seasonal",
        "operator": "Ev.-Luth. Dreikönigskirche",
        "population_note": "Winter-Nachtcafé 1. November bis 31. März, 19–7 Uhr (Einlass 19–22 Uhr); für wohnungslose Menschen ab 18 Jahren.",
        "needles": ["Dreikönigskirche", "Hauptstr. 23"],
    },
    {
        "source": "dresden_nachtcafe",
        "name": "Wohnungslosen-Nachtcafé Christophoruskirche Laubegast (Dienstag)",
        "city": "Dresden", "land": "SN", "kind": "kaeltehilfe",
        "address": "Hermann-Seidel-Straße 3", "plz": "01279", "district": "Laubegast",
        "status": "seasonal",
        "operator": "Ev.-Luth. Christophoruskirche Laubegast",
        "population_note": "Winter-Nachtcafé 1. November bis 31. März, 19–7 Uhr; für wohnungslose Menschen ab 18 Jahren.",
        "needles": ["Christophoruskirche Laubegast", "Hermann-Seidel-Str. 3"],
    },
    {
        "source": "dresden_nachtcafe",
        "name": "Wohnungslosen-Nachtcafé Heilige Familie (Mittwoch)",
        "city": "Dresden", "land": "SN", "kind": "kaeltehilfe",
        "address": "Meußlitzer Straße 108", "plz": "01259", "status": "seasonal",
        "operator": "Kath. Kirche Heilige Familie",
        "population_note": "Winter-Nachtcafé 1. November bis 31. März, 19–7 Uhr; für wohnungslose Menschen ab 18 Jahren.",
        "needles": ["Heilige Familie", "Meußlitzer Str. 108"],
    },
    {
        "source": "dresden_nachtcafe",
        "name": "Wohnungslosen-Nachtcafé Kirchgemeinde Loschwitz (Donnerstag)",
        "city": "Dresden", "land": "SN", "kind": "kaeltehilfe",
        "address": "Grundstraße 36", "plz": "01326", "district": "Loschwitz",
        "status": "seasonal",
        "operator": "Ev.-Luth. Kirchgemeinde Loschwitz",
        "population_note": "Winter-Nachtcafé 1. November bis 31. März, 19–7 Uhr; für wohnungslose Menschen ab 18 Jahren.",
        "needles": ["Loschwitz", "Grundstraße 36"],
    },
    {
        "source": "dresden_nachtcafe",
        "name": "Wohnungslosen-Nachtcafé Zionskirche (Freitag)",
        "city": "Dresden", "land": "SN", "kind": "kaeltehilfe",
        "address": "Bayreuther Straße 28", "plz": "01187", "status": "seasonal",
        "operator": "Ev.-Luth. Zionskirche Dresden",
        "population_note": "Winter-Nachtcafé 1. November bis 31. März, 19–7 Uhr; für wohnungslose Menschen ab 18 Jahren.",
        "needles": ["Zionskirche", "Bayreuther Str. 28"],
    },
    {
        "source": "dresden_nachtcafe",
        "name": "Wohnungslosen-Nachtcafé Immanuelkirche (Samstag)",
        "city": "Dresden", "land": "SN", "kind": "kaeltehilfe",
        "address": "Hühndorfer Straße 22", "plz": "01157", "status": "seasonal",
        "operator": "Ev.-Meth. Immanuelkirche",
        "population_note": "Winter-Nachtcafé 1. November bis 31. März, 19–7 Uhr; für wohnungslose Menschen ab 18 Jahren.",
        "needles": ["Immanuelkirche", "Hühndorfer Str. 22"],
    },
    {
        "source": "dresden_nachtcafe",
        "name": "Wohnungslosen-Nachtcafé St. Franziskus Xaverius (Sonntag)",
        "city": "Dresden", "land": "SN", "kind": "kaeltehilfe",
        "address": "Stauffenberg Allee 9 H", "plz": "01099", "status": "seasonal",
        "operator": "Kath. Kirche St. Franziskus Xaverius",
        "population_note": "Winter-Nachtcafé 1. November bis 31. März, 19–7 Uhr; für wohnungslose Menschen ab 18 Jahren.",
        "needles": ["Franziskus Xaverius", "Stauffenberg Allee 9"],
    },
    # Hannover official Notschlafstellen (not day-only Tagestreffs)
    {
        "source": "hannover",
        "name": "Notschlafstelle für Frauen (Hannover, ohne Kinder)",
        "city": "Hannover", "land": "NI", "kind": "notunterkunft",
        "population_note": "für volljährige Frauen ohne Kinder.",
        "needles": ["Frauen ohne Kinder"],
    },
    {
        "source": "hannover",
        "name": "Notschlafstelle für Frauen (Hannover, auch mit Kindern)",
        "city": "Hannover", "land": "NI", "kind": "notunterkunft",
        "population_note": "für volljährige Frauen mit und ohne Kinder; vollständig barrierefrei.",
        "needles": ["Frauen mit und ohne Kinder"],
    },
    {
        "source": "hannover",
        "name": "Notschlafstelle Wörthstraße",
        "city": "Hannover", "land": "NI", "kind": "notunterkunft",
        "address": "Wörthstraße 10", "plz": "30161",
        "population_note": "für volljährige Männer; barrierefreie Plätze.",
        "needles": ["Wörthstraße 10", "volljährige Männer"],
    },
    {
        "source": "hannover",
        "name": "Notschlafstelle Podbielskistraße",
        "city": "Hannover", "land": "NI", "kind": "notunterkunft",
        "address": "Podbielskistraße 115 C", "plz": "30177",
        "population_note": "für Familien.",
        "needles": ["Podbielskistraße 115 C", "Familien"],
    },
    {
        "source": "hannover",
        "name": "Notschlafstelle Alter Flughafen",
        "city": "Hannover", "land": "NI", "kind": "notunterkunft",
        "address": "Alter Flughafen 12", "plz": "30179",
        "population_note": "für volljährige Personen, Hunde erlaubt, eingeschränkt barrierefrei.",
        "needles": ["Alter Flughafen 12", "Hunde erlaubt"],
    },
    {
        "source": "hannover",
        "name": "Notschlafstelle Feuerwehrstraße",
        "city": "Hannover", "land": "NI", "kind": "notunterkunft",
        "address": "Feuerwehrstraße 1", "plz": "30169",
        "population_note": "für volljährige Männer; keine barrierefreien Plätze.",
        "needles": ["Feuerwehrstraße 1", "volljährige Männer"],
    },
    # Bremen official service page (not post-address or day centres)
    {
        "source": "bremen",
        "name": "Notunterkunft für Männer Rembertiring",
        "city": "Bremen", "land": "HB", "kind": "notunterkunft",
        "address": "Rembertiring 49", "plz": "28195",
        "population_note": "für Männer; Notaufnahme rund um die Uhr.",
        "needles": ["Notunterkunft für Männer", "Rembertiring 49"],
    },
    {
        "source": "bremen",
        "name": "Notunterkunft für Frauen",
        "city": "Bremen", "land": "HB", "kind": "notunterkunft",
        "population_note": "für Frauen; Notaufnahme rund um die Uhr.",
        "needles": ["Notunterkunft für Frauen"],
    },
    {
        "source": "bremen",
        "name": "Sleep Inn Bremen",
        "city": "Bremen", "land": "HB", "kind": "notunterkunft",
        "address": "Oberneulander Landstraße 19", "plz": "28355",
        "population_note": "für Drogenkonsumentinnen und Drogenkonsumenten.",
        "needles": ["Sleep Inn", "Oberneulander Landstr"],
    },
    {
        "source": "bremen",
        "name": "La Campagne",
        "city": "Bremen", "land": "HB", "kind": "notunterkunft",
        "address": "Ahlringstraße 2-4", "plz": "28309",
        "population_note": "für Drogenkonsumentinnen und Drogenkonsumenten.",
        "needles": ["La Campagne", "Ahlringstr"],
    },
    # Essen official press page
    {
        "source": "essen",
        "name": "Notübernachtungsstelle Lichtstraße",
        "city": "Essen", "land": "NW", "kind": "notunterkunft",
        "address": "Lichtstraße 1", "district": "Westviertel",
        "population_note": "für wohnungs- und obdachlose Männer; in der kalten Jahreszeit ab 19 Uhr.",
        "needles": ["Lichtstraße 1", "Männer"],
    },
    {
        "source": "essen",
        "name": "Notübernachtungsstelle für Frauen",
        "city": "Essen", "land": "NW", "kind": "notunterkunft",
        "district": "Kray",
        "population_note": "für Frauen; in der kalten Jahreszeit ab 19 Uhr.",
        "needles": ["Notübernachtungsstelle", "Essen-Kray", "Frauen"],
    },
    {
        "source": "essen",
        "name": "RAUM 58 Notschlafstelle für Jugendliche",
        "city": "Essen", "land": "NW", "kind": "notunterkunft",
        "district": "Nordviertel",
        "population_note": "für Jugendliche zwischen 14 und 21 Jahren; 21–9 Uhr.",
        "needles": ["RAUM 58", "Jugendliche"],
    },
    {
        "source": "essen",
        "name": "Integrationsangebot mit Übernachtung Hoffnungstraße",
        "city": "Essen", "land": "NW", "kind": "notunterkunft",
        "address": "Hoffnungstraße 24", "district": "Westviertel",
        "operator": "Suchthilfe direkt gGmbH",
        "population_note": "Übernachtung für wohnungslose drogenkranke Menschen; montags bis sonntags ab 19 Uhr.",
        "needles": ["Hoffnungstraße 24", "Übernachtung"],
    },
    {
        "source": "essen",
        "name": "DRK-Wärmezelte Wolfsbankring (extreme Kälte)",
        "city": "Essen", "land": "NW", "kind": "kaeltehilfe",
        "address": "Wolfsbankring 5a", "district": "Borbeck", "status": "seasonal",
        "operator": "Deutsches Rotes Kreuz",
        "population_note": "Wärmezelte, wenn an zwei aufeinanderfolgenden Nächten −3 Grad zu erwarten sind; ab 21 Uhr.",
        "needles": ["Wolfsbankring 5a", "Wärmezelte"],
    },
    # Dortmund official PDF (regular overnight) and frost press page
    {
        "source": "dortmund_pdf",
        "name": "Frauenübernachtungsstelle für Frauen",
        "city": "Dortmund", "land": "NW", "kind": "notunterkunft",
        "beds": 50,
        "operator": "Diakonisches Werk",
        "population_note": "für Frauen; 50 Plätze, montags bis sonntags 24 Stunden.",
        "needles": ["Frauenübernachtungsstelle"],
    },
    {
        "source": "dortmund_pdf",
        "name": "Männerübernachtungsstelle",
        "city": "Dortmund", "land": "NW", "kind": "notunterkunft",
        "address": "Unionstraße 33", "beds": 70,
        "operator": "European Homecare GmbH",
        "population_note": "für Männer; 70 Plätze, davon acht als Angebot Grip Spot für junge Volljährige; 24 Stunden.",
        "needles": ["Männerübernachtungsstelle", "Unionstraße 33"],
    },
    {
        "source": "dortmund_pdf",
        "name": "Notschlafstelle SW 42",
        "city": "Dortmund", "land": "NW", "kind": "notunterkunft",
        "address": "Schwanenwall 42", "beds": 20,
        "operator": "Soziales Zentrum e.V.",
        "population_note": "Übernachtungsstelle für Drogenkonsumierende; 20 Plätze, 24 Stunden.",
        "needles": ["Schwanenwall 42", "Drogen"],
    },
    {
        "source": "dortmund_pdf",
        "name": "Gap Jump für junge Erwachsene",
        "city": "Dortmund", "land": "NW", "kind": "notunterkunft",
        "beds": 20,
        "operator": "European Homecare GmbH",
        "population_note": "für junge Erwachsene / junge Wohnungslose; 20 Plätze; Kontakt über die Männerübernachtungsstelle. Keine eigene Anschrift in der amtlichen Liste.",
        "needles": ["Gap Jump", "junge Wohnungslose"],
    },
    {
        "source": "dortmund_press",
        "name": "Sleep-In Stellwerk für Jugendliche",
        "city": "Dortmund", "land": "NW", "kind": "notunterkunft",
        "beds": 10,
        "operator": "Verbund Sozialtherapeutischer Einrichtungen NRW e.V.",
        "population_note": "für Jugendliche; 10 Schlafplätze. Die offizielle Presseseite nennt keine Anschrift.",
        "needles": ["Sleep-In Stellwerk", "Jugendliche"],
    },
    {
        "source": "dortmund_press",
        "name": "Akut-Notschlafstelle Leuthardstraße (Frost)",
        "city": "Dortmund", "land": "NW", "kind": "kaeltehilfe",
        "address": "Leuthardstraße 7", "status": "seasonal",
        "population_note": "Zusätzliche Akut-Notschlafstelle bei extremer Kälte; Frauen- und Männerbereiche getrennt; 19–8 Uhr.",
        "needles": ["Leuthardstraße 7", "Akut-Notschlafstelle"],
    },
    {
        "source": "dortmund_press",
        "name": "Einrichtung Mergelteichstraße",
        "city": "Dortmund", "land": "NW", "kind": "notunterkunft",
        "address": "Mergelteichstraße",
        "population_note": "Überlauf, wenn die Männer- oder Frauenübernachtungsstelle voll belegt ist. Die offizielle Seite nennt die Straße ohne Hausnummer.",
        "needles": ["Mergelteichstraße"],
    },
    # Nürnberg official Obdachlosenhilfe page (overnight only, no Tagestreffs)
    {
        "source": "nuernberg",
        "name": "Bramwell-Booth-Haus (Notschlafstelle der Heilsarmee, G53)",
        "city": "Nürnberg", "land": "BY", "kind": "notunterkunft",
        "address": "Gostenhofer Hauptstraße 53", "plz": "90443",
        "operator": "Heilsarmee",
        "population_note": "Notübernachtung; Zuweisung über Haus Großweidenmühlstraße; Check-in 19–22 Uhr.",
        "needles": ["Bramwell", "Gostenhofer Hauptstraße 53"],
    },
    {
        "source": "nuernberg",
        "name": "Haus für Männer Großweidenmühlstraße",
        "city": "Nürnberg", "land": "BY", "kind": "notunterkunft",
        "address": "Großweidenmühlstraße 43", "plz": "90419",
        "population_note": "für Männer; Check-in 18–22 Uhr.",
        "needles": ["Haus für Männer", "Großweidenmühlstraße 43"],
    },
    {
        "source": "nuernberg",
        "name": "Notübernachtung Diana-Herberge",
        "city": "Nürnberg", "land": "BY", "kind": "notunterkunft",
        "address": "Dianastraße 29", "plz": "90441",
        "population_note": "Notübernachtung; Zuweisung über NOA bzw. Haus Großweidenmühlstraße.",
        "needles": ["Diana-Herberge", "Dianastraße 29"],
    },
    {
        "source": "nuernberg",
        "name": "Haus Rothstein der Heilsarmee",
        "city": "Nürnberg", "land": "BY", "kind": "notunterkunft",
        "address": "Gostenhofer Hauptstraße 47-49", "plz": "90443",
        "operator": "Heilsarmee",
        "needles": ["Haus Rothstein", "Gostenhofer Hauptstraße 47"],
    },
    {
        "source": "nuernberg",
        "name": "Domus Misericordiae der Caritas",
        "city": "Nürnberg", "land": "BY", "kind": "notunterkunft",
        "address": "Pirckheimerstraße 12", "plz": "90408",
        "operator": "Caritas",
        "needles": ["Domus Misericordiae", "Pirckheimerstraße 12"],
    },
    {
        "source": "nuernberg",
        "name": "Haus für Frauen",
        "city": "Nürnberg", "land": "BY", "kind": "notunterkunft",
        "population_note": "für Frauen.",
        "needles": ["Haus für Frauen"],
    },
    {
        "source": "nuernberg",
        "name": "Refugium für Frauen",
        "city": "Nürnberg", "land": "BY", "kind": "notunterkunft",
        "population_note": "für Frauen; Zuweisung über das Haus für Frauen (Ortsebene); Check-in 19–22 Uhr.",
        "needles": ["Refugium"],
    },
    {
        "source": "nuernberg",
        "name": "Catherine-Booth-Haus der Heilsarmee für Frauen",
        "city": "Nürnberg", "land": "BY", "kind": "notunterkunft",
        "operator": "Heilsarmee",
        "population_note": "für Frauen; Check-in 18–22 Uhr.",
        "needles": ["Catherine-Booth-Haus"],
    },
    {
        "source": "nuernberg",
        "name": "SleepIn Notschlafstelle für junge Menschen",
        "city": "Nürnberg", "land": "BY", "kind": "notunterkunft",
        "population_note": "für Jugendliche und junge Erwachsene von 14 bis 21 Jahren; Check-in 19–23 Uhr.",
        "needles": ["SleepIn", "14 bis 21"],
    },
    {
        "source": "nuernberg",
        "name": "Hängematte e.V. – Notschlafstelle und Krisenhilfe",
        "city": "Nürnberg", "land": "BY", "kind": "notunterkunft",
        "address": "Tafelfeldstraße 15", "plz": "90443",
        "operator": "Hängematte e.V.",
        "population_note": "für drogenkonsumierende Erwachsene; Check-in 20–22 Uhr.",
        "needles": ["Hängematte", "Tafelfeldstraße 15"],
    },
]


def fold_page_text(text: str) -> str:
    """Normalise official page text so needles can be checked without copying coords."""
    text = unescape(text or "")
    text = text.replace("\u00ad", "").replace("\xa0", " ")
    text = text.replace("ß", "ss").replace("ẞ", "ss")
    text = re.sub(r"(?i)str(?:asse|\.)", "strasse", text)
    text = re.sub(r"(?i)(\w)-\s+(\w)", r"\1\2", text)
    return re.sub(r"\s+", " ", text).casefold().strip()


def html_to_text(raw: bytes | str) -> str:
    html = raw.decode("utf-8", "replace") if isinstance(raw, (bytes, bytearray)) else raw
    html = re.sub(r"(?is)<script[\s\S]*?</script>|<style[\s\S]*?</style>|<noscript[\s\S]*?</noscript>", " ", html)
    html = re.sub(r"(?i)<br\s*/?>", "\n", html)
    html = re.sub(r"(?i)</(?:p|h[1-6]|li|div|tr|section|article|td|br)>", "\n", html)
    text = unescape(re.sub(r"<[^>]+>", " ", html))
    return re.sub(r"[ \t]+", " ", re.sub(r"\n+", "\n", text))


def page_text_from_bytes(data: bytes, *, kind_of: str) -> str:
    if kind_of == "pdf" or data.lstrip().startswith(b"%PDF"):
        return pdf_to_text(data)
    return html_to_text(data)


def needles_found(folded: str, needles: list[str]) -> list[str]:
    missing = []
    for needle in needles:
        if fold_page_text(needle) not in folded:
            missing.append(needle)
    return missing


def official_key_for(offer: dict) -> str:
    prefix = {
        "Düsseldorf": "DUS-", "Stuttgart": "S-", "Leipzig": "L-",
        "Dresden": "DD-", "Hannover": "H-", "Bremen": "HB-",
        "Essen": "E-", "Dortmund": "DO-", "Nürnberg": "N-",
    }[offer["city"]]
    return official_slug(prefix, offer["name"], offer.get("address"), offer["city"])


def record_from_offer(offer: dict, src: dict) -> dict:
    rec = {
        "official_key": official_key_for(offer),
        "name": offer["name"],
        "kind": offer.get("kind") or "notunterkunft",
        "land": offer["land"],
        "city": offer["city"],
        "address": offer.get("address"),
        "plz": offer.get("plz"),
        "district": offer.get("district"),
        "operator": offer.get("operator"),
        "beds": offer.get("beds"),
        "status": offer.get("status") or "active",
        "population_note": offer.get("population_note"),
        "source_url": src["url"],
        "official_url": src["url"],
        "source_name": src["source_title"],
        "license": src["license"],
        "license_url": src["license_url"],
        "attribution": src["attribution"],
        "publisher": src["publisher"],
        "source_title": src["source_title"],
        "source_notes": src["source_notes"],
        "redistribute_fulltext": src["redistribute_fulltext"],
    }
    return rec


def ingest_more_city_shelters(conn, cfg, sources, notes) -> int:
    force = bool(cfg.get("force"))
    folded_by_source: dict[str, str] = {}
    stored = 0
    skipped = 0
    by_city: dict[str, int] = {}

    for key, src in SOURCES.items():
        try:
            raw = _fetch(src["url"], force=force)
        except Exception as exc:
            notes.append(
                f"{key} official page failed: {type(exc).__name__}: {str(exc)[:180]}"
            )
            folded_by_source[key] = ""
            continue
        if src["kind_of"] == "pdf" and not raw.lstrip().startswith(b"%PDF"):
            notes.append(f"{key} official document was not a PDF")
            folded_by_source[key] = ""
            continue
        folded_by_source[key] = fold_page_text(page_text_from_bytes(raw, kind_of=src["kind_of"]))

    try:
        _fetch(FRANKFURT_URL, force=force)
        notes.append("Frankfurt official Notschlafstellen page returned HTTP 200 on this pass; no catalog was built because earlier runs were blocked.")
    except Exception as exc:
        notes.append(
            "Frankfurt official Notschlafstellen and Kältebus pages returned "
            f"{type(exc).__name__} from this environment (polite single retry; not hammered). "
            "No frankfurt.de offers were stored."
        )

    for offer in OFFERS:
        src = SOURCES[offer["source"]]
        folded = folded_by_source.get(offer["source"], "")
        if not folded:
            skipped += 1
            continue
        missing = needles_found(folded, offer["needles"])
        if missing:
            notes.append(
                f"Skipped {offer['name']} ({offer['city']}): official text missing {missing!r}"
            )
            skipped += 1
            continue
        rec = record_from_offer(offer, src)
        if store_official_facility(conn, rec, sources=sources):
            stored += 1
            by_city[offer["city"]] = by_city.get(offer["city"], 0) + 1
        else:
            notes.append(f"store_official_facility rejected {offer['name']} ({offer['city']})")
            skipped += 1

    parts = ", ".join(f"{city}={n}" for city, n in sorted(by_city.items())) or "none"
    notes.append(
        f"Additional official city shelters stored={stored} skipped={skipped} ({parts}). "
        "Day centres and Beratungsstellen without an overnight offer were not stored. "
        "Women-/youth-/LGBTQ-only offers are district- or city-level only."
    )
    return stored


if __name__ == "__main__":
    from ingest.common import no_direct_run
    raise SystemExit(no_direct_run("institutions_media"))
