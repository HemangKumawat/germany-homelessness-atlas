# counts_law — Destatis counts, Wohnungslosenbericht, Länder figures, and the law

status: OPEN
owner: Counts & Law bot
branch: worker/counts_law
deps: ingest/schema.sql pit, geo_land, geo_kreis, geo_gemeinde, law, doc
accept: ingest/domains/counts_law.py + research/counts_law.md; AGS geography
(Land 2-digit, Kreis 5-digit, Gemeinde 8-digit); Destatis GENESIS 22971 and the
Wohnungslosenbericht ingested with the figure as printed; is_est=1 on estimates;
law rows for SGB XII §67, Ordnungsrechtliche Unterbringung, and Aktionspläne,
each citing the source text.

Do not invent an AGS or a count. If a Land or city publishes a figure that Destatis
does not, store it with its own source_id and do not overwrite the Destatis row.
