"""Exercise the cited contract fixture through the real CLI and local shell."""
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("contract_rule", REPO / "examples" / "contract_rule.py")
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)


class ContractBridge(unittest.TestCase):
    def test_public_source_provenance(self):
        fixture = bridge.load_fixture()
        source = fixture["source"]
        self.assertEqual(source["url"], "https://bonterms.com/standard/ai-addendum-v2-signable-version")
        self.assertEqual(source["kit_commit"], "9138e0039f5e81b1dd3716a2b127927f2ba73c19")
        self.assertEqual(source["kit_path"], "standard-packs/originals/bonterms-ai-v2-signable.txt")
        self.assertEqual(source["sha256"], "e431231237bb0e9451925eafc3b6c74fd4a7da104dfab8531d3760a6717b5109")
        self.assertEqual(source["section"], "AI Features / New AI Features / (b) Opt-Out")
        self.assertEqual(source["license"], "CC BY 4.0")
        self.assertEqual(source["excerpt"], "(b) Opt-Out. Customer will have the ability to decline or disable any New AI Feature through administrative controls in the Cloud Service (or other reasonable measure made available by Provider) at the account, organization or equivalent administrator level.")
        self.assertFalse(fixture["review"]["real_customer_approval"])

    def test_fresh_copy_runs_without_git_or_dependencies(self):
        with tempfile.TemporaryDirectory(prefix="kyma-bridge-checkout-") as tmp:
            root = Path(tmp)
            clone = root / "fresh copy"
            clone.mkdir()
            for folder in ("src", "examples"):
                shutil.copytree(REPO / folder, clone / folder, ignore=shutil.ignore_patterns("__pycache__", "*.egg-info"))
            shutil.copyfile(REPO / "kyma", clone / "kyma")
            output = root / "receipt with spaces"
            proc = subprocess.run([sys.executable, "-I", str(clone / "examples" / "contract_rule.py"),
                                   "--output", str(output), "--json"],
                                  cwd=root, capture_output=True, text=True, timeout=60,
                                  env={"PATH": "/usr/bin:/bin"})
            self.assertEqual(proc.returncode, 0, proc.stderr)
            result = json.loads(proc.stdout)
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(json.loads((output / "receipt.json").read_text()), result)
            rows = result["attempts"]
            self.assertEqual([r["verdict"] for r in rows], ["allow", "ask", "allow", "ask"])
            self.assertEqual([r["executed"] for r in rows], [True, False, True, False])
            self.assertEqual([r["check_exit"] for r in rows], [0, 1, 0, 1])
            self.assertEqual(Path(rows[0]["output"]).read_text(), "Acme fixture summary\n")
            self.assertFalse(Path(rows[1]["output"]).exists())
            self.assertEqual(Path(rows[2]["output"]).read_text(), "Beta fixture report\n")
            self.assertFalse(Path(rows[3]["output"]).exists())
            self.assertEqual(rows[3]["declared_customer"], "Beta")
            self.assertEqual(rows[3]["customer"], "Acme")
            for row in (rows[0], rows[1], rows[3]):
                self.assertIn(result["source"]["url"], row["runtime_reason"])
                self.assertIn(result["source"]["id"], row["runtime_reason"])
            self.assertIn("version 2", rows[1]["runtime_reason"])
            self.assertIn("fixture-beta-independent-permission", rows[2]["runtime_reason"])
            self.assertNotIn(result["source"]["url"], rows[2]["runtime_reason"])
            for item in result["compiled_grant"] + result["compiled_withdrawal"]:
                self.assertEqual(item["topics"], ["write"])
                self.assertTrue(item["enforced"])
                self.assertEqual(len(item["paths"]), 1)
                self.assertTrue(Path(item["paths"][0]).is_absolute())
                self.assertTrue(Path(item["paths"][0]).is_relative_to((output / "workspace").resolve()))

    def copied_fixture(self, root):
        for path in bridge.FIXTURE.parent.iterdir():
            shutil.copyfile(path, root / path.name)
        return root / bridge.FIXTURE.name

    def test_source_tamper_is_rejected_before_execution(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = self.copied_fixture(root)
            source = root / "bonterms-ai-v2-signable.txt"
            source.write_text(source.read_text() + "changed\n")
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                bridge.run(root / "output", fixture)
            self.assertFalse((root / "output").exists())

    def test_missing_excerpt_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = self.copied_fixture(root)
            fixture = json.loads(path.read_text())
            fixture["source"]["excerpt"] = "An invented grant of all AI rights."
            path.write_text(json.dumps(fixture))
            with self.assertRaisesRegex(ValueError, "excerpt is absent"):
                bridge.run(root / "output", path)
            self.assertFalse((root / "output").exists())

    def test_customer_path_escape_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = self.copied_fixture(root)
            fixture = json.loads(path.read_text())
            fixture["scopes"][0]["relative_path"] = "../outside"
            path.write_text(json.dumps(fixture))
            with self.assertRaisesRegex(ValueError, "inside the fixture"):
                bridge.run(root / "output", path)
            self.assertFalse((root / "output").exists())

    def test_data_purpose_rule_cannot_replace_path_mapping(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = self.copied_fixture(root)
            fixture = json.loads(path.read_text())
            fixture["scopes"][0]["grant_template"] = "My agent may train on customer tickets."
            path.write_text(json.dumps(fixture))
            with self.assertRaisesRegex(ValueError, "Unsupported rule"):
                bridge.run(root / "output", path)
            self.assertEqual(list((root / "output" / "workspace").rglob("*.txt")), [])

    def test_existing_output_is_not_reused(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FileExistsError):
                bridge.run(tmp)


if __name__ == "__main__":
    unittest.main()
