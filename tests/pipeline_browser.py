"""Browser integration: AI Journey → /api/routes using a recorded real engine response (tests/fixtures). Needs Playwright."""
import asyncio, pathlib, re, os
from playwright.async_api import async_playwright
async def main():
    root=pathlib.Path(__file__).resolve().parents[1]
    async with async_playwright() as pw:
        browser=await pw.chromium.launch(headless=True,executable_path=os.environ.get('CHROME_PATH'),args=['--no-sandbox'])
        page=await browser.new_page()
        errors=[];page.on('pageerror',lambda x:errors.append(str(x)))
        await page.route('**/*',lambda route:route.abort('blockedbyclient'))
        html=(root/'index.html').read_text();html=re.sub(r'<script src="[^"]+"></script>','',html)
        html=re.sub(r'<link [^>]*href="[^"]+"[^>]*>','',html)
        await page.set_content(html)
        await page.add_style_tag(content=(root/'styles.css').read_text())
        await page.add_script_tag(content=(root/'experience-core.js').read_text())
        for name in ('api-config.js','weather.js','places.js','opening-hours.js','app.js','route-client.js','weather-ui.js','journey.js','journey-ui.js','voice.js','nav-engine.js','nav-ui.js','urban-geo.js','urban-style.js','urban-layers.js','explore-map.js','explore-analytics.js','center-map.js'):
            await page.add_script_tag(content=(root/name).read_text())
        # Serve the routing engine's recorded response in place of the server; record what the page asked for.
        fixture=(root/'tests'/'fixtures'/'route-response.json').read_text()
        await page.evaluate('''(fixture) => {
          window.routeRequests=[];
          window.fetch=async (url,opts)=>{
            if(String(url).endsWith('/api/routes')){window.routeRequests.push(JSON.parse(opts.body));return new Response(fixture,{headers:{'Content-Type':'application/json'}});}
            if(String(url).endsWith('/api/pois'))return new Response(JSON.stringify({pois:[]}),{headers:{'Content-Type':'application/json'}});
            throw new Error('blocked in test');
          };
        }''',fixture)
        # Set the scenario's 30-minute cap explicitly; do not depend on UI defaults.
        await page.locator('#customTime').fill('30')
        await page.locator('#customTime').dispatch_event('change')
        await page.locator('#generateRoutes').click()
        await page.wait_for_function('!state.routingBusy && !planner.parsing && state.routes.length>0',timeout=18000)
        result=await page.evaluate('''() => ({n:state.routes.length,best:state.activeRoute,weights:planner.weights,origins:planner.origins,budget:state.budget,poisons:planner.routePois.length,chat:planner.conversations.length})''')
        assert result['n']>=1 and result['best'] is not None,result
        assert result['weights']['Nature']>=85 and result['origins']['Nature']=='local',result
        assert result['budget']==30 and result['chat']>=2,result
        # Follow-up adjusts the existing trip duration but does not reset origin/destination.
        await page.evaluate('''() => {document.querySelector('#chatInput').value='Five more minutes, even greener.';document.querySelector('#chatForm').requestSubmit();}''')
        await page.wait_for_function('!state.routingBusy && !planner.parsing && state.budget===35 && state.routes.length>0',timeout=18000)
        follow=await page.evaluate('''() => ({start:state.start,end:state.end,budget:state.budget,number:state.routes.length,hasGeometry:state.routes.every(r=>r.coords.length>=2),asked:window.routeRequests.at(-1).constraints.max_minutes,edges:state.routes.every(r=>r.raw.ordered_edge_ids.length===r.raw.edges.length)})''')
        assert follow['start']=='bryant' and follow['end']=='rock' and follow['budget']==35,follow
        assert follow['hasGeometry'] and follow['edges'] and follow['asked']==35,follow
        assert not errors,errors
        await browser.close()
        print('PIPELINE PASS: Plan → /api/routes request → recorded engine response → Route Intelligence → follow-up re-request with the new limit')
asyncio.run(main())
