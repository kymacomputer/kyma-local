"""Direct test commands must not read or change the caller's state stores."""
import _test_home  # isolate state before Kyma imports or subprocesses

import ast
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent


def snapshot(root):
    return {str(p.relative_to(root)): (p.stat().st_mode, hashlib.sha256(p.read_bytes()).hexdigest())
            for p in root.rglob("*") if p.is_file()}


class EntryIsolation(unittest.TestCase):
    def test_every_entry_isolates_before_other_imports(self):
        for path in HERE.glob("test_*.py"):
            with self.subTest(entry=path.name):
                body = ast.parse(path.read_text()).body
                if isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                    body = body[1:]
                self.assertIsInstance(body[0], ast.Import)
                self.assertEqual([a.name for a in body[0].names], ["_test_home"])

    def test_direct_consumers_leave_owner_state_unchanged(self):
        with tempfile.TemporaryDirectory(prefix="kyma-owner-sentinels-") as folder:
            owner = Path(folder)
            for name in (".kyma/log.jsonl", ".kyma/RULES.md", ".claude/settings.json",
                         "codex/config.toml", "cursor/settings.json", "xdg/kyma-local/proof",
                         "poison-light-home/keep", ".gitconfig"):
                path = owner / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("OWNER_SENTINEL_DO_NOT_CHANGE\n")
            (owner / ".kyma/.kyma").write_text("kyma state folder\n")
            env = {k: v for k, v in os.environ.items() if k in ("PATH", "LANG", "TMPDIR", "SYSTEMROOT")}
            env.update(HOME=str(owner), KYMA_HOME=str(owner / ".kyma"),
                       CLAUDE_CONFIG_DIR=str(owner / ".claude"), CODEX_HOME=str(owner / "codex"),
                       CURSOR_CONFIG_DIR=str(owner / "cursor"), XDG_STATE_HOME=str(owner / "xdg"),
                       XDG_CONFIG_HOME=str(owner / "xdg-config"), XDG_CACHE_HOME=str(owner / "xdg-cache"),
                       KYMA_LIGHT_TEST_HOME=str(owner / "poison-light-home"), PYTHONDONTWRITEBYTECODE="1")
            before = snapshot(owner)
            commands = (("test_scale.py", "Scale.test_migration_preserves_concurrent_append_without_blocking_transform"),
                        ("test_results.py",), ("test_activity_evidence.py",), ("test_sources.py",))
            for command in commands:
                with self.subTest(command=command):
                    run = subprocess.run([sys.executable, str(HERE / command[0]), *command[1:]],
                                         cwd=ROOT, env=env, capture_output=True, text=True, timeout=60)
                    self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
                    self.assertEqual(snapshot(owner), before)
                    self.assertFalse((owner / "xdg-config").exists())
                    self.assertFalse((owner / "xdg-cache").exists())

    def test_spawned_worker_retains_parent_sandbox_and_cannot_use_keychain(self):
        with tempfile.TemporaryDirectory(prefix="kyma-spawn-probe-") as folder:
            script = Path(folder) / "consumer.py"
            script.write_text('''import sys
sys.path.insert(0, sys.argv[1])
import _test_home
import json, os, multiprocessing
from concurrent.futures import ProcessPoolExecutor
def state():
    return {key: os.environ.get(key) for key in ("HOME", "KYMA_HOME", "KYMA_TEST_SANDBOX_ROOT", "KYMA_NO_KEYCHAIN")}
if __name__ == "__main__":
    parent = state()
    with ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context(sys.argv[2])) as pool:
        child = pool.submit(state).result(timeout=20)
    assert parent == child, (parent, child)
    assert parent["KYMA_NO_KEYCHAIN"] == "1"
    print(json.dumps({"same_sandbox": parent == child, "keychain_disabled": True}))
''')
            env = {k: v for k, v in os.environ.items() if k in ("PATH", "LANG", "TMPDIR", "SYSTEMROOT")}
            for method in ("spawn", "forkserver"):
                if method not in multiprocessing.get_all_start_methods():
                    continue
                with self.subTest(start_method=method):
                    run = subprocess.run([sys.executable, str(script), str(HERE), method], env=env,
                                         capture_output=True, text=True, timeout=30)
                    self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
                    self.assertEqual(json.loads(run.stdout), {"same_sandbox": True, "keychain_disabled": True})


if __name__ == "__main__":
    unittest.main(verbosity=2)
