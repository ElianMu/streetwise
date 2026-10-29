/* Cartographic design system rules (urban-style.js): the selected route is the only warm-white line on the map (round 9; was lime),
   every catalog category has a colour, zoom tiers are ordered, and every map expression keeps ['zoom'] at the
   top level (MapLibre silently drops a layer otherwise). */
const fs=require('fs'),path=require('path'),assert=require('node:assert/strict');
const root=path.join(__dirname,'..');
const S=require(path.join(root,'urban-style.js')),T=S.T;
const cat=JSON.parse(fs.readFileSync(path.join(root,'data/layers/catalog.json')));
const hue=h=>{const r=parseInt(h.slice(1,3),16)/255,g=parseInt(h.slice(3,5),16)/255,b=parseInt(h.slice(5,7),16)/255,mx=Math.max(r,g,b),mn=Math.min(r,g,b),d=mx-mn;
 if(!d)return {h:0,s:0};const H=mx===r?((g-b)/d+6)%6:mx===g?(b-r)/d+2:(r-g)/d+4;return {h:H*60,s:d/(1-Math.abs(mx+mn-1))};};
const lum=h=>{const r=parseInt(h.slice(1,3),16),g=parseInt(h.slice(3,5),16),b=parseInt(h.slice(5,7),16);return (Math.max(r,g,b)+Math.min(r,g,b))/510;};
const routeLike=h=>lum(h)>.84&&hue(h).s<.45; // warm white / near white
assert(routeLike(T.route.selected),'route is warm white');
const dataColours=[...Object.values(T.cat),...Object.values(S.LINES).map(l=>l.color),T.building.neutral,...T.building.height.stops.map(s=>s[1]),...T.building.age.stops.map(s=>s[1]),...T.building.landuse.classes.map(c=>c[1])];
for(const c of dataColours)assert(!routeLike(c),`data colour ${c} could be mistaken for the selected route`);
for(const c of cat.categories)assert(T.cat[c.id],`category ${c.id} has no colour token`);
assert(T.zoom.neighbourhood<T.zoom.street&&T.zoom.street<T.zoom.detail);
assert(T.label.minZoom>=T.zoom.detail,'labels only at detail zoom');
// ['zoom'] may only appear as the input of a top-level interpolate/step.
function zoomNested(e,top=true){if(!Array.isArray(e))return false;if(e[0]==='zoom')return !top;
 const input=e[0]==='interpolate'?2:e[0]==='step'?1:-1;return e.slice(1).some((x,j)=>zoomNested(x,top&&j+1===input));}
for(const [k,v] of Object.entries({tree:T.tree.radius,cluster:T.cluster.radius,ramp:S.rampExpr('h',T.building.height.stops)}))assert(!zoomNested(v),`${k} nests zoom`);
const src=['urban-layers.js','explore-map.js','app.js','center-map.js'].map(f=>fs.readFileSync(path.join(root,f),'utf8')).join('\n');
assert(!/\['\*',[\d.]+,width\]/.test(src),'no scaled zoom ramps');
// Browser APIs called unbound throw "Illegal invocation" (jsdom does not catch this): never store them in arrays/objects.
assert(!/\[\s*requestAnimationFrame\s*,/.test(src),'requestAnimationFrame must be wrapped, not stored unbound');
assert.equal(S.shade('#7cb68a',0,1),'#7cb68a');assert.notEqual(S.shade('#7cb68a',0,3),S.shade('#7cb68a',2,3));
console.log(`URBAN STYLE PASS: route is the only warm-white line (${dataColours.length} data colours checked), ${cat.categories.length} category tokens, ordered zoom tiers, no nested zoom expressions`);
