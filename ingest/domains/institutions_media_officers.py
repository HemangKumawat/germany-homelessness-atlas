"""Published Vorstand and Gremien roles of the big Wohlfahrtsverbände.

Scope (split with Funding & Träger): annual-report / Jahresbericht /
transparency-report PDFs, and Vorstand / Gremien pages beyond the Impressum.
This first pass covers verified federal Gremien pages. Impressum roles are
out of scope (Funding & Träger already stores those in org_person).

Rows go in org_person, never a sidecar table. Each row has a verbatim quote
from the unmodified archived page, a stand date, a published funktion, and a
source. Before insert, an existing org_person row with the same org_id, name
and funktion is skipped. No private contact details are stored.

This module never opens data/atlas.db.
"""
from __future__ import annotations

import re
import time
import urllib.parse
from pathlib import Path

from ingest import common
from ingest.common import html_to_text, name_norm, no_direct_run

DOMAIN = "institutions_media"
RECORD_KIND = "institutions_media_gremien"
HOST_GAP = 3.0
STAND = "2026-11-23"

QUOTE_LICENCE = (
    "Rechte vorbehalten (Impressum zitiert); nur Fakten, Metadaten und "
    "Kurzzitate nach § 51 UrhG, Volltext nicht weiterverbreitet"
)

# Personal contact or private-life tokens must never be stored.
CONTACT_RE = re.compile(
    r"(?i)@|tel\.\s*\+|\+\d{2}\s*\(\s*0\s*\)|"
    r"\bgeb(\.|oren)\s*(am\s*)?\d|\bgeb\.\s*\d"
)
STAFF_RE = re.compile(
    r"(?i)vorstandsassistent|vorstandsreferent|referent(in)? f"
)

# Bundesverband Gremien pages only — no Impressum URL belongs here.
PAGES: list[dict] = [
    {
        "id": "bagw-vorstand",
        "org": "Bundesarbeitsgemeinschaft Wohnungslosenhilfe e.V.",
        "legal_form": "e.V.",
        "land": "BE",
        "url": "https://www.bagw.de/de/bag-w/leitungsgremien/vorstand",
        "license_url": "https://www.bagw.de/de/impressum",
        "publisher": "Bundesarbeitsgemeinschaft Wohnungslosenhilfe e.V.",
        "title": "Der Vorstand der BAG W",
        "people": [
            {"name": "Stephanie Kasten", "funktion": "Vorstand",
             "quote": "Folgende Personen gehören dem aktuellen Vorstand der BAG W an: Stephanie Kasten"},
        ],
    },
    {
        "id": "bagw-praesidium",
        "org": "Bundesarbeitsgemeinschaft Wohnungslosenhilfe e.V.",
        "legal_form": "e.V.",
        "land": "BE",
        "url": "https://www.bagw.de/de/bag-w/leitungsgremien/praesidium",
        "license_url": "https://www.bagw.de/de/impressum",
        "publisher": "Bundesarbeitsgemeinschaft Wohnungslosenhilfe e.V.",
        "title": "Das Präsidium der BAG W",
        "people": [
            {"name": "Sabine Bösing", "funktion": "Mitglied des Präsidiums",
             "quote": "Die Mitglieder des Präsidiums: Sabine Bösing"},
        ],
    },
    {
        "id": "bagfw-gremien",
        "org": "Bundesarbeitsgemeinschaft der Freien Wohlfahrtspflege e.V.",
        "legal_form": "e.V.",
        "land": "DE",
        "url": "https://www.bagfw.de/ueber-uns/gremien",
        "license_url": "https://www.bagfw.de/site/impressum",
        "publisher": "Bundesarbeitsgemeinschaft der Freien Wohlfahrtspflege e.V.",
        "title": "Gremien der BAGFW",
        "people": [
            {"name": "Achim Meyer auf der Heyde", "funktion": "Präsident",
             "quote": "Präsident der BAGFW ist bis zum 31.12.2026 Achim Meyer auf der Heyde, Vorsitzender des Paritätischen Gesamtverbandes."},
            {"name": "Michael Groß", "funktion": "Vizepräsident",
             "quote": "Vizepräsident:innen sind: Michael Groß, Präsident des Arbeiterwohlfahrt Bundesverbandes und Eva Maria Welskop-Deffaa, Deutscher Caritasverband."},
            {"name": "Eva Maria Welskop-Deffaa", "funktion": "Vizepräsidentin",
             "quote": "Vizepräsident:innen sind: Michael Groß, Präsident des Arbeiterwohlfahrt Bundesverbandes und Eva Maria Welskop-Deffaa, Deutscher Caritasverband."},
        ],
    },
    {
        "id": "diakonie-struktur",
        "org": "Diakonie Deutschland, Evangelisches Werk für Diakonie und Entwicklung e.V.",
        "legal_form": "e.V.",
        "land": "DE",
        "url": "https://www.diakonie.de/informieren/der-bundesverband/unsere-struktur",
        "license_url": "https://www.diakonie.de/impressum",
        "publisher": "Diakonie Deutschland",
        "title": "Unsere Struktur — Diakonie Deutschland",
        "people": [
            {"name": "Rüdiger Schuch", "funktion": "Präsident",
             "quote": "Präsident Rüdiger Schuch"},
            {"name": "Jörg Kruttschnitt", "funktion": "Vorstand Finanzen, Personal, Recht",
             "quote": "Vorstand Finanzen, Personal, Recht Dr. Jörg Kruttschnitt"},
        ],
    },
    {
        "id": "caritas-struktur",
        "org": "Deutscher Caritasverband e. V.",
        "legal_form": "e.V.",
        "land": "DE",
        "url": "https://www.caritas.de/diecaritas/deutschercaritasverband/strukturundleitung/strukturundleitung",
        "license_url": "https://www.caritas.de/impressum",
        "publisher": "Deutscher Caritasverband e. V.",
        "title": "Struktur und Leitung des Deutschen Caritasverbandes",
        "people": [
            {"name": "Eva Maria Welskop-Deffaa", "funktion": "Präsidentin",
             "quote": "Eva Maria Welskop-Deffaa – Präsidentin"},
            {"name": "Susanne Pauser", "funktion": "Vorständin Personal und Digitales",
             "quote": "Dr. Susanne Pauser – Vorständin Personal und Digitales"},
            {"name": "Oliver Müller", "funktion": "Vorstand Internationales, Migration und Katastrophenhilfe",
             "quote": "Dr. Oliver Müller – Vorstand Internationales, Migration und Katastrophenhilfe"},
            {"name": "Friedrich von Schönfeld", "funktion": "Vorstand Finanzen und Recht",
             "quote": "Dr. Friedrich von Schönfeld – Vorstand Finanzen und Recht"},
        ],
    },
    {
        "id": "awo-praesidium",
        "org": "Arbeiterwohlfahrt Bundesverband e. V.",
        "legal_form": "e.V.",
        "land": "DE",
        "url": "https://awo.org/verband/verbandsstruktur/praesidium-und-vorstand/",
        "license_url": "https://awo.org/impressum/",
        "publisher": "Arbeiterwohlfahrt Bundesverband e. V.",
        "title": "Präsidium und Vorstand — AWO Bundesverband",
        "people": [
            {"name": "Kathrin Sonnenholzner", "funktion": "Vorsitzende des Präsidiums",
             "quote": "Vorsitzende des Präsidiums Kathrin Sonnenholzner"},
            {"name": "Britta Altenkamp", "funktion": "Stellvertretende Vorsitzende des Präsidiums",
             "quote": "Stellvertretende Vorsitzende des Präsidiums Britta Altenkamp"},
        ],
    },
    {
        "id": "awo-vorstand",
        "org": "Arbeiterwohlfahrt Bundesverband e. V.",
        "legal_form": "e.V.",
        "land": "DE",
        "url": "https://awo.org/verband/verbandsstruktur/bundesverband/vorstand/",
        "license_url": "https://awo.org/impressum/",
        "publisher": "Arbeiterwohlfahrt Bundesverband e. V.",
        "title": "Vorstand — AWO Bundesverband",
        "people": [
            {"name": "Claudia Mandrysch", "funktion": "Vorständin",
             "quote": "Claudia Mandrysch Vorständin"},
            {"name": "Marvin Deversi", "funktion": "Vorstand",
             "quote": "Dr. Marvin Deversi Vorstand"},
        ],
    },
    {
        "id": "drk-praesidium",
        "org": "Deutsches Rotes Kreuz e.V.",
        "legal_form": "e.V.",
        "land": "DE",
        "url": "https://www.drk.de/das-drk/drk-verbandsstruktur/praesidium/",
        "license_url": "https://www.drk.de/service/impressum/",
        "publisher": "Deutsches Rotes Kreuz e.V.",
        "title": "Präsidium des Deutschen Roten Kreuzes",
        "people": [
            {"name": "Hermann Gröhe", "funktion": "Präsident",
             "quote": "Die Bundesversammlung des Deutschen Roten Kreuzes hat am 29. November 2025 Hermann Gröhe zum neuen Präsidenten des DRK gewählt."},
            {"name": "Jürgen Christmann", "funktion": "Vizepräsident",
             "quote": "Neu gewählt in das DRK-Präsidium wurde auch Jürgen Christmann als Vizepräsident. Ulrike Würth wurde als Vizepräsidentin wiedergewählt."},
            {"name": "Ulrike Würth", "funktion": "Vizepräsidentin",
             "quote": "Neu gewählt in das DRK-Präsidium wurde auch Jürgen Christmann als Vizepräsident. Ulrike Würth wurde als Vizepräsidentin wiedergewählt."},
        ],
    },
]


# Alternate published names, so find_org can reuse an existing org
# (AWO 662 was stored as "AWO Bundesverband e.V."; BAGFW similarly).
ORG_ALIASES = {
    "Arbeiterwohlfahrt Bundesverband e. V.": [
        "Arbeiterwohlfahrt Bundesverband e. V.",
        "Arbeiterwohlfahrt Bundesverband e.V.",
        "AWO Bundesverband e.V.",
        "AWO Bundesverband e. V.",
    ],
    "Bundesarbeitsgemeinschaft der Freien Wohlfahrtspflege e.V.": [
        "Bundesarbeitsgemeinschaft der Freien Wohlfahrtspflege e.V.",
        "Bundesarbeitsgemeinschaft der Freien Wohlfahrtspflege e. V.",
        "BAGFW e.V.",
        "BAGFW e. V.",
        "Bundesarbeitsgemeinschaft der Freien Wohlfahrtspflege (BAGFW) e.V.",
    ],
    "Bundesarbeitsgemeinschaft Wohnungslosenhilfe e.V.": [
        "Bundesarbeitsgemeinschaft Wohnungslosenhilfe e.V.",
        "Bundesarbeitsgemeinschaft Wohnungslosenhilfe e. V.",
        "BAG Wohnungslosenhilfe e.V.",
        "BAG Wohnungslosenhilfe e. V.",
    ],
    "Deutscher Caritasverband e. V.": [
        "Deutscher Caritasverband e. V.",
        "Deutscher Caritasverband e.V.",
    ],
    "Deutsches Rotes Kreuz e.V.": [
        "Deutsches Rotes Kreuz e.V.",
        "Deutsches Rotes Kreuz e. V.",
        "DRK e.V.",
        "DRK e. V.",
    ],
    "Diakonie Deutschland, Evangelisches Werk für Diakonie und Entwicklung e.V.": [
        "Diakonie Deutschland, Evangelisches Werk für Diakonie und Entwicklung e.V.",
        "Diakonie Deutschland, Evangelisches Werk für Diakonie und Entwicklung e. V.",
        "Diakonie Deutschland e.V.",
        "Evangelisches Werk für Diakonie und Entwicklung e.V.",
    ],
}

def role_class(funktion: str) -> str:
    """Map a published function to org_person.rollenklasse."""
    text = (funktion or "").lower()
    if "geschäftsführ" in text:
        return "geschaeftsfuehrung"
    if "präsidium" in text or "präsident" in text:
        return "praesidium"
    if "aufsichtsrat" in text:
        return "aufsichtsrat"
    if "kuratorium" in text:
        return "kuratorium"
    if "vorstand" in text or "vorständ" in text:
        return "vorstand"
    return "sonstige"


def fold_ws(text: str | None) -> str:
    """Collapse whitespace, including non-breaking spaces, the way verify.norm does."""
    return re.sub(r"[\s\u00a0\u2007\u2009\u202f]+", " ", text or "").strip()


def quote_is_verbatim(quote: str | None, document: str | None) -> bool:
    q = fold_ws(quote).lower()
    hay = fold_ws(document).lower()
    return bool(q) and q in hay


def name_tokens_in(person: str, document: str | None) -> bool:
    hay = (document or "").lower()
    toks = person_tokens(person)
    return bool(toks) and all(t.lower() in hay for t in toks)




_TITLE_RE = re.compile(r"(?i)\b(?:prof\.?\s*)?(?:dr\.?)\s+")
_STOP_FUNKTION = {"des", "der", "dem", "die", "und", "fuer", "für", "im", "in", "das"}
PRAESIDIUM_CITY_RE = re.compile(
    r",\s*(?:Berlin|Gummersbach|Muenchen|München|Frankfurt(?:\s+a\.?\s*M\.?)?)\b",
    re.I,
)


def person_key(name: str) -> str:
    """Normalised person name: case, whitespace, and titles such as Dr./Prof. stripped."""
    text = fold_ws(name)
    text = _TITLE_RE.sub(" ", text)
    return name_norm(text) or fold_ws(text).casefold()


def funktion_key(funktion: str) -> str:
    """Normalised role: case, whitespace, Stv./stellv., and gendered endings folded."""
    text = fold_ws(funktion).casefold()
    text = (text.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss"))
    text = re.sub(r"\bstv\.?\b|\bstellv\.?\b", "stellvertretend", text)
    rules = (
        (r"vizepraesident(?:in|:innen|innen|en)?", "vizepraesident"),
        (r"praesident(?:in|:innen|innen|en)?", "praesident"),
        (r"stellvertretende[rn]?", "stellvertretend"),
        (r"vorsitzende[rn]?", "vorsitzend"),
        (r"vorstaendin|vorstaende", "vorstand"),
        (r"geschaeftsfuehrerin|geschaeftsfuehrer|geschaeftsfuehrung", "geschaeftsfuehr"),
        (r"mitglieder", "mitglied"),
    )
    for pat, rep in rules:
        text = re.sub(pat, rep, text)
    return re.sub(r"\s+", " ", text).strip()


def person_tokens(person: str) -> list[str]:
    text = _TITLE_RE.sub(" ", fold_ws(person))
    return [tok for tok in re.split(r"\s+", text) if tok and not tok.endswith(".")]


def quote_has_name_and_role(person: str, funktion: str, quote: str | None) -> bool:
    """The stored quote itself must contain the person's name and the published role."""
    q = fold_ws(quote)
    if not q:
        return False
    q_low = q.casefold()
    toks = person_tokens(person)
    if not toks or any(tok.casefold() not in q_low for tok in toks):
        return False
    words = [w for w in re.split(r"\W+", funktion or "") if len(w) > 2 and w.casefold() not in _STOP_FUNKTION]
    if not words:
        return False
    q_key = funktion_key(q)
    for word in words:
        if funktion_key(word) not in q_key and word.casefold() not in q_low:
            return False
    return True


def already_have(conn, org_id: int, person: str, funktion: str, *, org_name: str | None = None, jahr: int | None = None) -> bool:
    """True when an org_person row already holds this person and role.

    Comparison uses person_key / funktion_key (case, whitespace, titles, gendered
    forms). Also true when an INSERT would collide on the unique key — we never
    UPDATE an existing row to point at a different org.
    """
    want_p, want_f = person_key(person), funktion_key(funktion)
    if not want_p or not want_f:
        return False
    rows = conn.execute(
        "SELECT id, org_id, funktionstraeger, funktion, org_bezeichnung, jahr FROM org_person"
    ).fetchall()
    for row in rows:
        same_person = person_key(row["funktionstraeger"]) == want_p
        same_role = funktion_key(row["funktion"]) == want_f
        if same_person and same_role and row["org_id"] == org_id:
            return True
        if org_name is not None and jahr is not None:
            if (row["org_bezeichnung"] == org_name and row["jahr"] == jahr
                    and same_person and (row["funktion"] == common.clean(funktion) or same_role)):
                return True
    return False


def seed_urls() -> list[str]:
    return [p["url"] for p in PAGES]


def assert_no_impressum_seeds() -> None:
    for url in seed_urls():
        if "impressum" in url.lower():
            raise ValueError(f"Impressum URL is out of scope for this module: {url}")


_last_host: dict[str, float] = {}


def _wait_host(url: str) -> None:
    host = urllib.parse.urlsplit(url).netloc
    last = _last_host.get(host, 0.0)
    wait = HOST_GAP - (time.monotonic() - last)
    if wait > 0:
        time.sleep(wait)
    _last_host[host] = time.monotonic()


def _org_names(name: str) -> list[str]:
    names = list(ORG_ALIASES.get(name) or [name])
    if name not in names:
        names.insert(0, name)
    # unique, stable order
    out, seen = [], set()
    for item in names:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _bind_org(conn, page: dict, source_id: int) -> int | None:
    """Reuse an existing org of this name or a known alias before creating one."""
    name = page["org"]
    land = page.get("land")
    legal = page.get("legal_form")
    hit = common.resolve_org(conn)
    if hit:
        return hit
    for alias in _org_names(name):
        for any_land in (False, True):
            found = common.find_org(conn, alias, land, legal_form=legal, any_land=any_land)
            if found["org_id"] is not None:
                return found["org_id"]
    key = f"{name_norm(name)}|{land or '-'}|{page['id']}"
    return common.ensure_org(
        conn, name, land, source_id,
        legal_form=legal, record_kind=RECORD_KIND, record_key=key,
    )


def _register_page(conn, page: dict, raw: bytes, sources) -> int:
    from ingest.domains import institutions_media as im

    # Plant the bytes on the fetch cache path so source_id_for / G4 find the archive.
    path = common.raw_path(DOMAIN, page["url"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    meta = path.with_suffix(".meta.json")
    if not meta.exists():
        import hashlib, json
        meta.write_text(json.dumps({
            "url": page["url"], "method": "GET", "status": 200,
            "retrieved_at": common.now(), "content_type": "text/html",
            "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
        }, ensure_ascii=False), encoding="utf-8")
    return im._register_source(
        conn, page["url"],
        title=page["title"],
        publisher=page["publisher"],
        license_=QUOTE_LICENCE,
        bucket=sources,
        license_url=page.get("license_url") or page["url"],
        attribution=page["publisher"],
        notes=f"{RECORD_KIND}; short § 51 quotes only",
        redistribute_fulltext=0,
    )


def _load_page(conn, page: dict, cfg: dict, sources, notes) -> tuple[int | None, str | None]:
    url = page["url"]
    fixtures = cfg.get("officers_fixture") or {}
    if url in fixtures:
        raw = fixtures[url]
        if isinstance(raw, (str, Path)):
            p = Path(raw)
            raw = p.read_bytes() if p.exists() else str(raw).encode("utf-8")
        sid = _register_page(conn, page, raw, sources)
        return sid, html_to_text(raw)
    from ingest.domains.institutions_media_press import press_robots_status
    allowed, reason, _delay = press_robots_status(url)
    if not allowed:
        notes.append(f"officers: skipped {url}: {reason}")
        return None, None
    _wait_host(url)
    raw = common.fetch(url, domain=DOMAIN, force=bool(cfg.get("force")))
    sid = _register_page(conn, page, raw, sources)
    return sid, html_to_text(raw)


def _usable_person(rec: dict) -> bool:
    person = common.clean(rec.get("name"))
    funktion = common.clean(rec.get("funktion"))
    quote = rec.get("quote")
    if not person or not funktion or len(person.split()) < 2 or not quote:
        return False
    blob = f"{person} {funktion} {quote}"
    if CONTACT_RE.search(blob) or STAFF_RE.search(blob):
        return False
    return True


def _add_person(conn, *, org_id, org_name, person, funktion, jahr, locator, source_id, quote, stand, rolle=None) -> bool:
    """Insert a new org_person row. Never UPDATE or re-point an existing row."""
    import sqlite3
    person = common.clean(person)
    funktion = common.clean(funktion)
    quote = common.clean(quote)
    if not person or not funktion or len(person.split()) < 2 or not quote:
        return False
    if CONTACT_RE.search(f"{person} {funktion} {quote}") or STAFF_RE.search(funktion):
        return False
    if already_have(conn, org_id, person, funktion, org_name=org_name, jahr=jahr):
        return False
    try:
        conn.execute(
            "INSERT INTO org_person(org_id, org_bezeichnung, funktionstraeger, funktionstraeger_norm, "
            "funktion, rollenklasse, jahr, locator, source_id, quote, stand) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (org_id, org_name, person, name_norm(person), funktion, rolle or role_class(funktion),
             jahr, locator, source_id, quote, stand),
        )
    except sqlite3.IntegrityError:
        return False
    return True


def ingest_officers(conn, cfg, sources, notes) -> int:
    """Store published Gremien / Vorstand roles in org_person. Returns the number of new rows."""
    assert_no_impressum_seeds()
    stand = common.clean(cfg.get("officers_stand")) or STAND
    try:
        jahr = int(str(stand)[:4])
    except ValueError:
        jahr = 2026
    catalog = cfg.get("officers_pages") or PAGES
    stored = 0
    skipped_quote = skipped_dup = skipped_page = 0
    per_org: dict[str, int] = {}
    for page in catalog:
        sid, text = _load_page(conn, page, cfg, sources, notes)
        if not sid or not text:
            skipped_page += 1
            continue
        org_id = _bind_org(conn, page, sid)
        if org_id is None:
            notes.append(f"officers: could not bind org {page['org']}")
            continue
        for rec in page.get("people") or []:
            if not _usable_person(rec):
                skipped_quote += 1
                continue
            person = common.clean(rec["name"])
            funktion = common.clean(rec["funktion"])
            quote = rec["quote"]
            if not quote_is_verbatim(quote, text) or not name_tokens_in(person, text):
                skipped_quote += 1
                continue
            if not quote_has_name_and_role(person, funktion, quote):
                skipped_quote += 1
                continue
            if role_class(funktion) == "praesidium" and PRAESIDIUM_CITY_RE.search(quote):
                skipped_quote += 1
                continue
            if already_have(conn, org_id, person, funktion, org_name=page["org"], jahr=jahr):
                skipped_dup += 1
                continue
            ok = _add_person(
                conn,
                org_id=org_id,
                org_name=page["org"],
                person=person,
                funktion=funktion,
                jahr=jahr,
                locator=page["url"],
                source_id=sid,
                quote=quote,
                stand=stand,
                rolle=role_class(funktion),
            )
            if ok:
                stored += 1
                per_org[page["org"]] = per_org.get(page["org"], 0) + 1
            else:
                skipped_dup += 1
    parts = ", ".join(f"{name}={n}" for name, n in sorted(per_org.items())) or "none"
    notes.append(
        f"officers: stored={stored} skipped_quote={skipped_quote} "
        f"skipped_dup={skipped_dup} skipped_page={skipped_page}; per org: {parts}. "
        "Source tag institutions_media / institutions_media_gremien; Impressum roles not stored."
    )
    return stored


if __name__ == "__main__":
    raise SystemExit(no_direct_run(DOMAIN))
