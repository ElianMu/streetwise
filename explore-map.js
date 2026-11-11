'use strict';
/* Map Mode (Explore Urban Data): street-segment maps of the 12 Experience Dimensions, read from the GIS pipeline
   output in data/dimensions/<area>/ (scripts/dimensions/build.py): segments.geojson (geometry + dimension scores),
   indicators.json (raw + percentile values, fetched on the first click) and manifest.json (spec, sources, coverage).
   Scores are 0–100 ranks within the comparison area, not calibrated experience scores. Missing = N/A, never 0.
   Independent from AI Journey: no route data is read or changed here (routes keep using data/manhattan-streets.json). */
const DIM_LABELS=['Architecture','Nature','Culture','Quiet & Relax','Spatial Comfort','Urban Vibrancy','Food & Retail','Scenic & Visual','Walkability','Access & Safety','Environment','Transit Connectivity'];
const EXPLORE_VIEWS=[
 {label:'Overall (available dimensions)',prop:'overall',dim:null},
 ...DIM_LABELS.map((label,i)=>({label,prop:'d'+i,dim:i}))
];
// Full Manhattan first; the Midtown pilot is used only if the Manhattan build is missing (and is labelled as such).
const DIMENSION_AREAS=['manhattan','midtown'];
const exploreMap={data:null,loading:null,active:false,view:2,opacity:.9,hover:null,selected:null,collapsed:false,thumbs:false,labels:[],stops:null,manifest:null,base:null,details:null,detailsLoading:null,no2:null};
// Sequential green ramps that follow the map theme: lightness always runs toward the strongest contrast with the
// basemap, so high scores stand out (light theme: light → dark green; dark theme: dark → bright green).
const EXPLORE_RAMPS={light:['#dcefcf','#a3d48c','#5fa862','#2b7a44','#0f4a2b'],dark:['#163b2c','#1e6140','#2f8f4f','#73c463','#cdf58f']},EXPLORE_NA='#56585a';
const exploreRampColors=()=>EXPLORE_RAMPS[document.documentElement.dataset.mapTheme==='dark'?'dark':'light'];
const exploreView=()=>EXPLORE_VIEWS[exploreMap.view];
// Dimension scores are already percentiles, so fixed stops; Overall is a mean that clusters near 50, so its stops follow its own quantiles.
function exploreStops(view=exploreView()){if(view.dim!=null||!exploreMap.stops)return [0,35,60,78,100];return exploreMap.stops;}
function exploreColor(v,view=exploreView()){
 if(v==null||!Number.isFinite(v))return EXPLORE_NA;const s=exploreStops(view),c=exploreRampColors();
 if(v<=s[0])return c[0];for(let i=1;i<s.length;i++)if(v<=s[i]){const t=(v-s[i-1])/((s[i]-s[i-1])||1),a=c[i-1],b=c[i];const ch=k=>Math.round(parseInt(a.slice(k,k+2),16)*(1-t)+parseInt(b.slice(k,k+2),16)*t);return `rgb(${ch(1)},${ch(3)},${ch(5)})`;}
 return c.at(-1);
}
function exploreLineColor(){const v=exploreView(),s=exploreStops();return ['case',['==',['typeof',['get',v.prop]],'number'],['interpolate',['linear'],['get',v.prop],...s.flatMap((x,i)=>[x,exploreRampColors()[i]])],EXPLORE_NA];}
const fmtScore=v=>v==null||!Number.isFinite(Number(v))?'N/A':String(Math.round(v));
const exploreHasFilter=(v=exploreView())=>['==',['typeof',['get',v.prop]],'number'];
const exploreNaFilter=(v=exploreView())=>['!=',['typeof',['get',v.prop]],'number'];
/** The pipeline manifest, reshaped into the metadata fields the analytics panel already reads. */
function exploreCompatMeta(m){
 const byDim={};
 for(const x of m.indicators)(byDim[x.dimension]=byDim[x.dimension]||[]).push({...x,source:x.db[0],role:x.role==='validation'||x.role==='context'?'context':x.role});
 const src=Object.entries(m.sources);
 return {segments:m.segments,keys:m.dimensions.map(d=>d.key),indicators:byDim,score_method:m.score_method,
  source_labels:Object.fromEntries(src.map(([k,v])=>[k,v.label])),sources:Object.fromEntries(src.map(([k,v])=>[k,v.url])),
  data_version:(m.windows?.retrieved_at||m.built_at).slice(0,10),score_version:m.calculation_version,retrieved_at:m.windows?.retrieved_at||m.built_at};
}
async function loadDimensionArea(){
 // Offline hook (DOM tests, single-file demo): {manifest, segments, indicators, no2} injected as window.STREETWISE_DIMENSIONS.
 const pre=window.STREETWISE_DIMENSIONS;
 if(pre){const fc=pre.segments;fc.metadata=exploreCompatMeta(pre.manifest);exploreMap.manifest=pre.manifest;exploreMap.base=null;return fc;}
 let last;
 for(const area of DIMENSION_AREAS){
  const base=`./data/dimensions/${area}/`;
  try{
   const manifest=await timedJson(base+'manifest.json',15000);
   const fc=await timedJson(base+manifest.files.segments,30000);
   if(fc.metadata?.calculation_version!==manifest.calculation_version)throw new Error(`${area}: segment file and manifest come from different builds`);
   fc.metadata=exploreCompatMeta(manifest);exploreMap.manifest=manifest;exploreMap.base=base;
   return fc;
  }catch(e){last=e;}
 }
 throw last||new Error('no computed dimension data found');
}
async function loadExploreStreets(){
 if(exploreMap.data)return exploreMap.data;
 $('exploreStatus').textContent='Loading computed street dimensions…';
 exploreMap.loading=exploreMap.loading||loadDimensionArea();
 try{exploreMap.data=await exploreMap.loading;}catch(e){exploreMap.loading=null;$('exploreStatus').textContent='Computed street dimension data unavailable: '+e.message+'. Run python3 -m scripts.dimensions.build --area manhattan.';throw e;}
 const mf=exploreMap.manifest,overall=exploreMap.data.features.map(f=>f.properties.overall).filter(Number.isFinite).sort((a,b)=>a-b);
 const q=p=>overall[Math.min(overall.length-1,Math.floor(p*(overall.length-1)))];
 exploreMap.stops=[q(.02),q(.3),q(.55),q(.8),q(.98)].map((v,i,a)=>i&&v<=a[i-1]?a[i-1]+.5:v);
 const done=mf.indicators.filter(x=>x.status==='computed').length,scored=mf.indicators.filter(x=>x.role==='up'||x.role==='down').length;
 $('exploreScope').textContent=mf.area==='manhattan'?'ALL MANHATTAN · STREET SEGMENTS':'MIDTOWN PILOT ONLY · NOT ALL MANHATTAN';
 $('exploreStatus').innerHTML=`<b>${mf.segments.toLocaleString()}</b> ${esc(mf.area_label)} street segments · <b>${done}/${scored}</b> scored indicators computed from real sources (retrieved ${esc((mf.windows?.retrieved_at||'').slice(0,10))}). `+
  `Percentiles rank segments within this area only. N/A = not measurable, never 0. <span class="explore-version">calc ${esc(mf.calculation_version)} · built ${esc(mf.built_at.slice(0,16).replace('T',' '))} UTC</span>`;
 renderExploreThumbs();selectExploreView(exploreMap.view);
 if(state.mapLayersReady)state.map.getSource('manhattan-streets')?.setData(exploreMap.data);
 loadExploreNo2().catch(()=>{});
 if(typeof renderExploreAnalytics==='function')renderExploreAnalytics();
 return exploreMap.data;
}
/** Raw + percentile indicator values, fetched once on the first segment click (kept out of the map layer). */
function loadExploreDetails(){
 if(exploreMap.details)return Promise.resolve(exploreMap.details);
 const pre=window.STREETWISE_DIMENSIONS?.indicators;
 exploreMap.detailsLoading=exploreMap.detailsLoading||(pre?Promise.resolve(pre):timedJson(exploreMap.base+exploreMap.manifest.files.indicators,30000)).then(d=>{
  if(d.calculation_version!==exploreMap.manifest.calculation_version)throw new Error('indicator file comes from a different build');
  d.index=new Map(d.ids.map((id,i)=>[id,i]));exploreMap.details=d;return d;}).catch(e=>{exploreMap.detailsLoading=null;throw e;});
 return exploreMap.detailsLoading;
}
/** DOHMH annual NO₂ by Community District — area context drawn under Environment, never a street value. */
async function loadExploreNo2(){
 const f=exploreMap.manifest?.files?.context_no2;if(!f||exploreMap.no2)return exploreMap.no2;
 exploreMap.no2=window.STREETWISE_DIMENSIONS?.no2||await timedJson(exploreMap.base+f,15000);
 if(state.mapLayersReady)state.map.getSource('explore-no2')?.setData(exploreMap.no2);
 return exploreMap.no2;
}
/** Route-edge inspectors keep reading the routing engine's own street file, unchanged. */
let legacyStreets=null;
function loadLegacyStreets(){
 return legacyStreets||(legacyStreets=(window.STREETWISE_STREETS?Promise.resolve(window.STREETWISE_STREETS):timedJson('./data/manhattan-streets.json',30000)).catch(e=>{legacyStreets=null;throw e;}));
}
function setupExploreMap(){
 // MapLibre only accepts ['zoom'] as the input of a top-level interpolate, so scaled widths are separate ramps.
 const m=state.map,W=[[10.5,.55],[12,1.1],[14,2.4],[16,5],[18,10]],ramp=f=>['interpolate',['exponential',1.5],['zoom'],...W.flatMap(([z,v])=>[z,f(v)])],width=ramp(v=>v);
 // Basemap labels and icons are hidden in Explore so nothing sits on top of the streets.
 exploreMap.labels=m.getStyle().layers.filter(l=>l.type==='symbol').map(l=>l.id);
 m.addSource('manhattan-streets',{type:'geojson',data:exploreMap.data||emptyFC(),promoteId:'id'});
 m.addSource('explore-no2',{type:'geojson',data:exploreMap.no2||emptyFC()});
 const before='landmark-fill';
 // NO₂ is neighbourhood context: a faint Community District wash + outline, drawn only in the Environment view.
 m.addLayer({id:'explore-no2-fill',type:'fill',source:'explore-no2',layout:{visibility:'none'},paint:{'fill-color':['interpolate',['linear'],['get','no2_ppb'],16,'#2a3b46',25,'#7a5a3a'],'fill-opacity':.28}},before);
 m.addLayer({id:'explore-no2-line',type:'line',source:'explore-no2',layout:{visibility:'none'},paint:{'line-color':'#b9a27a','line-width':1,'line-dasharray':[3,2],'line-opacity':.55}},before);
 // N/A segments: their own dashed grey style, so "no data" never reads as a low score.
 m.addLayer({id:'explore-na',type:'line',source:'manhattan-streets',layout:{visibility:'none','line-cap':'butt'},filter:exploreNaFilter(),paint:{'line-color':EXPLORE_NA,'line-width':ramp(v=>.7*v),'line-dasharray':[2,1.5],'line-opacity':.75}},before);
 m.addLayer({id:'explore-glow',type:'line',source:'manhattan-streets',layout:{visibility:'none','line-cap':'round'},filter:['>=',['coalesce',['get','d1'],-1],78],paint:{'line-color':'#ffd83a','line-width':ramp(v=>3*v),'line-blur':ramp(v=>2*v),'line-opacity':.2}},before);
 m.addLayer({id:'explore-streets',type:'line',source:'manhattan-streets',filter:exploreHasFilter(),layout:{visibility:'none','line-cap':'round','line-join':'round','line-sort-key':['coalesce',['get','overall'],-1]},paint:{'line-color':exploreLineColor(),'line-width':width,'line-opacity':exploreMap.opacity}},before);
 m.addLayer({id:'explore-hover',type:'line',source:'manhattan-streets',layout:{visibility:'none','line-cap':'round'},paint:{'line-color':'#ffffff','line-width':ramp(v=>1.6*v),'line-opacity':['case',['boolean',['feature-state','hover'],false],.85,0]}},before);
 m.addLayer({id:'explore-selected',type:'line',source:'manhattan-streets',layout:{visibility:'none','line-cap':'round'},filter:['==',['get','id'],''],paint:{'line-color':'#ffffff','line-width':ramp(v=>Math.max(5,2.6*v)),'line-opacity':1}},before);
 // Invisible wide hit target: segments are clickable at whole-island zoom without zooming in first.
 m.addLayer({id:'explore-hit',type:'line',source:'manhattan-streets',layout:{visibility:'none'},paint:{'line-color':'#000','line-width':['interpolate',['linear'],['zoom'],10,9,14,14,17,22],'line-opacity':0}},before);
 m.on('mousemove','explore-hit',e=>{
  const f=e.features?.[0];if(!f)return;showExploreTooltip(f.properties,e.point);
  if(f.id===exploreMap.hover)return;if(exploreMap.hover!=null)m.setFeatureState({source:'manhattan-streets',id:exploreMap.hover},{hover:false});exploreMap.hover=f.id;m.setFeatureState({source:'manhattan-streets',id:f.id},{hover:true});m.getCanvas().style.cursor='pointer';
 });
 m.on('mouseleave','explore-hit',()=>{if(exploreMap.hover!=null)m.setFeatureState({source:'manhattan-streets',id:exploreMap.hover},{hover:false});exploreMap.hover=null;m.getCanvas().style.cursor='';$('exploreTooltip').classList.add('hidden');});
 m.on('click','explore-hit',e=>{if(state.pick)return;const f=e.features?.[0];if(f)selectExploreSegment(f.properties.id);});
 if(exploreMap.active)setExploreMode(true);
}
function exploreSegment(id){return exploreMap.data?.features.find(f=>f.properties.id===id)?.properties||null;}
function showExploreTooltip(p,point){
 const t=$('exploreTooltip'),v=exploreView();
 const cov=v.dim==null?`${p.coverage}/12 dimensions`:`${p['n'+v.dim]}/${exploreMap.manifest?.dimensions[v.dim].scored_indicators.length??'?'} indicators`;
 t.innerHTML=`<strong>${esc(p.name||'Unnamed street')}</strong><span>${esc(v.label)} · <b style="color:${exploreColor(p[v.prop])}">${fmtScore(p[v.prop])}</b> <small>${esc(cov)}</small></span>`;
 t.style.left=Math.round(point.x+14)+'px';t.style.top=Math.round(point.y+14)+'px';t.classList.remove('hidden');
}
function selectExploreView(view){
 exploreMap.view=view;const v=exploreView();
 if(typeof renderExploreAnalytics==='function')renderExploreAnalytics();
 $('exploreTitle').textContent=v.dim==null?v.label:`${String(v.dim+1).padStart(2,'0')} ${v.label}`;
 const mf=exploreMap.manifest;
 if(!mf)$('exploreMetric').textContent='';
 else if(v.dim==null)$('exploreMetric').textContent='Equal-weight mean of the dimension scores available on each segment (N/A dimensions excluded). Context view only.';
 else{
  const d=mf.dimensions[v.dim],inds=mf.indicators.filter(x=>x.dimension===d.key);
  $('exploreMetric').innerHTML=`<span class="explore-cov ${d.status}">${d.model_coverage} scored indicators available</span> `+inds.map(x=>{
   const tag=x.status==='unavailable'?' — N/A (source not acquired)':x.role==='validation'?' — validation only':x.role==='context'?' — area context only':x.role==='down'?' (lower is better)':'';
   return `<span class="explore-ind ${x.status}"><code>${esc(x.key)}</code> ${esc(x.label)}${esc(tag)}</span>`;}).join('');
 }
 $('exploreRampLow').textContent=fmtScore(exploreStops()[0]);$('exploreRampHigh').textContent=fmtScore(exploreStops().at(-1));
 document.querySelectorAll('[data-view]').forEach(b=>b.setAttribute('aria-checked',String(Number(b.dataset.view)===view)));
 renderExploreInspector();
 if(!state.mapLayersReady||!state.map.getLayer('explore-streets'))return;
 state.map.setPaintProperty('explore-streets','line-color',exploreLineColor());
 state.map.setFilter('explore-streets',exploreHasFilter());state.map.setFilter('explore-na',exploreNaFilter());
 const env=exploreMap.active&&v.dim===10;setMapLayerVisible('explore-no2-fill',env);setMapLayerVisible('explore-no2-line',env);
 state.map.setLayoutProperty('explore-streets','line-sort-key',['coalesce',['get',v.prop],-1]);
 state.map.setFilter('explore-glow',['>=',['coalesce',['get',v.prop],-1],exploreStops()[3]]);
}
/** Called by applyMapTheme(): repaint the street ramp, small multiples and inspector swatch for the new theme. */
function applyExploreTheme(){
 if(state.mapLayersReady&&state.map.getLayer('explore-streets'))state.map.setPaintProperty('explore-streets','line-color',exploreLineColor());
 if(exploreMap.data){renderExploreThumbs();renderExploreInspector();}
}
function selectExploreSegment(id){
 exploreMap.selected=id;
 if(state.mapLayersReady&&state.map.getLayer('explore-selected'))state.map.setFilter('explore-selected',['==',['get','id'],id||'']);
 renderExploreInspector();
}
/** Raw value in the unit of the specification (shares 0–1 also shown as %). */
function indicatorValue(v,unit){
 if(v==null||!Number.isFinite(Number(v)))return 'N/A';const n=Number(v);
 if(unit==='share 0–1')return `${n.toFixed(2)} (${Math.round(n*100)}%)`;
 if(unit==='m'||unit==='ft'||unit==='count'||unit==='people/h')return `${Math.round(n).toLocaleString()} ${unit}`;
 return `${n.toLocaleString(undefined,{maximumFractionDigits:2})} ${unit}`;
}
const INSPECTOR_STATUS={computed:'Computed',unavailable:'N/A · source not acquired','validation-only':'Validation only · not scored','context-only':'Area context only · not scored'};
let inspectorToken=0;
function renderExploreInspector(){
 const box=$('exploreInspector'),p=exploreMap.selected&&exploreSegment(exploreMap.selected);
 if(!exploreMap.active||!p){box.classList.add('hidden');return;}
 const mf=exploreMap.manifest,v=exploreView(),score=p[v.prop],token=++inspectorToken;
 const dimMeta=v.dim==null?null:mf.dimensions[v.dim];
 const cov=v.dim==null?`${p.coverage} of 12 dimensions available on this segment`:`${p['n'+v.dim]} of ${dimMeta.scored_indicators.length} scored indicators available on this segment · model ${dimMeta.model_coverage}`;
 const head=`<div class="inspector-head"><div><div class="explore-eyebrow">STREET SEGMENT INFORMATION</div><strong>${esc(p.name||'Unnamed street')}</strong></div><button type="button" id="inspectorClose" class="explore-collapse" aria-label="Close inspector">✕</button></div>
  <dl class="inspector-ids"><dt>Segment ID</dt><dd data-k="segment-id">${esc(p.id)}</dd><dt>Street Name</dt><dd>${esc(p.name||'N/A')}</dd><dt>Length</dt><dd>${Number(p.length_m).toLocaleString(undefined,{maximumFractionDigits:1})} m</dd><dt>Dimension</dt><dd>${esc(v.dim==null?v.label:`${dimMeta.num} ${dimMeta.label}`)}</dd></dl>
  <div class="inspector-score"><span>${esc(v.label)} · Dimension Score</span><strong class="score-with-swatch"><i class="score-swatch${score==null?' na':''}" style="background:${exploreColor(score)}"></i><b data-k="dimension-score">${fmtScore(score)}</b></strong><small>0–100 percentile within ${esc(mf.area_label)} · ${esc(cov)}</small></div>`;
 const prov=`<h4>Data &amp; version</h4><p>Segment ${esc(p.id)} = NYC LION physical ID. ${esc(mf.comparison_scope)} Calculation ${esc(mf.calculation_version)}, built ${esc(mf.built_at.slice(0,10))}. Values marked N/A were not measurable and are never counted as 0.</p>`;
 box.innerHTML=head+`<p class="explore-note" data-k="loading">Loading indicator values…</p>`+prov;box.classList.remove('hidden');
 $('inspectorClose').addEventListener('click',()=>selectExploreSegment(null));
 loadExploreDetails().then(D=>{
  if(token!==inspectorToken)return;
  const i=D.index.get(p.id);
  let body;
  if(v.dim==null){
   body=`<div class="explore-rows">${mf.dimensions.map((d,j)=>{const s=p['d'+j];return `<div class="explore-row"><span>${esc(d.num+' '+d.label)} <small>${p['n'+j]}/${d.scored_indicators.length}</small></span><i>${s==null?'':`<b style="width:${s}%;background:${exploreColor(s,EXPLORE_VIEWS[j+1])}"></b>`}</i><em>${fmtScore(s)}</em></div>`;}).join('')}</div>
    <h4>Method</h4><p>${esc(mf.score_method)} Overall = mean of the available dimension scores.</p>`;
  }else{
   const inds=mf.indicators.filter(x=>x.dimension===dimMeta.key);
   body=`<h4>Indicators</h4>${inds.map(x=>{
    const raw=i==null?null:D.raw[x.key]?.[i],pct=i==null?null:D.pct[x.key]?.[i];
    let extra='';
    if(x.key==='no2_area_context'){const cd=D.extras.cd?.[i],f=exploreMap.no2?.features.find(q=>q.properties.cd===cd);
     extra=f?`<div class="indicator-top"><span>Community District ${cd} · ${esc(f.properties.name)}</span><strong>${f.properties.no2_ppb} ppb</strong></div><small>Annual mean NO₂ ${esc(exploreMap.no2.metadata.time_period)} for the whole district — neighbourhood context, not a value measured on this street.</small>`:'<small>Outside the published Community District geography.</small>';}
    if(x.key==='tree_km'&&D.extras.tree_n)extra=`<small>${D.extras.tree_n[i]} trees snapped to this segment.</small>`;
    if(x.key==='vibr_idx'&&D.extras.poi_n)extra=`<small>${D.extras.poi_n[i]} places within 150 m · diversity H = ${D.extras.diversity_h[i]}</small>`;
    if(x.key==='ped_flow_observed'&&raw==null&&x.status!=='unavailable')extra='<small>No DOT count location on this segment.</small>';
    const scored=x.role==='up'||x.role==='down';
    return `<div class="indicator ${esc(x.status)}" data-key="${esc(x.key)}"><div class="indicator-top"><span><code>${esc(x.key)}</code> ${esc(x.label)}</span><strong data-k="raw">${x.role==='context'?'—':esc(indicatorValue(raw,x.unit))}</strong></div>
     <div class="indicator-role">${esc(INSPECTOR_STATUS[x.status]||x.status)}${scored&&x.status==='computed'?` · normalized <b data-k="pct">${pct==null?'N/A':pct}</b>/100 · ${x.role==='down'?'lower raw value is better (percentile reversed)':'higher raw value is better'}`:''}</div>
     ${extra}<p>${esc(x.method)}</p>${(x.notes||[]).map(n=>`<small class="indicator-note">${esc(n)}</small>`).join('')}<small>Source: ${esc(x.sources.join(' · '))}</small></div>`;}).join('')}
    <h4>Score method</h4><p>${esc(mf.score_method)}${score==null?' No scored indicator is measurable on this segment, so the score is N/A.':''}</p>`;
  }
  box.querySelector('[data-k="loading"]').outerHTML=body;
 }).catch(e=>{if(token===inspectorToken){const l=box.querySelector('[data-k="loading"]');if(l)l.textContent='Indicator values unavailable: '+e.message;}});
}
function renderExploreChips(){
 $('exploreChips').innerHTML=EXPLORE_VIEWS.map((v,i)=>`<button type="button" class="explore-chip${i?'':' overall'}" role="radio" data-view="${i}" aria-checked="${i===exploreMap.view}">${i?`<b>${String(i).padStart(2,'0')}</b>`:'✦ '}${esc(v.label)}</button>`).join('');
 $('exploreChips').querySelectorAll('[data-view]').forEach(b=>b.addEventListener('click',()=>selectExploreView(Number(b.dataset.view))));
}
function renderExploreThumbs(){
 const root=$('exploreGrid'),fs=exploreMap.data?.features||[];
 root.innerHTML=EXPLORE_VIEWS.map((v,i)=>`<button type="button" class="explore-dim" data-view="${i}" aria-checked="${i===exploreMap.view}"><canvas width="90" height="300" aria-hidden="true"></canvas><span>${esc(v.label)}</span></button>`).join('');
 root.querySelectorAll('[data-view]').forEach(b=>b.addEventListener('click',()=>selectExploreView(Number(b.dataset.view))));
 if(!fs.length||!exploreMap.thumbs)return;
 // Small multiples share one projection, rotated ~23° so the island's long axis stands upright.
 const kx=Math.cos(40.78*Math.PI/180),a=23*Math.PI/180,ca=Math.cos(a),sa=Math.sin(a),rot=([x,y])=>[x*kx*ca-y*sa,x*kx*sa+y*ca];
 const lines=fs.map(f=>f.geometry.coordinates.map(rot));
 let x0=Infinity,y0=Infinity,x1=-Infinity,y1=-Infinity;
 for(const l of lines)for(const [x,y] of l){x0=Math.min(x0,x);x1=Math.max(x1,x);y0=Math.min(y0,y);y1=Math.max(y1,y);}
 root.querySelectorAll('canvas').forEach((cv,i)=>{
  const ctx=cv.getContext('2d');if(!ctx)return;
  const v=EXPLORE_VIEWS[i],s=Math.min((cv.width-4)/(x1-x0),(cv.height-4)/(y1-y0)),ox=(cv.width-(x1-x0)*s)/2,oy=(cv.height-(y1-y0)*s)/2;
  const order=fs.map((f,j)=>j).sort((p,q)=>(fs[p].properties[v.prop]??-1)-(fs[q].properties[v.prop]??-1));
  ctx.lineWidth=.9;ctx.lineCap='round';
  for(const j of order){ctx.strokeStyle=exploreColor(fs[j].properties[v.prop],v);ctx.beginPath();lines[j].forEach(([x,y],k)=>{const px=ox+(x-x0)*s,py=oy+(y1-y)*s;k?ctx.lineTo(px,py):ctx.moveTo(px,py);});ctx.stroke();}
 });
}
function setExploreMode(on){
 exploreMap.active=on;
 // Route-edge and street popups belong to the mode that opened them.
 document.querySelectorAll('.maplibregl-popup').forEach(p=>p.remove());
 if(typeof closeUrbanInspector==='function')closeUrbanInspector();
 $('explorePanel').classList.toggle('hidden',!on);
 for(const sel of ['.experience-controls','.map-layer-switch','.wx-panel','.ud-legend'])document.querySelector(sel).classList.toggle('hidden',on);
 document.querySelector('.map-legend').classList.toggle('explore-hidden',on);
 $('selectedRouteSummary').classList.toggle('hidden',on);
 if(!on)$('exploreTooltip').classList.add('hidden');
 if(on)loadExploreStreets().catch(()=>{});
 renderExploreInspector();
 if(!state.mapLayersReady)return;
 if(on)state.map.fitBounds(MANHATTAN_BOUNDS,{padding:{top:30,bottom:40,right:60,left:exploreMap.collapsed||window.innerWidth<=740?30:300},duration:700,maxZoom:12});
 updateMapStyles();
}
function applyExploreVisibility(){
 const on=exploreMap.active;
 for(const id of ['explore-glow','explore-na','explore-streets','explore-hover','explore-selected','explore-hit'])setMapLayerVisible(id,on);
 for(const id of ['explore-no2-fill','explore-no2-line'])setMapLayerVisible(id,on&&exploreView().dim===10);
 for(const id of exploreMap.labels)setMapLayerVisible(id,!on);
 for(const id of ['point-starts','point-ends','point-gps'])setMapLayerVisible(id,!on);
 if(!on){for(const id of [...urbanMapLayerIds(),'ud-highlight-fill','ud-highlight-line','ud-highlight-pt'])setMapLayerVisible(id,true);applyEnvTheme();return;}
 // Explore shows only the street map: no journey routes, pins, POIs, raw tree/landmark points or section overlays.
 for(const id of [...urbanMapLayerIds(),'ud-highlight-fill','ud-highlight-line','ud-highlight-pt','road-highlight','road-underlay','route-alts','route-shadow','route-selected','route-edge-selected','route-edge-hit','point-starts','point-ends','point-gps','poi-points','tree-points','landmark-fill','landmark-outline','experience-hit','experience-coverage-line',...ExperienceCore.keys.map(k=>'experience-'+k)])setMapLayerVisible(id,false);
}
function setupExploreControls(){
 renderExploreChips();renderExploreThumbs();selectExploreView(exploreMap.view);
 $('exploreOpacity').addEventListener('input',e=>{exploreMap.opacity=e.target.value/100;if(state.mapLayersReady)state.map.setPaintProperty('explore-streets','line-opacity',exploreMap.opacity);});
 $('exploreCollapse').addEventListener('click',()=>{exploreMap.collapsed=!exploreMap.collapsed;$('explorePanel').classList.toggle('collapsed',exploreMap.collapsed);$('exploreCollapse').textContent=exploreMap.collapsed?'+':'–';$('exploreCollapse').setAttribute('aria-expanded',String(!exploreMap.collapsed));});
 $('exploreThumbsToggle').addEventListener('click',()=>{exploreMap.thumbs=!exploreMap.thumbs;$('exploreThumbsToggle').setAttribute('aria-pressed',String(exploreMap.thumbs));$('exploreGrid').classList.toggle('hidden',!exploreMap.thumbs);$('exploreChips').classList.toggle('hidden',exploreMap.thumbs);$('explorePanel').classList.toggle('wide',exploreMap.thumbs);if(exploreMap.collapsed)$('exploreCollapse').click();renderExploreThumbs();});
 document.addEventListener('keydown',e=>{if(e.key==='Escape'&&exploreMap.selected)selectExploreSegment(null);});
 if(window.innerWidth<=740)$('exploreCollapse').click();
}
