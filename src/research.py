"""research.py — Perplexity Sonar -> recent intel per person.

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
    "Research {name}, {title} at {company}. Return, with sources: recent public "
    "posts/talks/interviews (last 3 months, quote sparingly), career path and any "
    "non-linear jumps, and the company's latest funding/launches/hiring. Be specific "
    "and recent. If you cannot find solid, recent, person-specific information, say so "
    "explicitly rather than padding with generics."
)


def research(person: dict, cfg: dict, use_mocks: bool = True) -> dict:
    """Return {'content': str, 'citations': [str, ...]} of fresh intel on one person."""
    api_key = os.getenv("PERPLEXITY_API_KEY")
    if use_mocks or not api_key:
        return _mock_research(person)

    prompt = _PROMPT.format(
        name=person["name"], title=person["title"], company=person["company"]
    )
    body = {
        "model": cfg["run"]["research_model"],
        "messages": [
            {"role": "system", "content": "You are a precise research assistant. Cite sources."},
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
    return {
        "content": (
            f"{name} ({person['title']} at {company}) recently posted about the messy reality of "
            f"deploying LLM agents into customer environments — specifically the gap between a demo "
            f"that works and an integration that survives real data. They wrote: \"evals are the "
            f"product, not the model.\" Career path: started as a backend engineer, moved into "
            f"solutions/forward-deployed work after leading a thorny on-prem migration. {company} "
            f"closed a Series A last quarter and is hiring across forward-deployed and solutions "
            f"engineering."
        ),
        "citations": [
            f"https://www.linkedin.com/in/{name.lower().replace(' ', '-')}",
            f"https://{company.lower().replace(' ', '')}.example/blog/agents-in-production",
        ],
    }
