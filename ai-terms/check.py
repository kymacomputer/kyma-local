#!/usr/bin/env python3
"""Validate an editable AI-terms file and export its complete local tables."""
from __future__ import annotations

import argparse
import csv
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import tempfile
from urllib.parse import urlsplit

FIELDS = (
    'training_on_customer_data', 'ai_subprocessors_and_wayback_first_seen',
    'new_subprocessor_notice_days', 'objection_remedy',
    'prompt_output_retention_days', 'ai_processing_regions', 'customer_ai_stop_right',
)
RELATIONS = ('actor', 'data', 'purpose', 'model', 'feature', 'hierarchy', 'condition')
FLAGS = ('customer_specific_clearance', 'vendor_authored', 'vendor_adopted', 'outside_adoption')


def require(predicate, message):
    if not predicate:
        raise ValueError(message)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def read_json(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, 'duplicate_json_key:' + key)
            result[key] = value
        return result
    return json.loads(path.read_bytes(), object_pairs_hook=unique)


def text(value, label):
    require(isinstance(value, str) and bool(value.strip()), label + ':nonempty_string_required')
    return value


def hash_value(value, label):
    require(isinstance(value, str) and re.fullmatch(r'[0-9a-f]{64}', value), label + ':sha256_required')


def identifiers(rows, label):
    require(isinstance(rows, list), label + ':array_required')
    result = {}
    for row in rows:
        require(isinstance(row, dict), label + ':object_required')
        key = text(row.get('id'), label + '.id')
        require(key not in result, label + ':duplicate_id:' + key)
        result[key] = row
    return result


def timestamp(value, label):
    try:
        parsed = datetime.fromisoformat(text(value, label).replace('Z', '+00:00'))
    except (ValueError, TypeError) as error:
        raise ValueError(label + ':timestamp_required') from error
    require(parsed.tzinfo is not None, label + ':timezone_required')


def relative_file(root, name):
    part = Path(text(name, 'path'))
    require(not part.is_absolute() and '..' not in part.parts, 'unsafe_source_path')
    path = root / part
    require(path.resolve().is_relative_to(root.resolve()) and not path.is_symlink(), 'unsafe_source_path')
    return path


def check(path, expected_sha256=None, source_root=None):
    path = Path(path).resolve()
    raw = path.read_bytes()
    if expected_sha256 is not None:
        hash_value(expected_sha256, 'expected_sha256')
        require(digest(raw) == expected_sha256, 'reviewed_file_changed')
    document = read_json(path)
    require(isinstance(document, dict), 'document_object_required')
    require(document.get('schema') == 'kyma-ai-terms-file/v1', 'unsupported_schema')
    require(document.get('format_license') == 'MIT', 'unsupported_format_license')
    for key in ('company', 'domain', 'status', 'method'):
        text(document.get(key), key)
    timestamp(document.get('created_at_utc'), 'created_at_utc')
    for key in FLAGS:
        require(type(document.get(key)) is bool, key + ':boolean_required')
    require(document['customer_specific_clearance'] is False, 'customer_clearance_outside_format_scope')
    boundaries = document.get('boundaries')
    require(isinstance(boundaries, list) and boundaries and all(isinstance(v, str) and v.strip() for v in boundaries), 'boundaries_required')
    require(len(set(boundaries)) == len(boundaries), 'duplicate_boundary')
    pin = document.get('source_pins', {})
    require(isinstance(pin, dict), 'source_pins_object_required')
    evidence_path = relative_file(path.parent, pin.get('path'))
    require(Path(pin['path']).parts[0] not in {'ai-terms.json', 'index-fields.csv', 'decisions.csv', 'CHECK.json'},
            'reserved_evidence_output_path')
    hash_value(pin.get('sha256'), 'source_pins.sha256')
    require(digest(evidence_path.read_bytes()) == pin['sha256'], 'source_evidence_changed')
    evidence = read_json(evidence_path)
    require(isinstance(evidence, dict), 'evidence_object_required')
    require(evidence.get('schema') == 'kyma-ai-terms-evidence/v1', 'unsupported_evidence_schema')
    sources = identifiers(evidence.get('sources'), 'sources')
    excerpts = identifiers(evidence.get('spans'), 'spans')
    require(sources and excerpts, 'source_evidence_required')
    for source in sources.values():
        url = urlsplit(text(source.get('url'), 'source.url'))
        require(url.scheme == 'https' and bool(url.hostname) and not url.username and not url.password,
                'public_https_source_required')
        hash_value(source.get('sha256'), 'source.sha256')
        timestamp(source.get('observed_at_utc'), 'source.observed_at_utc')
        require(type(source.get('bytes')) is int and source['bytes'] > 0, 'source_size_required')
        if source_root is not None:
            body = relative_file(Path(source_root), source.get('body_path')).read_bytes()
            require(len(body) == source['bytes'] and digest(body) == source['sha256'], 'full_source_changed:' + source['id'])
    for excerpt in excerpts.values():
        require(excerpt.get('source_id') in sources, 'unknown_excerpt_source')
        hash_value(excerpt.get('normalized_text_sha256'), 'excerpt.normalized_text_sha256')
        source = sources[excerpt['source_id']]
        require(excerpt.get('source_sha256') == source['sha256'], 'excerpt_source_hash_mismatch')
        start, end = excerpt.get('html_byte_start'), excerpt.get('html_byte_end_exclusive')
        require(type(start) is int and type(end) is int and 0 <= start < end <= source['bytes'], 'invalid_excerpt_offsets')
        hash_value(excerpt.get('html_span_sha256'), 'excerpt.html_span_sha256')
        if source_root is not None:
            body = relative_file(Path(source_root), source['body_path']).read_bytes()
            require(digest(body[start:end]) == excerpt['html_span_sha256'], 'source_span_changed:' + excerpt['id'])
    case = document.get('decision_case', {})
    require(isinstance(case, dict), 'decision_case_object_required')
    rows = identifiers(case.get('rows'), 'decisions')
    queue = identifiers(case.get('uncertainty_queue'), 'uncertainty_queue')
    for entry in queue.values():
        for key in ('issue', 'needed_evidence', 'decision_effect', 'state', 'owner'):
            text(entry.get(key), 'uncertainty.' + key)
    require(rows, 'decision_rows_required')
    require(type(case.get('customer_specific_clearance')) is bool and case['customer_specific_clearance'] is False,
            'customer_clearance_outside_format_scope')
    for row in rows.values():
        for key in ('title', 'public_decision'):
            text(row.get(key), 'decision.' + key)
        for relation in RELATIONS:
            value = row.get(relation, {})
            require(isinstance(value, dict), relation + ':object_required')
            text(value.get('statement'), relation + '.statement')
            require(value.get('source_span_ids'), relation + ':source_binding_required')
    index = document.get('index_fields')
    require(isinstance(index, list) and len(index) == len(FIELDS), 'index_field_population_changed')
    require(all(isinstance(row, dict) and isinstance(row.get('field'), str) for row in index), 'index_object_required')
    require(len({row.get('field') for row in index}) == len(FIELDS)
            and {row.get('field') for row in index} == set(FIELDS), 'index_field_population_changed')
    for row in index:
        text(row.get('value'), 'index.value')
        text(row.get('statement'), 'index.statement')
        require(row.get('source_span_ids'), 'index_source_binding_required')
        require(isinstance(row.get('uncertainty_queue_ids'), list), 'index_uncertainty_array_required')

    def references(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key in {'source_span_ids', 'uncertainty_queue_ids'}:
                    require(isinstance(item, list) and all(isinstance(v, str) for v in item), 'reference_array_required')
                    require(len(set(item)) == len(item), 'duplicate_reference')
                    population = excerpts if key == 'source_span_ids' else queue
                    require(all(v in population for v in item), 'unresolved_' + key)
                else:
                    references(item)
        elif isinstance(value, list):
            for item in value:
                references(item)
    references(document)
    require(isinstance(document.get('source_document_ids'), list) and document['source_document_ids']
            and all(isinstance(v, str) and v in sources for v in document['source_document_ids']), 'unresolved_source_document_ids')
    require(len(set(document['source_document_ids'])) == len(document['source_document_ids']), 'duplicate_source_document_id')
    return document, evidence, {
        'schema': 'kyma-ai-terms-check/v1', 'file_sha256': digest(raw),
        'company': document['company'], 'index_fields': len(index), 'decision_rows': len(rows),
        'source_documents': len(sources), 'source_spans': len(excerpts),
        'reviewed_digest_matched': expected_sha256 is not None,
        'full_source_bytes_verified': source_root is not None,
        'declarations': {key: document[key] for key in FLAGS},
        'vendor_authorship_verified': False, 'outside_adoption_verified': False,
        'legal_clearance': False,
        'scope': 'Structural fields, citation references and evidence-file integrity. Optional original source bytes and span hashes. Statements require substantive review.',
    }


def export(path, out, expected_sha256=None, source_root=None):
    document, evidence, receipt = check(path, expected_sha256, source_root)
    out = Path(out)
    require(not out.exists(), 'new_output_directory_required')
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.ai-terms-', dir=out.parent) as temporary:
        stage = Path(temporary) / 'result'
        stage.mkdir()
        (stage / 'ai-terms.json').write_bytes(Path(path).read_bytes())
        evidence_path = relative_file(stage, document['source_pins']['path'])
        evidence_path.parent.mkdir(parents=True, exist_ok=True)
        evidence_path.write_bytes(relative_file(Path(path).resolve().parent, document['source_pins']['path']).read_bytes())
        with (stage / 'index-fields.csv').open('w', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=['field', 'value', 'statement', 'source_span_ids', 'uncertainty_queue_ids'])
            writer.writeheader()
            for row in document['index_fields']:
                writer.writerow({key: ' | '.join(row[key]) if isinstance(row[key], list) else row[key] for key in writer.fieldnames})
        with (stage / 'decisions.csv').open('w', newline='') as stream:
            fields = ['id', 'title', 'public_decision', *[k for relation in RELATIONS for k in (relation, relation + '_source_spans')], 'uncertainty_queue_ids']
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            for row in document['decision_case']['rows']:
                flat = {key: row.get(key, '') for key in ('id', 'title', 'public_decision')}
                flat['uncertainty_queue_ids'] = ' | '.join(row.get('uncertainty_queue_ids', []))
                for relation in RELATIONS:
                    flat[relation] = row[relation]['statement']
                    flat[relation + '_source_spans'] = ' | '.join(row[relation]['source_span_ids'])
                writer.writerow(flat)
        (stage / 'CHECK.json').write_text(json.dumps(receipt, indent=2) + '\n')
        stage.rename(out)
    return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('file', type=Path)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--expected-sha256')
    parser.add_argument('--source-root', type=Path, help='Optional original source captures. No network access occurs.')
    args = parser.parse_args()
    try:
        print(json.dumps(export(args.file, args.out, args.expected_sha256, args.source_root), indent=2))
    except (ValueError, KeyError, TypeError, OSError) as error:
        parser.exit(1, 'AI terms check failed: ' + str(error) + '\n')
