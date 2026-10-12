"""All fixture PDFs are synthetic, not MOEX official answer keys."""
from __future__ import annotations
import collections
from pathlib import Path
import json
import os
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from final98_answer_candidate_v5 import (
    GateError,source_identity,parse_pdf,parse_special_notes,parse_labeled_text,
    load_inputs,cache_pdf,sha256,make_rows,write_output,DB_SHA,
)

HERE=Path(__file__).parent/'fixtures'
Q='https://wwwq.moex.gov.tw/exam/wHandExamQandA_File.ashx?t=Q&code=114040&c=301&s=0302&q=1'
S=Q.replace('t=Q','t=S')
M=Q.replace('t=Q','t=M')

def fixture(name):return (HERE/name).read_bytes()

class V5AnswersTests(unittest.TestCase):
    def test_source_exact_url_and_reject_other_class(self):
        self.assertEqual(source_identity(Q),source_identity(S))
        self.assertNotEqual(source_identity(Q),source_identity(S.replace('c=301','c=302')))
        for u in (Q.replace('https:','http:'),Q.replace('wwwq.moex.gov.tw','wwwq.moex.gov.tw.evil.invalid'),
                  Q.replace('t=Q','t=S&t=Q'),Q.replace('code=114040','code=abc')):
            with self.assertRaises(GateError):source_identity(u)

    def test_25_complete_grid_candidate_but_never_verified(self):
        p=parse_pdf(fixture('MOCK_25_COMPLETE_NOT_OFFICIAL.pdf'),25,'S')
        self.assertEqual(p['status'],'COMPLETE_CANDIDATE_NOT_FINAL')
        self.assertEqual(p['evidenceMethod'],'PDF_POSITIONED_GRID_CANDIDATE')
        self.assertEqual(len(p['candidateKeys']),25)
        self.assertEqual(p['candidateKeys']['1'],'B')
        self.assertEqual(p['candidateKeys']['25'],'B')
        self.assertFalse(p['scoringEnabled']);self.assertFalse(p['finalAnswerVerified'])
        self.assertFalse(p['publicationAllowed'])

    def test_missing_interior_answer_denies_full_key(self):
        p=parse_pdf(fixture('MOCK_25_MISSING_8_NOT_OFFICIAL.pdf'),25,'S')
        self.assertEqual(p['status'],'REQUIRES_REVIEW')
        self.assertEqual(p['candidateKeys'],{})
        self.assertEqual(p['positionedPairs'],24)

    def test_shifted_answer_cell_fails_closed(self):
        p=parse_pdf(fixture('MOCK_25_SHIFTED_8_NOT_OFFICIAL.pdf'),25,'S')
        self.assertEqual(p['status'],'REQUIRES_REVIEW')
        self.assertGreaterEqual(p['rejectedPositionedGroups'],1)
        self.assertEqual(p['candidateKeys'],{})

    def test_duplicate_page_fails_closed(self):
        p=parse_pdf(fixture('MOCK_25_DUP_PAGE_NOT_OFFICIAL.pdf'),25,'S')
        self.assertEqual(p['status'],'REQUIRES_REVIEW')
        self.assertEqual(p['candidateKeys'],{})
        self.assertIn('DUPLICATE_OR_CONFLICTING_PDF_CELLS',p['issues'])

    def test_m_special_marker_notes_not_automatically_keyed(self):
        p=parse_pdf(fixture('MOCK_25_M_SPECIAL_NOT_OFFICIAL.pdf'),25,'M')
        self.assertEqual(p['status'],'REQUIRES_REVIEW')
        self.assertEqual(p['candidateKeys'],{})
        self.assertIn(20,p['positionedMarkers'])
        self.assertEqual(p['specialNotesUnverified']['20']['choices'],['B','C'])
        self.assertNotIn('20',p['positionedNonFinalCellEvidence'])
        self.assertEqual(len(p['positionedNonFinalCellEvidence']),24)
        self.assertFalse(p['finalAnswerVerified'])

    def test_declared_count_conflict_denies_keys(self):
        p=parse_pdf(fixture('MOCK_25_COUNT_WRONG_NOT_OFFICIAL.pdf'),25,'S')
        self.assertEqual(p['candidateKeys'],{})
        self.assertIn('OFFICIAL_DECLARED_NUMBER_CONFLICT',p['issues'])

    def test_text_pairing_requires_labeled_numbers(self):
        ok=parse_labeled_text('題號 1 2 3\n答案 A B C',3)
        self.assertTrue(ok['complete']);self.assertEqual(ok['candidates']['2'],'B')
        bad=parse_labeled_text('A B C\n A B C\n 1 2 3',3)
        self.assertFalse(bad['complete']);self.assertEqual(bad['candidates'],{})

    def test_special_note_would_not_certify_scoring(self):
        d,conflicts=parse_special_notes('備註：第20題答Ｂ或Ｃ者均給分。',25)
        self.assertEqual(d['20']['choices'],['B','C']);self.assertFalse(d['20']['humanVerified'])
        self.assertEqual(conflicts,[])

    def test_cache_checksum_and_symlink_rejected(self):
        raw=fixture('MOCK_25_COMPLETE_NOT_OFFICIAL.pdf');pdfsha=sha256(raw)
        with tempfile.TemporaryDirectory() as t:
            p=Path(t);url=S
            doc={'url':url,'actual_sha256':pdfsha,'reference_sha256':pdfsha}
            (p/(pdfsha+'.pdf')).write_bytes(raw)
            (p/(sha256(url.encode())+'.json')).write_text(json.dumps(doc),encoding='utf-8')
            self.assertEqual(cache_pdf(doc,p),raw)
            (p/(pdfsha+'.pdf')).write_bytes(raw+b'injected')
            with self.assertRaises(GateError):cache_pdf(doc,p)
            (p/(pdfsha+'.pdf')).unlink()
            (p/(pdfsha+'.pdf')).symlink_to(Path(t)/'absent.pdf')
            with self.assertRaises(GateError):cache_pdf(doc,p)

    def test_v5_output_never_unlocks_release(self):
        with tempfile.TemporaryDirectory() as t:
            path=Path(t)/'report.zip'; summary={'schema':'lexflow.final98.answer.candidates.v5',
                  'publication_allowed':False,'scoring_enabled':False,'final_answers_verified':False}
            write_output(path,summary,{},[],[{'paper_id':'p','candidate_status':'NOT_FINAL'}])
            self.assertTrue(path.exists())
            with self.assertRaises(GateError):write_output(path,summary,{},[],[])
            invalid=dict(summary);invalid['scoring_enabled']=True
            with self.assertRaises(GateError):write_output(Path(t)/'invalid.zip',invalid,{},[],[])

    @unittest.skipUnless(os.environ.get('LEXFLOW_FINAL98_V4') and os.environ.get('LEXFLOW_FINAL98_SHARDS'),
                         'real private V4+449 inputs are optional')
    def test_full_v4_and_449_archives(self):
        r,docs,papers=load_inputs(Path(os.environ['LEXFLOW_FINAL98_V4']),Path(os.environ['LEXFLOW_FINAL98_SHARDS']))
        self.assertEqual(len(docs),301);self.assertEqual(len(papers),449)
        self.assertEqual(sum(x['mcq_count'] for x in papers.values()),8290)
        self.assertEqual(sum(x['mcq_count']>0 for x in papers.values()),246)
        self.assertFalse(r['release_permitted'])

if __name__=='__main__':unittest.main()
