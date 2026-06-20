"""tracker.py — CSV log, dedup, follow-up flags.

tracker.csv columns: date,name,company,channel,linkedin,email,tier,status
  channel: linkedin | email
  status:  queued | commented | dm_sent | emailed | replied | dead

GH Actions is ephemeral — the workflow commits tracker.csv back to the repo after each
run so dedup survives across days.
"""
from __future__ import annotations

import csv
import os

TRACKER_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "tracker.csv")

_TRACKER_FIELDS = ["date", "name", "company", "channel", "linkedin", "email", "tier", "status"]


def _ensure(path: str, fields: list[str]) -> None:
    """Create the CSV with the right header. If an OLD header is present (e.g. from before
    the channel/email columns), reset to the current header — a shifted header silently
    breaks dedup under DictReader, and the stale rows can't be realigned reliably."""
    if os.path.exists(path):
        with open(path, newline="", encoding="utf-8") as f:
            current = (f.readline().strip() == ",".join(fields))
        if current:
            return
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
                "channel": it.get("channel", "linkedin"),
                "linkedin": p.get("linkedin") or "",
                "email": p.get("email") or "",
                "tier": d.get("tier", ""),
                "status": "queued",
            })


def log_roster(people: list[dict], date: str) -> None:
    """Log senior people (the email-yourself roster) so they're not re-listed tomorrow."""
    if not people:
        return
    _ensure(TRACKER_PATH, _TRACKER_FIELDS)
    with open(TRACKER_PATH, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=_TRACKER_FIELDS)
        for p in people:
            w.writerow({
                "date": date,
                "name": p["name"],
                "company": p["company"],
                "channel": "email",
                "linkedin": p.get("linkedin") or "",
                "email": p.get("email") or "",
                "tier": "",
                "status": "to_email",
            })
