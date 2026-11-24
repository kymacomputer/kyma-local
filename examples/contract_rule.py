#!/usr/bin/env python3
"""Run the public clause -> reviewed fixture -> actual local command bridge.

The review record is fictional test data. No contract reader or customer
authorization is simulated as a real event. Only the local commands are real.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile

REPO = Path(__file__).resolve().parents[1]
FIXTURE = Path(__file__).with_name("fixtures") / "contract-rule.json"
COMPILE = """import json, runpy, sys
runpy.run_path(sys.argv[1], run_name='contract_bridge_loader')
from kyma import rules
payload = json.load(sys.stdin)
items = rules.parse(payload['text'], source='RULES.md', base=payload['base'])
print(json.dumps([{'text': r.text, 'enforced': r.enforced, 'problem': r.problem,
                  'topics': r.topics, 'paths': r.paths, 'cite': r.cite,
                  'cite_problem': r.cite_problem} for r in items]))
"""


def require(condition, message):
    if not condition:
        raise ValueError(message)


def load_fixture(path=FIXTURE):
    path = Path(path)
    fixture = json.loads(path.read_text(encoding="utf-8"))
    require(fixture.get("schema") == "kyma-contract-bridge-fixture/v1", "Unknown fixture schema")
    source = fixture["source"]
    snapshot = Path(source["snapshot"])
    require(snapshot.name == str(snapshot), "Source snapshot must be a sibling file")
    data = (path.parent / snapshot).read_bytes()
    require(hashlib.sha256(data).hexdigest() == source["sha256"], "Source snapshot hash mismatch")
    require(source["excerpt"] in data.decode("utf-8"), "Source excerpt is absent from the pinned document")
    require(fixture["review"]["real_customer_approval"] is False, "This example cannot attest to actual customer approval")
    require([s["customer"] for s in fixture["scopes"]] == ["Acme", "Beta"], "Expected Acme and Beta fixture scopes")
    for scope in fixture["scopes"]:
        relative = Path(scope["relative_path"])
        require(not relative.is_absolute() and ".." not in relative.parts,
                "Customer scope must stay inside the fixture workspace")
        require(relative.parts[:2] == ("customers", scope["customer"].lower()), "Customer path binding mismatch")
    return fixture


def environment(box):
    return {"HOME": str(box / "home"), "KYMA_HOME": str(box / "home" / ".kyma"),
            "KYMA_ALLOW_TEMP_HOME": "1", "KYMA_NO_KEYCHAIN": "1", "PATH": "/usr/bin:/bin",
            "PYTHONDONTWRITEBYTECODE": "1", "NO_COLOR": "1"}


def rule_text(fixture, revoked=False):
    lines = []
    for scope in fixture["scopes"]:
        acme = scope["customer"] == "Acme"
        source = (fixture["source"]["id"] + " | " + fixture["source"]["url"]
                  if acme else scope["source_id"])
        source += " | " + scope["grant_id"]
        version = "2" if acme and revoked else "1"
        citation = (f" (source: {source}; approved: {fixture['review']['approved_by']}; version: {version})")
        # HOME is the isolated home/. Expand it to an absolute customer path.
        # A bare relative rule would instead match a path suffix anywhere.
        path = "`~/../workspace/" + scope["relative_path"] + "`"
        lines.append("- " + scope["hold_template"].format(path=path) + citation)
        if not (revoked and acme):
            lines.append("- " + scope["grant_template"].format(path=path) + citation)
    return "\n".join(lines) + "\n"


def install_fixture_rules(box, fixture, revoked=False):
    text = rule_text(fixture, revoked)
    rules_file = box / "home" / ".kyma" / "RULES.md"
    compiled = subprocess.run(
        [sys.executable, "-I", "-c", COMPILE, str(REPO / "kyma")],
        input=json.dumps({"text": text, "base": str(rules_file.parent)}),
        cwd=box / "workspace", env=environment(box), capture_output=True, text=True, check=True,
    )
    items = json.loads(compiled.stdout)
    require(len(items) == (3 if revoked else 4), "Unexpected rule count")
    for item in items:
        require(item["enforced"] and not item["cite_problem"], "Unsupported rule: " + str(item))
        require(item["topics"] == ["write"] and len(item["paths"]) == 1,
                "The fixture must compile only to one write action and one local path")
    rules_file.write_text(text, encoding="utf-8")
    (box / ("rules-withdrawn.md" if revoked else "rules-granted.md")).write_text(text, encoding="utf-8")
    return items


def attempt(box, stage, customer, output, content, declared_customer=None):
    command = "printf '%s\\n' " + shlex.quote(content) + " > " + shlex.quote(str(output))
    payload = {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(box / "workspace")}
    if declared_customer:
        payload["customer"] = declared_customer  # Deliberately untrusted context, not a policy predicate.
    check = subprocess.run(
        [sys.executable, "-I", str(REPO / "kyma"), "check", "--json"],
        input=json.dumps(payload), cwd=box / "workspace", env=environment(box),
        capture_output=True, text=True, check=False,
    )
    require(check.returncode in (0, 1, 2), "Runtime check failed: " + check.stderr)
    verdict = {0: "allow", 1: "ask", 2: "block"}[check.returncode]
    require(check.stdout.startswith(verdict + "  "), "Runtime exit and decision disagree")
    executed = False
    if verdict == "allow":
        subprocess.run(["/bin/sh", "-c", command], cwd=box / "workspace",
                       env=environment(box), capture_output=True, text=True, check=True)
        executed = True
    return {"stage": stage, "customer": customer, "declared_customer": declared_customer,
            "command": command, "check_exit": check.returncode, "verdict": verdict,
            "runtime_reason": check.stdout.strip(), "executed": executed,
            "output": str(output), "exists": output.exists(),
            "content": output.read_text(encoding="utf-8") if output.exists() else None}


def run(output=None, fixture_path=FIXTURE):
    fixture = load_fixture(fixture_path)
    if output:
        box = Path(output).absolute()
        box.mkdir(mode=0o700)  # Refuse reuse. A prior output must not become proof for this run.
    else:
        box = Path(tempfile.mkdtemp(prefix="kyma-contract-bridge-"))
    (box / "home" / ".kyma").mkdir(parents=True)
    workspace = box / "workspace"
    for scope in fixture["scopes"]:
        (workspace / scope["relative_path"]).mkdir(parents=True)
    acme = workspace / fixture["scopes"][0]["relative_path"]
    beta = workspace / fixture["scopes"][1]["relative_path"]
    granted = install_fixture_rules(box, fixture)
    before = attempt(box, "grant", "Acme", acme / "before.txt", "Acme fixture summary")
    require(before["verdict"] == "allow" and before["content"] == "Acme fixture summary\n",
            "Acme grant did not produce the actual output")
    withdrawn = install_fixture_rules(box, fixture, revoked=True)
    after = attempt(box, "withdraw", "Acme", acme / "after.txt", "Acme must not create this")
    require(after["verdict"] == "ask" and not after["executed"] and not after["exists"],
            "Acme withdrawal did not hold the next actual command")
    unaffected = attempt(box, "independent-grant", "Beta", beta / "report.txt", "Beta fixture report")
    require(unaffected["verdict"] == "allow" and unaffected["content"] == "Beta fixture report\n",
            "Acme withdrawal changed Beta's independent permission")
    mislabeled = attempt(box, "metadata-is-not-authority", "Acme", acme / "mislabeled.txt",
                         "Acme must not create this either", declared_customer="Beta")
    require(mislabeled["verdict"] == "ask" and not mislabeled["exists"],
            "A caller's customer label changed the actual path rule")
    source = fixture["source"]
    for row in (before, after, mislabeled):
        require(source["id"] in row["runtime_reason"] and source["url"] in row["runtime_reason"],
                "Runtime lost the exact source citation")
        require(fixture["review"]["approved_by"] in row["runtime_reason"], "Runtime lost the fixture review label")
    require("version 2" in after["runtime_reason"], "Withdrawal did not carry its new version")
    require(fixture["scopes"][1]["grant_id"] in unaffected["runtime_reason"], "Beta lost its independent grant citation")
    require((acme / "before.txt").read_text() == "Acme fixture summary\n", "Withdrawal changed an earlier result")
    receipt = {"schema": "kyma-contract-bridge-receipt/v1", "status": "PASS", "directory": str(box),
               "source": source, "review": fixture["review"], "compiled_grant": granted,
               "compiled_withdrawal": withdrawn, "attempts": [before, after, unaffected, mislabeled],
               "boundary": "A fictional review maps a public clause to known local write paths. No arbitrary purpose or customer semantics are inferred. No actual customer approval or demand is proved."}
    (box / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", help="A new directory for isolated state, outputs and receipt")
    parser.add_argument("--json", action="store_true", help="Print the complete receipt")
    args = parser.parse_args()
    try:
        result = run(args.output)
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        print("contract bridge: FAIL: " + str(exc), file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print("Acme grant: allow. The local summary file exists.")
        print("Acme withdrawal: ask. The next command did not execute. Its output is absent.")
        print("Beta independent grant: allow. The unrelated report file exists.")
        print("A false Beta label on Acme's command: ask. The output is absent.")
        print("Review identity and customer permissions are fictional fixture data.")
        print("Receipt: " + result["directory"] + "/receipt.json")
        print("contract bridge: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
