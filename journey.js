'use strict';
/* AI Discover My Walk: shared journey state, agent tools and multi-stop planning.

   One state object (journey) is read by the left panel, the map and Route Intelligence; start and destination stay in
   the existing state.start / state.end (getPlace), so every panel sees the same places.
   Tools (each returns real data or an explicit "not available"):
     autocomplete_places / search_places      places.js (Photon + NYC GeoSearch, five boroughs)
     discover_attractions / search_restaurants / search_hotels / search_local_services
                                              data/places/*.json — OpenStreetMap + NYC LPC + NYC restrooms snapshot,
                                              limited to the walking-route coverage (Manhattan)
     verify_menu_item                         POST /api/menu/verify (official website only)
     recommend_food                           POST /api/recommend/food (hard filters → menu evidence → detour → explanation)
     get_place_details / get_place_ratings    GET /api/places/<id>, /api/places/<id>/ratings (per provider; blocked without keys)
     find_along_route                         POST /api/detours (real network detours)
     plan_itinerary                           POST /api/itinerary (network matrix, ordering, experience-aware legs)
     get_current_location / get_weather_context   existing GPS and weather.js
   The language step (LLM when configured, otherwise the clearly-labelled local parser) only fills names, categories and
   limits. It never supplies coordinates, menus, hours, distances or scores. */
const journey={
 endMode:'fixed',          // fixed | open | round | hotel
 hotel:null,rememberHotel:false,
 interests:[],             // famous | museums | historic | parks | shopping | culture
 requirements:{},counts:{},unresolved:[],
 food:[],                  // {category,item,cuisine,required}
 services:[],              // {type,scope,addAsStop}
 named:[],                 // resolved concrete stops: {place,required,order,visitMin,visitEstimated}
 extra:{},                 // "one more museum": extra pool places per interest
 removed:new Set(),        // place ids the user removed
 replaced:{},              // slot id -> place chosen by the user
 plan:null,lastFound:null,menu:{},recs:{},pending:false,active:false,
};
const POI_CACHE={};
// Typical short-visit estimates (minutes); always shown as estimates and editable per stop.
const VISIT_MIN={museums:45,attractions:20,historic:10,historic_lpc:10,parks:20,culture:20,shopping:25,cafes:15,bakeries:10,restaurants:45,bars:30,
 pharmacies:10,groceries:10,health:0,banks:5,restrooms:5,luggage:10,hotels:0};
const INTEREST_SOURCES={famous:['attractions','museums','historic','culture','parks'],museums:['museums'],historic:['historic_lpc','historic'],
 parks:['parks'],shopping:['shopping'],culture:['culture','museums']};
const INTEREST_VISIT={famous:20,museums:45,historic:10,parks:20,shopping:25,culture:20};
const INTEREST_LABEL={famous:'Famous sight',museums:'Museum',historic:'Historic building',parks:'Park',shopping:'Shopping',culture:'Culture venue'};
const SERVICE_LABEL={pharmacies:'Pharmacy',groceries:'Grocery / supermarket',health:'Hospital / clinic',banks:'ATM / bank',restrooms:'Public restroom',luggage:'Luggage storage'};
const placesUrl=c=>`./data/places/${c}.json`;
async function loadPlaces(cat){
 if(!POI_CACHE[cat])POI_CACHE[cat]=streetwiseJson(placesUrl(cat)).then(d=>d.records.filter(r=>!['restaurants','cafes','bakeries','bars'].includes(cat)||foodListingEligible(r)).map(r=>({...r,cat}))).catch(e=>{delete POI_CACHE[cat];throw e;});
 return POI_CACHE[cat];
}
function foodListingEligible(r){
 if(['private','no','permit'].includes(r.access))return false;
 return !(r.src==='dohmh'&&!(r.pids||[]).some(p=>p.startsWith('osm:'))&&(!r.insp||r.insp.startsWith('1900-01-01'))&&!r.web);
}
let PLACE_INDEX=null;
async function placeIndex(){return PLACE_INDEX||(PLACE_INDEX=streetwiseJson('./data/places/index.json').catch(e=>{PLACE_INDEX=null;throw e;}));}
/** POI index record → unified Place (same model as places.js), with its provenance. */
function poiPlace(r){
 const src=r.src==='lpc'?'NYC Landmarks Preservation Commission':r.src==='nyc_restrooms'?'NYC Open Data Public Restrooms':r.src==='dohmh'?'NYC DOHMH Restaurant Inspection Results':r.source_url?r.src:'OpenStreetMap (Overpass snapshot)';
 return {id:r.id,name:r.name,address:r.addr||null,neighborhood:null,borough:r.boro||(r.search_only?null:'Manhattan'),routing_coverage:r.search_only?'search_only':'manhattan_network',category:poiCategoryLabel(r),lat:r.lat,lon:r.lon,source:src,
  sourceUrl:r.id.startsWith('osm:')?`https://www.openstreetmap.org/${r.id.slice(4)}`:r.source_url||r.report||null,website:r.web||null,menuUrl:r.menu||null,hours:r.hours||null,
  wikidata:r.wd||null,cat:r.cat,drink:r.drink||null,cuisine:r.cuisine||null,cid:r.cid||r.id,providerIds:r.pids||[r.id],quality:r.q||null,accessM:r.snap??null,
  operationalStatus:'Listed in source — not verified open today',landmark:r.src==='lpc'||Boolean(r.lpc),verification:'Listed by source (not verified by STROLLANE)',raw:r};
}
function poiCategoryLabel(r){
 const s=r.sub||'';const v=s.split('=')[1]||'';
 if(r.src==='lpc')return `NYC Landmark${r.type?' · '+r.type:''}`;
 return titleCase(v.replace(/_/g,' '))||titleCase(r.cat);
}
const kmBetween=(a,b)=>haversineKm(a,b);
function distToPathKm(p,path){
 if(path.length===1)return kmBetween(p,path[0]);
 let best=Infinity;const kx=84.4143,ky=111.0497;
 for(let i=1;i<path.length;i++){const a=path[i-1],b=path[i];const ax=a.lon*kx,ay=a.lat*ky,bx=b.lon*kx,by=b.lat*ky,px=p.lon*kx,py=p.lat*ky;
  const ux=bx-ax,uy=by-ay,l2=ux*ux+uy*uy,t=l2?Math.max(0,Math.min(1,((px-ax)*ux+(py-ay)*uy)/l2)):0;best=Math.min(best,Math.hypot(px-ax-t*ux,py-ay-t*uy));}
 return best;
}
/** Anchor path the walk is likely to follow (start → fixed stops → end), used only to pre-select nearby candidates;
    the planner then compares them on the real network. */
function anchorPath(){
 const pts=[getPlace('start')];
 for(const n of journey.named)pts.push(n.place);
 const end=journeyEndPlace();if(end)pts.push(end);
 return pts.filter(Boolean);
}
function journeyEndPlace(){
 if(journey.endMode==='fixed')return getPlace('end');
 if(journey.endMode==='hotel')return journey.hotel;
 if(journey.endMode==='round')return getPlace('start');
 return null;
}
/** Relevance 0..1 from source evidence only: notability (Wikidata sitelinks = Wikipedia editions), designation (LPC),
    item evidence (OSM drink / cuisine tags), data completeness. */
function relevance(r,{item=null,cuisine=null}={}){
 let s=.3;
 if(r.sl)s+=.55*Math.min(1,Math.log10(1+r.sl)/2.1);else if(r.wd)s+=.05;
 if(r.src==='lpc'||r.lpc)s+=.2;if(r.web)s+=.05;if(r.hours)s+=.05;
 if(item){const d=r.drink||{};if(d[item]==='yes')s+=.3;else if(['cappuccino','latte','espresso','flat white'].includes(item)&&(d.espresso==='yes'||d.coffee==='yes'||/coffee/.test(r.cuisine||'')))s+=.15;}
 if(cuisine&&new RegExp(`(^|;)${cuisine}(;|$)`,'i').test(r.cuisine||''))s+=.3;
 return Math.min(1,s);
}
/** Tool: candidate places of some categories near the walk, ranked by relevance minus straight-line distance to the path
    (pre-selection only; real walking cost is computed by the planner). */
async function discoverPlaces(cats,{item=null,cuisine=null,filter=null,limit=8,near=null,radiusKm=2.5}={}){
 const path=near?[near]:anchorPath();if(!path.length)return [];
 let lists;
 if(cats.every(c=>['restaurants','cafes','bakeries','bars'].includes(c))){
  try{lists=[await foodRecordsNearPath(cats,path,radiusKm,cuisine)];}
  catch(e){console.warn('Food search API unavailable; using the published local source snapshot:',e.message);}
 }
 if(!lists)lists=await Promise.all(cats.map(c=>loadPlaces(c).catch(()=>[])));
 // never "discover" the start, the end or a stop already chosen
 const fixedPts=[...anchorPath(),journey.hotel].filter(Boolean);
 const seen=new Set(),out=[];
 for(const r of lists.flat()){
  if(journey.removed.has(r.id)||filter&&!filter(r))continue;
  // one canonical place once, however many sources list it (cid from scripts/build_place_index.py entity resolution)
  const key=normName(r.name);if(seen.has(r.cid||r.id))continue;seen.add(r.cid||r.id);
  const d=distToPathKm(r,path);if(d>radiusKm)continue;
  if(fixedPts.some(f=>kmBetween(f,r)<.15||normName(f.name)===key))continue;
  const rel=relevance(r,{item,cuisine});out.push({r,rel,d,score:rel-.3*d});
 }
 out.sort((a,b)=>b.score-a.score);
 return out.slice(0,limit).map(x=>({...poiPlace(x.r),score:Math.round(x.rel*100)/100,straightKm:Math.round(x.d*100)/100}));
}
function canonicalFoodRecord(p){
 const food=p.restaurant||{},inspection=food.inspection||{};
 return {id:p.index_id||p.place_id,cid:p.place_id,name:p.name,cat:p.category,lat:p.coordinates.lat,lon:p.coordinates.lon,addr:p.address,
  src:(p.index_id||'').startsWith('dohmh:')?'dohmh':'osm',web:p.official_website,menu:food.menu_url,hours:p.opening_hours,
  cuisine:food.cuisine||food.cuisine_dohmh,drink:food.drink_tags_osm, insp:inspection.last_inspection,dohmh:inspection.permit,
  search_only:p.routing_coverage==='search_only',boro:p.borough};
}
async function foodRecordsNearPath(cats,path,radiusKm,cuisine){
 // Nearby discovery is a bounded shortlist, not an assertion that every NYC
 // business was checked. Read at most 50 source records per sampled anchor.
 const anchors=[path[0]];
 for(let i=1;i<path.length;i++){
  const a=path[i-1],b=path[i],steps=Math.max(1,Math.ceil(kmBetween(a,b)));
  for(let j=1;j<=steps;j++)anchors.push({lat:a.lat+(b.lat-a.lat)*j/steps,lon:a.lon+(b.lon-a.lon)*j/steps});
 }
 if(anchors.length>12)throw new Error('Long search area requires the full published snapshot');
 const found=new Map();
 for(let i=0;i<anchors.length;i+=3){
  const responses=await Promise.all(anchors.slice(i,i+3).map(p=>streetwiseJson('/api/places/search?'+new URLSearchParams({lat:p.lat,lon:p.lon,categories:cats.join(','),radius_m:Math.min(3000,Math.ceil(radiusKm*1000+500)),limit:50,...(cuisine?{cuisine}:{})}),{signal:AbortSignal.timeout(12000)})));
  for(const d of responses){if(!Array.isArray(d.results))throw new Error('Invalid food search response');for(const p of d.results)found.set(p.place_id,canonicalFoodRecord(p));}
 }
 return [...found.values()];
}
async function findNamedPlace(name){
 // Index first (real records with provenance), then the five-borough search providers.
 const n=normName(name);
 for(const c of ['attractions','museums','historic','historic_lpc','culture','parks','hotels','shopping']){
  const hit=(await loadPlaces(c).catch(()=>[])).filter(r=>normName(r.name)===n||normName(r.name).startsWith(n+' ')).sort((a,b)=>Boolean(b.wd)-Boolean(a.wd))[0];
  if(hit)return poiPlace(hit);
 }
 try{const {places}=await searchPlaces(name,{near:{lat:40.758,lon:-73.985},limit:3});return places.find(p=>!p.pending)||null;}catch(e){return null;}
}

/* ---------- language: local fallback parser (labelled), same output shape as the LLM's `journey` ---------- */
const ZH_PLACES={'洛克菲勒中心':'Rockefeller Center','时代广场':'Times Square','中央公园':'Central Park','帝国大厦':'Empire State Building','大都会博物馆':'The Metropolitan Museum of Art',
 '大都会艺术博物馆':'The Metropolitan Museum of Art','布鲁克林大桥':'Brooklyn Bridge','华尔街':'Wall Street','中央车站':'Grand Central Terminal','现代艺术博物馆':'Museum of Modern Art',
 '高线公园':'The High Line','联合广场':'Union Square','华盛顿广场':'Washington Square Park','911纪念馆':'National September 11 Memorial & Museum','炮台公园':'The Battery',
 '古根海姆':'Solomon R. Guggenheim Museum','自然历史博物馆':'American Museum of Natural History','熨斗大厦':'Flatiron Building','克莱斯勒大厦':'Chrysler Building',
 '圣帕特里克大教堂':"St. Patrick's Cathedral",'纽约公共图书馆':'New York Public Library','哥伦比亚大学':'Columbia University','切尔西市场':'Chelsea Market','布莱恩特公园':'Bryant Park',
 '无线电城':'Radio City Music Hall','卡内基音乐厅':'Carnegie Hall','林肯中心':'Lincoln Center','唐人街':'Chinatown','小意大利':'Little Italy'};
const FOOD_RULES=[
 [/cappuccino|卡布奇诺/i,{category:'cafes',item:'cappuccino'}],[/latte|拿铁/i,{category:'cafes',item:'latte'}],[/espresso|浓缩咖啡/i,{category:'cafes',item:'espresso'}],
 [/flat white|澳白|馥芮白/i,{category:'cafes',item:'flat white'}],[/matcha|抹茶/i,{category:'cafes',item:'matcha'}],[/coffee|咖啡/i,{category:'cafes',item:'coffee'}],[/café|cafe/i,{category:'cafes',item:null}],
 [/cheesecake|芝士蛋糕/i,{category:'bakeries',item:'cheesecake'}],[/bagel|贝果/i,{category:'bakeries',item:'bagel'}],[/croissant|可颂|羊角包/i,{category:'bakeries',item:'croissant'}],
 [/dessert|甜品|甜点|ice cream|冰淇淋/i,{category:'bakeries',item:null}],[/bakery|面包/i,{category:'bakeries',item:null}],
 [/tiramisu|提拉米苏/i,{category:'restaurants',item:'tiramisu'}],[/pizza|披萨|比萨/i,{category:'restaurants',item:'pizza',cuisine:'pizza'}],[/italian|意大利菜|意餐/i,{category:'restaurants',cuisine:'italian'}],[/chinese food|中餐|中国菜/i,{category:'restaurants',cuisine:'chinese'}],
 [/sushi|寿司|japanese|日料|日本菜/i,{category:'restaurants',cuisine:'japanese'}],[/ramen|拉面/i,{category:'restaurants',cuisine:'ramen'}],[/mexican|墨西哥/i,{category:'restaurants',cuisine:'mexican'}],
 [/brunch|早午餐/i,{category:'restaurants',cuisine:'brunch'}],[/\brestaurant|eat\b|dinner|lunch|吃饭|晚餐|午餐|餐厅/i,{category:'restaurants'}],[/\bbar\b|cocktail|beer|酒吧|啤酒|鸡尾酒/i,{category:'bars'}]];
const SERVICE_RULES=[[/pharmac|drugstore|药店|药房/i,'pharmacies'],[/restroom|toilet|bathroom|washroom|洗手间|厕所|卫生间/i,'restrooms'],[/\batm\b|取钱|取款/i,'banks'],[/\bbank\b|银行/i,'banks'],
 [/supermarket|grocery|convenience store|超市|便利店/i,'groceries'],[/hospital|clinic|urgent care|医院|诊所/i,'health'],[/luggage|baggage|存行李|寄存|行李/i,'luggage']];
const INTEREST_RULES=[[/famous|landmark|sights?\b|must.see|attraction|tourist|著名|景点|地标|必去/i,'famous'],[/museum|galler|art\b|博物馆|美术馆|艺术馆|画廊/i,'museums'],
 [/historic|history|architecture|heritage|old building|历史|建筑|古迹/i,'historic'],[/\bparks?\b|garden|公园|花园/i,'parks'],[/shopping|shops|mall|购物|商场|逛街/i,'shopping'],[/theat(er|re)|broadway|library|剧院|图书馆|百老汇/i,'culture']];
const CN_NUM={'一':1,'两':2,'二':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9,'十':10,'半':.5};
const EN_NUM={one:1,an:1,a:1,two:2,three:3,four:4,five:5,six:6,half:.5};
function parseHours(q){
 let m=q.match(/(\d+(?:\.\d+)?)\s*(?:hours?|hrs?|h\b|小时)/i);if(m)return Math.round(+m[1]*60)+(/(and a half|个半|半)/.test(q.slice(m.index,m.index+m[0].length+10))&&!m[1].includes('.')?30:0);
 m=q.match(/([一两二三四五六七八九十])\s*个?\s*(半)?\s*小时/);if(m)return Math.round((CN_NUM[m[1]]+(m[2]?.5:0))*60);
 m=q.match(/\b(one|an|a|two|three|four|five|six)\s+(?:and a half\s+)?hours?(\s+and a half)?/i);if(m)return Math.round((EN_NUM[m[1].toLowerCase()]+(/and a half/i.test(m[0])?.5:0))*60);
 m=q.match(/(\d{2,3})\s*(?:minutes?|mins?|分钟)/i);if(m)return +m[1];
 return null;
}
function namedHotelAnchor(q){return (localJourney.names||[]).find(n=>q.toLowerCase().includes('near '+n.toLowerCase()))||null;}
function localJourney(q){
 const j={interests:[],named_stops:[],food:[],services:[],service_scope:null,hotel:null,origin:null,destination:null,end_mode:null,walking_minutes:null,outing_minutes:null,distance_km:null,more:{},remove:[]};
 const seqWords=/(then|after that|afterwards|before|first|finally|先|再|然后|接着|之后|最后)/i.test(q);
 for(const [re,v] of INTEREST_RULES)if(re.test(q)&&!j.interests.includes(v))j.interests.push(v);
 // "interesting architecture" is a walking preference (the Architecture dimension), not a request to visit places:
 // these interests start discovery only with a visit cue. Museums and famous sights are places by definition.
 if(!/(visit|see |see$|show me|explore|tour|sightsee|first time|discover|go to|stop at|逛|看看|看一些|参观|游览|第一次|去看|去逛)/i.test(q))j.interests=j.interests.filter(i=>['famous','museums'].includes(i));
 // "one more museum" / "再加一个博物馆" adds to what is already planned
 const more=q.match(/(?:another|one more|add (?:a|one)|再加(?:一个|一家|个)?|再来一个|多加一个)\s*([^,，。.]{0,14})/i);
 if(more){const what=more[1];for(const [re,v] of INTEREST_RULES)if(re.test(what)){j.more[v]=(j.more[v]||0)+1;j.interests=j.interests.filter(x=>x!==v);}}
 for(const [re,v] of FOOD_RULES){if(re.test(q)&&!j.food.some(f=>f.category===v.category&&(f.item||f.cuisine))){j.food.push({category:v.category,item:v.item||null,cuisine:v.cuisine||null,required:true});}}
 // Preserve explicit cuisine alongside a requested dish; a cuisine tag alone is not menu evidence.
 for(const [re,v] of FOOD_RULES)if(v.cuisine&&re.test(q))for(const f of j.food)if(f.category===v.category&&!f.cuisine)f.cuisine=v.cuisine;
 j.requirements={};j.counts={};
 const searchAnchor=namedHotelAnchor(q);if(searchAnchor)j.requirements.search_anchor=searchAnchor;
 if(/highly rated|good reviews|well.reviewed|good (?:cafe|café|coffee|bakery|restaurant)|高评分|好评/i.test(q))j.requirements.ratings_required=true;
 const countMatch=q.match(/\b(one|two|three|four|five|[1-9]) (landmarks?|attractions?|museums?)\b/i);
 if(countMatch){const key=/museum/i.test(countMatch[2])?'museums':'famous';j.counts[key]=EN_NUM[countMatch[1].toLowerCase()]||+countMatch[1];if(!j.interests.includes(key))j.interests.push(key);}
 const nightly=q.match(/\$([0-9]+(?:\.[0-9]{1,2})?)\s*(?:per night|a night|\/night)/i);
 if(nightly)j.requirements.hotel_budget_per_night_usd=+nightly[1];
 const beds=q.match(/\b(one|two|three|[1-6]) beds?\b/i);if(beds)j.requirements.beds=EN_NUM[beds[1].toLowerCase()]||+beds[1];
 if(j.requirements.hotel_budget_per_night_usd!=null||j.requirements.beds){const near=namedHotelAnchor(q);if(near)j.origin=near;}
 // keep only the most specific coffee request
 if(j.food.some(f=>f.category==='cafes'&&f.item))j.food=j.food.filter(f=>!(f.category==='cafes'&&!f.item));
 if(j.food.filter(f=>f.category==='restaurants').length>1)j.food=j.food.filter(f=>!(f.category==='restaurants'&&!f.cuisine));
 for(const [re,v] of SERVICE_RULES)if(re.test(q)&&!j.services.includes(v))j.services.push(v);
 j.service_scope=/near (my |the )?hotel|酒店附近|酒店旁/i.test(q)?'near_hotel':/along|on the way|on my (walk|route)|途中|路上|顺路|沿途/i.test(q)?'along_route':j.services.length?'near_start':null;
 const serviceAsStop=/(先去|first go|go to|stop at|drop (off )?(my )?(luggage|bags)|存行李|need to|must)/i.test(q);
 j.service_stop=serviceAsStop;
 // named places: Chinese aliases and English names found in the discovery index
 const named=[];
 for(const [zh,en] of Object.entries(ZH_PLACES)){const i=q.indexOf(zh);if(i>=0)named.push({name:en,at:i});}
 for(const n of (localJourney.names||[])){const i=q.toLowerCase().indexOf(n.toLowerCase());if(i>=0&&!named.some(x=>normName(x.name)===normName(n)))named.push({name:n,at:i});}
 named.sort((a,b)=>a.at-b.at);
 const hotelM=q.match(/(?:staying at|stay at|my hotel is|我住在|住在|我的酒店是)\s*(?:the |a |an )?([^,，。.;]+?)(?:\s+(?:near|by|in|附近)\s+([^,，。.;]+))?(?=[,，。.;]|$)/i);
 if(hotelM)j.hotel={name:hotelM[1].trim(),near:hotelM[2]?.trim()||null,is_mine:true};
 else if(/find (a |me a )?hotels?|hotels? near|找(个|家)?酒店|推荐酒店/i.test(q)){const near=q.match(/hotels? near ([^,，。.;]+)|(?:在)?([^,，。.;]{2,12})附近的?酒店/i);j.hotel={name:null,near:(near?.[1]||near?.[2]||'').trim()||null,is_mine:false};}
 const endHotel=/back to (my |the )?hotel|return to (my |the )?hotel|回(到)?(我的)?酒店|返回酒店/i.test(q),endStart=/back to (the )?start|round.?trip|loop|回到起点|回到出发/i.test(q);
 j.end_mode=endHotel?'hotel':endStart?'round':null;
 if(/from (my |the )?hotel|start (at|from) (my |the )?hotel|从(我的)?酒店出发/i.test(q))j.origin='hotel';
 else if(/from (here|my location|where i am)|从这里|从我(现在)?的位置/i.test(q))j.origin='gps';
 const endAt=q.match(/(?:end (?:at|in)|finish (?:at|in)|最后(?:到|去|在))\s*([^,，。.;]+)/i);
 for(const n of named){
  const before=q.slice(Math.max(0,n.at-14),n.at);
  if(endAt&&endAt[1].includes(n.name.split(' ')[0])||/最后(到|去|在)\s*$|end (at|in)\s*$|finish (at|in)\s*$/i.test(before)){j.destination=n.name;j.end_mode='fixed';continue;}
  if(/(from|start (at|from)|从)\s*$/i.test(before)){j.origin=n.name;continue;}
  j.named_stops.push({name:n.name,required:true,order:seqWords?j.named_stops.length+1:null});
 }
 const outing=/(i have|i've got|we have|total|altogether|我有|总共|一共|有)\s*.{0,10}?(hours?|hrs?|minutes?|小时|分钟)/i.test(q)||/(two|three|two and a half)\s+hours to/i.test(q);
 const mins=parseHours(q);
 if(mins!=null){if(outing||/hour|小时/.test(q))j.outing_minutes=mins;}
 // "extend to 180 minutes" / "时间可以延长到 180 分钟" / "延长到三个小时": a new total outing time
 if(/extend|longer|延长|增加|放宽/i.test(q)){const e=q.match(/(\d{2,3}(?:\.\d)?)\s*(hours?|hrs?|小时|minutes?|mins?|分钟)?/i);
  if(e)j.outing_minutes=/hour|hr|小时/i.test(e[2]||'')?Math.round(+e[1]*60):+e[1];else{const h=parseHours(q);if(h)j.outing_minutes=h;}}
 const km=q.match(/(\d+(?:\.\d+)?)\s*(km|kilomet(?:er|re)s?|公里|千米)/i),mi=q.match(/(\d+(?:\.\d+)?)\s*(miles?|mi\b|英里)/i);
 j.distance_km=km?+km[1]:mi?Math.round(+mi[1]*KM_PER_MILE*10)/10:null;
 if(/less walking|walk less|少走|少走路/i.test(q))j.less_walking=true;
 const rm=q.match(/(?:remove|skip|drop|去掉|删掉|不要去|不去)\s*([^,，。.;]+)/i);if(rm)j.remove.push(rm[1].trim());
 return j;
}
async function warmNameIndex(){
 if(localJourney.names)return;
 const lists=await Promise.all(['attractions','museums','historic','culture','parks'].map(c=>loadPlaces(c).catch(()=>[])));
 // notable names only (Wikidata), long enough not to match common words
 localJourney.names=[...new Set(lists.flat().filter(r=>r.wd&&r.name.length>=8).map(r=>r.name))].concat(Object.values(PLACES).map(p=>p.name));
}
function journeyIntentPresent(j){return Boolean(j&&(j.interests.length||j.named_stops.length||j.food.length||j.services.length||j.hotel||j.end_mode||j.origin==='hotel'||Object.keys(j.more||{}).length||j.remove.length||(j.outing_minutes!=null)));}

/* ---------- state updates (multi-turn: merge, never wipe what is already settled) ---------- */
async function applyJourney(j){
 const changes=[];if(!j)return changes;
 journey.businessOnly=false;
 if(j.counts)for(const [k,v] of Object.entries(j.counts))if(v!=null)journey.counts[k]=v;
 if(j.requirements){for(const [k,v] of Object.entries(j.requirements))if(v!=null)journey.requirements[k]=v;
  if(j.requirements.ratings_required)changes.push('ratings evidence required; no unverified review score will be substituted');}
 if(j.requirements&&(j.requirements.hotel_budget_per_night_usd!=null||j.requirements.beds!=null)&&!j.hotel?.is_mine){
  const near=j.requirements.search_anchor?await findNamedPlace(j.requirements.search_anchor):j.origin&&!['gps','hotel'].includes(j.origin)?await findNamedPlace(j.origin):getPlace('start');journey.businessOnly=true;
  if(near){const q=new URLSearchParams({lat:near.lat,lon:near.lon,...Object.fromEntries(Object.entries({checkin:j.requirements.checkin,checkout:j.requirements.checkout,guests:j.requirements.guests,beds:j.requirements.beds,max_price:j.requirements.hotel_budget_per_night_usd}).filter(([,v])=>v!=null))});
   try{const d=await streetwiseJson('/api/hotels/search?'+q);
    showFoundPlaces('Hotel listings — room criteria unverified',d.candidates.map(p=>({id:p.index_id,name:p.name,category:p.category,lat:p.coordinates.lat,lon:p.coordinates.lon,address:p.address,source:p.data_sources.join(' + ')})),{note:d.reason});
    appendChat('assistant',d.reason+' No hotel is claimed to meet your bed or nightly-price requirements.');
   }catch(e){appendChat('assistant','Hotel search unavailable: '+e.message);}}
  if(!near)appendChat('assistant','Hotel search area could not be resolved. Choose a real search location; no hotel is claimed to match.');
  return ['hotel requirements retained; availability and price not verified'];
 }
 journey.active=journey.active||journeyIntentPresent(j);
 for(const i of j.interests)if(!journey.interests.includes(i)){journey.interests.push(i);changes.push(`interest: ${INTEREST_LABEL[i]}`);}
 for(const [k,v] of Object.entries(j.more||{})){if(!journey.interests.includes(k))journey.interests.push(k);journey.extra[k]=(journey.extra[k]||0)+v;changes.push(`+${v} ${INTEREST_LABEL[k]||k}`);}
 for(const f of j.food){const same=journey.food.findIndex(x=>x.category===f.category);if(same>=0)journey.food[same]=f;else journey.food.push(f);
  changes.push(f.item?`${f.item} (${f.category})`:f.cuisine?`${f.cuisine} ${f.category}`:f.category);}
 for(const s of j.services){if(!journey.services.some(x=>x.type===s)){journey.services.push({type:s,scope:j.service_scope||'near_start',addAsStop:Boolean(j.service_stop)});changes.push(SERVICE_LABEL[s]+(j.service_stop?' (stop)':''));}}
 for(const n of j.named_stops){
  if(journey.named.some(x=>normName(x.place.name)===normName(n.name)))continue;
  const p=await findNamedPlace(n.name);
  if(!p){if(n.required!==false&&!journey.unresolved.includes(n.name))journey.unresolved.push(n.name);changes.push(`“${n.name}” not found in NYC place data`);continue;}
  journey.unresolved=journey.unresolved.filter(name=>normName(name)!==normName(n.name));
  journey.named.push({place:p,required:n.required!==false,order:n.order,visitMin:VISIT_MIN[p.cat]??20,visitEstimated:true});changes.push(`stop: ${p.name}`);
 }
 if(j.origin==='hotel'){if(journey.hotel){setJourneyPlace('start',journey.hotel);changes.push('start: my hotel');}else changes.push('start: my hotel (set your hotel first)');}
 else if(j.origin==='gps'){if(state.gps){state.start='gps';$('searchStart').value='My current location';changes.push('start: my location');}else changes.push('start: GPS (allow location first)');}
 else if(j.origin){const p=await findNamedPlace(j.origin);if(p){setJourneyPlace('start',p);changes.push(`start: ${p.name}`);}}
 if(j.destination){const p=await findNamedPlace(j.destination);if(p){setJourneyPlace('end',p);setEndMode('fixed');changes.push(`end: ${p.name}`);}}
 if(j.end_mode&&j.end_mode!=='fixed'){setEndMode(j.end_mode);changes.push({hotel:'end: back to my hotel',round:'end: back to start',open:'flexible end'}[j.end_mode]);}
 // discovery never drops a destination: with one set, discovered stops go along the way
 else if(journey.active&&!j.destination&&journey.endMode==='fixed'&&(j.interests.length||Object.keys(j.more||{}).length)&&!getPlace('end')){setEndMode('open');changes.push('flexible end (discover for me)');}
 if(j.outing_minutes!=null){state.outingMin=j.outing_minutes;$('outingMin').value=j.outing_minutes;changes.push(`outing ${j.outing_minutes} min (walking + visits)`);
  if(j.outing_minutes>state.budget){setBudget(j.outing_minutes);}}
 if(j.walking_minutes!=null&&setBudget(Math.round(j.walking_minutes)))changes.push(`max ${state.budget} min walking`);
 if(j.distance_km!=null&&setDistanceLimit(j.distance_km))changes.push(`max ${j.distance_km} km`);
 if(j.less_walking&&journey.plan){const km=Math.max(1,Math.round(journey.plan.totals.walk_m/1000*.8*10)/10);setDistanceLimit(km);changes.push(`less walking: max ${km} km`);}
 for(const name of j.remove||[]){const n=normName(name);const hit=journey.named.find(x=>normName(x.place.name).includes(n))||journey.plan?.stops.find(s=>normName(s.name).includes(n));
  journey.unresolved=journey.unresolved.filter(value=>!normName(value).includes(n));
  if(hit){const id=hit.place?.id||hit.id;journey.removed.add(id);journey.named=journey.named.filter(x=>x.place.id!==id);changes.push(`removed ${hit.place?.name||hit.name}`);}}
 if(j.hotel)changes.push(...await handleHotelIntent(j.hotel));
 renderJourneyPanel();
 return changes.filter(Boolean);
}
function setJourneyPlace(kind,p){
 state[kind==='start'?'customStart':'customEnd']=p;state[kind]='custom';
 placeInputs[kind]?.set(p);$(kind==='start'?'startSelect':'endSelect').value='custom';
 if(kind==='end')journey.userSetDestination=true;
 syncMapData();
}
function setEndMode(mode){
 journey.endMode=mode;document.querySelectorAll('[data-end-mode]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.endMode===mode)));
 $('endFixedBox').classList.toggle('hidden',mode!=='fixed');
 if(mode==='hotel'&&!journey.hotel)toast('Set My Hotel first (search it under My hotel).');
 syncMapData();
}

/* ---------- hotels ---------- */
async function handleHotelIntent(h){
 const out=[];
 let near=null;if(h.near){near=await findNamedPlace(h.near);}
 if(h.name){
  const q=normName(h.name);
  const idx=(await loadPlaces('hotels').catch(()=>[])).filter(r=>normName(r.name).includes(q)||normName(r.brand||'').includes(q));
  const ranked=idx.map(r=>({r,d:near?kmBetween(r,near):0})).sort((a,b)=>a.d-b.d).slice(0,5).map(x=>poiPlace(x.r));
  if(h.is_mine){
   if(ranked.length===1){setMyHotel(ranked[0]);out.push(`my hotel: ${ranked[0].name}`);}
   else if(ranked.length>1){askChoice(`Which hotel are you staying at? ${ranked.length} real matches${near?` near ${near.name}`:''}:`,ranked,p=>{setMyHotel(p);appendChat('assistant',`My hotel set to ${p.name}. It will be used as start / return point when you ask.`);});out.push('hotel: please confirm which one');}
   else out.push(`no hotel named “${h.name}” in the Manhattan data — search it under My hotel`);
  }else{showFoundPlaces(`Hotels matching “${h.name}”`,ranked);out.push(`${ranked.length} hotels found (not set as yours)`);}
 }else{
  const res=await discoverPlaces(['hotels'],{near:near||getPlace('start'),limit:8,radiusKm:1.5});
  showFoundPlaces(`Hotels near ${near?.name||getPlace('start')?.name||'the start'}`,res,{hotel:true});out.push(`${res.length} hotels near ${near?.name||'the start'} (search only, no live availability or prices)`);
 }
 return out;
}
function setMyHotel(p){
 journey.hotel=p?{...p,category:p.category||'Hotel'}:null;
 $('hotelName').textContent=p?p.name:'not set';hotelInput?.set(p);
 try{if(journey.rememberHotel&&p)localStorage.setItem('sw.myHotel',JSON.stringify({id:p.id,name:p.name,lat:p.lat,lon:p.lon,address:p.address,source:p.source}));else localStorage.removeItem('sw.myHotel');}catch(e){}
 renderJourneyPanel();syncMapData();
}

/* ---------- building the planner request ---------- */
async function itineraryRequest(){
 if(journey.unresolved.length)throw new Error('Required places could not be resolved from source data: '+journey.unresolved.join(', ')+'. Choose a real place or explicitly remove the requirement.');
 const start=getPlace('start');if(!start)throw new Error('Choose a starting point (search, GPS, My hotel or the map).');
 const end=journey.endMode==='fixed'?getPlace('end'):journey.endMode==='hotel'?journey.hotel:null;
 if(journey.endMode==='fixed'&&!end)throw new Error('Choose a destination, or pick “Discover for me”.');
 if(journey.endMode==='hotel'&&!end)throw new Error('Set My Hotel to return to it.');
 const searchAnchor=journey.requirements.search_anchor?await findNamedPlace(journey.requirements.search_anchor):null;
 if(journey.requirements.search_anchor&&!searchAnchor)throw new Error('Search area could not be resolved from the source index; choose it explicitly.');
 const ordered=journey.named.some(n=>n.order!=null);
 // a named stop that is the start or the end (same name, or within 250 m under another record) is not a second visit
 const sameAs=(p,q)=>q&&(kmBetween(p,q)<.05||(kmBetween(p,q)<.25&&(normName(p.name).includes(normName(q.name))||normName(q.name).includes(normName(p.name)))));
 const stops=journey.named.filter(n=>!journey.removed.has(n.place.id)&&!sameAs(n.place,start)&&!sameAs(n.place,end)).map(n=>({...pick(n.place),required:n.required,order:n.order,visit_min:n.visitMin,visit_estimated:n.visitEstimated}));
 const slots=[],poolCands=[];let order=stops.length;
 // Interests, food items and service candidates are independent lookups (no iteration reads another's result),
 // so they are fetched together instead of one-at-a-time: with live menu verification able to take several
 // seconds per food item (server budget in routing/recommend.py), awaiting them in sequence was the main reason
 // planning a walk with more than one requirement felt slow. Fetching runs in parallel; applying the results
 // (throwing on a missing requirement, building slots, assigning `order`) stays in the original, deterministic
 // array order exactly as before — only the waiting is concurrent, not the outcome.
 if(journey.requirements.restaurant_budget_usd!=null&&journey.food.some(f=>!f.item))throw new Error('Restaurant budget cannot be verified without a specific item and directly sourced price.');
 const [interestResults,foodResults]=await Promise.all([
  Promise.all(journey.interests.map(i=>discoverPlaces(INTEREST_SOURCES[i],{near:searchAnchor,limit:10,filter:i==='famous'?(r=>(r.sl||0)>=8):null}))),
  Promise.all(journey.food.map(f=>{
   const cats=f.item==='cheesecake'?['bakeries','restaurants']:/^bagels?$/i.test(f.item||'')?['bakeries','cafes','restaurants']:[f.category];
   const filt=f.cuisine?(r=>new RegExp(`(^|;)${f.cuisine}(;|$)`,'i').test(r.cuisine||'')):f.category==='cafes'&&f.item?(r=>r.cat==='cafes'):null;
   const fixed=journey.replaced['food:'+f.category+':'+(f.item||f.cuisine||'')];
   if(fixed)return Promise.resolve(null); // no lookup needed; applied from journey.replaced below
   // a requested item: server-side recommendation (menu evidence first, closed / unreachable excluded); local discovery otherwise or as fallback
   return (f.item||journey.requirements.ratings_required)?recommendFood(f,cats,start,end).then(rec=>rec||[]):discoverPlaces(cats,{item:f.item,cuisine:f.cuisine,filter:filt,limit:6,radiusKm:1.2,near:searchAnchor});
  })),
 ]);
 journey.interests.forEach((i,idx)=>{
  const cands=interestResults[idx];
  const fixed=journey.replaced['interest:'+i];
  if(fixed)stops.push({...pick(fixed),required:true,order:null,visit_min:VISIT_MIN[fixed.cat]??30});
  else if(!cands.length)throw new Error(`No verified discovery candidate for ${INTEREST_LABEL[i]}; this required interest is not fulfilled.`);
  else if(cands.length){const count=journey.counts[i]||1;if(cands.length<count)throw new Error(`Only ${cands.length} distinct candidates for ${count} required ${INTEREST_LABEL[i]}.`);
   for(let k=0;k<count;k++)slots.push({slot_id:'interest:'+i+(count>1?':'+(k+1):''),label:INTEREST_LABEL[i]+(count>1?' '+(k+1):''),required:true,visit_min:INTEREST_VISIT[i],candidates:cands.slice(0,Math.max(4,count)).map(slotCand)});}
  for(const c of cands.slice(4))poolCands.push({...slotCand(c),visit_min:INTEREST_VISIT[i],group:i});
 });
 journey.food.forEach((f,idx)=>{
  const id='food:'+f.category+':'+(f.item||f.cuisine||'');const fixed=journey.replaced[id];
  const cands=foodResults[idx]||[];
  if(fixed)stops.push({...pick(fixed),required:true,required_item:f.item||null,order:null,visit_min:VISIT_MIN[fixed.cat]??20});
  else if(!cands.length&&f.required!==false)throw new Error(`Cannot verify the required ${foodLabel(f)}. No matching place with sufficient evidence was found; the requirement has not been removed.`);
  else if(cands.length)slots.push({slot_id:id,label:foodLabel(f),required_item:f.item||null,required:f.required!==false,visit_min:VISIT_MIN[f.category]??20,candidates:cands.map(slotCand),order:ordered?++order:null});
 });
 // One source-verified venue may satisfy several dishes; explicit landmark counts still require distinct places.
 for(let i=0;i<slots.length;i++){
  const first=slots[i];if(!first.slot_id.startsWith('food:')||!first.required||!first.required_item)continue;
  for(let j=i+1;j<slots.length;j++){
   const next=slots[j];if(!next.slot_id.startsWith('food:')||!next.required||!next.required_item)continue;
   const shared=first.candidates.filter(c=>next.candidates.some(p=>p.id===c.id));if(!shared.length)continue;
   first.required_items=[...(first.required_items||[first.required_item]),next.required_item];first.label+=' + '+next.label;
   first.candidates=shared;first.visit_min=Math.max(first.visit_min,next.visit_min);slots.splice(j--,1);
  }
 }
 const neededServices=journey.services.filter(s=>s.addAsStop);
 const serviceResults=await Promise.all(neededServices.map(s=>discoverPlaces([s.type],{limit:6,radiusKm:1.5})));
 neededServices.forEach((s,idx)=>{
  const cands=serviceResults[idx],id='service:'+s.type;
  if(!cands.length)throw new Error(`No candidate for required ${SERVICE_LABEL[s.type]}.`);
  slots.push({slot_id:id,label:SERVICE_LABEL[s.type],required:true,visit_min:VISIT_MIN[s.type]??10,candidates:cands.map(slotCand),order:s.type==='luggage'?0:null});
 });
 const outing=state.outingMin;
 if(journey.requirements.ticket_budget_usd!=null||journey.requirements.total_budget_usd!=null)throw new Error('Ticket/total monetary budget cannot be verified: admission prices and all required costs are not connected. Walking time remains separate.');
 // extra discoveries scale with the time available (walking budget, or the total outing when set)
 const base=outing||state.budget,maxPool=Math.max(0,Object.values(journey.extra).reduce((a,b)=>a+b,0)+(journey.interests.length&&!Object.keys(journey.counts).length?Math.max(1,Math.min(4,Math.round((base-30)/40))):0));
 return {departure:new Date().toISOString(),origin:pick(start),end:{mode:journey.endMode,place:end?pick(end):null},stops,slots,pool:{label:'Discovered places',max_stops:maxPool,candidates:poolCands.slice(0,16)},
  constraints:{max_minutes:state.budget,max_km:state.maxKm,max_outing_minutes:outing,avoid_stairs:planner.constraints.avoidStairs,require_open:journey.requirements.must_be_open===true},
  preferences:buildRouteRequest(start,end||start).preferences,theme:journeyTheme()};
}
const pick=p=>({id:p.id,name:p.name,lat:p.lat,lon:p.lon,category:p.category||null,address:p.address||null,source:p.source||null,hours:p.hours||p.raw?.hours||null});
const slotCand=c=>({...pick(c),score:c.score,evidence:typeof c.evidence==='string'?c.evidence:candidateEvidence(c)});
function foodLabel(f){return f.item?`${titleCase(f.item)} (${f.category==='cafes'?'café':f.category.replace(/s$/,'')})`:f.cuisine?`${titleCase(f.cuisine)} restaurant`:{cafes:'Café',restaurants:'Restaurant',bakeries:'Bakery / dessert',bars:'Bar'}[f.category];}
function candidateEvidence(c){
 const e=[];if(c.raw?.sl)e.push(`Wikipedia in ${c.raw.sl} editions`);else if(c.wikidata)e.push('Wikidata-listed');if(c.raw?.src==='lpc'||c.raw?.lpc)e.push('NYC designated landmark');if(c.raw?.snap>80)e.push(`entrance approx. ${Math.round(c.raw.snap)} m from mapped point`);if(c.drink?.espresso==='yes')e.push('OSM tag: serves espresso');if(c.drink?.coffee==='yes')e.push('OSM tag: serves coffee');
 if(c.cuisine)e.push('cuisine: '+c.cuisine.replace(/;/g,', '));if(c.hours)e.push('hours listed');return e.join(' · ')||null;
}
function journeyTheme(){
 const parts=[...journey.interests.map(i=>INTEREST_LABEL[i]+'s'),...journey.food.map(foodLabel),...journey.named.map(n=>n.place.name)];
 return parts.length?`City walk: ${parts.slice(0,4).join(' · ')}`:'Your City Walk';
}
function journeyMode(){return journey.active||journey.named.length>0||journey.endMode!=='fixed';}

/* ---------- planning ---------- */
async function planJourney(isFollowUp=false){
 if(state.routingBusy)return;
 if(planner.constraints.stepFree){resetRoutes();$('rankingStatus').textContent='Step-free access cannot be verified with the current curb-ramp and elevator data. No route is recommended.';appendChat('assistant',$('rankingStatus').textContent);return;}
 const run=++planner.runId;state.routingBusy=true;$('generateRoutes').disabled=true;$('chatSend').disabled=true;$('ctaLabel').textContent='Finding places & routing…';
 try{
  var kept=isFollowUp?snapshotRoutes():null;
  resetRoutes(true);renderRouteCards();
  const req=await itineraryRequest();
  const res=await streetwiseFetch('/api/itinerary',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(req),signal:AbortSignal.timeout(45000)});
  const json=await res.json().catch(()=>({}));if(run!==planner.runId)return;
  if(!res.ok)throw new Error(json.error||`Itinerary service HTTP ${res.status}`);
  journey.plan=json.itinerary;journey.request=req;
  validateIndependentResponse(req.preferences,json);applyRouteResponse(json);
  planner.lastExplanation=itinerarySummaryText(json.itinerary);
  $('rankingStatus').textContent=planner.lastExplanation;
  renderRouteCards();syncMapData();updateProfile();updateWhyRoute();renderRouteEdges();renderPOIs();renderCityWalk();renderJourneyPanel();
  appendChat('assistant',planner.lastExplanation);
  if(state.mapReady){const bx=routeBounds(state.routes,80);if(bx)state.map.fitBounds([[bx[0],bx[1]],[bx[2],bx[3]]],{padding:routeFitPadding(65),maxZoom:15.5,duration:700});}
  autoVerifyMenus();cacheStopPlaces();
 }catch(err){
  if(run!==planner.runId)return;resetRoutes(true);renderRouteCards();
  const restored=restoreRoutes(kept);
  const msg=`Could not build the walk: ${err.message}${restored?' Your previous route is still shown and unchanged.':''}`;$('rankingStatus').textContent=msg;appendChat('assistant',msg);toast(msg);
 }finally{if(run===planner.runId){state.routingBusy=false;$('generateRoutes').disabled=false;$('chatSend').disabled=false;$('ctaLabel').textContent='Plan My Walk';}}
}
function itinerarySummaryText(it){
 const t=it.totals,c=it.constraints;
 const stops=it.stops.filter(s=>s.role!=='end').map(s=>s.name).join(' → ');
 const pool=it.pool&&it.pool.requested>it.pool.added?` ${it.pool.requested-it.pool.added} more discovered place(s) did not fit the ${c.max_outing_minutes?`${c.max_outing_minutes}-minute outing`:'budget'}; extend the time to add them.`:'';
 return pool+`${c.feasible?'Planned':'Not feasible'}: ${t.stops} stop(s)${stops?` — ${stops}`:''}${it.end_mode==='round'?' → back to start':it.end_mode==='hotel'?' → back to my hotel':''}. `+
  `${(t.walk_m/1000).toFixed(2)} km, ${Math.round(t.walk_min)} min walking + ${Math.round(t.visit_min)} min visits (estimated) = ${Math.round(t.outing_min)} min.`+
  (c.violations.length?` ${c.violations.join('; ')}.`:'')+(it.skipped.length?` Skipped: ${it.skipped.map(s=>`${s.name} (${s.reason})`).join('; ')}.`:'')+
  it.stops.map(s=>{const f=journey.food.find(f=>s.slot_id===`food:${f.category}:${f.item||f.cuisine||''}`&&f.item),r=f&&journey.recs[s.id+'|'+f.item];
   return r&&r.classification!=='meets_request'?` ${titleCase(f.item)} is not confirmed on ${s.name}’s official menu (${r.classification==='needs_review'?'possible match, review the evidence':'no confirming source'}).`:'';}).join('');
}

/* ---------- food recommendations (server) ---------- */
async function recommendFood(f,cats,start,end){
 try{
  const searchAnchor=journey.requirements.search_anchor?await findNamedPlace(journey.requirements.search_anchor):null;
  const r=await streetwiseFetch('/api/recommend/food',{method:'POST',headers:{'Content-Type':'application/json'},signal:AbortSignal.timeout(65000),
   body:JSON.stringify({search_near:searchAnchor?pick(searchAnchor):null,item:f.item,cuisine:f.cuisine||null,categories:cats,sequence:[start,end].filter(Boolean).map(pick),radius_m:1000,departure:new Date().toISOString(),ratings_required:journey.requirements.ratings_required,minimum_rating:journey.requirements.minimum_rating,max_item_price_usd:journey.requirements.restaurant_budget_usd})});
  const d=await r.json();if(!r.ok)throw new Error(d.error||`HTTP ${r.status}`);
  if(d.status==='blocked_by_provider_access')appendChat('assistant','Requested review evidence is unavailable: no rating provider is configured. No candidate will be called highly rated.');
  const keep=d.candidates.filter(c=>c.classification==='meets_request').slice(0,6);
  for(const c of keep){const id=c.place.index_id||c.place.place_id;journey.recs[id+'|'+f.item]=c;if(c.menu&&c.menu.status!=='not_checked')journey.menu[id+'|'+f.item]=c.menu;}
  return keep.map(c=>({id:c.place.index_id||c.place.place_id,name:c.place.name,lat:c.place.coordinates.lat,lon:c.place.coordinates.lon,category:c.place.category,
   address:c.place.address,hours:c.place.opening_hours,source:c.place.data_sources.join(' + '),score:{meets_request:1,needs_review:.6,not_confirmed:.2}[c.classification],
   evidence:[c.explanation.interpretation,...c.explanation.verified_facts].join(' · ')}));
 }catch(e){console.warn('food recommendation unavailable',e.message);return null;}
}

/* ---------- typed place details (server) ---------- */
const QUALITY_LABEL={verified:'Source corroborated — see evidence',unverified:'Listed, not verified',limited_data:'Limited data',closed:'Closed (NYC DOHMH)'};
async function placeDetails(id){
 try{const r=await streetwiseFetch('/api/places/'+id.split('/').map(encodeURIComponent).join('/'),{signal:AbortSignal.timeout(10000)});return r.ok?await r.json():null;}catch{return null;}
}
async function placeRatings(id){
 const r=await streetwiseFetch('/api/places/'+id.split('/').map(encodeURIComponent).join('/')+'/ratings',{signal:AbortSignal.timeout(30000)});
 const d=await r.json();if(!r.ok)throw new Error(d.error||`HTTP ${r.status}`);return d;
}

/* ---------- menu verification ---------- */
function freshMenuEvidence(m){
 if(!m?.checked_at)return false;
 const age=Date.now()-Date.parse(m.checked_at),ttl=m.status==='confirmed_menu_match'?12*3600000:300000;
 return Number.isFinite(age)&&age>=0&&age<ttl;
}
function menuEvidenceForDisplay(m){
 return m?.status==='confirmed_menu_match'&&!freshMenuEvidence(m)?{...m,status:'unverified',price:null,reason:'Menu evidence has expired or has no check date; recheck the official menu.'}:m;
}
function stopMenuItems(stop){
 const f=journey.food.find(f=>stop.slot_id===`food:${f.category}:${f.item||f.cuisine||''}`&&f.item);
 return [...new Set([...(stop.required_items||[]),stop.required_item,f?.item].filter(Boolean))];
}
const MENU_INFLIGHT=new Map();
async function verifyMenuItem(place,item){
 const key=place.id+'|'+item;if(journey.menu[key]?.status&&journey.menu[key].status!=='checking'&&freshMenuEvidence(journey.menu[key]))return journey.menu[key];
 if(MENU_INFLIGHT.has(key))return MENU_INFLIGHT.get(key);
 const pending=checkMenuItem(place,item,key);MENU_INFLIGHT.set(key,pending);
 try{return await pending;}finally{MENU_INFLIGHT.delete(key);}
}
async function checkMenuItem(place,item,key){
 journey.menu[key]={status:'checking'};renderCityWalk();
 try{const r=await streetwiseFetch('/api/menu/verify',{method:'POST',headers:{'Content-Type':'application/json'},
   body:JSON.stringify({place_id:place.id,name:place.name,website:place.website||place.raw?.web||null,menu_url:place.menuUrl||place.raw?.menu||null,item}),signal:AbortSignal.timeout(30000)});
  const d=await r.json();if(!r.ok)throw new Error(d.error||`HTTP ${r.status}`);journey.menu[key]=d;
 }catch(e){journey.menu[key]={status:'unverified',checked_at:new Date().toISOString(),reason:`Menu check unavailable (${e.message}).`};}
 renderCityWalk();return journey.menu[key];
}
async function autoVerifyMenus(){
 if(!journey.plan)return;
 for(const s of journey.plan.stops){
  const items=stopMenuItems(s);if(!items.length)continue;
  const p=await placeById(s.id);if(p)for(const item of items)verifyMenuItem(p,item);
 }
}
async function placeById(id){
 for(const c of Object.keys(POI_CACHE)){const r=(await POI_CACHE[c]).find(x=>x.id===id);if(r)return poiPlace(r);}
 return null;
}
const MENU_LABEL={confirmed_menu_match:'Confirmed menu match',probable_match_review:'Probable match — review needed',unverified:'Unverified',not_found_in_checked_sources:'Not found in checked sources',checking:'Checking official menu…'};

/* ---------- nearby / along-route search (find, without adding) ---------- */
async function findServices(type,scope){
 const anchor=scope==='near_hotel'?journey.hotel:journey.requirements.search_anchor?await findNamedPlace(journey.requirements.search_anchor):getPlace('start');
 if(scope==='near_hotel'&&!anchor)return {places:[],note:'Set My Hotel first to search near it.'};
 if(scope==='along_route'&&journey.plan||scope==='along_route'&&state.routes.length){
  const seq=journey.plan?[journey.plan.start,...journey.plan.stops]:[getPlace('start'),getPlace('end')].filter(Boolean);
  const cands=await discoverPlaces([type],{limit:10,radiusKm:.8});
  try{const r=await streetwiseFetch('/api/detours',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({sequence:seq.map(pick),candidates:cands.map(pick)}),signal:AbortSignal.timeout(20000)});
   const d=await r.json();if(!r.ok)throw new Error(d.error);
   const by=Object.fromEntries(d.candidates.map(c=>[c.id,c]));
   return {places:cands.map(c=>({...c,detour:by[c.id]})).filter(c=>c.detour?.reachable).sort((a,b)=>a.detour.detour_m-b.detour.detour_m).slice(0,6),note:'Ranked by real walking detour added to your current walk.'};
  }catch(e){return {places:cands.slice(0,6),note:`Detours unavailable (${e.message}); shown by straight-line distance to the walk.`};}
 }
 let citywideError=null;
 if(anchor){try{const d=await streetwiseJson('/api/places/search?'+new URLSearchParams({lat:anchor.lat,lon:anchor.lon,categories:type,radius_m:1200,limit:6}));
  return {places:d.results.map(p=>({id:p.index_id,place_id:p.place_id,name:p.name,category:p.category,lat:p.coordinates.lat,lon:p.coordinates.lon,address:p.address,hours:p.opening_hours,source:p.data_sources.join(' + '),sourceUrl:p.source_links?.[0],routing_coverage:p.routing_coverage})),note:'NYC source search; distances are straight-line preselection. Search-only records have no verified walking access.'};
 }catch(e){citywideError=e.message;console.warn('Citywide service source unavailable',e.message);}}
 const res=await discoverPlaces([type],{near:anchor,limit:6,radiusKm:1.2});
 return {places:res,note:`${citywideError?'Citywide source unavailable; partial local snapshot only. ':''}Nearest by straight-line distance to ${anchor?.name||'the start'}; add one as a stop to get the real walking route.`};
}
