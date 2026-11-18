"""Start / destination acceptance test (real Chromium, phone viewport, real server.py + routing engine).

  python3 tests/ends_e2e.py --base http://127.0.0.1:8080 [--local-maplibre DIR] [--chrome PATH]

No preset start or destination: the start is what the request names, otherwise the user's location (GPS); a
request without a destination gets a recommended walk (open-ended, or back to the start for "around here").
The LLM is not configured in this test, so the clearly-labelled local interpreter reads the requests.
"""
import argparse, json, os, re, sys
from playwright.sync_api import sync_playwright

BLANK_STYLE = {'version': 8, 'sources': {}, 'layers': [{'id': 'bg', 'type': 'background', 'paint': {'background-color': '#f2f2ee'}}]}
UNION_SQ = {'latitude': 40.7359, 'longitude': -73.9903}
results = []


def check(group, name, ok, detail=None):
    results.append({'group': group, 'check': name, 'ok': bool(ok), 'detail': detail})
    print(('PASS ' if ok else 'FAIL ') + f'[{group}] {name}' + (f' — {detail}' if detail is not None and not ok else ''))


def new_page(browser, a, geo):
    ctx = browser.new_context(viewport={'width': 390, 'height': 844}, device_scale_factor=2, is_mobile=True, has_touch=True,
                              service_workers='block', permissions=['geolocation'] if geo else [], geolocation=geo)
    page = ctx.new_page()
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)))
    if a.local_maplibre:
        page.route(re.compile(r'^https?://(?!localhost|127\.0\.0\.1).*'), lambda r: r.abort())
        def serve(name, ctype):
            return lambda route: route.fulfill(path=os.path.join(a.local_maplibre, name), content_type=ctype, headers={'Access-Control-Allow-Origin': '*'})
        for f, ct in (('maplibre-gl.js', 'application/javascript'), ('maplibre-gl.css', 'text/css')):
            page.route(f'**/unpkg.com/maplibre-gl@*/dist/{f}', serve(f, ct))
        page.route('**/basemaps.cartocdn.com/**/style.json', lambda r: r.fulfill(body=json.dumps(BLANK_STYLE), content_type='application/json'))
    page.goto(a.base + '/', wait_until='domcontentloaded')
    page.wait_for_function("document.body.dataset.mview === 'home' && typeof state !== 'undefined' && state.map && state.map.loaded()", timeout=60000)
    page.wait_for_timeout(1500)
    return ctx, page, errors


def ask(page, text, wait_ms=90000):
    if not page.locator('#intentText').is_visible() and page.locator('#mCompactEdit').is_visible():
        page.click('#mCompactEdit')   # results view: the composer is collapsed into its compact bar
        page.wait_for_timeout(300)
    page.click('#intentText')
    page.fill('#intentText', text)
    page.click('#mCreate')
    page.wait_for_function("!document.body.dataset.mview || ['results', 'home'].includes(document.body.dataset.mview) && !state.routingBusy && !planner.parsing && $('mCreate') && !$('mCreate').disabled", timeout=wait_ms)
    page.wait_for_timeout(800)
    return page.evaluate("""() => ({ view: document.body.dataset.mview, routes: state.routes.length, start: state.start, startName: getPlace('start')?.name || null,
        end: getPlace('end')?.name || null, endMode: journey.endMode, interests: [...journey.interests], auto: [...journey.autoInterests],
        stops: (journey.plan?.stops || []).map((s) => s.name), planEnd: journey.plan?.end_mode || null, status: $('mStatus').innerText,
        chat: planner.conversations.filter((m) => m.role === 'assistant').slice(-3).map((m) => m.content) })""")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--base', default='http://127.0.0.1:8080')
    ap.add_argument('--local-maplibre')
    ap.add_argument('--chrome', default=os.environ.get('CHROME_PATH'))
    a = ap.parse_args()
    gl = ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist']
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=a.chrome, args=gl) if a.chrome else pw.chromium.launch(args=gl)

        # 1. Location allowed (Union Square): default start = my location, no destination preset.
        ctx, page, errors = new_page(browser, a, UNION_SQ)
        home = page.evaluate("() => ({ start: state.start, end: state.end, s: $('searchStart').value, e: $('searchEnd').value, endSel: $('endSelect').value })")
        check('Defaults', 'start defaults to my location (GPS)', home['start'] == 'gps', home)
        check('Defaults', 'no preset destination (no Columbia, no Bryant Park)', home['end'] is None and home['e'] == '' and home['endSel'] == '', home)
        check('Defaults', 'Columbia is not a quick-pick default anywhere', page.evaluate("![...document.querySelectorAll('option')].some((o) => /Columbia/.test(o.textContent) && o.selected)"))

        r = ask(page, 'A quiet walk with interesting architecture.')
        check('No destination', 'a recommended walk is planned (not a question, not an error)', r['view'] == 'results' and r['routes'] > 0, r)
        check('No destination', 'starts at my location', r['start'] == 'gps', r)
        check('No destination', 'open end, stops chosen from the priorities (parks / historic)', r['planEnd'] == 'open' and set(r['auto']) <= {'parks', 'historic'} and r['auto'], r)
        check('No destination', 'stops are real places on the plan', len(r['stops']) >= 2, r['stops'])
        check('No destination', 'explains the recommendation', any('No destination given' in c for c in r['chat']), r['chat'])
        ctx.close()

        ctx, page, errors2 = new_page(browser, a, UNION_SQ)
        r = ask(page, 'Walk to the Metropolitan Museum')
        check('Destination only', 'start = my location, destination from the text', r['start'] == 'gps' and r['end'] and 'Metropolitan' in r['end'] and r['routes'] > 0, r)
        check('Destination only', 'no recommended stops added when a destination is given', not r['auto'], r)
        ctx.close()

        ctx, page, errors3 = new_page(browser, a, UNION_SQ)
        r = ask(page, 'From Washington Square Park to Bryant Park')
        check('From and to', 'both ends read from the text', r['startName'] and 'Washington Square' in r['startName'] and r['end'] and 'Bryant' in r['end'] and r['routes'] > 0, r)
        ctx.close()

        ctx, page, errors4 = new_page(browser, a, UNION_SQ)
        r = ask(page, '推荐一条附近散步的路线')
        check('Around here', 'a loop back to the start from my location', r['view'] == 'results' and r['planEnd'] == 'round' and r['start'] == 'gps' and r['routes'] > 0, r)
        ctx.close()

        ctx, page, errors5 = new_page(browser, a, UNION_SQ)
        r = ask(page, 'Start at Bryant Park and show me some museums')
        check('Start only + interest', 'start from the text, museums on an open-ended walk', r['startName'] == 'Bryant Park' and r['planEnd'] == 'open' and 'museums' in r['interests'] and not r['auto'] and r['routes'] > 0, r)
        # follow-up with a destination: our own recommendation would be dropped, the user's interest stays
        ctx.close()

        ctx, page, errors6 = new_page(browser, a, UNION_SQ)
        r = ask(page, 'A green walk with lots of trees')
        r2 = ask(page, 'Actually, end at Grand Central Terminal')
        check('Follow-up destination', 'a later destination replaces the recommended open end', r2['end'] and 'Grand Central' in r2['end'] and r2['endMode'] == 'fixed' and not r2['auto'] and r2['routes'] > 0, {'first': r, 'second': r2})
        ctx.close()

        # 2. Location refused and no start named: ask, with the ways to give a start.
        ctx, page, errors7 = new_page(browser, a, None)
        r = ask(page, 'A quiet walk with interesting architecture.', wait_ms=40000)
        check('No location', 'no route invented without a start', r['routes'] == 0 and r['start'] is None, r)
        check('No location', 'asks where to start, offers "Use my location"', 'start' in r['status'].lower() and page.locator('#mStatus button', has_text='Use my location').count() == 1, r['status'])
        r = ask(page, 'From Union Square, a walk with nice architecture')
        check('No location', 'a start named in the request works without GPS', r['startName'] and 'Union Square' in r['startName'] and r['routes'] > 0 and r['planEnd'] == 'open', r)
        ctx.close()

        all_errors = errors + errors2 + errors3 + errors4 + errors5 + errors6 + errors7
        check('Setup', 'no uncaught page errors', not all_errors, all_errors)
        browser.close()
    passed = sum(r['ok'] for r in results)
    print(f'ENDS E2E: {passed}/{len(results)} passed')
    sys.exit(0 if passed == len(results) else 1)


if __name__ == '__main__':
    main()
