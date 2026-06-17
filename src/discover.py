"""discover.py — Apollo People Search (API) -> right-level people.

HARD CONSTRAINT #1: discovery is Apollo API + open-web research ONLY. Never LinkedIn.
HARD CONSTRAINT #2: founders / C-suite / VPs never go to the cold queue -> warm_path.

API reference (fetched 2026-06): POST https://api.apollo.io/api/v1/mixed_people/search
  auth header: x-api-key
  body filters: q_organization_domains_list[], person_titles[], person_seniorities[], page, per_page
  response: {"people": [{id, name, first_name, last_name, title, linkedin_url,
                         organization: {name}, email|None}, ...]}
  NOTE: People Search does NOT return verified emails — that costs a separate enrichment
  credit (see enrich_email). We keep email=None here and only reveal post-match.
"""
from __future__ import annotations

import os
import requests

APOLLO_SEARCH_URL = "https://api.apollo.io/api/v1/mixed_people/search"
APOLLO_MATCH_URL = "https://api.apollo.io/api/v1/people/match"


def _is_excluded(title: str, exclude_titles: list[str]) -> bool:
    """True if the title contains any excluded seniority token (founder/ceo/vp/...)."""
    t = (title or "").lower()
    return any(bad.lower() in t for bad in exclude_titles)


def _normalize(person: dict) -> dict:
    """Map an Apollo person record to our flat contract."""
    name = person.get("name") or " ".join(
        p for p in [person.get("first_name"), person.get("last_name")] if p
    ).strip()
    org = person.get("organization") or {}
    return {
        "name": name or "(name withheld)",
        "title": person.get("title") or "",
        "company": org.get("name") or "",
        "linkedin": person.get("linkedin_url"),
        "email": person.get("email"),  # almost always None from search
        "_apollo_id": person.get("id"),
        "_first_name": person.get("first_name"),
        "_last_name": person.get("last_name"),
    }


def discover(target: dict, cfg: dict, use_mocks: bool = True) -> tuple[list[dict], list[dict]]:
    """Find right-level people at one target company.

    Returns (queue, warm_path):
      queue     -> [{name, title, company, linkedin, email|None}, ...] right-level only
      warm_path -> same shape, for founders/C-suite/VPs (intro-only list)
    """
    exclude = cfg["seniority_exclude_titles"]
    api_key = os.getenv("APOLLO_API_KEY")

    if use_mocks or not api_key:
        people = _mock_people(target)
    else:
        people = _search_apollo(target, cfg, api_key)

    queue, warm_path = [], []
    for raw in people:
        p = _normalize(raw)
        if not p["company"]:
            p["company"] = target["company"]
        (warm_path if _is_excluded(p["title"], exclude) else queue).append(p)
    return queue, warm_path


def _search_apollo(target: dict, cfg: dict, api_key: str) -> list[dict]:
    body = {
        "q_organization_domains_list": [target["domain"]],
        "person_titles": target["roles"],
        "person_seniorities": cfg["seniority_include"],
        "page": 1,
        "per_page": max(10, cfg["run"]["people_per_day"]),
    }
    headers = {
        "x-api-key": api_key,
        "Content-Type": "application/json",
        "Cache-Control": "no-cache",
    }
    resp = requests.post(APOLLO_SEARCH_URL, json=body, headers=headers, timeout=30)
    resp.raise_for_status()
    return resp.json().get("people", [])


def enrich_email(person: dict, use_mocks: bool = True) -> str | None:
    """Spend ONE Apollo enrichment credit to reveal a verified email.

    Call this ONLY for people who survive matching and you'll actually contact
    (free tier ~100 reveals/mo). Returns the email or None.
    """
    api_key = os.getenv("APOLLO_API_KEY")
    if use_mocks or not api_key:
        return person.get("email")

    body = {"reveal_personal_emails": True}
    if person.get("_apollo_id"):
        body["id"] = person["_apollo_id"]
    else:
        body["first_name"] = person.get("_first_name")
        body["last_name"] = person.get("_last_name")
        body["organization_name"] = person.get("company")

    headers = {"x-api-key": api_key, "Content-Type": "application/json", "Cache-Control": "no-cache"}
    try:
        resp = requests.post(APOLLO_MATCH_URL, json=body, headers=headers, timeout=30)
        resp.raise_for_status()
        return (resp.json().get("person") or {}).get("email")
    except requests.RequestException:
        return None


def _mock_people(target: dict) -> list[dict]:
    """Deterministic sample data so the full pipeline runs at $0."""
    company = target["company"]
    slug = company.lower().replace(" ", "")
    return [
        {
            "name": f"Maya Chen",
            "first_name": "Maya",
            "last_name": "Chen",
            "title": "Head of Forward Deployed Engineering",
            "organization": {"name": company},
            "linkedin_url": f"https://www.linkedin.com/in/maya-chen-{slug}",
            "email": None,
            "id": f"mock_{slug}_1",
        },
        {
            "name": f"Devin Park",
            "first_name": "Devin",
            "last_name": "Park",
            "title": "Senior Solutions Engineer",
            "organization": {"name": company},
            "linkedin_url": f"https://www.linkedin.com/in/devin-park-{slug}",
            "email": None,
            "id": f"mock_{slug}_2",
        },
        {
            # excluded -> should land in warm_path, not the queue
            "name": f"Sam Rivera",
            "first_name": "Sam",
            "last_name": "Rivera",
            "title": "Co-Founder & CEO",
            "organization": {"name": company},
            "linkedin_url": f"https://www.linkedin.com/in/sam-rivera-{slug}",
            "email": None,
            "id": f"mock_{slug}_3",
        },
    ]
