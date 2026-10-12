#!/usr/bin/env python3
"""Final98 V4: READ-ONLY all-paper provenance audit and bounded MOEX source reacquisition.

No answer scoring, no automated content signoff, no release, no GitHub uploads.
Input is the private 449 paper staging shards ZIP, output is a report ZIP without
question text, PDF bytes, or private response records. Python standard library.
"""
from __future__ import annotations

import argparse
import collections
import csv
import datetime
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

SOURCE_DB_SHA = 'a43a6c786eb0f7404e2a5af952153b983919092866773594e0a458f64bf5facd'
EXPECTED = dict(papers=449, questions=9399, MCQ=8290, ESSAY=1109, risk_records=2293, risk_questions=1841, shared_articles=34)
HEX64 = re.compile(r'^[a-f0-9]{64}$')
PAPER_ID = re.compile(r'^MOEX-Q-[a-f0-9]{20}$')
ALLOWED_ROLES = {'VERIFY_Q', 'EXISTING_S', 'MISSING_S', 'EXISTING_M', 'MISSING_M'}
MAX_SOURCE_BYTES = 16 * 1024 * 1024
MAX_ZIP_ENTRY = 12 * 1024 * 1024
USER_AGENT = 'LexFlow-SourceAudit/4.0 (review-only, no score, no publishing)'

class ReviewError(Exception):
    pass


def require(ok, message):
    if not ok:
        raise ReviewError(message)


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def encode_json(data) -> bytes:
    return (json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode('utf-8')


def validate_official_url(raw: str, role: str | None = None):
    require(isinstance(raw, str) and 0 < len(raw) <= 2048, '非法來源網址長度')
    try:
        url = urllib.parse.urlsplit(raw)
        require(url.scheme == 'https' and url.hostname in ('moex.gov.tw', 'wwwq.moex.gov.tw') or
                (url.scheme == 'https' and url.hostname and url.hostname.endswith('.moex.gov.tw')),
                '不是可信的考選部 HTTPS 網域')
        require(not url.username and not url.password and not url.fragment and url.port in (None, 443), '網址含不安全參數')
        require(url.path.lower().endswith('whandexamqanda_file.ashx'), '不是官方 Q/S/M 試題檔案路徑')
        qs = urllib.parse.parse_qs(url.query, keep_blank_values=True)
        require(all(len(qs.get(k, [])) == 1 and qs[k][0].strip() for k in ('code','c','s','q','t')), '官方試卷網址身分參數不完整')
        require(qs['t'][0] in ('Q','S','M'), '不支援的官方文件型態')
        if role:
            want = 'Q' if role == 'VERIFY_Q' else ('S' if role.endswith('_S') else 'M')
            require(qs['t'][0] == want, '角色與官方網址 Q/S/M 不一致')
        return {k:qs[k][0] for k in ('code','c','s','q','t')}
    except (ValueError,AttributeError,TypeError) as exc:
        raise ReviewError('官方來源網址格式不符') from exc


def reference_relation(question_url: str, source_url: str) -> str:
    q = validate_official_url(question_url, 'VERIFY_Q')
    a = validate_official_url(source_url)
    if any(q[k] != a[k] for k in ('code','s','q')):
        return 'DIFFERENT_EXAM_IDENTITY_QUARANTINE'
    if q['c'] != a['c']:
        return 'CROSS_CLASS_ASSOCIATION_NOT_AUTOMATICALLY_EQUIVALENT'
    return 'EXACT_EXAM_CLASS_SUBJECT_IDENTITY'


def _zip_read(z, name):
    i = z.getinfo(name)
    require(i.file_size <= MAX_ZIP_ENTRY, 'ZIP 檔案過大: '+name)
    return z.read(name)


def audit(source_zip: Path, expected=EXPECTED) -> tuple[dict, list[dict], list[dict]]:
    """Audit a ZIP. expected can be overridden by synthetic offline unit tests only."""
    require(source_zip.is_file() and not source_zip.is_symlink(), '找不到安全的原始分片 ZIP')
    q_ids, paper_ids = set(), set()
    role_docs = collections.Counter()
    risk_code_counts = collections.Counter()
    kinds = collections.Counter()
    section_counts = collections.Counter()
    role_paper = collections.defaultdict(set)
    targets = []
    problems = []
    per_paper = []
    question_matrix = []
    risk_questions = 0
    count_articles = 0
    five_choice = 0
    cross_class_papers = set()
    cross_class_links = 0
    mcq_papers = 0
    paper_s_roles = collections.Counter()
    s_questions = collections.Counter()
    paper_types = collections.Counter()
    try:
        with zipfile.ZipFile(source_zip, 'r') as z:
            names = z.namelist()
            require(len(names) == len(set(names)), 'ZIP 有重複路徑')
            require(all(name == 'manifest.json' or name == 'audit.json' or
                        (name.startswith('papers/') and PAPER_ID.fullmatch(name[7:-5]) and name.endswith('.json'))
                        for name in names), 'ZIP 含非預期路徑或外來資料')
            manifest = json.loads(_zip_read(z, 'manifest.json'))
            require(manifest.get('schema') == 'lexflow.final98.shards.preview.v1', '分片結構版本錯誤')
            require(manifest.get('db_sha256') == SOURCE_DB_SHA, '不是核定的 Final98 隔離來源資料庫')
            require(manifest.get('publication_allowed') is False and manifest.get('scoring_enabled') is False and
                    manifest.get('backend_import_allowed') is False, '分片包含未授權的發布或計分狀態')
            entries = manifest.get('papers')
            require(isinstance(entries, list) and len(entries) == expected['papers'], '試卷筆數不符')
            require(len(names) == len(entries)+2, 'ZIP 內含多餘或遺漏的分片')
            for record in entries:
                pid = record['id']; path = record['path']
                require(PAPER_ID.fullmatch(pid) and path == 'papers/'+pid+'.json', '試卷名稱或路徑不合法')
                require(pid not in paper_ids, '發現重複試卷 ID')
                paper_ids.add(pid)
                raw = _zip_read(z, path)
                require(HEX64.fullmatch(record['sha256']) and sha256(raw)==record['sha256'], '試卷分片 SHA256 不符: '+pid)
                obj = json.loads(raw)
                require(obj.get('schema')=='lexflow.final98.paper.preview.v1' and obj.get('id')==pid, '分片來源身分不一致')
                require(obj.get('publication_allowed') is False and obj.get('scoring_enabled') is False and
                        obj.get('answers_omitted') is True, '原卷候審資料被擅自放行')
                qsrc = validate_official_url(obj['officialUrl'], 'VERIFY_Q')
                srcpdf = obj.get('sourcePdfSha256')
                require(isinstance(srcpdf,str) and HEX64.fullmatch(srcpdf) and pid.endswith(srcpdf[:20]), 'Q 原始雜湊不符合試卷身分')
                all_questions = obj.get('questions')
                require(isinstance(all_questions,list) and len(all_questions)==record['questionCount'], '單卷題數不符: '+pid)
                sources = obj.get('sources')
                require(isinstance(sources,list) and sources, '缺少官方來源文件紀錄')
                article_list=obj.get('articles')
                require(isinstance(article_list,list), '共用題文分組資料格式不符')
                article_ids=set()
                for a in article_list:
                    key=a.get('article_key')
                    require(isinstance(key,str) and key not in article_ids and a.get('paper_id')==pid, '重複或跨卷共用題文')
                    require(isinstance(a.get('effective_article_body'),str) and a['effective_article_body'].strip(), '共用題文為空白')
                    article_ids.add(key)
                count_articles+=len(article_ids)
                thiskind=collections.Counter()
                thisrisk=collections.Counter()
                for q in all_questions:
                    qid=q.get('id'); kind=q.get('kind');risks=q.get('risks')
                    require(isinstance(qid,str) and qid.startswith(pid+'-') and qid not in q_ids, '題目 ID 重複或不屬於試卷')
                    q_ids.add(qid)
                    require(kind in ('MCQ','ESSAY'), '未知題型')
                    require(isinstance(q.get('stem'),str) and q['stem'].strip(), '空白題文')
                    require(q.get('previewOnly') is True and q.get('previewIssue') is None, '題目不是完整候審格式')
                    require(isinstance(q.get('effectiveSha256'),str) and HEX64.fullmatch(q['effectiveSha256']), '題文證據雜湊不合法')
                    require(not any(k in q for k in ('answer','correct','officialAnswer','officialScore','scoring_rule','grade','release_allowed')),
                            '私人候審資料含有未授權答案／分數欄位')
                    require(isinstance(risks,list) and all(isinstance(r,str) and r.strip() for r in risks), '風險欄位不合法')
                    require(isinstance(q.get('domains'),list) and all(isinstance(v,str) for v in q['domains']), '科目標籤不合法')
                    if q.get('articleKey'):
                        require(q['articleKey'] in article_ids, '題目共用文章關聯缺失')
                    options=q.get('options')
                    require(isinstance(options,list), '選項格式不是陣列')
                    if kind=='MCQ':
                        require(len(options) in (4,5), '選擇題缺少四／五選項')
                        if len(options)==5:five_choice+=1
                        require(all(isinstance(x,str) and x.strip() and len(x) <= 12000 for x in options),
                                '選項文字為空白或過長')
                    else:
                        require(options==[], '申論題出現選項')
                    thiskind[kind]+=1;kinds[kind]+=1
                    if risks:
                        risk_questions+=1
                        for risk in risks:
                            risk_code_counts[risk]+=1;thisrisk[risk]+=1
                    section_counts.update(q.get('domains',[]))
                    question_matrix.append({'paper_id':pid,'question_id':qid,'kind':kind,
                       'subject':str(q.get('subject') or ''),'domains':list(q.get('domains',[])),
                       'risk_codes':risks,'shared_article_key':q.get('articleKey') or '',
                       'effective_content_sha256':q['effectiveSha256']})
                require(thiskind['MCQ']==record['mcqCount'] and thiskind['ESSAY']==record['essayCount'], '單卷題型統計不符')
                if thiskind['MCQ']: mcq_papers+=1
                paper_types['MIXED' if thiskind['MCQ'] and thiskind['ESSAY'] else ('MCQ' if thiskind['MCQ'] else 'ESSAY')]+=1
                state_s=set()
                for item in sources:
                    role=item.get('role')
                    require(item.get('paper_id')==pid and role in ALLOWED_ROLES,'來源角色或試卷身分不合法')
                    url=item.get('official_url'); h=item.get('source_sha256')
                    require(isinstance(h,str) and HEX64.fullmatch(h), '官方來源雜湊欄位不合法')
                    validate_official_url(url, role)
                    rel=reference_relation(obj['officialUrl'],url)
                    if role=='VERIFY_Q':
                        require(h==srcpdf and url==obj['officialUrl'], 'Q 官方來源不符合原卷雜湊或網址')
                    else:
                        require(thiskind['MCQ']>0, '不含選擇題的卷附有非 Q 答案來源')
                        if rel=='CROSS_CLASS_ASSOCIATION_NOT_AUTOMATICALLY_EQUIVALENT':
                            cross_class_links+=1;cross_class_papers.add(pid)
                        if rel=='DIFFERENT_EXAM_IDENTITY_QUARANTINE':
                            problems.append({'paper_id':pid,'issue':'SOURCE_DOC_EXAM_ID_MISMATCH','role':role})
                        if role.endswith('_S'): state_s.add('EXISTING' if role.startswith('EXISTING') else 'MISSING')
                    role_docs[role]+=1;role_paper[role].add(pid)
                    targets.append({'paper_id':pid,'role':role,'url':url,'reference_sha256':h,
                                    'class_relation':rel,'source_status_in_staging':role})
                require(sum(s['role']=='VERIFY_Q' for s in sources)==1, '試卷缺少唯一 Q 文件')
                if thiskind['MCQ']:
                    require(len(state_s)==1,'選擇題卷 S 來源角色缺失或矛盾')
                    state_s=next(iter(state_s))
                    paper_s_roles[state_s]+=1
                    s_questions[state_s]+=thiskind['MCQ']
                per_paper.append({'paper_id':pid,'mcq':thiskind['MCQ'],'essay':thiskind['ESSAY'],
                    's_role':(next(iter(state_s)) if state_s else 'NOT_APPLICABLE_ESSAY'),
                    'risk_questions':sum(1 for q in all_questions if q['risks']),
                    'risks':dict(thisrisk),
                    'source_role_counts':dict(collections.Counter(s['role'] for s in sources)),
                    'cross_class_source_relation':pid in cross_class_papers})
            require(len(q_ids)==expected['questions'] and len(paper_ids)==expected['papers'], '總題數／試卷數不符')
            require(kinds['MCQ']==expected['MCQ'] and kinds['ESSAY']==expected['ESSAY'], '題型總題數不符')
            require(sum(risk_code_counts.values())==expected['risk_records'] and risk_questions==expected['risk_questions'], '風險證據總數不符')
            require(count_articles==expected['shared_articles'], '共用文章數量不符')
    except (ValueError,KeyError,TypeError,zipfile.BadZipFile,IndexError) as exc:
        raise ReviewError('來源分片資料毀損或欄位不相容: '+str(exc)) from exc
    summary={'schema':'lexflow.final98.source.qa.v4','status':'MACHINE_STAGING_READY_SOURCE_ANSWER_REVIEW_PENDING',
             'generated_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
             'source_db_sha256':SOURCE_DB_SHA,'archive_sha256':file_sha(source_zip),
             'papers':len(paper_ids),'questions':len(q_ids),'question_kinds':dict(kinds),
             'paper_types':dict(paper_types),'mcq_papers':mcq_papers,
             'paper_s_role_counts':dict(paper_s_roles),'mcq_questions_by_s_role':dict(s_questions),
             'source_role_rows':dict(role_docs),'distinct_papers_by_source_role':{k:len(v) for k,v in role_paper.items()},
             'all_source_rows':len(targets),'shared_articles':count_articles,'five_choice_questions':five_choice,
             'risk_records':sum(risk_code_counts.values()),'risk_questions':risk_questions,
             'risk_codes':dict(risk_code_counts.most_common()),'cross_class_source_rows':cross_class_links,
             'cross_class_papers':len(cross_class_papers),'cross_class_paper_ids':sorted(cross_class_papers),
             'domains':dict(section_counts),'source_identity_warnings':problems,
             'release_permitted':False,'official_scoring_permitted':False,
             'original_item_content_human_verified':False,'official_answer_pairing_complete':False,
             'all_official_corrections_verified':False,'full_official_legal_explanations_verified':False,
             'live_backend_modified':False}
    return summary, per_paper, targets, question_matrix


def file_sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):
            h.update(b)
    return h.hexdigest()


def unique_source_tasks(targets, *, include_q=False):
    todo=[]; seen={}
    for doc in targets:
        role=doc['role']
        if role=='VERIFY_Q' and not include_q:continue
        # All pre-paired URLs are retained, but cross-class associations may
        # NOT authorize another class's scoring or final answer.
        k=doc['url']
        old=seen.get(k)
        if old:
            require(old['reference_sha256']==doc['reference_sha256'], '同網址不同來源 SHA 衝突，拒絕下載')
            old['referenced_by'].append({'paper_id':doc['paper_id'],'role':role,'class_relation':doc['class_relation']})
        else:
            new={'url':k,'reference_sha256':doc['reference_sha256'],
                 'source_type':'Q' if role=='VERIFY_Q' else role[-1],
                 'referenced_by':[{'paper_id':doc['paper_id'],'role':role,'class_relation':doc['class_relation']}],
                 'status':'NOT_FETCHED'}
            todo.append(new);seen[k]=new
    # Handle the staging MISSING_* designations first. They already carry source
    # URLs and historic SHA values, but are NOT certified final answer sources.
    priority={'MISSING_S':0,'MISSING_M':1,'EXISTING_M':2,'EXISTING_S':3,'VERIFY_Q':4}
    todo.sort(key=lambda t:(min(priority[r['role']] for r in t['referenced_by']),t['url']))
    return todo


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ReviewError('來源發生重新導向；需重新審查官方網址')


def fetch_document(target, cache_dir: Path, timeout=20, opener=None):
    validate_official_url(target['url'])
    cache_dir.mkdir(parents=True,exist_ok=True,mode=0o700)
    require(not cache_dir.is_symlink(), '來源快取目錄不可為捷徑')
    url_id=sha256(target['url'].encode())
    stamp=cache_dir / (url_id+'.json')
    if stamp.exists():
        try:
            m=json.loads(stamp.read_text('utf-8'))
            dest=cache_dir / (m['actual_sha256']+'.pdf')
            if (m['url']==target['url'] and dest.is_file() and
                file_sha(dest)==m['actual_sha256'] and dest.stat().st_size<=MAX_SOURCE_BYTES):
                return {**m,'status':'CACHED_MATCH' if m['actual_sha256']==target['reference_sha256'] else 'CACHED_MISMATCH'}
        except (OSError,ValueError,KeyError):pass
    if opener is None:opener=urllib.request.build_opener(NoRedirect())
    try:
        request=urllib.request.Request(target['url'],headers={'User-Agent':USER_AGENT,'Accept':'application/pdf,application/octet-stream,*/*'})
        with opener.open(request,timeout=timeout) as response:
            final=response.geturl()
            validate_official_url(final)
            require(final==target['url'], '官方檔案 URL 被重導')
            n=0;chunks=[]
            while True:
                part=response.read(65536)
                if not part:break
                n+=len(part)
                require(n<=MAX_SOURCE_BYTES, 'PDF 超過 16 MB 安全限制')
                chunks.append(part)
        data=b''.join(chunks)
        require(len(data)>100 and data[:1024].lstrip().startswith(b'%PDF-'), '回應不是 PDF；可能是 HTML 或官方錯誤頁')
        h=sha256(data)
        dest=cache_dir/(h+'.pdf')
        if not dest.exists():
            fd,tmppath=tempfile.mkstemp(dir=cache_dir,prefix='.download_',suffix='.part');os.fchmod(fd,0o600)
            try:
                with os.fdopen(fd,'wb') as f:f.write(data);f.flush();os.fsync(f.fileno())
                os.replace(tmppath,dest)
            finally:
                if os.path.exists(tmppath):os.unlink(tmppath)
        result={'url':target['url'],'reference_sha256':target['reference_sha256'],
                'actual_sha256':h,'bytes':len(data),'checked_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
                'status':'PDF_SHA256_MATCH' if h==target['reference_sha256'] else 'PDF_SHA256_MISMATCH',
                'legal_content_reviewed':False,'final_answer_verified':False,'scoring_enabled':False}
        # Cache only integrity-inspectable PDFs; never publish them.
        atomic_json(stamp,result)
        return result
    except (OSError,TimeoutError,urllib.error.URLError,urllib.error.HTTPError,ReviewError) as e:
        return {'url':target['url'],'reference_sha256':target['reference_sha256'],
                'status':'FETCH_BLOCKED','reason':str(e)[:250],
                'legal_content_reviewed':False,'final_answer_verified':False,'scoring_enabled':False}


def atomic_json(path: Path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(dir=path.parent,prefix='.atomic_',suffix='.json');os.fchmod(fd,0o600)
    try:
        with os.fdopen(fd,'wb') as f:f.write(encode_json(data));f.flush();os.fsync(f.fileno())
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)


def campaign_fetch(tasks, cache: Path, *, rate_seconds=.8, timeout=20, max_requests=1000, time_budget_seconds=900, fetcher=None, report_progress=True):
    if fetcher is None:fetcher=fetch_document
    out=[];last=0.0; started=time.monotonic()
    for i, task in enumerate(tasks):
        if i>=max_requests:
            out.extend({**p,'status':'DEFERRED_RATE_BOUND'} for p in tasks[i:]);break
        if time.monotonic()-started>=time_budget_seconds:
            out.extend({**p,'status':'DEFERRED_TIME_BUDGET'} for p in tasks[i:]);break
        if rate_seconds>0 and last:
            wait=rate_seconds-(time.monotonic()-last)
            if wait>0:time.sleep(wait)
        last=time.monotonic()
        res=fetcher(task, cache, timeout=timeout)
        out.append({**task,**res})
        if report_progress and ((i+1)%15==0 or i+1==len(tasks)):
            matches=sum(x.get('status') in ('PDF_SHA256_MATCH','CACHED_MATCH') for x in out)
            print(f'  來源檔案 {i+1}/{len(tasks)}，雜湊一致 {matches}，其餘保留隔離',flush=True)
    return out


def create_report(out_path: Path, summary: dict, papers: list, source_status: list, question_matrix: list):
    require(not out_path.exists(), '報告檔案已存在，拒絕覆寫')
    out_path.parent.mkdir(parents=True,exist_ok=True)
    statuses=collections.Counter(x.get('status','UNKNOWN') for x in source_status)
    summary={**summary,'source_recheck':{'status_counts':dict(statuses),
                'total_urls':len(source_status),'all_corrected_answers_verified':False},
                'release_permitted':False,'official_scoring_permitted':False}
    buffer=io.StringIO();w=csv.writer(buffer)
    w.writerow(['paper_id','mcq','essay','S_source_role','risk_questions','risk_codes','source_role_counts','cross_class_source'])
    for row in papers:
        w.writerow([row['paper_id'],row['mcq'],row['essay'],row['s_role'],row['risk_questions'],
                    json.dumps(row['risks'],ensure_ascii=False),json.dumps(row['source_role_counts'],ensure_ascii=False),
                    row['cross_class_source_relation']])
    qbuf=io.StringIO();qw=csv.writer(qbuf)
    qw.writerow(['paper_id','question_id','kind','subject','domain_tags','risk_codes','shared_article_key','effective_sha256','release_allowed'])
    for row in question_matrix:
        qw.writerow([row['paper_id'],row['question_id'],row['kind'],row['subject'],
                     '|'.join(row['domains']),'|'.join(row['risk_codes']),row['shared_article_key'],
                     row['effective_content_sha256'],'false'])
    fd,temporary=tempfile.mkstemp(dir=out_path.parent,prefix='.lexflow_report_',suffix='.zip');os.close(fd)
    try:
        with zipfile.ZipFile(temporary,'w',zipfile.ZIP_DEFLATED,compresslevel=8) as z:
            z.writestr('audit_summary.json',encode_json(summary))
            z.writestr('paper_gap_matrix.csv',buffer.getvalue().encode('utf-8-sig'))
            z.writestr('question_evidence_matrix.csv',qbuf.getvalue().encode('utf-8-sig'))
            z.writestr('official_source_recheck.json',encode_json({'schema':'lexflow.final98.moe.source.review.v4',
                'scope':'SOURCE_DOWNLOAD_SHA_ONLY_NOT_ANSWER_CERTIFICATION','documents':source_status,
                'publication_allowed':False,'scoring_enabled':False,'all_answers_verified':False}))
            z.writestr('README.txt','LexFlow Final98 V4: independent machine-only provenance & official document SHA audit.\n'
                'No question text, answer keys, PDF bytes, personal practice history, or GitHub credentials.\n'
                'A PDF SHA match does NOT certify answer-key rows, final correction notices, legal explanations, or official scores.\n'
                'No data was imported to production. All official scoring and publication remain LOCKED.\n')
        with zipfile.ZipFile(temporary) as z:
            require(z.testzip() is None,'產出 ZIP 損壞')
            x=json.loads(z.read('audit_summary.json'))
            require(x['release_permitted'] is False and x['official_scoring_permitted'] is False,'未授權放行')
        os.replace(temporary,out_path)
    finally:
        if os.path.exists(temporary):os.unlink(temporary)
    return summary


def source_path():
    directories=[Path.home()/'storage'/'downloads',Path.home()/'downloads',Path.home()]
    matches=[]
    for d in directories:
        if d.is_dir():matches.extend(d.glob('LexFlow_449_Shards_STAGING_*.zip'))
    if not matches:
        raise ReviewError('找不到 LexFlow_449_Shards_STAGING_*.zip。請確認原來產生的分片包仍在 Downloads。')
    return max(matches,key=lambda p:p.stat().st_mtime)


def main(argv=None):
    ap=argparse.ArgumentParser(description='Read-only 449-paper Final98 evidence audit, no scoring or release')
    ap.add_argument('--shards',type=Path,help='Existing private 449 shard ZIP')
    ap.add_argument('--mode',choices=('offline','source-recheck'),default='source-recheck')
    ap.add_argument('--include-q',action='store_true',help='Also reacquire 449 Q PDFs (can take a long time)')
    ap.add_argument('--max-requests',type=int,default=350)
    ap.add_argument('--rate-seconds',type=float,default=.8)
    ap.add_argument('--timeout',type=int,default=20)
    ap.add_argument('--time-budget-seconds',type=int,default=900)
    ap.add_argument('--cache',type=Path,default=Path.home()/'LexFlow_Final98_V4_SourceCache')
    ap.add_argument('--output',type=Path)
    args=ap.parse_args(argv)
    try:
        require(0<=args.max_requests<=1000 and .35<=args.rate_seconds<=10 and 5<=args.timeout<=60 and
                30<=args.time_budget_seconds<=1800, '來源下載速率或時間參數不安全')
        path=args.shards or source_path()
        print('[1/3] 唯讀逐卷/逐題核對 Final98 449 卷、9,399 題…',flush=True)
        summary,papers,targets,questions=audit(path)
        todo=unique_source_tasks(targets,include_q=args.include_q)
        print(f"  驗證 {summary['papers']} 份 / {summary['questions']} 題 / {summary['risk_records']} 筆風險標記")
        print(f"  選擇題卷已列 EXISTING_S={summary['paper_s_role_counts'].get('EXISTING',0)}，MISSING_S={summary['paper_s_role_counts'].get('MISSING',0)}")
        print(f"  Q/S/M 對應需隔離的跨類科關聯：{summary['cross_class_source_rows']} 筆")
        if summary['source_identity_warnings']:
            print('  ⚠️ 來源考試代碼不符，已登錄隔離，不會當成最終答案')
        if args.mode=='source-recheck':
            print(f'[2/3] 批次核對 {len(todo)} 個官方 S/M'+('/Q' if args.include_q else '')+' PDF 來源指紋（缺件/更正不自動放行）…',flush=True)
            states=campaign_fetch(todo,args.cache,rate_seconds=args.rate_seconds,timeout=args.timeout,
                                  max_requests=args.max_requests,time_budget_seconds=args.time_budget_seconds)
        else:
            print('[2/3] 離線模式，不向官方網站下載 PDF。')
            states=[{**x,'status':'NOT_FETCHED'} for x in todo]
        print('[3/3] 產生不含題文、答案或 PDF 的 QA 報告 ZIP…',flush=True)
        dest=args.output
        if dest is None:
            dl=Path.home()/'storage'/'downloads';dl=dl if dl.is_dir() else Path.home()
            dest=dl/('LexFlow_Final98_V4_AutoQA_'+datetime.datetime.now().strftime('%Y%m%d_%H%M%S')+'.zip')
        report=create_report(dest,summary,papers,states,questions)
        print('\n✅ 完成唯讀來源核驗報告：'+str(dest))
        print('來源結果：'+str(report['source_recheck']['status_counts']))
        print('🔒 正式題庫匯入及官方計分仍鎖定。來源 PDF 雜湊通過≠最終答案驗證。',flush=True)
        return 0
    except (ReviewError,OSError,ValueError,zipfile.BadZipFile) as e:
        print('⛔ 安全停止：'+str(e),file=sys.stderr)
        return 2

if __name__=='__main__':sys.exit(main())
