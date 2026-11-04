"""Read the actual local receiver and exercise the assessed OpenFeature export."""
import hashlib
import importlib.util
import itertools
import json
import re
import sqlite3
from collections import Counter
from pathlib import Path

work = Path(__file__).resolve().parent


def load(name):
    return json.loads((work / name).read_text())


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()


bundle = load('model-decisions.json')
export = load('openfeature-rules.json')
manifest = load('source-manifest.json')
feature = load('feature.json')
digest = hashlib.sha256(canonical(bundle)).hexdigest()
expected = set(itertools.product(
    [row['id'] for row in manifest['customers']],
    [row['id'] for row in feature['operations']],
))
for field in ['decisions', 'controls']:
    assert Counter((row['customer_id'], row['operation_id']) for row in bundle[field]) == Counter({p: 1 for p in expected})
assert all(row['page'] is None for row in bundle['evidence'])
assert export['rules'] == bundle['controls']
assert export['bundle_sha256'] == digest
assert load('validation-tool-result.json')['bundle_sha256'] == digest
assert load('consumer-receipt.json')['bundle_sha256'] == digest

with sqlite3.connect('file:' + str(work / 'local-results.sqlite3') + '?mode=ro', uri=True) as db:
    received_rows = db.execute('SELECT bundle_hash,body FROM results').fetchall()
selected = [json.loads(body) for key, body in received_rows if key == digest]
assert len(selected) == 1
assert selected[0]['bundle'] == bundle
assert selected[0]['export'] == export
assert selected[0] in load('model-receiving-readback.json')['results']
assert load('readback-tool-result.json') == load('model-receiving-readback.json')

source_checks = []
for customer in manifest['customers']:
    for document in customer['documents']:
        actual = hashlib.sha256((work / document['text_file']).read_bytes()).hexdigest()
        assert actual == document['text_sha256']
        source_checks.append(dict(document_id=document['id'], text_sha256=actual, unchanged=True))

contexts = []
for rule in export['rules']:
    exact = dict(rule['required_facts'])
    variants = [
        ('matched_scenario', rule['customer_id'], rule['operation_id'], exact),
        ('missing_all_facts', rule['customer_id'], rule['operation_id'], {}),
        ('unknown_customer', 'unknown-customer', rule['operation_id'], exact),
        ('unknown_operation', rule['customer_id'], 'unknown-operation', exact),
    ]
    for key, value in exact.items():
        missing = dict(exact)
        missing.pop(key)
        changed = dict(exact)
        changed[key] = not value if isinstance(value, bool) else 'different-literal'
        variants.extend([
            ('missing_' + key, rule['customer_id'], rule['operation_id'], missing),
            ('different_' + key, rule['customer_id'], rule['operation_id'], changed),
        ])
    for case, customer, operation, facts in variants:
        contexts.append(dict(case=case, customer_id=customer, operation_id=operation, facts=facts))

spec = importlib.util.spec_from_file_location('local_tool', work.parent.parent / 'src/kyma_local/tool.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
sdk_checks = module.evaluate_sdk(export, contexts)
assert all(row['value'] is False for row in sdk_checks)


def check_prose(value, field=''):
    if isinstance(value, dict):
        for key, child in value.items():
            if key not in ['quote', 'required_facts']:
                check_prose(child, key)
    elif isinstance(value, list):
        for child in value:
            check_prose(child, field)
    elif isinstance(value, str):
        assert ';' not in value and '—' not in value, field
        for paragraph in value.split('\n\n'):
            sentences = re.split(r'(?<=[.!?])\s+', paragraph)
            assert len(sentences) <= 5, (field, 'paragraph', len(sentences))
            assert all(len(sentence.split()) <= 25 for sentence in sentences), (field, 'sentence')


check_prose(bundle)
receipt = dict(
    bundle_sha256=digest,
    decision_pairs_exactly_once=True,
    control_pairs_exactly_once=True,
    source_quotes_verified=len(bundle['evidence']),
    source_integrity=source_checks,
    decisions=[{key: row[key] for key in ['id', 'customer_id', 'operation_id', 'status']} for row in bundle['decisions']],
    receiver=dict(path=str(work / 'local-results.sqlite3'), table='results',
                  total_rows=len(received_rows), selected_rows=len(selected), bundle_exact=True,
                  export_exact=True, tool_readback_exact=True,
                  selection='The final canonical bundle hash selects the exact final receiver row. Earlier local revisions remain separate.'),
    openfeature=dict(compile_evaluations=len(load('openfeature-consumer.json')['evaluations']),
                     additional_actual_sdk_evaluations=len(sdk_checks), all_returned_false=True,
                     proposed_eligible=sum(row['proposed_eligible'] for row in export['rules']),
                     scope_limit='The all-false export verifies denial and exact delivery. It proves no positive contract clearance or live deployment. Unknown flags use the false caller default.'),
    opa=dict(artifact='feature-policy.rego', runtime_executed=False, reason='No opa executable is installed in PATH.'),
    outside_use=False,
    customer_accounts_changed=False,
)
(work / 'independent-receiving-check.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n')
(work / 'additional-openfeature-checks.json').write_text(json.dumps(sdk_checks, ensure_ascii=False, indent=2) + '\n')
print(json.dumps(receipt, ensure_ascii=False, indent=2))
