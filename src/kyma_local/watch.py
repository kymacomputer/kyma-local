"""Reassess actual contract, feature and supplier-source changes through the user's model."""
import argparse
from copy import deepcopy
import difflib
from hashlib import sha256
import json
from pathlib import Path
import sqlite3

from kyma_local.documents import inventory
from kyma_local.tool import canonical, load, validate, write


def index(groups):
    return {row['original_relative_path']: row for group in groups for row in group['documents']}


def compare_sources(before, after, before_root, after_root, kind, prefix):
    changes = []
    for key in sorted(set(before) | set(after)):
        old, new = before.get(key), after.get(key)
        if old and new and old['original_sha256'] == new['original_sha256']:
            continue
        a = (before_root / old['text_file']).read_text() if old else ''
        b = (after_root / new['text_file']).read_text() if new else ''
        changes.append({'id': prefix + str(len(changes) + 1), 'kind': kind,
                        'change': 'added' if old is None else 'removed' if new is None else 'content_changed',
                        'relative_source': key, 'before_document_id': old['id'] if old else None,
                        'after_document_id': new['id'] if new else None,
                        'before_original_sha256': old['original_sha256'] if old else None,
                        'after_original_sha256': new['original_sha256'] if new else None,
                        'before_provenance': old['provenance'] if old else None,
                        'after_provenance': new['provenance'] if new else None,
                        'complete_observed_text_diff': '\n'.join(difflib.unified_diff(
                            a.splitlines(), b.splitlines(), fromfile='before/' + key, tofile='after/' + key, n=6))})
    return changes


def retain_previous_sources(prior, manifest, changes, out):
    groups = {}
    old_documents = index(prior['manifest']['customers'])
    for change in changes:
        old = old_documents.get(change['relative_source'])
        if not old:
            continue
        document = deepcopy(old)
        document['id'] = 'previous:' + old['id']
        document['source_role'] = 'historical_customer'
        document['text_file'] = 'documents/' + sha256(document['id'].encode()).hexdigest()[:16] + '.txt'
        (out / document['text_file']).write_bytes((prior['root'] / old['text_file']).read_bytes())
        document['provenance'] = {**document['provenance'], 'historical_assessment': str(prior['root'])}
        groups.setdefault(document['customer_id'], []).append(document)
        change['before_document_id'] = document['id']
    if groups:
        manifest['historical_customer_sets'] = [{'id': key, 'source_role': 'historical_customer', 'documents': values}
                                               for key, values in sorted(groups.items())]


def verify_previous(before):
    if (before / 'agent-job.json').exists():
        from kyma_local.agent_workflow import read_contract_result
        assert (before / 'agent-receiving-readback.json').exists(), 'Read the previous current-agent result before a revision.'
        return read_contract_result(str(before))['receipt']
    from kyma_local.main import verify
    return verify(before)


def prepare_revision(before, contracts, feature, out, references=None, reference_baseline=None):
    """Freeze complete revision inputs before either supported model route reads them."""
    before, out = Path(before).resolve(), Path(out).resolve()
    prior_receipt = verify_previous(before)
    facts = load(feature)
    assert facts['id'] and facts['name'] and facts['operations'], 'named_feature_required'
    ids = [row['id'] for row in facts['operations']]
    assert len(set(ids)) == len(ids), 'duplicate_operation_id'
    try:
        out.mkdir(parents=True, exist_ok=False)
    except FileExistsError as error:
        raise ValueError('Use a new revision output folder. Existing work remains intact.') from error
    manifest = inventory(contracts, out, references, reference_baseline)
    old_manifest = load(before / 'source-manifest.json')
    changes = compare_sources(index(old_manifest['customers']), index(manifest['customers']), before, out,
                              'customer_contract_source', 'C')
    retain_previous_sources({'root': before, 'manifest': old_manifest}, manifest, changes, out)
    from .importers import import_identity
    old_import = import_identity(old_manifest.get('contract_import'))
    new_import = import_identity(manifest.get('contract_import'))
    if old_import != new_import:
        changes.append({'id': 'I1', 'kind': 'contract_import_context', 'change': 'import_context_changed',
                        'before_import': old_import, 'after_import': new_import,
                        'scope': 'Export metadata, record relationships, query coverage and missing originals. No contractual precedence is inferred.'})
    baseline_groups = manifest.get('historical_reference_sets', []) if reference_baseline else old_manifest.get('reference_sets', [])
    baseline_root = out if reference_baseline else before
    changes += compare_sources(index(baseline_groups), index(manifest.get('reference_sets', [])), baseline_root, out,
                               'shared_reference_source', 'R')
    if not reference_baseline:
        historical = {}
        for change in changes:
            if change['kind'] != 'shared_reference_source' or not change['before_document_id']:
                continue
            document = deepcopy(index(baseline_groups)[change['relative_source']])
            document['id'] = 'previous:' + document['id']
            document['source_role'] = 'historical_reference'
            document['text_file'] = 'documents/' + sha256(document['id'].encode()).hexdigest()[:16] + '.txt'
            old_document = index(baseline_groups)[change['relative_source']]
            (out / document['text_file']).write_bytes((before / old_document['text_file']).read_bytes())
            historical.setdefault(document['customer_id'], []).append(document)
            change['before_document_id'] = document['id']
        manifest['historical_reference_sets'] = [
            {'id': key, 'source_role': 'historical_reference', 'documents': values}
            for key, values in sorted(historical.items())]
    old_feature = load(before / 'feature.json')
    if canonical(old_feature) != canonical(facts):
        changes.append({'id': 'F1', 'kind': 'feature_facts', 'change': 'content_changed',
                        'before_sha256': sha256(canonical(old_feature)).hexdigest(),
                        'after_sha256': sha256(canonical(facts)).hexdigest(),
                        'complete_fact_diff': '\n'.join(difflib.unified_diff(
                            json.dumps(old_feature, sort_keys=True, indent=2).splitlines(),
                            json.dumps(facts, sort_keys=True, indent=2).splitlines(), fromfile='before/feature.json', tofile='after/feature.json'))})
    write(out / 'feature.json', facts)
    write(out / 'source-manifest.json', manifest)
    write(out / 'input-diff.json', {'input_changes': changes,
                                  'comparison': 'Original content hashes and complete acquired text, independently of printed revision dates.'})
    if not changes:
        value = {'status': 'unchanged', 'actual_model_invocation': False,
                 'before_bundle_sha256': prior_receipt['bundle_sha256'], 'input_changes': [],
                 'previous_receiving_state_verified': True, 'output': str(out)}
        write(out / 'watch-result.json', value)
        (out / 'CHANGES.md').write_text('# Source and feature check\n\nThe original source bytes and feature facts are unchanged.\nThe previous verified engineering packet remains current for this snapshot.\n')
        return value
    context = {'previous_actual_assessment': load(before / 'model-decisions.json'),
               'previous_bundle_sha256': prior_receipt['bundle_sha256'], 'previous_assessment_directory': str(before),
               'input_changes': changes,
               'external_reference_baseline': bool(reference_baseline),
               'baseline_scope': 'An explicitly supplied reference baseline is an independent captured source observation, not a claim that the previous AI assessed it.',
               'feature_preservation': 'The complete current feature file and customer contract sets remain the decision inputs.'}
    write(out / 'revision-context.json', context)
    return {'status': 'prepared', 'output': str(out), 'revision_context': context,
            'actual_model_invocation': False, 'previous_receiving_state_verified': True}


def update(args):
    from kyma_local.main import analyze
    out = args.out.resolve()
    prepared = prepare_revision(args.before, args.contracts, args.feature, out, args.references, args.reference_baseline)
    if prepared['status'] == 'unchanged':
        return prepared
    args.prepared_manifest = True
    args.revision_context = prepared['revision_context']
    args.feature = out / 'feature.json'
    result = analyze(args)
    assert (out / 'revision-receiving-readback.json').exists(), 'The model did not read the revision receiver.'
    events = [json.loads(row) for row in (out / 'observable-transcript.jsonl').read_text().splitlines()]
    commands = [row['item']['command'] for row in events if row.get('type') == 'item.completed' and
                (row.get('item') or {}).get('type') == 'command_execution' and row['item'].get('exit_code') == 0]
    for action in ['finalize', 'readback']:
        assert any('watch.py ' + action in command for command in commands), 'Actual model revision tool missing: ' + action
    event = finalize(out)
    read = load(out / 'revision-receiving-readback.json')
    assert any(row == event for row in read['events']), 'The model revision read differs from the actual event.'
    value = {**result, 'status': 'reassessed', 'input_changes': len(prepared['revision_context']['input_changes']),
             'model_revision_impacts': len(event['model_revision_impacts']),
             'customers_with_changed_status': sorted({row['customer_id'] for row in event['status_changes']}),
             'revision_event_sha256': event['event_sha256'], 'actual_model_revision_tools_verified': True,
             'revision_receiving_state_exact': True}
    write(out / 'watch-result.json', value)
    return value


def collection_delta(before, after, identity, projection=lambda row: row):
    def grouped(rows):
        groups = {}
        for row in rows:
            groups.setdefault(identity(row), []).append(row)
        return groups
    old, new = grouped(before), grouped(after)
    result = []
    for key in sorted(set(old) | set(new)):
        a, b = old.get(key), new.get(key)
        if a is not None and b is not None and sorted(canonical(projection(r)) for r in a) == sorted(canonical(projection(r)) for r in b):
            continue
        result.append({'change': 'added' if a is None else 'removed' if b is None else 'changed',
                       'identity': list(key) if isinstance(key, tuple) else key, 'before': a[0] if a and len(a) == 1 else a,
                       'after': b[0] if b and len(b) == 1 else b})
    return result


def downstream_diff(previous, bundle):
    """Keep status labels separate from policy, conditions, engineering and draft changes."""
    old = {(r['customer_id'], r['operation_id']): r for r in previous['decisions']}
    new = {(r['customer_id'], r['operation_id']): r for r in bundle['decisions']}
    labels = []
    for pair in sorted(set(old) | set(new)):
        a, b = old.get(pair), new.get(pair)
        if a is None or b is None or a['status'] != b['status']:
            row = b or a
            labels.append({'customer_id': pair[0], 'operation_id': pair[1],
                           'before_status': a['status'] if a else None, 'after_status': b['status'] if b else None,
                           'rationale': row['rationale'], 'evidence_ids': row['evidence_ids'],
                           'attribution': 'Observed assessment difference. Source causality requires the model revision impact.'})
    fields = ('status', 'actor', 'data', 'purpose', 'model', 'feature', 'conditions')
    decisions = collection_delta(previous['decisions'], bundle['decisions'],
                                 lambda r: (r['customer_id'], r['operation_id']),
                                 lambda r: {k: r.get(k) for k in fields})
    controls = collection_delta(previous['controls'], bundle['controls'],
                                lambda r: (r['customer_id'], r['operation_id']))
    engineering = collection_delta(previous['engineering_outputs'], bundle['engineering_outputs'], lambda r: r['id'])
    drafts = collection_delta(previous.get('notices_or_consent_drafts', []), bundle.get('notices_or_consent_drafts', []),
                              lambda r: (r['customer_id'], r['type']))
    affected = sorted({r['customer_id'] for r in labels})
    return {'status_changes': labels, 'decision_changes': decisions, 'control_changes': controls,
            'engineering_changes': engineering, 'draft_changes': drafts,
            'changed_customer_segments': {
                'customers': affected,
                'rules': [r for r in bundle['controls'] if r['customer_id'] in affected],
                'removed_rules': [r['before'] for r in controls if r['change'] == 'removed' and r['before']['customer_id'] in affected],
                'conditional_drafts': [r for r in bundle.get('notices_or_consent_drafts', []) if r['customer_id'] in affected]}}


def finalize(work):
    context = load(work / 'revision-context.json')
    bundle = load(work / 'model-decisions.json')
    validation = validate(work, bundle)
    delta = downstream_diff(context['previous_actual_assessment'], bundle)
    changed = delta['status_changes']
    value = {'schema': 'kyma-source-revision/v2',
             'before_bundle_sha256': context['previous_bundle_sha256'], 'after_bundle_sha256': validation['bundle_sha256'],
             'input_changes': context['input_changes'], **delta,
             'model_revision_impacts': bundle['revision_impacts'],
             'current_engineering_outputs': bundle['engineering_outputs'],
             'current_conditional_drafts': bundle.get('notices_or_consent_drafts', []),
             'feature_facts_sha256': sha256(canonical(load(work / 'feature.json'))).hexdigest()}
    value['event_sha256'] = sha256(canonical(value)).hexdigest()
    write(work / 'change-summary.json', value)
    write(work / 'changed-customer-segments.json', delta['changed_customer_segments'])
    write(work / 'downstream-diff.json', {key: delta[key] for key in [
        'decision_changes', 'control_changes', 'engineering_changes', 'draft_changes']})
    lines = ['# Source and feature revision', '', '## Source effects and engineering work', '']
    for impact in bundle['revision_impacts']:
        lines.extend(['### ' + impact['change_id'], '', impact['source_effect'], '', impact['engineering_action'], '',
                      'Engagement state: ' + impact['engagement_state'] + '.', ''])
    lines.extend(['## Customers with changed status', ''])
    if changed:
        lines.extend(['| Customer | Operation | Before | After |', '|---|---|---|---|'])
        for row in changed:
            lines.append('| ' + ' | '.join(str(row[key]) for key in ['customer_id', 'operation_id', 'before_status', 'after_status']) + ' |')
    else:
        lines.append('The customer statuses are unchanged.')
    lines.extend(['', '## Changed downstream work', ''])
    for kind in ['engineering_changes', 'draft_changes', 'control_changes', 'decision_changes']:
        rows = delta[kind]
        lines.extend(['### ' + kind.replace('_', ' ').capitalize(), ''])
        if not rows:
            lines.extend(['No change.', ''])
        for row in rows:
            lines.extend([row['change'] + ': ' + str(row['identity']), '',
                          '```json', json.dumps(row, ensure_ascii=False, indent=2), '```', ''])
    (work / 'CHANGES.md').write_text('\n'.join(lines) + '\n')
    with sqlite3.connect(work / 'local-results.sqlite3') as db:
        db.execute('CREATE TABLE IF NOT EXISTS revision_events(event_hash TEXT PRIMARY KEY, body TEXT)')
        body = canonical(value).decode()
        old_row = db.execute('SELECT body FROM revision_events WHERE event_hash=?', (value['event_sha256'],)).fetchone()
        assert old_row is None or old_row[0] == body, 'revision_event_payload_conflict'
        db.execute('INSERT OR IGNORE INTO revision_events VALUES (?,?)', (value['event_sha256'], body))
        received = db.execute('SELECT body FROM revision_events WHERE event_hash=?', (value['event_sha256'],)).fetchone()
        assert received and json.loads(received[0]) == value
    return value


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['finalize', 'readback'])
    parser.add_argument('--work', type=Path, required=True)
    args = parser.parse_args()
    work = args.work.resolve()
    if args.command == 'finalize':
        value = finalize(work)
    else:
        with sqlite3.connect('file:' + str(work / 'local-results.sqlite3') + '?mode=ro', uri=True) as db:
            value = {'events': [json.loads(row[0]) for row in db.execute('SELECT body FROM revision_events ORDER BY event_hash')]}
        write(work / 'revision-receiving-readback.json', value)
    print(json.dumps(value, ensure_ascii=False))


if __name__ == '__main__':
    main()
