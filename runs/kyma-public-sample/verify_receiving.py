"""Verify this exact local assessment at the actual receiving boundary."""
import importlib.util
import json
import sqlite3
from collections import Counter
from hashlib import sha256
from pathlib import Path

WORK = Path(__file__).resolve().parent
KIT = WORK.parent.parent


def read(name):
    return json.loads((WORK / name).read_text())


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()


bundle = read('model-decisions.json')
export = read('openfeature-rules.json')
bundle_hash = sha256(canonical(bundle)).hexdigest()
assert export['bundle_sha256'] == bundle_hash
assert export['rules'] == bundle['controls']
assert len(bundle['decisions']) == len(bundle['controls']) == 6
decision_pairs = Counter((row['customer_id'], row['operation_id']) for row in bundle['decisions'])
control_pairs = Counter((row['customer_id'], row['operation_id']) for row in bundle['controls'])
assert decision_pairs == control_pairs and set(decision_pairs.values()) == {1}
assert all(not control['proposed_eligible'] for control in bundle['controls'])
assert len({item['id'] for item in bundle['unknowns']}) == len(bundle['unknowns'])
assert len({item['id'] for item in bundle['engineering_outputs']}) == len(bundle['engineering_outputs'])

with sqlite3.connect('file:' + str(WORK / 'local-results.sqlite3') + '?mode=ro', uri=True) as db:
    rows = db.execute('SELECT bundle_hash, body FROM results ORDER BY bundle_hash').fetchall()
received = [json.loads(body) for key, body in rows if key == bundle_hash]
assert len(received) == 1
assert received[0]['bundle'] == bundle
assert received[0]['export'] == export
readback = read('model-receiving-readback.json')
assert readback['results'] == [json.loads(body) for key, body in rows]
assert read('readback-command-result.json') == readback
assert read('validation-result.json')['bundle_sha256'] == bundle_hash
assert read('validated-source-evidence.json')['bundle_sha256'] == bundle_hash
assert read('opa-data.json')['kyma_feature_rules'] == export

manifest = read('source-manifest.json')
source_checks = []
for customer in manifest['customers']:
    for document in customer['documents']:
        acquired = (WORK / document['text_file']).read_bytes()
        original = Path(manifest['input_root']) / document['original_relative_path']
        assert sha256(acquired).hexdigest() == document['text_sha256']
        assert sha256(original.read_bytes()).hexdigest() == document['original_sha256']
        source_checks.append({'document_id': document['id'], 'original_and_text_hash_match': True})

spec = importlib.util.spec_from_file_location('unchanged_kyma_tool', KIT / 'src/kyma_local/tool.py')
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)
contexts = []
for rule in export['rules']:
    customer, operation, facts = rule['customer_id'], rule['operation_id'], rule['required_facts']
    contexts.append(dict(customer_id=customer, operation_id=operation, facts=dict(facts), probe='exact_proposal'))
    contexts.append(dict(customer_id='unknown-customer', operation_id=operation, facts=dict(facts), probe='unknown_customer'))
    contexts.append(dict(customer_id=customer, operation_id=operation, facts={}, probe='empty_facts'))
    for key, value in facts.items():
        missing = {k: v for k, v in facts.items() if k != key}
        contexts.append(dict(customer_id=customer, operation_id=operation, facts=missing, probe='missing:' + key))
        wrong = dict(facts)
        wrong[key] = not value if type(value) is bool else 'different-literal'
        contexts.append(dict(customer_id=customer, operation_id=operation, facts=wrong, probe='wrong:' + key))
    confused = dict(facts)
    confused['actor_role'] = 'service_provider' if facts['actor_role'] == 'customer' else 'customer'
    confused['provider_content_access'] = not facts['provider_content_access']
    contexts.append(dict(customer_id=customer, operation_id=operation, facts=confused, probe='actor_access_confusion'))
evaluations = tool.evaluate_sdk(export, contexts)
assert all(row['value'] is False and row['error_code'] is None for row in evaluations)
native = read('openfeature-consumer.json')
assert native['actual_sdk_evaluation'] is True
assert len(native['evaluations']) == 18
assert all(row['value'] is False and row['error_code'] is None for row in native['evaluations'])
supplemental = {
    'actual_sdk_evaluation': True,
    'sdk': native['sdk'],
    'bundle_sha256': bundle_hash,
    'scope': 'Disabled-state negative checks only. These do not test a future enabled rule or prove legal interpretation.',
    'evaluations': evaluations,
}
(WORK / 'supplemental-openfeature-checks.json').write_text(json.dumps(supplemental, indent=2) + '\n')
receipt = {
    'bundle_sha256': bundle_hash,
    'sqlite_rows': len(rows),
    'current_bundle_rows': len(received),
    'receiver_bundle_exact': True,
    'receiver_export_exact': True,
    'tool_readback_matches_sqlite': True,
    'exact_customer_operation_pairs': 6,
    'verified_quotes': len(read('validated-source-evidence.json')['resolved_evidence']),
    'source_checks': source_checks,
    'native_sdk_evaluations': len(native['evaluations']),
    'supplemental_sdk_evaluations': len(evaluations),
    'all_evaluations_false_without_errors': True,
    'proposed_eligible_count': 0,
    'outside_use': False,
    'customer_accounts_changed': False,
    'limits': [
        'Exact quotation verifies provenance, not contract interpretation.',
        'No customer-specific applicability, missing contract, site or commencement fact is inferred.',
        'All controls are false. These checks do not test an enabled deployment or type-strict equality in future eligible rules.',
        'The OPA files match the export. No OPA runtime evaluation was performed.',
        'No actual model, customer infrastructure, data deletion or external feature service was exercised.',
    ],
}
(WORK / 'receiving-comparison.json').write_text(json.dumps(receipt, indent=2) + '\n')
print(json.dumps(receipt))
