import unittest

import pack

FACTS = dict(training_data_class='input', training_benefit='shared', improves_model=False,
             improvement_benefit='shared', identifies_customer=False,
             proper_human_oversight=False, falsely_claims_human=True)

def result(cover, facts=None):
    return {r['operation_id']: r for r in pack.interpret(cover, facts or FACTS)}

class SourcePackTests(unittest.TestCase):
    def test_originals_and_public_runtime(self):
        self.assertEqual(pack.verify_sources()['source_version'], 'Common Paper AI Addendum1.0')

    def test_no_training_does_not_delete_improvement(self):
        r = result(pack.default_cover())
        self.assertEqual(r['model_training']['scoped_status'], 'off')
        self.assertEqual(r['system_improvement']['scoped_status'], 'live_with_conditions')
        self.assertTrue(all(x['overall_status'] == 'unresolved' for x in r.values()))

    def test_training_requires_both_variables(self):
        for missing in ['training_data', 'training_purposes']:
            c = pack.default_cover()
            c.update(training_data=['input'], training_purposes=['ai_services'])
            c[missing] = []
            self.assertEqual(result(c)['model_training']['scoped_status'], 'off')

    def test_explicit_none_conflict(self):
        for field in ['training_data', 'training_purposes', 'training_restrictions', 'improvement_restrictions']:
            c = pack.default_cover()
            c[field] = ['none', next(iter({'training_data':pack.DATA,'training_purposes':pack.PURPOSES,
                 'training_restrictions':pack.TRAINING,'improvement_restrictions':pack.IMPROVEMENT}[field]))]
            with self.assertRaisesRegex(ValueError, 'conflicting_none'):
                result(c)

    def test_customer_only_and_shared_conflict(self):
        c = pack.default_cover()
        c['training_purposes'] = ['ai_services','solely_customer_benefit']
        with self.assertRaisesRegex(ValueError, 'conflicting_customer_only'):
            result(c)

    def test_customer_only_training(self):
        c = pack.default_cover()
        c.update(training_data=['input'], training_purposes=['solely_customer_benefit'])
        self.assertEqual(result(c)['model_training']['scoped_status'], 'off')
        f = dict(FACTS, training_benefit='solely_customer')
        self.assertEqual(result(c, f)['model_training']['scoped_status'], 'live_with_conditions')

    def test_data_selection_exact(self):
        for category in sorted(pack.DATA):
            c = pack.default_cover()
            c.update(training_data=[category], training_purposes=['ai_services'])
            f = dict(FACTS, training_data_class=category)
            self.assertEqual(result(c, f)['model_training']['scoped_status'], 'live_with_conditions')
            f['training_data_class'] = 'output' if category=='input' else 'input'
            self.assertEqual(result(c, f)['model_training']['scoped_status'], 'off')

    def test_model_change_is_not_system_only_improvement(self):
        self.assertEqual(result(pack.default_cover(), dict(FACTS, improves_model=True))['system_improvement']['scoped_status'], 'off')

    def test_improvement_choices(self):
        c = pack.default_cover()
        c['improvement_restrictions'] = ['solely_customer_benefit']
        self.assertEqual(result(c)['system_improvement']['scoped_status'], 'off')
        self.assertEqual(result(c, dict(FACTS, improvement_benefit='solely_customer'))['system_improvement']['scoped_status'], 'live_with_conditions')
        c['improvement_restrictions'] = ['no_customer_identification']
        self.assertEqual(result(c, dict(FACTS, identifies_customer=None))['system_improvement']['scoped_status'], 'unresolved')

    def test_custom_terms_do_not_match_standard_assumptions(self):
        c = pack.default_cover()
        c['custom_text'] = 'The provider shall never use Output to improve any system.'
        self.assertTrue(all(r['scoped_status'] == 'unresolved' for r in result(c).values()))

    def test_missing_aup_and_underlying(self):
        c = pack.default_cover()
        c['ai_aup_selected'] = True
        self.assertTrue(all(len(r['source_set_gaps']) == 3 for r in result(c).values()))

    def test_indemnity_never_follows_ownership(self):
        c = pack.default_cover()
        self.assertEqual(result(c)['output_indemnity']['scoped_status'], 'off')
        c['provider_covered_claims'] = True
        self.assertEqual(result(c)['output_indemnity']['scoped_status'], 'unresolved')

    def test_regulated_and_human_controls(self):
        r = result(pack.default_cover())
        self.assertEqual(r['regulated_decision']['scoped_status'], 'off')
        self.assertEqual(r['human_attribution']['scoped_status'], 'off')

    def test_schema_version_and_typing(self):
        for mutation in [dict(version='2.0'),dict(ai_aup_selected=1),dict(training_data=['magic']),dict(extra='x'),dict(underlying_agreement_supplied=True),dict(private_amendments_reviewed=True)]:
            c = pack.default_cover()
            c.update(mutation)
            with self.assertRaises(ValueError):
                result(c)

    def test_efforts_do_not_replace_actual_deidentification(self):
        c = pack.default_cover()
        c.update(training_data=['input'], training_purposes=['ai_services'], training_restrictions=['deidentified'])
        f = dict(FACTS, commercially_reasonable_deidentification_performed=True)
        self.assertEqual(result(c, f)['model_training']['scoped_status'], 'unresolved')
        f['deidentified_training_data'] = False
        self.assertEqual(result(c, f)['model_training']['scoped_status'], 'off')
        f['deidentified_training_data'] = True
        self.assertEqual(result(c, f)['model_training']['scoped_status'], 'live_with_conditions')
        c['training_restrictions'] = ['commercially_reasonable_deidentification']
        f['deidentified_training_data'] = False
        self.assertEqual(result(c, f)['model_training']['scoped_status'], 'live_with_conditions')

    def test_missing_facts_stay_unknown(self):
        r = result(pack.default_cover(), {'unrelated':True})
        for op in ['model_training','system_improvement','regulated_decision','human_attribution']:
            self.assertEqual(r[op]['scoped_status'], 'unresolved')

    def test_feedback_does_not_become_input_through_default(self):
        for category in ['feedback','usage_data','customer_content']:
            r=result(pack.default_cover(),dict(FACTS,training_data_class=category))
            self.assertEqual(r['model_training']['scoped_status'],'unresolved')

    def test_customer_indemnity_is_a_separate_cover_choice(self):
        c=pack.default_cover()
        self.assertEqual(result(c)['input_indemnity']['scoped_status'],'off')
        c['customer_covered_claims']=True
        self.assertEqual(result(c)['input_indemnity']['scoped_status'],'unresolved')
        self.assertEqual(result(c)['output_indemnity']['scoped_status'],'off')

    def test_policy_boolean_cannot_replace_policy_source(self):
        c=pack.default_cover();c['ai_aup_supplied']=True
        with self.assertRaisesRegex(ValueError,'actual_aup_interpretation_requires'):
            result(c)

    def test_input_grant_includes_prompts_without_reverse_expansion(self):
        c=pack.default_cover()
        c.update(training_data=['input'],training_purposes=['ai_services'])
        self.assertEqual(result(c,dict(FACTS,training_data_class='user_prompts_only'))['model_training']['scoped_status'],'live_with_conditions')
        c['training_data']=['user_prompts_only']
        self.assertEqual(result(c,dict(FACTS,training_data_class='input'))['model_training']['scoped_status'],'off')

    def test_malformed_facts_cannot_bypass_model_classification(self):
        for value in ['false',0,1,[],{}]:
            with self.subTest(value=value),self.assertRaisesRegex(ValueError,'literal_boolean_fact_required'):
                result(pack.default_cover(),dict(FACTS,improves_model=value))

if __name__ == '__main__':
    unittest.main()
