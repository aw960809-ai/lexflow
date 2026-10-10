#!/usr/bin/env python3
"""Two-source MOEX updater. Distinct outputs prevent partial fallback replacing CSV.

CSV success -> update the full CSV candidate only.
CSV failure -> attempt the approved MOEX individual-exam HTML page and update
its separate candidate only. Two failures -> preserve BOTH previous snapshots.
No private records or question answers are accessed or published.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
from moex_index import fetch_csv, create_index, write_atomic, SourceFailure
from moex_page_fallback import fetch_exam_page, create_fallback_index


def sync(*, primary: Path, fallback: Path, fallback_only: bool = False,
         input_csv: bytes | None = None, input_html: bytes | None = None,
         fetch_primary=fetch_csv, fetch_secondary=fetch_exam_page) -> dict:
    if not fallback_only:
        try:
            contents = input_csv if input_csv is not None else fetch_primary()
            data = create_index(contents, min_rows=30)
            return {'mode': 'primary_csv', 'changed': write_atomic(primary, data),
                    'details': data['summary']}
        except (SourceFailure, OSError, ValueError, UnicodeError) as ex:
            print(f'Primary official CSV unavailable/invalid: {ex}; primary snapshot untouched', file=sys.stderr)
    try:
        contents = input_html if input_html is not None else fetch_secondary('114120')
        data = create_fallback_index(contents, exam_code='114120', min_items=3)
        return {'mode': 'separate_individual_exam_fallback',
                'changed': write_atomic(fallback, data), 'details': data['summary']}
    except (SourceFailure, OSError, ValueError, UnicodeError) as ex:
        raise SourceFailure(f'official page fallback unavailable/invalid: {ex}; both previous snapshots untouched') from ex


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--primary', type=Path, default=Path('data/moex_official_index.json'))
    ap.add_argument('--fallback', type=Path, default=Path('data/moex_official_fallback.json'))
    ap.add_argument('--fallback-only', action='store_true',
                    help='safe read-only source check in a temporary output location')
    a = ap.parse_args(argv)
    if a.primary.resolve() == a.fallback.resolve():
        print('FAIL CLOSED: primary/fallback output paths must be different', file=sys.stderr)
        return 2
    try:
        result = sync(primary=a.primary, fallback=a.fallback, fallback_only=a.fallback_only)
    except SourceFailure as err:
        print(f'FAIL CLOSED: {err}', file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
