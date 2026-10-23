'use strict';
/* Navigate · Urban Data Layers. Real NYC / OSM records grouped by the 12 experience dimensions, drawn Along Route
   (records within a display distance of the selected route's real geometry) or for the Current View.
   Layer metadata comes from data/layers/registry.json via /api/layers; nothing here is simulated.
   Display distance filters what is drawn only; experience scores are computed elsewhere and never change. */
const URBAN_COLORS={landmarks:'#f6ac6e',street_trees:'#8fdc86',parks:'#4caf6a',cultural_venues:'#c39bff',public_art:'#ff8fc8',scenic_points:'#7fd6ff',
 noise_complaints:'#ff7a6b',sidewalk_surface:'#9fb3ba',seating:'#e7d27a',activity_places:'#ffc861',food_drink:'#ff9f5a',retail:'#f2d36b',intersections:'#d6e6e1',
 osm_sidewalks:'#7bc8d6',osm_crosswalks:'#ffffff',osm_paths:'#b9e28c',pedestrian_crashes:'#ff4f6a',expressways:'#c4776b',subway_entrances:'#4fb4ff'};
const urbanLayers={registry:null,loading:null,active:new Map(),scope:'route',distance:'auto',overlay:-1,focusDim:null,search:'',viewTimer:0,seq:0};
const URBAN_BEFORE='nav-score-overlay';
function urbanDimLabel(key){const i=ExperienceCore.keys.indexOf(key);return i<0?key:`${String(i+1).padStart(2,'0')} ${dimLabel(ExperienceCore.names[i])}`;}
async function ensureUrbanRegistry(){
 if(urbanLayers.registry)return urbanLayers.registry;
 urbanLayers.loading=urbanLayers.loading||(async()=>{const res=await fetch('/api/layers',{signal:AbortSignal.timeout(15000)});const j=await res.json();if(!res.ok)throw new Error(j.error||'HTTP '+res.status);return j;})();
 try{urbanLayers.registry=await urbanLayers.loading;}catch(e){urbanLayers.loading=null;throw e;}
 return urbanLayers.registry;
}
function urbanLayerList(){return Object.values(urbanLayers.registry?.layers||{});}
function layersForDim(key){
 const order={scoring:0,context:1,unavailable:2};
 return urbanLayerList().map(l=>({l,link:l.dims.find(d=>d.dimension===key)})).filter(x=>x.link)
  .sort((a,b)=>(order[a.l.status==='available'?a.link.role:'unavailable']-order[b.l.status==='available'?b.link.role:'unavailable'])||a.l.name.localeCompare(b.l.name));
}
async function openUrbanPanel(){
 const root=$('urbanDims');
 if(location.protocol==='file:'){root.innerHTML='<p class="urban-note">Urban data layers are served by server.py; start it and open http://127.0.0.1:8080.</p>';return}
 try{await ensureUrbanRegistry();renderUrbanPanel();}
 catch(e){root.innerHTML=`<p class="urban-note">Urban data layers unavailable: ${esc(e.message)}</p>`;}
}
function renderUrbanPanel(){
 const reg=urbanLayers.registry;if(!reg)return;
 const q=urbanLayers.search.trim().toLowerCase();
 const match=(l,key)=>!q||[l.name,l.dataset,l.source,urbanDimLabel(key)].some(t=>String(t||'').toLowerCase().includes(q));
 $('urbanDims').innerHTML=reg.dimension_order.map(key=>{
  const rows=layersForDim(key).filter(x=>match(x.l,key));if(!rows.length)return '';
  const on=rows.filter(x=>urbanLayers.active.has(x.l.id)).length;
  return `<details class="urban-dim" data-dim="${key}" ${q||urbanLayers.focusDim===key?'open':''}><summary><span>${esc(urbanDimLabel(key))}</span><small>${rows.filter(x=>x.l.status==='available').length} layers${on?` · ${on} on`:''}</small></summary>${rows.map(({l,link})=>urbanLayerRow(l,link,key)).join('')}</details>`;
 }).join('')||'<p class="urban-note">No layer matches this search.</p>';
 $('urbanDims').querySelectorAll('.urban-dim').forEach(d=>d.addEventListener('toggle',()=>{if(d.open)urbanLayers.focusDim=d.dataset.dim;}));
 $('urbanDims').querySelectorAll('[data-layer-toggle]').forEach(c=>c.addEventListener('change',()=>{urbanLayers.focusDim=c.dataset.dim;toggleUrbanLayer(c.dataset.layerToggle,c.checked);}));
 $('urbanDims').querySelectorAll('[data-layer-opacity]').forEach(r=>r.addEventListener('input',()=>setUrbanOpacity(r.dataset.layerOpacity,r.value/100)));
 $('urbanDims').querySelectorAll('[data-layer-info]').forEach(b=>b.addEventListener('click',()=>{const box=b.closest('.urban-layer').querySelector('.urban-meta');box.classList.toggle('hidden');b.setAttribute('aria-expanded',String(!box.classList.contains('hidden')));}));
 $('urbanActiveCount').textContent=urbanLayers.active.size?`${urbanLayers.active.size} on`:'';
}
function urbanLayerRow(l,link,key){
 if(l.status!=='available')return `<div class="urban-layer unavailable"><div class="urban-row"><input type="checkbox" disabled aria-label="${esc(l.name)} unavailable"><span class="urban-swatch none"></span><span class="urban-name">${esc(l.name)}</span><span class="urban-badge off">Unavailable</span></div><p class="urban-reason">${esc(l.reason)}</p></div>`;
 const a=urbanLayers.active.get(l.id),role=link.role;
 const subs=link.sub_indicators.map(k=>urbanLayers.registry.indicators[key]?.find(x=>x.key===k)?.label||k);
 return `<div class="urban-layer"><div class="urban-row"><input type="checkbox" data-layer-toggle="${l.id}" data-dim="${key}" ${a?'checked':''} aria-label="Show ${esc(l.name)}"><span class="urban-swatch ${l.geometry.toLowerCase()}" style="--c:${URBAN_COLORS[l.id]||'#ccc'}"></span><span class="urban-name">${esc(l.name)}</span><span class="urban-badge ${role}">${role==='scoring'?'Scoring':'Context only'}</span><button type="button" class="urban-info" data-layer-info aria-expanded="false" title="Dataset details">i</button></div>
  ${a?`<div class="urban-live"><label>Opacity <input type="range" min="15" max="100" value="${Math.round(a.opacity*100)}" data-layer-opacity="${l.id}"></label><span class="urban-status">${esc(a.status||'')}</span></div>`:''}
  <dl class="urban-meta hidden"><dt>Layer ID</dt><dd>${esc(l.id)}</dd><dt>Dataset</dt><dd>${esc(l.dataset)}</dd><dt>Source</dt><dd><a href="${esc(l.url)}" target="_blank" rel="noopener noreferrer">${esc(l.source)}</a></dd><dt>Geometry</dt><dd>${esc(l.geometry)} · ${Number(l.feature_count||0).toLocaleString()} Manhattan features</dd>
  <dt>Dimension link</dt><dd>${l.dims.map(d=>`${esc(urbanDimLabel(d.dimension))}: ${d.role==='scoring'?'scoring':'context only'}`).join('; ')}</dd>${role==='scoring'?`<dt>Sub-indicator</dt><dd>${esc(subs.join(', '))}</dd><dt>Chain</dt><dd>${esc(l.name)} → ${esc(subs[0]||'')} → ${esc(dimLabel(ExperienceCore.names[ExperienceCore.keys.indexOf(key)]))} score → route score</dd>`:'<dt>Scoring</dt><dd>Not part of any score (context only)</dd>'}
  <dt>Processing</dt><dd>${esc(l.processing)}</dd><dt>Distances</dt><dd>Scoring range ${l.scoring_distance_m==null?'—':l.scoring_distance_m+' m'} · default display ${l.display_distance_m} m</dd><dt>Attributes</dt><dd>${esc(l.attributes.join(', '))}</dd><dt>Updated</dt><dd>${esc(l.updated||'unknown')} (retrieved ${esc(l.retrieved)})</dd></dl></div>`;
}
// --- map layers ----------------------------------------------------------------------------------------
function urbanSourceId(lid){return 'ul-'+lid;}
function urbanMapLayerIds(){const ids=[];for(const lid of urbanLayers.active.keys())ids.push(...urbanStyleIds(lid));return ids;}
function urbanStyleIds(lid){const g=urbanLayers.registry.layers[lid].geometry,s=urbanSourceId(lid);return g==='Point'?[s+'-cluster',s+'-pt']:g==='LineString'?[s+'-line']:[s+'-fill',s+'-outline'];}
function addUrbanMapLayer(lid){
 const m=state.map,l=urbanLayers.registry.layers[lid],s=urbanSourceId(lid),c=URBAN_COLORS[lid]||'#ccc',op=urbanLayers.active.get(lid).opacity;
 if(m.getSource(s))return;
 if(l.geometry==='Point'){
  // Dense point data is clustered so the route stays readable; clusters split as you zoom in.
  m.addSource(s,{type:'geojson',data:emptyFC(),cluster:true,clusterRadius:36,clusterMaxZoom:16,promoteId:'feature_id'});
  m.addLayer({id:s+'-cluster',type:'circle',source:s,filter:['has','point_count'],paint:{'circle-color':c,'circle-opacity':op*.45,'circle-stroke-color':c,'circle-stroke-width':1.2,'circle-radius':['interpolate',['linear'],['get','point_count'],2,8,50,14,500,22]}},URBAN_BEFORE);
  m.addLayer({id:s+'-pt',type:'circle',source:s,filter:['!',['has','point_count']],paint:{'circle-color':c,'circle-opacity':op,'circle-radius':['interpolate',['linear'],['zoom'],12,2.5,16,5],'circle-stroke-color':'#0b1a1d','circle-stroke-width':.8}},URBAN_BEFORE);
 }else if(l.geometry==='LineString'){
  m.addSource(s,{type:'geojson',data:emptyFC(),promoteId:'feature_id'});
  m.addLayer({id:s+'-line',type:'line',source:s,paint:{'line-color':c,'line-opacity':op,'line-width':['interpolate',['linear'],['zoom'],12,1,16,3]}},URBAN_BEFORE);
 }else{
  m.addSource(s,{type:'geojson',data:emptyFC(),promoteId:'feature_id'});
  m.addLayer({id:s+'-fill',type:'fill',source:s,paint:{'fill-color':c,'fill-opacity':op*.28}},URBAN_BEFORE);
  m.addLayer({id:s+'-outline',type:'line',source:s,paint:{'line-color':c,'line-opacity':op,'line-width':1.1}},URBAN_BEFORE);
 }
 for(const id of urbanStyleIds(lid)){
  m.on('click',id,e=>{if(state.pick||m.queryRenderedFeatures(e.point,{layers:['route-edge-hit']}).length)return;const f=e.features?.[0];if(!f)return;
   if(f.properties.point_count){m.getSource(s).getClusterExpansionZoom(f.properties.cluster_id).then(z=>m.easeTo({center:f.geometry.coordinates,zoom:z})).catch(()=>{});return;}
   e.originalEvent.__urbanHandled=true;showUrbanFeature(lid,f,e.lngLat);});
  m.on('mouseenter',id,()=>{if(!state.pick)m.getCanvas().style.cursor='pointer';});m.on('mouseleave',id,()=>{if(!state.pick)m.getCanvas().style.cursor='';});
 }
}
function removeUrbanMapLayer(lid){const m=state.map,s=urbanSourceId(lid);if(!m)return;for(const id of urbanStyleIds(lid))if(m.getLayer(id))m.removeLayer(id);if(m.getSource(s))m.removeSource(s);}
function setUrbanOpacity(lid,op){
 const a=urbanLayers.active.get(lid);if(!a||!state.mapLayersReady)return;a.opacity=op;const s=urbanSourceId(lid),m=state.map;
 if(m.getLayer(s+'-pt'))m.setPaintProperty(s+'-pt','circle-opacity',op);if(m.getLayer(s+'-cluster'))m.setPaintProperty(s+'-cluster','circle-opacity',op*.45);
 if(m.getLayer(s+'-line'))m.setPaintProperty(s+'-line','line-opacity',op);if(m.getLayer(s+'-fill'))m.setPaintProperty(s+'-fill','fill-opacity',op*.28);if(m.getLayer(s+'-outline'))m.setPaintProperty(s+'-outline','line-opacity',op);
}
function toggleUrbanLayer(lid,on){
 if(on){urbanLayers.active.set(lid,{opacity:.85,status:'Loading…'});if(state.mapLayersReady)addUrbanMapLayer(lid);loadUrbanLayer(lid);}
 else{urbanLayers.active.delete(lid);removeUrbanMapLayer(lid);}
 renderUrbanPanel();
}
function clearUrbanLayers(){for(const lid of [...urbanLayers.active.keys()])removeUrbanMapLayer(lid);urbanLayers.active.clear();clearUrbanHighlight();renderUrbanPanel();}
function urbanDistance(lid){return urbanLayers.distance==='auto'?urbanLayers.registry.layers[lid].display_distance_m:Number(urbanLayers.distance);}
async function loadUrbanLayer(lid){
 const a=urbanLayers.active.get(lid);if(!a)return;const seq=a.seq=++urbanLayers.seq;
 const setStatus=t=>{a.status=t;const el=document.querySelector(`[data-layer-opacity="${lid}"]`)?.closest('.urban-live')?.querySelector('.urban-status');if(el)el.textContent=t;};
 let url;
 if(urbanLayers.scope==='route'){
  const r=state.routes.find(x=>x.id===state.activeRoute);
  if(!r){setUrbanData(lid,emptyFC());setStatus('Select a route, or switch to Current View.');return}
  url=`/api/layers/${encodeURIComponent(lid)}?route_id=${encodeURIComponent(r.id)}&distance=${urbanDistance(lid)}`;
 }else{
  if(!state.mapReady){setStatus('Map not ready.');return}
  const b=state.map.getBounds();url=`/api/layers/${encodeURIComponent(lid)}?bbox=${[b.getWest(),b.getSouth(),b.getEast(),b.getNorth()].map(v=>v.toFixed(5)).join(',')}`;
 }
 setStatus('Loading…');
 try{
  const res=await fetch(url,{signal:AbortSignal.timeout(30000)});const j=await res.json();
  if(seq!==a.seq||!urbanLayers.active.has(lid))return;
  if(!res.ok)throw new Error(j.error||'HTTP '+res.status);
  setUrbanData(lid,{type:'FeatureCollection',features:j.features});
  setStatus(j.too_many?j.message:j.scope==='along_route'?`${j.count.toLocaleString()} within ${j.display_distance_m} m of the route`:`${j.count.toLocaleString()} in view`);
 }catch(e){if(seq===a.seq){setUrbanData(lid,emptyFC());setStatus('Unavailable: '+e.message);}}
}
function setUrbanData(lid,fc){if(state.mapLayersReady)state.map.getSource(urbanSourceId(lid))?.setData(fc);}
function refreshUrbanLayers(){for(const lid of urbanLayers.active.keys())loadUrbanLayer(lid);}
// Called by route-client when the selected route changes, and on map moves for Current View.
function urbanLayersRouteChanged(){if(urbanLayers.scope==='route')refreshUrbanLayers();}
function urbanViewMoved(){if(urbanLayers.scope!=='view'||!urbanLayers.active.size)return;clearTimeout(urbanLayers.viewTimer);urbanLayers.viewTimer=setTimeout(refreshUrbanLayers,450);}
// --- feature inspector ---------------------------------------------------------------------------------
function urbanFeatureHtml(lid,props){
 const l=urbanLayers.registry.layers[lid],attrs=l.attributes.filter(k=>props[k]!=null&&props[k]!=='').map(k=>`<dt>${esc(k)}</dt><dd>${/^https?:\/\//.test(String(props[k]))?`<a href="${esc(props[k])}" target="_blank" rel="noopener noreferrer">link</a>`:esc(props[k])}</dd>`).join('');
 const title=props.name||props.LPC_NAME||props.signname||props.genusspecies||props.stop_name||props.complaint_type||props.street_name||l.name;
 return `<strong>Raw Data Feature</strong><dl><dt>Feature ID (${esc(l.dataset)})</dt><dd>${esc(props.feature_id)}</dd><dt>Name / type</dt><dd>${esc(title)}</dd>${attrs}${props.distance_to_route_m!=null?`<dt>Distance to route</dt><dd>${props.distance_to_route_m} m</dd>`:''}<dt>Dataset source</dt><dd><a href="${esc(l.url)}" target="_blank" rel="noopener noreferrer">${esc(l.source)}</a></dd><dt>Last updated</dt><dd>${esc(l.updated||'unknown')}</dd><dt>Role</dt><dd>${esc(l.dims.map(d=>`${urbanDimLabel(d.dimension)} ${d.role==='scoring'?'(scoring)':'(context only)'}`).join('; '))}</dd></dl><small>This is a source record, not a street segment. Street and route segment scores are in the Route Segment Inspector.</small>`;
}
function showUrbanFeature(lid,f,lngLat){
 setUrbanHighlight(f);
 const html=urbanFeatureHtml(lid,f.properties);
 if(state.mapReady&&typeof maplibregl!=='undefined')new maplibregl.Popup({maxWidth:'320px'}).setLngLat(lngLat).setHTML(html).addTo(state.map);else $('segmentDetail').innerHTML=html;
}
function setUrbanHighlight(f){if(state.mapLayersReady)state.map.getSource('ul-highlight')?.setData({type:'FeatureCollection',features:[{type:'Feature',properties:{},geometry:f.geometry}]});}
function clearUrbanHighlight(){if(state.mapLayersReady)state.map.getSource('ul-highlight')?.setData(emptyFC());}
// --- experience score overlay (LION segments, the Explore scores) ---------------------------------------
async function setScoreOverlay(index){
 urbanLayers.overlay=index;
 if(!state.mapLayersReady)return;
 const m=state.map;
 if(index<0){m.setLayoutProperty('nav-score-overlay','visibility','none');return}
 try{const data=await loadExploreStreets();m.getSource('nav-score-overlay').setData(data);}catch(e){toast('Experience scores unavailable: '+e.message);return}
 const prop='d'+index;
 m.setPaintProperty('nav-score-overlay','line-color',['case',['==',['typeof',['get',prop]],'number'],['interpolate',['linear'],['get',prop],0,'#1d5b8e',35,'#2389cc',60,'#3fc7e8',78,'#f0d23e',100,'#ffe04a'],'#5d686c']);
 if(mapExperience.mode!=='explore')m.setLayoutProperty('nav-score-overlay','visibility','visible');
 urbanLayers.focusDim=ExperienceCore.keys[index];
}
function setupUrbanMap(){
 const m=state.map;
 // Rendering order: base map → urban data → score overlay → alternative routes → selected route → points → highlight.
 m.addSource('nav-score-overlay',{type:'geojson',data:emptyFC()});
 m.addLayer({id:'nav-score-overlay',type:'line',source:'nav-score-overlay',layout:{visibility:'none','line-cap':'round'},paint:{'line-color':'#5d686c','line-width':['interpolate',['linear'],['zoom'],11,.8,15,2.6],'line-opacity':.7}},'route-alts');
 m.addSource('ul-highlight',{type:'geojson',data:emptyFC()});
 m.addLayer({id:'ul-highlight-fill',type:'fill',source:'ul-highlight',filter:['==',['geometry-type'],'Polygon'],paint:{'fill-color':'#ffffff','fill-opacity':.18}});
 m.addLayer({id:'ul-highlight-line',type:'line',source:'ul-highlight',paint:{'line-color':'#ffffff','line-width':3}});
 m.addLayer({id:'ul-highlight-pt',type:'circle',source:'ul-highlight',filter:['==',['geometry-type'],'Point'],paint:{'circle-radius':9,'circle-color':'rgba(0,0,0,0)','circle-stroke-color':'#ffffff','circle-stroke-width':2.5}});
 for(const lid of urbanLayers.active.keys())addUrbanMapLayer(lid);
 m.on('moveend',urbanViewMoved);
}
function setupUrbanControls(){
 const panel=$('urbanLayers');
 panel.addEventListener('toggle',()=>{if(panel.open)openUrbanPanel();});
 document.querySelectorAll('[name="urbanScope"]').forEach(r=>r.addEventListener('change',()=>{urbanLayers.scope=r.value;refreshUrbanLayers();}));
 $('urbanDistance').addEventListener('change',e=>{urbanLayers.distance=e.target.value;if(urbanLayers.scope==='route')refreshUrbanLayers();});
 $('urbanSearch').addEventListener('input',e=>{urbanLayers.search=e.target.value;renderUrbanPanel();});
 $('urbanClear').addEventListener('click',clearUrbanLayers);
 $('scoreOverlay').innerHTML='<option value="-1">Off</option>'+ExperienceCore.names.map((n,i)=>`<option value="${i}">${String(i+1).padStart(2,'0')} ${esc(dimLabel(n))}</option>`).join('');
 $('scoreOverlay').addEventListener('change',e=>setScoreOverlay(Number(e.target.value)));
}
