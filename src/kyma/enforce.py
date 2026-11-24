"""Check every tool call before it runs.

  hook()      one PreToolUse payload in on stdin, one answer out on stdout.
  install()   one hook entry in the agent's own settings file. Nothing else.

Three promises this file keeps, each learned the hard way:

  * Inside the hook, it never fails open. A payload it cannot read, rules it
    cannot read, or an error of its own all answer "ask", with the reason, so
    a person decides. A guard that silently stops guarding is worse than none.
    Outside it, the host decides: the hook is installed with
    `onFailure: "block"`, which Claude Code honours from 2.1.295. Older
    versions run the tool call when the hook cannot start, crashes or times
    out, and `kyma on` / `kyma status` say so when they find one.
  * A tool call that changes any RULES.md, kyma's own directory, or the
    agent's hook settings asks you first, and an edit to your RULES.md that
    removes or loosens a rule is not applied until you accept it at a
    terminal (`kyma rules`). What kyma cannot see, it cannot hold: a process
    outside Claude Code, or a person approving the ask, still can.
  * It never damages a file it does not own. A settings file it cannot parse
    is refused, not replaced. Another tool's hook is never touched.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import sys
import time

from . import guard, HOME, ensure_home, rules, shell, sources
from . import canon, case_insensitive, home_problem, lazy, state_append, state_read, state_write

shutil, subprocess, tempfile = lazy("shutil"), lazy("subprocess"), lazy("tempfile")

LOG = os.path.join(HOME, "log.jsonl")
# What the agent itself wrote, so that running it later is still the agent's act:
# Write a script in one call, run it in the next, and each call alone looks innocent.
AUTHORED = os.path.join(HOME, "authored.json")
_LAST_UNITS: list = []
COUNTER = os.path.join(HOME, "checked")
GLOBAL_RULES = os.path.join(HOME, "RULES.md")

TEMPLATE = """# RULES.md

One rule per line, in your own words. Say never, ask me before, or may.
Run `kyma rules` to see exactly how each line is being enforced.

- Ask me before sending any email.
- Ask me before any git push.
- Never read credentials or .env files.
- Ask me before setting anything to run on a schedule or at startup.
- Never use sudo.
"""

DECISION = {"block": "deny", "ask": "ask", "allow": "allow"}

# One switch that stops everything. While it exists, every tool call is held,
# on the very next call, with no deploy and no restart. `kyma go` removes it.
HALT = os.path.join(HOME, "HALT")


def halted():
    """-> (since, why) while the stop is pulled, else None."""
    if not os.path.lexists(HALT):
        return None
    # Whatever HALT is (a file, a link, a folder), its being there is the stop.
    body = (state_read(HALT, 4096) or "").strip().splitlines()
    since = body[0] if body else ""
    why = body[1] if len(body) > 1 else ""
    return since, why


def halt(why: str = "") -> str:
    ensure_home()
    from .signals import clean
    state_write(HALT, _now() + "\n" + clean(why)[:200] + "\n")
    return HALT


def release() -> bool:
    try:
        os.unlink(HALT)
        return True
    except OSError:
        return False


# ------------------------------------------------------------------- where

def project_root(start: str | None = None) -> str:
    """The folder an agent session runs in: the git root, else where you are."""
    cur = os.path.realpath(start or os.getcwd())
    probe = cur
    while True:
        if os.path.exists(os.path.join(probe, ".git")):
            return probe
        parent = os.path.dirname(probe)
        if parent == probe:
            return cur
        probe = parent


def project_rules(cwd: str | None = None) -> str | None:
    """Nearest .kyma/RULES.md from the working folder up to the project root.

    Not above it: /tmp and /Users/Shared are writable by every account, so a
    file planted there must not set policy for every project below. And not a
    file someone else owns, for the same reason.
    """
    cur = os.path.realpath(cwd or os.getcwd())
    top = project_root(cur)
    mine = os.path.realpath(GLOBAL_RULES)
    while True:
        # .kyma/RULES.md, never a bare RULES.md: a cloned repo's game rules or
        # contributing guide is not your policy, even when a line of it parses.
        cand = os.path.join(cur, ".kyma", "RULES.md")
        real = os.path.realpath(cand)
        if os.path.lexists(cand) and not (real == top or real.startswith(top.rstrip("/") + "/")):
            # a link out of the project (to ~/.ssh/id_rsa, say) is not this project's rules:
            # never read, never printed back as rule lines
            cand = ""
        if cand and os.path.lexists(cand) and os.path.realpath(cand) != mine:
            try:
                if os.stat(cand).st_uid == os.getuid():
                    return cand
            except OSError:
                return cand              # exists but unreadable: let load() report it
        if cur == top:
            return None
        parent = os.path.dirname(cur)
        if parent == cur:
            return None
        cur = parent


def rules_path(start: str | None = None) -> str:
    """The file `kyma rules` and `kyma on` talk about first: yours."""
    return GLOBAL_RULES


def load_rules(cwd: str | None = None, path: str | None = None) -> tuple:
    """-> (rules, files). Raises rules.RulesError if a file exists but cannot be read."""
    if path:
        return rules.load(path, trust="global"), [path]
    try:
        if os.lstat(GLOBAL_RULES).st_uid != os.getuid():
            raise rules.RulesError(f"{_short(GLOBAL_RULES)} belongs to another account")
    except FileNotFoundError:
        pass
    except OSError:
        pass
    out = rules.load(GLOBAL_RULES, trust="global")
    files = [GLOBAL_RULES]
    proj = project_rules(cwd)
    if proj:
        out += rules.load(proj, trust="project")
        files.append(proj)
    root = project_root(cwd)
    for r in out:
        if not r.base:
            continue
        full = os.path.join(r.base, "RULES.md")
        if r.trust == "project" and full.startswith(root + os.sep):
            r.source = os.path.relpath(full, root)          # .kyma/RULES.md, or app/.kyma/RULES.md
        else:
            r.source = _short(full)                         # ~/.kyma/RULES.md
    return out, files


def _short(p: str) -> str:
    home = os.path.expanduser("~")
    return "~" + p[len(home):] if p.startswith(home + "/") else p


# ------------------------------------------------------ self-protection

_MUTATING = {"mv", "rm", "unlink", "chmod", "chown", "chflags", "truncate", "shred", "touch", "ln",
             "tee", "dd", "xattr", "rename", "cp", "install", "rsync", "sed", "perl", "git"}
# A write verb, not just `open(`: json.load(open(settings.json)) only reads it.
_CODE_WRITE = re.compile(r"open\([^)]*,\s*f?['\"](?:w|a|x|r\+|wb|ab)|\.write\(|write_text|write_bytes|json\.dump\(|"
                         r"\bunlink|os\.remove|os\.rename|os\.replace|shutil\.|chmod|truncate|rmtree|writeFileSync|"
                         r"appendFileSync|rmSync|sed\s+-i", re.I)   # a shell redirect is resolved by the parser
_GIT_MUTATING = {"checkout", "restore", "rm", "mv", "reset", "clean", "stash", "apply", "am", "cherry-pick",
                 "revert", "merge", "rebase", "pull", "switch"}


def _settings_files() -> list:
    """Claude Code's settings files, wherever CLAUDE_CONFIG_DIR has moved them,
    and wherever ~/.claude is: both, when the variable is set. Plus every file
    kyma installed into (installs.json): a hook put in under CLAUDE_CONFIG_DIR
    stays protected in a session started without the variable."""
    out = []
    for d in {os.path.realpath(sources.claude_dir()), os.path.realpath(os.path.expanduser("~/.claude"))}:
        for n in ("settings.json", "settings.local.json"):
            p = os.path.join(d, n)
            out.append(p)
            # a dotfiles setup links settings.json elsewhere: the file it lands on is just as much the setting
            if os.path.islink(p):
                out.append(os.path.realpath(p))
    for p in _recorded_settings():
        if p not in out:
            out.append(p)
    return out


_RECORDED: list = [None, []]


def _recorded_settings() -> list:
    """The settings files installs.json names, and where their links land.
    Read again only when the file changes: this runs inside every check."""
    try:
        st = os.stat(INSTALLS)
    except OSError:
        return []
    key = (st.st_mtime_ns, st.st_size, st.st_ino)
    if _RECORDED[0] != key:
        paths = []
        for p in _ledger():
            if os.path.isabs(p):
                paths.append(p)
                real = os.path.realpath(p)
                if real != p:
                    paths.append(real)
        _RECORDED[:] = [key, paths]
    return _RECORDED[1]


_SETTINGS_TAIL = re.compile(r"/\.claude/settings(?:\.local)?\.json$")


def _protected(path: str) -> bool:
    """RULES.md, kyma's own folder, or a Claude Code settings file, in any
    spelling the disk accepts. On a disk that ignores case (the macOS
    default), ~/.Kyma/rules.md and ~/.CLAUDE/Settings.json are those files."""
    if not path or "\x00" in path:
        return False
    p = canon(path)
    # kyma's RULES.md: yours in ~/.kyma, a project's in .kyma/. A docs/RULES.md is a document.
    if os.path.basename(p).lower() == "rules.md" and os.path.basename(os.path.dirname(p)).lower() == ".kyma":
        return True
    home = canon(HOME)
    if p == home or p.startswith(home + os.sep):
        return True
    folded = case_insensitive(p)
    for f in _settings_files():
        f = f.lower() if folded else f
        if p == f:
            return True
    return bool(_SETTINGS_TAIL.search(p.lower() if folded else p))


# find runs an action on whatever its search matches, so its search roots are
# what it changes. -delete and -exec rm are the obvious ones; -ok asks a human
# but the human is the agent's terminal, which is no one.
_FIND_ACTS = re.compile(r"(?:^|\s)-(?:delete|exec|execdir|ok|okdir)(?:\s|$)")
_FIND_NAMES = re.compile(r"(?:^|\s)-(i?name|i?path|i?wholename|i?regex)\s+(\S+)")


def _find_hits_protected(u) -> bool:
    """Could this `find` reach RULES.md, kyma's own files, or the hook settings?

    The answer has to come from the search, not the listing: `find ~ -name
    RULES.md -delete` names no protected path, yet deletes one. A root inside
    a protected folder is enough; a root above one counts when nothing in the
    name tests rules the protected file out, so `find ~ -name '*.pyc' -delete`
    still runs."""
    if u.head != "find" or not _FIND_ACTS.search(u.text):
        return False
    roots = [r for r in u.paths if r]
    if any(_protected(r) for r in roots):
        return True
    home = os.path.realpath(HOME)
    files = [os.path.join(home, n) for n in ("RULES.md", "log.jsonl", "authored.json", "rules.seen",
                                             "checked", "HALT")] + _settings_files()
    tests = _FIND_NAMES.findall(u.text)
    names = [(flag, pat.strip("'\"")) for flag, pat in tests]

    def could_match(f: str) -> bool:
        if not names:
            return True
        for flag, pat in names:
            subject = os.path.basename(f) if flag.endswith("name") and "path" not in flag else f
            if flag.startswith("i"):
                subject, pat = subject.lower(), pat.lower()
            if "regex" in flag:
                try:
                    if re.search(pat, subject):
                        return True
                except re.error:
                    return True
            elif shell.fnmatch_safe(subject, pat) or (flag.endswith("path") and pat in subject):
                return True
        return False

    if any(n.lower() in ("rules.md", "settings.json", "settings.local.json") or
           shell.fnmatch_safe("RULES.md", n) for _, n in names):
        return True                     # a RULES.md anywhere below the roots is policy
    for r in roots or [os.getcwd()]:
        r = os.path.realpath(r)
        for f in files:
            if (f == r or f.startswith(r.rstrip("/") + "/")) and could_match(f):
                return True
    return False


# Code can spell a protected name without writing it whole: 'RUL'+'ES.md',
# '/'.join([h, '.kyma', ...]), ".cl" + "aude". Gluing adjacent string literals
# back together catches the spelling; anything cleverer meets the rest of the
# gate. Only a literal that could be a path counts: a name inside prose
# ('see ~/.claude/settings.json') is a sentence the code writes somewhere
# else, and holding it would hold every script that edits documentation.
_GLUE_PLUS = re.compile(r"""['"]\s*\+\s*['"]""")
_GLUE_ANY = re.compile(r"""['"]\s*(?:\+|,)\s*['"]""")
_LITERAL = re.compile(r"'([^'\n]{1,400})'" + r'|"([^"\n]{1,400})"')
_SELF_NAMES = re.compile(r"RULES\.md|\.claude(?:/|$)|^\.claude|(?:^|/)settings(?:\.local)?\.json$|(?:^|/)log\.jsonl$|"
                         r"authored\.json|rules\.seen|\.kyma(?:/|$|RULES)")


def _code_names_self(text: str) -> bool:
    homes = {HOME.rstrip("/"), os.path.realpath(HOME).rstrip("/")}
    for variant in (text, _GLUE_PLUS.sub("", text), _GLUE_ANY.sub("", text)):
        for m in _LITERAL.finditer(variant):
            lit = m.group(1) if m.group(1) is not None else m.group(2)
            if re.search(r"\s", lit):
                continue
            if _SELF_NAMES.search(lit) or any(h and (lit == h or lit.startswith(h + "/")) for h in homes):
                return True
    return False


# What kyma does when an agent runs it. Anything else (on, off, go, stop,
# rules, which accepts a loosened RULES.md at a terminal, try --keep, a word
# built at run time) changes what kyma enforces, and needs a person.
_KYMA_READS = {"", "see", "scan", "status", "log", "check", "demo", "help", "hook", "mcp", "try",
               "--version", "-h", "--help", "--no-open", "--days", "--limit", "--all"}
_KYMA_NAMES = {"kyma", "kyma-local"}
_KYMA_MODULES = re.compile(r"^kyma(?:\.(?:cli|enforce|guard|rules|__main__|mcp))?$")
_FEEDS_ARGS = {"xargs", "parallel", "find", "watch", "entr", "fd"}
# Code that drives kyma from the inside: from kyma import cli; cli.main(["off"]); runpy.run_path(".../kyma")
_CODE_DRIVES = re.compile(r"\b(?:from\s+kyma(?:\.\w+)?\s+import|import\s+kyma\b|kyma\.(?:cli|enforce|guard|rules)\b|"
                          r"importlib\.import_module\(\s*['\"]kyma|__import__\(\s*['\"]kyma|run_(?:path|module)\([^)]*kyma)")
_CODE_KYMA = re.compile(r"(?<![\w-])kyma(?![\w-])|kyma-local|KYMA_HOME")


def _names_kyma(word: str) -> bool:
    """kyma, ~/.local/bin/kyma, the launcher in a clone, or a glob that opens it: kym?, k*a, k[y]ma."""
    w = os.path.basename(word.strip("'\""))
    if w in _KYMA_NAMES:
        return True
    try:
        if os.path.isabs(word) and os.path.realpath(word) == os.path.realpath(guard.LAUNCHER):
            return True
    except (OSError, ValueError):
        pass
    return bool(re.search(r"[*?\[]", w)) and (shell.fnmatch_safe("kyma", w) or shell.fnmatch_safe("kyma-local", w))


def _kyma_sub(words: list):
    """-> what kyma is asked to do in these words: the subcommand, '?' when it
    is built at run time, or None when kyma is not what runs."""
    for i, w in enumerate(words):
        prev = [x for x in words[:i] if not x.startswith("-")]
        first = not prev or all(os.path.basename(x).lower() in shell.WRAPPERS or "=" in x for x in prev)
        via_py = i > 0 and any(re.fullmatch(r"python[\d.]*|pypy\d?|uvx|uv|pipx|run|tool", os.path.basename(x))
                                for x in words[max(0, i - 3):i])
        if words[i - 1:i] == ["-m"] and _KYMA_MODULES.match(w.strip("'\"")):
            pass
        elif not (_names_kyma(w) and (first or via_py)):
            continue
        rest = words[i + 1:]
        if any(os.path.basename(x) in _FEEDS_ARGS for x in words[:i]):
            return "?"                  # xargs and friends add the words at run time
        nxt = next((x for x in rest if not x.startswith("-")), "")
        if re.search(r"[$`{}*?\[\]'\"\\]", nxt):
            return "?"
        if nxt == "try" and any(x.startswith("--k") or x == "-k" for x in rest):
            return "try --keep"
        return nxt
    return None


_UNINSTALLS = re.compile(r"\b(?:pip3?|pipx|uv|brew|conda|mamba|poetry|pdm)\b(?:\s+\S+)*?\s+(?:uninstall|remove|rm)\b"
                         r"(?:\s+\S+)*?\s+['\"]?kyma(?:-local)?['\"]?(?:\s|$)")


def _switches_kyma(u) -> bool:
    """Does this unit run kyma to change what it enforces? Uninstalling it is switching it off."""
    if u.data:
        return False
    if _UNINSTALLS.search(u.text or "") or _UNINSTALLS.search(u.raw or ""):
        return True
    for text in {u.text or "", u.raw or ""}:
        sub = _kyma_sub(text.split())
        if sub is not None and sub not in _KYMA_READS:
            return True
        # words inside a program: spawn kyma rules, ["kyma", "off"], EXEC:'kyma rules'
        toks = [t for t in re.split(r"[\s,;:=()\[\]{}'\"]+", text) if t]
        for i, t in enumerate(toks):
            if _names_kyma(t) and i + 1 < len(toks) and toks[i + 1] in ("on", "off", "go", "rules"):
                return True
    return False


def _code_drives_kyma(u) -> bool:
    """Code given inline that imports, runs or names kyma, however the name is spelled."""
    if u.data or u.head not in shell.INTERPRETERS or u.head in shell.SHELLS or u.origin != "command":
        return False
    code = guard.glue(shell.reveal(u.raw or u.text or ""))
    if _CODE_DRIVES.search(code):
        return True
    return bool(_CODE_KYMA.search(code) and re.search(r"\b(?:import|require|runpy|exec|system|spawn|run|Popen|"
                                                      r"open|write|remove|unlink|rename|sys\.path)\b", code))


# Another agent started from this one runs where this hook is not: its own
# settings, its own permissions, often none. So is a change to where Claude
# Code or kyma looks for their settings, or to the agent's install.
_AGENT_CLIS = {"claude", "codex", "cursor-agent", "aider", "gemini", "opencode", "goose", "crush", "qwen", "amp",
               "plandex", "openhands", "droid", "kiro-cli", "claude-code", "llm"}
_AGENT_INFO = {"--version", "-v", "-V", "--help", "-h", "help", "doctor"}
_AGENT_PKGS = re.compile(r"@anthropic-ai/claude-code|@openai/codex|\bclaude-code\b|\bcodex-cli\b|@google/gemini-cli|"
                         r"\baider-chat\b|opencode-ai")
_SETENV = re.compile(r"\blaunchctl\s+setenv\s+(?:CLAUDE_\w+|KYMA_\w+|CODEX_\w+|ANTHROPIC_\w+|PATH|PYTHON\w*|HOME|"
                     r"BASH_ENV|ENV|ZDOTDIR|DEVELOPER_DIR)\b|\bsystemctl\s+--user\s+set-environment\s+(?:CLAUDE_|KYMA_|CODEX_)")


def starts_agent(units: list) -> str:
    """-> what in this call starts or rewires an agent kyma would not see, or ''."""
    for u in units:
        if u.data:
            continue
        words = (u.text or "").split()
        if u.head in _AGENT_CLIS and words:
            at = next((i for i, w in enumerate(words) if os.path.basename(w).lower() == u.head), 0)
            rest = words[at + 1:]
            if not rest or not (set(rest) <= _AGENT_INFO or rest[:2] in (["mcp", "list"], ["config", "get"])):
                return f"it starts {u.head}, another agent that this hook does not check"
        if u.head in ("npm", "pnpm", "yarn", "bun", "brew", "pipx", "uv", "npx", "volta") and \
                _AGENT_PKGS.search(u.text or "") and re.search(r"\b(?:i|install|add|update|upgrade|up|link|exec|dlx|x)\b",
                                                             u.text or "") or (u.head == "npx" and _AGENT_PKGS.search(u.text or "")):
            return "it changes or runs an agent's install"
        if _SETENV.search(u.text or ""):
            return "it changes where an agent or kyma finds its settings"
    return ""


# Code that writes or removes, and builds the strings it uses at run time:
# chr(46)+'env', bytes.fromhex(...), a reversed literal. What it touches cannot
# be read before it runs, and kyma's own files are among what it could touch.
_BUILT = re.compile(r"\bchr\b|fromhex|b64decode|\batob\(|Buffer\.from|rot_?13|\[\s*::\s*-1\s*\]|\.reverse\b|"
                    r"fromCharCode|\bbytes\(\s*\[|\bpack\(|\bunhexlify|\bdecode\(\s*['\"](?:hex|base64)")


def _code_builds_paths(u) -> bool:
    if u.data or u.head not in shell.INTERPRETERS or u.head in shell.SHELLS or u.origin != "command":
        return False
    code = u.raw or u.text or ""
    return bool(_BUILT.search(code) and _CODE_WRITE.search(code))


# Folders a recursive copy or an archive may land in: an ancestor of kyma's
# folder or of the hook settings is a write into them. `tar -xf x.tar -C ~`
# can carry .kyma/RULES.md and .claude/settings.json inside it.
_EXTRACT_TO = re.compile(r"(?:^|\s)(?:-C\s*|--directory[=\s]|-d\s+)(\S+)")


def _guarded_roots() -> list:
    return [canon(HOME), canon(sources.claude_dir()), canon(os.path.expanduser("~/.claude"))]


def _lands_above_protected(u, cwd) -> bool:
    words = (u.text or "").split()
    if not words:
        return False
    dests = []
    head = u.head
    here = getattr(u, "cwd", "") or cwd or os.getcwd()
    if head in ("tar", "bsdtar", "gtar") and (re.search(r"(?:^|\s)-?[a-zA-Z]*x", " ".join(words[1:2]))
                                             or "--extract" in words or "-x" in words):
        dests += _EXTRACT_TO.findall(u.raw or u.text) or [here]     # no -C: it lands where it runs
    elif head in ("unzip", "7z", "ditto"):
        dests += _EXTRACT_TO.findall(u.raw or u.text)
        if head == "ditto" and u.paths:
            dests.append(u.paths[-1])
        elif not dests and (head == "unzip" or (head == "7z" and words[1:2] in (["x"], ["e"]))):
            dests.append(here)
    elif head in ("cp", "rsync", "gcp") and any(re.fullmatch(r"-\w*[rRa]\w*|--recursive|--archive", w) for w in words[1:]):
        if u.paths:
            dests.append(u.paths[-1])
    for d in dests:
        d = canon(shell._norm_path(d, here, {}))
        for root in _guarded_roots():
            if root == d or root.startswith(d.rstrip("/") + "/"):
                return True
    return False


_READ_ONLY_TOOLS = {"Read", "Glob", "Grep", "LS", "NotebookRead", "WebFetch", "WebSearch", "TodoWrite", "TodoRead"}
_READ_VERB = re.compile(r"(?:^|__)(?:read|list|get|search|view|find|stat|directory_tree|info)[\w-]*$", re.I)


# search_replace, find_and_replace, getOrCreate_file: a read verb first, a write after it
_WRITE_WORD = re.compile(r"replace|write|creat|edit|set|updat|delet|remov|move|renam|put|save|append|patch|insert|"
                         r"upsert|copy|mkdir|chmod|touch|or_?create|Or[A-Z]", re.I)


def _input_names_self(tool: str, tool_input, cwd) -> bool:
    """A tool kyma has no reader for (mcp__filesystem__write_file, edit_file,
    move_file...) that names RULES.md, kyma's folder or the hook settings in
    any of its inputs needs a person. Every string that is a path counts,
    whatever the key is called."""
    t = str(tool or "")
    leaf = t.split("__")[-1]
    if t in shell.SHELL_TOOLS or t in _READ_ONLY_TOOLS or (_READ_VERB.search(t) and not _WRITE_WORD.search(leaf)):
        return False
    seen = [0]

    def walk(v, depth):
        seen[0] += 1
        if seen[0] > 5000 or depth > 20:
            return False
        if isinstance(v, str):
            x = v.strip()
            if not x or len(x) > 4096 or "\n" in x or not (x.startswith(("/", "~", ".", "$HOME")) or "/" in x
                                                          or x.lower() in ("rules.md", "settings.json")):
                return False
            for c in {x, re.sub(r"^(?:file://)", "", x)}:
                c = re.sub(r"^\$\{?HOME\}?", os.path.expanduser("~"), c)
                c = os.path.expanduser(c)
                if not os.path.isabs(c):
                    c = os.path.join(cwd or os.getcwd(), c)
                if _protected(c) or guard.protected(c):
                    return True
            return False
        if isinstance(v, dict):
            return any(walk(k, depth + 1) or walk(x, depth + 1) for k, x in v.items())
        if isinstance(v, (list, tuple)):
            return any(walk(x, depth + 1) for x in v)
        return False
    return walk(tool_input, 0)


def _history_roots() -> list:
    return [canon(os.path.join(sources.claude_dir(), "projects")), canon(os.path.join(sources.codex_dir(), "sessions")),
            canon(os.path.join(sources.codex_dir(), "archived_sessions"))]


def _forges_history(u, targets) -> bool:
    """A file, link or FIFO the agent puts among Claude Code's or Codex's session
    logs is history kyma would read as what an agent did."""
    cands = list(targets)
    if u.head in ("ln", "mkfifo", "mknod", "cp", "mv", "install", "rsync", "ditto", "touch", "tee", "dd"):
        cands += list(u.paths or [])[-1:] if u.head in ("ln", "cp", "mv", "install", "rsync", "ditto") else u.paths
    roots = _history_roots()
    for t in cands:
        c = canon(t)
        if any(c == r or c.startswith(r + os.sep) for r in roots):
            return True
    return False


# A shell profile that moves Claude Code's settings, kyma's folder, the Xcode
# the hook's Python comes from, or PATH, or that puts something in claude's place.
_REWIRE = re.compile(r"\b(?:CLAUDE_CONFIG_DIR|KYMA_\w+|DEVELOPER_DIR|PATH)\s*=|\bset\s+-\w*x\w*\s+(?:CLAUDE_CONFIG_DIR|KYMA_\w+|"
                     r"DEVELOPER_DIR|PATH)\b|\bsetenv\s+(?:CLAUDE_CONFIG_DIR|KYMA_\w+|DEVELOPER_DIR|PATH)\b|"
                     r"\balias\s+claude\b|\bfunction\s+claude\b|(?:^|[\s;])claude\s*\(\)|\bfish_add_path\b")


def _rewires_profile(u) -> bool:
    if getattr(u, "origin", "") == "written" and _REWIRE.search(u.text or u.raw or ""):
        return True                     # a heredoc or a patch into a profile, read as what it runs
    return any(shell.PROFILE.search(w) for w in (u.writes or [])) and bool(_REWIRE.search(u.raw or u.text or ""))


def rewires_profile_input(tool: str, tool_input) -> bool:
    """The Write and Edit tools: content going into a shell profile."""
    if not isinstance(tool_input, dict):
        return False
    fp = str(tool_input.get("file_path") or tool_input.get("path") or "")
    if not shell.PROFILE.search(fp):
        return False
    body = " ".join(str(tool_input.get(k) or "") for k in ("content", "new_string", "new_source"))
    body += " ".join(str(e.get("new_string") or "") for e in (tool_input.get("edits") or []) if isinstance(e, dict))
    return bool(_REWIRE.search(body))


def guards_itself(units: list, cwd: str | None = None) -> bool:
    """Would this call change kyma's rules, kyma's state, or the hook itself?"""
    for u in units:
        if _switches_kyma(u):
            return True                 # an agent must not switch its own gate off
        if _lands_above_protected(u, cwd):
            return True
        targets = list(u.writes or [])
        if u.kind == "write":
            targets += u.paths
        in_place = u.head not in ("sed", "perl") or re.search(r"\s-[a-zA-Z]*i", u.text)   # sed -n only prints
        if u.head in _MUTATING and in_place and (u.head != "git" or set(u.text.split()[1:3]) & _GIT_MUTATING):
            targets += u.paths
        if any(_protected(t) for t in targets):
            return True
        if _forges_history(u, targets):
            return True
        if _rewires_profile(u):
            return True
        if _find_hits_protected(u):
            return True
        if u.head in shell.INTERPRETERS and u.head not in shell.SHELLS:
            # Code: the paths it writes are resolved above when they are literal.
            # A path built at run time is not, so code that writes anything and
            # names kyma's files in any spelling needs a person. A mention
            # alone is not a write: json.load(open(settings.json)) only reads.
            for code in {u.text or "", shell.reveal(u.raw or u.text or "")}:
                if not u.data and _CODE_WRITE.search(code) and _code_names_self(code):
                    return True
            if _code_drives_kyma(u) or _code_builds_paths(u):
                return True             # kyma's own functions, called from code, switch it off as well
            continue
        if not u.data and re.search(r"RULES\.md|\.claude/settings|" + re.escape(HOME), u.text) \
                and _CODE_WRITE.search(u.text) and u.head not in ("cat", "less", "head", "tail", "grep", "rg"):
            return True
    return False


# ------------------------------------------------------- tamper evidence
#
# Every write to RULES.md through a tool call asks first. But a person who
# approves "edit RULES.md" in a stream of prompts has not necessarily read the
# diff, and a file can change by routes no hook sees. So kyma keeps the rule
# set it last accepted, and an edit that removes or loosens a rule does not
# take effect until a person accepts it at a terminal. Tightening needs no
# one: a stricter file can only hold more, so it is accepted on the spot.
#
# Only your own RULES.md is kept this way. A project's .kyma/RULES.md changes
# with every branch it is checked out on, and it can never loosen yours
# (Rule.covers), so holding it back would only be noise.

SEEN = os.path.join(HOME, "rules.seen")


def _sig(r) -> tuple:
    """What a rule does, without where it sits or how it is worded."""
    return (tuple(sorted(r.topics)), r.any_topic, tuple(r.literals), tuple(sorted(e.lower() for e in r.emails)),
            tuple(sorted(r.paths)), tuple(sorted(r.tools)), r.outside, tuple(sorted(r.except_hosts)), r.prod)


def _read_text(path: str):
    try:
        with open(path, "rb") as fh:
            return rules._decode(fh.read(1024 * 1024 + 1))
    except OSError:
        return None


def _seen():
    try:
        d = json.loads(state_read(SEEN) or "null")
        return d.get("text") if isinstance(d, dict) and isinstance(d.get("text"), str) else None
    except (OSError, ValueError, RecursionError):
        return None


# A second copy of what you accepted, outside KYMA_HOME, and on macOS a hash
# of it in your login keychain. An agent that rewrites RULES.md and rules.seen
# to match, by any route the hook does not see, still does not match these.
def _proof_path() -> str:
    import hashlib
    tag = hashlib.sha256(os.path.realpath(HOME).encode()).hexdigest()[:16]
    return os.path.join(guard.anchor_dir(), f"accepted-{tag}.json")


def _real_home() -> bool:
    """Is HOME this account's own? Sandboxes and tests must never touch the real keychain."""
    try:
        import pwd
        return os.path.realpath(pwd.getpwuid(os.getuid()).pw_dir) == os.path.realpath(os.path.expanduser("~"))
    except (ImportError, KeyError, OSError):
        return False


_SECURITY = "/usr/bin/security"


_KC: dict = {}


def _keychain_usable() -> bool:
    return sys.platform == "darwin" and os.path.isfile(_SECURITY) and _real_home() \
        and not os.environ.get("KYMA_NO_KEYCHAIN")


def keychain_start() -> None:
    """Ask the keychain now, read the answer later: the hook overlaps the 14 ms
    `security` takes with its own reading of the call."""
    if "proc" in _KC or not _keychain_usable():
        return
    try:
        _KC["proc"] = subprocess.Popen([_SECURITY, "find-generic-password", "-s", "kyma-local accepted rules", "-a",
                                        os.path.realpath(HOME), "-w"], stdout=subprocess.PIPE,
                                       stderr=subprocess.DEVNULL, text=True)
    except OSError:
        _KC["proc"] = None


# Tests stand in for the keychain with a dict: {"sha": ...}. Never the real one.
KEYCHAIN_FAKE: list = [None]


def _keychain(write_sha: str | None = None):
    """-> the sha kept in the keychain, or None where there is no keychain (not macOS, a sandbox)."""
    fake = KEYCHAIN_FAKE[0]
    if fake is not None:
        if write_sha:
            fake["sha"] = write_sha
            return write_sha
        return fake.get("sha", "")
    if not _keychain_usable():
        return None
    args = ["-s", "kyma-local accepted rules", "-a", os.path.realpath(HOME)]
    if not write_sha and _KC.get("proc") is not None:
        proc = _KC.pop("proc")
        try:
            out, _ = proc.communicate(timeout=5)
            return out.strip() if proc.returncode == 0 and out.strip() else ""
        except Exception:
            proc.kill()
            return None
    try:
        if write_sha:
            subprocess.run([_SECURITY, "add-generic-password", "-U"] + args + ["-w", write_sha],
                           capture_output=True, timeout=5)
            return write_sha
        p = subprocess.run([_SECURITY, "find-generic-password"] + args + ["-w"], capture_output=True, text=True,
                           timeout=5)
        return p.stdout.strip() if p.returncode == 0 and p.stdout.strip() else ""
    except (OSError, subprocess.SubprocessError):
        return None


def _proof_write(text: str) -> None:
    try:
        d = guard.anchor_dir()
        os.makedirs(d, mode=0o700, exist_ok=True)
        body = json.dumps({"home": os.path.realpath(HOME), "sha": _sha(text.encode()), "text": text})
        tmp = _proof_path() + ".tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0), 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(body)
        os.replace(tmp, _proof_path())
    except OSError:
        return
    _keychain(_sha(text.encode()))


def _proof():
    """-> the text kept outside KYMA_HOME, if it is there and whole."""
    try:
        fd = os.open(_proof_path(), os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(fd, encoding="utf-8") as fh:
            d = json.loads(fh.read(2 * 1024 * 1024))
        t = d.get("text") if isinstance(d, dict) else None
        return t if isinstance(t, str) and d.get("sha") == _sha(t.encode()) else None
    except (OSError, ValueError, RecursionError):
        return None


def _seen_proofed() -> bool:
    try:
        d = json.loads(state_read(SEEN) or "null")
        return isinstance(d, dict) and d.get("proof") is True
    except (OSError, ValueError, RecursionError):
        return False


def accepted():
    """-> (the rules text you last accepted, or None; why it cannot be trusted, or '').

    The copy outside KYMA_HOME wins over rules.seen: a rules.seen that
    disagrees with it was written by something other than kyma. The keychain
    hash, where there is one, outranks both."""
    seen = _seen()
    proof = _proof()
    if proof is not None:
        kc = _keychain()
        if kc and kc != _sha(proof.encode()):
            return None, "kyma's record of the rules you accepted was changed outside kyma"
        return proof, ""
    if seen is not None:
        kc = _keychain()
        if kc and kc != _sha(seen.encode()):
            return None, "kyma's record of the rules you accepted was changed outside kyma"
        if _seen_proofed() and not kc:
            return None, "kyma's copy of the rules you accepted is gone"
        return seen, ""                      # accepted before kyma kept a second copy
    if os.path.lexists(SEEN) or os.path.lexists(_proof_path()):
        return None, "kyma's record of the rules you accepted is missing or unreadable"
    return None, ""                          # never accepted: the first file read is


def _parse_global(text: str) -> list:
    out = rules.parse(text, source="RULES.md", base=os.path.dirname(os.path.abspath(GLOBAL_RULES)), trust="global")
    for r in out:
        r.source = _short(GLOBAL_RULES)
    return out


def _write_seen(text: str) -> None:
    try:
        ensure_home()
        compiled = [{"line": r.line, "text": r.text, "verdict": r.verdict, "enforced": r.enforced}
                    for r in _parse_global(text)]
        state_write(SEEN, json.dumps({"accepted": _now(), "text": text, "rules": compiled, "proof": True}))
    except OSError:
        pass
    _proof_write(text)


def loosened(before: list, after: list) -> list:
    """What the new rule set gives up, in words, or [] if it only tightens."""
    out = []
    cur = [r for r in after if r.enforced]
    for a in before:
        if not a.enforced or a.verdict == rules.ALLOW:
            continue
        same = [c for c in cur if _sig(c) == _sig(a) and c.verdict != rules.ALLOW]
        if not same:
            out.append(f"lost '{a.text}'")
        elif max(rules.STRICT[c.verdict] for c in same) < rules.STRICT[a.verdict]:
            out.append(f"changed '{a.text}' from {a.verdict} to {max(same, key=lambda c: rules.STRICT[c.verdict]).verdict}")
    had = {_sig(a) for a in before if a.enforced and a.verdict == rules.ALLOW}
    for c in cur:
        if c.verdict == rules.ALLOW and _sig(c) not in had:
            out.append(f"added the exception '{c.text}'")
    return out


HOLD_ALL = "hold everything"


def _seed() -> None:
    if os.path.lexists(SEEN) or os.path.lexists(_proof_path()):
        return
    text = _read_text(GLOBAL_RULES)
    if text is not None:
        _write_seen(text)


def held_back(loaded: list, write: bool = True) -> tuple:
    """-> (changes, rules to enforce). Accepts silently whatever only tightens.

    The first file kyma reads is the one you wrote, from any surface: the
    hook, `kyma check` or `kyma mcp`. After that, a record of acceptance that
    is missing or was rewritten behind kyma's back holds everything, as a
    missing RULES.md does: changes == [why, HOLD_ALL]."""
    text = _read_text(GLOBAL_RULES)
    seen, bad = accepted()
    if bad:
        return [bad, HOLD_ALL], loaded
    if text is None:
        if seen is not None:
            return ["is gone; the accepted global rules still apply"], \
                _parse_global(seen) + [r for r in loaded if r.trust != "global"]
        return [], loaded
    if seen is None:
        _write_seen(text)               # the first file kyma sees is the one you wrote
        return [], loaded
    if seen == text:
        if not os.path.exists(_proof_path()):
            _write_seen(text)           # an older install: keep the second copy from now on
        return [], loaded
    before = _parse_global(seen)
    now = [r for r in loaded if r.trust == "global"]
    changes = loosened(before, now)
    if not changes:
        _write_seen(text)
        return [], loaded
    # The rules you last accepted, plus anything the edit made stricter.
    keep = before + [r for r in now if r.verdict != rules.ALLOW]
    return changes, keep + [r for r in loaded if r.trust != "global"]


def pending_changes() -> list:
    """The loosening edits to your RULES.md that kyma is not yet applying."""
    text = _read_text(GLOBAL_RULES)
    seen, bad = accepted()
    if bad and text is not None:
        return [bad]
    if text is None or seen is None or seen == text:
        return []
    return loosened(_parse_global(seen), _parse_global(text))


def rules_view(cwd: str | None = None) -> tuple:
    """Rules for readback, including an accepted global file that disappeared."""
    loaded, files = load_rules(cwd)
    missing = False
    if not os.path.lexists(GLOBAL_RULES):
        seen, bad = accepted()
        if seen is not None and not bad:
            loaded = _parse_global(seen) + [r for r in loaded if r.trust != "global"]
            missing = True
    return loaded, files, missing


def restore_accepted_rules(interactive: bool) -> bool:
    """Restore only a missing global file, with its verified accepted content."""
    if not interactive or os.path.lexists(GLOBAL_RULES):
        return False
    seen, bad = accepted()
    if seen is None or bad:
        return False
    ensure_home()
    try:
        fd = os.open(GLOBAL_RULES, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    except FileExistsError:
        return False
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(seen)
        fh.flush()
        os.fsync(fh.fileno())
    return _read_text(GLOBAL_RULES) == seen


def accept_rules(interactive: bool) -> bool:
    """Make the current RULES.md the accepted one. Only a person at a terminal
    can do this: an agent's shell has no TTY, so a loosening it wrote, or
    talked someone into approving, stays held back."""
    text = _read_text(GLOBAL_RULES)
    if text is None or not interactive:
        return False
    _write_seen(text)
    return True


# --------------------------------------------------------------- deciding

PATH_TOOLS = {"Glob", "Grep", "LS"}


def input_problem(tool, tool_input) -> str:
    """Reject an absent call before an empty parse can become permission."""
    if not isinstance(tool, str) or not tool.strip():
        return "tool_name must be a non-empty string"
    shell_form = tool in shell.SHELL_TOOLS and isinstance(tool_input, (str, list, tuple))
    if not shell_form and not isinstance(tool_input, dict):
        return "tool_input must be an object"
    required = shell.SHELL_TOOLS | shell._FILE_TOOLS | {"WebFetch", "WebSearch", "Task", "Agent"}
    if not tool_input and tool in required:
        return "this tool requires non-empty arguments"
    if tool in shell.SHELL_TOOLS:
        if isinstance(tool_input, dict):
            for key in shell._CMD_KEYS:
                if key in tool_input and (not tool_input[key] or not isinstance(tool_input[key], (str, list, tuple, dict))):
                    return "the shell command must contain text or an argument list"
        if not shell.shell_command_of(tool_input).strip():
            return "the shell call has no command"
    return ""


def input_for(tool: str, text: str) -> dict:
    """The tool_input a host would send, for a tool named with one string.

    `kyma check` and `kyma mcp` are given a tool name and a line of text. A
    shell tool whose text lands under file_path is read as a path and passes
    whatever the command does, so every shell name maps to `command`; the
    file tools to `file_path`; the search tools to `path`, as the hook gets them."""
    t = tool or "Bash"
    if t in shell._PATCH and "*** " in text:
        return {"input": text}               # a patch; a bare path is the file it writes
    if t in shell.SHELL_TOOLS:
        return {"command": text}
    if t in sources.WRITE_TOOLS or t in sources.READ_TOOLS or t == "NotebookRead":
        return {"file_path": text}
    if t in PATH_TOOLS:
        return {"path": text, "pattern": "*"} if t == "Glob" else {"path": text}
    if t == "WebFetch":
        return {"url": text}
    if t == "WebSearch":
        return {"query": text}
    return {"command": text}


STARTER = "kyma's starter rules"


def starter_rules() -> list:
    """The five rules `kyma on` writes, as kyma applies them before you write any."""
    out = rules.parse(TEMPLATE, source=STARTER, base="", trust="global")
    for n, r in enumerate(out, 1):
        r.source = STARTER
        r.line = n          # cite "starter rules:3", a line you can find in `kyma rules`
    return out


def evaluate(tool: str, tool_input, path: str | None = None, cwd: str | None = None, write: bool = True,
             starter: bool = False, box: dict | None = None):
    """The call as sent and, when another agent's tool shape maps onto one kyma
    reads (Cursor's edit_file, Codex's write_stdin, a write_file of any MCP
    server), as that too. The stricter answer stands."""
    problem = input_problem(tool, tool_input)
    if problem:
        return rules.Decision("ask", note=f"kyma could not read this tool call ({problem}). [kyma]"), "", []
    shell.begin_call()
    try:
        out = _evaluate(tool, tool_input, path, cwd, write, starter, box)
        mapped = shell.normalise(tool, tool_input)
        if mapped is not None:
            shell.begin_call()
            other = _evaluate(mapped[0], mapped[1], path, cwd, write, starter, box)
            if rules.STRICT[other[0].verdict] > rules.STRICT[out[0].verdict]:
                return other[0], out[1], out[2]
        return out
    finally:
        shell._IN_CALL[0] = False


def _evaluate(tool: str, tool_input, path: str | None = None, cwd: str | None = None, write: bool = True,
              starter: bool = False, box: dict | None = None):
    """-> (Decision, subject, rules). Raises nothing for odd input; RulesError for unreadable rules."""
    subject = shell.describe(tool, tool_input)
    big = rules.Decision("ask", note="This call is too large for kyma to read, so it needs your approval. [kyma]")
    # The limit is on what has to be judged. A 300 KB file written as data is
    # cheap to pass through; 300 KB of code that will run is not read in time.
    if len(subject) > 8 * shell.MAX:
        return big, subject, []
    if not path and not starter:
        _seed()                         # before any early answer: the first file seen is the accepted one
    shell.AUTHORED, shell.LINKS = _authored()
    units = shell.units_for(tool, tool_input, cwd)
    _LAST_UNITS[:] = units
    if any(u.oversize for u in units):
        return big, subject, []
    # The second reading's forms, read once: what the call runs however it is
    # spelled. Self-protection looks at these as well as at the plain units.
    guard.UNITS.clear()
    try:
        pre = guard.variants(tool, tool_input, cwd)
    except Exception:
        pre = None
    vunits = []
    for v, _cap in (pre[0] if pre else []):
        vunits += guard.parsed(v, cwd)
    # Switching kyma off needs no rule to be refused: without this, one call
    # (an edit to kyma's code, a `python3` ahead of the real one) ends every check.
    try:
        why = guard.self_protect(tool, tool_input, cwd, units + vunits)
    except Exception:
        return rules.Decision("ask", note="kyma could not finish checking whether this call changes kyma "
                                          "itself, so it needs your approval. [kyma]"), subject, []
    if why:
        return rules.Decision("block", note=f"This would change {why}, which would stop kyma checking your "
                                            "agent. Do it yourself in a terminal if you mean it. [kyma]"), subject, []
    box = box if box is not None else {}
    guarded = guards_itself(units + vunits, cwd) or _input_names_self(tool, tool_input, cwd) \
        or rewires_profile_input(tool, tool_input)
    opaque = next((u for u in units + vunits if getattr(u, "opaque", "")), None)
    agent = starts_agent(units + vunits)
    try:
        loaded, _files = (starter_rules(), []) if starter else load_rules(cwd, path)
    except rules.RulesError as exc:
        return rules.Decision("ask", note=f"kyma cannot read your rules ({exc}), so every call needs "
                                          "your approval until it can. [kyma]"), subject, []
    root = project_root(cwd) if cwd or not path else None
    changes, effective = ([], loaded) if path or starter else held_back(loaded, write)
    if HOLD_ALL in changes:
        return rules.Decision("ask", note=f"{changes[0][0].upper() + changes[0][1:]}, so every call needs your "
                                          "approval until you run `kyma rules` in a terminal. [kyma]"), subject, loaded
    if not path and not starter and not [r for r in effective if r.enforced] and used_before():
        # had rules, now none: the same as a missing RULES.md
        missing = "is gone" if not os.path.lexists(GLOBAL_RULES) else "has no rules left"
        return rules.Decision("ask", note=f"{_short(GLOBAL_RULES)} {missing}, so every call needs your "
                                          "approval until it has some again or kyma is turned off. [kyma]"), subject, loaded
    decision = rules.decide_units([r for r in effective if r.enforced], units, root)
    if decision.verdict == "block":
        box["early"] = decision          # found before the second reading: kept if that runs out of time
    if changes:
        now = rules.decide_units([r for r in loaded if r.enforced], units, root)
        if rules.STRICT[now.verdict] < rules.STRICT[decision.verdict]:
            # This call is one the edit would have let through. Name the edit,
            # so the person approving sees what changed, not just a rule.
            what = f"{_short(GLOBAL_RULES)} {changes[0]}"
            if len(changes) > 1:
                what += f" (and {len(changes) - 1} more change{'s' if len(changes) > 2 else ''})"
            what += " " if re.search(r"[.!?]'$", what) else ". "
            recovery = ("restore the accepted copy" if not os.path.lexists(GLOBAL_RULES) else "accept")
            decision = rules.Decision(decision.verdict, decision.rule,
                                      note=what + f"Run `kyma rules` in a terminal to {recovery}. [kyma]")
    # A second reading: what the call would run, however it is spelled.
    try:
        second = guard.check(tool, tool_input, cwd, effective, root, pre=pre)
    except Exception:
        second = rules.Decision("ask", note="kyma could not finish reading this call, so it needs your approval. [kyma]")
    if second and rules.STRICT[second.verdict] > rules.STRICT[decision.verdict]:
        decision = second
    if guarded and rules.STRICT[decision.verdict] < rules.STRICT["ask"]:
        decision = rules.Decision("ask", note="Changing kyma's rules or your agent's hook settings needs "
                                              "your approval. [kyma]")
    if agent and rules.STRICT[decision.verdict] < rules.STRICT["ask"]:
        decision = rules.Decision("ask", note=f"This needs your approval: {agent}. [kyma]")
    if opaque is not None and rules.STRICT[decision.verdict] < rules.STRICT["ask"]:
        decision = rules.Decision("ask", note=f"kyma cannot read what this runs ({opaque.opaque}), so it needs "
                                              "your approval. [kyma]")
    if rules.STRICT[decision.verdict] < rules.STRICT["ask"]:
        prog = guard.run_time_decider(units, [r for r in effective if r.enforced])
        if prog:
            decision = rules.Decision("ask", note=f"kyma cannot read what this runs (what {prog} is asked to do "
                                                  "is decided at run time), so it needs your approval. [kyma]")
    if not path and not starter and changes and not os.path.lexists(GLOBAL_RULES) \
            and rules.STRICT[decision.verdict] < rules.STRICT["ask"]:
        decision = rules.Decision("ask", note=f"{_short(GLOBAL_RULES)} is gone. The accepted rules still apply; "
                                              "other calls need your approval until it is restored. [kyma]")
    return decision, subject, loaded


# How long one decision may take. A command built to be slow to read must not
# become a command that runs because the host gave up waiting on the hook.
BUDGET = float(os.environ.get("KYMA_BUDGET") or 2.0)
# The longest any one answer may take, start to finish, whatever the CPU budget:
# Claude Code gives a hook 10 s, and past that the host, not kyma, decides.
WALL = 7.0
MAX_STDIN = 1024 * 1024         # a payload larger than this is answered ask before it is read as a call


def _cpu_clock(t):
    """A clock of the CPU time one thread has used, where the platform has one."""
    try:
        return time.pthread_getcpuclockid(t.ident)
    except (AttributeError, OSError, TypeError):
        return None


def evaluate_within(tool: str, tool_input, cwd: str | None = None, path: str | None = None,
                    budget: float | None = None, write: bool = True, starter: bool = False):
    """evaluate(), or an ask if it cannot finish in time. -> (Decision, subject, rules, finished).

    The budget is the CPU time the reading itself uses, so a machine under
    load answers the same as an idle one (a wall-clock limit turned fast
    blocks into asks when 20 checks ran at once). A reading past its budget
    is stopped, not left running beside the next one; one that had already
    found a block keeps it."""
    import threading
    box = {}
    stop = threading.Event()
    limit = BUDGET if budget is None else budget

    def work():
        shell.STOP[0] = stop
        try:
            box["out"] = evaluate(tool, tool_input, path=path, cwd=cwd, write=write, starter=starter, box=box)
        except shell.Stopped:
            pass
        except BaseException as exc:            # handed to the caller, never lost in the thread
            box["err"] = exc
        finally:
            shell.STOP[0] = None

    t = threading.Thread(target=work, daemon=True)
    started = time.monotonic()
    t.start()
    clock = _cpu_clock(t)
    while t.is_alive():
        t.join(0.02)
        if not t.is_alive():
            break
        used = time.clock_gettime(clock) if clock is not None else time.monotonic() - started
        # a hard wall cap too: CPU time does not grow while a reading waits on a slow disk
        if used > limit or time.monotonic() - started > min(limit * 5, WALL):
            stop.set()
            t.join(1.0)
            early = box.get("early")
            if early is not None and early.verdict == "block":
                return early, shell.describe(tool, tool_input), [], False
            return (rules.Decision("ask", note="This call is too complex for kyma to read in time, so it needs "
                                               "your approval. [kyma]"), shell.describe(tool, tool_input), [], False)
    if "err" in box:
        raise box["err"]
    if "out" not in box:
        return (rules.Decision("ask", note="kyma could not finish reading this call, so it needs your approval. "
                                           "[kyma]"), shell.describe(tool, tool_input), [], False)
    d, subject, loaded = box["out"]
    return d, subject, loaded, True


def used_before() -> bool:
    """Has kyma been set up here? Then a missing RULES.md was removed, not never written."""
    return any(os.path.lexists(p) for p in (SEEN, COUNTER, LOG, _proof_path()))


def verdict_for(tool: str, tool_input, cwd: str | None = None) -> dict:
    """One answer for `kyma check` and `kyma mcp`: what the hook would say, and why.

    -> {"verdict": allow|ask|block, "reason": str, "rule": str|None}. The
    reason is always filled in, allow included: a bare "allow" cannot be told
    apart from a guard that read nothing."""
    unsafe = home_problem()
    if unsafe:
        return {"verdict": "ask", "rule": None,
                "reason": f"kyma will not trust its rules: {unsafe}. Every call needs your approval until "
                          "KYMA_HOME is a folder of yours alone. [kyma]"}
    stop = halted()
    if stop is not None:
        return {"verdict": "block", "rule": "kyma stop",
                "reason": "Everything is on hold: the owner ran `kyma stop`. Nothing runs until `kyma go`. [kyma]"}
    starter = False
    if not os.path.lexists(GLOBAL_RULES) and not project_rules(cwd):
        starter = not used_before()     # a missing accepted file still uses its accepted rules
    d, _subject, loaded, _done = evaluate_within(tool, tool_input, cwd=cwd, write=False, starter=starter)
    if d.verdict != "allow" or d.rule is not None:
        reason = d.reason if d.verdict != "allow" else f"Permitted by {d.reason}"
        out = {"verdict": d.verdict, "reason": reason, "rule": d.rule.text if d.rule else None}
        if d.rule and d.rule.cite:
            out.update({k: d.rule.cite.get(k) for k in ("source", "approved", "version")})
        return out
    active = [r for r in loaded if r.enforced]
    unread = len(loaded) - len(active)
    reason = (f"None of the {len(active)} starter rules applies to this. Write your own in "
              f"{_short(GLOBAL_RULES)}." if starter else f"None of the {len(active)} rules applies to this.")
    if unread:
        reason += f" {unread} more lines could not be read as rules (kyma rules lists them)."
    return {"verdict": "allow", "reason": reason, "rule": None}


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _redact(text: str) -> str:
    """Masked, and cut first: masking a 1 MB subject took 7.9 s of a hook the host gives 10."""
    from .signals import redact
    return redact(text[:4096])


def _clean(text: str) -> str:
    from .signals import clean
    return clean(text)


def record(entry: dict) -> None:
    if os.environ.get("KYMA_SELF_TEST"):
        return                  # kyma checking its own hook is not something your agent did
    try:
        ensure_home()
        # ASCII escapes: a lone surrogate (\ud800) in a command cannot be
        # encoded as UTF-8, and a log line that cannot be written must not
        # become a hook that cannot answer.
        line = json.dumps(entry, ensure_ascii=True) + "\n"
        state_append(LOG, line)
    except Exception:
        pass


class _Locked:
    """An exclusive lock on a file beside the state, for read-modify-write:
    48 hooks at once lost 6 to 14 of their increments without it."""

    def __init__(self, path: str):
        self.path = path + ".lock"

    def __enter__(self):
        self.fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            import fcntl
            fcntl.flock(self.fd, fcntl.LOCK_EX)
        except (ImportError, OSError):
            pass
        return self

    def __exit__(self, *exc):
        os.close(self.fd)
        return False


def _bump() -> None:
    if os.environ.get("KYMA_SELF_TEST"):
        return
    try:
        ensure_home()
        with _Locked(COUNTER):
            try:
                cur = int((state_read(COUNTER, 64) or "0").strip() or 0)
            except ValueError:
                cur = 0
            state_write(COUNTER, str(cur + 1))
    except OSError:
        pass


def _answer(stdout, verdict: str, reason: str) -> int:
    try:
        reason = _clean(reason)        # a folder named with ESC or BEL reaches the terminal through this
    except Exception:
        reason = re.sub(r"[\x00-\x1f\x7f-\x9f]", "?", str(reason))
    try:
        json.dump({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                          "permissionDecision": DECISION[verdict],
                                          "permissionDecisionReason": reason}}, stdout)
        stdout.flush()
        return 0
    except Exception:
        sys.stderr.write("kyma: could not answer; holding this call.\n")
        return 2                       # the host treats exit 2 as a block


def hook(stdin=None, stdout=None) -> int:
    """Every path out of here is an answer. A payload built to crash the
    reader (a lone surrogate, an array 100,000 deep, a poisoned state file)
    ends as an ask with the reason, never a traceback the host reads as
    "the hook failed" and, before 2.1.295, runs the call anyway."""
    stdout = stdout or sys.stdout
    try:
        return _hook(stdin or sys.stdin, stdout)
    except BaseException as exc:            # RecursionError, MemoryError, KeyboardInterrupt, anything
        try:
            record({"ts": _now(), "tool": "?", "verdict": "error", "error": repr(exc)[:200]})
        except BaseException:
            pass
        return _answer(stdout, "ask", f"kyma hit an error checking this call ({type(exc).__name__}), "
                                      "so it needs your approval. [kyma]")


def _hook(stdin, stdout) -> int:
    try:
        raw = stdin.read(MAX_STDIN + 1)
        if raw and len(raw) > MAX_STDIN:
            _bump()
            record({"ts": _now(), "tool": "?", "verdict": "ask", "rule": "too large", "where": "kyma",
                    "subject": _clean(_redact(raw[:300].replace("\n", " ")))[:300]})
            return _answer(stdout, "ask", "This call is too large for kyma to read, so it needs your approval. [kyma]")
        payload = json.loads(raw) if raw and raw.strip() else None
    except Exception:                      # ValueError, RecursionError, UnicodeDecodeError, OSError
        payload = None
    if not isinstance(payload, dict):
        _bump()
        record({"ts": _now(), "tool": "?", "verdict": "error", "error": "unreadable payload"})
        return _answer(stdout, "ask", "kyma could not read this tool call, so it needs your approval. [kyma]")

    tool = payload.get("tool_name")
    tool_input = payload.get("tool_input")
    problem = input_problem(tool, tool_input)
    if problem:
        _bump()
        record({"ts": _now(), "tool": "?", "verdict": "error", "error": problem})
        return _answer(stdout, "ask", f"kyma could not read this tool call ({problem}), so it needs your approval. [kyma]")
    cwd = payload.get("cwd") if isinstance(payload.get("cwd"), str) else None

    keychain_start()
    unsafe = home_problem()
    if unsafe:
        # Another account can replace RULES.md in there: no rule read from it can be trusted.
        return _answer(stdout, "ask", f"kyma will not trust its rules: {unsafe}. Every call needs your "
                                      "approval until KYMA_HOME is a folder of yours alone. [kyma]")
    stop = halted()
    if stop is not None:
        _bump()
        since, why = stop
        try:
            from datetime import datetime
            d = datetime.fromisoformat(since).astimezone()
            when = f"{d.hour % 12 or 12}:{d:%M} {'am' if d.hour < 12 else 'pm'}"
        except (ValueError, TypeError):
            when = "earlier"
        record({"ts": _now(), "tool": tool, "verdict": "block", "rule": "kyma stop", "where": "kyma",
                "subject": _clean(_redact(shell.describe(tool, tool_input).replace("\n", " ")))[:300],
                "cwd": _clean(cwd or os.getcwd())})
        note = f"Everything is on hold: your owner ran `kyma stop` at {when}"
        note += f" ({why})." if why else "."
        return _answer(stdout, "block", note + " Nothing runs until they run `kyma go`. [kyma]")
    if not os.path.lexists(GLOBAL_RULES) and not project_rules(cwd or os.getcwd()) and not used_before():
        _bump()
        record({"ts": _now(), "tool": tool, "verdict": "ask", "rule": "no rules file", "where": "kyma",
                "subject": _clean(_redact(shell.describe(tool, tool_input).replace("\n", " ")))[:300],
                "cwd": _clean(cwd or os.getcwd())})
        return _answer(stdout, "ask", f"kyma is plugged in but {_short(GLOBAL_RULES)} is gone, so every call "
                                      "needs your approval until it is back or kyma is turned off. [kyma]")
    try:
        decision, subject, _, finished = evaluate_within(tool, tool_input, cwd=cwd or os.getcwd())
    except Exception as exc:
        _bump()
        record({"ts": _now(), "tool": tool, "verdict": "error", "error": repr(exc)[:200]})
        return _answer(stdout, "ask", f"kyma hit an error checking this call ({type(exc).__name__}), "
                                      "so it needs your approval. [kyma]")
    _bump()
    if decision.verdict != "block" and finished:
        _remember(_LAST_UNITS, cwd or os.getcwd())   # an allowed or approved write may be run next
    if decision.verdict == "allow":
        try:
            json.dump({}, stdout)
            stdout.flush()
        except Exception:
            return 0
        return 0
    record({"ts": _now(), "tool": tool, "verdict": decision.verdict,
            "rule": decision.rule.text if decision.rule else decision.note,
            "where": _clean(decision.rule.where) if decision.rule else "kyma",
            "subject": _clean(_redact(subject.replace("\n", " ")))[:300],
            "cwd": _clean(cwd or os.getcwd())})
    return _answer(stdout, decision.verdict, decision.reason)


def _authored() -> tuple:
    """The record of what the agent wrote. A file of the wrong shape (a list,
    numbers for names) is read as empty, never as a crash."""
    try:
        d = json.loads(state_read(AUTHORED) or "{}")
        paths = d.get("paths") if isinstance(d, dict) else None
        links = d.get("links") if isinstance(d, dict) else None
        paths = {k for k in paths if isinstance(k, str)} if isinstance(paths, dict) else set()
        links = {k: v for k, v in links.items() if isinstance(k, str) and isinstance(v, str)} \
            if isinstance(links, dict) else {}
        return paths, links
    except Exception:
        return set(), {}


_DOWNLOAD_TO = re.compile(r"(?:^|\s)(?:-o|--output|-O|--output-document)[=\s]+(\S+)")
_EMPTY_WRITERS = {"touch", "mkdir", "truncate", "ln", "chmod", "chown"}


def _remember(units: list, cwd: str | None = None) -> None:
    """Record files this call writes and links it makes, for the calls that run them.

    Any file the agent puts content into counts, whatever its name: code piped
    into peek.txt and run as `python3 peek.txt` is still the agent's code, and so
    is a program it downloads with curl -o. `touch` writes no content, so a
    thousand empty files cannot push a real script out of the record.
    """
    paths, links = {}, {}
    if not any(u.writes or u.head in ("curl", "wget", "ln") for u in units):
        return
    now = _now()
    for u in units:
        if u.head not in _EMPTY_WRITERS:
            for w in (u.writes or []):
                paths[w] = now
        if u.head in ("curl", "wget"):
            for m in _DOWNLOAD_TO.finditer(u.raw or u.text or ""):
                if m.group(1) not in ("-", "/dev/null"):
                    paths[shell._norm_path(m.group(1).strip("'\""), cwd or os.getcwd(), {})] = now
        words = u.text.split()
        if u.head == "ln" and any(re.fullmatch(r"-\w*s\w*", x) for x in words[1:]):
            pos = [x for x in words[1:] if not x.startswith("-")]
            if len(pos) >= 2:
                links[shell._norm_path(pos[1], cwd or os.getcwd(), {})] = os.path.basename(pos[0])
    if not paths and not links:
        return
    try:
        ensure_home()
        # Parallel subagents call the hook at once: without a lock two read the
        # same record and the later write drops the earlier file, and a file
        # dropped from the record turns a deny into an allow.
        lockf = os.open(AUTHORED + ".lock", os.O_WRONLY | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            try:
                import fcntl
                fcntl.flock(lockf, fcntl.LOCK_EX)
            except (ImportError, OSError):
                pass
            try:
                d = json.loads(state_read(AUTHORED) or "{}")
            except (ValueError, RecursionError):
                d = {}
            d = d if isinstance(d, dict) else {}
            allp = d.get("paths") if isinstance(d.get("paths"), dict) else {}
            allp = {k: v for k, v in allp.items() if isinstance(k, str) and isinstance(v, str)}
            allp.update(paths)
            alll = d.get("links") if isinstance(d.get("links"), dict) else {}
            alll = {k: v for k, v in alll.items() if isinstance(k, str) and isinstance(v, str)}
            alll.update(links)
            if len(allp) > 20000:
                # past the cap, down to 15,000 at once, so the next 5,000 writes
                # prune nothing: files that no longer exist go first, then the oldest
                gone = [k for k in allp if not os.path.lexists(k)]
                for k in gone[: len(allp) - 15000]:
                    allp.pop(k, None)
                allp = dict(sorted(allp.items(), key=lambda kv: kv[1])[-15000:])
            state_write(AUTHORED, json.dumps({"paths": allp, "links": dict(list(alll.items())[-2000:])}))
        finally:
            os.close(lockf)
    except OSError:
        pass


def checked_total() -> int:
    try:
        return int((state_read(COUNTER, 64) or "0").strip() or 0)
    except ValueError:
        return 0


_HELD = ("block", "ask", "error")
SUMMARY = os.path.join(HOME, "log.summary.json")


def _held_entry(line: str):
    try:
        e = json.loads(line)
    except (ValueError, RecursionError):
        return None
    return e if isinstance(e, dict) and e.get("verdict") in _HELD else None


def _tail(path: str, want: int) -> list:
    """The last `want` lines, read from the end: the log grows by one line per
    held call, and reading 300,000 lines to print 20 took 18 s."""
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError:
        return []
    try:
        end = os.fstat(fd).st_size
        buf, pos = b"", end
        while pos > 0 and buf.count(b"\n") <= want:
            step = min(1 << 16, pos)
            pos -= step
            os.lseek(fd, pos, os.SEEK_SET)
            buf = os.read(fd, step) + buf
        lines = buf.decode("utf-8", "replace").splitlines()
        return lines[-want:] if pos == 0 else lines[1:][-want:]
    except OSError:
        return []
    finally:
        os.close(fd)


def held(limit: int | None = None) -> list:
    """Held calls, oldest first. With a limit, only the newest that many,
    from the end of the log."""
    if limit:
        got, want = [], limit * 4
        while True:
            lines = _tail(LOG, want)
            got = [e for e in map(_held_entry, lines) if e]
            if len(got) >= limit or len(lines) < want:
                return got[-limit:]
            want *= 4
    text = state_read(LOG)
    if text is None:
        return []
    return [e for e in map(_held_entry, text.splitlines()) if e]


def log_totals() -> dict:
    """-> {"held": n, "errors": n} over the whole log, not the newest page of it.

    Counted once and kept in a small summary beside the log, with the offset
    it reached: each run reads only what was appended since. A log that
    shrank or was rewritten is counted again from the start."""
    try:
        d = json.loads(state_read(SUMMARY, 4096) or "{}")
    except (ValueError, RecursionError):
        d = {}
    d = d if isinstance(d, dict) else {}
    off, n_held, n_err, head = d.get("offset"), d.get("held"), d.get("errors"), d.get("head")
    if not all(isinstance(x, int) and not isinstance(x, bool) and x >= 0 for x in (off, n_held, n_err)):
        off, n_held, n_err, head = 0, 0, 0, ""
    try:
        fd = os.open(LOG, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError:
        return {"held": 0, "errors": 0}
    try:
        size = os.fstat(fd).st_size
        first = os.read(fd, 64).decode("utf-8", "replace")
        if size < off or first != head:
            off, n_held, n_err = 0, 0, 0
        os.lseek(fd, off, os.SEEK_SET)
        while True:
            chunk = os.read(fd, 1 << 20)
            if not chunk:
                break
            cut = chunk.rfind(b"\n")
            if cut < 0:
                break                              # a line still being written: next time
            for line in chunk[:cut].decode("utf-8", "replace").splitlines():
                e = _held_entry(line)
                if e:
                    n_err += e.get("verdict") == "error"
                    n_held += e.get("verdict") != "error"
            off += cut + 1
            os.lseek(fd, off, os.SEEK_SET)
    except OSError:
        pass
    finally:
        os.close(fd)
    try:
        state_write(SUMMARY, json.dumps({"offset": off, "held": n_held, "errors": n_err, "head": first}))
    except (OSError, NameError):
        pass
    return {"held": n_held, "errors": n_err}


def forget_rules() -> None:
    """Undo a first-run ensure_rules() whose install then failed."""
    for f in (GLOBAL_RULES, SEEN, _proof_path()):
        try:
            os.unlink(f)
        except OSError:
            pass


def _last_line(text: str) -> str:
    """The line that says what went wrong: a traceback's last, not its first 300 characters."""
    rows = [r.strip() for r in (text or "").strip().splitlines() if r.strip()]
    return rows[-1][:300] if rows else ""


def ensure_rules() -> str:
    """A first-run RULES.md you can edit, never silently overwritten."""
    if not os.path.lexists(GLOBAL_RULES):
        ensure_home()
        fd = os.open(GLOBAL_RULES, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(TEMPLATE)
    return GLOBAL_RULES


# ------------------------------------------------------------------ install

class InstallError(Exception):
    pass


def settings_path(scope: str, root: str | None = None) -> str:
    if scope == "global":
        return os.path.join(sources.claude_dir(), "settings.json")
    return os.path.join(root or project_root(), ".claude", "settings.local.json")


def _launcher() -> str:
    entry = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "kyma"))
    return entry if os.path.isfile(entry) else ""


def _shim_ok(shim: str = "/usr/bin/python3") -> bool:
    if not os.path.isfile(shim):
        return False
    entry = _launcher()
    probe = ("import sys, os; print(sys.flags.isolated, sys.version_info >= (3, 9))" if entry else
             "import sys, os, kyma; print(sys.flags.isolated, os.path.realpath(kyma.__file__))")
    try:
        p = subprocess.run([shim, "-I", "-c", probe], capture_output=True, text=True, timeout=10,
                           env={"PATH": "/usr/bin:/bin", "HOME": os.path.expanduser("~")})
    except (OSError, subprocess.SubprocessError):
        return False
    out = (p.stdout or "").split()
    if p.returncode != 0 or len(out) < 2 or out[0] != "1":
        return False
    if entry:
        return out[1] == "True"
    return out[1] == os.path.realpath(os.path.join(os.path.dirname(__file__), "__init__.py"))


def interpreter() -> str:
    """The Python running this, by a path that survives an upgrade.

    Not /usr/bin/env python3: that is whichever python3 the session's PATH
    finds first, and a session's PATH is the agent's to change. Not the
    versioned Homebrew Cellar path either, which `brew upgrade` deletes: the
    formula's opt link points at the same file and stays."""
    py = os.path.abspath(sys.executable)
    # Xcode's and the Command Line Tools' Python move with every Xcode update:
    # pinned, a moved Xcode would hold every tool call. /usr/bin/python3 is the
    # stable shim in front of them, used only once it is shown to run this kyma, isolated.
    if re.match(r"^(?:/Applications/Xcode[^/]*\.app/|/Library/Developer/CommandLineTools/)", py) and _shim_ok():
        return "/usr/bin/python3"
    m = re.match(r"^(.*)/Cellar/([^/]+)/[^/]+/(.+)$", py)
    if m:
        opt = f"{m.group(1)}/opt/{m.group(2)}/{m.group(3)}"
        try:
            if os.path.samefile(opt, py):
                return opt
        except OSError:
            pass
    return py


def _scripts_dirs() -> list:
    import sysconfig
    out = [os.path.dirname(os.path.abspath(sys.executable))]
    for scheme in (None, f"{os.name}_user", "osx_framework_user"):
        try:
            d = sysconfig.get_path("scripts", scheme) if scheme else sysconfig.get_path("scripts")
        except KeyError:
            continue
        if d and d not in out:
            out.append(d)
    return out


def command_for_script(script: str) -> str:
    """The hook command for a kept `kyma` script: its own Python, isolated, never the script."""
    try:
        with open(script, "rb") as fh:
            first = fh.readline(4096).decode("utf-8", "replace")
    except OSError:
        return f"{shlex.quote(script)} hook"
    m = re.match(r"#!\s*(?:'([^']+)'|\"([^\"]+)\"|(\S+))", first)
    py = m and (m.group(1) or m.group(2) or m.group(3))
    if py and os.path.isfile(py):
        return f"{shlex.quote(py)} -I -m kyma hook"
    return f"{shlex.quote(script)} hook"


def console_script() -> str:
    """The `kyma` installed with this very Python, never the first one on PATH.

    `shutil.which("kyma")` finds whatever an earlier PATH entry holds, which
    may be another version, or a file an agent put there. A console script
    whose first line names this interpreter is this install's own."""
    me = os.path.realpath(sys.executable)
    for d in _scripts_dirs():
        cand = os.path.join(d, "kyma")
        if not (os.path.isfile(cand) and os.access(cand, os.X_OK)):
            continue
        try:
            with open(cand, "rb") as fh:
                first = fh.readline(4096).decode("utf-8", "replace")
        except OSError:
            continue
        m = re.match(r"#!\s*(?:'([^']+)'|\"([^\"]+)\"|(\S+))", first)
        shebang = m and (m.group(1) or m.group(2) or m.group(3))
        try:
            if shebang and os.path.realpath(shebang) == me:
                return cand
        except OSError:
            continue
    return ""


def hook_command() -> str:
    """Absolute and quoted: a space in a path, or a PATH change, must not
    silently disable the guard. And nothing the session's folder can supply:
    Claude Code runs the hook in the project, so `python3 -m kyma` there
    would import a kyma/ folder from the repository being worked on."""
    py = shlex.quote(interpreter())
    entry = _launcher()
    script = "" if entry else console_script()
    if entry:
        cmd = f"{py} -I {shlex.quote(entry)} hook"        # -I: no cwd, no PYTHON* variables
    else:
        # Never the console script itself: its Python honours PYTHONPATH, so PYTHONPATH=. and a
        # kyma/ folder in the repository would answer for kyma. The same Python with -I cannot.
        cmd = f"{py} -I -m kyma hook"
    # Always named: a KYMA_HOME set later in a profile or by `launchctl setenv`
    # must not move the hook to a folder of someone's choosing.
    return f"KYMA_HOME={shlex.quote(HOME)} {cmd}"


def _venv_of(exe: str) -> str:
    """The virtual environment an interpreter path belongs to, or ''. A venv's
    python is a link to its base Python: resolved, two venvs on one Python look
    the same, while each imports its own kyma."""
    d = os.path.dirname(os.path.dirname(os.path.abspath(exe)))
    return os.path.realpath(d) if os.path.isfile(os.path.join(d, "pyvenv.cfg")) else ""


def hook_identity(cmd):
    """-> what a hook command runs: (interpreter, module or script, KYMA_HOME),
    each resolved, so two spellings of one kyma compare equal; ("missing",
    path) when a file it runs is not there; None when it is not kyma's.

    The interpreter is the resolved Python plus the venv it sits in, if any:
    two venvs on the same base Python are two different kymas."""
    if not is_ours(cmd):
        return None
    try:
        words = shlex.split(cmd)
    except ValueError:
        return None
    env = {}
    while words and re.match(r"^[A-Za-z_]\w*=", words[0]):
        k, _, v = words.pop(0).partition("=")
        env[k] = v
    if not words:
        return None
    home = os.path.realpath(os.path.expanduser(env.get("KYMA_HOME") or "~/.kyma"))
    exe = words[0]
    if not os.path.isabs(exe):
        return ("other", cmd)            # whatever PATH finds first: never kyma's own
    if not os.path.exists(exe):
        return ("missing", exe)
    py = (os.path.realpath(exe), _venv_of(exe))
    rest = [w for w in words[1:] if w not in ("-I", "-E", "-s", "-B")]
    if rest[:2] == ["-m", "kyma"]:
        return (py, "module kyma", home)
    if rest and rest[0] != "hook":
        if os.path.isabs(rest[0]) and not os.path.exists(rest[0]):
            return ("missing", rest[0])
        return (py, os.path.realpath(rest[0]), home)
    # a kept console script: its own first line names its Python
    via = command_for_script(exe)
    if via != f"{shlex.quote(exe)} hook":
        r = hook_identity(via)
        return r if not r or r[0] == "missing" else (r[0], r[1], home)
    return (py, "script", home)


_OURS = re.compile(r"(?:^|[\s/'\"])kyma['\"]?\s+hook\s*$|\s-m\s+kyma\s+hook\s*$")


def is_ours(cmd) -> bool:
    return isinstance(cmd, str) and _OURS.search(cmd.strip()) is not None


_CACHE_MARKS = ("/.cache/uv/", "/uv/builds-v0/", "/pipx/venvs/.cache", "/Caches/uv/", "/archive-v0/",
                "/Caches/pipx/", "/.cache/pipx/", "/pipx/.cache/")


def _ephemeral(path: str) -> bool:
    """Will this file exist tomorrow? uvx and pipx caches and temp folders are cleaned."""
    p = os.path.realpath(path)
    roots = {os.path.realpath(tempfile.gettempdir()), "/tmp", "/private/tmp", "/var/folders",
             "/private/var/folders"}
    if any(p == r or p.startswith(r.rstrip("/") + "/") for r in roots):
        return True
    return any(m in p for m in _CACHE_MARKS)


def install_is_durable() -> tuple:
    # A test suite run from a clone in a temp folder installs from there on purpose.
    if os.environ.get("KYMA_TRUST_INSTALL_PATH") == "1":
        return True, ""
    for cand in (_launcher(), console_script(), os.path.abspath(__file__), sys.executable):
        if cand and _ephemeral(cand):
            return False, cand
    return True, ""


def _source_spec():
    """-> (what uv should install, so the kept copy is this one) or None.

    PEP 610's direct_url.json says where the running copy came from: a git
    commit, a local folder, an archive. Installing the default branch of the
    repository instead would plug in a kyma nobody has run."""
    try:
        from importlib import metadata
        dist = metadata.distribution("kyma-local")
        loc = dist.locate_file("kyma/__init__.py")
        if not os.path.exists(str(loc)) or not os.path.samefile(str(loc), os.path.join(os.path.dirname(__file__),
                                                                                       "__init__.py")):
            return None
        raw = dist.read_text("direct_url.json")
    except Exception:
        return None
    from . import __version__
    return spec_from_direct_url(raw, __version__)


def spec_from_direct_url(raw, version: str):
    """PEP 610 direct_url.json -> what `uv tool install` needs for the same copy."""
    if not raw:
        return f"kyma-local=={version}"
    try:
        d = json.loads(raw)
        url = d["url"]
    except (ValueError, KeyError, TypeError):
        return None
    if not isinstance(d, dict) or not isinstance(url, str):
        return None
    vcs = d.get("vcs_info") if isinstance(d.get("vcs_info"), dict) else None
    if vcs and vcs.get("vcs") == "git" and vcs.get("commit_id"):
        return f"git+{url}@{vcs['commit_id']}"
    if url.startswith("file://") and isinstance(d.get("dir_info"), dict):
        from urllib.parse import unquote, urlparse
        return unquote(urlparse(url).path)
    if isinstance(d.get("archive_info"), dict):
        return url
    return None


def keep_copy(ask=None, run=None):
    """Keep this copy of kyma with `uv tool install`, for a hook that lasts.
    -> (path of the kept kyma, '') or (None, why not).

    `ask` is asked before an existing kyma-local tool is replaced; without
    it, an existing one is left as it is. `run` stands in for subprocess.run."""
    import subprocess
    run = run or subprocess.run
    uv = shutil.which("uv")
    if not uv:
        return None, "uv is not installed"
    spec = _source_spec()
    if not spec:
        return None, "kyma cannot tell where this copy came from"
    try:
        listed = run([uv, "tool", "list"], capture_output=True, text=True, timeout=60).stdout or ""
    except Exception as exc:
        return None, f"uv tool list failed ({type(exc).__name__})"
    args = [uv, "tool", "install", "--python", sys.executable, spec]      # the Python you ran it with
    if re.search(r"(?m)^kyma-local\b", listed):
        if ask is None or not ask(f"Replace the kyma-local you already installed with this copy ({spec})? [y/N] "):
            return None, "a kyma-local tool is already installed; kyma left it alone"
        args.insert(3, "--force")   # after "install"
    try:
        run(args, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=300)
        bindir = run([uv, "tool", "dir", "--bin"], check=True, capture_output=True, text=True,
                     timeout=30).stdout.strip()
    except Exception as exc:
        said = _last_line(getattr(exc, "stderr", "") or "") if isinstance(getattr(exc, "stderr", ""), str) else \
            _last_line((getattr(exc, "stderr", b"") or b"").decode("utf-8", "replace"))
        return None, f"uv could not install it ({said or type(exc).__name__})"
    kept = os.path.join(bindir, "kyma")
    return (kept, "") if os.access(kept, os.X_OK) else (None, f"uv installed it, but {kept} is not there")


def _read_settings(path: str) -> tuple:
    """-> (data, fmt). Refuses anything it cannot round-trip.

    fmt keeps the file's own text (read with its newlines as they are), so an
    install can splice one entry into it and leave every other byte alone."""
    fmt = {"indent": 2, "newline": True, "nl": "\n", "text": None}
    if os.path.islink(path) and not os.path.exists(path):
        raise InstallError(f"{path} is a link to {os.readlink(path)}, which is not there. Create that file, "
                           "or remove the link, then run this again")
    if not os.path.lexists(path):
        return {}, fmt
    if os.path.isdir(path):
        raise InstallError(f"{path} is a folder, not a settings file")
    try:
        with open(path, encoding="utf-8", newline="") as fh:
            text = fh.read()
    except (OSError, UnicodeDecodeError) as exc:
        raise InstallError(f"cannot read {path} ({exc})")
    fmt["text"] = text
    if "\r\n" in text:
        fmt["nl"] = "\r\n"
    if not text.strip():
        return {}, fmt
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise InstallError(f"{path} is not valid JSON ({exc}). Fix it and run this again: "
                           "kyma never rewrites a file it cannot read") from None
    if not isinstance(data, dict):
        raise InstallError(f"{path} is not a JSON object, so kyma left it alone")
    m = re.search(r"\n([ \t]+)\S", text)
    if m:
        fmt["indent"] = "\t" if m.group(1).startswith("\t") else len(m.group(1))
    fmt["newline"] = text.endswith("\n")
    return data, fmt


def _write_settings(path: str, data: dict, fmt: dict, body: str | None = None) -> None:
    """Atomic. Writes through a symlink to its target, keeps mode, indent,
    newline style and unicode, and leaves nothing behind if it fails. With
    `body`, those exact characters are written instead of `data`."""
    real = os.path.realpath(path) if os.path.islink(path) else path
    folder = os.path.dirname(real) or "."
    os.makedirs(folder, exist_ok=True)
    if body is None:
        body = json.dumps(data, indent=fmt.get("indent", 2), ensure_ascii=False) + ("\n" if fmt.get("newline") else "")
        if fmt.get("nl") == "\r\n":
            body = body.replace("\n", "\r\n")
    fd, tmp = tempfile.mkstemp(prefix=".kyma-", suffix=".tmp", dir=folder)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(body.encode("utf-8"))
            fh.flush()
            os.fsync(fh.fileno())
        if os.path.isfile(real):
            shutil.copymode(real, tmp)
        os.replace(tmp, real)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _snapshot(path: str):
    try:
        with open(path, "rb") as fh:
            return fh.read()
    except OSError:
        return None


def _restore(path: str, before) -> None:
    """Put the bytes back exactly, through a temp file and one rename, with the mode kept."""
    real = os.path.realpath(path) if os.path.islink(path) else path
    if before is None:
        if os.path.isfile(real):
            os.unlink(real)
        return
    folder = os.path.dirname(real) or "."
    fd, tmp = tempfile.mkstemp(prefix=".kyma-", suffix=".tmp", dir=folder)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(before)
            fh.flush()
            os.fsync(fh.fileno())
        if os.path.isfile(real):
            shutil.copymode(real, tmp)
        os.replace(tmp, real)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


_SELF_TEST_REASON = "[kyma]"


def self_test(cmd: str, root: str, settings: str | None = None) -> tuple:
    """Run kyma's own hook command exactly as the host will, once.

    Only ever hook_command() or one kyma itself chose (a kept uv copy): never a
    string read back from a settings file, which a cloned repository's
    .claude/settings.local.json can fill with anything ending in `kyma hook`.
    And an answer of `{}` proves nothing, since any program can print that:
    the test asks the hook about an edit to the hook's own settings, which
    kyma, and only kyma, holds for a person."""
    target = settings or settings_path("global")
    payload = json.dumps({"hook_event_name": "PreToolUse", "tool_name": "Edit",
                          "tool_input": {"file_path": target, "old_string": "\"onFailure\": \"block\"",
                                         "new_string": ""}, "cwd": root})
    try:
        p = subprocess.run(["/bin/sh", "-c", cmd], input=payload, capture_output=True,
                           text=True, timeout=15, cwd=root, env=dict(os.environ, KYMA_SELF_TEST="1"))
    except Exception as exc:
        return False, str(exc)
    if p.returncode != 0:
        return False, _last_line(p.stderr) or _last_line(p.stdout) or f"exit {p.returncode}"
    try:
        out = json.loads(p.stdout or "{}")
    except ValueError:
        return False, "it answered with something that is not JSON"
    o = (out.get("hookSpecificOutput") or {}) if isinstance(out, dict) else {}
    if not isinstance(o, dict) or o.get("permissionDecision") not in ("ask", "deny") \
            or _SELF_TEST_REASON not in str(o.get("permissionDecisionReason") or ""):
        return False, "it let an edit of its own settings through, so it is not kyma answering"
    return True, ""


# What kyma changed, so that `kyma off` can undo exactly that: the bytes each
# settings file had before, a hash of what kyma wrote, and the containers
# ("hooks", "PreToolUse") that kyma had to create.
INSTALLS = os.path.join(HOME, "installs.json")


def _ledger() -> dict:
    try:
        d = json.loads(state_read(INSTALLS) or "{}")
    except (ValueError, RecursionError):
        return {}
    return {k: v for k, v in d.items() if isinstance(k, str) and isinstance(v, dict)} if isinstance(d, dict) else {}


def _ledger_put(d: dict) -> None:
    try:
        ensure_home()
        state_write(INSTALLS, json.dumps(d, indent=1))
    except OSError:
        pass


def _sha(b) -> str:
    import hashlib
    return hashlib.sha256(b).hexdigest() if b is not None else ""


def project_installs() -> list:
    """-> [(settings path, project root)] for every `kyma on --project` still recorded."""
    return [(p, e.get("root") or "") for p, e in _ledger().items() if e.get("scope") == "project"]


def _git_exclude(root: str, path: str):
    """A settings.local.json kyma created is local to this machine: keep it out of commits.
    -> what kyma added, so `kyma off` takes out exactly that, or ''. It is
    {"line", "newline", "made_file", "made_dir"}: the line, whether a newline
    went in before it (the file had none at its end), and whether kyma
    created .git/info/exclude or .git/info itself."""
    info = os.path.join(root, ".git", "info")
    if not os.path.isdir(os.path.join(root, ".git")):
        return ""
    line = "/" + os.path.relpath(path, root).replace(os.sep, "/")
    ex = os.path.join(info, "exclude")
    made_dir = not os.path.isdir(info)
    made_file = not os.path.lexists(ex)
    try:
        os.makedirs(info, exist_ok=True)
        try:
            with open(ex, encoding="utf-8", newline="") as fh:
                have = fh.read()
        except OSError:
            have = ""
        if line not in have.splitlines():
            lead = "" if not have or have.endswith("\n") else "\n"
            with open(ex, "a", encoding="utf-8", newline="") as fh:
                fh.write(lead + line + "\n")
            return {"line": line, "newline": bool(lead), "made_file": made_file, "made_dir": made_dir}
    except OSError:
        pass
    return ""


def _git_unexclude(root: str, line) -> None:
    """Take out what _git_exclude added, exactly: the newline it put before the
    line too, and the file and folder if kyma created them. `line` is that
    record, or a bare line from an older kyma."""
    rec = line if isinstance(line, dict) else {"line": line}
    line = rec.get("line")
    if not isinstance(line, str) or not line:
        return
    info = os.path.join(root, ".git", "info")
    ex = os.path.join(info, "exclude")
    try:
        with open(ex, encoding="utf-8", newline="") as fh:
            have = fh.read()
        tail = ("\n" if rec.get("newline") else "") + line + "\n"
        if have.endswith(tail):
            new = have[:-len(tail)]          # appended last, and still last: undo the append
        else:
            rows = have.splitlines(keepends=True)
            new = "".join(r for r in rows if r.rstrip("\r\n") != line)
        if new == have:
            return
        if not new and rec.get("made_file"):
            os.unlink(ex)
            if rec.get("made_dir") and not os.listdir(info):
                os.rmdir(info)
            return
        with open(ex, "w", encoding="utf-8", newline="") as fh:
            fh.write(new)
    except OSError:
        pass


# Splicing one entry into a settings file. Re-serialising the whole file
# reflowed compact one-line JSON, CRLF newlines, é escapes and inline
# objects inside tab-indented files, and an empty file came back as {}. So kyma
# inserts its entry into the file's own text, records where and how long it
# is, and `kyma off` takes out exactly those bytes while the file is unchanged.
_JSON_ATOM = re.compile(r"-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?|true|false|null")
_JSON_WS = " \t\r\n"


def _ws(t: str, i: int) -> int:
    while i < len(t) and t[i] in _JSON_WS:
        i += 1
    return i


def _json_end(t: str, i: int) -> int:
    """-> the index just past the JSON value that starts at t[i]. Iterative: no depth limit."""
    c = t[i]
    if c == '"':
        j = i + 1
        while True:
            k = t.index('"', j)
            n, b = 0, k - 1
            while t[b] == "\\":
                n, b = n + 1, b - 1
            if n % 2 == 0:
                return k + 1
            j = k + 1
    if c in "{[":
        depth, j = 0, i
        while j < len(t):
            ch = t[j]
            if ch == '"':
                j = _json_end(t, j)
                continue
            if ch in "{[":
                depth += 1
            elif ch in "}]":
                depth -= 1
                if not depth:
                    return j + 1
            j += 1
        raise ValueError("unterminated")
    m = _JSON_ATOM.match(t, i)
    if not m:
        raise ValueError(f"not JSON at {i}")
    return m.end()


def _json_members(t: str, open_i: int) -> tuple:
    """-> ([(key or None, start, value start, value end)], index of the closing bracket)."""
    out, arr = [], t[open_i] == "["
    i = _ws(t, open_i + 1)
    if t[i] in "]}":
        return out, i
    while True:
        start, key = i, None
        if not arr:
            kend = _json_end(t, i)
            key = json.loads(t[i:kend])
            i = _ws(t, kend)
            if t[i] != ":":
                raise ValueError("no colon")
            i = _ws(t, i + 1)
        vend = _json_end(t, i)
        out.append((key, start, i, vend))
        i = _ws(t, vend)
        if t[i] == ",":
            i = _ws(t, i + 1)
            continue
        if t[i] in "]}":
            return out, i
        raise ValueError("no comma")


def _line_of(t: str, i: int) -> tuple:
    """-> (the indentation of the line holding t[i], whether t[i] begins that line)."""
    s = t.rfind("\n", 0, i) + 1
    lead = t[s:i]
    return re.match(r"[ \t]*", lead).group(0), not lead.strip()


def _splice_entry(text: str, created: list, group: dict, fmt: dict):
    """-> (new text, character offset, inserted text, replaced text): `group`
    appended to hooks.PreToolUse in the file's own text and style."""
    if not text.strip():
        body = json.dumps({"hooks": {"PreToolUse": [group]}}, indent=2, ensure_ascii=False) + "\n"
        if fmt.get("nl") == "\r\n":
            body = body.replace("\n", "\r\n")
        return body, 0, body, text             # only whitespace is replaced, and recorded
    top = _ws(text, 0)
    if text[top] != "{":
        raise ValueError("not an object")

    def last(open_i, key):
        hit = [m for m in _json_members(text, open_i)[0] if m[0] == key]
        if not hit:
            raise ValueError(f"no {key}")
        return hit[-1][2]                       # the last one, as json.loads reads duplicates
    if "hooks" in created:
        at, key, value = top, "hooks", {"PreToolUse": [group]}
    elif "PreToolUse" in created:
        at, key, value = last(top, "hooks"), "PreToolUse", [group]
    else:
        at, key, value = last(last(top, "hooks"), "PreToolUse"), None, group
    if text[at] != ("[" if key is None else "{"):
        raise ValueError("unexpected container")
    nl = "\r\n" if "\r\n" in text else "\n"
    unit = fmt.get("indent", 2)
    unit_s = unit if isinstance(unit, str) else " " * int(unit)
    colon = ": " if re.search(r'"[ \t]*:[ \t\r\n]', text) or '":' not in text else ":"
    asc = text.isascii() and "\\u" in text
    members, close = _json_members(text, at)
    if members:
        inner, pretty = _line_of(text, members[-1][1])
    else:
        outer, _ = _line_of(text, at)
        inner, pretty = outer + unit_s, "\n" in text
    if pretty:
        val = json.dumps(value, indent=unit, ensure_ascii=asc, separators=(",", colon)).replace("\n", nl + inner)
    else:
        if len(members) > 1:
            sp = " " if text[members[-2][3]:members[-1][1]].startswith(", ") else ""
        else:
            sp = " " if re.search(r",[ ]\S", text) or (colon == ": " and not re.search(r",[\"{\[]", text)) else ""
        val = json.dumps(value, ensure_ascii=asc, separators=("," + sp, colon))
    item = (json.dumps(key, ensure_ascii=asc) + colon if key is not None else "") + val
    if members:
        pos = members[-1][3]
        if pretty:
            ins = "," + nl + inner + item
        else:
            ins = "," + sp + item
    else:
        pos = at + 1
        if pretty:
            ins = nl + inner + item + ("" if "\n" in text[at + 1:close] else nl + outer)
        else:
            ins = item
    return text[:pos] + ins + text[pos:], pos, ins, ""


def install(scope: str = "project", root: str | None = None, command: str | None = None) -> tuple:
    root = root or project_root()
    cdir = sources.claude_dir()
    if not os.path.isdir(cdir):
        # The hook is Claude Code's. Creating its folder and saying "On" would be a guard with no host.
        raise InstallError(f"Claude Code was not found: {_short(cdir)} does not exist. Install Claude Code, "
                           "run it once, then run this again")
    path = settings_path(scope, root)
    real = os.path.realpath(path) if os.path.islink(path) else path
    folder = os.path.dirname(real) or "."
    if os.path.lexists(real) and not os.access(real, os.W_OK):
        raise InstallError(f"{path} is read-only, so kyma left it alone")
    if os.path.isdir(folder) and not os.access(folder, os.W_OK | os.X_OK):
        raise InstallError(f"{folder} is read-only, so kyma left it alone")
    data, fmt = _read_settings(path)
    before = _snapshot(path)
    created = [k for k in ("hooks",) if "hooks" not in data]
    hooks = data.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise InstallError(f"{path}: 'hooks' is not an object, so kyma left it alone")
    if "PreToolUse" not in hooks:
        created.append("PreToolUse")
    pre = hooks.setdefault("PreToolUse", [])
    if not isinstance(pre, list):
        raise InstallError(f"{path}: 'hooks.PreToolUse' is not a list, so kyma left it alone")
    cmd = command or hook_command()
    if not re.match(r"^KYMA_HOME=", cmd):
        cmd = f"KYMA_HOME={shlex.quote(HOME)} {cmd}"
    if os.environ.get("KYMA_HOME") and _ephemeral(os.path.realpath(HOME)) and not os.environ.get("KYMA_ALLOW_TEMP_HOME"):
        raise InstallError(f"KYMA_HOME is {HOME}, a temporary folder: a hook pointing at it would stop "
                           "guarding when it is cleaned up")
    status = "installed"
    for group in pre:
        for h in (group.get("hooks") or []) if isinstance(group, dict) else []:
            if isinstance(h, dict) and is_ours(h.get("command")):
                status = "already on" if h.get("command") == cmd and h.get("onFailure") == "block" else "updated"
                h["command"] = cmd
                h["onFailure"] = "block"     # Claude Code 2.1.295+: a hook that cannot run holds the call
    splice = None
    body = None
    if status == "installed":
        group = {"matcher": "*", "hooks": [{"type": "command", "command": cmd, "timeout": 10,
                                            "onFailure": "block"}]}
        pre.append(group)
        try:
            new, pos, ins, was = _splice_entry(fmt.get("text") or "", created, group, fmt)
            if json.loads(new) == data:         # the splice says exactly what kyma meant, or is not used
                body = new
                splice = {"at": len(new[:pos].encode("utf-8")), "len": len(ins.encode("utf-8")), "was": was}
        except (ValueError, IndexError, TypeError, RecursionError):
            pass
    made_folder = not os.path.isdir(folder)
    if status != "already on":
        _write_settings(path, data, fmt, body=body)
    ok, why = self_test(cmd, root, path)
    if not ok:
        if status == "already on":
            raise InstallError(f"the hook in {path} does not run ({why})")
        try:
            _restore(path, before)
            if made_folder:
                os.rmdir(folder)
        except OSError as exc:
            raise InstallError(f"the hook was written but did not run ({why}), and kyma could not take it "
                               f"out again ({exc}). It is still in {path}: remove it, or run `kyma off`")
        raise InstallError(f"the hook was written but did not run ({why}). It was taken out again, "
                           "so nothing changed")
    led = _ledger()
    prior = led.get(path) or {}
    if not prior or status == "installed" or "before" in prior:
        # Only what undoing needs: whether the file existed, a hash of its bytes, and
        # what kyma added. Never a copy of the file: settings hold env values and keys.
        prior = {"existed": before is not None, "before_sha": _sha(before), "created": created,
                 "made_folder": made_folder}
    if status != "already on":
        prior.pop("splice", None)           # offsets into an earlier version of the file
    if splice:
        prior["splice"] = splice
    prior.update(scope=scope, root=root if scope == "project" else "", after=_sha(_snapshot(path)))
    led[path] = prior
    _ledger_put(led)
    if scope == "project" and before is None:
        added = _git_exclude(root, path)
        if added:
            led[path]["excluded"] = added
            _ledger_put(led)
    return path, status


def uninstall(scope: str = "project", root: str | None = None, path: str | None = None) -> tuple:
    path = path or settings_path(scope, root)
    entry = _ledger().get(path) or {}
    out = _uninstall(scope, root, path)
    if entry.get("excluded") and entry.get("root") and out[1] in ("removed", "not installed"):
        _git_unexclude(entry["root"], entry["excluded"])      # the line kyma added, and only that
    return out


def _uninstall(scope: str, root, path: str) -> tuple:
    led = _ledger()
    entry = led.get(path)
    if not os.path.lexists(path):
        if entry:
            led.pop(path, None)
            _ledger_put(led)
        return path, "not installed"
    cur = _snapshot(path)
    sp = entry.get("splice") if entry else None
    if isinstance(sp, dict) and cur is not None and entry.get("after") and _sha(cur) == entry["after"]:
        # The file is byte for byte what kyma wrote: take out exactly the span it inserted.
        try:
            at, n, was = int(sp["at"]), int(sp["len"]), str(sp.get("was") or "").encode("utf-8")
        except (KeyError, TypeError, ValueError):
            at = None
        if at is not None and 0 <= at <= at + n <= len(cur):
            before = cur[:at] + was + cur[at + n:]
            if not entry.get("existed") and not before.strip():
                real = os.path.realpath(path)
                os.unlink(real if os.path.isfile(real) else path)
                folder = os.path.dirname(path)
                try:
                    if entry.get("made_folder") and os.path.basename(folder) == ".claude" and not os.listdir(folder):
                        os.rmdir(folder)
                except OSError:
                    pass
                led.pop(path, None)
                _ledger_put(led)
                return path, "removed"
            if _sha(before) == entry.get("before_sha"):
                _restore(path, before)
                led.pop(path, None)
                _ledger_put(led)
                return path, "removed"
    if entry and "before" in entry and cur is not None and entry.get("after") and _sha(cur) == entry["after"]:
        # a record from an older kyma, which kept the bytes: used once, then gone with the record
        # Nothing else changed the file since kyma wrote it: put back the very bytes it had.
        import base64
        try:
            before = None if entry.get("before") is None else base64.b64decode(entry["before"])
        except (ValueError, TypeError):
            before = cur
        if before != cur:
            _restore(path, before)
            if before is None and entry.get("made_folder"):
                try:
                    os.rmdir(os.path.dirname(path))
                except OSError:
                    pass
            led.pop(path, None)
            _ledger_put(led)
            return path, "removed"
    try:
        data, fmt = _read_settings(path)
    except InstallError as exc:
        raw = (cur or b"").decode("utf-8", "replace")
        if not re.search(r"kyma['\"]?\s+hook|-m\s+kyma\s+hook", raw):
            # nothing of kyma's is in it (or it is a link to nothing): there is nothing to turn off
            if entry:
                led.pop(path, None)
                _ledger_put(led)
            return path, "not installed"
        return path, f"left alone: {exc}"
    hooks = data.get("hooks")
    pre = hooks.get("PreToolUse") if isinstance(hooks, dict) else None

    def forget():
        if entry:
            led.pop(path, None)
            _ledger_put(led)
    if not isinstance(pre, list):
        forget()
        return path, "not installed"
    removed = 0
    for group in list(pre):
        if not isinstance(group, dict) or not isinstance(group.get("hooks"), list):
            continue
        keep = [h for h in group["hooks"] if not (isinstance(h, dict) and is_ours(h.get("command")))]
        if len(keep) != len(group["hooks"]):
            removed += len(group["hooks"]) - len(keep)
            group["hooks"] = keep
            if not keep:
                pre.remove(group)
    if not removed:
        forget()
        return path, "not installed"
    # Only the containers kyma made. With no record (installed before kyma
    # kept one), empty ones go, as they always did.
    made = entry.get("created", ["hooks", "PreToolUse"]) if entry else ["hooks", "PreToolUse"]
    if not pre and "PreToolUse" in made:
        hooks.pop("PreToolUse", None)
        if not hooks and "hooks" in made:
            data.pop("hooks", None)
    if entry:
        led.pop(path, None)
        _ledger_put(led)
    if not data and os.path.islink(path):
        _write_settings(path, data, fmt)     # keep the dotfile the link points at
        return path, "removed"
    existed = entry.get("existed", entry.get("before") is not None) if entry else False
    if not data and not existed:
        real = os.path.realpath(path)
        os.unlink(real if os.path.isfile(real) else path)
        folder = os.path.dirname(path)
        try:
            if os.path.basename(folder) == ".claude" and not os.listdir(folder) and (not entry or entry.get("made_folder")):
                os.rmdir(folder)
        except OSError:
            pass
        return path, "removed"
    _write_settings(path, data, fmt)
    return path, "removed"


def removed_hooks() -> list:
    """Settings files kyma installed into (and `kyma off` has not undone)
    whose kyma hook is gone: someone took it out by hand, or an agent did."""
    out = []
    for path, e in _ledger().items():
        try:
            data, _ = _read_settings(path)
        except InstallError:
            continue
        found = any(isinstance(h, dict) and is_ours(h.get("command"))
                    for g in (((data.get("hooks") or {}).get("PreToolUse") or [])
                              if isinstance(data.get("hooks"), dict) else [])
                    for h in ((g.get("hooks") or []) if isinstance(g, dict) else []))
        if not found:
            out.append(path)
    return out


def installed_command(scope: str, root: str | None = None):
    try:
        data, _ = _read_settings(settings_path(scope, root))
    except InstallError:
        return None
    for group in ((data.get("hooks") or {}).get("PreToolUse") or []) if isinstance(data.get("hooks"), dict) else []:
        for h in (group.get("hooks") or []) if isinstance(group, dict) else []:
            if isinstance(h, dict) and is_ours(h.get("command")):
                return h.get("command")
    return None


# Settings an administrator sets for every user; they win over yours.
MANAGED_SETTINGS = ["/Library/Application Support/ClaudeCode/managed-settings.json",
                    "/etc/claude-code/managed-settings.json"]


def hooks_off_reason(root: str | None = None) -> str:
    """-> why Claude Code would run no hook of kyma's here, or ''.

    `disableAllHooks` in your settings, the project's, or the managed ones
    turns every hook off; `allowManagedHooksOnly` in managed settings runs
    only an administrator's hooks. Either way, "On" would be a false word."""
    files = [(p, True) for p in MANAGED_SETTINGS] + [(settings_path("global"), False)]
    r = root or project_root()
    files += [(os.path.join(r, ".claude", n), False) for n in ("settings.json", "settings.local.json")]
    for p, managed in files:
        try:
            data, _ = _read_settings(p)
        except (InstallError, OSError):
            continue
        if data.get("disableAllHooks") is True:
            return f"disableAllHooks is on in {_short(p)}: Claude Code runs no hook, kyma's included"
        if managed and data.get("allowManagedHooksOnly") is True:
            return f"allowManagedHooksOnly is on in {p}: Claude Code runs only your administrator's hooks"
    return ""


def hooks_disabled(scope: str = "global", root: str | None = None) -> bool:
    """Would Claude Code run no hook of kyma's? See hooks_off_reason()."""
    return bool(hooks_off_reason(root))


def is_installed(scope: str = "project", root: str | None = None) -> bool:
    return installed_command(scope, root) is not None
