# Institutions and media

Four in-memory dry-runs, no `data/atlas.db`. The first, on 20 November 2026, ingested Bundestag DIP papers, Wikidata facilities and Commons media. The second, on 21 November 2026 around 01:10 Europe/Berlin (UTC+1), was `--dry-run --landtag-only` and added official Landtag papers. The third, around 01:28 Europe/Berlin the same night, was a full `--dry-run` after the Lead's licence-gate fixes: every `source.license` is non-empty, Commons files carry licence short name, licence URL and attribution, Wikidata rows are `CC0 1.0` citing the licensing page (HTTP 200), and protected facilities/media drop coordinates and geotags. The fourth, on 21 November 2026 around 01:50 Europe/Berlin (UTC+1), was `--dry-run --rechnungshof-only` and added official Bundesrechnungshof and Landesrechnungshof audit reports plus cited euro amounts in `metric`.

First-run table counts (DIP, Wikidata, Commons):

| Table | Rows |
| --- | ---: |
| doc | 81 |
| institutions_media_drucksache | 81 |
| facility | 442 |
| institutions_media_facility | 442 |
| media | 127 |
| source | 650 |

`facility.budget` and `facility.annual_cost_per_bed` are NULL on all 442 rows. No `frauenhaus` or `protected_shelter` row was stored. `doc` + `facility` + `media` = 650, which is the `rows` value returned by `run`.

Landtag-only dry-run counts (DIP, Wikidata and Commons skipped):

| Table | Rows |
| --- | ---: |
| doc | 285 |
| institutions_media_drucksache | 285 |
| source | 160 |
| facility / media | 0 |

Of the 285 stored papers, 284 are Berlin PARDOK and 1 is Bayern official RSS. `source` is 160 because 125 Berlin Schriftliche Anfrage/Antwort pairs share one official PDF (159 unique Berlin PDFs + the Bayern catalog URL). `doc.url` appends `#<dip_id>` so both members of a pair keep their own date and type. A full `run` after merge will add these Landtag rows on top of the first-slice DIP/facility/media counts.

Full dry-run after the licence-gate fixes (21 November 2026, about 01:28 Europe/Berlin), still in-memory:

| Table | Rows |
| --- | ---: |
| doc | 366 |
| institutions_media_drucksache | 366 (81 DIP + 284 BE + 1 BY) |
| facility | 442 |
| media | 127 |
| source | 810 |
| source with NULL licence | 0 |
| source with a TODO licence | 82 (81 DIP + 1 Bayern RSS) |

`protected_with_location` was 0. Commons: 127 kept, 0 skipped for licence, 4 skipped as not image/video (audio or PDF). Each stored Commons `source` row has `license`, `license_url` and `attribution`. Wikidata: 442 sources, `license=CC0 1.0`, `license_url=https://www.wikidata.org/wiki/Wikidata:Licensing` (HTTP 200). Berlin PARDOK sources use `dl-de/by-2-0` with attribution "Parlamentsdokumentation, Abgeordnetenhaus von Berlin" (159 unique PDF URLs). DIP rows use a clear TODO string because the official terms page is still a JS shell with no licence sentence.

## Sources

HTTP responses actually received. The DIP API key is the published help-api key (the page says it is valid through the end of May 2027). It was sent only as `Authorization: ApiKey …` and is not copied here.

| URL | Status | What was used |
| --- | --- | --- |
| https://content.dip.bundestag.de/content-api/v1/content/help-api | 200 | Published key. Sentence on the page: "Der zunächst bis Ende Mai 2027 gültige API-Key lautet: …" |
| https://search.dip.bundestag.de/api/v1/openapi.yaml | 200 | `application/yaml`. Confirms `f.titel` is repeatable and that paging continues until `cursor` stops changing. |
| https://dip.bundestag.de/documents/informationsblatt_zur_dip_api.pdf | 206 | `application/pdf`, body starts `%PDF-1.4`. |
| https://dip.bundestag.de/über-dip/hilfe/api | 200 | HTML shell, 2375 bytes. The key used for requests came from the help-api content URL above, not from this shell. |
| https://dip.bundestag.de/über-dip/nutzungsbedingungen | 200 | Same 2375-byte HTML shell. No licence sentence in the HTML. DIP `source.license` is now `TODO: DIP Nutzungsbedingungen pending Lead confirmation`, with this page as `license_url`, until the Lead pins down the terms. |
| https://search.dip.bundestag.de/api/v1/drucksache | 200 | Title search. `numFound` 81, 81 documents, then a follow-up with the returned cursor: same cursor, 0 documents. |
| https://search.dip.bundestag.de/api/v1/drucksache/{id} | 200 | Per-document metadata. This is `source_id` for each Drucksache. |
| https://dip.bundestag.de/drucksache/{id} | 200 | Catalog SPA, 81/81 during the dry-run. Title is not in the HTML. Used as `doc.url` when status is 200. |
| https://dserver.bundestag.de/…pdf | 206 or 404 | Ranged GET. 80 responses were `206 application/pdf` and began with `%PDF`. One was `404 text/html`. |
| https://query.wikidata.org/sparql | 200 | Facility query. 471 bindings. |
| https://www.wikidata.org/w/api.php | 200 | Live labels before the query, and the CC0 sentence from the extract of Wikidata:Licensing. |
| https://www.wikidata.org/wiki/Wikidata:Licensing | 200 | Live page. Facility sources now store `license=CC0 1.0` and this URL as `license_url`. |
| https://www.wikidata.org/wiki/Special:EntityData/{qid}.json | 200 | Per-item source URL for each stored facility. |
| https://commons.wikimedia.org/w/api.php | 200 | File metadata. No file bytes downloaded. |
| https://commons.wikimedia.org/wiki/File:… | 200 | File description page. `media.url` and `media.license` come from the API `descriptionurl` and `LicenseShortName`. |

| https://pardok.parlament-berlin.de/portala/opendata.tt.html | 200 | Official Open Data page. Published API key (stated valid until the end of December 2026). Key sent only as `X-API-Key` and not copied here. |
| https://pardok.parlament-berlin.de/api/v1/openapi.yaml | 200 | `application/yaml`. Confirms `f.titel`, cursor paging, and the `X-API-Key` header. |
| https://pardok.parlament-berlin.de/portala/local/OpenData_Dokumentation.pdf | 206 | `application/pdf`, `%PDF-1.4`. |
| https://pardok.parlament-berlin.de/portala/local/OpenData_Nutzungsbedingungen.pdf | 206 | `application/pdf`. Metadata licence is Datenlizenz Deutschland — Namensnennung — Version 2.0 (`dl-de/by-2-0`). Attribution: "Parlamentsdokumentation, Abgeordnetenhaus von Berlin". Official PDF documents remain amtliche Werke. |
| https://pardok.parlament-berlin.de/api/v1/drucksache | 200 | Title search. `numFound` 284, 3 pages (100+100+84), 284 stored, all `verified_pdf`. |
| https://pardok.parlament-berlin.de/starweb/adis/citat/VT/19/SchrAnfr/S19-27042.pdf | 206 | Sample Berlin PDF, `application/pdf`, body starts `%PDF-1.7`. |
| https://www.parlamentsdokumentation.brandenburg.de/portal/opendata_dokumente.tt.html | 200 | Official ELVIS document export page (the older `/starweb/LBB/ELVIS/OpenData.html` path redirects here). |
| https://www.parlamentsdokumentation.brandenburg.de/opendata/exportWP{1-8}.xml | 200 / 206 | Official XML exports, WP 1–8. WP8 was 14,499,390 bytes, `application/xml`. The path printed in the schema PDF (`/opendata_dokumente/exportWP8.xml`) is a 404; the live links on the official page are `/opendata/exportWP8.xml`. |
| https://www.parlamentsdokumentation.brandenburg.de/portal/local/Dokumentation_BB_XML-Export_Dokumente_v1.1.pdf | 206 | Official XML schema, `application/pdf`. |
| https://www.parlamentsdokumentation.brandenburg.de/starweb/LBB/ELVIS/parladoku/…pdf | 403 | Official `LokURL` values in the XML. HTTP 403 `text/html` from this environment (with and without `Range`, session, or Referer). No BB row was stored. |
| https://www.bayern.landtag.de/parlament/dokumente/rss-feeds/ | 200 | Official RSS index (webangebot3). |
| https://www.bayern.landtag.de/webangebot3/views/rssfeed/rssfeed.xhtml?art=ANFRAGE&titel=Drucksachen+von+Anfragen | 200 | `application/rss+xml`, 538 recent items. |
| https://www.bayern.landtag.de/webangebot3/views/vorgangsmappe/vorgangsmappe.xhtml?gegenstandid=167484 | 200 | Catalog URL for the stored Bayern hit; the server returns `application/pdf` beginning `%PDF-1.6` (480,299 bytes). |
| https://www.buergerschaft-hh.de/parldok | 200 | Official Hamburg ParlDok start page. |
| https://www.buergerschaft-hh.de/parldok/index.rss | 200 | Official recent RSS, 20 items, 0 title-term hits. |
| https://www.landtag.ltsh.de/aktuelles/parlafeed/ | 200 | Official ParlaFeed page with RSS URLs. |
| http://lissh.lvn.ltsh.de/shlt/rss/aborss002.xml and aborss003.xml | 200 during the dry-run on the worktree host; HTTP 500 on a later check from another environment | Recent official feeds. 58 Drucksachen + 24 Kleine Anfragen items during the dry-run, 0 title-term hits. |

Wikidata and Commons are already listed in `docs/SOURCES.md`. No row was appended. Landtag endpoints are documented here rather than as a SOURCES.md append in this slice.

## Method

`run(conn, cfg)` writes four slices (DIP, Wikidata facilities, Commons, Landtag). Each slice is isolated: a 403 or missing key stops that slice and the others continue. `cfg["skip"]` can omit slices (`--dry-run --landtag-only` skips DIP, facilities and media). A DIP 401 stops only DIP and records the help page plus parlamentsdokumentation@bundestag.de. `ingest.common.db` and `ingest.common.main` are not called.

**Drucksachen.** `GET /api/v1/drucksache` with repeated `f.titel`: Wohnungslosigkeit, Obdachlosigkeit, Wohnungslosenhilfe, Kältehilfe, Wohnungsnotfall, Wohnungsnotfälle, Housing First. The cursor from page 1 was sent once. The follow-up returned the same cursor and an empty `documents` array, so the title-filter set is complete (`numFound` 81, stored 81). The note `pages=1` counts pages that contained documents. Each PDF URL was checked with `Range: bytes=0-15`. Status 200 or 206 plus `application/pdf` or a `%PDF` body is `pdf_status=verified_pdf`. Anything else, including a 404 HTML body, is `unavailable`. The row is still stored. `doc.kind` is `report`, `doc.land` is `DE`, publisher is Deutscher Bundestag (BT) or Bundesrat (BR). The summary is type, number, title and date only. Urheber text is the institutional `titel` (a faction, the Bundesregierung, the Europäisches Parlament). `autoren_anzeige` is not copied. Natural key is `dip_id`.

**Landtag papers.** Same title terms as DIP. Only official machine-readable sources are used. Berlin: official PARDOK REST `GET /api/v1/drucksache` with repeated `f.titel`, cursor paging, page size 100. The published key is loaded from the official Open Data page (or `PARDOK_API_KEY`) and sent only as `X-API-Key`; it is never placed in a URL, log, research note or commit. Metadata licence is `dl-de/by-2-0`. PDF URLs from the API are stored only after a ranged GET returns 200 or 206 with a PDF type or `%PDF` magic. Schriftliche Anfrage and Antwort often share one PDF; both rows are kept, and `doc.url` is `pdf_url#<dip_id>` so dates are not overwritten. Brandenburg: official ELVIS XML exports WP 1–8 are parsed (title match, skip `VFunktion=delete`). 26 title matches were found (17 Kleine Anfrage, 4 Fragestunde, 4 Antrag, 1 Sitzung). Their official `LokURL` PDFs returned HTTP 403 from this environment, so no BB row was stored. Bayern: official webangebot3 RSS feeds for Anfragen, Anträge and Gesetzentwürfe, recent window only (Anfragen spanned 25 August to 19 November 2026). Bayern RSS titles are often just "Initiativdrucksache 19/…"; the subject is in `description` and is used as `titel`. Hamburg: official ParlDok `index.rss`, recent items only. Schleswig-Holstein: official ParlaFeed RSS when the published URLs return RSS. Other Länder are recorded as gaps. Landtag rows use `origin` `landtag_pardok`, `landtag_elvis` or `landtag_rss`, `land` as the official abbreviation, and a prefixed `dip_id` (`BE-PARDOK:…`, `BB-ELVIS:…`, `BY-RSS:…`). A Landtag row is stored only when a public URL returned HTTP 200 or a verified PDF.

**Facilities.** Labels were checked with `wbgetentities` before the query. A class whose live German or English label did not match was not used. No class was dropped. Items are in Germany (`P17` Q183) or located in a German Land, and instance of a psychiatric class (Q210999, Q1516931, Q2539416, Q70450233) or a prison class (Q594128, Q40357, Q18050, Q2945301, Q2305965, Q227691). Women's shelter (Q1451763) is excluded. Kind is `psychiatric`, `psych_unit`, or `prison`. An item that is both a psychiatric class and a prison class is `other`. City is the single direct `P131` label. Land is the official abbreviation when exactly one `P131+` Land has an ISO 3166-2 code in the schema set (SH, HH, NI, HB, NW, HE, RP, BW, BY, SL, BE, BB, MV, SN, ST, TH). Beds, opened year, closed year, operator, address and one coordinate are stored only when Wikidata has exactly one value. Status is `closed` only when `P3999` or `P576` has a value, otherwise `unknown`. `is_est` is 0. Budget and annual cost per bed are not written. The facility natural key is `(name_norm, land, city)`; the private table `institutions_media_facility` keeps the QID so a second run updates the same row when city is NULL. A name collision on that natural key leaves the existing row in place.

**Licences.** Every `source` this domain writes gets a non-empty `license` (the Lead verify gate G3 rejects NULL). Commons: `LicenseShortName`, `LicenseUrl` and Artist/Credit/Attribution from `extmetadata` are stored on that file's `source` and `media` rows; files with a missing or non-free licence are skipped (CC0, Public domain, CC BY, CC BY-SA, and GFDL as an equivalent free licence are kept). When Commons omits `LicenseUrl` but the short name is a known free licence (typical for "Public domain"), a canonical URL is filled in. Wikidata: `CC0 1.0`, citing https://www.wikidata.org/wiki/Wikidata:Licensing after a live HTTP 200; if that page is not 200, facilities are skipped rather than stored with a NULL licence. Berlin PARDOK metadata: `dl-de/by-2-0` and the official attribution. DIP: `source.license` is `TODO: DIP Nutzungsbedingungen pending Lead confirmation` with `license_url` pointing at https://dip.bundestag.de/über-dip/nutzungsbedingungen, until the Lead pins down the terms. Bayern official RSS (the one stored paper) is also a TODO, because no reuse licence is stated on the official RSS/catalog page. Brandenburg ELVIS would use the same kind of TODO if a PDF ever returned 200; none were stored.

**Media.** Commons category members of `Category:Homelessness in Germany` and `Category:Housing First`, one level of subcategories whose titles match the homelessness word list, plus `intitle:` searches for Obdachlosigkeit, Wohnungslosigkeit, Kältehilfe and "Housing First". A file is stored only when `LicenseShortName` matches a free licence (CC0, CC BY, CC BY-SA, public domain, GFDL) and the mediatype is an image or a video. Video rows are metadata only.

## Limits

- The DIP query matches titles, not the full text. A paper that discusses homelessness only in the body is absent.
- Landtag coverage is uneven. Berlin is a full official API. Brandenburg has a full official XML export, but the document PDFs were HTTP 403 here, so BB is documented and not stored. Bayern, Hamburg and Schleswig-Holstein official RSS feeds cover only a recent window, not the archive. Sachsen EDAS is a public HTML search; no official public API documentation was found. NRW's Parlamentsdatenbank is a public HTML search (sometimes called OPAL) with no official REST or XML export found. Hessen, Rheinland-Pfalz, Thüringen, Bremen, Sachsen-Anhalt and Saarland have no official machine-readable parliament API or bulk export found (newsletter or HTML search only). Mecklenburg-Vorpommern offers account-based alerts, not a documented public RSS or API. Baden-Württemberg's official "RSS Feed — Neue Drucksachen" page is HTML only; no machine-readable feed URL was advertised on that page. Niedersachsen's official RSS page was in maintenance when checked.
- Official RSS titles are matched against the same seven terms as DIP. A Bayern motion whose description said "Obdachlose" and "Kälte" but not "Obdachlosigkeit" or "Kältehilfe" was not stored.
- Bundesrechnungshof, Land Rechnungshof reports, and court decisions were not searched. No `doc.kind=audit` and no court rows.
- Wikidata is not an official hospital or prison register. 27 items had no German or English label and were skipped. Psychiatric departments (Q70450233) contributed no German items. Closed items are included only when Wikidata has a dissolution or official-closure statement; a missing statement stays `unknown`, not `open`.
- No EUR amount was copied. `P2139` / similar revenue statements were not treated as a budget, because no cited document was opened and checked for a euro figure.
- The catalog, the human help page, and the terms page are JavaScript shells. The title and the licence are not in that HTML.
- `Category:Obdachlosigkeit` came back as page id `-1` with the missing flag (a categoryinfo block on that missing record said 1 file). It was not used.
- Commons `intitle:` is not a Germany filter. One of the two stored videos is a US Senate hearing whose title contains "Housing First".
- Four free Commons files were left out because they are audio (three `.ogg` pronunciation files) or a PDF. This module stores image and video metadata only.
- Named members of parliament appear in `autoren_anzeige` on some DIP records. They were not stored. No private individuals were stored.
- DIP `source.license` is a TODO, not a resolved official licence. 81 DIP source rows in the full dry-run would have been NULL before this fix. The Bayern RSS row (1) is the same kind of TODO. These 82 rows are the only remaining licence gaps; none are NULL.
- Commons and Wikidata coordinates are dropped for `frauenhaus` / `schutzwohnung` / `protected_shelter` facilities and for media whose title, description or categories name those places. No such protected Commons file appeared in this dry-run (`protected_geotags_dropped=0`).

## Verified

Re-fetched 2026-11-20. Fields below are the values in that response.

1. **Bundestag, Drucksache 21/8865, PDF available.**  
   https://search.dip.bundestag.de/api/v1/drucksache/292009 returned HTTP 200 `application/json`.  
   `id` 292009, `dokumentnummer` 21/8865, `drucksachetyp` Kleine Anfrage, `datum` 2026-11-02, `wahlperiode` 21, `herausgeber` BT, `titel` "Wohnungslosigkeit infolge von Zwangsräumungen", urheber `titel` "Fraktion DIE LINKE", `fundstelle.pdf_url` https://dserver.bundestag.de/btd/21/088/2108865.pdf.  
   The record also has `autoren_anzeige`. Those names were not stored.  
   Ranged GET of the PDF: HTTP 206, `content-type` `application/pdf`, first bytes `%PDF-1.7`.  
   Catalog https://dip.bundestag.de/drucksache/292009 is HTTP 200 `text/html`, 2375 bytes, 13 script tags. The title string is not in the HTML.

2. **Bundestag, Drucksache 21/9274, PDF missing.**  
   https://search.dip.bundestag.de/api/v1/drucksache/292500 returned HTTP 200 `application/json`.  
   `id` 292500, `dokumentnummer` 21/9274, `drucksachetyp` Antwort, `datum` 2026-11-17, `wahlperiode` 21, `herausgeber` BT, urheber `titel` "Bundesregierung", `fundstelle.pdf_url` https://dserver.bundestag.de/btd/21/092/2109274.pdf.  
   `titel` is three lines: "auf die Kleine Anfrage", "- Drucksache 21/8865 -", "Wohnungslosigkeit infolge von Zwangsräumungen".  
   Ranged GET of the PDF: HTTP 404, `content-type` `text/html; charset=utf-8`, body starts `<html>`. Not stored as a PDF. The row is kept and cites the API document.  
   Catalog https://dip.bundestag.de/drucksache/292500 is HTTP 200, same 2375-byte shell, title not in the HTML.

3. **Bundesrat, Drucksache 89/11.**  
   https://search.dip.bundestag.de/api/v1/drucksache/31488 returned HTTP 200 `application/json`.  
   `id` 31488, `dokumentnummer` 89/11, `drucksachetyp` Unterrichtung, `datum` 2011-01-28, `wahlperiode` 17, `herausgeber` BR, `titel` "Erklärung des Europäischen Parlaments vom 16. Dezember 2010 zu einer EU-Strategie zur Bekämpfung der Obdachlosigkeit", urheber `titel` "Europäisches Parlament", `fundstelle.pdf_url` https://dserver.bundestag.de/brd/2011/0089-11.pdf.  
   Ranged GET of the PDF: HTTP 206, `application/pdf`, first bytes `%PDF-1.4`.  
   Catalog https://dip.bundestag.de/drucksache/31488 is HTTP 200 and does not contain the title.

4. **Inn-Salzach-Klinikum.**  
   https://www.wikidata.org/wiki/Special:EntityData/Q1663850.json returned HTTP 200 `application/json`.  
   German label "Inn-Salzach-Klinikum". `P31` includes Q210999 (psychiatric hospital). `P17` is Q183. `P131` is Q259617. `P6801` amount is `+759`. `P571` time is `+1883-00-00T00:00:00Z` (year 1883, no day). No `P576`, no `P3999`, no `P6375`.  
   https://www.wikidata.org/w/api.php `wbgetentities` for Q259617 returned HTTP 200, German label "Wasserburg am Inn". That is the only direct parent, so city is Wasserburg am Inn.  
   https://www.wikidata.org/wiki/Special:EntityData/Q980.json returned HTTP 200. German label "Bayern", `P31` includes Q1221156, `P300` is `DE-BY`. The SPARQL binding for this item (same day's query, HTTP 200) has `landIsos` `Q980=DE-BY` and `beds` `759`. The string `DE-BY` is on the Bayern item, not on Q1663850. No euro amount is on the hospital item.

5. **Justizvollzugsanstalt Nürnberg.**  
   https://www.wikidata.org/wiki/Special:EntityData/Q1714428.json returned HTTP 200.  
   German label "Justizvollzugsanstalt Nürnberg". `P31` is Q594128 (Justizvollzugsanstalt). `P17` is Q183. `P131` is Q2090. `P571` time is `+1865-00-00T00:00:00Z`. No `P6801`, no `P576`, no `P3999`, no street address.  
   `wbgetentities` for Q2090 returned HTTP 200, German label "Nürnberg". The same SPARQL response has `landIsos` `Q980=DE-BY` and `parents` `Q2090=Nürnberg`. Status stays `unknown` because there is no closure statement.

6. **Commons image.**  
   https://commons.wikimedia.org/w/api.php for `File:2020-12-04 Plakat 02 Jetzt besetzen wir.jpg` returned HTTP 200.  
   `title` "File:2020-12-04 Plakat 02 Jetzt besetzen wir.jpg", `descriptionurl` https://commons.wikimedia.org/wiki/File:2020-12-04_Plakat_02_Jetzt_besetzen_wir.jpg, `mime` `image/jpeg`, `mediatype` `BITMAP`, `LicenseShortName` "CC BY-SA 4.0", `License` "cc-by-sa-4.0".  
   The file page itself returned HTTP 200 `text/html` and contains the string "CC BY-SA 4.0".

## Licence verified

Re-fetched 21 November 2026, Europe/Berlin.

1. **Wikidata licensing page.**  
   https://www.wikidata.org/wiki/Wikidata:Licensing returned HTTP 200 `text/html`. The page states that structured data is released under Creative Commons Zero. Facility `source.license` is stored as `CC0 1.0` and `source.license_url` is this page.

2. **Commons file, CC BY-SA 4.0, attribution stored.**  
   https://commons.wikimedia.org/wiki/File:2020-12-04_Plakat_02_Jetzt_besetzen_wir.jpg was stored in the dry-run with `license=CC BY-SA 4.0` taken from extmetadata `LicenseShortName`. Licence URL and creator credit come from the same extmetadata block. 127 files kept, 0 skipped for licence, 4 skipped because they are not an image or video.

3. **Brandenburg Landtag Nutzungsbedingungen (Drucksachen).**  
   https://www.parlamentsdokumentation.brandenburg.de/portal/opendata_dokumente.tt.html returned HTTP 200. Official wording: "Soweit es sich bei den Drucksachen, Informationen sowie Einladungen und Protokollen zu den Sitzungen des Landtags und seiner Gremien um schutzfähige Werke im Sinne des UrhG handelt, genießen sie als amtliche Werke im Sinne des § 5 Absatz 2 UrhG keinen urheberrechtlichen Schutz. Sie unterliegen jedoch dem Änderungsverbot gemäß § 62 Absatz 1 bis 3 UrhG und dem Gebot der Quellenangabe gemäß § 63 Absatz 1 und 2 UrhG." Stored `source.license` quotes that § 5 Abs. 2 / § 62 / § 63 rule and keeps this URL. Attribution: Parlamentsdokumentation, Landtag Brandenburg.

4. **Bayerischer Landtag imprint (Drucksachen).**  
   https://www.bayern.landtag.de/service/impressum/ returned HTTP 200. Official wording: "Drucksachen und Plenarprotokolle des Bayerischen Landtags genießen als amtliche Werke im Sinne des § 5 Abs. 2 UrhG keinen urheberrechtlichen Schutz, d. h. die Dokumente dürfen abgespeichert und an anderen Stellen, auch im Internet, veröffentlicht werden (der Bayerische Landtag empfiehlt jedoch jeweils eine Verlinkung auf die Dokumente der Landtagswebseite). Sie unterliegen jedoch dem Änderungsverbot gemäß § 62 Abs. 1 bis 3 UrhG und dem Gebot der Quellenangabe gemäß § 63 Abs. 1 und 2 UrhG." Stored `source.license` quotes that rule and keeps this imprint URL.

5. **Schleswig-Holsteinischer Landtag imprint (Drucksachen).**  
   https://www.landtag.ltsh.de/metainfo/impressum/ returned HTTP 200. Official wording: "Drucksachen und Plenarprotokolle des Schleswig-Holsteinischen Landtages genießen als amtliche Werke im Sinne des § 5 Abs. 2 UrhG keinen urheberrechtlichen Schutz. Sie unterliegen jedoch dem Änderungsverbot gemäß § 62 Abs. 1 bis 3 UrhG und dem Gebot der Quellenangabe gemäß § 63 Abs. 1 und 2 UrhG." The ParlaFeed itself states no document terms; the imprint does. Stored `source.license` quotes the imprint and keeps this URL. (The dry-run stored no SH row this pass, but the licence is wired for any future hit.)

6. **Hamburgische Bürgerschaft / ParlDok.**  
   Official ParlDok https://www.buergerschaft-hh.de/parldok/index.rss and https://www.buergerschaft-hh.de/parldok/lizenz.html (HTTP 200) state no reuse terms for Drucksachen; lizenz.html lists third-party software licences. The Bürgerschaft impressum https://www.hamburgische-buergerschaft.de/impressum (HTTP 200) also states no Drucksachen terms. Stored `source.license` is "amtliches Werk, § 5 UrhG", explicitly scoped to the cited Bürgerschaft document text only, and keeps the impressum URL. (The dry-run stored no HH row this pass.)

Bundestag DIP licences remain `TODO` pending the Lead's replacement at merge. They are the only TODO licences this domain still writes.

## Landtag verified

Re-fetched 21 November 2026, Europe/Berlin.

1. **Berlin, Drucksache 27042, Antwort, PDF available.**  
   PARDOK `id` D-459264, `dokumentnummer` 27042, `drucksachetyp` Antwort, `datum` 2026-09-08, `wahlperiode` 19, title "Vom Jugendamt in die Wohnungslosigkeit - wie viele Careleaver lässt Berlin nach Ende der Jugendhilfe ohne sichere Wohnperspektive?".  
   https://pardok.parlament-berlin.de/starweb/adis/citat/VT/19/SchrAnfr/S19-27042.pdf returned HTTP 206 `application/pdf` and began with `%PDF-1.7`. The paired Schriftliche Anfrage is D-459263 on the same PDF, dated 2026-08-18.

2. **Berlin Open Data terms.**  
   https://pardok.parlament-berlin.de/portala/local/OpenData_Nutzungsbedingungen.pdf returned HTTP 206 `application/pdf`. The text names Datenlizenz Deutschland — Namensnennung — Version 2.0 and the attribution "Parlamentsdokumentation, Abgeordnetenhaus von Berlin".

3. **Brandenburg ELVIS export and current PDF path.**  
   https://www.parlamentsdokumentation.brandenburg.de/opendata/exportWP8.xml returned HTTP 200/206 `application/xml`. A title search of WP 1–8 found 26 documents. Official `LokURL` values still use the retired path `/starweb/LBB/ELVIS/parladoku/…`. The Lead confirmed that `/starweb/` returned Apache 403 from another IP and a real browser, while the current portal homepage https://www.parlamentsdokumentation.brandenburg.de/portal/browse.tt.html loads. Portal search is a JavaScript STAR/esearch form that POSTs JSON to `/portal/browse.tt.json`; results are not in the first HTML. The same documents are served at the official path made by stripping `/starweb/LBB/ELVIS` from `LokURL`, e.g. https://www.parlamentsdokumentation.brandenburg.de/parladoku/w8/drs/ab_2800/2836.pdf (and `/parladoku/w8/apr/AASGZ/14.pdf` for 08/14). Rechecked 2026-11-21 around 02:05 Europe/Berlin from deck: all 26 mapped `/parladoku/` URLs returned HTTP 200 or 206 `application/pdf` and began with `%PDF`. The ingest maps every ELVIS `LokURL` to that current official path before verification. (From deck at the same check, one old `/starweb/` URL also returned 200; the module still stores `/parladoku/` because that is the current official location.)

4. **Bayern, Initiativdrucksache 19/13306.**  
   Official Anfragen RSS item titled "Initiativdrucksache 19/13306" with description "Obdachlosigkeit".  
   https://www.bayern.landtag.de/webangebot3/views/vorgangsmappe/vorgangsmappe.xhtml?gegenstandid=167484 returned HTTP 200 `application/pdf` and began with `%PDF-1.6`.

## Coverage

The dry-run list response and the ingest log agree: 81 catalog checks at HTTP 200, 80 PDF checks at HTTP 206, 1 PDF check at HTTP 404.

| Slice | What this pass holds | Denominator |
| --- | --- | --- |
| Bundestag / Bundesrat titles | 81/81 documents for the seven title terms. 77 BT, 4 BR. Types: Antrag 21, Antwort 17, Kleine Anfrage 17, Beschlussempfehlung und Bericht 15, Unterrichtung 7, Entschließungsantrag 2, Ergänzende Antwort 1, Bericht 1. | The title-filter hit set that day. Not every relevant paper, and not the full text. |
| PDF files for those 81 | 80 verified, 1 unavailable (21/9274). | The 81 `fundstelle.pdf_url` values. |
| Landtag papers | 311 stored in the landtag-only dry-run on 21 November 2026, 02:28–02:34 Europe/Berlin (284 BE, 26 BB, 1 BY), after the PARDOK probe retry. | See the per-Land table and the PARDOK drift section. |
| Psychiatric facilities | 122 stored as `psychiatric`. `psych_unit` 0. | Wikidata items of the checked classes with a de/en label. Not an official clinic register. |
| Prisons | 318 stored as `prison`. | Same Wikidata limit. Not an official Justizvollzugsanstalt register. |
| Both classes at once | 2 stored as `other`. | Of 469 unique items (471 bindings). 27 further items had no de/en label and were skipped. 442 stored. |
| Beds | Stored only for a single `P6801`. 1 item had several bed values and was stored with beds NULL. | Wikidata statements, not a bed census. |
| Coordinates | 3 items had more than one coordinate and were stored with lat/lon NULL. | |
| EUR economics | 0/442 with a budget or a cost per bed. | No cited euro document was verified. |
| Audits | 0 | Not fetched. |
| Court decisions | 0 | Not fetched. |
| Commons metadata | 127 stored of 131 unique files returned by the category walk and the four intitle searches. 125 images, 2 videos. | Those queries. The unfiltered Commons search (tens of thousands of hits) was not used. `Category:Homelessness in Germany` itself is 37 members (27 files, 10 subcategories). `Category:Housing First` is 2 files. |

Per-Land Landtag results (title terms, official machine-readable sources only):

| Land | Stored | Source used | Notes |
| --- | ---: | --- | --- |
| BE | 284 | Official PARDOK REST API, `f.titel`, full database | After the `_probe` retry: `--dry-run --landtag-only` on 21 November 2026, 02:28–02:34 Europe/Berlin, `numFound=284`, stored 284 (`verified_pdf=283`, `unavailable=1`). The 02:10 drop to 268 and the 16 dropped probes are explained in the PARDOK drift section. Licence `dl-de/by-2-0`. |
| BB | 26 | Official ELVIS XML WP 1–8, PDFs at the current `/parladoku/` path | 26 title matches (wp1=2, wp2=2, wp3=4, wp4=3, wp5=2, wp6=5, wp7=6, wp8=2), all stored as `verified_pdf`. Official `LokURL` still points at retired `/starweb/LBB/ELVIS/parladoku/…`; ingest rewrites that to `/parladoku/…` (same host and document path, including `/parladoku/w8/apr/AASGZ/14.pdf`). Licence: amtliches Werk, § 5 Abs. 2 UrhG, as quoted from the official Nutzungsbedingungen. |
| BY | 1 | Official webangebot3 RSS (Anfragen, Anträge, Gesetzentwürfe) | Recent window only. 538+628+104 feed items; one Anfragen hit ("Obdachlosigkeit", 19/13306). Licence: amtliches Werk, § 5 Abs. 2 UrhG, as quoted from the official Landtag imprint. |
| HH | 0 | Official ParlDok `index.rss` | Recent window only. 20 items, no title-term hit. |
| SH | 0 | Official ParlaFeed RSS (Drucksachen and Kleine Anfragen) | Recent window only. 58+24 items during the dry-run, no title-term hit. The same URLs later returned HTTP 500 from another environment. |
| SN | 0 | — | Official EDAS HTML search exists. No official public API documentation found. |
| NW | 0 | — | Public HTML Parlamentsdatenbank (sometimes called OPAL). No official REST or XML export found. |
| MV | 0 | — | Account-based document alerts, no documented public RSS or API found. |
| BW | 0 | — | Official "RSS Feed — Neue Drucksachen" page is HTML only; no machine-readable feed URL advertised. |
| NI | 0 | — | Official RSS-Feeds page was in maintenance when checked. |
| HE, RP, TH, HB, ST, SL | 0 | — | No official machine-readable parliament API or bulk export found. |

The 26 Brandenburg title matches listed in an earlier pass (01/1817, 01/2381, 02/572, 02/3654, 03/115, 03/124, 03/7847, 03/7849, 04/111, 04/759, 04/1270, 05/4381, 05/7025, 06/2629, 06/3435, 06/7727, 06/9909, 06/9920, 07/396, 07/5944, 07/6328, 07/6684, 07/7198 Neudruck, 07/7265, 08/14, 08/2836) are now stored from the current official `/parladoku/` URLs.

Still missing for a later slice: Landtag papers for the gap Länder once an official machine-readable source is available; and per-facility euro figures taken from a document that actually prints the amount. Commons `intitle:` results still need a Germany filter before they are treated as a German corpus. Berlin PARDOK drift (16 title hits not stored in the mid-night dry-run) is explained in the section below; a retry was added and the post-fix count is recorded there. Court decisions are out of scope for this domain (Counts & Law); any genuinely domestic-relevant leads from the stopped BVerwG pass are under “court leads for Counts & Law”.

## manual archive needed

The 26 Brandenburg ELVIS `LokURL` PDFs listed here on 2026-11-21 01:32 Europe/Berlin (HTTP 403 on the retired `/starweb/LBB/ELVIS/parladoku/` path) are archived as resolved: they are stored from the current official `/parladoku/` URLs (all 26 verified HTTP 200/206 + `%PDF` from deck on 2026-11-21 around 02:05 Europe/Berlin). No manual download is required.

Rechnungshof Bremen Jahresberichte 2024 is archived, not outstanding. The official URL https://www.rechnungshof.bremen.de/sixcms/media.php/13/2024-03-07_RH-Jahresberichte-2024_Land-und-Stadt-barrierefrei.pdf still returns no PDF from deck (verdict `unavailable` / previously HTTP 403, checked 2026-11-21 01:49 and again during the 02:15 Europe/Berlin dry-run). The Atlas Lead fetched the same official URL with the honest project User-Agent from another IP and stored it at `~/projects/_manual_archive/institutions_media/rh_bremen_jb2024.pdf` (7,007,314 bytes, sha256 `1d5a8bfa3e5a6200b190455c0eadb1bde150a15533d95499070301272bfd53a6`). Size and sha256 were verified on deck before ingest. The source row cites the official URL and records that provenance. The "Projekt Housing First" chapter (Stadt, S. 63–65, Tz. 238–251) was extracted from the archive; euro figures were stored only with verbatim quotes and those page locators.

### Bremen / Frankfurt official shelter pages and blocked shelter-cost documents

One list of official URLs that still need a manual archive, compiled for the Lead on 21 November 2026. Checked from deck between 06:54 and 06:56 Europe/Berlin (CET, UTC+1). Polite fetching only: honest project User-Agent `germany-atlas/1.0 (public-record research on homelessness in Germany; local, non-commercial)`, one request per second, `robots.txt` honoured, a single retry after HTTP 403, no host hammered. Candidates were identified from public search and from official indexes that themselves loaded (Bremische Bürgerschaft Sitzungsdokumente, STVV PARLIS Vorlagensuche, Köln RIS SessionNet and the Stadt Köln Satzungssammlung). `data/atlas.db` was not opened.

The four catalogued Bremen overnight offers have no separate official municipal URLs. They are listed on the service.bremen.de page and again on the Senatorin’s Wohnungslosenhilfe page. Archiving those two pages is enough to verify the offers. Träger sites were not requested. The women-only offer remains district/city-level on ingest; this list only asks for the official pages as published.

`robots.txt` for `service.bremen.de`, `soziales.bremen.de`, `rathaus.bremen.de` and `amtfuersozialedienste.bremen.de` themselves returned HTTP 403, so no crawl rule could be read; the document URLs were then requested once plus one retry. `frankfurt.de/robots.txt` allows `/` and states Content-Signal `search=yes, ai-train=no, use=reference`; the pages still returned HTTP 403 with a Cloudflare “Just a moment…” body. Please fetch with the honest UA from another IP, as with the Bremen Rechnungshof Jahresberichte 2024, and store under `~/projects/_manual_archive/institutions_media/` with bytes and sha256.

#### Needed for manual archive

| URL | What it is | Status | Time checked (Europe/Berlin) |
| --- | --- | --- | --- |
| https://www.service.bremen.de/dienstleistungen/notunterkunft-als-wohnungslose-person-nachfragen-11450 | Bremen official service page “Notunterkunft als wohnungslose Person nachfragen”. This is the catalogued source for all four overnight offers: Notunterkunft für Männer, Rembertiring 49, 28195 Bremen; Notunterkunft für Frauen (address withheld: women-only offer); Sleep Inn, Oberneulander Landstraße 19, 28355 Bremen; La Campagne, Ahlringstraße 2-4, 28309 Bremen. | HTTP 403 (`text/html`, 199 bytes, title “403 Forbidden”) after one polite retry | 2026-11-21 06:54 CET |
| https://www.soziales.bremen.de/soziales/wohnungslosenhilfe-126027 | Bremen Senatorin für Arbeit, Soziales, Jugend und Integration, official Wohnungslosenhilfe page. Independently lists the same four official overnight offers. | HTTP 403 (`text/html`, 199 bytes, title “403 Forbidden”) after one polite retry | 2026-11-21 06:54 CET |
| https://www.amtfuersozialedienste.bremen.de/erwachsene/zentrale-fachstelle-wohnen-11198 | Bremen Amt für Soziale Dienste, official Zentrale Fachstelle Wohnen page (the service desk that mediates the Notunterkünfte). | HTTP 403 (`text/html`, 199 bytes, title “403 Forbidden”) after one polite retry | 2026-11-21 06:54 CET |
| https://frankfurt.de/leistungen/Notlagen-und-Opferhilfen-8958513/Finanzielle-und-sonstige-Hilfen-8958541/Notschlafstellen | Frankfurt official Notschlafstellen service page (the published overnight-shelter directory). | HTTP 403 (`text/html`, Cloudflare “Just a moment…”) after one polite retry | 2026-11-21 06:55 CET |
| https://frankfurt.de/themen/soziales-und-gesellschaft/notlagen-und-hilfen/in-notlagen/kaeltebus | Frankfurt official Kältebus / Hitzebus page. | HTTP 403 (`text/html`, Cloudflare “Just a moment…”) after one polite retry | 2026-11-21 06:55 CET |
| https://frankfurt.de/de-de/aktuelle-meldung/dezernat-viii/schlafplaetze-fuer-obdachlose/ | Frankfurt official Dezernat VIII press page, 4 November 2026, “Frankfurt hält für Obdachlose 630 Schlafplätze vor” (capacity overview, not the directory). | HTTP 403 (`text/html`, Cloudflare “Just a moment…”) after one polite retry | 2026-11-21 06:55 CET |
| https://www.rathaus.bremen.de/sixcms/media.php/13/20250819_top_22_Wohnungs_und_Obdachlosigkeit.pdf | Bremen Senate answer adopted 19 August 2025 on Wohnungs- und Obdachlosigkeit. Official annual net costs for Notunterkünfte, betreute Einrichtungen, hotels and pensions (Bremen 2023: €4,043,506; 2024: €4,465,032; Bremerhaven men’s Notunterkunft 2023: around €280,000). | HTTP 403 (`text/html`, 199 bytes, title “403 Forbidden”) after one polite retry | 2026-11-21 06:55 CET |
| https://www.rathaus.bremen.de/sixcms/media.php/13/top%2011_20240423_Beendigung_von_Wohnungs_und_Obdachlosigkeit_N.pdf | Bremen Senate template of 23 April 2024, “Beendigung von Wohnungs- und Obdachlosigkeit”. | HTTP 403 (`text/html`, 199 bytes, title “403 Forbidden”) after one polite retry | 2026-11-21 06:55 CET |
| https://www.soziales.bremen.de/sixcms/media.php/13/Mehr+Transparenz+bei+den+Angeboten+und+Kosten+der+Wohnungslosenhilfe.pdf | Bremen Senate answer 2013, “Mehr Transparenz bei den Angeboten und Kosten der Wohnungslosenhilfe”, with per-facility daily Entgelte that include the four official offers (for example Sleep Inn 52,39 €, La Campagne 48,86 €). | HTTP 403 (`text/html`, 199 bytes, title “403 Forbidden”) after one polite retry | 2026-11-21 06:55 CET |
| https://sd.bremische-buergerschaft.de/sdnetrim/UGhVM0hpd2NXNFdFcExjZRqJi2_bo6AeOa2nQOVq-sexF-o1P2dFKO76dTyARjnT/Beschlussvorlage_Ausschuesse-Deputationen_VL_20-1210.pdf | Deputationsvorlage VL 20/1210, “Notunterkünfte für Obdachlose” (export 17.04.2020). The official index page loaded (HTTP 200, 26,757 bytes, 06:55 CET): https://sd.bremische-buergerschaft.de/vorgang/?__=UGhVM0hpd2NXNFdFcExjZZ8cY3SbgEe6ZmdswZ6YTZA | Not fetched: `https://sd.bremische-buergerschaft.de/robots.txt` is `User-Agent: *` / `Disallow: /*.pdf$` | 2026-11-21 06:56 CET |
| https://sd.bremische-buergerschaft.de/sdnetrim/UGhVM0hpd2NXNFdFcExjZZB7EJQ4UxlGTaLNwm4P-vajKNS-iUJAGGKfBgGyUCxh/Beschlussvorlage_Ausschuesse-Deputationen_VL_20-7270.pdf | Deputationsvorlage VL 20/7270, “Sachstandsbericht zur Unterbringung in Notunterkünften” (export 27.10.2022). The official index page loaded (HTTP 200, 26,766 bytes, 06:55 CET): https://sd.bremische-buergerschaft.de/vorgang/?__=UGhVM0hpd2NXNFdFcExjZVVPlm6aWK-DAC7QDZwfBt0 | Not fetched: same `Disallow: /*.pdf$` on this host | 2026-11-21 06:56 CET |
| https://frankfurt.de/-/media/frankfurtde/service-und-rathaus/verwaltung/aemter-und-institutionen/rechtsamt/pdf/satzungen/unterbringungsgebuehrensatzung.pdf | Frankfurt official Unterbringungsgebührensatzung 2026 with Gebührenverzeichnis (LAG-HSOG / sonstige Unterkunft monthly fees, including fees for obdach- and wohnungslose Personen after the merger of the two earlier statutes). | HTTP 403 (`text/html`, Cloudflare “Just a moment…”) after one polite retry | 2026-11-21 06:55 CET |

Two public Beschluss texts sit on the same Bürgerschaft index pages as VL 20/1210 and VL 20/7270 (städtische Deputation 23.04.2020 and staatliche Deputation 03.11.2022). They are also `*.pdf` and were not fetched because of the same robots rule. If the Lead is already collecting that folder, those two files can come along; they are not expected to carry the Kostensätze.

Frankfurt Magistratsvorlage M 71/2026 (“Zusammenführung” of the LAufnG and the obdach-/wohnungslosen Personen fee statutes, accepted by the Stadtverordnetenversammlung on 25 June 2026) is the parliamentary source of the 2026 Unterbringungsgebührensatzung. The official PDF lives in PARLIS. `https://www.stvv.frankfurt.de/robots.txt` disallows `/PARLISLINK`, `/dokumente` and `/download`, so that PDF was not requested. The Vorlagensuche index https://www.stvv.frankfurt.de/parlis2/vorlagen.html loaded (HTTP 200, 7,713 bytes, 2026-11-21 06:55 CET). Please archive the official PARLIS PDF of M 71/2026 from a browser.

The official Frankfurt Amtsblätter 2026 index (https://frankfurt.de/service-und-rathaus/verwaltung/amtsblatt-der-stadt-frankfurt-am-main/amtsblaetter-2026) and the thematic statutes index also returned HTTP 403 at 06:55 CET, so the exact Amtsblatt issue that promulgated the Satzung could not be verified from deck. The Satzung PDF above is the document to archive first.

No official Köln shelter-cost document identified in this pass returned HTTP 403 from deck, so none is on the list above.

#### Identified official cost documents that loaded from deck (no manual archive needed)

These were found via the same search and official indexes, then fetched politely, and returned HTTP 200 with a verified PDF. They can be ingested later without a hand archive.

| URL | What it is | Status | Time checked (Europe/Berlin) |
| --- | --- | --- | --- |
| https://static.bremische-buergerschaft.de/dokumente/wp19/land/drucksache/D19L0894.pdf | Bremische Bürgerschaft Drs 19/894 (answer of 10 January 2017): official Kostensätze for Wohnungslosen-Notunterkünfte of 51,01 € to 136,65 € per person and night, and 16 € to about 40 € (in a single case up to 45 €) for hotels and pensions. | HTTP 200, `application/pdf`, 73,268 bytes, `%PDF` magic | 2026-11-21 06:55 CET |
| https://www.stadt-koeln.de/mediaasset/content/satzungen/satzung_zur_aenderung_der_gebuehrensatzung_obdachloseneinrichtungen_2024_04_05.pdf | Köln official amending statute of 17 April 2024 on fees for Einrichtungen für obdachlose Personen. | HTTP 200, PDF, 218,182 bytes | 2026-11-21 06:55 CET |
| https://www.stadt-koeln.de/mediaasset/content/satzungen/gebuehrensatzung_inanspruchnahme_einrichtungen_obdachlose_18-07-2018.pdf | Köln official fee statute of 18 July 2018 for Einrichtungen für obdachlose Personen. | HTTP 200, PDF, 147,847 bytes | 2026-11-21 06:55 CET |
| https://ratsinformation.stadt-koeln.de/vo0050.asp?__kvonr=119717 | Köln RIS index for the 2024 Satzungsänderung (Vorlage 2690/2023/1). | HTTP 200, HTML, 22,916 bytes | 2026-11-21 06:55 CET |
| https://ratsinformation.stadt-koeln.de/getfile.asp?id=973457&type=do | Köln RIS Beschlussvorlage 2690/2023/1 (March 2024) amending the fee statutes, with Gebührenkalkulation. | HTTP 200, PDF, 377,163 bytes | 2026-11-21 06:55 CET |
| https://ratsinformation.stadt-koeln.de/getfile.asp?id=976557&type=do | Köln RIS attachment: Kosten- und Finanzierungsübersicht, including soziale Betreuung in gewerblichen Notunterkünften (Einfachhotel). | HTTP 200, PDF, 457,844 bytes | 2026-11-21 06:55 CET |
| https://ratsinformation.stadt-koeln.de/getfile.asp?id=949806&type=do | Köln RIS fee-statute / Kalkulation file id 949806, linked from the official RIS index. | HTTP 200, PDF, 265,273 bytes | 2026-11-21 06:55 CET |
| https://ratsinformation.stadt-koeln.de/getfile.asp?id=983460&type=do | Köln RIS fee-statute / Kalkulation file id 983460, linked from the official RIS index. | HTTP 200, PDF, 301,167 bytes | 2026-11-21 06:56 CET |
| https://ratsinformation.stadt-koeln.de/getfile.asp?id=956143&type=do | Köln RIS fee-statute / Angemessenheit file id 956143, linked from the official RIS index. | HTTP 200, PDF, 243,791 bytes | 2026-11-21 06:56 CET |
| https://ratsinformation.stadt-koeln.de/getfile.asp?id=713209&type=do | Köln RIS older fee-statute file id 713209, linked from the official RIS index. | HTTP 200, PDF, 11,335 bytes | 2026-11-21 06:56 CET |
| https://ratsinformation.stadt-koeln.de/getfile.asp?id=713190&type=do | Köln RIS older fee-statute file id 713190, linked from the official RIS index. | HTTP 200, PDF, 125,999 bytes | 2026-11-21 06:56 CET |

Further attachments linked from the same Köln RIS indexes also loaded as PDFs at 06:56–06:57 CET (ids 980356, 980352, 973474, 973481, 973678, 947604, 952987, 951657, 951658) and likewise do not need a hand archive. A later Bremen paper, Drs 21/1356, is about Unterbringung of refugees, not Wohnungslosenhilfe, and was not added to either list.


## Schema note

After this worktree was rebased onto `main` (`f874a1f`), facility rows of kind `frauenhaus`, `schutzwohnung` or `protected_shelter` set `is_protected=1` and leave `address`, `plz`, `lat` and `lon` NULL, which is what the schema CHECKs on that revision require. The fixture selftest stores the Hamburg Frauenhaus as a name-only row that way. The live dry-run stored no protected-shelter facilities, so the table counts above are unchanged.

`institutions_media_drucksache` now also has `land`, `origin` and `parliament`. `ensure_tables` adds those columns with `ALTER TABLE` when a previous revision of the private table already exists, so a Lead ingest on a database that already ran the first slice will not need a manual migration. Bundestag rows keep `land=DE` and `origin=bundestag_dip`.


## Rechnungshof audits

In-memory `--dry-run --rechnungshof-only` on 21 November 2026 around 02:15 Europe/Berlin (UTC+1), after the Bremen archive and licence pass. Official publication sites only. A PDF was stored only after a ranged or full GET returned HTTP 200 or 206 with `application/pdf` or `%PDF` magic, except Bremen Jahresberichte 2024, which is stored from the Lead's manual archive of that official URL after size and sha256 verification (the official host still does not return the PDF to deck). Every `source.license` is non-empty. After the Lead licence policy of 21 November 2026, sources whose imprint explicitly claims rights (including the Bundesrechnungshof and the Rechnungshof Bremen, and Berlin because its impressum allows only private copies of site content) are not labelled § 5 UrhG. Those rows store only facts, metadata, the official URL, and short quotes under § 51 UrhG, with `redistribute_fulltext=0` and the reserved-rights licence string set out below. One Bundesrechnungshof report is also a Bundestag Drucksache and is cited from DIP under the DIP TODO terms. Where a court states no terms for the report text, the licence remains "amtliches Werk, § 5 UrhG" scoped to the cited report text only, with `redistribute_fulltext=1`. A post-policy in-memory `--dry-run --rechnungshof-only` on 21 November 2026 at 02:34 Europe/Berlin (UTC+1) stored 10 audit rows and 15 metrics (same euro figures as before). `source` is 10: 6 with the reserved-rights licence and `redistribute_fulltext=0` (four Bundesrechnungshof reports without a DIP counterpart, Berlin Jahresbericht 2019, Bremen Jahresberichte 2024), 3 Hamburg reports with scoped § 5 UrhG, and 1 DIP TODO (BT-Drs 20/6530, Bemerkung 28, locators `BT-Drs 20/6530, S. 48, Bemerkung 28`). 0 NULL licences. 1 TODO licence, as intended, until the Lead pins down DIP terms. Bremen provenance includes the sentence that the archived PDF stays local for verification only and must never be republished. Quotes remain stored and were still found in the cited PDFs / DIP print. Euro amounts were written to `metric` only when the quote was found in the official PDF text (or the verified Bremen archive), with a page locator. No `data/atlas.db`.

| Table | Rows |
| --- | ---: |
| doc (kind=audit) | 10 |
| institutions_media_audit | 10 |
| metric | 15 |
| source | 10 |
| source with NULL licence | 0 |
| source with a TODO licence | 0 (02:15 Europe/Berlin run, before the DIP citation of BT-Drs 20/6530) |

Counts per Rechnungshof (stored, verified official PDFs or the verified Bremen archive):

| Court | Land | Stored | Kinds |
| --- | --- | ---: | --- |
| Bundesrechnungshof | DE | 5 | 3 Prüfungsmitteilungen (KdU 2019, 2020 Teil I and Teil II), 1 Bemerkung (Ergänzungsband 2022 Nr. 28), 1 Beratungsbericht (Jobcenter KdU 2024) |
| Rechnungshof von Berlin | BE | 1 | Jahresbericht 2019, chapters T 14 (Unterbringung Wohnungsloser) and T 15 (Wohnungslosenhilfe im ISP) |
| Rechnungshof der Freien und Hansestadt Hamburg | HH | 3 | Jahresbericht 2025, Jahresbericht 2026 (Finanzierung der öffentlich-rechtlichen Unterbringung), Beratende Äußerung Haushaltslage 2026 (Abschnitt 4.2.2) |
| Rechnungshof der Freien Hansestadt Bremen | HB | 1 | Jahresberichte 2024 (Land und Stadt), chapter "Projekt Housing First" (Stadt, S. 63–65, Tz. 238–251); official URL plus manual-archive provenance |
| Other 13 Landesrechnungshöfe | — | 0 | See gaps below |

The five Bundesrechnungshof rows are dedicated "Kosten der Unterkunft" / "Unterkunft und Heizung" audits (the brief asked for KdU where relevant). A 2025 Prüfungsmitteilung on KdU in der besonderen Wohnform (§ 42a SGB XII) was excluded as off-topic.

Euro figures stored, each with a quote from the cited official PDF:

| Metric | Entity | Year | Value | Locator | Report |
| --- | ---: | ---: | ---: | --- | --- |
| be_isp_wohnungslosenhilfe_plan_eur | land:BE | 2015 | 2,937,885.99 EUR | S. 201, Ansicht 60 | Berlin Jahresbericht 2019 |
| be_isp_wohnungslosenhilfe_plan_eur | land:BE | 2016 | 4,106,026.67 EUR | S. 197, Ansicht 59 | Berlin Jahresbericht 2019 |
| be_isp_wohnungslosenhilfe_plan_eur | land:BE | 2017 | 4,174,127.76 EUR | S. 197, Ansicht 59 | Berlin Jahresbericht 2019 |
| be_isp_wohnungslosenhilfe_plan_eur | land:BE | 2018 | 8,130,474.69 EUR | S. 197, Ansicht 59 | Berlin Jahresbericht 2019 |
| de_kdu_federal_annual_eur | de:DE | 2022 | 10,000,000,000 EUR (rounded, "10 Mrd.") | S. 1 | BRH Ergänzungsband 2022, Bemerkung 28 |
| de_kdu_federal_disadvantage_prevented_eur | de:DE | 2022 | 9,800,000 EUR (rounded, "9,8 Mio.") | S. 1 | BRH Ergänzungsband 2022, Bemerkung 28 |
| hh_pg25303_transfer_authorisation_eur | land:HH | 2023 | 180,404,000 EUR | S. 55, Tz. 100 | Hamburg Jahresbericht 2025 |
| hh_oeru_additional_transfer_bedarf_eur | land:HH | 2023 | 127,400,000 EUR (rounded, "127,4 Mio.") | S. 164, Tz. 591 | Hamburg Jahresbericht 2026 |
| hh_pg25303_transfer_eur | land:HH | 2019 | 45,000,000 EUR (rounded, "45 Mio.") | S. 28, Abschnitt 4.2.2 | Hamburg Beratende Äußerung 2026 |
| hh_pg25303_transfer_eur | land:HH | 2025 | 289,000,000 EUR (rounded, "289 Mio.") | S. 28, Abschnitt 4.2.2 | Hamburg Beratende Äußerung 2026 |
| hh_pg25303_transfer_plan_eur | land:HH | 2027 | 221,000,000 EUR (rounded, "221 Mio.") | S. 30, Abschnitt 4.2.2 | Hamburg Beratende Äußerung 2026 |
| hh_pg25303_transfer_plan_eur | land:HH | 2028 | 222,000,000 EUR (rounded, "222 Mio.") | S. 30, Abschnitt 4.2.2 | Hamburg Beratende Äußerung 2026 |
| hb_housing_first_grant_eur | land:HB | 2021 | 232,000 EUR (rounded, "rd. 232 T€") | Stadt, S. 65, Tz. 250 | Bremen Jahresberichte 2024, Projekt Housing First |
| hb_housing_first_overpayment_eur | land:HB | 2021 | 72,000 EUR (rounded, "rd. 72 T€") | Stadt, S. 65, Tz. 250 | Bremen Jahresberichte 2024, Projekt Housing First |
| hb_housing_first_grant_eur | land:HB | 2022 | 400,000 EUR | Stadt, S. 65, Tz. 251 | Bremen Jahresberichte 2024, Projekt Housing First |

Approximate wording such as "mehr als eine halbe Milliarde Euro" was not stored as a euro amount. ISP totals in Ansicht 59 (the wider programme, not the Wohnungslosenhilfe column) were not stored.

Method and checks: official Berichtssuche of the Bundesrechnungshof (title-filtered); Berlin Jahresberichte 2015-2025 (2018, 2019, 2021-2025 text-searched; 2015-2017 and 2020 returned HTTP 429 during the first pass); Hamburg Jahresberichte 2024-2026 plus the 2026 Beratende Äußerung; Bremen Jahresberichte 2024 (official listing plus the Lead's verified manual archive of the official PDF; Housing First chapter); NRW Jahresbericht 2026 (no on-topic hits). Other official publication indexes were opened (Bayern ORH, Baden-Württemberg, Hessen, Niedersachsen, Schleswig-Holstein, Rheinland-Pfalz, Saarland, Sachsen, Sachsen-Anhalt TLS errors on the first fetch, Thüringen, Mecklenburg-Vorpommern, Brandenburg). Official imprint or terms URLs for the federal court and the 16 Landesrechnungshöfe were opened and quoted or, where they state no report terms, replaced with "amtliches Werk, § 5 UrhG" scoped to the cited report text. The catalog in `ingest/domains/institutions_media_rechnungshof.py` is the stored set; ingest re-verifies each PDF (or the Bremen archive) and each euro quote.

Licence policy applied before the next commit (Lead note of 21 November 2026), and re-checked against each opened imprint:

- Reserved rights, `redistribute_fulltext=0`, licence exactly `Rechte vorbehalten (Impressum zitiert); nur Fakten, Metadaten und Kurzzitate nach § 51 UrhG, Volltext nicht weiterverbreitet`, quotes capped at two sentences under § 51 UrhG:
  - Bundesrechnungshof: four reports that have no Bundestag Drucksache counterpart (Prüfungsmitteilungen KdU 2019, 2020 Teil I and Teil II, Beratungsbericht Jobcenter KdU 2024). The imprint at https://bundesrechnungshof.de/impressum states that texts and images are urheberrechtlich geschützt and that use beyond personal use needs permission.
  - Rechnungshof von Berlin (Jahresbericht 2019). The impressum (https://www.berlin.de/rechnungshof/veroeffentlichungen/archiv/artikel.385436.php) protects website content and allows only private copies unless the court consents. That is an explicit rights notice, so § 5 UrhG is not asserted.
  - Rechnungshof der Freien Hansestadt Bremen (Jahresberichte 2024). The site impressum (https://www.rechnungshof.bremen.de/impressum) places website content under CC BY-NC-ND unless a file states otherwise; that is an explicit rights notice, so § 5 UrhG is not asserted. The Lead-archived PDF at `~/projects/_manual_archive/institutions_media/rh_bremen_jb2024.pdf` (7,007,314 bytes, sha256 `1d5a8bfa3e5a6200b190455c0eadb1bde150a15533d95499070301272bfd53a6`) stays local for verification only and must never be republished. The `source` row cites the official URL and records that provenance restriction.
  - The same reserved-rights licence is wired for every other Rechnungshof whose opened imprint claims rights (RH-BB, ORH-BY, RH-BW, RH-HE, LRH-NI, LRH-NW, RH-RP, RH-SN, LRH-ST, LRH-SH, TRH-TH), even though those courts have no stored report in this pass.
- DIP citation instead of the reserved-rights BRH source: Ergänzungsband 2022, Bemerkung 28, is also Bundestag Drucksache 20/6530 (DIP id 267178). The stored row cites `https://dserver.bundestag.de/btd/20/065/2006530.pdf` (verified HTTP 200, `%PDF-1.7`, 3,033,320 bytes; quotes checked on printed S. 48) and the DIP catalog `https://dip.bundestag.de/drucksache/267178`, with licence `TODO: DIP Nutzungsbedingungen pending Lead confirmation` and `redistribute_fulltext=1`. Locators are `BT-Drs 20/6530, S. 48, Bemerkung 28`.
- Scoped § 5 UrhG, `redistribute_fulltext=1`, only where the opened official pages state no explicit rights notice for the report text:
  - Rechnungshof Hamburg (3 stored sources): Jahresberichte page and the generic hamburg.de impressum state no report-text reuse terms.
  - Landesrechnungshof Mecklenburg-Vorpommern and Rechnungshof Saarland (no stored reports this pass): same finding on the opened official pages.
- Quotes on reserved-rights rows are trimmed to at most two sentences (abbreviations such as `Mio.` and `Mrd.` are not treated as sentence ends). The `source` table gets `redistribute_fulltext` via `ALTER TABLE` in the domain module (`ensure_source_extensions`); workers do not edit `ingest/schema.sql`.

Gaps:

- The official Bremen PDF URL still does not return a PDF to deck; the report is stored only because of the verified Lead archive described above.
- No verified on-topic official PDF stored for BB, BY, BW, HE, MV, NI, NW, RP, SL, SN, ST, SH, TH. Official indexes were checked; this pass did not download every historical Jahresbericht PDF of every Land (Berlin 2015-2017 and 2020 also remain unchecked because of HTTP 429).
- Berlin Jahresbericht 2018 mentions Obdachlosigkeit only in a refugee-procurement contribution and was not stored. Hamburg Jahresbericht 2024 has only an incidental PG 253.03 mention and was not stored.
- Court decisions are out of scope for this domain (Counts & Law).


## Berlin PARDOK drift (16 dropped rows)

On 21 November 2026 a `--dry-run --landtag-only` run around 02:10 Europe/Berlin (UTC+1; log window 01:08–01:13 UTC) still saw PARDOK `numFound=284` but stored only 268 papers (266 `verified_pdf`, 2 `unavailable`). An earlier dry-run the same day had stored all 284 as `verified_pdf`. This was not a unique-URL / `#dip_id` dedup bug: `store_drucksache` correctly keeps Anfrage/Antwort pairs that share a PDF, and those 16 rows were never written.

Root cause: the official PARDOK PDF host (`starweb`) returned HTTP 503 on both the ranged PDF probe and the follow-up catalog probe, in a burst around 01:08–01:09 UTC. `_probe` was a live `requests.get` with no retry or backoff, so a 503 was final. `store_drucksache` then refused the Landtag row because it had neither `pdf_status=verified_pdf` nor `catalog_ok`. Of 284 document probes in that run, 266 PDF-range requests returned 206 (stored as verified), and 18 PDF-range requests returned 503. Of those 18, 2 catalog probes returned 200 (stored as `unavailable`) and 16 catalog probes also returned 503 (dropped). The 16 dropped probes involve 12 unique PDF URLs; some Schriftliche Anfrage/Antwort pairs share a PDF and were both dropped.

The 16 dropped probes, all HTTP 503 on the PDF and on the catalog, around 02:08–02:09 Europe/Berlin (01:08–01:09 UTC):

1. `S19-24131.pdf` — “Warum nutzt der Senat erfolgreiche Instrumente zur Überwindung von Wohnungslosigkeit wie die Erprobungsklausel nicht ausreichend?” (API has Antwort D-440254, 2025-10-27, and Schriftliche Anfrage D-440253, 2025-10-14; only one of the pair was in the 16 dropped probes).
2. `d19-2635.pdf` — Antrag D-437830, Drs 2635 (2025-09-02), “Wohnungs- und Obdachlosigkeit beenden V – Versorgung mit Wohnraum…”.
3–4. `S19-23200.pdf` twice — Antwort D-436154 and Schriftliche Anfrage D-436153, “Kosten der Wohnungslosigkeit in Berlin (Teil 2)”.
5. `d19-2548.pdf` — Antrag D-434968, Drs 2548, “Wohnungs- und Obdachlosigkeit beenden IV - EU-Bürger*innen…”.
6. `d19-2528.pdf` — Beschlussempfehlung D-434358, Drs 2528, “Menschen vor dem Erfrierungstod bewahren…”.
7–8. `S19-22796.pdf` twice — D-434706 / D-434705, “Absage der Strategiekonferenz…”.
9. `d19-2485.pdf` — Antrag D-433502, Drs 2485, “Wohnungs- und Obdachlosigkeit beenden III - Hilfen nach § 67 SGB XII…”.
10–11. `S19-22334.pdf` twice — D-432463 / D-432462, “Was kostet was in der Wohnungsnotfallhilfe?”.
12, 14. `S19-21807.pdf` twice — D-426718 / D-426717, “Wohnungslosigkeit von queeren Menschen”.
13. `d19-2311.pdf` — Antrag D-426434, Drs 2311, “Wohnungs- und Obdachlosigkeit beenden II - Prävention stärken”.
15. `d19-2238.pdf` — Antrag D-425005, Drs 2238, “Wohnungs- und Obdachlosigkeit beenden I - Mehr Schutz… obdachlose Frauen*”.
16. `S19-21498.pdf` — “Schutzklausel in Mietverträgen bei landeseigenen Wohnungsunternehmen bei Wohnungsnotfällen” (API has Antwort D-424993 and Schriftliche Anfrage D-424986; only one of the pair was in the 16 dropped probes).

Two further papers were stored as `unavailable` (PDF 503, catalog 200): `S19-24301.pdf` (D-441434 / D-441433, Leopoldplatz) and `S19-21435.pdf` (D-424589 / D-424588, Kältehilfe Steglitz-Zehlendorf).

Fix: `_probe` now retries up to four times with a polite wait and exponential backoff (1s…16s) on HTTP 429, 500, 502, 503 and 504 and on `RequestException`, honours a numeric `Retry-After` capped at 30 seconds, and logs `attempt=N`. `ingest_pardok` records each dropped row as `PARDOK not stored (N): dip_id nummer pdf_status=… catalog_ok=…`.

Post-fix `--dry-run --landtag-only` on 21 November 2026, 02:28–02:34 Europe/Berlin (UTC+1), in memory, no `data/atlas.db`: PARDOK `numFound=284`, stored 284 (`verified_pdf=283`, `unavailable=1`). The 16 previously dropped probes were stored. The one remaining unavailable PDF is `S19-24851.pdf`, Antwort D-443979, 2026-01-29, “Dokumentation bei Housing First Projekten” (the official PDF URL did not verify in this run). The two papers that had been stored as unavailable in the 02:10 run (`S19-24301.pdf` Leopoldplatz and `S19-21435.pdf` Kältehilfe Steglitz-Zehlendorf) verified in this pass. Combined Landtag counts: BE=284, BB=26, BY=1, total 311 drucksache rows; 0 NULL licences.

## court leads for Counts & Law

Court ingest in this domain has been stopped. The nine asylum-return BVerwG decisions that were stored from the official Obdachlosigkeit search (all Sachgebiet Asylrecht: homelessness as a risk after return to another Member State, not provision in Germany) have been removed from the module, and `institutions_media_courts.py` is no longer run. The BVerwG host is left alone. Counts & Law already holds BVerwG 1 C 4.20 and 4 C 9.18 and the BayVGH decisions; those are not repeated here.

The one first-page official hit that looked genuinely domestic, and is not already on that list, is:

- Bundesverwaltungsgericht, Urteil 24.06.2021, Az. 5 C 7.20, official URL https://www.bverwg.de/de/240621U5C7.20.0 (ECLI not retrieved; the decision page returned HTTP 403 from this environment and was not fetched again). Official Sachgebiet: Jugendhilfe- und Jugendschutzrecht. The official search teaser concerns a stay in a gemeinsame Wohnform and taking a private flat there “zur Vermeidung von Obdachlosigkeit”, then admission to a psychiatric facility — German youth/welfare provision, not an asylum-return case.

No other domestic-relevant court leads were verified in this pass. The official BVerwG Obdachlosigkeit search reported 41 hits; the rest of the first page was Asylrecht (or the two decisions already held by Counts & Law). Pagination and other terms were blocked by a WAF. `rechtsprechung-im-internet.de` has no titles in its TOC, the official BVerfG site returned HTTP 400, and no Land decision database was ingested.


## Jobcenter and Sozialämter

In-memory `--dry-run --jobcenter-only` on 21 November 2026 around 03:07 Europe/Berlin (UTC+1). No `data/atlas.db`. Official Statistik der Bundesagentur für Arbeit tables only, Gebietsstand 12.11.2026:

- Catalog: https://statistik.arbeitsagentur.de/DE/Navigation/Grundlagen/Klassifikationen/Regionale-Gliederungen/Gebietsstruktur-Traeger-Grundsicherung-Nav.html
- `Gebietsstruktur-Traeger-Grundsicherung-XLS.xlsx` (404 Jobcenter, 300 gemeinsame Einrichtungen and 104 zugelassene kommunale Träger)
- `Zuordnung-Jobcenter.xlsx` (412 official Kreis assignments, 401 distinct 5-digit AGS; some Kreise are split and 6 Jobcenters cover more than one Kreis)

Stored: 404 `org` rows (`org_type=government`, role `jobcenter`, subtype `gE` or `zkT`, Träger-Nr as `register_id`) and 412 `institutions_media_org_kreis` rows. Kreis AGS are taken from the official table only (leading zeros restored when a spreadsheet cell dropped them; no codes invented). Where a Jobcenter covers more than one Kreis, `org.kreis_ags` is left NULL and the assignments live only in the mapping table. No Jobcenter street addresses were stored from this table (the Statistik file itself says official Träger details should be taken from the SGB-II-Träger websites, which were not harvested this pass).

Licence (one `source` row, `redistribute_fulltext=1`, 0 NULL, 0 TODO): the Statistik imprint at https://statistik.arbeitsagentur.de/DE/Home/Service/Impressum/impressum_node.html allows unrestricted use of statistical tables the BA publishes under its statutory duty, with attribution `© Statistik der Bundesagentur für Arbeit`, no alteration, and own calculations marked as such. That wording is stored on the source. This is not a reserved-rights source.

Counts by Land (gE + zkT = total): BB 11+7=18, BE 12+0=12, BW 33+11=44, BY 83+10=93, HB 2+0=2, HE 11+16=27, HH 1+0=1, MV 7+1=8, NI 29+16=45, NW 35+18=53, RP 26+5=31, SH 13+2=15, SL 3+3=6, SN 8+5=13, ST 8+6=14, TH 18+4=22.

Sozialämter: no official federal directory of örtliche Träger / Sozialämter by Kreis was found. SGB XII names Kreise and kreisfreie Städte as the local carriers, but that is not a published office list and was not turned into invented org rows. Official Land directories exist (Service Brandenburg has a CSV; BayernPortal; LAS Sachsen-Anhalt) and remain a gap for a later pass.


## Wohnungslosenhilfe umbrella bodies

In-memory `--dry-run --umbrellas-only` on 21 November 2026 around 03:08 Europe/Berlin (UTC+1). No `data/atlas.db`. Organisation level only, from the official BAG W membership page https://www.bagw.de/de/bag-w/mitgliedschaft (HTTP 200). Member-facility addresses were not stored. The page names 240 Träger with 1015 Mitgliedseinrichtungen (Stand Juni 2026) but does not publish that directory, so those bodies were not stored. Landesarbeitsgemeinschaften are not listed on this official page and remain a gap.

Stored 7 `org` rows (`org_type=nonprofit`, `land=DE`, `redistribute_fulltext=0`), all with a verified official website:

- Bundesarbeitsgemeinschaft Wohnungslosenhilfe e.V. (role umbrella / bundesverband), https://www.bagw.de
- Diakonie Deutschland - Evangelischer Bundesverband, https://www.diakonie.de/
- Deutscher Caritasverband e.V., https://www.caritas.de/
- Der PARITÄTISCHE Gesamtverband, http://www.der-paritaetische.de
- Die Arbeiterwohlfahrt, http://www.awo.org
- Evangelischer Bundesfachverband Existenzsicherung und Teilhabe (EBET, Diakonie specialist association), http://www.ebet-ev.de
- Katholische Bundesarbeitsgemeinschaft Wohnungslosenhilfe (KAG W, Caritas specialist association), http://www.kagw.de

Licence: the BAG W imprint (https://www.bagw.de/de/impressum) claims copyright in the site’s texts and images and allows reuse only after consultation / with a source citation. That is an explicit rights notice, so the reserved-rights licence string is stored and the full page text is not redistributed. Only facts, metadata, official URLs and (if needed) short § 51 quotes are kept. 0 NULL licences, 0 TODO.


## Kältehilfe and official Notunterkünfte

In-memory `--dry-run --shelters-only` on 21 November 2026 around 03:20 Europe/Berlin (UTC+1). No `data/atlas.db`. Organisation/facility level as published by the official source. Stored 111 `facility` rows and 111 `institutions_media_shelter` sidecar rows (112 store attempts). The 112-vs-111 mismatch is an intentional dedup of an official Hamburg duplicate: the GeoJSON lists both `Harburg Huus` (`kind=notunterkunft`) and `Harburg-Huus` (`kind=tagesaufenthalt`) at the same address, Außenmühlenweg 10b, 21073 Hamburg. `name_norm` folds the hyphen, so both become `HARBURG HUUS` and share the generated `official_key` `HH-OD:harburg-huus-aussenmuehlenweg-10b-21073-hamburg`. Upsert therefore keeps one `facility` row (the second write wins: hyphenated name, `tagesaufenthalt`) and one sidecar row. Confirmed against the archived official GeoJSON on 21 November 2026 (Europe/Berlin). `protected_with_location=0`. No Ansprechperson names stored. 0 NULL licences, 0 TODO.

Sources and counts:

- Berlin Kältehilfe, 39 official offers from the Senate-commissioned directory https://kaeltehilfe-berlin.de/kaeltehilfe-angebot (paginated Joomla list, `?start=0…35`, 39 unique offers). No open-data Kältehilfe export exists on daten.berlin.de; the Senate page points to kaeltehilfe-berlin.de. Licence: imprint reserves copyright, so reserved-rights terms plus `redistribute_fulltext=0`. Public “Notübernachtung für Frauen” / “Notunterkunft für Frauen” entries are stored as `notunterkunft` with the published address (they are public emergency offers, not Frauenhäuser).
- Hamburg official open data, 51 offers (50 unique after the Huus name-variant collapse) from the Sozialbehörde / LGV WFS, GeoJSON download https://geodienste.hamburg.de/download?url=https://geodienste.hamburg.de/HH_WFS_Uebernachtungsangebote&f=json, capabilities at https://geodienste.hamburg.de/HH_WFS_Uebernachtungsangebote. This already includes both Winternotprogramm sites: Friesenstraße 22 (400 places) and Châu-und-Lân-Straße 6 (300 places). Kinds as published: 23 shelter / Übergangswohnen, 10 Tagesaufenthalt, 6 Übernachtungsstätten (`notunterkunft`; one of the 7 raw Übernachtungs features was the Huus variant), 6 Beratung, 5 other. Licence: Datenlizenz Deutschland – Namensnennung – Version 2.0 (dl-de/by-2-0); WFS AccessConstraints state no access restrictions; `redistribute_fulltext=1`. Attribution: Freie und Hansestadt Hamburg, Behörde für Gesundheit, Soziales und Integration / Landesbetrieb Geoinformation und Vermessung.
- München, 15 address-level offers from the official city PDF “Angebote für obdachlose Menschen in München”, Stand August 2026, https://stadt.muenchen.de/dam/Home/Stadtverwaltung/Sozialreferat/wohnungsamt/Wohnungslosigkeit-akut/LHM_Angebote_fuer_Obdachlose.pdf. Includes the Übernachtungsschutz at Lotte-Branz-Straße 5 and a public women-only Frauenobdach (address withheld here; women-only offers are stored at city level). The city impressum URL `stadt.muenchen.de/impressum.html` returned 404, so reserved-rights terms plus `redistribute_fulltext=0` are stored until an open imprint is confirmed. `Wärmebus` / `Behandlungsbus` listings that only point at already-stored sites were not stored as separate facilities. A second Beratungsstelle at Schellingstraße 65 (Paare und Familien) was not stored separately because the parser keeps one facility per address from this PDF.
- Köln, 7 official Notschlafstellen from https://www.stadt-koeln.de/service/produkte/00871/index.html (Elisabeth-Fry-Haus and Comeback for women, Johanneshaus, Don-Bosco-Club, SKM Drogen, NOTEL, SKM EU). The municipal contact office ResoDienste was not stored as a Notschlafstelle. The city impressum returned HTTP 403, so reserved-rights terms plus `redistribute_fulltext=0` are stored.

Protection policy (filters + tests): explicit Frauenhaus / Frauenschutzhaus / Schutzwohnung / Zufluchtswohnung / Zufluchtshaus / Gewaltschutzhaus or -einrichtung / protected-shelter terms force `is_protected=1` and store no location at all: no address, postcode, coordinates, or AGS (`kreis_ags` is left NULL even when the offer comes from a city directory whose Kreis key is otherwise known). Women-/youth-/LGBTQ-only public official offers are not secret shelters; they stay at city/district level, including the official city-level Kreis AGS, with no street, PLZ or coordinates. On 21 November 2026 this AGS tightening touched 0 live official rows: none of the 111 current Kältehilfe/Notunterkunft facilities is a secret Frauenhaus or Schutzwohnung (`is_protected=1` count is 0; 22 are restricted-group and keep the city-level key).

Gaps:

- Frankfurt official pages (`frankfurt.de`) returned HTTP 403 from this environment and were not retried aggressively.
- Other large cities (Düsseldorf, Stuttgart, Leipzig, and so on) were a gap in the first four-city pass; official lists for nine further cities are in the later section 'Further official city shelter lists'.
- Landesarbeitsgemeinschaften Wohnungslosenhilfe are not in a single official national directory (the BAG W membership page also does not list them). Verified Land-level umbrellas from official Land sites are in the later section '(j) LAG Wohnungslosenhilfe and Land-level umbrella bodies'.
- Berlin has no official open-data Kältehilfe export.

`--selftest` and `tests.test_institutions_media` (33 tests) pass. Run with `--dry-run --shelters-only`. Workers must not write `data/atlas.db`.


## Women-, youth- and LGBTQ-only offers: district level only

In-memory `--dry-run --shelters-only` on 21 November 2026 around 03:28 Europe/Berlin (UTC+1), after the Lead's location policy. No `data/atlas.db`. 35 tests and `--selftest` pass. `restricted_group_with_street=0`, `protected_with_location=0`.

Women-only, youth-only and LGBTQ-only official offers (including public Notübernachtung für Frauen and Frauenobdach) are no longer stored with a street, postcode or coordinates. They stay in the directory at Bezirk/Stadtteil level where the official source publishes a district, and always keep `official_url` pointing at the city's own page or official dataset so people can find the offer there. Secret Frauenhaus / Schutzwohnung rows remain fully protected (`location_precision=protected`, no district, and no `kreis_ags` or other AGS). Mixed and general Notunterkünfte, including men-only offers and “Männer und Frauen”, keep the published street address.

21 of 111 facilities were reduced to district level:

- Berlin: 8 (all with an official Bezirk from kaeltehilfe-berlin.de, and a per-offer official URL), including “Notübernachtung für Frauen in Evas Haltestelle”, “24/7 Notunterkunft für Frauen Kreuzberg” and “NÜ Home & Care Reinickendorf” (`nur Frauen`).
- Hamburg: 7 (Frauenzimmer / FrauenProjekte / Kemenate / JEP I / Frauen Wohn Projekt Wilhelmsburg). The official GeoJSON has no Stadtteil field; Wilhelmsburg is taken from the official name, the others are stored at city level with a link to the official WFS. “Projekt Ankerplatz (für haftentlassene Männer und Frauen)” is mixed and keeps its address.
- München: 3 (Frauenobdach Karla 51 and two official women's counselling offices). The city PDF does not publish a Stadtbezirk, so these are city-level with a link to the official PDF.
- Köln: 3 (Elisabeth-Fry-Haus and Comeback, women-only, Stadtteile Köln-Raderthal and Köln-Innenstadt; Don-Bosco-Club youth night shelter, Köln-Mülheim). Official URL is the city's Notschlafstellen page.



## Further official city shelter lists

Rebased onto `2139d37` and made handoff-ready on 21 November 2026 (Europe/Berlin). Official Kreis AGS is stored for restricted-group and mixed offers; protected (`is_protected=1`) rows store no AGS. In-memory catalogue checks and the earlier `--dry-run --shelters-only` (04:22 Europe/Berlin, UTC+1) found:

Combined total: 176 `facility` rows and 176 `institutions_media_shelter` sidecar rows (previous 111 from Berlin, Hamburg, Munich and Cologne, plus 65 newly stored). `protected_with_location=0`, `restricted_group_with_street=0`, `restricted_group_district_only=41`. 0 NULL licences, 0 TODO. 14 source rows: 10 reserved-rights, 3 scoped amtliches Werk § 5 UrhG (Leipzig and the two Dresden pages), 1 Hamburg dl-de/by-2-0. Additional official municipal overnight offers were added for Düsseldorf, Stuttgart, Leipzig, Dresden, Hannover, Essen, Dortmund and Nürnberg (Bremen's official service page returned HTTP 403 from the deck environment, so its 4 catalogued offers were not stored). A facility is stored only when its name and published location appear in a fetched official HTTP 200 page or PDF. Day centres, Wärmestuben, Beratungsstellen and other offers with no overnight place were not stored. Women-only, youth-only and LGBTQ-only offers are district-level where the official source names a Stadtteil (otherwise city-level) with `official_url` to the city's own page; mixed, general and men-only offers keep the published street address. No Frauenhaus address or coordinates are stored. Personal e-mail addresses from official pages were not stored.

Sources, licences and counts from this pass:

- Düsseldorf, official Winternothilfe page. Impressum reserves all rights including reproduction. 8 overnight offers (Graf-Adolf-Straße mixed 78 places; Harkortstraße and Kaiserswerther Straße / K 13 men-only, addresses kept; Ariadne for women, Knackpunkt for girls and young women to 26, and Sleep In for ages 14–21 at district/city level; Up Stairs mixed; Eisenstraße 49 winter overflow, not a direct Anlaufstelle). Berger Kirche and the Wärmezelt Moskauer Straße are day-only and were not stored. The open-data CSV was not used; the official HTML page was sufficient and the open-data host failed TLS in this environment.
- Stuttgart, official PDF “Notaufnahmemöglichkeiten für Wohnungslose im Winter 2026/2027”, Stand August 2026. Impressum allows private copies only, no distribution. Overnight/Notaufnahme entries only (Beratung and Tagesaufenthalt sections omitted). Women-only pensions and houses at district level where the PDF names Bad Cannstatt, Stuttgart-Ost or Stuttgart-Mitte; Johannes-Falk-Haus (junge Erwachsene, men) at Stuttgart-Nord; mixed and men-only houses keep the published address.
- Leipzig, official Sozialamt page. The leipzig.de imprint states no text-reuse terms, so the cited page text is treated as an official work under § 5 UrhG (scoped, stated explicitly). Six overnight houses (Rücke, Helene and Scharnhorststraße for men; the women’s house at city level; Alternative I and III mixed). Tagestreffs were not stored.
- Dresden, official Übergangswohnheim page (Notaufnahme Hechtstraße 10) and official Nachtcafé calendar (seven rotating church overnight offers, 1 Nov–31 Mar, 19–7 Uhr, published addresses kept). The dresden.de imprint states no text-reuse terms (Haftungsausschluss only); cited page text is scoped amtliches Werk, § 5 UrhG.
- Hannover, official Notschlafstellen page. Impressum: reproduction by third parties only by agreement. Two women’s Notschlafstellen at city level (no official Stadtteil on the page); four mixed/men/family sites keep addresses. Day-only Tagesaufenthalte were not stored.
- Bremen: the official service.bremen.de page (Notunterkunft als wohnungslose Person nachfragen) returned HTTP 403 from the deck environment, so none of the four catalogued overnight offers (Rembertiring men, the women-only offer, Sleep Inn and La Campagne) were stored. The same URL had returned HTTP 200 from another network earlier in the pass; this is recorded as a fetch gap, not as a zero. The imprint of that page (fetched earlier) forbids reproduction or passing on of the texts. A previously mentioned Kälteregelung address was not used, because it could not be verified on a 200 official page from this environment.
- Essen, official essen.de press page naming overnight offers. Impressum requires prior consent for reproduction. Lichtstraße 1 (men, address kept), a women-only site in Kray (district only), RAUM 58 for youth 14–21 in the Nordviertel (district only), Hoffnungstraße mixed drug-use overnight, and DRK Wärmezelte at Wolfsbankring 5a when two nights of −3 °C are expected. The Tagesaufenthalt on Steeler Straße was not stored.
- Dortmund, official “Existenzielle Hilfen” PDF (Stand 12/2025) plus the official 8 January 2026 frost press page. Impressum: personal information only; further use prohibited without consent. Frauenübernachtungsstelle at city level (address stripped); Männerübernachtungsstelle Unionstraße 33 and SW 42 / Schwanenwall 42 keep addresses; Gap Jump (junge Erwachsene, contact via the men’s house, no own address in the PDF) and Sleep-In Stellwerk for youth (named without an address on the press page) at city level; Akut-Notschlafstelle Leuthardstraße 7 (mixed, seasonal) keeps its address; overflow site Mergelteichstraße is stored with the street name as published (no house number).
- Nürnberg, official Obdachlosenhilfe page. Haftungshinweis: copies for private use only; any further exploitation needs written consent. Five general/men’s overnight houses keep addresses; Haus für Frauen, Refugium and Catherine-Booth-Haus at city level; SleepIn for ages 14–21 at city level; Hängematte mixed drug-use overnight keeps its address. Tagestreffs were not stored. Transit-link coordinates on the city page were not copied.
- Count by city in this pass: Düsseldorf 8, Stuttgart 15, Leipzig 6, Dresden 8, Hannover 6, Essen 5, Dortmund 7, Nürnberg 10, Bremen 0 (HTTP 403). Total new stored: 65.

Frankfurt official `frankfurt.de` Notschlafstellen and Kältebus pages still returned HTTP 403 to the project user agent after a polite single retry and were not stored.


## Press investigations

In-memory `--dry-run --investigations-only` on 21 November 2026 around 03:28 Europe/Berlin (UTC+1). No `data/atlas.db`. Curated list, quality over quantity: 21 investigations stored from a catalog of 21 (`doc.kind=investigation` plus `institutions_media_investigation`). Every URL returned HTTP 200 and the stored short quote was found verbatim on the fetched page. Author is left empty. 0 NULL licences, 0 TODO, all `redistribute_fulltext=0`.

Outlets: CORRECTIV (3 fact-checks on counts and the right to shelter), NDR Panorama – Die Reporter (2), Deutschlandfunk (2), ZDFinfo / ZDF (2), DER SPIEGEL (1), WDR (1), taz (3), Süddeutsche Zeitung (1), rbb / Die Story im Ersten (1), SWR Aktuell 360 Grad (1), Report Mainz (1), tagesschau (2), MDR exakt (1). Dates range from 2017 to 2026.

Licence: no piece stated a Creative Commons licence. CORRECTIV’s “Steal Our Stories” reuse policy is not CC, so the reserved-rights string is used for CORRECTIV as well as for the public broadcasters and newspapers, with only a short § 51 quotation in `doc.summary`. Full article text is not stored.

Private individuals who are not in public roles are not named in stored fields (title, quote, outlet). A denylist plus tests drop first names that appeared in candidate pages (for example Frank, Ulf, Kurt, Sandro). The MDR teaser names correspondent Daniel Tautz, which is a public professional role.

Gaps: DIE ZEIT (HTTP 403 from this environment); a Spiegel+ feature with no usable free-text quotation; ZDFzoom “Leben ohne Zuhause” was only found as a presseportal.de notice, not an official zdf.de page; FAZ and other paywalled newspaper investigations were not added.

`--selftest` and `tests.test_institutions_media` (34 tests) pass. Run with `--dry-run --investigations-only`. Workers must not write `data/atlas.db`.

## Drogentote per Land

In-memory `--dry-run --drogentote-only` on 21 November 2026, Europe/Berlin (UTC+1). No `data/atlas.db`. Official sources only: BKA Bundeslagebild Rauschgiftkriminalität 2022–2025 and the Drogenbeauftragter tables that cite Bundeskriminalamt Wiesbaden. Every stored number has a locator and a short quote that was found in the cited document. 0 NULL licences, 0 TODO. BKA and Drogenbeauftragter imprints reserve rights, so every source uses the reserved-rights string and `redistribute_fulltext=0` (facts, metadata and short § 51 quotes only).

Notable cited figures:

- 2025: 2.150 drogenbedingte Todesfälle in Germany (BKA Lagebild 2025, S. 23; +0,6 % vs 2.137 in 2024). 1.777 men, 373 women. Mean age 40,61 years (Drogenbeauftragter table 2025). The 2025 Lagebild has no extractable 16-Land table.
- 2024: 2.137 (Lagebild 2024, S. 21; −4,0 % vs 2.227 in 2023). 1.747 men, 390 women. Mean age 40,7. Land figures named in running text only: Nordrhein-Westfalen 769, Berlin 294, Bayern 214, Baden-Württemberg 195, Bremen 35, Rheinland-Pfalz 33, Sachsen 28, Brandenburg 17. Berlin had the highest per-capita burden, then Hamburg and Bremen (no official per-capita rates stored, because they appear only as an unlabelled map).
- 2023: 2.227 (Lagebild 2023, S. 23), the peak since the series began. 1.844 men, 383 women. Named Land figures: Nordrhein-Westfalen 872, Berlin 271, Bayern 257, Sachsen-Anhalt 52, Schleswig-Holstein 42.
- 2022: complete official Land table published with the 11.05.2023 Drogenbeauftragter press release “2022 erneuter Anstieg bei Zahl der Drogentoten” (PDF heading is only “Anzahl der Rauschgifttoten”; the year is taken from that official press packaging, and the sums match the 2022 Lagebild). Summe 1.990 (1.648 men, 342 women, mean age 40,6). All 16 Länder: NW 703, BY 277, BE 230, BW 179, NI 117, HE 97, HH 96, SH 56, RP 52, SL 43, TH 33, HB 29, BB 24, SN 24, ST 19, MV 11.

Caveats stored with the slice: since 2022 the BKA and IFT München changed how causes of death are counted, so cause breakdowns are not directly comparable with years before 2022. Land figures can be revised after the 31 January reporting date.

Gaps: no official complete 16-Land table was found for 2023, 2024 or 2025 (guessed 2024 Land-table URLs on bundesdrogenbeauftragter.de returned HTTP 500 and were not retried aggressively). The official Lagebilder and Drogenbeauftragter tables do not report drug deaths among wohnungslose people specifically; that absence is recorded as a gap, not as a zero. Map Belastungszahlen were not stored, because the Länder are not labelled in the extractable text.

`--selftest` and `tests.test_institutions_media` pass. Run with `--dry-run --drogentote-only`. Workers must not write `data/atlas.db`.

## PKS victimisation of homeless people

In-memory `--dry-run --pks-only` on 21 November 2026, Europe/Berlin (UTC+1). No `data/atlas.db`. Scope is area-level victimisation of, and offences against, homeless people only. Tatverdächtige “ohne festen Wohnsitz” are not ingested and crime is not framed as caused by homeless people.

Bund totals come from the official BKA T941 workbooks (Opferspezifik — Opfer wegen persönlicher Beeinträchtigung, Spalte Obdachlosigkeit), licence Datenlizenz Deutschland – Namensnennung – Version 2.0 with the required attribution “PKS Bundeskriminalamt, Berichtsjahr, Version”, `redistribute_fulltext=1`. Land totals come from the official government answer BT-Drs 21/2183 (10.10.2025), which publishes the PKS Land tables for 2022–2024; the Drucksache itself is stored under the reserved-rights string (`redistribute_fulltext=0`) because Bundestag reuse terms are not clearly granted. Bund totals in the Drs match T941 exactly. 0 NULL licences, 0 TODO. Every stored number has a locator and a short quote checked against the cited document.

Official caveats stored with every row: the PKS counts victimisations, not unique people; figures cover completed and attempted offences against highly personal legal interests only; a case is counted only when police findings show the offence was motivated by, or factually linked to, the victim’s homelessness.

Notable cited figures (Straftaten insgesamt, Opferspezifik Obdachlosigkeit):

- 2024: 2.194 victims nationally (1.673 male, 521 female). Of these, Körperverletzung 1.644, Gewaltkriminalität 955, Raub etc. 209 (offence groups can overlap and are not additive). Highest Land counts: Berlin 498, Bayern 394, Nordrhein-Westfalen 351, Hamburg 231, Baden-Württemberg 210.
- 2023: 2.180 (1.706 male, 474 female). Berlin 441, Bayern 425, Nordrhein-Westfalen 363, Baden-Württemberg 227, Hamburg 218.
- 2022: 1.986 (1.537 male, 449 female). Berlin 421, Nordrhein-Westfalen 387, Bayern 376, Baden-Württemberg 203, Hamburg 165.

All 16 Länder plus Bund are stored for each of those three years from the Drs Land tables (Bund from T941).

Gaps: no official T941 2025 workbook or 2025 Land table was found (PKS 2025 Opfer table page returned HTTP 404). No Land-level machine-readable T941 workbook was found on the BKA Bund pages. The top-25 Landkreis list in BT-Drs 21/2183 is a selected ranking, not a complete Kreis series, and was not ingested, to avoid “Brennpunkte” framing.

`--selftest` and `tests.test_institutions_media` pass. Run with `--dry-run --pks-only`. Workers must not write `data/atlas.db`.

## JVA Entlassungsmanagement and psychiatric beds

In-memory `--dry-run --jva-psych-only` on 21 November 2026, Europe/Berlin (UTC+1). No `data/atlas.db`. Facts with citations only. This slice does not ingest Destatis homelessness counts, the Wohnungslosenbericht, law or courts (Counts & Law). Destatis Grunddaten der Krankenhäuser (statistic 23111) is used only for psychiatric and psychosomatic hospital beds, clearly labelled. 0 NULL licences, 0 TODO.

JVA / Übergangsmanagement: Landtag NRW Drs 18/1283 (19.10.2022). The Land government states it has no valid data on how many people leave prison without housing; Entlassungsanschriften collected in release planning are voluntary and “stellen keine valide Datengrundlage dar.” That is stored as `jva_release_homeless_data_available=0` for Nordrhein-Westfalen in 2022, with a note that this is an official data gap, not a count of zero releases. The same answer describes the standardised access checklist, §§ 9–10 StVollzG NRW, and the rollout of structured Übergangsmanagement since 2020; where no housing can be arranged, a place in a local Notunterkunft is mediated. Licence: amtliches Werk, § 5 UrhG, scoped to the cited document text (the PDF states no terms; the previously used Landtag imprint URL returned HTTP 404).

Psychiatric beds: BT-Drs 21/6258, Anlage 1, Tabelle 1, sourced from Destatis Grunddaten and Eurostat, hospital beds in psychiatric care in Germany 2014–2023 (reserved-rights string, short quotes only). Official national stock rose from 102.916 (2014) to 110.943 (2023), with a small dip in 2020 (108.099) that is not treated as a closure. Destatis Statistischer Bericht Grunddaten der Krankenhäuser 2024, Tabelle 23111-07 (dl-de/by-2-0; imprint permits reproduction with attribution) supplies a 2024 snapshot of aufgestellte Betten by Land for Allgemeine Psychiatrie (57.090 nationally, including 13.744 in Nordrhein-Westfalen, 7.694 in Bayern, 7.227 in Baden-Württemberg), Kinder- und Jugendpsychiatrie (6.953 nationally) and Psychosomatik/Psychotherapie (13.060 nationally). These snapshots are not named hospital closures.

Gaps: no official national count of releases from prison into homelessness was found; other Länder JVA/Übergangsmanagement answers were not ingested in this slice. No official Drucksache documenting a named psychiatric hospital closure was stored. Do not infer closures from the 2020 dip or from a single-year bed snapshot.

`--selftest` and `tests.test_institutions_media` pass. Run with `--dry-run --jva-psych-only`. Workers must not write `data/atlas.db`.

## Studies catalogue

In-memory `--dry-run --studies-only` on 21 November 2026, Europe/Berlin (UTC+1). No `data/atlas.db`. Before ingest, `research/counts_law.md` was read on the Counts & Law worktree (`worker/counts_law`, then at `46873a1`). Counts & Law already holds the Wohnungslosenbericht 2022/2024, the BAG W Hochrechnung 2018–2024, the NRW Wohnungsnotfallberichterstattung, the Berlin Nacht der Solidarität headcounts from Drs. 19/10884, the Hamburg GOE 2018 study, München Produktcontrolling and the BW GISS 2015 study plus Liga BW Stichtagserhebung. Those documents were not added again, and none of their headline person/household counts is stored here.

A study is stored as `doc.kind=study` plus `institutions_media_study` (commissioning body, authors' organisation, year, optional DOI). Every source has a licence and a URL verified HTTP 200 with the project UA. Metrics are stored only when a short locator quote is present in the official PDF (layout and raw `pdftotext` streams, so two-column pages still match) and only when `figure_held_by_counts_law` does not flag the value. Authors are institutions or public-role researchers; no private contact addresses are stored. Open-access papers keep CC BY 4.0 and `redistribute_fulltext=1`. Sources whose imprint reserves rights use the reserved-rights string, facts/metadata/short § 51 quotes only, and `redistribute_fulltext=0`. BMAS Forschungsberichte and the Hamburg Bürgerschaft Drs. use scoped `amtliches Werk, § 5 UrhG` for the cited text, because those imprints state no text-reuse terms.

Catalogue (11 study documents):

1. BMAS Forschungsbericht 534 (2019), GISS, commissioned by BMAS. Official PDF on bmas.de. Structural figures only: 45.740 threatened households in 81 municipalities in 2017; density 5,8 per 1.000 households (method chapter; the Kurzbeschreibung wording “je 1.000 Einwohnerinnen und Einwohner” is not used); rent arrears 85 % of prevention triggers; prevention action in 84 % of known cases; homelessness prevented in just under 63 % of cases with a known outcome. The 31.05.2018 national stock estimate is stored as two metric rows, low 313.000 and high 337.000, each with is_est=1, locator PDF-S. 5, a verbatim Kurzbeschreibung quote, and series label exactly “BMAS FB 534 Schätzung 2018” in metric.note, so it can be shown beside later Counts & Law series.
2. BMAS Forschungsbericht 605 (2022), GISS and Kantar Public, commissioned by BMAS. Official PDF on bmas.de. This is the empirical study behind the Wohnungslosenbericht 2022, not the Bericht itself. Stored as a document plus the sample-design fact of 151 municipalities (1–7 February 2022). Unsheltered/hidden/total counts from the 2022 Bericht are not stored.
3. BAG W Statistikbericht 2024 (Lebenslagenbericht, published 2026), Sarah Lotties, BAG W. Official PDF on bagw.de. Stored: around 73 % of DzW clients were acutely homeless (contiguous quote on PDF-S. 4). The printed sentence on 248 participating facilities and 45.026 anonymised records is not contiguous in the archived `pdftotext -layout` text (two-column interleaving), so those two figures were dropped rather than reconstructed. This is not the BAG W Hochrechnung already held by Counts & Law. BAG W imprint reserves copyright; reserved-rights terms.
4. Housing First Berlin evaluation, end report December 2021, Susanne Gerull, Alice Salomon Hochschule Berlin, commissioned by Neue Chance gGmbH and the Berliner Stadtmission with SenIAS funding. Official berlin.de PDF. 611 applications, 44 admissions, 40 people housed, 37 still in support on 30.09.2021 (period 01.10.2018–31.08.2021). Reserved-rights terms, consistent with other Berlin official sources.
5. Housing First für Frauen Berlin evaluation, end report December 2021, same author and host. Official berlin.de PDF. 377 applications, 75 admissions, 38 women and one non-binary person housed, 41 still in support on 30.09.2021; housing retained for 100 % of housed users. The 41 still in support include two people not yet housed (39 already housed plus two leases shortly before completion; PDF-S. 30, Abschnitt 4.1: „zwei weitere Mietverträge standen zu diesem Zeitpunkt zudem kurz vor dem Abschluss.“). Figures 75 / 39 / 41 are stored verbatim. Project-level figures only; no street address. Reserved-rights terms.
6. Housing First Hamburg evaluation, Abschlussbericht 2025, Peer Gillner (Lawaetz-Stiftung) and Gerd Walter (SÖSTRA), Anlage 2 to Bürgerschaft Drs. 23/5727 of 16.10.2026. Official ParlDok PDF (HTTP 200). 37 tenancies against 30 planned; 36 people still in open-ended tenancies. Scoped § 5 UrhG as for other Hamburg official documents.
7. Susanne Gerull, *1. Nacht der Solidarität. Neu- und Weiterberechnung der Befragungsdaten*, 25.09.2020, commissioned by SenIAS, official berlin.de PDF. A different document from Drs. 19/10884. Survey interview counts only: up to 282 street-count interviews and up to 320 Kältehilfe interviews. The 1.976 / 807 / 942 headcounts are not stored. Reserved-rights terms.
8. Knörle, Gutwinski, Willich, Berghöfer, *Bundesgesundheitsblatt* 2022, DOI 10.1007/s00103-022-03536-9, CC BY 4.0 (Projekt DEAL). Official Springer PDF. Stored as a study document (title quote, which is contiguous in the archived layout text). The Zusammenfassung sentences on the 112-patient clinic sample and 84,9 % with mental illness already present before homelessness are not contiguous in `pdftotext -layout` (two-column interleaving) and were dropped rather than reconstructed. Meta-analysis figures cited from other papers are not stored.
9. Laudien, Püschel, Lohner, Friedrich, Ondruschka, *Rechtsmedizin* 2024, DOI 10.1007/s00194-024-00723-7, CC BY 4.0. Official Springer PDF. LKA 41 Hamburg cases: 42 deaths of homeless people in 2019 and 70 in 2021.
10. Evaluation of the Housing-First-Fonds NRW, GISS for the Paritätischer Landesverband NRW, October 2020. Official GISS PDF. 22 provider contracts by mid-October 2020. Reserved-rights terms. This is not the later Düsseldorf scaling-up evaluation.
11. Handlungsorientierte Sozialberichterstattung Niedersachsen, Statistikteil 2024, LSN for the Niedersächsisches Sozialministerium, chapter 9.7. Official ministry PDF. Stored as a study document only. The NI imprint reserves copyright. Destatis 22971 and Wohnungslosenbericht 2022 reprints in that chapter are not stored.

Gaps: SEEWOLF has no open-licensed official full text (Thieme journal article and Lambertus book; the file at giss-ev.de is a review and was not stored). The GISS formative evaluation of Housing First scaling-up in Düsseldorf, announced 25.08.2026, has no published end report. Earlier BAG W Statistikberichte were not ingested (2024 only). The Berlin Sozialbericht 2025 was not ingested (it reprints Destatis/WB figures already held by Counts & Law, and berlin.de returned HTTP 429 during an earlier fetch in this pass). Hamburg GOE 2018, BW GISS 2015, NRW WNB, München Produktcontrolling and the two Wohnungslosenberichte remain with Counts & Law.

After the Lead review of run #7, study PDFs are extracted with `pdftotext -layout` only (the same rendering `common.document_text` archives). A second raw-reading-order stream is no longer concatenated before quote matching. Metrics whose quotes were only matchable in that reconstructed text were dropped: bagw_dzw_client_records (45.026), bagw_dzw_facilities (248), charite_sample_patients (112), charite_mental_illness_before_homelessness_pct (84,9 %).

`--selftest` and `tests.test_institutions_media` pass. Run with `--dry-run --studies-only`. Workers must not write `data/atlas.db`.

## Prison costs per Hafttag / Haftplatz (k)

In-memory `--dry-run --prison-costs-only` on 21 November 2026 (Europe/Berlin). No `data/atlas.db`. These are official institution costs, not a crime rate, and are not framed as caused by homeless people. Every euro figure is stored only when its short quote appears in the unmodified `pdftotext -layout` archive of the cited PDF. Metric geography is the 2-digit Land AGS (or `DE` for the published average). Competing official series are kept side by side with their own metric name and series label in `anmerkung`.

Sources (all official PDFs, not catalog or navigation pages):

- Landtag MV Drs 8/5062 (Antwort der Landesregierung, 12.07.2025), https://www.dokumentation.landtag-mv.de/parldok/dokument/64894/8_5062_entwicklung_der_kosten_in_den_justizvollzugsanstalten_in_mecklenburg_vorpommern.pdf. This is the comparable series: the official 16-Land THKS table for 2022 and 2023 (Strafvollzugsausschuss der Länder method, 117th meeting, Wiesbaden 15–17 May 2013). Thüringen did not transmit a 2022 figure. The answer says not all Länder had submitted 2024 by then, so no 2024 comparison table is stored. MV’s own totals and THKS for 2022–2024 are also stored from the table on PDF-S. 2 (Gesamtkosten rose from €67.47M in 2022 to €68.88M in 2024; THKS 174.77 / 180.84 / 188.98).
- Landtag NRW Vorlage 18/5295 (Justizministerium, 08.07.2026), https://www.landtag.nrw.de/portal/WWW/dokumentenarchiv/Dokument/MMV18-5295.pdf. Own-Land series, 2014–2025, including monthly and annual figures. 2024: €202.73 per day, €73,996.45 per year; 2025: €215.17 per day. The same ministry’s “Justiz in Zahlen” leaflet repeats the daily figures but is not used as the archived source (layout of the large euro totals is ambiguous). A footnote there, and the 2014 jump in the Vorlage table, mark a methodology break (Baukostensatz included from 2014), so earlier years were not stored. NRW’s own 2023 figure (€199.07) differs from the MV comparison table (€192.07); both are kept.
- Bayerischer Landtag Drs 19/4490 (2023) and 19/8767 (Antwort 31.10.2025, for 2024). 2023 total daily cost €185.32 (THKS €154.23, which matches the MV table, plus Bau- and Sach-Investitionssätze). 2024 total daily cost €192.95 (THKS €159.70); Justizvollzug total €661.5M (stored rounded).
- Abgeordnetenhaus Berlin Drs 19/23828 (Antwort 25.09.2025). Two official methods: after Belegungsfähigkeit and after tatsächliche Hafttage, for Tageshaftkosten and Gesamt-Tageshaftkosten, 2021–2024, plus annual totals after receipts. The MV comparison table’s Berlin 2022/2023 figures (218.36 / 220.80) match Berlin’s Tageshaftkosten after actual detention days, not the capacity series (182.87 / 185.96) and not the Gesamtsatz.
- Bürgerschaft Hamburg Drs 23/1111 (15.08.2025), Tabelle 5. Own THKS 2022 €215.67, 2023 €213.11, 2024 €204.21. Hamburg’s 2022 own figure differs slightly from the MV comparison table (€215.49); both are kept. 2025 is not yet published.

Licence: cited Landtag / Bürgerschaft text is stored as an official work under § 5 UrhG where the PDF itself states no reuse terms (Bayern’s imprint states § 5 Abs. 2 explicitly). Only facts, metadata, the official PDF URL and short quotes are kept (`redistribute_fulltext=0`). 0 NULL licences, 0 TODO.

Gaps: no official complete 16-Land THKS table for 2024; own-Land 2024 figures are still missing for most Länder (BW, BB, HB, HE, NI, RP, SL, SN, ST, SH, TH). Landeshaushalt Einzelpläne were not parsed in this pass (they rarely state a per-place unit cost as clearly as these answers). Justizministerien websites beyond the NRW leaflet were not harvested this pass.
## (l) Krankenhauspläne (psychiatric Planbetten)

In-memory `--dry-run --hospital-plans-only` on 21 November 2026 (Europe/Berlin). No `data/atlas.db`. Quotes are stored only when they appear in the unmodified `pdftotext -layout` archive. Metric geography for Land totals is the 2-digit AGS (`02` Hamburg, `03` Niedersachsen). These Planbetten / Betten-Soll figures are a different series from Destatis Grunddaten der Krankenhäuser (aufgestellte Betten, table 23111-07) already stored by `jva_psych`; they use the prefix `khplan_` and a series label in `anmerkung`.

Sources used:

- Hamburg, *Einzelblätter der Krankenhäuser zu den Feststellungsbescheiden*, Stand 01.01.2026 (canonical dokumente.hamburg.de PDF, 103 pages). Anlage 4 Fachgebiet sheets are the cited pages: PDF p. 87 FG 390 (Kinder- und Jugendpsychiatrie), p. 92 FG 820 (Psychiatrie und Psychotherapie), p. 93 FG 830 (Psychosomatische Medizin und Psychotherapie). Stored are Betten-Soll and Plätze-Soll 01.01.2026 only. Land totals: KJP 219 voll / 94 teil; Psychiatrie 1.601 voll / 823 teil; Psychosomatik 210 voll / 166 teil. 38 non-zero per-hospital rows (for example Asklepios Klinik Nord PSY 705 beds and 308 day places; UKE PSY 200, KJP 62, PSM 24; Asklepios Klinikum Harburg PSY 185, KJP 45; Schön Klinik Hamburg Eilbek PSY 118, PSM 82). Anlage 5 (pp. 98–99) is a smashed wide table and is not used.
- Niedersachsen, *Krankenhausplanbetten / teilstationäre Plätze nach Fachrichtungen*, Stand 1. Januar 2024. Only the official Land total line is stored this pass, including the typo „Kapaziäten“ as printed: KJP 731, Psychiatrie 5.370, Psychosomatik 973 vollstationär; 401 / 1.600 / 222 teilstationär. Per-hospital NI rows wrap or truncate in the layout extract, so they are not stored rather than guessed.

Linking: every official Hamburg hospital row is kept in the sidecar `institutions_media_khplan`. A facility metric (`entity_type='facility'`, `entity_id=<qid>`) is written only when the official hospital name uniquely matches an existing psychiatric / `psych_unit` Wikidata facility in the same Land. No facility is invented. `--hospital-plans-only` has no Wikidata rows in memory, so a dry-run of that flag reports `linked_to_wikidata=0`; a full dry-run / runner pass links unique matches.

Licence: both PDFs state no reuse terms, so the cited official plan text is stored as an official work under § 5 UrhG. Only facts, metadata, the official URL and short quotes are kept (`redistribute_fulltext=0`). 0 NULL licences, 0 TODO.

Gaps: Bayern (Krankenhausplan 2025, 275 pages) has a per-hospital layout that wraps across lines and was not parsed safely this pass; Berlin (Krankenhausplan 2020) and Baden-Württemberg (Krankenhausplan 2026) are official but were not reduced to quote-safe Land or hospital figures here. The other Länder are not in this slice. NI per-hospital Planbetten remain a gap until a column-faithful extract is possible.
## (m) Official shelter cost per place/night

In-memory `--dry-run --shelter-costs-only` on 21 November 2026 (Europe/Berlin). No `data/atlas.db`. Quotes are stored only when they appear in the unmodified `pdftotext -layout` archive. Geography is AGS only: Berlin and Hamburg as Land (`11`, `02`); Munich as the official Kreisschlüssel of the kreisfreie Stadt (`09162`). Women-only / restricted-group Träger (SKF Berlin) stay at city AGS with no street address. Official labels that happen to contain a street (“Ohlauer 365”, “Hallesches Ufer”) remain in the quote and offer label only.

Sources used:

- Abgeordnetenhaus Berlin Drs 19/22334 (Antwort 28.04.2025, licence dl-de/by-2-0). Kältehilfe last season: average rund 31 €, median rund 29 € per place/night (is_est=1). 24/7-Unterkunft am Halleschen Ufer: rund 104 €/night in 2025 (total 2.476.379,31 € for 65 persons) and rund 102 € in 2024. Ten ganzjährige Notunterkunft Tagessätze for 2025, each quoted with Träger and Plansumme (Stadtmission 41 € and 50 € as two distinct rows; Straßenfeger 49 €; AWO Spree-Wuhle 65 €; GEBEWO 97 €; Koepjohann 93 €; SKF 61 €; Diakonie Stadtmitte 64 €; EJF 63 €; Johanniter (Ohlauer 365) 50 €). § 67 Hilfen 2023 average Leistungspauschalen: WuW 26,19 €, BEW 33,35 €, BEG 40,09 €, ÜGH 63,16 €, Krisen- und Clearinghäuser “knapp über 200,- €” (stored as 200 with is_est=1). ASOG daily cost: the Senate has no data (official gap, not a zero).
- Landeshauptstadt München, Sozialreferat, Anfrage 20-26/F 01095, Antwort 22.05.2025. 58 Unterkünfte (8 städtische Notquartiere, 13 Flexi-Heime, 7 Clearinghäuser, 26 Beherbergungsbetriebe, 4 sonstige); the city itself operates 13. Budget for commercial Bettplätze 40.500.000 €. Average Bettplatzentgelt currently 674,00 € *per month* (not converted to a nightly rate); caps 750,00 € / 800,00 € per month; Erwerbstätigenhäuser 500,00 € single / 350,00 € p.P. double, also monthly.
- Bürgerschaft Hamburg Drs 23/1321, Tabelle 3 (PDF-S. 6). These are Kostensätze of the öffentlich-rechtliche Folgeunterbringung (örU), *not* Kältehilfe or Wohnungsnotfallhilfe, and Notstandorte mix Erstaufnahme (footnote: four EA sites with 1.547 places and three örU sites with 196). 2025 (gerundet): Hotel 81 €/day (5.873 places, 173.800 Tsd. €), Interims 41 €/day (5.104 places), Notstandorte 43 €/day (2.107 places); total 180.000 Tsd. € and 13.083 places; Mehrbedarf 119.500 Tsd. €. 2024 comparators in the following narrative: Hotel 83 €/day, Interims 48 €/day (the two-column layout splits the sentences; quotes are the fragments that appear contiguously in the unmodified archive). 2024 Notstandorte is described as unchanged but the 2024 figure is not stated as a number, so it is not stored. PG 253.03 kennzahl “Anzahl der durch Wohnungslose genutzten Plätze” 5.050 (Fort. Plan neu 2025).

Licence: Berlin is dl-de/by-2-0 as for other PARDOK documents. Munich and Hamburg PDFs state no reuse terms, so the cited official text is stored as an official work under § 5 UrhG. Only facts, metadata, the official URL and short quotes are kept (`redistribute_fulltext=0`). 0 NULL licences, 0 TODO.

Gaps: Berlin ASOG per-place daily cost (Senate has no overview yet) and 2024 ASOG annual total (Jahresabschluss not yet complete). Hamburg 2024 Notstandorte has no quoted number. No Frauenhaus addresses or costs at address level. Official fee statutes and one Bremen Drucksache for further cities were added on 23 November 2026 (see the city shelter-cost slice below); units are stored exactly as published (per person per night/day/month, per place per month, or per m² per month) and are not converted.
## (j) LAG Wohnungslosenhilfe and Land-level umbrella bodies

In-memory `--dry-run --lags-only` on 21 November 2026 (Europe/Berlin). No `data/atlas.db`. Organisation level only: official name, website, official page URL, Land letter on `org.land` and the 2-digit Land AGS on `institutions_media_org.land_ags`. `kreis_ags` is NULL. No people are stored. A row is written only when the official name appears in a fetched official HTTP 200 page.

Stored:

- Koordination Wohnungslosenhilfe Nordbayern and Südbayern (Land AGS `09`), official site wohnungslosenhilfe-bayern.de (also listed as Behörden on BayernPortal). Impressum reserves further use of the texts.
- Arbeitskreis Wohnungsnot, Berlin (Land AGS `11`), the published network of more than 70 Berlin Träger and public bodies. The impressum legal entity is the Förderverein der Wohnungslosenhilfe in Berlin e. V.; the organisation is stored under its public name. Site © Arbeitskreis Wohnungsnot.
- Evangelischer Fachverband Wohnungslosenhilfe (Diakonie RWL, Land AGS `05`). Impressum: no rights in the website content are transferred.
- Fachverband Evangelische Wohnungsnotfallhilfe und Straffälligenhilfe (Diakonie Bayern, Land AGS `09`). The Diakonie Bayern impressum states no separate text-reuse terms, so the cited official name and URL are stored as an official work under § 5 UrhG.
- Evangelischer Fachverband Wohnungslosenhilfe und Existenzsicherung e.V. (Diakonie in Niedersachsen, Land AGS `03`). The page uses the genitive form of the name; that wording is in the unmodified archive. Impressum reserves reuse of the texts.

0 NULL licences, 0 TODO, `redistribute_fulltext=0`.

Gaps: there is no single official national directory of Landesarbeitsgemeinschaften (the BAG W membership page lists only the federal korporative members already stored). No dedicated official LAG website was verified this pass for Baden-Württemberg, Bremen, Hamburg, Hessen, Mecklenburg-Vorpommern, Rheinland-Pfalz, Saarland, Sachsen, Sachsen-Anhalt, Schleswig-Holstein or Thüringen. Party working groups (for example a party LAG in Berlin) and unofficial personal sites were not stored. Liga der Freien Wohlfahrtspflege pages in Sachsen and Baden-Württemberg are general welfare umbrellas, not Wohnungslosenhilfe LAGs, and were not stored under that label.

## Bounce fixes after run #15

Hamburg young-adult offers: `Junge Wohnhilfe` and `Werkhaus Münzviertel (für Jungerwachsene 18-27 Jahre)` are restricted-group offers. The matcher now treats *Junge Wohnhilfe* and the closed compound *Jungerwachsene* as youth-only, so both are stored at city/district level with no street, PLZ or coordinates.

Licences: the Munich Sozialreferat letter (RIS F 01095) uses reserved-rights terms and `redistribute_fulltext=0`, citing [stadt.muenchen.de/infos/impressum.html](https://stadt.muenchen.de/infos/impressum.html) (the RIS imprint points there; republication of site texts needs consent). Hamburg Drs 23/1321 uses the official ParlDok wording, amtliches Werk § 5 UrhG, scoped to the cited text, licence URL [parldok/lizenz.html](https://www.buergerschaft-hh.de/parldok/lizenz.html). The Hamburg and Niedersachsen Krankenhausplan PDFs themselves state no reuse terms; they are no longer labelled § 5 on that basis. Both now use reserved-rights terms citing the official imprint (hamburg.de/impressum, ms.niedersachsen.de/impressum).

Landtag feed failures (RSS fetch/parse errors, and exceptions from PARDOK/ELVIS/RSS) are counted in the run summary as `landtag_feed_errors=N` and returned on `run()["errors"]`, not only as narrative notes.



## Bremen and Frankfurt manual archive

Wired on 23 November 2026 (Europe/Berlin) from the Lead's hand archive at `~/projects/_manual_archive/institutions_media/` (SHA256SUMS + SIZES, provenance «manual archive via browser/box, 2026-11-21»). The module reads those local files only. It never fetches `sd.bremische-buergerschaft.de` PDFs or the `stvv.frankfurt.de/download` path. Bytes are seeded into `data/raw/institutions_media/` so the official URL has a sha256 for verify G4. Frankfurt HTML is a rendered-page capture; quotes are taken from the visible text only.

Official overnight offers stored (restricted-group rules as usual):

- Bremen, service.bremen.de: four catalogued Notunterkünfte. The women-only offer is stored at city/district level, with no street, PLZ or coordinates. Mixed/general and men-only offers keep the published address. Kreis AGS `04011`.
- Frankfurt am Main, official Notschlafstellen list: eight offers. Hannah-Wohnen für Frauen is women-only (district level). Drogennotdienst is operated by Jugendberatung und Jugendhilfe e.V.; the Jugend operator name is coarsened (no street). Kreis AGS `06412`.

Cost and capacity metrics, quoted from the unmodified archive (`pdftotext -layout` for PDFs):

- Frankfurt Dezernat VIII, 4.11.2026: «Frankfurt hält für Obdachlose 630 Schlafplätze vor» (630 places, Kreis `06412`).
- Bremen Senatsantwort 19.08.2025: net costs € 4.043.506 (2023) and € 4.465.032 (2024) for Notunterkünfte, betreute Einrichtungen, hotels and pensions in Bremen (Land AGS `04`); Bremerhaven men's Notunterkunft «rund 280.000 €» in 2023 (Kreis `04012`, `is_est=1` because of «rund»). The document's Frauenhaus remark is not stored as a facility or an address.
- Bremen Senatsantwort 2013: daily Entgelte Jakobushaus 51,73 €, Frauennotunterkunft 87,92 €, La Campagne 48,86 €, Sleep Inn 52,39 € (Land-level, `eur_per_place_day`, no street address).
- Frankfurt Unterbringungsgebührensatzung: monthly fee for a one-person household 635,00 € (zwischengenutzter Wohnraum) and 810,00 € (sonstige Unterkunft).

VL 20/1210, VL 20/7270, M 71/2026 and the 2024 Senate template (`hb_senat_2030.pdf`, also used by Counts & Law) are registered as sources only in this pass. HTML city pages that do not name a licence in the footer use reserved-rights terms and `redistribute_fulltext=0`. Senate answers, Bürgerschaft deputations, the municipal Satzung and the Magistratsvorlage are stored as official works under § 5 UrhG, scoped to the cited text. 0 NULL licences.

The 13 URLs listed under «manual archive needed» on 21 November 2026 are therefore resolved for ingest, still never auto-fetched from the blocked hosts.


## Press and public-broadcaster media

First media slice, 23 November 2026 (Europe/Berlin). This closes part of the gap against the US atlas (127 media rows at run #15 versus 1,999+). The module discovers official articles about Wohnungslosigkeit, Obdachlosigkeit, Kältehilfe, Notunterkünfte, Wohnungsnotfallhilfe and Housing First from:

- Bundestag hib and press RSS;
- Destatis RSS, press search and the Wohnungslosigkeit topic page;
- Land statistics office press pages (Statistik BW RSS plus official search pages at LfStat Bayern, Amt für Statistik Berlin-Brandenburg, IT.NRW, Statistikamt Nord and Statistik Sachsen);
- city press offices (Berlin RSS/search, Hamburg, München, Köln RSS, Leipzig, Dresden, Stuttgart, Düsseldorf);
- Landtag press search pages (NRW, Abgeordnetenhaus Berlin, Bayerischer Landtag);
- public broadcasters: tagesschau (topic page, official search API, RSS), Deutschlandfunk, BR, NDR, WDR, rbb, MDR, SWR and HR.

Each stored row is metadata plus at most two sentences quoted under § 51 UrhG from the unmodified archived page. Licence: reserved-rights terms, `redistribute_fulltext=0`. AGS (Land or Kreis) is stored only when the article is clearly local; national stories stay `land=DE` with no AGS. Private individuals are not named unless they act in a public role. Paywalled pages are skipped, not bypassed. Hosts that disallow the path in robots.txt, or that reserve TDM in robots.txt, `/.well-known/tdmrep.json`, an HTTP header or a page meta tag, are skipped and listed in the run notes. Requests are polite (at least 3 seconds between requests to the same host; 61 seconds for www.tagesschau.de, per the official API terms).

`--dry-run --press-only` is in-memory and does not write `data/atlas.db`. Feed endpoints are listed in `docs/SOURCES.md`; each stored article also gets its own source row at ingest.


## More press and statistics-office media

Second media slice, 23 November 2026 (Europe/Berlin). Added official discovery sources that were missing from the first slice, after an HTTP 200 check with the project User-Agent:

- Statistisches Landesamt Bremen RSS (`statistik-bremen-14970`);
- Statistisches Amt Saarland Pressemitteilungen RSS;
- Statistisches Landesamt Rheinland-Pfalz `all_feeds.rss` (linked from the office's RSS-Feed page);
- Hessisches Statistisches Landesamt press index;
- Statistisches Amt Mecklenburg-Vorpommern (LAiV) press index;
- Pressestelle des Senats der Freien Hansestadt Bremen, current press list.

The first-slice BR RSS URL `meldung-100~rss.xml` and the rbb URL `/aktuell/index.xml` returned HTTP 404 during the in-memory `--press-only` dry-run. They were replaced with the current official URLs: the BR Nachrichten-Ticker listed on [br.de/service/br-rss-feeds-100.html](https://www.br.de/service/br-rss-feeds-100.html), and the rbb24 homepage RSS link `index.xml/feed=rss.xml`. The BR imprint URL was updated to the official [impressum/index.html](https://www.br.de/unternehmen/service/impressum/index.html) (the previous `impressum-102.html` path now returns 404).

Not added in this pass: Frankfurt city press pages still return HTTP 403 (Cloudflare) from this environment, as with the manual-archive HTML; there is no public municipal RSS, only a newsletter. Sachsen-Anhalt Statistik RSS failed TLS from this environment. Further Landtag press feeds were not added without a verified official machine-readable URL.

Same rules as the first slice: reserved-rights terms, `redistribute_fulltext=0`, short § 51 quotes from the unmodified archived page, robots.txt and TDM reservations honoured, AGS only when clearly local, no private individuals unless they act in a public role.

## Press media from official archives and sitemaps

The first `--press-only` dry-run stored 19 rows because most RSS and HTML search windows had few or no on-topic items. This slice adds official XML and news sitemaps (and a larger tagesschau API page budget) so discovery can use archives rather than only the live window.

Sitemaps were added only after a robots.txt check (including `Allow` wildcards that Python's `urllib.robotparser` misses) and a TDM check (`TDM-Reservation: 1` in robots, tdmrep.json, HTTP headers or HTML meta). There is no machine-readable `TDM-Reservation: 1` on these hosts. ARD and the ARD Länder broadcasters state a prose § 44b reservation in robots.txt, with an exception for automated access used only for retrieval-augmented generation or grounding, provided robots.txt is honoured and the source is attributed. Rows stay metadata plus at most two sentences under § 51 UrhG, with the reserved-rights licence and `redistribute_fulltext=0`.

Polite clocks: at least 3 seconds between requests per host, Destatis `Crawl-delay: 30`, Deutschlandfunk `Crawl-delay: 5`, tagesschau 61 seconds (official 60 requests/hour cap). Cached `data/raw` files are not delayed again. The per-host tdmrep.json check runs once.

Topic filter on the sitemap loc or news title (and, when present, news keywords): Obdachlos, Wohnungslos, Kältehilfe / Kaeltehilfe, Notunterkunft, Kältebus, Housing First, plus Wohnungsnot only together with Obdach. English Destatis `/EN/` copies are dropped. Quotes are taken verbatim from the unmodified archived page; titles or quotes that name a private individual are skipped.

Verified HTTP 200 from this environment (23 November 2026) and wired as feeds:

- tagesschau sitemap index (`index~sitemap.xml`, 61 child urlsets). One child urlset (`p-0`) had 6 on-topic locs among 3,000; `sitemap.xml` itself is 404. The search API now paginates more terms (including Notunterkunft, Housing First, Wohnungsnotfallhilfe, Kältebus) with a cap of 18 search requests and 80 stored items, still under the hourly cap.
- BR `article-archive.xml` (29,392 locs, 32 on-topic in the 23 November 2026 snapshot).
- NDR, WDR and MDR sitemap indexes (90 / 60 / 38 children). MDR follows only the `nachrichten` children, not radio/service/unternehmen sitemaps.
- hessenschau `sitemap.nc.xml` (9,999 locs in the published file, 28 on-topic).
- Deutschlandfunk topical sitemaps listed in robots.txt (`gesellschaftsthemen-100`, `politikthemen-100`, `nachrichten-100`). These are rolling windows (about 38–200 locs), not a full historical archive; `dlf-search` remains for query-based discovery. Crawl-delay 5 seconds.
- Bundestag German sitemap index (two gzip urlsets of 50,000 locs in sitemap1; topic slugs are rare — 1 on-topic loc in that file). The existing hib and press RSS feeds are unchanged. The `/presse/pressemitteilungen/2025` and `/webarchiv/presse/hib` HTML pages returned 200 but did not expose article links in the static HTML (they appear to be client-rendered), so they were not added as `html_index` feeds.
- Destatis `Sitemap_PressReleases.xml` (500 locs, no topic slugs or news titles, so this feed will usually contribute 0 candidates). Destatis RSS under `/SiteGlobals/Functions/RSSFeed/DE/` is allowed and is now honoured (urllib had treated it as disallowed). The press-search form `Pressesuche_Formular_2.html` does not match the robots `Allow` pattern `*_Formular.*` (it would match a `*_Formular.html` path) and stays skipped. A `/DE/Presse/Pressemitteilungen/2025/_inhalt.html` year index returned HTTP 404.

Not added:

- SWR site sitemap index lists only the last three homepage daily sitemaps, not a historical archive. Existing SWR RSS/news feeds stay in use.
- rbb24 robots.txt lists no Sitemap URL; existing rbb RSS stays in use.
- City press archives that do not load from this environment (Frankfurt city press still HTTP 403 / Cloudflare) were not added.
- Sachsen-Anhalt Statistik RSS still failed TLS from this environment in the previous slice.

`wdr-search` remains robots-skipped; the WDR sitemap index replaces that discovery path. `duesseldorf.de` article paths that robots.txt already blocked are unchanged.


## Rebase onto schema v6 (c46e3f6) and Lead press fixes

23 November 2026, Europe/Berlin. lead/core and the rebase target are `c46e3f6` (schema v6, INGEST_CONTRACT §12). The worker branch `worker/institutions_media` was rebased onto that commit (not onto `04f0830`). Head `914cd40`. No push. `data/atlas.db` was not written.

Fixes carried on this rebase:

1. Press robots.txt is fail-closed via counts_law `_robots_for` / `_robots_allows`. Only HTTP 404 or 410 (or HTML instead of robots) means there are no rules. Network errors, 5xx, 401/403 and cross-site redirects skip the host.
2. Press and media rows store only headline, date, outlet, URL and a short topic tag. No quote and no full text. One `source` row per outlet at the imprint URL, licence `Rechte vorbehalten (Impressum zitiert); nur Fakten und Metadaten, Volltext nicht weiterverbreitet`, `redistribute_fulltext=0`. Private individuals are not named.
3. Bremen net costs 4,043,506 € (2023) and 4,465,032 € (2024) are on Kreis AGS `04011`, unit `€ per year` (the Senat document says „in Bremen“).
4. Landtag Drucksachen, the Hamburg and Niedersachsen Krankenhauspläne, and the München Sozialreferat letter use the rights-reserved licence with rf=0. § 5 remains only for statutes and gazettes. DIP terms and Rechnungshof rows are unchanged. The Lead had already reserved the six Bremen/Frankfurt archive sources.
5. Each Jobcenter has one `org_link` with `method=register_id` and `id_value='BA_JC:<nr>'`. No origin duplicate of that value.
6. Coarsened (restricted/protected) facility rows still clear `anschrift`/`plz`/`lat`/`lon` after upsert, consistent with `b86e969`.

Schema 6 bounce, committed as `914cd40`: orgs are created through `common.ensure_org`. The module uses the id that helper returns and does not look an org up again by `(name_norm, land)`. `legal_form_norm` is set from the source name or legal form. A record that creates the org is linked as `method=origin`, confidence 1.0, unflagged. Reviewed name_fuzzy rows in `docs/link_reviews.tsv` are left for the Lead.

### In-memory press dry-run (23 November 2026, finished 17:59 Europe/Berlin)

`--dry-run --press-only` against the fail-closed / metadata-only press module, in memory. stored=451, candidates=577, fetch_failed=15, topic_skipped=926, missing-title=1, name_skipped=7, dup=13, paywall=0, host_skipped=7. 12 outlet sources, facts-only licence, rf=0. No zusammenfassung longer than a topic tag.

Per outlet (herausgeber):

- Norddeutscher Rundfunk: 188
- Westdeutscher Rundfunk: 151
- Bayerischer Rundfunk: 28
- tagesschau / ARD-aktuell: 28
- Mitteldeutscher Rundfunk: 22
- Hessischer Rundfunk (hessenschau): 15
- Deutscher Bundestag: 5
- Landeshauptstadt Dresden: 4
- Landeshauptstadt München: 4
- Statistisches Landesamt des Freistaates Sachsen: 4
- Deutschlandfunk: 1
- Statistisches Bundesamt (Destatis): 1

Hosts skipped entirely (fail-closed robots):

- www.saarland.de — robots.txt HTTP 403 (`statistik-sl-rss`)
- www.senatspressestelle.bremen.de — robots.txt HTTP 403 (`bremen-senat-presse`)
- www.statistik.bremen.de — robots.txt HTTP 403 (`statistik-hb-rss`)
- www.hamburg.de — robots.txt unreadable, connection reset (`hamburg-presse`)

Path-level robots disallow (host not blocked as a whole): destatis-search (`Pressesuche_Formular_2.html` does not match Allow `*_Formular.*`); wdr-search (the WDR sitemap is used instead); some `www.duesseldorf.de` article paths.

### Hand-archive list for the Lead

Frankfurt and 404/410 press URLs still needing a manual archive (or a current official replacement URL). Already-archived Bremen/Frankfurt shelter and cost files from 21 November 2026 are not repeated.

Frankfurt city press:

- City press index / municipal press pages still return HTTP 403 (Cloudflare) from this environment. There is no public municipal RSS, only a newsletter. The 13 official shelter and cost files (including M 71/2026) are already in `~/projects/_manual_archive/institutions_media/`.

HTTP 404 or 410 discovered on this dry-run (official feed URLs that no longer serve the listed resource):

- https://www.destatis.de/DE/Presse/Pressemitteilungen/2025/_inhalt.html — Destatis 2025 year index, HTTP 404 (noted earlier)
- https://www.stadt-koeln.de/politik-und-verwaltung/presse/mitteilungen/rss.xml — Köln press RSS, HTTP 410
- https://www.ndr.de/suche20.html?query=Wohnungslosigkeit&sort_by=date — NDR search, HTTP 404
- https://www.mdr.de/nachrichten/suche-100.html?query=Wohnungslosigkeit — MDR search, HTTP 404
- https://www.swr.de/swraktuell/suche-102.html?q=Wohnungslosigkeit — SWR search, HTTP 404
- https://www.statistik-bw.de/Service/RSS/rss.xml — Statistik BW RSS, HTTP 404
- https://www.statistik.bayern.de/suche/index.html?query=Wohnungslosigkeit — LfStat Bayern search, HTTP 404
- https://www.statistik-berlin-brandenburg.de/suche?search=Wohnungslosigkeit — Amt für Statistik Berlin-Brandenburg search, HTTP 404
- https://www.statistik-nord.de/suche?tx_kesearch_pi1[sword]=Wohnungslosigkeit — Statistikamt Nord search, HTTP 404
- https://www.berlin.de/presse/pressemitteilungen/index/index.rss — Berlin Senat press RSS, HTTP 404
- https://www.berlin.de/presse/pressemitteilungen/index/index.php?q=Wohnungslosigkeit — Berlin Senat press search, HTTP 404
- https://www.leipzig.de/newsportal?tx_news_pi1[search][keyword]=Wohnungslosigkeit — Leipzig press search, HTTP 404
- https://www.stuttgart.de/rathaus/aktuelles/pressemitteilungen.php?search=Wohnungslosigkeit — Stuttgart press search, HTTP 404
- https://www.landtag.nrw.de/portal/WWW/suche/suche.jsp?query=Wohnungslosigkeit — Landtag NRW press search, HTTP 404
- https://www.bayern.landtag.de/aktuelles/suche/?q=Wohnungslosigkeit — Bayerischer Landtag press search, HTTP 404

Already replaced earlier (do not re-add the retired URLs): BR `meldung-100~rss.xml` and rbb `/aktuell/index.xml` were HTTP 404 and were swapped for the current official feeds.

Still candidates if a rendered capture is possible: Bundestag `https://www.bundestag.de/presse/pressemitteilungen/2025` and `https://www.bundestag.de/webarchiv/presse/hib` return HTTP 200 but are client-rendered and expose no article links in static HTML.

Not added as auto-fetch: SWR sitemap index lists only the last three homepage daily sitemaps; rbb24 robots.txt lists no Sitemap URL. Sachsen-Anhalt Statistik RSS still failed TLS from this environment in an earlier slice.

## City shelter-cost slice (23 November 2026, Europe/Berlin)

Official Unterbringungsgebührensatzungen, one Ratsvorlage and Bremen Drs 19/894 were fetched under the fail-closed robots check (only HTTP 404/410 on robots.txt means there are no rules). All listed cost documents returned HTTP 200 from deck on 23 November 2026 and are cached under `data/raw/institutions_media/`. Quotes are taken from the unmodified `pdftotext -layout` archive (HTML via `document_text` for Düsseldorf Stadtrecht 54.101) and each stored quote contains the cited number. Geography is the Kreis AGS of the kreisfreie Stadt. Satzungen use § 5 Abs. 1 UrhG; the Köln RIS Vorlage 2690/2023/1 and Bremen Drs 19/894 are rights reserved, `redistribute_fulltext=0`. No organisation rows were created in this slice. `data/atlas.db` was not written.

Metrics wired in `institutions_media_shelter_costs.py` (37 new figures):

- Köln, Kreis `05315`: 2024 Satzung — 50,00 € per person per month (Amsterdamer Str. 149); 12,50 / 11,53 / 4,10 € per m² per month (named special rates); 12,90 + 0,92 € per m² per month plus 33,58 € per Unterkunft per month (Wohnen auf Zeit); annex Gesamtgebühr min 5,20 / max 14,20 € per m² per month. 2018 Satzung — 50,00 € per person (Amsterdamer Str., monthly Gebührenhöhe section); 10,03 and 5,21 € per m² per month (Brand- und Katastrophenschutz); annex min 4,55 / max 12,59 € per m² per month. Vorlage 2690/2023/1 is registered as a source/document; the promulgated rates come from the Satzung.
- Bremen city, Kreis `04011`: Drs 19/894 (10 January 2017) — Notunterkünfte 51,01–136,65 € per person per night; hotels/pensions 16 € to ca. 40 €, in a single case 45 € per person per night. These are not a duplicate of the already-wired 2013 daily Entgelte or the 2023/2024 net costs (4,043,506 / 4,465,032 € per year). `pdftotext -layout` of this official PDF renders the euro sign as ‡; quotes keep that glyph and the numbers. The PDF was taken from `static.bremische-buergerschaft.de`, not from `sd.bremische-buergerschaft.de`.
- Leipzig, Kreis `14713`: Satzung 5-08 (in force 01.07.2025) — 5,00 Euro per person per night in the Gemeinschaftsunterkunft for Wohnungslose.
- Dresden, Kreis `14612`: Unterbringungssatzung 5.8 (10.04.2025), Anlage 2, Personenkreis § 1 Abs. 2 Buchstabe a) — 1.104,03 € per person per month (Übergangswohnheim, § 3); 431,90 € per person per month (Gewährleistungswohnungen / sonstige after §§ 4, 6 Abs. 2); 20,00 € per person per day (höhere Gewalt, § 5).
- Stuttgart, Kreis `08111`: Stadtrecht 4/12 (17.10.2019) — 15,23 / 10,52 EUR per m² per month, and reduced Selbstzahler rates 11,40 / 7,40 EUR per m² per month.
- Düsseldorf, Kreis `05111`: Stadtrecht 54.101, § 3 (fees in force 01.01.2018) — Obdachlosenunterkünfte (Ziff. 3) Grundgebühr 6,25 / 6,80 EUR per m² per month, Nebenkosten 1,92, Heizkosten 1,10.
- Also official Satzungen for Karlsruhe (Kreis `08212`, 500 € per place per month / 400 € per person per month) and Mannheim (Kreis `08222`, 16,00 € per m² per person per month and 21,00 € per person per day in the Notübernachtungsstelle).

### Hand-archive list from this slice

No official shelter-cost document in this slice returned HTTP 403 or a fail-closed robots skip. All ten source URLs above loaded as PDF or HTML with HTTP 200.

Impressum notes (licence_url only; not cost documents): `https://www.stadt-koeln.de/impressum` and `.../impressum/index.html` returned HTTP 403 from deck on 23 November 2026; the working official imprint is `https://www.stadt-koeln.de/service/kontakt/impressum` (HTTP 200). `https://www.bremische-buergerschaft.de/impressum` returned HTTP 404 (the site currently fronts `/baustelle`); the working official imprint is `https://static.bremische-buergerschaft.de/index02b6.html?id=93` (HTTP 200, title «Bremische Bürgerschaft: Impressum»). `https://www.dresden.de/de/impressum.php` was 404; `https://www.dresden.de/impressum` is 200. `https://www.duesseldorf.de/impressum` was 404; `https://www.duesseldorf.de/infonav/impressum` is 200. None of these imprint misses blocked a cost document, so none is requested as a manual archive for this slice.

Earlier fail-closed press skips (saarland.de, senatspressestelle.bremen.de, statistik.bremen.de robots 403; hamburg.de robots connection reset) are unchanged and are not part of this cost slice.

## Krankenhausplan slice for other Länder (23 November 2026, Europe/Berlin)

Head of the previous city-cost slice (`943b0de`) was already with the Lead. This pass extends `institutions_media_hospital_plans.py` only, under fail-closed robots.txt (HTTP 404/410 means no rules; network errors, 5xx, 401/403 and cross-site redirects skip the host). Quotes are taken from the unmodified `pdftotext -layout` archive and each stored quote contains the cited number. Geography is the 2-digit Land AGS. Hospital organisations would go through `ensure_org` with `legal_form_norm` and an unflagged origin link; this pass stores quote-safe Land totals only, so no new hospital orgs and no Kreis hospital rows. Hamburg and Niedersachsen parsers were not changed. `data/atlas.db` was not written. No push.

Wired Land totals (11 new metrics, 0 orgs):

- Baden-Württemberg, Land AGS `08`, Krankenhausplan 2026, PDF-S. 50: Psychosomatik Bedarf 2025 — 1.566 Betten and 517 Plätze. KJP and adult psychiatry chapters state only the Burton-Hill formula (90 % / 70 % utilisation) and give no landesweit bed totals. The 2030 outlook states a lower Bedarf without a new bed/place number, so it is not stored. Licence: rights reserved, `redistribute_fulltext=0` (administrative plan, not a statute or Amtsblatt).
- Berlin, Land AGS `11`, Krankenhausplan 2020 (Senate decision 14.09.2021), PDF-S. 73: prognostizierter gesamtstädtischer Bedarf 2025 — Psychiatrie 3.436, Psychosomatik 547, KJP 601 Betten/Plätze. These are combined beds and day-clinic places, stored with unit `beds_or_places` and not converted. Tab 9.1 (aufgestellte Betten from hospital statistics) and Tab 9.4.2 (2017 needed beds at norm utilisation) are not Plan-Soll and were not stored. Tab 9.2 Ist / Soll-Alt KH-Plan 2016 is quote-safe but is a different series, so it is also not stored in this pass. Licence: rights reserved, `rf=0`.
- Brandenburg, Land AGS `12`, Vierter Krankenhausplan, Amtsblatt für Brandenburg Nr. 28 (Ausgabe S) vom 23. Juli 2021, table annex PDF-S. 19–20: 4. KH-Plan Festlegungen — KJP 255 Planbetten / 202 Tagesklinikplätze, Psychiatrie 1.821 / 850, Psychosomatik 253 / 142. The earlier annex table of aufgestellte Betten 2013–2017 (Amt für Statistik) is not stored. Versorgungsgebiet breakdowns are not Kreis AGS and were not stored. Later hospital-level annex pages were not reduced to quote-safe rows in this pass. Licence: § 5 Abs. 1 UrhG (Amtsblatt).

### Länder skipped, with the reason

- Hamburg and Niedersachsen: already stored in an earlier pass; not redone.
- Bayern, Krankenhausplan 2025 (275 pages, official stmgp.bayern.de PDF, robots allowed): per-hospital table rows wrap (name/codes vs numbers often not on one quotable line); no clean Land Summe for psych/KJP/psm.
- Hessen, Krankenhausplan 2025 (266 pages, familie.hessen.de, robots allowed): the psych/psm chapter says the 2020 psychiatric and psychosomatic plan is continued with no changes; this document contains no Planbetten or place figures to quote.
- Sachsen, Krankenhausplan 2026 Teil I Anlage 1 (gesunde.sachsen.de, robots allowed): occupancy-day targets only, no bed or place counts. The Teil II URL and a guessed landes page returned HTTP 404. Teil III (expected bed lists) is not yet published.
- Thüringen, 8. Thüringer Krankenhausplan of 09.07.2024 (soziales.thueringen.de, general part, robots allowed): framework text, no current bed/place table. The figure of 217 Planbetten is a historical 7th-plan Psychosomatik calculation (one bed per 10.000 inhabitants), not a Festlegung of the 8th plan, so it is not stored.
- Nordrhein-Westfalen, Krankenhausplan 2022 (mags.nrw, robots allowed): plans in Leistungsgruppen / Belegungstagen, not Planbetten; the plan itself says it does not fix individual hospitals. The official annex xlsx is Leistungsgruppen definitions, not bed counts. No quote-safe psych bed or day-place Land total was stored; Belegungstage were not converted into beds.
- Rheinland-Pfalz, Landeskrankenhausplan 2019–2025: official ministry PDF and the Staatsanzeiger Nr. 22 annex of 24.06.2019 were fetched under fail-closed robots (both HTTP 200). The gazette is two-column; psychiatric planning is regional narrative (individual “um n Betten/Plätze” notes) without a quote-safe Land total or per-hospital psych table in this extract. Not stored.
- Sachsen-Anhalt: the 2022 plan is in force and `ms.sachsen-anhalt.de` robots.txt is readable, but the previously cited Rahmenvorgaben PDF path returned HTTP 404 on 23 November 2026. No substitute official bed-table PDF was confirmed this pass.
- Mecklenburg-Vorpommern: no official current ministry plan PDF URL was confirmed this pass. `regierung-mv.de` robots.txt redirected off the site to `https://land-mv.de/` and was skipped fail-closed.

### Hand-archive list from this slice

These official plan PDFs must not be auto-fetched; robots.txt was unreadable (fail-closed):

- Bremen, Krankenhausrahmenplan 2022–2024: `https://www.gesundheit.bremen.de/sixcms/media.php/13/01_Krankenhausrahmenplan_2022_2024.pdf` — robots.txt HTTP 403 on `gesundheit.bremen.de`.
- Schleswig-Holstein, Krankenhausplan 2017 Teil A: `https://www.schleswig-holstein.de/DE/fachinhalte/K/krankenhaeuser/Downloads/Krankenhausplan_2017_Teil_A.pdf?__blob=publicationFile&v=1` — robots.txt connection reset on `schleswig-holstein.de`.
- Schleswig-Holstein, Krankenhausplan 2017 Anlagen: `https://www.schleswig-holstein.de/DE/fachinhalte/K/krankenhaeuser/Downloads/Krankenhausplan_2017_Anlagen.pdf?__blob=publicationFile&v=1` — same robots failure. (Table 8 Land totals for 2017 are described in secondary extracts but are not stored until an allowed official archive exists.)
- Schleswig-Holstein, Krankenhausplan 2017 Besonderer Teil: `https://www.schleswig-holstein.de/DE/fachinhalte/K/krankenhaeuser/Downloads/Krankenhausplan_2017_BesondererTeil.pdf?__blob=publicationFile&v=1` — same robots failure.
- Saarland, Krankenhausplan 2018–2025 (ministry download page): `https://www.saarland.de/SharedDocs/Downloads/DE/msgff/tp_gesundheitprävention/downloads_servicegesundheit/downloads_salkrankenhauswesen/download_krankenhausplan_18-25` — robots.txt HTTP 403 on `www.saarland.de`.
- Saarland, reported Krankenhausplan 2027–2035 download: `https://www.saarland.de/SharedDocs/Downloads/DE/masfg/gesundheit/dld_krankenhausplan_2027_2035` — same robots 403; not fetched, URL not verified as a PDF in this pass.

## Regional and local media outside Berlin (23 November 2026, Europe/Berlin)

Built on head `9c558f3`. Discovery is sitemap-only, under the fail-closed robots.txt check. Stored rows are headline, date, outlet, URL and a topic tag only (no quote, no full text). One source row per outlet, rights reserved, facts only, `redistribute_fulltext=0`. No private individuals' names in the stored headline. Kreis AGS only when the article is clearly local. In-memory dry-run of `REGIONAL_LOCAL_FEEDS` only: stored=112, candidates=117, fetch_failed=1, topic_skipped=1, name_skipped=3, dup=0, paywall=0, host_skipped=0. `data/atlas.db` was not written. No push.

The existing Land-wide NDR / WDR / BR / MDR / hessenschau sitemaps are unchanged. These new feeds are narrower regional desks and city press sitemaps. When the Lead later ingests the full press module, URLs already stored under the Land-wide outlet will be deduped; new unique rows from this slice are mainly Stadt Dortmund plus any regional loc that the generic child selection had missed.

### Rows per outlet (in-memory dry-run, 23 November 2026)

- Norddeutscher Rundfunk (Hamburg): 45 stored (45 candidates). Kreis `02000`. Sample 25/25 on topic (100%).
- Westdeutscher Rundfunk (Ruhr): 25 stored (26 candidates). Kreise include Dortmund `05913`, Essen `05113`, Bochum `05911`, Duisburg `05112`. Sample 25/25 on topic (100%).
- hessenschau (Frankfurt): 14 stored (15 candidates). Kreis `06412`. Sample 14/14 on topic (100%). One stored headline is truncated to «6,1 Millionen Euro»; the URL and topic tag are the Hessen programme against Wohnungslosigkeit in Frankfurt.
- Westdeutscher Rundfunk (Köln): 10 stored (10 candidates). Sample 10/10 on topic (100%). A later alias fix (`koeln`/`Köln` as one city) maps clearly local Köln rows to Kreis `05315` (a few dry-run rows were still `land=DE` before that fix).
- Mitteldeutscher Rundfunk (Sachsen): 10 stored (11 candidates; not Sachsen-Anhalt). Leipzig `14713` (5), Dresden `14612` (2), other Sachsen stories Land-only. Sample 10/10 on topic (100%).
- Stadt Dortmund newsroom: 7 stored (8 candidates). Kreis `05913`. Sample 7/7 on topic (100%). Official frost / Notschlafstelle / Aktionsplan gegen Obdachlosigkeit notices.
- Bayerischer Rundfunk (München): 1 stored (2 candidates). Sample 1/1 on topic (100%): «Hitze in München: Warum Obdachlose besonders leiden».
- SWR Baden-Württemberg (`swr-bw-sitemap`): 0 stored. The official swraktuell sitemap index only lists the last three daily sitemaps; none of the Baden-Württemberg locs in that window matched the topic filter.
- Landeshauptstadt Stuttgart press sitemap: 0 stored. 486 press / aktuelle-Meldungen locs in the city sitemap, none with a topic slug; service/organigramm hits were excluded by `loc_must`.
- Landeshauptstadt Düsseldorf news sitemap: 0 stored. The news sitemap is a short rolling window (8 items on 23 November 2026), none on topic.

A seed-20261123 random sample of 25 rows (or all rows if fewer) was drawn per outlet. On-topic means homelessness or housing loss under the tightened `has_topic()` filter (Wohnungslosigkeit, Obdachlosigkeit, Kältehilfe / Kältebus, Notunterkunft / Notschlafstelle, Wohnungsnotfall, Housing First; «Wohnungsnot» only together with Obdach). Every outlet with stored rows is at 100%. A manual read of the sampled headlines agrees with that, with these notes: some WDR Ruhr headlines are crime reports involving homeless people; one NDR Hamburg headline is a refugee «Notunterkunft» in a Messehalle (the URL still contains Notunterkunft); none of those pull any outlet below 80%. The filter was not loosened.

### Skipped outlets, with the reason

City press / official sites:

- Hamburg city (`www.hamburg.de`): an official sitemap index exists (`service-sitemap-hamburg.de-sitemap_index.xml` and child `sitemap1.xml.gz`), but `robots.txt` intermittently fails with connection reset. Fail-closed and skipped. The Lead will not make a manual archive of this feed: manual archives are for one-off documents, not for sitemaps we would crawl again while robots.txt cannot be read. Not auto-fetched.
- Leipzig (`www.leipzig.de`): robots.txt unreadable (HTTP 503). Fail-closed and skipped. The Lead will not make a manual archive of this city site for the same reason. Not auto-fetched.
- München official press (`stadt.muenchen.de`): robots allowed, but no Sitemap directive and `/sitemap.xml` is HTTP 404. The tourism sitemap on `www.muenchen.de` (2,903 locs) had 0 on-topic URL slugs and is not a press outlet.
- Köln official (`www.stadt-koeln.de`): robots allowed, no Sitemap directive; `/sitemap.xml` is HTTP 410.
- Frankfurt official (`www.frankfurt.de`): robots allowed, no Sitemap directive; `/sitemap.xml` is HTTP 403. Not auto-fetched.
- Dresden official: robots allowed (crawl-delay 5), no Sitemap directive; `/sitemap.xml` is HTTP 404.
- Essen, Duisburg, Gelsenkirchen, Oberhausen: no usable sitemap declared or found. `www.muelheim-ruhr.de` robots.txt redirected off-site to `cms.muelheim-ruhr.de` and was skipped fail-closed.
- Bochum: sitemap exists, but the only on-topic loc is a social-services page, not a press article; not added as an outlet.

Newspapers (include only if robots allow the sitemap and article paths, no TDM reservation, and metadata is readable without a paywall):

- merkur.de, tz.de, fr.de, fnp.de: robots.txt disallows this project's user agent.
- abendblatt.de, waz.de, nrz.de, wp.de, derwesten.de (Funke): Impressum reserves commercial Text- und Data-Mining under § 44b UrhG. Skipped (TDM).
- ksta.de and express.de: news sitemaps allowed and had one on-topic loc each, but article HTML contains paywall / Abo language. Skipped (paywall).
- mopo.de: no TDM reservation found in the Impressum or AGB; a news viewport and historical article sitemaps exist, but article HTML contains paywall / Abo language. Skipped (paywall).
- stuttgarter-zeitung.de and stuttgarter-nachrichten.de: news sitemaps allowed, 0 on-topic locs in the current window; not added.
- sueddeutsche.de, faz.net, lvz.de, saechsische.de, dnn.de: no Sitemap directive in robots.txt. Not added.
- lokalkompass.de: robots.txt redirected off-site. Skipped fail-closed.

### Hand-archive list from this slice

None. Hamburg (`www.hamburg.de` sitemap) and Leipzig (`www.leipzig.de`) stay fail-closed and skipped; they are not listed for hand archive, because manual archives are only for one-off documents, not for feeds that would be crawled again while robots.txt cannot be read.

The Bremen, Schleswig-Holstein and Saarland Krankenhausplan PDFs listed in the previous slice remain with the Lead for one-off manual archive.

## Per-hospital psychiatry rows (23 November 2026, Europe/Berlin)

Built on `9c558f3` / then-HEAD `d92b0ce`. Quote-safe per-hospital Planbetten and Tagesklinikplätze from the Brandenburg 4. KH-Plan Amtsblatt table annex (same PDF already registered as `bb_kh4`, § 5 Abs. 1 UrhG, `redistribute_fulltext=0`). Figures are the 4. KH-Plan Festlegungen, not the 31 July 2021 stock totals. Quotes are unmodified `pdftotext -layout` lines that contain the stored number. Hospital site addresses are taken from the left-hand column; the right-hand Träger headquarters is not used for Kreis AGS (so Treuenbrietzen stays 12069, not Berlin 12205; Lübben and Teupitz stay 12061, not Brandenburg an der Havel).

Organisations are created with `ensure_hospital_org` (schema v6, `legal_form_norm` only when the Träger line states GmbH/gGmbH/mbH/e.V., origin link 1.0 unflagged, one org per hospital). Kreis AGS is stored on the sidecar (`institutions_media_khplan`), not as a Kreis metric — two hospitals in one Kreis would otherwise overwrite each other on `(entity_type, entity_id, metric, year)`. Facility metrics are written only when a unique Wikidata psychiatric facility already matches, as for Hamburg.

**Brandenburg: 17 hospitals, 60 sidecar rows.** Land-total cross-check: KJP beds 255 and Psychosomatik beds 253 match the Land Festlegungen exactly. Adult psychiatry beds sum to 1.751 against the Land total of 1.821; the missing 70 are Havelland Kliniken, whose sheet is not quote-safe (see below). Day-place sums are lower than the Land totals where labels wrap onto the next line (no number on the same quotable line).

Rows by hospital and Kreis:

- Ruppiner Kliniken, Neuruppin, Kreis 12068, GmbH — KJP 39 / Psych 138 / PSM 18 beds; KJP 21 / Psych 60 / PSM 12 day places (6)
- Kreiskrankenhaus Prignitz, Perleberg, 12070, gGmbH — Psych 69; Psych 33 day places (2)
- Oberhavel Kliniken, Hennigsdorf (and Oranienburg, same Kreis), 12065, GmbH — Psych 114 / PSM 25; Psych 65 day places (3). Wrapped KJP/PSM day-place labels skipped.
- Krankenhaus Angermünde, 12073, gGmbH — Psych 75; Psych 59 day places (2)
- Martin Gropius Krankenhaus, Eberswalde, 12060, GmbH — KJP 40 / Psych 136 / PSM 30; Psych 62 day places (4). Wrapped KJP/PSM day-place labels skipped.
- Klinikum Ernst von Bergmann, Potsdam, 12054, gGmbH — KJP 35 / Psych 128 / PSM 34 (3). All day-place labels wrap; none stored.
- Johanniter-Krankenhaus Treuenbrietzen, 12069, GmbH — Psych 46 / PSM 18; Psych 35 / PSM 12 day places (4)
- ASKLEPIOS Fachklinikum Brandenburg, Brandenburg an der Havel, 12051, GmbH — KJP 53 / Psych 205 / PSM 28; KJP 34 / Psych 78 / PSM 12 day places (6)
- Carl-Thiem-Klinikum Cottbus, 12052, gGmbH — Psych 81 / PSM 18; Psych 21 / PSM 18 day places (4)
- Klinikum Niederlausitz, Senftenberg, 12066, GmbH — Psych 68 / PSM 20; Psych 43 day places (3)
- Elbe-Elster-Klinikum, Elsterwerda, 12062, GmbH — Psych 66; Psych 30 day places (2)
- Krankenhaus Spremberg, 12071, mbH — Psych 71; Psych 51 day places (2)
- ASKLEPIOS Fachklinikum Lübben, 12061, GmbH — KJP 66 / Psych 109 / PSM 20; KJP 52 / PSM 12 day places (5)
- ASKLEPIOS Fachklinikum Teupitz, 12061, GmbH — Psych 194; Psych 48 day places (2)
- Klinikum Frankfurt (Oder), 12053, GmbH — KJP 22 / Psych 101 / PSM 21; KJP 23 / Psych 32 / PSM 12 day places (6)
- Städtisches Krankenhaus Eisenhüttenstadt, 12067, GmbH — Psych 68; Psych 40 day places (2)
- Immanuel Klinik Rüdersdorf, 12064, GmbH — Psych 82 / PSM 21; Psych 69 / PSM 12 day places (4)

Multi-site sheets (Oberhavel Kliniken, Martin Gropius, Ernst von Bergmann) have three number columns: 4. KH-Plan gesamt, then “davon vollstationär” by site. The first cell is stored, and the quote is the whole line, which contains that number.

**Skipped in this pass**

- Havelland Kliniken (annex PDF-S. 59): layout is garbled (`70-` cells, mashed labels such as `psychotherapieJugendpsychiatrie`). Not stored. That hospital accounts for the 70-bed gap against the Land psychiatry total.
- Day-place lines whose Fachabteilung label wraps so the number sits on the next line: not quote-safe; skipped rather than reconstructed.
- Berlin Krankenhausplan 2020: Tab. 11.13 often puts the hospital name and the bed number on different lines. Anlage 1 has per-hospital sheets with three columns (Ist-Stand, Umsetzung KH-Plan 2016, Krankenhausplan 2020), but many Vivantes/Alexianer pages mix network totals and site lines. Not parsed in this pass; Land Bedarf 2025 totals already stored.
- Baden-Württemberg Krankenhausplan 2026: no per-hospital psychiatry table (0 candidate pages). Land Psychosomatik Bedarf 2025 already stored.
- Hamburg and Niedersachsen per-hospital rows were not changed.

No new hand-archive URLs. The Bremen, Schleswig-Holstein and Saarland Krankenhausplan PDFs remain with the Lead for one-off manual archive. Hamburg and Leipzig city sitemaps are fail-closed skips, not hand-archive items.

## Further regional public-broadcaster desks (23 November 2026, Europe/Berlin)

Built on `7784de8`, after the Hamburg/Leipzig hand-archive correction at `8506d10`. Same rules as `b1260be` / `91787d3`: sitemap discovery only, fail-closed robots, no TDM reservation found on these public-broadcaster hosts (tdmrep.json 404, no TDM header; NDR/MDR `/.well-known/tdmrep.json` returned HTTP 500, which is not treated as a reservation), metadata only, no private names, one SOURCES row per outlet, facts-only licence, `redistribute_fulltext=0`. Kreis AGS only when the article is clearly local. A geo fix in this commit stops `Sachsen-Anhalt` URL paths from being read as Land Sachsen (hyphen was a word boundary) and stops the German word «Essen» (food) from being tagged as the city of Essen.

In-memory dry-run of the new `REGIONAL_DESK_FEEDS` only, 23 November 2026, Europe/Berlin: stored=144, candidates=147, fetch_failed=0, topic_skipped=2, name_skipped=1, dup=0, paywall=0, host_skipped=0.

### Rows per outlet and sample on-topic rate

- Norddeutscher Rundfunk (Niedersachsen): 87 stored (88 candidates). Sample 25/25 on topic (100%). Hannover Kreis `03241` is used when the article is clearly local.
- Norddeutscher Rundfunk (Schleswig-Holstein): 48 stored (48 candidates). Sample 25/25 on topic (100%). Kiel `01002` when clearly local.
- Mitteldeutscher Rundfunk (Sachsen-Anhalt): 7 stored (7 candidates). Sample 7/7 on topic (100%). The dry-run ran before the geo fix, so four Halle stories were then tagged `land=SN` and Magdeburg as `land=DE`; the unit tests for the fix (same URLs) now map Halle (Saale) to Kreis `15002` and Magdeburg to `15003`. The next ingest should use those AGS values.
- Bayerischer Rundfunk (Regionalstudios): 2 stored (2 candidates). Sample 2/2 on topic (100%). Loc filter is regional studio/city names other than München (already a separate outlet).
- Mitteldeutscher Rundfunk (Thüringen): 2 sitemap candidates, 0 stored after the topic / private-name filter. Feed registered for later windows.
- SWR Rheinland-Pfalz (`swr-rp-sitemap`): 0 candidates in the current swraktuell index (only the last three daily sitemaps, same window limit as SWR BW). Feed registered.
- Saarländischer Rundfunk (`sr-nachrichten-sitemap`): official sitemap allowed (index plus three children); `loc_must` keeps `/sr/home/nachrichten/`. 0 on-topic locs in the current urlsets. Feed registered.

A seed-20261123 random sample of 25 (or all, if fewer) was drawn per outlet with rows. Every such outlet is at 100%. The filter was not loosened.

### Skipped outlets, with the reason

- rbb Brandenburg (`www.rbb24.de` / `www.rbb-online.de`): robots.txt is readable and allows this project's user agent, and no TDM reservation was found, but the robots file has no Sitemap directive. Guessed ARD sitemap paths (`/sitemap.xml`, `/index~sitemap.xml`, `/news-sitemap.xml`, `/sitemapIndex.xml`) all returned HTTP 404. Not added: discovery is sitemap-only, and no sitemap exists to crawl.
- Radio Bremen / butenunbinnen (`www.radiobremen.de`, `www.butenunbinnen.de`): same situation — robots allowed, no TDM reservation, no Sitemap directive, guessed sitemap paths HTTP 404. Not added.

No new hand-archive URLs. Hamburg and Leipzig remain fail-closed skips, not hand-archive items. The Bremen, Schleswig-Holstein and Saarland Krankenhausplan PDFs remain with the Lead for one-off manual archive.

## Federal Wohlfahrtsverband Gremien officers (23 November 2026, Europe/Berlin)

Rows go in the shared `org_person` table (INGEST_CONTRACT §9: no domain side table for people). The module is `ingest/domains/institutions_media_officers.py`. It uses the same conventions as Funding & Träger's `funding_officers.py` (quote, stand, funktion, rollenklasse, source), with a distinct source tag (`domain=institutions_media`, `record_kind=institutions_media_gremien`) and a pre-insert check for an existing row with the same `org_id`, name and `funktion`.

### Split with Funding & Träger

Funding & Träger (module `funding_officers.py` on `worker/funding_traeger`, head `b59c80c` when this was agreed) already writes `org_person` from:

- the Lobbyregister API v2
- hand-curated Impressum seeds
- `impressum_auto` over organisations with a website
- Initiative Transparente Zivilgesellschaft point-4 pages

This module does **not** write Impressum roles. Its scope is Vorstand / Gremien pages beyond the Impressum, plus annual-report, Jahresbericht and transparency-report PDFs (PDFs are not parsed in this first pass; see deferred items below).

Where the same person already appears from an Impressum (for example Susanne Hahmann as Vertretungsberechtigter Vorstand of the BAG W, or Claudia Mandrysch / Marvin Deversi on the AWO Impressum), a Gremien row is still stored only when the published `funktion` differs, or is skipped when `org_id` + name + funktion already exist.

### First-pass rows (36), verified against unmodified page text (`html_to_text`)

| Organisation | Land | Rows | Source page |
|---|---|---|---|
| Bundesarbeitsgemeinschaft Wohnungslosenhilfe e.V. | BE | 17 (11 Vorstand, 6 Präsidium) | Vorstand and Präsidium pages |
| Bundesarbeitsgemeinschaft der Freien Wohlfahrtspflege e.V. | DE | 3 | Gremien page (Präsident Achim Meyer auf der Heyde until 31.12.2026; Vizepräsident:innen Michael Groß, Eva Maria Welskop-Deffaa) |
| Diakonie Deutschland, Evangelisches Werk für Diakonie und Entwicklung e.V. | DE | 2 | Struktur page (Präsident Rüdiger Schuch; Vorstand Finanzen, Personal, Recht Jörg Kruttschnitt) |
| Deutscher Caritasverband e. V. | DE | 4 | Struktur und Leitung |
| Arbeiterwohlfahrt Bundesverband e. V. | DE | 7 (5 Präsidium, 2 Vorstand) | Präsidium und Vorstand; Vorstand |
| Deutsches Rotes Kreuz e.V. | DE | 3 | Präsidium (Präsident Hermann Gröhe, elected 29 November 2025; Vizepräsident Jürgen Christmann; Vizepräsidentin Ulrike Würth) |

Every row has a verbatim quote of at most two sentences from the archived HTML, a stand date of 2026-11-23, licence rights reserved with short § 51 quotes, `redistribute_fulltext=0`. Legal form is `e.V.`; officers are never attached to a gGmbH of the same name. Orgs are resolved with `resolve_org` / `find_org` (including any Land, so a BAG W already stored as DE is reused) then `ensure_org`.

### What was left out, on purpose

- Impressum URLs are not in the seed catalog.
- AWO Vorstand page lists personal emails, phone numbers, and staff (Vorstandsassistentin, Referent, Vorstandsreferentin). Those contacts and staff are not stored; quotes never include `@` or a telephone number.
- AWO “Zur Person” blocks include birth dates and family status; those tokens are not stored. Stefan Wolfshörndl is listed under Stellvertretende Vorsitzende des Präsidiums but the page has no contiguous Bundesverband role phrase that can be quoted without the private bio, so he is not stored in this pass.
- Gerda Hasselfeldt is named Ehrenpräsidentin on the DRK page and is not stored as current Präsidentin.
- The Paritätischer Gesamtverband transparenz-compliance page (`https://www.der-paritaetische.de/verband/transparenz-compliance/`, redirect from `/verband/gremien/`) does not list Vorstand names in the visible text. Achim Meyer auf der Heyde is recorded only as Präsident of the BAGFW, from the BAGFW page, not as a Paritätischer-org officer.
- ZWST: guessed organ/Vorstand URLs returned HTTP 404; no confirmed Gremien or Jahresbericht URL in this pass.
- Land associations of Diakonie, Caritas, AWO, DRK, Paritätischer and ZWST, and Jahresbericht / transparency-report PDFs, are still to do.

No new hand-archive URLs. Hamburg and Leipzig remain fail-closed skips, not hand-archive items.

## Hand-archived Krankenhauspläne (SH 2017, Bremen 2022–2024, Saarland 2018–2025 and 2027–2035) — 2026-11-23

All six PDFs are in `~/projects/_manual_archive/institutions_media/` (SHA256SUMS, SIZES, provenance `PROVENANCE_2026-11-23_krankenhausplaene.md`). Readers check the sha256 before parsing and make no network calls (same pattern as `funding_manual`). None of the six states a licence; all are stored as rights reserved with `redistribute_fulltext=0`. § 5 UrhG is not used.

Citations use the landing or file URL from the provenance file, plus PDF page and line.

### Schleswig-Holstein (Krankenhausplan 2017)

Land totals from Teil A only, quote-safe sentences:

- Aktuell (year 2017): KJP 244 Planbetten / 167 tagesklinische Plätze (PDF-S. 79); Psychiatrie 1.981 / 746 (PDF-S. 80); Psychosomatik 450 / 107 (PDF-S. 81).
- Angebot 2015: KJP 239 Planbetten and 150 tagesklinische Plätze (Stand 2015); Psychiatrie 1.962 / 700; Psychosomatik 448 Planbetten. The 107 psychosomatic day places (“Es stehen somit 107 Plätze an sieben Standorten”) have no year in the sentence, so they are not stored as 2015.

Per-hospital rows are skipped: the Anlagen 390/820/830 sheets mix two columns on the same line (same problem as the Havelland sheet in Brandenburg). The Besonderer Teil is registered as a source but has no quote-safe hospital table in this pass. All three SH files are registered.

### Bremen (Krankenhausrahmenplan 2022–2024, 13. Februar 2023)

Land totals from Tabelle 4, Spalte 2022 (PDF-S. 59): KJP 50 / 43, Psychiatrie 563 / 268, Psychosomatik 30 Planbetten. There is no Land row for psychosomatic day places. The 2022 value is the 13th year column, not the trailing Veränderung. Rechnerischer Bedarf 2024/2030 (Tabelle 48–55) is four scenarios (SI–SIV), so it is not stored as a single total.

Per-hospital 2022 rows from the 13-column Fachgebiet tables, which sum exactly to the Land totals:

- AMEOS Klinikum Bremen (mbH, 04011): Psychiatrie 201 / 35
- Klinikum Bremen-Nord (Gesundheit Nord gGmbH, 04011): 49 / 43
- Klinikum Bremen-Ost (Gesundheit Nord gGmbH, 04011): KJP 50 / 23, Psychiatrie 220 / 153, Psychosomatik 30
- Arche Klinik (Diakonie Arche Bremerhaven gemeinnützige GmbH, 04012): KJP 20 day places
- Klinikum Bremerhaven-Reinkenheide gGmbH (04012): Psychiatrie 93 / 37

Hospital organisations go through `ensure_hospital_org` / `ensure_org`.

### Saarland 2018–2025

Land Festlegungen (quote-safe single lines with both Planbetten and Plätze): 31.12.2017 KJP 55 / 60, Psychiatrie 643 / 248, Psychosomatik 86 / 10; 31.12.2025 KJP 71 / 73, Psychiatrie 690 / 289, Psychosomatik 90 / 12. Cited from the ministry landing page.

Per-hospital Standort tables are skipped: they mix 2017 and 2025 columns plus Veränderung, and several names wrap (for example “Tagesklinik Wadern vom Klini-”).

### Saarland 2027–2035

Land Versorgungsangebot 2023 (quote-safe prose): KJP 73 / 77, Psychiatrie 739 / 314, Psychosomatik 126 / 24. Cited from the ministry landing page. 2035 Bedarf figures are averages / “rd.” ranges and are not stored.

Per-hospital Planungsentscheidung tables are stored where Planbetten and Planplätze sit on the same line as the hospital name (year 2027, except Marienhaus Klinikum Neunkirchen KJP 10 Plätze ab 01.01.2028). Zero-bed rows store only day places (Klinikum Merzig 33; Marienhaus Neunkirchen 10). Johannesbad Saarschleife Fachkrankenhaus für Psychosomatische Medizin und Psychotherapie is skipped: the name wraps around the 15 / 0 figures, so the line is not quote-safe. Clean psychosomatic rows kept: CaritasKlinikum Saarbrücken, St. Josef 38 / 30; Knappschaft Kliniken Püttlingen 30 / 12; MEDIAN Klinik Berus 36.

