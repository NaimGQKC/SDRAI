"""tracker.py — CSV log, dedup, follow-up flags.

tracker.csv columns: date,name,company,linkedin,tier,status
  status: queued | commented | dm_sent | replied | dead

GH Actions is ephemeral — the workflow commits tracker.csv back to the repo after each
run so dedup survives across days.
"""
from __future__ import annotations

import csv
import os

TRACKER_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "tracker.csv")
WARM_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "warm_path.csv")

_TRACKER_FIELDS = ["date", "name", "company", "linkedin", "tier", "status"]
_WARM_FIELDS = ["date", "name", "company", "linkedin", "title"]


def _ensure(path: str, fields: list[str]) -> None:
    if not os.path.exists(path):
        with open(path, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(fields)


def _seen_keys(path: str, col: str) -> set[str]:
    if not os.path.exists(path):
        return set()
    with open(path, newline="", encoding="utf-8") as f:
        return {(row.get(col) or "").strip().lower() for row in csv.DictReader(f) if row.get(col)}


def already_seen(linkedin: str | None, name: str = "", company: str = "") -> bool:
    """Dedup: True if this person is already logged (HARD CONSTRAINT #4).

    Matches on LinkedIn URL when available, else falls back to name+company.
    """
    if linkedin:
        return linkedin.strip().lower() in _seen_keys(TRACKER_PATH, "linkedin")
    if not os.path.exists(TRACKER_PATH):
        return False
    key = f"{name}|{company}".strip().lower()
    with open(TRACKER_PATH, newline="", encoding="utf-8") as f:
        return any(
            f"{r.get('name','')}|{r.get('company','')}".strip().lower() == key
            for r in csv.DictReader(f)
        )


def log_items(items: list[dict], date: str) -> None:
    """Append queued people to the tracker (status=queued)."""
    _ensure(TRACKER_PATH, _TRACKER_FIELDS)
    with open(TRACKER_PATH, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=_TRACKER_FIELDS)
        for it in items:
            p, d = it["person"], it["draft"]
            w.writerow({
                "date": date,
                "name": p["name"],
                "company": p["company"],
                "linkedin": p.get("linkedin") or "",
                "tier": d.get("tier", ""),
                "status": "queued",
            })


def log_warm_path(people: list[dict], date: str) -> None:
    """Append founders/C-suite/VPs to the intro-only warm-path list."""
    if not people:
        return
    _ensure(WARM_PATH, _WARM_FIELDS)
    seen = _seen_keys(WARM_PATH, "linkedin")
    with open(WARM_PATH, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=_WARM_FIELDS)
        for p in people:
            li = (p.get("linkedin") or "").strip()
            if li and li.lower() in seen:
                continue
            w.writerow({
                "date": date,
                "name": p["name"],
                "company": p["company"],
                "linkedin": li,
                "title": p["title"],
            })
