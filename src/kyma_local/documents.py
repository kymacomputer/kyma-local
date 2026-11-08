"""Complete local text acquisition with immutable original-byte fingerprints."""
from hashlib import sha256
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import zipfile
import xml.etree.ElementTree as ET

SUPPORTED = {'.txt', '.md', '.html', '.htm', '.pdf', '.docx'}


class VisibleHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in {'script', 'style', 'noscript'}:
            self.skip += 1
        if not self.skip and tag in {'p', 'div', 'tr', 'td', 'th', 'li', 'br', 'hr', 'h1', 'h2', 'h3', 'h4'}:
            self.parts.append('\n')

    def handle_endtag(self, tag):
        if tag in {'script', 'style', 'noscript'}:
            self.skip = max(0, self.skip - 1)
        if not self.skip and tag in {'p', 'div', 'tr', 'td', 'th', 'li', 'h1', 'h2', 'h3', 'h4'}:
            self.parts.append('\n')

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def extract(path):
    warnings = []
    units = []
    if path.suffix.lower() in {'.html', '.htm'}:
        parser = VisibleHTML()
        parser.feed(path.read_text(errors='replace'))
        text = '\n'.join(line for raw in ''.join(parser.parts).splitlines()
                         if (line := re.sub(r'[\t \u00a0]+', ' ', raw).strip()))
        units = [{'page': None, 'part': 'complete-visible-html', 'text': text}]
    elif path.suffix.lower() == '.pdf':
        from pypdf import PdfReader
        reader = PdfReader(path)
        for number, page in enumerate(reader.pages, 1):
            text = page.extract_text(extraction_mode='layout') or ''
            if not text.strip():
                warnings.append('Page ' + str(number) + ' has no extractable text. OCR or the original text source is required.')
            units.append({'page': number, 'part': 'pdf-page', 'text': text})
        for name, field in sorted((reader.get_fields() or {}).items()):
            if field.get('/FT') == '/Sig':
                warnings.append('Signature field ' + name + ' is present. This extractor does not validate its cryptographic signature or legal effect.')
                continue
            try:
                pages = [reader.get_page_number(page) + 1 for page in reader.get_pages_showing_field(field)]
            except (ValueError, AttributeError):
                pages = []
            for key, role in [('/V', 'value'), ('/DV', 'default')]:
                value = field.get(key)
                if value is None:
                    continue
                values = value if isinstance(value, list) else [value]
                for part in values:
                    if not isinstance(part, (str, int, float)):
                        warnings.append('Form field ' + name + ' has an unsupported ' + role + '. Review its original PDF object.')
                        continue
                    for number in pages or [None]:
                        units.append({'page': number, 'part': 'pdf-form-field-' + role,
                                      'field_name': name, 'field_type': str(field.get('/FT', '')),
                                      'text': str(part)})
            if not pages:
                warnings.append('Form field ' + name + ' has no verified page mapping. Its value cannot receive an invented page reference.')
    elif path.suffix.lower() == '.docx':
        with zipfile.ZipFile(path) as archive:
            parts = sorted(name for name in archive.namelist() if name.startswith('word/') and
                           (name == 'word/document.xml' or re.match(r'word/(footnotes|endnotes|header\d*|footer\d*)\.xml$', name)))
            for name in parts:
                element = ET.fromstring(archive.read(name))
                paragraphs = []
                for paragraph in element.iter('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p'):
                    words = [node.text or '' for node in paragraph.iter()
                             if node.tag in {'{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t',
                                             '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}delText'}]
                    paragraphs.append(''.join(words))
                if any(node.tag.endswith(('}ins', '}del', '}moveFrom', '}moveTo')) for node in element.iter()):
                    warnings.append(name + ' contains tracked revisions. Their acceptance state needs source review.')
                units.append({'page': None, 'part': name, 'text': '\n'.join(paragraphs)})
    else:
        units = [{'page': None, 'part': 'original-text', 'text': path.read_text(errors='replace')}]
    text = '\n\n'.join(unit['text'] for unit in units)
    if not text.strip():
        warnings.append('The document has no usable extracted text. Do not infer its missing terms.')
    return text, units, warnings


def read_groups(root, output, role='customer', namespace=''):
    root = Path(root).resolve()
    groups = []
    for folder in sorted(path for path in root.iterdir() if path.is_dir() and not path.name.startswith('.')):
        provenance = {}
        if (folder / '_sources.json').exists():
            provenance = {row['file']: row for row in json.loads((folder / '_sources.json').read_text())}
        documents, warnings, unsupported = [], [], []
        for path in sorted(folder.rglob('*')):
            if not path.is_file() or path.name.startswith(('.', '_')):
                continue
            if path.suffix.lower() not in SUPPORTED:
                unsupported.append(str(path.relative_to(folder)))
                continue
            identity = namespace + folder.name + ':' + str(path.relative_to(folder))
            try:
                text, units, extraction_warnings = extract(path)
            except Exception as error:
                text, units = '', []
                extraction_warnings = [type(error).__name__ + ': ' + str(error)]
            target = 'documents/' + sha256(identity.encode()).hexdigest()[:16] + '.txt'
            (output / target).write_text(text)
            row = {'id': identity, 'customer_id': folder.name if role == 'customer' else None,
                   'source_role': role, 'original_relative_path': str(path.relative_to(root)),
                   'original_bytes': path.stat().st_size, 'original_sha256': sha256(path.read_bytes()).hexdigest(),
                   'text_file': target, 'text_bytes': len(text.encode()), 'text_sha256': sha256(text.encode()).hexdigest(),
                   'units': units, 'warnings': extraction_warnings,
                   'form_fields': [unit for unit in units if unit['part'].startswith('pdf-form-field-')],
                   'provenance': provenance.get(path.name, {'source_class': 'user_supplied', 'scope': 'User selected source. Contract applicability is a model-assessed fact, not inferred from folder custody.'})}
            documents.append(row)
            warnings.extend(identity + ': ' + warning for warning in extraction_warnings)
        groups.append({'id': folder.name, 'source_role': role, 'documents': documents, 'acquisition_warnings': warnings,
                          'unsupported_files': unsupported,
                          'completeness': 'Every supported file in this folder is included. Missing references, redactions and contract applicability require source interpretation.'})
    return groups


def inventory(contracts, output, references=None, reference_baseline=None):
    contracts = Path(contracts).resolve()
    output = Path(output).resolve()
    from .importers import read_import_context
    imported = read_import_context(contracts)
    (output / 'documents').mkdir(parents=True, exist_ok=True)
    customers = read_groups(contracts, output)
    if imported:
        if {group['id'] for group in customers} != set(imported['customers']):
            raise ValueError('Imported customer folders differ from the import manifest.')
        for group in customers:
            group['import_context'] = imported['customers'][group['id']]
            group['import_coverage'] = imported['coverage']
            group['acquisition_warnings'] += [
                'Export attachment is missing: ' + json.dumps(row, ensure_ascii=False)
                for row in group['import_context']['missing']]
            group['completeness'] = imported['completeness']
    assert customers and any(customer['documents'] for customer in customers), 'No customer subfolder contains supported documents.'
    value = {'schema': 'kyma-source-inventory/v1', 'customers': customers,
             'input_root': str(contracts), 'full_sources': True,
             'limits': 'Complete acquired text is not a guarantee that the underlying legal agreement is complete. Image-only pages and revisions remain explicit.'}
    if imported:
        value['contract_import'] = imported
    if references:
        value['reference_sets'] = read_groups(references, output, 'shared_reference', 'reference:')
        value['reference_root'] = str(Path(references).resolve())
    if reference_baseline:
        value['historical_reference_sets'] = read_groups(reference_baseline, output, 'historical_reference', 'historical-reference:')
        value['historical_reference_root'] = str(Path(reference_baseline).resolve())
    (output / 'source-manifest.json').write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')
    return value


def document_groups(manifest):
    return [group for key in ['customers', 'reference_sets', 'historical_reference_sets', 'historical_customer_sets']
            for group in manifest.get(key, [])]
