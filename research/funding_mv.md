# funding_mv – Mecklenburg-Vorpommern Zuwendungen (LAGuS Zuwendungsverzeichnis, WoftG M-V)

Worker: funding_traeger · branch worker/funding_traeger · 2026-11-23 · survey and choice: research/funding_nonberlin_survey.md

## Why this source, and one domain of its own
The survey found no non-Berlin source that is machine-readable, openly licensed, names recipients with amounts, is about
homelessness **and** is reachable under our robots rule: Bremen (CC BY XLSX) and the federal ESF Plus / EhAP Plus list
are the two that would be, and both are blocked by robots.txt (403 / `/SiteGlobals/`). The ESF Plus Länder lists are
open XLSX files but have ~0 homelessness rows outside Berlin. The LAGuS Zuwendungsverzeichnis is the best reachable
source: a statutory list (§ 12 Abs. 2 WoftG M-V) of every Land grant to social-work Träger, with recipient, purpose,
period and amount, so it gets a reader.

**Domain choice:** a domain of its own (`funding_mv`), not a shared "funding_laender", because:
* it has its own parser (a PDF layout table), its own raw cache and its own side table;
* the Land's second WoftG source (the Transparenzdatenbank: register numbers, legal forms, Entscheidungsträger) is
  the natural next step and belongs in the same module, with the same host family and the same legal basis;
* a shared Länder domain would make a failure in one Land's reader stop the others' runs.

## Access path (robots-first)
1. `http://www.zuwendung-mv.de/robots.txt` through `funding_officers.robots_gate` (the request is redirected and the
   gate finds no Disallow lines), project UA, ≥ 1 s per host;
2. start page `http://www.zuwendung-mv.de/` → its only PDF link `zuwendung.pdf`;
3. the PDF (178,452 bytes, 68 pages, "für das Jahr 2020", sha256 6a22af57…), archived under data/raw/funding_mv.
Three requests per run. The start page links only one edition (2020). Older or newer years are not offered.

## Parsing
The PDF is a layout table (Ghostscript output, no tagged structure). Cells wrap over 1–7 lines and are vertically
centred on the **anchor line**, which holds the lfd. Nr., both dates and the amount. Some pages use a narrower scale.
The reader works on `pdftotext -bbox` word boxes:
* anchors: words `N.` in the leftmost column that have a date on the same baseline;
* the date column is the x of the second-last date on the anchor lines. Dates inside the Zweck ("26.07. –
  31.07.2020") are therefore not taken as the period;
* the Empfänger|Zweck boundary is the widest empty vertical gutter between the number and date columns, per page;
* wrapped lines go to the anchor whose cell spans as far below the anchor as it does above it. "Mecklenburg-" +
  "Vorpommern" is joined without a space; a spaced " -" is kept.
Result on the live file: all 663 lfd. Nr. parsed (1..663, no gaps); every row has a name, purpose, two dates and one
amount. The quote is the anchor line exactly as `pdftotext -layout` renders it (the text verify archives). It always
contains the lfd. Nr., dates and amount, but may hold only part of the name or Zweck, e.g.
`435. 01.01.2020 31.12.2020 19.150,37 €`. The locator gives the page and the lfd. Nr.

## Filter
`funding_traeger.BZ_CORE` plus "Straßenzeitung…" and "Obdach" (as in Hamburg) give the core tier. `BZ_ADJACENT` gives
the adjacent tier when no refugee context is named. All social authority, so there is no Behörde condition.
Live result (2020): core 4, adjacent 0.

| lfd. Nr. | Empfänger | Zweck (short) | EUR |
|---|---|---|---|
| 430 | Deutscher Paritätischer Wohlfahrtsverband Landesverband M-V e.V. | ASB OV Hagenow/Ludwigslust: Wohnungsnotfallhilfe | 16,000.00 |
| 431 | same | Wohltat e.V.: Betreuung der Verkäufer der Straßenzeitung „Strohhalm“ | 18,000.00 |
| 435 | Diakonisches Werk Mecklenburg-Vorpommern e.V. | „Treffpunkt Stadtmitte“ Wismar … Möglichkeit für Obdachlose zu duschen | 19,150.37 |
| 437 | same | „Soziales Haus Loitz“ – Hilfe für wohnungslose Menschen (Kreisdiakonisches Werk Greifswald e.V.) | 15,000.00 |

Considered and left out (no homelessness term in the text, no inference): 429 Phönix e.V. Straffälligenhilfe,
432 Caritas help with "Wohnungssuche" for immigrants, 434 Begegnungsstätte "Lichtblick", 436 Tagesstätte Boot
(Diakoniezentrum Borwinheim Neustrelitz), 438 SOS-Station (addiction).

## Pass-through (Liga funds)
The Spitzenverbände receive the Liga money and forward it to members. The Zweck names the executing member
("ASB OV Hagenow/Ludwigslust: …", "… organisiert vom Kreisdiakonischen Werk Greifswald e.V.", "durch : …").
The award recipient stays the Zuwendungsempfänger that the document names. The member is kept only as text
(`funding_mv_zuwendung.durchfuehrung`, also in the award locator). No org row and no link is made for it.

## Privacy and protection
* Natural persons and sole traders / GbR (`funding_traeger.ted_is_person`) are skipped entirely: 20 rows, which are
  not stored even in the side table. The guard is conservative, so some of the 20 are organisations without a
  legal-form token ("Stift Bethlehem", "Erzbistum Hamburg", "CJD Nord", "Bürgerstiftung Vorpommern"). None of them is
  a homelessness row; this costs nothing in scope.
* Protected shelters (21 rows: Frauenhäuser, Frauenschutzhaus, Interventionsstellen …): the side table keeps
  recipient, period and amount but no Zweck, no executing member and no quote (Land level only). None is in award
  scope.

## Results (scratch run, /tmp/fa_mv_run.db = copy of /tmp/fa_v6.db, real runner)
* 663 rows parsed; 643 organisation rows in funding_mv_zuwendung;
* **4 awards, 2 recipients (both new orgs, legal_form_norm ev, Land MV), EUR 68,150.37, year 2020**;
* link methods: origin only (2 org + 4 award), 0 flagged, 0 name_fuzzy;
* verify (scripts/verify.py --db /tmp/fa_mv_run.db): ALL GATES PASS (G3 1172 sources, G5 710 numbers, G9 705 sampled rows).

## Licence / terms
No licence is stated on zuwendung-mv.de or in the PDF. It is a statutory publication (§ 12 Abs. 2 WoftG M-V). We store
facts only (names, purpose, period, amount) with a citation, as for TED and the Lobbyregister. **A human should confirm
this**, see the survey's "Needs a human" list.

## Next (not built)
* **Transparenzdatenbank M-V** (https://www.transparenz-mv.de, robots: no rules; 355 Träger in 24 HTML list pages):
  register number, Rechtsform, Kreis and Spitzenverband per Träger, plus per-Träger pages with Entscheidungsträger
  (name + Funktion, published by the Träger under WoftG "only if already public or with consent") and
  Hauptzuwendungsgeber. This gives register ids for the two recipients above and officer coverage from a statutory
  filing. About 2 requests per Träger at 1 req/s.
* Newer Zuwendungsverzeichnis years when LAGuS publishes them (the reader takes whatever PDF the start page links).

## Source 2: Transparenzdatenbank M-V (Träger and Entscheidungsträger), added 2026-11-23

- Pages: list https://www.transparenz-mv.de/site/index?page=<n>&per-page=15 (24 pages, 355 Träger), one Entscheidungsträger page per Träger at /entscheidungstraeger/wizzard?id=<uuid>. robots.txt fetched first through the gated fetch (no Disallow rules); 1 req/s; project User-Agent.
- Licence: none stated; statutory publication under the WoftG M-V. Facts only with citation, redistribute_fulltext=0 on every source (Lead, 2026-11-23, like TED and the Lobbyregister).
- Orgs: a register number is stored in org_register only when the court is stated (funding_officers.impressum_registers rules; "B" suffix = Charlottenburg). 241 published numbers have no court ("VR 1243") and are not stored as ids; when such a number equals a matched org's register, that goes into the link note only. Resolution: register holder -> register_id link; otherwise common.ensure_org with legal_form_norm (a name match is a flagged name_fuzzy link for review).
- Skipped: natural persons / sole traders (Rechtsform Einzelunternehmen/GbR or a person-shaped name); protected Träger entirely (name matches PROTECTED_RE / is_protected, the matched org is a protected Träger, or the Zuwendungsverzeichnis shows the Träger receiving money for a Frauenhaus / Schutzwohnung, column funding_mv_zuwendung.schutzunterkunft). Counselling against domestic violence alone does not make a Träger protected.
- Held back: 3 new orgs whose names verify G7 reads as a person's (DLRG-Jugend MV, Evangelische Jugend Pommern, Evangelische Jugend Mecklenburg; no register stated). Proposed for the Lead: add "jugend" to ORGWORD_RE in verify.py, then they can be admitted.
- Officers: governance roles only (Vorstand, Geschäftsführung, Präsidium, Aufsichtsrat, Kuratorium and similar) into org_person; quote = "Name Funktion" as on the page; stand = retrieval date; dedup on (org_id, name_norm, lower(funktion)). Officer lists longer than one page are counted, not followed (0 on this run).
- Split with Institutions & Media: annual-report PDFs and Verband Gremien pages are theirs and are not parsed here.
