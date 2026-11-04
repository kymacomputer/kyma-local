"""Explicit local observation and opt-in job evidence. No service or Kai timer is installed."""
from argparse import Namespace
from datetime import date, datetime, timezone
import fcntl
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import time
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from uuid import uuid4

from .tool import canonical, load
from .watch import verify_previous


def now():
    return datetime.now(timezone.utc).isoformat()


def save(path, value):
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')
    os.replace(temporary, path)


def tree(root):
    if root is None:
        return []
    assert root.is_dir(), 'source_folder_missing: ' + str(root)
    rows = []
    for path in sorted(root.rglob('*')):
        assert not path.is_symlink(), 'source_symlinks_not_supported: ' + str(path)
        if path.is_file() and path.name != '.DS_Store':
            rows.append([path.relative_to(root).as_posix(), sha256(path.read_bytes()).hexdigest()])
    return rows


def fingerprint(config):
    value = {'contracts': tree(Path(config['contracts'])),
             'references': tree(Path(config['references'])) if config['references'] else [],
             'feature': sha256(canonical(load(config['feature']))).hexdigest()}
    return sha256(canonical(value)).hexdigest()


def input_identity(work):
    manifest = load(work / 'source-manifest.json')
    value = {'customers': sorted((d['original_relative_path'], d['original_sha256'])
                                for g in manifest['customers'] for d in g['documents']),
             'references': sorted((d['original_relative_path'], d['original_sha256'])
                                  for g in manifest.get('reference_sets', []) for d in g['documents']),
             'feature': load(work / 'feature.json')}
    return sha256(canonical(value)).hexdigest()


def refresh_references(state):
    """Fetch only explicitly configured public source URLs, never customer contract text."""
    config = state['config']
    if not config['reference_sources']:
        return
    rows = load(config['reference_sources'])
    assert isinstance(rows, list), 'reference_sources_must_be_a_list'
    assert len({row['path'] for row in rows}) == len(rows), 'duplicate_remote_reference_destination'
    assert len({row['url'] for row in rows}) == len(rows), 'duplicate_remote_reference_url'
    assert config['references'], 'reference_folder_required_for_remote_sources'
    root = Path(config['references'])
    for row in rows:
        parsed = urlparse(row['url'])
        assert parsed.scheme == 'https' and parsed.hostname and not parsed.username and not parsed.password, 'public_https_source_required'
        assert not parsed.fragment, 'source_url_fragment_not_supported'
        relative = Path(row['path'])
        assert not relative.is_absolute() and '..' not in relative.parts and len(relative.parts) >= 2, 'reference_path_requires_vendor_folder'
        assert relative.suffix.lower() in {'.html', '.htm', '.txt', '.md', '.pdf', '.docx'}, 'unsupported_remote_reference_type'
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        assert not target.is_symlink() and root.resolve() in target.resolve().parents, 'reference_destination_outside_folder'
        retained = state.setdefault('remote_sources', {}).get(row['url'], {})
        headers = {'User-Agent': 'Kyma-Local/0.4 public-source-observer'}
        # A local edit or deletion invalidates the conditional request validator.
        current_hash = sha256(target.read_bytes()).hexdigest() if target.exists() else None
        if current_hash == retained.get('sha256'):
            if retained.get('etag'):
                headers['If-None-Match'] = retained['etag']
            if retained.get('last_modified'):
                headers['If-Modified-Since'] = retained['last_modified']
        try:
            with urlopen(Request(row['url'], headers=headers), timeout=30) as response:
                assert urlparse(response.url).scheme == 'https', 'source_redirect_requires_https'
                body = response.read()
                remote = {'url': row['url'], 'final_url': response.url, 'retrieved_at_utc': now(),
                          'etag': response.headers.get('ETag'), 'last_modified': response.headers.get('Last-Modified'),
                          'sha256': sha256(body).hexdigest(), 'bytes': len(body)}
        except HTTPError as error:
            if error.code == 304 and current_hash and current_hash == retained.get('sha256'):
                continue
            raise
        state['remote_sources'][row['url']] = remote
        if current_hash == remote['sha256']:
            continue
        temporary = target.with_name(target.name + '.download')
        temporary.write_bytes(body)
        os.replace(temporary, target)
        provenance_path = target.parent / '_sources.json'
        provenance = load(provenance_path) if provenance_path.exists() else {}
        provenance[target.name] = remote
        save(provenance_path, provenance)


def snapshot(config, destination, expected):
    destination.mkdir(parents=True, exist_ok=False)
    shutil.copytree(config['contracts'], destination / 'contracts')
    if config['references']:
        shutil.copytree(config['references'], destination / 'references')
    shutil.copy2(config['feature'], destination / 'feature.json')
    copied = {**config, 'contracts': str(destination / 'contracts'), 'feature': str(destination / 'feature.json'),
              'references': str(destination / 'references') if config['references'] else None}
    assert fingerprint(copied) == expected == fingerprint(config), 'sources_changed_during_snapshot'
    return copied


def verified_job(work):
    receipt = verify_previous(work)
    event = load(work / 'change-summary.json') if (work / 'change-summary.json').exists() else None
    if event:
        read = load(work / 'revision-receiving-readback.json')
        assert event in read['events'], 'revision_receiving_read_required'
        assert event['after_bundle_sha256'] == receipt['bundle_sha256'], 'revision_bundle_mismatch'
    return receipt, event


def finish_pending(state):
    pending = state.get('pending')
    if not pending:
        return False
    work = Path(pending['work'])
    # Preparation or compilation alone cannot count as a completed useful job.
    read = 'agent-receiving-readback.json' if (work / 'agent-job.json').exists() else 'model-receiving-readback.json'
    if not (work / read).exists():
        return False
    receipt, event = verified_job(work)
    assert event, 'revision_event_required'
    identity = input_identity(work)
    state['jobs'].append({'job_id': event['event_sha256'], 'input_identity': identity,
                          'distinct_input': identity not in {row['input_identity'] for row in state['jobs']},
                          'bundle_sha256': receipt['bundle_sha256'], 'completed_at_utc': now(),
                          'work': str(work), 'trigger': 'source_change',
                          'automatic_completion': pending['automatic_completion'],
                          'downstream_delta_counts': {key: len(event.get(key, [])) for key in [
                              'status_changes', 'decision_changes', 'control_changes', 'engineering_changes', 'draft_changes']},
                          'useful_self_report': None, 'consumer_verified': True})
    state['before'] = str(work)
    state['fingerprint'] = pending['fingerprint']
    state['pending'] = None
    state['failed'] = None
    return True


def activity(state, notes=None):
    state = json.loads(json.dumps(state))
    for job in state['jobs']:
        if notes and job['job_id'] in notes:
            job['useful_self_report'] = notes[job['job_id']]
    first = state['jobs'][0]
    first_clock = datetime.fromisoformat(first['completed_at_utc'])
    repeat = []
    for job in state['jobs'][1:]:
        elapsed = (datetime.fromisoformat(job['completed_at_utc']) - first_clock).total_seconds()
        useful_delta = any(job['downstream_delta_counts'].values())
        if (elapsed >= 86400 and job['distinct_input'] and job['automatic_completion'] and useful_delta
                and job['useful_self_report'] and first['useful_self_report']):
            repeat.append(job['job_id'])
    return {'install_id': state['install_id'], 'next_natural_event': state['next_natural_event'],
            'completed_jobs': len(state['jobs']), 'jobs': state['jobs'], 'pending': state.get('pending'),
            'qualified_local_repeat_job_ids': repeat,
            'evidence_scope': 'Local consumer verification and explicit local usefulness reports. No outside-user identity or independent retention attestation.',
            'telemetry_sent': False, 'background_service_installed': False,
            'observation_scope': 'Only this foreground process observes changes. It stops when the process or host stops.'}


def initialize(args, root):
    assert args.opt_in, 'Use --opt-in to create a local observer and activity record.'
    assert args.next_event and args.event_date, 'next_natural_event_and_date_required'
    assert args.before and args.contracts and args.feature, 'first_observer_requires_before_contracts_and_feature'
    date.fromisoformat(args.event_date)
    config = {'contracts': str(args.contracts.resolve()), 'feature': str(args.feature.resolve()),
              'references': str(args.references.resolve()) if args.references else None,
              'reference_sources': str(args.reference_sources.resolve()) if args.reference_sources else None,
              'prepare_only': args.prepare_only, 'mode': args.mode, 'model': args.model,
              'effort': args.effort, 'timeout': args.timeout}
    for source in [config['contracts'], config['references']]:
        if source:
            assert Path(source) != root and Path(source) not in root.parents, 'observer_output_must_be_outside_source_folders'
    before = args.before.resolve()
    receipt, _ = verified_job(before)
    return {'schema': 'kyma-local-observer/v1', 'install_id': str(uuid4()), 'created_at_utc': now(),
            'config': config, 'before': str(before), 'fingerprint': None, 'pending': None, 'failed': None,
            'next_natural_event': {'description': args.next_event, 'date': args.event_date, 'source': 'user_supplied'},
            'jobs': [{'job_id': receipt['bundle_sha256'], 'input_identity': input_identity(before),
                      'bundle_sha256': receipt['bundle_sha256'], 'work': str(before), 'completed_at_utc': now(),
                      'clock_source': 'first_observed_at_opt_in', 'trigger': 'first_value_registration',
                      'automatic_completion': False, 'distinct_input': True, 'consumer_verified': True,
                      'useful_self_report': args.first_value_note, 'downstream_delta_counts': {}}]}


def tick(state, root, settle_seconds=2, run_update=None, automatic_trigger=True):
    completed = finish_pending(state)
    if completed:
        save(root / 'observer.json', state)
    if state.get('pending'):
        return {'status': 'awaiting_current_job', 'pending': state['pending'], 'actual_model_invocation': False}
    refresh_references(state)
    current = fingerprint(state['config'])
    if current == state['fingerprint']:
        if completed:
            return {'status': 'job_completed', 'job': state['jobs'][-1], 'actual_model_invocation': False}
        return {'status': 'unchanged', 'actual_model_invocation': False}
    if (state.get('failed') or {}).get('fingerprint') == current:
        return {'status': 'previous_attempt_failed', 'failure': state['failed'], 'actual_model_invocation': False}
    if settle_seconds:
        time.sleep(settle_seconds)
    if fingerprint(state['config']) != current:
        return {'status': 'inputs_not_stable', 'actual_model_invocation': False}
    job = root / 'jobs' / str(uuid4())
    job.parent.mkdir(parents=True, exist_ok=True)
    captured = snapshot(state['config'], job / 'input', current)
    work = job / 'assessment'
    pending = {'work': str(work), 'fingerprint': current,
               'automatic_completion': (automatic_trigger and not state['config']['prepare_only']
                                        and current != state.get('prompted_retry_fingerprint')),
               'observed_at_utc': now()}
    state['pending'] = pending
    save(root / 'observer.json', state)
    try:
        if state['config']['prepare_only']:
            from .agent_workflow import prepare_revision_job
            result = prepare_revision_job(state['before'], captured['contracts'], captured['feature'], str(work), captured['references'])
        else:
            from .watch import update
            config = state['config']
            args = Namespace(before=Path(state['before']), contracts=Path(captured['contracts']),
                             feature=Path(captured['feature']), references=Path(captured['references']) if captured['references'] else None,
                             reference_baseline=None, out=work, mode=config['mode'], model=config['model'],
                             effort=config['effort'], timeout=config['timeout'])
            result = (run_update or update)(args)
        if result['status'] == 'unchanged':
            state['fingerprint'] = current
            state['pending'] = None
            state['failed'] = None
        elif result['status'] != 'prepared':
            assert finish_pending(state), 'completed_job_without_verified_receiver'
        save(root / 'observer.json', state)
        value = {'status': result['status'], 'work': str(work),
                 'actual_model_invocation_by_observer': not state['config']['prepare_only'] and result['status'] != 'unchanged'}
        if result['status'] == 'prepared':
            value['next_action'] = 'Read the complete prepared job: kyma-local-agent job --work ' + str(work)
        elif result['status'] == 'reassessed':
            value['job'] = state['jobs'][-1]
        return value
    except Exception as error:
        # Preserve the exact failed job and input. An unchanged failure never spawns model retries.
        state['failed'] = {'fingerprint': current, 'work': str(work), 'error_type': type(error).__name__,
                           'error': str(error), 'observed_at_utc': now()}
        state['pending'] = None
        save(root / 'observer.json', state)
        raise


def run(args):
    root = args.out.resolve()
    root.mkdir(parents=True, exist_ok=True)
    with (root / '.observer.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError('This observer already has a foreground owner.') from error
        path = root / 'observer.json'
        state = load(path) if path.exists() else initialize(args, root)
        assert state['schema'] == 'kyma-local-observer/v1', 'observer_schema_mismatch'
        if args.retry_failed:
            state['prompted_retry_fingerprint'] = (state.get('failed') or state.get('pending') or {}).get('fingerprint')
            if state.get('pending'):
                launch_path = Path(state['pending']['work']) / 'launch.json'
                assert launch_path.exists() and load(launch_path)['status'] in {'failed', 'timeout', 'cancelled'}, 'pending_job_has_no_terminal_failure'
                state['pending'] = None
            state['failed'] = None
        save(path, state)
        last_status = None
        while True:
            try:
                result = tick(state, root, args.settle_seconds, automatic_trigger=not args.once)
                save(path, state)
                status = result['status']
                if status not in {'unchanged', 'awaiting_current_job', 'previous_attempt_failed'} or status != last_status:
                    print(json.dumps(result, ensure_ascii=False), flush=True)
                last_status = status
            except KeyboardInterrupt:
                return {'status': 'stopped', **activity(state, local_notes(root))}
            if args.once:
                return activity(state, local_notes(root))
            try:
                time.sleep(args.poll_seconds)
            except KeyboardInterrupt:
                return {'status': 'stopped', **activity(state, local_notes(root))}


def local_notes(root):
    path = root / 'usefulness.json'
    return load(path) if path.exists() else {}


def report(args):
    root = args.out.resolve()
    # A usefulness statement can arrive while the observer owns its foreground loop.
    # Notes have a separate atomic writer; they never replace the observer snapshot.
    with (root / '.activity.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        state = load(root / 'observer.json')
        notes = local_notes(root)
        if args.confirm_job:
            assert args.useful_note, 'usefulness_note_required'
            matches = [row for row in state['jobs'] if row['job_id'] == args.confirm_job]
            assert len(matches) == 1, 'completed_job_identity_required'
            notes[args.confirm_job] = {'note': args.useful_note, 'recorded_at_utc': now(), 'source': 'local_user_statement'}
            save(root / 'usefulness.json', notes)
        return activity(state, notes)
