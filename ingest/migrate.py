"""Schema 2 migration: English column names (schema 1) -> German column names, US-only columns removed.

The mapping below is the single source of truth. It is used
  * by migrate() to lift an existing database in place (row ids kept, nothing lost), and
  * by ingest.common.upsert() to accept the old column names from modules that were written
    against schema 1 (transition aid for worker branches; see docs/INGEST_CONTRACT.md).

migrate() is lossless by construction: a column is only dropped when it holds no value in any row,
otherwise it refuses to run. Row counts are compared table by table and foreign keys and integrity
are checked before the transaction commits.
"""
from __future__ import annotations

import re
import sqlite3

SCHEMA_VERSION = 6

TABLE_RENAMES = {"pit": "zaehlung"}

COLUMN_RENAMES: dict[str, dict[str, str]] = {
    "geo_land": {"pop": "einwohner", "land_sqkm": "flaeche_km2"},
    "geo_kreis": {"pop": "einwohner"},
    "geo_gemeinde": {"pop": "einwohner"},
    "org": {"status": "registerstatus", "founded": "gruendungsjahr", "city": "ort", "address1": "strasse",
            "website": "webseite", "phone": "telefon", "fiscal_year": "geschaeftsjahr",
            "revenue": "ertraege_eur", "expenses": "aufwendungen_eur", "assets": "bilanzsumme_eur",
            "employees": "beschaeftigte", "updated_at": "aktualisiert_am"},
    "org_person": {"org_name": "org_bezeichnung", "person": "funktionstraeger", "person_norm": "funktionstraeger_norm",
                   "title": "funktion", "role_class": "rollenklasse", "year": "jahr", "valid_from": "gueltig_ab",
                   "valid_to": "gueltig_bis", "comp": "verguetung_eur"},
    "award": {"award_key": "foerder_schluessel", "award_id": "foerder_id", "award_type": "foerderart",
              "agency": "zuwendungsgeber", "office": "dienststelle", "program": "programm",
              "programme_code": "programm_code", "description": "zweck", "recipient_name": "empfaenger",
              "recipient_norm": "empfaenger_norm", "recipient_id": "empfaenger_id",
              "recipient_register": "empfaenger_register", "amount_total": "betrag", "fy": "haushaltsjahr",
              "pop_start": "laufzeit_von", "pop_end": "laufzeit_bis", "place_land": "ort_land",
              "place_kreis": "ort_kreis", "place_gemeinde": "ort_gemeinde"},
    "pit": {"year": "berichtsjahr", "sheltered": "untergebracht", "unsheltered": "ohne_unterkunft",
            "hidden": "verdeckt", "total": "insgesamt", "children": "minderjaehrige", "households": "haushalte"},
    "metric": {"unit": "einheit", "note": "anmerkung"},
    "facility": {"status": "betriebsstatus", "opened": "eroeffnet", "closed": "geschlossen", "beds": "betten",
                 "operator": "traeger", "operator_org_id": "traeger_org_id", "population_note": "zielgruppe",
                 "city": "ort", "address": "anschrift", "budget": "haushalt_eur", "staff": "personal",
                 "annual_cost_per_bed": "kosten_je_platz_eur"},
    "media": {"publisher": "herausgeber", "author": "urheber", "published": "veroeffentlicht", "license": "lizenz",
              "thumbnail": "vorschaubild", "duration": "dauer_s", "place": "ort", "summary": "zusammenfassung"},
    "doc": {"publisher": "herausgeber", "author": "urheber", "published": "veroeffentlicht", "place": "ort",
            "summary": "zusammenfassung"},
}
# US-only columns of schema 1 (HUD PIT sub-populations, USASpending fields, US facility economics).
DROPPED: dict[str, set[str]] = {
    "pit": {"chronic", "smi", "sud", "veterans", "hiv", "dv", "families", "youth"},
    "award": {"amount_obligated", "psc", "subtier"},
    "facility": {"capacity_est", "owner"},
}
REBUILT = ["geo_country", "geo_land", "geo_kreis", "geo_gemeinde", "org", "org_person", "award",
           "pit", "metric", "facility", "media", "doc"]
VIEWS = ["places", "sources", "ingest_runs"]


def new_table(table: str) -> str:
    return TABLE_RENAMES.get(table, table)


def translate(table: str, row: dict) -> tuple[str, dict]:
    """Map a schema-1 (table, row) to schema 2. Dropped columns must be empty."""
    old = {v: k for k, v in TABLE_RENAMES.items()}.get(table, table)
    ren = COLUMN_RENAMES.get(old, {})
    out = {}
    for k, v in row.items():
        if k in DROPPED.get(old, ()):
            if v not in (None, ""):
                raise ValueError(f"{old}.{k} was removed in schema 2 (US-only column); value {v!r} cannot be stored")
            continue
        out[ren.get(k, k)] = v
    return new_table(table), out


def is_legacy(conn) -> bool:
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    return "pit" in names or ("facility" in names and "address" in {r[1] for r in conn.execute("PRAGMA table_info(facility)")})


def _creates(schema_sql: str) -> dict[str, str]:
    return {m.group(1): m.group(0) for m in re.finditer(r"CREATE TABLE IF NOT EXISTS (\w+) \(.*?\n\);", schema_sql, re.S)}


def migrate(conn, schema_sql: str, log=print) -> dict:
    """Lift a schema-1 database to schema 2 in one transaction. Returns {table: rows}."""
    creates = _creates(schema_sql)
    conn.execute("PRAGMA foreign_keys=OFF")
    conn.execute("BEGIN IMMEDIATE")
    try:
        for v in VIEWS:
            conn.execute(f"DROP VIEW IF EXISTS {v}")
        have = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        counts = {}
        for old in REBUILT:
            if old not in have:
                continue
            new = new_table(old)
            ddl = creates[new].replace(f"CREATE TABLE IF NOT EXISTS {new} (", f"CREATE TABLE {new}__v2 (", 1)
            conn.execute(ddl)
            new_cols = [r[1] for r in conn.execute(f"PRAGMA table_info({new}__v2)")]
            old_cols = [r[1] for r in conn.execute(f"PRAGMA table_info({old})")]
            ren = COLUMN_RENAMES.get(old, {})
            inv = {v: k for k, v in ren.items()}
            src_of = {}
            for c in new_cols:
                o = inv.get(c, c)
                if o in old_cols:
                    src_of[c] = o
            unmapped = [c for c in old_cols if c not in src_of.values()]
            for c in unmapped:
                if c not in DROPPED.get(old, ()):
                    raise RuntimeError(f"migrate: {old}.{c} has no place in schema 2 and is not listed as dropped")
                n = conn.execute(f"SELECT count(*) FROM {old} WHERE {c} IS NOT NULL AND {c} <> ''").fetchone()[0]
                if n:
                    raise RuntimeError(f"migrate: refusing to drop {old}.{c}: {n} row(s) hold a value")
            cols = list(src_of)
            conn.execute(f"INSERT INTO {new}__v2 (rowid, {', '.join(cols)}) "
                         f"SELECT rowid, {', '.join(src_of[c] for c in cols)} FROM {old}")
            a = conn.execute(f"SELECT count(*) FROM {old}").fetchone()[0]
            b = conn.execute(f"SELECT count(*) FROM {new}__v2").fetchone()[0]
            if a != b:
                raise RuntimeError(f"migrate: {old} -> {new}: {a} rows before, {b} after")
            conn.execute(f"DROP TABLE {old}")
            conn.execute(f"ALTER TABLE {new}__v2 RENAME TO {new}")
            counts[new] = b
            log(f"migrate: {old} -> {new}: {b} rows; renamed {len([c for c in cols if c != src_of[c]])} "
                f"column(s), dropped {sorted(unmapped)}")
        # indexes and views of schema 2
        for stmt in re.findall(r"CREATE (?:INDEX|VIEW) IF NOT EXISTS .*?;", schema_sql, re.S):
            conn.execute(stmt)
        bad = conn.execute("PRAGMA foreign_key_check").fetchall()
        if bad:
            raise RuntimeError(f"migrate: foreign_key_check found {len(bad)} violation(s), e.g. {tuple(bad[0])}")
        conn.execute("PRAGMA user_version=2")   # upgrade() continues from here
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.execute("PRAGMA foreign_keys=ON")
    ok = conn.execute("PRAGMA integrity_check").fetchone()[0]
    if ok != "ok":
        raise RuntimeError(f"migrate: integrity_check {ok}")
    return counts


# ---- schema 5 -> 6 (2026-11-23): legal form in the org key (INGEST_CONTRACT §12)
# name_norm keys an earlier funding_traeger version wrote to dodge UNIQUE(name_norm, land): 'MALTESER HILFSDIENST EV'
OLD_KIND_TAGS = ("GGMBH", "GMBH", "GMBH CO KG", "UG", "AG", "EV", "EG", "KDOER", "AOER", "STIFTUNG")


def needs_v6(conn) -> bool:
    """True for an existing org table without legal_form_norm (must be rebuilt BEFORE schema.sql runs)."""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(org)")}
    return bool(cols) and "legal_form_norm" not in cols


def _v6_backfill(conn, table: str, log) -> dict:
    """legal_form_norm from the name / printed legal form; restore tagged name_norm keys to common.name_norm()."""
    from ingest import common, orglink
    out = {"legal_form_norm": 0, "name_norm_restored": []}
    rows = conn.execute(f"SELECT id, name, name_norm, legal_form, legal_form_norm FROM {table}").fetchall()
    for oid, name, nn, lf, lfn in rows:
        if lfn is None:
            v = orglink.legal_form_norm(name, lf)
            if v is not None:
                conn.execute(f"UPDATE {table} SET legal_form_norm=? WHERE id=?", (v, oid))
                out["legal_form_norm"] += 1
        std = common.name_norm(name)
        if nn != std and any(nn == f"{std} {t}" for t in OLD_KIND_TAGS):
            conn.execute(f"UPDATE {table} SET name_norm=? WHERE id=?", (std, oid))
            out["name_norm_restored"].append((oid, nn, std))
    dup = conn.execute(f"SELECT name_norm, coalesce(legal_form_norm,''), land, count(*) FROM {table} "
                       f"GROUP BY 1, 2, 3 HAVING count(*) > 1 AND land IS NOT NULL").fetchall()
    if dup:
        raise RuntimeError(f"upgrade 6: {len(dup)} duplicate (name_norm, legal_form_norm, land) keys, e.g. {tuple(dup[0])}")
    for oid, old, new in out["name_norm_restored"]:
        log(f"upgrade 6: org #{oid} name_norm {old!r} -> {new!r} (legal form is now its own key column)")
    return out


def upgrade_6(conn, schema_sql: str, log=print) -> dict:
    """Rebuild org with legal_form_norm and UNIQUE(name_norm, coalesce(legal_form_norm,''), land) instead of the
    inline UNIQUE(name_norm, land) (an inline constraint's index cannot be dropped). Every row and id is kept;
    indexes and triggers that name org are recreated from their stored SQL; one transaction."""
    ddl = _creates(schema_sql)["org"].replace("CREATE TABLE IF NOT EXISTS org (", "CREATE TABLE org__v6 (", 1)
    uniq = re.search(r"CREATE UNIQUE INDEX IF NOT EXISTS org_eindeutig ON org\(.*?\);", schema_sql).group(0)
    conn.execute("PRAGMA foreign_keys=OFF")
    conn.execute("BEGIN IMMEDIATE")
    try:
        ids_before = [r[0] for r in conn.execute("SELECT id FROM org ORDER BY id")]
        names_before = conn.execute("SELECT group_concat(id || '|' || name, char(10)) FROM (SELECT id, name FROM org ORDER BY id)").fetchone()[0]
        keep = conn.execute("SELECT type, name, sql FROM sqlite_master WHERE sql IS NOT NULL AND type IN ('index','trigger') "
                            "AND name <> 'org_eindeutig' AND (tbl_name='org' OR (type='trigger' AND sql LIKE '%FROM org %'))").fetchall()
        for typ, name, _sql in keep:
            conn.execute(f"DROP {typ.upper()} IF EXISTS {name}")
        conn.execute(ddl)
        new_cols = [r[1] for r in conn.execute("PRAGMA table_info(org__v6)")]
        old_cols = [r[1] for r in conn.execute("PRAGMA table_info(org)")]
        lost = [c for c in old_cols if c not in new_cols]
        if lost:
            raise RuntimeError(f"upgrade 6: org columns {lost} have no place in schema 6")
        cols = [c for c in old_cols]
        conn.execute(f"INSERT INTO org__v6 ({', '.join(cols)}) SELECT {', '.join(cols)} FROM org")
        bf = _v6_backfill(conn, "org__v6", log)
        conn.execute("DROP TABLE org")
        conn.execute("ALTER TABLE org__v6 RENAME TO org")
        conn.execute(uniq)
        for _typ, _name, sql in keep:
            conn.execute(sql)
        ids_after = [r[0] for r in conn.execute("SELECT id FROM org ORDER BY id")]
        names_after = conn.execute("SELECT group_concat(id || '|' || name, char(10)) FROM (SELECT id, name FROM org ORDER BY id)").fetchone()[0]
        if ids_before != ids_after or names_before != names_after:
            raise RuntimeError(f"upgrade 6: org rows/ids changed ({len(ids_before)} -> {len(ids_after)})")
        bad = conn.execute("PRAGMA foreign_key_check").fetchall()
        if bad:
            raise RuntimeError(f"upgrade 6: foreign_key_check found {len(bad)} violation(s), e.g. {tuple(bad[0])}")
        if conn.execute("PRAGMA user_version").fetchone()[0] >= 5:
            conn.execute("PRAGMA user_version=6")
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.execute("PRAGMA foreign_keys=ON")
    ok = conn.execute("PRAGMA integrity_check").fetchone()[0]
    if ok != "ok":
        raise RuntimeError(f"upgrade 6: integrity_check {ok}")
    log(f"upgrade 6: org rebuilt, {len(ids_after)} rows and ids kept; legal_form_norm filled on {bf['legal_form_norm']}; "
        f"{len(keep)} index/trigger definitions recreated; UNIQUE(name_norm, legal_form_norm, land)")
    return {"rows": len(ids_after), **bf}


def _upgrade_6_finish(conn, log) -> None:
    """A database whose org table already has the schema-6 shape (fresh, or rebuilt by upgrade_6): backfill, version."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        if not needs_v6(conn) and {r[1] for r in conn.execute("PRAGMA table_info(org)")}:
            _v6_backfill(conn, "org", log)
        conn.execute("PRAGMA user_version=6")
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise


# ---- schema 2 -> 3 (2026-11-21): Gemeinde area/geometry columns; Land letter codes in metric -> AGS
V3_COLUMNS = [("geo_gemeinde", "flaeche_km2", "REAL"), ("geo_gemeinde", "geometry", "TEXT"),
              ("geo_gemeinde", "geometry_source_id", "INTEGER REFERENCES source(id)")]
LAND_AGS = {"SH": "01", "HH": "02", "NI": "03", "HB": "04", "NW": "05", "HE": "06", "RP": "07", "BW": "08",
            "BY": "09", "SL": "10", "BE": "11", "BB": "12", "MV": "13", "SN": "14", "ST": "15", "TH": "16"}


def upgrade(conn, log=print) -> None:
    """Idempotent steps 2 -> 3 -> 4 -> 5, each in one transaction (called by ingest.run.open_db)."""
    if conn.execute("PRAGMA user_version").fetchone()[0] < 3:
        _upgrade_3(conn, log)
    if conn.execute("PRAGMA user_version").fetchone()[0] < 4:
        _upgrade_4(conn, log)
    if conn.execute("PRAGMA user_version").fetchone()[0] < 5:
        _upgrade_5(conn, log)
    if conn.execute("PRAGMA user_version").fetchone()[0] < 6:
        _upgrade_6_finish(conn, log)


def _upgrade_3(conn, log) -> None:
    conn.execute("BEGIN IMMEDIATE")
    try:
        for table, col, decl in V3_COLUMNS:
            if col not in {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
                log(f"upgrade 3: {table}.{col} added")
        moved = 0
        for abbr, ags in LAND_AGS.items():
            moved += conn.execute("UPDATE metric SET entity_id=? WHERE entity_type='land' AND entity_id=?",
                                  (ags, abbr)).rowcount
        log(f"upgrade 3: {moved} metric rows moved from Land letter codes to the Land AGS")
        conn.execute("PRAGMA user_version=3")
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise



# ---- schema 3 -> 4 (2026-11-21): org_person carries its verbatim quote and Stand (no domain side tables)
V4_COLUMNS = [("org_person", "quote", "TEXT"), ("org_person", "stand", "TEXT")]


def _upgrade_4(conn, log) -> None:
    conn.execute("BEGIN IMMEDIATE")
    try:
        before = conn.execute("SELECT count(*) FROM org_person").fetchone()[0]
        for table, col, decl in V4_COLUMNS:
            if col not in {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
                log(f"upgrade 4: {table}.{col} added")
        after = conn.execute("SELECT count(*) FROM org_person").fetchone()[0]
        if before != after:
            raise RuntimeError(f"upgrade 4: org_person {before} rows before, {after} after")
        conn.execute("PRAGMA user_version=4")
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise


# ---- schema 4 -> 5 (2026-11-23): org entity resolution (org.canonical_org_id, org_link, ingest_colstats, triggers)
def _upgrade_5(conn, log) -> None:
    from ingest import orglink
    conn.execute("BEGIN IMMEDIATE")
    try:
        before = conn.execute("SELECT count(*) FROM org").fetchone()[0]
        orglink.ensure_schema(conn)
        after = conn.execute("SELECT count(*) FROM org").fetchone()[0]
        if before != after:
            raise RuntimeError(f"upgrade 5: org {before} rows before, {after} after")
        log("upgrade 5: org.canonical_org_id, org_link, ingest_colstats and canonical-org triggers in place")
        conn.execute("PRAGMA user_version=5")
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
