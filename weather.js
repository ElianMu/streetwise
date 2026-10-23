'use strict';
/* STREETWISE weather context: fetched once, shared by AI Journey, the routing request and Route Intelligence.
   Weather is a dynamic context next to the 12 static dimensions, never a 13th dimension and never a street-level
   measurement: one Open-Meteo grid value describes the whole walk, and only the routing engine decides whether it
   may change a route (routing/weather.py, where heat meets the street-tree / park cover proxy).

   Sources: Open-Meteo forecast API (no key; current = 15-minute model state, hourly = forecast) and the US National
   Weather Service active alerts API (no key). Missing values stay null; a failure never blocks ordinary routing. */
const WEATHER={
 forecastUrl:'https://api.open-meteo.com/v1/forecast',
 alertsUrl:'https://api.weather.gov/alerts/active',
 refreshMin:15,      // automatic refresh interval; map moves never trigger a request
 staleMin:45,        // shown as stale after this; the engine ignores snapshots older than 180 min
 timeoutMs:10000,
 // A route recalculation is suggested only when one of these changes (not on small value drift).
 signature:s=>s?[s.heatBand,s.daylight,s.rainAdvisory,s.windAdvisory].join('|'):'none',
};
const weatherContext={status:'idle',source:'Open-Meteo forecast API (model data, not a station observation)',fetchedAt:null,location:null,
 current:null,hourly:[],alerts:{status:'idle',items:[],source:'US National Weather Service active alerts'},error:null,mode:'auto',priority:'normal',lastSignature:null,listeners:[]};

function weatherAgeMin(){return weatherContext.fetchedAt?(Date.now()-weatherContext.fetchedAt)/60000:null;}
function weatherFresh(){const a=weatherAgeMin();return weatherContext.status==='ok'&&a!==null&&a<=WEATHER.staleMin;}
function onWeather(fn){weatherContext.listeners.push(fn);}
function emitWeather(){for(const fn of weatherContext.listeners){try{fn(weatherContext)}catch(e){console.warn('weather listener',e)}}}

async function fetchJsonTimeout(url,ms,headers){const r=await fetch(url,{signal:AbortSignal.timeout(ms),headers});if(!r.ok)throw new Error(`HTTP ${r.status}`);return r.json();}

/** Fetch (or reuse) the weather. `force` ignores the cache (user pressed refresh). Never throws. */
async function refreshWeather(force=false,here=null){
 if(weatherContext.pending)return weatherContext.pending;
 const age=weatherAgeMin();if(!force&&weatherContext.status==='ok'&&age!==null&&age<WEATHER.refreshMin)return weatherContext;
 const loc=here||weatherContext.location||{lat:40.783,lon:-73.969};weatherContext.location=loc;
 if(weatherContext.status!=='ok')weatherContext.status='loading';emitWeather();
 weatherContext.pending=(async()=>{
  try{
   const q=new URLSearchParams({latitude:loc.lat.toFixed(4),longitude:loc.lon.toFixed(4),timezone:'America/New_York',forecast_hours:'6',
    current:'temperature_2m,apparent_temperature,relative_humidity_2m,precipitation,weather_code,wind_speed_10m,wind_direction_10m,is_day',
    hourly:'temperature_2m,apparent_temperature,precipitation_probability,precipitation,weather_code,wind_speed_10m,is_day'});
   const d=await fetchJsonTimeout(`${WEATHER.forecastUrl}?${q}`,WEATHER.timeoutMs);
   if(!d.current||!d.hourly)throw new Error('No model output');
   const c=d.current;
   weatherContext.current={time:c.time,temperature:c.temperature_2m??null,feelsLike:c.apparent_temperature??null,humidity:c.relative_humidity_2m??null,
    precipitation:c.precipitation??null,windSpeed:c.wind_speed_10m??null,windDirection:c.wind_direction_10m??null,code:c.weather_code??null,isDay:c.is_day==null?null:c.is_day===1,
    units:{temperature:'°C',precipitation:'mm',windSpeed:'km/h',windDirection:'°',humidity:'%'}};
   // Hourly times are New York local without an offset: convert to absolute ms with the response's UTC offset.
   const off=(d.utc_offset_seconds||0)*1000,abs=t=>Date.parse(t+'Z')-off;
   const h=d.hourly;weatherContext.hourly=h.time.map((t,i)=>({time:t,t:abs(t),temperature:h.temperature_2m[i],feelsLike:h.apparent_temperature[i],precipProbability:h.precipitation_probability[i],
    precipitation:h.precipitation[i],code:h.weather_code[i],windSpeed:h.wind_speed_10m[i],isDay:h.is_day[i]===1}));
   weatherContext.status='ok';weatherContext.error=null;weatherContext.fetchedAt=Date.now();
  }catch(e){
   weatherContext.error=e.name==='TimeoutError'?'Weather service timed out':navigator.onLine===false?'No network connection':`Weather service unavailable (${e.message})`;
   // Keep the last good data but mark it; with no data at all the context is unavailable.
   weatherContext.status=weatherContext.current?'ok':'error';
  }
  await refreshAlerts(loc);
  weatherContext.pending=null;emitWeather();return weatherContext;
 })();
 return weatherContext.pending;
}
async function refreshAlerts(loc){
 const A=weatherContext.alerts;
 try{const d=await fetchJsonTimeout(`${WEATHER.alertsUrl}?point=${loc.lat.toFixed(4)},${loc.lon.toFixed(4)}`,WEATHER.timeoutMs,{Accept:'application/geo+json'});
  A.items=(d.features||[]).map(f=>({event:f.properties.event,headline:f.properties.headline,severity:f.properties.severity,ends:f.properties.ends||f.properties.expires}));A.status='ok';A.fetchedAt=Date.now();
 }catch(e){A.status='error';A.items=[];}
}

/** Forecast summary for a walk starting now and lasting `minutes`: worst case over the hourly slots it touches. */
function weatherWindow(minutes,now=Date.now()){
 if(weatherContext.status!=='ok'||!weatherContext.hourly.length)return null;
 const start=now,end=start+Math.max(10,minutes||30)*60000;
 const slots=weatherContext.hourly.filter(s=>s.t<=end&&s.t+3600000>start);
 if(!slots.length)return null;
 const max=k=>{const v=slots.map(s=>s[k]).filter(x=>x!=null);return v.length?Math.max(...v):null;};
 const c=weatherContext.current;
 const feels=Math.max(...[max('feelsLike'),c?.feelsLike].filter(x=>x!=null));
 const w={from:slots[0].time,to:slots.at(-1).time,minutes:Math.round((end-start)/60000),feelsLikeMax:Number.isFinite(feels)?feels:null,temperatureMax:max('temperature'),
  precipProbabilityMax:max('precipProbability'),precipMax:max('precipitation'),windMax:Math.max(max('windSpeed')??0,c?.windSpeed??0)||null,daylight:slots.some(s=>s.isDay)};
 w.heatBand=w.feelsLikeMax==null?'na':w.feelsLikeMax<27?'none':w.feelsLikeMax<32?'caution':'extreme';
 w.rainAdvisory=(w.precipProbabilityMax??0)>=40||(w.precipMax??0)>=.5;w.windAdvisory=(w.windMax??0)>=30;
 return w;
}
/** Routing request field `weather` (routing/weather.py validates it); null when there is nothing trustworthy to send. */
function weatherSnapshot(minutes,now=Date.now()){
 const w=weatherWindow(minutes,now);if(!w)return null;
 return {source:'open-meteo',kind:'forecast_window',valid_from:w.from,valid_to:w.to,age_min:Math.round(weatherAgeMin()),feels_like_max_c:w.feelsLikeMax,temperature_max_c:w.temperatureMax,
  precip_probability_max_pct:w.precipProbabilityMax,precip_max_mm_per_h:w.precipMax,wind_max_kmh:w.windMax,daylight:w.daylight,mode:weatherContext.mode,priority:weatherContext.priority,
  alerts:weatherContext.alerts.items.map(a=>a.event)};
}
function weatherName(c){if(c==null)return'Unknown';if(c===0)return'Clear';if(c<=3)return'Cloudy';if(c===45||c===48)return'Fog';if(c>=51&&c<=67)return'Rain';if(c>=71&&c<=77)return'Snow';if(c>=80&&c<=82)return'Showers';if(c>=95)return'Storm';return'Variable'}
function weatherIcon(c){if(c==null)return'·';if(c===0)return'☀';if(c<=3)return'☁';if(c>=71&&c<=77)return'❄';if(c>=95)return'⚡';if(c>=51)return'☂';return'☁'}
function windArrow(deg){if(deg==null)return'';return['N','NE','E','SE','S','SW','W','NW'][Math.round(deg/45)%8];}
/** General walking advice from the walk-window forecast; never claims one street is cooler, drier or calmer than another. */
function weatherAdvice(w){
 if(!w)return [];const out=[];
 if(w.heatBand==='extreme')out.push(`Feels like up to ${Math.round(w.feelsLikeMax)} °C: carry water and take breaks in shade.`);
 else if(w.heatBand==='caution')out.push(`Feels like up to ${Math.round(w.feelsLikeMax)} °C: warm for a long walk.`);
 if(w.rainAdvisory)out.push(`Rain likely (${w.precipProbabilityMax??'?'}% chance${w.precipMax?`, up to ${w.precipMax} mm/h`:''}): no covered-walkway data is connected, so routes are not rain-optimised.`);
 if(w.windAdvisory)out.push(`Wind up to ${Math.round(w.windMax)} km/h: street-level wind exposure is not modelled, so no route is claimed to be sheltered.`);
 return out;
}
if(typeof module!=='undefined')module.exports={WEATHER,weatherContext,weatherWindow,weatherSnapshot,weatherAdvice};
