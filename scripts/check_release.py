"""Check the release file boundary without a model, account, or external effect."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile

from package_kit import digest, shareable_trace, source_paths


def main():
    checks = []
    packager = Path(__file__).with_name('package_kit.py')
    with tempfile.TemporaryDirectory(prefix='kyma-release-check-') as raw:
        root = Path(raw)
        kit = root / 'kit'
        kit.mkdir()
        subprocess.run(['git', 'init', '-q', str(kit)], check=True)
        (kit / 'public.txt').write_text('Public release source.\n')
        subprocess.run(['git', '-C', str(kit), 'add', 'public.txt'], check=True)
        (kit / 'my-contracts').mkdir()
        (kit / 'my-contracts/private.txt').write_text('UNTRACKED_PRIVATE_CONTRACT_CANARY')
        (kit / 'runs').mkdir()
        (kit / 'runs/private-result.json').write_text('UNTRACKED_PRIVATE_RESULT_CANARY')
        archive = root / 'release.zip'
        subprocess.run([sys.executable, str(packager), str(kit), '--out', str(archive)],
                       capture_output=True, text=True, check=True)
        with zipfile.ZipFile(archive) as bundle:
            manifest = json.loads(bundle.read('kyma-local/PACKAGE-MANIFEST.json'))
            names = {row['path'] for row in manifest['files']}
            assert names == {'public.txt', 'evidence/package-custody.json'}
            assert all(b'UNTRACKED_PRIVATE_' not in bundle.read(name) for name in bundle.namelist())
            portable = root / 'portable'
            bundle.extractall(portable)
        checks.append({'case': 'untracked_contract_and_result_absent_from_actual_archive', 'passed': True})
        portable_kit = (portable / 'kyma-local').resolve()
        paths, selection = source_paths(portable_kit)
        assert selection == 'portable_source_manifest'
        assert {str(path.relative_to(portable_kit)) for path in paths} == names
        checks.append({'case': 'portable_manifest_preserves_exact_release_population', 'passed': True})
        (kit / 'outside-link').symlink_to(kit / 'my-contracts/private.txt')
        subprocess.run(['git', '-C', str(kit), 'add', 'outside-link'], check=True)
        try:
            source_paths(kit)
        except ValueError as error:
            assert 'regular file inside the kit' in str(error)
        else:
            raise AssertionError('Tracked symlink entered the release.')
        checks.append({'case': 'tracked_symlink_rejected_before_archive', 'passed': True})
        (portable / 'kyma-local/PACKAGE-MANIFEST.json').write_text(json.dumps({'files': [{'path': '../private.txt'}]}))
        try:
            source_paths(portable / 'kyma-local')
        except ValueError as error:
            assert 'Unsafe release source path' in str(error)
        else:
            raise AssertionError('Traversal entered the release.')
        checks.append({'case': 'portable_manifest_traversal_rejected', 'passed': True})

    private = 'PRIVATE_OWNER_OUTPUT_CANARY'
    events = [
        {'item': {'id': 'start', 'type': 'command_execution', 'command': 'cat /example/.claude/notes'}},
        {'item': {'id': 'done', 'type': 'command_execution', 'command': 'cat /example/.claude/notes',
                  'aggregated_output': private}},
        {'item': {'id': 'tool', 'type': 'command_execution', 'command': 'python tool.py readback',
                  'aggregated_output': 'Complete task receiver.'}},
        {'item': {'type': 'reasoning', 'text': 'PRIVATE_REASONING_CANARY'}}]
    trace, exclusions = shareable_trace(('\n'.join(json.dumps(row) for row in events)).encode())
    assert private.encode() not in trace and b'PRIVATE_REASONING_CANARY' not in trace
    assert b'Complete task receiver.' in trace
    assert len(exclusions) == 1 and exclusions[0]['sha256'] == digest(private.encode())
    repeated, repeated_exclusions = shareable_trace(trace)
    assert repeated == trace and repeated_exclusions == exclusions
    checks.append({'case': 'private_trace_output_removed_with_exact_public_receiving_output_and_repeat', 'passed': True})
    print(json.dumps({'checks': checks, 'all_passed': True, 'new_model_invocation': False}, indent=2))


if __name__ == '__main__':
    main()
