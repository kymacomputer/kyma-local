"""`kyma demo` must hold, then let through after the amendment is accepted, and say so.

Nothing else watches the demo end to end, and it is the first thing a person
with no history runs: if it calls itself broken, kyma looks broken."""
import _test_home  # isolate state before Kyma imports or subprocesses
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
KYMA = os.path.join(HERE, "..", "kyma")


def main() -> int:
    home = tempfile.mkdtemp(prefix="kyma-demo-home-")
    env = dict(os.environ, HOME=home, KYMA_HOME=os.path.join(home, ".kyma"), KYMA_ALLOW_TEMP_HOME="1", NO_COLOR="1")
    p = subprocess.run([sys.executable, KYMA, "demo"], capture_output=True, text=True, env=env, timeout=120)
    out = p.stdout + p.stderr
    checks = [
        ("exits 0", p.returncode == 0),
        ("the rule held first", "outbox/  empty" in out),
        ("the accepted exception let it through", "1 message to cofounder@example.com" in out),
        ("acceptance is shown as a person's step", "rules does at your terminal" in out),
        ("no claim that `kyma rules` was run", "$ kyma rules" not in out),
        ("no claim that an ask reached the agent", "Your agent was handed" not in out),
        ("never calls itself broken", "demo failed" not in out),
    ]
    bad = [n for n, ok in checks if not ok]
    for n, ok in checks:
        print(("ok    " if ok else "FAIL  ") + n)
    if bad:
        print(out[-1500:])
    print("demo: " + ("PASS" if not bad else f"{len(bad)} FAILURES"))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
