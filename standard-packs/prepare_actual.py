#!/usr/bin/env python3
"""Prepare complete actual sources plus typed standard references for this agent.

This command never supplies a customer assessment or invokes a model. The host's
current model must interpret the complete returned corpus under the native schema.
"""
import argparse
import json
from pathlib import Path
import shutil

import pack
import standard_packs
from kyma_local.agent_workflow import prepare_contract_job

GUIDE = '''# Source-bound standard references

This is a model-authored interpretation guide, not a signed agreement or authority.
Read every complete customer source before selection. Match the exact incorporated
source version. A newer public standard does not amend an older signed agreement.
Resolve the actual Cover Page, definitions, scope, execution, amendments, AUP,
supplier list and feature facts. A filename or default fixture is insufficient.

Common Paper AI Addendum1.0 separates Model training1.3 from AI System improvement1.4.
Selected Training Data and Training Purposes jointly matter. Customer-only use,
aggregation, de-identification and commercially reasonable efforts are distinct.
Preserve optional Covered Claims and every exclusion. Output ownership does not
prove protectability, uniqueness, noninfringement or an indemnity.

Common Paper CSA3.0 removed its prior default machine-learning clause. Compare
Customer Content1.5, Usage Data/Feedback1.4, their definitions, confidentiality10,
GDPR DPA3.1, Prohibited Data3.2 and all actual Cover Page changes. Do not infer a
general training grant or prohibition from an old version or an improvement label.

Common Paper DPA1.1 includes a Cover Page omission rule. Resolve its exact scope.
Match AnnexI(B) and documented processing instructions. Keep Subprocessor approval,
10 business days prior notice and30 calendar days objection/deemed acceptance
distinct. Actual approval, objection, flowdown and notice facts need evidence.
SCC ModuleTwo/Three depends on the actual customer role, not a vendor title.
Referenced SCCs, UK Addendum and completed Annexes remain necessary sources.

Bonterms AI Addendum2.0 defaults to no Input/Output Model training. Operational
monitoring is a separate bounded exception. It requires a specific allowed purpose,
logical separation, need-to-know access, deletion and its retention/exception rules.
Per-customer retrieval isolation applies even without Model weight updates.
New AI Features require the stated prior notice, administrator opt-out and retained
core non-AI functionality. The default does not require30 days notice. A selected
Additional Term can change that duration. Main Agreement definitions control
equivalent terms. Additional Terms can override the Addendum in their actual scope.
The published playbook contains alternatives, not adopted modifications. Preserve
all copyright indemnity exclusions and the actual cap relationship.

Use independent judgment. These finite examples cannot interpret arbitrary private
amendments. Source quotation proves provenance, not legal correctness or clearance.
Keep source omissions and actual uncertainty explicit in the native assessment.
Submit the model's complete assessment through the unchanged current-agent tools,
then read the real local receiver. No account, notice or customer effect follows.
'''

def prepare(contracts, feature, out, papers):
    standard_packs.verify_pins()
    out=Path(out).resolve()
    if out.exists():
        raise ValueError('new_output_directory_required')
    refs=out/'pack-references'
    selected=[]
    for name in papers:
        if name=='common-ai1':
            selected.append((name,['ai-standalone.docx','ai-in-app.docx'],
                             'https://commonpaper.com/standards/ai-addendum/1.0/'))
        else:
            entry=standard_packs.PAPERS[name]
            selected.append((name,entry['files'],entry['url']))
    for name,files,url in selected:
        folder=refs/name
        folder.mkdir(parents=True)
        records=[]
        for source in files:
            shutil.copy2(pack.ROOT/'originals'/source,folder/source)
            records.append(dict(standard_packs.source_record(source,url),source_class='official_companion_examples' if source=='additional-terms-examples.txt' else 'official_standard_reference',
                scope='Pinned public standard or recorded source transformation. Not evidence of customer adoption. Match the exact incorporated version.'))
        pack.write(folder/'_sources.json',records)
    guide=refs/'model-interpretation-guide'
    guide.mkdir(parents=True)
    (guide/'GUIDE.md').write_text(GUIDE)
    pack.write(guide/'_sources.json',[dict(file='GUIDE.md',source_class='model_authored_reference',
        scope='Current Codex interpretation. Independently evaluate against complete actual contracts. It creates no authority, factual attestation or signed term.')])
    job=prepare_contract_job(str(Path(contracts).resolve()),str(Path(feature).resolve()),str(out/'native-runtime'),str(refs))
    pack.write(out/'PREPARED-JOB.json',job)
    manifest=json.loads((out/'native-runtime/source-manifest.json').read_text())
    pack.write(out/'PREPARATION-CONSUMER.json',dict(prepared_only=True,model_call=False,
        customer_count=len(manifest['customers']),reference_set_count=len(manifest['reference_sets']),
        standard_reference_is_customer=False,assessment_submitted=False,consumer_result_committed=False,
        source_manifest_sha256=pack.digest(out/'native-runtime/source-manifest.json'),
        next='The current host agent reads every returned source, authors the native schema, submits and reads the exact result.'))
    return job

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--contracts',required=True)
    p.add_argument('--feature',required=True)
    p.add_argument('--out',required=True)
    p.add_argument('--papers',nargs='+',choices=['common-ai1']+sorted(standard_packs.PAPERS),required=True)
    a=p.parse_args()
    job=prepare(a.contracts,a.feature,a.out,a.papers)
    print(json.dumps(dict(out=a.out,sources=len(job['sources']),prepared_only=True,new_model_call=False)))

if __name__=='__main__':
    main()
