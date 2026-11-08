import unittest

import standard_packs as s

class CurrentStandardTests(unittest.TestCase):
    def status(self,kind,c,f,op):
        return next(r['scoped_status'] for r in s.assess(kind,c,f) if r['operation_id']==op)

    def test_actual_current_versions_and_pins(self):
        self.assertEqual(s.verify_pins()['versions'],{'csa':'3.0','dpa':'1.1','bonterms_ai':'2.0'})
        for kind,old in [('csa3','2.1'),('dpa11','1.0'),('bonterms2','1.0')]:
            with self.assertRaisesRegex(ValueError,'exact_paper_version'):
                s.assess(kind,{'version':old},{})

    def test_csa_usage_disclosure_two_conditions(self):
        c={'version':'3.0'}
        for aggregate,anonymous,expect in [(True,True,'live_with_conditions'),(True,False,'off'),(False,True,'off'),(True,None,'unresolved')]:
            f=dict(usage_data_aggregated=aggregate,usage_data_nonidentifying=anonymous)
            self.assertEqual(self.status('csa3',c,f,'usage-data-external-disclosure'),expect)

    def test_csa_v3_does_not_import_old_ml_default(self):
        self.assertEqual(self.status('csa3',{'version':'3.0'},{},'general-model-training-content'),'unresolved')

    def test_csa_purpose_and_data_authorization(self):
        c={'version':'3.0','prohibited_data_authorized':False,'dpa_selected':False}
        f={'necessary_to_provide_or_maintain_product':False,'gdpr_personal_data':True}
        for op in ['service-content-use','prohibited-data-submission','gdpr-personal-data-submission']:
            self.assertEqual(self.status('csa3',c,f,op),'off')
        self.assertEqual(self.status('csa3',{'version':'3.0'},f,'gdpr-personal-data-submission'),'unresolved')

    def test_dpa_approved_identity_does_not_replace_flowdown(self):
        c={'version':'1.1'}
        for flowdown,expect in [(True,'live_with_conditions'),(False,'off'),(None,'unresolved')]:
            f=dict(subprocessor_approval_state='approved',subprocessor_written_flowdown=flowdown,new_subprocessor_change=False)
            self.assertEqual(self.status('dpa11',c,f,'subprocessor-content-transfer'),expect)

    def test_dpa_ten_business_days_do_not_equal_thirty_day_acceptance(self):
        c={'version':'1.1'}
        f=dict(subprocessor_approval_state='not_approved',notice_business_days=10,notice_calendar_days=14,
               customer_objected=False,subprocessor_written_flowdown=True)
        self.assertEqual(self.status('dpa11',c,f,'subprocessor-content-transfer'),'needs_consent')
        f['notice_calendar_days']=30
        self.assertEqual(self.status('dpa11',c,f,'subprocessor-content-transfer'),'live_with_conditions')
        f['customer_objected']=True
        self.assertEqual(self.status('dpa11',c,f,'subprocessor-content-transfer'),'needs_consent')

    def test_dpa_business_day_clock_is_explicit_not_inferred(self):
        c={'version':'1.1'}
        f=dict(subprocessor_approval_state='not_approved',notice_calendar_days=30,customer_objected=False,
               subprocessor_written_flowdown=True)
        self.assertEqual(self.status('dpa11',c,f,'subprocessor-content-transfer'),'needs_consent')

    def test_dpa_module_follows_customer_role_not_provider_label(self):
        for role,label in [('controller','Module Two'),('processor','Module Three')]:
            rows=s.assess('dpa11',{'version':'1.1','customer_role':role},{})
            r=next(r for r in rows if r['operation_id']=='restricted-transfer')
            self.assertIn(label,r['rationale'])
            self.assertEqual(r['scoped_status'],'unresolved')

    def test_dpa_annex_change_and_ccpa_selection(self):
        c={'version':'1.1','ccpa_service_provider_selected':True}
        f=dict(annex_update_notice_given=False,independent_reuse=True,ccpa_permitted_law_exception=False)
        self.assertEqual(self.status('dpa11',c,f,'feature-annex-change'),'live_after_notice')
        self.assertEqual(self.status('dpa11',c,f,'ccpa-service-provider-reuse'),'off')

    def test_bonterms_default_training_and_exact_exceptions(self):
        f=dict(generative_feature=True,solely_customer_training=True,
               training_deidentified_all_persons=True,training_aggregated_across_customers=True)
        for exception,expect in [('none','off'),('customer_only','live_with_conditions'),('deidentified_aggregated','live_with_conditions')]:
            self.assertEqual(self.status('bonterms2',{'version':'2.0','training_exception':exception},f,'model-training'),expect)
        f['solely_customer_training']=False
        self.assertEqual(self.status('bonterms2',{'version':'2.0','training_exception':'customer_only'},f,'model-training'),'off')

    def test_bonterms_both_anonymity_and_aggregation(self):
        c={'version':'2.0','training_exception':'deidentified_aggregated'}
        f=dict(generative_feature=True,training_deidentified_all_persons=True)
        self.assertEqual(self.status('bonterms2',c,f,'model-training'),'unresolved')
        f['training_aggregated_across_customers']=False
        self.assertEqual(self.status('bonterms2',c,f,'model-training'),'off')

    def test_bonterms_monitoring_is_not_general_improvement(self):
        f=dict(generative_feature=True,monitoring_purpose='general_product_improvement',monitoring_days=2,
               monitoring_data_separated=True,monitoring_need_to_know=True,automatic_deletion=True)
        self.assertEqual(self.status('bonterms2',{'version':'2.0'},f,'operational-monitoring'),'off')
        f['monitoring_purpose']='abuse'
        self.assertEqual(self.status('bonterms2',{'version':'2.0'},f,'operational-monitoring'),'live_with_conditions')

    def test_bonterms_retention_boundary_and_investigation_exception(self):
        c={'version':'2.0'}
        f=dict(generative_feature=True,monitoring_purpose='abuse',monitoring_days=31,
               monitoring_data_separated=True,monitoring_need_to_know=True,automatic_deletion=True)
        self.assertEqual(self.status('bonterms2',c,f,'operational-monitoring'),'off')
        f['ongoing_specific_investigation_or_legal_exception']=True
        self.assertEqual(self.status('bonterms2',c,f,'operational-monitoring'),'unresolved')
        c['retention_days']=40
        self.assertEqual(self.status('bonterms2',c,f,'operational-monitoring'),'live_with_conditions')

    def test_bonterms_retrieval_tenant_boundary(self):
        f=dict(generative_feature=True,retrieval_per_customer=True,no_cross_customer_context=False)
        self.assertEqual(self.status('bonterms2',{'version':'2.0'},f,'tenant-retrieval'),'off')

    def test_bonterms_no_default_thirty_day_new_feature_clock(self):
        c={'version':'2.0'}
        f=dict(generative_feature=True,new_feature_prior_notice=True,new_feature_admin_disable=True,
               core_non_ai_preserved=True,feature_notice_days=10)
        self.assertEqual(self.status('bonterms2',c,f,'new-feature-default-enable'),'live_with_conditions')
        c['minimum_feature_notice_days']=30
        self.assertEqual(self.status('bonterms2',c,f,'new-feature-default-enable'),'live_after_notice')

    def test_bonterms_non_generative_scope(self):
        r=s.assess('bonterms2',{'version':'2.0'},{'generative_feature':False})
        self.assertTrue(all(x['scoped_status']=='unresolved' for x in r))

    def test_custom_text_preserves_population_and_unknowns(self):
        for kind,c in [('csa3',{'version':'3.0'}),('dpa11',{'version':'1.1'}),('bonterms2',{'version':'2.0'})]:
            baseline=s.assess(kind,c,{})
            changed=s.assess(kind,dict(c,custom_text='Private amendment.'),{})
            self.assertEqual({x['operation_id'] for x in baseline},{x['operation_id'] for x in changed})
            self.assertTrue(all(x['scoped_status']=='unresolved' for x in changed))

    def test_unknown_choice_and_false_boolean(self):
        for kind,c in [('csa3',{'version':'3.0','dpa_selected':1}),('dpa11',{'version':'1.1','customer_role':'seller'}),
                        ('bonterms2',{'version':'2.0','unseen_term':True}),('bonterms2',{'version':'2.0','retention_days':True})]:
            with self.assertRaises(ValueError):
                s.assess(kind,c,{})

    def test_notice_clock_cannot_erase_missing_administrator_control(self):
        c={'version':'2.0','minimum_feature_notice_days':30}
        f=dict(generative_feature=True,new_feature_prior_notice=True,new_feature_admin_disable=False,
               core_non_ai_preserved=True,feature_notice_days=10)
        self.assertEqual(self.status('bonterms2',c,f,'new-feature-default-enable'),'off')
        f['new_feature_admin_disable']=True
        self.assertEqual(self.status('bonterms2',c,f,'new-feature-default-enable'),'live_after_notice')

    def test_notice_gap_is_distinct_from_provider_flowdown_violation(self):
        c={'version':'2.0','minimum_provider_notice_days':30}
        f=dict(generative_feature=True,model_provider_list_current=True,provider_notice_before_change=False,
               model_provider_flowdown=False,provider_notice_days=10)
        self.assertEqual(self.status('bonterms2',c,f,'model-provider-change'),'off')
        f['model_provider_flowdown']=True
        self.assertEqual(self.status('bonterms2',c,f,'model-provider-change'),'live_after_notice')

    def test_investigation_does_not_waive_separation(self):
        f=dict(generative_feature=True,monitoring_purpose='abuse',monitoring_days=31,
               monitoring_data_separated=False,monitoring_need_to_know=True,automatic_deletion=True,
               ongoing_specific_investigation_or_legal_exception=True)
        self.assertEqual(self.status('bonterms2',{'version':'2.0'},f,'operational-monitoring'),'off')

    def test_dpa_omission_rule_needs_exact_scoped_interpretation(self):
        c={'version':'1.1','omitted_variables':['Approved Subprocessors']}
        rows=s.assess('dpa11',c,{'subprocessor_approval_state':'approved','subprocessor_written_flowdown':True})
        self.assertEqual(len(rows),6)
        self.assertTrue(all(x['scoped_status']=='unresolved' for x in rows))

    def test_prior_approval_does_not_erase_a_new_change_notice(self):
        f=dict(subprocessor_approval_state='approved',subprocessor_written_flowdown=True,new_subprocessor_change=True,
               notice_business_days=3)
        self.assertEqual(self.status('dpa11',{'version':'1.1'},f,'subprocessor-content-transfer'),'live_after_notice')

    def test_ccpa_law_exception_remains_an_evidence_dependency(self):
        c={'version':'1.1','ccpa_service_provider_selected':True}
        f=dict(independent_reuse=True,ccpa_permitted_law_exception=True)
        self.assertEqual(self.status('dpa11',c,f,'ccpa-service-provider-reuse'),'unresolved')

    def test_provider_and_customer_training_are_distinct_actors(self):
        c={'version':'2.0','training_exception':'customer_only'}
        f=dict(generative_feature=True,solely_customer_training=True,trains_competing_third_party_model=True)
        self.assertEqual(self.status('bonterms2',c,f,'model-training'),'live_with_conditions')
        self.assertEqual(self.status('bonterms2',c,f,'customer-competing-model-training'),'off')
        self.assertNotEqual(s.actor('bonterms2','model-training',c),s.actor('bonterms2','customer-competing-model-training',c))

    def test_human_review_does_not_prove_legal_compliance(self):
        c={'version':'2.0'}
        f=dict(generative_feature=True,appropriate_human_review=True)
        self.assertEqual(self.status('bonterms2',c,f,'significant-automated-decision'),'unresolved')

    def test_provider_approval_is_separate_from_human_authorship(self):
        c={'version':'2.0'}
        f=dict(generative_feature=True,falsely_claims_human=False,claims_provider_approval=True)
        self.assertEqual(self.status('bonterms2',c,f,'human-attribution'),'live_with_conditions')
        self.assertEqual(self.status('bonterms2',c,f,'provider-approval-attribution'),'off')
        f['claims_provider_approval']=None
        self.assertEqual(self.status('bonterms2',c,f,'provider-approval-attribution'),'unresolved')
        f['claims_provider_approval']=False
        self.assertEqual(self.status('bonterms2',c,f,'provider-approval-attribution'),'live_with_conditions')

    def test_fact_types_and_clocks_are_not_truthy_strings(self):
        for facts in [dict(gdpr_personal_data='false'),dict(notice_business_days=True),
                      dict(notice_calendar_days=-1),dict(subprocessor_approval_state='probably'),
                      dict(usage_data_aggregated=1)]:
            with self.subTest(facts=facts),self.assertRaises(ValueError):
                s.assess('csa3',{'version':'3.0'},facts)

if __name__=='__main__':
    unittest.main()
