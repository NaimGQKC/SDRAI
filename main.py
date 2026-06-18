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

    items: list[dict] = []
    all_warm: list[dict] = []

    for target in cfg["targets"]:
        if len(items) >= target_count:
            break
        queue, warm_path = discover_mod.discover(target, cfg, use_mocks=use_mocks)
        all_warm.extend(warm_path)
        print(f"[discover] {target['company']}: {len(queue)} queue-eligible, "
              f"{len(warm_path)} warm-path")

        for person in queue:
            if len(items) >= target_count:
                break
            if tracker.already_seen(person.get("linkedin"), person["name"], person["company"]):
                print(f"  [skip] already seen: {person['name']}")
                continue

            intel = research_mod.research(person, cfg, use_mocks=use_mocks)
            draft = match_mod.match_draft(profile, person, intel["content"], cfg, use_mocks=use_mocks)

            # HARD CONSTRAINT #3: no fabrication. Drop low-confidence people from the queue.
            if draft["tier"] not in ("A", "B", "C") or not draft["dms"]:
                print(f"  [drop] low_confidence: {person['name']}")
                continue

            # Reveal an email only for survivors we'll actually contact (conserve PDL credits).
            if not use_mocks and cfg["run"].get("reveal_emails"):
                person["email"] = discover_mod.enrich_email(person, use_mocks=use_mocks)

            items.append({"person": person, "research": intel, "draft": draft})
            print(f"  [queue] {person['name']} — tier {draft['tier']}")

    html = build_digest(items, date)
    out_path = os.path.join(ROOT, f"digest_{date}.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[digest] wrote {out_path} ({len(items)} people)")

    if not use_mocks:
        tracker.log_warm_path(all_warm, date)
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
