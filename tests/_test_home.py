"""Isolate direct test entry points before Kyma resolves any state paths.

Import this module before Kyma or a test helper. Spawned workers reuse their
parent's sandbox. Only the process that created a sandbox removes it.
"""

import atexit
import json
import multiprocessing
import os
from pathlib import Path
import shutil
import sys
import tempfile


if "kyma" in sys.modules:
    raise RuntimeError("Test isolation must precede Kyma imports. Run python3 tests/run.py instead.")

ORIGINAL_CLAUDE_CONFIG_DIR = os.path.expanduser(os.environ.get("CLAUDE_CONFIG_DIR") or "~/.claude")
_OWNER = "KYMA_TEST_SANDBOX_PID"
_ROOT = "KYMA_TEST_SANDBOX_ROOT"


def _inherited():
    root = os.environ.get(_ROOT, "")
    owner = os.environ.get(_OWNER, "")
    # A forkserver worker's OS parent is the server, not the test process.
    # Both spawn and forkserver mark this phase before they import the main file.
    worker_bootstrap = getattr(multiprocessing.current_process(), "_inheriting", False)
    if not root or not owner.isdecimal() or (owner != str(os.getppid()) and not worker_bootstrap):
        return False
    try:
        marker = Path(root) / ".test-owner.json"
        return not marker.is_symlink() and json.loads(marker.read_text()) == {"pid": int(owner)}
    except (OSError, ValueError, TypeError):
        return False


if not _inherited():
    base = Path(tempfile.gettempdir())
    if str(base.resolve()).startswith(("/tmp", "/private/tmp", "/var/tmp", "/dev/shm")):
        # Starter rules treat /tmp as disposable. A test HOME must retain the
        # same protected-home semantics as a normal user's HOME.
        base = Path(__file__).resolve().parent.parent / ".test-homes"
        base.mkdir(exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="kyma-direct-test-", dir=base))
    (root / ".test-owner.json").write_text(json.dumps({"pid": os.getpid()}))
    os.environ[_ROOT] = str(root)
    os.environ[_OWNER] = str(os.getpid())
    os.environ["HOME"] = str(root)
    os.environ["KYMA_HOME"] = str(root / ".kyma")
    os.environ["KYMA_ALLOW_TEMP_HOME"] = "1"
    os.environ["KYMA_NO_KEYCHAIN"] = "1"
    for key in ("CLAUDE_CONFIG_DIR", "CODEX_HOME", "CURSOR_CONFIG_DIR", "KYMA_LIGHT_TEST_HOME",
                "XDG_STATE_HOME", "XDG_CONFIG_HOME", "XDG_CACHE_HOME"):
        os.environ.pop(key, None)

    def _cleanup():
        if os.environ.get(_OWNER) == str(os.getpid()):
            shutil.rmtree(root, ignore_errors=True)

    atexit.register(_cleanup)
