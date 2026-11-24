"""What a tool call actually does, cut into units a rule can judge.

The first gate matched rules against the raw command string. Three things
broke because of that, and each one was walked past by a reviewer:

  * An exception matched anywhere in the string. "My agent may email
    cofounder@example.com" unlocked `cat .env | send-mail --to stranger
    # cofounder@example.com`, because the comment contained the address.
  * Text was matched as if it ran. `git commit -m "remove sudo"` was blocked
    by "Never use sudo".
  * Surface tricks hid what ran: `su''do`, `s\\udo`, `$HOME/.ssh`,
    `git -C dir push`, `rm -fr`, a 4,001st character.

So a command becomes units: one per command it runs, quote-aware, comments
removed, variables and `cd` followed, quoted words collapsed the way the shell
collapses them, paths expanded and resolved. Data stays data -- the message
of a commit, the pattern of a grep, the text of an echo, a heredoc written to
a README -- unless it is piped into something that runs it.

This module decides nothing. It describes.
"""

from __future__ import annotations

import base64
import fnmatch
import glob as _glob
import itertools
import json
import os
import re
import shlex
from . import field, record as dataclass

HOME = os.path.expanduser("~")
MAX = 256 * 1024          # past this, a call is too large to read honestly
_KNOWN_DIRS = ("CLAUDE_CONFIG_DIR", "CODEX_HOME", "KYMA_HOME", "XDG_CONFIG_HOME")
MAX_STAGES = 500          # commands in one call (pipes, ;, &&): past this, also too large

SHELLS = {"sh", "bash", "zsh", "dash", "ksh", "fish"}
# Tool names that run a shell command, across agents (Claude Code, Codex, the
# rest). Kept equal to sources.SHELL_TOOLS by test: a name missing here is a
# command the gate reads as "other" and lets through.
SHELL_TOOLS = {"Bash", "Shell", "exec", "shell", "local_shell", "run_command", "execute_command",
               "shell_command", "exec_command", "run_shell_command", "container.exec"}
INTERPRETERS = SHELLS | {"python", "python3", "node", "deno", "bun", "ruby", "perl", "php", "osascript"}
WRAPPERS = {"sudo", "doas", "env", "command", "exec", "nohup", "time", "nice", "ionice", "stdbuf",
            "caffeinate", "timeout", "gtimeout", "xargs", "watch", "then", "do", "else", "elif",
            "if", "while", "until", "!", "{", "}", "(", ")", "eval", "builtin", "setsid", "unbuffer", "coproc",
            "busybox", "toybox"}
# commands whose arguments are text, not actions
DATA_COMMANDS = {"echo", "printf", "man", "which", "whatis", "apropos", "type", "help", "info",
                 "tldr", "whereis", "say"}
GREP_LIKE = {"grep", "egrep", "fgrep", "rg", "ag", "ack", "git-grep"}
# heredoc targets that are prose, so a body written there is data
PROSE = re.compile(r"\.(?:md|markdown|txt|rst|adoc|csv|tsv|log|html?|css|svg)$", re.I)
SCRIPT = re.compile(r"(?:\.(?:sh|bash|zsh|command|ksh)$|/\.git/hooks/[^/]+$|(?:^|/)Makefile$)", re.I)
# Files that hold credentials. Shared by the gate and the findings.
# Where a file runs by itself later, outside any tool call this hook will see.
AUTOSTART = re.compile(r"/(?:LaunchAgents|LaunchDaemons)(?:/|$)|/etc/cron|/\.config/systemd/user(?:/|$)|/\.config/autostart/|"
                       r"/var/spool/cron|(?:^|/)\.git/hooks/[a-z-]+$")
PROFILE = re.compile(r"/\.(?:zshrc|bashrc|bash_profile|zprofile|zshenv|zlogin|profile)$|/fish/config\.fish$")
DEV_SINKS = {"/dev/null", "/dev/stdout", "/dev/stderr", "/dev/tty"}
DB_CLIENTS = {"sqlite3", "psql", "mysql", "mariadb", "mongosh", "mongo", "redis-cli", "clickhouse-client", "cockroach"}

SENSITIVE = re.compile(
    r"(?:^|/)\.env(?:\.(?!(?:example|sample|template|dist)(?:\.|$))[\w.-]+)?$|(?:^|/)[\w-]+\.env$|(?:^|/)id_(?:rsa|ed25519|ecdsa|dsa)$|"
    r"/\.ssh/(?!.*\.pub$)(?!known_hosts$)(?!config$)|/\.aws/credentials$|(?:^|/)\.netrc$|"
    r"(?:^|/)credentials\.json$|(?:^|/)\.pgpass$|(?:^|/)\.npmrc$|(?:^|/)\.pypirc$|"
    r"/\.config/gh/hosts\.yml$|/\.docker/config\.json$|/\.kube/config$|(?:^|/)\.git-credentials$|"
    r"/\.codex/auth\.json$|application_default_credentials\.json$|/Keychains/|/Login Data$|"
    r"\.(?:p12|pfx)$|(?:^|/)[\w.-]*(?:key|priv)[\w.-]*\.pem$|(?:^|/)[\w.-]*private[\w.-]*\.key$|(?:^|/)server\.key$|"
    r"(?:^|/)\.envrc$|(?:^|/)\.dev\.vars$|(?:^|/)config/(?:master|credentials(?:/[\w.-]+)?)\.key$|"
    r"\.tfstate(?:\.backup)?$|/\.gnupg/(?!.*\.conf$)|(?:^|/)service[-_]?account[\w.-]*\.json$")
SENSITIVE_NAMES = [".env", "id_rsa", "id_ed25519", "id_ecdsa", ".netrc", "credentials",
                   "credentials.json", ".pgpass", ".npmrc", ".pypirc", ".envrc", ".dev.vars"]


@dataclass
class Unit:
    tool: str
    kind: str                          # shell, write, read, web, mcp, other
    text: str                          # normalised words, for category and literal matching
    raw: str = ""                      # as written, for display
    paths: list = field(default_factory=list)    # absolute where resolvable
    writes: list = field(default_factory=list)   # paths this unit writes to
    background: bool = False
    data: bool = False                 # an argument-only unit (text, not an action)
    head: str = ""                     # the command it runs, past wrappers
    feeds_code: bool = False           # its output is piped into something that runs it
    delegated: bool = False            # read from a subagent brief: the act comes later
    # "command": the agent's own words. "file": a program on disk it ran.
    # "written": text it is writing. What a program opens is the program's
    # business; what the agent's command opens is the agent reading it.
    origin: str = "command"
    cwd: str = ""                      # the folder it runs in, after any cd before it
    # Too large or too deep to read honestly: the gate asks rather than guess.
    oversize: bool = False
    # What it runs is decided at run time (a program piped in from `rev`, a
    # command word built by $(...)): why, in a few words, or ''.
    opaque: str = ""


# ------------------------------------------------------------------ helpers

_FS = [True]          # False while reading history: describe, never touch today's disk
AUTHORED: set = set()  # files the agent wrote through this hook: running one is still the agent's act
LINKS: dict = {}       # links the agent made: ./s -> sudo


def fnmatch_safe(name: str, pattern: str) -> bool:
    """fnmatch compiles the pattern to a regex. Text from a log can contain
    `[x-t]`, a reversed range, and the compile error must not become a crash."""
    try:
        return fnmatch.fnmatch(name, pattern)
    except re.error:
        return False


import functools  # noqa: E402


@functools.lru_cache(maxsize=4096)
def _real(p: str) -> str:
    if "\x00" in p:
        return p
    try:
        return os.path.realpath(p)
    except OSError:
        return p


def _norm_path(tok: str, cwd: str | None, env: dict) -> str:
    t = tok.strip().strip("'\"")
    if "=@" in t:
        t = t.split("=@", 1)[1]
    if t.startswith("@"):
        t = t[1:]
    if "=" in t and not t.startswith(("/", "~", ".")):
        t = t.split("=", 1)[1]
    t = re.sub(r"\$\{HOME\}|\$HOME", HOME, t)
    t = re.sub(r"\$\{(\w+)\}|\$(\w+)", lambda m: env.get(m.group(1) or m.group(2), m.group(0)), t)
    if t == "~" or t.startswith("~/"):
        t = HOME + t[1:]
    if not t.startswith("/"):
        if not cwd:
            return os.path.normpath(t) if t else t
        t = os.path.join(cwd, t)
    t = os.path.normpath(t)
    if t.startswith("//"):
        t = "/" + t.lstrip("/")
    if not _FS[0]:
        return t                      # history: describe, never touch today's disk
    if re.search(r"[*?\[]", t):
        return _real_prefix(t)        # a glob: fnmatch later, against resolved rule paths
    return _real(t)                   # /tmp -> /private/tmp, links -> their targets


def _real_prefix(pattern: str) -> str:
    """Resolve the literal folders in front of a glob's first wildcard.

    Rule paths are resolved, so a glob must be too, or the same folder has two
    spellings: macOS HOME under /var/folders is /private/var/folders once
    resolved, and `~/.ss?` would never match the rule "Never touch ~/.ssh".
    The wildcard part stays a pattern; only what is fixed is looked up."""
    parts = pattern.split("/")
    for i, part in enumerate(parts):
        if re.search(r"[*?\[]", part):
            fixed = "/".join(parts[:i]) or "/"
            rest = "/".join(parts[i:])
            return os.path.join(_real(fixed), rest)
    return _real(pattern)


def _pathlike(tok: str) -> bool:
    t = tok.strip("'\"")
    if "=@" in t:
        t = t.split("=@", 1)[1]
    if t.startswith("@"):
        t = t[1:]
    if not t or t.startswith("-") and "=" not in t:
        return False
    if t.startswith(("http://", "https://", "git@", "ssh://")):
        return False
    return ("/" in t or t.startswith(("~", ".", "$HOME", "${HOME}", "@/", "@~", "@."))
            or t in SENSITIVE_NAMES)


def _tokens(seg: str) -> list:
    try:
        lex = shlex.shlex(seg, posix=True, punctuation_chars="<>")
        lex.whitespace_split = True
        lex.commenters = ""
        return list(lex)
    except ValueError:
        return seg.split()


def _modify(v: str, op: str) -> str:
    if op in (":l", ",,", "(L)"):
        return v.lower()
    if op in (":u", "^^", "(U)"):
        return v.upper()
    return v


def _expand_vars(tok: str, env: dict) -> str:
    if "$" not in tok:
        return tok
    # ${x:l} ${x,,} ${(L)x}: zsh and bash case modifiers; ${x:-word}: the word when x is unset
    tok = re.sub(r"\$\{(\w+)(:l|:u|,,|\^\^)\}", lambda m: _modify(env[m.group(1)], m.group(2))
                 if m.group(1) in env else m.group(0), tok)
    tok = re.sub(r"\$\{\((L|U)\)(\w+)\}", lambda m: _modify(env[m.group(2)], "(" + m.group(1) + ")")
                 if m.group(2) in env else m.group(0), tok)
    tok = re.sub(r"\$\{(\w+):?-([^}$`]*)\}", lambda m: env.get(m.group(1), m.group(2)), tok)
    return re.sub(r"\$\{(\w+)\}|\$(\w+)",
                  lambda m: env.get(m.group(1) or m.group(2), m.group(0)), tok)


def _globbed(tok: str, cwd: str | None) -> list:
    """`cat .e?v` names .env without saying it."""
    if not re.search(r"[*?\[]", tok):
        return []
    tok = tok.strip("'\"")
    if "=@" in tok:
        tok = tok.split("=@", 1)[1]             # curl -F f=@.?nv uploads the file
    if tok.startswith("@"):
        tok = tok[1:]
    # A shell's `*` never matches a dotfile, and a pattern with no literal
    # start says nothing about any one name: `ls app/*` must not read as `.env`.
    pat = os.path.basename(tok)
    lead = re.match(r"[^*?\[]*", pat).group(0)
    out = [n for n in SENSITIVE_NAMES
           if n.startswith(".") == pat.startswith(".") and len(lead) >= 2 and fnmatch_safe(n, pat)]
    try:
        # `~` first: joined onto the folder the call runs in, ~/app/.?nv would
        # name a folder called ~ there, and match nothing.
        t = re.sub(r"^(?:\$\{HOME\}|\$HOME)(?=/|$)", HOME, tok)
        t = os.path.expanduser(t)
        base = t if t.startswith("/") else os.path.join(cwd or "", t)
        if _FS[0] and (t.startswith("/") or cwd) and _GLOB_BUDGET[0] > 0:
            # Lazily, and only the first 50: `D/*/../*/../*` grows as N**3,
            # and a hook that spends ten seconds listing folders is a hook
            # the host gives up on. A budget per call bounds the words too.
            _GLOB_BUDGET[0] -= 1
            out += list(itertools.islice(_glob.iglob(base), 50))
    except Exception:
        pass
    return out


_GLOB_BUDGET = [64]        # glob expansions left for this call; reset by units_for


class Stopped(Exception):
    """The caller gave up on this reading: stop at the next step, change nothing."""


STOP = [None]              # a threading.Event set when the current reading is abandoned


def _check_stop() -> None:
    ev = STOP[0]
    if ev is not None and ev.is_set():
        raise Stopped()


# ------------------------------------------------------- shell: split and read

import bisect  # noqa: E402

_WORDLINE = re.compile(r"\w+")


def _terminators(lines: list) -> dict:
    """Where each possible heredoc terminator stands: word -> sorted line numbers.

    Searching forward from every `<<WORD` is quadratic: twenty thousand
    unterminated openers took 29 seconds, which is a call the host times out
    on. One pass to index the lines, then a bisect per opener, is linear."""
    idx = {}
    for k, ln in enumerate(lines):
        w = ln.strip()
        if w and _WORDLINE.fullmatch(w):
            idx.setdefault(w, []).append(k)
    return idx


def _next_line(idx: dict, word: str, start: int) -> int:
    at = idx.get(word)
    if not at:
        return -1
    p = bisect.bisect_left(at, start)
    return at[p] if p < len(at) else -1


def _strip_heredocs(command: str) -> str:
    """Keep heredoc bodies that run; drop the ones that are only written."""
    if "<<" not in command or "\n" not in command:
        return command
    lines = command.split("\n")
    ends = _terminators(lines)
    out, i = [], 0
    hd = re.compile(r"<<(-?)\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\2")
    while i < len(lines):
        line = lines[i]
        out.append(line)
        i += 1
        for m in hd.finditer(line):
            word = m.group(3)
            j = _next_line(ends, word, i)
            if j < 0:
                continue
            body = lines[i:j]
            head = line[:m.start()]
            target = re.search(r"(?:>>?|\btee\s+(?:-a\s+)?)\s*['\"]?([^\s'\"<>|;&]+)", head)
            words = re.split(r"\|\||&&|[|;]", head)[-1].split()
            cmd = os.path.basename(words[0]) if words else ""
            prose = (target and PROSE.search(target.group(1))) or \
                    (cmd == "git" and "commit" in words) or (cmd == "cat" and not target)
            if not prose:
                out.extend(body)          # a script, a config, code fed to an interpreter
            i = j + 1
    return "\n".join(out)


def split(command: str) -> list:
    """Quote-aware split into (segment, operator-before). Comments removed.
    A `( subshell )` opening a segment is unwrapped; other parentheses are
    kept, because `os.system('...')` is code, not grouping."""
    segs, buf, op, q = [], [], "", None
    opened = 0
    depth = 0           # inside $( ) <( ) >( ): `S=$(grep x .env | cut -f2)` is one command
    bq = False          # inside backticks, likewise
    i, n = 0, len(command)
    while i < n:
        c = command[i]
        if q:
            buf.append(c)
            if c == "\\" and q == '"' and i + 1 < n:
                buf.append(command[i + 1])
                i += 2
                continue
            if c == q:
                q = None
            i += 1
            continue
        if c in "'\"":
            q = c
            buf.append(c)
            i += 1
            continue
        if c == "\\" and i + 1 < n:
            buf.append(c)
            buf.append(command[i + 1])
            i += 2
            continue
        if c == "`":
            bq = not bq
            buf.append(c)
            i += 1
            continue
        if command.startswith(("$(", "<(", ">("), i):
            depth += 1
            buf.append(command[i:i + 2])
            i += 2
            continue
        if depth or bq:
            if c == "(":
                depth += 1 if depth else 0
            elif c == ")" and depth:
                depth -= 1
            buf.append(c)
            i += 1
            continue
        if c == "|" and buf and buf[-1] == ">":      # `>|` overrides noclobber; it is a redirect
            buf.append(c)
            i += 1
            continue
        # `\ #` is an escaped space glued to `#`: one word, not a comment, to every shell
        if c == "#" and (not buf or buf[-1] in " \t;&|(\n") and not (len(buf) > 1 and buf[-2] == "\\"):
            j = command.find("\n", i)
            i = n if j < 0 else j
            continue
        two = command[i:i + 2]
        if two in ("&&", "||"):
            segs.append(("".join(buf), op))
            buf, op = [], two
            i += 2
            continue
        if c == "&" and (buf and buf[-1] in "<>" or command[i + 1:i + 2] == ">"):
            buf.append(c)
            i += 1
            continue
        if c in ";\n|&":
            if c == "|" and command[i + 1:i + 2] == "&":
                i += 1
            segs.append(("".join(buf), op))
            buf, op = [], c
            i += 1
            continue
        if c == "(" and not "".join(buf).strip():
            opened += 1
            i += 1
            continue
        if c == ")" and opened and buf.count("(") <= buf.count(")"):
            opened -= 1
            i += 1
            continue
        buf.append(c)
        i += 1
    segs.append(("".join(buf), op))
    return [(s.strip(), o) for s, o in segs if s.strip()]


# Commands whose positional arguments are files, even without a slash.
_FILE_ARGS = {"rm", "unlink", "rmdir", "shred", "mv", "cp", "ln", "install", "touch", "tee", "truncate",
              "cat", "less", "more", "head", "tail", "source", ".", "open", "vi", "vim", "nvim", "nano",
              "emacs", "ed", "code", "subl", "ex", "view", "sponge", "chmod", "chown", "chflags", "sed", "perl", "dd", "base64",
              "xxd", "strings", "bat", "wc", "diff", "cmp", "sha256sum", "shasum", "md5", "md5sum", "scp"}
_EDITORS = {"vi", "vim", "nvim", "nano", "emacs", "ed", "code", "subl", "ex", "view", "gvim", "mvim", "red",
            "sponge", "micro", "pico", "joe", "kak", "jed"}
# a shell command handed to a program as a string still runs
_EMBEDDED = re.compile(r"(?:os\.system|os\.popen|subprocess\.(?:run|call|check_call|check_output|Popen|"
                       r"getoutput|getstatusoutput)|execSync|spawnSync|child_process\.exec)\(\s*"
                       r"(\[[^\]]{0,2000}\]|f?(['\"])(.{1,2000}?)\2)")
_CODE_READ = re.compile(r"open\(\s*(?:os\.path\.(?:expanduser|join|abspath)\(\s*)?f?['\"]([^'\"]{1,400})['\"]|readFileSync\(\s*['\"]([^'\"]{1,400})['\"]|"
                        r"Path\(\s*f?['\"]([^'\"]{1,400})['\"]\s*\)\.read_(?:text|bytes)")
_CODE_WRITE = re.compile(r"open\(\s*(?:os\.path\.(?:expanduser|join|abspath)\(\s*)?f?['\"]([^'\"]{1,400})['\"]"
                         r"[^)]{0,80}\)?\s*,\s*f?['\"](?:w|a|x|r\+|wb|ab)|"
                         r"Path\(\s*f?['\"]([^'\"]{1,400})['\"]\s*\)\.(?:write_text|write_bytes|unlink|touch)|"
                         r"(?:writeFileSync|appendFileSync|unlinkSync)\(\s*['\"]([^'\"]{1,400})['\"]")


_DOTENV = re.compile(r"\bload_dotenv\(|\bdotenv_values\(|dotenv['\"]\)\.config\(|\bdotenv\.config\(")
_ASSIGN = re.compile(r"(?m)\b([A-Za-z_]\w*)\s*=\s*(?:Path\(\s*|os\.path\.(?:expanduser|abspath)\(\s*)?"
                     r"f?['\"]([^'\"\n]{1,400})['\"]")
_DEF = re.compile(r"(?m)^\s*(?:def\s+([A-Za-z_]\w*)\s*\(\s*([A-Za-z_]\w*)|"
                  r"(?:function\s+([A-Za-z_$][\w$]*)|(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:function)?)"
                  r"\s*\(\s*([A-Za-z_$][\w$]*))")


def _writes_var(code: str, v: str) -> bool:
    v = re.escape(v)
    return bool(re.search(
        rf"\bopen\(\s*{v}\s*,\s*f?['\"](?:w|a|x|r\+|wb|ab)|\b{v}\.(?:write_text|write_bytes|unlink|touch|rename|replace|chmod)\(|"
        rf"(?:writeFileSync|appendFileSync|unlinkSync|rmSync)\(\s*{v}\b|os\.(?:remove|unlink|rename|replace|chmod)\(\s*{v}\b|"
        rf"shutil\.(?:copy\w*|move)\([^)]*,\s*{v}\s*\)", code))


def _reads_var(code: str, v: str) -> bool:
    v = re.escape(v)
    return bool(re.search(rf"\bopen\(\s*{v}\b|\b{v}\.(?:read_text|read_bytes|open)\(|readFileSync\(\s*{v}\b", code))


_PATH_EXPR = re.compile(
    r"os\.path\.join\(\s*(?P<join>(?:os\.path\.expanduser\(\s*['\"][^'\"\n]*['\"]\s*\)|['\"][^'\"\n]*['\"])"
    r"(?:\s*,\s*['\"][^'\"\n]*['\"])*)\s*\)"
    r"|Path\.home\(\)(?P<home>(?:\s*/\s*['\"][^'\"\n]+['\"])+)"
    r"|Path\(\s*['\"](?P<pbase>[^'\"\n]+)['\"]\s*\)(?P<pparts>(?:\s*/\s*['\"][^'\"\n]+['\"])+)")


def _expr_value(m) -> str:
    q = r"['\"]([^'\"\n]*)['\"]"
    if m.group("join"):
        parts = re.findall(q, m.group("join"))
        return os.path.join(*parts) if parts else ""
    if m.group("home"):
        return os.path.join("~", *re.findall(q, m.group("home")))
    return os.path.join(m.group("pbase"), *re.findall(q, m.group("pparts")))


def code_paths(code: str, cwd, env: dict) -> tuple:
    """What a piece of code reads and writes. A path the code only names, in a
    message or a list, is neither: naming `.env` is not reading it."""
    reads, writes = [], []
    for m in _CODE_READ.finditer(code):
        t = m.group(1) or m.group(2) or m.group(3)
        if t and not t.startswith(("http://", "https://")):
            reads.append(t)
    for m in _CODE_WRITE.finditer(code):
        t = m.group(1) or m.group(2) or m.group(3)
        if t:
            writes.append(t)
    if _DOTENV.search(code):
        reads.append(".env")
    lits = {}
    for m in _ASSIGN.finditer(code):
        if _pathlike(m.group(2)) or "." in m.group(2):
            lits[m.group(1)] = m.group(2)
    for m in _PATH_EXPR.finditer(code):
        val = _expr_value(m)
        if not val:
            continue
        pre, post = code[max(0, m.start() - 40):m.start()], code[m.end():m.end() + 40]
        var = re.search(r"\b([A-Za-z_]\w*)\s*=\s*$", pre)
        if var:
            lits[var.group(1)] = val
        elif re.search(r"open\(\s*$", pre):
            (writes if re.match(r"\s*,\s*f?['\"](?:w|a|x|r\+|wb|ab)", post) else reads).append(val)
        elif re.match(r"\s*\)?\s*\.(?:write_text|write_bytes|unlink|touch)\(", post):
            writes.append(val)
        elif re.match(r"\s*\)?\s*\.(?:read_text|read_bytes|open)\(", post):
            reads.append(val)
    for v, t in lits.items():
        if _writes_var(code, v):
            writes.append(t)
        elif _reads_var(code, v):
            reads.append(t)
    # def rep(f, a, b): ... open(f, "w") ...   then   rep("NOTES.md", ...)
    for m in _DEF.finditer(code):
        fn = m.group(1) or m.group(3) or m.group(4)
        par = m.group(2) or m.group(5)
        if not fn or not par:
            continue
        body = code[m.end():m.end() + 1500]
        if not _writes_var(body, par):
            continue
        for c in re.finditer(rf"\b{re.escape(fn)}\(\s*(?:f?['\"]([^'\"\n]{{1,400}})['\"]|([A-Za-z_]\w*))", code[m.end():]):
            t = c.group(1) or lits.get(c.group(2) or "")
            if t:
                writes.append(t)
    norm = lambda xs: list(dict.fromkeys(_norm_path(x, cwd, env) for x in xs if x))
    return norm(reads), norm(writes)


_HIDES = re.compile(r"chr\(|fromhex|b64decode|atob\(|Buffer\.from|rot_?13|::\s*-1|reverse|fromCharCode|\.join\(|"
                    r"['\"]\s*%\s*[('\"]|\.format\(|['\"]\s*\+\s*['\"]|['\"] +['\"]|\.(?:lower|upper|toLowerCase)\(")


def reveal(code: str) -> str:
    """guard.reveal, only for code that builds strings: chr codes, hex, joins..."""
    if not _HIDES.search(code):
        return code
    from .guard import reveal as _r
    return _r(code)


def _code_units(code: str, runner: str, tool: str, cwd, env: dict, depth: int) -> list:
    """A heredoc of python, node, SQL...: one unit of code, not lines of shell.
    Read as shell, a python string like "At 60%, skip" became the `at` scheduler."""
    if len(code) > MAX:
        return [Unit(tool, "shell", runner, head=runner, oversize=True)]
    code = reveal(code)
    units = []
    if depth < 3:
        for inner in _embedded(code):
            units.extend(shell_units(inner, tool, cwd, False, depth + 1))
    reads, writes = code_paths(code, cwd, env)
    text = (runner + " " + " ".join(code.split()))[:MAX]
    units.append(Unit(tool, "shell", text, raw=code, paths=list(dict.fromkeys(reads + writes)),
                      writes=writes, head=runner))
    return units


_HD = re.compile(r"(?<!<)<<(-?)\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\2")
_HD_TOKEN = re.compile(r"^KYMAHEREDOC(\d+)$")
_CODE_SHEBANG = re.compile(r"#!\s*\S*(?:/|env\s+(?:-\S+\s+)*)(?:python[\d.]*|node|deno|bun|ruby|perl|php)\b")
_SHELL_SHEBANG = re.compile(r"#!\s*\S*(?:/|env\s+(?:-\S+\s+)*)(?:ba|z|k|da)?sh\b")
_RUN_VIA = {"uv", "poetry", "pipenv", "pdm", "hatch", "rye", "conda", "mamba", "micromamba", "npx", "bunx",
            "pnpx", "docker", "podman", "kubectl", "nix-shell", "ssh"}


def _runner(words: list):
    """The program that will execute what is fed to these words, if any."""
    clean = [w.strip("'\"") for w in words]
    h, at = _head(clean)
    if h in INTERPRETERS or h in DB_CLIENTS:
        return h
    if h in _RUN_VIA:
        for w in clean[at + 1:]:
            b = os.path.basename(w).lower()
            if b in INTERPRETERS or b in DB_CLIENTS:
                return b
        if h == "ssh":
            return "sh"                 # the far side runs it as shell
    return None


def _heredoc_kind(line: str, m, body: list):
    before, after = line[:m.start()], line[m.end():]
    seg_before = re.split(r"\|\||&&|[|;]", before)[-1]
    downstream = re.split(r"\|\||&&|;", after)[0]
    words = seg_before.split()
    head = _head([w.strip("'\"") for w in words])[0] if words else ""
    runner = _runner(words)
    if runner is None:
        for part in downstream.split("|")[1:]:
            runner = _runner(part.split())
            if runner:
                break
    if runner in SHELLS:
        return ("shell", None)
    if runner:
        return ("code", runner)
    if head in ("git", "gh", "hub", "glab"):
        return None                     # a commit message or an issue body is text
    t = re.search(r"(?:^|\s)[\d&]?>>?\|?\s*['\"]?([^\s'\"<>|;&]+)|\btee\s+(?:-a\s+)?['\"]?([^\s'\"<>|;&]+)",
                  seg_before + " " + downstream)
    target = (t.group(1) or t.group(2)) if t else ""
    first = body[0] if body else ""
    if target and (SCRIPT.search(target) or AUTOSTART.search(target) or PROFILE.search(target)
                   or _SHELL_SHEBANG.match(first)):
        return ("script", target)
    if target:
        return ("text", target)         # judged by where it goes; kept in case this command runs it
    return None                         # text printed, not written


def _heredocs(command: str, start: int = 0):
    """Lift heredoc bodies out of a command, each judged as what it is.

    -> (command, bodies). A KYMAHEREDOC<n> token marks where body n was, so it
    is judged in place, after any `cd` before it. Kinds: "shell" (a shell runs
    it now), "code" (python, node, SQL... runs it now), "script" (a shell
    script being written: judged as what it will run). Text is dropped."""
    if "<<" not in command or "\n" not in command:
        return command, []
    lines = command.split("\n")
    ends = _terminators(lines)
    out, bodies, i = [], [], 0
    while i < len(lines):
        line = lines[i]
        i += 1
        marks = []
        for m in _HD.finditer(line):
            word = m.group(3)
            j = _next_line(ends, word, i)
            if j < 0:
                continue
            body = lines[i:j]
            kind = _heredoc_kind(line, m, body)
            if kind:
                bodies.append((kind[0], "\n".join(body), kind[1]))
                marks.append((m.end(), start + len(bodies) - 1))
            i = j + 1
        for pos, n in reversed(marks):
            line = f"{line[:pos]} KYMAHEREDOC{n} {line[pos:]}"
        out.append(line)
    return "\n".join(out), bodies


_NODE_ARGV = re.compile(r"\b(?:execFileSync|execFile|spawnSync|spawn|execa|execaSync|fork)\(\s*['\"`]([^'\"`]{1,200})['\"`]"
                        r"\s*,\s*\[([^\]]{0,2000})\]")
_BARE_EXEC = re.compile(r"(?<![.\w])(?:exec|execSync|system|run|call|check_call|check_output|Popen)\(\s*"
                        r"(\[[^\]]{0,2000}\]|f?(['\"`])(.{1,2000}?)\2)")
_LIST_VAR = re.compile(r"(?:^|[;\n])\s*(\w+)\s*=\s*(\[[^\]]{0,2000}\])")
_VAR_CALL = re.compile(r"(?:subprocess\.)?(?:run|call|check_call|check_output|Popen)\(\s*(\w+)\s*[,)]")


def _embedded(text: str) -> list:
    out = [m.group(1) for m in re.finditer(r'do\s+shell\s+script\s+"((?:[^"\\]|\\.){1,2000})"', text)]
    # execFileSync('git', ['push']) and spawn('sudo', [...]): the command and its argv apart
    for m in _NODE_ARGV.finditer(text):
        parts = [m.group(1)] + re.findall(r"['\"`]([^'\"`]*)['\"`]", m.group(2))
        out.append(" ".join(shlex.quote(x) for x in parts))
    # const {exec} = require('child_process'); exec('sudo ls')  /  from subprocess import run
    if re.search(r"child_process|from\s+subprocess\s+import|import\s+subprocess", text):
        for m in _BARE_EXEC.finditer(text):
            arg = m.group(1)
            if arg.startswith("["):
                parts = re.findall(r"['\"]([^'\"]*)['\"]", arg)
                if parts:
                    out.append(" ".join(shlex.quote(x) for x in parts))
            elif m.group(3):
                out.append(m.group(3))
        # cmd = ["sudo", "chown", ...]; subprocess.run(cmd)
        lists = {m.group(1): m.group(2) for m in _LIST_VAR.finditer(text)}
        for m in _VAR_CALL.finditer(text):
            if m.group(1) in lists:
                parts = re.findall(r"['\"]([^'\"]*)['\"]", lists[m.group(1)])
                if parts:
                    out.append(" ".join(shlex.quote(x) for x in parts))
    for m in _EMBEDDED.finditer(text):
        arg = m.group(1)
        if arg.startswith("["):
            parts = re.findall(r"['\"]([^'\"]*)['\"]", arg)
            if parts:
                out.append(" ".join(shlex.quote(x) for x in parts))
        elif m.group(3):
            out.append(m.group(3))
    return out


def _current_branch(cwd: str) -> str:
    if not _FS[0]:
        return ""
    cur = cwd
    while True:
        head = os.path.join(cur, ".git", "HEAD")
        if os.path.isfile(head):
            try:
                with open(head) as fh:
                    ref = fh.read().strip()
            except OSError:
                return ""
            return ref.rsplit("/", 1)[-1] if ref.startswith("ref:") else ""
        parent = os.path.dirname(cur)
        if parent == cur:
            return ""
        cur = parent


def _head(words: list, stop_env: bool = False):
    """The command a segment runs, past wrappers, env assignments and flags."""
    i = 0
    while i < len(words):
        w = words[i]
        base = os.path.basename(w).lower()      # macOS: `SUDO` runs sudo
        if stop_env and base in ("env", "genv"):
            return base, i
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", w):
            i += 1
            continue
        # The command inside a shell construct is the act: `f() { sudo x; }`,
        # `function f { ... }`, `case $1 in a) sudo x;; esac`. Read as written,
        # each of these hid its command behind `f()`, `function` or `case`.
        if re.fullmatch(r"[A-Za-z_][\w:.-]*\(\)\{?", w):
            i += 1
            continue
        if base == "function" and i + 1 < len(words):
            i += 2
            continue
        if base == "case":
            j = i + 1
            while j < len(words) and words[j] != "in":
                j += 1
            i = j + 1
            continue
        if re.fullmatch(r"\(?[^()$`\s]+\)", w):
            i += 1                       # a case pattern: `logs)`, `*)`
            continue
        if base in WRAPPERS:
            i += 1
            # skip the wrapper's own flags (sudo -u x, timeout 5, nice -n 5)
            while i < len(words) and (words[i].startswith("-") or
                                      (base in ("timeout", "gtimeout") and re.match(r"^\d", words[i]))):
                if (words[i] in ("-u", "-g", "-C") or (words[i] == "-p" and base != "command") or
                    (words[i] == "-n" and base in ("nice", "ionice"))) and i + 1 < len(words):
                    i += 1
                i += 1
            continue
        return base, i
    return "", len(words)


def _env_split(text: str, env: dict) -> list | None:
    """GNU env -S splits argv, not shell code. Unknown expansion stays opaque."""
    args, word, quote, started, i = [], [], "", False, 0
    escapes = {"f": "\f", "n": "\n", "r": "\r", "t": "\t", "v": "\v"}
    while i < len(text):
        if i % 1024 == 0:
            _check_stop()
        c = text[i]
        if c in "'\"" and (not quote or quote == c):
            quote = "" if quote else c
            started = True
        elif c.isspace() and not quote:
            if started:
                args.append("".join(word))
            word, started = [], False
        elif c == "#" and not started:
            break
        elif c == "\\" and (quote != "'" or text[i + 1:i + 2] in ("\\", "'")):
            i += 1
            if i == len(text):
                return None
            c = text[i]
            if c == "c":
                if quote == '"':
                    return None
                break
            if c == "_" and quote != '"':
                if started:
                    args.append("".join(word))
                word, started = [], False
            elif c in escapes or c in "\"#$'\\_":
                word.append(escapes.get(c, " " if c == "_" else c))
                started = True
            else:
                return None
        elif c == "$" and quote != "'":
            match = re.match(r"\$\{([A-Za-z_]\w*)\}", text[i:])
            if not match or match.group(1) not in env:
                return None
            value = env[match.group(1)]
            if value:
                word.append(value)           # env does not split whitespace in the value
                started = True
            i += len(match.group(0)) - 1
        else:
            word.append(c)
            started = True
        i += 1
    if quote:
        return None
    if started:
        args.append("".join(word))
    return args


def _env_command(words: list, env: dict, cwd) -> tuple:
    """Remove env's own options and expand -S before any rule reads the act."""
    options = {"argv0": "a", "chdir": "C", "unset": "u", "split-string": "S",
               "ignore-environment": "i", "null": "0", "debug": "v", "help": "help",
               "version": "version", "default-signal": "signal", "ignore-signal": "signal",
               "block-signal": "signal", "list-signal-handling": "v",
               "quoting-style": "q", "env0-from": "file"}
    directory, changed, steps = cwd, False, 0
    while True:
        head, at = _head(words, stop_env=True)
        if head not in ("env", "genv"):
            return words, directory if changed else None, ""
        incoming = dict(env)
        for token in words[:at]:
            if re.match(r"^[A-Za-z_]\w*=", token):
                key, value = token.split("=", 1)
                incoming[key] = value
        rest, i, layer_cwd = list(words[at + 1:]), 0, directory
        while i < len(rest) and rest[i].startswith("-") and rest[i] != "-":
            _check_stop()
            steps += 1
            if steps > MAX_STAGES:
                return words, None, "too many env options"
            token = rest[i]
            if token == "--":
                i += 1
                break
            if token.startswith("--"):
                name, equal, value = token[2:].partition("=")
                matches = [k for k in options if k.startswith(name)]
                name = name if name in options else matches[0] if len(matches) == 1 else ""
                flags = [(options.get(name, "?"), value if equal else None)]
            else:
                flags, j = [], 1
                while j < len(token):
                    flag = token[j]
                    value = (token[j + 1:] or None) if flag in "aCuSP" else None
                    flags.append((flag, value))
                    if flag in "aCuSP":
                        break
                    j += 1
            i += 1
            for flag, value in flags:
                if flag in ("a", "C", "u", "S", "P", "q", "file") and value is None:
                    if i == len(rest):
                        return words, None, "an env option without its value"
                    value, i = rest[i], i + 1
                if flag == "S":
                    split_args = _env_split(value, incoming)
                    if split_args is None:
                        return words, None, "an env split string with unknown expansion or invalid syntax"
                    # These characters came from env's argv splitter. They are
                    # literal arguments, unlike operators in the outer shell.
                    split_args = [shlex.quote(v) if v in ("<", ">", ">>", "<<", "<<<", "&>",
                                                         "|", "||", "&", "&&", ";") else v
                                  for v in split_args]
                    rest, i = split_args + rest[i:], 0
                elif flag == "C":
                    directory, changed = _norm_path(value, layer_cwd, incoming), True
                elif flag in ("help", "version"):
                    return words[:at] + ["env", "--" + flag], None, ""
                elif flag == "file":
                    return words, None, "an environment loaded from a file"
                elif flag not in ("a", "u", "P", "q", "i", "0", "v", "signal"):
                    return words, None, "an unknown env option"
        if rest[i:i + 1] == ["-"]:
            i += 1
        assignments = []
        while i < len(rest) and "=" in rest[i]:
            # GNU accepts names that the shell assignment grammar does not.
            # Keep shell names for downstream -c expansion; neither is an act.
            if re.match(r"^[A-Za-z_]\w*=", rest[i]):
                assignments.append(rest[i])
            i += 1
        if not rest[i:]:
            return words[:at] + ["env"], None, ""
        words = words[:at] + assignments + rest[i:]
        steps += 1
        if steps > MAX_STAGES:
            return words, None, "too many nested env wrappers"


# `sudo -l` or `sudo --version` asks about privilege without taking it. The
# gate and the findings both read this, so they cannot disagree about it.
PRIV_WRAP = {"sudo", "doas", "pkexec"}
_PRIV_INFO = {"-V", "--version", "-h", "--help", "-l", "--list", "-k", "-K",
              "--reset-timestamp", "--remove-timestamp"}


def priv_info_only(words: list) -> bool:
    for i, w in enumerate(words):
        if os.path.basename(w).lower() in PRIV_WRAP:
            rest = words[i + 1:]
            return bool(rest) and all(x in _PRIV_INFO for x in rest)
    return False


# A subagent brief says what the next agent will do. "Run sudo chown" in it is
# an instruction; "`.env`" is a mention and "do not run git push" a refusal.
# Reading every backticked span as a command held briefs that merely named a
# file, so only a verb that orders an act counts, and never inside a negation.
_INSTRUCTED = re.compile(r"(?i)\b(?:run|execute|exec|invoke)\s+(?:the\s+)?(?:command\s+)?[`'\"]?([^`'\"\n;]{2,300})")
_NEGATED = re.compile(r"(?i)\b(?:not|never|no|avoid|without|nor|cannot|can'?t|don'?t|won'?t|mustn'?t"
                      r"|shouldn'?t|instead\s+of|rather\s+than|unless|except)\b")


def _instructions(text: str) -> list:
    out = []
    text = text[:MAX]
    for m in _INSTRUCTED.finditer(text):
        clause = re.split(r"[.!?;\n]", text[:m.start()])[-1]
        if _NEGATED.search(clause):
            continue
        span = re.split(r"\.(?:\s|$)", m.group(1))[0].strip().rstrip(".,")
        if span:
            out.append(span)
    return out


def _canon(words: list, head: str, at: int) -> list:
    """Spell equivalent forms one way: `rm -fr` and `rm -r -f` are `rm -rf`."""
    w = list(words)
    if head == "rm":
        flags = "".join(x[1:] for x in w[at + 1:] if x.startswith("-") and not x.startswith("--"))
        longs = {x for x in w[at + 1:] if x.startswith("--")}
        r = "r" in flags or "R" in flags or "--recursive" in longs
        f = "f" in flags or "--force" in longs
        rest = [x for x in w[at + 1:] if not x.startswith("-")]
        w = w[:at + 1] + (["-rf"] if r and f else ["-r"] if r else ["-f"] if f else []) + rest
    elif head in ("npm", "pnpm", "yarn", "bun"):
        args, _ = package_args(w[at + 1:], None, {})
        w = w[:at + 1] + args
    elif head == "git":
        # git -C dir / -c k=v / --git-dir=x before the subcommand
        j, out = at + 1, w[:at + 1]
        while j < len(w):
            x = w[j]
            if x in ("-C", "-c", "--git-dir", "--work-tree", "--namespace") and j + 1 < len(w):
                j += 2
                continue
            if x.startswith("--git-dir=") or x.startswith("--work-tree=") or x.startswith("-c") and len(x) > 2:
                j += 1
                continue
            break
        rest = w[j:]
        if rest[:1] == ["push"] and any(a in ("-f", "--force", "--force-with-lease") or
                                         a.startswith("--force") or a.startswith("+") for a in rest[1:]):
            rest = rest + ["--force"]
        w = out + rest
    return w


def _substitutions(seg: str) -> list:
    """$(...), `...`, <(...) and >(...) run before the command around them."""
    out, i, n = [], 0, len(seg)
    single = double = False
    while i < n:
        c = seg[i]
        if c == "\\" and not single:
            i += 2
            continue
        if c == "'" and not double:
            single = not single
            i += 1
            continue
        if c == '"' and not single:
            double = not double
        if single:
            i += 1
            continue
        if seg.startswith("$(", i) or seg.startswith("<(", i) or seg.startswith(">(", i):
            depth, j = 1, i + 2
            while j < n and depth:
                if seg[j] == "(":
                    depth += 1
                elif seg[j] == ")":
                    depth -= 1
                j += 1
            out.append(seg[i + 2:j - 1])
            i = j
            continue
        if seg[i] == "`":
            j = seg.find("`", i + 1)
            if j > i:
                out.append(seg[i + 1:j])
                i = j + 1
                continue
        i += 1
    return [x for x in out if x.strip() and not x.startswith("(")]


def _match_brace(text: str, at: int) -> int:
    """Index of the `}` closing the `{` at `at`, or -1."""
    depth, q, i = 0, None, at
    while i < len(text):
        c = text[i]
        if q:
            if c == "\\" and q == '"':
                i += 2
                continue
            if c == q:
                q = None
        elif c in "'\"":
            q = c
        elif c == "\\":
            i += 2
            continue
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


_FUNC_ANY = re.compile(r"(?:^|(?<=[;&|\s(]))(?:function\s+)?([A-Za-z_][\w-]*)\s*\(\)\s*\{|"
                       r"(?:^|(?<=[;&|\s(]))function\s+([A-Za-z_][\w-]*)\s*\{")
_FUNC = re.compile(r"(?m)^[ \t]*(?:function[ \t]+)?([A-Za-z_][\w-]*)[ \t]*\(\)[ \t]*\{|^[ \t]*function[ \t]+([A-Za-z_][\w-]*)[ \t]*\{")
_DISPATCH = re.compile(r'(?ms)^[ \t]*case[ \t]+"?\$\{?1(?::-[^}]*)?\}?"?[ \t]+in[ \t]*$(.*?)^[ \t]*esac\b')


def _dispatch_slice(body: str, args: list) -> str:
    """The part of a script that this invocation runs.

    `./ctl logs 40` runs the `logs)` branch of a `case "$1"`, and the
    functions it calls, not every function in the file. Judging the whole
    file held `logs` for a `.env` read that only `switch` makes. Anything
    this cannot follow is judged whole."""
    funcs, top, pos = {}, [], 0
    for m in _FUNC.finditer(body):
        if m.start() < pos:
            continue
        close = _match_brace(body, m.end() - 1)
        if close < 0:
            return body
        top.append(body[pos:m.start()])
        funcs[m.group(1) or m.group(2)] = body[m.end():close]
        pos = close + 1
    top.append(body[pos:])
    top = "".join(top)
    cm = _DISPATCH.search(top)
    if not cm:
        return body                     # a script with no case "$1": judged whole
    arg = args[0].strip("'\"") if args else ""
    if re.search(r"[$`*?\[]", arg):
        return body                     # the branch is chosen at run time: every branch may run
    chosen = default = None
    for am in re.finditer(r"(?ms)^[ \t]*\(?([^)\n]+)\)(.*?)(?:;;|\Z)", cm.group(1)):
        labels = [x.strip().strip("'\"") for x in am.group(1).split("|")]
        if arg and any(x != "*" and fnmatch_safe(arg, x) for x in labels):
            chosen = am.group(2)
            break
        if "*" in labels:
            default = am.group(2)
    code = top[:cm.start()] + "\n" + top[cm.end():] + "\n" + (chosen if chosen is not None else (default or ""))
    seen, queue = set(), [code]
    while queue:
        c = queue.pop()
        for name, fbody in funcs.items():
            if name not in seen and re.search(rf"(?<![\w-]){re.escape(name)}(?![\w-])", c):
                seen.add(name)
                queue.append(fbody)
    return code + "\n" + "\n".join(funcs[n] for n in seen)


def _script_file(words: list, at: int, head: str, cwd: str | None, env: dict, written: dict):
    """`bash fix.sh`, `source x`, `./x.sh`, `python3 x.py`: the file is what runs.

    -> (kind, text, runner) or None. A file written earlier in this same
    command is read from the command, because it is not on disk yet when the
    hook runs: `cat > x.sh <<EOF ... EOF; bash x.sh` used to read nothing."""
    if at >= len(words):
        return None
    cand, runner, rest = None, None, []
    tail = words[at + 1:]
    if head in SHELLS or head in ("source", "."):
        if "-c" in tail or "-n" in tail or "--noexec" in tail:
            return None                  # code given inline, or a syntax check that runs nothing
        pos = [w for w in tail if not w.startswith("-")]
        if pos:
            cand, rest, runner = pos[0], pos[1:], "sh"
    elif head in INTERPRETERS:
        if any(f in ("-c", "-e", "-m", "-", "--eval", "-p") for f in tail[:3]):
            return None
        pos = [w for w in tail if not w.startswith("-")]
        if pos and re.search(r"\.(?:py|js|mjs|cjs|ts|rb|pl|php)$", pos[0]):
            cand, rest, runner = pos[0], pos[1:], head
    elif words[at].startswith(("./", "/", "~/", "../")):
        if re.match(r"/(?:bin|sbin|usr/bin|usr/sbin|usr/libexec|System|Library/Apple)/", words[at]):
            return None                  # the system's own tools, not something the agent wrote
        cand, rest = words[at], tail
    if not cand:
        return None
    path = _norm_path(cand, cwd, env)
    body = written.get(path)
    if body is OPAQUE:
        return "opaque", "", head, True
    if body is None:
        if not _FS[0]:
            return None
        try:
            if not os.path.isfile(path):
                return None
            if os.path.getsize(path) > MAX:
                return "oversize", "", head, True
            with open(path, "rb") as fh:
                raw = fh.read(MAX)
        except (OSError, ValueError):
            return None
        if _native_binary(raw):
            if runner is not None:
                return "opaque", "native executable bytes supplied as source", head, True
            return None                  # executable bytes are not source code
        if b"\x00" in raw:
            # Shells can execute source with NUL bytes. Its interpretation is
            # interpreter-specific, so it must not become an unreadable allow.
            return "opaque", "a script with NUL bytes", head, True
        body = raw.decode("utf-8", "replace")
    if runner is None:                   # run directly: the first line decides
        m = _CODE_SHEBANG.match(body)
        if m:
            runner = re.search(r"(python[\d.]*|node|deno|bun|ruby|perl|php)", body.split("\n", 1)[0]).group(1)
        elif body.startswith("#!") and not _SHELL_SHEBANG.match(body):
            return None
        else:
            runner = "sh"
    disk = path not in written and path not in AUTHORED
    if runner == "sh":
        return ("shell", _dispatch_slice(body, rest), "sh", disk)
    return ("code", body, runner, disk)


# ------------------------------------------------------- what will actually run
#
# A command can hand its real work to something kyma would otherwise never
# read: text piped into a shell, a file fed on stdin, a Makefile recipe, a
# package.json script, the command after find -exec or ssh host. Each is
# resolved to the text it executes, and that text is judged like the agent
# typed it. Unresolvable is not the same as harmless: it is simply not added.

_GIT_GLOBAL_FLAGS = {"--no-pager", "-P", "--paginate", "-p", "--no-optional-locks", "--bare",
                     "--no-replace-objects", "--literal-pathspecs", "--glob-pathspecs", "--noglob-pathspecs",
                     "--icase-pathspecs", "--no-advice"}
_GIT_SUBS = {"push", "commit", "fetch", "pull", "clone", "reset", "rebase", "checkout", "clean", "rm", "mv",
             "stash", "tag", "merge", "remote", "config", "log", "show", "diff", "add", "branch", "status",
             "subtree", "restore", "switch", "cherry-pick", "revert", "am", "apply", "send-email", "request-pull"}
_WATCHED_HEADS = ("sudo", "doas", "pkexec", "su", "git", "curl", "wget", "rm", "crontab", "launchctl", "ssh",
                  "sendmail", "mail", "mailx", "swaks", "msmtp", "osascript", "security", "chmod", "chown",
                  "launchctl", "kyma", "nc", "openssl", "claude", "codex")
_SUBST_WORD = re.compile(r"^(?:\$\((?:which|command\s+-v|type\s+-P)\s+([\w.-]+)\)|`(?:which|command\s+-v)\s+([\w.-]+)`)$")


def _merge_substitutions(words: list) -> list:
    """The tokenizer splits $(which sudo), <(echo x) and `x y` into pieces: rejoin them."""
    merged = []
    for w in words:
        if merged and merged[-1] == "<" and w.startswith("("):
            merged[-1] = "<" + w             # `<` then `(echo x)` is one process substitution
            continue
        merged.append(w)
    out, buf, depth = [], [], 0
    for w in merged:
        if buf or w.startswith("$(") or w.startswith("<("):
            buf.append(w)
            depth += w.count("(") - w.count(")")
            if depth <= 0:
                out.append(" ".join(buf))
                buf, depth = [], 0
            continue
        out.append(w)
    return out + ([" ".join(buf)] if buf else [])


def _normalize(words: list, env: dict, cwd=None, written=None) -> list:
    """Spell a disguised command plainly before its head is read."""
    written = written or {}
    out = []
    for w in _merge_substitutions(words):
        if w in ("$SHELL", "${SHELL}"):
            out.append("sh")
            continue
        if not out and re.fullmatch(r"=[A-Za-z_][\w.-]*", w):
            out.append(w[1:])                          # zsh: =sudo is the path of sudo
            continue
        m = _SUBST_WORD.match(w)
        if m:
            out.append(m.group(1) or m.group(2))       # $(which sudo) runs sudo
            continue
        m = re.fullmatch(r"\$\((?!\()(.+)\)", w, re.S)
        is_program = bool(out) and (re.fullmatch(r"-\w*c", out[-1]) or out[-1] in ("eval", "source", "."))
        if m and not is_program:
            given = None
            for seg, _op in split(m.group(1).strip()):
                given = _produced(_tokens(seg), cwd, env, written, given)
            if given and given.strip() and "\n" not in given.strip() and not re.search(r"[;&|`$<>]", given):
                out.extend(given.split())             # cat $(echo .env) reads .env
                continue
        if " " in w and not out and re.match(r"^[\w./-]+ ", w) and not w.startswith(("$(", "<(")):
            out.extend(w.split())                       # $SUDO holding "sudo -E"
            continue
        out.append(w)
    if out and _FS[0] and out[0].startswith(("./", "/", "../", "~/")):
        try:
            p = _norm_path(out[0], cwd, env)
            if LINKS.get(p) in _WATCHED_HEADS:
                out[0] = LINKS[p]
            elif os.path.islink(p):
                real = os.path.basename(os.path.realpath(p))
                if real in _WATCHED_HEADS:
                    out[0] = real               # ln -s "$(which sudo)" ./s; ./s
        except OSError:
            pass
    for i, w in enumerate(out[:4]):
        # a glob as the command word: /usr/bin/su?o is sudo. Only the command
        # word, the first one past any wrapper: in `rm -rf ~/Documents/*` the
        # `*` is the files to delete, not a program named sudo.
        command_word = all(os.path.basename(x) in WRAPPERS or x.startswith("-") for x in out[:i])
        if re.search(r"[*?\[]", w) and command_word:
            hit = next((h for h in _WATCHED_HEADS if fnmatch_safe(h, os.path.basename(w)) or
                        fnmatch_safe(h, os.path.basename(w).lower())), None)
            if hit:
                out[i] = hit
        if re.fullmatch(r"(?:.*/)?git-([a-z-]+)", w) and w.split("/")[-1][4:] in _GIT_SUBS:
            out[i:i + 1] = ["git", w.split("/")[-1][4:]]        # git-push is git push
            break
    # wrappers that run their arguments: script -q FILE cmd, xcrun [-sdk x] cmd
    if out and os.path.basename(out[0]) == "script":
        k = 1
        while k < len(out) and out[k].startswith("-"):
            k += 2 if out[k] in ("-t", "-T") else 1
        out = out[k + 1:] if len(out) > k + 1 else out
    if out and os.path.basename(out[0]) == "xcrun":
        k = 1
        while k < len(out) and out[k].startswith("-"):
            k += 2 if out[k] in ("-sdk", "--sdk", "--toolchain") else 1
        out = out[k:] or out
    # git's global options and aliases sit before the subcommand
    if out and os.path.basename(out[0]) == "git":
        alias, k = {}, 1
        while k < len(out):
            x = out[k]
            if x in _GIT_GLOBAL_FLAGS or x.startswith("--exec-path") or x.startswith("--git-dir=") \
                    or x.startswith("--work-tree=") or x.startswith("--namespace="):
                k += 1
                continue
            if x in ("-C", "--git-dir", "--work-tree", "--namespace") and k + 1 < len(out):
                k += 2
                continue
            if x == "-c" and k + 1 < len(out):
                m = re.match(r"alias\.([\w-]+)=(.+)", out[k + 1])
                if m:
                    alias[m.group(1)] = m.group(2).lstrip("!").split()
                k += 2
                continue
            break
        rest = out[k:]
        if rest and rest[0] in alias:
            rest = alias[rest[0]] + rest[1:]
        out = [out[0]] + rest
    return out


OPAQUE = "\x00opaque"          # written in this call by something whose output kyma cannot know


def _native_binary(raw: bytes) -> bool:
    """ELF and Mach-O signatures, including universal Mach-O executables."""
    if raw.startswith(b"\x7fELF"):
        if len(raw) < 16 or raw[4] not in (1, 2) or raw[5] not in (1, 2) or raw[6] != 1 \
                or raw[9:16] != b"\x00" * 7:
            return False
        size, phsize = (52, 32) if raw[4] == 1 else (64, 56)
        if len(raw) < size:
            return False
        order = "little" if raw[5] == 1 else "big"
        value = lambda start, end: int.from_bytes(raw[start:end], order)
        at = 40 if raw[4] == 1 else 52
        phoff = value(28, 32) if raw[4] == 1 else value(32, 40)
        count = value(at + 4, at + 6)
        # A short magic prefix can still be executable shell source. Require
        # the real header and a bounded program table with a loadable segment.
        return value(16, 18) in (2, 3) and value(20, 24) == 1 and value(at, at + 2) == size \
            and value(at + 2, at + 4) == phsize and count > 0 and phoff >= size \
            and phoff + count * phsize <= len(raw) \
            and any(value(i, i + 4) == 1 for i in range(phoff, phoff + count * phsize, phsize))
    return len(raw) >= 28 and raw[:4] in (b"\xfe\xed\xfa\xce", b"\xce\xfa\xed\xfe",
                                        b"\xfe\xed\xfa\xcf", b"\xcf\xfa\xed\xfe", b"\xca\xfe\xba\xbe",
                                        b"\xbe\xba\xfe\xca", b"\xca\xfe\xba\xbf", b"\xbf\xba\xfe\xca")


def _read_text(path: str, written: dict):
    if path in written:
        return None if written[path] is OPAQUE else written[path]
    if not _FS[0]:
        return None
    try:
        if not os.path.isfile(path) or os.path.getsize(path) > MAX:
            return None
        with open(path, "rb") as fh:
            raw = fh.read(MAX)
    except (OSError, ValueError):
        return None
    return None if b"\x00" in raw[:4096] else raw.decode("utf-8", "replace")


def _produced(words: list, cwd, env: dict, written: dict, given):
    """The text a pipeline stage writes to stdout, when it is a literal: echo,
    printf, cat FILE, base64 -d. `given` is what the stage before produced."""
    if not words:
        return given
    head = os.path.basename(words[0])
    args = words[1:]
    here = None
    if "<<<" in args:
        i = args.index("<<<")
        here = args[i + 1] if i + 1 < len(args) else ""
        args = args[:i] + args[i + 2:]
    if head == "echo":
        return " ".join(a for a in args if a not in ("-n", "-e", "-E"))
    if head == "printf":
        body = [a for a in args if not a.startswith("-") or a == "-"]
        if not body:
            return ""
        try:
            fmt = body[0].encode().decode("unicode_escape")
        except (UnicodeDecodeError, ValueError):
            fmt = body[0]
        rest = body[1:]
        n = len(re.findall(r"%[^%]", fmt))
        if not n:
            return fmt.replace("%%", "%")
        out = []
        try:
            # printf repeats its format until the arguments run out: printf %s ky ma is kyma
            for k in range(0, max(len(rest), 1), n):
                chunk = rest[k:k + n]
                chunk += [""] * (n - len(chunk))
                out.append(re.sub(r"%[-+ #0-9.]*[dixX]", "%s", fmt) % tuple(chunk))
            return "".join(out)
        except (TypeError, ValueError):
            return " ".join(body)
    if head == "cat":
        files = [a for a in args if not a.startswith("-") and a != "<"]
        if not files:
            return here if here is not None else given
        texts = [_read_text(_norm_path(f, cwd, env), written) for f in files]
        return None if any(t is None for t in texts) else "\n".join(texts)
    if head == "base64" and any(a in ("-d", "-D", "--decode") for a in args):
        src = here if here is not None else given
        if src is None:
            return None
        try:
            return base64.b64decode(re.sub(r"\s", "", src) + "==", validate=False).decode("utf-8", "replace")
        except (ValueError, TypeError):
            return None
    if head in ("tee", "dos2unix"):
        return given
    return None


def _make_recipe(target: str, cwd, written: dict):
    for name in ("GNUmakefile", "makefile", "Makefile"):
        text = _read_text(_norm_path(name, cwd, {}), written)
        if text is None:
            continue
        lines = text.splitlines()
        targets = [l.split(":", 1)[0].strip() for l in lines
                   if re.match(r"^[\w./%-]+(?:\s+[\w./%-]+)*\s*::?(?!=)", l) and not l.startswith("\t")]
        want = target or next((t for t in targets if not t.startswith(".")), "")
        out, on = [], False
        for l in lines:
            if not l.startswith("\t") and re.match(r"^[\w./%-]+(?:\s+[\w./%-]+)*\s*::?(?!=)", l):
                on = want in l.split(":", 1)[0].split()
                continue
            if on and l.startswith("\t"):
                out.append(re.sub(r"^\t[@+-]*", "", l))
            elif on and l.strip() and not l.startswith("\t"):
                on = False
        return "\n".join(out) if out else None
    return None


def _pkg_script(name: str, cwd, written: dict):
    text = _read_text(_norm_path("package.json", cwd, {}), written)
    if not text:
        return None
    try:
        scripts = (json.loads(text) or {}).get("scripts") or {}
    except ValueError:
        return None
    parts = [scripts.get(f"pre{name}"), scripts.get(name), scripts.get(f"post{name}")]
    parts = [p for p in parts if isinstance(p, str)]
    return "\n".join(parts) if parts else None


def package_args(args: list, cwd, env: dict) -> tuple:
    """Separate package options and their values from the verb and script.

    The same reader serves primary parsing and lifecycle expansion, so a
    selector before `run` cannot become its verb or resolve a different file.
    """
    selectors = {"--prefix", "-C", "--cwd", "--dir", "-w", "--workspace", "--filter"}
    values = selectors | {"--cache", "--userconfig", "--registry", "--loglevel", "--script-shell"}
    kept, directory, i = [], cwd, 0
    while i < len(args):
        token = args[i]
        if token == "--":
            kept.extend(args[i:])
            break
        flag, equal, value = token.partition("=")
        if flag in values:
            if not equal:
                if i + 1 >= len(args):
                    kept.append(token)
                    break
                i += 1
                value = args[i]
            if flag in selectors:
                candidates = [_norm_path(value, cwd, env)]
                if flag in ("-w", "--workspace", "--filter"):
                    candidates.append(_norm_path("packages/" + value, cwd, env))
                directory = next((p for p in candidates if os.path.isfile(os.path.join(p, "package.json"))),
                                 candidates[0])
        else:
            kept.append(token)
        i += 1
    return kept, directory


def _runs(segs: list, idx: int, words: list, cwd, env: dict, written: dict):
    """-> (kind, text, runner) that this segment executes beyond its own words, or None."""
    pre = [w for w in words if re.match(r"^[A-Za-z_]\w*=", w)]
    k = 0
    while k < len(words) and (re.match(r"^[A-Za-z_]\w*=", words[k]) or
                              (os.path.basename(words[k]) in WRAPPERS and words[k] not in ("eval", "xargs"))):
        k += 1
        while k < len(words) and words[k].startswith("-") and os.path.basename(words[k - 1]) not in ("eval",):
            k += 1
    words = words[k:]
    if not words:
        return None
    head = os.path.basename(words[0])
    args = words[1:]
    # a program read from stdin: a pipe, a redirect, or a here-string
    if head in INTERPRETERS:
        flags = [a for a in args if a.startswith("-") and not a.startswith(("<", "-<"))]
        skip = {i + 1 for i, a in enumerate(args) if a in ("<", "<<<")}
        pos = [a for i, a in enumerate(args) if not a.startswith("-") and a not in ("<", "<<<") and i not in skip]
        reads_stdin = not pos or pos[0] == "-" or (head in SHELLS and "-s" in flags)
        inline = any(f in ("-c", "-e", "--eval") or (head in SHELLS and not f.startswith("--") and "c" in f[1:])
                     for f in flags)
        if inline and head in SHELLS and pos and not pos[0].startswith(("$(", "<(")):
            # CMD='git push' sh -c '$CMD': the program reads the prefix assignment at run time
            prefix = {w.split("=", 1)[0]: w.split("=", 1)[1].strip("'\"") for w in pre if "=" in w}
            return ("shell", _expand_vars(pos[0], {**env, **prefix}), "sh")   # sh -lc 'x' too
        if reads_stdin and not inline:
            text = None
            if "<" in args:
                i = args.index("<")
                if i + 1 < len(args):
                    text = _read_text(_norm_path(args[i + 1], cwd, env), written)
                    if text is None:
                        return ("opaque", "a program from an unreadable input file", head)
            elif "<<<" in args:
                i = args.index("<<<")
                text = args[i + 1] if i + 1 < len(args) else None
            elif idx > 0 and segs[idx][1] == "|":
                j = idx
                while j > 0 and segs[j][1] == "|":
                    j -= 1
                given = None
                for s, _ in segs[j:idx]:
                    given = _produced(_tokens(s), cwd, env, written, given)
                text = given
                if given is None:
                    # rev, tr, jq, awk... piped into a shell: what it runs is computed, not written
                    return ("opaque", "a program piped in from another command", head)
            if text:
                return ("shell" if head in SHELLS else "code", text, "sh" if head in SHELLS else head)
        # bash -c "$(cat f)" / eval "$(...)" / source <(...): the substitution is the program
        if inline or head in SHELLS:
            for a in args:
                m = re.fullmatch(r"\$\((.+)\)|<\((.+)\)|`(.+)`", a.strip(), re.S)
                if m:
                    inner = m.group(1) or m.group(2) or m.group(3)
                    given = None
                    for s, _ in split(inner):
                        given = _produced(_tokens(s), cwd, env, written, given)
                    if given:
                        return ("shell" if head in SHELLS else "code", given, "sh" if head in SHELLS else head)
    if head in ("eval", "source", "."):
        for a in args:
            m = re.fullmatch(r"\$\((.+)\)|<\((.+)\)|`(.+)`", a, re.S)
            if m:
                inner = m.group(1) or m.group(2) or m.group(3)
                given = None
                for s, _ in split(inner):
                    given = _produced(_tokens(s), cwd, env, written, given)
                if given:
                    return ("shell", given, "sh")
    # launchers that run a recipe or a script by name
    if head in ("make", "gmake"):
        tgt = next((a for a in args if not a.startswith("-") and "=" not in a), "")
        body = _make_recipe(tgt, cwd, written)
        if body:
            return ("shell", body, "sh")
    if head in ("npm", "pnpm", "yarn", "bun") and args:
        pkg_args, pkg_dir = package_args(args, cwd, env)
        pkg_args = [a for a in pkg_args if not a.startswith("-")]
        name = pkg_args[1] if pkg_args[:1] in (["run"], ["run-script"], ["rum"], ["urn"]) and len(pkg_args) > 1 else (
            pkg_args[0] if pkg_args and (pkg_args[0] in ("start", "test", "stop", "restart")
                                       or head in ("yarn", "pnpm", "bun")) else "")
        if name and not name.startswith("-"):
            body = _pkg_script(name, pkg_dir, written)
            if body:
                return ("shell", "cd " + shlex.quote(pkg_dir) + "\n" + body if pkg_dir else body, "sh")
    if head == "uv" and args[:1] == ["run"]:
        rest = [a for a in args[1:] if not a.startswith("-")]
        if rest and re.search(r"\.py$", rest[0]):
            body = _read_text(_norm_path(rest[0], cwd, env), written)
            if body:
                return ("code", body, "python3")
        elif rest:
            return ("shell", " ".join(rest), "sh")
    if head in ("npx", "bunx", "pnpx") and len(args) >= 2 and args[0] in ("tsx", "ts-node", "node"):
        body = _read_text(_norm_path(args[1], cwd, env), written)
        if body:
            return ("code", body, "node")
    if re.fullmatch(r"python[\d.]*", head) and "-m" in args:
        i = args.index("-m")
        if i + 1 < len(args):
            mod = args[i + 1].replace(".", "/")
            for cand in (mod + ".py", mod + "/__main__.py"):
                body = _read_text(_norm_path(cand, cwd, env), written)
                if body:
                    return ("code", body, "python3")
    # commands that carry another command
    if head == "find":
        for flag in ("-exec", "-execdir", "-ok", "-okdir"):
            if flag in args:
                i = args.index(flag)
                found = next((args[j + 1].replace("*", "") for j, a in enumerate(args[:i])
                              if a in ("-name", "-iname") and j + 1 < len(args)), "")
                cmd = []
                for a in args[i + 1:]:
                    if a in (";", r"\;", "+"):
                        break
                    if a != "{}":
                        cmd.append(a)
                    elif found:
                        cmd.append(found)       # find -name '*.env*' -exec cat {} reads .env
                if cmd:
                    return ("shell", " ".join(shlex.quote(c) for c in cmd), "sh")
    if head == "ssh":
        k = 0
        while k < len(args) and args[k].startswith("-"):
            k += 2 if args[k] in ("-p", "-i", "-l", "-o", "-F", "-J", "-L", "-R", "-D", "-W", "-b", "-c", "-E",
                                  "-e", "-m", "-O", "-Q", "-S", "-w") else 1
        rest = args[k + 1:]
        if rest:
            return ("shell", " ".join(rest), "sh")
    if head == "xargs":
        k = 0
        while k < len(args) and args[k].startswith("-"):
            k += 2 if args[k] in ("-I", "-n", "-P", "-L", "-s", "-d", "-E") else 1
        cmd = args[k:] or ["echo"]
        given = None
        if "<<<" in args:
            given = args[args.index("<<<") + 1] if args.index("<<<") + 1 < len(args) else None
            cmd = [c for c in cmd if c != "<<<" and c != given]
        elif idx > 0 and segs[idx][1] == "|":
            j = idx
            while j > 0 and segs[j][1] == "|":
                j -= 1
            for s, _ in segs[j:idx]:
                given = _produced(_tokens(s), cwd, env, written, given)
        repl = next((args[j + 1] for j, a in enumerate(args[:-1]) if a in ("-I", "-J")), None)
        if repl is None:
            repl = next((a[2:] for a in args if a.startswith("-I") and len(a) > 2), None)
        if given and repl:
            line = given.strip().split("\n")[0]
            return ("shell", " ".join(shlex.quote(c.replace(repl, line)) if repl in c else shlex.quote(c)
                                      for c in cmd if c != "<<<"), "sh")
        if given:
            return ("shell", " ".join(shlex.quote(c) for c in cmd + given.split()), "sh")
        if idx > 0 and segs[idx][1] == "|":
            return ("opaque", "arguments xargs reads from another command", "xargs")
    return None


def _note_written(segs, idx, words, at, head, positional, writes, cwd, env, written) -> None:
    """What a write in this call puts in its file, so that running the file
    later in the same call is judged: `printf 'sudo id' > k.sh; sh k.sh`.
    Unknown content is marked, never guessed: running it then needs a person."""
    if head in ("cp", "mv", "install", "ditto") and len(positional) >= 2:
        src = _read_text(_norm_path(positional[0], cwd, env), written)
        dst = _norm_path(positional[-1], cwd, env)
        written.setdefault(dst, OPAQUE if src is None else src)
        return
    if head in ("touch", "mkdir", "rm", "unlink", "rmdir", "chmod", "chown", "ln", "truncate", "shred"):
        return
    plain, k = [], 0
    while k < len(words):
        if words[k] in (">", ">>", "&>", "1>", "2>"):
            k += 2
            continue
        plain.append(words[k])
        k += 1
    given = None
    if idx > 0 and segs[idx][1] == "|":
        j = idx
        while j > 0 and segs[j][1] == "|":
            j -= 1
        for s_, _ in segs[j:idx]:
            given = _produced(_tokens(s_), cwd, env, written, given)
    out = _produced(plain[at:], cwd, env, written, given)
    for w in writes:
        if w not in written:
            written[w] = OPAQUE if out is None else out


# Programs that take a shell command as one of their arguments. Each such
# argument runs, and is read as the command it is.
def _nested(head: str, args: list, cwd, env: dict, written: dict) -> list:
    out = []
    a = [x for x in args]
    if head in ("sqlite3", "duckdb", "spatialite"):
        for x in a:
            m = re.match(r"\s*\.(?:shell|system)\s+(.+)", x, re.S)
            if m:
                out.append(m.group(1))
    elif head in ("vim", "vi", "nvim", "ex", "view", "gvim", "mvim", "evim"):
        for j, x in enumerate(a):
            cmd = a[j + 1] if x in ("-c", "--cmd") and j + 1 < len(a) else x[1:] if x.startswith("+") else None
            if not cmd:
                continue
            for c in cmd.split("|"):
                c = c.strip().lstrip(":")
                m = re.match(r"(?:r(?:ead)?\s*)?!(.+)", c, re.S) or re.match(r"(?:silent\s+)?!(.+)", c, re.S)
                if m:
                    out.append(m.group(1))
                for m in re.finditer(r"\bsystem(?:list)?\(\s*['\"](.+?)['\"]\s*\)", c):
                    out.append(m.group(1))
                m = re.match(r"(?:w(?:rite)?|sav(?:eas)?|x(?:it)?|wq)!?\s+(\S+)", c)
                if m:
                    out.append(f"touch {shlex.quote(m.group(1))}")     # :w FILE writes FILE
    elif head in ("m4",):
        for x in a:
            for m in re.finditer(r"\b(?:e?syscmd)\(\s*(.+?)\)", x, re.S):
                out.append(m.group(1))
    elif head in ("lldb", "gdb"):
        for j, x in enumerate(a):
            if x in ("-o", "--one-line", "-ex", "--eval-command", "-O") and j + 1 < len(a):
                m = re.match(r"\s*(?:platform\s+shell|shell|!)\s*(.+)", a[j + 1], re.S)
                if m:
                    out.append(m.group(1))
    elif head in ("make", "gmake") and any(x in ("/dev/stdin", "-") for x in a):
        if "<<<" in a and a.index("<<<") + 1 < len(a):
            text = a[a.index("<<<") + 1]
            if text.startswith("$"):
                text = text[1:].encode().decode("unicode_escape", "replace")
            out += [ln[1:].lstrip("@-+") for ln in text.split("\n") if ln.startswith("\t")]
    elif head == "trap" and a:
        if not a[0].startswith("-"):
            out.append(a[0])
    elif head in ("screen",) and any(re.fullmatch(r"-d?m\w*", x) for x in a):
        k = 0
        while k < len(a) and a[k].startswith("-"):
            k += 2 if a[k] in ("-S", "-c", "-t", "-L", "-Logfile") else 1
        if k < len(a):
            out.append(" ".join(shlex.quote(x) for x in a[k:]))
    elif head == "tmux" and a and a[0] in ("new-session", "new", "new-window", "neww", "send-keys", "send",
                                            "run-shell", "run", "split-window", "splitw", "respawn-pane"):
        pos = [x for x in a[1:] if not x.startswith("-")]
        if pos:
            out.append(pos[-1] if a[0] not in ("send-keys", "send") else " ".join(p for p in pos if p != "Enter"))
    elif head in ("sandbox-exec", "taskpolicy", "chroot", "flatpak-spawn", "systemd-run", "run-parts", "daemonize",
                  "launchctl") and a:
        if head == "launchctl" and a[0] not in ("submit", "asuser"):
            return out
        k = 0
        takes = {"sandbox-exec": ("-p", "-f", "-n", "-D"), "taskpolicy": ("-c", "-d", "-g", "-t", "-p"),
                 "systemd-run": ("-p", "--unit", "-u", "--property"), "launchctl": ("-l", "-o", "-e")}.get(head, ())
        if head == "launchctl":
            k = 1 if a[0] == "submit" else 2
        while k < len(a) and (a[k].startswith("-") or (head == "chroot" and k == 0)):
            if a[k] == "--":
                k += 1
                break
            k += 2 if a[k] in takes else 1
        if k < len(a):
            out.append(" ".join(shlex.quote(x) for x in a[k:]))
    return [x for x in out if x and x.strip()]


_DEEP = 4096                   # longer than any path the OS will open (PATH_MAX is 1024 on macOS)


def _cd(tgt: str, cwd, env: dict) -> str:
    """Where `cd tgt` lands. A plain name below a folder that is already
    resolved needs no full realpath: only the new last part can be a link, and
    a part that does not exist resolves to itself. Resolving the whole path on
    every `cd` re-walked every folder above it, once per `cd`."""
    plain = cwd and _FS[0] and re.fullmatch(r"[\w.@+-]+", tgt or "") and tgt not in (".", "..") \
        and cwd.startswith("/")
    if plain:
        cand = cwd.rstrip("/") + "/" + tgt
        if not os.path.lexists(cand):
            return cand
        if not os.path.islink(cand):
            return cand if _real(cwd) == cwd else _real(cand)
    return _norm_path(tgt, cwd, env)


def shell_units(command: str, tool: str = "Bash", cwd: str | None = None,
                background: bool = False, _depth: int = 0, _hd: dict | None = None) -> list:
    if "\x00" in command:
        return [Unit(tool, "shell", "", raw=command[:200], opaque="shell source with NUL bytes")]
    # Heredoc bodies by id, shared with every recursion below this one: a
    # heredoc inside $( ) is lifted here and judged inside the substitution.
    hd = dict(_hd or {})
    command = command.replace("\\\n", "")          # `cat .e\<newline>nv` is `cat .env` to the shell
    command, found = _heredocs(command, start=len(hd))
    for k, b in enumerate(found):
        hd[len(_hd or {}) + k] = b
    segs = split(command)
    if len(segs) > MAX_STAGES:
        # 2,000 piped stages took 20 s to read: past this, no honest reading fits the budget
        return [Unit(tool, "shell", "", raw=command[:200], oversize=True)]
    env, units, written = {"HOME": os.path.expanduser("~")}, [], {}
    for k in _KNOWN_DIRS:          # $CLAUDE_CONFIG_DIR/settings.json is the hook settings, spelled by name
        if os.environ.get(k):
            env[k] = os.environ[k]
    if _depth > 3:
        return units
    funcs = {}
    if "(" in command or "function" in command:
        for m in _FUNC_ANY.finditer(command):
            close = _match_brace(command, m.end() - 1)
            if close > 0:
                funcs[m.group(1) or m.group(2)] = command[m.end():close]
    for seg, _op in segs:
        for inner in _substitutions(seg):
            units.extend(shell_units(inner, tool, cwd, background, _depth + 1, hd))
    for idx, (seg, op) in enumerate(segs):
        _check_stop()
        toks = _tokens(seg)
        if "env" in seg and "$" in seg:
            # Shell expansion and env expansion occur at different times. Once
            # quotes are stripped, do not guess which environment supplied -S.
            _, _, problem = _env_command(toks, {}, cwd)
            if problem:
                units.append(Unit(tool, "shell", "", raw=seg, opaque=problem))
        here = [int(_HD_TOKEN.match(w).group(1)) for w in toks if _HD_TOKEN.match(w)]
        words = []
        ifs = env.get("IFS")
        for w in toks:
            if _HD_TOKEN.match(w):
                continue
            e = _expand_vars(w, env)
            if ifs and e != w and re.search(r"[^ \t\n]", ifs):
                # IFS=,; c=tee,-a,RULES.md; $c  -- an unquoted expansion is split on IFS
                words += [x for x in re.split("[" + re.escape(ifs) + "]+", e) if x]
            else:
                words.append(e)
        seg = re.sub(r"\s?KYMAHEREDOC\d+\s?", " ", seg)
        for n in here:
            if n not in hd:
                continue
            kind, body, extra = hd[n]
            if kind == "text":
                written[_norm_path(extra, cwd, env)] = body
                continue
            if kind == "shell":
                units.extend(shell_units(body, tool, cwd, background, _depth + 1))
            elif kind == "code":
                units.extend(_code_units(body, extra, tool, cwd, env, _depth))
            else:
                tgt = _norm_path(extra, cwd, env)
                written[tgt] = body             # if this same command runs it, it is judged there
                if AUTOSTART.search(tgt) or PROFILE.search(tgt):
                    # it will run by itself later, where no hook sees it: judge it now
                    later = shell_units(body, tool, os.path.dirname(tgt) or cwd, False, _depth + 1)
                    for u in later:
                        u.origin = "written"
                    units.extend(later)
        if not words:
            continue
        # NAME=value on its own is an assignment we can follow later
        if all(re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", w) for w in words) or \
                (words[0] == "export" and len(words) > 1):
            for w in words[1:] if words[0] == "export" else words:
                if "=" in w:
                    k, v = w.split("=", 1)
                    env[k] = v.strip("'\"")
            continue
        words = _normalize(words, env, cwd, written)
        before_env = words
        words, env_cwd, env_problem = _env_command(words, env, cwd)
        acted_raw = shlex.join(words) if words != before_env else seg
        if env_problem:
            units.append(Unit(tool, "shell", "env", raw=seg, head="env", opaque=env_problem))
        if env_cwd is not None:
            if _depth >= 3:
                units.append(Unit(tool, "shell", "env", raw=seg, oversize=True))
            else:
                units.extend(shell_units(shlex.join(words), tool, env_cwd, background, _depth + 1, hd))
            continue
        head, at = _head(words)
        said = list(words)                 # before data commands lose their words: what lands in a file
        # f() { git "$@"; }; f push  -- a function call runs its body with these arguments
        if at < len(words) and words[at] in funcs and _depth < 3:
            body = funcs[words[at]]
            args = words[at + 1:]
            expanded_args = " ".join(shlex.quote(a) for a in args)
            body = re.sub(r'"?\$(?:@|\*|\{@\}|\{\*\})"?', lambda _m: expanded_args, body)
            body = re.sub(r'"?\$\{?([1-9])\}?"?', lambda m: shlex.quote(args[int(m.group(1)) - 1])
                          if int(m.group(1)) <= len(args) else "", body)
            units.extend(shell_units(body, tool, cwd, background, _depth + 1, hd))
        # the program itself is chosen at run time: $(rev <<< odus) -n id, ${x:l}, an unknown $c
        if at < len(words) and re.search(r"[$`]", os.path.basename(words[at])) and \
                not re.fullmatch(r"\$\{?\w+\}?=.*", words[at]):
            units.append(Unit(tool, "shell", words[at], raw=seg, head="", opaque="a program named at run time"))
        # what this segment hands its real work to: stdin, a recipe, -exec, ssh...
        if _depth < 3:
            run = _runs(segs, idx, words, cwd, env, written)
            if run:
                kind, text, runner = run
                if kind == "opaque":
                    units.append(Unit(tool, "shell", runner, raw=seg, head=runner, opaque=text))
                else:
                    ran = (shell_units(text, tool, cwd, background, _depth + 1) if kind == "shell"
                           else _code_units(text, runner, tool, cwd, env, _depth + 1))
                    units.extend(ran)
            for inner in _nested(head, words[at + 1:], cwd, env, written):
                units.extend(shell_units(inner, tool, cwd, background, _depth + 1, hd))
        nxt = segs[idx + 1] if idx + 1 < len(segs) else None
        piped_into_code = False
        k = idx + 1
        while k < len(segs) and segs[k][1] == "|":
            nwords = _tokens(segs[k][0])
            nh, nat = _head(nwords)
            nh = os.path.basename(nh)
            if nh in INTERPRETERS:
                args = [a for a in nwords[nat + 1:] if not a.startswith("-") or a == "-"]
                flags = [a for a in nwords[nat + 1:] if a.startswith("-") and a != "-"]
                code_flag = any(("c" in f[1:] and nh in SHELLS) or (nh.startswith("python") and ("c" in f[1:] or "m" in f[1:]))
                                or (nh in ("node", "ruby", "perl") and "e" in f[1:]) for f in flags if not f.startswith("--"))
                piped_into_code = (not code_flag) and (not args or args[0] == "-" or (nh in SHELLS and "-s" in nwords))
                break
            if nh == "base64" and ("-d" in nwords or "--decode" in nwords or "-D" in nwords):
                k += 1
                continue
            if nh in ("tee", "cat", "gunzip", "zcat", "xz", "unxz", "bzip2", "bunzip2", "tr", "dos2unix"):
                k += 1
                continue
            break

        # cd changes where later relative paths point
        if head in ("cd", "pushd"):
            args = [w for w in words[at + 1:] if not re.fullmatch(r"-[LPe@n]+", w)]
            tgt = args[0] if args else "~"
            if re.search(r"[*?\[]", tgt):
                # `cd ~/.cl?ude` lands in the one folder the glob names
                hit = _globbed(tgt, cwd)
                tgt = next((g for g in hit if os.path.isdir(g)), tgt)
            cwd = _cd(tgt, cwd, env)
            if len(cwd) > _DEEP:
                # `cd a; cd a; ...` thousands deep: no real folder is there, and
                # following it costs the square of its depth. Say so instead.
                units.append(Unit(tool, "shell", "cd", raw=seg[:200], oversize=True))
                return units
            units.append(Unit(tool, "shell", "cd " + cwd, raw=seg, paths=[cwd]))
            continue

        script = _script_file(words, at, head, cwd, env, written)
        if script and script[0] == "opaque":
            units.append(Unit(tool, "shell", head, raw=seg, head=head,
                              opaque=script[1] or "a script this same call writes"))
        elif script and (script[0] == "oversize" or _depth >= 3):
            units.append(Unit(tool, "shell", head, head=head, oversize=True))
        elif script:
            kind, text, runner, disk = script
            ran = (shell_units(text, tool, cwd, background, _depth + 1) if kind == "shell"
                   else _code_units(text, runner, tool, cwd, env, _depth))
            for u in ran:
                if disk and u.origin == "command":
                    u.origin = "file"
            units.extend(ran)
        for k in range(min(at + 1, len(words))):
            if re.match(r"^[A-Za-z_]\w*=", words[k]):
                continue
            if words[k].startswith("/"):
                words[k] = os.path.basename(words[k]) or words[k]
            if os.path.basename(words[k]).lower() in WRAPPERS or k == at:
                words[k] = words[k].lower() if words[k].isalpha() else words[k]
        words = _canon(words, head, at)
        # (i) a bare `git push` pushes the branch you are on
        if head == "git" and words[at + 1:at + 2] == ["push"] and cwd:
            pos = [w for w in words[at + 2:] if not w.startswith("-")]
            if len(pos) < 2:
                br = _current_branch(cwd)
                if br:
                    words = words + ([br] if pos else ["origin", br])
        data = False
        if not piped_into_code:
            if head in DATA_COMMANDS:
                # the words are text; a redirect and its target are an action
                kept, k = words[:at + 1], at + 1
                while k < len(words):
                    x = words[k]
                    if x in (">", ">>", "&>", "1>", "2>") and k + 1 < len(words):
                        if words[k + 1] == "|" and k + 2 < len(words):     # >| file: the noclobber override
                            kept += [x, words[k + 2]]
                            k += 3
                            continue
                        kept += [x, words[k + 1]]
                        k += 2
                        continue
                    if x.startswith("-"):
                        kept.append(x)
                    k += 1
                words = kept
                data = True
            elif head in GREP_LIKE or (head == "git" and words[at + 1:at + 2] == ["grep"]):
                # the first positional is the pattern; the rest are where to look
                out, dropped = words[:at + 1], False
                skip_next = False
                for x in words[at + 1:]:
                    if skip_next:
                        skip_next = False
                        continue
                    if x in ("-e", "--regexp", "-f", "--file"):
                        skip_next, dropped = True, True
                        continue
                    if not x.startswith("-") and not dropped and x != "grep":
                        dropped = True
                        continue
                    out.append(x)
                words = out
            elif head == "git" and words[at + 1:at + 2] in (["commit"], ["tag"], ["notes"]):
                out, skip = [], False
                for x in words:
                    if skip:
                        skip = False
                        continue
                    # -m, and any cluster that ends in it: -am, -sm, -qam
                    if x in ("--message", "-F", "--file") or re.fullmatch(r"-[A-Za-z]*m", x):
                        skip = True
                        continue
                    if x.startswith("--message=") or (x.startswith("-m") and len(x) > 2):
                        continue
                    out.append(x)
                words = out

        paths, writes = [], []
        positional = []
        skip_first = head in ("chmod", "chown", "chflags") or (head in ("sed", "perl") and
                                                               not any(w in ("-e", "-f") for w in words))
        for k, x in enumerate(words):
            if k <= at and k != 0:
                continue
            nxt_w = words[k + 1] if k + 1 < len(words) else ""
            if x in (">", ">>"):
                if nxt_w == "|" and k + 2 < len(words):      # >| file
                    nxt_w = words[k + 2]
                elif nxt_w.startswith("|") and len(nxt_w) > 1:
                    nxt_w = nxt_w[1:]                        # >|file: the tokenizer glues the bar on
                if nxt_w.startswith("&") and not re.fullmatch(r"&(?:\d+|-)?", nxt_w):
                    nxt_w = nxt_w[1:]                     # >&file sends both streams to file
                if nxt_w and not re.fullmatch(r"&(?:\d+|-)?", nxt_w) and nxt_w not in DEV_SINKS \
                        and not nxt_w.startswith("/dev/fd/"):
                    writes.append(_norm_path(nxt_w, cwd, env))
                continue
            if x == "<":
                if nxt_w and nxt_w != "<" and not nxt_w.startswith("("):
                    paths.append(_norm_path(nxt_w, cwd, env))   # `done < .env` reads it
                continue
            if x in ("<<", "<<<", "|"):
                continue
            prev = words[k - 1] if k > 0 else ""
            if x == "|" and prev in (">", ">>"):
                continue
            if prev in (">", ">>", "<", "<<", "<<<") or (prev == "|" and k > 1 and words[k - 2] in (">", ">>")):
                continue                                   # a target, a delimiter, a here-string
            if (x.isdigit() or x == "&") and nxt_w in (">", ">>", "<"):
                continue                                   # 2>, &>: a stream number, not a file
            if k > at and not x.startswith("-"):
                positional.append(x)
            if _pathlike(x):
                paths.append(_norm_path(x, cwd, env))
            for g in _globbed(x, cwd):
                paths.append(_norm_path(g, cwd, env))
        if head in _FILE_ARGS:
            files = positional[1:] if skip_first else positional
            for x in files:
                if not _pathlike(x) and re.fullmatch(r"[\w@%+=:,.~-]+", x) and not x.startswith("$"):
                    paths.append(_norm_path(x, cwd, env))
        if head in INTERPRETERS and head not in SHELLS:
            r, w = code_paths(reveal(seg), cwd, env)
            paths += r
            writes += w
        if head in ("awk", "gawk", "mawk", "nawk"):
            # print > "file" inside the program writes the file
            # Read the expanded argument: shell quote concatenation may build the path.
            for m in re.finditer(r'\bprintf?\b(?:"(?:[^"\\]|\\.)*"|[^";}\n])*?>>?\s*"([^"]+)"',
                                 " ".join(words)):
                writes.append(_norm_path(m.group(1), cwd, env))
                paths.append(writes[-1])
        if head in ("tee",):
            writes += [p for p in paths]
        if head in ("cp", "mv", "ln", "install", "rsync") and positional:
            writes.append(_norm_path(positional[-1], cwd, env))   # the destination is the last argument
        if head in ("touch", "mkdir", "truncate", "chmod", "chown", "rm", "unlink", "rmdir", "shred") or \
                head in _EDITORS or (head in ("sed", "perl") and any(x.startswith("-i") or
                                                                     re.match(r"^-\w*i", x) for x in words)):
            writes += [p for p in paths]
        for inner in _embedded(reveal(seg) if head in INTERPRETERS else seg):
            if _depth < 3:
                units.extend(shell_units(inner, tool, cwd, background, _depth + 1, hd))
        if head in INTERPRETERS and "<<<" in words and _depth < 3:
            k = words.index("<<<")
            if k + 1 < len(words):
                units.extend(shell_units(words[k + 1], tool, cwd, background, _depth + 1))
        if _depth < 3:
            raw_words = _tokens(seg)
            rh, rat = _head(raw_words)
            rh = os.path.basename(rh)
            if rh in SHELLS or rh in ("su",):
                for k in range(rat + 1, len(raw_words) - 1):
                    f = raw_words[k]
                    if f.startswith("-") and not f.startswith("--") and "c" in f[1:]:
                        units.extend(shell_units(raw_words[k + 1], tool, cwd, background, _depth + 1, hd))
                        break
            if raw_words and raw_words[0] == "eval" and len(raw_words) > 1:
                units.extend(shell_units(" ".join(raw_words[1:]), tool, cwd, background, _depth + 1, hd))

        if writes:
            _note_written(segs, idx, said, at, head, positional, writes, cwd, env, written)
        text = " ".join(words)
        if head in INTERPRETERS and head not in SHELLS:
            text = reveal(text)              # chr(115)+'udo' is 'sudo' to every rule
        allp = list(dict.fromkeys(paths + writes))
        units.append(Unit(tool, "shell", text, raw=acted_raw, paths=allp, writes=list(dict.fromkeys(writes)),
                          background=background or head in ("nohup", "disown", "setsid")
                          or (nxt is not None and nxt[1] == "&"), data=data, head=head,
                          feeds_code=piped_into_code, cwd=cwd or ""))

        # `echo <base64> | base64 -d | sh` runs the decoded text
        if head in ("echo", "printf") and piped_into_code and len(segs) > idx + 2:
            third = _head(_tokens(segs[idx + 2][0]))[0]
            if third in SHELLS:
                for x in words[at + 1:]:
                    try:
                        dec = base64.b64decode(x, validate=True).decode("utf-8", "replace")
                    except Exception:
                        continue
                    units.extend(shell_units(dec, tool, cwd))
    # a trailing `&` puts the last command in the background
    if units and command.rstrip().endswith("&") and not command.rstrip().endswith("&&"):
        units[-1].background = True
    return units


# --------------------------------------------------------------- any tool call

def _flatten(v, out: list) -> None:
    if isinstance(v, dict):
        for k, x in v.items():
            out.append(str(k))
            _flatten(x, out)
    elif isinstance(v, (list, tuple)):
        for x in v:
            _flatten(x, out)
    elif v is not None:
        out.append(str(v))


def _script_target(path: str, content: str) -> bool:
    return bool(SCRIPT.search(path or "") or PROFILE.search(path or "")) or bool(_SHELL_SHEBANG.match(content or ""))


def history_units(command: str) -> list:
    """Units for a recorded command: described, never resolved against today's disk."""
    _FS[0] = False
    try:
        return shell_units(command[:MAX])
    finally:
        _FS[0] = True


_HEREDOC_OPEN = re.compile(r"<<-?\s*['\"]?(\w+)['\"]?")


def _without_bodies(cmd: str) -> str:
    """The command with every terminated heredoc body cut out, in one pass."""
    if "<<" not in cmd:
        return cmd
    lines = cmd.split("\n")
    ends = _terminators(lines)
    out, i = [], 0
    while i < len(lines):
        line = lines[i]
        m = _HEREDOC_OPEN.search(line)
        j = _next_line(ends, m.group(1), i + 1) if m else -1
        if j < 0:
            out.append(line)
            i += 1
            continue
        out.append(line[:m.start()])
        i = j + 1
    return "\n".join(out)

NOTE_TOOLS = {"TodoWrite", "TodoRead", "ExitPlanMode", "EnterPlanMode", "TaskCreate", "TaskUpdate", "TaskList",
              "TaskGet", "update_plan", "AskUserQuestion"}


_CMD_KEYS = ("command", "cmd", "argv", "args", "script", "input")


def _argv_text(v) -> str:
    if isinstance(v, str):
        return v
    if isinstance(v, (list, tuple)) and v and all(isinstance(x, str) for x in v):
        # an argv, quoted back: ["bash", "-lc", "git push"] is one -lc script, not `git` and `push`
        return shlex.join(v)
    return "\n".join(_strings(v))       # an odd shape: each string read as its own command


def _strings(v, depth: int = 0) -> list:
    if depth > 20:
        return []
    if isinstance(v, str):
        return [v]
    if isinstance(v, dict):
        return [x for y in v.values() for x in _strings(y, depth + 1)]
    if isinstance(v, (list, tuple)):
        return [x for y in v for x in _strings(y, depth + 1)]
    return []


def shell_command_of(tool_input) -> str:
    """The command a shell tool runs, in every shape the agents send it.

    Claude Code: {"command": "..."}. Codex: {"command": ["bash", "-lc", "..."]},
    {"cmd": "..."}, {"action": {"command": [...]}}, a bare string. A shape no
    key here matches is read as every string in it, joined: a command kyma
    cannot find must still be read, never passed as nothing."""
    if isinstance(tool_input, str):
        return tool_input
    if isinstance(tool_input, (list, tuple)):
        return _argv_text(tool_input)
    if not isinstance(tool_input, dict):
        return "" if tool_input is None else str(tool_input)
    for k in _CMD_KEYS:
        v = tool_input.get(k)
        if v not in (None, "", []):
            return _argv_text(v)
    act = tool_input.get("action")
    if isinstance(act, dict):
        return shell_command_of(act)
    return "\n".join(_strings({k: v for k, v in tool_input.items()
                               if k not in ("cwd", "workdir", "timeout", "timeout_ms", "description",
                                            "run_in_background", "justification", "with_escalated_permissions")}))


_PATCH = ("apply_patch", "applypatch", "patch")


def _patch_text(tool: str, tool_input):
    """A Codex patch, in each shape it comes: {"input": patch}, a bare string,
    ["apply_patch", patch], {"command": ["apply_patch", patch]}."""
    v = tool_input
    if isinstance(v, dict):
        cmd = v.get("command")
        if isinstance(cmd, list) and cmd and str(cmd[0]).rsplit("/", 1)[-1] in _PATCH:
            return "\n".join(str(x) for x in cmd[1:])
        if tool not in _PATCH:
            return None
        v = v.get("input") or v.get("patch") or ""
        if not isinstance(v, str) or "*** " not in v:
            return None                  # {"file_path": ...}: the file it writes, read below
    if isinstance(v, list) and v and str(v[0]).rsplit("/", 1)[-1] in _PATCH:
        return "\n".join(str(x) for x in v[1:])
    if isinstance(v, str) and (tool in _PATCH or v.lstrip().startswith("*** Begin Patch")):
        return v
    return None


def _patch_units(tool: str, text: str, cwd) -> list:
    """One write per file the patch touches, and what it adds to a file that
    runs by itself (a profile, a LaunchAgent, a git hook) judged now."""
    from .sources import _patch_paths
    out = []
    added, cur = {}, None
    for ln in text.splitlines():
        m = re.match(r"^\*\*\* (?:Add|Update|Delete) File: *(.+?)\s*$|^\*\*\* Move to: *(.+?)\s*$", ln)
        if m:
            cur = m.group(1) or m.group(2)
            added.setdefault(cur, [])
            continue
        if cur is not None and ln.startswith("+") and not ln.startswith("+++"):
            added[cur].append(ln[1:])
    for raw in _patch_paths(text) or list(added):
        p = _norm_path(raw, cwd, {})
        out.append(Unit(tool, "write", f"{tool} {p}", raw=raw, paths=[p], writes=[p]))
        body = "\n".join(added.get(raw, []))
        if body and (AUTOSTART.search(p) or PROFILE.search(p) or SCRIPT.search(p)) and _script_target(p, body):
            later = shell_units(body, tool, os.path.dirname(p) or cwd)
            for u in later:
                u.origin = "written"
            out += later
    return out or [Unit(tool, "write", f"{tool} patch", raw=text[:200])]


def _js_units(tool: str, src: str, cwd) -> list:
    """Codex's JS exec: await tools.exec_command({cmd: '...'}), patches inside it."""
    from .sources import _js_calls
    out = []
    for kind, cmd, paths in _js_calls(src):
        if kind == "shell" and cmd:
            out += shell_units(cmd, tool, cwd)
        for raw in paths:
            p = _norm_path(raw, cwd, {})
            out.append(Unit(tool, "write", f"{tool} {p}", raw=raw, paths=[p], writes=[p]))
    return out


_JS_EXEC = re.compile(r"\btools\.(?:exec_command|shell_command|apply_patch)\s*\(|\bexec_command\s*\(\s*\{")


_FILE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit", "Read", "Grep", "Glob", "LS", "NotebookRead"}
_PATH_KEYS = ("file_path", "path", "target_file", "filename", "file", "notebook_path")
_BODY_KEYS = ("content", "contents", "text", "code_edit", "data", "body", "new_string")


def normalise(tool: str, tool_input):
    """-> (tool, input) in a shape kyma reads, for another agent's tool, or None.

    Codex write_stdin types into a running shell; Cursor's edit_file,
    read_file, list_dir, delete_file, grep_search, run_terminal_cmd and
    search_replace are Claude Code's Write, Read, LS, rm, Grep, Bash and Edit;
    any tool with a path and a body is a write. Shared with `kyma mcp`."""
    t = str(tool or "")
    inp = tool_input if isinstance(tool_input, dict) else None
    if inp is None or t in _FILE_TOOLS or t in SHELL_TOOLS:
        return None
    leaf = t.split("__")[-1]
    s = lambda k: inp.get(k) if isinstance(inp.get(k), str) else None
    if leaf == "write_stdin" and s("chars") is not None:
        return "Bash", {"command": s("chars")}
    if leaf == "run_terminal_cmd" and s("command") is not None:
        return "Bash", {"command": s("command")}
    if leaf == "edit_file" and s("target_file") is not None and s("code_edit") is not None:
        return "Write", {"file_path": s("target_file"), "content": s("code_edit")}
    if leaf == "read_file" and s("target_file") is not None:
        return "Read", {"file_path": s("target_file")}
    if leaf == "list_dir" and s("relative_workspace_path") is not None:
        return "LS", {"path": s("relative_workspace_path")}
    if leaf == "delete_file" and s("target_file") is not None:
        return "Bash", {"command": "rm -- " + shlex.quote(s("target_file"))}
    if leaf == "grep_search" and s("query") is not None:
        out = {"pattern": s("query")}
        if s("include_pattern"):
            out["glob"] = s("include_pattern")
        return "Grep", out
    if leaf == "move_file" and s("source") is not None and s("destination") is not None:
        return "Bash", {"command": f"mv -- {shlex.quote(s('source'))} {shlex.quote(s('destination'))}"}
    if leaf == "search_files" and s("path") is not None and s("pattern") is not None:
        return "Glob", {"path": s("path"), "pattern": s("pattern")}
    if leaf == "search_replace" and s("file_path") is not None and s("new_string") is not None:
        return "Edit", {"file_path": s("file_path"), "old_string": s("old_string") or "", "new_string": s("new_string")}
    path = next((inp[k] for k in _PATH_KEYS if isinstance(inp.get(k), str) and inp[k].strip()), None)
    if path is None:
        return None
    edits = inp.get("edits")
    if isinstance(edits, list) and edits:
        new = [str(e.get("newText") if e.get("newText") is not None else e.get("new_string") or "")
               for e in edits if isinstance(e, dict)]
        return "Edit", {"file_path": path, "old_string": "", "new_string": "\n".join(new)}
    body = next((inp[k] for k in _BODY_KEYS if isinstance(inp.get(k), str)), None)
    if body is not None:
        return "Write", {"file_path": path, "content": body}
    return None


def begin_call() -> None:
    """One tool call starts: its glob budget covers every reading of it, the
    second reading's forms included, not 64 globs for each of 48 forms."""
    _GLOB_BUDGET[0] = 64
    _IN_CALL[0] = True


_IN_CALL = [False]


def units_for(tool: str, tool_input, cwd: str | None = None) -> list:
    """Every unit a tool call contains. Never raises on odd input shapes."""
    if not _IN_CALL[0]:
        _GLOB_BUDGET[0] = 64
    t = str(tool or "")
    patch = _patch_text(t, tool_input)
    if patch is not None:
        return _patch_units(t, patch, cwd)
    if t in SHELL_TOOLS or t == "js_exec":
        if isinstance(tool_input, dict):
            src = tool_input.get("input") if isinstance(tool_input.get("input"), str) else tool_input.get("code")
        else:
            src = tool_input if isinstance(tool_input, str) else None
        if isinstance(src, str) and _JS_EXEC.search(src):
            return _js_units(t, src, cwd) or [Unit(t, "shell", "", raw=src[:200],
                                                   opaque="code that runs commands kyma could not find")]
    if t in SHELL_TOOLS:
        cmd = shell_command_of(tool_input)
        if isinstance(tool_input, dict):
            cwd = cwd or tool_input.get("cwd") or tool_input.get("workdir") or None
            cwd = cwd if isinstance(cwd, str) else None
            background = bool(tool_input.get("run_in_background"))
        else:
            background = False
        # Past MAX the command itself must be short once its heredoc bodies are
        # set aside: a body is judged on its own terms (data, or code with its
        # own limit), but a quarter megabyte of shell is not read in time.
        if len(cmd) > MAX and len(_without_bodies(cmd)) > MAX:
            return [Unit(t, "shell", "", oversize=True)]
        return shell_units(cmd, t, cwd, background=background)
    if not isinstance(tool_input, dict):
        flat = []
        _flatten(tool_input, flat)
        return [Unit(str(tool), "other", str(tool) + " " + " ".join(flat))]
    if t in ("Write", "Edit", "MultiEdit", "NotebookEdit", "apply_patch", "create_file"):
        path = tool_input.get("file_path") or tool_input.get("notebook_path") or tool_input.get("path") or ""
        p = _norm_path(path, cwd, {}) if path else ""
        content = ""
        for key in ("content", "new_string", "new_source"):
            if isinstance(tool_input.get(key), str):
                content += tool_input[key] + "\n"
        for e in tool_input.get("edits") or []:
            if isinstance(e, dict) and isinstance(e.get("new_string"), str):
                content += e["new_string"] + "\n"
        out = [Unit(t, "write", f"{t} {p}", raw=path, paths=[p] if p else [], writes=[p] if p else [])]
        if content and _script_target(p, content) and (AUTOSTART.search(p) or PROFILE.search(p)):
            # A file that runs by itself (a LaunchAgent, a git hook, a shell
            # profile) is judged now: nothing will ask again when it fires. Any
            # other script is judged when it runs, through this hook, from disk.
            later = shell_units(content, t, os.path.dirname(p) or cwd)
            for u in later:
                u.origin = "written"
            out += later
        elif t == "NotebookEdit" and content:
            lines = [ln[1:] for ln in content.splitlines() if ln.startswith("!")]
            if content.lstrip().startswith(("%%bash", "%%sh", "%%script")):
                lines = content.splitlines()[1:]
            if lines:
                out += shell_units("\n".join(lines), t, cwd)
        return out
    if t in ("Read", "Grep", "Glob", "LS", "NotebookRead"):
        flat, paths = [], []
        for key in ("file_path", "path", "notebook_path"):
            if isinstance(tool_input.get(key), str) and tool_input[key]:
                paths.append(_norm_path(tool_input[key], cwd, {}))
                for g in _globbed(tool_input[key], cwd):
                    paths.append(_norm_path(g, cwd, {}))
        names_only = t == "Glob" or str(tool_input.get("output_mode") or "") in ("files_with_matches", "count")
        for key in ("glob", "pattern", "include"):
            v = tool_input.get(key)
            if isinstance(v, str):
                flat.append(v)
                if names_only:
                    continue                     # it answers which files, not what is in them
                if t != "Grep" or key == "glob":
                    for g in _globbed(v, cwd) or ([v] if v in SENSITIVE_NAMES else []):
                        paths.append(_norm_path(g, cwd, {}))
        return [Unit(t, "read", f"{t} " + " ".join(paths + flat), paths=paths)]
    if t in ("WebFetch", "WebSearch"):
        flat = []
        _flatten(tool_input, flat)
        return [Unit(t, "web", f"{t} " + " ".join(flat))]
    flat = []
    _flatten(tool_input, flat)
    text = f"{t} " + " ".join(flat)
    if t in NOTE_TOOLS:
        # A plan, a todo, a task card: words about work, not work.
        return [Unit(t, "note", text)]
    # A path is one token. A sentence that happens to contain ~/.ssh is prose.
    paths = [_norm_path(x, cwd, {}) for x in flat
             if isinstance(x, str) and _pathlike(x) and len(x) < 4096 and not re.search(r"\s", x.strip())]
    kind = "mcp" if t.startswith("mcp__") else "other"
    if t in ("Task", "Agent"):
        # A local subagent's every call passes through this same hook, so its
        # brief is prose about work, judged when the work happens. A remote one
        # runs where this hook is not: its instructions are judged now.
        if str(tool_input.get("isolation") or "").lower() != "remote":
            return [Unit(t, "note", text)]
        out = [Unit(t, "brief", text, paths=paths)]   # no hook where it runs: what it is asked counts
        for key in ("prompt", "description"):
            v = tool_input.get(key)
            if isinstance(v, str):
                for span in _instructions(v):
                    out += shell_units(span, t, cwd)
        return out
    out = [Unit(t, kind, text, paths=paths)]
    # an MCP tool that takes code runs it: AppleScript, a notebook cell, a script body
    for key in ("code", "script_content", "source", "applescript", "jxa"):
        v = tool_input.get(key)
        if isinstance(v, str) and v.strip():
            bang = [ln.lstrip()[1:] for ln in v.splitlines() if ln.lstrip().startswith("!")]
            if bang:
                out += shell_units("\n".join(bang), t, cwd)
            runner = "osascript" if re.search(r"\btell\s+application\b|do\s+shell\s+script", v) else "python3"
            out += _code_units(v, runner, t, cwd, {}, 0)
    # an MCP tool that takes a command runs it
    for key in ("command", "cmd", "argv", "script", "shell_command"):
        v = tool_input.get(key)
        if isinstance(v, list):
            v = " ".join(shlex.quote(str(x)) for x in v)
        if isinstance(v, str) and v.strip():
            out += shell_units(v, t, cwd)
    return out


def describe(tool: str, tool_input) -> str:
    """One readable line for logs and messages. Display only: never matched."""
    if isinstance(tool_input, dict):
        for key in ("command", "file_path", "notebook_path", "path", "url", "query", "pattern"):
            v = tool_input.get(key)
            if isinstance(v, str) and v:
                return v
        try:
            return json.dumps(tool_input, ensure_ascii=False)
        except (TypeError, ValueError):
            return str(tool_input)
    return str(tool_input)
