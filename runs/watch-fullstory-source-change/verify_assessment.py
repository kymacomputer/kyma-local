"""Exercise the actual local consumer and isolated synthetic regression cases.

No synthetic eligible rule is persisted in the assessment receiver or export.
"""
import copy
import difflib
import hashlib
import json
from pathlib import Path
import sqlite3

from kyma_local.tool import canonical, evaluate_sdk

WORK = Path(__file__).resolve().parent


def load(name):
    return json.loads((WORK / name).read_text())


def run():
    checks = []

    def check(name, predicate):
        assert predicate, name
        checks.append({"check": name, "passed": True})

    bundle, export = load("model-decisions.json"), load("openfeature-rules.json")
    manifest, feature = load("source-manifest.json"), load("feature.json")
    context = load("revision-context.json")
    comparison = load("source-comparison.json")
    bundle_hash = hashlib.sha256(canonical(bundle)).hexdigest()
    protected = {name: hashlib.sha256((WORK / name).read_bytes()).hexdigest()
                 for name in ("source-manifest.json", "feature.json", "input-diff.json", "revision-context.json",
                              "model-decisions.json", "openfeature-rules.json", "local-results.sqlite3")}
    documents = {d["id"]: d for key in ("customers", "reference_sets", "historical_reference_sets")
                 for group in manifest.get(key, []) for d in group["documents"]}
    for d in documents.values():
        check("source_hash:" + d["id"], hashlib.sha256((WORK / d["text_file"]).read_bytes()).hexdigest() == d["text_sha256"])
    check("exact_population", len(bundle["decisions"]) == len(bundle["controls"]) == 6)
    check("only_actual_customers", {d["customer_id"] for d in bundle["decisions"]} == {"c3-bhge", "sai-esds"})
    old_status = {(d["customer_id"], d["operation_id"]): d["status"] for d in context["previous_actual_assessment"]["decisions"]}
    check("unchanged_statuses", all(old_status[(d["customer_id"], d["operation_id"])] == d["status"] for d in bundle["decisions"]))
    operations = {op["id"]: op for op in feature["operations"]}
    for rule in bundle["controls"]:
        op = operations[rule["operation_id"]]
        check("disabled:" + rule["decision_id"], rule["proposed_eligible"] is False)
        for k, v in op["proposed_facts"].items():
            check("literal_fact:" + rule["decision_id"] + ":" + k, canonical(rule["required_facts"][k]) == canonical(v))
        for k in ("actor", "purpose", "data_access", "model", "training", "retention", "regions"):
            check("preserved_feature:" + rule["decision_id"] + ":" + k, canonical(rule["required_facts"][k]) == canonical(op[k]))
        check("preserved_data:" + rule["decision_id"], rule["required_facts"]["data_categories"] == feature["data"])
    check("export_matches_authored_controls", export["rules"] == bundle["controls"])
    check("export_hash_matches", export["bundle_sha256"] == bundle_hash)
    with sqlite3.connect("file:" + str(WORK / "local-results.sqlite3") + "?mode=ro", uri=True) as db:
        rows = db.execute("SELECT bundle_hash, body FROM results").fetchall()
        check("one_actual_result", len(rows) == 1)
        received = json.loads(rows[0][1])
        check("sqlite_exact_bundle", canonical(received["bundle"]) == canonical(bundle))
        check("sqlite_exact_export", canonical(received["export"]) == canonical(export))
        check("sqlite_exact_key", rows[0][0] == bundle_hash)
    tool_read = load("model-receiving-readback.json")
    check("tool_receiver_exact", tool_read["results"] == [received])
    check("stdout_receiver_exact", load("receiver-tool-result.json") == tool_read)
    native = load("openfeature-consumer.json")
    check("actual_sdk_used", native["actual_sdk_evaluation"] is True)
    check("18_actual_evaluations", len(native["evaluations"]) == 18)
    check("all_actual_values_false", all(r["value"] is False and r["error_code"] is None for r in native["evaluations"]))

    before_id, after_id = comparison["before"]["document_id"], comparison["after"]["document_id"]
    before, after = [(WORK / documents[i]["text_file"]).read_text() for i in (before_id, after_id)]
    diff = "\n".join(difflib.unified_diff(before.splitlines(), after.splitlines(),
                         fromfile="before/fullstory/subprocessor-list.html", tofile="after/fullstory/subprocessor-list.html", n=6))
    check("complete_diff_equals_input_change", diff == context["input_changes"][0]["complete_observed_text_diff"] == comparison["complete_observed_text_diff"])
    check("printed_date_unchanged", comparison["before_displayed_date"] == comparison["after_displayed_date"] == "Last Updated: June 2, 2026")
    check("original_hash_changed", comparison["before"]["original_sha256"] != comparison["after"]["original_sha256"])
    check("text_hash_changed", comparison["before"]["text_sha256"] != comparison["after"]["text_sha256"])
    check("seven_rows_each", len(comparison["before"]["rows"]) == len(comparison["after"]["rows"]) == 7)
    check("only_google_purpose_changed", len(comparison["supplier_row_changes"]) == 1
          and comparison["supplier_row_changes"][0]["entity"] == "Google LLC"
          and comparison["supplier_row_changes"][0]["changed_fields"] == ["purpose"])
    check("all_other_supplier_rows_unchanged", len(comparison["unchanged_supplier_rows"]) == 6)
    phrase = "AI model inference for in-product AI features"
    check("purpose_addition_not_training", phrase not in comparison["before"]["rows"]["Google LLC"]["purpose"]
          and phrase in comparison["after"]["rows"]["Google LLC"]["purpose"]
          and "training" not in comparison["after"]["rows"]["Google LLC"]["purpose"].lower())
    check("location_and_data_unchanged", all(comparison["before"]["rows"]["Google LLC"][k] == comparison["after"]["rows"]["Google LLC"][k]
                                            for k in ("location", "processed_data")))
    check("openai_location_absent_not_inferred", comparison["before"]["rows"]["OpenAI (optional)"]["location"] is None
          and comparison["after"]["rows"]["OpenAI (optional)"]["location"] is None)
    def table_text(t):
        return t.split("ENTITY NAME\nPURPOSE OF PROCESSING\nPROCESSED DATA\nLOCATION\n", 1)[1].split("\nFollow us", 1)[0]
    navigation_only = after.replace("Platform Overview", "SYNTHETIC NAVIGATION TEST", 1)
    check("navigation_noise_does_not_change_supplier_table", navigation_only != after and table_text(navigation_only) == table_text(after))
    check("no_customer_engagement_inferred", set(comparison["engagement_by_customer"].values()) == {"not_established"})
    check("revision_effect_not_permission", bundle["revision_impacts"][0]["engagement_state"] == "not_established")

    # Positive controls avoid an all-disabled export's vacuous success.
    synthetic = copy.deepcopy(export)
    rule = copy.deepcopy(export["rules"][0])
    rule.update({"customer_id": "synthetic-regression-only", "proposed_eligible": True})
    synthetic["rules"] = [rule]
    full = copy.deepcopy(rule["required_facts"])
    cases = [("complete_positive", "synthetic-regression-only", full, True)]
    for key in full:
        facts = copy.deepcopy(full)
        del facts[key]
        cases.append(("missing_" + key, rule["customer_id"], facts, False))
    mutations = {
      "different_actor": {"actor_role": "service_provider"},
      "different_purpose": {"purpose": "Improve the provider's shared support model for use across its customer base."},
      "provider_access": {"provider_content_access": True},
      "external_google_content_recipient": {"external_content_transfer": True, "model": "Google inference through Fullstory"},
      "training": {"provider_training": True},
      "region": {"processing_region": "United States"},
      "boolean_as_zero": {"external_content_transfer": 0},
      "boolean_as_string": {"provider_content_access": "false"},
      "boolean_as_null": {"provider_training": None},
      "different_retention": {"retention": "Raw examples retained for 30 days."},
      "region_list_as_string": {"regions": "Australia"},
      "extra_region": {"regions": ["Australia", "Germany"]},
      "different_dataset": {"data_categories": ["Other customer content"]}
    }
    for label, change in mutations.items():
        facts = copy.deepcopy(full)
        facts.update(change)
        cases.append((label, rule["customer_id"], facts, False))
    cases.append(("wrong_customer", "unknown-customer", copy.deepcopy(full), False))
    requests = [{"customer_id": customer, "operation_id": rule["operation_id"], "facts": facts}
                for _, customer, facts, _ in cases]
    sdk_results = evaluate_sdk(synthetic, requests)
    for (label, _, _, expected), result in zip(cases, sdk_results):
        check("isolated_sdk:" + label, result["value"] is expected and result["error_code"] is None)
    for name, old_hash in protected.items():
        check("no_test_mutation:" + name, hashlib.sha256((WORK / name).read_bytes()).hexdigest() == old_hash)
    report = {"passed": True, "bundle_sha256": bundle_hash, "checks": checks,
              "check_count": len(checks), "actual_customer_sdk_evaluations": 18,
              "isolated_synthetic_sdk_evaluations": len(cases), "synthetic_sdk_results": sdk_results,
              "synthetic_rules_saved_to_receiver": False,
              "limits": "Tests verify source identity, declared impact, typed SDK matching and exact local receipt. They do not prove legal interpretation, live isolation or actual engagement."}
    (WORK / "verification-report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({k: report[k] for k in ("passed", "bundle_sha256", "check_count", "actual_customer_sdk_evaluations", "isolated_synthetic_sdk_evaluations")}))


if __name__ == "__main__":
    run()
