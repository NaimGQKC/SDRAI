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
   Discovery is Apollo's API + open-web research only. You send everything by hand.
2. **Seniority targeting.** Cold queue = hiring managers (Head/Director of FDE/SE), senior IC
   peers (Senior/Staff SE/FDE), eng managers/leads. Founders / C-suite / VPs are routed to
   `warm_path.csv` (intro only), never the cold queue.
3. **No fabrication.** Thin research → person is dropped, never guessed.
4. **Dedup.** Never queues anyone already in `tracker.csv`.
5. **Drafts for human review only.** Nothing is sent automatically.

## Setup
1. `pip install -r requirements.txt`
2. `cp .env.example .env` and fill keys:
   - **Apollo**: Settings → Integrations → API Keys (scope: People Search + Enrichment).
   - **Perplexity**: a `pplx-…` Sonar API key (Pro grants ~$5/mo credit; the chat sub is separate).
   - **Anthropic**: pay-as-you-go API key for the cron's drafting.
   - **Gmail**: a Google **App Password** (needs 2FA), not your real password.
3. Edit `config.yaml` (targets, seniority rules) and `profile/alejandro_profile.md` (your "me" layer).

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
`ANTHROPIC_API_KEY, PERPLEXITY_API_KEY, APOLLO_API_KEY, GMAIL_ADDRESS, GMAIL_APP_PASSWORD, DIGEST_TO`.

## Layout
```
config.yaml                 targets, seniority rules, run settings
profile/alejandro_profile.md  the "me" layer (read whole, passed to the model)
src/discover.py             Apollo People Search → right-level people (+ warm-path split)
src/research.py             Perplexity Sonar → recent intel per person
src/match_draft.py          Anthropic → strongest overlap + comment + DMs (strict JSON)
src/digest.py               render hit-list as HTML
src/deliver.py              Gmail SMTP
src/tracker.py              CSV log, dedup, follow-up flags
main.py                     orchestration (--mocks, --no-mocks, --limit)
```

## Cost
Apollo free tier, Perplexity ~covered by Pro credit, Anthropic ~$2–5/mo on Sonnet, Gmail +
GitHub Actions free. **Total ≈ $0–5/mo.**
