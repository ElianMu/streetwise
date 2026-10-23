/* DOM/state integration. Test-only fixtures never ship into the runtime app. Run with jsdom installed. */
const {JSDOM}=require(process.env.JSDOM_PATH||'jsdom'),fs=require('fs'),path=require('path'),assert=require('node:assert/strict');
const root=path.join(__dirname,'..'),html=fs.readFileSync(path.join(root,'index.html'),'utf8');
const dom=new JSDOM(html,{runScripts:'outside-only',url:'http://localhost:8080'}),w=dom.window;
w.fetch=async()=>{throw new Error('Network intentionally blocked in DOM test')};w.HTMLElement.prototype.scrollIntoView=function(){};w.AbortSignal.timeout=()=>new w.AbortController().signal;
const vm=require('vm'),context=dom.getInternalVMContext();
for(const file of ['experience-core.js','api-config.js','app.js','route-client.js','urban-geo.js','urban-layers.js','explore-map.js','center-map.js'])vm.runInContext(fs.readFileSync(path.join(root,file),'utf8'),context);
const run=s=>vm.runInContext(s,context);
(async()=>{
 assert.equal(w.document.querySelectorAll('#experienceDimension option').length,12);
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
 w.document.querySelector('#exploreChips [data-view="2"]').click();assert.equal(w.document.querySelector('#exploreTitle').textContent,'Nature');
 assert(insp().textContent.includes('Living street trees per km'));assert(insp().textContent.includes('NYC Parks Forestry Tree Points'));assert.equal(insp().querySelectorAll('.explore-row').length,0);assert(!insp().textContent.includes('Walkability'));
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
 // Walking constraints: default 60, slider 10–60 extending to the custom value, validation on commit only.
 const tr=()=>w.document.querySelector('#timeRange'),ct=()=>w.document.querySelector('#customTime'),tv=()=>w.document.querySelector('#timeValue').textContent,tm=()=>w.document.querySelector('#timeRangeMax').textContent;
 assert.equal(run('state.budget'),60);assert.equal(tr().min,'10');assert.equal(tr().max,'60');assert.equal(tr().value,'60');assert.equal(tv(),'60 MIN');assert.equal(tm(),'60 MIN');assert.equal(ct().value,'60');
 const commit=v=>{ct().focus();ct().value=v;ct().dispatchEvent(new w.KeyboardEvent('keydown',{key:'Enter'}));ct().blur();};
 for(const [v,max] of [['45','60'],['60','60'],['72','72'],['120','120']]){commit(v);assert.equal(run('state.budget'),Number(v));assert.equal(tv(),`${v} MIN`);assert.equal(tr().max,max);assert.equal(tm(),`${max} MIN`);assert.equal(tr().value,v);assert.equal(ct().value,v);}
 for(const bad of ['5','','-3','12.5','9']){commit(bad);assert.equal(run('state.budget'),120,`"${bad}" must not change the limit`);assert.equal(ct().value,'120');}
 ct().focus();ct().value='';assert.equal(run('state.budget'),120,'an empty box while typing is allowed and does not touch state');ct().value='72';ct().blur();assert.equal(run('state.budget'),72);
 tr().value='50';tr().dispatchEvent(new w.Event('input'));assert.equal(run('state.budget'),50);assert.equal(ct().value,'50');assert.equal(tr().max,'60');assert.equal(tm(),'60 MIN');
 assert(run("applyInterpretation({weights:{},time_minutes:5},'local')").some(c=>c.includes('ignored')));assert.equal(run('state.budget'),50);
 run("applyInterpretation({weights:{},time_minutes:95},'local')");assert.equal(run('state.budget'),95);assert.equal(tr().max,'95');
 // AI Journey → routing engine: a recorded real /api/routes response (tests/fixtures, produced by routing/engine.py).
 const fixture=JSON.parse(fs.readFileSync(path.join(root,'tests/fixtures/route-response.json')));
 // Response-like stub: JSON bodies with headers, and the real static catalog/tiles read from disk.
 const resp=(obj,status=200,type='application/json')=>({ok:status<400,status,headers:{get:k=>k.toLowerCase()==='content-type'?type:null},json:async()=>typeof obj==='string'?JSON.parse(obj):JSON.parse(JSON.stringify(obj)),text:async()=>typeof obj==='string'?obj:JSON.stringify(obj)});
 const calls=[];w.fetch=async(url,opts={})=>{url=String(url);calls.push({url,body:opts.body&&JSON.parse(opts.body)});
  if(url.endsWith('/api/routes'))return resp(fixture);
  if(url.startsWith('./data/layers/')){const f=path.join(root,url.slice(2));return fs.existsSync(f)?resp(fs.readFileSync(f,'utf8')):resp('<!DOCTYPE html><title>404</title>',404,'text/html');}
  if(url.endsWith('/api/navigation/progress'))return resp({state:'off_route',distance_from_route_m:82,remaining_m:700,remaining_min:9,reroute_recommended:true});
  throw new Error('Network intentionally blocked in DOM test')};
 run("planner.weights.Nature=90;planner.origins.Nature='manual';planner.directions.Nature='high';setBudget(72);planner.maxDetourPct=25");
 await run('generateRoutes()');
 const req=calls.find(c=>c.url.endsWith('/api/routes')).body;
 assert.deepEqual(req.preferences.weights,{Nature:90});assert.equal(req.constraints.max_minutes,72);assert(w.document.querySelector('#routeCards').textContent.includes('max 72 min walking'));assert.equal(req.constraints.max_detour_pct,25);assert.equal(req.origin.lat,40.7536);
 assert.equal(run('state.routes.length'),fixture.routes.length);
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
 assert(uinsp().querySelector('.evidence-scoring').textContent.includes('Living street trees per km'),'existing scoring indicators are labelled separately');
 await run(`showRouteEdgeInspector(state.routes.find(r=>r.id===state.activeRoute).raw.edges[${best.edges.indexOf(best.edges.find(e=>!e.matched_segment_ids.length))}])`);
 assert(uinsp().textContent.includes('Unmatched'));assert(!/MN-\d/.test(uinsp().querySelector('dl').textContent),'an unmatched edge must not show a LION ID');
 // Urban Data Layers: dataset catalog (not dimensions), statuses, search.
 const panel=w.document.querySelector('#urbanLayers');assert(!panel.open,'panel starts collapsed');panel.open=true;await run('openUrbanPanel()');
 assert.equal(w.document.querySelectorAll('#urbanCats .urban-cat').length,10);
 const catText=w.document.querySelector('#urbanCats').textContent;assert(catText.includes('Streets & Pedestrian Infrastructure')&&catText.includes('Available · not connected')&&catText.includes('Missing'));const heads=[...w.document.querySelectorAll('#urbanCats .urban-cat > summary span')].map(x=>x.textContent);assert(!heads.some(h=>run('DIMENSIONS').some(d=>h===d.name)),'categories are datasets, not experience dimensions');
 assert(w.document.querySelector('[data-ud-toggle="air_quality"]')===null,'unconnected datasets cannot be switched on');
 w.document.querySelector('#urbanSearch').value='tree';w.document.querySelector('#urbanSearch').dispatchEvent(new w.Event('input'));
 assert(w.document.querySelector('[data-ud-toggle="street_trees"]')&&!w.document.querySelector('[data-ud-toggle="restaurants"]'));
 w.document.querySelector('#urbanSearch').value='';w.document.querySelector('#urbanSearch').dispatchEvent(new w.Event('input'));
 // Along the selected route (default 100 m): counts equal the brute-force reference; layers survive a route switch.
 const ref=JSON.parse(fs.readFileSync(path.join(root,'tests/fixtures/urban-along-route.json')));
 run(`selectRoute(${JSON.stringify(best.route_id)})`);
 for(const id of ['street_trees','landmarks','historic_districts']){run(`toggleUrbanDataset('${id}',true)`);}
 await new Promise(r=>setTimeout(r,300));
 const status=id=>w.document.querySelector(`[data-ud-status="${id}"]`).textContent;
 assert.equal(status('street_trees'),`${Object.keys(ref.datasets.street_trees).length} within 100 m`);assert.equal(status('landmarks'),`${Object.keys(ref.datasets.landmarks).length} within 100 m`);
 assert.equal(w.document.querySelector('#urbanActiveTitle').textContent,'ACTIVE LAYERS: 3');
 run(`selectRoute(${JSON.stringify(ref.alt_route_id)})`);await new Promise(r=>setTimeout(r,300));
 assert.equal(run('urbanData.active.size'),3,'layers kept after switching routes');assert.equal(status('landmarks'),`${Object.keys(ref.alt.landmarks).length} within 100 m`);
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
 w.document.querySelector('#urbanClear').click();assert.equal(run('urbanData.active.size'),0);assert.equal(w.document.querySelector('#urbanActiveTitle').textContent,'ACTIVE LAYERS: 0');
 assert(!calls.some(c=>c.url.includes('/api/layers')),'urban data comes from static files, never the old /api/layers');
 // A missing static file is reported plainly, not as a JSON parse error.
 await assert.rejects(run("streetwiseJson('./data/layers/tiles/nope/0_0.json')"),/HTML page/);
 // Display corridor never changes route scores.
 const scoresBefore=JSON.stringify(run('state.routes.map(r=>r.raw.dimension_scores)'));run("urbanData.corridor=500;refreshUrbanLayers()");assert.equal(JSON.stringify(run('state.routes.map(r=>r.raw.dimension_scores)')),scoresBefore);run('urbanData.corridor=100');
 assert(w.document.querySelector('#exploreInspector').classList.contains('hidden'));
 run(`selectRoute(${JSON.stringify(fixture.routes[1].route_id)})`);assert.equal(run('state.activeRoute'),fixture.routes[1].route_id);
 assert.equal(w.document.querySelectorAll('#routeEdgeList .edge-row').length,fixture.routes[1].ordered_edge_ids.length);
 run("planner.profileView='compare';updateProfile()");assert.equal(w.document.querySelectorAll('#profileChart .route-compare tbody tr').length,15);run("planner.profileView='selected';updateProfile()");
 // No feasible candidate: nothing is recommended and the reason is stated.
 const blocked=JSON.parse(JSON.stringify(fixture));blocked.routes.forEach(r=>{r.recommended=false;r.constraints.feasible=false;r.constraints.violations=['13 min exceeds the 10-minute limit']});
 run(`applyRouteResponse(${JSON.stringify(blocked)})`);assert.equal(run('state.activeRoute'),null);assert(run('planner.lastExplanation').includes('10-minute limit'));
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
 console.log('DOM PASS: walking-time default/sync/validation/API, urban data catalog (10 dataset categories, statuses, search), along-route counts = brute-force reference, route switch keeps layers, route urban data summary, feature inspector, segment evidence (matched/unmatched), static JSON errors, mode, 13 explore views, segment inspector (single + overall, N/A), 12 names, real pilot, routing-engine request/response adapter, 12 route scores, ordered continuous edges, route-edge inspector, route switching/compare, infeasible + step-free blocking, GPS progress + off-route replan, GPS error states, slider replanning. No browser/WebGL claims.');dom.window.close();
})().catch(e=>{console.error(e);dom.window.close();process.exitCode=1});
