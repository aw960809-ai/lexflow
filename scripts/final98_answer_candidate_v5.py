#!/usr/bin/env python3
"""LexFlow Final98 V5 -- SHA-pinned, cache-only *candidate* official answer pairing.

Inputs: private Final98 449-paper staging archive, V4 source-only QA ZIP, and
Termux private cache of 301 original MOEX S/M PDFs. Absolutely no network,
no changes to formal database, no scoring or official final-key authorization.
"""
from __future__ import annotations
import argparse
import collections
import csv
import datetime as dt
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import stat
import statistics
import sys
import tempfile
import unicodedata
from urllib.parse import urlsplit, parse_qs
import zipfile

DB_SHA = 'a43a6c786eb0f7404e2a5af952153b983919092866773594e0a458f64bf5facd'
EXPECTED = {'papers':449,'questions':9399,'MCQ':8290,'ESSAY':1109}
HEX64 = re.compile(r'^[0-9a-f]{64}$')
PID = re.compile(r'^MOEX-Q-[0-9a-f]{20}$')
MAX_PDF_BYTES = 16*1024*1024
MAX_PAGES = 30
MAX_TEXT_CHARS = 250000
MAX_PDF_TOKENS = 7000
REPORT_SCHEMA = 'lexflow.final98.answer.candidates.v5'
CORRECTION_RE = re.compile(r'(?:第\s*(\d{1,3})\s*題|題號\s*(\d{1,3}))[^\n。]{0,110}?([A-E])\s*(?:或|、|／|/|及|和)\s*([A-E])\s*(?:者)?\s*(?:均|都)?\s*(?:給分|計分|給予分數|得分)')
DECLARED = re.compile(r'(?:單選題數|測驗式試題共|測驗題數)\s*[:：]?\s*(\d{1,3})\s*題')
NUM_CELL = re.compile(r'^(?:第)?([0-9]{1,3})(?:題)?$')

class GateError(RuntimeError): pass

def check(condition, code):
    if not condition: raise GateError(code)

def sha256(v): return hashlib.sha256(v).hexdigest()

def sha_file(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for data in iter(lambda:f.read(1048576),b''):h.update(data)
    return h.hexdigest()

def jsondata(obj):
    return (json.dumps(obj,ensure_ascii=False,indent=2,sort_keys=True,allow_nan=False)+'\n').encode('utf-8')

def normalize(text): return unicodedata.normalize('NFKC',str(text or ''))

def file_safe(path, maxsize):
    check(path.is_file() and not path.is_symlink(),'UNSAFE_OR_MISSING_FILE:'+str(path))
    check(stat.S_ISREG(path.stat().st_mode) and path.stat().st_size<=maxsize,'FILE_SIZE_OR_TYPE_INVALID')

def source_identity(url,role=None):
    """Precisely bind MOEX code, class, subject and exam part. No cross-class merge."""
    try:
        check(type(url) is str and 0<len(url)<2049,'BAD_URL')
        u=urlsplit(url)
        check(u.scheme=='https' and u.hostname=='wwwq.moex.gov.tw' and not u.username
              and not u.password and u.port in (None,443) and not u.fragment,'UNTRUSTED_DOMAIN')
        check(u.path.lower()=='/exam/whandexamqanda_file.ashx','UNTRUSTED_PATH')
        q=parse_qs(u.query,strict_parsing=True,keep_blank_values=True)
        check(set(q)=={'t','code','c','s','q'} and all(len(v)==1 for v in q.values()),'UNTRUSTED_QS')
        check(q['t'][0] in {'Q','S','M'},'UNTRUSTED_ROLE')
        if role:check(q['t'][0]==role,'URL_ROLE_MISMATCH')
        check(all(re.fullmatch(r'\d{1,8}',q[k][0]) for k in ('code','c','s','q')),'BAD_CODE')
        return tuple(q[k][0] for k in ('code','c','s','q'))
    except (TypeError,ValueError,AttributeError) as e:
        raise GateError('INVALID_OFFICIAL_SOURCE_IDENTITY') from e


def load_inputs(v4,shards):
    file_safe(v4,8*1024*1024);file_safe(shards,100*1024*1024)
    with zipfile.ZipFile(v4) as z:
        check(z.testzip() is None,'V4_ZIP_CORRUPT')
        report=json.loads(z.read('audit_summary.json'))
        recheck=json.loads(z.read('official_source_recheck.json'))
        check(report['schema']=='lexflow.final98.source.qa.v4' and
              report['source_db_sha256']==DB_SHA and report['release_permitted'] is False
              and report['official_scoring_permitted'] is False,'V4_RELEASE_GATE_MISMATCH')
        check(report['papers']==449 and report['questions']==9399 and
              report['question_kinds']=={'ESSAY':1109,'MCQ':8290},'V4_COUNTS_MISMATCH')
        check(recheck['schema']=='lexflow.final98.moe.source.review.v4' and
              recheck['publication_allowed'] is False and recheck['scoring_enabled'] is False and
              recheck['all_answers_verified'] is False,'V4_SOURCE_GATE_MISMATCH')
        documents=recheck['documents']
        check(len(documents)==301 and len({d['url'] for d in documents})==301,'V4_SOURCE_COUNT_MISMATCH')
        for d in documents:
            check(d['status'] in ('PDF_SHA256_MATCH','CACHED_MATCH') and
                  d['actual_sha256']==d['reference_sha256'] and HEX64.fullmatch(d['actual_sha256']) and
                  d['final_answer_verified'] is False and d['scoring_enabled'] is False,'V4_DOC_UNTRUSTED')
            source_identity(d['url'],d['source_type'])
    check(sha_file(shards)==report['archive_sha256'],'V4_SHARD_ARCHIVE_FINGERPRINT_MISMATCH')
    paper_map={}
    with zipfile.ZipFile(shards) as z:
        check(z.testzip() is None,'SHARDS_ZIP_CORRUPT')
        manifest=json.loads(z.read('manifest.json'))
        check(manifest['schema']=='lexflow.final98.shards.preview.v1' and
              manifest['db_sha256']==DB_SHA and manifest['publication_allowed'] is False and
              manifest['scoring_enabled'] is False and manifest['backend_import_allowed'] is False,'SHARDS_GATES_FAILED')
        check(len(manifest['papers'])==449,'PAPER_MANIFEST_COUNT_FAILED')
        unique=set();kind_counter=collections.Counter()
        for p in manifest['papers']:
            paperid=p['id'];path=p['path']
            check(PID.fullmatch(paperid) and path=='papers/'+paperid+'.json','UNSAFE_PAPER_PATH')
            blob=z.read(path)
            check(sha256(blob)==p['sha256'],'PAPER_FRAGMENT_HASH_MISMATCH')
            paper=json.loads(blob)
            check(paper['id']==paperid and paper['answers_omitted'] is True and
                  paper['scoring_enabled'] is False and paper['publication_allowed'] is False,
                  'PAPER_RELEASE_GATE_FAILED')
            source_identity(paper['officialUrl'],'Q')
            questions=paper['questions']
            check(len(questions)==p['questionCount'],'PAPER_QUESTION_COUNT_MISMATCH')
            numbered=[]
            for q in questions:
                check(q['id'] not in unique,'DUPLICATE_QUESTION_ID')
                unique.add(q['id'])
                check(q['kind'] in ('MCQ','ESSAY') and q['previewOnly'] is True,'BAD_QUESTION_STATE')
                kind_counter[q['kind']]+=1
                if q['kind']=='MCQ':
                    check(re.fullmatch(r'[1-9][0-9]*',q['number']) is not None and
                          4<=len(q['options'])<=5, 'INVALID_MCQ_NUMBER_OR_OPTIONS')
                    numbered.append(int(q['number']))
            check(sorted(numbered)==list(range(1,len(numbered)+1)),'MCQ_NUMBER_SEQUENCE_CHANGED')
            check(len(numbered)==p['mcqCount'] and (len(questions)-len(numbered))==p['essayCount'],
                  'MCQ_ESSAY_COUNTS_INCONSISTENT')
            rows=[]
            for d in paper['sources']:
                role=d['role']
                check(role in ('VERIFY_Q','EXISTING_S','MISSING_S','EXISTING_M','MISSING_M'),
                      'UNEXPECTED_SOURCE_ROLE')
                source_identity(d['official_url'],role[-1])
                check(HEX64.fullmatch(d['source_sha256']),'UNVERIFIED_SOURCE_SHA')
                rows.append(d)
            paper_map[paperid]={'questions':questions,'mcq_count':len(numbered),
                                'official_url':paper['officialUrl'],'sources':rows,
                                'sha256':p['sha256']}
        check(len(paper_map)==449 and len(unique)==9399 and kind_counter=={'MCQ':8290,'ESSAY':1109},
              'INCOMPLETE_OR_MUTATED_SHARDS')
    # Every rechecked source is tied to the specific paper/role/hash recorded in shards.
    associated=[]
    for d in documents:
        for r in d['referenced_by']:
            pid=r['paper_id'];role=r['role']
            check(pid in paper_map and role in ('EXISTING_S','MISSING_S','EXISTING_M','MISSING_M'),
                  'SOURCE_REFERENCE_NOT_IN_SHARDS')
            found=[x for x in paper_map[pid]['sources'] if x['role']==role and
                   x['official_url']==d['url'] and x['source_sha256']==d['actual_sha256']]
            check(len(found)==1,'SOURCE_ASSOCIATION_MISSING_OR_DUPLICATED')
            rel='EXACT_EXAM_CLASS_SUBJECT_IDENTITY' if source_identity(d['url'])==source_identity(paper_map[pid]['official_url']) else 'CROSS_CLASS_ASSOCIATION_NOT_AUTOMATICALLY_EQUIVALENT'
            check(r['class_relation']==rel,'SOURCE_CLASS_RELATION_MISMATCH')
            associated.append((pid,role,d['url']))
    check(len(associated)==301,'DOCUMENT_ROLE_LINK_COUNT_FAILED')
    return report,documents,paper_map


def cache_pdf(doc, cache):
    """V4 cache: URL-SHA.json metadata plus PDF named by content SHA.
    Refuses symlinks and any metadata/content inconsistency. No network usage.
    """
    stamp=cache/(sha256(doc['url'].encode('utf-8'))+'.json')
    filename=cache/(doc['actual_sha256']+'.pdf')
    file_safe(stamp,100000)
    file_safe(filename,MAX_PDF_BYTES)
    meta=json.loads(stamp.read_text('utf-8'))
    check(meta.get('url')==doc['url'] and
          meta.get('actual_sha256')==doc['actual_sha256'] and
          meta.get('reference_sha256')==doc['reference_sha256'],'CACHE_METADATA_MISMATCH')
    check(sha_file(filename)==doc['actual_sha256'],'CACHE_PDF_FINGERPRINT_MISMATCH')
    raw=filename.read_bytes()
    check(len(raw)>100 and raw[:1024].lstrip().startswith(b'%PDF-'),'NOT_A_PDF')
    return raw


def typed_token(fragment,x,y,page):
    v=normalize(fragment).strip()
    if '\n' in v or len(v)>45:return None
    compact=re.sub(r'\s+','',v)
    if compact in ('題號','題次'):return {'x':x,'y':y,'page':page,'type':'nlabel','value':compact}
    if compact in ('答案','標準答案'):return {'x':x,'y':y,'page':page,'type':'alabel','value':compact}
    if compact in ('A','B','C','D','E','#'):return {'x':x,'y':y,'page':page,'type':'answer','value':compact}
    m=NUM_CELL.fullmatch(compact)
    if m:return {'x':x,'y':y,'page':page,'type':'number','value':int(m.group(1))}
    return None


def pdf_cell_rows(pages):
    rows=[]
    for page_index,page in enumerate(pages):
        cells=[]
        def visitor(fragment,cm,tm,font,size):
            if len(cells)>MAX_PDF_TOKENS:return
            try:
                x=cm[0]*tm[4]+cm[2]*tm[5]+cm[4]
                y=cm[1]*tm[4]+cm[3]*tm[5]+cm[5]
                if not(math.isfinite(x) and math.isfinite(y) and -100<x<3000 and -100<y<3000):return
                item=typed_token(fragment,round(float(x),2),round(float(y),2),page_index)
                if item:cells.append(item)
            except (ValueError,IndexError,TypeError,OverflowError):return
        page.extract_text(visitor_text=visitor)
        check(len(cells)<MAX_PDF_TOKENS,'PDF_TOO_MANY_LAYOUT_TOKENS')
        for cell in sorted(cells,key=lambda x:(-x['y'],x['x'])):
            if rows and rows[-1]['page']==page_index and abs(rows[-1]['y']-cell['y'])<=2.5:
                rows[-1]['cells'].append(cell)
            else:rows.append({'page':page_index,'y':cell['y'],'cells':[cell]})
    return rows


def parse_positioned(pages,expected):
    """Require labeled, aligned rows, no filling in blanks, no OCR assumptions."""
    pairs={};conflicts=set();markers=set();groups=0;rejected=0
    for page_index in range(len(pages)):
        rows=[row for row in pdf_cell_rows([pages[page_index]])]
        for i,head in enumerate(rows):
            labels=[x for x in head['cells'] if x['type']=='nlabel']
            numbers=[x for x in head['cells'] if x['type']=='number']
            if len(labels)!=1 or len(numbers)<3:continue
            nums=[x['value'] for x in numbers]
            if nums!=list(range(nums[0],nums[0]+len(nums))) or len(set(nums))!=len(nums):rejected+=1;continue
            useful=[x for x in numbers if 1<=x['value']<=expected]
            if not useful:continue
            steps=[b['x']-a['x'] for a,b in zip(numbers,numbers[1:])]
            if any(step<=9 or step>250 for step in steps):rejected+=1;continue
            bodies=[]
            for body in rows[i+1:]:
                dy=head['y']-body['y']
                if dy>35:break
                if not 5<=dy<=30:continue
                lab=[x for x in body['cells'] if x['type']=='alabel']
                if len(lab)==1 and abs(lab[0]['x']-labels[0]['x'])<=18:bodies.append(body)
            if len(bodies)!=1:rejected+=1;continue
            opts=[x for x in bodies[0]['cells'] if x['type']=='answer']
            if not opts or len(opts)>len(useful):rejected+=1;continue
            tolerance=min(18,max(8,min(steps)*.34))
            local={};broken=False
            for opt in opts:
                closest=sorted((abs(opt['x']-n['x']),n['value']) for n in useful)
                if (not closest or closest[0][0]>tolerance or
                    (len(closest)>1 and closest[1][0]-closest[0][0]<2) or
                    closest[0][1] in local):
                    broken=True;break
                local[closest[0][1]]=opt['value']
            if broken:rejected+=1;continue
            for n,key in local.items():
                if n in pairs:conflicts.add(n)
                pairs[n]=key
            groups+=1
    if conflicts:return {'candidates':{},'markers':[], 'complete':False,'coverage':0,'groups':groups,
                         'rejected_groups':rejected,'conflicts':sorted(conflicts)}
    markers=sorted(n for n,v in pairs.items() if v=='#')
    complete=set(pairs)==set(range(1,expected+1))
    return {'candidates':{str(n):v for n,v in sorted(pairs.items()) if v in 'ABCDE'},
            'markers':markers,'complete':complete,'coverage':len(pairs),'groups':groups,
            'rejected_groups':rejected,'conflicts':[]}


def parse_labeled_text(text,expected):
    """Accept only explicitly paired numeric rows, never a free-stream A B C sequence."""
    norm=normalize(text)
    vals={};conflict=False
    for line in norm.splitlines():
        m=re.fullmatch(r'\s*(?:第)?(\d{1,3})(?:題)?[.、)\s:：]+([A-E])\s*',line)
        if not m:continue
        n,key=int(m.group(1)),m.group(2)
        if not 1<=n<=expected:continue
        if n in vals and vals[n]!=key:conflict=True
        vals[n]=key
    lines=[l.strip() for l in norm.splitlines() if l.strip()]
    for i in range(len(lines)-1):
        nline=re.fullmatch(r'題(?:號|次)\s*[:：]?\s*((?:\d{1,3}\s+)+\d{1,3})',lines[i]);aline=re.fullmatch(r'(?:標準)?答案\s*[:：]?\s*((?:[A-E]\s+)+[A-E])',lines[i+1])
        if not(nline and aline):continue
        nums=[int(x) for x in nline.group(1).split()];keys=aline.group(1).split()
        if not nums or len(nums)!=len(keys) or len(set(nums))!=len(nums):continue
        for n,key in zip(nums,keys):
            if not 1<=n<=expected:conflict=True;break
            if n in vals and vals[n]!=key:conflict=True
            vals[n]=key
    return {'candidates':{str(n):v for n,v in sorted(vals.items())} if not conflict else {},
            'complete':not conflict and set(vals)==set(range(1,expected+1)),
            'conflicts':conflict}


def parse_special_notes(text,expected):
    norm=normalize(text);notes={};conflicts=set()
    for m in CORRECTION_RE.finditer(norm):
        n=int(m.group(1) or m.group(2))
        if n>expected or n<1:conflicts.add(n);continue
        keys=sorted(set((m.group(3),m.group(4))))
        if len(keys)!=2:continue
        if str(n) in notes and notes[str(n)]['choices']!=keys:conflicts.add(n)
        notes[str(n)]={'choices':keys,'textExcerpt':m.group()[:140], 'humanVerified':False}
    return notes,sorted(conflicts)


def parse_pdf(raw:bytes,expected:int,source_role:str):
    """No candidate accepted unless entire S/M grid is sequential and unambiguous."""
    from pypdf import PdfReader
    check(1<=expected<=100,'EXPECTED_COUNT_OUTSIDE_RANGE')
    reader=PdfReader(io.BytesIO(raw),strict=False)
    check(1<=len(reader.pages)<=MAX_PAGES and not reader.is_encrypted,'PDF_ENCRYPTED_OR_TOO_MANY_PAGES')
    text='\n'.join(p.extract_text() or '' for p in reader.pages)
    check(len(text)<=MAX_TEXT_CHARS,'PDF_TEXT_TOO_LARGE')
    grid=parse_positioned(reader.pages,expected)
    inline=parse_labeled_text(text,expected)
    notes,note_conflicts=parse_special_notes(text,expected)
    declared=[int(x) for x in DECLARED.findall(normalize(text))]
    count_issue=bool(declared and any(v!=expected for v in declared))
    overlap_conflicts=sorted(int(n) for n,v in grid['candidates'].items()
                             if n in inline['candidates'] and v!=inline['candidates'][n])
    issues=[]
    if grid['conflicts']:issues.append('DUPLICATE_OR_CONFLICTING_PDF_CELLS')
    if grid['rejected_groups']:issues.append('LAYOUT_ROWS_REJECTED')
    if inline['conflicts']:issues.append('TEXT_PAIRING_CONFLICT')
    if count_issue:issues.append('OFFICIAL_DECLARED_NUMBER_CONFLICT')
    if overlap_conflicts:issues.append('POSITION_TEXT_CONFLICT')
    if note_conflicts:issues.append('SPECIAL_NOTE_CONFLICT_OR_OUT_OF_RANGE')
    markers=set(grid['markers']);unresolved=sorted(markers-set(map(int,notes)))
    unanchored=sorted(set(map(int,notes))-markers)
    if unresolved:issues.append('UNRESOLVED_CHANGE_MARKER')
    if source_role=='S' and (markers or notes):issues.append('SPECIAL_MARKER_IN_STANDARD_SOURCE')
    if notes:issues.append('SPECIAL_CREDIT_REQUIRES_REVIEW')
    if source_role=='M' and unanchored:issues.append('SPECIAL_NOTE_WITHOUT_GRID_MARKER')
    # Mark text-only complete as candidate, but signal less certain method.
    candidate=grid['candidates'] if grid['complete'] else (inline['candidates'] if inline['complete'] else {})
    complete=(bool(candidate) and len(candidate)==expected and not grid['markers'] and
              not overlap_conflicts and not count_issue and not grid['conflicts'] and
              not inline['conflicts'] and not note_conflicts and not notes)
    # If a positioned grid contains some keyed cells and text parsing is separately complete,
    # do not allow a text-only promotion: the grid evidence disagrees in completeness.
    if inline['complete'] and grid['coverage'] and not grid['complete']:
        complete=False;issues.append('POSITIONAL_INCOMPLETE_TEXT_ONLY_NOT_APPROVED')
    if grid['rejected_groups']:complete=False
    # M correction grids can contain a # linked to special-credit notes. Never
    # convert # to an invented single letter, but retain all other aligned cells
    # as nonfinal inspection evidence even if the M grid is incomplete.
    positioned_preview=(grid['candidates'] if grid['complete'] and
                        not (grid['conflicts'] or grid['rejected_groups'] or count_issue or overlap_conflicts)
                        else {})
    if not complete:candidate={}
    if not candidate and not text.strip():issues.append('PDF_NO_EXTRACTABLE_TEXT')
    if not complete:issues.append('INCOMPLETE_OR_UNSUPPORTED_GRID')
    if complete and grid['complete']:method='PDF_POSITIONED_GRID_CANDIDATE'
    elif complete:method='EXPLICIT_NUMBER_TEXT_CANDIDATE'
    else:method='NO_SAFE_FULL_KEY'
    return {'status':'COMPLETE_CANDIDATE_NOT_FINAL' if complete else 'REQUIRES_REVIEW',
            'sourceRole':source_role,'expectedCount':expected,'evidenceMethod':method,
            'candidateKeys':candidate,
            'positionedNonFinalCellEvidence':positioned_preview if source_role=='M' else {},
            'positionedPairs':grid['coverage'],
            'positionedMarkers':grid['markers'], 'positionedGroups':grid['groups'],
            'rejectedPositionedGroups':grid['rejected_groups'],
            'specialNotesUnverified':notes,
            'issues':sorted(set(issues)),
            'pdfTextSha256':sha256(text.encode()),
            'finalAnswerVerified':False,'scoringEnabled':False,'publicationAllowed':False}


def make_rows(papers,documents,cache,limit=None):
    source_by_url={d['url']:d for d in documents}
    jobs=collections.defaultdict(list)
    for pid,p in papers.items():
        if p['mcq_count']==0:continue
        for source in p['sources']:
            if source['role'][-1] in ('S','M'):
                jobs[source['official_url']].append((pid,source))
    checked={}; errors=[]
    for n,(url,links) in enumerate(sorted(jobs.items()),1):
        d=source_by_url[url]
        # Format may depend on expected count. Conflicting expectations cannot share a key.
        counts={papers[pid]['mcq_count'] for pid,_ in links}
        if len(counts)!=1:
            checked[url]={'status':'COUNT_CONFLICT','issues':['MULTI_PAPER_COUNT_DISAGREEMENT'],
                          'candidateKeys':{},'sourceRole':d['source_type']}
        else:
            try:
                raw=cache_pdf(d,cache)
                result=parse_pdf(raw,counts.pop(),d['source_type'])
                checked[url]={**result,'url':url,'pdfSha256':d['actual_sha256'],
                              'statusFromV4':d['status'],'paperReferences':len(links)}
            except (OSError,ValueError,GateError,ImportError,RuntimeError,Exception) as e:
                checked[url]={'status':'REQUIRES_REVIEW','issues':['PDF_CACHE_OR_PARSER_ERROR'],
                              'reason':str(e)[:180], 'candidateKeys':{},'sourceRole':d['source_type'],
                              'url':url,'pdfSha256':d['actual_sha256']}
        if n%25==0 or n==len(jobs):print(f'  候審答案 PDF 已解析 {n}/{len(jobs)}',flush=True)
    questions=[];reviews=[];stats=collections.Counter()
    for pid in sorted(papers):
        p=papers[pid];items=sorted((q for q in p['questions'] if q['kind']=='MCQ'),key=lambda q:int(q['number']))
        if not items:continue
        sdocs=[s for s in p['sources'] if s['role'][-1]=='S']
        mdocs=[s for s in p['sources'] if s['role'][-1]=='M']
        qid=source_identity(p['official_url'])
        exact_s=[s for s in sdocs if source_identity(s['official_url'])==qid]
        crossed=any(source_identity(s['official_url'])!=qid for s in (sdocs+mdocs))
        s_ok=(len(sdocs)==1 and len(exact_s)==1 and checked.get(sdocs[0]['official_url'],{}).get('status')=='COMPLETE_CANDIDATE_NOT_FINAL')
        skeys=checked[sdocs[0]['official_url']]['candidateKeys'] if s_ok else {}
        for q in items:
            n=q['number'];num=int(n);issues=[]
            if crossed:issues.append('CROSS_CLASS_SOURCE_VARIANTS_NOT_MERGED')
            if len(sdocs)!=1:issues.append('MULTIPLE_S_SOURCE_VARIANTS')
            if not s_ok:issues.append('NO_UNAMBIGUOUS_COMPLETE_S_KEY')
            if mdocs:issues.append('CORRECTION_SOURCE_REQUIRES_FINAL_RULE_VALIDATION')
            if len(q['options'])==5:issues.append('FIVE_OPTION_PARTIAL_MARK_RULE_UNVERIFIED')
            if q['risks']:issues.append('ORIGINAL_QUESTION_RISK_STILL_PENDING')
            if not mdocs:issues.append('LATEST_M_NOT_PROVEN_ABSENT')
            # S candidate requires an exact one-to-one official class identity.
            proposed=skeys.get(n) if (s_ok and not crossed) else None
            if proposed and proposed not in 'ABCDE'[:len(q['options'])]:
                proposed=None;issues.append('OFFICIAL_KEY_OUTSIDE_OPTION_COUNT')
            # M source is a separate *non-final* correction candidate. Never
            # overwrite the S key, even where the two answer grids disagree.
            corrected=''; special=''
            if len(mdocs)==1 and not crossed and source_identity(mdocs[0]['official_url'])==qid:
                evidence=checked[mdocs[0]['official_url']]
                corrected=(evidence.get('candidateKeys') or evidence.get('positionedNonFinalCellEvidence') or {}).get(n,'')
                if corrected and corrected not in 'ABCDE'[:len(q['options'])]:
                    corrected='';issues.append('CORRECTION_KEY_OUTSIDE_OPTION_COUNT')
                special_notes=evidence.get('specialNotesUnverified',{})
                if n in special_notes:special=''.join(special_notes[n]['choices'])
            if proposed and corrected and proposed!=corrected:issues.append('S_AND_M_CANDIDATES_DIFFER_REVIEW')
            if special:issues.append('SPECIAL_CREDIT_NO_AUTOMATIC_SCORING')
            rows={'paper_id':pid,'question_id':q['id'],'number':num,
                  'choice_count':len(q['options']),
                  'published_S_candidate_not_final':proposed or '',
                  'corrected_M_candidate_not_final':corrected,
                  'special_M_choices_not_final':special,
                  'matched_S_url_sha256':sha256(sdocs[0]['official_url'].encode()) if len(sdocs)==1 else '',
                  'M_source_count':len(mdocs),'risk_codes':'|'.join(q['risks']),
                  'blockers':'|'.join(issues),
                  'candidate_status':'PUBLISHED_S_CANDIDATE_NOT_FINAL' if proposed else 'SOURCE_OR_LAYOUT_REVIEW_REQUIRED',
                  'final_answer_verified':'false','scoring_enabled':'false','publication_allowed':'false'}
            questions.append(rows)
            stats[rows['candidate_status']]+=1
        reviews.append({'paperId':pid,'mcqCount':len(items),'S_sourceCount':len(sdocs),
                        'M_sourceCount':len(mdocs),'crossClass':crossed,
                        'S_parseStatuses':[{'role':s['role'],'status':checked[s['official_url']]['status'],
                                            'issues':checked[s['official_url']].get('issues',[])} for s in sdocs],
                        'contentReviewComplete':False,'finalCorrectionsReviewed':False,
                        'publicationAllowed':False,'scoringEnabled':False})
    check(len(questions)==8290 and len(reviews)==246,'V5_CANDIDATE_OUTPUT_COUNT_MISMATCH')
    stats['source_documents_attempted']=len(checked)
    stats['source_documents_readable']=sum('evidenceMethod' in d for d in checked.values())
    stats['source_cache_or_parser_failures']=sum('PDF_CACHE_OR_PARSER_ERROR' in d.get('issues',[]) for d in checked.values())
    stats['source_documents_complete']=sum(d.get('status')=='COMPLETE_CANDIDATE_NOT_FINAL' for d in checked.values())
    stats['source_documents_require_review']=len(checked)-stats['source_documents_complete']
    stats['cross_class_papers']=sum(p['crossClass'] for p in reviews)
    stats['papers_with_S_candidate']=sum(len(p['S_parseStatuses'])==1 and p['S_parseStatuses'][0]['status']=='COMPLETE_CANDIDATE_NOT_FINAL' and not p['crossClass'] for p in reviews)
    return checked,reviews,questions,dict(stats)


def write_output(dest,summary,documents,papers,rows):
    check(not dest.exists(),'OUTPUT_EXISTS_REFUSE_OVERWRITE')
    dest.parent.mkdir(parents=True,exist_ok=True)
    def encode_csv(data):
        buf=io.StringIO(newline='')
        if not data:return b''
        w=csv.DictWriter(buf,fieldnames=list(data[0]),lineterminator='\n')
        w.writeheader();w.writerows(data)
        return buf.getvalue().encode('utf-8-sig')
    fd,tmp=tempfile.mkstemp(dir=dest.parent,prefix='.lexflow_v5_',suffix='.zip')
    os.close(fd)
    try:
        with zipfile.ZipFile(tmp,'w',zipfile.ZIP_DEFLATED,compresslevel=8) as z:
            z.writestr('v5_summary.json',jsondata(summary))
            z.writestr('v5_document_parse_status.json',jsondata(documents))
            z.writestr('v5_paper_review.json',jsondata(papers))
            z.writestr('v5_question_candidates_NOT_FINAL.csv',encode_csv(rows))
            z.writestr('README.txt',
              'PRIVATE Final98 V5: published S-key proposals ONLY. Not final corrected answers.\n'
              'No official scoring, backend import or publication permitted. S and M sources are separate.\n'
              'Cross-class sources cannot be merged; candidate table extraction may fail closed.\n'
              'All original question risks remain unresolved until separate content verification.\n')
        with zipfile.ZipFile(tmp) as z:
            check(z.testzip() is None,'V5_OUTPUT_ZIP_CORRUPT')
            v=json.loads(z.read('v5_summary.json'))
            check(v['publication_allowed'] is False and v['scoring_enabled'] is False
                  and v['final_answers_verified'] is False,'V5_OUTPUT_RELEASE_FLAG_INVALID')
        os.replace(tmp,dest)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)


def main(argv=None):
    p=argparse.ArgumentParser(description='V5 offline MOEX answer candidate parser. Never scores or publishes.')
    p.add_argument('--v4',type=Path)
    p.add_argument('--shards',type=Path)
    p.add_argument('--cache',type=Path,default=Path.home()/'LexFlow_Final98_V4_SourceCache')
    p.add_argument('--output',type=Path)
    args=p.parse_args(argv)
    download=Path.home()/'storage'/'downloads'
    if not download.is_dir():download=Path.home()
    def latest(glob):
        f=list(download.glob(glob))
        if glob.startswith('LexFlow_Final98_V4_AutoQA_'):
            f=[x for x in f if re.fullmatch(r'LexFlow_Final98_V4_AutoQA_\d{8}_\d{6}\.zip',x.name)]
        check(len(f)>0,'REQUIRED_INPUT_NOT_FOUND:'+glob)
        return max(f,key=lambda x:x.stat().st_mtime)
    try:
        v4=args.v4 or latest('LexFlow_Final98_V4_AutoQA_*.zip')
        shards=args.shards or latest('LexFlow_449_Shards_STAGING_*.zip')
        output=args.output or download/('LexFlow_Final98_V5_Candidates_'+dt.datetime.now().strftime('%Y%m%d_%H%M%S')+'.zip')
        print('[1/3] 核對原始 449 份試卷及 V4 來源證據…',flush=True)
        original,docs,papers=load_inputs(v4,shards)
        check(args.cache.is_dir() and not args.cache.is_symlink(),'V4_PDF_CACHE_NOT_FOUND_OR_UNSAFE')
        try:
            import pypdf  # dependency is installed once by the Termux launcher
        except ImportError as e:
            raise GateError('PYPDF_NOT_INSTALLED_RUN_TERMUX_INSTALLER') from e
        print(f'[2/3] 只解析已快取的 {len(docs)} 個 S/M PDF，不重新下載…',flush=True)
        parsed,reviews,rows,counts=make_rows(papers,docs,args.cache)
        summary={'schema':REPORT_SCHEMA,'generatedAtUTC':dt.datetime.now(dt.timezone.utc).isoformat(),
                 'v4_report_sha256':sha_file(v4),'shards_sha256':sha_file(shards),
                 'sourceDBSha256':DB_SHA,'input_pdf_sha256_matches':len(docs),
                 'expected_papers':449,'expected_questions':9399,'mcq_papers':246,'mcq_questions':8290,
                 'candidate_counts':counts,
                 'processing_status':('CACHE_ERRORS_REPORTED' if counts['source_cache_or_parser_failures'] else
                                      'CANDIDATES_EXTRACTED_NOT_FINAL' if counts.get('PUBLISHED_S_CANDIDATE_NOT_FINAL',0) else
                                      'NO_COMPLETE_ANSWER_GRIDS_REVIEW_REQUIRED'),
                 'machine_source_hash_verified':True,'question_text_human_reviewed':False,
                 'source_document_extract_is_not_final_correction':True,
                 'all_corrections_verified':False,'final_answers_verified':False,
                 'scoring_enabled':False,'publication_allowed':False,'formal_backend_import_allowed':False}
        print('[3/3] 匯出逐題候審答案、來源差異與疑義清單（正式計分仍鎖定）…',flush=True)
        write_output(output,summary,parsed,reviews,rows)
        print('✅ V5 離線候審證據處理完成（不是最終答案核准）',flush=True)
        if counts['source_cache_or_parser_failures']:
            print('⚠️ 來源快取／PDF 解析異常：',counts['source_cache_or_parser_failures'],'份。請查看報告，不代表已配對成功。',flush=True)
        print('配對統計：',json.dumps(counts,ensure_ascii=False),flush=True)
        print('🔒 未核准任何官方答案，沒有修改正式題庫或作答紀錄',flush=True)
        print('報告：',output,flush=True)
        return 0
    except (GateError,OSError,ValueError,KeyError,TypeError,zipfile.BadZipFile,ImportError) as e:
        print('⛔ 安全停止：'+str(e),file=sys.stderr,flush=True)
        return 2

if __name__=='__main__':sys.exit(main())
