#!/usr/bin/env python3
"""LexFlow Final98 V6, offline targeted S / M *candidate evidence* reconciliation.

Uses existing immutable V4/V5/shards ZIPs and (optionally) the existing private
S/M PDF cache. No network, no backend import, no official scoring or publishing.

The original S answer is *never* overwritten by an M correction proposal.
Multi-class exam variants remain separate, even if their PDF SHA is equal.
"""
from __future__ import annotations
import argparse
import collections
import csv
import datetime as dt
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import unicodedata
import zipfile

import final98_answer_candidate_v5 as base

V6_SCHEMA='lexflow.final98.targeted.answerevidence.v6'
EXPECTED_V5_SHA='0fc3b5370951213b2d83c4a7a247a13518d327a83ed94ff0039a0f555119093e'
HEX64=re.compile(r'^[a-f0-9]{64}$')
SAFE_KINDS={'SINGLE_S_CANDIDATE_NOT_FINAL','MULTI_S_CANDIDATE_NOT_FINAL','S_UNRESOLVED'}
PDF_NOTE_ALL=re.compile(r'第\s*(\d{1,3})\s*題\s*(?:一律|全部|均|皆|不論作答均|不論答案均)\s*(?:給分|計分|得分)')
PDF_NOTE_VARIANTS=re.compile(r'第\s*(\d{1,3})\s*題\s*答\s*([A-E])\s*(?:或|、|及|和|／|/)\s*([A-E])\s*者?\s*(?:均|都)?\s*(?:給分|計分|得分)')
PDF_NOTE_REPLACEMENT=re.compile(r'第\s*(\d{1,3})\s*題\s*(?:答案)?\s*(?:由|從)\s*([A-E])\s*(?:改為|更正為|修正為)\s*([A-E])')
DECLARED_SINGLE=re.compile(r'單選題數\s*[:：]\s*60\s*題\s*[(（]\s*第\s*1\s*[~～\-]\s*60\s*題\s*[)）]')
DECLARED_MULTI=re.compile(r'複選題數\s*[:：]\s*10\s*題\s*[(（]\s*第\s*61\s*[~～\-]\s*70\s*題\s*[)）]')


def require(ok,code):
    if not ok:raise base.GateError(code)


def norm(s):return unicodedata.normalize('NFKC',str(s or ''))


def v5_report_read(path,v4,shards,papers,docs):
    base.file_safe(path,16*1024*1024)
    with zipfile.ZipFile(path) as z:
        require(z.testzip() is None,'V5_ZIP_BAD')
        require(set(z.namelist())=={'v5_summary.json','v5_document_parse_status.json',
               'v5_paper_review.json','v5_question_candidates_NOT_FINAL.csv','README.txt'},'V5_UNEXPECTED_CONTENT')
        summary=json.loads(z.read('v5_summary.json'))
        parsed=json.loads(z.read('v5_document_parse_status.json'))
        reviews=json.loads(z.read('v5_paper_review.json'))
        rows=list(csv.DictReader(io.StringIO(z.read('v5_question_candidates_NOT_FINAL.csv').decode('utf-8-sig'))))
    require(summary.get('schema')=='lexflow.final98.answer.candidates.v5' and
            summary.get('sourceDBSha256')==base.DB_SHA and
            summary.get('v4_report_sha256')==base.sha_file(v4) and
            summary.get('shards_sha256')==base.sha_file(shards) and
            summary.get('expected_papers')==449 and summary.get('mcq_questions')==8290 and
            summary.get('input_pdf_sha256_matches')==301 and
            summary.get('final_answers_verified') is False and
            summary.get('scoring_enabled') is False and
            summary.get('publication_allowed') is False and
            summary.get('formal_backend_import_allowed') is False,'V5_SOURCE_OR_GATE_MISMATCH')
    require(len(parsed)==301 and len(rows)==8290 and len(reviews)==246,'V5_ROWS_MISSING')
    doc_map={d['url']:d for d in docs}
    for url,rec in parsed.items():
        require(url in doc_map and rec.get('url')==url and
                rec.get('pdfSha256')==doc_map[url]['actual_sha256'] and
                rec.get('sourceRole')==doc_map[url]['source_type'] and
                rec.get('finalAnswerVerified') is False and
                rec.get('scoringEnabled') is False and rec.get('publicationAllowed') is False,
                'V5_SOURCE_DOC_MISMATCH')
        require(rec.get('status') in {'COMPLETE_CANDIDATE_NOT_FINAL','REQUIRES_REVIEW'},'V5_UNKNOWN_DOC_STATUS')
        if rec['status']=='COMPLETE_CANDIDATE_NOT_FINAL':
            expected=rec.get('expectedCount');keys=rec.get('candidateKeys',{})
            require(type(expected) is int and len(keys)==expected and
                    set(keys)=={str(i) for i in range(1,expected+1)} and
                    all(isinstance(x,str) and re.fullmatch('[A-E]',x) for x in keys.values()),
                    'V5_PDF_PARSED_KEYS_UNTRUSTED')
        else:
            require(not rec.get('candidateKeys'),'V5_REVIEW_WITH_KEYS')
    ids={q['id']: (pid,q) for pid,p in papers.items() for q in p['questions'] if q['kind']=='MCQ'}
    require(len(ids)==8290,'SHARDS_MCQ_ID_ERROR')
    seen=set();n_s=0;n_b=0
    for r in rows:
        qid=r.get('question_id')
        require(qid in ids and qid not in seen,'V5_QUESTION_ID_MISMATCH');seen.add(qid)
        pid,q=ids[qid]
        require(r.get('paper_id')==pid and r.get('number')==q['number'] and
                int(r.get('choice_count',0))==len(q['options']) and
                r.get('final_answer_verified')=='false' and r.get('scoring_enabled')=='false' and
                r.get('publication_allowed')=='false','V5_QUESTION_METADATA_CHANGED')
        s=r.get('published_S_candidate_not_final','')
        require(not s or (len(s)==1 and s in 'ABCDE'[:len(q['options'])]),'V5_S_BAD')
        if s:
            ss=[d for d in papers[pid]['sources'] if d['role'].endswith('_S')]
            eq=[d for d in ss if base.source_identity(d['official_url'])==base.source_identity(papers[pid]['official_url'])]
            require(len(eq)==1 and len(ss)==1 and
                    parsed[eq[0]['official_url']]['candidateKeys'].get(q['number'])==s and
                    r.get('matched_S_url_sha256')==base.sha256(eq[0]['official_url'].encode()),
                    'V5_S_CANDIDATE_WITHOUT_SOURCE_PROOF')
            n_s+=1
        else:n_b+=1
    require(len(seen)==8290 and n_s==7750 and n_b==540,'V5_BASELINE_COUNTS_CHANGED')
    paperids={p['paperId'] for p in reviews}
    require(len(paperids)==len(reviews)==246,'V5_PAPER_REVIEW_DUPLICATES')
    return summary,parsed,rows


def note_actions(raw_text,expected,markers):
    """Machine-only literal M note classifications. Never creates scored keys.

    Only a numbered note matching an existing # cell can be retained. Other
    notes, duplicates, and any unknown marker remain explicit blockers.
    """
    t=norm(raw_text)
    # Parsed notes only after actual 備註 field where possible; Chinese PDF
    # extract_text sometimes places the note near the end after the grid.
    candidates=collections.defaultdict(list)
    for m in PDF_NOTE_ALL.finditer(t):
        candidates[int(m.group(1))].append({'type':'ALL_CREDIT_CANDIDATE_NOT_FINAL','evidence':m.group()[:130]})
    for m in PDF_NOTE_VARIANTS.finditer(t):
        a,b=m.group(2),m.group(3)
        if a!=b:candidates[int(m.group(1))].append({'type':'ACCEPTED_VARIANTS_CANDIDATE_NOT_FINAL',
              'choices':''.join(sorted((a,b))),'evidence':m.group()[:130]})
    for m in PDF_NOTE_REPLACEMENT.finditer(t):
        a,b=m.group(2),m.group(3)
        if a!=b:candidates[int(m.group(1))].append({'type':'REPLACEMENT_CANDIDATE_NOT_FINAL',
              'before':a,'after':b,'evidence':m.group()[:130]})
    marker_set=set(markers)
    recognized={}
    for number in sorted(marker_set):
        if not 1<=number<=expected:continue
        options=candidates.get(number,[])
        # Multiple overlapping parsers finding the same excerpt must agree.
        unique={(x['type'],x.get('choices'),x.get('before'),x.get('after')):x for x in options}
        if len(unique)==1: recognized[str(number)]=next(iter(unique.values()))
    unresolved=sorted(marker_set-set(map(int,recognized)))
    without_marker=sorted(n for n in candidates if n not in marker_set)
    return {'recognized':recognized,'unresolved_markers':unresolved,
            'notes_without_marker':without_marker,
            'conflict_markers':sorted(n for n in marker_set if len({(x['type'],x.get('choices'),x.get('before'),x.get('after')) for x in candidates.get(n,[])})>1)}


def _cell_token(fragment,x,y,page):
    token=norm(fragment).strip()
    if '\n' in token or len(token)>50:return None
    compact=re.sub(r'\s+','',token)
    if compact in {'題號','題次'}: typ='header';val=compact
    elif compact in {'答案','標準答案'}:typ='answer_label';val=compact
    else:
        nm=re.fullmatch(r'第(\d{1,3})題',compact)
        if nm:typ='number';val=int(nm.group(1))
        elif re.fullmatch('[A-E]{1,5}',compact) and len(set(compact))==len(compact):
            typ='key';val=''.join(sorted(compact))
        else:return None
    return {'page':page,'x':x,'y':y,'type':typ,'value':val}


def extract_mixed_layout(pages):
    """Read aligned PDF table cells without concatenating text extraction order."""
    all_rows=[]
    for page_no,page in enumerate(pages):
        cells=[]
        def visitor(text,cm,tm,font,fontsize):
            if len(cells)>7000:return
            try:
                x=cm[0]*tm[4]+cm[2]*tm[5]+cm[4]
                y=cm[1]*tm[4]+cm[3]*tm[5]+cm[5]
                if not(-100<x<3000 and -100<y<3000):return
                c=_cell_token(text,round(float(x),2),round(float(y),2),page_no)
                if c:cells.append(c)
            except (IndexError,TypeError,ValueError,OverflowError):return
        page.extract_text(visitor_text=visitor)
        require(len(cells)<7000,'PDF_TOKEN_LIMIT')
        rows=[]
        for cell in sorted(cells,key=lambda c:(-c['y'],c['x'])):
            if rows and abs(rows[-1]['y']-cell['y'])<=2.5:
                rows[-1]['cells'].append(cell)
            else:rows.append({'y':cell['y'],'cells':[cell],'page':page_no})
        all_rows.extend(rows)
    return all_rows


def parse_mixed_70_pages(pages, raw_text):
    """Only 60 single + 10 five-choice multiple. Never infer missing cells.

    Expected headings 1..70 and exactly one directly corresponding answer cell
    per heading. Additional blank template rows 71..100 are ignored.
    """
    text=norm(raw_text)
    require(DECLARED_SINGLE.search(text) is not None and DECLARED_MULTI.search(text) is not None,
            'MIXED_OFFICIAL_COUNT_DECLARATIONS_MISSING')
    rows=extract_mixed_layout(pages)
    found={};rejected=[];groups=[]
    for i,head in enumerate(rows):
        headers=[x for x in head['cells'] if x['type']=='header']
        nums=[x for x in head['cells'] if x['type']=='number']
        if len(headers)!=1 or len(nums)<3:continue
        nums=sorted(nums,key=lambda x:x['x'])
        values=[x['value'] for x in nums]
        if values!=list(range(values[0],values[0]+len(values))) or len(values)!=len(set(values)):
            rejected.append(('HEADER',values[:3]));continue
        relevant=[c for c in nums if 1<=c['value']<=70]
        if not relevant:continue
        xs=[c['x'] for c in nums]
        steps=[b-a for a,b in zip(xs,xs[1:])]
        if not steps or any(d<=9 or d>250 for d in steps):
            rejected.append(('PITCH',values[:3]));continue
        matching=[]
        for row in rows[i+1:]:
            if row['page']!=head['page']:break
            dy=head['y']-row['y']
            if dy>40:break
            if not 5<=dy<=30:continue
            labels=[x for x in row['cells'] if x['type']=='answer_label']
            if len(labels)==1 and abs(labels[0]['x']-headers[0]['x'])<=18:
                matching.append(row)
        if len(matching)!=1:
            rejected.append(('ANSWER_ROW',values[:3]));continue
        keys=[x for x in matching[0]['cells'] if x['type']=='key']
        if len(keys)!=len(relevant):
            rejected.append(('KEY_COUNT',values[:3]));continue
        tolerance=min(18,max(8,min(steps)*.34))
        local={}
        for key in keys:
            dist=sorted((abs(key['x']-n['x']),n['value']) for n in relevant)
            if not dist or dist[0][0]>tolerance or (len(dist)>1 and dist[1][0]-dist[0][0]<2) or dist[0][1] in local:
                local={};break
            n=dist[0][1];val=key['value']
            if n<=60 and (len(val)!=1 or val not in 'ABCD'):
                local={};break
            if 61<=n<=70 and (not 1<=len(val)<=5 or any(a not in 'ABCDE' for a in val)):
                local={};break
            local[n]=val
        if len(local)!=len(relevant) or any(n in found for n in local):
            rejected.append(('COLLISION',values[:3]));continue
        found.update(local)
        groups.append({'first':values[0],'last':values[-1],'length':len(local)})
    require(not rejected,'MIXED_70_LAYOUT_AMBIGUOUS:'+str(rejected[:2]))
    require(set(found)==set(range(1,71)),'MIXED_70_HAS_MISSING_QUESTION_CELLS')
    return {'keys':{str(n):found[n] for n in range(1,71)},
            'single':60,'multiple':10,'aligned_groups':len(groups),
            'machine_only':True,'final_answer_verified':False,'scoring_enabled':False}


def parse_mixed_70_pdf(data):
    from pypdf import PdfReader
    reader=PdfReader(io.BytesIO(data),strict=False)
    require(not reader.is_encrypted and len(reader.pages) in (1,2),'MIXED_PDF_PAGE_COUNT_UNEXPECTED')
    page_text='\n'.join(page.extract_text() or '' for page in reader.pages)
    return parse_mixed_70_pages(reader.pages,page_text)


def collect_s_candidates(papers,parsed,cache,doc_by_url):
    """Q exact-class S only; never use other classes as the selected key."""
    result={};variant_checks=[];read_pdfs={};cache_warnings=[]
    for pid,p in papers.items():
        if not p['mcq_count']:continue
        sdocs=[x for x in p['sources'] if x['role'][-1]=='S']
        identity=base.source_identity(p['official_url'])
        exact=[x for x in sdocs if base.source_identity(x['official_url'])==identity]
        entry={'paper_id':pid,'source_count':len(sdocs),'exact_class_s_count':len(exact),
               'selected_url':'','other_class_sources':[], 'candidateKeys':{},
               'evidence_method':'NONE','status':'NO_UNAMBIGUOUS_S',
               'gate':'NOT_FINAL_NOT_FOR_SCORING'}
        for other in sdocs:
            if other not in exact:
                entry['other_class_sources'].append({'url':other['official_url'],
                    'pdf_sha256':other['source_sha256'],'identity':base.source_identity(other['official_url'])})
        if len(exact)==1:
            doc=exact[0];u=doc['official_url'];e=parsed[u]
            entry['selected_url']=u
            entry['selected_source_sha256']=doc['source_sha256']
            if e['status']=='COMPLETE_CANDIDATE_NOT_FINAL' and len(e['candidateKeys'])==p['mcq_count']:
                entry['candidateKeys']=dict(e['candidateKeys'])
                entry['evidence_method']='EXACT_CLASS_V5_COMPLETE_GRID'
                entry['status']='S_EXACT_CLASS_CANDIDATES_ONLY'
            elif p['mcq_count']==70:
                if cache is None:
                    entry['status']='MIXED_70_CACHE_REQUIRES_TERMUX'
                else:
                    try:
                        pdf=base.cache_pdf(doc_by_url[u],cache)
                        parsed_mixed=parse_mixed_70_pdf(pdf)
                        entry['candidateKeys']=parsed_mixed['keys']
                        entry['status']='S_EXACT_CLASS_MIXED_70_CANDIDATES_ONLY'
                        entry['evidence_method']='TWO_SEGMENT_POSITIONED_GRID_WITH_DECLARED_60_10'
                        read_pdfs[base.sha256(pdf)]=parsed_mixed
                    except Exception as e2:
                        entry['status']='MIXED_70_NEEDS_REVIEW'
                        entry['error']=str(e2)[:160]
                        cache_warnings.append({'paper_id':pid,'code':'MIXED_PARSE_FAILED','detail':str(e2)[:160]})
        # Different source URLs may have the same PDF digest. Keep every variant
        # for traceability; never silently replace the chosen official class.
        if len(sdocs)>1:
            hashes={x['source_sha256'] for x in sdocs}
            entry['all_class_pdf_bytes_equivalent']=len(hashes)==1
            variant_checks.append({'paper_id':pid,'exact_count':len(exact),
                 'all_variant_pdfs_same_sha':len(hashes)==1,'variants':len(sdocs)})
        result[pid]=entry
    return result,variant_checks,read_pdfs,cache_warnings


def collect_m_source(papers,parsed,cache,doc_by_url):
    """Read 40 M PDF notes only when already available in private V4 cache."""
    result={};warnings=[]
    for pid,p in papers.items():
        if not p['mcq_count']:continue
        qident=base.source_identity(p['official_url'])
        md=[s for s in p['sources'] if s['role'][-1]=='M']
        exact=[x for x in md if base.source_identity(x['official_url'])==qident]
        record={'paper_id':pid,'M_count':len(md),'M_exact_class_count':len(exact),
                'selected_url':'','markers':[],'positioned_M_keys_NOT_FINAL':{},
                'notes_NOT_FINAL':{},'unresolved_markers':[],
                'M_notes_without_marker':[],'M_status':'NO_RECORDED_M','machine_only':True}
        if len(exact)==1:
            src=exact[0];u=src['official_url'];doc=parsed[u]
            record['selected_url']=u
            record['M_source_sha256']=src['source_sha256']
            record['markers']=doc.get('positionedMarkers',[])
            record['positioned_M_keys_NOT_FINAL']=doc.get('positionedNonFinalCellEvidence',{})
            record['M_status']='M_PRESENT_CORRECTIONS_NOT_FINAL'
            # Preserve the 21 V5 special-credit note candidates already derived
            # from these exact SHA-matched original M documents. Unrecognized #
            # positions remain blocked; nothing is deemed final or scorable.
            baseline={}
            for n,item in (doc.get('specialNotesUnverified') or {}).items():
                require(str(n).isdigit() and int(n) in record['markers'],'M_V5_NOTE_WITHOUT_MARKER')
                choice=item.get('choices')
                require(isinstance(choice,list) and len(choice)==2 and len(set(choice))==2 and
                        all(isinstance(x,str) and x in 'ABCDE' for x in choice),'M_V5_NOTE_INVALID')
                baseline[str(n)]={'type':'ACCEPTED_VARIANTS_CANDIDATE_NOT_FINAL',
                    'choices':''.join(sorted(choice)),
                    'evidence':item.get('textExcerpt','')[:130],
                    'origin':'V5_SHA_PINNED_PDF_CANDIDATE'}
            record['notes_NOT_FINAL']=baseline
            record['unresolved_markers']=sorted(set(record['markers'])-set(map(int,baseline)))
            if cache is not None:
                try:
                    from pypdf import PdfReader
                    blob=base.cache_pdf(doc_by_url[u],cache)
                    reader=PdfReader(io.BytesIO(blob),strict=False)
                    require(len(reader.pages)<=30 and not reader.is_encrypted,'M_PDF_UNSAFE')
                    plaintext='\n'.join(page.extract_text() or '' for page in reader.pages)
                    actions=note_actions(plaintext,p['mcq_count'],record['markers'])
                    merged=dict(baseline)
                    conflicts=list(actions['conflict_markers'])
                    for n,proposed in actions['recognized'].items():
                        prior=baseline.get(n)
                        if prior and (prior['type']!=proposed['type'] or
                                     prior.get('choices')!=proposed.get('choices')):
                            conflicts.append(int(n))
                            merged.pop(n,None)
                        elif not prior:merged[n]={**proposed,'origin':'V6_CACHED_PDF_TEXT_PROPOSAL'}
                    for n in conflicts:merged.pop(str(n),None)
                    record['notes_NOT_FINAL']=merged
                    record['unresolved_markers']=sorted(set(record['markers'])-set(map(int,merged)))
                    record['M_notes_without_marker']=actions['notes_without_marker']
                    record['M_note_conflicts']=sorted(set(conflicts))
                    if conflicts or actions['notes_without_marker']:
                        record['M_status']='M_NOTES_AMBIGUOUS'
                    elif not record['unresolved_markers']:
                        record['M_status']='M_CHANGE_MARKERS_ALL_ACCOUNTED_CANDIDATES'
                    else:record['M_status']='M_CHANGE_MARKER_INCOMPLETE'
                except Exception as exc:
                    warnings.append({'paper_id':pid,'code':'M_NOTE_READ_FAILED','detail':str(exc)[:160]})
                    record['M_status']='M_NOTE_PDF_READ_FAILED'
        elif md:
            record['M_status']='M_CLASS_NOT_UNIQUELY_BOUND'
        result[pid]=record
    return result,warnings


def create_rows(v5rows,papers,sproofs,mproofs):
    rows=[];audit=collections.Counter();recovered=[]
    for original in v5rows:
        row=dict(original);pid=row['paper_id'];number=row['number'];n=int(number)
        q=next(x for x in papers[pid]['questions'] if x['id']==row['question_id'])
        s=sproofs[pid];m=mproofs[pid]
        proposed=s['candidateKeys'].get(number,'')
        require(not proposed or (1<=len(proposed)<=len(q['options']) and
                 all(a in 'ABCDE'[:len(q['options'])] for a in proposed) and
                 len(set(proposed))==len(proposed)),'PROPOSED_KEY_OUTSIDE_QUESTION_OPTIONS')
        # No replacement of V5 original S: V6 holds its own strictly provisional field.
        if row['published_S_candidate_not_final']:
            require(row['published_S_candidate_not_final']==proposed,'V5_AND_V6_S_DISAGREE')
            status='V5_PRESERVED_S_NOT_FINAL'
        elif proposed:
            status='EXACT_CLASS_S_RECOVERED_NOT_FINAL'
            recovered.append(row['question_id'])
        else:status='S_STILL_UNRESOLVED'
        note=m['notes_NOT_FINAL'].get(number)
        mkey=m['positioned_M_keys_NOT_FINAL'].get(number,'')
        if mkey and len(mkey)!=1:mkey=''
        problems=[]
        if m['M_count'] and m['M_exact_class_count']!=1:problems.append('M_CLASS_ASSOCIATION_UNRESOLVED')
        if n in m['unresolved_markers']:problems.append('M_MARKER_WITHOUT_UNAMBIGUOUS_NOTE')
        if n in m['M_notes_without_marker']:problems.append('M_NOTE_NOT_BOUND_TO_MARKER')
        if mkey and proposed and mkey!=proposed:problems.append('S_M_GRID_DIFFERENCE_NEEDS_REVIEW')
        if note:problems.append('M_SPECIAL_NOTE_CANDIDATE_NOT_FINAL')
        if len(q['options'])==5:problems.append('FIVE_OPTION_RULE_PENDING')
        if not m['M_count']:problems.append('LATEST_CORRECTION_ABSENCE_NOT_PROVEN')
        if q['risks']:problems.append('ORIGINAL_CONTENT_RISKS_PENDING')
        if not proposed:problems.append('S_LAYOUT_OR_IDENTITY_UNRESOLVED')
        note_kind=note['type'] if note else ''
        row.update({'V6_S_candidate_NOT_FINAL':proposed,
           'V6_S_candidate_evidence':s['evidence_method'],
           'V6_S_candidate_status':status,
           'V6_S_selected_class_url_sha256':base.sha256(s['selected_url'].encode()) if s['selected_url'] else '',
           'V6_M_positioned_grid_NOT_FINAL':mkey,
           'V6_M_special_note_kind_NOT_FINAL':note_kind,
           'V6_M_special_note_detail_NOT_FINAL':json.dumps(note,ensure_ascii=False,sort_keys=True) if note else '',
           'V6_additional_blockers':'|'.join(problems),
           'V6_final_answer_verified':'false','V6_scoring_enabled':'false','V6_publication_allowed':'false'})
        rows.append(row)
        audit['V6_CANDIDATE']+=bool(proposed)
        audit['V6_UNRESOLVED']+=not bool(proposed)
        audit['V6_NEW_CANDIDATES']+=bool(proposed) and not bool(original['published_S_candidate_not_final'])
        audit['V6_MULTI']+=bool(proposed) and len(proposed)>1
        audit['V6_S_M_GRID_DIFF']+=('S_M_GRID_DIFFERENCE_NEEDS_REVIEW' in problems)
        audit['V6_M_NOTE']+=bool(note)
        audit['V6_M_MARKER_UNRESOLVED']+=('M_MARKER_WITHOUT_UNAMBIGUOUS_NOTE' in problems)
    require(len(rows)==8290 and len({r['question_id'] for r in rows})==8290,'V6_OUTPUT_QUESTIONS_INVALID')
    return rows,dict(audit),recovered


def write_output(output,summary,rows,sources,msources):
    require(not output.exists(),'OUTPUT_EXISTS_REFUSE_OVERWRITE')
    output.parent.mkdir(parents=True,exist_ok=True)
    buf=io.StringIO(newline='')
    w=csv.DictWriter(buf,fieldnames=list(rows[0]),lineterminator='\n')
    w.writeheader();w.writerows(rows)
    fd,tmp=tempfile.mkstemp(prefix='.lexflow_v6_',suffix='.zip',dir=str(output.parent));os.close(fd)
    try:
        with zipfile.ZipFile(tmp,'w',zipfile.ZIP_DEFLATED,compresslevel=8) as z:
            z.writestr('v6_summary.json',base.jsondata(summary))
            z.writestr('v6_question_candidates_NOT_FINAL.csv',buf.getvalue().encode('utf-8-sig'))
            z.writestr('v6_S_exact_class_sources.json',base.jsondata(sources))
            z.writestr('v6_M_correction_notes_NOT_FINAL.json',base.jsondata(msources))
            z.writestr('README.txt',
              'LexFlow Final98 V6: PRIVATE candidate evidence only. No final answer certification.\n'
              'Original V5 S candidates unchanged. New proposals must match the exact exam/class/subject/part Q identity.\n'
              'Mixed 60 single plus 10 multi keys are distinct unscored evidence types.\n'
              'M notes and grids are separate unverified evidence, never auto-overwrite published S.\n'
              'No private PDF bytes, question text or personal answers are included.\n')
        with zipfile.ZipFile(tmp) as z:
            require(z.testzip() is None,'OUTPUT_CORRUPT')
            v=json.loads(z.read('v6_summary.json'))
            require(v['publication_allowed'] is False and v['official_scoring_enabled'] is False and
                    v['final_answers_verified'] is False and v['production_import_allowed'] is False,'OUTPUT_GATES')
        os.replace(tmp,output)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)


def main(args=None):
    cli=argparse.ArgumentParser(description='V6: targeted SHA-pinned S/M evidence, no score or publication')
    cli.add_argument('--v4',type=Path,required=True)
    cli.add_argument('--v5',type=Path,required=True)
    cli.add_argument('--shards',type=Path,required=True)
    cli.add_argument('--cache',type=Path,help='Existing V4 PDF cache, no network (optional for report-only)')
    cli.add_argument('--output',type=Path,required=True)
    a=cli.parse_args(args)
    try:
        require(a.cache is None or (a.cache.is_dir() and not a.cache.is_symlink()),'CACHE_UNSAFE_OR_MISSING')
        _,documents,papers=base.load_inputs(a.v4,a.shards)
        _,parsed,rows=v5_report_read(a.v5,a.v4,a.shards,papers,documents)
        byurl={r['url']:r for r in documents}
        sp,variants,read_pdfs,warnings=collect_s_candidates(papers,parsed,a.cache,byurl)
        mp,other_warnings=collect_m_source(papers,parsed,a.cache,byurl)
        rows_v6,counts,recovered=create_rows(rows,papers,sp,mp)
        counts['documents_reread_from_cache']=len(read_pdfs)+sum(bool(x['selected_url']) and a.cache is not None for x in mp.values())
        counts['M_note_all_credit_candidates']=sum(note['type']=='ALL_CREDIT_CANDIDATE_NOT_FINAL' for m in mp.values() for note in m['notes_NOT_FINAL'].values())
        counts['M_note_variant_candidates']=sum(note['type']=='ACCEPTED_VARIANTS_CANDIDATE_NOT_FINAL' for m in mp.values() for note in m['notes_NOT_FINAL'].values())
        counts['M_note_replacement_candidates']=sum(note['type']=='REPLACEMENT_CANDIDATE_NOT_FINAL' for m in mp.values() for note in m['notes_NOT_FINAL'].values())
        summary={'schema':V6_SCHEMA,'generation_utc':dt.datetime.now(dt.timezone.utc).isoformat(),
             'db_sha256':base.DB_SHA,'v4_sha256':base.sha_file(a.v4),'v5_sha256':base.sha_file(a.v5),
             'shards_sha256':base.sha_file(a.shards), 'mcq_count':8290,'paper_count':449,
             'cross_class_papers':len(variants),'cross_class_notes':'EXACT_CLASS_ONLY_OTHER_CLASS_VARIANTS_NOT_MERGED',
             'candidate_counts':counts, 'unresolved_S_question_ids':[r['question_id'] for r in rows_v6 if not r['V6_S_candidate_NOT_FINAL']],
             'recovered_count':len(recovered),
             'warnings':warnings+other_warnings,
             'source_pdf_sha256_validated_by_v4_v5':True,
             'all_m_newly_verified_final':False,
             'question_text_review_complete':False,'final_answers_verified':False,
             'publication_allowed':False,'official_scoring_enabled':False,'production_import_allowed':False}
        write_output(a.output,summary,rows_v6,sp,mp)
        print('✅ V6 全卷回填完成：'+str(counts['V6_CANDIDATE'])+'/8,290 個非最終候審值')
        print('  新增精確類科來源候審值：'+str(counts['V6_NEW_CANDIDATES']))
        print('  尚未配對：'+str(counts['V6_UNRESOLVED']))
        print('  更正來源候選說明：'+str(counts['V6_M_NOTE'])+', 未解 #：'+str(counts['V6_M_MARKER_UNRESOLVED']))
        print('🔒 正式答案、計分與主系統發布繼續鎖定。報告：'+str(a.output))
        return 0
    except (base.GateError,OSError,ValueError,KeyError,TypeError,zipfile.BadZipFile,ImportError) as exc:
        print('⛔ 安全停止：'+str(exc),file=sys.stderr)
        return 2

if __name__=='__main__':sys.exit(main())
