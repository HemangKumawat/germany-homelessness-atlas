# funding_traeger — every public Träger, contract and grant

status: OPEN
owner: Funding & Träger bot
branch: worker/funding_traeger
deps: ingest/schema.sql org, org_person, award
accept: ingest/domains/funding_traeger.py + research/funding_traeger.md; idempotent upserts;
named officers only from published filings; amounts in EUR with source_id on every row;
no protected-shelter addresses.

Collect publicly available records of homelessness and housing-emergency providers
in Germany (freier Träger such as Diakonie, Caritas, AWO, DRK, independent gGmbH,
municipal Träger, housing companies where they hold a public contract) and the
public contracts, Zuwendungen and grants that pay them — Bund, Land, Kommune and
EU — from official publications, Haushaltspläne, govdata, TED/ELI, and published
register / Impressum / Jahresbericht filings.
