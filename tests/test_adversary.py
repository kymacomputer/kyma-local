"""A blind adversary's corpus, kept: 173 ways to do what a starting rule forbids
without saying it plainly, 181 ordinary calls that must pass, and 9 controls.

Written by a reviewer who had never seen the gate's code, against the five
starter rules. Every attempt is only piped to `kyma hook`; nothing it names is
ever run. Each case gets a throwaway home with fake secrets.

Held means ask or deny. S16 is not counted: it defines a shell alias and uses
it in the same `-c` string, which no shell expands, so it cannot escape.
"""
import _test_home  # isolate state before Kyma imports or subprocesses
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "adversary"))

import cases_escape     # noqa: E402
import cases_precision  # noqa: E402
from runner import fresh_sandbox, run_steps  # noqa: E402

HELD = ("ask", "deny")


def main() -> int:
    bad = []
    ctx = fresh_sandbox("day-")
    over = []
    clear = 0
    for cid, label, desc, fn in cases_precision.cases():
        clear += label == "clear"
        res = run_steps(ctx, fn(ctx))
        if label == "clear" and any(r["decision"] in HELD for r in res):
            over.append(f"{cid} {desc}")
        bad += [f"{cid} anomaly {r['anomaly']}" for r in res if r["anomaly"]]
    shutil.rmtree(ctx.S, ignore_errors=True)
    held = total = 0
    escaped = []
    for cid, rule, desc, fn in cases_escape.cases():
        ctx = fresh_sandbox(cid + "-")
        res = run_steps(ctx, fn(ctx))
        shutil.rmtree(ctx.S, ignore_errors=True)
        if cid == "S16":
            continue
        out = all(r["decision"] == "allow" for r in res)
        if rule == "X":
            if out:
                bad.append(f"control {cid} {desc} was allowed")
            continue
        total += 1
        if out:
            escaped.append(f"{cid} {desc}")
        else:
            held += 1
    for e in escaped:
        print("ESCAPED   " + e)
    for o in over:
        print("OVERHELD  " + o)
    for b in bad:
        print("BROKEN    " + b)
    print(f"adversary: {held}/{total} escapes held, {len(over)} of {clear} ordinary calls held")
    # README and SECURITY.md quote these sizes: a corpus that shrinks must say so here first
    if (total, clear) != (173, 181):
        bad.append(f"corpus is {total} escapes and {clear} ordinary calls, not the 173 and 181 the README states")
    ok = not escaped and not over and not bad
    print("adversary: " + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
