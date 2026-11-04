#!/usr/bin/env python3
"""Build a portable kit without credentials, unrelated owner memory or private model events."""
import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import zipfile


def digest(value):
    return hashlib.sha256(value).hexdigest()


def source_paths(kit):
    kit = Path(kit).resolve()
    if (kit / '.git').exists():
        result = subprocess.run(['git', '-C', str(kit), 'ls-files', '--cached', '-z'],
                                capture_output=True, check=True)
        names = [name for name in result.stdout.decode().split('\0') if name]
        selection = 'tracked_git_source'
    else:
        manifest = json.loads((kit / 'PACKAGE-MANIFEST.json').read_text())
        names = [row['path'] for row in manifest['files']]
        selection = 'portable_source_manifest'
    paths = []
    for name in names:
        relative = Path(name)
        if relative.is_absolute() or '..' in relative.parts:
            raise ValueError('Unsafe release source path: ' + name)
        path = kit / relative
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(kit):
            raise ValueError('Release source must be a regular file inside the kit: ' + name)
        paths.append(path)
    return sorted(set(paths)), selection


def shareable_trace(raw):
    rows, exclusions = [], []
    for event in map(json.loads, raw.decode().splitlines()):
        value = deepcopy(event)
        item = value.get('item') or {}
        if item.get('type') == 'reasoning':
            continue
        if item.get('type') == 'command_execution':
            command = item.get('command', '')
            if any(pattern in command for pattern in ['/.claude/', '/.codex/', '/methods/']):
                if 'aggregated_output' in item:
                    output = item.pop('aggregated_output')
                    item['output_excluded'] = {
                        'reason': 'Existing owner instructions or unrelated private memory. No source-decision tool output is removed.',
                        'bytes': len(output.encode()), 'sha256': digest(output.encode())}
                if item.get('output_excluded'):
                    exclusions.append({'item_id': item.get('id'), **item['output_excluded']})
        rows.append(value)
    return (''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in rows).encode(), exclusions)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('kit', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    kit = args.kit.resolve()
    paths, selection = source_paths(kit)
    bodies, exclusions = {}, {}
    for path in sorted(paths):
        relative = path.relative_to(kit)
        if path.name in {'events.private.jsonl', 'stderr.private.txt', 'PACKAGE-MANIFEST.json'} or path.suffix == '.pyc':
            continue
        data = path.read_bytes()
        if path.name == 'observable-transcript.jsonl':
            data, excluded = shareable_trace(data)
            exclusions[str(relative)] = excluded
        bodies[str(relative)] = data
    privacy = {'created_at_utc': datetime.now(timezone.utc).isoformat(),
               'source_selection': selection,
               'untracked_local_files_included': False,
               'omitted_private_files': ['events.private.jsonl', 'stderr.private.txt'],
               'private_model_reasoning_included': False, 'credentials_included': False,
               'unrelated_owner_instruction_or_memory_outputs': exclusions,
               'scope': 'Complete public task input, model-authored results and actual task-tool outputs remain. Private instruction read outputs retain hashes and exact command metadata only. Full private event originals remain with the owner.'}
    bodies['evidence/package-custody.json'] = (json.dumps(privacy, indent=2) + '\n').encode()
    manifest = {'schema': 'kyma-local-kit-files/v1', 'files': [
        {'path': path, 'bytes': len(data), 'sha256': digest(data)} for path, data in sorted(bodies.items())],
        'scope': 'Exact portable package contents. No outside user or customer deployment is inferred.'}
    bodies['PACKAGE-MANIFEST.json'] = (json.dumps(manifest, indent=2) + '\n').encode()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(args.out, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path, data in sorted(bodies.items()):
            info = zipfile.ZipInfo('kyma-local/' + path, date_time=(2026, 11, 4, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, data)
    receipt = {'path': str(args.out.resolve()), 'bytes': args.out.stat().st_size,
               'sha256': digest(args.out.read_bytes()), 'files': len(bodies),
               'manifest_sha256': digest(bodies['PACKAGE-MANIFEST.json']),
               'task_trace_excluded_output_blocks': sum(len(rows) for rows in exclusions.values())}
    print(json.dumps(receipt, indent=2))


if __name__ == '__main__':
    main()
