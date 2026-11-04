"""Assemble model-authored judgments with verbatim excerpts from the fixed corpus.

This local authoring aid selects no interpretation or status from source keywords.
All judgments, scope relations, alternatives and work items below are authored.
"""
import json
from pathlib import Path

WORK = Path(__file__).resolve().parent
manifest = json.loads((WORK / 'source-manifest.json').read_text())
docs = {d['id']: d for c in manifest['customers'] for d in c['documents']}
texts = {key: (WORK / value['text_file']).read_text() for key, value in docs.items()}
BASE = 'c3-bhge:01-joint-venture-2019-06-06.html'
FIRST = 'c3-bhge:02-first-amendment-2019-09-26.html'
SECOND = 'c3-bhge:03-second-amendment-2020-06-01.html'
SAI = 'sai-esds:01-master-services-2026-03-31.html'
evidence = []


def cite(identity, document, section, start, end, supports, occurrence=0):
    source = texts[document]
    offset = -1
    for _ in range(occurrence + 1):
        offset = source.index(start, offset + 1)
    finish = source.index(end, offset + len(start)) if end else len(source)
    evidence.append(dict(id=identity, document_id=document, section=section, page=None,
                         quote=source[offset:finish].rstrip(), supports=supports))


cite('E1', BASE, '1.19, C3 Offering Internal BHGE Subscription',
     '1.19“C3 Offering Internal BHGE Subscription”', '1.20',
     'BHGE internal use depends on the separate April 29, 2019 MSSA and associated orders or SOWs.')
cite('E2', BASE, '1.12, C3 AI Suite', '1.12“C3 AI Suite”', '1.13',
     'The platform contemplates AI applications. This definition supplies neither a customer-specific license nor content-use permission.')
cite('E3', BASE, '1.46–1.48, MSSA and Order definitions', '1.46“MSSA”', '1.49',
     'Standard MSSA and Order forms are referenced. A form reference does not establish an executed downstream agreement.')
cite('E4', BASE, '8.1(b)(i)–(c), ownership and internal-subscription savings',
     '(b)BHGE.\ni.[***]', '8.2Marks Licenses.',
     'Redacted ownership text remains unknown. No implied BHGE technology license arises. Internal MSSA ownership terms remain distinct.')
cite('E5', BASE, '8.4, BHGE Technology License', '8.4BHGE Technology License.', '8.5',
     'Expressly provided BHGE-owned technology and qualifying Feedback receive a broad but object- and purpose-specific license.')
cite('E6', BASE, '9.1, Confidential Information and Sensitive Information',
     '9.1Confidential Information.', '9.2',
     'Nonpublic technical data and third-party confidences can be confidential. Sensitive Information has designated recipients. Exceptions require their actual predicates.')
cite('E7', BASE, '9.2, Non-Use and Nondisclosure', '9.2Non-Use and Nondisclosure.', '9.3',
     'Confidential information use must serve authorized agreement rights or obligations. Confidentiality and recipient restrictions remain material.')
cite('E8', BASE, '9.3, Disclosure to Employees', '9.3Disclosure to Employees.', '9.4',
     'Need-to-know, protective agreements, restricted-party exclusions and written Sensitive Information designations constrain access.')
cite('E9', BASE, '9.4, Return of Confidential Information', '9.4Return of Confidential Information.', '9.5',
     'Return or deletion and officer certification have express exceptions for intended section 8.4 use and necessary surviving obligations.')
cite('E10', BASE, '12.3(b), effect on existing customer and internal subscription rights',
     '(b)Expiration or termination of this Agreement shall not affect', '(c)For a period of six',
     'JV expiry alone does not terminate customer or internal subscription rights. Their respective agreements govern those rights.')
cite('E11', BASE, '12.4, Survival', '12.4Survival.', '13.GENERAL PROVISIONS',
     'IP and confidentiality provisions survive subject to stated limits. Survival is not proof of current subscription authority.')
cite('E12', BASE, '13.17–13.18, Exhibits and Entire Agreement', '13.17Exhibits.', '13.19',
     'Exhibits are incorporated. The JV body ranks above its exhibits for inconsistent subject matter.')
cite('E13', BASE, '13.13, Amendments and Waivers', '13.13Amendments; Waivers.', '13.14',
     'Amendments require both signatures. A signed waiver has only its expressly identified scope.')
cite('E14', FIRST, '1–4, year definitions, revenue calculation, term and Exhibit B-1 replacement',
     '1.Article 1 of the JV Agreement', '5.Sections',
     'Express changes establish Years 1–3, replace section 5.1(b), set the initial term through April 30, 2022, and replace the revenue table.')
cite('E15', FIRST, '5–6, Exhibit E 1.3–1.4 replacement and unchanged remainder',
     '5.Sections 1.3 and 1.4', '7.This Amendment',
     'Only the stated roadmap provisions change. Unamended terms remain intact at this amendment stage.')
cite('E16', SECOND, '1–2, BH nomination and Years 4–5', '1.Throughout the JV Agreement', '3.Section',
     'The amendment expressly replaces BHGE with BH and adds Years 4–5. File dates do not supply this effect.')
cite('E17', SECOND, '3–4, section 5.1(b) and section 12.1 replacement', '3.Section 5.l(b)', '5.Exhibit',
     'The new term runs through April 30, 2024. Further renewal requires BH action and the stated revenue and internal-subscription conditions.')
cite('E18', SECOND, '5–8, restated Exhibits B-1, E and F and unchanged remainder',
     '5.Exhibit B-1', '9.This Second Amendment',
     'The amendment replaces all of Exhibits B-1, E and F. The acquired exhibit supplies restated B-1 but not restated E or F.')
cite('E19', BASE, '6.1–6.2, Development and Changes to C3 Offerings', '6.1C3 Applications Development.', '7.ALLIANCE MANAGEMENT',
     'Development refers to Exhibit E. Offering changes have customer-functionality safeguards and quarterly BHGE information duties, not general data-use permission.')
cite('E20', BASE, '8.5, BHGE and C3 Responsibilities', '8.5BHGE and C3 Responsibilities.', '11\n9.CONFIDENTIALITY',
     'No unauthorized access, reverse engineering or offering modification follows from an AI platform definition.')
cite('E21', BASE, '13.4–13.5, Privacy and Data Protection and Compliance with Laws',
     '13.4Privacy and Data Protection.', '13.6Publicity.',
     'Privacy obligations depend on actual processing and applicable law. The filing does not establish data-subject or legal applicability facts.')
cite('E22', BASE, 'Original Exhibit E, 1.6 and 2, subsequently replaced in full',
     '1.6. C3.ai will train and enable', None,
     'The original roadmap contemplated generalization of analytics and workflows. Second Amendment section 6 replaces this entire exhibit.')

cite('E23', SAI, 'Opening party definitions', 'Between:\n1.', 'WHEREAS:',
     'SAI is Service Provider. SPOCHUB and ESDS Cloud together are Customer. ESDS Software Solutions is separately the Parent in the MSA.')
cite('E24', SAI, '1.1, Cloud Infrastructure', '“Cloud\nInfrastructure”', '“Cloud\nServices”',
     'Exclusive infrastructure for machine learning supports customer AI as a technical use class, subject to the separate permitted-purpose terms.')
cite('E25', SAI, '1.1, Confidential Information and Content', '“Confidential\nInformation”', '“Control”',
     'Confidentiality reaches operational and technical information. Content includes data, text, software and other media.')
cite('E26', SAI, '1.1, Customer Data', '“Customer\nData”', '“Data\nProtection Legislation”',
     'Customer-provided data is covered. Provider-system-generated logs, usage, telemetry and operational data are excluded from this definition.')
cite('E27', SAI, '1.1, Permitted Territory', '“Permitted\nTerritory”', '“Professional\nServices”',
     'Permitted Territory is the data-centre site in the relevant Service Orders. A country label alone does not resolve the site.')
cite('E28', SAI, '2.4, order of precedence', '\n2.4\n', '\n2.5\n',
     'Expressly identified Special Conditions rank above the MSA, then ordinary order terms, subject to express contrary language and only actual inconsistencies.')
cite('E29', SAI, '4.1–4.5, reseller appointment, permitted purpose, End Customer internal use and signatures',
     '\n4.1\n', '\n4.6\n',
     'The contracting Customer resells. Internal business use belongs to End Customers. Service Orders require the relevant customer and provider signatures.')
cite('E30', SAI, '4.7–4.8, End Customer Contracts and Authorised Users', '\n4.7\n', '\n4.9\n',
     'Resale remains the sole customer cloud purpose. Redacted End Customer contracts, authorized users and minimum requirements have explicit conditions.')
cite('E31', SAI, '8.2, Monitoring, including final proviso', '\n8.2\n', '\n8.3\n',
     'Service improvement and quantitative analysis do not permit access, reconstruction, deciphering or interpretation of Customer Data content, despite any Service Order.')
cite('E32', SAI, '11.1–11.2, data rights, encryption keys and backups', '\n11.1\n', '\n11.3\n',
     'The Customer warrants necessary data rights and bears the specified data, encryption-key and backup responsibilities.')
cite('E33', SAI, '11.3, Monitoring and Removal', '\n11.3\n', '\n11.4\n',
     'Routine content access is outside the stated service model. The specified legal or explicit obligation exceptions are not routine support permission.')
cite('E34', SAI, '11.5–11.7, Personal Data and intended roles', '\n11.5\n', '\n11.8\n',
     'The text does not contemplate provider access to Customer Personal Data or a provider controller/processor role for that data.')
cite('E35', SAI, '15.1–15.5, Background IPR, application exclusion, Foreground IPR and Feedback',
     '\n15.1\n', '\n15.6\n',
     'Foreground ownership and genuine Customer Feedback rights are substantial. Customer Background IPR and the application-layer exclusion require distinct analysis.')
cite('E36', SAI, '17.1–17.2, confidential purpose and particular disclosure consent', '\n17.1\n', '\n17.3\n',
     'Ordinary confidential use serves contractual performance. Particular disclosure consent does not itself amend the independent content-access prohibition.')
cite('E37', SAI, '17.5–17.6, confidentiality duration and return or destruction', '\n17.5\n', '\n18\n',
     'Confidentiality can survive and requested return or destruction has qualifications. Indefinite model retention does not automatically satisfy these terms.')
cite('E38', SAI, '23.5, Amendment', '\n23.5\n', '\n23.6\n',
     'A revised purpose or content-access bargain requires a written amendment signed by each Party, not a generic owner approval.')
cite('E39', SAI, 'Populated Service Order, final execution block',
     'This\nService Order is executed as an agreement by its duly authorised representatives\nSigned', None,
     'The supplied populated order contains signature labels and names but no visible signed entries. Actual execution remains unproved.')
cite('E40', SAI, 'Populated Service Order, incorporation and customer description',
     'SERVICE\nORDER\nThis\nService Order and its Appendices', 'Item\nReference\nData',
     'The populated order incorporates the MSA but describes Customer differently by also naming the Parent. This does not silently rewrite MSA role allocations.')
cite('E41', SAI, '5.1–5.4, commencement and commissioning', '\n5.1\n', '\n6\n',
     'Installation, co-testing, written confirmation and the mutually signed Commissioning Certificate govern commencement. Planned dates prove no completed state.')
cite('E42', SAI, '2.8(f)–(i), residency covenants as printed', '\n2.8\n', '\n3\nTERM',
     'Residency includes physical infrastructure and backups. Mandatory-law migration has a narrow ninety-day-notice rule. Printed cross-reference errors remain visible.')
cite('E43', SAI, '18.19, Location Warranty', '\n18.19\n', '\n19\n',
     'Infrastructure stays within the Permitted Territory. Customer consent for outside hardware is not a content-purpose authorization.')
cite('E44', SAI, 'Service Order Appendix F, Part 2, Bare Metal',
     'The\nService Provider will provision hardware and will monitor and manage hardware failures.', 'Cooling\nRequirement',
     'The Customer is responsible from the OS upwards and receives control-plane access. Provider hardware and OOB roles remain distinct.')
cite('E45', SAI, 'Service Order Appendix B, Customer Tools and Platform', 'Customer\nTools and Platform', '\nTax\n',
     'The standard provider portal remains relevant. Customer tools can require due diligence, technical conditions and Additional Fees.')
cite('E46', SAI, 'Schedule 7, Australia-Specific Commitments and SLA Modifications',
     'Australia-Specific\nCommitments & Data Sovereignty', 'END\nOF ANNEXURES',
     'Schedule 7 specifies Australian data centres. Its thirty-day SLA update mechanism is not an AI content-use notice route.')
cite('E47', SAI, 'Schedule 5 AUP, 4.5–4.6, outputs and training data responsibility',
     '\n4.5\nResponsibility', '\n5.\nMonitoring',
     'Customer-deployed AI is contemplated. The Customer bears input-rights and output responsibilities. This is not provider training authorization.')
cite('E48', SAI, '8.3, incorporated End Customer Terms and Conditions', '\n8.3\n', '\n9\n',
     'End Customer contracts must incorporate the defined Terms and Conditions throughout the order term.')
cite('E49', SAI, '23.12, Audit', '\n23.12\n', '\n23.13\n',
     'The audit clause expressly excludes Customer Data provision. Audit powers do not supply copilot training or support ingestion authority.')
cite('E50', SAI, '2.7, third-party engagement', '\n2.7\n', '\n2.8\n',
     'The text requires prior written Customer consent for third-party performance and further subcontracting.')
cite('E51', SAI, '23.7, final subcontracting proviso',
     'Notwithstanding\nthe foregoing, Service Provider may subcontract', '\n23.8\n',
     'A later clause permits subcontracting without consent despite its foregoing assignment text. Its relation to section 2.7 is not resolved by date or file order.')
cite('E52', SAI, '8.1.13, security testing', '\n8.1.13\n', '\n8.2\n',
     'Intrusive security tests of provider infrastructure require prior written provider consent. Local offline contract/export tests do not exercise that route.')
cite('E53', SAI, 'Service Order Appendix F, managed OOB',
     'The\nService Provider will provide credentials to a shared OOB platform', '-16-',
     'Shared managed OOB is not evidence of provider inability to access memory, disks, keys or workload plaintext.')
cite('E54', SAI, 'Schedule 5, 3.3, Misuse of AI and Machine Learning',
     '\n3.3\nMisuse', '\n3.4\n',
     'The AUP restricts specified model purposes and platform misuse. It does not ban all customer AI.')
cite('E55', SAI, '8.1.2–8.1.5, use and distribution restrictions', '\n8.1.2\n', '\n8.1.6\n',
     'A broad distribution prohibition coexists with the express reseller grant. A downstream implementation must preserve the narrow express grant and resolve any remaining conflict.')
cite('E56', SAI, 'Schedule 3, Backup Management, dataset recycling sentence',
     'Data sets on backup\ntapes are retained', '\n●',
     'A backup-media retention limit is not permission to retain training examples or use Customer Data for a new purpose.')


precedence = [
    dict(higher_document_id=FIRST, lower_document_id=BASE,
         scope='Year 1–3 definitions, section 5.1(b), initial term and renewal wording, and Exhibit B-1 section 1',
         reason='First Amendment sections 1–4 expressly add definitions or delete and replace the identified provisions. These changes do not alter confidentiality.',
         evidence_ids=['E14', 'E13']),
    dict(higher_document_id=FIRST, lower_document_id=BASE,
         scope='Exhibit E sections 1.3 and 1.4 before their later entire-exhibit replacement',
         reason='First Amendment section 5 expressly replaces these roadmap deadlines. Section 6 preserves the rest.', evidence_ids=['E15']),
    dict(higher_document_id=SECOND, lower_document_id=FIRST,
         scope='Section 12.1 initial term and renewal rights, and section 5.1(b) annual revenue periods',
         reason='Second Amendment sections 3–4 expressly replace the provisions previously replaced by First Amendment sections 2–3. April 30, 2024 replaces April 30, 2022.',
         evidence_ids=['E17', 'E14']),
    dict(higher_document_id=SECOND, lower_document_id=BASE,
         scope='BHGE nomination, added Years 4–5, section 5.1(b), and section 12.1 term and renewal requirements',
         reason='Second Amendment sections 1–4 expressly enact these changes. The renewal right is conditional, not evidence of its exercise.',
         evidence_ids=['E16', 'E17']),
    dict(higher_document_id=SECOND, lower_document_id=BASE,
         scope='Entire Exhibits B-1, E and F, with no replacement of JV sections 8 or 9',
         reason='Second Amendment sections 5–7 replace these exhibits in full. Section 8 preserves unamended terms. Missing restated E/F cannot revive superseded originals.',
         evidence_ids=['E18', 'E12', 'E22']),
    dict(higher_document_id=SECOND, lower_document_id=FIRST,
         scope='Exhibit B-1 section 1 and Exhibit E sections 1.3–1.4',
         reason='Entire-exhibit replacement supersedes the First Amendment partial replacements within those exhibits. It does not repeal untouched Year 1–3 definitions.',
         evidence_ids=['E18', 'E14', 'E15']),
]


def decision(identity, customer, operation, status, actor, data, purpose, model, conditions, rationale, refs, unknowns):
    return dict(id=identity, customer_id=customer, operation_id=operation, status=status,
                actor=actor, data=data, purpose=purpose, model=model,
                feature='Tenant Operations Copilot', conditions=conditions, rationale=rationale,
                evidence_ids=refs, unknown_ids=unknowns)


decisions = [
    decision('D1', 'c3-bhge', 'customer-controlled-inference', 'unresolved',
        'BH, formerly BHGE, under its actual internal subscription, or a downstream Customer under its own executed subscription. These roles are not interchangeable.',
        'The customer’s own operational workloads and technical documents, subject to actual ownership, third-party confidence and subscription rights. C3 receives no readable content.',
        'Answer that customer’s own operational questions for internal use.',
        'Customer-selected open-weight model inside its single tenant in Australia. No separate model recipient, provider training or provider prompt retention.',
        [
            'Identify the exact internal or downstream subscription, its orders, permitted users, deployment scope and current operative terms.',
            'Preserve the prohibition on unauthorized access, reverse engineering and offering modification. A customer application is not automatically an offering derivative.',
            'Keep content and decryption keys under customer control, as the proposal specifies. Verify these technical facts before any deployment claim.',
            'Preserve confidentiality and Sensitive Information limits for any other party’s information. Resolve third-party input rights from the applicable contract.',
            'Assess applicable privacy and security duties from actual data and processing facts. Australia is a proposed location, not a sourced JV residency approval.',
        ],
        'The supplied JV contemplates AI applications and identifies a separate BH internal subscription. It does not supply that subscription or an executed downstream MSSA. '
        'Therefore neither permission nor prohibition for this exact current deployment can be established. The strongest design is customer-controlled inference without C3 content access.\n\n'
        'The amended initial JV term ends April 30, 2024, but expiry does not itself extinguish surviving customer subscription rights. '
        'A renewal right or public filing cannot prove a current term. D1 remains unavailable in this export until the exact governing instruments resolve these prerequisites.',
        ['E1', 'E2', 'E3', 'E4', 'E6', 'E7', 'E8', 'E10', 'E11', 'E17', 'E20', 'E21'],
        ['U1', 'U2', 'U3', 'U4']),
    decision('D2', 'c3-bhge', 'provider-support-inference', 'unresolved',
        'C3.ai as the contracting service provider. BH is the discloser only for its own information. Downstream customers retain their separate contract position.',
        'Workload content, support logs and confidential technical documents for one customer. Sensitive Information and third-party confidences require separate recipient and use checks.',
        'Answer support questions for that same customer within an established contractual service obligation.',
        'C3-operated, tenant-isolated open-weight inference in Australia. No external model recipient, training or retained session content.',
        [
            'Confirm that the actual subscription, order or SOW permits this content access and support purpose.',
            'Limit confidential use to the extent required for authorized rights or obligations under the applicable agreement.',
            'Restrict human access to permitted need-to-know recipients with protective confidentiality agreements. Enforce written Sensitive Information designations.',
            'Enforce tenant isolation and session deletion across prompts, responses, indexes, traces and caches. No training path may receive these materials.',
            'Honor return or deletion obligations and their actual exceptions. Do not infer an unrestricted retention license from a support session.',
        ],
        'Section 9.2 is a purpose limitation, not a blanket prohibition on every provider AI inference. Authorized same-customer support may fit its performance route. '
        'The JV alone does not establish the required support scope, customer data license or permitted recipients. Zero retention and no external transfer do not create those rights.\n\n'
        'Use a provider-documentation and permitted noncontent diagnostic copilot while support content authority remains unresolved. '
        'Alternatively use D1’s customer-controlled route after its subscription prerequisites resolve. Neither alternative silently enables D2.',
        ['E1', 'E3', 'E6', 'E7', 'E8', 'E9', 'E10', 'E11', 'E17', 'E21'],
        ['U1', 'U2', 'U3', 'U4']),
    decision('D3', 'c3-bhge', 'provider-shared-training', 'off',
        'C3.ai as provider and shared-model owner. BH cannot grant another customer’s rights through the JV alone.',
        'The proposed mixture contains workload content, support logs and confidential technical information. No universal Customer Data training license appears in the supplied JV.',
        'Improve C3’s shared support model across customers, with thirty-day raw examples and indefinite model retention.',
        'C3-owned shared open-weight model, trained and hosted in Australia. No separate provider receives content. This remains provider training.',
        [
            'Exclude the proposed unqualified workload and confidential-document mixture from shared training.',
            'Use section 8.4 only for its actual objects: expressly supplied, identified BH-owned technology or qualifying Feedback, for its specified purposes.',
            'For BH Provided Technology, verify BH ownership and applicability to the BH Field. Feedback does not share the technology-specific express-identification requirement.',
            'Confirm the supplied objects, ownership and precise development or C3-offering purpose before any section 8.4 alternative receives a live assessment.',
            'Do not use superseded original Exhibit E generalization language as current authority. The restated Exhibit E is absent.',
            'Retain section 9.4 exceptions for authorized section 8.4 technology. Do not invent either universal deletion of licensed models or indefinite retention of unlicensed confidences.',
        ],
        'The exact mixed-content shared-training proposal lacks a supported grant and exceeds established confidential-use authority. It is off under the supplied record. '
        'Section 8.4 is a substantial useful alternative, not a blanket waiver: its broad license attaches to specified BH technology and Feedback.\n\n'
        'It does not automatically attach to every workload, log or downstream customer document. A qualifying corpus may support C3-offering development or commercialization within section 8.4. '
        'Object-level proof and the stated purpose remain necessary. Missing Exhibit E limits a development-specific assessment, not every commercialization route.\n\n'
        'An accrued perpetual section 8.4 license can survive JV expiry. A missing renewal or current subscription does not alone defeat that accrued grant. '
        'Public, synthetic or separately licensed inputs provide another useful route.\n\n'
        'Thirty-day example deletion does not cure an unauthorized initial use. Indefinite weights require analysis if they retain protected information. '
        'A signed, specifically scoped license or waiver could change the result, but no such instrument is assumed.',
        ['E4', 'E5', 'E6', 'E7', 'E8', 'E9', 'E11', 'E13', 'E17', 'E18', 'E19', 'E22'],
        ['U1', 'U2', 'U3', 'U4', 'U5']),
    decision('D4', 'sai-esds', 'customer-controlled-inference', 'off',
        'SPOCHUB SOLUTIONS PRIVATE LIMITED and ESDS Cloud FZ-LLC as the contracting Customer, subject to actual order allocations. The Parent is a distinct MSA role.',
        'Customer-controlled operational workloads and confidential documents, with content and keys unavailable to SAI under the proposed design.',
        'The contracting Customer’s own internal operational questions, rather than resale to an End Customer.',
        'Customer-selected single-tenant open-weight model in Australia. No provider training, separate model recipient or provider prompt retention.',
        [
            'Do not enable the exact contracting-Customer internal-use purpose under sections 4.3 and 4.8(a).',
            'Preserve the separate End Customer internal-business-use route under section 4.4. Require a real resale arrangement and its actual contracts.',
            'Obtain the executed Service Order and incorporated terms before any alternative live assessment. The populated order’s dates do not establish execution.',
            'Resolve commissioning, permitted site, customer-tool conditions, capacity and actual authorized users from the receiving environment and governing sources.',
            'Keep provider content access unavailable. Bare metal and managed OOB do not prove customer-exclusive plaintext or key control.',
        ],
        'The exact actor-purpose pair conflicts with reseller-only use. Exclusive machine-learning infrastructure and application control do not expand the contracting Customer’s purpose. '
        'The strongest supported alternative places the copilot with a genuine End Customer for that End Customer’s internal business use. '
        'This is an actor-and-workflow change, not a relabeling of SPOCHUB or ESDS as its own End Customer.\n\n'
        'A signed amendment could instead authorize internal use, but ordinary consent or a notice does not supply that amendment. '
        'The alternative also needs the actual executed order, commissioning evidence, incorporated End Customer terms, input rights and permitted-site confirmation. '
        'It receives no enablement through D4. Current customer authorization remains unknown.',
        ['E23', 'E24', 'E27', 'E28', 'E29', 'E30', 'E31', 'E32', 'E34', 'E38', 'E39', 'E40', 'E41', 'E44', 'E45', 'E47', 'E48', 'E53', 'E55'],
        ['U6', 'U7', 'U8', 'U9', 'U10', 'U12']),
    decision('D5', 'sai-esds', 'provider-support-inference', 'off',
        'SAI AU NO.2 PTY LTD as Service Provider, not the Customer or its End Customers.',
        'Readable customer workload content and confidential technical documents. Uploaded support logs can remain Customer Data even when a filename says telemetry.',
        'Read and interpret content to answer support questions for the same customer.',
        'SAI-operated tenant-isolated open-weight inference in Australia. No separate model provider, model training or retention beyond the session.',
        [
            'Prevent SAI and its support model from access to, reconstruction of, or interpretation of Customer Data content.',
            'Do not substitute section 8.2 service-improvement powers, support duties, audit access or particular disclosure consent for content-access authority.',
            'Exclude Customer Personal Data from provider-readable inputs under the supplied role allocation. Determine actual personal-data facts before any redesigned route.',
            'Use only authorized provider documentation and content-free provider-system metrics for the alternate support route.',
            'Treat any proposed content-access amendment as a new contractual assessment. It must resolve the express override wording and relevant privacy roles.',
        ],
        'Section 8.2 expressly bars the proposed content read despite anything in the agreement or any Service Order. '
        'Tenant isolation, no training, Australian hosting and zero retention do not cure the prohibited access. '
        'Section 17.2(d) permits a particular disclosure with consent. It does not independently amend section 8.2 or create a Customer Personal Data processor role.\n\n'
        'Build a provider-documentation copilot with hardware-fault metrics and permit local customer-side diagnosis without provider content transfer. '
        'A customer-generated bundle is useful only if its actual fields avoid restricted content and have their own permitted disclosure purpose. '
        'The no-content alternative remains distinct from this off operation.',
        ['E25', 'E26', 'E28', 'E31', 'E33', 'E34', 'E36', 'E38', 'E39', 'E44', 'E45', 'E49'],
        ['U6', 'U7', 'U8', 'U9', 'U10', 'U11', 'U12']),
    decision('D6', 'sai-esds', 'provider-shared-training', 'off',
        'SAI AU NO.2 PTY LTD as provider and shared-model owner.',
        'A mixture of workload content, support logs and confidential technical information. Provider-origin operational metadata, submitted Feedback and customer-origin content are separate classes.',
        'Train a shared support model for use across customers. Retain raw examples for thirty days and model weights indefinitely.',
        'Provider-owned model trained and hosted in Australia. No separate model provider receives content, but SAI itself reads and trains on it.',
        [
            'Reject the proposed mixed customer-content training corpus before its first ingestion, embedding or training step.',
            'Do not treat provider ownership of Foreground IPR as authority to acquire or process prohibited input content.',
            'Separate voluntarily submitted qualifying Customer Feedback from workload content. Preserve the Background IPR exception and any specific background license analysis.',
            'Use public, synthetic or independently licensed materials, or qualifying noncontent provider metrics within authorized purposes, for an alternate improvement route.',
            'Evaluate retained weights, adapters, embeddings and examples for protected-information content and the actual return, destruction and confidentiality obligations.',
        ],
        'The content-access prohibition defeats this exact proposal before training begins. Confidential information also has a contractual-performance purpose limit. '
        'Sections 15.2–15.5 grant substantial ownership and Feedback rights, but ownership is not blanket input authorization.\n\n'
        'Genuine submitted suggestions, questions and bug reports can qualify under section 15.4 and support a useful separate improvement corpus. '
        'Its notwithstanding wording creates a real tension with section 8.2 for mixed Feedback that contains workload content. '
        'Use unambiguous noncontent Feedback and preserve that mixed-submission question rather than silently choosing the broader grant.\n\n'
        'The Customer Data exclusion for provider-generated logs does not exempt every support log or erase confidentiality and privacy limits. '
        'A thirty-day backup or raw-example period does not authorize indefinite protected information in weights. No de-identification is assumed.',
        ['E25', 'E26', 'E31', 'E32', 'E33', 'E34', 'E35', 'E36', 'E37', 'E38', 'E39', 'E42', 'E43', 'E47', 'E56'],
        ['U6', 'U7', 'U8', 'U9', 'U10', 'U11', 'U12']),
]


unknowns = [
    dict(id='U1', customer_id='c3-bhge',
         description='Current applicability on November 4, 2026 is unproved. The amended initial JV term ends April 30, 2024. Renewal and subscription continuity are not supplied.',
         resolution='Obtain executed later amendments, the actual BH renewal election and evidence of its conditions, plus the operative subscription term and any termination records. Distinguish JV expiry from independent subscription survival.',
         evidence_ids=['E10', 'E11', 'E17']),
    dict(id='U2', customer_id='c3-bhge',
         description='The April 29, 2019 internal MSSA, associated orders and SOWs are absent. Executed downstream MSSAs and Orders are also absent. The actual customer route is unresolved.',
         resolution='Supply the exact internal subscription package or relevant downstream executed MSSA, Orders and SOWs. Identify the contracting customer, permitted model deployment, support content rights and retained-data terms.',
         evidence_ids=['E1', 'E3', 'E4', 'E10']),
    dict(id='U3', customer_id='c3-bhge',
         description='Restated Exhibits E and F are absent although the Second Amendment replaces them. Other referenced exhibits and redacted definitions or ownership terms remain incomplete.',
         resolution='Obtain the operative restated E/F and relevant A-1, G, H and I materials through the authorized owner. Preserve every redaction until an actual source resolves it. Do not restore superseded Exhibit E.',
         evidence_ids=['E3', 'E4', 'E7', 'E8', 'E18', 'E19', 'E22']),
    dict(id='U4', customer_id='c3-bhge',
         description='Actual data owners, third-party restrictions, Sensitive Information designations, permitted recipients and personal-data facts are not supplied by the feature proposal.',
         resolution='Review an owner-provided data inventory and the applicable customer agreements. Match each input and recipient to its rights and written designations. Verify isolation with authorized nonproduction tests.',
         evidence_ids=['E6', 'E7', 'E8', 'E21']),
    dict(id='U5', customer_id='c3-bhge',
         description='No object-level evidence shows that the proposed training materials are BH-owned technology expressly provided under section 8.4, qualifying Feedback, or separately licensed training data.',
         resolution='Supply actual provision records, the object list and purpose mapping. For BH Provided Technology, establish express identification, BH ownership and BH-Field applicability. Resolve missing Exhibit E for section 6.1 development reliance. Do not require renewed JV or subscription authority merely for an accrued perpetual commercialization license. Evaluate protected information in retained artifacts.',
         evidence_ids=['E4', 'E5', 'E9', 'E13', 'E18', 'E19']),
    dict(id='U6', customer_id='sai-esds',
         description='The public source supplies signed-looking MSA entries and a populated Service Order with blank signature fields. Current executed order and incorporated terms are not established.',
         resolution='Obtain the executed Service Order, its signed appendices, identified Special Conditions, applicable Product Specific Terms and later signed amendments. Preserve which entity signs in each capacity.',
         evidence_ids=['E28', 'E29', 'E38', 'E39', 'E40']),
    dict(id='U7', customer_id='sai-esds',
         description='Installation, commissioning, actual live service state, allocated capacity and the relevant contracted site are unproved. Australia is not an exact Permitted Territory site.',
         resolution='Inspect the mutually signed Commissioning Certificate, applicable start-state records, current order site specification and actual hardware, storage and backup locations. Read current activation and capacity state without assuming planned dates completed.',
         evidence_ids=['E27', 'E41', 'E42', 'E43', 'E46']),
    dict(id='U8', customer_id='sai-esds',
         description='The actual Customer and Parent allocations and any real End Customer resale arrangement are unknown. No End Customer contract or input-rights evidence is supplied.',
         resolution='Obtain the executed parties and capacity allocations, actual End Customer Contracts, required term incorporation and timely redacted-copy delivery records. Confirm input rights and each actual authorized user. Do not create nominal End Customer status.',
         evidence_ids=['E23', 'E29', 'E30', 'E32', 'E40', 'E48']),
    dict(id='U9', customer_id='sai-esds',
         description='Several same-source scope tensions remain: sections 2.7 versus 23.7 on subcontractors, 8.2 versus 15.4 for mixed Feedback, and 4.4 versus 8.1.3 on express resale.',
         resolution='Obtain any actual signed clarification and applicable Special Conditions. Preserve section 2.4 and every express notwithstanding clause. For the alternate design, avoid mixed Feedback and content-bearing subcontractor access. Do not use file order as a tie-breaker.',
         evidence_ids=['E28', 'E29', 'E31', 'E35', 'E38', 'E50', 'E51', 'E55']),
    dict(id='U10', customer_id='sai-esds',
         description='Actual data classes, personal-data exposure, customer tool integration terms and provider plaintext or key access are unverified. Shared managed OOB complicates the proposed blindness claim.',
         resolution='Supply field-level producer and rights records, actual tool integration conditions and configuration evidence. Exercise customer-controlled synthetic canaries in an authorized test environment. Inspect OOB, snapshots, memory, logs and backup paths without real customer content.',
         evidence_ids=['E25', 'E26', 'E32', 'E34', 'E44', 'E45', 'E52', 'E53', 'E54']),
    dict(id='U11', customer_id='sai-esds',
         description='No concrete support-log or Feedback samples establish provider-system origin, noncontent status, absence of Customer Background IPR, or permitted cross-customer use.',
         resolution='Review owner-provided schema and synthetic representative samples. Separate producer-generated metrics, customer-uploaded logs and genuinely submitted Feedback. Resolve mixed confidential or Background IPR objects against sections 8.2, 15 and 17.',
         evidence_ids=['E25', 'E26', 'E31', 'E35', 'E36', 'E37']),
    dict(id='U12', customer_id='sai-esds',
         description='Redacted technical, SLA and commercial details remain unavailable. Generic security measures do not establish deployment controls or full customer-app/model ownership.',
         resolution='Obtain only the technical specifications, current service scope and IP terms needed for the selected variant. Resolve the application-layer exclusion against the broad Foreground IPR provisions for adapters, code and model artifacts. Preserve all unresolved redactions.',
         evidence_ids=['E35', 'E39', 'E41', 'E44', 'E45', 'E46', 'E53']),
]


feature = json.loads((WORK / 'feature.json').read_text())
operations = {op['id']: op for op in feature['operations']}
controls = []
for row in decisions:
    op = operations[row['operation_id']]
    facts = dict(op['proposed_facts'])
    facts['purpose'] = op['purpose']
    facts['model'] = op['model']
    facts['feature_id'] = feature['id']
    controls.append(dict(decision_id=row['id'], customer_id=row['customer_id'],
                         operation_id=row['operation_id'], proposed_eligible=False,
                         required_facts=facts,
                         reason=('These literals describe the supplied hypothetical operation, not verified customer deployment facts. '
                                 'Eligibility remains false because ' + {
                                     'D1': 'the operative subscription and current scope prerequisites remain unresolved.',
                                     'D2': 'the support purpose and content-access grant remain unresolved.',
                                     'D3': 'the mixed training corpus has no supported grant. A licensed section 8.4 alternative requires a distinct assessment.',
                                     'D4': 'contracting-Customer internal use conflicts with the reseller-only purpose. End Customer use is a different actor-purpose pair.',
                                     'D5': 'provider interpretation of Customer Data content conflicts with section 8.2, even with no retention or training.',
                                     'D6': 'the shared-training mixture includes content prohibited by section 8.2 and unqualified confidential material.',
                                 }[row['id']])))


engineering = [
    dict(id='ENG1', title='Implement source-unit hierarchy and contract-state intake',
         body='Decision contract: off means the exact proposal conflicts with supplied terms. Unresolved means missing operative instruments prevent a permission conclusion. '
              'Neither status asserts current customer contract status. Notice or consent status applies only when an actual source supplies that route.\n\n'
              'C3 hierarchy: apply the explicit First and Second Amendment replacements in precedence[]. Keep untouched sections 8 and 9, and retained Year 1–3 definitions. '
              'Mark restated E/F unavailable after their complete replacement. Never reuse original Exhibit E generalization as operative permission. '
              'Preserve section 12.3(b) independent subscription rights and section 12.4 survival.\n\n'
              'SAI same-source hierarchy: section 2.4 ranks expressly identified Special Conditions, MSA terms, then ordinary order terms, only for inconsistencies. '
              'Section 8.2 adds an express notwithstanding-any-Service-Order content prohibition. A generic order term cannot silently defeat it. '
              'Do not fabricate separate document IDs or self-precedence edges for sections of this single HTML source. '
              'Record these source-unit relations against E28, E31, E35, E38, E50, E51 and E55.\n\n'
              'Accept a supplied signed amendment that expressly resolves the relevant conflict as a new input, then reassess only the affected operation. '
              'Distinguish signature, commissioning, service activation and content authorization. A typed representative name or planned date proves none of the later states. '
              'Do not create a generic permission broker or alter personal Kai capabilities.',
         acceptance_criteria='A replay retains April 30, 2024 as the last sourced initial C3 term without an assumed renewal. '
              'It marks restated E/F absent and preserves independent subscription survival. '
              'For SAI, unsigned ordinary order text cannot enable content access or contracting-Customer internal use. '
              'Same-source conflicts retain exact section references and source evidence. No unsupported precedence edge or new account state appears.',
         decision_ids=['D1', 'D2', 'D3', 'D4', 'D5', 'D6']),
    dict(id='ENG2', title='Build a customer-side operational copilot with an exact actor-purpose boundary',
         body='Target architecture: authorized customer user to local retriever to tenant-local open-weight model to the same user. '
              'Content, retrieval indexes, prompts, outputs and keys remain inside that authorized tenant. Provider support receives no plaintext or learned customer artifacts.\n\n'
              'For C3, bind the tenant to the actual internal or downstream subscription and permitted scope before any live reassessment. '
              'For SAI, use a genuine End Customer internal-business deployment under an actual resale contract. The contracting Customer’s own internal operation stays off. '
              'Do not promote an affiliate into End Customer status through a configuration label.\n\n'
              'Use the SAI provider portal and hardware interfaces according to the actual customer-tool integration terms. '
              'Specify OS, firewall, network and storage duties against Appendix F rather than assume a turnkey managed application. '
              'Verify OOB and key custody before the provider-blind claim. Resolve customer application and adapter IP under sections 15.1–15.5.\n\n'
              'Source basis: E1–E4, E7–E10, E20–E21, E23–E24, E27–E34, E35, E39–E48 and E53–E55. '
              'No technical isolation result replaces a missing service license, valid purpose or data right.',
         acceptance_criteria='With synthetic tenant A and B data, A retrieves only A records and B retrieves only B records. '
              'Provider support and provider observability find no plaintext canary, key, prompt, response, index or dump. '
              'All model and storage paths match the contracted site.\n\nA contracting-Customer internal-purpose SAI request remains denied despite perfect isolation. '
              'Missing executed agreements, tool conditions or End Customer terms prevent promotion. No live infrastructure test occurs without its required authority.',
         decision_ids=['D1', 'D4']),
    dict(id='ENG3', title='Build provider support from documentation and allowlisted infrastructure metrics',
         body='Alternate support flow: provider-owned manuals plus hardware-fault metrics feed a provider copilot. '
              'The copilot returns diagnostic steps for customer administrators to execute. A tenant-local diagnostic agent may analyze content without a provider-readable response.\n\n'
              'Proposed metric schema: device_fault_code, gpu_error_count, temperature_band, power_band, capacity_used and service_health. '
              'This schema is an engineering allowlist, not a claim that any real field already has permission. '
              'Exclude free text, command lines, payload fragments, paths with secrets, prompts, outputs and customer documents. '
              'Classify identifiers and timing data for confidentiality and Personal Data before use.\n\n'
              'Distinguish provider-system telemetry from customer-uploaded workload logs by producer and field provenance. '
              'A provider-generated log cannot serve as a conduit for prohibited content capture. '
              'For SAI, section 8.2 permits specified use analysis but its content proviso remains binding. '
              'For C3, use only documentation and operational records with actual ownership and purpose authority.\n\n'
              'A customer summary may enter support only after its concrete fields pass the applicable content, confidentiality and purpose checks. '
              'No external model provider or new subcontractor is part of this design. Source basis: E6–E9, E25–E26, E31–E36, E44–E45, E49–E53.',
         acceptance_criteria='A synthetic support bundle with a hidden prompt, document fragment or secret fails before model ingestion. '
              'Pure allowlisted metrics produce a useful hardware diagnosis in an isolated test. '
              'Customer Personal Data and mixed-origin logs cannot pass through a filename-based telemetry exemption. '
              'C3 content support remains unresolved and SAI content support remains off. Neither operation inherits enablement from the alternate metric route.',
         decision_ids=['D2', 'D5']),
    dict(id='ENG4', title='Create an object-level licensed improvement corpus without workload-content laundering',
         body='Corpus manifest fields: object_id, producer, discloser, rights_owner, source_class, transmission_record, license_clause, allowed_purpose, protected_fields and retention_basis. '
              'Use public, synthetic or independently licensed materials where their actual rights permit the intended model use. '
              'Keep workload data, support content, gradients, adapters and embeddings outside shared improvement by default in this assessed configuration.\n\n'
              'C3 alternate lane: section 8.4 BH-owned technology expressly identified and provided, or qualifying Feedback. '
              'Map each object to its section 8.4 purpose. Obtain the missing development scope when the route relies on section 6.1. '
              'Preserve accrued perpetual commercialization rights despite JV expiry. An absent Exhibit F, renewal or current subscription does not alone defeat those rights.\n\n'
              'Do not treat a log upload or every BH confidential document as BH Provided Technology. '
              'Preserve the section 9.4(a) continued-use exception for validly licensed technology.\n\n'
              'SAI alternate lane: genuine Customer Feedback under section 15.4, such as a submitted suggestion or bug report without workload content. '
              'Respect the Customer Background IPR exception and any actual section 15.5 license predicate. '
              'Quarantine a mixed submission because sections 8.2 and 15.4 both contain broad override language. '
              'Provider ownership of a resulting artifact cannot retrospectively authorize prohibited input access.\n\n'
              'No universal de-identification, consent, model ownership or cross-customer permission is inferred. '
              'Source basis: E4–E9, E11, E13, E18–E19, E25–E26, E31–E38, E47 and E56.',
         acceptance_criteria='An arbitrary workload log labeled Feedback is rejected. '
              'An expressly provided BH technology object with verified owner and purpose reaches only its separately assessed licensed lane. '
              'A pure service suggestion reaches the SAI Feedback review lane without imported workload material. '
              'Customer Background IPR and mixed-content uncertainty remain explicit. D3 and D6 stay off for the original mixed corpora.',
         decision_ids=['D3', 'D6']),
    dict(id='ENG5', title='Specify retention and protected-information disposal for every derived artifact',
         body='Track raw examples, retrieval indexes, embeddings, adapters, weights, snapshots, logs, caches and backups as distinct artifacts. '
              'Attach each artifact to its input lineage, contractual purpose, retention basis and applicable request or termination event. '
              'Thirty-day raw-example retention and zero session retention are technical proposals, not contract grants.\n\n'
              'For C3, implement section 9.4 return or deletion and officer certification with its exact exceptions. '
              'For SAI, preserve section 17.6 qualifications and section 17.5 continuing protection. '
              'Do not assume every weight is Confidential Information or that every weight is free of it. '
              'Assess copied or recoverable protected information and obtain a defensible disposition for affected model artifacts.\n\n'
              'Use synthetic planted secrets for extraction tests. A failed extraction attempt is exposure evidence only, not proof of consent or irreversible anonymization. '
              'Do not use a backup-media schedule as authority for indefinite model retention. Source basis: E5–E9, E11, E35–E37 and E56.',
         acceptance_criteria='A simulated valid deletion request removes the targeted synthetic examples from active stores, caches and applicable copies. '
              'The artifact inventory identifies every dependent model or index and states its disposition or specific retained-right exception. '
              'No compliance-only retained copy remains accessible to shared training. '
              'The receipt distinguishes completed deletion, retained licensed use, delayed backup expiry and unresolved derived-information questions.',
         decision_ids=['D2', 'D3', 'D5', 'D6']),
    dict(id='ENG6', title='Bind proposed OpenFeature rules to the exact six assessed operations',
         body='Export one control per customer-operation pair. Bind customer ID, operation ID, actor role, purpose, model, provider access, training role, external transfer and region. '
              'The required_facts literals come from the hypothetical feature sheet. They are equality predicates, not verified deployment facts. '
              'Do not put unknown signatures, renewal, commissioning, consents or site elections into required_facts as established truths.\n\n'
              'All six proposed_eligible values are false for this acquired record. '
              'Missing prerequisites and prohibited proposals remain unavailable even when every scenario literal matches. '
              'A future source change requires a revised model assessment and export before eligibility changes. '
              'The local policy implements this feature only and cannot restrict personal Kai or become a general permission broker.\n\n'
              'Compile the unchanged kit and exercise its actual OpenFeature SDK. '
              'Read SQLite directly and compare the full bundle and export with the authored files. '
              'Record that an all-false export tests denial and exact delivery but cannot demonstrate positive live contract clearance.',
         acceptance_criteria='Exactly six unique pairs and six unique controls exist. '
              'Matched, unknown-customer and missing-fact contexts all return false in the actual SDK. '
              'Additional wrong-purpose, wrong-actor, wrong-region and wrong-operation contexts return false. '
              'The receiver bundle and export match structurally and by canonical SHA-256.\n\nSource hashes remain unchanged. '
              'The OPA artifact exists, but an OPA runtime pass is claimed only after a real OPA execution.',
         decision_ids=['D1', 'D2', 'D3', 'D4', 'D5', 'D6']),
    dict(id='ENG7', title='Prepare a scoped amendment only if the exact prohibited design remains necessary',
         body='This is a conditional drafting specification, not a source-required generic owner approval or a notice workflow. '
              'For SAI internal use, identify sections 4.3 and 4.8(a), the actual Customer entities, permitted internal purpose and affected Service Order. '
              'For provider content access, expressly resolve section 8.2 rather than rely on ordinary support terms or a general Special Condition.\n\n'
              'Any content-access instrument must state data classes, confidential-use purpose, recipients, model operator, no-training or training role, retention, permitted site and actual privacy roles. '
              'Any shared-training instrument must address cross-customer use, third-party input rights, derivative artifacts and deletion or retained-right treatment. '
              'Use section 23.5 signatures for an SAI amendment and section 13.13 for a C3 amendment or scoped waiver. '
              'A party cannot license absent downstream rights or convert a legal obligation into a fact by declaration.\n\n'
              'No inferred AI launch notice exists here. C3 quarterly offering-update information, SAI SLA updates and mandatory-law migration notices retain their separate triggers. '
              'Do not send them to manufacture authorization. Source basis: E13, E19, E28–E38, E42 and E46.',
         acceptance_criteria='A hypothetical generic support consent leaves the existing content prohibition intact. '
              'A revised signed source that expressly changes the applicable actor-purpose or access rule triggers a fresh scoped decision. '
              'Unchanged operations preserve their prior conditions and unknowns. '
              'No placeholder date, recipient, signature, approval or current deployment claim appears as an accomplished fact.',
         decision_ids=['D3', 'D4', 'D5', 'D6']),
]

drafts = [
    dict(type='information_request', customer_id='c3-bhge',
         reason='The internal subscription and downstream instruments govern the proposed use. Amendment and survival provisions prevent an inference from the public JV term alone.',
         draft='Conditional preparation for the hypothetical Tenant Operations Copilot assessment:\n\n'
               'Could you provide the operative internal subscription MSSA and its orders, or the executed downstream MSSA, Orders and SOWs for the intended customer? '
               'Please include later amendments, any renewal election, and the restated Exhibits E and F referenced by the Second Amendment. '
               'For provider support, identify the agreed content-access and service scope. '
               'For a section 8.4 improvement route, include the identified technology or Feedback transmission and the associated ownership and purpose records. '
               'These materials will let the assessment distinguish customer inference, same-customer support and shared-model improvement.',
         unknown_fields=['actual customer and subscription route', 'operative instruments and renewal evidence',
                         'restated E/F', 'support scope', 'section 8.4 object records', 'authorized recipient'],
         evidence_ids=['E1', 'E3', 'E5', 'E8', 'E10', 'E17', 'E18']),
    dict(type='information_request', customer_id='sai-esds',
         reason='Sections 4.5 and 5 require actual execution and commissioning evidence. Resale and site conditions require the governing order and End Customer records.',
         draft='Conditional preparation for the hypothetical Tenant Operations Copilot assessment:\n\n'
               'Could you provide the executed Service Order, its Special Conditions, applicable Product Specific Terms and later signed amendments? '
               'Please include the commissioning record, contracted data-centre site and customer-tool integration terms. '
               'For an End Customer deployment, include the actual resale contract and required term incorporation. '
               'A representative field schema will help separate provider telemetry, customer workload logs and submitted Feedback. '
               'The customer-controlled End Customer design and content-free provider support design can then receive separate assessments.',
         unknown_fields=['executed order and current amendments', 'commissioning record', 'Permitted Territory site',
                         'actual End Customer arrangement', 'tool integration conditions', 'field provenance', 'authorized recipient'],
         evidence_ids=['E27', 'E28', 'E29', 'E30', 'E31', 'E35', 'E38', 'E39', 'E41', 'E45', 'E48']),
]

bundle = dict(
    assessment_type='proposed_source_bound_decisions', feature_id=feature['id'],
    summary='Six source-bound proposal decisions: C3 customer inference and provider support remain unresolved. '
            'C3 mixed-content shared training and all three exact SAI operations are off under the supplied record. '
            'No operation qualifies for present enablement or a notice-only launch.\n\n'
            'The strongest useful design keeps content inference with the properly licensed customer or genuine End Customer. '
            'It combines that route with content-free provider diagnostics and separate object-level licensed technology or Feedback improvement lanes. '
            'SAI contracting-Customer internal use cannot borrow the End Customer grant. C3 Feedback rights cannot absorb all workload content.\n\n'
            'All controls remain false. Missing executed instruments, replaced exhibits, redactions and current applicability remain explicit. '
            'SAI same-source hierarchy and conflicting scopes appear in ENG1 and U9 because its source units share one document ID. '
            'This hypothetical public-sample export grants no actual customer clearance and changes no live account or feature.',
    evidence=evidence, precedence=precedence, decisions=decisions, unknowns=unknowns,
    controls=controls, engineering_outputs=engineering, notices_or_consent_drafts=drafts,
)
(WORK / 'model-decisions.json').write_text(json.dumps(bundle, ensure_ascii=False, indent=2) + '\n')
print(json.dumps({'authored_decisions': len(decisions), 'exact_evidence_items': len(evidence),
                  'engineering_outputs': len(engineering), 'output': str(WORK / 'model-decisions.json')}))
