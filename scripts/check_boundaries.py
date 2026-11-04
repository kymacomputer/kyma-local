#!/usr/bin/env python3
"""Test source, hierarchy and receiving invariants on an actual model-authored output."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import shutil

from kyma_local.tool import compile_outputs, evaluate_sdk, load, validate


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('run', type=Path)
    args = parser.parse_args()
    source = args.run.resolve()
    with tempfile.TemporaryDirectory(prefix='kyma-kit-boundaries-') as raw:
        work = Path(raw)
        for name in ['source-manifest.json', 'feature.json', 'model-decisions.json']:
            shutil.copy2(source / name, work / name)
        shutil.copytree(source / 'documents', work / 'documents')
        bundle = load(work / 'model-decisions.json')
        checks = []

        def reject(label, candidate):
            assert not (work / 'local-results.sqlite3').exists()
            try:
                validate(work, candidate)
            except AssertionError as error:
                checks.append({'case': label, 'passed': True, 'exact_error': str(error), 'zero_receiving_effect': True})
            else:
                raise AssertionError('Expected rejection: ' + label)

        value = deepcopy(bundle);value['evidence'][0]['quote'] = 'A fabricated source quote that does not exist.'
        reject('invented_quote', value)
        value = deepcopy(bundle);value['decisions'][0]['operation_id'] = 'unknown-feature-operation'
        reject('wrong_operation_identity', value)
        value = deepcopy(bundle);value['decisions'] = value['decisions'][1:]
        reject('omitted_customer_operation', value)
        value = deepcopy(bundle);extra = deepcopy(value['decisions'][0]);extra['id'] += '-duplicate';value['decisions'].append(extra)
        reject('duplicate_customer_operation_pair', value)
        value = deepcopy(bundle);value['controls'].append(deepcopy(value['controls'][0]))
        reject('duplicate_control', value)
        value = deepcopy(bundle);value['evidence'][0]['page'] = 99999
        reject('invented_pdf_page', value)
        document = load(work / 'source-manifest.json')['customers'][0]['documents'][0]
        text = work / document['text_file'];original = text.read_bytes();text.write_bytes(original + b'\nChanged.\n')
        reject('changed_source_after_model_read', bundle);text.write_bytes(original)
        first = compile_outputs(work, bundle)
        second = compile_outputs(work, bundle)
        assert first['bundle_sha256'] == second['bundle_sha256']
        import sqlite3
        with sqlite3.connect(work / 'local-results.sqlite3') as db:
            count = db.execute('SELECT count(*) FROM results').fetchone()[0]
        assert count == 1, 'same output created duplicate durable results'
        checks.append({'case': 'same_model_output_replay', 'passed': True, 'durable_results': count})
        export = {'feature_id': 'runtime-boundary-fixture', 'operations': ['own-inference'], 'rules': [
            {'customer_id': 'fixture-only', 'operation_id': 'own-inference', 'proposed_eligible': True,
             'required_facts': {'training': False, 'nested': {'enabled': False}, 'count': 7}}]}
        contexts = [
            {'customer_id': 'fixture-only', 'operation_id': 'own-inference', 'facts': {'training': False, 'nested': {'enabled': False}, 'count': 7.0}},
            {'customer_id': 'fixture-only', 'operation_id': 'own-inference', 'facts': {'training': 0, 'nested': {'enabled': False}, 'count': 7}},
            {'customer_id': 'fixture-only', 'operation_id': 'own-inference', 'facts': {'training': False, 'nested': {'enabled': 0}, 'count': 7}},
            {'customer_id': 'unknown', 'operation_id': 'own-inference', 'facts': {'training': False, 'nested': {'enabled': False}, 'count': 7}},
            {'customer_id': 'fixture-only', 'operation_id': 'own-inference', 'facts': {'nested': {'enabled': False}, 'count': 7}}]
        evaluations = evaluate_sdk(export, contexts)
        assert [row['value'] for row in evaluations] == [True, False, False, False, False]
        checks.append({'case': 'json_boolean_numeric_distinction_and_positive_control', 'passed': True,
                       'evaluations': evaluations, 'source': 'Explicit runtime fixture. No contract permission or actual customer is inferred.'})
        value = {'checks': checks, 'all_passed': all(row['passed'] for row in checks),
                 'scope': 'No additional model call. Exact source, target, population, page and replay checks on an actual model-authored result.'}
    (source / 'boundary-checks.json').write_text(json.dumps(value, indent=2) + '\n')
    print(json.dumps({'checks': len(checks), 'all_passed': value['all_passed']}))


if __name__ == '__main__':
    main()
