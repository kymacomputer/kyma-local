#!/usr/bin/env python3
"""Run explicit hypothetical choices through the isolated native receiver."""
import argparse
import copy
import json
from pathlib import Path

import pack

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--out', required=True)
    a = p.parse_args()
    out = Path(a.out).resolve()
    if out.exists():
        raise ValueError('new_output_root_required')
    f = json.loads((pack.ROOT / 'examples/facts.json').read_text())
    base = pack.default_cover()
    choices = {
      'no-training': ({'training_data':['none'],'training_purposes':['none']}, {}),
      'shared-training': ({'training_data':['input'],'training_purposes':['ai_services']}, {}),
      'input-includes-prompts': ({'training_data':['input'],'training_purposes':['ai_services']}, {'training_data_class':'user_prompts_only'}),
      'customer-only-rejects-shared-training': ({'training_data':['input'],'training_purposes':['solely_customer_benefit']}, {}),
      'customer-only-permits-customer-training': ({'training_data':['input'],'training_purposes':['solely_customer_benefit']}, {'training_benefit':'solely_customer'}),
      'exact-data-category': ({'training_data':['user_prompts_only'],'training_purposes':['ai_services']}, {}),
      'deidentified-requires-result': ({'training_data':['input'],'training_purposes':['ai_services'],'training_restrictions':['deidentified']}, {'commercially_reasonable_deidentification_performed':True}),
      'efforts-is-distinct': ({'training_data':['input'],'training_purposes':['ai_services'],'training_restrictions':['commercially_reasonable_deidentification']}, {'commercially_reasonable_deidentification_performed':True,'deidentified_training_data':False}),
      'aggregated-and-deidentified': ({'training_data':['input'],'training_purposes':['ai_services'],'training_restrictions':['aggregated','deidentified']}, {'aggregated_training_data':True,'deidentified_training_data':True}),
      'customer-only-improvement': ({'improvement_restrictions':['solely_customer_benefit']}, {}),
      'no-customer-identification': ({'improvement_restrictions':['no_customer_identification']}, {'identifies_customer':True}),
      'model-change-is-training': ({}, {'improves_model':True}),
      'proper-human-oversight': ({}, {'proper_human_oversight':True,'falsely_claims_human':False}),
      'selected-indemnities': ({'provider_covered_claims':True,'customer_covered_claims':True}, {}),
      'missing-selected-aup': ({'ai_aup_selected':True}, {}),
      'custom-amendment': ({'custom_text':'Input and Output shall not support system improvement.'}, {})}
    index = []
    for name, (delta, fact_delta) in choices.items():
        c = copy.deepcopy(base)
        c.update(delta)
        facts = dict(f, **fact_delta)
        pack.write(out / 'inputs' / (name + '.cover.json'), c)
        pack.write(out / 'inputs' / (name + '.facts.json'), facts)
        matrix = pack.run(c, facts, out / name)
        index.append(dict(name=name, consumer=str((out/name/'CONSUMER.json').relative_to(out)),
                          scoped_statuses={r['operation_id']:r['scoped_status'] for r in matrix}))
    pack.write(out / 'INDEX.json', dict(hypothetical_unsigned_cases=True, scenarios=index,
        cases=len(index), matrix_cells=len(index)*len(pack.OPERATIONS),
        native_runtime_commit=pack.verify_sources()['runtime_commit'],
        model_activity='Deterministic replay of the interpretation authored by the current Codex agent. No new model call.',
        limitations='No actual customer agreement, clearance, outside use, or live feature change.'))
    print(json.dumps(dict(out=str(out), cases=len(index), cells=len(index)*len(pack.OPERATIONS))))

if __name__ == '__main__':
    main()
