import test from 'node:test';
import assert from 'node:assert/strict';
import {normalizeOfficialSelection, officialInputSpec, scoreOfficialReferenceForAudit,
  scoreUnreleasedOfficialSession, previewChoiceSpec, canonicalPreviewResponse,
  countPreviewAnswered} from '../official-scoring-core.mjs';
const j=x=>JSON.stringify(x);
const rule=(mode,variants,config=null)=>({proposal_mode:mode,accepted_variants_json:j(variants), exceptional_scoring_json:config===null?null:j(config)});
const partial = rule('FIVE_OPTION_PARTIAL_CREDIT',['AC'],{option_count:5,points_full:3,points_one_wrong:1.8,
  points_two_wrong:0.6,points_other:0,blank_credit:0,wrong_count_mode:'SYMMETRIC_DIFFERENCE_MARKED_AND_CORRECT'});
function earned(r,x){return scoreOfficialReferenceForAudit(r,x).earnedUnits;}
function combos(a){const q=[''];for(const l of a){q.push(...[...q].map(v=>v+l));}return q;}
test('official candidate and forged approval flags never produce official score',()=>{
 for(const fake of [{}, {independentlyReviewed:true, trustedReleaseManifest:true,appEndToEndTested:true},
    {status:'READY',publication_allowed:true,scoring_enabled:true}]){
   assert.deepEqual(scoreUnreleasedOfficialSession(fake),{
     status:'BLOCKED_PENDING_FULL_REVIEW', correct:null,percentage:null,officialScore:null,publicationAllowed:false});
 }
});
test('choice rules allow multi-mark only when the official correction or five-option format requires it',()=>{
 assert.equal(officialInputSpec(rule('SINGLE_EXACT',['B'])).inputType,'radio');
 assert.equal(officialInputSpec(rule('MULTIPLE_ACCEPTED_VARIANTS',['A','B'])).inputType,'radio');
 assert.equal(officialInputSpec(rule('MULTIPLE_ACCEPTED_VARIANTS',['A','B','AB'])).inputType,'checkbox');
 assert.deepEqual(officialInputSpec(partial).alphabet,'ABCDE');
});
test('three permissible responses A, B and AB are exact; others are wrong',()=>{
 const r=rule('MULTIPLE_ACCEPTED_VARIANTS',['A','B','AB']);
 for(const x of combos('ABCD'))assert.equal(earned(r,x),['A','B','AB'].includes(x)?1:0);
});
test('corrected answer replaces old key; unconditional all-credit accepts blank',()=>{
 const r=rule('CORRECTED_SINGLE_REPLACEMENT',['B']);
 assert.equal(earned(r,'B'),1);assert.equal(earned(r,'A'),0);
 assert.equal(earned(rule('UNCONDITIONAL_ALL_CREDIT',[]),''),1);
});
test('five-choice official partial credit exhausts 32 response patterns',()=>{
 let n=0;for(const ans of combos('ABCDE')){
   const wrong=[...'ABCDE'].filter(c=>'AC'.includes(c)!==ans.includes(c)).length;
   assert.equal(earned(partial,ans),ans===''?0:wrong===0?3:wrong===1?1.8:wrong===2?0.6:0);
   n++;
 }assert.equal(n,32);
});
test('no untrusted selections, malformed policies, or wrong scoring schedules',()=>{
 for(const x of ['AA','F','a',' A','A B',13,['A','A']])assert.throws(()=>normalizeOfficialSelection(x));
 assert.throws(()=>scoreOfficialReferenceForAudit(rule('UNKNOWN',['A']),'A'));
 assert.throws(()=>scoreOfficialReferenceForAudit(rule('SINGLE_EXACT',['AB']),'A'));
 assert.equal(earned(rule('MULTIPLE_ACCEPTED_VARIANTS',['A','B']),'AB'),0);
 const invalid=rule('FIVE_OPTION_PARTIAL_CREDIT',['AC'],{option_count:5,wrong_count_mode:'DIFFERENT',points_full:3});
 assert.throws(()=>scoreOfficialReferenceForAudit(invalid,'AC'));
});
test('preview checkbox/radio control accepts five letters, but never calculates a grade',()=>{
 const a={number:1,options:['一','二','三','四'],answerInputMode:'multiple'};
 const b={number:2,options:['甲','乙','丙','丁','戊']};
 const c={number:3,options:['a','b','c','d']};
 assert.equal(previewChoiceSpec(a).inputType,'checkbox');
 assert.equal(previewChoiceSpec(b).inputType,'checkbox');
 assert.equal(previewChoiceSpec(c).inputType,'radio');
 assert.equal(canonicalPreviewResponse(['B','A'],a),'AB');
 assert.equal(canonicalPreviewResponse('EA',b),'AE');
 assert.throws(()=>canonicalPreviewResponse('AB',c));
 assert.equal(countPreviewAnswered({'1':'AB','2':'CE','3':'A'},[a,b,c]),3);
 assert.equal(countPreviewAnswered({'1':'ABCDEF','2':'','3':'AC'},[a,b,c]),0);
});
