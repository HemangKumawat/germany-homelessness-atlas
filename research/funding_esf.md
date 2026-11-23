# funding_esf: ESF Plus "Liste der Vorhaben" of the Länder

Built 2026-11-23 (Lead decision: ESF+ Länder lists facts only, rf=0; Berlin rows deduped against ZUWDB).

## Lists and access
| Land | list page -> file | period | rows scanned | robots |
|---|---|---|---|---|
| NI | europa-fuer-niedersachsen.niedersachsen.de liste-der-vorhaben-152610 -> Liste_der_Vorhaben_ESF_Stand_31.01.2026.xlsx | 2021-2027 | 873 | allowed |
| BY | esf.bayern.de/esf-bayern/zahlen/ -> liste_der_vorhaben.xlsx (Stand 01.06.2026) | 2021-2027 | 3,042 | allowed |
| NW | mags.nrw/esf-2021-2027-antrag -> esf_2021-2027_liste_der_vorhaben.xlsx | 2021-2027 | 31,354 | allowed |
| TH | esf-thueringen.de/liste-der-vorhaben-1 -> 04_Liste_der_Vorhaben_31.08.2026_final.xlsx | 2021-2027 | 6,188 | allowed |
| RP | esf.rlp.de/service/liste-der-vorhaben -> Liste_der_Vorhaben__Stand_31.08.2026_.xlsx | 2021-2027 | 5,772 | allowed |
| BE | berlin.de ESF artikel.1215438 -> 20260731_liste_der_vorhaben.xlsx | 2021-2027 | 417 | allowed |
| BB | esf.brandenburg.de projekte-in-brandenburg -> Liste_der_Vorhaben_20251231.698520.xlsx | **2014-2020** Gesamtliste | 8,649 | allowed |

- The file is found on the list page (same-host links only). The BB 2021-2027 list sits on mais2red.lvnbb.de
  (robots-disallowed) and is never requested; what esf.brandenburg.de serves is the 2014-2020 list.
- robots.txt of every host is read fresh in each run before any other request, also when the file is in the disk
  cache; then max(crawl-delay, 1 s) per host.
- Not read: HH and ST (connection reset), BW (no XLSX), HB (robots 403), federal list (robots).
- Licence: no list page states one. Recorded as "no licence stated; Art. 49(3) Reg. (EU) 2021/1060" (BB:
  Art. 115(2) Reg. (EU) 1303/2013), plus the page's own Art. 49 sentence where it has one (BY, TH). Facts only,
  redistribute_fulltext=0.

## Amounts
- award.betrag = the total (eligible) cost of the operation exactly as the list states it (NI "Gesamtkosten des
  Vorhabens", BY "Gesamtbetrag der förderfähigen Ausgabe", NW "Gesamtkosten", TH/RP "Gesamtkosten des Vorhabens",
  BE "zum Stichtag bewilligte förderfähige Gesamtkosten", BB "Gesamtbetrag der förderfähigen Ausgaben").
- The EU contribution is stored as given in funding_esf_vorhaben.eu_beitrag (only NI and BE state it); BY, NW,
  TH, RP and BB state only the co-financing rate (kofi_satz, text as given; never multiplied out). The award
  locator says which column is cited and whether an EU amount is stated.

## Filter (adjustments to the Berlin/Hamburg filter)
- core: funding_manual.classify on the operation title (BZ_CORE + CORE_EXTRA, incl. "Housing-First").
- adjacent (new): no core term in the title, but the description names homeless people as the target group
  (TARGET_RE: "wohnungslose/obdachlose ... Menschen|Frauen|Männer|Personen|Familien|Mütter|EU-Bürger|EU-Migrant",
  "Menschen ohne Obdach/Wohnung") and no refugee context (REFUGEE_RE). Reason: ESF descriptions are long free text,
  so a keyword anywhere is too weak; a named target group is not.
- Not used: the adjacent-only vocabulary (Suppenküche, Streetwork ...) that Berlin/Hamburg accept from a social
  authority; ESF lists name no granting authority.
- Excluded by this rule in Berlin: spok "Sport und Integration" (homeless refugees: refugee context) and Stiftung
  SPI "Miro nevo drom" ("Wohnungslosigkeit" as one of several problems, no target group).
- Result outside Berlin: 0 hits in NI, BY, NW, TH, RP and BB (same as the survey).

## Berlin dedupe against the Zuwendungsdatenbank
Rule: a kept Berlin row is a duplicate of a ZUWDB award (funding_traeger, foerderart zuwendung) when the recipient
matches (name_norm, or the same org, or the same first two name tokens) AND the purpose matches (title tokens equal
or Jaccard >= 0.6) AND first the amount (+-1 EUR; ZUWDB rounds to euros) or else a ZUWDB Haushaltsjahr inside the
ESF period. Duplicates are not written as awards; they stay in funding_esf_vorhaben (status dup_zuwdb, zuwdb_award_id).
Dropped on the scratch run (5):
- row 350 ARBEIT und LEBEN Berlin-Brandenburg gGmbH, Integrationspfade für wohnungslose EU-Migrant*innen (47,423.81) = ZUWDB 8066
- row 356 BETA gGmbH, Solidarisch gegen Obdachlosigkeit im Bezirk Pankow (45,866.72) = ZUWDB 22967
- row 385 Unionhilfswerk Soziale Dienste gGmbH, Lebensbedingungen langjährig obdachloser Menschen (24,948.00) = ZUWDB 148691
- row 401 GEBEWO -Soziale Dienste- Berlin gGmbH, Integrationspfade (298,751.25) = ZUWDB 63932
- row 419 BETA gGmbH, Solidarisch gegen Obdachlosigkeit in Pankow (294,509.49) = ZUWDB 22973

## Held back until the Lead's G9 numeric-cell fix
The Berlin file stores some costs as binary floats (19980.240000000002). G9 can't find 19980.24 as a token, so
such rows are held (status held_g9_float, no award): Die Wille gGmbH (19,980.24), My Way Soziale Dienste gGmbH
(30,517.20), agens Arbeitsmarktservice gGmbH (299,839.96). Release: cfg esf_float_ok=True once the fix is on lead/core.

## Written
1 award: Verein für Berliner Stadtmission, "Nachhaltige Integration Wohnungs- und Obddachloser in Schöneberg"
(sic), 2025, total cost EUR 46,704.84 (EU contribution EUR 17,939.04), adjacent, linked by name (flagged).

## Later (low priority, not built): München
Lead rule: only organisation recipients whose full name can be resolved from the document itself;
abbreviations that no source resolves are skipped; budget figures are not awards, at most a metric with is_est=1
labelled "Haushaltsansatz".

## 2026-11-23 rebase on lead/core fcfbfa3 (funding worker)

- `esf_float_ok` now defaults to True: the 3 previously held ESF Berlin rows (Die Wille, My Way, agens) are kept;
  ESF BE now has 4 awards (with Stadtmission), EUR 397,042.24 total cost; 5 ZUWDB duplicates still dropped.
- Units: every funding award locator now names basis and period next to the currency, e.g.
  "EUR, Zuwendung 2024, bewilligt" (Berlin ZUWDB), "EUR, award-time contract value" (TED),
  "EUR, Zuwendungssumme bewilligt, Zeitraum ..." (HH), "EUR, Höhe der Zuwendung 2020, Bewilligungszeitraum ..." (MV),
  "EUR, Zuwendungssumme bewilligt, Jahr Maßnahmebeginn ..." (HB), "EUR, Höhe der Zuwendung, Zuwendungsübersicht 2024" (RLP),
  "EUR, total eligible cost, operation period ..." (ESF). `award.currency` stays the 3-letter code (schema CHECK).
- Org resolution: new `funding_traeger.ensure_org_xland` (register/USt, same Land, then a unique exact/family/single
  match in any Land) before creating a Land-scoped org; used by funding_manual, funding_hamburg, funding_mv (LAGuS), funding_esf.
- orglink.sync (Lead core, proposed): an award links as `origin` when its org row was created by the same domain and
  the same source system under the exact org key (name_norm + legal form + Land). Flagged links on the scratch build: 91 -> 32.
