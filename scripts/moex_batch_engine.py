#!/usr/bin/env python3
"""LexFlow V0.3 reusable, bounded MOEX PDF review *candidate* processor.

Works from any properly formatted MOEX document-link index (not a particular
exam year or subject). The index is untrusted input; neither subject metadata,
PDF readability nor apparent answers authorize scoring. A single paper failing
is isolated. The tool NEVER modifies the source index, app, user data or quiz.

Without --download-documents only a safe review plan is generated. Actual
network calls must be explicitly requested and are bounded by two limits.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import sys
import time
from urllib.parse import parse_qs, urlsplit
import urllib.request

from moex_document_qa import MAX_PDF_BYTES, DocumentQAError, validate_pdf_bytes
from moex_index import SourceFailure, write_atomic
from moex_page_fallback import (create_fallback_index, fetch_exam_page,
                                official_document_url, page_url)

FOCUS = ('民法', '刑法', '憲法')
MAX_PAPERS = 12
MAX_DOCUMENTS = 24
MAX_PREVIEW = 25
MAX_PDF_PAGES = 120
MAX_READABLE_TEXT = 250_000
SCHEMA = 'lexflow.moex.universal.batch.v1'
APPROVED_INDEX_STATES = {'index_only_unverified_answers', 'fallback_official_page_links_unverified'}


class BatchReviewError(ValueError):
    pass


def safe_official_ref(value: str, role: str) -> dict:
    """Exact Q/S/M identity when MOEX offers it; other MOEX HTTPS links stay unpaired.

    Unpaired links may be inspected as PDF sources, but their answer URLs are
    never automatically associated with that question or marked verified.
    """
    if not isinstance(value, str) or not value or len(value) > 2048 or role not in ('Q', 'S', 'M'):
        raise BatchReviewError('missing/oversized official document URL or unknown role')
    try:
        x = urlsplit(value)
        host = (x.hostname or '').lower()
        if (x.scheme != 'https' or x.username or x.password or x.port not in (None, 443)
            or x.fragment or not x.path or (host != 'moex.gov.tw' and not host.endswith('.moex.gov.tw'))):
            raise BatchReviewError('non-HTTPS or non-MOEX document URL')
        if x.path.lower() == '/exam/whandexamqanda_file.ashx':
            if host != 'wwwq.moex.gov.tw':
                raise BatchReviewError('MOEX Q/S/M endpoint is on an unexpected host')
            params = parse_qs(x.query, strict_parsing=True, keep_blank_values=True)
            code = params.get('code', [''])[0]
            if not re.fullmatch(r'\d{5,8}', code):
                raise BatchReviewError('invalid MOEX examination code')
            parsed = official_document_url(value, exam_code=code)
            if parsed is None or parsed[1] != role:
                raise BatchReviewError('wrong/invalid Q/S/M document format')
            return {'url': value, 'role': role, 'family': 'moex_qsm',
                    'identity': [code, *parsed[2]]}
        # A different official MOEX URL may occur in the CSV. It is NOT enough
        # to prove that a separate answer URL belongs to the question URL.
        if any(ord(ch) < 32 for ch in value):
            raise BatchReviewError('control character in official link')
        return {'url': value, 'role': role, 'family': 'moex_other_official', 'identity': None}
    except ValueError as exc:
        if isinstance(exc, BatchReviewError):
            raise
        raise BatchReviewError('invalid official document URL') from exc


def normalize_paper(item: dict) -> dict:
    if not isinstance(item, dict):
        raise BatchReviewError('malformed index paper')
    paper_id, subject = item.get('id'), item.get('subject')
    if (not isinstance(paper_id, str) or not 1 <= len(paper_id) <= 150
        or not isinstance(subject, str) or not 1 <= len(subject) <= 200):
        raise BatchReviewError('missing/oversized paper identity')
    focus = item.get('focus_subjects')
    if not isinstance(focus, list) or len(focus) > len(FOCUS) or any(v not in FOCUS for v in focus):
        raise BatchReviewError('invalid focus classification')
    year = str(item.get('year_roc', ''))
    if not re.fullmatch(r'\d{2,4}', year):
        raise BatchReviewError('invalid published year')
    question = safe_official_ref(item.get('question_url'), 'Q')
    if question['family'] == 'moex_qsm' and len(year) == 3 and not question['identity'][0].startswith(year):
        raise BatchReviewError('exam year and official Q URL code disagree')
    links = {'Q': question}
    for role, key in [('S', 'answer_url'), ('M', 'answer_correction_url')]:
        raw = item.get(key, '')
        if raw:
            ref = safe_official_ref(raw, role)
            if question['family'] == 'moex_qsm' and (
                ref['family'] != 'moex_qsm' or ref['identity'] != question['identity']
            ):
                raise BatchReviewError(f'Q/{role} exam, class, subject or session identity mismatch')
            links[role] = ref
    return {
        'id': paper_id, 'subject': subject, 'year_roc': year,
        'exam': str(item.get('exam', ''))[:200],
        'groups': [str(x)[:200] for x in item.get('groups', [])[:20]] if isinstance(item.get('groups', []), list) else [],
        'focus_subjects': list(dict.fromkeys(focus)),
        'classification': str(item.get('classification', 'needs_classification'))[:40],
        'links': links, 'question_type_label': str(item.get('question_type', ''))[:100],
        'pair_identity_confirmed': question['family'] == 'moex_qsm',
    }


def validate_index(index: dict) -> list[dict]:
    if (not isinstance(index, dict) or index.get('schema') != 'lexflow.moex.index.v1'
        or index.get('status') not in APPROVED_INDEX_STATES
        or not isinstance(index.get('items'), list)
        or not 1 <= len(index['items']) <= 150_000
        or any(not isinstance(x, dict) for x in index['items'])):
        raise BatchReviewError('missing, non-candidate or invalid MOEX index')
    return index['items']


def choose_representative(items: list[dict], max_papers: int) -> list[dict]:
    """One per field first, corrected mixed next, then extras. No named-paper constants."""
    if not 1 <= max_papers <= MAX_PAPERS:
        raise BatchReviewError('batch paper limit out of bounds')
    def score(v):
        return (0 if v.get('answer_correction_url') else 1,
                0 if v.get('answer_url') else 1,
                0 if v.get('classification') == 'subject_named' else 1,
                str(v.get('subject', '')), str(v.get('question_url', '')))
    # Do not choose more than one URL per batch (even if index IDs differ).
    ordered = sorted(items, key=score)
    chosen, urls = [], set()
    def add(p):
        url = p.get('question_url')
        if isinstance(url, str) and url not in urls and len(chosen) < max_papers:
            chosen.append(p); urls.add(url)
    for focus in FOCUS:
        for p in ordered:
            if focus in (p.get('focus_subjects') or []) and p.get('question_url') not in urls:
                add(p); break
    if len(chosen) < max_papers:
        for p in ordered:
            if p.get('classification') == 'mixed' and p.get('question_url') not in urls:
                add(p); break
    for p in ordered:
        add(p)
    return chosen


def identify_download_redirect(original: dict, redirected: str) -> None:
    after = safe_official_ref(redirected, original['role'])
    # A known Q/S/M link can be served with a different ordering of query
    # parameters. It may NOT redirect to a different paper/role or hostname.
    if (original['family'] != after['family'] or
        (original['identity'] is not None and original['identity'] != after['identity']) or
        (original['identity'] is None and original['url'] != after['url'])):
        raise BatchReviewError('unexpected official PDF redirect or changed document identity')


def fetch_pdf(ref: dict, *, timeout: int = 35) -> bytes:
    identify_download_redirect(ref, ref['url'])
    request = urllib.request.Request(ref['url'], headers={
        'User-Agent': 'LexFlow/0.3 (bounded official source document verification)',
        'Accept': 'application/pdf,application/octet-stream;q=0.8,*/*;q=0.2',
    })
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            identify_download_redirect(ref, response.geturl())
            size = response.headers.get('Content-Length')
            if size and int(size) > MAX_PDF_BYTES:
                raise BatchReviewError('oversized official PDF')
            blob = response.read(MAX_PDF_BYTES + 1)
    except (OSError, TimeoutError, ValueError) as exc:
        if isinstance(exc, BatchReviewError):
            raise
        raise BatchReviewError('official PDF fetch failed: ' + type(exc).__name__) from exc
    try:
        validate_pdf_bytes(blob)
    except DocumentQAError as exc:
        raise BatchReviewError(str(exc)) from exc
    return blob


def raw_question_previews(text: str) -> dict:
    """Extract ONLY tentative fragments if a full monotone numbering run exists.

    Question body and options remain unverified. No OCR and no inferred answers.
    """
    if not text.strip():
        return {'status': 'no_extractable_text_or_scan', 'count': 0, 'samples': []}
    if len(text) > MAX_READABLE_TEXT:
        return {'status': 'text_exceeds_review_limit', 'count': 0, 'samples': []}
    hits = [(int(m.group(1)), m.start()) for m in re.finditer(
        r'(?m)^[ \t\u3000]*(\d{1,3})[ \t\u3000]+', text)
        if 1 <= int(m.group(1)) <= 200]
    runs = []
    for i, (number, _) in enumerate(hits):
        if number != 1:
            continue
        end = i + 1
        while end < len(hits) and hits[end][0] == hits[end - 1][0] + 1:
            end += 1
        if end - i >= 3:
            runs.append(hits[i:end])
    if not runs:
        return {'status': 'no_confident_sequential_numbering', 'count': 0, 'samples': []}
    run = max(runs, key=len)
    if sum(len(r) == len(run) for r in runs) > 1:
        return {'status': 'ambiguous_numbered_sections', 'count': 0, 'samples': []}
    rows = []
    for i, (n, offset) in enumerate(run[:MAX_PREVIEW]):
        stop = run[i + 1][1] if i + 1 < len(run) else min(len(text), offset + 2000)
        excerpt = text[offset:stop].strip()
        if not 12 <= len(excerpt) <= 3500:
            return {'status': 'unreliable_question_spans', 'count': 0, 'samples': []}
        rows.append({'number': n, 'raw_excerpt_unreviewed': excerpt[:1400]})
    return {'status': 'numbered_text_fragments_REQUIRE_REVIEW',
            'count': len(run), 'samples': rows}


def inspect_pdf_source(blob: bytes, role: str, expected_subject: str) -> dict:
    """Structure + human-review preview, never authoritative question extraction."""
    try:
        validate_pdf_bytes(blob)
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(blob), strict=False)
        count = len(reader.pages)
        if not 1 <= count <= MAX_PDF_PAGES:
            raise BatchReviewError('implausible official PDF page count')
        body = '\n'.join((page.extract_text() or '') for page in reader.pages[: min(count, 20)])
    except (DocumentQAError, ImportError, ValueError, OSError) as exc:
        raise BatchReviewError('unreadable/truncated PDF or missing PDF parser') from exc
    except Exception as exc:
        raise BatchReviewError('unexpected PDF extraction error: ' + type(exc).__name__) from exc
    match = re.sub(r'\s+', '', expected_subject) in re.sub(r'\s+', '', body)
    result = {'pages': count, 'bytes': len(blob), 'sha256': hashlib.sha256(blob).hexdigest(),
              'expected_subject_label_seen': match, 'pdf_structure_readable': True,
              'content_and_options_verified': False, 'final_answer_verified': False}
    if role == 'Q':
        result['question_preview'] = raw_question_previews(body)
    else:
        # S/M PDFs can contain correction or credit-all/special-score rules;
        # never mechanically associate a letter with a question number here.
        result['answer_preview_status'] = 'official_document_requires_answer_and_correction_review'
    return result


def process_batch(index: dict, *, max_papers: int = 4, max_documents: int = 9,
                  download: bool = False, require_all: bool = False,
                  fetch=fetch_pdf, inspect=inspect_pdf_source,
                  pause_seconds: float = 0.0,
                  extract_questions: bool = False,
                  min_question_candidates: int = 0,
                  enrich=None) -> dict:
    source = validate_index(index)
    if extract_questions and not download:
        raise BatchReviewError('question and answer extraction requires actual PDF downloads')
    if not isinstance(min_question_candidates, int) or not 0 <= min_question_candidates <= 100:
        raise BatchReviewError('invalid minimum question candidate count')
    if min_question_candidates and not extract_questions:
        raise BatchReviewError('minimum question count requires candidate extraction mode')
    if extract_questions and enrich is None:
        from moex_question_pipeline import make_question_answer_review
        enrich = make_question_answer_review
    if not 1 <= max_documents <= MAX_DOCUMENTS:
        raise BatchReviewError('document limit out of bounds')
    selected = choose_representative(source, max_papers)
    if not selected:
        raise BatchReviewError('no selected official-source index papers')
    results, downloaded, failures, succeeded = [], 0, 0, 0
    for original in selected:
        try:
            p = normalize_paper(original)
            result = {'id': p['id'], 'exam': p['exam'], 'year_roc': p['year_roc'],
                      'subject': p['subject'], 'focus_subjects': p['focus_subjects'],
                      'classification': p['classification'], 'groups_unverified': p['groups'],
                      'question_type_label_unverified': p['question_type_label'],
                      'source_link_identity_confirmed': p['pair_identity_confirmed'],
                      'original_index_id': p['id'], 'documents': [], 'warnings': [],
                      'question_content_verified': False, 'options_verified': False,
                      'answer_verified_final': False, 'legal_explanation_verified': False,
                      'eligible_for_scoring': False}
            if (p['classification'] in ('mixed', 'needs_classification')
                or any(word in p['subject'] for word in ('英文', '綜合', '法學知識'))):
                result['warnings'].append('mixed_or_unclassified_paper_not_entirely_one_legal_field')
            if 'M' in p['links']:
                result['warnings'].append('official_correction_present_requires_manual_application')
                if 'S' not in p['links']:
                    result['warnings'].append('correction_without_standard_answer_requires_review')
            if not p['pair_identity_confirmed'] and len(p['links']) > 1:
                result['warnings'].append('general_CSV_links_cannot_prove_answer_pair_identity')
            if not download:
                result['state'] = 'planned_no_download'
                result['planned_document_roles'] = list(p['links'])
                results.append(result)
                succeeded += 1
                continue
            complete_document_sample = True
            validated_pdf_blobs = {} if extract_questions else None
            for role, ref in p['links'].items():
                # In generic CSV links, a PDF link on an official host does not
                # establish that the given answer belongs to this question.
                if role != 'Q' and not p['pair_identity_confirmed']:
                    result['warnings'].append(f'{role}_document_skipped_unproven_identity')
                    complete_document_sample = False
                    continue
                if downloaded >= max_documents:
                    result['warnings'].append('batch_document_budget_exhausted')
                    complete_document_sample = False
                    break
                downloaded += 1  # attempts bounded even if a fetch raises
                try:
                    pdf_bytes = fetch(ref)
                    doc = inspect(pdf_bytes, role, p['subject'])
                    if not isinstance(doc, dict) or not doc.get('pdf_structure_readable'):
                        raise BatchReviewError('PDF did not pass structural inspection')
                    if extract_questions:
                        validated_pdf_blobs[role] = pdf_bytes
                    result['documents'].append({'role': role, 'url': ref['url'], **doc,
                                                'content_and_options_verified': False,
                                                'final_answer_verified': False,
                                                'question_text_verified': False,
                                                'legal_explanation_verified': False,
                                                'eligible_for_scoring': False})
                    if not doc.get('expected_subject_label_seen'):
                        result['warnings'].append(f'{role}_subject_label_requires_manual_review')
                except (OSError, ValueError, RuntimeError) as exc:
                    failures += 1
                    result['warnings'].append(f'{role}_source_failed_{type(exc).__name__}')
                    result.setdefault('errors', []).append({'role': role,
                        'reason': str(exc)[:180]})
                if pause_seconds:
                    time.sleep(pause_seconds)
            question_readable = 'Q' in {d['role'] for d in result['documents']}
            if extract_questions:
                try:
                    if not question_readable:
                        raise BatchReviewError('question PDF was not readable')
                    review = enrich(validated_pdf_blobs,
                                    expected_subject=p['subject'],
                                    identity_paired=p['pair_identity_confirmed'])
                    if (not isinstance(review, dict)
                        or review.get('schema') != 'lexflow.moex.question.candidates.v1'
                        or review.get('publication_allowed') is not False
                        or review.get('scoring_enabled') is not False
                        or not isinstance(review.get('questions'), list)):
                        raise BatchReviewError('candidate extraction schema or nonpublication gate invalid')
                    # Enforce flags at the integration boundary too. Neither
                    # a faulty plug-in nor a future parser can enable scoring.
                    for candidate in review['questions']:
                        if not isinstance(candidate, dict):
                            raise BatchReviewError('invalid individual extraction candidate')
                        for protected in ('eligible_for_scoring', 'question_text_verified',
                                          'options_verified', 'final_answer_verified',
                                          'correction_applied', 'legal_explanation_verified'):
                            candidate[protected] = False
                    for protected in ('publication_allowed', 'scoring_enabled',
                                      'final_answer_verified', 'special_scoring_applied',
                                      'question_text_and_options_verified'):
                        review[protected] = False
                    result['question_answer_candidates'] = review
                    if review.get('candidate_question_count', 0) < min_question_candidates:
                        result['warnings'].append('too_few_extracted_four_choice_candidates')
                        complete_document_sample = False
                except (OSError, ValueError, RuntimeError, ImportError) as exc:
                    result['warnings'].append('question_answer_extraction_isolated')
                    result['extraction_failure'] = type(exc).__name__ + ': ' + str(exc)[:180]
                    complete_document_sample = False
                finally:
                    validated_pdf_blobs.clear()  # do not persist raw PDF bytes
            result['state'] = ('pdfs_readable_CONTENT_NOT_VERIFIED'
                if question_readable and not result.get('errors') and complete_document_sample
                else 'isolated_needs_review')
            if question_readable and not result.get('errors'):
                # An inspectable Q PDF is a useful partial result even when an
                # unpaired CSV answer must remain in the human review queue.
                succeeded += 1
            elif not result.get('errors'):
                failures += 1
            results.append(result)
        except (OSError, ValueError) as exc:
            failures += 1
            results.append({'id': str(original.get('id', 'invalid'))[:150] if isinstance(original, dict) else 'invalid',
                            'state': 'isolated_invalid_paper', 'reason': str(exc)[:180],
                            'eligible_for_scoring': False})
    if not succeeded:
        raise BatchReviewError('no paper passed planning/PDF inspection; old report kept')
    if require_all and (failures or any(x['state'] != 'pdfs_readable_CONTENT_NOT_VERIFIED' for x in results)):
        raise BatchReviewError('strict smoke test: a selected paper or PDF failed; old report kept')
    summary = {'total_source_index_papers': len(source), 'selected_papers': len(selected),
               'completed_review_plans_or_pdfs': succeeded,
               'document_fetch_attempts': downloaded, 'download_or_validation_errors': failures,
               'isolated_papers': sum(x['state'].startswith('isolated_') for x in results),
               'focus_coverage': {x: sum(x in p.get('focus_subjects', [])
                                        for p in results) for x in FOCUS}}
    if extract_questions:
        extracts = [item.get('question_answer_candidates', {}) for item in results]
        summary['candidate_question_pipeline'] = {
            'four_option_candidacies': sum(int(x.get('candidate_question_count', 0)) for x in extracts),
            'published_standard_key_pairs': sum(int(x.get('candidate_answer_pair_count', 0)) for x in extracts),
            'papers_needing_extraction_review': sum(
                not x or x.get('candidate_question_count', 0) < min_question_candidates
                for x in extracts),
            'question_and_answer_content_verified': False,
            'final_scoring_enabled': False,
        }
    review_queue = [
        {'id': item.get('id', 'invalid'), 'state': item['state'],
         'reasons': ['question_text_options_and_final_answer_not_verified',
                     *item.get('warnings', []),
                     *[e['reason'] for e in item.get('errors', [])]]}
        for item in results
    ]
    return {'schema': SCHEMA, 'status': ('bounded_pdf_review_not_a_scored_bank' if download
                                      else 'review_plan_only_no_download'),
            'source_method': index.get('source', {}).get('method', 'official_moex_csv'),
            'summary': summary, 'reviewed_items': results,
            'manual_review_queue': review_queue,
            'publication_allowed': False, 'scoring_enabled': False,
            'all_answers_verified': False, 'all_question_text_verified': False,
            'correction_and_special_scoring_applied': False,
            'disclaimer': '跨科目批次來源檢查與候審預覽；即使 PDF 可讀，也未核對完整題幹選項、答案更正或法律詳解，不能作為計分題庫。'}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    choice = ap.add_mutually_exclusive_group(required=True)
    choice.add_argument('--input-index', type=Path, help='existing MOEX candidate JSON, any exam year')
    choice.add_argument('--live-exam', help='approved MOEX exam page code (read-only)')
    ap.add_argument('--max-papers', type=int, default=4)
    ap.add_argument('--max-documents', type=int, default=9)
    ap.add_argument('--download-documents', action='store_true', help='opt in to bounded official PDF downloads')
    ap.add_argument('--require-all', action='store_true', help='fail CI when any chosen source fails')
    ap.add_argument('--extract-questions', action='store_true',
                    help='emit unverified question/answer candidates from fetched PDFs')
    ap.add_argument('--min-choice-candidates-per-paper', type=int, default=0,
                    help='optional hard quality gate for question extraction (CI only)')
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args(argv)
    if args.require_all and not args.download_documents:
        ap.error('--require-all requires --download-documents')
    if args.extract_questions and not args.download_documents:
        ap.error('--extract-questions requires --download-documents')
    if args.input_index and args.input_index.resolve() == args.output.resolve():
        ap.error('cannot overwrite the source index')
    if args.output.name in {'moex_official_index.json', 'moex_official_fallback.json'}:
        ap.error('candidate index is not a review report destination')
    try:
        if args.live_exam:
            # An explicit allowlist is used for source-page discovery until
            # individual exam pages for other years are independently approved.
            index = create_fallback_index(fetch_exam_page(args.live_exam),
                                          exam_code=args.live_exam, min_items=3)
        else:
            index = json.loads(args.input_index.read_text(encoding='utf-8'))
        report = process_batch(index, max_papers=args.max_papers,
                               max_documents=args.max_documents,
                               download=args.download_documents,
                               require_all=args.require_all,
                               pause_seconds=0.25 if args.download_documents else 0,
                               extract_questions=args.extract_questions,
                               min_question_candidates=args.min_choice_candidates_per_paper)
        write_atomic(args.output, report)
        print(json.dumps({'status': report['status'], **report['summary'],
                          'publication_allowed': False, 'scoring_enabled': False}, ensure_ascii=False))
        return 0
    except (BatchReviewError, OSError, ValueError, SourceFailure) as exc:
        print('UNIVERSAL BATCH BLOCKED: ' + str(exc)[:300] + '; existing files untouched', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
