"""A second reading of each call: what it would run, not how it is spelled.

The shell reader in shell.py follows a command the way a person reads it: the
first word is the program, the rest are arguments. An agent can keep that
reading and still run something else. `exec -a builder sudo id` names
`builder`; `$'\\x73udo' id` spells sudo in hex; `perl -e 'system qw(git push)'`
never says `git push` as a command at all; `npm version patch` runs whatever
package.json says should run after a version bump.

This module turns each such form back into the plain command it would run,
and puts that plain command through the same rules and the same reader. So a
`may` exception still applies, and nothing here can hold a call the plain form
would let through. Where a route has no plain form (a restart policy, a mail
API host), it names the topic, and the owner's rule for that topic applies.

Before any of that: an agent must not be able to turn kyma off. Writing into
kyma's own code, its folder, a project's .kyma, or putting a `python3` ahead
of the real one on the PATH is denied outright, with no rule needed.

What this cannot do: read a value that only exists when the command runs (a
network response, a file the agent has not written yet). The README says so.
"""

from __future__ import annotations

import base64
import binascii
import fnmatch
import json
import os
import re
import shlex

from . import lazy, rules, shell

_uparse = lazy("urllib.parse")

PKG = os.path.dirname(os.path.realpath(__file__))
REPO = os.path.dirname(os.path.dirname(PKG))
LAUNCHER = os.path.join(REPO, "kyma")
MAX_VARIANTS = 48
MAX_FILE = 64 * 1024

# ------------------------------------------------------------- self-protection

_INTERP_NAMES = re.compile(r"^(?:python[\d.]*|env|node|uv|uvx|kyma|kyma-local|sh|bash|zsh|"
                           r"claude|zstd|git|security|codex)$")   # what the hook and kyma itself run by name
_USER_BINS = ("~/.local/bin", "~/bin", "~/.bin", "/usr/local/bin", "/opt/homebrew/bin", "~/.cargo/bin",
              "~/.pyenv/shims", "~/.asdf/shims", "~/.volta/bin", "~/.npm-global/bin")
# What each command changes: every path it names, or only where it puts things.
# `find ~/.kyma -name '*.md'` and `cp ~/.kyma/RULES.md backup.md` change nothing of kyma's.
_ALL_PATHS = {"rm", "mv", "chmod", "chown", "chflags", "tee", "truncate", "touch", "unlink", "rmdir", "shred", "xattr",
              "sponge", "trash", "srm", "gio"}
_LAST_PATH = {"cp", "ln", "rsync", "install", "ditto", "scp"}
_IN_PLACE = {"sed", "perl", "ruby", "gsed"}
# These open a file to rewrite it, whatever their flags: `ex -sc '%d|x' f`, `vim -es`, `ed f`.
_EDITORS = {"ex", "vi", "vim", "nvim", "view", "gvim", "mvim", "ed", "red", "nano", "pico", "emacs", "micro",
            "joe", "kak", "vis", "jed", "mcedit", "sponge"}
# What deletes or moves a folder with everything in it: kyma's folder dies with any folder above it.
_REMOVERS = {"rm", "rmdir", "mv", "unlink", "shred", "trash", "srm", "gio", "rsync", "chmod", "chown", "chflags"}
_CODE_WRITES = re.compile(r"open\([^)]*['\"][wax]|write_text|write_bytes|writeFileSync|appendFileSync|unlink|"
                          r"rmtree|os\.remove|os\.rename|shutil\.|fs\.rm|File\.write|file_put_contents|>\s*\S")
_SETTINGS = re.compile(r"/\.claude/settings(?:\.local)?\.json$", re.I)


def _path_dirs() -> set:
    out = set()
    for d in (os.environ.get("PATH", "").split(os.pathsep) + [os.path.expanduser(b) for b in _USER_BINS]):
        if d:
            out.add(os.path.realpath(os.path.expanduser(d)))
    return out


def _hook_paths() -> list:
    """Every file the installed hook command runs through: its Python, the
    venv that Python lives in, the launcher or console script it names."""
    out = []
    try:
        from . import sources
        for f in (os.path.join(sources.claude_dir(), "settings.json"),):
            with open(f, encoding="utf-8") as fh:
                d = json.load(fh)
            for g in ((d.get("hooks") or {}).get("PreToolUse") or []) if isinstance(d, dict) else []:
                for h in (g.get("hooks") or []) if isinstance(g, dict) else []:
                    cmd = h.get("command") if isinstance(h, dict) else None
                    if isinstance(cmd, str) and re.search(r"kyma\S*\s+hook\s*$", cmd):
                        out += [w for w in _words(cmd) if w.startswith("/")]
    except (OSError, ValueError, AttributeError, TypeError, RecursionError):
        pass
    return out


def _venv_root(exe: str) -> str:
    d = os.path.dirname(os.path.dirname(exe))
    return d if os.path.isfile(os.path.join(d, "pyvenv.cfg")) else ""


_ANCHOR_CACHE: dict = {}


def anchors() -> tuple:
    """-> (code, state, holds): what the hook depends on.

    code: kyma's package, the clone it runs from, the Python running the hook
    and its venv, and whatever the installed hook command names.
    state: kyma's own folder, its proof of acceptance, the hook settings files.
    holds: folders that hold settings files (Claude Code's own folder)."""
    import sys
    from . import HOME, sources
    key = (HOME, os.environ.get("CLAUDE_CONFIG_DIR"), os.environ.get("HOME"))
    if key in _ANCHOR_CACHE:
        return _ANCHOR_CACHE[key]
    code = {PKG, os.path.realpath(LAUNCHER)}
    holds = set()
    if os.path.isfile(LAUNCHER):
        # Running from a clone: the launcher loads only src/kyma, so src/ and the
        # launcher are what runs. The clone's README and tests are the agent's to edit.
        code.add(os.path.join(REPO, "src"))
        holds.add(REPO)
    exes = [sys.executable] + [p for p in _hook_paths()]
    for e in exes:
        r = os.path.realpath(e)
        code.update({os.path.abspath(e), r})
        for v in (_venv_root(os.path.abspath(e)), _venv_root(r)):
            if v:
                code.add(os.path.realpath(v))
        if os.path.basename(r) == "kyma" and os.path.isfile(os.path.join(os.path.dirname(r), "src", "kyma",
                                                                          "__init__.py")):
            code.add(os.path.join(os.path.dirname(r), "src"))
            holds.add(os.path.dirname(r))
    import sysconfig
    for k in ("purelib", "platlib", "stdlib", "platstdlib"):
        try:
            v = sysconfig.get_paths().get(k)
        except Exception:
            v = None
        if v:
            code.add(os.path.realpath(v))
    for v in (sys.prefix, sys.base_prefix):
        if v and _venv_root(os.path.join(v, "bin", "python")):
            code.add(os.path.realpath(v))       # a venv (uv tool's): every file in it is the hook's
    state = {os.path.realpath(HOME), os.path.realpath(anchor_dir()),
             os.path.realpath(os.path.expanduser("~/Library/Application Support/kyma-local")),
             os.path.realpath(os.path.expanduser("~/.local/state/kyma-local"))}
    cdirs = {os.path.realpath(sources.claude_dir()), os.path.realpath(os.path.expanduser("~/.claude"))}
    files = set()
    for d in cdirs:
        for n in ("settings.json", "settings.local.json"):
            p = os.path.join(d, n)
            files.add(p)
            if os.path.islink(p):
                files.add(os.path.realpath(p))   # a dotfiles link: the file it lands on is the setting
    state |= files
    holds |= cdirs
    out = (tuple(sorted(c for c in code if c and c != "/")), tuple(sorted(x for x in state if x and x != "/")),
           tuple(sorted(holds)))
    _ANCHOR_CACHE[key] = out
    return out


def anchor_dir() -> str:
    """Where kyma keeps proof of the rules you accepted, outside KYMA_HOME:
    an agent that rewrites both files in ~/.kyma cannot rewrite this to match
    without passing through the hook that guards it."""
    base = os.path.expanduser("~/Library/Application Support") if os.path.isdir(os.path.expanduser("~/Library")) \
        else os.path.expanduser(os.environ.get("XDG_STATE_HOME") or "~/.local/state")
    return os.path.join(base, "kyma-local")


def _under(p: str, root: str) -> bool:
    return p == root or p.startswith(root.rstrip("/") + "/")


def protected(path: str, cwd: str | None = None, removing: bool = False) -> str:
    """-> why this path is kyma's own, or ''. With `removing`, a folder that
    holds any of it counts too: `rm -rf ~` deletes ~/.kyma."""
    if not path or "\x00" in path:
        return ""
    p = os.path.expanduser(path)
    if cwd and not os.path.isabs(p):
        p = os.path.join(cwd, p)
    try:
        real = os.path.realpath(p)
    except (OSError, ValueError):
        return ""
    # A disk that ignores case (the macOS default) opens ~/.Kyma as ~/.kyma.
    folded = _case_insensitive(real)
    fold = (lambda x: x.lower()) if folded else (lambda x: x)
    code, state, holds = anchors()
    dirs = {fold(d) for d in _path_dirs()}
    for cand in {fold(os.path.normpath(p)), fold(real)}:
        for c in code:
            if _under(cand, fold(c)):
                return "kyma's own code"
        for x in state:
            if _under(cand, fold(x)):
                return "your agent's hook settings" if x.endswith(".json") else "kyma's rules and state"
        if re.search(r"/\.kyma(?:/|$)", cand, re.I if folded else 0):
            return "kyma's rules and state"
        if _SETTINGS.search(cand):
            return "your agent's hook settings"
        base, parent = os.path.basename(cand), os.path.dirname(cand)
        if _INTERP_NAMES.match(base) and parent in dirs:
            return "a program the hook runs through"
        if removing:
            for c in code + state + holds:
                if _under(fold(c), cand.rstrip("/") or "/"):
                    return "a folder that holds kyma or your agent's hook settings"
    return ""


def _case_insensitive(p: str) -> bool:
    from . import case_insensitive
    try:
        return case_insensitive(p)
    except OSError:
        return False


def _hooks_off(blob: str) -> bool:
    for t in [blob] + decoded_strings(blob):
        t = unescape(t.replace("\\\\", "\\"))
        if re.search(r"\bdisableAllHooks\b\W{0,6}\s*[:=]\s*(?:true|1|True)", t):
            return True
    return False


# Commands that only read what they name. Any other command that names one of
# kyma's files in its arguments is taken to write it: curl -o, sort -o, uniq IN
# OUT, openssl -out, patch FILE, yq -i... there are too many output flags to list.
_READS = {"cat", "less", "more", "head", "tail", "grep", "egrep", "fgrep", "rg", "ag", "ack", "ls", "stat", "file",
          "wc", "diff", "cmp", "md5", "md5sum", "shasum", "sha1sum", "sha256sum", "jq", "bat", "strings", "od",
          "hexdump", "readlink", "realpath", "dirname", "basename", "test", "[", "cd", "pushd", "echo", "printf",
          "open", "code", "subl", "du", "tree", "exa", "eza", "lsof", "nl", "column", "fold", "pbcopy", "type",
          "which", "command", "man", "diff3", "colordiff", "delta", "difft", "less", "view-only", "zcat", "xattr"}
_ARCHIVERS = {"tar", "bsdtar", "gtar", "zip", "7z", "7za", "jar"}
_OUT_FLAG = re.compile(r"(?:^|\s)(?:-[A-Za-z]*o|--output(?:-document|-dir)?|-out|-O|--out|-P|--directory-prefix)"
                       r"(?:=|\s+)?(['\"]?)([^\s'\"]+)\1")
_SQLITE_OUT = re.compile(r"\.(?:once|output|save|backup|excel)\s+(?:-\w+\s+)*['\"]?([^\s'\"]+)")


def _named_writes(u) -> list:
    """Paths a command could write that are not a redirect: an output flag's
    value, or any path it names when it is not a reader."""
    if u.data or not u.head or u.head in _READS or u.head in shell.INTERPRETERS or u.head == "git" \
            or u.head == "find" or u.head in _LAST_PATH:
        return []
    out = []
    text = u.raw or u.text or ""
    for m in _OUT_FLAG.finditer(text):
        v = m.group(2)
        if v and not v.startswith("-"):
            out.append(v)
    if u.head in ("sqlite3", "duckdb"):
        out += _SQLITE_OUT.findall(text)
    if u.head in _ARCHIVERS:
        return out                       # an archive reads what it names, except where it extracts
    return out + list(u.paths or [])


_GIT_TREE_CHANGERS = {"checkout", "switch", "restore", "reset", "pull", "merge", "rebase", "am", "apply", "stash",
                      "cherry-pick", "revert", "clean", "rm", "mv", "read-tree", "checkout-index", "filter-branch",
                      "filter-repo", "worktree", "submodule", "sparse-checkout", "update-index", "bisect"}


def _git_tree(u, cwd) -> str:
    """The work tree a git command changes: -C, --work-tree, or the folder it runs in."""
    try:
        w = shlex.split(u.raw or "")
    except ValueError:
        w = (u.raw or "").split()
    here = u.cwd or cwd or os.getcwd()
    tree = None
    i = 1
    while i < len(w):
        x = w[i]
        if x == "-C" and i + 1 < len(w):
            here = os.path.join(here, os.path.expanduser(w[i + 1]))
            i += 2
            continue
        if x == "--work-tree" and i + 1 < len(w):
            tree = os.path.join(here, os.path.expanduser(w[i + 1]))
            i += 2
            continue
        if x.startswith("--work-tree="):
            tree = os.path.join(here, os.path.expanduser(x.split("=", 1)[1]))
        i += 1
    return os.path.realpath(tree or here)


def _git_changes_kyma(u, cwd) -> bool:
    words = (u.text or "").split()
    sub = words[1] if len(words) > 1 else ""
    if u.head != "git" or sub not in _GIT_TREE_CHANGERS:
        return False
    tree = _git_tree(u, cwd)
    # the clone kyma runs from, or a folder above it: its checkout replaces kyma's code
    return any(_under(c, tree) for c in (PKG, os.path.realpath(LAUNCHER)) if os.path.exists(c))


def self_protect(tool: str, tool_input, cwd: str | None, units: list) -> str:
    """-> why this call would switch kyma off, or ''. Checked before any rule."""
    inp = tool_input if isinstance(tool_input, dict) else {}
    blob = json.dumps(inp) if inp else str(tool_input or "")
    if "isableAllHooks" in blob or "llHooks" in blob or decoded_strings(blob):
        if tool not in ("Read", "Grep", "Glob", "LS") and _hooks_off(blob):
            return "turning off every hook"
    if tool in ("Write", "Edit", "MultiEdit", "NotebookEdit", "apply_patch", "create_file"):
        for k in ("file_path", "path", "notebook_path"):
            why = protected(str(inp.get(k) or ""), cwd)
            if why:
                return why
    for u in units:
        targets = list(getattr(u, "writes", None) or [])
        paths = list(u.paths or [])
        words = (u.text or "").split()
        removing = u.head in _REMOVERS and (u.head not in ("chmod", "chown", "chflags") or
                                            re.search(r"\s-\w*R", u.text or "")) and \
            (u.head != "rsync" or "--delete" in (u.text or "")) and (u.head != "gio" or "trash" in words[1:2])
        if u.kind == "write" or u.head in _ALL_PATHS or u.head in _EDITORS:
            targets += paths
        elif u.head in _LAST_PATH and paths:
            targets.append(paths[-1])
        elif u.head in _IN_PLACE and re.search(r"(?:^|\s)-\w*i", u.text or ""):
            targets += paths
        elif u.head in ("tar", "unzip", "bsdtar") and re.search(r"(?:^|\s)-\w*[xd]|\s-C\s|--directory", u.text or ""):
            targets += paths
        elif u.head == "find" and re.search(r"\s-(?:delete|exec|execdir|ok)\b", u.text or ""):
            targets += paths            # a root above kyma's files is the name tests' call (enforce asks)
        elif u.head == "git" and len(words) > 1 and words[1] in ("checkout", "restore", "rm", "mv", "clean", "reset", "apply"):
            targets += paths
        if _git_changes_kyma(u, cwd):
            return "kyma's own code"
        if u.head == "security" and re.search(r"\b(?:add|delete|set)-generic-password\b|\bdelete-keychain\b|"
                                               r"\bset-keychain-settings\b|\bunlock-keychain\b",
                                               u.text or "") and re.search(r"kyma", u.raw or u.text or "", re.I):
            return "kyma's record of the rules you accepted"
        for t in targets + _named_writes(u):
            why = protected(t, u.cwd or cwd, removing=removing)
            if why:
                return why
        if removing and u.head == "rsync" and paths:
            why = protected(paths[-1], cwd, removing=True)
            if why:
                return why
        if u.head in shell.INTERPRETERS and u.head not in shell.SHELLS and _CODE_WRITES.search(u.text or ""):
            glued = glue(reveal(u.text or ""))
            if re.search(r"\.kyma\b|/src/kyma/|\bdisableAllHooks\b|kyma-local", glued) or PKG in glued:
                return "kyma's rules and state"
    return ""


# ------------------------------------------------------------- reading forms

_ESC = re.compile(r"\\x([0-9a-fA-F]{2})|\\0?([0-7]{3})|\\u([0-9a-fA-F]{4})")


def unescape(s: str) -> str:
    def one(m):
        if m.group(1):
            return chr(int(m.group(1), 16))
        if m.group(2):
            return chr(int(m.group(2), 8))
        return chr(int(m.group(3), 16))
    return _ESC.sub(one, s)


def glue(s: str) -> str:
    """'.e'+'nv' -> '.env'; "su" "do" stays two words."""
    # only a quote that closes a string with something in it: '.' alone is a string, not an operator
    return re.sub(r"(?<=[^\s(\[,=+'\"])(['\"])\s*(?:\+|\.|\.\.)\s*\1(?=[^'\"\s)])", "", s)


def _q(t: str) -> str:
    """A decoded value, quoted back as a literal the other readers can see."""
    return "'" + t.replace("\\", "\\\\").replace("'", "\\'") + "'" if "'" in t else "'" + t + "'"


_S = r"""(?:'(?:[^'\\\n]|\\.)*'|"(?:[^"\\\n]|\\.)*")"""      # one string literal
_NUMS = r"\[\s*\d{1,7}(?:\s*,\s*\d{1,7})*\s*,?\s*\]"


def _lit(t: str) -> str:
    return unescape(t[1:-1])


def _ints(t: str) -> list:
    return [int(x) for x in re.findall(r"\d+", t)]


def _chars(ns: list) -> str:
    try:
        return "".join(chr(n) for n in ns if n < 0x110000)
    except (ValueError, OverflowError):
        return ""


_REVEAL = [
    # ''.join(map(chr,[...])), "".join(chr(c) for c in [...]), bytes([...]).decode(), String.fromCharCode(..)
    (re.compile(r"""['"]{2}\s*\.\s*join\(\s*(?:map\(\s*chr\s*,\s*|\[?\s*chr\(\s*\w+\s*\)\s+for\s+\w+\s+in\s+)(""" + _NUMS + r""")\s*\)?\s*\]?\s*\)"""),
     lambda m: _q(_chars(_ints(m.group(1))))),
    (re.compile(r"bytes\(\s*(" + _NUMS + r")\s*\)(?:\.decode\(\s*(?:['\"][\w-]*['\"])?\s*\))?"),
     lambda m: _q(_chars(_ints(m.group(1))))),
    (re.compile(r"String\.fromCharCode\(\s*([\d\s,]{1,4000})\)"), lambda m: _q(_chars(_ints(m.group(1))))),
    (re.compile(r"\bchr\(\s*(\d{1,7}|0x[0-9a-fA-F]{1,6})\s*\)"),
     lambda m: _q(_chars([int(m.group(1), 0)]))),
    (re.compile(r"\b(?:bytes|bytearray)\.fromhex\(\s*(" + _S + r")\s*\)(?:\.decode\(\s*(?:['\"][\w-]*['\"])?\s*\))?"),
     lambda m: _q(_fromhex(_lit(m.group(1))))),
    (re.compile(r"\b(?:base64\.)?(?:b64decode|standard_b64decode|urlsafe_b64decode|atob)\(\s*(" + _S +
                r")\s*\)(?:\.decode\(\s*(?:['\"][\w-]*['\"])?\s*\))?"), lambda m: _q(_b64(_lit(m.group(1))))),
    (re.compile(r"Buffer\.from\(\s*(" + _S + r")\s*,\s*['\"](base64|hex)['\"]\s*\)(?:\.toString\([^)]*\))?"),
     lambda m: _q(_b64(_lit(m.group(1))) if m.group(2) == "base64" else _fromhex(_lit(m.group(1))))),
    (re.compile(r"\bcodecs\.(?:decode|encode)\(\s*(" + _S + r")\s*,\s*['\"]rot_?13['\"]\s*\)"),
     lambda m: _q(_rot13(_lit(m.group(1))))),
    # reversed: 'abc'[::-1], "abc".reverse, [string reverse abc], scalar reverse("abc"), reverse("abc")
    (re.compile(r"(" + _S + r")\s*\[\s*::\s*-1\s*\]"), lambda m: _q(_lit(m.group(1))[::-1])),
    (re.compile(r"(" + _S + r")\s*\.reverse\b(?:\(\s*\))?"), lambda m: _q(_lit(m.group(1))[::-1])),
    (re.compile(r"\[\s*string\s+reverse\s+(\w+)\s*\]"), lambda m: m.group(1)[::-1]),
    (re.compile(r"\b(?:scalar\s+)?reverse\(\s*(" + _S + r")\s*\)"), lambda m: _q(_lit(m.group(1))[::-1])),
    (re.compile(r"(" + _S + r")\s*\.\s*(lower|upper|strip|casefold)\(\s*\)"),
     lambda m: _q(getattr(_lit(m.group(1)), m.group(2))())),
    (re.compile(r"(" + _S + r")\s*\.\s*(toLowerCase|toUpperCase)\(\s*\)"),
     lambda m: _q(_lit(m.group(1)).lower() if m.group(2) == "toLowerCase" else _lit(m.group(1)).upper())),
    # 'SEP'.join(['a','b']) and ['a','b'].join('SEP'), and ruby's .map(&:reverse)
    (re.compile(r"(" + _S + r")\s*\.\s*join\(\s*[\[(]\s*(" + _S + r"(?:\s*,\s*" + _S + r")*)\s*,?\s*[\])]\s*\)"),
     lambda m: _q(_lit(m.group(1)).join(_lit(x) for x in re.findall(_S, m.group(2))))),
    (re.compile(r"\[\s*(" + _S + r"(?:\s*,\s*" + _S + r")*)\s*,?\s*\]\s*(\.map\(\s*&:reverse\s*\))?\s*\.\s*join\(\s*(" +
                _S + r")?\s*\)"),
     lambda m: _q(_lit(m.group(3) or "''").join((_lit(x)[::-1] if m.group(2) else _lit(x))
                                               for x in re.findall(_S, m.group(1))))),
    # '%sma' % 'ky', '%s/%s' % ('a', 'b'), '{}ma'.format('ky')
    (re.compile(r"(" + _S + r")\s*%\s*(?:(" + _S + r")|\(\s*(" + _S + r"(?:\s*,\s*" + _S + r")*)\s*,?\s*\))"),
     lambda m: _q(_fmt(_lit(m.group(1)), [_lit(m.group(2))] if m.group(2) else
                       [_lit(x) for x in re.findall(_S, m.group(3))]))),
    (re.compile(r"(" + _S + r")\s*\.\s*format\(\s*(" + _S + r"(?:\s*,\s*" + _S + r")*)\s*\)"),
     lambda m: _q(_format(_lit(m.group(1)), [_lit(x) for x in re.findall(_S, m.group(2))]))),
]


def _requote(val: str, text: str, at: int) -> str:
    """Write a worked-out value in the quote the code around it is not using:
    inside a shell's '...' a new '...' would end the program early."""
    if len(val) < 2 or val[0] not in "'\"" or val[-1] != val[0]:
        return val
    before = text[:at]
    if before.count("'") % 2 and val[0] == "'":
        inner = val[1:-1]
        return '"' + inner.replace('"', '\\"') + '"'
    return val


def _fromhex(t: str) -> str:
    try:
        return bytes.fromhex(t).decode("utf-8", "replace")
    except ValueError:
        return ""


def _b64(t: str) -> str:
    try:
        return base64.b64decode(t + "=" * (-len(t) % 4)).decode("utf-8", "replace")
    except (binascii.Error, ValueError):
        return ""


def _rot13(t: str) -> str:
    import codecs
    return codecs.decode(t, "rot13")


def _fmt(f: str, args: list) -> str:
    try:
        return f % tuple(args)
    except (TypeError, ValueError):
        return f


def _format(f: str, args: list) -> str:
    try:
        return f.format(*args)
    except (IndexError, KeyError, ValueError):
        return f


def reveal(code: str) -> str:
    """Code with its built-up strings worked out: chr codes, hex, base64,
    rot13, reversals, joins, %-formatting, adjacent literals. What the
    program would compute from literals alone, written back as literals, so
    every other reader sees 'sudo' where the code says chr(115)+'udo'."""
    if len(code) > 64 * 1024:
        return code
    out = code
    for _ in range(4):
        before = out
        for rx, fn in _REVEAL:
            try:
                cur = out
                out = rx.sub(lambda m: _requote(fn(m), cur, m.start()), cur)
            except (re.error, RecursionError, ValueError):
                pass
        out = re.sub(r"(?<=[^\\])(['\"])\s*\+\s*(['\"])", "", out)       # 'su' + 'do' -> 'sudo'
        out = re.sub(r"(?<=[^\\\s(\[,=])(['\"]) +(['\"])(?=[^\s,)\]])", "", out)     # 'ky' 'ma' -> 'kyma'
        if out == before:
            break
    return out


def _printable(b: bytes) -> str:
    try:
        t = b.decode("utf-8")
    except UnicodeDecodeError:
        return ""
    if len(t) < 3 or sum(c.isprintable() or c in "\n\t" for c in t) < 0.95 * len(t):
        return ""
    return t if re.search(r"[a-z]{2}", t) else ""


def decoded_strings(s: str) -> list:
    """base64 and hex literals that decode to text."""
    out = []
    for tok in set(re.findall(r"[A-Za-z0-9+/]{8,}={0,2}", s)):
        if len(tok) % 4 == 0 and not re.fullmatch(r"[0-9a-fA-F]+", tok):
            try:
                t = _printable(base64.b64decode(tok, validate=True))
            except (binascii.Error, ValueError):
                t = ""
            if t:
                out.append(t)
    for tok in set(re.findall(r"\b(?:[0-9a-fA-F]{2}){4,}\b", s)):
        try:
            t = _printable(bytes.fromhex(tok))
        except ValueError:
            t = ""
        if t:
            out.append(t)
    return out


def _braces(s: str) -> list:
    if "{" not in s or "," not in s:
        return []
    m = re.search(r"([^\s{}'\"]{0,80})\{([^{}\s]{0,80},[^{}\s]{0,80})\}([^\s{}'\"]{0,80})", s)
    if not m:
        return []
    return [s[:m.start()] + m.group(1) + alt + m.group(3) + s[m.end():] for alt in m.group(2).split(",")[:4]]


_WRAP = [
    r"exec(?:\s+-a\s+\S+|\s+-[cl])*\s+",
    r"timeout(?:\s+-[sk]\s+\S+|\s+--\S+|\s+-\w+)*\s+\d+[smhd]?\s+",
    r"caffeinate(?:\s+-[dimsu]+|\s+-[tw]\s+\d+)*\s+",
    # env owns an argv grammar (-S, option values, and quotes). shell's shared
    # reader handles it; a regex here would reinterpret option values as acts.
    r"arch(?:\s+-\w+)+\s+",
    r"nice(?:\s+-n\s+-?\d+|\s+-\d+)*\s+",
    r"ionice(?:\s+-[cnp]\s*\d+)*\s+",
    r"stdbuf(?:\s+-\w\S*)+\s+",
    r"chrt(?:\s+-\w)*\s+\d+\s+",
    r"taskset(?:\s+-\w+)*\s+\S+\s+",
    r"setsid(?:\s+-\w)*\s+",
    r"nohup\s+", r"time(?:\s+-p)?\s+", r"builtin\s+", r"unbuffer\s+",
    r"command\s+(?!-[vV])", r"watch(?:\s+-n\s*\S+|\s+-\w+)*\s+",
    r"flock(?:\s+-\w+)*\s+\S+\s+", r"script\s+-q\s+\S+\s+", r"doas\s+", r"sg\s+\S+\s+-c\s+",
    r"xargs(?:\s+-[0rtx]|\s+-[JILnPdEs]\s*\S+)*\s+",
]
_WRAP_RX = re.compile(r"^\s*(?:" + "|".join(_WRAP) + r")")
_SEG = re.compile(r"(\|\||&&|;|\||&|\n|\$\(|`|\(|\))")


def unwrap(cmd: str) -> str:
    parts = _SEG.split(cmd)
    out = []
    for p in parts:
        if _SEG.fullmatch(p or ""):
            out.append(p)
            continue
        q = p
        for _ in range(6):
            m = _WRAP_RX.match(q)
            if not m:
                break
            q = q[m.end():]
            q = re.sub(r"^\s*(['\"])(.*)\1\s*$", r"\2", q)
        q = re.sub(r"(?<!\S)(%|\{\})(?!\S)", "X", q)               # xargs -J % sudo %
        out.append(" " + q if q is not p else q)
    return "".join(out)


def substitute(cmd: str) -> str:
    """Variables, arrays, set --, functions, hash -p, links made in the same call."""
    vals = {}
    for m in re.finditer(r"(?:\b(?:declare|typeset|local|export|readonly)(?:\s+-\w+)*\s+)?\b([A-Za-z_]\w*)=\(([^)]*)\)", cmd):
        vals[m.group(1)] = " ".join(w.strip("'\"") for w in m.group(2).split())
    for m in re.finditer(r"(?:^|[;&|\s])(?:(?:declare|typeset|local|export|readonly)(?:\s+-\w+)*\s+)?([A-Za-z_]\w*)=(['\"]?)([^\s;&|'\"()]+)\2", cmd):
        vals.setdefault(m.group(1), m.group(3))
    for m in re.finditer(r"\bread(?:\s+-\w+)*\s+([A-Za-z_]\w*)\s*<<<\s*(['\"]?)([^\s;&|'\"]+)\2", cmd):
        vals[m.group(1)] = m.group(3)
    for m in re.finditer(r"\bprintf\s+-v\s+([A-Za-z_]\w*)\s+(['\"]?)([^\s;&|'\"%]+)\2", cmd):
        vals[m.group(1)] = m.group(3)
    out = cmd
    for k, v in vals.items():
        out = re.sub(r"\"?\$\{" + k + r"(?:\[[@*0-9]\])?\}\"?|\"?\$" + k + r"\b\"?", v, out)
    m = re.search(r"\bset\s+--\s+([^;&|\n]+)", out)
    if m:
        out = re.sub(r"\"?\$[@*]\"?", m.group(1).strip(), out)
    for m in re.finditer(r"(?:function\s+)?([A-Za-z_][\w-]*)\s*\(\)\s*\{[^}]*\}\s*;?", cmd):
        out = out.replace(m.group(0), " ")
        out = re.sub(r"(?:^|(?<=[;&|\s]))" + re.escape(m.group(1)) + r"(?=\s)", " ", out)
    for m in re.finditer(r"\bhash\s+-p\s+(\S+)\s+([\w.-]+)", cmd):
        out = re.sub(r"(?:^|(?<=[;&|]))\s*" + re.escape(m.group(2)) + r"(?=\s)", " " + os.path.basename(m.group(1)), out)
    for m in re.finditer(r"\b(?:ln\s+(?:-\w+\s+)*|cp\s+(?:-\w+\s+)*)(\"?\$\(command -v (\w+)\)\"?|\S+)\s+(\S+)", cmd):
        src = m.group(2) or os.path.basename(m.group(1).strip("'\""))
        tgt = m.group(3).strip("'\"")
        if src and tgt and "/" in tgt:
            out = out.replace(tgt, src)
    return out


def decode_forms(cmd: str) -> str:
    out = cmd
    out = re.sub(r"\$'((?:[^'\\]|\\.)*)'", lambda m: unescape(m.group(1)), out)
    out = re.sub(r"\$\{[A-Za-z_]\w*:?[-=+]([^}]*)\}", r"\1", out)
    out = re.sub(r"\"?\$\(\s*(?:echo|printf)\s+(?:-\w+\s+)?['\"]?([^'\"|)]+?)['\"]?\s*\|\s*rev\s*\)\"?",
                 lambda m: m.group(1)[::-1], out)
    out = re.sub(r"\"?\$\(\s*printf\s+['\"]%s['\"]\s+([^)]*)\)\"?",
                 lambda m: "".join(w.strip("'\"") for w in m.group(1).split()), out)

    def hexd(m):
        try:
            return bytes.fromhex(m.group(1)).decode("utf-8", "replace")
        except ValueError:
            return m.group(0)
    out = re.sub(r"\"?\$\(\s*xxd\s+-r\s+-p\s*<<<\s*['\"]?([0-9a-fA-F]+)['\"]?\s*\)\"?", hexd, out)
    return unescape(out)


# ------------------------------------------------------- code that starts processes

_INTERP = re.compile(r"(?:^|[\s;&|(`/])(perl|ruby|php|g?awk|mawk|nawk|expect|osascript|lua|tclsh|python[\d.]*|node|bun|deno|"
                     r"Rscript|julia|tmux|screen|swift)\b")
_SPAWN = re.compile(r"\b(?:system|exec[vlp]?\w*|spawn\w*|popen\w*|qx)\s*[\(\[{\s'\"]|"
                    r"\b(?:passthru|shell_exec|proc_open|pty\.spawn|check_output|check_call|Popen|call|run|execute|"
                    r"Command|execSync|execFileSync|spawnSync)\s*\(|%x[\(\[{]|`[^`]+`|do shell script|doShellScript|"
                    r"send-keys|-X\s+stuff|do script|\bspawn\s|\|\s*['\"](?:/bin/)?(?:ba|z|da)?sh['\"]|"
                    r"\bopen\s*\(?\s*\w+\s*,\s*['\"]\s*\||\bopen\s*\(?[^)]{0,40}['\"]\|-?['\"]|^\s*exec\s|[;\n]\s*exec\s")
_LIT = re.compile(r"'((?:[^'\\\n]|\\.){1,400})'|\"((?:[^\"\\\n]|\\.){1,400})\"|`([^`\n]{1,400})`|"
                  r"\bqw\s*[\(\[{]([^)\]}]{1,400})[)\]}]|%x[\(\[{]([^)\]}]{1,400})[)\]}]")


def literals(code: str, depth: int = 0) -> list:
    """Quoted strings, and the quoted strings inside those: `perl -e 'system("sudo","id")'`."""
    out = []
    for m in _LIT.finditer(glue(code)):
        s = unescape(next(g for g in m.groups() if g is not None))
        inner = literals(s, depth + 1) if depth < 2 and re.search(r"['\"`]|qw\s*[\(\[{]", s) else []
        if inner:
            out += inner
        else:
            out.append(s)
    return out


def spawned(code: str) -> list:
    """Command lines code would hand to a process, as plain strings."""
    code = reveal(code)
    if not _SPAWN.search(code):
        return []
    lits = []
    for l in literals(code):
        for piece in re.split(r";|\n", l) if len(l) < 400 else [l]:
            piece = re.sub(r"^\s*%x[\(\[{](.*)[\)\]}]\s*$", r"\1", piece)
            piece = re.sub(r"^\s*(?:spawn|exec|system|eval|run|do shell script)\s+", "", piece).strip()
            if piece:
                lits.append(piece)
    out = []
    for i, l in enumerate(lits):
        if len(l) < 200:
            out.append(l)
        for n in range(2, 7):
            if i + n <= len(lits):
                out.append(" ".join(lits[i:i + n]))
    for d in decoded_strings(code):
        out.append(d)
        out += spawned(d)[:12]
    return out


# -------------------------------------------------------------- files that run

def _read(path: str) -> str:
    try:
        if os.path.isfile(path) and os.path.getsize(path) <= MAX_FILE:
            with open(path, "rb") as fh:
                raw = fh.read(MAX_FILE)
            # Small native executables also fit the source-size budget. Their
            # string tables are data, not code that launches shell commands.
            if shell._native_binary(raw):
                return ""
            return raw.decode("utf-8", "replace").replace("\r\n", "\n").replace("\r", "\n")
    except OSError:
        pass
    return ""


def _abs(tok: str, cwd: str | None) -> str:
    t = os.path.expanduser(tok.strip("'\""))
    return t if os.path.isabs(t) else os.path.join(cwd or os.getcwd(), t)


def _scripts(pkg_dir: str) -> dict:
    try:
        return (json.loads(_read(os.path.join(pkg_dir, "package.json")) or "{}").get("scripts") or {})
    except ValueError:
        return {}


_LIFECYCLE = {"version": ["preversion", "version", "postversion"],
              "install": ["preinstall", "install", "postinstall", "prepare"], "i": None, "ci": None, "add": None,
              "test": ["pretest", "test", "posttest"], "t": None,
              "publish": ["prepublishOnly", "prepublish", "prepare", "publish", "postpublish"],
              "start": ["prestart", "start", "poststart"], "pack": ["prepack", "prepare", "postpack"]}


def _recipe(text: str, target: str | None, indent: str) -> list:
    lines, out, on = text.splitlines(), [], False
    first = None
    for ln in lines:
        m = re.match(r"^([A-Za-z0-9_.@%/-]+)(?:\s+[^:=]*)?:(?!=)", ln)
        if m and not ln.startswith((" ", "\t")):
            first = first or m.group(1)
            on = (m.group(1) == target) if target else (m.group(1) == first)
            continue
        if on and ln.startswith(indent) and ln.strip():
            out.append(ln.strip().lstrip("@-+"))
    return out


def _words(seg: str) -> list:
    try:
        return shlex.split(seg)
    except ValueError:
        return seg.split()


def launched(cmd: str, cwd: str | None) -> list:
    """What package managers, make, just and test runners would run here."""
    out = []
    cwd = cwd or os.getcwd()
    # an editor, pager or askpass set for this one call runs as a command
    for m in re.finditer(r"\b(?:GIT_EDITOR|GIT_SEQUENCE_EDITOR|GIT_PAGER|PAGER|EDITOR|VISUAL|GIT_SSH_COMMAND|"
                         r"GIT_ASKPASS|SSH_ASKPASS|GIT_EXTERNAL_DIFF|GIT_SSH|GIT_PROXY_COMMAND|LESSOPEN|"
                         r"PROMPT_COMMAND|GIT_SEQUENCE_EDITOR)=(?:'([^']*)'|\"([^\"]*)\"|(\S+))", cmd):
        out.append(next(g for g in m.groups() if g is not None).lstrip("|"))
    # BASH_ENV=f bash -c x, ENV=f sh -i: the shell runs f first
    for m in re.finditer(r"\b(?:BASH_ENV|ENV|ZDOTDIR)=(?:'([^']*)'|\"([^\"]*)\"|(\S+))", cmd):
        f = next(g for g in m.groups() if g is not None)
        body = _read(_abs(f, cwd)) or _read(os.path.join(_abs(f, cwd), ".zshenv"))
        out.append(body or f"cat {shlex.quote(f)}")
    for seg in re.split(r"&&|\|\||;(?![^'\"]*['\"][^'\"]*$)|\n", cmd):
        w = _words(seg)
        if not w:
            continue
        h = os.path.basename(w[0])
        if h in ("npm", "pnpm", "yarn", "bun"):
            args, d = shell.package_args(w[1:], cwd, {})
            args = [x for x in args if not x.startswith("-")]
            sc = _scripts(d)
            verb = args[0] if args else ("install" if h in ("yarn", "pnpm") else "")
            names = []
            if verb in ("run", "run-script", "rum", "urn") and len(args) > 1:
                names = ["pre" + args[1], args[1], "post" + args[1]]
            elif verb in _LIFECYCLE:
                names = _LIFECYCLE[verb] or _LIFECYCLE[{"i": "install", "ci": "install", "add": "install",
                                                         "t": "test"}[verb]]
            elif verb in sc:
                names = ["pre" + verb, verb, "post" + verb]
            elif h == "bun" and verb == "run" and len(args) > 1:
                out.append(_read(_abs(args[1], d)))
            out += ["cd " + shlex.quote(d) + "\n" + sc[n] for n in names if n in sc and isinstance(sc[n], str)]
            if verb in ("test", "t") or "vitest" in seg or "jest" in seg:
                for n in os.listdir(d) if os.path.isdir(d) else []:
                    if re.match(r"(?:vitest|vite|jest)\.config\.\w+$", n):
                        out.append(_read(os.path.join(d, n)))
        elif h in ("npx", "pnpx") and len(w) > 1 and w[1] in ("vitest", "jest"):
            for n in os.listdir(cwd):
                if re.match(r"(?:vitest|vite|jest)\.config\.\w+$", n):
                    out.append(_read(os.path.join(cwd, n)))
        elif h in ("make", "gmake"):
            d, f, target = cwd, None, None
            i = 1
            while i < len(w):
                if w[i] == "-C" and i + 1 < len(w):
                    d = _abs(w[i + 1], cwd); i += 2; continue
                if w[i] == "-f" and i + 1 < len(w):
                    f = w[i + 1]; i += 2; continue
                if not w[i].startswith("-") and "=" not in w[i] and target is None:
                    target = w[i]
                i += 1
            text = _read(_abs(f, d) if f else os.path.join(d, "Makefile")) or _read(os.path.join(d, "makefile"))
            out += _recipe(text, target, "\t")
        elif h == "just":
            target = next((x for x in w[1:] if not x.startswith("-")), None)
            text = _read(os.path.join(cwd, "justfile")) or _read(os.path.join(cwd, "Justfile"))
            out += _recipe(text, target, " ") + _recipe(text, target, "\t")
        elif h == "deno" and len(w) > 2 and w[1] == "task":
            try:
                tasks = json.loads(_read(os.path.join(cwd, "deno.json")) or "{}").get("tasks") or {}
            except ValueError:
                tasks = {}
            if w[2] in tasks:
                out.append(tasks[w[2]])
        elif h in ("pytest", "py.test") or (h.startswith("python") and "pytest" in w[1:3]):
            for c in ("conftest.py", "tests/conftest.py", "test/conftest.py"):
                out.append(_read(os.path.join(cwd, c)))
        elif h == "git":
            out += _git_aliases(w, cwd)
            sub = next((x for x in w[1:] if not x.startswith("-") and "=" not in x and x not in _git_cfg_vals(w)), "")
            hooks_dir = next((v for k, v in _git_cfgs(w) if k.lower() == "core.hookspath"), None)
            if sub in ("commit", "merge", "rebase", "am", "push", "checkout", "switch"):
                for hk in ("pre-commit", "commit-msg", "post-commit", "prepare-commit-msg", "pre-push",
                           "post-checkout", "post-merge", "pre-rebase", "applypatch-msg", "pre-applypatch"):
                    out.append(_read(os.path.join(cwd, ".husky", hk)))
                    out.append(_read(os.path.join(cwd, ".git", "hooks", hk)))
                    if hooks_dir:
                        out.append(_read(os.path.join(_abs(hooks_dir, cwd), hk)))
            rest = w[w.index(sub) + 1:] if sub in w else []
            # subcommands that run a command they are given
            if sub == "bisect" and rest[:1] == ["run"]:
                out.append(" ".join(shlex.quote(x) for x in rest[1:]))
            elif sub == "submodule" and "foreach" in rest:
                out.append(" ".join(rest[rest.index("foreach") + 1:]).strip("'\""))
            elif sub in ("rebase", "difftool", "mergetool", "filter-branch"):
                for i, x in enumerate(rest):
                    if x in ("--exec", "-x", "--extcmd", "--tool-cmd") and i + 1 < len(rest):
                        out.append(rest[i + 1])
                    elif x.startswith(("--exec=", "--extcmd=")):
                        out.append(x.split("=", 1)[1])
                    elif x.endswith("-filter") and i + 1 < len(rest):
                        out.append(rest[i + 1])
        elif h == "open" and ("-a" in w or any(x.endswith((".command", ".tool", ".sh")) for x in w)):
            out += [_read(_abs(x, cwd)) for x in w[1:] if not x.startswith("-") and os.path.isfile(_abs(x, cwd))]
    return [t for t in out if t]


_GIT_RUNS = re.compile(r"^(?:core\.(?:pager|editor|fsmonitor|sshcommand|askpass|hookspath)|sequence\.editor|"
                       r"diff\.external|diff\.[^.]+\.(?:textconv|command)|credential(?:\.[^.]+)?\.helper|"
                       r"filter\.[^.]+\.(?:clean|smudge|process)|merge\.[^.]+\.driver|gpg(?:\.\w+)?\.program|"
                       r"pager\.\w+|interactive\.difffilter|uploadpack\.packobjectshook|core\.gitproxy|"
                       r"difftool\.[^.]+\.cmd|mergetool\.[^.]+\.cmd|remote\.[^.]+\.(?:receivepack|uploadpack))$", re.I)


def _git_cfgs(w: list) -> list:
    out = []
    for i, x in enumerate(w):
        if x == "-c" and i + 1 < len(w) and "=" in w[i + 1]:
            k, _, v = w[i + 1].partition("=")
            out.append((k, v.strip("'\"")))
        elif x.startswith("--config-env="):
            pass
    return out


def _git_cfg_vals(w: list) -> set:
    return {w[i + 1] for i, x in enumerate(w) if x in ("-c", "-C") and i + 1 < len(w)}


def _git_aliases(w: list, cwd: str) -> list:
    out = []
    i, inline = 1, {}
    while i < len(w):
        if w[i] == "-c" and i + 1 < len(w):
            k, _, v = w[i + 1].partition("=")
            if k.startswith("alias."):
                inline[k[6:]] = v.strip("'\"")
            if _GIT_RUNS.match(k) and k.lower() != "core.hookspath":
                if len(v) > 1 and v[0] == v[-1] and v[0] in "'\"":
                    v = v[1:-1]
                out.append(v[1:] if v.startswith("!") else v)      # credential.helper='!cmd' runs cmd
            i += 2
            continue
        if w[i].startswith("-"):
            i += 1
            continue
        break
    sub = w[i] if i < len(w) else ""
    cfg = {}
    for f in (os.path.join(cwd, ".git", "config"), os.path.expanduser("~/.gitconfig")):
        sect = ""
        for ln in _read(f).splitlines():
            s = ln.strip()
            m = re.match(r"\[(\w+)", s)
            if m:
                sect = m.group(1).lower()
            elif sect == "alias" and "=" in s:
                k, _, v = s.partition("=")
                cfg.setdefault(k.strip(), v.strip().strip("'\""))
    for v in (inline.get(sub), cfg.get(sub)):
        if v:
            args = " ".join(shlex.quote(x) for x in w[i + 1:])
            out.append(v[1:] + " " + args if v.startswith("!") else "git " + v + " " + args)
    if sub == "config" and len(w) > i + 2 and w[i + 1].startswith("alias."):
        v = " ".join(w[i + 2:]).strip("'\"")
        out.append(v[1:] if v.startswith("!") else "git " + v)
    return out


def file_code(cmd: str, cwd: str | None) -> list:
    """Files an interpreter, or the shell itself, is handed to run."""
    out = []
    for seg in re.split(r"&&|\|\||;|\n|\|", cmd):
        w = seg.split()
        if not w:
            continue
        h = os.path.basename(w[0])
        cands = []
        if h in ("perl", "ruby", "php", "osascript", "expect", "lua", "tclsh", "awk", "gawk", "bun", "deno", "node",
                 "Rscript") or h.startswith("python"):
            cands = [x for x in w[1:] if not x.startswith("-") and os.path.isfile(_abs(x, cwd))]
        elif "/" in w[0] and os.path.isfile(_abs(w[0], cwd)):
            cands = [w[0]]
        elif h == "poetry" and "run" in w:
            cands = [x for x in w if os.path.isfile(_abs(x, cwd)) and x.endswith((".py", ".sh"))]
        for c in cands[:3]:
            text = _read(_abs(c, cwd))
            if text:
                out.append((text, _abs(c, cwd)))
    return out


# ------------------------------------------------ words decided at run time
#
# A rule about `git push` is decided by git's subcommand; about mail, by the
# recipient; about cron, by what crontab is given. When that deciding word is
# $(...), `...` or a variable with no value in the same command, what the call
# does is decided when it runs: it asks, as an unreadable program name does.
# Every other word may be anything: `git commit -m "$(cat msg)"`, `git log
# $(git merge-base a b)..HEAD`.

# program -> (topics its rules speak about, which positional words decide)
_DECIDES = {
    "git": ({"publish", "destructive"}, "sub"), "gh": ({"publish", "outbound"}, "sub2"),
    "glab": ({"publish"}, "sub2"), "hub": ({"publish"}, "sub"), "jj": ({"publish"}, "sub2"),
    "npm": ({"publish", "supplychain"}, "pkg"), "pnpm": ({"publish", "supplychain"}, "pkg"),
    "yarn": ({"publish", "supplychain"}, "pkg"), "bun": ({"publish", "supplychain"}, "pkg"),
    "cargo": ({"publish"}, "sub"), "twine": ({"publish"}, "sub"), "gem": ({"publish"}, "sub"),
    "docker": ({"publish", "persistence"}, "sub"), "podman": ({"publish", "persistence"}, "sub"),
    "crontab": ({"persistence"}, "all"), "launchctl": ({"persistence"}, "sub"), "at": ({"persistence"}, "all"),
    "systemctl": ({"persistence"}, "sub2"), "pm2": ({"persistence"}, "sub"),
    "mail": ({"outbound"}, "all"), "mailx": ({"outbound"}, "all"), "sendmail": ({"outbound"}, "all"),
    "mutt": ({"outbound"}, "all"), "neomutt": ({"outbound"}, "all"), "msmtp": ({"outbound"}, "all"),
    "swaks": ({"outbound"}, "all"), "himalaya": ({"outbound"}, "sub2"),
    "rm": ({"destructive"}, "all"), "dropdb": ({"destructive"}, "all"), "kubectl": ({"destructive"}, "sub"),
    "terraform": ({"destructive", "publish"}, "sub"), "vercel": ({"publish"}, "sub"), "fly": ({"publish"}, "sub"),
    "flyctl": ({"publish"}, "sub"), "netlify": ({"publish"}, "sub"), "wrangler": ({"publish"}, "sub"),
}
_BUILT_WORD = re.compile(r"\$\(|`|\$\{?[A-Za-z_]")


def _rule_names(r, head: str, topics: set) -> bool:
    """Does this rule speak about this program? "Ask me before any git push" is
    about git, not npm; "Never publish anything" is about every publisher."""
    if any((lit.split() or [""])[0] == head for lit in (r.literals or [])):
        return True
    topics = set(topics)
    if "publish" in topics:
        topics.update(("git_push", "deploy"))
    if "outbound" in topics:
        topics.add("email")
    if not set(r.topics or []) & topics:
        return False
    said = {w for w in re.findall(r"[a-z][\w-]*", (r.text or "").lower()) if w in _DECIDES}
    return head in said if said else True


def run_time_decider(units: list, live: list) -> str:
    """-> the program whose rule-deciding word is built at run time, or ''."""
    for u in units:
        if u.data or u.kind != "shell" or u.head not in _DECIDES or getattr(u, "opaque", ""):
            continue
        topics, which = _DECIDES[u.head]
        named = any(_rule_names(r, u.head, topics) for r in live if r.verdict != rules.ALLOW)
        if not named:
            continue
        words = (u.text or "").split()
        at = next((i for i, w in enumerate(words) if os.path.basename(w).lower() == u.head), None)
        if at is None:
            continue
        pos = [w for w in words[at + 1:] if not w.startswith("-") or _BUILT_WORD.match(w)]
        if which == "sub":
            deciding = pos[:1]
        elif which == "sub2":
            deciding = pos[:2]
        elif which == "pkg":
            # npm publish, npm run <script>: the script's name decides what runs
            deciding = pos[:2] if pos[:1] in (["run"], ["run-script"], ["exec"], ["x"]) else pos[:1]
        else:
            deciding = pos
        if any(_BUILT_WORD.search(w) for w in deciding):
            return u.head
    return ""


# ------------------------------------------------------------ topic routes

_MAIL_HOSTS = re.compile(r"api\.sparkpost\.com|api\.mailersend\.com|mandrillapp\.com|api\.sendgrid\.com|"
                         r"api(?:\.\w+)?\.mailgun\.net|api\.postmarkapp\.com|api\.resend\.com|email[.-][\w-]+\.amazonaws\.com|"
                         r"api\.brevo\.com|api\.sendinblue\.com|mail\.google\.com/mail/\?[^\s'\"]*view=cm|"
                         r"api\.smtp2go\.com|mailtrap\.io/api/send|gmail\.googleapis\.com/[^\s'\"]*/(?:drafts|messages)/send|"
                         r"googleapis\.com/gmail/[^\s'\"]*/(?:drafts|messages)/send|graph\.microsoft\.com/[^\s'\"]*/(?:sendMail|"
                         r"messages/[^/\s'\"]+/send)|formspree\.io/f/|api\.elasticemail\.com|app\.loops\.so/api/v1/transactional|"
                         r"api\.mailjet\.com/v\d/send|api\.sendpulse\.com|api\.mailchimp\.com|mandrill|api\.postale\.io|"
                         r"api\.smtp\.com|api\.emailjs\.com|hooks\.zapier\.com/hooks/catch/[^\s'\"]*(?=.*(?:to|email)=)", re.I)
_MAIL = re.compile(r"\baws\s+sesv?2?\s+send-(?:raw-)?email\b|\bgit\s+send-email\b|\bsendEmail\b|\b(?:neo)?mutt\b|"
                   r"\bmailx?\s+-s\b|\bgam\b.*\bsendemail\b|-starttls\s+smtp\b|\bsmtps?://|"
                   r"(?:^|[\s:,(])(?:25|465|587)\b.{0,80}(?:RCPT TO|MAIL FROM|HELO|EHLO)|RCPT TO:|"
                   r"\.(?:sendmail|send_message)\(|getattr\([^)]{0,80}send_?(?:mail|message)|"
                   r"OutgoingMessage|outgoingMessages\.push|GMAIL_SEND|"
                   r"(?:smtp[\w.-]*|mail[\w.-]*)[:\s](?:25|465|587|2525)\b|-connect\s+\S+:(?:25|465|587|2525)\b|"
                   r"\bnc\b[^|;&]*\b(?:25|465|587|2525)\b|^\s*(?:HELO|EHLO)\b[\s\S]*RCPT\s+TO|MAIL\s+FROM:|"
                   r"\.(?:mail|rcpt)\(\s*['\"][^'\"]*@|smtplib\.SMTP|tell\s+app(?:lication)?\s+\"Mail\"[\s\S]{0,200}\bsend\b|"
                   r"Application\(\s*['\"]Mail['\"]\s*\)[\s\S]{0,300}\.send\(|"
                   r"\bcurl\b[^|;&]*\s(?:-K|--config)\s|--mail-rcpt\b|--mail-from\b", re.I | re.M)
_PUSH = re.compile(r"\bgit\s+send-pack\b|\bgit_push\b|\bpush_files\b|\bcreate_or_update_file\b|\bdelete_file\b|"
                   r"\bgh\s+api\b(?=.*(?:-X\s*(?:PUT|POST|PATCH|DELETE)|--method\s+(?:PUT|POST|PATCH|DELETE)|\s-f\s))"
                   r"(?=.*(?:/contents/|/git/refs|/merges|/pulls/\d+/merge))|\bhub\s+push\b|"
                   r"isomorphic-git[\s\S]{0,200}\.push\(|\.git\.execute\(|"
                   r"(?:-\w*X\s*|--request\s+)(?:PATCH|POST|PUT|DELETE)\b[^|;&]*api\.github\.com/repos/[^\s'\"]+/git/refs|"
                   r"api\.github\.com/repos/[^\s'\"]+/git/refs[^|;&]*(?:-\w*X\s*|--request\s+)(?:PATCH|POST|PUT|DELETE)\b|"
                   r"\bgh\s+repo\s+sync\b[^|;&]*(?:--force|\s[\w.-]+/[\w.-]+)", re.I)
_SCHEDULE = re.compile(r"(?:^|[;&|(]\s*)at\s+(?:-[a-zA-Z]\s*\S*\s+)*(?:now|noon|midnight|teatime|\d)|\|\s*at\b|"
                       r"\bcore\.(?:fsmonitor|hooksPath)\b|--restart[= ](?!no\b)\S|\bpm2\s+(?:start|startup|save)\b|"
                       r"\bkubectl\s+create\s+cronjob\b|kind:\s*CronJob|--schedule-expression|\bgcloud\s+scheduler\b|"
                       r"\bgh\s+workflow\s+enable\b|\bsystemctl\s+--user\s+enable\b|\bPlistBuddy\b[\s\S]*LaunchAgents|"
                       r"(?:ditto|cp|tar|ln|rsync|install|mv|copy\w*|copyfile|plutil|defaults\s+write)\b[^;&|\n]{0,300}"
                       r"Launch(?:Agents|Daemons)|-C\s+\S*Launch(?:Agents|Daemons)|"
                       r"Launch(?:Agents|Daemons)[\s\S]{0,300}\b(?:copy\w*|copyfile|write\w*|rename|move|symlink)\(|"
                       r"loginItems\.push|make\s+(?:new\s+)?login\s+item|\bLoginItem\(|SMAppService|LSSharedFileList|"
                       r"\b(?:tar|bsdtar|gtar|unzip|ditto|7z)\b[^;&|\n]*(?:-C|-d|--directory[= ]|\s)\s*['\"]?"
                       r"(?:~|\$HOME|/Users/[^/\s'\"]+|/home/[^/\s'\"]+)(?:/Library)?/?['\"]?(?:\s|$)|"
                       r"\bscreen\s+-\w*d\w*m[\s\S]*\b(?:while|until|for)\b|"
                       r"\btmux\s+new(?:-session)?\b[^;&|\n]*\s-d\b[\s\S]*\b(?:while|until)\b", re.I)
_AUTOLOAD = re.compile(r"/\.bash_login$|/\.config/fish/(?:conf\.d/[^/]+|config\.fish)$|/\.husky/[^/]+$|\.pth$|"
                       r"/\.git/hooks/[^/]+$|/(?:\.bash_logout|\.zlogout|\.xprofile|\.xsessionrc)$")
_PRIV = re.compile(r"administrator\s+privileges|administratorPrivileges|\bsudoedit\b|\bpkexec\b", re.I)
_TERMINALS = re.compile(r"terminal|iterm|warp|ghostty|kitty|alacritty|wezterm|hyper|console", re.I)


def topics_for(tool: str, inp, cmd: str, variants: list, cwd: str | None) -> list:
    """[(topic, cap)] for routes that have no plain-command form.

    `cmd` and `variants` are already the parts that run: a commit message, an
    echo, a grep pattern or a heredoc written to a file is said, not done."""
    cmd = glue(cmd)
    variants = [glue(v) for v in variants]
    out = []
    urls = [str(v) for k, v in (inp.items() if isinstance(inp, dict) else []) if isinstance(v, str) and
            (k in ("url", "uri", "href") or "://" in v[:12])]
    text = "\n".join([cmd, tool] + variants + urls)
    if _MAIL_HOSTS.search(text) or _MAIL.search(text):
        out.append(("outbound", None))
        out.append(("email", None))
    if _PUSH.search(text) or re.search(r"git_push$|(?:github|gitlab|gitea|bitbucket)\w*__(?:delete_file|"
                                       r"create_or_update_file|push_files|merge_pull_request|update_ref)$", tool):
        out.append(("publish", None))
        out.append(("git_push", None))
    if _SCHEDULE.search(text):
        out.append(("persistence", None))
    if _PRIV.search(text):
        out.append(("privilege", None))
    if re.search(r"\b(?:release-it|semantic-release|changeset\s+publish|lerna\s+publish|np\s+(?:patch|minor|major)|"
                 r"gh\s+release\s+create|cargo\s+release)\b", text):
        out.append(("publish", None))
        if not re.search(r"\bgh\s+release\s+create\b", text):
            out.append(("git_push", "ask"))
    if re.search(r"\bshortcuts\s+run\b[^;&|\n]*(?:mail|message|send|text)", text, re.I):
        out.append(("outbound", "ask"))
        if re.search(r"\bmail\b|email", text, re.I):
            out.append(("email", "ask"))
    # something left to run long after the call returns: (sleep 7200; x) &, nohup loops
    for m in re.finditer(r"\bsleep\s+(\d+(?:\.\d+)?)([smhd]?)\b", text):
        secs = float(m.group(1)) * {"": 1, "s": 1, "m": 60, "h": 3600, "d": 86400}[m.group(2)]
        if secs >= 300 and re.search(r"&\s*(?:$|\n|;)|\bnohup\b|\bdisown\b|\bsetsid\b|\bwhile\b", text):
            out.append(("persistence", "ask"))
            break
    if isinstance(inp, dict):
        if inp.get("run_in_background") and re.search(r"\bsleep\s+\d|\bwatch\b|\bwhile\b", cmd):
            out.append(("persistence", "ask"))
        fp = str(inp.get("file_path") or inp.get("path") or "")
        body = str(inp.get("content") or inp.get("new_string") or "")
        if fp and _AUTOLOAD.search(fp):
            out.append(("persistence", "ask"))
        if fp.endswith(".vscode/tasks.json") and "folderOpen" in body:
            out.append(("persistence", "ask"))
        if "/.github/workflows/" in fp and re.search(r"(?m)^\s*-?\s*cron:|\bschedule:", body):
            out.append(("persistence", "ask"))
    if re.search(r"(?:^|_)(?:cron|schedul|trigger|routine)", tool, re.I) or tool in ("CronCreate", "RemoteTrigger"):
        out.append(("persistence", "ask"))
    if tool.startswith("mcp__") and isinstance(inp, dict) and \
            re.search(r"send_?email|GMAIL_SEND|send_?mail\b|\bsendEmail\b", tool + json.dumps(inp), re.I) and \
            not re.search(r"draft", tool + str(inp.get("action", "")), re.I):
        out.append(("outbound", None))
        out.append(("email", None))
    # mcp__mailgun__messages_create, mcp__agentmail__create_message: a message made by a mail service is sent
    if tool.startswith("mcp__") and re.search(r"mail|smtp|ses\b|postmark|sendgrid|resend|outlook|inbox|brevo|"
                                               r"mailjet|loops|sparkpost", tool.split("__")[1] if "__" in tool[5:] else
                                               tool, re.I) \
            and re.search(r"(?:messages?_?(?:create|send)|(?:create|send)_?(?:message|mail|email)|reply|forward)",
                          tool.split("__")[-1], re.I) and not re.search(r"draft", tool, re.I):
        out.append(("outbound", None))
        out.append(("email", None))
    if re.search(r"docker[- ]compose\s+(?:up|run)\b[^|;&]*-d|docker[- ]compose\s+up\b", cmd):
        comp = _read(os.path.join(cwd or "", "docker-compose.yml")) or _read(os.path.join(cwd or "", "compose.yaml")) \
            or _read(os.path.join(cwd or "", "docker-compose.yaml")) or _read(os.path.join(cwd or "", "compose.yml"))
        if re.search(r"restart:\s*['\"]?(?:always|unless-stopped|on-failure)", comp):
            out.append(("persistence", "ask"))
    return out


# ------------------------------------------------------------ secret routes

# The environment, printed: what --env-file loaded comes back out.
_PRINTS_ENV = re.compile(r"(?:^|[|;&]\s*|\s)(?:env|printenv|set|export\s+-p)\s*(?:$|[|;&>])|process\[?['\"]?env\b|"
                         r"\bprocess\.env\b(?!\.\w)|os\.environ\b(?!\[|\.get)|os\.getenv\(|getenv\(|\bENV\b\s*\]|"
                         r"System\.getenv|Deno\.env\.toObject", re.M)
_SECRET_NAME = re.compile(r"(?i)(?:^|[\s/'\":=<(,])(\.env(?:\.[\w.-]+)?)(?=$|[\s'\";)|,&>])")


def _secret_files(d: str) -> list:
    try:
        return [n for n in os.listdir(d) if re.fullmatch(r"(?i)\.env(?:\.[\w.-]+)?", n)
                and not re.search(r"(?i)example|sample|template|dist$", n)]
    except OSError:
        return []


def secret_reads(cmd: str, cwd: str | None, code: list) -> list:
    """-> [(plain read command, cap)]"""
    out = []
    cwd = cwd or os.getcwd()
    here = _secret_files(cwd)
    low = cmd
    # a name spelled in another case still opens the same file on macOS
    for m in re.finditer(r"(?i)(?<![\w.])\.env(?:\.[\w.-]+)?\b", cmd):
        if m.group(0) != m.group(0).lower() and m.group(0).lower() in [h.lower() for h in here]:
            low = low.replace(m.group(0), m.group(0).lower())
    if low != cmd:
        out.append((low, None))
    for v in _braces(cmd):
        out.append((v, None))
    if re.search(r"%2[eE]", cmd):
        out.append((_uparse.unquote(cmd), None))
    for m in re.finditer(r"file://([^\s'\"?#]+)", _uparse.unquote(cmd)):
        p = m.group(1)
        if re.search(r"(?i)/\.env(?:\.[\w.-]+)?$", p):
            out.append(("cat " + p, None))
    plain = re.sub(r"\\(?=\.)|\^(?=\\?\.)|\$(?=['\"])", "", cmd)      # '^\.env$' names .env too
    names = [m.group(1) for m in _SECRET_NAME.finditer(plain)]
    secret = [n for n in names if not re.search(r"(?i)example|sample|template", n)]
    if secret:
        first = secret[0]
        # moved, linked, copied or archived FROM a secret: its contents go somewhere they can be read.
        # `cp .env.example .env.test` copies a template, not a secret.
        for seg in re.split(r"&&|\|\||;|\n|\|", plain):
            w = _words(seg)
            if not w:
                continue
            h = os.path.basename(w[0])
            args = [a for a in w[1:] if not a.startswith("-")]
            srcs = args[:-1] if h in ("mv", "cp", "ln", "ditto", "rsync", "install") else args if h in ("zip", "tar", "7z") else []
            if any(re.fullmatch(r"(?i)(?:.*/)?\.env(?:\.[\w.-]+)?", a) and not re.search(r"(?i)example|sample|template", a)
                   for a in srcs):
                out.append(("cat " + first, None))
                break
        if re.search(r"\bgit\s+(?:add\s+(?:-\w*f\w*|--force)|cat-file\b|show\s+:)", plain) \
                or (re.search(r"--env-file[= ]|\benv_file\b|\bdotenv\b|-m\s+dotenv", plain) and _PRINTS_ENV.search(plain)):
            out.append(("cat " + first, None))
        # handed to a reader through a pipe, a loop, a database or an interpreter
        if re.search(r"xargs\s+(?:-\w+\s+)*(?:cat|less|more|head|tail|bat|strings|od|xxd)\b|"
                     r"\b(?:cat|less|head|tail|bat)\s+\"?\$|\bunzip\s+-p\b|"
                     r"\b(?:sqlite3|duckdb|psql|mysql)\b|\bread\s+POSIX\s+file\b", plain):
            out.append(("cat " + first, None))
    if re.search(r"\bdotenv\b(?:\s+(?:list|get)|\s+-e\b.*|\s+--)|-m\s+dotenv\b|\bnode\s+--env-file", cmd) and here \
            and (re.search(r"\bdotenv\s+(?:list|get)\b|-m\s+dotenv\s+(?:list|get)", cmd) or _PRINTS_ENV.search(cmd)):
        out.append(("cat " + here[0], None))
    # a compose service that loads env_file, run so that it prints its environment
    if here and re.search(r"docker[- ]compose\s+(?:run|exec|up)\b", cmd) and re.search(r"\benv\b|printenv|\bset\b", cmd):
        for n in ("docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"):
            if re.search(r"(?m)^\s*env_file:", _read(os.path.join(cwd, n))):
                out.append(("cat " + here[0], None))
                break
    # globs and prefixes that land on a secret file in this folder
    if here and re.search(r"\b(?:cat|xargs|open|readFileSync|read_text|File\.read|file_get_contents|unzip|less|head|"
                          r"tail|-p\b|print)\b", cmd + "\n".join(code)):
        pats = re.findall(r"['\"]([^'\"\s]*[*?][^'\"\s]*)['\"]", cmd)
        pats += [p for p in re.findall(r"(?<![\w/])(\.[\w]*[*?]\S*)", cmd)]
        hits = [h for h in here if any(fnmatch.fnmatch(h, p.lstrip("./")) or fnmatch.fnmatch(h, p) for p in pats)]
        for c in code:
            if re.search(r"listdir|readdirSync|glob|scandir|Dir\.|readdir|iterdir|os\.walk|Dir\[", c):
                for lit in literals(c):
                    if 2 <= len(lit) <= 6 and any(h.startswith(lit) for h in here):
                        hits.append(here[0])
        if hits:
            out.append(("cat " + hits[0], None))
    # a recursive search reaches nested .env files a top-level check never sees: it prints
    # every matching line of every file, a .env's included, whatever the pattern is
    m = re.search(r"\b(?:grep|egrep|fgrep)\s+(?:-\w+\s+)*-\w*[rR]\w*\b([^;&|]*)", cmd)
    if m and not re.search(r"--include|\s-\w*[lLcq]\w*\b|--files-with|--count|--quiet", m.group(1)):
        excl = [x.strip("'\"") for x in re.findall(r"--exclude=(\S+)", m.group(1))]
        pos = [t for t in _words(m.group(1)) if not t.startswith("-")]
        pat = (m.group(0).split("-e", 1)[1].split()[0] if " -e " in m.group(0) else (pos[0] if pos else "")).strip("'\"")
        roots = pos[1:] or ["."]
        nocase = bool(re.search(r"\s-\w*i|--ignore-case", m.group(0)))
        for r in roots[:3]:
            hit = _nested_secret(_abs(r, cwd), excl)
            # it prints a line of the secret only if the pattern matches one: `grep -rn TODO .` prints none
            if hit and (_matches_a_line(hit, pat, nocase) or re.search(
                    r"(?i)key|secret|token|pass|auth|cred|api|=|private|\bdsn\b|database_url", pat)):
                out.append(("cat " + hit, "ask"))
                break
    # whole-tree readers: an archive of the folder printed, every file cat'ed, everything staged then shown
    tree = re.search(r"\b(?:tar|bsdtar|gtar)\s+-?\w*c\w*\s+[^;&|]*\s\.\/?(?:\s|$)|"
                     r"\bzip\s+-\w*r\w*\s+[^;&|]*\s\.\/?(?:\s|$)|\b7z\s+a\s+[^;&|]*\s\.\/?(?:\s|$)|"
                     r"\bditto\s+-c\b[^;&|]*\s\.\/?(?:\s|$)|"
                     r"\bfind\s+\.\S*\s[^;&|]*-exec\s+(?:cat|head|tail|less|more|strings|xxd|od|bat|grep)\b|"
                     r"\bgit\s+add\s+(?:-A|--all|\.)(?:\s|$)[\s\S]*\bgit\s+(?:diff\s+[^;&|]*--(?:cached|staged)|show)|"
                     r"\bgit\s+stash\s+(?:push\s+)?(?:-u|--include-untracked|-a|--all)\b[\s\S]*\bstash\s+show\b", cmd)
    if tree:
        hit = _nested_secret(cwd, [], tracked_only="git" in tree.group(0))
        if hit:
            out.append(("cat " + hit, "ask"))
    # a reader handed a name worked out at run time, in a folder that holds a secret
    if here and re.search(r"\b(?:cat|less|more|head|tail|bat|strings|xxd|od|nl|tac)\s+[^;&|]*[\"']?\$\(", cmd):
        out.append(("cat " + here[0], "ask"))
    if re.search(r"\bloadEnvFile\(|\bdotenv\.config\(|load_dotenv\(", cmd + "\n".join(code)) and here \
            and (_PRINTS_ENV.search(cmd + "\n".join(code)) or
                 re.search(r"(?:console\.log|print\w*|puts|write)\s*\(?[^;]*(?:process\.env|os\.environ|ENV)",
                           cmd + "\n".join(code))):
        out.append(("cat " + here[0], None))
    if re.search(r"\b(?:rg|ag)\b[^;&|]*(?:--hidden[^;&|]*--no-ignore|--no-ignore[^;&|]*--hidden|-uu+)", cmd):
        if here:
            out.append(("cat " + here[0], None))
    # copying a whole folder that holds a .env and then reading the copy
    if here and re.search(r"\b(?:zip\s+-\w*r|rsync\s+-\w*a|tar\s+-?\w*c|cp\s+-\w*[rR]|ditto)\b[^;&|]*\s\.\/?(?:\s|$)", cmd) \
            and re.search(r"\b(?:grep|cat|unzip\s+-p|less|head|tail)\b", cmd):
        out.append(("cat " + here[0], "ask"))
    if here and re.search(r"\bdocker\s+(?:build|buildx\s+build)\b", cmd) and re.search(r"(?i)\bCOPY\s+\.", cmd) \
            and re.search(r"\bcat\b|\bRUN\b", cmd):
        out.append(("cat " + here[0], "ask"))
    for c in code:
        for lit in literals(c):
            l2 = lit.lstrip("<>+ ")
            if re.fullmatch(r"(?i)(?:.*/)?\.env(?:\.[\w.-]+)?", l2) and not re.search(r"(?i)example|sample", l2):
                if re.search(r"\bopen\b|readFile|read_text|File\.read|file_get_contents|IO\.read|read POSIX|fopen|"
                             r"\.import|load_dotenv|dotenv", c):
                    out.append(("cat " + l2, None))
                    break
    return out


def _matches_a_line(path: str, pat: str, nocase: bool) -> bool:
    """Would grep print any line of this file? Read here, never shown."""
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            lines = fh.read(64 * 1024).splitlines()
    except OSError:
        return True
    if not pat:
        return True
    try:
        rx = re.compile(pat.replace("\\|", "|"), re.I if nocase else 0)
        return any(rx.search(ln) for ln in lines)
    except re.error:
        p = pat.lower() if nocase else pat
        return any(p in (ln.lower() if nocase else ln) for ln in lines)


def _ignored(root: str, name: str) -> bool:
    try:
        with open(os.path.join(root, ".gitignore"), encoding="utf-8", errors="replace") as fh:
            pats = [ln.strip().lstrip("/") for ln in fh if ln.strip() and not ln.startswith("#")]
    except OSError:
        return False
    return any(fnmatch.fnmatch(name, p) or fnmatch.fnmatch(name, p.rstrip("/")) for p in pats)


def _nested_secret(root: str, excl: list = (), tracked_only: bool = False) -> str:
    """The first credential file below root. `tracked_only`: one git would
    stage (not in .gitignore), for `git add -A` and `git stash -u`."""
    if not os.path.isdir(root):
        return ""
    n = 0
    for d, dirs, files in os.walk(root):
        dirs[:] = [x for x in dirs if x not in (".git", "node_modules", ".venv", "venv", "dist", "build", "target")]
        if True:
            for f in files:
                if re.fullmatch(r"\.env(?:\.[\w.-]+)?", f) and not re.search(r"example|sample|template", f) \
                        and not any(fnmatch.fnmatch(f, x) for x in excl) \
                        and not (tracked_only and (_ignored(root, f) or _ignored(d, f))):
                    return os.path.join(d, f)
        n += len(files)
        if n > 4000 or d.count(os.sep) - root.count(os.sep) > 4:
            break
    return ""


# ------------------------------------------------------------------ deciding

def _tool_text(tool: str, inp) -> list:
    """Strings a non-shell tool would type, run or send."""
    if not isinstance(inp, dict):
        return []
    out = []
    looks = re.search(r"execute|run_|shell|script|command|terminal|app_type|type_text|send_keys|javascript", tool, re.I)
    for k, v in inp.items():
        if isinstance(v, str) and (looks or k in ("command", "cmd", "script", "script_content", "code")):
            if tool.endswith("app_type") and not _TERMINALS.search(str(inp.get("app", ""))):
                continue
            out.append(v)
    return out


def variants(tool: str, inp, cwd: str | None) -> tuple:
    """-> ([(plain command, cap)], [code texts], base command text)"""
    cmd = ""
    if isinstance(inp, dict) and tool in ("Bash", "shell", "local_shell", "exec_command", "shell_command") \
            and isinstance(inp.get("command"), str):
        cmd = inp["command"]
    extra = _tool_text(tool, inp) if tool not in ("Bash",) else []
    texts = [t for t in [cmd] + extra if t]
    out, code, ran = [], [], []
    seen = set()

    def add(v, cap=None):
        v = (v or "").strip()
        if v and v not in seen and len(out) < MAX_VARIANTS and len(v) < shell.MAX:
            seen.add(v)
            out.append((v, cap))

    for t in texts:
        if len(t) > 64 * 1024:
            add(unwrap(t))         # past this the shell reader judges it as too large anyway
            continue
        if t is not cmd:
            add(t)
        d = decode_forms(t)
        u = unwrap(substitute(d))
        add(d if d != t else "")
        add(u if u != t else "")
        add(unwrap(substitute(t)))
        for s in decoded_strings(t):
            add(s)
            add(unwrap(substitute(decode_forms(s))))
        for s in dict.fromkeys(launched(u, cwd) + (launched(d, cwd) if "()" in d else [])):
            add(s)
            code.append(s)
        for f, path in file_code(u, cwd):
            shellish = re.match(r"#!\s*\S*(?:/|env\s+)(?:ba|z|da|k)?sh\b", f) or path.endswith((".sh", ".bash", ".zsh"))
            if shellish:
                continue
            ran.append(f)
            if os.path.realpath(path) in shell.AUTHORED:
                code.append(f)        # the agent wrote it: what it opens is the agent's act
            for s in spawned(f):
                add(s)
            if re.match(r"#!\s*\S*(?:/|env\s+)(?:g?awk)\b", f):
                add("awk '" + f.split("\n", 1)[-1] + "'")
        # a heredoc body is code only when an interpreter reads it, not when it is written to a file
        outer = shell._strip_heredocs(t)
        if _INTERP.search(outer) or _SPAWN.search(outer):
            code.append(t)
            for s in spawned(t):
                add(s)
                add(unwrap(substitute(decode_forms(s))))
    if isinstance(inp, dict) and tool in ("Write", "Edit", "MultiEdit", "create_file"):
        body = str(inp.get("content") or inp.get("new_string") or "")
        fp = str(inp.get("file_path") or "")
        # a file that will run by itself later: judge what it would run, now
        if re.search(r"conftest\.py$|\.pth$|/\.husky/|(?:vitest|vite|jest)\.config\.\w+$|/\.git/hooks/|"
                     r"/\.config/fish/|/\.bash_login$|tasks\.json$", fp):
            code.append(body)
            for s in spawned(body):
                add(s)
            for ln in body.splitlines():
                if ln.strip() and not ln.lstrip().startswith(("#", "//")):
                    add(re.sub(r"^\s*(?:-\s*)?(?:run|command):\s*", "", ln.strip()).strip("\"'"))
    return out, code + [("\x00ran", r) for r in ran], "\n".join(texts)


def file_tools(tool: str, inp, cwd: str | None) -> list:
    """Read in another case, Grep with a glob, a browser on a file:// URL: the plain read each one is."""
    if not isinstance(inp, dict):
        return []
    out = []
    p = str(inp.get("file_path") or inp.get("path") or inp.get("notebook_path") or "")
    if tool in ("Read", "NotebookRead", "View") and p:
        b = os.path.basename(p)
        if re.fullmatch(r"(?i)\.env(?:\.[\w.-]+)?", b) and b != b.lower():
            out.append(("cat " + os.path.join(os.path.dirname(p), b.lower()), None))
    if tool in ("Grep", "Glob", "Search") and isinstance(inp.get("glob") or inp.get("pattern"), str):
        g = str(inp.get("glob") or (inp.get("pattern") if tool == "Glob" else "") or "")
        d = _abs(p or ".", cwd) if p else (cwd or os.getcwd())
        hits = [h for h in _secret_files(d) if g and (fnmatch.fnmatch(h, g) or fnmatch.fnmatch(h, g.split("/")[-1]))]
        if hits and inp.get("output_mode") in ("content", None) and tool == "Grep":
            out.append(("cat " + os.path.join(d, hits[0]), None))
    if tool == "Grep" and inp.get("output_mode") == "content" and not inp.get("glob") and not inp.get("type"):
        d = _abs(p or ".", cwd) if p else (cwd or os.getcwd())
        hit = _nested_secret(d, []) if os.path.isdir(d) else ""
        if hit and not _ignored(d, os.path.basename(hit)):
            out.append(("cat " + hit, "ask"))      # every matching line of every file, the .env's included
    for v in inp.values():
        if isinstance(v, str) and v.startswith("file://"):
            path = _uparse.unquote(v[7:].split("?")[0].split("#")[0])
            if re.search(r"(?i)/\.env(?:\.[\w.-]+)?$", path) and not re.search(r"(?i)example|sample", path):
                out.append(("cat " + path, None))
    return out


def _acted(u) -> str:
    """A unit as it acts: its normalised words, plus the code an interpreter is given."""
    if u.head in shell.INTERPRETERS and u.head not in shell.SHELLS:
        t = (u.head or "") + " " + (u.raw or u.text or "")
    else:
        t = u.text or ""
    return t + (" &" if getattr(u, "background", False) else "")


def said_and_done(cmd: str, cwd: str | None) -> str:
    if not cmd:
        return ""
    try:
        return "\n".join(_acted(u) for u in shell.units_for("Bash", {"command": cmd}, cwd) if not u.data)
    except Exception:
        return cmd


UNITS: dict = {}      # variant -> its units, for this one call: read once, judged twice


def parsed(v: str, cwd: str | None) -> list:
    key = (v, cwd)
    if key not in UNITS:
        try:
            UNITS[key] = shell.units_for("Bash", {"command": v}, cwd)
        except shell.Stopped:
            raise
        except Exception:
            UNITS[key] = []
    return UNITS[key]


def check(tool: str, tool_input, cwd: str | None, effective: list, root: str | None, pre=None):
    """-> a Decision stricter than allow, or None."""
    vs, code, base = pre if pre else variants(tool, tool_input, cwd)
    vs = list(vs)
    ran = [c[1] for c in code if isinstance(c, tuple)]       # programs on disk: topics only
    code = [c for c in code if not isinstance(c, tuple)]
    # a heredoc written to a file is prose; one fed to an interpreter is already in `code`
    vs += secret_reads(shell._strip_heredocs(base), cwd, code) if base else []
    vs += file_tools(tool, tool_input, cwd)
    live = [r for r in effective if r.enforced]
    best = rules.Decision(rules.ALLOW)
    done = []
    for v, cap in vs:
        shell._check_stop()
        units = parsed(v, cwd)
        done += [_acted(u) for u in units if not u.data]
        d = rules.decide_units(live, units, root)
        if d.verdict == rules.ALLOW:
            continue
        if cap and rules.STRICT[d.verdict] > rules.STRICT[cap]:
            d = rules.Decision(cap, d.rule)
        if rules.STRICT[d.verdict] > rules.STRICT[best.verdict]:
            best = d
    for topic, cap in topics_for(tool, tool_input, said_and_done(base, cwd), done + code + ran, cwd):
        for r in live:
            if r.verdict == rules.ALLOW or topic not in (r.topics or []):
                continue
            if r.literals or r.paths or r.emails or r.outside or r.except_hosts or r.tools:
                continue
            if any(a.verdict == rules.ALLOW and a.trust == r.trust and topic in (a.topics or [])
                   and not (a.literals or a.paths or a.emails or a.prod or a.tools or a.outside or a.except_hosts)
                   for a in live):
                continue
            verdict = r.verdict if not cap or rules.STRICT[r.verdict] <= rules.STRICT[cap] else cap
            if rules.STRICT[verdict] > rules.STRICT[best.verdict]:
                best = rules.Decision(verdict, r)
    return best if best.verdict != rules.ALLOW else None
