# Fuzzy org-link review

Lead review, 2026-11-23 (lead run #29, `lead_org_resolution`). Source: the 69 flagged `name_fuzzy` rows in `org_link`
listed in reports/join_gaps.md before this run, plus its similar-name duplicate candidates. Every verdict rests on stored data and archived
source documents only (TED notice XML, Impressum pages, Berlin Zuwendungsdatenbank and Lobbyregister records in
data/raw); nothing was fetched. Accepted evidence: the same register number, LEI, USt-IdNr or QID; the same eForms CompanyID;
the same street and PLZ in the source documents; or an explicit statement. A name and a town alone are never enough.
Organisation-level data only: street names are not repeated here.

Decisions are applied from docs/link_reviews.tsv:
- **confirm**: method `manual` (0.95) or `origin` (1.0) for self-links, flagged 0, reviewed 1, and the evidence goes in the note.
- **reject**: the link is removed and the award is left unlinked.
- **unsure**: untouched, so it stays flagged.

## Summary

| verdict | links |
|---|---|
| confirm | 54 (award 32, Impressum 10, org_name 12) |
| reject | 0 |
| unsure (stay flagged) | 15 (all award links) |
| merges (docs/org_merges.tsv) | 0 |

## Links

| link id | kind | name in record | linked org | Land | evidence | verdict |
|---|---|---|---|---|---|---|
| 1614 | award | Verein für Berliner Stadtmission | #14 Berliner Stadtmission e. V. | BE | notice gives only 'Verein für Berliner Stadtmission, Berlin'; the name is the legal name per the org's Impressum, but there is no address or register in the notice | **unsure** |
| 1515 | award | GEBEWO pro GmbH | #47 GEBEWO pro gGmbH | BE | notice gives only 'GEBEWO pro GmbH, Berlin' (no 'g', no address, no register) | **unsure** |
| 1613 | award | Stiftung zur Förderung sozialer Dienste (FSD-Stiftung) | #98 Stiftung zur Förderung sozialer Dienste (FSD-Stiftung) | BE | notice gives only name and 'Berlin'; the org's ZUWDB record has a street, the notice has none | **unsure** |
| 1474 | award | five walls GmbH | #115 five walls GmbH | BY | same street and PLZ 82166 Gräfelfing for the contractor in this notice and in the notice(s) the org was built from | **confirm** |
| 1517 | award | five walls GmbH | #115 five walls GmbH | BY | same street and PLZ 82166 Gräfelfing for the contractor in this notice and in the notice(s) the org was built from | **confirm** |
| 1519 | award | five walls GmbH | #115 five walls GmbH | BY | same street and PLZ 82166 Gräfelfing for the contractor in this notice and in the notice(s) the org was built from | **confirm** |
| 1520 | award | five walls GmbH | #115 five walls GmbH | BY | same street and PLZ 82166 Gräfelfing for the contractor in this notice and in the notice(s) the org was built from | **confirm** |
| 1523 | award | five walls GmbH | #115 five walls GmbH | BY | same street and PLZ 82166 Gräfelfing for the contractor in this notice and in the notice(s) the org was built from | **confirm** |
| 1586 | award | five walls GmbH | #115 five walls GmbH | BY | notice gives only 'five walls GmbH, München' (no street, no id); it states five walls GmbH was split off from PulsM GmbH and registered 05.10.2021, but nothing ties that to #115's Gräfelfing seat or USt-IdNr | **unsure** |
| 1587 | award | five walls GmbH | #115 five walls GmbH | BY | notice gives only 'five walls GmbH, München' (no street, no id); it states five walls GmbH was split off from PulsM GmbH and registered 05.10.2021, but nothing ties that to #115's Gräfelfing seat or USt-IdNr | **unsure** |
| 1588 | award | five walls GmbH | #115 five walls GmbH | BY | notice gives only 'five walls GmbH, München' (no street, no id); it states five walls GmbH was split off from PulsM GmbH and registered 05.10.2021, but nothing ties that to #115's Gräfelfing seat or USt-IdNr | **unsure** |
| 1589 | award | five walls GmbH | #115 five walls GmbH | BY | notice gives only 'five walls GmbH, München' (no street, no id); it states five walls GmbH was split off from PulsM GmbH and registered 05.10.2021, but nothing ties that to #115's Gräfelfing seat or USt-IdNr | **unsure** |
| 1590 | award | five walls GmbH | #115 five walls GmbH | BY | notice gives only 'five walls GmbH, München' (no street, no id); it states five walls GmbH was split off from PulsM GmbH and registered 05.10.2021, but nothing ties that to #115's Gräfelfing seat or USt-IdNr | **unsure** |
| 1591 | award | five walls GmbH | #115 five walls GmbH | BY | notice gives only 'five walls GmbH, München' (no street, no id); it states five walls GmbH was split off from PulsM GmbH and registered 05.10.2021, but nothing ties that to #115's Gräfelfing seat or USt-IdNr | **unsure** |
| 1592 | award | five walls GmbH | #115 five walls GmbH | BY | notice gives only 'five walls GmbH, München' (no street, no id); it states five walls GmbH was split off from PulsM GmbH and registered 05.10.2021, but nothing ties that to #115's Gräfelfing seat or USt-IdNr | **unsure** |
| 1492 | award | European Homecare GmbH | #116 European Homecare GmbH | NW | same street and PLZ 45136 Essen for the contractor in this notice and in the notice(s) the org was built from | **confirm** |
| 1548 | award | European Homecare GmbH | #116 European Homecare GmbH | NW | same street and PLZ 45136 Essen for the contractor in this notice and in the notice(s) the org was built from | **confirm** |
| 1559 | award | European Homecare GmbH | #116 European Homecare GmbH | NW | old-format notice gives only name and town (Essen); no street, register or USt-IdNr to compare | **unsure** |
| 1563 | award | European Homecare GmbH | #116 European Homecare GmbH | NW | same street and PLZ 45136 Essen for the contractor in this notice and in the notice(s) the org was built from | **confirm** |
| 1567 | award | European Homecare GmbH | #116 European Homecare GmbH | NW | same street and PLZ 45136 Essen for the contractor in this notice and in the notice(s) the org was built from | **confirm** |
| 1569 | award | European Homecare GmbH | #116 European Homecare GmbH | NW | old-format notice gives only name and town (Essen); no street, register or USt-IdNr to compare | **unsure** |
| 1574 | award | European Homecare GmbH | #116 European Homecare GmbH | NW | old-format notice gives only name and town (Essen); no street, register or USt-IdNr to compare | **unsure** |
| 1650 | award | European Homecare GmbH | #116 European Homecare GmbH | NW | same street and PLZ 45136 Essen for the contractor in this notice and in the notice(s) the org was built from | **confirm** |
| 1510 | award | AWO Hamburg Seniorenwohnen&Pflege gGmbH | #117 AWO Hamburg Seniorenwohnen&Pflege gGmbH | HH | same eForms CompanyID (e20cd33e…) and same street and PLZ 21035 in both notices | **confirm** |
| 1551 | award | AWO Hamburg Seniorenwohnen&Pflege gGmbH | #117 AWO Hamburg Seniorenwohnen&Pflege gGmbH | HH | same eForms CompanyID (e20cd33e…) and same street and PLZ 21035 in both notices | **confirm** |
| 1593 | award | Tannenhof Berlin-Brandenburg gGmbH | #130 Tannenhof Berlin-Brandenburg gGmbH | BE | same street and PLZ 10825 Berlin for the contractor in this notice and in the notice(s) the org was built from | **confirm** |
| 1540 | award | Caritasverband für den Bezirk Hochtaunus e. V. | #140 Caritasverband für den Bezirk Hochtaunus e. V. | HE | same street and PLZ 61348 Bad Homburg for the contractor in this notice and in the notice(s) the org was built from | **confirm** |
| 1538 | award | DRK Betreuungsdienste Westfalen-Lippe gGmbH | #141 DRK Betreuungsdienste Westfalen-Lippe gGmbH | NW | same street and PLZ 48151 Münster for the contractor in this notice and in the notice(s) the org was built from | **confirm** |
| 1539 | award | DRK Betreuungsdienste Westfalen-Lippe gGmbH | #141 DRK Betreuungsdienste Westfalen-Lippe gGmbH | NW | same street and PLZ 48151 Münster for the contractor in this notice and in the notice(s) the org was built from | **confirm** |
| 1619 | award | DRK Betreuungsdienste Westfalen-Lippe gGmbH | #141 DRK Betreuungsdienste Westfalen-Lippe gGmbH | NW | same street and PLZ 48151 Münster for the contractor in this notice and in the notice(s) the org was built from | **confirm** |
| 1629 | award | DRK Betreuungsdienste Westfalen-Lippe gGmbH | #141 DRK Betreuungsdienste Westfalen-Lippe gGmbH | NW | same street and PLZ 48151 Münster for the contractor in this notice and in the notice(s) the org was built from | **confirm** |
| 1630 | award | DRK Betreuungsdienste Westfalen-Lippe gGmbH | #141 DRK Betreuungsdienste Westfalen-Lippe gGmbH | NW | same street and PLZ 48151 Münster for the contractor in this notice and in the notice(s) the org was built from | **confirm** |
| 1664 | award | Deutsches Rotes Kreuz Kreisverband Hamburg-Harburg e.V. | #154 Deutsches Rotes Kreuz Kreisverband Hamburg-Harburg e.V. | HH | same eForms CompanyID (2d361aa9…) and same PLZ 21073 in this notice and in the org's origin notice 234152-2024 | **confirm** |
| 1676 | award | Mook Wat e.V. | #163 Mook wat e.V. | HH | notice address (street, PLZ 22297) = address on the org's Impressum (mookwat.de), which also gives the org's register VR 10074 AG Hamburg | **confirm** |
| 1678 | award | jhj Hamburg e.V. | #164 jhj Hamburg e.V | HH | notice gives a street address, but the org's sources (TED 244267-2022) give only 'Hamburg' and no Impressum is held; nothing to compare | **unsure** |
| 1675 | award | Jugendhilfe e.V. | #165 Jugendhilfe e.V. | HH | notice address (street, PLZ 20097) = address on the org's Impressum (jugendhilfe.de), which also gives the org's register VR 5922 AG Hamburg | **confirm** |
| 1677 | award | Lawaetz wohnen & leben gGmbH | #166 Lawaetz-wohnen & leben gGmbH | HH | notice address (street, PLZ 20357) = address on the org's Impressum (lawaetz-ggmbh.de), which also gives the org's register HRB 138951 AG Hamburg | **confirm** |
| 1617 | award | AWO Unterbezirk Ruhr-Mitte | #170 AWO Unterbezirk Ruhr-Mitte | NW | same street and PLZ 44809 Bochum for the contractor in this notice and in the notice(s) the org was built from | **confirm** |
| 1599 | award | Hotel Ahorn | #194 hotel Ahorn | BY | notice gives only 'Hotel Ahorn, München'; the org's notice has a street but this one has none | **unsure** |
| 1640 | award | Forward-Soziale Dienste GmbH | #199 Forward-Soziale Dienste GmbH | NI | notice prints HRB 202174 = the org's register HRB 202174 (AG Stadthagen; court not printed in the notice), and same street and PLZ 31542 | **confirm** |
| 1655 | award | Forward-Soziale Dienste GmbH | #199 Forward-Soziale Dienste GmbH | NI | notice prints HRB 202174 = the org's register HRB 202174 (AG Stadthagen; court not printed in the notice), and same street and PLZ 31542 | **confirm** |
| 1621 | award | Hero Services gGmbH | #205 Hero Services gGmbH | BE | same street and PLZ 12689 Berlin for the contractor in this notice and in the notice(s) the org was built from; same website herozukunft.de | **confirm** |
| 1624 | award | Hero Services gGmbH | #205 Hero Services gGmbH | BE | same street and PLZ 12689 Berlin for the contractor in this notice and in the notice(s) the org was built from; same website herozukunft.de | **confirm** |
| 1628 | award | Lectus München GmbH | #208 Lectus München GmbH | BY | same street and PLZ 80807 München for the contractor in this notice and in the notice(s) the org was built from (1628 also has a second, misspelt street line) | **confirm** |
| 1631 | award | Lectus München GmbH | #208 Lectus München GmbH | BY | same street and PLZ 80807 München for the contractor in this notice and in the notice(s) the org was built from (1628 also has a second, misspelt street line) | **confirm** |
| 1637 | award | Thomas Wolter GmbH | #225 Thomas Wolter GmbH | SN | same street and PLZ 01097 Dresden for the contractor in this notice and in the notice(s) the org was built from; the org's notice prints USt-IdNr DE247465106 | **confirm** |
| 1612 | award | Malteser Hilfsdienst e.V. | #682 Malteser Hilfsdienst e.V. | BW | identity: org #682 was created from this same award record (TED 624927-2022, source #1008); the fuzzy score comes only from #682's name_norm carrying 'EV'. Not evidence for #682 = #658 (no merge) | **confirm** |
| 2102 | impressum | Arbeiterwohlfahrt Berlin Spree-Wuhle e. V. | #7 Arbeiterwohlfahrt Berlin Spree-Wuhle e. V. | BE | Berlin Zuwendungsdatenbank 'Registrierungsnummer' vr_021507 = register number VR 21507 B on the org's own Impressum (all Berlin Vereins- and Handelsregister are kept at AG Charlottenburg, suffix B) | **confirm** |
| 2097 | impressum | Verein für Berliner Stadtmission | #14 Berliner Stadtmission e. V. | BE | Berlin Zuwendungsdatenbank 'Registrierungsnummer' vr_024148 = register number VR 24148 B on the org's own Impressum (all Berlin Vereins- and Handelsregister are kept at AG Charlottenburg, suffix B); the org's ZUWDB street and PLZ 10557 are on the page too; the Impressum gives the legal name 'Verein für Berliner Stadtmission' | **confirm** |
| 2104 | impressum | Bundesarbeitsgemeinschaft Wohnungslosenhilfe e. V. | #19 Bundesarbeitsgemeinschaft Wohnungslosenhilfe e. V. | BE | same address in both source documents: the org's ZUWDB street and PLZ 13509 are on the Impressum (which prints VR 35127 B AG Charlottenburg) | **confirm** |
| 2100 | impressum | Gangway e. V. | #45 Gangway | BE | Berlin Zuwendungsdatenbank 'Registrierungsnummer' vr_010473 = register number VR 10473 B on the org's own Impressum (all Berlin Vereins- and Handelsregister are kept at AG Charlottenburg, suffix B); the org's ZUWDB street and PLZ 10117 are on the page too | **confirm** |
| 2098 | impressum | GEBEWO pro gGmbH | #47 GEBEWO pro gGmbH | BE | Berlin Zuwendungsdatenbank 'Registrierungsnummer' hrb_095854 = register number HRB 95854 (printed under 'GEBEWO pro gGmbH') on the org's own Impressum (all Berlin Vereins- and Handelsregister are kept at AG Charlottenburg, suffix B) | **confirm** |
| 2099 | impressum | GEBEWO -Soziale Dienste- Berlin gGmbH | #48 GEBEWO -Soziale Dienste- Berlin gemeinnützige GmbH | BE | Berlin Zuwendungsdatenbank 'Registrierungsnummer' hrb_054310 = register number HRB 54310 (printed under 'GEBEWO -Soziale Dienste- Berlin gGmbH') on the org's own Impressum (all Berlin Vereins- and Handelsregister are kept at AG Charlottenburg, suffix B) | **confirm** |
| 2101 | impressum | Sozialdienst katholischer Frauen e. V. Berlin | #96 Sozialdienst katholischer Frauen e. V. Berlin | BE | Berlin Zuwendungsdatenbank 'Registrierungsnummer' vr_000275 = register number VR 275 B on the org's own Impressum (all Berlin Vereins- and Handelsregister are kept at AG Charlottenburg, suffix B) | **confirm** |
| 2103 | impressum | Deutscher Caritasverband e. V. | #650 Deutscher Caritasverband e.V. | DE | same Impressum page states VR 570 at AG Freiburg (impressum_register link), the register of #650 | **confirm** |
| 2106 | impressum | Diakonie Deutschland, Evangelisches Werk für Diakonie und Entwicklung e.V. | #660 Diakonie Deutschland, Evangelisches Werk für Diakonie und Entwicklung e.V. | - | same address in both source documents: Impressum and Lobbyregister R001639 give the same street and PLZ 10115 Berlin; Impressum also prints Vereinsregister 31924 B (not yet on #660) | **confirm** |
| 2105 | impressum | AWO Bundesverband e.V. | #662 AWO Bundesverband e.V. | - | same Impressum page also yields VR 29346 B AG Charlottenburg (impressum_register link), which is the register of #662 (Lobbyregister R002224) | **confirm** |
| 2084 | org_name | Diakonie Deutschland - Evangelischer Bundesverband | #649 Diakonie Deutschland - Evangelischer Bundesverband | DE | identity: org #649 was created from this same record (same source #1975, identical name and Land); not a cross-source match | **confirm** |
| 2085 | org_name | Deutscher Caritasverband e.V. | #650 Deutscher Caritasverband e.V. | DE | identity: org #650 was created from this same record (same source #1975, identical name and Land); not a cross-source match | **confirm** |
| 2086 | org_name | Der PARITÄTISCHE Gesamtverband | #651 Der PARITÄTISCHE Gesamtverband | DE | identity: org #651 was created from this same record (same source #1975, identical name and Land); not a cross-source match | **confirm** |
| 2087 | org_name | Die Arbeiterwohlfahrt | #652 Die Arbeiterwohlfahrt | DE | identity: org #652 was created from this same record (same source #1975, identical name and Land); not a cross-source match | **confirm** |
| 2088 | org_name | Evangelischer Bundesfachverband Existenzsicherung und Teilhabe | #653 Evangelischer Bundesfachverband Existenzsicherung und Teilhabe | DE | identity: org #653 was created from this same record (same source #1975, identical name and Land); not a cross-source match | **confirm** |
| 2089 | org_name | Katholische Bundesarbeitsgemeinschaft Wohnungslosenhilfe | #654 Katholische Bundesarbeitsgemeinschaft Wohnungslosenhilfe | DE | identity: org #654 was created from this same record (same source #1975, identical name and Land); not a cross-source match | **confirm** |
| 2090 | org_name | Koordination Wohnungslosenhilfe Nordbayern | #676 Koordination Wohnungslosenhilfe Nordbayern | BY | identity: org #676 was created from this same record (same source #2208, identical name and Land); not a cross-source match | **confirm** |
| 2091 | org_name | Koordination Wohnungslosenhilfe Südbayern | #677 Koordination Wohnungslosenhilfe Südbayern | BY | identity: org #677 was created from this same record (same source #2208, identical name and Land); not a cross-source match | **confirm** |
| 2092 | org_name | Arbeitskreis Wohnungsnot | #678 Arbeitskreis Wohnungsnot | BE | identity: org #678 was created from this same record (same source #2209, identical name and Land); not a cross-source match | **confirm** |
| 2093 | org_name | Evangelischer Fachverband Wohnungslosenhilfe | #679 Evangelischer Fachverband Wohnungslosenhilfe | NW | identity: org #679 was created from this same record (same source #2210, identical name and Land); not a cross-source match | **confirm** |
| 2094 | org_name | Fachverband Evangelische Wohnungsnotfallhilfe und Straffälligenhilfe | #680 Fachverband Evangelische Wohnungsnotfallhilfe und Straffälligenhilfe | BY | identity: org #680 was created from this same record (same source #2211, identical name and Land); not a cross-source match | **confirm** |
| 2095 | org_name | Evangelischer Fachverband Wohnungslosenhilfe und Existenzsicherung e.V. | #681 Evangelischer Fachverband Wohnungslosenhilfe und Existenzsicherung e.V. | NI | identity: org #681 was created from this same record (same source #2212, identical name and Land); not a cross-source match | **confirm** |

## Similar-name duplicate candidates (reports/join_gaps.md): no merges

| orgs | Land | evidence | verdict |
|---|---|---|---|
| #236 Meglingerstraße Appartement-Haus GmbH / #237 Reisingerstraße Appartement- Haus GmbH | BY | two firms named in the same TED notice 794864-2025, each with its own name; they share a management address, but a shared address doesn't make one firm | reject (distinct entities) |
| #676 Koordination Wohnungslosenhilfe Nordbayern / #677 … Südbayern | BY | two regional coordination offices named side by side on the same source page | reject (distinct entities) |
| #157 MW Malteser Werke gGmbH / #219 Malteser Werke gGmbH | NW | same Köln street and PLZ 51103, but that is the Malteser group seat shared by several legal entities; #219 holds HRB 31629 AG Köln and #157's notice prints only an eForms CompanyID | unsure |
| #206 Heinzelmännchen Gebäudereinigungs GmbH / #215 Heinzelmännchen Gebäudereinigung GmbH | NW | both notices give only the name and Verl; #215 holds HRB 491 (AG Krefeld), #206 has nothing to compare | unsure |
| Johanniter-Unfall-Hilfe #62 (BE, ZUWDB vr_017661, Lobbyregister R002223) / #151 (SH, Lübeck) / #222 (NW, Neuss, USt-IdNr DE122124138) | BE/SH/NW | no shared register, USt-IdNr or address; whether the regional units are the one national e.V. is not stated in any source we hold | unsure |
| Malteser Hilfsdienst #145 gGmbH (HE, Limburg) / #162 gGmbH (BW, Stuttgart, HRB 26997 AG Köln) / #658 e.V. (Lobbyregister, VR 4726 AG Köln) / #682 e.V. (TED 624927-2022, Freiburg) | HE/BW/-/BW | #682 vs #658: TED 624927-2022 prints only "Malteser Hilfsdienst e.V., Freiburg i. Br." with no register, so no source we hold proves #682 is VR 4726; #145 vs #162 have different seats and #145 has no register | unsure, not merged |

## Systematic findings

1. **Self-links written as name matches (institutions_media, 12 links).** When the module creates an org from a record,
   it then links that same record to that org as `name_fuzzy` 0.7 instead of `origin`. Bounce.
2. **An Impressum name link is flagged even when the same page proves the org (funding_officers, 10 links).**
   - On the AWO Bundesverband and Caritas pages, the same page's register line already links to the same org by register number.
   - On the Berlin Impressum pages, VR/HRB numbers aren't compared with the org's Zuwendungsdatenbank number.
   - The parser also misses "Vereinsregister 31924 B" (Diakonie), so #660 still has no register.
   - Bounce.
3. **Some eForms CompanyID values aren't company ids (funding_traeger).** Awards in TED 660611-2025 (Hero Services) store
   `empfaenger_id` = "2" and "6", and the notice for #199 prints "2". These are probably lot or party sequence numbers, not register ids. Bounce: ignore CompanyIDs that don't look like an id.
4. **#682's name_norm is "MALTESER HILFSDIENST EV" rather than `common.name_norm`** (funding_traeger), so `sync()` didn't
   see it as the origin record of its own award. The cause is `UNIQUE(name_norm, land)`: name_norm drops the legal
   form, so an e.V. and a gGmbH with the same name in the same Land collide. Bounce, and it needs a schema decision.
5. **Lead fixes in this run**:
   - `orglink.legal_kind` read "Ev." (evangelisch) as e.V. That made the parish award 351 (Kirchengemeinde zum Guten Hirten, KdöR, linked to #33 by ZUWDB id) look like a Fixpunkt-type legal-form mismatch. Fixed, with a test.
   - The scan of all 847 awards for an award attached to a different legal form (the Fixpunkt pattern) now finds **0**.
   - `orglink.link()` no longer lets a module re-run downgrade a Lead-reviewed link to `name_fuzzy` for the same org.
   - A reviewed `manual` award link that moves to another org is flagged again instead of keeping `manual`.
   - Tests: tests/test_link_reviews.py.
6. **Name + town only (8 of the 15 unsure: European Homecare x3, jhj, Hotel Ahorn, FSD, Stadtmission, GEBEWO pro).** Under § 30 HGB and § 57 Abs. 2 BGB, a firm or association name must be
   distinct at its registered seat. An identical full legal name in the same town would therefore support a confirm.
   That is a policy choice I have not made: these stay unsure.

## Lead review 2026-11-23 (funding_hamburg run #35): held for Hemang's review, nothing merged

Verdict for all items below: **unsure**: not merged and still flagged. The only evidence is the name and Land in two documents.
Per the rules above, that is not enough: neither the Transparenzportal Hamburg XLSX nor the TED notice gives a register
number or USt-IdNr.

### Spelling pairs (both orgs created by funding_hamburg from the same XLSX, source 2469)
- [ ] **Streetlife.** Org 710 is "Streetlife e.V. Verein für Straßensozialarbeit in" (truncated in the file; 2 grants, EUR 355,389.85).
  Org 716 is "STREETLIFE - Verein für Straßensozialarbeit in Hamburg e.V." (10 grants, EUR 2,003,381.56). Same purpose words and same Land.
  The XLSX spells the recipient two ways. Probably one Verein, but there's no register number to prove it.
- [ ] **Bodelschwingh.** Org 703 is "Ev.Stiftung Bodelschwingh-Gemeinde" (1 grant, EUR 221,154.42).
  Org 709 is "Evangelische Stiftung der Bodelschwingh- Gemeinde" (4 grants, EUR 356,808.31). Same legal form (Stiftung) and Land HH.
  It's a spelling variant in the file, with no register number.

### name_fuzzy links to org 154 "Deutsches Rotes Kreuz Kreisverband Hamburg-Harburg e.V." (worker's note said org 136; the ids shifted on the live DB)
Org 154 was created from TED notice 234152-2024 (source 781, winner name). The 5 Hamburg grants carry the same name
and legal form, but in a different source, so ensure_org linked them as name_fuzzy at 0.95 and flagged them:
- [ ] DE-HH-ZUW:ZUW-2025-03341, EUR 671,000.00: Betrieb der DRK-Tagesaufenthalts- und Übernachtungsstätte für obdachlose Menschen mit Hund "Harburg-Huus"
- [ ] DE-HH-ZUW:SF-105039, EUR 308,546.13: same purpose; the recipient is spelt "Deutsches Rotes Kreuz, Kreisverband Hamburg-Harburg e.V."
- [ ] DE-HH-ZUW:ZUW-2023-01549, EUR 378,968.05: same purpose
- [ ] DE-HH-ZUW:ZUW-2024-01700, EUR 399,135.10: same purpose
- [ ] DE-HH-ZUW:SF-098036, EUR 4,425.68: "Ehrenamtliche gemeinsam für und mit jungen Obdachlosen" (comma spelling)

To confirm any of these, add a line to docs/link_reviews.tsv with the evidence, for example a VR number from the
Hamburg Vereinsregister or the DRK-Landesverband's member list.
