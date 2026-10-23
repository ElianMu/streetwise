/* weather.js: walk-window forecast, New York timestamps, routing snapshot, recalculation signature and failure
   handling, with fixed forecast data (no live API call). */
const path=require('path'),assert=require('node:assert/strict');
const W=require(path.join(__dirname,'..','weather.js'));
const {weatherContext:ctx,weatherWindow,weatherSnapshot,weatherAdvice,WEATHER}=W;
// Open-Meteo returns New York local hours without an offset; weather.js converts them with utc_offset_seconds.
const off=-4*3600*1000,abs=t=>Date.parse(t+'Z')-off;
const hours=['2026-07-15T13:00','2026-07-15T14:00','2026-07-15T15:00','2026-07-15T16:00'];
const now=abs('2026-07-15T14:20');   // 14:20 in New York, wherever the test runs
ctx.status='ok';ctx.fetchedAt=Date.now();ctx.current={feelsLike:30,windSpeed:8,code:0};
ctx.hourly=hours.map((t,i)=>({time:t,t:abs(t),temperature:29+i,feelsLike:[30,31,35,38][i],precipProbability:[0,10,60,0][i],precipitation:[0,0,1.2,0][i],windSpeed:[8,9,12,35][i],isDay:true}));
// A 20-minute walk from 14:20 touches only the 14:00 slot; a 60-minute walk reaches 15:00 (rain, 35 °C).
const short=weatherWindow(20,now),long=weatherWindow(60,now);
assert.equal(short.from,'2026-07-15T14:00');assert.equal(short.to,'2026-07-15T14:00');assert.equal(short.feelsLikeMax,31);assert.equal(short.rainAdvisory,false);
assert.equal(long.to,'2026-07-15T15:00');assert.equal(long.feelsLikeMax,35);assert.equal(long.precipProbabilityMax,60);assert.equal(long.rainAdvisory,true);assert.equal(long.heatBand,'extreme');
assert.equal(weatherWindow(120,now).windAdvisory,true);
// Snapshot for the engine: units implied by field names, mode/priority carried, no invented fields.
ctx.priority='high';const snap=weatherSnapshot(60,now);
assert.equal(snap.kind,'forecast_window');assert.equal(snap.priority,'high');assert.equal(snap.source,'open-meteo');
for(const k of ['feels_like_max_c','precip_probability_max_pct','wind_max_kmh','daylight'])assert(k in snap,k);
// Recalculation signature: small drift does not change it; crossing a band does.
const sig=w=>WEATHER.signature(w);
assert.equal(sig({...short,feelsLikeMax:31.4}),sig(short));assert.notEqual(sig(short),sig(long));
// Advice never claims a street is cooler, drier or calmer.
const advice=weatherAdvice(weatherWindow(120,now)).join(' ');
assert(/not rain-optimised/.test(advice)&&/no route is claimed to be sheltered/.test(advice));assert(!/this street is|is cooler|more sheltered route/i.test(advice));
// Failure: no data → no window, no snapshot (the request then carries weather:null and routing is unchanged).
ctx.status='error';ctx.hourly=[];
assert.equal(weatherWindow(30,now),null);assert.equal(weatherSnapshot(30,now),null);
console.log('WEATHER PASS: walk window (NY time), worst-case values, rain/wind/heat advisories, snapshot, band signature, failure → null');
