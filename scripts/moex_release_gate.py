#!/usr/bin/env python3
"""Fail-closed release-readiness AUDIT for LexFlow official PDF candidates.

This tool never approves publication, generates answers, changes quiz.js, or
converts an unreviewed PDF/text candidate into a scored question bank.
A future *separate* human/source-review workflow must attach visual PDF checks,
current correction notices, and independently validated legal explanations.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
import sys

from moex_index import write_atomic

SCHEMA = 'lexflow.moex.release.readiness.v1'
NO_PUBLISH = ('publication_allowed', 'scoring_enabled', 'eligible_for_scoring',
              'question_text_verified', 'options_verified', 'final_answer_verified',
              'answer_verified_final', 'correction_applied',
              'question_text_and_options_verified', 'legal_explanation_verified',
              'content_and_options_verified', 'special_scoring_applied',
              'all_question_text_verified', 'all_answers_verified')


class ReleaseGateError(ValueError):
    pass


def _reject_false_certificates(obj, *, depth=0):
    if depth > 15:
        raise ReleaseGateError('unexpected deep candidate object')
    if isinstance(obj, dict):
        for key, val in obj.items():
            if key in NO_PUBLISH and val is not False:
                raise ReleaseGateError('unreviewed candidate has unauthorized approval flag: ' + key)
            _reject_false_certificates(val, depth=depth + 1)
    elif isinstance(obj, list):
        if len(obj) > 10000:
            raise ReleaseGateError('candidate array too large')
        for val in obj:
            _reject_false_certificates(val, depth=depth + 1)


def audit_batch(report: dict) -> dict:
    if not isinstance(report, dict) or report.get('schema') != 'lexflow.moex.universal.batch.v1':
        raise ReleaseGateError('unexpected source batch report schema')
    if report.get('status') != 'bounded_pdf_review_not_a_scored_bank':
        raise ReleaseGateError('a downloaded official PDF candidate batch is required')
    if not isinstance(report.get('reviewed_items'), list) or not report['reviewed_items']:
        raise ReleaseGateError('empty candidate batch')
    _reject_false_certificates(report)
    rows, checklists = [], []
    for paper in report['reviewed_items']:
        if not isinstance(paper, dict) or not isinstance(paper.get('id'), str):
            raise ReleaseGateError('malformed paper')
        qa = paper.get('question_answer_candidates')
        documents = paper.get('documents', [])
        if not isinstance(documents, list):
            raise ReleaseGateError('malformed document list')
        roles = [x.get('role') for x in documents if isinstance(x, dict)]
        unique_roles = len(set(roles)) == len(roles)
        doc_evidence = all(isinstance(d, dict) and d.get('pdf_structure_readable') is True
                           and isinstance(d.get('sha256'), str)
                           and re.fullmatch(r'[0-9a-f]{64}', d['sha256'])
                           for d in documents)
        if not isinstance(qa, dict):
            rows.append({'id': paper['id'], 'status': 'paper_isolated_no_question_candidates',
                         'reasons': ['candidate_extraction_missing'], 'count': 0,
                         'score_release_allowed': False})
            continue
        questions = qa.get('questions')
        question_counts = qa.get('published_question_extraction', {})
        if not isinstance(questions, list) or not isinstance(question_counts, dict):
            raise ReleaseGateError('malformed question candidate details')
        count = question_counts.get('expected_question_count')
        safe_count = isinstance(count, int) and not isinstance(count, bool) and 1 <= count <= 100
        nums = [q.get('number') for q in questions if isinstance(q, dict)]
        sequence_ok = safe_count and nums == list(range(1, count + 1))
        options_ok = sequence_ok and all(
            q.get('candidate_status') == 'four_options_extracted_NEEDS_VISUAL_REVIEW'
            and isinstance(q.get('options_unverified'), dict)
            and set(q['options_unverified']) == set('ABCD')
            and all(isinstance(v, str) and v.strip() for v in q['options_unverified'].values())
            and isinstance(q.get('stem_unverified'), str) and q['stem_unverified'].strip()
            for q in questions)
        answer_map = qa.get('published_standard_answer_extraction', {})
        if not isinstance(answer_map, dict):
            raise ReleaseGateError('malformed answer extraction')
        published = answer_map.get('published_candidates', [])
        answer_list_consistent = (isinstance(published, list) and safe_count
            and len(published) == count
            and all(isinstance(key, dict)
                    and key.get('number') == n
                    and isinstance(key.get('published_standard_candidate'), str)
                    and key['published_standard_candidate'] in 'ABCD'
                    for n, key in enumerate(published, 1))
            and all(isinstance(q, dict) and
                    q.get('published_standard_candidate') == published[n-1]['published_standard_candidate']
                    for n, q in enumerate(questions, 1)))
        answer_complete = (sequence_ok and answer_map.get('status') ==
                           'published_standard_letter_candidates_NOT_FINAL'
                           and answer_list_consistent
                           and all(isinstance(q.get('published_standard_candidate'), str)
                                   and q['published_standard_candidate'] in 'ABCD'
                                   for q in questions))
        corr = qa.get('official_correction', {})
        if not isinstance(corr, dict):
            raise ReleaseGateError('malformed correction data')
        correction_pending = corr.get('detected') is True
        title_partial = not qa.get('all_subject_names_exactly_confirmed', False)
        reasons = []
        if not unique_roles or not doc_evidence or 'Q' not in roles:
            reasons.append('official_PDF_identity_hash_or_role_NEEDS_REVIEW')
        if not paper.get('source_link_identity_confirmed'):
            reasons.append('question_answer_link_pairing_not_proven')
        if not sequence_ok:
            reasons.append('question_count_or_sequence_incomplete')
        if not options_ok:
            reasons.append('question_stem_or_four_options_need_visual_review')
        if not answer_complete:
            reasons.append('published_answer_mapping_incomplete_or_ambiguous')
        if correction_pending:
            reasons.append('published_correction_or_special_credit_needs_manual_application')
        else:
            reasons.append('absence_of_later_official_corrections_NOT_VERIFIED')
        if title_partial:
            reasons.append('subject_heading_needs_visual_review')
        if paper.get('classification') in ('mixed', 'needs_classification'):
            reasons.append('mixed_subject_items_need_individual_classification')
        # These two gates are always unsatisfied by machine-extracted candidates.
        reasons += ['printed_question_and_option_visual_comparison_missing',
                    'human_confirmed_final_answer_and_source_date_missing']
        rows.append({
            'id': paper['id'], 'subject': str(paper.get('subject',''))[:200],
            'status': ('structure_complete_STILL_NEEDS_HUMAN_REVIEW'
                       if sequence_ok and options_ok and answer_complete
                       else 'extraction_incomplete_NEEDS_REVIEW'),
            'candidate_count': len(questions), 'declared_count': count,
            'four_options_present': bool(options_ok),
            'published_answer_grid_paired': bool(answer_complete),
            'correction_present': correction_pending,
            'reasons': list(dict.fromkeys(reasons)),
            'score_release_allowed': False,
            'explanation_release_allowed': False,
        })
        checklists.append({'id': paper['id'],
                           'required_human_review': [
                               'visually_compare_every_question_stem_and_four_options_to_unchanged_official_Q_PDF',
                               'check_official_S_and_all_later_M_ledger_notices_with_effective_date',
                               'resolve_partial_subject_names_and_mixed_field_boundaries',
                               'record_q_s_m_sha256_and_reviewer_approval_independently',
                               'check_articles_and_case_law_with_effective_date_before_publishing_explanations',
                           ]})
    return {
        'schema': SCHEMA, 'status': 'human_quality_gate_NOT_SATISFIED',
        'source_schema': report['schema'],
        'summary': {'sampled_papers': len(rows),
                    'structure_complete_not_content_verified': sum(
                        x.get('status') == 'structure_complete_STILL_NEEDS_HUMAN_REVIEW' for x in rows),
                    'pending_or_isolated_papers': sum(
                        x.get('status') != 'structure_complete_STILL_NEEDS_HUMAN_REVIEW' for x in rows)},
        'papers': rows, 'human_checklist': checklists,
        'publication_allowed': False, 'scoring_enabled': False,
        'legal_explanation_release_allowed': False,
        'disclaimer': '來源與文字候審抽取不構成逐題原卷視覺核對或最終答案驗證；不得公開計分。',
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--input', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args(argv)
    if args.input.resolve() == args.output.resolve():
        ap.error('readiness report cannot overwrite source candidate report')
    try:
        data = json.loads(args.input.read_text(encoding='utf-8'))
        review = audit_batch(data)
        write_atomic(args.output, review)
    except (OSError, ValueError, TypeError, RecursionError) as exc:
        print('RELEASE GATE BLOCKED: '+str(exc)[:250]+'; source reports untouched', file=sys.stderr)
        return 2
    print(json.dumps({'status': review['status'], **review['summary'],
                      'publication_allowed': False, 'scoring_enabled': False},
                     ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
