# Non-Berlin grants: source survey (funding_traeger worker, 2026-11-23)

Scope: public grant data (Zuwendungen, Transparenz/Open Data, ESF Plus beneficiary lists) outside Berlin that could
give **organisation recipient + amount + citable document** for homelessness work. Hamburg is done (`funding_hamburg`,
b59c80c). Every host below was checked through the gated fetch (`funding_officers.robots_gate`: robots.txt first,
fail-closed on anything but 200/404/410), project User-Agent, ≥ 1 s between requests, Crawl-delay honoured.
"Robots" = result for the exact path we would need. Times CET.

Legend: **GO** = build now · **LATER** = usable, but low yield or a human terms answer is needed first · **NO-GO** = blocked or useless.

| # | Candidate | URL (entry point) | Format | Licence / terms | Robots (our UA) | Recipient + amount? | Homelessness relevance | Decision |
|---|---|---|---|---|---|---|---|---|
| 1 | Bremen – Zuwendungen Quartalsberichte (ZEBRA, § 11 BremIFG) | https://www.transparenz.bremen.de/daten/zuwendungen-quartalsberichte-2026-326296 | XLSX + CSV per quarter, 2024–2026 | CC BY 3.0 (dataset page, as reported by the search index; not fetched by us) | **robots.txt answers HTTP 403** to our UA and to a plain curl UA, so fail-closed: nothing fetched. Same for www.finanzen.bremen.de (annual Zuwendungsbericht) and esfplus.bremen.de (robots refuses the project-list path) | yes (all Zuwendungen paid in the year) | high (Land-wide, includes social authority) | **NO-GO now, best candidate if unblocked** – needs a human answer (see below) |
| 2 | Federal ESF Plus "Liste der Vorhaben" (includes EhAP Plus with eligible costs) | https://www.esf.de/portal/DE/ESF-Plus-2021-2027/Liste-der-Vorhaben/inhalt.html | HTML search form only | EU Reg. 2021/1060 Art. 49(3) publication; no open licence stated | page allowed (Crawl-delay 10); the list is served only by the form `/SiteGlobals/Forms/Vorhabensuche/…`, and **`/SiteGlobals/` is disallowed** | yes | very high (EhAP Plus Einzelziel 2 = homeless people) | **NO-GO** (robots); ask BMAS/ESF for a file download |
| 3 | EhAP Plus project list (1st + 2nd round), PDF | https://www.esf.de/portal/SharedDocs/PDFs/DE/Programme-2021-2027/BMAS/ehap_projektliste.pdf | PDF | none stated | allowed (Crawl-delay 10) | Träger + place + duration, **no amounts**; also lists phone / e-mail (not taken) | very high | **LATER** (programme membership only, no money) |
| 4 | ESF Plus Länder "Liste der Vorhaben" (Art. 49 standard columns: beneficiary, operation, purpose, dates, total cost, Union contribution) | NI europa-fuer-niedersachsen.niedersachsen.de · BY esf.bayern.de · NRW mags.nrw · TH esf-thueringen.de · RLP esf.rlp.de · BB esf.brandenburg.de · BE berlin.de | XLSX | none stated (EU publication duty) | allowed for NI, BY, NRW, TH, RLP, BE, BB (esf.brandenburg.de; the newer file on mais2red.lvnbb.de is **disallowed**); HH esf-hamburg.de and ST eufonds.sachsen-anhalt.de reset the connection | yes (total cost + EU share) | **almost none**: homelessness keywords in purpose/title hit 0 rows in NI (880), BY (3,050), NRW (31,358), TH (6,196), RLP (5,774), 1 false hit in BB (20,000); 10 rows in Berlin (GEBEWO, Unionhilfswerk, BETA, ARBEIT UND LEBEN … "Lokal-Sozial-Innovativ") | **LATER** (generic reader is cheap, but the yield outside Berlin is ~0; Berlin rows may duplicate Berlin Zuwendungsdatenbank entries) |
| 5 | Mecklenburg-Vorpommern – Zuwendungsverzeichnis (LAGuS, § 12 Abs. 2 WoftG M-V) | http://www.zuwendung-mv.de/zuwendung.pdf | PDF (2,788 lines, 663 grants, year 2020) | statutory publication, no licence stated (facts only) | allowed (no robots rules) | **yes**: recipient, purpose, period, amount | medium (all social work in MV; ~10 homelessness / Wohnungsnotfallhilfe rows; Frauenhaus rows = protected) | **GO** (small, statutory, named recipients) |
| 6 | Mecklenburg-Vorpommern – Transparenzdatenbank (LAGuS, WoftG M-V) | https://www.transparenz-mv.de/site/index | HTML, 355 Träger (24 list pages + per-Träger pages) | statutory publication, no licence stated; officer names only "if already public or with consent" (page text) | allowed (no rules) | Träger register no. + Rechtsform + Kreis + Spitzenverband; per Träger: Entscheidungsträger (name + Funktion), Hauptzuwendungsgeber (funder names, **no amounts**) | high for org identity / officers of MV social Träger | **GO** as the identity + officer companion of #5 (register numbers for linking; officers = "officer coverage from filings") |
| 7 | München – Zuschussnehmerdatei (ZND) 2026, Amt für Wohnen und Migration, Anlage 1a (Sozialausschuss, SV 20-26 / V 18206) | https://risi.muenchen.de/risi/sitzungsvorlage/detail/9344584 → /risi/dokument/v/9424343 | PDF (2,190 lines, layout table) | council document; no licence stated | allowed (`/*jsessionid*` only) | amount yes (product-oriented Ansatz 2025/2026 per project = budgeted, partly contracts "Vu"); **recipient only as abbreviation** ("KMFV", "EvH", "SKF", "IB") with no legend in the document | **very high** (Produkt 40315400 Soziale Einrichtungen für Wohnungslose: EUR 42.2 M Ansatz 2026) | **LATER** – needs a sourced abbreviation → Träger table and a Lead decision that budget Ansätze (not paid grants) may enter `award` |
| 8 | Köln – Offene Daten, Förderungen des Kulturamts | https://www.offenedaten-koeln.de/dataset/foerderungen-durch-das-kulturamt-ab-2019 | CSV | dl-de/zero-2.0 | allowed | yes | none (culture only) | **NO-GO** (off-topic) |
| 9 | Düsseldorf – EU-Fördergelder (> EUR 100,000, 2014–2019) | https://opendata.duesseldorf.de/dataset/eu-f%C3%B6rdergelder-d%C3%BCsseldorf | CSV | open (portal; not verified) | allowed, Crawl-delay 10 | yes | low (EU structural funds, city as beneficiary) | **NO-GO** |
| 10 | Dortmund / Essen – EU-Fördermittelbilanz (Open Data Ruhr) | https://www.opendata.ruhr/dataset/eu-fordermittelbilanz-2007-2013-und-2014-2020 | CSV | open (portal) | not probed | programme totals | none | **NO-GO** |
| 11 | Frankfurt am Main | https://offenedaten.frankfurt.de/ | – | – | portal allowed | no city-wide recipient-level grant list found in the open-data catalogue | – | **NO-GO** |
| 12 | Stuttgart, Hannover | – | – | – | – | no published recipient-level grant list found | – | **NO-GO** |
| 13 | Leipzig – Stadtbezirksbudget | https://opendata.leipzig.de/de/dataset/stadtbezirksbudget | XLSX | open (CKAN) | allowed, Crawl-delay 10, `/api/` disallowed | yes | none (neighbourhood micro-grants) | **NO-GO** |
| 14 | Sachsen / Dresden – FÖMISAX extracts | Landtag answers (e.g. Drs. 8/2461) | PDF per Kleine Anfrage | Landtag print | not probed | ad hoc | low, ad hoc | **NO-GO** |
| 15 | Schleswig-Holstein – Transparenzportal Zuwendungen | https://transparenz.schleswig-holstein.de/dataset?tags=+Zuwendung | PDF | portal | allowed, Crawl-delay 10, `/api/` disallowed | yes (§ 11 IZG-SH: Zuwendungen an juristische Personen) – but only the KI programme is published | none | **NO-GO** |
| 16 | Rheinland-Pfalz – Zuwendungsübersichten nach § 7 LTranspG (e.g. MASTD 2024) | https://open.rlp.de/de/suchergebnisse/dataset/zuwendungsubersicht-mastd-2024 | PDF per Behörde | dl-de/by-2.0 (dataset page) | dataset page allowed; **file host upload.open.rlp.de: robots.txt HTTP 403** (fail-closed); the portal search answered HTTP 418 once (bot block, not retried) | yes | medium (social ministry) | **NO-GO now** – needs a human answer (see below) |
| 17 | Saarland – Transparenzdatenbank (Ministerium der Finanzen) | https://www.saarland.de/mfw/DE/portale/haushaltundfinanzen/transparenzdatenbank/transparenzdatenbank | web DB + Excel export | unknown | **robots.txt HTTP 403** (fail-closed) | yes | medium | **NO-GO now** – human answer |
| 18 | GovData (federal open-data catalogue, mirrors Länder datasets) | https://data.gov.de | – | – | **`Disallow: /`** | – | – | **NO-GO** |
| 19 | Förderkatalog des Bundes | https://foerderportal.bund.de/foekat/ | web DB | – | robots.txt HTTP 403 (earlier check, research/funding_nonberlin_plan.md) | yes | low (research funding) | **NO-GO** |

## Decision for step 2

No candidate is at once machine-readable, openly licensed, recipient + amount **and** about homelessness **and**
reachable under our robots rule: the two that would be (Bremen #1, federal ESF/EhAP #2) are blocked by robots.txt.
Build therefore the best reachable statutory source:

* **Mecklenburg-Vorpommern (#5), domain `funding_mv`** (built, research/funding_mv.md): the LAGuS Zuwendungsverzeichnis
  (named recipients, purpose, period, EUR, statutory under § 12 Abs. 2 WoftG M-V) filtered to homelessness like
  Berlin/Hamburg. Yield is small: 4 awards, 2 recipients, EUR 68,150.37 (2020).
* The Transparenzdatenbank of the same law (#6: register number, legal form, Entscheidungsträger) is the next step
  in the same module. It is not built in this step.

Not built, with reason: ESF Länder lists (#4, ~0 homelessness rows outside Berlin), München (#7, abbreviations +
budget figures), the rest (off-topic or blocked).

## Needs a human (terms / access) answer

1. **Bremen** (#1): robots.txt of www.transparenz.bremen.de returns HTTP 403 to non-browser clients, so our rule
   reads it as "refused". The data are CC BY 3.0 and exactly what we want. Options: ask the Senator für Finanzen
   (Office@Finanzen.Bremen.de) whether automated download of the Quartalsberichte is permitted / to fix robots.txt,
   or a human downloads the files once and we cite the dataset URL.
2. **Federal ESF Plus list incl. EhAP Plus** (#2): only behind `/SiteGlobals/` (disallowed). Ask BMAS / ESF-Info
   for a file export of the "Liste des Bundes" (Art. 49 (3) CPR requires a spreadsheet-like publication).
3. **Rheinland-Pfalz** (#16) and **Saarland** (#17): robots.txt 403 on the file / portal host; same question as Bremen.
4. **München** (#7): may council documents (no licence stated) be used as facts-only sources, may budget Ansätze be
   stored as awards, and is there an official list of the Träger abbreviations?
5. **Mecklenburg-Vorpommern** (#5, #6): no licence stated; we take facts only (names, amounts, published roles) with
   citation, as for TED and the Lobbyregister. Confirm that is acceptable.
