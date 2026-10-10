"""Regression tests: all PDF fixtures are synthetic and NOT MOEX answer keys.

Tests never enable scoring, update the official release feed, or touch attempts.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from moex_quality_overlay import (
    OverlayError, _parse_pdf_positioned_answers, inspect_corrected_pdf,
    build_overlay, parse_special_credit_note, parse_table_candidates,
)

try:
    from pypdf import PdfReader, PdfWriter
except ImportError:
    PdfReader = None
    PdfWriter = None

HERE = Path(__file__).resolve().parent / 'fixtures'
Q_M = 'https://wwwq.moex.gov.tw/exam/wHandExamQandA_File.ashx?t=Q&code=114010&c=501&s=0202&q=1'
Q_S = 'https://wwwq.moex.gov.tw/exam/wHandExamQandA_File.ashx?t=Q&code=114040&c=301&s=0103&q=1'


def fixture(file):
    return (HERE / file).read_bytes()


def report(blob, n, role, *, qanswers=None):
    q = Q_M if role == 'M' else Q_S
    source = {'paper_id':'moex-'+'a'*24, 'official_subject':'合成測試科目',
              'official_type':'測驗題' if role=='M' else '混合題',
              'question_url':q, 'answer_url':q.replace('t=Q',f't={role}')}
    questions = [
        {'number':i,'published_standard_candidate':qanswers.get(i) if qanswers else None,
         'candidate_status':'four_options_extracted_NEEDS_VISUAL_REVIEW',
         'options_unverified':{'A':'甲','B':'乙','C':'丙','D':'丁'},
         'final_answer_verified':False} for i in range(1,n+1)
    ]
    return {'schema':'lexflow.moex.whole-paper-review.v1','paper_id':source['paper_id'],
      'official_source':source,'publication_allowed':False,'scoring_enabled':False,
      'extracted_question_text':{},
      'v03_review':{'publication_allowed':False,'scoring_enabled':False,'reviewed_items':[
        {'documents':[{'role':role,'sha256':hashlib.sha256(blob).hexdigest()}],
         'question_answer_candidates':{'questions':questions,
                  'publication_allowed':False,'scoring_enabled':False}}
      ]}}


class AnswerGridTests(unittest.TestCase):
    def test_special_credit_matches_actual_note_grammatical_particle(self):
        notes=parse_special_credit_note('備　註： 第20題答Ｂ或Ｃ者均給分。')
        self.assertEqual([20],[r['number'] for r in notes])
        self.assertEqual(['B','C'],notes[0]['candidate_valid_choices'])
        self.assertFalse(notes[0]['human_verified'])

    def test_reject_unrelated_special_credit_text(self):
        self.assertEqual([],parse_special_credit_note('第20題答案為B；其他題目 C 均有給分'))
        self.assertEqual([],parse_special_credit_note('第20題D無條件給分'))

    def test_explicit_number_text_grid_remains_supported(self):
        old=parse_table_candidates('題號 1 2 3\n答案 A B C\n',expected_question_count=3)
        self.assertEqual(old['candidates'],{'1':'A','2':'B','3':'C'})
        self.assertFalse(old['scoring_enabled'])

    @unittest.skipIf(PdfReader is None,'pypdf not installed; positional fixtures run in PDF smoke environment')
    def test_M_50_positioned_table_has_49_single_values_and_marker(self):
        raw=fixture('MOCK_M_50_POSITIONAL_NOT_OFFICIAL.pdf')
        out=_parse_pdf_positioned_answers(PdfReader(HERE/'MOCK_M_50_POSITIONAL_NOT_OFFICIAL.pdf').pages,expected_question_count=50)
        self.assertEqual(out['unique_paired_numbers'],49)
        self.assertEqual(out['covered_cell_count'],50)
        self.assertEqual(out['correction_markers'],[20])
        self.assertTrue(out['complete_positioned_grid'])
        self.assertEqual(out['evidence_group_count'],5)
        self.assertNotIn('20',out['candidates'])
        self.assertFalse(out['scoring_enabled'])

    @unittest.skipIf(PdfReader is None,'pypdf not installed; positional fixtures run in PDF smoke environment')
    def test_M_50_full_evidence_keeps_B_and_C_not_one_answer(self):
        raw=fixture('MOCK_M_50_POSITIONAL_NOT_OFFICIAL.pdf')
        r=report(raw,50,'M');original=copy.deepcopy(r)
        out=inspect_corrected_pdf(raw,declared_url=r['official_source']['answer_url'],role='M',report=r,expected_count=50)
        tab=out['table_candidate']
        self.assertEqual(tab['unique_paired_numbers'],49)
        self.assertEqual(tab['special_credit_choices_unverified'],{'20':['B','C']})
        self.assertEqual(tab['answer_cell_coverage_with_special_notes'],50)
        self.assertTrue(tab['complete_numbering_candidate'])
        self.assertEqual(out['cannot_convert_to_single_choice'],[20])
        self.assertFalse(out['final_answers_verified'])
        self.assertFalse(out['scoring_enabled'])
        self.assertEqual(r,original)

    @unittest.skipIf(PdfReader is None,'pypdf not installed; positional fixtures run in PDF smoke environment')
    def test_S_30_positioned_table_all_30_paired(self):
        raw=fixture('MOCK_S_30_POSITIONAL_NOT_OFFICIAL.pdf')
        r=report(raw,30,'S')
        out=inspect_corrected_pdf(raw,declared_url=r['official_source']['answer_url'],role='S',report=r,expected_count=30)
        tab=out['table_candidate']
        self.assertEqual(tab['unique_paired_numbers'],30)
        self.assertTrue(tab['complete_numbering_candidate'])
        self.assertEqual(tab['original_candidate_conflict_numbers'] if 'original_candidate_conflict_numbers' in tab else [],[])
        self.assertEqual(out['special_credit_candidate'],[])
        self.assertFalse(tab['scoring_enabled'])

    @unittest.skipIf(PdfReader is None,'pypdf not installed; positional fixtures run in PDF smoke environment')
    def test_missing_answer_cell_does_not_fill_gap(self):
        p=PdfReader(HERE/'MOCK_S_30_MISSING_D8_NOT_OFFICIAL.pdf')
        out=_parse_pdf_positioned_answers(p.pages,expected_question_count=30)
        self.assertEqual(out['unique_paired_numbers'],29)
        self.assertNotIn('8',out['candidates'])
        self.assertFalse(out['complete_positioned_grid'])

    @unittest.skipIf(PdfReader is None,'pypdf not installed; positional fixtures run in PDF smoke environment')
    def test_shifted_cell_rejects_whole_ambiguous_row(self):
        p=PdfReader(HERE/'MOCK_S_30_SHIFTED_NOT_OFFICIAL.pdf')
        out=_parse_pdf_positioned_answers(p.pages,expected_question_count=30)
        self.assertFalse(out['complete_positioned_grid'])
        self.assertGreaterEqual(out['rejected_grid_groups'],1)
        self.assertNotIn('3',out['candidates'])

    @unittest.skipIf(PdfReader is None,'pypdf not installed; positional fixtures run in PDF smoke environment')
    def test_count_disagreement_empties_candidates(self):
        raw=fixture('MOCK_S_30_POSITIONAL_NOT_OFFICIAL.pdf');r=report(raw,29,'S')
        out=inspect_corrected_pdf(raw,declared_url=r['official_source']['answer_url'],role='S',report=r,expected_count=29)
        self.assertEqual(out['table_candidate']['candidates'],{})
        self.assertTrue(out['table_candidate']['declared_count_mismatch'])

    @unittest.skipIf(PdfReader is None,'pypdf not installed; positional fixtures run in PDF smoke environment')
    def test_duplicate_whole_page_is_not_accepted(self):
        pdf=PdfReader(HERE/'MOCK_S_30_POSITIONAL_NOT_OFFICIAL.pdf')
        writer=PdfWriter(); writer.add_page(pdf.pages[0]);writer.add_page(pdf.pages[0])
        out=_parse_pdf_positioned_answers(writer.pages,expected_question_count=30)
        self.assertEqual(out['candidates'],{})
        self.assertEqual(len(out['conflicting_numbers']),30)

    @unittest.skipIf(PdfReader is None,'pypdf not installed; positional fixtures run in PDF smoke environment')
    def test_original_30_answer_candidates_must_agree(self):
        raw=fixture('MOCK_S_30_POSITIONAL_NOT_OFFICIAL.pdf')
        table=_parse_pdf_positioned_answers(PdfReader(HERE/'MOCK_S_30_POSITIONAL_NOT_OFFICIAL.pdf').pages,expected_question_count=30)
        original={int(k):v for k,v in table['candidates'].items()}
        r=report(raw,30,'S',qanswers=original)
        text='科 目：合成測試科目\n甲、作文部分：\n乙、測驗題部分：\n'
        r['extracted_question_text']['sha256']=hashlib.sha256(text.encode()).hexdigest()
        out=build_overlay(r,text,report_bytes=json.dumps(r).encode(),answer_pdf=raw,answer_role='S')
        evidence=out['answer_and_correction_evidence']['table_candidate']
        self.assertEqual(evidence['original_candidate_overlap_count'],30)
        self.assertEqual(evidence['original_candidate_conflict_numbers'],[])
        self.assertTrue(evidence['complete_numbering_candidate'])
        self.assertFalse(out['scoring_enabled'])
        original[3] = 'A' if original[3] != 'A' else 'B'
        mismatch=report(raw,30,'S',qanswers=original)
        mismatch['extracted_question_text']['sha256']=hashlib.sha256(text.encode()).hexdigest()
        out2=build_overlay(mismatch,text,report_bytes=json.dumps(mismatch).encode(),answer_pdf=raw,answer_role='S')
        evidence2=out2['answer_and_correction_evidence']['table_candidate']
        self.assertEqual(evidence2['original_candidate_conflict_numbers'],[3])
        self.assertEqual(evidence2['candidates'],{})
        self.assertFalse(evidence2['complete_numbering_candidate'])

    @unittest.skipIf(PdfReader is None,'pypdf not installed; positional fixtures run in PDF smoke environment')
    def test_modified_cached_document_is_rejected(self):
        raw=fixture('MOCK_S_30_POSITIONAL_NOT_OFFICIAL.pdf');r=report(raw,30,'S')
        with self.assertRaises(OverlayError):
            inspect_corrected_pdf(raw+b'a',declared_url=r['official_source']['answer_url'],role='S',report=r,expected_count=30)
        with self.assertRaises(OverlayError):
            inspect_corrected_pdf(raw,declared_url=Q_M.replace('t=Q','t=S'),role='S',report=r,expected_count=30)

if __name__ == '__main__':
    unittest.main()
