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
import statistics
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
SPECIAL_CREDIT = re.compile(r'一律給分|均予給分|均給分|全部給分|皆予給分|送分|複數答案|多重答案|不予計分|不計分')
# Only an identifiable official page frame at the very END of a numbered
# fragment may be excluded from the option preview. The raw evidence stays
# intact. Never remove a line merely because it mentions a page or a code.
TRAILING_PAGE_FRAME = re.compile(
    r'\n\s*代\s*號\s*[:：][ \t]*[\d \t]{2,24}'
    r'(?:\n[ \t]*\d{4,8}[ \t]*){0,5}'
    r'\n[ \t]*頁\s*次\s*[:：][ \t]*\d{1,3}[－–-]\d{1,3}[ \t]*\Z')
ONE_HEADING_CELL = re.compile(r'^第\s*(\d{1,3})\s*題$')
ONE_ANSWER_CELL = re.compile(r'^[A-D]$')


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
        page_frame = TRAILING_PAGE_FRAME.search(body)
        source_normalizations = []
        if page_frame:
            body = body[:page_frame.start()].rstrip()
            source_normalizations.append('trailing_official_page_frame_excluded_from_candidate')
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
        # Raw source remains unchanged; only a separately annotated candidate
        # excludes a complete boundary-only page frame. Visual review is still
        # mandatory before any official question is displayed to students.
        if len(raw) > MAX_QUESTION_RAW:
            issues.append('raw_fragment_exceeds_review_limit')
        rows.append({
            'number': number,
            'candidate_status': ('four_options_extracted_NEEDS_VISUAL_REVIEW' if not issues
                                 else 'isolated_question_fragment_NEEDS_REVIEW'),
            'stem_unverified': stem[:MAX_EXCERPT],
            'options_unverified': options if letters == ['A', 'B', 'C', 'D'] else {},
            'raw_pdf_excerpt_unverified': raw[:MAX_EXCERPT],
            'source_normalizations_unverified': source_normalizations,
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


def positioned_pdf_cells(blob: bytes) -> list[dict]:
    """Obtain PDF text fragments with locations, never infer omitted cells.

    pypdf's text visitor sometimes merges whole rows or lacks usable character
    positions. In that case no positional answers are returned. The caller may
    still show a candidate from a separately unambiguous textual table.
    """
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(blob), strict=False)
    if not 1 <= len(reader.pages) <= 4:
        raise QuestionExtractionError('answer PDF needs an independent multi-page layout review')
    found = []
    for page_no, page in enumerate(reader.pages):
        def visitor(value, cm, tm, font, size):
            if len(found) > 1500:
                return
            label = _tight(value)
            if not (ONE_HEADING_CELL.fullmatch(label) or ONE_ANSWER_CELL.fullmatch(label)):
                return
            # The text matrix is relative to the graphics-state transform.
            # Ordinary PDF table cells have a position near their printed row.
            x = cm[0] * tm[4] + cm[2] * tm[5] + cm[4]
            y = cm[1] * tm[4] + cm[3] * tm[5] + cm[5]
            if not (-100 <= x <= 3000 and -100 <= y <= 3000):
                return
            found.append({'page': page_no, 'x': round(x, 2), 'y': round(y, 2),
                          'text': label})
        page.extract_text(visitor_text=visitor)
    return found[:1500]


def pair_positioned_answer_cells(cells: list[dict], *, expected_count: int) -> dict[int, str]:
    """Align numbered cells with letter cells on adjacent physical PDF rows.

    A partial final row is permitted ONLY if its empty cells fall outside the
    declared number of questions and x/y coordinates prove all other pairs.
    Any collision, missing interior cell or uncertain row rejects ALL keys.
    """
    if not 1 <= expected_count <= MAX_QUESTIONS or len(cells) > 1500:
        return {}
    rows = []
    for page in sorted({cell.get('page') for cell in cells}):
        members = sorted((c for c in cells if c.get('page') == page),
                         key=lambda c: (-c['y'], c['x']))
        for cell in members:
            try:
                y = float(cell['y'])
                x = float(cell['x'])
                if not (-100 < x < 3000 and -100 < y < 3000):
                    return {}
            except (TypeError, ValueError, KeyError):
                return {}
            if rows and rows[-1]['page'] == page and abs(rows[-1]['y'] - y) <= 3:
                rows[-1]['cells'].append(cell)
            else:
                rows.append({'page': page, 'y': y, 'cells': [cell]})
    pairs: dict[int, str] = {}
    used_answer_rows = set()
    for i, row in enumerate(rows):
        headings = []
        for cell in row['cells']:
            m = ONE_HEADING_CELL.fullmatch(cell['text'])
            if m:
                headings.append((int(m.group(1)), float(cell['x'])))
        if len(headings) < 2:
            continue
        headings.sort(key=lambda z: z[1])
        nums = [n for n, _ in headings]
        if nums != list(range(nums[0], nums[0] + len(nums))):
            return {}
        gaps = [headings[j+1][1] - headings[j][1] for j in range(len(headings)-1)]
        if not all(12 <= gap <= 250 for gap in gaps):
            return {}
        pitch = statistics.median(gaps)
        # Only a single physically adjacent answer row can satisfy a heading.
        answer_rows = []
        for j in range(i + 1, len(rows)):
            other = rows[j]
            if other['page'] != row['page'] or row['y'] - other['y'] > 48:
                break
            if any(ONE_HEADING_CELL.fullmatch(c['text']) for c in other['cells']):
                break
            letters = [c for c in other['cells'] if ONE_ANSWER_CELL.fullmatch(c['text'])]
            if letters and 2 <= row['y'] - other['y'] <= 48:
                answer_rows.append((j, letters))
        if len(answer_rows) != 1 or answer_rows[0][0] in used_answer_rows:
            # A header row with no answers is valid only when ALL its headings
            # exceed the declared last question (blank official template).
            if any(n <= expected_count for n in nums):
                return {}
            continue
        j, letters = answer_rows[0]
        used_answer_rows.add(j)
        if len(letters) > len(headings):
            return {}
        seen_for_row = set()
        for c in letters:
            ranked = sorted(((abs(float(c['x'])-hx), n) for n, hx in headings))
            if len(ranked) > 1 and abs(ranked[0][0] - ranked[1][0]) < 1:
                return {}
            if ranked[0][0] > pitch * 0.44:
                return {}
            _, number = ranked[0]
            if number in seen_for_row or number in pairs or number > expected_count:
                return {}
            seen_for_row.add(number)
            pairs[number] = c['text']
        # Missing an answer in the middle is NEVER equivalent to blank trailing
        # template cells. Numbered columns <= expected_count must be complete.
        if any(n <= expected_count and n not in seen_for_row for n in nums):
            return {}
    return pairs if set(pairs) == set(range(1, expected_count+1)) else {}


def parse_answer_table_text(texts: list[str], *, expected_count: int | None,
                            positioned_cells: list[dict] | None = None) -> dict:
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
    position_candidate = None
    if positioned_cells is not None:
        position_candidate = pair_positioned_answer_cells(positioned_cells,
                                                          expected_count=expected_count)
        if position_candidate:
            collected.append(position_candidate)
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
        # In a positioned PDF layout, the last heading in a ten-column row
        # is followed by a newline and then the FIRST column's answer. Using
        # \s* here would silently mispair that answer with column ten.
        # Only a number and letter printed on the SAME physical text line
        # qualifies for this non-positional inline extraction mode.
        inline = re.findall(
            r'第[ \t]*(\d{1,3})[ \t]*題[ \t]*[:：=｜|]?[ \t]*([A-D])(?=[ \t]|$|[、，,。])',
            text, flags=re.M)
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
            'evidence_method': ('positioned_pdf_cell_alignment_WITH_VISUAL_REVIEW_REQUIRED'
                                if position_candidate and candidate == position_candidate
                                else 'explicit_number_and_letter_text_alignment_UNVERIFIED'),
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


def correction_notice_review(text: str, *, expected_count: int | None = None) -> dict:
    """Locate an MOEX M notice without converting it into a final answer.

    Numbered cells in the large corrected-answer GRID are not correction
    notices. Only explicit numbered references in 備註 are possible targets.
    A complex/missing note always remains a paper-wide manual-review issue.
    """
    cleaned = unicodedata.normalize('NFKC', text or '')
    anchor = re.search(r'備\s*註\s*[:：]\s*', cleaned)
    after = cleaned[anchor.end():] if anchor else ''
    after = re.split(r'標\s*準\s*答\s*案\s*[:：]', after, maxsplit=1)[0]
    note = re.sub(r'\s+', ' ', after).strip()[:600]
    numbers = sorted({int(n) for n in Q_LABEL.findall(note)
                      if expected_count is None or 1 <= int(n) <= expected_count})
    # A source with no legible 備註 still demands special-score review if such
    # text appears elsewhere; but its question number is NOT inferred.
    special = bool(SPECIAL_CREDIT.search(note or cleaned))
    marker = bool(re.search(r'答案標註\s*#|標註\s*#|更正答案|#者', cleaned))
    return {
        'status': 'official_correction_notice_PRESENT_UNAPPLIED',
        'affected_question_numbers_NEEDS_VISUAL_CHECK': numbers,
        'published_notice_excerpt_unverified': note[:350],
        'notice_is_bounded_to_remarks': bool(anchor),
        'correction_marker_present': marker,
        'special_scoring_mentioned': special,
        'final_answer_verified': False,
        'correction_applied': False,
    }


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
        # Positional cells are only a second independent candidate view.
        # Incomplete/misaligned cells are silently ignored (no invented keys).
        positioned = None
        if pdf_documents['S'].startswith(b'%PDF-'):
            try:
                positioned = positioned_pdf_cells(pdf_documents['S'])
            except Exception:
                positioned = None
        answer = parse_answer_table_text([s_layout, s_plain], expected_count=expected,
                                         positioned_cells=positioned)
    correction = {'status': 'corrections_not_proven_absent', 'detected': False,
                  'special_scoring_mentioned': False, 'correction_applied': False}
    if 'M' in pdf_documents:
        if not identity_paired:
            raise QuestionExtractionError('unpaired correction document cannot be mapped')
        m_plain, _ = _get_pdf_texts(pdf_documents['M'])
        correction = correction_notice_review(m_plain, expected_count=expected)
        correction['detected'] = True
    else:
        correction['review_required_to_confirm_no_later_changes'] = True
    by_num = {p['number']: p['published_standard_candidate'] for p in answer['published_candidates']}
    qrows = []
    for row in question['items']:
        new_row = dict(row)
        new_row['published_standard_candidate'] = by_num.get(row['number'])
        new_row['correction_notice_mentions_question'] = (row['number'] in
            correction.get('affected_question_numbers_NEEDS_VISUAL_CHECK', []))
        new_row['requires_official_correction_finality_review'] = True
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
