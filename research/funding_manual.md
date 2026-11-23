# funding_manual: manual-archive readers (Bremen, Rheinland-Pfalz)

Added 2026-11-23. Source mode "manual archive": the Lead saved the files by hand on deck at
~/projects/_manual_archive/funding_traeger/ (SHA256SUMS, SIZES, PROVENANCE.md). The reader opens only that
directory, makes no network request to the hosts, checks every file's sha256 against SHA256SUMS before parsing
and stops on a mismatch or a missing entry. Each file is seeded into the raw cache under its official download URL
(with meta.json) so G4/G5/G9 trace it like a fetched file; the source notes name the dataset page, the file and
"manual archive (browser, Lead, 2026-11-23)". Saarland: not archived, skipped.

## Bremen: Zuwendungen Quartalsberichte (ZEBRA), 2024 Q1 to 2026 Q3
- Licence CC BY 3.0 (dataset field "Lizenz"). 11 XLSX parsed; the 11 CSV twins are used only for a cross-check
  (same GKZ, same amount): 38 of 38 kept awards agree.
- Dedupe rule: by GKZ (Bremen's grant id, column "GKZ"). Quarterly reports restate the same grant; for each GKZ the
  report with the latest Berichtsdatum wins, and the locator states in how many reports the GKZ appears. Inside
  one file, identical duplicate rows are dropped; conflicting duplicates keep the larger Zuwendungssumme (58 identical,
  78 conflicting across all report rows, before the homelessness filter).
  21,887 report rows -> 8,537 distinct GKZ (6,348 restated in more than one report).
- Filter: core = shared BZ_CORE vocabulary plus Winternot, Tagesaufenthalt, Übernachtungsstätte, Krankenstube,
  Straßenzeitung, Obdach, Kälteregel, Erfrierungsschutz, Notschlafstelle, Housing First (also hyphenated);
  adjacent (Tagestreff, Streetwork, aufsuchende Straßensozialarbeit, BZ_ADJACENT) only from a social authority and
  never for refugee/migrant or youth provision (checked on Zweck and recipient).
- Organisations only: natural persons skipped (2). Protected shelters: none in the kept set; the rule (Land level only)
  is in place.
- Result on the scratch run: 38 awards, 13 recipients, EUR 3,615,559.98; years 2024: 12, 2025: 16, 2026: 10.
  Citation: dataset page + file + sheet/row/cell; quote is the cell line.
- Borderline kept: "Günstiger Mittagstisch ältere Menschen in der Suppenküche" (core via Suppenküche, EUR 35,000)
  and "Streetwork mal anders - Im Wasser statt an Land" (EUR 740.10).

## Rheinland-Pfalz: Zuwendungsübersicht MASTD 2024 (PDF, 10 pages)
- Licence dl-de/by-2-0. Parsed with the funding_mv bbox helpers (anchor "Epl." + date + Zuwendungsart + amount).
  87 grants parsed; 1 in scope: Prot. Kirchenbezirk Ludwigshafen, Suppenküche Ludwigshafen, EUR 1,000 (adjacent).
  Citation: dataset page + file + page/line.

## For the Lead
- VALID_MODE: funding_manual needs "--test" / "--selftest" like funding_mv.
- G9 float artifacts in spreadsheet cells: passed on this sample; the Lead's numeric-cell fix still applies.
