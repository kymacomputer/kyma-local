"""Offline imports of documented Ironclad records and explicit review-table CSVs.

Metadata identifies acquired sources. It cannot establish contractual precedence,
permission, or completeness. Attachment URLs are retained and never fetched.
"""
import csv
from datetime import datetime, timezone
from hashlib import sha256
import io
import json
from pathlib import Path
import re
from typing import Any

from .documents import SUPPORTED


IRONCLAD_SCHEMA = 'https://developer.ironcladapp.com/reference/list-all-records'
MAP_SCHEMA = 'kyma-contract-import-map/v1'


def _json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('Duplicate JSON key: ' + key)
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=pairs)


def import_identity(metadata):
    """A new local acquisition clock alone is not a changed contract input."""
    return {key: value for key, value in metadata.items() if key != 'acquired_at_utc'} if metadata else None


def read_import_context(root):
    """Verify the committed originals before an existing source consumer reads them."""
    marker = root / '_import.json'
    if not marker.exists():
        if (root / '.import').exists():
            raise ValueError('The contract import is incomplete. Use a new import output folder.')
        return None
    value = _object(_json(marker.read_text()), 'Import manifest')
    if value.get('schema') != 'kyma-contract-import/v1':
        raise ValueError('Unknown contract import schema.')
    originals = {}
    for label in ['export', 'mapping']:
        record = value.get(label)
        if record is None:
            continue
        data = _local_file(root, record['file']).read_bytes()
        if len(data) != record['bytes'] or sha256(data).hexdigest() != record['sha256']:
            raise ValueError('Imported original changed: ' + label)
        originals[label] = data
    if value['format'] == 'ironclad-json':
        records, coverage = _ironclad(originals['export'], _json(originals['mapping']))
    elif value['format'] == 'review-table-csv':
        records, coverage = _review_table(originals['export'])
    else:
        raise ValueError('Unknown contract import format.')
    expected = {record['id']: record for record in records}
    acquired = [record for group in value['customers'].values() for record in group['records']]
    actual = {record['id']: record for record in acquired}
    groups_match = all(record['customer_id'] == customer for customer, group in value['customers'].items()
                       for record in group['records'])
    if expected != actual or len(acquired) != len(expected) or not groups_match or coverage != value['coverage']:
        raise ValueError('Import metadata differs from the preserved original export.')
    for record in value['documents']:
        data = _local_file(root, record['path']).read_bytes()
        if len(data) != record['bytes'] or sha256(data).hexdigest() != record['sha256']:
            raise ValueError('Imported attachment changed. Import the new original into a new folder: ' + record['path'])
    copies, groups = _project(records, root, imported=True)
    documents = [{'path': name, 'sha256': sha256(data).hexdigest(), 'bytes': len(data)} for name, data, _ in copies]
    if groups != value['customers'] or documents != value['documents']:
        raise ValueError('Import indexes differ from the preserved export and acquired originals.')
    sources = {customer: [] for customer in groups}
    for destination, _, provenance in copies:
        sources[destination.split('/')[0]].append({**provenance, 'export_sha256': value['export']['sha256']})
    for customer, rows in sources.items():
        if _json((root / customer / '_sources.json').read_bytes()) != rows:
            raise ValueError('Import provenance differs from the preserved export: ' + customer)
        visible = {(path.relative_to(root)).as_posix() for path in (root / customer).rglob('*')
                   if path.is_file() and not path.name.startswith(('.', '_'))}
        if visible != {row['path'] for row in documents if row['path'].split('/')[0] == customer}:
            raise ValueError('Import attachment population differs from the preserved export: ' + customer)
    return value


def _object(value, label):
    if not isinstance(value, dict):
        raise ValueError(label + ' must be an object.')
    return value


def _text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(label + ' must be a nonempty string.')
    return value


def _customer(value):
    value = _text(value, 'customer_id')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*', value):
        raise ValueError('customer_id must be one visible folder name: ' + value)
    return value


def _local_file(root, relative):
    relative = Path(_text(relative, 'Local attachment path'))
    if relative.is_absolute() or '..' in relative.parts:
        raise ValueError('Attachment paths must stay inside files_root.')
    candidate = root / relative
    if not candidate.resolve().is_relative_to(root):
        raise ValueError('Attachment path resolves outside files_root.')
    for part in [candidate, *candidate.parents]:
        if part == root:
            break
        if part.is_symlink():
            raise ValueError('Attachment symlinks need an explicit local copy.')
    return candidate


def _ironclad(raw, mapping):
    data = _object(_json(raw), 'Ironclad response')
    rows = data.get('list')
    if not isinstance(rows, list):
        raise ValueError('Expected the documented Ironclad List All Records response with a list field.')
    for key in ['page', 'pageSize', 'count']:
        if type(data.get(key)) is not int or data[key] < 0:
            raise ValueError('Ironclad ' + key + ' must be a nonnegative integer.')
    if not 1 <= data['pageSize'] <= 100 or len(rows) > data['pageSize'] or len(rows) > data['count']:
        raise ValueError('Ironclad pagination counts are inconsistent.')
    mapping = _object(mapping, 'Ironclad mapping')
    if mapping.get('schema') != MAP_SCHEMA:
        raise ValueError('Use mapping schema ' + MAP_SCHEMA)
    assignments = _object(mapping.get('records'), 'mapping.records')
    seen, records = set(), []
    for row in rows:
        _object(row, 'Ironclad record')
        for key in ['id', 'ironcladId', 'type', 'name', 'lastUpdated']:
            _text(row.get(key), 'Ironclad record ' + key)
        identity = row['id']
        if identity in seen:
            raise ValueError('Duplicate Ironclad record id: ' + identity)
        seen.add(identity)
        _object(row.get('properties'), 'Ironclad properties')
        attachments = _object(row.get('attachments'), 'Ironclad attachments')
        if not isinstance(row.get('links'), list):
            raise ValueError('Ironclad links must be an array.')
        assignment = _object(assignments.get(identity), 'Mapping for record ' + identity)
        customer = _customer(assignment.get('customer_id'))
        paths = _object(assignment.get('attachments', {}), 'Attachment mapping')
        if any(path is not None and not isinstance(path, str) for path in paths.values()):
            raise ValueError('Local attachment mappings must be relative path strings or null.')
        if set(paths) - set(attachments):
            raise ValueError('Mapping contains an unknown attachment key for ' + identity)
        sources = []
        for key, attachment in attachments.items():
            _text(key, 'Attachment key')
            _object(attachment, 'Ironclad attachment')
            _text(attachment.get('filename'), 'Attachment filename')
            _text(attachment.get('href'), 'Attachment href')
            digest = attachment.get('fileHash')
            if digest is not None and (not isinstance(digest, str) or not re.fullmatch('[0-9a-fA-F]{64}', digest)):
                raise ValueError('Ironclad fileHash must be a SHA-256 hex digest.')
            if attachment.get('hashAlgorithm') not in {None, 'sha256'}:
                raise ValueError('Unsupported Ironclad attachment hashAlgorithm.')
            sources.append({'key': key, 'path': paths.get(key), 'metadata': attachment})
        records.append({'id': identity, 'customer_id': customer, 'metadata': row, 'attachments': sources})
    if set(assignments) != seen:
        raise ValueError('Mapping record ids must exactly match the imported page.')
    coverage = {key: data[key] for key in ['page', 'pageSize', 'count']}
    coverage['records_acquired'] = len(rows)
    coverage['all_query_records_acquired'] = data['page'] == 0 and len(rows) == data['count']
    coverage['scope'] = 'One acquired API page under its original user permissions and filters. Query coverage does not establish a complete legal set.'
    return records, coverage


def _review_table(raw):
    reader = csv.DictReader(io.StringIO(raw.decode('utf-8-sig'), newline=''), strict=True)
    headers = reader.fieldnames or []
    required = {'document_id', 'customer_id', 'file'}
    if len(set(headers)) != len(headers) or not required <= set(headers):
        raise ValueError('Review CSV needs unique headers: document_id,customer_id,file. Other columns remain intact.')
    records, seen = [], set()
    for number, row in enumerate(reader, 2):
        if None in row or any(value is None for value in row.values()):
            raise ValueError('Review CSV row has a different column count: ' + str(number))
        identity = _text(row['document_id'], 'document_id at row ' + str(number))
        if identity in seen:
            raise ValueError('Duplicate review document_id: ' + identity)
        seen.add(identity)
        records.append({'id': identity, 'customer_id': _customer(row['customer_id']),
                        'metadata': {'csv_record': number, 'columns': row},
                        'attachments': [{'key': 'document', 'path': row['file'] or None, 'metadata': {}}]})
    return records, {'records_acquired': len(records), 'scope': 'User-defined review-table CSV. This is not a claimed Harvey, Legora or LinkSquares native export schema.'}


def _project(records, root, imported=False):
    """Derive every consumer index from preserved identities and acquired bytes."""
    customers = {record['customer_id'] for record in records}
    if len({customer.casefold() for customer in customers}) != len(customers):
        raise ValueError('Customer ids differ only by letter case. Use distinct folder identities.')
    copies, groups, claimed_paths = [], {}, set()
    for record in records:
        group = groups.setdefault(record['customer_id'], {'records': [], 'missing': [], 'unsupported': []})
        group['records'].append(record)
        if not record['attachments']:
            group['missing'].append({'record_id': record['id'], 'reason': 'The record has no acquired attachment metadata.'})
        for attachment in record['attachments']:
            item = {'record_id': record['id'], 'attachment_key': attachment['key']}
            original = Path(_text(attachment['path'], 'Local attachment path')) if attachment['path'] else None
            if original is not None and (original.is_absolute() or '..' in original.parts):
                raise ValueError('Attachment paths must stay inside files_root.')
            identity = json.dumps([record['id'], attachment['key']], separators=(',', ':'))
            filename = sha256(identity.encode()).hexdigest()[:20] + (original.suffix.lower() if original else '')
            destination = record['customer_id'] + '/' + filename
            path = _local_file(root, destination if imported else original.as_posix()) if original else None
            if path is None or not path.is_file():
                group['missing'].append({**item, 'path': attachment['path'], 'reason': 'Local original was not supplied.'})
                continue
            data = path.read_bytes()
            digest = sha256(data).hexdigest()
            expected = attachment['metadata'].get('fileHash')
            if expected and digest != expected.lower():
                raise ValueError('Attachment SHA-256 differs from Ironclad metadata: ' + record['id'] + '/' + attachment['key'])
            if destination in claimed_paths:
                raise ValueError('Attachment destination collision.')
            claimed_paths.add(destination)
            provenance = {'file': filename, 'source_class': 'user_supplied_contract_export',
                          'original_relative_path': original.as_posix(),
                          'record_id': record['id'], 'attachment_key': attachment['key'],
                          'metadata': attachment['metadata'], 'original_filename': original.name,
                          'original_sha256': digest, 'original_bytes': len(data),
                          'scope': 'Original local attachment bytes. Export metadata and relationship links do not establish legal precedence.'}
            copies.append((destination, data, provenance))
            if original.suffix.lower() not in SUPPORTED:
                group['unsupported'].append({**item, 'file': filename, 'original_filename': original.name})
    return copies, groups


def import_contract_export(format: str, export_path: str, files_root: str, out: str,
                           mapping_path: str | None = None) -> dict[str, Any]:
    """Preserve an offline export and local attachments in a new Kyma contract folder.

    format is ironclad-json or review-table-csv. Ironclad requires a mapping JSON
    with schema kyma-contract-import-map/v1 and records keyed by exact record id.
    Each mapping supplies customer_id and attachments keyed by attachment key.
    Review CSV columns are document_id,customer_id,file plus arbitrary metadata.
    Every attachment path is relative to files_root. No network request occurs.
    """
    source = Path(export_path).expanduser().resolve()
    root = Path(files_root).expanduser().resolve()
    output = Path(out).expanduser().resolve()
    if not root.is_dir():
        raise ValueError('files_root must be an existing local folder.')
    if output.is_relative_to(root) or root.is_relative_to(output):
        raise ValueError('Use an output folder outside files_root.')
    raw = source.read_bytes()
    mapping_raw = Path(mapping_path).expanduser().read_bytes() if mapping_path else None
    if format == 'ironclad-json':
        if mapping_raw is None:
            raise ValueError('Ironclad requires mapping_path for explicit customer and local attachment identities.')
        records, coverage = _ironclad(raw, _json(mapping_raw))
    elif format == 'review-table-csv':
        if mapping_raw is not None:
            raise ValueError('Review CSV supplies its own customer and file columns. Omit mapping_path.')
        records, coverage = _review_table(raw)
    else:
        raise ValueError('Supported formats: ironclad-json, review-table-csv.')
    if not records:
        raise ValueError('The export contains no records.')

    # Resolve and acquire before the first output write. Never join by a guessed
    # filename, record name, counterparty name, or vendor-specific title label.
    copies, groups = _project(records, root)

    try:
        output.mkdir(parents=True, exist_ok=False)
    except FileExistsError as error:
        raise ValueError('Use a new import output folder. Existing work remains intact.') from error
    contracts = output / 'contracts'
    originals = contracts / '.import'
    originals.mkdir(parents=True)
    originals.joinpath('export.original').write_bytes(raw)
    if mapping_raw is not None:
        originals.joinpath('mapping.original').write_bytes(mapping_raw)
    export_sha = sha256(raw).hexdigest()
    for customer in groups:
        (contracts / customer).mkdir()
    sources = {customer: [] for customer in groups}
    for destination, data, provenance in copies:
        (contracts / destination).write_bytes(data)
        sources[destination.split('/')[0]].append({**provenance, 'export_sha256': export_sha})
    for customer, rows in sources.items():
        (contracts / customer / '_sources.json').write_text(json.dumps(rows, indent=2, ensure_ascii=False) + '\n')
    metadata = {'schema': 'kyma-contract-import/v1', 'format': format,
                'acquired_at_utc': datetime.now(timezone.utc).isoformat(),
                'export': {'file': '.import/export.original', 'sha256': export_sha, 'bytes': len(raw)},
                'mapping': {'file': '.import/mapping.original', 'sha256': sha256(mapping_raw).hexdigest(), 'bytes': len(mapping_raw)} if mapping_raw is not None else None,
                'coverage': coverage, 'customers': groups,
                'documents': [{'path': name, 'sha256': sha256(data).hexdigest(), 'bytes': len(data)} for name, data, _ in copies],
                'precedence': 'No hierarchy is inferred from row order, links, filename or parent id. Interpret the original documents.',
                'completeness': 'Missing attachments and unacquired query pages remain explicit. Even full query coverage does not establish a complete legal agreement set.',
                'format_reference': IRONCLAD_SCHEMA if format == 'ironclad-json' else 'docs/contract-imports.md#review-table-csv',
                'network_requests': 0}
    # This marker commits the import. The inventory rejects an interrupted import
    # whose .import folder exists without this marker.
    (contracts / '_import.json').write_text(json.dumps(metadata, indent=2, ensure_ascii=False) + '\n')
    return {'contracts': str(contracts), 'import_manifest': str(contracts / '_import.json'),
            'customers': len(groups), 'documents_copied': len(copies),
            'missing_attachments': sum(len(group['missing']) for group in groups.values()),
            'unsupported_attachments': sum(len(group['unsupported']) for group in groups.values()),
            'coverage': coverage, 'network_requests': 0,
            'next_action': 'Prepare a contract job with this contracts folder and the actual feature facts.'}
