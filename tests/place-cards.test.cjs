/* DOM cards use explicit test fixtures. No mock provider response is a live call. */
const {JSDOM}=require(process.env.JSDOM_PATH||'jsdom'),fs=require('fs'),vm=require('vm'),assert=require('node:assert/strict'),path=require('path');
const dom=new JSDOM('<main id="card"></main>',{runScripts:'outside-only',url:'https://fixture.invalid/'}),w=dom.window,ctx=dom.getInternalVMContext();
vm.runInContext(`const esc=v=>String(v??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');`,ctx);
for(const f of ['journey.js','journey-ui.js','nav-ui.js'])vm.runInContext(fs.readFileSync(path.join(__dirname,'..',f),'utf8'),ctx);
const run=s=>vm.runInContext(s,ctx),card=w.document.querySelector('#card');
try{
 w.fixture={name:'Test <script>unsafe</script>',quality_status:'unverified',data_sources:['NYC DOHMH'],public_access:{basis:'Permit only; public access unverified'},opening_hours:'09:00-17:00; PH off',
  restaurant:{cuisine:'coffee',inspection:{permit:'test',grade:'A',grade_date:'2026-10-24',last_inspection:'2026-10-24'}}};
 card.innerHTML=run('typedCard(fixture)');
 assert(card.textContent.includes('not a review'));assert(card.textContent.includes('no default rating'));assert(card.textContent.includes('Item prices'));
 assert(card.textContent.includes('Permit only; public access unverified'));assert(card.textContent.includes('not live status'));assert(card.textContent.includes('holiday calendar'));
 assert(!card.querySelector('script'));assert(!/4\.8|\$\d/.test(card.textContent));
 w.fixture={quality_status:'verified',data_sources:['NYC LPC'],verification_basis:[{source:'NYC LPC',record_id:'LP-TEST',scope:'Historic property identity; not current hotel operation'}],
  hotel:{star_rating:'4',star_rating_source:'OpenStreetMap stars tag'},official_website:'javascript:alert(1)'};
 card.innerHTML=run('typedCard(fixture)');assert(card.textContent.includes('OpenStreetMap stars tag'));assert(card.textContent.includes('never mixed with stars'));
 assert(card.textContent.includes('LP-TEST'));assert(card.textContent.includes('not current hotel operation'));assert(card.textContent.includes('Unavailable until an authorized provider'));
 assert.equal(card.querySelector('a').getAttribute('href'),'#');
 assert.equal(run("freshMenuEvidence({status:'confirmed_menu_match'})"),false);
 assert.equal(run("freshMenuEvidence({status:'confirmed_menu_match',checked_at:new Date(Date.now()-13*3600000).toISOString()})"),false);
 assert.equal(run("freshMenuEvidence({status:'confirmed_menu_match',checked_at:new Date().toISOString()})"),true);
 assert.equal(run("menuEvidenceForDisplay({status:'confirmed_menu_match',price:5}).status"),'unverified');
 assert.equal(run("menuEvidenceForDisplay({status:'confirmed_menu_match',price:5}).price"),null);
 console.log('PLACE CARD DOM PASS: source scopes, public access, missing prices/reviews/rooms, safe links, menu expiry; no live provider claims');
}finally{w.close();}
