# Germany Homelessness Atlas (Wohnungslosigkeit-Atlas)

*Öffentliche Daten zu Wohnungs- und Obdachlosigkeit in Deutschland, als Karte und durchsuchbares Wiki.*

A public-record atlas of homelessness in Germany. It links official counts, the organisations (Träger) and
public bodies paid to respond, their grants and contracts in EUR, the published officers of those
organisations, the law, institutions, audits and media. Everything is keyed by Land, Kreis and Gemeinde
(AGS), and every number points to the archived public document that contains it.

> **AI agents: start with [`AGENTS.md`](AGENTS.md) and [`llms.txt`](llms.txt).**

## Current state (2026-11-23, branch `lead/core` @ `d5f33ea`)

| | |
|---|---:|
| registered sources (each archived, sha256-pinned) | 2,808 |
| organisations (`org`) | 1,079 |
| published officer / director roles (`org_person`) | 1,198 |
| grants and contracts (`award`) | 1,067 |
| metric rows (counts, costs, population) | 29,791 |
| Destatis 22971 count rows (`zaehlung`) | 2,086 |
| facilities (shelters, psychiatric hospitals, prisons, day centres) | 630 |
| law and ordinance rows | 271 |
| generated site pages | ~17,355 |

Full per-table and per-source numbers: [`data/CATALOG.md`](data/CATALOG.md). Run log and verdicts: [`LEDGER.md`](LEDGER.md).

## Scope

- **Counts:** Destatis GENESIS 22971 (people *housed* because they are homeless, Stichtag 31.01.2022–2026)
  for Bund, 16 Länder and 400 Kreise; the federal Wohnungslosenbericht; Länder and city figures; police
  statistics on homeless victims; population denominators (Destatis 12411, GV-ISys).
- **Money:** Berlin Zuwendungsdatenbank, EU TED procurement awards, Hamburg Zuwendungsbericht, Mecklenburg-
  Vorpommern Zuwendungs- and Transparenzdatenbank, ESF Plus Länder project lists, Bremen and Rheinland-Pfalz
  archives, municipal shelter fee statutes (Gebührensatzungen) for 8 cities.
- **Organisations and people:** Träger identity (register numbers, legal form, USt-IdNr) with entity
  resolution; officers and directors only as published roles (Impressum, Vereins-/Handelsregister,
  Jahresbericht, Lobbyregister, Wohlfahrtsverband Gremien).
- **Law:** SGB XII §§ 67 ff., Ordnungsrecht / Unterbringung, Land and city Aktionspläne, local statutes.
- **Institutions and media:** shelters, psychiatric hospitals (Länder Krankenhauspläne), prisons, Bundestag and
  Landtag papers (DIP, ParlDok), Rechnungshof reports, openly licensed media (Wikimedia Commons).

## What is excluded, and why

- **Protected shelters.** Frauenhäuser, Schutzwohnungen and similar protected places never get an address,
  postcode or map pin. Women-only, youth-only and LGBTQ-only offers are stored at city level only. The schema
  refuses such rows and gate G8 re-checks them.
- **Private individuals.** Only people in a published public or professional role, tied to an organisation and
  a source. No private persons, no affected people from press reports (gate G7).
- **Source documents.** Archived PDFs/HTML (`data/raw/`, ~2.9 GB) are kept locally for verification only and
  are never committed or republished (gate G10). Press and reserved-rights sources contribute facts, metadata
  and short quotes only.
- **Built artefacts.** The SQLite database (`data/atlas.db`, ~66 MB) and the static site (`site/`, ~80 MB,
  ~17k pages) are generated and not committed. See *Build*.
- **Framing.** Destatis 22971 counts people *housed* by municipalities (*untergebracht*); it is never presented
  as total homelessness. Crime data is area-level context only.

## Build and verify

Requirements: Python 3.11+, `sqlite3` with FTS5, `pdftotext` (poppler-utils). No third-party Python packages.

```bash
python3 scripts/init_db.py                  # create data/atlas.db from ingest/schema.sql
python3 -m ingest.run --list                # list domain modules
python3 -m ingest.run counts_law            # one domain per run (single writer, flock); re-fetches sources politely
python3 -m ingest.run lead_org_resolution   # org entity resolution after funding runs
python3 scripts/verify.py                   # gates G1–G11 against data/atlas.db + data/raw/
python3 scripts/verify.py --selftest        # plants bad rows in a copy and expects each gate to fail
python3 -m unittest discover -s tests       # offline unit tests (no network, no data/atlas.db needed)
python3 scripts/build_site.py               # static wiki + Leaflet map into site/
python3 scripts/catalog.py                  # data/CATALOG.md + data/catalog/sources.csv
python3 -m http.server 8000 -d site         # local preview
```

Some sources need a free API key (e.g. Bundestag DIP); keys are read from the environment or
`~/.config/germany-atlas/env`, never from the repo. Fetches are rate-limited (≤ 1 req/s) and respect robots.txt.

## Verification gates

`scripts/verify.py` must exit 0 before anything is kept.

| gate | checks |
|---|---|
| G1 integrity | SQLite `integrity_check` and `foreign_key_check` |
| G2 provenance | every row has a valid `source_id` |
| G3 licences | every source has a concrete licence (no TODO) and appears in `docs/SOURCES.md` |
| G4 archive | every source has an archived copy whose sha256 matches |
| G5 numbers | every stored number occurs in its cited document (unit- and format-aware) |
| G6 estimates | estimates are flagged `is_est=1` and rendered with † |
| G7 people | person names only with a published role / register context |
| G8 protection | no address, postcode or coordinates on protected shelters |
| G9 spot-check | deterministic sample of rows from every source traced to the exact document line |
| G10 no republication | no archived document or extracted full text in `site/` or git |
| G11 join integrity | one canonical org per hard id, references to canonical orgs only, no NULL regressions |

## Licences

- **Code:** MIT, see [`LICENSE`](LICENSE).
- **Atlas compilation and original text** (docs, research notes, catalog, schema design, site text): CC BY 4.0,
  see [`LICENSE-DATA`](LICENSE-DATA).
- **Upstream data keeps its own licence**, listed per source in [`docs/SOURCES.md`](docs/SOURCES.md) and
  [`data/catalog/sources.csv`](data/catalog/sources.csv): e.g. Destatis and BKG dl-de/by-2-0, Hamburg CC0,
  Bremen CC BY 3.0, Berlin open data CC BY-SA, Wikidata CC0, Commons CC BY-SA, TED © EU with reuse permitted,
  official works (§ 5 UrhG) public domain. See [`NOTICE.md`](NOTICE.md).

## Inspiration and credit

Inspired by **[0xSero/homeless-atlas](https://github.com/0xSero/homeless-atlas)**, the US public-record
homelessness atlas, and its idea of linking counts, money, organisations and laws with every number checked
against an archived document. That repository publishes no licence, so this project is an independent
re-implementation: no code, schema text, data or configuration from it is included. Details in
[`NOTICE.md`](NOTICE.md) and [`BLOCKERS.md`](BLOCKERS.md) §1.

## Repository map

```
ingest/schema.sql            tables, CHECKs, FKs, indexes, FTS5 search, views (German column names)
ingest/common.py             fetch + archive + sha256 + text extraction, upsert, name_norm, register ids, secrets
ingest/run.py                the single writer: flock, WAL, synchronous=FULL, foreign_keys=ON, one domain per run
ingest/domains/<domain>.py   one module per domain: run(conn, cfg) -> {"rows","notes","sources"}
ingest/orglink.py            org entity resolution: hard-id keys, canonical orgs, org_link
scripts/verify.py            the gates G1–G11 (--selftest, --ledger, --spot)
scripts/build_site.py        static wiki + Leaflet map into site/ (atomic swap, shrink guard)
scripts/catalog.py           data/CATALOG.md + data/catalog/sources.csv
scripts/join_gaps.py, audit.py   coverage gaps and plausibility warnings (reports/)
research/<domain>.md         per-domain source notes, verified rows, coverage, caveats
docs/                        ingest contract, sources and licences, review tables, bot roles
tests/                       offline unit tests and fixtures
GOALS/GOAL.md, LEDGER.md, BLOCKERS.md   objective, run ledger, open blockers
```

This atlas was built by a small team of AI coding agents (one Lead as the only database writer, three domain
workers) under human review; see [`docs/BOTS.md`](docs/BOTS.md) and [`docs/INGEST_CONTRACT.md`](docs/INGEST_CONTRACT.md).
