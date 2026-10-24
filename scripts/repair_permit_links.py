"""Re-link the shipped OSM snapshot to the shipped DOHMH snapshot conservatively.

No network calls, invented records or refreshed timestamps for upstream sources.
Keep OSM fields/canonical IDs; rebuild only permit associations and permit-only
records, using exact normalized addresses and unambiguous name matches.
"""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import build_place_index as build
from routing.engine import get_planner, RoutingError
from snapshot_io import publish


def main():
    root=Path(build.OUT)
    categories=('restaurants','cafes','bakeries','bars')
    original={c:json.loads((root/(c+'.json')).read_text())['records'] for c in categories}
    old={r['id']:r for rows in original.values() for r in rows}
    groups={c:[] for c in categories}
    for cat,rows in original.items():
        for record in rows:
            if record.get('src')=='dohmh':continue
            r=dict(record)
            for key in ('dohmh','grade','gdate','insp','dcuisine','closed'):r.pop(key,None)
            r['pids']=[p for p in r.get('pids',[r['id']]) if not p.startswith('dohmh:')]
            groups[cat].append(r)
    net=get_planner().net
    def snap(lon,lat):
        try:return net.snap(lon,lat,'permit')['snap_distance_m']
        except RoutingError:return None
    summary=build.link_inspections(groups,snap)
    at=datetime.now(timezone.utc).isoformat(timespec='seconds')
    for cat,rows in groups.items():
        for r in rows:
            if r['src']=='dohmh':
                r['cid']=old.get(r['id'],{}).get('cid') or 'sw:'+hashlib.sha1(r['id'].encode()).hexdigest()[:12]
                r['chk']=at;r['upd']=r.get('insp');r['q']='partial' if r.get('addr') else 'minimal'
            elif r.get('dohmh'):
                r['pids'].append('dohmh:'+r['dohmh'])
            if len(r.get('pids',[]))==1:r.pop('pids')
            r['status']='closed_by_dohmh' if r.get('closed') else 'listed'
        rows.sort(key=lambda r:(r['name'].casefold(),r['id']))
    aliases=[p for rows in groups.values() for r in rows for p in r.get('pids',[r['id']])]
    assert len(aliases)==len(set(aliases)), 'Provider aliases must identify exactly one record'
    ids=[r['cid'] for rows in groups.values() for r in rows]
    assert len(ids)==len(set(ids)), 'Canonical identities must not collide after splitting links'
    changed=[{'id':r['id'],'name':r['name'],'old_permit':old[r['id']].get('dohmh'),'new_permit':r.get('dohmh')}
             for rows in groups.values() for r in rows if r['id'] in old and old[r['id']].get('dohmh')!=r.get('dohmh')]
    receipt={'method':'same source snapshots; unambiguous names AND exact normalized address AND <60 m; uncertain records retained separately',
             'repaired_at':at,'permit_source_sha256':hashlib.sha256(Path(build.INSPECTIONS).read_bytes()).hexdigest(),
             'source_record_counts':{c:len(v) for c,v in original.items()},'result_record_counts':{c:len(v) for c,v in groups.items()},
             'changed_links':changed,'summary':summary}
    index=json.loads((root/'index.json').read_text())
    for c in index['categories']:
        if c['id'] in groups:
            rows=groups[c['id']];c['count']=len(rows)
            c['missing']={k:sum(not r.get(k) for r in rows) for k in ('addr','web','hours')}
    index['inspections']=summary
    index['permit_link_repair']={k:v for k,v in receipt.items() if k!='changed_links'}
    docs={c+'.json':{'category':c,'records':v} for c,v in groups.items()}
    docs['index.json']=index
    publish(str(root),docs,str(root.parent.parent.parent/'streetwise-data-history'/'permit-link-repair'),pretty=('index.json',))
    (root.parent/'urban'/'research'/'permit-link-repair.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print(json.dumps({k:v for k,v in receipt.items() if k!='changed_links'},indent=2))
    print('Changed permit associations:',len(changed))


if __name__=='__main__':main()
