# funding_officers — named Vorstand, Geschäftsführung and board members of Träger

Module: `ingest/domains/funding_officers.py` (`DOMAIN = "funding_officers"`, target table `org_person`).
Readers, selected with `cfg["sources"]` (default: both, in this order):

| reader | what it writes |
|---|---|
| `lobbyregister` | `org_person` for every published legal representative (with the published function) and every person entrusted with interest representation (`rollenklasse='lobby_kontakt'`); `org` (only if no org with that `name_norm` exists; name, `ort`, `webseite`); `org_register` scheme `LobbyR` |
| `impressum` | `org_person` for the role lines on curated Träger Impressum pages; `org` only if new |

Private table `funding_officers_person` (one row per `org_person` row): `reader`, `register_no`, **`quote`** (verbatim
from the archived source; `org_person` itself has no quote column), **`as_of`** (entry version valid-from date for
Lobbyregister, retrieval date for Impressum), `page_url` (human-readable page), `source_id`.
`org_person.jahr` = year of `as_of`; `org_person.locator` names the JSON path or Impressum line and the date.

Privacy rules (enforced in code and tests):
- Only name + published function. Person-level `contactDetails` (phone, e-mail), addresses and birthdates are
  never read into any table; quotes are cut so that they never contain contact data.
- Lobbyregister entries of natural persons (`identity != ORGANIZATION`) are skipped entirely.
- Organisations whose name marks them as a protected shelter (Frauenhaus, Schutzwohnung, Zufluchtswohnung,
  Gewaltschutz …) are skipped; no org row created here carries `strasse`, `plz` or coordinates.
- Persons named only in a Datenschutz / Redaktion / Webdesign context are not seeded.

CLI (never data/atlas.db; no mode or an unknown flag exits 2):
```
python3 tests/test_funding_officers.py
python3 -m ingest.domains.funding_officers --test
python3 -m ingest.domains.funding_officers --selftest --db /tmp/off_scratch.db [--source=lobbyregister|impressum] [--full] [--commit]
```
`--selftest` refuses atlas.db*, anything under `data/` and the Lead worktree; without `--commit` it rolls back.

## Source a — Lobbyregister des Deutschen Bundestages, API v2

| | |
|---|---|
| Publisher | Deutscher Bundestag, Lobbyregister für die Interessenvertretung gegenüber dem Deutschen Bundestag und der Bundesregierung |
| Search | `GET https://api.lobbyregister.bundestag.de/rest/v2/registerentries?q=<q>&format=json` (+ `cursor` paging) |
| Per-row citation | `https://api.lobbyregister.bundestag.de/rest/v2/registerentries/<registerNumber>?format=json` (archived, sha256); human page from `registerEntryDetails.detailsPageUrl` in `page_url` / locator |
| Key | header `Authorization: ApiKey <key>`. The open-data page publishes the current public key ("Der aktuell gültige API-Key lautet: …"). Stored as `LOBBYREGISTER_API_KEY` in `~/.config/germany-atlas/env` (chmod 600, outside git), read via `common.secret()`; never printed, logged or committed (the key is a header, so it is not in any cached URL or source row). |
| Licence / terms | Public register under the Lobbyregistergesetz; open-data API of the Bundestag (https://www.lobbyregister.bundestag.de/informationen-und-hilfe/open-data-1049716). Every API response names its source: "Deutscher Bundestag, Lobbyregister für die Interessenvertretung gegenüber dem Deutschen Bundestag und der Bundesregierung". No separate licence text is published; we cite with that source line. |
| robots | `api.lobbyregister.bundestag.de/robots.txt`: `Allow: /`. (www.lobbyregister.bundestag.de disallows `/sucheJson`, `/sucheDetailJson` and PDF exports: not used.) 1 req/s, project User-Agent. |

Selection: 21 keyword queries (Wohnungslosenhilfe, wohnungslos(e), Obdachlosenhilfe, obdachlos(e),
Wohnungsnotfallhilfe, Wohlfahrtspflege, Wohlfahrtsverband, Diakonie, Caritas, Arbeiterwohlfahrt, Paritätische,
Rotes Kreuz, Stadtmission, Bahnhofsmission, Sozialdienst katholischer, Johanniter, Malteser, Heilsarmee,
Volkssolidarität) plus one first-page query per organisation name already in `org`. An entry is kept when it is an
organisation and (a) its `name_norm` equals a Träger in `org` (`org_match`), or (b) its activities / public
allowances / regulatory projects mention homelessness (`homelessness`), or (c) its name is a welfare body
(`welfare`: Diakonie, Caritas, AWO, Paritätischer, DRK, Stadtmission, Johanniter, Malteser, Heilsarmee, SkF/SKM …).

## Full run (2026-11-21, scratch DB `/tmp/off_full.db` = main schema + funding_traeger full run; never atlas.db)
`python3 -m ingest.domains.funding_officers --selftest --db /tmp/off_full.db --full --commit`
- lobbyregister: 259 queries (21 keywords + 238 Träger names from `org`), **27 relevant entries**
  (welfare 16, homelessness 6, org_match 5), 27 orgs, **441 persons** (legal representatives with function +
  entrusted persons).
- impressum: 10 seed pages, 10 orgs, **28 persons**, 0 robots-blocked, 0 stale.
- `org_person` total **469** rows on **34 organisations**; governance roles (vorstand 96, geschaeftsfuehrung 26,
  praesidium 2) = **124 persons on 34 orgs**; `lobby_kontakt` 345. 11 of the 34 orgs are Träger that already
  had Berlin / TED money (e.g. BAG W, Johanniter-Unfall-Hilfe, Malteser Hilfsdienst gGmbH, Verein für Berliner
  Stadtmission, GEBEWO pro, Gangway, SkF Berlin, AWO Spree-Wuhle); 23 orgs are new (federal welfare
  associations, Tafel Deutschland, Off Road Kids Stiftung, Neustart e.V. …), none with address, phone or e-mail.
- verify.py on that DB (with the two SOURCES rows below added to a local, uncommitted copy of docs/SOURCES.md):
  **ALL GATES PASS** (G7: people only as sourced organisation roles).
- Entries dropped by the relevance rule in an earlier draft run (kept out on purpose): real-estate and tenant
  lobbies, rail, child-rights and international-aid bodies that only lobby *about* homelessness.
- As published: one Lobbyregister entry has first and last name swapped ("Ferlings Stephanie", BAG W,
  `"lastName":"Stephanie","firstName":"Ferlings"`); kept verbatim, flagged here.

## Source b — Impressum pages of Träger

Impressum data are mandatory publications (§ 5 DDG, § 18 MStV): name and function of the persons authorised to
represent the organisation. The reader uses a **curated seed list** (`IMPRESSUM_SEEDS`): page URL, organisation
as named there, and the expected (person, function, quote) lines. Each run fetches the live page (robots.txt
checked per host, 1 req/s, project User-Agent), whitespace-normalises the text and writes a person only if the
quote is still on the page; changed pages are reported as `stale` instead of guessed. A generic parser was
tried and rejected: Impressum layouts differ too much (role before / after the name, phone numbers and e-mails
interleaved, menu items named "Vorstand").

Seeds (2026-11-21): Verein für Berliner Stadtmission, GEBEWO pro gGmbH, GEBEWO -Soziale Dienste- Berlin gGmbH,
Gangway e. V., SkF e. V. Berlin, AWO Berlin Spree-Wuhle e. V., Deutscher Caritasverband e. V., BAG
Wohnungslosenhilfe e. V., AWO Bundesverband e. V., Diakonie Deutschland. Checked but not seeded:
eu-homecare.com (403), merkur-berlin.org and karuna.de (no response), der-paritaetische.de (no role lines in text).

## Source c — Handelsregister / Unternehmensregister: manual / later, not automated

- handelsregister.de: terms of use forbid more than 60 queries per hour and bulk automated retrieval; the
  search is a session/JSF form. Not automated. Use: manual look-ups of single Träger (Geschäftsführer of a
  gGmbH, Vorstand of an e.V. from the Vereinsregister "Aktueller Abdruck"), recorded with the document URL/date.
- unternehmensregister.de: robots.txt disallows `/de/veroeffentlichung`, `/de/registerinformationen`,
  `/de/registerPortal`, `/de/suche`. Not automated.
- Transparenzregister: not usable (public access ended, CJEU C-37/20; personal data).

## Verified
Checked live on 2026-11-21 with the project User-Agent, ≤ 1 req/s:
1. Susanne Hahmann — Vorsitzende, BAG Wohnungslosenhilfe e. V. — https://www.lobbyregister.bundestag.de/suche/R001487/88452
   ("Vertretungsberechtigte Person(en): Susanne Hahmann Funktion: Vorsitzende"); also on https://www.bagw.de/de/impressum
   ("Vertretungsberechtigter Vorstand: Susanne Hahmann (Vorsitzende)").
2. Daniela Keeß — Stellvertretende Vorsitzende, BAG W — same Lobbyregister page ("Daniela Keeß Funktion: Stellvertretende Vorsitzende").
3. Sabine Bösing — Geschäftsführung (Lobbyregister) / Geschäftsführerin (Impressum), BAG W — both pages above.
4. Andreas Steppuhn — Vorsitzender (seit 07.07.2023), Tafel Deutschland — https://www.lobbyregister.bundestag.de/suche/R000080/74928
5. Sirkka Jendis — Geschäftsführerin, Tafel Deutschland — same page ("Sirkka Jendis Funktion: Geschäftsführerin").
6. Eva Maria Welskop-Deffaa and Dr. Susanne Pauser — Deutscher Caritasverband — https://www.lobbyregister.bundestag.de/suche/R000896/88650
   and https://www.caritas.de/impressum ("Präsidentin Eva Maria Welskop-Deffaa", "Vorständin Personal und Digitales Dr. Susanne Pauser").
7. Dr. Christian Ceconi — Theologischer Vorstand, Verein für Berliner Stadtmission — https://www.berliner-stadtmission.de/impressum
8. Elvira Berndt — Geschäftsführung, Gangway e. V. — https://gangway.de/ueber-uns/impressum/
Every Impressum person is re-checked on each run (the quote must be on the live page); every Lobbyregister
person carries a verbatim JSON quote from the archived entry, and verify.py G9 traced all sampled rows.

## Coverage
- Universe: named Vorstand / Geschäftsführung / Präsidium members of homelessness and welfare Träger in Germany,
  in particular the Träger already in `org` (Berlin Zuwendungen, TED winners: ~240 orgs).
- Captured: 34 organisations, 124 governance persons (+345 lobby contacts). Of the Träger in `org` from
  funding_traeger, 11 now have named officers.
- Not covered: the other ~230 Träger in `org` (mostly local e.V. / gGmbH that are not in the Lobbyregister and
  not yet seeded); Länder-level welfare associations except where they lobby the Bund; Aufsichtsrat /
  Kuratorium (rarely in Impressum or Lobbyregister); historical officers (only the current entry version /
  current Impressum).
- Dates: Lobbyregister `as_of` = valid-from date of the register entry version, not the start of the office.
  Impressum `as_of` = retrieval date.

## SOURCES.md rows (for the Lead to append)

| Source | Gives | Licence / terms | Endpoint | Ingestor |
|---|---|---|---|---|
| Lobbyregister des Deutschen Bundestages, API v2, Registereintrag (JSON) | named legal representatives with published function and persons entrusted with interest representation of welfare / homelessness organisations; register number | Öffentliches Register nach dem Lobbyregistergesetz; Open-Data-API des Deutschen Bundestages; Quellenangabe "Deutscher Bundestag, Lobbyregister für die Interessenvertretung gegenüber dem Deutschen Bundestag und der Bundesregierung" (https://www.lobbyregister.bundestag.de/informationen-und-hilfe/open-data-1049716) | https://api.lobbyregister.bundestag.de/rest/v2/registerentries/<registerNumber>?format=json | `funding_officers` |
| Impressum pages of Träger (curated list) | names and published functions of Vorstand / Geschäftsführung / Präsidium | Pflichtangaben nach § 5 DDG / § 18 MStV, veröffentlicht vom Träger; zitiert mit Quellenangabe, nur Name und Funktion übernommen | https://www.berliner-stadtmission.de/impressum, https://gebewo.berlin/impressum, https://gangway.de/ueber-uns/impressum/, https://skf-berlin.de/impressum/, https://www.awo-spree-wuhle.de/impressum/, https://www.caritas.de/impressum, https://www.bagw.de/de/impressum, https://awo.org/impressum/, https://www.diakonie.de/impressum | `funding_officers` |

| Impressum pages of Träger (impressum_auto: Träger in `org` with a known website, TED winner website or SITE_SEEDS; worker scratch run 2026-11-23) | court register entry (Registergericht + VR/HRB/HRA number) and names and published functions of Vorstand / Geschäftsführung / Präsidium, each with a verbatim quote; no contact data of persons | Pflichtangaben im Impressum (§ 5 DDG / § 18 MStV), veröffentlicht vom Träger; keine offene Lizenz, Rechte vorbehalten: nur Name, Funktion und Registereintrag (Fakten) und eine kurze zitierte Zeile (§ 51 UrhG) mit Quellenangabe, redistribute_fulltext=0 | http://drk-betreuungsdienste-westfalen.de/footer-menue-deutsch/service/impressum.html · http://www.lavette-group.de/impressum-lavette-reinigungsdienste · https://allgaeu-medical.de/impressum/ · https://bildungszentrum-blume.de/impressum/ · https://bonveno-goettingen.de/impressum/ · https://fair-facility.de/impressum/ · https://forward-sozial.de/impressum · https://herozukunft.de/impressum · https://hilfefuerjungs.de/hilfe-fuer-jungs/impressung-datenschutz/ · https://hzm.de/reinigung/impressum/ · https://jugendbildung-hamburg.de/impressum/ · https://mookwat.de/kontakt/impressum/ · https://msm-security-service.de/impressum/ · https://offroadkids.de/impressum · https://schwulenberatungberlin.de/impressum/ · https://soziale-arbeit-mittelmark.de/impressum/ · https://tafel.de/footprintnavigation/impressum · https://unter-druck.de/impressum/ · https://www.aqtivus.de/impressum/ · https://www.bagfw.de/site/impressum · https://www.be-an-angel.de/de/impressum · https://www.bundesjugendwerk.de/impressum/ · https://www.caritas-regensburg.de/impressum · https://www.complete-dienstleistung.de/impressum · https://www.defensio-ignis.de/impressum/ · https://www.der-paritaetische.de/impressum/ · https://www.deutscher-verband.org/impressum · https://www.diakoniewerk-simeon.de/impressum · https://www.dornahof.de/impressum.html · https://www.drk-harburg.hamburg/service/impressum.html · https://www.drk-hochtaunus.de/service/impressum.html · https://www.drk-schaumburg.de/impressum · https://www.ewibo.de/impressum/ · https://www.herozukunft.de/impressum · https://www.human-care.eu/footer/impressum/ · https://www.jhj-hamburg.de/impressum/ · https://www.jonasbetterplace.com/impressum · https://www.jugendhilfe.de/Juhi-impr.html · https://www.jugendhilfeverein.de/impressum-und-datenschutz/ · https://www.kreuzberger-kinderstiftung.de/impressum · https://www.lawaetz-ggmbh.de/impressum/ · https://www.lebensnaehe.de/impressum/ · https://www.lebensraum-diakonie.de/impressum.html · https://www.livingquarter.de/impressum/ · https://www.malteser-werke.de/impressum.html · https://www.malteser.de/impressum.html · https://www.neuechance.de/impressum · https://www.neustart-ev.de/impressum/ · https://www.primus-service.de/impressum · https://www.prisod.de/impressum/ · https://www.pulsm.de/de/impressum · https://www.rullko.de/impressum/ · https://www.saxonia-catering.de/impressum-saxonia-catering-gmbh-ko-kg.html · https://www.skf-zentrale.de/impressum · https://www.skm-augsburg.de/impressum · https://www.skmev.de/impressum/ · https://www.sozialverein-friedrichshain.de/impressum/ · https://www.spsh.de/impressum · https://www.strassenkinder.de/impressum/ · https://www.tamaja.de/impressum/ · https://www.tandembtl.de/impressum.html · https://www.tannenhof.de/kontakt/impressum/ · https://www.waescherei-kellner.de/Impressum · https://www.zeppelin-rental.de/information/impressum · https://www.zieglersche.de/impressum | `funding_officers` |

(The impressum_auto URL list is whatever the run fetched: regenerate it from `source WHERE domain='funding_officers' AND title LIKE 'Impressum %'` after the Lead ingest, since the Lead DB has more Träger with websites than the worker scratch DB.)

Also registered (archived, not cited by rows): the robots.txt of each Impressum host is fetched via
`common.fetch` (cache only, no `source` row).

## Caveats and next steps
- Lobbyregister covers only organisations that lobby the Bund: the federal and Land welfare associations,
  large Träger. Small local Träger (most Berlin/TED recipients) are not in it.
- `lobby_kontakt` persons are employees named as entrusted with interest representation: a published
  professional role, but not governance. Filter `rollenklasse IN ('vorstand','geschaeftsfuehrung','praesidium',
  'aufsichtsrat','kuratorium')` for boards.
- Impressum seeds are hand-curated; extending them is the cheapest way to cover more Träger in `org`.
  Next: Initiative Transparente Zivilgesellschaft signatories (transparency.de list → each Träger's
  "Transparenz" page names Vorstand / Geschäftsführung), and annual reports (PDF, page-cited).
- The same person can appear twice for one organisation (Lobbyregister function and Impressum function differ,
  e.g. "Präsident" vs. "Vorsitzender des Vorstands, Präsident"); `funktionstraeger_norm` makes them joinable.

## Lead merge notes (2026-11-21)
- `funding_officers_person` is folded into `org_person` (schema 4: `quote`, `stand`); no side table. `reader`,
  `register_no` and `page_url` are recoverable from `source.url`, `org_register` (scheme `LobbyR`) and `locator`.
- `_raw_quote` now walks every occurrence of the last name and quotes the object that also carries the first name.
- Activity-text relevance ignores "Bahnhofsmission" (Allianz pro Schiene matched only because the Bahnhofsmission is a member).
- Officers attach to an existing org only when the legal form agrees (Malteser Hilfsdienst e.V. is not the gGmbH).
- AWO Bundesverband Impressum rows link to the Lobbyregister org "AWO Bundesverband e.V." (`link_org`).
- Licence wording corrected: the Lobbyregister has no open licence; sources carry `redistribute_fulltext=0`.
- A run where every Lobbyregister request fails, or no person is written, now fails instead of ingesting 0 rows.


## Open duplicate candidate: two "Malteser Hilfsdienst gGmbH" org rows (left unlinked, 2026-11-23)

| org row (worker scratch) | Land | source | what the notice prints |
|---|---|---|---|
| Malteser Hilfsdienst gGmbH | HE | TED 203109-2022 (https://ted.europa.eu/en/notice/203109-2022/xml) | contractor address Frankfurter Straße 9, 65549 Limburg a.d. Lahn; **no register number** |
| Malteser Hilfsdienst gGmbH | BW | TED 243674-2026 (https://ted.europa.eu/en/notice/243674-2026/xml) | contractor town Stuttgart (70327, NUTS DE111); **HRB 26997 (AG Köln)** |

Not linked: the HE notice prints no register number and its address (Limburg) differs from the BW one (Stuttgart),
so neither hard id nor address proves one legal entity (Malteser runs regional branches under one gGmbH, but
also separate regional gGmbHs). A Lead `manual` merge needs a source that ties the Limburg contractor to HRB 26997.

## Impressum reader guarantees (Lead review 2026-11-23)

1. robots.txt per host, read live with the project UA, fail closed (unreadable / 5xx / 401 / 403 / off-site redirect
   = host skipped; 404/410 = no rules), crawl-delay honoured, 1 req/s floor (common.fetch), pages cached on disk;
   parser and matcher reused from `ingest.domains.counts_law`. Every page request goes through `gated_fetch`.
2. Only governance role lines (Geschäftsführung, Vorstand, Präsidium, Aufsichtsrat) and the court register entry are
   written. Datenschutzbeauftragte, webmaster, photo credits, Redaktion, V.i.S.d.P. / § 18 MStV contacts are never
   extracted unless the same line labels them with a governance role. A quote containing an e-mail address or a
   phone/fax number is dropped. No address, phone or e-mail column of `org` is written. USt-IdNr is not read.
3. Träger of protected shelters (org.is_protected, a protected facility with this Träger, or a name matching
   Frauenhaus / Schutzwohnung / Zuflucht / Frauen helfen Frauen / Mädchenhaus / Inobhutnahme / anonyme Notaufnahme …)
   are skipped before any request, so no Impressum of theirs is fetched, archived or parsed: Land level only.

## Malteser Hilfsdienst e.V. (TED 624927-2022): VR 4726 not proven, link stays flagged (Lead review 2026-11-23)

Question: is the TED award party "Malteser Hilfsdienst e.V." (Lead org 682, BW, no register) the Lobbyregister
entity R001276 "Malteser Hilfsdienst e.V." (Lead org 658, VR 4726)?

What every cited source says:

| source | quote (verbatim) | register? | Freiburg/Köln? |
|---|---|---|---|
| TED 624927-2022 (contract award, cached `data/raw/funding_traeger/51c5d8aa….bin`) | "Alltagsbetreuung für Flüchtlinge (Notunterkunft) 2022-10-19 1 Malteser Hilfsdienst e.V. Freiburg i. Br. 1100000.00 1343000.00" | **none** (no national ID in the notice) | Freiburg i. Br. only |
| Lobbyregister R001276 | legal form LF_EV, seat Köln; Freiburg appears only as a *donor* ("Regierungspräsidium Freiburg", "Stadt Freiburg") in the public-allowances list | no "4726" in the entry | Köln; nothing says the Freiburg unit is the same Verein |
| malteser.de/impressum (cached `data/raw/funding_officers/88b7fcb2….bin`) | "Registergericht: Amtsgericht Köln Registernummer: VR 4726", address "Erna-Scheffler-Str. 2 51103 Köln" | VR 4726 | Köln; no Freiburg |

No cited document ties the Freiburg award party to VR 4726 or to the Köln Verein. The VR on the TED row came only
from a **name-keyed** Impressum seed (`SITE_SEEDS["Malteser Hilfsdienst e.V."] = malteser.de`), which matched by name
and wrote the Köln register onto the Freiburg row. Decision: **no hard link**. The seed is removed (commit below);
a fresh scratch run leaves the e.V. TED row without a register (court-register fills 39 → 38). Org 682 ↔ 658 stays a
flagged `name_fuzzy` candidate for manual review. (No "VR 4726" text was in research/*.md or the regression tests;
`test_malteser_ev_not_on_ggmbh` asserts only that e.V. officers never land on the gGmbH.) If the Lead's DB still holds
VR 4726 on a TED-derived row from an older run, it came from that seed and should be cleared there; this module no
longer writes it.

## Why our scratch run says 536 / 61 and the Lead's merge says 494 / 69 (measured 2026-11-23)

Measured on scratch DB `/tmp/fa_full3.db` (fresh schema; funding_traeger then funding_officers; 247 orgs):

1. **536 is not an org_person count.** It is `ingest_run.rows` of the funding_officers run = persons written
   (Lobbyregister 436 + Impressum seeds 28 + impressum_auto 33 = 497 upsert calls, a few of them updates of the same
   key) + 39 court-register fills. `SELECT COUNT(*) FROM org_person` on that DB = **492**
   (434 Lobbyregister: 91 governance + 343 lobby contacts; 58 Impressum). The Lead's 494 is an org_person count.
   Like for like: 492 vs 494. A re-run on the same DB today gives 494 (`/tmp/fa_relabel.db`), so the 2-row gap is
   run-to-run drift of live sources, not lost rows.
2. **Flagged links, 61 vs 69.** Our 61 = 46 award name_fuzzy + 10 impressum + 5 lobbyregister, over our 247 orgs.
   The Lead's DB has ~682 orgs from all domains; its 69 includes links in that larger org set (e.g. the new
   TED Malteser e.V. org 682 ↔ 658 name_fuzzy). We may not open the Lead's DB, so the per-kind split of the extra 8 is
   **not measured here**; the Lead can get it with
   `SELECT record_kind, method, COUNT(*) FROM org_link WHERE flagged=1 GROUP BY 1,2`.
3. **Robots refusals, 2 vs 6: cache.** `gated_fetch` (counts_law pattern) checks robots.txt only before a live fetch;
   a page already in `data/raw/funding_officers/` is served from cache. In our run almost every Impressum page was a
   cache hit, so robots.txt was requested for only 5 hosts (log: 2 read, 1 404 = no rules, 2 unreadable → refused).
   Both refusals are DNS failures (fail-closed): `www.bewa-security.info`, `www.liga-thueringen.de`.
   The Lead's worktree has its own cache, so its run fetched live and checked robots per host, giving 6 refusals.
   Pages refused there are pages we read from cache; with 1–2 persons per page this can move a handful of
   impressum_auto rows either way. The host list of the Lead's 6 is in its run log (`robots-skip` lines); not visible
   from this worktree.
4. **Pages only we read.** Our run cited 3 Impressum pages that the Lead run #26 did not cite (verify G3 flagged
   them until added to docs/SOURCES.md): `https://www.neuechance.de/impressum`,
   `https://www.strassenkinder.de/impressum/`, `https://www.jonasbetterplace.com/impressum`. Their robots.txt allows
   us today (checked 2026-11-23: strassenkinder/neuechance answer 301 to their new hosts, jonasbetterplace
   `User-agent: * / Disallow:`), so these are cache-vs-live and org-set differences, not robots blocks.

## Source d — Initiative Transparente Zivilgesellschaft (ITZ) transparency pages (2026-11-23)

The ITZ signatory list (https://www.transparente-zivilgesellschaft.de/ueber-uns/unterzeichnerorganisationen, pages
1–100, 20 per page, page 101 = 404; robots.txt allows `/ueber-uns/`) links each signatory's own transparency page.
Point 4 of the ITZ self-commitment is "Name und Funktion wesentlicher Entscheidungsträger", so these pages are a
published, organisation-authored source for governance roles (same facts-only/GDPR rules as Impressum pages:
name + published function + verbatim quote, no contact data, protected-shelter Träger never fetched).

Matching: exact `_norm_tokens` name **and** compatible legal form (a gGmbH never takes an e.V.'s page); if one list
entry fits several org rows, or several entries fit one org, nothing is written (reported as ambiguous). The page
must name the organisation. Parser (`itz_people`): only inside point 4 (until the next numbered item, max 3000 chars):
`Name, Funktion` / `Name – Funktion` / `Name (Funktion)` lines, name lines under a governance heading
(Vorstand, Geschäftsführung, Aufsichtsrat, Kuratorium, Stiftungsrat …), and `Vorstand: A, B und C` lines. Headings
like Leitung, Prokura, Gesellschafterversammlung, Kontakt end a block; roles in another organisation
("Vorstandsvorsitzender des Sozialverbandes VdK …") are skipped; on a GmbH page only Geschäftsführung (and a
non-foundation Aufsichtsrat) count. A heading class wins for bare "Vorsitzender"/"Mitglied" under Kuratorium /
Stiftungsrat. Every stored quote contains its funktion label and is verbatim on the page.

Scratch run (`/tmp/fa_itz.db`, copy of the fresh scratch DB, 2026-11-23): 1,999 signatories parsed; 33 matched a
Träger (15 already had officers, 3 ambiguous: the three Johanniter-Unfall-Hilfe e.V. rows); 16 pages naming the org
(robots 1, not named 1); 8 had no parseable point-4 roles (links to PDFs/other pages: Caritas Berlin, Diakonie
Berlin-Brandenburg, DRK Berlin-Zentrum …); **20 persons on 8 new orgs** (org_person 494 → 514, orgs with
governance officers 52 → 60).

Annual / transparency reports (PDF) are **not** parsed yet: the 8 "no role line" pages mostly point to a
Geschäftsbericht or Vereinsregisterauszug PDF. Next step if wanted: pdftotext on the linked report, same point-4
parser, page number in the locator.

## Soft hyphens (&shy;) in Träger pages (2026-11-23)

12 of 1,667 cached funding_officers pages contain U+00AD soft hyphens ("Geschäfts­führerin", "dia­konisches
Unter­nehmen"); `html_to_text` keeps them, so a role label or the organisation's name split by one was invisible to
the parsers. Now `deshy()` removes them for matching and parsing (Impressum auto and ITZ readers), and
`verbatim_quote()` maps each quote back to the archived text with the soft hyphens in place, so the stored quote is
still verbatim for verify G7 (`norm(quote) in norm(archived text)`). A person whose *name* is split by a soft hyphen
is skipped and counted ("soft-hyphen name/quote skipped"), never stored altered (G7 checks every name token
against the archived text). Fresh scratch run: +1 court register (MSM Security & Service GmbH, HRB 15340,
AG Gelsenkirchen; its page prints the name with soft hyphens), 0 skipped names.
Note for the Lead: a stored quote may contain U+00AD; if verify's `norm()` stripped U+00AD on both sides, quotes
could be stored clean instead. That would be a verify.py change, so I did not make it.

## Register lines replace name_fuzzy links; Berlin ZUWDB numbers; eForms CompanyIDs (Lead review run #29, 2026-11-23)

- **Seed Impressum pages link by register.** When the page prints a court register line for the organisation
  (nearest after its name, scheme fits the legal form, not ambiguous), the org is resolved by that register
  (`common.resolve_org`) and the link is `method=register_id` with the register as id_value. The same link row
  (`impressum`, `<url>#<org>`) is upgraded from name_fuzzy, never downgraded. If the page spells the org
  differently, its only register line still counts when the org of that name already holds that register or the
  equal ZUWDB number. Fresh scratch run: 8 of 10 seed pages link by register. Still name_fuzzy: GEBEWO pro gGmbH and
  GEBEWO -Soziale Dienste- Berlin gGmbH. Their shared page prints HRB 54310 and HRB 95854 next to each other, so
  which number belongs to which company is left open, not guessed.
- **Berlin Zuwendungsdatenbank = AG Charlottenburg.** `vr_024148` = `VR 24148 B (AG Charlottenburg)` (leading
  zeros and the B suffix normalised; only Berlin's register court qualifies). A page register equal to an org's ZUWDB
  number proves identity (link register_id, court register added, `org.register_id` never overwritten). On an
  impressum_auto page, a different Berlin number than the org's ZUWDB number marks another entity, so neither the
  register nor the officers are taken. Examples: Verein für Berliner Stadtmission VR 24148 = vr_024148, AWO Berlin
  Spree-Wuhle VR 21507 = vr_021507.
- **"Vereinsregister 31924 B"** (Diakonie Deutschland: "Amtsgericht Berlin-Charlottenburg, Vereinsregister 31924 B")
  is now parsed as VR 31924 B (AG Charlottenburg).
- **eForms CompanyID / TED NATIONALID** (`funding_traeger.valid_company_id`): kept as `award.empfaenger_id` only if
  it is a USt-IdNr (DE + 9 digits, stored without spaces), a court register number (VR/HRA/HRB/GnR/PR + digits)
  or an LEI. Dropped: notice-internal sequence numbers ('0', '1', '2', '4', '5', '6'), GUIDs, tax numbers
  ('349/5999/9337'), 'keine Angabe', and 'AG Bochum B14528' (no scheme). On the same TED notices: 44 award rows
  changed. 34 went to NULL and 10 USt-IDs lost their spaces. Non-NULL empfaenger_id 98 → 64. No award changed org.
  A Lead DB re-run will see this drop of 34 in G11c, so it needs a `docs/null_allowlist.tsv` line for
  `award.empfaenger_id`.

## Robots before every request; schema 6 (2026-11-23, rebased onto lead/core c46e3f6)

- `robots_gate()` is now the first step of every request the two funding modules make: Impressum/ITZ pages,
  the Lobbyregister API, berlin.de Zuwendungsdatenbank JSON/detail pages, the TED search API (POST) and the
  TED notice XML. robots.txt is read once per host per run, fail-closed. A disallowed path (e.g. `/api/`) raises
  RobotsRefused and is never requested. Only a response already in the disk cache skips the gate, because it needs
  no request. Checked 2026-11-23: api.lobbyregister.bundestag.de `Allow: /`; api.ted.europa.eu robots.txt 404
  (no rules); ted.europa.eu and www.berlin.de allow the paths we use. Test: `_test_robots_first`.
- Schema 6 (INGEST_CONTRACT §12): kept the Lead's `_ensure_org` (legal_form_norm + flag_new_org) and
  `resolve_or_find` (common.find_org). The seed fallback uses `common.find_org`, and every test fixture org row sets
  `legal_form_norm`. Fresh v6 scratch run: flagged 52 (award name_fuzzy 46 → 45), no `org_name` split flags.
