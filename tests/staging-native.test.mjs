import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createHash} from 'node:crypto';
import {validateStagingCatalog, selectStagingPapers,inspectStagingRecords,
  STAGE_SOURCE_SHA,STAGE_CATALOG_SHA,formatStagingRecordCounts} from '../staging-native.mjs';

function fakeCatalog(){
  const papers=[], questions=[];
  let mcq=0,essay=0,seenQuestion=0;
  for(let i=0;i<449;i++){
    const id='MOEX-Q-'+(i+1).toString(16).padStart(20,'0');
    const size=i<419?21:20;
    let cm=0,ce=0,riskCount=0;
    for(let j=1;j<=size;j++){
      const kind=mcq<8290?'MCQ':'ESSAY';
      if(kind==='MCQ'){mcq++;cm++;}else{essay++;ce++;}
      const risks=seenQuestion<1841?['SUBJECT_UNDECIDED',...(seenQuestion<452?['PDF_HEADER_ARTIFACT']:[])]:[];
      if(risks.length)riskCount++;
      seenQuestion++;
      questions.push({paperId:id,id:id+'-'+kind+'-'+j,kind,domains:j===1?[]:['民法'],
        risks,
        searchText:j===2?'甲善意取得':'通用試題'+j,subject:j===1?'混合／待判':'民法'});
    }
    papers.push({id,file:'papers/'+id+'.json',sha256:'a'.repeat(64),
      officialUrl:'https://wwwq.moex.gov.tw/exam/wHandExamQandA_File.ashx?code=115140&t=Q&c=301&q=1&s=0101',
      officialCode:String(115140-i),subjectNames:['民法'],year:'115',mcqCount:cm,essayCount:ce,
      questionCount:size,riskCount});
  }
  assert.equal(mcq,8290);assert.equal(essay,1109);
  return {schema:'lexflow.shadow.readonly.catalog.v1',status:'PRIVATE_STAGING_MACHINE_ONLY_NOT_PRODUCTION',sourceDbSha256:STAGE_SOURCE_SHA,
    contentHumanVerified:false,publicationAllowed:false,scoringEnabled:false,
    stats:{papers:449,questions:9399,mcq:8290,essay:1109,riskRecords:2293,riskQuestions:1841,sharedArticles:34},papers,questions};
}
const fixture=fakeCatalog();
test('449 complete papers, 9,399 unique questions, safe gates',()=>{
  assert.equal(validateStagingCatalog(fixture),fixture);
});
test('filters exact question kinds, law domains, risk, and text',()=>{
  const essay=selectStagingPapers(fixture,{kind:'ESSAY'});
  assert.equal(essay.matchingQuestions,1109);
  const five=selectStagingPapers(fixture,{domain:'其他'});
  assert.equal(five.matchingQuestions,449);
  assert.equal(selectStagingPapers(fixture,{risk:'有標記'}).matchingQuestions,1841);
  assert.equal(selectStagingPapers(fixture,{search:'善意取得'}).matchingQuestions,449);
  assert.equal(selectStagingPapers(fixture,{year:'999'}).matchingQuestions,0);
  assert.equal(selectStagingPapers(fixture,{domain:'行政法'}).matchingQuestions,0);
});
test('reject score authorization, duplicate items, tampered source, malicious domains',()=>{
  for(const modify of [
    x=>{x.scoringEnabled=true},
    x=>{x.contentHumanVerified=true},
    x=>{x.sourceDbSha256='0'.repeat(64)},
    x=>{x.papers[0].officialUrl='https://attacker.invalid/abc'},
    x=>{x.papers[0].officialUrl='http://wwwq.moex.gov.tw/'},
    x=>{x.questions[0].answer='A'},
    x=>{x.questions[0].id=x.questions[1].id},
    x=>{x.papers[0].questionCount=99},
    x=>{x.papers[0].file='../example.json'}]){
    const mutated=structuredClone(fixture);modify(mutated);
    assert.throws(()=>validateStagingCatalog(mutated));
  }
});
test('read-only records are separate from graded and native v02 attempts',()=>{
  const p=fixture.papers[0],q=fixture.questions[0];
  const session={id:'s1',paperId:p.id,paperSha256:p.sha256,
    startedAt:'2026-10-12T09:00:00.000Z',updatedAt:'2026-10-12T09:10:00.000Z',
    completedAt:'2026-10-12T09:10:00.000Z',submissionStatus:'SELF_RESPONSES_ONLY_UNSCORED',
    answers:{[q.id]:['A']}};
  const obj={schema:'lexflow.shadow.practice.local.v1',sourceDbSha256:STAGE_SOURCE_SHA,
    drafts:{},history:[session]};
  const validator=(x,hash)=>{assert.equal(hash,STAGE_SOURCE_SHA);return x};
  const records=inspectStagingRecords(JSON.stringify(obj),fixture,validator);
  assert.equal(records.status,'ok');assert.equal(records.countHistory,1);
  assert.equal(records.history[0].answered,1);
  assert.equal(records.history[0].kind,'history');
  assert.deepEqual(inspectStagingRecords(null,fixture,validator).history,[]);
  obj.history[0].officialScore=100;
  assert.throws(()=>inspectStagingRecords(JSON.stringify(obj),fixture,validator));
  delete obj.history[0].officialScore;
  obj.history[0].paperSha256='b'.repeat(64);
  assert.throws(()=>inspectStagingRecords(JSON.stringify(obj),fixture,validator));
});
test('empty or malformed histories fail without writes',()=>{
  assert.throws(()=>inspectStagingRecords('{bad',fixture,()=>({})),SyntaxError);
  assert.throws(()=>inspectStagingRecords('a'.repeat(4500001),fixture,()=>({})),/容量/);
});
test('real uploaded Final98 staging catalog (offline optional)', {skip:!process.env.LEXFLOW_CATALOG_PATH},()=>{
  const buf=readFileSync(process.env.LEXFLOW_CATALOG_PATH);
  assert.equal(createHash('sha256').update(buf).digest('hex'),STAGE_CATALOG_SHA);
  const cat=validateStagingCatalog(JSON.parse(buf));
  assert.equal(cat.papers.length,449);
  assert.equal(cat.questions.length,9399);
  assert.equal(selectStagingPapers(cat,{domain:'行政法'}).matchingQuestions,2879);
  assert.equal(selectStagingPapers(cat,{domain:'刑法'}).matchingQuestions,1497);
  assert.equal(selectStagingPapers(cat,{kind:'MCQ'}).matchingQuestions,8290);
  assert.equal(selectStagingPapers(cat,{kind:'ESSAY'}).matchingQuestions,1109);
  assert.equal(selectStagingPapers(cat,{domain:'其他'}).matchingQuestions,1225);
});

test('stage record summaries format counts, never stringify history arrays',()=>{
  const good={status:'ok',countHistory:2,countDrafts:1,history:[{id:'one'},{id:'two'}],drafts:[{id:'draft'}]};
  const view=formatStagingRecordCounts(good);
  assert.match(view,/2 次整卷交卷紀錄、1 份暫存/);
  assert(!view.includes('[object Object]'));
  assert.match(formatStagingRecordCounts({status:'empty'}),/目前沒有整卷/);
  assert.match(formatStagingRecordCounts({status:'blocked'}),/已維持原樣/);
  assert.throws(()=>formatStagingRecordCounts({status:'ok',countHistory:[],countDrafts:0}));
});
