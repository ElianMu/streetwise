'use strict';
/* STREETWISE walking navigation engine (no DOM): map matching, navigation state machine, along-route distances, alerts.
   Input is the selected STREETWISE Route Object (its geometry, ordered edges and server-built maneuvers); nothing here plans
   a route or decides a turn. Continuous GPS stays in the browser; only re-routing calls the server.

   Map matching: each fix is projected onto the route only inside a window around the last matched progress
   (−BACK_M … +forward reach from walking speed, elapsed time and accuracy), scored by perpendicular distance relative to
   accuracy, backward motion, and heading agreement when a trustworthy heading exists. Progress never jumps ahead of what
   walking could cover and only moves backwards after several consistent fixes (the user turned around).
   Off-route: the distance to the route beyond the fix's own uncertainty must exceed OFF_M on OFF_FIXES consecutive fixes
   spanning OFF_SECONDS with usable accuracy; one bad fix only makes the state POSSIBLY_OFF_ROUTE.
   Alert distances are initial, configurable values (not validated standards): they grow with GPS uncertainty and shrink
   when maneuvers are close together. */
const NAV_CONFIG={
 walkMaxMps:2.6,          // brisk walking / light jog; faster apparent motion is treated as GPS jump
 backM:25,                // matching window behind the last progress
 accuracyGoodM:20,accuracyUsableM:50,
 staleSeconds:15,         // no fix for this long: GPS_WEAK
 offM:25,offFixes:3,offSeconds:8,
 earlyM:90,approachM:30,nowM:8,passM:6,
 arriveM:15,
 rerouteMinSeconds:20,
};
const NAV_STATES=['IDLE','READY','STARTING','NAVIGATING','GPS_WEAK','POSSIBLY_OFF_ROUTE','OFF_ROUTE','REROUTING','PAUSED','ARRIVED_AT_STOP','ARRIVED','ERROR','STOPPED'];
// Allowed transitions; anything else is ignored (prevents duplicate starts, double reroutes and repeated arrivals).
const NAV_TRANSITIONS={
 IDLE:['READY'],READY:['STARTING','IDLE'],STARTING:['NAVIGATING','ERROR','STOPPED','READY'],
 NAVIGATING:['GPS_WEAK','POSSIBLY_OFF_ROUTE','PAUSED','ARRIVED_AT_STOP','ARRIVED','STOPPED','ERROR'],
 GPS_WEAK:['NAVIGATING','POSSIBLY_OFF_ROUTE','PAUSED','STOPPED','ARRIVED_AT_STOP','ARRIVED','ERROR'],
 POSSIBLY_OFF_ROUTE:['NAVIGATING','OFF_ROUTE','GPS_WEAK','PAUSED','STOPPED'],
 OFF_ROUTE:['REROUTING','NAVIGATING','PAUSED','STOPPED'],
 REROUTING:['NAVIGATING','OFF_ROUTE','ERROR','STOPPED'],
 PAUSED:['NAVIGATING','STOPPED'],ARRIVED_AT_STOP:['NAVIGATING','STOPPED','ARRIVED'],ARRIVED:['STOPPED','IDLE'],
 ERROR:['READY','STOPPED','REROUTING','NAVIGATING'],STOPPED:['IDLE','READY'],
};
const MX_NAV=84414.3,MY_NAV=111049.7;
const navXY=c=>[c[0]*MX_NAV,c[1]*MY_NAV];
function navBearing(a,b){return (Math.atan2((b[0]-a[0])*MX_NAV,(b[1]-a[1])*MY_NAV)*180/Math.PI+360)%360;}
const angDiff=(a,b)=>Math.abs((a-b+540)%360-180);

class NavEngine{
 constructor(route,opts={}){
  this.cfg={...NAV_CONFIG,...(opts.config||{})};
  this.route=route;this.state='IDLE';this.listeners=[];
  const c=route.geometry.coordinates;this.pts=c.map(navXY);this.cum=[0];
  for(let i=1;i<c.length;i++)this.cum.push(this.cum[i-1]+Math.hypot(this.pts[i][0]-this.pts[i-1][0],this.pts[i][1]-this.pts[i-1][1]));
  this.geoLen=this.cum.at(-1)||1;this.netLen=route.distance_m||this.geoLen;this.k=this.netLen/this.geoLen;  // geometry metres → route metres
  // edge boundaries in route metres (for matched_edge_id)
  this.edgeEnds=[];let run=0;for(const e of route.edges||[]){run+=e.traversed_length_m;this.edgeEnds.push([run,e.edge_id]);}
  this.maneuvers=(route.maneuvers||[]).slice().sort((a,b)=>a.distance_along_route_m-b.distance_along_route_m);
  this.reset(opts.progress_m||0);
  if(route.validation&&route.validation.navigation_allowed===false){this.blocked=route.validation.blocking_issues||['Route failed validation'];}
 }
 reset(progress=0){
  Object.assign(this,{progress,lastFix:null,lastMatchT:null,offCount:0,offSince:null,backCount:0,alerted:{},arrivedStops:new Set(),
   next:this.maneuvers.findIndex(m=>m.distance_along_route_m>progress+this.cfg.passM&&m.type!=='depart'),lastOutput:null});
  if(this.next<0)this.next=this.maneuvers.length-1;
 }
 on(fn){this.listeners.push(fn);}
 emit(ev){for(const fn of this.listeners){try{fn(ev)}catch(e){}}}
 /** Moves the state machine; returns false (and changes nothing) for a transition the table does not allow. */
 transition(to,why=''){
  if(to===this.state)return true;
  if(!(NAV_TRANSITIONS[this.state]||[]).includes(to))return false;
  const from=this.state;this.state=to;this.emit({type:'state',from,to,why});return true;
 }
 pointAt(s){ // route metres → [lon,lat]
  const g=Math.max(0,Math.min(this.geoLen,s/this.k));let lo=0,hi=this.cum.length-1;
  while(lo<hi-1){const m=(lo+hi)>>1;if(this.cum[m]<=g)lo=m;else hi=m;}
  const seg=this.cum[hi]-this.cum[lo],t=seg?(g-this.cum[lo])/seg:0,a=this.pts[lo],b=this.pts[hi];
  return [(a[0]+(b[0]-a[0])*t)/MX_NAV,(a[1]+(b[1]-a[1])*t)/MY_NAV];
 }
 edgeAt(s){for(const [end,id] of this.edgeEnds)if(s<=end+1e-6)return id;return this.edgeEnds.at(-1)?.[1]||null;}
 /** Project p onto route segments whose route-metre span intersects [lo,hi]; best by score. */
 match(p,lo,hi,fix){
  const sAcc=Math.max(8,Math.min(fix.accuracy??30,80));let best=null;
  const head=fix.heading!=null&&Number.isFinite(fix.heading)&&(fix.speed??0)>.6?fix.heading:null;
  for(let i=1;i<this.pts.length;i++){
   const s0=this.cum[i-1]*this.k,s1=this.cum[i]*this.k;if(s1<lo||s0>hi)continue;
   const a=this.pts[i-1],b=this.pts[i],ux=b[0]-a[0],uy=b[1]-a[1],l2=ux*ux+uy*uy;
   let t=l2?((p[0]-a[0])*ux+(p[1]-a[1])*uy)/l2:0;t=Math.max(0,Math.min(1,t));
   let s=(this.cum[i-1]+t*Math.sqrt(l2))*this.k;s=Math.max(lo,Math.min(hi,s));
   const q=navXY(this.pointAt(s)),d=Math.hypot(p[0]-q[0],p[1]-q[1]);
   let score=(d/sAcc)**2;
   if(s<this.progress-3)score+=((this.progress-s)/15)**2;                     // walking backwards is unlikely
   if(head!=null&&l2)score+=angDiff(head,navBearing(this.route.geometry.coordinates[i-1],this.route.geometry.coordinates[i]))>100?2:0;
   if(!best||score<best.score)best={s,d,score};
  }
  return best;
 }
 /** One GPS fix → navigation output. Fix fields may be missing (accuracy, speed, heading). */
 update(fix){
  if(['IDLE','READY','STOPPED','ARRIVED','PAUSED','REROUTING','ERROR'].includes(this.state))return this.lastOutput;
  if(!fix||!Number.isFinite(fix.lat)||!Number.isFinite(fix.lon))return this.lastOutput;
  const t=fix.timestamp??Date.now(),acc=Number.isFinite(fix.accuracy)?fix.accuracy:null;
  const dt=this.lastMatchT!=null?Math.max(.5,(t-this.lastMatchT)/1000):5;
  const quality=acc==null?'unknown':acc<=this.cfg.accuracyGoodM?'good':acc<=this.cfg.accuracyUsableM?'fair':'poor';
  if(this.state==='STARTING')this.transition('NAVIGATING','first fix');
  const p=navXY([fix.lon,fix.lat]);
  const reach=15+this.cfg.walkMaxMps*dt*1.5+Math.min(acc??30,60);
  // first fix (or after a reset): find where on the route the walker is; afterwards stay within the walking window
  let m=this.lastMatchT==null?this.match(p,0,this.netLen,fix):this.match(p,this.progress-this.cfg.backM,this.progress+reach,fix);
  if(this.lastMatchT==null&&m){
   // where the route passes near itself, an equally plausible earlier position wins (the walk has just begun)
   const earlier=m.s>1?this.match(p,0,m.s-1,fix):null;
   if(earlier&&earlier.d<=m.d+Math.max(5,(acc??20)/2))m=earlier;
   // standing at the route start (Start Navigation checks this): begin at 0 m
   const s0=navXY(this.route.geometry.coordinates[0]),d0=Math.hypot(p[0]-s0[0],p[1]-s0[1]);
   if(this.progress===0&&d0<=Math.max(25,2*(acc??20)))m={s:0,d:d0,score:0};
   if(m.d<=Math.max(35,2.5*(acc??20)))this.progress=m.s;
  }
  // rejoin after a long gap anywhere ahead (never behind) when the windowed match is far away
  if(m&&m.d>40&&dt>20){const g=this.match(p,this.progress,this.netLen,fix);if(g&&g.d<m.d)m=g;}
  const out={timestamp:t,accuracy_m:acc,location_quality:quality,raw:[fix.lon,fix.lat]};
  if(!m){this.lastFix=fix;return this.finish(out);}
  const unc=Math.max(0,m.d-(acc??20));
  // An outlier (far beyond its own accuracy) never moves progress; it only counts towards off-route.
  const outlier=m.d>Math.max(35,2.5*(acc??20));
  if(!outlier){
   if(m.s>=this.progress){
    // forward: a deadband the size of the noise stops progress ratcheting up while standing still
    const dead=Math.min(10,Math.max(3,.5*(acc??20)));const still=fix.speed!=null&&fix.speed<.3;
    if(!still&&m.s-dead>this.progress)this.progress=m.s-dead;this.backCount=0;
   }else if(this.progress-m.s>10&&unc<10){
    // backwards only when the best forward position is clearly worse, on several consecutive fixes (turned around)
    const fwd=this.match(p,this.progress,this.progress+reach,fix);
    if(!fwd||fwd.d>m.d+12){if(++this.backCount>=3)this.progress=m.s;}else this.backCount=0;
   }
  }
  this.lastMatchT=t;
  out.matched_coordinate=this.pointAt(this.progress);out.matched_edge_id=this.edgeAt(this.progress);out.distance_to_route_m=Math.round(m.d);
  out.confidence=quality==='poor'?'low':m.d<=(acc??20)+5?'high':m.d<=40?'medium':'low';
  // states: weak GPS never triggers off-route; off-route needs consecutive fixes over time
  if(quality==='poor'){this.offCount=0;this.offSince=null;if(['NAVIGATING','POSSIBLY_OFF_ROUTE'].includes(this.state))this.transition('GPS_WEAK','accuracy '+Math.round(acc)+' m');}
  else if(unc>this.cfg.offM){
   this.offCount++;this.offSince=this.offSince??t;
   if(this.state==='GPS_WEAK')this.transition('NAVIGATING','accuracy recovered');
   if(this.offCount>=this.cfg.offFixes&&(t-this.offSince)/1000>=this.cfg.offSeconds){if(this.state!=='OFF_ROUTE'&&this.transition('OFF_ROUTE',`${Math.round(m.d)} m from route`))this.emit({type:'off_route',distance_m:m.d,at:[fix.lon,fix.lat]});}
   else if(this.state!=='OFF_ROUTE')this.transition('POSSIBLY_OFF_ROUTE',`${Math.round(m.d)} m from route`);
  }else{
   this.offCount=0;this.offSince=null;
   if(['GPS_WEAK','POSSIBLY_OFF_ROUTE','OFF_ROUTE'].includes(this.state))this.transition('NAVIGATING','back on route');
  }
  this.lastFix=fix;
  return this.finish(out);
 }
 /** Advance maneuvers, raise alerts and arrivals from the current progress. */
 finish(out){
  const cfg=this.cfg,acc=out.accuracy_m??20,onRoute=['NAVIGATING','GPS_WEAK'].includes(this.state);
  while(this.next<this.maneuvers.length-1&&this.progress>this.maneuvers[this.next].distance_along_route_m+cfg.passM&&!this.maneuvers[this.next].type.startsWith('arrive'))this.next++;
  const nm=this.maneuvers[this.next];
  if(nm){
   const d=nm.distance_along_route_m-this.progress,prev=this.maneuvers[this.next-1];
   const gap=prev?nm.distance_along_route_m-prev.distance_along_route_m:Infinity;
   const early=Math.min(cfg.earlyM+Math.min(acc,40)/2,gap*.8),approach=Math.min(cfg.approachM+Math.min(acc,30)/2,Math.max(12,gap*.5));
   const key=nm.maneuver_id;this.alerted[key]=this.alerted[key]||{};
   if(onRoute&&!nm.type.startsWith('arrive')){
    for(const [lvl,th] of [['now',cfg.nowM+Math.min(acc,20)/4],['approach',approach],['early',early]]){
     if(d<=th&&!this.alerted[key][lvl]){
      // a nearer level supersedes farther ones: never "in 90 m" after "turn now"
      if(lvl!=='early'||!this.alerted[key].approach){this.alerted[key][lvl]=true;if(lvl==='now')this.alerted[key].approach=this.alerted[key].early=true;if(lvl==='approach')this.alerted[key].early=true;
       this.emit({type:'alert',level:lvl,maneuver:nm,distance_m:Math.max(0,d)});}
      break;
     }
    }
   }
   // arrivals: progress reached the stop (with uncertainty) while matched on the route
   if(onRoute&&nm.type.startsWith('arrive')&&d<=Math.max(cfg.arriveM,Math.min(acc,40))&&!this.arrivedStops.has(key)&&(out.distance_to_route_m??0)<=Math.max(30,acc)){
    this.arrivedStops.add(key);
    if(nm.type==='arrive'){this.transition('ARRIVED','destination');this.emit({type:'arrived',maneuver:nm});}
    else{this.transition('ARRIVED_AT_STOP',nm.stop_name||'stop');this.emit({type:'arrived_stop',maneuver:nm});}
   }
   out.next_maneuver=nm;out.distance_to_next_m=Math.max(0,Math.round(d));out.after_next=this.maneuvers[this.next+1]||null;
  }
  out.state=this.state;out.progress_m=Math.round(this.progress);out.remaining_m=Math.max(0,Math.round(this.netLen-this.progress));
  out.remaining_min=Math.round(out.remaining_m/80*10)/10;
  const stops=this.maneuvers.filter(m=>m.type==='arrive_stop');
  out.remaining_stops=stops.filter(m=>!this.arrivedStops.has(m.maneuver_id)).map(m=>m.stop_name);
  out.current_street=this.maneuvers.slice(0,this.next).reverse().find(m=>m.street_name)?.street_name||null;
  this.lastOutput=out;this.emit({type:'update',output:out});return out;
 }
 /** Continue after a stop (the user confirms they are moving on). */
 continueFromStop(){if(this.state==='ARRIVED_AT_STOP'){this.next=Math.min(this.next+1,this.maneuvers.length-1);this.transition('NAVIGATING','continue');}}
 skipStop(){if(this.state!=='ARRIVED_AT_STOP'&&this.maneuvers[this.next]?.type==='arrive_stop'&&this.maneuvers[this.next].required===false){this.arrivedStops.add(this.maneuvers[this.next].maneuver_id);this.next++;return true;}return false;}
 /** Staleness check, called on a timer: no fix for a while means the location shown is not current. */
 tick(now=Date.now()){
  if(this.lastFix&&['NAVIGATING','POSSIBLY_OFF_ROUTE'].includes(this.state)&&(now-(this.lastFix.timestamp??now))/1000>this.cfg.staleSeconds)this.transition('GPS_WEAK','no recent GPS fix');
 }
 snapshot(){return {route_id:this.route.route_id,route_signature:this.route.route_signature,network_version:this.route.network_version,progress_m:this.progress,
  next:this.next,arrived:[...this.arrivedStops],state:this.state};}
}
/** Distances for the UI, metric or imperial. */
function formatNavDistance(m,units='metric'){
 if(m==null||!Number.isFinite(m))return '—';
 if(units==='imperial'){const ft=m*3.28084;return ft<1000?`${Math.max(10,Math.round(ft/10)*10)} ft`:`${(m/1609.344).toFixed(ft<5280*10?1:0)} mi`;}
 return m<1000?`${Math.max(5,Math.round(m/5)*5)} m`:`${(m/1000).toFixed(1)} km`;
}
/** Spoken instruction from an engine maneuver (never generated by a language model). */
function spokenInstruction(m,d,lang='en',units='metric'){
 if(!m)return '';
 if(lang==='zh'){const dist=d!=null&&d>12?`前方约${units==='imperial'?formatNavDistance(d,units):formatNavDistance(d).replace(' m','米').replace(' km','公里')}，`:'';return dist+(m.instruction_zh||m.instruction_text);}
 const dist=d!=null&&d>12?`In ${formatNavDistance(d,units).replace(' m',' meters').replace(' km',' kilometers').replace(' ft',' feet').replace(' mi',' miles')}, `:'';
 const text=m.instruction_text;return dist+(dist?text[0].toLowerCase()+text.slice(1):text);
}
if(typeof module!=='undefined')module.exports={NavEngine,NAV_CONFIG,NAV_STATES,NAV_TRANSITIONS,formatNavDistance,spokenInstruction};
