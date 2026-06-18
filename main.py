"""main.py — orchestration for the Hit-List Engine.

Loop: discover -> research -> match+draft -> digest -> (email + track).
A human does every LinkedIn action. The engine only researches and drafts.

Usage:
  python main.py --mocks            # default: full pipeline on sample data, $0
  python main.py --no-mocks         # real keys: PDL + Perplexity + Claude + Gmail
  python main.py --no-mocks --limit 3
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sys

import yaml
from dotenv import load_dotenv

from src import discover as discover_mod
from src import research as research_mod
from src import match_draft as match_mod
from src.digest import build_digest
from src.deliver import send_digest
from src import tracker

ROOT = os.path.dirname(os.path.abspath(__file__))


def load_config() -> dict:
    with open(os.path.join(ROOT, "config.yaml"), encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_profile() -> str:
    with open(os.path.join(ROOT, "profile", "alejandro_profile.md"), encoding="utf-8") as f:
        return f.read()


def parse_args(argv: list[str]) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Hit-List Engine")
    ap.add_argument("--mocks", dest="mocks", action="store_true", help="use mock data (default)")
    ap.add_argument("--no-mocks", dest="mocks", action="store_false", help="use real API keys")
    ap.add_argument("--limit", type=int, default=None, help="cap number of people queued")
    ap.add_argument("--open", dest="open_html", action="store_true",
                    help="open the digest in your browser after writing it")
    ap.set_defaults(mocks=True)
    return ap.parse_args(argv)


def run(use_mocks: bool, limit: int | None, open_html: bool = False) -> str:
    cfg = load_config()
    profile = load_profile()
    target_count = limit or cfg["run"]["people_per_day"]
    date = dt.date.today().isoformat()

    email_cap = cfg["run"].get("emails_per_day", 3)
    items: list[dict] = []

    def n(channel: str) -> int:
        return sum(1 for it in items if it["channel"] == channel)

    def consider(person: dict, channel: str = "linkedin") -> bool:
        """Research + draft one person on `channel`; append if usable. Returns True if added."""
        if tracker.already_seen(person.get("linkedin"), person["name"], person["company"]):
            print(f"  [skip] already seen: {person['name']}")
            return False

        intel = research_mod.research(person, cfg, use_mocks=use_mocks)
        draft = match_mod.match_draft(profile, person, intel["content"], cfg,
                                      use_mocks=use_mocks, channel=channel)

        # HARD CONSTRAINT #3: no fabrication. Drop low-confidence people.
        usable = draft.get("body") if channel == "email" else draft.get("dms")
        if draft["tier"] not in ("A", "B", "C") or not usable:
            print(f"  [drop] low_confidence: {person['name']}")
            return False

        if channel == "email":
            # The whole point of the email channel — find a real public address to send to.
            person["email"] = research_mod.find_email(person, cfg, use_mocks=use_mocks)
        elif not use_mocks and cfg["run"].get("reveal_emails"):
            person["email"] = discover_mod.enrich_email(person, use_mocks=use_mocks)

        items.append({"person": person, "research": intel, "draft": draft, "channel": channel})
        tag = "email" if channel == "email" else f"tier {draft['tier']}"
        print(f"  [{channel}] {person['name']} — {tag}")
        return True

    def process(queue: list[dict], warm: list[dict]) -> None:
        for person in queue:
            if n("linkedin") >= target_count:
                break
            consider(person, "linkedin")
        for person in warm:  # senior people -> cold email instead of the old warm-path list
            if n("email") >= email_cap:
                break
            consider(person, "email")

    source = cfg["run"].get("discovery_source", "seed")
    if source == "seed":
        # Discovery is a flat, pre-built list (you / Clay / an agent). No API, no credits.
        process(*discover_mod.discover_from_seed(cfg))
    else:
        # Company-by-company (perplexity | pdl), stopping once both channels are full.
        for target in cfg["targets"]:
            if n("linkedin") >= target_count and n("email") >= email_cap:
                break
            if source == "perplexity":
                queue, warm_path = discover_mod.discover_via_perplexity(target, cfg, use_mocks=use_mocks)
            else:
                queue, warm_path = discover_mod.discover(target, cfg, use_mocks=use_mocks)
            print(f"[discover] {target['company']}: {len(queue)} LinkedIn, {len(warm_path)} email-eligible")
            process(queue, warm_path)

    html = build_digest(items, date)
    out_path = os.path.join(ROOT, f"digest_{date}.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[digest] wrote {out_path} ({len(items)} people)")

    if not use_mocks:
        tracker.log_items(items, date)
        try:
            send_digest(html, date)
            print(f"[deliver] emailed digest to {os.getenv('DIGEST_TO') or os.getenv('GMAIL_ADDRESS')}")
        except Exception as e:  # noqa: BLE001 — email is best-effort; HTML is the source of truth
            print(f"[deliver] email skipped ({e}). Digest saved locally at {out_path}.")
    else:
        print("[mocks] skipped email + tracker writes. Open the HTML to preview.")

    if open_html:
        import webbrowser
        webbrowser.open(out_path)

    return out_path


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    args = parse_args(argv if argv is not None else sys.argv[1:])
    mode = "MOCK" if args.mocks else "LIVE"
    print(f"=== Hit-List Engine ({mode}) ===")
    run(use_mocks=args.mocks, limit=args.limit, open_html=args.open_html)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
