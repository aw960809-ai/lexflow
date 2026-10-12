"""Offline staging checks: do not publish unverifiable MOEX answer claims."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from moex_release_gate import audit_batch
from moex_candidate_feed import stage_candidate, CandidateFeedError, main

Q='https://wwwq.moex.gov.tw/exam/wHandExamQandA_File.ashx?c=201&code=114120&q=1&s=0405&t=Q'
S=Q.replace('t=Q','t=S')

def fixture():
    qs=[]
    for n in range(1,4):
        qs.append({'number':n,'candidate_status':'four_options_extracted_NEEDS_VISUAL_REVIEW',
                   'review_reasons':[],'stem_unverified':f'第{n}題說明',
                   'options_unverified':{'A':'甲','B':'乙','C':'丙','D':'丁'},
                   'published_standard_candidate':'B','question_text_verified':False,
                   'options_verified':False,'final_answer_verified':False,'eligible_for_scoring':False})
    qa={'schema':'lexflow.moex.question.candidates.v1',
        'status':'candidate_question_and_published_answer_review_only',
        'question_text_and_options_verified':False,'final_answer_verified':False,
        'publication_allowed':False,'scoring_enabled':False,
        'published_question_extraction':{'expected_question_count':3},
        'published_standard_answer_extraction':{
            'status':'published_standard_letter_candidates_NOT_FINAL',
            'published_candidates':[{'number':n,'published_standard_candidate':'B'} for n in range(1,4)]},
        'official_correction':{'detected':False,'correction_applied':False},
        'all_subject_names_exactly_confirmed':True,
        'questions':qs}
    data={'schema':'lexflow.moex.universal.batch.v1',
          'status':'bounded_pdf_review_not_a_scored_bank',
          'publication_allowed':False,'scoring_enabled':False,
          'all_answers_verified':False,'all_question_text_verified':False,
          'reviewed_items':[{'id':'moex-sample','subject':'民法概要','state':'pdfs_readable_CONTENT_NOT_VERIFIED',
          'source_link_identity_confirmed':True,'classification':'subject_named',
          'documents':[{'role':r,'url':u,'pdf_structure_readable':True,'sha256':'a'*64}
                       for r,u in [('Q',Q),('S',S)]],
          'question_answer_candidates':qa}]}
    return data,audit_batch(data)

class CandidateFeedTests(unittest.TestCase):
    def test_valid_staged_candidate_is_unscored_and_deterministic(self):
        report,gate=fixture()
        staged=stage_candidate(report,gate)
        self.assertEqual(staged['schema'],report['schema'])
        self.assertEqual(staged['staging']['human_content_and_answer_review_satisfied'],False)
        self.assertEqual(staged['readiness']['status'],'human_quality_gate_NOT_SATISFIED')
        self.assertFalse(staged['scoring_enabled'])
        self.assertEqual(stage_candidate(report,gate),staged)
        self.assertNotIn('staging',report)
    def test_gate_spoof_cannot_approve(self):
        r,g=fixture();g['status']='all_final';self.assertRaises(CandidateFeedError,stage_candidate,r,g)
    def test_gate_summary_must_match_source(self):
        r,g=fixture();g['summary']['sampled_papers']=55
        self.assertRaises(CandidateFeedError,stage_candidate,r,g)
    def test_fake_release_flag_blocks(self):
        r,g=fixture();r['reviewed_items'][0]['question_answer_candidates']['questions'][0]['eligible_for_scoring']=True
        self.assertRaises(CandidateFeedError,stage_candidate,r,g)
    def test_single_invalid_url_blocks_and_no_dropping(self):
        r,g=fixture();r['reviewed_items'][0]['documents'][0]['url']='https://evil.com/q'
        self.assertRaises(CandidateFeedError,stage_candidate,r,g)
    def test_cross_paper_identity_fails_even_if_order_reversed(self):
        r,g=fixture();r['reviewed_items'][0]['documents'].reverse()
        r['reviewed_items'][0]['documents'][0]['url']=S.replace('s=0405','s=9999')
        self.assertRaises(CandidateFeedError,stage_candidate,r,g)
    def test_missing_q_source_blocks(self):
        r,g=fixture();r['reviewed_items'][0]['documents']=[r['reviewed_items'][0]['documents'][1]]
        self.assertRaises(CandidateFeedError,stage_candidate,r,g)
    def test_duplicate_question_number_blocks(self):
        r,g=fixture();r['reviewed_items'][0]['question_answer_candidates']['questions'][1]['number']=1
        self.assertRaises(CandidateFeedError,stage_candidate,r,g)
    def test_no_quadruple_option_is_unsafe(self):
        r,g=fixture()
        for q in r['reviewed_items'][0]['question_answer_candidates']['questions']:
            q['candidate_status']='isolated_question_fragment_NEEDS_REVIEW'
        self.assertRaises(CandidateFeedError,stage_candidate,r,g)
    def test_isolated_paper_never_staged(self):
        r,g=fixture();r['reviewed_items'][0]['state']='isolated_needs_review'
        self.assertRaises(CandidateFeedError,stage_candidate,r,g)
    def test_cli_failure_preserves_existing_destination(self):
        r,g=fixture()
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);p=root/'source.json';gr=root/'gate.json';out=root/'moex_review_candidate.json'
            p.write_text(json.dumps(r));gr.write_text(json.dumps(g));out.write_text('OLD')
            self.assertEqual(main(['--input',str(p),'--readiness',str(gr),'--output',str(out)]),0)
            written=out.read_text();self.assertEqual(main(['--input',str(p),'--readiness',str(gr),'--output',str(out)]),0)
            self.assertEqual(out.read_text(),written)
            gr.write_text('{}');self.assertEqual(main(['--input',str(p),'--readiness',str(gr),'--output',str(out)]),2)
            self.assertEqual(out.read_text(),written)
    def test_source_alias_must_be_rejected(self):
        r,g=fixture()
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);p=root/'moex_review_candidate.json';gr=root/'gate.json'
            p.write_text(json.dumps(r));gr.write_text(json.dumps(g))
            self.assertEqual(main(['--input',str(p),'--readiness',str(gr),'--output',str(p)]),2)

if __name__=='__main__':unittest.main()
