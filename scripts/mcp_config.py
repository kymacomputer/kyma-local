"""Print a host configuration for this installed copy without editing host settings."""
import json
from pathlib import Path

kit = Path(__file__).resolve().parent.parent
print(json.dumps({'mcpServers': {'kyma-local': {
    'command': str(kit / '.venv/bin/kyma-local-mcp'), 'args': []}}}, indent=2))
