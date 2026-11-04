"""Materialize the source-bound judgments authored for this invocation.

Evidence slices preserve the acquired original text. They do not select meaning.
This file reads only the assigned source corpus and feature fact sheet.
"""
import json
from pathlib import Path

WORK = Path(__file__).resolve().parent
manifest = json.loads((WORK / 'source-manifest.json').read_text())
feature = json.loads((WORK / 'feature.json').read_text())
docs = {d['id']: (WORK / d['text_file']).read_text()
        for customer in manifest['customers'] for d in customer['documents']}
C = 'c3-bhge:01-joint-venture-2019-06-06.html'
A = 'c3-bhge:02-first-amendment-2019-09-26.html'
B = 'c3-bhge:03-second-amendment-2020-06-01.html'
S = 'sai-esds:01-master-services-2026-03-31.html'
evidence = []


def span(identity, document, section, start, end, supports):
    text = docs[document]
    begin = text.index(start)
    stop = text.index(end, begin)
    quote = text[begin:stop].rstrip('\n')
    assert quote and quote in text
    evidence.append(dict(id=identity, document_id=document, section=section,
                         page=None, quote=quote, supports=supports))


def lines(identity, section, first, last, supports):
    quote = ''.join(docs[S].splitlines(keepends=True)[first-1:last]).rstrip('\n')
    evidence.append(dict(id=identity, document_id=S, section=section,
                         page=None, quote=quote, supports=supports))


span('E1', C, 'Section 1.19, internal subscription definition', '1.19“C3 Offering Internal', '1.20“C3 Price List',
     'BHGE internal subscription rights derive from a separate April 29, 2019 MSSA, orders and SOWs. Those instruments are absent.')
span('E2', C, 'Section 1.12, C3 AI Suite definition', '1.12“C3 AI Suite', '1.13“C3 Capabilities',
     'The platform supports AI application development and operation. This describes capability, not a complete runtime license.')
span('E3', C, 'Sections 1.46-1.48, MSSA and Order definitions', '1.46“MSSA”', '1.49“Personnel”',
     'The JV distinguishes a standard downstream MSSA form and customer-specific Orders from the JV and the separate internal MSSA.')
span('E4', C, 'Section 3.1(b), preferred AI platform', '(b)Preferred AI Platform.', '3.2Resources:',
     'An internal and external AI platform announcement does not replace the actual customer subscription terms.')
span('E5', C, 'Section 8.1(b)-(c), BHGE ownership and internal MSSA preservation', '(b)BHGE.\ni.[***]', '8.2Marks Licenses.',
     'BHGE reserves ungranted technology rights. The central ownership carveout is redacted, and internal MSSA ownership terms remain separate.')
span('E6', C, 'Section 8.4, BHGE Technology License', '8.4BHGE Technology License.', '8.5BHGE and C3 Responsibilities.',
     'A perpetual license covers expressly supplied and identified BHGE-owned technology and actually supplied Feedback within specified development and commercialization purposes.')
span('E7', C, 'Section 8.5, access and modification restrictions', '8.5BHGE and C3 Responsibilities.', '9.CONFIDENTIALITY',
     'Customer model integration cannot depend on unauthorized access, reverse engineering or unlicensed modification of C3 Offerings.')
span('E8', C, 'Section 9.1, Confidential and Sensitive Information definitions', '9.1Confidential Information.', '9.2Non-Use and Nondisclosure.',
     'Confidential Information includes protected third-party information. Sensitive Information has designated individuals or job functions. Exceptions need actual facts.')
span('E9', C, 'Section 9.2, use and disclosure purpose limits', '9.2Non-Use and Nondisclosure.', '9.3Disclosure to Employees.',
     'Use must be required for contractual rights and obligations. Third-party disclosure requires protective terms and respects Restricted Purchasers and Restricted Parties.')
span('E10', C, 'Section 9.3, permitted recipients and Sensitive Information', '9.3Disclosure to Employees.', '9.4Return of Confidential Information.',
     'Recipients require a need to know and protective agreements. Sensitive Information requires the designated recipient scope, subject to stated exceptions.')
span('E11', C, 'Section 9.4, return, deletion and licensed-technology retention', '9.4Return of Confidential Information.', '9.5Required Disclosure.',
     'Return or deletion duties coexist with continued use of Section 8.4 technology and limited surviving-compliance retention.')
span('E12', C, 'Section 12.3(b), separate customer rights after JV termination', '(b)Expiration or termination of this Agreement shall not affect', '(c)For a period of six',
     'JV termination does not itself determine customer or internal subscription rights. The respective agreements govern, with a stated payment-breach exception.')
span('E13', C, 'Section 12.4, survival', '12.4Survival.', '13.GENERAL PROVISIONS',
     'IP, confidentiality and other listed provisions survive JV termination. Expiry cannot erase every license or restriction.')
span('E14', C, 'Section 13.13, amendments and waivers', '13.13Amendments; Waivers.', '13.14Severability.',
     'An amendment requires both parties signatures. A waiver requires the charged party signature and remains limited to its stated circumstance.')
span('E15', C, 'Sections 13.17-13.18, incorporation and hierarchy', '13.17Exhibits.', '13.19Counterparts.',
     'Exhibits are incorporated. The JV precedes its exhibits only within this agreement, not automatically over separate customer contracts.')
span('E16', C, 'Original Exhibit E, Sections 1.6 and 2, superseded development language', '1.6. C3.ai will train and enable', '2.2. C3.ai will work',
     'The original Exhibit E discusses analytic generalization and customer SOWs. The Second Amendment replaces that exhibit in full, so this language cannot authorize current reuse.')
# The last paragraph remains part of the complete original Exhibit E evidence.
evidence[-1]['quote'] = docs[C][docs[C].index('1.6. C3.ai will train and enable'):].rstrip('\n')
span('E17', A, 'First Amendment, Sections 1-2, Year 1-3 definitions', '1.Article 1', '3.Section 12.1',
     'The First Amendment expressly changes Year 1-3 definitions and revenue reporting. These are not general data-use amendments.')
span('E18', A, 'First Amendment, Section 3, replaced term', '3.Section 12.1', '4.Section I of Exhibit',
     'The First Amendment expressly replaces Section 12.1 with an April 30, 2022 initial term and negotiated renewals.')
span('E19', A, 'First Amendment, Sections 5-6, Exhibit E changes and preservation', '5.Sections 1.3', '7.This Amendment',
     'Only selected original Exhibit E deadlines changed at this stage. Other terms remain unchanged unless expressly amended.')
span('E20', B, 'Second Amendment, introductory relation and Section 1', 'THIS SECOND AMENDMENT TO', '2.Section 1.1',
     'The Second Amendment expressly amends the JV as previously amended and replaces BHGE with BH. The chain rests on text, not file order.')
span('E21', B, 'Second Amendment, Section 4, term and conditional renewal', '4.Section 12.1', '5.Exhibit B-1',
     'The initial term ends April 30, 2024. Renewal needs a timely BH election and specified revenue and internal subscription commitments. Exercise is not proved.')
span('E22', B, 'Second Amendment, Sections 5-8, complete exhibit replacements', '5.Exhibit B-1', '9.This Second Amendment',
     'Exhibits B-1, E and F are replaced in full. The restated E and F are not present in this supplied text. Unchanged provisions remain effective on their own terms.')
lines('E23', 'MSA opening, parties and Parent allocation', 12, 39,
      'SAI is Service Provider. SPOCHUB and ESDS Cloud together form Customer. ESDS Software Solutions is separately Parent in the MSA.')
lines('E24', 'Section 1.1, Authorised Users and Cloud Infrastructure definitions', 90, 120,
      'Customer-authorized personnel and End Customers can be users. Exclusive ML infrastructure describes technical scope, not an exception to reseller-only use.')
lines('E25', 'Section 1.1, Confidential Information, Content and Customer Data', 130, 154,
      'Content is broad. Customer Data includes customer-supplied data but excludes operational data generated by provider software and systems.')
lines('E26', 'Section 1.1, Permitted Territory and Services/Service Order definitions', 265, 294,
      'The actual Service Order selects the Data Centre site and service scope. An executed order, not a proposed region, supplies this election.')
lines('E27', 'MSA Section 2.4, scoped order of precedence', 425, 437,
      'Identified Service Order Special Conditions precede MSA terms, which precede ordinary order terms, only to the extent of inconsistency.')
lines('E28', 'MSA Section 2.7, personal performance and subcontractor consent', 454, 472,
      'Section 2.7 requires prior written customer consent to provider third-party performance. Sections 23.7 and 23.9 contain contrary subcontractor permissions.')
lines('E29', 'MSA Section 2.8, residency commitments and narrow migration route', 473, 514,
      'Customer Data and infrastructure must remain in the actual Permitted Territory. The mandatory-law migration route has its own 90-day notice conditions.')
lines('E30', 'MSA Sections 4.3-4.5, resale purpose and order execution', 563, 582,
      'The contracting Customer can use Services only for resale. End Customers receive internal-use rights. A Service Order binds only upon both signatures.')
lines('E31', 'MSA Sections 4.7-4.8, downstream contracts and authorized access', 593, 646,
      'Customer must provide downstream contracts, authenticate users and use Cloud Services solely for resale. Section 8.3 separately supplies the incorporation obligation.')
lines('E32', 'MSA Section 5.4, commencement', 754, 757,
      'Computing Services commence upon both parties signing the Commissioning Certificate. A delivery date does not prove commencement.')
lines('E33', 'MSA Section 7, support recipients and contractual scope', 881, 890,
      'Support follows the actual Service Order and Schedule 7, ordinarily for Customer administrators. Support duties do not themselves grant workload-content access.')
lines('E34', 'MSA Section 8.2, usage improvement grant and content-access proviso', 969, 986,
      'Provider usage analysis can improve services and produce quantitative analytics. It cannot access or interpret Customer Data Content despite this MSA or any order.')
lines('E35', 'MSA Sections 11.1-11.3, data rights, keys, backups and content boundary', 1146, 1181,
      'Customer needs data-use authority and owns encryption-key and backup duties. Provider does not actively monitor or access hosted Customer Data Contents.')
lines('E36', 'MSA Sections 11.5-11.7, personal data and roles', 1191, 1223,
      'No provider access to Customer Personal Data is contemplated. Separate-controller business operations do not create a customer-workload processor appointment.')
lines('E37', 'MSA Sections 15.1-15.5, IP allocation, Feedback and Background IPR', 1442, 1491,
      'Service IP ownership is distinct from input access. Qualifying Customer Feedback has an express any-purpose override, except Customer Background IPR. Section 15.5 is conditional.')
lines('E38', 'MSA Sections 17.1-17.2, confidentiality and particular disclosures', 1523, 1562,
      'Confidential Information use serves proper performance. Disclosure recipients and particular written consent remain scoped, not a blanket data-use license.')
lines('E39', 'MSA Sections 17.4-17.6, exceptions, duration and return', 1572, 1614,
      'Public-domain and other exceptions depend on facts. Trade secret/IP protection can outlast two years. Return/destruction duties prevent unqualified indefinite reuse.')
lines('E40', 'MSA Section 18.6, AI disclaimers and AI Outputs definition', 1684, 1719,
      'AI workloads and outputs are contemplated but disclaimers supply neither a provider training license nor an own-internal-use exception.')
lines('E41', 'MSA Section 18.19, physical infrastructure location warranty', 1983, 1992,
      'All relevant hardware must remain in the selected Permitted Territory. A generic Australia designation does not prove the selected site.')
lines('E42', 'MSA Section 23.5, signed amendment', 2312, 2315,
      'A valid MSA amendment, modification or supplement needs each party duly authorized representative signature.')
lines('E43', 'MSA Section 23.7, final subcontracting sentence', 2354, 2356,
      'The final paragraph allows provider subcontracting without consent and responsibility remains with the provider. It conflicts with Section 2.7.')
lines('E44', 'MSA Section 23.9, subcontractor changes', 2396, 2401,
      'The provider can change subcontractors subject to law. This does not authorize Customer Data Content access or resolve Section 2.7 by date/order alone.')
lines('E45', 'MSA Section 23.12, audit data boundary', 2434, 2442,
      'The provider audit right expressly excludes Customer Data. Audit cannot become a routine training or support-content route.')
lines('E46', 'Schedule 5 AUP, Sections 3.3-3.6', 3115, 3197,
      'AI-specific restrictions, privacy, sanctions and high-risk use limits apply to actual workloads. The proposed internal QA purpose does not prove every prerequisite.')
lines('E47', 'Schedule 5 AUP, Sections 4.5-4.6', 3245, 3269,
      'Customer responsibility for outputs and training inputs confirms customer AI is contemplated. It is not provider-content access authority.')
lines('E48', 'Schedule 5 AUP, Section 5, monitoring and lawful requests', 3270, 3289,
      'AUP investigations and mandatory lawful requests serve exceptional compliance purposes. They do not authorize routine support inference or shared model development.')
lines('E49', 'Schedule 7 SLA, Australia commitment and modification notice', 3548, 3557,
      'The SLA promises Australian centres and requires 30-day notice for SLA changes. Neither term grants AI content reuse or replaces the MSA site election.')
lines('E50', 'Included Service Order No.1, incorporation and customer wording', 3561, 3585,
      'A populated Service Order is included and incorporates the MSA, but its customer wording differs from the MSA allocation. Its presence does not prove execution.')
lines('E51', 'Included Service Order No.1, Special Condition 3 and Security heading', 3719, 3732,
      'Special Conditions concern infrastructure limits and credit security here. They do not state an internal-use or AI-content-access exception.')
lines('E52', 'Service Order Appendix A, Section 6, change control and maintenance', 4036, 4056,
      'Some necessary installation or maintenance changes have their own notice rule. They do not authorize a new content-reading copilot.')
lines('E53', 'Service Order Appendix B, Customer Tools and Platform', 4232, 4245,
      'Customer tools may require technical due diligence, conditions and Additional Fees. Remote platform operation does not require Australian customer personnel.')
lines('E54', 'Service Order Appendix F Part 2, bare-metal responsibility', 4406, 4414,
      'The customer controls OS upwards while provider manages hardware. Customer-controlled models fit this technical allocation, subject to purpose and actual order applicability.')
lines('E55', 'Service Order Appendix F Part 2, firewall, network, compute, storage and OOB', 4479, 4513,
      'Customer responsibility and shared managed OOB require explicit content-secrecy tests. A contractual allocation alone cannot prove no provider access.')
lines('E56', 'Service Order execution page, visible signature fields', 4839, 4882,
      'The acquired Service Order shows names and empty signature fields. It does not establish signed execution, although the MSA has visible signature entries.')
span('E57', A, 'First Amendment, Section 4, Exhibit B-1 Section 1 replacement', '4.Section I of Exhibit', '5.Sections 1.3',
     'The First Amendment expressly replaces Exhibit B-1 Section 1. The Second Amendment later replaces the complete exhibit.')
span('E58', B, 'Second Amendment, Sections 2-3, Year 4-5 and reporting additions', '2.Section 1.1', '4.Section 12.1',
     'The Second Amendment expressly adds Year 4-5 definitions and replaces Section 5.1(b) revenue reporting.')
lines('E59', 'MSA Section 8.3, incorporation into End Customer Contracts', 987, 996,
      'Customer must incorporate the defined Terms and Conditions into binding End Customer Contracts. That duty does not create a Customer own-internal-use license.')
lines('E60', 'MSA execution page, visible signature entries', 2588, 2650,
      'The filed MSA has visible signature entries. They do not prove execution of the separately included Service Order or current service activation.')
lines('E61', 'MSA Section 2.6, conditional Early Access', 447, 453,
      'An actual Early Access offer and readiness notice may support a distinct commencement route. The proposal supplies no such record.')

precedence = [
    dict(higher_document_id=A, lower_document_id=C,
         scope='Year 1-3 definitions, Section 5.1(b), Section 12.1, Exhibit B-1 Section 1 and original Exhibit E Sections 1.3-1.4 only',
         reason='The First Amendment expressly adds definitions and deletes/replaces the listed provisions. Other JV terms remain unchanged. Later Second Amendment replacements govern overlapping subjects.',
         evidence_ids=['E17', 'E18', 'E19', 'E57']),
    dict(higher_document_id=B, lower_document_id=A,
         scope='Section 12.1 term/renewal, Section 5.1(b), Exhibit B-1 and entire Exhibit E where the First Amendment changed them',
         reason='The Second Amendment identifies the previously amended JV and expressly replaces these provisions. Its full Exhibit E replacement also displaces the First Amendment feature deadlines.',
         evidence_ids=['E20', 'E21', 'E22']),
    dict(higher_document_id=B, lower_document_id=C,
         scope='BHGE-to-BH naming, Year 4-5 additions, Section 5.1(b), Section 12.1 and complete replacements of Exhibits B-1, E and F',
         reason='Express additions and delete-and-replace clauses control these subjects. Section 8 preserves the remainder. The absent restated Exhibit E cannot revive its original text.',
         evidence_ids=['E20', 'E21', 'E22', 'E58'])
]

unknowns = [
    dict(id='U1', customer_id='c3-bhge',
         description='Current JV applicability at November 4, 2026 is not proved. The supplied initial term ends April 30, 2024.',
         resolution='Obtain any timely BH renewal election, the specified revenue/subscription commitment records, later signed amendments and termination records. Preserve independently surviving rights meanwhile.',
         evidence_ids=['E21', 'E12', 'E13']),
    dict(id='U2', customer_id='c3-bhge',
         description='The separate April 29, 2019 internal MSSA, associated orders/SOWs and applicable downstream executed customer agreements are absent.',
         resolution='Identify whether BH internal use or a named downstream customer is proposed. Obtain that actual executed MSSA, order, support SOW, amendments and applicable technical/region terms.',
         evidence_ids=['E1', 'E3', 'E7', 'E12']),
    dict(id='U3', customer_id='c3-bhge',
         description='Restated Exhibits E and F are referenced but absent. Listed MSSA forms, restricted-party lists and several other exhibits are also absent from the acquired text.',
         resolution='Obtain the Second Amendment restated Exhibit E for development scope, F for alliance management, and the actually applicable referenced exhibits. Do not reconstruct redacted terms.',
         evidence_ids=['E15', 'E20', 'E22', 'E9', 'E10']),
    dict(id='U4', customer_id='c3-bhge',
         description='The proposal does not establish corpus ownership, downstream confidentiality rights, Sensitive Information designations or authorized support recipients.',
         resolution='Map each intended workload/document/log to its owner, governing agreement, authorized purpose and recipients. Obtain the actual designations and contractual rights, without exposing credentials.',
         evidence_ids=['E5', 'E8', 'E9', 'E10']),
    dict(id='U5', customer_id='c3-bhge',
         description='No supplied record identifies an actual Section 8.4 technology delivery or Feedback contribution covering the proposed training corpus.',
         resolution='For an alternative curated corpus, obtain the specific delivery/identification receipt, BH ownership evidence, actual Feedback and permitted development/commercialization purpose. Otherwise obtain a scoped signed license.',
         evidence_ids=['E6', 'E9', 'E11', 'E14']),
    dict(id='U6', customer_id='sai-esds',
         description='A populated Service Order No.1 and Special Conditions exist in the source, but its execution, actual applicability and later amendments are not proved.',
         resolution='Obtain the applicable order with both required signatures, complete appendices, Product Specific Terms, effective Special Conditions and later signed modifications. Resolve Parent versus Customer allocation.',
         evidence_ids=['E23', 'E26', 'E27', 'E30', 'E50', 'E51', 'E56']),
    dict(id='U7', customer_id='sai-esds',
         description='The actual Commissioning Certificate, installed/accepted state, service activation and current service availability are not supplied.',
         resolution='Read the mutually signed commissioning/acceptance record and actual service-state record. A projected delivery date or unsigned certificate form is insufficient.',
         evidence_ids=['E32', 'E49', 'E56']),
    dict(id='U8', customer_id='sai-esds',
         description='The actual Permitted Territory Data Centre site, backup locations and hardware placement are not established by the proposed Australia fact.',
         resolution='Read the executed site election and infrastructure/backup inventory. Reconcile the SLA Australian commitment with the more specific actual site and any express exceptions.',
         evidence_ids=['E26', 'E29', 'E41', 'E49']),
    dict(id='U9', customer_id='sai-esds',
         description='No actual End Customer deployment, downstream agreement, internal-use purpose exception or dataset rights are supplied.',
         resolution='For the exact own-internal operation, obtain a signed amendment or express valid Special Condition resolving Sections 4.3 and 4.8(a). For resale, obtain the genuine End Customer contract and data-use rights.',
         evidence_ids=['E30', 'E31', 'E35', 'E42', 'E47']),
    dict(id='U10', customer_id='sai-esds',
         description='Support logs are not classified by origin or payload. Actual Personal Data, Confidential Information and Background IPR content are not established.',
         resolution='Use a schema-level data inventory with provenance and content inspection by the authorized customer. Separate native provider telemetry, submitted content and qualifying Feedback before any new route assessment.',
         evidence_ids=['E25', 'E34', 'E35', 'E36', 'E37', 'E38']),
    dict(id='U11', customer_id='sai-esds',
         description='Sections 2.7 and 23.7/23.9 conflict over provider subcontractor consent. No same-level hierarchy resolves that conflict here.',
         resolution='If third-party performance becomes relevant, obtain a signed clarification or an actually applicable express resolution. The self-operated proposal supplies no external model-provider transfer.',
         evidence_ids=['E28', 'E43', 'E44', 'E42']),
    dict(id='U12', customer_id='sai-esds',
         description='A future Feedback or content-free telemetry corpus lacks actual qualifying contributions, provenance and Background IPR evidence.',
         resolution='Verify native system generation for telemetry. For Feedback, verify actual customer transmission, service-change subject and separable Background IPR before use. Assess Section 15.5 separately if relevant.',
         evidence_ids=['E25', 'E34', 'E37'])
]

decisions = [
    dict(id='D1', customer_id='c3-bhge', operation_id='customer-controlled-inference', status='unresolved',
         actor='BH under its actual internal subscription, or a separately identified downstream Customer under its own executed agreement. Neither role substitutes for the other.',
         data='That actor authorized operational workloads and technical documents. Confidential Information and third-party rights retain their actual definitions. The JV does not define a blanket customer-content license.',
         purpose='Answer that customer own operational questions for internal use, within the actual subscription and order scope.',
         model='Customer-selected open-weight model in its controlled tenant in Australia. The proposal excludes provider content access, provider keys, external content transfer and provider training.',
         feature='Tenant Operations Copilot',
         conditions=[
             'Resolve U2 before a current internal-use permission decision. The AI Suite definition and preferred-platform statement do not supply the missing subscription license.',
             'Verify actual geography, integration and use rights. Do not reverse engineer or modify a C3 Offering beyond the actual agreement rights.',
             'Keep content access and encryption keys with authorized customer users. Preserve third-party confidentiality and actual Sensitive Information restrictions.',
             'Resolve current applicable instruments without assuming that JV expiry terminates the separate MSSA or surviving rights.'
         ],
         rationale='Preserve customer-controlled inference as the strongest candidate architecture. Its no-access design avoids a new C3 use of content, but it cannot create missing subscription rights. The JV expressly routes internal use to a separate MSSA. Obtain that instrument and assess this same design without a generic new consent requirement. A downstream customer needs its own contract. Public filing access, platform capability and the unexercised renewal right cannot establish current launch authority.',
         evidence_ids=['E1', 'E2', 'E3', 'E4', 'E7', 'E8', 'E12', 'E13', 'E21'], unknown_ids=['U1', 'U2', 'U4']),
    dict(id='D2', customer_id='c3-bhge', operation_id='provider-support-inference', status='unresolved',
         actor='C3.ai as the actual contracted support provider to BH or the identified downstream customer, within that distinct agreement.',
         data='Only content needed for that customer covered support obligation. Confidential and Sensitive Information, including protected third-party information, retain their source scope.',
         purpose='Answer support questions for that same customer through contractual performance. No unrelated provider or cross-customer improvement purpose is included.',
         model='C3-operated tenant-isolated open-weight inference model in Australia. It can read content. No separate model provider, training or retained session content is proposed.',
         feature='Tenant Operations Copilot',
         conditions=[
             'Establish that the actual agreement and support SOW cover this use and require this content for that support purpose.',
             'Limit data and access to need-to-know covered recipients with protective agreements. Enforce written Sensitive Information designations.',
             'Respect Restricted Purchasers and other applicable recipient limits if disclosure occurs. Do not treat a model vendor as an internal employee.',
             'Keep tenant isolation, zero provider training and session-only retention. Apply any stricter actual customer, security, return and deletion terms.',
             'Recover the restated Exhibit E if JV development obligations support the claimed purpose. Do not rely on deleted original roadmap language.'
         ],
         rationale='Same-customer support can serve the Section 9.2 performance purpose, so this set does not justify a universal AI inference ban or automatic consent demand. The missing actual support agreement and restated development scope prevent a current permission conclusion. Meanwhile build a copilot from C3-authored support material, or execute diagnostics within the customer boundary. Any returned diagnostic content needs its own valid classification and purpose. Removing training and retention does not itself establish the right to read customer content.',
         evidence_ids=['E1', 'E3', 'E8', 'E9', 'E10', 'E11', 'E12', 'E16', 'E21', 'E22'], unknown_ids=['U1', 'U2', 'U3', 'U4']),
    dict(id='D3', customer_id='c3-bhge', operation_id='provider-shared-training', status='needs_consent',
         actor='C3.ai as shared-model owner, distinct from BH or downstream customer as data-rights holder.',
         data='The proposed unclassified workload content, support logs and confidential technical information. These inputs are not established Section 8.4 technology or Feedback.',
         purpose='Improve a provider shared support model that serves other customers. This differs from necessary support for the originating customer.',
         model='C3-owned shared model in Australia, with 30-day raw-example retention and indefinite trained-model retention. No external model provider or de-identification is assumed.',
         feature='Tenant Operations Copilot',
         conditions=[
             'Do not train on the proposed raw-content corpus under this snapshot. Obtain a scoped signed license/amendment from the actual rights holders if that corpus remains the objective.',
             'The instrument must address inputs, shared-model use, confidentiality, permitted recipients, 30-day examples and indefinite model retention. BH cannot grant absent downstream rights.',
             'For a distinct alternative, admit only actual qualifying BH-owned technology expressly provided and identified, or actually provided Feedback, under Section 8.4.',
             'For that alternative, verify the defined development/commercialization connection, Sensitive Information limits and third-party rights. A perpetual license does not convert every workload into licensed technology.',
             'Preserve Section 8.4 continuing-use rights where proved. Do not erase them merely because renewal is unproved. Honor return/deletion outside the licensed and stated retention exceptions.'
         ],
         rationale='There is no demonstrated license for ordinary customer content to train this shared model. Ownership reservations and the required-performance confidentiality purpose prevent an inference from broad JV objectives to blanket reuse. Section 8.4 supplies a valuable separate route for proven technology and Feedback. It can support a curated improvement corpus within its purposes without a fresh generic consent gate. The original Exhibit E generalization clauses cannot repair the raw-content gap because the Second Amendment replaced that exhibit in full. Use rights-cleared synthetic examples and qualifying contributions until the broader input license exists.',
         evidence_ids=['E5', 'E6', 'E8', 'E9', 'E10', 'E11', 'E13', 'E14', 'E16', 'E22'], unknown_ids=['U2', 'U3', 'U4', 'U5']),
    dict(id='D4', customer_id='sai-esds', operation_id='customer-controlled-inference', status='needs_consent',
         actor='SPOCHUB SOLUTIONS PRIVATE LIMITED and/or ESDS Cloud FZ-LLC in the allocation of the actual executed order. The MSA separately identifies ESDS Software Solutions as Parent.',
         data='Customer-authorized workload content and technical documents, with customer keys and no provider content access. Customer Data excludes only the specifically defined native provider operational data.',
         purpose='Answer the contracting Customer own internal operational questions. This is not the MSA permitted resale purpose for an End Customer internal business use.',
         model='Customer-selected open-weight model, controlled by the customer above the OS boundary in Australia. No external model provider, provider training or provider prompt retention is proposed.',
         feature='Tenant Operations Copilot',
         conditions=[
             'For this exact own-internal purpose, obtain an effective signed amendment or express valid Special Condition that resolves Sections 4.3 and 4.8(a). Do not invent that exception.',
             'Alternatively assess a genuine End Customer internal-use deployment under a valid resale contract. Do not relabel the contracting Customer as its own End Customer.',
             'Verify the executed applicable Service Order, required commissioning state, actual Permitted Territory site and any integration due diligence or Additional Fees.',
             'Maintain customer key custody, authorized-user authentication, dataset rights, AUP compliance and customer responsibility for outputs and backups.',
             'The provider must not receive Customer Personal Data access through support tools, OOB administration, crash dumps or telemetry.'
         ],
         rationale='The no-provider-access design fits the bare-metal technical allocation and avoids Section 8.2 content interpretation by SAI. It still conflicts with the separate reseller-only purpose restriction. The Cloud Infrastructure ML definition, AUP and AI disclaimers confirm AI capability, not unrestricted own-internal use. The strongest useful route is this architecture under a real End Customer resale deployment, or a narrow purpose extension for the contracting Customer. Neither route is established now. Australia in the proposal does not prove the selected site, and the populated unsigned order is not an executed prerequisite.',
         evidence_ids=['E23', 'E24', 'E25', 'E26', 'E27', 'E29', 'E30', 'E31', 'E32', 'E35', 'E36', 'E40', 'E42', 'E46', 'E47', 'E49', 'E50', 'E53', 'E54', 'E55', 'E56'], unknown_ids=['U6', 'U7', 'U8', 'U9', 'U10']),
    dict(id='D5', customer_id='sai-esds', operation_id='provider-support-inference', status='off',
         actor='SAI AU NO.2 PTY LTD as content-reading support-model operator, not the Customer operating its own workload.',
         data='Customer workload content and confidential technical documents. Customer-submitted support diagnostics remain Customer Data unless their actual definition establishes otherwise.',
         purpose='Interpret customer content to answer that same customer support questions.',
         model='SAI-operated tenant-isolated open-weight inference model in Australia. No separate model provider, training or retained session content is proposed.',
         feature='Tenant Operations Copilot',
         conditions=[
             'Disable the proposed content-reading support route. Inference interprets Customer Data even without training, external transfer or retention.',
             'Use provider-authored support knowledge and content-free native hardware/usage telemetry for a distinct support copilot.',
             'Run content diagnostics inside the authorized customer or End Customer tenant. Do not automatically return interpreted customer data to the provider.',
             'Any future content-access extension must expressly resolve Section 8.2 and related confidentiality and personal-data terms through an effective instrument. A routine order or support ticket does not suffice.',
             'Keep exceptional AUP investigations and mandatory lawful disclosure separate from routine support and improvement purposes.'
         ],
         rationale='Section 8.2 forbids access, reconstruction, decipherment and interpretation of Customer Data Content despite other MSA terms or any Service Order. The support obligation in Section 7 and confidentiality performance purpose do not erase that narrower prohibition. A broad personnel disclosure permission or a single written disclosure consent is not a new processing license. A provider-knowledge and native-telemetry copilot remains useful, with customer-side diagnostics as the content-aware component. This alternative changes the input boundary and must not silently enable the exact content-reading operation.',
         evidence_ids=['E25', 'E27', 'E33', 'E34', 'E35', 'E36', 'E38', 'E42', 'E45', 'E48', 'E54', 'E55'], unknown_ids=['U6', 'U8', 'U10']),
    dict(id='D6', customer_id='sai-esds', operation_id='provider-shared-training', status='off',
         actor='SAI AU NO.2 PTY LTD as shared-model owner and training operator.',
         data='The proposed raw workload content, support logs and confidential technical documents. No de-identification, qualifying Feedback status or provider-native origin is assumed.',
         purpose='Improve the provider shared support model for use across its customer base, beyond the originating customer support session.',
         model='SAI-owned shared model trained and hosted in Australia. Raw examples persist for 30 days and the model persists indefinitely. No external model provider receives content.',
         feature='Tenant Operations Copilot',
         conditions=[
             'Exclude the exact proposed corpus from shared training under this snapshot. Service improvement and IP ownership do not authorize Customer Data Content access.',
             'Develop a separate native, content-free quantitative telemetry corpus under Section 8.2, with origin and payload controls.',
             'Develop a separate corpus of actual qualifying Customer Feedback under Section 15.4. Preserve its any-purpose notwithstanding grant and exclude Customer Background IPR from that grant.',
             'Assess Section 15.5 separately if Background IPR is incorporated in Foreground IPR. Do not manufacture the triggering incorporation as a way to acquire raw workload rights.',
             'Keep Customer Personal Data inaccessible. Honor confidentiality, return and destruction terms for data outside a demonstrated exception.',
             'A raw-content training extension requires an express signed resolution of the conflicting access, purpose, data-role and retention terms. Notice or relabeling alone cannot create it.'
         ],
         rationale='The exact raw-content operation is off. The Section 8.2 improvement grant preserves quantitative usage analysis but expressly excludes content access. Sections 15.2-15.3 allocate resulting IP rather than supplying the missing input license. Section 15.4 is stronger counterevidence: genuinely supplied Feedback has an express any-purpose override. Preserve that useful route instead of applying a universal training ban. The proposal does not establish that its workloads and logs are Feedback. A separate curated Feedback/telemetry/synthetic-data model can improve support without granting itself the proposed raw-content access. A 30-day example purge cannot eliminate indefinite model retention.',
         evidence_ids=['E25', 'E34', 'E35', 'E36', 'E37', 'E38', 'E39', 'E40', 'E42', 'E45', 'E47'], unknown_ids=['U6', 'U8', 'U10', 'U12'])
]

controls = []
for decision in decisions:
    op = next(o for o in feature['operations'] if o['id'] == decision['operation_id'])
    facts = dict(op['proposed_facts'])
    facts['purpose'] = op['purpose']
    facts['model_role'] = 'customer_selected' if op['id'] == 'customer-controlled-inference' else 'service_provider_operated'
    controls.append(dict(
        decision_id=decision['id'], customer_id=decision['customer_id'], operation_id=decision['operation_id'],
        proposed_eligible=False, required_facts=facts,
        reason={
            'D1': 'The exact proposed customer-custody facts do not establish missing internal or downstream subscription rights. U1/U2/U4 prevent eligibility.',
            'D2': 'The exact same-customer support facts do not prove the actual permitted performance purpose or recipient scope. U1-U4 prevent eligibility.',
            'D3': 'The exact shared-training facts lack the raw-content license. A qualifying Section 8.4 corpus is a distinct reassessed route.',
            'D4': 'The proposed own-internal purpose conflicts with reseller-only rights. Do not assert an unknown signed exception, order, commissioning or site election.',
            'D5': 'The exact inference design reads Customer Data Content and violates Section 8.2. No-training and Australia facts do not cure that restriction.',
            'D6': 'The exact raw-content shared-training design exceeds the permitted access. Narrow Feedback or native telemetry routes do not silently change this operation.'
        }[decision['id']]))

engineering_outputs = [
    dict(id='ENG1', title='Implement scoped contract resolution and source-to-decision coverage', decision_ids=['D1','D2','D3','D4','D5','D6'],
         body='Represent each rule as actor, data definition, purpose, model role, feature, subject scope and condition. Retain exact source and amendment relation. For C3, apply the First Amendment additions and express replacements first. Apply the Second Amendment full Exhibit E replacement even though its replacement text is absent. Keep Section 8.4 and confidentiality survival distinct from the unproved current JV term. Do not rank the separate internal MSSA below the JV without actual conflict text. For SAI, store the internal Section 2.4 hierarchy by unit, despite a single source document ID. Identified Special Conditions precede MSA terms, then ordinary order terms, only for a real inconsistency. Preserve Section 8.2 notwithstanding language and Section 15.4 separate Feedback override. Do not create a self-referential source-document precedence edge.\n\nStrong-term disposition: C3 platform preference and development discretion describe capability and change rights, not raw-data reuse. Original Exhibit E analytics generalization is superseded, not silently omitted. Revenue commitments affect renewal but grant no content rights. Marks, exclusivity and distribution provisions do not supply workload permissions. C3 reserved IP and redacted ownership remain explicit limits. SAI ML definitions, AI-output disclaimers, Foreground IPR, open-source component rights and security measures do not enlarge service purpose or content access. SAI support, remote hands, audit, maintenance, financing/KYC disclosure, AUP investigation and lawful-demand rights retain their exact purposes. They cannot become ordinary training rights. Included credit security, fees, termination and SLA remedies remain operational/commercial terms, without a new AI grant. The Service Order Special Conditions are present, not presumed missing or overridden by filename order. No actual legal jurisdiction, personal-data applicability, payment, termination or approval state is inferred.',
         acceptance_criteria='A replacement test removes original Exhibit E from operative authority while preserving its historical trace. A survival test preserves C3 Section 8.4 and Section 9 after JV expiry. A SAI hierarchy test rejects an ordinary order permission that conflicts with Section 8.2. A separate test preserves the actual Section 15.4 grant for qualifying Feedback. Source coverage lists all four supplied files and every material rejected counterterm.'),
    dict(id='ENG2', title='Ship exact six-pair proposed controls with literal fact matching', decision_ids=['D1','D2','D3','D4','D5','D6'],
         body='Export exactly the six controls in this assessment. Each targets its exact customer and operation. Treat the feature fact sheet as a hypothetical request context, not a certificate of contractual prerequisites. All six controls remain false. Require exact equality for actor_role, provider_content_access, external_content_transfer, provider_training, processing_region, purpose and model_role. Do not insert contract_executed=true, consent=true, site_verified=true or commissioning_complete=true without source evidence. A caller-supplied boolean cannot promote this assessment. Promotion requires a new source-bound decision with resolved prerequisite IDs and a new bundle hash. Keep the local OpenFeature and OPA exports scoped to this hypothetical feature. Do not install a general broker or restrict personal Kai.',
         acceptance_criteria='The actual OpenFeature SDK returns false for every exact proposed context, unknown customer and absent required fact. SQLite contains the exact six decisions and exact controls. The received bundle/export equal the authored JSON and compiled export. This test proves local behavior, not customer clearance or a live deployment.'),
    dict(id='ENG3', title='Build customer-side inference with independent purpose and access gates', decision_ids=['D1','D4'],
         body='Use a customer-selected open-weight model above the customer OS boundary. Keep documents, retrieval indexes, prompts, outputs and keys in that tenant. Provider support receives no payload, embedding, model context or key. Keep remote platform operation compatible with the actual order. For SAI, expose two distinct design choices in the implementation specification: a genuine End Customer internal-use resale deployment, or a contracting Customer deployment under an express effective purpose exception. Do not reinterpret the Customer as its own End Customer. For C3, bind the runtime to the actual internal MSSA or downstream customer agreement. Implement authentication and document ACL checks before retrieval. Use source-linked answers and advisory output for operational QA. Customer output responsibility remains material under the SAI AUP and disclaimer. No content-aware provider monitoring is required by this design.',
         acceptance_criteria='A synthetic authorized document can answer a tenant question. A second tenant and unauthorized user cannot retrieve it. Provider support credentials and OOB paths cannot expose plaintext through memory, snapshots, crash dumps, caches or consoles. The own-internal SAI purpose fails even when every custody predicate passes. A synthetic End Customer test remains preparation only until actual resale/order/site predicates exist.'),
    dict(id='ENG4', title='Build a provider support copilot with content-free telemetry', decision_ids=['D2','D5','D6'],
         body='Separate the provider knowledge plane from the customer content plane. The support model receives provider-authored runbooks, public material with verified reuse rights, and native provider-generated numeric metrics. Allowlist hardware fault code, GPU availability, aggregate resource utilization and coarse service event time only after each field origin is verified. Reject request bodies, query strings, customer document paths, arbitrary log messages, prompt/output fragments, stack locals and payload-derived embeddings. A native-system label is insufficient if the field contains customer content. Customer-submitted diagnostic logs retain their source classification. Run content-aware diagnosis inside the authorized customer tenant. Return only independently authorized result fields, with no automatic upload. This supports hardware and usage questions without interpreting Customer Data Content.',
         acceptance_criteria='Provider-generated hardware fault metrics produce a runbook answer. A customer log renamed telemetry is rejected. A numeric metric field containing a seeded document canary is rejected. Inference with provider_training=false still rejects customer content. The authorized customer can diagnose its synthetic workload locally while a provider trace contains no seeded payload or key.'),
    dict(id='ENG5', title='Create a rights-cleared improvement corpus with separate C3 and SAI rules', decision_ids=['D3','D6'],
         body='Define contribution records with source_artifact_id, contributor_role, origin_kind, actual_delivery_receipt, rights_holder, background_ipr_components, confidential_components, permitted_purposes, permitted_recipients, retention_scope and governing_evidence. Treat these as required future evidence, not present facts. The C3 route admits actual expressly identified BH-owned technology or actually provided Feedback only for Section 8.4 development/commercialization purposes. It excludes downstream content absent its own rights. The SAI route admits actual transmitted change recommendations, bug reports, comments, questions or similar Customer Feedback within Section 15.4. Preserve that clause any-purpose override for qualifying material. Separate Customer Background IPR, and assess Section 15.5 only if its incorporation condition actually holds. Neither route automatically ingests workload buckets or whole support logs. Independent synthetic examples may supplement the model if their provenance excludes protected input. Do not generate synthetic examples from prohibited customer content and call them independent.',
         acceptance_criteria='A synthetic, genuinely transmitted service-change suggestion with no Customer Background IPR passes the SAI classification test. An arbitrary workload document marked feedback fails. A C3 third-party model claimed as BH-owned fails absent rights. A C3 qualifying technology contribution retains its proved perpetual scope after JV expiry. A Background IPR component cannot pass solely through Section 15.4. No test fixture promotes the exact six blocked controls.'),
    dict(id='ENG6', title='Track retained models separately from raw example retention', decision_ids=['D2','D3','D5','D6'],
         body='For inference, remove session buffers, prompts, model caches and output records after the session where the proposed design requires it. For any later authorized training route, link each dataset version, checkpoint, adapter and derivative model to its actual contribution rights. Record raw-example expiry separately from trained-model retention. Test return/deletion requests against unlicensed and licensed artifacts independently. C3 Section 9.4 retains its stated Section 8.4 and surviving-obligation exceptions. SAI confidentiality and return/destruction terms remain scoped alongside any proved Feedback rights. Do not assert that ordinary 30-day raw deletion removes information from indefinite weights. For the proposed broad corpus, no training job can start.',
         acceptance_criteria='A synthetic example expires after the configured raw-retention period while its test checkpoint remains visible as a separate retained artifact. The system reports this distinction. A covered return request blocks further use of the affected unlicensed corpus. A genuinely surviving licensed artifact does not disappear through a blanket JV-expired rule. A prohibited proposed training input never reaches the trainer.'),
    dict(id='ENG7', title='Verify exact SAI site, service state and administrative access before any route promotion', decision_ids=['D4','D5','D6'],
         body='Create an evidence record for the executed order, effective Special Conditions, technical requirements, commissioning certificate, selected Data Centre site, backups and current service state. The record distinguishes the signed MSA, populated unsigned order, blank certificate forms and actual receiving-state evidence. Preserve the SLA Australia commitment, but require the actual Permitted Territory site. Do not trigger the 90-day mandatory-law migration path or 30-day SLA modification notice for this Australia-only feature proposal. A customer-tool integration follows actual Appendix B diligence, technical conditions and fees if that order applies. Separate customer key custody from the managed OOB platform. Record the Section 2.7 versus 23.7/23.9 conflict if a new third-party performer becomes relevant. The current self-operated models do not imply a separate model provider.',
         acceptance_criteria='A proposed Australia fact cannot satisfy a missing site election. A passed delivery-date clock cannot satisfy the mutual commissioning certificate. A cloud-region label cannot satisfy physical backup placement. A new external model provider fails this operation identity and requires separate assessment. No notice is fabricated solely because the source contains notice clauses.'),
    dict(id='ENG8', title='Run source, semantic and receiver regression checks without changing the kit', decision_ids=['D1','D2','D3','D4','D5','D6'],
         body='Run the supplied validate, compile and readback commands against model-decisions.json. Inspect every exact failure and change only the authored output where source evidence supports repair. Verify one decision/control per Cartesian pair, unique IDs, evidence membership and original source hashes. Read local-results.sqlite3 in read-only mode and compare the bundle and export with their exact local source files. Save the comparison receipt. Add effect-free supplemental SDK probes for missing each fact, wrong literal values, cross-customer substitutions and operation confusion. These probes use the unchanged supplied evaluation function and actual OpenFeature SDK. Label all false results correctly. They validate disabled-state behavior, not a future enabled path or the substantive interpretation. OPA policy generation is distinct from OPA runtime evaluation.',
         acceptance_criteria='The validator verifies every selected original quote. Compilation writes the expected exports and the real SDK evaluations pass. Receiver readback equals both exact decision and export content. Supplemental negative probes all return false. The completion receipt states untested semantic and live-system boundaries instead of claiming customer deployment.')
]

drafts = [
    dict(type='information_request', customer_id='c3-bhge',
         reason='The JV routes internal and downstream runtime rights to other instruments. The Second Amendment replaces development scope and makes renewal conditional.',
         draft='Conditional local draft for the appropriate contract custodian: Could you provide the applicable signed subscription agreement, orders, support SOW and amendments for the proposed deployment? For BH internal use, please include the April 29, 2019 MSSA and its current orders. Please include the Second Amendment restated Exhibit E and any renewal election or later instrument relevant to the current term. We also need the data-owner permissions and any written Sensitive Information recipient designations for the proposed corpus.',
         unknown_fields=['appropriate contract custodian', 'actual contracting customer', 'applicable subscription/order identifiers', 'current amendments and renewal records', 'corpus rights and designations'],
         evidence_ids=['E1', 'E3', 'E8', 'E10', 'E21', 'E22']),
    dict(type='information_request', customer_id='sai-esds',
         reason='The present order text does not prove signatures, commencement, the actual site election or an exception to reseller-only use.',
         draft='Conditional local draft for the appropriate contract custodian: Could you provide the applicable Service Order with both signatures, complete appendices and effective Special Conditions? Please include the mutually signed commissioning record and the selected Data Centre site with backup locations. Please identify whether the proposed user is the contracting Customer or a genuine End Customer. For an End Customer deployment, please provide the applicable resale terms and dataset-use rights. Please include any signed internal-use exception and later amendments.',
         unknown_fields=['appropriate contract custodian', 'executed applicable Service Order', 'customer allocation', 'commissioning record', 'selected site', 'actual End Customer', 'purpose exception'],
         evidence_ids=['E23', 'E26', 'E27', 'E30', 'E31', 'E32', 'E41', 'E50', 'E56']),
    dict(type='consent', customer_id='c3-bhge',
         reason='Ordinary confidential customer content has no demonstrated shared-training license. Any new grant must satisfy the actual rights and signed-instrument requirements.',
         draft='Conditional negotiation draft only: If the actual rights holders elect to permit the broader corpus, the signed instrument must identify the permitted source categories and specific contribution scope. It must expressly permit or reject training a C3.ai shared support model that serves other customers. The proposal retains raw examples for 30 days and trained models indefinitely in Australia. The instrument must resolve those retention terms, permitted use, confidentiality, disclosure, deletion and downstream rights. No broad grant takes effect through this draft, silence or a support request. Existing proven Section 8.4 contributions retain their own terms.',
         unknown_fields=['actual rights holders and signatories', 'governing instruments', 'specific corpus', 'permitted uses and recipients', 'retention/deletion terms', 'downstream rights', 'effective instrument'],
         evidence_ids=['E5', 'E6', 'E8', 'E9', 'E11', 'E14']),
    dict(type='consent', customer_id='sai-esds',
         reason='The exact contracting-Customer internal purpose requires a valid express exception to the MSA reseller-only purpose. This is distinct from provider content access.',
         draft='Conditional purpose-extension draft only: Subject to an effective instrument signed by the applicable parties, permit the identified contracting Customer to use the specified compute services for its own Tenant Operations Copilot operational questions. The exception must expressly resolve Sections 4.3 and 4.8(a) for that scope. Customer content, model execution and encryption keys remain under Customer control. This purpose extension gives SAI no customer-content access, shared-training right or external transfer right. The instrument must identify the applicable order, selected site, users and effective scope. It takes effect only through the required signed instrument.',
         unknown_fields=['applicable parties and signatories', 'executed order', 'specified internal-use scope', 'selected site', 'effective instrument', 'authorized users'],
         evidence_ids=['E27', 'E30', 'E31', 'E34', 'E35', 'E42'])
]

bundle = dict(
    assessment_type='proposed_source_bound_decisions', feature_id='tenant-operations-copilot',
    summary='Choose customer-side content inference plus a separate provider knowledge/telemetry copilot as the strongest useful design. A distinct rights-cleared Feedback corpus preserves useful provider improvement. The exact six proposals cannot receive present eligibility from these public snapshots. C3 customer inference and support remain unresolved pending actual subscription and support instruments. C3 raw-content shared training needs a scoped rights grant. SAI own-internal inference needs a purpose exception or a genuine End Customer deployment. SAI provider content inference and raw-content shared training are off under the supplied access restriction. All six proposed controls therefore remain false. These results concern the hypothetical feature at November 4, 2026. They establish no current customer clearance, legal applicability or outside use. No notice-alone route applies. The local conditional drafts are preparation only.',
    evidence=evidence, precedence=precedence, decisions=decisions, unknowns=unknowns,
    controls=controls, engineering_outputs=engineering_outputs, notices_or_consent_drafts=drafts)

# These are explicit author revisions, not an inference or decision generator.
revisions = {
    'the identified contracting Customer own': "the identified contracting Customer's own",
    'That actor authorized': "That actor's authorized",
    'that customer own': "that customer's own",
    'that same customer covered': "that same customer's covered",
    'the contracting Customer own': "the contracting Customer's own",
    'the provider shared': "the provider's shared",
    'both parties signatures': "both parties' signatures",
    'each party duly authorized': "each party's duly authorized",
    'the unexercised renewal right': 'the renewal right without evidence of exercise',
    'service-change subject': 'qualifying service-related Feedback under Section 15.4',
    'Sections 4.3 and 4.8(a)': 'Sections 4.3, 4.4 and 4.8(a)',
    'required commissioning state': 'valid commencement basis, including any actual authorized Early Access',
    'The actual Commissioning Certificate, installed/accepted state, service activation and current service availability are not supplied.':
        'Actual mutual commissioning, authorized Early Access, installed/accepted state and current service availability are not supplied.',
    'Read the mutually signed commissioning/acceptance record and actual service-state record. A projected delivery date or unsigned certificate form is insufficient.':
        'Read the mutual commissioning/acceptance record or actual authorized Early Access offer, readiness notice and applicable commencement terms. Verify actual service state. A projected delivery date or unsigned certificate form is insufficient.',
    'For SAI, expose two distinct design choices in the implementation specification: a genuine End Customer internal-use resale deployment, or a contracting Customer deployment under an express effective purpose exception.':
        'For SAI, specify a genuine End Customer internal-use resale deployment. Alternatively, specify a contracting Customer deployment with an affirmative internal-use license and effective purpose exception.',
    'Conditional negotiation draft only: If the actual rights holders elect to permit the broader corpus, the signed instrument must identify the permitted source categories and specific contribution scope.':
        'Conditional negotiation draft only. If the actual rights holders elect to permit the broader corpus, the signed instrument must identify source categories and contribution scope.',
    'Conditional purpose-extension draft only: Subject to an effective instrument signed by the applicable parties, permit the identified contracting Customer to use the specified compute services for its own Tenant Operations Copilot operational questions.':
        'Conditional purpose-extension draft only. The effective instrument must contain an affirmative internal-use license signed by the applicable parties. Its scope covers the identified contracting Customer own Tenant Operations Copilot operational questions on the specified compute services.',
    'A passed delivery-date clock cannot satisfy the mutual commissioning certificate.':
        'A passed delivery-date clock cannot satisfy mutual commissioning. An actually authorized Early Access arrangement receives its own commencement test.',
    'No notice is fabricated solely because the source contains notice clauses.':
        'No notice is fabricated solely because the source contains notice clauses. Any actual Early Access readiness notice remains a requirement of that separate route.'
}


def revise(value):
    if isinstance(value, dict):
        return {key: item if key == 'quote' else revise(item) for key, item in value.items()}
    if isinstance(value, list):
        return [revise(item) for item in value]
    if isinstance(value, str):
        for old, new in revisions.items():
            value = value.replace(old, new)
    return value


bundle = revise(bundle)
bundle['decisions'][3]['evidence_ids'].extend(['E59', 'E60', 'E61'])
bundle['unknowns'][6]['evidence_ids'].append('E61')
bundle['unknowns'][8]['resolution'] += ' The own-internal exception must also supply an affirmative internal-use license.'
bundle['engineering_outputs'][1]['acceptance_criteria'] += ' All-off evaluations do not test type-sensitive equality in a future enabled rule.'
bundle['engineering_outputs'][6]['body'] += ' Preserve any actually authorized Section 2.6 Early Access route as distinct from ordinary commissioning.'
bundle['notices_or_consent_drafts'][1]['evidence_ids'].append('E61')
bundle['notices_or_consent_drafts'][1]['draft'] = bundle['notices_or_consent_drafts'][1]['draft'].replace(
    'Please include the mutually signed commissioning record and the selected Data Centre site with backup locations.',
    'Please include the mutual commissioning record or any actual authorized Early Access offer and readiness notice. Please include the selected Data Centre site with backup locations.')
bundle['notices_or_consent_drafts'][1]['unknown_fields'].append('any actual authorized Early Access basis')

assert len(decisions) == len(controls) == 6
assert len({(d['customer_id'],d['operation_id']) for d in decisions}) == 6
(WORK / 'model-decisions.json').write_text(json.dumps(bundle, ensure_ascii=False, indent=2) + '\n')
print(json.dumps({'authored_decisions': len(decisions), 'evidence_items': len(evidence),
                  'engineering_outputs': len(engineering_outputs), 'eligible': 0}))
