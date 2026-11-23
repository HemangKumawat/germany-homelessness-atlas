# funding_traeger — Träger and the public money that pays them

Module: `ingest/domains/funding_traeger.py` (`DOMAIN = "funding_traeger"`, target table `award`).
`run(conn, cfg)` runs the readers listed in `cfg["sources"]` (default: all):

| reader | cfg key | rows land in |
|---|---|---|
| Berlin Zuwendungsdatenbank | `berlin_zuwendungen` | `award` (`award_type='zuwendung'`), `org`, `org_register` (`BE_ZUWDB`), private `funding_traeger_zuwendung` |
| TED award notices (EU Official Journal S) | `ted` | `award` (`award_type='contract'`), `org`, `org_register` (`USt-IdNr` only), private `funding_traeger_ted_notice`, `funding_traeger_ted_award` |

Rules applied by both readers:
- Organisation level only. Natural persons, GbRs and unnamed winners are skipped; no contact persons,
  e-mail or phone numbers are read into any table.
- Protected shelters (Frauenhaus, Schutzwohnung, Zufluchtswohnung, Gewaltschutz, häusliche Gewalt …):
  the org is inserted with `is_protected=1` and no address / plz / coordinates; TED notices tagged
  `protected_shelter` keep only org, value and dates (no winner city, NUTS or buyer office).
- Refugee accommodation is tagged, not mixed in: Berlin `tags` contains `refugee`; TED `award.program`
  starts with `[refugee]` and the private notice table has `tags`. Headline homelessness figures should
  exclude these rows.
- `currency='EUR'` is set explicitly; names are normalised with `common.name_norm`; existing `org` rows
  are never modified (lookup on `name_norm` + `land`).
- No transaction handling in the module: the runner owns BEGIN/COMMIT. `--selftest --db <scratch>` runs
  inside one transaction and rolls back.

Worker commands (never data/atlas.db):
```
python3 tests/test_funding_traeger.py                       # offline fixtures
python3 -m ingest.domains.funding_traeger --test           # same, inline
python3 -m ingest.domains.funding_traeger --dryrun [--source=ted|berlin_zuwendungen] [--out=…jsonl]  # in-memory DB
python3 -m ingest.domains.funding_traeger --selftest --db /tmp/fund_scratch.db   # scratch DB, rolled back
```

## Source 1 — Berlin Zuwendungsdatenbank (`cfg["sources"]=["berlin_zuwendungen"]`)

Reader: `run_berlin_zuwendungen()`.

### Source
| | |
|---|---|
| Publisher | Senatsverwaltung für Finanzen Berlin (administrator; data entered by each grant-giving body) |
| Landing page | https://www.berlin.de/sen/finanzen/service/zuwendungsdatenbank/ |
| Bulk export | https://www.berlin.de/sen/finanzen/service/zuwendungsdatenbank/index.php/index/all.json?q= (one GET, ~20.2 MB, 55,454 grants on 2026-11-20; the reader aborts if the declared count differs from the received count) |
| Per-row citation | https://www.berlin.de/sen/finanzen/service/zuwendungsdatenbank/index.php/detail/&lt;id&gt; (HTML: Name, Geber, Art, Jahr, Anschrift, Politikbereich, Zweck, Betrag, Registrierungsnummer) |
| Licence | CC BY-SA — Berlin Open Data register entry `simple_search_wwwberlindesenfinanzenservicezuwendungsdatenbank` (https://datenregister.berlin.de/api/3/action/package_show?id=simple_search_wwwberlindesenfinanzenservicezuwendungsdatenbank → `license_id` `cc-by-sa`; the daten.berlin.de HTML page answers 403 to curl) |
| robots.txt | www.berlin.de/robots.txt disallows only `/*/(S(*))`, `/kino/_bin/trefferliste.php`, `/land/kalender/print/`, `/land/kalender/qrcode.php`, `/presse/pressemitteilungen/index/search/`, `/stadtplan`; this path is allowed. |
| Load | 1 bulk GET + 1 GET per kept grant (~632) at ≤ 1 req/s, all cached in `data/raw/funding_traeger/`; `cfg["bz_details"]=False` skips the detail pages. |

Publisher's description (landing page, read 2026-11-20): grants approved on application ("auf Antrag
bewilligten Zuwendungen", from EUR 100) for the past five calendar years, refreshed each 30 June; grants to
natural persons and GbRs are only published as one sum per Politikbereich (Nr. 9.4 AV i. V. m. Nr. 1.5.1 AV
zu § 44 LHO). Currently 2021–2025; 2025 is marked provisional ("vorläufige Daten").

### Mapping
| target | from |
|---|---|
| `award.award_key` / `award_id` | `DE-BE-ZUW:<id>` / `<id>` |
| `award.recipient_name / recipient_norm` | `name` / `common.name_norm(name)` |
| `award.recipient_register` | `empfaengerid` as published (e.g. `vr_021507`, `hrb_267728`) |
| `award.award_type` | `zuwendung` |
| `award.agency / program / description` | `geber` / `art` (Projektförderung, institutionelle Förderung) / `zweck` |
| `award.amount_total`, `currency` | `betrag`, `'EUR'` |
| `award.fy`, `place_land` | `jahr`, `'BE'` (recipient seat; not the place of service) |
| `award.quote`, `locator` | `"Betrag: <n>"` exactly as on the detail page, `Detailseite, Feld 'Betrag' (EUR)`; when the detail page cannot be fetched the row cites the bulk export with locator `JSON-Gesamtexport, index[] mit id=<id>` and no quote |
| `award.source_id` | the detail-page source (fallback: bulk export) |
| `org` | inserted only if `(name_norm, land='BE')` is not present: name, `register_id`, address1/plz/city from `anschrift` (none for protected) |
| `org_register` | scheme `BE_ZUWDB`, court `''`, number = raw `empfaengerid`. The court is not published, so a court-less VR/HRB number could collide across courts; the Lead can promote these to VR/HRB once the court is known. |
| `funding_traeger_zuwendung` | all raw fields + `tier`, `matched_terms`, `tags`, `detail_url` |

### Selection (on `zweck`)
- **core**: wohnungslos*, obdachlos*, Wohnungsnot*, Wohnungsnotfall*, Kältehilfe*, Kältebus, Wärmestube,
  Notübernachtung*, Nachtcafé, Housing First, Bahnhofsmission, "ohne (eigenen) Wohnraum", Zwangsräumung*,
  Wohnungsverlust*, Mietschulden*, § 67 SGB XII, Wohnungslosentagesstätte.
- **adjacent** (flagged): Straßensozialarbeit, Suppenküche, Kleiderkammer, Notunterkunft*, Notunterbringung*,
  Essensausgabe; dropped when the text is about refugees without a core term. Contains youth street work,
  drug and sex-work outreach — **use `tier='core'` for headline figures.**
- Privacy: rows with empty / `ohne` / `gbr_` register id or "natürliche Person" are skipped.
- Tags: `refugee` (Geflüchtete / Flüchtling / Asyl in `zweck`), `protected_shelter`.

### Dry run (2026-11-20)
Full run 2026-11-21 into a scratch DB built from main's schema (`/tmp/fund_verify.db`, never atlas.db):
- export 55,454 grants (declared == received); kept **632** (core 557 / adjacent 75), **114** recipients,
  125 Berlin org rows, 97 `org_register` rows (`BE_ZUWDB`); 2 natural-person/GbR rows skipped.
- **EUR 158,307,147** (core EUR 144,256,401). By year (rows, EUR): 2021 130 / 40,237,365 · 2022 106 / 26,128,263 ·
  2023 149 / 31,161,798 · 2024 137 / 32,280,583 · 2025 110 / 28,499,138 (2025 provisional).
- All 632 detail pages fetched (0 fell back to the bulk export), so every row cites its own page and carries
  `quote = "Betrag: <n>"`. 7 rows tagged `refugee`, 0 `protected_shelter`.
- Largest recipients: Verein für Berliner Stadtmission (68 grants, EUR 29,175,487); KARUNA eG (14, EUR 23,435,951);
  GEBEWO pro gGmbH (35, EUR 11,435,194).

### Verified (Berlin)
Live detail pages fetched 2026-11-20 with the project User-Agent; name, Geber, Jahr, Zweck and the exact
`Betrag` string were found on each page and match the row:
1. https://www.berlin.de/sen/finanzen/service/zuwendungsdatenbank/index.php/detail/83141 — Katholische Kirchengemeinde Maria unter dem Kreuz, BA Charlottenburg-Wilmersdorf, 2021, "Kältehilfe, Suppenküche St. Marien", Betrag 26765
2. https://www.berlin.de/sen/finanzen/service/zuwendungsdatenbank/index.php/detail/51653 — Evangelischer Kirchenkreis Neukölln, BA Neukölln, 2021, "Kältehilfe - Nachtcafe Fürbitt-Melanchthon Kirche", Betrag 19648
3. https://www.berlin.de/sen/finanzen/service/zuwendungsdatenbank/index.php/detail/101750 — Merkur e. V. Berlin f. soziale Arbeit, BA Lichtenberg, 2023, "Notübernachtung im Rahmen der Kältehilfe", Betrag 137812
4. https://www.berlin.de/sen/finanzen/service/zuwendungsdatenbank/index.php/detail/25805 — bisous e. V., BA Friedrichshain-Kreuzberg, 2024, "Wrangelkiez Suppenküche", Betrag 3500 (adjacent tier)
5. https://www.berlin.de/sen/finanzen/service/zuwendungsdatenbank/index.php/detail/40937 — DRK Berlin Südwest Soziale Arbeit, Beratung und Bildung, BA Steglitz-Zehlendorf, 2021, "Wohnungsanmietung für wohnungslose Menschen mit Fluchthintergrund", Betrag 50000 (tagged `refugee` via "Fluchthintergrund")
6. https://www.berlin.de/sen/finanzen/service/zuwendungsdatenbank/index.php/detail/82868 — KARUNA eG, 2024, "Obdachlosenlots*In", Betrag 4808614
7. https://www.berlin.de/sen/finanzen/service/zuwendungsdatenbank/index.php/detail/8528 — AWO Berlin Spree-Wuhle e. V., "Wohnungslosentagesstätte Kiezcafé", 2021, Betrag 200250
In addition, every row of the dry run with a `quote` was matched automatically: the reader only sets
`quote` when the page's `Betrag` equals the export's `betrag`.

### Coverage (Berlin)
- Universe: Berlin Zuwendungen (Senat + 12 Bezirke) 2021–2025 whose purpose text names homelessness work.
  Captured: every matching row of the publisher's complete export (keyword recall, not a manual census).
- **Not covered, and large:** most Berlin homelessness money is not a Zuwendung. ASOG-Unterbringung and
  Hilfen nach §§ 67 ff. SGB XII are paid as Entgelte / Tagessätze under contracts and appear in
  Haushaltspläne, not here. Kältehilfe is partly Zuwendung (captured), partly contracts.
- Grants whose `zweck` does not use the vocabulary (e.g. a Träger's general institutional grant) are missed;
  `matched_terms` makes the filter auditable.
- Only five years are online; older years drop out every 30 June. Re-running yearly accumulates history.
- Grants to natural persons / GbRs are published only as aggregates and are excluded.
- berlin.de intermittently answers a detail request with **HTTP 307 to the same URL** (a soft throttle,
  seen at 1 req/s, more often when another client shares the IP). The reader retries twice with 5 s / 10 s
  back-off; if it still fails, the row cites the bulk export (number still verifiable there, no quote).

## Source 2 — TED award notices (`cfg["sources"]=["ted"]`)

Reader: `run_ted()`.

### Source
| | |
|---|---|
| Publisher | Publications Office of the European Union, TED (Supplement to the Official Journal, series S) |
| Search | `POST https://api.ted.europa.eu/v3/notices/search` (anonymous; `{query, fields, limit<=250, page}`); used only to find publication numbers, not registered as a source |
| Per-row citation | `https://ted.europa.eu/en/notice/<pub>/xml` (the notice as published; registered as `source`, archived with sha256). Human-readable PDF: `https://ted.europa.eu/de/notice/<pub>/pdf`. The HTML detail page answers 202 with an empty body to non-browser clients, so it is not cited. |
| Licence | "© European Union, 1998-2026 … Unless otherwise noted, the procurement notices published in the Supplement to the Official Journal of the European Union can be freely reused, for commercial or non-commercial purposes." — https://ted.europa.eu/en/legal-notice (read 2026-11-20; Commission Decision 2011/833/EU). Stored verbatim in `source.license`. |
| robots / load | notice pages are not disallowed; 1 request/s with the project User-Agent; every response cached in `data/raw/funding_traeger/` |

### Query
`buyer-country = DEU AND FT ~ (<keyword>) AND classification-cpv IN (<CPVs>)`, one query per keyword, deduplicated
on publication number. Wildcards inside `FT ~ (…)` return 0 hits, so whole words are listed:
wohnungslose, wohnungslos, Wohnungslosen, obdachlose, obdachlos, Obdachlosen, Obdachlosenunterkunft,
Obdachlosenunterbringung, Wohnungslosenhilfe, Wohnungslosenunterkunft, Obdachlosenhilfe, Notunterkunft,
Notunterkünfte, Notübernachtung, Kältehilfe, Wohnungsnotfall, Wohnungsnotfallhilfe, Wohnungsnotfälle,
Obdachlosigkeit, Wohnungslosigkeit.
CPVs: 85300000, 85310000, 85311000, 85312000, 85312100, 85312200, 85312300, 85312310, 85312320, 85312400,
85312500, 85320000, 85321000, 85322000 (social work), 98341000, 98341100 (accommodation / management services),
55100000, 55110000, 55200000, 55250000, 55270000 (accommodation), 70333000 (housing services).

### Parsing
- Two XML shapes: legacy `TED_EXPORT` R2.0.9 (`F03_2014`, `F21_2014`, …: `AWARD_CONTRACT/AWARDED_CONTRACT/CONTRACTORS/VAL_TOTAL`)
  and eForms UBL (`efac:NoticeResult/LotResult/LotTender/TenderingParty` → `efac:Organization`).
- One `award` row per (notice, contract/lot, winner): `award_key = TED:<pub>:<contract ref>:<winner name_norm>`.
  Consortia: every member gets a row, the value goes on the lead member only (others `amount_total=NULL`).
- Values are the published award value without VAT (`VAL_TOTAL` / `cbc:PayableAmount` or tender amount);
  ranges (`VAL_RANGE`) are kept in the private table only. Currency from the XML (all 220 rows are EUR).
- **Withheld values:** buyers who don't disclose the value publish placeholders (-1, 0.01, 0.11, 1, 1.5, 4.41
  in this run). Any value below EUR 100 is treated as not disclosed: `amount_total=NULL`, raw figure in
  `funding_traeger_ted_award.value_published_raw`, notice tag `value_withheld_placeholder` (93 award rows).
- Winner national id: a `DE#########` USt-IdNr goes to `org.ust_id` + `org_register(USt-IdNr)`; a value that
  parses as a VR/HRA/HRB/GnR/PR number goes to `award.recipient_register`; anything else (eForms internal
  GUIDs, e-procurement ids) stays in `award.recipient_id` only.
- `award.quote` = the XML element that publishes the value, verbatim (e.g. `<cbc:PayableAmount currencyID="EUR">1973970</cbc:PayableAmount>`), `award.locator` = contract/lot + element; all 74 valued rows carry one.
- `award.place_land` = Land of the buyer's NUTS code; `award.fy` = year of the award decision (else publication).
- Every notice found is kept in `funding_traeger_ted_notice` (buyer, title, CPV, dates, tags); only notices
  that publish a result with a named winner (can-*, can-modif, veat, some corr) produce `award` rows.
- `ted_is_person()` skips winners that look like natural persons (no legal-form or organisation token,
  "Herr/Frau", e.K./Inhaber, GbR (partners are natural persons), bare personal names); 16 winners skipped in the full run.

### Full run (2026-11-21, scratch DB /tmp/fund_verify.db built from main's schema; never atlas.db)
- 431 notices found and parsed: cn-standard 212, can-standard 138, cn-social 34, can-social 29, corr 11,
  can-modif 5, can-desg 1, veat 1; 0 failed.
- **215 award rows**, 126 distinct winners; 74 rows carry a value (each with a verbatim quote).
- **Total EUR 188,918,991.02** (only currency: EUR). Without refugee-tagged rows: 124 rows, EUR 129,172,103.21.
- Refugee-tagged notices 224 (91 award rows); protected-shelter notices 16.
- By Land (rows): BY 54, NW 45, HH 28, NI 25, HE 13, BB 12, BE 11, SN 10, ST 5, BW 5, SH 4, MV 3.
- Largest winners by summed value: European Homecare GmbH (13 rows, EUR 26,965,920.47, refugee-heavy),
  DRK Betreuungsdienste Westfalen-Lippe gGmbH (7, EUR 20,277,489.90), ABC Kochwerk Bremen GmbH (1, EUR 15,000,000,
  catering for Landesaufnahmebehörde Niedersachsen, refugee), Hero Services gGmbH (4, EUR 9,102,717.20).

### Verified (TED)
Live PDFs `https://ted.europa.eu/de/notice/<pub>/pdf` fetched 2026-11-20 with the project User-Agent, text via
`pdftotext`; winner name, buyer name and the exact award value were found in each:
1. https://ted.europa.eu/en/notice/660611-2025/xml — Wäscherei Kellner GmbH, Landesaufnahmebehörde Niedersachsen, EUR 977,400.00, 2025, NI, [refugee]
2. https://ted.europa.eu/en/notice/811706-2025/xml — BEWA Security GmbH, Bezirksregierung Köln, EUR 1,551,428.04, 2025, NW
3. https://ted.europa.eu/en/notice/665831-2024/xml — DRK Betreuungsdienste Westfalen-Lippe gGmbH, Bezirksregierung Münster, EUR 5,287,891.52, 2024, NW
4. https://ted.europa.eu/en/notice/861307-2025/xml — AWO KV Oberlausitz e.V., Stadtverwaltung Görlitz, EUR 1,973,970.00, 2025, SN (can-social)
5. https://ted.europa.eu/en/notice/790451-2026/xml — Forward-Soziale Dienste GmbH, Land Niedersachsen / Staatliches Baumanagement, EUR 341,540.00, 2026, NI
6. https://ted.europa.eu/en/notice/244267-2022/xml — Lawaetz-wohnen & leben gGmbH, Finanzbehörde Hamburg, Lose 6/7 at EUR 1,496,000.00 each
   (PDF: "Gesamtwert des Auftrags/Loses: 1 496 000,00 EUR"; 10 lots, notice total 14 960 000,00 EUR).
The same check on an earlier sample found four placeholder values (587518-2026 and 78157-2024: -1; 714260-2022: 0.01;
607751-2025: 1). That led to the withheld-value rule above.

### Coverage (TED)
- Universe: above-EU-threshold public contracts by German buyers whose notice text uses one of the
  20 homelessness words and whose CPV is social work / accommodation. Captured: every notice the API returns
  for those queries (2016–2026), parsed in both XML generations.
- Not covered: below-threshold awards (Land/municipal Vergabeportale), entgelt agreements under §§ 75 ff.
  SGB XII and ASOG accommodation that are never tendered, Zuwendungen, and notices that only use other words
  (e.g. "Unterbringung" alone, "Gemeinschaftsunterkunft").
- 141 of 215 award rows have no usable value (withheld, consortium member, or value only at notice level).
- "Refugee" appears in many notices that also cover homeless people (shared municipal Unterkünfte); the tag is
  deliberately broad and errs towards exclusion from homelessness headline figures.

## SOURCES.md rows (for the Lead to append to "Ingested sources")

| Source | Gives | Licence / terms | Endpoint | Ingestor |
|---|---|---|---|---|
| Zuwendungsdatenbank des Landes Berlin (Senatsverwaltung für Finanzen), JSON-Gesamtexport | every Berlin Zuwendung 2021–2025 (recipient, Registrierungsnummer, Geber, Art, Zweck, Betrag EUR); fallback citation when a detail page is unavailable | CC BY-SA (Berlin Open Data, datenregister.berlin.de entry simple_search_wwwberlindesenfinanzenservicezuwendungsdatenbank, license_id cc-by-sa) | https://www.berlin.de/sen/finanzen/service/zuwendungsdatenbank/index.php/index/all.json?q= | `funding_traeger` |
| Zuwendungsdatenbank des Landes Berlin, Detailseite je Zuwendung | per-grant citation; `award.quote` = "Betrag: <n>" | CC BY-SA (as above) | https://www.berlin.de/sen/finanzen/service/zuwendungsdatenbank/index.php/detail/<id> | `funding_traeger` |
| TED – Tenders Electronic Daily (Supplement to the Official Journal of the EU), notice XML | German award notices for homelessness services: buyer, winner organisations, award value + currency, dates, CPV | "© European Union, 1998-2026 … the procurement notices published in the Supplement to the Official Journal of the European Union can be freely reused, for commercial or non-commercial purposes." (https://ted.europa.eu/en/legal-notice; Commission Decision 2011/833/EU) | https://ted.europa.eu/en/notice/<pub>/xml (found via POST https://api.ted.europa.eu/v3/notices/search, which is not itself cited) | `funding_traeger` |

Not added to docs/SOURCES.md by the worker: the "Ingested sources" table says the Lead appends at merge time.

## Source map — what to build next (prioritised)

| # | Source | Access | Licence / terms | What it gives | Status |
|---|---|---|---|---|---|
| 1 | Berlin Zuwendungsdatenbank | bulk JSON + detail pages | CC BY-SA | Berlin grants 2021–2025 | **done** (this module) |
| 2 | TED award notices | API v3 search + notice XML | EU reuse (2011/833/EU) | above-threshold contracts, winners, values | **done** (this module) |
| 3 | Hamburg Transparenzportal | CKAN `https://suche.transparenz.hamburg.de/api/3/action/package_search?q=…` | dl-de per dataset | contracts ≥ EUR 100k under HmbTG (e.g. f&w fördern und wohnen AöR), quarterly Zuwendungsvorgänge | next; q=obdachlos → 1,023 packages (2026-11-20); separate refugee contracts |
| 4 | ESF Plus / EHAP Plus Liste der Vorhaben | https://www.esf.de/portal/DE/ESF-Plus-2021-2027/Liste-der-Vorhaben/inhalt.html | EU-mandated publication (Art. 49 CPR 2021/1060) | EHAP Plus beneficiaries (homeless / at-risk EU citizens), project, cost, EU share | next; locate the xlsx link |
| 5 | Lobbyregister Bundestag API v2 | `https://api.lobbyregister.bundestag.de/rest/v2/registerentries` + `Authorization: ApiKey <key>` | open data; key published on the open-data page | Wohlfahrtsverbände: lobbying spend, public allowances received, donors, persons entrusted (published roles) | **blocked on a decision**: 401 without key; the key must be stored outside git (`~/.config/germany-atlas/env`) by the Lead/Hemang |
| 6 | Förderkatalog des Bundes | https://foerderportal.bund.de/foekat/ | terms not stated; robots.txt answers 403 → go slow / ask | federal project grants | later |
| 7 | EU Financial Transparency System | https://ec.europa.eu/budget/financial-transparency-system/ | EU reuse | direct EU funds | later, small |
| 8 | Bundeshaushalt / Länder & municipal Haushaltspläne | bundeshaushalt.de; daten.berlin.de Doppelhaushalt CSV; PDFs elsewhere | mostly dl-de / CC BY | budget lines for Wohnungslosenhilfe, ASOG, Kältehilfe, § 67 SGB XII — **where most of the money is** | later, M–L |
| 9 | Other Zuwendungsberichte (Bremen, NRW, Sachsen, München …) | per publisher | varies | same shape as Berlin | later |
| 10 | Annual reports / Jahresabschlüsse of the big Träger; Handels-/Vereinsregister | Träger sites; unternehmensregister.de; handelsregister.de | publisher terms; registers restrict automation | revenue, staff, places, Geschäftsführung / Vorstand as published, with document citation | manual, per org |
| — | Transparenzregister | — | public access ended (CJEU C-37/20) | beneficial owners | **do not use** |

Join keys: Berlin `empfaengerid` (vr_/hrb_/gnr_/spr_ + number, court unknown) → Vereins-/Handelsregister;
TED USt-IdNr; Lobbyregister R-number. All via `org_register`.

## Caveats and blockers
- Entgelt-financed services (ASOG-Unterbringung, §§ 67 ff. SGB XII) are the bulk of homelessness spending and
  appear in neither source; they need Haushaltspläne and answers to parliamentary questions (PARDOK).
- TED values: 93 award rows carried placeholders (< EUR 100) and are stored as NULL; consortium members
  other than the lead carry NULL; some notices give only a notice-level total. Do not sum TED values as
  "money paid": they are contract values at award, often multi-year, sometimes framework ceilings.
- TED refugee tag is broad (224 of 431 notices); headline homelessness figures should filter `[refugee]`.
- Berlin detail pages: soft-throttle HTTP 307 (see Coverage); a full run fetches ~632 pages and took
  about 35 minutes at ≤ 1 req/s with retries (all pages eventually served).
- Grok Build headless (the delegated worker) stalled with no output and was killed; the TED reader was
  written and verified directly.
- Lobbyregister needs its published API key stored outside git — decision for the Lead.
- verify.py on the scratch DB (with the three SOURCES rows above appended to a local, uncommitted copy of
  docs/SOURCES.md): G1–G6, G8, G9 PASS; **G7 flags org 'Neue Chance'** as a possible person name. It is a
  company (Berlin Registrierungsnummer `hrb_115888`, Kältehilfe Notübernachtung grants DE-BE-ZUW:107900/107903/107906)
  — a heuristic false positive that needs a Lead review entry or a G7 exemption for orgs with an HRB/VR register.

## Schema 2 and direct-run safety (2026-11-21)
- Rebased on main 73fe570. All raw SQL uses the schema-2 names (award: foerder_schluessel, empfaenger, betrag,
  ort_land …; org: strasse, ort …). `_ensure_org` passes `strasse` / `ort` directly.
- `python3 -m ingest.domains.funding_traeger` with no mode prints usage and exits 2; unknown flags exit 2.
  No direct-run path opens data/atlas.db. `--selftest --db` refuses atlas.db*, anything under data/ and the Lead worktree.
- Protected-shelter check (full TED run into scratch /tmp/fund_verify2.db, 2026-11-21): 16 notices tagged
  `protected_shelter`; 0 with buyer city/NUTS; 0 winner rows with city/NUTS; their 10 award rows have
  `dienststelle`, `ort_gemeinde`, `ort_kreis` all NULL (Land only: BB, BY, NI); 0 linked orgs with strasse/plz/lat/lon.
  One linked org (Hero Services gGmbH) has `ort=Berlin`: its registered seat, taken from an unprotected notice
  (513374-2026), not a shelter location. verify.py on that DB: ALL GATES PASS (G1–G10).

## Schema 3 (main 70e3e9d)
- No metric rows are written by funding_traeger or funding_officers, so the AGS triggers (INGEST_CONTRACT §8) never fire; org.land / award.ort_land keep letter codes ("BE").
- Berlin Zuwendungen are placed at Kreis 11000 / Gemeinde 11000000 (Stadtstaat, unambiguous): award.ort_kreis/ort_gemeinde and org kreis_ags. Rows flagged no_address (protected shelters) stay Land-only (ort_kreis/ort_gemeinde NULL). TED rows are not placed below Land.
