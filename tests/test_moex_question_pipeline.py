"""Offline source-shaped fixtures: answer letters are TEST DATA, not MOEX claims."""
import unittest
from unittest.mock import patch
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from moex_question_pipeline import (QuestionExtractionError, split_question_text,
                                    parse_answer_table_text, make_question_answer_review)
from moex_batch_engine import process_batch, BatchReviewError

Q3 = '''司法四等考試 科目：民法概要
甲、申論題部分：（50分）
一、問答題不是選擇題。
乙、測驗題部分：（6分）
本試題為單一選擇題，共3題，每題2分。
1 下列何者為第一題測試敘述？
\ue18c選項甲\ue18d選項乙\ue18e選項丙\ue18f選項丁
2 下列何者為第二題測試敘述？
\ue18c文字Ａ \ue18d文字Ｂ\n\ue18e文字Ｃ \ue18f文字Ｄ
3 下列何者為第三題測試敘述？
\ue18c第一個答案 \ue18d第二個答案
\ue18e第三個答案 \ue18f第四個答案'''
S3 = '''測驗式試題標準答案
科目名稱：民法概要　單選題數：3題
題號 第1題 第2題 第3題
答案 A B C'''


def sample_index():
    base='https://wwwq.moex.gov.tw/exam/wHandExamQandA_File.ashx?code=114120&c=201&q=1&s=0405&t='
    return {'schema':'lexflow.moex.index.v1','status':'fallback_official_page_links_unverified',
            'source':{'method':'official_exam_page_html'},
            'items':[{'id':'test-only-paper','year_roc':'114','exam':'司法考試','subject':'民法概要',
                      'focus_subjects':['民法'],'classification':'subject_named',
                      'question_url':base+'Q','answer_url':base+'S',
                      'answer_correction_url':'','groups':['測試類科']} ]}


def inspect_mock(*_):
    return {'pdf_structure_readable':True, 'expected_subject_label_seen':True,
            'pages':1,'sha256':'fixture','bytes':120,
            'content_and_options_verified':False,'final_answer_verified':False}


class UniversalQuestionAnswerTests(unittest.TestCase):
    def test_three_question_and_four_special_moex_glyphs(self):
        result=split_question_text(Q3)
        self.assertEqual(result['expected_question_count'],3)
        self.assertTrue(result['count_matches_declared'])
        self.assertEqual(result['four_option_candidates'],3)
        self.assertEqual(result['items'][1]['options_unverified'],
                         {'A':'文字Ａ','B':'文字Ｂ','C':'文字Ｃ','D':'文字Ｄ'})
        self.assertTrue(all(x['eligible_for_scoring'] is False for x in result['items']))

    def test_parenthesized_abcd_option_variant_without_pua(self):
        raw=Q3.replace('\ue18c','（A）').replace('\ue18d','（B）').replace('\ue18e','（C）').replace('\ue18f','（D）')
        r=split_question_text(raw)
        self.assertEqual(r['four_option_candidates'],3)
        self.assertEqual(r['items'][0]['options_unverified']['A'],'選項甲')

    def test_mixed_pua_and_parenthesized_labels_are_ambiguous(self):
        raw=Q3.replace('\ue18c選項甲','（A）選項甲',1)
        r=split_question_text(raw)
        self.assertEqual(r['four_option_candidates'],2)
        self.assertIn('mixed_option_marker_styles_are_ambiguous',r['items'][0]['review_reasons'])

    def test_complete_page_frame_is_excluded_only_from_candidate_with_provenance(self):
        raw=Q3.replace('3 下列何者', '代號：20120\n頁次：4－2\n3 下列何者')
        # Keep unmodified raw source; drop an exact boundary footer from the
        # candidate's last option, which still needs visual PDF comparison.
        result=split_question_text(raw)
        self.assertTrue(result['count_matches_declared'])
        self.assertEqual(result['four_option_candidates'],3)
        self.assertIn('代號：20120',result['items'][1]['raw_pdf_excerpt_unverified'])
        self.assertNotIn('代號：20120',result['items'][1]['options_unverified']['D'])
        self.assertIn('trailing_official_page_frame_excluded_from_candidate',
                      result['items'][1]['source_normalizations_unverified'])
        self.assertFalse(result['items'][1]['eligible_for_scoring'])
        self.assertNotIn('page_header_or_footer_inside_question',result['items'][0]['review_reasons'])

    def test_scrambled_options_are_never_claimed_valid(self):
        for scrambled in ['\ue18cA \ue18dB \ue18dduplicate \ue18fD',
                          '\ue18cA \ue18eC \ue18fD','A) one B) two C) three D) four']:
            r=split_question_text(Q3.replace('\ue18c選項甲\ue18d選項乙\ue18e選項丙\ue18f選項丁',scrambled))
            self.assertEqual(r['four_option_candidates'],2)
            self.assertEqual(r['items'][0]['options_unverified'],{})

    def test_incomplete_run_and_count_conflict_stay_unverified(self):
        v=split_question_text(Q3.replace('3 下列何者為第三題','4 下列何者為第三題'))
        self.assertFalse(v['count_matches_declared'])
        v=split_question_text(Q3,expected_count=4)
        self.assertFalse(v['count_matches_declared'])
        self.assertIn('question_count_conflict',v['warnings'])

    def test_ambiguous_duplicate_sequence_cannot_pick_a_run(self):
        v=split_question_text(Q3+'\n'+Q3[Q3.index('1 下列'):])
        self.assertEqual(v['observed_sequential_numbers'],0)
        self.assertFalse(v['count_matches_declared'])

    def test_oversized_question_text_rejected(self):
        with self.assertRaises(QuestionExtractionError):
            split_question_text('x'*400001)

    def test_standard_answer_rows_pair_only_explicit_cells(self):
        result=parse_answer_table_text([S3],expected_count=3)
        self.assertEqual(result['status'],'published_standard_letter_candidates_NOT_FINAL')
        self.assertEqual([p['published_standard_candidate'] for p in result['published_candidates']],list('ABC'))
        self.assertFalse(result['final_answer_verified'])

    def test_inline_number_answer_pairs_can_be_read_when_complete(self):
        r=parse_answer_table_text(['單選題數：3題\n第1題 A\n第2題 D\n第3題 C'],expected_count=3)
        self.assertEqual([i['published_standard_candidate'] for i in r['published_candidates']],['A','D','C'])

    def test_non_linear_table_cannot_guess_answer_order(self):
        source='單選題數：3題\n第1題 第2題 第3題\nA B C\n其他表格欄位'
        r=parse_answer_table_text([source],expected_count=3)
        self.assertEqual(r['published_candidates'],[])
        self.assertIn('NEEDS_REVIEW',r['status'])

    def test_partial_or_conflicting_answer_table_never_produces_keys(self):
        partial='單選題數：3題\n題號 第1題 第2題\n答案 A B'
        r=parse_answer_table_text([partial],expected_count=3)
        self.assertEqual(r['published_candidates'],[])
        conflicting=S3.replace('答案 A B C','答案 A D C')
        r=parse_answer_table_text([S3,conflicting],expected_count=3)
        self.assertEqual(r['published_candidates'],[])
        self.assertIn('conflicting',r['status'])

    def test_special_scoring_language_prevents_key_promotion(self):
        r=parse_answer_table_text([S3+'\n備註：第2題一律給分'],expected_count=3)
        self.assertTrue(r['special_scoring_mentioned'])
        self.assertEqual(r['published_candidates'],[])
        self.assertIn('NEEDS_REVIEW',r['status'])
        # A generic blank '複選題數' line on official sheets is not a
        # special scoring decision for this all-single-choice paper.
        r=parse_answer_table_text([S3+'\n複選題數：　'],expected_count=3)
        self.assertEqual(len(r['published_candidates']),3)

    def test_answer_count_mismatch_isolated(self):
        r=parse_answer_table_text([S3.replace('3題','25題')],expected_count=3)
        self.assertEqual(r['published_candidates'],[])
        self.assertIn('conflict',r['status'])

    def test_missing_answer_count_isolated(self):
        r=parse_answer_table_text([S3],expected_count=None)
        self.assertEqual(r['published_candidates'],[])

    def test_assemble_paired_q_and_s_but_never_score(self):
        def fake_read(blob):
            return (Q3,'') if blob==b'q' else (S3,S3)
        with patch('moex_question_pipeline._get_pdf_texts',side_effect=fake_read):
            r=make_question_answer_review({'Q':b'q','S':b's'},
                                          expected_subject='民法概要',identity_paired=True)
        self.assertEqual(r['candidate_question_count'],3)
        self.assertEqual(r['candidate_answer_pair_count'],3)
        self.assertEqual(r['questions'][1]['published_standard_candidate'],'B')
        for p in r['questions']:
            self.assertFalse(p['final_answer_verified'])
            self.assertFalse(p['eligible_for_scoring'])
        self.assertFalse(r['publication_allowed'])
        self.assertFalse(r['scoring_enabled'])

    def test_official_m_correction_stays_separate_from_published_s(self):
        def read(blob):
            if blob==b'q':return Q3,''
            if blob==b's':return S3,S3
            return '民法概要\n第2題更正答案為D，其他一律給分',''
        with patch('moex_question_pipeline._get_pdf_texts',side_effect=read):
            r=make_question_answer_review({'Q':b'q','S':b's','M':b'm'},
                                          expected_subject='民法概要',identity_paired=True)
        self.assertTrue(r['official_correction']['detected'])
        self.assertTrue(r['official_correction']['special_scoring_mentioned'])
        self.assertFalse(r['official_correction']['correction_applied'])
        self.assertEqual(r['questions'][1]['published_standard_candidate'],'B')
        self.assertFalse(r['questions'][1]['final_answer_verified'])

    def test_parenthetical_title_difference_is_labelled_as_partial_evidence(self):
        source_title='綜合法政知識與英文(包括中華民國憲法、法學緒論、兩岸關係、英文)'
        def read(blob):
            return (Q3.replace('民法概要', '綜合法政知識與英文'), '') if blob==b'q' else (S3.replace('民法概要', '綜合法政知識與英文'),S3.replace('民法概要', '綜合法政知識與英文'))
        with patch('moex_question_pipeline._get_pdf_texts',side_effect=read):
            r=make_question_answer_review({'Q':b'q','S':b's'},expected_subject=source_title,identity_paired=True)
        self.assertIn('prefix_only',r['source_subject_title_check']['question'])
        self.assertFalse(r['all_subject_names_exactly_confirmed'])
        self.assertFalse(r['publication_allowed'])

    def test_unpaired_answer_cannot_be_mapped(self):
        def read(blob):return (Q3,'') if blob==b'q' else (S3,S3)
        with patch('moex_question_pipeline._get_pdf_texts',side_effect=read):
            with self.assertRaises(QuestionExtractionError):
                make_question_answer_review({'Q':b'q','S':b's'},
                                            expected_subject='民法概要',identity_paired=False)

    def test_wrong_subject_in_pdf_fails_closed(self):
        with patch('moex_question_pipeline._get_pdf_texts',return_value=('行政管理非本科目','')):
            with self.assertRaises(QuestionExtractionError):
                make_question_answer_review({'Q':b'q'},expected_subject='民法概要',identity_paired=True)

    def test_batch_extraction_can_run_independently_and_protect_nested_scoring(self):
        def dishonest_enrich(*args,**kwargs):
            return {'schema':'lexflow.moex.question.candidates.v1','publication_allowed':False,
                    'scoring_enabled':False,'candidate_question_count':3,
                    'candidate_answer_pair_count':0,
                    'questions':[{'number':1,'eligible_for_scoring':True,'final_answer_verified':True}]}
        result=process_batch(sample_index(),max_papers=1,max_documents=2,
                             download=True,require_all=True,extract_questions=True,
                             min_question_candidates=3,fetch=lambda ref:b'fixture',
                             inspect=inspect_mock,enrich=dishonest_enrich)
        row=result['reviewed_items'][0]['question_answer_candidates']['questions'][0]
        self.assertFalse(row['eligible_for_scoring'])
        self.assertFalse(row['final_answer_verified'])
        self.assertEqual(result['summary']['candidate_question_pipeline']['four_option_candidacies'],3)
        self.assertFalse(result['scoring_enabled'])

    def test_extraction_failure_isolated_and_strict_ci_fails(self):
        def failed(*args,**kwargs):raise QuestionExtractionError('source layout changed')
        report=process_batch(sample_index(),max_papers=1,max_documents=2,
                             download=True,extract_questions=True,
                             fetch=lambda ref:b'fixture',inspect=inspect_mock,enrich=failed)
        self.assertEqual(report['reviewed_items'][0]['state'],'isolated_needs_review')
        self.assertIn('question_answer_extraction_isolated',report['reviewed_items'][0]['warnings'])
        with self.assertRaises(BatchReviewError):
            process_batch(sample_index(),max_papers=1,max_documents=2,
                          download=True,require_all=True,extract_questions=True,
                          fetch=lambda ref:b'fixture',inspect=inspect_mock,enrich=failed)

    def test_candidate_mode_rejects_no_download_and_invalid_minimum(self):
        with self.assertRaises(BatchReviewError):
            process_batch(sample_index(),extract_questions=True,download=False)
        with self.assertRaises(BatchReviewError):
            process_batch(sample_index(),min_question_candidates=3)


if __name__ == '__main__':
    unittest.main()
