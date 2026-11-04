#!/usr/bin/env python3
"""Preserve actual PDF field values and defaults without a false signature or page claim."""
import json
from pathlib import Path
import tempfile

from pypdf import PdfWriter
from pypdf.generic import ArrayObject, DictionaryObject, NameObject, NumberObject, TextStringObject
from kyma_local.documents import extract


def main():
    with tempfile.TemporaryDirectory(prefix='kyma-pdf-forms-') as raw:
        path = Path(raw) / 'synthetic-order.pdf'
        writer = PdfWriter()
        writer.add_blank_page(width=500, height=500)
        page = writer.add_blank_page(width=500, height=500)
        field = DictionaryObject({NameObject('/FT'): NameObject('/Tx'), NameObject('/T'): TextStringObject('Selected site'),
                                  NameObject('/V'): TextStringObject('Sydney'), NameObject('/DV'): TextStringObject('Adelaide'),
                                  NameObject('/Type'): NameObject('/Annot'), NameObject('/Subtype'): NameObject('/Widget'),
                                  NameObject('/Rect'): ArrayObject([NumberObject(0), NumberObject(0), NumberObject(100), NumberObject(20)]),
                                  NameObject('/P'): page.indirect_reference})
        reference = writer._add_object(field)
        signature = writer._add_object(DictionaryObject({NameObject('/FT'): NameObject('/Sig'), NameObject('/T'): TextStringObject('Signature')}))
        page[NameObject('/Annots')] = ArrayObject([reference])
        writer._root_object[NameObject('/AcroForm')] = DictionaryObject({NameObject('/Fields'): ArrayObject([reference, signature])})
        writer.write(path)
        text, units, warnings = extract(path)
        fields = [unit for unit in units if unit['part'].startswith('pdf-form-field-')]
        actual = next(unit for unit in fields if unit['part'] == 'pdf-form-field-value')
        default = next(unit for unit in fields if unit['part'] == 'pdf-form-field-default')
        assert actual['text'] == 'Sydney' and default['text'] == 'Adelaide'
        assert actual['field_name'] == default['field_name'] == 'Selected site'
        assert actual['page'] == default['page'] == 2
        assert 'Sydney' in text and 'Adelaide' in text
        assert any('does not validate its cryptographic signature' in warning for warning in warnings)
        print(json.dumps({'actual_form_units': fields, 'signature_validity_inferred': False, 'warnings': warnings,
                          'all_passed': True, 'scope': 'A synthetic PDF tests stored value versus default, exact field name, actual page and the signature-validation boundary.'}, indent=2))


if __name__ == '__main__':
    main()
