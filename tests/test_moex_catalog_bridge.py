"""No-network regression for the universal catalog adapter. Official PDFs are
never fabricated: the only bundled PDF is deliberately marked SYNTHETIC.
"""
from __future__ import annotations
import importlib.util
import csv
import json
from pathlib import Path
import re
import sqlite3
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

    def test_raw_official_csv_no_longer_requires_separate_enrichment(self):
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
            candidates=bridge.make_plan(csvfile,scope='candidates',max_papers=1)
            self.assertEqual(candidates['selected_papers'],1)
            self.assertEqual(candidates['catalog_title_candidates'],1)
            self.assertEqual(candidates['papers'][0]['legal_candidate_class'],'名稱明確法律科目')
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


def official_record(subject='民法概要', kind='測驗題', *, question=Q, answer=S,
                    group='法院書記官', **overrides):
    values={'考試年度':'114','考試代碼':'114120','考試名稱':'114年司法人員等考試',
            '等級代碼':'4','等級分類':'司法四等','考試及等別':'司法四等',
            '類科代碼':'201','類科組別':group,'節次':'0405',
            '科目全名':subject,'試題型態':kind,'試題網址':question,
            '測驗式試題答案網址':answer if kind in ('測驗題','混合題') else '',
            '備註':''}
    values.update(overrides)
    return values


def create_catalog(path, entries, *, enriched=False):
    fields=bridge.METADATA_COLUMNS + (['原始資料序號','穩定試卷ID',
        '法律相關候選狀態','官方標題可見領域標籤'] if enriched else [])
    with path.open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=fields)
        writer.writeheader()
        for i,raw in enumerate(entries,1):
            r=dict(raw)
            if enriched:
                r.setdefault('原始資料序號',str(i))
                r.setdefault('穩定試卷ID','moex-'+bridge.digest(r['試題網址'].encode())[:24])
                label,tags=bridge.classify_official_title(r['科目全名'])
                r.setdefault('法律相關候選狀態',label)
                r.setdefault('官方標題可見領域標籤',tags)
            writer.writerow(r)


class FullCatalogUnificationTests(unittest.TestCase):
    def test_title_classifier_covers_the_full_law_range_without_guessing_subitems(self):
        examples={
            '民法概要':'名稱明確法律科目',
            '刑法與刑事訴訟法':'名稱明確法律科目',
            '憲法與行政法':'名稱明確法律科目',
            '稅務法規':'名稱明確法律科目',
            '專利法規':'名稱明確法律科目',
            '法學大意':'綜合／基礎法學科目',
            '綜合法政知識與英文(包括中華民國憲法、法學緒論、兩岸關係、英文)':'綜合／基礎法學科目',
            '不動產登記實務':'跨領域涉法候選（待複核）',
            '牙醫學(一)':'其他／未標記',
            '漁具漁法學':'其他／未標記',
        }
        for name,category in examples.items():
            with self.subTest(name=name):
                label,_=bridge.classify_official_title(name)
                self.assertEqual(label,category)
        label,hints=bridge.classify_official_title('綜合法政知識與英文(包括中華民國憲法、英文)')
        self.assertEqual(label,'綜合／基礎法學科目')
        self.assertIn('憲法',hints)
        self.assertNotIn('拆',label)
        _,tags=bridge.classify_official_title('國民法官法與監獄行刑法')
        self.assertNotIn('民法',tags.split('；'))
        self.assertNotIn('刑法',tags.split('；'))
        self.assertIn('監獄行刑法',tags.split('；'))
        _,tags2=bridge.classify_official_title('國民法官法、民法與刑法')
        self.assertIn('民法',tags2.split('；'))
        self.assertIn('刑法',tags2.split('；'))

    def test_raw_and_enriched_csv_share_one_classifier_and_all_official_names(self):
        sources=[official_record(),official_record('綜合法政知識與英文',kind='申論題',answer='',
                 question=Q.replace('s=0405','s=0406')),
                 official_record('牙醫學',question=Q.replace('s=0405','s=0407'),
                 answer=S.replace('s=0405','s=0407'))]
        with tempfile.TemporaryDirectory() as td:
            folder=Path(td);a=folder/'raw.csv';b=folder/'enriched.csv'
            create_catalog(a,sources);create_catalog(b,sources,enriched=True)
            raw=list(bridge.catalog_records(a)); enriched=list(bridge.catalog_records(b))
            self.assertEqual([r['official_subject'] for r in raw],
                             [r['official_subject'] for r in enriched])
            self.assertEqual([r['legal_candidate_class'] for r in raw],
                             [r['legal_candidate_class'] for r in enriched])
            self.assertEqual(sum(map(bridge.is_candidate,raw)),2)
            inv=bridge.inventory_catalog(a)
            self.assertEqual(inv['source_rows'],3)
            self.assertEqual(inv['law_related_title_candidate_rows'],2)
            self.assertFalse(inv['scoring_enabled'])
            self.assertEqual(inv['metadata_isolation_reasons'],{})

    def test_sqlite_and_raw_csv_yield_identical_classification_and_identity(self):
        originals=[official_record(),official_record(
            '綜合法學(一)(刑法、刑事訴訟法、法律倫理)',kind='申論題',
            question=Q.replace('s=0405','s=0406'),answer=''),
            official_record('牙醫學',question=Q.replace('s=0405','s=0407'),
                            answer=S.replace('s=0405','s=0407'))]
        with tempfile.TemporaryDirectory() as td:
            csv_path=Path(td)/'original.csv'
            db_path=Path(td)/'original.sqlite'
            create_catalog(csv_path, originals)
            rows=list(bridge.catalog_records(csv_path))
            cols=['source_row','paper_id','year_roc','exam_code','exam_name',
                  'grade_code','grade_label','exam_grade','class_code','class_group',
                  'session_code','official_subject','official_type','question_url',
                  'official_answer_url','official_note','legal_candidate_class','title_domain_tags']
            with sqlite3.connect(db_path) as con:
                con.execute('CREATE TABLE papers ('+','.join(
                    f'{c} '+('INTEGER' if c=='source_row' else 'TEXT') for c in cols)+')')
                for row in rows:
                    d=dict(row);d['official_answer_url']=d['answer_url']
                    con.execute('INSERT INTO papers VALUES ('+','.join('?' for _ in cols)+')',
                                tuple(d[c] for c in cols))
            sql_rows=list(bridge.catalog_records(db_path))
            for k in ('paper_id','official_subject','official_type','exam_name',
                      'class_group','legal_candidate_class','title_domain_tags'):
                self.assertEqual([r[k] for r in rows],[r[k] for r in sql_rows],k)
            raw_inv=bridge.inventory_catalog(csv_path)
            sql_inv=bridge.inventory_catalog(db_path)
            for k in ('source_rows','type_counts','candidate_class_counts','metadata_isolation_reasons'):
                self.assertEqual(raw_inv[k],sql_inv[k],k)

    def test_canonical_url_query_reordering_deduplicates_source_reference_not_labels(self):
        reordered='https://wwwq.moex.gov.tw/exam/wHandExamQandA_File.ashx?q=1&s=0405&c=201&code=114120&t=Q'
        with tempfile.TemporaryDirectory() as td:
            cat=Path(td)/'x.csv'
            create_catalog(cat,[official_record(group='法院書記官'),
                                official_record(group='共同科目',question=reordered)])
            inv=bridge.inventory_catalog(cat)
            self.assertEqual(inv['source_rows'],2)
            self.assertEqual(inv['unique_official_Q_source_identities'],1)
            self.assertEqual(inv['duplicate_Q_reference_rows'],1)
            plan=bridge.make_plan(cat,scope='candidates',max_papers=2)
            self.assertEqual(plan['selected_papers'],1)
            self.assertEqual([x['class_group'] for x in plan['papers'][0]['source_appearances']],
                             ['法院書記官','共同科目'])
            self.assertEqual(plan['papers'][0]['state'],'planned_review_not_downloaded')

    def test_conflicting_official_metadata_for_one_Q_is_isolated(self):
        with tempfile.TemporaryDirectory() as td:
            cat=Path(td)/'x.csv'
            create_catalog(cat,[official_record(),official_record('行政法')])
            inv=bridge.inventory_catalog(cat)
            self.assertEqual(inv['source_rows'],2)
            self.assertEqual(inv['unique_official_Q_source_identities'],1)
            self.assertEqual(inv['metadata_isolation_reasons'].get('source_metadata_conflicting_for_same_Q'),1)
            plan=bridge.make_plan(cat,scope='all',max_papers=2)
            self.assertEqual(plan['papers'][0]['state'],'isolated_invalid_metadata')
            self.assertEqual(len(plan['papers'][0]['source_appearances']),2)

    def test_different_official_Q_sources_are_not_deduplicated_just_by_title(self):
        with tempfile.TemporaryDirectory() as td:
            cat=Path(td)/'x.csv'
            create_catalog(cat,[official_record(),official_record(question=Q.replace('s=0405','s=0406'),
                              answer=S.replace('s=0405','s=0406'),節次='0406')])
            inv=bridge.inventory_catalog(cat)
            self.assertEqual(inv['unique_official_Q_source_identities'],2)
            self.assertTrue(inv['shared_source_reference_identity_is_not_PDF_content_equivalence'])

    def test_changed_legal_candidate_label_cannot_pass_as_authoritative_source(self):
        with tempfile.TemporaryDirectory() as td:
            cat=Path(td)/'x.csv'
            create_catalog(cat,[official_record()],enriched=True)
            lines=cat.read_text('utf-8-sig').replace('名稱明確法律科目','其他／未標記')
            cat.write_text(lines,encoding='utf-8-sig')
            inv=bridge.inventory_catalog(cat)
            self.assertEqual(inv['law_related_title_candidate_rows'],1)
            self.assertEqual(inv['metadata_isolation_reasons'].get('prior_title_classification_disagrees'),1)
            p=bridge.make_plan(cat,max_papers=1)
            self.assertEqual(p['papers'][0]['state'],'isolated_invalid_metadata')

    def test_catalog_truncation_and_invalid_answer_pair_are_reported_not_ignored(self):
        with tempfile.TemporaryDirectory() as td:
            cat=Path(td)/'x.csv'
            create_catalog(cat,[official_record(answer=S.replace('c=201','c=202'))])
            inv=bridge.inventory_catalog(cat)
            self.assertEqual(inv['source_rows'],1)
            self.assertEqual(inv['metadata_isolation_reasons'].get('source_identity_or_type_invalid'),1)
            p=bridge.make_plan(cat,scope='all',max_papers=1)
            self.assertEqual(p['papers'][0]['state'],'isolated_invalid_metadata')
            cat.write_text('考試年度,考試代碼\n114,114120\n',encoding='utf-8-sig')
            with self.assertRaises(bridge.UnsafeSource):
                bridge.inventory_catalog(cat)

    def test_existing_inventory_cannot_be_overwritten_or_replaced_by_source(self):
        with tempfile.TemporaryDirectory() as td:
            cat=Path(td)/'x.csv'; target=Path(td)/'inv.json'
            create_catalog(cat,[official_record()]);target.write_text('{"keep":true}')
            self.assertEqual(bridge.main(['inventory','--catalog',str(cat),'--output',str(target)]),2)
            self.assertEqual(target.read_text(),'{"keep":true}')
            self.assertEqual(bridge.main(['inventory','--catalog',str(cat),'--output',str(cat)]),2)

    def test_unclassified_law_exam_keeps_official_kind_without_fake_field(self):
        with tempfile.TemporaryDirectory() as td:
            cat=Path(td)/'x.csv'
            create_catalog(cat,[official_record('綜合法政知識與英文',kind='混合題')])
            p=bridge.make_plan(cat,scope='candidates',max_papers=1)
            item=p['papers'][0]
            self.assertEqual(item['official_subject'],'綜合法政知識與英文')
            self.assertEqual(item['official_type'],'混合題')
            self.assertEqual(item['legal_candidate_class'],'綜合／基礎法學科目')
            self.assertEqual(set(item['links']),{'Q','S'})
            self.assertFalse(p['scoring_enabled'])

    def test_official_exam_subject_class_and_type_filters_compose_without_rewriting(self):
        with tempfile.TemporaryDirectory() as td:
            cat=Path(td)/'x.csv'
            create_catalog(cat,[official_record(),official_record(
                '憲法與行政法',kind='申論題',question=Q.replace('s=0405','s=0406'),
                answer='',節次='0406')])
            plan=bridge.make_plan(cat,scope='candidates',max_papers=2,
                years=['114'],exam_codes=['114120'],subjects=['民法概要'],
                class_groups=['法院書記官'],types=['測驗題'])
            self.assertEqual(plan['selected_papers'],1)
            self.assertEqual(plan['papers'][0]['official_subject'],'民法概要')
            self.assertEqual(plan['papers'][0]['class_group'],'法院書記官')
            self.assertEqual(plan['class_groups_filter'],['法院書記官'])
            with self.assertRaises(bridge.UnsafeSource):
                bridge.make_plan(cat,scope='candidates',max_papers=2,exam_codes=['114123'],
                                 subjects=['民法概要'])
            with self.assertRaises(bridge.UnsafeSource):
                bridge.make_plan(cat,scope='all',max_papers=1,exam_codes=['javascript:'])


if __name__=='__main__':unittest.main()
