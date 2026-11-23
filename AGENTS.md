# AGENTS.md — map for coding agents

Read this first, then `GOALS/GOAL.md` (the contract) and `docs/INGEST_CONTRACT.md` (how a module joins).

## What this repo is
A Python + SQLite pipeline that fetches German public records on homelessness, archives each document
(sha256), extracts facts into `data/atlas.db`, proves every number against the archived text
(`scripts/verify.py`, gates G1–G11), and renders a static wiki + map (`site/`). No third-party Python packages.

## Layout
| path | what | who edits |
|---|---|---|
| `ingest/schema.sql` | all core tables, CHECK constraints, FTS5 index, views. German column names (`betrag`, `empfaenger`, `anschrift`, `haushaltsjahr`) | Lead only |
| `ingest/common.py` | `fetch` / `fetch_json` (polite, cached under `data/raw/`), `archive` + `source_id_for` (register a source with sha256), `document_text` (PDF/HTML/XLSX → text), `upsert`, `name_norm`, `parse_register`, `ensure_org` / `resolve_org`, `secret()` | Lead only |
| `ingest/run.py` | the single DB writer: `python3 -m ingest.run <domain>`; flock, one transaction per run, rollback on error | Lead only |
| `ingest/domains/<domain>.py` | one module per data domain (`counts_law`, `funding_traeger`, `funding_mv`, `funding_hamburg`, `funding_esf`, `funding_manual`, `funding_officers`, `institutions_media*`, `geo_bkg`, `geo_bevoelkerung`, …) | domain owner |
| `ingest/domains/<domain>.json` | optional per-domain config | domain owner |
| `ingest/orglink.py` | org entity resolution: hard ids (register no., USt-IdNr, CompanyID), canonical orgs, `org_link` aliases | Lead |
| `scripts/verify.py` | gates G1–G11; `--selftest`, `--ledger`, `--spot` | Lead |
| `scripts/build_site.py`, `site_src/` | static site generator and its JS/CSS (Leaflet vendored) | Lead |
| `scripts/catalog.py` | regenerates `data/CATALOG.md` and `data/catalog/sources.csv` | anyone |
| `docs/SOURCES.md` | every source URL (or URL pattern) with licence; append-only; G3 checks it | append a row |
| `docs/*.tsv` | Lead-reviewed exceptions: `est_reviewed`, `link_reviews`, `null_allowlist`, `org_merges` | Lead |
| `research/<domain>.md` | source notes, caveats, `## Verified` spot checks, `## Coverage` | domain owner |
| `tests/` | offline `unittest` suites with in-memory DBs and small fixtures | anyone |
| `LEDGER.md`, `ledger.jsonl` | one row per ingest run: KEEP / REJECT / PARKED with evidence | Lead |
| `reports/` | generated gap / parity / review reports | generated |
| `queue/`, `scripts/loop.sh`, `systemd/` | worker queue and backup timer used during the build | ops |

Not in git (rebuildable): `data/atlas.db`, `data/raw/` (archived documents), `data/backups/`, `site/`, `logs/`.

## Core schema (see `ingest/schema.sql`)
- `source(id, domain, url, title, publisher, license, license_url, attribution, retrieved_at, sha256, local_path, text_path, redistribute_fulltext)` — every other row has `source_id` → here.
- `org` (Träger, public bodies; register ids, legal form) · `org_link` (alias → canonical) · `org_person` (`funktionstraeger`, published `funktion`, `rollenklasse`, `quote`, `stand`).
- `award` (grant/contract: `zuwendungsgeber`, `empfaenger`, `org_id`, `betrag`, `currency`, `haushaltsjahr`, `quote`, `locator`).
- `metric` (any number by area/period: counts, costs, population) · `zaehlung` (Destatis 22971 cells).
- `facility` (`kind`, `anschrift`, `plz`, `lat`, `lon`, `is_protected`) · `law` · `media` · `doc`.
- `geo_land`, `geo_kreis`, `geo_gemeinde` keyed by AGS; `search_fts` full-text index.
- Most fact rows carry `quote` (verbatim snippet from the archived document) and `locator` (page/line/cell), `is_est` for estimates.

## Adding a source (the usual task)
1. Write `ingest/domains/<domain>.py` exposing `DOMAIN = "<domain>"` and `run(conn, cfg) -> {"rows", "notes", "sources"}`.
   Use `common.fetch` + `common.archive` so the document is archived, hashed and registered as a `source`; never store a number that is not in the document.
2. Make it idempotent (`common.upsert` on a natural key). Test against `:memory:` or `--db /tmp/x.db`, never `data/atlas.db`.
3. Copy the licence string from the live source into `source.license`; append a row to `docs/SOURCES.md`.
4. Add `tests/test_<domain>.py` (offline, fixtures in `tests/`) and `research/<domain>.md`.
5. Run `python3 -m unittest discover -s tests`, then (Lead) `python3 -m ingest.run <domain>` and `python3 scripts/verify.py`.
   A run that fails any gate is rolled back and logged as REJECT.

## Gates (`scripts/verify.py`, all must pass)
G1 integrity · G2 provenance · G3 licences · G4 archive (sha256) · G5 numbers in document · G6 estimates flagged ·
G7 people only as sourced roles · G8 protected shelters without location · G9 deterministic spot-check to the document line ·
G10 no republication of source documents · G11 org join integrity. `--selftest` plants a failure for each.

## Hard rules
- Public data only. Named people only as published roles tied to an org and a source; no private individuals,
  no affected persons named in press reports.
- Frauenhäuser / Schutzwohnungen / protected shelters: never an address, postcode or coordinates. Women-, youth-
  and LGBTQ-only offers: city level only.
- No invented numbers or URLs. Estimates: `is_est=1`, rendered with †.
- Destatis 22971 = people *housed* (untergebracht); never call it total homelessness.
- Respect source terms: ≤ 1 req/s, robots.txt first, no login/paywall scraping. Sources with
  `redistribute_fulltext=0` give facts, metadata and short quotes only.
- No secrets in git: keys come from the environment or `~/.config/germany-atlas/env` (`common.secret`).
- One DB writer at a time (`ingest/run.py` holds a flock; exit 75 if busy).

## Quick commands
```bash
python3 -m unittest discover -s tests        # ~150 offline tests, ~20 s
python3 scripts/verify.py                    # needs data/atlas.db + data/raw/
python3 scripts/verify.py --selftest
python3 scripts/build_site.py && python3 -m http.server 8000 -d site
python3 scripts/catalog.py
```
