#!/usr/bin/env python3
"""Acquire complete original SEC exhibits for the public sample pack."""
from datetime import datetime, timezone
import argparse
import hashlib
import json
import os
from pathlib import Path
import time
import urllib.request

ROOT = Path(__file__).resolve().parent
SOURCES = [
    ('c3-bhge', '01-joint-venture-2019-06-06.html', 'https://www.sec.gov/Archives/edgar/data/1577526/000162828020016443/exhibit1010-sx1.htm', 'Joint Venture Agreement', '2019-06-06'),
    ('c3-bhge', '02-first-amendment-2019-09-26.html', 'https://www.sec.gov/Archives/edgar/data/1577526/000162828020016443/exhibit1011-sx1.htm', 'First Amendment to Joint Venture Agreement', '2019-09-26'),
    ('c3-bhge', '03-second-amendment-2020-06-01.html', 'https://www.sec.gov/Archives/edgar/data/1577526/000162828020016443/exhibit1012-sx1.htm', 'Second Amendment to Joint Venture Agreement', '2020-06-01'),
    ('sai-esds', '01-master-services-2026-03-31.html', 'https://www.sec.gov/Archives/edgar/data/2068385/000149315226023769/ex10-17.htm', 'Master Services Agreement with schedules', '2026-03-31'),
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--user-agent', default=os.environ.get('SEC_USER_AGENT'))
    args = parser.parse_args()
    if not args.user_agent:
        raise SystemExit('Set SEC_USER_AGENT or --user-agent to your own SEC research contact. The complete acquired sample is already bundled.')
    rows = []
    for customer, name, url, title, effective in SOURCES:
        folder = ROOT / 'sample' / 'contracts' / customer
        folder.mkdir(parents=True, exist_ok=True)
        request = urllib.request.Request(url, headers={'User-Agent': args.user_agent, 'Accept': 'text/html'})
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                data = response.read()
                status = response.status
                final = response.url
        except Exception as error:
            rows.append({'customer_id': customer, 'file': name, 'url': url,
                         'observed_at_utc': datetime.now(timezone.utc).isoformat(),
                         'error': type(error).__name__ + ':' + str(error)})
            continue
        (folder / name).write_bytes(data)
        rows.append({'customer_id': customer, 'file': name, 'url': url, 'final_url': final,
                     'title': title, 'displayed_effective_date': effective,
                     'observed_at_utc': datetime.now(timezone.utc).isoformat(),
                     'http_status': status, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
                     'source_class': 'public_filing_negotiated_contract',
                     'limits': 'Complete original filed exhibit bytes. Public redactions and referenced missing documents remain material limitations. Not proof of a current customer contract.'})
        time.sleep(.2)
    (ROOT / 'sample' / 'source-acquisition.json').write_text(json.dumps(rows, indent=2) + '\n')
    for customer in {row[0] for row in SOURCES}:
        selected = [row for row in rows if row['customer_id'] == customer]
        (ROOT / 'sample' / 'contracts' / customer / '_sources.json').write_text(json.dumps(selected, indent=2) + '\n')
    print(json.dumps({'attempted': len(rows), 'acquired': sum(x.get('http_status') == 200 for x in rows), 'failures': [x for x in rows if 'error' in x]}, indent=2))


if __name__ == '__main__':
    main()
