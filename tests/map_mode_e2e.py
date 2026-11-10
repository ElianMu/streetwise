"""Map Mode end-to-end check: the numbers drawn and shown in the browser equal the GIS pipeline output.

  python3 -m http.server 8080 &            # from the repo root (Map Mode only needs static files)
  python3 tests/map_mode_e2e.py --url http://localhost:8080 --out screenshots/map-mode

Offline/sandboxed runs: --local-maplibre DIR serves maplibre-gl from node_modules and swaps the CARTO basemap
for a blank dark style (streets, scores and panels are unaffected).
"""
import argparse, json, math, os, random, re, sys
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BLANK_STYLE = {'version': 8, 'sources': {}, 'layers': [{'id': 'bg', 'type': 'background', 'paint': {'background-color': '#0d1517'}}]}


def expected(area):
    d = json.load(open(os.path.join(ROOT, 'data', 'dimensions', area, 'indicators.json')))
    fc = json.load(open(os.path.join(ROOT, 'data', 'dimensions', area, 'segments.geojson')))
    m = json.load(open(os.path.join(ROOT, 'data', 'dimensions', area, 'manifest.json')))
    return d, {f['properties']['id']: f['properties'] for f in fc['features']}, m


def fmt_raw(v, unit):  # mirror of indicatorValue() in explore-map.js
    if v is None:
        return 'N/A'
    if unit == 'share 0–1':
        return f'{v:.2f} ({int(math.floor(v * 100 + .5))}%)'
    if unit in ('m', 'ft', 'count', 'people/h'):
        return f'{int(math.floor(v + .5)):,} {unit}'
    s = f'{v:,.2f}'.rstrip('0').rstrip('.')
    return f'{s} {unit}'


def same_raw(shown, v, unit):
    """Displayed value equals the pipeline value at display precision (JS and Python round .5 cases differently)."""
    if v is None:
        return shown == 'N/A'
    m = re.match(r'-?[\d,]*\.?\d+', shown)
    if not m:
        return False
    got = float(m.group(0).replace(',', ''))
    tol = 0.5 if unit in ('m', 'ft', 'count', 'people/h') else 0.005
    return abs(got - v) <= tol + 1e-9


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--url', default='http://localhost:8080')
    ap.add_argument('--out', default=os.path.join(ROOT, 'screenshots', 'map-mode'))
    ap.add_argument('--local-maplibre')
    ap.add_argument('--chrome')
    ap.add_argument('--samples', type=int, default=40)
    ap.add_argument('--theme', choices=['light', 'dark'], help='map theme to test (default: the app default)')
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    report = {'checks': [], 'failures': []}

    def check(name, ok, detail=''):
        report['checks'].append({'name': name, 'ok': bool(ok), 'detail': detail})
        if not ok:
            report['failures'].append(f'{name}: {detail}')
        print(('PASS ' if ok else 'FAIL ') + name + (f' — {detail}' if detail else ''), flush=True)

    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=a.chrome, args=['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader']) if a.chrome else p.chromium.launch()
        page = b.new_page(viewport={'width': 1440, 'height': 900}, device_scale_factor=1.5)
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        if a.local_maplibre:
            dist = os.path.join(a.local_maplibre, 'node_modules', 'maplibre-gl', 'dist')
            # Playwright gives the most recently registered route priority: the catch-all goes first.
            page.route(re.compile(r'^https?://(?!localhost|127\.0\.0\.1).*'), lambda r: r.abort())
            page.route('**/unpkg.com/maplibre-gl@*/dist/maplibre-gl.js', lambda r: r.fulfill(path=os.path.join(dist, 'maplibre-gl.js'), content_type='application/javascript'))
            page.route('**/unpkg.com/maplibre-gl@*/dist/maplibre-gl.css', lambda r: r.fulfill(path=os.path.join(dist, 'maplibre-gl.css'), content_type='text/css'))
            blank = json.loads(json.dumps(BLANK_STYLE)); blank['layers'][0]['paint']['background-color'] = '#f2f2ee' if a.theme != 'dark' else '#0d1517'
            page.route('**/basemaps.cartocdn.com/**/style.json', lambda r: r.fulfill(body=json.dumps(blank), content_type='application/json'))
        if a.theme:
            page.add_init_script(f"try{{localStorage.setItem('strollane.mapTheme','{a.theme}')}}catch(e){{}}")
        page.goto(a.url + '/index.html', wait_until='domcontentloaded')
        page.wait_for_function('typeof state !== "undefined" && state.mapLayersReady === true', timeout=60000)
        page.click('#modeExplore')
        page.wait_for_function('exploreMap.data && exploreMap.manifest', timeout=60000)
        area = page.evaluate('exploreMap.manifest.area')
        D, P, M = expected(area)
        check('map mode loads computed data', True, f'area={area}, segments={page.evaluate("exploreMap.data.features.length")}, calc={page.evaluate("exploreMap.manifest.calculation_version")}')
        check('front end reads the same build as the GIS output', page.evaluate('exploreMap.manifest.calculation_version') == M['calculation_version'] == D['calculation_version'])

        # 1) every dimension score on the map layer source equals the pipeline GeoJSON written by Python
        src = page.evaluate('Object.fromEntries(exploreMap.data.features.map(f=>[f.properties.id,[...Array(12).keys()].map(j=>f.properties["d"+j])]))')
        mism = [(i, j) for i, row in src.items() for j in range(12) if row[j] != P[i][f'd{j}']]
        check('all 12 × N dimension scores on the map equal the pipeline output', not mism and len(src) == len(P), f'{len(src)} segments × 12, mismatches={len(mism)}')

        # 2) the colour drawn for a segment is the ramp colour of its score; N/A gets the N/A style
        page.evaluate('state.map.fitBounds([[-73.995,40.748],[-73.970,40.765]],{duration:0})')
        page.wait_for_timeout(2500)
        colour_ok = page.evaluate('''() => {
          const v=exploreView(); const fs=state.map.queryRenderedFeatures({layers:['explore-streets']}).slice(0,300);
          const toRgb=c=>{const s=String(exploreColor(c)); if(s.startsWith('rgb'))return s.match(/\\d+/g).map(Number); return [1,3,5].map(k=>parseInt(s.slice(k,k+2),16));};
          let bad=0; for(const f of fs){const c=f.layer.paint['line-color']; const got=[c.r*255,c.g*255,c.b*255].map(Math.round); const exp=toRgb(f.properties[v.prop]);
            if(got.some((x,i)=>Math.abs(x-exp[i])>3))bad++;} return {n:fs.length,bad};}''')
        check('rendered line colour = ramp colour of the segment score (Nature)', colour_ok['n'] > 50 and colour_ok['bad'] == 0, json.dumps(colour_ok))

        # 3) Street Details panel shows the pipeline raw and normalized values
        rnd = random.Random(7)
        ids = rnd.sample(sorted(P), a.samples)
        for view_idx, dim_key in ((2, 'nature'), (1, 'architecture'), (10, 'access_safety'), (5, 'spatial_comfort'), (11, 'environment'), (0, None)):
            page.evaluate(f'selectExploreView({view_idx})')
            dim_i = view_idx - 1
            bad = 0
            for sid in ids[: a.samples // 4]:
                page.evaluate(f'selectExploreSegment({json.dumps(sid)})')
                page.wait_for_function('!document.querySelector("#exploreInspector [data-k=loading]")', timeout=20000)
                shown = page.inner_text('#exploreInspector [data-k=dimension-score]').strip()
                exp_score = P[sid]['overall'] if dim_key is None else P[sid][f'd{dim_i}']
                if shown != ('N/A' if exp_score is None else str(int(math.floor(exp_score + .5)))):
                    bad += 1; print('  score', sid, shown, exp_score)
                if dim_key:
                    k = D['ids'].index(sid)
                    for ind in [x for x in M['indicators'] if x['dimension'] == dim_key and x['status'] == 'computed']:
                        raw = page.inner_text(f'#exploreInspector .indicator[data-key="{ind["key"]}"] [data-k=raw]').strip()
                        if not same_raw(raw, D['raw'][ind['key']][k], ind['unit']):
                            bad += 1; print('  raw', sid, ind['key'], raw, D['raw'][ind['key']][k])
                        if ind['role'] in ('up', 'down'):
                            pct = page.inner_text(f'#exploreInspector .indicator[data-key="{ind["key"]}"] [data-k=pct]').strip()
                            ev = D['pct'][ind['key']][k]
                            if pct != ('N/A' if ev is None else (str(int(ev)) if float(ev).is_integer() else str(ev))):
                                bad += 1; print('  pct', sid, ind['key'], pct, ev)
            check(f'Street Details panel = GIS output ({dim_key or "overall"})', bad == 0, f'{a.samples // 4} segments, mismatches={bad}')

        # screenshots for the report
        page.evaluate('selectExploreSegment(null)')
        for idx, name in ((2, 'nature'), (1, 'architecture'), (3, 'culture'), (9, 'walkability'), (10, 'access-safety'), (12, 'transit')):
            page.evaluate(f'selectExploreView({idx}); state.map.fitBounds(MANHATTAN_BOUNDS,{{padding:{{top:30,bottom:40,right:60,left:300}},duration:0,maxZoom:12}})')
            page.wait_for_timeout(1800)
            page.screenshot(path=os.path.join(a.out, f'{idx:02d}-{name}-manhattan.png'))
        page.evaluate('selectExploreView(2); state.map.fitBounds([[-73.992,40.750],[-73.972,40.762]],{duration:0})')
        page.wait_for_timeout(1500)
        mid = page.evaluate('exploreMap.data.features.find(f=>f.properties.name&&/5 AV|FIFTH/.test(f.properties.name)&&f.properties.d1!=null&&f.geometry.coordinates[0][1]>40.753&&f.geometry.coordinates[0][1]<40.759)?.properties.id')
        page.evaluate(f'selectExploreSegment({json.dumps(mid)})')
        page.wait_for_function('!document.querySelector("#exploreInspector [data-k=loading]")', timeout=20000)
        page.wait_for_timeout(600)
        page.screenshot(path=os.path.join(a.out, '02b-nature-midtown-street-details.png'))
        page.evaluate('selectExploreSegment(null)')
        page.evaluate('selectExploreView(11); state.map.fitBounds(MANHATTAN_BOUNDS,{padding:{top:30,bottom:40,right:60,left:300},duration:0,maxZoom:12})')
        page.wait_for_timeout(1800)
        page.screenshot(path=os.path.join(a.out, '11-environment-no2-context.png'))
        check('no JavaScript errors', not errors, '; '.join(errors[:3]))
        b.close()
    json.dump(report, open(os.path.join(a.out, 'e2e_report.json'), 'w'), indent=1)
    print(f"\n{len(report['checks']) - len(report['failures'])}/{len(report['checks'])} checks passed")
    return 1 if report['failures'] else 0


if __name__ == '__main__':
    sys.exit(main())
