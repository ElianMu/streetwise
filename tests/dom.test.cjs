/* DOM/state integration. Test-only fixtures never ship into the runtime app. Run with jsdom installed. */
const {JSDOM}=require(process.env.JSDOM_PATH||'jsdom'),fs=require('fs'),path=require('path'),assert=require('node:assert/strict');
const root=path.join(__dirname,'..'),html=fs.readFileSync(path.join(root,'index.html'),'utf8');
const dom=new JSDOM(html,{runScripts:'outside-only',url:'http://localhost:8080'}),w=dom.window;
w.fetch=async()=>{throw new Error('Network intentionally blocked in DOM test')};w.HTMLElement.prototype.scrollIntoView=function(){};w.AbortSignal.timeout=()=>new w.AbortController().signal;
const vm=require('vm'),context=dom.getInternalVMContext();
for(const file of ['experience-core.js','api-config.js','weather.js','places.js','opening-hours.js','app.js','route-story.js','street-photos.js','route-client.js','walk-presets.js','weather-ui.js','journey.js','journey-ui.js','voice.js','nav-engine.js','nav-ui.js','urban-geo.js','urban-style.js','urban-layers.js','side-panels.js','explore-map.js','explore-analytics.js','center-map.js','share-link.js','i18n.js'])vm.runInContext(fs.readFileSync(path.join(root,file),'utf8'),context);
const run=s=>vm.runInContext(s,context);
(async()=>{
 // flatMapBounds: a pitch-independent query box, checked against a real map.getBounds() reading captured live
 // in a browser (zoom 16.5, center [-73.9855,40.758], a 375x754 container, pitch 0 — where the two describe the
 // same thing) — regression-pins the 2^(z+1) MapLibre tile-size convention this depends on (MapLibre's zoom is
 // defined on a 512px base tile, one level ahead of the classic 156543.03392-constant's 256px assumption; this
 // was off by exactly 2x per dimension, 4x area, before accounting for it).
 w.__fmbMock={getZoom:()=>16.5,getCenter:()=>({lat:40.758,lng:-73.9855}),getContainer:()=>({clientWidth:375,clientHeight:754})};
 const fmb=run('flatMapBounds(window.__fmbMock)');
 const realDLng=0.0014224561372060407,realDLat=0.0021664396578131573,cLng=-73.9855,cLat=40.758;
 assert(Math.abs((fmb.getEast()-fmb.getWest())/2-realDLng)/realDLng<0.01,`flatMapBounds lng half-extent ${(fmb.getEast()-fmb.getWest())/2} should match the real map.getBounds() reading (${realDLng}) within 1%`);
 assert(Math.abs((fmb.getNorth()-fmb.getSouth())/2-realDLat)/realDLat<0.01,`flatMapBounds lat half-extent ${(fmb.getNorth()-fmb.getSouth())/2} should match the real map.getBounds() reading (${realDLat}) within 1%`);
 assert(Math.abs((fmb.getWest()+fmb.getEast())/2-cLng)<1e-9&&Math.abs((fmb.getSouth()+fmb.getNorth())/2-cLat)<1e-9,'flatMapBounds is centered on the map center');
 // Pitch independence: the whole point of this function. A second mock at a different zoom confirms the box
 // scales with zoom (smaller at a higher zoom), not with anything pitch-related (pitch isn't even an input).
 w.__fmbMock2={getZoom:()=>17.5,getCenter:()=>({lat:40.758,lng:-73.9855}),getContainer:()=>({clientWidth:375,clientHeight:754})};
 const fmb2=run('flatMapBounds(window.__fmbMock2)');
 assert((fmb2.getEast()-fmb2.getWest())<(fmb.getEast()-fmb.getWest()),'a higher zoom covers less ground, independent of any pitch input (there is none)');

 assert.equal(w.document.querySelectorAll('#experienceDimension option').length,12);
 assert.equal(run("localJourney('I want tiramisu at an Italian restaurant with good reviews').food[0].item"),'tiramisu');
 assert.equal(run("localJourney('I want tiramisu at an Italian restaurant with good reviews').food[0].cuisine"),'italian');
 assert.equal(run("localJourney('Find a hotel with two beds and a budget of $250 per night').requirements.hotel_budget_per_night_usd"),250);
 assert.equal(run("localJourney('Visit two landmarks').counts.famous"),2);

 // Map Mode reads the GIS pipeline output (data/dimensions/manhattan); route-edge inspectors keep the legacy street file.
 const dimDir=path.join(root,'data/dimensions/manhattan'),rd=f=>JSON.parse(fs.readFileSync(path.join(dimDir,f)));
 w.STREETWISE_STREETS=JSON.parse(fs.readFileSync(path.join(root,'data/manhattan-streets.json')));
 w.STREETWISE_DIMENSIONS={manifest:rd('manifest.json'),segments:rd('segments.geojson'),indicators:rd('indicators.json'),no2:rd('context_no2.geojson')};
 const tick=()=>new Promise(r=>setTimeout(r,0)),pad=i=>String(i).padStart(2,'0');
 w.document.querySelector('#modeExplore').click();assert.equal(run('mapExperience.mode'),'explore');
 await run('loadExploreStreets()');assert(!w.document.querySelector('#explorePanel').classList.contains('hidden'));
 assert.equal(w.document.querySelectorAll('#exploreChips [data-view]').length,13);assert.equal(w.document.querySelectorAll('#exploreGrid .explore-dim').length,13);
 assert.equal(w.document.querySelector('#exploreTitle').textContent,'02 Nature');
 assert.equal(w.document.querySelector('#exploreScope').textContent,'ALL MANHATTAN · STREET SEGMENTS');
 assert(w.document.querySelector('#exploreMetric').textContent.includes('canopy_pct'));assert(w.document.querySelector('#exploreMetric').textContent.includes('2/3 scored indicators available'));
 // A real segment whose LION record has no roadway width: that indicator is N/A, never 0.
 const D=w.STREETWISE_DIMENSIONS.indicators,k=D.raw.width_ft.findIndex(v=>v===null),seg=w.STREETWISE_DIMENSIONS.segments.features[k].properties;
 assert.equal(D.ids[k],seg.id);
 run('selectExploreView(0)');run(`selectExploreSegment(${JSON.stringify(seg.id)})`);await tick();await tick();const insp=()=>w.document.querySelector('#exploreInspector');
 assert(!insp().classList.contains('hidden'));assert(insp().textContent.includes(seg.id));assert(insp().textContent.includes('Length'));
 assert(insp().textContent.includes('Overall (available dimensions) · Dimension Score'));assert.equal(insp().querySelectorAll('.explore-row').length,12);assert(insp().textContent.includes(`${seg.coverage} of 12 dimensions`));
 // Three levels: Summary always visible; the 12 dimension rows are buttons that switch the map dimension while the
 // segment stays selected; Methodology is a closed <details> that still holds every original sentence.
 assert(insp().querySelector('.inspector-summary [data-k=dimension-score]')&&insp().querySelector('.inspector-summary [data-k=segment-id]'));
 {const m=insp().querySelector('details.inspector-method');assert(m&&!m.open,'methodology is collapsed by default');
  assert(m.textContent.includes('Method')&&m.textContent.includes('Overall = mean of the available dimension scores')&&m.textContent.includes('Data & version')&&m.textContent.includes('NYC LION physical ID')&&m.textContent.includes('never counted as 0'),'no methodology text was dropped');
  const row3=insp().querySelectorAll('button.explore-row')[2];assert.equal(row3.dataset.view,'3');row3.click();await tick();await tick();
  assert.equal(run('exploreMap.view'),3);assert.equal(run('exploreMap.selected'),seg.id,'the segment stays selected');assert(insp().textContent.includes(seg.id));
  insp().querySelector('#inspectorNext').click();await tick();assert.equal(run('exploreMap.view'),4);
  insp().querySelector('#inspectorPrev').click();insp().querySelector('#inspectorPrev').click();await tick();await tick();assert.equal(run('exploreMap.view'),2);
  run('exploreStep(-2)');assert.equal(run('exploreMap.view'),0,'stepping wraps through Overall');run('exploreStep(-1)');assert.equal(run('exploreMap.view'),12);
  // a single dimension: compact indicator rows; each indicator's method, notes and source sit in its own closed details
  run('selectExploreView(2)');await tick();await tick();
  const inds=[...insp().querySelectorAll('.indicator')];assert(inds.length>=2);
  for(const el of inds){const more=el.querySelector('details.indicator-more');assert(more&&!more.open);assert(more.textContent.includes('Source:'),'source kept');assert(el.querySelector('[data-k=raw]')&&!more.contains(el.querySelector('[data-k=raw]')),'values stay outside the collapsed part');}
  assert(insp().querySelector('.indicator.computed .indicator-bar b'),'a computed, scored indicator shows its normalized bar');
  assert(!insp().querySelector('.indicator.unavailable .indicator-bar'),'no bar is drawn for a value that is N/A');
  const m2=insp().querySelector('details.inspector-method');assert(m2.textContent.includes('Score method')&&m2.textContent.includes('Data & version'));
  m2.open=true;m2.dispatchEvent(new w.Event('toggle'));run('selectExploreView(3)');await tick();await tick();assert(insp().querySelector('details.inspector-method').open,'an opened Methodology stays open while exploring');
  insp().querySelector('details.inspector-method').open=false;insp().querySelector('details.inspector-method').dispatchEvent(new w.Event('toggle'));
  // Esc closes the inspector (existing behaviour, still works with the new header)
  w.document.body.dispatchEvent(new w.KeyboardEvent('keydown',{key:'Escape',bubbles:true}));assert.equal(run('exploreMap.selected'),null);assert(insp().classList.contains('hidden'));
  run('selectExploreView(0)');run(`selectExploreSegment(${JSON.stringify(seg.id)})`);await tick();await tick();}
 // Side panels (desktop): Explore hides both, leaving restores what the visitor had; the tabs work in either mode.
 {const cl=w.document.body.classList,L=w.document.querySelector('#toggleLeftPanel'),R=w.document.querySelector('#toggleRightPanel');
  assert(run('exploreMap.active')&&cl.contains('left-collapsed')&&cl.contains('right-collapsed'),'Explore gives the width to the map');
  assert.equal(L.getAttribute('aria-expanded'),'false');assert.equal(L.getAttribute('aria-label'),'Show planning panel');
  L.click();assert(!cl.contains('left-collapsed')&&cl.contains('right-collapsed'),'a panel can be brought back while exploring');assert.equal(L.getAttribute('aria-expanded'),'true');L.click();
  run('setExploreMode(false)');assert(!cl.contains('left-collapsed')&&!cl.contains('right-collapsed'),'leaving Explore restores both panels');
  R.click();assert(cl.contains('right-collapsed'));assert.equal(R.getAttribute('aria-label'),'Show walk panel');
  run('setExploreMode(true)');assert(cl.contains('left-collapsed')&&cl.contains('right-collapsed'));
  run('setExploreMode(false)');assert(!cl.contains('left-collapsed')&&cl.contains('right-collapsed'),'restores exactly the earlier choice, not a default');
  R.click();assert(!cl.contains('right-collapsed'));
  run('setExploreMode(true)');await tick();}
 // Every view binds the intended score property and updates the inspector.
 for(let i=0;i<13;i++){
  run(`selectExploreView(${i})`);await tick();
  const view=run('exploreView()');
  assert.equal(view.prop,i===0?'overall':`d${i-1}`);
  assert.equal(w.document.querySelector('#exploreTitle').textContent,i===0?view.label:`${pad(i)} ${view.label}`);
  assert(insp().textContent.includes(seg.id));
 }
 w.document.querySelector('#exploreChips [data-view="2"]').click();await tick();await tick();assert.equal(w.document.querySelector('#exploreTitle').textContent,'02 Nature');
 assert(insp().textContent.includes('Recorded trees'));assert(insp().textContent.includes('NYC Parks Forestry Tree Points'));assert.equal(insp().querySelectorAll('.explore-row').length,0);assert(!insp().textContent.includes('Walkability'));
 assert(insp().querySelector('.indicator.unavailable[data-key="canopy_pct"]'));assert.equal(insp().querySelector('[data-key="canopy_pct"] [data-k=raw]').textContent,'N/A');
 assert.equal(insp().querySelector('[data-k=dimension-score]').textContent,String(Math.round(seg.d1)));
 w.document.querySelector('#exploreChips [data-view="4"]').click();await tick();await tick();
 assert.equal(insp().querySelector('[data-key="width_ft"] [data-k=raw]').textContent,'N/A');assert.equal(seg.n3,1);
 assert.equal(insp().querySelector('[data-k=dimension-score]').textContent,String(Math.round(seg.d3)));
 w.document.querySelector('#exploreChips [data-view="11"]').click();await tick();await tick();
 assert(/Community District \d+/.test(insp().querySelector('[data-key="no2_area_context"]').textContent));assert(insp().querySelector('[data-key="no2_area_context"]').textContent.includes('ppb'));
 run("selectExploreSegment(null)");assert(insp().classList.contains('hidden'));
 assert(run('exploreMap.data.features.length>10000&&exploreMap.data.features.every(f=>f.geometry.type==="LineString"&&ExperienceCore.keys.every((k,i)=>f.properties["d"+i]===null||(f.properties["d"+i]>=0&&f.properties["d"+i]<=100)))'));
 w.document.querySelector('#modeNavigate').click();assert.equal(run('mapExperience.mode'),'navigate');assert(w.document.querySelector('#explorePanel').classList.contains('hidden'));assert(!w.document.querySelector('#layerRoutes').disabled,'routes toggle controls alternatives only; the selected route is always drawn');
 w.STREETWISE_PILOT=JSON.parse(fs.readFileSync(path.join(root,'data/pilot.json')));
 await run('analyzeArea(true)');assert.equal(run('mapExperience.sections.length'),477);
 w.document.querySelector('#experienceDimension').value='Architecture';w.document.querySelector('#experienceDimension').dispatchEvent(new w.Event('change'));
 assert(w.document.querySelector('#legendTitle').textContent.includes('Architecture'));
 w.document.querySelector('#experienceView').value='score';w.document.querySelector('#experienceView').dispatchEvent(new w.Event('change'));assert(w.document.querySelector('#legendSubtitle').textContent.includes('all score fields NULL'));
 // Walking constraints: default 100, slider 10–150 extending to the custom value, quick chips, validation on commit only.
 const tr=()=>w.document.querySelector('#timeRange'),ct=()=>w.document.querySelector('#customTime'),tv=()=>w.document.querySelector('#timeValue').textContent,tm=()=>w.document.querySelector('#timeRangeMax').textContent;
 assert.equal(run('state.budget'),100);assert.equal(tr().min,'10');assert.equal(tr().max,'150');assert.equal(tr().value,'100');assert.equal(tv(),'100 MIN');assert.equal(tm(),'150 MIN');assert.equal(ct().value,'100');
 assert.equal(w.document.querySelector('[data-walk-min="100"]').getAttribute('aria-pressed'),'true');assert.equal(run('state.maxKm'),null,'no hidden distance limit by default');
 const commit=v=>{ct().focus();ct().value=v;ct().dispatchEvent(new w.KeyboardEvent('keydown',{key:'Enter'}));ct().blur();};
 for(const [v,max] of [['45','150'],['60','150'],['72','150'],['120','150'],['180','180']]){commit(v);assert.equal(run('state.budget'),Number(v));assert.equal(tv(),`${v} MIN`);assert.equal(tr().max,max);assert.equal(tm(),`${max} MIN`);assert.equal(tr().value,v);assert.equal(ct().value,v);}
 for(const bad of ['5','','-3','12.5','9']){commit(bad);assert.equal(run('state.budget'),180,`"${bad}" must not change the limit`);assert.equal(ct().value,'180');}
 ct().focus();ct().value='';assert.equal(run('state.budget'),180,'an empty box while typing is allowed and does not touch state');ct().value='72';ct().blur();assert.equal(run('state.budget'),72);
 tr().value='50';tr().dispatchEvent(new w.Event('input'));assert.equal(run('state.budget'),50);assert.equal(ct().value,'50');assert.equal(tr().max,'150');assert.equal(tm(),'150 MIN');
 for(const m of ['60','120','150']){w.document.querySelector(`[data-walk-min="${m}"]`).click();assert.equal(run('state.budget'),+m);assert.equal(w.document.querySelector(`[data-walk-min="${m}"]`).getAttribute('aria-pressed'),'true');}
 tr().value='50';tr().dispatchEvent(new w.Event('input'));
 // Distance limit: chips, custom, unit switch (km ↔ mi), and 'Not set' clears it.
 w.document.querySelector('[data-walk-km="5"]').click();assert.equal(run('state.maxKm'),5);assert.equal(w.document.querySelector('#distValue').textContent,'5 KM');
 w.document.querySelector('[data-dist-unit="mi"]').click();assert.equal(w.document.querySelector('#distValue').textContent,'3.1 MI');assert.equal(run('state.maxKm'),5);
 const cd=w.document.querySelector('#customDist');cd.value='2';cd.dispatchEvent(new w.Event('change'));assert.equal(run('state.maxKm'),3.22);
 w.document.querySelector('[data-dist-unit="km"]').click();w.document.querySelector('[data-walk-km="none"]').click();assert.equal(run('state.maxKm'),null);
 assert(run("applyInterpretation({weights:{},time_minutes:5},'local')").some(c=>c.includes('ignored')));assert.equal(run('state.budget'),50);
 run("applyInterpretation({weights:{},time_minutes:95},'local')");assert.equal(run('state.budget'),95);assert.equal(tr().max,'150');
 // AI Journey → routing engine: a recorded real /api/routes response (tests/fixtures, produced by routing/engine.py).
 const fixture=JSON.parse(fs.readFileSync(path.join(root,'tests/fixtures/route-response.json')));
 // Response-like stub: JSON bodies with headers, and the real static catalog/tiles read from disk.
 const resp=(obj,status=200,type='application/json')=>({ok:status<400,status,headers:{get:k=>k.toLowerCase()==='content-type'?type:null},json:async()=>typeof obj==='string'?JSON.parse(obj):JSON.parse(JSON.stringify(obj)),text:async()=>typeof obj==='string'?obj:JSON.stringify(obj)});
 let menuFixtureConfirmed=true;
 const menuFixturePlace=JSON.parse(fs.readFileSync(path.join(root,'data/places/cafes.json'))).records.find(r=>r.id.startsWith('osm:'));
 const calls=[];w.fetch=async(url,opts={})=>{url=String(url);calls.push({url,body:opts.body&&JSON.parse(opts.body)});
  if(url.endsWith('/api/routes'))return resp(fixture);
  if(url.endsWith('/api/recommend/food'))return resp({status:menuFixtureConfirmed?'ok':'no_confirmed_match',candidates:[{classification:menuFixtureConfirmed?'meets_request':'not_confirmed',place:{place_id:menuFixturePlace.cid,index_id:menuFixturePlace.id,name:menuFixturePlace.name,category:'cafes',coordinates:{lat:menuFixturePlace.lat,lon:menuFixturePlace.lon},address:menuFixturePlace.addr,data_sources:['Test-only recorded place']},menu:{status:menuFixtureConfirmed?'confirmed_menu_match':'unverified',checked_at:new Date().toISOString(),source_url:'https://fixture.invalid/menu'},explanation:{interpretation:'Test-only verified-menu response',verified_facts:[]}}]});
  if(url.endsWith('/api/itinerary'))return resp(JSON.parse(fs.readFileSync(path.join(root,'tests/fixtures/itinerary-response.json'))));
  if(url.endsWith('/api/menu/verify'))return resp({status:'unverified',item:'cappuccino',reason:'No readable menu page was found on the official website.',checked_at:'2026-10-23T00:00:00Z'});
  if(url.startsWith('./data/layers/')||url.startsWith('./data/places/')){const f=path.join(root,url.slice(2));return fs.existsSync(f)?resp(fs.readFileSync(f,'utf8')):resp('<!DOCTYPE html><title>404</title>',404,'text/html');}
  if(url.endsWith('/api/navigation/progress'))return resp({state:'off_route',distance_from_route_m:82,remaining_m:700,remaining_min:9,reroute_recommended:true});
  throw new Error('Network intentionally blocked in DOM test')};
 // No preset ends any more (start = GPS or the request, destination optional): this fixture walk sets its own.
 run("state.start='bryant';state.end='columbia';$('searchStart').value='Bryant Park';$('searchEnd').value='Columbia University'");
 run("planner.weights.Nature=90;planner.origins.Nature='manual';planner.directions.Nature='high';setBudget(72);planner.maxDetourPct=25");
 await run('generateRoutes()');
 const req=calls.find(c=>c.url.endsWith('/api/routes')).body;
 assert.deepEqual(req.preferences.weights,{Nature:90});assert.equal(req.constraints.max_minutes,72);assert(w.document.querySelector('#routeCards').textContent.includes('max 72 min walking'));assert.equal(req.constraints.max_detour_pct,25);assert.equal(req.origin.lat,40.7536);
 assert.equal(run('state.routes.length'),fixture.routes.length);
 // Weather offline: the request carries weather:null, routing still works, and nothing claims weather was used.
 assert.equal(req.weather,null);assert.equal(run('weatherContext.status'),'error');
 assert(w.document.querySelector('#topWeather').textContent.includes('unavailable'));
 assert(w.document.querySelector('#wxRoute').textContent.includes('without usable weather data'));
 const best=fixture.routes.find(r=>r.recommended);assert.equal(run('state.activeRoute'),best.route_id);
 assert.equal(w.document.querySelectorAll('#routeCards .route-card').length,fixture.routes.length);
 assert(w.document.querySelector('#routeCards').textContent.includes(best.route_name));
 // Route Intelligence shows the engine's 12 scores, not browser-computed ones.
 const rows=[...w.document.querySelectorAll('#profileChart .experience-row')];assert.equal(rows.length,12);
 run('DIMENSIONS').forEach((d,i)=>assert.equal(rows[i].querySelector('strong').textContent,best.dimension_scores[d.name]==null?'N/A':String(best.dimension_scores[d.name])));
 assert(w.document.querySelector('#whyRoute').textContent.includes(String(best.personalized_score.utility)));
 // "What these scores measure": the router's own indicator definitions (static file), shown only for the user's
 // priorities and only when the file's score_version equals the route's. Numbers come from the route response.
 assert(!w.document.querySelector('#whyRoute .why-measures'),'no indicator text before the definitions file has loaded (network is blocked here)');
 const basis=JSON.parse(fs.readFileSync(path.join(root,'data/pedestrian/score-indicators.json')));assert.equal(basis.score_version,best.score_version);
 w.BASIS=basis;run('scoreBasis.doc=BASIS;scoreBasis.failed=false;updateWhyRoute()');
 const why=w.document.querySelector('#whyRoute .why-measures');assert(why,'indicator block rendered');
 assert.equal(why.querySelectorAll('.why-dim').length,1,'only the expressed priority (Nature) is explained');
 for(const i of basis.dimensions.Nature.filter(x=>x.role==='up'||x.role==='down'))assert(why.textContent.includes(i.label)&&why.textContent.includes(basis.source_labels[i.source]),`names ${i.key} and its source`);
 assert(!why.textContent.includes(basis.dimensions.Nature.find(x=>x.role==='context').label),'context-only indicators are not presented as part of the score');
 assert(why.textContent.includes(`this route ${best.dimension_scores.Nature}`));
 const fxShortest=fixture.routes.find(r=>r.objective==='shortest');
 if(fxShortest&&fxShortest!==best)assert(why.textContent.includes(`shortest route ${fxShortest.dimension_scores.Nature}`)&&why.textContent.includes(`${best.detour_percentage}% longer`),'compares with the real shortest candidate');
 assert(why.textContent.includes('not observations of how this walk feels')&&why.textContent.includes(basis.score_version));
 // Street photos (street-photos.js): only well-formed Mapillary records from our own API host are shown, each with how
 // far into the walk it is, the month it was taken, its author and a link; nothing when the host has no token.
 {const good={thumb:'https://example.invalid/a.jpg',page:'https://www.mapillary.com/app/?pKey=11',captured_on:'2024-06-10',at_m:420,distance_m:8.2,username:'walker',image_id:'11',looks_along_walk:true};
  const clean=d=>run('streetPhotoClean')(d);
  assert.equal(clean({configured:false,photos:[good]}).length,0,'no token on the host: nothing');assert.equal(clean(null).length,0);assert.equal(clean({configured:true}).length,0);
  assert.equal(clean({configured:true,radius_m:25,photos:[good,{...good,thumb:'http://insecure/a.jpg'},{...good,thumb:'javascript:alert(1)'},{...good,page:'https://evil.invalid/x'},{...good,captured_on:'last year'},{...good,distance_m:60},{...good,at_m:'far'},null]}).length,1,'malformed, insecure, undated or too-distant records are dropped');
  const calls0=[];const keepFetch=w.fetch;
  w.fetch=async(url,opt)=>{url=String(url);if(!url.endsWith('/api/street-photos'))return keepFetch(url,opt);calls0.push(JSON.parse(opt.body));return {ok:true,json:async()=>({configured:true,radius_m:25,attribution:'Images from Mapillary, CC BY-SA',photos:[good,{...good,image_id:'12',page:'https://www.mapillary.com/app/?pKey=12',at_m:1310,captured_on:'2019-03-02',username:null}]})};};
  run('streetPhotos.cache.clear();renderAlongWalk()');await new Promise(r=>setTimeout(r,20));
  assert.equal(calls0.length,1,'asked once for the selected route');assert.deepEqual(calls0[0].coordinates,best.geometry.coordinates,'sends only the route line');
  run('renderAlongWalk();renderAlongWalk()');await new Promise(r=>setTimeout(r,10));assert.equal(calls0.length,1,'not asked again');
  const sp=w.document.querySelector('#alongWalk .street-photos');assert(sp,'street photos shown under Along this walk');
  const figs=[...sp.querySelectorAll('figure')];assert.equal(figs.length,2);
  assert(figs[0].textContent.includes('0.42 km · Jun 2024')&&figs[0].textContent.includes('© walker · Mapillary'));
  assert(figs[1].textContent.includes('1.3 km · Mar 2019')&&figs[1].textContent.includes('Mapillary'));
  assert.equal(figs[0].querySelector('a').getAttribute('href'),'https://www.mapillary.com/app/?pKey=11');assert.equal(figs[0].querySelector('img').getAttribute('referrerpolicy'),'no-referrer');
  assert(sp.textContent.includes('within 25 m')&&sp.textContent.includes('Images from Mapillary, CC BY-SA')&&sp.textContent.includes('may not match today'));
  // an older API host (no such endpoint) or a failure: nothing shown, nothing thrown
  w.fetch=async(url,opt)=>String(url).endsWith('/api/street-photos')?({ok:false,status:404,json:async()=>({})}):keepFetch(url,opt);
  run('streetPhotos.cache.clear();renderAlongWalk()');await new Promise(r=>setTimeout(r,20));assert(!w.document.querySelector('#alongWalk .street-photos'));
  w.fetch=keepFetch;}
 // A hidden walk panel comes back when new walks arrive (they are shown there), but not while exploring.
 {const cl=w.document.body.classList,keep=run('JSON.stringify([exploreMap.active,sidePanels.left,sidePanels.right,state.activeRoute])');
  run("exploreMap.active=false;setSidePanel('right',true);applyRouteResponse(planner.routeResponse)");assert(!cl.contains('right-collapsed'),'new walks reveal the walk panel');
  run("exploreMap.active=true;setSidePanel('right',true);applyRouteResponse(planner.routeResponse)");assert(cl.contains('right-collapsed'),'Explore keeps the map wide');
  w.KEEP=keep;run("{const [a,l,r,id]=JSON.parse(KEEP);exploreMap.active=a;sidePanels.left=l;sidePanels.right=r;applySidePanels();state.activeRoute=id;}");}
 // The numbers behind the card's "why" sentence, on the selected card (not only inside Technical details):
 // priority score, the shortest route's score, and the indicators it is measured by.
 run('renderRouteCards()');
 const basisEls=[...w.document.querySelectorAll('.route-card .rc-basis')];assert.equal(basisEls.length,1,'only the selected card carries the numbers');
 const basisEl=basisEls[0];assert.equal(basisEl.closest('.route-card').dataset.route,best.route_id);
 assert(basisEl.textContent.includes(`${best.dimension_scores.Nature}`)&&basisEl.textContent.includes('Measured by:'));
 assert(basisEl.textContent.includes(basis.dimensions.Nature.find(x=>x.role==='up').label));
 if(fxShortest&&fxShortest!==best)assert(basisEl.textContent.includes(`shortest route ${fxShortest.dimension_scores.Nature}`));
 assert(basisEl.querySelectorAll('.rc-basis-row').length<=2,'two priorities at most on a card');
 w.BASIS_OLD={...basis,score_version:'sw-score-other'};run('scoreBasis.doc=BASIS_OLD;updateWhyRoute()');
 assert(!w.document.querySelector('#whyRoute .why-measures'),'definitions from a different score build are never shown');
 run('renderRouteCards()');assert(!w.document.querySelector('.rc-basis'),'nor on the cards');
 run('scoreBasis.doc=BASIS;updateWhyRoute()');
 // Sleeping API host (api-config.js): planning waits for /api/status, says so once, and a timeout reads as words.
 {const keepFetch=w.fetch;let n=0,notes=[];
  w.fetch=async(url)=>{if(!String(url).endsWith('/api/status'))throw new Error('unexpected '+url);n++;if(n<3)throw new Error('asleep');return {ok:true,json:async()=>({})};};
  w.NOTE=t=>notes.push(t);
  assert.equal(await w.eval('streetwiseAwake(NOTE,5000,5)'),true);assert.equal(n,0,'same-origin page: no extra request, the server that sent the page is the API');
  run('streetwiseHost.remote=true;streetwiseHost.awakeAt=0');
  assert.equal(await w.eval('streetwiseAwake(NOTE,5000,5)'),true);assert.equal(n,3,'kept asking until the host answered');
  assert.equal(notes.length,1,'the visitor is told once');assert(/Waking the route server/.test(notes[0]));assert.equal(run('streetwiseHost.waking'),false);
  await w.eval('streetwiseAwake(NOTE,5000,5)');assert.equal(n,3,'a host that just answered is not asked again');
  run('streetwiseHost.awakeAt=0');w.fetch=async()=>{throw new Error('asleep');};
  let gaveUp=null;try{await w.eval('streetwiseAwake(null,40,5)');}catch(e){gaveUp=e.message;}
  assert(/not answering right now/.test(gaveUp||''),'gives up in plain words after the wait limit');
  assert(/took too long to answer/.test(run("streetwiseErrorText(Object.assign(new Error('signal timed out'),{name:'TimeoutError'}))")));
  assert.equal(run("streetwiseErrorText(new Error('Start is outside walking-route coverage'))"),'Start is outside walking-route coverage','other errors pass through unchanged');
  run('streetwiseHost.remote=false;streetwiseHost.awakeAt=0');w.fetch=keepFetch;}
 // Walk priorities: one row of the 12 EXISTING dimensions. A pill only sets its dimension to the chips' weight (80)
 // or back to not-expressed; no new dimension, names and count untouched; the request box shows the choice in words.
 run('renderWalkPresets()');
 const presetRoots=[...w.document.querySelectorAll('[data-walk-presets]')];assert.equal(presetRoots.length,2,'desktop panel + phone request card');
 // looked up by dataset, not by an attribute selector: jsdom 27 (the version CI installs) returns null for a quoted
 // attribute value containing "&", which real browsers accept
 const pillFor=dim=>[...presetRoots[0].querySelectorAll('.walk-pill[data-dim]')].find(b=>b.dataset.dim===dim);
 const dimNames=run('DIMENSIONS.map(d=>d.name).join("|")').split('|');assert.equal(dimNames.length,12);
 for(const r of presetRoots){const pills=[...r.querySelectorAll('.walk-pill[data-dim]')].map(b=>b.dataset.dim);assert.equal(pills.length,12);assert.deepEqual([...pills].sort(),[...dimNames].sort(),'exactly the 12 registered dimensions, none invented or renamed');}
 assert.equal(run('WALK_PRESET_ORDER.slice(0,4).join("|")'),'Nature|Quiet & Relax|Architecture|Transit Connectivity','three featured for the lead audience, then benchmark order');
 const naturePill=pillFor('Nature');
 assert(naturePill.title.includes(basis.dimensions.Nature.find(x=>x.role==='up').label),'tooltip names the indicators from the router definitions file');
 const box=w.document.querySelector('#intentText');box.value=box.defaultValue;
 const savedPrefs=run('JSON.stringify([planner.weights,planner.origins,planner.directions])');
 run("for(const d of DIMENSIONS){planner.weights[d.name]=50;planner.origins[d.name]='default';planner.directions[d.name]='high';}renderWalkPresets()");
 pillFor('Nature').click();
 assert.equal(run("planner.weights['Nature']"),80);assert.equal(run("planner.origins['Nature']"),'manual');assert.equal(run("planner.directions['Nature']"),'high');
 assert.equal(box.value,'Prioritise: Nature.','the sample sentence is replaced by the choice in words');assert(run('isWalkPresetRequest(document.querySelector("#intentText").value)'));
 pillFor('Quiet & Relax').click();
 assert.equal(run("planner.weights['Quiet & Relax']"),80);assert.equal(run("planner.weights['Nature']"),80,'priorities combine');
 assert.equal(box.value,'Prioritise: Nature, Quiet & Relax.');
 for(const r of presetRoots)assert.deepEqual([...r.querySelectorAll('.walk-pill[data-dim][aria-pressed=true]')].map(b=>b.dataset.dim),['Nature','Quiet & Relax'],'both rows mirror planner state');
 box.value='Take me past bookshops';pillFor('Culture').click();
 assert.equal(box.value,'Take me past bookshops','words the visitor typed are never overwritten');assert(!run('isWalkPresetRequest(document.querySelector("#intentText").value)'),'typed text still goes through interpretation');
 assert.equal(run("planner.weights['Culture']"),80);
 for(const d of ['Nature','Quiet & Relax','Culture'])pillFor(d).click();
 assert.equal(run("['Nature','Quiet & Relax','Culture'].every(d=>planner.weights[d]===50&&planner.origins[d]==='default')"),true,'tapping again returns a dimension to not-expressed');
 // Walk activities: three one-tap starting points for the lead audience. Each is only a bundle of existing dimensions
 // at the pills' weight; it adds no dimension and no route of its own, and a later pill change dissolves it.
 {const acts=()=>[...presetRoots[0].querySelectorAll('.walk-activity')],act=k=>acts().find(b=>b.dataset.activity===k);
  assert.deepEqual(acts().map(b=>b.dataset.activity),['neighbourhood','nicer-way','with-a-point']);
  assert(run('WALK_ACTIVITIES.every(a=>a.dims.every(d=>DIMENSIONS.some(x=>x.name===d)))'),'activities use registered dimensions only');
  assert(presetRoots[0].firstElementChild.classList.contains('walk-activity'),'activities lead the row');
  run("for(const d of DIMENSIONS){planner.weights[d.name]=50;planner.origins[d.name]='default';}walkPresets.activity=null;renderWalkPresets()");box.value='';
  run("planner.weights['Culture']=65;planner.origins['Culture']='manual'");   // a slider the visitor moved themselves
  pillFor('Walkability').click();                                             // a pill chosen before the activity
  const endMode=run('journey.endMode');run("journey.endMode='round'");           // returning to the start: the activity says so
  act('neighbourhood').click();
  assert.equal(run('walkActivity().key'),'neighbourhood');
  assert.equal(run("['Nature','Quiet & Relax','Architecture'].every(d=>planner.weights[d]===80&&planner.origins[d]==='manual')"),true);
  assert.equal(run("planner.weights['Walkability']"),50,'pills chosen before the activity are released');
  assert.equal(run("planner.weights['Culture']"),65,'a weight the visitor set by slider is left alone');
  assert.equal(box.value,'Get to know a neighbourhood: a loop from here, favouring Nature, Quiet & Relax, Architecture.');
  assert(run('isWalkPresetRequest(document.querySelector("#intentText").value)'),'planned without an AI call');
  assert(/around|\bloop\b/.test(box.value)&&run('ROUND_TRIP_RE.test(document.querySelector("#intentText").value)'),'"a loop" is what the existing recommender reads as coming back to the start');
  assert.equal(act('neighbourhood').getAttribute('aria-pressed'),'true');
  run("journey.endMode='open'");run('syncWalkPresetRequest()');assert.equal(box.value,'Get to know a neighbourhood: favouring Nature, Quiet & Relax, Architecture.','an open-ended walk the visitor chose is not called a loop');
  run(`journey.endMode=${JSON.stringify(endMode)}`);
  if(run('walkHasDestination()')){run('syncWalkPresetRequest()');assert.equal(box.value,'Get to know a neighbourhood: favouring Nature, Quiet & Relax, Architecture.','with a destination chosen it is a walk there, not a loop');}
  act('nicer-way').click();
  assert.equal(run('walkActivity().key'),'nicer-way');assert.equal(run("planner.weights['Architecture']"),50,'switching activity releases the previous one');
  assert.equal(run("['Quiet & Relax','Nature','Spatial Comfort'].every(d=>planner.weights[d]===80)"),true);
  assert.equal(box.value,'Take the nicer way: favouring Quiet & Relax, Nature, Comfort.');
  pillFor('Culture').click();                                                 // 65 → pill toggles it on at 80
  assert.equal(run('walkActivity()'),null,'changing a pill turns the activity back into plain priorities');
  assert(box.value.startsWith('Prioritise: '));assert.equal(acts().filter(b=>b.getAttribute('aria-pressed')==='true').length,0);
  act('with-a-point').click();assert.equal(box.value,'A walk with a point: favouring Culture, Food & Retail.');
  act('with-a-point').click();assert.equal(run('walkActivity()'),null);assert.equal(run("planner.weights['Culture']"),50,'tapping the active activity again clears it');
  assert.equal(run('chooseWalkActivity("moonwalk")'),false);assert.equal(run('DIMENSIONS.length'),12);
  run("for(const d of DIMENSIONS){planner.weights[d.name]=50;planner.origins[d.name]='default';planner.directions[d.name]='high';}walkPresets.activity=null;renderWalkPresets()");box.value=box.defaultValue;}
 assert.equal(run('walkPresetRequest()'),'');assert.equal(run('DIMENSIONS.length'),12);assert.equal(run('toggleWalkPreset("Hidden gems")'),false);
 box.value=box.defaultValue;w.SAVED=savedPrefs;run('{const [a,b,c]=JSON.parse(SAVED);Object.assign(planner.weights,a);Object.assign(planner.origins,b);Object.assign(planner.directions,c);renderWalkPresets();}');
 // Ordered edges: listed in order, geometry continuous, distance = sum of traversed edge lengths.
 assert.equal(w.document.querySelectorAll('#routeEdgeList .edge-row').length,best.ordered_edge_ids.length);
 assert.deepEqual(best.edges.map(e=>e.edge_id),best.ordered_edge_ids);
 for(let i=1;i<best.edges.length;i++){const a=best.edges[i-1].geometry.coordinates.at(-1),b=best.edges[i].geometry.coordinates[0];assert(Math.hypot(a[0]-b[0],a[1]-b[1])<1e-6,`edge ${i} disconnected`)}
 assert(Math.abs(best.edges.reduce((s,e)=>s+e.traversed_length_m,0)-best.distance_m)<1);
 // Route-edge click (AI Journey) is a different inspector from the Explore segment inspector.
 const matched=best.edges.find(e=>e.matched_segment_ids.length);run(`selectRouteEdge(${best.edges.indexOf(matched)})`);
 await run(`showRouteEdgeInspector(state.routes.find(r=>r.id===state.activeRoute).raw.edges[${best.edges.indexOf(matched)}])`);
 const uinsp=()=>w.document.querySelector('#urbanInspector');assert(!uinsp().classList.contains('hidden'));
 let ev=uinsp().textContent;assert(ev.includes('STREET SEGMENT EVIDENCE')&&ev.includes(matched.edge_id)&&ev.includes(matched.matched_segment_ids[0])&&ev.includes(matched.street_name));
 // Evidence counts equal a brute-force scan of every tile (not only the tiles the page picked).
 const G=run('UrbanGeo'),catalog=JSON.parse(fs.readFileSync(path.join(root,'data/layers/catalog.json')));
 const allTiles=ts=>Object.keys(catalog.tilesets[ts].tiles).flatMap(k=>JSON.parse(fs.readFileSync(path.join(root,'data/layers/tiles',ts,k+'.json'))).features);
 const nTrees=G.alongLine(allTiles('street_trees'),matched.geometry.coordinates,30).length;
 const treeRow=[...uinsp().querySelectorAll('.evidence-row')].find(r=>r.textContent.startsWith('Street trees'));assert(treeRow.textContent.includes(`${nTrees} within 30 m`),treeRow.textContent);
 assert(ev.includes('Raw feature count')&&ev.includes('Spatial density')&&ev.includes('Nearest distance')&&ev.includes('Area coverage')&&ev.includes('context only'));
 assert(uinsp().querySelector('.evidence-scoring').textContent.includes('Full-structure inventory trees per km'),'existing scoring indicators are labelled separately');
 await run(`showRouteEdgeInspector(state.routes.find(r=>r.id===state.activeRoute).raw.edges[${best.edges.indexOf(best.edges.find(e=>!e.matched_segment_ids.length))}])`);
 assert(uinsp().textContent.includes('Unmatched'));assert(!/MN-\d/.test(uinsp().querySelector('dl').textContent),'an unmatched edge must not show a LION ID');
 // Urban Data Layers: dataset catalog (not dimensions), statuses, search.
 const panel=w.document.querySelector('#urbanLayers');assert(!panel.open,'panel starts collapsed');panel.open=true;await run('openUrbanPanel()');
 assert.equal(w.document.querySelectorAll('#urbanCats .urban-cat').length,10);
 const catText=w.document.querySelector('#urbanCats').textContent;assert(catText.includes('Streets & Pedestrian Infrastructure')&&catText.includes('Not connected · available')&&catText.includes('Not connected · no dataset'));const heads=[...w.document.querySelectorAll('#urbanCats .urban-cat > summary span')].map(x=>x.textContent);assert(!heads.some(h=>run('DIMENSIONS').some(d=>h===d.name)),'categories are datasets, not experience dimensions');
 assert(w.document.querySelector('[data-ud-toggle="air_quality"]')===null,'unconnected datasets cannot be switched on');
 // Static + indexed transports share category controls; defaults honour the declared visibility/density policy.
 const allDatasets=[...catalog.datasets,...(catalog.remote_datasets||[])],connected=allDatasets.filter(d=>d.status==='CONNECTED').length;
 const defaults=allDatasets.filter(d=>d.status==='CONNECTED'&&d.default_visible!==false).length;
 assert.equal(run('urbanData.active.size'),defaults,'every declared default dataset is on');assert.equal(w.document.querySelector('#urbanActiveTitle').textContent,`ACTIVE DATASETS: ${defaults} of ${connected}`);
 assert(w.document.querySelector('[data-ud-toggle="reported_complaints"]'),'indexed crime source is available independently of the 12 scores');
 w.document.querySelector('#urbanAllOff').click();assert.equal(run('urbanData.active.size'),0);
 w.document.querySelector('#urbanAllOn').click();assert.equal(run('urbanData.active.size'),connected);
 w.document.querySelector('#urbanAllOff').click();
 w.document.querySelector('#urbanSearch').value='tree';w.document.querySelector('#urbanSearch').dispatchEvent(new w.Event('input'));
 assert(w.document.querySelector('[data-ud-toggle="street_trees"]')&&!w.document.querySelector('[data-ud-toggle="restaurants"]'));
 w.document.querySelector('#urbanSearch').value='';w.document.querySelector('#urbanSearch').dispatchEvent(new w.Event('input'));
 // Along the selected route (default 100 m): counts equal the brute-force reference; layers survive a route switch.
 const ref=JSON.parse(fs.readFileSync(path.join(root,'tests/fixtures/urban-along-route.json')));
 run(`selectRoute(${JSON.stringify(best.route_id)})`);
 for(const id of ['street_trees','landmarks','historic_districts']){run(`toggleUrbanDataset('${id}',true)`);}
 await new Promise(r=>setTimeout(r,300));
 const status=id=>w.document.querySelector(`[data-ud-status="${id}"]`).textContent;
 assert.equal(status('street_trees'),`Loaded · ${Object.keys(ref.datasets.street_trees).length} within 100 m`);assert.equal(status('landmarks'),`Loaded · ${Object.keys(ref.datasets.landmarks).length} within 100 m`);
 assert.equal(w.document.querySelector('#urbanActiveTitle').textContent,`ACTIVE DATASETS: 3 of ${connected}`);
 const natureCat=w.document.querySelector('[data-ud-cat="nature"]');assert(natureCat.indeterminate&&natureCat.dataset.state==='some','category with some datasets on is indeterminate');
 // Dynamic legend: only symbols that are on the map; one building theme at a time.
 run('renderUrbanLegend()');
 const legend=()=>w.document.querySelector('#udLegend .lg-body').textContent;assert(legend().includes('Street trees')&&!legend().includes('Places & facilities'),JSON.stringify({legend:legend(),zoom:run('state.map?.getZoom()'),drawn:run('[...urbanData.drawn].map(([k,v])=>[k,v.size])')}));
 // Thematic selectors: four building themes (one fill at a time); environment themes without data are listed but disabled.
 assert.deepEqual([...w.document.querySelectorAll('#buildingTheme option')].map(o=>o.value),['neutral','height','age','landuse']);
 const env=[...w.document.querySelectorAll('#envTheme option')];assert(env.find(o=>o.value==='noise')&&!env.find(o=>o.value==='noise').disabled);assert(env.filter(o=>o.disabled).length>=3&&env.filter(o=>o.disabled).every(o=>o.textContent.includes('not connected')));
 run(`selectRoute(${JSON.stringify(ref.alt_route_id)})`);await new Promise(r=>setTimeout(r,300));
 assert.equal(run('urbanData.active.size'),3,'layers kept after switching routes');assert.equal(status('landmarks'),`Loaded · ${Object.keys(ref.alt.landmarks).length} within 100 m`);
 run(`selectRoute(${JSON.stringify(best.route_id)})`);await new Promise(r=>setTimeout(r,300));
 // Route Urban Data summary = the same spatial query as the map.
 await run('renderRouteUrbanData()');
 const item=k=>[...w.document.querySelectorAll('#routeUrbanData .route-urban-item')].find(b=>b.textContent.startsWith(k)).querySelector('strong').textContent;
 assert.equal(item('Trees'),String(Object.keys(ref.datasets.street_trees).length));
 assert.equal(item('Restaurants & cafés'),String(Object.keys(ref.datasets.restaurants).length+Object.keys(ref.datasets.cafes).length));
 assert.equal(item('Transit stops'),String(Object.keys(ref.datasets.subway_entrances).length+Object.keys(ref.datasets.bus_stops).length));
 assert(item('Pedestrian crashes').startsWith(`${Object.keys(ref.datasets.pedestrian_crashes).length} · Crashes`));
 run("urbanData.byId.get('bus_stops').status='MISSING'");await run('renderRouteUrbanData()');assert.equal(item('Transit stops'),'Data Unavailable');run("urbanData.byId.get('bus_stops').status='CONNECTED'");
 // Urban Feature Inspector: real fields, Not Available for missing ones, historical note for crashes, source link.
 const crash=allTiles('pedestrian_crashes').find(f=>f.properties.feature_id in ref.datasets.pedestrian_crashes&&!f.properties.off_street_name);
 const fh=run(`urbanFeatureHtml(urbanData.byId.get('pedestrian_crashes'),${JSON.stringify({...crash.properties,distance_to_route_m:12})})`);
 assert(fh.includes(crash.properties.feature_id)&&fh.includes(crash.properties.crash_date)&&fh.includes('Not Available')&&fh.includes('Historical record')&&fh.includes('h9gi-nx95')&&fh.includes('12 m from the route'));assert(!fh.includes('undefined'));
 w.document.querySelector('#urbanAllOff').click();assert.equal(run('urbanData.active.size'),0);assert.equal(w.document.querySelector('#urbanActiveTitle').textContent,`ACTIVE DATASETS: 0 of ${connected}`);
 assert(!calls.some(c=>c.url.includes('/api/layers')),'urban data comes from static files, never the old /api/layers');
 // A missing static file is reported plainly, not as a JSON parse error.
 await assert.rejects(run("streetwiseJson('./data/layers/tiles/nope/0_0.json')"),/HTML page/);
 // Display corridor never changes route scores.
 const scoresBefore=JSON.stringify(run('state.routes.map(r=>r.raw.dimension_scores)'));run("urbanData.corridor=500;refreshUrbanLayers()");assert.equal(JSON.stringify(run('state.routes.map(r=>r.raw.dimension_scores)')),scoresBefore);run('urbanData.corridor=100');
 assert(w.document.querySelector('#exploreInspector').classList.contains('hidden'));
 run(`selectRoute(${JSON.stringify(fixture.routes[1].route_id)})`);assert.equal(run('state.activeRoute'),fixture.routes[1].route_id);
 assert.equal(w.document.querySelectorAll('#routeEdgeList .edge-row').length,fixture.routes[1].ordered_edge_ids.length);
 run("planner.profileView='compare';updateProfile()");assert.equal(w.document.querySelectorAll('#profileChart .route-compare tbody tr').length,15);run("planner.profileView='selected';updateProfile()");
 // No feasible candidate: nothing is recommended, the reason is stated, and the shortest computed route is still
 // shown as an over-limit preview with a one-click "Allow N min" (the map never looks empty after a computation).
 const blocked=JSON.parse(JSON.stringify(fixture));blocked.routes.forEach(r=>{r.recommended=false;r.constraints.feasible=false;r.constraints.violations=['13 min exceeds the 10-minute limit']});
 run(`applyRouteResponse(${JSON.stringify(blocked)})`);assert(run('planner.lastExplanation').includes('10-minute limit'));
 const shortestBlocked=blocked.routes.reduce((a,r)=>r.estimated_duration_min<a.estimated_duration_min?r:a);
 assert.equal(run('state.activeRoute'),shortestBlocked.route_id);assert(!run('state.routes.some(r=>r.raw.recommended)'));
 run('renderRouteSummary()');assert.equal(w.document.querySelector('#allowTime').textContent,`Allow ${Math.ceil(shortestBlocked.estimated_duration_min)} min`);
 assert.equal(run('minutesToFit()'),Math.ceil(shortestBlocked.estimated_duration_min));
 run(`applyRouteResponse(${JSON.stringify(fixture)})`);
 // Step-free cannot be verified: the engine is not even asked.
 const before=calls.length;run('planner.constraints.stepFree=true');await run('generateRoutes()');assert.equal(calls.length,before);assert.equal(run('state.routes.length'),0);run('planner.constraints.stepFree=false');
 run(`applyRouteResponse(${JSON.stringify(fixture)})`);
 // GPS progress uses the engine's navigation endpoint; off-route with GPS as start queues a re-plan.
 run("state.start='gps';globalThis.replans=0;generateRoutes=async()=>{globalThis.replans++};setGpsPosition({latitude:40.756,longitude:-73.981,accuracy:12})");
 // the re-plan is debounced (650 ms) after the progress reply; wait for it instead of a fixed 800 ms (flaky under load)
 for(let t=0;t<30&&w.replans<1;t++)await new Promise(r=>setTimeout(r,100));assert(w.document.querySelector('#gpsMeta').textContent.includes('Off route by 82 m'));assert.equal(w.replans,1);
 assert.equal(calls.filter(c=>c.url.endsWith('/api/navigation/progress')).at(-1).body.route_id,best.route_id);
 run("state.start='bryant'");
 // GPS permission denied and timeout branches, secure localhost context.
 Object.defineProperty(w.navigator,'geolocation',{value:{getCurrentPosition:(good,bad)=>bad({code:1,message:'denied'})},configurable:true});run('requestGPS()');assert.equal(w.document.querySelector('#gpsMain').textContent,'DENIED');
 Object.defineProperty(w.navigator,'geolocation',{value:{getCurrentPosition:(good,bad)=>bad({code:3,message:'timeout'})},configurable:true});run('requestGPS()');assert.equal(w.document.querySelector('#gpsMain').textContent,'TIMED OUT');
 // Slider change must request fresh geometry, rather than merely recoloring.
 run("planner.constraints.stepFree=false;planner.adjust=true;renderDimensions();globalThis.replans=0;");const slider=w.document.querySelector('[data-weight="Nature"]');slider.value='80';slider.dispatchEvent(new w.Event('input'));slider.dispatchEvent(new w.Event('change'));await new Promise(r=>setTimeout(r,750));assert.equal(w.replans,1);
 // Weather intents in the local preview parser; "weather" no longer reads as "eat" (Food & Retail).
 assert.equal(run("localWeatherIntent('It\\'s really hot today. Find me a cooler walking route.')"),'cooler');
 assert.equal(run("localWeatherIntent('Is my current route comfortable in this weather?')"),'ask');
 assert.equal(run("localWeatherIntent('I want a greener walk, but consider today\\'s weather.')"),'consider');
 assert.equal(run("localWeatherIntent('Keep my destination, but find a more shaded route.')"),'cooler');
 assert.equal(run("localWeatherIntent('Make it quieter')"),null);
 assert.deepEqual(Object.keys(run("localInterpret('consider today\\'s weather on this street')").weights),[]);
 assert.equal(run("JSON.stringify(localJourney('I\\'d like a greener, quieter walk with interesting architecture.').interests)"),'[]','a preference is not a visit request');
 assert.equal(run("JSON.stringify(localJourney('I want to explore historic architecture').interests)"),'["historic"]');
 // A real engine response for a hot afternoon (tests/fixtures/route-response-hot.json): the UI reports exactly the engine record.
 const hot=JSON.parse(fs.readFileSync(path.join(root,'tests/fixtures/route-response-hot.json')));const eff=hot.weather_routing.routing.effect;
 w.HOT=hot;run('applyRouteResponse(HOT);renderRouteCards();updateWhyRoute()');
 const wxText=w.document.querySelector('#wxRoute').textContent;assert.equal(w.document.querySelector('#wxRouteStatus').textContent,'ROUTING ACTIVE');
 assert(eff.changed&&wxText.includes('Weather changed the recommendation')&&wxText.includes('Street-tree / park cover proxy')&&wxText.includes(`${Math.round(eff.exposure_reduction*100)} points less heat-exposed`));
 assert(w.document.querySelector('#routeCards').textContent.includes('heat-exposed (tree proxy)'));
 assert(run('weatherRouteSentence(HOT)').includes('not measured shade'));
 const fixtureMild=JSON.parse(JSON.stringify(hot));fixtureMild.weather_routing.routing={status:'not_active',active:false,reason:'Below the heat-caution band.'};w.MILD=fixtureMild;run('applyRouteResponse(MILD);updateWhyRoute()');
 assert(w.document.querySelector('#wxRoute').textContent.includes('weather-based route optimization is not active for this route'));
 // AI Discover My Walk: multi-turn journey state (Scenario H), real POI index, planner request, rendering of a real /api/itinerary response.
 await run('warmNameIndex()');
 const hotel=JSON.parse(fs.readFileSync(path.join(root,'data/places/hotels.json'))).records.find(r=>r.name==='Hilton New York Midtown');w.HOTEL=hotel;run('setMyHotel(poiPlace(HOTEL));setJourneyPlace("start",journey.hotel)');
 const turn=async q=>run(`applyJourney(localJourney(${JSON.stringify(q)}))`),jr=x=>JSON.parse(run(`JSON.stringify(${x})`));
 run('state.end=null;state.customEnd=null');  // a first-time visitor with no destination
 await turn('我想逛纽约著名景点。');assert.deepEqual(jr('journey.interests'),['famous']);assert.equal(run('journey.endMode'),'open','no destination needed');
 await turn('再加一个博物馆。');assert.deepEqual(jr('journey.extra'),{museums:1});
 await turn('顺路喝一杯卡布奇诺。');assert.equal(run('journey.food[0].item'),'cappuccino');
 await turn('还要经过洛克菲勒中心。');assert.equal(run('journey.named[0].place.name'),'Rockefeller Center');assert(run('journey.named[0].place.id').startsWith('osm:'),'named place resolved from real data');
 await turn('最后回我的酒店。');assert.equal(run('journey.endMode'),'hotel');
 await turn('最多走 5 公里。');assert.equal(run('state.maxKm'),5);
 await turn('时间可以延长到 150 分钟。');assert.equal(run('state.outingMin'),150);
 // everything settled earlier is still there
 assert.deepEqual(jr('journey.interests'),['famous','museums']);assert.equal(run('journey.food.length'),1);assert.equal(run('journey.named.length'),1);assert.equal(run('journey.endMode'),'hotel');assert.equal(run('getPlace("start").name'),'Hilton New York Midtown');assert.equal(run('state.maxKm'),5);
 menuFixtureConfirmed=false;
 await assert.rejects(run('itineraryRequest()'),/Cannot verify the required/);
 menuFixtureConfirmed=true;
 const jreq=await run('itineraryRequest()');
 assert.equal(jreq.end.mode,'hotel');assert.equal(jreq.end.place.name,'Hilton New York Midtown');assert.equal(jreq.constraints.max_km,5);assert.equal(jreq.constraints.max_outing_minutes,150);
 assert(jreq.stops.some(s=>s.name==='Rockefeller Center'&&s.required));
 const cs=jreq.slots.find(x=>x.slot_id==='food:cafes:cappuccino');assert(cs&&cs.candidates.length>0);for(const c of cs.candidates)assert(c.id.startsWith('osm:')&&Number.isFinite(c.lat));
 const priorExtra=jr('journey.extra');run('journey.counts={famous:2};journey.extra={}');
 const counted=await run('itineraryRequest()');assert.equal(counted.slots.filter(s=>s.slot_id.startsWith('interest:famous:')).length,2);assert.equal(counted.pool.max_stops,0,'an explicit count must not acquire automatic extra visits');
 run(`journey.counts={};journey.extra=${JSON.stringify(priorExtra)}`);
 await run("applyJourney({...localJourney(''),named_stops:[{name:'Unresolved required fixture 999',required:true,order:null}]})");
 await assert.rejects(run('itineraryRequest()'),/Required places could not be resolved/);
 await run("applyJourney({...localJourney(''),remove:['Unresolved required fixture 999']})");
 assert.equal(run('journey.unresolved.length'),0);
 assert(jreq.slots.some(x=>x.slot_id==='interest:famous'));assert(jreq.slots.some(x=>x.slot_id==='interest:museums'));
 assert(!jreq.slots.flatMap(x=>x.candidates).some(c=>c.name==='Hilton New York Midtown'),'the hotel itself is never discovered as a stop');
 calls.length=0;await run('planJourney()');
 assert(calls.some(c=>c.url.endsWith('/api/itinerary')),'planning goes to the engine');
 const itfx=JSON.parse(fs.readFileSync(path.join(root,'tests/fixtures/itinerary-response.json'))).itinerary;
 const cw=w.document.querySelector('#cityWalk').textContent;assert(cw.includes('YOUR CITY WALK'));for(const s of itfx.stops)assert(cw.includes(s.name),`stop ${s.name} shown`);
 assert(cw.includes(`${(itfx.totals.walk_m/1000).toFixed(2)} km`));assert(cw.includes('(est.)'),'visit times are labelled as estimates');
 assert.equal(run('state.routes.length'),1);assert.equal(run('state.activeRoute'),JSON.parse(fs.readFileSync(path.join(root,'tests/fixtures/itinerary-response.json'))).routes[0].route_id);
 await new Promise(r=>setTimeout(r,50));assert.equal(run("journey.menu[Object.keys(journey.menu)[0]]?.status"),'confirmed_menu_match');assert.equal(run("journey.menu[Object.keys(journey.menu)[0]]?.source_url"),'https://fixture.invalid/menu','verification comes only from the explicit test provider response');
 // "find" services do not add stops; hotel ambiguity asks instead of guessing
 const fr=await run("findServices('pharmacies','near_hotel')");assert(fr.places.length>0&&fr.places.every(p=>p.category&&p.source));assert.equal(run('journey.named.length'),1);
 await turn("I'm staying at a Marriott near Times Square");assert(w.document.querySelectorAll('.chat-choices [data-choice]').length>1,'several Marriotts: the user chooses');assert.equal(run('journey.hotel.name'),'Hilton New York Midtown','not changed until chosen');
 // A shared food venue must expose both evidence records; one missing result cannot pass.
 const originalFoodPlan=run('journey.plan'),originalFoodMenu=run('journey.menu');
 run("journey.plan={...journey.plan,stops:[{...journey.plan.stops[0],id:'fixture-shared-menu',required_items:['bagel','cappuccino']}]};journey.menu={'fixture-shared-menu|bagel':{status:'confirmed_menu_match',menu_source_url:'https://fixture.invalid/menu'}};renderCityWalk()");
 assert.equal(run("foodEvidenceStatus({objective:'itinerary'})"),'warning');
 assert(w.document.querySelector('#cityWalk').textContent.includes('cappuccino: not checked'));
 run("journey.menu['fixture-shared-menu|cappuccino']={status:'confirmed_menu_match',menu_source_url:'https://fixture.invalid/menu'};for(const m of Object.values(journey.menu))m.checked_at=new Date().toISOString();renderCityWalk()");
 assert.equal(run("foodEvidenceStatus({objective:'itinerary'})"),'pass');
 assert.equal(w.document.querySelectorAll('#cityWalk .cw-menu').length,2);
 w.ORIGINAL_FOOD_PLAN=originalFoodPlan;w.ORIGINAL_FOOD_MENU=originalFoodMenu;
 run('journey.plan=ORIGINAL_FOOD_PLAN;journey.menu=ORIGINAL_FOOD_MENU;renderCityWalk()');
 // Start Navigation is gated by the route check and needs engine maneuvers.
 const navRoute=JSON.parse(fs.readFileSync(path.join(root,'tests/fixtures/nav-route.json')));
 w.NAVR=navRoute;run("applyRouteResponse({routes:[{...NAVR,route_name:'Test',objective:'itinerary',recommended:true,constraints:{feasible:true,violations:[]},personalized_score:{utility:50},estimated_duration_min:14,dimension_scores:{},data_coverage:{by_dimension:{},mean:1,low_coverage_dimensions:[]}}],constraints_used:{},feasible_count:1});renderNavStart()");
 const ns=w.document.querySelector('#navStart');assert(!ns.classList.contains('hidden')&&!ns.disabled,'validated route with maneuvers can start');
 assert(w.document.querySelector('#routeValidation').textContent.includes('Route check'));
 run("state.routes[0].raw.validation={...state.routes[0].raw.validation,navigation_allowed:false,status:'fail',blocking_issues:['gap between edges']};renderNavStart()");assert(ns.disabled&&ns.title.includes('gap between edges'),'failed route check blocks navigation');
 run("delete state.routes[0].raw.maneuvers;state.routes[0].raw.validation.navigation_allowed=true;renderNavStart()");assert(ns.disabled,'no maneuvers, no navigation');
 // Reroute must preserve the City Walk: match a reached stop by stable id (two stops can share a name) and deduct
 // what was already walked/visited from the original budget instead of resetting it.
 {
  Object.defineProperty(w.navigator,'geolocation',{value:{watchPosition:()=>1,clearWatch:()=>{},getCurrentPosition:()=>{}},configurable:true});
  const rr=JSON.parse(JSON.stringify(navRoute));rr.objective='itinerary';
  const stopM=rr.maneuvers.find(m=>m.type==='arrive_stop');
  stopM.stop_id='place:cafe-A';
  // a second, not-yet-reached stop shares the exact same name as the reached one
  const secondStopM={...stopM,maneuver_id:'rt-extra-stop',stop_id:'place:cafe-B',distance_along_route_m:stopM.distance_along_route_m+50};
  rr.maneuvers.push(secondStopM);rr.maneuvers.sort((a,b)=>a.distance_along_route_m-b.distance_along_route_m);
  w.NAVR2=rr;
  run("journey.plan={stops:[{id:'place:cafe-A',name:'Café',role:'stop',lat:40.758,lon:-73.978},{id:'place:cafe-B',name:'Café',role:'stop',lat:40.759,lon:-73.977},{id:'end',name:'End',role:'end',lat:40.76,lon:-73.98}]};"+
      "journey.request={origin:{id:'o',name:'Origin',lat:40.753,lon:-73.983},end:{mode:'fixed',place:null},constraints:{max_minutes:30,max_km:2,max_outing_minutes:40},preferences:{weights:{}},theme:'t'};");
  run("nav.engine=new NavEngine(NAVR2);nav.route=NAVR2;nav.last={lat:40.7536,lon:-73.9798};nav.lastReroute=0;nav.totalWalkedM=0;nav.totalVisitMin=0;"+
      "nav.engine.state='OFF_ROUTE';nav.engine.progress=800;nav.engine.arrivedStops.add(NAVR2.maneuvers.find(m=>m.stop_id==='place:cafe-A').maneuver_id);");
  const before=calls.length;await run('reroute(true)');
  const body=calls.slice(before).find(c=>c.url.endsWith('/api/itinerary'))?.body;
  assert(body,'reroute posted a new itinerary request');
  assert.deepEqual(body.stops.map(s=>s.id),['place:cafe-B'],'the reached stop is dropped by id, not by its (shared) name; the end stays in req.end, not req.stops');
  assert(body.constraints.max_minutes<30&&body.constraints.max_minutes>0,`budget must shrink by what was already walked, got ${body.constraints.max_minutes}`);
  assert.equal(Math.round(body.constraints.max_minutes*10),Math.round((30-800/80)*10),'deduction matches progress at the 80 m/min walking pace');
  // Budget already exhausted: reroute must say so and must NOT ask the server for a fresh, implicitly-reset budget.
  run("nav.engine.state='OFF_ROUTE';nav.totalWalkedM=30*80;nav.engine.progress=0;nav.lastReroute=0;");
  const before2=calls.length;await run('reroute(true)');
  assert.equal(calls.length,before2,'exhausted budget must not call the itinerary endpoint');
  assert(w.document.querySelector('#navStatus').textContent.includes('used up'),'the walker is told the budget ran out, not given a silently reset one');
 }
 // Independent criteria stay separate, and a legacy response cannot silently ignore them.
 run("applyInterpretation({weights:{},crime:{mode:'set',direction:'high',weight:90},waterfront:{mode:'set',direction:'high',weight:90}},'local')");
 assert.equal(run('buildRouteRequest({lat:40.75,lon:-73.99},{lat:40.76,lon:-73.98}).preferences.crime.direction'),'high');
 run("applyInterpretation({weights:{},waterfront:{mode:'set',direction:'low',weight:90}},'local')");
 assert.equal(run('planner.waterfront.direction'),'low','a follow-up replaces the prior direction');
 w.OLD_ROUTE_RESPONSE=fixture;
 assert.throws(()=>run("validateIndependentResponse({crime:{direction:'high'}},OLD_ROUTE_RESPONSE)"),/did not apply/);
 run("applyInterpretation({weights:{},crime:{mode:'clear'},waterfront:{mode:'clear'}},'local')");
 assert.equal(run('planner.crime'),null);assert.equal(run('planner.waterfront'),null);
 // Mock AI transport only; never claim this as a real OpenAI call.
 const initialFetch=w.fetch;
 run('planner.llmConnected=false;planner.llmConfigured=null');
 w.fetch=async(url)=>String(url).endsWith('/api/interpret')?({ok:true,json:async()=>({weights:{'Scenic & Visual':90,Architecture:85,Nature:85},constraints:{},journey:{food:[{category:'cafes',item:'coffee',required:true}],interests:['parks']}})}):initialFetch(url);
 const ai=await run("interpretIntent('I want a scenic walk with architecture, parks, and good coffee.')");
 assert.equal(run('planner.interpretation'),'llm');
 assert(w.document.querySelector('#interpretMode').textContent.includes('AI VERIFIED'),'A failed status probe must not permanently force local preview');
 assert.equal(run("planner.weights['Scenic & Visual']"),90);
 assert.equal(ai.journey.food[0].item,'coffee');
 // A request no dataset measures (the critique's "as much dog poop as possible"): the AI names it in `unsupported`;
 // the app says so in plain words, changes no preference and sends no planning request. A reply without the field
 // (older server) behaves exactly as before (covered by the call above).
 {const before=run('JSON.stringify([planner.weights,planner.origins])'),seen=[];
  w.fetch=async(url)=>{url=String(url);seen.push(url);return url.endsWith('/api/interpret')?({ok:true,json:async()=>({weights:{},directions:{},constraints:{},journey:null,clarification:null,unsupported:[{request:'as much dog poop as possible',reason:'No dataset in STROLLANE measures dog waste',nearest_dimension:null}]})}):initialFetch(url);};
  const r1=await run("interpretIntent('a walk with as much dog poop as possible')");
  assert.equal(r1.unsupported.length,1);assert.equal(r1.changes.length,0);assert.equal(run('JSON.stringify([planner.weights,planner.origins])'),before,'no preference is invented for it');
  const said=run('unsupportedText')(r1.unsupported);assert.equal(said,'I can’t plan for “as much dog poop as possible”: No dataset in STROLLANE measures dog waste.');
  seen.length=0;const chatN=run('planner.conversations.length');
  await run("handlePlan('a walk with as much dog poop as possible',true)");
  assert(!seen.some(u=>u.endsWith('/api/routes')||u.endsWith('/api/itinerary')),'nothing is planned for a request that cannot be measured');
  const last=run('planner.conversations.at(-1).content');assert(run('planner.conversations.length')>chatN&&last.startsWith('I can’t plan for “as much dog poop as possible”')&&last.includes('Nothing was changed'));
  // the nearest dimension is offered only when it is a registered one; an invented name is ignored
  assert(run('unsupportedText')([{request:'nice smells',reason:'No dataset measures smells.',nearest_dimension:'Nature'}]).includes('The closest thing I can plan for is Nature'));
  assert(!run('unsupportedText')([{request:'nice smells',reason:'No dataset measures smells.',nearest_dimension:'Aroma'}]).includes('closest'));
  // malformed entries from a server are dropped, not shown
  w.fetch=async(url)=>String(url).endsWith('/api/interpret')?({ok:true,json:async()=>({weights:{},constraints:{},journey:null,unsupported:[{request:'',reason:'x'},{reason:'y'},null,'z']})}):initialFetch(url);
  assert.equal((await run("interpretIntent('anything')")).unsupported.length,0);}
 run('planner.llmConnected=true');
 w.fetch=async(url)=>String(url).endsWith('/api/interpret')?({ok:false,status:502,json:async()=>({reason:{stage:'upstream_http',code:'invalid_api_key',detail:'internal diagnostic keys: weights directions'}})}):initialFetch(url);
 await run("interpretIntent('greener walk')");
 assert.equal(run('planner.interpretation'),'local');
 assert(w.document.querySelector('#toast').textContent.includes('invalid_api_key'));
 assert(!w.document.querySelector('#toast').textContent.includes('internal diagnostic'));
 run('planner.llmConnected=false');w.fetch=initialFetch;

 // Drain route-summary and menu continuations before destroying their document.
 await run('renderRouteUrbanData()');
 await new Promise(resolve=>setImmediate(resolve));
 // --- live-site fixes (2026-11-15) ---
 // Short trips: say so with the response's own numbers; silent when a priority really gains or no priority is set.
 {w.__mk=(bestN,shortN,dist=480,same=false)=>({shortest_distance_m:dist,routes:[{rank:1,route_id:same?'s':'b',objective:same?'shortest':'experience',dimension_scores:{Nature:bestN}},...(same?[]:[{rank:2,route_id:'s',objective:'shortest',dimension_scores:{Nature:shortN}}])]});
  const reset="for(const d of DIMENSIONS){planner.weights[d.name]=50;planner.origins[d.name]='default';planner.directions[d.name]='high';}";
  const saved=run('JSON.stringify([planner.weights,planner.origins,planner.directions])');
  run(reset);assert.equal(run('shortTripNote(__mk(40,39))'),'','no priority chosen: nothing to say');
  run("planner.weights['Nature']=80;planner.origins['Nature']='manual'");
  assert.equal(run('shortTripNote(__mk(41,39))'),' This is a short trip (480 m): the best match differs from the shortest route by 2 points at most on your priorities, so there is little to gain by going another way.');
  assert.equal(run('shortTripNote(__mk(51,41))'),'','a real gain is not talked down');
  assert.equal(run('shortTripNote(__mk(41,39,2400))'),'','longer trips are not called short');
  assert.match(run('shortTripNote(__mk(40,40,480,true))'),/the shortest route is also the best match for your priorities, so there is no better way to offer\.$/);
  assert.equal(run('shortTripNote(__mk(null,39))'),'','N/A is not a zero-point gain');
  run("planner.directions['Nature']='low'");assert.equal(run('shortTripNote(__mk(30,41))'),'','with "prefer less", a lower score is the gain');
  w.__sv=JSON.parse(saved);run('Object.assign(planner.weights,__sv[0]);Object.assign(planner.origins,__sv[1]);Object.assign(planner.directions,__sv[2])');}
 // Page and route server on different versions: one plain sentence, none when they agree.
 assert.equal(run("versionMismatchText('v2','v2')"),'');assert.equal(run("versionMismatchText(null,'v2')"),'','the page copy did not load: no claim');
 assert.match(run("versionMismatchText('v2','v1')"),/page v2, server v1\)/);assert.match(run("versionMismatchText('v2',undefined)"),/server older, version not reported\)/);
 {w.__kb=run('scoreBasis.doc');
  await run("(async()=>{scoreBasis.doc={score_version:'page-build'};await checkServerVersion({score_version:'old-build'});})()");
  const box=w.document.querySelector('#versionNotice');assert(box&&/page page-build, server old-build/.test(box.textContent));
  await run("checkServerVersion({score_version:'page-build'})");assert.equal(w.document.querySelector('#versionNotice'),null,'cleared once they agree');
  run('scoreBasis.doc=__kb');}
 // Places near the walk: no "0 NEAR ROUTE" before the lookup has answered, and no "generate a route" while one is on screen.
 {w.__kp=run('[planner.poiStatus,planner.routePois]');const hadRoutes=run('state.routes.length');
  run("planner.routePois=[];planner.poiStatus='Not loaded';renderPOIs()");
  assert.equal(w.document.querySelector('#poiCount').textContent,'');
  assert.equal(w.document.querySelector('#poiList').textContent,hadRoutes?'Places near this walk have not been looked up yet.':'Generate or select a route to discover POIs.');
  run("planner.poiStatus='0 OSM records';renderPOIs()");assert.equal(w.document.querySelector('#poiCount').textContent,'0 NEAR ROUTE','a real answer of none is still reported');
  run('planner.poiStatus=__kp[0];planner.routePois=__kp[1];renderPOIs()');}
 assert(/loadRoutePOIs\(run\)/.test(fs.readFileSync(path.join(__dirname,'..','journey.js'),'utf8')),'recommended walks look up nearby places too');
 // --- Share this walk (share-link.js): the link carries the request only; it is validated like any outside input ---
 {const saved=run('JSON.stringify([planner.weights,planner.origins,planner.directions,state.budget,journey.endMode])'),keepS=run('[state.start,state.customStart,state.end,state.customEnd]');w.__ks=keepS;
  run("for(const d of DIMENSIONS){planner.weights[d.name]=50;planner.origins[d.name]='default';planner.directions[d.name]='high';}");
  run("setEndMode('fixed');setJourneyPlace('start',{id:'t:a',name:'Bryant Park',lat:40.753612,lon:-73.983233});setJourneyPlace('end',{id:'t:b',name:'Rockefeller & Co <b>',lat:40.7587,lon:-73.9787});");
  run("planner.weights['Nature']=80;planner.origins['Nature']='manual';planner.weights['Urban Vibrancy']=90;planner.origins['Urban Vibrancy']='manual';planner.directions['Urban Vibrancy']='low';setBudget(45)");
  const url=run("shareLinkEncode(shareLinkState(),'https://example.test/app/')"),hash=url.slice(url.indexOf('#'));
  assert(url.startsWith('https://example.test/app/#walk?'),'the request lives in the fragment, which is not sent to a server');
  assert(/from=40\.7536%2C-73\.9832/.test(url)&&!/753612/.test(url),'coordinates rounded to 4 decimals');
  assert(!/geometry|score|route_id/.test(url),'no route or score travels in the link');
  w.__h=hash;const st=run('shareLinkParse(__h)');
  assert.deepEqual(JSON.parse(JSON.stringify(st)),{from:{lat:40.7536,lon:-73.9832,name:'Bryant Park'},to:{lat:40.7587,lon:-73.9787,name:'Rockefeller & Co b'},end:'fixed',prefs:[{i:run("DIMENSIONS.findIndex(d=>d.name==='Nature')"),w:80,low:false},{i:run("DIMENSIONS.findIndex(d=>d.name==='Urban Vibrancy')"),w:90,low:true}].sort((a,b)=>a.i-b.i),minutes:45});
  // applying it reproduces the request exactly
  run("for(const d of DIMENSIONS){planner.weights[d.name]=50;planner.origins[d.name]='default';planner.directions[d.name]='high';}setBudget(72);state.start=null;state.end=null;");
  run('shareLinkApply(shareLinkParse(__h))');
  assert.equal(run("planner.weights['Nature']+'|'+planner.origins['Nature']+'|'+planner.weights['Urban Vibrancy']+'|'+planner.directions['Urban Vibrancy']+'|'+state.budget"),'80|manual|90|low|45');
  assert.equal(run("getPlace('start').lat+','+getPlace('end').lon+','+getPlace('start').source"),'40.7536,-73.9787,Shared link');
  assert.equal(run("DIMENSIONS.filter(d=>planner.origins[d.name]!=='default').length"),2,'only the shared priorities are set');
  // a loop has no destination; round-trips through the link too
  run("setEndMode('round')");const loop=run("shareLinkEncode(shareLinkState(),'x')");assert(/end=round/.test(loop)&&!/[?&]to=/.test(loop));
  w.__l=loop.slice(loop.indexOf('#'));assert.equal(run('shareLinkParse(__l).end'),'round');assert.equal(run('shareLinkParse(__l).to'),null);
  run("setEndMode('hotel')");assert.equal(run('shareLinkState()'),null,'"back to my hotel" is not shared');run("setEndMode('fixed')");
  // rejected whole, never half-applied: outside Manhattan, unknown dimension, out-of-range weight, repeated dimension, bad minutes, no start
  for(const bad of ['#walk?from=41.9000,-73.9832&to=40.7587,-73.9787','#walk?from=40.7536,-73.9832&to=40.7587,-73.9787&p=12.80','#walk?from=40.7536,-73.9832&to=40.7587,-73.9787&p=1.101','#walk?from=40.7536,-73.9832&to=40.7587,-73.9787&p=1.80,1.60','#walk?from=40.7536,-73.9832&to=40.7587,-73.9787&min=abc','#walk?to=40.7587,-73.9787','#walk?from=40.7536,-73.9832&end=hotel','#walk?from=40.7536,-73.9832','#other','#walk?from=javascript:alert(1)&to=40.7587,-73.9787']){w.__b=bad;assert.equal(run('shareLinkParse(__b)'),null,bad);}
  w.__kc=run('planner.crime');run('planner.crime=null');assert(!run('shareLinkOmits()').includes('the crime-report preference'));run("planner.crime={mode:'set'}");assert(run('shareLinkOmits()').includes('the crime-report preference'),'what the link leaves out is said');run('planner.crime=__kc');
  assert(w.document.querySelector('#shareWalk'),'Share button present');
  w.__sv=JSON.parse(saved);run('Object.assign(planner.weights,__sv[0]);Object.assign(planner.origins,__sv[1]);Object.assign(planner.directions,__sv[2]);setBudget(__sv[3]);setEndMode(__sv[4]);[state.start,state.customStart,state.end,state.customEnd]=__ks;');}
 // --- Chinese interface (i18n.js): display only, reversible, dimension names never replaced ---
 {const d=w.document,q=s=>d.querySelector(s),redraw="renderPreferenceSummary();if(typeof renderDimensions==='function')renderDimensions();renderWalkPresets();";run(redraw);
  const before=d.body.textContent,cta=q('#generateRoutes')?.textContent;
  assert.equal(run('i18n.lang'),'en');assert.equal(q('#langToggle [data-lang-label]').textContent,'中文');
  assert.equal(Object.keys(run('I18N_DIMENSIONS_ZH')).join('|'),run("DIMENSIONS.map(d=>d.name).join('|')"),'a gloss for each of the 12 registered names, no others');
  for(const n of run('DIMENSIONS.map(d=>d.name)'))assert(run('I18N_ZH')[n].endsWith(' '+n),'the unchanged English name stays on screen: '+n);
  const pill=[...d.querySelectorAll('[data-walk-presets] .walk-pill[data-dim]')].find(b=>b.dataset.dim==='Nature'),act=d.querySelector('.walk-activity[data-activity=neighbourhood]');
  const box=q('#intentText'),typed=box.value;
  run("setLanguage('zh',false)");
  assert.equal(d.documentElement.lang,'zh-Hans');assert.equal(q('#langToggle [data-lang-label]').textContent,'EN');
  assert.equal(pill.dataset.dim,'Nature');assert(/自然 Nature/.test(pill.textContent),'gloss + name, data key untouched');
  assert(/认识一个街区/.test(act.textContent));assert(d.body.textContent.includes('起点')&&d.body.textContent.includes('分享这条路线'));
  assert.equal(box.value,typed,'what is typed in the request box is never rewritten');
  assert.equal(box.getAttribute('placeholder'),run('I18N_ZH')[box.getAttribute('data-i18n-en-placeholder')],'placeholder translated, original kept on the element');
  // text the app writes later is translated too; built sentences are left in English, whole
  const probe=d.createElement('p');d.body.appendChild(probe);probe.textContent='More routes';
  const built=d.createElement('p');d.body.appendChild(built);built.textContent='3 walks to choose from: Greener, Quieter.';
  await new Promise(r=>setTimeout(r,0));
  assert.equal(probe.textContent,'更多路线');assert.equal(built.textContent,'3 walks to choose from: Greener, Quieter.');
  // the planner still works on English keys while Chinese is shown
  {const nature=()=>[...d.querySelectorAll('[data-walk-presets] .walk-pill[data-dim]')].find(b=>b.dataset.dim==='Nature'&&b.closest('[data-walk-presets]')===pill.closest('[data-walk-presets]'))||pill,was=run("planner.origins['Nature']")+run("planner.weights['Nature']"),keepN=run("[planner.weights['Nature'],planner.origins['Nature'],planner.directions['Nature']]");
   nature().click();assert.notEqual(run("planner.origins['Nature']")+run("planner.weights['Nature']"),was,'pills work on the English data key while Chinese is shown');assert(/自然 Nature/.test(nature().textContent),'a re-rendered pill is translated again');w.__kn=keepN;run("[planner.weights['Nature'],planner.origins['Nature'],planner.directions['Nature']]=__kn;renderWalkPresets()");}
  run(redraw);await new Promise(r=>setTimeout(r,0));run("setLanguage('en',false)");probe.remove();built.remove();
  assert.equal(d.documentElement.lang,'en');assert.equal(d.body.textContent,before,'switching back restores every string exactly');
  assert.equal(d.querySelectorAll('[data-i18n-en-placeholder],[data-i18n-en-title],[data-i18n-en-aria-label]').length,0);
  assert.equal(q('#generateRoutes')?.textContent,cta);}
 console.log('DOM PASS: navigation gate (route check + maneuvers), AI Discover My Walk (multi-turn state kept, real POI index, itinerary request + rendering, menu status honest, find vs add, hotel confirmation), weather offline → weather:null + honest status, weather intents, engine weather record shown as computed, walking-time default/sync/validation/API, urban data catalog (10 dataset categories, statuses, search), along-route counts = brute-force reference, route switch keeps layers, route urban data summary, feature inspector, segment evidence (matched/unmatched), static JSON errors, mode, 13 Map Mode views on computed GIS data, segment inspector (single + overall, indicator N/A, NO₂ context), 12 names, real pilot, routing-engine request/response adapter, 12 route scores, ordered continuous edges, route-edge inspector, route switching/compare, infeasible + step-free blocking, GPS progress + off-route replan, GPS error states, slider replanning. No browser/WebGL claims.');dom.window.close();
})().catch(e=>{console.error(e);dom.window.close();process.exitCode=1});
