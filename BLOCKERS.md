# Blockers

Open items that stop a domain or block publishing. Newest decisions at the top of each section.

## 1. Upstream licence → resolved by rewrite (2026-11-21); owner approved publishing 2026-11-23 (code MIT, content CC BY 4.0)

0xSero/homeless-atlas publishes no licence, so nothing from it may be reused. **Decision (Lead, 2026-11-21):**
`ingest/schema.sql` was rewritten as schema 2. It has German column names, its own CHECK constraints and
German comments and index names. The empty US-only columns are dropped (`pit.veterans/hiv/chronic/smi/sud/dv/families/youth`,
`award.amount_obligated/psc/subtier`, `facility.capacity_est/owner`), and `pit` is renamed to `zaehlung`. The
DB was migrated losslessly by `ingest/migrate.py`, with a backup at `data/backups/pre-schema2-migration.db`.
`NOTICE.md` is rewritten as our own text, crediting the upstream project as inspiration only.

**Line-similarity re-check, 2026-11-21, `lead/core`:** every tracked file (54) was compared against
`~/projects/_ref/homeless-atlas` @33711f8. We counted stripped lines over 12 characters that are identical to a
line in the same-path upstream file ("same-file") or in any upstream file ("any-file").
Result: 54 files checked; 41 contain at least one identical line; 477 identical lines in total, 83 of them in the same-path upstream file. Before the rewrite: 565 identical lines in 39 of 52 files, with schema.sql at 98 same-file / 100 any-file.

What the remaining identical lines are:
- **schema.sql (13):** the 10 contract table names (`CREATE TABLE IF NOT EXISTS source|org|org_person|award|metric|facility|law|media|doc|ingest_run (`)
  and 3 × `id INTEGER PRIMARY KEY,`. Kept on purpose. They are interface names, not expression.
- **Python and shell (common.py 12 same-file, verify 9, build_site 10, audit 5, ledger 3, loop.sh 3, run 2, backup 1):**
  shebangs, `from __future__ import annotations`, `from pathlib import Path`, `ROOT = Path(__file__).resolve().parent.parent`,
  `DB = ROOT / "data" / "atlas.db"`, `if __name__ == "__main__":`, `sys.exit(main())`, `except ValueError:`, and one-line
  signatures (`def now() -> str:`, `def to_int(v):`, `def name_norm(s: str | None) -> str:`). The three
  distinctive common.py lines (fetch-log JSON line, `save_raw` body, upsert row filter) were rewritten.
- **Domain modules, tests, research notes (any-file only, 0 same-file):** `conn.commit()`, `).fetchone()[0]`,
  `except sqlite3.OperationalError:`, calls to our own helpers (`upsert(conn, "metric",`), public API URLs
  (`https://commons.wikimedia.org/w/api.php`), and Markdown table rules `|---|---|`.
- **.gitignore (8), GOALS/GOAL.md (6), docs/SOURCES.md (5), LEDGER.md (2), BLOCKERS.md (2):** file paths
  (`data/atlas.db`, `data/backups/`), goal-template headings (`**Constraints**`), and table header and rule rows.
- site_src: `function render() {` and `*{box-sizing:border-box}`.

No file contains copied logic, comments or prose. **Status: closed from the code side.** Publishing to GitHub
still needs Hemang's explicit go-ahead and a licence choice (NOTICE.md: all rights reserved until then).

| file | lines > 12 chars | same-file | any-file |
|---|---|---|---|
| ingest/domains/institutions_media.py | 1987 | 0 | 75 |
| ingest/domains/institutions_media_shelters.py | 618 | 0 | 31 |
| ingest/domains/counts_law.py | 1329 | 0 | 28 |
| ingest/domains/funding_traeger.py | 883 | 0 | 26 |
| ingest/domains/institutions_media_rechnungshof.py | 917 | 0 | 26 |
| scripts/verify.py | 595 | 9 | 26 |
| research/counts_law.md | 644 | 0 | 25 |
| ingest/common.py | 353 | 12 | 21 |
| ingest/domains/institutions_media_orgs.py | 391 | 0 | 21 |
| scripts/build_site.py | 333 | 10 | 19 |
| tests/test_institutions_media.py | 1136 | 0 | 18 |
| ingest/domains/institutions_media_drogentote.py | 350 | 0 | 14 |
| ingest/run.py | 163 | 2 | 14 |
| ingest/schema.sql | 338 | 13 | 13 |
| ingest/domains/geo_bkg.py | 159 | 0 | 12 |
| scripts/audit.py | 44 | 5 | 10 |
| ingest/domains/institutions_media_pks.py | 297 | 0 | 9 |
| tests/fixture_institutions_media.json | 186 | 0 | 9 |
| .gitignore | 13 | 8 | 8 |
| ingest/domains/institutions_media_investigations.py | 238 | 0 | 8 |
| ingest/domains/institutions_media_jva_psych.py | 253 | 0 | 7 |
| GOALS/GOAL.md | 65 | 6 | 6 |
| tests/test_verify_g7.py | 29 | 0 | 6 |
| docs/SOURCES.md | 100 | 5 | 5 |
| ingest/migrate.py | 118 | 0 | 5 |
| research/funding_traeger.md | 200 | 0 | 4 |
| scripts/init_db.py | 7 | 0 | 4 |
| scripts/ledger.py | 13 | 3 | 4 |
| scripts/loop.sh | 74 | 3 | 3 |
| tests/test_funding_traeger.py | 20 | 0 | 3 |
| BLOCKERS.md | 105 | 2 | 2 |
| LEDGER.md | 16 | 2 | 2 |
| reports/parity_vs_us.md | 48 | 0 | 2 |
| scripts/backup_db.sh | 37 | 1 | 2 |
| tests/test_site_render.py | 39 | 0 | 2 |
| tests/test_verify_scaled.py | 18 | 0 | 2 |
| docs/BOTS.md | 45 | 0 | 1 |
| docs/INGEST_CONTRACT.md | 104 | 0 | 1 |
| site_src/app.js | 62 | 1 | 1 |
| site_src/atlas.css | 44 | 1 | 1 |
| tests/dryrun_institutions_media.py | 4 | 0 | 1 |

Tool: `/tmp/simcheck.py` on deck (`python3 /tmp/simcheck.py . [-l]`).

## 2. Destatis GENESIS GAST API refuses data (counts_law)

The documented GENESIS-Online REST API with the GAST guest login answers Code 15 (no data for guest).
`counts_law` reads the anonymous web-table JSON (`genesis.destatis.de/genesis/api/rest/tables/<code>/data`),
which is undocumented and may change; the module now fails loudly on shape drift (`GenesisShapeError`).
Fix: a free GENESIS account (Hemang to decide), credentials in `~/.config/germany-atlas/env`, never in git.

## 3. Bremen Polizeigesetz fetch failed (counts_law part 4)

`hb_polg`: https://www.transparenz.bremen.de/sixcms/detail.php?gsid=bremen203... raised on fetch during run #2;
the other 6 Land general clauses are in. Retry with the next counts_law run.
→ Resolved on `worker/counts_law`: the Lead archived the file by hand (`data/raw/counts_law/law_hb_polg.pdf`); the
module reads it without fetching.

## 4. Kreis gaps between BKG VG2500 (2026) and Destatis 22971

BKG lists 401 Kreise; 22971 has 400. No 22971 rows for 09475 (Landkreis Hof) and 16062 (Nordhausen);
22971 still reports 16056 (Eisenach, bis 30.06.2021), kept as a geometry-less Kreis row from counts_law.
Asked of Counts & Law: confirm the code mapping in the cube.
→ Resolved on `worker/counts_law` (1ce53cd, approved): 16056 folded into 16063 for 2022; 09475/16062 are current
Kreise published as "–" (stored as 0); 06415 Hanau has rows only from 2026. Kreise per Stichtag: 400 (2022–25), 401 (2026).

## 6. Land general clauses without an archivable official text (counts_law, manual archive by the Lead)

The consolidated texts are only on juris portals, which carry a TDM reservation. No free official gazette PDF was
found. Please archive the gazette pages (title page of the issue + the norm) under the file name given. The module
can then add each row with as-of "original promulgated text".

| Land | norm (general clause) | official gazette citation | file name to use |
|---|---|---|---|
| HH | § 3 SOG | Gesetz zum Schutz der öffentlichen Sicherheit und Ordnung vom 14.03.1966, HmbGVBl. 1966 S. 77 (citation from secondary sources; check against the gazette) | `data/raw/counts_law/law_hh_sog.pdf` |
| RP | § 9 POG | Polizei- und Ordnungsbehördengesetz i. d. F. vom 10.11.1993, GVBl. 1993 S. 595 (secondary sources; check) | `data/raw/counts_law/law_rp_pog.pdf` |
| SL | § 8 SPolG | Saarländisches Polizeigesetz i. d. F. der Bekanntmachung vom 26.03.2001, Amtsbl. 2001 S. 1074 | `data/raw/counts_law/law_sl_spolg.pdf` |
| ST | § 13 SOG LSA | SOG LSA i. d. F. der Bekanntmachung vom 20.05.2014, GVBl. LSA 2014 S. 182, ber. S. 380 | `data/raw/counts_law/law_st_sog.pdf` |
| TH | § 5 OBG | Thüringer Ordnungsbehördengesetz vom 18.06.1993, GVBl. 1993 S. 323 | `data/raw/counts_law/law_th_obg.pdf` |

SH was resolved with a qpdf excerpt of the official 1992 volume (GVOBl. Schl.-H. 1992 S. 243); see research/counts_law.md.

## 5. Operational

- The main checkout `~/projects/germany-atlas` is checked out on `worker/funding_traeger` with local edits
  (the Funding worker works there). The Lead works in the worktree `~/projects/germany-atlas-lead`
  (`lead/core`); the canonical DB is `germany-atlas-lead/data/atlas.db` and the backup timer points there.
  Workers should move to their own worktrees so `main` stays clean.
