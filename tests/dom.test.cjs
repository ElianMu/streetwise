/* DOM/state integration. Test-only fixtures never ship into the runtime app. Run with jsdom installed. */
const {JSDOM}=require(process.env.JSDOM_PATH||'jsdom'),fs=require('fs'),path=require('path'),assert=require('node:assert/strict');
const root=path.join(__dirname,'..'),html=fs.readFileSync(path.join(root,'index.html'),'utf8');
const dom=new JSDOM(html,{runScripts:'outside-only',url:'http://localhost:8080'}),w=dom.window;
w.fetch=async()=>{throw new Error('Network intentionally blocked in DOM test')};w.HTMLElement.prototype.scrollIntoView=function(){};w.AbortSignal.timeout=()=>new w.AbortController().signal;
const vm=require('vm'),context=dom.getInternalVMContext();
for(const file of ['experience-core.js','app.js','route-client.js','explore-map.js','center-map.js'])vm.runInContext(fs.readFileSync(path.join(root,file),'utf8'),context);
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
 w.document.querySelector('#modeNavigate').click();assert.equal(run('mapExperience.mode'),'navigate');assert(w.document.querySelector('#explorePanel').classList.contains('hidden'));assert(w.document.querySelector('#layerRoutes').disabled);
 w.STREETWISE_PILOT=JSON.parse(fs.readFileSync(path.join(root,'data/pilot.json')));
 await run('analyzeArea(true)');assert.equal(run('mapExperience.sections.length'),477);
 w.document.querySelector('#experienceDimension').value='Architecture';w.document.querySelector('#experienceDimension').dispatchEvent(new w.Event('change'));
 assert(w.document.querySelector('#legendTitle').textContent.includes('Architecture'));
 w.document.querySelector('#experienceView').value='score';w.document.querySelector('#experienceView').dispatchEvent(new w.Event('change'));assert(w.document.querySelector('#legendSubtitle').textContent.includes('all score fields NULL'));
 // AI Journey → routing engine: a recorded real /api/routes response (tests/fixtures, produced by routing/engine.py).
 const fixture=JSON.parse(fs.readFileSync(path.join(root,'tests/fixtures/route-response.json')));
 const calls=[];w.fetch=async(url,opts={})=>{calls.push({url:String(url),body:opts.body&&JSON.parse(opts.body)});
  if(String(url).endsWith('/api/routes'))return {ok:true,json:async()=>JSON.parse(JSON.stringify(fixture))};
  if(String(url).endsWith('/api/navigation/progress'))return {ok:true,json:async()=>({state:'off_route',distance_from_route_m:82,remaining_m:700,remaining_min:9,reroute_recommended:true})};
  throw new Error('Network intentionally blocked in DOM test')};
 run("planner.weights.Nature=90;planner.origins.Nature='manual';planner.directions.Nature='high';state.budget=30;planner.maxDetourPct=25");
 await run('generateRoutes()');
 const req=calls.find(c=>c.url.endsWith('/api/routes')).body;
 assert.deepEqual(req.preferences.weights,{Nature:90});assert.equal(req.constraints.max_minutes,30);assert.equal(req.constraints.max_detour_pct,25);assert.equal(req.origin.lat,40.7536);
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
 const edgeHtml=w.document.querySelector('#segmentDetail').textContent;assert(edgeHtml.includes('Route Edge Inspector'));assert(edgeHtml.includes(matched.edge_id));assert(edgeHtml.includes(matched.matched_segment_ids[0]));
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
 console.log('DOM PASS: mode, 13 explore views, segment inspector (single + overall, N/A), 12 names, real pilot, routing-engine request/response adapter, 12 route scores, ordered continuous edges, route-edge inspector, route switching/compare, infeasible + step-free blocking, GPS progress + off-route replan, GPS error states, slider replanning. No browser/WebGL claims.');dom.window.close();
})().catch(e=>{console.error(e);dom.window.close();process.exitCode=1});
