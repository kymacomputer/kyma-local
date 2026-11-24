"""Rules written as sentences, compiled to matchers, honest about failure.

This is a small deterministic compiler over a fixed vocabulary, not a language
model. A sentence compiles to something you can read back with `kyma rules`,
or it says it did not compile. It must never half-understand a rule and guard
less than you think.

    - Never let an agent email anyone.
    - Ask me before any git push.
    - Your agent may email cofounder@example.com without asking.
    - Never touch ~/.ssh.
    - Never run `rm -rf` outside ~/code.

How a call is judged (kyma/shell.py does the reading)
    A tool call is cut into units: one per command it actually runs. Each unit
    is judged on its own, and the strictest result wins. An exception
    therefore only covers the command it names. "may email cofounder@..."
    cannot lift a block on a different command in the same line, and cannot
    be triggered by a comment.

What an exception can lift
    An allow rule lifts a hold only when it speaks about the same act, and
    only when it covers everything that triggered the hold: every recipient it
    names, every path inside the paths it names. A rule that only names a
    tool ("may use Bash") lifts nothing but another tool-only rule.

Where rules come from
    ~/.kyma/RULES.md is yours. A RULES.md inside a project adds rules, and its
    exceptions apply to its own rules only: a repository you clone cannot
    loosen the rules you wrote for yourself.
"""

from __future__ import annotations

import os
import re
from . import asdict, field, fields, record as dataclass

from . import shell

BLOCK, ASK, ALLOW = "block", "ask", "allow"
STRICT = {ALLOW: 0, ASK: 1, BLOCK: 2}

# ------------------------------------------------------------- what a call did
#
# These are tuned for recall, on purpose. The report's findings make claims,
# so they match narrowly (signals.py). A gate is a door: a false prompt costs a
# keystroke, a missed act costs whatever the act was.

LABEL = {
    "privilege": "used sudo or root",
    "egress": "reached the network",
    "outbound": "sent a message to someone",
    "email": "sent an email",
    "git_push": "pushed changes to a remote repository",
    "publish": "pushed, published or deployed",
    "deploy": "deployed an app or changed infrastructure",
    "destructive": "deleted something",
    "supplychain": "installed packages",
    "secrets": "read a credential",
    "dotenv": "read a .env file",
    "persistence": "set something to run by itself later: on a schedule, at startup, or from a git hook",
    "background": "left a process running in the background",
    "database": "talked to a database",
    "git_history": "rewrote git history",
    "write": "wrote or changed a file",
    "agent_config": "changed the agent's own settings or instructions",
    "shell_profile": "changed your shell profile",
}

# Rule descriptions name possible actions, not events that already happened.
ACTION_LABEL = {
    "privilege": "use administrator access",
    "egress": "access the network",
    "outbound": "send a message",
    "email": "send email",
    "git_push": "upload code changes with git push",
    "publish": "push, publish or deploy",
    "deploy": "deploy an app or change infrastructure",
    "destructive": "delete files",
    "supplychain": "install packages",
    "secrets": "read credentials",
    "dotenv": "read .env files",
    "persistence": "schedule a task or configure automatic startup",
    "background": "start a background process",
    "database": "access a database",
    "git_history": "rewrite git history",
    "write": "write or change a file",
    "agent_config": "change agent settings or instructions",
    "shell_profile": "change your shell profile",
}

_I = re.I

# Command words count only at command position: the first word after any
# wrappers (sudo, env, nohup, xargs). Matching them anywhere in a unit made a
# Python heredoc line like print("done at 10:30") read as the `at` scheduler.
# The send endpoints of the mail APIs an agent reaches for.
_EMAIL_API = (r"api\.resend\.com/emails|api\.mailgun\.net/\S*messages|gmail\.googleapis\.com/\S*messages/send|"
             r"api\.postmarkapp\.com/email|api\.sendgrid\.com/v3/mail/send|graph\.microsoft\.com/\S*sendMail|"
             r"api\.brevo\.com/v3/smtp/email|api\.mailjet\.com/v3\S*/send|email\.\S+\.amazonaws\.com")
_MAIL_API = (_EMAIL_API + "|" +
             # chat: a message posted is a message sent
             r"slack\.com/api/(?:chat\.(?:postMessage|postEphemeral|scheduleMessage|update)|files\.upload)|"
             r"hooks\.slack\.com/services/|discord(?:app)?\.com/api/(?:v\d+/)?(?:webhooks/|channels/\S*/messages)|"
             r"api\.telegram\.org/bot\S*/send\w+|api\.twilio\.com/\S*/Messages|graph\.microsoft\.com/\S*/chats?/\S*/messages|"
             r"api\.pushover\.net/|ntfy\.sh/|outlook\.office\.com/webhook/|webhook\.office\.com/")

_CAT_CMD = {
    "git_push": re.compile(r"^git\s+(?:push|send-pack)\b|^git\s+subtree\s+push\b|^jj\s+git\s+push\b|"
                            r"^gt\s+(?:submit|ss|stack\s+submit|ds|downstack\s+submit)\b|^hub\s+push\b|"
                            r"^(?:npx\s+(?:-\S+\s+)*)?gh-pages\b", _I),
    "email": re.compile(r"^(?:\S*/)?(?:sendmail|send-mail|send_mail|mailx|msmtp|swaks|(?:neo)?mutt)\b|^mail\s+.*@|"
                         r"^gog\s+gmail\s+(?:send|reply|forward|drafts\s+send)\b|^himalaya\s+message\s+send\b|"
                         r"^aws\s+sesv?2?\s+send-(?:email|raw-email)\b|^git\s+send-email\b|"
                         r"^osascript\b.*application\s+\"?Mail\"?.*\bsend\b|"
                         r"^(?:curl|wget|xh|http|https)\b.*(?:smtps?://|--mail-rcpt|--mail-from|" + _EMAIL_API + r")", _I),
    "privilege": re.compile(
        r"^(?:su\b(?:\s+-\S*)*(?:\s+(?:root|-c)\b|\s*$)|visudo\b|"
        r"chmod\s+(?:-\S+\s+)*(?:[4-7][0-7]{3}\b|[ua]*\+s\b|u[a-z]*\+[a-z]*s)|"
        r"chown\s+(?:-\S+\s+)*root\b|dscl\b.*\s-(?:create|append|change)\b|spctl\s+--(?:master|global)-disable\b|"
        r"osascript\b.*with\s+administrator\s+privileges)", _I),
    "egress": re.compile(
        r"^(?:curl|wget|nc|ncat|netcat|socat|scp|sftp|ftp|telnet|aria2c|xh|httpie|ssh|dig|nslookup|drill)\b|"
        r"^host\s+\S+\.\S+|^rsync\b.*\s[\w.@-]+:|^git\s+(?:clone|fetch|pull|ls-remote|push)\b|"
        r"^gh\s+(?:api|gist|release|repo\s+create|pr\s+(?:create|comment)|issue\s+(?:create|comment))\b", _I),
    "outbound": re.compile(
        r"^(?:sendmail|send-mail|send_mail|mailx|msmtp|swaks|(?:neo)?mutt)\b|^mail\s+.*@|"
        r"^gog\s+gmail\s+(?:send|reply|forward|drafts\s+send)\b|^himalaya\s+message\s+send\b|"
        r"^aws\s+(?:sns\s+publish|ses\s+send-(?:email|raw-email))\b|^gh\s+(?:issue|pr)\s+comment\b|"
        r"^osascript\b.*\bmessages\b|^(?!git\s+format-patch\b).*--to[= ]\s*\"?[\w.+-]+@[\w-]+\.[\w.-]+|"
        r"^(?:mail|mailx|s-nail)\s+\S|^osascript\b.*application\s+\"?Mail\"?.*\bsend\b|"
        r"^(?:curl|wget|xh|http|https)\b.*(?:smtps?://|--mail-rcpt|--mail-from|" + _MAIL_API + r")", _I),
    "publish": re.compile(
        r"^git\s+push\b|^git\s+subtree\s+push\b|^(?:npx\s+(?:-\S+\s+)*)?gh-pages\b|^jj\s+git\s+push\b|"
        r"^gt\s+(?:submit|ss|stack\s+submit|ds|downstack\s+submit)\b|"
        r"^gh\s+(?:pr\s+(?:create|merge)|release\s+create|repo\s+create)\b|"
        r"^(?:npm|pnpm|yarn|uv)\s+publish\b|^twine\s+upload\b|^cargo\s+publish\b|^gem\s+push\b|^docker\s+push\b|"
        r"^(?:netlify|fly|firebase|wrangler|railway)\s+(?:deploy|publish|up)\b|"
        r"^vercel\b(?!(?:\s+-\S+)*\s+(?:dev|build|login|logout|env|link|pull|logs|ls|list|whoami|inspect|help|init|"
        r"projects?|domains|dns|certs|teams|switch|git|integration|bisect|telemetry|cache|open|whoami)\b)|"
        r"^(?:npm|pnpm|yarn)\s+run\s+(?:release|deploy|publish)\b", _I),
    # deploys: an app, a cluster, infrastructure. Their own category, so that
    # "any git push" does not hold `terraform apply`; "never deploy" covers app and infrastructure changes.
    "deploy": re.compile(
        r"^gcloud\s+(?:app\s+deploy|run\s+deploy|functions\s+deploy|builds\s+submit|deploy)\b|"
        r"^kubectl\s+(?:apply|create|replace|patch|set\s+image|rollout\s+(?:restart|undo))\b|"
        r"^(?:terraform|tofu)\s+apply\b|^helm\s+(?:install|upgrade|rollback)\b|^pulumi\s+up\b|"
        r"^(?:aws\s+(?:cloudformation\s+deploy|lambda\s+update-function-code|s3\s+sync)|sam\s+deploy|cdk\s+deploy|"
        r"serverless\s+deploy|sls\s+deploy|heroku\s+(?:deploy|releases:rollback)|eb\s+deploy|az\s+webapp\s+deploy)\b|"
        r"^(?:netlify|fly|firebase|wrangler|railway)\s+(?:deploy|publish|up)\b|"
        r"^vercel\b(?!(?:\s+-\S+)*\s+(?:dev|build|login|logout|env|link|pull|logs|ls|list|whoami|inspect|help|init|"
        r"projects?|domains|dns|certs|teams|switch|git|integration|bisect|telemetry|cache|open)\b)|"
        r"^(?:npm|pnpm|yarn)\s+run\s+deploy\b", _I),
    "destructive": re.compile(
        r"^(?:rm|rmdir|unlink|shred|srm|trash)(?:\s|$)|^find\b.*\s-delete\b|^find\b.*-exec\s+rm\b|"
        r"^git\s+(?:reset\s+--hard|clean\s+-\w*[fdx]|checkout\s+--(?:\s|$)|restore\b|branch\s+-D\b|stash\s+clear\b|"
        r"push\s+\S+\s+(?:--delete|:\S))|^truncate\b.*-s\s*0|^dd\b.*\bof=|^(?:dropdb|dropuser)\b|"
        r"^terraform\s+destroy\b|^kubectl\s+delete\b|^docker\s+system\s+prune\b|^aws\s+s3\s+rm\b", _I),
    "supplychain": re.compile(
        r"^(?:npm|pnpm|yarn|bun)\s+(?:i|install|add|ci)\b|^(?:npx|bunx|pnpx|uvx)\s|^(?:pnpm|yarn)\s+dlx\b|"
        r"^(?:pip3?|python3?\s+-m\s+pip)\s+install\b|^uv\s+(?:pip\s+install|add|tool\s+install|sync)\b|"
        r"^pipx\s+(?:install|run)\b|^poetry\s+(?:add|install)\b|^(?:conda|mamba|micromamba)\s+install\b|"
        r"^brew\s+(?:install|tap|reinstall)\b|^gem\s+install\b|^cargo\s+(?:install|add)\b|^go\s+(?:install|get)\b|"
        r"^(?:apt|apt-get|yum|dnf|apk|zypper)\s+(?:install|add)\b|^pacman\s+-S\b|^composer\s+(?:require|install)\b|"
        r"^deno\s+install\b", _I),
    "secrets": re.compile(
        r"^security\s+(?:find|dump)-(?:generic|internet)-password\b|^security\s+dump-keychain\b|"
        r"^gcloud\s+auth\s+print|^gh\s+auth\s+token\b|^op\s+(?:read|item\s+get)\b|"
        r"^aws\s+configure\s+get\s+\S*(?:key|secret|token)|"
        r"^printenv\s*(?:$|\S*(?:KEY|TOKEN|SECRET|PASS|CRED|AUTH|COOKIE|SESSION)\S*)|^env\s*$|"
        r"^vault\s+(?:read|kv\s+get)\b|^docker[- ]compose\b(?:\s+-\S+(?:\s+\S+)?)*\s+config\b(?!.*(?:\s-q\b|--quiet\b|--services\b|--volumes\b|--images\b|--profiles\b|--hash\b))", _I),
    "persistence": re.compile(
        r"^crontab\s+(?!-l\b)(?!-r\b)\S|^at\s+(?:now|midnight|noon|teatime|tomorrow|\d)|"
        r"^launchctl\s+(?:load|bootstrap|enable|submit)\b|^brew\s+services\s+(?:start|restart|run)\b|"
        r"^at\s+(?:-[fmqv]\s*\S*\s+)*(?:now|midnight|noon|teatime|tomorrow|\d)|^batch\b|^crontab\s*(?:-\s*)?$|"
        r"^systemd-run\b.*--on-(?:calendar|boot|active|unit-active|startup)|^pm2\s+start\b.*--cron|"
        r"^docker\s+(?:run|create|update|container\s+(?:run|create|update))\b.*--restart[= ](?!no\b)|"
        r"^git\s+config\b.*\bcore\.hookspath\b|^defaults\s+write\b.*(?:LaunchAgents|loginwindow|LoginItems)|"
        r"^(?:curl|wget|plutil|cp|install|ln|rsync|tee)\b.*(?:/LaunchAgents/|/LaunchDaemons/|/\.config/autostart/)|"
        r"^systemctl\s+(?:--user\s+)?enable\b|^pm2\s+(?:startup|save)\b|^osascript\b.*make\s+(?:new\s+)?login\s+item", _I),
    "background": re.compile(
        r"^screen\s+-\S*d|^tmux\s+new(?:-session)?\b.*\s-d\b|^pm2\s+start\b|^systemctl\s+(?:--user\s+)?start\b", _I),
    "database": re.compile(
        r"^(?:psql|mysql|mariadb|mongo|mongosh|redis-cli|sqlite3|cockroach|clickhouse-client|pg_dump|pg_restore|"
        r"createdb|dropdb|dropuser)\b|^supabase\s+db\b|^prisma\s+(?:migrate|db)\b|^rails\s+db:|"
        r"^alembic\s+(?:upgrade|downgrade)\b", _I),
    "git_history": re.compile(
        r"^git\s+(?:rebase|filter-branch|filter-repo|commit\s+.*--amend|reset\s+--hard\s+\S)|^git\s+push\b.*--force", _I),
}
# Inside code (a python -c, a heredoc fed to node), the act is an API call.
_CAT_CODE = {
    "git_push": re.compile(r"\bRepo\([^)]*\)\.remotes?\b.*\.push\(|\bremote\([^)]*\)\.push\(|\borigin\.push\(|"
                           r"\.git\.push\(", _I),
    "email": re.compile(r"\.sendmail\(|\.send_message\(|\bsend_(?:raw_)?email\(|\.emails?\.send\(|\bEmails\.send\(|"
                        r"\byagmail\b.*\.send\(|\bSendGridAPIClient\b|@sendgrid/mail|\b\w*mail\w*\.send\(|"
                        r"\bnodemailer\b|\.sendMail\(|application\s+\"Mail\"[\s\S]{0,2000}\bsend\b|" + _EMAIL_API, _I),
    "egress": re.compile(r"\b(?:urllib|urlopen|requests\.(?:get|post|put|patch|delete|request)|httpx|aiohttp|"
                         r"http\.client|axios|socket\.create_connection|net\.connect)\b|\bfetch\(", _I),
    "privilege": re.compile(r"with\s+administrator\s+privileges", _I),
    "publish": re.compile(r"\bRepo\([^)]*\)\.remotes?\b.*\.push\(|\bremote\([^)]*\)\.push\(|\borigin\.push\(|"
                          r"\.git\.push\(", _I),
    "persistence": re.compile(r"(?:shutil\.copy\w*|copyfile|copyFileSync|writeFileSync|write_text|open)\([^)]*"
                              r"(?:LaunchAgents|LaunchDaemons|\.config/autostart)|\bCronTab\(|"
                              r"make\s+(?:new\s+)?login\s+item", _I),
    "outbound": re.compile(r"\.sendmail\(|\.send_message\(|chat[._]post(?:Message|Ephemeral)\(|"
                           r"\bsend_(?:raw_)?email\(|\.emails?\.send\(|\bEmails\.send\(|\byagmail\b.*\.send\(|"
                           r"\bSendGridAPIClient\b|@sendgrid/mail|\b\w*mail\w*\.send\(|\bnodemailer\b|\.sendMail\(|"
                           r"application\s+\"Mail\"[\s\S]{0,2000}\bsend\b|" + _MAIL_API + r"|"
                           r"/messages\.send|/v3/mail/send|api\.telegram\.org/bot|hooks\.slack\.com/services/|"
                           r"discord(?:app)?\.com/api/webhooks/", _I),
    "destructive": re.compile(r"shutil\.rmtree|os\.(?:remove|unlink|rmdir)\b|\.(?:rm|rmdir|unlink)Sync\(|\brimraf\b|"
                              r"\bdelete\s+from\s+[\w.\"`]+\s*(?:;|$)|\b(?:drop|truncate)\s+(?:table|database|schema)\b", _I),
    "database": re.compile(r"\b(?:drop|truncate|alter)\s+(?:table|database|schema)\b", _I),
}
# MCP tools are judged by their names.
_MCP_SERVICE = re.compile(r"gmail|e?mail|slack|telegram|discord|sms|twilio|whatsapp|imessage|outlook|teams|messenger|"
                          r"google[-_]?workspace|gsuite|ms[-_]?365|office[-_]?365|microsoft|apple[-_]?mcp", _I)
_MCP_MAIL = re.compile(r"gmail|e?mail|smtp|outlook|postmark|sendgrid|resend|brevo|mailjet|sparkpost", _I)
_MCP = {
    "outbound": re.compile(r"(?:send|post|reply|forward)\w*", _I),
    "publish": re.compile(r"push_files|merge_pull|create_pull_request(?!_review)|create_release|publish|deploy|"
                          r"create_or_update_file|delete_file|"
                          r"update_file|create_commit|create_tree|update_ref|create_branch", _I),
    "deploy": re.compile(r"deploy|rollout|apply_terraform|terraform_apply", _I),
    "persistence": re.compile(r"(?:create|add|update|set)_?\w*(?:schedul|cron|trigger|routine|reminder)|"
                              r"(?:schedul|cron)\w*_?(?:create|add|set)", _I),
    "egress": re.compile(r"fetch|http|browser|navigate|web_?search|request|scrape", _I),
    "database": re.compile(r"sql|postgres|mysql|supabase|database|execute_query", _I),
    "destructive": re.compile(r"delete|drop_|remove|destroy|purge", _I),
}
# A brief is prose, and prose says "root cause", "admin dashboard", "review PR #42" and
# "release notes". In a brief these topics need the act itself named.
_BRIEF = {
    "secrets": re.compile(r"\.env\b|\bcredentials?\b|\bapi[_\s-]?keys?\b|\bprivate\s+keys?\b|\bpasswords?\b|"
                          r"\bssh\s+keys?\b|\b(?:access|auth|bearer|api|github|npm|session)\s+tokens?\b|\bsecrets?\b(?!\s+scanning)", _I),
    "privilege": re.compile(r"\bsudo\b|\bdoas\b|\bas\s+root\b|\broot\s+(?:shell|access|privileges?|user|password)\b|"
                            r"administrator\s+privileges|\bsu\s+-\b|\bchown\s+root\b", _I),
    "publish": re.compile(r"\bpush\b(?!\s+notification)|\bpublish(?:es|ed|ing)?\b|\bdeploy\w*\b|\bmerge\s+(?:it\s+)?(?:in)?to\s+"
                          r"(?:main|master|prod)|\b(?:cut|tag|ship)\s+(?:a\s+|the\s+)?release\b|\bnpm\s+publish\b", _I),
    "outbound": re.compile(r"\b(?:send|email|mail|message|text|dm)\s+(?:it\s+|them\s+|this\s+|the\s+\w+\s+)?(?:to\s+)?"
                           r"(?:\S+@\S+|the\s+(?:team|customer|client|user)s?|everyone|\w+\s+on\s+(?:slack|email))|"
                           r"\bsend\s+(?:an?\s+|the\s+)?(?:email|mail|message|newsletter|invite)", _I),
}
_PRIV_WRAP = shell.PRIV_WRAP
_BG_WRAP = {"nohup", "disown", "setsid"}
_SENSITIVE = shell.SENSITIVE
_AUTOSTART = shell.AUTOSTART
_AGENT = re.compile(r"(?:^|/)(?:CLAUDE|AGENTS|GEMINI)\.md$|/\.claude/|/\.codex/|/\.cursor/|\.mcp\.json$|/\.gemini/|"
                    r"\.cursorrules$|\.windsurfrules$")
_PROFILE = shell.PROFILE
# Asking a CLI how it works is not running it. Only the shapes where the help
# flag cannot be an operand count: BSD `rm important --help` deletes important.
_HELP_LAST = {"--help", "-h", "--version", "-V"}
_MULTI_CLI = {"git", "gh", "gog", "npm", "pnpm", "yarn", "bun", "vercel", "netlify", "fly", "flyctl", "wrangler",
              "docker", "podman", "kubectl", "helm", "aws", "gcloud", "az", "brew", "cargo", "pip", "pip3", "uv",
              "pipx", "poetry", "himalaya", "supabase", "firebase", "railway", "heroku", "terraform", "launchctl",
              "systemctl", "pm2", "twine", "gem", "go", "deno", "op", "vault", "prisma", "stripe", "gsutil"}
_NO_HELP = {"ssh", "scp", "sftp", "telnet", "nc", "ncat", "socat", "mosh", "rsync"}
# These look at a file without opening it: `ls -la .env` reads no secret.
_META = {"ls", "stat", "test", "[", "[[", "du", "file", "realpath", "readlink", "basename", "dirname", "lsof"}


# A tool whose name starts like this looks; it does not act.
_MCP_LOOKS = re.compile(r"^(?:get|list|read|search|find|view|show|describe|status|check|fetch_status|inspect)_?", _I)
# These open no file's contents: they create, move, mark or delete one.
_NO_READ = {"touch", "chmod", "chown", "chgrp", "mkdir", "rm", "rmdir", "unlink", "trash", "mv", "ln", "xattr",
            "mkcert"}
# These hand a file to a program that loads it; your agent never sees what is inside.
_LOADS = re.compile(r"(?:--env-file|--secret\s+id=\S+,src|--secret|dotenv\b.*?\s-e)(?:=|\s+)(\S+)")
# Asking for a dry run is not doing it.
_DRY = re.compile(r"(?:^|\s)(?:--dry-run|--dryrun|-n)(?:\s|$)")


_CODE_SECRET = re.compile(r"['\"`](?:[^'\"`]*/)?(?:\.env(?:\.(?!example|sample|template)\w+)?|id_rsa|id_ed25519|"
                          r"\.npmrc|\.netrc|\.pgpass|credentials(?:\.json)?|[\w-]+\.env)['\"`]")
_CODE_READS = re.compile(r"\bopen\(|read_text|read_bytes|readFile|File\.read|IO\.read|\bslurp|<\$?\w*>|dotenv_values|"
                         r"\bcat\b", _I)
_CONFIG_LOAD = re.compile(r"\bload_dotenv\(|dotenv['\"]\)\.config\(|\bdotenv\.config\(")
_PRINTS_ENV = re.compile(r"\bprintenv\b|^\s*env\s*$|process\.env|os\.environ|ENV\[|\$ENV\{|echo\s+\$\w", _I | re.M)
_ENV_SOURCE = re.compile(r"process\.env|os\.(?:environ|getenv)|ENV\[|\$ENV\{", _I)
_ENV_SINK = re.compile(r"\b(?:print\w*|pprint|puts|console\.(?:log|dir|table)|(?:sys|process)\.stdout\.write|"
                       r"(?:requests|httpx)\.(?:post|put|patch)|fetch|sendmail|send_message|sendMail)\s*\(([^;\n]*)", _I)


def _exposes_environment(code: str) -> bool:
    """Recognize direct output and ordinary local aliases of environment data."""
    aliases = set()
    assignments = re.findall(r"\b([A-Za-z_]\w*)\s*=\s*([^;\n]+)", code)
    for _ in range(min(len(assignments), 16)):
        before = len(aliases)
        for name, value in assignments:
            if _ENV_SOURCE.search(value) or aliases.intersection(re.findall(r"\b[A-Za-z_]\w*\b", value)):
                aliases.add(name)
        if len(aliases) == before:
            break
    return any(_ENV_SOURCE.search(m.group(1)) or aliases.intersection(re.findall(r"\b[A-Za-z_]\w*\b", m.group(1)))
               for m in _ENV_SINK.finditer(code))


# A recursive grep prints only the lines it matches. It shows a .env secret when
# its pattern can match a secret line, not when it looks for TODO.
_SECRET_LINE = re.compile(r"key|token|secret|pass|pwd|auth|cred|database_url|dsn|private|bearer|^[.^$*\\w]{0,2}$|=", _I)


def _grep_finds_secrets(text: str) -> bool:
    words = text.split()[1:]
    pat, k = None, 0
    while k < len(words):
        w = words[k]
        if w in ("-e", "--regexp") and k + 1 < len(words):
            pat = words[k + 1]
            break
        if not w.startswith("-"):
            pat = w
            break
        k += 1
    # only the files it is told to read, and only names if -l/-L/-c: neither shows a .env line
    inc = [g.strip("'\"") for g in re.findall(r"--include=(\S+)", text)]
    if inc and not any(fnmatch_any(n, g) for g in inc for n in (".env", ".env.local", ".env.production")):
        return False
    if re.search(r"(?:^|\s)-\w*[lLc]\w*(?:\s|$)|--files-with(?:out)?-match|--count\b", text):
        return False
    return pat is None or bool(_SECRET_LINE.search(pat.strip("'\"")))


def fnmatch_any(name: str, glob: str) -> bool:
    import fnmatch
    return fnmatch.fnmatch(name, glob) or fnmatch.fnmatch(name, glob.split("/")[-1])


def _FS_OK() -> bool:
    return shell._FS[0]


def _asks_how(u) -> bool:
    if u.kind != "shell" or u.head in _NO_HELP or not u.head:
        return False
    words = u.text.split()
    try:
        at = [os.path.basename(w).lower() for w in words].index(u.head)
    except ValueError:
        return False
    args, k = [], at + 1
    while k < len(words):
        w = words[k]
        if w in (">", ">>", "<"):
            k += 2
            continue
        if (w.isdigit() or w == "&") and k + 1 < len(words) and words[k + 1] in (">", ">>"):
            k += 1
            continue
        args.append(w)
        k += 1
    if not args or args[-1] not in _HELP_LAST:
        return False
    mid = args[:-1]
    return not mid or (u.head in _MULTI_CLI and len(mid) <= 4 and all(re.fullmatch(r"[a-z][a-z0-9-]*", w) for w in mid))


def categories(u: shell.Unit) -> set:
    """What one unit did, in the gate's vocabulary."""
    out = set()
    words = u.text.split()
    hi = 0
    for i, w in enumerate(words):
        if os.path.basename(w).lower() == u.head:
            hi = i
            break
    if u.kind == "shell" and not u.head:
        # The wrappers consumed every word: `sudo -i`, `sudo -s`, `exec doas -s`.
        # That is a root shell, the strongest form of the act, and with no head
        # to anchor on it used to read as no command at all.
        hi = len(words)
    prefix = {os.path.basename(w).lower() for w in words[:hi]}
    cmd = " ".join(words[hi:]) if not u.data else u.head
    if u.kind == "note":
        return out                   # a plan or a todo describes work; it does none
    if u.kind == "brief":
        # A remote agent runs where no hook sees it: what it is asked to do is the act.
        # Clause by clause, and never inside a refusal: "Don't run git push" asks for no push.
        for clause in re.split(r"[.;!?\n]+", u.text):
            for cid in ("outbound", "email", "publish", "git_push", "deploy", "persistence", "privilege", "destructive", "secrets"):
                m = (_BRIEF.get(cid) or TOPICS_C[cid]).search(clause)
                if m and not shell._NEGATED.search(clause[:m.start()]):
                    out.add(cid)
        return out
    if u.kind == "mcp":
        name = u.tool
        leaf = name.split("__")[-1]
        looks = bool(_MCP_LOOKS.match(leaf))
        for cid, rx in _MCP.items():
            if looks and cid in ("outbound", "publish", "deploy", "destructive"):
                continue
            if rx.search(leaf) and (cid != "outbound" or _MCP_SERVICE.search(name)):
                out.add(cid)
        # one tool, many operations: apple-mcp mail {operation: send}
        if not looks and _MCP_SERVICE.search(name) and not re.search(r"draft|list|get|search|read|fetch", leaf, re.I) \
                and re.search(r"(?:^|\s)(?:send|reply|forward)\w*(?:\s|$)", u.text):
            out.add("outbound")
        if "outbound" in out and _MCP_MAIL.search(name):
            out.add("email")
        if "publish" in out and re.search(r"git_push|push_files|create_or_update_file|update_ref", leaf):
            out.add("git_push")
        cmd = ""
    elif u.kind in ("shell", "other") and not _asks_how(u):
        for cid, rx in _CAT_CMD.items():
            if rx.search(cmd):
                out.add(cid)
        if (prefix & _PRIV_WRAP or u.head in _PRIV_WRAP) and not shell.priv_info_only(words):
            out.add("privilege")
        if prefix & _BG_WRAP:
            out.add("background")
        if "publish" in out and _DRY.search(cmd):
            out.discard("publish")
            out.discard("git_push")
    runs_code = u.head in shell.INTERPRETERS and u.head not in shell.SHELLS
    if (runs_code or u.kind == "mcp") and not u.data:
        # Only code can call an API. The same words in a grep pattern, a file
        # name, a search query or a commit message call nothing.
        for cid, rx in _CAT_CODE.items():
            if rx.search(u.text):
                out.add(cid)
    if u.kind == "web":
        out.add("egress")
    if u.feeds_code and u.head in ("curl", "wget"):
        out.add("supplychain")       # a download piped into something that runs it
    if "supplychain" in out:
        out.add("egress")            # installing a package downloads it
    writes = u.writes or []
    sub = u.text.split()[1:2]
    looks_only = (u.head in _META or u.head in _NO_READ or u.tool == "Glob"
                  or (u.head == "git" and set(sub) & {"check-ignore", "ls-files", "status", "rm", "mv", "log", "add"})
                  or (u.head == "find" and not re.search(r"\s-(?:exec|execdir|ok|delete)\b", u.text))
                  or (u.head == "ssh-keygen" and re.search(r"\s-t\s", u.text) is not None))
    loaded = set(_LOADS.findall(u.text)) if u.kind == "shell" else set()
    env_output = _PRINTS_ENV.search(u.text) and (u.origin == "command" or _exposes_environment(u.raw or u.text))
    config_only = runs_code and _CONFIG_LOAD.search(u.text) and not _CODE_READS.search(u.text) \
        and not env_output
    # A secret counts when it is read: written to, created, listed or handed
    # to a program to load, the agent never sees what is inside.
    # An editor opens the file it rewrites: `vim -es -c '%p' .env` prints it.
    opens = u.head in shell._EDITORS and u.head != "sponge"
    reads = [] if looks_only or config_only else [p for p in (u.paths or []) if (p not in writes or opens)
                                   and not any(p.endswith(l.lstrip("$HOME").lstrip("~")) for l in loaded)]
    if u.head == "git" and sub == ["show"]:
        reads += [w.split(":", 1)[1] for w in u.text.split()[2:] if ":" in w]
    if any(_SENSITIVE.search(p) for p in reads):
        out.add("secrets")
    if any(re.search(r"(?:^|/)\.env(?:\.(?!(?:example|sample|template|dist)(?:\.|$))[\w.-]+)?$|(?:^|/)[\w-]+\.env$", p)
           for p in reads):
        out.add("dotenv")
    if runs_code and _CODE_SECRET.search(u.text) and _CODE_READS.search(u.text):
        out.add("secrets")           # open(os.path.join(os.getcwd(), '.env')).read()
        if re.search(r"\.env\b", u.text):
            out.add("dotenv")
    if (loaded or re.search(r"\bdotenv\b|--env-file", u.text)) and env_output:
        out.add("secrets")           # node --env-file=.env -e 'console.log(process.env)'
        out.add("dotenv")
    if u.head in ("grep", "egrep", "fgrep") and re.search(r"\s-\w*[rR]", u.text) and _FS_OK() \
            and not re.search(r"--exclude(?:-dir)?=\S*env", u.text) and _grep_finds_secrets(u.raw or u.text):
        for d in (u.paths or []):
            if os.path.isdir(d) and any(os.path.exists(os.path.join(d, n)) for n in (".env", ".env.local")):
                out.add("secrets")   # grep -rn KEY . reads .env along with everything else
                out.add("dotenv")
                break
    if writes or u.kind == "write":
        out.add("write")
    removing = u.head in ("rm", "unlink", "trash") or (u.head == "chmod" and re.search(r"\s[ugoa]*-[rwx]*x", u.text)) \
        or (u.head == "mv" and writes and not _AUTOSTART.search(writes[-1]))
    if not removing and any(_AUTOSTART.search(p) for p in writes):
        out.add("persistence")
    if u.background:
        out.add("background")
    if any(_AGENT.search(p) for p in writes):
        out.add("agent_config")
    if any(_PROFILE.search(p) for p in writes):
        out.add("shell_profile")
        out.add("persistence")       # a login shell runs it at every start: that is running at startup
    if re.search(r"\bsleep\s+(?:[6-9]\d|\d{3,})\s*(?:&&|;)\s*\S", u.text) and (prefix & _BG_WRAP or u.background):
        out.add("persistence")       # nohup sh -c 'sleep 7200 && job' &: a job set to run later
    # Loading dotenv as application configuration is handled by _LOADS above.
    # An explicit read remains a read when its code comes from a script file.
    return out


# ------------------------------------------------------------- reading a rule

TOPICS = {
    "dotenv": r"(?:\.env\b|\bdotenv\b)",
    "email": r"\b(?:e-?mails?|e-?mailing|mails?)\b",
    "git_push": r"\bgit\s+push(?:es|ing)?\b",
    "outbound": r"\b(?:e-?mails?|e-?mailing|mails?|messages?|messaging|dms?|texts?|texting|slack|telegram|"
                r"discord|sms|whatsapp|imessage|notify|notifications?|tweet\w*)\b",
    "publish": r"\b(?:push|pushes|pushing|publish\w*|releases?|releasing|pull\s+requests?|prs?)\b",
    "deploy": r"\b(?:deploy\w*|ship|shipping|go\s+live|roll\s*outs?|infrastructure|infra)\b",
    "egress": r"\b(?:network|internet|online|web|websites?|urls?|download\w*|upload\w*|fetch\w*|curl|wget|"
              r"outside\s+world|external\s+(?:sites?|servers?|services?|apis?)|exfiltrat\w*|send\s+data|http)\b",
    "destructive": r"\b(?:delet\w*|remov\w*|rm|wip\w*|eras\w*|destroy\w*|drop|dropping|discard\w*|"
                   r"hard\s+reset|clean)\b",
    "supplychain": r"\b(?:install\w*|dependenc\w*|packages?|third[-\s]party|librar\w*)\b",
    "privilege": r"\b(?:sudo|root|admin\w*|privileges?|elevated|superuser)\b",
    "secrets": r"(?:\.env\b|\bdotenv\b|\bsecrets?\b|\bcredentials?\b|\bpasswords?\b|\bapi\s*keys?\b|"
               r"\bkeys?\b|\btokens?\b|\bkeychain\b|\bprivate\s+keys?\b)",
    "persistence": r"\b(?:schedul\w*|cron\w*|launchd|launch\s+agents?|daemons?|keeps?\s+running|persist\w*|"
                   r"at\s+(?:startup|login|boot)|on\s+(?:startup|login|boot)|autostart\w*|login\s+items?)\b",
    "background": r"\b(?:background|nohup|detach\w*|long[-\s]running)\b",
    "database": r"\b(?:databases?|db|psql|postgres\w*|mysql|mongo\w*|redis|sqlite\w*|migrations?|sql)\b",
    "git_history": r"\b(?:rebase|amend\w*|force[-\s]*push\w*|rewrit\w*\s+(?:git\s+)?history|git\s+history|"
                   r"filter-branch)\b",
    "write": r"\b(?:writ\w*|edit\w*|modif\w*|overwrit\w*|chang\w*|creat\w*|sav\w*)\s+(?:to\s+)?"
             r"(?:any\s+|my\s+|the\s+|new\s+)?(?:files?|code|anything|disk|folders?|director\w*)\b|"
             r"\b(?:writ\w*|edit\w*)\s+(?:anything\s+)?outside\b",
    "agent_config": r"(?:\bclaude\.md\b|\bagents\.md\b|\b(?:its|their|the\s+agent'?s?|your)\s+own\s+"
                    r"(?:settings|config\w*|instructions|permissions|rules|hooks)\b|\bagent\s+(?:settings|"
                    r"config\w*|instructions)\b|\bsettings\.json\b|\bmcp\s+config\w*)",
    "shell_profile": r"\b(?:shell\s+profiles?|zshrc|bashrc|bash_profile|zprofile|dotfiles?|shell\s+config\w*|"
                     r"shell\s+startup)\b",
}
TOPICS_C = {k: re.compile(v, _I) for k, v in TOPICS.items()}
_PROD = re.compile(r"\b(?:production|prod)\b", _I)
_TEMPORAL = re.compile(r"\b(?:(?:mon|tues|wednes|thurs|fri|satur|sun)days?|weekends?|weekdays?|holidays?|"
                       r"january|february|march|april|june|july|august|september|october|november|december)\b|"
                       r"\b(?:on|during|after|before|until|except|only|at|by|in)\s+(?:every\s+|the\s+)?"
                       r"(?:may|business\s+hours?|work\s+hours?|mornings?|afternoons?|evenings?|nights?|noon|midnight|"
                       r"\d{1,2}(?::\d{2})?(?:\s*(?:am|pm))?)\b|\b\d{4}-\d{2}-\d{2}\b|"
                       r"\b(?:today|tomorrow|tonight|after\s+hours|daily|weekly|monthly)\b|"
                       r"\b(?:older|newer)\s+than\s+\d+\s+(?:days?|hours?|minutes?|weeks?|months?)\b", _I)

_NEG = r"(?:never|don'?t|do\s+not|dont|no\s+one|nobody|must\s+not|mustn'?t|may\s+not|can\s*not|can'?t|" \
       r"should\s*n[o']t|shouldn'?t|not)"
_ASK_NEG = re.compile(_NEG + r"\b.*\bwithout\s+(?:first\s+)?(?:asking|checking|approval|permission|confirm\w*|"
                      r"my\s+(?:ok|okay|approval|permission))", _I)
_ASK = re.compile(
    r"\b(?:ask\s+(?:me\s+)?(?:first|before|for)?|always\s+ask|check\s+with\s+me|confirm\s+(?:with\s+me\s+)?"
    r"(?:first|before)?|get\s+(?:my\s+)?approval|require\s+(?:my\s+)?approval|needs?\s+my\s+(?:ok|approval)|"
    r"run\s+(?:it\s+)?by\s+me|only\s+with\s+my\s+(?:ok|approval|permission))\b", _I)
_BLOCK = re.compile(
    r"\b(?:never|don'?t|do\s+not|dont|must\s+not|mustn'?t|may\s+not|can\s*not|can'?t|should\s+not|shouldn'?t|"
    r"(?:is|are|isn'?t|aren'?t)\s+not\s+allowed|not\s+allowed|isn'?t\s+allowed|aren'?t\s+allowed|"
    r"not\s+permitted|forbid(?:den)?|prohibit(?:ed)?|block|refuse|avoid|ban(?:ned)?|"
    r"under\s+no\s+circumstances|no\s+one|nobody)\b|^\s*no\s+\w", _I)
_ALLOW = re.compile(
    r"\b(?:may|can|(?:is|are)\s+allowed\s+to|allowed\s+to|permitted\s+to|(?:it'?s\s+)?(?:fine|ok|okay)\s+to|"
    r"free\s+to|freely|without\s+asking|no\s+need\s+to\s+ask|always\s+allow|allow)\b", _I)

_BACKTICK = re.compile(r"`([^`]+)`")
_QUOTED = re.compile(r"[\"“]([^\"”]+)[\"”]")
_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]*\w\b")
_PATH = re.compile(r"(?<![\w`\"@])((?:~|\.{1,2}|\$HOME)?/[\w.*@%+~-]+(?:/[\w.*@%+~-]+)*/?|~(?=[\s.,;:!?)]|$))")
_TOOL = re.compile(r"\b(mcp__[\w-]+(?:__[\w*-]+)?|Bash|Write|Edit|MultiEdit|NotebookEdit|Read|Grep|Glob|"
                   r"WebFetch|WebSearch|Task)\b")
_OUTSIDE = re.compile(
    r"\b(?:outside(?:\s+of)?|anywhere\s+but|except(?:\s+(?:in|under|inside|within|for))?|"
    r"unless\s+(?:it'?s\s+|they'?re\s+|they\s+are\s+|it\s+is\s+)?(?:in|under|inside|within)|"
    r"other\s+than\s+(?:in|under)|apart\s+from|besides|but\s+not\s+(?:in|under))\s+", _I)
_HERE = re.compile(r"^\s*(?:this|the|my|our)\s+(?:repo(?:sitory)?|project|folder|directory|codebase)\b", _I)
_SENT = re.compile(r"(?<=[.!?])\s+(?=[A-Z`\"“])")

# Words that carry no scope. What is left after removing these, the verdict,
# the topic words and the captured objects is a qualifier kyma cannot check.
# An exception with an uncheckable qualifier is NOT enforced: guarding more
# than you wrote is safe, permitting more than you wrote is not.
_FILLER = set("""
a an the any all every some to of for in on at by with without from into onto my me i you your yours it its
it's they them their this that these those here there and or but so also too just please only ever always
claude codex agent agents assistant model ai bot let lets allowed allow fine ok okay free freely may can
is are be being been do does use uses using run runs running execute executes call calls make makes send sends sending
asking ask first before need needs no without permission approval check checking confirm one own
anything everything something stuff thing things file files folder folders directory directories new
read reads reading write writes writing edit edits editing open opens view access accesses touch touches
change changes modify modifies create creates commands command tool tools project repo repository code
inside within under outside except unless other than apart besides go goes get gets set sets
""".split())


_AGENT_NAME = re.compile(r"^\s*(?:the\s+)?[A-Z][\w-]*(?=\s+(?:may|can|is\s+allowed|is\s+free|is\s+fine)\b)")


def _clean_path(p: str) -> str:
    return p.strip().rstrip(".,;:!?)'\"").rstrip("/") or p.strip()


def _canon_literal(lit: str) -> str:
    """`rm -fr x` in a rule must mean what `rm -rf x` in a command means."""
    words = shell._tokens(lit)
    head, at = shell._head(words)
    return " ".join(shell._canon(words, head, at)).lower()


@dataclass
class Rule:
    text: str
    line: int
    source: str = "RULES.md"
    verdict: str = BLOCK
    topics: list = field(default_factory=list)
    any_topic: bool = False                           # topics joined by "or"
    literals: list = field(default_factory=list)      # commands or words, canonicalised
    emails: list = field(default_factory=list)
    paths: list = field(default_factory=list)         # absolute, resolved
    tools: list = field(default_factory=list)
    outside: str = ""                                 # absolute path, or "@project"
    except_hosts: list = field(default_factory=list)  # "except github.com", "outside example.com"
    prod: bool = False                                # sentence said production
    trust: str = "global"
    base: str = ""                                    # directory of the RULES.md
    enforced: bool = True
    problem: str = ""
    cite: dict = field(default_factory=dict)          # where the rule came from: source, approved, version
    cite_problem: str = ""                            # a source group kyma could not read; the rule still holds

    @property
    def where(self) -> str:
        return f"{self.source}:{self.line}"

    @property
    def cited(self) -> str:
        """'DPA §4.1, approved by Apolline, version 2': the rule's own source, for every verdict."""
        c = self.cite or {}
        parts = [c["source"]] if c.get("source") else []
        if c.get("approved"):
            parts.append("approved by " + c["approved"])
        if c.get("version"):
            parts.append("version " + c["version"])
        return ", ".join(parts)

    # ---------------------------------------------------------- read back
    def explain(self) -> str:
        if not self.enforced:
            return f"not enforced ({self.problem})"
        parts = []
        if self.topics:
            parts.append((" or " if self.any_topic else " and ").join(ACTION_LABEL[t] for t in self.topics))
        if self.literals:
            parts.append("only " + " or ".join(f"`{x}`" for x in self.literals))
        if self.emails:
            parts.append(("only to " if self.verdict == ALLOW else "to ") + ", ".join(self.emails))
        if self.paths:
            parts.append("under " + " or ".join(_tilde(p) for p in self.paths))
        if self.prod:
            parts.append("mentioning production")
        if self.tools:
            parts.append("tool " + "/".join(self.tools))
        scope = ""
        if self.outside:
            scope = " · only outside " + ("this project" if self.outside == "@project" else _tilde(self.outside))
        return (f"{self.verdict}  ·  {' · '.join(parts)}{scope}" + (f"  ·  from {self.cited}" if self.cite else "")
                + (f"  ·  source not read: {self.cite_problem}" if self.cite_problem else ""))

    # ------------------------------------------------------------- match
    def applies(self, u: shell.Unit, cats: set, project: str | None = None) -> bool:
        if not self.enforced:
            return False
        if self.tools and not _tool_ok(self.tools, u.tool):
            return False
        if self.topics:
            want = set(self.topics)
            if self.any_topic:
                if not (want & cats):
                    return False
            elif not want <= cats:
                return False
        text = u.text.lower()
        if self.literals and not any(_has_literal(text, lit) for lit in self.literals):
            return False
        if self.emails and self.verdict != ALLOW:
            if not any(e.lower() in text for e in self.emails):
                return False
        if self.emails and self.verdict == ALLOW:
            if not any(e.lower() in text for e in self.emails):
                return False
        if self.paths and not any(_under(p, rp) for p in u.paths for rp in self.paths):
            return False
        if self.prod and not re.search(r"(?<![\w-])(?:prod|production)(?![\w])", text):
            return False
        if self.except_hosts:
            hosts = _hosts(u.text)
            if hosts and all(any(h == d or h.endswith("." + d) for d in self.except_hosts) for h in hosts):
                return False
        if self.outside:
            zone = project if self.outside == "@project" else self.outside
            if not zone:
                return False
            relevant = u.writes or u.paths
            if not relevant or all(_under(p, zone) for p in relevant):
                return False
        return bool(self.topics or self.literals or self.emails or self.paths or self.tools)

    def covers(self, hold: "Rule", u: shell.Unit, cats: set, project: str | None) -> bool:
        """Can this allow rule lift that hold, for this unit?"""
        if self.verdict != ALLOW or not self.applies(u, cats, project):
            return False
        if hold.trust != self.trust:
            return False                       # each policy layer keeps its own holds and exceptions
        if hold.topics:
            mine = set(self.topics)
            for lit in self.literals:          # `git push origin x` speaks about publishing
                mine |= categories(shell.shell_units(lit)[0]) if shell.shell_units(lit) else set()
            # A permission for the parent category covers its named subset.
            # A subset permission also lifts the parent hold for this call,
            # after applies() established that the narrower permission matches.
            parents = {"email": "outbound", "git_push": "publish", "deploy": "publish", "dotenv": "secrets"}
            if not all(t in mine or parents.get(t) in mine or
                       any(parents.get(m) == t for m in mine) for t in hold.topics):
                return False
        elif hold.tools and not (hold.paths or hold.literals or hold.emails):
            if not self.tools or not set(hold.tools) <= set(self.tools):
                return False
        if self.emails:
            sent_to = {e.lower() for e in _EMAIL.findall(u.text)}
            if not sent_to or not sent_to <= {e.lower() for e in self.emails}:
                return False                   # an exception for one person covers that person alone
        if self.paths:
            scope = [p for p in u.paths if not hold.paths or any(_under(p, hp) for hp in hold.paths)]
            if not scope or not all(any(_under(p, ap) for ap in self.paths) for p in scope):
                return False
        if hold.literals and not self.literals and not self.paths:
            return False
        if hold.paths and not self.paths and not self.literals:
            return False
        if not (self.topics or self.literals or self.emails or self.paths):
            if hold.topics or hold.paths or hold.literals or hold.emails:
                return False                   # "may use Bash" lifts nothing it does not name
        return True

    def matches(self, tool: str, subject: str) -> bool:
        """Replay helper: does this rule fire anywhere in a recorded command?"""
        inp = {"command": subject} if tool == "Bash" else {"file_path": subject}
        for u in shell.units_for(tool, inp):
            if self.applies(u, categories(u)):
                return True
        return False


_HOST = re.compile(r"(?:https?|ftp|wss?)://([\w.-]+)|git@([\w.-]+):|[\w.+-]+@([\w-]+(?:\.[\w-]+)+)", _I)


def _hosts(text: str) -> list:
    """Hosts a unit reaches and domains it writes to."""
    out = []
    for m in _HOST.finditer(text):
        h = (m.group(1) or m.group(2) or m.group(3) or "").lower().rstrip(".")
        if h:
            out.append(h)
    return out


def _tilde(p: str) -> str:
    return "~" + p[len(shell.HOME):] if p.startswith(shell.HOME) else p


def _tool_ok(names: list, tool: str) -> bool:
    fam = {"Write": {"Write", "Edit", "MultiEdit", "NotebookEdit"}, "Edit": {"Edit", "MultiEdit", "NotebookEdit"}}
    for n in names:
        if n == tool or tool in fam.get(n, ()):
            return True
        if n.endswith("*") and tool.startswith(n[:-1]):
            return True
        if n.startswith("mcp__") and n.count("__") == 1 and tool.startswith(n + "__"):
            return True
    return False


def _has_literal(text: str, lit: str) -> bool:
    if not lit or lit not in text:
        # First the substring: with 2,000 rules each word pattern below was
        # compiled again on every call (re caches 512), 12.6 ms a call.
        return False
    if re.fullmatch(r"[\w.-]+", lit):
        return re.search(r"(?<![\w.-])" + re.escape(lit) + r"(?![\w-])", text) is not None
    return lit in text


def _under(path: str, prefix: str) -> bool:
    if not path or not prefix:
        return False
    fm = shell.fnmatch_safe
    if re.search(r"[*?\[]", prefix):
        return fm(path, prefix) or fm(os.path.basename(path), os.path.basename(prefix))
    p, q = path.rstrip("/").lower(), prefix.rstrip("/").lower()
    if re.search(r"[*?\[]", p):      # the call names a glob: could it reach the rule's path?
        # Inside it: `~/.ssh/*` is under ~/.ssh because the folders it names
        # before its first wildcard are. Above it: `~/*` could be ~/Documents.
        lit = "/".join(p.split("/")[:next(i for i, x in enumerate(p.split("/")) if re.search(r"[*?\[]", x))])
        if q.startswith("/") and lit and (lit == q or lit.startswith(q + "/")):
            return True
        return fm(q, p) or any(fm(q[:k], p) for k in range(1, len(q) + 1) if q[k - 1:k] == "/")
    if not q.startswith("/"):         # a relative path in a rule: anywhere it appears
        return p == q or p.endswith("/" + q) or ("/" + q + "/") in p + "/"
    return p == q or p.startswith(q + "/")


def _resolve(p: str, base: str) -> str:
    p = _clean_path(p)
    if p.startswith("$HOME"):
        p = "~" + p[5:]
    p = os.path.expanduser(p)
    if not p.startswith("/"):
        return os.path.normpath(p).lstrip("./") if p.startswith("./") else os.path.normpath(p)
    if re.search(r"[*?\[]", p):
        return p
    try:
        return os.path.realpath(os.path.normpath(p))
    except OSError:
        return os.path.normpath(p)


def _strip_markup(raw: str) -> str:
    raw = raw.replace("’", "'").replace("‘", "'")
    raw = re.sub(r"<!--.*?-->", " ", raw)
    raw = re.sub(r"(?<![\w*])\*\*(\S(?:.*?\S)?)\*\*(?![\w*])", r"\1", raw)
    raw = re.sub(r"(?<![\w_])__(\S(?:.*?\S)?)__(?![\w_])", r"\1", raw)
    raw = re.sub(r"(?<![\w*])\*(\S(?:.*?\S)?)\*(?![\w*])", r"\1", raw)
    raw = re.sub(r"(?<![\w_])_(\S(?:[^_]*?\S)?)_(?![\w_])", r"\1", raw)
    return raw.strip()


DATA_USE_PROBLEM = ("a data-use rule: kyma checks actions, not what data is used for; "
                    "Kyma reads these from contracts")
_DATA_NOUN = (r"(?:(?:customer|customers'?|user|users'?|client|patient|personal|employee|private|sensitive|health|"
              r"training)\s+(?:data|info\w*|records|tickets|emails|messages|conversations|content)|datasets?|"
              r"(?:support\s+)?tickets?|pii|phi)")
_DATA_USE = re.compile(
    r"\b(?:train(?:ing)?|fine[\s-]?tun\w*|pre[\s-]?train\w*)\s+(?:a\s+model\s+)?(?:on|with|using|from)\b|"
    r"\b(?:share|sharing|send|sending|sell|selling|disclose|disclosing|transfer|transferring|give|giving|"
    r"use|using|feed|feeding|expose|exposing|provide|providing)\b[^.;]{0,60}?\b" + _DATA_NOUN +
    r"\b[^.;]{0,60}?\b(?:with|to|into|for)\b|"
    r"\bretain\w*\b|\bretention\b|"
    r"\b(?:keep|store|hold)\b[^.;]{0,40}?\b" + _DATA_NOUN + r"\b[^.;]{0,30}?\b(?:longer\s+than|beyond|past|after|for\s+more\s+than)\b|"
    r"\b(?:delete|purge|erase)\w*\b[^.;]{0,60}?\bafter\s+\d+\s+(?:days?|weeks?|months?|years?|hours?)\b|"
    r"\bonly\s+for\s+(?:the\s+)?(?:purposes?\s+of|purposes?\b)|\b(?:used|use\s+\w+)\s+only\s+for\b|"
    r"\bfor\s+any\s+purpose\s+other\s+than\b",
    re.I)


# A rule can say where it came from, at the end of its line:
#   - Never upload files from ~/customers to any website. (source: DPA §4.1; approved: Apolline; version: 2)
# The group is taken off before the sentence is read, so the matcher is the
# same with it or without it; every verdict then names it.
# CLIs whose sentence form names one command: "terraform destroy", "kubectl delete".
# git is read by topic instead: "any git push" also means git send-pack and a
# write to a repository's refs through gh api.
_NAMED_CMD = re.compile(r"\b(terraform|tofu|kubectl|helm|gcloud|aws|az|docker|podman|npm|pnpm|yarn|cargo|gh|heroku|"
                        r"vercel|flyctl|fly|pulumi|brew|pip3?|systemctl|launchctl|make|rails|rake|ansible-playbook|"
                        r"dropdb|firebase|netlify|wrangler|cdk|serverless|eb|supabase|prisma|alembic)\s+"
                        r"([a-z][\w:-]*)\b", re.I)
_NOT_SUB = {"any", "anything", "command", "commands", "at", "in", "on", "to", "with", "without", "for", "or", "and",
            "the", "a", "an", "my", "me", "again", "here", "there", "unless", "before", "after", "when", "while",
            "except", "ever", "itself", "yourself", "files", "file", "at all", "please", "stuff", "things"}


_CITE = re.compile(r"\s*\(\s*([A-Za-z]+)\s*:([^()]*)\)\s*\.?\s*$")
CITE_KEYS = ("source", "approved", "version")


def split_cite(text: str) -> tuple:
    """-> (sentence, {key: value}, problem). A group that is not one is left in the sentence."""
    m = _CITE.search(text)
    if not m:
        return text, {}, ""
    cite, problem = {}, ""
    for part in (m.group(1) + ":" + m.group(2)).split(";"):
        if not part.strip():
            continue
        k, sep, v = part.partition(":")
        k, v = k.strip().lower(), " ".join(v.split())
        if not sep or not k:
            return text, {}, ""
        if k not in CITE_KEYS:
            problem = f"unknown key '{k}' in its source group: use source, approved or version"
            continue
        if v:
            cite[k] = v
    return text[:m.start()].rstrip(), cite, problem


def compile_rule(text: str, line: int, source: str = "RULES.md", base: str = "",
                 trust: str = "global", cite: dict | None = None, cite_problem: str = "") -> Rule | None:
    raw = text.strip()
    if cite is None:
        raw, cite, cite_problem = split_cite(raw)
    if not raw or raw.startswith("#") or raw.startswith("<!--") or raw.startswith(">"):
        return None
    raw = re.sub(r"^[-*+]\s+(?:\[[ xX]\]\s+)?", "", raw).strip()
    raw = re.sub(r"^\d+[.)]\s+", "", raw).strip()
    if raw.startswith("~~") and raw.rstrip(".").endswith("~~"):
        return None                                   # struck through: switched off
    raw = _strip_markup(raw)
    if not raw:
        return None
    from .signals import clean
    raw = clean(raw)

    # a source group kyma cannot read is not cited (a half-read source would cite the wrong one), and
    # it never switches the rule off: a typo in a citation must not turn a `never` into nothing
    r = Rule(text=raw, line=line, source=source, base=base, trust=trust,
             cite={} if cite_problem else dict(cite or {}), cite_problem=cite_problem)
    if _DATA_USE.search(raw):
        # "never train on customer tickets" is about what data is for, not an
        # action a tool call takes. Compiled, it became "block anything that
        # says `customer`": a keyword ban that holds the wrong calls.
        r.verdict = BLOCK if _BLOCK.search(raw) else ASK if _ASK.search(raw) else BLOCK
        r.enforced = False
        r.problem = DATA_USE_PROBLEM
        return r
    if _ASK_NEG.search(raw):
        r.verdict = ASK                               # "never X without asking" asks
    elif _BLOCK.search(raw):
        r.verdict = BLOCK
    elif _ASK.search(raw):
        r.verdict = ASK
    elif _ALLOW.search(raw):
        r.verdict = ALLOW
    else:
        r.enforced = False
        r.problem = "no never / ask me / may in the sentence"
        return r

    body = raw
    for rx in (_BACKTICK, _QUOTED):
        for m in rx.finditer(raw):
            val = m.group(1).strip()
            if not val:
                continue
            if re.match(r"^(?:~|/|\./|\.\./|\$HOME)", val) and " " not in val:
                r.paths.append(_resolve(val, base))
            elif _EMAIL.fullmatch(val):
                r.emails.append(val)
            elif _TOOL.fullmatch(val):
                r.tools.append(val)
            else:
                r.literals.append(_canon_literal(val))
            body = body.replace(m.group(0), " ")
    for m in _EMAIL.finditer(body):
        r.emails.append(m.group(0))
        body = body.replace(m.group(0), " ")
    for m in _TOOL.finditer(body):
        if m.group(1) not in r.tools:
            r.tools.append(m.group(1))
    body = _TOOL.sub(" ", body)

    m = _OUTSIDE.search(body)
    if m:
        tail = body[m.end():]
        pm = _PATH.match(tail.lstrip()) or _PATH.search(tail[:60])
        if _HERE.match(tail):
            r.outside = "@project"
            body = body[:m.start()] + " " + _HERE.sub(" ", tail, count=1)
        elif pm:
            r.outside = _resolve(pm.group(1), base)
            body = body[:m.start()] + " " + tail.replace(pm.group(1), " ", 1)
        elif re.match(r"\s*(?:for\s+|to\s+)?([\w-]+(?:\.[\w-]+)+)", tail):
            dm = re.match(r"\s*(?:for\s+|to\s+)?([\w-]+(?:\.[\w-]+)+)", tail)
            r.except_hosts.append(dm.group(1).lower().rstrip("."))
            body = body[:m.start()] + " " + tail[dm.end():]
        elif r.verdict == ALLOW:
            r.enforced, r.problem = False, "it names an exception kyma cannot place: give a path"
            return r
    for pm in _PATH.finditer(body):
        p = _resolve(pm.group(1), base)
        if p and p not in r.paths:
            r.paths.append(p)
    body = _PATH.sub(" ", body)
    if _TEMPORAL.search(body):
        r.enforced = False
        r.problem = "calendar and time conditions are not supported: use an unconditional rule or an exact command"
        return r

    if _PROD.search(body):
        r.prod = True
        body = _PROD.sub(" ", body)
    if r.paths and re.search(r"\b(?:writ\w*|edit\w*|modif\w*|overwrit\w*|chang\w*)\b", body, _I):
        r.topics.append("write")
    if not r.literals:
        # "Never run terraform destroy." names one command: the rule is that
        # command, as if it were in backticks, not "never delete anything".
        for cm in _NAMED_CMD.finditer(body):
            sub = cm.group(2).lower()
            if sub in _FILLER or sub in _NOT_SUB:
                continue
            r.literals.append(_canon_literal(f"{cm.group(1).lower()} {sub}"))
            body = body.replace(cm.group(0), " ")
    if r.verdict != ALLOW and not r.literals:
        for tm in re.finditer(r"\b(?:to|into|onto|on)\s+(?:the\s+)?([A-Za-z][\w.-]*)\b", body):
            word = tm.group(1).lower()
            if word not in _FILLER and not any(rx.fullmatch(word) for rx in TOPICS_C.values()) \
                    and word not in ("anyone", "anybody", "everyone", "people", "github", "disk"):
                r.literals.append(word)
    found = [t for t, rx in TOPICS_C.items() if rx.search(body) and t not in r.topics]
    found = r.topics + found
    if "dotenv" in found:
        other_secrets = TOPICS_C["secrets"].search(re.sub(r"\.env\b|\bdotenv\b", " ", body, flags=re.I))
        if other_secrets:
            found.remove("dotenv")
        elif "secrets" in found:
            found.remove("secrets")
    if "email" in found:
        if re.search(r"\b(?:messages?|messaging|dms?|texts?|slack|telegram|discord|sms|whatsapp|notify|notifications?)\b", body, _I):
            found.remove("email")
        elif "outbound" in found:
            found.remove("outbound")
    if "git_push" in found:
        if re.search(r"\b(?:publish\w*|releases?|pull\s+requests?|prs?)\b", body, _I):
            found.remove("git_push")
        elif "publish" in found:
            found.remove("publish")
    r.topics = found
    r.any_topic = len(found) > 1 and (re.search(r"\bor\b", body, _I) is not None
                                      or set(found) == {"persistence", "background"}
                                      or set(found) == {"publish", "deploy"})

    if not (r.topics or r.literals or r.emails or r.paths or r.tools):
        r.enforced = False
        r.problem = "nothing recognised to guard: name a category, a `command`, a path or an address"
        return r

    if r.verdict == ALLOW:
        # "My agent may ...", "Rex can ...": the sentence's subject is whatever the
        # owner calls their agent. A name is not a condition kyma could check,
        # and the gate only ever sees the agent anyway, so a leading
        # capitalised name before the permission verb carries no scope.
        rest = _AGENT_NAME.sub(" ", body, count=1)
        # A git push exception has the same publishing scope as the corresponding hold.
        rest = re.sub(r"\bgit\s+(?=push(?:es|ing)?\b)", " ", rest, flags=re.I)
        for rx in list(TOPICS_C.values()) + [_ALLOW, _BLOCK, _ASK]:
            rest = rx.sub(" ", rest)
        words = [w for w in re.findall(r"[A-Za-z][A-Za-z'-]*", rest.lower()) if w not in _FILLER]
        if words:
            r.enforced = False
            r.problem = (f"'{' '.join(words[:4])}' narrows this exception in a way kyma cannot check, "
                         "so it is not applied: name the exact command in backticks, or a path")
    return r


_BULLET = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+\S")


def parse(text: str, source: str = "RULES.md", base: str = "", trust: str = "global") -> list:
    """Rules are list items. A loose line that still reads as a rule is kept,
    because ignoring it silently is how a rule you wrote stops being applied."""
    lines = text.splitlines()
    bulleted = any(_BULLET.match(ln) for ln in lines)
    out, in_comment = [], False
    for i, line in enumerate(lines, 1):
        s = line
        if in_comment:
            if "-->" in s:
                in_comment = False
                s = s.split("-->", 1)[1]
            else:
                continue
        if "<!--" in s and "-->" not in s.split("<!--", 1)[1]:
            in_comment = True
            s = s.split("<!--", 1)[0]
        if not s.strip():
            continue
        loose = bulleted and not _BULLET.match(s)
        bullet_free = re.sub(r"^\s*(?:[-*+]|\d+[.)])\s+", "", s)
        # the source group belongs to the whole line: split it off before the sentences
        bullet_free, cite, cite_problem = split_cite(bullet_free.strip())
        for part in _SENT.split(bullet_free.strip()):
            rule = compile_rule(part, i, source, base, trust, cite=cite, cite_problem=cite_problem)
            if rule is None:
                continue
            if loose and not rule.enforced:
                continue          # prose in a bulleted file, not a rule
            out.append(rule)
    return out


class RulesError(Exception):
    """A rules file exists but cannot be read. The gate holds every call."""


def _decode(raw: bytes) -> str:
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16", "replace")
    return raw.decode("utf-8-sig", "replace")


def load(path: str, trust: str = "global") -> list:
    """Missing file: no rules. A file that exists but cannot be read: RulesError."""
    if not os.path.lexists(path):
        return []
    try:
        with open(path, "rb") as fh:
            raw = fh.read(1024 * 1024 + 1)
    except OSError as exc:
        raise RulesError(f"{path} exists but cannot be read ({exc.strerror or exc})") from exc
    if len(raw) > 1024 * 1024:
        raise RulesError(f"{path} is over 1 MB")
    source, base = os.path.basename(path), os.path.dirname(os.path.abspath(path))
    key = _cache_key(raw, source, base, trust)
    got = _cached(key)
    if got is not None:
        return got
    out = parse(_decode(raw), source=source, base=base, trust=trust)
    _cache_put(key, out)
    return out


# The hook reads RULES.md on every tool call. Compiling 2,000 rules took
# 120 ms of each call, and a 1 MB file most of two seconds; the compiled
# form is kept in kyma's own folder, keyed by the file's bytes and by this
# file's own version, so an edit to either compiles again.
_CACHE_NAME = "rules.compiled.json"
_FIELDS = None


def _cache_key(raw: bytes, source: str, base: str, trust: str) -> str:
    import hashlib
    try:
        st = os.stat(__file__)
        code = f"{st.st_mtime_ns}:{st.st_size}"
    except OSError:
        code = ""
    from . import __version__
    return hashlib.sha256(raw + b"\0" + "\0".join((source, base, trust, code, __version__)).encode()).hexdigest()


def _cache_file(key: str = "") -> str:
    """One file per compiled RULES.md: a single file holding every compiled
    form grew past what could be read back for a large project file, and
    every call compiled it again (865 KB, 1.9 s a call)."""
    from . import HOME
    return os.path.join(HOME, f"rules.compiled.{key[:32]}.json" if key else _CACHE_NAME)


_CACHE_LIMIT = 64 * 1024 * 1024


def _cached(key: str):
    try:
        from . import state_read
        import json
        text = state_read(_cache_file(key), _CACHE_LIMIT)
        if not text:
            return None
        d = json.loads(text)
        rows = d.get("rules") if isinstance(d, dict) and d.get("key") == key else None
        if not isinstance(rows, list):
            return None
        names = {f.name for f in fields(Rule)}
        out = []
        for row in rows:
            if not isinstance(row, dict) or set(row) != names:
                return None
            out.append(Rule(**row))
        return out
    except Exception:
        return None


def _cache_put(key: str, out: list) -> None:
    try:
        from . import HOME, home_problem, state_write
        import glob
        import json
        if not os.path.isdir(HOME) or home_problem():
            return
        state_write(_cache_file(key), json.dumps({"key": key, "rules": [asdict(r) for r in out]}))
        # a few files (yours, a project's or two): not every edit ever
        old = sorted(glob.glob(os.path.join(HOME, "rules.compiled.*.json")), key=os.path.getmtime)[:-4]
        for f in old + [os.path.join(HOME, _CACHE_NAME)]:
            try:
                os.unlink(f)
            except OSError:
                pass
    except Exception:
        pass


# ------------------------------------------------------------------- deciding

@dataclass
class Decision:
    verdict: str
    rule: Rule | None = None
    note: str = ""                           # for holds kyma raises itself

    @property
    def reason(self) -> str:
        if self.note:
            return self.note
        if not self.rule:
            return ""
        if self.rule.cite:
            return f"{self.rule.text} ({self.rule.cited}) [{self.rule.where}]"
        return f"{self.rule.text} [{self.rule.where}]"


class PreparedRules(list):
    """A policy snapshot with category candidates. Rebuild after a policy edit.

    Candidate selection removes impossible topic, literal and path predicates.
    applies() and covers() retain responsibility for every semantic decision.
    """

    def __init__(self, items):
        super().__init__(items)
        self.by_topic = {}
        self.by_gram = {}
        self.by_path_gram = {}
        self.path_rules = []
        self.unscoped = []
        self.allows = []
        self.order = {id(r): i for i, r in enumerate(self)}
        grams = {}
        for r in self:
            for lit in r.literals + [p.lower() for p in r.paths]:
                for gram in {lit[i:i + 3] for i in range(len(lit) - 2)}:
                    grams[gram] = grams.get(gram, 0) + 1
        for r in self:
            if not r.enforced:
                continue
            if r.verdict == ALLOW:
                self.allows.append(r)
            elif r.literals and all(len(lit) >= 3 for lit in r.literals):
                # A literal match necessarily contains every one of its trigrams.
                # Index its rarest trigram, then let applies() check the exact text.
                for lit in r.literals:
                    gram = min({lit[i:i + 3] for i in range(len(lit) - 2)}, key=lambda g: (grams[g], g))
                    self.by_gram.setdefault(gram, []).append(r)
            elif r.paths and all(len(p) >= 3 and not re.search(r"[*?\[]", p) for p in r.paths):
                self.path_rules.append(r)
                for path in r.paths:
                    path = path.lower()
                    gram = min({path[i:i + 3] for i in range(len(path) - 2)}, key=lambda g: (grams[g], g))
                    self.by_path_gram.setdefault(gram, []).append(r)
            elif not r.topics:
                self.unscoped.append(r)
            elif r.any_topic:
                for topic in r.topics:
                    self.by_topic.setdefault(topic, []).append(r)
            else:
                self.by_topic.setdefault(r.topics[0], []).append(r)

    def candidates(self, cats, text, paths):
        out = list(self.unscoped)
        seen = set()
        groups = [self.by_topic.get(topic, ()) for topic in cats]
        if self.by_gram:
            text = text.lower()
            groups.extend(self.by_gram[g] for g in {text[i:i + 3] for i in range(len(text) - 2)} if g in self.by_gram)
        if self.by_path_gram:
            if any(re.search(r"[*?\[]", p) for p in paths):
                groups.append(self.path_rules)   # a glob can reach a literal path without spelling its trigrams
            else:
                for path in paths:
                    path = path.lower()
                    groups.extend(self.by_path_gram[g] for g in {path[i:i + 3] for i in range(len(path) - 2)}
                                  if g in self.by_path_gram)
        for group in groups:
            for r in group:
                if id(r) not in seen:
                    seen.add(id(r))
                    out.append(r)
        return sorted(out, key=lambda r: self.order[id(r)])


def prepare_rules(items: list) -> PreparedRules:
    return items if isinstance(items, PreparedRules) else PreparedRules(items)


def decide_units(rules: list, units: list, project: str | None = None) -> Decision:
    best = Decision(ALLOW)
    prepared = rules if isinstance(rules, PreparedRules) else None
    allows = prepared.allows if prepared is not None else [r for r in rules if r.verdict == ALLOW]
    for u in units:
        cats = categories(u)
        candidates = prepared.candidates(cats, u.text, u.paths) if prepared is not None else rules
        holds = [r for r in candidates if r.verdict != ALLOW and r.applies(u, cats, project)]
        if u.delegated:
            holds = [r for r in holds if r.verdict == BLOCK]
        live = [h for h in holds if not any(a.covers(h, u, cats, project) for a in allows)]
        if not live:
            if best.verdict == ALLOW and best.rule is None:
                cover = [a for a in allows if a.applies(u, cats, project)]
                if holds and cover:
                    best = Decision(ALLOW, cover[-1])
            continue
        top = max(live, key=lambda r: (STRICT[r.verdict], len(r.literals) + len(r.paths) + len(r.emails), r.line))
        if STRICT[top.verdict] > STRICT[best.verdict] or (best.verdict == ALLOW):
            best = Decision(top.verdict, top)
    return best


def decide(rules: list, tool: str, subject: str) -> Decision:
    """Compatibility: judge a recorded command or path."""
    inp = {"command": subject} if tool == "Bash" else {"file_path": subject}
    return decide_units(rules, shell.units_for(tool, inp))


def excerpt(rule: Rule, command: str, span: int = 96) -> str:
    flat = " ".join(command.split())
    low = flat.lower()
    at = -1
    for lit in rule.literals + [e.lower() for e in rule.emails]:
        at = low.find(lit)
        if at >= 0:
            break
    if at < 0:
        for t in rule.topics:
            rx = _CAT_CMD.get(t) or _CAT_CODE.get(t)
            m = rx.search(flat) if rx else None
            if m:
                at = m.start()
                break
    if at < 0 or len(flat) <= span:
        return flat[:span] + ("…" if len(flat) > span else "")
    start = max(0, at - span // 3)
    end = min(len(flat), start + span)
    start = max(0, end - span)
    return ("…" if start else "") + flat[start:end].strip() + ("…" if end < len(flat) else "")
