'use strict';
/* Live walking navigation UI on top of nav-engine.js. The route, its maneuvers and its validation come from the STREETWISE
   engine; this file only shows them, follows the GPS, speaks the engine's instructions and asks the engine to re-plan.
   Privacy: positions stay in the browser; the server only receives the current position when a re-route is needed.
   Session: the route snapshot and progress (no GPS track) are kept in sessionStorage for 6 h to survive a page refresh. */
const nav={engine:null,watch:null,units:'metric',voice:true,voiceLang:'en',follow:true,headingUp:false,heading:null,headingSrc:null,
 last:null,queue:[],lastReroute:0,rerouteFails:0,wakeLock:null,lastCam:0,sessionKey:'sw.nav.v1'};
const NAV_ARROWS={depart:'M12 20V5m0 0-5 5m5-5 5 5',continue:'M12 20V5m0 0-5 5m5-5 5 5',turn_left:'M17 20v-7a4 4 0 0 0-4-4H5m0 0 4-4M5 9l4 4',
 turn_right:'M7 20v-7a4 4 0 0 1 4-4h8m0 0-4-4m4 4-4 4',slight_left:'M15 20v-6L8 7m0 0v5m0-5h5',slight_right:'M9 20v-6l7-7m0 0v5m0-5h-5',
 sharp_left:'M16 4v9a3 3 0 0 1-5 2L5 9m0 0v6m0-6h6',sharp_right:'M8 4v9a3 3 0 0 0 5 2l6-6m0 0v6m0-6h-6',keep_left:'M14 20v-5L9 9V4m0 0L6 7m3-3 3 3',
 keep_right:'M10 20v-5l5-6V4m0 0-3 3m3-3 3 3',u_turn:'M8 20V9a4 4 0 0 1 8 0v4m0 0-3-3m3 3 3-3',cross:'M4 12h16M7 8v8M12 8v8M17 8v8',
 enter_path:'M12 20V5m0 0-5 5m5-5 5 5',arrive_stop:'M12 21s-6-5.5-6-10a6 6 0 1 1 12 0c0 4.5-6 10-6 10zm0-8a2 2 0 1 0 0-4 2 2 0 0 0 0 4',
 arrive:'M5 21V4m0 0h11l-2 4 2 4H5',notice:'M12 8v5m0 3h.01M10.3 3.9 2.6 17a2 2 0 0 0 1.7 3h15.4a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z'};
const navArrow=t=>`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="${NAV_ARROWS[t]||NAV_ARROWS.continue}"/></svg>`;
const STATE_TEXT={GPS_WEAK:'Weak GPS signal — position approximate',POSSIBLY_OFF_ROUTE:'Checking whether you left the route…',OFF_ROUTE:'Off route',
 REROUTING:'Off route — recalculating on the walking network…',PAUSED:'Paused',ARRIVED_AT_STOP:'Arrived at stop',ARRIVED:'You have arrived',ERROR:'Navigation problem'};

function activeRouteObject(){return state.routes.find(r=>r.id===state.activeRoute)?.raw||null;}
/** Start Navigation is offered only for a selected route whose validation allows it. */
function renderNavStart(){
 const btn=$('navStart'),r=activeRouteObject();if(!btn)return;
 const v=r?.validation,ok=Boolean(r&&r.maneuvers?.length&&(!v||v.navigation_allowed));
 btn.classList.toggle('hidden',!r||nav.engine!=null);btn.disabled=!ok;
 btn.title=!r?'':!r.maneuvers?.length?'This route has no turn instructions (plan it again).':v&&!v.navigation_allowed?`Blocked: ${v.blocking_issues.join(' ')}`:'Start live walking navigation';
 renderValidation(r);
}
const VSTATUS={pass:'Pass',pass_with_warnings:'Pass with warnings',fail:'Fail',not_checked:'Not checked',warning:'Warning'};
function renderValidation(r){
 const box=$('routeValidation');if(!box)return;const v=r?.validation;
 if(!v){box.innerHTML='';box.classList.add('hidden');return;}
 box.classList.remove('hidden');
 const rows=[['Geometry',v.geometry_status],['Walking network',v.pedestrian_network_status],['Required stops',v.required_stops_status],['Stop access',v.stop_access_status],
  ['Time limit',v.time_constraint_status],['Distance limit',v.distance_constraint_status],['Food evidence',foodEvidenceStatus(r)]];
 box.innerHTML=`<details><summary><span class="rv-badge ${v.status}">${VSTATUS[v.status]}</span> Route check · ${esc(v.validation_version)}</summary>
  <dl class="rv-grid">${rows.map(([k,s])=>`<dt>${k}</dt><dd class="${s}">${VSTATUS[s]||esc(s)}</dd>`).join('')}</dl>
  ${v.blocking_issues.length?`<p class="rv-block">${v.blocking_issues.map(esc).join('<br>')}</p>`:''}
  ${v.warnings.length?`<ul class="rv-warn">${v.warnings.map(w=>`<li>${esc(w)}</li>`).join('')}</ul>`:''}
  <small>Checked ${esc(v.validation_timestamp)} on ${esc(v.data_coverage.network_version||'')}. Scores: ${esc(v.data_coverage.score_version||'')}; N/A: ${esc(v.data_coverage.not_available.join(', ')||'none')}.</small></details>`;
}
/** Food evidence comes from the separate menu check, never assumed. */
function foodEvidenceStatus(r){
 if(typeof journey==='undefined'||!journey.plan||r?.objective!=='itinerary')return 'not_checked';
 const items=journey.plan.stops.map(s=>{const f=journey.food.find(f=>s.slot_id===`food:${f.category}:${f.item||f.cuisine||''}`&&f.item);return f?journey.menu[s.id+'|'+f.item]:null;}).filter(Boolean);
 if(!items.length)return 'not_checked';
 return items.every(m=>m.status==='confirmed_menu_match')?'pass':items.some(m=>m.status==='checking')?'not_checked':'warning';
}

/* ---------- start ---------- */
async function startNavigation(){
 const r=activeRouteObject();if(!r||nav.engine)return;
 if(r.validation&&!r.validation.navigation_allowed)return toast('This route failed its route check and cannot be navigated.');
 if(!navigator.geolocation)return toast('Location is not available in this browser.');
 // iOS asks for compass access only inside a user gesture
 try{if(typeof DeviceOrientationEvent!=='undefined'&&typeof DeviceOrientationEvent.requestPermission==='function')await DeviceOrientationEvent.requestPermission();}catch(e){}
 showNavCard({status:'Getting your location…'});
 const fix=await new Promise(res=>navigator.geolocation.getCurrentPosition(p=>res(p),e=>res({error:e}),{enableHighAccuracy:true,timeout:15000,maximumAge:5000}));
 if(fix.error){hideNav();return toast({1:'Location permission was denied. Allow location for this site to navigate.',2:'Your position is unavailable (GPS off?).',3:'Locating timed out. Try again outdoors.'}[fix.error.code]||'Location error.');}
 const here={lon:fix.coords.longitude,lat:fix.coords.latitude},acc=fix.coords.accuracy||50;
 const start=r.geometry.coordinates[0],away=haversineKm(here,{lon:start[0],lat:start[1]})*1000;
 if(away>Math.max(60,2*acc)){hideNav();return askStartChoice(r,here,away);}
 beginNavigation(r);
}
function askStartChoice(r,here,away){
 const box=$('navChoice');box.classList.remove('hidden');
 box.innerHTML=`<div class="nav-choice-card"><strong>You are ${formatNavDistance(away,nav.units)} from the start of this route.</strong>
  <p>Choose how to begin. STREETWISE will not pretend you are at the start.</p>
  <button type="button" class="primary-cta" data-c="to-start">Navigate to start</button><button type="button" class="mini-outline" data-c="replan">Replan from my location</button><button type="button" class="mini-outline" data-c="cancel">Cancel</button></div>`;
 box.onclick=async e=>{const c=e.target.dataset?.c;if(!c)return;box.classList.add('hidden');
  if(c==='to-start'){const s=r.geometry.coordinates[0];const leg=await requestRoute(here,{lon:s[0],lat:s[1]});if(leg){nav.queue=[r];beginNavigation(leg,{temporary:true});}}
  else if(c==='replan'){state.gps={...here,accuracy:null};state.start='gps';$('searchStart').value='My current location';
   if(typeof journeyMode==='function'&&journeyMode())await planJourney(true);else await generateRoutes(null,true);toast('Re-planned from your location. Tap Start Navigation.');}};
}
/** Plain A→B walking route from the engine (used for "navigate to start" and simple re-routes). */
async function requestRoute(from,to){
 try{const body={...buildRouteRequest({lat:from.lat,lon:from.lon},{lat:to.lat,lon:to.lon}),weather:null};
  const res=await streetwiseFetch('/api/routes',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body),signal:AbortSignal.timeout(30000)});
  const j=await res.json();if(!res.ok)throw new Error(j.error||`HTTP ${res.status}`);
  const best=j.routes.find(x=>x.recommended)||j.routes.slice().sort((a,b)=>a.distance_m-b.distance_m)[0];
  if(best?.validation&&!best.validation.navigation_allowed)throw new Error('the new route failed its route check');
  return best;
 }catch(e){toast('Could not plan the walking route: '+e.message);return null;}
}
function beginNavigation(route,opts={}){
 stopWatch();
 const eng=new NavEngine(route,{progress_m:opts.progress_m||0});
 if(eng.blocked){toast('Route check failed: '+eng.blocked.join(' '));return;}
 nav.engine=eng;nav.temporary=Boolean(opts.temporary);nav.route=route;
 if(opts.restore){eng.next=opts.restore.next;opts.restore.arrived.forEach(a=>eng.arrivedStops.add(a));}
 eng.on(onNavEvent);eng.transition('READY');eng.transition('STARTING','start');
 document.body.classList.add('nav-mode');setDataLayersForNav(true);drawNavRoute(route);showNavCard({});
 nav.follow=true;nav.watch=navigator.geolocation.watchPosition(onFix,onFixError,{enableHighAccuracy:true,maximumAge:1000,timeout:20000});
 nav.tick=setInterval(()=>{eng.tick();renderNav();},3000);
 window.addEventListener('deviceorientationabsolute',onOrientation,true);window.addEventListener('deviceorientation',onOrientation,true);
 requestWakeLock();saveNavSession();renderNavStart();
 speak(route.maneuvers?.[0]?(nav.voiceLang==='zh'?route.maneuvers[0].instruction_zh:route.maneuvers[0].instruction_text):'');
}
/** During navigation the map shows the walk, not the data layers (restored on exit). */
function setDataLayersForNav(on){
 if(typeof urbanMapLayerIds!=='function'||!state.mapLayersReady)return;
 for(const id of urbanMapLayerIds())state.map.setLayoutProperty(id,'visibility',on?'none':'visible');
 for(const id of ['journey-found','poi-points','route-alts'])if(state.map.getLayer(id))state.map.setLayoutProperty(id,'visibility',on?'none':'visible');
 if(!on&&typeof applyEnvTheme==='function')applyEnvTheme();
}
function stopWatch(){if(nav.watch!=null)navigator.geolocation.clearWatch(nav.watch);nav.watch=null;clearInterval(nav.tick);}

/* ---------- GPS and compass ---------- */
function onFix(p){
 const c=p.coords;
 const fix={lat:c.latitude,lon:c.longitude,accuracy:Number.isFinite(c.accuracy)?c.accuracy:null,timestamp:p.timestamp||Date.now(),
  speed:Number.isFinite(c.speed)?c.speed:null,heading:Number.isFinite(c.heading)&&(c.speed??0)>.6?c.heading:null};
 if(fix.heading!=null){nav.heading=fix.heading;nav.headingSrc='GPS course';}
 nav.last=fix;const out=nav.engine?.update(fix);renderNav(out);updateCamera();
}
function onFixError(e){
 if(!nav.engine)return;
 if(e.code===1){nav.engine.transition('ERROR','permission revoked');showNavCard({status:'Location permission was turned off. Navigation stopped updating.'});}
 else nav.engine.transition('GPS_WEAK',e.message);
 renderNav();
}
function onOrientation(e){
 // absolute compass only (webkitCompassHeading on iOS, absolute alpha elsewhere); otherwise no cone is drawn
 let h=null;
 if(Number.isFinite(e.webkitCompassHeading))h=e.webkitCompassHeading;else if(e.absolute&&Number.isFinite(e.alpha))h=(360-e.alpha)%360;
 if(h==null)return;
 if(!nav.last||(nav.last.speed??0)<=.6){nav.heading=h;nav.headingSrc='device compass';}
}
async function requestWakeLock(){try{nav.wakeLock=await navigator.wakeLock?.request('screen');}catch(e){nav.wakeLock=null;}}

/* ---------- engine events: voice, arrivals, re-routing ---------- */
function onNavEvent(ev){
 if(ev.type==='alert'&&nav.engine.state!=='PAUSED'){
  const m=ev.maneuver,d=ev.level==='now'?null:ev.distance_m;
  speak(spokenInstruction(m,d,nav.voiceLang,nav.units));
 }else if(ev.type==='arrived_stop'){
  speak(nav.voiceLang==='zh'?ev.maneuver.instruction_zh:ev.maneuver.instruction_text);renderNav();
 }else if(ev.type==='arrived'){
  speak(nav.voiceLang==='zh'?ev.maneuver.instruction_zh:ev.maneuver.instruction_text);
  if(nav.temporary&&nav.queue.length){const next=nav.queue.shift();toast('At the start — now following your planned walk.');beginNavigation(next);return;}
  clearNavSession();renderNav();
 }else if(ev.type==='off_route'){
  speak(nav.voiceLang==='zh'?'您已偏离路线，正在重新规划。':'You are off route. Recalculating.');reroute();
 }else if(ev.type==='state')renderNav();
}
async function reroute(manual=false){
 const eng=nav.engine;if(!eng||!nav.last)return;
 const since=(Date.now()-nav.lastReroute)/1000;
 if(!manual&&since<eng.cfg.rerouteMinSeconds){setTimeout(()=>{if(nav.engine?.state==='OFF_ROUTE')reroute();},(eng.cfg.rerouteMinSeconds-since)*1000);return;}
 if(!eng.transition('REROUTING','off route'))return;
 nav.lastReroute=Date.now();renderNav();
 const here={lat:nav.last.lat,lon:nav.last.lon};let newRoute=null,json=null;
 try{
  if(nav.route.objective==='itinerary'&&typeof journey!=='undefined'&&journey.plan&&journey.request){
   // keep every required stop not reached yet, in the same order; the end stays the same
   const reached=new Set([...eng.arrivedStops].map(id=>eng.maneuvers.find(m=>m.maneuver_id===id)?.stop_name));
   const remaining=journey.plan.stops.filter(s=>s.role!=='end'&&!reached.has(s.name));
   const req={...journey.request,origin:{id:'gps',name:'My location',lat:here.lat,lon:here.lon},slots:[],pool:{max_stops:0,candidates:[]},
    stops:remaining.map((s,i)=>({id:s.id,name:s.name,lat:s.lat,lon:s.lon,required:s.required||true,order:i+1,visit_min:s.visit_min}))};
   const res=await streetwiseFetch('/api/itinerary',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(req),signal:AbortSignal.timeout(30000)});
   json=await res.json();if(!res.ok)throw new Error(json.error||`HTTP ${res.status}`);newRoute=json.routes[0];
  }else{
   const end=nav.route.geometry.coordinates.at(-1);newRoute=await requestRoute(here,{lon:end[0],lat:end[1]});
  }
  if(!newRoute)throw new Error('no route returned');
  if(newRoute.validation&&!newRoute.validation.navigation_allowed)throw new Error('the new route failed its route check');
  nav.rerouteFails=0;
  if(json){journey.plan=json.itinerary;applyRouteResponse(json);}else{state.routes=[adaptRoute(newRoute)];state.activeRoute=newRoute.route_id;}
  eng.transition('NAVIGATING','rerouted');stopWatch();nav.engine=null;beginNavigation(newRoute);
  if(typeof syncMapData==='function')syncMapData();
 }catch(e){
  nav.rerouteFails++;eng.transition('OFF_ROUTE','reroute failed');
  showNavCard({status:`Could not recalculate (${e.message}). Your last route is still shown.`,retry:true});
 }
}

/* ---------- map ---------- */
function setupNavMap(){
 const m=state.map;
 for(const id of ['nav-walked','nav-acc','nav-cone','nav-dot','nav-next'])m.addSource(id,{type:'geojson',data:emptyFC()});
 m.addLayer({id:'nav-walked',type:'line',source:'nav-walked',paint:{'line-color':'#56666a','line-width':['interpolate',['linear'],['zoom'],12,3,16,6,19,9],'line-opacity':.9},layout:{'line-cap':'round','line-join':'round'}});
 m.addLayer({id:'nav-acc',type:'fill',source:'nav-acc',paint:{'fill-color':'#4aa3ff','fill-opacity':.14,'fill-outline-color':'#4aa3ff'}});
 m.addLayer({id:'nav-cone',type:'fill',source:'nav-cone',paint:{'fill-color':'#4aa3ff','fill-opacity':.32}});
 m.addLayer({id:'nav-next',type:'circle',source:'nav-next',paint:{'circle-radius':7,'circle-color':'rgba(0,0,0,0)','circle-stroke-color':'#ffffff','circle-stroke-width':2.5}});
 m.addLayer({id:'nav-dot',type:'circle',source:'nav-dot',paint:{'circle-radius':8,'circle-color':'#2f8cff','circle-stroke-color':'#ffffff','circle-stroke-width':3}});
 m.on('dragstart',e=>{if(nav.engine&&e.originalEvent){nav.follow=false;$('navRecenter')?.classList.add('show');}});
}
function circlePoly(c,r,n=48){const pts=[];for(let i=0;i<=n;i++){const a=i/n*2*Math.PI;pts.push([c[0]+r*Math.sin(a)/84414.3,c[1]+r*Math.cos(a)/111049.7]);}return pts;}
function conePoly(c,h,r=28,spread=32){const pts=[c];for(let a=-spread;a<=spread;a+=8){const t=(h+a)*Math.PI/180;pts.push([c[0]+r*Math.sin(t)/84414.3,c[1]+r*Math.cos(t)/111049.7]);}pts.push(c);return pts;}
const navFC=fs=>({type:'FeatureCollection',features:fs});
function drawNavRoute(route){state.map?.getSource('nav-walked')?.setData(emptyFC());}
function drawNavPosition(out){
 const m=state.map;if(!m?.getSource('nav-dot'))return;
 if(!out||!nav.last){for(const id of ['nav-dot','nav-acc','nav-cone','nav-next','nav-walked'])m.getSource(id).setData(emptyFC());return;}
 const weak=['GPS_WEAK','POSSIBLY_OFF_ROUTE','OFF_ROUTE','REROUTING'].includes(out.state)||out.location_quality==='poor';
 // the dot is the raw GPS position; it snaps to the route only when the match is confident
 const p=out.matched_coordinate&&out.confidence==='high'&&!weak?out.matched_coordinate:out.raw;
 m.getSource('nav-dot').setData(navFC([{type:'Feature',properties:{},geometry:{type:'Point',coordinates:p}}]));
 m.setPaintProperty('nav-dot','circle-color',weak?'#8aa4b8':'#2f8cff');
 m.getSource('nav-acc').setData(out.accuracy_m?navFC([{type:'Feature',properties:{},geometry:{type:'Polygon',coordinates:[circlePoly(out.raw,out.accuracy_m)]}}]):emptyFC());
 m.getSource('nav-cone').setData(nav.heading!=null?navFC([{type:'Feature',properties:{},geometry:{type:'Polygon',coordinates:[conePoly(p,nav.heading)]}}]):emptyFC());
 const nm=out.next_maneuver;m.getSource('nav-next').setData(nm?navFC([{type:'Feature',properties:{},geometry:{type:'Point',coordinates:nm.coordinate}}]):emptyFC());
 const eng=nav.engine,walked=[];for(let s=0;s<=out.progress_m;s+=Math.max(5,out.progress_m/200))walked.push(eng.pointAt(s));walked.push(eng.pointAt(out.progress_m));
 m.getSource('nav-walked').setData(walked.length>1?navFC([{type:'Feature',properties:{},geometry:{type:'LineString',coordinates:walked}}]):emptyFC());
}
function updateCamera(force=false){
 const m=state.map,out=nav.engine?.lastOutput;if(!m||!out||(!nav.follow&&!force))return;
 const now=Date.now();if(!force&&now-nav.lastCam<1200)return;nav.lastCam=now;
 const p=out.matched_coordinate&&out.confidence==='high'?out.matched_coordinate:out.raw;
 const small=window.innerWidth<=740;
 m.easeTo({center:p,zoom:Math.max(m.getZoom(),17),bearing:nav.headingUp&&nav.heading!=null?nav.heading:0,pitch:0,
  padding:{top:small?150:170,bottom:small?170:120,left:20,right:20},duration:force?500:900,essential:true});
}

/* ---------- panels ---------- */
function showNavCard(o){$('navOverlay').classList.remove('hidden');if(o.status!=null){$('navStatus').textContent=o.status;$('navStatus').classList.remove('hidden');}$('navRetry').classList.toggle('hidden',!o.retry);}
function hideNav(){$('navOverlay').classList.add('hidden');document.body.classList.remove('nav-mode');}
function renderNav(out=nav.engine?.lastOutput){
 const eng=nav.engine;if(!eng)return;
 const st=eng.state,nm=out?.next_maneuver||eng.maneuvers[eng.next];
 const d=out?.distance_to_next_m??(nm?nm.distance_along_route_m-eng.progress:null);
 $('navArrow').innerHTML=navArrow(nm?.type);
 $('navDist').textContent=nm&&!nm.type.startsWith('arrive')||d>15?formatNavDistance(d,nav.units):'';
 $('navInstr').textContent=nm?(nav.voiceLang==='zh'?nm.instruction_zh:nm.instruction_text):'Follow the route';
 const after=out?.after_next;$('navThen').textContent=after?`Then: ${nav.voiceLang==='zh'?after.instruction_zh:after.instruction_text}`:'';
 $('navConf').textContent=nm?.confidence==='low'?'Low-confidence instruction — check the map':'';
 const msg=STATE_TEXT[st]||(st==='STARTING'?'Waiting for GPS…':'');
 $('navStatus').textContent=msg+(out?.accuracy_m&&['GPS_WEAK'].includes(st)?` (±${Math.round(out.accuracy_m)} m)`:'');$('navStatus').classList.toggle('hidden',!msg);
 $('navStatus').className='nav-status '+st.toLowerCase();
 $('navRemain').textContent=out?formatNavDistance(out.remaining_m,nav.units):formatNavDistance(eng.netLen,nav.units);
 $('navTime').textContent=out?`${Math.max(1,Math.round(out.remaining_min))} min`:`${Math.round(eng.netLen/80)} min`;
 const stops=out?.remaining_stops||[];$('navStop').textContent=nav.temporary?'To the start of your walk':stops.length?`Next stop: ${stops[0]}${stops.length>1?` · +${stops.length-1}`:''}`:'Destination';
 $('navStopActions').classList.toggle('hidden',st!=='ARRIVED_AT_STOP');
 if(st==='ARRIVED_AT_STOP'){const m=eng.maneuvers[eng.next];$('navStopName').textContent=m?.stop_name||'';$('navStopVisit').textContent=m?.visit_min?`Suggested visit ${m.visit_min} min (estimate)`:'';$('navSkip').classList.toggle('hidden',m?.required!==false);}
 $('navPause').textContent=st==='PAUSED'?'Resume':'Pause';$('navVoice').setAttribute('aria-pressed',String(nav.voice));$('navVoice').textContent=nav.voice?'Voice on':'Voice off';
 $('navUnits').textContent=nav.units==='metric'?'m':'ft';$('navMode').textContent=nav.headingUp?'Heading up':'North up';
 $('navHeadingNote').textContent=nav.heading==null?'No direction data — heading cone hidden':`Direction: ${nav.headingSrc}`;
 $('navArrived').classList.toggle('hidden',st!=='ARRIVED');
 drawNavPosition(out);if(st!=='ARRIVED')saveNavSession();
}
function speak(text){
 if(!nav.voice||!text||!('speechSynthesis' in window))return;
 try{speechSynthesis.cancel();const u=new SpeechSynthesisUtterance(text);u.lang=nav.voiceLang==='zh'?'zh-CN':'en-US';
  const v=speechSynthesis.getVoices().find(v=>v.lang.startsWith(u.lang.slice(0,2)));if(v)u.voice=v;speechSynthesis.speak(u);}catch(e){}
}
function exitNavigation(){
 const eng=nav.engine;if(eng){eng.transition('STOPPED','user exit');}
 stopWatch();try{speechSynthesis.cancel();}catch(e){}nav.wakeLock?.release?.().catch(()=>{});
 window.removeEventListener('deviceorientationabsolute',onOrientation,true);window.removeEventListener('deviceorientation',onOrientation,true);
 nav.engine=null;nav.queue=[];nav.last=null;nav.heading=null;drawNavPosition(null);clearNavSession();hideNav();setDataLayersForNav(false);renderNavStart();
 state.map?.easeTo({bearing:0,duration:400});
}

/* ---------- session (survives refresh; no GPS history) ---------- */
function saveNavSession(){
 const eng=nav.engine;if(!eng||nav.temporary)return;
 const r=nav.route,slim={route_id:r.route_id,route_name:r.route_name,objective:r.objective,route_signature:r.route_signature,network_version:r.network_version,
  geometry:r.geometry,distance_m:r.distance_m,maneuvers:r.maneuvers,edges:(r.edges||[]).map(e=>({edge_id:e.edge_id,traversed_length_m:e.traversed_length_m})),
  ordered_edge_ids:r.ordered_edge_ids,validation:r.validation&&{status:r.validation.status,navigation_allowed:r.validation.navigation_allowed,blocking_issues:r.validation.blocking_issues}};
 try{sessionStorage.setItem(nav.sessionKey,JSON.stringify({v:1,route:slim,progress:eng.snapshot(),created:nav.created||(nav.created=Date.now()),expires:(nav.created||Date.now())+6*3600e3}));}catch(e){}
}
function clearNavSession(){try{sessionStorage.removeItem(nav.sessionKey);}catch(e){}nav.created=null;}
async function offerNavResume(){
 let s=null;try{s=JSON.parse(sessionStorage.getItem(nav.sessionKey)||'null');}catch(e){}
 if(!s)return;if(Date.now()>s.expires){clearNavSession();return;}
 let netVersion=null;try{netVersion=(await streetwiseJson('/api/routing/status',{signal:AbortSignal.timeout(20000)})).network_version;}catch(e){}
 if(!netVersion||netVersion!==s.route.network_version){clearNavSession();toast(netVersion?'The walking network was updated since your navigation started — please plan the walk again.':'Navigation could not be restored (routing service unreachable).');return;}
 const box=$('navChoice');box.classList.remove('hidden');
 box.innerHTML=`<div class="nav-choice-card"><strong>Resume navigation?</strong><p>${esc(s.route.route_name||'Your walk')} · ${formatNavDistance(s.route.distance_m-s.progress.progress_m,nav.units)} left. The same route is restored (signature ${esc(s.route.route_signature)}).</p>
  <button type="button" class="primary-cta" data-c="resume">Resume</button><button type="button" class="mini-outline" data-c="discard">Discard</button></div>`;
 box.onclick=e=>{const c=e.target.dataset?.c;if(!c)return;box.classList.add('hidden');
  if(c==='resume'){nav.created=s.created;beginNavigation(s.route,{progress_m:s.progress.progress_m,restore:s.progress});}else clearNavSession();};
}
function setupNavUI(){
 $('navStart').addEventListener('click',startNavigation);
 $('navExit').addEventListener('click',exitNavigation);$('navArrivedDone').addEventListener('click',exitNavigation);
 $('navRecenter').addEventListener('click',()=>{nav.follow=true;$('navRecenter').classList.remove('show');updateCamera(true);});
 $('navVoice').addEventListener('click',()=>{nav.voice=!nav.voice;if(!nav.voice)try{speechSynthesis.cancel();}catch(e){}renderNav();});
 $('navRepeat').addEventListener('click',()=>{const o=nav.engine?.lastOutput;const m=o?.next_maneuver;if(m){const was=nav.voice;nav.voice=true;speak(spokenInstruction(m,o.distance_to_next_m,nav.voiceLang,nav.units));nav.voice=was;}});
 $('navLang').addEventListener('change',e=>{nav.voiceLang=e.target.value;renderNav();});
 $('navUnits').addEventListener('click',()=>{nav.units=nav.units==='metric'?'imperial':'metric';renderNav();});
 $('navMode').addEventListener('click',()=>{nav.headingUp=!nav.headingUp;renderNav();updateCamera(true);});
 $('navPause').addEventListener('click',()=>{const e=nav.engine;if(!e)return;
  if(e.state==='PAUSED'){e.transition('NAVIGATING','resume');nav.watch=navigator.geolocation.watchPosition(onFix,onFixError,{enableHighAccuracy:true,maximumAge:1000,timeout:20000});}
  else if(e.transition('PAUSED','user')){stopWatch();try{speechSynthesis.cancel();}catch(x){}}renderNav();});
 $('navContinue').addEventListener('click',()=>{nav.engine?.continueFromStop();renderNav();});
 $('navSkip').addEventListener('click',()=>{const e=nav.engine;if(e?.state==='ARRIVED_AT_STOP'){e.continueFromStop();renderNav();}});
 $('navRetry').addEventListener('click',()=>reroute(true));
 offerNavResume();
}
