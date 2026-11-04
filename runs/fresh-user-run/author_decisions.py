"""Local authoring aid. Interpretations below are model-authored, not inferred by code."""
import json
from pathlib import Path

WORK = Path(__file__).resolve().parent
manifest = json.loads((WORK / 'source-manifest.json').read_text())
docs = {d['id']: d for c in manifest['customers'] for d in c['documents']}
texts = {key: (WORK / d['text_file']).read_text() for key, d in docs.items()}
J = 'c3-bhge:01-joint-venture-2019-06-06.html'
A = 'c3-bhge:02-first-amendment-2019-09-26.html'
B = 'c3-bhge:03-second-amendment-2020-06-01.html'
S = 'sai-esds:01-master-services-2026-03-31.html'
evidence = []


def span(eid, doc, section, start, end, supports):
    text = texts[doc]
    first = text.index(start)
    last = text.index(end, first + len(start))
    evidence.append(dict(id=eid, document_id=doc, section=section, page=None,
                         quote=text[first:last], supports=supports))


def exact(eid, doc, section, quote, supports):
    assert quote in texts[doc], (eid, quote)
    evidence.append(dict(id=eid, document_id=doc, section=section, page=None,
                         quote=quote, supports=supports))


span('E1', J, '1.12: C3 AI Suite definition', '1.12“C3 AI Suite”', '1.13',
     'The platform supports customer AI applications. Its AI category alone supplies no customer-content licence.')
span('E2', J, '1.18–1.19: offerings and separate internal subscription', '1.18“C3 Offering(s)”', '1.20',
     'The offerings definition is redacted. BHGE internal use depends on a separately referenced April 29, 2019 MSSA and orders.')
span('E3', J, '1.46–1.48: MSSA, Offering and Order definitions', '1.46“MSSA”', '1.49',
     'The listed standard forms and actual customer orders are distinct from this JV agreement. Their text and execution cannot be assumed.')
span('E4', J, '2.1: appointment, customers and separate party authority', '2.1Appointment of BHGE.', '2.2BHGE Exclusivity.',
     'BHGE is a distributor or reseller to enterprise end customers. Neither party can bind the other through that appointment.')
span('E5', J, '3.1: noncompetition and preferred AI platform', '3.1Preferred AI Platform.', '3.2Resources:',
     'The noncompetition promise addresses external distribution and sale. The preferred platform statement is not a grant of every internal-use or data right.')
span('E6', J, '6.1–6.2: development and feature changes', '6.1C3 Applications Development.', '7.ALLIANCE MANAGEMENT',
     'C3 feature evolution remains subject to development terms and existing customer liabilities. It supplies no independent content-use permission.')
span('E7', J, '8.1(b)–(c): BHGE rights and internal MSSA preservation', 'ii.Except as set forth in the foregoing Section 8.1(b)i', '8.2Marks Licenses.',
     'BHGE reserves technology rights. The JV ownership rules preserve the separate internal MSSA, subject to the redacted exception.')
span('E8', J, '8.3–8.5: joint development, technology licence and restrictions', '8.3No Joint Development.', '9.CONFIDENTIALITY',
     'The 8.4 licence requires BHGE-owned technology expressly provided and identified, or actual Feedback. Its uses have specified development and commercial purposes.')
span('E9', J, '9.1: Confidential Information and Sensitive Information', '9.1Confidential Information.', '9.2Non-Use and Nondisclosure.',
     'Confidential Information includes technical data and third-party material held under confidence. Sensitive Information has designated recipient restrictions.')
span('E10', J, '9.2: non-use and nondisclosure', '9.2Non-Use and Nondisclosure.', '9.3Disclosure to Employees.',
     'Use must be required for JV rights or obligations. Confidentiality and restricted-recipient duties survive until an actual exception applies.')
span('E11', J, '9.3: permitted personnel and Sensitive Information', '9.3Disclosure to Employees.', '9.4Return of Confidential Information.',
     'Need-to-know and confidentiality agreements limit access. Sensitive Information requires the specified individuals or job functions, subject to stated exceptions.')
span('E12', J, '9.4–9.5: return, deletion and required disclosure', '9.4Return of Confidential Information.', '9.6Without limiting',
     'Return or deletion and officer certification apply. Retained 8.4 technology and necessary compliance copies have scoped exceptions. Compelled disclosure has its own conditions.')
span('E13', J, '12.3(b): existing customer and internal subscription rights', '(b)Expiration or termination of this Agreement shall not affect', '(c)For a period of six',
     'JV expiration does not automatically end existing customer or internal subscription rights. Those rights depend on their respective agreements.')
span('E14', J, '12.4: survival', '12.4Survival.', '13.GENERAL PROVISIONS',
     'Intellectual property and confidentiality obligations survive JV expiration or termination.')
span('E15', J, '13.13: signed amendments and scoped waivers', '13.13Amendments; Waivers.', '13.14Severability.',
     'Amendments need both signatures. A waiver applies only to its specific circumstance.')
span('E16', J, '13.17–13.18: incorporation and hierarchy', '13.17Exhibits.', '13.19Counterparts.',
     'Exhibits are incorporated. The JV body has priority over its exhibits. This does not supply omitted exhibit text.')
span('E17', J, 'Original Exhibit E: analytics and custom workflows', '1.6. C3.ai will train and enable', '2. Professional Services',
     'The original roadmap contemplated review for generalization. The Second Amendment replaces this entire exhibit, so this old language cannot establish current authority.')
exact('E18', J, 'Original Exhibit E 2.2: custom workflows',
      '2.2. C3.ai will work with system integrators and other relevant partners to provide service capabilities in the appropriate locations to create custom workflows and use cases for Customers. These custom workflows and use cases should periodically be reviewed with BHGE for potential generalization and incorporation into the C3.ai product roadmap.',
      'The old generalization provision concerns roadmap review, not an express licence to train on arbitrary customer content. The entire exhibit was later replaced.')
span('E19', A, '1–3: annual definitions, revenue calculation and replacement term', '1.Article 1 of the JV Agreement', '4.Section I of Exhibit B-1',
     'The First Amendment expressly replaces named terms and fixes the Initial Term at April 30, 2022 before the Second Amendment changes it.')
span('E20', A, '4–6: scoped exhibit amendments and preservation', '4.Section I of Exhibit B-1', '7.This Amendment',
     'Only the named revenue table and roadmap subsections change. Unaltered terms remain effective under this amendment.')
span('E21', B, '1–4: name, years, revenue calculation and replacement term', '1.Throughout the JV Agreement', '5.Exhibit B-1',
     'BH replaces BHGE. The Initial Term ends April 30, 2024. Renewal requires an exercise of the right and specified revenue and internal subscription conditions.')
span('E22', B, '5–8: wholesale exhibit replacement and preservation', '5.Exhibit B-1', '9.This Second Amendment',
     'B-1, E and F are replaced in full. Other JV terms remain unchanged. The acquired second amendment includes only the restated B-1 text.')
span('E23', B, 'Restated Exhibit B-1: annual minimum commitment table', '1.Minimum Annual Revenue Commitment.', '2.Shortfall.',
     'The five-year revenue table replaces earlier tables. Commercial commitments do not grant data-use rights.')
span('E24', S, 'MSA opening: contracting parties and Parent', '1.\nSAI\nAU NO.2', 'The\nCustomer and Service Provider',
     'SAI is Service Provider. SPOCHUB and ESDS Cloud together are Customer. ESDS Software Solutions is separately Parent under the MSA.')
span('E25', S, '1.1: Authorised Users', '“Authorised\nUsers”', '“Background\nIntellectual',
     'Authorised Users include authorised customer employees and contractors and any End Customer. That definition does not expand the permitted purpose.')
span('E26', S, '1.1: Cloud Infrastructure, Cloud Services and Commissioning Certificate', '“Cloud\nInfrastructure”', '2\nCommercial in confidence',
     'The infrastructure supports machine learning for exclusive customer use. Operational readiness requires a mutual Commissioning Certificate, not a calendar inference.')
span('E27', S, '1.1: Confidential Information, Content and Customer Data', '“Confidential\nInformation”', '“Data\nProtection Legislation”',
     'Content includes software and data. Customer Data includes customer-provided material but excludes provider-generated system logs, usage, telemetry and operational data.')
span('E28', S, '1.1: Permitted Territory', '“Permitted\nTerritory”', '“Professional\nServices”',
     'The Permitted Territory is the Data Centre site in the relevant Service Orders. Australia alone does not prove the selected site.')
span('E29', S, '1.1: Services and executed Service Order', '“Services”\nmeans', '5\nCommercial in confidence',
     'The purchased Services depend on a Service Order executed by both parties, including appendices and applicable product terms.')
span('E30', S, '2.4: scoped document precedence', '2.4\nIn\nthe event', '7\nCommercial in confidence',
     'Express Special Conditions outrank the MSA. The MSA outranks ordinary Service Order terms only to the extent of inconsistency.')
span('E31', S, '2.7–2.8: subcontractors and data residency', '2.7\nThe\nService Provider undertakes', '8\nCommercial in confidence',
     'Customer Data and infrastructure are site-bound. Technical migration cannot use an efficiency exception. Consent and mandatory-law migration routes have different conditions.')
span('E32', S, '3.1–3.5: term and separate orders', '3.1\nThis\nMSA shall commence', '4\nACCESS',
     'The MSA has a stated term. Each order has its own term and separate effect. This supplies no proof of current activation.')
span('E33', S, '4.1–4.6: resale purpose, grant and orders', '4.1\nAppointment:', '9\nCommercial in confidence',
     'The Customer may use the Services only for resale. End Customers receive internal business use. Orders need both signatures. Product terms can be incorporated.')
span('E34', S, '4.7–4.8: end-customer contracts and authorised use', '4.7\nCustomer\nResponsibilities:', '4.9\nDependencies:',
     'End Customer Contracts and user authorisation remain prerequisites. Cloud Services are available solely for resale, even to authorised customer personnel.')
span('E35', S, '5.1–5.4: commencement and Commissioning Certificate', '5.1\nThe\nParties agree to commence', '6\nSETTLEMENTS',
     'The mutual installation and co-testing procedure controls commencement. The signed Commissioning Certificate triggers computing services.')
span('E36', S, '7: support service scope', '7\nSERVICE\nLEVELS\nSubject', '8\nUSAGE',
     'Contracted support is for customer administrators and depends on payment and order scope. It does not authorise workload-content access.')
span('E37', S, '8.2: monitoring permission and overriding content exclusion', '8.2\nMonitoring:', '8.3\nTerms',
     'Provider improvement and quantitative analytics are allowed subjects of monitoring. The express proviso bars access, reconstruction, decipherment or interpretation of Customer Data content.')
span('E38', S, '8.3: binding end-customer restrictions', '8.3\nTerms', '9\nACCEPTANCE',
     'End Customer Contracts must validly incorporate the defined Terms and Conditions for the order term.')
span('E39', S, '11.1–11.3: rights, keys and no content access', '11.1\nGenerally:', '11.4\nDelays:',
     'The customer must have data rights and manages encryption keys and backups. The no-access position permits only explicit contractual or legal exceptions.')
span('E40', S, '11.5–11.7: personal data and provider role', '11.5\nProcessing:', '11.8\nController',
     'Personal Data should not be provided or made accessible to the provider. The intended provider role excludes a processor or controller of Customer Personal Data.')
span('E41', S, '12.1–12.2: security', '12.1\nInformation', '13\nCOMPLIANCE',
     'Security measures protect confidentiality, integrity and data against unauthorised access. Security duties do not grant an AI purpose.')
span('E42', S, '14.3: first advance prerequisite', '14.3\nAdvances:', '14.4\nTaxes:',
     'Cleared first-advance receipt and provider written confirmation are operational prerequisites. The filing does not prove them.')
span('E43', S, '15.1–15.3: ownership and customer application layer', '15.1\nBackground', '15.4\nCustomer',
     'Broad provider foreground ownership coexists with reserved background rights and the customer application-layer exclusion. Ownership does not itself grant content access.')
span('E44', S, '15.4–15.5: qualifying feedback and incorporated background IP', '15.4\nCustomer', '15.6\nIf',
     'Qualifying Customer Feedback has a specific any-purpose override, excluding customer Background IPR. The 15.5 licence concerns background IP actually incorporated in provider foreground IP.')
span('E45', S, '17.1–17.4: confidentiality purpose, disclosure and exceptions', '17.1\nConfidentiality', '17.5\nExpiration:',
     'Confidential Information use is confined to proper contractual performance. Specific written disclosure consent and actual confidentiality exceptions have narrower functions.')
span('E46', S, '17.5–17.6: survival and return', '17.5\nExpiration:', '18\nWARRANTIES',
     'Confidentiality duration and return or destruction constrain indefinite retention. Trade secrets and IP-related material have longer protection.')
span('E47', S, '18.6: AI warranty disclaimer and AI Outputs definition', '18.6\nWarranty', '18.7\nOwnership',
     'The agreement contemplates customer models and AI Outputs. The disclaimer allocates responsibility and supplies no provider content-use grant.')
span('E48', S, '18.19: site-specific location warranty', '18.19\nLocation', '19\nINDEMNITY',
     'Physical servers, storage, networks and backups must remain in the selected Permitted Territory. Hardware outside it requires express written consent.')
span('E49', S, '23.5–23.6: amendments and survival', '23.5\nAmendment:', '32\nCommercial in confidence',
     'MSA variations need written signatures from duly authorised representatives of each party. Confidentiality and IP survive termination.')
span('E50', S, '23.7: subcontracting tension', '23.7\nAssignment:', '23.8\nNotices:',
     'The general subcontract provision conflicts with the prior-consent language in 2.7. The selected no-external-model design avoids reliance on that conflict.')
span('E51', S, '23.8: notice mechanics', '23.8\nNotices:', '33\nCommercial in confidence',
     'Formal communications have delivery and receipt mechanics. A consent draft cannot substitute for actual signed variation or required delivery.')
span('E52', S, '23.12: audit content exclusion', '23.12\nAudit:', '23.13\nWaiver:',
     'Audit rights expressly exclude provision of Customer Data. Audit cannot serve as a pretext for the proposed copilot content use.')
span('E53', S, 'Schedule 3: backup security', 'Backup\nManagement, Disaster Recovery', 'Change\nManagement',
     'Backup security measures do not create a customer-backup service or permit raw training retention. Any offsite backup must respect site residency terms.')
span('E54', S, 'Schedule 5 AUP 3.3–3.7: AI and workload restrictions', '3.3\nMisuse', '4.\nEthical',
     'Customer AI is contemplated but prohibited AI purposes, privacy violations, high-risk AI and infrastructure abuse remain excluded.')
span('E55', S, 'Schedule 5 AUP 4–5: customer responsibility and compliance monitoring', '4.\nEthical', '6.\nViolations',
     'Customers retain responsibility for inputs and outputs. Compliance investigations and lawful demands are distinct from routine support inference or shared training.')
span('E56', S, 'Schedule 5 AUP 7–8: modifications', '7.\nModifications\nto AUP', 'Schedule\n6',
     'The AUP has its own posting or email amendment mechanism. It is not an AI launch-notice or permission route.')
span('E57', S, 'Schedule 7: sovereignty and SLA modifications', 'Australia-Specific\nCommitments', 'END\nOF ANNEXURES',
     'Australian processing and a 30-day SLA update notice concern their own subjects. The notice does not authorise content access or training.')
span('E58', S, 'Included Service Order No.1: delivery, start and grace period', '7.\nDelivery\nDate', '10.\nLiquidated',
     'The included order has planned delivery and conditional service commencement. The planned dates do not prove commissioning.')
span('E59', S, 'Included Service Order No.1 Special Conditions 4.4', '4.4\nFailure to Provide or Maintain Security', '4.5\nRecourse',
     'Security failures can suspend or delay performance. No payment, security compliance or live service state can be inferred from the proposal.')
span('E60', S, 'Included Service Order Appendix A 6–7: changes and acceptance', '6.\nChange\nControl & Exclusions', '-9-\nAppendix',
     'Operational change powers concern the infrastructure work and defined acceptance. They do not replace the express content restriction.')
span('E61', S, 'Included Service Order Appendix B: Customer Tools and Platform', 'Customer\nTools and Platform', 'Tax\nNotwithstanding',
     'Customer tools may require technical diligence, reasonable limits and Additional Fees. The supplied platform statement does not establish integration approval.')
span('E62', S, 'Included Service Order Appendix F Part 2: bare metal', 'Part\n2 – Service Descriptions', 'Cooling\nRequirement',
     'The customer manages the OS and application layers. The provider manages hardware faults. This supports a workload-confidential customer AI architecture.')
span('E63', S, 'Included Service Order Appendix F: compute and storage responsibility', 'Compute\n- Service\nHW', '-16-\nAppendix',
     'Hardware monitoring and customer-managed storage are distinct from provider interpretation of workload content. Shared OOB creates an implementation boundary to test.')
span('E64', S, 'Included Service Order final execution block', 'This\nService Order is executed as an agreement by its duly authorised representatives\nSigned', '-22-',
     'The acquired order execution block lists names and titles but no completed signatures. This exhibit is not proof of an executed applicable Service Order.')
span('E65', S, '8.1.1–8.1.13: general restrictions and security tests', '8.1.1\nRestrictions:', '8.2\nMonitoring:',
     'General third-party restrictions require reconciliation with the express resale grant. High-risk uses remain restricted. Platform security tests need prior written consent.')
span('E66', J, '13.4–13.5: privacy and compliance', '13.4Privacy and Data Protection.', '13.6Publicity.',
     'Privacy duties have an express processing and data-subject scope. Applicable law and safety or security policies remain constraints, without inferred applicability.')
span('E67', S, '1.1: Foreground Intellectual Property Rights', '“Foreground\nIntellectual Property Rights”', '“Installation\nStage”',
     'The foreground definition is broad and includes rights connected to customer use. Operational model control does not establish ownership of newly created IP.')

precedence = [
    dict(higher_document_id=A, lower_document_id=J,
         scope='First Amendment expressly named definitions, section 5.1(b), section 12.1, Exhibit B-1 section 1 and Exhibit E sections 1.3–1.4 only',
         reason='The instrument expressly deletes, replaces or adds these provisions. Clause 6 preserves all other terms. Later replacement by the Second Amendment limits continued reliance.',
         evidence_ids=['E19', 'E20', 'E15']),
    dict(higher_document_id=B, lower_document_id=A,
         scope='Replacement section 5.1(b), section 12.1 and entire Exhibits B-1 and E, including prior amended portions',
         reason='The Second Amendment identifies the already amended JV and expressly replaces these same provisions. Dates alone do not determine precedence.',
         evidence_ids=['E19', 'E20', 'E21', 'E22']),
    dict(higher_document_id=B, lower_document_id=J,
         scope='BHGE designation, added Year 4 and Year 5, section 5.1(b), section 12.1 and entire Exhibits B-1, E and F',
         reason='Clauses 1–7 expressly change these subjects. Clause 8 preserves the balance, including sections 8 and 9 and the main-body hierarchy. Restated E and F are not present in the supplied text.',
         evidence_ids=['E21', 'E22', 'E23', 'E16']),
]

unknowns = []


def unknown(uid, customer, description, resolution, ids):
    unknowns.append(dict(id=uid, customer_id=customer, description=description,
                         resolution=resolution, evidence_ids=ids))


unknown('U1', 'c3-bhge',
        'The operative customer and use route are not established. The separate April 29, 2019 internal MSSA, orders and SOWs are absent.',
        'Obtain the complete executed internal MSSA and applicable orders for BH internal use. For a downstream customer, obtain its executed MSSA, order, SOW and governing amendments. Identify the exact licensee and operation.',
        ['E2', 'E3', 'E4', 'E7', 'E13'])
unknown('U2', 'c3-bhge',
        'The last supplied Initial Term ends April 30, 2024. No renewal exercise, extension, early termination record or current subscription state is supplied.',
        'Obtain the executed renewal or later amendment and its exercise record. Test the required commitment and internal subscription coverage. Separately establish surviving customer subscription rights.',
        ['E21', 'E13', 'E14'])
unknown('U3', 'c3-bhge',
        'Redacted provisions and referenced exhibits remain absent. The Second Amendment replaces Exhibit E and Exhibit F, but supplies neither replacement text.',
        'Obtain the applicable unredacted rights provisions and restated E and F. Obtain the actual offerings, MSSA, order, restricted-party and security terms necessary for this operation. Preserve remaining redactions explicitly.',
        ['E2', 'E3', 'E7', 'E16', 'E22'])
unknown('U4', 'c3-bhge',
        'No workload provenance, third-party rights, Sensitive Information designations, personnel permissions or 8.4 contribution record is supplied.',
        'Classify the proposed dataset and recipients. Obtain actual designated-recipient instructions and need-to-know confidentiality records. For any 8.4 route, obtain BH ownership and express identification or actual Feedback evidence plus the licensed purpose.',
        ['E8', 'E9', 'E10', 'E11'])
unknown('U5', 'c3-bhge',
        'The supplied set does not authorise arbitrary workload and support-log use for shared model training or indefinite model retention.',
        'Obtain a signed, purpose-specific data and model licence from the relevant rights holders. Address shared use, raw retention, model retention, confidential derivation, deletion and downstream rights. Alternatively prove a narrow existing 8.4 licence for each contribution and permitted development purpose.',
        ['E8', 'E10', 'E12', 'E15', 'E22'])
unknown('U6', 'sai-esds',
        'The included Service Order No.1 is not proof of execution or applicability. Its final signature fields are blank in the acquired text.',
        'Obtain the complete mutually executed applicable order, appendices, Product Specific Terms, Special Conditions and later signed changes. Confirm its parties and live term without inference from filing availability.',
        ['E29', 'E30', 'E33', 'E64'])
unknown('U7', 'sai-esds',
        'No signed variation permits the contracting Customer to use the Services for its own internal operational copilot. End-customer resale rights are distinct.',
        'For the exact proposed actor and purpose, obtain a signed internal-use variation. For the resale alternative, establish the actual End Customer, binding End Customer Contract and incorporated Terms and Conditions. Reconcile the general 8.1.3 third-party restriction with the specific 4.1–4.4 resale grant in the applicable terms. Do not substitute the Parent for the Customer.',
        ['E24', 'E25', 'E33', 'E34', 'E38', 'E49', 'E65'])
unknown('U8', 'sai-esds',
        'The elected Data Centre site, commissioning state, first-advance confirmation, security compliance and current service availability are absent.',
        'Inspect the executed site election and physical deployment record. Obtain the mutual Commissioning Certificate, cleared-advance confirmation and current security and suspension state. Resolve the certificate-form cross-reference mismatch from the actual signed certificate.',
        ['E26', 'E28', 'E31', 'E35', 'E42', 'E48', 'E58', 'E59'])
unknown('U9', 'sai-esds',
        'No integration diligence result or verified implementation proves that SAI cannot read content through the managed platform, OOB path or storage. New application IP ownership also needs scope review.',
        'Obtain the order-specific integration conditions and fee scope. Test customer-only key custody, protected runtime memory, console access, dumps, storage snapshots and telemetry with synthetic content. Observe the prior-consent requirement for platform security tests. Reconcile 15.2’s application-layer exclusion with 15.3 and the broad Foreground IPR definition before any ownership representation. Ciphertext alone does not protect content during inference.',
        ['E39', 'E41', 'E43', 'E61', 'E62', 'E63', 'E65', 'E67'])
unknown('U10', 'sai-esds',
        'Data rights, Personal Data exposure, confidentiality ownership and end-customer permission are not supplied for actual workloads or support material.',
        'Inspect the actual data inventory and rights records. Determine whether provider-visible material contains Personal Data or customer Background IPR. Obtain the actual end-customer authority where its data is involved.',
        ['E27', 'E34', 'E39', 'E40', 'E44', 'E45', 'E54', 'E55'])
unknown('U11', 'sai-esds',
        'No signed content-access variation overrides the 8.2 prohibition for provider support inference. An ordinary support entitlement is insufficient.',
        'Obtain a signed MSA amendment or expressly identified applicable Special Condition for the exact support purpose, data and model. Resolve clauses 8.2, 11.3, 11.6–11.7 and 17 expressly. A notice or disclosure consent alone does not supply that variation.',
        ['E30', 'E36', 'E37', 'E39', 'E40', 'E45', 'E49'])
unknown('U12', 'sai-esds',
        'The proposed shared-training dataset has no established content-use licence or retention exception. Actual qualifying feedback and excluded operational telemetry are not identified.',
        'For a changed shared-training proposal, obtain a signed variation and all actual data rights, with raw and model retention rules. For the separate useful route, classify genuine feedback, provider-generated non-content telemetry or independently sourced public materials. Exclude customer Background IPR from the feedback override.',
        ['E27', 'E37', 'E40', 'E43', 'E44', 'E45', 'E46', 'E49'])

feature = json.loads((WORK / 'feature.json').read_text())
ops = {op['id']: op for op in feature['operations']}
decisions = []


def decision(did, customer, operation, status, actor, data, purpose, model, conditions, rationale, eids, uids):
    decisions.append(dict(id=did, customer_id=customer, operation_id=operation, status=status,
                          actor=actor, data=data, purpose=purpose, model=model,
                          feature='Tenant Operations Copilot', conditions=conditions,
                          rationale=rationale, evidence_ids=eids, unknown_ids=uids))


decision('D1', 'c3-bhge', 'customer-controlled-inference', 'unresolved',
         'BH under its separate internal subscription, or the actual downstream enterprise customer under its own subscription. C3 supplies the platform.',
         'Customer-authorised operational workloads and technical documents. Customer-owned information differs from C3 Confidential Information and third-party confidential material under 9.1. Sensitive Information keeps its designated audience.',
         'Answer the contracting customer’s own internal operational questions. This is customer computation, not C3 content interpretation or shared model improvement.',
         'Customer-selected open-weight model in one customer-controlled Australian tenant. No separate model provider receives content. No C3 content access, decryption key, prompt retention or provider training.',
         [
             'Resolve the actual internal or downstream subscription and its platform, model, application and data rights under U1–U3.',
             'Keep C3 without plaintext access, including the runtime, console, diagnostic and storage paths. Apply the actual agreement to customer-controlled storage.',
             'Limit users to the actual subscription and source permissions. Preserve third-party rights and Sensitive Information designations.',
             'Do not apply the external resale noncompetition rule as a blanket prohibition on internal customer AI. Do not infer an unrestricted model licence from the preferred-platform statement.',
             'Review the actual Australian deployment, security and any personal-data terms in the operative subscription before an eligibility change.'
         ],
         'The strongest design keeps inference and keys with the customer. The JV defines an AI platform and identifies internal use, but it does not supply the operative subscription grant. The internal MSSA remains separate, and downstream rights have their own contracts. The Second Amendment sets an April 30, 2024 Initial Term. That date proves neither current renewal nor the extinction of surviving subscriptions. Therefore the exact proposal remains unresolved, rather than prohibited merely because it uses AI. Reassess on the actual subscription and current rights record.',
         ['E1', 'E2', 'E3', 'E4', 'E5', 'E7', 'E8', 'E9', 'E10', 'E11', 'E13', 'E14', 'E21', 'E22', 'E66'],
         ['U1', 'U2', 'U3', 'U4'])

decision('D2', 'c3-bhge', 'provider-support-inference', 'unresolved',
         'C3.ai as the actual contracted support provider. BH’s distribution role does not itself establish downstream disclosure rights.',
         'The same customer’s workload content and confidential technical documents. Third-party information and Sensitive Information retain the restrictions in sections 9.1–9.3.',
         'Answer that same customer’s support question within actual support performance. No product-wide improvement or cross-customer use.',
         'C3-operated tenant-isolated open-weight model in Australia. C3 and its model interpret content. No external model recipient, provider training or prompt/output retention beyond the response session.',
         [
             'Establish that the exact support task and data access are required for a right or obligation under the applicable agreement.',
             'Resolve the missing internal or downstream MSSA, SOW and restated development exhibit before any launch.',
             'Restrict personnel and service identities by need to know. Honour Sensitive Information’s written individual or job-function designation.',
             'Apply the actual restricted-recipient and confidentiality terms. No separate external model recipient is part of this proposal.',
             'Enforce tenant isolation and session deletion across caches, model servers, diagnostics, traces and backups. Do not retain content for training.',
             'Use the customer-controlled route in D1 where provider content access cannot be supported, subject to D1’s independent subscription review.'
         ],
         'Confidential support can fit section 9.2 when it is required contractual performance. Confidentiality does not impose a universal new AI-consent requirement. The supplied set does not establish that support scope or an applicable current customer agreement. Tenant isolation and no training reduce use but do not create the missing permission. The 8.4 technology licence is unnecessary for genuinely authorised support and cannot substitute for absent support terms. Keep the provider route unresolved until that scope is established.',
         ['E2', 'E3', 'E4', 'E6', 'E8', 'E9', 'E10', 'E11', 'E12', 'E13', 'E14', 'E21', 'E22'],
         ['U1', 'U2', 'U3', 'U4'])

decision('D3', 'c3-bhge', 'provider-shared-training', 'needs_consent',
         'C3.ai as a provider of a shared support model. BH cannot license a downstream customer’s rights through its JV role alone.',
         'Arbitrary customer workloads, support logs and confidential technical information as proposed. These are not automatically BH Provided Technology or Feedback.',
         'Improve C3’s shared support model for other customers. This purpose differs from the same customer’s support response.',
         'C3-owned shared model, trained and hosted in Australia. No external model provider. Raw examples persist for 30 days and the model indefinitely.',
         [
             'Obtain a signed, purpose-specific grant for the actual dataset and shared model use unless a complete existing scoped licence proves that use.',
             'Do not equate ordinary workload upload with an express BH-owned technology contribution under 8.4.',
             'Do not equate support logs with Feedback without actual qualifying content and provenance.',
             'Resolve the missing restated Exhibit E before reliance on development obligations. The original roadmap generalization clauses no longer supply operative authority.',
             'Address raw examples, checkpoints, learned derivatives, deletion requests, return duties and indefinite model retention in the exact grant.',
             'Verify all downstream rights, Sensitive Information recipients and current agreement scope. A BH-only signature cannot clear unrelated customer rights.'
         ],
         'The proposal changes both the beneficiary and the persistence of confidential information. Section 9.2 supplies no general cross-customer training grant. Section 8.4 can support useful reuse of expressly contributed BH-owned technology or actual Feedback for its named purposes. It does not automatically cover every workload or support record. The original Exhibit E’s review-for-generalization language is also weaker than a training licence and was replaced in full. Consent here means a scoped contractual grant or amendment from the actual rights holders, not generic owner approval. A useful alternative trains on independently created provider materials or demonstrably licensed contributions, with a separate dataset decision.',
         ['E7', 'E8', 'E9', 'E10', 'E11', 'E12', 'E14', 'E15', 'E16', 'E17', 'E18', 'E20', 'E21', 'E22'],
         ['U1', 'U2', 'U3', 'U4', 'U5'])

decision('D4', 'sai-esds', 'customer-controlled-inference', 'needs_consent',
         'SPOCHUB and ESDS Cloud as the contracting Customer. An End Customer under a resale contract is a distinct permitted actor. The Parent is separate.',
         'Customer-authorised workloads and confidential technical documents in a customer-controlled tenant. Customer Data includes submitted models and documents. Provider-generated non-content telemetry is excluded.',
         'Answer the contracting Customer’s own internal operational questions, exactly as proposed. The separate resale alternative answers an End Customer’s internal questions.',
         'Customer-selected open-weight model on Australian compute, with customer-only content access and keys. No external model provider, SAI training or retained provider prompts.',
         [
             'For the exact direct internal-use purpose, obtain a signed variation to the resale-only grant in clauses 4.3 and 4.8(a).',
             'Alternatively implement the copilot for a verified End Customer under a valid resale order and End Customer Contract. This actor-purpose change needs a fresh operation assessment.',
             'Resolve the executed order, applicable Special Conditions, selected Data Centre site, commissioning, first advance and service availability.',
             'Keep SAI unable to read, reconstruct or interpret Customer Data through all operational paths, including OOB and diagnostics.',
             'Resolve customer-tool diligence, reasonable technical conditions and Additional Fees under the applicable order.',
             'Maintain input rights, user authentication, customer backup duties and the AUP. Do not provide Customer Personal Data to SAI or assume a new processor role.'
         ],
         'The contract contemplates customer AI workloads and excludes certain application-layer rights from 15.2. Broad foreground ownership still requires scope review before any ownership promise. The content-access ban therefore does not prohibit customer-controlled AI as a category. However, the exact proposed contracting-customer internal purpose conflicts with clauses 4.3 and 4.8(a), which permit use solely for resale. The broad machine-learning infrastructure definition cannot erase that purpose restriction. A signed internal-use variation is required for this exact operation. The strongest existing-contract alternative serves a verified End Customer’s internal business through the reseller. Read the general 8.1.3 third-party restriction within the specific resale grant, rather than silently deleting either provision. Confirm their reconciliation in the operative terms. That route still needs the actual executed order, rights and service state. No eligibility is asserted from the sample order or its dates.',
         ['E24', 'E25', 'E26', 'E27', 'E28', 'E29', 'E30', 'E31', 'E32', 'E33', 'E34', 'E35', 'E37', 'E38', 'E39', 'E40', 'E41', 'E42', 'E43', 'E47', 'E48', 'E49', 'E54', 'E55', 'E58', 'E59', 'E61', 'E62', 'E63', 'E64', 'E65', 'E67'],
         ['U6', 'U7', 'U8', 'U9', 'U10'])

decision('D5', 'sai-esds', 'provider-support-inference', 'needs_consent',
         'SAI AU NO.2 PTY LTD as the service provider and model operator. The contractual Customer and actual data rights holders must authorise a changed content-access arrangement.',
         'Customer workload content and confidential technical documents. Their contents remain Customer Data despite support use. A content-bearing log does not become telemetry by a new label.',
         'Read and interpret content to answer the same customer’s support questions. This is distinct from hardware-fault monitoring or non-content quantitative analytics.',
         'SAI-operated tenant-isolated open-weight model in Australia. SAI can read content. No external model provider, training or retention beyond the response session.',
         [
             'Obtain a signed amendment or expressly identified applicable Special Condition that permits this exact provider content-access purpose.',
             'Expressly reconcile 8.2, 11.3, 11.6–11.7 and 17.2. A confidentiality agreement, zero retention or notice alone cannot override the content prohibition.',
             'Exclude Customer Personal Data unless a separate signed data-role arrangement and actual lawful authority cover it. The current MSA does not contemplate that provider role.',
             'Confirm actual customer or End Customer rights, scope of support, recipients, deployment site and order applicability.',
             'Preserve tenant separation, session deletion, no provider training and no external model recipient.',
             'Use provider-generated hardware telemetry and provider-owned support manuals for a separate metadata-only support design. Keep content-rich diagnosis within the customer-controlled tenant.'
         ],
         'Clause 8.2 expressly permits improvement analytics and then bars access or interpretation of Customer Data content notwithstanding other agreement or order terms. The proposed support model performs exactly that barred interpretation. Clause 7 support and clause 17 permitted personnel disclosure do not create an exception to 8.2. AUP compliance investigations and legal demands are separate limited purposes. This route needs a signed contractual variation, rather than a launch notice. A useful support copilot can instead use non-content hardware signals and provider-owned manuals while the customer retains content-rich diagnosis. That alternative must not silently ingest workload logs.',
         ['E27', 'E28', 'E30', 'E31', 'E36', 'E37', 'E39', 'E40', 'E41', 'E44', 'E45', 'E48', 'E49', 'E51', 'E52', 'E55', 'E57', 'E61', 'E62', 'E63'],
         ['U6', 'U8', 'U10', 'U11'])

decision('D6', 'sai-esds', 'provider-shared-training', 'off',
         'SAI AU NO.2 PTY LTD as the owner and operator of a model that serves multiple customers.',
         'Customer workload content, content-bearing support logs and confidential technical material. Provider-generated non-content telemetry and genuine Customer Feedback require separate classification.',
         'Improve SAI’s shared support model across customers. This exceeds the same customer’s support session and introduces indefinite model retention.',
         'SAI-owned shared model trained and hosted in Australia. Raw customer examples persist for 30 days. The trained model persists indefinitely. No separate model provider receives content.',
         [
             'Keep this exact workload-content training path off under the supplied terms and facts.',
             'Do not use foreground ownership, the AI Outputs definition or service-improvement monitoring as a blanket training licence.',
             'Do not relabel customer-submitted or content-bearing logs as excluded provider-generated operational telemetry.',
             'Preserve the specific any-purpose Customer Feedback override in 15.4 only for actual qualifying feedback and its stated Background IPR exclusion.',
             'For a materially changed content-training proposal, obtain a signed scope and data-role variation plus all dataset rights and retention rules before reassessment.',
             'Develop a separate improvement corpus from genuine qualifying feedback, lawful non-content provider telemetry and independently sourced provider or public materials. Do not assume de-identification or permission.'
         ],
         'The exact proposal fails the 8.2 content prohibition and the confidentiality-purpose limitation. No assumed consent or de-identification cures either issue. Broad foreground IP ownership does not authorise the prior content access that creates a model. Indefinite model retention also needs treatment under return and confidentiality duties. The strongest counter-reading is 15.4’s express any-purpose override for Customer Feedback. Preserve that useful route for actual suggestions and its Background IPR exclusion, but reject its extension to arbitrary workloads and support logs. Non-content operational analytics under 8.2 also remains useful. A changed, signed content-training arrangement would require a new assessment.',
         ['E27', 'E30', 'E31', 'E37', 'E39', 'E40', 'E43', 'E44', 'E45', 'E46', 'E47', 'E48', 'E49', 'E52', 'E53', 'E54', 'E55'],
         ['U6', 'U8', 'U10', 'U12'])

controls = []
for d in decisions:
    op = ops[d['operation_id']]
    facts = {**op['proposed_facts'], 'purpose': op['purpose'], 'model': op['model'],
             'training': op['training'], 'retention': op['retention']}
    controls.append(dict(decision_id=d['id'], customer_id=d['customer_id'], operation_id=d['operation_id'],
                         proposed_eligible=False, required_facts=facts,
                         reason=f"{d['id']} has status {d['status']} and unresolved source prerequisites. Eligibility is false. "
                                'The literal facts describe the proposed operation only. They assert no signed order, consent, current contract, site election or actual deployment. '
                                'Resolve the decision’s named unknowns and author a revised source-bound decision before any eligibility change.'))

engineering = [
    dict(id='ENG1', title='Implement the customer-controlled copilot without provider content access',
         body='Evidence E1–E3, E26, E37, E39, E61–E63 supports a customer computation route with separate licence and integration prerequisites. '
              'Build the model runtime, retrieval index and document parser inside the customer tenant. Keep document ACLs attached to every chunk and response. '
              'Use customer-held keys and a runtime that excludes provider administrative plaintext access. If the platform cannot prove runtime exclusion, do not claim this design meets the feature facts. '
              'Use local simulation for this export. Any later platform security test needs the prior written consent required by 8.1.13 and the AUP. '
              'Exclude payloads from hardware telemetry, support bundles, traces, crash dumps, console recordings and snapshots. Provide aggregate hardware health to SAI without prompts or workload content. '
              'Keep customer storage and its backup duties separate from ephemeral inference retention. Resolve the actual Data Centre site for all replicas. '
              'For SAI, choose the verified End Customer resale route unless a signed direct internal-use variation exists. For C3, bind the actual internal or downstream subscription. '
              'This is an implementable ticket. No production runtime or contract right is claimed by this export.',
         acceptance_criteria='Use synthetic documents with unique markers and two users with different ACLs. The authorised user receives the correct source-bound answer. '
                             'The other user receives no source text or derived answer. Provider service identities cannot obtain markers from storage, memory, OOB, logs, dumps or backups. '
                             'Network traces show no external model transfer. All storage and compute resolve to the elected site. '
                             'A missing subscription, resale authority, integration result or commissioning record leaves the corresponding proposed rule false.',
         decision_ids=['D1', 'D2', 'D4', 'D5']),
    dict(id='ENG2', title='Separate metadata support from content support at the ingestion boundary',
         body='Evidence E27, E36–E40, E45, E52 and E55 distinguishes hardware support from content interpretation. '
              'Create an explicit allowlist for provider-generated non-content counters, hardware error codes, capacity signals and provider-owned runbooks. '
              'Reject arbitrary log bodies, command output, memory dumps, file names with user content, document snippets and prompt or completion fields. '
              'Attach origin, producer, schema version, confidentiality class and source purpose to every event. Treat an unknown producer or a mixed event as content. '
              'A metadata copilot can diagnose infrastructure and propose actions for the customer administrator. It cannot read customer workloads. '
              'Keep the content-support operation false until D2’s actual support scope or D5’s signed variation resolves. A metadata-only alternative does not flip that operation’s existing flag.',
         acceptance_criteria='A clean hardware fault counter reaches the metadata copilot. A customer-uploaded log and a provider log with an embedded customer prompt are rejected. '
                             'A renamed telemetry field still fails the origin and content checks. A same-customer, zero-retention content request leaves D5 false. '
                             'The metadata route returns a runbook-backed hardware recommendation without a customer-content marker.',
         decision_ids=['D2', 'D5', 'D6']),
    dict(id='ENG3', title='Create a rights-aware improvement corpus with distinct contribution classes',
         body='Evidence E8, E10, E12, E22, E27, E37 and E43–E46 supports narrower useful improvement routes. '
              'Keep four dataset classes separate: independent provider or public materials, non-content provider telemetry, qualifying feedback, and customer content. '
              'For C3 contributions, record BH ownership, express identification or actual Feedback, the 8.4 licence and the named development or commercial purpose. '
              'For SAI feedback, record the actual suggestion, its sender authority and the 15.4 scope. Exclude customer Background IPR from that override. '
              'The 15.5 licence requires actual incorporation into foreground IP. It is not a licence to all customer background material. '
              'Never accept workload records merely because they accompany a bug report. Split the abstract suggestion from attached content. '
              'Keep confidential examples and derived checkpoints linked to provenance and retention obligations. Use independently authored synthetic cases for test data. '
              'Customer-derived synthetic data is not independent merely because a model rewrites it. Raw-content shared training remains false for both customers.',
         acceptance_criteria='An abstract feature suggestion with documented rights enters only its qualified feedback class. '
                             'An attached private stack trace and a document with customer Background IPR remain excluded from that class. '
                             'An 8.4 contribution without express identification or BH ownership fails. A model checkpoint without complete dataset lineage cannot enter the shared-model registry. '
                             'No raw customer example appears in the independent synthetic corpus.',
         decision_ids=['D3', 'D6']),
    dict(id='ENG4', title='Bind each operation to the exact agreement, actor, purpose and service state',
         body='Evidence E2–E4, E7, E13, E19–E23, E24, E28–E35, E42, E49 and E58–E64 defines the resolution requirements. '
              'Use a per-operation record for the legal customer, licensed actor, data class, purpose, model operator, model recipient, training role, region and retention. '
              'Store evidence references for the actual executed subscription or order, incorporation, signed changes, selected site and commissioning. Unknown is a distinct state. '
              'Apply the First and Second Amendment replacements by their expressed subjects. Do not restore the old Exhibit E when the restatement is absent. '
              'Within the SAI document, record the 2.4 hierarchy as Special Conditions, MSA, then ordinary Service Order terms, only at actual conflicts. '
              'The JSON precedence array cannot encode a self-edge for sections inside one source document. Keep this internal hierarchy with its exact E30 evidence here and in the decision conditions. '
              'Reconcile the specific resale grant with the general 8.1.3 restriction. Preserve the actual authorised resale scope. '
              'Keep operational control separate from IP ownership. Reconcile 15.2, 15.3 and the Foreground IPR definition before any model-ownership promise. '
              'Do not fabricate a separate document ID for an appendix. Preserve the MSA Customer and Parent roles where the included order uses a different shorthand. '
              'Resolve source contradictions before any new external-model or subcontractor design. Clauses 2.7 and 23.7 conflict on consent, but no external model recipient is proposed. '
              'Missing records must select a false proposed rule rather than an invented fact. The receiver stores the assessment, not a customer-contract clearance.',
         acceptance_criteria='The 2019 term stops at April 30, 2022 under the First Amendment and then April 30, 2024 under the Second. '
                             'Neither value proves a renewal or a surviving subscription’s end. The original roadmap clauses stay superseded. '
                             'A lower ordinary order term cannot override 8.2. An expressly identified signed Special Condition applies only to its conflicting subject. '
                             'An unsigned order, an Australian country label without a site, or a planned start date fails the prerequisite check.',
         decision_ids=['D1', 'D2', 'D3', 'D4', 'D5', 'D6']),
    dict(id='ENG5', title='Compile and verify the exact local OpenFeature assessment and SQLite receiver',
         body='Use the supplied validator and compiler without source or tool changes. Export exactly one decision and one control for each of the six customer-operation pairs. '
              'All six proposed_eligible values remain false because each exact operation has an unresolved prerequisite or an unsupported purpose. '
              'The literal required_facts values describe the supplied hypothesis. They do not attest to contract or deployment state. '
              'Exercise the actual OpenFeature SDK for each pair, an unknown customer and missing facts. Compare the SQLite bundle and export with the authored JSON and compiled export. '
              'Add isolated synthetic rule tests for an eligible test rule. Test mismatched actor, purpose, provider access, training and types. '
              'Synthetic positive tests must not change the customer export or enter the assessment receiver. Report their scope separately. '
              'Generate the OPA policy as supplied. Do not claim an OPA runtime test unless an actual OPA executable evaluates it.',
         acceptance_criteria='Validation verifies every exact quote and complete pair coverage. Compilation produces the requested files and 18 actual SDK evaluations. '
                             'The real export evaluates all six complete proposed contexts as false. SQLite contains an exact bundle and export with the same canonical bundle hash. '
                             'A synthetic eligible rule evaluates true only for its complete typed facts. Missing, altered, null and numeric substitutions fail. '
                             'No customer account, live feature or external recipient changes.',
         decision_ids=['D1', 'D2', 'D3', 'D4', 'D5', 'D6']),
    dict(id='ENG6', title='Preserve source coverage and exact limits in the decision packet',
         body='C3 base agreement: the platform and distribution terms frame the actors but do not license every use. '
              'The noncompetition and preferred-platform terms do not prohibit all internal customer AI. Technology ownership, 8.4 and sections 9.1–9.5 remain material. '
              'The separate internal MSSA and downstream agreements survive as separate sources. The First Amendment changes its listed periods, calculations and roadmap subsections. '
              'The Second Amendment replaces the term and entire B-1, E and F. Its supplied B-1 includes redacted conditions. Missing restatements remain missing. '
              'Revenue commitments, distribution exclusivity, trademarks, indemnity, warranty and dispute machinery do not independently authorise content use. '
              'C3 return and survival terms prevent a silent indefinite-retention inference. Its feature-change power in E6 is not a data licence. '
              'Preserve the quarterly feature-update information duty if an actual applicable feature change occurs. This hypothesis triggers no separate AI launch notice. '
              'SAI: definitions, resale grant, content prohibition, residency, keys, personal-data roles, feedback and IP, confidentiality, AUP and operational readiness drive the decisions. '
              'The AUP recognises customer AI and preserves its prohibited-use boundaries. AUP compliance monitoring and compelled disclosure do not authorise ordinary support or training. '
              'AUP changes and SLA changes use different amendment mechanisms. Neither creates a copilot launch-notice requirement. '
              'Infrastructure maintenance has separate scope and notice terms. Those terms do not authorise content use. '
              'The backup security schedule does not create a backup service against 11.2 or permission for out-of-site copies. '
              'The included order’s platform, tools, hardware-only support, customer-managed storage and OOB terms define the engineering boundary. Its empty signature fields do not establish execution. '
              'Special security, financing/KYC, termination, tax, pledge and indemnity clauses affect payment or service-state risk, not a general AI data licence. '
              'The pledge is a separate security purpose with redacted financial fields. No values or fulfilment are inferred. '
              'Subcontractor consent language conflicts within the MSA. Keep that question open for a changed third-party design instead of a date-based precedence guess. '
              'No source declares legal applicability, present contract status, end-customer approval or actual deployment merely through public availability. '
              'The decision can change only when the named rights, actual source or operation facts change. Exact provenance validation does not prove interpretive correctness.',
         acceptance_criteria='The packet contains evidence from all four original documents. Every material decision and cross-document precedence edge cites source evidence. '
                             'It distinguishes customer AI, provider support and shared training by actor and purpose. '
                             'A reviewer can locate the missing sources and the strongest counter-reading for each blocked useful route. '
                             'No notice draft appears solely because the feature uses AI. Public-sample scope remains explicit throughout the export.',
         decision_ids=['D1', 'D2', 'D3', 'D4', 'D5', 'D6']),
]

drafts = [
    dict(type='information_request', customer_id='c3-bhge',
         reason='The JV points to separate subscription and customer agreements. The Second Amendment replaces exhibits absent from the acquired text. These sources can resolve U1–U4.',
         draft='Conditional preparation for the actual contract owner: Please provide the complete executed agreement set for the proposed Tenant Operations Copilot. Include the applicable internal or downstream MSSA, order, SOW, later amendments and renewal records. Please also provide the restated Exhibits E and F and the applicable data, security and recipient restrictions. Identify the contracting customer, licensed users, support scope and any designated Sensitive Information audience. For an 8.4 contribution, include the ownership, express contribution record and permitted use. Keep unneeded personal and financial values redacted.',
         unknown_fields=['actual contract owner and recipient', 'internal or downstream agreement route', 'operative agreement and order identifiers', 'current term and renewal records', 'restated exhibits and relevant redacted terms'],
         evidence_ids=['E2', 'E3', 'E7', 'E8', 'E11', 'E13', 'E21', 'E22']),
    dict(type='consent', customer_id='c3-bhge',
         reason='Shared use of arbitrary confidential workload content lacks the required purpose-specific grant. Sections 9.2, 9.4 and 13.13 require a scoped contractual solution where no existing licence covers it.',
         draft='Conditional amendment terms for the actual contracting parties: C3.ai may use only the data listed in the executed data schedule to train the named shared support model. The schedule must identify each rights holder, authorised data category and confidential-information restriction. The model may serve other customers only within the agreed model-use scope. Raw examples may remain for 30 days. Any indefinite model retention requires an express term that addresses derived confidential information, return, deletion and later cessation of use. No downstream rights or Sensitive Information permissions arise by implication. Existing terms continue outside this exact scope. This proposal takes effect only through the applicable signed instrument and the identified rights holders’ grants.',
         unknown_fields=['actual parties and rights holders', 'dataset and exclusions', 'named model and uses', 'permitted recipients', 'effective date', 'model retention and deletion treatment', 'signed instrument and applicable subscription'],
         evidence_ids=['E8', 'E9', 'E10', 'E11', 'E12', 'E15']),
    dict(type='information_request', customer_id='sai-esds',
         reason='The exact internal-use and provider-content proposals need operative order, actor, site and readiness evidence. The acquired order is not proof of execution.',
         draft='Conditional preparation for the actual contract owner: Please provide the executed applicable Service Order with all appendices, Product Specific Terms, Special Conditions and later changes. Identify the elected Data Centre site and the actual Customer or End Customer use route. Include the mutual Commissioning Certificate and the confirmations that establish service availability, without bank or credential values. Please provide the customer-tool integration conditions and the data-rights record for the proposed copilot. Identify any signed exception to the resale-only purpose or provider content-access restriction.',
         unknown_fields=['actual recipient and authorised contract owner', 'executed order and applicable terms', 'selected Data Centre site', 'commissioning and service state', 'End Customer identity and permissions', 'integration diligence and fee scope', 'existing signed exceptions'],
         evidence_ids=['E24', 'E28', 'E29', 'E30', 'E33', 'E34', 'E35', 'E37', 'E42', 'E49', 'E58', 'E59', 'E61', 'E64']),
    dict(type='consent', customer_id='sai-esds',
         reason='The contracting Customer’s direct internal purpose needs a signed variation to 4.3 and 4.8(a). This is distinct from the provider support-access variation.',
         draft='Conditional variation terms for the actual contracting parties: The Customer may use the identified contracted capacity for Tenant Operations Copilot to answer its own internal operational questions. This permission varies clauses 4.3 and 4.8(a) only for that purpose and the specified users. The Customer controls its model and content. SAI receives no content, customer key, retained prompt or training right through this variation. The executed order must identify the permitted Data Centre site and integration conditions. All other usage, confidentiality, residency and data-rights requirements continue. The variation takes effect only when each required party signs the applicable written instrument.',
         unknown_fields=['applicable order and capacity', 'exact Customer entities and authorised users', 'effective date', 'elected site', 'integration terms', 'required parties and signatures'],
         evidence_ids=['E24', 'E30', 'E33', 'E34', 'E37', 'E49', 'E61']),
    dict(type='consent', customer_id='sai-esds',
         reason='Provider support inference reads Customer Data content barred by 8.2. A signed scoped variation must also address the current personal-data and confidentiality terms.',
         draft='Conditional variation terms for the actual contracting parties: SAI may process only the listed Customer Data and technical documents through the identified tenant-isolated support model. It may use them only to answer that same customer’s support questions. The agreed exception to clause 8.2 and clause 11.3 applies only to this support session. No separate model provider receives content. SAI retains no prompt or output after the session and obtains no training or cross-customer improvement right. The schedule must identify the permitted Data Centre site, authorised recipients and data rights. Customer Personal Data remains excluded unless a separate signed data-role arrangement and the necessary authority expressly cover it. Confidentiality continues under clause 17. The variation takes effect only through the applicable signed instrument.',
         unknown_fields=['applicable order', 'actual data rights holders and dataset', 'named model and access audience', 'permitted Data Centre site', 'effective date', 'personal-data exclusion or separate role arrangement', 'required parties and signatures'],
         evidence_ids=['E27', 'E28', 'E30', 'E36', 'E37', 'E39', 'E40', 'E45', 'E49']),
]

bundle = dict(
    assessment_type='proposed_source_bound_decisions', feature_id=feature['id'],
    summary='Assess all six exact operations as a hypothetical public-source proposal. C3 customer inference and provider support remain unresolved because the operative subscription, current rights and key exhibits are absent. '
            'C3 raw-content shared training needs a purpose-specific grant unless a complete existing scoped licence proves that use. '
            'SAI contracting-customer internal inference needs a signed purpose variation. SAI provider content support needs a signed content-access variation. SAI raw-content shared training stays off. '
            'The strongest useful architecture keeps content-rich inference with the authorised customer or verified End Customer and confines provider support to non-content telemetry and provider materials. '
            'Preserve qualifying feedback and expressly licensed technology as separate improvement routes. Do not relabel arbitrary logs or confidential workloads as either. '
            'All six exact proposed controls remain false. This export establishes neither current customer clearance nor actual outside use. No AI-specific launch notice is required by the supplied terms. '
            'The drafts are local conditional preparation only. Exact source verification checks provenance and consistency, not legal correctness.',
    evidence=evidence, precedence=precedence, decisions=decisions, unknowns=unknowns,
    controls=controls, engineering_outputs=engineering, notices_or_consent_drafts=drafts)

(WORK / 'model-decisions.json').write_text(json.dumps(bundle, ensure_ascii=False, indent=2) + '\n')
print(json.dumps({'decisions': len(decisions), 'controls': len(controls), 'evidence': len(evidence),
                  'engineering_outputs': len(engineering), 'unknowns': len(unknowns), 'drafts': len(drafts)}))
