#!/usr/bin/env python3
"""Current-model interpretations for three current standard-paper families.

The finite cases are demonstrations, not an interpreter for arbitrary text.
Every native job reads the pinned sources, preserves gaps, and disables customer flags.
"""
import argparse
import json
from pathlib import Path
import shutil

import pack
from kyma_local.agent_workflow import prepare_contract_job, read_contract_source, submit_contract_assessment, read_contract_result

PAPERS = {
 'csa3': dict(title='Common Paper CSA3.0', version='3.0', files=['csa-current-cover-and-terms.docx'],
   url='https://commonpaper.com/standards/cloud-service-agreement/3.0/', license='CC BY4.0'),
 'dpa11': dict(title='Common Paper DPA1.1', version='1.1', files=['dpa-current-cover-and-terms.docx','csa-current-cover-and-terms.docx'],
   url='https://commonpaper.com/standards/data-processing-agreement/1.1/', license='CC BY4.0'),
 'bonterms2': dict(title='Bonterms AI Addendum2.0 Signable', version='2.0', files=['bonterms-ai-v2-signable.txt','additional-terms-examples.txt'],
   url='https://bonterms.com/standard/ai-addendum-v2-signable-version', license='Standard terms CC BY4.0. Additional Terms text CC0 with recorded attribution removal. No sponsor or endorsement claim.')}

def source_record(name,fallback_url):
    for item in json.loads((pack.ROOT/'SOURCE-PINS.json').read_text())['files']:
        if Path(item['path']).name==name:
            return dict(item,file=name,source_class='official_companion_examples' if name=='additional-terms-examples.txt' else 'official_public_standard_form',
                scope='Pinned public standard or explicit source derivative. A companion example or public template does not prove actual adoption.')
    raise ValueError('exact_acquisition_receipt_required:'+name)

def require(facts, names):
    if any(facts.get(n) is False for n in names):
        return 'off'
    if any(facts.get(n) is not True for n in names):
        return 'unresolved'
    return 'live_with_conditions'

def joint(*statuses):
    """A curable timing gap cannot erase an independently observed violation."""
    order={'live_with_conditions':0,'live_after_notice':1,'unresolved':2,'needs_consent':3,'off':4}
    return max(statuses,key=order.__getitem__)

def notice_status(value):
    return 'live_with_conditions' if value is True else 'live_after_notice' if value is False else 'unresolved'

def row(op, status, reason, anchor, condition, extra=None):
    return dict(operation_id=op, scoped_status=status, rationale=reason, quote_anchor=anchor,
                condition=condition, source_file=extra)

def assess(kind, choices, facts):
    pack.validate_facts(facts)
    if kind not in PAPERS or choices.get('version') != PAPERS[kind]['version']:
        raise ValueError('exact_paper_version_required')
    allowed={'csa3':{'version','custom_text','dpa_selected','prohibited_data_authorized'},
             'dpa11':{'version','custom_text','customer_role','ccpa_service_provider_selected','omitted_variables'},
             'bonterms2':{'version','custom_text','training_exception','retention_days','narrow_monitoring',
                          'minimum_feature_notice_days','minimum_provider_notice_days'}}[kind]
    if not set(choices)<=allowed:
        raise ValueError('unsupported_choice_requires_current_agent:'+','.join(sorted(set(choices)-allowed)))
    for key in ['dpa_selected','prohibited_data_authorized','ccpa_service_provider_selected','narrow_monitoring']:
        if key in choices and choices[key] is not None and type(choices[key]) is not bool:
            raise ValueError('literal_boolean_choice_required:'+key)
    if kind=='dpa11' and choices.get('customer_role') not in {None,'controller','processor'}:
        raise ValueError('source_defined_customer_role_required')
    if kind=='dpa11' and choices.get('omitted_variables'):
        if not isinstance(choices['omitted_variables'],list) or not all(isinstance(x,str) and x for x in choices['omitted_variables']):
            raise ValueError('exact_omitted_variable_names_required')
        baseline=assess(kind,{k:v for k,v in choices.items() if k!='omitted_variables'},facts)
        for item in baseline:
            item.update(scoped_status='unresolved',rationale='DPA1.1 Cover Page omission rule needs exact clause-level interpretation for: '+', '.join(choices['omitted_variables'])+'. Do not erase or assume an obligation from a generic blank-field default.')
        return baseline
    if choices.get('custom_text'):
        baseline=assess(kind,dict(choices,custom_text=''),facts)
        for item in baseline:
            item.update(scoped_status='unresolved',rationale='Custom terms require complete current-agent interpretation. Read every Additional Term, amendment and incorporated document.')
        return baseline
    if kind == 'csa3':
        disclosure = require(facts, ['usage_data_aggregated','usage_data_nonidentifying'])
        content = require(facts, ['necessary_to_provide_or_maintain_product'])
        gdpr = facts.get('gdpr_personal_data')
        personal = ('unresolved' if gdpr is None else 'live_with_conditions' if gdpr is False else
                    'live_with_conditions' if choices.get('dpa_selected') is True else
                    'off' if choices.get('dpa_selected') is False else 'unresolved')
        prohibited = ('live_with_conditions' if choices.get('prohibited_data_authorized') is True else
                      'off' if choices.get('prohibited_data_authorized') is False else 'unresolved')
        return [
          row('service-content-use',content,'Customer Content purpose stays bounded by1.5. A generic improvement label does not expand it.',
              'Customer Content.  Provider may copy, display, modify, and use Customer Content',
              'Use only as needed to provide and maintain the Product and related offerings.'),
          row('usage-data-external-disclosure',disclosure,'External Usage Data disclosure requires both aggregation and no identification of Customer or Users.',
              'Feedback and Usage Data.','Both aggregation and non-identification must hold. Preserve the Usage Data definition.'),
          row('general-model-training-content','unresolved','CSA3.0 has no former default machine-learning clause. The actual purpose, data definition and any AI Addendum must establish this proposed training route.',
              'Customer Content.  Provider may copy, display, modify, and use Customer Content',
              'Do not import the removed prior-version clause or treat absent AI language as unlimited permission.'),
          row('gdpr-personal-data-submission',personal,'Section3.1 requires a DPA before GDPR Personal Data submission and gives it Personal Data priority.',
              'Personal Data.  Before submitting Personal Data governed by GDPR',
              'Review the actual incorporated DPA and applicable source facts before submission.'),
          row('prohibited-data-submission',prohibited,'Section3.2 permits otherwise Prohibited Data only when the actual Order Form or Key Terms authorizes it.',
              'Prohibited Data.  Customer will not',
              'Match the source definition and exact scoped authorization. No general data-category waiver follows.'),
          row('confidential-contractor-transfer',require(facts,['recipient_need_to_know','recipient_equivalent_confidentiality']),
              'Section10.4 requires need to know, protective confidentiality duties and continuing Recipient responsibility.',
              'Permitted Disclosures.','Preserve all10.4 conditions and every narrower data-purpose obligation.')]
    if kind == 'dpa11':
        approval = facts.get('subprocessor_approval_state')
        if approval == 'approved':
            sub = require(facts,['subprocessor_written_flowdown'])
            if facts.get('new_subprocessor_change') is True:
                bd=facts.get('notice_business_days')
                sub=joint(sub,'live_after_notice' if type(bd) is int and bd<10 else
                          'live_with_conditions' if type(bd) is int else 'unresolved')
            elif facts.get('new_subprocessor_change') is not False:
                sub=joint(sub,'unresolved')
        elif approval == 'objected':
            sub = 'needs_consent'
        elif approval == 'not_approved':
            bd, cd = facts.get('notice_business_days'), facts.get('notice_calendar_days')
            if type(bd) is int and type(cd) is int and bd >= 10 and cd >= 30 and facts.get('customer_objected') is False:
                sub = require(facts,['subprocessor_written_flowdown'])
            else:
                sub = 'needs_consent'
        else:
            sub = 'unresolved'
        role = choices.get('customer_role')
        module = 'Module Two' if role == 'controller' else 'Module Three' if role == 'processor' else 'unresolved module'
        return [
          row('subprocessor-content-transfer',sub,'Approval, prior10-business-day notice and the separate30-day objection/deemed-acceptance mechanism remain distinct. An objection needs resolution.',
              'Provider will not provide, transfer, or hand over any Customer Personal Data to a Subprocessor',
              'Match approved identity, country, anticipated task and actual contract. Apply written flowdown and GDPR obligations.'),
          row('processing-purpose',require(facts,['within_documented_instructions','within_annex_scope']),
              'Annex scope and documented instructions jointly constrain the AI operation. A broad CSA use right cannot erase them.',
              'Processing Instructions.','Match the full AnnexI(B), instructions, actual actor and purpose.'),
          row('feature-annex-change','live_after_notice' if facts.get('annex_update_notice_given') is False else
              'live_with_conditions' if facts.get('annex_update_notice_given') is True else 'unresolved',
              'Section2.3 allows needed listed Annex updates for Service changes through notice. This is not authority to rewrite all contractual purposes.',
              'Processing by Provider.','Identify the actual feature change and notify Customer of applicable listed Annex changes.'),
          row('restricted-transfer','unresolved',module + ' follows the stated customer role. Actual territory, applicable law, safeguard, complete Annexes, EEA SCCs and UK Addendum remain necessary.',
              'Ex-EEA Transfers.','Do not turn a module-selection example into a current-law or completed-transfer attestation.'),
          row('delete-personal-data','live_with_conditions',
              'Customer deletion instructions apply as soon as reasonably practicable, subject to legally required storage. Expiration has a separate return/delete regime.',
              'Deletion by Customer.','Implement applicable instructions, actual lawful-retention exceptions and continuing protection. Do not promise immediate deletion in every case.'),
          row('ccpa-service-provider-reuse','off' if choices.get('ccpa_service_provider_selected') is True and facts.get('independent_reuse') is True and facts.get('ccpa_permitted_law_exception') is False else 'unresolved',
              'The optional Cover Page service-provider clause adds sale/share and purpose limits when selected. It is not a GDPR-only blanket grant or proof of overall CCPA compliance.',
              '[    ]To the extent California Consumer Privacy Act,','Read the exact selected clause, purpose and permitted-law exception.')]
    if choices.get('training_exception','none') not in {'none','customer_only','deidentified_aggregated'}:
        raise ValueError('unsupported_training_exception_requires_current_agent')
    days = choices.get('retention_days',30)
    if type(days) is not int or days < 0:
        raise ValueError('literal_nonnegative_retention_days_required')
    exception = choices.get('training_exception','none')
    training = ('off' if exception == 'none' else
                require(facts,['solely_customer_training']) if exception == 'customer_only' else
                require(facts,['training_deidentified_all_persons','training_aggregated_across_customers']))
    monitor = require(facts,['monitoring_data_separated','monitoring_need_to_know','automatic_deletion'])
    if facts.get('monitoring_purpose') not in {'abuse','misuse','security','malfunction','abnormal_performance'}:
        monitor = joint(monitor,'off' if facts.get('monitoring_purpose') else 'unresolved')
    if choices.get('narrow_monitoring') is True and facts.get('monitoring_purpose') in {'malfunction','abnormal_performance'}:
        monitor = 'off'
    actual_days = facts.get('monitoring_days')
    if type(actual_days) is int and actual_days < 0:
        raise ValueError('nonnegative_monitoring_days_required')
    if type(actual_days) is not int:
        monitor = joint(monitor,'unresolved')
    elif actual_days > days:
        monitor = joint(monitor,'unresolved' if facts.get('ongoing_specific_investigation_or_legal_exception') is True else 'off')
    new_feature = joint(require(facts,['new_feature_admin_disable','core_non_ai_preserved']),notice_status(facts.get('new_feature_prior_notice')))
    if choices.get('minimum_feature_notice_days') is not None:
        n = choices['minimum_feature_notice_days']
        if type(n) is not int or n != 30:
            raise ValueError('exact_published_feature_notice_example_is_30_days_other_text_needs_agent')
        if type(facts.get('feature_notice_days')) is not int:
            new_feature = joint(new_feature,'unresolved')
        elif facts['feature_notice_days'] < n:
            new_feature = joint(new_feature,'live_after_notice')
    provider = joint(require(facts,['model_provider_list_current','model_provider_flowdown']),notice_status(facts.get('provider_notice_before_change')))
    if choices.get('minimum_provider_notice_days') is not None:
        n = choices['minimum_provider_notice_days']
        if type(n) is not int or n < 0:
            raise ValueError('literal_provider_notice_days_required')
        if type(facts.get('provider_notice_days')) is not int:
            provider = joint(provider,'unresolved')
        elif facts['provider_notice_days'] < n:
            provider = joint(provider,'live_after_notice')
    r = [
      row('model-training',training,'The default prohibits Input/Output training. Only the specifically selected exact Additional Terms example changes this row.',
          'No Training.','Match any training definition, exact exception and no-private-amendment assumption.'),
      row('operational-monitoring',monitor,'The operational exception has a bounded purpose, retention and safeguards. It does not authorize training or general product development.',
          '(a) Purpose. Notwithstanding Section 3.1','Preserve logical separation, need-to-know access, automatic deletion and exact investigation/law exceptions.'),
      row('tenant-retrieval',require(facts,['retrieval_per_customer','no_cross_customer_context']),
          'Caching, indexing and retrieval must stay logically separated per customer. A no-training claim alone does not establish this condition.',
          '(a) Tenant Isolation.','Reject a shared customer-content retrieval pool, even without weight updates.'),
      row('transient-inference',require(facts,['inference_transient_or_customer_elected']),
          'Real-time execution and filtering retain no content beyond the interaction, except3.2 monitoring or Customer election through administrative controls.',
          '(b) Ephemeral Processing.','Match the actual retention route. Preserve the monitoring and Customer-election exceptions.'),
      row('new-feature-default-enable',new_feature,
          'The default requires reasonable prior notice, an administrator disable route and preserved core non-AI functionality. It does not create a default30-day clock.',
          '(a) Notice.','Apply a fixed notice duration only when the exact Additional Terms selects one.'),
      row('model-provider-change',provider,
          'The list, prior notice and material data-handling flowdown apply. No direct Model Provider agreement is required unless the Main Agreement expressly says otherwise.',
          'Model Providers. Customer acknowledges','Preserve8.1–8.6, all actual Model Provider obligations and the applicable AUP.'),
      row('output-copyright-indemnity','unresolved',
          'The default covers copyright, preserves all5.2 and Main Agreement exclusions, and applies the general cap under5.3. Other IP claims are distinct.',
          'Copyright Indemnity.','Read Main Agreement definitions, procedures, cap and any Additional Terms before a claim assessment.'),
      row('customer-competing-model-training','off' if facts.get('trains_competing_third_party_model') is True else
          'live_with_conditions' if facts.get('trains_competing_third_party_model') is False else 'unresolved',
          'Section7(a) separately restricts Customer use for competing third-party models. Provider training rights under3.1 address a different actor.',
          '(a) train, retrain or fine-tune any third-party','Match the Customer actor and actual competing third-party model. Review the remaining Main Agreement and use restrictions.'),
      row('human-attribution','off' if facts.get('falsely_claims_human') is True else
          'live_with_conditions' if facts.get('falsely_claims_human') is False else 'unresolved',
          'Customer may not represent Output as wholly human-generated.',
          '(c) represent any Output as being a wholly human-generated work','Preserve the separate Provider-approval restriction.'),
      row('provider-approval-attribution','off' if facts.get('claims_provider_approval') is True else
          'live_with_conditions' if facts.get('claims_provider_approval') is False else 'unresolved',
          'Customer may not represent Output as approved or vetted by Provider. A truthful AI-authorship statement cannot satisfy this separate restriction.',
          '(b) represent any Output as being approved or vetted by Provider',
          'Check the actual Provider-approval representation independently of human authorship.'),
      row('significant-automated-decision',require(facts,['appropriate_human_review','applicable_law_compliance']),
          'Customer significant-effect automated decisions require appropriate human review and compliance with applicable law. Human review alone does not establish legal compliance.',
          '(d) make automated decisions','Read the exact use, applicable legal source, AUP and any high-risk classification disclosure.'),
      row('output-use','live_with_conditions',
          'Customer owns Output between the parties under4.2, with no transfer of Provider Cloud Service IP, uniqueness promise or guaranteed protectability.',
          '(a) Customer owns Output.','Preserve4.2(b)–(c),6.2 review duties and the actual Main Agreement.')]
    if facts.get('generative_feature') is not True:
        for item in r:
            item.update(scoped_status='unresolved', rationale='The default AI Features definition excludes solely non-generative classification, ranking and analysis. Establish scope from the Main Agreement and actual feature.')
    return r

def actor(kind,operation,choices):
    if kind=='csa3':
        return {'service-content-use':'Provider as the limited Customer Content licensee under1.5.',
                'usage-data-external-disclosure':'Provider as collector and external discloser of source-defined Usage Data.',
                'general-model-training-content':'Provider as proposed general-purpose Model trainer using Customer Content.',
                'gdpr-personal-data-submission':'Customer and its Users submit Personal Data to Provider.',
                'prohibited-data-submission':'Customer and its Users submit source-defined Prohibited Data.',
                'confidential-contractor-transfer':'The Recipient party discloses the other party’s Confidential Information to a need-to-know contractor.'}[operation]
    if kind=='dpa11':
        role='Processor' if choices.get('customer_role')=='controller' else 'Subprocessor' if choices.get('customer_role')=='processor' else 'Processor or Subprocessor, subject to the actual Customer role'
        if operation=='restricted-transfer':
            return 'Customer as data exporter and Provider as data importer under the actual Annex and applicable SCC module.'
        return 'Provider as '+role+', subject to Customer’s documented instructions and the exact cited provision.'
    return 'Customer and its authorized third parties as users of AI Features or Output.' if operation in {
        'customer-competing-model-training','human-attribution','provider-approval-attribution','significant-automated-decision','output-use'} else 'Provider as the AI Features operator and contracting party responsible for its Model Providers.'

def verify_pins():
    pins = json.loads((pack.ROOT/'EXTENDED-SOURCE-PINS.json').read_text())
    for item in pins['files']:
        if pack.digest(pack.ROOT/item['path']) != item['sha256']:
            raise ValueError('source_bytes_changed:' + item['path'])
    pack.verify_sources()
    return pins

def run(kind, choices, facts, out):
    pins = verify_pins()
    results = assess(kind, choices, facts)
    paper = PAPERS[kind]
    out = Path(out).resolve()
    if out.exists():
        raise ValueError('new_output_directory_required')
    case = out/'inputs/contracts/standard-paper-example'
    case.mkdir(parents=True)
    for name in paper['files']:
        shutil.copy2(pack.ROOT/'originals'/name,case/name)
    (case/'hypothetical-choices.txt').write_text('UNSIGNED HYPOTHETICAL CHOICES. No actual party, adoption, execution or customer clearance.\n'+json.dumps(choices,indent=2))
    records=[source_record(name,paper['url']) for name in paper['files']]
    records.append(dict(file='hypothetical-choices.txt',source_class='hypothetical_fixture',scope='Authored unsigned scenario. No human fact, actual party, signature or adoption.'))
    pack.write(case/'_sources.json',records)
    feature = dict(id=kind+'-paper-example',name=paper['title']+' bounded AI-operation examples',
       input_status='Public unsigned template. Deterministic replay of the current model interpretation, not a new model job.',
       operations=[dict(id=r['operation_id'],actor=actor(kind,r['operation_id'],choices),
          data='Exact source-defined data and roles',purpose=r['condition'],model='Hypothetical source-defined AI or processor function',
          proposed_facts=facts) for r in results])
    pack.write(out/'inputs/feature.json',feature)
    work=out/'native-runtime'
    job=prepare_contract_job(str(case.parent),str(out/'inputs/feature.json'),str(work))
    sources={x['id']:read_contract_source(str(work),x['id']) for x in job['sources']}
    pack.write(out/'complete-runtime-source-read.json',sources)
    evidence=[]
    for n,r in enumerate(results):
        match=[(docid,s) for docid,s in sources.items() if r['quote_anchor'] in s['text']]
        if not match:
            raise ValueError('source_anchor_absent:'+r['quote_anchor'])
        docid,source=match[0]
        quote=next(line for line in source['text'].splitlines() if r['quote_anchor'] in line)
        evidence.append(dict(id='E'+str(n),document_id=docid,section=r['operation_id'],page=None,
          quote=quote,supports=r['rationale']))
    choice_id=next(docid for docid in sources if docid.endswith('hypothetical-choices.txt'))
    evidence.append(dict(id='Echoices',document_id=choice_id,section='Exact hypothetical choices',page=None,
        quote=sources[choice_id]['text'],supports='These explicit unsigned choices select only the stated demonstration branch.'))
    # Complete pinned source text remains with the consumer. These extra units keep
    # exception, role, definition, precedence and form choices beside the decisions.
    for docid,source in sources.items():
        if docid.endswith('hypothetical-choices.txt'):
            continue
        for line in source['text'].splitlines():
            if not line.strip():
                continue
            if any(word in line for word in ['Definitions.','Conflicts Between Documents','If there is any inconsistency',
                 'Order of Precedence.','AI Addendum Controls.','Exclusions.', '(a) failing to use',
                 '(b) providing infringing','(c) modifying Output','Liability Cap.','Main Agreement Unmodified',
                 'No Output Indemnity','“AI Features” means','“Retention Period” means',
                 '“Customer Content” means','“Usage Data” means','“Prohibited Data” means',
                 '“Customer Personal Data” means','[ drafting note:','[Drafting note:',
                 '(b) Safeguards.','No Direct Pass-Through.','Model Provider Obligations.',
                 'Customer Benefit Training Exception','De-Identified and Aggregated Training Exception',
                 'Notwithstanding Section 3.1, Provider may','Provider will give Customer at least 30',
                 'Provider will maintain a current list of Model Providers','“Training” means','"Training" means']):
                evidence.append(dict(id='EX'+str(len(evidence)),document_id=docid,section='Preserved exception, definition, Cover Page or precedence',page=None,
                    quote=line,supports='Retain this source boundary. Its presence does not establish adoption or override.'))
    decisions=[];controls=[];unknowns=[]
    for n,r in enumerate(results):
        did='D'+str(n);uid='U'+str(n)
        evidence_ids=['E'+str(n),'Echoices']
        if kind=='bonterms2' and r['operation_id']=='model-training' and choices.get('training_exception','none')!='none':
            evidence_ids.extend(e['id'] for e in evidence if 'Notwithstanding Section 3.1, Provider may' in e['quote'] or '"Training" means' in e['quote'])
        unknowns.append(dict(id=uid,customer_id='standard-paper-example',
          description='The executed Main Agreement, actual Cover Page, all private amendments, incorporated policies and actual feature facts are outside this unsigned public-paper example.',
          resolution='Use the current agent on the complete actual source set. Match the exact source version and every applicable cover choice.',evidence_ids=evidence_ids))
        decisions.append(dict(id=did,customer_id='standard-paper-example',operation_id=r['operation_id'],status='unresolved',
          actor=actor(kind,r['operation_id'],choices),data='Source-defined data with actual classification and custody required',
          purpose=r['condition'],model='Hypothetical source-defined function. No actual deployment or vendor engagement inferred.',
          feature=feature['name'],conditions=[r['condition']],rationale='Clause-only '+r['scoped_status']+': '+r['rationale'],
          evidence_ids=evidence_ids,unknown_ids=[uid]))
        controls.append(dict(decision_id=did,customer_id='standard-paper-example',operation_id=r['operation_id'],proposed_eligible=False,
          required_facts={'actual_complete_source_set_reviewed':True},reason='An unsigned standard-paper fixture cannot enable a customer operation.'))
    bundle=dict(assessment_type='proposed_source_bound_decisions',feature_id=feature['id'],
      summary=paper['title']+' source-bound clause matrix with exact current source versions and complete source gaps.',
      evidence=evidence,precedence=[],decisions=decisions,unknowns=unknowns,controls=controls,
      engineering_outputs=[dict(id='ENG1',title=paper['title']+' operation-specific implementation',
         body='\n'.join(r['operation_id']+': '+r['condition']+' '+r['rationale'] for r in results),
         acceptance_criteria='Each named operation passes its clause-specific controls. Unknown source versions, omitted policies, custom amendments and absent feature facts cannot enable customer flags.',
         decision_ids=[d['id'] for d in decisions])],notices_or_consent_drafts=[])
    submitted=submit_contract_assessment(str(work),bundle)
    readback=read_contract_result(str(work))
    pack.write(out/'cover-choice-matrix.json',results)
    pack.write(out/'native-submit.json',submitted)
    pack.write(out/'native-consumer.json',readback)
    pack.write(out/'CONSUMER.json',dict(paper=paper['title'],version=paper['version'],unsigned_hypothetical=True,
       source_bytes_exact=True,full_source_text_with_recorded_transformations=True,finite_current_model_replay=True,new_model_call=False,
       native_decisions=len(decisions),source_quotes=len(evidence),actual_sdk_evaluations=len(readback['fresh_sdk_evaluations']),
       native_receiver_rows=readback['receiver_rows'],durable_result_exact=readback['durable_result_exact'],
       all_customer_flags_disabled=all(x['value'] is False for x in readback['fresh_sdk_evaluations']),
       customer_clearance=False,outside_use=False,source_pins=pins))
    return results

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--paper',choices=sorted(PAPERS),required=True)
    p.add_argument('--choices',required=True)
    p.add_argument('--facts',required=True)
    p.add_argument('--out',required=True)
    a=p.parse_args()
    rows=run(a.paper,json.loads(Path(a.choices).read_text()),json.loads(Path(a.facts).read_text()),a.out)
    print(json.dumps(dict(out=a.out,decisions=len(rows),paper=PAPERS[a.paper]['title'])))

if __name__=='__main__':
    main()
