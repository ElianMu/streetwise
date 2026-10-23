'use strict';
/* Weather UI: compact status in Navigate, "Weather & your walk" in Route Intelligence, and the AI Journey's weather
   answers. Everything about routing comes from the engine's `weather_routing` record in the last route response
   (routing/weather.py), never from the browser's own guess. Four states are kept apart:
   Weather Data Available · Weather Context Applied · Weather Routing Active · Weather Routing Unavailable. */
const wxUI={timer:null};
const fmt=(v,u,d=0)=>v==null?'—':`${Number(v).toFixed(d)}${u}`;
function wxRouting(){return planner.routeResponse?.weather_routing||null;}
/** One label for the four states (data / context / routing active / routing unavailable). */
function weatherStates(){
 const data=weatherContext.status==='ok',fresh=weatherFresh(),r=wxRouting()?.routing;
 return {data:data?(fresh?'Weather data available':'Weather data stale'):weatherContext.status==='loading'?'Loading weather':'Weather data unavailable',
  context:Boolean(wxRouting()?.data_available),routing:r?.active?'active':r?r.status:'none',reason:r?.reason||null};
}
function renderWeatherStatus(){
 const c=weatherContext.current,ok=weatherContext.status==='ok'&&c,age=weatherAgeMin(),stale=ok&&!weatherFresh();
 const when=ok?`${c.time.replace('T',' ')} (New York) · ${Math.round(age)} min ago`:'';
 $('topWeather').innerHTML=ok?`<span class="tiny-sun">${weatherIcon(c.code)}</span> ${fmt(c.temperature,'°C')} · ${esc(weatherName(c.code))}${stale?' · stale':''}`:
  weatherContext.status==='loading'?'<span class="tiny-sun">·</span> Weather loading…':'Weather unavailable';
 $('weatherMain').textContent=ok?fmt(c.temperature,'°C'):weatherContext.status==='loading'?'…':'UNAVAILABLE';
 $('weatherMeta').textContent=ok?`Feels ${fmt(c.feelsLike,'°C')} · ${weatherName(c.code)} · ${fmt(c.windSpeed,' km/h')} wind`:(weatherContext.error||'Awaiting forecast');
 $('contextUpdated').textContent=ok?`Open-Meteo model (not a station observation) · valid ${when}${stale?' · STALE, refresh to update':''}`:`Weather: ${weatherContext.error||'not loaded'}. Routes use the static experience scores.`;
 renderWeatherPanel();renderWeatherRoute();
}
function renderWeatherPanel(){
 const pill=$('wxPill'),body=$('wxBody');if(!pill||!body)return;
 const c=weatherContext.current,ok=weatherContext.status==='ok'&&c,w=weatherWindow(state.budget),st=weatherStates(),changed=weatherChangedSinceRouting();
 pill.innerHTML=ok?`<span class="wx-ico">${weatherIcon(c.code)}</span><strong>${fmt(c.temperature,'°')}</strong><span>feels ${fmt(c.feelsLike,'°')}</span>${w?.rainAdvisory?'<span class="wx-flag">rain</span>':''}${w?.windAdvisory?'<span class="wx-flag">wind</span>':''}${weatherContext.alerts.items.length?'<span class="wx-flag alert">alert</span>':''}${st.routing==='active'?'<span class="wx-flag on">routing</span>':''}${changed?'<span class="wx-dot" title="Weather changed since routes were computed"></span>':''}`
  :`<span class="wx-ico">·</span><span>${weatherContext.status==='loading'?'Weather…':'Weather n/a'}</span>`;
 const alerts=weatherContext.alerts.status==='ok'?(weatherContext.alerts.items.length?weatherContext.alerts.items.map(a=>`<li class="wx-alert">${esc(a.event)}${a.ends?` · until ${esc(new Date(a.ends).toLocaleString('en-US',{timeZone:'America/New_York',hour:'numeric',minute:'2-digit',weekday:'short'}))}`:''}</li>`).join(''):'<li>No active NWS alerts for this point</li>'):'<li>NWS alerts unavailable</li>';
 body.innerHTML=ok?`<dl class="wx-grid">
   <dt>Now</dt><dd>${fmt(c.temperature,' °C')} · feels ${fmt(c.feelsLike,' °C')} · ${esc(weatherName(c.code))}</dd>
   <dt>Humidity</dt><dd>${fmt(c.humidity,' %')}</dd>
   <dt>Wind</dt><dd>${fmt(c.windSpeed,' km/h')} ${windArrow(c.windDirection)}</dd>
   <dt>Next ${w?.minutes||state.budget} min</dt><dd>${w?`feels up to ${fmt(w.feelsLikeMax,' °C')} · rain ${fmt(w.precipProbabilityMax,' %')} · wind up to ${fmt(w.windMax,' km/h')}${w.daylight?'':' · after dark'}`:'Forecast window unavailable'}</dd></dl>
  <ul class="wx-list">${alerts}</ul>
  <p class="wx-route-state ${st.routing}">${esc(routingStateText())}</p>`
  :`<p class="wx-route-state">${esc(weatherContext.error||'Weather has not loaded.')} Routes use the static experience scores.</p>`;
 body.insertAdjacentHTML('beforeend',`<div class="wx-actions"><label><input type="checkbox" id="wxAuto" ${weatherContext.mode==='auto'?'checked':''}> Weather-aware routing</label><button type="button" id="wxRefresh" class="mini-outline">Refresh</button>${changed&&state.routes.length?'<button type="button" id="wxReroute" class="mini-outline">Recalculate</button>':''}</div>
  <small class="wx-source">Open-Meteo forecast (grid model, one value for the whole walk) · NWS alerts. Never a street-level measurement.</small>`);
 $('wxAuto').addEventListener('change',e=>{weatherContext.mode=e.target.checked?'auto':'off';renderWeatherPanel();if(state.routes.length)toast('Recalculate to apply this to the routes.');});
 $('wxRefresh').addEventListener('click',()=>refreshWeather(true));
 $('wxReroute')?.addEventListener('click',()=>generateRoutes(null,true));
}
function routingStateText(){
 const r=wxRouting()?.routing;
 if(!state.routes.length)return weatherContext.mode==='off'?'Weather-aware routing is off.':'Weather will be checked when you plan a route.';
 if(!r)return 'These routes were computed without weather data.';
 if(r.active)return `Weather routing active: ${r.reason}`;
 return r.status==='unavailable'?`Weather routing unavailable: ${r.reason}`:`Weather information is available, but weather-based route optimization is not active for this route. ${r.reason}`;
}
/** Route Intelligence: conditions for the walk, impact, and what the engine actually did. */
function renderWeatherRoute(){
 const root=$('wxRoute');if(!root)return;
 const x=state.routes.find(r=>r.id===state.activeRoute),w=weatherWindow(x?Math.ceil(x.raw.estimated_duration_min):state.budget),wr=wxRouting(),r=wr?.routing;
 $('wxRouteStatus').textContent=r?.active?'ROUTING ACTIVE':weatherContext.status==='ok'?'INFO ONLY':'UNAVAILABLE';
 const cond=w?`<div class="data-pair"><span>During the walk (${w.minutes} min from now)</span><span>feels up to ${fmt(w.feelsLikeMax,' °C')}</span></div><div class="data-pair"><span>Rain chance · wind</span><span>${fmt(w.precipProbabilityMax,' %')} · ${fmt(w.windMax,' km/h')}</span></div>`
  :`<p class="soft-copy">${esc(weatherContext.error||'Weather forecast not loaded.')}</p>`;
 const advice=weatherAdvice(w);
 const impact=`<p class="wx-sub">Weather impact on your walk</p>${advice.length?`<ul class="wx-list">${advice.map(a=>`<li>${esc(a)}</li>`).join('')}</ul>`:`<p class="soft-copy">${w?'No weather condition expected to affect walking comfort.':'Unknown — no forecast.'}</p>`}`;
 let expl='';
 if(!x)expl='<p class="soft-copy">Plan a route to see whether weather changed it.</p>';
 else if(!r||!wr.data_available)expl=`<p class="soft-copy">These routes were computed without usable weather data${r?.reason?`: ${esc(r.reason)}`:''}.</p>`;
 else if(!r.active)expl=`<p class="wx-route-state">Weather information is available, but weather-based route optimization is not active for this route.</p><small>${esc(r.reason)}</small>`;
 else{
  const e=r.effect,mine=x.raw.weather,cooler=state.routes.find(y=>y.raw.objective==='weather_heat');
  expl=`<div class="data-pair"><span>Factor considered</span><span>Heat · feels ${fmt(wr.snapshot.feels_like_max_c,' °C')} (level ${r.level}${r.multiplier>1?', ×'+r.multiplier+' on request':''})</span></div>
   <div class="data-pair"><span>Spatial evidence</span><span>Street-tree / park cover proxy</span></div>
   ${mine?`<div class="data-pair"><span>This route, heat-exposed length</span><span>${Math.round(mine.heat_exposure_share*100)}% · evidence on ${Math.round(mine.evidence_coverage*100)}%</span></div>`:''}
   <p>${e?.changed?`Weather changed the recommendation: <strong>${esc(state.routes.find(y=>y.id===e.recommended_route_id)?.label||'')}</strong> replaces <strong>${esc(state.routes.find(y=>y.id===e.baseline_route_id)?.label||'the static best match')}</strong>, ${Math.round(e.exposure_reduction*100)} points less heat-exposed length for ${e.extra_minutes>=0?'+':''}${e.extra_minutes} min.`
    :'Weather was applied, and the static recommendation still ranks best, so it is kept.'}${cooler?` A dedicated <strong>Cooler Route</strong> (${Math.round(cooler.raw.weather.heat_exposure_share*100)}% exposed, ${Math.ceil(cooler.raw.estimated_duration_min)} min) is in the list.`:''}</p>
   <small>${esc(mine?.evidence||'')} Coefficients ${esc(wr.config_version)}; routes keep every walking-time, detour and stairs limit.</small>`;
 }
 root.innerHTML=`<p class="wx-sub">Weather conditions</p>${cond}${impact}<p class="wx-sub">Weather-aware route explanation</p>${expl}${weatherChangedSinceRouting()&&x?'<button type="button" class="mini-outline" id="wxReroute2">Weather changed · Recalculate</button>':''}`;
 $('wxReroute2')?.addEventListener('click',()=>generateRoutes(null,true));
}
/** Chat sentence describing what weather did in the last computation (from the engine record). */
function weatherRouteSentence(json){
 const wr=json?.weather_routing,r=wr?.routing;if(!r)return '';
 if(!wr.data_available)return ' Weather: no usable forecast, so routes use the static scores only.';
 if(!r.active)return ` Weather: considered but not used for routing — ${r.reason}`;
 const e=r.effect;
 return ` Weather routing active (${r.reason.replace(/\.$/,'')}). `+(e?.changed?`The recommendation changed to reduce heat-exposed length by ${Math.round(e.exposure_reduction*100)} points for ${e.extra_minutes>=0?'+':''}${e.extra_minutes} min.`:'The recommended route is unchanged: it still ranks best with the heat term.')+' Evidence: street-tree / park cover proxy, not measured shade.';
}
/** "Is my route comfortable in this weather?" — answered from the forecast and computed route fields only. */
function weatherAnswer(){
 const x=state.routes.find(r=>r.id===state.activeRoute),w=weatherWindow(x?Math.ceil(x.raw.estimated_duration_min):state.budget);
 if(!w)return `I can't read the weather right now (${weatherContext.error||'no forecast'}), so I can't judge comfort.`;
 const parts=[`For the next ${w.minutes} min the forecast is feels-like up to ${fmt(w.feelsLikeMax,' °C')}, ${fmt(w.precipProbabilityMax,' %')} rain chance, wind up to ${fmt(w.windMax,' km/h')}${w.daylight?'':', after dark'}.`];
 parts.push(...weatherAdvice(w));
 if(x?.raw.weather)parts.push(`Your selected route has ${Math.round(x.raw.weather.heat_exposure_share*100)}% of its length with little street-tree or park cover (a proxy, not measured shade).`);
 parts.push('This forecast is one value for the whole area; I have no street-level temperature, rain-cover or wind data, so I can\'t say one street is actually more comfortable than another.');
 if(w.heatBand!=='none'&&w.heatBand!=='na')parts.push('Ask for "a cooler route" to re-plan with the heat term weighted up.');
 return parts.join(' ');
}
function weatherChangedSinceRouting(){
 if(!state.routes.length||planner.weatherSignature===undefined)return false;
 return WEATHER.signature(weatherWindow(state.budget))!==planner.weatherSignature;
}
function setupWeatherUI(){
 onWeather(renderWeatherStatus);
 // The open panel never stays over the route: any map interaction closes it.
 $('map').addEventListener('pointerdown',()=>{$('wxPanel').open=false;});
 // Periodic refresh; requests never follow map movement. Hidden tabs skip the refresh.
 wxUI.timer=setInterval(()=>{if(!document.hidden)refreshWeather(false);},WEATHER.refreshMin*60000);
 setInterval(()=>{if(weatherContext.status==='ok')renderWeatherStatus();},60000);  // age / stale labels
 renderWeatherStatus();
}
