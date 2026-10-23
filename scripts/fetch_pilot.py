"""Reproducible bounded real-source snapshot; fails closed on incomplete pages."""
import json, urllib.request, urllib.parse, datetime, concurrent.futures, pathlib
ROOT=pathlib.Path(__file__).resolve().parents[1]
BOX=[-73.992,40.749,-73.970,40.769]
URLS={
'streets':'https://services.arcgis.com/V6ZHFr6zdgNZuVG0/ArcGIS/rest/services/NYC_Street_Centerline/FeatureServer/0',
'trees':'https://services5.arcgis.com/cuQhNeNcUrgLmYGD/ArcGIS/rest/services/2015_Street_Tree_Census_NYC/FeatureServer/0',
'lpc':'https://services5.arcgis.com/Oos4pNA2538iVFA1/ArcGIS/rest/services/Ind_Landmark_Lots_POLY/FeatureServer/0'}
def get(url):
    with urllib.request.urlopen(url,timeout=55) as r:return json.load(r)
def fetch(item):
    kind,base=item
    if kind=='trees':return fetch_official_trees()
    meta=get(base+'?f=json');oid=next(f['name'] for f in meta['fields'] if f['type']=='esriFieldTypeOID')
    args=dict(where="borocode='1'" if kind=='streets' else '1=1',geometry=','.join(map(str,BOX)),geometryType='esriGeometryEnvelope',inSR=4326,spatialRel='esriSpatialRelIntersects')
    expected=get(base+'/query?'+urllib.parse.urlencode(dict(args,returnCountOnly='true',f='json')))['count']
    fs=[]
    while len(fs)<expected:
        page=get(base+'/query?'+urllib.parse.urlencode(dict(args,f='geojson',outFields='*',outSR=4326,returnGeometry='true',orderByFields=oid+' ASC',resultOffset=len(fs),resultRecordCount=1000)))
        batch=page.get('features',[])
        if not batch:raise RuntimeError('Incomplete '+kind)
        fs+=batch
    assert len(fs)==expected and len({str(f['properties'].get(oid,f.get('id'))) for f in fs})==expected
    print(kind,len(fs),flush=True)
    return kind,{'type':'FeatureCollection','features':fs},dict(url=base,object_id=oid,expected=expected,complete=True,source_year=2015 if kind=='trees' else None,service_edit=meta.get('editingInfo'),description=meta.get('description','')[:1000])
def fetch_official_trees():
    base='https://data.cityofnewyork.us/resource/uvpi-gqnh.json'
    where=f"latitude between {BOX[1]} and {BOX[3]} AND longitude between {BOX[0]} and {BOX[2]} AND borocode='1'"
    def query(q):return get(base+'?'+urllib.parse.urlencode(q,quote_via=urllib.parse.quote))
    n=int(query({'$select':'count(*) as n','$where':where})[0]['n']);rows=[]
    while len(rows)<n:
        page=query({'$where':where,'$order':'tree_id','$limit':1000,'$offset':len(rows)})
        if not page:raise RuntimeError('Incomplete official trees')
        rows+=page
    assert len(rows)==n and len({r['tree_id'] for r in rows})==n
    fs=[{'type':'Feature','id':r['tree_id'],'properties':r,'geometry':{'type':'Point','coordinates':[float(r['longitude']),float(r['latitude'])]}} for r in rows]
    print('official trees',n,flush=True)
    return 'trees',{'type':'FeatureCollection','features':fs},{'url':base,'object_id':'tree_id','expected':n,'complete':True,'source_year':2015,'description':'Official NYC Open Data 2015 Street Tree Census; numeric latitude/longitude bounding box and Manhattan borough filter.'}
if __name__=='__main__':
    out={'bbox':BOX,'retrieved_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'datasets':{},'sources':{}}
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        for kind,fc,meta in pool.map(fetch,URLS.items()):out['datasets'][kind]=fc;out['sources'][kind]=meta
    (ROOT/'data/pilot.json').write_text(json.dumps(out,separators=(',',':')))
