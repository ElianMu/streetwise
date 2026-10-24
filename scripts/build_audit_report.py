"""DATA_AUDIT_REPORT.md (+ data/audit.json): an audit of the data STREETWISE actually ships and uses, computed from the files.

Reads data/registry.json (scripts/build_registry.py) and the discovery index, then checks the code for hard-coded places,
placeholder or simulated data, unreferenced data files, and which agent tools really read data. Nothing is estimated.
Run after build_registry.py:  python3 scripts/build_audit_report.py
"""
import glob, json, math, os, re
from collections import Counter
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D = lambda *p: os.path.join(ROOT, 'data', *p)
RUNTIME = ['app.js', 'route-client.js', 'center-map.js', 'explore-map.js', 'explore-analytics.js', 'urban-layers.js', 'journey.js', 'journey-ui.js',
           'places.js', 'weather.js', 'weather-ui.js', 'nav-engine.js', 'nav-ui.js', 'voice.js', 'server.py'] + glob.glob(os.path.join(ROOT, 'routing', '*.py'))


def quality(r):
    """Rule-based quality label from measured counts (not an opinion)."""
    n, v = r.get('feature_count'), r.get('valid_geometry_count')
    st = r.get('integration_status') or ''
    if not st.startswith('connected'):
        return 'n/a (blocked by provider access)' if st == 'blocked_by_provider_access' else 'n/a (not connected)'
    if st != 'connected':
        return 'measured in its connected row'
    if not n:
        return 'unmeasured'
    worst_missing = max((r.get('missing_fields') or {}).values(), default=0)
    valid = (v / n) if v is not None else 1
    if valid < .99:
        return f'limited (valid geometry {valid:.1%})'
    if worst_missing > .5:
        return f'fair (a field missing in {worst_missing:.0%})'
    return 'good'


def main():
    reg = json.load(open(D('registry.json')))
    idx = json.load(open(D('places', 'index.json')))
    rows = reg['datasets']
    # hard-coded quick-pick places: compare with the nearest same-name record in the discovery index
    src = open(os.path.join(ROOT, 'app.js')).read()
    presets = re.findall(r"(\w+):\s*\{\s*name:\s*'([^']+)',\s*lon:\s*(-?[\d.]+),\s*lat:\s*(-?[\d.]+)", src)
    allrec = [r for c in idx['categories'] for r in json.load(open(D('places', c['id'] + '.json')))['records']]
    norm = lambda s: re.sub(r'[^a-z0-9]+', ' ', s.lower().replace('’', "'")).strip()
    preset_rows = []
    for key, name, lon, lat in presets:
        lon, lat = float(lon), float(lat)
        same = [r for r in allrec if norm(r['name']) == norm(name)] or [r for r in allrec if norm(r['name']).startswith(norm(name) + ' ') or norm(r['name']) == 'the ' + norm(name)]
        best = min(same, key=lambda r: math.hypot((r['lon'] - lon) * 84414, (r['lat'] - lat) * 111050), default=None)
        d = math.hypot((best['lon'] - lon) * 84414, (best['lat'] - lat) * 111050) if best else None
        preset_rows.append({'key': key, 'name': name, 'matched': best['name'] if best else None, 'matched_id': best['id'] if best else None,
                            'offset_m': round(d) if d is not None else None})
    # placeholder / simulated data scan in runtime code
    pat = re.compile(r'Math\.random|\bmock\b|\bfake\b|dummy|lorem|hard-?coded rating|rating:\s*[0-9.]+')
    flags = []
    for f in RUNTIME:
        p = f if os.path.isabs(f) else os.path.join(ROOT, f)
        for n, line in enumerate(open(p, encoding='utf-8'), 1):
            if pat.search(line):
                flags.append({'file': os.path.relpath(p, ROOT), 'line': n, 'text': line.strip()[:120]})
    code = '\n'.join(open(f if os.path.isabs(f) else os.path.join(ROOT, f), encoding='utf-8').read() for f in RUNTIME)
    unreferenced = [os.path.basename(p) for p in glob.glob(D('*.json')) if os.path.basename(p) not in code and os.path.basename(p) not in ('registry.json', 'audit.json')]
    # capability → (implementation, code signature that proves it is wired: a call site, not just a definition)
    tools = {'search_places / autocomplete': ('places.js searchPlaces (Photon + NYC GeoSearch, live)', r'await searchPlaces\('),
             'discover places (POI index)': ('journey.js discoverPlaces → data/places/*.json', r'await discoverPlaces\('),
             'verify_menu_item': ('POST /api/menu/verify (routing/menu.py)', r"'/api/menu/verify'"),
             'calculate_walking_route': ('POST /api/routes, /api/itinerary', r"'/api/itinerary'"),
             'validate_route': ('routing/validation.py on every route', r'qa\.validate\('),
             'turn-by-turn maneuvers': ('routing/maneuvers.py', r'mv\.build\('),
             'find along route (detours)': ('POST /api/detours', r"'/api/detours'"),
             'weather context': ('weather.js (Open-Meteo, NWS)', r'refreshWeather\(')}
    tool_use = {k: ('wired (call site found)' if re.search(sig, code) else 'not wired') for k, (impl, sig) in tools.items()}
    tools = {k: impl for k, (impl, sig) in tools.items()}
    summary = {'built_at': datetime.now(timezone.utc).isoformat(timespec='seconds'), 'datasets': len(rows), 'connected': sum(r['integration_status'] == 'connected' for r in rows),
               'records': sum(r.get('feature_count') or 0 for r in rows), 'presets': preset_rows, 'placeholder_flags': flags, 'unreferenced_data_files': unreferenced,
               'agent_tools': {k: {'implementation': v, 'status': tool_use[k]} for k, v in tools.items()},
               'provider_access': {'google_places': bool(os.environ.get('GOOGLE_PLACES_API_KEY')), 'yelp_fusion': bool(os.environ.get('YELP_API_KEY')),
                                   'foursquare': bool(os.environ.get('FOURSQUARE_API_KEY')), 'booking_demand': bool(os.environ.get('BOOKING_DEMAND_API_KEY')),
                                   'expedia_rapid': bool(os.environ.get('EXPEDIA_RAPID_API_KEY')), 'openai': bool(os.environ.get('OPENAI_API_KEY'))}}
    json.dump(summary, open(D('audit.json'), 'w'), indent=1)
    md = [f"# STREETWISE · NYC — Data Audit Report\n\nGenerated {summary['built_at']} by `scripts/build_audit_report.py` from the shipped files (no estimates).\n",
          f"**{summary['datasets']} datasets** ({summary['connected']} connected), **{summary['records']:,} records** in the shipped files. A record count is not a count of places verified open today.\n",
          '## Datasets\n', '| Dataset | Provider | Class | Coverage | Records | Freshness (days) | Missing fields | Quality | Integration |', '|---|---|---|---|---|---|---|---|---|']
    for r in rows:
        miss = ', '.join(f'{k} {v:.0%}' for k, v in sorted((r.get('missing_fields') or {}).items(), key=lambda kv: -kv[1])[:3]) or '—'
        md.append(f"| {r['name']} | {r.get('publisher') or '—'} | {r.get('data_class', '—')} | {r.get('coverage_area') or '—'} | {r.get('feature_count') if r.get('feature_count') is not None else '—'} | "
                  f"{r.get('freshness_days') if r.get('freshness_days') is not None else '—'} | {miss} | {quality(r)} | {r['integration_status']} |")
    md += ['\n## Hard-coded quick-pick places (app.js `PLACES`)\n', 'Real places with hand-entered coordinates, used only as optional quick picks. Offset = distance to the same-name record in the discovery index.\n',
           '| Preset | Name | Matched record | Offset (m) |', '|---|---|---|---|']
    md += [f"| {p['key']} | {p['name']} | {p['matched'] or 'no index match'} | {p['offset_m'] if p['offset_m'] is not None else '—'} |" for p in preset_rows]
    md += ['\n## Placeholder / simulated data in runtime code\n', ('No matches for random values, mock/fake/dummy data or hard-coded ratings.' if not flags else
           '\n'.join(f"- {f['file']}:{f['line']} `{f['text']}`" for f in flags))]
    md += ['\n## Data files not read by runtime code\n', ', '.join(unreferenced) or 'None.']
    md += ['\n## Agent tools\n', '| Capability | Implementation | Status |', '|---|---|---|'] + [f"| {k} | {v['implementation']} | {v['status']} |" for k, v in summary['agent_tools'].items()]
    md += ['\n## Business-data provider access (this build environment)\n', '| Provider | Key configured |', '|---|---|'] + [f'| {k} | {"yes" if v else "no"} |' for k, v in summary['provider_access'].items()]
    md += ['\nRatings, review counts, review text, hotel room types, live prices and availability need one of these providers; without a key they are reported as **Blocked by Provider Access**, never simulated.\n']
    open(os.path.join(ROOT, 'DATA_AUDIT_REPORT.md'), 'w').write('\n'.join(md) + '\n')
    print('audit:', summary['datasets'], 'datasets,', len(preset_rows), 'presets,', len(flags), 'placeholder flags,', len(unreferenced), 'unreferenced files')


if __name__ == '__main__':
    main()
