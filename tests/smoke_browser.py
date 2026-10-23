"""Runs against server.py listening on port 8092. Third-party traffic blocked on purpose:
no test data is ever displayed as real urban data in the user-facing release."""
import asyncio, pathlib, re, os
from playwright.async_api import async_playwright

async def run():
    async with async_playwright() as pw:
        browser=await pw.chromium.launch(headless=True,executable_path=os.environ.get('CHROME_PATH'),args=['--no-sandbox'])
        page=await browser.new_page(viewport={'width':1600,'height':900})
        errors=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        async def intercept(route):
            url=route.request.url
            if url.startswith('http://127.0.0.1:8092/'):
                await route.continue_()
            else:await route.abort('blockedbyclient')
        await page.route('**/*',intercept)
        root=pathlib.Path(__file__).resolve().parents[1]
        html=(root/'index.html').read_text()
        html=re.sub(r'<script src=\"[^\"]+\"></script>','',html)
        html=re.sub(r'<link [^>]*(?:href=\"https?://[^\"]+\"|href=\"\./styles\.css\")[^>]*/?>','',html)
        await page.set_content(html,wait_until='domcontentloaded')
        await page.add_style_tag(content=(root/'styles.css').read_text())
        await page.add_script_tag(content=(root/'experience-core.js').read_text())
        for name in ('app.js','route-client.js','explore-map.js','center-map.js'):
            await page.add_script_tag(content=(root/name).read_text())
        await page.wait_for_timeout(500)
        assert await page.locator('#openMethodology').count()==1
        assert await page.locator('#poiList').count()==1
        assert await page.locator('.profile-toggle button').count()==2
        dims=await page.evaluate('DIMENSIONS.map(x=>x.name)')
        assert len(dims)==12 and dims[10]=='Environment' and dims[11]=='Transit Connectivity',dims
        parsed=await page.evaluate("localInterpret('Make it greener and less crowded within 30 minutes')")
        assert parsed['weights']['Nature']==90 and parsed['weights']['Urban Vibrancy']==90,parsed
        assert parsed['directions']['Urban Vibrancy']=='low',parsed
        assert parsed['time_minutes']==30,parsed
        modified=await page.evaluate('''() => {
            const result=applyInterpretation({weights:{Nature:90},directions:{Nature:'high'},time_minutes:78,constraints:{}},'local');
            return {budget:state.budget,range:document.getElementById('timeRange').value,custom:document.getElementById('customTime').value,weight:planner.weights.Nature,dir:planner.directions.Nature};
        }''')
        assert modified['budget']==78 and modified['custom']=='78',modified
        assert modified['weight']==90 and modified['dir']=='high',modified
        fixture=(root/'tests'/'fixtures'/'route-response.json').read_text()
        ranked=await page.evaluate('''(fixture) => {
            applyRouteResponse(JSON.parse(fixture));renderRouteCards();updateProfile();updateWhyRoute();renderRouteEdges();
            return {best:state.activeRoute,profile:document.querySelectorAll('#profileChart .experience-row').length,reason:document.getElementById('whyRoute').innerText,edges:document.querySelectorAll('#routeEdgeList .edge-row').length};
        }''',fixture)
        assert ranked['best'] and ranked['profile']==12 and ranked['edges']>0,ranked
        assert 'Personalized score' in ranked['reason'],ranked
        block=await page.evaluate('''async () => {
            planner.constraints.stepFree=true;await generateRoutes();return {routes:state.routes.length,text:document.getElementById('rankingStatus').textContent};
        }''')
        assert block['routes']==0 and 'Step-free' in block['text'],block
        await page.locator('#openMethodology').click()
        assert await page.locator('#modalOverlay').is_visible()
        assert 'Two layers, one score definition' in await page.locator('#modalContent').inner_text()
        await page.locator('#closeModal').click()
        assert not errors, errors
        await page.screenshot(path='/tmp/streetwise_ui_smoke.png',full_page=False)
        await browser.close()
        print('BROWSER SMOKE PASS: DOM, parser, expanded time, 12 dimensions, engine route rendering, step-free block, methodology; 0 page exceptions')

asyncio.run(run())
