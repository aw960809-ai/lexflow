"""Offline contract tests for multi-cohort expansion over the existing LexFlow engine.

Source records are synthetic (not published exam questions or official answers).
All derived candidates remain unverified, unscored and unpublished.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
sys.path.insert(0,str(ROOT/'tests'))
import moex_coverage_campaign as coverage
import moex_review_series as series
from moex_catalog_bridge import UnsafeSource
from test_moex_review_series import make_catalog, dummy_run


class CoverageCampaignTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base=Path(temp.name)
        self.catalog=self.base/'official-14-columns.csv'
        make_catalog(self.catalog,n=12)
        self.root=self.base/'public-only-review'

    def prepare(self):
        return coverage.prepare_campaign(self.catalog,self.root,
            year_groups='113;114',batches=1,papers_per_batch=3,documents_per_batch=8)

    def test_year_groups_reject_overlap_bad_tokens_and_excess(self):
        self.assertEqual(coverage.parse_groups('101-103;104,105;115'),
                         [['101','102','103'],['104','105'],['115']])
        for text in ['', '101-103;103-105', '115-112','101x','101;;103',
                     '101-200','101,101','101-102-103', '115;' ]:
            with self.subTest(text=text),self.assertRaises(UnsafeSource):
                coverage.parse_groups(text)

    def test_preparation_is_idempotent_uses_original_whole_papers_and_no_pdf(self):
        src=self.catalog.read_bytes()
        first=self.prepare()
        self.assertEqual(first['status'],'PLANNED_ONLY_NO_PDF_DOWNLOAD')
        self.assertFalse(first['scoring_enabled'])
        self.assertEqual(first['cohorts'],2)
        self.assertEqual(first['papers'],6)
        file=Path(first['campaign_path']); content=file.read_bytes()
        second=self.prepare()
        self.assertEqual(file.read_bytes(),content)
        self.assertEqual(second['campaign_path'],first['campaign_path'])
        self.assertEqual(self.catalog.read_bytes(),src)
        root,manifest,details,papers=coverage.read_campaign(file,catalog=self.catalog)
        self.assertEqual(len(details),2)
        self.assertEqual(len({x['paper_id'] for x in papers}),6)
        self.assertEqual({p['year_roc'] for p in papers},{'113','114'})
        self.assertTrue(all(p['source_file_sha256']==manifest['catalog_sha256'] for p in papers))
        self.assertFalse((self.root/'official-review'/'official_pdf_cache').exists())

    def test_campaign_manifest_mutation_rejected_and_source_unchanged(self):
        info=self.prepare()
        source_bytes=self.catalog.read_bytes()
        p=Path(info['campaign_path']);raw=p.read_bytes()
        blob=json.loads(raw)
        blob['publication_allowed']=True
        p.write_text(json.dumps(blob),encoding='utf-8')
        with self.assertRaises(UnsafeSource):coverage.read_campaign(p,catalog=self.catalog)
        with self.assertRaises(UnsafeSource):self.prepare()
        self.assertEqual(self.catalog.read_bytes(),source_bytes)

    def test_campaign_cohort_metadata_tampering_is_detected(self):
        file=Path(self.prepare()['campaign_path'])
        body=json.loads(file.read_text('utf-8'))
        body['cohorts'][0]['official_exam_codes']=['000000']
        file.write_text(json.dumps(body),encoding='utf-8')
        with self.assertRaises(UnsafeSource):
            coverage.read_campaign(file,catalog=self.catalog)

    def test_campaign_does_not_accept_different_catalog_fingerprint(self):
        p=Path(self.prepare()['campaign_path'])
        self.catalog.write_bytes(self.catalog.read_bytes()+b'\n')
        with self.assertRaises(UnsafeSource):coverage.read_campaign(p,catalog=self.catalog)

    def test_offline_no_reports_yields_zero_downloads_never_fake_success_rate(self):
        file=Path(self.prepare()['campaign_path'])
        s=coverage.summarize_campaign(file,catalog=self.catalog)
        self.assertEqual(s['planned_whole_papers'],6)
        self.assertEqual(s['Q_fulltext_SHA_matched'],0)
        report=json.loads(Path(s['source_quality_report']).read_text('utf-8'))
        self.assertIsNone(report['fulltext_completeness_rate'])
        self.assertFalse(report['official_total_question_count_confirmed'])
        self.assertFalse(report['human_answers_verified'])
        self.assertEqual(report['PDF_documents_reported'],0)
        self.assertEqual(report['positioned_answer_pairs_UNVERIFIED'],0)
        self.assertEqual(report['cohorts'][0]['source_states'],{'no_saved_review':3})
        with Path(s['per_paper_CSV']).open(encoding='utf-8-sig',newline='') as f:
            rows=list(csv.DictReader(f))
        self.assertEqual(len(rows),6)
        self.assertTrue(all(row['scoring_enabled']=='False' for row in rows))
        self.assertTrue(all(row['official_total_question_count_confirmed']=='False' for row in rows))
        self.assertEqual(s,coverage.summarize_campaign(file,catalog=self.catalog))

    def test_resume_one_cohort_delegates_to_existing_series_no_parallel_downloader(self):
        manifest=Path(self.prepare()['campaign_path'])
        with patch.object(series,'run_plan',side_effect=dummy_run) as mocked:
            one=coverage.run_one(manifest,catalog=self.catalog,cohort_index=1,
                                 max_batches=1,offline_only=True)
        self.assertEqual(mocked.call_count,1)
        self.assertTrue(mocked.call_args.kwargs['offline_only'])
        self.assertEqual(one['batches_completed_of_cohort'],1)
        self.assertEqual(one['batches_total_for_cohort'],1)
        self.assertFalse(one['official_PDF_network_mode'])
        audit=coverage.summarize_campaign(manifest,catalog=self.catalog)
        self.assertEqual(audit['Q_fulltext_SHA_matched'],3)
        report=json.loads(Path(audit['source_quality_report']).read_text('utf-8'))
        self.assertEqual(report['cohorts'][0]['source_Q_fulltext_SHA_matched'],3)
        self.assertEqual(report['cohorts'][1]['source_Q_fulltext_SHA_matched'],0)
        self.assertFalse(report['scoring_enabled'])
        with patch.object(series,'run_plan',side_effect=AssertionError('repeated downloads')):
            again=coverage.run_one(manifest,catalog=self.catalog,cohort_index=1,
                                   max_batches=1,offline_only=True)
        self.assertEqual(again['batches_completed_of_cohort'],1)
        self.assertEqual(again['status'],'BOUNDED_BATCHES_REVIEWED_NOT_SCORED')

    def test_run_requires_explicit_bounded_mode_and_cohort(self):
        campaign=Path(self.prepare()['campaign_path'])
        for choices in [{}, {'download_documents':True,'offline_only':True}]:
            with self.assertRaises(UnsafeSource):
                coverage.run_one(campaign,catalog=self.catalog,cohort_index=1,**choices)
        with self.assertRaises(UnsafeSource):
            coverage.run_one(campaign,catalog=self.catalog,cohort_index=3,offline_only=True)
        with self.assertRaises(UnsafeSource):
            coverage.run_one(campaign,catalog=self.catalog,cohort_index=1,max_batches=4,offline_only=True)

    def test_create_only_prevents_overwrite_and_link_redirection(self):
        path=self.base/'new'/'result.json'
        self.assertTrue(coverage.create_bytes_only(path,b'first'))
        self.assertFalse(coverage.create_bytes_only(path,b'first'))
        with self.assertRaises(UnsafeSource):coverage.create_bytes_only(path,b'second')
        link=self.base/'new'/'symlink.json'
        link.symlink_to(path)
        with self.assertRaises(UnsafeSource):coverage.create_bytes_only(link,b'first')
        self.assertEqual(path.read_bytes(),b'first')

    def test_malicious_audit_must_never_produce_comparative_scoring_report(self):
        manifest=Path(self.prepare()['campaign_path'])
        root,m,details,papers=coverage.read_campaign(manifest)
        home=details[0][0]
        # Simulates a plugin claiming that an unreviewed source is scored.
        auditfile=home/'audits'/'forged.json'
        auditfile.parent.mkdir(parents=True,exist_ok=True)
        auditfile.write_text(json.dumps({'schema':series.QUALITY_SCHEMA,
            'catalog_sha256':m['catalog_sha256'],'scoring_enabled':True,
            'publication_allowed':False,'human_answers_verified':False,
            'official_total_question_count_confirmed':False,'fulltext_completeness_rate':None,
            'papers':[]}),encoding='utf-8')
        with patch.object(series,'audit',return_value={'audit_path':str(auditfile)}):
            with self.assertRaises(UnsafeSource):
                coverage.summarize_campaign(manifest,catalog=self.catalog)
        self.assertFalse((root/'campaigns'/'reports').exists())

if __name__=='__main__':unittest.main()
