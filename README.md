# Hit-List Engine

A personal outbound engine. Each morning it hands you a ready-to-execute LinkedIn
**hit-list**: ~8 right-level people at your target companies, each with recent intel, a
warm-up comment, and 2–3 DM options written in your voice. You read, tweak, and **send by
hand**. The machine does the research and drafting; you do the human part.

```
discover → research → match+draft → digest → email → track
```

## Hard constraints
1. **Never automates LinkedIn.** No browser automation, no scraping, no auto-connect/DM.
   Discovery is a seed list (or People Data Labs' API) + open-web research only. You send
   everything by hand.
2. **Seniority targeting.** Cold queue = hiring managers (Head/Director of FDE/SE), senior IC
   peers (Senior/Staff SE/FDE), eng managers/leads. Founders / C-suite / VPs are routed to
   `warm_path.csv` (intro only), never the cold queue.
3. **No fabrication.** Thin research → person is dropped, never guessed.
4. **Dedup.** Never queues anyone already in `tracker.csv`.
5. **Drafts for human review only.** Nothing is sent automatically.

## Discovery: seed list vs PDL
`run.discovery_source` in `config.yaml` picks where the names come from:
- **`seed`** (default): the engine reads **`people_seed.csv`** — a list you fill however you
  like (by hand, a Clay export, an agent). Only `name` + `company` are required; anything
  else (github/twitter/linkedin/domain/title) just deepens the dossier. **$0, no API, no
  vendor credit wall.** See `people_seed.example.csv` for the format. This is the robust
  default because no people-data vendor gives real person-search away for free.
- **`pdl`**: People Data Labs Person Search API (needs `PDL_API_KEY`). Automated, but the
  free tier is tiny and quickly rate-/quota-limited; realistic only on a paid plan.

Either way, the valuable part — the deep open-web dossier + the draft — is identical.

## Setup
1. `pip install -r requirements.txt`
2. `cp .env.example .env` and fill keys:
   - **Perplexity**: a `pplx-…` Sonar API key (Pro grants ~$5/mo credit; the chat sub is separate).
   - **People Data Labs** (only if `discovery_source: pdl`): free key at dashboard.peopledatalabs.com.
   - **Anthropic**: only needed if you set `draft_backend: api`; the default `claude_cli` uses your login.
   - **Gmail**: a Google **App Password** (needs 2FA), not your real password.
3. Fill `people_seed.csv` (seed mode), edit `config.yaml` (run settings, seniority rules) and
   `profile/alejandro_profile.md` (your "me" layer).

## Run
```bash
python main.py --mocks      # full pipeline on sample data, $0. Open digest_<date>.html.
python main.py --no-mocks   # real keys: discovers, researches, drafts, emails, logs.
python main.py --no-mocks --limit 3
```
Any key left blank in `.env` automatically forces that module into mock mode, so you can flip
mocks off **one module at a time** (draft → research → discover → deliver).

## Autonomous cron
`.github/workflows/daily.yml` runs `main.py --no-mocks` on a weekday schedule, emails the
digest, and **commits `tracker.csv` back** (GitHub Actions is ephemeral, so this is how dedup
survives across days). Add these repo secrets:
`CLAUDE_CODE_OAUTH_TOKEN, PERPLEXITY_API_KEY, GMAIL_ADDRESS, GMAIL_APP_PASSWORD, DIGEST_TO`
(plus `PDL_API_KEY` only if `discovery_source: pdl`). In seed mode, commit your
`people_seed.csv` so the cron can read it.

## Layout
```
config.yaml                 targets, seniority rules, run settings
profile/alejandro_profile.md  the "me" layer (read whole, passed to the model)
people_seed.csv             seed-mode input: your list of people (name,company,…)
src/discover.py             seed CSV reader / PDL Person Search → people (+ warm-path split)
src/research.py             Perplexity Sonar → recent intel per person
src/match_draft.py          Anthropic → strongest overlap + comment + DMs (strict JSON)
src/digest.py               render hit-list as HTML
src/deliver.py              Gmail SMTP
src/tracker.py              CSV log, dedup, follow-up flags
main.py                     orchestration (--mocks, --no-mocks, --limit)
```

## Cost
Seed-mode discovery is $0 (no vendor). Drafting via `claude_cli` uses your Claude login (no
API spend), Perplexity ~covered by Pro credit, Gmail + GitHub Actions free. **Total ≈ $0/mo**
in the default config. (PDL mode or `draft_backend: api` add metered cost.)
