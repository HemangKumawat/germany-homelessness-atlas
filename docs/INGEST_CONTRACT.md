# Ingest contract — how a domain module joins germany-atlas

This is the hand-off contract between the domain workers (Funding & Träger, Counts & Law,
Institutions & Media) and the Lead, who is the single database writer. Read it together with
`ingest/schema.sql` and `ingest/common.py`.

## 1. What a worker delivers

On branch `worker/<domain>`:

| file | purpose |
|---|---|
| `ingest/domains/<domain>.py` | the module (one per domain; `<domain>` is snake_case and matches `DOMAIN`) |
| `research/<domain>.md` | what the source is, what lands where, caveats, `## Verified` (5 live spot checks), `## Coverage` |
| one appended row in `docs/SOURCES.md` | every URL the module registers, or a URL pattern with `<placeholder>` segments |
| optional `tests/test_<domain>.py` + fixtures | offline tests on an in-memory DB built from `ingest/schema.sql` |

Workers never open `data/atlas.db`, never edit `scripts/`, `site/`, `ingest/schema.sql`, `ingest/common.py`
or another domain's files. They test against a scratch DB (`--db /tmp/<domain>.db` or `:memory:`).
Raw downloads made while testing stay out of git. The Lead copies them into `data/raw/<domain>/` at merge time
or lets the real run re-fetch them.

## 2. Interface

```python
DOMAIN = "counts_law"
def run(conn, cfg) -> dict:
    ...
    return {"rows": int, "notes": str, "sources": [(url, licence), ...]}
```

- `conn` is a `sqlite3.Connection` (`row_factory = sqlite3.Row`, `foreign_keys=ON`). The runner has
  already opened a transaction. `conn.commit()` inside a module is a no-op until the module returns,
  so a failing run rolls back completely. `conn.executescript()` works for `CREATE TABLE IF NOT EXISTS`
  of domain-private tables.
- `cfg` is a dict: `ingest/domains/<domain>.json` if present, plus CLI extras (`--refresh` sets
  `refresh=True, force=True`).
- The module must be **idempotent**: a second run changes nothing. Use `common.upsert` on a natural key.

The Lead runs it, alone, under the lock:

```bash
python3 -m ingest.run <domain>          # exits 75 if another writer holds data/atlas.lock
python3 scripts/verify.py --ledger      # gate; verdict appended to LEDGER.md
```

**Only the runner writes `data/atlas.db`. A domain module run directly never opens it.**

- `python3 -m ingest.domains.<x>` and `python3 ingest/domains/<x>.py` are for offline checks only
  (`--selftest`, `--dry-run`, `--shape-test`, `--test`, or `--db <scratch copy>`). Writes go through
  `python3 -m ingest.run <domain>`, under the lock.
- Every module's `__main__` uses `argparse` with `allow_abbrev=False`. An unknown or abbreviated flag
  exits non-zero, and so does running with no flags. A module without its own offline modes ends with
  `common.no_direct_run(DOMAIN)`.
- `run.open_db` refuses (`SystemExit("REFUSED: …")`) when the process was started as a domain module and
  the path is the canonical DB (this checkout's `data/atlas.db`, or any file named `atlas.db`).
  `common.main()` no longer runs anything and returns 2.
- `tests/test_direct_invocation.py` enforces this for every file in `ingest/domains/`. It checks that an
  unknown flag exits 2, that an unknown flag next to a valid mode is still rejected, that abbreviations
  and empty argv are rejected, and that `atlas.db`, its WAL and the lock are byte-for-byte unchanged
  afterwards. A new module must pass it before review.

## 3. Helpers (`ingest/common.py`)

| helper | does |
|---|---|
| `fetch(url, *, method, data, headers, domain, force)` | HTTP with cache in `data/raw/<domain>/<key>.bin` + `.meta.json`, 1 req/s, backoff on 429/5xx |
| `fetch_json`, `fetch_post_json` | the same, parsed |
| `source_id_for(conn, url, domain, title=, publisher=, license=)` | registers the source and links it to the **same** cache file `fetch` wrote (sha256, bytes, local path, extracted text) |
| `archive(conn, url, domain=, filename=, title=, publisher=, license=, …)` | fetch + store under a readable filename + register; for documents you cite by name |
| `upsert(conn, table, row, keys)` | insert or update on the unique key; `None` never overwrites a stored value; returns the row id |
| `name_norm(s)` | German-aware matching key: strips e.V., gGmbH, GmbH, mbH, gUG/UG (haftungsbeschränkt), AG, KG, eG, KdöR, AöR, GbR, "Stiftung des bürgerlichen Rechts" (keeps the word Stiftung), stop words; folds umlauts |
| `parse_register(raw)` | `vr_021507`, `Amtsgericht Charlottenburg HRB 1234 B`, `R004711` → `{scheme, court, number, raw}` for `org_register` |
| `to_eur`, `to_int`, `clean`, `slug`, `now` | parsing helpers; `to_eur` reads German and English number formats |
| `secret(name)` | reads API keys from the environment or `~/.config/germany-atlas/env` (chmod 600). Never print the value |

`source_id_for` and `fetch` share one cache key, so `sha256` is always filled. (The upstream helper hashed
different strings in the two functions, which left `sha256` empty.)

## 4. Data rules (checked by `scripts/verify.py`)

1. **Provenance.** Every row in a core table has `source_id`. The archived document behind it must exist
   and must contain every number you store (German formats are understood). Put the sentence or table cell
   in `quote` and where it is (page, table, paragraph) in `locator` whenever the source is a document, not a
   data cube.
2. **Estimates.** `is_est=1` when the source calls a figure a Schätzung, geschätzt, Hochrechnung or
   hochgerechnet (also modelled or proxy figures). `is_rounded=1` when the publisher rounded ("rund").
3. **Geography.** AGS: `DE`, Land 2 digits, Kreis 5, Gemeinde 8. Never invent one. Create geography rows only
   with `INSERT OR IGNORE`, and never change rows another domain created.
4. **Money.** `currency` defaults to `EUR`. Store amounts as published. Convert only when the source itself
   publishes the euro figure.
5. **Organisations and people.** `org.name_norm = common.name_norm(name)`, unique per `land`. Register IDs go
   in `org_register` (structured) and the raw string in `org.register_id` / `award.empfaenger_register`.
   Named officers, directors and board members from published filings (Impressum, Handelsregister,
   Jahresbericht, Lobbyregister, Drucksachen) go in `org_person` with `org_id`, the published `funktion` (e.g. Vorstand, Geschäftsführung) and
   `source_id`. Never record private individuals who are not in a public role.
6. **Protected shelters.** Frauenhäuser, Schutzwohnungen and similar: `facility.kind` in
   (`frauenhaus`, `schutzwohnung`, `protected_shelter`) forces `is_protected=1`. The schema then refuses
   `anschrift`, `plz`, `lat` and `lon`. An `org` that *is* a shelter gets `is_protected=1` and no address.
7. **Never set `source_id` on rows you did not create.**
8. **Counts.** `zaehlung.untergebracht` is the Destatis *untergebracht* figure (WoBerichtsG). `zaehlung.insgesamt`
   stays NULL unless the source itself publishes a total of all forms of homelessness.
9. **Politeness.** 1 request/second, honour robots.txt. On a 403 or a missing key, stop that source and
   record it in `BLOCKERS.md`.

## 5. Tables

Core: `source`, `geo_country`, `geo_land`, `geo_kreis`, `geo_gemeinde`, `org`, `org_register`,
`org_person`, `award`, `zaehlung`, `metric`, `facility`, `law`, `media`, `doc`. `ingest/schema.sql` is the
reference for every column (schema version 6, `PRAGMA user_version`). Domain-private tables are
named `<domain>_*`. Convenience views: `places`, `sources`, `ingest_runs`.

## 6. Lead review checklist

1. Read the diff. Only the delivered files changed.
2. Run the offline tests and `--selftest` against a scratch DB.
3. Copy or re-fetch the raw archive. `python3 -m ingest.run <domain>`.
4. `python3 scripts/verify.py --ledger` and `python3 scripts/audit.py`. Spot-check 5 rows against the archived files.
5. `python3 scripts/ledger.py <domain> KEEP|REJECT <rows> <evidence> <note>`. Rebuild the site.

## 7. Migration note: schema 2 (2026-11-21), please read before your next delivery

The Lead migrated `data/atlas.db` to schema 2. The schema now uses our own German column names. The empty
US-only columns are gone. Data is unchanged: every row kept its rowid, and a backup of the old DB exists. What
this means for workers:

- **`upsert()` still accepts the old names** for one transition period. `common.upsert(conn, "pit", {...})` and
  old dict keys are translated (`ingest.migrate.translate`). A value in a **dropped** column raises
  `ValueError`, so nothing is silently lost. Please move to the new names anyway.
- **Raw SQL is not translated.** Every `SELECT`, `UPDATE`, `DELETE` or `INSERT` string in your module and
  your tests must use the new names. Selecting an old name fails with `no such column`.
- Rebase on `lead/core` (≥ the schema 2 commit) and run your offline tests against `ingest/schema.sql`.

Renamed table: `pit` → **`zaehlung`**.

| table | old → new |
|---|---|
| geo_land | pop → einwohner, land_sqkm → flaeche_km2 |
| geo_kreis, geo_gemeinde | pop → einwohner |
| org | status → registerstatus, founded → gruendungsjahr, city → ort, address1 → strasse, website → webseite, phone → telefon, fiscal_year → geschaeftsjahr, revenue → ertraege_eur, expenses → aufwendungen_eur, assets → bilanzsumme_eur, employees → beschaeftigte, updated_at → aktualisiert_am |
| org_person | org_name → org_bezeichnung, person → funktionstraeger, person_norm → funktionstraeger_norm, title → funktion, role_class → rollenklasse, year → jahr, valid_from → gueltig_ab, valid_to → gueltig_bis, comp → verguetung_eur |
| award | award_key → foerder_schluessel, award_id → foerder_id, award_type → foerderart, agency → zuwendungsgeber, office → dienststelle, program → programm, programme_code → programm_code, description → zweck, recipient_name → empfaenger, recipient_norm → empfaenger_norm, recipient_id → empfaenger_id, recipient_register → empfaenger_register, amount_total → betrag, fy → haushaltsjahr, pop_start → laufzeit_von, pop_end → laufzeit_bis, place_land/_kreis/_gemeinde → ort_land/ort_kreis/ort_gemeinde |
| zaehlung (was pit) | year → berichtsjahr, sheltered → untergebracht, unsheltered → ohne_unterkunft, hidden → verdeckt, total → insgesamt, children → minderjaehrige, households → haushalte |
| metric | unit → einheit, note → anmerkung |
| facility | status → betriebsstatus, opened → eroeffnet, closed → geschlossen, beds → betten, operator → traeger, operator_org_id → traeger_org_id, population_note → zielgruppe, city → ort, address → anschrift, budget → haushalt_eur, staff → personal, annual_cost_per_bed → kosten_je_platz_eur |
| media | publisher → herausgeber, author → urheber, published → veroeffentlicht, license → lizenz, thumbnail → vorschaubild, duration → dauer_s, place → ort, summary → zusammenfassung |
| doc | publisher → herausgeber, author → urheber, published → veroeffentlicht, place → ort, summary → zusammenfassung |

Dropped (were empty everywhere): `pit.chronic, smi, sud, veterans, hiv, dv, families, youth`;
`award.amount_obligated, psc, subtier`; `facility.capacity_est, owner`.

Unchanged: `source` (all columns), and the shared generic words `id, name, name_norm, title, url, kind, land,
plz, kreis_ags, lat, lon, year` (metric/law), `value, metric, quote, locator, source_id, is_est, is_rounded,
is_protected, currency`.

New constraints: `lat`/`lon` must lie in Germany's bounding box; `name`/`title` must not be blank; counts in
`zaehlung` must be ≥ 0 and `berichtsjahr` between 1990 and 2100; `metric.year` between 1900 and 2100.

## 8. Schema 3 (2026-11-21): Gemeinden and AGS-only geography

- `geo_gemeinde` gains `flaeche_km2`, `geometry` (GeoJSON, simplified to 250 m) and `geometry_source_id`.
  It is filled by the Lead domain `geo_bevoelkerung` (GV-ISys, Gebietsstand 30.09.2026; BKG VG250 01.01.2026).
- Population by Bund, Land and Kreis is in `metric` (`metric='einwohner'`, `year` = Stichtag 31.12.,
  `einheit='persons'`, Destatis 12411), not in `geo_land/geo_kreis.einwohner`, so that every number keeps its
  own source. The series breaks between 31.12.2021 (Zensus 2011 basis) and 31.12.2022 (Zensus 2022 basis).
- **`metric` geography is AGS only**: `entity_type='land'` needs the 2-digit AGS (`'12'`, not `'BB'`),
  `'kreis'` 5 digits, `'gemeinde'` 8 digits. Triggers `kennzahl_ags_neu` and `kennzahl_ags_aenderung` reject
  anything else. `common.upsert` still maps a Land letter code to the AGS (`common.LAND_AGS`) for metric
  rows, but raw SQL is not mapped. The upgrade moved the 235 existing letter-code rows to AGS. `land` columns
  on `org`, `facility` and so on keep the letter codes.
- Per-capita rates are never stored. The site computes them at build time and labels them "berechnet".


## 9. Schema 4 (2026-11-21): quotes and Stand on `org_person`

- `org_person` gains two nullable columns: `quote` (verbatim fragment of the archived source naming the
  person and, where printed, the function) and `stand` (ISO date the role is stated for: Lobbyregister entry
  version valid-from, or the Impressum retrieval date). `source_id` was already required.
- **No domain side tables for people.** Write quote and Stand into `org_person` itself; `funding_officers_person`
  (worker draft) was folded in before the first ingest and never existed in `data/atlas.db`.
- G7 now requires, for every `org_person` row, that the source's archived text contains every name token
  (initials and degrees ending in "." excepted) and, when `quote` is set, the quote verbatim. The org-name
  heuristic (person-like org names fail unless the org has a court-register number) is unchanged.
- Only people in published professional roles: board, Geschäftsführung, Präsidium, Aufsichtsrat/Kuratorium,
  and persons the Lobbyregister publishes as legal representatives or entrusted persons. Never contact details,
  addresses, birth data or other private-life data of persons.
- Officers attach to an org only when the legal form agrees (e.V. officers never land on a gGmbH of the same
  name; `funding_officers.legal_kind`).
- The upgrade is additive (`ALTER TABLE … ADD COLUMN`) and runs in one transaction from `ingest.run.open_db`.

## 10. Schema 5 (2026-11-23): org entity resolution and G11 join integrity

One legal entity = one **canonical** org. The same Träger arrives from several sources (Berlin
Zuwendungsdatenbank, Lobbyregister, TED, BA Jobcenter list, BAG W, Wikidata …) under different spellings
and Länder; schema 5 records every such join instead of hiding it.

- `org.canonical_org_id` (new, nullable): `NULL` = canonical org; otherwise the row is an **alias row** of
  the org it names. Alias rows are kept exactly as written (they are source-level records), but nothing may
  point at them. Workers **never** set this column; only the Lead merges (`python3 -m ingest.run
  lead_org_resolution`).
- `org_link` (new): one row per source-level org record (`record_kind` org | org_register | award | wikidata
  | …, `record_key`) with the canonical `org_id`, `method` (`register_id` | `lei` | `ust_id` | `wikidata_qid` |
  `name_fuzzy` | `manual` | `origin`), `confidence` 0–1, `id_value` (the normalised hard id the link rests on),
  `source_id`, and `flagged` = 1 for every `name_fuzzy` link. The runner syncs links for every org row,
  org_register row and award after each run (`orglink.sync`), so you only write links for *other* records
  (e.g. a Wikidata item or a TED winner id you resolved).
- Triggers re-point `award.org_id`, `org_person.org_id`, `org_register.org_id` and
  `facility.traeger_org_id` from an alias row to its canonical org on insert and update, so an id returned by an
  old `(name_norm, land)` lookup still lands on the right org. Do not rely on that: resolve first.
- `ingest_colstats` (new): the runner snapshots every table's per-column non-NULL counts before and after
  each run (G11c).

**What a module must do**

1. Before creating an org row, call `common.resolve_org(conn, register=…, ust_id=…, lei=…, qid=…,
   ba_traeger=…)` with every hard id the source prints. If it returns an id, use it; do not insert a new row
   for a new spelling or a different Land. A name lookup comes only after that, and a name match is never a
   reason to reuse an org that holds a *different* register id (that is how three "Fixpunkt gGmbH"
   awards ended up on "Fixpunkt e. V.").
2. Record non-row joins with `common.link_org(conn, record_kind=, record_key=, org_id=, method=, confidence=,
   source_id=, record_name=, id_value=)`. Hard methods need `id_value` from `orglink.register_keys()`,
   `ust_key()`, `lei_key()` or `qid_key()`. A name match is `method="name_fuzzy"` (flagged automatically) with
   an honest confidence; never label a name match as a hard one. `manual` is for the Lead.
3. Court registers go in `org.register_id` / `org_register` only. Other identifiers are not register ids:
   the BA Jobcenter Träger-Nr belongs in a link (`id_value="BA_JC:<nr>"`) or `org_register` scheme `other`,
   QIDs in a `wikidata_qid` link, never in free text.
4. Do not lower a filled column's non-NULL count in a run (no `UPDATE … SET x=NULL`, no delete-and-reinsert
   with fewer fields). If a run must (a documented prune), the Lead adds a narrow line with a reason to
   `docs/null_allowlist.tsv` before the ingest.

**G11 join integrity** (`scripts/verify.py`) fails if (a) a hard id — court + register number (Berlin "B" =
AG Charlottenburg), Berlin ZUWDB id, Lobbyregister number, BA Träger-Nr, USt-IdNr, LEI, QID — is held by more
than one canonical org, or an alias chain exists; (b) an `org_person`, `award`, `org_register`, `facility` or
`org_link` row names a missing or alias org, or an award's recipient *register* id belongs to another canonical
org (a USt-IdNr conflict is only reported: VAT groups share one number); (c) a column's non-NULL count (or a
table's row count) fell during a run without an allowlist line. `--selftest` plants one case of each.

`reports/join_gaps.md` is rewritten after every run and by `python3 -m scripts.join_gaps`: orgs with awards
but no register id, Kreise/Gemeinden with counts but no population, `org_person` rows without a valid org,
duplicate candidates (shared hard id, register number with differing court, name similarity ≥ 0.9 with the
same Land and legal form, same name in different Länder), fuzzy links awaiting review, and the merges made.
Org-level data and published roles only: no person names.

## 11. Lapsed rules (2026-11-23, no schema change): `law.status='lapsed'` + `law.in_force_to`

A rule that is no longer in force but is kept as a historical record is never pruned. It is marked in the columns
`law` already has:

| column | value |
|---|---|
| `status` | `'lapsed'` (current rules keep `'in_force'` / `'enacted'`; nothing else changes) |
| `in_force_to` | the first day it is no longer in force, `YYYY-MM-DD`; `YYYY` only when the day cannot be determined from the archived text |
| `summary` | starts with `[außer Kraft seit DD.MM.YYYY: <basis>; deciding sentence: „…“] ` |

- `<basis>` names the statute section that ends the rule (e.g. `§ 32 Abs. 1 OBG NRW`, `Art. 50 Abs. 2 LStVG`,
  `§ 61 NPOG`, `§ 32 PolG BW`, `§ 79 HSOG`) and/or the document's own end clause, and why an amendment does not
  restart the term.
- The deciding sentence (publication / entry-into-force / end clause) must be one of the row's needles, so it is
  verified verbatim in the archived text.
- verify G9 fails a `lapsed` row without a valid `in_force_to` or without the summary prefix citing § / Art.
- The site shows „außer Kraft seit …“ on the law page and in the list, and counts only non-lapsed rows as current
  rules (home page and any city/Land summary: `WHERE status <> 'lapsed'`). Research coverage tables must count a
  lapsed row as „lapsed“, not „covered“.

counts_law sets this from the module: `_mu(..., lapsed_on="YYYY-MM-DD" | "YYYY", lapsed_basis="… § …",
lapsed_needle="<one of needles>")`; `_mu` refuses a basis without § / Art. or a needle that is not in `needles`.
Other domains writing `law` rows use the same three columns and prefix.

## 12. Schema 6 (2026-11-23): legal form is part of the org key

`org` uniqueness is now `(name_norm, legal_form_norm, land)`, enforced by the expression index
`org_eindeutig ON org(name_norm, coalesce(legal_form_norm, ''), land)` (the old inline `UNIQUE (name_norm, land)`
is gone). An e.V. and a gGmbH with the same name in the same Land are two rows, without any suffix or tag in
`name_norm`. `name_norm` stays the plain standard form from `orglink.norm_name`; tagging it (the old
`KIND_TAG` / `… EV` hacks) is no longer allowed.

| `legal_form_norm` | meaning |
|---|---|
| `ev` | eingetragener Verein (e.V., e. V., eV, Ev. at the end) |
| `ggmbh` / `gmbh` | gemeinnützige GmbH / GmbH (UG and GmbH & Co. KG are `other`) |
| `ag` | AG |
| `stiftung` | Stiftung (any form) |
| `koer` / `kdoer` | Körperschaft öffentlichen Rechts (KöR / KdöR spelling) |
| `eg` | eingetragene Genossenschaft |
| `gbr` | GbR |
| `other` | another form named in the name (UG, KG, GmbH & Co. KG, OHG, PartG, e.K., …) |
| `NULL` | the source gives no legal form |

Set it with `orglink.legal_form_norm(name, legal_form=None)`; never by hand. Families `{gmbh, ggmbh}` and
`{koer, kdoer}` are treated as the same entity when matching (`orglink.same_form_family`), so a later
„X GmbH“ notice joins an existing „X gGmbH“ row instead of creating a duplicate.

**Resolution rules** (`common.find_org` / `common.ensure_org`, used by every domain):

1. Hard ids first (`common.resolve_org`: register, USt-IdNr., LEI, QID, BA-Träger) as in §10.
2. Same `name_norm` + Land + same form → that row (`how='exact'`); same family → that row (`'family'`).
3. Form `NULL` (either side): matches an existing row **only when exactly one** namesake candidate exists
   (`'single'`, written as a flagged `name_fuzzy` link). With two or more candidates (`'ambiguous'`) a new row
   with `legal_form_norm = NULL` is created and `common.flag_new_org` writes a flagged `org_name` link
   (`confidence 0.5`, note „legal form unknown; … not matched: new row (INGEST_CONTRACT §12)“) so the lead
   reviews it in `reports/join_gaps.md`. If that NULL row already exists it is reused (`'ambiguous_existing'`).
4. A court/register-number suffix in `name_norm` is only allowed for two orgs with the same name, **same form**
   and different register entries (funding_traeger's existing case); everything else is separated by the form.

`common.upsert(conn, "org", {...}, keys=["name_norm", "land"])` keeps working: it fills `legal_form_norm`,
resolves through `find_org` and updates the matched row by id; otherwise it inserts on the conflict target
`(name_norm, coalesce(legal_form_norm, ''), land)`. **Use the id it returns**; do not re-select an org by
`(name_norm, land)`, which is no longer unique. Raw `INSERT INTO org` in modules or test fixtures must set
`legal_form_norm` (or go through `ensure_org`) and use `RETURNING org_id`.

Migration: `run.open_db` rebuilds `org` once (`migrate.upgrade_6`, before `schema.sql` runs) with every row and
`org_id` kept, backfills `legal_form_norm` from the name, restores any tagged `name_norm` to the standard form,
recreates all indexes and triggers on `org`, checks foreign keys and sets `user_version = 6`. On rebase, drop
your scratch DB or let `open_db` migrate it; no data change is needed in module output.
