"""Consumer controls for X9. Retained AI work and explicit fixtures, without new model calls."""
import argparse
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time
import tempfile
from unittest.mock import patch
from urllib.error import HTTPError

from kyma_local import follow
from kyma_local.agent_workflow import prepare_revision_job, read_contract_result, submit_contract_assessment
from kyma_local.main import verify
from kyma_local import main as main_module
from kyma_local.tool import canonical, load, write
from kyma_local.watch import downstream_diff


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--kit', type=Path, default=Path.cwd())
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    kit = args.kit.resolve()
    checks = []
    with tempfile.TemporaryDirectory(prefix='kyma-x9-consumer-') as raw:
        root = Path(raw)
        contracts = root / 'contracts'
        shutil.copytree(kit / 'sample/contracts', contracts)
        feature = root / 'feature.json'
        shutil.copy2(kit / 'sample/feature.json', feature)
        original = load(kit / 'runs/fresh-user-run/model-decisions.json')

        def passed(name, **details):
            checks.append({'case': name, 'passed': True, **details})

        def rejected(name, action, reason):
            try:
                action()
            except (AssertionError, ValueError) as error:
                assert reason in str(error), (name, str(error))
                passed(name, exact_error=str(error))
            else:
                raise AssertionError('Expected rejection: ' + name)

        count = 0

        def fixture_update(options):
            nonlocal count
            count += 1
            result = prepare_revision_job(str(options.before), str(options.contracts), str(options.feature),
                                          str(options.out), str(options.references) if options.references else None)
            if result['status'] == 'unchanged':
                return result
            bundle = deepcopy(original)
            bundle['engineering_outputs'].append({'id': 'FIXTURE-WORK', 'title': 'Explicit observer fixture',
                                                 'body': 'Fixture input identity: ' + follow.input_identity(options.out),
                                                 'acceptance_criteria': 'The exact receiver returns this fixture work.',
                                                 'decision_ids': [bundle['decisions'][0]['id']]})
            bundle['revision_impacts'] = [
                {'id': 'FIXTURE-' + row['id'], 'change_id': row['id'],
                 'source_effect': 'Explicit test change. No new model interpretation is claimed.',
                 'engagement_state': 'not_established', 'affected_operation_ids': [],
                 'customer_status_effect': 'Retained proposals stay exact for this mechanical fixture.',
                 'engineering_action': 'Exercise the actual local revision receiver.',
                 'evidence_ids': [bundle['evidence'][0]['id']], 'unknown_ids': []}
                for row in result['revision_context']['input_changes']]
            submit_contract_assessment(str(options.out), bundle)
            read_contract_result(str(options.out))
            return {'status': 'reassessed', 'fixture_only': True}

        # Baseline exact sources and no-change behavior retain the strict CLI proof.
        unchanged = prepare_revision_job(str(kit / 'runs/fresh-user-run'), str(contracts), str(feature), str(root / 'unchanged'))
        assert unchanged['status'] == 'unchanged' and not unchanged['actual_model_invocation']
        passed('unchanged_complete_sources_skip_model')
        rejected('existing_revision_preserved', lambda: prepare_revision_job(
            str(kit / 'runs/fresh-user-run'), str(contracts), str(feature), str(root / 'unchanged')), 'new revision output')

        settings = argparse.Namespace(out=root / 'observer', before=kit / 'runs/fresh-user-run',
            contracts=contracts, feature=feature, references=None, reference_sources=None, opt_in=True,
            next_event='Fixture: planned contract amendment', event_date='2026-11-06', first_value_note='Fixture baseline use.',
            prepare_only=False, mode='kyma', model='unused-fixture', effort='ultra', timeout=30)
        settings.out.mkdir()
        state = follow.initialize(settings, settings.out)
        baseline_id = state['install_id']
        assert state['next_natural_event']['date'] == '2026-11-06'
        result = follow.tick(state, settings.out, settle_seconds=0, run_update=fixture_update)
        assert result['status'] == 'unchanged' and len(state['jobs']) == 1
        before_count = count
        result = follow.tick(state, settings.out, settle_seconds=0, run_update=fixture_update)
        assert result['status'] == 'unchanged' and count == before_count
        passed('explicit_local_event_record_and_zero_model_empty_poll')

        cli_root = root / 'cli-observer'
        command = [sys.executable, '-m', 'kyma_local.main', 'follow', '--out', str(cli_root),
                   '--before', str(kit / 'runs/fresh-user-run'), '--contracts', str(contracts), '--feature', str(feature),
                   '--opt-in', '--next-event', 'Explicit CLI fixture event', '--event-date', '2026-11-06', '--once', '--settle-seconds', '0']
        process = subprocess.run(command, capture_output=True, text=True, timeout=30)
        assert process.returncode == 0, process.stderr
        cli_state = load(cli_root / 'observer.json')
        assert len(cli_state['jobs']) == 1 and cli_state['pending'] is None
        resumed = subprocess.run([sys.executable, '-m', 'kyma_local.main', 'follow', '--out', str(cli_root),
                                  '--once', '--settle-seconds', '0'], capture_output=True, text=True, timeout=30)
        assert resumed.returncode == 0 and load(cli_root / 'observer.json')['install_id'] == cli_state['install_id']
        with (cli_root / '.observer.lock').open('a') as lock:
            follow.fcntl.flock(lock, follow.fcntl.LOCK_EX | follow.fcntl.LOCK_NB)
            competing = subprocess.run([sys.executable, '-m', 'kyma_local.main', 'follow', '--out', str(cli_root), '--once'],
                                       capture_output=True, text=True, timeout=30)
            assert competing.returncode != 0 and 'foreground owner' in competing.stderr
            report = subprocess.run([sys.executable, '-m', 'kyma_local.main', 'activity', '--out', str(cli_root),
                                    '--confirm-job', cli_state['jobs'][0]['job_id'], '--useful-note', 'Explicit local fixture usefulness.'],
                                   capture_output=True, text=True, timeout=30)
            assert report.returncode == 0 and json.loads(report.stdout)['jobs'][0]['useful_self_report']['source'] == 'local_user_statement'
        assert (cli_root / 'observer.json').read_text() == json.dumps(load(cli_root / 'observer.json'), indent=2, ensure_ascii=False) + '\n'
        assert not load(cli_root / 'observer.json')['jobs'][0]['useful_self_report']
        passed('actual_cli_opt_in_resume_exclusive_owner_and_concurrent_local_usefulness_note')

        live_root = root / 'live-observer'
        live_feature = root / 'live-feature.json'
        shutil.copy2(feature, live_feature)
        live = subprocess.Popen([sys.executable, '-m', 'kyma_local.main', 'follow', '--out', str(live_root),
            '--before', str(kit / 'runs/fresh-user-run'), '--contracts', str(contracts), '--feature', str(live_feature),
            '--opt-in', '--next-event', 'Explicit live source fixture', '--event-date', '2026-11-06',
            '--prepare-only', '--poll-seconds', '0.1', '--settle-seconds', '0'],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        def await_state(predicate):
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                if (live_root / 'observer.json').exists():
                    candidate = load(live_root / 'observer.json')
                    if predicate(candidate):
                        return candidate
                assert live.poll() is None, 'live observer exited unexpectedly'
                time.sleep(0.05)
            raise AssertionError('live observer state deadline')
        try:
            await_state(lambda value: value['fingerprint'] is not None)
            write(live_feature, {**load(feature), 'fixture_revision': 'Live local edit.'})
            current = await_state(lambda value: bool(value['pending']) and Path(value['pending']['work']).joinpath('agent-job.json').exists())
            work = Path(current['pending']['work'])
            bundle = deepcopy(original)
            bundle['revision_impacts'] = [{'id': 'LIVE-FIXTURE', 'change_id': 'F1', 'source_effect': 'Explicit live-process metadata fixture.',
                'engagement_state': 'not_established', 'affected_operation_ids': [], 'customer_status_effect': 'Retained proposals remain exact.',
                'engineering_action': 'Exercise source-trigger to real receiver.', 'evidence_ids': [bundle['evidence'][0]['id']], 'unknown_ids': []}]
            submit_contract_assessment(str(work), bundle)
            read_contract_result(str(work))
            current = await_state(lambda value: len(value['jobs']) == 2 and value['pending'] is None)
            assert current['jobs'][1]['automatic_completion'] is False
            assert not follow.activity(current)['qualified_local_repeat_job_ids']
            live.send_signal(signal.SIGINT)
            stdout, stderr = live.communicate(timeout=15)
            assert live.returncode == 0 and 'job_completed' in stdout and '"status": "stopped"' in stdout, (stdout, stderr)
            passed('actual_foreground_source_trigger_agent_receiver_promotion_and_clean_stop', new_model_calls=0)
        finally:
            if live.poll() is None:
                live.terminate()
                live.communicate(timeout=15)

        facts = load(feature)
        facts['fixture_revision'] = 1
        write(feature, facts)
        captured_work = []

        def change_during_model(options):
            captured_work.append(options.out)
            result = fixture_update(options)
            next_facts = load(feature)
            next_facts['fixture_revision'] = 2
            write(feature, next_facts)
            return result

        result = follow.tick(state, settings.out, 0, change_during_model)
        assert result['status'] == 'reassessed' and len(state['jobs']) == 2
        assert load(captured_work[0] / 'feature.json')['fixture_revision'] == 1
        assert load(feature)['fixture_revision'] == 2
        result = follow.tick(state, settings.out, 0, fixture_update)
        assert result['status'] == 'reassessed' and len(state['jobs']) == 3
        assert load(Path(state['before']) / 'feature.json')['fixture_revision'] == 2
        assert all(row['consumer_verified'] for row in state['jobs'])
        assert follow.load(settings.out / 'observer.json')['install_id'] == baseline_id
        passed('change_during_analysis_survives_as_next_distinct_job', completed_fixture_jobs=3)

        result = verify(Path(state['before']))
        assert result['verification_route'] == 'current_agent' and result['revision_receiving_state_exact']
        assert result['author_identity_attestation'] is None
        assert result['source_reading_attestation'] is None
        passed('general_verifier_dispatches_current_agent_without_false_model_attestation')

        # Crash-after-receiver/before-state-save recovery observes one existing effect.
        recovered = deepcopy(state)
        recovered['pending'] = {'work': str(captured_work[0]), 'fingerprint': 'fixture-captured-input',
                                'automatic_completion': False}
        recovered['jobs'] = recovered['jobs'][:1]
        assert follow.finish_pending(recovered) and len(recovered['jobs']) == 2
        assert not follow.finish_pending(recovered) and len(recovered['jobs']) == 2
        assert recovered['jobs'][1]['automatic_completion'] is False
        passed('crash_after_receiver_recovery_reads_one_effect_without_replay')

        summary = load(Path(state['before']) / 'change-summary.json')
        assert not summary['status_changes'] and summary['engineering_changes']
        assert summary['changed_customer_segments'] == {'customers': [], 'rules': [], 'removed_rules': [], 'conditional_drafts': []}
        passed('same_status_preserves_useful_downstream_work_without_customer_broadcast')

        # Contract additions and removals are retained as complete source-change evidence.
        added = contracts / 'c3-bhge/fixture-amendment.txt'
        added.write_text('Explicit fixture amendment, not an executed customer agreement.\n')
        result = follow.tick(state, settings.out, 0, fixture_update)
        assert any(row['change'] == 'added' and row['kind'] == 'customer_contract_source'
                   for row in load(Path(state['before']) / 'input-diff.json')['input_changes'])
        added.unlink()
        follow.tick(state, settings.out, 0, fixture_update)
        removed_manifest = load(Path(state['before']) / 'source-manifest.json')
        assert removed_manifest['historical_customer_sets'][0]['documents'][0]['source_role'] == 'historical_customer'
        passed('contract_addition_and_removal_trigger_with_complete_prior_source')

        # A source with a stable printed date still changes by original bytes.
        refs = root / 'references'
        shutil.copytree(kit / 'sample/references-before', refs)
        reference_revision = prepare_revision_job(str(kit / 'runs/watch-fullstory-source-change'), str(contracts),
            str(kit / 'sample/feature.json'), str(root / 'reference-revision'), str(refs))
        sources = reference_revision['sources']
        historical = [row for row in sources if row['source_role'] == 'historical_reference']
        assert len(historical) == 1 and (root / 'reference-revision' / historical[0]['text_file']).read_bytes()
        assert any(row['kind'] == 'shared_reference_source' for row in reference_revision['revision_context']['input_changes'])
        passed('changed_supplier_reference_retains_complete_current_and_prior_versions')

        facts['fixture_revision'] = 3
        write(feature, facts)
        attempts = []

        def fail(options):
            attempts.append(str(options.out))
            raise RuntimeError('Explicit fixture transport failure before model result.')

        try:
            follow.tick(state, settings.out, 0, fail)
        except RuntimeError:
            pass
        else:
            raise AssertionError('fixture failure expected')
        current_jobs = len(state['jobs'])
        result = follow.tick(state, settings.out, 0, fail)
        assert result['status'] == 'previous_attempt_failed' and len(attempts) == 1 and len(state['jobs']) == current_jobs
        assert Path(state['failed']['work']).parent.joinpath('input/feature.json').exists()
        passed('failed_attempt_preserves_input_and_never_retries_unchanged_model_job')

        actual_fingerprint = follow.fingerprint(state['config'])
        with patch.object(follow, 'fingerprint', side_effect=[actual_fingerprint, 'newer-source']):
            state['failed'] = None
            result = follow.tick(state, settings.out, 0, fail)
        assert result['status'] == 'inputs_not_stable' and len(attempts) == 1
        passed('unstable_input_skips_model_and_snapshot')

        state['prompted_retry_fingerprint'] = follow.fingerprint(state['config'])
        follow.tick(state, settings.out, 0, fixture_update)
        assert state['jobs'][-1]['automatic_completion'] is False
        write(feature, {**facts, 'fixture_revision': 4})
        follow.tick(state, settings.out, 0, fixture_update, automatic_trigger=False)
        assert state['jobs'][-1]['automatic_completion'] is False
        passed('explicit_retry_and_manual_one_shot_cannot_count_as_unprompted_repeat')

        # Simulated clocks test the predicate. These are never production retention evidence.
        measured = deepcopy(state)
        initial = datetime(2026, 1, 1, tzinfo=timezone.utc)
        measured['jobs'] = deepcopy(state['jobs'][:2])
        first, second = measured['jobs']
        first['completed_at_utc'] = initial.isoformat()
        second['completed_at_utc'] = (initial + timedelta(hours=24)).isoformat()
        first['useful_self_report'] = second['useful_self_report'] = {'note': 'Fixture report.'}
        assert follow.activity(measured)['qualified_local_repeat_job_ids'] == [second['job_id']]
        for key, value in [('automatic_completion', False), ('distinct_input', False), ('useful_self_report', None),
                           ('downstream_delta_counts', {'status_changes': 0})]:
            copy = deepcopy(measured)
            copy['jobs'][1][key] = value
            assert not follow.activity(copy)['qualified_local_repeat_job_ids']
        copy = deepcopy(measured)
        copy['jobs'][1]['completed_at_utc'] = (initial + timedelta(hours=24, microseconds=-1)).isoformat()
        assert not follow.activity(copy)['qualified_local_repeat_job_ids']
        assert not follow.activity(state)['qualified_local_repeat_job_ids']
        passed('repeat_predicate_rejects_uptime_replay_prompted_empty_unconfirmed_and_under24h', fixture_clock_only=True)

        changed = deepcopy(original)
        changed['decisions'][0]['conditions'].append('Explicit same-label fixture condition.')
        changed['notices_or_consent_drafts'].append(deepcopy(changed['notices_or_consent_drafts'][0]))
        delta = downstream_diff(original, changed)
        assert not delta['status_changes'] and len(delta['decision_changes']) == 1
        assert len(delta['draft_changes'][0]['after']) == 2
        changed['decisions'][0]['status'] = 'off'
        delta = downstream_diff(original, changed)
        customer = original['decisions'][0]['customer_id']
        assert delta['changed_customer_segments']['customers'] == [customer]
        assert all(row['customer_id'] == customer for row in delta['changed_customer_segments']['rules'])
        assert all(row['customer_id'] == customer for row in delta['changed_customer_segments']['conditional_drafts'])
        changed['decisions'] = changed['decisions'][1:]
        changed['controls'] = changed['controls'][1:]
        delta = downstream_diff(original, changed)
        assert delta['status_changes'][0]['after_status'] is None
        assert delta['changed_customer_segments']['removed_rules']
        passed('status_conditions_removed_operations_and_duplicate_drafts_keep_distinct_semantics')

        remote_state = deepcopy(state)
        remote_state['config']['references'] = str(refs)
        remote_state['config']['reference_sources'] = str(root / 'remote.json')
        write(root / 'remote.json', [{'url': 'https://vendor.example/subprocessors', 'path': 'vendor/list.html'}])
        class Response:
            headers = {'ETag': 'fixture-v1'}
            url = 'https://vendor.example/subprocessors'
            def __enter__(self): return self
            def __exit__(self, *args): return None
            def read(self): return b'<p>Explicit public-source fetch fixture.</p>'
        requests = []
        def fetch(request, timeout):
            requests.append(request)
            if len(requests) == 2:
                raise HTTPError(request.full_url, 304, 'Not Modified', {}, None)
            return Response()
        with patch.object(follow, 'urlopen', side_effect=fetch):
            follow.refresh_references(remote_state)
            first_bytes = (refs / 'vendor/_sources.json').read_bytes()
            follow.refresh_references(remote_state)
            assert requests[1].get_header('If-none-match') == 'fixture-v1'
            assert (refs / 'vendor/_sources.json').read_bytes() == first_bytes
            (refs / 'vendor/list.html').unlink()
            follow.refresh_references(remote_state)
            assert requests[2].get_header('If-none-match') is None
        assert (refs / 'vendor/list.html').exists()
        write(root / 'remote.json', [{'url': 'https://vendor.example/subprocessors', 'path': '../escape.html'}])
        rejected('remote_reference_path_escape_rejected', lambda: follow.refresh_references(remote_state), 'vendor_folder')
        passed('conditional_public_reference_fetch_and_deleted_capture_recovery', mocked_https_only=True)

        class InterruptedChild:
            def __init__(self): self.terminated = False
            def communicate(self, *args, **kwargs): raise KeyboardInterrupt()
            def poll(self): return None
            def terminate(self): self.terminated = True
            def wait(self, timeout): return 0
        child = InterruptedChild()
        options = argparse.Namespace(out=root / 'cancelled-model-fixture', contracts=contracts, feature=feature,
                                     references=None, mode='kyma', effort='ultra', model='fixture-only', timeout=30)
        with patch.object(main_module, 'doctor', return_value={'codex_executable': 'fixture-codex'}), \
             patch.object(main_module.subprocess, 'Popen', return_value=child) as launch:
            try:
                main_module.analyze(options)
            except KeyboardInterrupt:
                pass
            else:
                raise AssertionError('interruption expected')
        assert child.terminated and load(options.out / 'launch.json')['status'] == 'cancelled'
        command = launch.call_args.args[0]
        assert 'forced_login_method="chatgpt"' in command
        assert all(key not in launch.call_args.kwargs['env'] for key in main_module.METERED)
        passed('interrupted_model_child_stops_and_retains_cancelled_launch', mocked_child_only=True)

    value = {'checks': checks, 'all_passed': True, 'new_model_calls': 0, 'outside_users': 0,
             'qualified_production_repeat_jobs': 0,
             'scope': 'Actual local source, CLI-library, SDK and SQLite consumers with retained model work and explicit source/clock/HTTPS fixtures. No new AI analysis, live vendor-fetch claim or natural 24-hour retention observation.'}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    write(args.out, value)
    print(json.dumps({'checks': len(checks), 'all_passed': True, 'evidence': str(args.out)}))


if __name__ == '__main__':
    main()
