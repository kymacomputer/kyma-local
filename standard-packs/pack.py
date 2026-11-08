#!/usr/bin/env python3
"""Replay a source-bound AI Addendum interpretation through unchanged Kyma Local.

The current Codex agent authored the finite interpretation below after reading
the complete official terms and both Cover Pages. This is not a new model call,
legal clearance, or a parser for private agreements. Custom text goes to an agent.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parent
RUNTIME = ROOT.parent
sys.path.insert(0, str(RUNTIME / 'src'))
from kyma_local.agent_workflow import prepare_contract_job, read_contract_source, submit_contract_assessment, read_contract_result

DATA = {'usage_data', 'feedback', 'input', 'output', 'user_prompts_only', 'customer_content'}
PURPOSES = {'solely_customer_benefit', 'ai_services'}
TRAINING = {'aggregated', 'deidentified', 'commercially_reasonable_deidentification'}
IMPROVEMENT = {'no_customer_identification', 'solely_customer_benefit'}
OPERATIONS = {
    'service_inference': ('1.1', 'Use Input only as necessary to provide the described AI Services.'),
    'model_training': ('1.3', 'Match selected Training Data and Training Purposes. Apply every selected Training Restriction.'),
    'system_improvement': ('1.4', 'Exclude changes to Models. Apply every selected Improvement Restriction.'),
    'regulated_decision': ('1.2', 'Require proper human oversight and review under applicable laws and professional rules.'),
    'human_attribution': ('1.2', 'Do not falsely state that AI Output was created by a human.'),
    'output_ownership': ('2.1', 'Customer ownership is between the parties, subject to applicable law and the nature-of-AI disclaimer.'),
    'output_indemnity': ('3.2', 'A selected Cover Page indemnity has its exact exclusions and underlying procedure. Ownership alone supplies no noninfringement warranty.'),
    'input_indemnity': ('2.3', 'A selected Customer Covered Claim addresses Input rights or Customer use violations, subject to the exact underlying procedure and exclusions.'),
    'acceptable_use': ('1.2', 'Match the selected AI Acceptable Use Policy and the Agreement restrictions. An absent optional AI policy does not erase underlying restrictions.')
}
ACTORS = {
    'service_inference':'Customer submits Input and uses AI Services. Provider processes Input as needed to provide them.',
    'model_training':'Provider trains Models using the specifically selected Training Data and Training Purposes.',
    'system_improvement':'Provider improves the AI System, excluding underlying Models unless the separate Training grant permits them.',
    'regulated_decision':'Customer and anyone it permits to use AI Services for regulated decisions.',
    'human_attribution':'Customer and anyone it permits to describe AI Output authorship.',
    'output_ownership':'Customer retains Input and owns Output between the parties. Provider assigns its rights to the extent permitted by Applicable Laws.',
    'output_indemnity':'Provider as potential Indemnifying Party for selected Provider Covered Claims. Customer as Protected Party.',
    'input_indemnity':'Customer as potential Indemnifying Party for selected Customer Covered Claims. Provider as Protected Party.',
    'acceptable_use':'Customer and anyone it permits to use the AI Services under the selected AUP and Agreement restrictions.'}

def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def write(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')

def default_cover():
    return dict(version='1.0', training_data=[], training_purposes=[],
                training_restrictions=[], improvement_restrictions=[],
                provider_covered_claims=False, customer_covered_claims=False,
                ai_aup_selected=False, ai_aup_supplied=False, custom_text='',
                underlying_agreement_supplied=False, private_amendments_reviewed=False)

def validate_cover(cover):
    expected = set(default_cover())
    if set(cover) != expected:
        raise ValueError('exact_cover_fields_required:' + ','.join(sorted(expected ^ set(cover))))
    if cover['version'] != '1.0':
        raise ValueError('unsupported_source_version')
    for field, allowed in [('training_data', DATA), ('training_purposes', PURPOSES),
                           ('training_restrictions', TRAINING), ('improvement_restrictions', IMPROVEMENT)]:
        if not isinstance(cover[field], list) or len(cover[field]) != len(set(cover[field])):
            raise ValueError('unique_choice_list_required:' + field)
        if not set(cover[field]) <= allowed | {'none'}:
            raise ValueError('unknown_cover_choice:' + field)
        if 'none' in cover[field] and len(cover[field]) > 1:
            raise ValueError('conflicting_none_and_selected_choice:' + field)
    if len(cover['training_purposes']) > 1:
        raise ValueError('conflicting_customer_only_and_shared_training_purposes')
    for field in ['provider_covered_claims', 'customer_covered_claims', 'ai_aup_selected',
                  'ai_aup_supplied', 'underlying_agreement_supplied', 'private_amendments_reviewed']:
        if type(cover[field]) is not bool:
            raise ValueError('boolean_required:' + field)
    if not isinstance(cover['custom_text'], str):
        raise ValueError('custom_text_string_required')
    if cover['underlying_agreement_supplied'] or cover['private_amendments_reviewed']:
        raise ValueError('actual_source_completeness_requires_current_agent_job_not_a_cover_boolean')
    if cover['ai_aup_supplied']:
        raise ValueError('actual_aup_interpretation_requires_current_agent_source_not_a_cover_boolean')
    return cover

def interpret(cover, facts):
    """Finite model-authored interpretation. No arbitrary contract interpretation."""
    validate_cover(cover)
    validate_facts(facts)
    gaps = []
    if not cover['underlying_agreement_supplied']:
        gaps.append('Underlying signed CSA or Software License Agreement, its Cover Page and incorporated documents are absent.')
    if not cover['private_amendments_reviewed']:
        gaps.append('Private amendments and actual execution or incorporation remain outside this public-paper example.')
    if cover['ai_aup_selected'] and not cover['ai_aup_supplied']:
        gaps.append('Selected AI Acceptable Use Policy is absent.')
    if cover['custom_text']:
        gaps.append('Custom Cover Page or amendment text needs complete current-agent interpretation: ' + cover['custom_text'])
    rows = []
    for op, (section, condition) in OPERATIONS.items():
        status, reason = 'live_with_conditions', condition
        if cover['custom_text']:
            status, reason = 'unresolved', 'Custom text may change this provision. Read it with the complete agreement.'
        elif op == 'model_training':
            data = set(cover['training_data']) - {'none'}
            purposes = set(cover['training_purposes']) - {'none'}
            actual_class=facts.get('training_data_class')
            if not actual_class:
                status, reason = 'unresolved', 'Identify the actual training data class before applying the Input/Output rule or a selected grant.'
            elif actual_class in {'feedback','usage_data','customer_content'} and (not data or not purposes or actual_class not in data):
                status, reason = 'unresolved', 'Section1.3 expressly bars unselected Input/Output training. Input excludes Feedback. Resolve the actual data definition and any distinct underlying grant before a wider training conclusion.'
            elif not data or not purposes:
                status, reason = 'off', 'No joint selection of Training Data and Training Purposes. Section1.3 supplies no Input/Output training grant.'
            elif actual_class not in data and not (actual_class == 'user_prompts_only' and 'input' in data):
                status, reason = ('unresolved' if not facts.get('training_data_class') else 'off'), 'The proposed training data class must match the exact Cover Page selection.'
            elif 'solely_customer_benefit' in purposes and 'ai_services' not in purposes and facts.get('training_benefit') != 'solely_customer':
                status, reason = ('unresolved' if not facts.get('training_benefit') else 'off'), 'The selected customer-only purpose does not cover a shared-benefit Model.'
            else:
                reason += ' Selected restrictions: ' + ', '.join(cover['training_restrictions']) + '.'
                required = {'aggregated':'aggregated_training_data', 'deidentified':'deidentified_training_data',
                            'commercially_reasonable_deidentification':'commercially_reasonable_deidentification_performed'}
                unmet = [(choice, facts.get(required[choice])) for choice in cover['training_restrictions'] if choice != 'none' and facts.get(required[choice]) is not True]
                if unmet:
                    status = 'off' if any(value is False for _, value in unmet) else 'unresolved'
                    reason = 'Selected Training Restrictions require distinct evidence: ' + ', '.join(choice for choice, _ in unmet) + '. Commercially reasonable efforts do not establish actual de-identification.'
        elif op == 'system_improvement':
            if facts.get('improves_model') is None:
                status, reason = 'unresolved', 'Establish whether the operation improves a Model or only the AI System.'
            elif facts.get('improves_model') is True:
                status, reason = 'off', 'Section1.4 excludes Model improvement. Reassess this operation as Training under1.3.'
            elif 'solely_customer_benefit' in cover['improvement_restrictions'] and facts.get('improvement_benefit') != 'solely_customer':
                status, reason = ('unresolved' if not facts.get('improvement_benefit') else 'off'), 'The selected Improvement Restriction excludes general-benefit improvement.'
            elif 'no_customer_identification' in cover['improvement_restrictions'] and facts.get('identifies_customer') is not False:
                status, reason = ('off' if facts.get('identifies_customer') is True else 'unresolved'), 'Show that neither Input nor Output identifies Customer before this restricted use.'
            else:
                reason += ' A no-training selection does not delete this distinct clause.'
        elif op == 'regulated_decision' and facts.get('proper_human_oversight') is not True:
            status, reason = ('off' if facts.get('proper_human_oversight') is False else 'unresolved'), 'The proposed regulated decision requires proper human oversight and review.'
        elif op == 'human_attribution' and facts.get('falsely_claims_human') is None:
            status, reason = 'unresolved', 'Establish the actual authorship claim before this attribution operation.'
        elif op == 'human_attribution' and facts.get('falsely_claims_human') is True:
            status, reason = 'off', 'Section1.2(c) prohibits a false human-authorship claim.'
        elif op == 'output_indemnity':
            if cover['provider_covered_claims']:
                status, reason = 'unresolved', 'The optional indemnity applies only as selected and modified. Underlying indemnity procedure, exclusions and exact claim facts need review.'
            else:
                status, reason = 'off', 'This unselected optional Cover Page indemnity supplies no AI-specific Provider Covered Claim grant. Check underlying indemnities separately.'
        elif op == 'input_indemnity':
            if cover['customer_covered_claims']:
                status, reason = 'unresolved', 'Selected Customer Covered Claims address Input rights and Customer use violations. Read the exact chosen language and underlying indemnity procedure and exclusions.'
            else:
                status, reason = 'off', 'The optional AI-specific Customer Covered Claim is unselected. Existing Agreement indemnities remain a separate question.'
        elif op == 'acceptable_use':
            status, reason = 'unresolved', ('The selected AI AUP is absent. Read its complete text and the Agreement restrictions.' if cover['ai_aup_selected'] else 'No optional AI AUP is selected. The Agreement restrictions still apply and the underlying source is absent.')
        rows.append(dict(operation_id=op, section=section, scoped_status=status,
                         scoped_rationale=reason, source_set_gaps=list(gaps),
                         overall_status='unresolved' if gaps else status,
                         condition=condition))
    return rows

def verify_sources():
    pins = json.loads((ROOT / 'SOURCE-PINS.json').read_text())
    for row in pins['files']:
        if digest(ROOT / row['path']) != row['sha256']:
            raise ValueError('source_version_or_bytes_changed:' + row['path'])
    runtime_pins=json.loads((ROOT/'RUNTIME-PINS.json').read_text())
    if runtime_pins['base_commit']!=pins['runtime_commit']:
        raise ValueError('runtime_version_changed')
    for source in runtime_pins['files']:
        if digest(RUNTIME/source['path'])!=source['sha256']:
            raise ValueError('runtime_source_changed:'+source['path'])
    actual={str(p.relative_to(RUNTIME)) for p in (RUNTIME/'src').rglob('*.py')}
    expected={x['path'] for x in runtime_pins['files'] if x['path'].startswith('src/') and x['path'].endswith('.py')}
    if actual!=expected:
        raise ValueError('runtime_source_population_changed')
    return pins


def validate_facts(facts):
    """Preserve unknown values and reject coercion into a positive predicate."""
    if not isinstance(facts, dict):
        raise ValueError('fact_object_required')
    booleans = {
        'aggregated_training_data', 'deidentified_training_data',
        'commercially_reasonable_deidentification_performed', 'improves_model',
        'identifies_customer', 'proper_human_oversight', 'falsely_claims_human',
        'claims_provider_approval', 'usage_data_aggregated', 'usage_data_nonidentifying',
        'necessary_to_provide_or_maintain_product', 'gdpr_personal_data',
        'recipient_need_to_know', 'recipient_equivalent_confidentiality',
        'subprocessor_written_flowdown', 'new_subprocessor_change', 'customer_objected',
        'within_documented_instructions', 'within_annex_scope', 'annex_update_notice_given',
        'independent_reuse', 'ccpa_permitted_law_exception', 'generative_feature',
        'solely_customer_training', 'training_deidentified_all_persons',
        'training_aggregated_across_customers', 'monitoring_data_separated',
        'monitoring_need_to_know', 'automatic_deletion',
        'ongoing_specific_investigation_or_legal_exception', 'retrieval_per_customer',
        'no_cross_customer_context', 'inference_transient_or_customer_elected',
        'new_feature_admin_disable', 'core_non_ai_preserved', 'new_feature_prior_notice',
        'model_provider_list_current', 'model_provider_flowdown',
        'provider_notice_before_change', 'trains_competing_third_party_model',
        'appropriate_human_review', 'applicable_law_compliance',
    }
    for key in booleans & facts.keys():
        if facts[key] is not None and type(facts[key]) is not bool:
            raise ValueError('literal_boolean_fact_required:' + key)
    for key in {'notice_business_days', 'notice_calendar_days', 'monitoring_days',
                'feature_notice_days', 'provider_notice_days'} & facts.keys():
        value = facts[key]
        if value is not None and (type(value) is not int or value < 0):
            raise ValueError('nonnegative_integer_fact_required:' + key)
    for key, values in {
        'training_data_class': DATA,
        'training_benefit': {'solely_customer', 'shared'},
        'improvement_benefit': {'solely_customer', 'shared'},
        'subprocessor_approval_state': {'approved', 'objected', 'not_approved'},
    }.items():
        if key in facts and facts[key] is not None and facts[key] not in values:
            raise ValueError('source_defined_fact_value_required:' + key)

def run(cover, facts, out):
    pins = verify_sources()
    rows = interpret(cover, facts)
    out = Path(out).resolve()
    if out.exists():
        raise ValueError('new_output_directory_required')
    case = out / 'inputs' / 'contracts' / 'standard-paper-example'
    case.mkdir(parents=True)
    shutil.copy2(ROOT / 'originals/ai-standalone.docx', case / 'ai-addendum-template.docx')
    selections = 'HYPOTHETICAL UNSIGNED COVER PAGE SELECTIONS. Not an actual customer contract.\n' + json.dumps(cover, indent=2)
    (case / 'selected-cover.txt').write_text(selections)
    write(case / '_sources.json', [dict(file='ai-addendum-template.docx', source_class='official_public_standard_form',
          url='https://commonpaper.com/standards/ai-addendum/1.0/cover-page-and-standard-terms-docx',
          scope='Common Paper AI Addendum v1.0, CC BY4.0. Entire Cover Page, attached Standard Terms and footer retained.'),
          dict(file='selected-cover.txt', source_class='hypothetical_fixture', scope='Explicit model test choices, unsigned, no customer identity or adoption claim.')])
    feature = dict(id='common-paper-ai-v1', name='Common Paper AI Addendum clause-bound operation examples',
                   input_status='Hypothetical source interpretation and replay. No customer legal clearance or account change.',
                   operations=[dict(id=op, actor=ACTORS[op],
                                    data='Input, Output and selected Training Data under the exact standard definitions',
                                    purpose=desc, model='Hypothetical AI Services and Models, no asserted supplier',
                                    proposed_facts=facts) for op, (_, desc) in OPERATIONS.items()])
    write(out / 'inputs' / 'feature.json', feature)
    work = out / 'native-runtime'
    job = prepare_contract_job(str(case.parent), str(out / 'inputs/feature.json'), str(work))
    write(out / 'prepared-job.json', job)
    sources = {row['id']: read_contract_source(str(work), row['id']) for row in job['sources']}
    write(out / 'complete-runtime-source-read.json', sources)
    docid = next(k for k in sources if k.endswith('ai-addendum-template.docx'))
    text = sources[docid]['text']
    # These complete paragraph quotes come from the extracted original DOCX.
    paragraphs = [line for line in text.splitlines() if line.strip()]
    starts = {'1.1':'Using AI Services.', '1.2':'Restrictions.', '1.3':'Model Training.',
              '1.4':'Non-Training Improvement.', '2.1':'Ownership.', '2.2':'Personal Data.',
              '2.3':'Rights to Input.', '3.1':'Nature of AI.', '3.2':'Similarity of Output.',
              '4.1':'"AI Addendum Standard Terms"', '4.2':'"AI Services"',
              '4.3':'"AI System"', '4.4':'"Input"', '4.5':'"Model"',
              '4.6':'"Output"', '4.7':'"Train"'}
    evidence = [dict(id='E' + sec, document_id=docid, section=sec, page=None,
                     quote=next(p for p in paragraphs if p.startswith(start)),
                     supports='Complete original clause with its conditions and exceptions.') for sec, start in starts.items()]
    cp_id = next(k for k in sources if k.endswith('selected-cover.txt'))
    evidence.append(dict(id='Ecover', document_id=cp_id, section='Hypothetical complete selections', page=None,
                         quote=selections, supports='The exact test choices, with no signature or legal-effect claim.'))
    # Retain all provider indemnity exceptions, customer indemnity and AUP text as native source evidence.
    for n, start in enumerate(['[    ]Provider Covered Claims', 'Without limiting the indemnity exclusions',
                               '[    ]Customer Covered Claims', '[    ]Use of the AI Services']):
        evidence.append(dict(id='Eoptional' + str(n), document_id=docid, section='Cover Page optional clauses', page=None,
                             quote=next(p for p in paragraphs if p.startswith(start)), supports='Optional choice and its full exception boundary.'))
    decisions, controls, unknowns = [], [], []
    for n, row in enumerate(rows):
        did = 'D' + str(n + 1)
        uids = []
        if row['source_set_gaps'] or row['scoped_status'] == 'unresolved':
            uid = 'U' + str(n + 1)
            uids.append(uid)
            unknowns.append(dict(id=uid, customer_id='standard-paper-example',
                description=' '.join(row['source_set_gaps']) or row['scoped_rationale'],
                resolution='Supply the complete executed agreement, exact Cover Page, amendments, selected AUP and actual feature facts to the current agent.', evidence_ids=['Ecover', 'E' + row['section']]))
        decisions.append(dict(id=did, customer_id='standard-paper-example', operation_id=row['operation_id'],
            status=row['overall_status'], actor=ACTORS[row['operation_id']],
            data='Input, Output and selected Training Data. Input excludes Feedback under4.4.',
            purpose=OPERATIONS[row['operation_id']][1], model='Hypothetical AI Services. Training and AI System improvement remain distinct.',
            feature=feature['name'], conditions=[row['condition']], rationale='Clause-only ' + row['scoped_status'] + ': ' + row['scoped_rationale'],
            evidence_ids=['E' + row['section'], 'Ecover', 'E2.2', 'E2.3', 'E3.1', 'E4.2', 'E4.3', 'E4.4', 'E4.5', 'E4.6', 'E4.7'] +
                         (['Eoptional2'] if row['operation_id']=='input_indemnity' else ['Eoptional3'] if row['operation_id']=='acceptable_use' else ['Eoptional0','Eoptional1'] if row['operation_id']=='output_indemnity' else []), unknown_ids=uids))
        controls.append(dict(decision_id=did, customer_id='standard-paper-example', operation_id=row['operation_id'],
            proposed_eligible=False, required_facts={'complete_source_set_reviewed':True},
            reason='A public unsigned standard-form example cannot enable a customer feature. Clause-only outcomes remain in the matrix.'))
    bundle = dict(assessment_type='proposed_source_bound_decisions', feature_id=feature['id'],
        summary='The model-authored finite pack separates training rights from non-training improvement and preserves complete Cover Page choices. Customer enablement awaits actual source review.',
        evidence=evidence, precedence=[], decisions=decisions, unknowns=unknowns, controls=controls,
        engineering_outputs=[dict(id='ENG1', title='Keep Model training separate from AI System improvement',
            body='Implement independent purpose flags. For training, match selected data category and permitted beneficiary. Enforce aggregation, de-identification and efforts obligations according to their distinct text. Route custom language to the current agent. Keep the actual feature disabled until the complete executed source set and feature facts are assessed.',
            acceptance_criteria='No-training blocks Input/Output training. It does not erase1.4. Customer-only choices reject shared-benefit use. Missing sources and custom terms never enable a flag. All output indemnity exceptions survive.',
            decision_ids=[d['id'] for d in decisions])], notices_or_consent_drafts=[])
    receipt = submit_contract_assessment(str(work), bundle)
    readback = read_contract_result(str(work))
    write(out / 'cover-choice-matrix.json', rows)
    write(out / 'source-pins.json', pins)
    write(out / 'native-submit.json', receipt)
    write(out / 'native-consumer.json', readback)
    write(out / 'CONSUMER.json', dict(source_bytes_exact=True, native_runtime_api_unchanged=True,
        hypothetical_unsigned_case=True, deterministic_replay_of_current_model_interpretation=True,
        new_model_call=False, outside_use=False, customer_clearance=False,
        matrix_cells=len(rows), native_decisions=len(decisions), native_receiver_rows=readback['receiver_rows'],
        all_native_flags_disabled=all(not x['value'] for x in readback['fresh_sdk_evaluations']),
        durable_result_exact=readback['durable_result_exact']))
    return rows

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--cover', required=True)
    p.add_argument('--facts', required=True)
    p.add_argument('--out', required=True)
    a = p.parse_args()
    rows = run(json.loads(Path(a.cover).read_text()), json.loads(Path(a.facts).read_text()), a.out)
    print(json.dumps(dict(out=a.out, cells=len(rows), source_scope='Common Paper AI Addendum1.0, selected hypothetical Cover Page, not legal clearance')))

if __name__ == '__main__':
    main()
