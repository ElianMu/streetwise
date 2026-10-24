"""Clip large context polygons offline into indexed fragments; bounded map queries need no full-city GeoJSON."""
import gzip,hashlib,json,math,os,pathlib,sqlite3,tempfile,zlib
from collections import Counter
from shapely.geometry import shape,mapping,box
from shapely.affinity import scale
ROOT=pathlib.Path(__file__).resolve().parents[1];BASE=ROOT/'data/urban/context';MX=111320*math.cos(math.radians(40.78));MY=110540

def build():
 source_manifest=BASE/'source_manifest.json'
 m=json.loads((source_manifest if source_manifest.exists() else BASE/'manifest.json').read_text())
 if (BASE/'manifest.json').exists():
  prior=json.loads((BASE/'manifest.json').read_text())
  if prior.get('sources')==m['sources'] and prior.get('sha256') and (BASE/'context.sqlite.gz').exists():print('Context index already matches validated sources',flush=True);return
 fd,tmp=tempfile.mkstemp(suffix='.sqlite',dir=ROOT.parent);os.close(fd);db=sqlite3.connect(tmp)
 db.execute('PRAGMA journal_mode=OFF');db.execute('CREATE TABLE features(id INTEGER PRIMARY KEY,category TEXT,source_id TEXT,properties TEXT,geometry BLOB)');db.execute('CREATE VIRTUAL TABLE feature_rtree USING rtree(id,min_lon,max_lon,min_lat,max_lat)');counts=Counter();pid=0
 try:
  for source in m['sources']:
   with gzip.open(BASE/source['file'],'rt') as f:data=json.load(f)
   for feature in data['features']:
    geom=shape(feature['geometry']);metric=scale(geom,xfact=MX,yfact=MY,origin=(0,0));fragments=[]
    if source['id']=='hydrography':
     a,b,c,d=metric.bounds
     for x in range(math.floor(a/2000),math.floor(c/2000)+1):
      for y in range(math.floor(b/2000),math.floor(d/2000)+1):
       clipped=metric.intersection(box(x*2000,y*2000,(x+1)*2000,(y+1)*2000))
       if not clipped.is_empty and clipped.area>1:fragments.append(scale(clipped.simplify(2,preserve_topology=True),xfact=1/MX,yfact=1/MY,origin=(0,0)))
    else:fragments=[geom]
    for part in fragments:
     pid+=1;props=feature['properties'];blob=zlib.compress(json.dumps(mapping(part),separators=(',',':')).encode())
     db.execute('INSERT INTO features VALUES(?,?,?,?,?)',(pid,source['id'],props['feature_id'],json.dumps(props,separators=(',',':')),blob))
     w,s,e,n=part.bounds;db.execute('INSERT INTO feature_rtree VALUES(?,?,?,?,?)',(pid,w,e,s,n));counts[source['id']]+=1
   print('Indexed',source['id'],counts[source['id']],'fragments from',source['records'],'source records',flush=True)
  db.execute('CREATE INDEX category_idx ON features(category)');db.commit();db.close();db=None
  packed=BASE/'context.sqlite.gz.tmp'
  with open(tmp,'rb') as data,packed.open('wb') as out,gzip.GzipFile(fileobj=out,mode='wb',mtime=0) as gz:
   import shutil;shutil.copyfileobj(data,gz,1024*1024)
  m.update(database='context.sqlite.gz',database_bytes=pathlib.Path(tmp).stat().st_size,compressed_bytes=packed.stat().st_size,sha256=hashlib.sha256(packed.read_bytes()).hexdigest(),indexed_fragments=dict(counts),method='Hydrography clipped to 2 km cells and simplified by 2 m for display only. Original source geometries retained; routing uses original boundaries. Other geometry kept as supplied or documented CRS transformation.')
  os.replace(packed,BASE/'context.sqlite.gz');(BASE/'manifest.json').write_text(json.dumps(m,indent=2));print('Context index bytes',m['compressed_bytes'],flush=True)
 finally:
  if db:db.close()
  pathlib.Path(tmp).unlink(missing_ok=True)
if __name__=='__main__':build()
