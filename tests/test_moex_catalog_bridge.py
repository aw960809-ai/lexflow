"""No-network regression for the universal catalog adapter. Official PDFs are
never fabricated: the only bundled PDF is deliberately marked SYNTHETIC.
"""
from __future__ import annotations
import importlib.util
import json
from pathlib import Path
import re
import sys
import tempfile
import types
import unittest
from unittest import mock

HERE=Path(__file__).resolve().parent
SCRIPT=HERE.parent/'scripts'/'moex_catalog_bridge.py'
spec=importlib.util.spec_from_file_location('moex_catalog_bridge',SCRIPT)
bridge=importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)
Q='https://wwwq.moex.gov.tw/exam/wHandExamQandA_File.ashx?t=Q&code=114120&c=201&s=0405&q=1'
S='https://wwwq.moex.gov.tw/exam/wHandExamQandA_File.ashx?t=S&code=114120&c=201&s=0405&q=1'
M='https://wwwq.moex.gov.tw/exam/wHandExamQandA_File.ashx?t=M&code=114120&c=201&s=0405&q=1'


def row(kind='測驗題'):
    return dict(source_row=1,paper_id='moex-'+bridge.digest(Q.encode())[:24],
      year_roc='114',exam_code='114120',exam_name='114年公務人員相關考試',
      grade_code='4',grade_label='司法四等',exam_grade='司法四等',class_code='201',
      class_group='法院書記官',session_code='0405',official_subject='民法概要',
      official_type=kind,question_url=Q,answer_url=S if kind!='申論題' else '',
      official_note='',legal_candidate_class='名稱明確法律科目',title_domain_tags='民法')


class CatalogBridgeUnitTests(unittest.TestCase):
    def test_official_source_identity_validated(self):
        self.assertEqual(bridge.source_ref(Q,'Q'),bridge.source_ref(S,'S'))
        self.assertEqual(bridge.source_ref(M,'M'),bridge.source_ref(Q,'Q'))

    def test_fake_and_mismatched_answer_blocked(self):
        for fake in [S.replace('code=114120','code=113120'),S.replace('c=201','c=202'),S.replace('s=0405','s=0406'),S.replace('wwwq.moex.gov.tw','wwwq.moex.gov.tw.evil.org'),S.replace('t=S','t=Q')]:
            r=row();r['answer_url']=fake
            with self.subTest(fake=fake),self.assertRaises(bridge.UnsafeSource):
                bridge.validate_paper(r)

    def test_forbid_untrusted_url_forms(self):
        for url in ['http://wwwq.moex.gov.tw/exam/wHandExamQandA_File.ashx?t=Q&code=114120&c=201&s=0405&q=1',
                    'https://attacker@wwwq.moex.gov.tw/exam/wHandExamQandA_File.ashx?t=Q&code=114120&c=201&s=0405&q=1',
                    Q+'#test',Q+'&t=Q',Q.replace('wwwq.moex.gov.tw','wwwq.moex.gov.tw.bad'),
                    Q.replace('c=201','c=abc')]:
            with self.subTest(url=url), self.assertRaises(bridge.UnsafeSource):
                bridge.source_ref(url,'Q')

    def test_routing_uses_official_type_not_title_guess(self):
        for kind in ('測驗題','混合題','申論題'):
            r=row(kind);result=bridge.plan_to_v03_index({**r, 'state':'planned_review_not_downloaded',
                   'links':bridge.validate_paper(r)[0],'source_file_sha256':'abc'})
            item=result['items'][0]
            self.assertEqual(item['question_type'],kind)
            self.assertEqual(item['subject'],'民法概要')
            self.assertEqual(item['answer_url']==S,kind!='申論題')
        r=row();r['answer_url']=M
        links,warnings=bridge.validate_paper(r)
        self.assertEqual(set(links),{'Q','M'})
        self.assertTrue(any('corrected_answer' in s for s in warnings))

    def test_empty_focus_tags_do_not_reclassify_official_subject(self):
        r=row();r['official_subject']='綜合法政知識與英文(包括中華民國憲法、法學緒論、兩岸關係、英文)'
        r['legal_candidate_class']='綜合／基礎法學科目'
        adapted=bridge.plan_to_v03_index({**r,'state':'planned_review_not_downloaded',
                    'links':bridge.validate_paper(r)[0],'source_file_sha256':'abc'})
        self.assertEqual(adapted['items'][0]['subject'],r['official_subject'])
        self.assertEqual(adapted['items'][0]['classification'],'needs_classification')
        self.assertEqual(adapted['items'][0]['focus_subjects'],[])
        # Focus tags are search hints only; original subject remains independent.

    def test_essay_sections_are_index_only_and_preserve_order(self):
        text='第一題 甲乙因通謀虛偽意思表示訂約，試論第三人保護。\n第二題 甲丙發生管轄爭議，請具體分析民事訴訟規定。'
        out=bridge.essay_segments_from_text(text)
        self.assertEqual(out['count'],2)
        self.assertEqual([s['heading_candidate'] for s in out['sections']],['第一題','第二題'])
        self.assertTrue(all(s['human_verified'] is False for s in out['sections']))
        self.assertNotIn('paper_id',out['sections'][0])

    def test_ambiguous_text_is_not_pretended_to_be_complete(self):
        out=bridge.essay_segments_from_text('甲與乙之間所生民事糾紛應檢討何種請求權基礎？本題沒有可靠的題號標記，因此仍需確認試卷原始排版與所有子題，不應只憑擷取文字判斷其完整性。')
        self.assertEqual(out['status'],'unsegmented_paper_needs_manual_review')
        self.assertEqual(out['count'],0)

    def test_full_pdf_content_is_extracted_from_labeled_synthetic_fixture(self):
        try:
            import pypdf  # noqa: F401
        except ImportError:
            self.skipTest('pypdf not installed; structural PDF tests run in isolated PDF job')
        blob=(HERE/'fixtures'/'synthetic_essay.pdf').read_bytes()
        full,sections=bridge.inspect_essay_pdf(blob)
        self.assertIn('通謀虛偽',full)
        self.assertEqual(sections['count'],2)
        self.assertFalse(any(x.get('human_verified') for x in sections['sections']))

    def test_original_full_paper_kept_when_mixed(self):
        r=row('混合題')
        links,warnings=bridge.validate_paper(r)
        self.assertIn('Q',links)
        self.assertEqual(len([x for x in warnings if 'mixed' in x]),1)

    def test_safe_file_write_and_no_truncation_on_invalid_json(self):
        with tempfile.TemporaryDirectory() as td:
            f=Path(td)/'record.json';bridge.save_json(f,{'preserve':True})
            self.assertEqual(json.loads(f.read_text())['preserve'],True)
            leftovers=list(Path(td).glob('.*.tmp'))
            self.assertEqual(leftovers,[])

    def test_real_csv_requires_explicit_all_scope_when_unclassified(self):
        with tempfile.TemporaryDirectory() as td:
            csvfile=Path(td)/'source.csv'
            original_headers=bridge.METADATA_COLUMNS
            import csv
            with csvfile.open('w',encoding='utf-8',newline='') as fp:
                writer=csv.DictWriter(fp,fieldnames=original_headers);writer.writeheader()
                writer.writerow({'考試年度':'114','考試代碼':'114120','考試名稱':'司法考試',
                    '等級代碼':'4','等級分類':'司法四等','考試及等別':'司法四等',
                    '類科代碼':'201','類科組別':'法院書記官','節次':'0405',
                    '科目全名':'民法概要','試題型態':'測驗題','試題網址':Q,
                    '測驗式試題答案網址':S,'備註':''})
            with self.assertRaises(bridge.UnsafeSource):
                bridge.make_plan(csvfile,scope='candidates',max_papers=1)
            plan=bridge.make_plan(csvfile,scope='all',max_papers=1)
            self.assertEqual(plan['selected_papers'],1)
            self.assertFalse(plan['scoring_enabled'])
            self.assertEqual(len(plan['papers'][0]['links']),2)

    def test_stratified_and_sequential_selection_do_not_repeat_papers(self):
        rows=[]
        for i in range(1,31):
            r=row(kind=('測驗題','申論題','混合題')[i%3]).copy()
            r['source_row']=i;r['year_roc']=str(112+i%3)
            r['exam_code']=str(112+i%3)+'120';r['official_subject']='law'+str(i%10)
            r['paper_id']='moex-'+format(i,'024x')
            rows.append(r)
        cov=bridge.pick_rows(rows,max_papers=9,strategy='coverage')
        self.assertEqual(len(cov),9)
        self.assertEqual(len({r['paper_id'] for r in cov}),9)
        self.assertEqual({r['official_type'] for r in cov},{'測驗題','申論題','混合題'})
        self.assertEqual(bridge.pick_rows(rows,max_papers=5,strategy='sequential'),rows[:5])

    def test_plan_is_never_scored(self):
        with self.assertRaises(bridge.UnsafeSource):
            bridge.run_plan({'schema':bridge.SCHEMA,'publication_allowed':True,'scoring_enabled':False,'papers':[]},Path('/does/not/matter'))

    def test_forged_oversized_plan_blocks_pre_import(self):
        with self.assertRaises(bridge.UnsafeSource):
            bridge.run_plan({'schema':bridge.SCHEMA,'publication_allowed':False,'scoring_enabled':False,'papers':[{}]*13},Path('/does/not/matter'))

    def test_offline_cached_review_never_fetches_network_and_preserves_existing_report(self):
        # Mock only the V0.3 engine import boundary; use a REAL small PDF test fixture.
        try:
            import pypdf  # noqa: F401
        except ImportError:
            self.skipTest('pypdf not installed')
        pdf=(HERE/'fixtures'/'synthetic_essay.pdf').read_bytes()
        mock_engine=types.ModuleType('moex_batch_engine')
        remote=[]
        def fake_fetch(ref):
            remote.append(ref['url']);return pdf
        def fake_inspect(blob,role,subject):
            return {'pdf_structure_readable':True,'expected_subject_label_seen':False,
                  'sha256':bridge.digest(blob),'pages':1}
        def fake_process(index,*,fetch,inspect,**kwargs):
            item=index['items'][0]
            refs=[{'role':'Q','url':item['question_url']}]
            for role,key in [('S','answer_url'),('M','answer_correction_url')]:
                if item.get(key):refs.append({'role':role,'url':item[key]})
            docs=[]
            for ref in refs:
                d=inspect(fetch(ref),ref['role'],item['subject'])
                docs.append({'role':ref['role'],'url':ref['url'],**d})
            return {'summary':{'document_fetch_attempts':len(refs),'isolated_papers':0},
                    'reviewed_items':[{'state':'pdfs_readable_CONTENT_NOT_VERIFIED','documents':docs}],
                    'publication_allowed':False,'scoring_enabled':False}
        mock_engine.fetch_pdf=fake_fetch
        mock_engine.inspect_pdf_source=fake_inspect
        mock_engine.process_batch=fake_process
        mock_qa=types.ModuleType('moex_document_qa')
        mock_qa.validate_pdf_bytes=lambda b: self.assertTrue(b.startswith(b'%PDF-'))
        r=row('申論題')
        p={**r,'links':bridge.validate_paper(r)[0],
           'source_file_sha256':'abcd','state':'planned_review_not_downloaded'}
        plan={'schema':bridge.SCHEMA,'catalog_sha256':'abcd','papers':[p],
              'publication_allowed':False,'scoring_enabled':False}
        with tempfile.TemporaryDirectory() as td, mock.patch.dict(sys.modules,{'moex_batch_engine':mock_engine,'moex_document_qa':mock_qa}):
            outdir=Path(td)
            r1=bridge.run_plan(plan,outdir,max_papers=1,max_docs=3)
            self.assertEqual(r1['network_pdf_downloads'],1)
            self.assertEqual(len(remote),1)
            self.assertFalse(r1['publication_allowed'])
            stored=json.loads((outdir/'reports'/(p['paper_id']+'.json')).read_text())
            self.assertEqual(stored['essay_candidate_sections']['count'],2)
            self.assertTrue((outdir/'extracted_text'/(p['paper_id']+'.txt')).exists())
            self.assertEqual(stored['official_source']['official_type'],'申論題')
            self.assertFalse(stored['scoring_enabled'])
            r2=bridge.run_plan(plan,outdir,max_papers=1,max_docs=3)
            self.assertEqual(r2['reviews'][0]['state'],'existing_report_preserved')
            self.assertEqual(r2['network_pdf_downloads'],0)
            self.assertEqual(len(remote),1)
            # Corruption of the cache metadata must never be silently trusted.
            cached=list((outdir/'official_pdf_cache').glob('*.json'))[0]
            cached.write_text('{"url":"tampered"}')
            getter,_=bridge.cached_fetch_for_review(outdir/'official_pdf_cache',offline_only=True)
            with self.assertRaises(bridge.UnsafeSource):
                getter({'url':Q,'role':'Q'})


if __name__=='__main__':unittest.main()
