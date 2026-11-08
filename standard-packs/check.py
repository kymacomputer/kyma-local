#!/usr/bin/env python3
"""Exercise every supplied case and the actual native receiving boundary."""
import argparse
import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

import pack
import prepare_actual
import standard_packs
from kyma_local.agent_workflow import read_contract_result, read_contract_source
from kyma_local.tool import validate


def negative_controls(work):
    bundle = json.loads((work / 'model-decisions.json').read_text())
    changes = []
    value = copy.deepcopy(bundle)
    value['evidence'][0]['quote'] = 'THIS QUOTATION IS ABSENT FROM THE SOURCE.'
    changes.append(('invented-quotation', value, 'quote_not_in_source'))
    value = copy.deepcopy(bundle)
    value['controls'][0]['proposed_eligible'] = True
    value['decisions'][0]['status'] = 'live_with_conditions'
    changes.append(('unknown-prerequisite-enabled', value, 'unresolved_fact_cannot_be_enabled'))
    value = copy.deepcopy(bundle)
    value['decisions'].pop()
    value['controls'].pop()
    changes.append(('missing-operation', value, 'incomplete_customer_operation_population'))
    results = []
    for name, changed, signature in changes:
        try:
            validate(work, changed)
        except (ValueError, AssertionError) as error:
            if signature not in str(error):
                raise
            results.append(dict(name=name, rejected=True, signature=str(error)))
        else:
            raise AssertionError('negative_control_accepted:' + name)
    with tempfile.TemporaryDirectory(prefix='kyma-source-control-') as temporary:
        changed_work = Path(temporary) / 'changed'
        shutil.copytree(work, changed_work)
        manifest = json.loads((changed_work / 'source-manifest.json').read_text())
        document = changed_work / manifest['customers'][0]['documents'][0]['text_file']
        document.write_text(document.read_text() + '\nUNAUTHORIZED CHANGE\n')
        try:
            validate(changed_work, bundle)
        except (ValueError, AssertionError) as error:
            if 'source_hash_changed' not in str(error):
                raise
            results.append(dict(name='changed-source', rejected=True, signature=str(error)))
        else:
            raise AssertionError('changed_source_accepted')
    return results


def check(out):
    if out.exists():
        raise ValueError('new_output_directory_required')
    out.mkdir(parents=True)
    standard_packs.verify_pins()
    suite = unittest.defaultTestLoader.discover(str(pack.ROOT), pattern='test_*.py')
    outcome = unittest.TextTestRunner(verbosity=1).run(suite)
    if not outcome.wasSuccessful():
        raise AssertionError('semantic_controls_failed')
    for script, folder in [('run_examples.py', 'ai'), ('run_standard_examples.py', 'extended')]:
        subprocess.run([sys.executable, str(pack.ROOT / script), '--out', str(out / folder)], check=True)
    cases = []
    for folder in [out / 'ai', out / 'extended']:
        index = json.loads((folder / 'INDEX.json').read_text())
        for scenario in index['scenarios']:
            case = folder / scenario['name']
            result = read_contract_result(str(case / 'native-runtime'))
            if not result['durable_result_exact'] or result['receiver_rows'] != 1:
                raise AssertionError('native_receiver_mismatch:' + scenario['name'])
            if any(row['value'] is not False for row in result['fresh_sdk_evaluations']):
                raise AssertionError('unsigned_example_enabled:' + scenario['name'])
            cases.append(dict(case=scenario['name'], decisions=len(result['stored_result']['bundle']['decisions']),
                              sdk_evaluations=len(result['fresh_sdk_evaluations']), receiver_rows=1))
    if len(cases) != 44:
        raise AssertionError('complete_example_population_required')
    contracts = out / 'preparation-inputs' / 'contracts' / 'synthetic-customer'
    contracts.mkdir(parents=True)
    (contracts / 'amendment.txt').write_text(
        'SYNTHETIC TEST ONLY. No real parties, signature or adoption.\n'
        'This amendment prohibits Input and Output use for system improvement.\n')
    feature = out / 'preparation-inputs' / 'feature.json'
    pack.write(feature, dict(id='private-amendment-test', name='Synthetic amendment review',
                            operations=[dict(id='system-improvement', actor='Provider', data='Input and Output',
                                             purpose='Improve the AI System', model='Synthetic AI System')]))
    prepared = out / 'actual-route-preparation'
    job = prepare_actual.prepare(str(contracts.parent), str(feature), str(prepared),
                                 ['common-ai1', 'csa3', 'dpa11', 'bonterms2'])
    sources = [read_contract_source(str(prepared / 'native-runtime'), source['id']) for source in job['sources']]
    manifest = json.loads((prepared / 'native-runtime/source-manifest.json').read_text())
    if len(manifest['customers']) != 1 or len(manifest['reference_sets']) != 5 or len(sources) != 9:
        raise AssertionError('customer_reference_population_confused')
    negatives = negative_controls(out / 'ai' / 'no-training' / 'native-runtime')
    consumer = dict(schema='kyma-standard-pack-consumer/v2', semantic_controls=outcome.testsRun,
                    cases=len(cases), decisions=sum(row['decisions'] for row in cases),
                    sdk_evaluations=sum(row['sdk_evaluations'] for row in cases),
                    all_native_receivers_exact=True, all_unsigned_flags_disabled=True,
                    negative_controls=negatives, native_cases=cases,
                    actual_route_preparation=dict(customer_groups=1, reference_sets=5, source_reads=len(sources),
                                                  assessment_submitted=False, original_source_is_synthetic=True),
                    new_model_call=False, outside_use=False, legal_clearance=False)
    pack.write(out / 'CONSUMER.json', consumer)
    return consumer


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    result = check(args.out.resolve())
    print(json.dumps({key: result[key] for key in ['cases', 'decisions', 'sdk_evaluations', 'all_native_receivers_exact']}))


if __name__ == '__main__':
    main()
