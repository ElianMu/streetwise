'use strict';
const mapExperience={mode:'navigate',view:'evidence',visible:true,coverage:true,sections:[],bbox:null,source:'No analyzed area',retrieved:null,busy:false,request:0,queue:0};
const dimensionDefinitions=[
 'LPC individual-landmark parcel proximity. Presence is not architectural quality; historic districts are not included.',
 'Living 2015 census street trees within 75 m. Not canopy, shade, parks or present-day vegetation.',
 'Cultural venue access; venue inventory and opening-hours processing pending.',
 'Quietness requires time-matched noise observations and an inverse exposure model; unavailable.',
 'Comfort requires sidewalk width, crowding and obstructions; unavailable.',
 'Activity intensity, not universal desirability. User direction must distinguish lively from less busy. Data unavailable.',
 'Food and retail access needs verified business inventory and opening times; unavailable.',
 'Views and visual experience need visibility/perception validation; unavailable.',
 'Pedestrian connectivity, grade and crossing model missing. Street geometry alone is not a score.',
 'Accessibility and safety need barrier and hazard evidence; no safety guarantee.',
 'Air/heat exposure model missing. Forecast weather is context only.',
 'Transit entrance access and service frequency processing pending.'
];
const fc=features=>({type:'FeatureCollection',features});
function experienceFeatures(){return mapExperience.sections;}
function selectedEvidenceKey(){return state.dimension==='Nature'?'nature':state.dimension==='Architecture'?'architecture':null;}
function queueMapReplan(){clearTimeout(mapExperience.queue);mapExperience.queue=setTimeout(()=>{if(state.routingBusy){queueMapReplan();return;}generateRoutes(null,true);},650);}
function chooseIntentLayer(){const preferred=['Nature','Architecture'].filter(n=>planner.origins[n]!=='default').sort((a,b)=>planner.weights[b]-planner.weights[a]);if(preferred.length){state.dimension=preferred[0];$('experienceDimension').value=state.dimension;updateLegend();}}
function boxFeature(b,label){return {type:'Feature',properties:{label},geometry:{type:'Polygon',coordinates:[[[b[0],b[1]],[b[2],b[1]],[b[2],b[3]],[b[0],b[3]],[b[0],b[1]]]]}};}
function setupExperienceMap(){
 const m=state.map;
 m.addSource('experience-sections',{type:'geojson',data:fc([])});m.addSource('experience-coverage',{type:'geojson',data:fc([])});
 m.addLayer({id:'experience-coverage-line',source:'experience-coverage',type:'line',paint:{'line-color':'#c9bd8b','line-width':1.5,'line-dasharray':[3,3]}},'route-alts');
 // One independent source-backed layer per dimension; absent metrics remain empty/No Data.
 ExperienceCore.keys.forEach((key,i)=>m.addLayer({id:'experience-'+key,source:'experience-sections',type:'line',layout:{visibility:'none'},paint:{'line-color':'#69777d','line-width':5,'line-opacity':.8}},'route-alts'));
 m.addLayer({id:'experience-hit',source:'experience-sections',type:'line',paint:{'line-color':'#ffffff','line-width':15,'line-opacity':0}},'route-alts');
 m.on('click','experience-hit',e=>{if(state.pick||!mapExperience.visible)return;const f=e.features?.[0];if(f)showSectionPopup(f,e.lngLat);});
 m.on('mouseenter','experience-hit',()=>{if(!state.pick)m.getCanvas().style.cursor='pointer';});
 m.on('mouseleave','experience-hit',()=>{if(!state.pick)m.getCanvas().style.cursor='';});
 for(const layer of ['tree-points','landmark-fill'])m.on('click',layer,e=>{if(state.pick)return;const p=e.features?.[0]?.properties;if(!p)return;new maplibregl.Popup({maxWidth:'280px'}).setLngLat(e.lngLat).setHTML(`<strong>${layer==='tree-points'?'2015 tree record':'LPC parcel record'}</strong><dl>${Object.entries(p).slice(0,12).map(([k,v])=>`<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join('')}</dl><small>Source service: ${layer==='tree-points'?'NYC Open Data tree census':'LPC individual-landmark mirror; observation year unspecified'}</small>`).addTo(m);});
 setupExploreMap();syncExperienceMap();
}
function syncExperienceMap(){
 renderRouteSummary();renderExperienceLegend();
 if(!state.mapLayersReady)return;
 state.map.getSource('experience-sections')?.setData(fc(experienceFeatures()));
 const boxes=[];if(mapExperience.bbox)boxes.push(boxFeature(mapExperience.bbox,'Analyzed pilot retrieval extent (not borough boundary)'));
 state.map.getSource('experience-coverage')?.setData(fc(boxes));
 updateExperienceStyles();renderExperienceLegend();renderRouteSummary();
}
function updateExperienceStyles(){
 if(!state.mapLayersReady)return;
 const key=selectedEvidenceKey(),index=ExperienceCore.names.indexOf(state.dimension);
 const vals=experienceFeatures().map(f=>f.properties[key]).filter(Number.isFinite).sort((a,b)=>a-b);
 const lo=vals.length?vals[Math.floor((vals.length-1)*.33)]:0,hi=vals.length?vals[Math.floor((vals.length-1)*.67)]:0;
 mapExperience.breaks=[lo,hi];
 ExperienceCore.keys.forEach((k,i)=>{const id='experience-'+k;if(!state.map.getLayer(id))return;setMapLayerVisible(id,mapExperience.visible&&mapExperience.view!=='raw'&&i===index);
 const color=mapExperience.view==='score'||!key?'#69777d':['case',['==',['get',key],null],'#69777d',['<=',['get',key],lo],'#315e67',['<=',['get',key],hi],'#46b6ad','#d8f365'];
 state.map.setPaintProperty(id,'line-color',color);
 });
 setMapLayerVisible('experience-hit',mapExperience.visible&&mapExperience.view!=='raw');
 setMapLayerVisible('experience-coverage-line',mapExperience.coverage);
 // Original raw toggles remain independent; selected raw experience is an additional visibility reason.
 setMapLayerVisible('tree-points',state.display.trees||(mapExperience.visible&&mapExperience.view==='raw'&&key==='nature'));
 for(const id of ['landmark-fill','landmark-outline'])setMapLayerVisible(id,state.display.lpc||(mapExperience.visible&&mapExperience.view==='raw'&&key==='architecture'));
 applyExploreVisibility();
}
function renderExperienceLegend(){
 if(!$('legendTitle'))return;
 const i=ExperienceCore.names.indexOf(state.dimension),key=selectedEvidenceKey(),features=experienceFeatures();
 const n=key?features.filter(f=>Number.isFinite(f.properties[key])).length:0;
 const source=key==='nature'?'NYC Open Data 2015 Tree Census · year 2015':key==='architecture'?'NYC LPC individual-landmark parcels (ArcGIS mirror) · observation year not provided':'No verified dataset loaded';
 $('legendTitle').textContent=state.dimension+' · '+(mapExperience.view==='score'?'NO VALIDATED SCORE':mapExperience.view==='raw'?'RAW DATA':'STREET EVIDENCE');
 $('legendDot').style.background=key?'#d8f365':'#69777d';
 $('legendSubtitle').textContent=(dimensionDefinitions[i]||'Choose an experience dimension.')+' '+source+'. '+(mapExperience.view==='score'?'0/12 calibrated; all score fields NULL. ':`${n}/${features.length} sections with this proxy. `)+'Coverage: analyzed pilot / route sections only; elsewhere No Data. '+(mapExperience.retrieved?'Pilot retrieved '+mapExperience.retrieved.slice(0,10)+'. ':'');
 const scale=$('legend-scale');scale.classList.toggle('hidden',mapExperience.view!=='evidence'||!n);
 if(n){const [lo,hi]=mapExperience.breaks||[0,0];scale.innerHTML=`<span><i style="background:#315e67"></i>≤${lo.toFixed(1)}</span><span><i style="background:#46b6ad"></i>≤${hi.toFixed(1)}</span><span><i style="background:#d8f365"></i>&gt;${hi.toFixed(1)}</span><span>records/km · local thirds</span><span><i style="background:#69777d"></i>No Data</span>`;}
}
function renderRouteSummary(){
 const r=state.routes.find(x=>x.id===state.activeRoute);$('selectedRouteSummary').textContent=r?`${r.feasible?'Selected':'Outside constraints'} · ${r.label} · ${Math.ceil(r.min)} min · ${r.km.toFixed(2)} km`:'Choose a journey to compare real walking routes.';
}
function showSectionPopup(f,lngLat){
 const p=f.properties,key=selectedEvidenceKey();const value=key&&Number.isFinite(p[key])?`${p[key].toFixed(1)} records/km`:'No Data';
 const content=`<strong>${esc(p.street_name)}</strong><dl><dt>Segment ID</dt><dd>${esc(p.segment_id)}</dd><dt>${esc(state.dimension)} score</dt><dd>NULL · not calibrated</dd><dt>Raw section exposure</dt><dd>${esc(value)}</dd><dt>Evidence ≤75 m</dt><dd>${p.tree_count??'N/A'} living trees · ${p.lpc_count??'N/A'} LPC parcels</dd><dt>Source / year</dt><dd>NYC Open Data Tree Census / 2015; LPC mirror / year unspecified</dd></dl><small>${esc(p.network)}. 75 m is an exploratory buffer, not a verified human field of view.</small>`;
 $('segmentDetail').innerHTML=content;
 new maplibregl.Popup({maxWidth:'300px'}).setLngLat(lngLat).setHTML(content).addTo(state.map);
}
function showPOIPopup(f,lngLat){new maplibregl.Popup({maxWidth:'270px'}).setLngLat(lngLat).setHTML(`<strong>${esc(f.properties.name)}</strong><p>${esc(f.properties.category)} · OpenStreetMap</p><p>${f.geometry.coordinates.map(n=>Number(n).toFixed(5)).join(', ')} (lon, lat)</p><p>${esc(f.properties.distance_m)} m from selected route (straight-line offset)</p>`).addTo(state.map);}
async function analyzeArea(pilot=false){
 if(mapExperience.busy)return;const request=++mapExperience.request;mapExperience.busy=true;$('analyzeView').disabled=true;
 $('experienceStatus').textContent='Loading and checking complete spatial evidence…';
 try{
  let box,raw,streets,source,retrieved;
  if(pilot){const d=window.STREETWISE_PILOT||await timedJson('./data/pilot.json',15000);box=d.bbox;raw={trees:d.datasets.trees.features,lpc:d.datasets.lpc.features};streets=d.datasets.streets;source='Bundled real Midtown snapshot';retrieved=d.retrieved_at;
   if(!['trees','lpc','streets'].every(k=>d.sources[k].complete&&d.sources[k].expected===d.datasets[k].features.length))throw new Error('Pilot completeness check failed');
  }else{
   box=visibleEnvelope();if(!box||box[2]-box[0]>.025||box[3]-box[1]>.025)throw new Error('Zoom in: analyze an area smaller than roughly 2 km across.');
   const result=await Promise.allSettled(['trees','lpc','streets'].map(k=>fetchCompleteEvidence(k,box,k==='trees'?14000:6500)));
   if(result[2].status!=='fulfilled')throw new Error('Street source unavailable; existing analysis retained');
   raw={trees:result[0].status==='fulfilled'?result[0].value:null,lpc:result[1].status==='fulfilled'?result[1].value:null};streets=fc(result[2].value);source='Live bounded source scan';retrieved=new Date().toISOString();
  }
  if(request!==mapExperience.request)return;
  // Bounded scan plus 75 m inset: edge sections without a complete buffer are excluded.
  const sections=ExperienceCore.streets(streets,raw,box);
  for(const f of sections){f.properties.retrieved_at=retrieved;f.properties.coverage='Bounded pilot; complete buffer inset';}
  mapExperience.sections=sections;mapExperience.bbox=box;mapExperience.source=source;mapExperience.retrieved=retrieved;
  state.datasets.trees=raw.trees?fc(raw.trees):null;state.datasets.lpc=raw.lpc?fc(raw.lpc):null;
  state.overlayCoverage.trees={bbox:box,partial:!raw.trees};state.overlayCoverage.lpc={bbox:box,partial:!raw.lpc};
  $('experienceStatus').textContent=`${source}: ${sections.length} interior centerline sections. Nature ${raw.trees?'computed':'unavailable'} · Architecture ${raw.lpc?'computed':'unavailable'}. Raw proxies only; 0/12 calibrated scores.`;
  if(pilot&&state.mapReady)state.map.fitBounds([[box[0],box[1]],[box[2],box[3]]],{padding:60,maxZoom:14.5});syncMapData();
 }catch(e){$('experienceStatus').textContent=e.message+' · No scores fabricated.';}
 finally{mapExperience.busy=false;$('analyzeView').disabled=false;}
}
function setupExperienceControls(){
 if(window.innerWidth<=740){document.querySelector('.map-legend').classList.add('hidden');$('toggleLegend').setAttribute('aria-pressed','false');}
 state.dimension='Nature';$('experienceDimension').innerHTML=ExperienceCore.names.map((n,i)=>`<option value="${esc(n)}">${String(i+1).padStart(2,'0')} ${esc(n)}</option>`).join('');$('experienceDimension').value='Nature';
 for(const [id,mode] of [['modeNavigate','navigate'],['modeExplore','explore']])$(id).addEventListener('click',()=>{mapExperience.mode=mode;$('modeNavigate').setAttribute('aria-pressed',String(mode==='navigate'));$('modeExplore').setAttribute('aria-pressed',String(mode==='explore'));updateMapStyles();setExploreMode(mode==='explore');});
 $('experienceDimension').addEventListener('change',e=>{state.dimension=e.target.value;updateMapStyles();updateLegend();if(mapExperience.view==='raw')loadSelectedRaw();});
 $('experienceView').addEventListener('change',e=>{mapExperience.view=e.target.value;if(e.target.value==='raw')loadSelectedRaw();updateMapStyles();updateLegend();});
 $('layerExperience').addEventListener('change',e=>{mapExperience.visible=e.target.checked;updateMapStyles();});
 $('layerCoverage').addEventListener('change',e=>{mapExperience.coverage=e.target.checked;updateMapStyles();});
 $('analyzeView').addEventListener('click',()=>analyzeArea(false));
 $('exportExperience').addEventListener('click',()=>downloadGeoJSON('Streetwise_experience_sections.geojson',fc(experienceFeatures())));
 $('toggleLegend').addEventListener('click',()=>{const hidden=document.querySelector('.map-legend').classList.toggle('hidden');$('toggleLegend').setAttribute('aria-pressed',String(!hidden));});
 renderExperienceLegend();
}
function loadSelectedRaw(){const kind=selectedEvidenceKey()==='nature'?'trees':selectedEvidenceKey()==='architecture'?'lpc':null;if(kind&&!state.datasets[kind])loadViewportEvidence(kind);}
setupControls();setupExperienceControls();setupExploreControls();setupUrbanControls();setupMap();loadData('streets');loadWeather();
