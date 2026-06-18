"""match_draft.py — the brain.

Finds the single strongest genuine overlap between Alejandro and one target person, then
drafts outreach in his voice. Two channels:
  linkedin -> a warm-up comment + 2-3 DM options (for right-level peers / hiring managers)
  email    -> a cold email (subject + body) for senior people (founders / C-suite / execs),
              where a cold DM is weak but a sharp, specific email can land.
Both return strict JSON.

Backends (cfg['run']['draft_backend']):
  claude_cli -> shells out to `claude -p` (Claude Code). No Anthropic API key; uses the
                logged-in Pro subscription locally, or CLAUDE_CODE_OAUTH_TOKEN in CI.
  api        -> Anthropic API (needs ANTHROPIC_API_KEY). Fallback only.
  mock       -> canned sample drafts (also used by --mocks).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess

# --- LinkedIn channel: warm-up comment + DM options -------------------------------------
SYSTEM_LINKEDIN = """You are Alejandro's outreach engine. You are given his profile and fresh research on one
target person. Find the SINGLE strongest genuine overlap between them and write outreach
in his voice.

Rules:
- Pick the overlap that could only be said to this one person. Discard generic matches.
- Voice: under 75 words, conversational, sharp, confident — an ambitious peer, not an
  applicant. Open on THEM. No flattery, no "I hope this finds you well," no corporate filler.
  End on a low-friction ask (usually a 15-minute call), sometimes with an easy out.
- The comment is a warm-up reaction to their most recent post: additive (a sharp take, a real
  question, or "I hit this exact thing when I built X") — never "great post."
- If the research is thin or you're unsure of a fact, lower the tier and say so. Never invent
  facts, quotes, or links.

Return STRICT JSON only, no prose, no code fences:
{"tier":"A|B|C","angle":"<one line>","comment":"<warm-up comment>",
 "dms":["<dm option 1>","<dm option 2>"],"why":"<one line: which overlap it uses>"}"""

# --- Email channel: cold email to a senior person ---------------------------------------
SYSTEM_EMAIL = """You are Alejandro's cold-email writer. You are given his profile and fresh research on one
SENIOR person (founder / C-suite / exec). A cold LinkedIn DM to them would be weak — write a
short, specific cold email in his voice that earns a reply.

Rules:
- Find the SINGLE strongest genuine reason only HE could send THIS person. Discard generic.
- Subject: <= 8 words, specific and intriguing — no clickbait, no "quick question", nothing
  that reads like a mass blast.
- Body: under 120 words. Open on THEM or their company's specific current moment/work — never
  on himself. Give one concrete reason for reaching out, one line of real credibility (he
  BUILDS and SELLS: shipped VisiMind and NadiaAI end-to-end, solo forward-deployed work), one
  low-friction ask (15-min call, or a sharp question), and an easy out. Sign "— Alejandro".
  No "I hope this finds you well", no flattery, no corporate filler.
- If research is thin or you're unsure of a fact, lower the tier and say so. Never invent
  facts, quotes, or links.

Return STRICT JSON only, no prose, no code fences:
{"tier":"A|B|C","subject":"<subject line>","body":"<email body>","why":"<one line: the reason it uses>"}"""

_LOW_CONF_LINKEDIN = {"tier": "C", "angle": "", "comment": "", "dms": [],
                      "why": "low_confidence: drafter returned no usable JSON"}
_LOW_CONF_EMAIL = {"tier": "C", "subject": "", "body": "",
                   "why": "low_confidence: drafter returned no usable JSON"}


def _build_user_message(profile: str, person: dict, research_text: str) -> str:
    return (
        "=== ALEJANDRO'S PROFILE ===\n"
        f"{profile}\n\n"
        "=== TARGET PERSON ===\n"
        f"Name: {person['name']}\n"
        f"Title: {person['title']}\n"
        f"Company: {person['company']}\n"
        f"Location: {person.get('location') or '(unknown)'}\n"
        f"GitHub: {person.get('github') or '(none)'}\n"
        f"X/Twitter: {person.get('twitter') or '(none)'}\n"
        f"Previously: {', '.join(person.get('prior') or []) or '(unknown)'}\n"
        f"LinkedIn: {person.get('linkedin') or '(unknown)'}\n\n"
        "=== DOSSIER (prefer a specific artifact/view from here over the job title) ===\n"
        f"{research_text}\n"
    )


def _extract_json(text: str) -> dict:
    """Strip code fences / surrounding prose and parse the first JSON object."""
    cleaned = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        raise


def _coerce_linkedin(data: dict) -> dict:
    dms = data.get("dms") or []
    if isinstance(dms, str):
        dms = [dms]
    return {
        "tier": str(data.get("tier", "C")).strip().upper()[:1] or "C",
        "angle": data.get("angle", "").strip(),
        "comment": data.get("comment", "").strip(),
        "dms": [d.strip() for d in dms if d and d.strip()],
        "why": data.get("why", "").strip(),
    }


def _coerce_email(data: dict) -> dict:
    return {
        "tier": str(data.get("tier", "C")).strip().upper()[:1] or "C",
        "subject": data.get("subject", "").strip(),
        "body": data.get("body", "").strip(),
        "why": data.get("why", "").strip(),
    }


# channel -> (system prompt, coerce fn, low-confidence default, mock fn)
def _channel_spec(channel: str):
    if channel == "email":
        return SYSTEM_EMAIL, _coerce_email, _LOW_CONF_EMAIL, _mock_email
    return SYSTEM_LINKEDIN, _coerce_linkedin, _LOW_CONF_LINKEDIN, _mock_linkedin


def match_draft(profile: str, person: dict, research_text: str, cfg: dict,
                use_mocks: bool = True, channel: str = "linkedin") -> dict:
    """Return a draft dict. LinkedIn: {tier,angle,comment,dms[],why}. Email: {tier,subject,body,why}."""
    system, coerce, low_conf, mock = _channel_spec(channel)
    backend = "mock" if use_mocks else cfg["run"].get("draft_backend", "claude_cli")
    user_msg = _build_user_message(profile, person, research_text)

    if backend == "mock":
        return mock(person)
    if backend == "api":
        return _draft_via_api(user_msg, cfg, person, system, coerce, low_conf, mock)
    return _draft_via_cli(user_msg, cfg, person, system, coerce, low_conf, mock)


# --- claude_cli backend: `claude -p` (Claude Code, no API key) --------------------------

def _draft_via_cli(user_msg, cfg, person, system, coerce, low_conf, mock) -> dict:
    """Draft by shelling out to Claude Code in non-interactive print mode."""
    claude = shutil.which("claude") or shutil.which("claude.cmd")
    if not claude:
        print("  [warn] `claude` CLI not found on PATH — falling back to mock draft.")
        return mock(person)

    base = [
        claude, "-p", user_msg,
        "--system-prompt", system,
        "--output-format", "json",
        "--model", cfg["run"].get("draft_model", "claude-sonnet-4-6"),
        "--max-turns", "1",
    ]

    def _run(args: list[str]) -> dict | None:
        try:
            proc = subprocess.run(args, capture_output=True, text=True, timeout=180)
        except (subprocess.TimeoutExpired, OSError) as e:
            print(f"  [warn] claude -p failed: {e}")
            return None
        if proc.returncode != 0:
            print(f"  [warn] claude -p exited {proc.returncode}: {proc.stderr.strip()[:200]}")
            return None
        try:
            envelope = json.loads(proc.stdout)
        except json.JSONDecodeError:
            envelope = {"result": proc.stdout}
        payload = envelope.get("structured_output")
        if isinstance(payload, dict):
            return payload
        text = envelope.get("result") if isinstance(envelope, dict) else proc.stdout
        try:
            return _extract_json(text or "")
        except (json.JSONDecodeError, ValueError):
            return None

    data = _run(base)
    if data is None:
        retry = list(base)
        retry[2] = user_msg + "\n\nReturn ONLY the JSON object specified. No other text."
        data = _run(retry)
    return coerce(data) if data else dict(low_conf)


# --- api backend: Anthropic SDK (optional fallback) -------------------------------------

def _draft_via_api(user_msg, cfg, person, system, coerce, low_conf, mock) -> dict:
    api_key = (os.getenv("ANTHROPIC_API_KEY") or "").strip() or None
    if not api_key:
        print("  [warn] draft_backend=api but ANTHROPIC_API_KEY is unset — using mock draft.")
        return mock(person)

    import anthropic

    client = anthropic.Anthropic(api_key=api_key)

    def _call(extra: str = "") -> str:
        resp = client.messages.create(
            model=cfg["run"].get("draft_model", "claude-sonnet-4-6"),
            max_tokens=1024,
            system=system + extra,
            messages=[{"role": "user", "content": user_msg}],
        )
        return resp.content[0].text

    try:
        return coerce(_extract_json(_call()))
    except (json.JSONDecodeError, ValueError):
        try:
            return coerce(_extract_json(_call("\n\nReturn ONLY the JSON object. No other text.")))
        except (json.JSONDecodeError, ValueError):
            return dict(low_conf)


def _mock_linkedin(person: dict) -> dict:
    first = person["name"].split()[0]
    return {
        "tier": "A",
        "angle": "Both lived the demo-to-production gap for LLM agents in customer stacks.",
        "comment": (
            f"\"Evals are the product\" — yes. I hit this exact wall building VisiMind: the agent "
            f"demoed clean, then fell over the second it touched real customer data. The eval "
            f"harness ended up being the actual moat. Curious whether you gate releases on evals "
            f"or treat them as a dashboard?"
        ),
        "dms": [
            (
                f"{first} — your take that evals are the product, not the model, is exactly what I "
                f"learned the hard way shipping VisiMind into messy customer stacks. I'm a "
                f"builder-who-sells looking hard at forward-deployed work at {person['company']}. "
                f"Worth 15 min to compare notes on what actually survives production?"
            ),
            (
                f"{first} — saw you're deep in the integration-survives-real-data problem. I've been "
                f"living that loop solo (built + deployed NadiaAI end-to-end). Would love 15 min on "
                f"how {person['company']} runs forward-deployed. No pitch — happy to just trade scar "
                f"tissue. Open to it?"
            ),
        ],
        "why": "Overlap: their 'evals are the product' post vs. Alejandro's VisiMind eval-harness experience.",
    }


def _mock_email(person: dict) -> dict:
    first = person["name"].split()[0]
    return {
        "tier": "A",
        "subject": f"{person['company']}'s forward-deployed gap",
        "body": (
            f"{first} — I've been watching {person['company']}'s push into real customer "
            f"deployments. I build AND sell: shipped VisiMind and NadiaAI end-to-end solo, the "
            f"whole forward-deployed loop from first call to production. The bet that the "
            f"integration layer is where deals are won or lost is exactly what I care about.\n\n"
            f"Worth 15 minutes to compare notes on what actually survives real data? Happy to send "
            f"a couple of specific thoughts first if that's easier.\n\n— Alejandro"
        ),
        "why": "Overlap: their company's forward-deployed motion vs. Alejandro's solo build+deploy track.",
    }
