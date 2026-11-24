"""`kyma see` -- the same findings, in a room someone would want to sit in.

The terminal report is correct and cold. This page is the care: the same
evidence, laid out so the eye lands on the right thing first.

Rules that keep it honest:

  * Zero network. No CDN font, no icon set, no analytics, no remote anything.
    A report about what leaves your machine that itself phones home would
    deserve to be laughed at. The page references no external resource.
  * Everything from the user's disk is escaped. A logged command can contain
    `<script>`; an agent testing an XSS payload logs exactly that payload.
  * No manufactured feeling. The first version painted the hours between 1am
    and 6am in the page's only accent colour on every machine. On a machine
    whose agents work afternoons, that put the emphasis on the five quietest
    hours of the day, and the clock argued against its own caption. Night is
    emphasised now only when it is actually there.
"""

from __future__ import annotations

import datetime as _dt
import html
import math
import os
import re
import webbrowser

from . import HOME, ensure_home, index, render, signals, sources

OUT = os.path.join(HOME, "report.html")

NIGHT = range(1, 6)                 # 1am up to 6am, local time

CSS = """
*,*::before,*::after{box-sizing:border-box}
:root{--paper:#f7f4ef;--ink:#17161a;--soft:#6d6a73;--line:#e0dbd2;--card:#fffefb;
  --night:#b4531f;--code:#efe8dd}
@media (prefers-color-scheme:dark){:root{--paper:#15141a;--ink:#f0ede8;--soft:#948fa0;
  --line:#2e2b37;--card:#1c1b23;--night:#e8915a;--code:#2a2631}}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--paper);color:var(--ink);
  font:16px/1.65 ui-sans-serif,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  -webkit-font-smoothing:antialiased}
.wrap{max-width:46rem;margin:0 auto;padding:clamp(2.5rem,7vw,6rem) 1.5rem 6rem}
.meta{font-size:.78rem;letter-spacing:.09em;text-transform:uppercase;color:var(--soft)}
h1{font:400 clamp(1.9rem,5.2vw,2.9rem)/1.2 ui-serif,Georgia,"Times New Roman",serif;
  margin:.9rem 0 0;letter-spacing:-.015em;text-wrap:balance}
h1 b{font-weight:600;font-variant-numeric:tabular-nums}
h2{font-family:inherit;font-weight:500;font-size:.8rem;line-height:1.4;letter-spacing:.11em;
  text-transform:uppercase;color:var(--soft);margin:4rem 0 1.25rem;padding-bottom:.6rem;
  border-bottom:1px solid var(--line)}
.lede{color:var(--soft);margin:-.35rem 0 1.4rem}
.soft{color:var(--soft)}
.clock{display:flex;gap:clamp(1.5rem,5vw,3rem);align-items:center}
.dial{width:min(100%,280px);height:auto;flex:0 0 auto}
.dial text{font:10.5px ui-monospace,SFMono-Regular,Menlo,monospace;fill:var(--soft)}
.legend{flex:1 1 14rem}
.legend p{margin:.55rem 0 0}
.big{font:600 2.6rem/1 ui-serif,Georgia,serif;letter-spacing:-.02em;font-variant-numeric:tabular-nums}
.big.night{color:var(--night)}
@media (max-width:40rem){.clock{flex-direction:column;text-align:center}}
.lead{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:1.6rem}
.lead .n{font:600 3.5rem/1 ui-serif,Georgia,serif;letter-spacing:-.025em;font-variant-numeric:tabular-nums}
.lead .what{font-size:1.25rem;line-height:1.4;margin:.6rem 0 0}
.lead pre{font-size:14px}
.rows{margin:1.75rem 0 0;border-bottom:1px solid var(--line)}
.row{display:grid;grid-template-columns:4.5rem 1fr;column-gap:1.25rem;
  border-top:1px solid var(--line);padding:1.05rem 0}
.row .n{font:600 1.6rem/1.15 ui-serif,Georgia,serif;text-align:right;font-variant-numeric:tabular-nums}
.row .what{margin:.1rem 0 0}
.q{margin:.85rem 0 0}
.t{display:block;font-size:.78rem;color:var(--soft);margin:0 0 .3rem;font-variant-numeric:tabular-nums}
.t.night{color:var(--night)}
pre{margin:0;padding:.65rem .85rem;background:var(--code);border-radius:7px;
  font:12.5px/1.6 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;color:var(--ink);
  white-space:pre-wrap;overflow-wrap:anywhere}
.also{display:flex;flex-wrap:wrap;column-gap:1.1rem;row-gap:.15rem;margin:0;
  color:var(--soft);font-size:.92rem;line-height:1.9}
.also span{white-space:nowrap}
.next{margin:4rem 0 0;padding:1.5rem;border:1px solid var(--line);border-radius:14px;background:var(--card)}
.next p{margin:0 0 1rem;max-width:32rem}
.next p:last-child{margin:0}
code.cmd{display:inline-block;max-width:100%;overflow-x:auto;vertical-align:middle;white-space:nowrap;
  background:var(--code);border-radius:6px;padding:.35rem .6rem;
  font:13px/1.4 ui-monospace,SFMono-Regular,Menlo,monospace;-webkit-user-select:all;user-select:all}
footer{margin:4rem 0 0;padding-top:1.5rem;border-top:1px solid var(--line);color:var(--soft);font-size:.84rem}
@media print{body{background:#fff}.lead,.row,.next{break-inside:avoid}}
"""

_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f�]")


def _esc(text) -> str:
    return html.escape(_CONTROL.sub("", str(text)), quote=True)


def _local(ts: str):
    try:
        return _dt.datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone()
    except (ValueError, TypeError, OSError, AttributeError):
        return None


def _stamp(d) -> str:
    return f"{d:%a} {d.day} {d:%b}, {d.hour % 12 or 12}:{d:%M} {'am' if d.hour < 12 else 'pm'}"


def _hour(h: int) -> str:
    return f"{h % 12 or 12}{'am' if h < 12 else 'pm'}"


def _pt(r: float, frac: float, c: float = 120.0):
    a = frac * 2 * math.pi - math.pi / 2          # midnight at the top, clockwise
    return c + r * math.cos(a), c + r * math.sin(a)


def _dial(counts: list, night_on: bool, label: str) -> str:
    peak = max(counts) or 1
    inner, span = 46.0, 52.0
    out = ['<circle cx="120" cy="120" r="40" fill="none" stroke="var(--line)" stroke-width="1"/>']
    if night_on:
        x1, y1 = _pt(40, 1 / 24)
        x2, y2 = _pt(40, 6 / 24)
        out.append(f'<path d="M{x1:.1f} {y1:.1f} A40 40 0 0 1 {x2:.1f} {y2:.1f}" fill="none" '
                   f'stroke="var(--night)" stroke-width="2.5" stroke-linecap="round"/>')
    for h, c in enumerate(counts):
        frac = (h + 0.5) / 24          # each bar sits in the middle of its hour
        if c:
            end = inner + span * (c / peak)
            lit = night_on and h in NIGHT
            colour, op = ("var(--night)", ".95") if lit else ("var(--ink)", ".5")
        else:
            end, colour, op = inner + 2.0, "var(--soft)", ".35"   # nothing happened: a tick, not a mark
        x1, y1 = _pt(inner, frac)
        x2, y2 = _pt(end, frac)
        out.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{colour}" '
                   f'stroke-opacity="{op}" stroke-width="5.4" stroke-linecap="round"/>')
    for h, txt in ((0, "12a"), (6, "6a"), (12, "12p"), (18, "6p")):
        x, y = _pt(29, h / 24)
        out.append(f'<text x="{x:.1f}" y="{y + 3.6:.1f}" text-anchor="middle">{txt}</text>')
    return (f'<svg class="dial" viewBox="0 0 240 240" role="img" aria-label="{_esc(label)}">'
            + "".join(out) + "</svg>")


def _best(examples: list, limit: int = 2) -> list:
    """Clean examples only, with their time. A bad quote costs more than none."""
    out = []
    for e in sorted(examples, key=lambda e: -e[0]):
        if e[0] < 0:
            break
        out.append((e[1], e[2] if len(e) > 2 else ""))
        if len(out) >= limit:
            break
    return out


def _findings(data: dict):
    """The terminal's own selection, so the page and the terminal never disagree."""
    from . import scan
    rows, promoted = scan.select(data)
    return [(sid, n, [(e[1], e[2] if len(e) > 2 else "") for e in ex]) for sid, n, ex in rows], promoted


def _quotes(shown: list) -> str:
    out = []
    for text, ts in shown:
        d = _local(ts)
        when = ""
        if d:
            cls = "t night" if d.hour in NIGHT else "t"
            when = f'<time class="{cls}" datetime="{_esc(d.isoformat())}">{_esc(_stamp(d))}</time>'
        out.append(f'<div class="q">{when}<pre>{_esc(text)}</pre></div>')
    return "".join(out)


def build(data: dict, path: str = OUT) -> str:
    from . import scan
    hours = data.get("hours", {})
    counts = [int(hours.get(str(h), hours.get(h, 0)) or 0) for h in range(24)]
    total = data.get("actions", 0)
    night = sum(counts[h] for h in NIGHT)
    night_on = night >= 25 and total and night / total >= 0.02
    busiest = max(range(24), key=lambda h: counts[h]) if any(counts) else None
    rows, _promoted = _findings(data)

    agents = {"claude": "Claude Code", "codex": "Codex"}
    seen = [agents.get(a, a) for a in sorted(data.get("agents", {}) or {})]
    files = data.get("files", 0)
    scope = f"{files:,} {render.plural(files, 'session')}"
    if data.get("files_found", 0) > files:
        scope = f"{files:,} of {data['files_found']:,} sessions"
    since = render.when(data.get("first_ts", ""))
    meta = " &nbsp;·&nbsp; ".join(_esc(b) for b in [" · ".join(seen) or "your agents", scope]
                                   + ([f"since {since}"] if since else []))

    p = ['<!doctype html><html lang="en"><head><meta charset="utf-8">',
         '<meta name="viewport" content="width=device-width,initial-scale=1">',
         f"<title>What your agents tried</title><style>{CSS}</style></head><body>",
         f'<div class="wrap"><div class="meta">{meta}</div>',
         "<h1>" + (f"In your last {files:,} sessions, your agents made <b>{total:,}</b> tool calls."
                   if data.get("files_found", 0) > files else
                   f"Your agents have made <b>{total:,}</b> tool calls on this machine.") + "</h1>"]

    if busiest is not None:
        if night_on:
            label = (f"Tool calls by hour of day. {night:,} between 1am and 6am. "
                     f"Busiest at {_hour(busiest)}.")
            legend = (f'<div class="big night">{night:,}</div>'
                      f"<p>tool calls between 1am and 6am, your time.</p>"
                      f'<p class="soft">{night / total:.0%} of everything. '
                      f"Busiest at {_hour(busiest)}.</p>")
        else:
            label = f"Tool calls by hour of day. Busiest at {_hour(busiest)}."
            legend = (f'<div class="big">{_hour(busiest)}</div>'
                      f"<p>is when your agents are busiest.</p>"
                      f'<p class="soft">Between 1am and 6am: {night:,} '
                      f"{render.plural(night, 'call')}.</p>")
        p.append(f'<h2>When</h2><div class="clock">{_dial(counts, night_on, label)}'
                 f'<div class="legend">{legend}</div></div>')

    p.append("<h2>Attempted actions</h2>")
    if rows:
        sid, count, shown = rows[0]
        p.append(f'<div class="lead"><div class="n">{count:,}</div>'
                 f'<p class="what">{_esc(signals.BY_ID[sid][0])}</p>{_quotes(shown)}</div>')
        if rows[1:]:
            p.append('<div class="rows">')
            for sid, count, shown in rows[1:]:
                p.append(f'<div class="row"><div class="n">{count:,}</div><div>'
                         f'<p class="what">{_esc(signals.BY_ID[sid][0])}</p>{_quotes(shown)}</div></div>')
            p.append("</div>")
    else:
        p.append('<p class="lede">No recorded attempts matched these categories.</p>')

    shown_ids = {r[0] for r in rows}
    also = sorted(((data["hits"][s]["n"], t) for s, t in scan.ALSO.items()
                   if data.get("hits", {}).get(s, {}).get("n") and s not in shown_ids), reverse=True)
    if also:
        p.append('<h2>Also</h2><p class="also">'
                 + " ".join(f"<span>{c:,} {_esc(t)}</span>" for c, t in also[:7]) + "</p>")

    p.append('<div class="next"><p>Test a rule against these attempts:</p><p><code class="cmd">kyma try "never read my .env files"'
             '</code></p><p>That replays the rule against this same history, so you see what it '
             'would have stopped before you install anything. Then <code class="cmd">kyma on</code> '
             "checks each Claude Code tool call before it runs.</p></div>")

    now = _dt.datetime.now()
    p.append(f"<footer>Built {_esc(_stamp(now))} from the logs on this disk. This page loads nothing "
             "remote and sends nothing anywhere. kyma keeps masked excerpts in ~/.kyma; deleting that "
             "folder removes them.</footer></div></body></html>")

    if os.path.dirname(path) == HOME:
        ensure_home()
    else:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    # Atomic: an interrupted write never leaves half a page, and the new file
    # takes the 0600 mode the CLI sets, which an in-place rewrite would not.
    # A fresh temp file (mkstemp: never an existing name, never through a link), then one rename.
    from . import state_write
    state_write(path, "".join(p))
    return path


def run(since_days=None, agents=("claude", "codex"), limit=index.DEFAULT_LIMIT, open_it=True) -> int:
    found = sources.available()
    live = tuple(a for a in agents if found.get(a))
    if not live:
        from . import scan
        render.out(scan.NOTHING)
        return 1
    render.out()
    data = index.build(since_days=since_days, agents=live, limit=limit,
                       progress=lambda d, t: render.progress(d, t, f"reading {t:,} session logs"))
    render.clear_progress()
    if not data.get("actions"):
        render.out(f"{render.PAD}No tool calls recorded yet.")
        render.out()
        return 1
    path = build(data)
    render.out(f"{render.PAD}{render.bold(render.n(data['actions']))} tool calls, in a page you can read:")
    render.out()
    render.out(f"{render.PAD}{render.PAD}{path}")
    render.out()
    if open_it:
        try:
            webbrowser.open("file://" + path)
        except Exception:
            pass
    return 0
