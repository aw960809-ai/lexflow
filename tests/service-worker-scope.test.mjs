import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';

const script=readFileSync(new URL('../sw.js', import.meta.url), 'utf8');

function workerHarness(cacheNames, fetchResult={ok:true,clone(){return this}}) {
  const listeners=new Map(), deleted=[], live=new Set(cacheNames), fetched=[], matched=[], shellAdded=[];
  const caches={
    keys:async()=>[...live],
    delete:async key=>{deleted.push(key);return live.delete(key);},
    open:async()=>({addAll:async assets=>{shellAdded.push([...assets]);},put:async()=>{}}),
    match:async req=>{matched.push(req);return {from:'cached-shell'};}
  };
  const self={
    location:{origin:'https://aw960809-ai.github.io'},
    clients:{claim:async()=>{}},
    skipWaiting:async()=>{},
    addEventListener:(name,fn)=>listeners.set(name,fn)
  };
  const fetch=async(...args)=>{
    fetched.push(args);
    if(fetchResult instanceof Error)throw fetchResult;
    return fetchResult;
  };
  runInNewContext(script,{self,caches,fetch,URL,Promise});
  return {listeners,deleted,live,fetched,matched,shellAdded};
}

test('activation deletes only obsolete LexFlow caches, leaving unrelated apps untouched',async()=>{
  const h=workerHarness(['lexflow-pages-v02','lexflow-pages-v03-safe-review-feed-20261009','another-project-cache','lexflow-private-backup']);
  let pending;
  h.listeners.get('activate')({waitUntil:p=>{pending=p;}});
  await pending;
  assert.deepEqual(h.deleted,['lexflow-pages-v02','lexflow-pages-v03-safe-review-feed-20261009']);
  assert(h.live.has('another-project-cache'));
  assert(h.live.has('lexflow-private-backup'));
});

test('official candidate feed always bypasses CacheStorage and uses no-store network',async()=>{
  const h=workerHarness([]),request={method:'GET',url:'https://aw960809-ai.github.io/lexflow/data/moex_review_candidate.json'};
  let pending;
  h.listeners.get('fetch')({request,respondWith:p=>{pending=p;}});
  await pending;
  assert.equal(h.fetched.length,1);
  assert.equal(h.fetched[0][0],request);
  assert.equal(h.fetched[0][1].cache,'no-store');
  assert.equal(h.matched.length,0);
});

test('offline shell navigation can use pre-cached assets without modifying stored answers',async()=>{
  const h=workerHarness([],new Error('network offline'));
  const request={method:'GET',url:'https://aw960809-ai.github.io/lexflow/practice-lab.html'};
  let pending;
  h.listeners.get('fetch')({request,respondWith:p=>{pending=p;}});
  const response=await pending;
  assert.equal(response.from,'cached-shell');
  assert.equal(h.matched.length,1);
  assert.equal(h.matched[0],request);
});

// Regression: new module must be install-preloaded for first offline launch.
test('official-scoring-core is precached before offline launch',async()=>{
  const h=workerHarness([]);
  let pending;
  h.listeners.get('install')({waitUntil:p=>{pending=p;}});
  await pending;
  assert.equal(h.shellAdded.length,1);
  const shell=h.shellAdded[0];
  assert(shell.includes('./practice-lab.js'));
  assert(shell.includes('./practice-core.mjs'));
  assert(shell.includes('./official-scoring-core.mjs'));
  assert(!shell.includes('./data/moex_review_candidate.json'));
});
