#!/usr/bin/env python3
"""Fail-closed index of MOEX examination-page *document links*.

A document link's appearance on an official page does NOT confirm its PDF bytes,
final answer, question contents or lawful interpretation. Do not publish as a
scored question bank. This fallback is deliberately smaller than the CSV index;
its output MUST be stored separately and never replace the primary CSV index.
"""
from __future__ import annotations

import hashlib
import html
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sys
import urllib.parse
import urllib.request

from moex_index import SourceFailure, subjects_of, write_atomic

# Explicit, documented allowlist. Do not recursively crawl the entire site.
EXAM_PAGES = {
    '114120': 'https://wwwq.moex.gov.tw/exam/wFrmExamQandASearch.aspx?e=114120&y=2025',
}
MAX_HTML_BYTES = 6 * 1024 * 1024
MAX_ITEMS = 2500
EXAM_DISPLAY = '114年司法人員、法務部調查局調查人員等考試（考試代碼114120）'


def page_url(code: str) -> str:
    if code not in EXAM_PAGES:
        raise SourceFailure('exam is not in the preapproved official-page allowlist')
    return EXAM_PAGES[code]


def official_document_url(value: str, *, exam_code: str) -> tuple[str, str, tuple[str, str, str]] | None:
    """Only accept published MOEX Q/S/M link shapes, never arbitrary URLs."""
    url = html.unescape(str(value or '').strip())
    try:
        x = urllib.parse.urlsplit(url)
        if (x.scheme != 'https' or x.username or x.password or x.port not in (None, 443)
            or (x.hostname or '').lower() != 'wwwq.moex.gov.tw'
            or x.path.lower() != '/exam/whandexamqanda_file.ashx'
            or x.fragment):
            return None
        pairs = urllib.parse.parse_qs(x.query, strict_parsing=True, keep_blank_values=True)
        if set(pairs) != {'c', 'code', 'q', 's', 't'} or any(len(v) != 1 for v in pairs.values()):
            return None
        if pairs['code'][0] != exam_code or pairs['t'][0] not in ('Q', 'S', 'M'):
            return None
        if not all(re.fullmatch(r'\d{1,12}', pairs[k][0]) for k in ('c', 'q', 's')):
            return None
        return url, pairs['t'][0], (pairs['c'][0], pairs['q'][0], pairs['s'][0])
    except (ValueError, KeyError):
        return None


class TextLinks(HTMLParser):
    """Extract visible text/anchors in document order; no arbitrary HTML execution."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tokens: list[tuple[str, str]] = []
        self.skip = 0
        self.anchor: dict | None = None
        self.total_links = 0

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style', 'noscript'):
            self.skip += 1
            return
        if self.skip:
            return
        if tag == 'a':
            at = dict(attrs)
            self.anchor = {'href': at.get('href', ''), 'text': ''}
            self.total_links += 1

    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'noscript') and self.skip:
            self.skip -= 1
            return
        if self.skip:
            return
        if tag == 'a' and self.anchor is not None:
            self.tokens.append(('href', self.anchor['href']))
            self.anchor = None

    def handle_data(self, text):
        if self.skip:
            return
        clean = re.sub(r'\s+', ' ', text).strip()
        if not clean:
            return
        if self.anchor is not None:
            self.anchor['text'] += clean
        else:
            self.tokens.append(('text', clean))


def decode_html(data: bytes) -> str:
    if not data or len(data) > MAX_HTML_BYTES:
        raise SourceFailure('official exam page is empty/oversized')
    for enc in ('utf-8-sig', 'cp950', 'big5'):
        try:
            content = data.decode(enc)
        except UnicodeError:
            continue
        if '考畢試題查詢' in content and '<' in content:
            return content
    raise SourceFailure('unexpected response or encoding: not an MOEX exam page')


def fetch_exam_page(code: str = '114120', timeout: int = 25) -> bytes:
    url = page_url(code)
    req = urllib.request.Request(url, headers={
        'User-Agent': 'Mozilla/5.0 (compatible; LexFlow/0.3; public examination page read-only)',
        'Accept': 'text/html,application/xhtml+xml;q=0.9,*/*;q=0.4',
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            if response.geturl() != url:
                raise SourceFailure('unexpected MOEX exam page redirect')
            result = response.read(MAX_HTML_BYTES + 1)
    except (OSError, TimeoutError) as exc:
        raise SourceFailure(f'official individual exam page unavailable: {exc}') from exc
    if len(result) > MAX_HTML_BYTES:
        raise SourceFailure('official exam page exceeded configured size limit')
    return result


def _maybe_subject(text: str) -> str:
    # Preserve the official subject description, stripping only adjacent link labels.
    text = text.strip(' ：:、，\u3000')
    text = re.sub(r'(?:更正答案|試題|答案)+$', '', text).strip()
    return text[:180]


def _group(text: str) -> str | None:
    if '_' in text and '類科' in text and ('考試' in text or '司法' in text or '調查' in text):
        return text[:180]
    return None


def create_fallback_index(page_html: bytes, *, exam_code: str = '114120', min_items: int = 3) -> dict:
    page_url(exam_code)
    text = decode_html(page_html)
    parsed = TextLinks()
    parsed.feed(text)
    if parsed.total_links == 0 or f'{exam_code[:3]}年' not in text:
        raise SourceFailure('unexpected exam page / no examination-year evidence')
    # Tokens come from published HTML only. URLs in script markup are ignored.
    subject = ''
    group = ''
    current_id = ''
    active_key = None
    items: dict[str, dict] = {}
    invalid_official_doc = 0
    for kind, value in parsed.tokens:
        if kind == 'text':
            label = _group(value)
            if label:
                group = label
                current_id = ''
                active_key = None
            # Text immediately preceding '試題' is the displayed subject. A label
            # such as '答案' or site caption is not itself a subject.
            if len(value) <= 200 and value not in ('試題', '答案', '更正答案', '下載', '查看'):
                if ('法' in value or '憲' in value) and not label:
                    subject = _maybe_subject(value)
                elif '法' not in value and not label and len(value) < 90 and not value.startswith(('共 ', '本考試')):
                    subject = ''
            continue
        href = urllib.parse.urljoin(page_url(exam_code), value)
        # An unsafe link masquerading as Q/S/M on the site should fail closed.
        if 'wHandExamQandA_File.ashx' not in href:
            continue
        checked = official_document_url(href, exam_code=exam_code)
        if not checked:
            invalid_official_doc += 1
            continue
        absolute, role, link_key = checked
        if role == 'Q':
            cls = subjects_of(subject)
            if cls is None:
                active_key = None
                continue
            current_id = hashlib.sha256((exam_code + '\x1f' + absolute).encode('utf-8')).hexdigest()[:22]
            active_key = link_key
            if current_id in items:
                if group and group not in items[current_id]['groups']:
                    items[current_id]['groups'].append(group)
                continue
            items[current_id] = {
                'id': 'moex-page-' + current_id,
                'year_roc': exam_code[:3], 'exam': EXAM_DISPLAY,
                'grade': group.split('_')[0] if '_' in group else '類別待核對',
                'subject': subject, 'focus_subjects': cls[0],
                'classification': cls[1],
                'question_type': '題型待原卷核對（可能包含申論及測驗）',
                'question_url': absolute,
                'answer_url': '', 'answer_correction_url': '',
                'answer_verification': 'not_verified',
                'explanation_verification': 'not_available',
                'groups': [group] if group else [],
                'source_page_url': page_url(exam_code),
                'source': 'MOEX official examination page (link only)',
            }
        elif current_id in items and active_key == link_key:
            if role == 'S':
                items[current_id]['answer_url'] = absolute
            elif role == 'M':
                items[current_id]['answer_correction_url'] = absolute
    if invalid_official_doc:
        raise SourceFailure(f'{invalid_official_doc} invalid official-document links in examination page')
    if not (min_items <= len(items) <= MAX_ITEMS):
        raise SourceFailure(f'implausible/empty official-page index ({len(items)} records)')
    entries = sorted(items.values(), key=lambda d: (d['subject'], d['question_url']))
    for item in entries:
        item['groups'].sort()
    count = {x: sum(x in p['focus_subjects'] for p in entries) for x in ('民法', '刑法', '憲法')}
    return {
        'schema': 'lexflow.moex.index.v1',
        'status': 'fallback_official_page_links_unverified',
        'source': {
            'agency': '考選部', 'method': 'official_exam_page_html',
            'exam_pages': [page_url(exam_code)],
            'fingerprint_sha256': hashlib.sha256(json.dumps(entries, ensure_ascii=False, sort_keys=True).encode()).hexdigest(),
        },
        'summary': {'source_rows': len(parsed.tokens), 'index_papers': len(entries),
                    'subject_papers': count,
                    'needs_classification': sum(p['classification'] == 'needs_classification' for p in entries)},
        'disclaimer': '官方頁面備援：已建立試卷與答案連結，未逐份確認 PDF 內容、最終更正答案或逐題解析；主 CSV 索引未被覆蓋。',
        'items': entries,
    }


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument('--fetch', action='store_true')
    group.add_argument('--input-html', type=Path)
    ap.add_argument('--exam-code', default='114120', choices=sorted(EXAM_PAGES))
    ap.add_argument('--min-items', default=3, type=int)
    ap.add_argument('--output', type=Path, default=Path('data/moex_official_fallback.json'))
    a = ap.parse_args(argv)
    try:
        raw = fetch_exam_page(a.exam_code) if a.fetch else a.input_html.read_bytes()
        out = create_fallback_index(raw, exam_code=a.exam_code, min_items=a.min_items)
        changed = write_atomic(a.output, out)
    except (OSError, SourceFailure, UnicodeError, ValueError) as e:
        print(f'FAIL CLOSED (official page fallback): {e}; fallback index untouched', file=sys.stderr)
        return 2
    print(json.dumps({'source': 'individual_official_exam_page', 'changed': changed, **out['summary']}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
