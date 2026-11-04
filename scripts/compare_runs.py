#!/usr/bin/env python3
"""Compare equally capable actual AI routes without an invented accuracy score."""
import argparse
import json
from pathlib import Path


def load(path):
    return json.loads(Path(path).read_text())


def signatures(manifest):
    return {document['id']: (document['original_sha256'], document['text_sha256'])
            for customer in manifest['customers'] for document in customer['documents']}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('kyma', type=Path)
    parser.add_argument('native', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    first, second = load(args.kyma / 'launch.json'), load(args.native / 'launch.json')
    assert first['status'] == second['status'] == 'completed'
    assert first['model'] == second['model'] and first['reasoning_effort'] == second['reasoning_effort']
    assert signatures(load(args.kyma / 'source-manifest.json')) == signatures(load(args.native / 'source-manifest.json'))
    assert load(args.kyma / 'feature.json') == load(args.native / 'feature.json')
    bundles = [load(folder / 'model-decisions.json') for folder in [args.kyma, args.native]]
    maps = [{(row['customer_id'], row['operation_id']): row for row in bundle['decisions']} for bundle in bundles]
    assert set(maps[0]) == set(maps[1])
    rows = []
    for key in sorted(maps[0]):
        a, b = maps[0][key], maps[1][key]
        rows.append({'customer_id': key[0], 'operation_id': key[1], 'kyma_status': a['status'], 'native_status': b['status'],
                     'status_agrees': a['status'] == b['status'], 'kyma_rationale': a['rationale'], 'native_rationale': b['rationale']})
    value = {'model': first['model'], 'effort': first['reasoning_effort'], 'complete_original_inputs_identical': True,
             'feature_facts_identical': True, 'tool_capabilities_identical': True,
             'independent_model_threads': [first['thread_id'], second['thread_id']],
             'rows': rows, 'status_disagreements': sum(not row['status_agrees'] for row in rows),
             'kyma_source_quotes': len(bundles[0]['evidence']), 'native_source_quotes': len(bundles[1]['evidence']),
             'kyma_precedence_edges': len(bundles[0]['precedence']), 'native_precedence_edges': len(bundles[1]['precedence']),
             'kyma_engineering_outputs': len(bundles[0]['engineering_outputs']),
             'native_engineering_outputs': len(bundles[1]['engineering_outputs']),
             'accuracy_grade': None, 'lawyer_grade': None,
             'scope': 'Two actual model source-to-decision runs with equal complete inputs and tools. Agreement is not proof of legal correctness. No wrong-clearance rate or superiority follows without an independent reference.'}
    args.out.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')
    print(json.dumps({key: value[key] for key in ['complete_original_inputs_identical', 'status_disagreements', 'kyma_source_quotes', 'native_source_quotes', 'accuracy_grade']}, indent=2))


if __name__ == '__main__':
    main()
