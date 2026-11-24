"""Replay recorded tool calls through the hook, the way Claude Code hands them over.

By default the history is synthetic: the made-up developer of
scripts/example.py, written into a throwaway HOME, so the result is the same
on every machine and in CI and never reads anyone's real transcripts. Set
KYMA_REPLAY_REAL=1 to replay this machine's own ~/.claude logs instead,
which are the shapes the hook is handed in production. Under the five
default rules that `kyma on` installs:

    1. the hook never raises and never answers with anything but allow, ask or deny
    2. it holds something (the rules fire on real history) but not too much
       (a guard that interrupts a quarter of all work gets switched off)
    3. latency is reported, per decision, as measured here. Python start-up
       (about 50 ms) comes on top when the host runs the hook as a process.

It runs in a sandbox of its own and writes nothing to your ~/.kyma.
"""
import _test_home  # isolate state before Kyma imports or subprocesses

import io, json, os, shutil, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))

# The hook writes a decision log and a counter. Without this, every run of the
# suite appended thousands of synthetic decisions to the user's real
# ~/.kyma, and `kyma log` then showed enforcement that never happened. Set
# before importing kyma: the state directory is resolved at import.
STATE = tempfile.mkdtemp(prefix="kyma-test-state-")
os.environ["KYMA_HOME"] = STATE
REAL = os.environ.get("KYMA_REPLAY_REAL") == "1"
if REAL:
    # Explicit real-history mode reads the original Claude source only. The
    # shared bootstrap and STATE still confine every decision write.
    os.environ["CLAUDE_CONFIG_DIR"] = _test_home.ORIGINAL_CLAUDE_CONFIG_DIR
else:
    # sources resolves ~/.claude at import, so the synthetic HOME comes first
    FAKE_HOME = tempfile.mkdtemp(prefix="kyma-replay-home-")
    os.environ["HOME"] = FAKE_HOME
    os.environ.pop("CLAUDE_CONFIG_DIR", None)
    os.environ.pop("CODEX_HOME", None)
    sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
    import example  # noqa: E402  (only its history writer; nothing is rendered)
    example.write_history(FAKE_HOME)

from kyma import enforce, sources  # noqa: E402

RULES = enforce.TEMPLATE        # exactly what `kyma on` installs

LIMIT = int(os.environ.get("KYMA_REPLAY", "4000"))


def main() -> int:
    work = tempfile.mkdtemp(prefix="kyma-replay-")
    os.makedirs(os.path.join(work, ".kyma"))
    with open(os.path.join(work, ".kyma", "RULES.md"), "w") as fh:
        fh.write(RULES)
    os.chdir(work)

    payloads = []
    for a in sources.read_all(since_days=14 if REAL else 120, agents=("claude",)):
        inp = {"command": a.command} if a.command else (
            {"file_path": a.paths[0]} if a.paths else {})
        payloads.append((a.tool, inp))
        if len(payloads) >= LIMIT:
            break
    # Zero calls is a broken reader or a broken fixture, never a pass.
    assert payloads, ("replayed zero calls from " + ("this machine's logs" if REAL else "the synthetic history")
                      + ": the reader or the fixture is broken")

    counts = {"allow": 0, "ask": 0, "deny": 0}
    errors = []
    lat = []
    start = time.time()
    for tool, inp in payloads:
        out = io.StringIO()
        t0 = time.perf_counter()
        try:
            enforce.hook(io.StringIO(json.dumps(
                {"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": inp, "cwd": work})), out)
            lat.append(time.perf_counter() - t0)
            res = json.loads(out.getvalue())
        except Exception as exc:
            errors.append((tool, repr(exc)[:120]))
            continue
        spec = res.get("hookSpecificOutput") or {}
        verdict = spec.get("permissionDecision", "allow")
        if verdict not in counts:
            errors.append((tool, "bad verdict " + repr(verdict)))
            continue
        counts[verdict] += 1
    elapsed = time.time() - start

    print(f"replayed {len(payloads):,} tool calls from " + ("this machine's logs" if REAL else "a synthetic history"))
    print(f"  verdicts: {counts}")
    lat.sort()
    if lat:
        p50 = lat[len(lat) // 2] * 1000
        p99 = lat[min(len(lat) - 1, int(len(lat) * 0.99))] * 1000
        print(f"  latency:  {p50:.2f} ms median, {p99:.1f} ms p99 per decision (plus ~50 ms Python start-up per call)")
    print(f"  errors:   {len(errors)}")
    for tool, err in errors[:5]:
        print("   ", tool, err)

    assert not errors, errors[:5]
    assert counts["allow"] > 0, "nothing allowed: the guard would stop all work"
    assert counts["deny"] + counts["ask"] > 0, "nothing held: rules never fired on real history"
    held_rate = (counts["deny"] + counts["ask"]) / len(payloads)
    assert held_rate < 0.25, f"held {held_rate:.0%} of all calls -- rules are too broad"
    print("  held rate:", f"{held_rate:.1%}")
    assert enforce.HOME == STATE, "hook state escaped the test sandbox"
    shutil.rmtree(work, ignore_errors=True)
    shutil.rmtree(STATE, ignore_errors=True)
    if not REAL:
        shutil.rmtree(FAKE_HOME, ignore_errors=True)
    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
