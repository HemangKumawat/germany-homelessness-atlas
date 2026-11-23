"""funding_officers -- named Vorstand / Geschäftsführung / board members of homelessness and welfare Träger.

Published professional roles only, each with organisation, source, date and a verbatim quote:

  lobbyregister  Lobbyregister des Deutschen Bundestages, API v2 (no open licence, facts only; public API key read from
                 LOBBYREGISTER_API_KEY in the environment or ~/.config/germany-atlas/env, never printed):
                 legalRepresentatives (with their published function) and entrustedPersons of
                 organisations whose entry concerns homelessness / welfare, or whose name matches a Träger in org.
  impressum      Impressum pages of Träger (legal notice duty, § 5 DDG / § 18 MStV). A curated seed list
                 names the page and the expected role lines; the reader fetches the live page (robots.txt
                 checked, 1 req/s, project User-Agent) and writes a person only when the quote is on the page.

  impressum_auto For every canonical, non-protected Träger with a known website (org.webseite, the winner
                 website printed in its TED notice, or SITE_SEEDS) that still lacks governance officers or a
                 court register number: the Impressum page (robots.txt checked, 1 req/s). Only when the page
                 names the organisation: Vorstand / Geschäftsführung lines (verbatim quote) and the court
                 register entry (Registergericht + VR/HRB/HRA/GnR/PR number, legal form must agree), each with
                 source and quote. A register number another canonical org already holds is never written
                 (reported as a duplicate candidate instead).

  itz            Initiative Transparente Zivilgesellschaft (ITZ): the public signatory list
                 (transparente-zivilgesellschaft.de, about 2,000 organisations, 20 per page) links each signatory's own
                 transparency page, which must publish "Name und Funktion wesentlicher Entscheidungsträger" (point 4 of
                 the ten ITZ items). For a canonical, non-protected Träger without governance officers whose name
                 (same legal form) is on the list exactly once: that page (robots.txt checked, 1 req/s), read with the
                 Impressum role-line parser, only when the page names the organisation. Same facts-only rules.

Org resolution (schema 5): hard ids first (common.resolve_org with the Lobbyregister number or the court
register), then an exact name of the same legal form that holds no different id; a name match is recorded as a
flagged name_fuzzy org_link, never as a hard id. canonical_org_id is never written here.

Never stored: contact details (e-mail, phone, address) of persons, birthdates, private addresses, or any
location of a protected shelter. Organisations whose name marks them as a protected shelter are skipped.
Handelsregister / Unternehmensregister are NOT read automatically (terms of use; see research/funding_officers.md).
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from urllib.parse import quote as urlquote, urlparse

from ingest import common
from ingest.domains.funding_traeger import court_numbers, org_compatible, resolve_or_find

DOMAIN = "funding_officers"
LR_API = "https://api.lobbyregister.bundestag.de/rest/v2/registerentries"
LR_PUBLISHER = "Deutscher Bundestag, Lobbyregister für die Interessenvertretung gegenüber dem Deutschen Bundestag und der Bundesregierung"
LR_LICENSE = ("Keine offene Lizenz: maschinenlesbare Veröffentlichung nach § 4 Abs. 2 LobbyRG "
              "(https://www.lobbyregister.bundestag.de/informationen-und-hilfe/open-data-1049716); Nutzungsbedingungen "
              "des Deutschen Bundestages (https://www.bundestag.de/impressum) behalten Rechte vor. Übernommen werden nur "
              "Fakten (Name, veröffentlichte Funktion, Registernummer, Stand) und eine kurze Belegstelle; kein Volltext. "
              "Quellenangabe: Deutscher Bundestag, Lobbyregister")
IMP_LICENSE = ("Pflichtangaben im Impressum (§ 5 DDG / § 18 MStV), veröffentlicht vom Träger; keine offene Lizenz, Rechte "
               "vorbehalten: nur Name und veröffentlichte Funktion (Fakten) und eine kurze zitierte Zeile (§ 51 UrhG) mit Quellenangabe")

PROTECTED_RE = re.compile(r"frauenh[äa]e?us|frauenschutz|schutzwohnung|zuflucht|gewaltschutz|"
                          r"h[äa]e?usliche[rn]? gewalt|schutzunterkunft|frauen helfen frauen|m(?:ä|ae)dchenh(?:ä|ae)?us|"
                          r"m(?:ä|ae)dchennotdienst|m(?:ä|ae)dchenschutz|inobhutnahme|"
                          r"anonyme[rn]?\s+(?:zuflucht|notaufnahme|notunterkunft|unterkunft|schutzstelle|wohnung)", re.I)


def protected_traeger(conn, oid, name: str | None) -> bool:
    """Träger of a protected shelter (Frauenhaus, Schutzwohnung, anonymous youth emergency place): the org is flagged,
    its name says so, or it runs a facility flagged is_protected. Its Impressum is never fetched (the address printed
    there is often the shelter itself); only Land-level facts from other sources are kept."""
    if name and PROTECTED_RE.search(name):
        return True
    if oid is None:
        return False
    r = conn.execute("SELECT is_protected FROM org WHERE id=?", (oid,)).fetchone()
    if r is not None and r[0]:
        return True
    return conn.execute("SELECT 1 FROM facility WHERE traeger_org_id=? AND is_protected=1 LIMIT 1", (oid,)).fetchone() is not None
HOMELESS_RE = re.compile(r"wohnungslos|obdachlos|wohnungsnotfall|kältehilfe|bahnhofsmission|"
                         r"straßensozialarbeit|housing first", re.I)
WELFARE_NAME_RE = re.compile(r"diakon|caritas|arbeiterwohlfahrt|\bawo\b|parit[äa]tisch|rotes kreuz|\bdrk\b|"
                             r"stadtmission|johanniter|malteser|heilsarmee|volkssolidarit|wohlfahrt|"
                             r"sozialdienst katholischer|\bskf\b|\bskm\b|wohnungslos|obdachlos|tafel deutschland", re.I)
LR_QUERIES = ["Wohnungslosenhilfe", "wohnungslos", "wohnungslose", "Obdachlosenhilfe", "obdachlos", "obdachlose",
              "Wohnungsnotfallhilfe", "Wohlfahrtspflege", "Wohlfahrtsverband", "Diakonie", "Caritas",
              "Arbeiterwohlfahrt", "Paritätische", "Rotes Kreuz", "Stadtmission", "Bahnhofsmission",
              "Sozialdienst katholischer", "Johanniter", "Malteser", "Heilsarmee", "Volkssolidarität"]



def rollenklasse(funktion: str) -> str:
    f = funktion.lower()
    if "geschäftsf" in f or "geschaeftsf" in f:
        return "geschaeftsfuehrung"
    if "aufsichtsrat" in f:
        return "aufsichtsrat"
    if "kuratori" in f:
        return "kuratorium"
    if "präsidium" in f or "praesidium" in f:
        return "praesidium"
    if "generalsekret" in f:
        return "geschaeftsfuehrung"
    if re.search(r"vorst|vorsitz|pr[äa]s[iy]?d|schatzmeister", f):
        return "vorstand"
    if "betraut" in f:
        return "lobby_kontakt"
    return "sonstige"


# Display order on org pages: governance first, Lobbyregister-entrusted persons last (Caritas alone has 100+).
ROLE_RANK = {"vorstand": 1, "geschaeftsfuehrung": 1, "praesidium": 2, "aufsichtsrat": 3, "kuratorium": 3,
             "sonstige": 4, "lobby_kontakt": 9}
ROLE_RANK_SQL = ("CASE rollenklasse " + " ".join(f"WHEN '{k}' THEN {v}" for k, v in ROLE_RANK.items())
                 + " ELSE 5 END")
GOVERNANCE = ("vorstand", "geschaeftsfuehrung", "praesidium", "aufsichtsrat", "kuratorium")


def role_rank(rolle: str | None) -> int:
    return ROLE_RANK.get(rolle or "", 5)


def person_name(p: dict) -> str:
    parts = [p.get("academicDegreeBefore"), p.get("firstName"), p.get("lastName"), p.get("academicDegreeAfter")]
    return " ".join(common.clean(x) for x in parts if common.clean(x))


_KIND_RE = [("ev", re.compile(r"(?i)\be\.\s?v\.?(?=\s|$|,)|eingetragener verein")),
            ("gmbh", re.compile(r"(?i)\bg?gmbh\b|gesellschaft mit beschr")),
            ("stiftung", re.compile(r"(?i)\bstiftung\b")),
            ("kdoer", re.compile(r"(?i)k\.?\s?d\.?\s?ö\.?\s?r|körperschaft des öffentlichen"))]


def legal_kind(name: str) -> str | None:
    """Coarse legal form from the printed name: 'Malteser Hilfsdienst e.V.' and 'Malteser Hilfsdienst gGmbH'
    share a name_norm but are different legal entities, so their officers must not be merged."""
    for k, rx in _KIND_RE:
        if rx.search(name or ""):
            return k
    return None


def _url(u):
    """Lobbyregister websites are often printed without a scheme ('www.awo.org')."""
    u = common.clean(u)
    return None if not u else (u if re.match(r"(?i)https?://", u) else "https://" + u)


def _ensure_org(conn, name: str, land, sid: int, *, lobby=None, register=None, link_kind=None, link_key=None,
                **extra) -> int | None:
    """Resolve first (Lobbyregister number / court register), then an exact name of the same legal form that
    holds no different id (recorded as a flagged name_fuzzy link), else a new org row (land as given)."""
    nn = common.name_norm(name)
    if not nn:
        return None
    oid, how = resolve_or_find(conn, name, nn, land, register=register, lobby=lobby, any_land=True)
    if oid is not None:
        if how == "name" and link_kind and link_key:
            common.link_org(conn, record_kind=link_kind, record_key=link_key, org_id=oid, method="name_fuzzy",
                            confidence=0.9, source_id=sid, record_name=name,
                            note="same normalised name and legal form, no conflicting register id")
        return oid
    key = how or nn
    vals = {k: v for k, v in extra.items() if v is not None}
    from ingest import orglink               # schema 6 (INGEST_CONTRACT §12): the legal form is part of the key
    oid = conn.execute("INSERT INTO org(name, name_norm, legal_form_norm, land, source_id, currency, aktualisiert_am"
                       + "".join(f", {k}" for k in vals) + ") VALUES (?,?,?,?,?,?,?" + ",?" * len(vals) + ") RETURNING id",
                       [name, key, orglink.legal_form_norm(name, vals.get("legal_form")), land, sid, "EUR", common.now(),
                        *vals.values()]).fetchone()[0]
    common.flag_new_org(conn, oid, sid)
    if lobby:
        conn.execute("INSERT OR IGNORE INTO org_register(org_id, scheme, court, number, raw, source_id) VALUES (?,?,?,?,?,?)",
                     (oid, "LobbyR", "", lobby, lobby, sid))
    return oid


def _add_person(conn, *, org_id, org_name, person, funktion, jahr, locator, sid, quote, stand, rolle=None) -> bool:
    """One org_person row (schema 4): name, published function, source, verbatim quote and Stand."""
    person = common.clean(person)
    funktion = common.clean(funktion)
    if not person or not funktion or len(person.split()) < 2 or not quote:
        return False
    common.upsert(conn, "org_person", {
        "org_id": org_id, "org_bezeichnung": org_name, "funktionstraeger": person,
        "funktionstraeger_norm": common.name_norm(person), "funktion": funktion,
        "rollenklasse": rolle or rollenklasse(funktion), "jahr": jahr, "locator": locator, "source_id": sid,
        "quote": quote, "stand": stand}, keys=["funktionstraeger_norm", "org_bezeichnung", "jahr", "funktion"])
    return True


# ------------------------------------------------------------------ Lobbyregister

class LobbyregisterAuthError(RuntimeError):
    """401/403 from the API: the key is wrong or revoked. Never swallowed: the run fails."""


_TRANSIENT = re.compile(r"HTTP (?:429|5\d\d)|fetch failed after|URLError|timed out|Connection", re.I)


def _lr_get(url: str, key: str, cfg: dict) -> dict:
    """One API GET with a gentle retry: up to lr_tries (3) attempts, each a single common.fetch (1 req/s floor),
    with lr_backoff seconds (10, 30) between them, for 429/5xx/network errors only. 401/403 raise
    LobbyregisterAuthError; anything still failing raises RuntimeError and is counted as a run error."""
    import time as _t
    tries = int(cfg.get("lr_tries", 3))
    backoff = list(cfg.get("lr_backoff", (10, 30)))
    last = None
    for attempt in range(tries):
        try:
            if cfg.get("lr_fixture") is not None:
                v = cfg["lr_fixture"][url]
                return v() if callable(v) else v
            robots_gate(url, cfg)          # the API host's robots.txt first, also for API paths
            return json.loads(common.fetch(url, domain=DOMAIN, headers={"Authorization": f"ApiKey {key}"},
                                           force=bool(cfg.get("force")), retries=1))
        except RobotsRefused:
            raise
        except RuntimeError as ex:
            if re.search(r"HTTP 40[13]\b", str(ex)):
                raise LobbyregisterAuthError(f"Lobbyregister API refused the key: {str(ex)[-80:]}") from ex
            if not _TRANSIENT.search(str(ex)):
                raise
            last = ex
            if attempt + 1 < tries:
                _t.sleep(backoff[min(attempt, len(backoff) - 1)] if backoff else 0)
    raise RuntimeError(f"after {tries} tries: {str(last)[-80:]}")


def lr_search(q: str, key: str, cfg: dict, max_pages: int | None = None) -> list[dict]:
    out, cursor, seen = [], None, set()
    for _ in range(int(max_pages or cfg.get("lr_max_pages", 5))):
        url = f"{LR_API}?q={urlquote(q)}&format=json" + (f"&cursor={urlquote(cursor)}" if cursor else "")
        d = _lr_get(url, key, cfg)
        out.extend(d.get("results") or [])
        nxt = d.get("cursor")
        if not nxt or nxt == cursor or nxt in seen:
            break
        seen.add(nxt)
        cursor = nxt
    return out


NOT_DOMESTIC_RE = re.compile(r"katastrophenhilfe|brot für die welt|\binternational\b", re.I)


def lr_relevant(entry: dict, org_norms) -> str | None:
    """Why an entry is read: org_match (same name_norm as a Träger in org), homelessness (its own
    activity description or its public allowances mention homelessness work), or welfare (name of a
    domestic welfare body). Lobbying *about* homelessness in regulatory projects does not count."""
    li = entry.get("lobbyistIdentity") or {}
    if li.get("identity") != "ORGANIZATION":
        return None                      # natural persons registered as lobbyists are never read
    name = li.get("name") or ""
    if PROTECTED_RE.search(name):
        return None
    kinds = org_norms.get(common.name_norm(name)) if isinstance(org_norms, dict) else (
        {None} if common.name_norm(name) in org_norms else None)
    if kinds is not None:            # legal form must agree: an e.V. entry is not the gGmbH of the same name
        k = legal_kind(name)
        if k is None or None in kinds or k in kinds:
            return "org_match"
    own = json.dumps({k: entry.get(k) for k in ("activitiesAndInterests", "publicAllowances")}, ensure_ascii=False)
    own = re.sub(r"(?i)bahnhofsmission", "", own)     # 'members include the Bahnhofsmission' (Allianz pro Schiene)
    if HOMELESS_RE.search(name) or HOMELESS_RE.search(own):
        return "homelessness"
    if WELFARE_NAME_RE.search(name) and not NOT_DOMESTIC_RE.search(name):
        return "welfare"
    return None


def _raw_quote(raw: str, p: dict) -> str | None:
    """Verbatim fragment of the archived JSON naming the person (and the function, when there is one).
    Tries every occurrence of the last name and prefers the JSON object that also carries the first
    name, so a namesake elsewhere in the entry is never quoted. Never includes contactDetails."""
    ln = '"lastName":' + json.dumps(p.get("lastName") or "", ensure_ascii=False)
    best = None
    i = raw.find(ln)
    while i >= 0:
        lo = raw.rfind("{", 0, i) + 1                      # the person object's opening brace
        hi = raw.find("}", i)
        nested = raw.find("{", i)
        if 0 <= nested < hi:
            hi = nested
        spans = [(i, i + len(ln))]
        for k in ("firstName", "academicDegreeBefore", "academicDegreeAfter", "function"):
            if p.get(k):
                frag = f'"{k}":' + json.dumps(p[k], ensure_ascii=False)
                j = raw.find(frag, lo, hi)
                if j >= 0:
                    spans.append((j, j + len(frag)))
        a, b = min(x for x, _ in spans), max(y for _, y in spans)
        q = raw[a:b]
        if "contactDetails" in q or "@" in q or "phone" in q.lower():
            q = raw[i:i + len(ln)]
        has_first = not p.get("firstName") or ('"firstName":' + json.dumps(p["firstName"], ensure_ascii=False)) in q
        if has_first:
            return q
        best = best or q
        i = raw.find(ln, i + 1)
    return best


def run_lobbyregister(conn, cfg: dict) -> dict:
    key = cfg.get("lr_key") or common.secret("LOBBYREGISTER_API_KEY")
    if not key:
        return {"rows": 0, "notes": "lobbyregister: LOBBYREGISTER_API_KEY not set (see research/funding_officers.md)",
                "sources": []}
    org_norms: dict[str, set] = {}
    for nn_, nm_ in conn.execute("SELECT name_norm, name FROM org WHERE canonical_org_id IS NULL AND is_protected=0"):
        org_norms.setdefault(common.name_norm(nm_) or nn_, set()).add(legal_kind(nm_))
    queries = [(q, None) for q in (cfg.get("lr_queries") or LR_QUERIES)]
    if cfg.get("lr_org_names", True):        # one page per Träger name: an exact entry ranks first
        names = [r[0] for r in conn.execute("SELECT DISTINCT name FROM org WHERE canonical_org_id IS NULL "
                                            "AND is_protected=0 ORDER BY id")]
        names = [n for n in names if not PROTECTED_RE.search(n)]
        if cfg.get("lr_org_limit"):          # no cap by default (every canonical Träger is queried once)
            names = names[: int(cfg["lr_org_limit"])]
        queries += [(n, 1) for n in names]
    found: dict[str, tuple[str, dict]] = {}
    failed = []
    for q, pages in queries:
        try:
            for e in lr_search(q, key, cfg, pages):
                why = lr_relevant(e, org_norms)
                if why and e.get("registerNumber"):
                    found.setdefault(e["registerNumber"], (why, e))
        except RuntimeError as ex:
            failed.append(f"q={q[:40]}: {str(ex)[-60:]}")
    limit = cfg.get("lr_limit")
    persons = orgs = 0
    why_count: dict[str, int] = {}
    for n, (regno, (why, _hit)) in enumerate(sorted(found.items())):
        if limit and n >= int(limit):
            break
        url = f"{LR_API}/{regno}?format=json"
        try:
            entry = _lr_get(url, key, cfg)
        except RuntimeError as ex:
            failed.append(f"{regno}: {str(ex)[-60:]}")
            continue
        raw = (cfg["lr_fixture_raw"][url] if cfg.get("lr_fixture_raw") else
               common.cached_path(DOMAIN, url).read_text(encoding="utf-8"))
        li = entry.get("lobbyistIdentity") or {}
        det = entry.get("registerEntryDetails") or {}
        name = common.clean(li.get("name"))
        as_of = (det.get("validFromDate") or "")[:10] or None
        page = det.get("detailsPageUrl") or f"https://www.lobbyregister.bundestag.de/suche/{regno}"
        sid = common.source_id_for(conn, url, DOMAIN, title=f"Lobbyregister {regno}: {name}",
                                   publisher=LR_PUBLISHER, license=LR_LICENSE)
        conn.execute("UPDATE source SET redistribute_fulltext=0 WHERE id=?", (sid,))
        addr = li.get("address") or {}
        org_id = _ensure_org(conn, name, None, sid, lobby=regno, link_kind="lobbyregister", link_key=regno,
                             ort=common.clean(addr.get("city")),
                             webseite=_url(next((w.get("website") for w in (li.get("contactDetails") or {}).get("websites") or []
                                           if isinstance(w, dict) and w.get("website")), None)))
        if org_id is None:
            continue
        orgs += 1
        why_count[why] = why_count.get(why, 0) + 1
        jahr = int(as_of[:4]) if as_of else None
        seen = set()
        for i, p in enumerate(li.get("legalRepresentatives") or []):
            nm = person_name(p)
            q = _raw_quote(raw, p)
            if not q:
                continue
            seen.add(common.name_norm(nm))
            persons += _add_person(
                conn, org_id=org_id, org_name=name, person=nm, funktion=p.get("function") or "Vertretungsberechtigte Person",
                jahr=jahr, sid=sid, quote=q, stand=as_of,
                locator=f"Lobbyregister {regno}, Version {det.get('version')}, Stand {as_of}: "
                        f"lobbyistIdentity.legalRepresentatives[{i}]; {page}")
        for i, p in enumerate(li.get("entrustedPersons") or []):
            nm = person_name(p)
            if common.name_norm(nm) in seen:
                continue
            q = _raw_quote(raw, p)
            if not q:
                continue
            persons += _add_person(
                conn, org_id=org_id, org_name=name, person=nm,
                funktion="Mit der Interessenvertretung betraute Person (Lobbyregister)", rolle="lobby_kontakt",
                jahr=jahr, sid=sid, quote=q, stand=as_of,
                locator=f"Lobbyregister {regno}, Version {det.get('version')}, Stand {as_of}: "
                        f"lobbyistIdentity.entrustedPersons[{i}]; {page}")
    if failed and not found and not cfg.get("lr_fixture"):
        raise RuntimeError(f"lobbyregister: every query failed ({len(failed)}), e.g. {failed[:2]}")
    if found and persons == 0 and not cfg.get("lr_fixture"):
        raise RuntimeError(f"lobbyregister: {len(found)} relevant entries but no person written; failed: {failed[:3]}")
    notes = ((f"RUN ERRORS {len(failed)} (Lobbyregister requests still failing after retries): {failed[:5]} | " if failed else "")
             + f"lobbyregister: {len(queries)} queries, {len(found)} relevant entries {why_count}, {orgs} orgs, "
             f"{persons} persons; failed {len(failed)}: {failed[:3]}")
    return {"rows": persons, "notes": notes, "errors": [f"lobbyregister {f}" for f in failed],
            "sources": [(f"{LR_API}/<registerNumber>?format=json", LR_LICENSE)]}


# ------------------------------------------------------------------ Impressum

# Curated seeds: the page, the organisation as named there, and the role lines expected on it. A person
# is written only if `quote` (whitespace-normalised) is on the live page; stale seeds are reported.
IMPRESSUM_SEEDS = [
    {"org": "Verein für Berliner Stadtmission", "land": "BE", "url": "https://www.berliner-stadtmission.de/impressum",
     "people": [("Dr. Christian Ceconi", "Theologischer Vorstand", "Theologischer Vorstand Dr. Christian Ceconi"),
                ("Dragana Duric", "Kaufmännische Vorständin", "Kaufmännische Vorständin Dragana Duric")]},
    {"org": "GEBEWO pro gGmbH", "land": "BE", "url": "https://gebewo.berlin/impressum",
     "people": [("Ekkehard Hayner", "Geschäftsführung", "GEBEWO pro gGmbH Vertreten durch die Geschäftsführung: Ekkehard Hayner & Madeleine Osho-Ogun"),
                ("Madeleine Osho-Ogun", "Geschäftsführung", "GEBEWO pro gGmbH Vertreten durch die Geschäftsführung: Ekkehard Hayner & Madeleine Osho-Ogun")]},
    {"org": "GEBEWO -Soziale Dienste- Berlin gGmbH", "land": "BE", "url": "https://gebewo.berlin/impressum",
     "people": [("Ekkehard Hayner", "Geschäftsführung", "GEBEWO -Soziale Dienste- Berlin gGmbH Vertreten durch die Geschäftsführung: Ekkehard Hayner & Madeleine Osho-Ogun"),
                ("Madeleine Osho-Ogun", "Geschäftsführung", "GEBEWO -Soziale Dienste- Berlin gGmbH Vertreten durch die Geschäftsführung: Ekkehard Hayner & Madeleine Osho-Ogun")]},
    {"org": "Gangway e. V.", "land": "BE", "url": "https://gangway.de/ueber-uns/impressum/",
     "people": [("Elvira Berndt", "Geschäftsführung", "Geschäftsführung: Elvira Berndt")]
     + [(n, "Vorstand", "Vorstand : Katrin Toptschian, Anne Lersch, Frank Finschow, Thomas Mücke, Dr. Peter Schruth")
        for n in ("Katrin Toptschian", "Anne Lersch", "Frank Finschow", "Thomas Mücke", "Dr. Peter Schruth")]},
    {"org": "Sozialdienst katholischer Frauen e. V. Berlin", "land": "BE", "url": "https://skf-berlin.de/impressum/",
     "people": [("Rita Brandt", "Vorstand", "vertreten durch den Vorstand. Rita Brandt Vorstand")]},
    {"org": "Arbeiterwohlfahrt Berlin Spree-Wuhle e. V.", "land": "BE", "url": "https://www.awo-spree-wuhle.de/impressum/",
     "people": [("C. Meyerdierks", "Kreisvorsitzender", "Kreisvorsitzender: C. Meyerdierks"),
                ("H. Langkau", "Geschäftsführer", "Geschäftsführer: H. Langkau")]},
    {"org": "Deutscher Caritasverband e. V.", "land": None, "url": "https://www.caritas.de/impressum",
     "people": [("Eva Maria Welskop-Deffaa", "Präsidentin", "Dem Vorstand gehören an: Präsidentin Eva Maria Welskop-Deffaa",
                 "Präsidentin (Vorstand)"),
                ("Dr. Susanne Pauser", "Vorständin Personal und Digitales", "Vorständin Personal und Digitales Dr. Susanne Pauser"),
                ("Dr. Oliver Müller", "Vorstand Internationales, Migration und Katastrophenhilfe", "Vorstand Internationales, Migration und Katastrophenhilfe Dr. Oliver Müller"),
                ("Dr. Friedrich von Schönfeld", "Vorstand Finanzen und Recht", "Vorstand Finanzen und Recht Dr. Friedrich von Schönfeld")]},
    {"org": "Bundesarbeitsgemeinschaft Wohnungslosenhilfe e. V.", "land": "BE", "url": "https://www.bagw.de/de/impressum",
     "people": [("Susanne Hahmann", "Vertretungsberechtigter Vorstand", "Vertretungsberechtigter Vorstand: Susanne Hahmann (Vorsitzende)",
                 "Vertretungsberechtigter Vorstand (Vorsitzende)"),
                ("Sabine Bösing", "Geschäftsführerin", "Sabine Bösing (Geschäftsführerin)")]},
    {"org": "Arbeiterwohlfahrt Bundesverband e. V.", "link_org": "AWO Bundesverband e.V.", "land": None, "url": "https://awo.org/impressum/",
     "people": [("Claudia Mandrysch", "Vorstand", "Vorstand Claudia Mandrysch, Dr. Marvin Deversi"),
                ("Dr. Marvin Deversi", "Vorstand", "Vorstand Claudia Mandrysch, Dr. Marvin Deversi"),
                ("Kathrin Sonnenholzner", "Vorsitzende des Präsidiums", "Vorsitzende des Präsidiums Kathrin Sonnenholzner, Michael Groß"),
                ("Michael Groß", "Vorsitzende des Präsidiums", "Vorsitzende des Präsidiums Kathrin Sonnenholzner, Michael Groß",
                 "Vorsitzender des Präsidiums")]},
    {"org": "Diakonie Deutschland, Evangelisches Werk für Diakonie und Entwicklung e.V.", "land": None,
     "url": "https://www.diakonie.de/impressum",
     "people": [("Rüdiger Schuch", "Vorsitzender", "Das Werk wird durch den Vorstand vertreten. Er besteht aus folgenden Mitgliedern Vorsitzender: Präsident Pfarrer Rüdiger Schuch",
                 "Vorsitzender des Vorstands, Präsident"),
                ("Dr. Dagmar Pruin", "stellvertretende Vorsitzende", "Das Werk wird durch den Vorstand vertreten. Er besteht aus folgenden Mitgliedern Vorsitzender: Präsident Pfarrer Rüdiger Schuch stellvertretende Vorsitzende: Präsidentin Pfarrerin Dr. Dagmar Pruin",
                 "stellvertretende Vorsitzende des Vorstands, Präsidentin"),
                ("Dr. Jörg Kruttschnitt", "Vorstand", "Das Werk wird durch den Vorstand vertreten. Er besteht aus folgenden Mitgliedern Vorsitzender: Präsident Pfarrer Rüdiger Schuch stellvertretende Vorsitzende: Präsidentin Pfarrerin Dr. Dagmar Pruin Dr. Jörg Kruttschnitt",
                 "Mitglied des Vorstands")]},
]

# ---- run-time robots.txt gate: the counts_law pattern (Lead review 2026-11-23), parser and matcher reused from
# ingest.domains.counts_law. Every network request of the Impressum readers goes through gated_fetch(). Before the
# first request to a host its robots.txt is read live (never from the disk cache) with the project UA, and the
# gate fails closed: a disallowed path, or a robots.txt that cannot be read (network error, 5xx, 401/403, redirect
# off the host) means nothing is fetched from that host. A 404/410 robots.txt is "no rules" (RFC 9309), an HTML
# page instead of robots.txt is "no rules". Crawl-delay is honoured per host on top of the 1 req/s floor of
# common.fetch (one process-wide request at a time, so at most 1 req/s per host). Cached pages need no request.
_ROBOTS: dict = {}       # "scheme://host" -> (rules, crawl_delay) | reason text (host skipped)
_HOST_LAST: dict = {}    # "scheme://host" -> monotonic time of the last request


class RobotsRefused(RuntimeError):
    """robots.txt disallows the path or could not be read; nothing was fetched."""


def _origin(url: str) -> str:
    u = urlparse(url)
    return f"{u.scheme}://{u.netloc}"


def _robots_for(origin: str, cfg: dict):
    import time as _t
    import urllib.error
    import urllib.request
    from ingest.domains.counts_law import _robots_parse
    if origin in _ROBOTS:
        return _ROBOTS[origin]
    fx = cfg.get("robots_fixture")
    if fx is not None:                       # offline tests: origin -> robots.txt text | HTTP status | "error"
        v = fx.get(origin, 404)
        if isinstance(v, str) and v != "error":
            _ROBOTS[origin] = _robots_parse(v)
        elif v in (404, 410):
            _ROBOTS[origin] = ([], None)
        else:
            _ROBOTS[origin] = f"robots.txt unreadable ({v})"
        return _ROBOTS[origin]
    url = origin + "/robots.txt"
    common._polite_wait()
    try:
        req = urllib.request.Request(url, headers={"User-Agent": common.UA, "Accept": "text/plain,*/*"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            final = resp.geturl()
            if urlparse(final).netloc.lower().removeprefix("www.") != urlparse(origin).netloc.lower().removeprefix("www."):
                raise RobotsRefused(f"robots.txt redirected off the site to {final}")
            body = resp.read(512 * 1024)
            ctype = resp.headers.get("Content-Type", "")
        try:
            text = body.decode("utf-8")
        except UnicodeDecodeError:
            text = body.decode("latin-1")
        if "html" in ctype.lower() or text.lstrip()[:1] == "<":
            _ROBOTS[origin] = ([], None)
            common._log(DOMAIN, url, 200, len(body), f"no robots.txt (HTML page at {final}): no rules")
        else:
            _ROBOTS[origin] = _robots_parse(text)
            common._log(DOMAIN, url, 200, len(body), "robots.txt read")
    except urllib.error.HTTPError as e:
        if e.code in (404, 410):
            _ROBOTS[origin] = ([], None)
            common._log(DOMAIN, url, e.code, 0, "no robots.txt: no rules (RFC 9309)")
        else:
            _ROBOTS[origin] = f"robots.txt unreadable (HTTP {e.code})"
    except RobotsRefused as e:
        _ROBOTS[origin] = str(e)
    except Exception as e:  # noqa: BLE001  network/TLS/timeouts: fail closed
        _ROBOTS[origin] = f"robots.txt unreadable ({e!r:.120})"
    _HOST_LAST[origin] = _t.monotonic()
    return _ROBOTS[origin]


def robots_ok(url: str, cfg: dict) -> bool:
    """True only when the host's robots.txt was read (or is absent) and allows this path for the project UA."""
    from ingest.domains.counts_law import _robots_allows
    if cfg.get("imp_fixture") is not None and cfg.get("robots_fixture") is None:
        return True                          # offline parser tests without a robots fixture
    robots = _robots_for(_origin(url), cfg)
    if isinstance(robots, str):
        return False
    u = urlparse(url)
    return _robots_allows(robots[0], (u.path or "/") + (f"?{u.query}" if u.query else ""))


def robots_gate(url: str, cfg: dict | None = None, *, domain: str = DOMAIN, cached_ok: bool = True) -> None:
    """Every request of the funding modules (pages, APIs, POST searches, probes) passes here first: robots.txt of
    the host is read (once per run, fail-closed) BEFORE any other request to that host; a disallowed path raises
    RobotsRefused and is never requested. A response already in the disk cache needs no request (cached_ok)."""
    cfg = cfg or {}
    if cached_ok and not cfg.get("force") and common.cached_path(domain, url) is not None:
        return
    if not robots_ok(url, cfg):
        common._log(domain, url, "robots-skip", 0, str(_ROBOTS.get(_origin(url)))[:200])
        raise RobotsRefused(f"robots.txt refuses {url}")


def gated_fetch(url: str, cfg: dict, **kw) -> bytes:
    """The only way the Impressum readers fetch a page: fixture, disk cache, or robots-gated live request."""
    import time as _t
    if cfg.get("imp_fixture") is not None:
        if not robots_ok(url, cfg):
            raise RobotsRefused(f"robots.txt refuses {url}")
        return cfg["imp_fixture"][url]       # KeyError = page missing
    if common.cached_path(DOMAIN, url) is not None:
        return common.fetch(url, domain=DOMAIN, **kw)
    if not robots_ok(url, cfg):
        common._log(DOMAIN, url, "robots-skip", 0, str(_ROBOTS.get(_origin(url)))[:200])
        raise RobotsRefused(f"robots.txt refuses {url}")
    origin = _origin(url)
    robots = _ROBOTS.get(origin)
    delay = robots[1] if isinstance(robots, tuple) else None
    if delay:
        gap = _t.monotonic() - _HOST_LAST.get(origin, 0.0)
        if gap < delay:
            _t.sleep(delay - gap)
    try:
        return common.fetch(url, domain=DOMAIN, **kw)
    finally:
        _HOST_LAST[origin] = _t.monotonic()


def _ws(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


SHY = "\u00ad"                              # soft hyphen (&shy;): invisible, but it splits words in the page text


def deshy(lines: str) -> str:
    """The page text with soft hyphens removed: parsers and name matching run on this view."""
    return lines.replace(SHY, "")


def verbatim_quote(quote: str, lines: str) -> str | None:
    """The quote as it stands in the archived page text (soft hyphens kept), so verify G7 finds it verbatim;
    None when it is not there."""
    page = _ws(lines)
    if SHY not in page:
        return quote if quote in page else None
    m = re.search((SHY + "?").join(re.escape(c) for c in quote), page)
    return m.group(0) if m else None


def name_on_page(person: str, lines: str) -> bool:
    """Every name token (degrees/initials excepted) occurs as printed: a name split by a soft hyphen is skipped,
    because the stored name must be findable in the archived text (verify G7)."""
    low = lines.lower()
    return all(t.lower() in low for t in person.split() if not t.endswith("."))


def zuwdb_holder(conn, raw: str):
    """Canonical org holding the Berlin Zuwendungsdatenbank Registrierungsnummer that equals this Berlin court register:
    'VR 24148 B (AG Charlottenburg)' = 'vr_024148' (leading zeros and the B suffix normalised). Only AG Charlottenburg
    (Berlin's one register court) qualifies. Raises ValueError if two canonical orgs hold it."""
    from ingest import orglink
    key = orglink.parse_court_register(raw)
    if not key:
        return None
    sch, num, court = key[0].split(":")
    if court != "CHARLOTTENBURG":
        return None
    hits = set()
    for oid, n in conn.execute("SELECT org_id, number FROM org_register WHERE scheme='BE_ZUWDB' "
                               "UNION SELECT id, register_id FROM org WHERE register_id IS NOT NULL"):
        m = re.fullmatch(r"(?i)([a-zäöü]{1,5})_(\d+)", str(n or "").strip())
        if m and m.group(1).upper() == sch.upper() and int(m.group(2)) == int(num):
            hits.add(common.canonical_org(conn, oid))
    if len(hits) > 1:
        raise ValueError(f"{raw}: Zuwendungsdatenbank number held by {sorted(hits)}")
    return next(iter(hits), None)


def register_holder(conn, raw: str):
    """(org_id, how) for a court register printed on a page: how='register' (hard id already held),
    'zuwdb' (the same number as a Berlin Zuwendungsdatenbank Registrierungsnummer), (None, None) if nobody
    holds it, (-1, 'ambiguous') if two orgs do."""
    try:
        hit = common.resolve_org(conn, register=raw)
        if hit:
            return hit, "register"
        hit = zuwdb_holder(conn, raw)
        return (hit, "zuwdb") if hit else (None, None)
    except ValueError:
        return -1, "ambiguous"


def page_register(text: str, pos: int, name: str, legal=None):
    """(register dict | None, status) for the organisation named at offset pos: the entry nearest after the name
    whose scheme fits the legal form; status ok | none | form_mismatch | ambiguous."""
    from ingest import orglink
    kind = orglink.legal_kind(name, legal)
    regs = [r for r in impressum_registers(text) if r["pos"] >= pos - 400]
    ok_regs = [r for r in regs if kind not in KIND_SCHEMES or r["scheme"] in KIND_SCHEMES[kind]]
    if regs and not ok_regs:
        return None, "form_mismatch"
    keys = {orglink.parse_court_register(r["raw"])[0] for r in ok_regs if orglink.parse_court_register(r["raw"])}
    if len(keys) > 1:
        ok_regs = sorted(ok_regs, key=lambda r: r["pos"])[:1]
        nxt = sorted(x["pos"] for x in regs if x is not ok_regs[0])
        if nxt and nxt[0] - ok_regs[0]["pos"] < 300:
            return None, "ambiguous"
    return (ok_regs[0], "ok") if ok_regs else (None, "none")


def link_by_register(conn, *, oid, name, r, url, sid, today, record_kind, record_key, how=None) -> None:
    """Write the page's court register on the org (org_register, org.register_id if empty) and record the link
    with method register_id (never name_fuzzy: the register line proves the organisation)."""
    from ingest import orglink
    num = re.sub(r"\D", "", r["number"])
    court = orglink.court_norm(r["court"])
    conn.execute("INSERT OR IGNORE INTO org_register(org_id, scheme, court, number, raw, source_id) VALUES (?,?,?,?,?,?)",
                 (oid, r["scheme"], court, num, r["raw"], sid))
    conn.execute("UPDATE org SET register_id=? WHERE id=? AND register_id IS NULL", (r["raw"], oid))
    key = orglink.parse_court_register(r["raw"])
    extra = " = Registrierungsnummer der Berliner Zuwendungsdatenbank" if how == "zuwdb" else ""
    common.link_org(conn, record_kind=record_kind, record_key=record_key, org_id=oid, method="register_id",
                    confidence=1.0, source_id=sid, record_name=name, id_value=key[0] if key else None,
                    note=f"Impressum (abgerufen {today}): \u201e{r['quote'][:300]}\u201c{extra}")


def run_impressum(conn, cfg: dict) -> dict:
    seeds = cfg.get("imp_seeds") or IMPRESSUM_SEEDS
    persons = orgs = by_register = 0
    stale, blocked = [], []
    today = common.now()[:10]
    for seed in seeds:
        url = seed["url"]
        if PROTECTED_RE.search(seed["org"]):
            continue
        try:
            raw = gated_fetch(url, cfg)
        except RobotsRefused:
            blocked.append(url)
            continue
        except RuntimeError as ex:
            stale.append(f"{url}: {str(ex)[-40:]}")
            continue
        page_lines = common.html_to_text(raw)
        text = _ws(page_lines)
        sid = common.source_id_for(conn, url, DOMAIN, title=f"Impressum {seed['org']}", publisher=seed["org"],
                                   license=IMP_LICENSE)
        conn.execute("UPDATE source SET redistribute_fulltext=0 WHERE id=?", (sid,))
        oname = seed.get("link_org") or seed["org"]
        web = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
        link_key = url + "#" + seed["org"]
        # the page's own register line proves the organisation: resolve and link by register, not by name
        dtext = _ws(deshy(page_lines))
        pos = _page_names_org(dtext, seed["org"])
        pos = pos if pos >= 0 else _page_names_org(dtext, oname)
        reg, _status = page_register(dtext, pos, oname) if pos >= 0 else (None, "not named")
        holder, how = register_holder(conn, reg["raw"]) if reg else (None, None)
        if pos < 0:
            # page prints the org under another spelling: its single register line still proves identity when
            # that register (or the equal Berlin ZUWDB number) is already held by the org of this name
            kind = legal_kind(oname)
            cands = [r for r in impressum_registers(dtext) if kind not in KIND_SCHEMES or r["scheme"] in KIND_SCHEMES[kind]]
            named = common.find_org(conn, oname, seed.get("land"), any_land=seed.get("land") is None)["org_id"]
            if len({r["raw"] for r in cands}) == 1 and named:
                h, hw = register_holder(conn, cands[0]["raw"])
                if h not in (None, -1) and h == common.canonical_org(conn, named):
                    reg, holder, how = cands[0], h, hw
        if reg and holder == -1:
            reg = None                     # held by two orgs: a G11 case for the Lead, fall back to the name
        if reg and holder and legal_kind(oname) not in (None, legal_kind(conn.execute(
                "SELECT name FROM org WHERE id=?", (holder,)).fetchone()[0])) and legal_kind(conn.execute(
                "SELECT name FROM org WHERE id=?", (holder,)).fetchone()[0]) is not None:
            reg = holder = None            # register holder has another legal form: do not trust the line
        if reg:
            org_id = holder or _ensure_org(conn, oname, seed.get("land"), sid, register=reg["raw"], webseite=web)
            link_by_register(conn, oid=org_id, name=oname, r=reg, url=url, sid=sid, today=today,
                             record_kind="impressum", record_key=link_key, how=how)
            by_register += 1
        else:
            org_id = _ensure_org(conn, oname, seed.get("land"), sid, link_kind="impressum", link_key=link_key,
                                 webseite=web)
        n_before = persons
        for person, funktion, quote, *was in seed["people"]:
            if _ws(quote) not in text or person.split()[-1] not in quote or funktion not in quote:
                stale.append(f"{seed['org']}: '{quote[:40]}' not on page (or label '{funktion}' not in the quote)")
                continue
            if was:                        # relabel a row written under an older, non-verbatim label in place
                conn.execute("UPDATE OR IGNORE org_person SET funktion=?, rollenklasse=?, quote=?, locator=? "
                             "WHERE funktionstraeger_norm=? AND org_bezeichnung=? AND funktion=?",
                             (funktion, rollenklasse(funktion), _ws(quote),
                              f"Impressum, Zeile '{_ws(quote)[:120]}' (abgerufen {today})",
                              common.name_norm(person), seed["org"], was[0]))
            persons += _add_person(conn, org_id=org_id, org_name=seed["org"], person=person, funktion=funktion,
                                   jahr=int(today[:4]), sid=sid, quote=_ws(quote), stand=today,
                                   locator=f"Impressum, Zeile '{_ws(quote)[:120]}' (abgerufen {today})")
        orgs += persons > n_before
    notes = (f"impressum: {len(seeds)} seed pages, {orgs} orgs ({by_register} linked by the page's register line), "
             f"{persons} persons; robots-blocked {len(blocked)}; "
             f"stale {len(stale)}: {stale[:4]}")
    return {"rows": persons, "notes": notes, "sources": [("<Träger-Impressum-URL>", IMP_LICENSE)]}


# ------------------------------------------------------------------ Impressum, automatic (officers + court register)

# Curated starting pages for Träger whose website is in no source row (found by hand; each is still checked live:
# robots.txt, the page must name the organisation, every person/register value must be on the page).
# key: org name as in org.name (exact); value: homepage or Impressum URL.
SITE_SEEDS: dict[str, str] = {
    # join_gaps batch 2026-11-23 (official sites found by search; the page must still name the org)
    "European Homecare GmbH": "https://www.eu-homecare.com/impressum",
    "Soziales Zentrum e. V.": "https://www.soziales-zentrum.org/",
    "Heinzelmännchen Gebäudereinigung GmbH": "https://hzm.de/reinigung/impressum/",
    "BEWA Security GmbH": "https://www.bewa-security.info/impressum",
    "Primus Service GmbH": "https://www.primus-service.de/impressum",
    "MSM Security & Service GmbH": "https://msm-security-service.de/impressum/",
    "AWO KV Oberlausitz e.V.": "https://awo-oberlausitz.de/impressum/",
    "Deutsches Rotes Kreuz Kreisverband Hochtaunus e. V.": "https://www.drk-hochtaunus.de/service/impressum.html",
    "ASB Neubrandenburg gGmbH": "https://www.asb-nb-mst.de/",
    "Solidarische Psychosoziale Hilfe Hamburg e. V.": "https://www.spsh.de/",
    "DRK Kreisverband Schaumburg e.V.": "https://www.drk-schaumburg.de/impressum",
    "AQtivus gGmbH": "https://www.aqtivus.de/",
    "Allgäu Medical Service GmbH": "https://www.allgaeu-medical.de/",
    "Be an Angel e. V.": "https://www.be-an-angel.de/",
    "Berliner Help Stiftung": "https://www.berliner-help-stiftung.de/",
    "Berliner Stadtmission e. V.": "https://www.berliner-stadtmission.de/",
    "Caritasverband für die Diözese Regensburg e.V.": "https://www.caritas-regensburg.de/impressum",
    "Complete Dienstleistung GmbH": "https://www.complete-dienstleistung.de/",
    "Defensio Ignis GmbH": "https://www.defensio-ignis.de/",
    "Deutsches Rotes Kreuz Kreisverband Hamburg-Harburg e.V.": "https://www.drk-harburg.hamburg/service/impressum.html",
    "Diakoniewerk Simeon gGmbH": "https://www.diakoniewerk-simeon.de/",
    "Diakoniewerk im nördlichen Mecklenburg gGmbH": "https://www.diakoniewerk-gvm.de/",
    "Dornahof Integrationsbetriebe gGmbH": "https://www.dornahof.de/",
    "EWIBO GmbH": "https://www.ewibo.de/",
    "Ev. Jugendhilfe Verein e. V.": "https://www.jugendhilfeverein.de/",
    "Fair Facility Management GmbH & Co KG": "https://fair-facility.de/impressum/",
    "HILFE-FÜR-JUNGS e. V.": "https://www.hilfefuerjungs.de/",
    "Hero Zukunft GmbH": "https://www.herozukunft.de/",
    "Human-Care GmbH": "https://www.human-care.eu/footer/impressum/",
    "Jonas Better Place GmbH": "https://www.jonasbetterplace.de/",
    "Jugendbildung Hamburg gGmbH": "https://www.jugendbildung-hamburg.de/",
    "Jugendhilfe e.V.": "https://www.jugendhilfe.de/",
    "Kreuzberger Kinderstiftung gAG": "https://www.kreuzberger-kinderstiftung.de/",
    "Lawaetz-wohnen & leben gGmbH": "https://www.lawaetz-ggmbh.de/impressum/",
    "Lebensnähe gGmbH": "https://www.lebensnaehe.de/",
    "Mook wat e.V.": "https://mookwat.de/kontakt/impressum/",
    "Neue Chance": "https://www.neuechance.de/",
    "PRISOD Wohnheimbetriebs GmbH": "https://www.prisod.de/",
    "PaSo gGmbH": "https://www.paso-ggmbh.de/impressum/index.php",
    "PulsM GmbH": "https://www.pulsm.de/",
    "Rullko Großeinkauf GmbH & Co. KG": "https://www.rullko.de/",
    "SKM Augsburg e. V.": "https://www.skm-augsburg.de/",
    "Schwulenberatung Berlin gGmbH": "https://www.schwulenberatungberlin.de/",
    "Soziale Arbeit Mittelmark e.V.": "https://www.soziale-arbeit-mittelmark.de/",
    "Sozialverein Friedrichshain e. V.": "https://www.sozialverein-friedrichshain.de/",
    "Straßenkinder e. V.": "https://www.strassenkinder.de/",
    "Tamaja Betreuung und Beherbergung gemeinnützige GmbH": "https://www.tamaja.de/",
    "Teen Challenge Berlin e. V.": "https://www.teenchallengeberlin.de/",
    "Unter Druck e. V.": "https://www.unter-druck.de/",
    "Volkssolidarität Berlin e. V.": "https://www.volkssolidaritaet-berlin.de/",
    "Wäscherei Kellner GmbH": "https://www.waescherei-kellner.de/",
    "Zeppelin Rental GmbH": "https://www.zeppelin-rental.de/",
    "jhj Hamburg e.V": "https://www.jhj-hamburg.de/",
    "tandem BTL gGmbH": "https://www.tandembtl.de/",
}

_IMP_LINK = re.compile(r"""<a\b[^>]*?href\s*=\s*["']([^"'#]+)["'][^>]*>(.*?)</a>""", re.I | re.S)
_NAME_TOK = r"[A-ZÄÖÜ][a-zäöüßéèáàçñ]+(?:-[A-ZÄÖÜ][a-zäöüßéèáàçñ]+)?"
_TITLE = r"(?:(?:Dr\.|Prof\.|Dipl\.-[A-Za-zäöü]+\.?|Pfarrer(?:in)?|Pastor(?:in)?|Diakon(?:in)?)\s+)*"
# names never run across a line break (html_to_text keeps block elements on their own lines)
_PERSON = (_TITLE.replace(r"\s+", r"[ \t]+") + _NAME_TOK + r"(?:[ \t]+(?:von|van|de|zu|von der|von dem)(?=[ \t]))?(?:[ \t]+"
           + _NAME_TOK + r"){1,2}")
_SEP = r"(?:[ \t]*(?:,|;|&|\bund\b|\bsowie\b)[ \t]*\n?[ \t]*|[ \t]*\n[ \t]*)"
_PERSONS = _PERSON + r"(?:" + _SEP + _PERSON + r"){0,7}"
_ROLE = (r"(?P<role>(?:Kaufmännische[rn]?\s+|Theologische[rn]?\s+|Hauptamtliche[rn]?\s+|Vertretungsberechtigte[rn]?\s+)?"
         r"(?:Geschäftsführer(?:innen|in)?|Geschäftsführung|Vorstandsvorsitzende[rn]?|Vorsitzende[rn]? des Vorstand(?:e)?s|"
         r"Vorständin|Vorstände|Vorstand|Vorstandsmitglieder|Präsident(?:in)?|Aufsichtsratsvorsitzende[rn]?|"
         r"Vorsitzende[rn]? des Aufsichtsrat(?:e)?s))")
_ROLE_LINE = re.compile(r"(?:vertreten\s+durch\s+(?:den|die|das)?\s*)?" + _ROLE + r"(?:\s*\([^)]{1,40}\))?\s*:\s*(?P<names>" + _PERSONS + r")")
_VERTRETEN = re.compile(r"vertreten\s+durch\s*:?\s*(?:den|die)?\s*(?P<names>" + _PERSONS + r")\s*\(\s*" + _ROLE + r"\s*\)")
_NOT_NAME = {"Straße", "Strasse", "Telefon", "Fax", "Mail", "Sitz", "Amtsgericht", "Registergericht", "Vereinsregister",
             "Handelsregister", "Verantwortlich", "Inhalt", "Kontakt", "Steuernummer", "Umsatzsteuer", "Datenschutz",
             "Haftung", "Postfach", "Deutschland", "Verein", "Gesellschaft", "Stiftung", "Diakonie", "Caritas", "Vorstand",
             "Geschäftsführer", "Geschäftsführerin", "Geschäftsführung", "Vorsitzende", "Vorsitzender", "Registernummer",
             "Register", "Impressum", "Anschrift", "Adresse", "Internet", "Ust", "Berlin", "Hamburg", "München", "Köln",
             "Gemeinnützige", "Landesverband", "Kreisverband", "Bezirksverband", "Bundesverband", "Mitglied",
             "Mitglieder", "Aufsichtsrat", "Präsident", "Präsidentin", "Leitung", "Bereich", "Team", "Geschäftsstelle",
             "Evangelische", "Katholische", "Arbeiterwohlfahrt", "Rotes", "Kreuz", "Hilfe", "Hilfswerk", "Services",
             "Service", "Gmb", "Sozial", "Soziale", "Dienste", "Wohnen", "Hotel", "Herr", "Frau", "Und", "Finanzamt",
             "Kontaktaufnahme", "Kontaktdaten", "Steuer", "Hinweis", "Bankverbindung", "Konto", "Ansprechpartner",
             "Redaktion", "Verantwortliche", "Verantwortlicher", "Presse", "Gericht", "Amtsgerichts", "Bildnachweis",
             "Fotos", "Gestaltung", "Webdesign", "Identifikationsnummer", "Zentrale", "Geschäftsführende",
             "Geschäftsführender", "Stellvertretende", "Stellvertretender", "Kaufmännischer", "Kaufmännische",
             "Theologischer", "Theologische", "Vorstände", "Vorständin", "Aufsichtsrats", "Aufsichtsratsvorsitzender"}
_REGNO = re.compile(r"(?<![A-Za-z])(VR|HRB|HRA|GnR|PR|HR[\s-]?[AB]|Vereinsregister(?:nummer)?)\s*:?\s*(?:-?\s*Nr\.?\s*:?\s*)?(\d{1,6})"
                    r"(?:\s+([A-Z]{1,2})(?![A-Za-z]))?")
# number printed before the scheme: 'Registereintragung: 206124 HRB - Amtsgericht Walsrode' (court must follow)
_REGNO_REV = re.compile(r"(?<![\d.,/])(\d{3,6})\s+(HRB|HRA|VR)(?![A-Za-z])")


def _scheme(raw: str) -> str:
    s = re.sub(r"[\s-]", "", raw).upper()
    if s.startswith("VEREINSREGISTER"):
        return "VR"                        # 'Amtsgericht Berlin-Charlottenburg, Vereinsregister 31924 B' 
    return {"GNR": "GnR", "HR": "HRB"}.get(s, s)
_COURT_BEFORE = re.compile(r"(?:Amtsgericht(?:s|es)?|Registergericht\s*:?\s*(?:Amtsgericht)?|\bAG|"
                           r"(?:Handels|Vereins)register(?:\s+beim)?(?=\s+[A-ZÄÖÜ][a-zäöüß])(?!\s+(?:Abteilung|Nummer|Nr))"
                           r"(?:\s+Amtsgericht)?)(?:\s*:\s*|\s+)([A-ZÄÖÜ][\wäöüß\-]+"
                           r"(?:\s(?:am|an der|im|in der|i\.\s?\w+\.?|\(\w+\))\s?[\wäöüß\-]*)?)")
KIND_SCHEMES = {"e.V.": {"VR"}, "gGmbH": {"HRB"}, "GmbH": {"HRB"}, "UG": {"HRB"}, "AG": {"HRB"},
                "GmbH & Co. KG": {"HRA"}, "eG": {"GnR"}}


_CONTACT_RE = re.compile(r"@|\bE-?Mail\b|\b(?:Tel|Telefon|Fax|Mobil)\b|\+\d{2}|\(?0\d{2,5}\)?[ /-]?\d{3,}", re.I)


def _clean_person(n: str) -> str | None:
    words = _ws(n).split()
    while words and words[-1].strip(",.;:") in _NOT_NAME:      # 'Otto Muster Registergericht' -> 'Otto Muster'
        words.pop()
    toks = [t for t in words if not re.match(r"(?:Dr|Prof|Dipl|Pfarrer|Pastor|Diakon)", t)]
    if len(toks) < 2 or any(t.strip(",.;") in _NOT_NAME for t in toks):
        return None
    return " ".join(words)


def impressum_people(text: str, near: int | None = None) -> list[tuple[str, str, str]]:
    """[(person, published function, verbatim quote)] from Impressum text (html_to_text lines). The quote runs
    from the role label to the end of the last name kept, whitespace-normalised.

    near: whitespace-normalised offset of the organisation's name on the page. Then only role lines within
    [near-300, near+1500] count, and per role class only the line closest after the name (pages that print a
    parent and a subsidiary keep the officers of the entity that is named)."""
    found = []
    for rx in (_ROLE_LINE, _VERTRETEN):
        for m in rx.finditer(text):
            role = _ws(m.group("role"))
            kept, end = [], None
            for pm in re.finditer(_PERSON, m.group("names")):
                p = _clean_person(pm.group(0))
                if p is None:
                    break                  # stop at the first non-name ('Finanzamt München', 'Sitz Berlin')
                kept.append(p)
                end = m.start("names") + pm.start() + len(p)
            if not kept:
                continue
            quote = _ws(text[m.start(): max(end, m.end("role"))] if rx is _ROLE_LINE else m.group(0))
            if _CONTACT_RE.search(quote):
                continue                   # a quote never carries an e-mail address or phone/fax number
            found.append((len(_ws(text[:m.start()])), role, kept, quote))
    if near is not None:
        found = [f for f in found if near - 300 <= f[0] <= near + 1500]
        best: dict[str, int] = {}
        for off, role, _k, _q in found:
            rk = rollenklasse(role)
            d = off - near if off >= near else 10_000 + near - off
            best[rk] = min(best.get(rk, d), d)
        found = [f for f in found if (f[0] - near if f[0] >= near else 10_000 + near - f[0]) == best[rollenklasse(f[1])]]
    out, seen = [], set()
    for _off, role, kept, quote in found:
        for p in kept:
            if (p, role) not in seen:
                seen.add((p, role))
                out.append((p, role, quote))
    return out


def _court_hits(before: str) -> list:
    """Overlapping court matches, skipping a bare label ('Name des zuständigen Amtsgerichts: AG Kempten')."""
    out, i = [], 0
    while (mm := _COURT_BEFORE.search(before, i)):
        if mm.group(1).rstrip(":") not in ("AG", "Amtsgericht", "Amtsgerichts", "Registergericht"):
            out.append(mm)
        i = mm.start() + 1
    return out


def impressum_registers(text: str) -> list[dict]:
    """Court register entries on the page: scheme, number, court, verbatim quote, position."""
    out = []
    hits = [(m, _scheme(m.group(1)), m.group(2), m.group(3), False) for m in _REGNO.finditer(text)]
    hits += [(m, m.group(2), m.group(1), None, True) for m in _REGNO_REV.finditer(text)]
    for m, scheme, number, suffix, rev in hits:
        lo = max(0, m.start() - 160)
        before = "" if rev else text[lo:m.start()]       # reversed form: the court must follow the scheme
        after = text[m.end():m.end() + 80]
        court = None
        cs = _court_hits(before)
        if cs:
            court, qa = cs[-1].group(1), lo + cs[-1].start()
        else:
            ca = _COURT_BEFORE.search(after)
            if ca and ca.start() < 40:
                court, qa = ca.group(1), m.start()
        if court and re.fullmatch(r"(?i)Berlin[\s\-(]*Charlottenburg\)?", court.strip()):
            court = "Charlottenburg"                           # 'AG Berlin-Charlottenburg' = AG Charlottenburg
        if not court and suffix == "B" and scheme in ("HRB", "VR", "HRA"):
            court, qa = "Charlottenburg", m.start()          # Berlin numbers carry the suffix B (AG Charlottenburg)
        if not court:
            continue
        qb = max(m.end(), (m.end() + ca.end()) if (not cs and ca) else m.end())
        quote = _ws(text[qa:qb])
        raw = f"{scheme} {number}" + (f" {suffix}" if suffix else "") + f" (AG {court.strip()})"
        out.append({"scheme": scheme, "number": number + (f" {suffix}" if suffix else ""),
                    "court": court.strip(), "raw": raw, "quote": quote, "pos": m.start()})
    return out


_ABBR = [(re.compile(r"\bDEUTSCHES ROTES KREUZ\b"), "DRK"), (re.compile(r"\bARBEITERWOHLFAHRT\b"), "AWO"),
         (re.compile(r"\bARBEITER SAMARITER BUND\b"), "ASB"), (re.compile(r"\bKATHOLISCHE[RN]?\b"), "KATH"),
         (re.compile(r"\bKATH\b"), "KATH"), (re.compile(r"\bEVANGELISCHE[RN]?\b"), "EV")]


def _norm_tokens(s: str) -> str:
    t = common.name_norm(s)
    for rx, ab in _ABBR:
        t = rx.sub(ab, t)
    return t


def _page_names_org(text: str, name: str) -> int:
    """Whitespace-normalised offset of the organisation's name on the page (name_norm token sequence, with
    DRK/AWO/ASB abbreviations folded), -1 if absent. Addresses printed after the name in the source are ignored."""
    core = _norm_tokens(re.split(r",\s*(?=[A-ZÄÖÜ][a-zäöüß]+(?:straße|str\.|weg|platz|allee))|,\s*\d", name)[0])
    if not core or len(core) < 5:
        return -1
    target = core.split()
    words = text.split()
    toks, owner = [], []
    for wi, w in enumerate(words):
        for t in _norm_tokens(w).split():
            toks.append(t)
            owner.append(wi)
    n = len(target)
    for i in range(len(toks) - n + 1):
        if toks[i:i + n] == target:
            return len(" ".join(words[:owner[i]]))
    return -1


def _find_impressum_url(home: str, cfg: dict) -> str | None:
    if "impressum" in home.lower():
        return home
    try:
        raw = gated_fetch(home, cfg, retries=2, timeout=30)
    except RobotsRefused:
        raise
    except (RuntimeError, KeyError):
        return None
    from urllib.parse import urljoin
    html = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw
    for href, label in _IMP_LINK.findall(html):
        if "impressum" in href.lower() or "impressum" in re.sub(r"<[^>]+>", "", label).lower():
            u = urljoin(home, href.strip())
            if urlparse(u).scheme in ("http", "https"):
                return u
    return None


def run_impressum_auto(conn, cfg: dict) -> dict:
    """Governance officers and court register numbers from Träger Impressum pages (see module docstring)."""
    from ingest import orglink
    today = common.now()[:10]
    gov = {r[0] for r in conn.execute("SELECT DISTINCT org_id FROM org_person WHERE rollenklasse IN "
                                      f"({','.join('?' * len(GOVERNANCE))})", GOVERNANCE)}
    seeds = {**SITE_SEEDS, **(cfg.get("site_seeds") or {})}
    todo = []
    for oid, name, web, legal, reg in conn.execute(
            "SELECT id, name, webseite, legal_form, register_id FROM org WHERE canonical_org_id IS NULL AND is_protected=0 "
            "ORDER BY id").fetchall():
        if protected_traeger(conn, oid, name):
            continue                       # never fetch a protected-shelter Träger's Impressum (Land level only)
        site = seeds.get(name) or web
        if not site:
            continue
        has_court = bool(court_numbers(*[r[0] for r in conn.execute(
            "SELECT scheme || ' ' || number FROM org_register WHERE org_id=? AND scheme IN ('VR','HRB','HRA','GnR','PR')",
            (oid,))], reg if reg and not re.fullmatch(r"(?i)[a-zäöü]{1,5}_\d+", reg.strip()) else None))
        if oid in gov and has_court:
            continue
        todo.append((oid, name, _url(site), legal, has_court, oid in gov))
    if cfg.get("imp_auto_limit"):
        todo = todo[: int(cfg["imp_auto_limit"])]
    st = {"orgs": len(todo), "pages": 0, "no_page": 0, "robots": 0, "not_named": 0, "persons": 0, "orgs_with_persons": 0,
          "registers": 0, "reg_conflict": 0, "reg_ambiguous": 0, "reg_form_mismatch": 0, "zuwdb_match": 0,
          "zuwdb_mismatch": 0}
    conflicts, filled = [], []
    for oid, name, site, legal, has_court, has_gov in todo:
        try:
            url = _find_impressum_url(site, cfg)
            if not url:
                st["no_page"] += 1
                continue
            raw = gated_fetch(url, cfg, retries=2, timeout=30)
        except RobotsRefused:
            st["robots"] += 1
            continue
        except (RuntimeError, KeyError):
            st["no_page"] += 1
            continue
        page_lines = common.html_to_text(raw)
        lines = deshy(page_lines)            # match and parse without soft hyphens; quotes are mapped back below
        text = _ws(lines)
        pos = _page_names_org(text, name)
        if pos < 0:
            st["not_named"] += 1
            continue
        st["pages"] += 1
        sid = common.source_id_for(conn, url, DOMAIN, title=f"Impressum {name}", publisher=name, license=IMP_LICENSE)
        conn.execute("UPDATE source SET redistribute_fulltext=0 WHERE id=?", (sid,))
        # court register: the entry nearest after the organisation's name; the legal form must agree
        wrong_entity = False
        if not has_court:
            r, status = page_register(text, pos, name, legal)
            st["reg_form_mismatch"] += status == "form_mismatch"
            st["reg_ambiguous"] += status == "ambiguous"
            if r:
                holder, how = register_holder(conn, r["raw"])
                zuw = court_numbers(*[x[0] for x in conn.execute(
                    "SELECT number FROM org_register WHERE org_id=? AND scheme='BE_ZUWDB'", (oid,))],
                    reg if reg and re.fullmatch(r"(?i)[a-zäöü]{1,5}_\d+", reg.strip()) else None)
                page_num = court_numbers(r["raw"])
                berlin = (orglink.parse_court_register(r["raw"]) or ("",))[0].endswith(":CHARLOTTENBURG")
                if holder not in (None, oid):
                    st["reg_conflict"] += 1
                    conflicts.append(f"#{oid} {name}: {r['raw']} held by #{holder}")
                elif holder is None and zuw and berlin and not (page_num & zuw):
                    st["zuwdb_mismatch"] += 1  # Berlin page register differs from the org's ZUWDB number: other entity
                    wrong_entity = True
                else:
                    st["zuwdb_match"] += how == "zuwdb"
                    link_by_register(conn, oid=oid, name=name, r=r, url=url, sid=sid, today=today,
                                     record_kind="impressum_register", record_key=url, how=how)
                    st["registers"] += 1
                    filled.append((oid, name, r["raw"], url, r["quote"]))
        if not has_gov and not wrong_entity:
            n0 = st["persons"]
            kind = orglink.legal_kind(name, legal)
            for person, role, quote in impressum_people(lines, near=pos):
                if kind in ("GmbH", "gGmbH", "UG", "GmbH & Co. KG") and rollenklasse(role) == "vorstand":
                    continue               # a GmbH has no Vorstand: that line belongs to a parent e.V. on the same page
                quote = verbatim_quote(quote, page_lines)
                if quote is None or not name_on_page(person, page_lines):
                    st["shy_skipped"] = st.get("shy_skipped", 0) + 1
                    continue
                st["persons"] += _add_person(conn, org_id=oid, org_name=name, person=person, funktion=role,
                                             jahr=int(today[:4]), sid=sid, quote=quote, stand=today,
                                             locator=f"Impressum, Zeile '{quote[:120]}' (abgerufen {today})")
            st["orgs_with_persons"] += st["persons"] > n0
    cfg.setdefault("_report", {})["register_filled"] = filled
    cfg["_report"]["register_conflicts"] = conflicts
    notes = (f"impressum_auto: {st['orgs']} Träger with a website to check, {st['pages']} Impressum pages naming the org "
             f"(no page {st['no_page']}, robots {st['robots']}, org not named {st['not_named']}); "
             f"{st['persons']} persons on {st['orgs_with_persons']} orgs; court register filled {st['registers']} "
             f"(held by another org {st['reg_conflict']}: {conflicts[:3]}, ambiguous {st['reg_ambiguous']}, "
             f"legal form mismatch {st['reg_form_mismatch']}; ZUWDB number confirmed {st['zuwdb_match']}, "
             f"ZUWDB mismatch {st['zuwdb_mismatch']}); soft-hyphen name/quote skipped {st.get('shy_skipped', 0)}")
    return {"rows": st["persons"] + st["registers"], "notes": notes,
            "sources": [("<Träger-Impressum-URL>", IMP_LICENSE)]}


ITZ_LIST = "https://www.transparente-zivilgesellschaft.de/ueber-uns/unterzeichnerorganisationen"
ITZ_LICENSE = ("Transparenzangaben nach der Selbstverpflichtung der Initiative Transparente Zivilgesellschaft (Punkt 4: Name "
               "und Funktion wesentlicher Entscheidungsträger), veröffentlicht vom Träger; keine offene Lizenz, Rechte "
               "vorbehalten: nur Name und veröffentlichte Funktion (Fakten) und eine kurze zitierte Zeile (§ 51 UrhG) mit "
               "Quellenangabe")
_ITZ_LI = re.compile(r'<li class="subscriber">(.*?)</li>', re.S)


def itz_signatories(cfg: dict) -> list[dict]:
    """The ITZ signatory list: [{name, city, url, list_url}], pages 1..n until a page has no entry (or 404)."""
    import html as _h
    out = []
    for n in range(1, int(cfg.get("itz_max_pages", 300)) + 1):
        url = ITZ_LIST if n == 1 else f"{ITZ_LIST}/{n}"
        try:
            raw = gated_fetch(url, cfg, retries=2, timeout=30)
        except KeyError:
            break                          # fixture: no further page
        except RuntimeError as ex:
            if "HTTP 404" in str(ex):
                break                      # past the last page
            raise
        items = _ITZ_LI.findall(raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw)
        if not items:
            break
        for it in items:
            nm = re.search(r'<h3 class="name">(.*?)</h3>', it, re.S)
            city = re.search(r'<p class="city"[^>]*>(.*?)</p>', it, re.S)
            href = re.search(r'href="([^"]+)"', it)
            if not (nm and href):
                continue
            link = _h.unescape(href.group(1)).strip()
            if "://" not in link:
                link = "https://" + link.lstrip("/")
            out.append({"name": _ws(_h.unescape(re.sub(r"<[^>]+>", "", nm.group(1)))),
                        "city": _ws(_h.unescape(city.group(1))) if city else None, "url": link, "list_url": url})
    return out


_ITZ_HEAD = re.compile(r"(?i)(?:Namen?\s+und\s+Funktion(?:en)?\s+(?:der\s+)?(?:wesentliche[rn]?|wichtige[rn]?)\s+"
                       r"En?t?scheidungstr[äa]ger|Die\s+Entscheidungstr[äa]ger)\S*")
_ITZ_NEXT = re.compile(r"^\s*\d{1,2}[a-z]?\.\s+\S")                 # '5. Tätigkeitsbericht' ends point 4
_ITZ_GOV = re.compile(r"(?i)vorst[aä]nd|vorsitz|gesch[äa]ftsf[üu]hr|aufsichtsrat|kuratori|stiftungsrat|verwaltungsrat|"
                      r"pr[äa]sid|schatzmeister|schriftf[üu]hr")
_ITZ_RESET = re.compile(r"(?i)leitung|prokur|kontakt|ansprechpart|gesellschafter|mitarbeit|team|beirat|bereich|referent")
_ITZ_OTHER_ORG = re.compile(r"e\.\s?V\.|gGmbH|GmbH|Verband|verbandes|\bbei der\b|\bbeim\b")
_ITZ_SPLIT = re.compile(r"^(?P<name>.+?)\s*(?:,|\s[–—-]\s)\s*(?P<role>[^,]{3,90})$|^(?P<name2>.+?)\s*\((?P<role2>[^()]{3,60})\)$")
_ITZ_NOT_PERSON = re.compile(r"(?i)\b(?:kirchenkreis|evangelisch\w*|katholisch\w*|stiftung|verband|werk|gemeinde|kirche|"
                             r"diakonie|caritas|verein)\b|(?:ung|ungen|heit|keit|arbeit|hilfen?|schaft|bericht|struktur|"
                             r"ion|ismus|tät)$")
_ITZ_SKIP = re.compile(r"(?i)^(?:bild|foto|tel\.?|telefon|fax|e-?mail|mail|datei|pdf\b.*|download\b.*)$")


def _itz_name(t: str) -> str | None:
    t = re.sub(r"^[•·\-–*]\s*", "", t.strip())
    t = re.sub(r"\s+(?:[A-Z]{2,4})$", "", t)                       # 'Elisabeth Eichert UAC' (order suffix)
    if not re.fullmatch(_PERSON, t) or _ITZ_NOT_PERSON.search(t):
        return None
    return _clean_person(t)


def _itz_label(t: str) -> str | None:
    """A governance body or role heading line without a name: 'Vorstand', 'Der Vorstand:', '4.1 Stiftungsrat'."""
    t = re.sub(r"^\d+(?:\.\d+)*\s+", "", t.strip())
    if len(t) > 60 or not _ITZ_GOV.search(t) or re.search(r"[\d,]|\s[–—]\s", t):
        return None
    t = re.sub(r"(?i)^(?:der|die|das)\s+", "", t)
    t = re.sub(r"(?i)\s+vertreten\s+durch\s*:?$", "", t).rstrip(": ").strip()
    return t or None


def _itz_class(label: str | None, role: str) -> str:
    """Role class: a supervisory body heading wins over a bare 'Vorsitzender' / 'Mitglied' under it."""
    lb = (label or "").lower()
    if "stiftungsrat" in lb or "kuratori" in lb:
        return "kuratorium"
    if "aufsichtsrat" in lb or "verwaltungsrat" in lb:
        return "aufsichtsrat"
    if "vorstand" in lb and rollenklasse(role) == "sonstige":
        return "vorstand"
    rk = rollenklasse(role)
    return rollenklasse(label) if rk == "sonstige" and label else rk


def itz_people(lines: str) -> list[tuple[str, str, str, str]]:
    """[(person, published function, verbatim quote, role class)] from point 4 of an ITZ transparency page
    ('Name und Funktion wesentlicher Entscheidungsträger'): 'Name, Funktion' / 'Name – Funktion' / 'Name (Funktion)'
    lines and name lines under a governance heading. Lines under a non-governance heading (Leitung, Prokura,
    Gesellschafterversammlung, Kontakt …) and roles held in another organisation are skipped."""
    m = _ITZ_HEAD.search(lines)
    if not m:
        return []
    rows = lines[m.end():].split("\n")
    out, seen = [], set()
    label, label_at, since = None, 0, 0
    offs, o = [], m.end()
    for r in rows:
        offs.append(o)
        o += len(r) + 1
    for i, raw in enumerate(rows):
        line = raw.strip()
        if i > 0 and _ITZ_NEXT.match(line) and not re.match(r"^\s*\d+\.\d", line):
            break
        if offs[i] - m.end() > 3000:
            break
        if not line or _ITZ_SKIP.match(line) or _CONTACT_RE.search(line):
            since += 1
            continue
        person = role = None
        sm = _ITZ_SPLIT.match(re.sub(r"^[•·*]\s*", "", line))
        if sm:
            nm, rl = (sm.group("name"), sm.group("role")) if sm.group("name") else (sm.group("name2"), sm.group("role2"))
            person = _itz_name(nm)
            role = _ws(rl) if person else None
        if person is None:
            person = _itz_name(line)
        if person is None:
            lb = _itz_label(line)
            if lb:
                label, label_at, since = lb, offs[i], 0
            elif _ITZ_RESET.search(line) or since >= 3:
                label = None
            elif len(line) <= 60 and "," not in line:
                since += 1                 # short stray lines expire a heading; prose and 'Beruf, Ort' lines do not
            continue
        since = 0
        if role and _ITZ_OTHER_ORG.search(role):
            continue                       # 'Vorstandsvorsitzender des Sozialverbandes VdK …': another organisation
        if role and not _ITZ_GOV.search(role) and (not label or not (
                re.search(r"(?i)mitglied|beisitz|kassier|stellv|ehren", role) or len(role.split()) >= 2)):
            continue                       # 'Kirchenkreis X, Berlin': a place, not a function
        funktion = role or label
        if not funktion:
            continue
        end = offs[i] + len(raw)
        start = label_at if (label and end - label_at <= 300) else offs[i]
        quote = _ws(lines[start:end])
        if funktion not in quote or _CONTACT_RE.search(quote):
            quote = _ws(raw)
            if funktion not in quote:
                continue
        key = (common.name_norm(person), funktion)
        if key not in seen:
            seen.add(key)
            out.append((person, funktion, quote, _itz_class(label, funktion)))
    # 'Vorstand: A, B und C' lines inside point 4 (the Impressum role-line parser)
    sec = lines[m.end(): m.end() + 3000]
    nxt = re.search(r"\n\s*\d{1,2}[a-z]?\.\s+\S", sec)
    sec = sec[: nxt.start()] if nxt else sec
    for person, role, quote in impressum_people(sec):
        key = (common.name_norm(person), role)
        if key not in seen and not any(common.name_norm(person) == k[0] for k in seen):
            seen.add(key)
            out.append((person, role, quote, rollenklasse(role)))
    return out


def run_itz(conn, cfg: dict) -> dict:
    """Governance officers from ITZ transparency pages (see module docstring)."""
    from ingest import orglink
    today = common.now()[:10]
    gov = {r[0] for r in conn.execute("SELECT DISTINCT org_id FROM org_person WHERE rollenklasse IN "
                                      f"({','.join('?' * len(GOVERNANCE))})", GOVERNANCE)}
    sigs = itz_signatories(cfg)
    if not sigs and not cfg.get("imp_fixture"):
        raise RuntimeError("itz: the signatory list yielded no entry (page layout changed?)")
    by_name: dict[str, list[dict]] = {}
    for e in sigs:
        by_name.setdefault(_norm_tokens(e["name"]), []).append(e)
    orgs_by_key: dict[str, list] = {}
    for oid, name, legal in conn.execute("SELECT id, name, legal_form FROM org WHERE canonical_org_id IS NULL "
                                         "AND is_protected=0 ORDER BY id").fetchall():
        orgs_by_key.setdefault(_norm_tokens(name), []).append((oid, name, legal))
    st = {"signatories": len(sigs), "matched": 0, "ambiguous": 0, "had_gov": 0, "pages": 0, "robots": 0, "no_page": 0,
          "not_named": 0, "no_roles": 0, "persons": 0, "orgs_with_persons": 0}
    amb = []
    for key, orgs in orgs_by_key.items():
        cands = by_name.get(key) or []
        for oid, name, legal in orgs:
            kind = orglink.legal_kind(name, legal)

            def fits(k1, k2):
                return k1 is None or k2 is None or k1 == k2
            same = [e for e in cands if fits(kind, orglink.legal_kind(e["name"]))]
            if not same:
                continue
            if protected_traeger(conn, oid, name):
                continue                   # never fetch for a protected-shelter Träger
            rivals = [o for o in orgs if any(fits(orglink.legal_kind(o[1], o[2]), orglink.legal_kind(e["name"])) for e in same)]
            if len({e["url"] for e in same}) > 1 or len(rivals) > 1:
                st["ambiguous"] += 1       # one ITZ entry for several org rows, or several entries: no guess
                amb.append(f"#{oid} {name}")
                continue
            st["matched"] += 1
            if oid in gov:
                st["had_gov"] += 1
                continue
            e = same[0]
            try:
                raw = gated_fetch(e["url"], cfg, retries=2, timeout=30)
            except RobotsRefused:
                st["robots"] += 1
                continue
            except (RuntimeError, KeyError):
                st["no_page"] += 1
                continue
            if raw[:5] == b"%PDF-":
                st["no_page"] += 1         # report PDFs: not parsed in this reader
                continue
            page_lines = common.html_to_text(raw)
            lines = deshy(page_lines)
            text = _ws(lines)
            pos = _page_names_org(text, name)
            if pos < 0:
                pos = _page_names_org(text, e["name"])
            if pos < 0:
                st["not_named"] += 1
                continue
            st["pages"] += 1
            people = []
            for person, role, quote, klass in itz_people(lines):
                vq = verbatim_quote(quote, page_lines)
                if vq is None or not name_on_page(person, page_lines):
                    st["shy_skipped"] = st.get("shy_skipped", 0) + 1
                    continue
                people.append((person, role, vq, klass))
            if kind in ("GmbH", "gGmbH", "UG", "GmbH & Co. KG"):
                # a GmbH has a Geschäftsführung (and maybe an Aufsichtsrat); Vorstand / Stiftungsrat lines on its page
                # belong to a parent association or foundation
                people = [x for x in people if x[3] == "geschaeftsfuehrung" or
                          (x[3] == "aufsichtsrat" and "stiftung" not in x[2].lower())]
            if not people:
                st["no_roles"] += 1
                continue
            sid = common.source_id_for(conn, e["url"], DOMAIN, title=f"ITZ-Transparenzangaben {name}", publisher=name,
                                       license=ITZ_LICENSE)
            conn.execute("UPDATE source SET redistribute_fulltext=0 WHERE id=?", (sid,))
            n0 = st["persons"]
            for person, role, quote, klass in people:
                st["persons"] += _add_person(conn, org_id=oid, org_name=name, person=person, funktion=role,
                                             rolle=klass, jahr=int(today[:4]), sid=sid, quote=quote, stand=today,
                                             locator=f"ITZ-Transparenzseite (Punkt 4 Entscheidungsträger; gelistet auf "
                                                     f"{e['list_url']} als \u201e{e['name']}\u201c), Zeile '{quote[:120]}' "
                                                     f"(abgerufen {today})")
            st["orgs_with_persons"] += st["persons"] > n0
    notes = (f"itz: {st['signatories']} signatories listed; {st['matched']} matched a Träger by exact name and legal form "
             f"({st['had_gov']} already had officers; ambiguous {st['ambiguous']}: {amb[:3]}); {st['pages']} pages naming "
             f"the org (robots {st['robots']}, no page/PDF {st['no_page']}, org not named {st['not_named']}, no role line "
             f"{st['no_roles']}); {st['persons']} persons on {st['orgs_with_persons']} orgs; soft-hyphen name/quote "
             f"skipped {st.get('shy_skipped', 0)}")
    return {"rows": st["persons"], "notes": notes, "sources": [("<ITZ-Transparenzseite des Trägers>", ITZ_LICENSE)]}


SOURCES = {"lobbyregister": run_lobbyregister, "impressum": run_impressum, "impressum_auto": run_impressum_auto,
           "itz": run_itz}


def run(conn, cfg: dict) -> dict:
    names = cfg.get("sources") or list(SOURCES)
    rows, notes, srcs, errors = 0, [], [], []
    for n in names:
        r = SOURCES[n](conn, cfg)
        rows += r["rows"]
        notes.append(r["notes"])
        srcs += r["sources"]
        errors += r.get("errors") or []
    head = f"RUN ERRORS {len(errors)}: {errors[:5]} | " if errors else ""
    return {"rows": rows, "notes": head + " | ".join(notes), "sources": srcs, "errors": errors}


# ------------------------------------------------------------------ offline tests

def _lfn(name, form=None):
    """legal_form_norm for test fixtures (schema 6: every fixture org row carries it)."""
    from ingest import orglink
    return orglink.legal_form_norm(name, form)


def memory_conn():
    import sqlite3
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(common.SCHEMA.read_text(encoding="utf-8"))
    return conn


_LR_ENTRY = {"registerNumber": "R000001", "registerEntryDetails": {"version": 3, "validFromDate": "2026-09-07T10:19:17.000+02:00",
             "detailsPageUrl": "https://www.lobbyregister.bundestag.de/suche/R000001/1"},
             "lobbyistIdentity": {"identity": "ORGANIZATION", "name": "Wohnungslosenhilfe Beispiel e.V.",
                                  "address": {"street": "Musterweg", "streetNumber": "1", "zipCode": "10115", "city": "Berlin"},
                                  "contactDetails": {"phoneNumber": "+49 30 123", "emails": [{"email": "info@example.org"}],
                                                     "websites": [{"website": "www.example.org"}]},
                                  "legalRepresentatives": [
                                      {"academicDegreeBefore": "Dr.", "lastName": "Muster", "firstName": "Erika",
                                       "function": "Vorsitzende des Vorstands", "contactDetails": {"phoneNumber": "+49 30 999"}},
                                      {"lastName": "Beispiel", "firstName": "Max", "function": "Geschäftsführer", "contactDetails": {}}],
                                  "entrustedPersons": [{"lastName": "Muster", "firstName": "Erika", "academicDegreeBefore": "Dr."},
                                                       {"lastName": "Probe", "firstName": "Jana"}]},
             "activitiesAndInterests": {"activityDescription": "Hilfen für wohnungslose Menschen"}}
_LR_PERSON = {"registerNumber": "R000002", "lobbyistIdentity": {"identity": "NATURAL", "name": "Hans Privat",
              "legalRepresentatives": [{"lastName": "Privat", "firstName": "Hans", "function": "Inhaber"}]}}


def _lr_fixture():
    search = f"{LR_API}?q={urlquote('wohnungslos')}&format=json"
    detail = f"{LR_API}/R000001?format=json"
    raw = json.dumps(_LR_ENTRY, ensure_ascii=False, separators=(",", ":"))
    return {"lr_key": "test", "lr_queries": ["wohnungslos"], "lr_org_names": False,
            "lr_fixture": {search: {"results": [_LR_ENTRY, _LR_PERSON]}, detail: _LR_ENTRY},
            "lr_fixture_raw": {detail: raw}}


def _test_lobbyregister():
    conn = memory_conn()
    conn.execute("INSERT INTO source(domain,url) VALUES ('t','https://example.org/seed')")
    cfg = _lr_fixture()
    raw = cfg["lr_fixture_raw"][f"{LR_API}/R000001?format=json"]
    common_sid = common.source_id_for

    def fake_sid(c, url, domain, **kw):
        return common.upsert(c, "source", {"domain": domain, "url": url, "title": kw.get("title"),
                                           "license": kw.get("license"), "retrieved_at": common.now()}, keys=["domain", "url"])
    common.source_id_for = fake_sid
    try:
        res = run(conn, {**cfg, "sources": ["lobbyregister"]})
    finally:
        common.source_id_for = common_sid
    assert res["rows"] == 3, res
    rows = {r["funktionstraeger"]: dict(r) for r in conn.execute("SELECT * FROM org_person")}
    assert set(rows) == {"Dr. Erika Muster", "Max Beispiel", "Jana Probe"}, rows
    assert rows["Max Beispiel"]["rollenklasse"] == "geschaeftsfuehrung"
    assert rows["Dr. Erika Muster"]["rollenklasse"] == "vorstand" and rows["Dr. Erika Muster"]["jahr"] == 2026
    assert rows["Jana Probe"]["rollenklasse"] == "lobby_kontakt"
    for q, in conn.execute("SELECT quote FROM org_person"):
        assert q in raw and "999" not in q and "contactDetails" not in q, q
    o = conn.execute("SELECT name, strasse, plz, telefon, email, ort FROM org").fetchone()
    assert o["strasse"] is None and o["plz"] is None and o["telefon"] is None and o["email"] is None
    assert conn.execute("SELECT number FROM org_register WHERE scheme='LobbyR'").fetchone()[0] == "R000001"
    assert conn.execute("SELECT COUNT(*) FROM org WHERE name='Hans Privat'").fetchone()[0] == 0


def _test_impressum():
    conn = memory_conn()
    url = "https://traeger.example/impressum"
    html = ("<html><body><p>Beispiel Träger e.V.</p><p>Vertretungsberechtigter Vorstand:</p><p>Dr. Anna Beispiel</p>"
            "<p>Tel. 030 1234</p><p>Geschäftsführung: Otto Muster</p></body></html>").encode()
    seeds = [{"org": "Beispiel Träger e.V.", "land": "BE", "url": url,
              "people": [("Dr. Anna Beispiel", "Vertretungsberechtigter Vorstand", "Vertretungsberechtigter Vorstand: Dr. Anna Beispiel"),
                         ("Otto Muster", "Geschäftsführung", "Geschäftsführung: Otto Muster"),
                         ("Gone Person", "Vorstand", "Vorstand: Gone Person")]},
             {"org": "Frauenhaus Beispiel e.V.", "land": "BE", "url": url, "people": [("X Y", "Vorstand", "Vorstand")]}]
    sid_orig = common.source_id_for
    common.source_id_for = lambda c, u, d, **kw: common.upsert(c, "source", {"domain": d, "url": u, "license": kw.get("license"),
                                                                              "retrieved_at": common.now()}, keys=["domain", "url"])
    try:
        res = run(conn, {"sources": ["impressum"], "imp_seeds": seeds, "imp_fixture": {url: html}})
    finally:
        common.source_id_for = sid_orig
    assert res["rows"] == 2 and "stale 1" in res["notes"], res
    assert conn.execute("SELECT COUNT(*) FROM org WHERE name LIKE 'Frauenhaus%'").fetchone()[0] == 0
    r = conn.execute("SELECT funktionstraeger, rollenklasse FROM org_person ORDER BY funktionstraeger").fetchall()
    assert [tuple(x) for x in r] == [("Dr. Anna Beispiel", "vorstand"), ("Otto Muster", "geschaeftsfuehrung")], r
    assert conn.execute("SELECT COUNT(*) FROM org_person WHERE funktionstraeger LIKE '%030%'").fetchone()[0] == 0


def _reset_robots():
    _ROBOTS.clear()
    _HOST_LAST.clear()


class _Seen(dict):
    """imp_fixture that records which URLs were read."""
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.read = []

    def __getitem__(self, k):
        self.read.append(k)
        return super().__getitem__(k)


def _fake_sources():
    orig = common.source_id_for
    common.source_id_for = lambda c, u, d, **kw: common.upsert(c, "source", {"domain": d, "url": u, "license": kw.get("license"),
                                                                              "retrieved_at": common.now()}, keys=["domain", "url"])
    return orig


def _test_robots_gate():
    """(1) per-host robots.txt, fail closed; honest UA; nothing fetched from a refused host."""
    import urllib.error
    import urllib.request
    _reset_robots()
    fx = {"https://ok.example": "User-agent: *\nDisallow: /intern/\n",
          "https://ours.example": "User-agent: germany-atlas\nDisallow: /\n\nUser-agent: *\nAllow: /\n",
          "https://err.example": "error", "https://five.example": 503, "https://forbid.example": 403,
          "https://none.example": 404}
    cfg = {"robots_fixture": fx}
    assert robots_ok("https://ok.example/impressum", cfg) and not robots_ok("https://ok.example/intern/impressum", cfg)
    assert not robots_ok("https://ours.example/impressum", cfg)              # our agent's own group wins
    for host in ("err", "five", "forbid"):
        assert not robots_ok(f"https://{host}.example/impressum", cfg), host  # unreadable robots.txt: fail closed
    assert robots_ok("https://none.example/impressum", cfg)                 # 404: no rules
    pages = _Seen({"https://err.example/impressum": b"<p>X e.V.</p>", "https://ok.example/intern/impressum": b"x"})
    for u in pages.copy():
        try:
            gated_fetch(u, {"robots_fixture": fx, "imp_fixture": pages})
            raise AssertionError("refused page fetched")
        except RobotsRefused:
            pass
    assert pages.read == [], pages.read
    # live path: the robots request carries the project UA, and a network error fails closed
    _reset_robots()
    seen = {}
    orig = urllib.request.urlopen

    def fake(req, timeout=None):
        seen["ua"] = req.get_header("User-agent")
        raise urllib.error.URLError("unreachable")
    urllib.request.urlopen = fake
    try:
        assert robots_ok("https://down.example/impressum", {}) is False
    finally:
        urllib.request.urlopen = orig
    assert seen["ua"] == common.UA and "germany-atlas" in common.UA, seen
    assert "unreadable" in _ROBOTS["https://down.example"]
    _reset_robots()


def _test_robots_first():
    """Lead review 2026-11-23: robots.txt is read before ANY request to a host (pages, API paths, POST searches,
    probes); a path robots.txt disallows (/api/) is never requested."""
    import urllib.request
    from ingest.domains import funding_traeger as ft
    _reset_robots()
    order = []
    orig_open, orig_fetch, orig_post = urllib.request.urlopen, common.fetch, common.fetch_post_json

    class Resp:
        def __init__(self, url):
            self.url = url
            self.headers = {"Content-Type": "text/plain"}

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def geturl(self):
            return self.url

        def read(self, n=-1):
            return b"User-agent: *\nDisallow: /api/\n"

    def fake_open(req, timeout=None):
        order.append(("robots", req.full_url))
        return Resp(req.full_url)

    def fake_fetch(url, **kw):
        order.append(("get", url))
        return b"{}"

    def fake_post(url, body, **kw):
        order.append(("post", url))
        return {"notices": []}
    urllib.request.urlopen, common.fetch, common.fetch_post_json = fake_open, fake_fetch, fake_post
    try:
        host = "https://robots-first.example"
        for fn in (lambda: gated_fetch(host + "/api/3/action/package_search?q=x", {}),
                   lambda: _lr_get(host + "/api/v2/registerentries?q=x", "k", {"lr_backoff": (0, 0)}),
                   lambda: robots_gate(host + "/api/probe", {}, cached_ok=False)):
            try:
                fn()
                raise AssertionError("disallowed /api/ path requested")
            except RobotsRefused:
                pass
        assert order == [("robots", host + "/robots.txt")], order      # robots once, first; no /api/ request
        gated_fetch(host + "/impressum", {})                             # allowed path: after robots, no re-read
        assert order[-1] == ("get", host + "/impressum") and len(order) == 2, order
        # funding_traeger: TED search (POST API) and notice XML go through the same gate
        ft._robots_gate("https://api2.example/v3/notices/search", {}, post=True)
        assert order[2] == ("robots", "https://api2.example/robots.txt"), order
        try:
            ft._robots_gate("https://api2.example/api/x", {}, post=True)
            raise AssertionError("disallowed POST path passed")
        except RuntimeError as ex:                 # RobotsRefused (class of the imported module under -m)
            assert type(ex).__name__ == "RobotsRefused", ex
    finally:
        urllib.request.urlopen, common.fetch, common.fetch_post_json = orig_open, orig_fetch, orig_post
        _reset_robots()


def _test_org_facts_only():
    """(2) governance roles only: no Datenschutzbeauftragte, webmaster, photographers, editors, V.i.S.d.P. contacts
    (unless they hold a governance role), and no e-mail address or phone number in any stored value."""
    page = ("Impressum\nBeispiel Hilfe gGmbH\nMusterweg 1, 10115 Berlin\nGeschäftsführung: Gerda Führer\n"
            "Telefon: 030 123456\nE-Mail: info@beispiel.example\nDatenschutzbeauftragter: Max Daten\n"
            "Webmaster: Willi Web\nFotos: Fritz Foto\nRedaktion: Rita Red\nV.i.S.d.P.: Volker Press\n"
            "Verantwortlich i.S.d. § 18 Abs. 2 MStV: Vera Ant\nBildnachweis: Bernd Bild\n"
            "Registergericht: Amtsgericht Charlottenburg Registernummer: HRB 123456 B\n")
    ppl = impressum_people(page)
    assert [(a, b) for a, b, _ in ppl] == [("Gerda Führer", "Geschäftsführung")], ppl
    assert not any(_CONTACT_RE.search(q) for _, _, q in ppl)
    p2 = impressum_people("V.i.S.d.P.: Geschäftsführer: Hans Gut\nVorstand: Erika Probe Tel. 089 765432\n")
    assert ("Hans Gut", "Geschäftsführer") in [(a, b) for a, b, _ in p2], p2       # V.i.S.d.P. who is also GF
    assert all(not _CONTACT_RE.search(q) for _, _, q in p2), p2
    # end to end: only the GF and the register land in the DB; no address, phone or e-mail columns written
    _reset_robots()
    conn = memory_conn()
    orig = _fake_sources()
    try:
        sid = conn.execute("INSERT INTO source(domain,url,license) VALUES ('funding_traeger','https://s.example','x') RETURNING id").fetchone()[0]
        conn.execute("INSERT INTO org(name,name_norm,land,legal_form,webseite,source_id,currency,legal_form_norm) VALUES "
                     "('Beispiel Hilfe gGmbH',?, 'BE','gGmbH','https://beispiel.example',?, 'EUR', ?)",
                     (common.name_norm("Beispiel Hilfe gGmbH"), sid, _lfn("Beispiel Hilfe gGmbH")))
        url = "https://beispiel.example/impressum"
        html = ("<html><body>" + "".join(f"<p>{l}</p>" for l in page.splitlines()) + "</body></html>").encode()
        res = run(conn, {"sources": ["impressum_auto"], "imp_fixture": {"https://beispiel.example": f'<a href="{url}">Impressum</a>'.encode(),
                                                                        url: html}})
    finally:
        common.source_id_for = orig
    names = [r[0] for r in conn.execute("SELECT funktionstraeger FROM org_person")]
    assert names == ["Gerda Führer"], (names, res)
    o = conn.execute("SELECT strasse, plz, ort, lat, lon, telefon, email FROM org").fetchone()
    assert tuple(o) == (None,) * 7, tuple(o)
    assert conn.execute("SELECT number FROM org_register WHERE scheme='HRB'").fetchone()[0] == "123456"
    for (q,) in conn.execute("SELECT quote FROM org_person"):
        assert not _CONTACT_RE.search(q or ""), q


def _test_protected_traeger():
    """(3) Träger of protected shelters: their Impressum is never read; no street, PLZ or coordinates; Land only."""
    _reset_robots()
    conn = memory_conn()
    orig = _fake_sources()
    try:
        sid = conn.execute("INSERT INTO source(domain,url,license) VALUES ('funding_traeger','https://s.example','x') RETURNING id").fetchone()[0]
        rows = [("Frauen helfen Frauen Musterstadt e.V.", 0, "https://fhf.example"),     # name says so
                ("Zuflucht für Mädchen e.V.", 0, "https://zuflucht.example"),           # anonymous youth emergency place
                ("Neutraler Träger e.V.", 1, "https://flagged.example"),               # org flagged by the Lead
                ("Sozialwerk Beispiel e.V.", 0, "https://sozialwerk.example")]         # runs a protected facility
        ids = {}
        for n, prot, web in rows:
            ids[n] = conn.execute("INSERT INTO org(name,name_norm,land,legal_form,webseite,is_protected,source_id,currency,legal_form_norm) "
                                  "VALUES (?,?, 'NW','e.V.',?,?,?, 'EUR', ?) RETURNING id",
                                  (n, common.name_norm(n), web, prot, sid, _lfn(n))).fetchone()[0]
        conn.execute("INSERT INTO facility(name,name_norm,kind,traeger_org_id,land,is_protected,source_id) VALUES "
                     "('Schutzwohnung','SCHUTZWOHNUNG','frauenhaus',?, 'NW',1,?)", (ids["Sozialwerk Beispiel e.V."], sid))
        pages = _Seen()
        for n, _p, web in rows:
            pages[web + "/impressum"] = (f"<p>Impressum</p><p>{n}</p><p>Geheimweg 7, 12345 Musterstadt</p>"
                                         "<p>Vorstand: Erika Probe</p><p>Registergericht: Amtsgericht Essen VR 4711</p>").encode()
            pages[web] = f'<a href="{web}/impressum">Impressum</a>'.encode()
        assert all(protected_traeger(conn, ids[n], n) for n, _p, _w in rows)
        assert not protected_traeger(conn, None, "Berliner Stadtmission e.V.")
        res = run(conn, {"sources": ["impressum_auto"], "imp_fixture": pages})
    finally:
        common.source_id_for = orig
    assert pages.read == [], pages.read                                  # not even the home page was requested
    assert "0 Träger with a website" in res["notes"], res["notes"]
    assert conn.execute("SELECT COUNT(*) FROM org_person").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM org_register").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM source WHERE domain=?", (DOMAIN,)).fetchone()[0] == 0
    for r in conn.execute("SELECT strasse, plz, ort, lat, lon, land FROM org"):
        assert tuple(r)[:5] == (None,) * 5 and r[5] == "NW", tuple(r)


def _test_seed_quotes_contain_label():
    """Lead review: every hand-seeded quote contains its funktion label verbatim (and the person's last name)."""
    for seed in IMPRESSUM_SEEDS:
        for person, funktion, quote, *_was in seed["people"]:
            assert funktion in quote, (seed["org"], person, funktion, quote)
            assert person.split()[-1] in quote, (seed["org"], person, quote)
    # a seed whose label is not in its quote is reported stale and never written; an old label is relabelled in place
    conn = memory_conn()
    url = "https://traeger.example/impressum"
    html = "<p>Beispiel e.V.</p><p>Der Vorstand: Vorsitzende Anna Beispiel</p>".encode()
    orig = _fake_sources()
    try:
        sid = conn.execute("INSERT INTO source(domain,url,license) VALUES (?,?, 'x') RETURNING id", (DOMAIN, url)).fetchone()[0]
        oid = conn.execute("INSERT INTO org(name,name_norm,land,source_id,currency,legal_form_norm) VALUES ('Beispiel e.V.',?, 'BE',?, 'EUR', ?) "
                           "RETURNING id", (common.name_norm("Beispiel e.V."), sid, _lfn("Beispiel e.V."))).fetchone()[0]
        conn.execute("INSERT INTO org_person(org_id,org_bezeichnung,funktionstraeger,funktionstraeger_norm,funktion,rollenklasse,"
                     "jahr,source_id,quote) VALUES (?, 'Beispiel e.V.', 'Anna Beispiel', ?, 'Vorsitzende des Vorstands', 'vorstand',"
                     " ?, ?, 'Anna Beispiel')", (oid, common.name_norm("Anna Beispiel"), int(common.now()[:4]), sid))
        seeds = [{"org": "Beispiel e.V.", "land": "BE", "url": url,
                  "people": [("Anna Beispiel", "Vorsitzende", "Der Vorstand: Vorsitzende Anna Beispiel", "Vorsitzende des Vorstands"),
                             ("Otto Muster", "Vorstand", "Otto Muster")]}]
        res = run(conn, {"sources": ["impressum"], "imp_seeds": seeds, "imp_fixture": {url: html}})
    finally:
        common.source_id_for = orig
    rows = [tuple(r) for r in conn.execute("SELECT funktionstraeger, funktion, quote FROM org_person")]
    assert rows == [("Anna Beispiel", "Vorsitzende", "Der Vorstand: Vorsitzende Anna Beispiel")], rows
    assert "stale 1" in res["notes"], res["notes"]


def _test_no_ust_id():
    """Lead review: the Impressum reader never extracts a USt-IdNr (not as register, not into org, not in a quote)."""
    page = ("Impressum\nBeispiel Dienste GmbH\nGeschäftsführer: Paul Probe\nUSt-IdNr. DE123456789\n"
            "Umsatzsteuer-Identifikationsnummer gemäß § 27 a UStG: DE 123 456 789\n"
            "Registergericht: Amtsgericht Köln Registernummer: HRB 4711\n")
    regs = impressum_registers(page)
    assert [(r["scheme"], r["number"]) for r in regs] == [("HRB", "4711")], regs
    assert not any("DE123456789" in r["raw"] or "123456789" in r["number"] for r in regs)
    _reset_robots()
    conn = memory_conn()
    orig = _fake_sources()
    try:
        sid = conn.execute("INSERT INTO source(domain,url,license) VALUES ('funding_traeger','https://s.example','x') RETURNING id").fetchone()[0]
        conn.execute("INSERT INTO org(name,name_norm,land,legal_form,webseite,source_id,currency,legal_form_norm) VALUES "
                     "('Beispiel Dienste GmbH',?, 'NW','GmbH','https://dienste.example',?, 'EUR', ?)",
                     (common.name_norm("Beispiel Dienste GmbH"), sid, _lfn("Beispiel Dienste GmbH")))
        url = "https://dienste.example/impressum"
        html = ("<html><body>" + "".join(f"<p>{l}</p>" for l in page.splitlines()) + "</body></html>").encode()
        run(conn, {"sources": ["impressum_auto"], "imp_fixture": {"https://dienste.example": f'<a href="{url}">Impressum</a>'.encode(),
                                                                   url: html}})
    finally:
        common.source_id_for = orig
    reg, ust = conn.execute("SELECT register_id, ust_id FROM org").fetchone()
    assert ust is None and "HRB 4711" in (reg or ""), (reg, ust)        # the reader ran: court register yes, USt-ID no
    assert conn.execute("SELECT COUNT(*) FROM org_person").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM org_register WHERE scheme NOT IN ('VR','HRB','HRA','GnR','PR')").fetchone()[0] == 0
    for (tbl,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
        for r in conn.execute(f"SELECT * FROM {tbl}"):
            for x in r:
                if isinstance(x, str):
                    assert "123456789" not in x.replace(" ", ""), (tbl, x[:120])


def _test_lr_retry():
    """Lead review: a Lobbyregister 500 is retried gently; a persistent failure is a counted run error, not a skip;
    401/403 fails the run."""
    calls = {"n": 0}
    search = f"{LR_API}?q={urlquote('wohnungslos')}&format=json"

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError(f"fetch failed after 1 attempts: {search}: HTTP 500")
        return {"results": []}
    cfg = {"lr_fixture": {search: flaky}, "lr_backoff": (0, 0)}
    assert _lr_get(search, "k", cfg) == {"results": []} and calls["n"] == 3

    def down():
        calls["n"] += 1
        raise RuntimeError(f"fetch failed after 1 attempts: {search}: HTTP 500")
    calls["n"] = 0
    conn = memory_conn()
    res = run(conn, {"sources": ["lobbyregister"], "lr_key": "k", "lr_queries": ["wohnungslos"], "lr_org_names": False,
                     "lr_fixture": {search: down}, "lr_backoff": (0, 0)})
    assert calls["n"] == 3, calls
    assert len(res["errors"]) == 1 and "HTTP 500" in res["errors"][0], res
    assert res["notes"].startswith("RUN ERRORS 1"), res["notes"]

    def refused():
        raise RuntimeError(f"{search} -> HTTP 401")
    try:
        _lr_get(search, "k", {"lr_fixture": {search: refused}, "lr_backoff": (0, 0)})
        raise AssertionError("401 swallowed")
    except LobbyregisterAuthError:
        pass


def _test_itz():
    """ITZ: list parsed across pages; exact name + same legal form only; GmbH never gets a Vorstand; page must name
    the org; persons carry the verbatim quote; a protected Träger is never fetched; existing officers are kept."""
    _reset_robots()
    conn = memory_conn()
    orig = _fake_sources()
    li = ('<li class="subscriber"><h3 class="name">{n}</h3><p class="city" title="Ort">Berlin</p>'
          '<p class="link"><a class="extern" href="{u}">Link</a></p></li>')
    p1 = "<ul>" + li.format(n="Beispielhilfe e.V.", u="https://bh.example/transparenz") + \
        li.format(n="Musterdienste gGmbH", u="https://md.example/transparenz") + "</ul>"
    p2 = "<ul>" + li.format(n="Frauenhaus Muster e.V.", u="https://fh.example/transparenz") + \
        li.format(n="Andere Hilfe e.V.", u="https://ah.example/t") + "</ul>"
    fx = {ITZ_LIST: p1.encode(), f"{ITZ_LIST}/2": p2.encode(), f"{ITZ_LIST}/3": b"<ul></ul>",
          "https://bh.example/transparenz": ("<p>Beispielhilfe e.V.</p><p>4. Name und Funktion wesentlicher "
                                             "Entscheidungsträger</p><p>Vorstand: Anna Beispiel, Otto Muster</p>").encode(),
          "https://md.example/transparenz": ("<p>Musterdienste gGmbH</p><p>4. Name und Funktion der wesentlichen "
                                             "Entscheidungsträger</p><p>Stiftungsvorstand</p><p>Rita Falsch, Vorsitzende</p>"
                                             "<p>Geschäftsführung</p><p>• Ben Recht</p><p>Prokura</p><p>• Paul Prokura</p>"
                                             "<p>5. Tätigkeitsbericht</p>").encode(),
          "https://ah.example/t": "<p>Ein ganz anderer Verein</p><p>Vorstand: Nora Niemand</p>".encode()}
    try:
        sid = conn.execute("INSERT INTO source(domain,url,license) VALUES ('funding_traeger','https://s.example','x') RETURNING id").fetchone()[0]
        for nm, land in (("Beispielhilfe e. V.", "BE"), ("Musterdienste gGmbH", "BE"), ("Beispielhilfe gGmbH", "HH"),
                         ("Frauenhaus Muster e.V.", "BE"), ("Andere Hilfe e.V.", "BE")):
            conn.execute("INSERT INTO org(name,name_norm,land,source_id,currency,legal_form_norm) VALUES (?,?,?,?, 'EUR', ?)",
                         (nm, common.name_norm(nm), land, sid, _lfn(nm)))
        res = run(conn, {"sources": ["itz"], "imp_fixture": fx})
    finally:
        common.source_id_for = orig
    rows = sorted(tuple(r) for r in conn.execute(
        "SELECT o.name, p.funktionstraeger, p.funktion, p.quote FROM org_person p JOIN org o ON o.id=p.org_id"))
    assert rows == [("Beispielhilfe e. V.", "Anna Beispiel", "Vorstand", "Vorstand: Anna Beispiel, Otto Muster"),
                    ("Beispielhilfe e. V.", "Otto Muster", "Vorstand", "Vorstand: Anna Beispiel, Otto Muster"),
                    ("Musterdienste gGmbH", "Ben Recht", "Geschäftsführung", "Geschäftsführung • Ben Recht")], rows
    # formats seen on real ITZ pages (EJF, Unionhilfswerk, Koepjohann, Straßenkinder, tandem BTL, Pallotti-Mobil)
    page = "\n".join([
        "4. Name und Funktion der wesentlichen Entscheidungsträger", "Vorstand", "Dr. Andreas Beispiel",
        "Aufsichtsrat", "Karl Muster (Aufsichtsratsvorsitzender)", "Anne Probe",
        "Stiftungsrat", "Dr. Thomas Test, Vorsitzender", "Dieter Demo, Mitglied",
        "Das Kuratorium vertreten durch:", "Prof. Dr. Lena Lehr – Vorsitzende des Kuratoriums",
        "Gesellschafterversammlung", "Ralf Rand, Gesellschaftsvertreter und Vorstandsvorsitzender des Sozialverbandes X e.V.",
        "Leitung in den Bereichen", "Jana Jung", "Kontakt", "Tel. 030 123456",
        "5. Tätigkeitsbericht", "Vorstand", "Spät Danach"])
    got = [(p_, f_, k_) for p_, f_, _q, k_ in itz_people(page)]
    assert got == [("Dr. Andreas Beispiel", "Vorstand", "vorstand"),
                   ("Karl Muster", "Aufsichtsratsvorsitzender", "aufsichtsrat"),
                   ("Anne Probe", "Aufsichtsrat", "aufsichtsrat"),
                   ("Dr. Thomas Test", "Vorsitzender", "kuratorium"), ("Dieter Demo", "Mitglied", "kuratorium"),
                   ("Prof. Dr. Lena Lehr", "Vorsitzende des Kuratoriums", "kuratorium")], got
    for p_, f_, q_, _k in itz_people(page):
        assert f_ in q_ and p_.split()[-1] in q_ and q_ in _ws(page), (p_, f_, q_)
    assert "https://fh.example/transparenz" not in str([r[0] for r in conn.execute("SELECT url FROM source")])
    assert "org not named 1" in res["notes"] and "2000" not in res["notes"], res["notes"]
    lic = conn.execute("SELECT DISTINCT s.redistribute_fulltext FROM source s JOIN org_person p ON p.source_id=s.id").fetchall()
    assert [tuple(r) for r in lic] == [(0,)], lic


def _test_soft_hyphen():
    """&shy; inside a role label or the org name no longer hides an officer; the stored quote keeps the soft hyphen
    (verbatim in the archived text, verify G7); a name split by a soft hyphen is skipped, not stored altered."""
    _reset_robots()
    conn = memory_conn()
    orig = _fake_sources()
    home, url = "https://shy.example", "https://shy.example/impressum"
    html = ("<p>Muster&shy;dienste gGmbH</p><p>Geschäfts&shy;führerin: Anna Beispiel</p>"
            "<p>Aufsichtsratsvorsitzender: Otto Mus&shy;termann</p>").encode()
    try:
        sid = conn.execute("INSERT INTO source(domain,url,license) VALUES ('funding_traeger','https://s.example','x') RETURNING id").fetchone()[0]
        conn.execute("INSERT INTO org(name,name_norm,land,legal_form,webseite,source_id,currency,legal_form_norm) VALUES "
                     "('Musterdienste gGmbH',?, 'BE','gGmbH',?,?, 'EUR', ?)", (common.name_norm("Musterdienste gGmbH"), home, sid, _lfn("Musterdienste gGmbH")))
        res = run(conn, {"sources": ["impressum_auto"], "imp_fixture": {home: f'<a href="{url}">Impressum</a>'.encode(), url: html}})
    finally:
        common.source_id_for = orig
    rows = [tuple(r) for r in conn.execute("SELECT funktionstraeger, funktion, quote FROM org_person")]
    assert rows == [("Anna Beispiel", "Geschäftsführerin", "Geschäfts\u00adführerin: Anna Beispiel")], rows
    page = common.html_to_text(html)
    assert rows[0][2] in _ws(page)                       # verbatim, as verify G7 checks
    assert "soft-hyphen name/quote skipped 1" in res["notes"], res["notes"]
    assert verbatim_quote("Vorstand: Anna Beispiel", "Vor\u00adstand: Anna Beispiel") == "Vor\u00adstand: Anna Beispiel"
    assert verbatim_quote("Vorstand: Rita", "Vorstand: Anna") is None


def _test_register_links():
    """Lead review 2026-11-23: (1) a seed page whose register line exists links by register, not name_fuzzy;
    (2) a Berlin page register equal to the ZUWDB Registrierungsnummer (vr_024148 = VR 24148 B) proves the org;
    (3) 'Vereinsregister 31924 B' is parsed."""
    from ingest import orglink
    # (3) the exact Diakonie string
    regs = impressum_registers("Registergericht Amtsgericht Berlin-Charlottenburg, Vereinsregister 31924 B USt-IdNr.: DE 147801862")
    assert [(r["scheme"], r["number"], r["court"]) for r in regs] == [("VR", "31924 B", "Charlottenburg")], regs
    assert orglink.parse_court_register(regs[0]["raw"])[0] == "VR:31924:CHARLOTTENBURG", regs[0]["raw"]
    _reset_robots()
    conn = memory_conn()
    orig = _fake_sources()
    try:
        sid = conn.execute("INSERT INTO source(domain,url,license) VALUES ('funding_traeger','https://s.example','x') RETURNING id").fetchone()[0]
        # (1) org known by name only; its Impressum prints the register
        a = conn.execute("INSERT INTO org(name,name_norm,land,source_id,currency,legal_form_norm) VALUES ('Beispielwerk e.V.',?, 'BE',?, 'EUR', ?) "
                         "RETURNING id", (common.name_norm("Beispielwerk e.V."), sid, _lfn("Beispielwerk e.V."))).fetchone()[0]
        # (2) org known from the Berlin Zuwendungsdatenbank under another spelling, number vr_024148
        b = conn.execute("INSERT INTO org(name,name_norm,land,register_id,source_id,currency,legal_form_norm) VALUES "
                         "('Zuwendungsverein Berlin e. V.',?, 'BE','vr_024148',?, 'EUR', ?) RETURNING id",
                         (common.name_norm("Zuwendungsverein Berlin e. V."), sid, _lfn("Zuwendungsverein Berlin e. V."))).fetchone()[0]
        conn.execute("INSERT INTO org_register(org_id,scheme,court,number,raw,source_id) VALUES (?, 'BE_ZUWDB','', 'vr_024148','vr_024148',?)", (b, sid))
        u1, u2 = "https://bw.example/impressum", "https://zv.example/impressum"
        fx = {u1: "<p>Beispielwerk e.V.</p><p>Vorstand: Anna Beispiel</p><p>Amtsgericht Charlottenburg VR 1234 B</p>".encode(),
              u2: ("<p>Verein Zuwendung Berlin e.V.</p><p>Vorstand: Otto Muster</p>"
                   "<p>Amtsgericht Berlin-Charlottenburg, Vereinsregister 24148 B</p>").encode()}
        c = conn.execute("INSERT INTO org(name,name_norm,land,register_id,source_id,currency,legal_form_norm) VALUES "
                         "('AWO Musterbezirk e. V.',?, 'BE','vr_021507',?, 'EUR', ?) RETURNING id",
                         (common.name_norm("AWO Musterbezirk e. V."), sid, _lfn("AWO Musterbezirk e. V."))).fetchone()[0]
        conn.execute("INSERT INTO org_register(org_id,scheme,court,number,raw,source_id) VALUES (?, 'BE_ZUWDB','', 'vr_021507','vr_021507',?)", (c, sid))
        u3 = "https://awo-mb.example/impressum"
        fx[u3] = "<p>Arbeiterwohlfahrt Kreisverband Musterbezirk</p><p>Vorstand: Paula Probe</p><p>VR 21507 B</p>".encode()
        seeds = [{"org": "AWO Musterbezirk e. V.", "land": "BE", "url": u3,
                  "people": [("Paula Probe", "Vorstand", "Vorstand: Paula Probe")]},
                 {"org": "Beispielwerk e.V.", "land": "BE", "url": u1,
                  "people": [("Anna Beispiel", "Vorstand", "Vorstand: Anna Beispiel")]},
                 {"org": "Verein Zuwendung Berlin e.V.", "land": "BE", "url": u2,
                  "people": [("Otto Muster", "Vorstand", "Vorstand: Otto Muster")]}]
        res = run(conn, {"sources": ["impressum"], "imp_seeds": seeds, "imp_fixture": fx})
    finally:
        common.source_id_for = orig
    links = sorted(tuple(r) for r in conn.execute("SELECT record_key, org_id, method, flagged, id_value FROM org_link"))
    assert links == sorted([(u1 + "#Beispielwerk e.V.", a, "register_id", 0, "VR:1234:CHARLOTTENBURG"),
                            (u2 + "#Verein Zuwendung Berlin e.V.", b, "register_id", 0, "VR:24148:CHARLOTTENBURG"),
                            (u3 + "#AWO Musterbezirk e. V.", c, "register_id", 0, "VR:21507:CHARLOTTENBURG")]), links
    assert conn.execute("SELECT register_id FROM org WHERE id=?", (a,)).fetchone()[0] == "VR 1234 B (AG Charlottenburg)"
    assert conn.execute("SELECT register_id FROM org WHERE id=?", (b,)).fetchone()[0] == "vr_024148"   # never overwritten
    assert conn.execute("SELECT COUNT(*) FROM org").fetchone()[0] == 3                                  # no new org row
    assert {r[0] for r in conn.execute("SELECT org_id FROM org_person")} == {a, b, c}
    assert "3 linked by the page's register line" in res["notes"], res["notes"]
    assert zuwdb_holder(conn, "VR 24148 B (AG Charlottenburg)") == b
    assert zuwdb_holder(conn, "VR 24148 (AG Köln)") is None                     # only Berlin's register court
    # impressum_auto: a ZUWDB-only org whose page prints a different Berlin number is another entity
    _reset_robots()
    conn = memory_conn()
    orig = _fake_sources()
    try:
        sid = conn.execute("INSERT INTO source(domain,url,license) VALUES ('funding_traeger','https://s.example','x') RETURNING id").fetchone()[0]
        for nm, web, zn in (("Gleichname e. V.", "https://gl.example", "vr_000777"), ("Treffer e. V.", "https://tr.example", "vr_024148")):
            o = conn.execute("INSERT INTO org(name,name_norm,land,register_id,webseite,source_id,currency,legal_form_norm) VALUES (?,?, 'BE',?,?,?, 'EUR', ?) "
                             "RETURNING id", (nm, common.name_norm(nm), zn, web, sid, _lfn(nm))).fetchone()[0]
            conn.execute("INSERT INTO org_register(org_id,scheme,court,number,raw,source_id) VALUES (?, 'BE_ZUWDB','',?,?,?)", (o, zn, zn, sid))
        fx = {"https://gl.example/impressum": "<p>Gleichname e.V.</p><p>Vorstand: Rita Falsch</p><p>Amtsgericht Charlottenburg VR 999 B</p>".encode(),
              "https://tr.example/impressum": "<p>Treffer e.V.</p><p>Vorstand: Ben Recht</p><p>Amtsgericht Charlottenburg VR 24148 B</p>".encode()}
        res = run(conn, {"sources": ["impressum_auto"], "imp_fixture": fx,
                         "site_seeds": {"Gleichname e. V.": "https://gl.example/impressum", "Treffer e. V.": "https://tr.example/impressum"}})
    finally:
        common.source_id_for = orig
    assert "ZUWDB number confirmed 1, ZUWDB mismatch 1" in res["notes"], res["notes"]
    assert [r[0] for r in conn.execute("SELECT funktionstraeger FROM org_person")] == ["Ben Recht"]
    assert [tuple(r) for r in conn.execute("SELECT method, id_value FROM org_link")] == [("register_id", "VR:24148:CHARLOTTENBURG")]


def _test_impressum_parsers():
    t = _ws("Beispiel Hilfe gGmbH Musterweg 1 Vertreten durch die Geschäftsführung: Dr. Anna Beispiel und Otto Muster "
            "Registergericht: Amtsgericht Charlottenburg Registernummer: HRB 123456 B Telefon: 030 1234 "
            "Vorstand: Erika Probe, Hans-Peter Klein")
    ppl = impressum_people(t)
    assert ("Dr. Anna Beispiel", "Geschäftsführung") in [(a, b) for a, b, _ in ppl], ppl
    assert ("Otto Muster", "Geschäftsführung") in [(a, b) for a, b, _ in ppl], ppl
    assert ("Hans-Peter Klein", "Vorstand") in [(a, b) for a, b, _ in ppl], ppl
    assert all("030" not in q and q in t for _, _, q in ppl)
    regs = impressum_registers(t)
    assert len(regs) == 1 and regs[0]["scheme"] == "HRB" and regs[0]["court"] == "Charlottenburg", regs
    assert regs[0]["quote"] in t and "HRB 123456 B" in regs[0]["quote"]
    t3 = "Geschäftsführer: Dr. Wolfgang Kaefer\nFinanzamt München\nVorstand:\nErika Probe\nHans Klein\nTelefon 089"
    p3 = [(a, b) for a, b, _ in impressum_people(t3)]
    assert p3 == [("Dr. Wolfgang Kaefer", "Geschäftsführer"), ("Erika Probe", "Vorstand"), ("Hans Klein", "Vorstand")], p3
    t2 = "Eingetragen im Vereinsregister VR 4711 beim Amtsgericht Köln"
    r2 = impressum_registers(t2)
    assert r2 and r2[0]["court"] == "Köln" and r2[0]["quote"] in t2, r2
    assert impressum_registers("HRB 1234 ohne Gericht") == []
    r4 = impressum_registers("Sitz der Gesellschaft: Sottrum Registereintragung: 206124 HRB - Amtsgericht Walsrode Geschäftsführer")
    assert [(r["scheme"], r["number"], r["court"]) for r in r4] == [("HRB", "206124", "Walsrode")], r4
    r5 = impressum_registers("Registergericht: Amtsgericht Coesfeld Registernummer: HR B 7954 Umsatzsteuer")
    assert [(r["scheme"], r["number"], r["court"]) for r in r5] == [("HRB", "7954", "Coesfeld")], r5
    r6 = impressum_registers("Name des zuständigen Amtsgerichts: AG Kempten HRB: 10199 Steuernummer: 127/121/51941")
    assert [(r["scheme"], r["number"], r["court"]) for r in r6] == [("HRB", "10199", "Kempten")], r6
    assert impressum_registers("PLZ 10115 HRB fehlt") == []
    r7 = impressum_registers("Eintragung im Handelsregister. Registergericht:Krefeld Registernummer: HRB 491 Umsatzsteuer")
    assert [(r["scheme"], r["number"], r["court"]) for r in r7] == [("HRB", "491", "Krefeld")], r7
    assert _page_names_org("Impressum Beispiel Hilfe gGmbH Musterweg", "Beispiel Hilfe gGmbH") >= 0
    assert _page_names_org("Impressum Andere Hilfe gGmbH", "Beispiel Hilfe gGmbH") == -1


def _test_resolution():
    """Fixpunkt / Malteser: a namesake with another legal form or another register number is never reused."""
    from ingest.domains import funding_traeger as ft
    conn = memory_conn()
    sid = conn.execute("INSERT INTO source(domain,url) VALUES ('funding_traeger','https://example.org/s') RETURNING id").fetchone()[0]
    a = ft._ensure_org(conn, "Fixpunkt e. V.", "FIXPUNKT", "BE", sid, register="vr_011111")
    ft._add_register(conn, a, "BE_ZUWDB", "vr_011111", "vr_011111", sid)
    b = ft._ensure_org(conn, "Fixpunkt gGmbH", "FIXPUNKT", "BE", sid, register="hrb_082787")
    assert a != b, (a, b)
    ft._add_register(conn, b, "BE_ZUWDB", "hrb_082787", "hrb_082787", sid)
    assert ft._ensure_org(conn, "Fixpunkt gGmbH", "FIXPUNKT", "BE", sid, register="hrb_082787") == b
    assert ft._ensure_org(conn, "Fixpunkt e. V.", "FIXPUNKT", "BE", sid, register="vr_011111") == a
    g = ft._ensure_org(conn, "Malteser Hilfsdienst gGmbH", "MALTESER HILFSDIENST", "BW", sid, register="HRB 26997 (AG Köln)")
    e = ft._ensure_org(conn, "Malteser Hilfsdienst e.V.", "MALTESER HILFSDIENST", "BW", sid)
    assert g != e and tuple(conn.execute("SELECT name_norm, legal_form_norm FROM org WHERE id=?", (e,)).fetchone()) == (
        "MALTESER HILFSDIENST", "ev")                                         # schema 6: no tagged name_norm
    assert ft._ensure_org(conn, "Malteser Hilfsdienst e.V.", "MALTESER HILFSDIENST", "BW", sid) == e
    # officers: a Lobbyregister entry of the e.V. never lands on the gGmbH; a name match is a flagged link
    o = _ensure_org(conn, "Malteser Hilfsdienst e.V.", None, sid, lobby="R009999", link_kind="lobbyregister", link_key="R009999")
    assert o == e
    lk = conn.execute("SELECT method, flagged FROM org_link WHERE record_kind='lobbyregister' AND record_key='R009999'").fetchone()
    assert tuple(lk) == ("name_fuzzy", 1), tuple(lk)
    assert conn.execute("SELECT COUNT(*) FROM org WHERE canonical_org_id IS NOT NULL").fetchone()[0] == 0
    assert role_rank("geschaeftsfuehrung") < role_rank("aufsichtsrat") < role_rank("lobby_kontakt")


TESTS = [_test_lobbyregister, _test_impressum, _test_impressum_parsers, _test_resolution, _test_robots_gate,
         _test_org_facts_only, _test_protected_traeger, _test_seed_quotes_contain_label, _test_no_ust_id, _test_lr_retry, _test_itz, _test_soft_hyphen, _test_register_links, _test_robots_first]


def _run_tests():
    for t in TESTS:
        t()
        print("PASS", t.__name__)


# ------------------------------------------------------------------ CLI (never data/atlas.db)

SELFTEST_CFG = {"lr_queries": ["Wohnungslosenhilfe"], "lr_org_names": False, "lr_max_pages": 1, "lr_limit": 6}
USAGE = f"""usage: python3 -m ingest.domains.{DOMAIN} (--test | --selftest --db /tmp/SCRATCH.db [--source=NAME] [--full])
Running the module directly never touches data/atlas.db; the Lead ingests with `python3 -m ingest.run {DOMAIN}`."""


def scratch_db_path(argv) -> Path:
    if "--db" not in argv or argv.index("--db") + 1 >= len(argv):
        raise SystemExit("--selftest needs --db /tmp/<scratch>.db (never data/atlas.db)")
    p = Path(argv[argv.index("--db") + 1]).expanduser().resolve()
    if (p == common.DB.resolve() or p.name.startswith("atlas.db") or "germany-atlas-lead" in str(p)
            or (common.ROOT / "data").resolve() in p.parents):
        raise SystemExit(f"refusing to use {p}: selftests run on a scratch DB only")
    return p


def _selftest(argv):
    """Live sample into a scratch DB inside one transaction; --commit keeps the rows (scratch only)."""
    from ingest import run as runner
    conn = runner.open_db(scratch_db_path(argv))
    cfg = {} if "--full" in argv else dict(SELFTEST_CFG)
    srcs = [a.split("=", 1)[1] for a in argv if a.startswith("--source=")]
    if srcs:
        cfg["sources"] = srcs
    conn.execute("BEGIN IMMEDIATE")
    conn.runner_txn = True
    ok = False
    try:
        res = run(conn, cfg)
        print(f"[{DOMAIN}] selftest rows={res['rows']}")
        for n in res["notes"].split(" | "):
            print(f"[{DOMAIN}]   {n}")
        for r in conn.execute("SELECT p.funktionstraeger, p.funktion, p.rollenklasse, p.org_bezeichnung, p.jahr, p.stand, "
                              "p.quote, s.url FROM org_person p JOIN source s ON s.id=p.source_id ORDER BY random() LIMIT 3"):
            print("   ", dict(r))
        assert conn.execute("SELECT COUNT(*) FROM org_person WHERE source_id IS NULL").fetchone()[0] == 0
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        ok = True
    finally:
        conn.runner_txn = False
        conn.execute("COMMIT" if ok and "--commit" in argv else "ROLLBACK")
        conn.close()


def cli(argv=None) -> int:
    """argparse with allow_abbrev=False: unknown/abbreviated flags and a bare run exit 2; never atlas.db."""
    import argparse
    ap = argparse.ArgumentParser(prog=f"python3 -m ingest.domains.{DOMAIN}", allow_abbrev=False,
                                 description=f"Worker tools. data/atlas.db is written only by `python3 -m ingest.run {DOMAIN}`.")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--test", action="store_true", help="offline unit tests (in-memory SQLite)")
    mode.add_argument("--selftest", action="store_true", help="live sample into a scratch DB (needs --db)")
    ap.add_argument("--db", help="--selftest: scratch DB path (never atlas.db)")
    ap.add_argument("--source", action="append", choices=sorted(SOURCES), help="--selftest: limit to a reader")
    ap.add_argument("--full", action="store_true", help="--selftest: full run instead of the small sample")
    ap.add_argument("--commit", action="store_true", help="--selftest: keep the rows in the scratch DB")
    a = ap.parse_args(argv)
    if a.test:
        if a.db or a.source or a.full or a.commit:
            ap.error("--db/--source/--full/--commit are only valid with --selftest")
        _run_tests()
        return 0
    if not a.db:
        ap.error("--selftest needs --db <scratch path>")
    _selftest(["--selftest", "--db", a.db] + [f"--source={x}" for x in a.source or []]
              + (["--full"] if a.full else []) + (["--commit"] if a.commit else []))
    return 0


if __name__ == "__main__":
    sys.exit(cli())
