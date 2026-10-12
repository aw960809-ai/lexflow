"""Zero-network regression tests for official PDF QA. Fictitious metadata stays in tests."""
from __future__ import annotations
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
from moex_document_qa import (CASES, DocumentQAError, check_response_origin,
    doc_identity, inspect_pdf, metadata_warnings, require_pairs,
    review_index, select_smoke, validate_pdf_bytes, main)

HOST = 'https://wwwq.moex.gov.tw/exam/wHandExamQandA_File.ashx'
def doc(c,s,role): return f'{HOST}?t={role}&code=114120&c={c}&s={s}&q=1'
def one(title,c,s,correction=False, group='司法四等考試_法院書記官類科'):
    return {'id': 'test-'+c+'-'+s, 'subject': title,
            'question_url': doc(c,s,'Q'),'answer_url':doc(c,s,'S'),
            'answer_correction_url':doc(c,s,'M') if correction else '',
            'groups':[group], 'answer_verification':'not_verified'}
def index():
    return {
        'schema':'lexflow.moex.index.v1',
        'status':'fallback_official_page_links_unverified',
        'source':{'exam_pages':['https://wwwq.moex.gov.tw/exam/wFrmExamQandASearch.aspx?e=114120&y=2025'],
                  'exam_wide_answer_url': f'{HOST}?t=A&code=114120'},
        'items':[one('民法概要','201','0405'),one('刑法概要','201','0504'),
                 one('法學知識與英文（包括中華民國憲法、法學緒論、英文）', '201','0204',True)],
    }

class OfficialDocumentQA(unittest.TestCase):
    def test_bounded_smoke_preserves_distinct_question_and_answer_roles(self):
        samples=select_smoke(index())
        self.assertEqual([x['case'] for x in samples],['civil','criminal','mixed_corrected','exam_ledger'])
        self.assertEqual([r for r,_ in samples[2]['documents']],['Q','S','M'])
        self.assertEqual([r for r,_ in samples[-1]['documents']],['A'])
        self.assertEqual(len([y for x in samples for y in x['documents']]),7)

    def test_official_answer_and_correction_never_confused(self):
        item=one('民法概要','201','0405',True)
        roles=require_pairs(item,('Q','S','M'))
        self.assertNotEqual(roles[1][1],roles[2][1])
        item['answer_correction_url']=doc('202','0405','M')
        with self.assertRaises(DocumentQAError): require_pairs(item,('Q','S','M'))

    def test_missing_correction_blocks_corrected_sample(self):
        data=index()
        data['items'][-1]['answer_correction_url']=''
        with self.assertRaises(DocumentQAError):select_smoke(data)

    def test_untrusted_question_rejected_before_fetch(self):
        data=index();data['items'][0]['question_url']='https://evil.com/q.pdf'
        with self.assertRaises(DocumentQAError):select_smoke(data)
        for target in ['http://wwwq.moex.gov.tw/exam/wHandExamQandA_File.ashx?code=114120&t=A',
                       'https://evil.com/exam/wHandExamQandA_File.ashx?code=114120&t=A',
                       f'{HOST}?t=A&code=114120&other=1']:
            with self.assertRaises(DocumentQAError):check_response_origin(target,'A')

    def test_fake_html_and_truncated_pdf_are_rejected(self):
        for contents in [b'<html>not pdf</html>',b'%PDF-1.7' + b'a'*256,
                         b'%PDF-1.5'+b'0'*120+b'%%E0F']:
            with self.assertRaises(DocumentQAError): validate_pdf_bytes(contents)

    def test_pdf_parser_result_still_does_not_claim_answers(self):
        class FakePage:
            def extract_text(self):return '不相關文件'
        class FakeReader:
            def __init__(self,source,strict=False):self.pages=[FakePage()]
        blob=b'%PDF-1.4\n'+b'0'*180+b'\n%%EOF\n'
        with patch.dict(sys.modules, {'pypdf':SimpleNamespace(PdfReader=FakeReader)}):
            result=inspect_pdf(blob, expected='民法概要')
        self.assertEqual(result['pages'],1)
        self.assertFalse(result['expected_subject_text_seen'])
        self.assertEqual(len(result['sha256']),64)

    def test_anomaly_flags_stale_classification_without_mutation(self):
        data=index();before=json.dumps(data,ensure_ascii=False,sort_keys=True)
        data['items'] += [one('憲法','4'+str(i).zfill(2),'0309',False,'司法五等考試_庭務員類科') for i in range(25)]
        alerts=metadata_warnings(data)
        self.assertEqual(alerts[0]['code'],'group_context_may_be_stale')
        self.assertEqual(alerts[0]['count'],25)
        self.assertEqual(json.loads(before)['items'][0]['subject'],'民法概要')

    def test_review_report_cannot_turn_into_official_scoring(self):
        calls=[]
        def fake_fetch(url,role):calls.append(role);return b'%PDF-mocked'
        def fake_inspect(value,expected):return {'pages':1,'bytes':100,'sha256':'0'*64,
            'expected_subject_text_seen':False,'identity_validation':'document_text_needs_independent_review'}
        r=review_index(index(),fetch=fake_fetch,inspect=fake_inspect)
        self.assertEqual(calls,['Q','S','Q','Q','S','M','A'])
        self.assertEqual(r['sampling']['papers_tested'],3)
        self.assertFalse(r['publication_allowed'])
        self.assertFalse(r['scoring_enabled'])
        self.assertFalse(r['answer_choices_verified'])
        self.assertFalse(r['correction_applied_to_choices'])
        self.assertNotIn('correctIndex', json.dumps(r))
        self.assertNotIn('grade',json.dumps(r))

    def test_unexpected_source_and_duplicate_sample_fail_closed(self):
        data=index();data['items'][0]['id']='A';data['items'].append(dict(data['items'][0],id='B'))
        with self.assertRaises(DocumentQAError):select_smoke(data)
        data=index();data['status']='official_answer_scored'
        with self.assertRaises(DocumentQAError):select_smoke(data)

    def test_missing_external_source_does_not_overwrite_old_report(self):
        with tempfile.TemporaryDirectory() as d:
            src=Path(d)/'bad.json'; dst=Path(d)/'report.json'
            src.write_text('{"status":"untrusted"}')
            dst.write_text('KEEP PREVIOUS')
            self.assertEqual(main(['--input-index',str(src),'--output',str(dst)]),2)
            self.assertEqual(dst.read_text(),'KEEP PREVIOUS')

if __name__=='__main__':unittest.main()
