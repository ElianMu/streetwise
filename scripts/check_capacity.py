"""Fresh-process Linux memory budget regression using shipped real data and graph.

Run separately from unit tests: python scripts/check_capacity.py. No OpenAI or
website calls. The 448 MiB process-peak ceiling reserves 64 MiB of a 512 MiB
instance; cgroup file-cache/production behaviour still require deployment checks.
"""
import concurrent.futures
import gc
import json
from pathlib import Path
import resource
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from routing.engine import get_planner
from routing.places import store
from routing import crime
from routing.capacity import Admission


def main():
    planner = get_planner()
    crime.edge_field(planner.net, crime.validate({'direction': 'high'}))
    places = store()
    # Include the first all-borough permit read, not just the warmed Manhattan graph.
    outside = places.search({'lat':40.68,'lon':-73.95}, ['restaurants'], radius_m=1200)
    assert outside and all(r['borough']=='Brooklyn' for r in outside)
    gate = Admission()
    start = time.monotonic()
    def work(i):
        assert gate.acquire(30)
        try:
            result = planner.plan({'lon':-73.999,'lat':40.733}, {'lon':-73.977,'lat':40.758},
                                  {'crime':{'direction':'high' if i%2 else 'low'}},
                                  {'max_minutes':100,'max_detour_pct':40})
            assert result['routes'] and len(result['routes'][0]['dimension_scores']) == 12
            return len(result['routes'])
        finally:
            gate.release()
    with concurrent.futures.ThreadPoolExecutor(3) as pool:
        results = list(pool.map(work, range(3)))
    gc.collect()
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    receipt = {'scope':'fresh Linux process; real graph/source snapshots; no live API calls',
               'python':sys.version.split()[0], 'peak_rss_kib':peak, 'ceiling_kib':448*1024,
               'three_client_seconds':round(time.monotonic()-start,3), 'routes_per_client':results,
               'admission':gate.status(), 'packed_geometry_bytes':planner.net.geoms.packed_bytes}
    print(json.dumps(receipt, indent=2))
    assert sys.platform.startswith('linux'), 'RSS ceiling units are defined here for Linux only'
    assert peak < receipt['ceiling_kib'], '512 MiB capacity headroom regression'


if __name__ == '__main__':
    main()
