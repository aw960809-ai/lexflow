"""Offline source-safety and whole-paper parsing regression tests.
Fixture M PDF is entirely synthetic, NOT an official exam or answer key.
"""
from __future__ import annotations
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
# Tests also support working on a patch source tree before staging.
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from moex_quality_overlay import (
    _sha, OverlayError, clean_page_frames, _essay_entries, section_index,
    normalize_label, title_evidence, repaired_questions, parse_special_credit_note,
    parse_table_candidates, inspect_corrected_pdf, build_overlay,
    make_overlay_from_disk,
)

Q='https://wwwq.moex.gov.tw/exam/wHandExamQandA_File.ashx?t=Q&code=114010&c=501&s=0202&q=1'
M=Q.replace('t=Q','t=M')


def sample(text:str, *, typ='申論題', subject='行政法', questions=None, answer_pdf=None):
    p_id='moex-'+'a'*24
    q_doc=[{'role':'Q','url':Q,'sha256':'0'*64}]
    if answer_pdf:q_doc.append({'role':'M','url':M,'sha256':_sha(answer_pdf)})
    report={
        'schema':'lexflow.moex.whole-paper-review.v1',
        'paper_id':p_id,'publication_allowed':False,'scoring_enabled':False,
        'extracted_question_text':{'sha256':_sha(text.encode())},
        'official_source':{'paper_id':p_id,'official_subject':subject,'official_type':typ,
                           'question_url':Q,'answer_url':M if answer_pdf else ''},
        'v03_review':{'publication_allowed':False,'scoring_enabled':False,'reviewed_items':[
            {'documents':q_doc,'question_answer_candidates':{'questions':questions or [],'publication_allowed':False,'scoring_enabled':False}}
        ]}
    }
    return report


class QualityOverlayTests(unittest.TestCase):
    def test_essay_chinese_headings_directly_followed_by_chinese_are_recognized(self):
        text='一、甲乙間發生租賃糾紛，請分析契約關係。（25 分）\n二、其他民事程序爭議，試論救濟方式。（25 分）'
        x=section_index(text,'申論題')
        self.assertEqual(x['essay']['count'],2)
        self.assertEqual([s['number'] for s in x['essay']['sections']],[1,2])
        self.assertFalse(any(s['is_separate_paper'] for s in x['essay']['sections']))

    def test_sequence_gaps_and_duplicate_headings_fail_closed(self):
        for text in ['一、甲乙有長篇爭議需要分析多種規範。\n三、其他法律問題請說明理由。',
                     '一、長篇案情請分析請求權基礎。\n一、另一個大題卻重複編號。']:
            self.assertEqual(section_index(text,'申論題')['essay']['count'],0)

    def test_exact_two_line_page_frame_removed_not_question_law(self):
        raw='這裡是答案D的內容\n代號：30110-31110\n頁次：6－2\n'
        clean,notes=clean_page_frames(raw)
        self.assertEqual(clean.strip(),'這裡是答案D的內容')
        self.assertEqual(len(notes),1)
        content='法院認為「代號：30110-31110」有意義\n頁次：6－2\n'
        self.assertEqual(clean_page_frames(content)[0],content)
        self.assertEqual(clean_page_frames('代號：30110-31110\n頁次：1－6\n')[1],[])

    def test_mixed_composition_never_called_legal_essay(self):
        text='甲、作文部分：（40 分）\n請以生命經驗寫一篇作文。\n乙、測驗題部分：（60 分）\n1 第一題內容長一些\n2 第二題內容長一些'
        sections=section_index(text,'混合題')['sections']
        self.assertEqual([s['type'] for s in sections],['composition','multiple_choice'])
        self.assertTrue(sections[1]['numbering_sequential'])
        self.assertEqual(sections[1]['numeric_heading_candidate_count'],2)
        self.assertFalse(any(s['is_separate_paper'] for s in sections))

    def test_avoid_inventing_missing_mixed_sections(self):
        s=section_index('單獨作文題，但沒有甲乙分段。','混合題')
        self.assertEqual(s['state'],'mixed_subsections_missing_or_ambiguous')

    def test_name_nfkc_equivalent_without_overwriting_original(self):
        label='基礎能力測驗(作文、中華民國憲法及法學緒論)'
        actual='科 目：基礎能力測驗（作文、中華民國憲法及法學緒論）\n'
        d=title_evidence(label,actual)
        self.assertTrue(d['match_after_NFKC'])
        self.assertEqual(d['official_name_unchanged'],label)
        self.assertNotEqual(label,d['pdf_label_unverified'])
        self.assertNotEqual(normalize_label('民法'),'刑法')

    def test_five_page_contaminated_questions_recovered_as_unverified(self):
        q=[]
        for n in range(1,31):
            stained=n in (1,8,13,19,25)
            optD='選項D\n代號：30110-31110\n頁次：6－2' if stained else '選項D'
            q.append({'number':n,'candidate_status':'isolated_question_fragment_NEEDS_REVIEW' if stained else 'four_options_extracted_NEEDS_VISUAL_REVIEW',
                'review_reasons':['page_header_or_footer_inside_question'] if stained else [],
                'options_unverified':{'A':'選項A','B':'選項B','C':'選項C','D':optD},
                'published_standard_candidate':'A','final_answer_verified':False})
        copy_before=copy.deepcopy(q)
        out=repaired_questions(q,type_label='混合題')
        self.assertEqual(out['candidate_count'],30)
        self.assertEqual([s['number'] for s in out['repaired']],[1,8,13,19,25])
        self.assertTrue(all(x['scoring_enabled'] is False for x in out['question_candidates']))
        self.assertEqual(q,copy_before,'Source candidates MUST remain immutable')
        self.assertEqual(out['question_candidates'][0]['options_unverified']['D'],'選項D')

    def test_uncorroborated_header_or_incomplete_option_is_not_recovered(self):
        q=[{'number':1,'candidate_status':'isolated_question_fragment_NEEDS_REVIEW',
            'review_reasons':['page_header_or_footer_inside_question'],
            'options_unverified':{'A':'甲','B':'乙','C':'丙','D':'丁\n頁次：1－2'}}]
        self.assertEqual(repaired_questions(q,type_label='測驗題')['candidate_count'],0)

    def test_grid_pairing_validates_count_and_detects_conflicts(self):
        nums=' '.join(str(x) for x in range(1,51)); keys=' '.join('ABCD'[x%4] for x in range(1,51))
        out=parse_table_candidates('題號 '+nums+'\n答案 '+keys,expected_question_count=50)
        self.assertTrue(out['complete_numbering_candidate'])
        self.assertEqual(len(out['candidates']),50)
        bad=parse_table_candidates('題號 1 2 3\n答案 A B\n',expected_question_count=3)
        self.assertFalse(bad['complete_numbering_candidate'])
        conflict=parse_table_candidates('1 A\n1 B\n',expected_question_count=1)
        self.assertEqual(conflict['candidates'],{})
        self.assertEqual(conflict['conflicting_numbers'],[1])

    def test_two_valid_choices_are_not_reduced_to_a_single_key(self):
        m=parse_special_credit_note('修正公告：第20題 B或C均給分。')
        self.assertEqual(m[0]['candidate_valid_choices'],['B','C'])
        self.assertTrue(m[0]['requires_special_scoring_review'])

    def test_only_exact_official_answer_source_and_hash_is_allowed(self):
        try:import pypdf  # noqa
        except ImportError:self.skipTest('pypdf not installed in offline CI; use PDF smoke environment')
        blob=(Path(__file__).resolve().parent/'fixtures'/'synthetic_corrected_answer_NOT_OFFICIAL.pdf').read_bytes()
        rep=sample('科 目：法學大意\n1 第一題候審題幹。',typ='測驗題',subject='法學大意',answer_pdf=blob)
        good=inspect_corrected_pdf(blob,declared_url=M,role='M',report=rep,expected_count=50)
        self.assertEqual(good['table_candidate']['unique_paired_numbers'],50)
        self.assertEqual(good['cannot_convert_to_single_choice'],[20])
        self.assertFalse(good['scoring_enabled'])
        with self.assertRaises(OverlayError):
            inspect_corrected_pdf(blob+b'evil',declared_url=M,role='M',report=rep,expected_count=50)
        with self.assertRaises(OverlayError):
            inspect_corrected_pdf(blob,declared_url=M.replace('code=114010','code=113010'),role='M',report=rep,expected_count=50)

    def test_source_text_tampering_blocks_overlay(self):
        text='科 目：行政法\n一、此題題幹非常完整，請分析法律關係。'
        report=sample(text)
        raw=json.dumps(report).encode()
        with self.assertRaises(OverlayError):
            build_overlay(report,text+'hidden edit',report_bytes=raw)
        report['scoring_enabled']=True
        with self.assertRaises(OverlayError):
            build_overlay(report,text,report_bytes=raw)
        report['scoring_enabled']=False
        report['v03_review']['scoring_enabled']=True
        with self.assertRaises(OverlayError):
            build_overlay(report,text,report_bytes=raw)
        report['v03_review']['scoring_enabled']=False
        report['v03_review']['reviewed_items'][0]['question_answer_candidates']['questions']=[
            {'number':1,'final_answer_verified':True,'options_unverified':{}}
        ]
        with self.assertRaises(OverlayError):
            build_overlay(report,text,report_bytes=raw)

    def test_create_only_and_old_report_untouched(self):
        text='科 目：行政法\n一、試題題幹已完整，請分析不動產契約之法律關係。\n二、第二個題幹完整，請分析行政處分與救濟。'
        report=sample(text);pid=report['paper_id']
        with tempfile.TemporaryDirectory() as td:
            out=Path(td)
            a=out/'reports'/f'{pid}.json';a.parent.mkdir(parents=True)
            a.write_text(json.dumps(report,ensure_ascii=False),encoding='utf-8')
            f=out/'extracted_text'/f'{pid}.txt';f.parent.mkdir(parents=True);f.write_text(text,encoding='utf-8')
            original=a.read_bytes();original_text=f.read_bytes()
            target,overlay=make_overlay_from_disk(out,a)
            again,_=make_overlay_from_disk(out,a)
            self.assertEqual(target,again)
            self.assertEqual(original,a.read_bytes())
            self.assertEqual(original_text,f.read_bytes())
            self.assertFalse(overlay['publication_allowed'])
            self.assertFalse(overlay['scoring_enabled'])
            self.assertEqual(overlay['section_candidates']['essay']['count'],2)
            self.assertEqual(len(list((out/'quality_previews').glob('*.json'))),1)

if __name__=='__main__':unittest.main()
