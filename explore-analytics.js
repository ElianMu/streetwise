'use strict';
/* Explore Urban Data analytics, computed from the same street segments the map draws (data/manhattan-streets.json):
   distribution of the active view, comparison of two views, and dataset details for the active dimension.
   Only measured values are counted; N/A segments are reported as missing, never as 0. Scores are relative ranks among
   Manhattan segments (0–100), not calibrated experience measurements. */
const exploreStats={compare:1,open:false};
function viewValues(view){return (exploreMap.data?.features||[]).map(f=>f.properties[view.prop]).filter(v=>v!=null&&Number.isFinite(v));}
function quantile(sorted,q){if(!sorted.length)return null;const i=(sorted.length-1)*q,lo=Math.floor(i),hi=Math.ceil(i);return sorted[lo]+(sorted[hi]-sorted[lo])*(i-lo);}
function describe(vals,total){
 const s=[...vals].sort((a,b)=>a-b),n=s.length;
 return {n,total,coverage:total?n/total:0,mean:n?s.reduce((a,b)=>a+b,0)/n:null,median:quantile(s,.5),p10:quantile(s,.1),p25:quantile(s,.25),p75:quantile(s,.75),p90:quantile(s,.9)};
}
/** Spearman rank correlation over segments where both views are measured. */
function spearman(a,b){
 const pairs=(exploreMap.data?.features||[]).map(f=>[f.properties[a.prop],f.properties[b.prop]]).filter(([x,y])=>x!=null&&y!=null);
 const rank=v=>{const idx=v.map((x,i)=>[x,i]).sort((p,q)=>p[0]-q[0]),r=new Array(v.length);let k=0;
  while(k<idx.length){let j=k;while(j+1<idx.length&&idx[j+1][0]===idx[k][0])j++;for(let t=k;t<=j;t++)r[idx[t][1]]=(k+j)/2;k=j+1;}return r;};
 const n=pairs.length;if(n<3)return {n,rho:null};
 const rx=rank(pairs.map(p=>p[0])),ry=rank(pairs.map(p=>p[1])),mx=(n-1)/2;let num=0,dx=0,dy=0;
 for(let i=0;i<n;i++){num+=(rx[i]-mx)*(ry[i]-mx);dx+=(rx[i]-mx)**2;dy+=(ry[i]-mx)**2;}
 return {n,rho:num/Math.sqrt(dx*dy)};
}
function histogram(vals,bins=10){const h=new Array(bins).fill(0);for(const v of vals)h[Math.min(bins-1,Math.floor(v/100*bins))]++;return h;}
function histSvg(h,color,w=230,ht=54){
 const max=Math.max(1,...h),bw=w/h.length;
 return `<svg viewBox="0 0 ${w} ${ht}" class="ea-hist" role="img" aria-label="Distribution 0 to 100">${h.map((c,i)=>`<rect x="${i*bw+1}" y="${ht-2-(ht-4)*c/max}" width="${bw-2}" height="${(ht-4)*c/max}" fill="${color}" rx="1.5"><title>${i*10}–${i*10+10}: ${c} segments</title></rect>`).join('')}</svg>`;
}
const f1=v=>v==null?'N/A':Math.round(v*10)/10;
let REGISTRY=null;
async function loadRegistry(){return REGISTRY||(REGISTRY=streetwiseJson('./data/registry.json').catch(e=>{REGISTRY=null;throw e;}));}
async function renderExploreAnalytics(){
 const root=$('exploreAnalytics');if(!root||!exploreMap.data)return;
 const v=exploreView(),total=exploreMap.data.features.length,d=describe(viewValues(v),total);
 const other=EXPLORE_VIEWS[exploreStats.compare===exploreMap.view?(exploreMap.view+1)%EXPLORE_VIEWS.length:exploreStats.compare],d2=describe(viewValues(other),total),cor=spearman(v,other);
 const meta=exploreMap.data.metadata;
 let datasets='';
 if(v.dim!=null){
  const ind=meta.indicators[meta.keys[v.dim]];let reg=null;try{reg=await loadRegistry();}catch(e){}
  const srcIds=[...new Set(ind.map(x=>x.source))];
  datasets=srcIds.map(s=>{const label=meta.source_labels?.[s]||s,url=meta.sources?.[s];
   const row=reg?.datasets.find(r=>r.source_url&&url&&url.includes((r.source_url.split('/resource/')[1]||'~').split('.')[0]))||null;
   return `<li><strong>${esc(label)}</strong>${url?` · <a href="${esc(url.replace(/\/query$/,''))}" target="_blank" rel="noopener">source</a>`:''}${row?` · ${esc(row.license)} · publisher update ${esc(row.publisher_updated_at||'n/a')}`:''}<br><small>${esc(ind.filter(x=>x.source===s).map(x=>`${x.label}: ${x.method}`).join(' · '))}</small></li>`;}).join('');
 }
 root.innerHTML=`<details ${exploreStats.open?'open':''} id="eaDetails"><summary>Analytics · ${esc(v.label)}</summary>
  <div class="ea-grid"><div><span>Segments with data</span><strong>${d.n.toLocaleString()}</strong><small>of ${total.toLocaleString()} (${Math.round(d.coverage*100)}%)</small></div>
   <div><span>Mean · median</span><strong>${f1(d.mean)} · ${f1(d.median)}</strong><small>P10 ${f1(d.p10)} · P25 ${f1(d.p25)} · P75 ${f1(d.p75)} · P90 ${f1(d.p90)}</small></div></div>
  ${histSvg(histogram(viewValues(v)),'#E3B55B')}
  <label class="ea-compare">Compare with <select id="eaCompare">${EXPLORE_VIEWS.map((x,i)=>i===exploreMap.view?'':`<option value="${i}" ${x===other?'selected':''}>${esc(x.label)}</option>`).join('')}</select></label>
  ${histSvg(histogram(viewValues(other)),'#4aa3ff')}
  <p class="ea-note">${esc(other.label)}: ${d2.n.toLocaleString()} segments, median ${f1(d2.median)}. Spearman ρ = ${cor.rho==null?'N/A':cor.rho.toFixed(2)} over ${cor.n.toLocaleString()} segments where both are measured.</p>
  ${datasets?`<h4>Datasets behind ${esc(v.label)}</h4><ul class="ea-sources">${datasets}</ul>`:`<p class="ea-note">Overall = mean of the measured dimensions of each segment (N/A dimensions excluded).</p>`}
  <p class="ea-note">Scores rank segments within Manhattan (0–100 percentiles of measured indicators); they are not calibrated experience measurements. Data ${esc(meta.data_version)} · ${esc(meta.score_version)}.</p></details>`;
 $('eaDetails').addEventListener('toggle',e=>{exploreStats.open=e.target.open;});
 $('eaCompare').addEventListener('change',e=>{exploreStats.compare=+e.target.value;renderExploreAnalytics();});
}
function setupExploreAnalytics(){
 const search=$('exploreSearch');
 search?.addEventListener('input',()=>{const q=search.value.trim().toLowerCase();
  document.querySelectorAll('#exploreChips [data-view]').forEach(b=>{b.classList.toggle('hidden',Boolean(q)&&!b.textContent.toLowerCase().includes(q));});});
 $('exploreReset')?.addEventListener('click',()=>{if(state.mapLayersReady)state.map.fitBounds(MANHATTAN_BOUNDS,{padding:30,duration:600,maxZoom:12});if(typeof selectExploreSegment==='function')selectExploreSegment(null);});
}
