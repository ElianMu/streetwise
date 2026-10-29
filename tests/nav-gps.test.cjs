/* Replayable GPS-track tests for nav-engine.js on a real STREETWISE itinerary (tests/fixtures/nav-route.json:
   Bryant Park → Rockefeller Center (stop) → Radio City, built by routing/itinerary.py). Tracks are synthetic and
   deterministic (seeded noise) so every run gives the same Pass / Fail. Real-device behaviour is NOT covered here. */
const assert=require('node:assert/strict'),path=require('path');
const {NavEngine,formatNavDistance,spokenInstruction,NAV_TRANSITIONS}=require(path.join(__dirname,'..','nav-engine.js'));
const route=require('./fixtures/nav-route.json');
let seed=7;const rnd=()=>((seed=(seed*16807)%2147483647)/2147483647);
const gauss=()=>{let u=0,v=0;while(!u)u=rnd();while(!v)v=rnd();return Math.sqrt(-2*Math.log(u))*Math.cos(2*Math.PI*v);};
const M=[84414.3,111049.7];
const offset=(p,dx,dy)=>[p[0]+dx/M[0],p[1]+dy/M[1]];
function walk(eng,from,to,{speed=1.35,dt=1,noise=4,acc=8,t0=0}={}){
 // positions along the route itself (ground truth = route metres), with GPS noise
 const fixes=[];let s=from,t=t0;
 while(from<to?s<=to:s>=to){const p=eng.pointAt(s);fixes.push({truth:s,fix:{...lonlat(offset(p,gauss()*noise,gauss()*noise)),accuracy:acc,timestamp:t*1000,speed}});s+=(from<to?1:-1)*speed*dt;t+=dt;}
 return fixes;
}
const lonlat=p=>({lon:p[0],lat:p[1]});
function fresh(){const e=new NavEngine(JSON.parse(JSON.stringify(route)));const ev=[];e.on(x=>ev.push(x));e.transition('READY');e.transition('STARTING');return [e,ev];}
const results=[];const test=(name,fn)=>{try{fn();results.push(['PASS',name]);}catch(err){results.push(['FAIL',name,err.message]);}};
const stopM=route.maneuvers.find(m=>m.type==='arrive_stop').distance_along_route_m;

test('normal walking: progress follows truth, monotonic, turn alerts once each in order',()=>{
 const [e,ev]=fresh();let last=0,maxErr=0;
 for(const {truth,fix} of walk(e,0,stopM-30)){const o=e.update(fix);assert(o.progress_m>=last,'progress never moves back');last=o.progress_m;maxErr=Math.max(maxErr,Math.abs(o.progress_m-truth));}
 assert(maxErr<25,`progress error ${maxErr.toFixed(1)} m`);assert.equal(e.state,'NAVIGATING');
 const alerts=ev.filter(x=>x.type==='alert');const keys=alerts.map(a=>a.maneuver.maneuver_id+a.level);
 assert.equal(new Set(keys).size,keys.length,'no repeated alert');
 const turn5=alerts.filter(a=>a.maneuver.instruction_text==='Turn left onto 5th Ave').map(a=>a.level);
 assert(turn5.includes('now'),'turn-now alert for 5th Ave');assert(!turn5.includes('early')||turn5.indexOf('early')<turn5.indexOf('now'));
});
test('distance to next maneuver is along the route, not straight-line',()=>{
 const [e]=fresh();for(const {fix} of walk(e,0,300))e.update(fix);
 const o=e.lastOutput;const nm=o.next_maneuver;assert.equal(nm.instruction_text,'Turn left onto W 49th St');
 assert(Math.abs(o.distance_to_next_m-(nm.distance_along_route_m-o.progress_m))<=1);
});
test('standing still: progress stays, no alerts storm, no off-route',()=>{
 const [e,ev]=fresh();const p=e.pointAt(400);
 for(let i=0;i<120;i++)e.update({...lonlat(offset(p,gauss()*5,gauss()*5)),accuracy:10,timestamp:i*1000,speed:0});
 const ps=ev.filter(x=>x.type==='update').map(x=>x.output.progress_m);
 assert(Math.max(...ps.slice(5))-Math.min(...ps.slice(5))<15,'progress jitter bounded');assert(!['OFF_ROUTE','POSSIBLY_OFF_ROUTE'].includes(e.state));
});
test('drift in tall-building canyon (σ 20 m, accuracy 35 m): no false off-route',()=>{
 const [e,ev]=fresh();for(const {fix} of walk(e,250,700,{noise:20,acc:35}))e.update(fix);
 assert(!ev.some(x=>x.type==='off_route'),'drift is not off-route');
});
test('single GPS jump of 150 m: ignored, progress does not leap',()=>{
 const [e]=fresh();const tr=walk(e,0,400);for(const {fix} of tr.slice(0,200))e.update(fix);const before=e.progress;
 const p=e.pointAt(e.progress);e.update({...lonlat(offset(p,0,150)),accuracy:10,timestamp:200*1000});
 assert(e.progress-before<20,'no leap forward');assert.notEqual(e.state,'OFF_ROUTE','one fix never confirms off-route');
 for(const {fix} of tr.slice(201))e.update(fix);assert.equal(e.state,'NAVIGATING');
});
test('GPS loss then stale: GPS_WEAK; recovery resumes navigation',()=>{
 const [e]=fresh();const tr=walk(e,0,500);for(const {fix} of tr.slice(0,100))e.update(fix);
 e.tick(100*1000+20000);assert.equal(e.state,'GPS_WEAK');
 for(const {fix} of walk(e,180,260,{t0:130}))e.update(fix);assert.equal(e.state,'NAVIGATING');assert(e.progress>170);
});
test('off-route still confirmed when intermittent location errors interleave the off-route fixes',()=>{
 // Regression (Mobile v2 E2E): a watchPosition error between fixes puts the engine in GPS_WEAK (nav-ui onFixError),
 // the next good fix returns it to NAVIGATING ("accuracy recovered") — and NAVIGATING may not jump straight to
 // OFF_ROUTE in NAV_TRANSITIONS, so the confirmation used to fail silently forever and no reroute ever happened.
 const [e,ev]=fresh();for(const {fix} of walk(e,0,450))e.update(fix);
 const p=e.pointAt(450);
 for(let i=1;i<=12;i++){e.transition('GPS_WEAK','');e.update({...lonlat(offset(p,300+i*2,0)),accuracy:8,timestamp:(340+i*1.6)*1000});}
 assert.equal(ev.filter(x=>x.type==='off_route').length,1,'off-route raised exactly once');assert.equal(e.state,'OFF_ROUTE');
});
test('a single off-route fix after an error is still only "possibly" off route',()=>{
 const [e,ev]=fresh();for(const {fix} of walk(e,0,450))e.update(fix);
 e.transition('GPS_WEAK','');e.update({...lonlat(offset(e.pointAt(450),300,0)),accuracy:8,timestamp:341000});
 assert(!ev.some(x=>x.type==='off_route'));assert.notEqual(e.state,'OFF_ROUTE');
});
test('poor accuracy (80 m): GPS_WEAK and no off-route decision',()=>{
 const [e,ev]=fresh();for(const {fix} of walk(e,0,200,{acc:80,noise:30}))e.update(fix);
 assert.equal(e.state,'GPS_WEAK');assert(!ev.some(x=>x.type==='off_route'));
});
test('leaving the route: possibly → confirmed off-route once; back on route recovers',()=>{
 const [e,ev]=fresh();for(const {fix} of walk(e,0,450))e.update(fix);
 const p=e.pointAt(450);let t=1000;
 for(let i=1;i<=20;i++)e.update({...lonlat(offset(p,i*6,0)),accuracy:8,timestamp:(340+i)*1000});
 assert.equal(ev.filter(x=>x.type==='off_route').length,1,'off-route raised exactly once');assert.equal(e.state,'OFF_ROUTE');
 for(let i=20;i>=0;i--)e.update({...lonlat(offset(p,i*6,0)),accuracy:8,timestamp:(361+20-i)*1000});
 assert.equal(e.state,'NAVIGATING','back on the route');
});
test('walking direction reversed: progress follows back only after consistent evidence',()=>{
 const [e]=fresh();for(const {fix} of walk(e,0,600))e.update(fix);const top=e.progress;
 const back=walk(e,600,450,{t0:500});e.update(back[0].fix);e.update(back[12].fix);assert(e.progress>=top-1,'two fixes do not pull progress back');
 for(const {fix} of back)e.update(fix);assert(e.progress<top-60,'sustained reversal is followed');
});
test('consecutive close maneuvers are announced in order without skipping',()=>{
 const [e,ev]=fresh();for(const {fix} of walk(e,0,130,{speed:1.0}))e.update(fix);
 const order=ev.filter(x=>x.type==='alert'&&x.level==='now').map(x=>x.maneuver.distance_along_route_m);
 assert.deepEqual(order,[...order].sort((a,b)=>a-b));assert(order.length>=2,'stairs/path turns near the start announced');
});
test('stop arrival: ARRIVED_AT_STOP once; continue resumes; final arrival',()=>{
 const [e,ev]=fresh();for(const {fix} of walk(e,0,stopM+3))e.update(fix);
 assert.equal(e.state,'ARRIVED_AT_STOP');assert.equal(ev.filter(x=>x.type==='arrived_stop').length,1);
 for(const {fix} of walk(e,stopM,stopM+10,{t0:2000}))e.update(fix);assert.equal(e.state,'ARRIVED_AT_STOP','waits for the user');
 e.continueFromStop();assert.equal(e.state,'NAVIGATING');
 for(const {fix} of walk(e,stopM+10,route.distance_m,{t0:2100}))e.update(fix);
 assert.equal(e.state,'ARRIVED');assert.equal(ev.filter(x=>x.type==='arrived').length,1);
});
test('state machine rejects invalid transitions (no double start / reroute)',()=>{
 const [e]=fresh();assert.equal(e.transition('STARTING'),true);assert.equal(e.transition('REROUTING'),false);
 for(const [from,tos] of Object.entries(NAV_TRANSITIONS))for(const to of tos)assert(NAV_TRANSITIONS[to],`unknown state ${to} from ${from}`);
});
test('units and spoken text come from engine maneuvers',()=>{
 assert.equal(formatNavDistance(28),'30 m');assert.equal(formatNavDistance(28,'imperial'),'90 ft');assert.equal(formatNavDistance(2400,'imperial'),'1.5 mi');
 const m=route.maneuvers.find(x=>x.instruction_text==='Turn left onto 5th Ave');
 assert.equal(spokenInstruction(m,30),'In 30 meters, turn left onto 5th Ave');assert.equal(spokenInstruction(m,30,'zh'),'前方约30米，'+m.instruction_zh);
});
test('bearingAt: the route\'s own forward direction, for Route-Up and the honest no-compass fallback',()=>{
 const [e]=fresh();
 // On the straight stretch between the W 42nd St and 5th Ave turns, the route bearing should read close to the
 // W 42nd St maneuver's own bearing_after (119°) — not some other direction, and not null.
 const b=e.bearingAt(150);
 assert(b!=null,'a real stretch of route has a bearing');
 assert(Math.abs(((b-119+540)%360)-180)<15,`bearing ${b.toFixed(1)}° should be close to 119°`);
 assert(e.bearingAt(0)!=null,'bearing at the very start of the route is defined');
 assert(e.bearingAt(route.distance_m)!=null,'bearing at the very end of the route is defined');
});
test('validation gate: a failed route cannot navigate',()=>{
 const bad={...JSON.parse(JSON.stringify(route)),validation:{navigation_allowed:false,blocking_issues:['gap']}};
 assert.deepEqual(new NavEngine(bad).blocked,['gap']);
});
for(const r of results)console.log(r[0],r[1],r[2]?'— '+r[2]:'');
const failed=results.filter(r=>r[0]==='FAIL').length;
console.log(`NAV GPS ${failed?'FAILED':'PASS'}: ${results.length-failed}/${results.length} replayed scenarios`);
if(failed)process.exitCode=1;
