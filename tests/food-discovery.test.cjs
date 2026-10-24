/* Nearby query transport is mocked; source fixture is a shipped real place. */
const {JSDOM}=require(process.env.JSDOM_PATH||'jsdom'),fs=require('fs'),path=require('path'),vm=require('vm'),assert=require('node:assert/strict');
const root=path.join(__dirname,'..'),dom=new JSDOM('',{runScripts:'outside-only',url:'https://fixture.invalid/'}),w=dom.window,ctx=dom.getInternalVMContext();
const real=JSON.parse(fs.readFileSync(path.join(root,'data/places/restaurants.json'))).records.find(r=>r.src==='osm'&&r.addr);
const requests=[];w.record=real;
vm.runInContext(`function haversineKm(a,b){return Math.hypot((a.lon-b.lon)*84.4143,(a.lat-b.lat)*111.0497);}const requests=window.requests;`,ctx);
w.requests=requests;
// Only the nearby API is offered. Access to the large static file is an error.
w.streetwiseJson=async url=>{requests.push(String(url));assert(String(url).startsWith('/api/places/search?'));return {results:[{
 place_id:real.cid,index_id:real.id,name:real.name,category:'restaurants',coordinates:{lat:real.lat,lon:real.lon},address:real.addr,data_sources:['OpenStreetMap'],
 restaurant:{cuisine:real.cuisine,inspection:null},routing_coverage:'manhattan_network'}]};};
vm.runInContext(fs.readFileSync(path.join(root,'journey.js'),'utf8'),ctx);
(async()=>{
 const records=await vm.runInContext(`foodRecordsNearPath(['restaurants'],[{lat:record.lat,lon:record.lon},{lat:record.lat+.005,lon:record.lon}],1.2,null)`,ctx);
 assert.equal(records.length,1);assert.equal(records[0].id,real.id);assert.equal(records[0].name,real.name);assert(requests.length>=1);
 assert(requests.every(u=>!u.includes('restaurants.json')));assert(requests.every(u=>new URL(u,'https://fixture.invalid').searchParams.get('limit')==='50'));
 assert.equal(vm.runInContext(`foodListingEligible({src:'dohmh',insp:'1900-01-01'})`,ctx),false);
 assert.equal(vm.runInContext(`foodListingEligible({src:'osm',access:'private'})`,ctx),false);
 console.log('FOOD DISCOVERY PASS: bounded nearby records retain real source IDs; no full restaurant JSON request; restricted/uninspected listings excluded');
})().catch(e=>{console.error(e);process.exitCode=1;}).finally(()=>w.close());
