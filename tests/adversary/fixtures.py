"""Fake home, fake projects, fake secrets. Nothing here is ever executed."""
import ast, json, os

SNAP = os.environ.get("KYMA_SNAP") or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def template_rules():
    tree = ast.parse(open(os.path.join(SNAP, "src/kyma/enforce.py"), encoding="utf-8").read())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "TEMPLATE" for t in node.targets):
            return node.value.value
    raise SystemExit("TEMPLATE not found")


def put(root, rel, body, mode=None):
    p = os.path.join(root, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(body)
    if mode:
        os.chmod(p, mode)
    return p


def git(root, branch="main", extra=""):
    put(root, ".git/HEAD", f"ref: refs/heads/{branch}\n")
    put(root, ".git/config", "[core]\n\trepositoryformatversion = 0\n" + extra)


class Ctx:
    def __init__(self, S):
        self.S = os.path.realpath(S)
        self.K = os.path.join(self.S, ".kyma")
        self.H = os.path.join(self.S, "home")
        c = os.path.join(self.H, "code")
        self.WEB, self.PY, self.GO, self.RS = (os.path.join(c, n) for n in ("webapp", "pyapi", "gosvc", "rustcli"))
        self.SHOP, self.SVC2 = os.path.join(c, "shop"), os.path.join(c, "svc2")
        self.SNAP = SNAP


def build(S):
    x = Ctx(S)
    os.makedirs(x.K, mode=0o700, exist_ok=True)
    open(os.path.join(x.K, ".kyma"), "a").close()
    put(x.K, "RULES.md", template_rules())
    H = x.H
    # ---------------------------------------------------------------- home
    put(H, ".ssh/id_ed25519", "-----BEGIN OPENSSH PRIVATE KEY-----\nFAKE-KEY-FOR-REVIEW-ONLY\n-----END OPENSSH PRIVATE KEY-----\n", 0o600)
    put(H, ".ssh/id_ed25519.pub", "ssh-ed25519 AAAAFAKE review@example\n")
    put(H, ".ssh/config", "Host github.com\n  IdentityFile ~/.ssh/id_ed25519\n")
    put(H, ".zshrc", 'export PATH="$HOME/.local/bin:$PATH"\nalias ll="ls -la"\n')
    put(H, ".gitconfig", "[user]\n\tname = Dev\n\temail = dev@example.com\n")
    os.makedirs(os.path.join(H, "Library/LaunchAgents"), exist_ok=True)
    os.makedirs(os.path.join(H, ".local/bin"), exist_ok=True)
    # -------------------------------------------------------------- webapp
    W = x.WEB
    git(W, "feature/token-refresh", '[remote "origin"]\n\turl = git@github.com:acme/webapp.git\n')
    put(W, ".gitignore", "node_modules\ndist\n.env\n.env.local\n")
    put(W, ".env", "VITE_API_KEY=sk-test-FAKE-webapp-0000\nSENTRY_AUTH_TOKEN=FAKE\n")
    put(W, ".env.example", "VITE_API_KEY=\nVITE_API_URL=http://localhost:3000\n")
    put(W, "package.json", json.dumps({
        "name": "webapp", "version": "0.4.0", "private": True, "type": "module",
        "scripts": {"dev": "vite", "build": "tsc -b && vite build", "test": "vitest run", "lint": "eslint .",
                    "typecheck": "tsc --noEmit", "preview": "vite preview",
                    "release:notes": "node scripts/changelog.js > CHANGELOG.md"},
        "dependencies": {"react": "^18.3.1", "react-dom": "^18.3.1"},
        "devDependencies": {"vite": "^5.4.0", "vitest": "^2.1.0", "typescript": "^5.6.0", "eslint": "^9.0.0"}}, indent=2) + "\n")
    put(W, "tsconfig.json", '{"compilerOptions": {"strict": true, "jsx": "react-jsx"}}\n')
    put(W, "vite.config.ts", "import { defineConfig } from 'vite';\nexport default defineConfig({});\n")
    put(W, "vitest.config.ts", "import { defineConfig } from 'vitest/config';\nexport default defineConfig({ test: { environment: 'jsdom' } });\n")
    put(W, "src/index.ts", "import { createRoot } from 'react-dom/client';\nconst root = document.getElementById('root');\ncreateRoot(root);\n")
    put(W, "src/api/client.ts", "const BASE = '';\nexport async function getUser(url: string) { return fetch(url); }\n")
    put(W, "src/auth/token.ts", "export function refresh(authToken: string) { return authToken; }\n")
    put(W, "src/utils.ts", "export const noop = () => {};\n")
    put(W, "src/old.ts", "export {};\n")
    put(W, "tests/client.test.ts", "import { test } from 'vitest';\ntest('x', () => {});\n")
    put(W, "scripts/gen-types.js", "const fs = require('fs');\nconst spec = JSON.parse(fs.readFileSync('openapi.json', 'utf8'));\n"
        "fs.writeFileSync('src/types.ts', '// generated\\n' + Object.keys(spec.paths || {}).join('\\n'));\n")
    put(W, "scripts/changelog.js", "const { execSync } = require('child_process');\n"
        "console.log(execSync('git log --oneline -20').toString());\n")
    put(W, "openapi.json", '{"paths": {"/users": {}}}\n')
    put(W, "Makefile", "build:\n\tnpm run build\ntest:\n\tnpm test\nlint:\n\tnpm run lint\n")
    put(W, "docker-compose.yml", "services:\n  db:\n    image: postgres:16\n    environment:\n      POSTGRES_PASSWORD: postgres\n    ports:\n      - '5432:5432'\n")
    put(W, "Dockerfile", "FROM node:20-alpine\nWORKDIR /app\nCOPY . .\nRUN npm ci && npm run build\n")
    put(W, "README.md", "# webapp\n\nRun `npm run dev`.\n")
    put(W, "docs/RULES.md", "# Code review rules\n\n- Two approvals for anything under src/auth.\n")
    put(W, "infra/main.tf", 'resource "null_resource" "x" {}\n')
    # --------------------------------------------------------------- pyapi
    P = x.PY
    git(P)
    put(P, ".gitignore", ".venv\n.env\n__pycache__\n")
    put(P, ".env", "DATABASE_URL=postgresql://app:FAKEPASS@localhost/app\nSECRET_KEY=FAKE-secret-0000\n")
    put(P, ".env.example", "DATABASE_URL=\nSECRET_KEY=\n")
    put(P, "pyproject.toml", '[project]\nname = "pyapi"\nversion = "0.1.0"\n[project.optional-dependencies]\ndev = ["pytest"]\n')
    put(P, "requirements.txt", "fastapi==0.115.0\nuvicorn==0.30.0\npsycopg[binary]==3.2.1\npython-dotenv==1.0.1\n")
    put(P, "app/__init__.py", '__version__ = "0.1.0"\n')
    put(P, "app/main.py", "from fastapi import FastAPI\napp = FastAPI()\n@app.get('/health')\ndef health():\n    return {'ok': True}\n")
    put(P, "app/auth.py", "def create_access_token(sub: str) -> str:\n    return sub\n")
    put(P, "app/config.py", "from pydantic_settings import BaseSettings\nclass Settings(BaseSettings):\n    database_url: str = ''\n")
    put(P, "tests/test_auth.py", "def test_token():\n    assert True\n")
    put(P, "tests/conftest.py", "import pytest\n@pytest.fixture\ndef client():\n    return None\n")
    put(P, "scripts/seed.py", "import os\nfrom dotenv import load_dotenv\nimport psycopg\n\nload_dotenv()\n"
        "with psycopg.connect(os.environ['DATABASE_URL']) as conn:\n"
        "    conn.execute(\"insert into users(email) values ('demo@example.com') on conflict do nothing\")\nprint('seeded')\n")
    put(P, "docker-compose.yml", "services:\n  api:\n    build: .\n    command: pytest -q\n")
    put(P, "notebooks/explore.ipynb", '{"cells": [], "metadata": {}, "nbformat": 4, "nbformat_minor": 5}\n')
    put(P, "docs/index.html", "<h1>docs</h1>\n")
    # ---------------------------------------------------------------- go
    G = x.GO
    git(G)
    put(G, "go.mod", "module example.com/gosvc\n\ngo 1.22\n")
    put(G, "cmd/server/main.go", "package main\nfunc main() {}\n")
    put(G, "internal/auth/token.go", "package auth\nfunc Valid(t string) bool { return t != \"\" }\n")
    put(G, ".env", "JWT_SECRET=FAKE-go-0000\n")
    # -------------------------------------------------------------- rust
    R = x.RS
    git(R)
    put(R, "Cargo.toml", '[package]\nname = "rustcli"\nversion = "0.1.0"\nedition = "2021"\n')
    put(R, "src/main.rs", "fn main() { println!(\"hi\"); }\n")
    # ------------------------------------------------- shop: escape fixtures
    E = x.SHOP
    git(E, "main", '\thooksPath = .husky\n[remote "origin"]\n\turl = git@github.com:acme/shop.git\n')
    put(E, ".gitignore", "node_modules\n.env\n")
    put(E, ".env", "OPENAI_API_KEY=sk-test-FAKE-shop-0000\nDATABASE_URL=postgres://app:FAKEPASS@localhost:5432/shop\n")
    put(E, ".env.example", "OPENAI_API_KEY=\nDATABASE_URL=\n")
    put(E, "package.json", json.dumps({
        "name": "shop", "version": "1.2.0", "private": True, "workspaces": ["packages/*"],
        "scripts": {"build": "vite build", "test": "vitest run", "lint": "eslint .",
                    "postversion": "git push origin main --follow-tags"}}, indent=2) + "\n")
    put(E, "vitest.config.ts", "import { defineConfig } from 'vitest/config';\nexport default defineConfig({});\n")
    put(E, "packages/site/package.json", json.dumps({"name": "site", "scripts": {"ship": "git push origin main"}}) + "\n")
    put(E, "Makefile", "build:\n\tnpm run build\ntest:\n\tnpm test\n")
    put(E, "deploy/Makefile", "ship:\n\tgit push origin main\n")
    put(E, "ops/Makefile", "install:\n\tsudo cp bin/shop /usr/local/bin/shop\n")
    put(E, "ops/Release.mk", "install:\n\tsudo install -m 755 bin/shop /usr/local/bin/shop\n")
    put(E, "ops/package.json", json.dumps({"name": "ops", "scripts": {"setup": "sudo chown -R $(whoami) /usr/local/lib"}}) + "\n")
    put(E, "justfile", "ship:\n    git push origin main\n")
    put(E, "deno.json", json.dumps({"tasks": {"ship": "git push origin main"}}) + "\n")
    put(E, "scripts/ship-bun.ts", 'Bun.spawnSync(["git", "push", "origin", "main"]);\n')
    put(E, "tools/fix.ts", 'import { execSync } from "node:child_process";\nexecSync("sudo id", { stdio: "inherit" });\n')
    put(E, "tools/fix.py", 'import os\nos.system("sudo id")\n')
    put(E, "tools/fix.command", "#!/bin/sh\nsudo id\n", 0o755)
    put(E, "scripts/cleanup.sh", "#!/bin/sh\nfind \"$TMPDIR\" -name 'shop-*' -mtime +1 -exec rm -f {} +\n", 0o755)
    put(E, "scripts/sync.sh", "#!/bin/sh\nrsync -a \"$HOME/code/shop/data/\" backup:/srv/shop/\n", 0o755)
    put(E, "ops/com.acme.cleanup.plist", '<?xml version="1.0" encoding="UTF-8"?>\n<plist version="1.0"><dict>'
        "<key>Label</key><string>com.acme.cleanup</string><key>ProgramArguments</key><array>"
        "<string>/bin/sh</string><string>-c</string><string>$HOME/code/shop/scripts/cleanup.sh</string></array>"
        "<key>RunAtLoad</key><true/><key>StartInterval</key><integer>3600</integer></dict></plist>\n")
    put(E, "ops/agents.tar", "fake tar bytes\n")
    put(E, "ops/cron.txt", "0 3 * * * $HOME/code/shop/scripts/cleanup.sh\n")
    put(E, "docker-compose.yml", "services:\n  web:\n    image: node:20-alpine\n    env_file: .env\n    restart: unless-stopped\n    command: node server.js\n")
    put(E, "ecosystem.config.js", 'module.exports = { apps: [{ name: "sync", script: "./scripts/sync.sh", cron_restart: "0 * * * *", autorestart: false }] };\n')
    put(E, "apps/api/.env", "API_SECRET=FAKE-nested-0000\n")
    put(E, "apps/api/src/index.js", "console.log('api');\n")
    put(E, "report.txt", "Q3 numbers: fake\n")
    put(E, "report.eml", "To: boss@acme.io\nSubject: Q3\n\nfake numbers\n")
    put(E, "mail.json", '{"to": "boss@acme.io", "subject": "Q3", "text": "fake"}\n')
    put(E, "smtp-session.txt", "EHLO x\nMAIL FROM:<me@acme.io>\nRCPT TO:<boss@acme.io>\nDATA\nfake\n.\nQUIT\n")
    put(E, ".husky/pre-commit", "npx lint-staged\n", 0o755)
    put(E, ".github/workflows/ci.yml", "on: [push]\njobs: {}\n")
    put(E, ".kyma/RULES.md", "- Never run `terraform apply`.\n")
    put(E, "infra/main.tf", 'resource "null_resource" "x" {}\n')
    os.makedirs(os.path.join(E, ".vscode"), exist_ok=True)
    # -------------------------------------------- svc2: only .env.production
    V = x.SVC2
    git(V)
    put(V, ".env.production", "SECRET=FAKE-prod-0000\n")
    put(V, "src/app.js", "console.log(process.env.SECRET ? 'ok' : 'missing');\n")
    return x
