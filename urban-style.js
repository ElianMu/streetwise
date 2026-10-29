/* STREETWISE Urban Data Cartographic Design System — tokens and composition rules for Navigate.
   One accent (the selected route, lime); muted semantic families for data categories; neutral buildings and streets;
   one continuous theme at a time for buildings and for environment. Used by urban-layers.js (rendering + legend). */
(function(root){
'use strict';
const T={
 bg:'#000000', stroke:'#000000', halo:'#000000',
 route:{selected:'#d8f365',halo:'#000000',alt:'#7d8794',start:'#45d4e6',end:'#f2a876'},
 // Category families on the black basemap. The eight data categories use one validated categorical set (dark steps,
 // adjacent-pair CVD ΔE ≥ 8, normal-vision ΔE ≥ 15, ≥ 3:1 on black; run the palette validator before changing it);
 // street infrastructure and building records are neutral graphite so they recede. Never lime (the route's colour).
 cat:{streets:'#7d8794',buildings:'#6b7380',waterfront:'#3987e5',transit:'#d95926',services:'#199e70',activities:'#c98500',environment:'#d55181',nature:'#008300',heritage:'#9085e9',safety:'#e66767'},
 // Visual weight per point category: street infrastructure (ramps, signals, corners) recedes; destinations lead.
 weight:{streets:{size:.7,opacity:.55},services:{size:.85,opacity:.8},safety:{size:.9,opacity:.85}},
 // Zoom tiers (MapLibre zoom), tuned on Midtown screenshots: city < 13 ≤ neighbourhood < 15 ≤ street < 17 ≤ detail.
 zoom:{neighbourhood:13,street:15,detail:17},
 point:{stops:[[13,1.8],[15,2.6],[17,4],[19,6]],ring:[3.4,4.8,7,10],strokeStops:[[13,0],[15,.4],[17,.8],[19,1]]},
 tree:{radius:['interpolate',['linear'],['zoom'],12,.5,15,1.4,18,3.2],opacity:.7},
 // Clusters shrink at city zoom so ten categories don't stack into a field of overlapping rings.
 cluster:{radius:['interpolate',['linear'],['zoom'],11,['interpolate',['linear'],['get','point_count'],2,2.5,40,4,400,6],14,['interpolate',['linear'],['get','point_count'],2,5,40,8,400,12]],fill:.14,stroke:.6,maxZoom:15,pixelRadius:48},
 label:{font:['Montserrat Medium','Open Sans Regular'],size:10,minZoom:17},
 building:{
  neutral:'#1a1e24',outline:'#3a414b',fillOpacity:.62,extrusionOpacity:.84,
  // Capped below off-white: in the flat 2D fill this ramp's top end barely showed (rooftop only); extruded to full
  // height a skyscraper's whole face carries it, so a near-white top stop blew out and broke the dark theme.
  height:{prop:'height_roof_ft',unit:'ft',stops:[[0,'#0c0f13'],[40,'#12171d'],[80,'#182029'],[150,'#202b38'],[300,'#2a3849'],[600,'#364a61']]},
  age:{prop:'construction_year',unit:'year built',stops:[[1800,'#5b4636'],[1880,'#6d5a44'],[1920,'#7b6f57'],[1950,'#5e6c6c'],[1980,'#4c6879'],[2015,'#3c6489']]},
  landuse:{prop:'landuse_name',classes:[['One & two family','#6f7f5b'],['Multi-family walk-up','#857d58'],['Multi-family elevator','#8c7552'],['Mixed residential & commercial','#8e6a5c'],['Commercial & office','#7a6070'],
   ['Industrial & manufacturing','#6a5f7c'],['Transportation & utility','#5b6a80'],['Public facilities & institutions','#4f7480'],['Open space & outdoor recreation','#4f7c66'],['Parking','#5e6468'],['Vacant land','#4a4f52']],other:'#3a4247'}},
 env:{noise:{label:'311 noise complaint density',unit:'relative density of complaints (12 months)',ramp:[[0,'rgba(0,0,0,0)'],[.2,'#33303f'],[.45,'#4d3b50'],[.7,'#6e4858'],[.9,'#94595f'],[1,'#b97a72']],opacity:.32,intensity:[12,.25,16,.6],radius:[12,6,16,15]}},
};
// Datasets with a dedicated render group; every other dataset is grouped by geometry and primary category.
const SPECIAL={building_footprints:'buildings',building_heights:'buildings',building_age:'buildings',land_use:'buildings',parks:'green',community_gardens:'green',natural_areas:'green',waterfront_parks:'green',
 sidewalk_surface:'surface',pedestrian_plazas:'surface',historic_districts:'districts',landmarks:'landmarks',street_trees:'trees',noise_complaints:'noise'};
// Line styles: thin, low-contrast, semantic. Nothing uses yellow, so no data line can be mistaken for the route.
const LINES={
 lion_centerline:{color:'#6b7685',width:[12,.4,16,1.1],opacity:.35},
 osm_sidewalks:{color:'#8a94a3',width:[15,.4,18,1.2],opacity:.35,minzoom:15},
 osm_crosswalks:{color:'#c3c9d1',width:[15,.8,18,2.4],opacity:.55,dash:[1.2,1],minzoom:15},
 osm_paths:{color:'#86ad8f',width:[14,.5,18,1.6],opacity:.5,dash:[2,1.2],minzoom:13.5},
 pedestrian_bridges:{color:'#c3c9d1',width:[13,1,18,2.6],opacity:.6},
 bike_routes:{color:'#62a2d9',width:[13,.6,18,1.8],opacity:.45,dash:[3,1.5]},
 speed_limits:{color:'#d27b6c',width:[14,.5,18,1.4],opacity:.35,minzoom:14},
 expressways:{color:'#c96e60',width:[11,1,16,3],opacity:.45},
};
function hexToHsl(h){const r=parseInt(h.slice(1,3),16)/255,g=parseInt(h.slice(3,5),16)/255,b=parseInt(h.slice(5,7),16)/255,mx=Math.max(r,g,b),mn=Math.min(r,g,b);let H=0,S=0;const L=(mx+mn)/2;
 if(mx!==mn){const d=mx-mn;S=L>.5?d/(2-mx-mn):d/(mx+mn);H=mx===r?(g-b)/d+(g<b?6:0):mx===g?(b-r)/d+2:(r-g)/d+4;H/=6;}return [H,S,L];}
function hslToHex(H,S,L){const f=n=>{const k=(n+H*12)%12,a=S*Math.min(L,1-L);return Math.round(255*(L-a*Math.max(-1,Math.min(k-3,9-k,1)))).toString(16).padStart(2,'0');};return '#'+f(0)+f(8)+f(4);}
/** Shade i of n within a category family: same hue, small lightness / saturation steps. */
function shade(base,i,n){if(n<=1)return base;const [h,s,l]=hexToHsl(base),t=i/(n-1)-.5;return hslToHex((h+t*.035+1)%1,Math.max(.15,s-Math.abs(t)*.1),Math.min(.82,Math.max(.38,l+t*.22)));}
function rampExpr(prop,stops){return ['interpolate',['linear'],['to-number',['get',prop],stops[0][0]],...stops.flat()];}
function categoricalExpr(prop,classes,other){return ['match',['get',prop],...classes.flat(),other];}
root.UrbanStyle={T,SPECIAL,LINES,shade,rampExpr,categoricalExpr};
if(typeof module!=='undefined')module.exports=root.UrbanStyle;
})(typeof globalThis!=='undefined'?globalThis:this);
