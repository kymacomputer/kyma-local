"""Assemble this invocation's model-authored assessment from exact source text.

Interpretations below are authored decisions, not an automated legal classifier.
The prior packet supplies quotation candidates only. Current sources verify them.
"""
import copy
import difflib
import hashlib
import json
from pathlib import Path

WORK = Path(__file__).resolve().parent
manifest = json.loads((WORK / "source-manifest.json").read_text())
feature = json.loads((WORK / "feature.json").read_text())
context = json.loads((WORK / "revision-context.json").read_text())
documents = {
    d["id"]: d
    for key in ("customers", "reference_sets", "historical_reference_sets")
    for group in manifest.get(key, [])
    for d in group["documents"]
}
texts = {key: (WORK / d["text_file"]).read_text() for key, d in documents.items()}
evidence = copy.deepcopy(context["previous_actual_assessment"]["evidence"])
for e in evidence:
    assert e["quote"] in texts[e["document_id"]], e["id"]


def quote(identity, document, section, start, end, supports):
    text = texts[document]
    a = text.index(start)
    b = text.index(end, a) + len(end)
    evidence.append({"id": identity, "document_id": document, "section": section,
                     "page": None, "quote": text[a:b], "supports": supports})


C3 = "c3-bhge:01-joint-venture-2019-06-06.html"
SAI = "sai-esds:01-master-services-2026-03-31.html"
BEFORE = "historical-reference:fullstory:subprocessor-list.html"
AFTER = "reference:fullstory:subprocessor-list.html"
quote("E68", BEFORE, "Historical capture: displayed date, disclosure scope and complete Google row",
      "Fullstory Sub-processor List\nLast Updated:", "United States; Germany",
      "The historical capture lists Google for storage, processing and security monitoring. It prints June 2, 2026. It states no Google inference purpose.")
quote("E69", AFTER, "Current capture: displayed date, disclosure scope and complete Google row",
      "Fullstory Sub-processor List\nLast Updated:", "United States; Germany",
      "The current capture adds Google AI model inference for in-product AI features. The date, processed data and listed locations remain unchanged.")
quote("E70", BEFORE, "Historical capture: OpenAI optional and Anthropic rows",
      "OpenAI (optional)", "Anthropic\nSupport delivery of the SaaS Services to Customer\nCustomer data and Customer’s end-users’ data\nUnited States",
      "The historical disclosure already includes optional OpenAI generative AI and Anthropic. This change does not establish a first general AI disclosure.")
quote("E71", AFTER, "Current capture: OpenAI optional and Anthropic rows",
      "OpenAI (optional)", "Anthropic\nSupport delivery of the SaaS Services to Customer\nCustomer data and Customer’s end-users’ data\nUnited States",
      "These AI-related rows remain the same. Optional OpenAI use is not established for this feature. The acquired row supplies no OpenAI location.")
quote("E72", SAI, "23.9: subcontractor changes",
      "23.9\nSubcontractors:", "change subcontractors or third-party Service Providers at its sole discretion.",
      "The MSA also permits discretionary subcontractor changes subject to Applicable Law. This reinforces the tension with 2.7, without a data-access or residency override.")
quote("E73", SAI, "16.1: component-specific open-source rights",
      "16.1\nLicense:", "applicable solely to the open-source software component.",
      "Open-source licences preserve their component-specific rights. They do not expand the contractual service purpose or grant rights over customer content.")
quote("E74", C3, "1.62: Third Party Offering definition",
      "1.62“Third Party Offering”", "any C3 Offering.",
      "A customer can procure an interoperable Third Party Offering. The definition alone does not establish its licence or permit disclosure to its supplier.")
quote("E75", SAI, "9.2(d): acceptance boundary",
      "(d)\nupon\nreceipt of a Deliverable Defects Notice", "no “acceptance” terms shall apply to Cloud Services.",
      "Generic deliverable acceptance cannot replace the particular computing commencement process. The contract explicitly excludes Cloud Services from these acceptance terms.")
quote("E76", SAI, "MSA execution page: provider signature",
      "IN\nWITNESS WHEREOF", "James\nManning\nTitle:\nCEO",
      "The filed MSA contains an executed provider signature. This differs from the blank included order and proves no present service state.")
quote("E77", SAI, "1.1: Terms and Conditions definition",
      "“Terms\nand Conditions”", "End Customer’s access to or use of the Services..",
      "The End Customer Terms and Conditions expressly include restrictions and monitoring. The resale alternative cannot escape the content-access proviso.")

precedence = [
    {"higher_document_id": "c3-bhge:02-first-amendment-2019-09-26.html", "lower_document_id": C3,
     "scope": "Added annual definitions, replacement 5.1(b) and 12.1, Exhibit B-1 section 1 and Exhibit E sections 1.3 and 1.4 only",
     "reason": "Clauses 1–5 identify each addition or replacement. Clause 6 preserves the remaining JV terms. This edge does not rest on file order.",
     "evidence_ids": ["E15", "E19", "E20"]},
    {"higher_document_id": "c3-bhge:03-second-amendment-2020-06-01.html", "lower_document_id": "c3-bhge:02-first-amendment-2019-09-26.html",
     "scope": "Replacement 5.1(b), 12.1, entire Exhibit B-1 and entire Exhibit E, including the First Amendment's amended portions",
     "reason": "The Second Amendment expressly addresses the previously amended JV. Its named replacements displace the earlier language on those same subjects.",
     "evidence_ids": ["E19", "E20", "E21", "E22"]},
    {"higher_document_id": "c3-bhge:03-second-amendment-2020-06-01.html", "lower_document_id": C3,
     "scope": "BH replaces BHGE, Year 4 and Year 5 added, 5.1(b) and 12.1 replaced, Exhibits B-1, E and F replaced in full",
     "reason": "Clauses 1–7 expressly change these subjects. Clause 8 preserves the balance. Missing restated E and F cannot revive the original exhibits.",
     "evidence_ids": ["E21", "E22", "E23", "E16"]}
]


def decision(identity, customer, operation, status, actor, data, purpose, model, conditions, rationale, ev, unknown):
    return {"id": identity, "customer_id": customer, "operation_id": operation,
            "status": status, "actor": actor, "data": data, "purpose": purpose,
            "model": model, "feature": feature["name"], "conditions": conditions,
            "rationale": rationale, "evidence_ids": ev.split(), "unknown_ids": unknown.split()}


decisions = [
    decision("D1", "c3-bhge", "customer-controlled-inference", "unresolved",
      "BH under the separate internal subscription, or the actual downstream licensee under its own subscription. C3 supplies the platform.",
      "Customer-controlled operational workloads and technical documents. Confidential Information includes protected third-party material. Sensitive Information retains its designated audience.",
      "Answer that customer's own operational questions for its internal use.",
      "Customer-selected open-weight model in one customer-controlled Australian tenant. No separate model provider receives content. C3 has no plaintext access or decryption key. No provider training.",
      [
       "Identify the actual licensee and operative internal or downstream subscription, order and application rights.",
       "Resolve current rights independently from the JV term. Do not infer renewal or subscription expiry from April 30, 2024 alone.",
       "Confirm model-weight, application, input and third-party rights. The open-weight description is not a model licence.",
       "Keep customer content and keys outside every C3 plaintext path, including console, runtime, dumps, traces, storage and backups.",
       "Keep document ACLs and Sensitive Information designations intact. Apply the operative deployment, security and privacy terms.",
       "Keep provider prompts unretained. Customer workload storage still follows the operative agreement. No external supplier path enters through a disclosure-list update."
      ],
      "Customer computation is the strongest useful design. The JV recognises an AI platform, an internal subscription and interoperable third-party offerings. "
      "It does not supply the separate subscription's actual application and data rights. Section 8.1(c) preserves that separate IP allocation. "
      "The external distribution noncompetition promise does not create a blanket prohibition on internal AI. The preferred-platform statement creates no unrestricted model licence. "
      "The Second Amendment replaces the JV term, but 12.3(b) preserves subscriptions subject to their own terms. Therefore this exact operation remains unresolved. "
      "The Fullstory change alters no source-bound permission or proposed data path. Its disclosure is neither incorporated here nor proof of engagement.",
      "E1 E2 E3 E4 E5 E7 E8 E9 E10 E11 E13 E14 E21 E22 E66 E68 E69 E74", "U1 U2 U3 U4"),
    decision("D2", "c3-bhge", "provider-support-inference", "unresolved",
      "C3 as the actual contracted support provider. BH's reseller appointment does not itself authorise downstream disclosures.",
      "Customer workload content, confidential technical documents and content-bearing support records. Third-party and Sensitive Information restrictions remain material.",
      "Read customer workload content and confidential technical documents to answer support questions for that same customer.",
      "C3-operated tenant-isolated open-weight inference in Australia. C3 interprets content. No external model provider, shared training or session-exceeding prompt/output retention.",
      [
       "Establish an actual support right or obligation that requires this exact content use under the applicable agreement.",
       "Obtain the operative support subscription or SOW and relevant restated development terms. Do not substitute the superseded Exhibit E.",
       "Limit access to permitted need-to-know personnel under protective confidentiality terms. Enforce written Sensitive Information designations.",
       "Keep restricted recipients excluded. Keep the model tenant-isolated, with no other customer access, training or external model recipient.",
       "Delete session content from model caches, diagnostics and traces after the response. Reconcile retained source documents under their distinct storage terms.",
       "Use provider manuals and verified non-content telemetry for an independent support route where content authority is absent. D1 remains subject to its own prerequisites."
      ],
      "Section 9.2 permits confidential use required for contractual rights or obligations. It does not require new AI consent for every authorised support computation. "
      "However, the supplied JV set does not establish this customer's actual support grant, permitted recipients or current subscription. Tenant isolation cannot create those rights. "
      "Section 8.4 is a separate contribution licence, not the necessary theory for ordinary authorised support. The exact content-support operation therefore remains unresolved. "
      "A metadata support copilot can use provider runbooks and independently classified operational facts without silently absorbing workload content. "
      "The Google disclosure addition cannot resolve the missing support grant or change the specified open-weight model.",
      "E2 E3 E4 E6 E8 E9 E10 E11 E12 E13 E14 E21 E22 E68 E69", "U1 U2 U3 U4"),
    decision("D3", "c3-bhge", "provider-shared-training", "needs_consent",
      "C3 as owner and operator of a shared support model. The actual data rights holders must supply any missing grant.",
      "Customer workload content, support logs and confidential technical information. These are not automatically BH Provided Technology or Feedback.",
      "Improve the provider's shared support model for use across its customer base.",
      "C3-owned model trained and hosted in Australia. Raw examples remain for 30 days. The model remains indefinitely. No external model recipient or assumed de-identification.",
      [
       "Obtain a purpose-specific signed grant for the actual dataset and shared model unless a complete existing licence demonstrably covers that use.",
       "For an 8.4 route, prove BH ownership and express contribution/identification of technology, or actual Feedback, plus the specified permitted development or commercial purpose.",
       "Do not infer a licence from a workload upload, a support attachment or roadmap review. The old Exhibit E is superseded in full.",
       "Address raw examples, checkpoints, learned confidential information, deletion, return duties and indefinite model use in the exact grant.",
       "Resolve downstream rights and Sensitive Information recipients. BH cannot clear another customer's rights through its distribution role.",
       "Keep a distinct corpus for provider-authored material, public material with actual reuse rights, and qualifying licensed contributions. Assess that changed dataset separately."
      ],
      "The proposal changes the beneficiary from the same customer to the provider's customer base. It also introduces persistent examples and an indefinite model. "
      "Section 9.2 supplies no general confidential-workload training right. Section 8.4 preserves a useful, specific contribution route with a perpetual scoped licence. "
      "That route cannot convert arbitrary customer content into BH-owned contributed technology or Feedback. Original roadmap generalization language is not an operative training licence. "
      "It was replaced with an absent restatement. The exact proposal needs a scoped grant, subject to the missing-source review. "
      "This is source-required contractual consent, not a generic owner approval. The changed Google disclosure describes inference, not this training use or model retention.",
      "E7 E8 E9 E10 E11 E12 E14 E15 E16 E17 E18 E20 E21 E22 E68 E69", "U1 U2 U3 U4 U5"),
    decision("D4", "sai-esds", "customer-controlled-inference", "needs_consent",
      "SPOCHUB and ESDS Cloud as the MSA Customer. The Parent and an actual End Customer are separate roles.",
      "Customer-authorised workloads, software and confidential technical documents. Customer Data includes customer submissions. Excluded provider-generated telemetry is a distinct class.",
      "Answer that customer's own operational questions for its internal use. This exact purpose is not limited to the resale business.",
      "Customer-selected open-weight model in a customer-controlled Australian tenant. SAI cannot read content or hold customer decryption keys. No external model provider or provider training.",
      [
       "For the exact unqualified contracting-customer internal purpose, obtain a signed variation to the resale-only scope in 4.3 and 4.8(a).",
       "Preserve the existing useful resale route: an actual End Customer may receive internal-business use through an authorised resale contract and order.",
       "A customer administrator's task strictly for contractual resale may fit the resale purpose. Establish that narrower purpose before a separate assessment.",
       "Resolve the executed order, applicable Special Conditions, exact Data Centre site, commissioning, advance confirmation and current service availability.",
       "Resolve integration diligence, technical conditions and Additional Fees. Verify customer-only content control across the runtime, shared OOB and storage.",
       "Maintain actual data and model rights, authenticated users, customer backup responsibilities and the AUP. Do not provide Customer Personal Data to SAI.",
       "Keep background, foreground and customer application-layer IP distinct. Do not promise ownership from operational control alone."
      ],
      "The contract contemplates machine learning and customer responsibility from the OS upwards. That supports customer-controlled AI without provider interpretation. "
      "However, 4.3 and 4.8(a) confine the contracting Customer's use to resale. The infrastructure definition and Authorised Users definition do not erase that purpose. "
      "The generic direct internal-use proposal needs a signed scope variation. The specific 4.4 End Customer internal-business route remains useful under existing terms. "
      "Resale administration is also distinct from unrelated internal business use, but that narrower factual purpose is not established here. "
      "Read the general 8.1.3 restriction within the specific resale grant, not as deletion of the reseller appointment. "
      "Neither alternative authorises SAI content access. The applicable order, rights and operational state remain unproved. The supplier disclosure changes none of these conclusions.",
      "E24 E25 E26 E27 E28 E29 E30 E31 E32 E33 E34 E35 E37 E38 E39 E40 E41 E42 E43 E47 E48 E49 E54 E55 E58 E59 E61 E62 E63 E64 E65 E67 E68 E69 E73 E75 E76 E77", "U6 U7 U8 U9 U10"),
    decision("D5", "sai-esds", "provider-support-inference", "needs_consent",
      "SAI AU NO.2 PTY LTD as the provider and model operator. The Customer and actual data rights holders must authorise the exact changed arrangement.",
      "Customer Data content, workload content and confidential technical documents. A content-bearing log does not become non-content telemetry through a label change.",
      "Read customer workload content and confidential technical documents to answer support questions for that same customer.",
      "SAI-operated tenant-isolated open-weight model in Australia. SAI interprets content. No external model recipient, model training or retention beyond the response session.",
      [
       "Obtain an effective signed variation that expressly addresses the 8.2 content prohibition for this exact support purpose.",
       "Do not rely on generic Special Conditions priority alone. Section 8.2 expressly applies notwithstanding any provision herein or any Service Order.",
       "Reconcile 11.3, confidentiality and the current Personal Data role exclusions in the signed instrument. Disclosure consent alone does not supply a new processing purpose.",
       "Exclude Customer Personal Data unless a separate effective signed role arrangement and actual authority cover it.",
       "Confirm the actual support entitlement, customer or End Customer data rights, permitted recipients, elected site and operational state.",
       "Retain tenant isolation, no external model recipient, no training and session deletion. These safeguards do not override the content prohibition.",
       "Use provider-owned manuals and allowlisted non-content infrastructure signals for useful metadata support. Keep content-rich diagnosis with the authorised customer."
      ],
      "Section 8.2 first permits service-improvement and quantitative analytics, then expressly forbids access or interpretation of Customer Data content. "
      "The proposed model does the forbidden interpretation, even with zero retention and no training. Section 7 support and 17.2 personnel disclosure do not override it. "
      "Section 2.4 has an 'unless expressly stated otherwise' boundary. Section 8.2 supplies such contrary wording for its specific subject. "
      "An ordinary order or a generic higher-ranked Special Condition is therefore insufficient without an effective express variation of this restriction. "
      "AUP investigations, legal demands and audit exclusions have separate purposes. They cannot authorise routine support inference. "
      "The exact operation needs contractual variation. Independent non-content support remains useful. The Google disclosure neither changes provider roles nor proves an external data path.",
      "E27 E28 E30 E31 E36 E37 E39 E40 E41 E44 E45 E48 E49 E51 E52 E55 E57 E61 E62 E63 E68 E69 E72 E77", "U6 U8 U10 U11"),
    decision("D6", "sai-esds", "provider-shared-training", "off",
      "SAI as the provider that trains and owns a model for multiple customers.",
      "Customer workload content, content-bearing support logs and confidential technical information. Genuine Customer Feedback and non-content provider telemetry remain separate classifications.",
      "Improve the provider's shared support model for use across its customer base.",
      "SAI-owned shared model trained and hosted in Australia. Raw examples remain for 30 days. The model remains indefinitely. No external provider, assumed consent or assumed de-identification.",
      [
       "Keep the exact raw-content shared-training path off under the supplied set.",
       "Do not derive content-access authority from Foreground IPR ownership, the AI Outputs definition, security duties or generic service-improvement language.",
       "Preserve the specific 15.4 any-purpose override for actual Customer Feedback, except customer Background IPR. Do not convert all attached workloads into feedback.",
       "Apply 15.5 only to customer Background IPR actually incorporated within the relevant provider Foreground IPR. It grants no universal data licence.",
       "For a changed content-training proposal, obtain an effective signed purpose, access and data-role variation plus actual dataset rights and retention terms.",
       "Develop independent provider materials, genuinely licensed feedback and appropriate non-content operational analytics as separate improvement routes.",
       "Respect confidentiality and Personal Data restrictions even when operational data falls outside the Customer Data definition. Retention remains purpose-specific."
      ],
      "The exact operation crosses the 8.2 content prohibition and the 17.1 performance-purpose limit. Indefinite model retention also lacks an established return-duty solution. "
      "Broad foreground ownership determines some resulting IP rights. It does not authorise every antecedent access or training act. "
      "The strongest counter is 15.4's specific any-purpose feedback override. That route survives for genuine qualifying feedback, with its Background IPR exclusion. "
      "It does not turn arbitrary customer workloads into suggestions. Likewise, 8.2 permits useful non-content quantitative analytics without granting a workload-content licence. "
      "A changed signed content-training arrangement needs a new assessment. The Google disclosure adds inference only and cannot supply this missing training or retention right.",
      "E27 E30 E31 E37 E39 E40 E43 E44 E45 E46 E47 E48 E49 E52 E53 E54 E55 E68 E69 E73", "U6 U8 U10 U12")
]

unknowns = [
 {"id": "U1", "customer_id": "c3-bhge",
  "description": "The actual licensee and operative internal or downstream subscription, orders and SOWs are absent.",
  "resolution": "Obtain the complete executed April 29, 2019 internal MSSA and relevant orders for BH internal use. For downstream use, obtain that customer's executed subscription, order, SOW and applicable amendments. Identify the actor, application rights and support scope.",
  "evidence_ids": ["E2", "E3", "E4", "E7", "E13"]},
 {"id": "U2", "customer_id": "c3-bhge",
  "description": "The last supplied Initial Term ends April 30, 2024. Renewal exercise, termination history and current independent subscription rights are not supplied.",
  "resolution": "Obtain the applicable renewal, exercise record, later amendment or termination record. Establish the required renewal commitments and internal subscription coverage. Determine surviving subscriptions under their own terms.",
  "evidence_ids": ["E13", "E14", "E21"]},
 {"id": "U3", "customer_id": "c3-bhge",
  "description": "Material redactions and referenced documents remain absent. The Second Amendment supplies neither restated Exhibit E nor restated Exhibit F.",
  "resolution": "Obtain the relevant unredacted rights provisions and complete restated E and F. Obtain the applicable offerings, actual subscription, recipient restrictions and security terms. Do not restore the superseded originals or invent redacted terms.",
  "evidence_ids": ["E2", "E3", "E7", "E16", "E22"]},
 {"id": "U4", "customer_id": "c3-bhge",
  "description": "No actual dataset, third-party rights, selected model licence, Sensitive Information designations or qualifying 8.4 contribution record is established.",
  "resolution": "Inspect the actual rights inventory, selected model licence and recipient designations. Establish protected third-party permissions and permitted personnel. For 8.4, obtain BH ownership, express technology identification or actual Feedback provenance and its permitted purpose.",
  "evidence_ids": ["E7", "E8", "E9", "E10", "E11", "E74"]},
 {"id": "U5", "customer_id": "c3-bhge",
  "description": "No established licence covers arbitrary confidential workloads for shared training and indefinite model retention.",
  "resolution": "Obtain a signed dataset and model-use grant from the actual rights holders. Address shared beneficiaries, raw and model retention, confidential derivatives, deletion and downstream rights. Alternatively prove the narrower existing 8.4 licence contribution by contribution.",
  "evidence_ids": ["E8", "E10", "E12", "E15", "E22"]},
 {"id": "U6", "customer_id": "sai-esds",
  "description": "The MSA includes signature text, but the acquired Service Order's signature fields are blank. No executed applicable order is established.",
  "resolution": "Obtain the complete mutually executed applicable order, appendices, incorporated Product Specific Terms and effective signed changes. Confirm Special Conditions and actual party allocations. The ordinary order's Parent shorthand does not silently replace the MSA Customer definition.",
  "evidence_ids": ["E24", "E29", "E30", "E33", "E64", "E76"]},
 {"id": "U7", "customer_id": "sai-esds",
  "description": "The unqualified direct internal purpose lacks a signed scope variation. No actual End Customer resale or narrower resale-administration purpose is established.",
  "resolution": "For the exact proposal, obtain a signed variation to 4.3 and 4.8(a). For the useful alternative, establish the End Customer, executed order, binding End Customer Contract and incorporated Terms and Conditions. For reseller administration, establish its actual resale purpose before a separate decision. Reconcile the general 8.1.3 wording with the specific resale grant.",
  "evidence_ids": ["E24", "E25", "E33", "E34", "E38", "E49", "E65", "E77"]},
 {"id": "U8", "customer_id": "sai-esds",
  "description": "The selected site, mutual commissioning, first-advance confirmation, security fulfilment and current service state are absent.",
  "resolution": "Inspect the executed Data Centre site election and infrastructure record. Obtain the mutual Commissioning Certificate, written cleared-advance confirmation and current security or suspension state. Resolve certificate-form cross-references from the actual signed instrument. Do not infer activation from planned dates or generic deemed acceptance.",
  "evidence_ids": ["E26", "E28", "E31", "E35", "E42", "E48", "E58", "E59", "E75"]},
 {"id": "U9", "customer_id": "sai-esds",
  "description": "Customer-tool integration, selected model rights, provider plaintext exclusion and new application IP allocation lack actual implementation evidence.",
  "resolution": "Obtain integration diligence, technical conditions, fee scope and the model licence. Verify customer key custody and plaintext exclusion across runtime, OOB, memory, dumps and storage with synthetic data. Obtain prior written consent before any platform security test under 8.1.13. Reconcile 15.2, 15.3 and the Foreground IPR definition before an ownership representation.",
  "evidence_ids": ["E39", "E41", "E43", "E61", "E62", "E63", "E65", "E67", "E73"]},
 {"id": "U10", "customer_id": "sai-esds",
  "description": "Actual input rights, Personal Data exposure, customer Background IPR, confidentiality ownership and End Customer permissions are not established.",
  "resolution": "Inspect the actual dataset, rights records and access paths. Classify Personal Data and confidential material independently from Customer Data exclusions. Establish End Customer authority and actual Background IPR boundaries. A label or an assumed de-identification step supplies no permission.",
  "evidence_ids": ["E27", "E34", "E39", "E40", "E44", "E45", "E54", "E55"]},
 {"id": "U11", "customer_id": "sai-esds",
  "description": "No effective express signed variation permits provider content-support inference against the specific 8.2 proviso.",
  "resolution": "Obtain a signed instrument that expressly varies 8.2 for the exact data, model and support purpose. Reconcile 11.3, 11.6–11.7 and 17. A generic Special Condition priority claim, confidentiality consent or notice is insufficient. Preserve 2.4's express-otherwise boundary and each clause's scope.",
  "evidence_ids": ["E30", "E36", "E37", "E39", "E40", "E45", "E49"]},
 {"id": "U12", "customer_id": "sai-esds",
  "description": "The raw-content shared-training dataset lacks a demonstrated licence, content-access variation and retention solution. Qualifying feedback has not been identified.",
  "resolution": "For a changed proposal, obtain an effective signed access, purpose and data-role variation, actual dataset rights and raw/model retention terms. For existing narrower routes, classify genuine feedback, non-content telemetry and independent materials. Exclude customer Background IPR from the 15.4 override.",
  "evidence_ids": ["E27", "E37", "E40", "E43", "E44", "E45", "E46", "E49"]},
 {"id": "U13", "customer_id": "c3-bhge",
  "description": "No C3/BH Fullstory engagement, Google inference feature selection or feature data path is established. This is not a new prerequisite for the preserved no-external-provider proposal.",
  "resolution": "If a different supplier-enabled design is proposed, inspect its actual vendor agreement/DPA, service configuration and request traces. Establish role, payload, purpose, location, recipients and retention. Keep the present feature facts unchanged until such a separately assessed change exists.",
  "evidence_ids": ["E2", "E3", "E9", "E10", "E11", "E68", "E69", "E70", "E71"]},
 {"id": "U14", "customer_id": "sai-esds",
  "description": "No SAI/ESDS Fullstory engagement or Google inference data flow is established. Clauses 2.7, 23.7 and 23.9 also require reconciliation for a changed subcontractor design.",
  "resolution": "For a separately proposed supplier route, obtain the actual engagement, signed applicable terms, configuration and payload traces. Reconcile subcontractor authority without erasing content, residency or Personal Data limits. The disclosure's US/Germany listing cannot establish an Australian deployment or elect the Permitted Territory.",
  "evidence_ids": ["E28", "E30", "E31", "E37", "E40", "E48", "E50", "E68", "E69", "E72"]}
]

controls = []
operations = {op["id"]: op for op in feature["operations"]}
for row in decisions:
    op = operations[row["operation_id"]]
    facts = dict(op["proposed_facts"])
    for field in ("actor", "purpose", "data_access", "model", "training", "retention", "regions"):
        facts[field] = copy.deepcopy(op[field])
    facts["data_categories"] = copy.deepcopy(feature["data"])
    controls.append({
        "decision_id": row["id"], "customer_id": row["customer_id"], "operation_id": row["operation_id"],
        "proposed_eligible": False, "required_facts": facts,
        "reason": f"{row['id']} is {row['status']}. Its exact contract prerequisites are unresolved or its purpose is unsupported. "
                  "The literal facts preserve the hypothetical proposal and are matching requirements only. They attest to no actual deployment, contract, consent or supplier engagement. "
                  "This customer-operation rule remains false. A changed actor, purpose, recipient, dataset or rights record needs a separate source-bound decision."
    })


def ticket(identity, title, body, acceptance, ids):
    return {"id": identity, "title": title, "body": body, "acceptance_criteria": acceptance, "decision_ids": ids.split()}


engineering = [
 ticket("ENG1", "Implement customer-controlled content diagnosis with a distinct provider metadata route",
   "Evidence E1–E3, E26, E37, E39 and E61–E63 supports separate control and content responsibilities. "
   "Place retrieval, document parsing and the open-weight runtime inside the customer tenant. Attach source ACLs to chunks, retrieval and answers. "
   "Keep customer keys and runtime plaintext outside provider administrative access. At-rest encryption alone cannot prove that boundary during inference. "
   "Exclude payloads from consoles, OOB recordings, dumps, traces, support bundles and snapshots. Emit only explicitly classified infrastructure facts to the provider. "
   "The provider copilot uses its own manuals and those facts. It returns diagnostic steps that the customer administrator executes inside the content boundary. "
   "For C3, bind the actual subscription and support scope. For SAI, use the verified End Customer resale route or an effective direct-use variation. "
   "A narrower reseller-administration design needs its own evidenced resale purpose. Resolve model licences, integration terms and the elected site before deployment. "
   "This local packet contains the design and tests. It does not establish an implemented production runtime.",
   "Use two synthetic documents with distinct ACLs and unique markers. The authorised user receives a source-bound answer. The other user receives no protected answer. "
   "Provider identities cannot recover markers from memory, storage, OOB, logs, caches, dumps or backups. A content marker in a telemetry field causes rejection. "
   "Network observation shows no separate model recipient. Compute and every replica resolve to the actual elected site. "
   "Missing subscription, integration, resale or commissioning evidence leaves the exact customer rule false. Obtain required prior consent before any actual platform security test.",
   "D1 D2 D4 D5"),
 ticket("ENG2", "Make metadata support useful without workload reconstruction",
   "Evidence E27, E36–E40, E45, E52, E55 and E62–E63 separates hardware support from content interpretation. "
   "Define event schemas for provider-generated error codes, fault counters and capacity signals. Require producer identity, schema version, source purpose and data classification. "
   "Reject unknown producers, arbitrary log bodies, command output, memory dumps and mixed records. Reject customer snippets, prompt fields and filenames with content. "
   "Check confidentiality and Personal Data separately. Exclusion from Customer Data does not erase either duty. "
   "Return a provider-runbook reference, fault classification and a customer-executable diagnostic step. The customer retains any content-rich result. "
   "Do not treat a redacted workload as non-content without an actual content and reconstruction test. "
   "This alternative does not activate D2 or D5, which specifically require provider access to customer content.",
   "A hardware ECC counter returns the matching runbook and diagnostic action. A customer-uploaded log fails the producer check. "
   "A provider event with an embedded prompt fails the content check. An altered telemetry label changes no result. "
   "A sequence of allowed signals must not reconstruct a workload secret. A Personal Data identifier fails the separate exposure check. "
   "The exact zero-retention content-support context still evaluates false for both customer pairs.", "D2 D5 D6"),
 ticket("ENG3", "Implement contribution-specific improvement datasets without raw-content laundering",
   "Evidence E8, E10, E12, E22, E27, E37 and E43–E46 supports several distinct improvement routes. "
   "Maintain separate classes for independent provider/public materials, non-content operational analytics, qualifying feedback and customer content. "
   "For C3 technology, require BH ownership, express identification and the actual 8.4 purpose. For C3 Feedback, establish an actual qualifying contribution. "
   "Do not rely on superseded Exhibit E generalization language. For SAI feedback, preserve the actual suggestion and exclude customer Background IPR. "
   "Separate abstract bug suggestions from attached workload examples. Classify each attachment independently. "
   "Apply 15.5 only to actually incorporated Background IPR. Preserve confidential-information and Personal Data duties outside any genuine override. "
   "Record dataset lineage and the retention rules for examples, derived datasets and checkpoints. An independent synthetic corpus must not derive from protected customer examples. "
   "Keep the two exact raw-content training controls false. Reassess any changed dataset and model purpose separately.",
   "A genuine abstract suggestion enters only its proven contribution class. A private trace attached to that suggestion remains outside the feedback class. "
   "A C3 technology record without ownership or express identification fails. A SAI record with customer Background IPR fails the 15.4 override test. "
   "A checkpoint without complete dataset lineage cannot enter the shared-model registry. Rewritten customer text cannot enter the independent synthetic class. "
   "Qualifying feedback is not rejected merely because the raw-content operation is off.", "D3 D6"),
 ticket("ENG4", "Resolve contract scope with clause-specific hierarchy and actual service-state evidence",
   "Evidence E2–E4, E13, E15–E23, E24, E28–E35, E37, E42, E49, E58–E65 and E75–E77 governs the source resolution. "
   "Bind each decision to the actual licensee, actor, data, purpose, model role and current subscription or order. "
   "Apply each C3 amendment only to its expressed replacements. Keep missing restated E and F absent. The JV body outranks its exhibits under 13.18. "
   "The 8.4 contribution licence and 9.4 retention exception remain scoped. A JV termination date does not determine independent subscription rights. "
   "Within SAI, 2.4 ranks expressly identified Special Conditions, then MSA, then ordinary order terms at actual inconsistencies. "
   "Preserve its express-otherwise proviso. Section 8.2 overrides contrary agreement or order terms for Customer Data content. "
   "A generic Special Condition cannot silently defeat that proviso. Require an effective express signed variation for the selected content-access route. "
   "The JSON precedence array has no valid same-document edge. Preserve SAI's internal hierarchy here, in D5 and in U11 with E30/E37 evidence. "
   "Reconcile 2.7, 23.7 and 23.9 if a third-party design is later proposed. None overrides purpose, content, confidentiality or residency. "
   "Distinguish the signed MSA text from the blank included order. Resolve site election, commissioning, payment confirmation and actual suspension state. "
   "Do not use generic deliverable deemed acceptance to infer computing commencement.",
   "The First Amendment's April 30, 2022 term yields to the Second Amendment's expressly replaced April 30, 2024 term. "
   "Neither proves current renewal or independent subscription expiry. Original Exhibit E stays superseded despite an absent replacement. "
   "An ordinary order and a generic Special Condition both fail an attempted 8.2 content override. An effective express signed variation prompts a new scoped assessment. "
   "Blank signatures, a planned start date, elapsed time, generic deemed acceptance and an Australia label without a site cannot satisfy service readiness.",
   "D1 D2 D3 D4 D5 D6"),
 ticket("ENG5", "Compile the exact local rules and verify the real OpenFeature and SQLite consumers",
   "Use the supplied tools unchanged. Export one decision and one control per customer-operation pair. "
   "Preserve every original operation fact, including actor, access, model, training, retention and Australia. No supplier update rewrites those facts. "
   "Keep all six eligibility values false. Exact matching facts describe this hypothetical proposal, not proved production facts. "
   "Execute validate, compile and readback. Compare the authored bundle and compiled export directly with the SQLite row and tool readback. "
   "Exercise the real OpenFeature SDK with complete contexts, unknown customers and missing facts. Add isolated positive and negative synthetic rule tests. "
   "Do not place a synthetic eligible rule in the customer export or receiver. Generate OPA artifacts through the supplied compiler. "
   "Claim OPA execution only if an actual OPA runtime evaluates the policy.",
   "Exact quotation checks pass for every evidence entry. All six complete contexts evaluate false in the real SDK. "
   "The compiler's 18 evaluations match the proposed controls. SQLite holds the exact authored bundle and exact export at the canonical bundle hash. "
   "An isolated synthetic eligible rule accepts complete typed facts. It rejects missing facts, wrong purpose, recipient changes and numeric substitutes for booleans. "
   "The customer export remains identical after synthetic tests. No live feature or customer account changes.", "D1 D2 D3 D4 D5 D6"),
 ticket("ENG6", "Retain complete-set coverage, strong counter-readings and source limits",
   "C3 base agreement: platform, distribution, noncompetition and preferred-platform clauses establish actors and scope, not a universal data licence. "
   "Sections 8 and 9 preserve ownership, qualifying contributions, use limits, recipient designations, return and survival. "
   "The internal MSSA and downstream subscriptions remain independent sources. The first amendment changes named periods, calculations and roadmap sections. "
   "The second replaces the term and entire B-1, E and F. Revenue tables and redacted commercial conditions create no inferred data grant. "
   "The original roadmap generalization clauses are a strong counter-reading, but they are both weaker than a blanket training licence and superseded. "
   "C3 feature evolution preserves functionality constraints and a quarterly information duty if an applicable real offering changes. This hypothetical assessment triggers no launch notice. "
   "Privacy and compliance clauses retain their stated scopes. Do not infer statutory applicability, critical-use suitability or missing contractual authority from them. "
   "SAI: preserve definitions, resale scope, monitoring proviso, keys, residency, Personal Data roles, IP, feedback, confidentiality, AUP and actual service readiness. "
   "Section 15.4 is the strongest specific improvement override. Its qualifying feedback and Background IPR boundary must survive the raw-workload refusal. "
   "Section 15.5 requires actual incorporation. Open-source rights concern the component, not service purpose or customer data. "
   "The broad Foreground IPR definition does not eliminate 15.2's application-layer exclusion or establish access authority. "
   "AUP compliance investigations, compelled disclosure and audit have distinct scopes. Audit expressly excludes Customer Data. "
   "AUP changes, SLA changes and infrastructure maintenance have their own notice mechanisms. None is a generic AI launch-notice route. "
   "Backup security language creates no dedicated customer-backup service or permission for out-of-site copies. "
   "The included order supplies hardware-only support, customer-managed application/storage responsibilities, integration conditions and shared OOB risk. "
   "Security, KYC, financing, pledge, tax, termination, indemnity, insurance and dispute terms remain relevant to their subjects. "
   "They do not grant a new AI content purpose or prove payment, signatures, commissioning, current contract status or supplier engagement. "
   "Redacted financial and account fields remain redacted. The separate pledge purpose creates no feature data-access right. "
   "Fullstory is shared source context, not a third customer or an incorporated amendment. Its historical version proves only its captured disclosure. "
   "Exact quote verification proves provenance. It cannot prove legal correctness or current customer clearance.",
   "Evidence spans all four customer documents and both Fullstory captures. Each material decision and cross-document precedence edge cites actual source evidence. "
   "The packet names the absent operative sources and the strongest useful alternative. It contains no fabricated supplier relationship, launch notice or current deployment claim. "
   "A reviewer can distinguish contractual permission, disclosure scope, actual engagement and actual feature data flow.", "D1 D2 D3 D4 D5 D6"),
 ticket("ENG7", "Track the added Google inference purpose without changing feature facts or inventing engagement",
   "Evidence E68/E69 shows one material supplier-row change. Google gains 'AI model inference for in-product AI features' beside its existing purposes. "
   "Customer/end-user data and United States/Germany remain unchanged. Both captures print June 2, 2026. E70/E71 shows unchanged optional OpenAI and Anthropic rows. "
   "Create source-comparison.json from both complete texts. Preserve original hashes, text hashes, observation clocks, row values, displayed dates and all text differences. "
   "Classify navigation, promotional and footer changes separately from the Google purpose addition. Do not equate a changed disclosure with a new engagement. "
   "Use content hashes and row-level semantic comparison rather than the printed date as the revision key. The historical capture lacks an explicit Google inference purpose. "
   "That absence does not prove Google never performed inference before. Neither capture supplies the feature, model, retention, regional deployment or customer-specific agreement. "
   "Record engagement as not_established for both customer sets. Preserve all three operations' no-separate-model-provider facts. "
   "For a future actual Fullstory route, bind the engagement and configuration to its contract/DPA and observed payload path before reassessment. "
   "Check C3 permitted purpose/recipients and SAI content, Personal Data and exact-site limits. US/Germany disclosure cannot establish Australian site compliance. "
   "An inference-purpose disclosure grants no shared training right. Create no notice, consent countdown or account mutation from this reference change alone. "
   "Run watch finalize and readback after the normal tools. Compare the stored revision impact and engineering action exactly with the authored packet.",
   "The before row lacks the added phrase. The after row contains it. Displayed dates and all Google fields except purpose compare equal. "
   "All seven supplier rows are compared. Optional OpenAI and Anthropic compare equal. Navigation-only changes do not produce a purpose change. "
   "The complete unified text diff matches R1. Original byte hashes and text hashes differ even though the printed date matches. "
   "Both customer sets remain not_established for actual engagement. No source-only change alters an operation fact or creates another customer. "
   "All six statuses remain unchanged. The revision SQLite event equals change-summary.json, including REV1, all engineering outputs and the current feature hash.",
   "D1 D2 D3 D4 D5 D6")
]

drafts = [
 {"type": "information_request", "customer_id": "c3-bhge",
  "reason": "The JV identifies separate subscriptions and missing replaced exhibits. These actual sources can resolve U1–U4.",
  "draft": "Conditional local request for the actual contract owner: Please provide the executed internal or downstream subscription, applicable order, SOW and later amendments. Include actual renewal or termination records and restated Exhibits E and F. Identify the licensee, authorised users, support scope and Sensitive Information audience. For any 8.4 route, provide ownership, express contribution identification or actual Feedback evidence and the permitted purpose. Keep unnecessary personal and financial values redacted. This request has no recipient or dispatch date until the applicable records identify them.",
  "unknown_fields": ["actual recipient", "operative licensee and agreement route", "applicable orders and signed changes", "current rights", "restated exhibits and material redactions"],
  "evidence_ids": ["E2", "E3", "E7", "E8", "E11", "E13", "E21", "E22"]},
 {"type": "consent", "customer_id": "c3-bhge",
  "reason": "Arbitrary confidential-workload shared training lacks a demonstrated purpose-specific grant. Existing 8.4 contributions require a separate scoped analysis.",
  "draft": "Conditional grant terms for the actual rights holders and contracting parties: C3 may use only the scheduled dataset for the identified shared support model. The executed schedule must identify data rights, purpose, permitted recipients and cross-customer beneficiaries. Raw examples may remain for 30 days. Indefinite model retention requires an express term for learned confidential information, return, deletion and cessation of use. No downstream rights or Sensitive Information permissions arise by implication. Existing terms continue outside this exact scope. No grant takes effect without the required signed instrument and actual rights-holder authority.",
  "unknown_fields": ["actual parties and rights holders", "dataset and exclusions", "model identity and permitted use", "recipients", "effective date", "model retention and deletion terms", "required signatures"],
  "evidence_ids": ["E8", "E9", "E10", "E11", "E12", "E15"]},
 {"type": "information_request", "customer_id": "sai-esds",
  "reason": "The actual order, site, service state, use route and integration conditions remain unproved.",
  "draft": "Conditional local request for the actual contract owner: Please provide the mutually executed applicable Service Order and all incorporated terms and signed changes. Identify the actual Customer, Parent and End Customer roles. Include the site election, mutual Commissioning Certificate and nonsecret confirmations that establish current service availability. Provide the customer-tool integration conditions, model licence and actual data-rights record. Identify any effective signed variation of the resale-only purpose or provider content-access restriction. Do not include credentials or full financial values.",
  "unknown_fields": ["actual recipient", "executed order and incorporated terms", "parties and use route", "Data Centre site", "service state", "integration conditions", "effective signed variations"],
  "evidence_ids": ["E24", "E28", "E29", "E30", "E33", "E34", "E35", "E37", "E42", "E49", "E58", "E59", "E61", "E64", "E76"]},
 {"type": "consent", "customer_id": "sai-esds",
  "reason": "The unqualified contracting-customer internal purpose needs an effective signed scope variation. An actual End Customer resale route remains distinct.",
  "draft": "Conditional variation terms for the actual contracting parties: The identified Customer may use the scheduled capacity for its own internal Tenant Operations Copilot questions. This varies clauses 4.3 and 4.8(a) only for the stated purpose and users. The Customer controls the model, content and keys. SAI receives no content-access, prompt-retention or training right through this variation. The applicable order must identify the permitted site and integration conditions. All other data-rights, confidentiality, usage and residency requirements continue. The variation takes effect only through the required signed written instrument.",
  "unknown_fields": ["applicable order and capacity", "Customer and authorised users", "effective date", "elected site", "integration scope", "required parties and signatures"],
  "evidence_ids": ["E24", "E30", "E33", "E34", "E37", "E49", "E61"]},
 {"type": "consent", "customer_id": "sai-esds",
  "reason": "Provider support inference requires an effective express signed variation of 8.2. A notice or generic Special Condition priority claim is insufficient.",
  "draft": "Conditional variation terms for the actual contracting parties: For the scheduled data and support sessions only, the parties expressly vary clause 8.2's content prohibition. SAI may use the identified tenant-isolated model only to answer that same customer's support question. The variation must expressly reconcile clause 11.3 and the applicable confidentiality terms. No separate model provider receives content. SAI retains no prompts or outputs after the session and receives no training right. The schedule must identify the permitted site, recipients and actual data rights. Customer Personal Data remains excluded unless a separate effective signed role arrangement and actual authority cover it. All other terms remain effective. This proposal creates no permission before the required signatures and scope resolution.",
  "unknown_fields": ["applicable order", "actual dataset and rights holders", "model identity and recipients", "Data Centre site", "effective date", "Personal Data exclusion or separate role arrangement", "required parties and signatures"],
  "evidence_ids": ["E27", "E28", "E30", "E36", "E37", "E39", "E40", "E45", "E49"]}
]

revision_impacts = [{
 "id": "REV1", "change_id": "R1",
 "source_effect": "The complete current Fullstory capture adds Google LLC AI model inference for in-product AI features to storage, processing and security monitoring. "
                  "The historical row lacks that express purpose. The Google data categories and United States/Germany locations remain unchanged. "
                  "Both complete captures display June 2, 2026, so the printed date does not establish content stability. "
                  "The historical archive observation is June 14, 2026. The current acquisition observation is October 31, 2026. "
                  "Those clocks bound supplied observations, not publication, effective permission, first inference use or engagement dates. "
                  "OpenAI remains optional and its generative-AI purpose is unchanged. Anthropic's service-delivery purpose is unchanged. "
                  "Navigation, promotional, legal-link and footer differences create no additional data-use grant. "
                  "This is a change in public supplier disclosure only. It neither grants customer-content training rights nor amends either supplied customer agreement.",
 "engagement_state": "not_established",
 "affected_operation_ids": ["customer-controlled-inference", "provider-support-inference", "provider-shared-training"],
 "customer_status_effect": "All three operations require impact review, but no actual Google data path is established for any operation. "
                           "C3 customer inference and support remain unresolved. C3 raw-content shared training remains needs_consent. "
                           "SAI direct internal inference and provider content support remain needs_consent. SAI raw-content shared training remains off. "
                           "All six controls remain false. The customer sources and original feature facts still determine those results. "
                           "The feature specifies open-weight customer/provider models in Australia, no separate model recipient and no external content transfer. "
                           "A Fullstory disclosure cannot silently replace those facts with Google inference or establish a relationship with either customer set. "
                           "No source-triggered customer notice, consent countdown or current-contract clearance follows from this shared reference alone.",
 "engineering_action": "ENG7 adds source-comparison.json and executable local revision tests. Compare complete versions and structured supplier rows independently from displayed dates. "
                       "Preserve hashes, observation clocks, the exact Google purpose delta and unchanged fields. Separate navigation noise from substantive purpose change. "
                       "Record actual engagement as not_established. Preserve every original operation fact and the two-customer population. "
                       "For a later supplier-enabled design, require its actual contract/DPA, configuration and observed payload path before a new scoped assessment. "
                       "Check C3 purpose and recipient rights plus SAI content, Personal Data and exact-site restrictions. Do not infer Australian compliance from US/Germany. "
                       "Keep inference and shared training distinct. Add isolated SDK tests that reject recipient and purpose mismatches. "
                       "Execute normal validation, compilation and SQLite readback, then watch finalize and revision readback. "
                       "Verify the stored event contains this exact impact and all seven engineering outputs while status_changes remains empty.",
 "evidence_ids": ["E2", "E3", "E8", "E10", "E11", "E21", "E22", "E27", "E28", "E30", "E31", "E33", "E34", "E37", "E40", "E44", "E45", "E48", "E49", "E50", "E68", "E69", "E70", "E71", "E72"],
 "unknown_ids": ["U13", "U14"]
}]

bundle = {
 "assessment_type": "proposed_source_bound_decisions", "feature_id": feature["id"],
 "summary": "All six exact operations retain their prior status after a fresh complete-set assessment. "
            "C3 customer-controlled inference and content support remain unresolved because operative subscriptions, current rights and material restatements are absent. "
            "C3 raw-content shared training needs a scoped grant unless a complete existing licence proves that exact use. "
            "SAI's unqualified direct internal inference needs a resale-purpose variation. SAI provider content support needs an express signed variation of the content prohibition. "
            "SAI raw-content shared training remains off. The strongest useful design keeps content-rich inference with the authorised customer and limits provider diagnosis to non-content signals and provider manuals. "
            "Preserve actual End Customer resale, narrow resale administration, qualifying feedback and expressly licensed technology as separate useful routes. "
            "The Fullstory capture adds a Google inference purpose despite an unchanged printed revision date. It establishes neither customer engagement nor this feature's data flow. "
            "All six proposed eligibility values remain false. Seven engineering outputs include executable source comparison and exact local consumer verification. "
            "No AI launch notice arises from this hypothetical proposal or the shared reference change. Conditional drafts are local preparation only. "
            "This public-source proposal is neither current customer clearance nor actual outside use. Provenance validation does not prove legal interpretation.",
 "evidence": evidence, "precedence": precedence, "decisions": decisions, "unknowns": unknowns,
 "controls": controls, "engineering_outputs": engineering, "notices_or_consent_drafts": drafts,
 "revision_impacts": revision_impacts
}

# A complete comparison artifact preserves every observed supplier row and text delta.
def supplier_rows(text):
    table = text.split("ENTITY NAME\nPURPOSE OF PROCESSING\nPROCESSED DATA\nLOCATION\n", 1)[1].split("\nFollow us", 1)[0]
    names = ["Google LLC", "Fastly, Inc. (Signal Sciences Corporation)", "Salesforce", "Zendesk", "Marketo", "OpenAI (optional)", "Anthropic"]
    lines = table.splitlines()
    rows = {}
    for i, name in enumerate(names):
        a = lines.index(name)
        b = lines.index(names[i + 1]) if i + 1 < len(names) else len(lines)
        fields = lines[a + 1:b]
        assert len(fields) in (2, 3)
        rows[name] = {"entity": name, "purpose": fields[0], "processed_data": fields[1],
                      "location": fields[2] if len(fields) == 3 else None,
                      "exact_row_text": "\n".join(lines[a:b])}
    return rows


old_rows, new_rows = supplier_rows(texts[BEFORE]), supplier_rows(texts[AFTER])
changes = []
for name in old_rows:
    fields = [k for k in ("purpose", "processed_data", "location") if old_rows[name][k] != new_rows[name][k]]
    if fields:
        changes.append({"entity": name, "changed_fields": fields,
                        "before": old_rows[name], "after": new_rows[name]})
diff = "\n".join(difflib.unified_diff(texts[BEFORE].splitlines(), texts[AFTER].splitlines(),
                                    fromfile="before/fullstory/subprocessor-list.html",
                                    tofile="after/fullstory/subprocessor-list.html", n=6))
assert diff == context["input_changes"][0]["complete_observed_text_diff"]
assert len(changes) == 1 and changes[0]["entity"] == "Google LLC"
assert changes[0]["changed_fields"] == ["purpose"]
comparison = {
 "change_id": "R1", "comparison_scope": "Complete supplied extracted texts and all seven supplier rows. Original-byte identity uses the supplied acquisition hashes.",
 "before": {"document_id": BEFORE, "original_sha256": documents[BEFORE]["original_sha256"],
            "text_sha256": documents[BEFORE]["text_sha256"], "provenance": documents[BEFORE]["provenance"], "rows": old_rows},
 "after": {"document_id": AFTER, "original_sha256": documents[AFTER]["original_sha256"],
           "text_sha256": documents[AFTER]["text_sha256"], "provenance": documents[AFTER]["provenance"], "rows": new_rows},
 "before_displayed_date": next(line for line in texts[BEFORE].splitlines() if line.startswith("Last Updated:")),
 "after_displayed_date": next(line for line in texts[AFTER].splitlines() if line.startswith("Last Updated:")),
 "supplier_row_changes": changes, "unchanged_supplier_rows": [n for n in old_rows if old_rows[n] == new_rows[n]],
 "complete_observed_text_diff": diff,
 "other_changes": "Navigation, product labels, promotional text, Modern Slavery Statement links and a footer marker differ. None independently changes the listed supplier data scope.",
 "engagement_by_customer": {"c3-bhge": "not_established", "sai-esds": "not_established"},
 "current_feature_facts_sha256": hashlib.sha256(json.dumps(feature, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest(),
 "feature_facts_changed_by_assessment": False, "direct_feature_data_flow_established": False,
 "temporal_limit": "Observation clocks do not establish publication, contract amendment, engagement or first-use dates.",
 "engineering_output_id": "ENG7", "revision_impact_id": "REV1"
}

for name, value in (("model-decisions.json", bundle), ("source-comparison.json", comparison)):
    (WORK / name).write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")
print(json.dumps({"authored_decisions": len(decisions), "controls": len(controls), "exact_evidence_candidates": len(evidence),
                  "engineering_outputs": len(engineering), "revision_impacts": len(revision_impacts),
                  "supplier_changed_fields": [{"entity": c["entity"], "fields": c["changed_fields"]} for c in changes]}))
