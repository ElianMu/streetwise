'use strict';
/* Navigate · Urban Data Layers — a dataset-centred, route-based view of real NYC / OSM data.
   Reads the static catalog and 1 km tiles in data/layers (built by scripts/build_urban_layers.py), so it works on
   GitHub Pages without the API. Records are filtered along the selected route's real geometry (or to the current
   view) in the browser with urban-geo.js. Display corridors only change what is drawn, never any score. */
const UD_PALETTE=['#8fdc86','#4caf6a','#f6ac6e','#c39bff','#ff8fc8','#7fd6ff','#ff9f5a','#f2d36b','#4fb4ff','#ff4f6a','#b9e28c','#e7d27a','#9fb3ba','#ffc861','#7bc8d6','#d6e6e1','#c4776b','#a98bff'];
const UD_COLORS={street_trees:'#8fdc86',parks:'#4caf6a',natural_areas:'#2f8f55',waterfront_parks:'#3aa6a0',community_gardens:'#a8d65a',landmarks:'#f6ac6e',historic_districts:'#e0b16a',
 museums:'#c39bff',galleries:'#d7a6ff',theaters:'#ab7cff',cinemas:'#9b8cff',libraries:'#8fa2ff',public_art:'#ff8fc8',monuments:'#ffb3d9',restaurants:'#ff9f5a',cafes:'#e5b380',bars:'#ff7a59',
 bakeries:'#f0c98a',grocery:'#f2d36b',retail:'#e7c34a',markets:'#d9a23a',entertainment:'#ff6fa5',recreation:'#7fd6a6',activity_places:'#ffc861',pedestrian_crashes:'#ff4f6a',cyclist_crashes:'#ff8a4f',
 speed_limits:'#e8d24a',noise_complaints:'#ff7a6b',expressways:'#c4776b',subway_stations:'#4fb4ff',subway_entrances:'#7fc8ff',accessible_entrances:'#57e0ff',bus_stops:'#62a8ff',bike_share:'#4f7bff',
 ferry_terminals:'#7fe0d0',lion_centerline:'#8aa3a8',osm_sidewalks:'#7bc8d6',osm_crosswalks:'#ffffff',osm_paths:'#b9e28c',sidewalk_surface:'#9fb3ba',pedestrian_ramps:'#d6e6e1',intersections:'#c7d3d6',
 traffic_signals:'#ffd75a',pedestrian_plazas:'#d6b4ff',bike_routes:'#5fd4ff',benches:'#e7d27a',drinking_fountains:'#5fc8ff',public_restrooms:'#9ee0ff',building_footprints:'#8f9aa3',
 land_use:'#c9a86a',pops:'#d6b4ff',hospitals_clinics:'#ff6b6b',pharmacies:'#6bd6a0',schools:'#f2c46b',linknyc:'#b0c4ff',viewpoints:'#7fd6ff',pedestrian_bridges:'#ffffff'};
const ROUTE_SUMMARY=[
 {key:'trees',label:'Trees',ds:['street_trees']},{key:'parks',label:'Parks',ds:['parks']},{key:'landmarks',label:'Historic landmarks',ds:['landmarks']},
 {key:'districts',label:'Historic districts',ds:['historic_districts']},{key:'food',label:'Restaurants & cafés',ds:['restaurants','cafes']},
 {key:'transit',label:'Transit stops',ds:['subway_entrances','bus_stops'],note:'subway entrances + bus stops'},{key:'crashes',label:'Pedestrian crashes',ds:['pedestrian_crashes'],period:true}];
// Street segment evidence: each item states its own measure and radius; none of these radii is a scoring definition.
const SEGMENT_EVIDENCE=[
 {label:'Street trees',ds:['street_trees'],kind:'count',r:30,dim:'nature'},{label:'Tree density',ds:['street_trees'],kind:'density',r:30,dim:'nature'},
 {label:'Historic landmarks',ds:['landmarks'],kind:'count',r:100,dim:'architecture'},{label:'In a historic district',ds:['historic_districts'],kind:'coverage'},
 {label:'Restaurants & cafés',ds:['restaurants','cafes'],kind:'count',r:50,dim:'food_retail'},{label:'Nearest park',ds:['parks'],kind:'nearest',r:600,dim:'nature'},
 {label:'Pedestrian injury crashes',ds:['pedestrian_crashes'],kind:'count',r:30,dim:'access_safety'},{label:'Nearest subway entrance',ds:['subway_entrances'],kind:'nearest',r:800,dim:'transit_connectivity'},
 {label:'Bus stops',ds:['bus_stops'],kind:'count',r:100},{label:'Building footprints',ds:['building_footprints'],kind:'count',r:30}];
const KIND_LABEL={count:'Raw feature count',density:'Spatial density',nearest:'Nearest distance',coverage:'Area coverage'};
const urbanData={catalog:null,loading:null,byId:new Map(),tiles:new Map(),active:new Map(),drawn:new Map(),scope:'route',corridor:100,search:'',openCats:new Set(),settings:false,viewTimer:0,summarySeq:0,lastEdge:null};
const UD_BEFORE='route-alts';
const udColor=id=>UD_COLORS[id]||UD_PALETTE[[...id].reduce((s,c)=>s+c.charCodeAt(0),0)%UD_PALETTE.length];

// --- catalog & tiles ---------------------------------------------------------------------------------------
async function ensureUrbanCatalog(){
 if(urbanData.catalog)return urbanData.catalog;
 urbanData.loading=urbanData.loading||streetwiseJson('./data/layers/catalog.json',{signal:AbortSignal.timeout(20000)});
 try{const c=await urbanData.loading;UrbanGeo.setProjection(c.projection);urbanData.catalog=c;c.datasets.forEach(d=>urbanData.byId.set(d.id,d));}
 catch(e){urbanData.loading=null;throw e;}
 return urbanData.catalog;
}
function tileUrl(tileset,key){return `./data/layers/tiles/${tileset}/${key}.json`;}
function tilesFor(tileset,box){const m=urbanData.catalog.tilesets[tileset].tiles;return UrbanGeo.tileKeys(box,urbanData.catalog.tile_size_m).filter(k=>m[k]);}
function tileRecordCount(tileset,box){const m=urbanData.catalog.tilesets[tileset].tiles;return tilesFor(tileset,box).reduce((s,k)=>s+m[k],0);}
async function tileFeatures(tileset,box){
 const keys=tilesFor(tileset,box);
 const parts=await Promise.all(keys.map(k=>{const url=tileUrl(tileset,k);
  if(!urbanData.tiles.has(url)){urbanData.tiles.set(url,streetwiseJson(url).then(fc=>fc.features).catch(e=>{urbanData.tiles.delete(url);throw e;}));
   if(urbanData.tiles.size>500)urbanData.tiles.delete(urbanData.tiles.keys().next().value);}  // bounded tile cache
  return urbanData.tiles.get(url);}));
 return parts.flat();
}
const routeCoords=()=>state.routes.find(x=>x.id===state.activeRoute)?.coords||null;
const routeName=()=>state.routes.find(x=>x.id===state.activeRoute)?.label||null;
/** Records of one dataset within `distance` m of a lon/lat line, each with its distance. */
async function datasetAlong(d,coords,distance){
 const feats=(await tileFeatures(d.tileset,UrbanGeo.lineBox(coords.map(UrbanGeo.xy),distance))).filter(f=>UrbanGeo.matchesFilter(f,d.filter));
 return UrbanGeo.alongLine(feats,coords,distance);
}

// --- panel ---------------------------------------------------------------------------------------------------
async function openUrbanPanel(){
 const root=$('urbanCats');
 try{await ensureUrbanCatalog();renderUrbanPanel();}
 catch(e){root.innerHTML=`<p class="urban-note">Urban data catalog could not be loaded: ${esc(e.message)}</p>`;}
}
const STATUS_LABEL={CONNECTED:'Connected',AVAILABLE_NOT_CONNECTED:'Available · not connected',MISSING:'Missing',UNAVAILABLE:'Unavailable'};
function renderUrbanPanel(){
 const cat=urbanData.catalog;if(!cat)return;
 const q=urbanData.search.trim().toLowerCase();
 // Word-start matching, so "tree" finds Street trees but not every OpenStreetMap dataset.
 const re=q&&new RegExp('(^|[^a-z0-9])'+q.replace(/[.*+?^${}()|[\]\\]/g,'\\$&'),'i');
 const hit=d=>!q||[d.name,d.source,...(d.categories||[]).map(c=>cat.categories.find(x=>x.id===c)?.name)].some(t=>re.test(String(t||'')));
 $('urbanCats').innerHTML=cat.categories.map(c=>{
  const items=cat.datasets.filter(d=>d.categories.includes(c.id)&&hit(d)).sort((a,b)=>(a.status!=='CONNECTED')-(b.status!=='CONNECTED')||a.name.localeCompare(b.name));
  if(!items.length)return '';const on=items.filter(d=>urbanData.active.has(d.id)).length,conn=items.filter(d=>d.status==='CONNECTED').length;
  return `<details class="urban-cat" data-cat="${c.id}" ${q||urbanData.openCats.has(c.id)?'open':''}><summary><span>${esc(c.name)}</span><small>${conn} connected${on?` · ${on} on`:''}</small></summary>${items.map(urbanDatasetRow).join('')}</details>`;
 }).join('')||'<p class="urban-note">No dataset matches this search.</p>';
 $('urbanCats').querySelectorAll('.urban-cat').forEach(d=>d.addEventListener('toggle',()=>{d.open?urbanData.openCats.add(d.dataset.cat):urbanData.openCats.delete(d.dataset.cat);}));
 $('urbanCats').querySelectorAll('[data-ud-toggle]').forEach(c=>c.addEventListener('change',()=>toggleUrbanDataset(c.dataset.udToggle,c.checked)));
 $('urbanCats').querySelectorAll('[data-ud-info]').forEach(b=>b.addEventListener('click',()=>{const box=b.closest('.urban-ds').querySelector('.urban-meta');box.classList.toggle('hidden');b.setAttribute('aria-expanded',String(!box.classList.contains('hidden')));}));
 renderActiveLayers();
}
function urbanDatasetRow(d){
 if(d.status!=='CONNECTED')return `<div class="urban-ds off"><div class="urban-row"><input type="checkbox" disabled aria-label="${esc(d.name)} — ${esc(STATUS_LABEL[d.status])}"><span class="urban-swatch none"></span><span class="urban-name">${esc(d.name)}</span><span class="urban-badge off">${esc(STATUS_LABEL[d.status])}</span></div><p class="urban-reason">${esc(d.reason)}${d.source?` · ${d.source_url?`<a href="${esc(d.source_url)}" target="_blank" rel="noopener noreferrer">${esc(d.source)}</a>`:esc(d.source)}`:''}</p></div>`;
 const on=urbanData.active.has(d.id),dims=d.scoring.map(s=>dimLabel(ExperienceCore.names[ExperienceCore.keys.indexOf(s.dimension)])).join(', ');
 return `<div class="urban-ds"><div class="urban-row"><input type="checkbox" data-ud-toggle="${d.id}" ${on?'checked':''} aria-label="Show ${esc(d.name)}"><span class="urban-swatch ${d.geometry.toLowerCase()}" style="--c:${udColor(d.id)}"></span><span class="urban-name">${esc(d.name)}</span><span class="urban-badge ${d.used_in_scoring?'scoring':'context'}" title="${d.used_in_scoring?`Feeds the ${esc(dims)} score`:'Not part of any score'}">${d.used_in_scoring?'Used in scoring':'Context only'}</span><button type="button" class="urban-info" data-ud-info aria-expanded="false" title="Dataset details">i</button></div>
  <dl class="urban-meta hidden"><dt>Source</dt><dd><a href="${esc(d.source_url)}" target="_blank" rel="noopener noreferrer">${esc(d.source)}</a></dd><dt>Geometry</dt><dd>${esc(d.geometry)} · ${Number(d.feature_count).toLocaleString()} Manhattan records</dd><dt>Time</dt><dd>${esc(d.time_range||'—')}</dd><dt>Last updated</dt><dd>${esc(d.last_updated||'unknown')}</dd>
  <dt>Scoring</dt><dd>${d.used_in_scoring?esc(d.scoring.map(s=>`${dimLabel(ExperienceCore.names[ExperienceCore.keys.indexOf(s.dimension)])} (${s.sub_indicators.join(', ')})`).join('; ')):'Context only — not part of any score'}</dd>${d.note?`<dt>Note</dt><dd>${esc(d.note)}</dd>`:''}<dt>Fields</dt><dd>${esc(d.attributes.join(', '))}</dd></dl></div>`;
}
function renderActiveLayers(){
 $('urbanActiveCount').textContent=urbanData.active.size?`${urbanData.active.size} on`:'';
 $('urbanActiveTitle').textContent=`ACTIVE LAYERS: ${urbanData.active.size}`;
 $('urbanActive').innerHTML=[...urbanData.active.entries()].map(([id,a])=>{const d=urbanData.byId.get(id);
  return `<div class="urban-active-row"><span class="urban-swatch ${d.geometry.toLowerCase()}" style="--c:${udColor(id)}"></span><span class="urban-name">${esc(d.name)}${d.style?.by?` <small>${esc(urbanLegend(d))}</small>`:''}</span><span class="urban-status" data-ud-status="${id}">${esc(a.status||'')}</span><button type="button" class="urban-remove" data-ud-remove="${id}" aria-label="Turn off ${esc(d.name)}">×</button>
   ${urbanData.settings?`<label class="urban-opacity">Opacity <input type="range" min="15" max="100" value="${Math.round(a.opacity*100)}" data-ud-opacity="${id}"></label>`:''}</div>`;}).join('')||'<p class="urban-note">No layers on. Tick datasets above.</p>';
 $('urbanActive').querySelectorAll('[data-ud-remove]').forEach(b=>b.addEventListener('click',()=>toggleUrbanDataset(b.dataset.udRemove,false)));
 $('urbanActive').querySelectorAll('[data-ud-opacity]').forEach(r=>r.addEventListener('input',()=>setUrbanOpacity(r.dataset.udOpacity,r.value/100)));
}
function urbanLegend(d){return d.style.stops.map(([v])=>v).join(' → ')+(d.style.unit?` ${d.style.unit}`:'');}
function setUrbanStatus(id,text){const a=urbanData.active.get(id);if(!a)return;a.status=text;const el=document.querySelector(`[data-ud-status="${id}"]`);if(el)el.textContent=text;}

// --- map layers ----------------------------------------------------------------------------------------------
const udSource=id=>'ud-'+id;
function urbanStyleIds(id){const d=urbanData.byId.get(id),s=udSource(id);return d.geometry==='Point'?[s+'-cluster',s+'-pt']:d.geometry==='LineString'?[s+'-line']:[s+'-fill',s+'-outline'];}
function urbanMapLayerIds(){return [...urbanData.active.keys()].flatMap(urbanStyleIds);}
function udPaintColor(d){
 const c=udColor(d.id),st=d.style;
 if(st?.by)return ['case',['has',st.by],['interpolate',['linear'],['to-number',['get',st.by],0],...st.stops.flat()],c];
 if(st?.by_category){const cats=['One & two family','Multi-family walk-up','Multi-family elevator','Mixed residential & commercial','Commercial & office','Industrial & manufacturing','Transportation & utility','Public facilities & institutions','Open space & outdoor recreation','Parking','Vacant land'];
  return ['match',['get',st.by_category],...cats.flatMap((n,i)=>[n,UD_PALETTE[i]]),'#888888'];}
 return c;
}
function addUrbanMapLayer(id){
 const m=state.map,d=urbanData.byId.get(id),s=udSource(id),op=urbanData.active.get(id).opacity,color=udPaintColor(d);
 if(m.getSource(s))return;
 if(d.geometry==='Point'){
  // Clusters at low zoom keep dense points from covering the route; they split into single records as you zoom in.
  m.addSource(s,{type:'geojson',data:emptyFC(),cluster:!d.style,clusterRadius:34,clusterMaxZoom:15});
  m.addLayer({id:s+'-cluster',type:'circle',source:s,filter:['has','point_count'],paint:{'circle-color':udColor(id),'circle-opacity':op*.4,'circle-stroke-color':udColor(id),'circle-stroke-width':1.2,'circle-radius':['interpolate',['linear'],['get','point_count'],2,8,50,13,500,20]}},UD_BEFORE);
  m.addLayer({id:s+'-pt',type:'circle',source:s,filter:['!',['has','point_count']],paint:{'circle-color':color,'circle-opacity':op,'circle-radius':['interpolate',['linear'],['zoom'],12,2.4,16,5.5],'circle-stroke-color':'#0b1a1d','circle-stroke-width':.8}},UD_BEFORE);
 }else if(d.geometry==='LineString'){
  m.addSource(s,{type:'geojson',data:emptyFC()});
  m.addLayer({id:s+'-line',type:'line',source:s,layout:{'line-cap':'round'},paint:{'line-color':color,'line-opacity':op,'line-width':['interpolate',['linear'],['zoom'],12,1,16,3.2]}},UD_BEFORE);
 }else{
  m.addSource(s,{type:'geojson',data:emptyFC()});
  m.addLayer({id:s+'-fill',type:'fill',source:s,paint:{'fill-color':color,'fill-opacity':op*.3}},UD_BEFORE);
  m.addLayer({id:s+'-outline',type:'line',source:s,paint:{'line-color':color,'line-opacity':op,'line-width':1.1}},UD_BEFORE);
 }
 for(const lid of urbanStyleIds(id)){
  m.on('click',lid,e=>{if(state.pick||m.queryRenderedFeatures(e.point,{layers:['route-edge-hit']}).length)return;const f=e.features?.[0];if(!f)return;
   if(f.properties.point_count){m.getSource(s).getClusterExpansionZoom(f.properties.cluster_id).then(z=>m.easeTo({center:f.geometry.coordinates,zoom:z})).catch(()=>{});return;}
   showUrbanFeature(id,f);});
  m.on('mouseenter',lid,()=>{if(!state.pick)m.getCanvas().style.cursor='pointer';});m.on('mouseleave',lid,()=>{if(!state.pick)m.getCanvas().style.cursor='';});
 }
}
function removeUrbanMapLayer(id){const m=state.map,s=udSource(id);if(!state.mapLayersReady)return;for(const lid of urbanStyleIds(id))if(m.getLayer(lid))m.removeLayer(lid);if(m.getSource(s))m.removeSource(s);}
function setUrbanOpacity(id,op){
 const a=urbanData.active.get(id);if(!a)return;a.opacity=op;if(!state.mapLayersReady)return;const m=state.map,s=udSource(id);
 const set=(l,p,v)=>{if(m.getLayer(l))m.setPaintProperty(l,p,v);};
 set(s+'-pt','circle-opacity',op);set(s+'-cluster','circle-opacity',op*.4);set(s+'-line','line-opacity',op);set(s+'-fill','fill-opacity',op*.3);set(s+'-outline','line-opacity',op);
}
function toggleUrbanDataset(id,on){
 if(!on)urbanData.drawn.delete(id);
 const d=urbanData.byId.get(id);if(!d||d.status!=='CONNECTED')return;
 if(on){if(!urbanData.active.has(id)){urbanData.active.set(id,{opacity:.85,status:'Loading…',seq:0});if(state.mapLayersReady)addUrbanMapLayer(id);}loadUrbanDataset(id);}
 else{urbanData.active.delete(id);removeUrbanMapLayer(id);}
 renderUrbanPanel();
}
function clearUrbanLayers(){for(const id of [...urbanData.active.keys()])removeUrbanMapLayer(id);urbanData.active.clear();clearUrbanHighlight();renderUrbanPanel();}
async function loadUrbanDataset(id){
 const a=urbanData.active.get(id),d=urbanData.byId.get(id);if(!a)return;const seq=++a.seq;
 const done=(fc,text)=>{if(seq!==a.seq||!urbanData.active.has(id))return;urbanData.drawn.set(id,new Map(fc.features.map(f=>[String(f.properties.feature_id),f])));if(state.mapLayersReady)state.map.getSource(udSource(id))?.setData(fc);setUrbanStatus(id,text);};
 try{
  if(urbanData.scope==='route'){
   const coords=routeCoords();
   if(!coords){done(emptyFC(),'Select a route, or switch to Current Map View');return}
   setUrbanStatus(id,'Loading…');
   const hits=await datasetAlong(d,coords,urbanData.corridor);
   done({type:'FeatureCollection',features:hits.map(h=>({...h.feature,properties:{...h.feature.properties,distance_to_route_m:Math.round(h.distance*10)/10}}))},`${hits.length.toLocaleString()} within ${urbanData.corridor} m`);
  }else{
   if(!state.mapReady){done(emptyFC(),'Map not ready');return}
   const b=state.map.getBounds(),box=UrbanGeo.lonLatBox(b.getWest(),b.getSouth(),b.getEast(),b.getNorth()),n=tileRecordCount(d.tileset,box);
   if(state.map.getZoom()<d.min_zoom_view&&n>5000){done(emptyFC(),`Zoom in to load (${n.toLocaleString()} records nearby)`);return}
   setUrbanStatus(id,'Loading…');
   const feats=(await tileFeatures(d.tileset,box)).filter(f=>UrbanGeo.matchesFilter(f,d.filter)),seen=new Set(),inView=[];
   for(const f of feats){if(seen.has(f.properties.feature_id))continue;seen.add(f.properties.feature_id);const bb=UrbanGeo.bboxOf(UrbanGeo.project(f.geometry));if(bb[0]<=box[2]&&bb[2]>=box[0]&&bb[1]<=box[3]&&bb[3]>=box[1])inView.push(f);}
   done({type:'FeatureCollection',features:inView},`${inView.length.toLocaleString()} in view`);
  }
 }catch(e){done(emptyFC(),'Load failed: '+e.message);}
}
function refreshUrbanLayers(){for(const id of urbanData.active.keys())loadUrbanDataset(id);}
/** Route changed (planned, switched or cleared): keep the user's layers, re-filter them, update the summary. */
function urbanLayersRouteChanged(){if(urbanData.scope==='route')refreshUrbanLayers();renderRouteUrbanData();closeUrbanInspector();}
function urbanViewMoved(){if(urbanData.scope!=='view'||!urbanData.active.size)return;clearTimeout(urbanData.viewTimer);urbanData.viewTimer=setTimeout(refreshUrbanLayers,400);}

// --- docked inspector ------------------------------------------------------------------------------------------
function openUrbanInspector(title,html){const box=$('urbanInspector');box.innerHTML=`<div class="inspector-head"><div><div class="explore-eyebrow">${esc(title)}</div></div><button type="button" class="explore-collapse" id="urbanInspectorClose" aria-label="Close inspector">✕</button></div>${html}`;box.classList.remove('hidden');$('urbanInspectorClose').addEventListener('click',closeUrbanInspector);return box;}
function closeUrbanInspector(){$('urbanInspector')?.classList.add('hidden');clearUrbanHighlight();}
const NA='<span class="na">Not Available</span>';
function urbanFeatureHtml(d,props){
 const v=x=>x==null||x===''?NA:/^https?:\/\//.test(String(x))?`<a href="${esc(x)}" target="_blank" rel="noopener noreferrer">open link</a>`:esc(x);
 const title=props.name||props.LPC_NAME||props.area_name||props.signname||props.gardenname||props.plazaname||props.facility_name||props.building_name||props.stop_name||props.genusspecies||props.complaint_type||props.street_name||props.street||d.name;
 const rel=props.distance_to_route_m!=null&&routeName()?`${esc(routeName())} · ${props.distance_to_route_m} m from the route`:routeName()?`${esc(routeName())} (current view; distance not computed)`:'No route selected';
 return `<dl class="inspector-ids"><dt>Dataset</dt><dd>${esc(d.name)}</dd><dt>Feature</dt><dd>${esc(title)}</dd><dt>Record ID</dt><dd>${esc(props.feature_id)}</dd></dl>
  <dl class="inspector-fields">${d.attributes.map(k=>`<dt>${esc(k)}</dt><dd>${v(props[k])}</dd>`).join('')}</dl>
  <dl class="inspector-ids"><dt>Data source</dt><dd>${esc(d.source)}</dd><dt>Data period</dt><dd>${esc(d.time_range||'—')}</dd><dt>Last updated</dt><dd>${esc(d.last_updated||'unknown')}</dd><dt>Related route</dt><dd>${rel}</dd><dt>Scoring</dt><dd>${d.used_in_scoring?'Used in scoring':'Context only'}</dd></dl>
  ${d.historical?'<p class="urban-warn">Historical record — not a real-time safety or condition prediction.</p>':''}${d.note?`<p class="urban-note">${esc(d.note)}</p>`:''}
  <a class="urban-source" href="${esc(d.source_url)}" target="_blank" rel="noopener noreferrer">View source ↗</a>`;
}
function showUrbanFeature(id,f){
 const d=urbanData.byId.get(id);
 const full=urbanData.drawn.get(id)?.get(String(f.properties.feature_id));  // the source record, not MapLibre's clipped render copy
 setUrbanHighlight(full||f);openUrbanInspector('URBAN FEATURE INSPECTOR',urbanFeatureHtml(d,(full||f).properties));
}
function setUrbanHighlight(f){if(state.mapLayersReady)state.map.getSource('ud-highlight')?.setData({type:'FeatureCollection',features:[{type:'Feature',properties:{},geometry:f.geometry}]});}
function clearUrbanHighlight(){if(state.mapLayersReady)state.map.getSource('ud-highlight')?.setData(emptyFC());}

// --- street segment evidence (route edge) -------------------------------------------------------------------
/** Spatial evidence around one route edge, computed now from the tiles. Each item names its measure and radius. */
async function segmentEvidence(edge){
 await ensureUrbanCatalog();
 const coords=edge.geometry.coordinates,lenKm=Math.max(UrbanGeo.lengthM(coords),1)/1000,out=[];
 for(const it of SEGMENT_EVIDENCE){
  const ds=it.ds.map(id=>urbanData.byId.get(id));
  if(ds.some(d=>!d||d.status!=='CONNECTED')){out.push({...it,value:null,text:'Data Unavailable'});continue}
  try{
   if(it.kind==='coverage'){const feats=(await Promise.all(ds.map(d=>tileFeatures(d.tileset,UrbanGeo.lineBox(coords.map(UrbanGeo.xy),0))))).flat();
    const share=UrbanGeo.shareInside(feats,coords),names=[...new Set(feats.filter(f=>UrbanGeo.alongLine([f],coords,0).length).map(f=>f.properties.area_name))];
    out.push({...it,value:share,text:share?`${Math.round(share*100)}% of the segment${names.length?` · ${names.join(', ')}`:''}`:'No'});continue}
   const hits=(await Promise.all(ds.map(d=>datasetAlong(d,coords,it.r)))).flat();
   if(it.kind==='nearest'){const n=hits.sort((a,b)=>a.distance-b.distance)[0];out.push({...it,value:n?n.distance:null,text:n?`${Math.round(n.distance)} m${n.feature.properties.signname||n.feature.properties.stop_name?` · ${n.feature.properties.signname||n.feature.properties.stop_name}`:''}`:`None within ${it.r} m`});continue}
   const n=hits.length,dd=ds[0];
   out.push({...it,value:it.kind==='density'?n/lenKm:n,text:it.kind==='density'?`${(n/lenKm).toFixed(1)} per km of this segment`:`${n} within ${it.r} m${dd.historical?` · ${dd.time_range}`:''}`});
  }catch(e){out.push({...it,value:null,text:'Load failed: '+e.message});}
 }
 return out;
}
/** Existing scoring indicators of the matched LION segment(s) (static Explore data) — the only "Used in scoring" values. */
async function scoringIndicators(edge,dims){
 if(edge.score_source==='direct_osm'&&edge.direct_sub_indicators){const cat=await loadExploreStreets(),inds=cat.metadata.indicators;
  return dims.map(k=>({dim:k,source:'measured directly on this OSM edge',rows:inds[k].filter(x=>x.role!=='context').map(x=>({label:x.label,value:edge.direct_sub_indicators[x.key],unit:x.unit}))}));}
 if(!edge.matched_segment_ids.length)return [];
 const data=await loadExploreStreets(),inds=data.metadata.indicators,seg=data.features.find(f=>f.properties.id===edge.matched_segment_ids[0])?.properties;
 if(!seg)return [];
 return dims.map(k=>({dim:k,source:`LION segment ${seg.id} (${seg.name})`,rows:inds[k].filter(x=>x.role!=='context').map(x=>({label:x.label,value:seg[x.key],unit:x.unit}))}));
}
async function showSegmentEvidence(edge,headHtml){
 urbanData.lastEdge=edge.edge_id;
 setUrbanHighlight({geometry:edge.geometry});
 const box=openUrbanInspector('STREET SEGMENT EVIDENCE',`${headHtml}<h4>Nearby urban data</h4><div class="evidence-list"><p class="soft-copy">Measuring around this segment…</p></div><h4>Used in scoring</h4><div class="evidence-scoring"><p class="soft-copy">Loading…</p></div>`);
 const ev=await segmentEvidence(edge);if(urbanData.lastEdge!==edge.edge_id)return;
 box.querySelector('.evidence-list').innerHTML=ev.map(x=>`<div class="evidence-row"><span>${esc(x.label)}<small>${esc(KIND_LABEL[x.kind])}${x.r&&x.kind!=='coverage'?` · ${x.kind==='nearest'?'searched':'radius'} ${x.r} m`:''} · context only</small></span><strong>${esc(x.text)}</strong></div>`).join('')
  +`<small>Measured now from ${esc([...new Set(ev.flatMap(x=>x.ds.map(id=>urbanData.byId.get(id)?.source).filter(Boolean)))].join('; '))}. These radii describe the evidence shown here; they are not the scoring definitions.</small>`;
 const dims=[...new Set(ev.map(x=>x.dim).filter(Boolean))];
 try{const sc=await scoringIndicators(edge,dims);if(urbanData.lastEdge!==edge.edge_id)return;
  box.querySelector('.evidence-scoring').innerHTML=sc.length?sc.map(s=>{const name=DIMENSIONS[ExperienceCore.keys.indexOf(s.dim)].name;return `<div class="evidence-score"><div class="evidence-row"><span>${esc(dimLabel(name))} score of this edge</span><strong>${scoreText(edge.dimension_scores[name])}</strong></div>${s.rows.map(r=>`<div class="evidence-row sub"><span>${esc(r.label)}</span><strong>${r.value==null?'N/A':`${Number(r.value).toLocaleString(undefined,{maximumFractionDigits:2})} ${esc(r.unit)}`}</strong></div>`).join('')}<small>${esc(s.source)}</small></div>`;}).join('')
   :'<p class="soft-copy">This edge is unmatched and not scored, so no scoring indicators apply.</p>';}
 catch(e){box.querySelector('.evidence-scoring').innerHTML=`<p class="soft-copy">Scoring indicators unavailable: ${esc(e.message)}</p>`;}
}

// --- route evidence summary (Route Intelligence) ------------------------------------------------------------
async function renderRouteUrbanData(){
 const root=$('routeUrbanData');if(!root)return;const seq=++urbanData.summarySeq,coords=routeCoords();
 $('routeUrbanCorridor').textContent=coords?`WITHIN ${urbanData.corridor} M`:'';
 if(!coords){root.innerHTML='<p class="soft-copy">Select a route to see the real city data around it.</p>';return}
 const r=state.routes.find(x=>x.id===state.activeRoute);
 root.innerHTML=`<div class="data-pair"><span>Selected route</span><span>${esc(r.label)} · ${(r.raw.distance_m/1000).toFixed(2)} km</span></div><div class="route-urban-items"><p class="soft-copy">Querying nearby datasets…</p></div>`;
 try{await ensureUrbanCatalog();}catch(e){if(seq===urbanData.summarySeq)root.querySelector('.route-urban-items').innerHTML=`<p class="soft-copy">Urban data unavailable: ${esc(e.message)}</p>`;return}
 const rows=await Promise.all(ROUTE_SUMMARY.map(async it=>{
  const ds=it.ds.map(id=>urbanData.byId.get(id));
  if(ds.some(d=>!d||d.status!=='CONNECTED'))return {...it,text:'Data Unavailable'};
  try{const n=(await Promise.all(ds.map(d=>datasetAlong(d,coords,urbanData.corridor)))).reduce((s,h)=>s+h.length,0);return {...it,n,text:`${n.toLocaleString()}${it.period?` · ${ds[0].time_range}`:''}`};}
  catch(e){return {...it,text:'Data Unavailable'};}
 }));
 if(seq!==urbanData.summarySeq)return;
 root.querySelector('.route-urban-items').innerHTML=rows.map(x=>`<button type="button" class="route-urban-item" data-ud-show="${x.ds.join(',')}" title="Show on map"><span>${esc(x.label)}${x.note?`<small>${esc(x.note)}</small>`:''}</span><strong>${esc(x.text)}</strong></button>`).join('')
  +`<button type="button" class="mini-outline" id="routeUrbanExplore">Explore on map ↗</button><small class="route-urban-foot">Real records within ${urbanData.corridor} m of the route's geometry (map display corridor, not a scoring distance).</small>`;
 root.querySelectorAll('[data-ud-show]').forEach(b=>b.addEventListener('click',()=>showDatasetsOnRoute(b.dataset.udShow.split(','))));
 $('routeUrbanExplore').addEventListener('click',()=>{$('urbanLayers').open=true;openUrbanPanel();});
}
function showDatasetsOnRoute(ids){
 if(urbanData.scope!=='route'){urbanData.scope='route';document.querySelector('[name="urbanScope"][value="route"]').checked=true;}
 for(const id of ids)toggleUrbanDataset(id,true);
 const r=state.routes.find(x=>x.id===state.activeRoute);if(r&&state.mapReady){const b=routeBounds([r],urbanData.corridor);if(b)state.map.fitBounds([[b[0],b[1]],[b[2],b[3]]],{padding:70,maxZoom:16,duration:500});}
}

// --- setup -----------------------------------------------------------------------------------------------------
function setupUrbanMap(){
 const m=state.map;
 m.addSource('ud-highlight',{type:'geojson',data:emptyFC()});
 m.addLayer({id:'ud-highlight-fill',type:'fill',source:'ud-highlight',filter:['==',['geometry-type'],'Polygon'],paint:{'fill-color':'#ffffff','fill-opacity':.18}});
 m.addLayer({id:'ud-highlight-line',type:'line',source:'ud-highlight',paint:{'line-color':'#ffffff','line-width':3.5}});
 m.addLayer({id:'ud-highlight-pt',type:'circle',source:'ud-highlight',filter:['==',['geometry-type'],'Point'],paint:{'circle-radius':9,'circle-color':'rgba(0,0,0,0)','circle-stroke-color':'#ffffff','circle-stroke-width':2.5}});
 for(const id of urbanData.active.keys())addUrbanMapLayer(id);
 m.on('moveend',urbanViewMoved);
}
function setupUrbanControls(){
 const panel=$('urbanLayers');
 panel.addEventListener('toggle',()=>{if(panel.open)openUrbanPanel();});
 document.querySelectorAll('[name="urbanScope"]').forEach(r=>r.addEventListener('change',()=>{urbanData.scope=r.value;refreshUrbanLayers();}));
 $('urbanCorridor').addEventListener('change',e=>{urbanData.corridor=Number(e.target.value);refreshUrbanLayers();renderRouteUrbanData();});
 $('urbanSearch').addEventListener('input',e=>{urbanData.search=e.target.value;renderUrbanPanel();});
 $('urbanClear').addEventListener('click',clearUrbanLayers);
 $('urbanSettings').addEventListener('click',()=>{urbanData.settings=!urbanData.settings;$('urbanSettings').setAttribute('aria-pressed',String(urbanData.settings));renderActiveLayers();});
 document.addEventListener('keydown',e=>{if(e.key==='Escape')closeUrbanInspector();});
}
