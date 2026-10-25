'use strict';

/** STREETWISE / Manhattan research prototype. All displayed geometry is remote GIS source data or external routing output. **/
const $ = (id) => document.getElementById(id);
const CENTER = [-73.9698, 40.7840];
// Study-area envelope, not a precise legal borough polygon.
const MANHATTAN_BOUNDS = [[-74.032, 40.696], [-73.904, 40.883]];
const BBOX = [MANHATTAN_BOUNDS[0][0], MANHATTAN_BOUNDS[0][1], MANHATTAN_BOUNDS[1][0], MANHATTAN_BOUNDS[1][1]];
const STREET_PAGE_SIZE = 1750;
const OVERLAY_PAGE_SIZE = 1600;
const PLACES = {
  bryant: { name: 'Bryant Park', lon: -73.9832, lat: 40.7536 },
  carnegie: { name: 'Carnegie Hall', lon: -73.9798, lat: 40.7651 },
  times: { name: 'Times Square', lon: -73.9855, lat: 40.7580 },
  rock: { name: 'Rockefeller Center', lon: -73.9787, lat: 40.7587 },
  nypl: {name:'New York Public Library',lon:-73.9818,lat:40.7532},
  stpatrick: {name:'St. Patrick’s Cathedral',lon:-73.9763,lat:40.7584},
  radio: {name:'Radio City Music Hall',lon:-73.9799,lat:40.7599},
  moma: {name:'Museum of Modern Art',lon:-73.9776,lat:40.7614},
  grand: { name: 'Grand Central Terminal', lon: -73.9770, lat: 40.7527 },
  battery: {name:'The Battery', lon:-74.0168, lat:40.7032},
  wall: {name:'Wall Street',lon:-74.0096,lat:40.7069},
  washington:{name:'Washington Square Park',lon:-73.9973,lat:40.7308},
  union:{name:'Union Square',lon:-73.9903,lat:40.7359},
  columbus:{name:'Columbus Circle',lon:-73.9819,lat:40.7681},
  met:{name:'The Metropolitan Museum',lon:-73.9632,lat:40.7794},
  columbia:{name:'Columbia University',lon:-73.9636,lat:40.8075},
  apollo:{name:'Apollo Theater',lon:-73.9501,lat:40.8100},
  fort:{name:'Fort Tryon Park',lon:-73.9319,lat:40.8638}
};
// The 12 experience dimensions. Street scores live in data/manhattan-streets.json (Explore) and are transferred to OSM
// pedestrian edges for routing (data/pedestrian/edge-scores.json.gz); both share one definition and score version.
const DIMENSIONS = [
  {name:'Architecture', icon:'▥', status:'measured', desc:'Street rank 0–100, shared with Explore'},
  {name:'Nature', icon:'❧', status:'measured', desc:'Street rank 0–100, shared with Explore'},
  {name:'Culture', icon:'◇', status:'measured', desc:'Street rank 0–100, shared with Explore'},
  {name:'Quiet & Relax', icon:'☾', status:'measured', desc:'Street rank 0–100, shared with Explore'},
  {name:'Spatial Comfort', icon:'▤', status:'measured', desc:'Street rank 0–100, shared with Explore'},
  {name:'Urban Vibrancy', icon:'✳', status:'measured', desc:'Street rank 0–100, shared with Explore'},
  {name:'Food & Retail', icon:'♜', status:'measured', desc:'Street rank 0–100, shared with Explore'},
  {name:'Scenic & Visual', icon:'✧', status:'measured', desc:'Street rank 0–100, shared with Explore'},
  {name:'Walkability', icon:'↗', status:'measured', desc:'Street rank 0–100, shared with Explore'},
  {name:'Access & Safety', icon:'◎', status:'measured', desc:'Street rank 0–100, shared with Explore'},
  {name:'Environment', icon:'☼', status:'measured', desc:'Street rank 0–100, shared with Explore'},
  {name:'Transit Connectivity', icon:'◈', status:'measured', desc:'Street rank 0–100, shared with Explore'}
];
const DOMAINS = [
  'Built Environment', 'Nature & Environment', 'Tourism Attractions', 'Food, Retail & Services',
  'Mobility Networks', 'Transport Services', 'Accessibility', 'Safety & Risk',
  'Time / Live Context', 'Neighborhood Context', 'User Trip Planning', 'Quality / Provenance'
];
const API = {
  streets:'https://services.arcgis.com/V6ZHFr6zdgNZuVG0/ArcGIS/rest/services/NYC_Street_Centerline/FeatureServer/0/query',
  trees:'https://data.cityofnewyork.us/resource/uvpi-gqnh.json',
  lpc:'https://services5.arcgis.com/Oos4pNA2538iVFA1/ArcGIS/rest/services/Ind_Landmark_Lots_POLY/FeatureServer/0/query',
  weather:'https://api.open-meteo.com/v1/forecast',
  kepler:'https://kepler.gl/demo'
};
const emptyFC = () => ({type:'FeatureCollection',features:[]});
// Independent from objective GIS observations: expressed weights are user preferences, NEVER environment scores.
const planner = {
  weights: Object.fromEntries(DIMENSIONS.map(d => [d.name, 50])),
  origins: Object.fromEntries(DIMENSIONS.map(d => [d.name, 'default'])),
  directions: Object.fromEntries(DIMENSIONS.map(d => [d.name, 'high'])),
  constraints: {avoidDetours:true,stepFree:false,avoidStairs:false},
  conversations:[], llmConnected:false, llmConfigured:null, interpretation:'unavailable', adjust:false,
  routeResponse:null, lastExplanation:'', runId:0, parsing:false, maxDetourPct:25,
  profileView:'selected', routePois:[], poiStatus:'Not loaded', poiRun:0, lastBest:null
};

const DEFAULT_WALK_MINUTES = 100, MIN_WALK_MINUTES = 10, SLIDER_BASE_MAX = 150;  // max walking time: default, minimum, base slider end
const WALK_QUICK_MINUTES = [60, 100, 120, 150], WALK_QUICK_KM = [2, 5, 8, 10], KM_PER_MILE = 1.609344;
const state = {
  map: null, mapReady: false, mapLayersReady:false,
  start:'bryant', end:'rock', customStart:null, customEnd:null, gps:null, gpsWatch:null,
  pick:null, dimension:'Streets', budget:DEFAULT_WALK_MINUTES, maxKm:null, distUnit:'km', outingMin:null,
  datasets:{streets:null, trees:null, lpc:null}, dataComplete:{streets:false,trees:false,lpc:false},
  dataErrors:{}, loading:{}, routes:[], activeRoute:null, selectedStreet:null,
  display:{roads:true,trees:false,lpc:false,routes:true,pois:true}, routingBusy:false, weather:null,
  treeStatsReady:false, thresholds:[0,0], intentTags:[], streetsById:new Map(), streetExpected:null, streetRetrying:false, overlayCoverage:{trees:null,lpc:null}, overlayRequestId:0
};

/* Max walking time: default 100 min, at least 10, no upper cap. The slider spans 10–150 and extends to the current
   value when it is higher, so slider, chips, custom input and header always show the same number.
   Max walking distance: not set by default (no hidden limit); optional total outing duration = walking + visits. */
function validWalkMinutes(v){const n=typeof v==='string'?v.trim():v;if(n===''||n===null)return null;const x=Number(n);return Number.isInteger(x)&&x>=MIN_WALK_MINUTES?x:null;}
function syncBudgetUI(){
  const max=Math.max(SLIDER_BASE_MAX,state.budget),r=$('timeRange');
  r.max=max;r.value=state.budget;$('timeRangeMax').textContent=`${max} MIN`;$('timeValue').textContent=`${state.budget} MIN`;
  if(document.activeElement!==$('customTime'))$('customTime').value=state.budget;  // never overwrite what the user is typing
  document.querySelectorAll('[data-walk-min]').forEach(b=>b.setAttribute('aria-pressed',String(+b.dataset.walkMin===state.budget)));
  const custom=!WALK_QUICK_MINUTES.includes(state.budget);document.querySelector('[data-walk-min="custom"]')?.setAttribute('aria-pressed',String(custom));
  syncDistanceUI();
}
/** Distance limit in km (null = not set); shown in the chosen unit. */
function setDistanceLimit(km){
  if(km===null||km===''||km===undefined){state.maxKm=null;syncDistanceUI();return true;}
  const x=Number(km);if(!Number.isFinite(x)||x<=0||x>100)return false;state.maxKm=Math.round(x*100)/100;syncDistanceUI();return true;
}
function syncDistanceUI(){
  const u=state.distUnit,v=state.maxKm==null?null:u==='mi'?state.maxKm/KM_PER_MILE:state.maxKm;
  const out=$('distValue');if(!out)return;
  out.textContent=v==null?'NOT SET':`${(Math.round(v*10)/10)} ${u.toUpperCase()}`;
  document.querySelectorAll('[data-walk-km]').forEach(b=>{const k=b.dataset.walkKm;b.setAttribute('aria-pressed',String(k==='none'?state.maxKm==null:k!=='custom'&&state.maxKm!=null&&Math.abs(+k-state.maxKm)<.01));
    if(k!=='none'&&k!=='custom')b.textContent=u==='mi'?`${(+k/KM_PER_MILE).toFixed(1)} mi`:`${k} km`;});
  if(document.activeElement!==$('customDist'))$('customDist').value=v==null?'':Math.round(v*10)/10;
  document.querySelectorAll('[data-dist-unit]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.distUnit===u)));
}
/** Sets the hard limit if valid; returns false (state unchanged) otherwise. */
function setBudget(v){const x=validWalkMinutes(v);if(x===null)return false;state.budget=x;syncBudgetUI();return true;}
const formatNum = (v, decimals=1) => Number.isFinite(v)?v.toFixed(decimals):'—';
const esc = s => String(s ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[ch]));
let toastTimer;
function toast(message){const e=$('toast'); e.textContent=message;e.classList.add('show');clearTimeout(toastTimer);toastTimer=setTimeout(()=>e.classList.remove('show'),4800)}
function setSourceStatus(text,good=false){$('sourceStatus').textContent=text;document.querySelector('.online-mark').style.background=good?'#d8f365':'#eaa873'}
function latLonInsideManhattanEnvelope(p){return p.lon>BBOX[0]&&p.lon<BBOX[2]&&p.lat>BBOX[1]&&p.lat<BBOX[3]}
function getPlace(kind){const id=state[kind]; if(id==='custom')return state[kind==='start'?'customStart':'customEnd']; if(id==='gps')return state.gps; return PLACES[id]||null}
function featureFC(x){return x && x.type==='FeatureCollection'&&Array.isArray(x.features)}
function geoDistanceKm(a,b){
  const rad=Math.PI/180, dlat=(b[1]-a[1])*rad,dlon=(b[0]-a[0])*rad;
  const q=Math.sin(dlat/2)**2+Math.cos(a[1]*rad)*Math.cos(b[1]*rad)*Math.sin(dlon/2)**2;
  return 12742*Math.asin(Math.min(1,Math.sqrt(q)));
}
function lineLengthKm(coords){let s=0;for(let i=1;i<coords.length;i++)s+=geoDistanceKm(coords[i-1],coords[i]);return s}
function segmentDistanceM(p,a,b){
  const cos=Math.cos(40.76*Math.PI/180);
  const x=(p[0]-a[0])*111320*cos,y=(p[1]-a[1])*111320;
  const ux=(b[0]-a[0])*111320*cos,uy=(b[1]-a[1])*111320;
  const f=(ux*ux+uy*uy)>0?Math.max(0,Math.min(1,(x*ux+y*uy)/(ux*ux+uy*uy))):0;
  return Math.hypot(x-f*ux,y-f*uy);
}
function pointNearPolyline(p,coords,meters){for(let k=1;k<coords.length;k++)if(segmentDistanceM(p,coords[k-1],coords[k])<=meters)return true;return false}
function featureCoords(feature){if(!feature?.geometry)return [];return feature.geometry.type==='LineString'?feature.geometry.coordinates:feature.geometry.type==='MultiLineString'?feature.geometry.coordinates.flat():[]}
function weightLabel(value){return value>=75?'High':value<=30?'Low':'Moderate'}
function renderDimensions(){
  $('dimensionGrid').innerHTML=DIMENSIONS.map((d,i)=>{
    const w=planner.weights[d.name],origin=planner.origins[d.name];
    const measured='Street rank 0–100';
    return `<div class="dimension-entry"><div class="dimension-title"><span class="dim-index">${String(i+1).padStart(2,'0')}</span><span>${esc(d.icon)} ${esc(d.name)}<small>${esc(measured)} · ${origin==='default'?'Neutral default':origin==='manual'?'Manually set':planner.interpretation==='llm'?'AI parsed':'Preview parsed'}</small></span></div><span class="dimension-weight">${w}${planner.directions[d.name]==='low'?' · prefer less':''}</span>${planner.adjust?`<input class="dimension-slider" type="range" min="0" max="100" step="5" value="${w}" data-weight="${esc(d.name)}" aria-label="Weight for ${esc(d.name)}"/>`:''}</div>`;
  }).join('');
  $('dimensionGrid').querySelectorAll('[data-weight]').forEach(el=>{
    el.addEventListener('input',()=>{
      planner.weights[el.dataset.weight]=+el.value;
      el.closest('.dimension-entry').querySelector('.dimension-weight').textContent=el.value+(planner.directions[el.dataset.weight]==='low'?' · prefer less':'');
    });
    el.addEventListener('change',()=>{
      planner.origins[el.dataset.weight]='manual';renderPreferenceSummary();
      if(state.routes.length)queueMapReplan();
    });
  });
}
function renderPreferenceSummary(){
  const items=DIMENSIONS.filter(d=>planner.origins[d.name]!=='default').sort((a,b)=>planner.weights[b.name]-planner.weights[a.name]);
  $('preferenceSource').textContent=planner.interpretation==='llm'?'AI INTERPRETED':planner.interpretation==='local'?'LOCAL PREVIEW':'NOT INTERPRETED';
  $('preferenceSummary').innerHTML=items.length?`<div class="pref-heading">✦ UNDERSTOOD YOUR PREFERENCES</div><div class="pref-items">${items.map(d=>`<div class="pref-item"><span>${esc(d.icon)} ${esc(d.name)}</span><strong>${weightLabel(planner.weights[d.name])} · ${planner.weights[d.name]}${planner.directions[d.name]==='low'?' · less':''}</strong></div>`).join('')}</div>`:'<span class="status-empty">✧ No preferences interpreted yet. Unmentioned dimensions = neutral 50.</span>';
  syncBudgetUI();$('maxDetourPct').value=planner.maxDetourPct;
  ['avoidDetours','stepFree','avoidStairs'].forEach(id=>$(id).checked=planner.constraints[id]);
  $('constraintWarning').classList.toggle('hidden',!planner.constraints.stepFree);
  renderDimensions();
}
// Clearly labelled LIMITED offline preview; an actual LLM is used only through server.py when configured.
/** Weather intent: 'ask' (a question about comfort, answered without re-routing), 'cooler' (heat term weighted up),
    'consider' (use today's weather, nothing else changes), or null. */
function localWeatherIntent(q){
  if(/\b(is|will|would)\b[^?]*\b(comfortable|ok|okay|fine|bearable|pleasant)\b[^?]*\bweather\b|这(个)?天气.*(舒服|合适|舒适)|天气.*(舒服|舒适)吗/i.test(q))return 'ask';
  if(/cool(er)?\b|too hot|really hot|so hot|\bheat\b|hot (day|today|weather)|shad(e|ed|y|ier)|less sun|out of the sun|凉快|凉爽|太热|很热|好热|阴凉|遮阴|晒/i.test(q))return 'cooler';
  if(/weather|天气/i.test(q))return 'consider';
  return null;
}
function localInterpret(q){
  q=q.replace(/\b(one|two|three|four|five|six|seven|eight|nine|ten|fifteen|twenty|thirty|forty|fifty|sixty)\b/gi,word=>({one:1,two:2,three:3,four:4,five:5,six:6,seven:7,eight:8,nine:9,ten:10,fifteen:15,twenty:20,thirty:30,forty:40,fifty:50,sixty:60}[word.toLowerCase()]));
  const map=[
    ['Architecture',/architect|historic|heritage|landmark|building|建筑|历史|地标/i],
    ['Nature',/green|\btrees?\b|\bparks?\b|shade|nature|greener|绿|树|自然|公园|阴凉/i],
    ['Culture',/culture|museum|\barts?\b|gallery|艺术|文化|博物馆/i],
    ['Quiet & Relax',/quiet|peaceful|calm|relax|less noisy|安静|清静|少噪音/i],
    ['Spatial Comfort',/comfort|spacious|uncrowded|宽敞|舒适/i],
    ['Urban Vibrancy',/lively|vibrant|busy|energetic|热闹|活力/i],
    ['Food & Retail',/food|coffee|restaurant|shop|\beat\b|餐厅|咖啡|美食|购物/i],
    ['Scenic & Visual',/scenic|beautiful view|viewpoint|photogenic|风景|景观|拍照/i],
    ['Walkability',/walkable|easy to walk|pedestrian.friend|好走|步行友好/i],
    ['Access & Safety',/safe|well.lit|safety|安全|照明/i],
    ['Environment',/air quality|clean air|less pollution|空气|污染/i],
    ['Transit Connectivity',/subway|transit|metro|地铁|公交|换乘/i]
  ];
  const weights={},directions={};
  for(const [name,re] of map){const m=re.exec(q);if(!m)continue;
    weights[name]=90;const before=q.slice(Math.max(0,m.index-30),m.index).toLowerCase();
    // Priority is never reversed; desired direction is independent from weight.
    directions[name]=/(avoid|less|fewer|without|reduce|not|不想|避开|减少)/i.test(before)?'low':'high';
    if(name==='Quiet & Relax' && /less noisy|少噪音/i.test(q))directions[name]='high';
  }
  if(/less crowded|fewer crowds|avoid crowds|less busy|少拥挤|少人群/i.test(q)){weights['Urban Vibrancy']=90;directions['Urban Vibrancy']='low'}
  const result={weights,directions,time_minutes:null,time_delta_minutes:null,constraints:{},weather:localWeatherIntent(q)};
  const explicit=q.match(/(?:within|under|maximum|max|no more than|at most|less than|最多|不超过|限制|以内|控制在)\s*(\d{1,3})\s*(?:minutes?|mins?|分钟)/i)||q.match(/(\d{1,3})\s*(?:minutes?|mins?|分钟)\s*(?:max|or less|以内|之内)/i);
  if(explicit)result.time_minutes=+explicit[1];
  const more=q.match(/(?:another|additional|extra|up to|多|增加|再|延长)\s*(\d{1,2})\s*(?:minutes?|mins?|分钟)/i)||q.match(/(\d{1,2})\s*(?:minutes?|mins?|分钟)\s*(?:more|extra|longer|也行|也可以)/i)||q.match(/(\d{1,2})\s*(?:more|extra|additional)\s*(?:minutes?|mins?)/i);
  if(more&&!explicit)result.time_delta_minutes=+more[1];
  if(/step.free|wheelchair|无障碍|轮椅/i.test(q))result.constraints.stepFree=true;
  if(/avoid stairs|no stairs|避开楼梯|不要楼梯/i.test(q))result.constraints.avoidStairs=true;
  if(/avoid detours|no detours|避免绕路/i.test(q))result.constraints.avoidDetours=true;
  if(/allow detours|okay with detours|可以绕路/i.test(q))result.constraints.avoidDetours=false;
  return result;
}
function applyInterpretation(result,source){
  const changes=[];planner.interpretation=source;
  if(result.waterfront){planner.waterfront=result.waterfront.mode==='clear'?null:{direction:result.waterfront.direction,weight:result.waterfront.weight||90};changes.push(planner.waterfront?`water proximity: prefer ${planner.waterfront.direction}`:'water proximity preference removed');}
  if(result.crime){planner.crime=result.crime.mode==='clear'?null:Object.fromEntries(Object.entries(result.crime).filter(([k])=>k!=='mode'));if(typeof urbanData!=='undefined')urbanData.crimeFilter={};changes.push(planner.crime?`historical complaint density: ${planner.crime.direction} (${planner.crime.from||'indexed default'} to ${planner.crime.to||'latest available'}, exclusive)`:'complaint-density preference removed');}
  for(const d of DIMENSIONS){
    if(Object.prototype.hasOwnProperty.call(result.weights||{},d.name)){
      const value=Number(result.weights[d.name]);if(Number.isFinite(value)&&value>=0&&value<=100){
        planner.weights[d.name]=Math.round(value);planner.origins[d.name]=source;
        planner.directions[d.name]=result.directions?.[d.name]==='low'?'low':'high';
        changes.push(`${d.name} ${Math.round(value)}`);
      }
    }
  }
  const asked=Number.isFinite(result.time_minutes)?Math.round(result.time_minutes):Number.isFinite(result.time_delta_minutes)?Math.round(state.budget+result.time_delta_minutes):null;
  if(asked!==null)changes.push(setBudget(asked)?`max ${state.budget} min`:`time limit ${asked} min ignored (minimum ${MIN_WALK_MINUTES}); kept ${state.budget} min`);
  for(const c of ['avoidDetours','stepFree','avoidStairs']){
    if(typeof result.constraints?.[c]==='boolean'){planner.constraints[c]=result.constraints[c];changes.push(`${c}: ${planner.constraints[c]?'yes':'no'}`)}
  }
  if(Number.isFinite(result.max_detour_percent)){planner.maxDetourPct=Math.max(0,Math.min(100,Math.round(result.max_detour_percent)));changes.push(`max detour ${planner.maxDetourPct}%`)}
  if(['cooler','consider'].includes(result.weather)){
    weatherContext.mode='auto';
    if(result.weather==='cooler'){weatherContext.priority='high';changes.push('weather: cooler walk (heat term ×2 when it is hot)');}
    else changes.push('weather: use today’s forecast');
  }
  planner.weatherIntent=result.weather||null;
  renderPreferenceSummary();
  return changes;
}
async function interpretIntent(q){
  const input=(q||'').trim();if(!input)return [];
  let data,mode='local';
  // A failed short status probe (for example a sleeping Render instance) is not
  // proof that AI is disabled. Attempt the real parse when configuration is unknown.
  if(location.protocol!=='file:' && planner.llmConfigured!==false){
    try{
      const r=await streetwiseFetch('/api/interpret',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:input,weights:planner.weights,budget:state.budget,constraints:planner.constraints,crime:planner.crime||null,waterfront:planner.waterfront||null,weather:weatherWindow(state.budget),history:planner.conversations.slice(-8)}),signal:AbortSignal.timeout(planner.llmConfigured===null?65000:32000)});
      if(!r.ok){const j=await r.json().catch(()=>({}));const why=j.reason?[j.reason.stage,j.reason.http_status,j.reason.type,j.reason.code].filter(Boolean).join(' · '):'';
        console.warn('LLM response rejected:',j.reason||{status:r.status});
        throw new Error(`LLM service ${r.status}${why?` (${why})`:''}`);}
      data=await r.json();mode='llm';planner.llmConnected=true;planner.llmConfigured=true;
      $('interpretMode').textContent='✦ AI VERIFIED · Latest natural-language request succeeded';
    }catch(err){planner.llmConnected=false;$('interpretMode').textContent='◇ LIMITED LOCAL PREVIEW · AI request failed; next plan retries';console.warn('LLM parsing unavailable:',err);toast(`AI parsing unavailable — ${err.message}. Using clearly marked limited local preview.`);}
  }
  if(!data){data=localInterpret(input);if(/\bcrime\b|犯罪/.test(input.toLowerCase()))data.crime={mode:'set',direction:/avoid|lower|less|low crime|避开|低犯罪/i.test(input)?'low':'high',weight:90};}
  if(mode!=='llm'&&/waterfront|river|河边|河岸|海边/i.test(input))data.waterfront={mode:'set',direction:/avoid|away from|not along|避开|不走/i.test(input)?'low':'high',weight:90};
  // Tourist / multi-stop intent: the LLM's structured `journey`, or the labelled local parser when no LLM is configured.
  if(mode!=='llm'&&typeof localJourney==='function'){await warmNameIndex().catch(()=>{});data.journey=localJourney(input);}
  if(typeof data?.clarification==='string'&&data.clarification.trim())return {changes:[],clarification:data.clarification.trim()};
  return {changes:applyInterpretation(data,mode),clarification:null,journey:data.journey||null};
}
async function checkInterpreter(){
  if(location.protocol==='file:'){$('interpretMode').textContent='LOCAL PREVIEW · Start server.py with an API key for genuine LLM understanding';return}
  try{
    const r=await streetwiseFetch('/api/status',{signal:AbortSignal.timeout(2500)});const d=await r.json();planner.llmConfigured=r.ok?Boolean(d.llm):null;planner.llmConnected=Boolean(r.ok&&d.llm);
  }catch(_) {planner.llmConnected=false;planner.llmConfigured=null;}
  $('interpretMode').textContent=planner.llmConnected?'✦ AI CONFIGURED · Connection verified when you plan':planner.llmConfigured===false?'◇ LOCAL PREVIEW · AI backend key is missing or invalid':'◇ AI STATUS UNAVAILABLE · Planning will retry the AI service';
}
function appendChat(role,message){
  planner.conversations.push({role,content:message});$('conversationSection').classList.remove('hidden');
  $('chatHistory').innerHTML=planner.conversations.map(m=>`<div class="chat-message ${m.role==='user'?'user-message':'assistant-message'}"><div class="chat-name">${m.role==='user'?'YOU':'✦ STROLLANE'}</div><div class="chat-copy">${esc(m.content)}</div></div>`).join('');
  $('chatHistory').scrollTop=$('chatHistory').scrollHeight;
  if(role==='assistant' && /Selected |No route meets|Pedestrian service unavailable|Route planning failed/.test(message)){
    $('conversationSection').scrollIntoView({block:'end',behavior:'smooth'});
  }
}
function updateLegendForEvidence(){updateLegend()}

function makeArcGISQuery(endpoint,options={}){
  const p=new URLSearchParams({where:options.where||'1=1',outFields:options.fields||'FID',returnGeometry:'true',outSR:'4326',f:'geojson',resultRecordCount:String(options.count||STREET_PAGE_SIZE)});
  if(options.sort)p.set('orderByFields',options.sort);
  if(Number.isInteger(options.offset))p.set('resultOffset',String(options.offset));
  if(options.bbox){p.set('geometry',options.bbox.join(','));p.set('geometryType','esriGeometryEnvelope');p.set('inSR','4326');p.set('spatialRel','esriSpatialRelIntersects');}
  return `${endpoint}?${p.toString()}`;
}
async function timedJson(url,timeoutMs=14000,opts={}){
  const controller=new AbortController();const t=setTimeout(()=>controller.abort(),timeoutMs);
  try{const response=await streetwiseFetch(url,{signal:controller.signal,...opts});if(!response.ok)throw new Error(`HTTP ${response.status}`);const d=await response.json();if(d.error)throw new Error(d.error.message||JSON.stringify(d.error));return d}finally{clearTimeout(t)}
}
async function loadData(kind){
  if(kind==='streets')return loadManhattanStreets();
  return loadViewportEvidence(kind);
}
async function loadManhattanStreets(){
  if(state.loading.streets)return;
  state.loading.streets=true;
  state.dataComplete.streets=false;
  setSourceStatus('LOADING MANHATTAN STREET CENTERLINES…');
  let features=state.datasets.streets?.features||[];
  let offset=features.length;
  let expected=state.streetExpected;
  try{
    if(expected===null){
      const c=await timedJson(`${API.streets}?${new URLSearchParams({where:"borocode='1'",returnCountOnly:'true',f:'json'})}`,16000);
      expected=Number.isFinite(c.count)?c.count:null;
      state.streetExpected=expected;
    }
    if(!state.datasets.streets){state.datasets.streets=emptyFC();features=state.datasets.streets.features;}
    // Request all Manhattan borough-code-1 records, ordered by stable object ID.
    while(expected===null || offset<expected){
      const d=await timedJson(makeArcGISQuery(API.streets,{where:"borocode='1'",count:STREET_PAGE_SIZE,offset,sort:'FID ASC',fields:'FID,borocode,st_label,st_name,status,physicalid,rw_type'}),26000);
      if(!featureFC(d))throw new Error('NYC service did not return a GeoJSON FeatureCollection');
      if(d.features.length===0){if(expected!==null&&offset<expected)throw new Error('NYC service returned an empty page before completion');break;}
      for(const f of d.features){
        if(f.properties){const clean={};for(const [key,value] of Object.entries(f.properties))clean[key.replace(/\\/g,'')]=value;f.properties=clean;}
        const fid=String(f.properties?.FID??f.id??'');
        if(!fid||state.streetsById.has(fid))continue;
        // Geodetic coordinates belong to the authoritative NYC service. No hand-drawn lines.
        if(!['LineString','MultiLineString'].includes(f.geometry?.type))continue;
        const coords=featureCoords(f);
        f.properties=f.properties||{};
        f.properties.length_km=coords.length>=2?lineLengthKm(coords):null;
        features.push(f);state.streetsById.set(fid,f);
      }
      offset+=d.features.length;
      state.datasets.streets={type:'FeatureCollection',features};
      const denom=expected===null?'?':expected.toLocaleString();
      setSourceStatus(`MANHATTAN · ${features.length.toLocaleString()} / ${denom} STREETS`);
      if(state.mapLayersReady)syncMapData();
      if(d.features.length<STREET_PAGE_SIZE && !d.properties?.exceededTransferLimit && !d.exceededTransferLimit){
        if(expected!==null && offset<expected)throw new Error(`Only ${offset} of ${expected} features were returned`);
        break;
      }
      if(offset>60000)throw new Error('Aborted unexpected oversized dataset');
    }
    if(expected!==null && features.length!==expected)throw new Error(`Only ${features.length} of ${expected} unique street features loaded`);
    state.dataComplete.streets=true;
    setSourceStatus(`MANHATTAN · ${features.length.toLocaleString()} NYC CENTERLINES`,true);
    toast('All Manhattan NYC Street Centerline geometry loaded. Streets are not a pedestrian-accessibility guarantee.');
  }catch(err){
    state.dataErrors.streets=err.message;
    setSourceStatus(`STREET DATA PARTIAL · ${features.length.toLocaleString()} FEATURES`);
    toast(`Street data incomplete (${features.length.toLocaleString()} loaded). Retry button available; no substitute geometry was invented.`);
  }finally{state.loading.streets=false;syncMapData();updateLegend();updateSegmentDetails();}
}
function visibleEnvelope(){
  if(!state.mapReady)return null;
  const b=state.map.getBounds();
  const raw=[Math.max(BBOX[0],b.getWest()),Math.max(BBOX[1],b.getSouth()),Math.min(BBOX[2],b.getEast()),Math.min(BBOX[3],b.getNorth())];
  return raw[0]<raw[2]&&raw[1]<raw[3]?raw:null;
}
let overlayMoveTimer=null;
function scheduleOverlayRefresh(){
  clearTimeout(overlayMoveTimer);
  overlayMoveTimer=setTimeout(()=>{
    if(state.display.trees)loadViewportEvidence('trees');
    if(state.display.lpc)loadViewportEvidence('lpc');
  },540);
}
async function loadViewportEvidence(kind){
  // Point and landmark evidence intentionally follow the current zoomed-in map viewport.
  // Never label their visible subset as complete Manhattan data.
  if(!state.mapReady)return;
  if(state.map.getZoom()<12.3){
    toast(`Zoom in to load ${kind==='trees'?'tree points':'landmark polygons'}; all-island raw evidence is too dense for a first-pass client view.`);
    return;
  }
  const bbox=visibleEnvelope();if(!bbox)return;
  if(state.loading[kind]){state.overlayPending=state.overlayPending||{};state.overlayPending[kind]=true;return;}
  state.loading[kind]=true;
  state.dataComplete[kind]=false;
  try{
    const d=kind==='trees'?{type:'FeatureCollection',features:await fetchOfficialTrees(bbox,14000)}:await timedJson(makeArcGISQuery(API[kind],{bbox,fields:'*',count:OVERLAY_PAGE_SIZE,offset:0}),22000);
    if(!featureFC(d))throw new Error('No valid GeoJSON feature collection');
    // Raw evidence is a VIEWPORT subset; it is never used as a citywide experience score.
    state.datasets[kind]=d;
    state.overlayCoverage[kind]={bbox,loaded:d.features.length,partial:kind==='trees'?false:Boolean(d.properties?.exceededTransferLimit||d.exceededTransferLimit||d.features.length>=OVERLAY_PAGE_SIZE)};
    state.dataComplete[kind]=!state.overlayCoverage[kind].partial;
    if(state.overlayCoverage[kind].partial)toast(`${kind==='trees'?'Trees':'Landmarks'}: showing only ${d.features.length} raw records in this view. Zoom in for a smaller area.`);
    syncMapData();updateLegend();updateSegmentDetails();updateProfile();
  }catch(err){state.dataErrors[kind]=err.message;toast(`${kind.toUpperCase()} data source unavailable: ${err.message}`)}
  finally{state.loading[kind]=false;if(state.overlayPending?.[kind]){state.overlayPending[kind]=false;scheduleOverlayRefresh();}}
}
function setMapLayerVisible(id,yes){if(state.mapReady&&state.map.getLayer(id))state.map.setLayoutProperty(id,'visibility',yes?'visible':'none')}
function getEmptyLine(){return {type:'FeatureCollection',features:[]}}
function currentRoutesGeojson(){return {type:'FeatureCollection',features:state.routes.map(r=>({type:'Feature',properties:{id:r.id,name:r.label,distance_km:r.km,time_min:r.min,network_version:r.raw.network_version,method:'Strollane pedestrian routing engine on the OSM pedestrian graph'},geometry:{type:'LineString',coordinates:r.coords}}))}}
function activeRouteGeojson(){const r=state.routes.find(x=>x.id===state.activeRoute);return r?{type:'FeatureCollection',features:[{type:'Feature',properties:{name:r.label},geometry:{type:'LineString',coordinates:r.coords}}]}:emptyFC()}
function pointGeojson(){const fs=[];for(const type of ['start','end']){const p=getPlace(type);if(p)fs.push({type:'Feature',properties:{role:type,name:p.name||type},geometry:{type:'Point',coordinates:[p.lon,p.lat]}})}if(state.gps)fs.push({type:'Feature',properties:{role:'gps',name:'Device location'},geometry:{type:'Point',coordinates:[state.gps.lon,state.gps.lat]}});return {type:'FeatureCollection',features:fs}}
function syncMapData(){
  const map=state.map;if(!state.mapLayersReady||!map)return;
  for(const [id,data] of [['nyc-roads',state.datasets.streets],['nyc-trees',state.datasets.trees],['nyc-landmarks',state.datasets.lpc],['candidate-routes',currentRoutesGeojson()],['route-edges',routeEdgesGeojson()],['selected-route',activeRouteGeojson()],['points',pointGeojson()],['route-pois',poiGeojson()]]){
    const s=map.getSource(id);if(s)s.setData(data||emptyFC());
  }
  if(typeof updateJourneyMap==='function')updateJourneyMap();
  // An over-limit preview is dashed; a feasible selection is solid lime.
  const active=state.routes.find(x=>x.id===state.activeRoute);
  if(map.getLayer('route-selected'))map.setPaintProperty('route-selected','line-dasharray',active&&!active.feasible?[1.4,1.1]:[1,0]);
  updateMapStyles();
  syncExperienceMap();
}
function updateMapStyles(){
  if(!state.mapLayersReady||!state.map)return;
  const m=state.map, raw=false; // No incomplete raw-record proximity data masquerades as a global nature score.
  const [lo,hi]=state.thresholds;
  const thresholdColor=['#395d63','#45b9c7','#d8f365'];
  const streetColor=raw?['case', ['!', ['has','tree_records_per_km']], '#647479', ['<', ['get','tree_records_per_km'], lo||1], thresholdColor[0], ['<',['get','tree_records_per_km'],hi||2],thresholdColor[1],thresholdColor[2]]:'#476b72';
  if(m.getLayer('road-highlight'))m.setPaintProperty('road-highlight','line-color',streetColor);
  setMapLayerVisible('road-highlight',state.display.roads);
  setMapLayerVisible('road-underlay',state.display.roads);
  setMapLayerVisible('tree-points',state.display.trees);
  setMapLayerVisible('landmark-fill',state.display.lpc);
  setMapLayerVisible('landmark-outline',state.display.lpc);
  // The selected route is always visible; the toggle controls alternative routes only.
  setMapLayerVisible('route-alts',state.display.routes);
  setMapLayerVisible('route-glow',true);
  setMapLayerVisible('route-shadow',true);
  setMapLayerVisible('route-selected',true);
  setMapLayerVisible('poi-points-glow',state.display.pois);
  setMapLayerVisible('poi-points',state.display.pois);
  updateExperienceStyles();
}
function updateLegend(){ renderExperienceLegend(); }
/** Re-tint CARTO's stock dark-matter basemap to the STROLLANE palette (only paint/layout properties
 * on CARTO's own layers — no style replaced, no extra tile requests). Water reads as water instead of
 * void; the road hierarchy gets more contrast; CARTO's own flat building fill is hidden because
 * udg-buildings-fill (real PLUTO footprints, see urban-layers.js) draws richer 3D buildings on top. */
function tuneBasemap(m){
  const set=(id,prop,val)=>{if(m.getLayer(id))m.setPaintProperty(id,prop,val);};
  set('background','background-color','#081114');
  for(const id of ['landcover','landuse'])set(id,'fill-color','#0a1416');
  set('water','fill-color','#0d2630');
  set('water_shadow','fill-color','#061419');
  set('road_mot_fill_noramp','line-color','#5c6a74');
  set('road_mot_fill_ramp','line-color','#5c6a74');
  set('road_pri_fill_noramp','line-color','#46525c');
  set('road_pri_fill_ramp','line-color','#46525c');
  set('road_sec_fill_noramp','line-color','#3a444c');
  set('road_minor_fill','line-color','#2e363d');
  for(const id of ['building','building-top'])if(m.getLayer(id))m.setLayoutProperty(id,'visibility','none');
}
function setupMap(){
  if(!window.maplibregl){ $('mapFallback').querySelector('h2').textContent='Map library unavailable';$('mapFallback').querySelector('p').textContent='Internet access is required to load the live map library. The interface remains accessible.';setSourceStatus('MAP LIBRARY OFFLINE');return;}
  try{
    const m=state.map=new maplibregl.Map({container:'map',style:'https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json',center:CENTER,zoom:10.7,pitch:0,bearing:0,attributionControl:true});
    m.addControl(new maplibregl.NavigationControl({showCompass:false}), 'bottom-right');
    m.on('load',()=>{
      state.mapReady=true;$('mapFallback').classList.add('hidden');m.fitBounds(MANHATTAN_BOUNDS,{padding:24,duration:0,maxZoom:11.1});
      tuneBasemap(m);
      for(const id of ['nyc-roads','nyc-trees','nyc-landmarks','candidate-routes','selected-route','points','route-pois'])m.addSource(id,{type:'geojson',data:emptyFC()});
      m.addLayer({id:'road-underlay',type:'line',source:'nyc-roads',paint:{'line-color':'#0b141b','line-width':5.3,'line-opacity':.85}});
      m.addLayer({id:'road-highlight',type:'line',source:'nyc-roads',paint:{'line-color':'#476b72','line-width':['interpolate',['linear'],['zoom'],11,.6,14,2,16,3.4],'line-opacity':.90}});
      m.addLayer({id:'landmark-fill',type:'fill',source:'nyc-landmarks',paint:{'fill-color':'#e89a5d','fill-opacity':.17}});
      m.addLayer({id:'landmark-outline',type:'line',source:'nyc-landmarks',paint:{'line-color':'#ffae70','line-width':1.5,'line-opacity':.88}});
      m.addLayer({id:'tree-points',type:'circle',source:'nyc-trees',paint:{'circle-color':'#a6e19a','circle-radius':['interpolate',['linear'],['zoom'],11,1.5,14,3,16,5],'circle-opacity':.82,'circle-stroke-color':'#0a2524','circle-stroke-width':.6}});
      // Route hierarchy: quiet dashed alternatives; the selected route is the only lime on the map, with a dark halo that separates it from data below.
      m.addLayer({id:'route-alts',type:'line',source:'candidate-routes',paint:{'line-color':'#8a9e9c','line-width':['interpolate',['linear'],['zoom'],12,1.6,16,3],'line-opacity':.55,'line-dasharray':[2,1.6]},layout:{'line-cap':'round','line-join':'round'}});
      // Glow beneath the dark separator shadow: a wide, soft-blurred lime halo (Citymapper/Google night-mode
      // routing). The dark route-shadow above it still does its job of separating the line from data clutter.
      m.addLayer({id:'route-glow',type:'line',source:'selected-route',paint:{'line-color':'#d8f365','line-width':['interpolate',['linear'],['zoom'],12,14,16,22,19,30],'line-opacity':.22,'line-blur':6},layout:{'line-cap':'round','line-join':'round'}});
      m.addLayer({id:'route-shadow',type:'line',source:'selected-route',paint:{'line-color':'#06110f','line-width':['interpolate',['linear'],['zoom'],12,6,16,11,19,16],'line-opacity':.82,'line-blur':1},layout:{'line-cap':'round','line-join':'round'}});
      m.addLayer({id:'route-selected',type:'line',source:'selected-route',paint:{'line-color':'#d8f365','line-width':['interpolate',['linear'],['zoom'],12,2.6,16,5,19,8],'line-opacity':1},layout:{'line-cap':'round','line-join':'round'}});
      m.addLayer({id:'poi-points-glow',type:'circle',source:'route-pois',paint:{'circle-color':'#b7a3e1','circle-radius':13,'circle-opacity':.3,'circle-blur':1}});
      m.addLayer({id:'poi-points',type:'circle',source:'route-pois',paint:{'circle-color':'#b7a3e1','circle-radius':5,'circle-stroke-color':'#132529','circle-stroke-width':2}});
      m.addLayer({id:'point-starts-glow',type:'circle',source:'points',filter:['==',['get','role'],'start'],paint:{'circle-color':'#6fd2d8','circle-radius':['interpolate',['linear'],['zoom'],12,11,16,16],'circle-opacity':.35,'circle-blur':1}});
      m.addLayer({id:'point-starts',type:'circle',source:'points',filter:['==',['get','role'],'start'],paint:{'circle-color':'#6fd2d8','circle-radius':['interpolate',['linear'],['zoom'],12,4.5,16,7],'circle-stroke-color':'#0b1418','circle-stroke-width':2.5}});
      m.addLayer({id:'point-ends-glow',type:'circle',source:'points',filter:['==',['get','role'],'end'],paint:{'circle-color':'#f2a876','circle-radius':['interpolate',['linear'],['zoom'],12,11,16,16],'circle-opacity':.35,'circle-blur':1}});
      m.addLayer({id:'point-ends',type:'circle',source:'points',filter:['==',['get','role'],'end'],paint:{'circle-color':'#f2a876','circle-radius':['interpolate',['linear'],['zoom'],12,4.5,16,7],'circle-stroke-color':'#0b1418','circle-stroke-width':2.5}});
      m.addLayer({id:'point-gps-glow',type:'circle',source:'points',filter:['==',['get','role'],'gps'],paint:{'circle-color':'#6dd2ff','circle-radius':16,'circle-opacity':.35,'circle-blur':1}});
      m.addLayer({id:'point-gps',type:'circle',source:'points',filter:['==',['get','role'],'gps'],paint:{'circle-color':'#6dd2ff','circle-radius':7,'circle-stroke-color':'#fff','circle-stroke-width':3}});
      setupRouteEdgeLayer();setupUrbanMap();if(typeof setupJourneyMap==='function')setupJourneyMap();if(typeof setupNavMap==='function')setupNavMap();
      state.mapLayersReady=true; setupExperienceMap(); syncMapData();updateMapStyles();
      m.on('click','road-highlight',(e)=>{if(state.pick||m.queryRenderedFeatures(e.point,{layers:['route-edge-hit',...urbanMapLayerIds()]}).length)return;const feat=e.features?.[0];if(!feat)return;const fid=feat.properties?.FID;const real=state.streetsById.get(String(fid));state.selectedStreet=real||feat;updateSegmentDetails();});
      m.on('click','route-alts',(e)=>{if(state.pick||m.queryRenderedFeatures(e.point,{layers:['route-edge-hit']}).length)return;  // a click on the selected route's segment opens its evidence instead
      const name=e.features?.[0]?.properties?.id;if(name)selectRoute(name)});
      m.on('click','poi-points',(e)=>{if(state.pick)return;const f=e.features?.[0];if(f?.properties?.name)showPOIPopup(f,e.lngLat)});
      m.on('click',async(e)=>{if(!state.pick)return;const kind=state.pick;const p={id:`map:${e.lngLat.lat.toFixed(5)},${e.lngLat.lng.toFixed(5)}`,name:`Map point ${e.lngLat.lat.toFixed(4)}, ${e.lngLat.lng.toFixed(4)}`,lat:e.lngLat.lat,lon:e.lngLat.lng,source:'Selected on map'};state[kind==='start'?'customStart':'customEnd']=p;state[kind]='custom';$(kind==='start'?'startSelect':'endSelect').value='custom';$(kind==='start'?'searchStart':'searchEnd').value=p.name;state.pick=null;$('pickNotice').classList.add('hidden');m.getCanvas().style.cursor='';resetRoutes();syncMapData();if(typeof placeInputs!=='undefined')placeInputs[kind]?.set(p);if(typeof reverseGeocode==='function'){const r=await reverseGeocode(p.lat,p.lon);if(r){p.address=r.address;p.borough=r.borough;p.name=`Near ${r.address}`;placeInputs[kind]?.set(p);$(kind==='start'?'searchStart':'searchEnd').value=p.name;}}toast(`${kind==='start'?'Start':'Destination'} set from the map.`)});
      for(const layer of ['road-highlight','route-alts']){m.on('mouseenter',layer,()=>{m.getCanvas().style.cursor=state.pick?'crosshair':'pointer'});m.on('mouseleave',layer,()=>{m.getCanvas().style.cursor=state.pick?'crosshair':''})}
      m.on('moveend',()=>{scheduleOverlayRefresh();$('mapCoords').textContent=`${m.getCenter().lat.toFixed(3)}° N · ${Math.abs(m.getCenter().lng).toFixed(3)}° W`});
      // Auto-tilt the 3D buildings into view as the walker zooms in (flat city overview → tilted street level),
      // the same zoom-triggered pattern Google Maps/Apple Maps use. Only on zoomend (not every 'zoom' tick) so
      // this never fights the user's own pinch/scroll gesture; live navigation forces pitch:0 of its own accord
      // (nav-ui.js updateCamera), so this never tilts the GPS view.
      m.on('zoomend',()=>{
       if(document.body.classList.contains('nav-mode'))return;
       const nz=UrbanStyle.T.zoom.neighbourhood,z=m.getZoom(),target=z>=nz?Math.min(50,(z-nz)*13):0;
       if(Math.abs(m.getPitch()-target)>2)m.easeTo({pitch:target,duration:600});
      });
    });
    m.on('error',(event)=>{if(event?.error)console.warn(state.mapReady?'MapLibre style/data error:':'MapLibre loading issue:',event.error.message)});
    setTimeout(()=>{if(!state.mapReady){$('mapFallback').querySelector('h2').textContent='Map tiles not reachable';$('mapFallback').querySelector('p').textContent='The web prototype is ready, but external basemap tiles require a network connection. The GIS layers can be explored when online.'}},16000);
  }catch(err){ $('mapFallback').querySelector('h2').textContent='Map initialization failed';$('mapFallback').querySelector('p').textContent=err.message;}
}

function resetRoutes(keepRun=false){if(!keepRun)planner.runId++; planner.routeResponse=null;if(typeof journey!=='undefined'){journey.plan=null;renderCityWalk();}state.routes=[];state.activeRoute=null;planner.routePois=[];planner.poiStatus='Not loaded';renderPOIs();updateWhyRoute();renderRouteEdges();if(typeof urbanLayersRouteChanged==='function')urbanLayersRouteChanged();$('rankingStatus').textContent='Journey changed. Plan again to update route geometry.';renderRouteCards();updateProfile();syncMapData();}
function routeBounds(routes,extraMeters=100){
  const all=routes.flatMap(r=>r.coords);
  if(!all.length)return null;
  const lon=all.map(x=>x[0]),lat=all.map(x=>x[1]),dx=extraMeters/85000,dy=extraMeters/111320;
  return [Math.min(...lon)-dx,Math.min(...lat)-dy,Math.max(...lon)+dx,Math.max(...lat)+dy];
}
async function fetchOfficialTrees(bbox,maxRecords){
  const where=`latitude between ${bbox[1]} and ${bbox[3]} AND longitude between ${bbox[0]} and ${bbox[2]} AND borocode='1'`;
  const query=args=>API.trees+'?'+Object.entries(args).map(([k,v])=>encodeURIComponent(k)+'='+encodeURIComponent(v)).join('&');
  const count=await timedJson(query({'$select':'count(*) as n','$where':where}),23000),expected=Number(count[0]?.n);
  if(!Number.isInteger(expected)||expected>maxRecords)throw new Error('Official tree source exceeds bounded scan');
  const rows=[],ids=new Set();
  while(rows.length<expected){
    const page=await timedJson(query({'$where':where,'$order':'tree_id','$limit':1000,'$offset':rows.length}),23000);
    if(!Array.isArray(page)||!page.length)throw new Error('Official tree source incomplete');
    for(const r of page){if(!r.tree_id||ids.has(r.tree_id)||!Number.isFinite(Number(r.longitude))||!Number.isFinite(Number(r.latitude)))throw new Error('Invalid or duplicate official tree record');ids.add(r.tree_id);rows.push(r);}
    if(rows.length>expected)throw new Error('Tree source changed during scan');
  }
  return rows.map(r=>({type:'Feature',id:r.tree_id,properties:r,geometry:{type:'Point',coordinates:[Number(r.longitude),Number(r.latitude)]}}));
}
async function fetchCompleteEvidence(kind,bbox,maxRecords){
  if(kind==='trees')return fetchOfficialTrees(bbox,maxRecords);
  const base=API[kind].replace(/\/query$/,'');
  const meta=await timedJson(base+'?f=json',16000);
  const oid=meta.fields?.find(f=>f.type==='esriFieldTypeOID')?.name;
  if(!oid)throw new Error(kind+': no stable object ID');
  const countURL=new URL(makeArcGISQuery(API[kind],{bbox}));
  countURL.searchParams.set('f','json');countURL.searchParams.set('returnCountOnly','true');
  const countResult=await timedJson(countURL.toString(),18000), expected=countResult.count;
  if(!Number.isInteger(expected)||expected>maxRecords)throw new Error(kind+': coverage exceeds verified browser scan');
  const features=[],ids=new Set();
  while(features.length<expected){
    const d=await timedJson(makeArcGISQuery(API[kind],{bbox,fields:'*',count:1000,offset:features.length,sort:oid+' ASC'}),23000);
    if(!featureFC(d)||!d.features.length)throw new Error(kind+': incomplete coverage');
    for(const f of d.features){const id=String(f.properties?.[oid]??f.id);if(id==='undefined'||ids.has(id))throw new Error(kind+': unstable pagination');ids.add(id);features.push(f);}
    if(features.length>expected)throw new Error(kind+': source changed during scan');
  }
  return features;
}
async function handlePlan(text,isFollowUp=false){
  if(state.routingBusy||planner.parsing)return;
  const q=(text||'').trim();if(!q){toast('Describe the walk you want.');return}
  for(const kind of ['start','end']){if(kind==='end'&&typeof journey!=='undefined'&&journey.endMode!=='fixed')continue;const typed=$(kind==='start'?'searchStart':'searchEnd').value.trim(),chosen=getPlace(kind);if(typed!==chosen?.name){toast(`Search and choose a ${kind==='start'?'starting point':'destination'} result first, or use a preset.`);return}}
  planner.parsing=true;$('generateRoutes').disabled=true;$('chatSend').disabled=true;
  appendChat('user',q);
  try{const result=await interpretIntent(q);if(result.clarification){$('rankingStatus').textContent='Clarification needed. The displayed previous route has not been recalculated.';appendChat('assistant',result.clarification+' The displayed previous route has not been recalculated.');return;}
    if(planner.weatherIntent==='ask'&&state.routes.length){if(weatherContext.status!=='ok')await loadWeather();appendChat('assistant',weatherAnswer());return;}
    if(typeof applyJourney==='function'&&result.journey){
      const jc=await applyJourney(result.journey);
      if(journey.businessOnly)return;
      if(jc.length)appendChat('assistant',`${planner.interpretation==='llm'?'AI':'Limited local'} journey interpretation: ${jc.join(' · ')}.`);
      // "find" requests (nearby / along the walk) list real places without changing the plan
      const finds=journey.services.filter(s=>!s.addAsStop&&result.journey.services.includes(s.type));
      for(const s of finds){const r=await findServices(s.type,s.scope);showFoundPlaces(`${SERVICE_LABEL[s.type]} ${s.scope==='near_hotel'?'near your hotel':s.scope==='along_route'?'along your walk':'near the start'}`,r.places,{note:r.note});
        appendChat('assistant',r.places.length?`${r.places.length} ${SERVICE_LABEL[s.type].toLowerCase()} option(s): ${r.places.slice(0,3).map(p=>p.name+(p.detour?` (+${p.detour.detour_min} min)`:'')).join(', ')}. Add one as a stop from the list. ${r.note}`:`No ${SERVICE_LABEL[s.type].toLowerCase()} found. ${r.note}`);
        journey.services=journey.services.filter(x=>x!==s);}
      if(finds.length&&!journeyIntentPresent({...result.journey,services:[]})&&state.routes.length)return;
    }
    const changes=result.changes;if(changes.length)appendChat('assistant',`${planner.interpretation==='llm'?'AI interpretation':'Limited local interpretation'}: ${changes.join(' · ')}. Checking feasible pedestrian paths…`);
    else appendChat('assistant',`No explicit preference change recognized${planner.interpretation==='local'?' by limited local preview':''}. I’ll check route options using current settings.`);
  }catch(err){toast('Unable to interpret preferences: '+err.message);return;}
  finally{planner.parsing=false;$('generateRoutes').disabled=false;$('chatSend').disabled=false}
  if(typeof journeyMode==='function'&&journeyMode())await planJourney(isFollowUp);
  else await generateRoutes(q,isFollowUp);
}

function poiDimension(tags){if(tags.tourism==='museum'||tags.tourism==='gallery'||tags.amenity==='theatre')return'Culture';if(tags.leisure==='park'||tags.leisure==='garden')return'Nature';if(tags.historic||tags.tourism==='attraction')return'Architecture';if(tags.amenity==='cafe'||tags.amenity==='restaurant')return'Food & Retail';if(tags.tourism==='viewpoint')return'Scenic & Visual';return null}
async function loadRoutePOIs(run){
  if(!state.routes.length){planner.routePois=[];renderPOIs();return}
  const box=routeBounds(state.routes,120);
  planner.poiStatus='Fetching OpenStreetMap POIs…';renderPOIs();
  if(!box || box[2]-box[0]>.055||box[3]-box[1]>.055){planner.routePois=[];planner.poiStatus='Route is too wide for this bounded POI lookup';renderPOIs();return}
  try{
    if(location.protocol==='file:')throw new Error('Run server.py for verified POIs');
    const res=await streetwiseFetch('/api/pois',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({bbox:box}),signal:AbortSignal.timeout(25000)});
    if(!res.ok)throw new Error(`POI service HTTP ${res.status}`);
    const json=await res.json();if(run!==planner.runId)return;
    planner.routePois=(json.pois||[]).filter(x=>Number.isFinite(x.lon)&&Number.isFinite(x.lat)&&x.name).slice(0,450);
    planner.poiStatus=`${planner.routePois.length} ${json.source||'OSM'} records${json.status==='snapshot_fallback'?` · live provider unavailable · snapshot ${json.retrieved_at||'date unknown'}`:''}`;
  }catch(err){if(run!==planner.runId)return;planner.routePois=[];planner.poiStatus='OSM POIs unavailable: '+err.message}
  renderPOIs();syncMapData();
}
function activePOIs(){
  const r=state.routes.find(x=>x.id===state.activeRoute);if(!r)return [];
  return planner.routePois.map(x=>({...x,distance:Math.round(polylinePointDistanceM([x.lon,x.lat],r.coords))}))
    .filter(x=>x.distance<=100 && poiDimension(x.tags)).sort((a,b)=>a.distance-b.distance).slice(0,14);
}
function polylinePointDistanceM(p,coords){let min=Infinity;for(let i=1;i<coords.length;i++)min=Math.min(min,segmentDistanceM(p,coords[i-1],coords[i]));return min}
function poiGeojson(){return {type:'FeatureCollection',features:state.display.pois?activePOIs().map(p=>({type:'Feature',properties:{name:p.name,category:poiDimension(p.tags),distance_m:p.distance},geometry:{type:'Point',coordinates:[p.lon,p.lat]}})):[]}}
function renderPOIs(){
  const list=activePOIs();$('poiCount').textContent=`${list.length} NEAR ROUTE`;
  if(!list.length){$('poiList').innerHTML=`<p class="status-empty">${esc(planner.poiStatus==='Not loaded'?'Generate or select a route to discover POIs.':planner.poiStatus||'No named OSM POIs confirmed near route.')}</p>`;return}
  $('poiList').innerHTML=`<small>${esc(planner.poiStatus)}</small>`+list.map((p,i)=>`<button class="poi-item" type="button" data-poi="${i}"><span><strong>${esc(p.name)}</strong><small>${esc(poiDimension(p.tags))} · OpenStreetMap</small></span><span class="poi-distance">${p.distance} m ↗</span></button>`).join('');
  $('poiList').querySelectorAll('[data-poi]').forEach(el=>el.addEventListener('click',()=>{
    const p=list[+el.dataset.poi];if(state.mapReady)state.map.flyTo({center:[p.lon,p.lat],zoom:16.4,duration:500});toast(`${p.name} · ${p.distance} m from route geometry`);
  }));
}
function updateSegmentDetails(){
  const f=state.selectedStreet,root=$('segmentDetail');
  if(!f){root.innerHTML='<p class="soft-copy">Click a street segment on the map to inspect its recorded properties.</p>';return}
  const p=f.properties||{},name=p.st_label||p.st_name||'Unnamed street centerline';
  let html=`<div class="segment-head">${esc(name)}</div><div class="data-pair"><span>NYC centerline feature ID</span><span>${esc(p.FID||f.id||'—')}</span></div><div class="data-pair"><span>Geometry length</span><span>${Number.isFinite(p.length_km)?Math.round(p.length_km*1000)+' m':'—'}</span></div>`;
  if(false && state.treeStatsReady && Number.isFinite(p.tree_records_per_km)){
    html+=`<div class="data-pair"><span>2015 tree records ≤75m</span><span>${p.tree_records_75m}</span></div><div class="data-pair"><span>Nearby tree records / km</span><span>${formatNum(p.tree_records_per_km,1)}</span></div>`;
  }else html+='<div class="data-pair"><span>Tree proximity</span><span>Not computed</span></div>';
  html+=`<p class="source-help">Source: NYC Street Centerline (road centerline geometry). Proximity counts can overlap between segments. Walkability, shade and safety are not inferred from this record.</p>`;
  root.innerHTML=html;
}

/** Weather lives in weather.js (one shared context); this keeps the old entry point and passes the GPS position. */
function loadWeather(force=false){
  const here=state.gps&&latLonInsideManhattanEnvelope(state.gps)?{lat:state.gps.lat,lon:state.gps.lon}:null;
  return refreshWeather(force,here);
}
function requestGPS(useAsStart=false,follow=false){
  if(!navigator.geolocation){$('gpsMain').textContent='UNAVAILABLE';toast('Geolocation is unavailable in this browser.');return}
  if(!window.isSecureContext && !['localhost','127.0.0.1'].includes(location.hostname)){$('gpsMain').textContent='HTTPS REQUIRED';toast('GPS requires HTTPS or localhost.');return}
  $('gpsMain').textContent='REQUESTING';
  const good=(p)=>{
    setGpsPosition(p.coords);
    if(useAsStart){if(!latLonInsideManhattanEnvelope(state.gps))toast('GPS is outside the Manhattan study envelope. You may explore the map, but routing here targets Manhattan.');else{state.start='gps';$('startSelect').value='gps';$('searchStart').value='My current location';resetRoutes();syncMapData()}}
    if(state.mapReady)state.map.flyTo({center:[state.gps.lon,state.gps.lat],zoom:15.5,duration:800});
    if(!follow)toast('GPS location acquired. It is not transmitted to our own server.');
    loadWeather();
  };
  const bad=(err)=>{toast(`Unable to access GPS: ${err.message||'location denied or timed out'}`);$('gpsMain').textContent=({1:'DENIED',2:'UNAVAILABLE',3:'TIMED OUT'})[err.code]||'UNAVAILABLE'};
  if(follow){if(state.gpsWatch!==null){navigator.geolocation.clearWatch(state.gpsWatch);state.gpsWatch=null;$('gpsMain').textContent='STOPPED';toast('Continuous GPS updates stopped.');return} state.gpsWatch=navigator.geolocation.watchPosition(good,bad,{enableHighAccuracy:true,maximumAge:4000,timeout:15000});toast('Foreground-only location updates enabled.');}
  else navigator.geolocation.getCurrentPosition(good,bad,{enableHighAccuracy:true,maximumAge:0,timeout:14000});
}
function downloadGeoJSON(name,fc){const blob=new Blob([JSON.stringify(fc,null,2)],{type:'application/geo+json'});const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),3000)}
const modalOverlay=$('modalOverlay');
function openModal(kind){
  modalOverlay.classList.remove('hidden');const c=$('modalContent');$('modalTitle').textContent=kind==='export'?'Explore this data in Kepler.gl.':kind==='data'?'The 12 Urban Data Domains.':'What is real, and what comes next.';
  if(kind==='export'){
    state.datasets.experience={type:'FeatureCollection',features:experienceFeatures()};
    const items=[['experience','Computed sections (NULL validated scores)'],['streets','Manhattan NYC centerlines (all pages)'],['trees','2015 tree records (current view)'],['lpc','LPC polygons (current view)']];
    const rows=items.map(([id,label])=>`<li><strong>${esc(label)}</strong> — ${state.datasets[id]?.features?.length||0} features <button data-export="${id}" ${!state.datasets[id]?'disabled':''}>Download GeoJSON</button></li>`).join('');
    c.innerHTML=`<p>Kepler.gl is the <strong>GIS exploration workspace</strong>. Export the real official street records and viewport evidence currently loaded in this website, then drag the GeoJSON files into Kepler.gl. The navigation shell itself uses MapLibre; native Kepler embedding is a later React step.</p><ul class="export-list">${rows}<li><strong>Computed pedestrian routes</strong> — ${state.routes.length} available <button data-export="routes" ${!state.routes.length?'disabled':''}>Download GeoJSON</button></li></ul><p>Citywide street GeoJSON loads in batches. Trees and landmarks are viewport-only raw evidence, not complete Manhattan datasets or experience scores.</p><div class="modal-actions"><button id="goKeplerFromModal">Open Kepler.gl Studio ↗</button></div>`;
    c.querySelectorAll('[data-export]').forEach(b=>b.addEventListener('click',()=>{const id=b.dataset.export;const d=id==='routes'?currentRoutesGeojson():state.datasets[id];if(d)downloadGeoJSON(`Strollane_${id}_Manhattan_or_viewport.geojson`,d)}));
    $('goKeplerFromModal').addEventListener('click',()=>window.open(API.kepler,'_blank','noopener,noreferrer'));
  }else if(kind==='methodology'){
    c.innerHTML=renderMethodology();
  }else if(kind==='data'){
    c.innerHTML=`<p>The project's 12 domains are a <strong>catalog of candidate urban data</strong>, not proof that every dataset is acquired, cleaned or represented as a GIS layer.</p><ol>${DOMAINS.map(t=>`<li>${esc(t)}</li>`).join('')}</ol><h3>Currently used</h3><p>NYC LION street centerlines, NYC Parks Forestry Tree Points and Parks Properties, LPC individual landmarks, NYC planimetric sidewalks, 311 noise complaints, NYPD pedestrian-injury crashes, MTA subway entrances and OpenStreetMap places score the 12 dimensions on every Manhattan street segment. Routes are computed by the STROLLANE engine on the OpenStreetMap pedestrian graph. Open-Meteo supplies weather context only.</p><h3>What still needs research</h3><p>Calibrating the relative ranks against observed walking experience, pedestrian-volume adjustment for crash exposure, sensitivity tests of buffer distances, and verified accessibility (curb ramps, elevators) data.</p>`;
  }else{
    c.innerHTML=`<p><strong>NYC Urban Experience Navigator</strong> is a research prototype. It is not a turn-by-turn navigation app and its scores are not a validated index.</p><h3>Real / verifiable components</h3><p>Walking routes come from the STROLLANE routing engine on the OpenStreetMap pedestrian graph; every route lists the OSM edges it uses. The 12 experience scores are computed from public NYC and OSM records on NYC LION street segments and transferred to OSM edges through a documented LION–OSM match table. Weather comes from Open-Meteo. GPS requires your permission and stays in your browser except when checking progress along a planned route on the local server.</p><h3>Prototype / incomplete components</h3><p>Scores are relative ranks within Manhattan, not calibrated measurements. Walking time uses a fixed 4.8 km/h pace. Step-free routing is blocked until accessibility data is connected. There is no voice guidance or live traffic.</p>`;
  }
}
function renderMethodology(){
  return `<p><strong>Two layers, one score definition.</strong> Experience scores are measured on NYC LION street segments (Explore Urban Data). Routing uses the OpenStreetMap pedestrian graph; each OSM edge takes the scores of the LION segments it matches (by distance, direction, street name and level), or is measured directly with the same indicator code when no reliable match exists (crossings, park paths, bridges).</p><p><strong>Scores</strong> are 0–100 percentile ranks among Manhattan street segments, not calibrated measurements. Missing data is N/A, never zero. Each dimension's sub-indicators, units, methods and sources are listed in the Street Segment Inspector in Explore Urban Data.</p><p><strong>Route score</strong> per dimension = Σ(length × score) / Σ(scored length) over the route's OSM edges, with coverage = scored length ÷ route length. <strong>Ranking</strong> = weighted experience (your preferences; low-coverage dimensions pulled toward neutral 50) − 0.4 × detour %. Routes over the time or detour limit are not recommended.</p><h3>12 dimensions</h3><ol>${DIMENSIONS.map(d=>`<li><strong>${esc(d.name)}</strong> — ${esc(d.desc)}</li>`).join('')}</ol>`;
}
function closeModal(){modalOverlay.classList.add('hidden')}
function setupControls(){
  renderPreferenceSummary();updateLegend();checkInterpreter();renderPOIs();updateWhyRoute();
  $('searchStart').value='Bryant Park';$('searchEnd').value='Rockefeller Center';
  for(const kind of ['start','end']){
    $(kind==='start'?'startSelect':'endSelect').addEventListener('change',e=>{
      state[kind]=e.target.value;const p=getPlace(kind);$(kind==='start'?'searchStart':'searchEnd').value=p?.name||'';if(typeof placeInputs!=='undefined')placeInputs[kind]?.set(p);if(kind==='end'&&typeof setEndMode==='function'){journey.userSetDestination=true;setEndMode('fixed');}resetRoutes();syncMapData();
    });
  }
  $('timeRange').addEventListener('input',e=>{setBudget(Number(e.target.value));updateRoutesUI()});
  document.querySelectorAll('[data-walk-min]').forEach(b=>b.addEventListener('click',()=>{
    if(b.dataset.walkMin==='custom'){$('customTime').focus();$('customTime').select();return;}
    setBudget(Number(b.dataset.walkMin));renderPreferenceSummary();updateRoutesUI();}));
  document.querySelectorAll('[data-walk-km]').forEach(b=>b.addEventListener('click',()=>{
    const k=b.dataset.walkKm;if(k==='custom'){$('customDist').focus();return;}
    setDistanceLimit(k==='none'?null:Number(k));renderPreferenceSummary();updateRoutesUI();}));
  document.querySelectorAll('[data-dist-unit]').forEach(b=>b.addEventListener('click',()=>{state.distUnit=b.dataset.distUnit;syncDistanceUI();}));
  $('customDist').addEventListener('change',e=>{const raw=e.target.value.trim();const km=raw===''?null:Number(raw)*(state.distUnit==='mi'?KM_PER_MILE:1);
    if(!setDistanceLimit(km)){toast('Enter a distance above 0.');syncDistanceUI();}renderPreferenceSummary();updateRoutesUI();});
  $('outingMin').addEventListener('change',e=>{const raw=e.target.value.trim(),x=Number(raw);
    state.outingMin=raw===''?null:Number.isInteger(x)&&x>=10?x:state.outingMin;e.target.value=state.outingMin??'';renderPreferenceSummary();});
  // Custom maximum: free typing (empty allowed while editing); validated on blur / Enter; invalid input restores the last valid value.
  const commitCustomTime=()=>{const raw=$('customTime').value;if(String(state.budget)===raw.trim())return;
    if(setBudget(raw)){renderPreferenceSummary();updateRoutesUI();}
    else{toast(`Enter whole minutes, ${MIN_WALK_MINUTES} or more. Kept ${state.budget} min.`);$('customTime').value=state.budget;}};
  $('customTime').addEventListener('change',commitCustomTime);
  $('customTime').addEventListener('blur',commitCustomTime);
  $('customTime').addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();commitCustomTime();}});
  $('maxDetourPct').addEventListener('change',e=>{const v=Number(e.target.value);if(Number.isFinite(v)&&v>=0&&v<=100){planner.maxDetourPct=v;updateRoutesUI()}else{toast('Choose a detour limit from 0 to 100%.');renderPreferenceSummary()}});
  $('generateRoutes').addEventListener('click',()=>handlePlan($('intentText').value,false));
  $('expandDimensions').addEventListener('click',()=>{
    const open=$('dimensionsPanel').classList.toggle('hidden')===false;$('expandDimensions').setAttribute('aria-expanded',String(open));$('dimensionChevron').textContent=open?'⌃':'⌄';
  });
  $('adjustPreferences').addEventListener('click',()=>{planner.adjust=!planner.adjust;$('adjustPreferences').setAttribute('aria-pressed',String(planner.adjust));$('adjustPreferences').textContent=planner.adjust?'✓ Done adjusting preferences':'✎ Adjust preferences';renderDimensions()});
  for(const k of ['avoidDetours','stepFree','avoidStairs'])$(k).addEventListener('change',e=>{planner.constraints[k]=e.target.checked;renderPreferenceSummary();updateRoutesUI()});
  $('chatForm').addEventListener('submit',e=>{e.preventDefault();const q=$('chatInput').value.trim();if(!q)return;$('chatInput').value='';handlePlan(q,true)});
  $('chatInput').addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();$('chatForm').requestSubmit()}});
  $('gpsStart').addEventListener('click',()=>requestGPS(true));
  $('mapLocate').addEventListener('click',()=>requestGPS(false,true));
  $('mapReset').addEventListener('click',()=>{if(state.mapReady){state.map.fitBounds(MANHATTAN_BOUNDS,{padding:24,duration:800,maxZoom:11.1})}});
  $('retryStreets').addEventListener('click',()=>{if(state.loading.streets)return;if(state.dataComplete.streets){toast('All Manhattan street lines are already loaded.');return}loadManhattanStreets()});
  for(const kind of ['start','end'])$(kind==='start'?'pickStart':'pickEnd').addEventListener('click',()=>{
    if(!state.mapReady){toast('Wait for the map to connect.');return}
    state.pick=kind;$('pickNotice').classList.remove('hidden');state.map.getCanvas().style.cursor='crosshair';
  });
  $('cancelPick').addEventListener('click',()=>{state.pick=null;$('pickNotice').classList.add('hidden');if(state.mapReady)state.map.getCanvas().style.cursor=''});
  for(const [key,id] of [['roads','layerRoads'],['routes','layerRoutes']]){
    $(id).addEventListener('change',e=>{state.display[key]=e.target.checked;if(e.target.checked&&(key==='trees'||key==='lpc'))loadViewportEvidence(key);updateMapStyles();updateLegend()});
  }
  $('exportKepler').addEventListener('click',()=>openModal('export'));
  $('openKepler').addEventListener('click',()=>openModal('export'));
  $('openInfo').addEventListener('click',()=>openModal('about'));
  $('toggleData').addEventListener('click',()=>openModal('data'));
  $('clearSelection').addEventListener('click',()=>{state.selectedStreet=null;updateSegmentDetails()});
  $('profileSelected').addEventListener('click',()=>{planner.profileView='selected';updateProfile()});
  $('profileCompare').addEventListener('click',()=>{planner.profileView='compare';updateProfile()});
  $('openMethodology').addEventListener('click',()=>openModal('methodology'));
  $('layerPOIs').addEventListener('change',e=>{state.display.pois=e.target.checked;updateMapStyles();syncMapData()});
  document.querySelectorAll('[data-refine]').forEach(button=>button.addEventListener('click',()=>{
    const mode=button.dataset.refine;
    const messages={nature:'More nature and greenery.',quiet:'Quieter streets, less noise.',architecture:'More interesting architecture.',shorter:'Find a shorter walk with the same destination.'};
    $('chatInput').value=messages[mode];$('conversationSection').classList.remove('hidden');handlePlan(messages[mode],true);
  }));
  $('closeModal').addEventListener('click',closeModal);
  modalOverlay.addEventListener('click',e=>{if(e.target===modalOverlay)closeModal()});
  document.addEventListener('keydown',e=>{if(e.key==='Escape'){closeModal();state.pick=null;$('pickNotice').classList.add('hidden');if(state.mapReady)state.map.getCanvas().style.cursor=''}});
  $('mobilePlan').addEventListener('click',()=>{$('leftPanel').classList.toggle('mobile-active');$('rightPanel').classList.remove('mobile-active')});
  $('mobileResults').addEventListener('click',()=>{$('rightPanel').classList.toggle('mobile-active');$('leftPanel').classList.remove('mobile-active')});
}

// Initialization is shared with center-map.js after extension functions are loaded.
