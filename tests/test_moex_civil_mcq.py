import hashlib
import json
import tempfile
import unittest
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from moex_civil_mcq import (
    PUBLISHED_ANSWERS,QUESTION_SHA256, ANSWER_SHA256, QUESTION_URL, ANSWER_URL,
    verify_pdf_metadata,verify_source_keys,build_candidate,McqCandidateError,collect_unverified_excerpts)
from moex_index import write_atomic


class CivilMcqAnswerCandidateTests(unittest.TestCase):
    def test_published_answer_snapshot_has_25_individually_numbered_keys(self):
        self.assertEqual(len(PUBLISHED_ANSWERS),25)
        self.assertEqual(''.join(PUBLISHED_ANSWERS[:10]),'ABAADDBACA')
        self.assertEqual(''.join(PUBLISHED_ANSWERS[10:20]),'CBDDBBDDCC')
        self.assertEqual(''.join(PUBLISHED_ANSWERS[20:]),'BBABC')
        self.assertEqual(set(PUBLISHED_ANSWERS),set('ABCD'))

    def test_source_identity(self):
        self.assertIsNone(verify_source_keys(QUESTION_URL,ANSWER_URL))

    def test_rejects_cross_subject_answer_identity(self):
        from moex_page_fallback import official_document_url
        invalid='https://wwwq.moex.gov.tw/exam/wHandExamQandA_File.ashx?t=S&code=114120&c=201&s=0204&q=1'
        with self.assertRaises(McqCandidateError):verify_source_keys(QUESTION_URL,invalid)

    def test_rejects_bad_exam_class_or_untrusted_host(self):
        with self.assertRaises(McqCandidateError):verify_source_keys(QUESTION_URL.replace('code=114120','code=114121'), ANSWER_URL)
        with self.assertRaises(McqCandidateError):verify_source_keys(QUESTION_URL.replace('wwwq.moex.gov.tw','evil.com'), ANSWER_URL)

    def test_pinned_document_sha_and_pages(self):
        q={'sha256':QUESTION_SHA256,'pages':4,'expected_subject_text_seen':True}
        a={'sha256':ANSWER_SHA256,'pages':1,'expected_subject_text_seen':True}
        self.assertIsNone(verify_pdf_metadata(q,a))
        for changed in [dict(q,sha256='bad'),dict(q,pages=3),dict(q,expected_subject_text_seen=False)]:
            with self.assertRaises(McqCandidateError):verify_pdf_metadata(changed,a)
        for changed in [dict(a,sha256='bad'),dict(a,pages=2),dict(a,expected_subject_text_seen=False)]:
            with self.assertRaises(McqCandidateError):verify_pdf_metadata(q,changed)

    def test_build_candidate_never_enables_scoring_or_verified_options(self):
        def inspect(fake,expected):
            return {'sha256':QUESTION_SHA256,'pages':4,'expected_subject_text_seen':True} if fake==b'q' else {'sha256':ANSWER_SHA256,'pages':1,'expected_subject_text_seen':True}
        d=build_candidate(question_pdf=b'q',answer_pdf=b'a',inspect=inspect, excerpts=lambda _ : ({},'not_extracted'))
        self.assertEqual(len(d['items']),25)
        self.assertEqual([x['number'] for x in d['items']],list(range(1,26)))
        self.assertEqual([x['published_standard_answer'] for x in d['items']],list(PUBLISHED_ANSWERS))
        self.assertFalse(d['publication_allowed'])
        self.assertFalse(d['scoring_enabled'])
        self.assertEqual(d['exam_wide_answer_and_corrections_review'],'not_completed')
        self.assertTrue(all(not i['eligible_for_scoring'] and not i['options_verified'] and not i['later_correction_checked'] for i in d['items']))
        self.assertNotIn('personal',json.dumps(d))

    def test_unverified_raw_pdf_excerpts_also_never_enable_scoring(self):
        def inspect(fake,expected):
            return {'sha256':QUESTION_SHA256,'pages':4,'expected_subject_text_seen':True} if fake==b'q' else {'sha256':ANSWER_SHA256,'pages':1,'expected_subject_text_seen':True}
        d=build_candidate(question_pdf=b'q',answer_pdf=b'a',inspect=inspect,excerpts=lambda _ : ({1:'1 未核對的題文片段'},'raw_pdf_text_requires_option_by_option_review'))
        self.assertIn('未核對',d['items'][0]['raw_pdf_excerpt_unreviewed'])
        self.assertFalse(d['items'][0]['question_text_verified'])
        self.assertFalse(d['publication_allowed'])

    def test_pdf_parse_failure_does_not_promote_text(self):
        raw,status=collect_unverified_excerpts(b'not-a-pdf')
        self.assertEqual(raw,{})
        self.assertIn(status,('pdf_text_extraction_unavailable','number_or_reading_order_requires_review'))

    def test_candidate_is_deterministic_and_atomic(self):
        def inspect(fake,expected):
            return {'sha256':QUESTION_SHA256,'pages':4,'expected_subject_text_seen':True} if fake==b'q' else {'sha256':ANSWER_SHA256,'pages':1,'expected_subject_text_seen':True}
        a=build_candidate(question_pdf=b'q',answer_pdf=b'a',inspect=inspect,excerpts=lambda _: ({},'not_extracted'))
        b=build_candidate(question_pdf=b'q',answer_pdf=b'a',inspect=inspect,excerpts=lambda _: ({},'not_extracted'))
        self.assertEqual(a,b)
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'candidate.json'
            self.assertTrue(write_atomic(p,a))
            before=p.read_bytes()
            self.assertFalse(write_atomic(p,b))
            self.assertEqual(p.read_bytes(),before)

if __name__=='__main__':unittest.main()
