import {MCQ_ITEMS} from './quiz.js';
import {LAB_STORAGE_KEY, demoSet, importCandidateReport, scoreSession, officialUrl, freshStore, checkStored, safeStoredRemotePaper} from './practice-core.mjs';
import {readCandidateFeed, combinedCandidatePapers} from './candidate-feed.mjs';

const $=(id)=>document.getElementById(id);
const esc=(v)=>String(v??'').replace(/[&<>"']/g,x=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[x]));
const letters=['A','B','C','D'];
const root=$('practice-lab');
const example=demoSet(MCQ_ITEMS);
const requestedPaper=new URLSearchParams(location.search).get('paper');
let store,view='home',readonly=false,storageError='',rawBackup=null;
let remotePapers=[], remoteFeedStatus='loading';
try {
  const raw=localStorage.getItem(LAB_STORAGE_KEY);
  store=raw===null?freshStore():checkStored(JSON.parse(raw));
} catch(e) {
  try{rawBackup=localStorage.getItem(LAB_STORAGE_KEY);}catch{}
  store=freshStore();readonly=true;storageError='既有學習室資料無法安全讀取。已啟用唯讀保護；請先匯出原始資料，不會覆寫。';
}
if(store.session) view=store.session.status==='completed'?'result':'practice';
// Navigating from the unified catalogue selects the relevant candidate list
// without silently discarding an existing practice session.
if(requestedPaper)view='home'; // keep any existing session available via Resume; never silently replace it

function save() {
  if(readonly)return false;
  try{
    const serialized=JSON.stringify(store);
    localStorage.setItem(LAB_STORAGE_KEY,serialized);
    if(localStorage.getItem(LAB_STORAGE_KEY)!==serialized) throw Error('storage mismatch');
    storageError='';return true;
  }catch(e){readonly=true;storageError='本機儲存失敗，請立即匯出目前資料；為防止遺失，已停止後續覆寫。';return false;}
}
function currentPaper() {
  const s=store.session;
  if(!s) return null;
  return s.mode==='demo'?example:(store.imported?.papers.find(p=>p.id===s.setId) || (store.remotePaper?.id===s.setId?store.remotePaper:null));
}
function notify(t){const n=$('lab-note');if(n){n.textContent=t;n.hidden=false;}}
function statusStrip(){return `<div class="lp-status"><span>V0.3 私人練習室</span><span class="lp-pill">本機儲存 · 尚未正式發布</span></div>`;}
function head(){return `<header class="lp-head"><div class="lp-brand"><span class="lp-brandicon">L</span><div><strong>LexFlow</strong><small>選擇題練習室</small></div></div><div class="lp-nav"><a href="./">統一題庫</a><a href="./official-index.html">官方索引 ↗</a></div></header>`;}
function banner(){return `<div class="lp-banner" role="note"><strong>資料來源分級</strong><span>自編題：可查看自編題答案與法條解析，不是國考成績。　｜　官方候審：僅供私人練習與參考，未核對最終答案，<b>不計分、不標示答對答錯</b>。</span></div>`;}
function paperRow(p){return `<div class="lp-paper ${requestedPaper===p.id?'lp-paper-selected':''}"><div><div class="lp-kicker">${esc(p.year?'民國'+p.year+'年 · ':'')}${esc(p.focus?.join('／')||'混合科目')} · 考選部來源候審</div><h3>${esc(p.subject)}</h3><p>${esc(p.exam)} · 可練習 ${p.questions.length} 題${p.excluded?` · 隔離 ${p.excluded} 題`:''}</p></div><button class="btn small" type="button" data-action="start-official" data-id="${esc(p.id)}">開始私人自測 →</button></div>`;}
function feedMessage() {
 if(remoteFeedStatus==='ready_unscored')return `已取得 ${remotePapers.length} 份網站候審試卷（來源未逐題核驗、不計分）。按下「開始」後才會保存所選試卷的本機快照。`;
 if(remoteFeedStatus==='loading')return '正在檢查本網站是否已有候審試卷…';
 if(remoteFeedStatus==='not_published')return '網站尚無可供自動載入的候審試卷；仍可自行匯入 JSON。';
 return '候審資料未通過安全檢查或暫時無法取得；已停止載入，私人作答不受影響。';
}
function historyMarkup(){if(!store.history.length)return '<p class="lp-muted">尚無完成的多題練習紀錄。</p>';
  return store.history.slice(0,8).map(h=>`<div class="lp-hist"><div><strong>${esc(h.subject)}</strong><small>${esc(h.mode==='demo'?'自編法條自測':'官方候審自測')} · ${esc(h.completedAt?.slice(0,16).replace('T',' ')||'')}</small></div><span>${h.answered}/${h.total} 題已作答${h.mode==='demo'?` · 自編題 ${h.correct} 題正確`:''}</span></div>`).join('');}
function home(){const papers=combinedCandidatePapers(store.imported?.papers||[],remotePapers,store.remotePaper);const ordered=requestedPaper?[...papers].sort((a,b)=>(a.id===requestedPaper?-1:0)-(b.id===requestedPaper?-1:0)):papers;return `${statusStrip()}${store.session?`<div class="lp-resume"><span><b>${store.session.status==='active'?'尚未完成的練習':'上一份練習結果'}</b><small>${esc(currentPaper()?.subject||'請重新選擇練習')} · ${store.session.status==='active'?'進度已保存在本機，計時已暫停':'可重新檢視本次結果'}</small></span><button class="btn small" data-action="resume">${store.session.status==='active'?'繼續作答 →':'查看結果 →'}</button></div>`:''}<div class="lp-hero"><div class="lp-eyebrow">PRACTICE / LEARN / REVIEW</div><h1>讓題庫真正開始被使用。</h1><p>不用再為每份試卷重新寫程式。你可以一次練習多道題、標記疑問、查看練習紀錄；正式國考題維持候審、不提供未核驗的分數。</p></div>${banner()}<div class="lp-grid"><section class="lp-card"><div class="lp-eyebrow">01 / 可查看自編解析</div><h2>自編法條多題練習</h2><div class="lp-number">${example.questions.length} <span>題</span></div><p>使用 V0.2 原有的民法、刑法、憲法示範題。完成後查看自編答案與逐選項解說，成績不代表國考表現。</p><button class="btn primary" type="button" data-action="start-demo">開始練習 →</button></section><section class="lp-card"><div class="lp-eyebrow">02 / 官方來源・候審</div><h2>考選部原題私人自測</h2><div class="lp-number">${papers.length} <span>份可選試卷</span></div><p>自動讀取本站經審查後提供的候審資料；未發佈時仍可手動匯入。題文與最終答案未核驗、不計分。</p><p class="lp-muted" role="status">${esc(feedMessage())}</p><button class="btn small" type="button" data-action="refresh-feed">檢查候審更新</button><label class="btn small" for="candidate-file">手動匯入 JSON</label><input type="file" id="candidate-file" accept=".json,application/json" class="lp-file" aria-label="匯入官方候審 JSON"></section></div>${papers.length?`<section id="official-papers" class="lp-card lp-full"><div class="lp-heading"><h2>候審試卷（網站／本機）</h2><small>完整四選項才可自測，其餘題目維持隔離</small></div>${ordered.map(paperRow).join('')}</section>`:''}<section class="lp-card lp-full"><div class="lp-heading"><h2>練習紀錄與備份</h2><button type="button" class="btn small" data-action="export">匯出私人練習備份</button></div>${historyMarkup()}<div class="lp-backup"><label class="btn small" for="restore-file">匯入私人練習備份</label><input id="restore-file" type="file" accept=".json,application/json" class="lp-file"><span>學習室使用獨立的本機資料鍵，不修改原本 V0.2 的作答、計時、備份。</span></div></section>`;}
function timeMs(s){return Math.max(0,(s.elapsedMs||0)+(s.runningSince?Date.now()-s.runningSince:0));}
function fmtTime(ms){const seconds=Math.floor(ms/1000);return `${String(Math.floor(seconds/60)).padStart(2,'0')}:${String(seconds%60).padStart(2,'0')}`;}
function progress(s,p){const n=p.questions.length;const count=p.questions.filter(q=>letters.includes(s.answers[String(q.number)])).length;return {count,total:n,percent:Math.round(100*count/n)};}
function practice(){const s=store.session,p=currentPaper();if(!p){view='home';return home();}
 const pos=Math.max(0,Math.min(s.position||0,p.questions.length-1)),q=p.questions[pos],pr=progress(s,p), selected=s.answers[String(q.number)];
 const isOfficial=s.mode==='official';
 return `${statusStrip()}<div class="lp-top"><div><div class="lp-eyebrow">${isOfficial?'OFFICIAL CANDIDATE / NOT SCORED':'DEMONSTRATION / SOURCE-BASED'}</div><h1>${esc(p.subject)}</h1><details class="lp-exam-detail"><summary>${esc(p.year?`民國${p.year}年 · `:'')}${isOfficial?'官方候審試卷':'自編示範練習'}　· 查看考試資訊</summary><p>${esc(p.exam)}</p></details></div><div class="lp-timer"><span id="timer-display">${fmtTime(timeMs(s))}</span><button class="btn small" type="button" data-action="timer">${s.runningSince?'暫停':'繼續'}</button></div></div><div class="lp-progress-head"><span id="answered-counter">已作答 ${pr.count} / ${pr.total} 題</span><button class="lp-link" type="button" data-action="home">返回題庫</button></div><div class="lp-track"><div id="progress-fill" style="width:${pr.percent}%"></div></div><details class="lp-navigator"><summary>快速選題 <span>已作答 ${pr.count}／${pr.total} 題 · 點擊展開</span></summary><div class="lp-index" aria-label="快速選題">${p.questions.map((qq,i)=>`<button aria-label="前往第 ${qq.number} 題" type="button" data-action="jump" data-index="${i}" class="${pos===i?'current ':''}${letters.includes(s.answers[String(qq.number)])?'done ':''}${s.bookmarks.includes(qq.number)?'flagged':''}">${qq.number}</button>`).join('')}</div></details><section class="lp-question"><div class="lp-qbar"><span>第 ${q.number} 題 · ${pos+1} / ${p.questions.length}</span><button class="btn small" type="button" data-action="bookmark">${s.bookmarks.includes(q.number)?'★ 已標記':'☆ 標記複習'}</button></div><h2>${esc(q.stem)}</h2><fieldset class="lp-options" ${readonly?'disabled':''}><legend class="lp-visually-hidden">單選題選項</legend>${q.options.map((opt,i)=>`<label class="lp-option ${selected===letters[i]?'checked':''}"><input type="radio" name="response" value="${letters[i]}" ${selected===letters[i]?'checked':''}><b>${letters[i]}</b><span>${esc(opt)}</span></label>`).join('')}</fieldset>${isOfficial?`<div class="lp-inline-warning">此為 PDF 擷取的未核驗題文。請對照 <a href="${esc(p.questionUrl)}" target="_blank" rel="noopener noreferrer">官方原卷 ↗</a>；即使已有候審答案，也不會即時判斷對錯。</div>`:`<p class="lp-muted">自編示範題：完成整組練習後才會顯示自編答案及法條解析。</p>`}</section><div class="lp-actions"><button class="btn" type="button" data-action="prev" ${pos===0?'disabled':''}>← 上一題</button><button class="btn" type="button" data-action="clear-answer">清除本題</button><button class="btn primary" type="button" data-action="next">${pos===p.questions.length-1?'前往總覽':'下一題 →'}</button></div><div class="lp-actions lp-submit"><button class="btn" type="button" data-action="finish">完成本次${isOfficial?'候審自測':'自編練習'} →</button></div>`;}
function result(){const s=store.session,p=currentPaper();if(!s||!p)return home();const summary=scoreSession(s,p.questions);const isOfficial=s.mode==='official';
return `${statusStrip()}<div class="lp-hero"><div class="lp-eyebrow">SESSION COMPLETE</div><h1>這次練習完成了。</h1><p>${esc(p.subject)} · ${isOfficial?'官方候審，自我練習未計分':'自編法條示範題回顧'}</p></div>${banner()}<section class="lp-card lp-full"><div class="lp-result-grid"><div><b>${summary.answered}<small> / ${summary.total}</small></b><span>完成作答</span></div><div><b>${s.bookmarks.length}</b><span>標記複習</span></div><div><b>${isOfficial?'—':summary.correct}</b><span>${isOfficial?'不計分':'自編答對'}</span></div></div><div class="lp-actions lp-result-actions"><button class="btn primary" type="button" data-action="home">返回學習室</button><button class="btn" type="button" data-action="retry">重新練習</button><button class="btn small lp-backup-action" type="button" data-action="export">備份紀錄 ↗</button></div></section><section class="lp-card lp-full"><h2>${isOfficial?'作答與公布答案候審對照':'逐題答案與自編解析'}</h2>${isOfficial?`<div class="lp-inline-warning"><strong>不是對錯判定：</strong>右側字母僅是官方公布答案 PDF 的自動擷取候審值，未核對是否為最終有效答案。不能由此計算答對率。${p.correctionUrl?`<div>本卷存在 <a href="${esc(p.correctionUrl)}" target="_blank" rel="noopener noreferrer">更正文件 ↗</a>，尚未完成特殊給分確認。</div>`:''}</div>`:''}${p.questions.map(q=>{const answer=s.answers[String(q.number)]||'未作答';if(isOfficial)return `<details class="lp-review"><summary>第 ${q.number} 題　你選：${esc(answer)}　｜　公布答案候審：${q.publishedCandidate||'未可靠取得'} <span>展開</span></summary><div><p>${esc(q.stem)}</p><p class="lp-muted">未完成逐字校對、最終更正確認及法律詳解；本頁不顯示答對或錯誤。</p></div></details>`;
return `<details class="lp-review"><summary>第 ${q.number} 題　你選：${esc(answer)}　｜　自編題答案：${q.answer}<span>展開解析</span></summary><div><p>${esc(q.stem)}</p>${q.explanations.map((v,i)=>`<p><b>${letters[i]}：</b>${esc(v)}</p>`).join('')}<p><a href="${esc(q.sourceUrl)}" target="_blank" rel="noopener noreferrer">${esc(q.source)}（法務部全國法規資料庫） ↗</a></p></div></details>`;}).join('')}</section>`;}
function paint(){
 const top=head();const alert=storageError?`<div class="lp-error" role="alert">${esc(storageError)} ${rawBackup?'<button class="btn small" data-action="raw-backup">匯出原始資料</button>':''}</div>`:'';
 root.innerHTML=`<div class="lp-shell">${top}<main>${alert}<p id="lab-note" class="lp-note" hidden></p>${view==='practice'?practice():view==='result'?result():home()}</main><footer class="lp-footer">LexFlow V0.3 候審學習室 · 非考選部官方 App · 僅本機保存 · 正式題庫發布另行驗收</footer></div>`;
 updateClock();
}
function persistAndPaint(){save();paint();}
function newSession(mode,id){const local=store.imported?.papers.find(x=>x.id===id), remote=remotePapers.find(x=>x.id===id), persisted=store.remotePaper?.id===id?store.remotePaper:null;
 const p=mode==='demo'?example:(local||remote||persisted);if(!p)return;
 if(store.session?.status==='active' && !window.confirm('目前的練習尚未完成。開始新練習會覆蓋尚未完成的進度，確定嗎？'))return;
 // A remote feed is never merged into private imports automatically. Save the
 // single selected paper with its session, so updates cannot change a live exam.
 const backup=JSON.parse(JSON.stringify(store));
 if(mode==='official' && !local){if(!safeStoredRemotePaper(p)){notify('候審來源資料不安全，無法開始');return;}store.remotePaper=JSON.parse(JSON.stringify(p));}
 const s={mode,setId:p.id,status:'active',position:0,answers:{},bookmarks:[],elapsedMs:0,runningSince:Date.now(),startedAt:new Date().toISOString(),completedAt:null};store.session=s;
 if(!save()){store=backup;paint();notify('進度保存失敗，無法開始練習；請先備份。');return;}
 view='practice';paint();window.scrollTo({top:0});}
function saveResponse(v){const s=store.session,p=currentPaper();if(!s||!p||s.status!=='active'||!letters.includes(v))return;
 const q=p.questions[s.position];s.answers[String(q.number)]=v;
 if(!save()){paint();notify('本次作答無法儲存；請先匯出目前資料，已啟動唯讀保護。');return;}
 const pr=progress(s,p);
 if($('answered-counter'))$('answered-counter').textContent=`已作答 ${pr.count} / ${pr.total} 題`;
 if($('progress-fill'))$('progress-fill').style.width=pr.percent+'%';
 document.querySelectorAll('.lp-option').forEach(n=>n.classList.toggle('checked',n.querySelector('input')?.value===v));
 const jump=document.querySelector(`button[data-action="jump"][data-index="${s.position}"]`);jump?.classList.add('done');
}
function stopClock(s){if(s?.runningSince){s.elapsedMs=timeMs(s);s.runningSince=null;}}
function finish(){const s=store.session,p=currentPaper();if(!s||s.status!=='active'||!p||readonly)return;
 const n=progress(s,p);if(n.count!==n.total&&!window.confirm(`還有 ${n.total-n.count} 題未作答，仍要結束嗎？`))return;
 const old=JSON.parse(JSON.stringify(store));
 stopClock(s);s.status='completed';s.completedAt=new Date().toISOString();const summary=scoreSession(s,p.questions);
 store.history.unshift({id:`local-${Date.now()}`,mode:s.mode,subject:p.subject,total:summary.total,answered:summary.answered,correct:summary.correct,completedAt:s.completedAt,elapsedMs:s.elapsedMs});store.history=store.history.slice(0,40);
 if(!save()){store=old;view='practice';paint();notify('完成紀錄無法可靠保存。資料未覆蓋，請先匯出備份。');return;}
 view='result';paint();window.scrollTo({top:0});}
function download(text,name){const a=document.createElement('a');const url=URL.createObjectURL(new Blob([text],{type:'application/json;charset=utf-8'}));a.href=url;a.download=name;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),30000);}
function updateClock(){const el=$('timer-display');if(el&&store.session)el.textContent=fmtTime(timeMs(store.session));}
setInterval(()=>{
  updateClock();
  const s=store.session;
  if(!readonly && s?.status==='active' && s.runningSince && Date.now()-s.runningSince>=10000){
    s.elapsedMs=timeMs(s);s.runningSince=Date.now();save();
  }
},1000);
function pauseForBackground(){
  if(readonly || store.session?.status!=='active' || !store.session.runningSince)return;
  stopClock(store.session);save();
}
document.addEventListener('visibilitychange',()=>{if(document.hidden)pauseForBackground();});
window.addEventListener('pagehide',pauseForBackground);

document.addEventListener('change',async ev=>{
 if(ev.target.matches('input[name="response"]')){saveResponse(ev.target.value);return;}
 if(ev.target.id==='candidate-file'){
  const f=ev.target.files?.[0];if(!f)return;
  if(readonly){notify('目前為唯讀保護，請先匯出並處理原始資料。');return;}
  try{if(f.size>5*1024*1024)throw Error('候審 JSON 超過 5MB，拒絕匯入');
    const imported=importCandidateReport(JSON.parse(await f.text()));
    if(store.session?.mode==='official'&&store.session.status==='active'&&!window.confirm('匯入新候審資料會使目前尚未完成的國考私人練習結束。確定嗎？'))return;
    if(store.session?.mode==='official')store.session=null;
    store.imported=imported;view='home';persistAndPaint();notify(`已在本機匯入 ${imported.papers.length} 份候審試卷（不計分）`);
  }catch(e){notify('匯入失敗：'+String(e.message).slice(0,180));}
  ev.target.value='';
 }
 if(ev.target.id==='restore-file'){
   const f=ev.target.files?.[0];if(!f)return;
   if(readonly){notify('目前為唯讀保護，不能直接還原覆寫。');return;}
   try{if(f.size>5*1024*1024)throw Error('備份檔案過大');
     const candidate=checkStored(JSON.parse(await f.text()));
     if(!window.confirm('匯入學習室備份將取代學習室原有資料（不影響 V0.2）。確定繼續？'))return;
     store=candidate;view=store.session?(store.session.status==='completed'?'result':'practice'):'home';persistAndPaint();notify('學習室備份已匯入');
   }catch(e){notify('備份還原失敗：'+String(e.message).slice(0,180));}ev.target.value='';
 }
});
document.addEventListener('click',ev=>{const button=ev.target.closest('[data-action]');if(!button)return;const action=button.dataset.action;
 if(readonly && ['start-demo','start-official','prev','next','jump','clear-answer','bookmark','timer','finish','retry'].includes(action)){notify('唯讀保護：此操作無法保存，請先匯出備份。');return;}
 if(action==='refresh-feed')void refreshCandidateFeed();
 if(action==='start-demo')newSession('demo');
 if(action==='start-official')newSession('official',button.dataset.id);
 if(action==='home'){if(store.session?.status==='active'){stopClock(store.session);save();}view='home';paint();}
 if(action==='resume'&&store.session){view=store.session.status==='completed'?'result':'practice';paint();window.scrollTo({top:0});}
 if(action==='prev'||action==='next'||action==='jump'){
  const s=store.session,p=currentPaper();if(!s||!p||s.status!=='active')return;
  s.position=action==='prev'?Math.max(0,s.position-1):action==='next'?Math.min(p.questions.length-1,s.position+1):Math.max(0,Math.min(p.questions.length-1,Number(button.dataset.index)));
  persistAndPaint();window.scrollTo({top:0});
 }
 if(action==='clear-answer'){const s=store.session,p=currentPaper();if(!s||!p)return;delete s.answers[String(p.questions[s.position].number)];persistAndPaint();}
 if(action==='bookmark'){const s=store.session,p=currentPaper();if(!s||!p)return;const n=p.questions[s.position].number;s.bookmarks=s.bookmarks.includes(n)?s.bookmarks.filter(x=>x!==n):[...s.bookmarks,n];persistAndPaint();}
 if(action==='timer'){const s=store.session;if(!s)return;if(s.runningSince)stopClock(s);else s.runningSince=Date.now();persistAndPaint();}
 if(action==='finish')finish();
 if(action==='retry'){if(!store.session)return;const {mode,setId}=store.session;store.session=null;newSession(mode,setId);}
 if(action==='export')download(JSON.stringify(store,null,2),'LexFlow_V03_practice_local_backup.json');
 if(action==='raw-backup'&&rawBackup)download(rawBackup,'LexFlow_V03_corrupt_data_recovery.json');
});
// A reload resumes paused. Timed work is checkpointed at most every 10 seconds.
if(store.session?.status==='active' && store.session.runningSince){
  store.session.runningSince=null;
  if(!readonly)save();
}
paint();
async function refreshCandidateFeed(){
 remoteFeedStatus='loading';if(view==='home')paint();
 const result=await readCandidateFeed();
 remotePapers=result.papers;
 remoteFeedStatus=result.status;
 if(view==='home')paint();
}
// Same-origin static review feed only; never requests private answers or performs auto writes.
if(location.protocol==='https:'||location.protocol==='http:')void refreshCandidateFeed();
