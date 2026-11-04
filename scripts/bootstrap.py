#!/usr/bin/env python3
"""Select an installed Python 3.10+ and install this kit into its local environment."""
import argparse
import json
from pathlib import Path
import platform
import shutil
import subprocess
import sys


def version(executable):
    result = subprocess.run([executable, '-c', 'import json,sys;print(json.dumps(list(sys.version_info[:3])))'],
                            capture_output=True, text=True, timeout=15)
    return tuple(json.loads(result.stdout)) if result.returncode == 0 else ()


def native_machine():
    if sys.platform == 'darwin':
        result = subprocess.run(['/usr/sbin/sysctl', '-n', 'hw.optional.arm64'],
                                capture_output=True, text=True, timeout=15)
        if result.returncode == 0 and result.stdout.strip() == '1':
            return 'arm64'
    return platform.machine()


def choose_python(candidates):
    usable = []
    for executable in dict.fromkeys(path for path in candidates if path):
        if version(executable) >= (3, 10):
            result = subprocess.run([executable, '-c', 'import platform;print(platform.machine())'],
                                    capture_output=True, text=True, timeout=15)
            usable.append((executable, result.stdout.strip()))
    preferred = native_machine()
    return next((path for path, machine in usable if machine == preferred), usable[0][0] if usable else None)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--venv', type=Path)
    parser.add_argument('--mcp', action='store_true', help='Include the optional local MCP server.')
    args = parser.parse_args()
    kit = Path(__file__).resolve().parent.parent
    target = (args.venv or kit / '.venv').resolve()
    candidates = [sys.executable] + [shutil.which(name) for name in
        ['python3.13', 'python3.12', 'python3.11', 'python3.10', 'python3']]
    python = choose_python(candidates)
    if not python:
        raise SystemExit('Python 3.10 or later is required. Install it, then repeat this command. No credential or account change occurred.')
    if target.exists():
        existing = target / 'bin/python'
        if not existing.exists() or version(str(existing)) < (3, 10):
            raise SystemExit('The selected environment uses an older Python. Use --venv with a new local path. Existing files remain intact.')
    else:
        subprocess.run([python, '-m', 'venv', str(target)], check=True)
    package = str(kit) + ('[mcp]' if args.mcp else '')
    subprocess.run([str(target / 'bin/python'), '-m', 'pip', 'install', package], check=True)
    print(json.dumps({'environment': str(target), 'python': version(str(target / 'bin/python')),
                      'next_command': str(target / 'bin/kyma-local') + ' doctor',
                      'credential_files_read_or_copied': False}, indent=2))


if __name__ == '__main__':
    main()
