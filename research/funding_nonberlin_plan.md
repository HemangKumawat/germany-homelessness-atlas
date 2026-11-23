# Plan: non-Berlin grants (funding_traeger), research only (2026-11-23)

Status: plan only, no code yet. Every probe ran from deck with the project User-Agent, ≤ 1 req/s.

## 1. Hamburg Transparenzportal: Zuwendungsvorgänge (best next source)
- What: quarterly "Zuwendungsvorgänge <Jahr> Quartal <n>" datasets (XLSX + ZIP), licence **dl-de-by-2.0**
  (open, attribution). A CKAN search for "Zuwendung Wohnungslos" returns 115 datasets.
- Access: robots.txt of suche.transparenz.hamburg.de says `Disallow: /api/` and `Crawl-Delay: 10`.
  **One probe request went to `/api/3/action/package_search` before I had read robots.txt. That was my mistake,
  and the reader must not do it.** The ingest has to get the dataset pages / resource download URLs without
  `/api/` (or use the same datasets mirrored on GovData, whose robots.txt did not answer from deck, so that stays
  fail-closed), honour the 10 s crawl delay, and cache.
- Mapping: Zuwendungsempfänger → org (resolve_org by name + legal form; no register in the file is expected),
  Betrag → award.betrag, Zweck/Haushaltstitel → filter for Wohnungslosen-/Obdachlosenhilfe, Land HH.
  Expect the same quote/locator pattern as the Berlin Zuwendungsdatenbank (sheet, row).

## 2. Förderkatalog des Bundes (foerderportal.bund.de/foekat)
- The search UI answers 200, but **robots.txt answers 403 Forbidden**, so the reader treats it as fail-closed:
  no automated reading. Options: ask the BMBF/Förderportal for an export or terms, or have a human run a few
  manual searches with documented queries. Coverage is mostly federal research/project funding (BMBF/BMWK …),
  so few homelessness Träger are likely. Low priority.

## 3. ESF Plus / EhAP Plus (Bund)
- Art. 49(3) of the CPR (EU 2021/1060) requires a public "Liste der Vorhaben" (operation, beneficiary, amounts,
  location). EhAP Plus ("Eingliederung hilft gegen Ausgrenzung der am stärksten benachteiligten Personen") funds
  homelessness projects directly, so this is the most relevant federal grant list.
- esf.de robots.txt: `Disallow: /SiteGlobals/ /DE/Service/ /EN/Service/`, `Crawl-delay: 10`. The Vorhabenliste
  download has to be at an allowed path; if it sits under /DE/Service/, it must be fetched manually and archived,
  not crawled.
- Licence: to be checked on the list itself (EU publication duty, so facts are public; the reuse terms decide
  between redistribute_fulltext 0 and 1).
- Mapping: Begünstigter → org; EU + national co-financing → award (two amounts, or the total with a note);
  Standort → Land/Kreis (no addresses for protected facilities).
- Länder ESF Plus lists (each Land publishes its own) follow the same Art. 49 duty: a second pass per Land.

## Order
1. Hamburg (open licence, structured, small): about 1 day including tests.
2. EhAP Plus Vorhabenliste (federal, on-topic): about 1 day once the file location and licence are settled.
3. Förderkatalog: only after a licence/terms answer.
