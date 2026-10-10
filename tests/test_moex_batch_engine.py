"""Fixtures only: cross-year, cross-field, fail-closed batch engine tests.

No synthetic answer values are distributed or represented as official data.
"""
import json
import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from moex_batch_engine import (
    BatchReviewError, SCHEMA, MAX_DOCUMENTS, choose_representative,
    fetch_pdf, identify_download_redirect, inspect_pdf_source, main,
    normalize_paper, process_batch, raw_question_previews,
    safe_official_ref, validate_index,
)


def official_link(code='114120', c='201', s='0405', role='Q'):
    return ('https://wwwq.moex.gov.tw/exam/wHandExamQandA_File.ashx?'
            f'code={code}&q=1&s={s}&t={role}&c={c}')


def entry(name='民法概要', focus=('民法',), *, code='114120', c='201', s='0405',
          answer=True, correction=False, classification='subject_named'):
    return {'id': f'p-{code}-{c}-{s}', 'year_roc': code[:3], 'exam': '核准候審官方考試',
            'subject': name, 'focus_subjects': list(focus), 'classification': classification,
            'question_url': official_link(code,c,s,'Q'),
            'answer_url': official_link(code,c,s,'S') if answer else '',
            'answer_correction_url': official_link(code,c,s,'M') if correction else '',
            'question_type': '題型待核對', 'groups': ['示例_待核對']}


def candidates(items, status='fallback_official_page_links_unverified'):
    return {'schema': 'lexflow.moex.index.v1', 'status': status,
            'source': {'agency':'考選部', 'method':'official_exam_page_html'}, 'items': items}


def three_fields(code='114120'):
    return candidates([
        entry(code=code),
        entry('刑法概要', ('刑法',), code=code, c='201', s='0504'),
        entry('法學知識與英文（含憲法）', ('憲法',), code=code, c='201', s='0204',
              classification='mixed', correction=True),
        entry('刑法與刑事訴訟法', ('刑法',), code=code, c='105', s='0501',
              classification='mixed', answer=False),
    ])


def inspect_ok(blob, role, expected):
    return {'pdf_structure_readable': True, 'sha256':'fixture-only-sha-not-real',
            'bytes':128, 'pages':1, 'expected_subject_label_seen':True,
            'content_and_options_verified': False, 'final_answer_verified':False}


class OfficialUniversalBatchTests(unittest.TestCase):
    def test_source_is_not_hardcoded_to_one_year_or_civil_paper(self):
        for code in ('113099','114120','115001'):
            data=three_fields(code)
            plan=process_batch(data,max_papers=3,max_documents=7)
            self.assertEqual(plan['summary']['selected_papers'],3)
            self.assertEqual(plan['summary']['focus_coverage'],{'民法':1,'刑法':1,'憲法':1})
            self.assertEqual(plan['status'],'review_plan_only_no_download')
            self.assertTrue(all(p['year_roc']==code[:3] for p in plan['reviewed_items']))
            self.assertTrue(all(p['eligible_for_scoring'] is False for p in plan['reviewed_items']))

    def test_cross_field_downloads_and_correction_roles(self):
        calls=[]
        def fetch(ref): calls.append((ref['identity'],ref['role']));return b'fixture'
        d=process_batch(three_fields(),max_papers=3,max_documents=7,
                        download=True,require_all=True,fetch=fetch,inspect=inspect_ok)
        self.assertEqual(d['schema'],SCHEMA)
        self.assertEqual(d['summary']['document_fetch_attempts'],7)
        self.assertEqual(d['summary']['completed_review_plans_or_pdfs'],3)
        self.assertEqual(set(p['focus_subjects'][0] for p in d['reviewed_items']),{'民法','刑法','憲法'})
        self.assertEqual(len([c for c in calls if c[1]=='M']),1)
        corrected=[p for p in d['reviewed_items'] if 'M' in [i['role'] for i in p['documents']]][0]
        self.assertIn('official_correction_present_requires_manual_application',corrected['warnings'])
        self.assertFalse(d['correction_and_special_scoring_applied'])
        self.assertFalse(d['publication_allowed'])
        self.assertFalse(d['scoring_enabled'])
        self.assertFalse(d['all_question_text_verified'])

    def test_question_and_answer_identity_mismatch_rejected_before_download(self):
        item=entry()
        item['answer_url']=official_link(c='202', role='S')
        with self.assertRaisesRegex(BatchReviewError,'identity mismatch'):
            normalize_paper(item)
        other=entry()
        other['answer_correction_url']=official_link(s='0406', role='M')
        with self.assertRaises(BatchReviewError):normalize_paper(other)

    def test_qsm_role_and_year_mismatch_rejected(self):
        x=entry();x['year_roc']='113'
        with self.assertRaisesRegex(BatchReviewError,'year'):
            normalize_paper(x)
        x=entry();x['question_url']=official_link(role='S')
        with self.assertRaises(BatchReviewError):normalize_paper(x)

    def test_untrusted_hosts_credentials_ports_and_schemes_blocked(self):
        base=official_link()
        urls=['http://'+base[8:],
              base.replace('wwwq.moex.gov.tw','wwwq.moex.gov.tw.evil.org'),
              base.replace('wwwq.moex.gov.tw','evil.com@wwwq.moex.gov.tw'),
              base.replace('wwwq.moex.gov.tw','wwwq.moex.gov.tw:444'),
              base+'#foo',base.replace('t=Q','t=X'),
              base.replace('code=114120','code=114120&code=114120'),
              base.replace('c=201','c=201%26x%3D2'),
              'javascript:alert(1)',
              ]
        for value in urls:
            with self.subTest(value=value),self.assertRaises(BatchReviewError):
                safe_official_ref(value,'Q')

    def test_other_official_csv_https_link_is_accepted_only_unpaired(self):
        x=entry();x['question_url']='https://wwwc.moex.gov.tw/main/Exam/PublicQuestion.ashx?a=1'
        x['answer_url']='https://wwwc.moex.gov.tw/main/Exam/PublicAnswer.ashx?a=1'
        x['answer_correction_url']=''
        data=candidates([x],status='index_only_unverified_answers')
        refs=[]
        d=process_batch(data,max_papers=1,max_documents=3,download=True,
                        fetch=lambda r:(refs.append(r['role']),b'ok')[1],inspect=inspect_ok)
        self.assertEqual(refs,['Q'])
        self.assertFalse(d['reviewed_items'][0]['source_link_identity_confirmed'])
        self.assertIn('S_document_skipped_unproven_identity',d['reviewed_items'][0]['warnings'])
        self.assertEqual(d['reviewed_items'][0]['state'],'isolated_needs_review')

    def test_html_aggregate_answer_is_never_per_paper_role(self):
        with self.assertRaises(BatchReviewError):
            safe_official_ref('https://wwwq.moex.gov.tw/exam/wHandExamQandA_File.ashx?code=114120&t=A','S')

    def test_safe_redirect_must_keep_paper_and_role(self):
        q=safe_official_ref(official_link(),'Q')
        identify_download_redirect(q,official_link())
        identify_download_redirect(q,'https://wwwq.moex.gov.tw/exam/wHandExamQandA_File.ashx?c=201&code=114120&q=1&s=0405&t=Q')
        for url in [official_link(c='999'),official_link(role='S'),
                    official_link().replace('114120','114121'),
                    official_link().replace('wwwq.moex.gov.tw','wwwq.moex.gov.tw.evil')]:
            with self.subTest(url=url),self.assertRaises(BatchReviewError):
                identify_download_redirect(q,url)

    def test_duplicate_documents_not_processed_twice(self):
        a=entry();b=dict(a);b['id']='a-different-id'
        data=candidates([a,b,entry('刑法',('刑法',),s='0504')])
        count=[]
        d=process_batch(data,max_papers=3,max_documents=6,download=True,
                        fetch=lambda r:(count.append(r['url']),b'data')[1],inspect=inspect_ok)
        self.assertEqual(len(d['reviewed_items']),2)
        self.assertEqual(len(count),4)

    def test_partial_document_failure_does_not_abort_whole_batch(self):
        refs=[]
        def fetch(ref):
            refs.append(ref['url'])
            if 's=0504' in ref['url']:
                raise BatchReviewError('simulated unavailable official PDF')
            return b'fixture'
        d=process_batch(three_fields(),max_papers=3,max_documents=7,download=True,
                        fetch=fetch, inspect=inspect_ok)
        self.assertEqual(len(d['reviewed_items']),3)
        self.assertGreaterEqual(d['summary']['completed_review_plans_or_pdfs'],1)
        self.assertGreaterEqual(d['summary']['download_or_validation_errors'],1)
        self.assertIn('isolated_needs_review',[x['state'] for x in d['reviewed_items']])
        self.assertFalse(d['publication_allowed'])
        self.assertGreaterEqual(len(refs),6)
        with self.assertRaisesRegex(BatchReviewError,'strict smoke test'):
            process_batch(three_fields(),max_papers=3,max_documents=7,
                          download=True,require_all=True,fetch=fetch,inspect=inspect_ok)

    def test_all_downloads_failed_keeps_previous_report(self):
        with self.assertRaisesRegex(BatchReviewError,'no paper passed'):
            process_batch(three_fields(),max_papers=3,max_documents=7,download=True,
                          fetch=lambda r:(_ for _ in ()).throw(BatchReviewError('offline')),
                          inspect=inspect_ok)

    def test_budgets_are_enforced_without_silent_success(self):
        hits=[]
        d=process_batch(three_fields(),max_papers=3,max_documents=2,download=True,
                        fetch=lambda r:(hits.append(r),b'dummy')[1],inspect=inspect_ok)
        self.assertEqual(len(hits),2)
        self.assertTrue(any('batch_document_budget_exhausted' in p.get('warnings',[])
                            for p in d['reviewed_items']))
        with self.assertRaisesRegex(BatchReviewError,'strict smoke'):
            process_batch(three_fields(),max_papers=3,max_documents=2,download=True,
                          require_all=True,fetch=lambda r:b'dummy',inspect=inspect_ok)
        for max_papers in (0,MAX_DOCUMENTS+1):
            with self.assertRaises(BatchReviewError):
                process_batch(three_fields(),max_papers=max_papers)
        for max_documents in (0,MAX_DOCUMENTS+1):
            with self.assertRaises(BatchReviewError):
                process_batch(three_fields(),max_documents=max_documents)

    def test_no_false_scoring_claims_even_if_inspection_pretends_yes(self):
        def malicious_inspect(*args):
            return {'pdf_structure_readable':True,'expected_subject_label_seen':True,
                    'content_and_options_verified':True,'final_answer_verified':True,
                    'eligible_for_scoring':True}
        d=process_batch(candidates([entry()]),max_papers=1,max_documents=2,
                        download=True,fetch=lambda r:b'x',inspect=malicious_inspect)
        for doc in d['reviewed_items'][0]['documents']:
            self.assertIs(doc['content_and_options_verified'],False)
            self.assertIs(doc['final_answer_verified'],False)
        self.assertFalse(d['reviewed_items'][0]['eligible_for_scoring'])

    def test_pdf_structure_gate_rejects_html_and_truncation(self):
        for blob in (b'<html>Error</html>', b'%PDF-1.4 '+b'x'*200):
            with self.assertRaises(BatchReviewError):
                inspect_pdf_source(blob,'Q','民法')

    def test_question_preview_no_numbering_does_not_invent_questions(self):
        for text in ('', '民法概要測驗題 abc', '1 xxx\n3 yyy\n5 zzz'):
            self.assertEqual(raw_question_previews(text)['count'],0)
        answer=raw_question_previews('前言\n1 第一題有一段較長敘述\n2 第二題有另一段相當完整的敘述\n3 第三題有足夠且較完整的一段內容')
        self.assertEqual(answer['count'],3)
        self.assertIn('REQUIRE_REVIEW', answer['status'])
        self.assertEqual([p['number'] for p in answer['samples']],[1,2,3])
        self.assertTrue(all('unreviewed' in next(iter(x for x in p if x != 'number')) for p in answer['samples']))

    def test_mock_source_records_are_not_modified(self):
        d=three_fields();original=json.dumps(d,sort_keys=True)
        process_batch(d,max_papers=3,download=True,fetch=lambda r:b'fixture',inspect=inspect_ok)
        self.assertEqual(original,json.dumps(d,sort_keys=True))

    def test_rejects_fake_published_or_score_ready_index(self):
        for state in ('ready_to_score','awaiting_first_official_page_sync',''):
            with self.assertRaises(BatchReviewError):
                validate_index(candidates([entry()],status=state))
        for index in ({}, {'schema':'lexflow.moex.index.v1','items':[]},
                      {'schema':'lexflow.moex.civil.114120.answer-candidate.v1','items':[entry()]}):
            with self.assertRaises(BatchReviewError):validate_index(index)

    def test_paper_isolation_of_unsafe_url_with_good_papers(self):
        bad=entry('刑法概要',('刑法',),s='0504')
        bad['question_url']='https://moex.gov.tw.evil.org/x'
        d=process_batch(candidates([entry(),bad]),max_papers=2,download=True,
                        fetch=lambda r:b'fixture',inspect=inspect_ok)
        self.assertEqual(len(d['reviewed_items']),2)
        self.assertEqual(d['summary']['isolated_papers'],1)
        self.assertTrue(any(p['state']=='isolated_invalid_paper' for p in d['reviewed_items']))
        self.assertTrue(any(p['state']=='pdfs_readable_CONTENT_NOT_VERIFIED' for p in d['reviewed_items']))

    def test_plan_only_cli_writes_report_and_rejects_overwrite(self):
        with tempfile.TemporaryDirectory() as root:
            root=Path(root)
            src=root/'source.json';out=root/'review.json'
            src.write_text(json.dumps(three_fields(),ensure_ascii=False),encoding='utf-8')
            self.assertEqual(main(['--input-index',str(src),'--max-papers','3','--output',str(out)]),0)
            report=json.loads(out.read_text())
            self.assertEqual(report['summary']['document_fetch_attempts'],0)
            self.assertFalse(report['scoring_enabled'])
            prev=out.read_bytes()
            # An invalid source should not rewrite the existing report.
            src.write_text(json.dumps({'status':'bad'}))
            self.assertEqual(main(['--input-index',str(src),'--output',str(out)]),2)
            self.assertEqual(prev,out.read_bytes())
            with self.assertRaises(SystemExit):
                main(['--input-index',str(src),'--output',str(src)])


if __name__=='__main__':
    unittest.main()
