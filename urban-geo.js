/* Geometry for the Navigate urban data layers: metric projection, tile lookup, corridor filtering, nearest
   distance and coverage. Shared by the browser (urban-layers.js) and tests (tests/urban-geo.test.cjs).
   Distances use a local equirectangular projection with WGS84 scales at 40.78°N (the catalog's `projection`),
   within 0.15 % of the WGS84 geodesic across Manhattan; raw lon/lat degrees are never used as distances. */
(function(root){
'use strict';
let P={lat0:40.78,mx:84414.3,my:111049.7};  // replaced by catalog.projection when the catalog loads
function setProjection(p){if(p&&p.mx&&p.my)P={lat0:p.lat0,mx:p.mx,my:p.my};}
const xy=c=>[c[0]*P.mx,c[1]*P.my];
function haversineM(a,b){const R=6371008.8,r=Math.PI/180,dl=(b[1]-a[1])*r,dn=(b[0]-a[0])*r;const s=Math.sin(dl/2)**2+Math.cos(a[1]*r)*Math.cos(b[1]*r)*Math.sin(dn/2)**2;return 2*R*Math.asin(Math.sqrt(s));}
/** Geometry → {kind, polys:[[ring,...],...] (polygons) | lines:[[p,...]] | points:[p]} in metres. */
function project(g){
 const t=g.type,c=g.coordinates;
 if(t==='Point')return {kind:'point',points:[xy(c)]};
 if(t==='MultiPoint')return {kind:'point',points:c.map(xy)};
 if(t==='LineString')return {kind:'line',lines:[c.map(xy)]};
 if(t==='MultiLineString')return {kind:'line',lines:c.map(l=>l.map(xy))};
 if(t==='Polygon')return {kind:'polygon',polys:[c.map(r=>r.map(xy))]};
 if(t==='MultiPolygon')return {kind:'polygon',polys:c.map(p=>p.map(r=>r.map(xy)))};
 return {kind:null};
}
function bboxOf(pg){let x0=Infinity,y0=Infinity,x1=-Infinity,y1=-Infinity;const add=p=>{if(p[0]<x0)x0=p[0];if(p[0]>x1)x1=p[0];if(p[1]<y0)y0=p[1];if(p[1]>y1)y1=p[1];};
 if(pg.points)pg.points.forEach(add);if(pg.lines)pg.lines.forEach(l=>l.forEach(add));if(pg.polys)pg.polys.forEach(p=>p.forEach(r=>r.forEach(add)));return [x0,y0,x1,y1];}
function ptSeg(p,a,b){const ux=b[0]-a[0],uy=b[1]-a[1],l2=ux*ux+uy*uy;const t=l2?Math.max(0,Math.min(1,((p[0]-a[0])*ux+(p[1]-a[1])*uy)/l2)):0;return Math.hypot(p[0]-a[0]-t*ux,p[1]-a[1]-t*uy);}
const cross=(a,b,c)=>(b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0]);
function segSeg(a,b,c,d){if(cross(a,b,c)*cross(a,b,d)<0&&cross(c,d,a)*cross(c,d,b)<0)return 0;return Math.min(ptSeg(a,c,d),ptSeg(b,c,d),ptSeg(c,a,b),ptSeg(d,a,b));}
function inRing(p,r){let yes=false;for(let i=0,j=r.length-1;i<r.length;j=i++){const a=r[i],b=r[j];if((a[1]>p[1])!==(b[1]>p[1])&&p[0]<(b[0]-a[0])*(p[1]-a[1])/(b[1]-a[1])+a[0])yes=!yes;}return yes;}
/** Point inside a polygon (outer ring, not in a hole). */
function inPolys(p,polys){return polys.some(rings=>inRing(p,rings[0])&&!rings.slice(1).some(h=>inRing(p,h)));}
/** Metres between a projected feature and a projected polyline (0 when they touch, cross or the line enters a polygon). */
function distanceToLine(pg,line){
 let best=Infinity;
 if(pg.kind==='polygon'){for(const p of line)if(inPolys(p,pg.polys))return 0;
  for(const rings of pg.polys)for(const r of rings)for(let i=1;i<r.length;i++)for(let k=1;k<line.length;k++){const d=segSeg(r[i-1],r[i],line[k-1],line[k]);if(d<best){best=d;if(!d)return 0;}}return best;}
 if(pg.kind==='line'){for(const l of pg.lines)for(let i=1;i<l.length;i++)for(let k=1;k<line.length;k++){const d=segSeg(l[i-1],l[i],line[k-1],line[k]);if(d<best){best=d;if(!d)return 0;}}return best;}
 if(pg.kind==='point'){for(const p of pg.points)for(let k=1;k<line.length;k++){const d=ptSeg(p,line[k-1],line[k]);if(d<best)best=d;}return best;}
 return Infinity;
}
function lineBox(line,pad){let x0=Infinity,y0=Infinity,x1=-Infinity,y1=-Infinity;for(const p of line){if(p[0]<x0)x0=p[0];if(p[0]>x1)x1=p[0];if(p[1]<y0)y0=p[1];if(p[1]>y1)y1=p[1];}return [x0-pad,y0-pad,x1+pad,y1+pad];}
/** Tile keys "tx_ty" that a metric box touches. */
function tileKeys(box,size){const out=[];for(let tx=Math.floor(box[0]/size);tx<=Math.floor(box[2]/size);tx++)for(let ty=Math.floor(box[1]/size);ty<=Math.floor(box[3]/size);ty++)out.push(tx+'_'+ty);return out;}
function lonLatBox(w,s,e,n){const a=xy([w,s]),b=xy([e,n]);return [a[0],a[1],b[0],b[1]];}
const overlaps=(a,b)=>a[0]<=b[2]&&a[2]>=b[0]&&a[1]<=b[3]&&a[3]>=b[1];
/** Features within `distance` metres of a lon/lat polyline, de-duplicated by feature_id, with their distance. */
function alongLine(features,coords,distance){
 const line=coords.map(xy),box=lineBox(line,distance),seen=new Set(),out=[];
 for(const f of features){const id=f.properties.feature_id;if(seen.has(id))continue;seen.add(id);
  const pg=project(f.geometry);if(!overlaps(bboxOf(pg),box))continue;
  const d=distanceToLine(pg,line);if(d<=distance)out.push({feature:f,distance:d});}
 return out;
}
/** Nearest feature to a polyline (searching the features given), or null. */
function nearest(features,coords){const line=coords.map(xy);let best=null;const seen=new Set();
 for(const f of features){const id=f.properties.feature_id;if(seen.has(id))continue;seen.add(id);const d=distanceToLine(project(f.geometry),line);if(!best||d<best.distance)best={feature:f,distance:d};}return best;}
/** Share of a polyline's length (sampled every ~5 m) that lies inside the given polygon features. */
function shareInside(features,coords){
 const line=coords.map(xy),polys=features.map(f=>project(f.geometry)).filter(p=>p.kind==='polygon');let total=0,inside=0;
 for(let k=1;k<line.length;k++){const a=line[k-1],b=line[k],len=Math.hypot(b[0]-a[0],b[1]-a[1]),n=Math.max(1,Math.round(len/5));
  for(let i=0;i<n;i++){const t=(i+.5)/n,p=[a[0]+(b[0]-a[0])*t,a[1]+(b[1]-a[1])*t];total+=len/n;if(polys.some(pg=>inPolys(p,pg.polys)))inside+=len/n;}}
 return total?inside/total:0;
}
function lengthM(coords){const l=coords.map(xy);let s=0;for(let i=1;i<l.length;i++)s+=Math.hypot(l[i][0]-l[i-1][0],l[i][1]-l[i-1][1]);return s;}
function matchesFilter(f,flt){if(!flt)return true;return Object.entries(flt).every(([k,vals])=>vals.includes(f.properties[k]));}
root.UrbanGeo={setProjection,xy,haversineM,project,bboxOf,distanceToLine,inPolys,tileKeys,lonLatBox,lineBox,alongLine,nearest,shareInside,lengthM,matchesFilter};
if(typeof module!=='undefined')module.exports=root.UrbanGeo;
})(typeof globalThis!=='undefined'?globalThis:this);
