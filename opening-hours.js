'use strict';
/* Minimal evaluator for OpenStreetMap opening_hours, for "open when you arrive" checks.
   Supports: 24/7; rules separated by ';'; day lists/ranges (Mo-Fr, Sa,Su); time lists/ranges (09:00-17:00, 08:00-12:00,13:00-18:00);
   ranges past midnight (18:00-02:00); "off"/"closed". PH rules return unknown without a holiday calendar. Anything else returns null rather
   than a guess. Times are evaluated in New York local time. */
const OH_DAYS=['Mo','Tu','We','Th','Fr','Sa','Su'];
function ohNyParts(date){
 const p=Object.fromEntries(new Intl.DateTimeFormat('en-US',{timeZone:'America/New_York',weekday:'short',hour:'2-digit',minute:'2-digit',hour12:false}).formatToParts(date).map(x=>[x.type,x.value]));
 const day=['Mon','Tue','Wed','Thu','Fri','Sat','Sun'].indexOf(p.weekday);return {day,min:(+p.hour%24)*60+(+p.minute)};
}
function ohDays(spec){
 const out=new Set();
 for(const part of spec.split(',')){const m=part.trim().match(/^(Mo|Tu|We|Th|Fr|Sa|Su)(?:-(Mo|Tu|We|Th|Fr|Sa|Su))?$/);if(!m)return null;
  let a=OH_DAYS.indexOf(m[1]),b=m[2]?OH_DAYS.indexOf(m[2]):a;for(let i=0;i<7;i++){const d=(a+i)%7;out.add(d);if(d===b)break;}}
 return out;
}
function ohTimes(spec){
 const out=[];for(const part of spec.split(',')){const m=part.trim().match(/^(\d{1,2}):(\d{2})-(\d{1,2}):(\d{2})\+?$/);if(!m||+m[1]>23||+m[3]>24||+m[2]>59||+m[4]>59||(+m[3]===24&&+m[4]!==0))return null;out.push([+m[1]*60+ +m[2],+m[3]*60+ +m[4]]);}return out;
}
/** true / false / null (unknown or unsupported syntax). */
function isOpenAt(hours,date){
 if(!hours||typeof hours!=='string')return null;const h=hours.trim();
 if(h==='24/7')return true;
 if(/\bPH\b/.test(h))return null;
 const {day,min}=ohNyParts(date);let verdict=null,anyRule=false;
 const nyDate=new Intl.DateTimeFormat('en-US',{timeZone:'America/New_York',month:'numeric',day:'numeric'}).formatToParts(date).reduce((o,x)=>(o[x.type]=+x.value,o),{});
 for(const raw of h.split(';')){
  const r=raw.trim();if(!r)continue;
  // date exceptions ('Dec 25 off', 'Nov Th[4] off') apply on their date only; other dated rules this month are unknown
  const mm=r.match(/^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\b\s*(.*)$/);
  if(mm){const mon=['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'].indexOf(mm[1])+1,rest=mm[2].trim();
   if(nyDate.month!==mon)continue;
   const d1=rest.match(/^0?(\d{1,2})\s+(off|closed)$/),nth=rest.match(/^(Mo|Tu|We|Th|Fr|Sa|Su)\[(\d)\]\s+(off|closed)$/);
   if(d1){if(nyDate.day===+d1[1])return false;continue;}
   if(nth){if(day===OH_DAYS.indexOf(nth[1])&&Math.floor((nyDate.day-1)/7)+1===+nth[2])return false;continue;}
   return null;}
  const m=r.match(/^((?:(?:Mo|Tu|We|Th|Fr|Sa|Su)(?:-(?:Mo|Tu|We|Th|Fr|Sa|Su))?)(?:,(?:Mo|Tu|We|Th|Fr|Sa|Su)(?:-(?:Mo|Tu|We|Th|Fr|Sa|Su))?)*)?\s*(.*)$/);
  if(!m)return null;
  const days=m[1]?ohDays(m[1]):new Set([0,1,2,3,4,5,6]),rest=m[2].trim();if(!days)return null;anyRule=true;
  const prevDay=(day+6)%7;
  if(/^(off|closed)$/i.test(rest)){if(days.has(day))verdict=false;continue;}
  const times=rest===''?[[0,1440]]:ohTimes(rest);if(!times)return null;
  for(const [a,b] of times){
   if(b>a){if(days.has(day)){verdict=verdict||false;if(min>=a&&min<b)verdict=true;}}
   else{ // past midnight: open from a today, or until b from yesterday's rule
    if(days.has(day)){verdict=verdict||false;if(min>=a)verdict=true;}
    if(days.has(prevDay)&&min<b)verdict=true;
   }
  }
  // A later rule for the same day replaces earlier ones in OSM syntax; we keep the most permissive match among the rules.
 }
 if(!anyRule)return null;
 return verdict===null?false:verdict;
}
if(typeof module!=='undefined')module.exports={isOpenAt};
