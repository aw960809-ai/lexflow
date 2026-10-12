#!/usr/bin/env python3
"""LexFlow V0.3: conservative MOEX source/PDF QA, NEVER official scoring.

- Pinned official exam-page origin and bounded sample; does not scrape arbitrary URLs.
- Validates identity of Q/S/M pairs by full official query key.
- Verifies selected PDF responses as real, readable PDF documents, with SHA-256.
- Separates published standard answer (S), correction (M), and exam-wide ledger (A).
- Flags suspicious category inheritance; no automatic answer matching or publication.
- Writes only a separate QA report. Does NOT modify candidate index, quiz.js or data.
"""
from __future__ import annotations
import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import sys
import urllib.request
from urllib.parse import urlsplit

from moex_index import SourceFailure, write_atomic
from moex_page_fallback import (create_fallback_index, fetch_exam_page,
                                official_document_url, official_aggregate_answer_url, page_url)

EXAM = '114120'
MAX_PDF_BYTES = 8 * 1024 * 1024
MAX_PAGES = 120
# Fixed, independently selected smoke cases. The list is intentionally small to
# avoid burdening the MOEX site and MUST NOT be represented as all indexed PDFs.
CASES = (
    ('civil', '民法概要', '201', '0405', ('Q', 'S')),
    ('criminal', '刑法概要', '201', '0504', ('Q',)),
    ('mixed_corrected', '法學知識與英文', '201', '0204', ('Q', 'S', 'M')),
)
ROLE = {'Q': 'question_pdf', 'S': 'published_standard_answer_pdf',
        'M': 'published_correction_pdf', 'A': 'exam_wide_answer_ledger_pdf'}

class DocumentQAError(ValueError):
    pass


def doc_identity(url: str, role: str) -> tuple[str, str, str]:
    checked = official_document_url(url, exam_code=EXAM)
    if checked is None or checked[1] != role:
        raise DocumentQAError(f'nonofficial or wrong-role {role} document link')
    return checked[2]


def require_pairs(item: dict, roles: tuple[str, ...]) -> list[tuple[str, str]]:
    """All S/M answer links MUST match the selected Q identity exactly."""
    key = doc_identity(item['question_url'], 'Q')
    result = []
    for role in roles:
        field = {'Q': 'question_url', 'S': 'answer_url', 'M': 'answer_correction_url'}[role]
        url = item.get(field, '')
        if not url:
            raise DocumentQAError(f'missing {role} link in selected official paper')
        if doc_identity(url, role) != key:
            raise DocumentQAError(f'question and {role} answer have different MOEX identity keys')
        result.append((role, url))
    return result


def select_smoke(index: dict) -> list[dict]:
    if (index.get('schema') != 'lexflow.moex.index.v1'
        or index.get('status') != 'fallback_official_page_links_unverified'
        or not isinstance(index.get('items'), list)
        or index.get('source', {}).get('exam_pages') != [page_url(EXAM)]):
        raise DocumentQAError('unrecognized official fallback candidate index')
    result = []
    for name, subject, c, s, roles in CASES:
        found = []
        for item in index['items']:
            if subject not in item.get('subject', ''):
                continue
            checked = official_document_url(item.get('question_url', ''), exam_code=EXAM)
            if checked and checked[1] == 'Q' and checked[2][0] == c and checked[2][2] == s:
                found.append(item)
        if len(found) != 1:
            raise DocumentQAError(f'smoke sample {name}: expected exactly one linked paper, got {len(found)}')
        item = found[0]
        result.append({'case': name, 'subject': item['subject'],
                       'index_id': item['id'], 'groups': item.get('groups', []),
                       'documents': require_pairs(item, roles)})
    aggregate = index['source'].get('exam_wide_answer_url', '')
    if not official_aggregate_answer_url(aggregate, exam_code=EXAM):
        raise DocumentQAError('missing or unsafe exam-wide answer ledger link')
    result.append({'case': 'exam_ledger', 'subject': '考試全科目答案更正清冊',
                   'index_id': None, 'groups': [], 'documents': [('A', aggregate)]})
    return result


def metadata_warnings(index: dict) -> list[dict]:
    """Conservative anomaly detection; neither classify nor rewrite the MOEX items."""
    items = index.get('items', [])
    frequency = {}
    for item in items:
        for name in set(item.get('groups', [])):
            frequency[name] = frequency.get(name, 0) + 1
    warnings = []
    for group, count in sorted(frequency.items()):
        # An apparent group assigned to >20 different paper links may indicate
        # inherited HTML context. Not proof of an error: requires source review.
        if count > 20:
            warnings.append({'code': 'group_context_may_be_stale',
                             'group': group, 'count': count,
                             'action': 'verify against the original exam page; do not publish group as confirmed'})
    for item in items:
        if item.get('answer_verification') not in ('not_verified', None):
            warnings.append({'code':'unexpected_answer_claim', 'id':item.get('id')})
    return warnings


def validate_pdf_bytes(data: bytes) -> None:
    """Strong format screening; not a substitute for parsing document content."""
    if len(data) < 128 or len(data) > MAX_PDF_BYTES or not data.startswith(b'%PDF-'):
        raise DocumentQAError('response is not a valid sized PDF header/body')
    if b'%%EOF' not in data[-4096:]:
        raise DocumentQAError('PDF trailer missing or incomplete download')


def check_response_origin(value: str, role: str) -> None:
    # No redirects to outside domains, plaintext endpoints or arbitrary paths.
    if role == 'A':
        allowed = official_aggregate_answer_url(value, exam_code=EXAM)
    else:
        allowed = official_document_url(value, exam_code=EXAM)
        allowed = allowed[0] if allowed and allowed[1] == role else ''
    if not allowed:
        raise DocumentQAError('PDF response redirected outside approved MOEX document URL')


def download_pdf(url: str, role: str, timeout: int = 35) -> bytes:
    check_response_origin(url, role)
    request = urllib.request.Request(url, headers={
        'User-Agent': 'LexFlow/0.3 (official public PDF QA, rate-limited)',
        'Accept': 'application/pdf,application/octet-stream;q=0.7,*/*;q=0.2',
    })
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            check_response_origin(response.geturl(), role)
            declared = response.headers.get('Content-Length')
            if declared and int(declared) > MAX_PDF_BYTES:
                raise DocumentQAError('PDF exceeds download size limit')
            data = response.read(MAX_PDF_BYTES + 1)
    except (OSError, TimeoutError, ValueError) as exc:
        raise DocumentQAError(f'official PDF fetch failed: {type(exc).__name__}: {exc}') from exc
    validate_pdf_bytes(data)
    return data


def inspect_pdf(data: bytes, *, expected: str) -> dict:
    """Require a working PDF parser to validate the document, but no answer extraction."""
    validate_pdf_bytes(data)
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise DocumentQAError('pypdf is required for real-PDF structure verification') from exc
    try:
        reader = PdfReader(io.BytesIO(data), strict=False)
        pages = len(reader.pages)
        if not 1 <= pages <= MAX_PAGES:
            raise DocumentQAError('PDF page count outside accepted range')
        texts = []
        for page in reader.pages[:min(pages, 3)]:
            texts.append(page.extract_text() or '')
        compact = re.sub(r'\s+', '', ''.join(texts))
        expected_compact = re.sub(r'\s+', '', expected)
        label_match = expected_compact in compact
    except DocumentQAError:
        raise
    except Exception as exc:
        raise DocumentQAError(f'PDF parser cannot read document: {type(exc).__name__}') from exc
    return {'pages': pages, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
            'expected_subject_text_seen': label_match,
            'identity_validation': ('sampled_subject_label_matches' if label_match
                                    else 'document_text_needs_independent_review')}


def review_index(index: dict, *, fetch=download_pdf, inspect=inspect_pdf) -> dict:
    samples = select_smoke(index)
    warnings = metadata_warnings(index)
    results = []
    for sample in samples:
        documents = []
        for role, url in sample['documents']:
            # Matching a label never constitutes verification of answer choices.
            expected = ('標準答案' if role == 'A' else
                        '法學知識與英文' if sample['case'] == 'mixed_corrected' else
                        sample['subject'])
            doc = inspect(fetch(url, role), expected=expected)
            documents.append({'kind': ROLE[role], 'url': url, **doc,
                              'answer_options_verified': False})
        results.append({'case': sample['case'], 'subject': sample['subject'],
                        'index_id': sample['index_id'],
                        'index_groups_verified': False, 'documents': documents})
    return {
        'schema': 'lexflow.moex.document.qa.v1',
        'status': 'sampled_pdfs_readable_not_final_question_validation',
        'agency': '考選部', 'source_exam': EXAM,
        'sampling': {'papers_tested': 3, 'individual_pdf_count': sum(len(s['documents']) for s in samples),
                     'indexed_candidates': len(index['items']),
                     'all_indexed_pdfs_verified': False},
        'metadata_warnings': warnings,
        'checked': results,
        'publication_allowed': False, 'scoring_enabled': False,
        'answer_choices_verified': False, 'correction_applied_to_choices': False,
        'disclaimer': ('Only selected official PDF documents were downloaded and parsed. '
                       'Original answers, correction notices, metadata and individual '
                       'answer choices require source-linked content verification; '
                       'nothing here is a scored exam bank.'),
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true', help='use pinned MOEX 114120 exam HTML')
    parser.add_argument('--input-index', type=Path, help='candidate JSON from a previous official source fetch')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    if args.live == bool(args.input_index):
        parser.error('use exactly one of --live or --input-index')
    try:
        if args.live:
            index = create_fallback_index(fetch_exam_page(EXAM), exam_code=EXAM, min_items=3)
        else:
            index = json.loads(args.input_index.read_text(encoding='utf-8'))
        report = review_index(index)
        write_atomic(args.output, report)
        print(json.dumps({'status': report['status'],
                          'sampling': report['sampling'],
                          'metadata_warnings': len(report['metadata_warnings']),
                          'text_identity_reviews_needed': sum(not d['expected_subject_text_seen']
                              for item in report['checked'] for d in item['documents']),
                          'publication_allowed': False, 'scoring_enabled': False}, ensure_ascii=False))
        return 0
    except (OSError, ValueError, SourceFailure, DocumentQAError) as exc:
        # Never change the report on failure. Live check is a hard gate.
        print(f'DOCUMENT QA BLOCKED: {exc}; no candidate index or question answer modified', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
