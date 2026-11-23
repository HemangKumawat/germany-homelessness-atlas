"""Land-level Wohnungslosenhilfe umbrellas (LAG / Koordination / Fachverband).

Organisation-level only: official name, Land, website and the official page
URL. No people, no private addresses, no Frauenhaus locations. A row is stored
only when the official name appears in a fetched official HTTP 200 page.
Land geography is the 2-digit Land AGS on the sidecar (`land_ags`);
`kreis_ags` stays NULL.
"""

from __future__ import annotations

from ingest.common import LAND_AGS, UA, clean, fetch, raw_path
from ingest.domains.institutions_media_orgs import ensure_org_tables, store_landscape_org
from ingest.domains.institutions_media_rechnungshof import RESERVED_LICENCE, fold_text

AMTLICH = (  # Lead review 2026-11-21: a Diakonie (private association) page is never an amtliches Werk
    'Rechte vorbehalten: Seite eines Wohlfahrtsverbands (eingetragener Verein), kein amtliches Werk nach § 5 UrhG; '
    'keine offene Lizenz angegeben. Nur Fakten auf Organisationsebene und Kurzzitate nach § 51 UrhG'
)

DOMAIN = "institutions_media"

CATALOG: list[dict] = [
    {
        "name": "Koordination Wohnungslosenhilfe Nordbayern",
        "land": "BY",
        "website": "https://wohnungslosenhilfe-bayern.de/",
        "source_url": "https://wohnungslosenhilfe-bayern.de/?ueberunstax=kontakt",
        "license_url": "https://wohnungslosenhilfe-bayern.de/?ueberunstax=impressum",
        "publisher": "Koordination Wohnungslosenhilfe Nord- und Südbayern",
        "attribution": "Koordination Wohnungslosenhilfe Nord- und Südbayern",
        "source_title": "Kontakt – Wohnungslosenhilfe Bayern (Koordination Nord- und Südbayern)",
        "source_notes": (
            "Official Koordination page. Impressum: 'Eine Veröffentlichung bzw. "
            "Weiterverwendung der vorliegenden Texte im öffentlichen Raum bedarf "
            "ebenfalls der Zustimmung.'"
        ),
        "subtype": "land_koordination",
    },
    {
        "name": "Koordination Wohnungslosenhilfe Südbayern",
        "land": "BY",
        "website": "https://wohnungslosenhilfe-bayern.de/",
        "source_url": "https://wohnungslosenhilfe-bayern.de/?ueberunstax=kontakt",
        "license_url": "https://wohnungslosenhilfe-bayern.de/?ueberunstax=impressum",
        "publisher": "Koordination Wohnungslosenhilfe Nord- und Südbayern",
        "attribution": "Koordination Wohnungslosenhilfe Nord- und Südbayern",
        "source_title": "Kontakt – Wohnungslosenhilfe Bayern (Koordination Nord- und Südbayern)",
        "source_notes": (
            "Official Koordination page. Impressum: 'Eine Veröffentlichung bzw. "
            "Weiterverwendung der vorliegenden Texte im öffentlichen Raum bedarf "
            "ebenfalls der Zustimmung.'"
        ),
        "subtype": "land_koordination",
    },
    {
        "name": "Arbeitskreis Wohnungsnot",
        "land": "BE",
        "website": "https://www.ak-wohnungsnot.de/",
        "source_url": "https://www.ak-wohnungsnot.de/arbeitskreis-wohnungsnot-ueber-uns",
        "license_url": "https://www.ak-wohnungsnot.de/impressum",
        "publisher": "Arbeitskreis Wohnungsnot / Förderverein der Wohnungslosenhilfe in Berlin e. V.",
        "attribution": "Arbeitskreis Wohnungsnot",
        "source_title": "Arbeitskreis Wohnungsnot: Über uns",
        "source_notes": (
            "Official Über-uns page of the Berlin Träger network. The impressum "
            "legal entity is the Förderverein der Wohnungslosenhilfe in Berlin e. V.; "
            "the published organisation name is Arbeitskreis Wohnungsnot. "
            "Impressum marks the site © Arbeitskreis Wohnungsnot."
        ),
        "legal_form": "e.V.",
        "subtype": "land_arbeitskreis",
    },
    {
        "name": "Evangelischer Fachverband Wohnungslosenhilfe",
        "land": "NW",
        "website": (
            "https://www.diakonie-rwl.de/themen/armut-und-soziale-notlagen/"
            "fachverbaende/evangelischer-fachverband-wohnungslosenhilfe"
        ),
        "source_url": (
            "https://www.diakonie-rwl.de/themen/armut-und-soziale-notlagen/"
            "fachverbaende/evangelischer-fachverband-wohnungslosenhilfe"
        ),
        "license_url": "https://www.diakonie-rwl.de/impressum",
        "publisher": "Diakonisches Werk Rheinland-Westfalen-Lippe e. V.",
        "attribution": "Diakonie RWL",
        "source_title": "Evangelischer Fachverband Wohnungslosenhilfe (Diakonie RWL)",
        "source_notes": (
            "Official Diakonie RWL Fachverband page. Impressum: 'Copyright - Rechte am "
            "Content (Inhalt) dieser Website' and '„Diakonie RWL“ überträgt keine Rechte "
            "an jeglichem Website-Content'."
        ),
        "subtype": "land_fachverband",
    },
    {
        "name": "Fachverband Evangelische Wohnungsnotfallhilfe und Straffälligenhilfe",
        "land": "BY",
        "website": (
            "https://www.diakonie-bayern.de/ueber-die-diakonie/die-fachverbaende/"
            "fachverband-evangelische-wohnungsnotfallhilfe-und-straffaelligenhilfe"
        ),
        "source_url": (
            "https://www.diakonie-bayern.de/ueber-die-diakonie/die-fachverbaende/"
            "fachverband-evangelische-wohnungsnotfallhilfe-und-straffaelligenhilfe"
        ),
        "license_url": "https://www.diakonie-bayern.de/impressum",
        "publisher": "Diakonisches Werk der Evangelisch-Lutherischen Kirche in Bayern e.V.",
        "attribution": "Diakonie Bayern",
        "source_title": "Fachverband Evangelische Wohnungsnotfallhilfe und Straffälligenhilfe – Diakonie Bayern",
        "source_notes": (
            "Official Diakonie Bayern Fachverband page. The impressum identifies "
            "Diakonisches Werk der Evangelisch-Lutherischen Kirche in Bayern e.V. "
            "and states no separate text-reuse terms, so the cited official name "
            "and URL are stored as an official work under § 5 UrhG."
        ),
        "license": AMTLICH,
        "subtype": "land_fachverband",
    },
    {
        "name": "Evangelischer Fachverband Wohnungslosenhilfe und Existenzsicherung e.V.",
        "land": "NI",
        "website": "https://www.diakonie-in-niedersachsen.de/ueber-uns/bereiche/inklusion/wohnungslosenhilfe",
        "source_url": "https://www.diakonie-in-niedersachsen.de/ueber-uns/bereiche/inklusion/wohnungslosenhilfe",
        "license_url": "https://www.diakonie-in-niedersachsen.de/impressum",
        "publisher": "Diakonisches Werk evangelischer Kirchen in Niedersachsen e.V.",
        "attribution": "Diakonie in Niedersachsen",
        "source_title": "Wohnungslosenhilfe – Diakonie in Niedersachsen",
        "source_notes": (
            "Official Diakonie Niedersachsen page naming the Fachverband and its "
            "Geschäftsführung. Impressum: 'Alle auf unseren Seiten verwendeten Bilder, "
            "Fotos, Logos, Texte etc. unterliegen dem Copyright des Diakonischen Werks "
            "evangelischer Kirchen in Niedersachsen e.V. bzw. von Dritten. Sie dürfen "
            "nicht bzw. nur nach Rücksprache mit der Redaktion weiter verwendet werd[en].'"
        ),
        "legal_form": "e.V.",
        "subtype": "land_fachverband",
    },
]


def _fetch(url: str, *, force: bool) -> bytes:
    return fetch(
        url,
        domain=DOMAIN,
        force=force,
        headers={"User-Agent": UA, "Accept": "text/html,*/*"},
        binary=True,
    )


def page_text(url: str, *, force: bool) -> str:
    raw = _fetch(url, force=force)
    if isinstance(raw, (bytes, bytearray)):
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            return raw.decode("latin-1", "replace")
    return str(raw)


def name_on_page(name: str, document: str) -> bool:
    return fold_text(name).casefold() in fold_text(document).casefold()


def land_ags(land: str) -> str | None:
    return LAND_AGS.get(land)


def ingest_lags(conn, cfg, sources, notes) -> int:
    """Store verified Land-level Wohnungslosenhilfe umbrellas. Returns org count."""
    force = bool(cfg.get("force"))
    ensure_org_tables(conn)
    stored = 0
    skipped = 0
    for item in CATALOG:
        url = item["source_url"]
        try:
            text = page_text(url, force=force)
        except Exception as exc:
            notes.append(
                f"LAG page failed for {item['name']}: {type(exc).__name__}: {str(exc)[:160]}"
            )
            skipped += 1
            continue
        if not name_on_page(item["name"], text):
            # The NI page uses the genitive 'Evangelischen Fachverbandes ...'
            alt = item["name"].replace(
                "Evangelischer Fachverband Wohnungslosenhilfe und Existenzsicherung e.V.",
                "Evangelischen Fachverbandes Wohnungslosenhilfe und Existenzsicherung e.V.",
            )
            if alt == item["name"] or not name_on_page(alt, text):
                notes.append(
                    f"LAG {item['name']} not stored; official name was not found on {url}"
                )
                skipped += 1
                continue
        rec = {
            "name": item["name"],
            "land": item["land"],
            "role": "umbrella",
            "subtype": item.get("subtype") or "land_umbrella",
            "org_type": "nonprofit",
            "legal_form": item.get("legal_form"),
            "website": item["website"],
            "source_url": url,
            "source_title": item["source_title"],
            "publisher": item["publisher"],
            "license": item.get("license") or RESERVED_LICENCE,
            "license_url": item["license_url"],
            "attribution": item["attribution"],
            "source_notes": item["source_notes"],
            "redistribute_fulltext": 0,
        }
        org_id = store_landscape_org(conn, rec, sources=sources)
        if not org_id:
            notes.append(f"LAG {item['name']} store_landscape_org returned False")
            skipped += 1
            continue
        # Record the official 2-digit Land AGS on the sidecar only (never as kreis_ags).
        ags = land_ags(item["land"])
        if ags:
            conn.execute(
                "UPDATE institutions_media_org SET land_ags=? WHERE org_id=?",
                (ags, org_id),
            )
        stored += 1
    notes.append(
        f"Land-level Wohnungslosenhilfe umbrellas stored={stored} skipped={skipped}. "
        "Stored only where the official name appears on a fetched official HTTP 200 page. "
        "Organisation level only (no people). Land AGS is on institutions_media_org.land_ags; "
        "kreis_ags is NULL. "
        "No single official national LAG directory exists (BAG W membership does not list them). "
        "Gaps this pass: no dedicated official LAG website was verified for BW, HB, HH, HE, "
        "MV, RP, SL, SN, ST, SH or TH. Party working groups and unofficial personal sites "
        "were not stored. Liga der Freien Wohlfahrtspflege pages (e.g. Sachsen, Baden-Württemberg) "
        "are general welfare umbrellas, not Wohnungslosenhilfe LAGs, and were not stored as such."
    )
    return stored


if __name__ == "__main__":
    from ingest.common import no_direct_run
    raise SystemExit(no_direct_run("institutions_media"))
