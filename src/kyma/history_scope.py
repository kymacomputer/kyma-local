"""Select a bounded real-history sample before any transcript is opened."""

from __future__ import annotations

import os
import time

RECENT_FILES = 25
RECENT_BYTES = 128 * 1024 * 1024
MAX_FILE_BYTES = 64 * 1024 * 1024
REPLAY_SECONDS = 3.0


def select(work, *, all_history=False, since_days=None, limit=None,
           max_files=RECENT_FILES, max_bytes=RECENT_BYTES, per_file=MAX_FILE_BYTES):
    """Return selected (path, format) pairs and source-free coverage metadata.

    Explicit history filters retain their requested scope. The default samples
    newest eligible files, with both count and byte bounds. Compressed file size
    cannot bound decoded work, so the quick sample leaves those for --all.
    """
    if all_history:
        limit = None
    rows = []
    unavailable = 0
    for path, host in work:
        try:
            st = os.stat(path)
        except OSError:
            unavailable += 1
            continue
        rows.append((path, host, st.st_size, st.st_mtime))
    rows.sort(key=lambda r: (-r[3], r[0]))
    quick = not (all_history or since_days is not None or limit is not None)
    cutoff = time.time() - since_days * 86400 if since_days else None
    candidates = [r for r in rows if cutoff is None or r[3] >= cutoff]
    if limit is not None:
        candidates = candidates[:max(0, limit)]
    chosen, total = [], 0
    large = compressed = budget = count = 0
    for path, host, size, _mtime in candidates:
        if quick:
            if path.endswith('.zst'):
                compressed += 1
                continue
            if size > per_file:
                large += 1
                continue
            if len(chosen) >= max_files:
                count += 1
                continue
            if total + size > max_bytes:
                budget += 1
                continue
        chosen.append((path, host))
        total += size
    scope = {
        'mode': 'recent' if quick else ('all' if all_history and cutoff is None and limit is None else 'selected'),
        'selected_files': len(chosen), 'available_files': len(rows),
        'selected_bytes': total, 'available_bytes': sum(r[2] for r in rows),
        'skipped_large_files': large, 'skipped_compressed_files': compressed,
        'skipped_budget_files': budget, 'skipped_count_files': count,
        'unavailable_files': unavailable,
        'file_limit': max_files if quick else limit,
        'byte_limit': max_bytes if quick else None,
        'per_file_limit': per_file if quick else None,
        'complete': len(chosen) == len(rows) and unavailable == 0,
    }
    return chosen, scope
