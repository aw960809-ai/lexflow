const CACHE = 'lexflow-pages-v03-safe-official-preview-20261010';
// CacheStorage is origin-wide: never remove caches belonging to other apps.
const OWNED_CACHE_PREFIX = 'lexflow-pages-';
const SHELL = ['./','./index.html','./styles.css','./app.js','./data.js','./quiz.js','./practice-lab.html','./practice-lab.js','./practice-lab.css','./practice-core.mjs','./catalog-core.mjs','./candidate-feed.mjs','./official-scoring-core.mjs','./manifest.webmanifest','./icon.svg','./icon-192.png','./icon-512.png'];
self.addEventListener('install',event=>event.waitUntil(caches.open(CACHE).then(cache=>cache.addAll(SHELL)).then(()=>self.skipWaiting())));
self.addEventListener('activate',event=>event.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(k=>k.startsWith(OWNED_CACHE_PREFIX) && k!==CACHE).map(k=>caches.delete(k)))).then(()=>self.clients.claim())));
self.addEventListener('fetch',event=>{
  const url=new URL(event.request.url);
  if(event.request.method!=='GET'||url.origin!==self.location.origin||url.pathname.startsWith('/api/'))return;
  // Never cache or replay a stale review feed. Offline practice uses its own saved snapshot.
  if(url.pathname.endsWith('/data/moex_review_candidate.json')){event.respondWith(fetch(event.request,{cache:'no-store'}));return;}
  event.respondWith(fetch(event.request).then(response=>{
    if(response.ok){const clone=response.clone();caches.open(CACHE).then(cache=>cache.put(event.request,clone));}
    return response;
  }).catch(()=>caches.match(event.request)));
});
