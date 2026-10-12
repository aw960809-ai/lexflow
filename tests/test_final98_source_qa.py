"""Offline tests only: V4 source audit must NEVER claim official answer or scoring approval."""
from pathlib import Path
import copy
import csv
import hashlib
import io
import json
import os
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import final98_source_qa as qa

Q='https://wwwq.moex.gov.tw/exam/wHandExamQandA_File.ashx?t=Q&code=114120&c=301&s=0101&q=1'
S=Q.replace('t=Q','t=S')
OTHER_CLASS=S.replace('c=301','c=302')
PID='MOEX-Q-'+'a'*20
SOURCE='a'*64

def document(role,url,sha='b'*64):
    return {'paper_id':PID,'role':role,'official_url':url,'source_sha256':sha}

def fixture():
    return {'schema':'lexflow.final98.paper.preview.v1','id':PID,'officialUrl':Q,
            'sourcePdfSha256':SOURCE,'publication_allowed':False,'scoring_enabled':False,'answers_omitted':True,
            'sources':[document('VERIFY_Q',Q,SOURCE),document('MISSING_S',S)],
            'articles':[],
            'questions':[
                {'id':PID+'-M-1','kind':'MCQ','number':'1','stem':'請依現行法律作答（示範）',
                 'options':['甲','乙','丙','丁'],'subject':'民法','domains':['民法'],
                 'articleKey':None,'risks':['SUBJECT_UNDECIDED'],
                 'proofStatus':'AUTO_PROVEN','effectiveSha256':'c'*64,'previewIssue':None,'previewOnly':True},
                {'id':PID+'-E-一','kind':'ESSAY','number':'一','stem':'請論述應如何分析此案',
                 'options':[],'subject':'刑法','domains':['刑法'],'articleKey':None,'risks':[],
                 'proofStatus':'AUTO_PROVEN','effectiveSha256':'d'*64,'previewIssue':None,'previewOnly':True},
            ]}

def make_zip(path, obj=None, mchange=None):
    obj=obj or fixture()
    doc=qa.encode_json(obj)
    manifest={'schema':'lexflow.final98.shards.preview.v1','db_sha256':qa.SOURCE_DB_SHA,
        'publication_allowed':False,'scoring_enabled':False,'backend_import_allowed':False,
        'papers':[{'id':PID,'path':'papers/'+PID+'.json','sha256':qa.sha256(doc),
                   'questionCount':2,'mcqCount':1,'essayCount':1}]}
    if mchange:mchange(manifest)
    with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED) as z:
        z.writestr('manifest.json',qa.encode_json(manifest))
        z.writestr('audit.json','{}')
        z.writestr('papers/'+PID+'.json',doc)

EXPECT=dict(papers=1,questions=2,MCQ=1,ESSAY=1,risk_records=1,risk_questions=1,shared_articles=0)

class FakeResponse:
    def __init__(self,url,raw):self.url=url;self.io=io.BytesIO(raw)
    def geturl(self):return self.url
    def read(self,n):return self.io.read(n)
    def __enter__(self):return self
    def __exit__(self,*a):pass
class FakeOpener:
    def __init__(self,raw):self.raw=raw
    def open(self,req,timeout):return FakeResponse(req.full_url,self.raw)

class EvidenceQATests(unittest.TestCase):
    def test_verified_two_question_fixture_stays_locked(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'source.zip';make_zip(path)
            result,papers,docs,questions=qa.audit(path,EXPECT)
            self.assertEqual((result['papers'],result['questions'],len(questions)),(1,2,2))
            self.assertEqual(result['mcq_questions_by_s_role'],{'MISSING':1})
            self.assertFalse(result['official_scoring_permitted'])
            self.assertFalse(result['release_permitted'])
            self.assertEqual(len(papers),1)
            self.assertEqual(len(docs),2)
            self.assertEqual(questions[0]['risk_codes'],['SUBJECT_UNDECIDED'])
            self.assertEqual(len(qa.unique_source_tasks(docs)),1)

    def test_cross_class_is_association_not_approved_answer(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'x.zip';obj=fixture();obj['sources'][1]['official_url']=OTHER_CLASS
            make_zip(p,obj)
            result,*_=qa.audit(p,EXPECT)
            self.assertEqual(result['cross_class_source_rows'],1)
            self.assertEqual(result['cross_class_papers'],1)
            self.assertFalse(result['official_answer_pairing_complete'])
            self.assertEqual(qa.reference_relation(Q,OTHER_CLASS),'CROSS_CLASS_ASSOCIATION_NOT_AUTOMATICALLY_EQUIVALENT')

    def test_block_forged_scores_and_unsafe_source_or_duplicate_ids(self):
        cases=[]
        obj=fixture();obj['publication_allowed']=True;cases.append(obj)
        obj=fixture();obj['questions'][0]['answer']='B';cases.append(obj)
        obj=fixture();obj['questions'][0]['previewOnly']=False;cases.append(obj)
        obj=fixture();obj['questions'][1]['id']=obj['questions'][0]['id'];cases.append(obj)
        obj=fixture();obj['sources'][1]['official_url']='https://wwwq.moex.gov.tw.evil.example/file.pdf';cases.append(obj)
        obj=fixture();obj['sources'][1]['official_url']=Q;cases.append(obj)
        obj=fixture();obj['sources'][1]['source_sha256']='z'*64;cases.append(obj)
        obj=fixture();obj['questions'][0]['options']=['甲','','丙','丁'];cases.append(obj)
        with tempfile.TemporaryDirectory() as d:
            for i,obj in enumerate(cases):
                p=Path(d)/f'{i}.zip';make_zip(p,obj)
                with self.subTest(i=i),self.assertRaises(qa.ReviewError):qa.audit(p,EXPECT)

    def test_refuse_archive_manifest_hash_mutation_and_unexpected_entries(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'bad.zip'
            make_zip(p,mchange=lambda m:m['papers'][0].update(sha256='0'*64))
            with self.assertRaises(qa.ReviewError):qa.audit(p,EXPECT)
            make_zip(p,mchange=lambda m:m.update(scoring_enabled=True))
            with self.assertRaises(qa.ReviewError):qa.audit(p,EXPECT)
            make_zip(p)
            with zipfile.ZipFile(p,'a') as z:z.writestr('../credentials.txt','private')
            with self.assertRaises(qa.ReviewError):qa.audit(p,EXPECT)

    def test_pdf_signature_and_sha_cache_without_network(self):
        with tempfile.TemporaryDirectory() as d:
            raw=b'%PDF-1.4\n'+b'sample text\n'*40
            target={'url':S,'reference_sha256':qa.sha256(raw)}
            opener=FakeOpener(raw)
            r=qa.fetch_document(target,Path(d)/'cache',opener=opener)
            self.assertEqual(r['status'],'PDF_SHA256_MATCH')
            self.assertFalse(r['final_answer_verified'])
            second=qa.fetch_document(target,Path(d)/'cache',opener=FakeOpener(b'non-pdf'))
            self.assertEqual(second['status'],'CACHED_MATCH')
            target2={**target,'url':S.replace('code=114120','code=114121')}
            failed=qa.fetch_document(target2,Path(d)/'cache',opener=FakeOpener(b'<html>404</html>'*20))
            self.assertEqual(failed['status'],'FETCH_BLOCKED')

    def test_priority_rechecks_missing_s_before_existing_s(self):
        docs=[{'paper_id':PID,'role':'EXISTING_S','url':S,'reference_sha256':'b'*64,'class_relation':'EXACT'},
              {'paper_id':PID,'role':'MISSING_S','url':OTHER_CLASS,'reference_sha256':'c'*64,'class_relation':'CROSS_CLASS'}]
        todo=qa.unique_source_tasks(docs)
        self.assertEqual(todo[0]['url'],OTHER_CLASS)
        self.assertEqual(len(todo),2)

    def test_report_has_full_question_matrix_but_never_question_content(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'source.zip';make_zip(p)
            summary,rows,sources,questions=qa.audit(p,EXPECT)
            report=Path(d)/'report.zip'
            ret=qa.create_report(report,summary,rows,[{**s,'status':'NOT_FETCHED'} for s in qa.unique_source_tasks(sources)],questions)
            self.assertFalse(ret['release_permitted'])
            with zipfile.ZipFile(report) as z:
                self.assertEqual(z.testzip(),None)
                cols=list(csv.DictReader(io.StringIO(z.read('question_evidence_matrix.csv').decode('utf-8-sig'))))
                self.assertEqual(len(cols),2)
                self.assertNotIn('stem',cols[0]);self.assertNotIn('options',cols[0]);self.assertNotIn('answer',cols[0])
                self.assertFalse(json.loads(z.read('audit_summary.json'))['official_scoring_permitted'])

    def test_official_url_identity_and_security(self):
        for bad in ('http://wwwq.moex.gov.tw/exam/wHandExamQandA_File.ashx?t=S&code=114120&c=301&s=0101&q=1',
                    'https://wwwq.moex.gov.tw.evil.com/exam/wHandExamQandA_File.ashx?t=S&code=114120&c=301&s=0101&q=1',
                    S+'#fragment',S+'&t=Q',S.replace('t=S','t=X'),
                    S.replace('wwwq.moex.gov.tw','wwwq.moex.gov.tw@evil.com')):
            with self.subTest(url=bad), self.assertRaises(qa.ReviewError):qa.validate_official_url(bad)

    @unittest.skipUnless(os.getenv('LEXFLOW_FINAL98_SHARDS'), 'Real 449 ZIP only when explicitly provided offline')
    def test_real_449_zip_9399_questions(self):
        summary,papers,docs,questions=qa.audit(Path(os.environ['LEXFLOW_FINAL98_SHARDS']))
        self.assertEqual((summary['papers'],summary['questions']), (449,9399))
        self.assertEqual(summary['cross_class_source_rows'],17)
        self.assertEqual(summary['paper_s_role_counts'],{'EXISTING':196,'MISSING':50})
        self.assertEqual(len(qa.unique_source_tasks(docs)),301)
        self.assertEqual(len(questions),9399)

if __name__=='__main__':unittest.main()
