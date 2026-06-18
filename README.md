# Hit-List Engine

A personal outbound engine. Each morning it hands you a ready-to-execute **hit-list** at your
target companies, each person with a deep dossier and a draft in your voice:
- **LinkedIn** for right-level peers / hiring managers — a warm-up comment + 2–3 DM options.
- **Email** for senior people (founders / C-suite) — a cold email (subject + body) with a
  public address it found, because a cold DM to them is weak but a sharp email can land.

You read, tweak, and **send by hand**. The machine does the research and drafting; you do the
human part.

```
discover → research → match+draft → digest → email → track
```

## Hard constraints
1. **Never auto-sends anything.** No browser automation, no auto-connect/DM, no auto-emailing.
   Every LinkedIn message and email is a draft you send by hand.
2. **Channel by seniority.** Right-level peers / hiring managers (Head/Director of FDE/SE,
   Senior/Staff SE/FDE, eng managers) → **LinkedIn** comment + DMs. Founders / C-suite / execs
   → **cold email** (a DM to them is weak; a specific email isn't).
3. **No fabrication.** Thin research → person is dropped, never guessed. Email addresses come
   from real public sources only — never pattern-guessed.
4. **Dedup.** Never queues anyone already in `tracker.csv`.
5. **Drafts for human review only.** Nothing is sent automatically.

## Discovery: who finds the people
`run.discovery_source` in `config.yaml` picks how the "find people" step works — the
high-effort step this whole thing exists to automate:
- **`perplexity`** (default): Sonar web-search **finds the people for you** at each target
  company ("senior solutions/forward-deployed engineers at <company>, with sources"). It
  surfaces publicly-visible people — team pages, talks, GitHub, press — which are exactly the
  ones you can write a sharp, personal message to. Not a structured database, so coverage
  varies and it's told never to guess; every name is re-verified by the deep research step and
  your own review. Uses `PERPLEXITY_API_KEY` (cheap; ~covered by Pro credit).
- **`seed`**: the engine reads **`people_seed.csv`** — a list you fill by hand / Clay export.
  Fully manual, $0, no API. Good for hand-picked targets. See `people_seed.example.csv`.
- **`pdl`**: People Data Labs Person Search API. Structured, but the free tier is tiny and
  quota-limited; realistic only on a paid plan.

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
src/discover.py             Perplexity finder / seed CSV / PDL search → people (+ warm-path split)
src/research.py             Perplexity Sonar → recent intel per person
src/match_draft.py          strongest overlap → LinkedIn comment+DMs OR cold email (strict JSON)
src/digest.py               render hit-list as HTML (LinkedIn + email sections)
src/deliver.py              Gmail SMTP
src/tracker.py              CSV log, dedup, follow-up flags
main.py                     orchestration (--mocks, --no-mocks, --limit)
```

## Cost
Seed-mode discovery is $0 (no vendor). Drafting via `claude_cli` uses your Claude login (no
API spend), Perplexity ~covered by Pro credit, Gmail + GitHub Actions free. **Total ≈ $0/mo**
in the default config. (PDL mode or `draft_backend: api` add metered cost.)
