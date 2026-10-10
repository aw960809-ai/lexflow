#!/usr/bin/env python3
"""Stage a *non-scoring* browser preview from an official PDF candidate review.

This tool NEVER promotes answers, changes user history, publishes a scored
question bank, or bypasses human source review. The generated file must be
reviewed in a Draft PR before it is placed on the public Pages branch.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys

from moex_index import write_atomic
from moex_release_gate import audit_batch, ReleaseGateError
from moex_batch_engine import safe_official_ref, BatchReviewError

MAX_FEED_BYTES = 2_000_000
MAX_PAPERS = 12
ALLOWED_ROLES = frozenset(('Q', 'S', 'M'))


class CandidateFeedError(ValueError):
    pass


def stage_candidate(report: dict, gate: dict) -> dict:
    """Reject altered identity, inconsistent gate, hostile URLs or scoring claims."""
    try:
        audited = audit_batch(report)
    except (ValueError, TypeError, RecursionError) as exc:
        raise CandidateFeedError('source candidate failed release safety audit') from exc
    if gate != audited or gate.get('status') != 'human_quality_gate_NOT_SATISFIED':
        raise CandidateFeedError('release-gate snapshot does not match candidate source')
    items = report['reviewed_items']
    if not 1 <= len(items) <= MAX_PAPERS:
        raise CandidateFeedError('candidate paper count outside bounded staging limit')
    papers = set()
    for paper in items:
        if paper['id'] in papers:
            raise CandidateFeedError('duplicate official paper ID')
        papers.add(paper['id'])
        if paper.get('state') != 'pdfs_readable_CONTENT_NOT_VERIFIED':
            raise CandidateFeedError('isolated or incomplete paper cannot enter browser preview')
        if not isinstance(paper.get('subject'), str) or not paper['subject'].strip():
            raise CandidateFeedError('missing published subject')
        documents = paper.get('documents', [])
        doc_roles, refs, question_found = set(), {}, False
        for d in documents:
            role = d.get('role')
            if role not in ALLOWED_ROLES or role in doc_roles:
                raise CandidateFeedError('unexpected/duplicate official Q/S/M role')
            doc_roles.add(role)
            try:
                ref = safe_official_ref(d.get('url'), role)
            except (ValueError, TypeError) as exc:
                raise CandidateFeedError('nonofficial or malformed document URL') from exc
            refs[role] = ref
            if role == 'Q':
                question_found = True
        if refs.get('Q', {}).get('identity') is not None and any(
            d['identity'] != refs['Q']['identity'] for role, d in refs.items() if role != 'Q'):
            raise CandidateFeedError('official question and answer identity mismatch')
        if not question_found:
            raise CandidateFeedError('official PDF question source missing')
        qa = paper.get('question_answer_candidates')
        if not isinstance(qa, dict) or qa.get('schema') != 'lexflow.moex.question.candidates.v1':
            raise CandidateFeedError('safe question candidate section absent')
        questions = qa.get('questions')
        if not isinstance(questions, list) or not 1 <= len(questions) <= 100:
            raise CandidateFeedError('question count missing or oversized')
        numbers = [x.get('number') for x in questions if isinstance(x, dict)]
        if len(numbers) != len(questions) or len(set(numbers)) != len(numbers) or any(
            not isinstance(n, int) or isinstance(n, bool) or not 1 <= n <= 100 for n in numbers):
            raise CandidateFeedError('repeated or invalid question number')
        if not any(q.get('candidate_status') == 'four_options_extracted_NEEDS_VISUAL_REVIEW'
                   and not q.get('review_reasons') and isinstance(q.get('options_unverified'), dict)
                   and set(q['options_unverified']) == set('ABCD') for q in questions):
            raise CandidateFeedError('no conservatively extracted four-option questions')
    feed = copy.deepcopy(report)
    canonical = json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')
    feed['staging'] = {
        'schema': 'lexflow.moex.unscored.preview-staging.v1',
        'origin_sha256': hashlib.sha256(canonical).hexdigest(),
        'source':'bounded MOEX official PDF batch (links + extracted text only)',
        'human_content_and_answer_review_satisfied': False,
        'website_display_only_after_review_and_merge': True,
        'personal_attempts_included': False,
    }
    feed['readiness'] = {
        'status': gate['status'],
        'summary': gate['summary'],
        'publication_allowed': False,
        'scoring_enabled': False,
    }
    if len(json.dumps(feed, ensure_ascii=False).encode('utf-8')) > MAX_FEED_BYTES:
        raise CandidateFeedError('generated browser candidate file exceeds safety limit')
    return feed


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--input', type=Path, required=True)
    ap.add_argument('--readiness', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args(argv)
    try:
        if len({args.input.resolve(), args.readiness.resolve(), args.output.resolve()}) != 3:
            raise CandidateFeedError('staging must not overwrite either source')
        if args.output.name != 'moex_review_candidate.json':
            raise CandidateFeedError('output must use the dedicated candidate filename')
        report = json.loads(args.input.read_text(encoding='utf-8'))
        gate = json.loads(args.readiness.read_text(encoding='utf-8'))
        result = stage_candidate(report, gate)
        changed = write_atomic(args.output, result)
        print(json.dumps({'state': 'staged_unscored_requires_PR_review',
            'changed': changed, 'papers': len(result['reviewed_items']),
            'score_publication_allowed': False}, ensure_ascii=False))
        return 0
    except (OSError, ValueError, TypeError, RecursionError) as exc:
        print('CANDIDATE FEED BLOCKED: ' + str(exc)[:250] + '; old feed untouched', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
