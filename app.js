import { OFFICIAL_PAPERS, PRACTICE_QUESTIONS, RUBRIC, LAW_SOURCES, OFFICIAL_SEARCH_URL } from './data.js';
import { MCQ_ITEMS } from './quiz.js';
import {LAB_STORAGE_KEY,checkStored} from './practice-core.mjs';
import {buildCatalog,filterCatalog,sourceCounts} from './catalog-core.mjs';
import {readCandidateFeed,combinedCandidatePapers} from './candidate-feed.mjs';

const STORAGE_KEY = 'lexflow-data-v02';
const LEGACY_STORAGE_KEY = 'lexflow-data-v01';
const VERSION = 2;
const LEGAL_AI_VERIFIED = false; // Legal-source verifier not yet implemented: NO official legal grades
const ALL_ITEMS = [...PRACTICE_QUESTIONS, ...OFFICIAL_PAPERS];
const LABELS = {bank:'題庫',practice:'練習',records:'批改',dashboard:'成長'};
const PAGE_LABELS = {...LABELS,settings:'設定'};
const defaultSettings = {theme:'system',backupReminder:true};
const icons={
 dashboard:'<rect x="3" y="3" width="8" height="8" rx="2"/><rect x="13" y="3" width="8" height="5" rx="2"/><rect x="13" y="10" width="8" height="11" rx="2"/><rect x="3" y="13" width="8" height="8" rx="2"/>',
 bank:'<rect x="4" y="3" width="16" height="18" rx="2"/><path d="M8 7h8M8 11h8M8 15h6"/>',
 practice:'<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3l-11 11L4 19l1.5-4.5Z"/>',
 records:'<path d="M3 12a9 9 0 1 0 3-6.7"/><path d="M3 4v5h5M12 7v5l4 2"/>',
 settings:'<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .34 1.9l-1.7 1.7a1.7 1.7 0 0 0-1.9-.34l-.95.4v2.35h-2.4v-2.35l-1-.4a1.7 1.7 0 0 0-1.9.34l-1.7-1.7a1.7 1.7 0 0 0 .35-1.9l-.4-.95H5.8v-2.4h2.35l.4-1a1.7 1.7 0 0 0-.35-1.9l1.7-1.7a1.7 1.7 0 0 0 1.9.35l1-.4V5.7h2.4V8l.95.4a1.7 1.7 0 0 0 1.9-.35l1.7 1.7a1.7 1.7 0 0 0-.34 1.9l.4 1h2.35v2.4h-2.35z" transform="translate(-2 -2) scale(1.15)"/>',
 plus:'<path d="M12 5v14M5 12h14"/>',
 arrow:'<path d="M4 12h16M14 6l6 6-6 6"/>',
 clock:'<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
 book:'<path d="M4 4h6c2 0 2 2 2 2s0-2 2-2h6v15h-6c-2 0-2 2-2 2s0-2-2-2H4zM12 6v15"/>',
 shield:'<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10Z"/><path d="m9 12 2 2 4-4"/>',
 cpu:'<rect x="6" y="6" width="12" height="12" rx="2"/><path d="M9 2v4m6-4v4M9 18v4m6-4v4M2 9h4m-4 6h4m12-6h4m-4 6h4"/>',
 clipboard:'<rect x="5" y="5" width="14" height="16" rx="2"/><rect x="9" y="2" width="6" height="5" rx="1"/><path d="M9 12h6M9 16h4"/>',
 alert:'<circle cx="12" cy="12" r="9"/><path d="M12 7v6M12 17h.01"/>',
 check:'<path d="m5 12 5 5 9-10"/>',
 external:'<path d="M14 3h7v7M10 14 21 3"/><path d="M18 13v7H4V6h7"/>',
 save:'<path d="M4 3h14l3 3v15H3V3zM7 3v7h10V3M7 21v-8h10v8"/>',
 upload:'<path d="M12 16V3m-5 5 5-5 5 5M4 17v4h16v-4"/>',
 download:'<path d="M12 3v13m-5-5 5 5 5-5M4 17v4h16v-4"/>',
 list:'<path d="M9 6h12M9 12h12M9 18h12M3 6h.01M3 12h.01M3 18h.01"/>',
 light:'<circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l2 2m10 10 2 2m0-14-2 2M7 17l-2 2"/>',
 moon:'<path d="M20.6 13a8.5 8.5 0 1 1-9.6-9.6A7 7 0 0 0 20.6 13Z"/>'
};
function ico(name,size=20){return `<svg aria-hidden="true" width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${icons[name]||icons.book}</svg>`;}
function esc(s=''){return String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
function date(s){return s?new Intl.DateTimeFormat('zh-TW',{year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'}).format(new Date(s)):'—';}
function uid(){return (typeof crypto !== 'undefined'&&crypto.randomUUID)?crypto.randomUUID():`id-${Date.now()}-${Math.random().toString(36).slice(2,8)}`;}
function durationFormat(ms){const sec=Math.floor(Math.max(0,ms)/1000);return `${String(Math.floor(sec/60)).padStart(2,'0')}:${String(sec%60).padStart(2,'0')}`;}
function countChars(v){return Array.from(String(v||'').replace(/\s/g,'')).length;}
function clone(v){return JSON.parse(JSON.stringify(v));}
let readOnlyMode=false,rawToRecover=null,lastPersistError='';
function freshState(){return {version:VERSION,settings:clone(defaultSettings),attempts:[],quizAttempts:[],draft:null,customQuestions:[]};}
function normalizeState(v){return {...freshState(),...v,version:VERSION,settings:{...defaultSettings,...(v.settings||{})},quizAttempts:Array.isArray(v.quizAttempts)?v.quizAttempts:[]};}
function isValidStored(v,vnum){return !!(v && v.version===vnum && Array.isArray(v.attempts) && Array.isArray(v.customQuestions) && (vnum===1 || Array.isArray(v.quizAttempts)) && v.attempts.every(a=>a && typeof a.id==='string' && typeof a.answer==='string' && typeof a.questionText==='string'));}
function readState(){
  let raw=null,origin=STORAGE_KEY;
  try{raw=localStorage.getItem(STORAGE_KEY);if(raw===null){raw=localStorage.getItem(LEGACY_STORAGE_KEY);origin=LEGACY_STORAGE_KEY;}}
  catch(e){readOnlyMode=true;lastPersistError='瀏覽器儲存空間無法存取，已啟用唯讀保護。';return freshState();}
  if(raw===null) return freshState();
  let data;
  try{data=JSON.parse(raw);}catch(e){readOnlyMode=true;rawToRecover=raw;lastPersistError='既有紀錄格式無法辨識，已停止寫入以防覆蓋。';return freshState();}
  const expected=origin===STORAGE_KEY?VERSION:1;
  if(!isValidStored(data,expected)){readOnlyMode=true;rawToRecover=raw;lastPersistError='發現未知或不相容的資料版本。已啟動唯讀模式，請先匯出原始資料。';return freshState();}
  const result=normalizeState(data);
  if(origin===LEGACY_STORAGE_KEY){
    try{const value=JSON.stringify(result);localStorage.setItem(STORAGE_KEY,value);if(localStorage.getItem(STORAGE_KEY)!==value)throw Error('新版本寫入驗證失敗');}
    catch(e){readOnlyMode=true;rawToRecover=raw;lastPersistError='舊版紀錄讀取成功，但無法安全建立新版本副本，已停止寫入。';}
  }
  return result;
}
let state=readState();let tab='bank',selectedRecord=null,bankFilter={subject:'全部',kind:'全部',search:''};let structureVisible=false,toastHandle=0,busy=false;
let bankMode='unified', quizActiveId=null,quizAnswer=null,quizResult=null,quizSubject='全部',recordMode='essay';
const unifiedFilter={area:'全部',type:'全部',source:'全部',search:''};
let automaticPapers=[], automaticStatus='loading';
function save(){
  if(readOnlyMode){lastPersistError=lastPersistError||'目前為唯讀安全模式，無法保存。';return false;}
  try{const value=JSON.stringify(state);localStorage.setItem(STORAGE_KEY,value);if(localStorage.getItem(STORAGE_KEY)!==value)throw Error('寫入後讀取不一致');lastPersistError='';return true;}
  catch(e){lastPersistError='儲存失敗：本次變更尚未可靠寫入。請不要關閉頁面，立即匯出 JSON 備份。';showPersistAlert();return false;}
}
function showPersistAlert(){let el=document.getElementById('persist-warning');if(!el){el=document.createElement('div');el.id='persist-warning';el.className='persist-warning';el.setAttribute('role','alert');document.body.appendChild(el);}el.textContent=lastPersistError;}

function notify(message){document.querySelector('.toast')?.remove();const el=document.createElement('div');el.className='toast';el.role='status';el.textContent=message;document.body.append(el);clearTimeout(toastHandle);toastHandle=setTimeout(()=>el.remove(),3400);}
function selectedItem(id){return [...ALL_ITEMS,...state.customQuestions].find(x=>x.id===id);}
function elapsedMs(draft=state.draft){return draft?draft.usedMs+(draft.runningSince?Math.max(0,Date.now()-draft.runningSince):0):0;}
function stopTimer(){if(state.draft?.runningSince){state.draft.usedMs=elapsedMs();state.draft.runningSince=null;return save();}return true;}
function applyTheme(){document.documentElement.dataset.theme=state.settings.theme==='system'?(window.matchMedia?.('(prefers-color-scheme: dark)').matches?'dark':'light'):(state.settings.theme==='dark'?'dark':'light');}
function makeDraft(item){return {sourceId:item.id,kind:item.kind,subject:item.subject,title:item.title,sourceUrl:item.url||'',questionText:item.question||'',referencePoints:item.points||[],answer:'',minutes:item.kind==='official'?45:item.duration||30,usedMs:0,runningSince:null,updatedAt:new Date().toISOString()};}
function startQuestion(id){const item=selectedItem(id);if(!item)return;if(state.draft?.answer.trim()&&state.draft.sourceId!==id&&!window.confirm('目前草稿尚未存成練習紀錄，切換題目會覆蓋草稿。確定切換嗎？'))return;const previous=state.draft;state.draft=makeDraft(item);if(!save()){state.draft=previous;notify('無法安全儲存新草稿，請先備份。');return;}structureVisible=false;selectedRecord=null;go('practice');}
function go(next){if(!PAGE_LABELS[next])return;if(next==='bank'&&tab!=='bank'){quizActiveId=null;quizResult=null;quizAnswer=null;}tab=next;render();window.scrollTo({top:0,behavior:'instant'});}
function navMarkup(){return Object.keys(LABELS).map(k=>`<button type="button" class="${tab===k?'active':''}" data-action="tab" data-tab="${k}" aria-current="${tab===k?'page':'false'}">${ico(k)}<span>${LABELS[k]}</span></button>`).join('');}
function layout(content){return `<div class="shell"><aside><div class="brand"><span class="brand-mark">L</span><span><strong class="brand-title">LexFlow</strong><br><small>法律雙軌訓練</small></span></div><nav class="nav">${navMarkup()}</nav><footer>V0.3 候審 · 不提供未經驗證的法律 AI 給分</footer></aside><main><div class="main-head"><span class="crumb">LEXFLOW / ${PAGE_LABELS[tab]}</span><div class="head-right"><span class="pill green">獨立測試版</span><button class="mini-action" type="button" aria-label="切換深淺色" data-action="theme">${ico('light',17)}</button><button class="mini-action" type="button" aria-label="設定與備份" data-action="tab" data-tab="settings">${ico('settings',17)}</button></div></div>${readOnlyMode?`<div class="critical" role="alert"><strong>已啟用唯讀安全模式</strong><p>${esc(lastPersistError)}</p><button class="btn small" data-action="export-raw">下載原始資料</button></div>`:''}${lastPersistError&&!readOnlyMode?`<div class="critical" role="alert">${esc(lastPersistError)}</div>`:''}${content}<div class="footnote">LexFlow 非官方國考系統。官方原題、編寫練習與 AI 內容分別標示；請以官方最新公告及有效法源為準。</div></main><nav class="bottom-nav" aria-label="主選單">${navMarkup()}</nav></div>`;}
function heading(eyebrow,title,sub){return `<header class="page-heading"><div class="eyebrow">${eyebrow}</div><h1>${title}</h1><p>${sub}</p></header>`;}
function dashboard(){const n=state.attempts.length;const minutes=Math.round(state.attempts.reduce((v,a)=>v+(a.elapsedMs||0),0)/60000);const totalQuiz=state.quizAttempts.length;const avg=totalQuiz?Math.round(state.quizAttempts.filter(a=>a.correct).length/totalQuiz*100)+'%':'—';const recent=state.attempts.slice(0,3);return `${heading('PERSONAL LEGAL TRAINING','追蹤你的法律學習。','雙軌申論與選擇題紀錄，各自計算，不以未驗證 AI 分數代表考試能力。')}<div class="stats"><div class="stat"><b>${n}</b><span>已保存作答</span></div><div class="stat"><b>${minutes}<small style="font-size:12px"> 分</small></b><span>累積作答時間</span></div><div class="stat"><b>${avg}</b><span>選擇題練習答對率</span></div></div><div class="grid"><div class="panel"><div class="eyebrow">QUICK START</div><h2>今天開始一題</h2><p class="muted">先用自編題練結構，再挑戰考選部官方原卷。系統將自動保存你的草稿。</p><div class="actions"><button class="btn primary" data-action="open-first">${ico('practice',17)} 開始練習</button><button class="btn" data-action="tab" data-tab="bank">查看歷屆原卷 ${ico('arrow',16)}</button></div></div><div class="panel"><div class="eyebrow">HOW IT WORKS</div><h2>批改分兩個層級</h2><p class="muted">結構初檢可直接離線使用；實質法律批改需要具備可核驗的法源與本機模型；目前尚未啟用。結構初檢不代表法律正確性。</p><div class="meta"><span class="pill green">離線結構檢查</span><span class="pill">AI 批改尚未開放</span><span class="pill">法源待查證</span></div></div></div><div class="panel"><div class="align-between"><h2>最近的作答</h2><button class="btn ghost small" data-action="tab" data-tab="records">查看全部 ${ico('arrow',15)}</button></div>${recent.length?recent.map(a=>`<div class="list-item"><div><strong>${esc(a.title)}</strong><br><span>${esc(a.subject)} · ${date(a.submittedAt)}</span></div><button class="btn small" data-action="view-record" data-id="${esc(a.id)}">查看</button></div>`).join(''):'<p class="muted">還沒有紀錄。完成第一篇申論後，這裡會顯示你的歷程。</p>'}</div><div class="notice">所有作答目前都留在此瀏覽器的本機儲存空間。更換裝置、清除網站資料前，請先到設定頁匯出備份。</div>`;}
function bank(){if(quizActiveId)return quizPractice();if(bankMode==='unified')return unifiedBank();if(bankMode==='mcq')return quizBank();const items=[...PRACTICE_QUESTIONS,...OFFICIAL_PAPERS,...state.customQuestions];const subjects=['全部',...new Set(items.map(x=>x.subject))];const filtered=items.filter(x=>(bankFilter.subject==='全部'||x.subject===bankFilter.subject)&&(bankFilter.kind==='全部'||x.kind===bankFilter.kind)&&`${x.title} ${x.subject} ${x.year||''} ${x.exam}`.toLowerCase().includes(bankFilter.search.toLowerCase()));return `${heading('QUESTION LIBRARY','題庫','學術申論與國考雙軌練習；官方原卷和自編題嚴格區分。')}${bankSwitch()}<div class="searchrow"><input id="bank-search" value="${esc(bankFilter.search)}" placeholder="搜尋科目、題名、年度…" aria-label="搜尋試題"><select id="bank-subject" aria-label="科目篩選">${subjects.map(s=>`<option value="${esc(s)}" ${bankFilter.subject===s?'selected':''}>${esc(s)}</option>`).join('')}</select><select id="bank-kind" aria-label="題型篩選"><option value="全部" ${bankFilter.kind==='全部'?'selected':''}>全部來源</option><option value="official" ${bankFilter.kind==='official'?'selected':''}>官方原卷</option><option value="practice" ${bankFilter.kind==='practice'?'selected':''}>自編／自建</option></select></div><div id="bank-items">${renderBankItems(filtered)}</div><div class="panel"><h2>本機 AI 自編申論題</h2><p class="muted">依科目及指定爭點產生模擬題，（不會標示為歷屆官方試題）。本功能需先在手機上啟動本機模型。</p><div class="searchrow"><select id="generate-subject" aria-label="出題科目"><option>民法</option><option>刑法</option><option>憲法</option><option>行政法</option><option>民事訴訟法</option><option>刑事訴訟法</option><option>商事法</option></select><select id="generate-level" aria-label="出題難度"><option value="入門">入門</option><option value="國考進階" selected>國考進階</option><option value="高難度">高難度</option></select><input id="generate-topic" placeholder="指定爭點（選填，例如：善意取得）" maxlength="80"></div><button class="btn" disabled title="尚未通過法源驗證">${ico('cpu',17)} AI 出題待驗證</button></div><div class="panel"><h2>自己建立新題目</h2><p class="muted">可把考選部 PDF 中的某一個完整小題、課堂申論題或自己的練習題貼進來，並記錄來源。</p><button class="btn" data-action="new-question">${ico('plus',17)} 新增自訂題</button></div><div class="panel"><h2>V0.3 多題學習室（候審測試）</h2><p class="muted">可一次作答多道自編法條示範題，也可私人匯入官方候審 JSON 進行不計分自測；兩種資料來源清楚區分。</p><a class="btn primary" href="./practice-lab.html">開啟多題練習室 ↗</a></div><div class="panel"><h2>官方國考試卷索引（候審）</h2><p class="muted">獨立的考選部開放資料索引；僅提供試卷連結，不提供尚未查核的逐題答案或詳解。</p><a class="btn" href="./official-index.html">查看官方試卷索引 ↗</a></div><div class="notice">考選部原卷由官方網站提供。本系統僅連結原始檔案，不將節錄內容誤標為完整原題，也不提供假冒的官方標準擬答。</div>`;}
function renderBankItems(items){return items.length?items.map(item=>`<article class="paper-card"><div><div class="meta"><span class="pill ${item.kind==='official'?'green':''}">${item.kind==='official'?'考選部官方原卷':'自編／自建練習'}</span><span class="pill">${esc(item.subject)}</span>${item.year?`<span class="pill">民國${item.year}年</span>`:''}</div><h3>${esc(item.title)}</h3><p>${esc(item.exam)} · ${item.kind==='official'?'原卷含多題，請選題貼入編輯器':'建議練習 '+item.duration+' 分鐘'}</p></div><div class="right"><div class="actions">${item.url?`<a class="btn small" href="${esc(item.url)}" target="_blank" rel="noopener noreferrer">官方試卷 ${ico('external',14)}</a>`:''}<button class="btn primary small" data-action="start-question" data-id="${esc(item.id)}">${item.kind==='official'?'選此試卷':'開始作答'}</button></div></div></article>`).join(''):'<div class="blank">沒有符合條件的題目。試著更換篩選條件。</div>';}

function readImportedCatalog(){
  // Read-only: never touch the V0.2 storage key or modify the lab's local JSON.
  try{
    const text=localStorage.getItem(LAB_STORAGE_KEY);
    if(text===null)return {papers:[],problem:false};
    const state=checkStored(JSON.parse(text));
    return {papers:combinedCandidatePapers(state.imported?.papers||[],[],state.remotePaper),problem:false};
  }catch{return {papers:[],problem:true};}
}
function unifiedCatalogue(){
  const lab=readImportedCatalog();
  return {lab,records:buildCatalog({essays:PRACTICE_QUESTIONS,officialPapers:OFFICIAL_PAPERS,
    selfMcq:MCQ_ITEMS,customEssays:state.customQuestions,importedPapers:combinedCandidatePapers(lab.papers,automaticPapers)})};
}
function catalogItems(){
  const {records,lab}=unifiedCatalogue();
  const visible=filterCatalog(records,unifiedFilter);
  const note=lab.problem?'<div class="notice">本機候審資料格式無法辨識；僅停止顯示這部分資料，原有紀錄沒有被修改。可在學習室匯出原始備份。</div>':
    !lab.papers.length&&!automaticPapers.length?`<div class="catalog-hint">${automaticStatus==='loading'?'正在檢查候審資料…':automaticStatus==='not_published'?'本站尚未發布可自動載入的候審資料；仍可在多題學習室自行匯入。':'官方候審來源未通過驗證或暫時無法存取，已保持隔離。'}</div>`:
    automaticPapers.length?`<div class="catalog-hint">已自動取得 ${automaticPapers.length} 份官方候審試卷（僅供私人自測、未核對最終答案、不計分），不會覆蓋本機紀錄。</div>`:'';
  return `<div class="catalog-count" role="status">符合條件：<b>${visible.length}</b> 筆 · 官方候審選擇題僅供自測、不計分</div>${note}<div class="catalog-list">${visible.length?visible.map(p=>{
    const pill=p.source==='官方候審'?'status-pending':p.source==='官方原卷'?'status-official':'status-authored';
    const action=p.action==='essay'?`<button class="btn primary small" type="button" data-action="start-question" data-id="${esc(p.id)}">${p.source==='官方原卷'?'選題寫申論':'開始申論'}</button>`:
      p.action==='single-mcq'?`<button class="btn primary small" type="button" data-action="start-quiz" data-id="${esc(p.id)}">練習單題</button>`:
      `<a class="btn primary small" href="./practice-lab.html?paper=${encodeURIComponent(p.id)}#official-papers">開始候審自測</a>`;
    const extra=p.source==='官方原卷'&&p.url?`<a class="btn small" href="${esc(p.url)}" rel="noopener noreferrer" target="_blank">官方 PDF ↗</a>`:'';
    return `<article class="catalog-entry"><div class="catalog-entry-main"><div class="catalog-tags"><span class="catalog-tag ${pill}">${esc(p.source)}</span><span class="catalog-tag">${esc(p.type)}</span><span class="catalog-tag">${esc(p.subject)}</span></div><h3>${esc(p.title)}</h3><p class="catalog-description">${esc(p.description)}${p.count>1?' · '+p.count+' 題':''}</p><p class="catalog-warning">${esc(p.warning)}</p></div><div class="catalog-entry-actions">${action}${extra}</div></article>`;
  }).join(''):'<div class="blank">沒有符合篩選的題目；可調整科目、題型或來源。</div>'}</div>`;
}
function unifiedBank(){
  const records=unifiedCatalogue().records,c=sourceCounts(records);
  const options=(values,current)=>values.map(v=>`<option value="${esc(v)}" ${current===v?'selected':''}>${esc(v)}</option>`).join('');
  return `${heading('ONE QUESTION LIBRARY','統一題庫','同一入口查找申論、選擇題、自編教材與官方候審試卷。各種來源分開標示，不混淆答案與正式成績。')}${bankSwitch()}
    <div class="catalog-summary"><span>申論題 <b>${c.essay}</b></span><span>自編選擇題 <b>${c.authored}</b></span><span>官方候審試卷 <b>${c.official}</b></span></div>
    <div class="catalog-shortcuts"><a class="btn primary small" href="./practice-lab.html">連續練習選擇題 →</a><a class="btn small" href="./official-index.html">官方試卷索引 ↗</a></div>
    <div class="catalog-filter" role="search"><label>科目<select id="unified-area">${options(['全部','民法','刑法','憲法','其他'],unifiedFilter.area)}</select></label>
      <label>題型<select id="unified-type">${options(['全部','申論','選擇題'],unifiedFilter.type)}</select></label>
      <label>來源<select id="unified-source">${options(['全部','自編','官方原卷','官方候審'],unifiedFilter.source)}</select></label>
      <label class="catalog-search">關鍵字<input id="unified-search" type="search" maxlength="150" value="${esc(unifiedFilter.search)}" placeholder="搜尋題名、法科或考試年度…"></label></div>
    <div id="unified-results">${catalogItems()}</div>
    <div class="notice">官方原卷申論題需由你選取完整題目後貼入編輯器。官方候審選擇題若已有經審查的本站靜態候審資料，將自動顯示；否則可在學習室自行匯入。所有候審題均不核定國考分數。</div>`;
}
function bankSwitch(){return `<div class="switcher" role="group" aria-label="題庫導覽"><button class="${bankMode==='unified'?'selected':''}" data-action="mode-unified">統一題庫</button><button class="${bankMode==='essay'?'selected':''}" data-action="mode-essay">申論編輯器</button><button class="${bankMode==='mcq'?'selected':''}" data-action="mode-mcq">自編單題</button></div>`;}
function quizBank(){const visible=MCQ_ITEMS.filter(q=>quizSubject==='全部'||q.subject===quizSubject);return `${heading('QUESTION LIBRARY','選擇題與詳解','六道自編法條核對練習，附全部選項理由及官方法條連結。尚非考選部歷屆真題。')}${bankSwitch()}<div class="notice"><strong>出處狀態：</strong>目前六題均為依官方法條編寫的示範題；並無考選部原題或官方選擇題答案。正式國考選擇題將在原題、答案更正與逐項詳解完成查核後分批新增。</div><div class="searchrow"><select id="quiz-subject" aria-label="選擇題科目">${['全部','民法','刑法','憲法'].map(v=>`<option ${quizSubject===v?'selected':''}>${v}</option>`).join('')}</select></div><div class="quiz-list">${visible.map(q=>`<article class="paper-card"><div><div class="meta"><span class="pill">自編法條核對</span><span class="pill">${esc(q.subject)}</span><span class="pill">${esc(q.topic)}</span></div><h3>${esc(q.title)}</h3><p>${esc(q.source)} · 含 A–D 各選項解析</p></div><div class="right"><button class="btn primary small" data-action="start-quiz" data-id="${esc(q.id)}">開始練習 ${ico('arrow',15)}</button></div></article>`).join('')}</div><div class="panel"><h2>考選部歷屆測驗式試題</h2><p class="muted">官方題目與正式答案入口已保留，尚未逐題匯入本機正式題庫。</p><div class="actions"><a class="btn" href="${esc(OFFICIAL_SEARCH_URL)}" target="_blank" rel="noopener noreferrer">官方試題及答案查詢 ${ico('external',15)}</a><a class="btn" href="https://data.gov.tw/dataset/170565" target="_blank" rel="noopener noreferrer">官方試卷開放資料 ${ico('external',15)}</a><a class="btn" href="./official-index.html">LexFlow 試卷候審索引 ↗</a><a class="btn primary" href="./practice-lab.html">V0.3 多題練習室 ↗</a></div></div>`;}
function quizPractice(){const q=MCQ_ITEMS.find(x=>x.id===quizActiveId);if(!q){quizActiveId=null;return quizBank();}const completed=quizResult&&quizResult.questionId===q.id;return `${heading('MULTIPLE CHOICE','選擇題練習',`自編練習 · ${esc(q.subject)} · ${esc(q.source)}`)}<div class="actions" style="margin-bottom:16px"><button class="btn small" data-action="back-quiz">← 返回選擇題題庫</button><span class="pill">不是官方歷屆試題</span></div><div class="panel"><div class="meta"><span class="pill green">${esc(q.subject)}</span><span class="pill">${esc(q.topic)}</span></div><h2 style="margin-top:14px">${esc(q.question)}</h2><div class="quiz-options">${q.options.map((option,i)=>`<label class="quiz-option ${completed?(i===q.answer?'correct-option':i===quizAnswer?'wrong-option':''):''}"><input type="radio" name="quiz-answer" value="${i}" ${quizAnswer===i?'checked':''} ${completed?'disabled':''}/><span class="option-letter">${'ABCD'[i]}</span><span>${esc(option)}</span></label>`).join('')}</div>${completed?`<div class="result-banner"><strong>${quizAnswer===q.answer?'答對了':'這題答錯了'}</strong><span>正確答案：${'ABCD'[q.answer]}（自編題參考答案，非官方考試答案）</span></div><h2>逐選項詳解</h2><div class="explain-list">${q.notes.map((n,i)=>`<div class="explain-row"><strong>${'ABCD'[i]}.</strong><span>${esc(n)}</span></div>`).join('')}</div><div class="notice">法源：${esc(q.source)}。本題依條文編寫；如法律修正，須重新核對。</div><a class="btn" href="${esc(q.sourceUrl)}" target="_blank" rel="noopener noreferrer">前往官方法條 ${ico('external',15)}</a><button class="btn" data-action="quiz-retry">重新作答</button>`:`<button class="btn primary" data-action="quiz-submit" ${quizAnswer===null?'disabled':''}>交卷並查看完整詳解</button>`}</div>`;}
function structuralCheck(answer){const text=String(answer||'');const compact=text.replace(/\s/g,'');return [
{label:'是否分段並建立架構',ok:/(?:一、|二、|（一）|\(一\)|首先|其次|第一|第二|壹、|1[\.、])/.test(text),tip:'使用爭點、規範、涵攝、結論等清楚層次。'},
{label:'是否明示規範或法律要件',ok:/(第\s*[0-9０-９一二三四五六七八九十百]+\s*條|民法|刑法|憲法|行政程序法|要件|構成要件|比例原則|法律保留)/.test(text),tip:'明確揭示相關條文或法律要件；檢查引用正確性。'},
{label:'是否有實際事實涵攝',ok:/(本件|本案|依題示|題示|就甲|就乙|因甲|由於甲|故本件|於本題)/.test(text),tip:'逐一連結題目事實與法律要件，避免只背定義。'},
{label:'是否呈現分析與理由',ok:/(然而|惟|但|因此|蓋|理由|可能|若|是否|反之|依此|縱使|爭議|學說|實務)/.test(text),tip:'處理不同主張、必要反論與例外情形。'},
{label:'是否提出明確結論',ok:/(綜上|綜合上述|結論|故甲|故乙|因此.*(?:成立|不成立|有理由|無理由)|應認為|應可認為|故應)/s.test(text),tip:'針對每個子問題給出明確、可辨識的結論。'},
{label:'作答是否具備基本篇幅',ok:countChars(text)>=180,tip:'這只是提醒檢查論證完整性；長短不能直接代表答案品質。'}];}
function practice(){if(!state.draft)return `${heading('WRITING STUDIO','限時申論練習','從題庫選擇題目，即可在手機上開始作答。')}<div class="blank"><div class="empty-icon">✍</div>目前沒有開啟中的題目。<br><br><button class="btn primary" data-action="tab" data-tab="bank">選擇申論題</button></div>`;const d=state.draft,struct=structuralCheck(d.answer);const wordCount=countChars(d.answer);const official=d.kind==='official';const notice=official?`<div class="notice">請先點「開啟官方原卷」，選擇完整的題號與子題，將題目完整貼在下方。原卷尚未自動逐題擷取。</div>`:'';return `${heading('WRITING STUDIO', '限時申論練習', '草稿會在此裝置自動保存；完成後可進行結構初檢與 AI 批改。')}<div class="editor-head"><span class="pill ${official?'green':''}">${official?'官方原卷來源':'自編／自建練習'} · ${esc(d.subject)}</span><div class="actions"><span class="timer" id="timer-label">${durationFormat(elapsedMs())}</span><button class="btn small" data-action="toggle-timer">${d.runningSince?'暫停':'開始計時'}</button><button class="btn small" data-action="reset-timer">重設</button></div></div><div class="split"><section class="panel"><div class="align-between"><h2>${esc(d.title)}</h2>${d.sourceUrl?`<a href="${esc(d.sourceUrl)}" target="_blank" rel="noopener noreferrer" class="btn small">原卷 ${ico('external',14)}</a>`:''}</div>${notice}<label class="label" for="question-edit">題目</label>${official?`<textarea id="question-edit" class="field" placeholder="請從官方原卷中貼上完整題目與必要事實，確認沒有遺漏子題。">${esc(d.questionText)}</textarea>`:`<div class="question-block">${esc(d.questionText)}</div>`}${d.referencePoints.length?`<div class="divider"></div><div class="hint">自編題提示（不是標準答案；建議作答後再看）</div><details><summary>展開出題者預期檢討方向</summary><ul class="keypoints">${d.referencePoints.map(p=>`<li>${esc(p)}</li>`).join('')}</ul></details>`:''}<div class="divider"></div><label class="label" for="duration-edit">預定練習時間（分鐘）</label><input id="duration-edit" type="number" class="field" min="5" max="240" value="${d.minutes}" style="max-width:135px"><p class="hint">計時採累積時間；關閉頁面再回來時仍會計入經過時間，除非先按暫停。</p></section><section class="panel"><div class="align-between"><h2>申論答案</h2><span class="pill" id="char-count">${wordCount} 字</span></div><textarea class="field answer" id="answer-edit" spellcheck="false" placeholder="建議依：請求權／犯罪成立要件／基本權審查 → 法律爭點 → 規範及見解 → 事實涵攝 → 結論，分層書寫。">${esc(d.answer)}</textarea><div class="editor-head"><span class="hint" id="autosave-status">上次儲存：${d.updatedAt?date(d.updatedAt):'尚未開始'}</span><span class="hint">建議 ${d.minutes} 分鐘</span></div><div class="actions"><button class="btn" data-action="structure">${ico('list',17)} 結構初檢</button><button class="btn primary" data-action="submit">${ico('save',17)} 保存作答</button><button class="btn" disabled title="法律法源驗證尚未通過">${ico('cpu',17)} 專業 AI 批改待驗證</button></div>${structureVisible?renderStructure(struct):''}</section></div>`;}
function renderStructure(items){return `<div class="divider"></div><h2>結構初檢 <span class="pill">非法律正確性評分</span></h2><p class="hint">僅用詞與段落線索判斷有無呈現特定結構，不等同於實質爭點與法條正確。</p>${items.map(x=>`<div class="checkrow"><span style="color:${x.ok?'var(--accent)':'var(--danger)'}">${x.ok?'✓':'○'}</span><div><b style="font-size:13px">${esc(x.label)}</b><div class="hint">${esc(x.tip)}</div></div></div>`).join('')}`;}
function records(){if(recordMode==='quiz')return quizHistory();const attempts=state.attempts;if(!attempts.length)return `${heading('PROGRESS ARCHIVE','批改與作答','保留申論原稿與練習記錄。')}${recordSwitch()}<div class="blank">尚無作答紀錄。<br><br><button class="btn primary" data-action="tab" data-tab="bank">前往題庫</button></div>`;const selected=attempts.find(x=>x.id===selectedRecord);return `${heading('FEEDBACK ARCHIVE','批改與作答','保存申論原稿、結構檢查、外部回饋與選擇題解析。')}${recordSwitch()}${selected?detail(selected):`<div class="panel"><h2>全部作答（${attempts.length}）</h2>${attempts.map(a=>`<div class="list-item"><div><strong>${esc(a.title)}</strong><br><span>${esc(a.subject)} · ${date(a.submittedAt)} · ${durationFormat(a.elapsedMs||0)} · ${countChars(a.answer)} 字</span><div class="meta" style="margin-top:6px">${a.aiGrade?.score?`<span class="pill green">AI 參考 ${Object.values(a.aiGrade.score).reduce((s,v)=>s+v,0)} 分</span>`:a.selfScore?`<span class="pill">自評 ${Object.values(a.selfScore).reduce((s,v)=>s+v,0)} 分</span>`:`<span class="pill">尚未實質批改</span>`}</div></div><button class="btn small" data-action="view-record" data-id="${esc(a.id)}">檢視 ${ico('arrow',15)}</button></div>`).join('')}</div>`}`;}

function recordSwitch(){return `<div class="switcher"><button data-action="record-essay" class="${recordMode==='essay'?'selected':''}">申論紀錄</button><button data-action="record-quiz" class="${recordMode==='quiz'?'selected':''}">選擇題紀錄</button></div>`;}
function quizHistory(){return `${heading('ANSWER ARCHIVE','選擇題紀錄','只記錄完成交卷的題目；相同題目不同作答分別保存。')}${recordSwitch()}${state.quizAttempts.length?`<div class="panel"><div class="stats" style="margin:0 0 10px"><div class="stat"><b>${state.quizAttempts.length}</b><span>累積交卷</span></div><div class="stat"><b>${state.quizAttempts.filter(x=>x.correct).length}</b><span>答對次數</span></div><div class="stat"><b>${Math.round(100*state.quizAttempts.filter(x=>x.correct).length/state.quizAttempts.length)}%</b><span>含重複作答</span></div></div>${state.quizAttempts.map(a=>`<div class="list-item"><div><strong>${esc(a.title)}</strong><br><span>${esc(a.subject)} · ${date(a.submittedAt)} · 選 ${esc('ABCD'[a.selected]||'—')}／參考 ${esc('ABCD'[a.correctIndex]||'—')}</span></div><span class="pill ${a.correct?'green':'red'}">${a.correct?'答對':'答錯'}</span></div>`).join('')}</div>`:'<div class="blank">還沒有選擇題交卷紀錄。<br><br><button class="btn primary" data-action="to-quiz">開始選擇題</button></div>'}`;}
function detail(a){const total=a.aiGrade?.score?Object.values(a.aiGrade.score).reduce((s,v)=>s+v,0):null;return `<div class="actions" style="margin-bottom:17px"><button class="btn small" data-action="back-records">← 返回全部紀錄</button><button class="btn small" data-action="retry" data-id="${esc(a.id)}">重做此題</button><button class="btn danger small" data-action="delete-record" data-id="${esc(a.id)}">刪除紀錄</button></div><div class="panel"><div class="meta"><span class="pill">${esc(a.subject)}</span><span class="pill">${date(a.submittedAt)}</span><span class="pill">${durationFormat(a.elapsedMs||0)}</span></div><h2 style="margin-top:10px">${esc(a.title)}</h2><details><summary>展開題目</summary><div class="question-block">${esc(a.questionText)}</div></details><div class="divider"></div><h2>你的答案</h2><div class="question-block">${esc(a.answer)}</div></div><div class="panel"><h2>結構初檢</h2>${renderStructure(structuralCheck(a.answer))}</div>${a.aiGrade?renderAIGrade(a.aiGrade):`<div class="notice">尚無本機 AI 批改意見。你可以使用「複製批改指令」請外部 AI 分析，或回到題目重新作答。</div>`}<div class="panel"><div class="align-between"><h2>自評量表</h2><span class="pill">不是官方分數</span></div><p class="hint">每個維度填寫你自行判斷的分數。可參考課堂或老師意見調整。</p><div class="grid">${RUBRIC.map(r=>`<label><span class="label">${esc(r.label)}（滿分 ${r.max}）</span><input class="field" type="number" min="0" max="${r.max}" data-selfscore="${r.key}" value="${a.selfScore?.[r.key]??''}" placeholder="未評"></label>`).join('')}</div><div class="actions" style="margin-top:15px"><button class="btn primary" data-action="save-selfscore" data-id="${esc(a.id)}">保存自評</button><button class="btn" data-action="copy-review-prompt" data-id="${esc(a.id)}">${ico('clipboard',17)} 複製 AI 批改指令</button></div><div class="divider"></div><label class="label" for="external-comments">外部老師／AI 評語（自行貼入，未經本系統驗證）</label><textarea id="external-comments" class="field textarea-small" placeholder="可把老師講評、課堂筆記或外部 AI 的批改意見貼在這裡。">${esc(a.externalComments||'')}</textarea><button class="btn small" data-action="save-comments" data-id="${esc(a.id)}">保存評語</button></div>`;}
function renderAIGrade(g){const score=g.score||{};const total=Object.values(score).reduce((s,v)=>s+(Number(v)||0),0);return `<div class="panel"><div class="align-between"><h2>本機 AI 參考批改</h2><span class="pill green">${total}/100 · 非官方評分</span></div><p class="hint">本機模型生成；所提法條、案例和判決仍須查證。不能替代教師或正式閱卷。</p><div class="scoregrid">${RUBRIC.map(r=>`<div class="scorecell"><b>${Number(score[r.key]||0)}<small style="font-size:10px;color:var(--muted)">/${r.max}</small></b><span>${r.label}</span></div>`).join('')}</div><div class="divider"></div><h2>優點</h2><ul class="keypoints">${(g.strengths||[]).map(t=>`<li>${esc(t)}</li>`).join('')||'<li>未提供</li>'}</ul><h2>待改善問題</h2><ul class="feedbacklist">${(g.gaps||[]).map(x=>`<li><b>${esc(x.point||'待檢討')}</b><div class="hint">${esc(x.evidence||'')}<br>改善：${esc(x.improvement||'')}</div></li>`).join('')||'<li>未提供</li>'}</ul><h2>建議擬答架構</h2><ol class="keypoints">${(g.outline||[]).map(t=>`<li>${esc(t)}</li>`).join('')||'<li>未提供</li>'}</ol>${(g.lawChecks||[]).length?`<h2>法源查核提醒</h2><ul class="keypoints">${g.lawChecks.map(t=>`<li>${esc(t.citation||'法源')}：${esc(t.status||'待查證')} — ${esc(t.note||'')}</li>`).join('')}</ul>`:''}${g.rewriteExample?`<h2>寫作示範片段</h2><div class="question-block">${esc(g.rewriteExample)}</div>`:''}</div>`;}
function settings(){return `${heading('PERSONAL SETTINGS','設定與資料安全','獨立運作、資料可攜、未經授權不連接其他 App。')}<div class="panel"><h2>介面</h2><label class="label" for="theme-select">顯示主題</label><select class="field" id="theme-select"><option value="system" ${state.settings.theme==='system'?'selected':''}>跟隨系統</option><option value="light" ${state.settings.theme==='light'?'selected':''}>淺色模式</option><option value="dark" ${state.settings.theme==='dark'?'selected':''}>深色模式</option></select></div><div class="panel"><h2>我的資料</h2><p class="muted">使用目前瀏覽器的本機儲存空間；與其他網址、裝置不會自動同步。匯入採不覆蓋既有紀錄的合併策略，但仍請保留獨立 JSON 備份。</p><div class="actions"><button class="btn primary" data-action="export">${ico('download',17)} 匯出 JSON 備份</button><button class="btn" data-action="import">${ico('upload',17)} 匯入備份</button></div><input id="file-import" type="file" accept="application/json,.json" hidden><div class="divider"></div><span class="hint">為避免資料意外遺失，本測試版暫停批次刪除功能。</span></div><div class="panel"><h2>官方法源與試題</h2><div class="linklist">${LAW_SOURCES.map(s=>`<a href="${esc(s.url)}" target="_blank" rel="noopener noreferrer">${esc(s.label)} ↗</a>`).join('')}</div><p class="hint" style="margin:13px 0 0">官網資料可能更新，引用前請再次核對時間與現行效力。</p></div><div class="panel"><h2>AI 專業批改狀態</h2><p class="muted">法律資料檢索與來源驗證尚未完成。V0.2 暫不提供 AI 實質給分或自動出題，避免把無法核實的意見當作正確答案。</p><span class="pill red">尚未開放法律 AI 正式批改</span></div><div class="panel"><h2>未來中央控制台連接</h2><p class="muted">第一版保留資料匯出與事件格式，尚未對外開放自動讀寫。未來會使用獨立連接器交換已授權的練習摘要、作答時間與弱點，不會直接覆寫你的目標管理系統。</p><div class="meta"><span class="pill green">獨立 App</span><span class="pill">資料由原 App 管理</span><span class="pill">權限最小化</span></div></div>`;}
function render(){applyTheme();const pages={dashboard,bank,practice,records,settings};document.getElementById('app').innerHTML=layout(pages[tab]());if(lastPersistError&&!readOnlyMode)showPersistAlert();}
function updateClock(){const el=document.getElementById('timer-label');if(el)el.textContent=durationFormat(elapsedMs());}
setInterval(updateClock,1000);
function saveAttempt(){const d=state.draft;if(!d)return null;if(d.kind==='official'&&countChars(d.questionText)<40){notify('請先貼上完整的官方試題，再保存答案');return null;}if(countChars(d.answer)<20){notify('至少輸入 20 字答案再保存，避免產生空白紀錄');return null;}if(!stopTimer())return null;const a={id:uid(),sourceId:d.sourceId,kind:d.kind,subject:d.subject,title:d.title,sourceUrl:d.sourceUrl,questionText:d.questionText,referencePoints:d.referencePoints,answer:d.answer,elapsedMs:elapsedMs(),submittedAt:new Date().toISOString(),aiGrade:null,selfScore:null,externalComments:''};state.attempts.unshift(a);const previousDraft=state.draft;state.draft=null;if(!save()){state.attempts.shift();state.draft=previousDraft;notify('保存未成功：紀錄尚未寫入，答案仍在編輯器。請立即備份。');return null;}return a;}
function promptFor(a){return `請以「臺灣法律國家考試申論批改老師」身分審閱以下作答；你不是官方閱卷委員。請依爭點20分、法規與要件25分、涵攝30分、體系15分、結論10分提供「非官方參考分數」、每個重要漏點、原句問題、可改寫段落與建議擬答架構。凡引述法條、裁判、實務見解，必須附可核對的正式來源；查不到的資訊請明確標記待查證，不得捏造。優先檢查是否漏掉請求權基礎／成立要件、學說與實務歧異、事實涵攝，以及結論是否精確。\n\n【試題】\n${a.questionText}\n\n【考生作答】\n${a.answer}\n\n【參考要點（僅自編練習題提供，非官方標準答案）】\n${(a.referencePoints||[]).join('；')||'無'}\n\n請先給核心問題，再逐點批改；缺乏資料不應假裝已驗證。`;}
async function clipboardWrite(text){try{if(navigator.clipboard&&window.isSecureContext){await navigator.clipboard.writeText(text);return true;}const el=document.createElement('textarea');el.value=text;el.style.position='fixed';el.style.top='-1000px';document.body.appendChild(el);el.select();const ok=document.execCommand('copy');el.remove();return ok;}catch(e){return false;}}
async function requestAIGrade(a){if(busy)return;busy=true;render();notify('正在連接本機 AI，請保持 App 開啟');try{const ctr=new AbortController();const t=setTimeout(()=>ctr.abort(),240000);let res;try{res=await fetch('/api/grade',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({question:a.questionText,answer:a.answer,referencePoints:a.referencePoints||[]}),signal:ctr.signal});}finally{clearTimeout(t);}const data=await res.json();if(!res.ok)throw Error(data.error||'本機模型回應失敗');const target=state.attempts.find(x=>x.id===a.id);if(target){target.aiGrade=data.grade;target.gradedAt=new Date().toISOString();save();}selectedRecord=a.id;tab='records';notify('本機 AI 已完成參考批改（請核對法源）');}catch(e){selectedRecord=a.id;tab='records';notify(`批改未完成：${e.message||'請確認本機服務已啟動'}`);}finally{busy=false;render();}}
function makeDownload(filename,data,mime='application/json'){const b=new Blob([data],{type:mime});const link=document.createElement('a');link.href=URL.createObjectURL(b);link.download=filename;document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(link.href),3000);}
function validateImport(v){return v&&[1,2].includes(v.version)&&Array.isArray(v.attempts)&&v.attempts.length<=30000&&Array.isArray(v.customQuestions)&&v.customQuestions.length<=30000&&v.attempts.every(a=>a&&typeof a.answer==='string'&&typeof a.questionText==='string'&&typeof a.id==='string')&&v.customQuestions.every(q=>q&&typeof q.question==='string'&&typeof q.id==='string')&&(!v.quizAttempts||Array.isArray(v.quizAttempts));}
function addCustomQuestion(){const title=window.prompt('題目名稱（例如：114年律師二試民法第一題）');if(!title?.trim())return;const subject=window.prompt('科目（例如：民法、刑法、行政法）','民法');if(!subject?.trim())return;const content=window.prompt('請貼上完整題目事實與問句（至少 20 字）');if(!content||countChars(content)<20){notify('題目需至少 20 字');return;}const src=window.prompt('來源備註（可留空）','自行整理／請再核對官方來源')||'';const custom={id:uid(),kind:'practice',year:null,exam:src.slice(0,160),subject:subject.slice(0,45),title:title.slice(0,140),duration:35,question:content.slice(0,40000),points:[],sourceNote:src};state.customQuestions.unshift(custom);save();startQuestion(custom.id);}

document.addEventListener('click',async ev=>{
  const el=ev.target.closest('[data-action]');if(!el)return;const action=el.dataset.action,id=el.dataset.id;
  if(readOnlyMode&&!['tab','export-raw','mode-unified','mode-essay','mode-mcq','back-quiz','record-essay','record-quiz'].includes(action)){notify('資料處於唯讀保護，請先備份再處理');return;}
  if(action==='tab')return go(el.dataset.tab);
  if(action==='export-raw'){return makeDownload('LexFlow_incompatible_raw_backup.json',rawToRecover||JSON.stringify(state,null,2),'application/json');}
  if(action==='mode-unified'){bankMode='unified';quizActiveId=null;return render();}
  if(action==='mode-essay'){bankMode='essay';quizActiveId=null;return render();}
  if(action==='mode-mcq'){bankMode='mcq';quizActiveId=null;return render();}
  if(action==='to-quiz'){bankMode='mcq';quizActiveId=null;return go('bank');}
  if(action==='record-essay'){recordMode='essay';selectedRecord=null;return render();}
  if(action==='record-quiz'){recordMode='quiz';selectedRecord=null;return render();}
  if(action==='start-quiz'){if(!MCQ_ITEMS.some(x=>x.id===id))return;quizActiveId=id;quizAnswer=null;quizResult=null;return render();}
  if(action==='back-quiz'){quizActiveId=null;quizAnswer=null;quizResult=null;return render();}
  if(action==='quiz-retry'){quizAnswer=null;quizResult=null;return render();}
  if(action==='quiz-submit'){
    const q=MCQ_ITEMS.find(x=>x.id===quizActiveId);if(!q||quizAnswer===null||quizResult)return;
    const a={id:uid(),questionId:q.id,subject:q.subject,title:q.title,selected:quizAnswer,correctIndex:q.answer,correct:quizAnswer===q.answer,submittedAt:new Date().toISOString(),questionKind:'self-authored-statute'};
    state.quizAttempts.unshift(a);
    if(!save()){state.quizAttempts.shift();notify('交卷結果保存失敗，詳解暫不開放，以免誤認已保存');return;}
    quizResult={questionId:q.id,attemptId:a.id};notify('已保存此次練習');return render();
  }
  if(action==='theme'){const prior=state.settings.theme;state.settings.theme=document.documentElement.dataset.theme==='dark'?'light':'dark';if(!save()){state.settings.theme=prior;return;}return render();}
  if(action==='open-first')return startQuestion(PRACTICE_QUESTIONS[0].id);
  if(action==='start-question')return startQuestion(id);
  if(action==='new-question')return addCustomQuestion();
  if(action==='generate-question'){if(!LEGAL_AI_VERIFIED){notify('AI 出題尚未通過來源查證，已暫停');return;}
    if(busy)return;
    const subject=document.getElementById('generate-subject')?.value||'民法';
    const difficulty=document.getElementById('generate-level')?.value||'國考進階';
    const topic=document.getElementById('generate-topic')?.value||'';
    busy=true;notify('本機 AI 正在出題，請保持畫面開啟');
    try{
      const ctl=new AbortController(),timer=setTimeout(()=>ctl.abort(),240000);
      let res;try{res=await fetch('/api/generate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({subject,difficulty,topic}),signal:ctl.signal});}finally{clearTimeout(timer);}
      const data=await res.json();if(!res.ok)throw Error(data.error||'出題失敗');
      const g=data.question;
      const item={id:uid(),kind:'practice',year:null,exam:'本機 AI 自編模擬題（非官方）',subject:g.subject||subject,title:g.title,duration:35,question:g.question,points:g.points||[],sourceNote:'由本機 AI 自編，非官方國考原題；法條與實務需查證。'};
      state.customQuestions.unshift(item);save();notify('模擬題已加入自訂題庫');startQuestion(item.id);
    }catch(e){notify('無法自動出題：'+(e.message||'請啟動本機 AI'));}
    finally{busy=false;}return;
  }
  if(action==='toggle-timer'){if(!state.draft)return;if(state.draft.runningSince)stopTimer();else state.draft.runningSince=Date.now();save();return render();}
  if(action==='reset-timer'){if(window.confirm('確定將本次練習計時歸零嗎？不會刪除答案。')){state.draft.usedMs=0;state.draft.runningSince=null;save();render();}return;}
  if(action==='structure'){structureVisible=!structureVisible;return render();}
  if(action==='submit'){const a=saveAttempt();if(a){recordMode='essay';selectedRecord=a.id;notify('作答已保存至練習紀錄');go('records');}return;}
  if(action==='ai-grade'){if(!LEGAL_AI_VERIFIED){notify('AI 法律實質批改尚未通過來源查證，已暫停');return;}
    if(!state.draft)return;
    try{
      const ctl=new AbortController(),timer=setTimeout(()=>ctl.abort(),4000);
      let ready;try{const res=await fetch('/api/health',{signal:ctl.signal});ready=(await res.json()).modelReady;}finally{clearTimeout(timer);}
      if(!ready){notify('本機 AI 尚未啟動。你仍可先保存答案、做結構初檢。');return;}
    }catch(e){notify('本機 AI 服務尚未啟動，請至設定頁確認');return;}
    const a=saveAttempt();if(a)await requestAIGrade(a);return;
  }
  if(action==='view-record'){selectedRecord=id;return render();}
  if(action==='back-records'){selectedRecord=null;return render();}
  if(action==='retry'){const a=state.attempts.find(x=>x.id===id);if(!a)return;if(state.draft?.answer.trim()&&!window.confirm('重做此題會取代目前編輯中的草稿，確定繼續嗎？'))return;state.draft={sourceId:a.sourceId,kind:a.kind,subject:a.subject,title:a.title,sourceUrl:a.sourceUrl,questionText:a.questionText,referencePoints:a.referencePoints||[],answer:'',minutes:35,usedMs:0,runningSince:null,updatedAt:new Date().toISOString()};save();structureVisible=false;return go('practice');}
  if(action==='delete-record'){if(!window.confirm('確定永久刪除此筆作答紀錄嗎？請先確認已備份。'))return;state.attempts=state.attempts.filter(x=>x.id!==id);selectedRecord=null;save();notify('紀錄已刪除');return render();}
  if(action==='save-selfscore'){const a=state.attempts.find(x=>x.id===id);if(!a)return;const fields=[...document.querySelectorAll('[data-selfscore]')];if(fields.some(f=>f.value.trim()==='')){notify('請填寫五個評分維度，或暫不保存自評');return;}const out={};for(const f of fields){const rubric=RUBRIC.find(r=>r.key===f.dataset.selfscore);const v=Number(f.value);if(!Number.isInteger(v)||v<0||v>rubric.max){notify(`「${rubric.label}」請輸入 0–${rubric.max} 分`);return;}out[f.dataset.selfscore]=v;}a.selfScore=out;save();notify('自評已保存');return render();}
  if(action==='save-comments'){const a=state.attempts.find(x=>x.id===id);if(!a)return;a.externalComments=document.getElementById('external-comments').value.slice(0,50000);save();notify('補充評語已保存');return;}
  if(action==='copy-review-prompt'){const a=state.attempts.find(x=>x.id===id);if(!a)return;const ok=await clipboardWrite(promptFor(a));notify(ok?'批改指令已複製，可貼至 ChatGPT':'複製失敗，請確認瀏覽器剪貼簿權限');return;}
  if(action==='export'){makeDownload(`LexFlow_V02_backup_${new Date().toISOString().slice(0,10)}.json`,JSON.stringify({...state,exportedAt:new Date().toISOString()},null,2));notify('已準備下載本機備份（請確認檔案已下載）');return;}
  if(action==='import')return document.getElementById('file-import').click();
  if(action==='clear-records'){if(!window.confirm('將刪除全部作答紀錄，且無法復原。確定嗎？'))return;if(!window.confirm('最後確認：你已經匯出備份，並確定要刪除所有練習紀錄？'))return;state.attempts=[];selectedRecord=null;save();notify('已清除練習紀錄，題庫及草稿未刪除');return render();}
  if(action==='check-ai'){const badge=document.getElementById('ai-status');badge.textContent='檢查中…';try{const ctr=new AbortController(),t=setTimeout(()=>ctr.abort(),3500);let res;try{res=await fetch('/api/health',{signal:ctr.signal});}finally{clearTimeout(t);}const j=await res.json();badge.textContent=j.modelReady?'本機模型已連接':'服務已開啟，模型未連接';badge.className=`pill ${j.modelReady?'green':'red'}`;}catch(e){badge.textContent='尚未啟動本機服務';badge.className='pill red';}return;}
});
document.addEventListener('input',ev=>{
  if(ev.target.id==='unified-search'){unifiedFilter.search=ev.target.value;const root=document.getElementById('unified-results');if(root)root.innerHTML=catalogItems();return;}
  if(ev.target.id==='answer-edit'&&state.draft){state.draft.answer=ev.target.value;state.draft.updatedAt=new Date().toISOString();const saved=save();const el=document.getElementById('char-count');if(el)el.textContent=countChars(ev.target.value)+' 字';const ts=document.getElementById('autosave-status');if(ts){ts.textContent=saved?'草稿已保存 · '+date(state.draft.updatedAt):'⚠ 儲存失敗！請勿關閉頁面，立即備份';ts.classList.toggle('text-danger',!saved);}}
  if(ev.target.id==='question-edit'&&state.draft){state.draft.questionText=ev.target.value;state.draft.updatedAt=new Date().toISOString();const saved=save();if(!saved)notify('官方題目尚未保存，請立即匯出備份');}
  if(ev.target.id==='bank-search'){bankFilter.search=ev.target.value;const items=[...PRACTICE_QUESTIONS,...OFFICIAL_PAPERS,...state.customQuestions];document.getElementById('bank-items').innerHTML=renderBankItems(items.filter(x=>(bankFilter.subject==='全部'||x.subject===bankFilter.subject)&&(bankFilter.kind==='全部'||x.kind===bankFilter.kind)&&`${x.title} ${x.subject} ${x.year||''} ${x.exam}`.toLowerCase().includes(bankFilter.search.toLowerCase())));}
});
document.addEventListener('change',async ev=>{
  const f={'unified-area':'area','unified-type':'type','unified-source':'source'}[ev.target.id];
  if(f){unifiedFilter[f]=ev.target.value;const root=document.getElementById('unified-results');if(root)root.innerHTML=catalogItems();return;}
  if(ev.target.name==='quiz-answer'){quizAnswer=Number(ev.target.value);const b=document.querySelector('[data-action="quiz-submit"]');if(b)b.disabled=false;return;}
  if(ev.target.id==='quiz-subject'){quizSubject=ev.target.value;return render();}
  if(ev.target.id==='theme-select'){const old=state.settings.theme;state.settings.theme=ev.target.value;if(!save())state.settings.theme=old;render();}
  if(ev.target.id==='duration-edit'&&state.draft){const n=Number(ev.target.value);state.draft.minutes=Number.isInteger(n)&&n>=5&&n<=240?n:35;save();notify('練習時間已更新');}
  if(ev.target.id==='bank-subject'){bankFilter.subject=ev.target.value;render();}
  if(ev.target.id==='bank-kind'){bankFilter.kind=ev.target.value;render();}
  if(ev.target.id==='file-import'){
    const f=ev.target.files?.[0];if(!f)return;if(f.size>20*1024*1024){notify('備份檔案過大，請先確認資料內容');return;}
    try{const raw=JSON.parse(await f.text());if(!validateImport(raw))throw Error('版本或資料格式不符合');if(!window.confirm(`確認將備份內紀錄「合併」至目前資料嗎？原有 ${state.attempts.length} 筆申論將保留。`))return;
       const prev=clone(state),incoming=normalizeState(raw);
       const mergeUnique=(current,newEntries)=>{const result=[...current];const known=new Set(result.map(x=>x.id));for(const entry of newEntries){if(known.has(entry.id)){const existing=result.find(x=>x.id===entry.id);if(JSON.stringify(existing)!==JSON.stringify(entry)){result.push({...entry,id:uid(),restoredFromId:entry.id});}}else{result.push(entry);known.add(entry.id);}}return result;};
       state.attempts=mergeUnique(state.attempts,incoming.attempts);
       state.customQuestions=mergeUnique(state.customQuestions,incoming.customQuestions);
       state.quizAttempts=mergeUnique(state.quizAttempts,incoming.quizAttempts);
       if(!state.draft&&incoming.draft)state.draft=incoming.draft;
       if(!save()){state=prev;throw Error('合併資料未能安全寫入，已保留原本紀錄');}
       selectedRecord=null;notify('備份已安全合併，原有紀錄保留');render();}catch(e){notify('匯入失敗：'+e.message);}
  }
});
window.LexFlowBridge = Object.freeze({
  version:'0.2',
  getSummary:()=>Object.freeze({schema:'lexflow.summary.v1',app:'lexflow',totalAttempts:state.attempts.length,totalMinutes:Math.round(state.attempts.reduce((s,a)=>s+(a.elapsedMs||0),0)/60000),lastPracticeAt:state.attempts[0]?.submittedAt||null,quizAttempts:state.quizAttempts.length}),
  exportAll:()=>clone(state)
});
applyTheme();render();
async function refreshAutomaticPapers(){
  const feed=await readCandidateFeed();
  automaticPapers=feed.papers;
  automaticStatus=feed.status;
  // Read-only update to display only; never writes private study/localStorage keys.
  if(tab==='bank' && bankMode==='unified' && !quizActiveId){
    const results=document.getElementById('unified-results');
    if(results){
      const count=sourceCounts(unifiedCatalogue().records);
      const summary=document.querySelector('.catalog-summary');
      if(summary){const parts=summary.querySelectorAll('b');if(parts.length===3)parts[2].textContent=String(count.official);}
      results.innerHTML=catalogItems();
    }
  }
}
if(location.protocol==='https:'||location.protocol==='http:')void refreshAutomaticPapers();
window.matchMedia?.('(prefers-color-scheme: dark)').addEventListener?.('change',()=>{if(state.settings.theme==='system')applyTheme();});
if('serviceWorker' in navigator&&location.protocol!=='file:')window.addEventListener('load',()=>navigator.serviceWorker.register('./sw.js').catch(()=>{}));
