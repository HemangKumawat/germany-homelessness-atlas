-- Germany Atlas – Datenbankschema (eigene Fassung, Schema-Version 2: deutsche Spaltennamen).
--
-- Wird von ingest/run.py bei jedem Lauf idempotent angewendet. Vorher hebt ingest/migrate.py eine
-- Datenbank im alten Layout (Schema 1, englische Spaltennamen) verlustfrei auf dieses Layout an.
-- Spätere Änderungen: nur additiv (neue Tabellen, neue NULL-fähige Spalten über run.MIGRATIONS).
--
-- Regeln, die hier per Constraint gelten und scripts/verify.py zusätzlich prüft:
--   * jede Faktenzeile verweist mit source_id auf ihre Quelle (source.id)
--   * Schätzungen tragen is_est = 1, vom Herausgeber gerundete Werte is_rounded = 1
--   * geschützte Einrichtungen (Frauenhaus, Schutzwohnung …) haben nie Anschrift, PLZ oder Koordinaten
--   * Personen nur in org_person, nur mit veröffentlichter Funktion und Quelle
--   * Geldbeträge in EUR, sofern die Zeile keine andere ISO-4217-Währung nennt
-- Die Spaltennamen sind in docs/INGEST_CONTRACT.md beschrieben (Abschnitt „Schema 2“).

-- ───────────────────────────────────────────── Quellen
CREATE TABLE IF NOT EXISTS source (
  id                    INTEGER PRIMARY KEY,         -- Quellen-Nr.
  domain                TEXT NOT NULL,               -- Ingest-Domäne, die die Quelle registriert hat
  url                   TEXT NOT NULL CHECK (url LIKE 'http%'),
  title                 TEXT,
  publisher             TEXT,
  license               TEXT,                        -- Lizenz-/Nutzungsbedingung wie veröffentlicht
  license_url           TEXT,
  attribution           TEXT,                        -- Pflicht-Quellenvermerk, wörtlich
  redistribute_fulltext INTEGER NOT NULL DEFAULT 1 CHECK (redistribute_fulltext IN (0,1)),
  retrieved_at          TEXT,                        -- ISO 8601 mit Offset
  bytes                 INTEGER,
  sha256                TEXT CHECK (sha256 IS NULL OR length(sha256) = 64),
  local_path            TEXT,                        -- Archivkopie (relativ zum Repo, nie veröffentlicht)
  text_path             TEXT,                        -- extrahierter Text für verify.py
  content_type          TEXT,
  slug                  TEXT UNIQUE,
  notes                 TEXT,
  UNIQUE (domain, url)
);
CREATE INDEX IF NOT EXISTS quelle_nach_url ON source(url);

-- ───────────────────────────────────────────── Gebiete (AGS)
CREATE TABLE IF NOT EXISTS geo_country (
  code        TEXT PRIMARY KEY CHECK (code = 'DE'),
  name        TEXT NOT NULL CHECK (trim(name) <> ''),
  lat         REAL CHECK (lat IS NULL OR lat BETWEEN 47.0 AND 55.2),   -- Breite WGS84
  lon         REAL CHECK (lon IS NULL OR lon BETWEEN 5.5 AND 15.3),    -- Länge WGS84
  geometry    TEXT,                                -- vereinfachtes GeoJSON
  source_id   INTEGER NOT NULL REFERENCES source(id)
);

CREATE TABLE IF NOT EXISTS geo_land (
  ags         TEXT PRIMARY KEY CHECK (length(ags) = 2 AND ags GLOB '[01][0-9]'),
  abbr        TEXT UNIQUE,                         -- ISO 3166-2:DE-Kürzel (BW, BY, BE …)
  name        TEXT NOT NULL CHECK (trim(name) <> ''),
  bez         TEXT,                                -- Land | Freistaat | Freie und Hansestadt …
  ars         TEXT,
  nuts        TEXT,
  einwohner   INTEGER CHECK (einwohner IS NULL OR einwohner >= 0),
  flaeche_km2 REAL,
  lat         REAL CHECK (lat IS NULL OR lat BETWEEN 47.0 AND 55.2),
  lon         REAL CHECK (lon IS NULL OR lon BETWEEN 5.5 AND 15.3),
  geometry    TEXT,
  geometry_source_id INTEGER REFERENCES source(id),
  is_est      INTEGER NOT NULL DEFAULT 0 CHECK (is_est IN (0,1)),
  source_id   INTEGER NOT NULL REFERENCES source(id)
);

CREATE TABLE IF NOT EXISTS geo_kreis (
  ags         TEXT PRIMARY KEY CHECK (length(ags) = 5 AND ags GLOB '[01][0-9][0-9][0-9][0-9]'),
  land_ags    TEXT REFERENCES geo_land(ags),
  land        TEXT,                                -- Länderkürzel
  name        TEXT NOT NULL CHECK (trim(name) <> ''),
  kind        TEXT,                                -- landkreis | kreisfreie_stadt | kreis | regionalverband …
  bez         TEXT,
  ars         TEXT,
  nuts        TEXT,
  einwohner   INTEGER CHECK (einwohner IS NULL OR einwohner >= 0),
  lat         REAL CHECK (lat IS NULL OR lat BETWEEN 47.0 AND 55.2),
  lon         REAL CHECK (lon IS NULL OR lon BETWEEN 5.5 AND 15.3),
  geometry    TEXT,
  geometry_source_id INTEGER REFERENCES source(id),
  source_id   INTEGER NOT NULL REFERENCES source(id),
  CHECK (land_ags IS NULL OR land_ags = substr(ags, 1, 2))
);
CREATE INDEX IF NOT EXISTS kreis_nach_land ON geo_kreis(land_ags);

CREATE TABLE IF NOT EXISTS geo_gemeinde (
  ags         TEXT PRIMARY KEY CHECK (length(ags) = 8 AND ags GLOB '[01][0-9]*'),
  land_ags    TEXT,
  kreis_ags   TEXT,
  land        TEXT,
  name        TEXT NOT NULL CHECK (trim(name) <> ''),
  kind        TEXT,
  einwohner   INTEGER CHECK (einwohner IS NULL OR einwohner >= 0),
  lat         REAL CHECK (lat IS NULL OR lat BETWEEN 47.0 AND 55.2),   -- veröffentlichter Mittelpunkt
  lon         REAL CHECK (lon IS NULL OR lon BETWEEN 5.5 AND 15.3),
  source_id   INTEGER NOT NULL REFERENCES source(id),
  flaeche_km2 REAL,                                -- Schema 3
  geometry    TEXT,                                -- Schema 3: vereinfachtes GeoJSON (VG250)
  geometry_source_id INTEGER REFERENCES source(id),-- Schema 3
  CHECK (kreis_ags IS NULL OR kreis_ags = substr(ags, 1, 5))
);
CREATE INDEX IF NOT EXISTS gemeinde_nach_kreis ON geo_gemeinde(kreis_ags);

-- ───────────────────────────────────────────── Träger, Register, Funktionsträger
CREATE TABLE IF NOT EXISTS org (
  id               INTEGER PRIMARY KEY,
  name             TEXT NOT NULL CHECK (trim(name) <> ''),
  name_norm        TEXT NOT NULL,                  -- ingest.common.name_norm(name)
  legal_form       TEXT,                           -- e.V. | gGmbH | gUG | Stiftung | KdöR | AöR | eG …
  legal_form_norm  TEXT CHECK (legal_form_norm IS NULL OR legal_form_norm IN
                   ('ev','ggmbh','gmbh','ag','stiftung','koer','kdoer','eg','gbr','other')),  -- Schema 6: orglink.legal_form_norm(); NULL = unbekannt
  org_type         TEXT,                           -- freier_traeger | kommunal | government | faith | forprofit | unknown …
  register_id      TEXT,                           -- Registerangabe wie gedruckt; strukturiert in org_register
  ust_id           TEXT,
  lei              TEXT,
  wz               TEXT,                           -- WZ-2008-Code
  registerstatus   TEXT,                           -- active | aufgeloest | unbekannt …
  gruendungsjahr   INTEGER,
  land             TEXT,
  kreis            TEXT,
  kreis_ags        TEXT,
  plz              TEXT,
  ort              TEXT,
  strasse          TEXT,                           -- veröffentlichte Geschäftsanschrift
  lat              REAL CHECK (lat IS NULL OR lat BETWEEN 47.0 AND 55.2),
  lon              REAL CHECK (lon IS NULL OR lon BETWEEN 5.5 AND 15.3),
  webseite         TEXT,
  email            TEXT,                           -- nur veröffentlichte Funktionsadresse
  telefon          TEXT,
  geschaeftsjahr   INTEGER,                        -- Bezugsjahr der folgenden Jahresabschlusszahlen
  ertraege_eur     INTEGER,
  aufwendungen_eur INTEGER,
  bilanzsumme_eur  INTEGER,
  beschaeftigte    INTEGER,
  currency         TEXT NOT NULL DEFAULT 'EUR' CHECK (length(currency) = 3),
  is_protected     INTEGER NOT NULL DEFAULT 0 CHECK (is_protected IN (0,1)),  -- Träger IST eine Schutzeinrichtung
  is_est           INTEGER NOT NULL DEFAULT 0 CHECK (is_est IN (0,1)),
  quote            TEXT,
  locator          TEXT,
  aktualisiert_am  TEXT,
  source_id        INTEGER NOT NULL REFERENCES source(id),
  canonical_org_id INTEGER REFERENCES org(id),     -- Schema 5: NULL = kanonischer Träger; sonst Alias-Zeile (ingest/orglink.py)
  CHECK (is_protected = 0 OR (strasse IS NULL AND plz IS NULL AND lat IS NULL AND lon IS NULL))
);
-- Schema 6: ein Träger = (name_norm, Rechtsform, Land); e.V. und gGmbH gleichen Namens sind zwei Zeilen (INGEST_CONTRACT §12)
CREATE UNIQUE INDEX IF NOT EXISTS org_eindeutig ON org(name_norm, coalesce(legal_form_norm, ''), land);
CREATE INDEX IF NOT EXISTS org_nach_land ON org(land);
CREATE INDEX IF NOT EXISTS org_nach_register ON org(register_id);
CREATE INDEX IF NOT EXISTS org_nach_kreis ON org(kreis_ags);

-- Registerkennungen, strukturiert. Ein Träger kann mehrere haben (VR + Lobbyregister + …).
CREATE TABLE IF NOT EXISTS org_register (
  id          INTEGER PRIMARY KEY,
  org_id      INTEGER NOT NULL REFERENCES org(id),
  scheme      TEXT NOT NULL CHECK (scheme IN ('VR','HRA','HRB','GnR','PR','StiftReg','LobbyR',
                'BE_ZUWDB','USt-IdNr','LEI','EU_TR','other')),
  court       TEXT NOT NULL DEFAULT '',            -- Registergericht
  number      TEXT NOT NULL,
  raw         TEXT,
  source_id   INTEGER NOT NULL REFERENCES source(id),
  UNIQUE (scheme, court, number)
);
CREATE INDEX IF NOT EXISTS register_nach_org ON org_register(org_id);

-- Funktionsträger (Vorstand, Geschäftsführung, Aufsichtsrat, Lobby-Kontakt …) wie in einer
-- veröffentlichten Quelle genannt (Registerbekanntmachung, Jahresbericht, Lobbyregister, Impressum).
-- Nie Privatpersonen.
CREATE TABLE IF NOT EXISTS org_person (
  id                    INTEGER PRIMARY KEY,
  org_id                INTEGER NOT NULL REFERENCES org(id),
  org_bezeichnung       TEXT,                      -- Trägername wie in der Quelle
  funktionstraeger      TEXT NOT NULL CHECK (trim(funktionstraeger) <> ''),
  funktionstraeger_norm TEXT,
  funktion              TEXT NOT NULL CHECK (length(trim(funktion)) > 0),   -- veröffentlichte Funktion
  rollenklasse          TEXT,                      -- vorstand | geschaeftsfuehrung | aufsichtsrat | kuratorium | lobby_kontakt …
  jahr                  INTEGER,
  gueltig_ab            TEXT,
  gueltig_bis           TEXT,
  verguetung_eur        INTEGER,                   -- nur wenn veröffentlicht
  locator               TEXT,
  quote                 TEXT,                      -- wörtliche Belegstelle aus dem archivierten Dokument (Schema 4)
  stand                 TEXT,                      -- Stand der Angabe (Registerversion gültig ab / Abrufdatum), ISO 8601
  source_id             INTEGER NOT NULL REFERENCES source(id),
  UNIQUE (funktionstraeger_norm, org_bezeichnung, jahr, funktion)
);
CREATE INDEX IF NOT EXISTS funktionstraeger_nach_name ON org_person(funktionstraeger_norm);
CREATE INDEX IF NOT EXISTS funktionstraeger_nach_org ON org_person(org_id);

-- ───────────────────────────────────────────── Förderungen und Aufträge
CREATE TABLE IF NOT EXISTS award (
  id                    INTEGER PRIMARY KEY,
  foerder_schluessel    TEXT UNIQUE,               -- '<Schema>:<Nr>', z. B. 'DE-BE-ZUW:8528', 'TED:…'
  foerder_id            TEXT,                      -- Kennung beim Geber
  foerderart            TEXT,                      -- zuwendung | auftrag | other
  zuwendungsgeber       TEXT,                      -- Geber / öffentlicher Auftraggeber
  dienststelle          TEXT,
  programm              TEXT,
  programm_code         TEXT,                      -- z. B. CPV-Code oder Haushaltstitel
  nace                  TEXT,
  zweck                 TEXT,
  empfaenger            TEXT,
  empfaenger_norm       TEXT,
  empfaenger_id         TEXT,
  empfaenger_register   TEXT,                      -- Registerangabe wie gedruckt (vr_021507, HRB 1234 B)
  org_id                INTEGER REFERENCES org(id),
  betrag                REAL,
  currency              TEXT NOT NULL DEFAULT 'EUR' CHECK (length(currency) = 3),
  haushaltsjahr         TEXT,
  laufzeit_von          TEXT,
  laufzeit_bis          TEXT,
  ort_land              TEXT,
  ort_kreis             TEXT,
  ort_gemeinde          TEXT,
  is_est                INTEGER NOT NULL DEFAULT 0 CHECK (is_est IN (0,1)),
  quote                 TEXT,
  locator               TEXT,
  source_id             INTEGER NOT NULL REFERENCES source(id)
);
CREATE INDEX IF NOT EXISTS foerderung_nach_org ON award(org_id);
CREATE INDEX IF NOT EXISTS foerderung_nach_land ON award(ort_land);
CREATE INDEX IF NOT EXISTS foerderung_nach_programm ON award(programm_code);
CREATE INDEX IF NOT EXISTS foerderung_nach_empfaenger ON award(empfaenger_norm);

-- ───────────────────────────────────────────── Zählungen
-- Amtliche Stichtagszahlen je Gebiet. geo_ags: 'DE' | 2- | 5- | 8-stellige AGS.
CREATE TABLE IF NOT EXISTS zaehlung (
  geo_ags          TEXT NOT NULL,
  geo_kind         TEXT NOT NULL CHECK (geo_kind IN ('bund','land','kreis','gemeinde')),
  berichtsjahr     INTEGER NOT NULL CHECK (berichtsjahr BETWEEN 1990 AND 2100),
  stichtag         TEXT,                           -- z. B. 2026-01-31
  untergebracht    INTEGER CHECK (untergebracht IS NULL OR untergebracht >= 0),      -- Destatis, WoBerichtsG
  ohne_unterkunft  INTEGER CHECK (ohne_unterkunft IS NULL OR ohne_unterkunft >= 0),  -- auf der Straße
  verdeckt         INTEGER CHECK (verdeckt IS NULL OR verdeckt >= 0),                -- verdeckt wohnungslos
  insgesamt        INTEGER CHECK (insgesamt IS NULL OR insgesamt >= 0),
  minderjaehrige   INTEGER CHECK (minderjaehrige IS NULL OR minderjaehrige >= 0),    -- darunter unter 18 Jahre
  haushalte        INTEGER CHECK (haushalte IS NULL OR haushalte >= 0),
  is_est           INTEGER NOT NULL DEFAULT 0 CHECK (is_est IN (0,1)),
  is_rounded       INTEGER NOT NULL DEFAULT 0 CHECK (is_rounded IN (0,1)),
  quote            TEXT,
  locator          TEXT,
  source_id        INTEGER NOT NULL REFERENCES source(id),
  PRIMARY KEY (geo_ags, geo_kind, berichtsjahr),
  CHECK ((geo_kind='bund' AND geo_ags='DE') OR (geo_kind='land' AND length(geo_ags)=2)
      OR (geo_kind='kreis' AND length(geo_ags)=5) OR (geo_kind='gemeinde' AND length(geo_ags)=8))
);

-- Kennzahlen beliebiger Domänen mit wörtlichem Beleg.
CREATE TABLE IF NOT EXISTS metric (
  id          INTEGER PRIMARY KEY,
  entity_type TEXT NOT NULL,                       -- de | bund | land | kreis | gemeinde | org | facility …
  entity_id   TEXT NOT NULL,
  metric      TEXT NOT NULL,
  year        INTEGER CHECK (year IS NULL OR year BETWEEN 1900 AND 2100),
  period      TEXT,                                -- genauer Stichtag oder Zeitraum
  value       REAL NOT NULL,
  einheit     TEXT,                                -- persons | beds | EUR | flag …
  is_est      INTEGER NOT NULL DEFAULT 0 CHECK (is_est IN (0,1)),
  is_rounded  INTEGER NOT NULL DEFAULT 0 CHECK (is_rounded IN (0,1)),
  anmerkung   TEXT,
  quote       TEXT,
  locator     TEXT,
  source_id   INTEGER NOT NULL REFERENCES source(id),
  UNIQUE (entity_type, entity_id, metric, year)
);
CREATE INDEX IF NOT EXISTS kennzahl_nach_typ ON metric(entity_type, metric);

-- Gebietskennzahlen tragen immer den AGS des Gebiets: Land 2-, Kreis 5-, Gemeinde 8-stellig (nie das Länderkürzel)
CREATE TRIGGER IF NOT EXISTS kennzahl_ags_neu BEFORE INSERT ON metric
WHEN (NEW.entity_type = 'land' AND NOT (length(NEW.entity_id) = 2 AND NEW.entity_id GLOB '[01][0-9]'))
  OR (NEW.entity_type = 'kreis' AND NOT (length(NEW.entity_id) = 5 AND NEW.entity_id GLOB '[01][0-9][0-9][0-9][0-9]'))
  OR (NEW.entity_type = 'gemeinde' AND NOT (length(NEW.entity_id) = 8 AND NEW.entity_id GLOB '[01][0-9][0-9][0-9][0-9][0-9][0-9][0-9]'))
BEGIN SELECT RAISE(ABORT, 'metric: land/kreis/gemeinde need the AGS (land e.g. 12, not BB)'); END;
CREATE TRIGGER IF NOT EXISTS kennzahl_ags_aenderung BEFORE UPDATE OF entity_type, entity_id ON metric
WHEN (NEW.entity_type = 'land' AND NOT (length(NEW.entity_id) = 2 AND NEW.entity_id GLOB '[01][0-9]'))
  OR (NEW.entity_type = 'kreis' AND NOT (length(NEW.entity_id) = 5 AND NEW.entity_id GLOB '[01][0-9][0-9][0-9][0-9]'))
  OR (NEW.entity_type = 'gemeinde' AND NOT (length(NEW.entity_id) = 8 AND NEW.entity_id GLOB '[01][0-9][0-9][0-9][0-9][0-9][0-9][0-9]'))
BEGIN SELECT RAISE(ABORT, 'metric: land/kreis/gemeinde need the AGS (land e.g. 12, not BB)'); END;

-- ───────────────────────────────────────────── Einrichtungen
CREATE TABLE IF NOT EXISTS facility (
  id                  INTEGER PRIMARY KEY,
  name                TEXT NOT NULL CHECK (trim(name) <> ''),
  name_norm           TEXT NOT NULL,
  kind                TEXT,   -- psychiatric | psych_unit | prison | shelter | notunterkunft | beratungsstelle |
                              -- tagesaufenthalt | frauenhaus | schutzwohnung | protected_shelter | other
  betriebsstatus      TEXT,                        -- active | closed | unknown
  eroeffnet           INTEGER,
  geschlossen         INTEGER,
  betten              INTEGER CHECK (betten IS NULL OR betten >= 0),
  traeger             TEXT,
  traeger_org_id      INTEGER REFERENCES org(id),
  zielgruppe          TEXT,                        -- Zielgruppe wie veröffentlicht
  land                TEXT,
  kreis_ags           TEXT,
  ort                 TEXT,
  anschrift           TEXT,
  plz                 TEXT,
  lat                 REAL CHECK (lat IS NULL OR lat BETWEEN 47.0 AND 55.2),
  lon                 REAL CHECK (lon IS NULL OR lon BETWEEN 5.5 AND 15.3),
  is_protected        INTEGER NOT NULL DEFAULT 0 CHECK (is_protected IN (0,1)),
  haushalt_eur        INTEGER,
  personal            INTEGER,
  kosten_je_platz_eur INTEGER,
  currency            TEXT NOT NULL DEFAULT 'EUR' CHECK (length(currency) = 3),
  is_est              INTEGER NOT NULL DEFAULT 0 CHECK (is_est IN (0,1)),
  quote               TEXT,
  locator             TEXT,
  source_id           INTEGER NOT NULL REFERENCES source(id),
  UNIQUE (name_norm, land, ort),
  CHECK (coalesce(kind,'') NOT IN ('frauenhaus','schutzwohnung','protected_shelter') OR is_protected = 1),
  CHECK (is_protected = 0 OR (anschrift IS NULL AND plz IS NULL AND lat IS NULL AND lon IS NULL))
);
CREATE INDEX IF NOT EXISTS einrichtung_nach_land ON facility(land);
CREATE INDEX IF NOT EXISTS einrichtung_nach_art ON facility(kind);

-- ───────────────────────────────────────────── Recht, Dokumente, Medien
CREATE TABLE IF NOT EXISTS law (
  id               INTEGER PRIMARY KEY,
  jurisdiction     TEXT,                           -- DE | Länderkürzel | Kommunal-AGS
  jurisdiction_ags TEXT,
  kind             TEXT,                           -- bundesgesetz | landesgesetz | verordnung | satzung | urteil | programm | aktionsplan | haushalt
  topic            TEXT,
  short_name       TEXT,                           -- SGB XII, WoBerichtsG …
  citation         TEXT,
  title            TEXT,
  summary          TEXT,
  status           TEXT,
  year             INTEGER,
  in_force_from    TEXT,
  in_force_to      TEXT,
  url              TEXT,
  source_id        INTEGER NOT NULL REFERENCES source(id),
  UNIQUE (jurisdiction, citation, title)
);

CREATE TABLE IF NOT EXISTS media (
  id               INTEGER PRIMARY KEY,
  kind             TEXT,                           -- image | video | article …
  title            TEXT NOT NULL CHECK (trim(title) <> ''),
  url              TEXT UNIQUE CHECK (url IS NULL OR url LIKE 'http%'),
  herausgeber      TEXT,                           -- Sender, Verlag, Plattform
  urheber          TEXT,                           -- wie genannt
  veroeffentlicht  TEXT,
  lizenz           TEXT,
  vorschaubild     TEXT,
  dauer_s          INTEGER,
  ort              TEXT,
  land             TEXT,
  zusammenfassung  TEXT,
  source_id        INTEGER NOT NULL REFERENCES source(id)
);
CREATE INDEX IF NOT EXISTS medien_nach_land ON media(land);

CREATE TABLE IF NOT EXISTS doc (
  id               INTEGER PRIMARY KEY,
  kind             TEXT,                           -- drucksache | audit | study | court | report …
  title            TEXT NOT NULL CHECK (trim(title) <> ''),
  url              TEXT UNIQUE CHECK (url IS NULL OR url LIKE 'http%'),
  herausgeber      TEXT,
  urheber          TEXT,
  veroeffentlicht  TEXT,
  ort              TEXT,
  land             TEXT,
  zusammenfassung  TEXT,
  source_id        INTEGER NOT NULL REFERENCES source(id)
);

-- ───────────────────────────────────────────── Betrieb
CREATE TABLE IF NOT EXISTS ingest_run (
  id          INTEGER PRIMARY KEY,
  domain      TEXT,
  ts          TEXT,                                -- = started_at
  started_at  TEXT,
  finished_at TEXT,
  status      TEXT CHECK (status IS NULL OR status IN ('running','ok','failed')),
  ok          INTEGER,
  rows        INTEGER,
  error       TEXT,
  notes       TEXT,
  host        TEXT,
  pid         INTEGER,
  git_rev     TEXT
);
CREATE INDEX IF NOT EXISTS lauf_nach_domain ON ingest_run(domain, ts);

-- Schema 5: Spaltenfüllstand je Lauf (NULL-Regressionsprüfung G11c), vorher/nachher
CREATE TABLE IF NOT EXISTS ingest_colstats (
  run_id   INTEGER NOT NULL REFERENCES ingest_run(id),
  phase    TEXT NOT NULL CHECK (phase IN ('before','after')),
  tbl      TEXT NOT NULL,
  col      TEXT NOT NULL,                                -- '*' = Zeilenzahl
  nonnull  INTEGER NOT NULL,
  PRIMARY KEY (run_id, phase, tbl, col)
);

-- ───────────────────────────────────────────── Entitätsauflösung (Schema 5)
-- Eine Zeile je quellseitigem Träger-Datensatz (org-Zeile, org_register-Zeile, Förderempfänger, Wikidata-Item …):
-- auf welchen kanonischen Träger er zeigt, nach welcher Methode, mit welcher Sicherheit. Namensabgleich ist immer
-- 'name_fuzzy' und flagged = 1; er führt nie Träger zusammen. Trigger und Hilfsfunktionen: ingest/orglink.py.
CREATE TABLE IF NOT EXISTS org_link (
  id            INTEGER PRIMARY KEY,
  org_id        INTEGER NOT NULL REFERENCES org(id),     -- kanonischer Träger
  record_kind   TEXT NOT NULL,                           -- org | org_register | award | wikidata | …
  record_key    TEXT NOT NULL,                           -- org-Id, scheme|court|number, foerder_schluessel, QID …
  record_name   TEXT,                                    -- Trägername wie im Datensatz
  source_system TEXT,                                    -- lobbyregister | berlin_zuwendungen | ted | ba_jobcenter | org_register:<scheme> | wikidata | domain:<d>
  id_value      TEXT,                                    -- normalisierte harte Kennung (UST:DE…, HRB:123:CHARLOTTENBURG, BE_ZUWDB:vr_…, QID:Q…)
  method        TEXT NOT NULL CHECK (method IN ('register_id','lei','ust_id','wikidata_qid','name_fuzzy','manual','origin')),
  confidence    REAL NOT NULL CHECK (confidence BETWEEN 0 AND 1),
  flagged       INTEGER NOT NULL DEFAULT 0 CHECK (flagged IN (0,1)),   -- 1 = Namensabgleich, Prüfung offen
  reviewed      INTEGER NOT NULL DEFAULT 0 CHECK (reviewed IN (0,1)),
  note          TEXT,
  source_id     INTEGER NOT NULL REFERENCES source(id),
  run_id        INTEGER,
  UNIQUE (record_kind, record_key),
  CHECK (method <> 'name_fuzzy' OR flagged = 1),
  CHECK (method NOT IN ('register_id','lei','ust_id','wikidata_qid') OR id_value IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS verknuepfung_nach_org ON org_link(org_id);
CREATE INDEX IF NOT EXISTS verknuepfung_nach_kennung ON org_link(id_value);

-- ───────────────────────────────────────────── Suche
CREATE VIRTUAL TABLE IF NOT EXISTS search_fts USING fts5(
  kind UNINDEXED, ref UNINDEXED, title, body, tokenize = 'unicode61 remove_diacritics 2'
);

-- ───────────────────────────────────────────── Sichten
CREATE VIEW IF NOT EXISTS places AS
  SELECT code AS ags, 'bund' AS level, name, NULL AS parent_ags, lat, lon, source_id FROM geo_country
  UNION ALL SELECT ags, 'land', name, 'DE', lat, lon, source_id FROM geo_land
  UNION ALL SELECT ags, 'kreis', name, land_ags, lat, lon, source_id FROM geo_kreis
  UNION ALL SELECT ags, 'gemeinde', name, kreis_ags, lat, lon, source_id FROM geo_gemeinde;
CREATE VIEW IF NOT EXISTS sources AS SELECT *, license AS licence FROM source;
CREATE VIEW IF NOT EXISTS ingest_runs AS SELECT * FROM ingest_run;
