#!/usr/bin/env python3
"""Conservative, reusable MOEX PDF question/answer CANDIDATE extraction.

A recognisable printed question or answer IS NOT a verified/scored question.
This module reads official PDF text only after the existing batch engine has
validated link origins, paper identities, PDF bytes, and download limits.

Important fail-closed design:
- Four visible options must appear exactly once in A,B,C,D order.
- Numbering must be one unambiguous consecutive run; detect page footers.
- Standard answers (S) are provisional and never assumed to be final.
- Corrections (M) are not auto-applied; special credits remain for review.
- No guessed missing answers and no scoring/publishing, ever.
- Does not fetch URLs, create files, or mutate existing LexFlow data.
"""
from __future__ import annotations

import io
import re
import unicodedata

GLYPH_TO_LETTER = {'\ue18c': 'A', '\ue18d': 'B', '\ue18e': 'C', '\ue18f': 'D'}
GLYPH_RE = re.compile('[' + ''.join(GLYPH_TO_LETTER) + ']')
PAREN_RE = re.compile(r'（([A-D])）|\(([A-D])\)')
HEADING = re.compile(r'(?m)^[ \t\u3000]*(\d{1,3})[ \t\u3000]+(?=\S)')
Q_LABEL = re.compile(r'第\s*(\d{1,3})\s*題')
MAX_QUESTIONS = 100
MAX_QUESTION_RAW = 3500
MAX_EXCERPT = 1400
FOOTER = re.compile(r'(?m)^\s*(?:代\s*號|頁\s*次)\s*[:：]')
SPECIAL_CREDIT = re.compile(r'一律給分|均予給分|全部給分|皆予給分|送分|複數答案|多重答案|不予計分|不計分')


class QuestionExtractionError(ValueError):
    """A candidate cannot be parsed safely; callers should isolate this paper."""


def _tight(text: str) -> str:
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', text or ''))


def _count_questions(text: str) -> int | None:
    matches = set(int(x) for x in re.findall(r'(?:共\s*|單選題數\s*[:：]\s*)(\d{1,3})\s*題', text))
    if len(matches) != 1:
        return None
    count = matches.pop()
    return count if 1 <= count <= MAX_QUESTIONS else None


def _unambiguous_run(text: str) -> list[tuple[int, int, int]]:
    """Return longest, unique sequence 1..N with line-anchored number markers."""
    headings = [(int(m.group(1)), m.start(), m.end()) for m in HEADING.finditer(text)
                if 1 <= int(m.group(1)) <= MAX_QUESTIONS]
    runs = []
    for i, (number, _, _) in enumerate(headings):
        if number != 1:
            continue
        j = i + 1
        while j < len(headings) and headings[j][0] == headings[j - 1][0] + 1:
            j += 1
        if j - i >= 1:
            runs.append(headings[i:j])
    if not runs:
        return []
    longest = max(map(len, runs))
    ties = [r for r in runs if len(r) == longest]
    return ties[0] if len(ties) == 1 else []


def split_question_text(text: str, *, expected_count: int | None = None) -> dict:
    """Recognise numbered PDF question fragments and map MOEX option glyphs.

    Only produces UNVERIFIED candidates; never a normalized scored quiz.
    An inferred section might be incomplete: its completeness is flagged.
    """
    if not isinstance(text, str) or len(text) > 400_000:
        raise QuestionExtractionError('unusable or oversized PDF text')
    # Skip preceding long essay problems if the official paper contains both.
    section = re.search(r'乙\s*[、.．]\s*測驗題', text)
    mcq_text = text[section.end():] if section else text
    declared = _count_questions(mcq_text)
    if expected_count is not None:
        if not isinstance(expected_count, int) or not 1 <= expected_count <= MAX_QUESTIONS:
            raise QuestionExtractionError('invalid declared question count')
        if declared is not None and declared != expected_count:
            # Disagreement is explicit; still preview the source, but fail the
            # numbering gate so it can never be accepted as a whole paper.
            conflicting_count = True
        else:
            conflicting_count = False
        declared = expected_count
    else:
        conflicting_count = False
    runs = _unambiguous_run(mcq_text)
    rows = []
    for i, (number, start, content_start) in enumerate(runs):
        end = runs[i + 1][1] if i + 1 < len(runs) else len(mcq_text)
        raw = mcq_text[start:end].strip()
        body = mcq_text[content_start:end].strip()
        issues = []
        glyph_marks = list(GLYPH_RE.finditer(body))
        parenthesized_marks = list(PAREN_RE.finditer(body))
        if glyph_marks and parenthesized_marks:
            marks, letters = [], []
            issues.append('mixed_option_marker_styles_are_ambiguous')
        elif glyph_marks:
            marks = glyph_marks
            letters = [GLYPH_TO_LETTER[x.group(0)] for x in marks]
        else:
            marks = parenthesized_marks
            letters = [x.group(1) or x.group(2) for x in marks]
        if letters != ['A', 'B', 'C', 'D']:
            issues.append('four_unique_options_not_detected_in_order')
        if FOOTER.search(body):
            issues.append('page_header_or_footer_inside_question')
        if not 10 <= len(body) <= MAX_QUESTION_RAW:
            issues.append('question_text_length_outside_review_range')
        stem = body[:marks[0].start()].strip() if marks else ''
        options = {}
        if letters == ['A', 'B', 'C', 'D']:
            for j, mark in enumerate(marks):
                stop = marks[j + 1].start() if j + 1 < len(marks) else len(body)
                option = body[mark.end():stop].strip()
                if not 1 <= len(option) <= 1800:
                    issues.append('empty_or_oversized_option')
                options[letters[j]] = option[:1800]
        if len(stem) < 4:
            issues.append('missing_question_stem')
        # Strip neither punctuation nor trailing lines: precise fidelity must
        # be checked against the source PDF image before student use.
        if len(raw) > MAX_QUESTION_RAW:
            issues.append('raw_fragment_exceeds_review_limit')
        rows.append({
            'number': number,
            'candidate_status': ('four_options_extracted_NEEDS_VISUAL_REVIEW' if not issues
                                 else 'isolated_question_fragment_NEEDS_REVIEW'),
            'stem_unverified': stem[:MAX_EXCERPT],
            'options_unverified': options if letters == ['A', 'B', 'C', 'D'] else {},
            'raw_pdf_excerpt_unverified': raw[:MAX_EXCERPT],
            'review_reasons': sorted(set(issues)),
            'question_text_verified': False, 'options_verified': False,
            'eligible_for_scoring': False,
        })
    complete = bool(rows and declared is not None and len(rows) == declared
                    and not conflicting_count and [x['number'] for x in rows] == list(range(1, declared + 1)))
    valid = sum(x['candidate_status'].startswith('four_options_extracted') for x in rows)
    return {
        'status': 'question_fragments_unverified',
        'expected_question_count': declared,
        'observed_sequential_numbers': len(rows),
        'count_matches_declared': complete,
        'four_option_candidates': valid,
        'requires_review_count': len(rows) - valid,
        'question_text_and_options_verified': False,
        'items': rows,
        'warnings': (['question_count_conflict'] if conflicting_count else []) +
                    ([] if complete else ['question_count_or_numbering_requires_review']),
    }


def parse_answer_table_text(texts: list[str], *, expected_count: int | None) -> dict:
    """Extract S (published standard) letters only from unambiguous tables.

    The PDF may use a visual grid with an extraction order that loses columns.
    In that case, DO NOT turn adjacent token streams into a guessed answer key.
    Extraction order/geometry ambiguity => zero proposed keys.
    """
    if not isinstance(texts, list) or not all(isinstance(t, str) for t in texts):
        raise QuestionExtractionError('invalid answer page text')
    if expected_count is None or not 1 <= expected_count <= MAX_QUESTIONS:
        return {'status': 'answer_count_unconfirmed_NEEDS_REVIEW', 'published_candidates': [],
                'review_reasons': ['missing_trusted_question_count'], 'final_answer_verified': False}
    collected = []
    special = False
    for text in texts:
        if len(text) > 200_000:
            continue
        special |= bool(SPECIAL_CREDIT.search(text))
        declared = _count_questions(text)
        if declared is not None and declared != expected_count:
            return {'status': 'answer_count_conflict_NEEDS_REVIEW', 'published_candidates': [],
                    'review_reasons': ['published_answer_count_disagrees_with_question_pdf'],
                    'special_scoring_mentioned': special, 'final_answer_verified': False}
        # Format A: explicit individually paired entries (not just one global
        # sequence of A/B/C/D letters, which loses row/column association).
        inline = re.findall(r'第\s*(\d{1,3})\s*題\s*[:：=｜|]?\s*([A-D])(?=\s|$|[、，,。])', text)
        if inline:
            pairs = [(int(n), a) for n, a in inline]
            if len(set(n for n, _ in pairs)) == len(pairs):
                collected.append(dict(pairs))
        # Format B: each grid is exactly two adjacent lines, labelled 題號 and
        # 答案, and the answer cell count exactly equals the numbered columns.
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        row_keys = {}
        for i, line in enumerate(lines[:-1]):
            nums = [int(n) for n in Q_LABEL.findall(line)]
            if not 2 <= len(nums) <= 20 or nums != list(range(nums[0], nums[0] + len(nums))):
                continue
            if '題號' not in line and not re.match(r'^第\s*\d+\s*題', line):
                continue
            next_line = lines[i + 1]
            if not next_line.startswith('答案'):
                continue
            tail = re.sub(r'^答案\s*[:：]?\s*', '', next_line)
            # Require spaced A-D tokens, with no other glyphs; disallow mashed
            # letter strings such as 'ABAAD' whose cell boundaries are unknown.
            cells = tail.split()
            if len(cells) == len(nums) and all(v in 'ABCD' and len(v) == 1 for v in cells):
                for n, a in zip(nums, cells):
                    if n in row_keys and row_keys[n] != a:
                        row_keys.clear()
                        break
                    row_keys[n] = a
        if row_keys:
            collected.append(row_keys)
    if not collected:
        return {'status': 'answer_table_layout_ambiguous_NEEDS_REVIEW', 'published_candidates': [],
                'review_reasons': ['answer_pdf_table_has_no_reliably_paired_number_letter_cells'],
                'special_scoring_mentioned': special, 'final_answer_verified': False}
    # Never combine two uncertain alternative extraction modes to fabricate a
    # complete sheet. Take the most complete single parse, and require other
    # parses to agree on every shared question number.
    candidate = max(collected, key=lambda m: len(m))
    for other in collected:
        if any(candidate.get(n) is not None and candidate[n] != a for n, a in other.items()):
            return {'status': 'answer_table_conflicting_read_orders_NEEDS_REVIEW',
                    'published_candidates': [], 'review_reasons': ['conflicting_number_letter_pairs'],
                    'special_scoring_mentioned': special, 'final_answer_verified': False}
    # The official answer layout may have 100 empty columns; include only the
    # expected answered range, with no missing or extra out-of-range keys.
    if set(candidate) != set(range(1, expected_count + 1)):
        return {'status': 'incomplete_answer_table_NEEDS_REVIEW', 'published_candidates': [],
                'review_reasons': [f'found_{len(candidate)}_of_{expected_count}_published_answers'],
                'special_scoring_mentioned': special, 'final_answer_verified': False}
    if special:
        return {'status': 'special_scoring_detected_NEEDS_REVIEW', 'published_candidates': [],
                'review_reasons': ['special_scoring_language_requires_independent_application'],
                'special_scoring_mentioned': True, 'final_answer_verified': False}
    return {'status': 'published_standard_letter_candidates_NOT_FINAL',
            'published_candidates': [{'number': n, 'published_standard_candidate': candidate[n]}
                                     for n in range(1, expected_count + 1)],
            'review_reasons': ['final_corrections_and_special_credit_not_verified'],
            'special_scoring_mentioned': False, 'final_answer_verified': False}


def _get_pdf_texts(blob: bytes) -> tuple[str, str]:
    # The pinned GitHub PDF QA installs pypdf 5.9.0 in a temporary venv.
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(blob), strict=False)
    if not 1 <= len(reader.pages) <= 120:
        raise QuestionExtractionError('unexpected PDF page count')
    plain = '\n'.join(page.extract_text() or '' for page in reader.pages[:20])
    # PDF layout mode is an alternative candidate view, not additional evidence
    # to assume a key; disagreements cause fail-closed in parse_answer_table_text.
    try:
        layout = '\n'.join(page.extract_text(extraction_mode='layout') or '' for page in reader.pages[:20])
    except Exception:
        layout = ''
    return plain, layout


def _subject_evidence(expected: str, text: str) -> str:
    """Compare source title conservatively, allowing an unverified parenthetical.

    Q/S identity is already validated by the caller. A common source can use
    ASCII/fullwidth brackets or omit a long parenthetical in its title. That
    must not be reported as a fully identical subject label.
    """
    if _tight(expected) and _tight(expected) in _tight(text):
        return 'full_printed_subject_name_matched'
    prefix = re.split(r'[（(]', expected, maxsplit=1)[0]
    if len(_tight(prefix)) >= 5 and _tight(prefix) in _tight(text):
        return 'subject_name_prefix_only_PARENTHESES_REQUIRE_REVIEW'
    raise QuestionExtractionError('published subject label absent from PDF text')


def make_question_answer_review(pdf_documents: dict[str, bytes], *,
                                expected_subject: str, identity_paired: bool) -> dict:
    """Bridge Q/S/M bytes to a non-scoring candidate report for one paper."""
    if not isinstance(pdf_documents, dict) or not isinstance(expected_subject, str):
        raise QuestionExtractionError('invalid document payload')
    if 'Q' not in pdf_documents:
        raise QuestionExtractionError('no official question PDF in paper review')
    q_plain, _ = _get_pdf_texts(pdf_documents['Q'])
    question_subject_evidence = _subject_evidence(expected_subject, q_plain)
    answer_subject_evidence = None
    question = split_question_text(q_plain)
    expected = question['expected_question_count']
    answer = {'status': 'no_proven_paired_standard_answer', 'published_candidates': [],
              'review_reasons': ['official_answer_pdf_missing_or_unpaired'], 'final_answer_verified': False}
    if 'S' in pdf_documents:
        if not identity_paired:
            raise QuestionExtractionError('unpaired answer document cannot create mapped keys')
        s_plain, s_layout = _get_pdf_texts(pdf_documents['S'])
        answer_subject_evidence = _subject_evidence(expected_subject, s_plain)
        answer = parse_answer_table_text([s_layout, s_plain], expected_count=expected)
    correction = {'status': 'corrections_not_proven_absent', 'detected': False,
                  'special_scoring_mentioned': False, 'correction_applied': False}
    if 'M' in pdf_documents:
        if not identity_paired:
            raise QuestionExtractionError('unpaired correction document cannot be mapped')
        m_plain, _ = _get_pdf_texts(pdf_documents['M'])
        correction = {'status': 'official_correction_document_present_REQUIRES_REVIEW',
                      'detected': True, 'special_scoring_mentioned': bool(SPECIAL_CREDIT.search(m_plain)),
                      'correction_applied': False}
    by_num = {p['number']: p['published_standard_candidate'] for p in answer['published_candidates']}
    qrows = []
    for row in question['items']:
        new_row = dict(row)
        new_row['published_standard_candidate'] = by_num.get(row['number'])
        new_row['final_answer_verified'] = False
        new_row['correction_applied'] = False
        new_row['legal_explanation_verified'] = False
        new_row['eligible_for_scoring'] = False
        qrows.append(new_row)
    return {'schema': 'lexflow.moex.question.candidates.v1',
            'status': 'candidate_question_and_published_answer_review_only',
            'source_subject_title_check': {
                'question': question_subject_evidence,
                'published_standard_answer': answer_subject_evidence,
            },
            'all_subject_names_exactly_confirmed': (
                question_subject_evidence == 'full_printed_subject_name_matched'
                and answer_subject_evidence == 'full_printed_subject_name_matched'),
            'published_question_extraction': {k: v for k, v in question.items() if k != 'items'},
            'published_standard_answer_extraction': answer,
            'official_correction': correction,
            'questions': qrows,
            'candidate_question_count': question['four_option_candidates'],
            'candidate_answer_pair_count': sum(row['published_standard_candidate'] is not None for row in qrows),
            'question_text_and_options_verified': False,
            'final_answer_verified': False,
            'special_scoring_applied': False,
            'publication_allowed': False, 'scoring_enabled': False}
