"""Exact source validation, decision exports and actual OpenFeature consumer reads.

The model chooses meaning, hierarchy, statuses, conditions and useful outputs.
This module does not turn exact quotation into legal truth.
"""
from hashlib import sha256
import argparse
import json
from pathlib import Path
import sqlite3

STATUSES = {'live_now', 'live_after_notice', 'needs_consent', 'live_with_conditions', 'off', 'unresolved'}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()


def load(path):
    return json.loads(Path(path).read_text())


def write(path, value):
    Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')


def validate(work, bundle):
    manifest = load(work / 'source-manifest.json')
    documents = {row['id']: row for customer in manifest['customers'] for row in customer['documents']}
    customer_ids = {customer['id'] for customer in manifest['customers']}
    feature = load(work / 'feature.json')
    operations = {row['id'] for row in feature['operations']}
    for source in documents.values():
        assert sha256((work / source['text_file']).read_bytes()).hexdigest() == source['text_sha256'], 'source_hash_changed'
    assert bundle['feature_id'] == feature['id'], 'feature_identity_mismatch'
    assert bundle['assessment_type'] == 'proposed_source_bound_decisions', 'assessment_type_required'
    evidence = {}
    resolved = []
    for item in bundle['evidence']:
        assert item['id'] not in evidence, 'duplicate_evidence_id'
        source = documents[item['document_id']]
        text = (work / source['text_file']).read_text()
        assert sha256(text.encode()).hexdigest() == source['text_sha256'], 'source_hash_changed'
        assert item['quote'] and item['quote'] in text, 'quote_not_in_source:' + item['id']
        start = text.index(item['quote'])
        page = item.get('page')
        if page is not None:
            assert any(unit['page'] == page and item['quote'] in unit['text'] for unit in source['units']), 'page_reference_mismatch'
        value = {**item, 'document_sha256': source['original_sha256'], 'text_sha256': source['text_sha256'],
                 'start': start, 'end': start + len(item['quote']), 'line_start': text[:start].count('\n') + 1,
                 'line_end': text[:start + len(item['quote'])].count('\n') + 1,
                 'source_class': source['provenance']['source_class']}
        evidence[item['id']] = value
        resolved.append(value)
    assert evidence, 'source_evidence_required'
    decisions = {}
    for row in bundle['decisions']:
        assert row['id'] not in decisions, 'duplicate_decision_id'
        assert row['customer_id'] in customer_ids and row['operation_id'] in operations, 'decision_target_mismatch'
        assert row['status'] in STATUSES, 'unknown_status'
        for field in ['actor', 'data', 'purpose', 'model', 'feature', 'conditions', 'rationale', 'evidence_ids', 'unknown_ids']:
            assert field in row, 'missing_relation_field:' + field
        assert row['evidence_ids'] and set(row['evidence_ids']) <= set(evidence), 'decision_evidence_missing'
        for identity in row['evidence_ids']:
            assert documents[evidence[identity]['document_id']]['customer_id'] == row['customer_id'], 'cross_customer_evidence'
        decisions[row['id']] = row
    assert {(row['customer_id'], row['operation_id']) for row in decisions.values()} == {(customer, operation) for customer in customer_ids for operation in operations}, 'incomplete_customer_operation_population'
    assert len(decisions) == len(customer_ids) * len(operations), 'duplicate_customer_operation_pair'
    unknowns = {row['id']: row for row in bundle['unknowns']}
    assert len(unknowns) == len(bundle['unknowns']), 'duplicate_unknown_id'
    for row in decisions.values():
        assert set(row['unknown_ids']) <= set(unknowns), 'unresolved_reference_missing'
    edges = {}
    for edge in bundle['precedence']:
        assert edge['higher_document_id'] in documents and edge['lower_document_id'] in documents, 'precedence_document_absent'
        assert edge['higher_document_id'] != edge['lower_document_id'], 'self_precedence'
        assert edge['evidence_ids'] and set(edge['evidence_ids']) <= set(evidence), 'precedence_evidence_missing'
        assert edge['scope'] and edge['reason'], 'scoped_precedence_required'
        edges.setdefault(edge['higher_document_id'], set()).add(edge['lower_document_id'])
    # Only identical-scope cycles are mechanically contradictory. Distinct subject matter can reverse hierarchy.
    for scope in {edge['scope'] for edge in bundle['precedence']}:
        scoped = {}
        for edge in bundle['precedence']:
            if edge['scope'] == scope:
                scoped.setdefault(edge['higher_document_id'], set()).add(edge['lower_document_id'])
        def visit(node, path):
            assert node not in path, 'precedence_cycle_same_scope'
            for child in scoped.get(node, set()):
                visit(child, path | {node})
        for node in scoped:
            visit(node, set())
    for control in bundle['controls']:
        decision = decisions[control['decision_id']]
        assert isinstance(control['proposed_eligible'], bool), 'control_boolean_required'
        assert isinstance(control['required_facts'], dict), 'required_facts_mapping_required'
        if control['proposed_eligible']:
            assert decision['status'] in {'live_now', 'live_with_conditions'}, 'unresolved_or_prohibited_cannot_be_enabled'
            assert not decision['unknown_ids'], 'unresolved_fact_cannot_be_enabled'
        assert control['customer_id'] == decision['customer_id'] and control['operation_id'] == decision['operation_id'], 'control_decision_mismatch'
    assert {row['decision_id'] for row in bundle['controls']} == set(decisions), 'control_population_incomplete'
    assert len(bundle['controls']) == len(decisions), 'duplicate_control'
    for task in bundle['engineering_outputs']:
        assert task['title'] and task['body'] and task['acceptance_criteria'], 'useful_engineering_output_required'
        assert set(task['decision_ids']) <= set(decisions), 'engineering_decision_missing'
    assert bundle['engineering_outputs'], 'at_least_one_useful_engineering_output_required'
    return {'valid': True, 'bundle_sha256': sha256(canonical(bundle)).hexdigest(), 'resolved_evidence': resolved,
            'semantics': 'The actual model selects interpretations, precedence, decisions, conditions and outputs. Code verifies exact provenance and consistency only.'}


def json_literals_equal(actual, expected):
    # JSON booleans are distinct from numbers. Python's False == 0 is not a valid fact match.
    if isinstance(actual, bool) or isinstance(expected, bool):
        return type(actual) is bool and type(expected) is bool and actual is expected
    if isinstance(actual, dict) or isinstance(expected, dict):
        return (type(actual) is dict and type(expected) is dict and actual.keys() == expected.keys()
                and all(json_literals_equal(actual[key], expected[key]) for key in expected))
    if isinstance(actual, list) or isinstance(expected, list):
        return (type(actual) is list and type(expected) is list and len(actual) == len(expected)
                and all(json_literals_equal(a, b) for a, b in zip(actual, expected)))
    if isinstance(actual, (int, float)) and isinstance(expected, (int, float)):
        return actual == expected
    return type(actual) is type(expected) and actual == expected


def evaluate_rule(rule, customer, facts):
    return bool(rule['customer_id'] == customer and rule['proposed_eligible'] is True and
                all(key in facts and json_literals_equal(facts[key], value)
                    for key, value in rule['required_facts'].items()))


def build_provider(export):
    """Return an importable OpenFeature provider without replacing an application's existing provider."""
    from openfeature.flag_evaluation import FlagResolutionDetails, Reason
    from openfeature.provider.in_memory_provider import InMemoryFlag, InMemoryProvider
    flags = {}
    for operation in export['operations']:
        rules = [row for row in export['rules'] if row['operation_id'] == operation]
        def resolver(flag, context, rules=rules):
            facts = context.attributes or {}
            variant = 'on' if any(evaluate_rule(rule, context.targeting_key, facts) for rule in rules) else 'off'
            return FlagResolutionDetails(value=flag.variants[variant], variant=variant, reason=Reason.TARGETING_MATCH)
        flags[export['feature_id'] + '.' + operation] = InMemoryFlag('off', {'on': True, 'off': False}, context_evaluator=resolver)
    return InMemoryProvider(flags)


def evaluate_sdk(export, contexts):
    """Exercise the real SDK in this isolated CLI process, then release its providers."""
    from openfeature import api
    from openfeature.evaluation_context import EvaluationContext
    api.set_provider_and_wait(build_provider(export))
    client = api.get_client('kyma-local-consumer')
    rows = []
    for context in contexts:
        key = export['feature_id'] + '.' + context['operation_id']
        details = client.get_boolean_details(key, False, EvaluationContext(targeting_key=context['customer_id'], attributes=context.get('facts') or {}))
        expected = any(evaluate_rule(rule, context['customer_id'], context.get('facts') or {}) for rule in export['rules'] if rule['operation_id'] == context['operation_id'])
        assert details.value == expected, 'openfeature_receiver_mismatch'
        rows.append({'context': context, 'flag_key': key, 'value': details.value, 'expected_model_control': expected,
                     'reason': str(details.reason), 'error_code': str(details.error_code) if details.error_code else None})
    api.shutdown()
    return rows


def compile_outputs(work, bundle):
    validation = validate(work, bundle)
    feature = load(work / 'feature.json')
    export = {'schema': 'kyma-openfeature-rules/v1', 'feature_id': feature['id'],
              'operations': [row['id'] for row in feature['operations']], 'rules': bundle['controls'],
              'bundle_sha256': validation['bundle_sha256'], 'default': False,
              'scope': 'Proposed model-derived contract assessment. Local evaluation does not prove actual deployment authority or customer clearance.'}
    write(work / 'validated-source-evidence.json', validation)
    write(work / 'openfeature-rules.json', export)
    write(work / 'opa-data.json', {'kyma_feature_rules': export})
    (work / 'feature-policy.rego').write_text('''package kyma.feature
import rego.v1
default enabled := false
enabled if {
    some rule in data.kyma_feature_rules.rules
    rule.proposed_eligible
    input.customer_id == rule.customer_id
    input.operation_id == rule.operation_id
    every key, value in rule.required_facts {
        input.facts[key] == value
    }
}
''')
    contexts = []
    for rule in export['rules']:
        contexts.append({'customer_id': rule['customer_id'], 'operation_id': rule['operation_id'], 'facts': dict(rule['required_facts'])})
        contexts.append({'customer_id': 'unknown-customer', 'operation_id': rule['operation_id'], 'facts': dict(rule['required_facts'])})
        if rule['required_facts']:
            missing = dict(rule['required_facts']);missing.pop(next(iter(missing)))
            contexts.append({'customer_id': rule['customer_id'], 'operation_id': rule['operation_id'], 'facts': missing})
    write(work / 'evaluation-contexts.json', contexts)
    receiving = evaluate_sdk(export, contexts)
    write(work / 'openfeature-consumer.json', {'sdk': 'openfeature-sdk==0.10.0', 'actual_sdk_evaluation': True, 'evaluations': receiving})
    lines = ['# ' + feature['name'], '', bundle['summary'], '',
             'These are proposed source-bound decisions. No actual feature or customer account was changed.', '',
             '| Customer | Operation | Proposed status | Rationale |', '|---|---|---|---|']
    for row in bundle['decisions']:
        lines.append('| ' + ' | '.join(str(row[key]).replace('|', '/') .replace('\n', ' ') for key in ['customer_id', 'operation_id', 'status', 'rationale']) + ' |')
    lines.extend(['', '## Engineering outputs', ''])
    for task in bundle['engineering_outputs']:
        lines.extend(['### ' + task['title'], '', task['body'], '', 'Acceptance: ' + task['acceptance_criteria'], ''])
    lines.extend(['## Unknowns', ''])
    for row in bundle['unknowns']:
        lines.extend(['- ' + row['id'] + ': ' + row['description'] + ' Resolution: ' + row['resolution']])
    (work / 'DECISIONS.md').write_text('\n'.join(lines) + '\n')
    with sqlite3.connect(work / 'local-results.sqlite3') as db:
        db.execute('CREATE TABLE IF NOT EXISTS results(bundle_hash TEXT PRIMARY KEY, body TEXT)')
        encoded = json.dumps({'bundle': bundle, 'export': export}, sort_keys=True)
        prior = db.execute('SELECT body FROM results WHERE bundle_hash=?', (validation['bundle_sha256'],)).fetchone()
        assert not prior or prior[0] == encoded, 'result_payload_conflict'
        db.execute('INSERT OR IGNORE INTO results VALUES (?,?)', (validation['bundle_sha256'], encoded))
        received = json.loads(db.execute('SELECT body FROM results WHERE bundle_hash=?', (validation['bundle_sha256'],)).fetchone()[0])
        assert received['bundle'] == bundle and received['export'] == export
    result = {'bundle_sha256': validation['bundle_sha256'], 'source_quotes_verified': len(validation['resolved_evidence']),
              'model_decisions': len(bundle['decisions']), 'model_engineering_outputs': len(bundle['engineering_outputs']),
              'openfeature_actual_evaluations': len(receiving), 'durable_result_exact': True,
              'artifacts': ['DECISIONS.md', 'openfeature-rules.json', 'feature-policy.rego', 'opa-data.json',
                            'validated-source-evidence.json', 'openfeature-consumer.json', 'local-results.sqlite3'],
              'outside_use': False, 'customer_accounts_changed': False}
    write(work / 'consumer-receipt.json', result)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['inspect', 'validate', 'compile', 'readback'])
    parser.add_argument('--work', type=Path, default=Path.cwd())
    parser.add_argument('--decision', default='model-decisions.json')
    args = parser.parse_args()
    work = args.work.resolve()
    if args.command == 'inspect':
        value = {'sources': load(work / 'source-manifest.json'), 'feature': load(work / 'feature.json'),
                 'scope': 'Complete extracted sources and user-proposed feature facts. No manual decision annex exists.'}
    elif args.command == 'readback':
        with sqlite3.connect('file:' + str(work / 'local-results.sqlite3') + '?mode=ro', uri=True) as db:
            value = {'results': [json.loads(row[0]) for row in db.execute('SELECT body FROM results ORDER BY bundle_hash')]}
        write(work / 'model-receiving-readback.json', value)
    else:
        bundle = load(work / args.decision)
        value = validate(work, bundle) if args.command == 'validate' else compile_outputs(work, bundle)
    print(json.dumps(value, ensure_ascii=False))


if __name__ == '__main__':
    main()
