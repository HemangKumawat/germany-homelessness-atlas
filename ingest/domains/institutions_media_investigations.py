"""Curated major press investigations on homelessness in Germany.

Each row is metadata plus a short § 51 UrhG quotation. Full article text is
never stored or redistributed unless a source is openly licensed (none of the
pieces in this pass stated a CC licence, including CORRECTIV). Private
individuals who are not in public roles are not named in stored fields.

This module never opens data/atlas.db.
"""
from __future__ import annotations

import re
from html import unescape

from ingest import common
from ingest.common import clean, upsert
from ingest.domains.institutions_media_rechnungshof import RESERVED_LICENCE

DOMAIN = "institutions_media"

INVESTIGATION_DDL = """
CREATE TABLE IF NOT EXISTS institutions_media_investigation (
  url TEXT PRIMARY KEY,
  doc_id INTEGER,
  outlet TEXT,
  published TEXT,
  quote TEXT,
  source_id INTEGER
);
"""

# First names of private individuals that appeared in candidate pages and must
# never be stored. Public officials and named experts are not on this list.
PRIVATE_GIVEN_RE = re.compile(
    r"(?i)\b(?:Frank|Ulf|Kurt|Chris|Sandro|Andr[eé]|Manuela|Serge|Joe|Ulli)\b"
)

# Quality-over-quantity catalogue. quote must appear verbatim on the fetched page.
CATALOG: list[dict] = [
    {
        "url": "https://correctiv.org/faktencheck/2023/03/17/nein-es-sind-nicht-400-000-deutsche-wohnunglos/",
        "outlet": "CORRECTIV",
        "title": "Nein, es sind nicht 400.000 Deutsche wohnungslos",
        "published": "2023-03-17",
        "land": "DE",
        "quote": "Es gab nach Schätzungen der Bundesarbeitsgemeinschaft Wohnungslosenhilfe 2020 zwar rund 400.000 wohnungslose Menschen, davon sind jedoch nicht alle Deutsche.",
    },
    {
        "url": "https://correctiv.org/faktencheck/gesellschaft/2019/07/10/veraltete-zahlen-zu-wohnungs-und-obdachlosen-im-umlauf/",
        "outlet": "CORRECTIV",
        "title": "Veraltete Zahlen zu Wohnungs- und Obdachlosen im Umlauf",
        "published": "2019-07-10",
        "land": "DE",
        "quote": "Obdachlos ist, wer wohnungslos ist und im öffentlichen Raum oder zum Beispiel in einer Notunterkunft übernachtet.",
    },
    {
        "url": "https://correctiv.org/fakten-check/2019/02/01/doch-auch-deutsche-wohnungslose-haben-ein-anrecht-auf-unterbringung-3/",
        "outlet": "CORRECTIV",
        "title": "Doch, auch deutsche Wohnungslose haben ein Anrecht auf Unterbringung",
        "published": "2019-02-01",
        "land": "DE",
        "quote": "Die Begründung: Unfreiwillige Obdachlosigkeit gefährdet die Grund- und Menschenrechte.",
    },
    {
        "url": "https://www.ndr.de/fernsehen/sendungen/panorama_die_reporter/Nie-wieder-obdachlos,sendung1322330.html",
        "outlet": "NDR Panorama – Die Reporter",
        "title": "Nie wieder obdachlos?",
        "published": "2023-02-09",
        "land": "DE",
        "quote": "EU-weit hat man es sich zum Ziel gesetzt, alle wohnungslosen Menschen unterzubringen.",
    },
    {
        "url": "https://www.ndr.de/fernsehen/sendungen/panorama_die_reporter/panorama-die-reporter,sendung-67822.html",
        "outlet": "NDR Panorama – Die Reporter",
        "title": "Beleidigt, geschlagen, gejagt: Wer bedroht Wohnungslose?",
        "published": "2026-04-29",
        "land": "DE",
        "quote": "Die Zahl der wohnungslosen Menschen, die Opfer von Gewalt werden, steigt seit Jahren.",
    },
    {
        "url": "https://www.deutschlandfunk.de/obdachlosigkeit-in-deutschland-verschaemt-versteckt-100.html",
        "outlet": "Deutschlandfunk",
        "title": "Obdachlosigkeit in Deutschland – Verschämt, versteckt, verdrängt – wohnungslose Frauen",
        "published": "2019-01-08",
        "land": "DE",
        "quote": "Viele von ihnen leben in einer verdeckten Wohnungslosigkeit - sie versuchen, ihren Status zu verbergen.",
    },
    {
        "url": "https://www.deutschlandfunk.de/obdachlosigkeit-leben-am-unteren-rand-100.html",
        "outlet": "Deutschlandfunk",
        "title": "Obdachlosigkeit – Leben am unteren Rand",
        "published": "2018-01-23",
        "land": "BE",
        "quote": "Die Wohnungslosigkeit ist die Vorstufe zur Obdachlosigkeit.",
    },
    {
        "url": "https://www.zdf.de/video/dokus/zdf-info-100/leben-auf-der-strasse-obdachlos-und-abgehaengt--100",
        "outlet": "ZDFinfo",
        "title": "Leben auf der Straße – Obdachlos und abgehängt",
        "published": "2022-03-10",
        "land": "DE",
        "quote": "Die Dokumentation begleitet Wohnungslose in ganz Deutschland und sucht nach Wegen aus der Not.",
    },
    {
        "url": "https://www.zdf.de/video/reportagen/zdf-reportage-jung-und-102/jung-und-obdachlos-102",
        "outlet": "ZDF",
        "title": "Jung und obdachlos",
        "published": "2025-05-11",
        "land": "DE",
        "quote": "Zu obdachlosen Jugendlichen gibt es keine belastbaren Zahlen.",
    },
    {
        "url": "https://www.spiegel.de/panorama/gesellschaft/obdachlosigkeit-in-deutschland-37-400-menschen-leben-laut-studie-auf-der-strasse-a-7503df2c-d1f2-4489-b1c1-2270467e8023",
        "outlet": "DER SPIEGEL",
        "title": "Obdachlosigkeit in Deutschland: 37.400 Menschen leben laut Studie auf der Straße",
        "published": "2022-09-27",
        "land": "DE",
        "quote": "Allerdings werden viele »verdeckt Wohnungslose« nicht erfasst.",
    },
    {
        "url": "https://www1.wdr.de/nrw/nah-dran-wohungslosigkeit-100.html",
        "outlet": "WDR",
        "title": "Immer mehr Wohnungslose: Schicksal oder Systemfehler?",
        "published": "2025-11-21",
        "land": "NW",
        "quote": "Laut Hochrechnungen der Bundesarbeitsgemeinschaft Wohnungslosenhilfe (BAG W) waren im vergangenen Jahr mindestens 1.029.000 Menschen in Deutschland wohnungslos.",
    },
    {
        "url": "https://taz.de/Versorgung-von-obdachlosen-Menschen/!6128049/",
        "outlet": "taz",
        "title": "Versorgung von obdachlosen Menschen: Gesundheit gibt es nur mit Meldeadresse",
        "published": "2025-11-23",
        "land": "HH",
        "quote": "Ein Großteil der obdachlosen Menschen leidet an gesundheitlichen Beeinträchtigungen, vermeidet aber, medizinische Hilfe in Anspruch zu nehmen.",
    },
    {
        "url": "https://taz.de/Wohnungslosigkeit-in-Deutschland/!5971851/",
        "outlet": "taz",
        "title": "Wohnungslosigkeit in Deutschland: Eine halbe Million ohne Unterkunft",
        "published": "2023-11-08",
        "land": "DE",
        "quote": "Rund 50.000 Menschen lebten danach ganz ohne Unterkunft als Obdachlose auf der Straße.",
    },
    {
        "url": "https://taz.de/Bericht-zu-Wohnungslosigkeit/!6032591/",
        "outlet": "taz",
        "title": "Bericht zu Wohnungslosigkeit: Ganz jung und ohne Wohnung",
        "published": "2024-09-10",
        "land": "DE",
        "quote": "Wohnungslosigkeit, das ist ein gängiges Missverständnis, heißt nicht zwingend, dass Menschen auf der Straße leben.",
    },
    {
        "url": "https://www.sueddeutsche.de/politik/portraetserie-sie-sind-das-volk-warum-gibt-es-nicht-genug-betten-fuer-obdachlose-1.3673980",
        "outlet": "Süddeutsche Zeitung",
        "title": "Warum gibt es nicht genug Betten für Obdachlose?",
        "published": "2017-09-22",
        "land": "DE",
        "quote": "Die Lage von Wohnungslosen war in diesem Bundestagswahlkampf kein Thema, wie auch schon in denen zuvor nicht.",
    },
    {
        "url": "https://www.rbb-online.de/unternehmen/presse/presseinformationen/programm/2019/07/20190708-wohnungslos-wenn-familien-kein-zuhause-haben.html",
        "outlet": "rbb / Das Erste",
        "title": "Wohnungslos – Wenn Familien kein Zuhause haben",
        "published": "2019-07-08",
        "land": "DE",
        "quote": "Immer mehr Familien mit kleinem Einkommen und Alleinerziehende sind betroffen, leben in einer Notunterkunft, ohne Perspektive.",
    },
    {
        "url": "https://www.ardmediathek.de/video/swr-aktuell-360-grad/auf-der-strasse-ueberleben-obdachlos-und-vergessen/swr/Y3JpZDovL3N3ci5kZS9hZXgvbzIzMTU3OTI",
        "outlet": "SWR Aktuell 360 Grad",
        "title": "Auf der Straße überleben: Obdachlos und vergessen!?",
        "published": "2026-04-23",
        "land": "RP",
        "quote": "In Deutschland sind hunderttausende Menschen von Wohnungs- und Obdachlosigkeit betroffen.",
    },
    {
        "url": "https://www.ardmediathek.de/video/report-mainz/leerstand-trotz-wohnungsnot/das-erste/Y3JpZDovL3N3ci5kZS9hZXgvbzE4NTQ0Nzc",
        "outlet": "Report Mainz / Das Erste",
        "title": "Leerstand trotz Wohnungsnot",
        "published": "2023-05-09",
        "land": "DE",
        "quote": "In Deutschland fehlt es an Wohnraum.",
    },
    {
        "url": "https://www.tagesschau.de/inland/gesellschaft/wohnungslose-deutschland-108.html",
        "outlet": "tagesschau",
        "title": "Zahl der Wohnungslosen erneut gestiegen",
        "published": "2025-11-17",
        "land": "DE",
        "quote": "Zu den häufigsten Auslösern von Wohnungslosigkeit in Deutschland zählen laut BAGW Miet- und Energieschulden, Konflikte im Wohnumfeld, Trennung oder Scheidung.",
    },
    {
        "url": "https://www.tagesschau.de/inland/gesellschaft/wohnungslosigkeit-frauen-100.html",
        "outlet": "tagesschau",
        "title": "Wie ein Berliner Projekt wohnungslosen Frauen hilft",
        "published": "2025-10-09",
        "land": "BE",
        "quote": "Die Mitarbeiterinnen verschaffen wohnungslosen Frauen ein Zuhause, egal in welcher wirtschaftlichen Lage sie sich befinden.",
    },
    {
        "url": "https://www.mdr.de/video/mdr-videos/d/video-exactly-leben-und-sterben-auf-der-strasse-100.html",
        "outlet": "MDR exakt",
        "title": "Leben und Sterben auf der Straße",
        "published": "2025-02-03",
        "land": "ST",
        "quote": "Daniel Tautz hat ein Jahr lang wohnungslose Hallenser begleitet und dabei ein innovatives Hilfsprojekt kennengelernt.",
    },
]


def _im():
    from ingest.domains import institutions_media as module
    return module


def _fetch(url: str, *, force: bool = False) -> bytes:
    return common.fetch(url, domain=DOMAIN, force=force)


def ensure_investigation_tables(conn) -> None:
    conn.executescript(INVESTIGATION_DDL)
    _im().ensure_source_extensions(conn)


def stored_fields_name_ok(*parts: str | None) -> bool:
    hay = " ".join(part or "" for part in parts)
    return not PRIVATE_GIVEN_RE.search(hay)


def quote_in_page(quote: str, page_text: str) -> bool:
    def norm(value: str) -> str:
        return re.sub(r"\s+", " ", value or "").strip()
    needle, hay = norm(quote), norm(page_text)
    return bool(needle) and needle in hay


def page_text(raw: bytes) -> str:
    html = raw.decode("utf-8", "replace")
    html = re.sub(r"<script[\s\S]*?</script>|<style[\s\S]*?</style>|<noscript[\s\S]*?</noscript>", " ", html, flags=re.I)
    html = re.sub(r"<br\s*/?>", "\n", html, flags=re.I)
    html = re.sub(r"</(?:p|h[1-6]|li|div|section|article)>", "\n", html, flags=re.I)
    text = unescape(re.sub(r"<[^>]+>", " ", html))
    return re.sub(r"\s+", " ", text)


def store_investigation(conn, rec: dict, *, sources) -> bool:
    ensure_investigation_tables(conn)
    url = clean(rec.get("url"))
    title = clean(rec.get("title"))
    outlet = clean(rec.get("outlet"))
    quote = clean(rec.get("quote"))
    licence = clean(rec.get("license")) or RESERVED_LICENCE
    published = clean(rec.get("published"))
    land = rec.get("land") if rec.get("land") in (set(_im().LANDS) | {"DE"}) else "DE"
    if not url or not title or not outlet or not quote or not licence:
        return False
    if not stored_fields_name_ok(title, outlet, quote, rec.get("author")):
        return False
    source_id = _im()._register_source(
        conn, url,
        title=title,
        publisher=outlet,
        license_=licence,
        bucket=sources,
        license_url=clean(rec.get("license_url")),
        attribution=outlet,
        notes=clean(rec.get("source_notes")) or (
            "Short § 51 UrhG quotation only; full text not redistributed. "
            "CORRECTIV Steal Our Stories is not a Creative Commons licence."
            if outlet == "CORRECTIV" else
            "Short § 51 UrhG quotation only; full text not redistributed."
        ),
        redistribute_fulltext=0 if rec.get("redistribute_fulltext", 0) == 0 else 1,
    )
    upsert(conn, "doc", {
        "kind": "investigation",
        "title": title,
        "url": url,
        "herausgeber": outlet,
        "urheber": None,
        "veroeffentlicht": published,
        "ort": None,
        "land": land,
        "zusammenfassung": quote,
        "source_id": source_id,
    }, ["url"])
    row = conn.execute("SELECT id FROM doc WHERE url=?", (url,)).fetchone()
    if not row:
        return False
    upsert(conn, "institutions_media_investigation", {
        "url": url,
        "doc_id": row["id"],
        "outlet": outlet,
        "published": published,
        "quote": quote,
        "source_id": source_id,
    }, ["url"])
    return True


def ingest_investigations(conn, cfg, sources, notes) -> int:
    ensure_investigation_tables(conn)
    force = bool(cfg.get("force"))
    stored = 0
    missing_quote = 0
    failed = 0
    skipped_names = 0
    for rec in CATALOG:
        rec = dict(rec)
        rec.setdefault("license", RESERVED_LICENCE)
        rec.setdefault("redistribute_fulltext", 0)
        if not stored_fields_name_ok(rec.get("title"), rec.get("quote")):
            skipped_names += 1
            continue
        try:
            raw = _fetch(rec["url"], force=force)
        except Exception as exc:
            failed += 1
            notes.append(f"Investigation fetch failed {rec['outlet']}: {type(exc).__name__}")
            continue
        if not quote_in_page(rec["quote"], page_text(raw)):
            missing_quote += 1
            notes.append(f"Investigation quote not found on page, not stored: {rec['url']}")
            continue
        if store_investigation(conn, rec, sources=sources):
            stored += 1
    notes.append(
        f"Press investigations stored={stored} catalog={len(CATALOG)} "
        f"fetch_failed={failed} quote_missing={missing_quote} name_skipped={skipped_names}. "
        "All stored rows use reserved-rights terms and redistribute_fulltext=0 "
        "(no CC licence was stated, including CORRECTIV). "
        "Gaps: DIE ZEIT article HTTP 403; Spiegel+ feature had no usable free-text quote; "
        "ZDFzoom 'Leben ohne Zuhause' was only found as a presseportal.de notice, not an official zdf.de page; "
        "FAZ and other paywalled newspaper investigations were not added."
    )
    return stored



if __name__ == "__main__":
    from ingest.common import no_direct_run
    raise SystemExit(no_direct_run("institutions_media"))
