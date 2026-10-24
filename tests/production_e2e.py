"""Actual production smoke/E2E checks. No network mocking or synthetic GPS fixes.

Default: public status, memory, desktop/mobile maps, 13 Explore views, source
cards, refresh/offline recovery. --live-ai additionally makes two billable real
AI route requests. A physical walking/GPS field test remains BLOCKED.
"""
import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import urllib.request
from playwright.async_api import async_playwright

SITE='https://elianmu.github.io/streetwise/'
API='https://streetwise-api.onrender.com'


def http_json(url, body=None):
    cmd=['curl','-sS','--max-time','55','-w','\n%{http_code}','-H','Origin: https://elianmu.github.io',url]
    if body is not None:cmd+=['-H','Content-Type: application/json','--data-binary','@-']
    r=subprocess.run(cmd,input=json.dumps(body) if body is not None else None,text=True,capture_output=True,timeout=60)
    if r.returncode:raise RuntimeError('HTTP transport failed: '+r.stderr[:250])
    text,status=r.stdout.rsplit('\n',1)
    return int(status),json.loads(text)


async def browser_checks(args,receipt):
    async with async_playwright() as p:
        proxy=urllib.request.getproxies().get('https')
        browser=await p.chromium.launch(executable_path=os.environ.get('CHROME_PATH') or None,
            proxy={'server':proxy} if proxy else None,headless=True,
            args=['--no-sandbox','--use-angle=swiftshader','--enable-unsafe-swiftshader'])
        for mobile in (False,True):
            name='mobile_emulation' if mobile else 'desktop'
            context=await browser.new_context(viewport={'width':390,'height':844} if mobile else {'width':1440,'height':1000},is_mobile=mobile,has_touch=mobile)
            page=await context.new_page();errors=[];api=[];food_downloads=[]
            page.on('pageerror',lambda e:errors.append(str(e)))
            page.on('response',lambda r:api.append({'path':r.url.split('/api/')[-1],'status':r.status}) if '/api/' in r.url else None)
            page.on('request',lambda r:food_downloads.append(r.url) if '/data/places/restaurants.json' in r.url else None)
            stage={'status':'FAIL','scope':'Chromium touch emulation, not physical GPS/device validation' if mobile else 'actual Chromium browser and public production sources'}
            receipt[name]=stage
            try:
                response=await page.goto(SITE,wait_until='domcontentloaded',timeout=60000)
                assert response.status==200
                await page.wait_for_function('state.mapLayersReady && urbanData.catalog',timeout=60000)
                await page.wait_for_function("state.map.queryRenderedFeatures().some(f=>f.source==='protomaps')",timeout=45000)
                assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth+2')
                before=await page.evaluate('state.map.getCenter().toArray()')
                await page.mouse.move(160 if mobile else 700,370);await page.mouse.down()
                await page.mouse.move(220 if mobile else 770,420,steps=10);await page.mouse.up()
                await page.wait_for_timeout(400)
                assert before!=await page.evaluate('state.map.getCenter().toArray()')
                await page.evaluate('state.map.zoomTo(15,{duration:0})')
                assert await page.evaluate('state.map.getZoom()')==15
                stage.update(map_loaded=True,basemap='actual CARTO/protomaps vector features rendered',drag=True,zoom=True,horizontal_overflow=False)
                if args.live_ai:
                    if mobile:await page.locator('#mobilePlan').click()
                    await page.locator('#intentText').fill('Find me a quiet walking route with more trees and fewer busy streets.')
                    await page.locator('#generateRoutes').scroll_into_view_if_needed();await page.locator('#generateRoutes').click()
                    await page.wait_for_function('!planner.parsing&&!state.routingBusy&&state.routes.length>0',timeout=95000)
                    result=await page.evaluate('''()=>({mode:planner.interpretation,weights:planner.weights,directions:planner.directions,
                        source:document.querySelector('#interpretMode').textContent,used:planner.routeResponse.preferences_used,
                        route:state.routes[0].raw,interests:journey.interests,food:journey.food})''')
                    assert result['mode']=='llm',result['mode']
                    assert not result['interests'] and not result['food'],'Unrequested visits were inserted'
                    for dimension in ('Nature','Quiet & Relax','Urban Vibrancy'):
                        assert result['weights'][dimension]>0
                        assert result['used'][dimension]['weight']==result['weights'][dimension]
                    assert result['directions']['Urban Vibrancy']=='low'
                    assert len(result['route']['dimension_scores'])==12
                    assert result['route']['ordered_edge_ids'] and result['route']['distance_m']>0
                    await page.wait_for_function("state.map.queryRenderedFeatures({layers:['route-selected']}).length>0",timeout=30000)
                    stage['real_ai_route']={'status':'PASS','weights':result['weights'],'directions':result['directions'],
                        'preferences_used':result['used'],'distance_m':result['route']['distance_m'],
                        'geometry_sha256':hashlib.sha256(json.dumps(result['route']['geometry']).encode()).hexdigest()}
                    if not mobile:
                        # Chromium permission denial is an error-path check, not real GPS tracking.
                        session=await context.new_cdp_session(page)
                        await session.send('Browser.setPermission',{'permission':{'name':'geolocation'},'setting':'denied','origin':'https://elianmu.github.io'})
                        await page.evaluate('startNavigation()')
                        assert 'permission was denied' in await page.locator('#toast').text_content()
                        stage['gps_permission_denied_browser']='PASS'
                    if mobile:await page.locator('#mobilePlan').click()
                else:stage['real_ai_route']={'status':'BLOCKED','reason':'Live AI calls require explicit --live-ai; never replaced by mocks'}
                await page.locator('#modeExplore').click()
                await page.wait_for_function('exploreMap.data',timeout=45000)
                count=await page.evaluate('''()=>{let n=0;for(let i=0;i<13;i++){selectExploreView(i);selectExploreSegment(exploreMap.data.features[0].properties.id);
                    if(!document.querySelector('#exploreInspector').classList.contains('hidden')&&JSON.stringify(state.map.getPaintProperty('explore-streets','line-color')).includes('"'+exploreView().prop+'"'))n++;}return n}''')
                assert count==13
                stage['experience_maps_and_inspector']=count
                # Actual nearby API, not a downloaded full restaurant file.
                nearby=await page.evaluate("async()=>{const d=await foodRecordsNearPath(['restaurants'],[{lat:40.7536,lon:-73.9832}],1.2,null);return {count:d.length,ids:d.map(p=>p.id)}}")
                assert nearby['count']>0
                assert not food_downloads,'Nearby search downloaded the full restaurant snapshot'
                stage['nearby_food_search']={'status':'PASS','returned':nearby['count'],'full_restaurant_downloads':len(food_downloads)}
                # Public production cards use actual existing source records.
                cards=await page.evaluate('''async()=>{const a=await placeDetails('dohmh:50181591'),h=await placeDetails('osm:way/266170533');
                    return {permit:a.public_access,permit_date:a.last_verified_at,hotel:h.quality_status,basis:h.verification_basis,hotel_html:typedCard(h),permit_html:typedCard(a)}}''')
                assert not cards['permit']['recommendation_eligible'] and cards['permit_date'] is None
                assert cards['hotel']=='verified' and any(b['source']=='NYC LPC' for b in cards['basis'])
                assert 'not current hotel operation' in cards['hotel_html'] and 'public-facing' in cards['permit_html']
                stage['source_cards']='PASS'
                await page.screenshot(path=str(args.output/(name+'.png')),full_page=False)
                await page.reload(wait_until='domcontentloaded');await page.wait_for_function('state.mapLayersReady',timeout=60000)
                await context.set_offline(True)
                rejected=await page.evaluate("async()=>{try{await streetwiseJson('/api/status',{signal:AbortSignal.timeout(3000)});return false}catch{return true}}")
                assert rejected
                await context.set_offline(False);await page.evaluate('checkInterpreter()')
                assert await page.evaluate('planner.llmConnected')
                assert not errors,errors
                stage.update(status='PASS',refresh=True,offline_rejected=True,recovered=True,page_errors=errors,api_responses=api)
            except Exception as e:
                stage['error']=type(e).__name__+': '+str(e)[:800]
                stage['page_errors']=errors
                try:await page.screenshot(path=str(args.output/(name+'-failure.png')))
                except Exception:pass
                raise
            finally:await context.close()
        await browser.close()


async def main(args):
    args.output.mkdir(parents=True,exist_ok=True)
    receipt={'status':'FAIL','started_at':time.time(),'live_ai_requested':args.live_ai,
             'physical_gps':{'status':'BLOCKED','reason':'No physical mobile device or walking field test in this cloud environment'}}
    try:
        code,before=await asyncio.to_thread(http_json,API+'/api/status')
        assert code==200
        if args.expected_commit:assert before['deployment_commit']==args.expected_commit,'Render commit mismatch'
        assert before['process_memory']['VmRSS_kib']<448*1024,'RSS headroom alert'
        assert before['cgroup_memory']['events']['oom_kill']==0,'OOM alert'
        receipt['before']=before
        if args.expected_commit:
            hashes={}
            for filename in ('app.js','journey.js','journey-ui.js'):
                bodies=[]
                for url in (SITE+filename+'?acceptance='+args.expected_commit, 'https://raw.githubusercontent.com/ElianMu/streetwise/'+args.expected_commit+'/'+filename):
                    r=subprocess.run(['curl','-fsS','--max-time','45',url],capture_output=True,timeout=50);assert r.returncode==0,'Frontend version download failed';bodies.append(r.stdout)
                assert bodies[0]==bodies[1],'GitHub Pages version mismatch: '+filename
                hashes[filename]=hashlib.sha256(bodies[0]).hexdigest()
            receipt['frontend_commit_verified']={'commit':args.expected_commit,'file_sha256':hashes}
        await browser_checks(args,receipt)
        code,after=await asyncio.to_thread(http_json,API+'/api/status')
        assert code==200 and after['process_started_at']==before['process_started_at'],'Server restarted during acceptance'
        assert after['process_memory']['VmRSS_kib']<448*1024
        assert after['cgroup_memory']['events']['oom_kill']==0
        receipt.update(status='PASS',after=after)
    except Exception as e:
        receipt['error']=type(e).__name__+': '+str(e)[:800]
        raise
    finally:
        receipt['completed_at']=time.time()
        (args.output/'acceptance.json').write_text(json.dumps(receipt,indent=2)+'\n')
        print(json.dumps({k:v for k,v in receipt.items() if k not in ('before','after')},indent=2),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live-ai',action='store_true')
    parser.add_argument('--expected-commit',default='')
    parser.add_argument('--output',type=Path,default=Path('/tmp/streetwise-production-acceptance'))
    asyncio.run(main(parser.parse_args()))
