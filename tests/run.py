"""Run every tests/test_*.py, each in a fresh, empty HOME and KYMA_HOME.

A suite that passes only because of where HOME happens to live, or because
of what a real ~/.claude holds, is not passing. So each file gets its own
throwaway HOME (outside /tmp, see _homes), no
CLAUDE_CONFIG_DIR or CODEX_HOME, and a nonzero exit on any failure.

    python3 tests/run.py            all of them
    python3 tests/run.py gate rules only test_gate.py and test_rules.py
"""
import glob
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))


def _homes() -> str:
    """Where the throwaway HOMEs go. Not under /tmp: the starter rules let a
    delete in /tmp through, so a HOME there made `rm -rf ~/Documents` look
    harmless, and the suite failed wherever TMPDIR is unset (Linux CI)."""
    base = os.environ.get("KYMA_TEST_HOMES")
    if not base:
        tmpish = lambda p: os.path.realpath(p).startswith(("/tmp", "/private/tmp", "/var/tmp", "/dev/shm"))
        for cand in (tempfile.gettempdir(), os.path.join(os.path.expanduser("~"), ".cache", "kyma-test-homes"),
                     os.path.join(os.path.dirname(HERE), ".test-homes")):
            if not tmpish(cand):
                base = cand
                break
        else:
            raise SystemExit("every place for test homes is under /tmp; set KYMA_TEST_HOMES to another folder")
    os.makedirs(base, exist_ok=True)
    return base


# The suites get the environment a clean shell would, not yours: your shell
# may hold API keys, and nothing under test needs them.
_PASS_ENV = ("PATH", "LANG", "LC_ALL", "LC_CTYPE", "TERM", "TZ", "TMPDIR", "SYSTEMROOT", "PYTHONIOENCODING")


def main(argv) -> int:
    files = sorted(glob.glob(os.path.join(HERE, "test_*.py")))
    if argv:
        files = [f for f in files if any(os.path.basename(f) in (f"test_{a}.py", a) for a in argv)]
    failed = []
    for f in files:
        home = tempfile.mkdtemp(prefix="kyma-run-home-", dir=_homes())
        state = tempfile.mkdtemp(prefix="kyma-run-state-", dir=_homes())
        env = {k: v for k, v in os.environ.items() if k in _PASS_ENV}
        env.update(HOME=home, KYMA_HOME=state, KYMA_ALLOW_TEMP_HOME="1", KYMA_NO_KEYCHAIN="1", PYTHONDONTWRITEBYTECODE="1")
        t0 = time.time()
        try:
            p = subprocess.run([sys.executable, f], cwd=os.path.dirname(HERE), env=env,
                               capture_output=True, text=True, timeout=900)
            code, out = p.returncode, (p.stdout + p.stderr)
        except subprocess.TimeoutExpired:
            code, out = -1, "timed out after 900 s"
        finally:
            shutil.rmtree(home, ignore_errors=True)
            shutil.rmtree(state, ignore_errors=True)
        last = (out.strip().splitlines() or [""])[-1]
        name = os.path.basename(f)
        print(f"{'ok  ' if code == 0 else 'FAIL'}  {name:<22} {time.time() - t0:5.1f}s  {last[:90]}")
        if code != 0:
            failed.append(name)
            print("      " + "\n      ".join(out.strip().splitlines()))
    if not files:
        print("no test files matched")
        return 2
    print(f"{len(files) - len(failed)} of {len(files)} passed" + (": " + ", ".join(failed) if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
