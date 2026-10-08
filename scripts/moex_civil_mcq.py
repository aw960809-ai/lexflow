#!/usr/bin/env python3
"""Stage the *published* 114 judicial civil-law MCQ answer keys for review.

This does NOT convert an answer sheet into a scored question bank. Only exact,
previously inspected official PDF byte snapshots are accepted. The individual
stems/options, later answer corrections, article citations and explanations
remain unverified, and all generated rows are explicitly non-scoring.

Provenance: MOEX 114120, 司法四等民法概要, test code 2201; each source is
an official document link with c=201, q=1, s=0405, t=Q/S. The published
answer table was read from its original official PDF page (not guessed by AI).
"""
from __future__ import annotations
import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import sys

from moex_document_qa import download_pdf, inspect_pdf, DocumentQAError
from moex_index import write_atomic
from moex_page_fallback import official_document_url

EXAM = '114120'
QUESTION_URL = 'https://wwwq.moex.gov.tw/exam/wHandExamQandA_File.ashx?t=Q&code=114120&c=201&s=0405&q=1'
ANSWER_URL = 'https://wwwq.moex.gov.tw/exam/wHandExamQandA_File.ashx?t=S&code=114120&c=201&s=0405&q=1'
QUESTION_SHA256 = 'f57cbcd55d4dc1e7fa9c0b0c8e6bc0ef264e17d7573531aa513eb093fe41fc89'
ANSWER_SHA256 = '18e2b4e83dece0763568b5daa59000fb78a14e8def9eb7558672416b5f923ce7'
# Verbatim official published letters transcribed from the MOEX 2201 answer PDF
# (table rows 1-10, 11-20, 21-25). Not proof of absence of later corrections.
PUBLISHED_ANSWERS = tuple('ABAADDBACACBDDBBDDCCBBABC')
assert len(PUBLISHED_ANSWERS) == 25


class McqCandidateError(ValueError):
    pass


def verify_source_keys(question_url: str, answer_url: str) -> None:
    q = official_document_url(question_url, exam_code=EXAM)
    a = official_document_url(answer_url, exam_code=EXAM)
    if not q or not a or q[1] != 'Q' or a[1] != 'S' or q[2] != a[2] or q[2] != ('201', '1', '0405'):
        raise McqCandidateError('official question and standard-answer source identity mismatch')


def verify_pdf_metadata(q: dict, a: dict) -> None:
    if q.get('sha256') != QUESTION_SHA256 or a.get('sha256') != ANSWER_SHA256:
        raise McqCandidateError('official PDF bytes differ from independently reviewed snapshots; reverify before updating keys')
    if q.get('pages') != 4 or a.get('pages') != 1:
        raise McqCandidateError('unexpected official PDF page count')
    if not q.get('expected_subject_text_seen') or not a.get('expected_subject_text_seen'):
        raise McqCandidateError('subject identity not found in PDF text')


def collect_unverified_excerpts(question_pdf: bytes) -> tuple[dict[int, str], str]:
    """Optional raw extraction for later human/source QA; never enough for scoring.

    PDF reading order can misplace options. Only keep bounded spans where all
    number headings appear; otherwise return no excerpts rather than guess.
    """
    try:
        from pypdf import PdfReader
        pdf = PdfReader(io.BytesIO(question_pdf), strict=False)
        if len(pdf.pages) != 4:
            return {}, 'pdf_pages_unexpected'
        content = '\n'.join(p.extract_text() or '' for p in pdf.pages[1:])
        # Header/seat numbers are not question numbers; require leading digit on a line.
        hits = list(re.finditer(r'(?m)^\s*(\d{1,2})[ \t\u3000]+', content))
        hits = [(int(m.group(1)), m.start()) for m in hits if 1 <= int(m.group(1)) <= 25]
        if [n for n, _ in hits] != list(range(1, 26)):
            return {}, 'number_or_reading_order_requires_review'
        result = {}
        for pos, (n, start) in enumerate(hits):
            end = hits[pos + 1][1] if pos + 1 < len(hits) else len(content)
            excerpt = content[start:end].strip()
            if not 15 <= len(excerpt) <= 3500:
                return {}, 'question_spans_require_review'
            result[n] = excerpt
        return result, 'raw_pdf_text_requires_option_by_option_review'
    except Exception:
        # Preview extraction is always optional; no arbitrary text becomes scored.
        return {}, 'pdf_text_extraction_unavailable'


def build_candidate(*, question_pdf: bytes, answer_pdf: bytes,
                    inspect=inspect_pdf, excerpts=collect_unverified_excerpts) -> dict:
    verify_source_keys(QUESTION_URL, ANSWER_URL)
    q_meta = inspect(question_pdf, expected='民法概要')
    a_meta = inspect(answer_pdf, expected='民法概要')
    verify_pdf_metadata(q_meta, a_meta)
    raw, extract_status = excerpts(question_pdf)
    entries = []
    for number, published_letter in enumerate(PUBLISHED_ANSWERS, 1):
        entries.append({
            'id': f'moex-114120-civil-2201-q{number:02d}', 'number': number,
            'published_standard_answer': published_letter,
            'answer_status': 'published_standard_pdf_snapshot_matched_NOT_confirmed_final',
            'question_pdf_url': QUESTION_URL, 'answer_pdf_url': ANSWER_URL,
            'raw_pdf_excerpt_unreviewed': raw.get(number, ''),
            'question_text_verified': False,
            'options_verified': False,
            'later_correction_checked': False,
            'legal_explanation_verified': False,
            'eligible_for_scoring': False,
        })
    return {
        'schema': 'lexflow.moex.civil.114120.answer-candidate.v1',
        'status': 'published_answer_pdf_checked_question_text_and_finality_pending',
        'exam': '114年司法特考四等',
        'exam_code': EXAM, 'official_subject': '民法概要',
        'subject_test_code': '2201', 'exam_classes_from_pdf': ['法院書記官','執達員','執行員'],
        'question_pdf': {'url': QUESTION_URL, **q_meta},
        'answer_pdf': {'url': ANSWER_URL, **a_meta},
        'question_count': 25, 'question_kind': 'single_choice',
        'answer_worksheet_per_question_points': 2,
        'answer_capture_method': 'official published answer PDF table manually transcribed and exact SHA256-pinned',
        'question_text_extraction_status': extract_status,
        'exam_wide_answer_and_corrections_review': 'not_completed',
        'source_review': 'requires_independent_source_and_legal_checks',
        'publication_allowed': False, 'scoring_enabled': False,
        'items': entries,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--live', action='store_true', help='download exactly two pinned MOEX Q/S PDFs')
    ap.add_argument('--question-file', type=Path)
    ap.add_argument('--answer-file', type=Path)
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args(argv)
    if not (args.live ^ bool(args.question_file and args.answer_file)):
        ap.error('choose --live or both --question-file and --answer-file')
    try:
        q = download_pdf(QUESTION_URL, 'Q') if args.live else args.question_file.read_bytes()
        s = download_pdf(ANSWER_URL, 'S') if args.live else args.answer_file.read_bytes()
        candidate = build_candidate(question_pdf=q, answer_pdf=s)
        write_atomic(args.output, candidate)
        print(json.dumps({'status': candidate['status'], 'question_count': len(candidate['items']),
                          'excerpt_status': candidate['question_text_extraction_status'],
                          'scoring_enabled': False, 'publication_allowed': False},ensure_ascii=False))
        return 0
    except (OSError, ValueError, DocumentQAError, McqCandidateError) as exc:
        print(f'BLOCKED: civil published-answer candidate could not be verified: {exc}; output unchanged',file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
