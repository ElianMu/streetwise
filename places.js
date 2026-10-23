'use strict';
/* NYC-wide place search shared by Starting Point, Destination, My Hotel and Add Stop.

   Providers (all called from the browser; no private key is ever shipped):
   · Photon (komoot) — OpenStreetMap POIs and addresses, designed for search-as-you-type, CORS-enabled.
   · NYC GeoSearch (NYC Planning Labs, Pelias over PAD/LION) — official NYC addresses and venues in all five boroughs,
     plus reverse geocoding for map picks.
   · Mapbox Search Box (/suggest + /retrieve) — only when a public token is configured (STREETWISE_CONFIG.mapboxToken);
     a suggestion is never treated as a confirmed place until /retrieve returns its coordinates.
   Results are normalized to one Place model, de-duplicated across providers and limited to the five boroughs.
   Search coverage (five boroughs) is not routing coverage: walking routes exist only where the pedestrian graph does. */
const NYC_BBOX=[-74.2591,40.4774,-73.7004,40.9176];
const BOROUGHS={'manhattan':'Manhattan','new york county':'Manhattan','new york':null,'brooklyn':'Brooklyn','kings county':'Brooklyn','queens':'Queens',
 'queens county':'Queens','bronx':'Bronx','the bronx':'Bronx','bronx county':'Bronx','staten island':'Staten Island','richmond county':'Staten Island'};
const PLACE_SEARCH={minChars:2,debounceMs:300,limit:7,timeoutMs:8000};
const OSM_LABEL={'tourism:museum':'Museum','tourism:gallery':'Gallery','tourism:hotel':'Hotel','tourism:hostel':'Hostel','tourism:guest_house':'Guest house',
 'tourism:attraction':'Attraction','tourism:viewpoint':'Viewpoint','amenity:cafe':'Café','amenity:restaurant':'Restaurant','amenity:fast_food':'Fast food',
 'amenity:bar':'Bar','amenity:pub':'Pub','amenity:pharmacy':'Pharmacy','amenity:hospital':'Hospital','amenity:clinic':'Clinic','amenity:bank':'Bank',
 'amenity:atm':'ATM','amenity:toilets':'Public restroom','amenity:university':'University','amenity:library':'Library','amenity:theatre':'Theatre',
 'shop:supermarket':'Supermarket','shop:convenience':'Convenience store','shop:bakery':'Bakery','shop:mall':'Shopping mall','shop:department_store':'Department store',
 'leisure:park':'Park','leisure:garden':'Garden','railway:station':'Station','railway:subway_entrance':'Subway entrance','public_transport:station':'Transit station',
 'highway:bus_stop':'Bus stop','building:yes':'Building','office:yes':'Building','place:house':'Address','highway:residential':'Street','highway:primary':'Street',
 'highway:secondary':'Street','highway:tertiary':'Street','place:square':'Square','historic:monument':'Monument','historic:memorial':'Memorial'};
const titleCase=s=>String(s||'').toLowerCase().replace(/\b\w/g,c=>c.toUpperCase());
function boroughOf(...names){for(const n of names){const b=BOROUGHS[String(n||'').toLowerCase()];if(b)return b;}return null;}
function haversineKm(a,b){const R=6371.0088,r=Math.PI/180,dl=(b.lat-a.lat)*r,dn=(b.lon-a.lon)*r;const s=Math.sin(dl/2)**2+Math.cos(a.lat*r)*Math.cos(b.lat*r)*Math.sin(dn/2)**2;return 2*R*Math.asin(Math.sqrt(s));}
function inNYC(p){return p.lon>=NYC_BBOX[0]&&p.lon<=NYC_BBOX[2]&&p.lat>=NYC_BBOX[1]&&p.lat<=NYC_BBOX[3];}
/** Walking routes exist only on the pedestrian graph (today Manhattan); the engine's snap is the final word. */
function inRoutingCoverage(p){return p.borough?p.borough==='Manhattan':typeof latLonInsideManhattanEnvelope==='function'&&latLonInsideManhattanEnvelope(p);}
const normName=s=>String(s||'').toLowerCase().normalize('NFKD').replace(/[̀-ͯ]/g,'').replace(/^the\s+/,'').replace(/[^a-z0-9一-鿿]+/g,' ').trim();

/** Unified Place model. */
function makePlace(o){
 return {id:o.id,name:o.name,address:o.address||null,neighborhood:o.neighborhood||null,borough:o.borough||null,category:o.category||null,
  lat:+o.lat,lon:+o.lon,source:o.source,sourceUrl:o.sourceUrl||null,website:o.website||null,hours:o.hours||null,retrievedAt:new Date().toISOString(),
  verification:o.verification||'Listed by source (not verified by STREETWISE)',raw:o.raw||null};
}
const PROVIDERS={
 photon:{label:'OpenStreetMap (Photon)',async search(q,opts,signal){
  const bias=opts.near||{lat:40.758,lon:-73.985};
  const p=new URLSearchParams({q,limit:'10',lat:bias.lat.toFixed(4),lon:bias.lon.toFixed(4),lang:'en',bbox:NYC_BBOX.join(',')});
  for(const t of opts.osmTags||[])p.append('osm_tag',t);
  const r=await fetch(`https://photon.komoot.io/api/?${p}`,{signal});if(!r.ok)throw new Error(`Photon HTTP ${r.status}`);
  const d=await r.json();
  return (d.features||[]).map(f=>{const x=f.properties||{},[lon,lat]=f.geometry.coordinates;
   const borough=boroughOf(x.district,x.city,x.county,x.locality);
   const street=[x.housenumber,x.street].filter(Boolean).join(' ');
   const name=x.name||street||null;if(!name||x.state&&x.state!=='New York')return null;
   return makePlace({id:`osm:${{N:'node',W:'way',R:'relation'}[x.osm_type]||x.osm_type}/${x.osm_id}`,name,address:[street,x.postcode].filter(Boolean).join(', ')||null,
    neighborhood:x.locality||x.district||null,borough,category:OSM_LABEL[`${x.osm_key}:${x.osm_value}`]||titleCase(String(x.osm_value||'').replace(/_/g,' ')),lat,lon,
    source:'OpenStreetMap via Photon',sourceUrl:`https://www.openstreetmap.org/${{N:'node',W:'way',R:'relation'}[x.osm_type]}/${x.osm_id}`,raw:{osm_key:x.osm_key,osm_value:x.osm_value}});
  }).filter(Boolean);
 }},
 geosearch:{label:'NYC GeoSearch (NYC Planning)',async search(q,opts,signal){
  if(opts.osmTags?.length)return [];  // category-only searches (e.g. hotels) are answered by POI providers
  const r=await fetch(`https://geosearch.planninglabs.nyc/v2/autocomplete?${new URLSearchParams({text:q})}`,{signal});if(!r.ok)throw new Error(`GeoSearch HTTP ${r.status}`);
  const d=await r.json();
  return (d.features||[]).map(f=>{const x=f.properties||{},[lon,lat]=f.geometry.coordinates;
   const venue=x.layer==='venue';
   return makePlace({id:`nycgeo:${x.gid||x.id}`,name:venue?titleCase(x.name):titleCase(x.name||x.label),address:venue?null:titleCase(x.label?.replace(/, (New York|Brooklyn|Bronx|Queens|Staten Island), NY, USA$/,'')),
    neighborhood:x.neighbourhood||null,borough:boroughOf(x.borough)||x.borough||null,category:venue?'Place':x.layer==='address'?'Address':titleCase(x.layer),lat,lon,
    source:'NYC GeoSearch (NYC Planning Labs · PAD)',raw:{layer:x.layer}});
  });
 }},
 mapbox:{label:'Mapbox Search Box',enabled:()=>Boolean(window.STREETWISE_CONFIG?.mapboxToken),async search(q,opts,signal){
  const token=window.STREETWISE_CONFIG.mapboxToken,session=placeSearchState.session||(placeSearchState.session=crypto.randomUUID());
  const p=new URLSearchParams({q,access_token:token,session_token:session,limit:'8',language:'en',bbox:NYC_BBOX.join(','),country:'US'});
  if(opts.near)p.set('proximity',`${opts.near.lon},${opts.near.lat}`);
  const r=await fetch(`https://api.mapbox.com/search/searchbox/v1/suggest?${p}`,{signal});if(!r.ok)throw new Error(`Mapbox HTTP ${r.status}`);
  const d=await r.json();
  // Suggestions have no confirmed coordinates: they are retrieved on selection (retrievePlace).
  return (d.suggestions||[]).map(s=>({id:`mapbox:${s.mapbox_id}`,name:s.name,address:s.full_address||s.place_formatted,borough:null,category:s.poi_category?.[0]||s.feature_type,
   source:'Mapbox Search Box',pending:true,mapboxId:s.mapbox_id}));
 }},
};
const placeSearchState={session:null};
async function retrievePlace(p){
 if(!p.pending)return p;
 const token=window.STREETWISE_CONFIG.mapboxToken;
 const r=await fetch(`https://api.mapbox.com/search/searchbox/v1/retrieve/${encodeURIComponent(p.mapboxId)}?${new URLSearchParams({access_token:token,session_token:placeSearchState.session||''})}`);
 if(!r.ok)throw new Error(`Mapbox retrieve HTTP ${r.status}`);
 const f=(await r.json()).features?.[0];if(!f)throw new Error('Mapbox returned no feature');placeSearchState.session=null;
 const [lon,lat]=f.geometry.coordinates;return makePlace({...p,lat,lon,borough:boroughOf(f.properties.context?.locality?.name,f.properties.context?.place?.name)});
}
/** Search all enabled providers in parallel, merge, de-duplicate and rank. Each provider can fail on its own. */
async function searchPlaces(q,opts={},signal){
 const names=Object.keys(PROVIDERS).filter(k=>!PROVIDERS[k].enabled||PROVIDERS[k].enabled());
 const settled=await Promise.allSettled(names.map(k=>Promise.race([PROVIDERS[k].search(q,opts,signal),new Promise((_,rej)=>setTimeout(()=>rej(new Error('timeout')),PLACE_SEARCH.timeoutMs))])));
 if(signal?.aborted)throw new DOMException('aborted','AbortError');
 const errors=settled.map((s,i)=>s.status==='rejected'?`${PROVIDERS[names[i]].label}: ${s.reason?.message||s.reason}`:null).filter(Boolean);
 const lists=settled.map(s=>s.status==='fulfilled'?s.value:[]);
 if(errors.length===names.length)throw new Error(errors.join(' · '));
 const nq=normName(q),merged=[];
 // Interleave providers so the best of each shows; then de-duplicate same-name places within 250 m.
 for(let i=0;i<10;i++)for(const l of lists)if(l[i])merged.push(l[i]);
 const out=[];
 for(const p of merged){
  if(!p.pending&&!inNYC(p))continue;
  const dup=out.find(o=>normName(o.name)===normName(p.name)&&(p.pending||o.pending||haversineKm(o,p)<.25));
  if(dup){dup.borough=dup.borough||p.borough;dup.neighborhood=dup.neighborhood||p.neighborhood;dup.address=dup.address||p.address;dup.alsoIn=[...(dup.alsoIn||[]),p.source];continue;}
  if(!p.pending&&!p.borough)continue;   // outside the five boroughs (e.g. Yonkers, Jersey City)
  out.push(p);
 }
 const score=p=>{const n=normName(p.name);return (n===nq?0:n.startsWith(nq)?1:n.includes(nq)?2:3);};
 out.sort((a,b)=>score(a)-score(b));
 return {places:out.slice(0,opts.limit||PLACE_SEARCH.limit),errors};
}
async function reverseGeocode(lat,lon){
 try{const r=await fetch(`https://geosearch.planninglabs.nyc/v2/reverse?${new URLSearchParams({'point.lat':lat,'point.lon':lon,size:'1'})}`,{signal:AbortSignal.timeout(6000)});
  const f=(await r.json()).features?.[0];if(!f)return null;const x=f.properties;
  return {address:titleCase(x.label.replace(/, NY, USA$/,'')),borough:boroughOf(x.borough)||x.borough||null,neighborhood:x.neighbourhood||null};
 }catch(e){return null;}
}
function placeDistanceText(p){
 const g=typeof state!=='undefined'&&state.gps;if(!g||p.pending)return '';
 const km=haversineKm(g,p);return `${km<1?Math.round(km*1000)+' m':km.toFixed(1)+' km'} straight-line from you`;
}

/** Autocomplete input: debounce, cancellation, stale-response guard, keyboard / mouse / touch, loading / empty / error. */
function attachPlaceSearch(input,{onSelect,onClear,osmTags=null,placeholder=null,emptyHint='No NYC place found. Try another spelling, or pick the point on the map.'}){
 if(placeholder)input.placeholder=placeholder;
 input.setAttribute('role','combobox');input.setAttribute('aria-autocomplete','list');input.setAttribute('aria-expanded','false');
 const wrap=input.closest('.search-place')||input.parentElement;wrap.classList.add('ps-wrap');
 const list=document.createElement('div');list.className='ps-list hidden';list.setAttribute('role','listbox');list.id=input.id+'List';input.setAttribute('aria-controls',list.id);
 wrap.after(list);
 const clear=document.createElement('button');clear.type='button';clear.className='ps-clear hidden';clear.setAttribute('aria-label','Clear');clear.textContent='×';input.after(clear);
 const st={timer:null,ctrl:null,seq:0,items:[],active:-1,selected:null};
 const close=()=>{list.classList.add('hidden');input.setAttribute('aria-expanded','false');st.active=-1;};
 const show=html=>{list.innerHTML=html;list.classList.remove('hidden');input.setAttribute('aria-expanded','true');};
 const render=()=>{
  show(st.items.map((p,i)=>`<button type="button" role="option" class="ps-item ${i===st.active?'active':''}" data-i="${i}" aria-selected="${i===st.active}">
   <span class="ps-name">${esc(p.name)}</span><span class="ps-cat">${esc(p.category||'')}</span>
   <span class="ps-meta">${esc([p.address,p.neighborhood,p.borough].filter(Boolean).filter((v,j,a)=>a.indexOf(v)===j).join(' · '))}${p.borough&&p.borough!=='Manhattan'?' · <em>search only — walking routes cover Manhattan</em>':''}</span>
   ${placeDistanceText(p)?`<span class="ps-dist">${esc(placeDistanceText(p))}</span>`:''}</button>`).join('')+`<div class="ps-foot">Sources: ${esc([...new Set(st.items.map(p=>p.source))].join(' · '))}</div>`);
  list.querySelectorAll('[data-i]').forEach(b=>b.addEventListener('mousedown',e=>{e.preventDefault();choose(+b.dataset.i);}));
 };
 async function choose(i){
  let p=st.items[i];if(!p)return;close();
  try{p=await retrievePlace(p);}catch(e){toast('Could not confirm that place: '+e.message);return;}
  st.selected=p;input.value=p.name;clear.classList.remove('hidden');onSelect(p);
 }
 async function run(q){
  st.ctrl?.abort();st.ctrl=new AbortController();const seq=++st.seq;
  show('<div class="ps-status">Searching NYC places…</div>');
  try{const {places,errors}=await searchPlaces(q,{near:state.gps||(state.mapReady?{lat:state.map.getCenter().lat,lon:state.map.getCenter().lng}:null),osmTags},st.ctrl.signal);
   if(seq!==st.seq)return;  // a newer keystroke owns the list
   st.items=places;st.active=places.length?0:-1;
   if(!places.length){show(`<div class="ps-status">${esc(emptyHint)}</div>${errors.length?`<div class="ps-foot">Partly unavailable: ${esc(errors.join(' · '))}</div>`:''}`);return;}
   render();
  }catch(e){if(e.name==='AbortError'||seq!==st.seq)return;show(`<div class="ps-status error">Place search unavailable (${esc(e.message)}). Pick the point on the map instead.</div>`);}
 }
 input.addEventListener('input',()=>{
  const q=input.value.trim();clear.classList.toggle('hidden',!input.value);
  // Editing a chosen place invalidates its coordinates until a new result is chosen.
  if(st.selected&&input.value!==st.selected.name){st.selected=null;onClear?.();}
  clearTimeout(st.timer);st.ctrl?.abort();
  if(q.length<PLACE_SEARCH.minChars){st.seq++;close();return;}
  st.timer=setTimeout(()=>run(q),PLACE_SEARCH.debounceMs);
 });
 input.addEventListener('keydown',e=>{
  if(list.classList.contains('hidden')||!st.items.length){if(e.key==='Enter')e.preventDefault();return;}
  if(e.key==='ArrowDown'){e.preventDefault();st.active=(st.active+1)%st.items.length;render();}
  else if(e.key==='ArrowUp'){e.preventDefault();st.active=(st.active-1+st.items.length)%st.items.length;render();}
  else if(e.key==='Enter'){e.preventDefault();if(st.active>=0)choose(st.active);}
  else if(e.key==='Escape'){close();}
 });
 input.addEventListener('blur',()=>setTimeout(close,150));
 clear.addEventListener('click',()=>{input.value='';clear.classList.add('hidden');st.seq++;st.ctrl?.abort();close();if(st.selected){st.selected=null;onClear?.();}input.focus();});
 return {set(p){st.selected=p;input.value=p?.name||'';clear.classList.toggle('hidden',!p);},clear(){st.selected=null;input.value='';clear.classList.add('hidden');},get selected(){return st.selected;}};
}
if(typeof module!=='undefined')module.exports={searchPlaces,makePlace,boroughOf,normName,haversineKm,inNYC,PROVIDERS,PLACE_SEARCH};
