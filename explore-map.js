'use strict';
/* Explore Urban Data: 13 Manhattan street-segment maps (Overall Experience + 12 dimensions) from
   data/manhattan-streets.json, with hover read-out and a Street Segment Inspector.
   Scores are 0–100 ranks within Manhattan, not calibrated experience scores. Missing = N/A, never filled.
   Independent from AI Journey: no route data is read or changed here. */
const EXPLORE_VIEWS=[
 {label:'Overall Experience',prop:'overall',dim:null},
 ...['Architecture','Nature','Culture','Quiet & Relax','Comfort','Vibrancy','Food & Retail','Scenic','Walkability','Safety','Environment','Transit'].map((label,i)=>({label,prop:'d'+i,dim:i}))
];
const exploreMap={data:null,loading:null,active:false,view:0,opacity:.9,hover:null,selected:null,collapsed:false,thumbs:false,labels:[],stops:null};
const EXPLORE_RAMP_COLORS=['#1d5b8e','#2389cc','#3fc7e8','#f0d23e','#ffe04a'],EXPLORE_NA='#5d686c';
const exploreView=()=>EXPLORE_VIEWS[exploreMap.view];
// Dimension scores are already percentiles, so fixed stops; Overall is a mean that clusters near 50, so its stops follow its own quantiles.
function exploreStops(view=exploreView()){if(view.dim!=null||!exploreMap.stops)return [0,35,60,78,100];return exploreMap.stops;}
function exploreColor(v,view=exploreView()){
 if(v==null||!Number.isFinite(v))return EXPLORE_NA;const s=exploreStops(view),c=EXPLORE_RAMP_COLORS;
 if(v<=s[0])return c[0];for(let i=1;i<s.length;i++)if(v<=s[i]){const t=(v-s[i-1])/((s[i]-s[i-1])||1),a=c[i-1],b=c[i];const ch=k=>Math.round(parseInt(a.slice(k,k+2),16)*(1-t)+parseInt(b.slice(k,k+2),16)*t);return `rgb(${ch(1)},${ch(3)},${ch(5)})`;}
 return c.at(-1);
}
function exploreLineColor(){const v=exploreView(),s=exploreStops();return ['case',['==',['typeof',['get',v.prop]],'number'],['interpolate',['linear'],['get',v.prop],...s.flatMap((x,i)=>[x,EXPLORE_RAMP_COLORS[i]])],EXPLORE_NA];}
const fmtScore=v=>v==null||!Number.isFinite(Number(v))?'N/A':String(Math.round(v));
async function loadExploreStreets(){
 if(exploreMap.data)return exploreMap.data;
 $('exploreStatus').textContent='Loading Manhattan street segments…';
 exploreMap.loading=exploreMap.loading||(window.STREETWISE_STREETS?Promise.resolve(window.STREETWISE_STREETS):timedJson('./data/manhattan-streets.json',30000));
 try{exploreMap.data=await exploreMap.loading;}catch(e){exploreMap.loading=null;$('exploreStatus').textContent='Street segment data unavailable: '+e.message;throw e;}
 const m=exploreMap.data.metadata,overall=exploreMap.data.features.map(f=>f.properties.overall).filter(Number.isFinite).sort((a,b)=>a-b);
 const q=p=>overall[Math.min(overall.length-1,Math.floor(p*(overall.length-1)))];
 exploreMap.stops=[q(.02),q(.3),q(.55),q(.8),q(.98)].map((v,i,a)=>i&&v<=a[i-1]?a[i-1]+.5:v);
 $('exploreStatus').textContent=`${m.segments.toLocaleString()} Manhattan street segments · retrieved ${m.retrieved_at.slice(0,10)}${m.trees_inventory_updated?` · tree inventory updated ${m.trees_inventory_updated}`:''}. Scores rank segments within Manhattan; they are not calibrated experience scores.`;
 renderExploreThumbs();selectExploreView(exploreMap.view);
 if(state.mapLayersReady)state.map.getSource('manhattan-streets')?.setData(exploreMap.data);
 if(typeof renderExploreAnalytics==='function')renderExploreAnalytics();
 return exploreMap.data;
}
function setupExploreMap(){
 // MapLibre only accepts ['zoom'] as the input of a top-level interpolate, so scaled widths are separate ramps.
 const m=state.map,W=[[10.5,.55],[12,1.1],[14,2.4],[16,5],[18,10]],ramp=f=>['interpolate',['exponential',1.5],['zoom'],...W.flatMap(([z,v])=>[z,f(v)])],width=ramp(v=>v);
 // Basemap labels and icons are hidden in Explore so nothing sits on top of the streets.
 exploreMap.labels=m.getStyle().layers.filter(l=>l.type==='symbol').map(l=>l.id);
 m.addSource('manhattan-streets',{type:'geojson',data:exploreMap.data||emptyFC(),promoteId:'id'});
 const before='landmark-fill';
 m.addLayer({id:'explore-glow',type:'line',source:'manhattan-streets',layout:{visibility:'none','line-cap':'round'},filter:['>=',['coalesce',['get','d1'],-1],78],paint:{'line-color':'#ffd83a','line-width':ramp(v=>3*v),'line-blur':ramp(v=>2*v),'line-opacity':.2}},before);
 m.addLayer({id:'explore-streets',type:'line',source:'manhattan-streets',layout:{visibility:'none','line-cap':'round','line-join':'round','line-sort-key':['coalesce',['get','overall'],-1]},paint:{'line-color':exploreLineColor(),'line-width':width,'line-opacity':exploreMap.opacity}},before);
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
 t.innerHTML=`<strong>${esc(p.name||'Unnamed street')}</strong><span>${esc(v.label)} · <b style="color:${exploreColor(p[v.prop])}">${fmtScore(p[v.prop])}</b></span>`;
 t.style.left=Math.round(point.x+14)+'px';t.style.top=Math.round(point.y+14)+'px';t.classList.remove('hidden');
}
function selectExploreView(view){
 exploreMap.view=view;const v=exploreView();
 if(typeof renderExploreAnalytics==='function')renderExploreAnalytics();
 $('exploreTitle').textContent=v.label;
 const meta=exploreMap.data?.metadata;
 $('exploreMetric').textContent=v.dim==null?'Equal-weight mean of the 12 dimension scores available on each segment.':(meta?.indicators[meta.keys[v.dim]]||[]).filter(x=>x.role!=='context').map(x=>x.label+(x.role==='down'?' (lower is better)':'')).join(' · ');
 $('exploreRampLow').textContent=fmtScore(exploreStops()[0]);$('exploreRampHigh').textContent=fmtScore(exploreStops().at(-1));
 document.querySelectorAll('[data-view]').forEach(b=>b.setAttribute('aria-checked',String(Number(b.dataset.view)===view)));
 renderExploreInspector();
 if(!state.mapLayersReady||!state.map.getLayer('explore-streets'))return;
 state.map.setPaintProperty('explore-streets','line-color',exploreLineColor());
 state.map.setLayoutProperty('explore-streets','line-sort-key',['coalesce',['get',v.prop],-1]);
 state.map.setFilter('explore-glow',['>=',['coalesce',['get',v.prop],-1],exploreStops()[3]]);
}
function selectExploreSegment(id){
 exploreMap.selected=id;
 if(state.mapLayersReady&&state.map.getLayer('explore-selected'))state.map.setFilter('explore-selected',['==',['get','id'],id||'']);
 renderExploreInspector();
}
function indicatorValue(v,unit){if(v==null)return 'N/A';const n=Number(v);const txt=Number.isInteger(n)?n.toLocaleString():n.toLocaleString(undefined,{maximumFractionDigits:2});return `${txt} ${unit}`;}
function renderExploreInspector(){
 const box=$('exploreInspector'),p=exploreMap.selected&&exploreSegment(exploreMap.selected);
 if(!exploreMap.active||!p){box.classList.add('hidden');return;}
 const meta=exploreMap.data.metadata,v=exploreView(),score=p[v.prop];
 const head=`<div class="inspector-head"><div><div class="explore-eyebrow">STREET SEGMENT INSPECTOR</div><strong>${esc(p.name||'Unnamed street')}</strong></div><button type="button" id="inspectorClose" class="explore-collapse" aria-label="Close inspector">✕</button></div>
  <dl class="inspector-ids"><dt>Segment ID</dt><dd>${esc(p.id)}</dd><dt>Street Name</dt><dd>${esc(p.name||'N/A')}</dd><dt>Segment Length</dt><dd>${Number(p.length_m).toLocaleString(undefined,{maximumFractionDigits:1})} m</dd></dl>
  <div class="inspector-score"><span>${esc(v.label)}${v.dim==null?' Score':' · Experience Score'}</span><strong style="color:${exploreColor(score)}">${fmtScore(score)}</strong><small>0–100, rank among Manhattan street segments</small></div>`;
 let body;
 if(v.dim==null){
  const missing=EXPLORE_VIEWS.slice(1).filter(x=>p[x.prop]==null).map(x=>x.label);
  body=`<div class="explore-rows">${EXPLORE_VIEWS.slice(1).map(x=>{const s=p[x.prop];return `<div class="explore-row"><span>${esc(x.label)}</span><i>${s==null?'':`<b style="width:${s}%;background:${exploreColor(s,x)}"></b>`}</i><em>${fmtScore(s)}</em></div>`;}).join('')}</div>
   <h4>Method</h4><p>${esc(meta.score_method)}</p>
   <h4>Data coverage</h4><p>${p.coverage} of 12 dimensions available${missing.length?` · N/A: ${esc(missing.join(', '))}`:''}.</p>`;
 }else{
  const ind=meta.indicators[meta.keys[v.dim]];
  body=`<h4>Sub-indicators</h4>${ind.map(x=>`<div class="indicator"><div class="indicator-top"><span>${esc(x.label)}</span><strong>${esc(indicatorValue(p[x.key],x.unit))}</strong></div><div class="indicator-role">${x.role==='context'?'Context only, not in score':x.role==='down'?'In score · lower is better':'In score · higher is better'}</div><p>${esc(x.method)}</p><small>Source: ${esc(meta.source_labels[x.source]||x.source)}</small></div>`).join('')}
   <h4>Score method</h4><p>Mean of the ranked sub-indicators above, each a 0–100 percentile among Manhattan segments. ${score==null?'No ranked sub-indicator is measurable here, so the score is N/A.':''}</p>`;
 }
 const srcs=v.dim==null?[]:[...new Set(meta.indicators[meta.keys[v.dim]].map(x=>x.source))];
 const prov=`<h4>Data</h4><p>Segment ${esc(p.id)} (NYC LION). Normalization: percentile rank among ${Number(meta.segments).toLocaleString()} Manhattan segments, 0–100. Data ${esc(meta.data_version)} · scores ${esc(meta.score_version)}.${srcs.length?` Sources: ${srcs.map(s=>esc(meta.source_labels?.[s]||s)).join(', ')}.`:''} Values marked N/A were not measurable and are not counted as 0.</p>`;
 box.innerHTML=head+body+prov;box.classList.remove('hidden');
 $('inspectorClose').addEventListener('click',()=>selectExploreSegment(null));
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
 for(const id of ['explore-glow','explore-streets','explore-hover','explore-selected','explore-hit'])setMapLayerVisible(id,on);
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
