#!/usr/bin/env python3
"""Offline, append-only quality previews for WHOLE MOEX papers.

Consumes existing V0.4 official-source reports (no browsing/private data),
keeps original Q/S/M candidates and report byte-for-byte intact.
Outputs only UNVERIFIED evidence, never enables official scoring/publication.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import io
import json
import math
from pathlib import Path
import re
import sys
import unicodedata
from urllib.parse import parse_qs, urlsplit

SCHEMA = 'lexflow.moex.whole-paper-quality-overlay.v1'
REVIEW_SCHEMA = 'lexflow.moex.whole-paper-review.v1'
MAX_SOURCE_BYTES = 4_000_000
MAX_TEXT_BYTES = 800_000
MAX_PDF_BYTES = 15_000_000
MAX_QUESTIONS = 300
_UNVERIFIED = {
    'publication_allowed': False,
    'scoring_enabled': False,
    'human_quality_gate_satisfied': False,
    'final_answer_verified': False,
    'options_verified': False,
    'question_text_verified': False,
}


class OverlayError(ValueError):
    pass


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def normalize_label(value: str) -> str:
    """Identity check only: never change the original official title."""
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', value or ''))


def title_evidence(source_title: str, raw_text: str) -> dict:
    line = re.search(r'(?m)^[ \t]*科[ \t]*目[ \t]*[:：][ \t]*(.{1,220})\s*$', raw_text)
    seen = (line.group(1).strip() if line else '')
    return {'official_name_unchanged': source_title, 'pdf_label_unverified': seen,
            'match_after_NFKC': bool(seen and normalize_label(seen)==normalize_label(source_title)),
            'visual_check_needed': True}


# Exact, paired official line markers only: a single-looking statement within
# a question MUST NOT be stripped. Preserve the original source separately.
_CODE = re.compile(r'^[ \t\u3000]*代號[ \t]*[:：][ \t]*[0-9]{2,8}(?:[－\-–][0-9]{2,8})?[ \t]*$')
_PAGE = re.compile(r'^[ \t\u3000]*頁次[ \t]*[:：][ \t]*([0-9]{1,3})[－\-–]([0-9]{1,3})[ \t]*$')


def clean_page_frames(raw: str) -> tuple[str, list[dict]]:
    lines = raw.replace('\r\n','\n').replace('\r','\n').splitlines(keepends=True)
    removed, output, i = [], [], 0
    while i < len(lines):
        if i + 1 < len(lines) and _CODE.fullmatch(lines[i].rstrip('\n')):
            pg = _PAGE.fullmatch(lines[i+1].rstrip('\n'))
            if pg and 1 <= int(pg.group(2)) <= int(pg.group(1)) <= 120:
                removed.append({'line_number': i+1, 'page': int(pg.group(2)),
                                'total_pages': int(pg.group(1)),
                                'frame_kind': 'exact_code_and_page_pair'})
                i += 2
                continue
        output.append(lines[i]); i += 1
    return ''.join(output), removed


_CHINESE_DIGITS = {'一':1,'二':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9,'十':10,
                  '壹':1,'貳':2,'參':3,'肆':4,'伍':5,'陸':6,'柒':7,'捌':8,'玖':9,'拾':10}


def _chinese_number(value: str) -> int | None:
    if value.isdecimal(): return int(value)
    if value in _CHINESE_DIGITS: return _CHINESE_DIGITS[value]
    if value.startswith('十') and len(value)==2 and value[1] in _CHINESE_DIGITS:
        return 10+_CHINESE_DIGITS[value[1]]
    if len(value)==2 and value.endswith('十') and value[0] in _CHINESE_DIGITS:
        return 10*_CHINESE_DIGITS[value[0]]
    return None


_ESSAY_HEAD = re.compile(r'(?m)^[ \t\u3000]{0,8}(?:第[ \t]*([0-9一二三四五六七八九十壹貳參肆伍陸柒捌玖拾]{1,3})[ \t]*題|([一二三四五六七八九十壹貳參肆伍陸柒捌玖拾]{1,3})[、．.])[ \t]*')
_MIXED_HEAD = re.compile(r'(?m)^[ \t\u3000]{0,8}([甲乙丙丁])[、．.][ \t]*(作文|測驗題|申論題)[ \t]*部分\s*[:：]?')
_NUMERIC_HEAD = re.compile(r'(?m)^[ \t]{0,5}([0-9]{1,3})[ \t]+')


def _essay_entries(section_text: str, *, max_items: int=50) -> dict:
    hits=[]
    for m in _ESSAY_HEAD.finditer(section_text):
        n=_chinese_number(m.group(1) or m.group(2))
        if n is not None and 1 <= n <= max_items:
            hits.append((n,m))
    if not hits:
        return {'state':'no_confirmed_essay_headings','count':0,'sections':[]}
    # Strong sequence gate. Do not silently skip out-of-order/duplicated items.
    if hits[0][0]!=1 or [n for n,_ in hits] != list(range(1,len(hits)+1)):
        return {'state':'ambiguous_essay_numbering_requires_review','count':0,'sections':[],
                'observed_numbers_unverified':[n for n,_ in hits]}
    segments=[]
    for i,(n,m) in enumerate(hits):
        end=hits[i+1][1].start() if i+1<len(hits) else len(section_text)
        content=section_text[m.end():end].strip()
        if len(content)<15 or len(content)>25_000:
            return {'state':'invalid_essay_section_length_requires_review','count':0,'sections':[]}
        segments.append({'number':n,'original_heading':m.group().strip(),
                         'text_unverified':content[:12000], 'truncated':len(content)>12000,
                         'is_separate_paper':False,'human_verified':False})
    return {'state':'essay_headings_extracted_NEEDS_VISUAL_REVIEW',
            'count':len(segments),'sections':segments}


def section_index(text: str, official_type: str) -> dict:
    clean, frames=clean_page_frames(text)
    if official_type=='申論題':
        return {'kind':'essay', 'essay':_essay_entries(clean), 'sections':[],
                'verified_page_frames_removed':len(frames)}
    if official_type=='混合題':
        marks=list(_MIXED_HEAD.finditer(clean))
        if not marks or [x.group(1) for x in marks]!=['甲','乙']:
            return {'kind':'mixed','state':'mixed_subsections_missing_or_ambiguous',
                    'essay':None,'sections':[],'verified_page_frames_removed':len(frames)}
        sections=[]
        for i,m in enumerate(marks):
            end=marks[i+1].start() if i+1<len(marks) else len(clean)
            fragment=clean[m.end():end].strip()
            part_type={'作文':'composition','測驗題':'multiple_choice','申論題':'essay'}[m.group(2)]
            # Never call a composition prompt a legal essay.
            item={'label':m.group(1),'type':part_type,
                  'raw_text_unverified':fragment[:12000],
                  'is_separate_paper':False,'human_verified':False}
            if part_type=='essay':item['essay_index']=_essay_entries(fragment)
            if part_type=='multiple_choice':
                number_sequence=[int(h.group(1)) for h in _NUMERIC_HEAD.finditer(fragment)]
                item['numeric_heading_candidate_count']=len(number_sequence)
                item['numbering_sequential']=number_sequence==list(range(1,len(number_sequence)+1))
            sections.append(item)
        return {'kind':'mixed','state':'mixed_sections_unverified',
                'sections':sections,'essay':None,'verified_page_frames_removed':len(frames)}
    return {'kind':'multiple_choice','sections':[], 'essay':None,
            'verified_page_frames_removed':len(frames)}


def repaired_questions(original_questions: list[dict], *, type_label: str) -> dict:
    if not isinstance(original_questions,list) or len(original_questions)>MAX_QUESTIONS:
        raise OverlayError('invalid question count')
    found=[]; changes=[]; seen=set()
    for q in original_questions:
        n=q.get('number') if isinstance(q,dict) else None
        if not isinstance(n,int) or n in seen or n<1 or n>MAX_QUESTIONS:
            raise OverlayError('duplicate or invalid question number')
        seen.add(n)
        options=q.get('options_unverified')
        if not isinstance(options,dict) or any(k not in ('A','B','C','D') for k in options):
            raise OverlayError('bad options')
        copied=copy.deepcopy(q)
        reasons=copied.get('review_reasons',[])
        if not isinstance(reasons,list): raise OverlayError('bad reasons')
        repaired=False
        if reasons==['page_header_or_footer_inside_question'] and len(options)==4:
            # Only alter option D when it ends in exact matched official framing.
            cleaned,frames=clean_page_frames(options['D'])
            cleaned=cleaned.strip()
            if frames and cleaned and len(cleaned)<=3000:
                copied['options_unverified']['D']=cleaned
                copied['candidate_status']='four_options_extracted_NEEDS_VISUAL_REVIEW'
                copied['review_reasons']=[]
                copied.setdefault('source_normalizations_unverified',[]).append('exact_page_frame_pair_removed_from_D')
                copied['human_verified']=False
                repaired=True
                changes.append({'number':n,'action':'remove_exact_page_frame_pair_from_option_D',
                                'source_frame_count':len(frames)})
        copied.update(_UNVERIFIED)
        copied['eligible_for_scoring']=False
        copied['correction_applied']=False
        if copied['candidate_status']=='four_options_extracted_NEEDS_VISUAL_REVIEW':
            # Visible four options are candidate status, not formal completeness proof.
            if set(copied['options_unverified'])=={'A','B','C','D'} and all(str(v).strip() for v in copied['options_unverified'].values()):
                found.append(copied)
        if not repaired and 'page_header_or_footer_inside_question' in reasons:
            changes.append({'number':n,'action':'page_frame_candidate_remains_isolated'})
    return {'candidate_count':len(found),'candidate_question_numbers':[q['number'] for q in found],
            'question_candidates':found,'repaired':changes,
            'original_questions_count':len(original_questions),
            'all_questions_final_verified':False}


def _identity(url:str, role:str)->tuple[str,...]:
    v=urlsplit(url)
    if (v.scheme!='https' or v.hostname!='wwwq.moex.gov.tw' or v.username or v.password
        or v.port not in (None,443) or v.fragment
        or v.path.lower()!='/exam/whandexamqanda_file.ashx'):
        raise OverlayError('untrusted official source URL')
    parts=parse_qs(v.query,strict_parsing=True,keep_blank_values=True)
    if set(parts)!={'t','code','c','s','q'} or any(len(x)!=1 for x in parts.values()) or parts['t'][0]!=role:
        raise OverlayError('unexpected official source identity')
    values=tuple(parts[k][0] for k in ('code','c','s','q'))
    if not all(re.fullmatch(r'[0-9]{1,8}',v) for v in values):
        raise OverlayError('malformed official identity code')
    return values


_CORRECTION = re.compile(r'(?:第\s*(\d{1,3})\s*題|題號\s*(\d{1,3}))[^\n。]{0,100}?([ABCD])\s*(?:或|、|／|\/|及|和)\s*([ABCD])\s*(?:者)?\s*(?:均|都)?\s*(?:給分|計分|給予分數|得分)')


def parse_special_credit_note(text:str) -> list[dict]:
    out=[]
    for m in _CORRECTION.finditer(unicodedata.normalize('NFKC',text)):
        n=int(m.group(1) or m.group(2));a,b=m.group(3),m.group(4)
        if 1<=n<=MAX_QUESTIONS and a!=b:
            out.append({'number':n,'candidate_valid_choices':sorted([a,b]),
                        'raw_note_unverified':m.group()[:180], 'human_verified':False,
                        'requires_special_scoring_review':True})
    return out


# Parse the OFFICIAL PDF by aligned visual cells, never by the arbitrary
# sequence in which PDF extract_text() happens to return table characters.
# All coordinates and labels originate from the already SHA-verified PDF.
_POSITIONED_NUMBER = re.compile(r'第([0-9]{1,3})題')
_COUNT_DECLARATION = re.compile(r'單選題數\s*[:：]?\s*(\d{1,3})\s*題')


def _fragment_kind(fragment: str) -> tuple[str, int | str] | None:
    text = unicodedata.normalize('NFKC', fragment).strip()
    # Embedded newlines in a single fragment cannot be positioned separately.
    if '\n' in text or len(text) > 35:
        return None
    compact = re.sub(r'\s+', '', text)
    if compact in ('題號', '題次'):
        return ('numbers_label', compact)
    if compact in ('答案', '標準答案'):
        return ('answers_label', compact)
    match = _POSITIONED_NUMBER.fullmatch(compact)
    if match:
        return ('number', int(match.group(1)))
    if compact in ('A', 'B', 'C', 'D', '#'):
        return ('answer', compact)
    return None


def _read_positioned_tokens(page) -> list[dict]:
    tokens = []
    def visitor(fragment, cm, tm, font_dict, font_size):
        classified = _fragment_kind(fragment)
        if not classified:
            return
        try:
            # PDF user-space position; account for text and current transforms.
            x = cm[0] * tm[4] + cm[2] * tm[5] + cm[4]
            y = cm[1] * tm[4] + cm[3] * tm[5] + cm[5]
            if not (math.isfinite(x) and math.isfinite(y)):
                return
            tokens.append({'x': round(float(x), 3), 'y': round(float(y), 3),
                           'kind': classified[0], 'value': classified[1]})
        except (TypeError, ValueError, IndexError, OverflowError):
            return
    page.extract_text(visitor_text=visitor)
    return tokens


def _rows_for_positioned(tokens: list[dict]) -> list[dict]:
    rows = []
    for token in sorted(tokens, key=lambda x: (-x['y'], x['x'])):
        if rows and abs(rows[-1]['y'] - token['y']) <= 2.5:
            rows[-1]['tokens'].append(token)
        else:
            rows.append({'y': token['y'], 'tokens': [token]})
    for row in rows:
        row['tokens'].sort(key=lambda x: x['x'])
    return rows


def _parse_pdf_positioned_answers(pages, *, expected_question_count: int) -> dict:
    """Strict column alignment between a labeled question row and answer row.

    No implied reading order, no PDF OCR, no automatic answer promotion.
    A # is only a change marker and must be resolved by an explicit note.
    """
    if not 1 <= expected_question_count <= MAX_QUESTIONS:
        raise OverlayError('invalid expected question count')
    pairs = {}
    markers = set()
    conflict = set()
    rejected_groups = 0
    accepted_groups = 0
    for page_num, page in enumerate(pages, 1):
        rows = _rows_for_positioned(_read_positioned_tokens(page))
        for index, head in enumerate(rows):
            heads = [t for t in head['tokens'] if t['kind'] == 'numbers_label']
            numbers = [t for t in head['tokens'] if t['kind'] == 'number']
            if len(heads) != 1 or len(numbers) < 3:
                continue
            # The official horizontal table numbers are consecutive left to right.
            numlist = [t['value'] for t in numbers]
            if numlist != list(range(numlist[0], numlist[0]+len(numlist))):
                rejected_groups += 1
                continue
            # Skip the final empty (51-100) table rows, not real answer cells.
            relevant = [t for t in numbers if 1 <= t['value'] <= expected_question_count]
            if not relevant:
                continue
            options = []
            for body in rows[index + 1:]:
                distance = head['y'] - body['y']
                if distance > 30:
                    break
                if not 5 <= distance <= 30:
                    continue
                labs = [t for t in body['tokens'] if t['kind']=='answers_label']
                if len(labs) != 1 or abs(labs[0]['x'] - heads[0]['x']) > 18:
                    continue
                options.append(body)
            if len(options) != 1:
                rejected_groups += 1
                continue
            answers = [t for t in options[0]['tokens'] if t['kind']=='answer']
            # The row may not contain answers for columns beyond the declared
            # question count. Reject more values than nonempty question cells.
            if not answers or len(answers) > len(relevant):
                rejected_groups += 1
                continue
            locations = [t['x'] for t in numbers]
            steps = [b-a for a,b in zip(locations,locations[1:])]
            if any(v <= 9 for v in steps):
                rejected_groups += 1
                continue
            tolerance = min(18, max(8, min(steps)*0.34))
            matched = []
            for answer in answers:
                nearest = sorted(((abs(answer['x']-item['x']), item['value']) for item in relevant),key=lambda v:v[0])
                if not nearest or nearest[0][0] > tolerance or (len(nearest)>1 and nearest[1][0] - nearest[0][0] < 2):
                    matched=[]
                    break
                matched.append((nearest[0][1],answer['value']))
            # This is a *whole row* proof; if any answer cell cannot be
            # assigned unambiguously, reject the entire row.
            if not matched or len({n for n,_ in matched}) != len(matched):
                rejected_groups += 1
                continue
            for n,answer in matched:
                if n in pairs:
                    # Duplicate cells (even identical ones) require review.
                    conflict.add(n)
                pairs[n] = answer
            accepted_groups += 1
    if conflict:
        pairs = {}
    for n,answer in pairs.items():
        if answer == '#':
            markers.add(n)
    single = {str(n):v for n,v in sorted(pairs.items()) if v in 'ABCD'}
    return {'candidates':single,'correction_markers':sorted(markers),
            'unique_paired_numbers':len(single), 'covered_cell_count':len(pairs),
            'complete_positioned_grid':len(pairs)==expected_question_count and not conflict,
            'conflicting_numbers':sorted(conflict),'evidence_group_count':accepted_groups,
            'rejected_grid_groups':rejected_groups,
            'pairing_method':'aligned_PDF_cell_positions',
            'final_answers_verified':False, 'publication_allowed':False,'scoring_enabled':False}


def parse_table_candidates(text:str, *, expected_question_count:int) -> dict:
    """Pairs only numbered rows / explicit paired grids. NEVER infer column order."""
    if not 1<=expected_question_count<=MAX_QUESTIONS:
        raise OverlayError('invalid expected count')
    answer_map={};conflicts=[]; observed_sources=0
    lines=unicodedata.normalize('NFKC',text).splitlines()
    # Number + answer on one line. Do not parse bare numeric lines in prose.
    one=re.compile(r'^\s*(\d{1,3})[.)、]?\s+([ABCD])\s*$')
    for line in lines:
        m=one.fullmatch(line)
        if m:
            n=int(m.group(1));value=m.group(2)
            if 1<=n<=expected_question_count:
                observed_sources+=1
                if n in answer_map and answer_map[n]!=value:conflicts.append(n)
                answer_map[n]=value
    # A common answer PDF grid: explicitly labeled paired lines.
    for i in range(len(lines)-1):
        nline=re.fullmatch(r'\s*題(?:號|次)\s*[:：]?\s*((?:\d{1,3}\s+)+\d{1,3})\s*',lines[i])
        aline=re.fullmatch(r'\s*(?:標準)?答案\s*[:：]?\s*(([ABCD]\s+)*[ABCD])\s*',lines[i+1])
        if not nline or not aline: continue
        nums=[int(v) for v in nline.group(1).split()]
        keys=aline.group(1).split()
        if len(nums)!=len(keys) or len(set(nums))!=len(nums) or any(n<1 or n>expected_question_count for n in nums):
            continue
        observed_sources+=1
        for n,key in zip(nums,keys):
            if n in answer_map and answer_map[n]!=key:conflicts.append(n)
            answer_map[n]=key
    completeness = bool(len(answer_map)==expected_question_count and set(answer_map)==set(range(1,expected_question_count+1)))
    return {'state':'complete_unverified_candidate_table' if completeness and not conflicts else 'partial_or_ambiguous_answer_table',
            'candidates':{str(k):v for k,v in sorted(answer_map.items())} if not conflicts else {},
            'unique_paired_numbers':len(answer_map),
            'complete_numbering_candidate':completeness and not conflicts,
            'conflicting_numbers':sorted(set(conflicts)),'evidence_group_count':observed_sources,
            'final_answers_verified':False, 'publication_allowed':False,'scoring_enabled':False}


def inspect_corrected_pdf(raw_pdf:bytes, *, declared_url:str, role:str, report:dict, expected_count:int) -> dict:
    from pypdf import PdfReader
    if not isinstance(raw_pdf,bytes) or len(raw_pdf)>MAX_PDF_BYTES or not raw_pdf.startswith(b'%PDF-'):
        raise OverlayError('invalid or oversized official answer document')
    if role not in ('S','M'):
        raise OverlayError('wrong answer role')
    official=report['official_source']
    ref=official['answer_url']
    if ref!=declared_url or _identity(declared_url,role)!=_identity(official['question_url'],'Q'):
        raise OverlayError('cross-paper or unauthorized answer file')
    docs=report['v03_review']['reviewed_items'][0]['documents']
    existing=[d for d in docs if d.get('role')==role]
    if len(existing)!=1 or existing[0].get('sha256')!=_sha(raw_pdf):
        raise OverlayError('answer PDF SHA256 mismatch against original review')
    reader=PdfReader(io.BytesIO(raw_pdf),strict=False)
    if not 1<=len(reader.pages)<=50:raise OverlayError('invalid page count')
    text='\n'.join((p.extract_text() or '') for p in reader.pages)
    if not text.strip() or len(text)>MAX_TEXT_BYTES:
        raise OverlayError('unreadable answer PDF')
    text_preview=parse_table_candidates(text,expected_question_count=expected_count)
    positioned=_parse_pdf_positioned_answers(reader.pages,expected_question_count=expected_count)
    special=parse_special_credit_note(text)
    if any(s['number']<1 or s['number']>expected_count for s in special):
        raise OverlayError('special note outside table scope')
    # Independent sources must agree wherever they overlap. A text run with
    # ambiguous flat-PDF ordering cannot trump the explicitly aligned cells.
    mismatches = sorted(n for n,v in positioned['candidates'].items()
                        if n in text_preview['candidates'] and text_preview['candidates'][n]!=v)
    declared = [int(n) for n in _COUNT_DECLARATION.findall(unicodedata.normalize('NFKC',text))]
    count_issue = bool(declared and (len(set(declared))!=1 or declared[0]!=expected_count))
    markers = positioned['correction_markers']
    notes_by_number = {}
    duplicate_note = set()
    for entry in special:
        n=entry['number'];choices=entry['candidate_valid_choices']
        if n in notes_by_number and notes_by_number[n]!=choices:
            duplicate_note.add(n)
        notes_by_number[n] = choices
    unresolved = sorted(set(markers)-set(notes_by_number))
    unanchored = sorted(set(notes_by_number)-set(markers))
    if role=='S' and markers:
        # A correction marker in a standard-answer document is unexpected.
        unresolved = sorted(set(unresolved)|set(markers))
    existing = positioned['candidates'] if positioned['evidence_group_count'] else text_preview['candidates']
    existing = dict(existing)
    for n in markers:
        # A # cell has no single-choice answer; it is linked only to the
        # accompanying explicit multiple-credit note. Never invent a letter.
        existing.pop(str(n),None)
    complete = (not count_issue and not mismatches and not duplicate_note
                and not unanchored and not unresolved and not text_preview['conflicting_numbers']
                and positioned['complete_positioned_grid']
                and len(existing)+len(notes_by_number)==expected_count
                and set(map(int,existing))|set(notes_by_number)==set(range(1,expected_count+1)))
    if count_issue or mismatches or duplicate_note or text_preview['conflicting_numbers'] or positioned['conflicting_numbers']:
        # Fail closed even when parts of the extracted PDF look plausible.
        existing={}
        complete=False
    preview={**positioned,
        'candidates':existing,
        'unique_paired_numbers':len(existing),
        'special_credit_choices_unverified':{str(n):v for n,v in sorted(notes_by_number.items())},
        'answer_cell_coverage_with_special_notes':len(set(map(int,existing)) | set(notes_by_number)) if not (mismatches or count_issue) else 0,
        'complete_numbering_candidate':complete,
        'state':'complete_unverified_candidate_table_WITH_SPECIAL_REVIEW' if complete and special else
                'complete_unverified_candidate_table' if complete else 'partial_or_ambiguous_answer_table',
        'text_extraction_candidate_count':text_preview['unique_paired_numbers'],
        'text_position_conflicts':mismatches,
        'declared_single_choice_count':declared,
        'declared_count_mismatch':count_issue,
        'unresolved_change_markers':unresolved,
        'special_credit_without_change_marker':unanchored,
        'conflicting_special_notes':sorted(duplicate_note),
        'final_answers_verified':False,'publication_allowed':False,'scoring_enabled':False}
    # Never turn a multi-credit note into a single automatically scored key.
    return {'state':'official_answer_PDF_candidate_requires_manual_QSM_review',
            'answer_document_role':role,'answer_document_sha256':_sha(raw_pdf),
            'table_candidate':preview,'special_credit_candidate':special,
            'answer_text_sha256':_sha(text.encode()),
            'cannot_convert_to_single_choice':sorted(set(s['number'] for s in special)),
            'final_answers_verified':False, 'scoring_enabled':False,'publication_allowed':False}


def _read_cache_pdf(out_dir:Path, report:dict, *, cache_root:Path|None=None) -> tuple[bytes|None,str|None]:
    # Read only an already-cached and report-SHA-matched official source.
    url=report['official_source'].get('answer_url') or ''
    if not url:return None,None
    role=parse_qs(urlsplit(url).query).get('t',[''])[0]
    if role not in ('S','M'):return None,None
    _identity(url,role)
    # The series orchestrator stores PUBLIC PDFs in a shared cache outside each
    # session's report directory. Legacy single-run callers keep their old path.
    root=cache_root if cache_root is not None else out_dir/'official_pdf_cache'
    key=_sha(url.encode())
    pdf=root/(key+'.pdf');meta=root/(key+'.json')
    if pdf.is_symlink() or meta.is_symlink():
        raise OverlayError('official PDF cache entry cannot be a symlink')
    if pdf.exists() != meta.exists():
        raise OverlayError('incomplete public answer PDF cache entry')
    if not pdf.exists():return None,None
    m=json.loads(meta.read_text('utf-8'))
    blob=pdf.read_bytes()
    if m.get('url')!=url or m.get('sha256')!=_sha(blob):
        raise OverlayError('official answer PDF cache mutated')
    return blob,role


def build_overlay(report:dict, raw_text:str, *, report_bytes:bytes, answer_pdf:bytes|None=None, answer_role:str|None=None) -> dict:
    if report.get('schema') != REVIEW_SCHEMA or report.get('publication_allowed') is not False or report.get('scoring_enabled') is not False:
        raise OverlayError('source report is not a safe unscored whole-paper review')
    source=report.get('official_source',{});kind=source.get('official_type')
    if kind not in ('測驗題','申論題','混合題'):
        raise OverlayError('unrecognized official examination type')
    if not raw_text or len(raw_text.encode())>MAX_TEXT_BYTES:
        raise OverlayError('unreadable source text')
    orig_digest=report.get('extracted_question_text',{}).get('sha256')
    if orig_digest!=_sha(raw_text.encode()):
        raise OverlayError('original fulltext SHA256 mismatch')
    if source.get('paper_id') != report.get('paper_id'):
        raise OverlayError('mixed paper IDs')
    core=report.get('v03_review',{})
    if core.get('publication_allowed') is not False or core.get('scoring_enabled') is not False:
        raise OverlayError('upstream report claims publication or scoring approval')
    reviewed=core.get('reviewed_items',[])
    if not isinstance(reviewed,list) or len(reviewed)!=1:
        raise OverlayError('unexpected number of original paper reviews')
    qreport=reviewed[0].get('question_answer_candidates',{})
    if (qreport.get('publication_allowed',False) is not False or
        qreport.get('scoring_enabled',False) is not False):
        raise OverlayError('upstream candidate report claims scoring approval')
    questions=qreport.get('questions',[])
    for q in questions:
        if not isinstance(q,dict) or any(q.get(flag) is True for flag in
            ('eligible_for_scoring','final_answer_verified','options_verified',
             'question_text_verified','correction_applied')):
            raise OverlayError('forged verification flag on source candidate')
    mcqs=repaired_questions(questions,type_label=kind)
    section=section_index(raw_text,kind)
    answer={'state':'not_available_or_not_required_for_essay','final_answers_verified':False}
    if kind in ('測驗題','混合題'):
        answer={'state':'S_or_M_cached_PDF_needed_for_answer_table','final_answers_verified':False}
        if answer_pdf is not None and answer_role:
            answer=inspect_corrected_pdf(answer_pdf,declared_url=source['answer_url'],role=answer_role,
                                         report=report,expected_count=len(questions))
            table=answer['table_candidate']
            old={str(q['number']):q['published_standard_candidate']
                 for q in questions if isinstance(q,dict)
                 and isinstance(q.get('number'),int)
                 and q.get('published_standard_candidate') in ('A','B','C','D')}
            new=table.get('candidates',{})
            overlaps=sorted(set(old)&set(new), key=int)
            discrepancies=[int(n) for n in overlaps if old[n]!=new[n]]
            table['original_candidate_overlap_count']=len(overlaps)
            table['original_candidate_conflict_numbers']=discrepancies
            table['original_candidate_comparison_is_not_answer_validation']=True
            if discrepancies:
                table['state']='source_and_positioned_answers_disagree_requires_review'
                table['complete_numbering_candidate']=False
                table['candidates']={}
                table['unique_paired_numbers']=0
                table['answer_cell_coverage_with_special_notes']=0
    effective_sha=_sha(answer_pdf) if answer_pdf is not None else 'not_cached'
    return {'schema':SCHEMA,'paper_id':source['paper_id'],
            'official_metadata_unchanged':copy.deepcopy(source),
            'official_type_unchanged':kind,
            'report_source_sha256':_sha(report_bytes),
            'extracted_text_source_sha256':_sha(raw_text.encode()),
            'answer_PDF_source_sha256_or_state':effective_sha,
            'subject_title_evidence':title_evidence(source.get('official_subject',''),raw_text),
            'section_candidates':section,'multiple_choice_candidates':mcqs,
            'answer_and_correction_evidence':answer,
            'note':'These are previews of the original WHOLE paper. No independent question papers are created.',
            **_UNVERIFIED, 'private_attempts_included':False}


def make_overlay_from_disk(out_dir:Path, report_path:Path, *, cache_root:Path|None=None) -> tuple[Path,dict]:
    report_bytes=report_path.read_bytes()
    if len(report_bytes)>MAX_SOURCE_BYTES:raise OverlayError('report oversized')
    report=json.loads(report_bytes)
    pid=report.get('paper_id')
    if not isinstance(pid,str) or not re.fullmatch(r'moex-[a-f0-9]{24}',pid) or report_path.name!=pid+'.json':
        raise OverlayError('unexpected public report name')
    text_path=out_dir/'extracted_text'/(pid+'.txt')
    raw=text_path.read_text('utf-8')
    pdf,role=_read_cache_pdf(out_dir,report,cache_root=cache_root)
    overlay=build_overlay(report,raw,report_bytes=report_bytes,answer_pdf=pdf,answer_role=role)
    content=(json.dumps(overlay,ensure_ascii=False,indent=2,sort_keys=True)+'\n').encode('utf-8')
    filename=pid+'-'+_sha(content)[:16]+'.json'
    target=out_dir/'quality_previews'/filename
    if target.exists():
        if target.read_bytes()!=content:raise OverlayError('existing quality preview mutated')
    else:
        target.parent.mkdir(parents=True,exist_ok=True)
        # Atomic CREATE ONLY; do not replace existing files and never touch the V0.3 report.
        try:
            with target.open('xb') as f:f.write(content)
        except FileExistsError:
            if target.read_bytes()!=content:raise OverlayError('concurrent quality preview conflict')
    return target,overlay


def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--review-dir',type=Path,required=True,help='existing public official-review directory')
    ap.add_argument('--paper-id',help='one moex-.. paper; omit for all source reports')
    args=ap.parse_args(argv)
    root=args.review_dir.resolve()
    src=root/'reports'
    paths=sorted(src.glob('moex-*.json')) if not args.paper_id else [src/(args.paper_id+'.json')]
    if not paths:
        print('No existing source reports, nothing rewritten',file=sys.stderr);return 2
    results=[]
    for path in paths:
        try:
            target,overlay=make_overlay_from_disk(root,path)
            answer_evidence=overlay['answer_and_correction_evidence']
            results.append({'paper_id':overlay['paper_id'],
                            'quality_preview':str(target),
                            'essay_questions': (overlay['section_candidates'].get('essay') or {}).get('count',0),
                            'candidate_multiple_choice':overlay['multiple_choice_candidates']['candidate_count'],
                            'mixed_sections':len(overlay['section_candidates']['sections']),
                            'answer_status':answer_evidence['state'],
                            'candidate_answer_pairs':answer_evidence.get('table_candidate',{}).get('unique_paired_numbers',0),
                            'special_credit_question_candidates':[v['number'] for v in answer_evidence.get('special_credit_candidate',[])],
                            'scoring_enabled':False})
        except (OSError,ValueError,TypeError,KeyError) as exc:
            results.append({'paper_id':path.stem,'state':'quality_preview_isolated_not_published',
                            'reason':type(exc).__name__+': '+str(exc)[:120]})
    print(json.dumps({'results':results,'publication_allowed':False,'scoring_enabled':False},ensure_ascii=False))
    return 0 if all('quality_preview' in item for item in results) else 2


if __name__=='__main__':
    sys.exit(main())
