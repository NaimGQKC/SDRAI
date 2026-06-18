"""digest.py — render the hit-list as a skimmable, mobile-friendly HTML email.

Two sections: LinkedIn (warm-up comment + DMs for right-level peers — the drafted part)
and an Email roster (senior people you write yourself, names + leads only). Nothing
auto-sends.
"""
from __future__ import annotations

from jinja2 import Environment, BaseLoader

_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
         color: #1a1a1a; line-height: 1.5; margin: 0; padding: 0; background: #f4f4f5; }
  .wrap { max-width: 640px; margin: 0 auto; padding: 16px; }
  .head { padding: 8px 0 16px; border-bottom: 2px solid #111; margin-bottom: 16px; }
  .head h1 { font-size: 20px; margin: 0 0 4px; }
  .head .sub { color: #555; font-size: 13px; }
  .sec { font-size: 13px; font-weight: 700; text-transform: uppercase; letter-spacing: .5px;
         color: #111; margin: 22px 0 10px; border-bottom: 1px solid #ddd; padding-bottom: 4px; }
  .card { background: #fff; border: 1px solid #e4e4e7; border-radius: 10px; padding: 16px;
          margin-bottom: 16px; }
  .who { font-size: 16px; font-weight: 700; margin: 0; }
  .meta { color: #555; font-size: 13px; margin: 2px 0 8px; }
  .tier { display: inline-block; font-size: 11px; font-weight: 700; padding: 2px 8px;
          border-radius: 999px; color: #fff; vertical-align: middle; margin-left: 6px; }
  .tier-A { background: #15803d; } .tier-B { background: #b45309; } .tier-C { background: #6b7280; }
  .why { color: #555; font-size: 13px; font-style: italic; margin: 0 0 10px; }
  .label { font-size: 11px; text-transform: uppercase; letter-spacing: .5px; color: #888;
           margin: 12px 0 4px; font-weight: 700; }
  .comment { background: #f0fdf4; border-left: 3px solid #15803d; padding: 8px 10px;
             border-radius: 4px; font-size: 14px; }
  ol.dms { margin: 4px 0 0; padding-left: 20px; }
  ol.dms li { background: #f8f8f8; border-radius: 4px; padding: 8px 10px; margin-bottom: 6px;
              font-size: 14px; }
  .row { background: #fff; border: 1px solid #e4e4e7; border-radius: 8px; padding: 10px 14px;
         margin-bottom: 8px; }
  .row .who { font-size: 14px; }
  a.li { color: #0a66c2; text-decoration: none; font-size: 13px; }
  .links { font-size: 12px; margin: 0 0 8px; }
  .links a { color: #444; text-decoration: none; margin-right: 10px; }
  .dossier { background: #fafafa; border: 1px solid #eee; border-radius: 6px; padding: 8px 10px;
             font-size: 12.5px; color: #333; white-space: pre-wrap; margin-top: 4px; }
  details > summary { cursor: pointer; font-size: 11px; text-transform: uppercase;
             letter-spacing: .5px; color: #888; font-weight: 700; margin: 12px 0 4px; }
  .src { font-size: 11px; color: #999; margin-top: 8px; word-break: break-all; }
  .foot { color: #999; font-size: 12px; text-align: center; padding: 8px 0 24px; }
</style>
</head>
<body>
<div class="wrap">
  <div class="head">
    <h1>Hit-list — {{ date }}</h1>
    <div class="sub">{{ linkedin_items|length }} LinkedIn drafts · {{ roster|length }} to email yourself.
      You send everything by hand — nothing is sent automatically.</div>
  </div>

  {% macro head(it) %}
    <p class="who">{{ it.person.name }}<span class="tier tier-{{ it.draft.tier }}">TIER {{ it.draft.tier }}</span></p>
    <div class="meta">{{ it.person.title }} · {{ it.person.company }}
      {% if it.person.location %}· {{ it.person.location }}{% endif %}
    </div>
    {% if it.person.linkedin or it.person.github or it.person.twitter %}
    <div class="links">
      {% if it.person.linkedin %}<a class="li" href="{{ it.person.linkedin }}">LinkedIn ↗</a>{% endif %}
      {% if it.person.github %}<a href="{{ it.person.github }}">GitHub ↗</a>{% endif %}
      {% if it.person.twitter %}<a href="{{ it.person.twitter }}">X ↗</a>{% endif %}
    </div>
    {% endif %}
    {% if it.draft.why %}<p class="why">{{ it.draft.why }}</p>{% endif %}
  {% endmacro %}

  {% macro tail(it) %}
    {% if it.research.content %}
    <details><summary>Dossier</summary><div class="dossier">{{ it.research.content }}</div></details>
    {% endif %}
    {% if it.research.citations %}
    <div class="src">Sources: {% for c in it.research.citations %}<a href="{{ c }}">{{ c }}</a>{% if not loop.last %} · {% endif %}{% endfor %}</div>
    {% endif %}
  {% endmacro %}

  {% if linkedin_items %}
  <div class="sec">LinkedIn — comment first, DM a day later</div>
  {% for it in linkedin_items %}
  <div class="card">
    {{ head(it) }}
    {% if it.draft.comment %}<div class="label">Warm-up comment</div><div class="comment">{{ it.draft.comment }}</div>{% endif %}
    {% if it.draft.dms %}<div class="label">DM options</div>
    <ol class="dms">{% for dm in it.draft.dms %}<li>{{ dm }}</li>{% endfor %}</ol>{% endif %}
    {{ tail(it) }}
  </div>
  {% endfor %}
  {% endif %}

  {% if roster %}
  <div class="sec">Email yourself — founders / C-suite / directors</div>
  <div class="sub" style="margin-bottom:10px;">Senior people. Write these with Perplexity + Claude
    and email by hand — the engine only surfaces them.</div>
  {% for p in roster %}
  <div class="row">
    <span class="who">{{ p.name }}</span>
    <div class="meta">{{ p.title }} · {{ p.company }}
      {% if p.location %}· {{ p.location }}{% endif %}
      {% if p.linkedin %}· <a class="li" href="{{ p.linkedin }}">LinkedIn ↗</a>{% endif %}
      {% if p.github %}· <a class="li" href="{{ p.github }}">GitHub ↗</a>{% endif %}
      {% if p.twitter %}· <a class="li" href="{{ p.twitter }}">X ↗</a>{% endif %}
    </div>
  </div>
  {% endfor %}
  {% endif %}

  {% if not linkedin_items and not roster %}
  <div class="card"><p>No new people today. (Everyone found was already in the tracker, or
    nothing verifiable surfaced.)</p></div>
  {% endif %}

  <div class="foot">Drafts for human review only. Nothing is sent automatically.</div>
</div>
</body>
</html>"""


def build_digest(items: list[dict], roster: list[dict], date: str) -> str:
    """items: drafted LinkedIn [{person,research,draft}], roster: senior person dicts."""
    env = Environment(loader=BaseLoader(), autoescape=True)
    return env.from_string(_TEMPLATE).render(linkedin_items=items, roster=roster, date=date)
