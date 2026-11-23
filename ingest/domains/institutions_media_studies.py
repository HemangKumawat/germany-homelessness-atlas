"""Curated catalogue of major German homelessness research studies.

Each row is stored as doc.kind='study' with commissioning body, authors'
organisation, year, a verified official URL and a licence. Metrics are stored
only when a short locator quote is present in the cited document, and only when
the figure is not already held by Counts & Law (Wohnungslosenbericht 2022/2024,
BAG W Hochrechnung 2018–2024, NRW Wohnungsnotfallberichterstattung, Berlin
Nacht der Solidarität counts, Hamburg GOE 2018, München Produktcontrolling,
BW GISS 2015 and Liga BW Stichtagserhebung).

The BMAS FB 534 national stock estimate for 31.05.2018 is stored as two
rows (low 313.000 and high 337.000, is_est=1) under the series label
'BMAS FB 534 Schätzung 2018', so it can be shown beside later Counts & Law
series with its own provenance.
"""

from __future__ import annotations

from pathlib import Path

from ingest.common import clean, fetch, upsert
from ingest.domains.institutions_media_drogentote import store_cited_metric
from ingest.domains.institutions_media_drogentote import pdf_text_from_bytes

from ingest.domains.institutions_media_investigations import stored_fields_name_ok
from ingest.domains.institutions_media_rechnungshof import (
    RESERVED_LICENCE,
    fold_text,
    quote_in_text,
    trim_quote,
)

DOMAIN = "institutions_media"

# Lead review 2026-11-21: a BMAS Forschungsbericht is a commissioned study whose text the contractors wrote "in
# eigener wissenschaftlicher Verantwortung" (imprint page); it is no Gesetz/Verordnung/Erlass and was not adopted
# as an official text, so § 5 UrhG does not apply. No open licence is stated: facts, metadata, short § 51 quotes.
AMT_LICENCE_BMAS = (
    "Rechte vorbehalten: im Auftrag des BMAS erstellter Forschungsbericht (Durchführung und Schlussfolgerungen "
    "\"von den Auftragnehmern in eigener wissenschaftlicher Verantwortung\"), kein amtliches Werk nach § 5 UrhG; "
    "keine offene Lizenz angegeben. Nur Fakten, Metadaten und kurze Zitate mit Quellenangabe (§ 51 UrhG), kein Volltext"
)
AMT_LICENCE_HH = (
    "amtliches Werk, § 5 UrhG, scoped to the cited Bürgerschaft document text only; "
    "ParlDok lizenz.html and the Bürgerschaft impressum state no Drucksachen terms"
)
CC_BY_40 = "CC BY 4.0"

# Person/household headline counts already held by Counts & Law.
# The BMAS FB 534 31.05.2018 range (313.000–337.000) is stored on purpose
# as its own estimate series and is therefore not in this set.
COUNTS_LAW_HELD_PERSONS = frozenset({
    # Wohnungslosenbericht 2024
    531601, 531600, 439466, 439465, 128705, 47270, 10939, 2051,
    60435, 4631, 6602, 15570, 45219, 53833, 1932, 6566, 107705,
    45338, 53869, 99207,
    # Wohnungslosenbericht 2022
    262600, 178100, 37400, 1100, 49300, 5500, 8800, 86700, 6000, 2800,
    # BAG W Hochrechnung 2018–2024
    1029000, 928000, 607000, 383000, 417000, 584000, 678000,
    760000, 681000, 447000, 268000, 306000, 451000, 543000, 542000,
    56000, 54000, 50000, 45000,
    840000, 765000, 465000, 300000, 264000, 820000, 209000, 412500, 616500,
    # NRW Land totals (Tab. 2) and 2024 examples
    20996, 25045, 32286, 44434, 46610, 49987, 48285, 78350, 108590, 122170,
    106330, 15840, 1795, 1565,
    # Berlin Nacht der Solidarität 2020 headcount (Drs. 19/10884)
    1976, 807, 942, 158, 540, 267,
    # Hamburg GOE 2018
    1910, 6576, 4666, 1029, 3953, 2924,
    # München Produktcontrolling
    11271, 11136, 4978, 4802, 8759, 5525,
    # BW GISS 2015 and Liga 2024
    22789, 14320, 10701, 8469, 22500, 13394, 3861, 9515,
})

STUDY_DDL = """
CREATE TABLE IF NOT EXISTS institutions_media_study (
    url TEXT PRIMARY KEY,
    doc_id INTEGER NOT NULL,
    commissioning_body TEXT NOT NULL,
    authors_organisation TEXT NOT NULL,
    year INTEGER NOT NULL,
    doi TEXT,
    quote TEXT,
    source_id INTEGER
);
"""

# Official URLs verified HTTP 200 with the project UA (2026-11-21).
CATALOG: list[dict] = [
    {
        "key": "fb534",
        "url": "https://www.bmas.de/SharedDocs/Downloads/DE/Publikationen/Forschungsberichte/fb534-entstehung-verlauf-struktur-von-wohnungslosigkeit-und-strategien-zu-vermeidung-und-behebung.pdf?__blob=publicationFile&v=2",
        "title": "Entstehung, Verlauf und Struktur von Wohnungslosigkeit und Strategien zu ihrer Vermeidung und Behebung – Ergebnisbericht (Forschungsbericht 534)",
        "year": 2019,
        "published": "2019-09",
        "land": "DE",
        "commissioning_body": "Bundesministerium für Arbeit und Soziales",
        "authors_organisation": "Gesellschaft für innovative Sozialforschung und Sozialplanung e. V. (GISS)",
        "author": "Volker Busch-Geertsema, Jutta Henke, Axel Steffen (GISS)",
        "publisher": "Bundesministerium für Arbeit und Soziales",
        "license": AMT_LICENCE_BMAS,
        "license_url": "https://www.bmas.de/EN/Services/Imprint/imprint.html",
        "redistribute_fulltext": 0,
        "quote": "Mietschulden und Mietzahlungsschwierigkeiten waren die mit Abstand häufigsten Anlässe drohender Wohnungslosigkeit (85 %).",
        "source_notes": (
            "Official BMAS Forschungsbericht (commissioned study, rights reserved; facts and short quotes only). The 31.05.2018 "
            "national stock estimate is stored as two is_est=1 rows (low 313.000, high "
            "337.000) with series label 'BMAS FB 534 Schätzung 2018' in metric.note, "
            "alongside later Counts & Law series rather than hidden."
        ),
        "metrics": [
            {
                "entity_type": "de", "entity_id": "DE",
                "metric": "fb534_homeless_estimate_low",
                "year": 2018, "value": 313000, "unit": "persons",
                "is_est": 1,
                "locator": "PDF-S. 5, Kurzbeschreibung",
                "quote": "Am Stichtag 31.05.2018 war schätzungsweise eine Gesamtzahl von zwischen 313.000 und 337.000 Menschen in Deutschland wohnungslos.",
                "note": "BMAS FB 534 Schätzung 2018",
            },
            {
                "entity_type": "de", "entity_id": "DE",
                "metric": "fb534_homeless_estimate_high",
                "year": 2018, "value": 337000, "unit": "persons",
                "is_est": 1,
                "locator": "PDF-S. 5, Kurzbeschreibung",
                "quote": "Am Stichtag 31.05.2018 war schätzungsweise eine Gesamtzahl von zwischen 313.000 und 337.000 Menschen in Deutschland wohnungslos.",
                "note": "BMAS FB 534 Schätzung 2018",
            },
            {
                "entity_type": "de", "entity_id": "DE",
                "metric": "fb534_threatened_hh_in_sample",
                "year": 2017, "value": 45740, "unit": "households",
                "is_est": 0,
                "locator": "PDF-S. 24",
                "quote": "In 81 Kommunen wurden insgesamt 45.740 Haushalte registriert, die im Jahr 2017 von Wohnungslosigkeit bedroht waren.",
                "note": "Registered prevention cases in 81 responding municipalities, not a national total.",
            },
            {
                "entity_type": "de", "entity_id": "DE",
                "metric": "fb534_threatened_hh_per_1000_households",
                "year": 2017, "value": 5.8, "unit": "per_1000_households",
                "is_est": 1, "is_rounded": 1,
                "locator": "PDF-S. 76",
                "quote": "eine Dichte von 5,8 von Wohnungsverlust bedrohten Haushalten je 1.000 Haushalte",
                "note": "Density calculated from the 81-municipality sample. The Kurzbeschreibung wording 'je 1.000 Einwohnerinnen und Einwohner' is not used; the method chapter states per 1.000 households.",
            },
            {
                "entity_type": "de", "entity_id": "DE",
                "metric": "fb534_rent_arrears_share_pct",
                "year": 2017, "value": 85, "unit": "percent",
                "is_est": 0,
                "locator": "PDF-S. 4, Kurzbeschreibung",
                "quote": "Mietschulden und Mietzahlungsschwierigkeiten waren die mit Abstand häufigsten Anlässe drohender Wohnungslosigkeit (85 %).",
            },
            {
                "entity_type": "de", "entity_id": "DE",
                "metric": "fb534_prevention_action_share_pct",
                "year": 2017, "value": 84, "unit": "percent",
                "is_est": 0,
                "locator": "PDF-S. 4, Kurzbeschreibung",
                "quote": "In 84 Prozent aller bekannt gewordenen Präventionsfälle wurden Aktivitäten zur Wohnraumsicherung eingeleitet.",
            },
            {
                "entity_type": "de", "entity_id": "DE",
                "metric": "fb534_prevention_success_share_pct",
                "year": 2017, "value": 63, "unit": "percent",
                "is_est": 0, "is_rounded": 1,
                "locator": "PDF-S. 25",
                "quote": "In knapp 63 % der Fälle, in denen ein Ausgang bekannt ist, konnte Wohnungslosigkeit durch Aktivitäten der kommunalen Stellen verhindert werden.",
            },
        ],
    },
    {
        "key": "fb605",
        "url": "https://www.bmas.de/SharedDocs/Downloads/DE/Publikationen/Forschungsberichte/fb-605-empirische-untersuchung-zum-wohnungslosenberichterstattungsgesetz.pdf?__blob=publicationFile&v=1",
        "title": "Empirische Untersuchung zum Gegenstand nach § 8 Abs. 2 und 3 WoBerichtsG (Forschungsbericht 605)",
        "year": 2022,
        "published": "2022-09",
        "land": "DE",
        "commissioning_body": "Bundesministerium für Arbeit und Soziales",
        "authors_organisation": "Gesellschaft für innovative Sozialforschung und Sozialplanung e. V. (GISS) und Kantar Public",
        "author": "Katharina Brüchmann, Volker Busch-Geertsema, Thorsten Heien, Jutta Henke, Tanja Kiesner, Martin Pfister, Sandra Schöpke (GISS/Kantar Public)",
        "publisher": "Bundesministerium für Arbeit und Soziales",
        "license": AMT_LICENCE_BMAS,
        "license_url": "https://www.bmas.de/EN/Services/Imprint/imprint.html",
        "redistribute_fulltext": 0,
        "quote": "Mit der Studie beschreitet die deutsche Forschung zu Wohnungslosigkeit methodisches Neuland.",
        "source_notes": (
            "Underlying empirical study for the Wohnungslosenbericht 2022, a different "
            "document from the official Bericht. Headline unsheltered/hidden/total counts "
            "from that Bericht are already in Counts & Law and are not stored here."
        ),
        "metrics": [
            {
                "entity_type": "de", "entity_id": "DE",
                "metric": "fb605_survey_municipalities",
                "year": 2022, "value": 151, "unit": "municipalities",
                "is_est": 0,
                "locator": "PDF-S. 5, Kurzbeschreibung",
                "quote": "eine repräsentative Auswahl von Wohnungslosen in 151 deutschen Städten und Gemeinden.",  # Lead: trim_quote cut the longer quote at "7."
                "note": "Sample design (municipalities), not a count of homeless people.",
            },
        ],
    },
    {
        "key": "bagw_sta2024",
        "url": "https://www.bagw.de/fileadmin/bagw/media/Doc/STA/STA_Statistikbericht_2024.pdf",
        "title": "Statistikbericht – Berichtsjahr 2024. Zu Lebenslagen wohnungsloser und von Wohnungslosigkeit bedrohter Menschen in Deutschland (Lebenslagenbericht)",
        "year": 2024,
        "published": "2026",
        "land": "DE",
        "commissioning_body": "Bundesarbeitsgemeinschaft Wohnungslosenhilfe e. V.",
        "authors_organisation": "Bundesarbeitsgemeinschaft Wohnungslosenhilfe e. V.",
        "author": "Sarah Lotties (BAG Wohnungslosenhilfe e. V.)",
        "publisher": "Bundesarbeitsgemeinschaft Wohnungslosenhilfe e. V.",
        "license": RESERVED_LICENCE,
        "license_url": "https://www.bagw.de/de/impressum",
        "redistribute_fulltext": 0,
        "quote": "Schwerpunktthema: Alter(n) und Wohnungsnot",
        "source_notes": (
            "BAG W imprint: texts are copyright of the BAG W or third parties and may be "
            "used only after consultation, with source attribution. Facts, metadata and "
            "short § 51 quotes only. This is the DzW client-data Lebenslagenbericht, not "
            "the BAG W Hochrechnung already held by Counts & Law. The printed sentence on "
            "PDF-S. 4 about 248 Einrichtungen and 45.026 Klient*innendatensätze is not "
            "contiguous in the archived pdftotext -layout text (two-column interleaving) "
            "and those two figures were not stored."
        ),
        "metrics": [
            {
                "entity_type": "de", "entity_id": "DE",
                "metric": "bagw_dzw_acutely_homeless_share_pct",
                "year": 2024, "value": 73, "unit": "percent",
                "is_est": 0, "is_rounded": 1,
                "locator": "PDF-S. 4",
                "quote": "Rund 73 % der Klient*innen im DzW waren akut wohnungslos.",
            },
        ],
    },
    {
        "key": "hf_berlin",
        "url": "https://www.berlin.de/sen/soziales/besondere-lebenssituationen/wohnungslose/wohnen/hfb_evaluationsendbericht_2021_final.pdf",
        "title": "Evaluation des Modellprojekts „Housing First Berlin“. Endbericht Dezember 2021",
        "year": 2021,
        "published": "2021-12",
        "land": "BE",
        "commissioning_body": "Neue Chance gGmbH und Verein für Berliner Stadtmission (Zuwendung der Senatsverwaltung für Integration, Arbeit und Soziales Berlin)",
        "authors_organisation": "Alice Salomon Hochschule Berlin",
        "author": "Susanne Gerull (Alice Salomon Hochschule Berlin)",
        "publisher": "Alice Salomon Hochschule Berlin / Senatsverwaltung für Integration, Arbeit und Soziales Berlin",
        "license": RESERVED_LICENCE,
        "license_url": "https://www.berlin.de/sen/soziales/besondere-lebenssituationen/wohnungslose/wohnen/housing-first-1293115.php",
        "redistribute_fulltext": 0,
        "quote": "Bis zum Ablauf der Modellprojektphase sind 44 Aufnahmen ins Projekt erfolgt, davon 12 Frauen.",
        "source_notes": (
            "Official berlin.de PDF. Berlin site content is treated as reserved-rights "
            "(facts, metadata and short § 51 quotes only), consistent with other Berlin "
            "official sources in this domain. Berichtszeitraum 01.10.2018–31.08.2021."
        ),
        "metrics": [
            {
                "entity_type": "land", "entity_id": "11",
                "metric": "hf_berlin_applications",
                "year": 2021, "value": 611, "unit": "households",
                "is_est": 0,
                "locator": "PDF-S. 30, Abschnitt 4.1",
                "quote": "Danach baten seit dem Start des Modellprojekts am 01. Oktober 2018 bis zum Stichtag 31.08.2021 insgesamt 611 wohnungslose Haushalte um Aufnahme ins Projekt",
            },
            {
                "entity_type": "land", "entity_id": "11",
                "metric": "hf_berlin_admissions",
                "year": 2021, "value": 44, "unit": "persons",
                "is_est": 0,
                "locator": "PDF-S. 30, Abschnitt 4.1",
                "quote": "Bis zum Ablauf der Modellprojektphase sind 44 Aufnahmen ins Projekt erfolgt, davon 12 Frauen.",
            },
            {
                "entity_type": "land", "entity_id": "11",
                "metric": "hf_berlin_housed",
                "year": 2021, "value": 40, "unit": "persons",
                "is_est": 0,
                "locator": "PDF-S. 30, Abschnitt 4.1",
                "quote": "Von diesen konnten 40 Personen mit Wohnraum versorgt werden, davon wiederum 11 Frauen.",
            },
            {
                "entity_type": "land", "entity_id": "11",
                "metric": "hf_berlin_in_support",
                "year": 2021, "value": 37, "unit": "persons",
                "is_est": 0,
                "locator": "PDF-S. 30, Abschnitt 4.1",
                "quote": "Mit Stand 30.09.2021 waren somit 37 Personen in laufender Unterstützung durch das Projekt, davon 10 Frauen.",
            },
        ],
    },
    {
        "key": "hf_frauen",
        "url": "https://www.berlin.de/sen/soziales/besondere-lebenssituationen/wohnungslose/wohnen/hfbff_evaluationsendbericht_2021_final.pdf",
        "title": "Evaluation des Modellprojekts „Housing First für Frauen Berlin“ vom Sozialdienst katholischer Frauen e. V. Berlin. Endbericht Dezember 2021",
        "year": 2021,
        "published": "2021-12",
        "land": "BE",
        "commissioning_body": "Sozialdienst katholischer Frauen e. V. Berlin (Zuwendung der Senatsverwaltung für Integration, Arbeit und Soziales Berlin)",
        "authors_organisation": "Alice Salomon Hochschule Berlin",
        "author": "Susanne Gerull (Alice Salomon Hochschule Berlin)",
        "publisher": "Alice Salomon Hochschule Berlin / Senatsverwaltung für Integration, Arbeit und Soziales Berlin",
        "license": RESERVED_LICENCE,
        "license_url": "https://www.berlin.de/sen/soziales/besondere-lebenssituationen/wohnungslose/wohnen/housing-first-1293115.php",
        "redistribute_fulltext": 0,
        "quote": "Bis zum Ablauf der Modellprojektphase sind 75 Aufnahmen ins Projekt erfolgt.",
        "source_notes": (
            "Official berlin.de PDF. Reserved-rights policy as for other Berlin official "
            "sources. Project-level evaluation figures only; no street address is stored. "
            "Berichtszeitraum 01.10.2018–31.08.2021."
        ),
        "metrics": [
            {
                "entity_type": "land", "entity_id": "11",
                "metric": "hf_frauen_applications",
                "year": 2021, "value": 377, "unit": "households",
                "is_est": 0,
                "locator": "PDF-S. 30, Abschnitt 4.1",
                "quote": "Danach baten seit dem Start des Modellprojekts am 01. Oktober 2018 bis zum Stichtag 31.08.2021 insgesamt 377 wohnungslose Haushalte um Aufnahme ins Projekt",
            },
            {
                "entity_type": "land", "entity_id": "11",
                "metric": "hf_frauen_admissions",
                "year": 2021, "value": 75, "unit": "persons",
                "is_est": 0,
                "locator": "PDF-S. 30, Abschnitt 4.1",
                "quote": "Bis zum Ablauf der Modellprojektphase sind 75 Aufnahmen ins Projekt erfolgt.",
            },
            {
                "entity_type": "land", "entity_id": "11",
                "metric": "hf_frauen_housed_women",
                "year": 2021, "value": 38,  # Lead: 39 was 38 women + 1 non-binary person, a sum not printed in the report "unit": "persons",
                "is_est": 0,
                "locator": "PDF-S. 30, Abschnitt 4.1",
                "quote": "Von diesen konnten 38 Frauen sowie eine sich als non-binär verstehende Person (vgl. 4.2.2) in der Modellprojektphase mit Wohnraum versorgt werden",
                "note": "38 women plus one non-binary person housed during the model phase.",
            },
            {
                "entity_type": "land", "entity_id": "11",
                "metric": "hf_frauen_in_support",
                "year": 2021, "value": 41, "unit": "persons",
                "is_est": 0,
                "locator": "PDF-S. 30, Abschnitt 4.1",
                "quote": "Mit Stand 30.09.2021 waren somit 41 Nutzerinnen in laufender Unterstützung durch das Projekt.",
                "note": (
                    "The 41 still in support on 30.09.2021 include two people not yet housed: "
                    "39 already housed plus two leases shortly before completion. "
                    "PDF-S. 30, Abschnitt 4.1: 'zwei weitere Mietverträge standen zu diesem "
                    "Zeitpunkt zudem kurz vor dem Abschluss.' 75 admissions minus 34 who left "
                    "the project also equals 41. Figures 75 / 39 / 41 are stored verbatim."
                ),
            },
            {
                "entity_type": "land", "entity_id": "11",
                "metric": "hf_frauen_housing_stability_pct",
                "year": 2021, "value": 100, "unit": "percent",
                "is_est": 0,
                "locator": "PDF-S. 83",
                "quote": "Die dauerhafte Erhaltung des Wohnraums gelang bei 100 % der Nutzerinnen.",
            },
        ],
    },
    {
        "key": "hf_hamburg",
        "url": "https://www.buergerschaft-hh.de/parldok/Dokument/105672",
        "title": "Evaluation des Modellprojekts Housing First Hamburg. Abschlussbericht 2025 (Anlage 2 zu Drs. 23/5727)",
        "year": 2025,
        "published": "2026-10-16",
        "land": "HH",
        "commissioning_body": "Bürgerschaft / Senat der Freien und Hansestadt Hamburg",
        "authors_organisation": "Johann Daniel Lawaetz-Stiftung und SÖSTRA GmbH",
        "author": "Peer Gillner (Lawaetz-Stiftung), Gerd Walter (SÖSTRA GmbH)",
        "publisher": "Bürgerschaft der Freien und Hansestadt Hamburg",
        "license": AMT_LICENCE_HH,
        "license_url": "https://www.buergerschaft-hh.de/parldok/lizenz.html",
        "redistribute_fulltext": 1,
        "quote": "Anstelle der vorgesehenen 30 Wohnungen wurden bis zum Ende der Projektlaufzeit insgesamt 37 Wohnungen akquiriert und erfolgreich vermittelt",
        "source_notes": (
            "Official Hamburg ParlDok PDF of Drs. 23/5727 (16.10.2026), including Anlage 2, "
            "the 2025 evaluation. Licence follows the Landtag/ParlDok rule already used "
            "for Hamburg official documents in this domain."
        ),
        "metrics": [
            {
                "entity_type": "land", "entity_id": "02",
                "metric": "hf_hh_tenancies_planned",
                "year": 2025, "value": 30, "unit": "dwellings",
                "is_est": 0,
                "locator": "Drs. 23/5727, PDF-S. 7",
                "quote": "Anstelle der vorgesehenen 30 Wohnungen wurden bis zum Ende der Projektlaufzeit insgesamt 37 Wohnungen akquiriert und erfolgreich vermittelt",
            },
            {
                "entity_type": "land", "entity_id": "02",
                "metric": "hf_hh_tenancies",
                "year": 2025, "value": 37, "unit": "dwellings",
                "is_est": 0,
                "locator": "Drs. 23/5727, PDF-S. 7",
                "quote": "Anstelle der vorgesehenen 30 Wohnungen wurden bis zum Ende der Projektlaufzeit insgesamt 37 Wohnungen akquiriert und erfolgreich vermittelt",
            },
            {
                "entity_type": "land", "entity_id": "02",
                "metric": "hf_hh_open_ended_remaining",
                "year": 2025, "value": 36, "unit": "persons",
                "is_est": 0,
                "locator": "Drs. 23/5727, PDF-S. 7",
                "quote": "36 Mieter:innen leben weiterhin in unbefristeten Mietverhältnissen.",
            },
        ],
    },
    {
        "key": "nds_gerull2020",
        "url": "https://www.berlin.de/sen/soziales/besondere-lebenssituationen/wohnungslose/statistik/gerull_auswertung-der-nacht-der-solidaritaet_barrierefrei.pdf",
        "title": "1. Nacht der Solidarität. Neu- und Weiterberechnung der Befragungsdaten",
        "year": 2020,
        "published": "2020-09-25",
        "land": "BE",
        "commissioning_body": "Senatsverwaltung für Integration, Arbeit und Soziales Berlin",
        "authors_organisation": "Alice Salomon Hochschule Berlin",
        "author": "Susanne Gerull (Alice Salomon Hochschule Berlin)",
        "publisher": "Senatsverwaltung für Integration, Arbeit und Soziales Berlin",
        "license": RESERVED_LICENCE,
        "license_url": "https://www.berlin.de/sen/soziales/besondere-lebenssituationen/wohnungslose/statistik/",
        "redistribute_fulltext": 0,
        "quote": "Für bis zu 282 Menschen liegen Befragungsdaten aus der Straßenzählung vor sowie für bis zu 320 Menschen aus der Kältehilfe.",
        "source_notes": (
            "Official berlin.de method report, a different document from Abgeordnetenhaus "
            "Drs. 19/10884 already held by Counts & Law. The 1.976 / 807 / 942 headcounts "
            "are not stored. Personal contact addresses printed on the cover are not stored."
        ),
        "metrics": [
            {
                "entity_type": "land", "entity_id": "11",
                "metric": "nds_survey_street",
                "year": 2020, "value": 282, "unit": "persons",
                "is_est": 0,
                "locator": "PDF-S. 3, Vorbemerkung",
                "quote": "Für bis zu 282 Menschen liegen Befragungsdaten aus der Straßenzählung vor sowie für bis zu 320 Menschen aus der Kältehilfe.",
                "note": "Survey interviews, not the street-count total already held by Counts & Law.",
            },
            {
                "entity_type": "land", "entity_id": "11",
                "metric": "nds_survey_kaeltehilfe",
                "year": 2020, "value": 320, "unit": "persons",
                "is_est": 0,
                "locator": "PDF-S. 3, Vorbemerkung",
                "quote": "Für bis zu 282 Menschen liegen Befragungsdaten aus der Straßenzählung vor sowie für bis zu 320 Menschen aus der Kältehilfe.",
                "note": "Survey interviews in Kältehilfe facilities, not the facility headcount already held by Counts & Law.",
            },
        ],
    },
    {
        "key": "knoerle2022",
        "url": "https://link.springer.com/content/pdf/10.1007/s00103-022-03536-9.pdf",
        "title": "Zusammenhänge zwischen psychischen Erkrankungen und Wohnungslosigkeit: Ergebnisse einer Sekundärdatenanalyse in einem Berliner Gesundheitszentrum für Obdachlose",
        "year": 2022,
        "published": "2022-05-04",
        "land": "BE",
        "doi": "10.1007/s00103-022-03536-9",
        "commissioning_body": "Charité – Universitätsmedizin Berlin / Gesundheitszentrum für Obdachlose der Jenny De la Torre-Stiftung",
        "authors_organisation": "Charité – Universitätsmedizin Berlin und Gesundheitszentrum für Obdachlose der Jenny De la Torre-Stiftung",
        "author": "Uwe Knörle, Stefan Gutwinski, Stefan N. Willich, Anne Berghöfer",
        "publisher": "Bundesgesundheitsblatt – Springer Nature",
        "license": CC_BY_40,
        "license_url": "https://creativecommons.org/licenses/by/4.0/deed.de",
        "redistribute_fulltext": 1,
        "quote": "Zusammenhänge zwischen psychischen Erkrankungen und Wohnungslosigkeit: Ergebnisse einer Sekundärdatenanalyse in einem Berliner Gesundheitszentrum für Obdachlose",
        "source_notes": (
            "Open-access article, CC BY 4.0 (Projekt DEAL). Clinic-sample findings only; "
            "cited meta-analysis prevalence figures from other papers are not stored. "
            "The Zusammenfassung sentences on 112 patients and 84,9 % with mental illness "
            "already present before homelessness are not contiguous in the archived "
            "pdftotext -layout text (two-column interleaving) and were not stored."
        ),
        "metrics": [],
    },
    {
        "key": "laudien2024",
        "url": "https://link.springer.com/content/pdf/10.1007/s00194-024-00723-7.pdf",
        "title": "Sterbefälle wohnungsloser Menschen vor und während der COVID-19-Pandemie in Hamburg",
        "year": 2024,
        "published": "2024-09-27",
        "land": "HH",
        "doi": "10.1007/s00194-024-00723-7",
        "commissioning_body": "Universitätsklinikum Hamburg-Eppendorf / Institut für Rechtsmedizin",
        "authors_organisation": "Institut für Rechtsmedizin, Universitätsklinikum Hamburg-Eppendorf, und Landeskriminalamt Hamburg",
        "author": "Caroline Laudien, Klaus Püschel, Larissa Lohner, Peter Friedrich, Benjamin Ondruschka",
        "publisher": "Rechtsmedizin – Springer Nature",
        "license": CC_BY_40,
        "license_url": "https://creativecommons.org/licenses/by/4.0/deed.de",
        "redistribute_fulltext": 1,
        "quote": "Todesfälle 112 Wohnungsloser in Hamburg aus den Jahren 2019 (n = 42) und 2021 (n = 70) wurden hinsichtlich des Geschlechts, Alters, Nationalität, Substanzmittelabusus, Ort des Versterbens und der Todesursachen verglichen.",
        "source_notes": "Open-access article, CC BY 4.0. Cases recorded at LKA 41 Hamburg; not a complete civil-registration mortality census.",
        "metrics": [
            {
                "entity_type": "land", "entity_id": "02",
                "metric": "hh_homeless_deaths_lka",
                "year": 2019, "value": 42, "unit": "persons",
                "is_est": 0,
                "locator": "Rechtsmedizin 2024, Zusammenfassung",
                "quote": "Todesfälle 112 Wohnungsloser in Hamburg aus den Jahren 2019 (n = 42) und 2021 (n = 70) wurden hinsichtlich des Geschlechts, Alters, Nationalität, Substanzmittelabusus, Ort des Versterbens und der Todesursachen verglichen.",
                "note": "LKA 41 cases of deceased people recorded as without a fixed address.",
            },
            {
                "entity_type": "land", "entity_id": "02",
                "metric": "hh_homeless_deaths_lka",
                "year": 2021, "value": 70, "unit": "persons",
                "is_est": 0,
                "locator": "Rechtsmedizin 2024, Zusammenfassung",
                "quote": "Todesfälle 112 Wohnungsloser in Hamburg aus den Jahren 2019 (n = 42) und 2021 (n = 70) wurden hinsichtlich des Geschlechts, Alters, Nationalität, Substanzmittelabusus, Ort des Versterbens und der Todesursachen verglichen.",
                "note": "LKA 41 cases of deceased people recorded as without a fixed address.",
            },
        ],
    },
    {
        "key": "hf_fonds_nrw",
        "url": "https://www.giss-ev.de/filestorage/projekte/2020/housing-first-paritaetischer-endbericht.pdf",
        "title": "Evaluation des Housing-First-Fonds NRW. Endbericht (Stand Oktober 2020)",
        "year": 2020,
        "published": "2020-10",
        "land": "NW",
        "commissioning_body": "Paritätischer Wohlfahrtsverband, Landesverband Nordrhein-Westfalen",
        "authors_organisation": "Gesellschaft für innovative Sozialforschung und Sozialplanung e. V. (GISS)",
        "author": "Volker Busch-Geertsema (GISS)",
        "publisher": "GISS e. V. / Der Paritätische NRW",
        "license": RESERVED_LICENCE,
        "license_url": "https://www.giss-ev.de/pages/4/impressum/",
        "redistribute_fulltext": 0,
        "quote": "Bis Mitte Oktober 2020 konnten Kooperationsverträge mit 22 Trägern geschlossen werden, darunter auch mit acht Trägern, die nicht dem Paritätischen angehören",
        "source_notes": (
            "GISS end report for the Paritätischer NRW. The GISS imprint states no reuse "
            "terms for publications; the report is stored under reserved-rights terms "
            "(facts, metadata and short § 51 quotes only). This is not the unfinished "
            "2026 formative evaluation of Housing First scaling-up in Düsseldorf."
        ),
        "metrics": [
            {
                "entity_type": "land", "entity_id": "05",
                "metric": "hf_fonds_nrw_provider_contracts",
                "year": 2020, "value": 22, "unit": "organisations",
                "is_est": 0,
                "locator": "PDF-S. 7, Abschnitt 2.1",
                "quote": "Bis Mitte Oktober 2020 konnten Kooperationsverträge mit 22 Trägern geschlossen werden, darunter auch mit acht Trägern, die nicht dem Paritätischen angehören",
            },
        ],
    },
    {
        "key": "hsbn2024",
        "url": "https://www.ms.niedersachsen.de/download/211038/HSBN_2024.pdf",
        "title": "Handlungsorientierte Sozialberichterstattung Niedersachsen. Statistikteil Bericht 2024",
        "year": 2024,
        "published": "2024",
        "land": "NI",
        "commissioning_body": "Niedersächsisches Ministerium für Soziales, Arbeit, Gesundheit und Gleichstellung",
        "authors_organisation": "Landesamt für Statistik Niedersachsen (LSN)",
        "author": "Landesamt für Statistik Niedersachsen (LSN)",
        "publisher": "Niedersächsisches Ministerium für Soziales, Arbeit, Gesundheit und Gleichstellung",
        "license": RESERVED_LICENCE,
        "license_url": "https://www.ms.niedersachsen.de/startseite/uber_uns/wir_uber_uns/impressum/impressum-14130.html",
        "redistribute_fulltext": 0,
        "quote": "Obdachlose, die ohne jede Unterkunft sind, also „auf der Straße leben“ oder Menschen in verdeckter Wohnungslosigkeit, die zum Beispiel bei Bekannten oder Angehörigen unterkommen, werden von der Statistik untergebrachter wohnungsloser Personen nicht erfasst.",
        "source_notes": (
            "Official Land social report, chapter 9.7 Wohnungslosigkeit. The NI imprint "
            "reserves copyright and forbids reproduction without prior consent. Destatis "
            "22971 and Wohnungslosenbericht 2022 reprints in that chapter are not stored; "
            "Counts & Law already holds those figures. Facts, metadata and a short § 51 "
            "quote only."
        ),
        "metrics": [],
    },
]



def study_document_text(url: str) -> str:
    """Fetch an official URL and return the unmodified archived document text.

    PDFs are extracted with `pdftotext -layout` only, the same rendering
    `common.document_text` writes for the archive. No second stream is
    concatenated, and no lines are added before quote matching.
    """
    raw = fetch(url, domain=DOMAIN)
    if raw.startswith(b"%PDF"):
        text = pdf_text_from_bytes(raw)
        if not text or not text.strip():
            raise RuntimeError(f"pdftotext failed for {url}")
        return text
    from ingest.common import html_to_text
    head = raw[:2048].lower()
    if b"<html" in head or b"<!doctype html" in head:
        return html_to_text(raw)
    return raw.decode("utf-8", "replace")


def _im():
    from ingest.domains import institutions_media as module
    return module


def figure_held_by_counts_law(value, unit: str | None) -> bool:
    """Return True if this numeric figure is a headline count Counts & Law already holds."""
    if value is None:
        return False
    unit = (unit or "").lower()
    if unit in {"percent", "per_1000_households", "municipalities", "facilities",
                "records", "organisations", "dwellings", "flag"}:
        return False
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    if number != int(number):
        return False
    return int(number) in COUNTS_LAW_HELD_PERSONS


def required_metadata_ok(rec: dict) -> bool:
    return all([
        clean(rec.get("url")),
        clean(rec.get("title")),
        clean(rec.get("commissioning_body")),
        clean(rec.get("authors_organisation")),
        rec.get("year"),
        clean(rec.get("license")),
        clean(rec.get("quote")),
    ])


def ensure_study_tables(conn) -> None:
    conn.executescript(STUDY_DDL)
    _im().ensure_source_extensions(conn)


def store_study(conn, rec: dict, *, sources) -> bool:
    ensure_study_tables(conn)
    if not required_metadata_ok(rec):
        return False
    if not stored_fields_name_ok(
        rec.get("title"), rec.get("author"), rec.get("quote"),
        rec.get("commissioning_body"), rec.get("authors_organisation"),
        rec.get("publisher"),
    ):
        return False
    licence = clean(rec.get("license"))
    url = clean(rec.get("url"))
    source_id = _im()._register_source(
        conn, url,
        title=clean(rec.get("title")),
        publisher=clean(rec.get("publisher")) or clean(rec.get("authors_organisation")),
        license_=licence,
        bucket=sources,
        license_url=clean(rec.get("license_url")),
        attribution=clean(rec.get("publisher")) or clean(rec.get("authors_organisation")),
        notes=clean(rec.get("source_notes")),
        redistribute_fulltext=0 if rec.get("redistribute_fulltext", 0) == 0 else 1,
    )
    land = rec.get("land") if rec.get("land") in (set(_im().LANDS) | {"DE"}) else "DE"
    upsert(conn, "doc", {
        "kind": "study",
        "title": clean(rec.get("title")),
        "url": url,
        "herausgeber": clean(rec.get("publisher")),
        "urheber": clean(rec.get("author")),
        "veroeffentlicht": clean(rec.get("published")),
        "ort": None,
        "land": land,
        "zusammenfassung": trim_quote(rec.get("quote")),
        "source_id": source_id,
    }, ["url"])
    row = conn.execute("SELECT id FROM doc WHERE url=?", (url,)).fetchone()
    if not row:
        return False
    upsert(conn, "institutions_media_study", {
        "url": url,
        "doc_id": row["id"],
        "commissioning_body": clean(rec.get("commissioning_body")),
        "authors_organisation": clean(rec.get("authors_organisation")),
        "year": int(rec["year"]),
        "doi": clean(rec.get("doi")),
        "quote": trim_quote(rec.get("quote")),
        "source_id": source_id,
    }, ["url"])
    return True


def ingest_studies(conn, cfg, sources, notes) -> int:
    ensure_study_tables(conn)
    stored = 0
    metrics_stored = 0
    metrics_blocked = 0
    missing_quote = 0
    failed = 0
    skipped_meta = 0
    for rec in CATALOG:
        rec = dict(rec)
        if not required_metadata_ok(rec) or not stored_fields_name_ok(
            rec.get("title"), rec.get("author"), rec.get("quote"),
            rec.get("commissioning_body"), rec.get("authors_organisation"),
        ):
            skipped_meta += 1
            notes.append(f"Study skipped (metadata or name rule): {rec.get('key')}")
            continue
        try:
            text = study_document_text(rec["url"]) if not cfg.get("skip_verify") else rec.get("document_text") or rec.get("quote")
        except Exception as exc:
            failed += 1
            notes.append(f"Study fetch failed {rec.get('key')}: {type(exc).__name__}: {str(exc)[:180]}")
            continue
        if not text or not quote_in_text(rec["quote"], text):
            missing_quote += 1
            notes.append(f"Study quote not found in document, not stored: {rec['url']}")
            continue
        if not store_study(conn, rec, sources=sources):
            skipped_meta += 1
            continue
        stored += 1
        source_id = conn.execute("SELECT source_id FROM doc WHERE url=?", (rec["url"],)).fetchone()["source_id"]
        for metric in rec.get("metrics") or []:
            if figure_held_by_counts_law(metric.get("value"), metric.get("unit")):
                metrics_blocked += 1
                notes.append(
                    f"Study metric skipped (already in counts_law): "
                    f"{metric.get('metric')}={metric.get('value')}"
                )
                continue
            if store_cited_metric(conn, metric, source_id=source_id, document_text=text, notes=notes):
                metrics_stored += 1
    notes.append(
        f"Studies stored={stored} catalog={len(CATALOG)} metrics={metrics_stored} "
        f"metrics_blocked_overlap={metrics_blocked} fetch_failed={failed} "
        f"quote_missing={missing_quote} meta_skipped={skipped_meta}. "
        "Documents already held by Counts & Law (Wohnungslosenbericht 2022/2024, "
        "BAG W Hochrechnung 2018–2024, NRW WNB, Hamburg GOE 2018, München "
        "Produktcontrolling, BW GISS 2015, Liga BW) were not added. "
        "Gaps: SEEWOLF has no open-licensed official full text (Thieme article / "
        "Lambertus book; the giss-ev.de PDF is a review and was not stored); "
        "the GISS formative evaluation of Housing First scaling-up in Düsseldorf "
        "(announced 25.08.2026) has no published end report; earlier BAG W "
        "Statistikberichte were not ingested (2024 only); Berlin Sozialbericht 2025 "
        "was not ingested (Destatis/WB reprints, and berlin.de returned HTTP 429 "
        "during this pass)."
    )
    return stored


if __name__ == "__main__":
    from ingest.common import no_direct_run
    raise SystemExit(no_direct_run("institutions_media"))
