'use strict';
/* AR live view for walking navigation — camera feed + GPS + compass, on top of nav-engine.js.
   No WebXR: iPhone Safari / Home Screen apps don't support it, so this is a "geo AR" overlay. The rear camera shows
   the street; the route's look-ahead point, the next turn and the walk's stops are placed by their real bearing
   from the GPS fix relative to the device's compass heading. Honest limits shown to the walker: compass error is
   typically 10–20° and GPS drifts 5–20 m between tall buildings, so the overlay says when either is weak and never
   pretends to more precision than it has. Nothing leaves the device (camera frames are never captured or sent).
   Design learned from Google Maps Live View (big arrows on the street, built for glances, safety prompt) and Apple
   Maps AR walking directions (raise to view / lower for the map, arrows that grow and glow as the turn nears,
   battery note). Depends on nav-ui.js globals: nav, $ , toast, formatNavDistance, navArrow; app.js esc. */
const ar={on:false,stream:null,heading:null,beta:null,compassAcc:null,raf:0,lastFrame:0,els:null,orientHandler:null,
 // Raise to View (after Apple Maps): once AR has been used, holding the phone upright opens it and lowering it returns
 // to the map. The camera stream is parked (not stopped) for a minute after lowering, so re-raising doesn't re-prompt.
 raise:true,raiseArmed:false,tiltSince:0,tiltState:null,parkTimer:0,shownAt:0,safetyShown:false,glanceHinted:false,watchHandler:null};
const AR_RAISE_BETA=68,AR_LOWER_BETA=35,AR_TILT_HOLD_MS=650,AR_PARK_MS=60000,AR_GLANCE_MS=25000,AR_NEAR_M=30,AR_NOW_M=10;
try{const v=localStorage.getItem('strollane.ar.raise');if(v!=null)ar.raise=v==='1';}catch(e){}
const AR_EYE_M=1.5;          // camera height above the pavement
const AR_LOOKAHEAD_M=28;     // the floor arrow points at the route this far ahead (or the next turn if nearer)
const AR_SMOOTH=.18;         // compass low-pass (circular), per event
const arRad=d=>d*Math.PI/180,arDeg=r=>r*180/Math.PI;
const arNorm=a=>((a%360)+540)%360-180; // → (-180,180]

function arSupported(){
 return Boolean(navigator.mediaDevices?.getUserMedia)&&'DeviceOrientationEvent' in window&&window.matchMedia('(pointer:coarse)').matches;
}
/** Great-circle bearing (deg, 0 = north) and distance (m) from a to b, both [lon,lat]. */
function arBearing(a,b){
 const f1=arRad(a[1]),f2=arRad(b[1]),dl=arRad(b[0]-a[0]);
 const y=Math.sin(dl)*Math.cos(f2),x=Math.cos(f1)*Math.sin(f2)-Math.sin(f1)*Math.cos(f2)*Math.cos(dl);
 return (arDeg(Math.atan2(y,x))+360)%360;
}
function arDistance(a,b){
 const R=6371008.8,f1=arRad(a[1]),f2=arRad(b[1]),df=f2-f1,dl=arRad(b[0]-a[0]);
 const h=Math.sin(df/2)**2+Math.cos(f1)*Math.cos(f2)*Math.sin(dl/2)**2;return 2*R*Math.asin(Math.sqrt(h));
}
/** Compass heading of the BACK camera from alpha/beta/gamma (W3C DeviceOrientation spec, worked example). */
function arHeadingFromEuler(alpha,beta,gamma){
 const x=arRad(beta),y=arRad(gamma),z=arRad(alpha);
 const cX=Math.cos(x),cY=Math.cos(y),cZ=Math.cos(z),sX=Math.sin(x),sY=Math.sin(y),sZ=Math.sin(z);
 const Vx=-cZ*sY-sZ*sX*cY,Vy=-sZ*sY+cZ*sX*cY;
 let h=Math.atan(Vx/Vy);if(Vy<0)h+=Math.PI;else if(Vx<0)h+=2*Math.PI;
 return arDeg(h);
}
function arOnOrientation(e){
 let h=null;
 if(Number.isFinite(e.webkitCompassHeading)){h=e.webkitCompassHeading;ar.compassAcc=Number.isFinite(e.webkitCompassAccuracy)?e.webkitCompassAccuracy:null;}
 else if(e.absolute&&Number.isFinite(e.alpha)&&Number.isFinite(e.beta)&&Number.isFinite(e.gamma))h=arHeadingFromEuler(e.alpha,e.beta,e.gamma);
 if(Number.isFinite(e.beta))ar.beta=e.beta;
 if(h==null)return;
 const so=(screen.orientation&&Number.isFinite(screen.orientation.angle))?screen.orientation.angle:(Number(window.orientation)||0);
 h=(h+so+360)%360;
 // circular low-pass so the overlay doesn't jitter with every magnetometer sample
 if(ar.heading==null)ar.heading=h;else ar.heading=(ar.heading+arNorm(h-ar.heading)*AR_SMOOTH+360)%360;
}

function arBuild(){
 if(ar.els)return ar.els;
 const root=document.createElement('section');root.id='arView';root.className='ar-view hidden';root.setAttribute('aria-label','AR walking view');
 root.innerHTML=`<video id="arVideo" class="ar-video" playsinline muted autoplay></video>
  <div class="ar-scrim" aria-hidden="true"></div>
  <div class="ar-layer" id="arLayer" aria-hidden="true">
   <div class="ar-floor" id="arFloor"><div class="ar-chevrons"><i></i><i></i><i></i></div></div>
   <div class="ar-target" id="arTarget"><span class="ar-target-pin"></span><span class="ar-target-label" id="arTargetLabel"></span></div>
   <div class="ar-stops" id="arStops"></div>
   <div class="ar-edge ar-edge-left" id="arEdgeLeft"><svg viewBox="0 0 24 24"><path d="M15 5l-7 7 7 7"/></svg><span>Turn left</span></div>
   <div class="ar-edge ar-edge-right" id="arEdgeRight"><span>Turn right</span><svg viewBox="0 0 24 24"><path d="M9 5l7 7-7 7"/></svg></div>
  </div>
  <p class="ar-hint" id="arHint" role="status"></p>
  <p class="ar-flash" id="arFlash" role="status"></p>
  <div class="ar-now" id="arNow"></div>
  <div class="ar-quality" id="arQuality"></div>`;
 const ov=$('navOverlay');ov.parentNode.insertBefore(root,ov);
 ar.els={root,video:root.querySelector('#arVideo'),floor:root.querySelector('#arFloor'),target:root.querySelector('#arTarget'),targetLabel:root.querySelector('#arTargetLabel'),
  stops:root.querySelector('#arStops'),left:root.querySelector('#arEdgeLeft'),right:root.querySelector('#arEdgeRight'),hint:root.querySelector('#arHint'),quality:root.querySelector('#arQuality'),flash:root.querySelector('#arFlash'),now:root.querySelector('#arNow')};
 return ar.els;
}

async function arStart(opts={}){
 if(ar.on||!nav.engine)return;
 if(ar.stream&&ar.els){arShow();return;} // parked stream from a recent lower → instant, no new prompt
 if(!arSupported())return toast('AR view needs a phone with a camera and a compass.');
 // iOS asks for motion access only inside a user gesture (this click) — nav start may already have asked
 if(opts.auto&&!ar.raiseArmed)return;
 try{if(!opts.auto&&typeof DeviceOrientationEvent!=='undefined'&&typeof DeviceOrientationEvent.requestPermission==='function'){
  const r=await DeviceOrientationEvent.requestPermission();if(r!=='granted')return toast('AR view needs motion & orientation access. Allow it in Settings › Safari › Motion & Orientation Access.');}}catch(e){}
 const els=arBuild();
 try{
  ar.stream=await navigator.mediaDevices.getUserMedia({video:{facingMode:{ideal:'environment'},width:{ideal:1280},height:{ideal:720}},audio:false});
 }catch(e){
  if(opts.auto){ar.raiseArmed=false;return toast('Raise to view paused — tap AR view to turn the camera back on.');}
  return toast(e.name==='NotAllowedError'?'Camera access was denied. Allow the camera for this site to use AR view.':`Camera unavailable (${e.name||e.message}).`);
 }
 els.video.srcObject=ar.stream;
 ar.heading=null;ar.compassAcc=null;ar.raiseArmed=true;
 arShow();
}
/** Show the AR layer over a live (or parked) camera stream. */
function arShow(){
 const els=ar.els;clearTimeout(ar.parkTimer);
 try{els.video.play();}catch(e){}
 ar.on=true;ar.shownAt=Date.now();ar.glanceHinted=false;
 if(!ar.orientHandler){ar.orientHandler=arOnOrientation;window.addEventListener('deviceorientationabsolute',ar.orientHandler,true);window.addEventListener('deviceorientation',ar.orientHandler,true);}
 els.root.classList.remove('hidden');document.body.classList.add('ar-mode');
 $('navAr')?.setAttribute('aria-pressed','true');if($('navAr'))$('navAr').textContent='Map view';
 // Safety first, as Google Live View and Apple Maps do: AR is for glances, not for walking with eyes on the screen.
 if(!ar.safetyShown){ar.safetyShown=true;arFlash('Look up from the screen and watch for traffic. AR uses the camera, so it drains the battery faster.',5200);}
 ar.raf=requestAnimationFrame(arFrame);
}
/** Lowered phone: back to the map, keep the camera parked briefly so raising again is instant. */
function arPark(){
 if(!ar.on)return;
 ar.on=false;cancelAnimationFrame(ar.raf);
 try{ar.els.video.pause();}catch(e){}
 ar.els.root.classList.add('hidden');document.body.classList.remove('ar-mode');
 $('navAr')?.setAttribute('aria-pressed','false');if($('navAr'))$('navAr').textContent='AR view';
 clearTimeout(ar.parkTimer);ar.parkTimer=setTimeout(arStop,AR_PARK_MS);
}
function arFlash(text,ms){const el=ar.els?.flash;if(!el)return;el.textContent=text;el.classList.add('show');clearTimeout(arFlash.t);arFlash.t=setTimeout(()=>el.classList.remove('show'),ms||3500);}
function arStop(){
 clearTimeout(ar.parkTimer);
 if(!ar.on&&!ar.stream)return;
 ar.on=false;cancelAnimationFrame(ar.raf);
 if(ar.orientHandler){window.removeEventListener('deviceorientationabsolute',ar.orientHandler,true);window.removeEventListener('deviceorientation',ar.orientHandler,true);}
 ar.orientHandler=null;
 ar.stream?.getTracks().forEach(t=>t.stop());ar.stream=null;
 if(ar.els){ar.els.video.srcObject=null;ar.els.root.classList.add('hidden');}
 document.body.classList.remove('ar-mode');
 $('navAr')?.setAttribute('aria-pressed','false');if($('navAr'))$('navAr').textContent='AR view';
}
// A manual "Map view" while the phone is still upright must not bounce straight back into AR: wait for one lower.
function arToggle(){if(ar.on){ar.suppressRaise=true;arStop();}else arStart();}
/** Raise to View: watch the phone's tilt during navigation (nav-ui already asked for motion access at start). */
function arOnTilt(e){
 // As in Apple Maps: lowering always leaves AR; the setting only decides whether raising brings it back.
 if(!nav.engine||!Number.isFinite(e.beta))return;
 const b=e.beta,now=Date.now();
 const want=b>=AR_RAISE_BETA?'up':b<=AR_LOWER_BETA?'down':null;
 if(want==='down')ar.suppressRaise=false;
 if(want!==ar.tiltState){ar.tiltState=want;ar.tiltSince=now;return;}
 if(!want||now-ar.tiltSince<AR_TILT_HOLD_MS)return;
 if(want==='up'&&ar.raise&&!ar.on&&ar.raiseArmed&&!ar.suppressRaise){ar.tiltSince=now+1e9;arStart({auto:true});}
 else if(want==='down'&&ar.on){ar.tiltSince=now+1e9;if(ar.raise)arPark();else arStop();}
}
function arSetRaise(on){ar.raise=on;try{localStorage.setItem('strollane.ar.raise',on?'1':'0');}catch(e){}const b=$('navArRaise');if(b){b.setAttribute('aria-pressed',String(on));b.textContent=on?'Raise to view: on':'Raise to view: off';}}

/** Camera field of view (deg) — typical phone main camera; portrait is narrower horizontally. */
function arFov(){const portrait=innerHeight>=innerWidth;return portrait?{h:52,v:66}:{h:66,v:52};}
/** Screen position (%) of a ground point at `dist` m and relative bearing `rel` deg; null if behind. */
function arProject(rel,dist,camPitch,fov){
 if(Math.abs(rel)>95)return null;
 const elev=-arDeg(Math.atan2(AR_EYE_M,Math.max(1,dist)));
 return {x:50+rel/fov.h*100,y:50-(elev-camPitch)/fov.v*100};
}
function arFrame(t){
 if(!ar.on)return;
 ar.raf=requestAnimationFrame(arFrame);
 if(t-ar.lastFrame<50)return; // ~20 fps is plenty for an overlay and saves battery
 ar.lastFrame=t;arRender();
}
function arRender(){
 const els=ar.els,eng=nav.engine,out=eng?.lastOutput;
 if(!els||!eng)return;
 const here=out?(out.matched_coordinate&&out.confidence==='high'?out.matched_coordinate:out.raw):null;
 const fov=arFov(),camPitch=ar.beta==null?0:Math.max(-60,Math.min(60,ar.beta-90));
 const hints=[];
 if(!here)hints.push('Waiting for GPS…');
 if(ar.heading==null)hints.push('Waiting for the compass… move the phone in a figure-8 if this persists.');
 if(ar.beta!=null&&ar.beta<45)hints.push('Hold the phone upright to see the arrows.');
 const gpsAcc=out?.accuracy_m??nav.last?.accuracy??null;
 const q=[];
 if(gpsAcc!=null)q.push(`GPS ±${Math.round(gpsAcc)} m`);
 if(ar.compassAcc!=null&&ar.compassAcc>=0)q.push(`Compass ±${Math.round(ar.compassAcc)}°`);
 els.quality.textContent=q.join(' · ');
 els.quality.classList.toggle('weak',(gpsAcc!=null&&gpsAcc>25)||(ar.compassAcc!=null&&(ar.compassAcc<0||ar.compassAcc>25)));
 if(gpsAcc!=null&&gpsAcc>25&&here)hints.push('Weak GPS between buildings — arrows are approximate; check the map.');
 els.hint.textContent=hints[0]||'';els.hint.classList.toggle('show',Boolean(hints[0]));
 const ready=here&&ar.heading!=null;
 els.root.classList.toggle('ar-ready',Boolean(ready));
 if(!ready)return;

 // Floor arrow → the route a short way ahead (or the next turn if it's nearer): the direction to walk now.
 const nm=out.next_maneuver,toNext=out.distance_to_next_m??Infinity;
 const ahead=eng.pointAt(Math.min(eng.netLen,(out.progress_m||0)+Math.min(AR_LOOKAHEAD_M,Math.max(8,toNext))));
 const relAhead=arNorm(arBearing(here,ahead)-ar.heading);
 els.floor.style.setProperty('--rot',`${relAhead.toFixed(1)}deg`);
 // Approaching the turn (after Apple Maps' arrows that grow and glow as you near them): brighter, larger, then "now".
 const turnish=nm&&!['depart','continue','arrive'].includes(nm.type);
 els.root.classList.toggle('ar-near',Boolean(turnish&&toNext<=AR_NEAR_M));
 const nowText=turnish&&toNext<=AR_NOW_M?((nav.voiceLang==='zh'?nm.instruction_zh:nm.instruction_text)||''):'';
 els.now.textContent=nowText;els.now.classList.toggle('show',Boolean(nowText));
 if(!ar.glanceHinted&&Date.now()-ar.shownAt>AR_GLANCE_MS){ar.glanceHinted=true;arFlash(ar.raise?'Lower the phone to see the map — raise it again for AR.':'Tap Map view to see the whole route.',4200);}
 els.floor.classList.toggle('behind',Math.abs(relAhead)>100);
 const half=fov.h/2;
 els.left.classList.toggle('show',relAhead<-half);els.right.classList.toggle('show',relAhead>half);

 // Labels live between the instruction card and the bottom bar, and never on top of each other (as in Live View):
 // nearest first, each later label is pushed down until it clears the ones already placed.
 const H=innerHeight||800,W=innerWidth||400;
 const topCard=document.querySelector('.nav-top')?.getBoundingClientRect(),botCard=document.querySelector('.nav-bottom')?.getBoundingClientRect();
 const yMin=((topCard?.bottom||H*.2)+14)/H*100,yMax=((botCard?.top||H*.8)-70)/H*100;
 const placed=[],LW=210/W*100,LH=50/H*100;
 const place=(x,y)=>{y=Math.max(yMin+LH,Math.min(yMax,y));for(let i=0;i<8;i++){const hit=placed.find(b=>Math.abs(b.x-x)<LW&&Math.abs(b.y-y)<LH);if(!hit)break;y=hit.y+LH+.8;}placed.push({x,y});return y;};

 // Next turn: a pin standing on the street at its real bearing and distance
 if(nm?.coordinate){
  const d=arDistance(here,nm.coordinate),rel=arNorm(arBearing(here,nm.coordinate)-ar.heading),p=arProject(rel,d,camPitch,fov);
  els.target.classList.toggle('hidden',!p||p.x<-10||p.x>110);
  if(p){const x=Math.max(8,Math.min(92,p.x));els.target.style.left=`${x}%`;els.target.style.top=`${place(x,p.y)}%`;
   const instr=nav.voiceLang==='zh'?nm.instruction_zh:nm.instruction_text;
   els.targetLabel.textContent=`${instr||'Next turn'} · ${formatNavDistance(d,nav.units)}`;}
 }else els.target.classList.add('hidden');

 // Stops still ahead on this walk, by name, where they really are (nearest first)
 const stops=eng.maneuvers.filter(m=>(m.type==='arrive_stop'||m.type==='arrive')&&m.distance_along_route_m>(out.progress_m||0)-5&&m.coordinate)
  .map(m=>({m,d:arDistance(here,m.coordinate)})).filter(o=>o.d<=1500).sort((a,b)=>a.d-b.d).slice(0,3);
 const html=[];
 for(const {m,d} of stops){
  const rel=arNorm(arBearing(here,m.coordinate)-ar.heading),p=arProject(rel,d,camPitch,fov);
  if(!p||p.x<-5||p.x>105)continue;
  const x=Math.max(10,Math.min(90,p.x)),y=place(x,p.y-6);
  const name=m.stop_name||(m.type==='arrive'?'Destination':'Stop');
  html.push(`<div class="ar-stop" style="left:${x.toFixed(1)}%;top:${y.toFixed(1)}%"><strong>${esc(name)}</strong><small>${formatNavDistance(d,nav.units)}</small></div>`);
 }
 els.stops.innerHTML=html.join('');
}

function setupArNav(){
 const btn=$('navAr');if(!btn)return;
 if(!arSupported()){btn.classList.add('hidden');return;}
 btn.addEventListener('click',arToggle);
 ar.watchHandler=arOnTilt;window.addEventListener('deviceorientation',ar.watchHandler,true);
 const more=document.querySelector('#navOverlay .nav-more-body');
 if(more&&!$('navArRaise')){const r=document.createElement('button');r.type='button';r.className='nav-pill';r.id='navArRaise';more.appendChild(r);r.addEventListener('click',()=>arSetRaise(!ar.raise));}
 arSetRaise(ar.raise);
 $('navExit')?.addEventListener('click',arStop,true);$('navArrivedDone')?.addEventListener('click',arStop,true);
 // never keep the camera running in the background
 document.addEventListener('visibilitychange',()=>{if(document.hidden&&(ar.on||ar.stream))arStop();});
 window.addEventListener('pagehide',arStop);
}
if(typeof window!=='undefined'){window.strollaneAr={start:arStart,stop:arStop,park:arPark,state:ar,render:arRender,project:arProject,bearing:arBearing,headingFromEuler:arHeadingFromEuler,setRaise:arSetRaise};
 if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',setupArNav);else setupArNav();}
