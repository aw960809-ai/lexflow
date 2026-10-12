"""Offline source-shaped tests: no invented exam answer letters are published."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from moex_question_pipeline import (split_question_text, correction_notice_review,
                                    positioned_pdf_cells, pair_positioned_answer_cells,
                                    parse_answer_table_text)
from moex_release_gate import audit_batch, ReleaseGateError, main


def cells_for_grid(n=25, bad=None):
    """MOEX-like 10-column printed table with 5 trailing template blanks."""
    cells=[]
    for line in range(3):
        for c in range(10):
            num=10*line+c+1
            x=30+c*52
            y=620-line*62
            cells.append({'page':0,'x':x,'y':y,'text':f'第{num}題'})
            if num<=n and num!=bad:
                cells.append({'page':0,'x':x+11,'y':y-21,'text':'ABCD'[(num-1)%4]})
    return cells


def sample_report(*, complete=True, correction=False):
    count=3
    entries=[]
    for n in range(1,count+1):
        options={k:f'官方第{n}題候審選項{k}' for k in 'ABCD'} if complete else {}
        entries.append({'number':n,'candidate_status': ('four_options_extracted_NEEDS_VISUAL_REVIEW' if complete else 'isolated_question_fragment_NEEDS_REVIEW'),
                        'stem_unverified':f'第{n}題候審題幹', 'options_unverified':options,
                        'published_standard_candidate':'ABC'[n-1] if complete else None,
                        'question_text_verified':False,'options_verified':False,
                        'correction_applied':False,'final_answer_verified':False,
                        'legal_explanation_verified':False,'eligible_for_scoring':False})
    return {'schema':'lexflow.moex.universal.batch.v1','status':'bounded_pdf_review_not_a_scored_bank',
       'publication_allowed':False,'scoring_enabled':False,'all_answers_verified':False,
       'all_question_text_verified':False,'correction_and_special_scoring_applied':False,
       'reviewed_items':[{
           'id':'p1','subject':'民法概要','classification':'subject_named',
           'source_link_identity_confirmed':True,'eligible_for_scoring':False,
           'answer_verified_final':False,'question_content_verified':False,
           'options_verified':False,'legal_explanation_verified':False,
           'documents':[{'role':'Q','sha256':'a'*64,'pdf_structure_readable':True,
                         'content_and_options_verified':False,'final_answer_verified':False,
                         'question_text_verified':False,'legal_explanation_verified':False,
                         'eligible_for_scoring':False},
                        {'role':'S','sha256':'b'*64,'pdf_structure_readable':True,
                         'content_and_options_verified':False,'final_answer_verified':False,
                         'question_text_verified':False,'legal_explanation_verified':False,
                         'eligible_for_scoring':False}],
           'question_answer_candidates':{
                'schema':'lexflow.moex.question.candidates.v1',
                'publication_allowed':False,'scoring_enabled':False,
                'final_answer_verified':False,'special_scoring_applied':False,
                'question_text_and_options_verified':False,
                'all_subject_names_exactly_confirmed':True,
                'published_question_extraction':{'expected_question_count':count},
                'published_standard_answer_extraction':{
                    'status':'published_standard_letter_candidates_NOT_FINAL' if complete else 'incomplete_answer_table_NEEDS_REVIEW',
                    'published_candidates':[{'number':n,'published_standard_candidate':'ABC'[n-1]} for n in range(1,count+1)] if complete else [],
                    'final_answer_verified':False},
                'official_correction':{'detected':correction,'correction_applied':False,
                                       'final_answer_verified':False},
                'questions':entries}}]}


class QualityUpgradeTests(unittest.TestCase):
    def test_last_five_answers_use_positional_cells_not_assumed_order(self):
        c=cells_for_grid()
        pairs=pair_positioned_answer_cells(c,expected_count=25)
        self.assertEqual(len(pairs),25)
        self.assertEqual(pairs[25],'ABCD'[24%4])
        ans=parse_answer_table_text(['單選題數：25題\n第1題 A'],expected_count=25,
                                    positioned_cells=c)
        self.assertEqual(len(ans['published_candidates']),25)
        self.assertTrue(ans['evidence_method'].startswith('positioned_pdf_cell_alignment'))
        self.assertFalse(ans['final_answer_verified'])

    def test_missing_interior_answer_is_not_shifted_or_guessed(self):
        self.assertEqual(pair_positioned_answer_cells(cells_for_grid(bad=23),expected_count=25),{})
        p=parse_answer_table_text(['單選題數：25題'],expected_count=25,
                                  positioned_cells=cells_for_grid(bad=23))
        self.assertEqual(p['published_candidates'],[])

    def test_horizontal_shift_across_columns_rejected(self):
        c=cells_for_grid()
        for x in c:
            if x['text'] in 'ABCD' and x['y']==599:
                x['x']+=51
        self.assertEqual(pair_positioned_answer_cells(c,expected_count=25),{})

    def test_conflicting_text_table_and_positioned_cells_fail_closed(self):
        c=cells_for_grid(n=3)
        # Limit only 3 headed cells for a small, clean example.
        c=[x for x in c if x['text'] in ['第1題','第2題','第3題','A','B','C'] and x['y']>=590]
        self.assertEqual(len(pair_positioned_answer_cells(c,expected_count=3)),3)
        conflicting='單選題數：3題\n題號 第1題 第2題 第3題\n答案 D B C'
        ans=parse_answer_table_text([conflicting],expected_count=3,positioned_cells=c)
        self.assertEqual(ans['published_candidates'],[])
        self.assertIn('conflicting',ans['status'])

    def test_last_heading_cannot_borrow_first_answer_on_following_line(self):
        # A common error in PDF table extraction is to pair 第10題 with A
        # printed on the *next* line for 第1題. This used to produce false keys.
        text='單選題數：3題\n第1題       第2題       第3題\nA B C'
        got=parse_answer_table_text([text],expected_count=3)
        self.assertEqual(got['published_candidates'],[])
        self.assertIn('NEEDS_REVIEW',got['status'])

    def test_unspecified_letters_and_merged_position_chunks_cannot_guess(self):
        c=cells_for_grid()
        c=[x for x in c if x['text']!='第25題']
        self.assertEqual(pair_positioned_answer_cells(c,expected_count=25),{})

    def test_page_frame_cleaning_only_for_exact_complete_boundary(self):
        q='共 2 題\n1 敘述何者正確？\ue18c甲\ue18d乙\ue18e丙\ue18f丁\n代號：20120\n20320\n頁次：4－2\n2 敘述何者正確？\ue18c甲\ue18d乙\ue18e丙\ue18f丁'
        r=split_question_text(q)
        self.assertEqual(r['four_option_candidates'],2)
        self.assertEqual(r['items'][0]['options_unverified']['D'],'丁')
        # A page number in a genuine option sentence must not be removed.
        unsafe=q.replace('頁次：4－2','頁次：4－2\n另有證據')
        r=split_question_text(unsafe)
        self.assertEqual(r['four_option_candidates'],1)
        self.assertIn('page_header_or_footer_inside_question',r['items'][0]['review_reasons'])

    def test_correction_remarks_number_and_credit_held_for_human_review(self):
        m='測驗題標準答案更正\n第1題 第2題 第3題\n# B C\n備　註： 第1題答Ｂ或Ｃ者均給分。\n標準答案：答案標註#者，表該題有更正答案'
        out=correction_notice_review(m,expected_count=50)
        self.assertEqual(out['affected_question_numbers_NEEDS_VISUAL_CHECK'],[1])
        self.assertTrue(out['special_scoring_mentioned'])
        self.assertTrue(out['correction_marker_present'])
        self.assertFalse(out['correction_applied'])
        self.assertFalse(out['final_answer_verified'])

    def test_no_remarks_does_not_guess_from_grid_question_numbers(self):
        out=correction_notice_review('第1題 第2題 答案更正，見原卷',expected_count=25)
        self.assertEqual(out['affected_question_numbers_NEEDS_VISUAL_CHECK'],[])
        self.assertFalse(out['notice_is_bounded_to_remarks'])

    def test_release_gate_audits_complete_candidates_but_never_authorizes(self):
        out=audit_batch(sample_report(complete=True))
        self.assertEqual(out['summary']['structure_complete_not_content_verified'],1)
        self.assertEqual(out['papers'][0]['status'],'structure_complete_STILL_NEEDS_HUMAN_REVIEW')
        self.assertFalse(out['publication_allowed'])
        self.assertFalse(out['papers'][0]['score_release_allowed'])
        self.assertIn('human_confirmed_final_answer_and_source_date_missing',out['papers'][0]['reasons'])

    def test_release_gate_exposes_missing_options_and_answers(self):
        out=audit_batch(sample_report(complete=False))
        self.assertEqual(out['summary']['pending_or_isolated_papers'],1)
        self.assertIn('question_stem_or_four_options_need_visual_review',out['papers'][0]['reasons'])

    def test_release_gate_records_correction_and_special_review(self):
        out=audit_batch(sample_report(correction=True))
        self.assertIn('published_correction_or_special_credit_needs_manual_application',out['papers'][0]['reasons'])
        self.assertFalse(out['scoring_enabled'])

    def test_tampered_nested_scores_are_rejected(self):
        j=sample_report();j['reviewed_items'][0]['question_answer_candidates']['questions'][1]['eligible_for_scoring']=True
        with self.assertRaises(ReleaseGateError):audit_batch(j)

    def test_gate_does_not_accept_conflicting_number_or_answer_pairs(self):
        j=sample_report()
        a=j['reviewed_items'][0]['question_answer_candidates']
        a['published_standard_answer_extraction']['published_candidates'][1]['number']=7
        out=audit_batch(j)
        self.assertEqual(out['summary']['structure_complete_not_content_verified'],0)
        j=sample_report()
        a=j['reviewed_items'][0]['question_answer_candidates']
        a['published_standard_answer_extraction']['published_candidates'][0]['published_standard_candidate']='D'
        out=audit_batch(j)
        self.assertEqual(out['summary']['structure_complete_not_content_verified'],0)
        j=sample_report();j['publication_allowed']=True
        with self.assertRaises(ReleaseGateError):audit_batch(j)

    def test_quality_gate_is_read_only_and_atomic_on_failure(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'candidate.json';q=Path(td)/'review.json'
            p.write_text(json.dumps(sample_report()),encoding='utf-8')
            self.assertEqual(main(['--input',str(p),'--output',str(q)]),0)
            self.assertEqual(json.loads(q.read_text())['publication_allowed'],False)
            p.write_text('{ BAD JSON',encoding='utf-8')
            old=q.read_bytes()
            self.assertEqual(main(['--input',str(p),'--output',str(q)]),2)
            self.assertEqual(q.read_bytes(),old)

    def test_invalid_source_candidate_cannot_be_used_as_release(self):
        for corrupt in [{'schema':'wrong'}, {}, {'schema':'lexflow.moex.universal.batch.v1','status':'review_plan_only_no_download','reviewed_items':[{'id':'x'}]}]:
            with self.assertRaises(ReleaseGateError):audit_batch(corrupt)


if __name__=='__main__':
    unittest.main()
