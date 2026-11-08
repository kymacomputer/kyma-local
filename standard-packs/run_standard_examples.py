#!/usr/bin/env python3
import argparse
import json
from pathlib import Path

import pack
import standard_packs as s

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--out',required=True)
    a=p.parse_args()
    out=Path(a.out).resolve()
    if out.exists():
        raise ValueError('new_output_directory_required')
    cf=json.loads((pack.ROOT/'examples/csa3.facts.json').read_text())
    df=json.loads((pack.ROOT/'examples/dpa11.facts.json').read_text())
    bf=json.loads((pack.ROOT/'examples/bonterms2.facts.json').read_text())
    df.update(new_subprocessor_change=True,ccpa_permitted_law_exception=False)
    bf.update(trains_competing_third_party_model=False,falsely_claims_human=False,
              claims_provider_approval=False,appropriate_human_review=True,applicable_law_compliance=True)
    cases=[
      ('csa-service', 'csa3', {'version':'3.0','dpa_selected':False,'prohibited_data_authorized':False}, cf),
      ('csa-identified-usage', 'csa3', {'version':'3.0'},dict(cf,usage_data_nonidentifying=False)),
      ('csa-express-sensitive-data', 'csa3', {'version':'3.0','dpa_selected':True,'prohibited_data_authorized':True},cf),
      ('csa-outside-service-purpose', 'csa3', {'version':'3.0'},dict(cf,necessary_to_provide_or_maintain_product=False)),
      ('csa-custom-order', 'csa3', {'version':'3.0','custom_text':'An Order Form changes the permitted data uses.'},cf),
      ('dpa-new-unapproved', 'dpa11', {'version':'1.1','customer_role':'controller'},df),
      ('dpa-affirmative-approval', 'dpa11', {'version':'1.1','customer_role':'controller'},dict(df,subprocessor_approval_state='approved')),
      ('dpa-ten-business-not-thirty', 'dpa11', {'version':'1.1'},dict(df,notice_business_days=10,notice_calendar_days=14)),
      ('dpa-deemed-acceptance', 'dpa11', {'version':'1.1'},dict(df,notice_business_days=20,notice_calendar_days=30)),
      ('dpa-objection', 'dpa11', {'version':'1.1'},dict(df,subprocessor_approval_state='objected',notice_business_days=20,notice_calendar_days=30)),
      ('dpa-customer-is-processor', 'dpa11', {'version':'1.1','customer_role':'processor'},df),
      ('dpa-missing-annex', 'dpa11', {'version':'1.1'},dict(df,within_annex_scope=None)),
      ('dpa-omitted-variable', 'dpa11', {'version':'1.1','omitted_variables':['Approved Subprocessors']},df),
      ('dpa-selected-ccpa', 'dpa11', {'version':'1.1','ccpa_service_provider_selected':True},df),
      ('bonterms-default', 'bonterms2', {'version':'2.0'},bf),
      ('bonterms-customer-training', 'bonterms2', {'version':'2.0','training_exception':'customer_only'},dict(bf,solely_customer_training=True)),
      ('bonterms-deidentified-aggregated', 'bonterms2', {'version':'2.0','training_exception':'deidentified_aggregated'},dict(bf,training_deidentified_all_persons=True,training_aggregated_across_customers=True)),
      ('bonterms-aggregation-missing', 'bonterms2', {'version':'2.0','training_exception':'deidentified_aggregated'},dict(bf,training_deidentified_all_persons=True)),
      ('bonterms-shared-retrieval', 'bonterms2', {'version':'2.0'},dict(bf,no_cross_customer_context=False)),
      ('bonterms-false-provider-approval', 'bonterms2', {'version':'2.0'},dict(bf,claims_provider_approval=True)),
      ('bonterms-retention-expired', 'bonterms2', {'version':'2.0'},dict(bf,monitoring_days=31)),
      ('bonterms-selected-seven-days', 'bonterms2', {'version':'2.0','retention_days':7},dict(bf,monitoring_days=8)),
      ('bonterms-fixed-notice', 'bonterms2', {'version':'2.0','minimum_feature_notice_days':30},dict(bf,feature_notice_days=10)),
      ('bonterms-notice-and-no-optout', 'bonterms2', {'version':'2.0','minimum_feature_notice_days':30},dict(bf,feature_notice_days=10,new_feature_admin_disable=False)),
      ('bonterms-provider-clock', 'bonterms2', {'version':'2.0','minimum_provider_notice_days':30},dict(bf,provider_notice_days=10)),
      ('bonterms-narrow-monitoring', 'bonterms2', {'version':'2.0','narrow_monitoring':True},dict(bf,monitoring_purpose='malfunction')),
      ('bonterms-custom-indemnity', 'bonterms2', {'version':'2.0','custom_text':'Additional Terms change Output Claims liability.'},bf),
      ('bonterms-non-generative', 'bonterms2', {'version':'2.0'},dict(bf,generative_feature=False))]
    rows=[]
    for name,kind,c,f in cases:
        pack.write(out/'inputs'/(name+'.choices.json'),c)
        pack.write(out/'inputs'/(name+'.facts.json'),f)
        result=s.run(kind,c,f,out/name)
        rows.append(dict(name=name,paper=kind,cells=len(result),consumer=name+'/CONSUMER.json',
                         scoped_statuses={r['operation_id']:r['scoped_status'] for r in result}))
    pack.write(out/'INDEX.json',dict(schema='kyma-current-standard-example-index/v1',
        hypothetical_unsigned_cases=True,model_activity='Finite replay of current Codex interpretation. No model invocation.',
        source_versions={'csa':'3.0','dpa':'1.1','bonterms_ai':'2.0'},scenarios=rows,
        scenarios_count=len(rows),clause_cells=sum(x['cells'] for x in rows),outside_use=False))
    print(json.dumps(dict(out=str(out),scenarios=len(rows),cells=sum(x['cells'] for x in rows))))

if __name__=='__main__':
    main()
