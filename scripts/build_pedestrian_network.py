"""Build the Manhattan OSM pedestrian routing graph (the routing layer; NYC LION is never routed on).

Run: python3 scripts/build_pedestrian_network.py
Needs OSMnx (>= 2.0) and NetworkX at build time only; the server reads the output with the standard library.
Writes data/pedestrian/manhattan-walk-graph.json.gz:
  nodes  {osm_node_id: [lon, lat, street_count, component]}
  geoms  shared LineStrings (an edge and its reverse twin share one, read backwards)
  edges  one row per directed MultiDiGraph edge, keeping the full (u, v, key) identity
"""
import collections, gzip, hashlib, json, os, sys, time
from datetime import datetime, timezone

import networkx as nx
import osmnx as ox

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'data', 'pedestrian', 'manhattan-walk-graph.json.gz')
PLACE = 'Manhattan, New York County, New York, United States'
EXTRA_TAGS = ['foot', 'access', 'sidewalk', 'footway', 'bridge', 'tunnel', 'layer', 'oneway:foot', 'crossing',
              'surface', 'incline', 'wheelchair', 'indoor', 'level', 'covered', 'service', 'area']
ALLOWED_FOOT = {'yes', 'designated', 'permissive'}


def first(v):
    return v[0] if isinstance(v, list) and v else v


def as_list(v):
    return v if isinstance(v, list) else [] if v is None else [v]


def excluded(d):
    """Why pedestrians may not use an edge (None = allowed). OSMnx's walk filter already drops motorways,
    construction and foot=no; these are the remaining legal restrictions."""
    foot, access = set(as_list(d.get('foot'))), set(as_list(d.get('access')))
    highway = set(as_list(d.get('highway')))
    if foot & {'no', 'private', 'use_sidepath'}:
        return 'foot=' + '/'.join(sorted(foot & {'no', 'private', 'use_sidepath'}))
    if access & {'no', 'private'} and not foot & ALLOWED_FOOT:
        return 'access=' + '/'.join(sorted(access & {'no', 'private'}))
    if highway & {'trunk', 'trunk_link', 'motorway', 'motorway_link'} and not foot & ALLOWED_FOOT:
        return 'expressway without pedestrian access'
    return None


def oneway_for_foot(d):
    return 'yes' in as_list(d.get('oneway:foot'))


def main():
    ox.settings.use_cache = True
    ox.settings.cache_folder = os.path.join(ROOT, 'data', 'cache', 'osmnx')
    ox.settings.log_console = False
    ox.settings.useful_tags_way = sorted(set(ox.settings.useful_tags_way + EXTRA_TAGS))
    t0 = time.time()
    boundary = ox.geocode_to_gdf(PLACE).geometry.iloc[0]
    print('Downloading OSM walk network (Overpass)…', flush=True)
    G = ox.graph_from_polygon(boundary, network_type='walk', simplify=True, retain_all=True, truncate_by_edge=True)
    raw_nodes, raw_edges = G.number_of_nodes(), G.number_of_edges()

    # Pedestrian access: drop legally closed edges; a directed copy against an oneway:foot restriction is dropped too.
    dropped = collections.Counter()
    for u, v, k, d in list(G.edges(keys=True, data=True)):
        why = excluded(d) or ('against oneway:foot' if oneway_for_foot(d) and d.get('reversed') is True else None)
        if why:
            G.remove_edge(u, v, k); dropped[why] += 1
    G.remove_nodes_from([n for n in list(G.nodes) if G.degree(n) == 0])

    # Connectivity: routes are only computed inside the largest strongly connected component; smaller pieces
    # (islands reachable only from other boroughs, private courtyards) are kept but flagged non-routable.
    comps = sorted(nx.strongly_connected_components(G), key=len, reverse=True)
    comp_of = {n: i for i, c in enumerate(comps) for n in c}

    nodes = {str(n): [round(d['x'], 7), round(d['y'], 7), int(d.get('street_count', 0)), comp_of[n]] for n, d in G.nodes(data=True)}
    geoms, geom_of, edges = [], {}, []
    for u, v, k, d in G.edges(keys=True, data=True):
        g = d.get('geometry')
        coords = [[round(x, 7), round(y, 7)] for x, y in (g.coords if g is not None else [(G.nodes[u]['x'], G.nodes[u]['y']), (G.nodes[v]['x'], G.nodes[v]['y'])])]
        osmids = sorted(as_list(d.get('osmid')))
        # Twin lookup: the reverse directed edge of the same OSM way(s) reuses this geometry backwards.
        twin_key = (min(u, v), max(u, v), tuple(osmids), round(float(d['length']), 2))
        if twin_key in geom_of and geoms[geom_of[twin_key]][::-1] == coords:
            gi, rev = geom_of[twin_key], 1
        else:
            gi, rev = len(geoms), 0
            geoms.append(coords); geom_of.setdefault(twin_key, gi)
        tags = {t: d[t] for t in ('highway', 'name', 'footway', 'bridge', 'tunnel', 'layer', 'foot', 'access', 'sidewalk', 'crossing', 'surface', 'indoor', 'level', 'covered', 'service', 'wheelchair', 'incline') if d.get(t) is not None}
        edges.append([u, v, k, gi, rev, round(float(d['length']), 2), osmids, tags])

    digest = hashlib.sha1(json.dumps(sorted((e[0], e[1], e[2], e[5]) for e in edges)).encode()).hexdigest()[:8]
    built = datetime.now(timezone.utc)
    meta = {
        'network_version': f"osm-walk-{built:%Y%m%d}-{digest}", 'built_at': built.isoformat(timespec='seconds'),
        'source': 'OpenStreetMap via Overpass API, OSMnx network_type="walk", simplified topology, truncate_by_edge',
        'osmnx_version': ox.__version__, 'boundary': PLACE, 'boundary_bounds': list(boundary.bounds),
        'counts': {'downloaded_nodes': raw_nodes, 'downloaded_edges': raw_edges, 'nodes': len(nodes), 'edges': len(edges),
                   'geometries': len(geoms), 'components': len(comps), 'main_component_nodes': len(comps[0]),
                   'excluded_edges': dict(dropped)},
        'edge_fields': ['u', 'v', 'key', 'geom_index', 'geom_reversed', 'length_m', 'osm_way_ids', 'tags'],
        'node_fields': ['lon', 'lat', 'street_count', 'component (0 = largest, routable)'],
        'edge_id': '"{u}-{v}-{key}" — the full MultiDiGraph identity; one OSM way can map to many edges',
        'oneway_rule': 'All walk edges are bidirectional unless tagged oneway:foot=yes (vehicle oneway does not bind pedestrians).',
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with gzip.open(OUT + '.tmp', 'wt', encoding='utf-8') as f:
        json.dump({'metadata': meta, 'nodes': nodes, 'geoms': geoms, 'edges': edges}, f, separators=(',', ':'), ensure_ascii=False)
    os.replace(OUT + '.tmp', OUT)
    print(json.dumps(meta['counts']), f'{time.time() - t0:.0f}s', meta['network_version'])
    print(f'Wrote {OUT} ({os.path.getsize(OUT) / 1e6:.1f} MB)')


if __name__ == '__main__':
    sys.exit(main())
