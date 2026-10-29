'use strict';
/* Immersive 3D route preview — a first-person fly-through of the selected walk through the 3D city (PLUTO building
   heights already on the map), before you leave. Play / pause, drag to any point, 1× / 2× / 4×, the next turn and
   the stops called out as you pass them. It's a preview of the real route geometry from the STROLLANE engine, not a
   simulation of street-level imagery. Depends on: state, $, esc, toast, formatNavDistance, NavEngine, activeRouteObject. */
const preview={on:false,eng:null,route:null,s:0,playing:false,speed:1,raf:0,lastT:0,bearing:null,saved:null,els:null,reduced:false};
const PREVIEW_PITCH=72,PREVIEW_ZOOM=17.6,PREVIEW_LOOK_M=45;

function previewBuild(){
 if(preview.els)return preview.els;
 const root=document.createElement('section');root.id='routePreview';root.className='route-preview hidden';root.setAttribute('aria-label','3D route preview');
 root.innerHTML=`<div class="rp-top"><div class="rp-now"><small id="rpWhere">Start</small><strong id="rpInstr">Preview of your walk</strong></div>
   <button type="button" class="rp-close" id="rpClose" aria-label="Close 3D preview"><svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6L6 18"/></svg></button></div>
  <div class="rp-stop hidden" id="rpStop"></div>
  <div class="rp-bar">
   <button type="button" class="rp-play" id="rpPlay" aria-label="Pause"><svg viewBox="0 0 24 24" id="rpPlayIcon"></svg></button>
   <div class="rp-track"><input type="range" id="rpScrub" min="0" max="1000" value="0" step="1" aria-label="Position along the walk"><div class="rp-meta"><span id="rpDone">0 m</span><span id="rpLeft"></span></div></div>
   <button type="button" class="rp-speed" id="rpSpeed" aria-label="Playback speed">1×</button>
  </div>`;
 document.querySelector('.map-workspace')?.appendChild(root);
 const q=id=>root.querySelector('#'+id);
 preview.els={root,where:q('rpWhere'),instr:q('rpInstr'),stop:q('rpStop'),play:q('rpPlay'),playIcon:q('rpPlayIcon'),scrub:q('rpScrub'),done:q('rpDone'),left:q('rpLeft'),speed:q('rpSpeed')};
 q('rpClose').addEventListener('click',previewStop);
 preview.els.play.addEventListener('click',()=>previewSetPlaying(!preview.playing));
 preview.els.speed.addEventListener('click',()=>{preview.speed={1:2,2:4,4:1}[preview.speed];preview.els.speed.textContent=`${preview.speed}×`;});
 preview.els.scrub.addEventListener('input',e=>{preview.s=e.target.value/1000*preview.eng.netLen;previewSetPlaying(false);previewApply(true);});
 document.addEventListener('keydown',e=>{if(!preview.on)return;if(e.key==='Escape')previewStop();else if(e.key===' '&&e.target===document.body){e.preventDefault();previewSetPlaying(!preview.playing);}});
 return preview.els;
}
function previewSetPlaying(on){
 preview.playing=on&&preview.s<preview.eng.netLen;preview.lastT=0;
 preview.els.playIcon.innerHTML=preview.playing?'<path d="M8 5v14M16 5v14"/>':'<path d="M7 4l13 8-13 8z"/>';
 preview.els.play.setAttribute('aria-label',preview.playing?'Pause':'Play');
}
/** Metres per second at 1×: the whole walk in ~40 s, never slower than a brisk 12 m/s fly-over. */
function previewBaseSpeed(){return Math.max(12,preview.eng.netLen/40);}

function previewStart(){
 const m=state.map,r=typeof activeRouteObject==='function'?activeRouteObject():null;
 if(!m||!r?.geometry?.coordinates?.length)return toast('Plan a route first, then preview it in 3D.');
 if(preview.on)previewStop();
 const eng=new NavEngine(r,{});preview.eng=eng;preview.route=r;
 preview.saved={center:m.getCenter(),zoom:m.getZoom(),bearing:m.getBearing(),pitch:m.getPitch(),padding:m.getPadding(),maxPitch:m.getMaxPitch()};
 if(m.getMaxPitch()<PREVIEW_PITCH)m.setMaxPitch(80);
 const els=previewBuild();
 preview.on=true;preview.s=0;preview.bearing=null;preview.speed=1;els.speed.textContent='1×';
 preview.reduced=window.matchMedia('(prefers-reduced-motion: reduce)').matches;
 document.body.classList.add('preview-mode');els.root.classList.remove('hidden');
 m.resize(); // desktop: side panels collapse, the map takes the window
 previewEnsureLayers();
 if(typeof m.setSky==='function'){try{preview.saved.sky=m.getSky?.();m.setSky({'sky-color':'#03050a','horizon-color':'#0a1220','fog-color':'#020306','sky-horizon-blend':.9,'horizon-fog-blend':.9,'fog-ground-blend':.35,'atmosphere-blend':0});}catch(e){}}
 previewApply(true);
 // reduced motion: start paused, the walker scrubs instead of watching an animation
 previewSetPlaying(!preview.reduced);
 preview.raf=requestAnimationFrame(previewFrame);
}
function previewStop(){
 if(!preview.on)return;
 preview.on=false;preview.playing=false;cancelAnimationFrame(preview.raf);
 const m=state.map;
 m.getSource('preview-walker')?.setData(emptyFC());
 if(typeof m.setSky==='function'){try{m.setSky(preview.saved?.sky||{});}catch(e){}}
 preview.els?.root.classList.add('hidden');document.body.classList.remove('preview-mode');m.resize();
 const s=preview.saved;
 if(s){m.setMaxPitch(s.maxPitch);m.easeTo({center:s.center,zoom:s.zoom,bearing:s.bearing,pitch:s.pitch,padding:s.padding,duration:700});}
 preview.eng=null;preview.route=null;
}
function previewEnsureLayers(){
 const m=state.map;if(m.getSource('preview-walker'))return;
 m.addSource('preview-walker',{type:'geojson',data:emptyFC()});
 m.addLayer({id:'preview-walker-glow',type:'circle',source:'preview-walker',paint:{'circle-radius':18,'circle-color':'#d8f365','circle-opacity':.18,'circle-blur':.8,'circle-pitch-alignment':'map'}});
 m.addLayer({id:'preview-walker',type:'circle',source:'preview-walker',paint:{'circle-radius':7,'circle-color':'#d8f365','circle-stroke-color':'#000000','circle-stroke-width':2,'circle-pitch-alignment':'map'}});
}
function previewFrame(t){
 if(!preview.on)return;
 preview.raf=requestAnimationFrame(previewFrame);
 if(!preview.playing){preview.lastT=0;return;}
 if(!preview.lastT){preview.lastT=t;return;}
 const dt=Math.min(.1,(t-preview.lastT)/1000);preview.lastT=t;
 preview.s=Math.min(preview.eng.netLen,preview.s+previewBaseSpeed()*preview.speed*dt);
 previewApply(false);
 if(preview.s>=preview.eng.netLen)previewSetPlaying(false);
}
function previewApply(jump){
 const eng=preview.eng,m=state.map,s=preview.s;
 const p=eng.pointAt(s),ahead=eng.pointAt(Math.min(eng.netLen,s+PREVIEW_LOOK_M));
 let target=(typeof arBearing==='function'?arBearing(p,ahead):eng.bearingAt(s));
 if(s>=eng.netLen-1&&preview.bearing!=null)target=preview.bearing;
 // smooth turns: rotate toward the look-ahead bearing instead of snapping at every vertex
 if(preview.bearing==null||jump)preview.bearing=target;
 else{const d=((target-preview.bearing+540)%360)-180;preview.bearing=(preview.bearing+d*.08+360)%360;}
 const h=m.getContainer().clientHeight||700;
 m.jumpTo({center:p,zoom:PREVIEW_ZOOM,pitch:PREVIEW_PITCH,bearing:preview.bearing,padding:{top:Math.round(h*.42),bottom:Math.round(h*.08),left:0,right:0}});
 m.getSource('preview-walker')?.setData({type:'FeatureCollection',features:[{type:'Feature',properties:{},geometry:{type:'Point',coordinates:p}}]});
 previewHud();
}
function previewHud(){
 const els=preview.els,eng=preview.eng,s=preview.s,units=(typeof nav!=='undefined'&&nav.units)||'metric',zh=typeof nav!=='undefined'&&nav.voiceLang==='zh';
 els.scrub.value=String(Math.round(s/eng.netLen*1000));
 els.done.textContent=formatNavDistance(s,units);
 els.left.textContent=`${formatNavDistance(Math.max(0,eng.netLen-s),units)} left · ${Math.max(0,Math.round((eng.netLen-s)/80))} min walk`;
 const next=eng.maneuvers.find(mv=>mv.distance_along_route_m>s+3);
 if(next){const d=next.distance_along_route_m-s;els.where.textContent=d>15?`In ${formatNavDistance(d,units)}`:'Now';els.instr.textContent=(zh?next.instruction_zh:next.instruction_text)||'Continue';}
 else{els.where.textContent='Arrived';els.instr.textContent=preview.route.route_name||'End of the walk';}
 const stop=eng.maneuvers.find(mv=>(mv.type==='arrive_stop'||mv.type==='arrive')&&Math.abs(mv.distance_along_route_m-s)<70);
 if(stop){els.stop.innerHTML=`<small>${stop.type==='arrive'?'Destination':'Stop on your walk'}</small><strong>${esc(stop.stop_name||preview.route.route_name||'Destination')}</strong>${stop.visit_min?`<span>Suggested visit ${stop.visit_min} min</span>`:''}`;els.stop.classList.remove('hidden');}
 else els.stop.classList.add('hidden');
}
function renderPreviewButton(){
 const b=$('routePreviewBtn');if(!b)return;
 const r=typeof activeRouteObject==='function'?activeRouteObject():null;
 b.classList.toggle('hidden',!r?.geometry?.coordinates?.length||(typeof nav!=='undefined'&&nav.engine!=null));
}
function setupRoutePreview(){
 $('routePreviewBtn')?.addEventListener('click',previewStart);
 // keep the button in step with the selected route (route cards, re-plans, navigation start/stop)
 const target=$('navStart');if(target)new MutationObserver(renderPreviewButton).observe(target,{attributes:true,attributeFilter:['class','disabled']});
 renderPreviewButton();
}
if(typeof window!=='undefined'){window.strollanePreview={start:previewStart,stop:previewStop,state:preview,apply:previewApply,setPlaying:previewSetPlaying};
 if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',setupRoutePreview);else setupRoutePreview();}
