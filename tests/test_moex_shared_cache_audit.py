"""End-to-end OFFLINE tests for shared public M/S PDF cache in immutable whole-paper audits.

PDF fixtures are synthetic, NOT official answers. Every result must stay unscored.
"""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from test_moex_review_series import make_catalog
import moex_catalog_bridge as bridge
import moex_review_series as series
import moex_quality_overlay as quality

try:
    import pypdf  # noqa
except ImportError:
    pypdf=None

FIXTURES=ROOT/'tests'/'fixtures'


def sha(data):
    return hashlib.sha256(data).hexdigest()


@unittest.skipIf(pypdf is None, 'pypdf==5.9.0 needed: must also run in pinned-PDF CI job')
class SharedCacheAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home=Path(self.temp.name)
        self.csv=self.home/'catalog.csv'
        make_catalog(self.csv)
        self.review_root=self.home/'review'
        self.old_bytes=None

    def prepare(self, *,role='S'):
        if role=='M':
            # The synthetic official-field catalog uses a corrected M URL for
            # the entire 50-answer fixture; the same Q/S/M identity is kept.
            with self.csv.open(encoding='utf-8-sig',newline='') as f:
                reader=csv.DictReader(f)
                fields=reader.fieldnames
                rows=list(reader)
            for row in rows:
                if row['試題型態']=='測驗題':
                    row['測驗式試題答案網址']=row['測驗式試題答案網址'].replace('t=S','t=M')
            with self.csv.open('w',encoding='utf-8-sig',newline='') as f:
                writer=csv.DictWriter(f,fieldnames=fields)
                writer.writeheader()
                writer.writerows(rows)
        result=series.prepare(self.csv,self.review_root,batches=3,per_batch=3,docs_per_batch=8)
        session=Path(result['session_dir'])
        manifest=series.read_session(session)
        plans=[json.loads((session/e['plan_path']).read_text('utf-8')) for e in manifest['batches']]
        p=next(p for b in plans for p in b['papers'] if p['official_type']=='測驗題')
        reportroot=self.review_root/'session-reviews'/manifest['session_id']
        return session,manifest,p,reportroot

    def create_source_report(self,manifest,p,reportroot,pdf_blob, *,role='S',count=30,credit=False):
        pid=p['paper_id']
        text='科 目：法學大意\n模擬文字，並非官方試題。\n'
        url=p['links'][role] if role else None
        original={}
        if role=='S' and count:
            for n,v in quality._parse_pdf_positioned_answers(
                    pypdf.PdfReader(FIXTURES/'MOCK_S_30_POSITIONAL_NOT_OFFICIAL.pdf').pages,
                    expected_question_count=30)['candidates'].items():
                original[int(n)]=v
        qlist=[{'number':n,'candidate_status':'four_options_extracted_NEEDS_VISUAL_REVIEW',
                'review_reasons':[], 'stem_unverified':f'合成測試題 {n}（不是正式原題）',
                'options_unverified':{'A':'選項甲','B':'選項乙','C':'選項丙','D':'選項丁'},
                'published_standard_candidate': original.get(n) if role=='S' else None,
                'final_answer_verified':False,'scoring_enabled':False} for n in range(1,count+1)]
        meta=bridge.paper_metadata(p)
        report={'schema':bridge.REVIEW_SCHEMA,'paper_id':pid,'catalog_sha256':manifest['catalog_sha256'],
                'official_source':meta,'state':'downloaded_source_still_requires_human_review',
                'publication_allowed':False,'scoring_enabled':False,
                'official_final_answers_verified':False,'human_quality_gate_satisfied':False,
                'extracted_question_text':{'relative_path':f'extracted_text/{pid}.txt',
                    'sha256':sha(text.encode()),'chars':len(text),'unverified':True,'truncated':False},
                'v03_review':{'publication_allowed':False,'scoring_enabled':False,
                    'reviewed_items':[{'documents':[
                        {'role':'Q','url':p['links']['Q'],'sha256':'1'*64},
                        *([{'role':role,'url':url,'sha256':sha(pdf_blob)}] if role else [])],
                        'eligible_for_scoring':False,'warnings':[],
                        'question_answer_candidates':{'publication_allowed':False,'scoring_enabled':False,
                            'final_answer_verified':False,'candidate_question_count':count,
                            'candidate_answer_pair_count':len(original),'questions':qlist}}]}}
        (reportroot/'extracted_text').mkdir(parents=True,exist_ok=True)
        (reportroot/'reports').mkdir(parents=True,exist_ok=True)
        (reportroot/'extracted_text'/f'{pid}.txt').write_text(text,encoding='utf-8')
        rp=reportroot/'reports'/f'{pid}.json'
        bridge.save_json(rp,report)
        self.old_bytes=rp.read_bytes()
        return rp

    def populate_shared_cache(self,p,blob,role):
        folder=self.review_root/'official-review'/'official_pdf_cache'
        folder.mkdir(parents=True,exist_ok=True)
        url=p['links'][role]
        name=sha(url.encode())
        pdf=folder/(name+'.pdf')
        metadata=folder/(name+'.json')
        pdf.write_bytes(blob)
        metadata.write_text(json.dumps({'url':url,'sha256':sha(blob),'role':role},
            sort_keys=True),encoding='utf-8')
        return pdf,metadata

    def test_old_uncached_and_new_shared_cache_S30_coexist_without_false_conflict(self):
        session,m,p,root=self.prepare()
        blob=(FIXTURES/'MOCK_S_30_POSITIONAL_NOT_OFFICIAL.pdf').read_bytes()
        rp=self.create_source_report(m,p,root,blob)
        oldfile,old_preview=quality.make_overlay_from_disk(root,rp)
        self.assertEqual(old_preview['answer_PDF_source_sha256_or_state'],'not_cached')
        old_snapshot=oldfile.read_bytes()
        before=json.loads(Path(series.audit(session)['audit_path']).read_text())
        self.assertEqual(before['positioned_answer_pairs_unverified'],0)
        self.populate_shared_cache(p,blob,'S')
        after=json.loads(Path(series.audit(session)['audit_path']).read_text())
        current=next(q for q in after['papers'] if q['paper_id']==p['paper_id'])
        self.assertEqual(after['positioned_answer_pairs_unverified'],30)
        self.assertEqual(after['shared_cached_answer_sources_sha_matched'],1)
        self.assertEqual(current['quality_preview_versions_for_source'],2)
        self.assertEqual(current['quality_overlay'],'current_verified_public_cache_preview')
        self.assertEqual(current['answer_pair_conflicts'],[])
        self.assertEqual(current['positioned_answer_pairs_unverified'],30)
        self.assertEqual(rp.read_bytes(),self.old_bytes)
        self.assertEqual(oldfile.read_bytes(),old_snapshot)
        self.assertEqual(len(list((root/'quality_previews').glob('*.json'))),2)
        same=json.loads(Path(series.audit(session)['audit_path']).read_text())
        self.assertEqual(same['positioned_answer_pairs_unverified'],30)
        self.assertEqual(len(list((root/'quality_previews').glob('*.json'))),2)
        self.assertFalse(after['scoring_enabled'])
        self.assertFalse(after['publication_allowed'])

    def test_shared_M50_correction_and_49_single_answers_are_counted_separately(self):
        session,m,p,root=self.prepare(role='M')
        blob=(FIXTURES/'MOCK_M_50_POSITIONAL_NOT_OFFICIAL.pdf').read_bytes()
        rp=self.create_source_report(m,p,root,blob,role='M',count=50)
        quality.make_overlay_from_disk(root,rp)
        self.populate_shared_cache(p,blob,'M')
        after=json.loads(Path(series.audit(session)['audit_path']).read_text())
        current=next(q for q in after['papers'] if q['paper_id']==p['paper_id'])
        self.assertEqual(current['positioned_answer_pairs_unverified'],49)
        self.assertEqual(current['answer_cells_including_special_credit_unverified'],50)
        self.assertEqual(current['special_credit_number_candidates'],[20])
        self.assertEqual(after['special_credit_question_candidates'],[20])
        self.assertEqual(after['answer_cells_including_special_credit_unverified'],50)
        self.assertFalse(after['human_answers_verified'])
        self.assertFalse(after['scoring_enabled'])

    def test_cache_tamper_does_not_fall_back_to_old_valid_preview(self):
        session,m,p,root=self.prepare()
        blob=(FIXTURES/'MOCK_S_30_POSITIONAL_NOT_OFFICIAL.pdf').read_bytes()
        rp=self.create_source_report(m,p,root,blob)
        self.populate_shared_cache(p,blob,'S')
        good=json.loads(Path(series.audit(session)['audit_path']).read_text())
        self.assertEqual(good['positioned_answer_pairs_unverified'],30)
        pdf,metadata=self.populate_shared_cache(p,blob,'S')
        obj=json.loads(metadata.read_text());obj['sha256']='0'*64
        metadata.write_text(json.dumps(obj),encoding='utf-8')
        bad=json.loads(Path(series.audit(session)['audit_path']).read_text())
        current=next(q for q in bad['papers'] if q['paper_id']==p['paper_id'])
        self.assertEqual(current['quality_overlay'],'isolated_shared_answer_cache_or_overlay_failure')
        self.assertEqual(bad['positioned_answer_pairs_unverified'],0)
        self.assertEqual(bad['shared_cached_answer_sources_sha_matched'],0)
        self.assertEqual(rp.read_bytes(),self.old_bytes)
        self.assertTrue(pdf.exists())

    def test_partial_or_symlinked_cache_cannot_be_used(self):
        session,m,p,root=self.prepare()
        blob=(FIXTURES/'MOCK_S_30_POSITIONAL_NOT_OFFICIAL.pdf').read_bytes()
        rp=self.create_source_report(m,p,root,blob)
        pdf,metadata=self.populate_shared_cache(p,blob,'S')
        metadata.unlink()
        bad=json.loads(Path(series.audit(session)['audit_path']).read_text())
        cur=next(x for x in bad['papers'] if x['paper_id']==p['paper_id'])
        self.assertEqual(cur['quality_overlay'],'isolated_shared_answer_cache_or_overlay_failure')
        self.assertEqual(bad['positioned_answer_pairs_unverified'],0)
        pdf.unlink()
        external=self.home/'external.pdf';external.write_bytes(blob)
        pdf.symlink_to(external)
        metadata.write_text(json.dumps({'url':p['links']['S'],'sha256':sha(blob)}))
        bad2=json.loads(Path(series.audit(session)['audit_path']).read_text())
        cur2=next(x for x in bad2['papers'] if x['paper_id']==p['paper_id'])
        self.assertEqual(cur2['quality_overlay'],'isolated_shared_answer_cache_or_overlay_failure')
        self.assertEqual(external.read_bytes(),blob)

    def test_report_document_SHA_mismatch_blocks_cached_answer_even_if_cache_valid(self):
        session,m,p,root=self.prepare()
        blob=(FIXTURES/'MOCK_S_30_POSITIONAL_NOT_OFFICIAL.pdf').read_bytes()
        rp=self.create_source_report(m,p,root,blob)
        doc=json.loads(rp.read_text())
        doc['v03_review']['reviewed_items'][0]['documents'][1]['sha256']='f'*64
        rp.write_text(json.dumps(doc,ensure_ascii=False),encoding='utf-8')
        self.populate_shared_cache(p,blob,'S')
        bad=json.loads(Path(series.audit(session)['audit_path']).read_text())
        cur=next(x for x in bad['papers'] if x['paper_id']==p['paper_id'])
        self.assertEqual(cur['quality_overlay'],'isolated_shared_answer_cache_or_overlay_failure')
        self.assertEqual(bad['positioned_answer_pairs_unverified'],0)

    def test_original_report_and_legacy_cache_location_remain_compatible(self):
        session,m,p,root=self.prepare()
        blob=(FIXTURES/'MOCK_S_30_POSITIONAL_NOT_OFFICIAL.pdf').read_bytes()
        rp=self.create_source_report(m,p,root,blob)
        legacy=root/'official_pdf_cache'
        legacy.mkdir()
        url=p['links']['S'];name=sha(url.encode())
        (legacy/(name+'.pdf')).write_bytes(blob)
        (legacy/(name+'.json')).write_text(json.dumps({'url':url,'sha256':sha(blob)}))
        path,preview=quality.make_overlay_from_disk(root,rp)
        self.assertEqual(preview['answer_PDF_source_sha256_or_state'],sha(blob))
        self.assertEqual(preview['answer_and_correction_evidence']['table_candidate']['unique_paired_numbers'],30)
        # Series audit MUST NOT mistake per-session private cache for the verified shared cache.
        audit=json.loads(Path(series.audit(session)['audit_path']).read_text())
        self.assertEqual(audit['positioned_answer_pairs_unverified'],0)
        self.assertFalse(audit['scoring_enabled'])

    def test_corrupted_legacy_overlay_isolated_not_silently_ignored(self):
        session,m,p,root=self.prepare()
        blob=(FIXTURES/'MOCK_S_30_POSITIONAL_NOT_OFFICIAL.pdf').read_bytes()
        rp=self.create_source_report(m,p,root,blob)
        preview=root/'quality_previews'
        preview.mkdir(parents=True)
        (preview/(p['paper_id']+'-deadbeef00000000.json')).write_text('{bad json',encoding='utf-8')
        audit=json.loads(Path(series.audit(session)['audit_path']).read_text())
        paper=next(x for x in audit['papers'] if x['paper_id']==p['paper_id'])
        self.assertEqual(paper['quality_overlay'],'isolated_malformed_quality_preview')
        self.assertEqual(audit['positioned_answer_pairs_unverified'],0)
        self.assertEqual(rp.read_bytes(),self.old_bytes)

    def test_essay_with_unidentified_headings_is_reported_not_invented(self):
        session,m,p,root=self.prepare()
        chosen=None
        for e in m['batches']:
            plan=json.loads((session/e['plan_path']).read_text())
            for paper in plan['papers']:
                if paper['official_type']=='申論題':chosen=paper;break
            if chosen:break
        self.assertIsNotNone(chosen)
        blob=(FIXTURES/'MOCK_S_30_POSITIONAL_NOT_OFFICIAL.pdf').read_bytes()
        rp=self.create_source_report(m,chosen,root,blob,role=None,count=0)
        # A synthetic standalone essay has Q metadata and no answer PDF.
        audit=json.loads(Path(series.audit(session)['audit_path']).read_text())
        cur=next(x for x in audit['papers'] if x['paper_id']==chosen['paper_id'])
        self.assertEqual(cur['essay_heading_needs_manual_review'],True)
        self.assertEqual(audit['essay_papers_with_headings_needing_review'],1)
        self.assertFalse(cur['scoring_enabled'])

if __name__=='__main__': unittest.main()
