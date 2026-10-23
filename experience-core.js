/* Pure spatial computations shared by map, route ranking and tests. No fabricated observations. */
(function(root){
'use strict';
const names=['Architecture','Nature','Culture','Quiet & Relax','Spatial Comfort','Urban Vibrancy','Food & Retail','Scenic & Visual','Walkability','Access & Safety','Environment','Transit Connectivity'];
const keys=['architecture','nature','culture','quiet','spatial_comfort','urban_vibrancy','food_retail','scenic_visual','walkability','access_safety','environment','transit_connectivity'];
const X=111320*Math.cos(40.76*Math.PI/180),Y=111320; // local equirectangular metric approximation, Midtown only
const xy=p=>[p[0]*X,p[1]*Y];
const dist=(a,b)=>Math.hypot((a[0]-b[0])*X,(a[1]-b[1])*Y);
function length(c){let n=0;for(let i=1;i<c.length;i++)n+=dist(c[i-1],c[i]);return n;}
function pointSegment(p,a,b){const u=[b[0]-a[0],b[1]-a[1]],v=[p[0]-a[0],p[1]-a[1]],l=u[0]*u[0]+u[1]*u[1];const t=l?Math.max(0,Math.min(1,(v[0]*u[0]+v[1]*u[1])/l)):0;return Math.hypot(v[0]-t*u[0],v[1]-t*u[1]);}
function pointLine(p,c){p=xy(p);let d=Infinity;for(let i=1;i<c.length;i++)d=Math.min(d,pointSegment(p,xy(c[i-1]),xy(c[i])));return d;}
function cross(a,b,c){return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0]);}
function edgeDistance(a,b,c,d){
 a=xy(a);b=xy(b);c=xy(c);d=xy(d);
 if(cross(a,b,c)*cross(a,b,d)<0&&cross(c,d,a)*cross(c,d,b)<0)return 0;
 return Math.min(pointSegment(a,c,d),pointSegment(b,c,d),pointSegment(c,a,b),pointSegment(d,a,b));
}
function inRing(p,r){let yes=false;for(let i=0,j=r.length-1;i<r.length;j=i++){const a=r[i],b=r[j];if((a[1]>p[1])!==(b[1]>p[1])&&p[0]<(b[0]-a[0])*(p[1]-a[1])/(b[1]-a[1])+a[0])yes=!yes;}return yes;}
function polygonNear(g,c,radius){
 const polygons=g?.type==='Polygon'?[g.coordinates]:g?.type==='MultiPolygon'?g.coordinates:[];
 for(const rings of polygons){
  if(c.some(p=>inRing(p,rings[0])&&!rings.slice(1).some(h=>inRing(p,h))))return true;
  for(const ring of rings)for(let j=1;j<ring.length;j++)for(let i=1;i<c.length;i++)if(edgeDistance(c[i-1],c[i],ring[j-1],ring[j])<=radius)return true;
 }return false;
}
function covered(c,b,r=75){return !!b&&c.every(p=>p[0]>=b[0]+r/X&&p[0]<=b[2]-r/X&&p[1]>=b[1]+r/Y&&p[1]<=b[3]-r/Y);}
function unique(fs){const seen=new Set();return fs.filter(f=>{const p=f.properties||{};const id=p.tree_id??p.OBJECTID??p.FID??f.id??JSON.stringify(f.geometry);if(seen.has(String(id)))return false;seen.add(String(id));return true;});}
function evidence(c,raw,bbox,radius=75){
 const result={nature:null,architecture:null,tree_count:null,lpc_count:null};const m=length(c);
 if(m<1||!covered(c,bbox,radius))return result;
 if(raw.trees){result.tree_count=unique(raw.trees).filter(f=>f.geometry?.type==='Point'&&String(f.properties?.status||'').toLowerCase()==='alive'&&pointLine(f.geometry.coordinates,c)<=radius).length;result.nature=result.tree_count/(m/1000);}
 if(raw.lpc){result.lpc_count=unique(raw.lpc).filter(f=>polygonNear(f.geometry,c,radius)).length;result.architecture=result.lpc_count/(m/1000);}
 return result;
}
function hash(s){let n=2166136261;for(let i=0;i<s.length;i++){n^=s.charCodeAt(i);n=Math.imul(n,16777619);}return (n>>>0).toString(16);}
function feature(c,id,raw,bbox,extra={}){
 const p={segment_id:id,length_m:length(c),...Object.fromEntries(keys.map(k=>[k+'_score',null])),...extra,...evidence(c,raw,bbox)};
 p.score_status='Not calibrated; NULL is not zero';p.nature_source='NYC Open Data 2015 Tree Census';p.nature_year=2015;p.architecture_source='NYC LPC individual-landmark parcels (ArcGIS mirror)';p.architecture_year=null;p.buffer_m=75;p.method='75m proximity / segment km; living 2015 trees and LPC parcel presence; local metric approximation';
 return {type:'Feature',properties:p,geometry:{type:'LineString',coordinates:c}};
}
function split(c,max=80){let out=[],part=[c[0]],used=0;for(let i=1;i<c.length;i++){let a=part.at(-1),b=c[i],d=dist(a,b);while(used+d>max){const t=(max-used)/d,p=[a[0]+(b[0]-a[0])*t,a[1]+(b[1]-a[1])*t];part.push(p);out.push(part);part=[p];a=p;d=dist(a,b);used=0;}part.push(b);used+=d;}if(length(part)>1)out.push(part);return out;}
function routeSegments(route,raw,bbox){return split(route.coords).map(c=>feature(c,'walk-'+hash(JSON.stringify(c)),raw,bbox,{route_id:route.id,street_name:'Pedestrian route section',network:'Valhalla pedestrian shape; geometry-derived section ID, not OSM edge ID'}));}
function aggregate(features,key){if(!features.length||features.some(f=>!Number.isFinite(f.properties[key])))return null;const total=features.reduce((s,f)=>s+f.properties.length_m,0);return total?features.reduce((s,f)=>s+f.properties[key]*f.properties.length_m,0)/total:null;}
function streets(fc,raw,bbox){return (fc?.features||[]).flatMap(f=>{const g=f.geometry,parts=g?.type==='LineString'?[g.coordinates]:g?.type==='MultiLineString'?g.coordinates:[];return parts.filter(c=>covered(c,bbox)).map((c,i)=>feature(c,'nyc-'+(f.properties?.FID??f.id??hash(JSON.stringify(c)))+'-'+i,raw,bbox,{street_name:f.properties?.st_label||f.properties?.st_name||'Unnamed centerline',network:'NYC centerline; pedestrian access not verified'}));});}
root.ExperienceCore={names,keys,X,Y,length,pointLine,polygonNear,covered,evidence,feature,split,routeSegments,aggregate,streets};
if(typeof module!=='undefined')module.exports=root.ExperienceCore;
})(globalThis);
