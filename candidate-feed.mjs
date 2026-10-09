/** Safe, read-only same-origin candidate feed. Never scores or mutates student data. */
import {importCandidateReport} from './practice-core.mjs';

export const CANDIDATE_FEED_PATH = './data/moex_review_candidate.json';
export const CANDIDATE_MAX_BYTES = 2_000_000;

function canonical(value) {
  if (Array.isArray(value)) return `[${value.map(canonical).join(',')}]`;
  if (value && typeof value === 'object') return `{${Object.keys(value).sort().map(k=>`${JSON.stringify(k)}:${canonical(value[k])}`).join(',')}}`;
  return JSON.stringify(value);
}

async function validateStaging(data) {
  const stage=data?.staging, readiness=data?.readiness;
  if(stage?.schema!=='lexflow.moex.unscored.preview-staging.v1' ||
     stage.human_content_and_answer_review_satisfied!==false ||
     stage.website_display_only_after_review_and_merge!==true ||
     readiness?.status!=='human_quality_gate_NOT_SATISFIED' ||
     readiness.publication_allowed!==false || readiness.scoring_enabled!==false ||
     typeof stage.origin_sha256!=='string' || !/^[0-9a-f]{64}$/.test(stage.origin_sha256))
     throw Error('非已完成來源稽核的官方候審資料');
  if(!globalThis.crypto?.subtle)throw Error('目前瀏覽器不支援候審來源指紋核對');
  const {staging:ignoredStage,readiness:ignoredGate,...source}=data;
  const bytes=new TextEncoder().encode(canonical(source));
  const digest=await globalThis.crypto.subtle.digest('SHA-256',bytes);
  const hex=Array.from(new Uint8Array(digest),x=>x.toString(16).padStart(2,'0')).join('');
  if(hex!==stage.origin_sha256)throw Error('候審來源 SHA256 不一致');
}


/** Read only a previously reviewed static candidate file placed on this site.
 *  Data integrity and scoring flags are checked by importCandidateReport.
 *  A missing file is NOT the same as "there are no official exams".
 */
export async function readCandidateFeed(fetchFn = fetch, path = CANDIDATE_FEED_PATH) {
  try {
    const response = await fetchFn(path, {cache: 'no-store', credentials: 'same-origin', redirect: 'error'});
    if (response.status === 404) return {status: 'not_published', papers: [], imported: null};
    if (!response.ok) throw Error(`HTTP ${response.status}`);
    const declared = response.headers?.get?.('Content-Length');
    if (declared !== null && declared !== undefined && declared !== '' && Number(declared) > CANDIDATE_MAX_BYTES)
      throw Error('官方候審檔案超出限制');
    const type = response.headers?.get?.('Content-Type') || '';
    if (type && !/application\/(?:json|octet-stream)|text\/plain/i.test(type))
      throw Error('候審檔案並非 JSON');
    const raw = await response.text();
    if (new TextEncoder().encode(raw).length > CANDIDATE_MAX_BYTES)
      throw Error('官方候審檔案超出限制');
    const report=JSON.parse(raw);
    await validateStaging(report);
    const imported = importCandidateReport(report);
    if (imported.officialFinalAnswersConfirmed !== false || !imported.papers.length)
      throw Error('不安全的官方候審狀態');
    return {status: 'ready_unscored', papers: imported.papers, imported};
  } catch (error) {
    return {status: 'invalid_or_unavailable', papers: [], imported: null,
      reason: String(error?.message || '無法載入').slice(0, 120)};
  }
}

/** Merge only visible descriptions. Existing personal imports take precedence. */
export function combinedCandidatePapers(localPapers = [], feedPapers = [], savedPaper = null) {
  const out = [], seen = new Set();
  for (const p of [...localPapers, ...feedPapers, ...(savedPaper ? [savedPaper] : [])]) {
    if (!p || typeof p.id !== 'string' || !Array.isArray(p.questions) || !p.questions.length || seen.has(p.id)) continue;
    out.push(p); seen.add(p.id);
  }
  return out;
}
