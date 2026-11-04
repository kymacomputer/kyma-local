#!/usr/bin/env python3
"""Check exact package files and isolated extraction/type invariants without another model call."""
import argparse
import hashlib
import json
from pathlib import Path
import tempfile
import zipfile

from kyma_local.documents import extract


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('kit', type=Path)
    args = parser.parse_args()
    kit = args.kit.resolve()
    manifest = json.loads((kit / 'PACKAGE-MANIFEST.json').read_text())
    for row in manifest['files']:
        path = kit / row['path']
        assert path.stat().st_size == row['bytes']
        assert hashlib.sha256(path.read_bytes()).hexdigest() == row['sha256'], row['path']
    assert not list(kit.rglob('auth.json'))
    assert not list(kit.rglob('events.private.jsonl'))
    assert not list(kit.rglob('stderr.private.txt'))
    checks = [{'case': 'exact_package_manifest', 'files': len(manifest['files']), 'passed': True}]
    with tempfile.TemporaryDirectory(prefix='kyma-format-check-') as raw:
        root = Path(raw)
        path = root / 'test.docx'
        namespace = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
        with zipfile.ZipFile(path, 'w') as archive:
            archive.writestr('word/document.xml', '<w:document xmlns:w="' + namespace + '"><w:body>'
                             '<w:p><w:r><w:t>Main contract.</w:t></w:r></w:p>'
                             '<w:tbl><w:tr><w:tc><w:p><w:r><w:t>Order condition.</w:t></w:r></w:p></w:tc></w:tr></w:tbl>'
                             '<w:p><w:del><w:r><w:delText>Deleted grant.</w:delText></w:r></w:del></w:p>'
                             '</w:body></w:document>')
            archive.writestr('word/footnotes.xml', '<w:footnotes xmlns:w="' + namespace + '"><w:footnote>'
                             '<w:p><w:r><w:t>Material footnote.</w:t></w:r></w:p></w:footnote></w:footnotes>')
        text, units, warnings = extract(path)
        assert all(value in text for value in ['Main contract.', 'Order condition.', 'Deleted grant.', 'Material footnote.'])
        assert any('tracked revisions' in warning for warning in warnings)
        checks.append({'case': 'docx_table_footnote_and_revision_boundary', 'passed': True,
                       'parts': [unit['part'] for unit in units], 'warnings': warnings})
        from pypdf import PdfWriter
        from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
        writer = PdfWriter()
        for value in ['First original page.', 'Second original page.']:
            page = writer.add_blank_page(width=500, height=500)
            font = DictionaryObject({NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'),
                                     NameObject('/BaseFont'): NameObject('/Helvetica')})
            page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): font})})
            stream = DecodedStreamObject();stream.set_data(('BT /F1 12 Tf 40 450 Td (' + value + ') Tj ET').encode())
            page[NameObject('/Contents')] = stream
        writer.add_blank_page(width=500, height=500)
        path = root / 'test.pdf'
        writer.write(path)
        text, units, warnings = extract(path)
        assert units[0]['page'] == 1 and 'First original page.' in units[0]['text']
        assert units[1]['page'] == 2 and 'Second original page.' in units[1]['text']
        assert units[2]['page'] == 3 and any('Page 3 has no extractable text' in warning for warning in warnings)
        checks.append({'case': 'pdf_original_pages_and_no_text_limit', 'passed': True,
                       'pages': len(units), 'warnings': warnings})
    print(json.dumps({'checks': checks, 'all_passed': True,
                      'scope': 'Fresh package bytes, original PDF page identity, DOCX material parts and explicit extraction limits. No semantic accuracy or outside use is inferred.'}, indent=2))


if __name__ == '__main__':
    main()
