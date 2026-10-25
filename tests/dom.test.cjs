/* DOM/state integration. Test-only fixtures never ship into the runtime app. Run with jsdom installed. */
const {JSDOM}=require(process.env.JSDOM_PATH||'jsdom'),fs=require('fs'),path=require('path'),assert=require('node:assert/strict');
const root=path.join(__dirname,'..'),html=fs.readFileSync(path.join(root,'index.html'),'utf8');
const dom=new JSDOM(html,{runScripts:'outside-only',url:'http://localhost:8080'}),w=dom.window;
w.fetch=async()=>{throw new Error('Network intentionally blocked in DOM test')};w.HTMLElement.prototype.scrollIntoView=function(){};w.AbortSignal.timeout=()=>new w.AbortController().signal;
const vm=require('vm'),context=dom.getInternalVMContext();
for(const file of ['experience-core.js','api-config.js','weather.js','places.js','opening-hours.js','app.js','route-client.js','weather-ui.js','journey.js','journey-ui.js','voice.js','nav-engine.js','nav-ui.js','urban-geo.js','urban-style.js','urban-layers.js','explore-map.js','explore-analytics.js','center-map.js'])vm.runInContext(fs.readFileSync(path.join(root,file),'utf8'),context);
const run=s=>vm.runInContext(s,context);
(async()=>{
 assert.equal(w.document.querySelectorAll('#experienceDimension option').length,12);
 assert.equal(run("localJourney('I want tiramisu at an Italian restaurant with good reviews').food[0].item"),'tiramisu');
 assert.equal(run("localJourney('I want tiramisu at an Italian restaurant with good reviews').food[0].cuisine"),'italian');
 assert.equal(run("localJourney('Find a hotel with two beds and a budget of $250 per night').requirements.hotel_budget_per_night_usd"),250);
 assert.equal(run("localJourney('Visit two landmarks').counts.famous"),2);

 w.STREETWISE_STREETS=JSON.parse(fs.readFileSync(path.join(root,'data/manhattan-streets.json')));
 w.document.querySelector('#modeExplore').click();assert.equal(run('mapExperience.mode'),'explore');
 await run('loadExploreStreets()');assert(!w.document.querySelector('#explorePanel').classList.contains('hidden'));
 assert.equal(w.document.querySelectorAll('#exploreChips [data-view]').length,13);assert.equal(w.document.querySelectorAll('#exploreGrid .explore-dim').length,13);
 assert.equal(w.document.querySelector('#exploreTitle').textContent,'Overall Experience');
 // Click-through: a real segment opens the Inspector; single-dimension view shows only that dimension's sub-indicators.
 const seg=run('exploreMap.data.features.find(f=>f.properties.d4===null&&f.properties.width_ft===null).properties');
 run(`selectExploreSegment(${JSON.stringify(seg.id)})`);const insp=()=>w.document.querySelector('#exploreInspector');
 assert(!insp().classList.contains('hidden'));assert(insp().textContent.includes(seg.id));assert(insp().textContent.includes('Segment Length'));
 assert(insp().textContent.includes('Overall Experience Score'));assert.equal(insp().querySelectorAll('.explore-row').length,12);assert(insp().textContent.includes('Comfort: N/A')||insp().textContent.includes('Comfort'));assert(insp().textContent.includes(`${seg.coverage} of 12 dimensions`));
 // Every view must bind the intended real-data score property and update the inspector.
 for(let i=0;i<13;i++){
  run(`selectExploreView(${i})`);
  const view=run('exploreView()');
  assert.equal(view.prop,i===0?'overall':`d${i-1}`);
  assert.equal(w.document.querySelector('#exploreTitle').textContent,view.label);
  assert(insp().textContent.includes(seg.id));
 }
 w.document.querySelector('#exploreChips [data-view="2"]').click();assert.equal(w.document.querySelector('#exploreTitle').textContent,'Nature');
 assert(insp().textContent.includes('Full-structure inventory trees per km'));assert(insp().textContent.includes('NYC Parks Forestry Tree Points'));assert.equal(insp().querySelectorAll('.explore-row').length,0);assert(!insp().textContent.includes('Walkability'));
 w.document.querySelector('#exploreChips [data-view="5"]').click();assert(insp().textContent.includes('Comfort · Experience Score'));assert(insp().querySelector('.inspector-score strong').textContent==='N/A');assert(insp().textContent.includes('N/A'));
 w.document.querySelector('#exploreChips [data-view="4"]').click();assert(insp().textContent.includes('Roadway width'));assert(/Roadway width\s*N\/A/.test(insp().textContent));
 assert.equal(insp().querySelector('.inspector-score strong').textContent,String(seg.d3));
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
 await new Promise(r=>setTimeout(r,800));assert(w.document.querySelector('#gpsMeta').textContent.includes('Off route by 82 m'));assert.equal(w.replans,1);
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
 console.log('DOM PASS: navigation gate (route check + maneuvers), AI Discover My Walk (multi-turn state kept, real POI index, itinerary request + rendering, menu status honest, find vs add, hotel confirmation), weather offline → weather:null + honest status, weather intents, engine weather record shown as computed, walking-time default/sync/validation/API, urban data catalog (10 dataset categories, statuses, search), along-route counts = brute-force reference, route switch keeps layers, route urban data summary, feature inspector, segment evidence (matched/unmatched), static JSON errors, mode, 13 explore views, segment inspector (single + overall, N/A), 12 names, real pilot, routing-engine request/response adapter, 12 route scores, ordered continuous edges, route-edge inspector, route switching/compare, infeasible + step-free blocking, GPS progress + off-route replan, GPS error states, slider replanning. No browser/WebGL claims.');dom.window.close();
})().catch(e=>{console.error(e);dom.window.close();process.exitCode=1});
