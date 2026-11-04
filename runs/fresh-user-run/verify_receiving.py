"""Verify the real receiver and run isolated, effect-free OpenFeature tests."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sqlite3

WORK = Path(__file__).resolve().parent
TOOL = WORK.parents[1] / '.venv/lib/python3.13/site-packages/kyma_local/tool.py'
spec = importlib.util.spec_from_file_location('supplied_kyma_tool', TOOL)
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)


def load(name):
    return json.loads((WORK / name).read_text())


bundle = load('model-decisions.json')
export = load('openfeature-rules.json')
receipt = load('consumer-receipt.json')
validation = load('validated-source-evidence.json')
feature = load('feature.json')
manifest = load('source-manifest.json')
digest = hashlib.sha256(tool.canonical(bundle)).hexdigest()
assert digest == receipt['bundle_sha256'] == export['bundle_sha256'] == validation['bundle_sha256']
with sqlite3.connect(f'file:{WORK / "local-results.sqlite3"}?mode=ro', uri=True) as db:
    rows = db.execute('SELECT bundle_hash, body FROM results ORDER BY bundle_hash').fetchall()
    matching = [json.loads(body) for identity, body in rows if identity == digest]
assert len(matching) == 1
received = matching[0]
assert received['bundle'] == bundle
assert received['export'] == export
assert export['rules'] == bundle['controls']
assert len(rows) == 1, 'This invocation must have one final receiver result.'
assert load('model-receiving-readback.json')['results'] == [received]
assert load('readback-tool-result.json')['results'] == [received]

expected_pairs = {(c['id'], op['id']) for c in manifest['customers'] for op in feature['operations']}
assert {(d['customer_id'], d['operation_id']) for d in bundle['decisions']} == expected_pairs
assert {(c['customer_id'], c['operation_id']) for c in bundle['controls']} == expected_pairs
assert len(bundle['decisions']) == len(bundle['controls']) == 6
assert not any(c['proposed_eligible'] for c in bundle['controls'])
assert all(e['page'] is None for e in bundle['evidence'])
assert {e['document_id'] for e in bundle['evidence']} == {
    d['id'] for c in manifest['customers'] for d in c['documents']}
assert all(len(e['quote']) == e['end'] - e['start'] for e in validation['resolved_evidence'])
ops = {op['id']: op for op in feature['operations']}
for c in bundle['controls']:
    proposal = ops[c['operation_id']]
    for key, value in proposal['proposed_facts'].items():
        assert tool.json_literals_equal(c['required_facts'][key], value)
    for key in ['purpose', 'model', 'training', 'retention']:
        assert c['required_facts'][key] == proposal[key]

# The real export stays unchanged. These contexts exercise its six denials.
actual_contexts = []
for c in export['rules']:
    actual_contexts.append(dict(customer_id=c['customer_id'], operation_id=c['operation_id'], facts=c['required_facts']))
actual_results = tool.evaluate_sdk(export, actual_contexts)
assert len(actual_results) == 6 and all(r['value'] is False and r['error_code'] is None for r in actual_results)
compiler_results = load('openfeature-consumer.json')['evaluations']
assert len(compiler_results) == 18
assert all(r['value'] is False and r['error_code'] is None for r in compiler_results)

# Positive fixtures test mechanics, never customer permission. They never enter SQLite.
fixture = copy.deepcopy(export)
fixture['scope'] = 'Synthetic effect-free fact-matcher test. No customer contract or clearance.'
fixture['rules'] = []
contexts = []
expected_values = []


def context(rule, facts, expected, customer=None):
    contexts.append(dict(customer_id=customer or rule['customer_id'],
                         operation_id=rule['operation_id'], facts=facts))
    expected_values.append(expected)


for index, original in enumerate(export['rules']):
    rule = copy.deepcopy(original)
    rule['customer_id'] = f'synthetic-contract-fixture-{index}'
    rule['decision_id'] = f'SYNTHETIC-{index}'
    rule['proposed_eligible'] = True
    fixture['rules'].append(rule)
    facts = rule['required_facts']
    context(rule, dict(facts), True)
    context(rule, {}, False)
    context(rule, dict(facts), False, customer='synthetic-unknown-customer')
    for key, value in facts.items():
        missing = dict(facts)
        del missing[key]
        context(rule, missing, False)
        changed = dict(facts)
        changed[key] = not value if type(value) is bool else value + ' [different]'
        context(rule, changed, False)
        wrong_type = dict(facts)
        wrong_type[key] = int(value) if type(value) is bool else None
        context(rule, wrong_type, False)

fixture_results = tool.evaluate_sdk(fixture, contexts)
assert len(fixture_results) == len(expected_values)
for row, expected in zip(fixture_results, expected_values):
    assert row['value'] is expected and row['error_code'] is None

# Test whole-operation eligibility separately from literal fact equality.
disabled_fixture = copy.deepcopy(fixture)
disabled_fixture['rules'][0]['proposed_eligible'] = False
eligibility_results = tool.evaluate_sdk(disabled_fixture, [contexts[0]])
assert eligibility_results[0]['value'] is False
assert load('openfeature-rules.json') == export
with sqlite3.connect(f'file:{WORK / "local-results.sqlite3"}?mode=ro', uri=True) as db:
    after = db.execute('SELECT bundle_hash, body FROM results ORDER BY bundle_hash').fetchall()
assert after == rows

result = dict(
    bundle_sha256=digest,
    direct_sqlite_read=True,
    receiver_rows=len(rows),
    exact_bundle_equal=True,
    exact_export_equal=True,
    tool_readback_equal=True,
    all_customer_operation_pairs_verified=True,
    source_documents_covered=4,
    exact_source_quotes=67,
    compiler_actual_sdk_evaluations=len(compiler_results),
    direct_actual_sdk_evaluations=len(actual_results),
    actual_eligible_controls=0,
    actual_denied_complete_contexts=6,
    synthetic_sdk_evaluations=len(fixture_results) + len(eligibility_results),
    synthetic_positive_matches=sum(expected_values),
    synthetic_negative_matches=len(expected_values) - sum(expected_values) + 1,
    synthetic_fixtures_saved_to_receiver=False,
    export_unchanged_after_tests=True,
    opa_executable_available=shutil.which('opa') is not None,
    opa_runtime_tested=False,
    verification_scope='Exact local provenance, pair coverage, typed SDK rules and durable receiving content. No legal correctness, live authority or deployment claim.',
    outside_use=False,
    customer_accounts_changed=False,
)
(WORK / 'receiving-verification.json').write_text(json.dumps(result, indent=2) + '\n')
(WORK / 'sdk-regression-details.json').write_text(json.dumps(dict(
    actual=actual_results, synthetic=fixture_results,
    disabled_eligibility=eligibility_results), ensure_ascii=False, indent=2) + '\n')
print(json.dumps(result, indent=2))
