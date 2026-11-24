"""The ten things people actually get uneasy about.

This file is deliberately short. An earlier version of this product reported
everything it could prove, and the result was unreadable: 1,097 "files written
outside the project" of which 1,097 were scratch directories. Curation is the
feature. A signal earns a place here only if a reasonable person, shown the
number, would want to do something about it.

Each signal is (id, label, severity, regex over the action subject).
severity "sharp" prints in the report body. severity "wide" prints as volume.
"""

from __future__ import annotations

import os
import re

# Paths that are noise, not news: the agent's own scratch space.
NOISE_PATH = re.compile(
    r"(/\.?(tmp|temp)/|/var/folders/|/private/tmp/|scratch-workspaces?/|"
    r"/scratchpad/|/node_modules/|/\.git/|/\.venv/|/__pycache__/|/\.cache/)",
    re.I,
)


def _bases(cwd) -> list:
    """Where the person's own files are: their home, and the folder the session ran in.

    Both spellings of each, because macOS logs /var/folders and /private/var/folders
    for the same folder, and history paths are never resolved on disk."""
    out = []
    for b in (os.path.expanduser("~"), cwd if isinstance(cwd, str) and cwd.startswith("/") else ""):
        if not b or b == "/":
            continue
        for v in (b, os.path.realpath(b)):
            v = v.rstrip("/")
            if v and v not in out:
                out.append(v)
    return out


def noise(path: str, rx=NOISE_PATH, cwd=None) -> bool:
    """Is this path scratch, judged only on the part below the person's own folders?

    A temp folder is noise because nobody keeps work there. That stops being
    true for the part of a path below HOME or the session's folder: CI, a
    sandbox and a Claude scratch workspace all put HOME or cwd inside a temp
    root, and a filter that looked at the whole path then hid every real
    finding there (`rm -rf ~/Documents/project` read as scratch). So the
    prefix that is HOME or cwd is skipped, and only what lies below it can
    make a path noise. `node_modules` below HOME is still noise; a scratch
    workspace under ~/Library is still noise unless the session ran in it."""
    if not path or not rx.search(path):
        return False
    start = 0
    for b in _bases(cwd):
        if (path == b or path.startswith(b + "/")) and len(b) > start:
            start = len(b)
    if not start:
        return True
    # search from the "/" after the base: `^` cannot match there, `(?:^|/)` can
    return rx.search(path, start) is not None

SIGNALS = [
    (
        "secrets",
        "read or printed a credential file",
        "sharp",
        # "\.env\.[a-z]" without the lookbehind matched process.env.FOO in every
        # JavaScript file an agent ever touched. The lookbehind is the fix.
        r"(?:(?<![\w/.-])\.env\b|/\.env|(?<!\w)\.env\.[a-z]|"
        r"\bid_rsa\b|\bid_ed25519\b|~?/\.ssh/|~?/\.aws/credentials|"
        r"\bsecurity\s+find-(?:generic|internet)-password|"
        r"\bgcloud\s+auth\s+print|\.netrc|\bcredentials\.json\b|"
        r"\bgh\s+auth\s+token\b|\bop\s+(?:read|item\s+get)\b)",
    ),
    (
        "egress",
        "sent or fetched data over the network",
        "sharp",
        r"(?:^|[|&;(`]\s*|\s)(?:curl|wget|nc|ncat|scp|rsync|sftp|ftp|"
        r"aws\s+s3\s+cp|gsutil\s+cp|http|httpie)\b",
    ),
    (
        "outbound",
        "sent a message to a human",
        "sharp",
        # Three versions of this pattern were wrong in opposite directions.
        # A hand-list of mailers let a program called send-mail through. The
        # fix -- any token containing "mail" -- then matched `gmail search`,
        # `gmail read` and `from email.parser import`, i.e. reading mail, and
        # a rule that prompts on every read is a rule people uninstall. What
        # it actually takes is a sending VERB, or an address being handed to
        # a --to flag.
        r"(?:"
        r"(?:^|[/\s;|&])(?:sendmail|send[-_]?mail|mail[-_]?send|msmtp|swaks|mailx)\b"
        r"|\bmail\s+-s\b|\b(?:neo)?mutt\b[^\n]*\s-s\b"
        r"|\b(?:gmail|mail|mailbox|imap|smtp|inbox)\b[^\n]{0,24}?"
        r"\b(?:send|forward|reply|deliver)\b"
        r"|\b(?:send|forward|reply|deliver)[\s_-][^\n]{0,24}?"
        r"\b(?:gmail|mail|message|email|sms|dm)\b"
        r"|--to[= ]\s*\"?[\w.+-]+@[\w-]+\.[\w.-]+"
        r"|\b(?:sendgrid|postmark|mailgun|twilio|courier)\b|\bresend\."
        r"|/messages\\?\.send|chat\\?\.postMessage|/v3/mail/send"
        r"|\bses\s+send-email\b|sendMessage"
        r"|\bosascript\b[^\n]*\bMessages\b"
        r")",
    ),
    (
        "destructive",
        "deleted or reset something irreversibly",
        "sharp",
        r"(?:\brm\s+-[a-zA-Z]*[rf]|\brm\s+-[a-zA-Z]*\s+-[a-zA-Z]*[rf]|"
        r"\bgit\s+reset\s+--hard\b|\bgit\s+clean\s+-[a-z]*[fd]|"
        r"\bdrop\s+(?:table|database)\b|\btruncate\s+table\b|"
        r"\bshred\b|\bdd\s+if=.*\bof=/dev/)",
    ),
    (
        "publish",
        "published code or opened a pull request",
        "sharp",
        r"(?:\bgit\s+push\b|\bgh\s+pr\s+create\b|\bgh\s+release\s+create\b|"
        r"\bnpm\s+publish\b|\btwine\s+upload\b|\bgit\s+tag\s+-)",
    ),
    (
        "persistence",
        "set something to run by itself later: on a schedule, at startup, or on a git event",
        "sharp",
        # Only acts that install something. The previous pattern matched any
        # mention: `crontab -l` (which lists), `ls ~/Library/LaunchAgents`, and
        # heredocs writing source code that contains the word launchctl. On
        # one machine 59 of 80 hits scheduled nothing. Writes INTO a
        # LaunchAgents directory are decided per segment, in _persists().
        # Command position only: start of a line, or after ; && || | ( or $(.
        # Without it the scheduler `at` matched English: "At 5:54 p.m. the
        # report..." inside an echo counted as scheduling a job, 349 times.
        r"(?:(?:^|(?<=[\n;&|(`]))\s*(?:sudo\s+(?:-\S+\s+)*)?(?-i:"
        r"launchctl\s+(?:load|bootstrap|enable|submit)\b|"
        r"crontab\s+(?:-e\b|-(?=\s|$)|(?!-)[^\s;|&]+)|"
        r"systemctl\s+(?:--user\s+)?enable\b|"
        r"at\s+(?:now|midnight|noon|teatime|\d{1,2}(?::?\d\d)?)\b|"
        r"pm2\s+(?:start|startup|save)\b)"
        r"|\bmake\s+(?:new\s+)?login\s+item)",
    ),
    (
        "background",
        "left a process running after the session",
        "wide",
        r"(?:^|\s)(?:nohup|disown|setsid)\b|\bscreen\s+-\S*d|\btmux\s+new(?:-session)?\b.*\s-d\b",
    ),
    (
        "privilege",
        "asked for or widened privileges",
        "sharp",
        r"(?:\bsudo\b|\bsu\s+-\b|\bchmod\s+(?:[0-7]*7[0-7]{2}|\+s)\b|"
        r"\bchown\s+(?:root|-R)\b|\bdscl\b|\bspctl\s+--master-disable\b)",
    ),
    (
        "supplychain",
        "installed third-party code",
        "sharp",
        r"(?:\bnpm\s+(?:i|install|add)\b|\bpnpm\s+add\b|\byarn\s+add\b|"
        r"\bpip\s+install\b|\buv\s+(?:pip\s+install|add)\b|\bbrew\s+install\b|"
        r"\bgem\s+install\b|\bcargo\s+install\b|\bgo\s+install\b)",
    ),
    (
        "database",
        "talked to a database directly",
        "wide",
        r"(?:\bpsql\b|\bmysql\b|\bmongosh?\b|\bredis-cli\b|\bsqlite3\b|"
        r"\bsupabase\s+db\b|\bprisma\s+(?:migrate|db)\b)",
    ),
    (
        "git_history",
        "rewrote git history",
        "wide",
        r"(?:\bgit\s+(?:rebase|commit\s+--amend|filter-branch|push\s+--force|"
        r"push\s+-f)\b)",
    ),
]

# ------------------------------------------------------------------ findings
#
# Counts do not land. "1,263 network calls" invites the honest reply "yes, I
# asked it to fetch things." What lands is a specific, surprising conjunction
# that nobody would have asked for. These are the things a person did not know
# were in their own logs.

FINDINGS = [
    (
        "self_modify",
        "edited your agent's own instructions or permissions",
        r"(?:~?/\.claude/(?:settings|CLAUDE|hooks)|~?/\.codex/(?:config|AGENTS|hooks)|"
        r"/\.claude/settings[\w.]*\.json|\bCLAUDE\.md\b|\bAGENTS\.md\b|"
        r"~?/\.cursor/|\.mcp\.json)",
    ),
    (
        "curl_pipe_shell",
        "downloaded code and ran it in the same breath",
        r"(?:curl|wget)\b[^|;&]*\|\s*(?:sudo\s+)?(?:sh|bash|zsh|python3?|node|ruby|perl)\b",
    ),
    (
        "shell_profile",
        "changed the shell that opens every new terminal you use",
        r"(?:>>?\s*~?/?\.(?:zshrc|bashrc|bash_profile|zprofile|profile)\b|"
        r"\b(?:tee|sed\s+-i)\b[^|;&\n]*\.(?:zshrc|bashrc|bash_profile|zprofile|profile)\b)",
    ),
]

# Conjunctions: two signals inside one command. The pair is the news.
COMBOS = [
    ("secrets_and_egress", "read a credential and reached the network in one command",
     ("secrets", "egress")),
    ("secrets_and_outbound", "read a credential and sent a message in one command",
     ("secrets", "outbound")),
    ("destructive_and_privilege", "deleted something as root", ("destructive", "privilege")),
]

SIGNALS = SIGNALS + [(i, l, "finding", p) for i, l, p in FINDINGS]

COMPILED = [(sid, label, sev, re.compile(pat, re.I)) for sid, label, sev, pat in SIGNALS]
BY_ID = {sid: (label, sev) for sid, label, sev, _ in SIGNALS}
SHARP = [sid for sid, _, sev, _ in SIGNALS if sev == "sharp"]
FINDING_IDS = [sid for sid, _, sev, _ in SIGNALS if sev == "finding"] + [c[0] for c in COMBOS]
BY_ID.update({i: (l, "finding") for i, l, _ in FINDINGS})
BY_ID.update({i: (l, "finding") for i, l, _ in COMBOS})


# --------------------------------------------------------- what actually ran
#
# Every label above claims an action: edited, ran, scheduled, deleted. The
# first matchers detected mentions. On one machine "987 edited your agent's
# own instructions" held 17 shell edits; 412 commands only read the file and
# 316 only mentioned it inside a heredoc being written to some other file.
# "129 downloaded code and ran it" held 8: the other 121 piped JSON into
# `python3 -c`, where the download is data and the program is local.
#
# So findings match on what executed. A heredoc body written to a file is
# data and is dropped -- unless it feeds an interpreter, or the same command
# goes on to run the file it just wrote, because then it ran.
#
# The gate does not use this. It matches raw text on purpose: a gate that
# ignored heredoc bodies could be walked past with `cat > x.sh <<EOF ... EOF
# && bash x.sh`. A finding is a claim, so precision wins; a gate is a door,
# so an extra prompt is cheaper than an escape.

_HEREDOC = re.compile(r"<<(-?)\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\2")
_INTERP = (r"(?:python3?(?:\.\d+)?|node|deno|bun|ruby|perl|php|bash|sh|zsh|fish|"
           r"osascript|psql|mysql|sqlite3|ssh|docker\s+exec|kubectl\s+exec)")
_FEEDS_INTERP = re.compile(r"(?:^|[|&;(]\s*)\s*(?:sudo\s+(?:-\S+\s+)*)?(?:env\s+(?:\w+=\S*\s+)*)?"
                           r"(" + _INTERP + r")\b[^|;&]*$")
_SHELLS = ("bash", "sh", "zsh", "fish", "ssh")
# Python, Node and the rest hold shell pipelines only as string literals until
# something hands them to os.system: a test file listing "curl x | sh" as a
# case to detect is not a download being run.
_STRINGS = re.compile(r'"""[\s\S]*?"""|\'\'\'[\s\S]*?\'\'\'|"(?:\\.|[^"\\\n])*"|\'(?:\\.|[^\'\\\n])*\'')
_WRITE_TARGET = re.compile(r"(?:\bcat\s*>>?|\btee\s+(?:-a\s+)?|>>?)\s*['\"]?([^\s'\"<>|;&]+)")


def _last_segment(head: str) -> str:
    return re.split(r"\|\||&&|[|;]", head)[-1]


def _runs_later(head: str, command: str) -> bool:
    m = _WRITE_TARGET.search(head)
    if not m:
        return False
    path = m.group(1)
    base = path.rsplit("/", 1)[-1]
    runner = (r"(?:\b(?:bash|sh|zsh|python3?|node|ruby|perl|source|exec)\s+(?:-\S+\s+)*"
              r"|(?<![\w/.-])\.\s+|\./)['\"]?")
    return bool(re.search(runner + r"\S*" + re.escape(base) + r"\b", command))


def executed(command: str, shell_only: bool = False) -> str:
    """The command as it ran: heredoc bodies that were only written somewhere
    are removed, bodies fed to an interpreter (or run afterwards) are kept.
    With shell_only, string literals inside non-shell interpreter bodies are
    blanked, for signals that are shell constructs."""
    if "<<" not in command or "\n" not in command:
        return command
    lines = command.split("\n")
    out, i = [], 0
    while i < len(lines):
        line = lines[i]
        out.append(line)
        i += 1
        for m in _HEREDOC.finditer(line):
            dash, word = m.group(1), m.group(3)
            j, body = i, []
            while j < len(lines):
                cand = lines[j].lstrip("\t") if dash else lines[j]
                if cand.strip() == word:
                    break
                body.append(lines[j])
                j += 1
            if j >= len(lines):
                continue          # no terminator: not a heredoc after all (e.g. `<<<`)
            head = line[:m.start()]
            feeds = _FEEDS_INTERP.search(_last_segment(head))
            if feeds or _runs_later(head, command):
                interp = feeds.group(1).split()[0] if feeds else "sh"
                if shell_only and not interp.startswith(_SHELLS):
                    out.extend(_STRINGS.sub('""', "\n".join(body)).split("\n"))
                else:
                    out.extend(body)
            i = j + 1
    return "\n".join(out)


def _segments(text: str) -> list:
    return [seg for seg in re.split(r"\n|;|\|\||&&|\|(?!\|)", text) if seg.strip()]


# ------------------------------------------------------------ what each unit did
#
# Findings are claims, so they are judged on the units a command actually ran
# (kyma/shell.py), with precision rules on top. The gate (rules.py) reads the
# same units with recall rules. Same reading, different thresholds.

from . import shell as _shell      # noqa: E402

_LOCAL = re.compile(r"^(?:localhost|127(?:\.\d{1,3}){3}|0\.0\.0\.0|\[?::1\]?|[\w.-]+\.local|"
                    r"[\w.-]+\.localhost|host\.docker\.internal|[\w-]+\.internal)$", re.I)
_URLHOST = re.compile(r"(?i)\b[a-z][a-z0-9+.-]{0,15}://(?:[^/\s@'\"]+@)?([^/\s:'\"?#]+)")
_NETCLI = {"curl", "wget", "nc", "ncat", "netcat", "socat", "scp", "sftp", "ftp", "telnet", "aria2c",
           "xh", "httpie", "ssh", "rsync", "http", "https"}
_HELP = re.compile(r"(?:^|\s)(?:--help|-h|--version|-V|--dry-run|-n|--dryrun|help)(?:\s|$)")
_NOISE_TARGET = re.compile(r"(?:^|/)(?:node_modules|dist|build|\.next|target|__pycache__|\.pytest_cache|"
                           r"coverage|\.cache|\.venv|venv|\.turbo|\.parcel-cache|out)(?:/|$)|^/(?:private/)?tmp/|"
                           r"/var/folders/|\.(?:log|tmp|pyc|o)$")
_AGENT_CFG = re.compile(r"/\.claude/(?:settings[\w.]*\.json|CLAUDE\.md|hooks/|skills/|rules/|agents/|commands/|"
                        r"output-styles/)|/\.claude\.json$|/\.codex/|(?:^|/)(?:CLAUDE|AGENTS|GEMINI)\.md$|\.mcp\.json$|"
                        r"/\.cursor/|\.cursorrules$|/\.config/claude|/\.gemini/|/\.aider|\.windsurfrules$|/\.continue/")


def _from_head(u) -> str:
    """`xargs rm x`, `sudo -E rm x`, `env A=1 rm x` all run rm: match from the command itself."""
    words = u.text.split()
    for i, w in enumerate(words):
        if os.path.basename(w) == u.head:
            return " ".join(words[i:])
    return u.text


def _hosts(u) -> list:
    out = [m.group(1).lower() for m in _URLHOST.finditer(u.text)]
    words = u.text.split()
    if u.head in ("ssh", "scp", "sftp", "rsync"):
        for w in words[1:]:
            if w.startswith("-"):
                continue
            m = re.match(r"^(?:[\w.-]+@)?([\w.-]+):", w) if u.head != "ssh" else re.match(r"^(?:[\w.-]+@)?([\w.-]+)$", w)
            if m and "/" not in m.group(1):
                out.append(m.group(1).lower())
            if u.head == "ssh" and m:
                break
    for m in re.finditer(r"git@([\w.-]+):", u.text):
        out.append(m.group(1).lower())
    return out


def _egress(u) -> bool:
    if u.data:
        return False
    hosts = _hosts(u)
    for p in u.writes + u.paths:
        m = re.match(r"/dev/(?:tcp|udp)/([^/]+)/", p)
        if m and not _LOCAL.match(m.group(1)):
            return True                        # bash's built-in network device
    if u.head == "gh" and re.match(r"gh\s+(?:gist\s+create|api\b|release\s+(?:create|upload)|"
                                   r"issue\s+(?:create|comment)|pr\s+(?:create|comment)|repo\s+create)", u.text):
        return not _HELP.search(" " + u.text + " ")
    if u.head in ("dig", "nslookup", "host", "drill"):
        names = [w for w in u.text.split()[1:] if not w.startswith(("-", "+", "@")) and "." in w]
        return any(not _LOCAL.match(n.rstrip(".")) for n in names)
    if u.head in _NETCLI:
        if _HELP.search(" " + u.text + " ") and not hosts:
            return False
        if u.head == "rsync" and not hosts:
            return False                       # rsync between local folders
        if u.head in ("http", "https") and not hosts:
            return False
        return not hosts or any(not _LOCAL.match(h) for h in hosts)
    if u.head == "git" and re.match(r"git\s+(?:clone|fetch|pull|push|ls-remote)\b", u.text):
        return not hosts or any(not _LOCAL.match(h) for h in hosts)
    if re.search(r"\b(?:urllib|urlopen|requests\.(?:get|post|put|patch|delete)|httpx|aiohttp|"
                 r"http\.client|fetch\(|axios|net\.connect)", u.text):
        return any(not _LOCAL.match(h) for h in hosts)
    return False


def _reads_secret(u) -> bool:
    if getattr(u, "origin", "command") != "command":
        return False
    if u.data or u.head in ("ssh-keygen", "ls", "stat", "test", "[", "file", "chmod", "chown"):
        return False
    if u.head.startswith("python") and "venv" in u.text.split():
        return False                           # `python -m venv .env` makes a folder called .env
    if u.head == "git" and re.match(r"git\s+(?:rm|add|check-ignore|ls-files)\b", u.text):
        return False
    for p in u.paths:
        if p.endswith(".pub") or re.search(r"\.env\.(?:example|sample|template|dist)$", p):
            continue
        if _shell.SENSITIVE.search(p):
            return True
    return bool(re.search(r"\bsecurity\s+(?:find|dump)-(?:generic|internet)-password\b|"
                          r"\bsecurity\s+dump-keychain\b|\bgcloud\s+auth\s+print|\bgh\s+auth\s+token\b|"
                          r"\bop\s+(?:read|item\s+get)\b|\baws\s+configure\s+get\b|"
                          r"^(?:printenv|env)(?:\s*$|\s+\|)", u.text))


def _sends(u) -> bool:
    if u.data or _HELP.search(" " + u.text + " "):
        return False
    t = u.text
    if "--gmail-no-send" in t or re.search(r"\bdrafts?\s+(?:create|list|get)\b", t):
        return False
    if u.head in ("sendmail", "send-mail", "send_mail", "mailx", "msmtp", "swaks", "mutt", "neomutt"):
        return True
    if u.head == "mail" and re.search(r"[\w.+-]+@[\w-]+\.", t):
        return True
    return bool(re.search(
        r"\bgog\s+gmail\s+(?:send|reply|forward|drafts\s+send)\b|\bhimalaya\s+message\s+send\b|"
        r"\baws\s+(?:sns\s+publish|ses\s+send-(?:email|raw-email))\b|\bgh\s+(?:issue|pr)\s+comment\b|"
        r"hooks\.slack\.com/services/|discord(?:app)?\.com/api/webhooks/|/bot[^/\s]*/send\w*\b|"
        r"\bsmtplib\b|\.sendmail\(|\.send_message\(|chat[._]post(?:Message|Ephemeral)|/messages\.send|/v3/mail/send|"
        r"\bcurl\b.*(?:smtps?://|--mail-rcpt)|"
        r"api\.sendgrid\.com|api\.mailgun\.net|api\.postmarkapp\.com|api\.twilio\.com|api\.resend\.com|"
        r"\bosascript\b.*\bMessages\b.*\bsend\b|--to[= ]\s*\"?[\w.+-]+@[\w-]+\.[\w.-]+", t))


def _publishes(u) -> bool:
    if u.data or _HELP.search(" " + u.text + " "):
        return False
    return bool(re.search(
        r"^git\s+push\b|^gh\s+(?:pr\s+(?:create|merge)|release\s+create|repo\s+create\s+.*--public)\b|"
        r"^(?:npm|pnpm|yarn|uv)\s+publish\b|^twine\s+upload\b|^cargo\s+publish\b|^gem\s+push\b|"
        r"^docker\s+push\b|^vercel\b.*\s(?:--prod|deploy)\b|^netlify\s+deploy\b.*--prod|"
        r"^(?:fly|firebase|wrangler)\s+deploy\b", _from_head(u)))


def _rewrites_history(u) -> bool:
    if u.data or _HELP.search(" " + u.text + " "):
        return False
    t = u.text
    if re.search(r"^git\s+rebase\b", t) and not re.search(r"--(?:abort|quit|show-current-patch|edit-todo)\b", t):
        return True
    return bool(re.search(r"^git\s+(?:commit\s+.*--amend|filter-branch|filter-repo)\b|"
                          r"^git\s+push\b.*--force|^git\s+reset\s+--hard\s+\S", t))


def _deletes(u, cwd=None) -> bool:
    if u.data or _HELP.search(" " + u.text + " "):
        return False
    t = _from_head(u)
    if u.head in ("rm", "rmdir", "unlink", "shred", "srm", "trash") or re.search(r"\bfind\b.*\s-delete\b", t):
        targets = [p for p in u.paths if p]
        return not targets or not all(noise(p, _NOISE_TARGET, cwd) for p in targets)
    if re.match(r"^git\s+restore\b", t) and (not re.search(r"--staged\b", t) or "--worktree" in t):
        return True                            # discards uncommitted work; --staged alone only unstages
    return bool(re.search(
        r"^git\s+(?:reset\s+--hard|clean\s+-\w*f|stash\s+clear|branch\s+-D)\b|^git\s+checkout\s+--(?:\s|$)|"
        r"\bdelete\s+from\s+[\w.\"`]+\s*(?:;|$)|\.(?:rm|rmdir|unlink)Sync\(|"
        r"^truncate\s+(?:-\S+\s+)*-s\s*0|^dd\b.*\bof=/dev/|\b(?:drop|truncate)\s+(?:table|database|schema)\b|"
        r"^(?:dropdb|dropuser)\b|\bredis-cli\b.*\bflush(?:all|db)\b|^terraform\s+destroy\b|"
        r"^kubectl\s+delete\b|^docker\s+system\s+prune\b|^aws\s+s3\s+rm\b.*--recursive|"
        r"shutil\.rmtree|\bfs\.(?:rm|rmdir)Sync\(", t, re.I))


_LEAD = re.compile(r"^(?:(?:exec|nohup|command|builtin|time|nice|env|setsid|caffeinate)\s+(?:-\S+\s+)*)+")


def _elevates(u) -> bool:
    if u.data:
        return False
    t = _LEAD.sub("", u.text)
    if _shell.priv_info_only(t.split()):
        return False
    return bool(re.search(
        r"^(?:sudo|doas|pkexec)\b|^su\b(?:\s+-\S*)*(?:\s+(?:root|-c)\b|\s*$)|with\s+administrator\s+privileges|"
        r"\bchmod\s+(?:-\S+\s+)*(?:[0-7]?[0-7]{2}[2367]\b|[4-7][0-7]{3}\b|[ugoa]*\+s\b|[oa]\+w\b)|"
        r"\bchown\s+(?:-\S+\s+)*root\b|\bdseditgroup\b.*\badmin\b|\bspctl\s+--(?:master|global)-disable\b|"
        r"\bxattr\s+-\w*d\w*\s+com\.apple\.quarantine\b|\bsecurity\s+add-trusted-cert\b", t))


def _installs(u) -> bool:
    if u.data or _HELP.search(" " + u.text + " "):
        return False
    m = re.search(r"\b(?:pip3?|python3?\s+-m\s+pip|uv\s+pip)\s+install\s+(.*)$", u.text)
    if m:
        args = [a for a in m.group(1).split() if a not in ("-e", "--editable", "-U", "--upgrade", "--user", "-q")]
        if args and all(a.startswith((".", "/", "~")) for a in args):
            return False                       # your own project, not someone else's package
    return bool(re.search(
        r"\b(?:npm|pnpm|yarn|bun)\s+(?:i|install|add|ci)\b|^(?:npx|bunx|pnpx|uvx)\s|\b(?:pnpm|yarn)\s+dlx\b|"
        r"\b(?:pip3?|python3?\s+-m\s+pip)\s+install\b|\buv\s+(?:pip\s+install|add|tool\s+install)\b|"
        r"\bpipx\s+(?:install|run)\b|\bpoetry\s+add\b|\b(?:conda|mamba)\s+install\b|"
        r"\bbrew\s+(?:install|tap|reinstall)\b|\bgem\s+install\b|\bcargo\s+(?:install|add)\b|"
        r"\bgo\s+(?:install|get)\b|\b(?:apt|apt-get|yum|dnf|apk)\s+(?:install|add)\b", u.text))


def _schedules(u) -> bool:
    if any(_AUTOSTART.search(p) for p in u.writes):
        return True                            # the redirect happens whatever echo's words are
    if u.data:
        return False
    return bool(re.search(
        r"^(?:sudo\s+)?(?:launchctl\s+(?:load|bootstrap|enable|submit)\b|crontab\s+(?:-e\b|-(?=\s|$)|(?!-)\S)|"
        r"systemctl\s+(?:--user\s+)?enable\b|at\s+(?:now|midnight|noon|teatime|\d)|pm2\s+(?:startup|save)\b|"
        r"brew\s+services\s+start\b)|\bmake\s+(?:new\s+)?login\s+item", u.text))


_AUTOSTART = _shell.AUTOSTART
_PROFILE_W = _shell.PROFILE


def _runs_download_units(units: list, raw: str) -> bool:
    """Code fetched and executed in one go, in any of the three usual shapes."""
    for u in units:
        if u.head in ("curl", "wget") and u.feeds_code and not u.data:
            return True                      # curl x | sh,  curl x | tee f | sudo -E bash -
    if re.search(r"(?:^|[\s;&|(/])(?:bash|sh|zsh|source|\.|eval)\s+(?:-\S+\s+)*[\"']?(?:\$\(|<\()\s*(?:curl|wget)\b",
                 raw):
        return True                          # bash -c "$(curl ...)",  bash <(curl ...)
    saved = set()
    for u in units:
        if u.head in ("curl", "wget"):
            m = re.search(r"(?:\s-o\s+|\s--output\s+|\s-O\s+|\s>\s*)(\S+)", u.text)
            if m and not m.group(1).startswith("-"):
                saved.add(os.path.basename(m.group(1)))
        elif saved:
            words = u.text.split()
            run = [w for w in words if os.path.basename(w) in saved]
            if run and (u.head in ("bash", "sh", "zsh", "source", ".") or os.path.basename(words[0]) in saved):
                return True                  # curl -o i.sh URL && bash i.sh
    return False


SHELL_ONLY_FINDINGS = {"self_modify", "curl_pipe_shell", "persistence", "shell_profile"}


def match(subject: str, kind: str = "shell", cwd: str | None = None) -> list:
    """Signal ids for one action, judged on what it did. `kind` is shell,
    write, read or other. Reading CLAUDE.md is never an edit; writing .env is
    not reading a credential; a commit message that mentions sudo used none.
    `cwd` is the folder the session ran in: deleting below it is never scratch."""
    if not subject:
        return []
    if kind == "read":
        p = subject
        return ["secrets"] if (_shell.SENSITIVE.search(p) and not p.endswith(".pub")
                               and not re.search(r"\.env\.(?:example|sample|template|dist)$", p)) else []
    if kind == "write":
        hit = []
        if _AGENT_CFG.search(subject):
            hit.append("self_modify")
        if _AUTOSTART.search(subject):
            hit.append("persistence")
        if _PROFILE_W.search(subject):
            hit.append("shell_profile")
        return hit
    if kind != "shell":
        return []

    units = _shell.history_units(subject)
    found = set()
    for u in units:
        if _reads_secret(u):
            found.add("secrets")
        if _egress(u):
            found.add("egress")
        if _sends(u):
            found.add("outbound")
        if _deletes(u, cwd):
            found.add("destructive")
        if _publishes(u):
            found.add("publish")
        if _schedules(u):
            found.add("persistence")
        if _elevates(u):
            found.add("privilege")
        if _installs(u):
            found.add("supplychain")
        if not u.data and re.search(r"(?:^|\s)(?:psql|mysql|mariadb|mongo|mongosh|redis-cli|sqlite3|"
                                    r"pg_dump|pg_restore|createdb|dropdb)\b|\bsupabase\s+db\b|"
                                    r"\bprisma\s+(?:migrate|db)\b", u.text):
            found.add("database")
        if _rewrites_history(u):
            found.add("git_history")
        if not u.data and (u.background or re.search(r"(?:^|\s)(?:nohup|disown|setsid)\b|\bscreen\s+-\S*d|"
                                                     r"\btmux\s+new(?:-session)?\b.*\s-d\b", u.text)):
            found.add("background")
        if any(_AGENT_CFG.search(p) for p in u.writes) or re.search(r"^(?:claude|codex)\s+mcp\s+add\b", u.text):
            found.add("self_modify")
        if any(_PROFILE_W.search(p) for p in u.writes):
            found.add("shell_profile")
        if _deletes(u, cwd) and _elevates(u):
            found.add("destructive_and_privilege")       # the same command, as root
    if _runs_download_units(units, executed(subject)):
        found |= {"curl_pipe_shell", "supplychain"}
    for cid, _, pair in COMBOS:
        if cid != "destructive_and_privilege" and found.issuperset(pair):
            found.add(cid)
    order = [sid for sid, _, _, _ in COMPILED] + [c[0] for c in COMBOS]
    return [sid for sid in order if sid in found]


# Not every matching command is worth quoting. An agent editing this very file
# logs a shell command full of the patterns below, and those self-matches made
# the three most important lines of the report read as broken output. Score
# candidates and quote the clearest, not the first.
_NOISY = re.compile(r"""(?:r["']\\b|\\b\(|<<\s*['"]?[A-Z]{2,}|"""
                    r"""\bsed\s+-i\b|\bcat\s*>|\bheredoc\b|re\.(?:compile|search|match))""")


def example_score(subject: str, sid: str) -> float:
    """Higher is more worth showing a human."""
    if not subject:
        return -99.0
    score = 0.0
    rx = next((r for i, _, _, r in COMPILED if i == sid), None)
    m = rx.search(subject) if rx else None
    if m:
        score += 6.0 if m.start() < 24 else 2.0
    if _NOISY.search(subject):
        score -= 12.0          # the command is writing code about this, not doing it
    n = len(subject)
    score += 4.0 if n < 90 else (1.0 if n < 180 else -2.0)
    score -= subject.count("\\") * 0.4
    score -= subject.count("|") * 0.2
    return score


def excerpt(subject: str, sid: str, span: int = 96) -> str:
    """The part of the command that tripped the signal, with context.

    Quoting the first 70 characters of a 400-character shell line usually
    hides the very thing being reported, which makes the most important three
    lines of the report useless. Centre the window on the match instead.
    """
    rx = next((r for i, _, _, r in COMPILED if i == sid), None)
    if rx is None:
        return subject[:span]
    m = rx.search(subject)
    if not m:
        return subject[:span]
    mid = (m.start() + m.end()) // 2
    start = max(0, mid - span // 2)
    end = min(len(subject), start + span)
    start = max(0, end - span)
    out = subject[start:end].strip()
    if start > 0:
        out = "…" + out
    if end < len(subject):
        out = out + "…"
    return out


# ------------------------------------------------------------------ redaction
#
# Mask secret VALUES, never commands or paths. Two error directions, both
# expensive: under-masking puts a live key into a page someone screenshots;
# over-masking erases the evidence, because "cat ~/.ssh/id_rsa" turned into
# "cat •••" is no longer a finding anyone feels. So the shape of every command
# survives and only the value is replaced.
#
# Applied to the whole line BEFORE excerpting: a 96-character window can slice
# a key in half, and the tail ("k-proj-AbC…") matches no prefix rule.

MASK = "•••"

# Quantifiers are bounded on purpose: an unbounded `[^\n|;&]*?` between two
# alternations made one reviewer's crafted 8 KB command take a quarter of a
# second and grow 4x per doubling. Every span below is capped.
_REDACT = [
    # echo 'hunter2' | sudo -S ...: the password is the echo's argument
    (re.compile(r"((?:echo|printf)\s+(?:-[a-z]+\s+)?)(['\"]?)([^'\"|\s]{3,200})\2(\s*\|\s*sudo\s+(?:-\w+\s+)*-\w*S)"), r"\1\2•••\2\4"),
    # printf '%s\n' 'hunter2' | sudo -S, and the same into any --password-stdin login
    (re.compile(r"(\bprintf\s+(['\"])[^'\"]{0,20}\2\s+)(['\"]?)[^'\"|\s]{3,200}\3(?=\s*\|\s*(?:sudo\s+(?:-\w+\s+)*-\w*S|"
                r"[^|\n]{0,200}--password-stdin))"), r"\1\3" + "•••" + r"\3"),
    (re.compile(r"((?:echo|printf)\s+(?:-[a-z]+\s+)?)(['\"]?)([^'\"|\s]{3,200})\2(?=\s*\|[^|\n]{0,200}--password-stdin)"),
     r"\1\2•••\2"),
    # sudo -S ... <<< 'hunter2': a here-string is stdin, so it is the password
    (re.compile(r"(\bsudo\b[^\n|;&]{0,400}?\s-\w*S\b[^\n|;&]{0,400}?<<<\s*)(['\"]?)[^\s'\"]{1,200}\2"), r"\1\2•••\2"),
    (re.compile(r"(--password-stdin\b[^\n|;&]{0,200}?<<<\s*)(['\"]?)[^\s'\"]{1,200}\2"), r"\1\2•••\2"),
    # pasted private keys, PGP blocks included
    (re.compile(r"-----BEGIN [A-Z ]{0,40}PRIVATE KEY(?: BLOCK)?-----[\s\S]{0,20000}?"
                r"(?:-----END [A-Z ]{0,40}PRIVATE KEY(?: BLOCK)?-----|$)"),
     "-----BEGIN PRIVATE KEY----- " + MASK),
    # vendor tokens with public prefixes. The prefix is kept: it is how you
    # recognise which key it was, and it is not the secret. Short minimums,
    # because a prefix this distinctive is evidence on its own, and because a
    # cut-off tail must still be masked.
    (re.compile(r"\bsk-ant-[A-Za-z0-9_-]{4,}"), "sk-ant-" + MASK),
    (re.compile(r"\bsk-(?:proj-|live-|test-|svcacct-)?[A-Za-z0-9_-]{16,}"), "sk-" + MASK),
    (re.compile(r"\b([rsp]k_(?:live|test)_)[A-Za-z0-9]{6,}"), r"\1" + MASK),
    (re.compile(r"\b(AKIA|ASIA)[0-9A-Z]{8,}"), r"\1" + MASK),
    (re.compile(r"\b(gh[pousr]_)[A-Za-z0-9]{8,}"), r"\1" + MASK),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{8,}"), "github_pat_" + MASK),
    (re.compile(r"\b(glpat-|glptt-|gldt-)[A-Za-z0-9_-]{8,}"), r"\1" + MASK),
    (re.compile(r"\b(hf_|npm_|dop_v1_|shpat_|shpss_|xapp-|sq0atp-|sq0csp-|pypi-)[A-Za-z0-9_-]{8,}"), r"\1" + MASK),
    (re.compile(r"\b(xox[abprs]-)[A-Za-z0-9-]{8,}"), r"\1" + MASK),
    (re.compile(r"\bAIza[0-9A-Za-z_-]{16,}"), "AIza" + MASK),
    (re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{4,}"), "eyJ" + MASK),
    (re.compile(r"(?<!\d)\d{8,12}:AA[A-Za-z0-9_-]{20,}"), MASK),                   # Telegram bot token
    (re.compile(r"(hooks\.slack\.com/services/)[A-Za-z0-9/]{10,}"), r"\1" + MASK),
    (re.compile(r"(discord(?:app)?\.com/api/webhooks/)[\w/-]{10,}"), r"\1" + MASK),
    # Authorization headers and cookies
    (re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}"), r"\1 " + MASK),
    (re.compile(r"(?i)(authorization:\s*token)\s+[A-Za-z0-9._~+/=-]{8,}"), r"\1 " + MASK),
    (re.compile(r"(?i)\b((?:set-)?cookie:\s*)[^'\"\n]{4,400}"), r"\1" + MASK),
    (re.compile(r"(?i)((?:\s|^)(?:--cookie|-b)\s+)(['\"]?)[^\s'\"]{6,}\2"), r"\1" + MASK),
    # secrets in URLs: scheme://user:password@host, and ?token=... style query parameters
    (re.compile(r"(?i)\b([a-z][a-z0-9+.-]{0,15}://[^\s/:@]{1,200}):([^\s/@]{3,200})@"), r"\1:" + MASK + "@"),
    (re.compile(r"(?i)([?&](?:sig|signature|token|access_token|api_key|apikey|key|secret|password|auth|"
                r"client_secret|code)=)[^&\s'\"#]{6,}"), r"\1" + MASK),
    # credentials on a command line
    (re.compile(r"(?i)(\b(?:curl|wget|http)\b[^\n|;&]{0,400}?\s(?:-u|--user)[\s=]+)(['\"]?)([^\s:'\"]+):[^\s'\"]+\2"),
     r"\1\2\3:" + MASK + r"\2"),
    (re.compile(r"(?i)(\bsshpass\s+-p\s*)(['\"]?)[^\s'\"]+\2"), r"\1" + MASK),
    (re.compile(r"(?i)(\bmysql\b[^\n|;&]{0,400}?\s-p)(?!\s)(['\"]?)[^\s'\"]{3,}\2"), r"\1" + MASK),
    (re.compile(r"(?i)(\bredis-cli\b[^\n|;&]{0,400}?\s(?:-a|--pass)\s+)(['\"]?)[^\s'\"]+\2"), r"\1" + MASK),
    (re.compile(r"(?i)(\b(?:docker|podman|helm|nerdctl)\s+(?:registry\s+)?login\b[^\n|;&]{0,400}?\s(?:-p|--password)[\s=]+)"
                r"(['\"]?)[^\s'\"]+\2"), r"\1" + MASK),
    (re.compile(r"(?i)(\baws\s+configure\s+set\s+\S*(?:secret|key|token)\S*\s+)(['\"]?)[^\s'\"]+\2"), r"\1" + MASK),
    (re.compile(r"(?i)(\bsecurity\s+add-(?:generic|internet)-password\b[^\n|;&]{0,400}?\s-w\s+)(['\"]?)[^\s'\"]+\2"),
     r"\1" + MASK),
    (re.compile(r"(?i)(--(?:password|passwd|pass|token|api[-_]?key|secret|auth[-_]?token|access[-_]?token|"
                r"client[-_]?secret)(?:=|\s+))(['\"]?)(?![$/~])[^\s'\"]{4,}\2"), r"\1" + MASK),
    (re.compile(r"(?i)(\bgpg\b[^\n|;&]{0,400}?\s--passphrase(?:=|\s+))(['\"]?)[^\s'\"]+\2"), r"\1" + MASK),
    (re.compile(r"(?i)(\bssh-keygen\b[^\n|;&]{0,400}?\s-N\s+)(['\"])[^'\"]+\2"), r"\1\2" + MASK + r"\2"),
    (re.compile(r"(?i)(\bssh-keygen\b[^\n|;&]{0,400}?\s-N\s+)(?!['\"])[^\s]+"), r"\1" + MASK),
    (re.compile(r"(?i)(\bmysqladmin\b[^\n|;&]{0,400}?\spassword\s+)(['\"]?)[^\s'\"]+\2"), r"\1" + MASK),
    (re.compile(r"\b(hv[sbr]\.)[A-Za-z0-9_-]{8,}"), r"\1" + MASK),
    (re.compile(r"\bSG\.[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{16,}"), "SG." + MASK),          # SendGrid
    (re.compile(r"\bGOCSPX-[A-Za-z0-9_-]{8,}"), "GOCSPX-" + MASK),                      # Google OAuth client secret
    (re.compile(r"\bAGE-SECRET-KEY-1[A-Z0-9]{8,}"), "AGE-SECRET-KEY-" + MASK),         # age
    (re.compile(r"\b(xai-|gsk_|r8_|pplx-|nvapi-|csk-|fw_|tvly-|lsv2_p[ts]_|sk_live_|rk_live_)[A-Za-z0-9_-]{12,}"),
     r"\1" + MASK),                                                                    # xAI, Groq, Replicate...
    # a password handed to a program as it runs: sudo -S <<EOF / pw / EOF, SSHPASS=, zip -P, 7z -p, htpasswd -b
    (re.compile(r"(\bsudo\b[^\n]*\s-\w*S\w*\b[^\n]*<<-?\s*['\"]?(\w+)['\"]?\n)[^\n]*"), r"\1" + MASK),
    (re.compile(r"(\becho\s+)(['\"]?)[^\s'\"|]{3,}\2(\s*\|\s*sudo\s+-\w*S)"), r"\1" + MASK + r"\3"),
    (re.compile(r"(\bSSHPASS=)(['\"]?)[^\s'\"]+\2"), r"\1" + MASK),
    (re.compile(r"\b(SK)[0-9a-fA-F]{32}\b"), r"\1" + MASK),                              # Twilio API key
    (re.compile(r"(\s-p)(['\"])[^'\"\n]{3,200}\2"), r"\1\2" + MASK + r"\2"),           # -p'pw', quoted
    (re.compile(r"(\bzip\b[^\n|;&]{0,200}?\s-P\s*)(['\"]?)[^\s'\"]+\2"), r"\1" + MASK),
    (re.compile(r"(\b7z[az]?\b[^\n|;&]{0,200}?\s-p)(['\"]?)[^\s'\"]+\2"), r"\1" + MASK),
    (re.compile(r"(\bhtpasswd\b[^\n|;&]{0,200}?\s-\w*b\w*\s+(?:-\S+\s+)*\S+\s+\S+\s+)(['\"]?)[^\s'\"]+\2"),
     r"\1" + MASK),
    (re.compile(r"((?:\bsmbclient|\brpcclient|\bmount_smbfs|\bnet\s+use)\b[^\n|;&]{0,200}?(?:-U\s*|//)[^\s%:@/]+[%:])"
                r"[^\s@'\"/]+"), r"\1" + MASK),
    (re.compile(r"(?i)(\s--pw(?:=|\s+))(['\"]?)[^\s'\"]+\2"), r"\1" + MASK),
    (re.compile(r"(?i)\b((?:password|passwd|passphrase|passcode|pin)\s*[:=]?\s+)(['\"]?)(?![$/~])"
                r"(?=[^\s'\"]{0,40}[\d!@#%^&*+=])(?=[^\s'\"]{0,40}[A-Za-z])[^\s'\"]{6,}\2"), r"\1" + MASK),
    # vault login <token>, gh secret set NAME --body <value>
    (re.compile(r"(\bvault\s+login\s+(?:-\S+\s+)*)(?!-)(['\"]?)(?![$/~])[^\s'\"=]{6,}\2(?=\s|$)"), r"\1" + MASK),
    (re.compile(r"(\bgh\s+secret\s+set\b[^\n|;&]{0,200}?\s(?:-b|--body)[\s=]+)(['\"]?)(?![$])[^\s'\"]+\2"),
     r"\1\2" + MASK + r"\2"),
    # flags that carry a secret under any prefix: --auth-password, --db-token, --x-api-key
    (re.compile(r"(?i)(--[\w-]{0,30}(?:password|passwd|token|api[-_]?key|secret)(?:=|\s+))(['\"]?)(?![$/~-])[^\s'\"]{4,}\2"),
     r"\1" + MASK),
    # .login(user, 'hunter2'), the password as code passes it
    (re.compile(r"(\.login\(\s*[^,()\n]{1,200},\s*)(['\"])[^'\"\n]{1,200}\2"), r"\1\2" + MASK + r"\2"),
    # a long hex or base64 run right after a word that says what it is
    (re.compile(r"(?i)(\b(?:key|token|secret|password|passwd|credential|apikey|api\s+key|auth)s?\b[^\n'\"]{0,40}?"
                r"(?<![\w/+=.-]))(?![/~.])(?:[0-9a-f]{32,}|(?=[A-Za-z0-9+/_-]{0,200}[0-9])(?=[A-Za-z0-9+/_-]{0,200}[A-Z])"
                r"(?=[A-Za-z0-9+/_-]{0,200}[a-z])[A-Za-z0-9+/_-]{32,}={0,2})(?![\w/+=-])"), r"\1" + MASK),
    (re.compile(r"(?i)\b(x-[a-z0-9-]*(?:auth|key|token|secret|signature)[a-z0-9-]*:\s*)[^'\"\n]{6,400}"), r"\1" + MASK),
    (re.compile(r"(?i)(\bmachine\s+\S+\s+login\s+\S+\s+password\s+)\S+"), r"\1" + MASK),
    # said in words: "the password is hunter2", "token: abc123"
    (re.compile(r"(?i)\b((?:password|passcode|passwd|passphrase|token|secret|api[\s_-]?key)\s+(?:is|was)\s+)"
                r"(['\"]?)(?![$/~])[^\s'\"]{4,}\2"), r"\1" + MASK),
    # NAME=value where the name says it is a secret. Skipped when the value is
    # a reference ($VAR, $(cmd)), a path (/ ~ .), a plain number, or a word
    # like true or none.
    # Short values (4-7 chars) count only with a digit or symbol in them:
    # API_TOKEN=a1b2c is a secret, SORT_KEY=name is not.
    (re.compile(r"(?i)\b([A-Z0-9_]{0,60}(?:KEY|TOKEN|SECRET|PASSWORD|PASSWD|PASSPHRASE|(?<![A-Z])PASS|"
                r"CREDENTIALS?|COOKIE|SESSION_?ID)[A-Z0-9_]{0,60})(['\"]?)(\s{0,3}[:=]\s{0,3})(['\"]?)(?![$/~.])"
                r"(?![0-9]+(?:['\"\s,}]|$))(?!(?:true|false|null|none|yes|no)\b)"
                r"(?=[^\s'\"]{8}|[^\s'\"]{0,7}[\d!@#%^&*+=$-])[^\s'\"]{4,}\4"),
     r"\1\2\3\4" + MASK + r"\4"),
]

# Anything printed from a log goes through clean(). A logged command can carry
# terminal escapes: one reviewer's planted command wrote to the clipboard
# through OSC 52 and erased every finding row above it with cursor movement.
# Control characters become visible and inert; bidirectional overrides, which
# can make a command read differently from what it is, are removed.
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")
_BIDI = re.compile(r"[\u202a-\u202e\u2066-\u2069\u200e\u200f\u061c]")


def clean(text) -> str:
    if text is None:
        return ""
    text = _BIDI.sub("", str(text))
    return _CONTROL.sub(lambda m: "\\x%02x" % ord(m.group(0)), text)


_TERM_SEQ = re.compile(r"\x1b\][^\x07\x1b]{0,4096}(?:\x07|\x1b\\)?|\x9d[^\x07\x1b\x9c]{0,4096}(?:\x07|\x9c)?|"
                       r"\x1b\[[0-?]{0,64}[ -/]{0,8}[@-~]?|\x9b[0-?]{0,64}[ -/]{0,8}[@-~]?|\x1b[PX^_][^\x1b]{0,4096}(?:\x1b\\)?|"
                       r"\x1b.?")


def clean_label(text, limit: int = 300) -> str:
    """A name shown in a list (a project, a subagent's kind, model or task):
    terminal sequences removed whole (ESC, OSC, CSI, DCS), any other control
    character turned to a space, bidi overrides gone, secrets masked.

    clean() keeps escapes visible, which is right for a command someone needs
    to read exactly; a label only needs to be safe and short."""
    if text is None:
        return ""
    t = _TERM_SEQ.sub("", str(text))
    t = _BIDI.sub("", t)
    t = _CONTROL.sub(" ", t.replace("\n", " ").replace("\t", " "))
    t = redact(" ".join(t.split()))
    return t[:limit]


def redact(text: str) -> str:
    if not text:
        return text
    for rx, repl in _REDACT:
        text = rx.sub(repl, text)
    return text
