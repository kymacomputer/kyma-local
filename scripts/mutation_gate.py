"""Break fifteen safety decisions, one at a time, in disposable copies.

Each unchanged regression must first pass. A mutant passes this gate only
when that same regression fails after its exact source substitution.
No command contained in a hook payload executes. No real keychain is used.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
REVIEW = "tests/test_review.py"
MUTANTS = [
    ("M01", "src/kyma/enforce.py", "        if kc and kc != _sha(proof.encode()):", "        if False:",
     ["tests/test_selfguard.py"]),
    ("M02", "src/kyma/enforce.py", 'return t if isinstance(t, str) and d.get("sha") == _sha(t.encode()) else None',
     'return t if isinstance(t, str) else None', [REVIEW, "a_corrupt_proof_copy"]),
    ("M03", "src/kyma/enforce.py", '        return 2                       # the host treats exit 2 as a block',
     '        return 0', [REVIEW, "out_of_time_never_allows"]),
    ("M04", "src/kyma/enforce.py", 'return _answer(stdout, "block", note + " Nothing runs',
     'return _answer(stdout, "allow", note + " Nothing runs', ["tests/test_gate.py"]),
    ("M05", "src/kyma/signals.py", '    (re.compile(r"(?i)\\b(bearer|basic)\\s+[A-Za-z0-9._~+/=-]{8,}"), r"\\1 " + MASK),',
     '', ["tests/test_signals.py"]),
    ("M06", "src/kyma/enforce.py", '    if not isinstance(o, dict) or o.get("permissionDecision") not in ("ask", "deny") \\',
     '    if False and not isinstance(o, dict) or False and o.get("permissionDecision") not in ("ask", "deny") \\',
     [REVIEW, "self_test_rejects_a_hook_that_is_not_kyma"]),
    ("M07", "src/kyma/enforce.py", '    if opaque is not None and rules.STRICT',
     '    if False and opaque is not None and rules.STRICT', ["tests/test_escapes.py"]),
    ("M08", "src/kyma/enforce.py", '    if agent and rules.STRICT', '    if False and agent and rules.STRICT',
     [REVIEW, "switching_kyma_off_or_loosening_it_asks"]),
    ("M09", "src/kyma/enforce.py", '            return (rules.Decision("ask", note="This call is too complex for kyma to read in time',
     '            return (rules.Decision("allow", note="This call is too complex for kyma to read in time',
     [REVIEW, "out_of_time_never_allows"]),
    ("M10", "src/kyma/enforce.py", 'return _answer(stdout, "ask", "kyma could not read this tool call',
     'return _answer(stdout, "allow", "kyma could not read this tool call', ["tests/test_gate.py"]),
    ("M11", "src/kyma/__init__.py", '    if st.st_mode & 0o022:\n        return f"{HOME} can be changed by other accounts on this machine"',
     '    if False:\n        return f"{HOME} can be changed by other accounts on this machine"',
     [REVIEW, "a_foreign_kyma_home"]),
    ("M12", "src/kyma/enforce.py", '            if early is not None and early.verdict == "block":', '            if False:',
     [REVIEW, "out_of_time_never_allows"]),
    ("M13", "src/kyma/enforce.py", '    if guarded and rules.STRICT', '    if False and guarded and rules.STRICT',
     [REVIEW, "shell_profiles_cannot_move_the_hook"]),
    ("M14", "src/kyma/enforce.py", '        return _answer(stdout, "ask", f"kyma is plugged in but',
     '        return _answer(stdout, "allow", f"kyma is plugged in but', [REVIEW, "check_uses_the_starter_rules"]),
    ("M15", "src/kyma/enforce.py", '        if _seen_proofed() and not kc:', '        if False:',
     ["tests/test_selfguard.py"]),
]


def run(root, args, box):
    home = box / "home"
    state = box / "state"
    home.mkdir(mode=0o700)
    state.mkdir(mode=0o700)
    env = {k: v for k, v in os.environ.items() if k in ("PATH", "LANG", "LC_ALL", "TZ", "TMPDIR")}
    env.update(HOME=str(home), KYMA_HOME=str(state), KYMA_NO_KEYCHAIN="1", KYMA_ALLOW_TEMP_HOME="1",
               PYTHONDONTWRITEBYTECODE="1")
    p = subprocess.run([sys.executable, *args], cwd=root, env=env, capture_output=True, text=True, timeout=90)
    return p.returncode, p.stdout + p.stderr


def main():
    results = []
    with tempfile.TemporaryDirectory(prefix="kyma-mutation-") as parent:
        base = Path(parent)
        for ident, file, old, new, args in MUTANTS:
            box = base / ident
            box.mkdir()
            repo = box / "repo"
            shutil.copytree(ROOT, repo, ignore=shutil.ignore_patterns(".git", "__pycache__", "build", ".test-homes", "*.egg-info"))
            source = repo / file
            text = source.read_text()
            if text.count(old) != 1:
                raise RuntimeError(f"{ident}: source pattern occurs {text.count(old)} times")
            normal = box / "normal"
            normal.mkdir()
            before, output = run(repo, args, normal)
            if before:
                raise RuntimeError(f"{ident}: unmodified regression failed\n{output}")
            source.write_text(text.replace(old, new))
            broken = box / "broken"
            broken.mkdir()
            after, output = run(repo, args, broken)
            receipt = {"id": ident, "caught": after != 0, "baseline_exit": before, "mutant_exit": after,
                       "regression": args, "evidence": output.strip().splitlines()[-10:]}
            results.append(receipt)
            print(json.dumps(receipt), flush=True)
    print(f"mutation gate: {sum(r['caught'] for r in results)}/{len(results)} caught")
    return int(not all(r["caught"] for r in results))


if __name__ == "__main__":
    raise SystemExit(main())
