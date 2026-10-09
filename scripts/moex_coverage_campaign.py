#!/usr/bin/env python3
"""Safe, small-cohort expansion over the existing LexFlow whole-paper pipeline.

This module DOES NOT download or parse PDFs itself. All source selection,
Q/S/M integrity, bounded downloads and report checks are delegated to the
already tested moex_review_series and moex_catalog_bridge modules.

'prepare' and 'summarize' never perform network operations. 'run-one' makes at
most the explicitly requested 1-3 existing batch calls, requiring explicit
--download-documents or --offline-only. All outputs are CREATE ONLY and keep
official whole-paper provenance. Nothing can enable scoring or publication.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sys

import moex_review_series as series
from moex_catalog_bridge import UnsafeSource, digest, sha256_file

SCHEMA = 'lexflow.moex.coverage-campaign.v1'
SUMMARY_SCHEMA = 'lexflow.moex.coverage-comparison.v1'
MAX_COHORTS = 8
MAX_PER_COHORT = 12
MAX_TOTAL = 96
YEAR = re.compile(r'\d{2,3}\Z')
SESSION = re.compile(r'sessions/series-[a-f0-9]{20}\Z')
CAMPAIGN = re.compile(r'campaign-[a-f0-9]{20}\.json\Z')


def encode(obj:dict) -> bytes:
    return (json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + '\n').encode('utf-8')


def create_bytes_only(path:Path, data:bytes) -> bool:
    """Termux-safe exclusive create. Existing byte-identical file is unchanged."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise UnsafeSource('refuse output through symlink: '+path.name)
    if path.exists():
        if path.read_bytes() != data:
            raise UnsafeSource('immutable report contents differ: '+path.name)
        return False
    try:
        with path.open('xb') as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
    except FileExistsError:
        if path.is_symlink() or path.read_bytes() != data:
            raise UnsafeSource('concurrent report differs: '+path.name)
        return False
    return True


def parse_groups(spec:str) -> list[list[str]]:
    """e.g. '101-103;104-106;107-109;110-112;115'; no overlapping years."""
    if not isinstance(spec,str) or len(spec)>220 or not spec.strip():
        raise UnsafeSource('missing/oversized year-group specification')
    buckets=[]; seen=set()
    for raw in spec.split(';'):
        raw=raw.strip()
        if not raw: raise UnsafeSource('empty year group')
        years=[]
        for item in raw.split(','):
            item=item.strip()
            if '-' in item:
                if item.count('-')!=1: raise UnsafeSource('invalid year range')
                low,high=item.split('-')
                if not YEAR.fullmatch(low) or not YEAR.fullmatch(high):
                    raise UnsafeSource('invalid ROC year range')
                a,b=int(low),int(high)
                if a>b or b-a>9: raise UnsafeSource('year range too large or reversed')
                years += [str(i) for i in range(a,b+1)]
            else:
                if not YEAR.fullmatch(item):raise UnsafeSource('invalid ROC year')
                years.append(str(int(item)))
        if len(years)>10 or len(years)!=len(set(years)) or seen.intersection(years):
            raise UnsafeSource('duplicate or overlapping year-group selection')
        seen.update(years)
        buckets.append(years)
    if not 1<=len(buckets)<=MAX_COHORTS:
        raise UnsafeSource('year-group count exceeds bounded campaign limit')
    return buckets


def _relative_session(root:Path, home:Path) -> str:
    try:rel=home.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as exc:raise UnsafeSource('unexpected session path outside review root') from exc
    if not SESSION.fullmatch(rel):
        raise UnsafeSource('unexpected bounded-session directory name')
    return rel


def prepare_campaign(catalog:Path, root:Path, *, year_groups:str,
                     batches:int=3,papers_per_batch:int=3,
                     documents_per_batch:int=8,scope='candidates') -> dict:
    """Make multiple EXISTING bounded sessions, not a new PDF/source engine."""
    groups=parse_groups(year_groups)
    if (not 1<=batches<=3 or not 1<=papers_per_batch<=4
        or not 1<=documents_per_batch<=8 or batches*papers_per_batch>MAX_PER_COHORT
        or len(groups)*batches*papers_per_batch>MAX_TOTAL):
        raise UnsafeSource('unsafe campaign batch sizing')
    catalog=catalog.resolve(strict=True)
    root=root.resolve()
    if root == catalog or catalog in root.parents:
        raise UnsafeSource('campaign output overlaps source catalog')
    source_sha=sha256_file(catalog)
    parts=[]; all_ids=set()
    for i,years in enumerate(groups,1):
        planned=series.prepare(catalog,root,years=years,scope=scope,
          strategy='coverage',batches=batches,per_batch=papers_per_batch,
          docs_per_batch=documents_per_batch)
        home=Path(planned['session_dir'])
        s=series.read_session(home)
        if s['catalog_sha256']!=source_sha or s['batch_count']>3:
            raise UnsafeSource('source changed during cohort planning')
        papers=[]
        for entry in s['batches']:
            obj=json.loads((home/entry['plan_path']).read_text('utf-8'))
            papers += obj['papers']
        ids=[p['paper_id'] for p in papers]
        if set(ids)&all_ids or len(set(ids))!=len(ids):
            raise UnsafeSource('repeat official Q paper across coverage cohorts')
        if any(p['year_roc'] not in years for p in papers):
            raise UnsafeSource('cohort selected unexpected official year')
        all_ids.update(ids)
        parts.append({'index':i,'year_filter':years,
          'session_path':_relative_session(root,home),
          'session_id':s['session_id'],
          'paper_ids':ids,'selected_papers':len(ids),
          'source_document_budget':sum(len(p['links']) for p in papers),
          'official_types':dict(sorted(Counter(p['official_type'] for p in papers).items())),
          'legal_title_classes':dict(sorted(Counter(p['legal_candidate_class'] for p in papers).items())),
          'official_exam_codes':sorted({p['exam_code'] for p in papers}),
          'actual_year_rocs':sorted({p['year_roc'] for p in papers}),
          'title_relevance_requires_review':sum(p['legal_candidate_class']=='跨領域涉法候選（待複核）' for p in papers)})
    if sha256_file(catalog)!=source_sha:
        raise UnsafeSource('catalog modified during full cohort preparation')
    identity={'catalog_sha256':source_sha,'year_groups':groups,
              'scope':scope,'batches':batches,'papers_per_batch':papers_per_batch,
              'documents_per_batch':documents_per_batch}
    campaign_id=digest(encode(identity))[:20]
    manifest={'schema':SCHEMA,'campaign_id':campaign_id,
      'catalog_sha256':source_sha,'catalog_basename':catalog.name,
      'year_groups':groups,'cohorts':parts,'cohort_count':len(parts),
      'source_scope':scope,'batches_per_cohort':batches,
      'papers_per_batch':papers_per_batch,'documents_per_batch':documents_per_batch,
      'planned_whole_papers':len(all_ids),
      'planned_source_documents':sum(p['source_document_budget'] for p in parts),
      'all_plan_paper_ids_unique':True,'network_downloads_this_step':0,
      'official_question_counts_verified':False,
      'legal_relevance_of_every_selected_paper_verified':False,
      'human_answers_verified':False,'publication_allowed':False,'scoring_enabled':False,
      'private_attempts_included':False,
      'note':'Only official catalog source plans. No PDF was downloaded or scored by this step.'}
    output=root/'campaigns'/f'campaign-{campaign_id}.json'
    create_bytes_only(output,encode(manifest))
    return {'status':'PLANNED_ONLY_NO_PDF_DOWNLOAD',
      'campaign_path':str(output),'cohorts':len(parts),
      'papers':len(all_ids),'official_QSM_document_references':manifest['planned_source_documents'],
      'years':sorted({y for g in groups for y in g},key=int),
      'candidate_title_relevance_needs_review':sum(p['title_relevance_requires_review'] for p in parts),
      'scoring_enabled':False,'publication_allowed':False}


def read_campaign(path:Path, *, catalog:Path|None=None):
    path=path.resolve(strict=True)
    root=path.parent.parent
    if path.parent!=root/'campaigns' or not CAMPAIGN.fullmatch(path.name):
        raise UnsafeSource('unexpected campaign manifest location')
    m=json.loads(path.read_text('utf-8'))
    if (not isinstance(m,dict) or m.get('schema')!=SCHEMA
        or m.get('scoring_enabled') is not False
        or m.get('publication_allowed') is not False
        or m.get('human_answers_verified') is not False
        or m.get('private_attempts_included') is not False
        or m.get('official_question_counts_verified') is not False
        or not isinstance(m.get('cohorts'),list)
        or not 1<=len(m['cohorts'])<=MAX_COHORTS
        or m.get('cohort_count')!=len(m['cohorts'])
        or not re.fullmatch(r'[0-9a-f]{64}',str(m.get('catalog_sha256','')))
        or path.name!=f"campaign-{m.get('campaign_id')}.json"):
        raise UnsafeSource('corrupt/publishing-enabled campaign manifest')
    identity={'catalog_sha256':m['catalog_sha256'],
      'year_groups':m.get('year_groups'), 'scope':m.get('source_scope'),
      'batches':m.get('batches_per_cohort'),
      'papers_per_batch':m.get('papers_per_batch'),
      'documents_per_batch':m.get('documents_per_batch')}
    if digest(encode(identity))[:20]!=m['campaign_id']:
        raise UnsafeSource('campaign identity checksum differs')
    if catalog is not None and sha256_file(catalog.resolve(strict=True))!=m['catalog_sha256']:
        raise UnsafeSource('official catalog SHA changed: start a new campaign')
    seen=set(); details=[]; flattened=[]
    groups=parse_groups(';'.join(','.join(g) for g in m['year_groups']))
    if groups!=m['year_groups'] or len(groups)!=m['cohort_count']:
        raise UnsafeSource('year groups differ from immutable source')
    for i,c in enumerate(m['cohorts'],1):
        if not isinstance(c,dict) or c.get('index')!=i or not SESSION.fullmatch(str(c.get('session_path',''))):
            raise UnsafeSource('invalid cohort session location')
        home=root/c['session_path']
        if home.is_symlink() or home.resolve()!=home or home.parent!=root/'sessions':
            raise UnsafeSource('cohort session path redirects')
        s=series.read_session(home)
        ids=[pid for b in s['batches'] for pid in b['paper_ids']]
        if (s.get('session_id')!=c.get('session_id')
            or s.get('catalog_sha256')!=m['catalog_sha256']
            or ids!=c.get('paper_ids') or len(ids)!=c.get('selected_papers')
            or s['filters']['years']!=c['year_filter']
            or s['source_scope']!=m['source_scope']
            or s['batch_count']!=m['batches_per_cohort']
            or s['papers_per_batch']!=m['papers_per_batch']
            or s['docs_per_batch']!=m['documents_per_batch']
            or set(ids)&seen):
            raise UnsafeSource('cohort source plan drift or duplicate paper ID')
        seen.update(ids);details.append((home,s,c))
        cohort_papers=[]
        for b in s['batches']:
            plan=json.loads((home/b['plan_path']).read_text('utf-8'))
            cohort_papers += plan['papers']
        if (sum(len(p['links']) for p in cohort_papers)!=c['source_document_budget']
            or sorted({p['exam_code'] for p in cohort_papers})!=c['official_exam_codes']
            or sorted({p['year_roc'] for p in cohort_papers})!=c['actual_year_rocs']
            or dict(sorted(Counter(p['official_type'] for p in cohort_papers).items()))!=c['official_types']
            or dict(sorted(Counter(p['legal_candidate_class'] for p in cohort_papers).items()))!=c['legal_title_classes']):
            raise UnsafeSource('cohort metadata differs from validated whole-paper plans')
        flattened += cohort_papers
    if len(seen)!=m.get('planned_whole_papers') or len(flattened)!=len(seen):
        raise UnsafeSource('campaign whole-paper identity count inconsistent')
    if sum(c['source_document_budget'] for c in m['cohorts'])!=m.get('planned_source_documents'):
        raise UnsafeSource('campaign official Q/S/M budget modified')
    return root,m,details,flattened


def run_one(path:Path, *, catalog:Path, cohort_index:int,
            max_batches:int=1,download_documents=False,offline_only=False)->dict:
    if download_documents==offline_only:
        raise UnsafeSource('explicitly select exactly one network or cache-only mode')
    root,m,details,all_papers=read_campaign(path,catalog=catalog)
    if not 1<=cohort_index<=len(details) or not 1<=max_batches<=3:
        raise UnsafeSource('bounded cohort or batch number out of range')
    home,s,c=details[cohort_index-1]
    result=series.execute(home,catalog=catalog,download_documents=download_documents,
                          offline_only=offline_only,max_batches=max_batches)
    if result.get('scoring_enabled') is not False or result.get('publication_allowed') is not False:
        raise UnsafeSource('underlying series unexpectedly enabled scoring')
    completed=result.get('batches_confirmed_completed',0)
    return {'status':result['status'],'campaign_id':m['campaign_id'],
      'cohort_index':cohort_index,'cohort_planned_whole_papers':c['selected_papers'],
      'batches_completed_of_cohort':completed,'batches_total_for_cohort':s['batch_count'],
      'batch_limit_this_invocation':max_batches,
      'official_PDF_network_mode':download_documents,
      'candidate_report_or_cache_errors_require_review':result['status']=='PARTIAL_REVIEW_SAFE_STOP',
      'publication_allowed':False,'scoring_enabled':False}


PAPER_COLUMNS=(
 'cohort_index','years','paper_id','exam_code','official_subject','official_type','legal_title_class',
 'source_appearances','quality_state','Q_fulltext_SHA_matched','PDF_documents_reported',
 'mcq_four_option_candidates_UNVERIFIED','essay_section_candidates_UNVERIFIED',
 'positioned_answer_pairs_UNVERIFIED','answer_cells_including_special_credit_UNVERIFIED',
 'answer_pair_conflicts_count','essay_heading_needs_manual_review','official_total_question_count_confirmed',
 'scoring_enabled','publication_allowed')


def summarize_campaign(path:Path, *, catalog:Path|None=None)->dict:
    root,m,details,all_papers=read_campaign(path,catalog=catalog)
    rows=[]; cohorts=[]
    for home,s,c in details:
        result=series.audit(home)  # local official-source reports only, never HTTP
        report_path=Path(result['audit_path'])
        if report_path.parent!=(home/'audits') or report_path.is_symlink():
            raise UnsafeSource('unexpected source-quality report path')
        report=json.loads(report_path.read_text('utf-8'))
        if (report.get('schema')!=series.QUALITY_SCHEMA
            or report.get('catalog_sha256')!=m['catalog_sha256']
            or report.get('scoring_enabled') is not False
            or report.get('publication_allowed') is not False
            or report.get('human_answers_verified') is not False
            or report.get('official_total_question_count_confirmed') is not False
            or report.get('fulltext_completeness_rate') is not None):
            raise UnsafeSource('source audit is not an unscored candidate report')
        if [p['paper_id'] for p in report['papers']] != c['paper_ids']:
            raise UnsafeSource('source audit paper IDs changed between planning and reporting')
        plans=[p for b in s['batches'] for p in json.loads((home/b['plan_path']).read_text('utf-8'))['papers']]
        for src,p in zip(plans,report['papers']):
            rows.append({'cohort_index':c['index'],'years':p['year_roc'],
              'paper_id':p['paper_id'],'exam_code':p['exam_code'],
              'official_subject':p['official_subject'],'official_type':p['official_type'],
              'legal_title_class':src['legal_candidate_class'],
              'source_appearances':len(src.get('source_appearances',[])),
              'quality_state':p['state'],
              'Q_fulltext_SHA_matched':p.get('question_fulltext_sha_matched') is True,
              'PDF_documents_reported':p.get('PDF_documents_reported',0),
              'mcq_four_option_candidates_UNVERIFIED':p.get('mcq_four_option_candidates_after_repair_unverified',p.get('mcq_four_option_candidates_unverified',0)),
              'essay_section_candidates_UNVERIFIED':p.get('essay_sections_after_repair_unverified',p.get('essay_section_candidates_unverified',0)),
              'positioned_answer_pairs_UNVERIFIED':p.get('positioned_answer_pairs_unverified',0),
              'answer_cells_including_special_credit_UNVERIFIED':p.get('answer_cells_including_special_credit_unverified',0),
              'answer_pair_conflicts_count':len(p.get('answer_pair_conflicts',[])),
              'essay_heading_needs_manual_review':p.get('essay_heading_needs_manual_review') is True,
              'official_total_question_count_confirmed':False,
              'scoring_enabled':False,'publication_allowed':False})
        group=[x for x in rows if x['cohort_index']==c['index']]
        cohorts.append({'cohort_index':c['index'],'years':c['year_filter'],
          'planned_whole_papers':len(group),
          'source_Q_fulltext_SHA_matched':sum(x['Q_fulltext_SHA_matched'] for x in group),
          'PDF_documents_reported':sum(x['PDF_documents_reported'] for x in group),
          'mcq_four_option_candidates_UNVERIFIED':sum(x['mcq_four_option_candidates_UNVERIFIED'] for x in group),
          'essay_section_candidates_UNVERIFIED':sum(x['essay_section_candidates_UNVERIFIED'] for x in group),
          'positioned_answer_pairs_UNVERIFIED':sum(x['positioned_answer_pairs_UNVERIFIED'] for x in group),
          'answer_cells_including_special_credit_UNVERIFIED':sum(x['answer_cells_including_special_credit_UNVERIFIED'] for x in group),
          'answer_pair_conflicts_count':sum(x['answer_pair_conflicts_count'] for x in group),
          'essay_heading_needs_manual_review':sum(x['essay_heading_needs_manual_review'] for x in group),
          'source_states':dict(sorted(Counter(x['quality_state'] for x in group).items()))})
    report={'schema':SUMMARY_SCHEMA,'campaign_id':m['campaign_id'],
      'catalog_sha256':m['catalog_sha256'],'source_catalog_only_law_candidate_filter':True,
      'planned_whole_papers':m['planned_whole_papers'],
      'source_Q_fulltext_SHA_matched':sum(g['source_Q_fulltext_SHA_matched'] for g in cohorts),
      'PDF_documents_reported':sum(g['PDF_documents_reported'] for g in cohorts),
      'mcq_four_option_candidates_UNVERIFIED':sum(g['mcq_four_option_candidates_UNVERIFIED'] for g in cohorts),
      'essay_section_candidates_UNVERIFIED':sum(g['essay_section_candidates_UNVERIFIED'] for g in cohorts),
      'positioned_answer_pairs_UNVERIFIED':sum(g['positioned_answer_pairs_UNVERIFIED'] for g in cohorts),
      'answer_cells_including_special_credit_UNVERIFIED':sum(g['answer_cells_including_special_credit_UNVERIFIED'] for g in cohorts),
      'answer_pair_conflicts_count':sum(g['answer_pair_conflicts_count'] for g in cohorts),
      'essay_heading_needs_manual_review':sum(g['essay_heading_needs_manual_review'] for g in cohorts),
      'cohorts':cohorts,'official_total_question_count_confirmed':False,
      'fulltext_completeness_rate':None,'human_answers_verified':False,
      'publication_allowed':False,'scoring_enabled':False,'private_attempts_included':False,
      'note':'Only SHA-matched source text and UNVERIFIED question/answer candidates; no official total-question denominator.'}
    data=encode(report)
    tag=digest(data)[:20]
    details_path=root/'campaigns'/'reports'/f'coverage-{tag}.json'
    create_bytes_only(details_path,data)
    f=io.StringIO();writer=csv.DictWriter(f,fieldnames=list(PAPER_COLUMNS),lineterminator='\n')
    writer.writeheader();writer.writerows(rows)
    csv_path=root/'campaigns'/'reports'/f'papers-{tag}.csv'
    create_bytes_only(csv_path,f.getvalue().encode('utf-8-sig'))
    return {'status':'UNSCORED_OFFLINE_COMPARABLE_SOURCE_AUDIT',
      'cohort_count':len(cohorts),'planned_whole_papers':len(rows),
      'Q_fulltext_SHA_matched':report['source_Q_fulltext_SHA_matched'],
      'source_quality_report':str(details_path),
      'per_paper_CSV':str(csv_path),'publication_allowed':False,'scoring_enabled':False}


def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__)
    sub=ap.add_subparsers(dest='action',required=True)
    plan=sub.add_parser('prepare',help='OFFLINE: 1-8 bounded existing batch sessions')
    plan.add_argument('--catalog',type=Path,required=True)
    plan.add_argument('--output-dir',type=Path,required=True)
    plan.add_argument('--year-groups',required=True,help='e.g. 101-103;104-106;107-109;110-112;115')
    plan.add_argument('--batches',type=int,default=3)
    plan.add_argument('--papers-per-batch',type=int,default=3)
    plan.add_argument('--documents-per-batch',type=int,default=8)
    run=sub.add_parser('run-one',help='Explicitly execute up to 3 batches of ONE cohort')
    run.add_argument('--campaign',type=Path,required=True)
    run.add_argument('--catalog',type=Path,required=True)
    run.add_argument('--cohort-index',type=int,required=True)
    run.add_argument('--max-batches',type=int,default=1)
    choice=run.add_mutually_exclusive_group(required=True)
    choice.add_argument('--download-documents',action='store_true')
    choice.add_argument('--offline-only',action='store_true')
    quality=sub.add_parser('summarize',help='OFFLINE: comparable, unscored cohort results')
    quality.add_argument('--campaign',type=Path,required=True)
    quality.add_argument('--catalog',type=Path,required=True)
    args=ap.parse_args(argv)
    try:
        if args.action=='prepare':
            result=prepare_campaign(args.catalog,args.output_dir,year_groups=args.year_groups,
                  batches=args.batches,papers_per_batch=args.papers_per_batch,
                  documents_per_batch=args.documents_per_batch)
        elif args.action=='run-one':
            result=run_one(args.campaign,catalog=args.catalog,cohort_index=args.cohort_index,
                  max_batches=args.max_batches,download_documents=args.download_documents,
                  offline_only=args.offline_only)
        else: result=summarize_campaign(args.campaign,catalog=args.catalog)
        print(json.dumps(result,ensure_ascii=False))
        return 0
    except (OSError,ValueError,KeyError,TypeError,json.JSONDecodeError) as exc:
        print('SAFE STOP: '+str(exc)[:280]+'; original catalogs/reviews unchanged',file=sys.stderr)
        return 2

if __name__=='__main__':sys.exit(main())
