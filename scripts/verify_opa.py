#!/usr/bin/env python3
"""Check the generated policy through a real native OPA binary on equal contexts."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('run', type=Path)
    parser.add_argument('--opa', type=Path, required=True)
    args = parser.parse_args()
    run, opa = args.run.resolve(), args.opa.resolve()
    contexts = json.loads((run / 'evaluation-contexts.json').read_text())
    expected = json.loads((run / 'openfeature-consumer.json').read_text())['evaluations']
    rows = []
    for index, context in enumerate(contexts):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json') as file:
            json.dump(context, file);file.flush()
            result = subprocess.run([str(opa), 'eval', '--format', 'json', '--data', str(run / 'feature-policy.rego'),
                                     '--data', str(run / 'opa-data.json'), '--input', file.name, 'data.kyma.feature.enabled'],
                                    capture_output=True, text=True, timeout=20)
        assert result.returncode == 0, result.stderr
        value = json.loads(result.stdout)['result'][0]['expressions'][0]['value']
        assert value == expected[index]['value'], 'OPA and OpenFeature differ'
        rows.append({'context': context, 'opa_value': value, 'openfeature_value': expected[index]['value'], 'equal': True})
    output = {'native_opa_sha256': hashlib.sha256(opa.read_bytes()).hexdigest(),
              'evaluations': rows, 'all_equal': all(row['equal'] for row in rows),
              'scope': 'Actual local OPA and OpenFeature consumer comparison. Neither proves semantic legal correctness or outside deployment.'}
    (run / 'opa-consumer.json').write_text(json.dumps(output, indent=2) + '\n')
    print(json.dumps({'contexts': len(rows), 'all_equal': output['all_equal']}))


if __name__ == '__main__':
    main()
