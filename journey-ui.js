'use strict';
/* Journey UI: shared place inputs, end modes, My Hotel, Journey Stops (left); waypoints, hotel and found places (map);
   "Your City Walk" (Route Intelligence). Every panel renders from `journey`, state.start/end and the last planner
   response, so they cannot disagree. */
const placeInputs={};let hotelInput=null,addStopInput=null;
const clockAt=min=>new Date(Date.now()+min*60000).toLocaleTimeString('en-US',{timeZone:'America/New_York',hour:'numeric',minute:'2-digit'});

function setupJourneyUI(){
 for(const kind of ['start','end']){
  placeInputs[kind]=attachPlaceSearch($(kind==='start'?'searchStart':'searchEnd'),{
   placeholder:'Search any NYC address, place or business',
   onSelect:p=>{setJourneyPlace(kind,p);resetRoutes();syncMapData();
    if(p.routing_coverage==='search_only')return toast('This source point has no verified walking access; discovery only.');
 if(!inRoutingCoverage(p))return toast(`${p.name} is in ${p.borough||'NYC'}: place search covers all five boroughs, but walking routes cover Manhattan only.`);
    if(state.mapReady)state.map.flyTo({center:[p.lon,p.lat],zoom:15,duration:450});},
   onClear:()=>{state[kind]=null;state[kind==='start'?'customStart':'customEnd']=null;resetRoutes();syncMapData();}});
 }
 placeInputs.start.set(getPlace('start'));placeInputs.end.set(getPlace('end'));
 hotelInput=attachPlaceSearch($('hotelSearch'),{osmTags:['tourism:hotel','tourism:hostel','tourism:guest_house','tourism:motel'],placeholder:'Search your hotel (name or brand)',
  emptyHint:'No hotel found with that name in NYC map data.',onSelect:p=>{setMyHotel(p);appendChat('assistant',`My hotel set to ${p.name}. Use it as start, return point or search anchor.`);},onClear:()=>setMyHotel(null)});
 addStopInput=attachPlaceSearch($('addStopSearch'),{placeholder:'Add a stop: any NYC place',onSelect:p=>{addNamedStop(p);addStopInput.clear();}});
 document.querySelectorAll('[data-end-mode]').forEach(b=>b.addEventListener('click',()=>{setEndMode(b.dataset.endMode);if(b.dataset.endMode!=='fixed')journey.active=true;renderJourneyPanel();}));
 $('rememberHotel').addEventListener('change',e=>{journey.rememberHotel=e.target.checked;setMyHotel(journey.hotel);});
 $('hotelAsStart').addEventListener('click',()=>{if(!journey.hotel)return toast('Set My Hotel first.');setJourneyPlace('start',journey.hotel);resetRoutes();});
 $('hotelReturn').addEventListener('click',()=>{if(!journey.hotel)return toast('Set My Hotel first.');setEndMode('hotel');journey.active=true;renderJourneyPanel();});
 $('hotelNearby').addEventListener('click',async()=>{if(!journey.hotel)return toast('Set My Hotel first.');const res=await discoverPlaces(['museums','attractions','cafes'],{near:journey.hotel,limit:8,radiusKm:1});showFoundPlaces(`Near ${journey.hotel.name}`,res);});
 $('journeyReset').addEventListener('click',()=>{Object.assign(journey,{interests:[],food:[],services:[],named:[],extra:{},removed:new Set(),replaced:{},plan:null,lastFound:null,active:false});setEndMode('fixed');resetRoutes();renderJourneyPanel();renderCityWalk();syncMapData();});
 // Privacy: My Hotel is stored only when the user ticks "Remember on this device".
 try{const saved=JSON.parse(localStorage.getItem('sw.myHotel')||'null');if(saved){journey.rememberHotel=true;$('rememberHotel').checked=true;setMyHotel({...saved,category:'Hotel'});}}catch(e){}
 renderJourneyPanel();renderCityWalk();
}
function addNamedStop(p,required=true){
 if(journey.named.some(n=>n.place.id===p.id))return toast(`${p.name} is already a stop.`);
 if(p.routing_coverage==='search_only')return toast('This source point has no verified walking access; discovery only.');
 if(!inRoutingCoverage(p))return toast(`${p.name} is outside walking-route coverage (Manhattan); it cannot be routed.`);
 journey.removed.delete(p.id);journey.named.push({place:p,required,order:null,visitMin:VISIT_MIN[p.cat]??20,visitEstimated:true});journey.active=true;
 if(journey.endMode==='fixed'&&!getPlace('end'))setEndMode('open');
 renderJourneyPanel();syncMapData();toast(`Added ${p.name}. Plan My Walk to route it.`);
}
function renderJourneyPanel(){
 const root=$('journeyStops');if(!root)return;
 const chips=[...journey.interests.map(i=>INTEREST_LABEL[i]+(journey.extra[i]?` +${journey.extra[i]}`:'')),...journey.food.map(foodLabel),...journey.services.map(s=>SERVICE_LABEL[s.type]+(s.addAsStop?' (stop)':' (find)'))];
 const end={fixed:getPlace('end')?.name||'destination not set',open:'flexible end',round:'back to start',hotel:journey.hotel?`back to ${journey.hotel.name}`:'back to hotel (not set)'}[journey.endMode];
 const planned=journey.plan?.stops.filter(s=>s.role!=='end')||[];
 root.innerHTML=`<div class="js-summary">${chips.length?chips.map(c=>`<span class="intent-tag">${esc(c)}</span>`).join(''):'<span class="soft-copy">No discovery request yet. Describe what you want, or add stops.</span>'}</div>
  <p class="js-end">From <strong>${esc(getPlace('start')?.name||'start not set')}</strong> · to <strong>${esc(end)}</strong></p>
  ${journey.named.length?`<ol class="js-list">${journey.named.map((n,i)=>`<li><span class="js-name">${esc(n.place.name)}<small>${esc(n.place.category||'')}${n.place.borough&&n.place.borough!=='Manhattan'?' · outside route coverage':''}</small></span>
   <span class="js-ctl"><button type="button" data-js-req="${i}" title="Required or optional" aria-pressed="${n.required}">${n.required?'Required':'Optional'}</button>
   <label title="Visit minutes (estimate, editable)"><input type="number" min="0" step="5" value="${n.visitMin}" data-js-visit="${i}" aria-label="Visit minutes for ${esc(n.place.name)}">min</label>
   <button type="button" data-js-up="${i}" aria-label="Move up" ${i?'':'disabled'}>↑</button><button type="button" data-js-x="${i}" aria-label="Remove">×</button></span></li>`).join('')}</ol>
   <label class="constraint-check"><input type="checkbox" id="jsKeepOrder" ${journey.named.some(n=>n.order!=null)?'checked':''}> Keep this order</label>`:''}
  ${planned.length&&!journey.named.length?`<p class="soft-copy">Planned stops are listed under “Your city walk” on the right.</p>`:''}
  ${journey.lastFound?foundListHtml():''}`;
 root.querySelectorAll('[data-js-req]').forEach(b=>b.addEventListener('click',()=>{const n=journey.named[+b.dataset.jsReq];n.required=!n.required;renderJourneyPanel();}));
 root.querySelectorAll('[data-js-visit]').forEach(inp=>inp.addEventListener('change',()=>{const n=journey.named[+inp.dataset.jsVisit],v=Number(inp.value);if(Number.isFinite(v)&&v>=0&&v<=600){n.visitMin=v;n.visitEstimated=false;}else inp.value=n.visitMin;}));
 root.querySelectorAll('[data-js-up]').forEach(b=>b.addEventListener('click',()=>{const i=+b.dataset.jsUp;[journey.named[i-1],journey.named[i]]=[journey.named[i],journey.named[i-1]];if(journey.named.some(n=>n.order!=null))journey.named.forEach((n,k)=>n.order=k+1);renderJourneyPanel();}));
 root.querySelectorAll('[data-js-x]').forEach(b=>b.addEventListener('click',()=>{const n=journey.named.splice(+b.dataset.jsX,1)[0];journey.removed.add(n.place.id);renderJourneyPanel();syncMapData();}));
 $('jsKeepOrder')?.addEventListener('change',e=>{journey.named.forEach((n,k)=>n.order=e.target.checked?k+1:null);});
 bindFoundList(root);
 $('journeyCount').textContent=journey.named.length||planned.length?`${journey.named.length||planned.length} STOP${(journey.named.length||planned.length)===1?'':'S'}`:'';
}
function foundListHtml(){
 const f=journey.lastFound;
 return `<div class="js-found"><div class="js-found-head">${esc(f.title)}</div>${f.places.length?f.places.map((p,i)=>`<div class="js-found-item"><span><strong>${esc(p.name)}</strong><small>${esc([p.category,p.address].filter(Boolean).join(' · '))}${p.detour?` · +${p.detour.detour_min} min walking detour`:p.straightKm!=null?` · ${p.straightKm} km straight-line`:''}</small></span>
  <span>${f.hotel?`<button type="button" class="mini-outline" data-found-hotel="${i}">My hotel</button>`:''}<button type="button" class="mini-outline" data-found-add="${i}">Add stop</button></span></div>`).join(''):'<p class="soft-copy">No matching place in the walking-route area.</p>'}
  <small>${esc(f.note||'')} Source: OpenStreetMap / NYC Open Data snapshot; hours as mapped, not live.</small></div>`;
}
function bindFoundList(root){
 root.querySelectorAll('[data-found-add]').forEach(b=>b.addEventListener('click',()=>addNamedStop(journey.lastFound.places[+b.dataset.foundAdd])));
 root.querySelectorAll('[data-found-hotel]').forEach(b=>b.addEventListener('click',()=>{const p=journey.lastFound.places[+b.dataset.foundHotel];setMyHotel(p);appendChat('assistant',`My hotel set to ${p.name}.`);}));
}
function showFoundPlaces(title,places,opts={}){journey.lastFound={title,places,note:opts.note||null,hotel:Boolean(opts.hotel)};renderJourneyPanel();syncMapData();}
function askChoice(question,places,onPick){
 appendChat('assistant',question);
 const box=document.createElement('div');box.className='chat-choices';
 box.innerHTML=places.map((p,i)=>`<button type="button" class="mini-outline" data-choice="${i}">${esc(p.name)}${p.address?` · ${esc(p.address)}`:''}</button>`).join('');
 box.querySelectorAll('[data-choice]').forEach(b=>b.addEventListener('click',()=>{onPick(places[+b.dataset.choice]);box.remove();}));
 $('chatHistory').appendChild(box);$('chatHistory').scrollTop=$('chatHistory').scrollHeight;
}

/* ---------- Route Intelligence: Your City Walk ---------- */
function renderCityWalk(){
 const root=$('cityWalk');if(!root)return;
 const it=journey.plan;root.classList.toggle('hidden',!it&&!journeyMode());
 if(!it){root.innerHTML=`<div class="section-row"><div class="section-overline">YOUR CITY WALK</div></div><p class="soft-copy">Describe what you want to see, eat or do — or add stops — then Plan My Walk.</p>`;return;}
 const t=it.totals,c=it.constraints,route=state.routes[0]?.raw;
 const stopRows=it.stops.map(s=>{
  const menuRows=stopMenuItems(s).map(item=>{
   const m=menuEvidenceForDisplay(journey.menu[s.id+'|'+item]),url=m?.menu_source_url||m?.source_url;
   return `<small class="cw-menu ${m?.status||''}">${esc(item)}: ${esc(MENU_LABEL[m?.status]||'not checked')}${m?.price?` · $${m.price.toFixed(2)} as listed`:''}${url?` · <a href="${esc(url)}" target="_blank" rel="noopener">source</a>`:''}${m?.reason?` — ${esc(m.reason)}`:''}</small>`;
  }).join('');
  const p=placeCache[s.id],hrs=p?.hours||s.hours;const open=s.open_at_arrival!=null?s.open_at_arrival:hrs?isOpenAt(hrs,new Date(Date.now()+s.arrival_min*60000)):null;
  return `<li class="cw-stop ${s.role==='end'?'end':''}"><span class="cw-seq">${s.role==='end'?'■':s.seq}</span><span class="cw-body"><strong>${esc(s.name)}</strong>
   <small>${esc([s.category,s.address].filter(Boolean).join(' · '))}</small>
   <small>Arrive ~${clockAt(s.arrival_min)} · +${(s.leg_in_m/1000).toFixed(2)} km / ${Math.round(s.leg_in_min)} min walk${s.visit_min?` · stay ${s.visit_min} min (est.)`:''}${s.slot_label?` · for “${esc(s.slot_label)}”`:''}${s.required?'':' · optional'}</small>
   ${open===false?'<small class="cw-warn">Opening hours (OSM) say closed at arrival time</small>':open===true?'<small class="cw-ok">Open at arrival per OSM hours</small>':hrs?'<small>Hours listed but not machine-readable</small>':'<small>Hours not listed</small>'}${s.closes_during_visit?'<small class="cw-warn">Closes during the planned visit (OSM hours)</small>':''}
   ${menuRows}
   ${stopMenuItems(s).some(item=>journey.recs[s.id+'|'+item])?stopMenuItems(s).map(item=>journey.recs[s.id+'|'+item]?recExplain(journey.recs[s.id+'|'+item]):'').join(''):s.evidence?`<small>${esc(s.evidence)}</small>`:''}
   ${s.alternatives?.length?`<button type="button" class="cw-alt" data-cw-replace="${esc(s.slot_id)}" data-cw-id="${esc(s.id)}">Replace</button>`:''}${s.role!=='end'?`<button type="button" class="cw-alt" data-cw-remove="${esc(s.id)}">Remove</button>`:''}</span></li>`;}).join('');
 root.innerHTML=`<div class="section-row"><div class="section-overline">YOUR CITY WALK</div><span class="small-count">${c.feasible?'WITHIN LIMITS':'NOT FEASIBLE'}</span></div>
  <div class="cw-theme">${esc(route?.route_name||'City walk')}</div>
  <p class="soft-copy">From ${esc(it.start.name)}${it.end_mode==='round'?' and back':it.end_mode==='hotel'?' back to your hotel':it.end_mode==='open'?' · flexible end':''}.</p>
  <div class="cw-grid"><div><span>Walking</span><strong>${(t.walk_m/1000).toFixed(2)} km</strong><small>${Math.round(t.walk_min)} min</small></div><div><span>Stops</span><strong>${t.stops}</strong><small>${Math.round(t.visit_min)} min stay (est.)</small></div>
   <div><span>Total outing</span><strong>${Math.round(t.outing_min)} min</strong><small>${c.max_outing_minutes?`limit ${c.max_outing_minutes}`:'no limit set'}</small></div><div><span>Experience</span><strong>${route?.personalized_score?.utility??'N/A'}</strong><small>route match</small></div></div>
  ${c.violations.length?`<p class="cw-warn">${esc(c.violations.join('; '))}. Required stops are never dropped silently: remove one or extend the limit.</p>`:''}
  <ol class="cw-stops">${stopRows}</ol>
  ${it.skipped.length?`<p class="soft-copy">Skipped: ${esc(it.skipped.map(s=>`${s.name} (${s.reason})`).join('; '))}</p>`:''}
  <div class="cw-refine">${[['museums','More museums'],['historic','More historic'],['coffee','Add coffee'],['cappuccino','Find cappuccino'],['restaurant','Add restaurant'],['hotel','Return to hotel'],['less','Less walking'],['extend','Extend time']].map(([k,l])=>`<button type="button" class="mini-outline" data-refine="${k}">${l}</button>`).join('')}</div>
  <small class="cw-method">${esc(it.method.join(' · '))}. Matrix: ${it.matrix.points} places, ${esc(it.matrix.basis)}. ${esc(it.coverage)}</small>`;
 root.querySelectorAll('[data-refine]').forEach(b=>b.addEventListener('click',()=>refineWalk(b.dataset.refine)));
 root.querySelectorAll('[data-cw-remove]').forEach(b=>b.addEventListener('click',()=>{journey.removed.add(b.dataset.cwRemove);journey.named=journey.named.filter(n=>n.place.id!==b.dataset.cwRemove);planJourney(true);}));
 root.querySelectorAll('[data-cw-replace]').forEach(b=>b.addEventListener('click',()=>{journey.removed.add(b.dataset.cwId);delete journey.replaced[b.dataset.cwReplace];planJourney(true);}));
}
// evidence sections of a server recommendation, kept apart: facts / derived / interpretation / unknown
function recExplain(r){
 const e=r.explanation,li=a=>a.map(x=>`<li>${esc(x)}</li>`).join('');
 return `<details class="cw-why"><summary>${esc(e.interpretation)}</summary>${e.verified_facts.length?`<b>Verified facts</b><ul>${li(e.verified_facts)}</ul>`:''}
  ${e.derived_metrics.length?`<b>Derived metrics</b><ul>${li(e.derived_metrics)}</ul>`:''}<b>Interpretation</b><p>${esc(e.interpretation)} <i>(${esc(e.interpretation_basis)})</i></p>
  ${e.unknown.length?`<b>Unknown</b><ul>${li(e.unknown)}</ul>`:''}</details>`;
}
const placeCache={};
async function cacheStopPlaces(){if(!journey.plan)return;for(const s of journey.plan.stops){if(!placeCache[s.id]){const p=await placeById(s.id);if(p)placeCache[s.id]=p;}}renderCityWalk();}
async function refineWalk(k){
 const j={interests:[],named_stops:[],food:[],services:[],more:{},remove:[]};
 if(k==='museums')j.more.museums=1;else if(k==='historic')j.more.historic=1;
 else if(k==='coffee')j.food.push({category:'cafes',item:null,required:true});else if(k==='cappuccino')j.food.push({category:'cafes',item:'cappuccino',required:true});
 else if(k==='restaurant')j.food.push({category:'restaurants',item:null,cuisine:null,required:true});
 else if(k==='hotel'){if(!journey.hotel)return toast('Set My Hotel first.');j.end_mode='hotel';}
 else if(k==='less')j.less_walking=true;
 else if(k==='extend'){const base=state.outingMin||state.budget;j.outing_minutes=base+30;}
 const changes=await applyJourney(j);appendChat('assistant',`Updated: ${changes.join(' · ')}. Re-planning…`);planJourney(true);
}

/* ---------- map: numbered stops, hotel, found places ---------- */
function setupJourneyMap(){
 const m=state.map;
 for(const id of ['journey-found','journey-stops','journey-hotel'])m.addSource(id,{type:'geojson',data:emptyFC()});
 m.addLayer({id:'journey-found',type:'circle',source:'journey-found',paint:{'circle-radius':['interpolate',['linear'],['zoom'],12,3,16,6],'circle-color':'#b7a3e1','circle-stroke-color':'#0a0b0c','circle-stroke-width':1.5,'circle-opacity':.9}});
 m.addLayer({id:'journey-hotel',type:'circle',source:'journey-hotel',paint:{'circle-radius':['interpolate',['linear'],['zoom'],12,6,16,10],'circle-color':'#f2a876','circle-stroke-color':'#0a0b0c','circle-stroke-width':2.5}});
 m.addLayer({id:'journey-hotel-label',type:'symbol',source:'journey-hotel',layout:{'text-field':'H','text-font':['Montserrat Medium','Open Sans Regular'],'text-size':11,'text-allow-overlap':true},paint:{'text-color':'#0a0b0c'}});
 m.addLayer({id:'journey-stops',type:'circle',source:'journey-stops',paint:{'circle-radius':['interpolate',['linear'],['zoom'],12,7,16,11],'circle-color':'#0a0b0c','circle-stroke-color':['case',['get','planned'],'#d8f365','#919397'],'circle-stroke-width':2.5}});
 m.addLayer({id:'journey-stops-label',type:'symbol',source:'journey-stops',layout:{'text-field':['to-string',['get','seq']],'text-font':['Montserrat Medium','Open Sans Regular'],'text-size':11,'text-allow-overlap':true},paint:{'text-color':'#d8f365'}});
 for(const id of ['journey-found','journey-stops','journey-hotel']){
  m.on('click',id,e=>{if(state.pick)return;const f=e.features?.[0];if(f)journeyPopup(f,e.lngLat);});
  m.on('mouseenter',id,()=>{m.getCanvas().style.cursor='pointer';});m.on('mouseleave',id,()=>{m.getCanvas().style.cursor='';});
 }
}
function updateJourneyMap(){
 const m=state.map;if(!state.mapLayersReady||!m.getSource('journey-stops'))return;
 const fc=fs=>({type:'FeatureCollection',features:fs});
 const pt=(p,props)=>({type:'Feature',properties:props,geometry:{type:'Point',coordinates:[p.lon,p.lat]}});
 const stops=journey.plan?journey.plan.stops.filter(s=>s.role!=='end').map(s=>pt(s,{id:s.id,seq:s.seq,name:s.name,planned:true})):journey.named.map((n,i)=>pt(n.place,{id:n.place.id,seq:i+1,name:n.place.name,planned:false}));
 m.getSource('journey-stops').setData(fc(stops));
 m.getSource('journey-hotel').setData(fc(journey.hotel?[pt(journey.hotel,{id:journey.hotel.id,name:journey.hotel.name,hotel:true})]:[]));
 m.getSource('journey-found').setData(fc((journey.lastFound?.places||[]).map((p,i)=>pt(p,{id:p.id,name:p.name,i,found:true}))));
}
function tourismHref(value){try{const u=new URL(value);return ['https:','http:'].includes(u.protocol)?u.href:'#';}catch{return '#';}}
async function journeyPopup(f,lngLat){
 const pr=f.properties;
 const p=pr.found?journey.lastFound.places[pr.i]:pr.hotel?journey.hotel:(await placeById(pr.id))||journey.named.find(n=>n.place.id===pr.id)?.place||{name:pr.name,id:pr.id};
 const d=p.id?await placeDetails(p.id):null;
 const isHotel=/hotel|hostel|guest/i.test(p.category||'')||p.cat==='hotels';
 const cafe=p.cat==='cafes'||/caf/i.test(p.category||'');
 const div=document.createElement('div');div.className='jp';
 div.innerHTML=`<strong>${esc(p.name)}</strong><dl>${[['Category',p.category],['Address',p.address],['Hours (OSM)',p.hours],['Website',p.website?`<a href="${esc(tourismHref(p.website))}" target="_blank" rel="noopener">${esc(p.website.replace(/^https?:\/\//,'').slice(0,40))}</a>`:null],['Source',p.source]].filter(x=>x[1]).map(([k,v])=>`<dt>${k}</dt><dd>${k==='Website'?v:esc(v)}</dd>`).join('')}</dl>
  ${d?typedCard(d):''}
  <div class="jp-actions">${!pr.planned?'<button type="button" data-a="add">Add stop</button>':''}${isHotel?'<button type="button" data-a="hotel">Set as My Hotel</button>':''}${d?.restaurant?`<input data-menu-item aria-label="Dish or drink to verify" placeholder="Dish / drink" value="${esc(journey.food.find(x=>x.item)?.item||'')}"><button type="button" data-a="menu">Verify menu item</button>`:''}${d?'<button type="button" data-a="ratings">Ratings</button>':''}${d?.category==='hotels'?`<label>Check-in <input type="date" data-stay="in" aria-label="Check-in date" value="${esc(journey.requirements.checkin||'')}"></label><label>Check-out <input type="date" data-stay="out" aria-label="Check-out date" value="${esc(journey.requirements.checkout||'')}"></label><label>Guests <input type="number" min="1" max="12" data-stay="guests" value="${journey.requirements.guests||2}"></label><button type="button" data-a="rooms">Rooms &amp; prices</button>`:''}</div><div class="jp-menu"></div>`;
 div.querySelector('[data-a="ratings"]')?.addEventListener('click',async()=>{const out=div.querySelector('.jp-menu');out.textContent='Asking rating providers…';
  try{const r=await placeRatings(d.place_id);out.innerHTML=r.ratings.length?r.ratings.map(x=>`<div><strong>${esc(x.provider)}</strong> ${esc(x.rating??'Not Available')}/${x.rating_scale} · ${esc(x.review_count??'count unavailable')} reviews${x.url?` · <a href="${esc(tourismHref(x.url))}" target="_blank" rel="noopener">${esc(x.attribution)}</a>`:''}</div>`).join('')+'<small>Shown per provider; never combined.</small>'
   :`<strong>${r.status==='blocked_by_provider_access'?'Blocked by provider access':'Unavailable'}</strong> ${esc(r.status==='blocked_by_provider_access'?'No rating provider (Google Places, Yelp, Foursquare) is configured on the server, so no rating is shown.':r.errors.map(x=>x.provider+': '+x.error).join('; '))}`;}
  catch(e){out.textContent=`Ratings unavailable (${e.message}).`;}});
 div.querySelector('[data-a="rooms"]')?.addEventListener('click',async()=>{const out=div.querySelector('.jp-menu');out.textContent='Checking lodging providers…';
  try{const r=await streetwiseFetch('/api/hotels/'+d.place_id.split('/').map(encodeURIComponent).join('/')+'/rooms?'+new URLSearchParams(Object.fromEntries(Object.entries({beds:journey.requirements.beds,max_price:journey.requirements.hotel_budget_per_night_usd,guests:div.querySelector('[data-stay="guests"]').value||2,checkin:div.querySelector('[data-stay="in"]').value||null,checkout:div.querySelector('[data-stay="out"]').value||null}).filter(([,v])=>v!=null))),{signal:AbortSignal.timeout(15000)});const x=await r.json();
   out.innerHTML=`<strong>${x.status==='blocked_by_provider_access'?'Blocked by provider access':esc(x.status||'Unavailable')}</strong> ${esc(x.reason||x.error||'')}`;}catch(e){out.textContent=`Room check unavailable (${e.message}).`;}});
 div.querySelector('[data-a="add"]')?.addEventListener('click',()=>addNamedStop(p));
 div.querySelector('[data-a="hotel"]')?.addEventListener('click',()=>{setMyHotel(p);toast(`My hotel: ${p.name}`);});
 div.querySelector('[data-a="menu"]')?.addEventListener('click',async()=>{const out=div.querySelector('.jp-menu');out.textContent='Checking the official menu…';const item=div.querySelector('[data-menu-item]').value.trim();if(!item){out.textContent='Enter a dish or drink to verify.';return;}const r=await verifyMenuItem(p,item);
  out.innerHTML=`<strong>${esc(MENU_LABEL[r.status]||r.status)}</strong> ${esc(r.reason||'')}${r.source_url?` <a href="${esc(tourismHref(r.source_url))}" target="_blank" rel="noopener">source</a>`:''}`;});
 new maplibregl.Popup({maxWidth:'300px'}).setLngLat(lngLat).setDOMContent(div).addTo(state.map);
}

// category card from GET /api/places/<id>: every value from a named source; absent values are said to be absent
function typedCard(d){
 const row=(k,v)=>v==null||v===''?'':`<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`;
 let rows='';
 if(d.restaurant){const r=d.restaurant,i=r.inspection;
  rows+=row('Cuisine',(r.cuisine||r.cuisine_dohmh||'').replace(/;/g,', ')||null)+row('Health grade',i?.grade?`${i.grade} (${i.grade_date}) — NYC DOHMH inspection, not a review`:i?'No letter grade on file':null)+
   row('Last inspected',i?.last_inspection)+row('Services (OSM)',r.services_osm?Object.entries(r.services_osm).map(([k,v])=>`${k.replace('_',' ')}: ${v}`).join(', '):null)+row('Menu',r.menu_url?'official menu link mapped':'checked per request on the official website')+row('Item prices','Not Available until verified from an associated menu item')+row('Reviews','Provider query required; no default rating');}
 if(d.hotel){const h=d.hotel;
  rows+=row('Stars',h.star_rating?`${h.star_rating} (${h.star_rating_source})`:'not mapped')+row('Guest rating','only from a configured provider; never mixed with stars')+
   row('Wi-Fi (OSM)',h.internet_access)+row('Check-in / out',h.check_in||h.check_out?`${h.check_in||'?'} / ${h.check_out||'?'}`:null)+row('NYC DOF lot',h.dof_hotel_lot?`${h.dof_hotel_lot.bbl} · class ${h.dof_hotel_lot.building_class}`:null)+row('Amenities (source)',(d.amenities||[]).join(', ')||'Not Available')+row('Rooms & prices','Unavailable until an authorized provider responds for your dates and party');}
 if(d.attraction){const a=d.attraction;
  rows+=row('About',a.description&&`${a.description} (${a.description_source})`)+row('Admission',a.admission?`${a.admission} (${a.admission_source})`:'unknown')+row('Reservation',a.reservation)+
   row('Typical visit',`${a.recommended_visit_min} min — ${a.visit_duration_basis}`)+row('Landmark',a.designated_landmark?'NYC designated (LPC)':null);}
 const provenance=row('Public access',d.public_access?.basis)+row('Corroboration',(d.verification_basis||[]).map(x=>`${x.source} ${x.record_id}: ${x.scope}`).join('; '))+row('Hours evidence',d.opening_hours?'OSM mapped schedule; may be missing/outdated; not live status. PH rules need a holiday calendar.':null)+row('Updated at source',d.source_updated_at||'Unknown')+row('Retrieved',d.retrieved_at||'Unknown')+row('Last verified',d.last_verified_at||'Not independently verified')+row('Conflicts',d.field_conflicts?.length?d.field_conflicts.map(x=>x.field).join(', '):null)+row('Coverage',d.routing_coverage==='search_only'?'search only — walking access unverified':null)+row('Sources',d.data_sources.join(', '));
 return `<span class="jp-q ${esc(d.quality_status)}">${esc(QUALITY_LABEL[d.quality_status]||d.quality_status)}</span><dl>${rows}</dl><details><summary>Evidence &amp; sources</summary><dl>${provenance}</dl><small>${esc(d.verification_scope||'Source evidence only; current business facts may be unavailable.')}</small>${d.official_website?`<p><a href="${esc(tourismHref(d.official_website))}" target="_blank" rel="noopener">Official website (source)</a></p>`:''}</details>`;
}
