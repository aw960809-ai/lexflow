import test from 'node:test';
import assert from 'node:assert/strict';
import {importCandidateReport,scoreSession,checkStored,freshStore,safeStoredRemotePaper} from '../practice-core.mjs';
import {countPreviewAnswered} from '../official-scoring-core.mjs';
const Q='https://wwwq.moex.gov.tw/exam/wHandExamQandA_File.ashx?c=301&code=114111&q=1&s=0302&t=Q';
const S=Q.replace('t=Q','t=S');
const makeQuestion=(number,options,mode)=>({number,candidate_status:options.E?'five_options_extracted_NEEDS_VISUAL_REVIEW':'four_options_extracted_NEEDS_VISUAL_REVIEW',review_reasons:[],stem_unverified:'經確認這是一題未完成正式驗收的候審題',options_unverified:options,published_standard_candidate:mode==='multiple_mark_candidate'?'AB':'A',choice_input_candidate:mode,eligible_for_scoring:false,final_answer_verified:false,question_text_verified:false,options_verified:false});
function fixture(){return {schema:'lexflow.moex.universal.batch.v1',status:'bounded_pdf_review_not_a_scored_bank',publication_allowed:false,scoring_enabled:false,all_answers_verified:false,all_question_text_verified:false,reviewed_items:[{
 id:'five-choice-private-test',exam:'示範來源',year_roc:'114',subject:'法律綜合',focus_subjects:['民法'],eligible_for_scoring:false,answer_verified_final:false,options_verified:false,source_link_identity_confirmed:true,
 documents:[{role:'Q',url:Q},{role:'S',url:S}],question_answer_candidates:{schema:'lexflow.moex.question.candidates.v1',publication_allowed:false,scoring_enabled:false,final_answer_verified:false,question_text_and_options_verified:false,official_correction:{detected:false},questions:[
 makeQuestion(1,{A:'甲',B:'乙',C:'丙',D:'丁',E:'戊'},'multiple_mark_candidate'),
 makeQuestion(2,{A:'一',B:'二',C:'三',D:'四'},'multiple_mark_candidate')
 ]}}]};}
test('five-option & 4-option multi-mark candidates preview but cannot become official scores',()=>{
 const p=importCandidateReport(fixture()).papers[0];assert.equal(p.questions.length,2);
 assert.deepEqual(p.questions.map(q=>q.options.length),[5,4]);
 assert.deepEqual(p.questions.map(q=>q.answerInputMode),['multiple','multiple']);
 assert.equal(safeStoredRemotePaper(p),true);
 const answers={'1':'ACE','2':'AB'};
 assert.equal(countPreviewAnswered(answers,p.questions),2);
 const summary=scoreSession({mode:'official',answers},p.questions);
 assert.equal(summary.answered,2);assert.equal(summary.officialScore,null);
 assert.equal(summary.correct,null);assert.equal(summary.percentage,null);
 const store=freshStore();store.imported=importCandidateReport(fixture());
 assert.equal(checkStored(store),store);
});
test('corrupt fifth-option candidate is isolated; forged publication flags are blocked',()=>{
 const bad=fixture();bad.reviewed_items[0].question_answer_candidates.questions[0].options_unverified.E='';
 assert.equal(importCandidateReport(bad).papers[0].questions.length,1);
 const forged=fixture();forged.reviewed_items[0].question_answer_candidates.scoring_enabled=true;
 assert.throws(()=>importCandidateReport(forged));
});
