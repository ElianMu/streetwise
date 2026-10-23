/* The browser's urban-data geometry (urban-geo.js), run on the real tiles exactly as urban-layers.js does
   (tile selection from the route corridor, then distance filtering), must return the same records as the
   brute-force Python reference over every tile (tests/fixtures/urban-along-route.json, from routing/layers.py). */
const fs=require('fs'),path=require('path'),assert=require('node:assert/strict');
const root=path.join(__dirname,'..');
const G=require(path.join(root,'urban-geo.js'));
const cat=JSON.parse(fs.readFileSync(path.join(root,'data/layers/catalog.json')));G.setProjection(cat.projection);
const ref=JSON.parse(fs.readFileSync(path.join(root,'tests/fixtures/urban-along-route.json')));
const routes=JSON.parse(fs.readFileSync(path.join(root,'tests/fixtures/route-response.json'))).routes;
const byId=Object.fromEntries(cat.datasets.map(d=>[d.id,d]));
function tileFeatures(tileset,box){const m=cat.tilesets[tileset].tiles;return G.tileKeys(box,cat.tile_size_m).filter(k=>m[k]).flatMap(k=>JSON.parse(fs.readFileSync(path.join(root,'data/layers/tiles',tileset,k+'.json'))).features);}
function along(did,coords,dist){const d=byId[did];const feats=tileFeatures(d.tileset,G.lineBox(coords.map(G.xy),dist)).filter(f=>G.matchesFilter(f,d.filter));return G.alongLine(feats,coords,dist);}
let checked=0;
for(const [key,routeId] of [['datasets',ref.route_id],['alt',ref.alt_route_id]]){
 const coords=routes.find(r=>r.route_id===routeId).geometry.coordinates;
 for(const [did,expect] of Object.entries(ref[key])){
  const got=along(did,coords,ref.corridor);
  assert.deepEqual(got.map(h=>h.feature.properties.feature_id).sort(),Object.keys(expect).sort(),`${did}: records along the route differ from the reference`);
  for(const h of got)assert(Math.abs(h.distance-expect[h.feature.properties.feature_id])<0.01,`${did}: distance mismatch`);
  checked++;
 }
}
// Switching routes changes the records (Route A vs Route B).
assert.notDeepEqual(Object.keys(ref.datasets.street_trees).sort(),Object.keys(ref.alt.street_trees).sort());
// Projection accuracy against the WGS84 ellipsoidal geodesic (pyproj, in the fixture): within 0.2 % across Manhattan.
let worst=0;for(const [a,b,geo] of ref.geodesic_pairs){if(geo<50)continue;const pa=G.xy(a),pb=G.xy(b);worst=Math.max(worst,Math.abs(Math.hypot(pa[0]-pb[0],pa[1]-pb[1])-geo)/geo);}
assert(worst<0.002,`projection error ${worst}`);
// Polygon logic: a line through a polygon is at distance 0; coverage of a line inside it is 1.
const sq={type:'Polygon',coordinates:[[[-73.99,40.75],[-73.98,40.75],[-73.98,40.76],[-73.99,40.76],[-73.99,40.75]]]};
assert.equal(G.distanceToLine(G.project(sq),[[-74.0,40.755],[-73.97,40.755]].map(G.xy)),0);
assert.equal(G.shareInside([{properties:{feature_id:'s'},geometry:sq}],[[-73.988,40.752],[-73.982,40.758]]),1);
console.log(`URBAN GEO PASS: ${checked} dataset/route combinations identical to the brute-force reference; projection error ${(worst*100).toFixed(3)} %`);
