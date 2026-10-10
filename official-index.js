const DATA_URL = './data/moex_official_index.json';
const FALLBACK_URL = './data/moex_official_fallback.json';
const $ = (id) => document.getElementById(id);
let dataset = null;
const allowedLink = (value) => {
  try { const u = new URL(value); return (u.protocol === 'https:' || u.protocol === 'http:') && (u.hostname === 'moex.gov.tw' || u.hostname.endsWith('.moex.gov.tw')) && !u.username && !u.password && (!u.port || ['80','443'].includes(u.port)) ? u.href : ''; }
  catch { return ''; }
};
function node(tag, text, className) { const x = document.createElement(tag); if (className) x.className=className; if(text!==undefined)x.textContent=String(text); return x; }
function makeLink(label, href) {const safe=allowedLink(href);if(!safe)return null;const a=node('a',label);a.href=safe;a.target='_blank';a.rel='noopener noreferrer';return a;}
function valid(data) {return data && data.schema==='lexflow.moex.index.v1' && Array.isArray(data.items) && data.items.length<=150000 && typeof data.status==='string' && data.items.every(p=>p&&typeof p.id==='string'&&typeof p.subject==='string'&&Array.isArray(p.focus_subjects)&&typeof p.exam==='string'&&typeof p.question_url==='string');}
function status() {
  const n = dataset.items.length;
  const method = dataset.source?.method || 'csv';
  if (dataset.status === 'awaiting_first_verified_sync' || dataset.status === 'awaiting_first_official_page_sync') {
    $('status').textContent = '尚未完成首次官方 CSV 同步';
  } else if (method === 'official_exam_page_html') {
    $('status').textContent = `已建立 ${n.toLocaleString('zh-Hant')} 份官方個別考試頁面備援索引（未核驗）`;
  } else if (method === 'combined_read_only') {
    $('status').textContent = `已建立 ${n.toLocaleString('zh-Hant')} 份官方候審索引（主來源＋備援）`;
  } else {
    $('status').textContent = `已建立 ${n.toLocaleString('zh-Hant')} 份官方試卷連結索引`;
  }
  $('meta').textContent = (dataset.disclaimer || '此處只有官方連結索引，尚無逐題答案核對。') +
    (dataset.source?.fingerprint_sha256 ? `｜頁面索引指紋：${dataset.source.fingerprint_sha256.slice(0,12)}…` :
    dataset.source?.sha256 ? `｜CSV SHA256：${dataset.source.sha256.slice(0,12)}…` : '');
}
function render() {
  if (!dataset) return;
  const subject = $('subject').value, type = $('type').value, q = $('search').value.trim().toLowerCase();
  const found = dataset.items.filter(item => {
    if(subject==='待分類' && item.classification!=='needs_classification') return false;
    if(subject!=='全部' && subject!=='待分類' && !item.focus_subjects.includes(subject)) return false;
    if(type!=='全部' && !String(item.question_type||'').includes(type)) return false;
    return [item.year_roc,item.exam,item.subject,item.grade,...(item.groups||[])].join(' ').toLowerCase().includes(q);
  });
  $('count').textContent = `符合條件：${found.length} 份｜目前顯示前 ${Math.min(60,found.length)} 份。混合試卷不代表全卷皆屬指定科目。`;
  const root=$('results');root.replaceChildren();
  if(!found.length){root.append(node('div',dataset.items.length?'找不到符合條件的試卷。':'目前沒有已同步的試卷索引；資料尚未取得，不代表沒有國考試題。','empty'));return;}
  for(const p of found.slice(0,60)) {
    const box=node('article',undefined,'paper'), tags=node('div',undefined,'tags');
    for(const v of [p.year_roc ? `民國 ${p.year_roc} 年` : '',p.question_type,p.classification==='mixed'?'混合科目':p.classification==='needs_classification'?'待人工分類':'科目名稱比對']) {if(v)tags.append(node('span',v,'tag'));}
    box.append(tags,node('h3',p.subject||'未命名科目'),node('div',p.exam,'tiny'));
    if(p.groups?.length)box.append(node('div',`類科：${p.groups.slice(0,6).join('、')}${p.groups.length>6?'…':''}`,'tiny'));
    box.append(node('p',p.source_page_url?'官方個別考試頁面備援連結（未核對 PDF 內容及最終答案）。':'僅索引官方試卷連結；答案與詳解尚未逐題查核。','tiny'));
    const qlink=makeLink('開啟官方原始試卷 ↗',p.question_url);if(qlink)box.append(qlink);
    const alink=makeLink('官方答案文件（尚未核驗）↗',p.answer_url);if(alink)box.append(alink);
    const amend=makeLink('官方更正答案文件（尚未核驗）↗',p.answer_correction_url);if(amend)box.append(amend);
    root.append(box);
  }
}
async function safeRead(url) {
  try {
    const response = await fetch(url,{cache:'no-store'});
    if (!response.ok) throw Error('HTTP '+response.status);
    const data=await response.json();
    if (!valid(data)) throw Error('索引資料格式不符合');
    return data;
  } catch { return null; }
}
async function load() {
  $('status').textContent='正在檢查官方主索引及個別頁面備援…';
  const [primary, fallback] = await Promise.all([safeRead(DATA_URL),safeRead(FALLBACK_URL)]);
  if (!primary && !fallback) {
    dataset=null;$('status').textContent='索引尚不可用';
    $('meta').textContent='官方主索引與備援索引目前都無法載入；已停止更新，原有作答資料不受影響。';
    $('results').replaceChildren(node('div','沒有可用的官方來源索引，不代表當期沒有考題。','empty'));
    return;
  }
  if ((!primary || !primary.items.length) && fallback?.items.length) {
    dataset=fallback;
  } else if (primary?.items.length && fallback?.items.length) {
    const originals=new Set(primary.items.map(i=>i.question_url));
    const additions=fallback.items.filter(i=>!originals.has(i.question_url));
    dataset={...primary,
      source:{method:'combined_read_only',sha256:primary.source?.sha256},
      items:[...primary.items,...additions],
      disclaimer:'合併顯示主 CSV 索引和個別考試頁面備援索引；兩份來源檔仍獨立保存。僅候審連結，未核驗最終答案與逐題詳解。'};
  } else {
    dataset=primary || fallback;
  }
  status(); render();
}
for(const id of ['subject','type','search']) $(id).addEventListener(id==='search'?'input':'change',render);
$('reload').addEventListener('click',load);
$('file').addEventListener('change',async event=>{
  const file=event.target.files?.[0];if(!file)return;
  if(file.size>12*1024*1024){$('meta').textContent='候審 JSON 超過 12MB，拒絕載入';return;}
  try {const d=JSON.parse(await file.text());if(!valid(d))throw Error('候審 JSON 格式不符');dataset=d;status();$('status').textContent+='（本機檔案預覽，未發布）';render();}
  catch(e){$('meta').textContent='預覽失敗：'+e.message;}
});
load();
