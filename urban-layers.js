'use strict';
/* Navigate · Urban Data Layers — a dataset-centred, route-based view of real NYC / OSM data.
   Reads the static catalog and 1 km tiles in data/layers (built by scripts/build_urban_layers.py), so it works on
   GitHub Pages without the API. Records are filtered along the selected route's real geometry (or to the current
   view) in the browser with urban-geo.js. Display corridors only change what is drawn, never any score. */
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
const urbanData={catalog:null,loading:null,byId:new Map(),tiles:new Map(),active:new Map(),drawn:new Map(),buildingTheme:'height',envTheme:'noise',scope:'route',corridor:100,search:'',openCats:new Set(),settings:false,viewTimer:0,summarySeq:0,lastEdge:null};
const UD_BEFORE='route-alts';
async function crimeMetadata(){
 if(urbanData.crimeMeta)return urbanData.crimeMeta;
 const m=await streetwiseJson('/api/urban/crime/metadata',{signal:AbortSignal.timeout(20000)});urbanData.crimeMeta=m;return m;
}

// --- catalog & tiles ---------------------------------------------------------------------------------------
/** First visit: every connected dataset with default_visible is switched on, once. */
function applyUrbanDefaults(c){if(urbanData.defaultsApplied)return;urbanData.defaultsApplied=true;
 for(const d of c.datasets)if(d.status==='CONNECTED'&&d.default_visible!==false)toggleUrbanDataset(d.id,true,true);renderActiveCount();renderUrbanLegend();}
async function ensureUrbanCatalog(){
 if(urbanData.catalog)return urbanData.catalog;
 urbanData.loading=urbanData.loading||streetwiseJson('./data/layers/catalog.json',{signal:AbortSignal.timeout(20000)});
 try{const c=await urbanData.loading;for(const d of c.remote_datasets||[])if(!c.datasets.some(x=>x.id===d.id))c.datasets.push(d);UrbanGeo.setProjection(c.projection);urbanData.catalog=c;c.datasets.forEach(d=>urbanData.byId.set(d.id,d));applyUrbanDefaults(c);}
 catch(e){urbanData.loading=null;throw e;}
 return urbanData.catalog;
}
function tileUrl(tileset,key){return `./data/layers/tiles/${tileset}/${key}.json`;}
function tilesFor(tileset,box){const m=urbanData.catalog.tilesets[tileset].tiles;return UrbanGeo.tileKeys(box,urbanData.catalog.tile_size_m).filter(k=>m[k]);}
function tileRecordCount(tileset,box){const m=urbanData.catalog.tilesets[tileset].tiles;return tilesFor(tileset,box).reduce((s,k)=>s+m[k],0);}
// At most 12 tile requests in flight: a whole-island view must not fire thousands of requests at once.
const tileQueue={active:0,waiting:[]};
function queuedJson(url){return new Promise((res,rej)=>{const run=()=>{tileQueue.active++;streetwiseJson(url).then(res,rej).finally(()=>{tileQueue.active--;tileQueue.waiting.shift()?.();});};
 tileQueue.active<12?run():tileQueue.waiting.push(run);});}
async function tileFeatures(tileset,box){
 const keys=tilesFor(tileset,box);
 const parts=await Promise.all(keys.map(k=>{const url=tileUrl(tileset,k);
  if(!urbanData.tiles.has(url)){urbanData.tiles.set(url,queuedJson(url).then(fc=>fc.features).catch(e=>{urbanData.tiles.delete(url);throw e;}));
   if(urbanData.tiles.size>3000)urbanData.tiles.delete(urbanData.tiles.keys().next().value);}  // bounded tile cache
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

// --- composition: which render group draws each dataset -------------------------------------------------
const UD_CATEGORY_IDS=['streets','nature','buildings','heritage','activities','safety','environment','transit','services','waterfront'];
const BUILDING_SET=['building_footprints','building_heights','building_age','land_use'];
const BUILDING_THEMES=[['neutral','Neutral buildings',null],['height','Building height','building_heights'],['age','Building year built','building_age'],['landuse','Land use (PLUTO)','land_use']];
const ENV_THEMES=[['noise','311 noise complaint density','noise_complaints'],['none','No environmental surface',null],['air_quality','Air quality',null],['urban_heat','Urban heat',null],['flood_risk','Flood risk',null]];
function udGroup(d){
 if(d.remote==='crime')return 'crime';
 if(d.remote==='trees')return 'trees';
 if(d.remote?.startsWith('context:'))return 'context';
 const s=UrbanStyle.SPECIAL[d.id];if(s)return s;
 if(d.geometry==='LineString')return 'lines';
 if(d.geometry==='Polygon')return 'surface';
 return 'pts-'+d.categories[0];
}
/** Colour of a dataset: its primary category's family, shaded by its position within that category. */
function udColor(id){
 const d=urbanData.byId.get(id);if(!d)return '#909296';
 if(UrbanStyle.LINES[id])return UrbanStyle.LINES[id].color;
 const cat=d.categories[0],peers=urbanData.catalog.datasets.filter(x=>x.status==='CONNECTED'&&x.categories[0]===cat&&udGroup(x)===udGroup(d));
 return UrbanStyle.shade(UrbanStyle.T.cat[cat],peers.indexOf(d),peers.length);
}
/** How an enabled dataset is actually drawn right now (stated in the panel and legend, never hidden silently). */
function udRepresentation(id){
 const z=state.mapReady?state.map.getZoom():12,T=UrbanStyle.T,g=udGroup(urbanData.byId.get(id));
 if(id==='reported_complaints')return 'NYPD historical complaints · aggregated cells; no personal-risk prediction';
 if(urbanData.byId.get(id).remote==='trees')return z<16?'Aggregated inventory cell centres; counts in inspector':'Source tree inventory points; no canopy/shade claim';
 if(BUILDING_SET.includes(id)){const theme=BUILDING_THEMES.find(t=>t[0]===urbanData.buildingTheme);
  if(id==='building_footprints')return `Building footprints · fill = ${theme[1]}`;
  return theme[2]===id?'Controls the building fill (active theme)':`Enabled · building theme is ${theme[1]}; open the inspector or switch theme`;}
 if(id==='noise_complaints')return urbanData.envTheme==='noise'?(z<16.5?'Density surface (environment theme)':'Individual complaints at detail zoom'):'Enabled · not the environment theme; shown as points from z16.5';
 if(id==='natural_areas'||id==='waterfront_parks')return 'Dashed outline over the park fill';
 if(id==='activity_places')return 'Draws places not already shown by a more specific dataset (no double dots)';
 if(id==='street_trees')return z<12?'Shown from z12 as a fine texture':'Fine green texture';
 if(g.startsWith('pts-'))return z<T.cluster.maxZoom?`Grouped with ${urbanCatName(urbanData.byId.get(id).categories[0])} into clusters below z${T.cluster.maxZoom}`:'Individual records';
 const L=UrbanStyle.LINES[id];if(L?.minzoom&&z<L.minzoom)return `Generalised: shown from z${L.minzoom}`;
 if(id==='sidewalk_surface'&&z<T.zoom.street)return `Generalised: shown from z${T.zoom.street}`;
 return 'Drawn';
}
const urbanCatName=c=>urbanData.catalog?.categories.find(x=>x.id===c)?.name||c;

// --- panel ---------------------------------------------------------------------------------------------------
async function openUrbanPanel(){
 const root=$('urbanCats');
 try{await ensureUrbanCatalog();renderUrbanPanel();}
 catch(e){root.innerHTML=`<p class="urban-note">Urban data catalog could not be loaded: ${esc(e.message)}</p>`;}
}
const STATUS_LABEL={CONNECTED:'Connected',AVAILABLE_NOT_CONNECTED:'Not connected · available',MISSING:'Not connected · no dataset',UNAVAILABLE:'Unavailable'};
function renderUrbanPanel(){
 const cat=urbanData.catalog;if(!cat)return;
 const q=urbanData.search.trim().toLowerCase();
 // Word-start matching, so "tree" finds Street trees but not every OpenStreetMap dataset.
 const re=q&&new RegExp('(^|[^a-z0-9])'+q.replace(/[.*+?^${}()|[\]\\]/g,'\\$&'),'i');
 const hit=d=>!q||[d.name,d.source,...(d.categories||[]).map(c=>cat.categories.find(x=>x.id===c)?.name)].some(t=>re.test(String(t||'')));
 $('urbanCats').innerHTML=cat.categories.map(c=>{
  const items=cat.datasets.filter(d=>d.categories.includes(c.id)&&hit(d)).sort((a,b)=>(a.status!=='CONNECTED')-(b.status!=='CONNECTED')||a.name.localeCompare(b.name));
  if(!items.length)return '';const conn=items.filter(d=>d.status==='CONNECTED'),on=conn.filter(d=>urbanData.active.has(d.id)).length;
  const state_=!on?'none':on===conn.length?'all':'some';
  return `<details class="urban-cat" data-cat="${c.id}" ${q||urbanData.openCats.has(c.id)?'open':''}><summary><input type="checkbox" data-ud-cat="${c.id}" data-state="${state_}" ${state_==='all'?'checked':''} ${conn.length?'':'disabled'} aria-label="Show all ${esc(c.name)}"><span class="urban-swatch" style="--c:${UrbanStyle.T.cat[c.id]}"></span><span>${esc(c.name)}</span><small>${on}/${conn.length} on</small></summary>${items.map(urbanDatasetRow).join('')}</details>`;
 }).join('')||'<p class="urban-note">No dataset matches this search.</p>';
 $('urbanCats').querySelectorAll('[data-ud-cat]').forEach(c=>{c.indeterminate=c.dataset.state==='some';
  c.addEventListener('click',e=>e.stopPropagation());c.addEventListener('change',()=>setUrbanCategory(c.dataset.udCat,c.checked));});
 $('urbanCats').querySelectorAll('.urban-cat').forEach(d=>d.addEventListener('toggle',()=>{d.open?urbanData.openCats.add(d.dataset.cat):urbanData.openCats.delete(d.dataset.cat);}));
 $('urbanCats').querySelectorAll('[data-ud-toggle]').forEach(c=>c.addEventListener('change',()=>toggleUrbanDataset(c.dataset.udToggle,c.checked)));
 $('urbanCats').querySelectorAll('[data-ud-info]').forEach(b=>b.addEventListener('click',()=>{const box=b.closest('.urban-ds').querySelector('.urban-meta');box.classList.toggle('hidden');b.setAttribute('aria-expanded',String(!box.classList.contains('hidden')));}));
 $('urbanCats').querySelectorAll('[data-ud-opacity]').forEach(r=>r.addEventListener('input',()=>setUrbanOpacity(r.dataset.udOpacity,r.value/100)));
 $('urbanCats').querySelectorAll('[data-crime-filter]').forEach(r=>r.addEventListener('change',()=>{
  if(state.routingBusy||planner.parsing){toast('Wait for the current route calculation before changing its data filters.');renderUrbanPanel();return;}
  const filters=urbanData.crimeFilter||{},k=r.dataset.crimeFilter;filters[k]=k==='offense_types'?(r.value?[r.value]:[]):r.value;urbanData.crimeFilter=filters;
  if(planner.crime){planner.crime={...planner.crime,...filters};if(typeof journeyMode==='function'&&journeyMode())planJourney(true);else generateRoutes(null,true);}
  loadUrbanDataset('reported_complaints');
 }));
 renderActiveCount();
}
function urbanDatasetRow(d){
 if(d.status!=='CONNECTED')return `<div class="urban-ds off"><div class="urban-row"><input type="checkbox" disabled aria-label="${esc(d.name)} — ${esc(STATUS_LABEL[d.status])}"><span class="urban-swatch none"></span><span class="urban-name">${esc(d.name)}</span><span class="urban-badge off">${esc(STATUS_LABEL[d.status])}</span></div><p class="urban-reason">${esc(d.reason)}${d.source?` · ${d.source_url?`<a href="${esc(d.source_url)}" target="_blank" rel="noopener noreferrer">${esc(d.source)}</a>`:esc(d.source)}`:''}</p></div>`;
 const a=urbanData.active.get(d.id),dims=d.scoring.map(s=>dimLabel(ExperienceCore.names[ExperienceCore.keys.indexOf(s.dimension)])).join(', ');
 const cm=urbanData.crimeMeta,cf={...(planner.crime||{}),...(urbanData.crimeFilter||{})};
 const crimeFilters=d.remote==='crime'?`<div class="urban-note"><label>From <input type="date" data-crime-filter="from" value="${esc(cf.from||cm?.default_start||'')}" min="${esc(cm?.available_start||'')}" max="${esc(cm?.available_end_exclusive||'')}"></label> <label>To (exclusive) <input type="date" data-crime-filter="to" value="${esc(cf.to||cm?.available_end_exclusive||'')}"></label><label>Offense <select data-crime-filter="offense_types"><option value="">Felony + misdemeanor complaints</option>${[...new Set(Object.values(cm?.offenses||{}).flat())].sort().map(v=>`<option value="${esc(v)}" ${cf.offense_types?.includes(v)?'selected':''}>${esc(v)}</option>`).join('')}</select></label></div>`:'';
 return `<div class="urban-ds"><div class="urban-row"><input type="checkbox" data-ud-toggle="${d.id}" ${a?'checked':''} aria-label="Show ${esc(d.name)}"><span class="urban-swatch ${d.geometry.toLowerCase()}" style="--c:${udColor(d.id)}"></span><span class="urban-name">${esc(d.name)}</span><span class="urban-badge ${d.used_in_scoring?'scoring':'context'}" title="${d.independent_metric?'Independent route objective; the 12 dimensions are unchanged':d.used_in_scoring?`Feeds the ${esc(dims)} score`:'Map context; not part of a core experience score'}">${d.independent_metric?'Route metric':d.used_in_scoring?'Scoring':'Context'}</span><button type="button" class="urban-info" data-ud-info aria-expanded="false" title="Dataset details">i</button></div>
  ${a?`<div class="urban-live"><span class="urban-status ${a.kind||''}" data-ud-status="${d.id}">${esc(a.status||'')}</span><span class="urban-repr" data-ud-repr="${d.id}">${esc(udRepresentation(d.id))}</span>${urbanData.settings?`<label class="urban-opacity">Opacity <input type="range" min="15" max="100" value="${Math.round(a.opacity*100)}" data-ud-opacity="${d.id}"></label>`:''}</div>${crimeFilters}`:''}
  <dl class="urban-meta hidden"><dt>Source</dt><dd><a href="${esc(d.source_url)}" target="_blank" rel="noopener noreferrer">${esc(d.source)}</a></dd><dt>Geometry</dt><dd>${esc(d.geometry)} · ${Number(d.feature_count).toLocaleString()} ${esc(d.coverage||'Manhattan')} records</dd><dt>Time</dt><dd>${esc(d.time_range||'—')}</dd><dt>Last updated</dt><dd>${esc(d.last_updated||'unknown')}</dd>
  <dt>Scoring</dt><dd>${d.used_in_scoring?esc(d.scoring.map(s=>`${dimLabel(ExperienceCore.names[ExperienceCore.keys.indexOf(s.dimension)])} (${s.sub_indicators.join(', ')})`).join('; ')):'Context only — not part of any score'}</dd>${d.note?`<dt>Note</dt><dd>${esc(d.note)}</dd>`:''}<dt>Fields</dt><dd>${esc(d.attributes.join(', '))}</dd></dl></div>`;
}
function renderActiveCount(){
 const n=urbanData.active.size,total=urbanData.catalog?urbanData.catalog.datasets.filter(d=>d.status==='CONNECTED').length:0;
 $('urbanActiveCount').textContent=n?`${n}/${total} on`:'';$('urbanActiveTitle').textContent=`ACTIVE DATASETS: ${n} of ${total}`;
}
// Status kinds: loaded · empty (no nearby features) · loading · error · waiting. Errors are never shown as 0.
function setUrbanStatus(id,text,kind){const a=urbanData.active.get(id);if(!a)return;a.status=text;a.kind=kind;const el=document.querySelector(`[data-ud-status="${id}"]`);if(el){el.textContent=text;el.className='urban-status '+kind;}}
function refreshRepresentations(){document.querySelectorAll('[data-ud-repr]').forEach(el=>{el.textContent=udRepresentation(el.dataset.udRepr);});}

// --- map: render groups in fixed tiers below the routes --------------------------------------------------
// Tier anchors keep the order base map → polygons → lines → environment → trees → POIs → labels → routes → highlight.
const UD_TIERS=['ud-z-polys','ud-z-lines','ud-z-env','ud-z-trees','ud-z-points','ud-z-labels'];
function urbanMapLayerIds(){return state.mapLayersReady?state.map.getStyle().layers.map(l=>l.id).filter(id=>id.startsWith('udg-')):[];}
function addGroupLayers(){
 const m=state.map,T=UrbanStyle.T,op=(base)=>['*',base,['coalesce',['get','_op'],1]];
 const src=(id,opts={})=>m.addSource(id,{type:'geojson',data:emptyFC(),...opts});
 const layer=(def,tier)=>m.addLayer(def,tier);
 src('udg-crime');
 layer({id:'udg-crime-fill',type:'fill',source:'udg-crime',paint:{'fill-color':['interpolate',['linear'],['get','density_per_km2'],0,'#382b38',1000,'#79556b',5000,'#b17a83',15000,'#d3a09b'],'fill-opacity':op(.24)}},'ud-z-env');
 src('udg-context');
 layer({id:'udg-context-fill',type:'fill',source:'udg-context',filter:['==',['geometry-type'],'Polygon'],paint:{'fill-color':['get','_c'],'fill-opacity':op(.16)}},'ud-z-polys');
 layer({id:'udg-context-line',type:'line',source:'udg-context',filter:['in',['geometry-type'],['literal',['Polygon','LineString']]],paint:{'line-color':['get','_c'],'line-width':1,'line-opacity':op(.5)}},'ud-z-lines');
 layer({id:'udg-context-pt',type:'circle',source:'udg-context',filter:['==',['geometry-type'],'Point'],paint:{'circle-color':['get','_c'],'circle-radius':2.5,'circle-opacity':op(.7)}},'ud-z-points');
 // Buildings: a real 3D massing model (fill-extrusion on real PLUTO roof height, not a flat colour block) whose
 // colour still follows the building theme; hairline footprint outlines from street zoom.
 src('udg-buildings');
 layer({id:'udg-buildings-fill',type:'fill-extrusion',source:'udg-buildings',minzoom:T.zoom.neighbourhood-.5,
  paint:{'fill-extrusion-color':T.building.neutral,'fill-extrusion-opacity':T.building.extrusionOpacity, // fill-extrusion-opacity is camera-only in MapLibre (no data expressions, unlike fill-opacity)
   'fill-extrusion-height':['*',0.3048,['coalesce',['to-number',['get',T.building.height.prop]],35]],
   'fill-extrusion-base':0,'fill-extrusion-vertical-gradient':true}},'ud-z-polys');
 layer({id:'udg-buildings-line',type:'line',source:'udg-buildings',minzoom:T.zoom.street,paint:{'line-color':T.building.outline,'line-width':['interpolate',['linear'],['zoom'],15,.3,18,.8],'line-opacity':.55}},'ud-z-polys');
 // Green: parks and gardens as soft fills with fine edges; classification subsets as dashed outlines.
 src('udg-green');
 layer({id:'udg-green-fill',type:'fill',source:'udg-green',filter:['in',['get','ds'],['literal',['parks','community_gardens']]],paint:{'fill-color':T.area.park.fill,'fill-opacity':op(T.area.park.fillOpacity)}},'ud-z-polys');
 layer({id:'udg-green-line',type:'line',source:'udg-green',filter:['in',['get','ds'],['literal',['parks','community_gardens']]],paint:{'line-color':T.area.park.line,'line-width':['interpolate',['linear'],['zoom'],12,.4,17,1.1],'line-opacity':op(T.area.park.lineOpacity)}},'ud-z-polys');
 layer({id:'udg-green-sub',type:'line',source:'udg-green',filter:['in',['get','ds'],['literal',['natural_areas','waterfront_parks']]],paint:{'line-color':['get','_c'],'line-width':1.2,'line-dasharray':[2,1.5],'line-opacity':op(.8)}},'ud-z-polys');
 // Surfaces: sidewalks and plazas as quiet ground textures.
 src('udg-surface');
 layer({id:'udg-surface-fill',type:'fill',source:'udg-surface',paint:{'fill-color':['get','_c'],'fill-opacity':['*',['case',['==',['get','ds'],'sidewalk_surface'],.09,.2],['coalesce',['get','_op'],1]]}},'ud-z-polys');
 layer({id:'udg-surface-line',type:'line',source:'udg-surface',filter:['!=',['get','ds'],'sidewalk_surface'],paint:{'line-color':['get','_c'],'line-width':.8,'line-opacity':op(.6)}},'ud-z-polys');
 m.setLayerZoomRange('udg-surface-fill',T.zoom.neighbourhood,24);
 // Heritage: districts as brass dashed hairlines with an italic name; landmark lots as thin brass outlines.
 src('udg-districts');
 layer({id:'udg-districts-fill',type:'fill',source:'udg-districts',paint:{'fill-color':T.area.district.line,'fill-opacity':op(T.area.district.fillOpacity)}},'ud-z-polys');
 layer({id:'udg-districts-line',type:'line',source:'udg-districts',paint:{'line-color':T.area.district.line,'line-width':['interpolate',['linear'],['zoom'],12,.6,17,1.2],'line-dasharray':[3,2],'line-opacity':op(T.area.district.lineOpacity)}},'ud-z-polys');
 layer({id:'udg-districts-label',type:'symbol',source:'udg-districts',minzoom:14,layout:{'text-field':['get','area_name'],'text-font':['Montserrat Regular Italic','Open Sans Italic'],'text-size':10,'text-max-width':10,'text-optional':true},paint:{'text-color':T.cat.heritage,'text-halo-color':T.halo,'text-halo-width':1.2,'text-opacity':.85}},'ud-z-labels');
 src('udg-landmarks');
 layer({id:'udg-landmarks-fill',type:'fill',source:'udg-landmarks',paint:{'fill-color':T.area.landmark.fill,'fill-opacity':op(T.area.landmark.fillOpacity)}},'ud-z-polys');
 layer({id:'udg-landmarks-line',type:'line',source:'udg-landmarks',paint:{'line-color':T.area.landmark.line,'line-width':['interpolate',['linear'],['zoom'],13,.5,17,1.1],'line-opacity':op(T.area.landmark.lineOpacity)}},'ud-z-polys');
 // Lines: one layer per line dataset with its token style (thin, low contrast, never yellow).
 src('udg-lines');
 for(const [id,L] of Object.entries(UrbanStyle.LINES)){
  const paint={'line-color':L.color,'line-width':['interpolate',['linear'],['zoom'],...L.width],'line-opacity':op(L.opacity)};if(L.dash)paint['line-dasharray']=L.dash;
  layer({id:'udg-line-'+id,type:'line',source:'udg-lines',filter:['==',['get','ds'],id],minzoom:L.minzoom||0,layout:{'line-cap':'round','line-join':'round'},paint},'ud-z-lines');
 }
 // Environment: one continuous theme as a density surface; individual complaints only at detail zoom.
 src('udg-noise');
 const E=T.env.noise;
 layer({id:'udg-noise-heat',type:'heatmap',source:'udg-noise',maxzoom:17,paint:{'heatmap-weight':1,'heatmap-intensity':['interpolate',['linear'],['zoom'],...E.intensity],'heatmap-radius':['interpolate',['linear'],['zoom'],...E.radius],
  'heatmap-color':['interpolate',['linear'],['heatmap-density'],...E.ramp.flat()],'heatmap-opacity':['interpolate',['linear'],['zoom'],15.5,E.opacity,17,0]}},'ud-z-env');
 layer({id:'udg-noise-pt',type:'circle',source:'udg-noise',minzoom:16.5,paint:{'circle-color':T.cat.environment,'circle-radius':['interpolate',['linear'],['zoom'],16.5,1.2,19,3],'circle-opacity':op(.5)}},'ud-z-env');
 // Trees: a fine green texture rather than markers.
 src('udg-trees');
 layer({id:'udg-trees-pt',type:'circle',source:'udg-trees',minzoom:12,filter:['!',['has','tree_count']],paint:{'circle-color':T.cat.nature,'circle-radius':T.tree.radius,'circle-opacity':op(T.tree.opacity),'circle-blur':.15}},'ud-z-trees');
 layer({id:'udg-tree-cells',type:'circle',source:'udg-trees',filter:['has','tree_count'],paint:{'circle-color':T.cat.nature,'circle-radius':['interpolate',['linear'],['get','tree_count'],1,.8,100,1.8,1000,4],'circle-opacity':op(.55)}},'ud-z-trees');
 // POIs: one clustered source per data category, so a cluster always means "records of this category".
 for(const c of UD_CATEGORY_IDS){
  const s='udg-pts-'+c,color=T.cat[c],wt=T.weight[c]||{size:1,opacity:1},sized=T.point.stops.map(([z,r])=>[z,r*wt.size]);
  src(s,{cluster:true,clusterRadius:T.cluster.pixelRadius,clusterMaxZoom:T.cluster.maxZoom-1});
  const neutralCat=c==='streets'||c==='buildings';
  layer({id:s+'-cluster',type:'circle',source:s,filter:['has','point_count'],paint:{'circle-color':color,'circle-opacity':neutralCat?T.cluster.opacityNeutral:T.cluster.opacity,'circle-stroke-color':T.stroke,'circle-stroke-width':T.cluster.strokeWidth,'circle-stroke-opacity':.9,'circle-radius':T.cluster.radius}},'ud-z-points');
  layer({id:s+'-count',type:'symbol',source:s,filter:['has','point_count'],minzoom:T.cluster.countMinZoom,layout:{'text-field':['get','point_count_abbreviated'],'text-font':T.label.font,'text-size':8.5,'text-offset':[0,-1.1],'text-allow-overlap':false},paint:{'text-color':T.cluster.countText,'text-halo-color':T.halo,'text-halo-width':1.4}},'ud-z-labels');
  // Zoom must be the outermost expression in MapLibre, so the accessible-entrance ring is a case inside each zoom stop.
  const acc=['==',['get','ds'],'accessible_entrances'],byZoom=(stops,ring)=>['interpolate',['linear'],['zoom'],...stops.flatMap(([z,v],i)=>[z,['case',acc,ring[i],v]])];
  layer({id:s+'-pt',type:'circle',source:s,filter:['!',['has','point_count']],paint:{'circle-color':['case',acc,'rgba(0,0,0,0)',['get','_c']],'circle-radius':byZoom(sized,T.point.ring),
   'circle-opacity':['*',wt.opacity,['coalesce',['get','_op'],1],['case',['has','distance_to_route_m'],['interpolate',['linear'],['get','distance_to_route_m'],0,1,500,.55],1]],
   'circle-stroke-color':['case',acc,['get','_c'],T.stroke],'circle-stroke-width':byZoom(T.point.strokeStops,[1.4,1.4,1.4,1.4]),'circle-stroke-opacity':['coalesce',['get','_op'],1]}},'ud-z-points');
  layer({id:s+'-label',type:'symbol',source:s,minzoom:T.label.minZoom,filter:['all',['!',['has','point_count']],['has','name']],layout:{'text-field':['get','name'],'text-font':T.label.font,'text-size':T.label.size,'text-offset':[0,.9],'text-anchor':'top','text-optional':true,'text-max-width':9,'symbol-sort-key':['coalesce',['get','distance_to_route_m'],999]},
   paint:{'text-color':color,'text-halo-color':T.halo,'text-halo-width':1.2,'text-opacity':.9}},'ud-z-labels');
 }
}
function setupUrbanMap(){
 const m=state.map;
 m.addSource('ud-anchor',{type:'geojson',data:emptyFC()});
 for(const id of UD_TIERS)m.addLayer({id,type:'circle',source:'ud-anchor',layout:{visibility:'none'}},UD_BEFORE);
 addGroupLayers();
 m.addSource('ud-highlight',{type:'geojson',data:emptyFC()});
 m.addLayer({id:'ud-highlight-fill',type:'fill',source:'ud-highlight',filter:['==',['geometry-type'],'Polygon'],paint:{'fill-color':'#ffffff','fill-opacity':.14}});
 m.addLayer({id:'ud-highlight-line',type:'line',source:'ud-highlight',paint:{'line-color':'#ffffff','line-width':3}});
 m.addLayer({id:'ud-highlight-pt',type:'circle',source:'ud-highlight',filter:['==',['geometry-type'],'Point'],paint:{'circle-radius':9,'circle-color':'rgba(0,0,0,0)','circle-stroke-color':'#ffffff','circle-stroke-width':2}});
 // One handler for every urban layer, resolved at event time: the topmost feature wins (points over lines over fills),
 // and the selected route's segment evidence wins over all data.
 const hitLayers=()=>urbanMapLayerIds().filter(id=>!id.endsWith('-count')&&!id.endsWith('-label')&&!id.startsWith('udg-noise-heat')&&m.getLayoutProperty(id,'visibility')!=='none');
 const topHit=pt=>{const layers=hitLayers();return layers.length?m.queryRenderedFeatures(pt,{layers}).find(f=>f.properties.ds||f.properties.point_count):null;};
 m.on('click',e=>{if(state.pick||(typeof exploreMap!=='undefined'&&exploreMap.active)||m.queryRenderedFeatures(e.point,{layers:['route-edge-hit']}).length)return;const f=topHit(e.point);if(!f)return;
  if(f.properties.point_count){m.getSource(f.source).getClusterExpansionZoom(f.properties.cluster_id).then(z=>m.easeTo({center:f.geometry.coordinates,zoom:z})).catch(()=>{});return;}
  showUrbanFeature(f.properties.ds,f);});
 let hovering=false;
 m.on('mousemove',e=>{if(state.pick||(typeof exploreMap!=='undefined'&&exploreMap.active))return;const on=!!topHit(e.point);if(on!==hovering){hovering=on;m.getCanvas().style.cursor=on?'pointer':'';}});
 m.on('moveend',urbanViewMoved);
 m.on('zoomend',()=>{refreshRepresentations();renderUrbanLegend();});
 applyBuildingTheme();applyEnvTheme();refreshUrbanLayers();
}
let udComposeFrame=0;
// Batched to one compose per frame (a timer where there is no frame loop, e.g. tests).
const udRaf=typeof requestAnimationFrame==='function'?[f=>requestAnimationFrame(f),h=>cancelAnimationFrame(h)]:[f=>setTimeout(f,16),h=>clearTimeout(h)];
function scheduleUrbanCompose(){udRaf[1](udComposeFrame);udComposeFrame=udRaf[0](composeUrbanGroups);}
/** Build each render group's data from the enabled datasets' records (each tagged with its dataset, colour, opacity). */
function composeUrbanGroups(){
 if(!state.mapLayersReady||!urbanData.catalog){renderUrbanLegend();return;}
 const groups={};
 const tag=(id,f)=>({...f,properties:{...f.properties,ds:id,_c:udColor(id),_op:urbanData.active.get(id).opacity}});
 const seenBuildings=new Set(),lots=new Map();
 for(const f of urbanData.drawn.get('land_use')?.values()||[])lots.set(String(f.properties.feature_id),f.properties.landuse_name);
 // General datasets (e.g. all activity places) go last and only add records no specific dataset already draws.
 const GENERAL=new Set(['activity_places']),placed=new Set();
 const order=[...urbanData.active.keys()].sort((a,b)=>GENERAL.has(a)-GENERAL.has(b));
 for(const id of order){
  if(id==='street_trees'&&urbanData.active.has('citywide_tree_inventory')&&urbanData.drawn.get('citywide_tree_inventory')?.size)continue;
  const newer={subway_stations:'citywide_mta_stations',subway_entrances:'citywide_mta_entrances',bus_stops:'citywide_mta_bus_stops'}[id];
  if(newer&&urbanData.active.has(newer)&&urbanData.drawn.get(newer)?.size)continue;
  const d=urbanData.byId.get(id),feats=urbanData.drawn.get(id);if(!feats)continue;
  const g=udGroup(d);
  if(g==='buildings'){
   if(id==='land_use')continue;  // tax-lot points feed the land-use building theme; they are not drawn as dots
   for(const f of feats.values()){const fid=f.properties.feature_id;if(seenBuildings.has(fid))continue;seenBuildings.add(fid);
    const t=tag(urbanData.buildingTheme==='height'&&urbanData.active.has('building_heights')?'building_heights':urbanData.buildingTheme==='age'&&urbanData.active.has('building_age')?'building_age':'building_footprints',f);
    const lu=lots.get(String(f.properties.base_bbl).split('.')[0]);if(lu)t.properties.landuse_name=lu;
    (groups.buildings=groups.buildings||[]).push(t);}
   continue;
  }
  const list=groups[g]=groups[g]||[];
  for(const f of feats.values()){const key=g.startsWith('pts-')&&id!=='accessible_entrances'?f.properties.feature_id:null;
   if(key&&GENERAL.has(id)&&placed.has(key))continue;if(key)placed.add(key);list.push(tag(id,f));}
 }
 const all=['buildings','green','surface','districts','landmarks','lines','noise','trees','crime','context',...UD_CATEGORY_IDS.map(c=>'pts-'+c)];
 for(const g of all)state.map.getSource('udg-'+g)?.setData({type:'FeatureCollection',features:groups[g]||[]});
 renderUrbanLegend();
}
function applyBuildingTheme(){
 if(!state.mapLayersReady)return;const B=UrbanStyle.T.building,t=urbanData.buildingTheme,light=document.documentElement.dataset.mapTheme==='light';
 // daylight map: the same height ramp, light to mid grey (the dark ramp would read as holes in a light city)
 const hStops=light?B.heightLight:B.height.stops,neutral=light?B.neutralLight:B.neutral;
 const color=t==='height'?UrbanStyle.rampExpr(B.height.prop,hStops):t==='landuse'?UrbanStyle.categoricalExpr(B.landuse.prop,B.landuse.classes,B.landuse.other):t==='age'?['case',['has',B.age.prop],UrbanStyle.rampExpr(B.age.prop,B.age.stops),neutral]:neutral;
 state.map.setPaintProperty('udg-buildings-fill','fill-extrusion-color',color);
 if(t==='landuse'&&!urbanData.active.has('land_use'))toast('Land use theme needs the Land use (tax lots) dataset; it has been switched on.');
 if(t==='landuse'&&!urbanData.active.has('land_use'))toggleUrbanDataset('land_use',true);
 refreshRepresentations();scheduleUrbanCompose();
}
function applyEnvTheme(){
 if(!state.mapLayersReady)return;const on=urbanData.envTheme==='noise';
 setMapLayerVisible('udg-noise-heat',on&&mapExperience.mode!=='explore');
 refreshRepresentations();renderUrbanLegend();
}
function setUrbanOpacity(id,op){const a=urbanData.active.get(id);if(!a)return;a.opacity=op;scheduleUrbanCompose();}
function toggleUrbanDataset(id,on,quiet){
 const d=urbanData.byId.get(id);if(!d||d.status!=='CONNECTED')return;
 if(on){if(!urbanData.active.has(id)){urbanData.active.set(id,{opacity:1,status:'Waiting',kind:'waiting',seq:0});}loadUrbanDataset(id);}
 else{urbanData.active.delete(id);urbanData.drawn.delete(id);scheduleUrbanCompose();}
 if(!quiet)renderUrbanPanel();
}
function setUrbanCategory(cat,on){for(const d of urbanData.catalog.datasets)if(d.status==='CONNECTED'&&d.categories.includes(cat))toggleUrbanDataset(d.id,on,true);renderUrbanPanel();}
function setAllUrban(on){for(const d of urbanData.catalog.datasets)if(d.status==='CONNECTED')toggleUrbanDataset(d.id,on,true);if(!on)clearUrbanHighlight();renderUrbanPanel();}
function clearUrbanLayers(){setAllUrban(false);}
async function loadUrbanDataset(id){
 const a=urbanData.active.get(id),d=urbanData.byId.get(id);if(!a)return;const seq=++a.seq;
 const done=(fc,text,kind)=>{if(seq!==a.seq||!urbanData.active.has(id))return;urbanData.drawn.set(id,new Map(fc.features.map(f=>[String(f.properties.feature_id),f])));setUrbanStatus(id,text,kind);scheduleUrbanCompose();};
 try{
  if(d.remote&&d.remote!=='crime'){
   if(!state.mapReady){done(emptyFC(),'Map not ready','waiting');return;}
   const b=flatMapBounds(state.map),coords=!urbanViewScope()?routeCoords():null,box=coords?UrbanGeo.lineBox(coords.map(UrbanGeo.xy),urbanData.corridor):null;
   const ll=box?[box[0]/urbanData.catalog.projection.mx,box[1]/urbanData.catalog.projection.my,box[2]/urbanData.catalog.projection.mx,box[3]/urbanData.catalog.projection.my]:[b.getWest(),b.getSouth(),b.getEast(),b.getNorth()];
   ll[0]=Math.max(-74.3,ll[0]);ll[1]=Math.max(40.45,ll[1]);ll[2]=Math.min(-73.68,ll[2]);ll[3]=Math.min(40.95,ll[3]);
   if(ll[0]>=ll[2]||ll[1]>=ll[3]){done(emptyFC(),'Outside NYC snapshot','empty');return;}
   const params=new URLSearchParams({bbox:ll.join(','),zoom:state.map.getZoom()});
   if(d.remote.startsWith('context:'))params.set('category',d.remote.slice(8));
   const fc=await streetwiseJson('/api/urban/'+(d.remote==='trees'?'trees':'context')+'?'+params,{signal:AbortSignal.timeout(20000)});
   if(coords)fc.features=UrbanGeo.alongLine(fc.features,coords,urbanData.corridor).map(h=>h.feature);
   done(fc,`${fc.features.length} ${d.remote==='trees'&&state.map.getZoom()<16?'inventory cells':'features'}${fc.metadata.truncated?' · truncated: zoom in':''}`,'loaded');return;
  }
  if(d.remote==='crime'){
   if(!state.mapReady){done(emptyFC(),'Map not ready','waiting');return;}
   const meta=await crimeMetadata(),p={...(planner.routeResponse?.independent_preferences_used?.crime||planner.crime||{}),...(urbanData.crimeFilter||{})},b=flatMapBounds(state.map),coords=!urbanViewScope()?routeCoords():null;
   const box=coords?UrbanGeo.lineBox(coords.map(UrbanGeo.xy),urbanData.corridor):null;
   const ll=box?[box[0]/urbanData.catalog.projection.mx,box[1]/urbanData.catalog.projection.my,box[2]/urbanData.catalog.projection.mx,box[3]/urbanData.catalog.projection.my]:[b.getWest(),b.getSouth(),b.getEast(),b.getNorth()];
   ll[0]=Math.max(-74.3,ll[0]);ll[1]=Math.max(40.45,ll[1]);ll[2]=Math.min(-73.68,ll[2]);ll[3]=Math.min(40.95,ll[3]);
   if(ll[0]>=ll[2]||ll[1]>=ll[3]){done(emptyFC(),'Outside NYC snapshot','empty');return;}
   const params=new URLSearchParams({bbox:ll.join(','),zoom:state.map.getZoom(),from:p.from||meta.default_start,to:p.to||meta.available_end_exclusive});
   const types=urbanData.crimeFilter?.offense_types||p.offense_types;
   const codes=types?Object.entries(meta.offenses).filter(([k,names])=>types.some(t=>names.includes(t))).map(([k])=>k):p.offense_codes;
   if(codes?.length)params.set('offense_codes',codes.join(','));
   const fc=await streetwiseJson('/api/urban/crime?'+params,{signal:AbortSignal.timeout(20000)});
   if(coords)fc.features=UrbanGeo.alongLine(fc.features,coords,urbanData.corridor).map(h=>h.feature);
   done(fc,`${fc.features.length} density cells · ${fc.metadata.from}–${fc.metadata.to_exclusive} (end exclusive)${fc.metadata.truncated?' · zoom in: truncated':''}`,'loaded');return;
  }
  if(!urbanViewScope()){
   const coords=routeCoords();
   setUrbanStatus(id,'Loading…','loading');
   const hits=await datasetAlong(d,coords,urbanData.corridor);
   done({type:'FeatureCollection',features:hits.map(h=>({...h.feature,properties:{...h.feature.properties,distance_to_route_m:Math.round(h.distance*10)/10}}))},
    hits.length?`Loaded · ${hits.length.toLocaleString()} within ${urbanData.corridor} m`:`No nearby features within ${urbanData.corridor} m`,hits.length?'loaded':'empty');
  }else{
   if(!state.mapReady){done(emptyFC(),'Map not ready','waiting');return}
   const b=flatMapBounds(state.map),box=UrbanGeo.lonLatBox(b.getWest(),b.getSouth(),b.getEast(),b.getNorth()),n=tileRecordCount(d.tileset,box);
   const tiles=tilesFor(d.tileset,box).length;
   // Sparse datasets load at any zoom (parks, landmarks, stations); dense ones wait for a closer view.
   if(n>1100&&(state.map.getZoom()<d.min_zoom_view&&n>5000||tiles>40)){done(emptyFC(),`Zoom in to load (${n.toLocaleString()} records in view)`,'waiting');return}
   setUrbanStatus(id,'Loading…','loading');
   const feats=(await tileFeatures(d.tileset,box)).filter(f=>UrbanGeo.matchesFilter(f,d.filter)),seen=new Set(),inView=[];
   for(const f of feats){if(seen.has(f.properties.feature_id))continue;seen.add(f.properties.feature_id);const bb=UrbanGeo.bboxOf(UrbanGeo.project(f.geometry));if(bb[0]<=box[2]&&bb[2]>=box[0]&&bb[1]<=box[3]&&bb[3]>=box[1])inView.push(f);}
   done({type:'FeatureCollection',features:inView},inView.length?`Loaded · ${inView.length.toLocaleString()} in view`:'No features in view',inView.length?'loaded':'empty');
  }
 }catch(e){if(seq===a.seq){urbanData.drawn.delete(id);setUrbanStatus(id,'Error: '+e.message,'error');scheduleUrbanCompose();}}
}
/** Along-route scope needs a route; until one is planned the datasets are drawn for the current map view. */
function urbanViewScope(){return urbanData.scope==='view'||!routeCoords();}
function refreshUrbanLayers(){for(const id of urbanData.active.keys())loadUrbanDataset(id);}
/** Route changed (planned, switched or cleared): keep the user's layers, re-filter them, update the summary. */
function urbanLayersRouteChanged(){if(planner.crime&&urbanData.byId.has('reported_complaints')&&!urbanData.active.has('reported_complaints'))toggleUrbanDataset('reported_complaints',true,true);if(urbanData.scope==='route')refreshUrbanLayers();renderUrbanLegend();renderRouteUrbanData();closeUrbanInspector();}
// Two fixes for the same measured bug (a single pitched camera move fired 490+ tile requests; not route
// computation itself, which is ~9ms server-side, and not the 3D buildings layer's own render cost):
// 1. loadUrbanDataset's bbox now comes from flatMapBounds(), not map.getBounds() — a pitched camera's real bounds
//    cover ~3x the ground area of the same flat view at the same center/zoom (measured directly) because a
//    tilted camera sees toward the horizon, and every active dataset re-querying that inflated area on every
//    camera move was most of the storm.
// 2. Live navigation hides every udg-* layer (setDataLayersForNav in nav-ui.js) but never touched
//    urbanData.active, so this kept firing on every nav-mode camera move anyway, for a viewport nobody could
//    see. Skipped outright below — there is nothing to refresh for a hidden layer.
function urbanViewMoved(){if(!urbanViewScope()||!urbanData.active.size||document.body.classList.contains('nav-mode'))return;clearTimeout(urbanData.viewTimer);urbanData.viewTimer=setTimeout(refreshUrbanLayers,400);}

// --- legend: only what is visible now -------------------------------------------------------------------
function renderUrbanLegend(){
 const box=$('udLegend');if(!box||!urbanData.catalog)return;
 const T=UrbanStyle.T,z=state.mapReady?state.map.getZoom():12,rows=[];
 const sw=(c,kind='point')=>`<i class="lg-sw ${kind}" style="--c:${c}"></i>`;
 if(state.routes.length){rows.push(`<div class="lg-row">${sw(T.route.selected,'route')}<span>Selected route</span></div>`);if(state.display.routes&&state.routes.length>1)rows.push(`<div class="lg-row">${sw(T.route.alt,'alt')}<span>Alternative routes</span></div>`);}
 const has=id=>urbanData.active.has(id)&&(urbanData.drawn.get(id)?.size||0)>0;
 if(['building_footprints','building_heights','building_age'].some(has)&&z>=T.zoom.neighbourhood-.5){
  const t=urbanData.buildingTheme,B=T.building;
  if(t==='height'||t==='age'){const R=B[t];rows.push(`<div class="lg-block"><span>Buildings · ${t==='height'?'roof height':'year built'}</span><i class="lg-ramp" style="background:linear-gradient(90deg,${R.stops.map(s=>s[1]).join(',')})"></i><small>${R.stops[0][0]} – ${R.stops.at(-1)[0]}${R.unit==='ft'?' ft':''}</small></div>`);}
  else if(t==='landuse')rows.push(`<div class="lg-block"><span>Buildings · land use (PLUTO lot)</span><div class="lg-classes">${B.landuse.classes.slice(0,11).map(([n,c])=>`<span>${sw(c,'fill')}${esc(n)}</span>`).join('')}</div></div>`);
  else rows.push(`<div class="lg-row">${sw(B.neutral,'fill')}<span>Buildings</span></div>`);
 }
 if(has('parks')||has('community_gardens'))rows.push(`<div class="lg-row">${sw(T.area.park.line,'fill')}<span>Parks & gardens</span></div>`);
 if(has('reported_complaints'))rows.push(`<div class="lg-row">${sw('#b17a83','fill')}<span>Historical reported complaint density · not a crime rate</span></div>`);
 if(has('street_trees')&&z>=12)rows.push(`<div class="lg-row">${sw(T.cat.nature,'tiny')}<span>Street trees</span></div>`);
 if(has('historic_districts'))rows.push(`<div class="lg-row">${sw(T.cat.heritage,'dash')}<span>Historic districts</span></div>`);
 if(has('landmarks'))rows.push(`<div class="lg-row">${sw(T.cat.heritage,'fill')}<span>Landmark lots</span></div>`);
 if(has('noise_complaints')&&urbanData.envTheme==='noise'&&z<17)rows.push(`<div class="lg-block"><span>${esc(T.env.noise.label)}</span><i class="lg-ramp" style="background:linear-gradient(90deg,${T.env.noise.ramp.slice(1).map(s=>s[1]).join(',')})"></i><small>low → high · ${esc(T.env.noise.unit)}; reports, not sound levels</small></div>`);
 const lineIds=Object.keys(UrbanStyle.LINES).filter(id=>has(id)&&z>=(UrbanStyle.LINES[id].minzoom||0));
 if(lineIds.length)rows.push(`<div class="lg-row" title="${esc(lineIds.map(id=>urbanData.byId.get(id).name).join(', '))}">${sw(T.cat.streets,'line')}<span>Street, path & transport lines <small>${lineIds.length} datasets</small></span></div>`);
 const chips=UD_CATEGORY_IDS.map(c=>[c,[...urbanData.active.keys()].filter(id=>udGroup(urbanData.byId.get(id))==='pts-'+c&&has(id))]).filter(([,ids])=>ids.length);
 if(chips.length)rows.push(`<div class="lg-block"><span>Places & facilities</span><div class="lg-chips">${chips.map(([c,ids])=>`<span title="${esc(ids.map(id=>urbanData.byId.get(id).name).join(', '))}">${sw(T.cat[c])}${esc(urbanCatName(c).split(/ & |,/)[0])}</span>`).join('')}</div></div>`);
 const notes=[];
 if(z<T.cluster.maxZoom)notes.push(`Rings with a number are clusters: that many records of one category. They split into individual records from z${T.cluster.maxZoom}.`);
 if(z<T.zoom.street)notes.push(`Sidewalks, crosswalks and building edges are generalised away until z${T.zoom.street}.`);
 if(urbanData.scope==='route'&&state.routes.length)notes.push(`Records within ${urbanData.corridor} m of the selected route; farther records are drawn lighter.`);
 if(!state.routes.length&&urbanData.scope==='route')notes.push('Showing the current map view; plan a route to focus the datasets along it.');
 box.querySelector('.lg-body').innerHTML=rows.join('')+(notes.length?`<p class="lg-note">${notes.map(esc).join(' ')}</p>`:'');
}

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
function setupUrbanControls(){
 const panel=$('urbanLayers');
 panel.addEventListener('toggle',()=>{if(panel.open)openUrbanPanel();});
 document.querySelectorAll('[name="urbanScope"]').forEach(r=>r.addEventListener('change',()=>{urbanData.scope=r.value;refreshUrbanLayers();renderUrbanLegend();}));
 $('urbanCorridor').addEventListener('change',e=>{urbanData.corridor=Number(e.target.value);refreshUrbanLayers();renderRouteUrbanData();});
 $('urbanSearch').addEventListener('input',e=>{urbanData.search=e.target.value;renderUrbanPanel();});
 $('urbanAllOn').addEventListener('click',()=>setAllUrban(true));
 $('urbanAllOff').addEventListener('click',()=>setAllUrban(false));
 $('urbanSettings').addEventListener('click',()=>{urbanData.settings=!urbanData.settings;$('urbanSettings').setAttribute('aria-pressed',String(urbanData.settings));renderUrbanPanel();});
 $('buildingTheme').innerHTML=BUILDING_THEMES.map(([v,n])=>`<option value="${v}">${esc(n)}</option>`).join('');$('buildingTheme').value=urbanData.buildingTheme;
 $('buildingTheme').addEventListener('change',e=>{urbanData.buildingTheme=e.target.value;applyBuildingTheme();});
 $('envTheme').innerHTML=ENV_THEMES.map(([v,n,ds])=>`<option value="${v}" ${v==='none'||ds?'':'disabled'}>${esc(n)}${v==='none'||ds?'':' — not connected'}</option>`).join('');$('envTheme').value=urbanData.envTheme;
 $('envTheme').addEventListener('change',e=>{urbanData.envTheme=e.target.value;applyEnvTheme();});
 $('udLegendToggle').addEventListener('click',()=>{const open=$('udLegend').classList.toggle('collapsed')===false;$('udLegendToggle').setAttribute('aria-expanded',String(open));});
 document.addEventListener('keydown',e=>{if(e.key==='Escape')closeUrbanInspector();});
 // First visit: every connected dataset is enabled; the drawer stays closed and categories collapsed.
 // Applied by whichever catalog load succeeds first, so a failed first fetch does not leave everything off.
 ensureUrbanCatalog().catch(e=>{$('urbanActiveCount').textContent='catalog error';console.warn('Urban data catalog:',e);});
}
