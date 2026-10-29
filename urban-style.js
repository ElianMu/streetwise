/* STREETWISE Urban Data Cartographic Design System — tokens and composition rules for Navigate.
   One accent (the selected route, lime); muted semantic families for data categories; neutral buildings and streets;
   one continuous theme at a time for buildings and for environment. Used by urban-layers.js (rendering + legend). */
(function(root){
'use strict';
const T={
 bg:'#0B0B0B', stroke:'#0B0B0B', halo:'#0B0B0B',
 route:{selected:'#F3EFE4',halo:'#0B0B0B',alt:'#8C8C86',start:'#F5F5F2',end:'#F3EFE4'}, // warm-white walk on a dark casing (round 9)
 // Category colours for POINTS on the black basemap (round 7). Built in OKLCH at one lightness band (L .58–.66,
 // C .12–.17) so no hue shouts; no violet (it read as cheap next to the lime); warm/cool alternate in legend order.
 // Validator (dark, #000): lightness/chroma/contrast PASS, adjacent normal-vision ΔE ≥ 17.8, CVD ΔE 7.0 (secondary
 // encoding present: text legend + labels on tap). Street infrastructure and buildings stay neutral graphite.
 // Never lime (the route's colour). Large AREAS never use these saturated hues — see `area` below.
 cat:{streets:'#7d8794',buildings:'#6b7380',waterfront:'#4087de',activities:'#d67523',nature:'#54a058',environment:'#0086b3',transit:'#c5547c',heritage:'#b48c2b',services:'#00a396',safety:'#d24c49'},
 // Area treatments, after Google Maps Night Mode / Mapbox guidance: big polygons are tonal shifts of the base,
 // not saturated fills. Parks = deep moss with a fine sage edge; heritage = a brass hairline, almost no fill.
 area:{park:{fill:'#0f2018',fillOpacity:.9,line:'#2f5d43',lineOpacity:.75},district:{line:'#b48c2b',lineOpacity:.5,fillOpacity:0},landmark:{fill:'#b48c2b',fillOpacity:.09,line:'#b48c2b',lineOpacity:.6}},
 // Visual weight per point category: street infrastructure (ramps, signals, corners) recedes; destinations lead.
 weight:{streets:{size:.7,opacity:.55},services:{size:.85,opacity:.8},safety:{size:.9,opacity:.85}},
 // Zoom tiers (MapLibre zoom), tuned on Midtown screenshots: city < 13 ≤ neighbourhood < 15 ≤ street < 17 ≤ detail.
 zoom:{neighbourhood:13,street:15,detail:17},
 point:{stops:[[13,1.8],[15,2.6],[17,4],[19,6]],ring:[3.4,4.8,7,10],strokeStops:[[13,0],[15,.4],[17,.8],[19,1]]},
 tree:{radius:['interpolate',['linear'],['zoom'],12,.5,15,1.4,18,3.2],opacity:.7},
 // Clusters are crisp solid dots (not translucent rings, which stacked into a coloured haze): small at city zoom,
 // growing with zoom and record count; a black ring separates neighbours from street zoom on; street-infrastructure
 // and building records stay faint. Counts are neutral text (never the series colour) and only from z14.
 cluster:{radius:['interpolate',['linear'],['zoom'],11,['interpolate',['linear'],['get','point_count'],2,1.6,40,2.6,400,3.8],13.5,['interpolate',['linear'],['get','point_count'],2,2.4,40,3.6,400,5.2],15,['interpolate',['linear'],['get','point_count'],2,3.6,40,5.6,400,8]],
  opacity:['interpolate',['linear'],['zoom'],12,.6,15,.95],opacityNeutral:['interpolate',['linear'],['zoom'],12,.3,15,.5],strokeWidth:['interpolate',['linear'],['zoom'],12,0,14,1],
  countMinZoom:14,countText:'#c9d0d8',maxZoom:15,pixelRadius:48},
 label:{font:['Montserrat Medium','Open Sans Regular'],size:10,minZoom:17},
 building:{
  neutral:'#3E3D38',neutralLight:'#DCDBD4',outline:'#2A2926',
  heightLight:[[0,'#E6E5DF'],[40,'#DEDDD6'],[80,'#D4D3CB'],[150,'#C9C8C0'],[300,'#BCBBB3'],[600,'#AAA9A1']],fillOpacity:.62,extrusionOpacity:.84,
  // Capped below off-white: in the flat 2D fill this ramp's top end barely showed (rooftop only); extruded to full
  // height a skyscraper's whole face carries it, so a near-white top stop blew out and broke the dark theme.
  // stone greys: the 3D city must stand clear of the near-black land (the first round-9 ramp was too dark — 3D read as flat)
  height:{prop:'height_roof_ft',unit:'ft',stops:[[0,'#34332F'],[40,'#3E3D38'],[80,'#4A4943'],[150,'#58574F'],[300,'#6A685F'],[600,'#838177']]},
  age:{prop:'construction_year',unit:'year built',stops:[[1800,'#5b4636'],[1880,'#6d5a44'],[1920,'#7b6f57'],[1950,'#5e6c6c'],[1980,'#4c6879'],[2015,'#3c6489']]},
  landuse:{prop:'landuse_name',classes:[['One & two family','#6f7f5b'],['Multi-family walk-up','#857d58'],['Multi-family elevator','#8c7552'],['Mixed residential & commercial','#8e6a5c'],['Commercial & office','#7a6070'],
   ['Industrial & manufacturing','#6a5f7c'],['Transportation & utility','#5b6a80'],['Public facilities & institutions','#4f7480'],['Open space & outdoor recreation','#4f7c66'],['Parking','#5e6468'],['Vacant land','#4a4f52']],other:'#3a4247'}},
 // Noise density as a faint cool glow (one hue, brighter = denser); the old mauve→rose ramp read as a pink haze.
 env:{noise:{label:'311 noise complaint density',unit:'relative density of complaints (12 months)',ramp:[[0,'rgba(0,0,0,0)'],[.2,'rgba(40,60,90,.25)'],[.45,'rgba(55,85,125,.4)'],[.7,'rgba(70,110,160,.55)'],[.9,'rgba(90,140,200,.65)'],[1,'rgba(120,170,230,.75)']],opacity:.35,intensity:[12,.25,16,.6],radius:[12,6,16,15]}},
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
 speed_limits:{color:'#6f7884',width:[14,.5,18,1.4],opacity:.35,minzoom:14},
 expressways:{color:'#5d6672',width:[11,1,16,3],opacity:.45},
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
