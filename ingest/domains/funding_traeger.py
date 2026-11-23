"""funding_traeger -- Träger/providers and the public money that pays them (Germany).

One domain file, one small reader per publisher (selected with cfg["sources"]):

  berlin_zuwendungen  Berlin Zuwendungsdatenbank (Senatsverwaltung für Finanzen): every grant
                      ("Zuwendung") of the last five calendar years whose purpose text names
                      homelessness work. One bulk JSON request; each row cites its own detail page.
  ted                 TED (EU Publications Office) API v3: German contract-award and competition
                      notices for homelessness services (see the TED section below).

Rules this module keeps (docs/INGEST_CONTRACT.md, GOALS/GOAL.md):
  * EUR amounts with currency set from the source; nothing estimated (is_est=0).
  * Every inserted row carries the source_id of the document that contains its numbers.
  * Organisations only: grants/awards to natural persons and GbRs are skipped; no contact persons,
    e-mails or phone numbers are stored.
  * Protected shelters (Frauenhaus etc.): the organisation and the money are kept, but no address,
    city or place of performance is written for that row or the recipient created from it.
  * Idempotent upserts on natural keys; rows never deleted.

Worker entry points (never touch data/atlas.db):
  python3 -m ingest.domains.funding_traeger --test      offline unit tests (in-memory SQLite)
  python3 -m ingest.domains.funding_traeger --dryrun    live fetch, in-memory SQLite, cache in /tmp
  python3 -m ingest.domains.funding_traeger --selftest --db /tmp/x.db   live sample into a scratch DB
The real DB is written only by the runner: python3 -m ingest.run funding_traeger. Unknown flags exit 2.
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from ingest import common

DOMAIN = "funding_traeger"

# --------------------------------------------------------------------------------------------- #
# shared vocabulary
# --------------------------------------------------------------------------------------------- #
PROTECTED_RE = re.compile(
    r"frauenh[äa]e?us|frauenschutz|schutzwohnung|zufluchtswohnung|zufluchtsst[äa]tte|gewaltschutz|"
    r"h[äa]e?usliche[rn]? gewalt|schutzunterkunft|anonyme[rn]? unterkunft", re.I)
REFUGEE_RE = re.compile(
    r"gefl[üu]e?chtete\w*|fl[üu]e?chtling\w*|asyl\w*|erstaufnahme\w*|ankunftszentr\w*|schutzsuchende\w*|"
    r"aufnahmeeinrichtung\w*|spät?aussiedler\w*|zuwander\w*|ukrain\w*|fluchthintergrund|fluchterfahrung", re.I)
_PERSON_HINT = re.compile(r"natürliche person|natuerliche person|\be\.\s?k(fm|fr)?\.?(?=\s|$)", re.I)


def is_protected(text: str | None) -> bool:
    return bool(PROTECTED_RE.search(text or ""))


# Lead: a protected-shelter row must not name the street either (titles like "Unterkunft Höntroper Str. 99a",
# "GU David-Gilly-Straße 5", "Notunterkunft Wilschenbrucher Weg"). Street + optional house number -> placeholder.
STREET_RE = re.compile(
    r"(?:\b[A-ZÄÖÜ][\wäöüß-]*\s+)?[\wäöüß-]*(?:[Ss]tra(?:ß|ss)e|[Ss]tr\.|[Ww]eg|[Pp]latz|[Aa]llee|[Gg]asse|[Rr]ing|"
    r"[Dd]amm|[Uu]fer|[Cc]haussee|[Ss]teig)(?![\wäöüß])(?:\s*\d+\s*[a-z]?(?![\wäöüß]))?")


def redact_place(text: str | None) -> str | None:
    if not text:
        return text
    t = STREET_RE.sub("[Standort geschützt] ", text)
    t = re.sub(r"(?<![\d.,])\b\d{5}\b(?![.,]\d)(?!\s*(?:€|EUR|Euro))\s*", "", t)   # postcode; the city name stays
    return re.sub(r"\s+([,.;])", r"\1", re.sub(r"\s{2,}", " ", t)).strip()


# --------------------------------------------------------------------------------------------- #
# Berlin Zuwendungsdatenbank
# --------------------------------------------------------------------------------------------- #
BZ_BASE = "https://www.berlin.de/sen/finanzen/service/zuwendungsdatenbank/"
BZ_BULK = BZ_BASE + "index.php/index/all.json?q="
BZ_DETAIL = BZ_BASE + "index.php/detail/{id}"
BZ_LICENSE = ("CC BY-SA (Berlin Open Data register, license_id 'cc-by-sa', "
              "datenregister.berlin.de package simple_search_wwwberlindesenfinanzenservicezuwendungsdatenbank)")
BZ_PUBLISHER = "Senatsverwaltung für Finanzen Berlin"

BZ_CORE = re.compile("|".join([
    r"wohnungslos\w*", r"obdachlos\w*", r"wohnungsnot\w*", r"k[äa]e?ltehilfe\w*", r"k[äa]e?ltebus",
    r"w[äa]e?rmestube", r"not[üu]e?bernachtung\w*", r"nachtcaf[ée]\w*", r"housing first",
    r"bahnhofsmission", r"ohne (?:eigenen )?wohnraum", r"ohne obdach", r"zwangsr[äa]e?umung\w*",
    r"wohnungsverlust\w*", r"mietschulden\w*", r"§ ?67 sgb ?xii"]), re.I)
BZ_ADJACENT = re.compile("|".join([
    r"stra[ßs]s?ensozialarbeit", r"suppenk[üu]e?che", r"kleiderkammer", r"notunterkunft\w*",
    r"notunterbringung\w*", r"essensausgabe"]), re.I)

BZ_DDL = """
CREATE TABLE IF NOT EXISTS funding_traeger_zuwendung (
  zuw_id         INTEGER PRIMARY KEY,   -- id in the Berlin Zuwendungsdatenbank
  name           TEXT,
  name_norm      TEXT,
  register_id    TEXT,                  -- published 'Registrierungsnummer', e.g. vr_021507
  geber          TEXT,
  art            TEXT,
  jahr           INTEGER,
  anschrift      TEXT,                  -- NULL when the grant concerns a protected shelter
  politikbereich TEXT,
  zweck          TEXT,
  betrag         REAL,
  currency       TEXT DEFAULT 'EUR',
  tier           TEXT,                  -- core | adjacent
  matched_terms  TEXT,                  -- JSON list
  tags           TEXT,                  -- JSON list: refugee, protected_shelter
  detail_url     TEXT,
  source_id      INTEGER
);
CREATE INDEX IF NOT EXISTS ix_ftz_norm ON funding_traeger_zuwendung(name_norm);
"""


def bz_classify(zweck: str | None) -> tuple[str | None, list[str]]:
    z = zweck or ""
    core = sorted({m.group(0).lower() for m in BZ_CORE.finditer(z)})
    adj = sorted({m.group(0).lower() for m in BZ_ADJACENT.finditer(z)})
    if core:
        return "core", core + adj
    if adj and not REFUGEE_RE.search(z):
        return "adjacent", adj
    return None, []


def bz_is_person(rec: dict) -> bool:
    rid = (rec.get("empfaengerid") or "").strip().lower()
    if not rid or rid == "ohne" or rid.startswith("gbr"):
        return True
    return bool(_PERSON_HINT.search(rec.get("name") or ""))


def split_address(a: str | None) -> tuple[str | None, str | None, str | None]:
    a = common.clean(a)
    if not a:
        return None, None, None
    m = re.match(r"^(.*?),?\s*(\d{5})\s+(.+)$", a)
    if not m:
        return a, None, None
    return common.clean(m.group(1).rstrip(",")), m.group(2), common.clean(m.group(3))


def eur(v) -> float | None:
    if v is None or str(v).strip() == "":
        return None
    s = str(v).strip()
    if not re.fullmatch(r"-?\d+(\.\d+)?", s):
        s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


BERLIN_KREIS_AGS, BERLIN_GEMEINDE_AGS = "11000", "11000000"   # Stadtstaat: Land = Kreis = Gemeinde


# ------------------------------------------------------------------ org resolution (schema 5, INGEST_CONTRACT §10)
_COURT_NUM = re.compile(r"(?<![A-Za-z])(VR|HRA|HRB|GnR|PR)[\s_.:-]*(?:Nr\.?\s*)?0*(\d{1,7})", re.I)
# (schema 6: the legal-form tags once appended to name_norm, e.g. 'MALTESER HILFSDIENST EV', are gone; §12)


_COURT_SHORT = re.compile(r"(?:AG|Amtsgericht)\s+([A-ZÄÖÜ][a-zäöüß][\wäöüß.\-]*(?:[ -]\(?[A-ZÄÖÜ][a-zäöüß][\wäöüß.\-)]*){0,3})"
                          r"\s*[,;:]?\s*(?:Reg(?:ister)?\.?-?\s*Nr\.?\s*:?\s*)?([AB])\s?-?\s?(\d{1,7})\s*")


def valid_company_id(v) -> str | None:
    """A TED NATIONALID / eForms CompanyID kept as empfaenger_id only when it is a real identifier: a German USt-IdNr
    (DE + 9 digits, 'USt-ID:' prefix and spaces allowed), a court register number (VR/HRA/HRB/GnR/PR + digits) or
    an LEI. eForms often carries notice-internal sequence numbers ('2', '6'), GUIDs, tax numbers or 'keine Angabe':
    those are dropped (None)."""
    t = common.clean(v)
    if not t:
        return None
    ust = re.sub(r"[\s.]", "", re.sub(r"(?i)^\s*(?:USt[-\s]?Id(?:Nr)?\.?|UID)\s*:?\s*", "", t))
    if re.fullmatch(r"DE\d{9}", ust):
        return ust
    short = _COURT_SHORT.fullmatch(t)
    if short:   # 'AG Bochum B14528': court named + Handelsregister A/B shorthand -> 'HRB 14528 (AG Bochum)'
        return f"HR{short.group(2).upper()} {int(short.group(3))} (AG {short.group(1).strip()})"
    reg = common.parse_register(t)
    if reg and reg["scheme"] in ("VR", "HRA", "HRB", "GnR", "PR") and re.search(r"\d", reg["number"]):
        return t
    if re.fullmatch(r"[A-Z0-9]{18}\d{2}", re.sub(r"\s", "", t)):
        return re.sub(r"\s", "", t)
    return None


def ensure_org_xland(conn, name, land, sid, *, register=None, ust_id=None, stats: dict | None = None, **cols):
    """Grant readers (Hamburg, M-V, Bremen/RLP, ESF): resolve a recipient before creating a Land-scoped org.
    1. hard ids (register / USt-ID) via common.resolve_org; 2. name + legal form in the record's Land (find_org);
    3. name + legal form in ANY Land, used only when exactly one canonical candidate matches exactly / by legal-form
    family / with one form unknown (national bodies such as BAG W, Lead 2026-11-23); 4. else common.ensure_org.
    The award link is written by orglink.sync (a cross-Land name match stays a flagged name_fuzzy link)."""
    hit = common.resolve_org(conn, register=register, ust_id=ust_id) if (register or ust_id) else None
    if hit:
        return hit
    r = common.find_org(conn, name, land)
    if r["org_id"] is None and r["how"] == "new" and not r["taken"]:
        r2 = common.find_org(conn, name, None, any_land=True)
        if r2["org_id"] is not None and r2["how"] in ("exact", "family", "single") and len(r2["candidates"]) == 1:
            if stats is not None:
                stats["xland"] = stats.get("xland", 0) + 1
            return r2["org_id"]
    return common.ensure_org(conn, name, land, sid, register=register, ust_id=ust_id, **cols)


def court_numbers(*raws) -> set[tuple[str, int]]:
    """{('HRB', 82787)} from 'hrb_082787', 'HRB 82787 B', 'VR 21507 B (AG Charlottenburg)' ... (court ignored)."""
    out = set()
    for r in raws:
        for m in _COURT_NUM.finditer(str(r or "")):
            out.add((m.group(1).upper().replace("GNR", "GnR"), int(m.group(2))))
    return out


def org_hard_ids(conn, oid) -> tuple[set, set]:
    """(court register numbers, Lobbyregister numbers) an org row (and its alias rows) holds."""
    ids = [r[0] for r in conn.execute("SELECT id FROM org WHERE id=? OR canonical_org_id=?", (oid, oid))]
    q = ",".join("?" * len(ids))
    raws = [r[0] for r in conn.execute(f"SELECT register_id FROM org WHERE id IN ({q})", ids)]
    lobby = set()
    for sch, num in conn.execute(f"SELECT scheme, number FROM org_register WHERE org_id IN ({q})", ids):
        if sch == "LobbyR":
            lobby.add(num)
        elif sch in ("VR", "HRA", "HRB", "GnR", "PR"):
            raws.append(f"{sch} {num}")
        elif sch == "BE_ZUWDB":
            raws.append(num)
    return court_numbers(*raws), lobby


def org_compatible(conn, oid, name, *, register=None, lobby=None) -> bool:
    """May a record named `name` (with these hard ids) land on org `oid`? Never when the legal form differs
    (e.V. vs gGmbH: 'Malteser Hilfsdienst e.V.' is not 'Malteser Hilfsdienst gGmbH') or when the org already
    holds a *different* number in the same kind of register (Fixpunkt e. V. vs Fixpunkt gGmbH hrb_082787)."""
    from ingest import orglink
    row = conn.execute("SELECT name, legal_form FROM org WHERE id=?", (oid,)).fetchone()
    if row is None:
        return False
    ka, kb = orglink.legal_kind(name), orglink.legal_kind(row[0], row[1])
    if ka and kb and ka != kb and {ka, kb} != {"GmbH", "gGmbH"}:
        return False
    have_court, have_lobby = org_hard_ids(conn, oid)
    mine = court_numbers(register)
    if mine and have_court and not (mine & have_court):
        return False
    if lobby and have_lobby and lobby not in have_lobby:
        return False
    return True


def resolve_or_find(conn, name, nn, land, *, register=None, ust_id=None, lobby=None, any_land=False):
    """(org_id, how) for a source record, or (None, key) with the name_norm key a new org row must use.

    1. common.resolve_org with every hard id the source prints (register / Lobbyregister number / USt-IdNr);
       a USt-IdNr hit is only taken when the legal form agrees (VAT groups share one number);
    2. otherwise an exact (name_norm, Land) row - only if org_compatible(); how='name' (a name match: the
       caller records it as a flagged name_fuzzy link where it is not an award/org row the runner links);
    3. otherwise a new row keyed (name_norm, legal_form_norm, Land) (schema 6, INGEST_CONTRACT §12): an e.V. and a
       gGmbH of the same name are two rows with the same name_norm. Only when the exact key is held by a different
       entity of the same legal form (another register number) does the new row's name_norm carry that number.
    Lead 2026-11-23: the name step is common.find_org (legal form in the key, NULL form only with one candidate).
    """
    from ingest import orglink
    reg_arg = register or lobby
    for kw in ({"register": reg_arg} if reg_arg else None, {"ust_id": ust_id} if ust_id else None):
        if not kw:
            continue
        try:
            rid = common.resolve_org(conn, **kw)
        except ValueError:
            rid = None                      # ambiguous hard id: a G11 case for the Lead, never guessed here
        if rid and ("ust_id" not in kw or org_compatible(conn, rid, name)):
            return rid, "hard"
    ok = lambda cid: org_compatible(conn, cid, name, register=register, lobby=lobby)  # noqa: E731
    res = common.find_org(conn, name, land, nn=nn, any_land=any_land, compatible=ok)
    if res["org_id"] is not None:
        return res["org_id"], "name"
    if not res["taken"]:
        return None, nn
    for sch, num in sorted(court_numbers(register))[:1]:      # same name + legal form + Land, other register number
        key = f"{nn} {sch.upper()} {num}"
        r = common.find_org(conn, name, land, nn=key, compatible=ok)
        if r["org_id"] is not None:
            return r["org_id"], "name"
        if not r["taken"]:
            return None, key
    return None, None                       # the key is taken by another entity: never guess


def _ensure_org(conn, name, nn, land, sid, *, register=None, ust_id=None, **extra) -> int | None:
    """Canonical org for this record (resolve first, never a different-register namesake), else a new row.

    `land` may be None (foreign or unknown seat); SQLite UNIQUE treats NULLs as distinct, so look up
    with IS. An org whose own name says it is a protected shelter gets is_protected=1 and no address.
    """
    if not nn:
        return None
    oid, key = resolve_or_find(conn, name, nn, land, register=register, ust_id=ust_id)
    if oid is not None:
        web = extra.get("webseite")
        if web:   # additive only: fill a missing website on a row this domain created
            conn.execute("UPDATE org SET webseite=? WHERE id=? AND webseite IS NULL AND is_protected=0 AND source_id IN "
                         "(SELECT id FROM source WHERE domain=?)", (web, oid, DOMAIN))
        return oid
    if key is None:
        return None
    protected = is_protected(name)
    from ingest.migrate import translate
    vals = translate("org", {k: v for k, v in {**extra, "register_id": register, "ust_id": ust_id}.items()
                             if v is not None})[1]   # schema 2 column names
    if protected:
        for k in ("strasse", "plz", "lat", "lon", "webseite"):
            vals.pop(k, None)
    from ingest import orglink
    oid = conn.execute(
        "INSERT INTO org(name, name_norm, legal_form_norm, land, source_id, currency, is_protected, aktualisiert_am"
        + "".join(f", {k}" for k in vals) + ") VALUES (?,?,?,?,?,?,?,?" + ",?" * len(vals) + ") RETURNING id",
        [name, key, orglink.legal_form_norm(name, vals.get("legal_form")), land, sid, "EUR", 1 if protected else 0,
         common.now(), *vals.values()]).fetchone()[0]
    common.flag_new_org(conn, oid, sid)      # schema 6: unknown legal form next to namesakes -> flagged for review
    return oid


def _web(u):
    """Winner website as printed in the notice ('www.x.de' -> 'https://www.x.de'); None if not a web address."""
    u = common.clean(u)
    if not u or " " in u or "@" in u or "." not in u:
        return None
    return u if re.match(r"(?i)https?://", u) else "https://" + u


def _add_register(conn, org_id, scheme, number, raw, sid) -> None:
    """org_register row, never re-pointing an identifier another org already holds."""
    if not org_id or not number:
        return
    hit = conn.execute("SELECT org_id FROM org_register WHERE scheme=? AND court='' AND number=?",
                       (scheme, number)).fetchone()
    if hit is None:
        conn.execute("INSERT INTO org_register(org_id, scheme, court, number, raw, source_id) VALUES (?,?,?,?,?,?)",
                     (org_id, scheme, "", number, raw, sid))


def _robots_gate(url: str, cfg: dict | None = None, *, post: bool = False) -> None:
    """robots.txt of the host is read (fail-closed, once per run) before any request: berlin.de pages and JSON,
    the TED search API (POST) and notice XML. Same gate as funding_officers.gated_fetch."""
    from ingest.domains import funding_officers as fo
    fo.robots_gate(url, cfg or {}, domain=DOMAIN, cached_ok=not post)


def _fetch_retry(url: str, *, force: bool = False, tries: int = 3) -> bytes:
    """common.fetch, retried on the transient HTTP 307 berlin.de's CDN sometimes answers."""
    import time
    last = None
    for i in range(tries):
        try:
            _robots_gate(url, {"force": force})
            return common.fetch(url, domain=DOMAIN, force=force)
        except RuntimeError as e:
            last = e
            if "HTTP 307" not in str(e) and "HTTP 302" not in str(e):
                raise
            time.sleep(5 * (i + 1))
    raise last


def run_berlin_zuwendungen(conn, cfg: dict) -> dict:
    conn.executescript(BZ_DDL)
    if cfg.get("bz_fixture"):
        data = cfg["bz_fixture"]
    else:
        _robots_gate(BZ_BULK, cfg)
        data = common.fetch_json(BZ_BULK, domain=DOMAIN, force=bool(cfg.get("force")))
    idx = data.get("index") or []
    declared = (data.get("results") or {}).get("count")
    if declared is not None and int(declared) != len(idx):
        raise RuntimeError(f"Berlin export truncated: declared {declared}, received {len(idx)}")
    bulk_sid = common.source_id_for(conn, BZ_BULK, DOMAIN, title="Zuwendungsdatenbank Berlin, JSON-Gesamtexport",
                                    publisher=BZ_PUBLISHER, license=BZ_LICENSE)
    # Lead: the recipient's Anschrift is withheld on ALL its grants and on its org row once any of its grants is a
    # protected-shelter grant (the export repeats the same Anschrift on every grant; export order must not decide
    # whether it leaks). Only the protected grants themselves are tagged and redacted: the other grants of a large
    # Träger (AWO, Caritas Kältehilfe sites) are ordinary public services.
    protected_recipients = {common.name_norm(common.clean(r_.get("name"))) for r_ in idx
                            if is_protected(r_.get("zweck")) or is_protected(r_.get("name"))}
    kept = persons = 0
    details_failed: list[str] = []
    limit = cfg.get("bz_limit")
    tiers = {"core": 0, "adjacent": 0}
    total = 0.0
    orgs = set()
    for rec in idx:
        tier, terms = bz_classify(rec.get("zweck"))
        if not tier:
            continue
        if bz_is_person(rec):
            persons += 1
            continue
        zid = int(rec["id"])
        url = BZ_DETAIL.format(id=zid)
        name = common.clean(rec.get("name"))
        nn = common.name_norm(name)
        amount = eur(rec.get("betrag"))
        year = common.to_int(rec.get("jahr"))
        zweck = common.clean(rec.get("zweck"))
        if is_protected(zweck) or is_protected(rec.get("name")):
            zweck = redact_place(zweck)
        tags = []
        if REFUGEE_RE.search(zweck or ""):
            tags.append("refugee")
        protected = is_protected(zweck) or is_protected(name)
        if protected:
            tags.append("protected_shelter")
        no_address = protected or nn in protected_recipients
        quote = locator = None
        detail_ok = False
        if cfg.get("bz_details", True) and not cfg.get("bz_fixture"):
            try:
                page = common.html_to_text(_fetch_retry(url, force=bool(cfg.get("force"))))
                detail_ok = True
                m = re.search(r"Betrag:\s*([\d.,]+)", page)
                if m and amount is not None and eur(m.group(1)) == amount:
                    quote, locator = f"Betrag: {m.group(1)}", f"Detailseite, Feld 'Betrag' ({bz_unit(year)})"
            except RuntimeError as e:  # detail page unavailable: cite the bulk export instead
                details_failed.append(f"{zid}: {e}"[:160])
        if detail_ok or cfg.get("bz_fixture"):
            sid = common.source_id_for(conn, url, DOMAIN, title=f"Zuwendungsdatenbank Berlin – Zuwendung {zid}: {name}",
                                       publisher=BZ_PUBLISHER, license=BZ_LICENSE)
        else:
            sid = bulk_sid
            locator = f"JSON-Gesamtexport, index[] mit id={zid}, Feld betrag ({bz_unit(year)}); Detailseite {url}"
        street, plz, city = split_address(rec.get("anschrift"))
        rid = common.clean(rec.get("empfaengerid"))
        common.upsert(conn, "funding_traeger_zuwendung", {
            "zuw_id": zid, "name": name, "name_norm": nn, "register_id": rid,
            "geber": common.clean(rec.get("geber")), "art": common.clean(rec.get("art")), "jahr": year,
            "anschrift": None if no_address else common.clean(rec.get("anschrift")),
            "politikbereich": common.clean(rec.get("politikbereich")), "zweck": zweck,
            "betrag": amount, "currency": "EUR", "tier": tier,
            "matched_terms": json.dumps(terms, ensure_ascii=False), "tags": json.dumps(tags),
            "detail_url": url, "source_id": sid}, keys=["zuw_id"])
        org_id = _ensure_org(conn, name, nn, "BE", sid, register=rid,
                             strasse=None if no_address else street,
                             plz=None if no_address else plz,
                             ort=None if no_address else (city or "Berlin"),
                             kreis=None if no_address else "Berlin",
                             kreis_ags=None if no_address else BERLIN_KREIS_AGS)
        # the court is not published, so the id is kept in the database's own scheme (no invented court)
        _add_register(conn, org_id, "BE_ZUWDB", rid, rid, sid)
        orgs.add(nn)
        common.upsert(conn, "award", {
            "foerder_schluessel": f"DE-BE-ZUW:{zid}", "foerder_id": str(zid), "empfaenger": name,
            "empfaenger_norm": nn, "empfaenger_register": rid, "org_id": org_id, "foerderart": "zuwendung",
            "zuwendungsgeber": common.clean(rec.get("geber")), "programm": common.clean(rec.get("art")),
            "zweck": zweck, "betrag": amount, "currency": "EUR",
            "haushaltsjahr": str(year) if year else None, "ort_land": "BE", "quote": quote,
            # Berlin is one Gemeinde (AGS 11000000): unambiguous for unprotected rows; protected rows stay at Land level
            "ort_kreis": None if no_address else BERLIN_KREIS_AGS,
            "ort_gemeinde": None if no_address else BERLIN_GEMEINDE_AGS, "locator": locator,
            "source_id": sid, "is_est": 0,
        }, keys=["foerder_schluessel"])
        kept += 1
        tiers[tier] += 1
        total += amount or 0
        if limit and kept >= int(limit):
            break
    notes = (f"berlin_zuwendungen: {len(idx)} grants in export, kept {kept} (core={tiers['core']}, "
             f"adjacent={tiers['adjacent']}), {len(orgs)} recipients, EUR {total:,.0f}; "
             f"skipped {persons} natural-person/GbR rows; detail pages failed {len(details_failed)}: {details_failed[:3]}")
    return {"rows": kept, "notes": notes, "sources": [(BZ_BULK, BZ_LICENSE)]}


# --------------------------------------------------------------------------------------------- #
# TED (EU Publications Office) API v3 — German award and competition notices, homelessness services
# --------------------------------------------------------------------------------------------- #

TED_SEARCH = "https://api.ted.europa.eu/v3/notices/search"
TED_XML = "https://ted.europa.eu/en/notice/{pub}/xml"
TED_PDF = "https://ted.europa.eu/de/notice/{pub}/pdf"
TED_HTML = "https://ted.europa.eu/de/notice/-/detail/{pub}"
TED_PUBLISHER = "Publications Office of the European Union (TED)"
TED_LICENSE = ("© European Union, 1998-2026. TED legal notice (https://ted.europa.eu/en/legal-notice): "
               "'Unless otherwise noted, the procurement notices published in the Supplement to the Official "
               "Journal of the European Union can be freely reused, for commercial or non-commercial purposes.' "
               "(Commission Decision 2011/833/EU on the reuse of Commission documents)")
TED_KEYWORDS = [
    "wohnungslose", "wohnungslos", "Wohnungslosen", "obdachlose", "obdachlos", "Obdachlosen",
    "Obdachlosenunterkunft", "Obdachlosenunterbringung", "Wohnungslosenhilfe", "Wohnungslosenunterkunft",
    "Obdachlosenhilfe", "Notunterkunft", "Notunterkünfte", "Notübernachtung", "Kältehilfe", "Wohnungsnotfall",
    "Wohnungsnotfallhilfe", "Wohnungsnotfälle", "Obdachlosigkeit", "Wohnungslosigkeit"]
# social-work / welfare / accommodation CPV codes (exact codes; TED matches any CPV on the notice)
TED_CPVS = ("85300000 85310000 85311000 85312000 85312100 85312200 85312300 85312310 85312320 85312400 "
            "85312500 85320000 85321000 85322000 98341000 98341100 55100000 55110000 55200000 55250000 "
            "55270000 70333000")
PLACEHOLDER_MAX = 100.0   # TED award values below EUR 100 are "not disclosed" placeholders (-1, 0.01, 1)
TED_HOMELESS_RE = re.compile(r"wohnungslos\w*|obdachlos\w*|notunterk\w*|not[üu]e?bernachtung\w*|"
                             r"k[äa]e?ltehilfe|wohnungsnotf[äa]e?ll\w*|wohnungsnot\b", re.I)
NUTS_LAND = {"DE1": "BW", "DE2": "BY", "DE3": "BE", "DE4": "BB", "DE5": "HB", "DE6": "HH", "DE7": "HE",
             "DE8": "MV", "DE9": "NI", "DEA": "NW", "DEB": "RP", "DEC": "SL", "DED": "SN", "DEE": "ST",
             "DEF": "SH", "DEG": "TH"}
_ORG_TOKEN = re.compile(
    r"\b(e\.?\s?v\.?|g?gmbh|mbh|g?ag|eg|ug|kg|ohg|partg\w*|se|ltd|gbr|a[öo]e?r|k[öo]e?r|stiftung|verein\w*|"
    r"verband|werk\w*|diakon\w*|caritas\w*|awo|arbeiterwohlfahrt|drk|rotes? kreuz\w*|johanniter\w*|malteser\w*|"
    r"parit[äa]e?t\w*|mission|kirche\w*|kirchen\w*|gemeinde\w*|stadt\w*|kreis\w*|landkreis|amt|gesellschaft|"
    r"hilfe\w*|dienst\w*|service\w*|zentrum|haus|hotel\w*|holding|group|gruppe|wohnen|sozial\w*|tr[äa]e?ger\w*|"
    r"genossenschaft|jugend\w*|bund\w*|land|universit\w*|institut\w*|agentur|partner\w*|team|co|"
    r"gemeinn[üu]e?tzig\w*|betrieb\w*|unternehmen\w*|management|consult\w*|immobilien\w*|bau\w*)\b", re.I)
# GbR partners are natural persons (Berlin publishes GbR grants only as aggregates for that reason)
_SOLE_TRADER = re.compile(r"\be\.?\s?k(fm|fr)?\.?(?=\s|$|,)|\binh\.|\binhaber\w*|\bGbR\b", re.I)

TED_DDL = """
CREATE TABLE IF NOT EXISTS funding_traeger_ted_notice (
  pub          TEXT PRIMARY KEY,   -- TED publication number, e.g. 51019-2024
  notice_type  TEXT,               -- TED notice-type (can-standard, cn-social, ...)
  form_type    TEXT,
  schema       TEXT,               -- legacy | eforms
  pub_date     TEXT,
  buyer_name   TEXT,
  buyer_city   TEXT,               -- NULL for protected-shelter notices
  buyer_nuts   TEXT,
  buyer_land   TEXT,
  title        TEXT,
  cpv_main     TEXT,
  cpv_all      TEXT,               -- JSON
  est_value    REAL,
  est_currency TEXT,
  total_value  REAL,               -- notice-level total as published (may cover all lots / framework)
  total_currency TEXT,
  n_awards     INTEGER,
  keywords     TEXT,               -- JSON: search keywords that returned this notice
  tags         TEXT,               -- JSON: homelessness, refugee, refugee_mention, protected_shelter, ...
  xml_url      TEXT,
  pdf_url      TEXT,
  html_url     TEXT,
  source_id    INTEGER
);
CREATE TABLE IF NOT EXISTS funding_traeger_ted_award (
  pub          TEXT NOT NULL,
  contract_ref TEXT NOT NULL,      -- legacy AWARD_CONTRACT ITEM / eForms LotTender id
  winner_norm  TEXT NOT NULL,
  lot          TEXT,
  lot_title    TEXT,
  winner_name  TEXT,
  winner_id    TEXT,               -- national id as published (USt-IdNr / register no.)
  winner_city  TEXT,               -- NULL for protected-shelter notices
  winner_nuts  TEXT,
  winner_country TEXT,
  n_members    INTEGER,            -- members of the winning tendering party (consortium)
  is_lead      INTEGER,
  value        REAL,               -- value of this contract/tender; only on the lead member
  value_low    REAL,
  value_high   REAL,
  value_published_raw REAL,       -- placeholder as printed (-1, 0.01, 1) when the buyer withheld the value
  currency     TEXT,
  contract_date TEXT,
  tags         TEXT,
  source_id    INTEGER,
  PRIMARY KEY (pub, contract_ref, winner_norm)
);
"""


def _ln(tag) -> str:
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _kids(e, name):
    return [c for c in list(e) if _ln(c.tag) == name] if e is not None else []


def _kid(e, *path):
    for name in path:
        if e is None:
            return None
        e = next((c for c in list(e) if _ln(c.tag) == name), None)
    return e


def _find_all(e, name):
    return [x for x in e.iter() if _ln(x.tag) == name] if e is not None else []


def _txt(e) -> str | None:
    return common.clean(" ".join(e.itertext())) if e is not None else None


_VALUE_TAGS = ("PayableAmount", "VAL_TOTAL", "TenderAmount", "TotalAmount")


def bz_unit(year) -> str:
    """Unit with basis and period for a Berlin Zuwendungsdatenbank amount (publisher: 'auf Antrag bewilligte
    Zuwendungen', one row per Jahr)."""
    return f"EUR, Zuwendung {year}, bewilligt" if year else "EUR, Zuwendung, bewilligt"


def _value_quote(xml_text: str, value: float | None) -> tuple[str | None, str | None]:
    """The XML element that publishes `value`, verbatim (award.quote) and its element name (locator)."""
    if value is None:
        return None, None
    for tag in _VALUE_TAGS:
        for m in re.finditer(r"<((?:\w+:)?" + tag + r")\b[^<>]*>\s*([\d.,]+)\s*</\1>", xml_text):
            if _num(m.group(2)) == value:
                return m.group(0), m.group(1)
    return None, None


def _num(s) -> float | None:
    s = common.clean(s)
    if s is None:
        return None
    s = s.replace(" ", "")
    if re.fullmatch(r"-?\d+(\.\d+)?", s):
        return float(s)
    if re.fullmatch(r"-?\d{1,3}(\.\d{3})*(,\d+)?", s) or re.fullmatch(r"-?\d+,\d+", s):
        return float(s.replace(".", "").replace(",", "."))
    return None


def _date(s) -> str | None:
    s = common.clean(s)
    if not s:
        return None
    m = re.match(r"(\d{4})-?(\d{2})-?(\d{2})", s)
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else None


def nuts_land(code) -> str | None:
    return NUTS_LAND.get((code or "")[:3].upper())


def ted_is_person(name: str | None) -> bool:
    """Privacy guard for winners: True when the name looks like a natural person / sole trader."""
    n = common.clean(name) or ""
    if not n:
        return True
    if _PERSON_HINT.search(n) or _SOLE_TRADER.search(n):
        return True
    if _ORG_TOKEN.search(n):
        # trade name followed by a bare personal name, e.g. "Glas- und Gebäudereinigung Philipp Lange"
        if re.search(r"(reinigung|handwerk|malerei|transporte?|dienstleistungen)\s+[A-ZÄÖÜ][a-zäöüß]+\s+"
                     r"[A-ZÄÖÜ][a-zäöüß\-]+$", n) and not re.search(r"gmbh|e\.?\s?v|ag\b|kg\b|ug\b", n, re.I):
            return True
        return False
    words = [w for w in re.split(r"\s+", n) if w]
    if 2 <= len(words) <= 4 and all(re.fullmatch(r"(Dr\.|Prof\.|[A-ZÄÖÜ][a-zäöüß\-]+\.?)", w) for w in words):
        return True
    # no organisation token at all: privacy wins
    return True


def _cpv_codes(root) -> list[str]:
    out = []
    for e in root.iter():
        t = _ln(e.tag)
        if t == "CPV_CODE" and e.get("CODE"):
            out.append(e.get("CODE"))
        elif t == "ItemClassificationCode" and (e.text or "").strip():
            out.append(e.text.strip())
    return list(dict.fromkeys(out))


def parse_legacy(root) -> tuple[dict, list[dict]]:
    """TED_EXPORT (R2.0.8 / R2.0.9). Reads the ORIGINAL-language form only."""
    forms = [f for fs in _find_all(root, "FORM_SECTION") for f in list(fs)]
    form = next((f for f in forms if f.get("CATEGORY") == "ORIGINAL"), forms[0] if forms else root)
    cb = _kid(form, "CONTRACTING_BODY", "ADDRESS_CONTRACTING_BODY")
    oc = _kid(form, "OBJECT_CONTRACT")
    nuts = _kid(cb, "NUTS")
    est = _kid(oc, "VAL_ESTIMATED_TOTAL")
    tot = _kid(oc, "VAL_TOTAL")
    cpv_main = _kid(oc, "CPV_MAIN", "CPV_CODE")
    lot_titles = {}
    for od in _kids(oc, "OBJECT_DESCR"):
        lot_titles[_txt(_kid(od, "LOT_NO")) or "-"] = _txt(_kid(od, "TITLE"))
    notice = {
        "schema": "legacy",
        "pub_date": _date(_txt(_kid(root, "CODED_DATA_SECTION", "REF_OJS", "DATE_PUB"))),
        "buyer_name": _txt(_kid(cb, "OFFICIALNAME")), "buyer_city": _txt(_kid(cb, "TOWN")),
        "buyer_nuts": nuts.get("CODE") if nuts is not None else None,
        "title": _txt(_kid(oc, "TITLE")), "short_descr": _txt(_kid(oc, "SHORT_DESCR")),
        "cpv_main": cpv_main.get("CODE") if cpv_main is not None else None,
        "cpv_all": _cpv_codes(form),
        "est_value": _num(est.text) if est is not None else None,
        "est_currency": est.get("CURRENCY") if est is not None else None,
        "total_value": _num(tot.text) if tot is not None else None,
        "total_currency": tot.get("CURRENCY") if tot is not None else None,
        "lot_titles": lot_titles,
    }
    awards = []
    for i, ac in enumerate(_kids(form, "AWARD_CONTRACT"), 1):
        aw = _kid(ac, "AWARDED_CONTRACT")
        if aw is None:
            continue
        lot = _txt(_kid(ac, "LOT_NO"))
        contractors = _find_all(aw, "CONTRACTOR")
        winners = []
        for c in contractors:
            a = _kid(c, "ADDRESS_CONTRACTOR")
            if a is None:
                continue
            n = _kid(a, "NUTS")
            ctry = _kid(a, "COUNTRY")
            winners.append({"name": _txt(_kid(a, "OFFICIALNAME")), "nat_id": _txt(_kid(a, "NATIONALID")),
                            "city": _txt(_kid(a, "TOWN")), "nuts": n.get("CODE") if n is not None else None,
                            "url": _txt(_kid(a, "URL")),
                            "country": ctry.get("VALUE") if ctry is not None else None})
        vals = _kid(aw, "VALUES")
        vt = _kid(vals, "VAL_TOTAL")
        vr = _kid(vals, "VAL_RANGE_TOTAL")
        cur = (vt.get("CURRENCY") if vt is not None else None) or (vr.get("CURRENCY") if vr is not None else None)
        awards.append({
            "ref": f"ITEM-{ac.get('ITEM') or i}", "lot": lot,
            "lot_title": _txt(_kid(ac, "TITLE")) or lot_titles.get(lot or "-"),
            "winners": winners, "lead_index": 0,
            "value": _num(vt.text) if vt is not None else None,
            "value_low": _num(_txt(_kid(vr, "LOW"))), "value_high": _num(_txt(_kid(vr, "HIGH"))),
            "currency": cur, "contract_date": _date(_txt(_kid(aw, "DATE_CONCLUSION_CONTRACT")))})
    return notice, awards


def _pick_lang(elems) -> str | None:
    vals = [(e.get("languageID"), _txt(e)) for e in elems if _txt(e)]
    for lang, v in vals:
        if (lang or "").upper() == "DEU":
            return v
    return vals[0][1] if vals else None


def parse_eforms(root) -> tuple[dict, list[dict]]:
    orgs = {}
    for o in _find_all(root, "Organization"):
        comp = _kid(o, "Company")
        oid = _txt(_kid(comp, "PartyIdentification", "ID"))
        if not oid:
            continue
        addr = _kid(comp, "PostalAddress")
        orgs[oid] = {"name": _pick_lang(_kids(_kid(comp, "PartyName"), "Name")),
                     "nat_id": _txt(_kid(comp, "PartyLegalEntity", "CompanyID")),
                     "city": _txt(_kid(addr, "CityName")), "nuts": _txt(_kid(addr, "CountrySubentityCode")),
                     "url": _txt(_kid(comp, "WebsiteURI")),
                     "country": _txt(_kid(addr, "Country", "IdentificationCode")),
                     "natural": (_txt(_kid(o, "NaturalPersonIndicator")) or "").lower() == "true"}
    buyer_id = _txt(_kid(root, "ContractingParty", "Party", "PartyIdentification", "ID"))
    buyer = orgs.get(buyer_id, {})
    pp = _kid(root, "ProcurementProject")
    est = _kid(pp, "RequestedTenderTotal", "EstimatedOverallContractAmount")
    lot_titles = {}
    for lot in _kids(root, "ProcurementProjectLot"):
        lot_titles[_txt(_kid(lot, "ID"))] = _pick_lang(_kids(_kid(lot, "ProcurementProject"), "Name"))
    nr = next(iter(_find_all(root, "NoticeResult")), None)
    tot = _kid(nr, "TotalAmount")
    notice = {
        "schema": "eforms", "pub_date": None,
        "buyer_name": buyer.get("name"), "buyer_city": buyer.get("city"), "buyer_nuts": buyer.get("nuts"),
        "title": _pick_lang(_kids(pp, "Name")), "short_descr": _pick_lang(_kids(pp, "Description")),
        "cpv_main": _txt(_kid(pp, "MainCommodityClassification", "ItemClassificationCode")),
        "cpv_all": _cpv_codes(root),
        "est_value": _num(est.text) if est is not None else None,
        "est_currency": est.get("currencyID") if est is not None else None,
        "total_value": _num(tot.text) if tot is not None else None,
        "total_currency": tot.get("currencyID") if tot is not None else None,
        "lot_titles": lot_titles,
    }
    awards = []
    if nr is None:
        return notice, awards
    parties = {}
    for tp in _kids(nr, "TenderingParty"):
        members = []
        for t in _kids(tp, "Tenderer"):
            members.append((_txt(_kid(t, "ID")), (_txt(_kid(t, "GroupLeadIndicator")) or "").lower() == "true"))
        parties[_txt(_kid(tp, "ID"))] = members
    contract_date = {}
    for sc in _kids(nr, "SettledContract"):
        for lt in _kids(sc, "LotTender"):
            contract_date[_txt(_kid(lt, "ID"))] = _date(_txt(_kid(sc, "IssueDate")))
    winning = set()
    for lr in _kids(nr, "LotResult"):
        if (_txt(_kid(lr, "TenderResultCode")) or "selec-w") != "selec-w":
            continue
        for lt in _kids(lr, "LotTender"):
            winning.add(_txt(_kid(lt, "ID")))
    for lt in _kids(nr, "LotTender"):
        tid = _txt(_kid(lt, "ID"))
        if winning and tid not in winning:
            continue
        lot = _txt(_kid(lt, "TenderLot", "ID"))
        amt = _kid(lt, "LegalMonetaryTotal", "PayableAmount")
        members = parties.get(_txt(_kid(lt, "TenderingParty", "ID")), [])
        winners, lead = [], 0
        for j, (oid, is_lead) in enumerate(members):
            o = dict(orgs.get(oid) or {"name": None})
            winners.append(o)
            if is_lead:
                lead = j
        awards.append({"ref": tid, "lot": lot, "lot_title": lot_titles.get(lot), "winners": winners,
                       "lead_index": lead, "value": _num(amt.text) if amt is not None else None,
                       "value_low": None, "value_high": None,
                       "currency": amt.get("currencyID") if amt is not None else None,
                       "contract_date": contract_date.get(tid)})
    return notice, awards


def parse_notice(xml_bytes: bytes) -> tuple[dict, list[dict], str]:
    root = ET.fromstring(xml_bytes)
    text = " ".join(t.strip() for t in root.itertext() if t and t.strip())
    if _ln(root.tag) == "TED_EXPORT":
        n, a = parse_legacy(root)
    else:
        n, a = parse_eforms(root)
    return n, a, text


def ted_tags(notice: dict, awards: list[dict], text: str) -> list[str]:
    tags = []
    head = " ".join(x for x in [notice.get("title"), notice.get("short_descr"),
                                *[a.get("lot_title") or "" for a in awards],
                                *[(v or "") for v in (notice.get("lot_titles") or {}).values()]] if x)
    if TED_HOMELESS_RE.search(text):
        tags.append("homelessness")
    else:
        tags.append("no_keyword_in_notice_text")
    if REFUGEE_RE.search(head):
        tags.append("refugee")
    elif REFUGEE_RE.search(text):
        tags.append("refugee_mention")
    if is_protected(text):
        tags.append("protected_shelter")
    cpv = notice.get("cpv_main") or ""
    if cpv[:2] == "45" or cpv[:2] == "71" or cpv.startswith("90911") or cpv.startswith("79710"):
        tags.append("facility_works")
    return tags


def ted_search(cfg: dict) -> dict:
    if cfg.get("ted_fixture"):
        return cfg["ted_fixture"]["search"]
    found: dict[str, dict] = {}
    max_pages = int(cfg.get("ted_max_pages") or 40)
    for kw in cfg.get("ted_keywords") or TED_KEYWORDS:
        q = f"buyer-country = DEU AND FT ~ ({kw}) AND classification-cpv IN ({TED_CPVS})"
        for page in range(1, max_pages + 1):
            _robots_gate(TED_SEARCH, cfg, post=True)
            res = common.fetch_post_json(TED_SEARCH, {
                "query": q, "fields": ["publication-number", "notice-type", "form-type", "publication-date"],
                "limit": 250, "page": page}, domain=DOMAIN)
            batch = res.get("notices") or []
            for n in batch:
                pub = n.get("publication-number")
                if not pub:
                    continue
                d = found.setdefault(pub, {"notice-type": n.get("notice-type"), "form-type": n.get("form-type"),
                                           "publication-date": n.get("publication-date"), "keywords": []})
                d["keywords"].append(kw)
            if len(batch) < 250:
                break
    return found


def run_ted(conn, cfg: dict) -> dict:
    conn.executescript(TED_DDL)
    found = ted_search(cfg)
    limit = cfg.get("ted_limit")
    stats = {"notices": 0, "failed": [], "award_rows": 0, "persons_skipped": 0, "refugee": 0,
             "protected": 0, "by_type": {}, "values": {}}
    for k, (pub, meta) in enumerate(sorted(found.items())):
        if limit and k >= int(limit):
            break
        xml_url = TED_XML.format(pub=pub)
        try:
            if cfg.get("ted_fixture"):
                raw = cfg["ted_fixture"]["xml"][pub]
            else:
                _robots_gate(xml_url, cfg)
                raw = common.fetch(xml_url, domain=DOMAIN)
            notice, awards, text = parse_notice(raw)
            xml_text = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)
        except Exception as e:  # noqa: BLE001 - one bad notice must not stop the run
            stats["failed"].append(f"{pub}: {e!r}"[:200])
            continue
        tags = ted_tags(notice, awards, text)
        protected = "protected_shelter" in tags
        refugee = "refugee" in tags
        placeholder = False
        for aw in awards:  # buyers who withhold the value publish -1, 0, 0.01 or 1: not an amount
            for fld in ("value", "value_low", "value_high"):
                if aw.get(fld) is not None and aw[fld] < PLACEHOLDER_MAX:
                    aw.setdefault("raw_" + fld, aw[fld])
                    aw[fld] = None
                    placeholder = True
        if placeholder:
            tags.append("value_withheld_placeholder")
        stats["notices"] += 1
        stats["refugee"] += refugee
        stats["protected"] += protected
        ntype = meta.get("notice-type")
        stats["by_type"][ntype] = stats["by_type"].get(ntype, 0) + 1
        title = notice.get("title")
        if protected:
            title = redact_place(title)
            notice["title"] = title
            for aw in awards:
                aw["lot_title"] = redact_place(aw.get("lot_title"))
        sid = common.source_id_for(conn, xml_url, DOMAIN, title=f"TED {pub}: {title or ''}".strip(),
                                   publisher=TED_PUBLISHER, license=TED_LICENSE)
        pub_date = notice.get("pub_date") or _date(meta.get("publication-date"))
        buyer_land = nuts_land(notice.get("buyer_nuts"))
        n_awards = 0
        for aw in awards:
            winners = aw["winners"]
            n_members = len(winners)
            for j, w in enumerate(winners):
                name = common.clean(w.get("name"))
                if not name or w.get("natural") or ted_is_person(name):
                    stats["persons_skipped"] += 1
                    continue
                nn = common.name_norm(name)
                is_lead = 1 if j == aw.get("lead_index", 0) else 0
                value = aw["value"] if is_lead else None
                cur = aw["currency"] if (value is not None or aw["value_low"] is not None) else None
                nat = common.clean(w.get("nat_id"))
                common.upsert(conn, "funding_traeger_ted_award", {
                    "pub": pub, "contract_ref": aw["ref"], "winner_norm": nn, "lot": aw["lot"],
                    "lot_title": aw["lot_title"], "winner_name": name, "winner_id": nat,
                    "winner_city": None if protected else common.clean(w.get("city")),
                    "winner_nuts": None if protected else w.get("nuts"), "winner_country": w.get("country"),
                    "n_members": n_members, "is_lead": is_lead, "value": value,
                    "value_low": aw["value_low"] if is_lead else None,
                    "value_published_raw": aw.get("raw_value") if is_lead else None,
                    "value_high": aw["value_high"] if is_lead else None, "currency": cur,
                    "contract_date": aw["contract_date"], "tags": json.dumps(tags), "source_id": sid,
                }, keys=["pub", "contract_ref", "winner_norm"])
                nat = valid_company_id(nat)       # notice-internal sequence numbers / GUIDs are not ids
                ust = nat or ""
                is_ust = bool(re.fullmatch(r"DE\d{9}", ust))
                reg = common.parse_register(nat) if nat and not is_ust else None
                # eForms CompanyID is often an internal GUID / e-procurement id: keep it only as recipient_id
                reg_raw = nat if (reg and reg["scheme"] in ("VR", "HRA", "HRB", "GnR", "PR")) else None
                w_land = nuts_land(w.get("nuts")) if (w.get("country") in (None, "DEU", "DE")) else None
                org_id = _ensure_org(conn, name, nn, w_land, sid,
                                     ust_id=ust if is_ust else None, register=reg_raw,
                                     ort=None if protected else common.clean(w.get("city")),
                                     webseite=None if protected else _web(w.get("url")))
                if is_ust:
                    _add_register(conn, org_id, "USt-IdNr", ust, nat, sid)
                quote, vtag = _value_quote(xml_text, value)
                desc = " – ".join(x for x in [title, aw["lot_title"] if aw["lot_title"] != title else None] if x)
                date = aw["contract_date"] or pub_date
                common.upsert(conn, "award", {
                    "foerder_schluessel": f"TED:{pub}:{aw['ref']}:{nn}", "foerder_id": pub, "empfaenger": name,
                    "empfaenger_norm": nn, "empfaenger_id": nat, "empfaenger_register": reg_raw,
                    "org_id": org_id, "foerderart": "contract",
                    "zuwendungsgeber": notice.get("buyer_name"), "dienststelle": None if protected else notice.get("buyer_city"),
                    "programm_code": notice.get("cpv_main"),
                    "programm": ("[refugee] " if refugee else "") + (ntype or ""),
                    "zweck": desc or None, "betrag": value, "currency": cur or "EUR",
                    "laufzeit_von": aw["contract_date"], "haushaltsjahr": date[:4] if date else None,
                    "ort_land": buyer_land, "source_id": sid, "is_est": 0, "quote": quote,
                    "locator": (f"TED notice XML, contract/lot {aw['ref']}, element {vtag} "
                                f"({cur or 'EUR'}, award-time contract value of the contract/lot)") if vtag else
                               f"TED notice XML, contract/lot {aw['ref']} ({cur or 'EUR'}, award-time contract value)",
                }, keys=["foerder_schluessel"])
                if nat is None:   # Lead: upsert never writes NULL; clear a stale non-id from an earlier run
                    conn.execute("UPDATE award SET empfaenger_id=NULL WHERE foerder_schluessel=? AND empfaenger_id IS NOT NULL",
                                 (f"TED:{pub}:{aw['ref']}:{nn}",))
                n_awards += 1
                stats["award_rows"] += 1
                if value is not None:
                    stats["values"][cur] = stats["values"].get(cur, 0.0) + value
        common.upsert(conn, "funding_traeger_ted_notice", {
            "pub": pub, "notice_type": ntype, "form_type": meta.get("form-type"), "schema": notice["schema"],
            "pub_date": pub_date, "buyer_name": notice.get("buyer_name"),
            "buyer_city": None if protected else notice.get("buyer_city"),
            "buyer_nuts": None if protected else notice.get("buyer_nuts"), "buyer_land": buyer_land,
            "title": title, "cpv_main": notice.get("cpv_main"), "cpv_all": json.dumps(notice.get("cpv_all")),
            "est_value": notice.get("est_value"), "est_currency": notice.get("est_currency"),
            "total_value": notice.get("total_value"), "total_currency": notice.get("total_currency"),
            "n_awards": n_awards, "keywords": json.dumps(sorted(set(meta.get("keywords") or []))),
            "tags": json.dumps(tags), "xml_url": xml_url, "pdf_url": TED_PDF.format(pub=pub),
            "html_url": TED_HTML.format(pub=pub), "source_id": sid}, keys=["pub"])
    vals = ", ".join(f"{c} {v:,.2f}" for c, v in sorted(stats["values"].items(), key=lambda x: str(x[0])))
    notes = (f"ted: {len(found)} notices found, {stats['notices']} parsed ({stats['by_type']}), "
             f"{stats['award_rows']} award rows, {stats['persons_skipped']} winners skipped as natural persons/"
             f"unnamed, refugee-tagged {stats['refugee']}, protected-shelter {stats['protected']}, "
             f"award value by currency: {vals or 'none'}; failed {len(stats['failed'])}: {stats['failed'][:5]}")
    return {"rows": stats["award_rows"], "notes": notes,
            "sources": [(TED_SEARCH, TED_LICENSE), ("https://ted.europa.eu/en/notice/<pub>/xml", TED_LICENSE)]}


# ---- TED offline fixtures -------------------------------------------------------------------- #
_TED_LEGACY = """<?xml version="1.0" encoding="UTF-8"?>
<TED_EXPORT xmlns="http://publications.europa.eu/resource/schema/ted/R2.0.9/publication" DOC_ID="1-2020">
<CODED_DATA_SECTION><REF_OJS><DATE_PUB>20200102</DATE_PUB></REF_OJS></CODED_DATA_SECTION>
<FORM_SECTION><F03_2014 CATEGORY="ORIGINAL" LG="DE">
<CONTRACTING_BODY><ADDRESS_CONTRACTING_BODY><OFFICIALNAME>Stadt Musterstadt</OFFICIALNAME><TOWN>Musterstadt</TOWN>
<NUTS CODE="DEA22"/><E_MAIL>vergabe@example.org</E_MAIL></ADDRESS_CONTRACTING_BODY></CONTRACTING_BODY>
<OBJECT_CONTRACT><TITLE><P>Betrieb einer Notunterkunft für wohnungslose Menschen</P></TITLE>
<CPV_MAIN><CPV_CODE CODE="85311000"/></CPV_MAIN><VAL_TOTAL CURRENCY="EUR">300000.00</VAL_TOTAL>
<OBJECT_DESCR ITEM="1"><TITLE><P>Los 1 Männer</P></TITLE><LOT_NO>1</LOT_NO></OBJECT_DESCR></OBJECT_CONTRACT>
<AWARD_CONTRACT ITEM="1"><LOT_NO>1</LOT_NO><AWARDED_CONTRACT><DATE_CONCLUSION_CONTRACT>2019-12-01</DATE_CONCLUSION_CONTRACT>
<CONTRACTORS><CONTRACTOR><ADDRESS_CONTRACTOR><OFFICIALNAME>Diakonie Musterstadt gGmbH</OFFICIALNAME>
<NATIONALID>DE123456789</NATIONALID><TOWN>Musterstadt</TOWN><NUTS CODE="DEA22"/><COUNTRY VALUE="DE"/>
<E_MAIL>person@example.org</E_MAIL></ADDRESS_CONTRACTOR></CONTRACTOR></CONTRACTORS>
<VALUES><VAL_TOTAL CURRENCY="EUR">200000.00</VAL_TOTAL></VALUES></AWARDED_CONTRACT></AWARD_CONTRACT>
<AWARD_CONTRACT ITEM="2"><LOT_NO>2</LOT_NO><AWARDED_CONTRACT><DATE_CONCLUSION_CONTRACT>2019-12-01</DATE_CONCLUSION_CONTRACT>
<CONTRACTORS><CONTRACTOR><ADDRESS_CONTRACTOR><OFFICIALNAME>Max Mustermann</OFFICIALNAME><TOWN>Musterstadt</TOWN>
</ADDRESS_CONTRACTOR></CONTRACTOR></CONTRACTORS><VALUES><VAL_TOTAL CURRENCY="EUR">100000.00</VAL_TOTAL></VALUES>
</AWARDED_CONTRACT></AWARD_CONTRACT></F03_2014></FORM_SECTION></TED_EXPORT>"""

_TED_EFORMS = """<?xml version="1.0" encoding="UTF-8"?>
<ContractAwardNotice xmlns="urn:oasis:names:specification:ubl:schema:xsd:ContractAwardNotice-2"
 xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
 xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"
 xmlns:efac="http://data.europa.eu/p27/eforms-ubl-extension-aggregate-components/1"
 xmlns:efbc="http://data.europa.eu/p27/eforms-ubl-extension-basic-components/1"
 xmlns:efext="http://data.europa.eu/p27/eforms-ubl-extensions/1"
 xmlns:ext="urn:oasis:names:specification:ubl:schema:xsd:CommonExtensionComponents-2">
<ext:UBLExtensions><ext:UBLExtension><ext:ExtensionContent><efext:EformsExtension>
<efac:NoticeResult><cbc:TotalAmount currencyID="EUR">900000</cbc:TotalAmount>
<efac:LotResult><cbc:ID>RES-0001</cbc:ID><cbc:TenderResultCode>selec-w</cbc:TenderResultCode>
<efac:LotTender><cbc:ID>TEN-0001</cbc:ID></efac:LotTender><efac:TenderLot><cbc:ID>LOT-0001</cbc:ID></efac:TenderLot></efac:LotResult>
<efac:LotResult><cbc:ID>RES-0002</cbc:ID><cbc:TenderResultCode>selec-w</cbc:TenderResultCode>
<efac:LotTender><cbc:ID>TEN-0002</cbc:ID></efac:LotTender><efac:TenderLot><cbc:ID>LOT-0002</cbc:ID></efac:TenderLot></efac:LotResult>
<efac:LotTender><cbc:ID>TEN-0001</cbc:ID><cac:LegalMonetaryTotal><cbc:PayableAmount currencyID="EUR">800000</cbc:PayableAmount></cac:LegalMonetaryTotal>
<efac:TenderingParty><cbc:ID>TPA-0001</cbc:ID></efac:TenderingParty><efac:TenderLot><cbc:ID>LOT-0001</cbc:ID></efac:TenderLot></efac:LotTender>
<efac:LotTender><cbc:ID>TEN-0002</cbc:ID><cac:LegalMonetaryTotal><cbc:PayableAmount currencyID="EUR">100000</cbc:PayableAmount></cac:LegalMonetaryTotal>
<efac:TenderingParty><cbc:ID>TPA-0002</cbc:ID></efac:TenderingParty><efac:TenderLot><cbc:ID>LOT-0002</cbc:ID></efac:TenderLot></efac:LotTender>
<efac:SettledContract><cbc:ID>CON-0001</cbc:ID><cbc:IssueDate>2024-03-01+01:00</cbc:IssueDate><efac:LotTender><cbc:ID>TEN-0001</cbc:ID></efac:LotTender></efac:SettledContract>
<efac:TenderingParty><cbc:ID>TPA-0001</cbc:ID><efac:Tenderer><cbc:ID>ORG-0002</cbc:ID><efbc:GroupLeadIndicator>false</efbc:GroupLeadIndicator></efac:Tenderer>
<efac:Tenderer><cbc:ID>ORG-0003</cbc:ID><efbc:GroupLeadIndicator>true</efbc:GroupLeadIndicator></efac:Tenderer></efac:TenderingParty>
<efac:TenderingParty><cbc:ID>TPA-0002</cbc:ID><efac:Tenderer><cbc:ID>ORG-0004</cbc:ID></efac:Tenderer></efac:TenderingParty>
</efac:NoticeResult>
<efac:Organizations>
<efac:Organization><efac:Company><cac:PartyIdentification><cbc:ID>ORG-0001</cbc:ID></cac:PartyIdentification>
<cac:PartyName><cbc:Name languageID="DEU">Landkreis Beispiel</cbc:Name></cac:PartyName><cac:PostalAddress><cbc:CityName>Beispielstadt</cbc:CityName>
<cbc:CountrySubentityCode>DE212</cbc:CountrySubentityCode><cac:Country><cbc:IdentificationCode>DEU</cbc:IdentificationCode></cac:Country></cac:PostalAddress>
<cac:Contact><cbc:Telephone>+49 1</cbc:Telephone><cbc:ElectronicMail>a@b.de</cbc:ElectronicMail></cac:Contact></efac:Company></efac:Organization>
<efac:Organization><efac:Company><cac:PartyIdentification><cbc:ID>ORG-0002</cbc:ID></cac:PartyIdentification>
<cac:PartyName><cbc:Name languageID="DEU">Caritasverband Beispiel e.V.</cbc:Name></cac:PartyName><cac:PostalAddress><cbc:CityName>Beispielstadt</cbc:CityName>
<cbc:CountrySubentityCode>DE212</cbc:CountrySubentityCode><cac:Country><cbc:IdentificationCode>DEU</cbc:IdentificationCode></cac:Country></cac:PostalAddress>
<cac:PartyLegalEntity><cbc:CompanyID>VR 1234</cbc:CompanyID></cac:PartyLegalEntity></efac:Company></efac:Organization>
<efac:Organization><efac:Company><cac:PartyIdentification><cbc:ID>ORG-0003</cbc:ID></cac:PartyIdentification>
<cac:PartyName><cbc:Name languageID="DEU">Wohnhilfe Beispiel gGmbH</cbc:Name></cac:PartyName><cac:PostalAddress><cbc:CityName>Beispielstadt</cbc:CityName>
<cbc:CountrySubentityCode>DE212</cbc:CountrySubentityCode><cac:Country><cbc:IdentificationCode>DEU</cbc:IdentificationCode></cac:Country></cac:PostalAddress>
<cac:PartyLegalEntity><cbc:CompanyID>DE 987654321</cbc:CompanyID></cac:PartyLegalEntity></efac:Company></efac:Organization>
<efac:Organization><efac:Company><cac:PartyIdentification><cbc:ID>ORG-0004</cbc:ID></cac:PartyIdentification>
<cac:PartyName><cbc:Name languageID="DEU">Erika Musterfrau</cbc:Name></cac:PartyName></efac:Company></efac:Organization>
</efac:Organizations></efext:EformsExtension></ext:ExtensionContent></ext:UBLExtension></ext:UBLExtensions>
<cac:ContractingParty><cac:Party><cac:PartyIdentification><cbc:ID>ORG-0001</cbc:ID></cac:PartyIdentification></cac:Party></cac:ContractingParty>
<cac:ProcurementProject><cbc:Name languageID="DEU">Betrieb einer Gemeinschaftsunterkunft für Geflüchtete und obdachlose Personen</cbc:Name>
<cac:MainCommodityClassification><cbc:ItemClassificationCode listName="cpv">85311000</cbc:ItemClassificationCode></cac:MainCommodityClassification></cac:ProcurementProject>
<cac:ProcurementProjectLot><cbc:ID schemeName="Lot">LOT-0001</cbc:ID><cac:ProcurementProject><cbc:Name languageID="DEU">Los 1</cbc:Name></cac:ProcurementProject></cac:ProcurementProjectLot>
</ContractAwardNotice>"""

_TED_PROTECTED = _TED_LEGACY.replace("Betrieb einer Notunterkunft für wohnungslose Menschen",
                                     "Frauenhaus und Notunterkunft für wohnungslose Frauen").replace(
                                     "Diakonie Musterstadt gGmbH", "Frauen helfen Frauen e.V.")

_TED_PLACEHOLDER = _TED_LEGACY.replace("200000.00", "-1").replace("Diakonie Musterstadt gGmbH", "Kältehilfe Träger gGmbH")

_TED_FIX = {"search": {"1-2020": {"notice-type": "can-standard", "keywords": ["wohnungslose"]},
                       "2-2024": {"notice-type": "can-standard", "publication-date": "2024-03-05Z",
                                  "keywords": ["obdachlose"]},
                       "4-2022": {"notice-type": "can-standard", "keywords": ["Kältehilfe"]},
                       "3-2021": {"notice-type": "can-social", "keywords": ["Notunterkunft"]}},
            "xml": {"1-2020": _TED_LEGACY.encode(), "2-2024": _TED_EFORMS.encode(),
                    "3-2021": _TED_PROTECTED.encode(), "4-2022": _TED_PLACEHOLDER.encode()}}


def _test_ted():
    assert ted_is_person("Max Mustermann") and ted_is_person("Glas- und Gebäudereinigung Philipp Lange")
    assert ted_is_person("Malerei Hans Meier e.K.") and not ted_is_person("Diakonie Musterstadt gGmbH")
    assert not ted_is_person("Caritasverband für das Erzbistum Berlin e.V.")
    conn = memory_conn()
    cfg = {"sources": ["ted"], "ted_fixture": _TED_FIX}
    res = run(conn, cfg)
    run(conn, cfg)  # idempotent
    # legacy: 1 org winner (person skipped); eForms: 2 consortium members (person skipped); protected: 1
    assert res["rows"] == 5, res
    ph = conn.execute("SELECT betrag FROM award WHERE foerder_id='4-2022'").fetchone()
    assert ph[0] is None
    assert conn.execute("SELECT value_published_raw FROM funding_traeger_ted_award WHERE pub='4-2022'").fetchone()[0] == -1
    assert conn.execute("SELECT COUNT(*) FROM award WHERE foerder_schluessel LIKE 'TED:%'").fetchone()[0] == 5
    a = conn.execute("SELECT betrag, currency, ort_land, laufzeit_von, s.url FROM award JOIN source s "
                     "ON s.id=award.source_id WHERE foerder_schluessel LIKE 'TED:1-2020:%'").fetchone()
    assert tuple(a) == (200000.0, "EUR", "NW", "2019-12-01", TED_XML.format(pub="1-2020")), tuple(a)
    cons = conn.execute("SELECT empfaenger, betrag, programm FROM award WHERE foerder_id='2-2024' "
                        "ORDER BY empfaenger").fetchall()
    assert [tuple(r) for r in cons] == [("Caritasverband Beispiel e.V.", None, "[refugee] can-standard"),
                                         ("Wohnhilfe Beispiel gGmbH", 800000.0, "[refugee] can-standard")], cons
    assert conn.execute("SELECT ust_id FROM org WHERE name='Wohnhilfe Beispiel gGmbH'").fetchone()[0] == "DE987654321"
    assert conn.execute("SELECT COUNT(*) FROM org_register WHERE scheme='USt-IdNr'").fetchone()[0] == 2
    assert conn.execute("SELECT empfaenger_register FROM award WHERE empfaenger='Caritasverband Beispiel e.V.'"
                        ).fetchone()[0] == "VR 1234"
    assert conn.execute("SELECT COUNT(*) FROM award WHERE currency IS NULL").fetchone()[0] == 0
    q = conn.execute("SELECT quote, locator FROM award WHERE foerder_id='1-2020'").fetchone()
    assert q[0] and "200000" in q[0] and q[0] in _TED_LEGACY and "VAL_TOTAL" in q[1], tuple(q)
    assert ted_is_person("Müller & Schmidt GbR") and not ted_is_person("Wohnhilfe Beispiel gGmbH")
    p = conn.execute("SELECT dienststelle, ort_land FROM award WHERE foerder_id='3-2021'").fetchone()
    assert p[0] is None
    w = conn.execute("SELECT winner_city, winner_nuts, tags FROM funding_traeger_ted_award WHERE pub='3-2021'").fetchone()
    assert w[0] is None and w[1] is None and "protected_shelter" in w[2]
    assert conn.execute("SELECT ort FROM org WHERE name='Frauen helfen Frauen e.V.'").fetchone()[0] is None
    n = conn.execute("SELECT buyer_city, tags FROM funding_traeger_ted_notice WHERE pub='3-2021'").fetchone()
    assert n[0] is None
    assert conn.execute("SELECT COUNT(*) FROM award WHERE empfaenger LIKE '%Muster%mann%' "
                        "OR empfaenger LIKE '%Musterfrau%'").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM org WHERE email IS NOT NULL OR telefon IS NOT NULL").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM award WHERE source_id IS NULL").fetchone()[0] == 0


SOURCES = {"berlin_zuwendungen": run_berlin_zuwendungen, "ted": run_ted}


# --------------------------------------------------------------------------------------------- #
# contract entry point
# --------------------------------------------------------------------------------------------- #
def run(conn, cfg=None) -> dict:
    cfg = cfg or {}
    names = cfg.get("sources") or list(SOURCES)
    rows, notes, sources = 0, [], []
    for n in names:
        res = SOURCES[n](conn, cfg)
        rows += res["rows"]
        notes.append(res["notes"])
        sources += res["sources"]
    return {"rows": rows, "notes": " | ".join(notes), "sources": sources}


# --------------------------------------------------------------------------------------------- #
# worker tools: in-memory DB, raw cache redirected to /tmp (never data/atlas.db, never data/raw)
# --------------------------------------------------------------------------------------------- #
def memory_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(common.SCHEMA.read_text(encoding="utf-8"))
    return conn


def _redirect_cache(tmp="/tmp/funding_traeger_dryrun"):
    """Dry runs keep the archive in data/raw/ (gitignored; source_id_for needs it under ROOT)
    and only move logs to /tmp. The DB stays in memory."""
    common.LOGS = Path(tmp) / "logs"
    common.LOGS.mkdir(parents=True, exist_ok=True)


def _dryrun(argv):
    _redirect_cache()
    srcs = [a.split("=", 1)[1] for a in argv if a.startswith("--source=")] or None
    out = Path(next((a.split("=", 1)[1] for a in argv if a.startswith("--out=")),
                    "/tmp/funding_traeger_dryrun/awards.jsonl"))
    conn = memory_conn()
    res = run(conn, {"sources": srcs} if srcs else {})
    print(json.dumps({"rows": res["rows"], "notes": res["notes"]}, ensure_ascii=False))
    rows = [dict(r) for r in conn.execute(
        "SELECT a.*, s.url AS citation_url FROM award a JOIN source s ON s.id=a.source_id ORDER BY a.foerder_schluessel")]
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"wrote {len(rows)} award rows to {out}")
    for r in conn.execute("SELECT substr(foerder_schluessel,1,instr(foerder_schluessel,':')-1) k, currency, COUNT(*), "
                          "SUM(betrag) FROM award GROUP BY k, currency"):
        print("total", tuple(r))
    print("orgs", conn.execute("SELECT COUNT(*) FROM org").fetchone()[0],
          "sources", conn.execute("SELECT COUNT(*) FROM source").fetchone()[0])
    assert conn.execute("SELECT COUNT(*) FROM award WHERE source_id IS NULL").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM org WHERE source_id IS NULL").fetchone()[0] == 0


# ---- offline tests --------------------------------------------------------------------------- #
_BZ_FIX = {"results": {"count": 6}, "index": [
    {"id": 8528, "name": "Arbeiterwohlfahrt Berlin Spree-Wuhle e. V.", "geber": "Bezirksamt Friedrichshain-Kreuzberg",
     "art": "Projektförderung", "jahr": "2021", "anschrift": "Rigaer Straße 55b, 10247 Berlin",
     "politikbereich": "Soziales", "zweck": "Wohnungslosentagesstätte Kiezcafé", "betrag": "200250",
     "empfaengerid": "vr_021507"},
    {"id": 1, "name": "Verschiedene natürliche Personen", "geber": "BA X", "art": "Projektförderung", "jahr": "2024",
     "anschrift": "", "politikbereich": "Soziales", "zweck": "Kältehilfe", "betrag": "100", "empfaengerid": "ohne"},
    {"id": 2, "name": "Test Verein e. V.", "geber": "BA X", "art": "Projektförderung", "jahr": "2023",
     "anschrift": "Teststr. 2, 10115 Berlin", "politikbereich": "Integration",
     "zweck": "Spielmaterial für die Notunterkunft für Geflüchtete", "betrag": "300", "empfaengerid": "vr_1"},
    {"id": 3, "name": "Test Verein e. V.", "geber": "BA X", "art": "Projektförderung", "jahr": "2023",
     "anschrift": "Teststr. 2, 10115 Berlin", "politikbereich": "Soziales", "zweck": "Suppenküche im Winter",
     "betrag": "1.234,50", "empfaengerid": "vr_1"},
    {"id": 4, "name": "Frauen Schutz e. V.", "geber": "BA X", "art": "Projektförderung", "jahr": "2023",
     "anschrift": "Geheimstr. 9, 10115 Berlin", "politikbereich": "Frauen",
     "zweck": "Frauenhaus: Plätze für wohnungslose Frauen", "betrag": "5000", "empfaengerid": "vr_9"},
    {"id": 5, "name": "Sportclub e. V.", "geber": "BA X", "art": "Projektförderung", "jahr": "2023",
     "anschrift": "Teststr. 3, 10115 Berlin", "politikbereich": "Sport", "zweck": "Tischtennisplatte",
     "betrag": "800", "empfaengerid": "vr_2"},
]}


def _test_berlin():
    assert bz_classify("Wohnungslosentagesstätte Kiezcafé")[0] == "core"
    assert bz_classify("Suppenküche")[0] == "adjacent"
    assert bz_classify("Notunterkunft für Geflüchtete")[0] is None
    conn = memory_conn()
    cfg = {"sources": ["berlin_zuwendungen"], "bz_fixture": _BZ_FIX}
    res = run(conn, cfg)
    assert set(res) >= {"rows", "notes", "sources"} and res["rows"] == 3, res
    run(conn, cfg)  # idempotent
    assert conn.execute("SELECT COUNT(*) FROM award").fetchone()[0] == 3
    r = conn.execute("SELECT a.betrag, a.currency, s.url FROM award a JOIN source s ON s.id=a.source_id "
                     "WHERE foerder_schluessel='DE-BE-ZUW:8528'").fetchone()
    assert r[0] == 200250.0 and r[1] == "EUR" and r[2] == BZ_DETAIL.format(id=8528)
    assert conn.execute("SELECT betrag FROM award WHERE foerder_schluessel='DE-BE-ZUW:3'").fetchone()[0] == 1234.5
    g = conn.execute("SELECT ort_land, ort_kreis, ort_gemeinde FROM award WHERE foerder_schluessel='DE-BE-ZUW:3'").fetchone()
    assert tuple(g) == ("BE", "11000", "11000000"), tuple(g)
    g = conn.execute("SELECT ort_land, ort_kreis, ort_gemeinde FROM award WHERE foerder_schluessel='DE-BE-ZUW:4'").fetchone()
    assert tuple(g) == ("BE", None, None), tuple(g)          # protected shelter: Land level only
    assert conn.execute("SELECT COUNT(*) FROM metric").fetchone()[0] == 0
    p = conn.execute("SELECT anschrift, tags FROM funding_traeger_zuwendung WHERE zuw_id=4").fetchone()
    assert p[0] is None and "protected_shelter" in p[1]
    o = conn.execute("SELECT strasse, plz, ort FROM org WHERE register_id='vr_9'").fetchone()
    assert tuple(o) == (None, None, None)
    assert conn.execute("SELECT register_id FROM org WHERE register_id='vr_021507'").fetchone()
    assert conn.execute("SELECT empfaenger_register FROM award WHERE foerder_schluessel='DE-BE-ZUW:8528'").fetchone()[0] == "vr_021507"
    reg = conn.execute("SELECT scheme, number, o.land FROM org_register r JOIN org o ON o.id=r.org_id "
                       "WHERE r.raw='vr_021507'").fetchone()
    assert tuple(reg) == ("BE_ZUWDB", "vr_021507", "BE"), tuple(reg)
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def _test_company_id():
    """eForms CompanyID: only real register numbers, USt-IDs or LEIs survive as empfaenger_id."""
    keep = {"DE275992867": "DE275992867", "DE 285 972 251": "DE285972251", "USt-ID: DE 1160 86 413": "DE116086413",
            "DE31 42 17 626": "DE314217626", "HRB 14122 Münster": "HRB 14122 Münster", "HRB245577B": "HRB245577B",
            "VR 1234": "VR 1234", "HRB 26997 (AG Köln)": "HRB 26997 (AG Köln)", "529900T8BM49AURSDO55": "529900T8BM49AURSDO55",
            # court named + Handelsregister A/B shorthand (Lead, fcfbfa3 review): a real register reference
            "AG Bochum B14528": "HRB 14528 (AG Bochum)", "Amtsgericht Essen, B 3051": "HRB 3051 (AG Essen)",
            "AG Bad Homburg A 123": "HRA 123 (AG Bad Homburg)", "Amtsgericht Bochum HRB 14528": "Amtsgericht Bochum HRB 14528"}
    drop = ["2", "6", "0", "1", "e20cd33e-5a73-4b49-8687-03bb2ff865c4", "Keine Angabe", "keine Angabe",
            "349/5999/9337", "B14528", "AG Bochum", "", None]
    for v, want in keep.items():
        assert valid_company_id(v) == want, (v, valid_company_id(v))
    for v in drop:
        assert valid_company_id(v) is None, (v, valid_company_id(v))
    from ingest import orglink
    assert orglink.parse_court_register(valid_company_id("AG Bochum B14528"))[0] == "HRB:14528:BOCHUM"
    assert common.parse_register(valid_company_id("AG Bochum B14528"))["number"] == "14528"


TESTS = [_test_berlin, _test_ted, _test_company_id]


def _run_tests():
    for t in TESTS:
        t()
        print("PASS", t.__name__)


SELFTEST_CFG = {"bz_limit": 15, "ted_keywords": ["Wohnungslosenhilfe"], "ted_max_pages": 1, "ted_limit": 12}


def _selftest(argv):
    """Small live sample into a scratch DB: python3 -m ingest.domains.funding_traeger --selftest --db /tmp/x.db
    Uses ingest.run's writer connection (lock + schema). No commit here: the runner owns the transaction,
    so the scratch file keeps only the schema; the rows are printed from the open transaction."""
    from ingest import run as runner
    if "--db" not in argv:
        raise SystemExit("--selftest needs --db /tmp/<scratch>.db (never data/atlas.db)")
    db_path = scratch_db_path(argv)
    conn = runner.open_db(db_path)
    conn.execute("BEGIN IMMEDIATE")
    conn.runner_txn = True
    try:
        res = run(conn, dict(SELFTEST_CFG))
        print(f"[{DOMAIN}] selftest rows={res['rows']}")
        for n in res["notes"].split(" | "):
            print(f"[{DOMAIN}]   {n}")
        for prefix in ("DE-BE-ZUW:%", "TED:%"):
            print(f"[{DOMAIN}] 3 sample award rows {prefix}")
            for r in conn.execute("SELECT a.foerder_schluessel, a.empfaenger, a.empfaenger_register, a.zuwendungsgeber, a.betrag, "
                                  "a.currency, a.haushaltsjahr, a.ort_land, a.quote, s.url FROM award a JOIN source s "
                                  "ON s.id=a.source_id WHERE a.foerder_schluessel LIKE ? ORDER BY random() LIMIT 3", (prefix,)):
                print("   ", dict(r))
        common.selftest_report(conn, DOMAIN, "org_register", "1=1", 3)
        bad = conn.execute("SELECT COUNT(*) FROM award WHERE source_id IS NULL OR currency IS NULL").fetchone()[0]
        assert bad == 0
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        conn.runner_txn = False
        conn.execute("ROLLBACK")
        conn.close()


def scratch_db_path(argv) -> Path:
    """--db value, refusing atlas.db, anything under data/ and the Lead worktree."""
    if "--db" not in argv or argv.index("--db") + 1 >= len(argv):
        raise SystemExit("--selftest needs --db /tmp/<scratch>.db (never data/atlas.db)")
    p = Path(argv[argv.index("--db") + 1]).expanduser().resolve()
    bad = (p == common.DB.resolve() or p.name.startswith("atlas.db") or "germany-atlas-lead" in str(p)
           or (common.ROOT / "data").resolve() in p.parents)
    if bad:
        raise SystemExit(f"refusing to use {p}: selftests run on a scratch DB only")
    return p


def _cli(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="python3 -m ingest.domains.funding_traeger", allow_abbrev=False,
                                 description="Worker tools. data/atlas.db is written only by "
                                             "`python3 -m ingest.run funding_traeger`.")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--test", action="store_true", help="offline unit tests (in-memory SQLite)")
    mode.add_argument("--dryrun", action="store_true", help="live fetch into in-memory SQLite, cache in /tmp")
    mode.add_argument("--selftest", action="store_true", help="live sample into a scratch DB (needs --db)")
    ap.add_argument("--db", help="--selftest: scratch DB path (never atlas.db)")
    ap.add_argument("--source", action="append", help="--dryrun: limit to one source (repeatable)")
    ap.add_argument("--out", help="--dryrun: JSONL output path")
    a = ap.parse_args(argv)
    if a.db and not a.selftest:
        ap.error("--db is only valid with --selftest")
    if (a.source or a.out) and not a.dryrun:
        ap.error("--source/--out are only valid with --dryrun")
    if a.test:
        _run_tests()
    elif a.dryrun:
        _dryrun([f"--source={s_}" for s_ in a.source or []] + ([f"--out={a.out}"] if a.out else []))
    else:
        if not a.db:
            ap.error("--selftest needs --db <scratch path>")
        _selftest(["--selftest", "--db", a.db])
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
