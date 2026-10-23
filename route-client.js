'use strict';
/* AI Journey + Route Intelligence ↔ STREETWISE pedestrian routing engine (server.py → routing/engine.py).
   Every displayed route is an engine Route Object built from real OSM pedestrian edges; nothing is computed or
   invented in the browser. Contract field names follow API.md.

   @typedef {{segment_id:string, source_segment_id:number|null, street_name:string, length_m:number,
     dimension_scores:Object<string,number|null>, overall_score:number|null, score_version:string}} StreetSegment
   @typedef {{edge_id:string, u:number, v:number, key:number, osm_way_ids:number[], geometry:object, length_m:number,
     traversed_length_m:number, pedestrian_access:object, dimension_scores:Object<string,number|null>,
     data_coverage:Object<string,number>, matched_segment_ids:string[], match_quality:string, score_source:string,
     network_version:string, score_version:string}} PedestrianEdge
   @typedef {{route_id:string, route_name:string, objective:string, geometry:object, ordered_edge_ids:string[],
     edges:PedestrianEdge[], distance_m:number, estimated_duration_min:number, detour_percentage:number,
     dimension_scores:Object<string,number|null>, overall_score:number|null, personalized_score:object,
     data_coverage:object, ranking_explanation:string, constraints:object, rank:number, recommended:boolean,
     navigation:object, network_version:string, score_version:string}} RouteObject */
const ROUTE_DIM_LABELS={'Spatial Comfort':'Comfort','Urban Vibrancy':'Vibrancy','Scenic & Visual':'Scenic','Access & Safety':'Safety','Transit Connectivity':'Transit'};
const dimLabel=d=>ROUTE_DIM_LABELS[d]||d;
const routeNav={pending:false,last:null,selectedEdge:null};

/** Routing API request: user preferences stay separate from the objective street scores. */
function buildRouteRequest(a,b){
 const weights={},directions={};
 for(const d of DIMENSIONS)if(planner.origins[d.name]!=='default'&&planner.weights[d.name]>0){weights[d.name]=planner.weights[d.name];directions[d.name]=planner.directions[d.name]||'high';}
 return {origin:{lat:a.lat,lon:a.lon},destination:{lat:b.lat,lon:b.lon},preferences:{weights,directions},
  constraints:{max_minutes:state.budget,max_detour_pct:planner.maxDetourPct,avoid_detours:planner.constraints.avoidDetours,avoid_stairs:planner.constraints.avoidStairs}};
}
/** Adapter: engine Route Object → the shape the existing map and panels read (id/label/coords/km/min). */
function adaptRoute(r){return {id:r.route_id,label:r.route_name,coords:r.geometry.coordinates,km:r.distance_m/1000,min:r.estimated_duration_min,feasible:r.constraints.feasible,score:r.personalized_score.utility,raw:r};}
function applyRouteResponse(json){
 planner.routeResponse=json;state.routes=json.routes.map(adaptRoute);
 const best=json.routes.find(r=>r.recommended);state.activeRoute=best?.route_id||null;routeNav.selectedEdge=null;
 if(typeof urbanLayersRouteChanged==='function')urbanLayersRouteChanged();
 planner.lastExplanation=best?best.ranking_explanation:`No Feasible Route: none of the ${json.routes.length} candidate routes meets your limits (${[...new Set(json.routes.flatMap(r=>r.constraints.violations))].join('; ')}). Increase the limit or change endpoints. Over-limit routes are shown for comparison only.`;
}
async function generateRoutes(userText=null,isFollowUp=false){
 if(state.routingBusy)return;
 const a=getPlace('start'),b=getPlace('end');
 if(!a||!b){toast('Select both a valid start and destination.');return}
 if(planner.constraints.stepFree){resetRoutes();$('rankingStatus').textContent='Step-free access needs verified curb-ramp and elevator data, which is not connected. No route recommendation will be returned.';appendChat('assistant','I cannot verify step-free access with the current source data, so no route has been recommended. "Avoid stairs" is available and excludes OSM steps.');return}
 if(geoDistanceKm([a.lon,a.lat],[b.lon,b.lat])<.07){toast('Start and destination too close to compare routes.');return}
 if(!latLonInsideManhattanEnvelope(a)||!latLonInsideManhattanEnvelope(b)){toast('Choose Manhattan locations.');return}
 chooseIntentLayer();
 const previous=state.routes.find(r=>r.id===state.activeRoute)?.raw.ordered_edge_ids.join(',');
 const run=++planner.runId;state.routingBusy=true;
 $('generateRoutes').disabled=true;$('chatSend').disabled=true;$('ctaLabel').textContent='✦ Planning your walk…';
 try{
  resetRoutes(true);renderRouteCards();
  if(location.protocol==='file:')throw new Error('The routing engine runs in server.py; start it and open http://127.0.0.1:8080.');
  const res=await streetwiseFetch('/api/routes',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(buildRouteRequest(a,b)),signal:AbortSignal.timeout(30000)});
  const json=await res.json().catch(()=>({}));
  if(run!==planner.runId)return;
  if(!res.ok)throw new Error(json.error||`Routing engine HTTP ${res.status}`);
  applyRouteResponse(json);
  const now=state.routes.find(r=>r.id===state.activeRoute)?.raw.ordered_edge_ids.join(',');
  if(previous&&now)planner.lastExplanation+=previous===now?' The recommended path is unchanged: it still ranks best under the updated preferences.':' The recommended path changed after recalculation.';
  $('rankingStatus').textContent=planner.lastExplanation;
  renderRouteCards();syncMapData();updateProfile();updateWhyRoute();renderRouteEdges();renderPOIs();
  appendChat('assistant',planner.lastExplanation);
  if(state.mapReady&&!isFollowUp){const bx=routeBounds(state.routes,80);if(bx)state.map.fitBounds([[bx[0],bx[1]],[bx[2],bx[3]]],{padding:65,maxZoom:15.5,duration:700});}
  await loadRoutePOIs(run);
 }catch(err){
  if(run!==planner.runId)return;
  planner.lastExplanation=`No route: ${err.message} No route was fabricated.`;
  $('rankingStatus').textContent=planner.lastExplanation;appendChat('assistant',planner.lastExplanation);toast(planner.lastExplanation);
 }finally{state.routingBusy=false;$('generateRoutes').disabled=false;$('chatSend').disabled=false;$('ctaLabel').textContent='✦ Plan My Walk';renderRouteCards()}
}
// Ranking happens in the engine; a changed limit asks the engine again instead of re-ranking locally.
function rankRoutes(){if(state.routes.length)queueMapReplan();}
function updateRoutesUI(){if(state.routes.length)queueMapReplan();else renderRouteCards();}
function selectRoute(id){
 const r=state.routes.find(x=>x.id===id);if(!r)return;
 state.activeRoute=id;routeNav.selectedEdge=null;urbanLayersRouteChanged();renderRouteCards();syncMapData();updateProfile();updateWhyRoute();renderRouteEdges();renderPOIs();
 if(state.mapReady){const b=routeBounds([r],160);if(b)state.map.fitBounds([[b[0],b[1]],[b[2],b[3]]],{padding:70,maxZoom:16,duration:500})}
}
function scoreText(v){return v==null?'N/A':String(v);}
/** The hard limits the engine actually applied to the current results (from the response, not the form). */
function constraintSummary(){
 const c=planner.routeResponse?.constraints_used;if(!c)return '';
 return `Hard limits used: max ${c.max_minutes==null?'—':Math.round(c.max_minutes)} min walking · ${c.avoid_detours&&c.max_detour_pct!=null?`max ${c.max_detour_pct}% detour`:'detour limit off'}${c.avoid_stairs?' · avoiding stairs':''} · ${planner.routeResponse.feasible_count} of ${planner.routeResponse.routes.length} routes feasible`;
}
function renderRouteCards(){
 const root=$('routeCards'),routes=state.routes;
 $('routeCount').textContent=`${routes.length} OSM ROUTE${routes.length===1?'':'S'}`;
 if(!routes.length){root.innerHTML=`<div class="empty-route"><strong>${state.routingBusy?'Computing pedestrian routes…':'No routes generated yet'}</strong><p>${state.routingBusy?'Searching the Manhattan OSM pedestrian graph.':'Start with a journey and walking preferences.'}</p></div>`;return}
 root.innerHTML=routes.map(x=>{
  const r=x.raw,selected=x.id===state.activeRoute,feasible=r.constraints.feasible;
  const tag=r.recommended?'BEST MATCH':r.objective==='shortest'?'SHORTEST':'ALTERNATIVE';
  return `<button class="route-card ${selected?'selected':''} ${!feasible?'over-budget':''}" type="button" data-route="${esc(x.id)}" aria-pressed="${selected}"><span class="route-icon">${selected?'✓':r.rank}</span><span class="route-names"><span class="route-category">${tag}${!feasible?' · NOT FEASIBLE':''}</span><strong>${esc(r.route_name)}</strong><small>Personalized ${r.personalized_score.utility} · Overall ${scoreText(r.overall_score)} · ${Math.round(r.data_coverage.mean*100)}% data coverage</small><small class="evidence-line">${r.detour_percentage>0?`+${r.detour_percentage}% vs shortest`:'Shortest distance'} · ${r.ordered_edge_ids.length} OSM edges</small>${!feasible?`<small>${esc(r.constraints.violations.join('; '))}</small>`:''}</span><span class="route-metrics"><strong>${(r.distance_m/1000).toFixed(2)} km</strong><small>${Math.ceil(r.estimated_duration_min)} min</small></span></button>`;
 }).join('')+`<p class="route-constraints">${esc(constraintSummary())}</p><p class="route-footnote">Routes are computed on the OSM pedestrian graph (${esc(planner.routeResponse?.network_version||'')}) and ranked by personalized utility = weighted experience − detour penalty. Experience scores are relative ranks within Manhattan (${esc(planner.routeResponse?.score_version||'')}), shared with Explore Urban Data.</p>`;
 root.querySelectorAll('[data-route]').forEach(el=>el.addEventListener('click',()=>selectRoute(el.dataset.route)));
}
function profileRows(r){
 return DIMENSIONS.map((d,i)=>{const v=r.dimension_scores[d.name],c=r.data_coverage.by_dimension[d.name],pref=planner.origins[d.name]!=='default';
  return `<div class="experience-row${pref?' preferred':''}"><span>${String(i+1).padStart(2,'0')} ${esc(dimLabel(d.name))}<small>${pref?`Your priority ${planner.weights[d.name]}${planner.directions[d.name]==='low'?' · prefer less':''} · `:''}${Math.round(c*100)}% coverage${c<.6?' · low':''}</small></span><strong>${scoreText(v)}</strong><div class="experience-meter"><i style="width:${v??0}%"></i></div></div>`;}).join('');
}
function updateProfile(){
 const x=state.routes.find(r=>r.id===state.activeRoute);
 $('profileSelected').setAttribute('aria-pressed',String(planner.profileView==='selected'));
 $('profileCompare').setAttribute('aria-pressed',String(planner.profileView==='compare'));
 if(!x){$('profileMode').textContent='NO ROUTE';$('profileChart').innerHTML='<div class="chart-empty"><p>Select a feasible route to see its 12 experience dimension scores.</p></div>';$('chartNote').textContent='Route scores = length-weighted mean of the OSM edges the route uses. N/A is never counted as zero.';return}
 const r=x.raw,measured=Object.values(r.dimension_scores).filter(v=>v!=null).length;
 $('profileMode').textContent=`${measured}/12 MEASURED`;
 if(planner.profileView==='compare'){
  $('profileChart').innerHTML=`<table class="route-compare"><thead><tr><th>Dimension</th>${state.routes.map(y=>`<th title="${esc(y.raw.route_name)}">${y.raw.rank}</th>`).join('')}</tr></thead><tbody>${DIMENSIONS.map(d=>`<tr><td>${esc(dimLabel(d.name))}</td>${state.routes.map(y=>`<td class="${y.id===state.activeRoute?'current':''}">${scoreText(y.raw.dimension_scores[d.name])}</td>`).join('')}</tr>`).join('')}<tr class="totals"><td>Personalized</td>${state.routes.map(y=>`<td>${y.raw.personalized_score.utility}</td>`).join('')}</tr><tr><td>Distance</td>${state.routes.map(y=>`<td>${(y.raw.distance_m/1000).toFixed(2)}</td>`).join('')}</tr><tr><td>Detour %</td>${state.routes.map(y=>`<td>${y.raw.detour_percentage}</td>`).join('')}</tr></tbody></table><small class="compare-key">${state.routes.map(y=>`${y.raw.rank} = ${esc(y.raw.route_name)}`).join(' · ')}</small>`;
 }else $('profileChart').innerHTML=`<div class="experience-rows">${profileRows(r)}</div>`;
 $('chartNote').textContent=`Overall ${scoreText(r.overall_score)} · mean data coverage ${Math.round(r.data_coverage.mean*100)}%. Each score is the length-weighted mean over the ${r.ordered_edge_ids.length} OSM edges this route uses (scored length only). Your priorities are stored separately and never change street scores.`;
}
function updateWhyRoute(){
 const x=state.routes.find(r=>r.id===state.activeRoute),root=$('whyRoute');
 if(!x){root.textContent=planner.constraints.stepFree?'Step-free access cannot be verified, so no route is recommended.':planner.routeResponse?planner.lastExplanation:'No selected route yet.';return}
 const p=x.raw.personalized_score;
 const parts=Object.entries(p.components).sort((a,b)=>b[1].weight-a[1].weight).slice(0,6).map(([d,c])=>`<div class="data-pair"><span>${esc(dimLabel(d))} · weight ${c.weight}${c.direction==='low'?' · less':''}</span><span>${scoreText(c.route_score)} → fit ${c.adjusted_fit}</span></div>`).join('');
 root.innerHTML=`<p>${esc(x.raw.ranking_explanation)}</p>${parts}<small>${esc(p.formula)}. ${p.preferences_expressed?'Weights come from your request.':'No preference expressed yet, so all 12 dimensions count equally.'}</small>`;
}
// --- Route edges: list in Route Intelligence and clickable on the map -------------------------------------
function routeEdgesGeojson(){
 const x=state.routes.find(r=>r.id===state.activeRoute);
 if(!x||mapExperience.mode==='explore')return emptyFC();
 return {type:'FeatureCollection',features:x.raw.edges.map((e,i)=>({type:'Feature',properties:{edge_id:e.edge_id,seq:i},geometry:e.geometry}))};
}
function renderRouteEdges(){
 const x=state.routes.find(r=>r.id===state.activeRoute),root=$('routeEdgeList');
 $('edgeCount').textContent=x?`${x.raw.ordered_edge_ids.length} EDGES`:'0';
 if(!x){root.innerHTML='<p class="soft-copy">Select a route to list the OSM pedestrian edges it uses, in order.</p>';return}
 root.innerHTML=x.raw.edges.map((e,i)=>`<button type="button" class="edge-row${routeNav.selectedEdge===i?' selected':''}" data-edge="${i}"><span>${i+1}. ${esc(e.name||(Array.isArray(e.highway)?e.highway.join('/'):e.highway)||'path')}</span><small>${esc(e.edge_id)} · ${Math.round(e.traversed_length_m)} m · ${esc(e.score_source.replace('_',' '))}</small></button>`).join('');
 root.querySelectorAll('[data-edge]').forEach(b=>b.addEventListener('click',()=>selectRouteEdge(Number(b.dataset.edge),true)));
}
function selectRouteEdge(seq,fly=false){
 const x=state.routes.find(r=>r.id===state.activeRoute);if(!x)return;const e=x.raw.edges[seq];if(!e)return;
 routeNav.selectedEdge=seq;
 if(state.mapLayersReady)state.map.setFilter('route-edge-selected',['==',['get','seq'],seq]);
 renderRouteEdges();
 const c=e.geometry.coordinates,mid=c[Math.floor(c.length/2)];
 if(fly&&state.mapReady)state.map.easeTo({center:mid,zoom:Math.max(state.map.getZoom(),16),duration:400});
 showRouteEdgeInspector(e,mid);
}
function showRouteEdgeInspector(e,lngLat){
 const html=routeEdgeInspectorHtml(e);
 let root;
 if(!state.mapReady||typeof maplibregl==='undefined'){$('segmentDetail').innerHTML=html;root=$('segmentDetail');}
 else root=new maplibregl.Popup({maxWidth:'330px'}).setLngLat(lngLat).setHTML(html).addTo(state.map).getElement();
 return fillFocusSubIndicators(root,e);
}
/** Dimension the user is looking at in the Urban Data Layers panel (or score overlay), if any. */
function routeFocusDim(){return typeof urbanLayers!=='undefined'&&urbanLayers.focusDim?urbanLayers.focusDim:null;}
function routeEdgeInspectorHtml(e){
 const key=routeFocusDim(),fi=key?ExperienceCore.keys.indexOf(key):-1,focus=fi>=0?DIMENSIONS[fi].name:null;
 const rows=DIMENSIONS.map(d=>{const v=e.dimension_scores[d.name];return `<div class="explore-row${d.name===focus?' current':''}"><span>${esc(dimLabel(d.name))}</span><i>${v==null?'':`<b style="width:${v}%;background:${typeof exploreColor==='function'?exploreColor(v,EXPLORE_VIEWS[1]):'#d8f365'}"></b>`}</i><em>${scoreText(v)}</em></div>`;}).join('');
 const lion=e.matched_segments?.length?e.matched_segments.map(m=>`<span class="seg-id">${esc(m.segment_id)}</span> ${esc(m.street_name||'')} · LION physicalid ${esc(m.source_segment_id??'—')}`).join('<br>')
  :e.score_source==='direct_osm'?'<strong>Unmatched</strong> — no reliable LION segment; scores measured directly on this OSM geometry':'<strong>Unmatched</strong> — not scored (outside the routable network)';
 const src=e.score_source==='lion_match'?`Borrowed from the matched LION segment(s), overlap-length weighted (${Math.round(e.lion_match_share*100)}% of the edge matched)`:e.score_source==='direct_osm'?'Measured directly on the OSM geometry with the shared indicator definitions':'Not scored';
 const cov=focus?e.data_coverage[focus]:Object.values(e.data_coverage).reduce((a,b)=>a+b,0)/12;
 const focusBlock=focus?`<div class="inspector-score"><span>${esc(dimLabel(focus))} · Experience Score</span><strong style="color:${typeof exploreColor==='function'?exploreColor(e.dimension_scores[focus],EXPLORE_VIEWS[1]):'#d8f365'}">${scoreText(e.dimension_scores[focus])}</strong><small>coverage ${Math.round(e.data_coverage[focus]*100)}% of this edge</small></div><div class="focus-subs" data-focus="${key}"><p class="soft-copy">Loading ${esc(dimLabel(focus))} sub-indicators…</p></div>`:'';
 return `<strong>Route Segment Inspector</strong><dl><dt>OSM Edge ID (u-v-key)</dt><dd>${esc(e.edge_id)}</dd><dt>OSM way ID(s)</dt><dd>${esc(e.osm_way_ids.join(', '))}</dd><dt>Matched LION Segment ID</dt><dd>${lion}</dd><dt>Street name</dt><dd>${esc(e.street_name||'Unnamed')} · ${esc([].concat(e.highway||[]).join('/'))}${e.pedestrian_access.footway?` · ${esc([].concat(e.pedestrian_access.footway).join('/'))}`:''}</dd><dt>Edge length</dt><dd>${Math.round(e.traversed_length_m)} m on route of ${Math.round(e.length_m)} m${e.partial?' (partial)':''}</dd><dt>Score source · quality</dt><dd>${esc(src)} · ${esc(e.match_quality)}</dd><dt>Score coverage</dt><dd>${Math.round(cov*100)}%${focus?` (${esc(dimLabel(focus))})`:' (mean of 12)'}</dd></dl>${focusBlock}<details class="all-dims" ${focus?'':'open'}><summary>All 12 dimension scores</summary><div class="explore-rows">${rows}</div></details><small>Edge overall ${scoreText(e.overall_score)} · ${esc(e.network_version)} · ${esc(e.score_version)}. Scores are relative ranks within Manhattan, not calibrated scores. Source-record IDs (trees, crashes…) are shown separately in the Raw Data Feature inspector.</small>`;
}
/** Sub-indicators behind the focused dimension: from the matched LION segment(s), or from the edge's own direct measurement. */
async function fillFocusSubIndicators(root,e){
 const box=root.querySelector('.focus-subs');if(!box)return;
 const key=box.dataset.focus,dim=DIMENSIONS[ExperienceCore.keys.indexOf(key)].name;
 const fmt=(x,v)=>v==null?'N/A':`${Number(v).toLocaleString(undefined,{maximumFractionDigits:2})} ${x.unit}`;
 const role=x=>x.role==='context'?'context':x.role==='down'?'in score · lower is better':'in score · higher is better';
 try{
  if(e.score_source==='direct_osm'&&e.direct_sub_indicators){
   const reg=await ensureUrbanRegistry(),inds=reg.indicators[key]||[];
   box.innerHTML=`<p class="soft-copy">Measured on this edge (records within distance, not snapped):</p>${inds.map(x=>`<div class="data-pair"><span>${esc(x.label)} <small>${esc(role(x))}</small></span><span>${esc(fmt(x,e.direct_sub_indicators[x.key]))}</span></div>`).join('')}<small>Sources: ${esc([...new Set(inds.map(x=>reg.source_labels[x.source]))].join('; '))}</small>`;
   return;
  }
  if(!e.matched_segment_ids.length){box.innerHTML='<p class="soft-copy">No sub-indicators: this edge is unmatched and not scored.</p>';return}
  const segs=await Promise.all(e.matched_segment_ids.slice(0,3).map(id=>streetwiseFetch('/api/segments/'+encodeURIComponent(id)).then(r=>r.ok?r.json():Promise.reject(new Error('segment '+id+' unavailable')))));
  box.innerHTML=segs.map(s=>`<div class="focus-seg"><strong>${esc(s.segment_id)} · ${esc(s.street_name)}</strong> <small>${esc(dimLabel(dim))} ${scoreText(s.dimension_scores[dim])}</small>${s.sub_indicators[dim].map(x=>`<div class="data-pair"><span>${esc(x.label)} <small>${esc(role(x))}</small></span><span>${esc(fmt(x,x.value))}</span></div>`).join('')}</div>`).join('')
   +`<small>Sources: ${esc([...new Set(segs.flatMap(s=>s.sub_indicators[dim].map(x=>s.data_sources[x.source])))].join('; '))}${e.matched_segment_ids.length>3?` · ${e.matched_segment_ids.length-3} more matched segment(s)`:''}</small>`;
 }catch(err){box.innerHTML=`<p class="soft-copy">Sub-indicators unavailable: ${esc(err.message)}</p>`;}
}
function setupRouteEdgeLayer(){
 const m=state.map;
 m.addSource('route-edges',{type:'geojson',data:emptyFC()});
 m.addLayer({id:'route-edge-selected',type:'line',source:'route-edges',filter:['==',['get','seq'],-1],paint:{'line-color':'#ffffff','line-width':9,'line-opacity':.95},layout:{'line-cap':'round'}},'poi-points');
 m.addLayer({id:'route-edge-hit',type:'line',source:'route-edges',paint:{'line-color':'#000','line-width':16,'line-opacity':0}},'poi-points');
 m.on('click','route-edge-hit',e=>{if(state.pick)return;const f=e.features?.[0];if(f)selectRouteEdge(f.properties.seq);});
 m.on('mouseenter','route-edge-hit',()=>{if(!state.pick)m.getCanvas().style.cursor='pointer';});
 m.on('mouseleave','route-edge-hit',()=>{if(!state.pick)m.getCanvas().style.cursor='';});
}
// --- GPS: position on the active route via the engine's progress endpoint (no live tracking is claimed) ------
function setGpsPosition(coords){
 state.gps={name:'My current location',lat:coords.latitude,lon:coords.longitude};
 $('gpsMain').textContent=latLonInsideManhattanEnvelope(state.gps)?'ACTIVE':'OUTSIDE STUDY AREA';
 $('gpsMeta').textContent=`±${coords.accuracy?Math.round(coords.accuracy)+'m':'?'} accuracy`;
 syncMapData();updateRouteProgress(coords.accuracy);
}
async function updateRouteProgress(accuracy){
 const x=state.routes.find(r=>r.id===state.activeRoute);
 if(!x||!state.gps||routeNav.pending||location.protocol==='file:')return;
 routeNav.pending=true;
 try{
  const res=await streetwiseFetch('/api/navigation/progress',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({route_id:x.id,lat:state.gps.lat,lon:state.gps.lon,accuracy_m:Number.isFinite(accuracy)?accuracy:null}),signal:AbortSignal.timeout(8000)});
  const p=await res.json();if(!res.ok)throw new Error(p.error);
  routeNav.last=p;
  $('gpsMeta').textContent=p.state==='off_route'?`Off route by ${Math.round(p.distance_from_route_m)} m · ±${Math.round(accuracy||0)} m`:p.state==='arrived'?'Arrived at destination':`On route · ${Math.round(p.remaining_m)} m / ${Math.ceil(p.remaining_min)} min left`;
  // Off-route re-planning only when GPS is the start and the fix is accurate enough (engine applies the ≤60 m rule).
  if(p.reroute_recommended&&state.start==='gps')queueMapReplan();
 }catch(err){routeNav.last=null;}
 finally{routeNav.pending=false;}
}
