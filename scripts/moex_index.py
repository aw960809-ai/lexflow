#!/usr/bin/env python3
"""Read MOEX's public CSV as an index of *document links*, never as verified answers.

LexFlow fail-closed rules:
- Source unavailable, malformed, empty or unexpectedly small => do not touch output.
- Keep original exam/subject designation, mixed papers stay mixed.
- Answer URL existence is NOT a verified final answer, and no PDF/AI parsing occurs.
- No user data or GitHub token is read or transmitted.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import html
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import urllib.parse
import urllib.request

SOURCE = 'https://wwwc.moex.gov.tw/main/Exam/wHandExamQandA_CSV.ashx'
LANDING = 'https://data.gov.tw/dataset/170565'
MAX_SOURCE_BYTES = 45 * 1024 * 1024
REQUIRED = {'考試年度', '考試名稱', '類科組別', '科目全名', '試題型態', '試題網址', '測驗式試題答案網址'}
FIELDS = {'year': '考試年度', 'exam': '考試名稱', 'grade': '等級分類',
          'exam_grade': '考試及等別', 'group': '類科組別', 'subject': '科目全名',
          'kind': '試題型態', 'question': '試題網址', 'answer': '測驗式試題答案網址',
          'note': '備註'}
FOCUS = ('民法', '刑法', '憲法')


class SourceFailure(ValueError):
    pass


def official_url(text: str) -> str:
    """Return original URL if on MOEX domain and http(s); else blank."""
    value = html.unescape(str(text or '').strip())
    try:
        u = urllib.parse.urlsplit(value)
        hostname = (u.hostname or '').lower().rstrip('.')
        if u.scheme not in ('http', 'https') or u.username or u.password:
            return ''
        if not (hostname == 'moex.gov.tw' or hostname.endswith('.moex.gov.tw')):
            return ''
        if u.port not in (None, 80, 443) or not u.path:
            return ''
        return value
    except ValueError:
        return ''


def decode_csv(data: bytes) -> str:
    if not data or len(data) > MAX_SOURCE_BYTES:
        raise SourceFailure('empty / oversized source')
    if data[:2048].lstrip().lower().startswith((b'<!doctype', b'<html', b'<head')):
        raise SourceFailure('HTML error page is not official CSV')
    for encoding in ('utf-8-sig', 'cp950', 'big5'):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            pass
    raise SourceFailure('unknown CSV encoding')


def fetch_csv(url: str = SOURCE) -> bytes:
    if url != SOURCE:
        raise SourceFailure('download only from the pinned MOEX dataset URL')
    req = urllib.request.Request(url, headers={
        'User-Agent': 'LexFlow/0.3 (public government open data index)',
        'Accept': 'text/csv,application/octet-stream,*/*;q=0.5',
    })
    try:
        with urllib.request.urlopen(req, timeout=45) as res:
            if not official_url(res.geturl()):
                raise SourceFailure('redirect outside MOEX official site')
            content = res.read(MAX_SOURCE_BYTES + 1)
    except (OSError, TimeoutError) as exc:
        raise SourceFailure(f'MOEX source fetch unavailable: {exc}') from exc
    if len(content) > MAX_SOURCE_BYTES:
        raise SourceFailure('CSV exceeds size limit')
    return content


def subjects_of(subject: str) -> tuple[list[str], str] | None:
    found = [x for x in FOCUS if x in subject]
    if found:
        # A paper can include more than one field or mix one field with other law courses.
        mixing = any(x in subject for x in ('綜合法學', '法學知識', '法學大意', '行政法', '民事訴訟法',
                                           '刑事訴訟法', '土地法', '商事法', '保險法', '公司法'))
        return found, ('mixed' if len(found) > 1 or mixing else 'subject_named')
    if any(x in subject for x in ('綜合法學', '法學知識', '法學大意')):
        return [], 'needs_classification'
    return None


def create_index(data: bytes, *, min_rows: int = 30) -> dict:
    text = decode_csv(data)
    reader = csv.DictReader(io.StringIO(text, newline=''))
    headers = {str(x).replace('\ufeff', '').strip() for x in (reader.fieldnames or [])}
    if not REQUIRED.issubset(headers):
        raise SourceFailure('changed/unknown official CSV headers: ' + ','.join(sorted(REQUIRED - headers)))
    candidates: dict[str, dict] = {}
    seen_rows = 0
    bad_links = 0
    for row in reader:
        seen_rows += 1
        if seen_rows > 150_000:
            raise SourceFailure('unexpectedly many rows')
        row = {str(k).replace('\ufeff', '').strip(): (str(v).strip() if v is not None else '')
               for k, v in row.items() if k is not None}
        subject = row.get(FIELDS['subject'], '')
        cls = subjects_of(subject)
        if cls is None:
            continue
        question = official_url(row.get(FIELDS['question'], ''))
        if not question:
            bad_links += 1
            continue
        answer_raw = row.get(FIELDS['answer'], '')
        answer = official_url(answer_raw)
        if answer_raw and not answer:
            bad_links += 1
            continue
        exam = row.get(FIELDS['exam'], '')
        year = row.get(FIELDS['year'], '')
        group = row.get(FIELDS['group'], '')
        grade = row.get(FIELDS['grade'], '')
        paper_kind = row.get(FIELDS['kind'], '')
        if not year.isdigit() or not exam or not paper_kind or not subject:
            raise SourceFailure('incomplete identity metadata on a relevant official row')
        # Deduplicate shared documents within the same examination; preserve all affected groups.
        key_parts = (year, exam, subject, paper_kind, question, answer)
        key = hashlib.sha256('\x1f'.join(key_parts).encode('utf-8')).hexdigest()[:22]
        if key in candidates:
            record = candidates[key]
            if group and group not in record['groups']:
                record['groups'].append(group)
            continue
        candidates[key] = {
            'id': 'moex-' + key, 'year_roc': year, 'exam': exam,
            'grade': grade, 'subject': subject,
            'focus_subjects': cls[0], 'classification': cls[1],
            'question_type': paper_kind, 'question_url': question,
            'answer_url': answer,
            'answer_verification': 'not_verified',
            'explanation_verification': 'not_available',
            'groups': [group] if group else [],
            'source': 'MOEX open dataset 170565 (official link index)',
        }
    if seen_rows < min_rows or not candidates:
        raise SourceFailure(f'suspiciously empty CSV ({seen_rows} rows / {len(candidates)} candidates)')
    if bad_links:
        # Fail closed: dropping a record can hide changed/malicious source URLs.
        raise SourceFailure(f'{bad_links} relevant records contained missing/nonofficial links')
    items = sorted(candidates.values(), key=lambda x: (-int(x['year_roc']), x['exam'], x['subject'], x['id']))
    for x in items:
        x['groups'].sort()
    counts = {name: sum(name in x['focus_subjects'] for x in items) for name in FOCUS}
    return {
        'schema': 'lexflow.moex.index.v1', 'status': 'index_only_unverified_answers',
        'source': {'agency': '考選部', 'dataset_url': LANDING, 'csv_url': SOURCE,
                   'sha256': hashlib.sha256(data).hexdigest()},
        'summary': {'source_rows': seen_rows, 'index_papers': len(items),
                    'subject_papers': counts,
                    'needs_classification': sum(x['classification'] == 'needs_classification' for x in items)},
        'disclaimer': '僅有考選部公告之試卷/答案網址索引；未解析逐題試題，未核對最終答案及詳解，不能供正式計分。',
        'items': items,
    }


def write_atomic(output: Path, data: dict) -> bool:
    result = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + '\n'
    if output.exists() and output.read_text(encoding='utf-8') == result:
        return False
    output.parent.mkdir(parents=True, exist_ok=True)
    handle, name = tempfile.mkstemp(prefix='lexflow-index-', dir=output.parent)
    try:
        with os.fdopen(handle, 'w', encoding='utf-8') as f:
            f.write(result)
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, output)
    finally:
        if os.path.exists(name):
            os.unlink(name)
    return True


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    choices = ap.add_mutually_exclusive_group(required=True)
    choices.add_argument('--fetch', action='store_true', help='download official MOEX CSV')
    choices.add_argument('--input', type=Path, help='existing CSV for offline/fixture tests')
    ap.add_argument('--output', type=Path, default=Path('data/moex_official_index.json'))
    ap.add_argument('--min-rows', type=int, default=30)
    args = ap.parse_args(argv)
    try:
        blob = fetch_csv() if args.fetch else args.input.read_bytes()
        result = create_index(blob, min_rows=args.min_rows)
        changed = write_atomic(args.output, result)
    except (SourceFailure, OSError, UnicodeError, csv.Error, ValueError) as exc:
        print(f'FAIL CLOSED: {exc}; existing index untouched', file=sys.stderr)
        return 2
    print(json.dumps({'changed': changed, **result['summary']}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
