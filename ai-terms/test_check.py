"""Exercise editable files, detached custody and failed imports at the real file boundary."""
from copy import deepcopy
import csv
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest

import check as reader

EXAMPLES = Path(__file__).resolve().parent / 'examples'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


class TermsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='kyma-ai-terms-test-')
        self.root = Path(self.temporary.name)
        self.file = self.root / 'example.json'
        self.evidence = self.root / 'sources.json'
        self.out = self.root / 'received'
        self.original = json.loads((EXAMPLES / 'intercom.ai-terms.json').read_bytes())
        self.original['source_pins']['path'] = self.evidence.name
        shutil.copyfile(EXAMPLES / 'intercom.sources.json', self.evidence)
        self.save(self.original)

    def tearDown(self):
        self.temporary.cleanup()

    def save(self, value):
        self.file.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')

    def save_evidence(self, value):
        self.evidence.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
        self.original['source_pins']['sha256'] = sha(self.evidence.read_bytes())
        self.save(self.original)

    def reject(self, signature):
        with self.assertRaisesRegex(ValueError, signature):
            reader.export(self.file, self.out)
        self.assertFalse(self.out.exists())

    def test_example_and_detached_consumer_preserve_every_field(self):
        receipt = reader.export(self.file, self.out)
        self.assertEqual((receipt['index_fields'], receipt['decision_rows'], receipt['source_spans']), (7, 21, 67))
        self.assertEqual(self.file.read_bytes(), (self.out / 'ai-terms.json').read_bytes())
        self.assertEqual(self.evidence.read_bytes(), (self.out / 'sources.json').read_bytes())
        self.file.unlink()
        self.evidence.unlink()
        self.assertEqual(reader.check(self.out / 'ai-terms.json')[0], self.original)
        with (self.out / 'index-fields.csv').open() as stream:
            self.assertEqual(len(list(csv.DictReader(stream))), 7)
        with (self.out / 'decisions.csv').open() as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual([row['id'] for row in rows], [row['id'] for row in self.original['decision_case']['rows']])
        self.assertFalse(receipt['full_source_bytes_verified'])
        self.assertFalse(receipt['legal_clearance'])

    def test_reviewed_anchor_and_useful_edit_are_separate(self):
        anchor = sha(self.file.read_bytes())
        self.assertTrue(reader.check(self.file, anchor)[2]['reviewed_digest_matched'])
        self.original['index_fields'][0]['statement'] += ' Revised for a local review.'
        self.save(self.original)
        self.assertFalse(reader.check(self.file)[2]['reviewed_digest_matched'])
        with self.assertRaisesRegex(ValueError, 'reviewed_file_changed'):
            reader.check(self.file, anchor)

    def fictional_vendor(self):
        raw = b'<p>Example Labs permits the fictional sample feature.</p>'
        (self.root / 'original.html').write_bytes(raw)
        source = {'id': 'fictional-source', 'url': 'https://example.invalid/terms', 'observed_at_utc': '2026-01-01T00:00:00Z',
                  'bytes': len(raw), 'sha256': sha(raw), 'body_path': 'original.html'}
        span = {'id': 'fictional-span', 'source_id': source['id'], 'source_sha256': sha(raw),
                'html_byte_start': 0, 'html_byte_end_exclusive': len(raw), 'html_span_sha256': sha(raw),
                'normalized_text_sha256': sha(b'Example Labs permits the fictional sample feature.')}
        relation = {'statement': 'A fictional test relation.', 'source_span_ids': [span['id']], 'nature': 'synthetic_fixture'}
        row = {'id': 'one', 'title': 'Fictional sample', 'public_decision': 'FIXTURE_ONLY',
               **{key: deepcopy(relation) for key in reader.RELATIONS}, 'uncertainty_queue_ids': []}
        self.original.update(company='Example Labs', domain='example.invalid', status='SYNTHETIC_TEST_FIXTURE',
                             source_document_ids=[source['id']], decision_case={
                                 'rows': [row], 'uncertainty_queue': [], 'customer_specific_clearance': False})
        for item in self.original['index_fields']:
            item.update(value='fixture_only', statement='A fictional field.', source_span_ids=[span['id']], uncertainty_queue_ids=[])
        self.save_evidence({'schema': 'kyma-ai-terms-evidence/v1', 'sources': [source], 'spans': [span]})

    def test_second_vendor_single_row_and_original_bytes(self):
        self.fictional_vendor()
        result = reader.export(self.file, self.out, source_root=self.root)
        self.assertEqual((result['company'], result['decision_rows']), ('Example Labs', 1))
        self.assertTrue(result['full_source_bytes_verified'])

    def test_changed_whole_source_fails_before_output(self):
        self.fictional_vendor()
        (self.root / 'original.html').write_bytes(b'Changed original source.')
        with self.assertRaisesRegex(ValueError, 'full_source_changed'):
            reader.export(self.file, self.out, source_root=self.root)
        self.assertFalse(self.out.exists())

    def test_wrong_span_hash_fails_with_original_bytes(self):
        self.fictional_vendor()
        evidence = json.loads(self.evidence.read_bytes())
        evidence['spans'][0]['html_span_sha256'] = '0' * 64
        self.save_evidence(evidence)
        with self.assertRaisesRegex(ValueError, 'source_span_changed'):
            reader.check(self.file, source_root=self.root)

    def test_evidence_tamper_without_new_pin_fails(self):
        self.evidence.write_bytes(self.evidence.read_bytes() + b' ')
        self.reject('source_evidence_changed')

    def test_missing_relation_source_is_not_a_complete_decision(self):
        self.original['decision_case']['rows'][0]['condition']['source_span_ids'] = []
        self.save(self.original)
        self.reject('condition:source_binding_required')

    def test_missing_reference_is_not_a_verified_citation(self):
        self.original['index_fields'][0]['source_span_ids'] = ['missing-source']
        self.save(self.original)
        self.reject('unresolved_source_span_ids')

    def test_missing_uncertainty_is_not_a_resolved_question(self):
        self.original['index_fields'][0]['uncertainty_queue_ids'] = ['missing-unknown']
        self.save(self.original)
        self.reject('unresolved_uncertainty_queue_ids')

    def test_string_false_does_not_become_boolean_false(self):
        self.original['vendor_adopted'] = 'false'
        self.save(self.original)
        self.reject('vendor_adopted:boolean_required')

    def test_vendor_declaration_does_not_become_verified_adoption(self):
        self.original['vendor_adopted'] = True
        self.original['vendor_authored'] = True
        self.save(self.original)
        receipt = reader.check(self.file)[2]
        self.assertTrue(receipt['declarations']['vendor_adopted'])
        self.assertFalse(receipt['outside_adoption_verified'])
        self.assertFalse(receipt['vendor_authorship_verified'])

    def test_duplicate_index_field_cannot_mask_missing_field(self):
        self.original['index_fields'][-1] = self.original['index_fields'][0]
        self.save(self.original)
        self.reject('index_field_population_changed')

    def test_duplicate_decision_id_fails(self):
        self.original['decision_case']['rows'].append(deepcopy(self.original['decision_case']['rows'][0]))
        self.save(self.original)
        self.reject('decisions:duplicate_id')

    def test_duplicate_json_key_cannot_hide_a_declaration(self):
        raw = self.file.read_text()
        self.file.write_text(raw.replace('"vendor_adopted": false,', '"vendor_adopted": true, "vendor_adopted": false,'))
        self.reject('duplicate_json_key')

    def test_traversal_is_not_an_evidence_source(self):
        self.original['source_pins']['path'] = '../outside.json'
        self.save(self.original)
        self.reject('unsafe_source_path')

    def test_evidence_path_cannot_overwrite_export_table(self):
        shutil.copyfile(self.evidence, self.root / 'decisions.csv')
        self.original['source_pins']['path'] = 'decisions.csv'
        self.save(self.original)
        self.reject('reserved_evidence_output_path')

    def test_existing_output_remains_exact(self):
        self.out.mkdir()
        marker = self.out / 'my-work.txt'
        marker.write_text('Retain this work.')
        with self.assertRaisesRegex(ValueError, 'new_output_directory_required'):
            reader.export(self.file, self.out)
        self.assertEqual(marker.read_text(), 'Retain this work.')
        self.assertEqual(list(self.out.iterdir()), [marker])

    def test_malformed_container_has_a_useful_error(self):
        for broken, signature in [([], 'document_object_required'),
                                  ({**self.original, 'decision_case': []}, 'decision_case_object_required'),
                                  ({**self.original, 'boundaries': 'Not an array'}, 'boundaries_required')]:
            self.save(broken)
            self.reject(signature)


if __name__ == '__main__':
    unittest.main()
