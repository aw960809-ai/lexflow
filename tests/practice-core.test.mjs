import test from 'node:test';
import assert from 'node:assert/strict';
import {importCandidateReport,demoSet,scoreSession,officialUrl,freshStore,checkStored,LAB_STORAGE_KEY} from '../practice-core.mjs';
const cases = [
  {id:'sample-1',question:'示範題幹',options:['A 說法','B 說法','C 說法','D 說法'],answer:1,notes:['A 理由','B 理由','C 理由','D 理由'],source:'民法第153條',sourceUrl:'https://law.moj.gov.tw/lawclass',subject:'民法',title:'示範'},
  {id:'sample-2',question:'另一道題',options:['一','二','三','四'],answer:2,notes:['甲','乙','丙','丁'],source:'刑法',sourceUrl:'https://law.moj.gov.tw/lawclass',subject:'刑法',title:'示範'}
];
const qURL='https://wwwq.moex.gov.tw/exam/wHandExamQandA_File.ashx?c=201&code=114120&q=1&s=0405&t=Q';
const aURL=qURL.replace('t=Q','t=S');
function candidate(){return {schema:'lexflow.moex.universal.batch.v1',status:'bounded_pdf_review_not_a_scored_bank',publication_allowed:false,scoring_enabled:false,all_answers_verified:false,all_question_text_verified:false,reviewed_items:[{
  id:'moex-first',year_roc:'114',subject:'民法概要',exam:'114司法特考',focus_subjects:['民法'],eligible_for_scoring:false,answer_verified_final:false,options_verified:false,source_link_identity_confirmed:true,
  documents:[{role:'Q',url:qURL},{role:'S',url:aURL}],
  question_answer_candidates:{schema:'lexflow.moex.question.candidates.v1',publication_allowed:false,scoring_enabled:false,final_answer_verified:false,question_text_and_options_verified:false,official_correction:{detected:false},questions:[{
    number:1,candidate_status:'four_options_extracted_NEEDS_VISUAL_REVIEW',review_reasons:[],stem_unverified:'如何解釋法律行為之效力？',options_unverified:{A:'選項甲',B:'選項乙',C:'選項丙',D:'選項丁'},published_standard_candidate:'B',eligible_for_scoring:false,final_answer_verified:false,question_text_verified:false,options_verified:false
  },{number:2,candidate_status:'isolated_question_fragment_NEEDS_REVIEW',review_reasons:['頁碼干擾'],stem_unverified:'不完整',options_unverified:{},published_standard_candidate:'C',eligible_for_scoring:false,final_answer_verified:false,question_text_verified:false,options_verified:false}]}
}]};}
function clone(x){return JSON.parse(JSON.stringify(x));}

test('source host validation blocks javascript, lookalike and credentials',()=>{
  assert.equal(officialUrl(qURL),qURL);
  for(const u of ['javascript:alert(1)','https://wwwq.moex.gov.tw.evil.com/a','https://who@wwwq.moex.gov.tw/a','http://wwwq.moex.gov.tw/a','https://wwwq.moex.gov.tw:444/a','https://evil.com/a']) assert.equal(officialUrl(u),'');
});
test('demo grade is never official national exam score',()=>{
  const p=demoSet(cases);const s=scoreSession({mode:'demo',answers:{'1':'B','2':'A'}},p.questions);
  assert.equal(s.correct,1); assert.equal(s.percentage,50);assert.equal(s.officialScore,null);
});
test('official candidates never yield a correct count or a percentage, even if they have a key',()=>{
  const p=importCandidateReport(candidate()).papers[0]; const r=scoreSession({mode:'official',answers:{'1':'B'}},p.questions);
  assert.equal(r.answered,1);assert.equal(r.correct,null);assert.equal(r.percentage,null);assert.equal(r.officialScore,null);
});
test('only complete four-choice source candidates are selectable; malformed are isolated',()=>{
  const d=importCandidateReport(candidate());assert.equal(d.papers.length,1);assert.equal(d.papers[0].questions.length,1);assert.equal(d.papers[0].excluded,1);assert.equal(d.papers[0].questions[0].publishedCandidate,'B');
  assert.equal(d.officialFinalAnswersConfirmed,false);
});
test('unpaired official answers cannot supply even a provisional answer letter',()=>{
  const x=candidate();x.reviewed_items[0].source_link_identity_confirmed=false;
  assert.equal(importCandidateReport(x).papers[0].questions[0].publishedCandidate,null);
});
test('rejects scored or published counterfeit candidate file at each level',()=>{
  const edits=[x=>x.scoring_enabled=true,x=>x.publication_allowed=true,
    x=>x.reviewed_items[0].eligible_for_scoring=true,
    x=>x.reviewed_items[0].question_answer_candidates.scoring_enabled=true,
    x=>x.reviewed_items[0].question_answer_candidates.questions[0].final_answer_verified=true,
    x=>x.reviewed_items[0].question_answer_candidates.questions[0].eligible_for_scoring=true];
  for(const mutate of edits){const x=candidate();mutate(x);assert.throws(()=>importCandidateReport(x),Error);}
});
test('malicious URLs inside report are rejected even though labels render as text',()=>{
  for(const v of ['javascript:alert(1)','https://evil.com/q','https://wwwq.moex.gov.tw.evil.com/q']){
    const x=candidate();x.reviewed_items[0].documents[0].url=v;
    assert.throws(()=>importCandidateReport(x),Error);
  }
});
test('duplicate question numbers cannot silently overwrite a response',()=>{
  const x=candidate(); const second=clone(x.reviewed_items[0].question_answer_candidates.questions[0]);second.stem_unverified='第二次出現同題號';x.reviewed_items[0].question_answer_candidates.questions.push(second);
  assert.throws(()=>importCandidateReport(x),/重複或非法題號/);
});
test('changing answer candidate to unknown choice does not invent an answer',()=>{
  const x=candidate();x.reviewed_items[0].question_answer_candidates.questions[0].published_standard_candidate='Z';
  assert.equal(importCandidateReport(x).papers[0].questions[0].publishedCandidate,null);
});
test('different report schema or ready-to-release status fail closed',()=>{
  const x=candidate();x.schema='other';assert.throws(()=>importCandidateReport(x));
  const y=candidate();y.status='scored_question_bank';assert.throws(()=>importCandidateReport(y));
});
test('local data uses independent key and rejects incompatible version',()=>{
  assert.notEqual(LAB_STORAGE_KEY,'lexflow-data-v02');
  const store=freshStore();assert.equal(checkStored(store),store);
  store.version=999;assert.throws(()=>checkStored(store));
});
