# Bots — who does what

## Roles

| Role | Bot id | Writes | Must not |
|---|---|---|---|
| **Lead** | `3654d8e3-0a25-4f61-880d-dee87f1aec7f` | `data/atlas.db` (the only writer), `scripts/verify.py`, `scripts/audit.py`, `scripts/build_site.py`, `scripts/backup_db.sh`, merges | change the fleet default model; touch reels folders or WhatsApp files; publish the site or push to GitHub without owner approval |
| **Funding & Träger** | (worker) | `ingest/domains/funding_traeger.py`, `research/funding_traeger.md` on branch `worker/funding_traeger`; may append one row to `docs/SOURCES.md` | open or write `data/atlas.db`; edit another domain; edit `site/` or `scripts/` |
| **Counts & Law** | (worker) | `ingest/domains/counts_law.py`, `research/counts_law.md` on branch `worker/counts_law`; may append one row to `docs/SOURCES.md` | same as above |
| **Institutions & Media** | (worker) | `ingest/domains/institutions_media.py`, `research/institutions_media.md` on branch `worker/institutions_media`; may append one row to `docs/SOURCES.md` | same as above |

Workers deliver a domain module plus research notes on their own git branch.
The Lead reviews, merges, and only then runs `python3 -m ingest.run <domain>`
against the database (single-writer flock). The US atlas slowed to a crawl and
once corrupted its SQLite file when ten processes wrote at once; that is why
the split exists.

## Grok Build on this machine

Grok Build (the `grok` CLI) is installed at `~/.local/bin/grok`. Confirmed
working: `grok --version` reports `grok 1.0.88`, and `grok models` reports
that the CLI is signed in with grok.com. Leave the CLI default model alone
(do not pass `--model` and do not write a per-project model override unless
the owner asks).

### Headless / non-interactive launch in this repo

Single-turn (prints the reply to stdout and exits):

```bash
cd ~/projects/germany-atlas
grok --cwd ~/projects/germany-atlas \
  --permission-mode acceptEdits \
  --output-format plain \
  --max-turns 1 \
  -p "PROMPT"
```

Multi-turn worker (non-interactive, tools auto-approved, turn cap):

```bash
cd ~/projects/germany-atlas
grok --cwd ~/projects/germany-atlas \
  --permission-mode acceptEdits \
  --always-approve \
  --output-format plain \
  --max-turns 80 \
  -p "PROMPT"
```

Prompt from a file (a queue item, or `logs/workers/<domain>.prompt.txt`):

```bash
cd ~/projects/germany-atlas
grok --cwd ~/projects/germany-atlas \
  --permission-mode acceptEdits \
  --always-approve \
  --output-format plain \
  --max-turns 80 \
  --prompt-file queue/01-funding_traeger.md
```

`--output-format` may also be `json` or `streaming-json`. Do not use
`grok agent headless`: that attaches to the Grok WebSocket relay, it is not a
one-shot repo run. `scripts/loop.sh` uses the multi-turn form above.

Trusted-folder approval may be required the first time Grok Build sees this
directory; after that, the same command runs unattended.
