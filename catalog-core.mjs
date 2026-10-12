/** LexFlow V0.3 unified catalogue. Pure/read-only: never scores or edits records. */
export const CATALOG_TYPES = Object.freeze(['全部', '申論', '選擇題']);
export const CATALOG_SOURCES = Object.freeze(['全部', '自編', '官方原卷', '官方候審']);
export const CATALOG_AREAS = Object.freeze(['全部', '民法', '刑法', '憲法', '其他']);

const FOCUS = ['民法', '刑法', '憲法'];
function focusFor(subject, explicit) {
  const all = Array.isArray(explicit) ? explicit.filter(s => FOCUS.includes(s)) : [];
  if (all.length) return [...new Set(all)];
  const clean = String(subject || '').replaceAll('監獄行刑法', '').replaceAll('國民法官法', '');
  return FOCUS.filter(s => clean.includes(s));
}
function simple(v, n = 180) { return String(v ?? '').slice(0, n); }

export function buildCatalog({essays = [], officialPapers = [], selfMcq = [], customEssays = [], importedPapers = []} = {}) {
  const out = [];
  for (const p of [...essays, ...customEssays]) {
    if (!p || typeof p.id !== 'string') continue;
    out.push({id: p.id, source: '自編', type: '申論', subject: simple(p.subject),
      focus: focusFor(p.subject), title: simple(p.title), description: simple(p.exam || '自行建立的申論練習'),
      action: 'essay', count: 1, url: '', warning: '自編練習；非官方標準擬答'});
  }
  for (const p of officialPapers) {
    if (!p || typeof p.id !== 'string') continue;
    out.push({id: p.id, source: '官方原卷', type: '申論', subject: simple(p.subject),
      focus: focusFor(p.subject), title: simple(p.title), description: simple(p.exam || '考選部官方申論原卷'),
      action: 'essay', count: 1, url: simple(p.url, 2048),
      warning: '原卷含多題；進入編輯器後請選取完整題目'});
  }
  for (const q of selfMcq) {
    if (!q || typeof q.id !== 'string') continue;
    out.push({id: q.id, source: '自編', type: '選擇題', subject: simple(q.subject),
      focus: focusFor(q.subject), title: simple(q.title), description: simple(q.topic || '自編法條選擇題'),
      action: 'single-mcq', count: 1, url: '', warning: '自編答案及詳解，不是國考成績'});
  }
  for (const p of importedPapers) {
    if (!p || typeof p.id !== 'string' || !Array.isArray(p.questions) || !p.questions.length) continue;
    out.push({id: p.id, source: '官方候審', type: '選擇題', subject: simple(p.subject),
      focus: focusFor(p.subject, p.focus), title: simple(p.subject),
      description: simple(p.exam || '官方來源 PDF 候審'), action: 'candidate',
      count: p.questions.length, url: '',
      warning: 'PDF 擷取候審；未核對最終答案，不計分'});
  }
  return out;
}

export function filterCatalog(records, filters = {}) {
  const type = CATALOG_TYPES.includes(filters.type) ? filters.type : '全部';
  const source = CATALOG_SOURCES.includes(filters.source) ? filters.source : '全部';
  const area = CATALOG_AREAS.includes(filters.area) ? filters.area : '全部';
  const text = String(filters.search || '').trim().toLocaleLowerCase('zh-TW').slice(0, 150);
  return records.filter(p =>
    (type === '全部' || p.type === type) &&
    (source === '全部' || p.source === source) &&
    (area === '全部' || (area === '其他' ? p.focus.length === 0 : p.focus.includes(area))) &&
    (!text || `${p.title} ${p.subject} ${p.description} ${p.source}`.toLocaleLowerCase('zh-TW').includes(text)));
}

export function sourceCounts(records) {
  return {
    essay: records.filter(p => p.type === '申論').length,
    authored: records.filter(p => p.type === '選擇題' && p.source === '自編').length,
    official: records.filter(p => p.source === '官方候審').length,
    officialOriginals: records.filter(p => p.source === '官方原卷').length
  };
}
