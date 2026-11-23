# funding_hamburg – Hamburg Zuwendungsvorgänge (Transparenzportal Hamburg)

Worker: funding_traeger worker, branch `worker/funding_traeger` (on 9f07026). Module `ingest/domains/funding_hamburg.py`,
tests `tests/test_funding_hamburg.py`. Plan: `research/funding_nonberlin_plan.md`.

## Why its own domain (not a source inside funding_traeger)

* INGEST_CONTRACT §2: one domain = one `run(conn, cfg)` with its own raw cache (`data/raw/funding_hamburg`), run summary,
  licence and selftest. The Hamburg file is a 9 MB XLSX with 77k rows; a separate run keeps the funding_traeger run
  (Berlin JSON + TED API) fast and lets the Lead re-run Hamburg alone.
* Different source family and licence (CC0 open-data file vs. CC BY-SA Berlin / TED legal notice), different fetch
  policy (Crawl-Delay 10, /api/ forbidden) and a different record model (Bescheide → Vorgänge).
* `ingest/run.py` loads domains with `importlib.import_module(f"ingest.domains.{domain}")`, so no runner change is needed.
* Shared code is imported, not copied: `funding_officers.robots_gate`/`robots_ok` (robots-first gate),
  `funding_traeger.BZ_CORE/BZ_ADJACENT/REFUGEE_RE/is_protected/redact_place/ted_is_person`, `common.ensure_org`,
  `common.xlsx_cell_line`, `institutions_media_orgs.iter_xlsx_sheets`.

## Access path (robots-first, 2026-11-23)

1. `https://suche.transparenz.hamburg.de/robots.txt` read first through the gate: `Disallow: /api/`, `/dataset/rate/`,
   `/revision/`, `/dataset/*/history`, `Crawl-Delay: 10`. The gate honours 10 s between requests to the host
   (the robots.txt read counts as the first request).
2. HTML search `https://suche.transparenz.hamburg.de/dataset?q=Zuwendungsvorg%C3%A4nge` (+ `&page=2..5`; the
   `/dataset/?q=…&page=n` form with a slash answered HTTP 500 once, the slash-less form works). 31 dataset slugs seen:
   `zuwendungsvorgaenge-2018-quartal-31` … `zuwendungsvorgaenge-2024-quartal-4`, `zuwendungsvorgaenge-2025`
   (CKAN adds a digit to duplicate slugs: `quartal-31` = Q3; the module reads the first digit).
3. Dataset page `https://suche.transparenz.hamburg.de/dataset/zuwendungsvorgaenge-2025` → one resource link
   `https://daten.transparenz.hamburg.de/Dataport.HmbTG.ZS.Webservice.GetRessource100/GetRessource100.svc/a9b44838-45d0-4f57-a27c-b7275684535b/Upload__Zuwendungsbericht2025INEZ.XLSX`.
   The page also links `http://suche.transparenz.hamburg.de/api/3/action/package_show?id=…`: never followed
   (`hh_fetch` refuses any `/api/` path before the gate, test `_test_discovery_and_api`).
4. `https://daten.transparenz.hamburg.de/robots.txt` read first (404 = no rules), then the XLSX (1 req/s).
   Requests this task: robots ×2, search pages 1–5 (one 500 on the slash form), 2 dataset pages, 2 XLSX
   (Q4 2024 for comparison, 2025). No /api/ request.

Licence printed on both dataset pages inspected (2024 Q4, 2025): **Creative Commons CCZero**, "Namensnennung: Freie und
Hansestadt Hamburg". The plan said dl-de-by-2.0 (from the portal search listing of older datasets); the module
stores the licence printed on the dataset page it used, and attributes the Finanzbehörde anyway.

## The file

Sheet `Sheet1`, 76,962 rows (header + 76,961 Bescheide), 42,085 INEZ-Nummern (Vorgänge), Bescheiddatum
2015-01-12 … 2025-12-29. Columns: INEZ-Nummer, Bescheiddatum (Excel serial), Bescheidart, Zuwendungsempfänger,
Behörde, Dienststelle, AKZ, ZuwendungszeitraumVon/Bis (serials), Zuwendungszweck, Förderungsart, Finanzierungsart,
Finanzierungsform, Summe von Betriebskostenanteil / Investitionskostenanteil / Rückforderungen / Zuwendungssumme.
No addresses, no register numbers, no USt-IdNr. 615 rows have the purpose "Datenschutzwürdiger Zweck" (withheld).

Bescheidarten: Zuwendungsbescheid 42,594 · Änderungsbescheid 25,183 · Rückforderungsbescheid 5,024 · Aufhebungs- und
Rückforderungsbescheid 1,750 · Teilbescheid 1,022 · Aufhebungsbescheid 504 · Zuwendungsvertrag 476 ·
Empfängerwechsel 340 · Änderungsvertrag 68.

**Cumulative snapshots.** Q4 2024 file: 83,530 rows, Bescheide 2015–2024; the 2025 file: 76,961 rows, 2015–2025
(fewer 2015–2016 rows: 2,944 vs 7,810 for 2015). Every dataset repeats the history, so only the newest one is read;
adding older snapshots would multiply-count. Not covered: Bescheide only in older snapshots (mostly 2015–2016).

**Änderungsbescheide restate the total.** Example SF-097035: Zuwendungsbescheid 13,656,000 → Änderungsbescheide
13,656,000 → 14,084,000 → 16,152,718 with the period extended. So one award per Vorgang carries the Zuwendungssumme of
its LATEST amount-bearing Bescheid (Zuwendungs-/Änderungs-/Teilbescheid, Zuwendungs-/Änderungsvertrag,
Empfängerwechsel; same day → longer period, then the earlier file row). Rückforderungs-/Aufhebungsbescheide are
stored in `funding_hamburg_bescheid` (33 kept rows with Rückforderungen, EUR 411,804.28) but not netted off the
award: `award.betrag` is the latest bewilligte Zuwendungssumme, not the money finally kept.

## Filter (keyword + Behörde, like Berlin)

On the Zuwendungszweck only (recipient names like "Streetlife e.V. Verein für Straßensozialarbeit" would pull in
their youth work). A Vorgang is in scope when any of its Bescheide matches.

* core = `funding_traeger.BZ_CORE` (wohnungslos*, obdachlos*, Wohnungsnot*, Kältehilfe, Kältebus, Wärmestube,
  Notübernachtung, Nachtcafé, Housing First, Bahnhofsmission, ohne Wohnraum/Obdach, Zwangsräumung, Wohnungsverlust,
  Mietschulden, § 67 SGB XII) + Hamburg terms: Winternot(programm), Tagesaufenthalt(sstätte), Übernachtungsstätte,
  Krankenstube, Straßenzeitung, Hinz & Kunzt, Mitternachtsbus, "Obdach". Any Behörde.
* adjacent = `BZ_ADJACENT` (Straßensozialarbeit, Suppenküche, Kleiderkammer, Notunterkunft, Notunterbringung,
  Essensausgabe) + Tagestreff, kept only when the Behörde is the social authority (name contains "Soziales":
  BASFI / BAGSFI / Sozialbehörde) and the text has no refugee term (`REFUGEE_RE`). Bezirksamt youth street work drops.
* Not adjacent on their own: "öffentlich-rechtliche Unterbringung", "Wohnunterkunft" (Hamburg houses refugees and
  homeless people in one system; the grants on these words are play schemes, childcare and counselling in refugee
  follow-up housing: SpielTiger e.V. 6.2 M, Verein zur Förderung der Jugendarbeit 3.7 M were dropped), and Sucht*
  (addiction care is its own field; 825 hits). They count only next to a core term.
* Recipients: natural persons / sole traders / GbR and names without any organisation token are skipped
  (`ted_is_person`, privacy wins), except a spelled-out public-law form ("Die Heilsarmee in Deutschland Körperschaft
  des öffentlichen Rechts", 1 Vorgang). Final run: 1 skipped, "Housing First Hamburg" (a project name; verify G7 also
  reads it as a person's name; Housing First grants paid to named Träger are kept).
* Protected shelters (`is_protected` on purpose or name): money kept, Dienststelle / Kreis / Gemeinde NULL, purpose
  street-redacted, tag `protected_shelter`. Final run: 0 such Vorgänge (Frauenhaus grants carry no homelessness term).

## Citation

`award.quote` = the exact line `common.xlsx_text` renders for the Zuwendungssumme cell, e.g.
`[Sheet1!Q2327] SF-101834 Änderungsbescheid Caritasverband … = 32049.99`; `award.locator` = file URL + sheet, row,
cell, Bescheidart, date and "latest of n Bescheide of INEZ x". `betrag` = the cell value exactly as stored
(float of the cell text), so G5 finds it.

**G9 issue (Lead's verify).** Some cells are written as binary-float text: `149286.76999999999` is the double
149286.77 (10 of 175 awards in the final run). G5 passes (it parses numbers), but G9's token forms (`149286.77`, `149.286,77`) are
not in the line, so a sampled award of that kind fails G9. Proposed verify change (not committed; Lead's file):

```diff
+_PLAIN_DEC_RE = re.compile(r"(?<![\d.,])-?\d+\.\d+(?![\d.,])")
+
+
+def float_artifacts(line: str) -> list[str]:
+    """Plain decimals with 15-17 significant digits (an XLSX cell written as a binary float, e.g. 283502.03000000003)."""
+    return [t for t in _PLAIN_DEC_RE.findall(line) if len(re.sub(r"\D", "", t).lstrip("0")) >= 15]
 ...
             hits = [n for n, ln in enumerate(lines) if any(p_.search(ln) for p_ in pats)]
+            if not hits and not float(v).is_integer():
+                # XLSX cells keep binary-float artifacts: '149286.76999999999' IS the stored double 149286.77
+                hits = [n for n, ln in enumerate(lines) if any(float(t_) == v for t_ in float_artifacts(ln))]
```

With it, all 175 Hamburg awards trace to their line (checked offline against every award, not only the sample).
Alternative: `common.xlsx_text` could render numeric cells as `repr(float(cell))`, but that changes the text of every
archived XLSX source.

## Org resolution (schema 6)

Only `common.ensure_org(conn, name, "HH", sid)`: no hard ids in the file, so the name step (`find_org`, key
name_norm + legal_form_norm + Land) decides; legal_form_norm comes from the name; name_norm untouched.
Land = HH for every recipient (the file has no seat; Hamburg grants go to Hamburg Träger almost always – a
limitation). Different spellings stay separate rows (e.g. "STREETLIFE - Verein für Straßensozialarbeit in Hamburg e.V."
vs "Streetlife e.V. Verein für Straßensozialarbeit in"; "Evangelische Stiftung der Bodelschwingh- Gemeinde" vs
"Ev.Stiftung Bodelschwingh-Gemeinde"): no fuzzy merging here, the Lead's review decides.

## Final scratch run (/tmp/fa_hh.db = /tmp/fa_v6.db + funding_hamburg)

175 Vorgänge (core 156, adjacent 19), 409 Bescheide, 29 recipients, EUR 44,596,999.58; Zuwendungszeitraum
2016-01-01 … 2026-12-31 (start years 2016:13 … 2025:22, 2026:5; 19 multi-year Vorgänge have haushaltsjahr NULL).
Largest: Diakonisches Werk Hamburg (57 Vorgänge, 16.5 M), Caritasverband Erzbistum Hamburg (28, 8.2 M),
MW Malteser Werke gGmbH (5, 7.0 M), Kemenate Frauen Wohnen e.V. (11, 3.7 M), Basis & Woge e.V. (11, 2.7 M).
28 new org rows (1 with unknown legal form, 0 flagged namesakes); award links: origin 170, name_fuzzy (flagged) 5
(DRK Kreisverband Hamburg-Harburg e.V., existing funding_traeger org 136).
