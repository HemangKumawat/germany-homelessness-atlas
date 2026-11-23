# NOTICE

## Authorship

Germany Atlas (Wohnungslosigkeits-Atlas Deutschland) is written for this project. The ingest helpers, the
domain modules, the SQLite schema (schema 2, German column names), the migration, the verification gates
G1–G11, the audit, the site builder and the site assets are our own implementation.

## Inspiration

The idea of a public-record atlas that links counts, money, organisations, institutions, laws and sources,
and that checks every number against an archived document, comes from 0xSero's US project
<https://github.com/0xSero/homeless-atlas>. We acknowledge that project as the inspiration. No code, schema
text, data, cached source files or deployment configuration from it is part of this repository. The
upstream repository publishes no licence (checked 2026-11-20), so we do not reuse its material.

A line-by-line comparison of every tracked file against that repository (reference commit
`33711f8dfd6f417ff209221744867984afe584ce`) is recorded in `BLOCKERS.md` §1. The only identical lines are
generic language idioms (shebangs, `from pathlib import Path`, `if __name__ == "__main__":`), common file
paths in `.gitignore`, Markdown table rules and headings, and the names of ten contract tables (`source`,
`org`, `org_person`, `award`, `metric`, `facility`, `law`, `media`, `doc`, `ingest_run`). These table names
are an interface, not creative expression.

## Data

All figures come from German and European public sources. Each source's licence or terms of use are listed
in `docs/SOURCES.md` and stored per source in the database. Archived source documents in `data/raw/` are kept
for verification only. They are not part of the repository or the site, and they are not republished.

## Licence of this repository

- Code: MIT (`LICENSE`).
- Atlas compilation, catalog, documentation and research notes: CC BY 4.0 (`LICENSE-DATA`).
- Upstream data keeps its own licence, recorded per source in `docs/SOURCES.md` and
  `data/catalog/sources.csv` (for example Destatis/BKG dl-de/by-2-0, Hamburg Transparenzportal CC0,
  Bremen Transparenzportal CC BY 3.0, Berlin Zuwendungsdatenbank CC BY-SA, Wikidata CC0, EU TED reuse notice,
  official works under § 5 UrhG). Share-alike and reserved-rights terms take precedence for the data they cover.

## History

The public repository starts from a single squashed snapshot. The private development history began from a
skeleton adapted from the upstream project before the schema-2 rewrite (see `BLOCKERS.md` §1), so it is not
published.
