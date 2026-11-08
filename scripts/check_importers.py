"""Import boundary tests and actual CLI/MCP/SDK consumers, with public fixtures.

The fixture metadata follows the published Ironclad schema. It is not a customer
export. The actual public contract bytes and retained model work remain exact.
"""
import asyncio
from copy import deepcopy
import csv
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from kyma_local.agent_workflow import prepare_contract_job, read_contract_source
from kyma_local.importers import import_contract_export, read_import_context

KIT = Path(__file__).resolve().parent.parent


class ImportBoundaries(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='kyma-import-boundary-')
        self.root = Path(self.temp.name)
        self.files = self.root / 'originals'
        self.files.mkdir()
        self.data = b'Original signed contract fixture. No training permission is inferred.\n'
        (self.files / 'msa.txt').write_bytes(self.data)
        self.record = {'id': 'record-1', 'ironcladId': 'IC-1', 'type': 'msa',
                       'name': 'Fixture agreement', 'lastUpdated': '2026-11-05T00:00:00Z',
                       'properties': {}, 'links': [{'recordId': 'missing-parent'}],
                       'attachments': {'signedCopy': {'filename': 'msa.txt', 'href': 'https://example.invalid/original',
                                       'fileHash': sha256(self.data).hexdigest(), 'hashAlgorithm': 'sha256'},
                                       'dpa': {'filename': 'dpa.pdf', 'href': 'https://example.invalid/dpa'}}}
        self.page = {'page': 0, 'pageSize': 20, 'count': 2, 'list': [self.record]}
        self.mapping = {'schema': 'kyma-contract-import-map/v1',
                        'records': {'record-1': {'customer_id': 'fixture-client', 'attachments': {'signedCopy': 'msa.txt'}}}}
        self.export = self.root / 'records.json'
        self.map = self.root / 'mapping.json'
        self.out = self.root / 'imported'

    def tearDown(self):
        self.temp.cleanup()

    def run_import(self):
        self.export.write_text(json.dumps(self.page))
        self.map.write_text(json.dumps(self.mapping))
        return import_contract_export('ironclad-json', str(self.export), str(self.files), str(self.out), str(self.map))

    def test_originals_missing_coverage_and_agent_context(self):
        got = self.run_import()
        self.assertEqual(got['missing_attachments'], 1)
        self.assertFalse(got['coverage']['all_query_records_acquired'])
        contracts = Path(got['contracts'])
        context = read_import_context(contracts)
        self.assertEqual(context['customers']['fixture-client']['records'][0]['metadata'], self.record)
        self.assertEqual((contracts / '.import/export.original').read_bytes(), self.export.read_bytes())
        job = prepare_contract_job(str(contracts), str(KIT / 'sample/feature.json'), str(self.root / 'work'))
        self.assertEqual(len(job['sources']), 1)
        self.assertTrue(job['source_groups'][0]['acquisition_warnings'])
        self.assertEqual(job['contract_import'], context)
        source = read_contract_source(job['work'], job['sources'][0]['id'])
        self.assertEqual(source['text'].encode(), self.data)
        self.assertEqual(source['metadata']['original_sha256'], sha256(self.data).hexdigest())

    def test_hash_mismatch_before_output(self):
        self.record['attachments']['signedCopy']['fileHash'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'SHA-256 differs'):
            self.run_import()
        self.assertFalse(self.out.exists())

    def test_path_escape_before_output(self):
        self.mapping['records']['record-1']['attachments']['signedCopy'] = '../secret.txt'
        with self.assertRaisesRegex(ValueError, 'inside files_root'):
            self.run_import()
        self.assertFalse(self.out.exists())

    def test_symlink_rejected(self):
        (self.files / 'linked.txt').symlink_to(self.files / 'msa.txt')
        self.mapping['records']['record-1']['attachments']['signedCopy'] = 'linked.txt'
        with self.assertRaisesRegex(ValueError, 'symlinks'):
            self.run_import()

    def test_invalid_mapping_type_rejected_before_output(self):
        self.mapping['records']['record-1']['attachments']['signedCopy'] = False
        with self.assertRaisesRegex(ValueError, 'relative path strings'):
            self.run_import()
        self.assertFalse(self.out.exists())

    def test_duplicate_record_rejected(self):
        self.page['list'].append(deepcopy(self.record))
        with self.assertRaisesRegex(ValueError, 'Duplicate Ironclad record'):
            self.run_import()

    def test_extra_mapping_rejected(self):
        self.mapping['records']['other'] = {'customer_id': 'other', 'attachments': {}}
        with self.assertRaisesRegex(ValueError, 'exactly match'):
            self.run_import()

    def test_duplicate_json_key_rejected(self):
        self.export.write_text('{"page":0,"page":1}')
        self.map.write_text(json.dumps(self.mapping))
        with self.assertRaisesRegex(ValueError, 'Duplicate JSON key'):
            import_contract_export('ironclad-json', str(self.export), str(self.files), str(self.out), str(self.map))

    def test_existing_output_preserved(self):
        self.out.mkdir()
        (self.out / 'keep').write_text('Previous work')
        with self.assertRaisesRegex(ValueError, 'Existing work remains intact'):
            self.run_import()
        self.assertEqual((self.out / 'keep').read_text(), 'Previous work')

    def test_changed_attachment_rejected_by_real_preparation(self):
        got = self.run_import()
        contracts = Path(got['contracts'])
        context = read_import_context(contracts)
        (contracts / context['documents'][0]['path']).write_text('Changed source')
        with self.assertRaisesRegex(ValueError, 'Imported attachment changed'):
            prepare_contract_job(str(contracts), str(KIT / 'sample/feature.json'), str(self.root / 'work'))

    def test_changed_export_rejected(self):
        contracts = Path(self.run_import()['contracts'])
        (contracts / '.import/export.original').write_text('{}')
        with self.assertRaisesRegex(ValueError, 'Imported original changed'):
            read_import_context(contracts)

    def test_metadata_not_independent_of_original(self):
        contracts = Path(self.run_import()['contracts'])
        marker = contracts / '_import.json'
        value = json.loads(marker.read_text())
        value['customers']['fixture-client']['records'][0]['metadata']['name'] = 'Invented metadata'
        marker.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, 'differs from the preserved'):
            read_import_context(contracts)

    def test_interrupted_import_rejected(self):
        contracts = self.root / 'interrupted'
        (contracts / '.import').mkdir(parents=True)
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            read_import_context(contracts)

    def test_csv_quoted_unicode_and_metadata(self):
        table = self.root / 'review.csv'
        with table.open('w', encoding='utf-8-sig', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['document_id', 'customer_id', 'file', 'Reviewer note'])
            writer.writerow(['row-1', 'fixture-client', 'msa.txt', 'Élodie, says\nreview the DPA'])
            writer.writerow(['row-2', 'fixture-client', '', '=HYPERLINK("not executed")'])
        got = import_contract_export('review-table-csv', str(table), str(self.files), str(self.out))
        context = read_import_context(Path(got['contracts']))
        self.assertEqual(got['missing_attachments'], 1)
        self.assertEqual(context['customers']['fixture-client']['records'][0]['metadata']['columns']['Reviewer note'], 'Élodie, says\nreview the DPA')

    def test_metadata_cannot_duplicate_or_move_record(self):
        contracts = Path(self.run_import()['contracts'])
        marker = contracts / '_import.json'
        original = json.loads(marker.read_text())
        duplicate = deepcopy(original)
        duplicate['customers']['fixture-client']['records'].append(deepcopy(duplicate['customers']['fixture-client']['records'][0]))
        moved = deepcopy(original)
        moved['customers']['other-client'] = moved['customers'].pop('fixture-client')
        for value in [duplicate, moved]:
            marker.write_text(json.dumps(value))
            with self.assertRaisesRegex(ValueError, 'differs from the preserved'):
                read_import_context(contracts)

    def test_csv_ambiguous_headers_and_short_row(self):
        table = self.root / 'bad.csv'
        for text in ['document_id,customer_id,file,file\na,b,c,d\n', 'document_id,customer_id,file\na,b\n']:
            table.write_text(text)
            with self.assertRaises(ValueError):
                import_contract_export('review-table-csv', str(table), str(self.files), str(self.out))
            self.assertFalse(self.out.exists())

    def test_missing_index_cannot_hide_unacquired_dpa(self):
        contracts = Path(self.run_import()['contracts'])
        marker = contracts / '_import.json'
        value = json.loads(marker.read_text())
        value['customers']['fixture-client']['missing'] = []
        marker.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, 'Import indexes differ'):
            prepare_contract_job(str(contracts), str(KIT / 'sample/feature.json'), str(self.root / 'work'))

    def test_source_provenance_cannot_change_record_or_original(self):
        contracts = Path(self.run_import()['contracts'])
        index = contracts / 'fixture-client/_sources.json'
        rows = json.loads(index.read_text())
        rows[0]['record_id'] = 'unrelated-record'
        rows[0]['original_relative_path'] = 'unrelated-company/secret.txt'
        index.write_text(json.dumps(rows))
        with self.assertRaisesRegex(ValueError, 'Import provenance differs'):
            prepare_contract_job(str(contracts), str(KIT / 'sample/feature.json'), str(self.root / 'work'))

    def test_document_index_cannot_drop_original(self):
        contracts = Path(self.run_import()['contracts'])
        marker = contracts / '_import.json'
        value = json.loads(marker.read_text());value['documents'] = []
        marker.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, 'Import indexes differ'):
            read_import_context(contracts)

    def test_extra_original_cannot_appear_without_import(self):
        contracts = Path(self.run_import()['contracts'])
        (contracts / 'fixture-client/unbound.txt').write_text('Unbound original')
        with self.assertRaisesRegex(ValueError, 'attachment population differs'):
            read_import_context(contracts)

    def test_casefold_customer_alias_rejected_before_output(self):
        table = self.root / 'ambiguous.csv'
        table.write_text('document_id,customer_id,file\none,Acme,msa.txt\ntwo,acme,msa.txt\n')
        with self.assertRaisesRegex(ValueError, 'letter case'):
            import_contract_export('review-table-csv', str(table), str(self.files), str(self.out))
        self.assertFalse(self.out.exists())

    def test_unsupported_original_retained(self):
        (self.files / 'original.doc').write_bytes(b'Unsupported binary fixture')
        self.record['attachments']['legacy'] = {'filename': 'original.doc', 'href': 'https://example.invalid/legacy'}
        self.mapping['records']['record-1']['attachments']['legacy'] = 'original.doc'
        got = self.run_import()
        self.assertEqual(got['unsupported_attachments'], 1)
        job = prepare_contract_job(got['contracts'], str(KIT / 'sample/feature.json'), str(self.root / 'work'))
        self.assertEqual(len(job['source_groups'][0]['unsupported_files']), 1)


async def protocol_consumer():
    from mcp import Client, StdioServerParameters
    with tempfile.TemporaryDirectory(prefix='kyma-import-protocol-') as tmp:
        root = Path(tmp)
        records, assignments = [], {}
        for folder in sorted((KIT / 'sample/contracts').iterdir()):
            if not folder.is_dir():
                continue
            identity = folder.name
            attachments, paths = {}, {}
            for number, path in enumerate(sorted(folder.glob('*.html'))):
                key = 'original' + str(number)
                attachments[key] = {'filename': path.name, 'href': 'https://example.invalid/fixture/' + key,
                                    'fileHash': sha256(path.read_bytes()).hexdigest(), 'hashAlgorithm': 'sha256'}
                paths[key] = path.relative_to(KIT / 'sample/contracts').as_posix()
            records.append({'id': identity, 'ironcladId': 'IC-fixture-' + identity,
                            'type': 'publicContractFixture', 'name': identity,
                            'lastUpdated': '2026-11-05T00:00:00Z', 'properties': {}, 'links': [], 'attachments': attachments})
            assignments[identity] = {'customer_id': identity, 'attachments': paths}
        page = {'page': 0, 'pageSize': 20, 'count': len(records), 'list': records}
        export, mapping = root / 'records.json', root / 'mapping.json'
        export.write_text(json.dumps(page));mapping.write_text(json.dumps({'schema': 'kyma-contract-import-map/v1', 'records': assignments}))
        server = StdioServerParameters(command=sys.executable, args=['-m', 'kyma_local.mcp_server'],
                                       env={'PYTHONPATH': str(KIT / 'src')})
        async with Client(server, mode='2026-07-28', read_timeout_seconds=90) as client:
            async def call(name, arguments):
                result = await client.call_tool(name, arguments)
                assert not result.is_error, result.content
                return result.structured_content
            tools = await client.list_tools()
            assert 'import_contract_export' in {tool.name for tool in tools.tools}
            imported = await call('import_contract_export', {'format': 'ironclad-json', 'export_path': str(export),
                                  'files_root': str(KIT / 'sample/contracts'), 'mapping_path': str(mapping), 'out': str(root / 'imported')})
            assert imported['documents_copied'] == 4 and imported['missing_attachments'] == 0
            job = await call('prepare_contract_job', {'contracts': imported['contracts'], 'feature': str(KIT / 'sample/feature.json'), 'out': str(root / 'work')})
            assert len(job['sources']) == 4 and len(job['source_groups']) == 2
            names = {}
            for source in job['sources']:
                original_path = source['provenance']['original_relative_path']
                customer, filename = original_path.split('/')
                names[customer + ':' + filename] = source['id']
                acquired = await call('read_contract_source', {'work': job['work'], 'document_id': source['id']})
                assert sha256(acquired['text'].encode()).hexdigest() == source['text_sha256']
            bundle = json.loads((KIT / 'runs/fresh-user-run/model-decisions.json').read_text())
            for row in bundle['evidence']:
                row['document_id'] = names[row['document_id']]
            for row in bundle['precedence']:
                for key in ['higher_document_id', 'lower_document_id']:
                    row[key] = names[row[key]]
            accepted = await call('submit_contract_assessment', {'work': job['work'], 'bundle': bundle})
            read = await call('read_contract_result', {'work': job['work']})
            assert read['stored_result']['bundle'] == bundle and read['receiver_rows'] == 1
            assert len(read['fresh_sdk_evaluations']) == 18
            identical = await call('import_contract_export', {'format': 'ironclad-json', 'export_path': str(export),
                                   'files_root': str(KIT / 'sample/contracts'), 'mapping_path': str(mapping), 'out': str(root / 'identical')})
            no_change = await call('prepare_revision_job', {'before': job['work'], 'contracts': identical['contracts'],
                                   'feature': str(KIT / 'sample/feature.json'), 'out': str(root / 'unchanged')})
            assert no_change['status'] == 'unchanged'
            # Same contract bytes, changed query coverage. The revision must expose
            # the changed import context even though no document text changed.
            page['count'] += 1
            export.write_text(json.dumps(page))
            second = await call('import_contract_export', {'format': 'ironclad-json', 'export_path': str(export),
                                'files_root': str(KIT / 'sample/contracts'), 'mapping_path': str(mapping), 'out': str(root / 'second')})
            revision = await call('prepare_revision_job', {'before': job['work'], 'contracts': second['contracts'],
                                  'feature': str(KIT / 'sample/feature.json'), 'out': str(root / 'revision')})
            changes = revision['revision_context']['input_changes']
            assert len(changes) == 1 and changes[0]['id'] == 'I1' and changes[0]['kind'] == 'contract_import_context'
        table = root / 'review.csv'
        with table.open('w', newline='') as f:
            writer = csv.writer(f);writer.writerow(['document_id', 'customer_id', 'file'])
            writer.writerow(['public-1', 'c3-bhge', next(iter(assignments['c3-bhge']['attachments'].values()))])
        result = subprocess.run([sys.executable, '-m', 'kyma_local', 'import', '--format', 'review-table-csv',
                                 '--export', str(table), '--files-root', str(KIT / 'sample/contracts'), '--out', str(root / 'cli')], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout)['documents_copied'] == 1
        return {'actual_modern_stdio_import_prepare_source_submit_readback': True,
                'original_public_documents': 4, 'retained_actual_model_decisions': accepted['model_decisions'],
                'actual_openfeature_evaluations': 18, 'sqlite_rows': 1,
                'metadata_only_revision_detected': True, 'identical_reimport_ignores_new_capture_clock': True,
                'actual_cli_csv_import': True,
                'new_model_invocation': False, 'customer_export_or_adoption_claim': False}


if __name__ == '__main__':
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(ImportBoundaries)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise SystemExit(1)
    protocol = asyncio.run(protocol_consumer())
    report = {'boundary_tests': result.testsRun, 'all_passed': True, 'consumer': protocol,
              'scope': 'Synthetic vendor metadata and user CSV fixtures with actual public contract bytes. No outside customer export or new model interpretation.'}
    path = KIT / 'evidence/importer-consumer.json'
    path.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
