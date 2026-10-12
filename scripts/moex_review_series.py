#!/usr/bin/env python3
"""Bounded, restart-safe orchestrator for the EXISTING LexFlow whole-paper engine.

This module does not implement a PDF downloader, parser, legal classifier, grade,
or publication path. It ONLY groups validated official catalog plans into small
immutable batches, calls moex_catalog_bridge.run_plan, and audits the resulting
unverified source evidence. No network access unless `execute --download-documents`.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile

from moex_catalog_bridge import (ALLOWED_KINDS, MAX_BATCH, UnsafeSource,
    digest, make_plan, run_plan, sha256_file, validate_paper)

SCHEMA = 'lexflow.moex.bounded-series.v1'
RESULT_SCHEMA = 'lexflow.moex.bounded-series-batch.v1'
QUALITY_SCHEMA = 'lexflow.moex.bounded-series-quality.v1'
MAX_SESSION_BATCHES = 3
MAX_PAPERS_PER_BATCH = 4
MAX_DOCS_PER_BATCH = 8
PAPER_RE = re.compile(r'^moex-[0-9a-f]{24}$')
SHA_RE = re.compile(r'^[0-9a-f]{64}$')


def _encoded(value: dict) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode('utf-8')


def create_only(path: Path, value: dict) -> bool:
    """Create-only, idempotent JSON; never overwrite existing files.

    Prefer atomic hard-link publication when supported. Android Termux Python
    may omit os.link entirely: use O_EXCL to reserve the final file instead.
    If an interrupted fallback write leaves incomplete bytes, a retry stops
    on the mismatch rather than silently overwriting the evidence.
    """
    payload = _encoded(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        if path.is_symlink() or path.read_bytes() != payload:
            raise UnsafeSource('existing immutable session file differs: ' + path.name)
        return False
    fd, tmp = tempfile.mkstemp(prefix='.lexflow-', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        linker = getattr(os, 'link', None)
        try:
            if callable(linker):
                linker(tmp, path)  # atomic create-only on supported platforms
            else:
                # Exclusive creation works in Termux even without hard links.
                # O_EXCL also rejects a pre-existing symlink (no following).
                output_fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                try:
                    with os.fdopen(output_fd, 'wb') as target:
                        target.write(payload)
                        target.flush()
                        os.fsync(target.fileno())
                except BaseException:
                    # Only our newly reserved path can be removed here.
                    path.unlink(missing_ok=True)
                    raise
        except FileExistsError:
            if path.is_symlink() or path.read_bytes() != payload:
                raise UnsafeSource('concurrent session creation differs: ' + path.name)
            return False
    finally:
        os.unlink(tmp)
    return True


def _checked_sha(value: str) -> str:
    if not isinstance(value, str) or not SHA_RE.fullmatch(value):
        raise UnsafeSource('invalid catalog SHA256')
    return value


def _validated_plan(plan: dict) -> None:
    if (not isinstance(plan, dict) or plan.get('schema') != 'lexflow.moex.whole-paper-plan.v1'
        or plan.get('publication_allowed') is not False
        or plan.get('scoring_enabled') is not False
        or plan.get('original_catalog_unchanged') is not True):
        raise UnsafeSource('unknown or publishing-enabled source plan')
    _checked_sha(plan.get('catalog_sha256'))
    papers = plan.get('papers')
    if not isinstance(papers, list) or not 1 <= len(papers) <= MAX_BATCH:
        raise UnsafeSource('empty or oversized source plan')
    ids = set()
    for p in papers:
        pid = p.get('paper_id') if isinstance(p, dict) else None
        if not isinstance(pid, str) or not PAPER_RE.fullmatch(pid) or pid in ids:
            raise UnsafeSource('invalid or duplicate official whole-paper ID')
        ids.add(pid)
        if (p.get('state') != 'planned_review_not_downloaded'
            or p.get('source_file_sha256') != plan['catalog_sha256']
            or p.get('scoring_enabled') is not False or p.get('content_verified') is not False
            or p.get('answer_verified') is not False):
            raise UnsafeSource('paper has unsafe candidate/release metadata')
        links, _ = validate_paper(p)
        if links != p.get('links'):
            raise UnsafeSource('paper links differ from validated official identity')


def _planned_batches(plan: dict, papers_per_batch: int, docs_per_batch: int) -> list[dict]:
    papers = plan['papers']
    batches = []
    for i in range(0, len(papers), papers_per_batch):
        chunk = papers[i:i + papers_per_batch]
        if sum(len(p['links']) for p in chunk) > docs_per_batch:
            # Never create a batch that would partially download a paper.
            raise UnsafeSource('selected whole papers exceed per-batch document budget')
        batches.append({**plan, 'papers': chunk,
                        'selected_papers': len(chunk),
                        'batch_source_selection': 'subset_of_original_whole_paper_plan',
                        'batch_index': len(batches) + 1})
    return batches


def prepare(catalog: Path, out_dir: Path, *, scope='candidates', years=None,
            types=None, exam_codes=None, subjects=None, class_groups=None,
            strategy='coverage', start_row=1, batches=3, per_batch=3,
            docs_per_batch=8) -> dict:
    """Offline-only planning. Works from original official CSV/enriched CSV/SQLite."""
    if (not 1 <= batches <= MAX_SESSION_BATCHES or
        not 1 <= per_batch <= MAX_PAPERS_PER_BATCH or
        not 1 <= docs_per_batch <= MAX_DOCS_PER_BATCH or
        batches * per_batch > MAX_BATCH or batches * docs_per_batch > 24):
        raise UnsafeSource('bounded session paper/document limit exceeded')
    if strategy not in ('coverage', 'sequential') or start_row < 1:
        raise UnsafeSource('invalid selection strategy or cursor')
    catalog = catalog.resolve(strict=True)
    out_dir = out_dir.resolve()
    # Source catalog can never become an output destination.
    if out_dir == catalog or catalog in out_dir.parents:
        raise UnsafeSource('source catalog cannot be used as output directory')
    whole_plan = make_plan(catalog, scope=scope, years=years, types=types,
        exam_codes=exam_codes, subjects=subjects, class_groups=class_groups,
        strategy=strategy, max_papers=batches * per_batch, start_row=start_row)
    _validated_plan(whole_plan)
    catalog_sha = _checked_sha(whole_plan['catalog_sha256'])
    if sha256_file(catalog) != catalog_sha:
        raise UnsafeSource('official catalog changed during planning')
    planned = _planned_batches(whole_plan, per_batch, docs_per_batch)
    identity = {'catalog_sha256':catalog_sha, 'schema':SCHEMA,
        'scope':scope, 'years':years or [], 'types':types or [],
        'exam_codes':exam_codes or [], 'subjects':subjects or [],
        'class_groups':class_groups or [], 'strategy':strategy,
        'start_row':start_row, 'batches':batches,
        'per_batch':per_batch, 'docs_per_batch':docs_per_batch,
        'paper_ids':[p['paper_id'] for p in whole_plan['papers']]}
    session_id = digest(_encoded(identity))[:20]
    home = out_dir / 'sessions' / ('series-' + session_id)
    entries = []
    for number, piece in enumerate(planned, 1):
        name = f'plans/batch-{number:02d}.json'
        entries.append({'index':number, 'plan_path':name,
                        'plan_sha256':digest(_encoded(piece)),
                        'paper_ids':[p['paper_id'] for p in piece['papers']],
                        'official_types':[p['official_type'] for p in piece['papers']],
                        'year_rocs':[p['year_roc'] for p in piece['papers']],
                        'exam_codes':[p['exam_code'] for p in piece['papers']],
                        'source_rows':[p['source_row'] for p in piece['papers']]})
    manifest = {'schema':SCHEMA, 'session_id':session_id,
        'catalog_sha256':catalog_sha, 'catalog_basename':catalog.name,
        'source_scope':scope, 'strategy':strategy,
        'source_rows_total':whole_plan['catalog_total_records'],
        'source_candidate_rows':whole_plan['catalog_title_candidates'],
        'filters':{k:identity[k] for k in ('years','types','exam_codes','subjects','class_groups')},
        'start_row':start_row, 'selected_papers':len(whole_plan['papers']),
        'batch_count':len(entries), 'papers_per_batch':per_batch,
        'docs_per_batch':docs_per_batch,
        'catalog_cursor_next_row':(max((p['source_row'] for p in whole_plan['papers']), default=0) + 1
            if strategy == 'sequential' else None),
        'cursor_is_complete_contiguous_enumeration':strategy=='sequential',
        'batches':entries, 'source_PDFs_downloaded':0,
        'title_based_law_candidate_not_human_verified':True,
        'private_attempts_included':False, 'publication_allowed':False,
        'scoring_enabled':False, 'final_answers_verified':False,
        'description':'Offline review plan. One original whole paper per ID. No downloaded or scored questions.'}
    # Store plans before the manifest; interrupted creation is re-runnable.
    for entry, piece in zip(entries, planned):
        create_only(home / entry['plan_path'], piece)
    create_only(home / 'session.json', manifest)
    return {'status':'PLANNED_OFFLINE_NO_DOWNLOAD', 'session_dir':str(home),
        'selected_papers':manifest['selected_papers'],
        'batch_count':manifest['batch_count'],
        'type_counts':dict(Counter(x for e in entries for x in e['official_types'])),
        'year_rocs':sorted(set(x for e in entries for x in e['year_rocs'])),
        'exam_codes':sorted(set(x for e in entries for x in e['exam_codes'])),
        'cursor_next_row_if_sequential_only':manifest['catalog_cursor_next_row'],
        'publication_allowed':False, 'scoring_enabled':False}


def read_session(home: Path) -> dict:
    manifest = json.loads((home/'session.json').read_text('utf-8'))
    if (manifest.get('schema') != SCHEMA or manifest.get('publication_allowed') is not False
        or manifest.get('scoring_enabled') is not False
        or not 1 <= manifest.get('batch_count',0) <= MAX_SESSION_BATCHES
        or not 1 <= manifest.get('docs_per_batch',0) <= MAX_DOCS_PER_BATCH
        or not isinstance(manifest.get('batches'),list)
        or len(manifest['batches']) != manifest['batch_count']
        or manifest['batch_count'] * manifest['docs_per_batch'] > 24
        or not 1 <= manifest.get('selected_papers',0) <= MAX_BATCH):
        raise UnsafeSource('invalid or publishing-enabled batch session')
    _checked_sha(manifest['catalog_sha256'])
    ids=set()
    for idx,e in enumerate(manifest['batches'],1):
        if (e.get('index')!=idx or e.get('plan_path')!=f'plans/batch-{idx:02d}.json'
            or not SHA_RE.fullmatch(str(e.get('plan_sha256','')))):
            raise UnsafeSource('invalid batch manifest entry')
        p_bytes = (home/e['plan_path']).read_bytes()
        if digest(p_bytes)!=e['plan_sha256']:
            raise UnsafeSource('batch source plan was modified')
        plan=json.loads(p_bytes)
        _validated_plan(plan)
        if plan['catalog_sha256']!=manifest['catalog_sha256'] or plan.get('batch_index')!=idx:
            raise UnsafeSource('batch provenance does not match catalog session')
        actual=[p['paper_id'] for p in plan['papers']]
        if actual!=e.get('paper_ids') or any(x in ids for x in actual):
            raise UnsafeSource('duplicate/mismatched original papers between batches')
        ids.update(actual)
        if sum(len(p['links']) for p in plan['papers']) > manifest['docs_per_batch']:
            raise UnsafeSource('batch source URLs exceed download budget')
    if len(ids)!=manifest.get('selected_papers'):
        raise UnsafeSource('incomplete manifest paper inventory')
    return manifest


def _read_saved_result(path: Path, session: dict, entry: dict) -> dict:
    payload = json.loads(path.read_text('utf-8'))
    if (payload.get('schema') != RESULT_SCHEMA
        or payload.get('catalog_sha256') != session['catalog_sha256']
        or payload.get('batch_index') != entry['index']
        or payload.get('plan_sha256') != entry['plan_sha256']
        or payload.get('paper_ids') != entry['paper_ids']
        or not isinstance(payload.get('review_results'),list)
        or payload.get('publication_allowed') is not False
        or payload.get('scoring_enabled') is not False):
        raise UnsafeSource('batch completion journal mismatch')
    return payload


def execute(home: Path, *, catalog: Path|None=None, offline_only=False,
            download_documents=False, max_batches=3) -> dict:
    """At most 3 bounded batches per invocation; all reports append-only."""
    if offline_only == download_documents:
        raise UnsafeSource('choose exactly one: offline cache-only or explicit network PDF download')
    if not 1<=max_batches<=MAX_SESSION_BATCHES:
        raise UnsafeSource('too many consecutive batches')
    home = home.resolve(strict=True)
    manifest=read_session(home)
    if catalog is not None and sha256_file(catalog)!=manifest['catalog_sha256']:
        raise UnsafeSource('source CSV SHA256 changed; start a different session')
    root=home.parent.parent
    report_dir=root/'session-reviews'/manifest['session_id']
    shared_cache=root/'official-review'/'official_pdf_cache'
    completed=[]; processed=0; incomplete=False
    for entry in manifest['batches']:
        idx=entry['index']
        journal=home/'results'/f'batch-{idx:02d}.json'
        if journal.exists():
            prior=_read_saved_result(journal,manifest,entry)
            completed.append({'batch_index':idx,'status':'preserved_completed_batch',
                              'papers':len(entry['paper_ids']),
                              'network_pdf_downloads':prior.get('network_pdf_downloads',0)})
            continue
        if processed>=max_batches:
            break
        if catalog is not None and sha256_file(catalog)!=manifest['catalog_sha256']:
            raise UnsafeSource('source catalog changed mid-run; no more batches processed')
        plan=json.loads((home/entry['plan_path']).read_text('utf-8'))
        result=run_plan(plan,report_dir,max_papers=len(plan['papers']),
            max_docs=manifest['docs_per_batch'],start_at=1,offline_only=offline_only,
            shared_cache_root=shared_cache)
        if result.get('scoring_enabled') is not False or result.get('publication_allowed') is not False:
            raise UnsafeSource('legacy review engine unexpectedly enabled publication')
        retryable = [x for x in result['reviews'] if x.get('state') not in (
            'downloaded_source_still_requires_human_review',
            'partial_or_isolated_source_needs_review',
            'existing_report_preserved')]
        if retryable:
            # Missing offline cache or transient PDF failures are NOT completed
            # checkpoints. A later explicit run may safely reuse successful PDFs.
            completed.append({'batch_index':idx,'status':'INCOMPLETE_RETRYABLE_NO_CHECKPOINT',
                'results':retryable, 'network_pdf_downloads':result['network_pdf_downloads']})
            processed += 1
            incomplete=True
            break
        journal_value={'schema':RESULT_SCHEMA,'batch_index':idx,
            'catalog_sha256':manifest['catalog_sha256'], 'plan_sha256':entry['plan_sha256'],
            'paper_ids':entry['paper_ids'], 'offline_cache_only':offline_only,
            'review_results':result['reviews'],
            'network_pdf_downloads':result['network_pdf_downloads'],
            'cache_reuses':result['cache_reuses'],
            'publication_allowed':False,'scoring_enabled':False,
            'human_final_answers_verified':False}
        create_only(journal,journal_value)
        completed.append({'batch_index':idx,'status':'review_batch_completed_unscored',
            'papers':len(entry['paper_ids']),
            'network_pdf_downloads':result['network_pdf_downloads'],
            'cache_reuses':result['cache_reuses'],
            'isolated':sum(x.get('state','').startswith(('isolated_','partial_','document_budget'))
                           for x in result['reviews'])})
        processed+=1
    return {'status':('PARTIAL_REVIEW_SAFE_STOP' if incomplete else 'BOUNDED_BATCHES_REVIEWED_NOT_SCORED'),
        'batches_processed_this_invocation':processed,
        'batches_confirmed_completed':sum(x['status']!='INCOMPLETE_RETRYABLE_NO_CHECKPOINT' for x in completed),
        'session_batches_total':manifest['batch_count'],
        'results':completed, 'publication_allowed':False, 'scoring_enabled':False,
        'note':'Individual PDF failures remain isolated and must be reviewed; no scoring/publication.'}


def _source_quality(report_root: Path, p: dict, catalog_sha: str, *, shared_cache_root: Path|None=None) -> dict:
    pid=p['paper_id']
    out={'paper_id':pid, 'year_roc':p['year_roc'],
        'exam_code':p['exam_code'],'official_subject':p['official_subject'],
        'official_type':p['official_type'],
        'state':'no_saved_review', 'question_fulltext_sha_matched':False,
        'official_final_answers_verified':False, 'publication_allowed':False,
        'scoring_enabled':False}
    file=report_root/'reports'/(pid+'.json')
    if not file.is_file(): return out
    raw=file.read_bytes()
    rep=json.loads(raw)
    if (rep.get('paper_id')!=pid or rep.get('catalog_sha256')!=catalog_sha
        or rep.get('official_source',{}).get('question_url')!=p['question_url']
        or rep.get('official_source',{}).get('official_type')!=p['official_type']
        or rep.get('publication_allowed') is not False
        or rep.get('scoring_enabled') is not False
        or rep.get('official_final_answers_verified') is True
        or rep.get('human_quality_gate_satisfied') is True
        or rep.get('v03_review',{}).get('scoring_enabled') is True
        or rep.get('v03_review',{}).get('publication_allowed') is True):
        out['state']='isolated_report_identity_or_scoring_mismatch';return out
    out['state']=rep.get('state','unknown_unscored_review_state')
    text_meta=rep.get('extracted_question_text')
    if isinstance(text_meta,dict):
        if text_meta.get('relative_path')!=f'extracted_text/{pid}.txt':
            out['state']='isolated_untrusted_fulltext_path';return out
        textpath=report_root/text_meta['relative_path']
        if not textpath.is_file() or sha256_file(textpath)!=text_meta.get('sha256'):
            out['state']='isolated_fulltext_missing_or_SHA_mismatch';return out
        out['question_fulltext_sha_matched']=True
        out['unverified_extracted_text_chars']=text_meta.get('chars',0)
        out['extracted_text_truncated']=text_meta.get('truncated',True)
    rows=rep.get('v03_review',{}).get('reviewed_items',[])
    if len(rows)!=1 or not isinstance(rows[0],dict):
        out['state']='isolated_missing_nested_review';return out
    inner=rows[0]
    if inner.get('eligible_for_scoring') is True:
        out['state']='isolated_nested_review_claims_scoring';return out
    docs=inner.get('documents',[])
    if not isinstance(docs,list) or any(not isinstance(d,dict) or
        d.get('url') != p['links'].get(d.get('role')) for d in docs):
        out['state']='isolated_source_document_links_mismatch';return out
    output_q=inner.get('question_answer_candidates',{})
    if isinstance(output_q,dict) and (output_q.get('scoring_enabled') is True or
        output_q.get('publication_allowed') is True or
        output_q.get('final_answer_verified') is True):
        out['state']='isolated_nested_questions_claim_verified';return out
    if isinstance(output_q,dict):
        out['mcq_four_option_candidates_unverified']=output_q.get('candidate_question_count',0)
        out['original_answer_pairs_unverified']=output_q.get('candidate_answer_pair_count',0)
    e=rep.get('essay_candidate_sections')
    if isinstance(e,dict): out['essay_section_candidates_unverified']=e.get('count',0)
    out['PDF_documents_reported']=len(inner.get('documents',[]))
    out['review_warnings']=inner.get('warnings',[])[:12]

    # A shared public Q/S/M cache lives one directory above this session's
    # reports. Older quality previews were made against an EMPTY session-local
    # cache. Never treat that older, not-cached preview as current answer proof.
    active_path=None
    answer_url=rep.get('official_source',{}).get('answer_url') or ''
    if answer_url and answer_url not in (p['links'].get('S'),p['links'].get('M')):
        out['quality_overlay']='isolated_answer_source_identity_mismatch'
        return out
    if answer_url and shared_cache_root is not None:
        key=hashlib.sha256(answer_url.encode('utf-8')).hexdigest()
        pdf=shared_cache_root/(key+'.pdf')
        meta=shared_cache_root/(key+'.json')
        if pdf.exists() or meta.exists() or pdf.is_symlink() or meta.is_symlink():
            try:
                # Create-only new preview; the source report and any previous
                # previews remain byte-for-byte untouched. The overlay verifies
                # BOTH public cache SHA and original reviewed document SHA.
                from moex_quality_overlay import make_overlay_from_disk
                active_path,active_overlay=make_overlay_from_disk(
                    report_root,file,cache_root=shared_cache_root)
                if active_overlay.get('answer_PDF_source_sha256_or_state') in (None,'not_cached'):
                    raise UnsafeSource('shared cache missing verified answer bytes')
                out['answer_pdf_cached_and_source_sha_matched']=True
            except (OSError,ValueError,KeyError,TypeError,ImportError) as exc:
                # A bad cache must NEVER fall back to a previously successful
                # preview as though the current source had been verified.
                out['quality_overlay']='isolated_shared_answer_cache_or_overlay_failure'
                out['quality_refresh_error']=type(exc).__name__
                return out

    overlays=[]
    for qfile in sorted((report_root/'quality_previews').glob(pid+'-*.json')):
        if qfile.is_symlink():
            out['quality_overlay']='isolated_symlinked_quality_preview';return out
        try:
            data=json.loads(qfile.read_text('utf-8'))
            if not isinstance(data,dict): raise ValueError('not a JSON object')
        except (ValueError,UnicodeError,OSError):
            out['quality_overlay']='isolated_malformed_quality_preview'
            return out
        if (data.get('paper_id')==pid and data.get('report_source_sha256')==digest(raw)
            and data.get('publication_allowed') is False
            and data.get('scoring_enabled') is False
            and data.get('final_answer_verified') is not True
            and data.get('human_quality_gate_satisfied') is not True):
            overlays.append((qfile,data))
    out['quality_preview_versions_for_source']=len(overlays)
    if active_path is not None:
        # Prefer the EXACT candidate generated against the verified current
        # public PDF cache. Older 'not_cached' previews are retained, not mixed.
        matches=[item for item in overlays if item[0]==active_path]
        if len(matches)!=1:
            out['quality_overlay']='isolated_active_preview_source_mismatch';return out
        overlay=matches[0][1]
        if (overlay.get('answer_PDF_source_sha256_or_state')!=active_overlay.get('answer_PDF_source_sha256_or_state')
            or overlay.get('extracted_text_source_sha256')!=text_meta.get('sha256')):
            out['quality_overlay']='isolated_active_preview_fingerprint_mismatch';return out
        out['quality_overlay']='current_verified_public_cache_preview'
    elif len(overlays)>1:
        out['quality_overlay']='ambiguous_multiple_matching_overlays';return out
    elif len(overlays)==1:
        overlay=overlays[0][1]
        # The legacy copy can still supply NON-ANSWER title / essay / MCQ
        # metadata, but never count positional answers without current PDF bytes.
        out['quality_overlay']='fingerprint_matches_saved_report'
    else:
        overlay=None
        out['quality_overlay']='none_matching_original_report'
    if overlay is not None:
        mcq=overlay.get('multiple_choice_candidates',{})
        if isinstance(mcq,dict):
            out['mcq_four_option_candidates_after_repair_unverified']=mcq.get('candidate_count',0)
        answer=overlay.get('answer_and_correction_evidence',{})
        table=answer.get('table_candidate',{}) if isinstance(answer,dict) else {}
        if isinstance(table,dict):
            out['answer_table_candidate_state']=table.get('state','unknown')
            out['answer_pair_conflicts']=table.get('original_candidate_conflict_numbers',[])
            if active_path is not None:
                out['positioned_answer_pairs_unverified']=table.get('unique_paired_numbers',0)
                out['special_credit_number_candidates']=sorted({int(x['number']) for x in
                    answer.get('special_credit_candidate',[]) if isinstance(x,dict) and 'number' in x})
                out['answer_cells_including_special_credit_unverified']=table.get(
                    'answer_cell_coverage_with_special_notes',0)
        sect=overlay.get('section_candidates',{})
        if isinstance(sect,dict):
            essay=sect.get('essay',{})
            if isinstance(essay,dict):
                out['essay_sections_after_repair_unverified']=essay.get('count',0)
    if (p['official_type']=='申論題' and out.get('question_fulltext_sha_matched') is True
        and out.get('essay_sections_after_repair_unverified',out.get('essay_section_candidates_unverified',0))==0):
        out['essay_heading_needs_manual_review']=True
    out['official_total_question_count_confirmed']=False
    out['question_completeness_percentage']=None
    return out


def audit(home: Path) -> dict:
    home=home.resolve(strict=True)
    m=read_session(home)
    root=home.parent.parent
    source=root/'session-reviews'/m['session_id']
    shared_cache_root=root/'official-review'/'official_pdf_cache'
    papers=[]
    for e in m['batches']:
        plan=json.loads((home/e['plan_path']).read_text('utf-8'))
        for p in plan['papers']:
            papers.append(_source_quality(source,p,m['catalog_sha256'],
                                          shared_cache_root=shared_cache_root))
    statuses=Counter(x['state'] for x in papers)
    report={'schema':QUALITY_SCHEMA,'session_id':m['session_id'],
        'catalog_sha256':m['catalog_sha256'],
        'paper_count':len(papers),'types':dict(Counter(x['official_type'] for x in papers)),
        'source_states':dict(statuses),
        'with_fulltext_sha_matched':sum(x.get('question_fulltext_sha_matched') is True for x in papers),
        'mcq_four_option_candidates_unverified':sum(x.get('mcq_four_option_candidates_after_repair_unverified',
            x.get('mcq_four_option_candidates_unverified',0)) for x in papers),
        'essay_section_candidates_unverified':sum(x.get('essay_sections_after_repair_unverified',
            x.get('essay_section_candidates_unverified',0)) for x in papers),
        'positioned_answer_pairs_unverified':sum(x.get('positioned_answer_pairs_unverified',0) for x in papers),
        'answer_cells_including_special_credit_unverified':sum(
            x.get('answer_cells_including_special_credit_unverified',0) for x in papers),
        'shared_cached_answer_sources_sha_matched':sum(
            x.get('answer_pdf_cached_and_source_sha_matched') is True for x in papers),
        'essay_papers_with_headings_needing_review':sum(
            x.get('essay_heading_needs_manual_review') is True for x in papers),
        'original_answer_pairs_unverified':sum(x.get('original_answer_pairs_unverified',0) for x in papers),
        'answer_pair_conflict_count':sum(len(x.get('answer_pair_conflicts',[])) for x in papers),
        'special_credit_question_candidates':sorted({i for p in papers for i in
            p.get('special_credit_number_candidates',[])}),
        'papers':papers,
        'official_total_question_count_confirmed':False,
        'fulltext_completeness_rate':None,
        'publication_allowed':False,'scoring_enabled':False,
        'human_answers_verified':False,
        'note':'Extracted fragments/keys are unverified. No known official full-question denominator.'}
    filename='quality-'+digest(_encoded(report))[:20]+'.json'
    create_only(home/'audits'/filename,report)
    return {'status':'UNSCORED_SOURCE_QUALITY_AUDIT','audit_path':str(home/'audits'/filename),
        'paper_count':len(papers),'states':report['source_states'],
        'with_fulltext_sha_matched':report['with_fulltext_sha_matched'],
        'mcq_candidates':report['mcq_four_option_candidates_unverified'],
        'essay_sections':report['essay_section_candidates_unverified'],
        'answer_pairs':report['positioned_answer_pairs_unverified'],
        'publication_allowed':False, 'scoring_enabled':False}


def main(argv=None) -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    cmd=parser.add_subparsers(dest='command',required=True)
    plan=cmd.add_parser('prepare',help='OFFLINE: small cross-year whole-paper plans')
    plan.add_argument('--catalog',type=Path,required=True)
    plan.add_argument('--output-dir',type=Path,required=True)
    plan.add_argument('--scope',choices=('candidates','all'),default='candidates')
    plan.add_argument('--strategy',choices=('coverage','sequential'),default='coverage')
    plan.add_argument('--years',default='')
    plan.add_argument('--types',default='')
    plan.add_argument('--exam-code',action='append',dest='exam_codes',default=[])
    plan.add_argument('--subject',action='append',dest='subjects',default=[])
    plan.add_argument('--class-group',action='append',dest='class_groups',default=[])
    plan.add_argument('--start-row',type=int,default=1)
    plan.add_argument('--batches',type=int,default=3)
    plan.add_argument('--papers-per-batch',type=int,default=3)
    plan.add_argument('--documents-per-batch',type=int,default=8)
    review=cmd.add_parser('execute',help='Explicit bounded PDF review; no publishing')
    review.add_argument('--session-dir',type=Path,required=True)
    review.add_argument('--catalog',type=Path)
    mutually=review.add_mutually_exclusive_group(required=True)
    mutually.add_argument('--download-documents',action='store_true')
    mutually.add_argument('--offline-only',action='store_true')
    review.add_argument('--max-batches',type=int,default=3)
    inspect=cmd.add_parser('audit',help='Read saved unverified results; never download')
    inspect.add_argument('--session-dir',type=Path,required=True)
    args=parser.parse_args(argv)
    try:
        if args.command=='prepare':
            out=prepare(args.catalog,args.output_dir,scope=args.scope,
                years=args.years.split(',') if args.years else None,
                types=args.types.split(',') if args.types else None,
                exam_codes=args.exam_codes,subjects=args.subjects,
                class_groups=args.class_groups,strategy=args.strategy,
                start_row=args.start_row,batches=args.batches,
                per_batch=args.papers_per_batch,docs_per_batch=args.documents_per_batch)
        elif args.command=='execute':
            out=execute(args.session_dir,catalog=args.catalog,
                offline_only=args.offline_only,
                download_documents=args.download_documents,
                max_batches=args.max_batches)
        else: out=audit(args.session_dir)
        print(json.dumps(out,ensure_ascii=False))
        return 0
    except (UnsafeSource,OSError,ValueError,KeyError,TypeError,ImportError,json.JSONDecodeError) as e:
        print('SAFE STOP: '+str(e)[:300]+'; stored official sources/answers unchanged',file=sys.stderr)
        return 2


if __name__=='__main__':
    raise SystemExit(main())
