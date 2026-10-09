#!/usr/bin/env python3
"""LexFlow: full official catalog -> immutable whole-paper bounded source reviews.

Offline by default. Uses the EXISTING V0.3 moex_batch_engine for network, PDF
identity checks and conservative MCQ candidate extraction. Never scores or
publishes. Works on any official exam subject / year / question type.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import tempfile
import time
from collections import Counter
from urllib.parse import parse_qs, urlsplit

SCHEMA = 'lexflow.moex.whole-paper-plan.v1'
REVIEW_SCHEMA = 'lexflow.moex.whole-paper-review.v1'
ALLOWED_KINDS = ('測驗題', '申論題', '混合題', '實地考試')
MAX_BATCH = 12
MAX_DOCS = 24
ALLOWED_HOST = 'wwwq.moex.gov.tw'
ENDPOINT = '/exam/whandexamqanda_file.ashx'
MAX_TEXT_CHARS = 250_000
METADATA_COLUMNS = [
    '考試年度', '考試代碼', '考試名稱', '等級代碼', '等級分類', '考試及等別',
    '類科代碼', '類科組別', '節次', '科目全名', '試題型態',
    '試題網址', '測驗式試題答案網址', '備註',
]
MAX_CATALOG_ROWS = 150_000
LEGAL_CLASSES = ('名稱明確法律科目', '綜合／基礎法學科目',
                 '跨領域涉法候選（待複核）', '其他／未標記')
# This is ONLY an opt-in discovery filter on the official subject title,
# not a replacement for the exam's published subject/classification.
GENERAL_TITLE = re.compile(r'綜合法學|綜合法政|法學知識|法學大意|法學緒論|法律常識|法律概論|基礎能力測驗')
DIRECT_TITLE = re.compile(
    r'民法|刑法|憲法|行政法|訴訟法|國際法|國際公法|國際私法|法規|法律|法制|法令|'
    r'強制執行|非訟事件|家事事件|公證|信託|票據|公司法|商事法|證券交易|保險法|'
    r'土地法|稅法|著作權|專利|商標|公平交易|警察法|監獄行刑|(?<!漁)法學|'
    r'海商法|稅務法|懲治走私|國籍法|移民法|海洋法|勞動法|智慧財產|稅捐稽徵|行政救濟')
CONTEXT_TITLE = re.compile(r'犯罪學|犯罪偵查|國境執法|刑事|司法|檢察|監所|監獄|'
                           r'勞工行政|土地登記|不動產|稅務|入出國|移民|戶政|法律倫理|監察|裁判|法務')
DOMAIN_TERMS = [
    ('民事訴訟法','民事訴訟法'),('刑事訴訟法','刑事訴訟法'),('行政訴訟法','行政訴訟法'),
    ('民法','民法'),('刑法','刑法'),('憲法','憲法'),('行政法','行政法'),
    ('國際公法','國際公法'),('國際私法','國際私法'),('商事法','商事法'),('公司法','公司法'),
    ('證券交易法','證券交易法'),('票據法','票據法'),('保險法','保險法'),('強制執行法','強制執行法'),
    ('非訟事件','非訟事件'),('家事事件','家事事件'),('信託法','信託法'),('公證法','公證法'),
    ('智慧財產','智慧財產法'),('著作權','著作權法'),('專利','專利法相關'),('商標','商標法相關'),
    ('土地法','土地法'),('公平交易法','公平交易法'),('稅務法規','稅務法規'),('稅法','稅法'),
    ('移民法','移民法'),('警察法','警察法'),('勞動法','勞動法'),('海商法','海商法'),
    ('監獄行刑法','監獄行刑法'),('關稅法','關稅法'),('國際法','國際法')
]

class UnsafeSource(ValueError):
    pass


def digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def classify_official_title(subject: str) -> tuple[str, str]:
    """Conservative TITLE-only discovery. Never renames or splits official subjects.

    A general/composite subject such as 綜合法政知識與英文 stays a SINGLE
    official subject; optional explicit title hints are *not* per-item topics.
    """
    if not isinstance(subject, str) or not subject.strip():
        raise UnsafeSource('official subject title is missing')
    base = re.split(r'[（(]', subject, maxsplit=1)[0]
    if base.startswith(('漁法學','漁具漁法學')):
        return '其他／未標記', ''
    if GENERAL_TITLE.search(subject):
        label = '綜合／基礎法學科目'
    elif DIRECT_TITLE.search(base):
        label = '名稱明確法律科目'
    elif DIRECT_TITLE.search(subject) or CONTEXT_TITLE.search(subject):
        label = '跨領域涉法候選（待複核）'
    else:
        label = '其他／未標記'
    # Longer official act names must not leak short false-positive field tags:
    # 國民法官法 is NOT 民法; 監獄行刑法 is NOT 刑法. If the short act is named
    # separately elsewhere in the title, it will still be detected.
    unambiguous_focus = subject.replace('國民法官法','').replace('監獄行刑法','')
    tags = list(dict.fromkeys(v for needle,v in DOMAIN_TERMS
                              if needle in (unambiguous_focus if needle in ('民法','刑法') else subject)))
    if '國際法' in tags and ('國際公法' in tags or '國際私法' in tags):
        tags.remove('國際法')
    return label, '；'.join(tags)


def normalize_catalog_classification(row: dict, source_class: str | None = None) -> dict:
    """Use the same rule for original 14-column CSV, enriched CSV and SQLite.

    Earlier source labels remain visible as evidence if classification versions
    disagree; a disagreement is isolated before PDF download, never hidden.
    """
    found, tags = classify_official_title(row['official_subject'])
    previous = source_class or row.get('legal_candidate_class') or ''
    row['catalog_classification_conflict'] = (
        bool(previous and previous not in ('未分類（原始 CSV）', found))
    )
    row['legacy_title_classification'] = previous
    row['legal_candidate_class'] = found
    row['title_domain_tags'] = tags
    return row


def atomic_bytes(path: Path, data: bytes) -> None:
    """No truncation on failure; caller alone decides overwrite policy."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix='.' + path.name + '.', suffix='.tmp')
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def save_json(path: Path, obj: dict) -> None:
    atomic_bytes(path, (json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=True) + '\n').encode('utf-8'))


def source_ref(url: str, role: str) -> tuple[str, str, str, str]:
    """MOEX Q/S/M URL identity. Never follow arbitrary URLs or blind redirects."""
    if not isinstance(url, str) or not 1 <= len(url) <= 2048 or role not in ('Q','S','M'):
        raise UnsafeSource('unknown source role or invalid URL')
    try:
        parsed = urlsplit(url)
        if parsed.scheme != 'https' or parsed.hostname != ALLOWED_HOST or parsed.port not in (None,443) or parsed.username or parsed.password or parsed.fragment or parsed.path.lower() != ENDPOINT:
            raise UnsafeSource('only the approved official HTTPS PDF endpoint is allowed')
        parts = parse_qs(parsed.query, strict_parsing=True, keep_blank_values=True)
        if set(parts) != {'t','code','c','s','q'} or any(len(v) != 1 for v in parts.values()) or parts['t'][0] != role:
            raise UnsafeSource('unexpected Q/S/M URL parameters or role')
        identity = tuple(parts[x][0] for x in ('code','c','s','q'))
        if not all(re.fullmatch(r'[0-9]{1,8}', s) for s in identity) or not 5 <= len(identity[0]) <= 8:
            raise UnsafeSource('invalid official PDF identity')
        return identity
    except ValueError as e:
        if isinstance(e, UnsafeSource):
            raise
        raise UnsafeSource('malformed source URL') from e


def catalog_records(path: Path):
    if path.suffix.lower() == '.sqlite':
        # Read only, even when the source file belongs to the user's full catalog pack.
        db = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)
        db.row_factory = sqlite3.Row
        try:
            columns = {r['name'] for r in db.execute('PRAGMA table_info(papers)')}
            required = {'source_row','paper_id','official_type','official_subject','question_url','year_roc','legal_candidate_class'}
            if not required.issubset(columns):
                raise UnsafeSource('not a LexFlow official_catalog.sqlite')
            cur = db.execute('SELECT * FROM papers ORDER BY source_row ASC')
            for row in cur:
                raw = dict(row)
                record = {
                    'source_row': int(raw['source_row']), 'paper_id':raw['paper_id'],
                    'year_roc':raw['year_roc'], 'exam_code':raw['exam_code'],
                    'exam_name':raw['exam_name'], 'grade_code':raw['grade_code'],
                    'grade_label':raw['grade_label'], 'exam_grade':raw['exam_grade'],
                    'class_code':raw['class_code'], 'class_group':raw['class_group'],
                    'session_code':raw['session_code'], 'official_subject':raw['official_subject'],
                    'official_type':raw['official_type'], 'question_url':raw['question_url'],
                    'answer_url':raw['official_answer_url'] or '',
                    'official_note':raw['official_note'], 'legal_candidate_class':raw['legal_candidate_class'],
                    'title_domain_tags':raw.get('title_domain_tags') or '',
                }
                yield normalize_catalog_classification(record)
        finally:
            db.close()
    elif path.suffix.lower() == '.csv':
        with path.open(encoding='utf-8-sig', newline='') as f:
            reader = csv.DictReader(f)
            if not set(METADATA_COLUMNS).issubset(reader.fieldnames or []):
                raise UnsafeSource('CSV missing official 14 columns')
            for i, row in enumerate(reader, 1):
                if i > MAX_CATALOG_ROWS:
                    raise UnsafeSource('catalog unexpectedly exceeded maximum row count')
                if None in row or any(row.get(k) is None for k in METADATA_COLUMNS):
                    raise UnsafeSource(f'malformed catalog row {i}')
                url=row['試題網址']
                # The full original 14-column official CSV and the enriched CSV
                # both work; the original can be 67,026+ rows.
                record = {
                    'source_row':int(row.get('原始資料序號') or i),
                    'paper_id':row.get('穩定試卷ID') or 'moex-'+digest(url.encode())[:24],
                    'year_roc':row['考試年度'], 'exam_code':row['考試代碼'],
                    'exam_name':row['考試名稱'], 'grade_code':row['等級代碼'],
                    'grade_label':row['等級分類'], 'exam_grade':row['考試及等別'],
                    'class_code':row['類科代碼'], 'class_group':row['類科組別'],
                    'session_code':row['節次'], 'official_subject':row['科目全名'],
                    'official_type':row['試題型態'], 'question_url':url,
                    'answer_url':row['測驗式試題答案網址'],
                    'official_note':row['備註'],
                    'legal_candidate_class':row.get('法律相關候選狀態') or '未分類（原始 CSV）',
                    'title_domain_tags':row.get('官方標題可見領域標籤') or '',
                }
                yield normalize_catalog_classification(record)
    else:
        raise UnsafeSource('catalog must be an official CSV or previous SQLite')


def is_candidate(row: dict) -> bool:
    """Only an optimization, NOT a claim that other papers are not about law."""
    return row['legal_candidate_class'] in LEGAL_CLASSES[:3]


def appearance(row: dict) -> dict:
    """An official row may reference a shared paper; never erase its class."""
    return {k:row[k] for k in (
        'source_row','exam_code','exam_name','year_roc','grade_code','grade_label',
        'exam_grade','class_code','class_group','session_code','official_subject','official_type')}


def _source_key(row: dict) -> tuple:
    """Canonical URL identity, unaffected by query-parameter ordering."""
    try:
        return ('Q', *source_ref(row['question_url'], 'Q'))
    except (UnsafeSource, TypeError, KeyError, ValueError):
        # Keep the damaged row visible for isolation, never merge it into a
        # healthy paper or drop it without a trace.
        return ('invalid_source_row', row['source_row'])


def unique_papers(rows) -> tuple[list[dict], int, int]:
    """Preserve EVERY source-row association while deduping known Q identities.

    Shared URL identity is proof of the same *source reference*, not proof
    that two distinct URLs serve the same PDF bytes. Different URLs can only
    be content-deduplicated after separate SHA-256 checks of their PDFs.
    """
    seen = {}
    duplicate_rows = 0
    conflicted_sources = 0
    for row in rows:
        key = _source_key(row)
        prior = seen.get(key)
        if prior is None:
            prior = dict(row)
            prior['source_appearances'] = [appearance(row)]
            prior['any_title_candidate'] = is_candidate(row)
            prior['source_metadata_conflict'] = bool(row.get('catalog_classification_conflict'))
            seen[key] = prior
            continue
        duplicate_rows += 1
        prior['source_appearances'].append(appearance(row))
        prior['any_title_candidate'] |= is_candidate(row)
        # A label-only change or source-answer change cannot be silently
        # merged into the older document, even when its Q URL is shared.
        mismatch = any(prior.get(k) != row.get(k) for k in (
            'exam_code','exam_name','year_roc','grade_code','class_code',
            'session_code','official_subject','official_type','answer_url'))
        if mismatch and not prior['source_metadata_conflict']:
            conflicted_sources += 1
        prior['source_metadata_conflict'] |= mismatch or bool(row.get('catalog_classification_conflict'))
    return list(seen.values()), duplicate_rows, conflicted_sources


def inventory_catalog(catalog: Path) -> dict:
    """Offline audit of ALL original official metadata, including non-law rows.

    No network request, no PDF, no user data. This report is intentionally
    compact; the unchanged CSV/SQLite remains the full 1-row-per-record index.
    """
    total = 0
    year_counts, kind_counts, title_classes = Counter(), Counter(), Counter()
    unique_exams, unique_subjects, unique_class_groups = set(), set(), set()
    isolated = Counter(); examples = []
    def source_rows():
        nonlocal total
        for row in catalog_records(catalog):
            total += 1
            if total > MAX_CATALOG_ROWS:
                raise UnsafeSource('unexpectedly many catalog rows')
            year_counts[row['year_roc']] += 1
            kind_counts[row['official_type']] += 1
            title_classes[row['legal_candidate_class']] += 1
            unique_exams.add(row['exam_code'])
            unique_subjects.add(row['official_subject'])
            unique_class_groups.add((row['exam_code'], row['class_code'], row['class_group']))
            reason = None
            if row.get('catalog_classification_conflict'):
                reason = 'prior_title_classification_disagrees'
            else:
                try:
                    validate_paper(row)
                except (UnsafeSource, KeyError, ValueError, TypeError):
                    reason = 'source_identity_or_type_invalid'
            if reason:
                isolated[reason] += 1
                if len(examples) < 12:
                    examples.append({'source_row':row['source_row'],
                                     'reason':reason,'paper_id':row['paper_id']})
            yield row
    documents, duplicates, conflicts = unique_papers(source_rows())
    if not total:
        raise UnsafeSource('no official source records')
    if conflicts:
        isolated['source_metadata_conflicting_for_same_Q'] += conflicts
    return {
        'schema':'lexflow.moex.catalog-inventory.v1',
        'status':'full_official_catalog_metadata_only_UNSCORED',
        'source_catalog_file':catalog.name,
        'catalog_sha256':sha256_file(catalog),
        'source_rows':total,
        'unique_official_Q_source_identities':len(documents),
        'duplicate_Q_reference_rows':duplicates,
        'shared_source_reference_identity_is_not_PDF_content_equivalence':True,
        'original_record_rows_preserved_in_source_file':True,
        'year_counts':dict(sorted(year_counts.items())),
        'type_counts':dict(sorted(kind_counts.items())),
        'candidate_class_counts':dict(sorted(title_classes.items())),
        'law_related_title_candidate_rows':sum(title_classes[x] for x in LEGAL_CLASSES[:3]),
        'official_exam_codes':len(unique_exams),
        'official_subject_names':len(unique_subjects),
        'official_class_group_references':len(unique_class_groups),
        'metadata_isolation_reasons':dict(sorted(isolated.items())),
        'isolated_examples':examples,
        'source_PDFs_downloaded':0,
        'human_content_and_answers_verified':False,
        'publication_allowed':False,'scoring_enabled':False,
        'private_attempts_included':False,
    }


def pick_rows(rows: list[dict], *, max_papers: int, strategy: str='coverage') -> list[dict]:
    if not 1 <= max_papers <= MAX_BATCH:
        raise UnsafeSource('limit must be between 1 and 12 per run')
    if strategy == 'sequential':
        return rows[:max_papers]
    if strategy != 'coverage':
        raise UnsafeSource('unknown selection strategy')
    # Strata by official format + year; reuse the source's category, never
    # infer a question format or legal topic from unverified PDF text.
    buckets: dict[tuple, list] = {}
    for row in rows:
        buckets.setdefault((row['official_type'],row['year_roc']),[]).append(row)
    ranked = sorted(buckets, key=lambda k:(ALLOWED_KINDS.index(k[0]) if k[0] in ALLOWED_KINDS else 9, k[1]), reverse=False)
    # Start with most recent year within each official type, then another year.
    ranked = sorted(ranked, key=lambda k:(ALLOWED_KINDS.index(k[0]) if k[0] in ALLOWED_KINDS else 9, -int(k[1])))
    picked, ids, exam_codes, subjects, years = [], set(), set(), set(), set()
    def add(row):
        if row['paper_id'] in ids or len(picked) >= max_papers:return False
        ids.add(row['paper_id']); picked.append(row); exam_codes.add(row['exam_code']);subjects.add(row['official_subject']);years.add(row['year_roc']);return True
    # Round robin prevents one high-volume year or subject dominating.
    for turn in range(max_papers):
        options=[]
        for n,key in enumerate(ranked):
            for row in buckets[key]:
                if row['paper_id'] in ids:continue
                options.append((
                  -(row['exam_code'] not in exam_codes),
                  -(row['official_subject'] not in subjects),
                  -(row['year_roc'] not in years),
                  sum(r['official_type']==key[0] for r in picked),
                  n, row['source_row'], row
                ))
                break
        if not options:break
        add(min(options, key=lambda x:x[:-1])[-1])
    return picked


def paper_metadata(row: dict) -> dict:
    base = {k:row[k] for k in (
      'source_row','paper_id','year_roc','exam_code','exam_name','grade_code',
      'grade_label','exam_grade','class_code','class_group','session_code',
      'official_subject','official_type','question_url','answer_url',
      'official_note','legal_candidate_class','title_domain_tags')}
    # These are official *references* to the same Q URL; do not turn them into
    # separate exam papers or lose a class_group when one Q link is shared.
    base['source_appearances'] = row.get('source_appearances', [appearance(row)])
    return base


def validate_paper(row: dict) -> tuple[dict, list[str]]:
    warnings=[]
    if row.get('catalog_classification_conflict') or row.get('source_metadata_conflict'):
        raise UnsafeSource('incompatible source metadata/classification; manual review required')
    if row['official_type'] not in ALLOWED_KINDS:
        raise UnsafeSource('unknown official question type')
    q_identity=source_ref(row['question_url'],'Q')
    if row['exam_code']!=q_identity[0] or row['class_code']!=q_identity[1] or not row['year_roc'] or not row['exam_code'].startswith(row['year_roc']):
        raise UnsafeSource('official title/CSV exam/class/year differs from PDF identity')
    if row['paper_id']!='moex-'+digest(row['question_url'].encode('utf-8'))[:24]:
        raise UnsafeSource('stable paper ID does not match immutable question URL')
    links={'Q':row['question_url']}
    if row['answer_url']:
        kind=urlsplit(row['answer_url']).query
        role=(parse_qs(kind).get('t') or [''])[0]
        if role not in ('S','M'):
            raise UnsafeSource('answer URL must be official S or corrected M')
        if source_ref(row['answer_url'],role) != q_identity:
            raise UnsafeSource('answer URL points to a different exam/class/paper')
        links[role]=row['answer_url']
        if role=='M':warnings.append('corrected_answer_M_not_verified_for_final_scoring')
    elif row['official_type'] in ('測驗題','混合題'):
        warnings.append('official_answer_link_missing')
    if row['official_type']=='混合題':warnings.append('mixed_paper_requires_item_level_type_review')
    if row['official_type']=='申論題':warnings.append('essay_requires_separate_issue_and_solution_review')
    if row['legal_candidate_class'] in ('其他／未標記','未分類（原始 CSV）'):
        warnings.append('legal_relevance_not_confirmed_by_title')
    return links,warnings


def make_plan(catalog: Path, *, years: list[str]|None=None, types:list[str]|None=None,
              scope='candidates',strategy='coverage',max_papers=9,start_row=1,
              exam_codes:list[str]|None=None, subjects:list[str]|None=None,
              class_groups:list[str]|None=None) -> dict:
    if scope not in ('candidates','all') or strategy not in ('coverage','sequential'):
        raise UnsafeSource('unknown plan scope or strategy')
    if years and any(not re.fullmatch(r'\d{2,3}',y) for y in years):
        raise UnsafeSource('invalid ROC year filter')
    if types and any(t not in ALLOWED_KINDS for t in types):
        raise UnsafeSource('invalid official format filter')
    if exam_codes and any(not re.fullmatch(r'\d{5,8}',v) for v in exam_codes):
        raise UnsafeSource('invalid official examination code filter')
    if any(not isinstance(v,str) or not v.strip() or len(v)>200 for group in (
            subjects or [],class_groups or []) for v in group):
        raise UnsafeSource('invalid subject/class filter')
    if not 1 <= max_papers <= MAX_BATCH or start_row<1:
        raise UnsafeSource('invalid start/limit bounds')
    source_fingerprint=sha256_file(catalog)
    total=0; candidates=0
    def catalog_rows():
        nonlocal total, candidates
        for row in catalog_records(catalog):
            total+=1
            if total>MAX_CATALOG_ROWS:
                raise UnsafeSource('unexpectedly many catalog rows')
            if is_candidate(row):candidates+=1
            yield row
    unique_records, dup_rows, conflicting_documents=unique_papers(catalog_rows())
    filtered=[]
    for row in unique_records:
        if row['source_row']<start_row:continue
        if years and row['year_roc'] not in years:continue
        if types and row['official_type'] not in types:continue
        if exam_codes and row['exam_code'] not in exam_codes:continue
        if subjects and row['official_subject'] not in subjects:continue
        if class_groups and not any(a['class_group'] in class_groups
                                    for a in row['source_appearances']):continue
        # Earlier and later official appearances are one source reference,
        # without losing those classes when only one appearance is selected.
        if scope=='candidates' and not row['any_title_candidate']:continue
        filtered.append(row)
    if scope=='candidates' and not candidates:
        raise UnsafeSource('no law-related titles in the supplied official catalog; try --scope all')
    if not filtered:
        raise UnsafeSource('no paper matched official year, exam, subject, class and type filters')
    chosen=pick_rows(filtered,max_papers=max_papers,strategy=strategy)
    papers=[]
    for row in chosen:
        meta=paper_metadata(row)
        try:
            links,warnings=validate_paper(row)
            state='planned_review_not_downloaded'
        except (UnsafeSource,TypeError,KeyError,ValueError) as exc:
            links={};warnings=['source_metadata_blocked:'+str(exc)[:150]];state='isolated_invalid_metadata'
        papers.append({**meta,'links':links,'state':state,
                       'issues':warnings,'source_file_sha256':source_fingerprint,
                       'content_verified':False,'answer_verified':False,'scoring_enabled':False})
    result={'schema':SCHEMA,'state':'offline_planned_no_PDF_download',
      'catalog_file_name':catalog.name,'catalog_sha256':source_fingerprint,
      'catalog_total_records':total,'catalog_title_candidates':candidates,
      'unique_official_Q_source_identities':len(unique_records),
      'duplicate_Q_reference_rows':dup_rows,
      'source_metadata_conflict_documents':conflicting_documents,
      'eligible_filtered_records':len(filtered),'selected_papers':len(papers),
      'strategy':strategy,'scope':scope,'years_filter':years or [],'types_filter':types or [],
      'exam_codes_filter':exam_codes or [],'subjects_filter':subjects or [],
      'class_groups_filter':class_groups or [],
      'cursor_last_selected_source_row':max((p['source_row'] for p in papers),default=None),
      'source_rows_in_requested_window':len(filtered),
      'original_catalog_unchanged':True,'publication_allowed':False,
      'scoring_enabled':False,'private_attempts_included':False,
      'papers':papers,
      'disclaimer':'This is only an official link plan, not downloaded PDFs or a validated question bank.'}
    return result


def essay_segments_from_text(text: str, *, max_segments=30) -> dict:
    """Tentative headings in a full original paper; never separate the paper ID."""
    text = text.replace('\r\n','\n').replace('\r','\n')
    if len(text)>MAX_TEXT_CHARS:
        return {'status':'long_text_requires_review','sections':[],'count':0}
    if len(text.strip())<40:
        return {'status':'no_readable_text_or_scanned_pdf','sections':[],'count':0}
    # Restrict heading anchors: article numbers inside paragraphs must not
    # accidentally turn the original paper into unrelated 'independent papers'.
    regex=re.compile(r'(?m)^[ \t\u3000]{0,8}(第[一二三四五六七八九十百0-9０-９]+題|[一二三四五六七八九十]+[、．]|[壹貳參肆伍陸柒捌玖拾]+[、．])(?=[ \t\u3000\n]|[^\w])')
    hits=list(regex.finditer(text))
    if not hits:
        return {'status':'unsegmented_paper_needs_manual_review','count':0,'sections':[],
                'raw_preview':text[:2800]}
    sections=[]
    for idx,m in enumerate(hits[:max_segments]):
        end=hits[idx+1].start() if idx+1<len(hits) else len(text)
        section=text[m.start():end].strip()
        if len(section)<15:continue
        sections.append({'sequence_unverified':idx+1,'heading_candidate':m.group(1),
                         'text_preview_unverified':section[:3800],
                         'truncated':len(section)>3800,
                         'human_verified':False})
    return {'status':'candidate_sections_need_visual_review','count':len(sections),
            'truncated_headings':len(hits)>max_segments,'sections':sections}


def inspect_essay_pdf(blob: bytes) -> tuple[str,dict]:
    from pypdf import PdfReader
    reader=PdfReader(io.BytesIO(blob),strict=False)
    if not 1<=len(reader.pages)<=120:
        raise UnsafeSource('unexpected PDF page count')
    pages=[]
    for page in reader.pages:
        pages.append(page.extract_text() or '')
    full='\n'.join(pages)
    if len(full)>MAX_TEXT_CHARS:
        return full[:MAX_TEXT_CHARS], {'status':'long_text_requires_review','count':0,'sections':[]}
    return full,essay_segments_from_text(full)


def plan_to_v03_index(p: dict) -> dict:
    """Adapter only: V0.3 remains the sole Q/S/M download+verification engine."""
    if p['state']!='planned_review_not_downloaded':
        raise UnsafeSource('blocked paper cannot run')
    links=p['links']
    focus=[]
    # This is only V0.3's legacy selector hint, NEVER the official category.
    # In particular 綜合法政知識與英文 is itself a subject: do not relabel
    # an entire composite paper as '憲法' merely because it mentions the word.
    if p['legal_candidate_class']=='名稱明確法律科目':
        for term in ('民法','刑法','憲法'):
            if p['official_subject'].startswith(term):
                focus.append(term)
    # V0.3 supports only 3 focus tags. The official subject name is retained
    # intact; for other law fields this list can be empty without data loss.
    return {'schema':'lexflow.moex.index.v1','status':'index_only_unverified_answers',
      'source':{'method':'user_uploaded_MOEX_official_CSV_catalog_bridge',
                'catalog_sha256':p['source_file_sha256']},
      'items':[{'id':p['paper_id'],'year_roc':p['year_roc'],
                'exam':p['exam_name'],'groups':[p['class_group']],
                'subject':p['official_subject'],'focus_subjects':focus,
                'classification':'subject_named' if p['legal_candidate_class']=='名稱明確法律科目' else 'needs_classification',
                'question_type':p['official_type'],
                'question_url':links['Q'],
                'answer_url':links.get('S',''),
                'answer_correction_url':links.get('M',''),
                'answer_verification':'not_verified',
                'explanation_verification':'not_available'}]}


def cached_fetch_for_review(cache_root:Path, *, offline_only=False):
    """Cache public source PDF bytes by URL, never by subject/title or user key."""
    from moex_batch_engine import fetch_pdf
    from moex_document_qa import validate_pdf_bytes
    cache_root.mkdir(parents=True, exist_ok=True)
    attempts={'remote':0,'cache':0}
    def fetch(ref):
        key=digest(ref['url'].encode('utf-8'))
        pdf_path=cache_root/(key+'.pdf')
        meta_path=cache_root/(key+'.json')
        if pdf_path.exists() and meta_path.exists():
            data=pdf_path.read_bytes();meta=json.loads(meta_path.read_text('utf-8'))
            if meta.get('url')!=ref['url'] or meta.get('sha256')!=digest(data):
                raise UnsafeSource('tampered cached official PDF, never silently use it')
            validate_pdf_bytes(data)
            attempts['cache']+=1
            return data
        if pdf_path.exists() or meta_path.exists():
            raise UnsafeSource('incomplete cache entry, old bytes preserved for inspection')
        if offline_only:
            raise UnsafeSource('official PDF not cached; offline requested')
        attempts['remote']+=1
        data=fetch_pdf(ref)
        validate_pdf_bytes(data)
        atomic_bytes(pdf_path,data)
        save_json(meta_path,{'url':ref['url'],'sha256':digest(data),
                             'bytes':len(data),'role':ref['role'],
                             'source':'original MOEX PDF; content not manually verified'})
        time.sleep(0.5)  # avoid burst requests to public service
        return data
    return fetch,attempts


def run_plan(plan:dict, out_dir:Path, *, max_papers=3, max_docs=9,
             start_at=1, offline_only=False, include_essay=True,
             shared_cache_root:Path|None=None)->dict:
    if plan.get('schema')!=SCHEMA or plan.get('publication_allowed') is not False or plan.get('scoring_enabled') is not False:
        raise UnsafeSource('untrusted plan or forged scoring status')
    if not 1<=max_papers<=MAX_BATCH or not 1<=max_docs<=MAX_DOCS or not 1<=start_at<=MAX_BATCH:
        raise UnsafeSource('review budget or start index exceeds safe bounds')
    papers=plan.get('papers')
    if not isinstance(papers,list) or len(papers)>MAX_BATCH:
        raise UnsafeSource('plan exceeds maximum allowed papers')
    from moex_batch_engine import process_batch, inspect_pdf_source
    out_dir.mkdir(parents=True,exist_ok=True)
    # New catalog snapshots keep independent reports, while immutable official
    # URL+SHA-checked PDF bytes may be reused across those report snapshots.
    cache_root=shared_cache_root if shared_cache_root is not None else out_dir/'official_pdf_cache'
    fetch,attempts=cached_fetch_for_review(cache_root,offline_only=offline_only)
    reviewed=[]; count_docs=0
    for p in papers[start_at-1:start_at-1+max_papers]:
        # This flow is conservative: existing batches never overwritten.
        pid=p.get('paper_id','')
        if not re.fullmatch(r'moex-[0-9a-f]{24}',pid):
            reviewed.append({'paper_id':str(pid)[:50], 'state':'invalid_paper_id'});continue
        item_path=out_dir/'reports'/(pid+'.json')
        if item_path.exists():
            prev=json.loads(item_path.read_text('utf-8'))
            if prev.get('catalog_sha256')!=plan['catalog_sha256'] or prev.get('official_source',{}).get('question_url')!=p.get('question_url'):
                reviewed.append({'paper_id':pid,'state':'source_changed_requires_new_run_directory'});continue
            # Append-only, separate quality preview for already downloaded whole papers.
            # Re-running must not rewrite original reports, raw text or PDF cache.
            quality_info={}
            try:
                from moex_quality_overlay import make_overlay_from_disk
                quality_path,_=make_overlay_from_disk(out_dir,item_path)
                quality_info={'quality_preview_state':'unverified_overlay_available',
                              'quality_preview_path':str(quality_path.relative_to(out_dir))}
            except (OSError,ValueError,TypeError,KeyError,ImportError) as exc:
                quality_info={'quality_preview_state':'isolated_overlay_failure',
                              'quality_preview_reason':type(exc).__name__}
            reviewed.append({'paper_id':pid,'state':'existing_report_preserved',**quality_info});continue
        if p.get('state')!='planned_review_not_downloaded':
            reviewed.append({'paper_id':pid,'state':'isolated_invalid_metadata'});continue
        count_docs=attempts['remote']+attempts['cache']
        limit=min(len(p['links']),max_docs-count_docs)
        if limit<len(p['links']):
            reviewed.append({'paper_id':pid,'state':'document_budget_exhausted_before_paper'});break
        # A missing Q or mismatched answer source is blocked before network I/O.
        try:
            validate_paper(p)
            v03=plan_to_v03_index(p)
            fulltext=None;essay_preview=None
            def inspect(blob,role,expected_subject):
                nonlocal fulltext, essay_preview
                check=inspect_pdf_source(blob,role,expected_subject)
                if role=='Q':
                    try:
                        fulltext,preview=inspect_essay_pdf(blob)
                        check['text_extraction_status']=preview['status']
                        if include_essay and p['official_type'] in ('申論題','混合題'):
                            essay_preview=preview
                            check['essay_preview_status']=preview['status']
                            check['essay_section_candidates_count']=preview['count']
                    except Exception as exc:
                        essay_preview={'status':'question_pdf_text_extract_failed','reason':type(exc).__name__}
                        check['text_extraction_status']='failed_requires_review'
                return check
            report=process_batch(v03,max_papers=1,max_documents=limit,
                 download=True,require_all=False,fetch=fetch,inspect=inspect,
                 extract_questions=p['official_type'] in ('測驗題','混合題'))
            if report.get('publication_allowed') is not False or report.get('scoring_enabled') is not False:
                raise UnsafeSource('upstream engine unexpectedly enabled scoring')
            core_paper_state=report['reviewed_items'][0].get('state','')
            report_state=('downloaded_source_still_requires_human_review'
                if core_paper_state=='pdfs_readable_CONTENT_NOT_VERIFIED'
                else 'partial_or_isolated_source_needs_review')
            result={'schema':REVIEW_SCHEMA,'state':report_state,
              'paper_id':pid,'catalog_sha256':plan['catalog_sha256'],
              'official_source':paper_metadata(p),
              'v03_review':report,
              'essay_candidate_sections':essay_preview if p['official_type'] in ('申論題','混合題') else None,
              'fulltext_ocr_and_visual_qa_pending':True,
              'publication_allowed':False,'scoring_enabled':False,
              'official_final_answers_verified':False,
              'human_quality_gate_satisfied':False,
              'private_attempts_included':False}
            if fulltext is not None:
                tpath=out_dir/'extracted_text'/(pid+'.txt')
                if tpath.exists():
                    raise UnsafeSource('existing extracted text will not be overwritten')
                atomic_bytes(tpath,fulltext.encode('utf-8'))
                result['extracted_question_text']={'relative_path':'extracted_text/'+pid+'.txt',
                  'sha256':digest(fulltext.encode('utf-8')),'chars':len(fulltext),
                  'unverified':True,'truncated':len(fulltext)>=MAX_TEXT_CHARS}
            save_json(item_path,result)
            # Post-processing only; no second downloader and NEVER rewrite the source.
            quality_info={}
            try:
                from moex_quality_overlay import make_overlay_from_disk
                quality_path,_=make_overlay_from_disk(out_dir,item_path)
                quality_info={'quality_preview_state':'unverified_overlay_available',
                              'quality_preview_path':str(quality_path.relative_to(out_dir))}
            except (OSError,ValueError,TypeError,KeyError,ImportError) as exc:
                quality_info={'quality_preview_state':'isolated_overlay_failure',
                              'quality_preview_reason':type(exc).__name__}
            reviewed.append({'paper_id':pid,'state':result['state'],
                             'documents':report['summary']['document_fetch_attempts'],
                             'isolated':report['summary']['isolated_papers'],**quality_info})
            count_docs=attempts['remote']+attempts['cache']
        except (UnsafeSource, OSError, ValueError, RuntimeError, ImportError) as exc:
            reviewed.append({'paper_id':pid,'state':'isolated_failed_not_published',
                             'reason':type(exc).__name__+': '+str(exc)[:160]})
    out={'schema':'lexflow.moex.review-run-summary.v1','catalog_sha256':plan['catalog_sha256'],
         'reviews':reviewed,'network_pdf_downloads':attempts['remote'],
         'cache_reuses':attempts['cache'],'publication_allowed':False,
         'scoring_enabled':False,'all_answers_verified':False,
         'original_catalog_unchanged':True}
    # Never overwrite previous run summaries: unique content hash name.
    summary_file=out_dir/('run-'+digest(json.dumps(out,sort_keys=True,ensure_ascii=False).encode())[:16]+'.json')
    if not summary_file.exists():save_json(summary_file,out)
    return out


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    modes=parser.add_subparsers(dest='action',required=True)
    inv=modes.add_parser('inventory', help='offline full-catalog metadata audit, no PDF/network')
    inv.add_argument('--catalog',type=Path,required=True)
    inv.add_argument('--output',type=Path,required=True)
    plan=modes.add_parser('plan',help='offline only: plan real official paper sources')
    plan.add_argument('--catalog',type=Path,required=True)
    plan.add_argument('--output',type=Path,required=True)
    plan.add_argument('--years',default='')
    plan.add_argument('--types',default='')
    plan.add_argument('--scope',choices=('candidates','all'),default='candidates')
    plan.add_argument('--strategy',choices=('coverage','sequential'),default='coverage')
    plan.add_argument('--start-row',type=int,default=1)
    plan.add_argument('--limit',type=int,default=9)
    plan.add_argument('--exam-code',action='append',dest='exam_codes',default=[],
                      help='exact official exam code; repeat for several')
    plan.add_argument('--subject',action='append',dest='subjects',default=[],
                      help='exact original official subject name; repeat for several')
    plan.add_argument('--class-group',action='append',dest='class_groups',default=[],
                      help='exact official class/group name; repeat for several')
    run=modes.add_parser('review',help='explicit bounded Q/S/M download and unverified extraction')
    run.add_argument('--plan',type=Path,required=True)
    run.add_argument('--output-dir',type=Path,required=True)
    run.add_argument('--max-papers',type=int,default=3)
    run.add_argument('--max-documents',type=int,default=9)
    run.add_argument('--offline-only',action='store_true')
    run.add_argument('--start-at',type=int,default=1,help='1-based manifest index for a later bounded batch')
    args=parser.parse_args(argv)
    try:
        if args.action=='inventory':
            if args.catalog.resolve()==args.output.resolve():
                raise UnsafeSource('never overwrite original catalog')
            if args.output.exists():
                raise UnsafeSource('existing inventory preserved: choose a new output path')
            inventory=inventory_catalog(args.catalog)
            save_json(args.output,inventory)
            print(json.dumps({
                'status':'FULL_CATALOG_METADATA_ONLY','source_rows':inventory['source_rows'],
                'unique_sources':inventory['unique_official_Q_source_identities'],
                'legal_candidate_rows':inventory['law_related_title_candidate_rows'],
                'metadata_isolation_reasons':inventory['metadata_isolation_reasons'],
                'publication_allowed':False,'scoring_enabled':False}, ensure_ascii=False))
            return 0
        if args.action=='plan':
            if args.catalog.resolve()==args.output.resolve():
                raise UnsafeSource('never overwrite original catalog')
            years=args.years.split(',') if args.years else None
            kinds=args.types.split(',') if args.types else None
            output=make_plan(args.catalog,years=years,types=kinds,scope=args.scope,
                             strategy=args.strategy,max_papers=args.limit,start_row=args.start_row,
                             exam_codes=args.exam_codes,subjects=args.subjects,
                             class_groups=args.class_groups)
            if args.output.exists():raise UnsafeSource('existing plan preserved: choose a new output path')
            save_json(args.output,output)
            print(json.dumps({'status':'PLANNED_OFFLINE','selected':output['selected_papers'],
                'total':output['catalog_total_records'],'filtered':output['eligible_filtered_records'],
                'types':{t:sum(p['official_type']==t for p in output['papers']) for t in ALLOWED_KINDS},
                'publication_allowed':False,'scoring_enabled':False},ensure_ascii=False))
            return 0
        blob=json.loads(args.plan.read_text('utf-8'))
        output=run_plan(blob,args.output_dir,max_papers=args.max_papers,
                        max_docs=args.max_documents,start_at=args.start_at,offline_only=args.offline_only)
        print(json.dumps(output,ensure_ascii=False))
        return 0
    except (UnsafeSource, OSError, ValueError, RuntimeError, ImportError) as exc:
        print('SAFE STOP: '+str(exc)[:300]+'; official source and study records unchanged',file=sys.stderr)
        return 2

if __name__=='__main__':
    sys.exit(main())
