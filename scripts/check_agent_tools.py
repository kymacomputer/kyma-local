"""Exercise the actual stdio protocol and local receiver with retained public AI work."""
import argparse
import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import time

from mcp import Client, StdioServerParameters


async def check(kit, output):
    started = time.perf_counter()
    root = Path(tempfile.mkdtemp(prefix='kyma-mcp-consumer-'))
    old = json.loads((kit / 'runs/fresh-user-run/model-decisions.json').read_text())
    checks = []
    server = StdioServerParameters(command=sys.executable, args=['-m', 'kyma_local.mcp_server'],
                                  env={'PYTHONPATH': str(kit / 'src')})
    async with Client(server, mode='2026-07-28', read_timeout_seconds=90) as client:
        listed = await client.list_tools()
        expected = {'import_contract_export', 'prepare_contract_job', 'prepare_revision_job', 'read_contract_source', 'submit_contract_assessment', 'read_contract_result'}
        assert {tool.name for tool in listed.tools} == expected
        checks.append({'case': 'actual_stdio_tool_discovery', 'passed': True, 'tools': sorted(expected)})

        async def call(name, arguments, error=False, reason=None):
            response = await client.call_tool(name, arguments)
            assert bool(response.is_error) == error, (name, response.content)
            if reason:
                assert reason in '\n'.join(getattr(part, 'text', '') for part in response.content)
            return response.structured_content

        prepared = await call('prepare_contract_job', {
            'contracts': str(kit / 'sample/contracts'), 'feature': str(kit / 'sample/feature.json'),
            'out': str(root / 'work')})
        assert prepared['feature']['id'] == old['feature_id']
        assert len(prepared['sources']) == 4
        acquired = []
        for source in prepared['sources']:
            got = await call('read_contract_source', {'work': prepared['work'], 'document_id': source['id']})
            raw = got['text'].encode()
            assert len(raw) == got['complete_extracted_bytes']
            assert hashlib.sha256(raw).hexdigest() == source['text_sha256']
            acquired.append({'id': source['id'], 'bytes': len(raw), 'sha256': source['text_sha256']})
        checks.append({'case': 'complete_four_public_sources_over_stdio', 'passed': True, 'sources': acquired})

        await call('prepare_contract_job', {
            'contracts': str(kit / 'sample/contracts'), 'feature': str(kit / 'sample/feature.json'),
            'out': prepared['work']}, error=True, reason='Use a new output folder.')
        assert not (root / 'work/local-results.sqlite3').exists()
        checks.append({'case': 'occupied_output_preserves_existing_source_job', 'passed': True})

        bad = deepcopy(old)
        bad['evidence'][0]['quote'] = 'This invented sentence is absent from the original public contracts.'
        await call('submit_contract_assessment', {'work': prepared['work'], 'bundle': bad}, error=True, reason='quote_not_in_source')
        assert not (root / 'work/local-results.sqlite3').exists()
        assert not (root / 'work/model-decisions.json').exists()
        checks.append({'case': 'fabricated_quote_rejected_before_receiver', 'passed': True})

        incomplete = deepcopy(old)
        incomplete['decisions'].pop()
        await call('submit_contract_assessment', {'work': prepared['work'], 'bundle': incomplete}, error=True, reason='incomplete_customer_operation_population')
        assert not (root / 'work/local-results.sqlite3').exists()
        checks.append({'case': 'missing_customer_operation_rejected', 'passed': True})

        accepted = await call('submit_contract_assessment', {'work': prepared['work'], 'bundle': old})
        assert accepted['model_decisions'] == 6 and accepted['durable_result_exact']
        actual = await call('read_contract_result', {'work': prepared['work']})
        assert actual['stored_result']['bundle'] == old
        assert actual['receiver_rows'] == 1 and actual['durable_result_exact']
        assert len(actual['fresh_sdk_evaluations']) == 18
        checks.append({'case': 'retained_actual_ai_bundle_compiles_and_reads_exactly', 'passed': True,
                       'bundle_sha256': accepted['bundle_sha256'], 'decisions': 6,
                       'sdk_evaluations': 18, 'new_model_invocation': False})

        repeated = await asyncio.gather(*[
            call('submit_contract_assessment', {'work': prepared['work'], 'bundle': old}) for _ in range(2)])
        assert all(row['bundle_sha256'] == accepted['bundle_sha256'] for row in repeated)
        after = await call('read_contract_result', {'work': prepared['work']})
        assert after['receiver_rows'] == 1 and after['stored_result']['bundle'] == old
        checks.append({'case': 'concurrent_exact_replay_has_one_receiver_row', 'passed': True})

        conflict = deepcopy(old)
        conflict['summary'] += ' This is a later proposed revision.'
        await call('submit_contract_assessment', {'work': prepared['work'], 'bundle': conflict}, error=True)
        assert json.loads((root / 'work/model-decisions.json').read_text()) == old
        checks.append({'case': 'accepted_assessment_is_preserved_on_conflict', 'passed': True})

        revision_facts = {**prepared['feature'], 'fixture_revision': 'Explicit stdio revision fixture.'}
        (root / 'revision-feature.json').write_text(json.dumps(revision_facts))
        revision = await call('prepare_revision_job', {
            'before': prepared['work'], 'contracts': str(kit / 'sample/contracts'),
            'feature': str(root / 'revision-feature.json'), 'out': str(root / 'revision')})
        assert revision['status'] == 'prepared'
        assert revision['assessment_schema']['revision_impacts']
        assert len(revision['sources']) == 4
        revised = deepcopy(old)
        revised['revision_impacts'] = [{
            'id': 'FIXTURE-REV1', 'change_id': 'F1', 'source_effect': 'Explicit metadata fixture.',
            'engagement_state': 'not_established', 'affected_operation_ids': [],
            'customer_status_effect': 'The retained proposals remain exact for this protocol fixture.',
            'engineering_action': 'Read the exact revised local export.',
            'evidence_ids': [old['evidence'][0]['id']], 'unknown_ids': []}]
        await call('submit_contract_assessment', {'work': revision['work'], 'bundle': revised})
        revision_read = await call('read_contract_result', {'work': revision['work']})
        assert revision_read['stored_result']['bundle'] == revised
        assert revision_read['revision_receiving_state_exact']
        assert not revision_read['revision_event']['status_changes']
        replay = await call('submit_contract_assessment', {'work': revision['work'], 'bundle': revised})
        assert replay['bundle_sha256'] == revision_read['receipt']['bundle_sha256']
        checks.append({'case': 'actual_stdio_current_agent_revision_schema_commit_and_readback', 'passed': True,
                       'new_model_invocation': False, 'scope': 'Explicit feature metadata fixture with retained actual AI work.'})

        feature_path = root / 'work/feature.json'
        feature = json.loads(feature_path.read_text())
        feature['name'] += ' altered'
        feature_path.write_text(json.dumps(feature))
        await call('read_contract_result', {'work': prepared['work']}, error=True)
        feature_path.write_text(json.dumps(prepared['feature'], indent=2) + '\n')
        checks.append({'case': 'changed_feature_facts_rejected', 'passed': True})

        race_args = {'contracts': str(kit / 'sample/contracts'), 'feature': str(kit / 'sample/feature.json'),
                     'out': str(root / 'competing-preparation')}
        race = await asyncio.gather(*[client.call_tool('prepare_contract_job', race_args) for _ in range(2)])
        assert sum(bool(row.is_error) for row in race) == 1
        assert (root / 'competing-preparation/agent-job.json').exists()
        checks.append({'case': 'same_output_preparation_has_one_atomic_winner', 'passed': True})

    # The actual SDK also exercises its legacy initialize path in a new process.
    async with Client(server, mode='legacy', read_timeout_seconds=90) as client:
        listed = await client.list_tools()
        assert {tool.name for tool in listed.tools} == expected
        received = await client.call_tool('read_contract_result', {'work': prepared['work']})
        assert not received.is_error
        assert received.structured_content['stored_result']['bundle'] == old
        checks.append({'case': 'legacy_stdio_discovery_and_exact_result_readback', 'passed': True})

    value = {'schema': 'kyma-mcp-actual-consumer/v1', 'at': datetime.now(timezone.utc).isoformat(),
             'kit': str(kit), 'work': str(root / 'work'), 'checks': checks,
             'all_passed': all(row['passed'] for row in checks),
             'elapsed_seconds': time.perf_counter() - started,
             'new_model_invocation': False, 'independent_host_install': False,
             'scope': 'Actual modern and legacy stdio, complete source transport, retained public model result, local SDK and SQLite. No new model interpretation or outside use is claimed.'}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(value, indent=2) + '\n')
    print(json.dumps(value, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--kit', type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(check(args.kit.resolve(), args.out.resolve()))
