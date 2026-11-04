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


def update(args):
    from kyma_local.main import analyze, verify
    before = args.before.resolve()
    prior_receipt = verify(before)
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    assert not (out / 'launch.json').exists() and not (out / 'revision-context.json').exists(), 'Use a new revision output folder.'
    manifest = inventory(args.contracts, out, args.references, args.reference_baseline)
    old_manifest = load(before / 'source-manifest.json')
    changes = compare_sources(index(old_manifest['customers']), index(manifest['customers']), before, out,
                              'customer_contract_source', 'C')
    retain_previous_sources({'root': before, 'manifest': old_manifest}, manifest, changes, out)
    baseline_groups = manifest.get('historical_reference_sets', []) if args.reference_baseline else old_manifest.get('reference_sets', [])
    baseline_root = out if args.reference_baseline else before
    changes += compare_sources(index(baseline_groups), index(manifest.get('reference_sets', [])), baseline_root, out,
                               'shared_reference_source', 'R')
    old_feature, feature = load(before / 'feature.json'), load(args.feature)
    if canonical(old_feature) != canonical(feature):
        changes.append({'id': 'F1', 'kind': 'feature_facts', 'change': 'content_changed',
                        'before_sha256': sha256(canonical(old_feature)).hexdigest(),
                        'after_sha256': sha256(canonical(feature)).hexdigest(),
                        'complete_fact_diff': '\n'.join(difflib.unified_diff(
                            json.dumps(old_feature, sort_keys=True, indent=2).splitlines(),
                            json.dumps(feature, sort_keys=True, indent=2).splitlines(), fromfile='before/feature.json', tofile='after/feature.json'))})
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
               'external_reference_baseline': bool(args.reference_baseline),
               'baseline_scope': 'An explicitly supplied reference baseline is an independent captured source observation, not a claim that the previous AI assessed it.',
               'feature_preservation': 'The complete current feature file and customer contract sets remain the decision inputs.'}
    write(out / 'revision-context.json', context)
    args.prepared_manifest = True
    args.revision_context = context
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
    value = {**result, 'status': 'reassessed', 'input_changes': len(changes),
             'model_revision_impacts': len(event['model_revision_impacts']),
             'customers_with_changed_status': sorted({row['customer_id'] for row in event['status_changes']}),
             'revision_event_sha256': event['event_sha256'], 'actual_model_revision_tools_verified': True,
             'revision_receiving_state_exact': True}
    write(out / 'watch-result.json', value)
    return value


def finalize(work):
    context = load(work / 'revision-context.json')
    bundle = load(work / 'model-decisions.json')
    validation = validate(work, bundle)
    old = {(row['customer_id'], row['operation_id']): row for row in context['previous_actual_assessment']['decisions']}
    changed = []
    for row in bundle['decisions']:
        previous = old.get((row['customer_id'], row['operation_id']))
        if previous is None or previous['status'] != row['status']:
            changed.append({'customer_id': row['customer_id'], 'operation_id': row['operation_id'],
                            'before_status': previous['status'] if previous else None, 'after_status': row['status'],
                            'rationale': row['rationale'], 'evidence_ids': row['evidence_ids'],
                            'attribution': 'Observed assessment difference. The model revision impact identifies the source effect. A label change alone does not establish source causality.'})
    value = {'before_bundle_sha256': context['previous_bundle_sha256'], 'after_bundle_sha256': validation['bundle_sha256'],
             'input_changes': context['input_changes'], 'status_changes': changed,
             'model_revision_impacts': bundle['revision_impacts'],
             'current_engineering_outputs': bundle['engineering_outputs'],
             'current_conditional_drafts': bundle.get('notices_or_consent_drafts', []),
             'feature_facts_sha256': sha256(canonical(load(work / 'feature.json'))).hexdigest()}
    value['event_sha256'] = sha256(canonical(value)).hexdigest()
    write(work / 'change-summary.json', value)
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
