"""Use the current agent's interpretation with local source and receiver tools.

This adapter never invokes a model. A client-submitted assessment does not attest
which model authored it or how much source that model actually read.
"""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from threading import RLock
from typing import Any

from .documents import document_groups, inventory
from .main import SCHEMA
from .tool import canonical, compile_outputs, evaluate_sdk, load, validate, write


# The existing SDK evaluator owns a process-global default provider. Independent
# source reads remain concurrent; receiver work serializes only inside this adapter.
_RECEIVER_LOCK = RLock()


def prepare_contract_job(contracts: str, feature: str, out: str, references: str | None = None) -> dict[str, Any]:
    """Extract all supported sources for a new local job without a model call."""
    work = Path(out).expanduser().resolve()
    facts = load(Path(feature).expanduser().resolve())
    assert facts['id'] and facts['name'] and facts['operations'], 'named_feature_required'
    ids = [operation['id'] for operation in facts['operations']]
    assert len(set(ids)) == len(ids), 'duplicate_operation_id'
    try:
        work.mkdir(parents=True, exist_ok=False)
    except FileExistsError as error:
        raise ValueError('Use a new output folder. Existing work remains intact.') from error
    manifest = inventory(Path(contracts).expanduser().resolve(), work,
                         Path(references).expanduser().resolve() if references else None)
    write(work / 'feature.json', facts)
    return _prepared(work, manifest, facts)


def _prepared(work, manifest, facts):
    marker = {'schema': 'kyma-current-agent-job/v1',
              'source_manifest_sha256': sha256((work / 'source-manifest.json').read_bytes()).hexdigest(),
              'feature_sha256': sha256(canonical(facts)).hexdigest(),
              'model_invocation_by_adapter': False}
    if (work / 'revision-context.json').exists():
        marker['revision_context_sha256'] = sha256((work / 'revision-context.json').read_bytes()).hexdigest()
    write(work / 'agent-job.json', marker)
    return describe_contract_job(str(work))


def describe_contract_job(work: str) -> dict[str, Any]:
    """Read the complete prepared job without a new extraction or model invocation."""
    work = _job(work)
    manifest, facts = load(work / 'source-manifest.json'), load(work / 'feature.json')
    sources = []
    for group in document_groups(manifest):
        for document in group['documents']:
            sources.append({key: value for key, value in document.items() if key != 'units'})
    result = {'work': str(work), 'feature': facts, 'sources': sources,
            'assessment_schema': json.loads(SCHEMA),
            'next_action': 'Read every source with read_contract_source. Interpret the complete set, then submit your assessment.',
            'source_reading_attestation': None,
            'data_flow': 'Local extraction only. Your host agent applies its own account and provider policies to source text.'}
    if (work / 'revision-context.json').exists():
        result['revision_context'] = load(work / 'revision-context.json')
        result['assessment_schema']['revision_impacts'] = [{
            'id': 'REV1', 'change_id': 'exact input change id',
            'source_effect': 'Material source meaning and its exact boundary.',
            'engagement_state': 'established|not_established|not_applicable',
            'affected_operation_ids': [], 'customer_status_effect': 'Actual feature consequence and reason.',
            'engineering_action': 'Complete useful downstream work or exact implementation change.',
            'evidence_ids': [], 'unknown_ids': []}]
    return result


def prepare_revision_job(before: str, contracts: str, feature: str, out: str,
                         references: str | None = None) -> dict[str, Any]:
    """Prepare a complete source-change job for the current agent, without another model call."""
    from .watch import prepare_revision
    work = Path(out).expanduser().resolve()
    result = prepare_revision(Path(before).expanduser(), Path(contracts).expanduser(), Path(feature).expanduser(),
                              work, Path(references).expanduser() if references else None)
    if result['status'] == 'unchanged':
        return result
    prepared = _prepared(work, load(work / 'source-manifest.json'), load(work / 'feature.json'))
    return {**prepared,
            'status': 'prepared', 'revision_context': result['revision_context'],
            'next_action': 'Read every current and historical source. Reassess every customer-operation pair. Add revision_impacts for each change, then submit and read the result.'}


def _job(work):
    work = Path(work).expanduser().resolve()
    marker = load(work / 'agent-job.json')
    assert marker['schema'] == 'kyma-current-agent-job/v1', 'current_agent_job_required'
    assert sha256((work / 'source-manifest.json').read_bytes()).hexdigest() == marker['source_manifest_sha256'], 'source_inventory_changed'
    assert sha256(canonical(load(work / 'feature.json'))).hexdigest() == marker['feature_sha256'], 'feature_facts_changed'
    context = work / 'revision-context.json'
    if 'revision_context_sha256' in marker or context.exists():
        assert context.exists() and sha256(context.read_bytes()).hexdigest() == marker.get('revision_context_sha256'), 'revision_context_changed'
    return work


def read_contract_source(work: str, document_id: str) -> dict[str, Any]:
    """Return a complete extracted source and its exact original provenance."""
    work = _job(work)
    manifest = load(work / 'source-manifest.json')
    matches = [document for group in document_groups(manifest) for document in group['documents']
               if document['id'] == document_id]
    assert len(matches) == 1, 'source_identity_unknown_or_ambiguous'
    document = matches[0]
    raw = (work / document['text_file']).read_bytes()
    assert sha256(raw).hexdigest() == document['text_sha256'], 'source_hash_changed'
    return {'metadata': {key: value for key, value in document.items() if key != 'units'},
            'text': raw.decode(), 'units': document['units'], 'complete_extracted_bytes': len(raw)}


def submit_contract_assessment(work: str, bundle: dict) -> dict[str, Any]:
    """Validate the client's decisions and commit the exact local proposed exports."""
    with _RECEIVER_LOCK:
        return _submit_contract_assessment(work, bundle)


def _submit_contract_assessment(work, bundle):
    work = _job(work)
    checked = validate(work, bundle)
    # One prepared job retains one accepted assessment. Replay of that same
    # assessment recovers a partial local export without another receiver row.
    if (work / 'consumer-receipt.json').exists():
        assert load(work / 'consumer-receipt.json')['bundle_sha256'] == checked['bundle_sha256'], 'Use a new job for a revised accepted assessment.'
    write(work / 'model-decisions.json', bundle)
    receipt = compile_outputs(work, bundle)
    if (work / 'revision-context.json').exists():
        from .watch import finalize
        finalize(work)
    write(work / 'agent-adapter-receipt.json', {
        'schema': 'kyma-current-agent-receipt/v1',
        'bundle_sha256': checked['bundle_sha256'],
        'model_invocation_by_adapter': False,
        'author_identity_attestation': None,
        'source_reading_attestation': None,
        'provenance': 'The connected client supplied the assessment. This adapter verifies source spans, consistency and the local consumer.'})
    return {**receipt, 'work': str(work),
            'decisions': [{key: row[key] for key in ['customer_id', 'operation_id', 'status', 'rationale']} for row in bundle['decisions']],
            'next_action': 'Read the exact local result with read_contract_result.'}


def read_contract_result(work: str) -> dict[str, Any]:
    """Read the exact SQLite assessment and re-evaluate its OpenFeature export."""
    with _RECEIVER_LOCK:
        return _read_contract_result(work)


def _read_contract_result(work):
    work = _job(work)
    bundle = load(work / 'model-decisions.json')
    checked = validate(work, bundle)
    receipt = load(work / 'consumer-receipt.json')
    assert receipt['bundle_sha256'] == checked['bundle_sha256'], 'receipt_bundle_mismatch'
    export = load(work / 'openfeature-rules.json')
    assert export['bundle_sha256'] == checked['bundle_sha256'], 'export_bundle_mismatch'
    with sqlite3.connect('file:' + str(work / 'local-results.sqlite3') + '?mode=ro', uri=True) as db:
        row = db.execute('SELECT body FROM results WHERE bundle_hash=?', (checked['bundle_sha256'],)).fetchone()
        stored = json.loads(row[0]) if row else None
        count = db.execute('SELECT COUNT(*) FROM results').fetchone()[0]
    assert stored == {'bundle': bundle, 'export': export}, 'durable_result_mismatch'
    evaluations = evaluate_sdk(export, load(work / 'evaluation-contexts.json'))
    assert evaluations == load(work / 'openfeature-consumer.json')['evaluations'], 'fresh_sdk_result_mismatch'
    result = {'work': str(work), 'receipt': receipt, 'stored_result': stored,
              'receiver_rows': count, 'fresh_sdk_evaluations': evaluations,
              'durable_result_exact': True, 'model_invocation_by_adapter': False,
              'author_identity_attestation': None, 'source_reading_attestation': None}
    if (work / 'revision-context.json').exists():
        event = load(work / 'change-summary.json')
        with sqlite3.connect('file:' + str(work / 'local-results.sqlite3') + '?mode=ro', uri=True) as db:
            row = db.execute('SELECT body FROM revision_events WHERE event_hash=?', (event['event_sha256'],)).fetchone()
        assert row and json.loads(row[0]) == event, 'revision_receiver_mismatch'
        assert event['after_bundle_sha256'] == checked['bundle_sha256'], 'revision_bundle_mismatch'
        result['revision_event'] = event
        result['revision_receiving_state_exact'] = True
        write(work / 'revision-receiving-readback.json', {'events': [event]})
    write(work / 'agent-receiving-readback.json', result)
    return result


def main():
    parser = argparse.ArgumentParser(description='Use the current agent with the local Kyma source and receiver tools.')
    commands = parser.add_subparsers(dest='command', required=True)
    prepare = commands.add_parser('prepare')
    prepare.add_argument('--contracts', required=True)
    prepare.add_argument('--feature', required=True)
    prepare.add_argument('--out', required=True)
    prepare.add_argument('--references')
    revision = commands.add_parser('revision')
    revision.add_argument('--before', required=True)
    revision.add_argument('--contracts', required=True)
    revision.add_argument('--feature', required=True)
    revision.add_argument('--out', required=True)
    revision.add_argument('--references')
    source = commands.add_parser('source')
    source.add_argument('--work', required=True)
    source.add_argument('--document-id', required=True)
    submit = commands.add_parser('submit')
    submit.add_argument('--work', required=True)
    submit.add_argument('--assessment', required=True)
    read = commands.add_parser('readback')
    read.add_argument('--work', required=True)
    job = commands.add_parser('job')
    job.add_argument('--work', required=True)
    args = parser.parse_args()
    if args.command == 'prepare':
        value = prepare_contract_job(args.contracts, args.feature, args.out, args.references)
    elif args.command == 'revision':
        value = prepare_revision_job(args.before, args.contracts, args.feature, args.out, args.references)
    elif args.command == 'source':
        value = read_contract_source(args.work, args.document_id)
    elif args.command == 'submit':
        value = submit_contract_assessment(args.work, load(args.assessment))
    elif args.command == 'job':
        value = describe_contract_job(args.work)
    else:
        value = read_contract_result(args.work)
    print(json.dumps(value, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
