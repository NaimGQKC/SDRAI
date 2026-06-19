"""discover.py — People Data Labs Person Search (API) -> right-level people.

HARD CONSTRAINT #1: discovery is the PDL API + open-web research ONLY. Never LinkedIn.
HARD CONSTRAINT #2: founders / C-suite / VPs never go to the cold queue -> warm_path.

We use People Data Labs instead of Apollo (Apollo's API is not usable on the free
tier). PDL exposes a clean REST person-search that fits this cron-driven pipeline.

API reference (docs.peopledatalabs.com/docs/person-search-api):
  POST https://api.peopledatalabs.com/v5/person/search
    auth header: X-Api-Key
    body: {"query": <Elasticsearch bool query>, "size": <1-100>, "dataset": "all"}
    response: {"status":200, "data":[{full_name, first_name, last_name, job_title,
               job_title_levels[], job_company_name, job_company_website, linkedin_url,
               work_email|None, emails[]|None, id}, ...], "total": N}
  NOTE: search costs one PDL credit per RECORD returned, so keep `size` small (the
  free tier is ~100 records/month). Verified emails are revealed post-match via the
  Enrich API (enrich_email) so we only spend on people we'll actually contact.
"""
from __future__ import annotations

import csv
import json
import os
import re
import time

import requests

PDL_SEARCH_URL = "https://api.peopledatalabs.com/v5/person/search"
PDL_ENRICH_URL = "https://api.peopledatalabs.com/v5/person/enrich"
PPLX_URL = "https://api.perplexity.ai/chat/completions"

# Seed file: a hand-/Clay-/agent-built list of people. The engine reads this instead of
# hitting PDL when run.discovery_source == "seed". Decouples discovery (flexible, free)
# from the valuable automated part (deep research + draft). Lives at the repo root.
SEED_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "people_seed.csv")

# PDL's free tier is tightly rate-limited; space calls out and retry once on 429.
_MIN_INTERVAL = 1.5
_last_call = 0.0


def _pdl_request(method: str, url: str, api_key: str, **kwargs) -> requests.Response:
    """Throttled PDL call with a single 429 backoff. Caller checks status_code."""
    global _last_call
    headers = {"X-Api-Key": api_key, "Content-Type": "application/json"}
    resp = None
    for attempt in range(3):
        wait = _MIN_INTERVAL - (time.monotonic() - _last_call)
        if wait > 0:
            time.sleep(wait)
        resp = requests.request(method, url, headers=headers, timeout=30, **kwargs)
        _last_call = time.monotonic()
        if resp.status_code != 429:
            return resp
        time.sleep(2 * (attempt + 1))  # 2s, 4s
    return resp


def _is_excluded(title: str, exclude_titles: list[str]) -> bool:
    """True if the title contains any excluded seniority token (founder/ceo/vp/...)."""
    t = (title or "").lower()
    return any(bad.lower() in t for bad in exclude_titles)


def _normalize_linkedin(url: str | None) -> str | None:
    """PDL returns linkedin like 'linkedin.com/in/foo' — make it a real URL."""
    if not url:
        return None
    url = url.strip()
    if url.startswith("http"):
        return url
    return f"https://www.{url}" if url.startswith("linkedin.com") else f"https://{url}"


def _to_url(u: str | None) -> str | None:
    """PDL profile fields (github_url, twitter_url) often omit the scheme."""
    if not u:
        return None
    u = u.strip()
    return u if u.startswith("http") else f"https://{u}"


def _prior_companies(person: dict) -> list[str]:
    """A few past roles ('Title at Company') from PDL experience, excluding the current one."""
    out, current = [], (person.get("job_company_name") or "").lower()
    for exp in person.get("experience") or []:
        comp = (exp.get("company") or {}).get("name") if isinstance(exp.get("company"), dict) else None
        title = (exp.get("title") or {}).get("name") if isinstance(exp.get("title"), dict) else None
        if not comp or comp.lower() == current:
            continue
        out.append(f"{title} at {comp}" if title else comp)
        if len(out) >= 3:
            break
    return out


def _education(person: dict) -> list[str]:
    out = []
    for ed in person.get("education") or []:
        school = (ed.get("school") or {}).get("name") if isinstance(ed.get("school"), dict) else None
        if school:
            out.append(school)
        if len(out) >= 2:
            break
    return out


def _first_email(person: dict) -> str | None:
    if person.get("work_email"):
        return person["work_email"]
    for e in person.get("emails") or []:
        addr = e.get("address") if isinstance(e, dict) else e
        if addr:
            return addr
    return None


def _normalize(person: dict) -> dict:
    """Map a PDL person record to our flat contract."""
    name = person.get("full_name") or " ".join(
        p for p in [person.get("first_name"), person.get("last_name")] if p
    ).strip()
    return {
        "name": name or "(name withheld)",
        "title": person.get("job_title") or "",
        "company": person.get("job_company_name") or "",
        "linkedin": _normalize_linkedin(person.get("linkedin_url")),
        "email": None,  # revealed post-match via enrich_email to conserve credits
        # Open-web seeds for deep, person-level research (never LinkedIn-scraped — these are
        # public handles PDL already resolved; research.py follows their own work from here).
        "github": _to_url(person.get("github_url")),
        "twitter": _to_url(person.get("twitter_url")),
        "location": person.get("location_name"),
        "prior": _prior_companies(person),
        "education": _education(person),
        "skills": (person.get("skills") or [])[:6],
        "interests": (person.get("interests") or [])[:6],
        "_pdl_id": person.get("id"),
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
    api_key = (os.getenv("PDL_API_KEY") or "").strip() or None

    if use_mocks or not api_key:
        people = _mock_people(target)
    else:
        people = _search_pdl(target, cfg, api_key)

    queue, warm_path = [], []
    for raw in people:
        p = _normalize(raw)
        if not p["company"]:
            p["company"] = target["company"]
        (warm_path if _is_excluded(p["title"], exclude) else queue).append(p)
    return queue, warm_path


def discover_from_seed(cfg: dict, seed_path: str | None = None) -> tuple[list[dict], list[dict]]:
    """Read people from people_seed.csv -> (queue, warm_path).

    The CSV needs at minimum `name` and `company`; everything else is optional and just
    gives the research step a head start. No API, no credits — you (or Clay, or an agent)
    fill the file, the engine does the deep work. Same warm-path rule as PDL discovery.
    """
    exclude = cfg["seniority_exclude_titles"]
    path = seed_path or SEED_PATH
    if not os.path.exists(path):
        print(f"[seed] no seed file at {path} — add people_seed.csv with name,company rows.")
        return [], []

    queue, warm_path = [], []
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            p = _person_from_seed(row)
            if not p:
                continue
            (warm_path if _is_excluded(p["title"], exclude) else queue).append(p)
    print(f"[seed] loaded {len(queue) + len(warm_path)} people from {os.path.basename(path)}")
    return queue, warm_path


_DISCOVER_SYSTEM = (
    "You are a precise sourcing researcher with live web access. Search hard across the "
    "company's team/about page, its GitHub organisation, LinkedIn, conference speaker lists, "
    "podcasts, blog author bylines and press.\n"
    "Only return people you can confirm are CURRENT employees of the named company from a "
    "public source. EXCLUDE advisors, investors, board members, former employees, and anyone "
    "you are not confident currently works there — it is better to return fewer, certain people "
    "than to guess. Never invent names, titles, or URLs."
)

_DISCOVER_USER = (
    "Find up to {n} people who currently work at {company} ({domain}) in engineering, product, "
    "solutions / forward-deployed, applied-AI or related technical roles. For each, give their "
    "full name, current title, and any public profile links you can find (LinkedIn, GitHub, X). "
    "Name real people from public sources — founders, engineers and product folks all count."
)

_DISCOVER_USER_LOOSE = (
    "Name real people who currently work at {company} ({domain}). For each give full name, "
    "current title, and any LinkedIn or GitHub link you can find. Search their website team "
    "page, GitHub organisation and LinkedIn. Even a name + role from one credible source counts."
)

# Structured-output schema so Sonar returns parseable JSON without us suppressing its search.
_PEOPLE_SCHEMA = {
    "type": "object",
    "properties": {
        "people": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "title": {"type": "string"},
                    "linkedin": {"type": "string"},
                    "github": {"type": "string"},
                    "twitter": {"type": "string"},
                },
                "required": ["name"],
            },
        }
    },
    "required": ["people"],
}


def discover_via_perplexity(target: dict, cfg: dict, use_mocks: bool = True) -> tuple[list[dict], list[dict]]:
    """Use Perplexity Sonar (web search) to FIND right-level people at one company.

    Returns (queue, warm_path), same contract as discover(). Sonar surfaces publicly-visible
    people (team pages, talks, GitHub, press) — exactly the ones you can personalise to. It is
    not a structured database, so coverage varies; the prompt forbids guessing and every name
    is re-verified by the deep research step + your own review before you send anything.
    """
    exclude = cfg["seniority_exclude_titles"]
    api_key = (os.getenv("PERPLEXITY_API_KEY") or "").strip() or None

    if use_mocks or not api_key:
        people = _mock_perplexity_people(target)
    else:
        people = _search_perplexity(target, cfg, api_key)

    queue, warm_path, seen = [], [], set()
    for raw in people:
        p = _person_from_pplx(raw, target)
        if not p or p["name"].lower() in seen:
            continue
        seen.add(p["name"].lower())
        (warm_path if _is_excluded(p["title"], exclude) else queue).append(p)
    return queue, warm_path


def _pplx_people_call(prompt: str, cfg: dict, api_key: str, use_schema: bool) -> str:
    """One Perplexity chat call; returns the message content (raises on HTTP error)."""
    body = {
        "model": cfg["run"]["research_model"],
        "messages": [
            {"role": "system", "content": _DISCOVER_SYSTEM},
            {"role": "user", "content": prompt},
        ],
    }
    if use_schema:
        body["response_format"] = {"type": "json_schema", "json_schema": {"schema": _PEOPLE_SCHEMA}}
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    resp = requests.post(PPLX_URL, json=body, headers=headers, timeout=90)
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def _search_perplexity(target: dict, cfg: dict, api_key: str) -> list[dict]:
    """Find people at one company. Tries a search-first structured query, then a looser
    fallback if the first comes back empty. Returns the first non-empty result."""
    n = max(8, int(cfg["run"].get("search_size") or cfg["run"]["people_per_day"]))
    company, domain = target["company"], target["domain"]
    attempts = [
        (_DISCOVER_USER.format(n=n, company=company, domain=domain), True),
        (_DISCOVER_USER_LOOSE.format(company=company, domain=domain), True),
        (_DISCOVER_USER_LOOSE.format(company=company, domain=domain), False),
    ]
    last_raw = ""
    for prompt, use_schema in attempts:
        try:
            content = _pplx_people_call(prompt, cfg, api_key, use_schema)
        except requests.RequestException as e:
            print(f"  [warn] Perplexity error for {company} (schema={use_schema}): {e}")
            continue
        people = _parse_pplx_people(content)
        if people:
            return people
        last_raw = content
    print(f"  [warn] no people found for {company}; last raw: {last_raw[:300]!r}")
    return []


def _parse_pplx_people(content: str) -> list[dict]:
    """Pull the people array out of Sonar's response, tolerating fences / stray prose."""
    cleaned = re.sub(r"^```(?:json)?|```$", "", content.strip(), flags=re.MULTILINE).strip()
    data = None
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}|\[.*\]", cleaned, re.DOTALL)
        if m:
            try:
                data = json.loads(m.group(0))
            except json.JSONDecodeError:
                return []
    if isinstance(data, dict):
        return data.get("people") or []
    return data if isinstance(data, list) else []


def _person_from_pplx(raw: dict, target: dict) -> dict | None:
    if not isinstance(raw, dict):
        return None
    name = (raw.get("name") or "").strip()
    if not name:
        return None
    parts = name.split()
    return {
        "name": name,
        "title": (raw.get("title") or "").strip(),
        "company": target["company"],
        "domain": target.get("domain"),
        "linkedin": _normalize_linkedin((raw.get("linkedin") or "").strip() or None),
        "github": _to_url((raw.get("github") or "").strip() or None),
        "twitter": _to_url((raw.get("twitter") or "").strip() or None),
        "email": None,
        "location": None,
        "prior": [],
        "education": [],
        "skills": [],
        "interests": [],
        "_pdl_id": None,
        "_first_name": parts[0] if parts else None,
        "_last_name": parts[-1] if len(parts) > 1 else None,
    }


def _mock_perplexity_people(target: dict) -> list[dict]:
    return [
        {"name": "Maya Chen", "title": "Senior Forward Deployed Engineer",
         "github": "github.com/mayachen", "twitter": "x.com/mayachen", "source": "https://example.com/talk"},
        {"name": "Devin Park", "title": "Solutions Engineer",
         "linkedin": "linkedin.com/in/devin-park", "source": "https://example.com/blog"},
        # excluded (founder) -> email roster, not LinkedIn-drafted
        {"name": "Sam Rivera", "title": "Co-Founder & CEO",
         "linkedin": "linkedin.com/in/sam-rivera", "source": "https://example.com/about"},
    ]


def _person_from_seed(row: dict) -> dict | None:
    """One CSV row -> our flat person contract. Requires name + company; rest optional."""
    name = (row.get("name") or "").strip()
    company = (row.get("company") or "").strip()
    if not name or not company:
        return None
    parts = name.split()
    return {
        "name": name,
        "title": (row.get("title") or "").strip(),
        "company": company,
        "domain": (row.get("domain") or "").strip() or None,
        "linkedin": _normalize_linkedin((row.get("linkedin") or "").strip() or None),
        "github": _to_url((row.get("github") or "").strip() or None),
        "twitter": _to_url((row.get("twitter") or "").strip() or None),
        "email": None,
        "location": (row.get("location") or "").strip() or None,
        "prior": [],
        "education": [],
        "skills": [],
        "interests": [],
        "_pdl_id": None,
        "_first_name": parts[0] if parts else None,
        "_last_name": parts[-1] if len(parts) > 1 else None,
    }


def _search_pdl(target: dict, cfg: dict, api_key: str) -> list[dict]:
    """One PDL Person Search per company. `size` is kept small to spare credits."""
    # Filter on the company website (most reliable) + seniority level, and require the
    # title to look like one of the target roles. role matches are analyzed text, so this
    # favours recall — the match/draft step + tier filter discard the noise downstream.
    must = [{"term": {"job_company_website": target["domain"].lower()}}]
    levels = cfg.get("seniority_include") or ["director", "manager", "senior"]
    must.append({"terms": {"job_title_levels": [lvl.lower() for lvl in levels]}})

    # Require at least one role keyword in the title. A nested bool with only `should`
    # clauses means "match >= 1" by default — PDL rejects an explicit minimum_should_match.
    role_should = [{"match": {"job_title": role}} for role in target.get("roles", [])]
    if role_should:
        must.append({"bool": {"should": role_should}})
    query: dict = {"bool": {"must": must}}

    size = cfg["run"].get("search_size") or cfg["run"]["people_per_day"]
    body = {"query": query, "size": max(1, min(int(size), 100)), "dataset": "all"}

    # One bad query (or a rate/credit limit) shouldn't kill the whole run — log PDL's own
    # error message (a 4xx costs no credits) and let the other companies proceed.
    try:
        resp = _pdl_request("POST", PDL_SEARCH_URL, api_key, json=body)
    except requests.RequestException as e:
        print(f"  [warn] PDL search failed for {target['company']}: {e}")
        return []
    if resp.status_code >= 400:
        print(f"  [warn] PDL search {resp.status_code} for {target['company']}: {resp.text[:500]}")
        return []
    return resp.json().get("data", [])


def enrich_email(person: dict, use_mocks: bool = True) -> str | None:
    """Spend ONE PDL enrichment credit to reveal a verified email.

    Call this ONLY for people who survive matching and you'll actually contact.
    Returns the email or None.
    """
    api_key = (os.getenv("PDL_API_KEY") or "").strip() or None
    if use_mocks or not api_key:
        return person.get("email")

    params: dict = {"min_likelihood": 6}
    if person.get("_pdl_id"):
        params["pdl_id"] = person["_pdl_id"]
    elif person.get("linkedin"):
        params["profile"] = person["linkedin"]
    else:
        params["first_name"] = person.get("_first_name")
        params["last_name"] = person.get("_last_name")
        params["company"] = person.get("company")

    try:
        resp = _pdl_request("GET", PDL_ENRICH_URL, api_key, params=params)
        resp.raise_for_status()
        return _first_email(resp.json().get("data") or {})
    except requests.RequestException:
        return None


def _mock_people(target: dict) -> list[dict]:
    """Deterministic sample data (PDL record shape) so the full pipeline runs at $0."""
    company = target["company"]
    slug = company.lower().replace(" ", "")
    return [
        {
            "full_name": "Maya Chen",
            "first_name": "Maya",
            "last_name": "Chen",
            "job_title": "Head of Forward Deployed Engineering",
            "job_title_levels": ["director"],
            "job_company_name": company,
            "job_company_website": target["domain"],
            "linkedin_url": f"linkedin.com/in/maya-chen-{slug}",
            "github_url": "github.com/mayachen",
            "twitter_url": "x.com/mayachen",
            "location_name": "berlin, germany",
            "experience": [
                {"company": {"name": "Palantir"}, "title": {"name": "Forward Deployed Engineer"}},
                {"company": {"name": "Stripe"}, "title": {"name": "Backend Engineer"}},
            ],
            "education": [{"school": {"name": "TU Munich"}}],
            "skills": ["python", "distributed systems", "llm evals", "on-prem deployment"],
            "interests": ["agents", "developer tooling"],
            "work_email": None,
            "id": f"mock_{slug}_1",
        },
        {
            "full_name": "Devin Park",
            "first_name": "Devin",
            "last_name": "Park",
            "job_title": "Senior Solutions Engineer",
            "job_title_levels": ["senior"],
            "job_company_name": company,
            "job_company_website": target["domain"],
            "linkedin_url": f"linkedin.com/in/devin-park-{slug}",
            "github_url": "github.com/devpark",
            "twitter_url": None,
            "location_name": "barcelona, spain",
            "experience": [
                {"company": {"name": "Typeform"}, "title": {"name": "Solutions Engineer"}},
            ],
            "education": [{"school": {"name": "UPC Barcelona"}}],
            "skills": ["typescript", "rag", "customer integrations"],
            "interests": ["retrieval", "open source"],
            "work_email": None,
            "id": f"mock_{slug}_2",
        },
        {
            # excluded -> should land in warm_path, not the queue
            "full_name": "Sam Rivera",
            "first_name": "Sam",
            "last_name": "Rivera",
            "job_title": "Co-Founder & CEO",
            "job_title_levels": ["cxo", "owner"],
            "job_company_name": company,
            "job_company_website": target["domain"],
            "linkedin_url": f"linkedin.com/in/sam-rivera-{slug}",
            "work_email": None,
            "id": f"mock_{slug}_3",
        },
    ]
