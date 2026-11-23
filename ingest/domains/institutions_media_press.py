"""Press and public-broadcaster media rows for institutions_media.

Discovers official articles from structured sources (RSS/Atom, XML and news
sitemaps, the tagesschau search API, Destatis/Bundestag feeds, official HTML
search and press-archive indexes) about Wohnungslosigkeit, Obdachlosigkeit,
Kältehilfe and Notunterkünfte. Each stored row is headline, date, outlet, URL and a short topic tag only.
No quotation and no full text are stored. One source row is registered per
outlet (rights reserved, facts only, redistribute_fulltext=0).

This module never opens data/atlas.db.
"""
from __future__ import annotations

import gzip
import json
import re
import time
import urllib.parse
import urllib.robotparser
import xml.etree.ElementTree as ET
from collections import defaultdict
from html import unescape
from typing import Callable

from ingest import common
from ingest.common import LAND_AGS, UA, clean, upsert
from ingest.domains.institutions_media_rechnungshof import RESERVED_LICENCE, trim_quote

DOMAIN = "institutions_media"
KIND = "article"
MIN_HOST_INTERVAL = 3.0
# Official Tagesschau API terms: no more than 60 requests per hour.
HOST_INTERVAL = {
    "www.tagesschau.de": 61.0,
}
REDIS_NOTE = (
    "Facts and metadata only; no article full text or quotations stored. "
    "Rights reserved as stated by the publisher."
)
FACTS_LICENCE = (
    "Rechte vorbehalten (Impressum zitiert); nur Fakten und Metadaten, "
    "Volltext nicht weiterverbreitet"
)

TOPIC_RE = re.compile(
    r"(?i)\b(?:"
    r"wohnungslos(?:e|er|en|igkeit|enhilfe)?"
    r"|obdachlos(?:e|er|en|igkeit)?"
    r"|k(?:ä|ae|a)lte[\s-]?hilfe|k(?:ä|ae|a)lte[\s-]?bus|winternothilfe"
    r"|notunterkunft|notunterk[üu]nfte|notunterkuenfte"
    r"|notschlafstelle|notschlafstellen"
    r"|wohnungsnotfall(?:hilfe|s)?"
    r"|housing[\s\-_]?first|housingfirst"
    r"|stra[ßs]enobdachlosigkeit"
    r")\b"
)
WOHNUNGSNOT_RE = re.compile(r"(?i)wohnungsnot")
OBDACH_RE = re.compile(r"(?i)obdach")

# Tight terms only; "Wohnungsnot" alone is not enough.
TOPIC_TERMS = (
    "Wohnungslosigkeit",
    "Obdachlosigkeit",
    "Wohnungslosenhilfe",
    "Wohnungslose",
    "Wohnungsloser",
    "wohnungslos",
    "Obdachlose",
    "Obdachloser",
    "obdachlos",
    "Kältehilfe",
    "Kaeltehilfe",
    "Kältebus",
    "Kaeltebus",
    "Winternothilfe",
    "Notunterkunft",
    "Notunterkünfte",
    "Notschlafstelle",
    "Notschlafstellen",
    "Wohnungsnotfall",
    "Wohnungsnotfallhilfe",
    "Housing First",
    "Straßenobdachlosigkeit",
)

PUBLIC_ROLE_RE = re.compile(
    r"(?i)\b(?:"
    r"bundeskanzler(?:in)?"
    r"|bundespr[äa]sident(?:in)?"
    r"|ministerpr[äa]sident(?:in)?"
    r"|regierende[rn]?\s+b[üu]rgermeister(?:in)?"
    r"|oberb[üu]rgermeister(?:in)?"
    r"|b[üu]rgermeister(?:in)?"
    r"|senator(?:in)?"
    r"|staatsminister(?:in)?"
    r"|staatssekret[äa]r(?:in)?"
    r"|sozialdezernent(?:in)?"
    r"|dezernent(?:in)?"
    r"|landrat|landr[äa]tin"
    r"|bundestagspr[äa]sident(?:in)?"
    r"|landtagspr[äa]sident(?:in)?"
    r"|abgeordnete[rn]?"
    r"|md[lb]"
    r"|sprecher(?:in)?"
    r"|intendant(?:in)?"
    r"|pr[äa]sident(?:in)"
    r"|minister(?:in)?"
    r"|stadtrat|stadtr[äa]tin"
    r"|sozialsenator(?:in)?"
    r")\b"
)

PRIVATE_HINT_RE = re.compile(
    r"(?i)(?:\b(?:herr|frau|fräulein)\s+[A-ZÄÖÜ]"
    r"|\b[A-ZÄÖÜ][a-zäöüß]+(?:-[A-ZÄÖÜ][a-zäöüß]+)?\s+[A-ZÄÖÜ]\."
    r"|\b(?:ich heiße|mein name ist|ich bin seit|sagt\s+[A-ZÄÖÜ][a-zäöüß]+\s+[A-ZÄÖÜ][a-zäöüß]+))"
)

PAYWALL_RE = re.compile(
    r"(?i)\b(?:jetzt abonnieren|plus-artikel|paywall|nur f[üu]r abonnent"
    r"|login um weiterzulesen|artikel ist nur mit abonnement)\b"
)

CITY_KREIS = {
    "Berlin": ("BE", "11000"),
    "Hamburg": ("HH", "02000"),
    "München": ("BY", "09162"),
    "Munich": ("BY", "09162"),
    "Köln": ("NW", "05315"),
    "Cologne": ("NW", "05315"),
    "Frankfurt": ("HE", "06412"),
    "Frankfurt am Main": ("HE", "06412"),
    "Bremen": ("HB", "04011"),
    "Dortmund": ("NW", "05913"),
    "Dresden": ("SN", "14612"),
    "Düsseldorf": ("NW", "05111"),
    "Essen": ("NW", "05113"),
    "Hannover": ("NI", "03241"),
    "Leipzig": ("SN", "14713"),
    "Nürnberg": ("BY", "09564"),
    "Stuttgart": ("BW", "08111"),
    "Bochum": ("NW", "05911"),
    "Duisburg": ("NW", "05112"),
    "Saarbrücken": ("SL", "10041"),
    "Kiel": ("SH", "01002"),
    "Magdeburg": ("ST", "15003"),
    "Halle (Saale)": ("ST", "15002"),
    "Erfurt": ("TH", "16051"),
    "Mainz": ("RP", "07315"),
    "Potsdam": ("BB", "12054"),
    "Augsburg": ("BY", "09761"),
    "Würzburg": ("BY", "09663"),
    "Regensburg": ("BY", "09362"),
    "Ingolstadt": ("BY", "09161"),
}

# Alternative spellings / URL slugs map onto the canonical CITY_KREIS name
# so "Köln" plus "koeln" counts as one city, not two.
CITY_NAME_ALIASES = {
    "Munich": "München",
    "Cologne": "Köln",
    "Muenchen": "München",
    "Koeln": "Köln",
    "Duesseldorf": "Düsseldorf",
    "Saarbruecken": "Saarbrücken",
    "Nuernberg": "Nürnberg",
    "Wuerzburg": "Würzburg",
    "Halle/Saale": "Halle (Saale)",
    "Halle an der Saale": "Halle (Saale)",
}

LAND_NAMES = {
    "Schleswig-Holstein": "SH",
    "Hamburg": "HH",
    "Niedersachsen": "NI",
    "Bremen": "HB",
    "Nordrhein-Westfalen": "NW",
    "NRW": "NW",
    "Hessen": "HE",
    "Rheinland-Pfalz": "RP",
    "Baden-Württemberg": "BW",
    "Bayern": "BY",
    "Saarland": "SL",
    "Berlin": "BE",
    "Brandenburg": "BB",
    "Mecklenburg-Vorpommern": "MV",
    "Sachsen": "SN",
    "Sachsen-Anhalt": "ST",
    "Thüringen": "TH",
}

# Official structured sources. HTML search indexes are used only where no
# RSS/API search is known. Items are topic-filtered before an article is fetched.
FEEDS: list[dict] = [
    # Bundestag
    {
        "id": "bt-hib",
        "kind": "rss",
        "publisher": "Deutscher Bundestag (hib)",
        "url": "https://www.bundestag.de/static/appdata/includes/rss/hib.rss",
        "license_url": "https://www.bundestag.de/impressum",
        "land": "DE",
    },
    {
        "id": "bt-presse",
        "kind": "rss",
        "publisher": "Deutscher Bundestag",
        "url": "https://www.bundestag.de/static/appdata/includes/rss/pressemitteilungen.rss",
        "license_url": "https://www.bundestag.de/impressum",
        "land": "DE",
    },
    # Destatis
    {
        "id": "destatis-rss",
        "kind": "rss",
        "publisher": "Statistisches Bundesamt (Destatis)",
        "url": "https://www.destatis.de/SiteGlobals/Functions/RSSFeed/DE/RSSNewsfeed/Aktuell.xml",
        "license_url": "https://www.destatis.de/DE/Service/Impressum/_inhalt.html",
        "land": "DE",
    },
    {
        "id": "destatis-search",
        "kind": "html_search",
        "publisher": "Statistisches Bundesamt (Destatis)",
        "url": (
            "https://www.destatis.de/SiteGlobals/Forms/Suche/Presse/DE/Pressesuche_Formular_2.html"
            "?templateQueryString={q}"
        ),
        "license_url": "https://www.destatis.de/DE/Service/Impressum/_inhalt.html",
        "land": "DE",
        "link_host": "www.destatis.de",
        "link_must": "/Presse/Pressemitteilungen/",
    },
    {
        "id": "destatis-topic",
        "kind": "html_index",
        "publisher": "Statistisches Bundesamt (Destatis)",
        "url": "https://www.destatis.de/DE/Themen/Gesellschaft-Umwelt/Soziales/Wohnungslosigkeit/_inhalt.html",
        "license_url": "https://www.destatis.de/DE/Service/Impressum/_inhalt.html",
        "land": "DE",
        "link_host": "www.destatis.de",
        "link_must": "/Presse/Pressemitteilungen/",
        "trust_index": True,
    },
    {
        "id": "tagesschau-thema",
        "kind": "html_index",
        "publisher": "tagesschau / ARD-aktuell",
        "url": "https://www.tagesschau.de/thema/obdachlosigkeit",
        "license_url": "https://www.tagesschau.de/impressum",
        "land": "DE",
        "link_host": "www.tagesschau.de",
        "max_items": 80,
    },
    {
        "id": "dlf-wohnen",
        "kind": "html_index",
        "publisher": "Deutschlandfunk",
        "url": "https://www.deutschlandfunk.de/wohnen-116.html",
        "license_url": "https://www.deutschlandfunk.de/impressum-100.html",
        "land": "DE",
        "link_host": "www.deutschlandfunk.de",
        "max_items": 80,
    },
    # tagesschau official search API
    {
        "id": "tagesschau-search",
        "kind": "tagesschau_search",
        "publisher": "tagesschau / ARD-aktuell",
        "url": "https://www.tagesschau.de/api2u/search/",
        "license_url": "https://www.tagesschau.de/impressum",
        "land": "DE",
        "max_items": 80,
        "search_pages": 5,
        "max_search_requests": 18,
    },
    # Public broadcaster RSS (official station feeds)
    {
        "id": "tagesschau-rss",
        "kind": "rss",
        "publisher": "tagesschau / ARD-aktuell",
        "url": "https://www.tagesschau.de/index~rss2.xml",
        "license_url": "https://www.tagesschau.de/impressum",
        "land": "DE",
        "max_items": 20,
    },
    {
        "id": "br-rss",
        "kind": "rss",
        "publisher": "Bayerischer Rundfunk",
        "url": "https://www.br.de/nachrichten/meldungen/nachrichten-bayerischer-rundfunk100~newsRss.xml",
        "license_url": "https://www.br.de/unternehmen/service/impressum/index.html",
        "land": "BY",
        "max_items": 80,
    },
    {
        "id": "br-search",
        "kind": "html_search",
        "publisher": "Bayerischer Rundfunk",
        "url": "https://www.br.de/nachrichten/suche?query={q}",
        "license_url": "https://www.br.de/unternehmen/service/impressum/index.html",
        "land": "BY",
        "link_host": "www.br.de",
        "link_must": "/nachrichten/",
    },
    {
        "id": "ndr-rss",
        "kind": "rss",
        "publisher": "Norddeutscher Rundfunk",
        "url": "https://www.ndr.de/index~rss2.xml",
        "license_url": "https://www.ndr.de/service/impressum/index.html",
        "land": "DE",
        "max_items": 80,
    },
    {
        "id": "ndr-search",
        "kind": "html_search",
        "publisher": "Norddeutscher Rundfunk",
        "url": "https://www.ndr.de/suche20.html?query={q}&sort_by=date",
        "license_url": "https://www.ndr.de/service/impressum/index.html",
        "land": "DE",
        "link_host": "www.ndr.de",
    },
    {
        "id": "wdr-rss",
        "kind": "rss",
        "publisher": "Westdeutscher Rundfunk",
        "url": "https://www1.wdr.de/uebersicht-100.feed",
        "license_url": "https://www1.wdr.de/help/impressum100.html",
        "land": "NW",
        "max_items": 80,
    },
    {
        "id": "wdr-search",
        "kind": "html_search",
        "publisher": "Westdeutscher Rundfunk",
        "url": "https://www1.wdr.de/suche/index.jsp?q={q}",
        "license_url": "https://www1.wdr.de/help/impressum100.html",
        "land": "NW",
        "link_host": "www1.wdr.de",
    },
    {
        "id": "rbb-rss",
        "kind": "rss",
        "publisher": "Rundfunk Berlin-Brandenburg",
        "url": "https://www.rbb24.de/index.xml/feed=rss.xml",
        "license_url": "https://www.rbb24.de/unternehmen/impressum/index.html",
        "land": "DE",
        "max_items": 80,
    },
    {
        "id": "rbb-search",
        "kind": "html_search",
        "publisher": "Rundfunk Berlin-Brandenburg",
        "url": "https://www.rbb24.de/suche/index.html?q={q}",
        "license_url": "https://www.rbb24.de/unternehmen/impressum/index.html",
        "land": "DE",
        "link_host": "www.rbb24.de",
    },
    {
        "id": "mdr-rss",
        "kind": "rss",
        "publisher": "Mitteldeutscher Rundfunk",
        "url": "https://www.mdr.de/nachrichten/index-rss.xml",
        "license_url": "https://www.mdr.de/service/impressum/index.html",
        "land": "DE",
        "max_items": 80,
    },
    {
        "id": "mdr-search",
        "kind": "html_search",
        "publisher": "Mitteldeutscher Rundfunk",
        "url": "https://www.mdr.de/nachrichten/suche-100.html?query={q}",
        "license_url": "https://www.mdr.de/service/impressum/index.html",
        "land": "DE",
        "link_host": "www.mdr.de",
    },
    {
        "id": "swr-search",
        "kind": "html_search",
        "publisher": "Südwestrundfunk",
        "url": "https://www.swr.de/swraktuell/suche-102.html?q={q}",
        "license_url": "https://www.swr.de/unternehmen/organisation/impressum-swr-100.html",
        "land": "DE",
        "link_host": "www.swr.de",
    },
    {
        "id": "hr-rss",
        "kind": "rss",
        "publisher": "Hessischer Rundfunk / hessenschau",
        "url": "https://www.hessenschau.de/index.rss",
        "license_url": "https://www.hessenschau.de/service/impressum-104.html",
        "land": "HE",
        "max_items": 80,
    },
    {
        "id": "hr-search",
        "kind": "html_search",
        "publisher": "Hessischer Rundfunk / hessenschau",
        "url": "https://www.hessenschau.de/suche/index.html?q={q}",
        "license_url": "https://www.hessenschau.de/service/impressum-104.html",
        "land": "HE",
        "link_host": "www.hessenschau.de",
    },
    {
        "id": "dlf-rss",
        "kind": "rss",
        "publisher": "Deutschlandfunk",
        "url": "https://www.deutschlandfunk.de/nachrichten-100.rss",
        "license_url": "https://www.deutschlandfunk.de/impressum-100.html",
        "land": "DE",
        "max_items": 80,
    },
    {
        "id": "dlf-search",
        "kind": "html_search",
        "publisher": "Deutschlandfunk",
        "url": "https://www.deutschlandfunk.de/suche?searchterm={q}",
        "license_url": "https://www.deutschlandfunk.de/impressum-100.html",
        "land": "DE",
        "link_host": "www.deutschlandfunk.de",
    },
    # Land statistics offices (official typo3 / RSS where published)
    {
        "id": "statistik-bw-rss",
        "kind": "rss",
        "publisher": "Statistisches Landesamt Baden-Württemberg",
        "url": "https://www.statistik-bw.de/Service/RSS/rss.xml",
        "license_url": "https://www.statistik-bw.de/Impressum/",
        "land": "BW",
    },
    {
        "id": "statistik-by-search",
        "kind": "html_search",
        "publisher": "Bayerisches Landesamt für Statistik",
        "url": "https://www.statistik.bayern.de/suche/index.html?query={q}",
        "license_url": "https://www.statistik.bayern.de/impressum/index.html",
        "land": "BY",
        "link_host": "www.statistik.bayern.de",
        "link_must": "/presse",
    },
    {
        "id": "statistik-bb-search",
        "kind": "html_search",
        "publisher": "Amt für Statistik Berlin-Brandenburg",
        "url": "https://www.statistik-berlin-brandenburg.de/suche?search={q}",
        "license_url": "https://www.statistik-berlin-brandenburg.de/impressum",
        "land": "DE",
        "link_host": "www.statistik-berlin-brandenburg.de",
    },
    {
        "id": "it-nrw-search",
        "kind": "html_search",
        "publisher": "Information und Technik Nordrhein-Westfalen (IT.NRW)",
        "url": "https://www.it.nrw/suche?keys={q}",
        "license_url": "https://www.it.nrw/impressum",
        "land": "NW",
        "link_host": "www.it.nrw",
        "link_must": "/presse",
    },
    {
        "id": "statistik-nord-search",
        "kind": "html_search",
        "publisher": "Statistikamt Nord",
        "url": "https://www.statistik-nord.de/suche?tx_kesearch_pi1[sword]={q}",
        "license_url": "https://www.statistik-nord.de/impressum",
        "land": "DE",
        "link_host": "www.statistik-nord.de",
    },
    {
        "id": "statistik-sachsen-search",
        "kind": "html_search",
        "publisher": "Statistisches Landesamt des Freistaates Sachsen",
        "url": "https://www.statistik.sachsen.de/html/suche.html?q={q}",
        "license_url": "https://www.statistik.sachsen.de/html/impressum.html",
        "land": "SN",
        "link_host": "www.statistik.sachsen.de",
    },
    # City press offices (official RSS / indexes)
    {
        "id": "berlin-presse",
        "kind": "rss",
        "publisher": "Der Regierende Bürgermeister von Berlin, Senatskanzlei",
        "url": "https://www.berlin.de/presse/pressemitteilungen/index/index.rss",
        "license_url": "https://www.berlin.de/rbmskzl/impressum/",
        "land": "BE",
        "kreis_ags": "11000",
        "ort": "Berlin",
        "max_items": 200,
    },
    {
        "id": "berlin-presse-search",
        "kind": "html_search",
        "publisher": "Der Regierende Bürgermeister von Berlin, Senatskanzlei",
        "url": "https://www.berlin.de/presse/pressemitteilungen/index/index.php?q={q}",
        "license_url": "https://www.berlin.de/rbmskzl/impressum/",
        "land": "BE",
        "kreis_ags": "11000",
        "ort": "Berlin",
        "link_host": "www.berlin.de",
        "link_must": "/presse/",
    },
    {
        "id": "hamburg-presse",
        "kind": "html_search",
        "publisher": "Freie und Hansestadt Hamburg",
        "url": "https://www.hamburg.de/suche/pressemitteilungen?query={q}",
        "license_url": "https://www.hamburg.de/impressum",
        "land": "HH",
        "kreis_ags": "02000",
        "ort": "Hamburg",
        "link_host": "www.hamburg.de",
    },
    {
        "id": "muenchen-presse",
        "kind": "html_search",
        "publisher": "Landeshauptstadt München",
        "url": "https://stadt.muenchen.de/infos/presse-muenchen.html?query={q}",
        "license_url": "https://stadt.muenchen.de/infos/impressum.html",
        "land": "BY",
        "kreis_ags": "09162",
        "ort": "München",
        "link_host": "stadt.muenchen.de",
    },
    {
        "id": "koeln-presse",
        "kind": "rss",
        "publisher": "Stadt Köln",
        "url": "https://www.stadt-koeln.de/politik-und-verwaltung/presse/mitteilungen/rss.xml",
        "license_url": "https://www.stadt-koeln.de/impressum/index.html",
        "land": "NW",
        "kreis_ags": "05315",
        "ort": "Köln",
        "max_items": 200,
    },
    {
        "id": "leipzig-presse",
        "kind": "html_search",
        "publisher": "Stadt Leipzig",
        "url": "https://www.leipzig.de/newsportal?tx_news_pi1[search][keyword]={q}",
        "license_url": "https://www.leipzig.de/impressum",
        "land": "SN",
        "kreis_ags": "14713",
        "ort": "Leipzig",
        "link_host": "www.leipzig.de",
    },
    {
        "id": "dresden-presse",
        "kind": "html_search",
        "publisher": "Landeshauptstadt Dresden",
        "url": "https://www.dresden.de/de/rathaus/aktuelles/pressemitteilungen.php?search={q}",
        "license_url": "https://www.dresden.de/de/impressum.php",
        "land": "SN",
        "kreis_ags": "14612",
        "ort": "Dresden",
        "link_host": "www.dresden.de",
        "link_must": "/pressemitteilungen",
    },
    {
        "id": "stuttgart-presse",
        "kind": "html_search",
        "publisher": "Landeshauptstadt Stuttgart",
        "url": "https://www.stuttgart.de/rathaus/aktuelles/pressemitteilungen.php?search={q}",
        "license_url": "https://www.stuttgart.de/impressum",
        "land": "BW",
        "kreis_ags": "08111",
        "ort": "Stuttgart",
        "link_host": "www.stuttgart.de",
    },
    {
        "id": "duesseldorf-presse",
        "kind": "html_search",
        "publisher": "Stadt Düsseldorf",
        "url": "https://www.duesseldorf.de/suche?q={q}",
        "license_url": "https://www.duesseldorf.de/impressum",
        "land": "NW",
        "kreis_ags": "05111",
        "ort": "Düsseldorf",
        "link_host": "www.duesseldorf.de",
        "link_must": "/presse",
    },
    # Landtag press RSS / official indexes where published as feeds
    {
        "id": "lt-nrw-presse",
        "kind": "html_search",
        "publisher": "Landtag Nordrhein-Westfalen",
        "url": "https://www.landtag.nrw.de/portal/WWW/suche/suche.jsp?query={q}",
        "license_url": "https://www.landtag.nrw.de/home/service/impressum.html",
        "land": "NW",
        "link_host": "www.landtag.nrw.de",
        "link_must": "/presse",
    },
    {
        "id": "agh-berlin-presse",
        "kind": "html_search",
        "publisher": "Abgeordnetenhaus von Berlin",
        "url": "https://www.parlament-berlin.de/suche?q={q}",
        "license_url": "https://www.parlament-berlin.de/impressum",
        "land": "BE",
        "link_host": "www.parlament-berlin.de",
        "link_must": "/presse",
    },
    {
        "id": "lt-bayern-presse",
        "kind": "html_search",
        "publisher": "Bayerischer Landtag",
        "url": "https://www.bayern.landtag.de/aktuelles/suche/?q={q}",
        "license_url": "https://www.bayern.landtag.de/service/impressum/",
        "land": "BY",
        "link_host": "www.bayern.landtag.de",
        "link_must": "/presse",
    },
    # Additional official statistics-office and Senate press sources (second media slice)
    {
        "id": "statistik-hb-rss",
        "kind": "rss",
        "publisher": "Statistisches Landesamt Bremen",
        "url": "https://www.statistik.bremen.de/rss-feed/statistik-bremen-14970?lang=de",
        "license_url": "https://www.statistik.bremen.de/impressum",
        "land": "HB",
    },
    {
        "id": "statistik-sl-rss",
        "kind": "rss",
        "publisher": "Statistisches Amt Saarland",
        "url": "https://www.saarland.de/stat/DE/aktuelles/zurueckgelegt/rss-feed/_feeds/pressemitteilungen_feed.xml",
        "license_url": "https://www.saarland.de/stat/DE/aktuelles/zurueckgelegt/rss-feed/_feeds/pressemitteilungen_feed.xml",
        "land": "SL",
    },
    {
        "id": "statistik-rlp-rss",
        "kind": "rss",
        "publisher": "Statistisches Landesamt Rheinland-Pfalz",
        "url": "https://www.statistik.rlp.de/service/rss-feeds/all_feeds.rss",
        "license_url": "https://www.statistik.rlp.de/ueber-statistikrlpde/impressum",
        "land": "RP",
    },
    {
        "id": "statistik-he-presse",
        "kind": "html_index",
        "publisher": "Hessisches Statistisches Landesamt",
        "url": "https://statistik.hessen.de/presse",
        "license_url": "https://statistik.hessen.de/impressum",
        "land": "HE",
        "link_host": "statistik.hessen.de",
    },
    {
        "id": "statistik-mv-presse",
        "kind": "html_index",
        "publisher": "Statistisches Amt Mecklenburg-Vorpommern (LAiV)",
        "url": "https://www.laiv-mv.de/Pressemitteilungen/",
        "license_url": "https://www.laiv-mv.de/Impressum/",
        "land": "MV",
        "link_host": "www.laiv-mv.de",
        "link_must": "/Pressemitteilungen",
    },
    {
        "id": "bremen-senat-presse",
        "kind": "html_index",
        "publisher": "Pressestelle des Senats der Freien Hansestadt Bremen",
        "url": "https://www.senatspressestelle.bremen.de/pressemitteilungen-1464",
        "license_url": "https://www.senatspressestelle.bremen.de/impressum-1478",
        "land": "HB",
        "link_host": "www.senatspressestelle.bremen.de",
        "link_must": "/pressemitteilungen",
    },
    # Official XML / news sitemaps (topic-filter URL or title, then fetch pages).
    {
        "id": "tagesschau-sitemap",
        "kind": "sitemap_index",
        "publisher": "tagesschau / ARD-aktuell",
        "url": "https://www.tagesschau.de/index~sitemap.xml",
        "license_url": "https://www.tagesschau.de/impressum",
        "land": "DE",
        "max_sitemaps": 61,
        "max_items": 200,
    },
    {
        "id": "br-article-archive",
        "kind": "sitemap",
        "publisher": "Bayerischer Rundfunk",
        "url": "https://www.br.de/nachrichten/sitemaps/article-archive.xml",
        "license_url": "https://www.br.de/unternehmen/service/impressum/index.html",
        "land": "BY",
        "max_items": 200,
    },
    {
        "id": "ndr-sitemap",
        "kind": "sitemap_index",
        "publisher": "Norddeutscher Rundfunk",
        "url": "https://www.ndr.de/index~sitemap.xml",
        "license_url": "https://www.ndr.de/service/impressum/index.html",
        "land": "DE",
        "max_sitemaps": 90,
        "child_must": r"sitemap-ndr-",
        "max_items": 200,
    },
    {
        "id": "wdr-sitemap",
        "kind": "sitemap_index",
        "publisher": "Westdeutscher Rundfunk",
        "url": "https://www1.wdr.de/index~sitemap.xml",
        "license_url": "https://www1.wdr.de/help/impressum100.html",
        "land": "NW",
        "max_sitemaps": 60,
        "max_items": 200,
    },
    {
        "id": "mdr-sitemap",
        "kind": "sitemap_index",
        "publisher": "Mitteldeutscher Rundfunk",
        "url": "https://www.mdr.de/sitemap/index~sitemap.xml",
        "license_url": "https://www.mdr.de/service/impressum/index.html",
        "land": "DE",
        "max_sitemaps": 40,
        "child_must": r"nachrichten",
        "max_items": 200,
    },
    {
        "id": "hr-sitemap",
        "kind": "sitemap",
        "publisher": "Hessischer Rundfunk (hessenschau)",
        "url": "https://www.hessenschau.de/sitemap.nc.xml",
        "license_url": "https://www.hessenschau.de/service/impressum-104.html",
        "land": "HE",
        "max_items": 200,
    },
    {
        "id": "dlf-gesellschaft-sitemap",
        "kind": "sitemap",
        "publisher": "Deutschlandfunk",
        "url": "https://www.deutschlandfunk.de/gesellschaftsthemen-100.sitemap",
        "license_url": "https://www.deutschlandfunk.de/impressum-100.html",
        "land": "DE",
        "max_items": 80,
    },
    {
        "id": "dlf-politik-sitemap",
        "kind": "sitemap",
        "publisher": "Deutschlandfunk",
        "url": "https://www.deutschlandfunk.de/politikthemen-100.sitemap",
        "license_url": "https://www.deutschlandfunk.de/impressum-100.html",
        "land": "DE",
        "max_items": 80,
    },
    {
        "id": "dlf-nachrichten-sitemap",
        "kind": "sitemap",
        "publisher": "Deutschlandfunk",
        "url": "https://www.deutschlandfunk.de/nachrichten-100.sitemap",
        "license_url": "https://www.deutschlandfunk.de/impressum-100.html",
        "land": "DE",
        "max_items": 80,
    },
    {
        "id": "bt-sitemap",
        "kind": "sitemap_index",
        "publisher": "Deutscher Bundestag",
        "url": "https://www.bundestag.de/service-sitemap-de-sitemap_index.xml",
        "license_url": "https://www.bundestag.de/impressum",
        "land": "DE",
        "max_sitemaps": 2,
        "max_items": 200,
    },
    {
        "id": "destatis-pm-sitemap",
        "kind": "sitemap",
        "publisher": "Statistisches Bundesamt (Destatis)",
        "url": "https://www.destatis.de/Sitemap_PressReleases.xml",
        "license_url": "https://www.destatis.de/DE/Service/Impressum/_inhalt.html",
        "land": "DE",
        "max_items": 80,
    },
    # Regional public-broadcaster sections and official city sitemaps (slice
    # closing the media gap outside Berlin). Discovery is sitemap-only.
    {
        "id": "ndr-hamburg-sitemap",
        "kind": "sitemap_index",
        "publisher": "Norddeutscher Rundfunk (Hamburg)",
        "url": "https://www.ndr.de/index~sitemap.xml",
        "source_url": "https://www.ndr.de/nachrichten/hamburg/",
        "license_url": "https://www.ndr.de/service/impressum/index.html",
        "land": "HH",
        "kreis_ags": "02000",
        "ort": "Hamburg",
        "max_sitemaps": 20,
        "child_must": r"sitemap-ndr-hamburg",
        "loc_must": r"(?i)/nachrichten/hamburg/",
        "max_items": 200,
        "slice": "regional_local",
    },
    {
        "id": "br-muenchen-sitemap",
        "kind": "sitemap",
        "publisher": "Bayerischer Rundfunk (München)",
        "url": "https://www.br.de/nachrichten/sitemaps/article-archive.xml",
        "source_url": "https://www.br.de/nachrichten/bayern/",
        "license_url": "https://www.br.de/unternehmen/service/impressum/index.html",
        "land": "BY",
        "kreis_ags": "09162",
        "ort": "München",
        "loc_must": r"(?i)muenchen|münchen",
        "max_items": 200,
        "slice": "regional_local",
    },
    {
        "id": "wdr-koeln-sitemap",
        "kind": "sitemap_index",
        "publisher": "Westdeutscher Rundfunk (Köln)",
        "url": "https://www1.wdr.de/index~sitemap.xml",
        "source_url": "https://www1.wdr.de/unternehmen/der-wdr/standorte/studios/koeln/index.html",
        "license_url": "https://www1.wdr.de/help/impressum100.html",
        "land": "NW",
        "kreis_ags": "05315",
        "ort": "Köln",
        "max_sitemaps": 60,
        "loc_must": r"(?i)/nrw/koeln/|/nachrichten/rheinland/koeln|/nrw/rheinland/[^/]*koeln",
        "max_items": 200,
        "slice": "regional_local",
    },
    {
        "id": "wdr-ruhr-sitemap",
        "kind": "sitemap_index",
        "publisher": "Westdeutscher Rundfunk (Ruhr)",
        "url": "https://www1.wdr.de/index~sitemap.xml",
        "source_url": "https://www1.wdr.de/unternehmen/der-wdr/standorte/studios/essen/index.html",
        "license_url": "https://www1.wdr.de/help/impressum100.html",
        "land": "NW",
        "max_sitemaps": 60,
        "loc_must": r"(?i)/nrw/ruhrgebiet/|/nrw/dortmund/|/nrw/essen/|/nrw/bochum/|/nrw/duisburg/|/nrw/gelsenkirchen/|/nachrichten/ruhrgebiet/",
        "max_items": 200,
        "slice": "regional_local",
    },
    {
        "id": "hr-frankfurt-sitemap",
        "kind": "sitemap",
        "publisher": "Hessischer Rundfunk / hessenschau (Frankfurt)",
        "url": "https://www.hessenschau.de/sitemap.nc.xml",
        "source_url": "https://www.hessenschau.de/",
        "license_url": "https://www.hessenschau.de/service/impressum-104.html",
        "land": "HE",
        "kreis_ags": "06412",
        "ort": "Frankfurt am Main",
        "loc_must": r"(?i)frankfurt",
        "max_items": 200,
        "slice": "regional_local",
    },
    {
        "id": "mdr-sachsen-sitemap",
        "kind": "sitemap_index",
        "publisher": "Mitteldeutscher Rundfunk (Sachsen)",
        "url": "https://www.mdr.de/sitemap/index~sitemap.xml",
        "source_url": "https://www.mdr.de/nachrichten/sachsen/",
        "license_url": "https://www.mdr.de/service/impressum/index.html",
        "land": "SN",
        "max_sitemaps": 20,
        "child_must": r"sitemap-mdr-nachrichten-sachsen-100",
        "loc_must": r"(?i)/nachrichten/sachsen/(?!anhalt)",
        "max_items": 200,
        "slice": "regional_local",
    },
    {
        "id": "swr-bw-sitemap",
        "kind": "sitemap_index",
        "publisher": "Südwestrundfunk (Baden-Württemberg)",
        "url": "https://www.swr.de/~sitemap/swraktuell/index.xml",
        "source_url": "https://www.swr.de/~sitemap/swraktuell/index.xml",
        "license_url": "https://www.swr.de/unternehmen/organisation/impressum-swr-100.html",
        "land": "BW",
        "max_sitemaps": 10,
        "loc_must": r"(?i)/swraktuell/baden-wuerttemberg/",
        "max_items": 200,
        "slice": "regional_local",
    },
    {
        "id": "dortmund-newsroom-sitemap",
        "kind": "sitemap",
        "publisher": "Stadt Dortmund",
        "url": "https://www.dortmund.de/technisches/sitemap.xml",
        "source_url": "https://www.dortmund.de/technisches/sitemap.xml",
        "license_url": "https://www.dortmund.de/impressum",
        "land": "NW",
        "kreis_ags": "05913",
        "ort": "Dortmund",
        "loc_must": r"(?i)/newsroom/",
        "max_items": 200,
        "slice": "regional_local",
    },
    {
        "id": "stuttgart-presse-sitemap",
        "kind": "sitemap_index",
        "publisher": "Landeshauptstadt Stuttgart",
        "url": "https://www.stuttgart.de/index.php?sp%3Aout=sitemap",
        "source_url": "https://www.stuttgart.de/index.php?sp%3Aout=sitemap",
        "license_url": "https://www.stuttgart.de/impressum",
        "land": "BW",
        "kreis_ags": "08111",
        "ort": "Stuttgart",
        "loc_must": r"(?i)/pressemitteilungen/|/service/aktuelle-meldungen/",
        "max_items": 200,
        "slice": "regional_local",
    },
    {
        "id": "duesseldorf-news-sitemap",
        "kind": "sitemap_index",
        "publisher": "Landeshauptstadt Düsseldorf",
        "url": "https://www.duesseldorf.de/news-sitemap.xml",
        "source_url": "https://www.duesseldorf.de/news-sitemap.xml",
        "license_url": "https://www.duesseldorf.de/infonav/impressum",
        "land": "NW",
        "kreis_ags": "05111",
        "ort": "Düsseldorf",
        "max_sitemaps": 5,
        "max_items": 200,
        "slice": "regional_local",
    },

    # Further regional public-broadcaster desks outside Berlin (slice after
    # 7784de8). Sitemap-only, fail-closed robots, metadata only.
    {
        "id": "ndr-niedersachsen-sitemap",
        "kind": "sitemap_index",
        "publisher": "Norddeutscher Rundfunk (Niedersachsen)",
        "url": "https://www.ndr.de/index~sitemap.xml",
        "source_url": "https://www.ndr.de/nachrichten/niedersachsen/",
        "license_url": "https://www.ndr.de/service/impressum/index.html",
        "land": "NI",
        "max_sitemaps": 20,
        "child_must": r"sitemap-ndr-niedersachsen",
        "loc_must": r"(?i)/nachrichten/niedersachsen/",
        "max_items": 200,
        "slice": "regional_desk",
    },
    {
        "id": "ndr-sh-sitemap",
        "kind": "sitemap_index",
        "publisher": "Norddeutscher Rundfunk (Schleswig-Holstein)",
        "url": "https://www.ndr.de/index~sitemap.xml",
        "source_url": "https://www.ndr.de/nachrichten/schleswig-holstein/",
        "license_url": "https://www.ndr.de/service/impressum/index.html",
        "land": "SH",
        "max_sitemaps": 20,
        "child_must": r"sitemap-ndr-schleswig-holstein",
        "loc_must": r"(?i)/nachrichten/schleswig-holstein/",
        "max_items": 200,
        "slice": "regional_desk",
    },
    {
        "id": "mdr-sachsen-anhalt-sitemap",
        "kind": "sitemap_index",
        "publisher": "Mitteldeutscher Rundfunk (Sachsen-Anhalt)",
        "url": "https://www.mdr.de/sitemap/index~sitemap.xml",
        "source_url": "https://www.mdr.de/nachrichten/sachsen-anhalt/",
        "license_url": "https://www.mdr.de/service/impressum/index.html",
        "land": "ST",
        "max_sitemaps": 20,
        "child_must": r"sitemap-mdr-nachrichten-sachsen-anhalt-100",
        "loc_must": r"(?i)/nachrichten/sachsen-anhalt/",
        "max_items": 200,
        "slice": "regional_desk",
    },
    {
        "id": "mdr-thueringen-sitemap",
        "kind": "sitemap_index",
        "publisher": "Mitteldeutscher Rundfunk (Thüringen)",
        "url": "https://www.mdr.de/sitemap/index~sitemap.xml",
        "source_url": "https://www.mdr.de/nachrichten/thueringen/",
        "license_url": "https://www.mdr.de/service/impressum/index.html",
        "land": "TH",
        "max_sitemaps": 20,
        "child_must": r"sitemap-mdr-nachrichten-thueringen-100",
        "loc_must": r"(?i)/nachrichten/thueringen/",
        "max_items": 200,
        "slice": "regional_desk",
    },
    {
        "id": "swr-rp-sitemap",
        "kind": "sitemap_index",
        "publisher": "Südwestrundfunk (Rheinland-Pfalz)",
        "url": "https://www.swr.de/~sitemap/swraktuell/index.xml",
        "source_url": "https://www.swr.de/swraktuell/rheinland-pfalz/",
        "license_url": "https://www.swr.de/unternehmen/organisation/impressum-swr-100.html",
        "land": "RP",
        "max_sitemaps": 10,
        "loc_must": r"(?i)/swraktuell/rheinland-pfalz/",
        "max_items": 200,
        "slice": "regional_desk",
    },
    {
        "id": "sr-nachrichten-sitemap",
        "kind": "sitemap_index",
        "publisher": "Saarländischer Rundfunk",
        "url": "https://www.sr.de/sr/sitemap100.xml",
        "source_url": "https://www.sr.de/sr/home/nachrichten/",
        "license_url": "https://www.sr.de/sr/home/impressum100.html",
        "land": "SL",
        "max_sitemaps": 10,
        "loc_must": r"(?i)/sr/home/nachrichten/",
        "max_items": 200,
        "slice": "regional_desk",
    },
    {
        "id": "br-regional-sitemap",
        "kind": "sitemap",
        "publisher": "Bayerischer Rundfunk (Regionalstudios)",
        "url": "https://www.br.de/nachrichten/sitemaps/article-archive.xml",
        "source_url": "https://www.br.de/nachrichten/bayern/",
        "license_url": "https://www.br.de/unternehmen/service/impressum/index.html",
        "land": "BY",
        "loc_must": (
            r"(?i)(?:franken|nuernberg|nürnberg|augsburg|schwaben|"
            r"niederbayern|oberpfalz|wuerzburg|würzburg|passau|"
            r"ingolstadt|bamberg|landshut|regensburg|fuerth|bayreuth)"
        ),
        "max_items": 200,
        "slice": "regional_desk",
    },
]


REGIONAL_LOCAL_FEEDS = [f for f in FEEDS if f.get("slice") == "regional_local"]
REGIONAL_DESK_FEEDS = [f for f in FEEDS if f.get("slice") == "regional_desk"]



def _im():
    from ingest.domains import institutions_media as module
    return module


def has_topic(*parts: str | None) -> bool:
    hay = " ".join(part or "" for part in parts)
    if TOPIC_RE.search(hay):
        return True
    # "Wohnungsnot" counts only together with Obdach, as required.
    return bool(WOHNUNGSNOT_RE.search(hay) and OBDACH_RE.search(hay))


def sample_on_topic_rate(rows: list[dict], *, k: int = 25, seed: int = 20261123) -> dict:
    """Random quality-gate sample: share of rows whose title/URL are on topic.

    Draws up to *k* rows (or all, if fewer). On-topic means homelessness or
    housing loss as matched by has_topic(), i.e. the tightened filter used to
    store the row. Returns counts, the rate, and the sampled records.
    """
    import random
    pool = list(rows or [])
    if not pool:
        return {"n": 0, "checked": 0, "on_topic": 0, "rate": 0.0, "sample": []}
    rng = random.Random(seed)
    checked_rows = pool if len(pool) <= k else rng.sample(pool, k)
    on_topic = []
    off_topic = []
    for rec in checked_rows:
        if has_topic(rec.get("title"), rec.get("url"), rec.get("topic"), rec.get("summary")):
            on_topic.append(rec)
        else:
            off_topic.append(rec)
    checked = len(checked_rows)
    return {
        "n": len(pool),
        "checked": checked,
        "on_topic": len(on_topic),
        "rate": (len(on_topic) / checked) if checked else 0.0,
        "sample": checked_rows,
        "off_topic": off_topic,
    }


def topic_tag(*parts: str | None) -> str | None:
    """A short canonical topic tag from the headline, URL or feed title."""
    hay = " ".join(part or "" for part in parts)
    if not hay:
        return None
    preferred = (
        "Wohnungsnotfallhilfe",
        "Wohnungslosigkeit",
        "Obdachlosigkeit",
        "Straßenobdachlosigkeit",
        "Winternothilfe",
        "Housing First",
        "Kältehilfe",
        "Kältebus",
        "Notschlafstelle",
        "Notunterkunft",
        "Wohnungslosenhilfe",
    )
    folded = hay.casefold()
    for term in preferred:
        if term.casefold() in folded:
            return term
        # URL stems use ae / no spaces.
        stem = (
            term.casefold()
            .replace("ä", "ae")
            .replace("ö", "oe")
            .replace("ü", "ue")
            .replace("ß", "ss")
            .replace(" ", "")
        )
        if stem and stem in folded.replace("-", "").replace("_", "").replace(" ", ""):
            return term
    if WOHNUNGSNOT_RE.search(hay) and OBDACH_RE.search(hay):
        return "Wohnungsnot"
    if TOPIC_RE.search(hay):
        match = TOPIC_RE.search(hay)
        return match.group(0)
    return None


GERMANY_RE = re.compile(
    r"(?i)\b(?:"
    r"deutschland|bundesrepublik|bundesweit|bundestag|bundesregierung|destatis|"
    r"berlin|hamburg|m[üu]nchen|k[öo]ln|frankfurt|bremen|stuttgart|d[üu]sseldorf|"
    r"leipzig|dresden|hannover|n[üu]rnberg|dortmund|essen|"
    r"schleswig-holstein|niedersachsen|nordrhein-westfalen|\bnrw\b|hessen|"
    r"rheinland-pfalz|baden-w[üu]rttemberg|bayern|saarland|brandenburg|"
    r"mecklenburg-vorpommern|sachsen-anhalt|sachsen|th[üu]ringen"
    r")\b"
)
FOREIGN_ONLY_RE = re.compile(
    r"(?i)\b(?:united states|\busa\b|new york|washington|kalifornien|california|"
    r"trump|gro[ßss]britannien|united kingdom|\buk\b|burnham|frankreich|"
    r"d[äa]nemark|finnland|depardieu)\b"
)


def is_germany_scope(title: str | None, text: str | None, url: str | None = None) -> bool:
    """Keep German-scope articles; drop purely foreign homelessness stories."""
    hay = " ".join(part or "" for part in (title, text, url))
    if GERMANY_RE.search(hay):
        return True
    if FOREIGN_ONLY_RE.search(hay) and not GERMANY_RE.search(hay):
        return False
    # Official German institutional sources default to in-scope.
    host = (url or "").lower()
    if any(h in host for h in (
        "destatis.de", "bundestag.de", "bundesregierung.de",
        "landtag.", "parlament-berlin.de", "statistik",
        "berlin.de", "hamburg.de", "muenchen.de", "stadt-koeln.de",
    )):
        return True
    # German public broadcasters: require a Germany marker in title/url at least.
    return bool(GERMANY_RE.search(" ".join(part or "" for part in (title, url))))


def page_text(raw: bytes) -> str:
    """Deterministic visible text from archived HTML bytes. No appended text."""
    html = raw.decode("utf-8", "replace")
    html = re.sub(
        r"<script[\s\S]*?</script>|<style[\s\S]*?</style>|<noscript[\s\S]*?</noscript>",
        " ",
        html,
        flags=re.I,
    )
    html = re.sub(r"<br\s*/?>", "\n", html, flags=re.I)
    html = re.sub(r"</(?:p|h[1-6]|li|div|section|article|tr)>", "\n", html, flags=re.I)
    text = unescape(re.sub(r"<[^>]+>", " ", html))
    return re.sub(r"[ \t\u00a0\u2007\u2009\u202f]+", " ", text)


def quote_in_page(quote: str, text: str) -> bool:
    def norm(value: str) -> str:
        return re.sub(r"\s+", " ", value or "").strip()
    needle, hay = norm(quote), norm(text)
    return bool(needle) and needle in hay


def looks_private(text: str | None) -> bool:
    """True if the text appears to name a private individual."""
    blob = text or ""
    if not PRIVATE_HINT_RE.search(blob):
        return False
    # A public-role title next to the hint is allowed (mayor, senator, …).
    for match in PRIVATE_HINT_RE.finditer(blob):
        start = max(0, match.start() - 80)
        window = blob[start:match.end() + 20]
        if not PUBLIC_ROLE_RE.search(window):
            return True
    return False


def fields_name_ok(*parts: str | None) -> bool:
    return not any(looks_private(part) for part in parts if part)


def is_paywalled(text: str) -> bool:
    if PAYWALL_RE.search(text or ""):
        # Only treat as paywalled when the usable topic text is also thin.
        if len(TOPIC_RE.findall(text or "")) == 0 or len(text) < 800:
            return True
    return False


def pick_quote(text: str) -> str | None:
    """Choose at most two sentences that mention the topic and name no private person."""
    folded = re.sub(r"\s+", " ", text or "").strip()
    if not folded:
        return None
    # Split on sentence boundaries; keep the delimiter with the sentence.
    parts = re.split(r"(?<=[.!?])\s+", folded)
    candidates: list[str] = []
    for i, part in enumerate(parts):
        token = part.strip()
        if not token or not has_topic(token):
            continue
        if looks_private(token):
            continue
        snippet = token
        if i + 1 < len(parts):
            nxt = parts[i + 1].strip()
            if nxt and not looks_private(nxt) and len(snippet) < 160:
                snippet = snippet + " " + nxt
        trimmed = trim_quote(snippet, max_sentences=2)
        if not trimmed:
            continue
        if len(trimmed) < 40 or len(trimmed) > 400:
            continue
        if not quote_in_page(trimmed, folded):
            continue
        if looks_private(trimmed):
            continue
        candidates.append(trimmed)
    if not candidates:
        return None
    # Prefer a mid-length factual sentence over a very short teaser.
    candidates.sort(key=lambda s: abs(len(s) - 180))
    return candidates[0]


def parse_published(*values: str | None) -> str | None:
    for raw in values:
        text = clean(raw)
        if not text:
            continue
        match = re.search(r"(20\d{2}-\d{2}-\d{2})", text)
        if match:
            return match.group(1)
        match = re.search(r"(\d{1,2})\.(\d{1,2})\.(20\d{2})", text)
        if match:
            return f"{match.group(3)}-{int(match.group(2)):02d}-{int(match.group(1)):02d}"
    return clean(values[0]) if values else None


def extract_html_title(raw: bytes) -> str | None:
    text = raw.decode("utf-8", "replace")
    match = re.search(r"<title[^>]*>(.*?)</title>", text, re.I | re.S)
    if not match:
        return None
    title = unescape(re.sub(r"\s+", " ", match.group(1))).strip()
    title = re.sub(r"\s+[|\-–—].*$", "", title).strip()
    return title or None


def normalize_url(url: str | None) -> str | None:
    text = clean(url)
    if not text:
        return None
    text = text.split("#")[0].strip()
    if text.endswith("/") and text.count("/") > 3:
        text = text[:-1]
    return text


def parse_feed_items(xml_bytes: bytes) -> list[dict]:
    """RSS item and Atom entry parser. Raises on HTML error pages."""
    from ingest.domains.institutions_media import parse_rss_items
    items = []
    try:
        for item in parse_rss_items(xml_bytes):
            items.append({
                "title": clean(item.get("title")),
                "url": normalize_url(item.get("link") or item.get("guid") or item.get("enclosure")),
                "summary": clean(item.get("description")),
                "published": parse_published(item.get("pubdate")),
            })
    except ValueError:
        raise
    except Exception:
        items = []
    # Atom entries (parse_rss_items only walks <item>).
    text = xml_bytes if isinstance(xml_bytes, (bytes, bytearray)) else str(xml_bytes).encode("utf-8")
    if text.startswith(b"\xef\xbb\xbf"):
        text = text[3:]
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return [item for item in items if item.get("url")]
    for entry in root.iter():
        tag = entry.tag.split("}")[-1].lower() if isinstance(entry.tag, str) else ""
        if tag != "entry":
            continue
        fields: dict[str, str | None] = {}
        href = None
        for child in list(entry):
            name = child.tag.split("}")[-1].lower() if isinstance(child.tag, str) else ""
            if name in {"title", "summary", "content", "published", "updated", "id"}:
                fields[name] = "".join(child.itertext()).strip()
            if name == "link":
                rel = (child.attrib.get("rel") or "alternate").lower()
                if rel in {"alternate", ""} and child.attrib.get("href"):
                    href = child.attrib.get("href")
        url = normalize_url(href or fields.get("id"))
        items.append({
            "title": clean(fields.get("title")),
            "url": url,
            "summary": clean(fields.get("summary") or fields.get("content")),
            "published": parse_published(fields.get("published"), fields.get("updated")),
        })
    seen = set()
    out = []
    for item in items:
        url = item.get("url")
        if not url or url in seen:
            continue
        seen.add(url)
        out.append(item)
    return out


def extract_search_links(raw: bytes, *, base: str, link_host: str | None, link_must: str | None) -> list[dict]:
    html = raw.decode("utf-8", "replace")
    found = []
    for match in re.finditer(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', html, re.I | re.S):
        href = urllib.parse.urljoin(base, unescape(match.group(1))).split("#")[0]
        title = clean(unescape(re.sub(r"<[^>]+>", " ", match.group(2))))
        host = urllib.parse.urlparse(href).netloc.lower()
        if link_host and host != link_host.lower() and not host.endswith("." + link_host.lower()):
            continue
        if link_must and link_must not in href:
            continue
        if href.startswith("javascript:") or href.startswith("mailto:"):
            continue
        found.append({"url": normalize_url(href), "title": title, "summary": title, "published": None})
    # Also pick plain official press-path hrefs even if the link text is an icon.
    for href in re.findall(r'href=["\']([^"\']+)["\']', html, re.I):
        absu = normalize_url(urllib.parse.urljoin(base, unescape(href)))
        if not absu:
            continue
        host = urllib.parse.urlparse(absu).netloc.lower()
        if link_host and host != link_host.lower() and not host.endswith("." + link_host.lower()):
            continue
        if link_must and link_must not in absu:
            continue
        found.append({"url": absu, "title": None, "summary": None, "published": None})
    seen = set()
    out = []
    for item in found:
        url = item.get("url")
        if not url or url in seen:
            continue
        # Drop navigational indexes
        path = urllib.parse.urlparse(url).path.lower()
        if path.endswith(("/suche", "/suche/", "/search", "/search/", "/index.html", "/")):
            continue
        seen.add(url)
        out.append(item)
    return out


def parse_tagesschau_search(payload: dict) -> list[dict]:
    items = []
    for row in payload.get("searchResults") or []:
        url = normalize_url(row.get("detailsWeb") or row.get("shareURL") or row.get("details"))
        if url and not url.startswith("http"):
            url = normalize_url("https://www.tagesschau.de" + url)
        items.append({
            "title": clean(row.get("title") or row.get("topline")),
            "url": url,
            "summary": clean(row.get("firstSentence") or row.get("teaserText") or row.get("shortText")),
            "published": parse_published(row.get("date")),
            "kind_hint": clean(row.get("type")),
        })
    return [item for item in items if item.get("url")]


def maybe_gunzip(raw: bytes) -> bytes:
    """Decode a gzip-compressed sitemap body (*.xml.gz or raw gzip bytes)."""
    if raw[:2] == b"\x1f\x8b":
        return gzip.decompress(raw)
    return raw


def _xml_local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if tag.startswith("{") else tag


def parse_sitemap(raw: bytes) -> dict:
    """Parse a sitemap urlset or sitemapindex. Accepts gzip-compressed bytes.

    Returns {"kind": "urlset"|"index"|"error", "entries": [...], "error"?}.
    Each urlset entry is {url, title, published, summary} (title/summary from
    the Google news sitemap tags when present). Index entries have {url, published}.
    """
    body = maybe_gunzip(raw or b"")
    try:
        root = ET.fromstring(body)
    except ET.ParseError as exc:
        return {"kind": "error", "error": str(exc), "entries": []}
    kind = _xml_local(root.tag).lower()
    entries: list[dict] = []
    if kind == "sitemapindex":
        for sm in root:
            if _xml_local(sm.tag).lower() != "sitemap":
                continue
            loc = lastmod = ""
            for child in sm:
                name = _xml_local(child.tag).lower()
                if name == "loc" and child.text:
                    loc = child.text.strip()
                elif name == "lastmod" and child.text:
                    lastmod = child.text.strip()
            if loc:
                entries.append({"url": loc, "title": None, "published": lastmod or None, "summary": None})
        return {"kind": "index", "entries": entries}
    if kind == "urlset":
        for url_el in root:
            if _xml_local(url_el.tag).lower() != "url":
                continue
            loc = title = published = lastmod = keywords = ""
            for child in url_el:
                name = _xml_local(child.tag).lower()
                if name == "loc" and child.text:
                    loc = child.text.strip()
                elif name == "lastmod" and child.text:
                    lastmod = child.text.strip()
                elif name == "news":
                    for news in child:
                        nname = _xml_local(news.tag).lower()
                        if nname == "title" and news.text:
                            title = news.text.strip()
                        elif nname == "publication_date" and news.text:
                            published = news.text.strip()
                        elif nname == "keywords" and news.text:
                            keywords = news.text.strip()
            if loc:
                entries.append({
                    "url": loc,
                    "title": clean(title) or None,
                    "published": parse_published(published, lastmod),
                    "summary": clean(keywords) or None,
                })
        return {"kind": "urlset", "entries": entries}
    return {"kind": "error", "error": f"unsupported sitemap root {_xml_local(root.tag)}", "entries": []}


def sitemap_on_topic(entry: dict) -> bool:
    """True when the sitemap loc, news title or keywords match the topic filter."""
    url = entry.get("url") or ""
    # Destatis and similar also publish an English copy of the same PM.
    if "/EN/" in url or "/en/" in url.split("://", 1)[-1]:
        return False
    return has_topic(url, entry.get("title"), entry.get("summary"))


def sitemap_loc_allowed(url: str, feed: dict) -> bool:
    """Honor an optional loc_must regex on the article URL."""
    pattern = feed.get("loc_must")
    if not pattern:
        return True
    return bool(re.search(pattern, url or ""))


def sitemap_entry_allowed(entry: dict, feed: dict | None = None) -> bool:
    """Topic filter plus optional regional/path restriction for a sitemap loc."""
    url = entry.get("url") or ""
    if feed is not None and not sitemap_loc_allowed(url, feed):
        return False
    return sitemap_on_topic(entry)


def select_child_sitemaps(children: list[dict], feed: dict) -> list[dict]:
    """Pick child sitemaps to follow from an index, honoring max_sitemaps and child_must."""
    max_sitemaps = int(feed.get("max_sitemaps") or 40)
    child_must = feed.get("child_must")
    must_re = re.compile(child_must) if child_must else None
    selected = []
    for child in children:
        url = child.get("url") or ""
        if not url:
            continue
        if must_re and not must_re.search(url):
            continue
        selected.append(child)
    if must_re:
        return selected[:max_sitemaps]
    prefer_re = re.compile(
        r"(?i)news|presse|nachricht|aktuell|hib|pressemitteilung|"
        r"article-archive|sitemap_p-"
    )
    preferred = [c for c in selected if prefer_re.search(c.get("url") or "")]
    pool = preferred or selected
    return pool[:max_sitemaps]


def discover_from_sitemap(feed: dict, *, fetch_url, notes) -> list[dict]:
    """Load a urlset or sitemap index and return on-topic article candidates."""
    raw = fetch_url(feed["url"])
    parsed = parse_sitemap(raw)
    if parsed["kind"] == "error":
        notes.append(f"Sitemap {feed.get('id')}: {parsed.get('error')}")
        return []
    if parsed["kind"] == "urlset":
        return [e for e in parsed["entries"] if sitemap_entry_allowed(e, feed)]
    if parsed["kind"] != "index":
        notes.append(f"Sitemap {feed.get('id')}: unexpected kind {parsed['kind']}")
        return []
    items: list[dict] = []
    seen: set[str] = set()
    for child in select_child_sitemaps(parsed["entries"], feed):
        child_url = child.get("url")
        if not child_url:
            continue
        try:
            craw = fetch_url(child_url)
        except Exception as exc:
            notes.append(f"Child sitemap {child_url}: {type(exc).__name__}: {str(exc)[:120]}")
            continue
        sub = parse_sitemap(craw)
        if sub["kind"] != "urlset":
            if sub["kind"] == "index":
                notes.append(f"Nested sitemap index skipped for {child_url}")
            continue
        for entry in sub["entries"]:
            if not sitemap_entry_allowed(entry, feed):
                continue
            url = normalize_url(entry.get("url"))
            if not url or url in seen:
                continue
            seen.add(url)
            entry = dict(entry)
            entry["url"] = url
            items.append(entry)
    return items


def _wildcard_to_re(pattern: str) -> re.Pattern:
    """Convert a robots.txt path pattern (*, $) to a regex."""
    ends = pattern.endswith("$")
    pat = pattern[:-1] if ends else pattern
    if "*" not in pat and not ends:
        # Prefix match, as in the robots.txt spec.
        return re.compile("^" + re.escape(pat))
    rx = re.escape(pat).replace(r"\*", ".*")
    if ends:
        rx = rx + "$"
    return re.compile("^" + rx)


def robots_path_allowed(robots_text: str, url: str, ua: str) -> bool | None:
    """Honour Allow/Disallow including * wildcards that urllib may miss.

    Returns True/False when a matching group has rules, or None when the file
    has no applicable rules (caller may fall back to RobotFileParser).
    The longest matching path wins; a tie prefers Allow.
    """
    groups: list[tuple[list[str], list[tuple[str, str]]]] = []
    agents: list[str] = []
    rules: list[tuple[str, str]] = []

    def flush():
        nonlocal agents, rules
        if agents:
            groups.append((agents, rules))
        agents, rules = [], []

    for raw_line in (robots_text or "").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key, value = key.strip().lower(), value.strip()
        if key == "user-agent":
            # A new UA starts a new group unless we are still listing agents.
            if rules:
                flush()
            agents.append(value.lower())
        elif key in {"allow", "disallow"}:
            if not agents:
                continue
            rules.append((key, value))
        elif key == "crawl-delay":
            continue
        elif key == "sitemap":
            continue
        else:
            continue
    flush()

    ua_l = (ua or "").lower()
    chosen: list[tuple[str, str]] | None = None
    # Prefer a group whose agent is a token in our UA, else User-agent: *.
    specific = None
    star = None
    for agents, rules in groups:
        for agent in agents:
            if agent == "*":
                star = rules
            elif agent and agent in ua_l:
                specific = rules
                break
        if specific is not None:
            break
    chosen = specific if specific is not None else star
    if chosen is None:
        return None
    if not chosen:
        return True

    parsed = urllib.parse.urlparse(url)
    path = parsed.path or "/"
    if parsed.query:
        path = path + "?" + parsed.query
    best_len = -1
    best: bool | None = None
    for kind, pattern in chosen:
        if pattern == "":
            # "Disallow:" empty means allow all in some parsers; skip empty Allow/Disallow.
            continue
        if not _wildcard_to_re(pattern).search(path):
            continue
        plen = len(pattern)
        allowed = kind == "allow"
        if plen > best_len or (plen == best_len and allowed):
            best_len = plen
            best = allowed
    if best is None:
        return True
    return best


def press_robots_status(url: str) -> tuple[bool, str, float | None]:
    """Fail-closed robots.txt decision, reusing counts_law's fetcher and matcher.

    Only HTTP 404 or 410 on robots.txt means there are no rules (RFC 9309).
    Network errors, 5xx, 401/403 and cross-site redirects skip the host.
    """
    from ingest.domains.counts_law import _robots_allows, _robots_for
    parts = urllib.parse.urlsplit(url)
    origin = f"{parts.scheme}://{parts.netloc}"
    robots = _robots_for(origin)
    if isinstance(robots, str):
        return False, robots, None
    rules, delay = robots
    path = parts.path or "/"
    if parts.query:
        path += "?" + parts.query
    if not _robots_allows(rules, path):
        return False, "robots.txt disallows this path for the project UA", delay
    return True, "", delay


def _place_names() -> list[str]:
    """Official Land and city names, longest first so 'Sachsen-Anhalt' wins over 'Sachsen'."""
    names = set(LAND_NAMES) | set(CITY_KREIS) | set(CITY_NAME_ALIASES)
    return sorted(names, key=len, reverse=True)


def _shadowed_by_longer(name: str, text: str, start: int, end: int) -> bool:
    """True when this hit is only the leading part of a longer official place name."""
    rest = (text or "")[end:]
    for longer in _place_names():
        if len(longer) <= len(name):
            continue
        if not longer.lower().startswith(name.lower()):
            continue
        suffix = longer[len(name):]
        if rest.lower().startswith(suffix.lower()):
            return True
    return False


def _name_hits(name: str, text: str) -> bool:
    if not text:
        return False
    # 'Essen' is also the German word for food; only treat it as the city
    # when the wording or path is clearly a place (in Essen, /essen/, …).
    if name == "Essen":
        return bool(re.search(
            r"(?i)(?:\b(?:in|aus|bei|nach|stadt)\s+Essen\b)|(?:^|/)essen(?:/|$)",
            text,
        ))
    for m in re.finditer(r"\b" + re.escape(name) + r"\b", text, re.I):
        if not _shadowed_by_longer(name, text, m.start(), m.end()):
            return True
    return False


def places_in(text: str) -> tuple[set[str], set[str]]:

    lands, cities = set(), set()
    hay = text or ""
    # Keep hyphens so 'sachsen-anhalt' is one Land name, not 'Sachsen' + 'Anhalt'.
    for name, code in LAND_NAMES.items():
        if _name_hits(name, hay):
            lands.add(code)
    for name, (code, ags) in CITY_KREIS.items():
        if _name_hits(name, hay):
            cities.add(CITY_NAME_ALIASES.get(name, name))
            lands.add(code)
    for alias, canonical in CITY_NAME_ALIASES.items():
        if _name_hits(alias, hay):
            if canonical in CITY_KREIS:
                cities.add(canonical)
                lands.add(CITY_KREIS[canonical][0])
    # 'Halle' is only the Saale city when the text already places it in
    # Sachsen-Anhalt or uses the official 'Halle (Saale)' form (not Halle Westfalen).
    if (
        "Halle (Saale)" not in cities
        and re.search(r"\bHalle\b", hay, re.I)
        and re.search(r"(?i)sachsen-anhalt|halle \(saale\)|halle/saale|/halle/", hay)
        and not re.search(r"(?i)halle\s+westfalen", hay)
    ):
        cities.add("Halle (Saale)")
        lands.add("ST")
    return lands, cities


def assign_geo(feed: dict, title: str | None, text: str | None, url: str | None = None) -> dict:
    """Link AGS only when the article is clearly local. National stories stay land=DE."""
    path = ""
    if url:
        # Keep hyphens in the path so 'sachsen-anhalt' is not split into 'Sachsen'.
        path = urllib.parse.urlparse(url).path.replace("_", " ").replace("/", " ")
    hay = " ".join(part for part in (title, text, path) if part)[:4000]
    lands, cities = places_in(hay)
    preset_land = feed.get("land") if feed.get("land") in set(LAND_AGS) else None
    preset_kreis = feed.get("kreis_ags")
    preset_ort = feed.get("ort")
    # City press office: clearly that city unless another city is the sole subject.
    if preset_kreis:
        if len(cities) <= 1:
            land = preset_land or (CITY_KREIS.get(preset_ort or "", (None, None))[0]) or "DE"
            return {
                "land": land if land in LAND_AGS else "DE",
                "land_ags": LAND_AGS.get(land) if land in LAND_AGS else None,
                "kreis_ags": preset_kreis,
                "ort": preset_ort,
            }
        return {"land": "DE", "land_ags": None, "kreis_ags": None, "ort": None}
    # A single named city and at most that city's Land.
    if len(cities) == 1:
        name = next(iter(cities))
        code, ags = CITY_KREIS[name]
        other_lands = lands - {code}
        if not other_lands:
            return {
                "land": code,
                "land_ags": LAND_AGS[code],
                "kreis_ags": ags,
                "ort": name if name not in {"Munich", "Cologne"} else (
                    "München" if name == "Munich" else "Köln"
                ),
            }
    # A single named Land, no city AGS.
    if len(lands) == 1 and len(cities) == 0:
        code = next(iter(lands))
        return {"land": code, "land_ags": LAND_AGS[code], "kreis_ags": None, "ort": None}
    # Single-Land station (BR, WDR, HR) when no other Land is named.
    if preset_land and preset_land in LAND_AGS and (not lands or lands == {preset_land}):
        if len(cities) == 0:
            return {
                "land": preset_land,
                "land_ags": LAND_AGS[preset_land],
                "kreis_ags": None,
                "ort": None,
            }
    return {"land": "DE", "land_ags": None, "kreis_ags": None, "ort": None}


def _host_of(url: str) -> str:
    return urllib.parse.urlparse(url).netloc.lower()


class RobotsRefused(Exception):
    """Raised when robots.txt (fail-closed) refuses a URL; the URL is never requested."""


class HostGate:
    """robots.txt + TDM reservation, and a per-host polite clock.

    Every outbound press/media request (sitemaps, HTML search, APIs, tdmrep.json,
    articles) must go through HostGate.fetch. That method reads robots.txt
    fail-closed BEFORE any other request to the host.
    """


    def __init__(self, fetch_bytes: Callable, notes: list[str], *, skip_policy: bool = False):
        self._fetch = fetch_bytes
        self.notes = notes
        self._skip_policy = bool(skip_policy)
        self.robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}
        self._robots_text: dict[str, str] = {}
        self.blocked: dict[str, str] = {}
        self._last: dict[str, float] = {}
        self._crawl_delay: dict[str, float] = {}
        self._tdm_checked: set[str] = set()
        self._sleep = time.sleep

    def wait(self, url: str) -> None:
        host = _host_of(url)
        gap = max(
            HOST_INTERVAL.get(host, MIN_HOST_INTERVAL),
            self._crawl_delay.get(host, 0.0),
            MIN_HOST_INTERVAL,
        )
        last = self._last.get(host, 0.0)
        delay = gap - (time.monotonic() - last)
        if delay > 0:
            self._sleep(delay)
        self._last[host] = time.monotonic()

    def load_robots(self, url: str) -> urllib.robotparser.RobotFileParser | None:
        host = _host_of(url)
        if host in self.robots:
            return self.robots[host]
        robots_url = f"{urllib.parse.urlparse(url).scheme}://{host}/robots.txt"
        rp = urllib.robotparser.RobotFileParser()
        try:
            self.wait(robots_url)
            raw = self._fetch(robots_url)
            text = raw.decode("utf-8", "replace")
            rp.parse(text.splitlines())
            self.robots[host] = rp
            self._robots_text[host] = text
            delay = None
            try:
                delay = rp.crawl_delay(UA) or rp.crawl_delay("*")
            except Exception:
                delay = None
            match = re.search(r"(?im)^crawl-delay:\s*([0-9.]+)\s*$", text)
            if match:
                delay = max(float(delay or 0), float(match.group(1)))
            if delay:
                self._crawl_delay[host] = float(delay)
            if re.search(r"(?i)tdm-?reservation\s*:\s*1\b", text):
                self.blocked[host] = "robots.txt states TDM-Reservation: 1"
            return rp
        except Exception:
            self.robots[host] = None
            return None

    def fetch(self, url: str, *, force: bool = False) -> bytes:
        """The only outbound press request path: robots.txt first, then the URL."""
        from ingest.common import cached_path
        host = _host_of(url)
        if not self._skip_policy:
            ok, reason, delay = press_robots_status(url)
            if delay:
                self._crawl_delay[host] = max(self._crawl_delay.get(host, 0.0), float(delay))
            if not ok:
                if "disallows this path" not in reason:
                    self.blocked[host] = reason
                raise RobotsRefused(reason)
        uncached = force or cached_path(DOMAIN, url) is None
        if uncached:
            self.wait(url)
        return self._fetch(url)

    def check_tdmrep(self, url: str) -> None:
        host = _host_of(url)
        if host in self.blocked or host in self._tdm_checked:
            return
        self._tdm_checked.add(host)
        tdm_url = f"{urllib.parse.urlparse(url).scheme}://{host}/.well-known/tdmrep.json"
        try:
            raw = self.fetch(tdm_url)
            payload = json.loads(raw.decode("utf-8", "replace"))
        except RobotsRefused:
            return
        except Exception:
            return
        records = payload if isinstance(payload, list) else [payload]
        for rec in records:
            if not isinstance(rec, dict):
                continue
            reserved = rec.get("tdm-reservation") or rec.get("tdm_reservation")
            if str(reserved) in {"1", "true", "True"}:
                self.blocked[host] = "tdmrep.json reserves TDM"
                return

    def allow(self, url: str, *, is_article: bool = False) -> tuple[bool, str]:
        host = _host_of(url)
        if host in self.blocked:
            return False, self.blocked[host]
        ok, reason, delay = press_robots_status(url)
        if delay:
            self._crawl_delay[host] = max(self._crawl_delay.get(host, 0.0), float(delay))
        if not ok:
            # Host-level failures (403/5xx/network/redirect) skip the whole host.
            if "disallows this path" not in reason:
                self.blocked[host] = reason
            return False, reason
        self.check_tdmrep(url)
        if host in self.blocked:
            return False, self.blocked[host]
        return True, ""

    def tdm_in_page(self, url: str, raw: bytes, headers: dict | None = None) -> str | None:
        host = _host_of(url)
        if headers:
            for key, value in headers.items():
                if str(key).lower() in {"tdm-reservation", "tdm_reservation"} and str(value).strip() in {"1", "true", "True"}:
                    self.blocked[host] = "HTTP header tdm-reservation=1"
                    return self.blocked[host]
        text = raw.decode("utf-8", "replace")
        if re.search(r'(?i)<meta[^>]+name=["\']tdm-reservation["\'][^>]+content=["\']1["\']', text):
            self.blocked[host] = "HTML meta tdm-reservation=1"
            return self.blocked[host]
        if re.search(r'(?i)<meta[^>]+content=["\']1["\'][^>]+name=["\']tdm-reservation["\']', text):
            self.blocked[host] = "HTML meta tdm-reservation=1"
            return self.blocked[host]
        return None


def ensure_press_columns(conn) -> None:
    cols = {row[1] for row in conn.execute("PRAGMA table_info(media)").fetchall()}
    if "land_ags" not in cols:
        conn.execute("ALTER TABLE media ADD COLUMN land_ags TEXT")
    if "kreis_ags" not in cols:
        conn.execute("ALTER TABLE media ADD COLUMN kreis_ags TEXT")


def existing_media_urls(conn) -> set[str]:
    urls = set()
    for row in conn.execute("SELECT url FROM media"):
        norm = normalize_url(row[0])
        if norm:
            urls.add(norm)
    try:
        from ingest.domains.institutions_media_investigations import CATALOG
        for rec in CATALOG:
            norm = normalize_url(rec.get("url"))
            if norm:
                urls.add(norm)
    except Exception:
        pass
    return urls


def outlet_source_id(conn, feed: dict, sources) -> int | None:
    """One source row per outlet (imprint URL), not per article."""
    publisher = clean(feed.get("publisher") or feed.get("herausgeber"))
    license_url = clean(feed.get("license_url"))
    # Prefer an outlet-specific official URL so two regional desks that
    # share an imprint still get one source row each.
    source_url = clean(feed.get("source_url")) or license_url
    if not publisher or not source_url:
        return None
    licence = clean(feed.get("license")) or FACTS_LICENCE
    return _im()._register_source(
        conn, source_url,
        title=f"{publisher} (press/media outlet)",
        publisher=publisher,
        license_=licence,
        bucket=sources,
        license_url=license_url or source_url,
        attribution=publisher,
        notes=REDIS_NOTE,
        redistribute_fulltext=0,
    )


def store_press_article(conn, rec: dict, *, sources) -> bool:
    ensure_press_columns(conn)
    url = normalize_url(rec.get("url"))
    title = clean(rec.get("title"))
    publisher = clean(rec.get("publisher") or rec.get("herausgeber"))
    tag = clean(rec.get("topic") or rec.get("zusammenfassung"))
    licence = clean(rec.get("license")) or FACTS_LICENCE
    if not url or not title or not publisher or not tag or not licence:
        return False
    if not fields_name_ok(title, rec.get("ort")):
        return False
    if rec.get("kind") not in (None, KIND):
        return False
    feed = rec.get("feed") or {
        "publisher": publisher,
        "license_url": rec.get("license_url"),
        "license": licence,
        "source_url": rec.get("license_url"),
    }
    source_id = outlet_source_id(conn, feed, sources)
    if not source_id:
        return False
    land = rec.get("land") if rec.get("land") in (set(LAND_AGS) | {"DE"}) else "DE"
    land_ags = clean(rec.get("land_ags"))
    kreis_ags = clean(rec.get("kreis_ags"))
    if land == "DE":
        # National rows must not carry a Land or Kreis AGS.
        land_ags = None
        kreis_ags = None
    elif land in LAND_AGS:
        if land_ags and land_ags != LAND_AGS[land]:
            land_ags = None
        elif rec.get("land_ags") == LAND_AGS[land]:
            land_ags = LAND_AGS[land]
        else:
            land_ags = None if not land_ags else land_ags
    upsert(conn, "media", {
        "kind": KIND,
        "title": title,
        "url": url,
        "herausgeber": publisher,
        "urheber": None,
        "veroeffentlicht": clean(rec.get("published") or rec.get("veroeffentlicht")),
        "ort": clean(rec.get("ort")),
        "land": land,
        "lizenz": licence,
        "zusammenfassung": tag,
        "source_id": source_id,
        "land_ags": land_ags,
        "kreis_ags": kreis_ags,
    }, ["url"])
    return True


def _default_fetch(url: str, *, force: bool = False) -> bytes:
    return common.fetch(url, domain=DOMAIN, force=force)


def _search_terms() -> list[str]:
    # Fewer, high-yield queries; avoid almost-duplicate stems.
    return [
        "Wohnungslosigkeit",
        "Obdachlosigkeit",
        "Kältehilfe",
        "Notunterkunft",
        "Housing First",
        "Wohnungsnotfallhilfe",
        "Kältebus",
    ]


def ingest_press(conn, cfg, sources, notes) -> int:
    """Discover, fetch and store press/broadcaster article media rows."""
    ensure_press_columns(conn)
    force = bool(cfg.get("force"))
    configured_fetch = cfg.get("fetch") or _default_fetch

    def fetch_bytes(url: str, force: bool = False) -> bytes:
        try:
            return configured_fetch(url, force=force)
        except TypeError:
            return configured_fetch(url)

    feeds = list(cfg.get("press_feeds") or FEEDS)
    limit = cfg.get("limit")
    max_total = int(limit) if limit is not None else None
    skip_policy = bool(cfg.get("skip_host_policy"))
    preloaded = cfg.get("press_pages")  # offline: [{url, raw, title, publisher, ...}]
    seen = existing_media_urls(conn)
    stored = 0
    skipped_host = 0
    skipped_topic = 0
    skipped_quote = 0
    skipped_names = 0
    skipped_dup = 0
    skipped_paywall = 0
    failed = 0
    per_host: dict[str, int] = defaultdict(int)
    per_feed: dict[str, int] = defaultdict(int)
    gate = HostGate(lambda url: fetch_bytes(url, force=force), notes, skip_policy=skip_policy)

    def fetch_url(url: str) -> bytes:
        # Every sitemap, search, API, tdmrep and article request goes through
        # HostGate.fetch, which reads robots.txt fail-closed first.
        return gate.fetch(url, force=force)

    # Offline path used by tests: pages already in memory, no network.
    if preloaded:
        for rec in preloaded:
            rec = dict(rec)
            url = normalize_url(rec.get("url"))
            raw = rec.get("raw")
            if isinstance(raw, str):
                raw = raw.encode("utf-8")
            if not url or raw is None:
                continue
            if url in seen:
                skipped_dup += 1
                continue
            text = page_text(raw) if raw else ""
            title = rec.get("title") or extract_html_title(raw) if raw else rec.get("title")
            if not title:
                skipped_quote += 1
                continue
            if not fields_name_ok(title):
                skipped_names += 1
                continue
            tag = rec.get("topic") or topic_tag(title, rec.get("summary"), url, text)
            if not tag:
                skipped_quote += 1
                continue
            feed = rec.get("feed") or {
                "publisher": rec.get("publisher"),
                "land": rec.get("land", "DE"),
                "license_url": rec.get("license_url"),
                "license": FACTS_LICENCE,
            }
            geo = assign_geo(feed, title, rec.get("summary") or text, url)
            stored_rec = {
                "url": url,
                "title": title,
                "publisher": rec.get("publisher") or feed.get("publisher"),
                "published": rec.get("published"),
                "topic": tag,
                "license": FACTS_LICENCE,
                "license_url": rec.get("license_url") or feed.get("license_url"),
                "feed": feed,
                **geo,
            }
            if rec.get("land"):
                stored_rec["land"] = rec["land"]
            if rec.get("land_ags") or rec.get("kreis_ags") or rec.get("ort"):
                stored_rec["land_ags"] = rec.get("land_ags", geo.get("land_ags"))
                stored_rec["kreis_ags"] = rec.get("kreis_ags", geo.get("kreis_ags"))
                stored_rec["ort"] = rec.get("ort", geo.get("ort"))
            if store_press_article(conn, stored_rec, sources=sources):
                stored += 1
                seen.add(url)
        notes.append(
            f"Press/broadcaster media stored={stored} (offline fixture) "
            f"dup={skipped_dup} quote_skipped={skipped_quote} name_skipped={skipped_names}"
        )
        return stored

    # Discover slow hosts last so other official feeds are collected first.
    feeds = sorted(
        feeds,
        key=lambda f: 1 if "tagesschau.de" in (f.get("url") or "") else 0,
    )
    candidates: list[dict] = []
    for feed in feeds:
        fid = feed.get("id") or feed.get("url")
        url = feed.get("url")
        if not url:
            continue
        if not skip_policy:
            # Policy is checked on a concrete URL; search templates are filled first.
            probe = url.replace("{q}", "Wohnungslosigkeit")
            ok, reason = gate.allow(probe, is_article=False)
            if not ok:
                skipped_host += 1
                notes.append(f"Skipped source {fid} ({_host_of(probe)}): {reason}")
                continue
        try:
            items = _discover_feed(feed, fetch_url=fetch_url, notes=notes)
        except Exception as exc:
            failed += 1
            notes.append(f"Feed {fid} failed: {type(exc).__name__}: {str(exc)[:160]}")
            print(f"[press] feed {fid} failed: {type(exc).__name__}: {str(exc)[:160]}", flush=True)
            continue
        kept = 0
        cap = int(feed.get("max_items") or 200)
        for item in items:
            article = normalize_url(item.get("url"))
            if not article:
                continue
            if article in seen or any(c.get("url") == article for c in candidates):
                skipped_dup += 1
                continue
            title, summary = item.get("title"), item.get("summary")
            # Topic filter on metadata; HTML-search items without a title are
            # fetched only when the path itself looks on-topic, else skipped.
            if title or summary:
                if not has_topic(title, summary, article):
                    skipped_topic += 1
                    continue
            elif not has_topic(article):
                skipped_topic += 1
                continue
            candidates.append({
                "url": article,
                "title": title,
                "summary": summary,
                "published": item.get("published"),
                "feed": feed,
            })
            kept += 1
            if kept >= cap:
                break
        notes.append(f"Feed {fid} candidates={kept}")
        print(f"[press] feed {fid} candidates={kept}", flush=True)

    # Interleave by host so a slow host (tagesschau 61s) does not stall the rest.
    buckets: dict[str, list[dict]] = defaultdict(list)
    for item in candidates:
        buckets[_host_of(item["url"])].append(item)
    order = list(buckets)
    idx = {host: 0 for host in order}

    def next_item():
        while order:
            host = order.pop(0)
            i = idx[host]
            if i >= len(buckets[host]):
                continue
            idx[host] = i + 1
            order.append(host)
            return buckets[host][i]
        return None

    while True:
        if max_total is not None and stored >= max_total:
            break
        item = next_item()
        if item is None:
            break
        url = item["url"]
        feed = item["feed"]
        if url in seen:
            skipped_dup += 1
            continue
        if not skip_policy:
            ok, reason = gate.allow(url, is_article=True)
            if not ok:
                skipped_host += 1
                notes.append(f"Skipped article host {_host_of(url)}: {reason}")
                # Drop remaining candidates on a reserved/blocked host.
                buckets[_host_of(url)] = []
                continue
        title = item.get("title")
        published = item.get("published")
        raw = None
        text = None
        # Fetch the page only when the headline or date is missing from the feed.
        if not title or not published:
            try:
                raw = fetch_url(url)
            except Exception as exc:
                failed += 1
                message = str(exc)
                if "HTTP 403" in message or "HTTP 404" in message:
                    notes.append(f"Article fetch {_host_of(url)}: {message[:120]}")
                continue
            if not skip_policy:
                reserved = gate.tdm_in_page(url, raw)
                if reserved:
                    skipped_host += 1
                    notes.append(f"Skipped host {_host_of(url)} after page TDM check: {reserved}")
                    buckets[_host_of(url)] = []
                    continue
            text = page_text(raw)
            if is_paywalled(text):
                skipped_paywall += 1
                continue
            title = title or extract_html_title(raw)
            published = published or parse_published(text[:800])
        if not title:
            skipped_quote += 1
            continue
        if not has_topic(title, item.get("summary"), url):
            skipped_topic += 1
            continue
        if not is_germany_scope(title, item.get("summary"), url):
            skipped_topic += 1
            continue
        if not fields_name_ok(title):
            skipped_names += 1
            continue
        tag = topic_tag(title, item.get("summary"), url)
        if not tag:
            skipped_topic += 1
            continue
        geo = assign_geo(feed, title, item.get("summary"), url)
        rec = {
            "url": url,
            "title": title,
            "publisher": feed.get("publisher"),
            "published": published,
            "topic": tag,
            "license": FACTS_LICENCE,
            "license_url": feed.get("license_url"),
            "feed": feed,
            **geo,
        }
        if store_press_article(conn, rec, sources=sources):
            stored += 1
            seen.add(url)
            per_host[_host_of(url)] += 1
            per_feed[feed.get("id") or feed.get("url")] += 1
            if stored % 10 == 0 or stored <= 3:
                print(f"[press] stored={stored} last={url}", flush=True)

    host_text = ", ".join(f"{host}={count}" for host, count in sorted(per_host.items())) or "none"
    blocked = ", ".join(f"{host} ({why})" for host, why in sorted(gate.blocked.items())) or "none"
    notes.append(
        f"Press/broadcaster media stored={stored} candidates={len(candidates)} "
        f"fetch_failed={failed} topic_skipped={skipped_topic} quote_skipped={skipped_quote} "
        f"name_skipped={skipped_names} dup={skipped_dup} paywall={skipped_paywall} "
        f"host_skipped={skipped_host}. Per host: {host_text}. "
        f"Blocked/reserved hosts: {blocked}. "
        "All stored rows are headline/date/outlet/URL/topic-tag only, with one rights-reserved facts-only source per outlet and redistribute_fulltext=0."
    )
    return stored


def _discover_feed(feed: dict, *, fetch_url, notes) -> list[dict]:
    kind = feed.get("kind") or "rss"
    url = feed["url"]
    if kind in {"rss", "atom"}:
        raw = fetch_url(url)
        return parse_feed_items(raw)
    if kind == "tagesschau_search":
        items = []
        seen = set()
        # Official API cap is 60 requests/hour; keep search itself small.
        terms = tuple(feed.get("search_terms") or (
            "Wohnungslosigkeit",
            "Obdachlosigkeit",
            "Kältehilfe",
            "Notunterkunft",
            "Housing First",
            "Wohnungsnotfallhilfe",
            "Kältebus",
        ))
        max_pages = int(feed.get("search_pages") or 5)
        budget = int(feed.get("max_search_requests") or 18)
        used = 0
        for term in terms:
            for page in range(0, max_pages):
                if used >= budget:
                    return items
                used += 1
                query = urllib.parse.urlencode({
                    "searchText": term,
                    "pageSize": 20,
                    "resultPage": page,
                })
                raw = fetch_url(url + ("&" if "?" in url else "?") + query)
                try:
                    payload = json.loads(raw.decode("utf-8", "replace"))
                except json.JSONDecodeError as exc:
                    notes.append(f"tagesschau search for {term!r} was not JSON: {exc}")
                    break
                batch = parse_tagesschau_search(payload)
                if not batch:
                    break
                for item in batch:
                    if item["url"] in seen:
                        continue
                    seen.add(item["url"])
                    items.append(item)
                if len(batch) < 10:
                    break
        return items
    if kind in {"sitemap", "news_sitemap", "sitemap_index"}:
        return discover_from_sitemap(feed, fetch_url=fetch_url, notes=notes)
    if kind == "html_index":
        pages = list(feed.get("pages") or [url])
        items = []
        seen_pages: set[str] = set()
        for page_url in pages:
            if not page_url or page_url in seen_pages:
                continue
            seen_pages.add(page_url)
            raw = fetch_url(page_url)
            for item in extract_search_links(
                raw, base=page_url,
                link_host=feed.get("link_host"),
                link_must=feed.get("link_must"),
            ):
                if item.get("url") and item["url"] not in {i.get("url") for i in items}:
                    items.append(item)
        if feed.get("trust_index"):
            return items
        return [item for item in items if has_topic(item.get("title"), item.get("url"), item.get("summary"))]
    if kind == "html_search":
        items = []
        seen = set()
        for term in _search_terms():
            page_url = url.format(q=urllib.parse.quote(term))
            raw = fetch_url(page_url)
            for item in extract_search_links(
                raw, base=page_url,
                link_host=feed.get("link_host"),
                link_must=feed.get("link_must"),
            ):
                if not item.get("url") or item["url"] in seen:
                    continue
                seen.add(item["url"])
                items.append(item)
        return items
    notes.append(f"Unknown feed kind {kind} for {feed.get('id')}")
    return []


if __name__ == "__main__":
    from ingest.common import no_direct_run
    raise SystemExit(no_direct_run("institutions_media"))
