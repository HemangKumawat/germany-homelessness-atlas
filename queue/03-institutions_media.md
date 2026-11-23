# institutions_media — hospitals, prisons, audits, Bundestag papers, and media

status: OPEN
owner: Institutions & Media bot
branch: worker/institutions_media
deps: ingest/schema.sql facility, doc, media
accept: ingest/domains/institutions_media.py + research/institutions_media.md;
open and closed psychiatric hospitals and prisons with published economics in EUR;
audits, court decisions, Bundestag and Landtag papers; media with a recorded licence;
Frauenhaus / protected-shelter rows must have address, lat and lon left NULL.

Public data only. Named professional roles from published institutional sources
are in scope; private individuals who are not in a public role are not.
