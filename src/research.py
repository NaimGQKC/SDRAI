"""research.py — Perplexity Sonar -> a deep, human-level dossier per person.

The point of this step is DEPTH about the human, not their job title. We seed the
search with the public handles PDL resolved (GitHub, X, past roles, schools) and ask
Sonar to follow THEIR OWN work — writing, talks, repos, podcasts, the opinions they
return to. That's what lets the drafter open on something that could only be said to
this one person. We never scrape LinkedIn; Sonar searches the open web.

POST https://api.perplexity.ai/chat/completions
  auth: Authorization: Bearer $PERPLEXITY_API_KEY
  model: sonar-pro
Response carries `choices[0].message.content` plus `citations` / `search_results`.
"""
from __future__ import annotations

import os
import requests

PPLX_URL = "https://api.perplexity.ai/chat/completions"

_PROMPT = (
    "Build a deep, human-level dossier on ONE person so an ambitious peer can reach out in a way "
    "that could ONLY be said to them. Prioritise what THEY create and argue about over their job "
    "title or what their company sells.\n\n"
    "Person: {name} — {title} at {company}{loc}.\n"
    "Seeds to mine FIRST (follow these to their actual work):\n{seeds}\n\n"
    "Dig for, and attach a source URL to every concrete claim:\n"
    "1. THEIR OWN WORK — blog posts/essays, conference talks or slides, GitHub repos & notable "
    "contributions, side projects, podcasts/interviews. Name the specific artifact and what's "
    "genuinely interesting in it.\n"
    "2. THEIR VIEWS — opinions they keep returning to, things they're frustrated by, technical "
    "hot takes, what they clearly care about. Quote sparingly and exactly.\n"
    "3. THEIR STORY — career path and non-linear jumps, what they did before this, where they're based.\n"
    "4. CONTEXT (brief) — only the company funding/launch facts that create a reason to reach out NOW.\n\n"
    "Rules: be specific and recent. ONE vivid, true, person-specific detail beats five generic ones. "
    "If you cannot find solid person-specific material, say so plainly — do NOT pad with generic "
    "company/role boilerplate. Never invent artifacts, quotes, or URLs."
)


def _seeds(person: dict) -> str:
    """Compact, open-web seeds for the dossier. Deliberately excludes LinkedIn."""
    bits = []
    if person.get("github"):
        bits.append(f"- GitHub: {person['github']}")
    if person.get("twitter"):
        bits.append(f"- X/Twitter: {person['twitter']}")
    if person.get("prior"):
        bits.append("- Previously: " + "; ".join(person["prior"]))
    if person.get("education"):
        bits.append("- Studied at: " + ", ".join(person["education"]))
    if person.get("skills"):
        bits.append("- Listed skills: " + ", ".join(person["skills"]))
    if person.get("interests"):
        bits.append("- Interests: " + ", ".join(person["interests"]))
    return "\n".join(bits) if bits else "- none on file — search the open web by name + company."


def research(person: dict, cfg: dict, use_mocks: bool = True) -> dict:
    """Return {'content': str, 'citations': [str, ...]} — a person-level dossier."""
    api_key = (os.getenv("PERPLEXITY_API_KEY") or "").strip() or None
    if use_mocks or not api_key:
        return _mock_research(person)

    loc = f", based in {person['location']}" if person.get("location") else ""
    prompt = _PROMPT.format(
        name=person["name"], title=person["title"], company=person["company"],
        loc=loc, seeds=_seeds(person),
    )
    body = {
        "model": cfg["run"]["research_model"],
        "messages": [
            {"role": "system", "content": "You are a precise research assistant. Cite a source for every claim."},
            {"role": "user", "content": prompt},
        ],
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    try:
        resp = requests.post(PPLX_URL, json=body, headers=headers, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        citations = data.get("citations") or [
            r.get("url") for r in data.get("search_results", []) if r.get("url")
        ]
        return {"content": content, "citations": citations}
    except (requests.RequestException, KeyError, IndexError) as e:
        return {"content": f"[research unavailable: {e}]", "citations": []}


def _mock_research(person: dict) -> dict:
    name = person["name"]
    company = person["company"]
    gh = person.get("github") or "https://github.com/example"
    prior = (person.get("prior") or ["a prior role"])[0]
    return {
        "content": (
            f"THEIR OWN WORK — {name} maintains an open-source eval harness on GitHub ({gh}) and gave "
            f"a talk \"Demos lie, evals don't\" at a recent AI-engineering meetup, walking through how a "
            f"forward-deployed integration survives messy customer data. They also write a small blog on "
            f"shipping LLM agents into regulated environments.\n\n"
            f"THEIR VIEWS — recurring theme: \"evals are the product, not the model.\" Visibly frustrated "
            f"by demo-driven roadmaps that ignore the integration layer.\n\n"
            f"THEIR STORY — backend engineer ({prior}) who moved into forward-deployed/solutions work "
            f"after leading a thorny on-prem migration. Hands-on, not a slideware person.\n\n"
            f"CONTEXT — {company} closed a Series A last quarter and is hiring across forward-deployed "
            f"and solutions engineering."
        ),
        "citations": [
            gh,
            f"https://{company.lower().replace(' ', '')}.example/blog/agents-in-production",
        ],
    }
