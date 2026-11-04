#!/usr/bin/env python3
"""Import one actual model export into a separate application-owned OpenFeature domain."""
import argparse
import json
from pathlib import Path

from openfeature import api
from openfeature.evaluation_context import EvaluationContext
from kyma_local.tool import build_provider


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('run', type=Path)
    args = parser.parse_args()
    export = json.loads((args.run / 'openfeature-rules.json').read_text())
    contexts = json.loads((args.run / 'evaluation-contexts.json').read_text())
    retained = json.loads((args.run / 'openfeature-consumer.json').read_text())['evaluations']
    api.set_provider_and_wait(build_provider(export), domain='my-feature-contracts')
    client = api.get_client('my-feature-contracts')
    rows = []
    for context, expected in zip(contexts, retained):
        key = export['feature_id'] + '.' + context['operation_id']
        result = client.get_boolean_details(key, False, EvaluationContext(
            targeting_key=context['customer_id'], attributes=context.get('facts') or {}))
        assert result.value is expected['value']
        rows.append({'customer_id': context['customer_id'], 'operation_id': context['operation_id'],
                     'value': result.value, 'reason': str(result.reason)})
    assert len(rows) == len(contexts) == len(retained)
    print(json.dumps({'sdk': 'openfeature-sdk==0.10.0', 'domain': 'my-feature-contracts',
                      'actual_imported_provider_evaluations': rows, 'actual_customer_deployment': False}, indent=2))


if __name__ == '__main__':
    main()
