/** LexFlow V0.3 local-only practice core. No fetch, no storage or UI side effects. */
export const LAB_SCHEMA = 'lexflow.practice.local.v1';
export const LAB_STORAGE_KEY = 'lexflow-v03-practice-lab-v1';
const ABCD = ['A','B','C','D'];

export function officialUrl(value) {
  if (typeof value !== 'string' || value.length > 2048) return '';
  try {
    const u = new URL(value);
    if (u.protocol !== 'https:' || u.username || u.password || (u.port && u.port !== '443') || u.hash) return '';
    const host = u.hostname.toLowerCase();
    if (host !== 'moex.gov.tw' && !host.endsWith('.moex.gov.tw')) return '';
    return value;
  } catch { return ''; }
}

function check(flag, message) { if (!flag) throw new Error(message); }
function capped(v, n, name) {
  check(typeof v === 'string' && v.length > 0 && v.length <= n, `${name}格式不符`);
  return v;
}
function readOfficialPaper(paper, paperIndex) {
  check(paper && typeof paper === 'object', '試卷格式錯誤');
  // Status cannot turn into a scoring permission even if an imported JSON is forged.
  check(paper.eligible_for_scoring === false && paper.answer_verified_final === false && paper.options_verified === false, '候審試卷包含不允許的評分狀態');
  const qa = paper.question_answer_candidates;
  check(qa && qa.schema === 'lexflow.moex.question.candidates.v1' && qa.publication_allowed === false && qa.scoring_enabled === false && qa.final_answer_verified === false && qa.question_text_and_options_verified === false, '題目候審狀態不正確');
  const id = capped(paper.id, 160, '試卷代號');
  const subject = capped(paper.subject, 240, '科目名稱');
  check(Array.isArray(qa.questions) && qa.questions.length <= 100, '題目數量不合理');
  const questionDoc = Array.isArray(paper.documents) ? paper.documents.find(d=>d?.role==='Q') : null;
  const questionUrl = officialUrl(questionDoc?.url);
  check(questionUrl, '缺乏官方試卷網址');
  const answerDoc = Array.isArray(paper.documents) ? paper.documents.find(d=>d?.role==='S') : null;
  const standardUrl = officialUrl(answerDoc?.url);
  const correctionDoc = Array.isArray(paper.documents) ? paper.documents.find(d=>d?.role==='M') : null;
  const correctionUrl = officialUrl(correctionDoc?.url);
  const correction = qa.official_correction || {};
  const questions = [];
  const seen = new Set();
  let excluded = 0;
  for (const q of qa.questions) {
    check(q && typeof q === 'object' && q.eligible_for_scoring === false && q.final_answer_verified === false && q.question_text_verified === false && q.options_verified === false, '候審題目含有錯誤的核驗旗標');
    const number = q.number;
    check(Number.isInteger(number) && number >= 1 && number <= 100 && !seen.has(number), '存在重複或非法題號');
    seen.add(number);
    const opts = q.options_unverified;
    const good = q.candidate_status === 'four_options_extracted_NEEDS_VISUAL_REVIEW' &&
      Array.isArray(q.review_reasons) && q.review_reasons.length === 0 &&
      typeof q.stem_unverified === 'string' && q.stem_unverified.trim().length >= 4 && q.stem_unverified.length <= 2500 &&
      opts && typeof opts === 'object' && !Array.isArray(opts) &&
      ABCD.every(k => typeof opts[k] === 'string' && opts[k].trim().length > 0 && opts[k].length <= 2000) &&
      Object.keys(opts).length === 4;
    if (!good) { excluded += 1; continue; }
    const candidate = paper.source_link_identity_confirmed === true && standardUrl && ABCD.includes(q.published_standard_candidate)
      ? q.published_standard_candidate : null;
    questions.push({number,stem:q.stem_unverified,options:ABCD.map(k=>opts[k]),publishedCandidate:candidate,
      flags:{correctionDocumentPresent:!!correctionUrl || correction.detected === true,
        correctionMentioned:!!q.correction_notice_mentions_question,sourceTextUnverified:true}});
  }
  questions.sort((a,b)=>a.number-b.number);
  if (!questions.length) return null;
  return {id,subject,exam:String(paper.exam||'考選部試卷').slice(0,200),year:String(paper.year_roc||'').slice(0,4),
    focus:Array.isArray(paper.focus_subjects)?paper.focus_subjects.filter(x=>['民法','刑法','憲法'].includes(x)):[],
    questionUrl,standardUrl,correctionUrl,questions,excluded,importIndex:paperIndex,
    status:'官方 PDF 擷取片段｜未完成逐字及最終答案核驗'};
}

/** Accept only GitHub's already unverified cross-field report. No official scoring data is created. */
export function importCandidateReport(data) {
  check(data && typeof data === 'object' && !Array.isArray(data), '候審報告格式錯誤');
  check(data.schema === 'lexflow.moex.universal.batch.v1' && data.status === 'bounded_pdf_review_not_a_scored_bank', '不是已支援的官方候審報告');
  check(data.publication_allowed === false && data.scoring_enabled === false && data.all_answers_verified === false && data.all_question_text_verified === false, '資料的發布／評分狀態不安全');
  check(Array.isArray(data.reviewed_items) && data.reviewed_items.length >= 1 && data.reviewed_items.length <= 12, '候審試卷數量不合理');
  const papers=[],ids=new Set();
  for (const [i,p] of data.reviewed_items.entries()) {
    const item=readOfficialPaper(p,i);
    if (!item) continue;
    check(!ids.has(item.id),'重複試卷代號');
    ids.add(item.id);papers.push(item);
  }
  check(papers.length > 0,'沒有可供私人練習的完整四選項題目');
  return {version:1,sourceSchema:data.schema,officialFinalAnswersConfirmed:false,importedAt:new Date().toISOString(),papers};
}

export function demoSet(mcqItems) {
  check(Array.isArray(mcqItems),'自編題庫格式不符');
  const q=mcqItems.map((v,i)=>{
    check(v && typeof v.id==='string' && typeof v.question==='string' &&
      Array.isArray(v.options) && v.options.length===4 && v.options.every(s=>typeof s==='string'&&s.trim()) &&
      Number.isInteger(v.answer) && v.answer>=0 && v.answer<4 && Array.isArray(v.notes)&&v.notes.length===4, '自編題資料不完整');
    return {number:i+1,id:v.id,subject:v.subject,stem:v.question,options:[...v.options],answer:ABCD[v.answer],
      explanations:v.notes,source:v.source,sourceUrl:v.sourceUrl,title:v.title};
  });
  return {id:'builtin-demo',subject:'民法・刑法・憲法',exam:'自編法條示範（不是考選部歷屆試題）',questions:q,mode:'demo'};
}

export function scoreSession(session, questions) {
  check(session && typeof session==='object' && Array.isArray(questions),'練習資料格式不符');
  const responses=session.answers||{};
  const total=questions.length,answered=questions.filter(q=>ABCD.includes(responses[String(q.number)])).length;
  if(session.mode !== 'demo') return {total,answered,unanswered:total-answered,correct:null,percentage:null,officialScore:null};
  const correct=questions.filter(q=>q.answer===responses[String(q.number)]).length;
  return {total,answered,unanswered:total-answered,correct,percentage:total?Math.round(correct*100/total):0,officialScore:null};
}

export function freshStore(){return {schema:LAB_SCHEMA,version:1,imported:null,session:null,history:[]};}
export function checkStored(v){
  check(v && typeof v==='object' && v.schema===LAB_SCHEMA && v.version===1 && Array.isArray(v.history) && v.history.length<=50, '本機學習資料版本不相容');
  check(v.session===null || (v.session && ['demo','official'].includes(v.session.mode) &&
    ['active','completed'].includes(v.session.status) && typeof v.session.setId==='string' &&
    v.session.answers && typeof v.session.answers==='object' && !Array.isArray(v.session.answers)), '本機進度格式不相容');
  check(v.imported===null || (v.imported && v.imported.version===1 && v.imported.officialFinalAnswersConfirmed===false &&
    Array.isArray(v.imported.papers) && v.imported.papers.length<=12), '本機候審資料格式不相容');
  if (v.imported) for (const p of v.imported.papers) {
    check(p && typeof p.id==='string' && p.id.length<=160 && typeof p.subject==='string' && p.subject.length<=240 &&
      officialUrl(p.questionUrl) && (!p.standardUrl || officialUrl(p.standardUrl)) &&
      (!p.correctionUrl || officialUrl(p.correctionUrl)) && Array.isArray(p.questions) && p.questions.length<=100,
      '本機候審試卷來源或格式不安全');
    for(const q of p.questions) check(q && Number.isInteger(q.number) && q.number>0 && q.number<=100 &&
      typeof q.stem==='string' && q.stem.length<=2500 && Array.isArray(q.options) && q.options.length===4 &&
      q.options.every(option=>typeof option==='string'&&option.length<=2000) &&
      (q.publishedCandidate===null || ABCD.includes(q.publishedCandidate)), '本機候審題目資料損壞');
  }
  return v;
}
