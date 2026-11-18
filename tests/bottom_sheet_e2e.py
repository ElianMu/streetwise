"""Mobile bottom-sheet acceptance test (real Chromium, touch input via CDP, iPhone-sized viewport).

Run against a running server.py:   python3 tests/bottom_sheet_e2e.py --base http://127.0.0.1:8080
In an egress-restricted sandbox add --local-maplibre <dir with maplibre-gl.js/.css> (the npm package
maplibre-gl@4.7.1 dist folder); the CARTO basemap is then replaced by a plain background.

Checks, in Navigate (route results sheet, incl. Technical details) and Map/Explore (Explore Urban Data sheet):
  1. the sheet rests exactly where a touch drag released it: 20/35/50/65/80 % and arbitrary heights;
  2. at each height the content scrolls to its very last element, which ends up fully visible above the safe area;
  3. a swipe inside the content scrolls the content and does not move the sheet;
  4. dragging does not change the content's scroll position;
  5. repeated up/down drags follow the finger without jumps;
  6. map panning in the exposed area still works and does not move the sheet;
  7. switching Navigate -> Explore -> Navigate keeps the behaviour.
"""
import argparse, json, os, re, sys, time
from playwright.sync_api import sync_playwright

BLANK_STYLE = {'version': 8, 'sources': {}, 'layers': [{'id': 'bg', 'type': 'background', 'paint': {'background-color': '#f2f2ee'}}]}
results = []


def check(group, name, ok, detail=None):
    results.append({'group': group, 'check': name, 'ok': bool(ok), 'detail': detail})
    print(('PASS ' if ok else 'FAIL ') + f'[{group}] {name}' + (f' — {detail}' if detail is not None and not ok else ''))


def touch(cdp, kind, x, y):
    cdp.send('Input.dispatchTouchEvent', {'type': kind, 'touchPoints': [] if kind == 'touchEnd' else [{'x': x, 'y': y, 'id': 1}]})


def touch_drag(page, cdp, x, y0, y1, steps=14):
    touch(cdp, 'touchStart', x, y0)
    for i in range(1, steps + 1):
        touch(cdp, 'touchMove', x, y0 + (y1 - y0) * i / steps)
        page.wait_for_timeout(16)
    touch(cdp, 'touchEnd', x, y1)


def sheet_box(page, pid):
    return page.evaluate("""(id) => { const p = document.getElementById(id), r = p.getBoundingClientRect();
        const h = p.querySelector('.sheet-handle').getBoundingClientRect();
        return { top: r.top, bottom: r.bottom, height: r.height, visible: innerHeight - r.top, vh: innerHeight,
                 handleX: h.left + h.width / 2, handleY: h.top + h.height / 2, level: p.dataset.level }; }""", pid)


def drag_sheet_to(page, cdp, pid, target_visible):
    b = sheet_box(page, pid)
    dy = b['visible'] - target_visible
    touch_drag(page, cdp, b['handleX'] - 60, b['handleY'], b['handleY'] + dy)   # off the toggle button, on the handle
    page.wait_for_timeout(450)


SCROLLER = {'rightPanel': '.right-scroll', 'exploreSheet': '.explore-sheet-scroll', 'leftPanel': '.panel-scroll'}


def last_content_reachable(page, pid, last_sel):
    """Scroll the sheet's scroller to its end and report whether last_sel is fully inside the visible scroller
    area and above the safe-area / screen bottom."""
    return page.evaluate("""([id, sc, last]) => {
        const p = document.getElementById(id), s = p.querySelector(sc), el = p.querySelector(last);
        s.scrollTop = s.scrollHeight;
        const sr = s.getBoundingClientRect(), er = el.getBoundingClientRect(), pr = p.getBoundingClientRect();
        const padB = parseFloat(getComputedStyle(p).paddingBottom) || 0;
        return { ok: er.bottom <= sr.bottom + 1 && er.top >= sr.top - 1 && sr.bottom <= innerHeight - padB + 1 && sr.height > 0,
                 scrollerBottom: Math.round(sr.bottom), lastBottom: Math.round(er.bottom), screen: innerHeight, padB,
                 scrollerH: Math.round(sr.height), scrollTop: Math.round(s.scrollTop), max: s.scrollHeight - s.clientHeight }; }""",
        [pid, SCROLLER[pid], last_sel])


def run_sheet_suite(page, cdp, group, pid, last_sel, last_label):
    vh = page.evaluate('innerHeight')
    maxh = page.evaluate("(id) => { const p = document.getElementById(id), h = p.style.height; p.style.height = ''; const m = p.offsetHeight; p.style.height = h; return m; }", pid)
    for frac in (0.2, 0.35, 0.5, 0.65, 0.8, 0.27, 0.58, 0.73):
        target = round(frac * vh)
        expect = min(target, maxh)
        drag_sheet_to(page, cdp, pid, target)
        b1 = sheet_box(page, pid)
        page.wait_for_timeout(700)
        b2 = sheet_box(page, pid)
        check(group, f'rests where released at {int(frac*100)} % ({target}px → {expect}px)', abs(b1['visible'] - expect) <= 3 and abs(b2['visible'] - b1['visible']) < 0.5,
              {'released': round(b1['visible']), 'after700ms': round(b2['visible']), 'expected': expect})
        check(group, f'bottom edge anchored to the viewport at {int(frac*100)} %', abs(b2['bottom'] - vh) <= 1, b2)
        reach = last_content_reachable(page, pid, last_sel)
        check(group, f'{last_label} fully reachable at {int(frac*100)} %', reach['ok'], reach)

    # Swipe inside the content: scrolls the content, not the sheet.
    drag_sheet_to(page, cdp, pid, round(0.5 * vh))
    page.evaluate("([id, sc]) => { document.getElementById(id).querySelector(sc).scrollTop = 0; }", [pid, SCROLLER[pid]])
    before = sheet_box(page, pid)
    sr = page.evaluate("([id, sc]) => { const r = document.getElementById(id).querySelector(sc).getBoundingClientRect(); return { x: r.left + r.width / 2, y: r.top + r.height / 2, h: r.height }; }", [pid, SCROLLER[pid]])
    touch_drag(page, cdp, sr['x'] + 40, sr['y'] + sr['h'] * 0.3, sr['y'] - sr['h'] * 0.3)
    page.wait_for_timeout(900)
    after = sheet_box(page, pid)
    st = page.evaluate("([id, sc]) => document.getElementById(id).querySelector(sc).scrollTop", [pid, SCROLLER[pid]])
    check(group, 'content swipe scrolls the content', st > 20, st)
    check(group, 'content swipe does not move the sheet', abs(after['top'] - before['top']) < 1, {'before': before['top'], 'after': after['top']})

    # Dragging the handle keeps the content's scroll position.
    page.evaluate("([id, sc]) => { document.getElementById(id).querySelector(sc).scrollTop = 150; }", [pid, SCROLLER[pid]])
    st0 = page.evaluate("([id, sc]) => document.getElementById(id).querySelector(sc).scrollTop", [pid, SCROLLER[pid]])
    drag_sheet_to(page, cdp, pid, round(0.72 * vh))
    drag_sheet_to(page, cdp, pid, round(0.41 * vh))
    st1 = page.evaluate("([id, sc]) => document.getElementById(id).querySelector(sc).scrollTop", [pid, SCROLLER[pid]])
    check(group, 'dragging does not reset the content scroll position', st0 > 0 and abs(st1 - st0) <= 1, {'before': st0, 'after': st1})

    # Repeated up/down drags: the sheet follows the finger during the move and never jumps on release.
    jumps = []
    for i in range(8):
        b = sheet_box(page, pid)
        target = round((0.3 if i % 2 else 0.7) * vh)
        dy = b['visible'] - target
        touch(cdp, 'touchStart', b['handleX'] - 60, b['handleY'])
        mids = []
        for k in range(1, 11):
            touch(cdp, 'touchMove', b['handleX'] - 60, b['handleY'] + dy * k / 10)
            page.wait_for_timeout(18)
            mids.append(round(sheet_box(page, pid)['visible']))
        touch(cdp, 'touchEnd', b['handleX'] - 60, b['handleY'] + dy)
        page.wait_for_timeout(60)
        rel = sheet_box(page, pid)['visible']
        page.wait_for_timeout(400)
        rest = sheet_box(page, pid)['visible']
        monotonic = all((mids[j + 1] - mids[j]) * (1 if dy < 0 else -1) >= -1 for j in range(len(mids) - 1))
        jumps.append({'target': min(target, maxh), 'release': round(rel), 'rest': round(rest), 'monotonic': monotonic})
    check(group, 'repeated up/down drags: follow the finger, no jump or snap', all(j['monotonic'] and abs(j['rest'] - j['target']) <= 3 and abs(j['rest'] - j['release']) <= 1 for j in jumps), jumps)

    # Map gestures in the exposed area still pan the map and leave the sheet alone.
    drag_sheet_to(page, cdp, pid, round(0.45 * vh))
    b = sheet_box(page, pid)
    c0 = page.evaluate('state.map.getCenter().toArray()')
    my = b['top'] * 0.6
    touch_drag(page, cdp, 200, my, my + 120, steps=10)
    page.wait_for_timeout(700)
    c1 = page.evaluate('state.map.getCenter().toArray()')
    b2 = sheet_box(page, pid)
    check(group, 'map pans in the exposed area', abs(c1[1] - c0[1]) > 1e-4, {'before': c0, 'after': c1})
    check(group, 'map gesture does not move the sheet', abs(b2['top'] - b['top']) < 1, {'before': b['top'], 'after': b2['top']})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--base', default='http://127.0.0.1:8080')
    ap.add_argument('--local-maplibre')
    ap.add_argument('--chrome', default=os.environ.get('CHROME_PATH'))
    ap.add_argument('--out', default='screenshots/bottom-sheet')
    ap.add_argument('--width', type=int, default=390)
    ap.add_argument('--height', type=int, default=844)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    with sync_playwright() as pw:
        gl = ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist']  # WebGL in headless Chromium
        browser = pw.chromium.launch(executable_path=a.chrome, args=gl) if a.chrome else pw.chromium.launch(args=gl)
        ctx = browser.new_context(viewport={'width': a.width, 'height': a.height}, device_scale_factor=2, is_mobile=True, has_touch=True,
                                  service_workers='block',
                                  user_agent='Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1')
        page = ctx.new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        if a.local_maplibre:
            page.route(re.compile(r'^https?://(?!localhost|127\.0\.0\.1).*'), lambda r: r.abort())
            def serve(name, ctype):  # unpkg sends ACAO: *, which crossorigin="anonymous" + SRI require
                return lambda route: route.fulfill(path=os.path.join(a.local_maplibre, name), content_type=ctype, headers={'Access-Control-Allow-Origin': '*'})
            for f, ct in (('maplibre-gl.js', 'application/javascript'), ('maplibre-gl.css', 'text/css')):
                page.route(f'**/unpkg.com/maplibre-gl@*/dist/{f}', serve(f, ct))
            page.route('**/basemaps.cartocdn.com/**/style.json', lambda r: r.fulfill(body=json.dumps(BLANK_STYLE), content_type='application/json'))
        cdp = ctx.new_cdp_session(page)
        page.goto(a.base + '/', wait_until='domcontentloaded')
        page.wait_for_function("document.body.dataset.mview === 'home' && typeof state !== 'undefined' && state.map && state.map.loaded()", timeout=60000)
        check('Setup', 'MapLibre loaded (SRI integrity accepted)', page.evaluate('typeof maplibregl !== "undefined"'))

        # Navigate: plan a real walk and open the route results sheet.
        page.click('#intentText')
        page.fill('#intentText', 'Take me from Bryant Park to Rockefeller Center on a quiet walk with interesting architecture.')
        page.click('#mCreate')
        page.wait_for_function("document.body.dataset.mview === 'results' && state.routes.length > 0", timeout=90000)
        page.wait_for_timeout(1200)
        check('Navigate', 'route results sheet open with real routes', page.evaluate("$('rightPanel').dataset.level !== 'hidden' && state.routes.length"))
        page.evaluate("$('techDetails').open = true")
        page.wait_for_timeout(300)
        drag_sheet_to(page, cdp, 'rightPanel', round(0.5 * a.height))
        page.evaluate("(() => { const s = document.querySelector('#rightPanel .right-scroll'); s.scrollTop = s.scrollHeight; })()")
        page.wait_for_timeout(300)
        page.screenshot(path=os.path.join(a.out, 'navigate-50pct-scrolled-to-end.png'))
        run_sheet_suite(page, cdp, 'Navigate', 'rightPanel', '#openMethodology', 'Technical details (to its last button)')
        drag_sheet_to(page, cdp, 'rightPanel', round(0.35 * a.height))
        page.evaluate("(() => { const s = document.querySelector('#rightPanel .right-scroll'); s.scrollTop = s.scrollHeight; })()")
        page.wait_for_timeout(300)
        page.screenshot(path=os.path.join(a.out, 'navigate-35pct-technical-details-end.png'))

        # Map mode: Explore Urban Data sheet.
        page.evaluate("$('modeExplore').click()")
        page.wait_for_function("$('exploreSheet').dataset.level && $('exploreSheet').dataset.level !== 'hidden'", timeout=30000)
        page.wait_for_function("typeof exploreMap !== 'undefined' && exploreMap.data", timeout=60000)
        page.wait_for_timeout(1500)
        # Open every collapsible section so the very last Explore content is the deepest possible element.
        page.evaluate("document.querySelectorAll('#exploreSheet details').forEach((d) => { d.open = true; })")
        page.wait_for_timeout(400)
        last_explore = page.evaluate("""(() => { const s = document.querySelector('#exploreSheet .explore-sheet-scroll');
            const all = [...s.querySelectorAll('*')].filter((e) => e.offsetParent && e.getBoundingClientRect().height > 0 && !e.children.length && !e.closest('details:not([open])'));
            const last = all.reduce((a, e) => (!a || e.getBoundingClientRect().bottom + s.scrollTop >= a.getBoundingClientRect().bottom + s.scrollTop ? e : a), null);
            last.setAttribute('data-e2e-last', '1'); return last.outerHTML.slice(0, 120); })()""")
        run_sheet_suite(page, cdp, 'Map (Explore)', 'exploreSheet', '[data-e2e-last]', 'last Explore section')
        drag_sheet_to(page, cdp, 'exploreSheet', round(0.5 * a.height))
        page.screenshot(path=os.path.join(a.out, 'explore-50pct.png'))

        # Back to Navigate: no regressions.
        page.evaluate("$('modeNavigate').click()")
        page.wait_for_timeout(800)
        if page.evaluate("$('rightPanel').dataset.level === 'hidden'"):
            page.evaluate("$('mobileResults').click()")
            page.wait_for_timeout(600)
        drag_sheet_to(page, cdp, 'rightPanel', round(0.62 * a.height))
        b = sheet_box(page, 'rightPanel')
        reach = last_content_reachable(page, 'rightPanel', '#openMethodology')
        check('Switch', 'Navigate after Explore: sheet rests where released', abs(b['visible'] - round(0.62 * a.height)) <= 3, b)
        check('Switch', 'Navigate after Explore: Technical details still reachable', reach['ok'], reach)
        check('Switch', 'no horizontal overflow', page.evaluate('document.documentElement.scrollWidth - innerWidth') <= 1)
        check('Setup', 'no uncaught page errors', not errors, errors)
        browser.close()
    passed = sum(r['ok'] for r in results)
    json.dump({'passed': passed, 'total': len(results), 'results': results}, open(os.path.join(a.out, 'report.json'), 'w'), indent=1)
    print(f'BOTTOM SHEET E2E: {passed}/{len(results)} passed')
    sys.exit(0 if passed == len(results) else 1)


if __name__ == '__main__':
    main()
