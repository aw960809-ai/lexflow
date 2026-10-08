"""Fixture-only tests: no fictional items are distributed as MOEX exam records."""
import html
import json
import tempfile
import unittest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
from moex_index import SourceFailure
from moex_page_fallback import create_fallback_index, official_document_url, official_aggregate_answer_url, fetch_exam_page
from moex_sync import sync

BASE='https://wwwq.moex.gov.tw/exam/wHandExamQandA_File.ashx?c=201&code=114120&q=1&s=0405&t='
H='''<!doctype html><html lang="zh-Hant"><head><title>考畢試題查詢平臺</title></head>
<body><h1>考畢試題查詢</h1><h2>114年公務人員特種考試司法人員考試</h2>
<table>
<tr><td>司法四等考試_法院書記官類科</td></tr>
<tr><td>民法概要</td><td><a href="'''+BASE+'''Q">試題</a></td>
<td><a href="'''+BASE+'''S">答案</a></td></tr>
<tr><td>刑法概要</td><td><a href="/exam/wHandExamQandA_File.ashx?c=202&amp;code=114120&amp;q=1&amp;s=0406&amp;t=Q">試題</a></td></tr>
<tr><td>法學知識與英文（包括中華民國憲法、法學緒論、英文）</td>
<td><a href="/exam/wHandExamQandA_File.ashx?c=203&amp;code=114120&amp;q=1&amp;s=0407&amp;t=Q">試題</a></td>
<td><a href="/exam/wHandExamQandA_File.ashx?c=203&amp;code=114120&amp;q=1&amp;s=0407&amp;t=S">答案</a></td>
<td><a href="/exam/wHandExamQandA_File.ashx?c=203&amp;code=114120&amp;q=1&amp;s=0407&amp;t=M">更正答案</a></td></tr>
<tr><td>司法四等考試_執達員類科</td></tr>
<tr><td>民法概要</td><td><a href="'''+BASE+'''Q">試題</a></td><td><a href="'''+BASE+'''S">答案</a></td></tr>
<tr><td>國文</td><td><a href="/exam/wHandExamQandA_File.ashx?c=205&amp;code=114120&amp;q=1&amp;s=0410&amp;t=Q">試題</a></td></tr>
</table></body></html>'''


class MoexFallbackTests(unittest.TestCase):
    def test_known_example_matches_official_link_format(self):
        q=official_document_url(BASE+'Q',exam_code='114120')
        self.assertEqual(q[1], 'Q')
        self.assertEqual(q[2], ('201','1','0405'))

    def test_rejects_untrusted_links(self):
        bad=['https://wwwq.moex.gov.tw.evil.com/exam/wHandExamQandA_File.ashx?'+BASE.split('?')[1],
             'javascript:alert(1)',BASE.replace('code=114120','code=114111')+'Q',
             BASE.replace('t=','t=X')+'Q',BASE.replace('https:', 'http:')+'Q',
             BASE.replace('c=201', 'c=201%26evil=1')+'Q',
             BASE.replace('wwwq.moex.gov.tw','wwwq.moex.gov.tw@evil.com')+'Q']
        for url in bad:
            self.assertIsNone(official_document_url(url,exam_code='114120'),url)

    def test_official_exam_wide_answer_pdf_is_not_an_invalid_subject_link(self):
        global_url = 'https://wwwq.moex.gov.tw/exam/wHandExamQandA_File.ashx?code=114120&t=A'
        self.assertEqual(official_aggregate_answer_url(global_url, exam_code='114120'), global_url)
        self.assertIsNone(official_document_url(global_url, exam_code='114120'))
        page = H.replace('<table>', '<a href="/exam/wHandExamQandA_File.ashx?code=114120&amp;t=A">本考試所有測驗題標準答案</a><table>')
        data = create_fallback_index(page.encode(), min_items=3)
        self.assertEqual(data['summary']['index_papers'], 3)
        self.assertEqual(data['source']['exam_wide_answer_url'], global_url)
        self.assertEqual(data['items'], create_fallback_index(H.encode(), min_items=3)['items'])

    def test_malformed_exam_wide_answer_pdf_still_fails_closed(self):
        global_link = '/exam/wHandExamQandA_File.ashx?code=114120&amp;t=A'
        variants = [
            global_link + '&amp;unexpected=1',
            global_link.replace('114120', '114119'),
            global_link.replace('t=A', 't=X'),
            global_link.replace('t=A', 't=A&amp;t=A'),
            'https://evil.com/exam/wHandExamQandA_File.ashx?code=114120&amp;t=A',
        ]
        for link in variants:
            self.assertEqual(official_aggregate_answer_url(html.unescape(link), exam_code='114120'), '')
            page = H.replace('<table>', '<a href="' + link + '">本考試所有測驗題標準答案</a><table>')
            with self.assertRaises(SourceFailure):
                create_fallback_index(page.encode(), min_items=3)

    def test_approved_source_and_deduplicated_groups(self):
        result=create_fallback_index(H.encode(),min_items=3)
        self.assertEqual(result['status'],'fallback_official_page_links_unverified')
        self.assertEqual(result['summary']['index_papers'],3)
        x=next(i for i in result['items'] if i['subject']=='民法概要')
        self.assertEqual(len(x['groups']),2)
        self.assertEqual(x['question_url'],BASE+'Q')
        self.assertEqual(x['answer_url'],BASE+'S')
        self.assertEqual(x['answer_verification'],'not_verified')
        self.assertIn('待原卷核對',x['question_type'])

    def test_mixed_field_and_correction_kept_separate(self):
        result=create_fallback_index(H.encode(),min_items=3)
        x=next(i for i in result['items'] if '法學知識' in i['subject'])
        self.assertEqual(x['classification'],'mixed')
        self.assertIn('憲法',x['focus_subjects'])
        self.assertTrue(x['answer_url'].endswith('t=S'))
        self.assertTrue(x['answer_correction_url'].endswith('t=M'))
        self.assertEqual(x['answer_verification'],'not_verified')

    def test_no_official_answer_inferred_from_question(self):
        r=create_fallback_index(H.encode(),min_items=3)
        x=next(i for i in r['items'] if i['subject']=='刑法概要')
        self.assertEqual(x['answer_url'],'')
        self.assertFalse('correctIndex' in json.dumps(r))

    def test_rejects_empty_and_unexpected_year(self):
        for b in (b'',b'<html>error</html>',H.replace('114年','113年').encode()):
            with self.assertRaises(SourceFailure): create_fallback_index(b,min_items=3)

    def test_rejects_hostile_official_file_in_page(self):
        poisoned=H.replace(BASE+'Q', 'https://evil.com/wHandExamQandA_File.ashx?c=201&code=114120&q=1&s=0405&t=Q')
        with self.assertRaises(SourceFailure): create_fallback_index(poisoned.encode(),min_items=3)

    def test_retry_is_deterministic(self):
        a=create_fallback_index(H.encode(),min_items=3)
        b=create_fallback_index(H.encode(),min_items=3)
        self.assertEqual(a,b)
        self.assertNotIn('draft',json.dumps(a))

    def test_primary_fail_secondary_success_primary_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'primary.json';f=Path(tmp)/'fallback.json'
            p.write_text('PRIMARY-OLD');f.write_text('BACKUP-OLD')
            def primary_fails(): raise SourceFailure('connection reset by peer')
            result=sync(primary=p,fallback=f,fetch_primary=primary_fails,fetch_secondary=lambda c:H.encode())
            self.assertEqual(result['mode'],'separate_individual_exam_fallback')
            self.assertEqual(p.read_text(),'PRIMARY-OLD')
            self.assertEqual(json.loads(f.read_text())['summary']['index_papers'],3)

    def test_both_fail_old_snapshots_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'primary.json';f=Path(tmp)/'fallback.json'
            p.write_text('PRIMARY-OLD');f.write_text('BACKUP-OLD')
            with self.assertRaises(SourceFailure):
                sync(primary=p,fallback=f,fetch_primary=lambda: b'html error',fetch_secondary=lambda c: b'<html>Error</html>')
            self.assertEqual(p.read_text(),'PRIMARY-OLD')
            self.assertEqual(f.read_text(),'BACKUP-OLD')

    def test_official_page_fallback_command_writes_new_separate_file(self):
        from moex_page_fallback import main
        with tempfile.TemporaryDirectory() as tmp:
            f=Path(tmp)/'official.html';out=Path(tmp)/'fallback.json'
            f.write_text(H)
            self.assertEqual(main(['--input-html',str(f),'--min-items','3','--output',str(out)]),0)
            self.assertEqual(json.loads(out.read_text())['source']['method'],'official_exam_page_html')


if __name__=='__main__':unittest.main()
