"""Org entity resolution (schema 5): one canonical org per legal entity, every join recorded.

Model
  * org.canonical_org_id   NULL = this row is a canonical org; otherwise it is an alias row (a source-level
                           record of the same legal entity) and points at its canonical org. Alias rows are
                           kept as they were written (nothing is deleted), but nothing else may point at them.
  * org_link               one row per source-level org record (an org row, an org_register row, an award
                           recipient, a Wikidata item …) saying which canonical org it resolves to, by which
                           method, with what confidence, and whether it is flagged for review.
  * triggers               award / org_person / org_register / facility ids that name an alias row are
                           re-pointed to the canonical org on insert and update.

Matching order (never silent): hard ids first (court register + number, Berlin Zuwendungsdatenbank id,
Lobbyregister number, BA Jobcenter Träger-Nr, LEI, USt-IdNr, Wikidata QID). A name match is only ever a
flagged `name_fuzzy` link; it never merges canonical orgs. Merges happen in a Lead run
(ingest/domains/lead_org_resolution.py) on a shared hard id, or on an explicit reviewed row of
docs/org_merges.tsv (method `manual`), and each one is written to org_link with its reason.

Everything here except sync(), merge(), snapshot() and ensure_schema() is read-only, so scripts/verify.py
and scripts/join_gaps.py can use it on a read-only connection.
"""
from __future__ import annotations

import difflib
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ALLOWLIST = ROOT / "docs" / "null_allowlist.tsv"
MERGES = ROOT / "docs" / "org_merges.tsv"

METHODS = ("register_id", "lei", "ust_id", "wikidata_qid", "name_fuzzy", "manual", "origin")
HARD_METHODS = ("register_id", "lei", "ust_id", "wikidata_qid")
# tables that point at org(id): (table, column)
ORG_REFS = [("award", "org_id"), ("org_person", "org_id"), ("org_register", "org_id"), ("facility", "traeger_org_id")]
# not snapshotted for the NULL-regression check: derived or operational tables
NOT_SNAPSHOTTED = {"org_link", "ingest_colstats", "ingest_run"}

SCHEMA_SQL = ROOT / "ingest" / "schema.sql"
V5_TABLES = ("org_link", "ingest_colstats")


def _triggers() -> str:
    out = []
    for t, c in ORG_REFS:
        for ev, name in (("INSERT", "neu"), (f"UPDATE OF {c}", "aenderung")):
            out.append(
                f"CREATE TRIGGER IF NOT EXISTS {t}_{c}_kanonisch_{name} AFTER {ev} ON {t} "
                f"WHEN NEW.{c} IN (SELECT id FROM org WHERE canonical_org_id IS NOT NULL) BEGIN "
                f"UPDATE {t} SET {c}=(SELECT canonical_org_id FROM org WHERE id=NEW.{c}) WHERE rowid=NEW.rowid; END;")
    out.append(
        "CREATE TRIGGER IF NOT EXISTS org_kanonisch_kette BEFORE UPDATE OF canonical_org_id ON org "
        "WHEN NEW.canonical_org_id IS NOT NULL AND (NEW.canonical_org_id = NEW.id OR "
        "(SELECT canonical_org_id FROM org WHERE id=NEW.canonical_org_id) IS NOT NULL OR "
        "NOT EXISTS (SELECT 1 FROM org WHERE id=NEW.canonical_org_id)) "
        "BEGIN SELECT RAISE(ABORT, 'org.canonical_org_id must point at an existing canonical org'); END;")
    return "\n".join(out)


def has_v5(conn) -> bool:
    cols = {r[1] for r in conn.execute("PRAGMA table_info(org)")}
    tabs = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    return "canonical_org_id" in cols and {"org_link", "ingest_colstats"} <= tabs


def ensure_schema(conn) -> None:
    """Idempotent schema-5 objects (column, tables, indexes, triggers). Caller owns the transaction."""
    if "canonical_org_id" not in {r[1] for r in conn.execute("PRAGMA table_info(org)")}:
        conn.execute("ALTER TABLE org ADD COLUMN canonical_org_id INTEGER REFERENCES org(id)")
    sql = SCHEMA_SQL.read_text(encoding="utf-8")
    for t in V5_TABLES:                      # single source of truth: ingest/schema.sql
        m = re.search(rf"CREATE TABLE IF NOT EXISTS {t} \(.*?\n\);", sql, re.S)
        conn.execute(m.group(0))
        for ix in re.findall(rf"CREATE INDEX IF NOT EXISTS \w+ ON {t}\(.*?\);", sql):
            conn.execute(ix)
    for stmt in [x for x in _triggers().split("\n") if x.strip()]:
        conn.execute(stmt)
    conn.execute("CREATE INDEX IF NOT EXISTS org_nach_kanon ON org(canonical_org_id)")


# ------------------------------------------------------------------ hard ids
_FOLD = str.maketrans({"Ä": "AE", "Ö": "OE", "Ü": "UE", "ß": "SS", "ẞ": "SS", "ä": "AE", "ö": "OE", "ü": "UE"})
_BEZUW = re.compile(r"^([a-zäöü]{1,5})_(\d+)$", re.I)          # Berlin Zuwendungsdatenbank: vr_021507, kör_100050
_COURT = re.compile(r"(?i:\b(VR|HRA|HRB|GNR|PR))\s*0*(\d+)\s*([A-Z]{1,2}\b)?")
_AG = re.compile(r"(?i:\b(?:Amtsgericht|AG))\s+([A-Za-zÄÖÜäöüß][A-Za-zÄÖÜäöüß.\- ]*?)(?=\s*[),;]|\s*$|\s+(?:VR|HRA|HRB|GnR|PR)\b)")
_CITY = re.compile(r"^\s*,?\s*\(?\s*([A-ZÄÖÜ][a-zäöüß]+(?:[ -][A-ZÄÖÜ][a-zäöüß]+)?)\s*\)?\s*$")
# court-register suffix letters as printed after the number; only Berlin's is unambiguous (one register court)
_SUFFIX_COURT = {"B": "CHARLOTTENBURG"}
SCHEME_NAME = {"VR": "VR", "HRA": "HRA", "HRB": "HRB", "GNR": "GnR", "PR": "PR"}


def _fold(s) -> str:
    return re.sub(r"\s+", " ", str(s or "").upper().translate(_FOLD)).strip(" .,;()")


def court_norm(court) -> str:
    c = _fold(court)
    c = re.sub(r"^(AMTSGERICHT|AG)\s+", "", c)
    c = re.sub(r"\s*\(.*$", "", c).strip()
    return _SUFFIX_COURT.get(c, c)


def court_register_key(scheme: str, number, court="") -> str | None:
    digits = re.sub(r"\D", "", str(number or ""))
    sch = SCHEME_NAME.get(str(scheme).upper())
    if not digits or not sch:
        return None
    return f"{sch}:{int(digits)}:{court_norm(court)}"


def parse_court_register(raw) -> tuple[str, str] | None:
    """'HRB 245577 B AG Charlottenburg' -> ('HRB:245577:CHARLOTTENBURG', 'HRB:245577')."""
    t = str(raw or "").strip()
    m = _COURT.search(t)
    if not m:
        return None
    court = ""
    ag = _AG.search(t)
    if ag:
        court = ag.group(1)
    elif m.group(3):
        court = m.group(3)
    else:
        cm = _CITY.match(t[m.end():])
        if cm:
            court = cm.group(1)
    key = court_register_key(m.group(1), m.group(2), court)
    return (key, key.rsplit(":", 1)[0]) if key else None


def ust_key(v) -> str | None:
    s = re.sub(r"[\s.\-]", "", str(v or "")).upper()
    return f"UST:{s}" if re.fullmatch(r"DE\d{9}", s) else None


def lei_key(v) -> str | None:
    s = re.sub(r"\s", "", str(v or "")).upper()
    return f"LEI:{s}" if re.fullmatch(r"[A-Z0-9]{18}\d{2}", s) else None


def qid_key(v) -> str | None:
    s = str(v or "").strip().rsplit("/", 1)[-1].upper()
    return f"QID:{s}" if re.fullmatch(r"Q[1-9]\d*", s) else None


def register_keys(raw, *, ba_traeger: bool = False) -> list[tuple[str, str]]:
    """A register string as stored (org.register_id, award.empfaenger_register) -> [(method, key)]."""
    r = str(raw or "").strip()
    if not r:
        return []
    if _BEZUW.match(r):
        return [("register_id", f"BE_ZUWDB:{r.lower()}")]
    if ba_traeger and r.isdigit():
        return [("register_id", f"BA_JC:{r}")]
    cr = parse_court_register(r)
    if cr:
        return [("register_id", cr[0])]
    if re.fullmatch(r"R\d{6}", r):
        return [("register_id", f"LobbyR:{r}")]
    if ust_key(r):
        return [("ust_id", ust_key(r))]
    if lei_key(r):
        return [("lei", lei_key(r))]
    return []


def loose_register(key: str) -> str | None:
    """Register number without the court, for the 'court not stated' candidate list (never for merging)."""
    if key.startswith("BE_ZUWDB:"):
        m = _BEZUW.match(key.split(":", 1)[1])
        sch = SCHEME_NAME.get(m.group(1).upper()) if m else None
        return f"{sch}:{int(m.group(2))}" if sch else None
    parts = key.split(":")
    if parts[0] in SCHEME_NAME.values() and len(parts) == 3:
        return f"{parts[0]}:{parts[1]}"
    return None


def org_register_key(scheme, court, number) -> tuple[str, str] | None:
    """org_register row -> (method, key) or None for scheme 'other'."""
    s, n = str(scheme or ""), str(number or "").strip()
    if s == "BE_ZUWDB":
        return ("register_id", f"BE_ZUWDB:{n.lower()}")
    if s in ("VR", "HRA", "HRB", "GnR", "PR"):
        k = court_register_key(s, n, court)
        return ("register_id", k) if k else None
    if s == "LobbyR":
        return ("register_id", f"LobbyR:{n}")
    if s == "USt-IdNr":
        k = ust_key(n)
        return ("ust_id", k) if k else None
    if s == "LEI":
        k = lei_key(n)
        return ("lei", k) if k else None
    if s in ("EU_TR", "StiftReg"):
        return ("register_id", f"{s}:{court_norm(court)}:{n}")
    return None


def method_for_key(key: str) -> str:
    return {"UST": "ust_id", "LEI": "lei", "QID": "wikidata_qid"}.get(key.split(":", 1)[0], "register_id")


# ------------------------------------------------------------------ loading (read-only)
def _tables(conn) -> set[str]:
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _host(url: str | None) -> str:
    """Publisher host of a source URL. Lead 2026-11-23: a same-domain origin link also needs the same host, so one
    module's two datasets (e.g. funding_mv: LAGuS zuwendung-mv.de vs Transparenzdatenbank transparenz-mv.de) never
    turn a name match into an origin link."""
    from urllib.parse import urlsplit
    return urlsplit(url or "").netloc.lower()


def source_system(url: str | None, domain: str | None) -> str:
    u = (url or "").lower()
    if "lobbyregister.bundestag.de" in u:
        return "lobbyregister"
    if "zuwendungsdatenbank" in u:
        return "berlin_zuwendungen"
    if "ted.europa.eu" in u:
        return "ted"
    if "statistik.arbeitsagentur.de" in u:
        return "ba_jobcenter"
    if "wikidata.org" in u:
        return "wikidata"
    return f"domain:{domain or 'unknown'}"


class Graph:
    """Snapshot of orgs, their hard ids and the canonical mapping (read-only)."""

    def __init__(self, conn):
        self.conn = conn
        tabs = _tables(conn)
        self.v5 = has_v5(conn)
        canon_col = "canonical_org_id" if self.v5 else "NULL"
        self.orgs = {}
        for r in conn.execute(
                f"SELECT o.id, o.name, o.name_norm, o.legal_form, o.land, o.ort, o.register_id, o.ust_id, o.lei, "
                f"o.source_id, {canon_col}, s.url, s.domain FROM org o LEFT JOIN source s ON s.id=o.source_id"):
            self.orgs[r[0]] = dict(id=r[0], name=r[1], name_norm=r[2] or "", legal_form=r[3], land=r[4], ort=r[5],
                                   register_id=r[6], ust_id=r[7], lei=r[8], source_id=r[9], canonical_org_id=r[10],
                                   source_url=r[11], domain=r[12])
        ba = set()
        if "institutions_media_org" in tabs:
            cols = {x[1] for x in conn.execute("PRAGMA table_info(institutions_media_org)")}
            if {"org_id", "traeger_nr"} <= cols:
                ba = {(a, str(b)) for a, b in conn.execute(
                    "SELECT org_id, traeger_nr FROM institutions_media_org WHERE traeger_nr IS NOT NULL")}
        # keys per org row: [(method, key, origin)]
        self.keys = defaultdict(list)
        for o in self.orgs.values():
            for m, k in register_keys(o["register_id"], ba_traeger=(o["id"], str(o["register_id"])) in ba):
                self.keys[o["id"]].append((m, k, "org.register_id"))
            if ust_key(o["ust_id"]):
                self.keys[o["id"]].append(("ust_id", ust_key(o["ust_id"]), "org.ust_id"))
            if lei_key(o["lei"]):
                self.keys[o["id"]].append(("lei", lei_key(o["lei"]), "org.lei"))
        self.registers = []
        if "org_register" in tabs:
            for rid, oid, sch, court, num, sid in conn.execute(
                    "SELECT id, org_id, scheme, court, number, source_id FROM org_register"):
                mk = org_register_key(sch, court, num)
                self.registers.append(dict(id=rid, org_id=oid, scheme=sch, court=court, number=num, source_id=sid,
                                           key=mk[1] if mk else None, method=mk[0] if mk else None))
                if mk and oid in self.orgs:
                    self.keys[oid].append((mk[0], mk[1], f"org_register #{rid}"))
        if self.v5:
            for oid, m, k, kind, key in conn.execute(
                    "SELECT org_id, method, id_value, record_kind, record_key FROM org_link "
                    "WHERE method IN ('register_id','lei','ust_id','wikidata_qid') AND id_value IS NOT NULL "
                    "AND record_kind NOT IN ('org','org_register','award')"):
                if oid in self.orgs:
                    self.keys[oid].append((m, k, f"org_link {kind}:{key}"))

    def canon(self, oid):
        """Canonical id for an org id (one hop; chains are a G11 failure), None if the id is missing."""
        o = self.orgs.get(oid)
        if o is None:
            return None
        c = o["canonical_org_id"]
        return oid if c is None else c

    def is_canonical(self, oid) -> bool:
        o = self.orgs.get(oid)
        return o is not None and o["canonical_org_id"] is None

    def canonical_ids(self) -> list[int]:
        return sorted(i for i, o in self.orgs.items() if o["canonical_org_id"] is None)

    def members(self) -> dict[int, list[int]]:
        if getattr(self, "_members", None) is None:
            g = defaultdict(list)
            for i in self.orgs:
                c = self.canon(i)
                if c is not None:
                    g[c].append(i)
            self._members = g
        return self._members

    def hard_index(self) -> dict[str, set[int]]:
        idx = defaultdict(set)
        for oid, ks in self.keys.items():
            c = self.canon(oid)
            for _m, k, _o in ks:
                idx[k].add(c)
        return idx

    def group_keys(self, cid) -> set[str]:
        return {k for oid in self.members().get(cid, [cid]) for _m, k, _o in self.keys.get(oid, [])}


def award_keys(empfaenger_register, empfaenger_id) -> list[tuple[str, str]]:
    out = register_keys(empfaenger_register)
    if empfaenger_id and str(empfaenger_id).strip() != str(empfaenger_register or "").strip():
        out += [x for x in register_keys(empfaenger_id) if x not in out]
    return out


# ------------------------------------------------------------------ legal form & similarity
_KINDS = [("gGmbH", r"\bG\.?\s?GMBH\b|GEMEINNUETZIGE GESELLSCHAFT MIT BESCHRAENKTER HAFTUNG|GEMEINNUETZIGE GMBH"),
          ("GmbH & Co. KG", r"GMBH\s*(?:&|UND|&AMP;)\s*CO"),
          ("GmbH", r"\bGMBH\b|GESELLSCHAFT MIT BESCHRAENKTER HAFTUNG|\bMBH\b"),
          ("UG", r"\bG?UG\b|HAFTUNGSBESCHRAENKT"), ("AG", r"\bG?AG\b|AKTIENGESELLSCHAFT"),
          ("e.V.", r"\bE\.\s?V\b|\bE\s+V\b|\bEV$|EINGETRAGENER VEREIN"), ("eG", r"\bE\.?\s?G\b\.?|GENOSSENSCHAFT"),
          ("KdöR", r"K\.?\s?D\.?\s?OE\.?\s?R|KOERPERSCHAFT DES OEFFENTLICHEN RECHTS|KIRCHENGEMEINDE|PFARREI"),
          ("AöR", r"A\.?\s?OE\.?\s?R|ANSTALT DES OEFFENTLICHEN RECHTS"), ("Stiftung", r"\bSTIFTUNG\b")]


LEGAL_FORM_NORMS = ("ev", "ggmbh", "gmbh", "ag", "stiftung", "koer", "kdoer", "eg", "gbr", "other")
_KIND_NORM = {"e.V.": "ev", "gGmbH": "ggmbh", "GmbH": "gmbh", "AG": "ag", "Stiftung": "stiftung", "KdöR": "kdoer",
              "eG": "eg"}
# one legal entity may be printed with either spelling of the family: GEBEWO pro "GmbH" is the gGmbH, KöR = KdöR
FORM_FAMILY = {"ggmbh": "gmbh", "gmbh": "gmbh", "koer": "kdoer", "kdoer": "kdoer"}
_GBR = r"\bGBR\b|GESELLSCHAFT BUERGERLICHEN RECHTS"
_KOER = r"\bK\.?\s?OE\.?\s?R\b|KOERPERSCHAFT OEFFENTLICHEN RECHTS"
_OTHER_FORM = (r"\bKGAA\b|\bKG\b|\bOHG\b|\bINC\b|\bLLC\b|\bLTD\b|\bSE\b|\bPARTG|\bE\.?\s?K\b\.?$|"
               r"GENOSSENSCHAFT|EINGETRAGENER KAUFMANN")


def legal_form_norm(name, legal_form=None) -> str | None:
    """Schema 6 org key part (INGEST_CONTRACT §12): ev | ggmbh | gmbh | ag | stiftung | koer | kdoer | eg | gbr |
    other, or None when neither the printed legal form nor the name shows one. Built on legal_kind()."""
    t = _fold(legal_form) + " " + _fold(name)
    if re.search(_GBR, t):
        return "gbr"
    k = legal_kind(name, legal_form)
    if k is None and re.search(_KOER, t):
        return "koer"
    if k in _KIND_NORM:
        return _KIND_NORM[k]
    if k is not None or re.search(_OTHER_FORM, t):
        return "other"
    return None


def same_form_family(a, b) -> bool:
    return a is not None and b is not None and FORM_FAMILY.get(a, a) == FORM_FAMILY.get(b, b)


def legal_kind(name, legal_form=None) -> str | None:
    t = _fold(legal_form) + " " + _fold(name)
    for kind, rx in _KINDS:
        if re.search(rx, t):
            return kind
    return None


def similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a or "", b or "").ratio()


# ------------------------------------------------------------------ writing
def canonical(conn, org_id):
    if org_id is None:
        return None
    if "canonical_org_id" not in {r[1] for r in conn.execute("PRAGMA table_info(org)")}:
        return org_id
    r = conn.execute("SELECT coalesce(canonical_org_id, id) FROM org WHERE id=?", (org_id,)).fetchone()
    return r[0] if r else None


def resolve(conn, *, register=None, ust_id=None, lei=None, qid=None, ba_traeger=None) -> int | None:
    """Canonical org id for a hard id, or None. Raises if the hard id is ambiguous (G11 would fail)."""
    want = set()
    for m, k in register_keys(register):
        want.add(k)
    if ba_traeger:
        want.add(f"BA_JC:{str(ba_traeger).strip()}")
    for k in (ust_key(ust_id), lei_key(lei), qid_key(qid)):
        if k:
            want.add(k)
    if not want:
        return None
    idx = Graph(conn).hard_index()
    hits = set().union(*(idx.get(k, set()) for k in want))
    if len(hits) > 1:
        raise ValueError(f"resolve_org: hard ids {sorted(want)} name {len(hits)} canonical orgs {sorted(hits)}")
    return next(iter(hits), None)


def link(conn, *, record_kind, record_key, org_id, method, confidence, source_id, record_name=None,
         id_value=None, source_system_=None, note=None, run_id=None, keep_method=False) -> int:
    """Insert or update one org_link row. org_id is canonicalised; name matches are always flagged."""
    if method not in METHODS:
        raise ValueError(f"org_link method {method!r} not in {METHODS}")
    if method in HARD_METHODS and not id_value:
        raise ValueError(f"org_link method {method} needs the normalised id_value it rests on")
    if not 0 <= float(confidence) <= 1:
        raise ValueError("org_link confidence must be between 0 and 1")
    cid = canonical(conn, org_id)
    if cid is None:
        raise ValueError(f"org_link: org {org_id} does not exist")
    flagged = 1 if method == "name_fuzzy" else 0
    # Lead 2026-11-23: a reviewed, non-fuzzy link (docs/link_reviews.tsv) is not downgraded by a later name match
    # to the same canonical org, and keep_method only holds while the org is unchanged; a match to a different org
    # is written as given (flagged again if it is a name match).
    prev = conn.execute("SELECT org_id, method, reviewed FROM org_link WHERE record_kind=? AND record_key=?",
                        (record_kind, str(record_key))).fetchone()
    if prev and canonical(conn, prev[0]) == cid:
        if prev[2] == 1 and prev[1] != "name_fuzzy" and method == "name_fuzzy":
            keep_method = True
    elif prev:
        keep_method = False
    upd = ("org_id=excluded.org_id, record_name=coalesce(excluded.record_name, org_link.record_name), "
           "source_system=coalesce(excluded.source_system, org_link.source_system)")
    if not keep_method:
        upd += (", id_value=excluded.id_value, method=excluded.method, confidence=excluded.confidence, "
                "flagged=excluded.flagged, note=coalesce(excluded.note, org_link.note), source_id=excluded.source_id, "
                "reviewed=CASE WHEN org_link.method=excluded.method AND org_link.org_id=excluded.org_id "
                "THEN org_link.reviewed ELSE 0 END, run_id=excluded.run_id")
    return conn.execute(
        "INSERT INTO org_link(org_id, record_kind, record_key, record_name, source_system, id_value, method, confidence, "
        "flagged, note, source_id, run_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?) "
        f"ON CONFLICT(record_kind, record_key) DO UPDATE SET {upd} RETURNING id",
        (cid, record_kind, str(record_key), record_name, source_system_, id_value, method, round(float(confidence), 3),
         flagged, note, source_id, run_id)).fetchone()[0]


def backfill_legal_form(conn) -> dict:
    """Fill org.legal_form_norm where it is NULL but the name or printed legal form shows one (schema 6). A row
    whose filled key would collide with another row is left NULL and counted (join_gaps reviews it)."""
    import sqlite3
    out = {"legal_form_filled": 0, "legal_form_collision": 0}
    for oid, name, lf in conn.execute("SELECT id, name, legal_form FROM org WHERE legal_form_norm IS NULL").fetchall():
        v = legal_form_norm(name, lf)
        if v is None:
            continue
        try:
            conn.execute("UPDATE org SET legal_form_norm=? WHERE id=?", (v, oid))
            out["legal_form_filled"] += 1
        except sqlite3.IntegrityError:
            out["legal_form_collision"] += 1
    return {k: v for k, v in out.items() if v}


def sync(conn, run_id=None) -> dict:
    """Deterministic links for every org row, org_register row and award, from stored data only."""
    ensure_schema(conn)
    stats = defaultdict(int)
    if "legal_form_norm" in {r[1] for r in conn.execute("PRAGMA table_info(org)")}:
        stats.update(backfill_legal_form(conn))
    g = Graph(conn)
    members = g.members()
    seen = defaultdict(set)
    existing = {(k, key): (oid, m) for k, key, oid, m in conn.execute(
        "SELECT record_kind, record_key, org_id, method FROM org_link")}
    # org rows
    for o in g.orgs.values():
        key = str(o["id"])
        seen["org"].add(key)
        sysname = source_system(o["source_url"], o["domain"])
        # Lead 2026-11-23: the origin link carries only a hard id held by the org row itself (register_id, ust_id,
        # lei, org_register). A key that exists only as an explicit org_link (e.g. BA_JC:<nr> from institutions_media)
        # already has its own link row; copying it onto the origin link duplicated all 404 BA_JC values.
        hard = sorted(k for _m, k, src in g.keys.get(o["id"], []) if not src.startswith("org_link "))
        if o["canonical_org_id"] is None:
            link(conn, record_kind="org", record_key=key, org_id=o["id"], method="origin", confidence=1.0,
                 source_id=o["source_id"], record_name=o["name"], id_value=hard[0] if hard else None,
                 source_system_=sysname, run_id=run_id)
            stats["origin"] += 1
        else:
            prev = existing.get(("org", key))
            if prev and prev[1] in ("register_id", "lei", "ust_id", "wikidata_qid", "manual"):
                conn.execute("UPDATE org_link SET org_id=? WHERE record_kind='org' AND record_key=?",
                             (o["canonical_org_id"], key))
            else:
                link(conn, record_kind="org", record_key=key, org_id=o["canonical_org_id"], method="manual",
                     confidence=1.0, source_id=o["source_id"], record_name=o["name"], source_system_=sysname,
                     note="canonical_org_id was set without a link record", run_id=run_id)
            stats["alias"] += 1
    # org_register rows
    for r in g.registers:
        key = f"{r['scheme']}|{r['court']}|{r['number']}"
        seen["org_register"].add(key)
        if r["key"] is None or g.canon(r["org_id"]) is None:
            continue
        link(conn, record_kind="org_register", record_key=key, org_id=r["org_id"], method=r["method"], confidence=1.0,
             source_id=r["source_id"], id_value=r["key"], source_system_=f"org_register:{r['scheme']}", run_id=run_id)
        stats["org_register"] += 1
    # award recipients
    for fk, aid, oid, emp, emp_norm, reg, eid, sid, adom, aland, aurl in conn.execute(
            "SELECT a.foerder_schluessel, a.id, a.org_id, a.empfaenger, a.empfaenger_norm, a.empfaenger_register, "
            "a.empfaenger_id, a.source_id, s.domain, a.ort_land, s.url FROM award a LEFT JOIN source s ON s.id = a.source_id "
            "WHERE a.org_id IS NOT NULL").fetchall():
        key = fk or f"id:{aid}"
        seen["award"].add(key)
        cid = g.canon(oid)
        if cid is None:
            continue
        gk = g.group_keys(cid)
        hit = next(((m, k) for m, k in award_keys(reg, eid) if k in gk), None)
        rows = [g.orgs[i] for i in members.get(cid, [cid])]
        if hit:
            method, conf, idv, note = hit[0], 1.0, hit[1], None
        elif any(r["source_id"] == sid and r["name_norm"] == (emp_norm or "") for r in rows):
            method, conf, idv, note = "origin", 1.0, None, "org row was created from this record"
        elif adom and any(r["domain"] == adom and source_system(r["source_url"], r["domain"]) == source_system(aurl, adom)
                          and _host(r["source_url"]) == _host(aurl)   # Lead: same publisher host = same dataset
                          and r["name_norm"] == (emp_norm or "") and r["land"] == aland
                          and legal_form_norm(emp) == legal_form_norm(r["name"], r["legal_form"]) for r in rows):
            # funding worker 2026-11-23: the org row was created by the same domain from another file of the same
            # dataset (another quarterly report / list page) under the exact org key (name_norm + legal form + Land):
            # the reader's own key, not a name guess
            method, conf, idv, note = "origin", 1.0, None, "org row created by this domain from another file of the " \
                                                           "same dataset (same name, legal form and Land)"
        else:
            best = max((similarity(emp_norm or "", r["name_norm"]) for r in rows), default=0.0)
            method, idv = "name_fuzzy", None
            conf = 0.95 if best == 1.0 else round(best * 0.9, 3)
            note = "same normalised name" if best == 1.0 else f"name similarity {best:.2f}"
            ka, kb = legal_kind(emp), legal_kind(g.orgs[cid]["name"], g.orgs[cid]["legal_form"])
            if ka and kb and ka != kb and {ka, kb} != {"GmbH", "gGmbH"}:
                conf = min(conf, 0.5)
                note += f"; legal form differs ({ka} in the record, {kb} on the org): likely a different entity"
            stats["award_name_fuzzy"] += 1
        prev = existing.get(("award", key))
        link(conn, record_kind="award", record_key=key, org_id=cid, method=method, confidence=conf, source_id=sid,
             record_name=emp, id_value=idv, source_system_="ted" if key.startswith("TED:") else
             ("berlin_zuwendungen" if key.startswith("DE-BE-ZUW:") else None), note=note, run_id=run_id,
             keep_method=bool(prev and prev[1] == "manual"))
        stats["award"] += 1
    # stale links (their record is gone)
    for kind in ("org", "org_register", "award"):
        for (k, key) in [x for x in existing if x[0] == kind and x[1] not in seen[kind]]:
            conn.execute("DELETE FROM org_link WHERE record_kind=? AND record_key=?", (k, key))
            stats["stale_removed"] += 1
    stats["flagged"] = conn.execute("SELECT count(*) FROM org_link WHERE flagged=1").fetchone()[0]
    return dict(stats)


def merge(conn, alias_id: int, canonical_id: int, *, method: str, confidence: float, reason: str,
          id_value=None, run_id=None) -> dict:
    """Make alias_id (and anything already merged into it) an alias of canonical_id; re-point references."""
    if method not in ("register_id", "lei", "ust_id", "wikidata_qid", "manual"):
        raise ValueError(f"merge: method {method!r} cannot merge orgs (name matches never merge)")
    if not reason:
        raise ValueError("merge: a reason is required")
    ensure_schema(conn)
    cid = canonical(conn, canonical_id)
    aid = canonical(conn, alias_id)
    if cid is None or aid is None:
        raise ValueError(f"merge: org {alias_id} or {canonical_id} does not exist")
    if cid == aid:
        return {"noop": 1}
    moved = {}
    # orgs already merged into the alias follow it (no chains); then the alias itself
    moved["aliases_followed"] = conn.execute("UPDATE org SET canonical_org_id=? WHERE canonical_org_id=?",
                                             (cid, aid)).rowcount
    conn.execute("UPDATE org SET canonical_org_id=? WHERE id=?", (cid, aid))
    for t, c in ORG_REFS:
        moved[t] = conn.execute(f"UPDATE {t} SET {c}=? WHERE {c}=?", (cid, aid)).rowcount
    moved["metric"] = conn.execute("UPDATE metric SET entity_id=? WHERE entity_type='org' AND entity_id=?",
                                   (str(cid), str(aid))).rowcount
    conn.execute("UPDATE org_link SET org_id=? WHERE org_id=?", (cid, aid))
    sid, name = conn.execute("SELECT source_id, name FROM org WHERE id=?", (aid,)).fetchone()
    link(conn, record_kind="org", record_key=str(aid), org_id=cid, method=method, confidence=confidence,
         source_id=sid, record_name=name, id_value=id_value, note=reason, run_id=run_id)
    conn.execute("UPDATE org_link SET reviewed=1 WHERE record_kind='org' AND record_key=?", (str(aid),))
    return moved


def plan_hard_merges(conn) -> list[dict]:
    """Canonical orgs that share a hard id -> [{alias, canonical, method, key}], deterministic."""
    g = Graph(conn)
    idx = g.hard_index()
    parent = {}

    def find(x):
        while parent.get(x, x) != x:
            x = parent[x]
        return x
    shared = defaultdict(set)
    for k, cs in idx.items():
        cs = sorted(c for c in cs if c is not None)
        for c in cs[1:]:
            parent[find(c)] = find(cs[0])
        if len(cs) > 1:
            for c in cs:
                shared[c].add(k)
    comps = defaultdict(set)
    for k, cs in idx.items():
        if len(cs) > 1:
            for c in cs:
                comps[find(c)].add(c)
    refs = defaultdict(int)
    for t, col in ORG_REFS:
        for oid, n in conn.execute(f"SELECT {col}, count(*) FROM {t} WHERE {col} IS NOT NULL GROUP BY 1"):
            refs[oid] += n
    reg_owner = defaultdict(set)
    for r in g.registers:
        if r["key"]:
            reg_owner[r["key"]].add(g.canon(r["org_id"]))
    plan = []
    for _root, cs in sorted(comps.items()):
        keys = set().union(*(shared[c] for c in cs))
        owners = {c for c in cs if any(c in reg_owner.get(k, ()) for k in keys)}
        pool = owners if owners else cs
        canon_id = sorted(pool, key=lambda c: (-refs[c], c))[0]
        for c in sorted(cs - {canon_id}):
            k = sorted(shared[c] & g.group_keys(canon_id)) or sorted(shared[c])
            plan.append(dict(alias=c, canonical=canon_id, method=method_for_key(k[0]), key=k[0],
                             alias_name=g.orgs[c]["name"], canonical_name=g.orgs[canon_id]["name"]))
    return plan


def award_conflicts(conn, g: Graph | None = None) -> list[dict]:
    """Awards whose recipient hard id belongs to a different canonical org than the one they point at.

    method 'register_id' (court register, Berlin ZUWDB id, Lobbyregister): a real mis-link, G11b fails and the
    Lead re-points it. method 'ust_id': reported only, because one USt-IdNr can cover several legal entities
    (umsatzsteuerliche Organschaft) and notices print the group number for subsidiaries."""
    g = g or Graph(conn)
    idx = g.hard_index()
    out = []
    for fk, aid, oid, emp, reg, eid in conn.execute(
            "SELECT foerder_schluessel, id, org_id, empfaenger, empfaenger_register, empfaenger_id FROM award "
            "WHERE org_id IS NOT NULL AND (empfaenger_register IS NOT NULL OR empfaenger_id IS NOT NULL)"):
        cid = g.canon(oid)
        for m, k in award_keys(reg, eid):
            owners = idx.get(k, set())
            if owners and cid not in owners and len(owners) == 1:
                out.append(dict(award_id=aid, key=fk, org_id=oid, owner=next(iter(owners)), empfaenger=emp,
                                register=k, method=m))
                break
    return out


def read_merges(path: Path = MERGES) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        p = line.split("\t")
        if p[0] == "alias_id":
            continue
        rows.append(dict(alias=int(p[0]), alias_norm=p[1], canonical=int(p[2]), canonical_norm=p[3], reason=p[4]))
    return rows


# ------------------------------------------------------------------ NULL-regression snapshots
LINK_REVIEWS = ROOT / "docs" / "link_reviews.tsv"
REVIEW_METHODS = {"manual": 0.95, "origin": 1.0}


def read_link_reviews(path: Path = LINK_REVIEWS) -> list[dict]:
    """Lead decisions on flagged org_link rows: record_kind, record_key, org_id, org_name_norm, verdict, method, evidence."""
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        p = line.split("\t")
        if p[0] == "record_kind":
            continue
        if len(p) != 7 or p[4] not in ("confirm", "reject", "unsure"):
            raise ValueError(f"link_reviews.tsv: bad line {line[:80]!r}")
        rows.append(dict(kind=p[0], key=p[1], org_id=int(p[2]), org_norm=p[3], verdict=p[4], method=p[5], evidence=p[6]))
    return rows


def apply_link_reviews(conn, reviews: list[dict] | None = None, run_id=None) -> dict:
    """confirm: method manual|origin, flagged 0, reviewed 1, evidence in the note. reject: the link is removed and, for
    an award, award.org_id is cleared so the row stays unlinked. unsure: untouched (stays flagged). A line whose link
    is gone, or now names another org, or whose org name_norm differs, is skipped."""
    reviews = read_link_reviews() if reviews is None else reviews
    out = defaultdict(list)
    for r in reviews:
        tag = f"{r['kind']}:{r['key']}"
        if r["verdict"] == "unsure":
            out["unsure"].append(tag)
            continue
        row = conn.execute("SELECT id, org_id FROM org_link WHERE record_kind=? AND record_key=?", (r["kind"], r["key"])).fetchone()
        nn = conn.execute("SELECT name_norm FROM org WHERE id=?", (r["org_id"],)).fetchone()
        if not row or not nn or nn[0] != r["org_norm"] or canonical(conn, row[1]) != canonical(conn, r["org_id"]):
            out["skipped"].append(tag)
            continue
        if r["verdict"] == "confirm":
            if r["method"] not in REVIEW_METHODS:
                raise ValueError(f"link_reviews.tsv: confirm needs method manual|origin, got {r['method']!r}")
            conn.execute("UPDATE org_link SET method=?, confidence=?, flagged=0, reviewed=1, note=?, run_id=coalesce(?, run_id) "
                         "WHERE id=?", (r["method"], REVIEW_METHODS[r["method"]],
                                        f"Lead review (docs/link_reviews.tsv): {r['evidence']}", run_id, row[0]))
            out["confirmed"].append(tag)
        else:
            if r["kind"] == "award":
                conn.execute("UPDATE award SET org_id=NULL WHERE foerder_schluessel=?", (r["key"],))
            conn.execute("DELETE FROM org_link WHERE id=?", (row[0],))
            out["rejected"].append(tag)
    res = {k: len(v) for k, v in out.items()}
    res["skipped_keys"] = out["skipped"]
    return res


def snapshot_tables(conn) -> list[str]:
    return sorted(t for t in _tables(conn) if not t.startswith(("sqlite_", "search_fts", "selftest"))
                  and t not in NOT_SNAPSHOTTED)


def column_counts(conn) -> dict[tuple[str, str], int]:
    out = {}
    for t in snapshot_tables(conn):
        cols = [r[1] for r in conn.execute(f"PRAGMA table_info({t})")]
        if not cols:
            continue
        row = conn.execute(f"SELECT count(*), " + ", ".join(f'count("{c}")' for c in cols) + f" FROM {t}").fetchone()
        out[(t, "*")] = row[0]
        for c, n in zip(cols, row[1:]):
            out[(t, c)] = n
    return out


def snapshot(conn, run_id: int, phase: str) -> int:
    ensure_schema(conn)
    counts = column_counts(conn)
    conn.executemany("INSERT OR REPLACE INTO ingest_colstats(run_id, phase, tbl, col, nonnull) VALUES (?,?,?,?,?)",
                     [(run_id, phase, t, c, n) for (t, c), n in counts.items()])
    return len(counts)


def read_allowlist(path: Path = ALLOWLIST) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        p = line.split("\t")
        if p[0] == "run":
            continue
        if len(p) < 6 or not p[5].strip():
            raise ValueError(f"{path.name}: every entry needs run, domain, table, column, max_drop and a reason: {line!r}")
        out.append(dict(run=p[0], domain=p[1], table=p[2], column=p[3], max_drop=int(p[4]), reason=p[5].strip()))
    return out


def null_regressions(conn, allow: list[dict] | None = None) -> tuple[list[str], dict]:
    """Columns whose non-NULL count fell during a run, minus reviewed allowlist entries."""
    allow = read_allowlist() if allow is None else allow
    if "ingest_colstats" not in _tables(conn):
        return ["no ingest_colstats table: schema < 5, NULL regressions cannot be checked"], {}
    dom = {r[0]: r[1] for r in conn.execute("SELECT id, domain FROM ingest_run")}
    snaps = defaultdict(lambda: defaultdict(dict))
    for run_id, phase, t, c, n in conn.execute("SELECT run_id, phase, tbl, col, nonnull FROM ingest_colstats"):
        snaps[run_id][phase][(t, c)] = n
    probs, info = [], {"runs_checked": 0, "allowed": 0}
    for run_id in sorted(snaps):
        b, a = snaps[run_id].get("before"), snaps[run_id].get("after")
        if not b or not a:
            continue
        info["runs_checked"] += 1
        for (t, c), nb in sorted(b.items()):
            na = a.get((t, c), 0)
            if nb > 0 and na < nb:
                drop = nb - na
                ok = any((e["run"] in ("*", str(run_id))) and e["domain"] in ("*", dom.get(run_id))
                         and e["table"] == t and e["column"] in ("*", c) and drop <= e["max_drop"] for e in allow)
                if ok:
                    info["allowed"] += 1
                    continue
                what = "rows" if c == "*" else f"non-NULL {t}.{c}"
                probs.append(f"NULL regression in run #{run_id} ({dom.get(run_id)}): {what} {nb} -> {na} "
                             f"(-{drop}); add a reviewed line to docs/null_allowlist.tsv only if intended")
    latest = max((r for r in snaps if snaps[r].get("before")), default=None)
    if latest is not None:
        b = snaps[latest]["before"]
        info["baseline_run"] = latest
        info["baseline_columns"] = sum(1 for (t, c) in b if c != "*")
        info["baseline_filled"] = sum(1 for (t, c), n in b.items() if c != "*" and n > 0)
        info["baseline_tables"] = len({t for t, _ in b})
    return probs, info


# ------------------------------------------------------------------ the gate (read-only)
def gate(conn) -> tuple[list[str], dict]:
    """G11 problems and a summary. (a) hard-id uniqueness, (b) references to canonical orgs, (c) NULL regression."""
    probs = []
    if not has_v5(conn):
        return ["schema < 5: org.canonical_org_id / org_link / ingest_colstats missing"], {}
    g = Graph(conn)
    info = {"orgs": len(g.orgs), "canonical": len(g.canonical_ids()), "aliases": len(g.orgs) - len(g.canonical_ids())}
    # (a)
    dup = 0
    for k, cs in sorted(g.hard_index().items()):
        if len(cs) > 1:
            dup += 1
            probs.append(f"(a) hard id {k} maps to {len(cs)} canonical orgs: "
                         + ", ".join(f"#{c} {g.orgs[c]['name']!r}" if c in g.orgs else f"#{c} (missing)" for c in sorted(cs, key=str)))
    for o in g.orgs.values():
        c = o["canonical_org_id"]
        if c is not None and (c not in g.orgs or g.orgs[c]["canonical_org_id"] is not None or c == o["id"]):
            probs.append(f"(a) org #{o['id']} {o['name']!r}: canonical_org_id {c} is missing, itself an alias, or a self-reference")
    info["hard_id_duplicates"] = dup
    # (b)
    orph = 0
    tabs = _tables(conn)
    for t, col in ORG_REFS + [("org_link", "org_id")]:
        if t not in tabs:
            continue
        for rid, oid in conn.execute(f"SELECT rowid, {col} FROM {t} WHERE {col} IS NOT NULL"):
            if oid not in g.orgs:
                orph += 1
                probs.append(f"(b) {t} row {rid}: {col}={oid} names no org")
            elif not g.is_canonical(oid):
                orph += 1
                probs.append(f"(b) {t} row {rid}: {col}={oid} names alias org {g.orgs[oid]['name']!r} "
                             f"(canonical #{g.orgs[oid]['canonical_org_id']})")
    for x in [x for x in award_conflicts(conn, g) if x["method"] == "register_id"]:
        orph += 1
        probs.append(f"(b) award {x['key']}: recipient id {x['register']!r} belongs to org #{x['owner']} "
                     f"{g.orgs[x['owner']]['name']!r}, but the award points to #{x['org_id']} {g.orgs.get(x['org_id'], {}).get('name')!r}")
    bad_flag = conn.execute("SELECT count(*) FROM org_link WHERE (method='name_fuzzy') <> (flagged=1)").fetchone()[0]
    if bad_flag:
        probs.append(f"(b) {bad_flag} org_link row(s) where flagged does not match method name_fuzzy")
    missing_src = conn.execute("SELECT count(*) FROM org_link WHERE source_id NOT IN (SELECT id FROM source)").fetchone()[0]
    if missing_src:
        probs.append(f"(b) {missing_src} org_link row(s) cite a missing source")
    info["orphans"] = orph
    info["flagged_links"] = conn.execute("SELECT count(*) FROM org_link WHERE flagged=1 AND reviewed=0").fetchone()[0]
    info["links"] = conn.execute("SELECT count(*) FROM org_link").fetchone()[0]
    # (c)
    nr, ninfo = null_regressions(conn)
    probs += [f"(c) {p}" for p in nr]
    info.update(ninfo)
    info["null_regressions"] = len(nr)
    return probs, info
