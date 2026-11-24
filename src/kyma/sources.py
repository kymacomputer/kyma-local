"""Read what your agents already did, from logs already on your disk.

Nothing here touches the network. Nothing here leaves the machine.

Two agents, several private formats, one normalized Action:

  Claude Code   ~/.claude/projects/<slug>/<session>.jsonl
                ~/.claude/projects/<slug>/<session>/subagents/agent-*.jsonl
                assistant messages contain content blocks of type "tool_use".
                Subagent transcripts held 72% of all tool calls on one heavy
                machine, so a reader that stops at the top level misses most
                of what happened.

  Codex         ~/.codex/sessions/[<y>/<m>/<d>/]rollout-*.jsonl[.zst]
                ~/.codex/archived_sessions/ (the same files, archived)
                Every generation is still on someone's disk:
                  TypeScript CLI         one pretty-printed rollout-*.json
                  Rust CLI to v0.31      each line is a bare response item,
                                         after one line of session metadata
                  Rust CLI v0.34 on      each line is {timestamp, type, payload}
                Shell work arrives as a function_call to shell (an argv list),
                shell_command (a string), exec_command ({"cmd": ...}),
                container.exec, as a local_shell_call (an argv list), or as a
                JS snippet run by the "exec" tool that calls
                tools.exec_command({cmd: ...}), often several times. File
                edits arrive as apply_patch, whose paths are its "*** Update
                File:" lines.

The normalization is deliberately lossy. We keep the five fields a human
actually asks about -- which agent, when, which tool, what command, which
paths -- and drop the rest. A scanner that kept everything would be a second
transcript, and nobody reads the first one.

A log is evidence, not a contract: a crash truncates a line, a version we never
saw adds a shape, a hand edit leaves a list where a string was. So the readers
never raise on content. A line they cannot use is skipped and the next one is
read, and every Action field has its declared type whatever the line held.
Access is different. A file that cannot be opened or read raises Unreadable,
before anything is yielded, so a caller can tell "this log is empty" from "we
could not look", and does not cache the second as the first.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import stat
import time
from . import field, lazy, record as dataclass

shutil, subprocess = lazy("shutil"), lazy("subprocess")
from typing import Iterator

def claude_dir() -> str:
    """Claude Code moves its whole folder when CLAUDE_CONFIG_DIR is set."""
    return os.path.expanduser(os.environ.get("CLAUDE_CONFIG_DIR") or "~/.claude")


CLAUDE_ROOT = os.path.join(claude_dir(), "projects")
def codex_dir() -> str:
    """Codex moves its whole folder when CODEX_HOME is set."""
    return os.path.expanduser(os.environ.get("CODEX_HOME") or "~/.codex")


CODEX_ROOT = os.path.join(codex_dir(), "sessions")
CODEX_ARCHIVE = os.path.join(codex_dir(), "archived_sessions")

# Tools whose job is to run a shell command, across agents.
SHELL_TOOLS = {"Bash", "exec", "shell", "local_shell", "run_command", "execute_command",
               "shell_command", "exec_command", "container.exec"}
# Tools that write to the filesystem.
WRITE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit", "apply_patch", "patch", "create_file"}
# Tools that read the filesystem.
READ_TOOLS = {"Read", "read_file", "view", "cat"}

# Everything downstream runs regexes over the command, so one pasted megabyte
# must not cost a megabyte of matching per rule.
COMMAND_CAP = 256 * 1024
# Directories below a root that discovery descends. Subagent transcripts sit
# three below ~/.claude/projects; Codex rollouts three below sessions/.
MAX_DEPTH = 4
# A longer line is dropped whole, read in pieces, never held in memory.
_MAX_LINE = 64 * 1024 * 1024
# The TypeScript CLI's rollout-*.json is parsed whole, so it is bounded too.
_MAX_JSON_FILE = 64 * 1024 * 1024


class Unreadable(Exception):
    """A log that exists but could not be read: no permission, an I/O error,
    not a regular file, or compressed with no zstd to open it.

    Raised by _read_claude and _read_codex before they yield anything, so the
    caller can skip caching the file instead of recording an empty session. An
    I/O error partway through raises it too: a partial read must not pass for a
    whole one.
    """

    def __init__(self, path: str, reason: str = ""):
        super().__init__(path, reason)      # (path, reason) keeps it picklable
        self.path = path
        self.reason = reason

    def __str__(self) -> str:
        return f"cannot read {self.path}" + (f": {self.reason}" if self.reason else "")


def _text(v, cap: int = 0) -> str:
    if type(v) is not str:
        return ""
    return v[:cap] if cap and len(v) > cap else v


def _clean_paths(v) -> list:
    out, total = [], 0
    for p in v if type(v) is list else ():
        if type(p) is str and p:
            total += len(p)
            if total > COMMAND_CAP:
                break
            out.append(p)
    return out


@dataclass
class Action:
    """One thing an agent did."""

    agent: str                 # "claude" | "codex"
    tool: str                  # tool name as the agent recorded it
    ts: str = ""               # ISO timestamp, may be empty
    command: str = ""          # shell command, when there is one
    paths: list = field(default_factory=list)   # filesystem paths touched
    project: str = ""          # cwd / project slug
    session: str = ""          # session id, for "show me that run"
    kind: str = "other"        # shell | write | read | mcp | other
    call_id: str = ""          # source-scoped digest of the exact native call ID

    def __post_init__(self):
        # The log decides what arrives here, and it can hold anything. A
        # timestamp written as a number used to reach index.py as an int, and a
        # cwd written as a list crashed the project counter: a list cannot be
        # a dict key. Every reader's output passes through this one check, so a
        # new format cannot forget it. The first test is the common case, done
        # in one expression because it runs for every Action of a 2 GB scan.
        c, t, p = self.command, self.ts, self.paths
        if (type(c) is str and type(t) is str and type(self.tool) is str and type(self.project) is str
                and type(self.session) is str and type(self.agent) is str and type(self.kind) is str
                and type(p) is list and len(c) <= COMMAND_CAP and len(t) <= 64 and self.kind
                and len(self.tool) <= 512 and len(self.project) <= 4096 and len(self.session) <= 512
                and type(self.call_id) is str and (not self.call_id or re.fullmatch(r"[a-f0-9]{64}", self.call_id))
                and (not p or (len(p) == 1 and type(p[0]) is str and 0 < len(p[0]) <= COMMAND_CAP))):
            return
        if type(self.agent) is not str:
            self.agent = ""
        if type(self.tool) is not str or len(self.tool) > 512:
            self.tool = _text(self.tool, 512)
        if type(self.ts) is not str or len(self.ts) > 64:
            self.ts = ""                # no real ISO timestamp is this long
        if type(self.command) is not str or len(self.command) > COMMAND_CAP:
            self.command = _text(self.command, COMMAND_CAP)
        if type(self.paths) is not list or self.paths:
            self.paths = _clean_paths(self.paths)
        if type(self.project) is not str or len(self.project) > 4096:
            self.project = _text(self.project, 4096)
        if type(self.session) is not str or len(self.session) > 512:
            self.session = _text(self.session, 512)
        if type(self.kind) is not str or not self.kind:
            self.kind = "other"
        if type(self.call_id) is not str or not re.fullmatch(r"[a-f0-9]{64}", self.call_id):
            self.call_id = ""

    @property
    def subject(self) -> str:
        """The single string a matcher should look at."""
        if self.command:
            return self.command
        if self.paths:
            return " ".join(self.paths)
        return ""

    @property
    def label(self) -> str:
        lines = self.command.strip().splitlines()
        if lines:                       # a whitespace-only command has none
            return lines[0][:160]
        if self.paths:
            return f"{self.tool} {self.paths[0]}"
        return self.tool


def _kind(tool: str) -> str:
    if tool in SHELL_TOOLS:
        return "shell"
    if tool in WRITE_TOOLS:
        return "write"
    if tool in READ_TOOLS:
        return "read"
    if tool.startswith("mcp__"):
        return "mcp"
    return "other"


def _paths_from_input(inp: dict) -> list:
    out = []
    for key in ("file_path", "path", "notebook_path", "filePath", "target_file"):
        v = inp.get(key)
        if isinstance(v, str) and v:
            out.append(v)
    return out


# ------------------------------------------------------------------ discovery

def _discover(root: str, want, min_depth: int, best: dict) -> None:
    """Fill best[(st_dev, st_ino)] = (is_symlink, path, stat) for every regular,
    non-empty file under root whose name passes want().

    Three hazards each cost a user real numbers. A symlinked directory such as
    sessions/2026/11/loop -> .. made glob read one session 33 times, so
    directories are entered only when they are real, and a file reached twice
    (a hard link, a symlink to it) is kept once, preferring its real path. A
    FIFO named x.jsonl blocked the scan forever on open(), and a directory or an
    empty file named like a log counted as a session, so only regular files with
    bytes in them count. Depth is bounded because nothing legitimate sits deeper.
    """
    # A symlinked directory is followed only while it stays inside the root:
    # a link to / walked the whole disk, and a link anywhere else is history
    # someone else wrote. Each directory is entered once by (device, inode),
    # which is what ends a loop such as sessions/loop -> ..
    seen = set()
    try:
        r = os.stat(root)
        seen.add((r.st_dev, r.st_ino))
        top = os.path.realpath(root).rstrip("/") + "/"
    except OSError:
        return
    stack = [(root, 0)]
    while stack:
        here, depth = stack.pop()
        try:
            with os.scandir(here) as it:
                entries = list(it)
        except OSError:
            continue
        for e in entries:
            try:
                if e.is_dir(follow_symlinks=True):
                    if e.is_symlink() and not (os.path.realpath(e.path) + "/").startswith(top):
                        continue
                    d = e.stat(follow_symlinks=True)
                    if depth < MAX_DEPTH and (d.st_dev, d.st_ino) not in seen:
                        seen.add((d.st_dev, d.st_ino))
                        stack.append((e.path, depth + 1))
                    continue
                if depth < min_depth or not want(e.name):
                    continue
                st = e.stat()                 # follows a symlinked file to its target
                link = e.is_symlink()
            except OSError:
                continue
            if not stat.S_ISREG(st.st_mode) or st.st_size == 0:
                continue
            key = (st.st_dev, st.st_ino)
            cand = (link, e.path, st)
            cur = best.get(key)
            if cur is None or cand[:2] < cur[:2]:
                best[key] = cand


def _fresh(found: list, since_days) -> list:
    if since_days:
        cutoff = time.time() - since_days * 86400
        found = [f for f in found if f[2].st_mtime >= cutoff]
    return sorted(f[1] for f in found)


def _claude_files(since_days: int | None = None) -> list:
    best: dict = {}
    # min_depth=1: a session always sits inside a project directory.
    _discover(CLAUDE_ROOT, lambda n: n.endswith(".jsonl"), 1, best)
    return _fresh(list(best.values()), since_days)


def _is_rollout(name: str) -> bool:
    return name.startswith("rollout-") and name.endswith((".jsonl", ".jsonl.zst", ".json"))


def _codex_found() -> list:
    """Every Codex rollout on disk, compressed ones included."""
    best: dict = {}
    for root in (CODEX_ROOT, CODEX_ARCHIVE):
        _discover(root, _is_rollout, 0, best)
    found = list(best.values())
    # Codex compresses old rollouts to .jsonl.zst and decompresses one to plain
    # .jsonl when a session is resumed. While both exist the plain file is the
    # authoritative one (Codex itself skips the compressed sibling), and reading
    # both would count that session twice.
    plain = {f[1] for f in found if f[1].endswith(".jsonl")}
    return [f for f in found if not (f[1].endswith(".zst") and f[1][:-4] in plain)]


def _codex_files(since_days: int | None = None) -> list:
    found = _codex_found()
    if not shutil.which("zstd"):
        found = [f for f in found if not f[1].endswith(".zst")]
    return _fresh(found, since_days)


def compressed_skipped() -> int:
    """How many compressed Codex logs exist that cannot be read, because no
    zstd binary is on PATH. Zero when zstd exists. Without this number a user
    whose old sessions are all compressed is told those sessions did nothing."""
    if shutil.which("zstd"):
        return 0
    return sum(1 for f in _codex_found() if f[1].endswith(".zst"))


# -------------------------------------------------------------------- reading

_O_READ = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0)


def _why(e: OSError) -> str:
    return e.strerror or e.__class__.__name__


def _open_log(path: str):
    """Open a log for binary reading, or raise Unreadable.

    O_NONBLOCK makes open() return at once even if the path became a FIFO
    after discovery, and fstat then refuses it. A regular file ignores the
    flag, so reads behave as usual.
    """
    try:
        fd = os.open(path, _O_READ)
    except OSError as e:
        raise Unreadable(path, _why(e)) from e
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise Unreadable(path, "not a regular file")
        return os.fdopen(fd, "rb", buffering=1024 * 1024)
    except OSError as e:
        os.close(fd)
        raise Unreadable(path, _why(e)) from e
    except BaseException:
        os.close(fd)
        raise


def _bounded(fh) -> Iterator[bytes]:
    """Lines of a binary stream, dropping any longer than _MAX_LINE whole."""
    readline = fh.readline
    while True:
        line = readline(_MAX_LINE)
        if not line:
            return
        if len(line) == _MAX_LINE and not line.endswith(b"\n"):
            while True:                 # skip the rest of the oversized line
                more = readline(_MAX_LINE)
                if not more or more.endswith(b"\n"):
                    break
            continue
        yield line


def _log_lines(path: str, cursor: dict | None = None) -> Iterator[bytes]:
    """Raw lines of a plain log. Bytes, split on b"\\n" alone: a line is decoded
    only once it looks like a tool call, which is the whole cost of a 2 GB scan,
    and str.splitlines would also have split inside a JSON string at U+2028."""
    fh = _open_log(path)
    with fh:
        try:
            if cursor is None:
                yield from _bounded(fh)
                return
            fh.seek(cursor.get("offset", 0))
            while True:
                begin = fh.tell()
                raw = fh.readline(_MAX_LINE)
                if not raw:
                    return
                if len(raw) == _MAX_LINE and not raw.endswith(b"\n"):
                    while raw and not raw.endswith(b"\n"):
                        raw = fh.readline(_MAX_LINE)
                    cursor.update(offset=fh.tell(), item=0)
                    continue
                # A live writer may not have finished this record. Retry its
                # start on the next pass instead of permanently skipping it.
                if not raw.endswith(b"\n") and _loads(raw) is None:
                    cursor.update(offset=begin, item=0)
                    return
                yield raw
                cursor.update(offset=fh.tell(), item=0)
        except OSError as e:
            raise Unreadable(path, _why(e)) from e


def _zstd_lines(path: str) -> Iterator[bytes]:
    """Raw lines of a .jsonl.zst, streamed through the zstd binary.

    The file is opened here and handed to zstd as stdin, so a permission
    problem is reported as Unreadable rather than as an empty decompression.
    Streaming keeps memory flat on a large session; the old read-it-all call
    also had a 30 s timeout that silently dropped the biggest files.
    """
    exe = shutil.which("zstd")
    if not exe:
        raise Unreadable(path, "compressed, and no zstd binary is on PATH")
    fh = _open_log(path)
    with fh:
        try:
            proc = subprocess.Popen([exe, "-d", "-c", "-q"], stdin=fh,
                                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        except (OSError, ValueError, subprocess.SubprocessError) as e:
            raise Unreadable(path, f"could not run zstd: {e}") from e
        try:
            yield from _bounded(proc.stdout)
        except OSError as e:
            raise Unreadable(path, _why(e)) from e
        finally:
            proc.stdout.close()
            if proc.poll() is None:
                proc.kill()             # the caller stopped early
            proc.wait()


def _safe_int(s: str):
    # Before 3.10.7 and 3.9.14 Python parsed a long digit string in quadratic
    # time, so one line of a million digits stalled the scan for minutes. No
    # field we read is a number, so a huge one becomes 0.
    return int(s) if len(s) <= 4000 else 0


def _loads(raw: bytes):
    """Parse one JSON line, or return None. Content never raises here: a
    truncated line, a bad byte, or nesting deeper than the recursion limit is
    skipped like any other line we cannot use."""
    try:
        text = raw.decode("utf-8", "replace")
        if text[:1] == "\ufeff":        # a BOM, left by an editor on a hand-edited log
            text = text[1:]
        if len(text) > 100_000:
            return json.loads(text, parse_int=_safe_int)
        return json.loads(text)
    except (ValueError, RecursionError):
        return None


# ---------------------------------------------------------------- Claude Code

def _claude_ids(path: str) -> tuple:
    """(project slug, session id) for a transcript path. A subagent transcript
    at <slug>/<session>/subagents/agent-x.jsonl belongs to <session>; its
    parent directory, "subagents", is not a project."""
    root = CLAUDE_ROOT.rstrip(os.sep) + os.sep
    if path.startswith(root):
        parts = path[len(root):].split(os.sep)
        if len(parts) >= 3:
            return parts[0], parts[1]
    return os.path.basename(os.path.dirname(path)), os.path.basename(path)[:-6]


def _read_claude(path: str, cursor: dict | None = None) -> Iterator[Action]:
    slug, session = _claude_ids(path)
    for raw in _log_lines(path, cursor):
        # Cheap pre-filter: most lines are prose, and decoding plus json.loads
        # is the expensive part of a 2 GB scan.
        if b'"tool_use"' not in raw:
            continue
        rec = _loads(raw)
        if type(rec) is not dict:
            continue
        msg = rec.get("message")
        if type(msg) is not dict:
            continue
        content = msg.get("content")
        if type(content) is not list:
            continue
        ts = rec.get("timestamp")
        cwd = rec.get("cwd")
        project = cwd if type(cwd) is str and cwd else slug
        skip = cursor.get("item", 0) if cursor is not None else 0
        for i, block in enumerate(content):
            if i < skip:
                continue
            if type(block) is not dict or block.get("type") != "tool_use":
                continue
            tool = block.get("name")
            if type(tool) is not str:
                tool = ""
            inp = block.get("input")
            if type(inp) is not dict:
                inp = {}
            command = inp.get("command")
            if cursor is not None:
                cursor["item"] = i + 1
            yield Action(
                agent="claude",
                tool=tool,
                ts=ts,
                command=command if type(command) is str else "",
                paths=_paths_from_input(inp),
                project=project,
                session=session,
                kind=_kind(tool),
                call_id=call_id(block.get("id"), path),
            )


def human_times(path: str, agent: str) -> Iterator[str]:
    """When a person typed to the agent. The other half of the picture.

    Tool results, injected context (`<system-reminder>`, `<environment_context>`),
    subagent briefs and resumed-session summaries are the machine talking to
    itself, so they are not counted. Never raises: a missing half is better
    than no picture."""
    try:
        if agent == "claude":
            for raw in _log_lines(path):
                if b'"type":"user"' not in raw.replace(b" ", b"") or b'"tool_result"' in raw:
                    continue
                rec = _loads(raw)
                if type(rec) is not dict or rec.get("type") != "user":
                    continue
                if rec.get("isSidechain") or rec.get("isMeta") or rec.get("isCompactSummary"):
                    continue
                msg = rec.get("message")
                c = msg.get("content") if type(msg) is dict else None
                if type(c) is list:
                    c = " ".join(b.get("text", "") for b in c if type(b) is dict and b.get("type") == "text")
                if type(c) is not str:
                    continue
                t = c.lstrip()
                if not t or t.startswith(("<", "Caveat:", "[Request interrupted", "This session is being continued")):
                    continue
                ts = rec.get("timestamp")
                if type(ts) is str:
                    yield ts
        elif not path.endswith(".json"):
            lines = _zstd_lines(path) if path.endswith(".zst") else _log_lines(path)
            try:
                for raw in lines:
                    if b'"user_message"' not in raw:
                        continue
                    rec = _loads(raw)
                    p = rec.get("payload") if type(rec) is dict else None
                    if type(p) is dict and p.get("type") == "user_message":
                        m = p.get("message")
                        if type(m) is str and m.strip() and not m.lstrip().startswith("<"):
                            ts = rec.get("timestamp")
                            if type(ts) is str:
                                yield ts
            finally:
                lines.close()
    except Exception:
        return


# ---------------------------------------------------------------------- Codex

# `.encode().decode("unicode_escape")` decodes each UTF-8 BYTE as its own
# character: "•" became "â\x80¢", and the \x80 rendered as a replacement
# glyph in the middle of a quoted command. Unescape the escape sequences only.
_JS_ESC = re.compile(r"\\(u\{[0-9a-fA-F]+\}|u[0-9a-fA-F]{4}|x[0-9a-fA-F]{2}|[\s\S])")
_JS_SIMPLE = {"n": "\n", "r": "\r", "t": "\t", "b": "\b", "f": "\f", "v": "\v", "0": "\0", "\n": ""}


def _js_unescape(s: str) -> str:
    def one(m):
        e = m.group(1)
        try:
            if e.startswith("u{"):
                return chr(int(e[2:-1], 16))
            if len(e) == 5 and e[0] == "u":
                return chr(int(e[1:], 16))
            if len(e) == 3 and e[0] == "x":
                return chr(int(e[1:], 16))
        except (ValueError, OverflowError):
            return "\ufffd"             # \u{110000} and above are not characters
        return _JS_SIMPLE.get(e, e)
    out = _JS_ESC.sub(one, s)
    # join \ud83d\ude00-style surrogate pairs; a lone half becomes U+FFFD
    return out.encode("utf-16", "surrogatepass").decode("utf-16", "replace")


# A scanner over a JS snippet that sees string literals whole, so nothing
# inside a string, a comment or a regex literal is mistaken for code. The old
# pattern, (['"`])(.*?)\1, ended a string at its first escaped quote and stored
#   tools.exec_command({cmd: "git commit -m \"wip\" && git push"})
# as `git commit -m \`. It also read only the first call, while one snippet
# often runs several commands, or builds them as data first:
#   const jobs = [{cmd: "npm test"}, {cmd: 'npm run lint'}]
# so every `cmd:` property whose value is a string literal is a command. A key
# counts only after { or , so the branch in `a ? cmd : b` is not one.
#
# _JS_NEXT finds the next place anything can start. Each of its branches
# begins with one literal character, which lets the regex engine skip every
# other character in C: 2.8 us a snippet, against 6.4 us for one alternation
# tried at every position.
_JS_KEY = r'''\s*(?:cmd\b|"cmd"|'cmd')\s*:\s*'''
_JS_NEXT = re.compile(r'"|' + r"'|`|/|\{" + _JS_KEY + r"|," + _JS_KEY
                      + r'''|\.shell_command\s*\(\s*\{\s*(?:command\b|"command"|'command')\s*:\s*''')
_JS_STRING = {
    '"': re.compile(r'"[^"\\\n]*(?:\\[\s\S][^"\\\n]*)*"'),
    "'": re.compile(r"'[^'\\\n]*(?:\\[\s\S][^'\\\n]*)*'"),
    "`": re.compile(r"`[^`\\]*(?:\\[\s\S][^`\\]*)*`"),
}
_JS_REGEX = re.compile(r"/(?![/*])(?:[^/\\\[\n]|\\.|\[(?:[^\]\\\n]|\\.)*\])+/[A-Za-z]*")
# After one of these a slash opens a regex literal, not a division. Left
# unrecognised, /["']/ opens a string that swallows the rest of the line.
_JS_BEFORE_REGEX = frozenset("(,=:[!&|?{};")


def _js_calls(src: str) -> list:
    """[(kind, command, paths)] for the shell commands and patches in a JS
    snippet, in source order."""
    if "cmd" not in src and "apply_patch" not in src and "shell_command" not in src:
        return []
    patching = "apply_patch" in src
    out = []
    at = -1                             # where a command's string must start
    pos, end = 0, len(src)
    search = _JS_NEXT.search
    while True:
        m = search(src, pos)
        if m is None:
            return out
        i = m.start()
        c = src[i]
        if c == '"' or c == "'" or c == "`":
            s = _JS_STRING[c].match(src, i)
            if s is None:               # unterminated: not a string after all
                pos, at = i + 1, -1
                continue
            if i == at:
                out.append(("shell", _js_unescape(s.group()[1:-1]), []))
            elif patching and "*** Begin Patch" in s.group():
                # tools.apply_patch("*** Begin Patch ..."), or the same text
                # held in a variable first
                paths = _patch_paths(_js_unescape(s.group()[1:-1]))
                if paths:
                    out.append(("write", "", paths))
            pos, at = s.end(), -1
        elif c == "/":
            after = src[i + 1:i + 2]
            if after == "/":
                e = src.find("\n", i)
                pos = end if e < 0 else e
            elif after == "*":
                e = src.find("*/", i + 2)
                pos = end if e < 0 else e + 2
            else:
                j = i - 1
                while j >= 0 and src[j] in " \t\r\n":
                    j -= 1
                r = _JS_REGEX.match(src, i) if j < 0 or src[j] in _JS_BEFORE_REGEX else None
                pos = r.end() if r else i + 1
            at = -1
        else:                           # a cmd: key; its value must follow at once
            pos = at = m.end()


_PATCH_PATH = re.compile(r"^[ \t]*\*\*\* (?:(?:Add|Update|Delete) File|Move to): *(.+?)[ \t\r]*$", re.M)


def _patch_paths(text) -> list:
    """Paths an apply_patch body touches, from its file header lines."""
    if type(text) is not str or "*** " not in text:
        return []
    out, seen = [], set()
    for m in _PATCH_PATH.finditer(text):
        p = m.group(1)
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


_SHELLS = {"sh", "bash", "zsh", "dash", "ksh", "mksh", "ash", "fish"}


def _argv_script(argv: list) -> str:
    """The command a human would have typed for an argv list.

    Codex usually wraps the script, ["bash", "-lc", "<script>"], and the script
    is the command: joining the list would quote it into one opaque argument
    that no signal can see into. A bare argv such as ["rg", "--files"] is
    joined with shell quoting.
    """
    head = re.split(r"[\\/]", argv[0])[-1].lower()
    if head.endswith(".exe"):
        head = head[:-4]
    if head in _SHELLS:
        i = 1
        while i < len(argv):
            a = argv[i]
            if a in ("-o", "+o", "-O", "+O"):     # these take a value
                i += 2
                continue
            if a == "--" or a[:1] not in ("-", "+") or len(a) < 2:
                break                             # a script file, not -c
            if not a.startswith("--") and "c" in a[1:]:
                if i + 1 < len(argv):
                    return argv[i + 1]
                break
            i += 1
    elif head in ("pwsh", "powershell"):
        for i, a in enumerate(argv[1:], 1):
            if a.lower() in ("-command", "-c") and i + 1 < len(argv):
                return " ".join(argv[i + 1:])
    elif head == "cmd":
        for i, a in enumerate(argv[1:], 1):
            if a.lower() in ("/c", "/k") and i + 1 < len(argv):
                return " ".join(argv[i + 1:])
    return shlex.join(argv)


def _argv_call(v):
    """(kind, command, paths) for a shell tool's command value, or None."""
    if type(v) is str:
        return ("shell", v, [])
    if type(v) is not list:
        return None
    argv = [a for a in v if type(a) is str]
    if not argv:
        return None
    if re.split(r"[\\/]", argv[0])[-1] in ("apply_patch", "applypatch"):
        # Codex ran ["apply_patch", "<patch>"] itself, with no shell: it is an
        # edit, and its patch text is file content, not a command.
        return ("write", "", _patch_paths(argv[1]) if len(argv) > 1 else [])
    return ("shell", _argv_script(argv), [])


_BAD = object()
# Arguments worth a JSON parse start like an object, a list or an encoded string.
_JSON_START = ("{", "[", '"')


def _json(s: str):
    try:
        return json.loads(s)
    except (ValueError, RecursionError):
        return _BAD


def _codex_args(raw) -> tuple:
    """(arguments dict, source text). A function call's arguments are JSON,
    usually encoded as a string and sometimes encoded twice. A custom tool's
    input is raw text: a JS snippet or a patch."""
    if type(raw) is dict:
        return raw, None
    if type(raw) is not str:
        return {}, None
    if raw[:1] not in _JSON_START and raw.lstrip()[:1] not in _JSON_START:
        return {}, raw                  # a JS snippet or a patch: no JSON parse to fail
    v = _json(raw)
    if v is _BAD:
        return {}, raw
    if type(v) is str:
        w = _json(v)
        return (w, None) if type(w) is dict else ({}, v)
    return (v, None) if type(v) is dict else ({}, None)


_CODEX_CALLS = ("function_call", "custom_tool_call", "local_shell_call")
_PATCH_TOOLS = ("apply_patch", "applypatch")

_CALL_ID = re.compile(r"[A-Za-z0-9_.:-]{1,256}\Z")
_RAW_CALL_ID = re.compile(rb'"(?:id|tool_use_id|call_id)"\s*:\s*("(?:[^"\\]|\\.){1,1536}")')


def call_id(value, path: str) -> str:
    """An exact ID join, scoped to one source, without exposing log identifiers."""
    if type(value) is not str or not _CALL_ID.fullmatch(value):
        return ""
    return hashlib.sha256((path + "\0" + value).encode("utf-8", "surrogatepass")).hexdigest()


def has_call_id(raw: bytes, path: str, wanted: set) -> bool:
    for match in _RAW_CALL_ID.finditer(raw):
        value = match.group(1)
        native = _loads(value) if b"\\" in value else value[1:-1].decode("utf-8", "replace")
        if call_id(native, path) in wanted:
            return True
    return False


def codex_call_id(item: dict, path: str, tool: str, calls: list) -> str:
    # An outer JS execution can contain several tools, or print their result.
    # Its completion does not identify a nested action's completion.
    if len(calls) != 1 or tool.rsplit(".", 1)[-1] == "exec":
        return ""
    raw = item.get("arguments", item.get("input"))
    _args, src = _codex_args(raw)
    if src is not None and "exec_command" in src and tool not in WRITE_TOOLS:
        return ""
    return call_id(item.get("call_id"), path)


def _codex_result_status(item: dict) -> tuple:
    """Only explicit host result fields or a complete shell-result header."""
    data = item.get("output")
    fields = [item, data] if type(data) is dict else [item]
    codes = [f["exit_code"] for f in fields if type(f.get("exit_code")) is int]
    errors = [f["is_error"] for f in fields if type(f.get("is_error")) is bool]
    states = {code != 0 for code in codes} | set(errors)
    if len(states) > 1:
        return "unknown", "conflicting_result"
    if codes:
        return ("tool_failed" if codes[0] else "tool_succeeded"), "codex_exit_code"
    if errors:
        return ("tool_failed" if errors[0] else "tool_succeeded"), "codex_is_error"
    if type(data) is str:
        # Read only the host header. Output text can itself contain fake status.
        match = re.match(r"\AChunk ID: [A-Za-z0-9_-]+\r?\nWall time: [0-9.]+ seconds\r?\n"
                         r"Process exited with code (-?\d+)\r?\n(?:Final output|Output):", data[:400])
        if match:
            return ("tool_failed" if int(match.group(1)) else "tool_succeeded"), "codex_shell_header"
    return "unknown", "unknown"


def result_links(rec: dict, agent: str, path: str):
    """Yield call/result identities and status only. Never retain output text."""
    if type(rec) is not dict:
        return
    if agent == "claude":
        msg = rec.get("message")
        if type(msg) is not dict or type(msg.get("content")) is not list:
            return
        for block in msg["content"]:
            if type(block) is not dict:
                continue
            if rec.get("type") == "assistant" and block.get("type") == "tool_use":
                yield "call", call_id(block.get("id"), path), "unknown", "unknown"
            elif rec.get("type") == "user" and block.get("type") == "tool_result":
                error = block.get("is_error")
                status = ("tool_failed" if error else "tool_succeeded") if type(error) is bool else "unknown"
                yield "result", call_id(block.get("tool_use_id"), path), status, "claude_tool_result"
    else:
        item = rec.get("payload", rec)
        if type(item) is not dict:
            return
        kind = item.get("type")
        if kind in _CODEX_CALLS:
            tool = item.get("name")
            shell = kind == "local_shell_call" or (type(tool) is str and tool in SHELL_TOOLS - {"exec"})
            yield "call", call_id(item.get("call_id"), path), "unknown", "codex_shell" if shell else "unknown"
        elif kind in ("function_call_output", "custom_tool_call_output", "local_shell_call_output"):
            status, source = _codex_result_status(item)
            yield "result", call_id(item.get("call_id"), path), status, source


def _codex_call(item: dict, ptype: str) -> tuple:
    """(tool, [(kind, command, paths)], workdir) for one Codex tool call."""
    tool = item.get("name")
    if type(tool) is not str:
        tool = ""
    if ptype == "local_shell_call":
        tool = tool or "local_shell"
        action = item.get("action")
        if type(action) is not dict:
            action = {}
        call = _argv_call(action.get("command"))
        return tool, [call or (_kind(tool), "", [])], _text(action.get("working_directory"))

    raw = item.get("arguments")
    if raw is None:
        raw = item.get("input")
    args, src = _codex_args(raw)
    calls = []
    if tool in SHELL_TOOLS:
        call = _argv_call(args.get("command"))
        if call is None and type(args.get("cmd")) is str:
            call = ("shell", args["cmd"], [])
        if call is not None:
            calls.append(call)
    if not calls and tool in _PATCH_TOOLS:
        calls.append(("write", "", _patch_paths(src if src is not None else args.get("input"))))
    if not calls and src is not None and (
            tool == "exec" or ("exec_command" in src and tool not in WRITE_TOOLS)):
        calls = _js_calls(src)
    if not calls and tool == "exec":
        for v in args.values():          # a snippet passed inside JSON arguments
            if type(v) is str:
                calls += _js_calls(v)
    if not calls:
        calls.append((_kind(tool), "", _paths_from_input(args)))
    return tool, calls, _text(args.get("workdir"))


def _codex_meta(first) -> tuple:
    """(cwd, timestamp) from a rollout's first line, in either generation:
    {"type": "session_meta", "payload": {...}}, or the bare {"id", "timestamp",
    "instructions"} that the early Rust CLI wrote. Parsed only when needed: the
    instructions make this line long, and most files never need it."""
    rec = _loads(first) if first else None
    if type(rec) is not dict:
        return "", ""
    body = rec.get("payload") if rec.get("type") == "session_meta" else rec
    if type(body) is not dict:
        return "", ""
    ts = body.get("timestamp")
    if type(ts) is not str or not ts:
        ts = rec.get("timestamp")
    return _text(body.get("cwd")), _text(ts)


def _abs(p: str) -> str:
    return p if p and os.path.isabs(p) else ""


def _read_codex(path: str, cursor: dict | None = None) -> Iterator[Action]:
    session = os.path.basename(path).split("-")[-1].split(".")[0]
    if path.endswith(".json"):
        yield from _read_codex_json(path, session)
        return
    lines = _zstd_lines(path) if path.endswith(".zst") else _log_lines(path, cursor)
    cwd = cursor.get("cwd", "") if cursor is not None else ""
    first = None
    meta = cursor.get("meta") if cursor is not None else None
    try:
        for raw in lines:
            if first is None:
                first = raw
                if meta is None:
                    meta = _codex_meta(first)
                    if cursor is not None:
                        cursor["meta"] = meta
            if b'"function_call"' not in raw and b'"custom_tool_call"' not in raw \
               and b'"local_shell_call"' not in raw and b'"turn_context"' not in raw:
                continue
            rec = _loads(raw)
            if type(rec) is not dict:
                continue
            if "payload" in rec:
                item = rec["payload"]
                if type(item) is not dict:
                    continue
                # turn_context's type sits on the envelope, not in the payload;
                # reading it from the payload left every Codex project empty.
                if rec.get("type") == "turn_context" or item.get("type") == "turn_context":
                    c = item.get("cwd")
                    if type(c) is str and c:
                        cwd = c
                        if cursor is not None:
                            cursor["cwd"] = cwd
                    continue
                ts = rec.get("timestamp")
            else:
                # Rust CLI to v0.31: the line is the item. It carries no time of
                # its own, so its actions take the session's start time.
                item = rec
                if meta is None:
                    meta = _codex_meta(first)
                ts = meta[1]
            ptype = item.get("type")
            if type(ptype) is not str or ptype not in _CODEX_CALLS:
                continue
            tool, calls, workdir = _codex_call(item, ptype)
            project = cwd
            if not project:
                if meta is None:
                    meta = _codex_meta(first)
                project = meta[0] or _abs(workdir)
            skip = cursor.get("item", 0) if cursor is not None else 0
            for i, (kind, command, paths) in enumerate(calls):
                if i < skip:
                    continue
                if cursor is not None:
                    cursor["item"] = i + 1
                yield Action(agent="codex", tool=tool, ts=ts, command=command, paths=paths,
                             project=project, session=session, kind=kind,
                             call_id=codex_call_id(item, path, tool, calls))
    finally:
        lines.close()                   # stops zstd at once if the caller stopped early


def _read_codex_json(path: str, session: str) -> Iterator[Action]:
    """The TypeScript CLI's rollout-*.json: {"session": {...}, "items": [...]}."""
    fh = _open_log(path)
    with fh:
        try:
            data = fh.read(_MAX_JSON_FILE + 1)
        except OSError as e:
            raise Unreadable(path, _why(e)) from e
    if len(data) > _MAX_JSON_FILE:
        return
    doc = _loads(data)
    if type(doc) is not dict:
        return
    meta = doc.get("session")
    ts = meta.get("timestamp") if type(meta) is dict else ""
    items = doc.get("items")
    if type(items) is not list:
        return
    for item in items:
        if type(item) is not dict:
            continue
        ptype = item.get("type")
        if type(ptype) is not str or ptype not in _CODEX_CALLS:
            continue
        tool, calls, workdir = _codex_call(item, ptype)
        for kind, command, paths in calls:
            yield Action(agent="codex", tool=tool, ts=ts, command=command, paths=paths,
                         project=_abs(workdir), session=session, kind=kind,
                         call_id=codex_call_id(item, path, tool, calls))


# ----------------------------------------------------------------- public API

def available() -> dict:
    """Which agents left logs on this machine."""
    return {
        "claude": len(_claude_files()),
        "codex": len(_codex_files()),
    }


def read_all(since_days: int | None = None, agents: tuple = ("claude", "codex")) -> Iterator[Action]:
    """Every action, from every log that can be read. A log that cannot be
    read is passed over here; index.py, which caches, needs to know and calls
    the readers directly."""
    work = []
    if "claude" in agents:
        work += [(f, _read_claude) for f in _claude_files(since_days)]
    if "codex" in agents:
        work += [(f, _read_codex) for f in _codex_files(since_days)]
    for f, reader in work:
        try:
            yield from reader(f)
        except Unreadable:
            continue
