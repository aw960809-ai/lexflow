import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {readCandidateFeed,combinedCandidatePapers,CANDIDATE_MAX_BYTES,CANDIDATE_FEED_PATH} from '../candidate-feed.mjs';
import {safeStoredRemotePaper,checkStored,freshStore,scoreSession,LAB_STORAGE_KEY} from '../practice-core.mjs';

const fixture = JSON.parse(readFileSync(new URL('../data/moex_review_candidate.json',import.meta.url),'utf8'));
function fakeResponse(data,options={}){
 const body=options.body ?? JSON.stringify(data);
 return {status:options.status||200,ok:options.ok??true,
 headers:{get:(name)=>options.contentType===null?'': name==='Content-Length'?String(body.length):'application/json; charset=utf-8'},
 text:async()=>body};
}
test('live official candidate sample is safe, unscored and has three distinct official papers',async()=>{
 const result=await readCandidateFeed(async()=>fakeResponse(fixture));
 assert.equal(result.status,'ready_unscored');
 assert.equal(result.papers.length,3);
 assert.deepEqual(result.papers.map(p=>p.questions.length),[25,25,45]);
 for(const p of result.papers){
  assert.ok(safeStoredRemotePaper(p));
  assert.match(p.questionUrl,/^https:\/\/wwwq\.moex\.gov\.tw/);
  const r=scoreSession({mode:'official',answers:{'1':'A'}},p.questions);
  assert.equal(r.correct,null);assert.equal(r.officialScore,null);
 }
});
test('feed fetch only requests same-origin static path; no credentials sent to external domains',async()=>{
 let request;const r=await readCandidateFeed(async (...args)=>{request=args;return fakeResponse(fixture)});
 assert.equal(r.status,'ready_unscored');
 assert.equal(request[0],CANDIDATE_FEED_PATH);
 assert.equal(request[1].cache,'no-store');
 assert.equal(request[1].credentials,'same-origin');
 assert.equal(request[1].redirect,'error');
});
test('404 is "not published", not "there are no exams"',async()=>{
 const r=await readCandidateFeed(async()=>fakeResponse({}, {status:404,ok:false}));
 assert.equal(r.status,'not_published');assert.deepEqual(r.papers,[]);
});
test('network failures do not write or invent candidate papers',async()=>{
 const r=await readCandidateFeed(async()=>{throw Error('blocked')});
 assert.equal(r.status,'invalid_or_unavailable');assert.equal(r.papers.length,0);
});
test('non-JSON, overlarge or forged final-scoring payloads are rejected',async()=>{
 const nonjson=await readCandidateFeed(async()=>fakeResponse({}, {body:'<html>bad</html>'}));
 assert.equal(nonjson.status,'invalid_or_unavailable');
 const wrongType=await readCandidateFeed(async()=>({ok:true,status:200,headers:{get:()=> 'text/html'},text:async()=>'{"bad":true}'}));
 assert.equal(wrongType.status,'invalid_or_unavailable');
 const big=await readCandidateFeed(async()=>fakeResponse({}, {body:' '.repeat(CANDIDATE_MAX_BYTES+1)}));
 assert.equal(big.status,'invalid_or_unavailable');
 const forged=structuredClone(fixture);forged.scoring_enabled=true;
 assert.equal((await readCandidateFeed(async()=>fakeResponse(forged))).status,'invalid_or_unavailable');
});
test('source fingerprint is verified before importing the candidate file',async()=>{
 const altered=structuredClone(fixture);
 altered.reviewed_items[0].subject='篡改後的科目';
 assert.equal((await readCandidateFeed(async()=>fakeResponse(altered))).status,'invalid_or_unavailable');
 const alteredDigest=structuredClone(fixture);alteredDigest.staging.origin_sha256='f'.repeat(64);
 assert.equal((await readCandidateFeed(async()=>fakeResponse(alteredDigest))).status,'invalid_or_unavailable');
});
test('auto source needs explicit PR-staging metadata and failed release audit',async()=>{
 const noStage=structuredClone(fixture);delete noStage.staging;
 assert.equal((await readCandidateFeed(async()=>fakeResponse(noStage))).status,'invalid_or_unavailable');
 const falseRelease=structuredClone(fixture);falseRelease.readiness.status='human_quality_gate_SATISFIED';
 assert.equal((await readCandidateFeed(async()=>fakeResponse(falseRelease))).status,'invalid_or_unavailable');
});
test('official hostile question URL and spoofed nested scoring cannot load',async()=>{
 const a=structuredClone(fixture);a.reviewed_items[0].documents.find(d=>d.role==='Q').url='https://wwwq.moex.gov.tw.evil.com/q';
 assert.equal((await readCandidateFeed(async()=>fakeResponse(a))).status,'invalid_or_unavailable');
 const b=structuredClone(fixture);b.reviewed_items[0].question_answer_candidates.questions[0].eligible_for_scoring=true;
 assert.equal((await readCandidateFeed(async()=>fakeResponse(b))).status,'invalid_or_unavailable');
});
test('automatic feed never overrides private imports by duplicate IDs',()=>{
 const a={id:'same',questions:[{number:1}],source:'private'};
 const b={id:'same',questions:[{number:2}],source:'remote'};
 const c={id:'new',questions:[{number:3}]};
 assert.deepEqual(combinedCandidatePapers([a],[b,c]).map(x=>x.source),['private',undefined]);
 assert.equal(combinedCandidatePapers([a],[b,c]).length,2);
 assert.equal(combinedCandidatePapers([],[],a).length,1);
});
test('remote session snapshot persists across reload without touching V0.2 key',()=>{
 const store=freshStore();store.remotePaper=(awaitedSample());
 store.session={mode:'official',setId:store.remotePaper.id,status:'active',answers:{'1':'B'}};
 const recovered=checkStored(JSON.parse(JSON.stringify(store)));
 assert.equal(recovered.remotePaper.id,store.session.setId);
 assert.deepEqual(recovered.session.answers,{'1':'B'});
 assert.notEqual(LAB_STORAGE_KEY,'lexflow-data-v02');
});
function awaitedSample(){const p=fixture.reviewed_items[0];const d={id:p.id,subject:p.subject,questionUrl:p.documents.find(x=>x.role==='Q').url,
 standardUrl:p.documents.find(x=>x.role==='S').url,correctionUrl:'',
 questions:[{number:1,stem:'完整文字候審題幹',options:['A','B','C','D'],publishedCandidate:'B'}]};return d;}
test('tampered stored remote preview source or fake scoring status is rejected',()=>{
 for(const mutation of [p=>p.questionUrl='https://evil.com',p=>p.eligible_for_scoring=true,p=>p.questions[0].options=['only one'],p=>p.questions[0].final_answer_verified=true]){
  const state=freshStore();state.remotePaper=awaitedSample();mutation(state.remotePaper);
  assert.throws(()=>checkStored(state));
 }
});
