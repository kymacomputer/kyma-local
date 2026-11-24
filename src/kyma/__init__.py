"""kyma: see what your coding agents already did, then hold what you don't want.

Everything kyma keeps lives in one directory, resolved here and nowhere else.

That directory holds excerpts of your agents' shell history. Claude Code keeps
the transcripts those excerpts come from at mode 0700/0600, readable by you
alone, so a copy that any other account on the machine could read would be
kyma widening the very exposure it exists to show you. ensure_home() creates
the directory 0700 and tightens it if an earlier version left it open. POSIX
needs search permission on every directory in a path, so nothing inside a 0700
directory is reachable by anyone else, whatever its own mode.

Set KYMA_HOME to keep this state somewhere else. The tests use it so that
running them never writes into your real decision log. Point it at an empty
folder, or one kyma made: kyma manages only its own files inside it, and only
in a folder that carries its marker (a file named .kyma that says "kyma",
owned by you, writable by no one else).

Every state file is opened without following a link. An agent that can make a
link can point ~/.kyma/log.jsonl at ~/.zshrc; the hook appends each held
command to the log, and a held command is exactly the text an agent would want
to land in a shell profile.
"""

from __future__ import annotations

import os
import stat
from contextlib import contextmanager

__version__ = "0.6.0"

# abspath: a relative KYMA_HOME baked into a hook would move with every folder
# Claude Code starts a session in.
HOME = os.path.abspath(os.path.expanduser(os.environ.get("KYMA_HOME") or "~/.kyma"))
MARK = ".kyma"                 # present in every directory kyma owns
MARK_TEXT = "kyma state folder. kyma changes only its own files in here.\n"
OWN = ("RULES.md", "log.jsonl", "checked", "report.html", ".kyma-cache", "cache", "imports", MARK)
_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)


class UnsafeHome(OSError):
    """KYMA_HOME is a folder other accounts can change, and kyma did not make it."""


def _default() -> bool:
    return os.path.realpath(HOME) == os.path.realpath(os.path.expanduser("~/.kyma"))


def _marker_ok(folder: str) -> bool:
    try:
        fd = os.open(os.path.join(folder, MARK), os.O_RDONLY | _NOFOLLOW)
    except OSError:
        return False
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid() or st.st_mode & 0o022:
            return False
        return os.read(fd, 64).startswith(b"kyma")
    except OSError:
        return False
    finally:
        os.close(fd)


def _ours() -> bool:
    """Only the default folder, or one kyma created, is kyma's to manage.
    KYMA_HOME may point at a folder full of someone's files: re-moding or
    purging those would be kyma damaging what it was asked to protect. A
    folder holding a .kyma/ directory (a project's rules) is not marked: the
    marker is a file, with kyma's words in it, that only you could have written."""
    try:
        st = os.stat(HOME)
    except OSError:
        return False
    if st.st_uid != os.getuid():
        return False
    return _default() or _marker_ok(HOME)


def _write_marker() -> None:
    try:
        fd = os.open(os.path.join(HOME, MARK), os.O_WRONLY | os.O_CREAT | os.O_EXCL | _NOFOLLOW, 0o600)
    except FileExistsError:
        # An empty marker, as kyma wrote before markers said "kyma", in a folder that is yours: fill it in.
        try:
            p = os.path.join(HOME, MARK)
            st = os.lstat(p)
            if stat.S_ISREG(st.st_mode) and st.st_size == 0 and st.st_uid == os.getuid():
                fd = os.open(p, os.O_WRONLY | _NOFOLLOW)
            else:
                return
        except OSError:
            return
    except OSError:
        return
    try:
        os.write(fd, MARK_TEXT.encode())
    finally:
        os.close(fd)


def home_problem() -> str:
    """-> why kyma must not trust its own folder, or ''. A folder that other
    accounts can write, and that kyma did not make, lets them replace RULES.md."""
    try:
        st = os.stat(HOME)
    except OSError:
        return ""
    if _ours():
        return ""
    if st.st_uid != os.getuid():
        return f"{HOME} belongs to another account"
    if st.st_mode & 0o022:
        return f"{HOME} can be changed by other accounts on this machine"
    return ""


def ensure_home() -> str:
    fresh = not os.path.lexists(HOME)
    os.makedirs(HOME, mode=0o700, exist_ok=True)
    try:
        st = os.stat(HOME)
        empty = not os.listdir(HOME)
    except OSError:
        st, empty = None, False
    mine = st is not None and st.st_uid == os.getuid() and not st.st_mode & 0o022
    # Fresh, empty, the default folder, or one holding only kyma's own files
    # (a RULES.md written there first): kyma's, so say so in the marker.
    if mine and (fresh or empty or _default() or _only_kymas()):
        _write_marker()
    if not _ours():
        why = home_problem()
        if why:
            raise UnsafeHome(f"kyma will not keep its state in {HOME}: {why.split(': ', 1)[-1]}. "
                             "Point KYMA_HOME at an empty folder of your own")
        return HOME
    try:
        if os.stat(HOME).st_mode & 0o077:
            os.chmod(HOME, 0o700)
            _tighten()
    except OSError:
        pass
    return HOME


_STATE_NAMES = ("RULES.md", "log.jsonl", "log.jsonl.lock", "checked", "checked.lock", "rules.seen", "authored.json", "authored.json.lock",
                "installs.json", "HALT", "log.summary.json", "report.html", ".kyma-cache", "cache", "imports")


def _only_kymas() -> bool:
    try:
        names = os.listdir(HOME)
    except OSError:
        return False
    return all(n in _STATE_NAMES or n == MARK or n.startswith(("rules.compiled", ".kyma-", ".log-masked")) for n in names)


def _tighten() -> None:
    """One pass over kyma's own files, and nothing else in the folder."""
    for name in OWN:
        p = os.path.join(HOME, name)
        if os.path.islink(p) or not os.path.exists(p):
            continue
        targets = [p]
        if os.path.isdir(p):
            for here, dirs, files in os.walk(p):
                targets += [os.path.join(here, x) for x in dirs + files]
        for t in targets:
            if os.path.islink(t):
                continue
            try:
                os.chmod(t, 0o700 if os.path.isdir(t) else 0o600)
            except OSError:
                pass


# ----------------------------------------------------------- state files
#
# Opened with O_NOFOLLOW, checked to be a plain file of yours with one name,
# and replaced through a fresh temp file in the same folder (rename replaces
# a link itself, never its target). One rule for every file kyma keeps.

def _safe_dirs(path: str) -> None:
    """No folder between kyma's home and this file may be a link."""
    home = os.path.realpath(HOME)
    cur, chain = os.path.dirname(os.path.abspath(path)), []
    while os.path.realpath(cur) != home:
        if os.path.dirname(cur) == cur:
            return                      # not under kyma's home: not kyma's to judge
        chain.append(cur)
        cur = os.path.dirname(cur)
    for d in chain:
        if os.path.islink(d):
            raise OSError(f"{d} is a link, so kyma will not write through it")


def _plain(fd: int, path: str) -> None:
    st = os.fstat(fd)
    if not stat.S_ISREG(st.st_mode) or st.st_nlink > 1 or st.st_uid != os.getuid():
        os.close(fd)
        raise OSError(f"{path} is not a plain file of kyma's, so kyma will not write to it")


def _marked(path: str) -> None:
    """kyma writes into its own folder only when the folder is kyma's: the
    default ~/.kyma or one carrying kyma's marker. A KYMA_HOME aimed at a folder
    full of someone else's files gets nothing written into it."""
    if os.path.realpath(os.path.dirname(os.path.abspath(path))) == os.path.realpath(HOME) and not _ours():
        raise OSError(f"{HOME} has no kyma marker, so kyma will not write into it")


@contextmanager
def _append_lock(path: str):
    """Keep append and replacement on the same inode, even during migration."""
    import fcntl
    lock = path + ".lock"
    _marked(lock)
    _safe_dirs(lock)
    fd = os.open(lock, os.O_RDWR | os.O_CREAT | _NOFOLLOW, 0o600)
    _plain(fd, lock)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def state_append(path: str, text: str) -> None:
    _marked(path)
    _safe_dirs(path)
    with _append_lock(path):
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | _NOFOLLOW, 0o600)
        _plain(fd, path)
        try:
            data = memoryview(text.encode("utf-8", "backslashreplace"))
            while data:
                data = data[os.write(fd, data):]
        finally:
            os.close(fd)


def state_read(path: str, limit: int | None = None):
    """-> the file's text, or None when it is missing, a link, or not a plain file."""
    try:
        fd = os.open(path, os.O_RDONLY | _NOFOLLOW)
    except OSError:
        return None
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            return None
        chunks, left = [], (limit if limit is not None else st.st_size + 1)
        while left > 0:
            b = os.read(fd, min(left, 1 << 20))
            if not b:
                break
            chunks.append(b)
            left -= len(b)
        return b"".join(chunks).decode("utf-8", "replace")
    except OSError:
        return None
    finally:
        os.close(fd)


def state_write(path: str, text: str, mode: int = 0o600) -> None:
    """Atomic: a fresh temp file beside it, then one rename."""
    _marked(path)
    _safe_dirs(path)
    folder = os.path.dirname(os.path.abspath(path))
    # what tempfile.mkstemp does, without importing tempfile (and shutil, random) on every hook call
    tmp = os.path.join(folder, f".kyma-{os.getpid()}-{os.urandom(6).hex()}.tmp")
    fd = os.open(tmp, os.O_RDWR | os.O_CREAT | os.O_EXCL | _NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", errors="backslashreplace") as fh:
            fh.write(text)
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    finally:
        if os.path.lexists(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass


# ------------------------------------------------------------- case
#
# macOS and Windows disks ignore case by default: ~/.Kyma/rules.md is
# ~/.kyma/RULES.md. Comparing spellings would let the first through.

_CI: dict = {}


def case_insensitive(path: str = "") -> bool:
    """Does the disk holding `path` (default: your home) ignore case?"""
    probe = os.path.realpath(path or os.path.expanduser("~"))
    while probe and not os.path.exists(probe):
        probe = os.path.dirname(probe)
    key = os.stat(probe).st_dev if probe else 0
    if key in _CI:
        return _CI[key]
    ans = False
    try:
        d = probe if os.path.isdir(probe) else os.path.dirname(probe)
        for name in os.listdir(d)[:200]:
            swapped = name.swapcase()
            if swapped != name:
                ans = os.path.exists(os.path.join(d, swapped)) and \
                    os.path.samefile(os.path.join(d, swapped), os.path.join(d, name))
                break
        else:
            up = d.upper() if d != d.upper() else d.lower()
            ans = up != d and os.path.exists(up)
    except OSError:
        ans = False
    _CI[key] = ans
    return ans


def canon(path: str) -> str:
    """One spelling per file: resolved, and folded on a disk that ignores case."""
    p = os.path.realpath(os.path.expanduser(path)) if path else path
    return p.lower() if p and case_insensitive(p) else p


def remask_log() -> None:
    """Logs written before masking was added held unmasked commands. Mask them once.

    The old prefix is transformed without a writer lock. Only the final tail
    and replacement hold the append lock, so hooks keep their receipts while
    a large legacy log is migrated. Fast check/MCP paths do not run this work."""
    log = os.path.join(HOME, "log.jsonl")
    done = os.path.join(HOME, ".log-masked-2")
    if not os.path.exists(log) or os.path.exists(done) or not _ours():
        return
    tmp = None
    try:
        import json
        from .signals import clean, redact
        def masked(line):
            try:
                e = json.loads(line)
            except ValueError:
                return b""
            if isinstance(e, dict):
                for k in ("subject", "rule", "error", "cwd"):
                    if isinstance(e.get(k), str):
                        e[k] = clean(redact(e[k]))
                return (json.dumps(e, ensure_ascii=True) + "\n").encode()
            return b""
        with _append_lock(log):
            fd = os.open(log, os.O_RDONLY | _NOFOLLOW)
            _plain(fd, log)
            old = os.fstat(fd)
        with os.fdopen(fd, "rb") as src:
            tmp = os.path.join(HOME, f".kyma-log-{os.getpid()}-{os.urandom(6).hex()}.tmp")
            target = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | _NOFOLLOW, 0o600)
            with os.fdopen(target, "wb") as dst:
                while src.tell() < old.st_size:
                    dst.write(masked(src.readline()))
                with _append_lock(log):
                    current = os.stat(log, follow_symlinks=False)
                    if (current.st_dev, current.st_ino) != (old.st_dev, old.st_ino) or current.st_size < old.st_size:
                        return
                    for line in src:
                        dst.write(masked(line))
                    dst.flush()
                    os.replace(tmp, log)
                    state_write(done, "")
    except Exception:
        pass
    finally:
        if tmp and os.path.lexists(tmp):
            os.unlink(tmp)


# ------------------------------------------------------------ records
#
# The hook starts a fresh Python on every tool call. `dataclasses` imports
# inspect, typing and ast, 16 ms of each call on the system Python 3.9, for
# three small record classes. This is the part of it kyma uses.

class _Factory:
    __slots__ = ("make",)

    def __init__(self, make):
        self.make = make


class _Field:
    __slots__ = ("name",)

    def __init__(self, name):
        self.name = name


def field(default_factory=None):
    return _Factory(default_factory)


def record(cls):
    """@dataclass, for plain records: __init__ in field order, defaults, a
    factory per instance, __post_init__, __eq__ and __repr__."""
    names = list(cls.__dict__.get("__annotations__", {}))
    defaults = {n: cls.__dict__[n] for n in names if n in cls.__dict__}
    for n in defaults:
        if not isinstance(defaults[n], property):
            delattr(cls, n) if isinstance(defaults[n], _Factory) else None

    def __init__(self, *args, **kw):
        if len(args) > len(names):
            raise TypeError(f"{cls.__name__} takes {len(names)} arguments")
        for n, v in zip(names, args):
            kw[n] = v
        for n in names:
            if n in kw:
                v = kw.pop(n)
            elif n in defaults:
                d = defaults[n]
                v = d.make() if isinstance(d, _Factory) else d
            else:
                raise TypeError(f"{cls.__name__} needs {n}")
            object.__setattr__(self, n, v)
        if kw:
            raise TypeError(f"{cls.__name__} got unexpected {sorted(kw)}")
        post = getattr(self, "__post_init__", None)
        if post is not None:
            post()

    def __eq__(self, other):
        return type(other) is type(self) and all(getattr(self, n) == getattr(other, n) for n in names)

    def __repr__(self):
        return f"{cls.__name__}(" + ", ".join(f"{n}={getattr(self, n)!r}" for n in names) + ")"

    cls.__init__, cls.__eq__, cls.__repr__, cls.__hash__ = __init__, __eq__, __repr__, None
    cls.__record_fields__ = tuple(_Field(n) for n in names)
    return cls


def fields(obj):
    return obj.__record_fields__


def asdict(obj) -> dict:
    out = {}
    for f in obj.__record_fields__:
        v = getattr(obj, f.name)
        out[f.name] = list(v) if isinstance(v, list) else dict(v) if isinstance(v, dict) else v
    return out


class lazy:
    """A module imported the first time it is used: the hook needs subprocess,
    shutil and datetime only on the rare paths that install or ask the keychain."""

    def __init__(self, name: str):
        self.__dict__["_name"] = name

    def __getattr__(self, attr):
        import importlib
        mod = importlib.import_module(self.__dict__["_name"])
        self.__dict__.update({k: getattr(mod, k) for k in dir(mod) if not k.startswith("__")})
        return getattr(mod, attr)

