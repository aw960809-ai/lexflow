import csv
import io
import json
import tempfile
import unittest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from moex_index import (create_index, decode_csv, official_url, subjects_of,
                        SourceFailure, write_atomic, main)

HEADER = ['考試年度', '考試代碼', '考試名稱', '等級代碼', '等級分類', '考試及等別', '類科代碼', '類科組別',
          '節次', '科目全名', '試題型態', '試題網址', '測驗式試題答案網址', '備註']


def entry(subject='民法', year='114', question='https://wwwq.moex.gov.tw/exam/question1.pdf',
          answer='https://wwwq.moex.gov.tw/exam/answer1.pdf', group='法制', kind='測試題'):
    return [year, 'EX01', '高考三級', '03', '三等', '高考', '001', group,
            '1', subject, kind, question, answer, '']


def blob(rows, encoding='utf-8-sig'):
    f = io.StringIO(newline='')
    writer = csv.writer(f)
    writer.writerow(HEADER)
    writer.writerows(rows)
    return f.getvalue().encode(encoding)


class MoexIndexTests(unittest.TestCase):
    def test_three_core_fields_and_metadata(self):
        r = create_index(blob([entry('民法'), entry('刑法'), entry('中華民國憲法'),
                               entry('應用統計學')]), min_rows=1)
        self.assertEqual(r['summary']['index_papers'], 3)
        self.assertEqual(r['summary']['subject_papers'], {'民法': 1, '刑法': 1, '憲法': 1})
        self.assertTrue(all(x['answer_verification'] == 'not_verified' for x in r['items']))
        self.assertTrue(all(x['source'].startswith('MOEX ') for x in r['items']))

    def test_reuses_same_paper_across_groups(self):
        r = create_index(blob([entry(group='法制'), entry(group='法律廉政')]), min_rows=1)
        self.assertEqual(r['summary']['index_papers'], 1)
        self.assertEqual(r['items'][0]['groups'], ['法制', '法律廉政'])

    def test_mixed_exam_not_mislabeled_as_pure(self):
        r = create_index(blob([entry('綜合法學（一）（憲法、行政法、刑法）')]), min_rows=1)
        self.assertEqual(r['items'][0]['classification'], 'mixed')
        self.assertEqual(r['items'][0]['focus_subjects'], ['刑法', '憲法'])

    def test_generic_law_exam_requires_review(self):
        r = create_index(blob([entry('法學知識（法學緒論）')]), min_rows=1)
        self.assertEqual(r['items'][0]['classification'], 'needs_classification')
        self.assertEqual(r['items'][0]['focus_subjects'], [])

    def test_embedded_law_names_do_not_misclassify_subjects(self):
        # "行刑法" contains "刑法"; "國民法官法" contains "民法".
        for unrelated in ('監獄行刑法概要', '監獄行刑法與羈押法', '國民法官法'):
            self.assertIsNone(subjects_of(unrelated), unrelated)
        self.assertEqual(subjects_of('刑法與監獄行刑法'), (['刑法'], 'mixed'))
        self.assertEqual(subjects_of('國民法官法與民法'), (['民法'], 'mixed'))
        self.assertEqual(subjects_of('刑法與少年事件處理法'), (['刑法'], 'mixed'))

    def test_substring_collisions_excluded_from_document_index(self):
        rows = [entry('民法'), entry('刑法'), entry('監獄行刑法概要'),
                entry('監獄行刑法與羈押法'), entry('國民法官法'),
                entry('刑法與少年事件處理法')]
        out = create_index(blob(rows), min_rows=1)
        self.assertEqual(out['summary']['index_papers'], 3)
        subjects = {i['subject']: i for i in out['items']}
        self.assertNotIn('監獄行刑法概要', subjects)
        self.assertNotIn('國民法官法', subjects)
        self.assertEqual(subjects['刑法與少年事件處理法']['classification'], 'mixed')

    def test_no_arbitrary_nonlaw_rows(self):
        with self.assertRaises(SourceFailure):
            create_index(blob([entry('線性代數')]), min_rows=1)

    def test_non_official_hosts_and_javascript_are_rejected(self):
        for url in ['javascript:alert(1)', 'https://moex.gov.tw.evil.net/a.pdf',
                    'https://wwwc.moex.gov.tw@evil.com/a.pdf', 'ftp://wwwq.moex.gov.tw/x.pdf',
                    'https://wwwc.moex.gov.tw:444/x.pdf']:
            self.assertEqual(official_url(url), '')
        self.assertEqual(official_url('https://wwwq.moex.gov.tw/q.pdf'), 'https://wwwq.moex.gov.tw/q.pdf')

    def test_invalid_official_link_fails_closed(self):
        with self.assertRaises(SourceFailure):
            create_index(blob([entry(question='https://fake.moex.gov.tw.evil.com/x.pdf')]), min_rows=1)

    def test_missing_answer_is_retained_but_not_verified(self):
        r = create_index(blob([entry(answer='', kind='申論題')]), min_rows=1)
        self.assertEqual(r['items'][0]['answer_url'], '')
        self.assertEqual(r['items'][0]['answer_verification'], 'not_verified')

    def test_encoding_cp950(self):
        r = create_index(blob([entry('中華民國憲法')], encoding='cp950'), min_rows=1)
        self.assertEqual(r['items'][0]['focus_subjects'], ['憲法'])

    def test_missing_headers_rejected(self):
        with self.assertRaises(SourceFailure):
            create_index('年度,科目\n114,民法'.encode(), min_rows=1)

    def test_html_response_rejected(self):
        with self.assertRaises(SourceFailure):
            decode_csv(b'<html>unavailable</html>')

    def test_minimum_row_count_rejects_partial_download(self):
        with self.assertRaises(SourceFailure):
            create_index(blob([entry()]), min_rows=30)

    def test_changes_do_not_rewrite_unchanged_output(self):
        r = create_index(blob([entry()]), min_rows=1)
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory) / 'index.json'
            self.assertTrue(write_atomic(p, r))
            initial = p.read_bytes()
            self.assertFalse(write_atomic(p, r))
            self.assertEqual(p.read_bytes(), initial)
            self.assertEqual(json.loads(initial)['status'], 'index_only_unverified_answers')

    def test_failed_replacement_keeps_previous_index(self):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory) / 'index.json'
            p.write_text('ORIGINAL', encoding='utf-8')
            q = Path(directory) / 'bad.csv'
            q.write_text('<html>server error</html>', encoding='utf-8')
            rc = main(['--input', str(q), '--output', str(p)])
            self.assertEqual(rc, 2)
            self.assertEqual(p.read_text(encoding='utf-8'), 'ORIGINAL')

    def test_no_personal_backup_files_in_index(self):
        r = create_index(blob([entry()]), min_rows=1)
        self.assertNotIn('draft', json.dumps(r))
        self.assertNotIn('attempts', json.dumps(r))


if __name__ == '__main__':
    unittest.main()
