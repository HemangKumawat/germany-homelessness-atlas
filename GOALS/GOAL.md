# GOAL — Germany Atlas

**Objective.** Build `germany-atlas`: the most complete public-record atlas of
homelessness (*Wohnungs- und Obdachlosigkeit*) in Germany — every Träger /
provider and every public contract or grant, Destatis counts (GENESIS table
22971) and the federal *Wohnungslosenbericht*, Länder and city counts, the
laws (SGB XII §67, Ordnungsrechtliche Unterbringung, Aktionspläne), institutions
(psychiatric hospitals, prisons, shelters), audits, Bundestag papers, and the
media — organised as a searchable, map-driven wiki by Land / Kreis / Gemeinde
(AGS codes), with money in EUR.

**Verified by**
1. `python3 scripts/verify.py` exits 0 and prints per-domain row counts,
   coverage (Länder / Kreise / Gemeinden covered), and page counts.
2. `sqlite3 data/atlas.db` counts meet the gates in `scripts/verify.py`; every
   row carries a `source_id`.
3. Every entity in the DB has a reachable HTML page; the search index contains
   every entity; every page has a working search box + breadcrumb; pages render
   at 390px and 1440px widths.
4. Zero fabricated values: every number traces to a `source` row with URL +
   retrieval date, and the cited document actually contains that number.
   Estimated or proxy numbers are labelled `is_est=1` in the DB and rendered
   with a dagger + footnote.

**Constraints**
- Public data only. Collect all publicly available data, matching the US
  atlas's scope. Named officers and directors from published filings
  (Impressum, Handelsregister, Jahresbericht, Bundestagsdrucksache, and
  equivalent) are in scope.
- Two exclusions only:
  1. Private individuals who are not in a public or published professional role.
  2. Addresses and coordinates of Frauenhäuser and other protected shelters.
     The organisation may be listed; the street address and map pin must not.
- Never invent a number or a URL. If a source is unavailable, record it in
  `BLOCKERS.md` and continue.
- Respect source terms. Fetch at polite rates (<= 1 req/s, exponential backoff,
  cache every response under `data/raw/`).
- Licences recorded per source in `docs/SOURCES.md`; attribution rendered on
  the site.
- Microcommit: one domain or one site change per commit.
- Parallel workers write only inside their own namespace
  (`ingest/domains/<domain>.py`, `research/<domain>.md`, and, after a Lead
  merge, `data/raw/<domain>/`). They never write `data/atlas.db`, never edit
  `site/`, and never edit another domain's files. Only the Lead (see
  `docs/BOTS.md`) is the database writer and runs verify / build.

**Boundaries / scope stops**
- Do not identify a private person who does not appear in a public role or a
  published filing.
- No framing of homeless people as a criminal class: crime data is area-level
  context with explicit caveats.
- Not a legal-advice product; law pages are summaries with citations.
- No public deploy and no GitHub publish until this dataset is at least as
  detailed as the US atlas, every verify gate passes, and the owner approves.
  After Germany clears that bar: Europe (EU, UK, Switzerland, Norway), then
  India.

**Iteration policy**
Between cycles: read `ledger.jsonl` tail + the queue, pick the highest-value
unfinished item whose sources are reachable, let workers deliver modules on
`worker/<domain>` branches, Lead merges and is the only process to run
ingestors against `data/atlas.db`, spot-check 5 random rows against the live
source, commit, log a ledger row (KEEP / REJECT / PARKED), rebuild the site,
then queue the next item. If a domain is exhausted, mark it DONE with evidence
and move on. The loop stops only when the queue has no OPEN items and
`verify.py` passes — or on an unrecoverable blocker.

**Blocked stop condition**
Stop and report (do not idle, do not fake progress) if: (a) a required API key
is missing and no keyless equivalent exists (record exact key + signup URL in
`BLOCKERS.md`), (b) rate limits or site policy make a domain unreachable after
3 retries across 2 cycles, (c) disk < 20 GB. Then write what unblocks it and
continue every other reachable domain.
