"""Collects cases instead of printing them. The batches were written by an
independent red-team reviewer against an earlier build; they stay here as a
permanent record of every way the gate was once walked past.

Paths in the cases say /home/you, a stand-in home: they are rewritten to
the home directory of whoever runs the tests, so a case means the same on
every machine and in a sandbox HOME.
"""
import os

CASES = []
_HOME = os.path.expanduser("~")
FAKE_HOME = "/home/you"


def _here(v):
    if isinstance(v, str):
        return v.replace(FAKE_HOME, _HOME)
    if isinstance(v, dict):
        return {k: _here(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return type(v)(_here(x) for x in v)
    return v


def run(cases, show_compile=False):
    for c in cases:
        CASES.append(_here(c))
