"""No-network, no-scoring integration tests for bounded whole-paper batches."""
from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
import moex_review_series as series
import moex_catalog_bridge as bridge


def url(role: str, code: str, klass: str, subject_code: str) -> str:
    return (f'https://wwwq.moex.gov.tw/exam/wHandExamQandA_File.ashx?'
            f't={role}&code={code}&c={klass}&s={subject_code}&q=1')


def make_catalog(path: Path, *, n=9) -> None:
    with path.open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f,fieldnames=bridge.METADATA_COLUMNS)
        writer.writeheader()
        # 3 types, 2 years, 3 exam codes, 9 DISTINCT official Q identities.
        for i in range(n):
            year = '113' if i%2==0 else '114'
            code = f'{year}0{10+(i//3)*10}'
            grade = '30'+str(i%3)
            subject_code = f'{100+i:04d}'
            typ = ('測驗題','申論題','混合題')[i%3]
            subject = ('法學大意','行政法','綜合法政知識與英文')[i%3]
            writer.writerow({'考試年度':year,'考試代碼':code,'考試名稱':'合成官方欄位測試考試',
               '等級代碼':'3','等級分類':'三等','考試及等別':'三等考試',
               '類科代碼':grade,'類科組別':'法律組', '節次':subject_code,
               '科目全名':subject, '試題型態':typ,
               '試題網址':url('Q',code,grade,subject_code),
               '測驗式試題答案網址':url('S',code,grade,subject_code) if typ!='申論題' else '',
               '備註':''})


def dummy_run(plan, outdir, *, max_papers, max_docs, start_at, offline_only, shared_cache_root=None):
    outdir.mkdir(parents=True,exist_ok=True)
    results=[]
    for p in plan['papers']:
        pid=p['paper_id']
        doc=outdir/'reports'/(pid+'.json')
        if not doc.exists():
            txt='第一題：此為合成測試文句，不是實際的考選部題幹。'
            src=outdir/'extracted_text'/(pid+'.txt');src.parent.mkdir(parents=True,exist_ok=True)
            src.write_text(txt,encoding='utf-8')
            rep={'paper_id':pid,'catalog_sha256':plan['catalog_sha256'],
                 'official_source':{'question_url':p['question_url'],
                     'official_type':p['official_type']},
                 'state':'downloaded_source_still_requires_human_review',
                 'publication_allowed':False,'scoring_enabled':False,
                 'extracted_question_text':{'sha256':hashlib.sha256(txt.encode()).hexdigest(),
                     'relative_path':'extracted_text/'+pid+'.txt',
                     'chars':len(txt),'truncated':False},
                 'v03_review':{'scoring_enabled':False,'publication_allowed':False,
                    'reviewed_items':[{'documents':[{'role':'Q','url':p['links']['Q']}],
                     'warnings':[],
                     'question_answer_candidates':{'candidate_question_count':2,
                         'candidate_answer_pair_count':1}}]},
                 'essay_candidate_sections':{'count':1}}
            bridge.save_json(doc,rep)
            status='downloaded_source_still_requires_human_review'
        else: status='existing_report_preserved'
        results.append({'paper_id':pid,'state':status})
    return {'reviews':results,'network_pdf_downloads':0 if offline_only else len(results),
            'cache_reuses':0, 'publication_allowed':False,'scoring_enabled':False}


class BoundedSeriesTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.csv=self.root/'catalog.csv';make_catalog(self.csv)
        self.out=self.root/'review'

    def prep(self,**opts):
        return series.prepare(self.csv,self.out,batches=3,per_batch=3,docs_per_batch=8,**opts)

    def test_prepare_uses_official_type_and_all_three_kinds(self):
        v=self.prep(strategy='coverage')
        self.assertEqual(v['selected_papers'],9)
        self.assertEqual(v['type_counts'],{'測驗題':3,'申論題':3,'混合題':3})
        self.assertEqual(v['year_rocs'],['113','114'])
        self.assertGreaterEqual(len(v['exam_codes']),3)
        self.assertIsNone(v['cursor_next_row_if_sequential_only'])
        m=series.read_session(Path(v['session_dir']))
        self.assertFalse(m['publication_allowed'])
        self.assertFalse(m['scoring_enabled'])
        self.assertEqual(m['batch_count'],3)
        self.assertEqual(sum(len(e['paper_ids']) for e in m['batches']),9)
        for e in m['batches']:
            p=json.loads((Path(v['session_dir'])/e['plan_path']).read_text())
            self.assertLessEqual(sum(len(x['links']) for x in p['papers']),8)

    def test_prepare_repeated_is_immutable_and_idempotent(self):
        v=self.prep()
        home=Path(v['session_dir']);before=(home/'session.json').read_bytes()
        self.assertEqual(self.prep()['session_dir'],v['session_dir'])
        self.assertEqual(before,(home/'session.json').read_bytes())
        with self.assertRaises(bridge.UnsafeSource):
            series.create_only(home/'session.json',{'other':True})

    def test_termux_without_os_link_still_prepares_all_three_batches(self):
        # Android's Python may lack os.link, but O_EXCL must still work.
        with mock.patch.object(series.os, 'link', None, create=True):
            v=self.prep()
            home=Path(v['session_dir'])
            self.assertEqual(len(list((home/'plans').glob('batch-*.json'))),3)
            self.assertEqual(series.read_session(home)['batch_count'],3)
            self.assertEqual(self.prep()['session_dir'],v['session_dir'])
            with self.assertRaises(bridge.UnsafeSource):
                series.create_only(home/'session.json',{'scoring_enabled':True})

    def test_termux_exclusive_create_rejects_symlink(self):
        with mock.patch.object(series.os, 'link', None, create=True):
            target=self.root/'real.json'
            target.write_bytes(b'private data to keep')
            link=self.root/'session.json'
            link.symlink_to(target)
            with self.assertRaises(bridge.UnsafeSource):
                series.create_only(link,{'scoring_enabled':False})
            self.assertEqual(target.read_bytes(),b'private data to keep')

    def test_termux_partial_write_failure_is_not_mistaken_for_success(self):
        path=self.root/'partial.json'
        original_fsync=series.os.fsync
        calls=[0]
        def failing_second_fsync(fd):
            calls[0]+=1
            if calls[0]==2:
                raise OSError('simulated interrupted Termux output sync')
            return original_fsync(fd)
        with mock.patch.object(series.os, 'link', None, create=True), \
             mock.patch.object(series.os, 'fsync', side_effect=failing_second_fsync):
            with self.assertRaises(OSError):
                series.create_only(path,{'not_scored':True})
        self.assertFalse(path.exists(),'failed exclusive create must not leave a success-looking file')
        self.assertEqual(list(self.root.glob('.lexflow-*.tmp')),[])

    def test_plan_fingerprint_tampering_fails_before_network(self):
        v=self.prep();home=Path(v['session_dir'])
        path=home/'plans/batch-02.json';blob=json.loads(path.read_text());blob['scoring_enabled']=True
        path.write_text(json.dumps(blob),encoding='utf-8')
        with self.assertRaises(bridge.UnsafeSource):series.read_session(home)
        with mock.patch.object(series,'run_plan') as guarded:
            with self.assertRaises(bridge.UnsafeSource):
                series.execute(home,offline_only=True)
            guarded.assert_not_called()

    def test_foreign_source_file_is_rejected_before_download(self):
        home=Path(self.prep()['session_dir'])
        self.csv.write_text('different source',encoding='utf-8')
        with mock.patch.object(series,'run_plan') as blocked:
            with self.assertRaises(bridge.UnsafeSource):
                series.execute(home,catalog=self.csv,download_documents=True)
            blocked.assert_not_called()

    def test_budgets_reject_excessive_full_download_plans(self):
        for options in [dict(batches=4),dict(per_batch=5),dict(docs_per_batch=9),
                        dict(batches=3,per_batch=5),dict(batches=3,per_batch=3,docs_per_batch=9)]:
            with self.subTest(options=options),self.assertRaises(bridge.UnsafeSource):
                series.prepare(self.csv,self.out,**options)

    def test_execution_requires_explicit_offline_or_download_mode(self):
        home=Path(self.prep()['session_dir'])
        for flags in [dict(),dict(offline_only=True,download_documents=True)]:
            with self.assertRaises(bridge.UnsafeSource):series.execute(home,**flags)

    def test_sequential_plan_reports_truthful_cursor(self):
        v=self.prep(strategy='sequential')
        self.assertEqual(v['cursor_next_row_if_sequential_only'],10)
        session=series.read_session(Path(v['session_dir']))
        self.assertTrue(session['cursor_is_complete_contiguous_enumeration'])
        self.assertEqual(session['catalog_cursor_next_row'],10)

    def test_execute_processes_three_batches_only_and_appends_journals(self):
        home=Path(self.prep()['session_dir'])
        with mock.patch.object(series,'run_plan',side_effect=dummy_run) as run:
            result=series.execute(home,download_documents=True,max_batches=3)
            self.assertEqual(result['batches_processed_this_invocation'],3)
            self.assertEqual(run.call_count,3)
            self.assertEqual(sum(r['network_pdf_downloads'] for r in result['results']),9)
            replay=series.execute(home,download_documents=True)
            self.assertEqual(replay['batches_processed_this_invocation'],0)
            self.assertEqual(run.call_count,3)
        self.assertEqual(len(list((home/'results').glob('batch-*.json'))),3)

    def test_restart_resumes_at_next_batch_not_first(self):
        home=Path(self.prep()['session_dir'])
        with mock.patch.object(series,'run_plan',side_effect=dummy_run) as r:
            first=series.execute(home,download_documents=True,max_batches=1)
            self.assertEqual(first['batches_processed_this_invocation'],1)
            second=series.execute(home,download_documents=True,max_batches=2)
            self.assertEqual(second['batches_processed_this_invocation'],2)
            self.assertEqual(r.call_count,3)

    def test_offline_missing_cache_does_not_checkpoint_or_block_online_retry(self):
        home=Path(self.prep()['session_dir']);n=[0]
        def dispatch(plan,outdir,**args):
            n[0]+=1
            if args['offline_only']:
                return {'reviews':[{'paper_id':p['paper_id'],
                         'state':'isolated_failed_not_published'} for p in plan['papers']],
                        'network_pdf_downloads':0,'cache_reuses':0,
                        'publication_allowed':False,'scoring_enabled':False}
            return dummy_run(plan,outdir,**args)
        with mock.patch.object(series,'run_plan',side_effect=dispatch):
            miss=series.execute(home,offline_only=True)
            self.assertEqual(miss['batches_confirmed_completed'],0)
            self.assertEqual(miss['status'],'PARTIAL_REVIEW_SAFE_STOP')
            self.assertEqual(miss['results'][0]['status'],'INCOMPLETE_RETRYABLE_NO_CHECKPOINT')
            self.assertFalse((home/'results'/'batch-01.json').exists())
            good=series.execute(home,download_documents=True,max_batches=1)
            self.assertEqual(good['results'][0]['status'],'review_batch_completed_unscored')
            self.assertTrue((home/'results'/'batch-01.json').exists())

    def test_crash_after_persisted_papers_can_resume_without_overwrite(self):
        home=Path(self.prep()['session_dir'])
        def crash(plan,outdir,**kwargs):
            dummy_run(plan,outdir,**kwargs)
            raise OSError('synthetic process crash before journal')
        with mock.patch.object(series,'run_plan',side_effect=crash):
            with self.assertRaises(OSError):series.execute(home,download_documents=True,max_batches=1)
        self.assertFalse((home/'results'/'batch-01.json').exists())
        files=list((self.out/'session-reviews'/series.read_session(home)['session_id']/'reports').glob('*.json'))
        snapshots={p.name:p.read_bytes() for p in files}
        with mock.patch.object(series,'run_plan',side_effect=dummy_run):
            next_run=series.execute(home,download_documents=True,max_batches=1)
        self.assertEqual(next_run['results'][0]['status'],'review_batch_completed_unscored')
        self.assertEqual(snapshots,{p.name:p.read_bytes() for p in files})

    def test_audit_reports_unverified_counts_without_invented_denominator(self):
        home=Path(self.prep()['session_dir'])
        with mock.patch.object(series,'run_plan',side_effect=dummy_run):
            series.execute(home,download_documents=True)
        result=series.audit(home)
        self.assertEqual(result['with_fulltext_sha_matched'],9)
        self.assertEqual(result['mcq_candidates'],18)
        audit=json.loads(Path(result['audit_path']).read_text())
        self.assertIsNone(audit['fulltext_completeness_rate'])
        self.assertFalse(audit['official_total_question_count_confirmed'])
        self.assertFalse(audit['human_answers_verified'])
        self.assertEqual(audit['types'],{'測驗題':3,'申論題':3,'混合題':3})
        self.assertTrue(all(x['scoring_enabled'] is False for x in audit['papers']))

    def test_audit_fails_closed_on_tampered_saved_text(self):
        home=Path(self.prep()['session_dir'])
        with mock.patch.object(series,'run_plan',side_effect=dummy_run):
            series.execute(home,download_documents=True,max_batches=1)
        p=next((self.out/'session-reviews'/series.read_session(home)['session_id']/'extracted_text').glob('*.txt'))
        p.write_text(p.read_text(encoding='utf-8')+' changed',encoding='utf-8')
        a=series.audit(home)
        x=json.loads(Path(a['audit_path']).read_text())
        self.assertTrue(any(i['state']=='isolated_fulltext_missing_or_SHA_mismatch' for i in x['papers']))
        self.assertEqual(x['with_fulltext_sha_matched'],2)
        self.assertFalse(x['scoring_enabled'])

    def test_audit_rejects_ambiguous_multiple_quality_previews(self):
        home=Path(self.prep()['session_dir'])
        with mock.patch.object(series,'run_plan',side_effect=dummy_run):
            series.execute(home,download_documents=True,max_batches=1)
        rep=next((self.out/'session-reviews'/series.read_session(home)['session_id']/'reports').glob('*.json'))
        pid=rep.stem
        overlays=self.out/'session-reviews'/series.read_session(home)['session_id']/'quality_previews';overlays.mkdir()
        for i in [1,2]:
            (overlays/f'{pid}-{i:016x}.json').write_text(json.dumps({
              'paper_id':pid,'report_source_sha256':bridge.digest(rep.read_bytes()),
              'publication_allowed':False,'scoring_enabled':False,
              'multiple_choice_candidates':{'candidate_count':30}}))
        x=json.loads(Path(series.audit(home)['audit_path']).read_text())
        record=next(i for i in x['papers'] if i['paper_id']==pid)
        self.assertEqual(record['quality_overlay'],'ambiguous_multiple_matching_overlays')
        self.assertNotIn('mcq_four_option_candidates_after_repair_unverified',record)

    def test_session_journal_forgery_blocks_resuming(self):
        home=Path(self.prep()['session_dir'])
        with mock.patch.object(series,'run_plan',side_effect=dummy_run):
            series.execute(home,download_documents=True,max_batches=1)
        j=home/'results/batch-01.json';value=json.loads(j.read_text())
        value['scoring_enabled']=True
        j.write_text(json.dumps(value))
        with mock.patch.object(series,'run_plan') as run:
            with self.assertRaises(bridge.UnsafeSource):
                series.execute(home,download_documents=True)
            run.assert_not_called()

    def test_audit_isolates_nested_scoring_claims(self):
        home=Path(self.prep()['session_dir'])
        with mock.patch.object(series,'run_plan',side_effect=dummy_run):
            series.execute(home,download_documents=True,max_batches=1)
        root=self.out/'session-reviews'/series.read_session(home)['session_id']
        path=next((root/'reports').glob('*.json'))
        obj=json.loads(path.read_text())
        obj['v03_review']['scoring_enabled']=True
        path.write_text(json.dumps(obj),encoding='utf-8')
        audit=json.loads(Path(series.audit(home)['audit_path']).read_text())
        self.assertEqual(sum(r['state']=='isolated_report_identity_or_scoring_mismatch'
                         for r in audit['papers']),1)
        self.assertFalse(audit['scoring_enabled'])

    def test_audit_blocks_changed_document_source_identity(self):
        home=Path(self.prep()['session_dir'])
        with mock.patch.object(series,'run_plan',side_effect=dummy_run):
            series.execute(home,download_documents=True,max_batches=1)
        root=self.out/'session-reviews'/series.read_session(home)['session_id']
        path=next((root/'reports').glob('*.json'))
        obj=json.loads(path.read_text())
        obj['v03_review']['reviewed_items'][0]['documents'][0]['url']=url('Q','114120','999','9999')
        path.write_text(json.dumps(obj),encoding='utf-8')
        audit=json.loads(Path(series.audit(home)['audit_path']).read_text())
        self.assertEqual(sum(r['state']=='isolated_source_document_links_mismatch'
                         for r in audit['papers']),1)

    def test_independent_catalog_snapshots_use_separate_report_folders(self):
        first=Path(self.prep()['session_dir'])
        with mock.patch.object(series,'run_plan',side_effect=dummy_run):
            series.execute(first,download_documents=True,max_batches=1)
        firstid=series.read_session(first)['session_id']
        original=self.csv.read_bytes()
        # Different authentic catalog snapshots must not silently inherit old reports.
        self.csv.write_bytes(original + b'\n')
        second=Path(self.prep()['session_dir'])
        secondid=series.read_session(second)['session_id']
        self.assertNotEqual(firstid,secondid)
        with mock.patch.object(series,'run_plan',side_effect=dummy_run):
            series.execute(second,download_documents=True,max_batches=1)
        self.assertTrue((self.out/'session-reviews'/firstid/'reports').exists())
        self.assertTrue((self.out/'session-reviews'/secondid/'reports').exists())
        self.assertEqual(series.audit(first)['with_fulltext_sha_matched'],3)
        self.assertEqual(series.audit(second)['with_fulltext_sha_matched'],3)

    def test_github_main_and_user_data_are_not_in_runtime_state(self):
        home=Path(self.prep()['session_dir'])
        m=series.read_session(home)
        self.assertFalse(m['private_attempts_included'])
        self.assertNotIn('student_answers',str(m).lower())
        self.assertNotIn('private_quiz_history',str(m).lower())
        self.assertNotIn('localStorage',str(m))
        self.assertNotIn('github_token',str(m))


if __name__=='__main__':unittest.main()
