"""Output as the product.

The brief for this file was: the reassurance has to arrive as a feeling, not
as a sentence claiming to be reassuring. So there is no copy here that tells
anyone how to feel. No warning triangles, no "⚠ RISK DETECTED", no severity
badges, no colour shouting. What produces the feeling is sequence and
restraint:

  1. a large true number about the reader's own machine
  2. the date it started, so the scale has depth in time
  3. the short list they have never looked at
  4. a few of their agents' own commands, secrets masked
  5. one thing to do next, and nothing else

Step 4 is the one that lands. A statistic is an argument; your own command,
quoted back to you, is not arguable. Everything else here exists to set it up
and then get out of the way.
"""

from __future__ import annotations

import datetime as _dt
import os
import shutil
import shlex
import sys

_TTY = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None
DIM = "\033[2m" if _TTY else ""
BOLD = "\033[1m" if _TTY else ""
OFF = "\033[0m" if _TTY else ""
PAD = "  "


def width() -> int:
    return min(shutil.get_terminal_size((80, 24)).columns, 92)


def out(line: str = "") -> None:
    try:
        print(line)
    except UnicodeEncodeError:
        enc = getattr(sys.stdout, "encoding", None) or "ascii"
        print(line.encode(enc, "replace").decode(enc, "replace"))


def clean(text) -> str:
    """Anything that came from a log is printed through this."""
    from .signals import clean as _clean
    return _clean(text)


def dim(text: str) -> str:
    return f"{DIM}{text}{OFF}"


def bold(text: str) -> str:
    return f"{BOLD}{text}{OFF}"


def n(value: int) -> str:
    return f"{value:,}"


def when(ts: str) -> str:
    """'2026-03-29T16:21:27Z' -> '29 March 2026'."""
    if not ts:
        return ""
    try:
        d = _dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return ts[:10]
    stamp = d.strftime("%-d %B %Y") if os.name != "nt" else d.strftime("%d %B %Y")
    return stamp


def headline(rows: list) -> None:
    """Right-aligned numbers, dim labels. The number is the sentence."""
    if not rows:
        return
    pad = max(len(n(v)) for v, _ in rows)
    for value, label in rows:
        out(f"{PAD}{PAD}{bold(n(value).rjust(pad))}  {dim(label)}")


def quote(lines: list, limit: int = 3) -> None:
    """Their own commands, verbatim, indented, nothing added."""
    w = width() - 8
    seen, uniq = set(), []
    for line in lines:
        key = line[:60]
        if key in seen:
            continue
        seen.add(key)
        uniq.append(line)
    lines = uniq
    for line in lines[:limit]:
        line = clean(line)
        text = line if len(line) <= w else line[: w - 1] + "…"
        out(f"{PAD}{PAD}{dim(text)}")


def prog(rest: str = "", *, absolute: bool = False) -> str:
    """How to run kyma again, the way it was run this time: ./kyma, kyma, or
    the uvx line. Telling a person to type `kyma demo` when kyma is not on
    their PATH is a dead end on the first screen."""
    import os as _os
    argv0 = sys.argv[0] if sys.argv else "kyma"
    real = _os.path.realpath(argv0)
    if any(m in real for m in ("/.cache/uv/", "/archive-v0/", "/uv/builds-v0/")):
        base = "uvx --from git+https://github.com/kymacomputer/kyma-local kyma"
    elif _os.path.basename(argv0) == "kyma" and ("/" in argv0) and not _os.path.dirname(real).endswith("/bin"):
        base = shlex.quote(real) if absolute else shlex.quote(argv0) if argv0.startswith((".", "/")) else "./kyma"
        if not absolute and base.startswith("/") and _os.path.dirname(real) == _os.getcwd():
            base = "./kyma"
    elif argv0.endswith("__main__.py") or argv0 == "-m":
        base = "python3 -m kyma"
    else:
        base = "kyma"
    return f"{base} {rest}".strip()


def next_step(command: str, effect: str) -> None:
    out()
    out(f"{PAD}{bold(command)}   {dim(effect)}")
    out()


def progress(done: int, total: int, label: str) -> None:
    if not _TTY:
        return
    pct = int(done * 100 / max(total, 1))
    bar_w = 24
    filled = int(bar_w * done / max(total, 1))
    bar = "█" * filled + "░" * (bar_w - filled)
    sys.stdout.write(f"\r{PAD}{dim(bar)} {pct:3d}%  {dim(label)}   ")
    sys.stdout.flush()


def clear_progress() -> None:
    if _TTY:
        sys.stdout.write("\r" + " " * (width() - 1) + "\r")
        sys.stdout.flush()


def fit(text: str, indent: int = 0) -> str:
    """Truncate to the terminal, with a mark so the reader knows it was cut."""
    room = max(24, width() - 4 - indent)
    text = clean(text)
    return text if len(text) <= room else text[: room - 1] + "…"


def plural(count: int, one: str, many: str | None = None) -> str:
    return one if count == 1 else (many or one + "s")
