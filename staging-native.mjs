/* LexFlow Final98 V3 — draft-code-only, private candidate index and read-only records.
 * READ ONLY. No import to formal backend, no official scoring, no answer keys.
 * Keep historic lexflow-data-v02 records untouched and 449 practice data separate.
 */
// No static import of _staging_449: published Draft code must remain usable without private assets.
const PRIVATE_STORE_KEY = 'lexflow-final98-shadow-practice-v1';

export const STAGE_SOURCE_SHA = 'a43a6c786eb0f7404e2a5af952153b983919092866773594e0a458f64bf5facd';
export const STAGE_CATALOG_SHA = '41e6340f497b36e0329921c269caea58e0924ab82cb0393e756e886d9adb4180';
const CATALOG_URL = './_staging_449/catalog.json';
const PAPER_PATTERN = /^MOEX-Q-[0-9a-f]{20}$/;
let catalogPromise = null;
const SCORING_FIELDS = ['score','officialScore','correct','percentage','officialAnswer','correctIndex'];
const text = (tag, className = '', str = '') => { const el = document.createElement(tag); if(className)el.className=className; if(str !== undefined && str !== null)el.textContent=String(str); return el; };
const add = (container, ...children) => {for(const child of children)container.append(child);return container;};

function insist(flag, message){if(!flag)throw Error(message);}
function officialUrl(s){try{const u=new URL(s);return u.protocol==='https:' &&
    !u.username && !u.password && !u.hash && (u.port===''||u.port==='443') &&
    (u.hostname==='moex.gov.tw'||u.hostname.endsWith('.moex.gov.tw'));}catch{return false;}}

export function validateStagingCatalog(value){
  insist(value&&value.schema==='lexflow.shadow.readonly.catalog.v1' &&
    value.status==='PRIVATE_STAGING_MACHINE_ONLY_NOT_PRODUCTION','候審目錄版本或發布狀態不相容');
  insist(value.sourceDbSha256===STAGE_SOURCE_SHA && value.contentHumanVerified===false &&
    value.publicationAllowed===false && value.scoringEnabled===false,'來源或正式放行鎖定狀態不符');
  insist(value.stats?.papers===449&&value.stats?.questions===9399&&value.stats?.mcq===8290&&
    value.stats?.essay===1109&&value.stats?.riskRecords===2293&&
    value.stats?.riskQuestions===1841&&value.stats?.sharedArticles===34,'候審數量不一致');
  insist(Array.isArray(value.papers)&&value.papers.length===449 && Array.isArray(value.questions)&&value.questions.length===9399,'題卷清單不完整');
  const ids=new Set(); let total=0,mcq=0,essay=0;
  for(const p of value.papers){
    insist(PAPER_PATTERN.test(p.id)&&p.file==='papers/'+p.id+'.json'&&/^[a-f0-9]{64}$/.test(p.sha256) &&
      Number.isInteger(p.questionCount)&&p.questionCount>0&&p.questionCount<=100&&officialUrl(p.officialUrl),
      '試卷來源身分或指紋不合法');
    insist(!ids.has(p.id),'重複試卷身分');ids.add(p.id);
    insist(p.questionCount===p.mcqCount+p.essayCount,'單卷題數不一致');
    total+=p.questionCount;mcq+=p.mcqCount;essay+=p.essayCount;
  }
  insist(total===9399&&mcq===8290&&essay===1109,'整卷題數總計不符');
  const seenQ=new Set(),counter=new Map(),riskPerPaper=new Map();
  let riskRecordCount=0,riskQuestionCount=0;
  for(const q of value.questions){
    insist(ids.has(q.paperId)&&typeof q.id==='string'&&q.id.startsWith(q.paperId+'-')&&
      (q.kind==='MCQ'||q.kind==='ESSAY') && Array.isArray(q.risks) && Array.isArray(q.domains) &&
      typeof q.searchText==='string' && q.searchText.length<15000,'索引題目資料不完整');
    insist(!seenQ.has(q.id),'重複題目 ID');seenQ.add(q.id);
    counter.set(q.paperId,(counter.get(q.paperId)||0)+1);
    riskRecordCount+=q.risks.length;
    if(q.risks.length){riskQuestionCount++;riskPerPaper.set(q.paperId,(riskPerPaper.get(q.paperId)||0)+1);}
    insist(!Object.hasOwn(q,'answer')&&!Object.hasOwn(q,'officialAnswer')&&!Object.hasOwn(q,'score'),'候審索引包含評分欄位');
  }
  for(const p of value.papers){
    insist(counter.get(p.id)===p.questionCount,'單卷題目 ID 數量不符');
    insist((riskPerPaper.get(p.id)||0)===p.riskCount,'單卷風險標記遺漏');
  }
  insist(riskRecordCount===2293&&riskQuestionCount===1841,'風險標記數量不符');
  return value;
}

export function selectStagingPapers(catalog,{domain='全部',kind='全部',risk='全部',year='全部',search=''}={}){
  const byId=new Map(catalog.papers.map(p=>[p.id,p]));
  const found=new Map(), keyword=String(search).trim().toLocaleLowerCase('zh-TW').slice(0,150);
  for(const q of catalog.questions){
    const paper=byId.get(q.paperId);if(!paper)continue;
    if(kind!=='全部' && q.kind!==kind)continue;
    if(year!=='全部' && paper.year!==year)continue;
    if(risk==='有標記' && !q.risks.length)continue;
    if(risk==='無標記' && q.risks.length)continue;
    if(domain==='其他'){
      if(q.domains?.length)continue;
    }else if(domain!=='全部' && !q.domains.includes(domain))continue;
    if(keyword){
      const searchable=[q.searchText,q.subject,paper.officialCode,paper.id,...(paper.subjectNames||[])].join(' ').toLocaleLowerCase('zh-TW');
      if(!searchable.includes(keyword))continue;
    }
    found.set(paper.id,(found.get(paper.id)||0)+1);
  }
  const papers=[...found].map(([id,n])=>({paper:byId.get(id),matches:n}));
  papers.sort((a,b)=> Number(b.paper.year)-Number(a.paper.year)||
    String(b.paper.officialCode).localeCompare(String(a.paper.officialCode))||a.paper.id.localeCompare(b.paper.id));
  return {papers,matchingQuestions:[...found.values()].reduce((a,b)=>a+b,0)};
}

/** Validate sessions against both the private practice-core and this catalog.
 * NEVER migrate, merge, or write lexflow-data-v02 or the shadow storage key.
 */
export function inspectStagingRecords(raw, catalog, validator){
  if(raw===null)return {status:'empty',history:[],drafts:[],countHistory:0,countDrafts:0};
  insist(typeof raw==='string' && raw.length<=4_500_000, '候審紀錄容量不符');
  insist(typeof validator==='function', '候審紀錄驗證器未載入');
  const state=validator(JSON.parse(raw),catalog.sourceDbSha256);
  const byId=new Map(catalog.papers.map(p=>[p.id,p]));
  function checkSession(session){
    const meta=byId.get(session.paperId);
    insist(meta && session.paperSha256===meta.sha256,'候審作答與試卷 SHA-256 不一致');
    insist(!SCORING_FIELDS.some(k=>Object.hasOwn(session,k)),'候審紀錄出現未授權評分欄位');
    insist(session.answers && typeof session.answers==='object' && !Array.isArray(session.answers),'作答欄位格式錯誤');
    const answered=Object.values(session.answers).filter(v=>Array.isArray(v)?v.length>0:typeof v==='string'&&v.trim()).length;
    return {id:session.id, paperId:session.paperId, subject:meta.subjectNames?.slice(0,3).join('／')||'科目待判',
      year:meta.year, paperCode:meta.officialCode, answered, total:meta.questionCount,
      time:session.completedAt||session.updatedAt, kind:session.completedAt?'history':'draft'};
  }
  const drafts=Object.values(state.drafts).map(checkSession).sort((a,b)=>b.time.localeCompare(a.time));
  const history=state.history.map(checkSession).sort((a,b)=>b.time.localeCompare(a.time));
  return {status:'ok',history,drafts,countHistory:history.length,countDrafts:drafts.length};
}

async function readStageRecords(catalog){
  try{
    // Import only after catalog checksum and flags have passed validation.
    const core=await import('./_staging_449/practice-core.mjs');
    insist(core.STORE_KEY===PRIVATE_STORE_KEY,'隔離作答儲存鍵不符');
    return inspectStagingRecords(window.localStorage.getItem(PRIVATE_STORE_KEY),catalog,core.validateStore);
  }catch(e){return {status:'blocked',error:String(e?.message||e).slice(0,180)};}
}

async function load(){
  if(!catalogPromise){
    catalogPromise=(async()=>{
      insist(!!globalThis.crypto?.subtle,'目前瀏覽器無法驗證 SHA-256');
      const res=await fetch(CATALOG_URL,{cache:'no-store',redirect:'error'});
      if(res.status===404)throw Error('此環境沒有安裝私人候審題庫；正式網站不會公開這批資料。');
      insist(res.ok,'目錄載入失敗（HTTP '+res.status+'）');
      const bytes=await res.arrayBuffer();
      const digest=await crypto.subtle.digest('SHA-256',bytes);
      const actual=[...new Uint8Array(digest)].map(x=>x.toString(16).padStart(2,'0')).join('');
      insist(actual===STAGE_CATALOG_SHA,'SHA-256 不一致，已拒絕候審題庫');
      return validateStagingCatalog(JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(bytes)));
    })().catch(e=>{catalogPromise=null;throw e;});
  }
  return catalogPromise;
}

function chip(value,group,selected){
  const button=text('button','stage-chip'+(selected===value?' active':''),value);
  button.type='button';button.dataset.group=group;button.dataset.value=value;
  button.setAttribute('aria-pressed',selected===value?'true':'false');return button;
}
function card(meta,matching){
  const wrap=text('article','stage-paper');
  add(wrap,text('div','stage-overline','民國 '+meta.year+' 年 · 官方代碼 '+meta.officialCode));
  add(wrap,text('h3','',meta.subjectNames?.slice(0,3).join('／')||'科目待確認'));
  add(wrap,text('p','stage-meta',`符合 ${matching} 題／全卷 ${meta.questionCount} 題 · 選擇 ${meta.mcqCount} · 申論 ${meta.essayCount}`));
  if(meta.riskCount)add(wrap,text('p','stage-warning',`共 ${meta.riskCount} 題保留風險標記，尚未完成內容及答案審核`));
  const actions=text('div','stage-actions');
  for(const [label,src,primary] of [
    ['查看全卷','./_staging_449/index.html?paper='+encodeURIComponent(meta.id),false],
    ['整卷練習','./_staging_449/practice.html?paper='+encodeURIComponent(meta.id),true]]){
    const a=text('a','stage-action'+(primary?' primary':''),label);a.href=src;actions.append(a);
  }
  wrap.append(actions);return wrap;
}

export async function mountStagingBank(root){
  if(!root)return;
  root.replaceChildren(text('p','stage-message','正在核對 449 份試卷目錄與來源 SHA-256…'));
  try{
    const catalog=await load();
    if(!root.isConnected)return;
    const state={domain:'全部',kind:'全部',risk:'全部',year:'全部',search:'',page:1};
    const summary=await readStageRecords(catalog);
    if(!root.isConnected)return;
    const stat=text('p','stage-notice','Final98 候審整卷：449 份／9,399 題（選擇 8,290；申論 1,109）。機器核證不等於正式內容審核；目前不提供官方答案、計分或正式發布。');
    const wrap=text('div','stage-bank');wrap.append(stat);
    const counts=text('div','stage-record-status');
    if(summary.status==='ok') counts.textContent=`此網址已有 ${summary.history} 次整卷交卷紀錄、${summary.drafts} 份暫存；與正式成績分開。`;
    else if(summary.status==='empty')counts.textContent='目前沒有整卷練習紀錄；作答只儲存在這個網址的本機資料。';
    else counts.textContent='現有候審練習紀錄格式不相容，已維持原樣、停止讀取，請先在練習室匯出備份。';
    const records=text('a','stage-record-link','查看整卷作答紀錄 ↗'); records.href='./_staging_449/practice.html';
    wrap.append(counts,records);
    const chipbar=text('div','stage-chipbar');
    const filterLabel=text('span','stage-field-label','法科');chipbar.append(filterLabel);
    const domainChips=text('div','stage-chips');
    for(const s of ['全部','民法','刑法','憲法','行政法','其他'])domainChips.append(chip(s,'domain',state.domain));
    chipbar.append(domainChips);
    const kindbar=text('div','stage-chipbar');kindbar.append(text('span','stage-field-label','題型'));
    const kindChips=text('div','stage-chips');
    for(const [v,label] of [['全部','全部'],['MCQ','選擇題'],['ESSAY','申論題']]){
      const b=chip(v,'kind',state.kind);b.textContent=label;kindChips.append(b);
    }
    kindbar.append(kindChips);wrap.append(chipbar,kindbar);
    const searchrow=text('div','stage-search-row');
    const label=text('label','stage-search-label','搜尋科目、題幹、來源代碼');
    const input=text('input','stage-search');input.type='search';input.placeholder='例如：善意取得、行政處分';input.maxLength=150;
    label.append(input); searchrow.append(label);
    const advanced=text('details','stage-advanced');advanced.append(text('summary','','年度與審核標記'));
    const opts=text('div','stage-options');
    const yearLabel=text('label','','年度');const yearSelect=text('select','stage-select');
    const yy=[...new Set(catalog.papers.map(p=>p.year))].sort((a,b)=>Number(b)-Number(a));
    for(const y of ['全部',...yy]){const option=text('option','',y==='全部'?'全部年度':'民國 '+y+' 年');option.value=y;yearSelect.append(option);}
    yearLabel.append(yearSelect);opts.append(yearLabel);
    const riskLabel=text('label','','審核標記');const riskSelect=text('select','stage-select');
    for(const val of ['全部','有標記','無標記']){const option=text('option','',val);option.value=val;riskSelect.append(option);}
    riskLabel.append(riskSelect);opts.append(riskLabel);advanced.append(opts);searchrow.append(advanced);wrap.append(searchrow);
    const status=text('p','stage-count');const list=text('div','stage-list');const pager=text('div','stage-pager');wrap.append(status,list,pager);
    root.replaceChildren(wrap);
    function render(){
      const r=selectStagingPapers(catalog,state);status.textContent=`符合 ${r.papers.length} 份試卷、${r.matchingQuestions.toLocaleString('zh-TW')} 題（完整原卷仍保留全部題目）`;
      const max=Math.max(1,Math.ceil(r.papers.length/20));state.page=Math.max(1,Math.min(state.page,max));
      list.replaceChildren();
      for(const item of r.papers.slice((state.page-1)*20,state.page*20))list.append(card(item.paper,item.matches));
      if(!r.papers.length)list.append(text('p','stage-message','目前沒有符合條件的試卷。'));
      const prev=chip('上一頁','pager','');prev.disabled=state.page===1;
      const next=chip('下一頁','pager','');next.disabled=state.page===max;
      pager.replaceChildren(prev,text('span','',`${state.page}／${max}`),next);
      prev.addEventListener('click',()=>{state.page--;render();});next.addEventListener('click',()=>{state.page++;render();});
    }
    for(const bar of [domainChips,kindChips]){
      bar.addEventListener('click',event=>{
        const button=event.target.closest('button[data-group]');if(!button)return;
        state[button.dataset.group]=button.dataset.value;state.page=1;
        for(const el of bar.querySelectorAll('button')){
          const sel=el===button;el.classList.toggle('active',sel);el.setAttribute('aria-pressed',String(sel));
        }render();
      });
    }
    input.addEventListener('input',()=>{state.search=input.value;state.page=1;render();});
    yearSelect.addEventListener('change',()=>{state.year=yearSelect.value;state.page=1;render();});
    riskSelect.addEventListener('change',()=>{state.risk=riskSelect.value;state.page=1;render();});
    render();
  }catch(e){if(root.isConnected){root.replaceChildren(text('div','stage-error','安全停止：'+String(e.message||e)));}}
}

/** Read-only records list in the original LexFlow '批改' page.
 * Existing v02 attempts and quizAttempts remain owned by app.js and unmodified.
 */
export async function mountStagingHistory(root){
  if(!root)return;
  root.replaceChildren(text('p','stage-message','正在核對整卷紀錄及試卷來源…'));
  try{
    const catalog=await load();
    if(!root.isConnected)return;
    const state=await readStageRecords(catalog);
    if(!root.isConnected)return;
    const wrap=text('div','stage-bank stage-history');
    wrap.append(text('p','stage-notice','這裡只顯示「整卷候審練習」的本機紀錄。與 LexFlow 原有申論、自編選擇題紀錄分開保存，不計入正式答對率或官方分數。'));
    if(state.status==='blocked'){
      wrap.append(text('p','stage-error','紀錄已安全停止讀取：'+state.error+'。原始資料未修改，請先在隔離練習室匯出備份。'));
      root.replaceChildren(wrap);return;
    }
    const counts=text('p','stage-count',`已交卷 ${state.countHistory} 次 · 暫存 ${state.countDrafts} 份 · 未計分`);
    const historyPage=text('a','stage-action','前往完整紀錄與備份 ↗');historyPage.href='./_staging_449/practice.html';
    wrap.append(counts,historyPage);
    function list(title,items,description,max){
      const section=text('section','stage-history-section');
      section.append(text('h3','stage-history-heading',title));
      if(items.length===0){section.append(text('p','stage-message',description));return section;}
      for(const item of items.slice(0,max)){
        const card=text('article','stage-paper stage-history-card');
        card.append(text('div','stage-overline',`民國 ${item.year} 年 · ${item.paperCode} · ${item.kind==='draft'?'未完成':'已交卷／未計分'}`));
        card.append(text('h4','',item.subject));
        card.append(text('p','stage-meta',`已作答 ${item.answered}／${item.total} 題 · ${new Date(item.time).toLocaleString('zh-TW')}`));
        const a=text('a','stage-action',item.kind==='draft'?'驗證後繼續作答 ↗':'查看自己的作答 ↗');
        a.href='./_staging_449/practice.html'+(item.kind==='draft'?'?paper='+encodeURIComponent(item.paperId):'');
        card.append(a);section.append(card);
      }
      if(items.length>max)section.append(text('p','stage-count',`其餘 ${items.length-max} 筆可在完整紀錄頁查看。`));
      return section;
    }
    wrap.append(list('未完成整卷',state.drafts,'目前沒有未完成的整卷。',10),
      list('歷史交卷',state.history,'目前沒有整卷交卷紀錄。',20));
    root.replaceChildren(wrap);
  }catch(e){if(root.isConnected)root.replaceChildren(text('div','stage-error','安全停止：'+String(e?.message||e)));}
}
