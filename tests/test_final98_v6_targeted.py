"""All in-memory PDFs are synthetic, not official answer keys.
No test authorizes official scoring, publication, or production import.
"""
from __future__ import annotations
import csv
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import final98_v6_targeted as v6
import final98_answer_candidate_v5 as v5

DATA=Path(os.environ.get('LEXFLOW_DATA_ROOT','/mnt/data'))
V4=Path(os.environ.get('LEXFLOW_FINAL98_V4',str(DATA/'LexFlow_Final98_V4_AutoQA_20261012_135713.zip')))
V5=Path(os.environ.get('LEXFLOW_FINAL98_V5',str(DATA/'LexFlow_Final98_V5_Candidates_20261012_144652.zip')))
SHARDS=Path(os.environ.get('LEXFLOW_FINAL98_SHARDS',str(DATA/'LexFlow_449_Shards_STAGING_20261012_104030.zip')))


class FakePage:
    def __init__(self,broken=None,declared='60/10'):
        self.cells=[]
        self.raw_text=('單選題數：60題(第1~60題)\n複選題數：10題(第61~70題)\n'
                       if declared=='60/10' else '單選題數：70題')
        for row_index in range(10):
            n0=row_index*10+1
            y=1400-row_index*75
            self.cells.extend([('題號',55,y),('答案',55,y-17)])
            for i in range(10):
                n=n0+i;x=145+i*65
                self.cells.append((f'第{n}題',x,y))
                if n>70:continue
                val='B' if n<=60 else ['AC','ACE','ABD','BDE','BC','AE','BCD','ACE','BD','CE'][n-61]
                if broken=='missing8' and n==8:continue
                if broken=='bad_multi' and n==64:val='AF'
                if broken=='shift8' and n==8:x+=33
                self.cells.append((val,x,y-17))
        if broken=='duplicate':
            self.cells.extend([('題號',55,30),('答案',55,13)])
            for i in range(10):
                n=i+1;x=145+i*65
                self.cells.extend([(f'第{n}題',x,30),('B',x,13)])

    def extract_text(self,visitor_text=None):
        if visitor_text is None:return self.raw_text
        for s,x,y in self.cells:
            visitor_text(s,[1,0,0,1,0,0],[1,0,0,1,x,y],None,12)
        return self.raw_text


class V6OfflineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if V4.exists() and V5.exists() and SHARDS.exists():
            cls.has_real=True
            _,cls.docs,cls.papers=v5.load_inputs(V4,SHARDS)
            cls.summary,cls.parsed,cls.rows=v6.v5_report_read(V5,V4,SHARDS,cls.papers,cls.docs)
        else:
            cls.has_real=False

    def require_real(self):
        if not self.has_real:self.skipTest('No uploaded V4/V5/shards: local optional integration fixture')

    def test_exact_class_sources_recover_400_but_not_cross_class_merge(self):
        self.require_real()
        selected,variants,_,warn=v6.collect_s_candidates(self.papers,self.parsed,None,{r['url']:r for r in self.docs})
        self.assertEqual(len(variants),8)
        self.assertFalse(warn)
        self.assertTrue(all(v['all_class_pdf_bytes_equivalent'] for v in selected.values() if v['source_count']>1))
        self.assertTrue(all(v['exact_count']==1 for v in variants))
        self.assertEqual(sum(len(v['candidateKeys']) for v in selected.values()),8150)
        for val in selected.values():
            if val['source_count']>1:
                self.assertEqual(len(val['other_class_sources']),val['source_count']-1)
                self.assertTrue(val['selected_url'])

    def test_new_proposals_never_mutate_original_v5_row(self):
        self.require_real()
        selected,_,_,_=v6.collect_s_candidates(self.papers,self.parsed,None,{r['url']:r for r in self.docs})
        md,_=v6.collect_m_source(self.papers,self.parsed,None,{r['url']:r for r in self.docs})
        originals=json.dumps(self.rows,sort_keys=True)
        rows,counts,new=v6.create_rows(self.rows,self.papers,selected,md)
        self.assertEqual(json.dumps(self.rows,sort_keys=True),originals)
        self.assertEqual(len(rows),8290)
        self.assertEqual((counts['V6_CANDIDATE'],counts['V6_NEW_CANDIDATES'],counts['V6_UNRESOLVED']),(8150,400,140))
        self.assertEqual(len(new),400)
        self.assertTrue(all(r['V6_publication_allowed']=='false' and r['V6_scoring_enabled']=='false' for r in rows))

    def test_leftover_140_are_two_mixed_papers(self):
        self.require_real()
        selected,_,_,_=v6.collect_s_candidates(self.papers,self.parsed,None,{r['url']:r for r in self.docs})
        unresolved={k:self.papers[k] for k,v in selected.items() if v['status']!='S_EXACT_CLASS_CANDIDATES_ONLY'}
        self.assertEqual(len(unresolved),2)
        self.assertEqual(sorted(p['mcq_count'] for p in unresolved.values()),[70,70])
        for p in unresolved.values():
            q=[i for i in p['questions'] if i['kind']=='MCQ']
            self.assertEqual(sum(len(i['options'])==4 for i in q),60)
            self.assertEqual(sum(len(i['options'])==5 for i in q),10)

    def test_m_markers_remain_blocked_when_no_private_cache(self):
        self.require_real()
        md,w=v6.collect_m_source(self.papers,self.parsed,None,{r['url']:r for r in self.docs})
        self.assertFalse(w)
        self.assertEqual(sum(len(x['unresolved_markers']) for x in md.values()),26)
        self.assertEqual(sum(len(x['notes_NOT_FINAL']) for x in md.values()),22)
        self.assertTrue(all(x['M_status'] in ('NO_RECORDED_M','M_PRESENT_CORRECTIONS_NOT_FINAL') for x in md.values()))

    def test_m_all_credit_note_is_candidate_only(self):
        r=v6.note_actions('單選題數：25題\n備　註：第11題一律給分。\n標準答案：',25,[11])
        self.assertEqual(r['recognized']['11']['type'],'ALL_CREDIT_CANDIDATE_NOT_FINAL')
        self.assertEqual(r['unresolved_markers'],[])

    def test_m_multiple_credit_and_replace(self):
        r=v6.note_actions('備註：第15題答C或D者均給分，第20題答案由A更正為B。',25,[15,20])
        self.assertEqual(r['recognized']['15']['choices'],'CD')
        self.assertEqual(r['recognized']['20']['after'],'B')
        self.assertFalse(r['unresolved_markers'])

    def test_m_note_unattached_or_conflict_stays_blocked(self):
        r=v6.note_actions('第15題一律給分 第16題一律給分',25,[15])
        self.assertEqual(r['notes_without_marker'],[16])
        self.assertEqual(r['recognized']['15']['type'],'ALL_CREDIT_CANDIDATE_NOT_FINAL')
        r=v6.note_actions('第15題一律給分 第15題答A或B者均給分',25,[15])
        self.assertIn(15,r['conflict_markers'])
        self.assertIn(15,r['unresolved_markers'])

    def test_mixed_70_geometry_preserves_60_plus_10(self):
        pg=FakePage()
        r=v6.parse_mixed_70_pages([pg],pg.extract_text())
        self.assertEqual((r['single'],r['multiple']), (60,10))
        self.assertEqual(len(r['keys']),70)
        self.assertEqual(r['keys']['61'],'AC')
        self.assertEqual(r['keys']['62'],'ACE')
        self.assertEqual(r['keys']['70'],'CE')
        self.assertFalse(r['final_answer_verified'])

    def test_mixed_missing_interior_option_rejected(self):
        p=FakePage('missing8')
        with self.assertRaises(v5.GateError):v6.parse_mixed_70_pages([p],p.extract_text())

    def test_mixed_shifted_coordinate_rejected(self):
        p=FakePage('shift8')
        with self.assertRaises(v5.GateError):v6.parse_mixed_70_pages([p],p.extract_text())

    def test_mixed_unknown_multi_choice_rejected(self):
        p=FakePage('bad_multi')
        with self.assertRaises(v5.GateError):v6.parse_mixed_70_pages([p],p.extract_text())

    def test_mixed_duplicate_page_rejected(self):
        p=FakePage('duplicate')
        with self.assertRaises(v5.GateError):v6.parse_mixed_70_pages([p],p.extract_text())

    def test_mixed_wrong_declaration_rejected(self):
        p=FakePage(declared='wrong')
        with self.assertRaises(v5.GateError):v6.parse_mixed_70_pages([p],p.extract_text())

    def test_export_schema_never_authorizes_production(self):
        self.require_real()
        selected,_,_,_=v6.collect_s_candidates(self.papers,self.parsed,None,{r['url']:r for r in self.docs})
        ms,_=v6.collect_m_source(self.papers,self.parsed,None,{r['url']:r for r in self.docs})
        records,_,_=v6.create_rows(self.rows,self.papers,selected,ms)
        with tempfile.TemporaryDirectory() as td:
            out=Path(td)/'report.zip'
            summary={'schema':v6.V6_SCHEMA,'publication_allowed':False,'official_scoring_enabled':False,
                     'final_answers_verified':False,'production_import_allowed':False}
            v6.write_output(out,summary,records,selected,ms)
            with zipfile.ZipFile(out) as z:
                a=json.loads(z.read('v6_summary.json'))
                self.assertFalse(a['official_scoring_enabled'])
                self.assertEqual(len(list(csv.DictReader(io.StringIO(z.read('v6_question_candidates_NOT_FINAL.csv').decode('utf-8-sig'))))),8290)
                self.assertNotIn('private_attempts',z.namelist())

if __name__=='__main__':unittest.main()
