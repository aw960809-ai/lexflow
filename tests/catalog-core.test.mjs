import {test} from 'node:test';
import assert from 'node:assert/strict';
import {buildCatalog, filterCatalog, sourceCounts} from '../catalog-core.mjs';
const fixture=()=>buildCatalog({
 essays:[{id:'e1',subject:'刑法',title:'歸責',exam:'自編'}],
 customEssays:[{id:'e2',subject:'民法',title:'第三人'}],
 officialPapers:[{id:'o1',subject:'民法與民事訴訟法',title:'114 年二試',exam:'司法官第二試',url:'https://wwwq.moex.gov.tw/exam/f.pdf'}],
 selfMcq:[{id:'s1',subject:'憲法',title:'法律保留',topic:'基本權'}],
 importedPapers:[{id:'i1',subject:'法學知識與英文',focus:['憲法'],exam:'114 年',questions:Array.from({length:25},(_,i)=>({number:i+1}))}]
});
test('one catalogue covers authored essay/MCQ, official essay and private official MCQ',()=>{
 const a=fixture();assert.equal(a.length,5);assert.equal(sourceCounts(a).official,1);
 assert.equal(a.find(x=>x.id==='i1').count,25);
 assert.deepEqual(a.map(x=>x.action),['essay','essay','essay','single-mcq','candidate']);
});
test('type source subject and search combine without changing underlying state',()=>{
 const a=fixture();const raw=JSON.stringify(a);
 assert.deepEqual(filterCatalog(a,{type:'選擇題',source:'官方候審',area:'憲法'}).map(x=>x.id),['i1']);
 assert.deepEqual(filterCatalog(a,{type:'申論',source:'官方原卷',area:'民法'}).map(x=>x.id),['o1']);
 assert.deepEqual(filterCatalog(a,{type:'選擇題',source:'自編',search:'法律保留'}).map(x=>x.id),['s1']);
 assert.equal(JSON.stringify(a),raw);
});
test('embedded legal name does not create false subject category',()=>{
 const a=buildCatalog({essays:[{id:'e1',subject:'監獄行刑法與國民法官法',title:'other'}]});
 assert.deepEqual(a[0].focus,[]);assert.equal(filterCatalog(a,{area:'刑法'}).length,0);
});
test('malformed private candidate records cannot become scored entries',()=>{
 const a=buildCatalog({importedPapers:[{id:'broken',subject:'民法',questions:[]},{id:'good',subject:'刑法',questions:[{}]}]});
 assert.equal(a.length,1);assert.equal(a[0].source,'官方候審');
 assert.match(a[0].warning,/不計分/);assert.equal('correct' in a[0],false);
});
test('legacy data is never mutated, catalogue exposes only descriptive metadata',()=>{
 const backup={essays:[{id:'e1',subject:'民法',title:'a',answer:'private answer'}]};
 const snap=JSON.stringify(backup), records=buildCatalog(backup);
 assert.equal(JSON.stringify(backup),snap);assert.equal('answer' in records[0],false);
});
