"""Check revision JSON identities, the actual SQLite receiver, and replay.

This script uses synthetic local inputs and invokes no model or remote service.
"""
import argparse
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

parser = argparse.ArgumentParser()
parser.add_argument('--kit', type=Path, default=Path(__file__).resolve().parents[1])
args, remaining = parser.parse_known_args()
sys.argv = [sys.argv[0], *remaining]
sys.dont_write_bytecode = True
sys.path.insert(0, str(args.kit.resolve() / 'src'))
from kyma_local import watch
from kyma_local.tool import canonical


def put(root, name, value):
    (root / name).write_text(json.dumps(value, ensure_ascii=False) + '\n')


def fixture(root, kind='status'):
    text = 'Synthetic source. Supplier must not use the customer name.\n'
    (root / 'source.txt').write_text(text)
    evidence = {'id':'E1','document_id':'customer:source.txt','section':'Only clause','page':None,
                'quote':'Supplier must not use the customer name.','supports':'The proposed source decision.'}
    decision = {'id':'D1','customer_id':'customer','operation_id':'name','status':'live_now',
                'actor':'Supplier','data':'Customer name','purpose':'Public identification',
                'model':'Not applicable','feature':'Synthetic test','conditions':[],
                'rationale':'Synthetic proposed decision.','evidence_ids':['E1'],'unknown_ids':[]}
    before = {'assessment_type':'proposed_source_bound_decisions','feature_id':'example',
              'summary':'Synthetic test only.','evidence':[evidence],'precedence':[],
              'decisions':[decision],'unknowns':[],
              'controls':[{'decision_id':'D1','customer_id':'customer','operation_id':'name',
                           'proposed_eligible':True,'required_facts':{},'reason':'Synthetic test.'}],
              'engineering_outputs':[{'id':'ENG1','title':'Preserve the source','body':'Retain the exact clause.',
                                      'acceptance_criteria':'Source hashes and receiver are exact.','decision_ids':['D1']}],
              'notices_or_consent_drafts':[]}
    after = deepcopy(before)
    if kind == 'status':
        after['decisions'][0]['status'] = 'off'
        after['controls'][0]['proposed_eligible'] = False
    elif kind == 'conditions':
        after['decisions'][0]['conditions'] = ['An explicit test condition.']
        after['controls'][0]['required_facts'] = {'test_fact':True}
    elif kind == 'draft':
        before['notices_or_consent_drafts'] = [{'customer_id':'customer','type':'notice','draft':'Prior draft.'}]
        after['notices_or_consent_drafts'] = [{'customer_id':'customer','type':'notice','draft':'Revised draft.'}]
    elif kind == 'engineering':
        after['engineering_outputs'][0]['body'] = 'Retain the exact source version and clause.'
    after['revision_impacts'] = [{'id':'REV1','change_id':'C1','source_effect':'A synthetic source effect.',
                                 'engineering_action':'Verify the exact revision receiver.',
                                 'engagement_state':'not_applicable','evidence_ids':['E1'],'unknown_ids':[]}]
    fingerprint=sha256(text.encode()).hexdigest()
    put(root,'source-manifest.json',{'customers':[{'id':'customer','documents':[{
        'id':'customer:source.txt','customer_id':'customer','text_file':'source.txt',
        'text_sha256':fingerprint,'original_sha256':fingerprint,'units':[{'page':None,'text':text}],
        'provenance':{'source_class':'synthetic_regression_fixture'}}]}]})
    put(root,'feature.json',{'id':'example','operations':[{'id':'name'}]})
    put(root,'model-decisions.json',after)
    put(root,'revision-context.json',{'previous_actual_assessment':before,
                                    'previous_bundle_sha256':sha256(canonical(before)).hexdigest(),
                                    'input_changes':[{'id':'C1'}]})


def received(root):
    with sqlite3.connect('file:'+str(root/'local-results.sqlite3')+'?mode=ro',uri=True) as db:
        return db.execute('SELECT event_hash,body FROM revision_events').fetchall()


class RevisionReceiverTests(unittest.TestCase):
    def check_revision(self, kind):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);fixture(root,kind)
            event=watch.finalize(root)
            rows=received(root)
            self.assertEqual(len(rows),1)
            self.assertEqual(json.loads(rows[0][1]),event)
            self.assertEqual(json.loads(canonical(event)),event)

    def test_changed_status_and_control(self):self.check_revision('status')
    def test_changed_condition_without_status_change(self):self.check_revision('conditions')
    def test_changed_notice_draft(self):self.check_revision('draft')
    def test_engineering_string_identity_is_preserved(self):self.check_revision('engineering')
    def test_unchanged_decisions_keep_valid_receiver(self):self.check_revision('unchanged')

    def test_duplicate_finalize_preserves_one_exact_event(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);fixture(root)
            first=watch.finalize(root);second=watch.finalize(root)
            self.assertEqual(first,second)
            self.assertEqual(len(received(root)),1)

    def test_legacy_partial_result_recovers_exact_event_without_duplicate(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);fixture(root)
            actual_delta=watch.collection_delta
            def legacy_delta(*args,**kwargs):
                rows=actual_delta(*args,**kwargs)
                for row in rows:
                    if isinstance(row['identity'],list):row['identity']=tuple(row['identity'])
                return rows
            with patch.object(watch,'collection_delta',side_effect=legacy_delta):
                with self.assertRaises(AssertionError):watch.finalize(root)
            before=received(root)
            self.assertEqual(before,[])
            emitted=json.loads((root/'change-summary.json').read_text())
            repaired=watch.finalize(root)
            after=received(root)
            self.assertEqual(len(after),1)
            self.assertEqual(repaired['event_sha256'],emitted['event_sha256'])
            self.assertEqual(json.loads(after[0][1]),repaired)
            self.assertEqual(watch.finalize(root),repaired)
            self.assertEqual(received(root),after)


if __name__ == '__main__':unittest.main(verbosity=2)
