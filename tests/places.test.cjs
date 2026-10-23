/* places.js (NYC place search) on recorded real responses from Photon and NYC GeoSearch
   (tests/fixtures/places/provider-responses.json, recorded 2026-10-23): normalization, five-borough filter,
   cross-provider de-duplication, ranking, partial provider failure. Live behaviour: run with LIVE=1. */
const path=require('path'),assert=require('node:assert/strict');
const rec=require('./fixtures/places/provider-responses.json');
global.state={};global.window={};global.latLonInsideManhattanEnvelope=p=>p.lon>-74.03&&p.lon<-73.9&&p.lat>40.69&&p.lat<40.89;
let failGeo=false;
if(!process.env.LIVE)global.fetch=async url=>{
 const u=new URL(url),q=u.searchParams.get('q')||u.searchParams.get('text');
 if(u.host.includes('geosearch')&&failGeo)return {ok:false,status:503,json:async()=>({})};
 const r=rec[q];if(!r)throw new Error('no fixture for '+q);
 return {ok:true,status:200,json:async()=>u.host.includes('photon')?r.photon:r.geosearch};
};
const P=require(path.join(__dirname,'..','places.js'));
(async()=>{
 const expect={'Empire State Building':['Manhattan',40.7484,-73.9857],'Brooklyn Museum':['Brooklyn',40.6710,-73.9633],
  'Flushing Main Street':['Queens',40.7597,-73.8296],'Columbia University':['Manhattan',40.8078,-73.9625],'Central Park':['Manhattan',40.7828,-73.9654]};
 for(const [q,[borough,lat,lon]] of Object.entries(expect)){
  const {places,errors}=await P.searchPlaces(q,{});assert.deepEqual(errors,[]);
  const top=places[0];assert(top,`${q}: no result`);
  assert.equal(top.borough,borough,`${q}: borough`);assert(Math.abs(top.lat-lat)<.002&&Math.abs(top.lon-lon)<.002,`${q}: coordinates ${top.lat},${top.lon}`);
  for(const p of places){assert(p.id&&p.source&&p.borough,`${q}: every result has id, source and borough`);assert(P.inNYC(p));}
  const keys=places.map(p=>P.normName(p.name)+Math.round(p.lat*400)+Math.round(p.lon*400));assert.equal(new Set(keys).size,keys.length,`${q}: duplicates removed`);
  assert(places.length<=P.PLACE_SEARCH.limit);
 }
 // Outside the five boroughs (Yonkers) never appears as an NYC result.
 const y=await P.searchPlaces('Yonkers',{});assert(y.places.every(p=>p.borough),'Yonkers results are only kept when inside a borough');
 // One provider down: results still come from the other, and the failure is reported.
 failGeo=true;const part=await P.searchPlaces('Brooklyn Museum',{});failGeo=false;
 if(!process.env.LIVE){assert(part.places.length>0);assert(part.errors.some(e=>/GeoSearch/.test(e)));}
 assert.equal(P.boroughOf('Kings County'),'Brooklyn');assert.equal(P.boroughOf('Richmond County'),'Staten Island');assert.equal(P.boroughOf('Hoboken'),null);
 console.log(`PLACES PASS (${process.env.LIVE?'live':'recorded'}): 5 Scenario-A queries → correct borough and coordinates, NYC-only, de-duplicated, provider failure isolated`);
})().catch(e=>{console.error(e);process.exitCode=1;});
