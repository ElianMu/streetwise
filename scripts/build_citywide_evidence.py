"""Source-backed citywide context geometry and current tree inventory, offline only."""
import csv,gzip,hashlib,io,json,math,os,pathlib,re,shutil,sqlite3,tempfile,urllib.parse,urllib.request
from collections import Counter
from datetime import datetime,timezone
ROOT=pathlib.Path(__file__).resolve().parents[1];OUT=ROOT/'data/urban';HOST='https://data.cityofnewyork.us'

def fetch(url):
 with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'STREETWISE-data-integration/1.0'}),timeout=180) as r:return json.load(r)
def url(id,q):return HOST+'/resource/'+id+'.json?'+urllib.parse.urlencode(q)
def point(raw):
 v=re.findall(r'-?\d+(?:\.\d+)?',raw or '')
 if len(v)!=2:raise ValueError('invalid WKT point')
 lon,lat=map(float,v)
 if not (-74.3<lon<-73.68 and 40.45<lat<40.95):raise ValueError('coordinate outside NYC')
 return lon,lat

def trees():
 id='hn5i-inap';meta=fetch(HOST+'/api/views/'+id+'.json');base=OUT/'trees';base.mkdir(parents=True,exist_ok=True)
 old=json.loads((base/'manifest.json').read_text()) if (base/'manifest.json').exists() else None
 if old and old['publisher_version']==meta['rowsUpdatedAt']:print('Current forestry snapshot unchanged',flush=True);return
 expected=int(fetch(url(id,{'$select':'count(*) as n','$where':"tpstructure='Full'"}))[0]['n'])
 tmp=pathlib.Path(tempfile.mkdtemp(prefix='streetwise-trees-',dir=ROOT.parent));db=sqlite3.connect(tmp/'trees.sqlite');db.execute('PRAGMA journal_mode=OFF');db.execute('PRAGMA cache_size=-4096')
 db.execute('CREATE TABLE trees(id INTEGER PRIMARY KEY,lon REAL,lat REAL,species TEXT,dbh REAL,condition TEXT,updated TEXT,planted TEXT)')
 fields=['objectid','genusspecies','dbh','tpcondition','tpstructure','planteddate','updateddate','location'];missing=Counter();rejected=0;count=0;batch=[]
 q={'$select':','.join(fields),'$where':"tpstructure='Full'",'$limit':2000000}
 req=urllib.request.Request(HOST+'/resource/'+id+'.csv?'+urllib.parse.urlencode(q),headers={'Accept-Encoding':'gzip','User-Agent':'STREETWISE-data-integration/1.0'})
 try:
  with urllib.request.urlopen(req,timeout=180) as response:
   raw=gzip.GzipFile(fileobj=response) if response.headers.get('Content-Encoding')=='gzip' else response
   for r in csv.DictReader(io.TextIOWrapper(raw,encoding='utf-8-sig',newline='')):
    count+=1
    for k in fields:missing[k]+=not r.get(k) or r.get(k)=='(null)'
    try:lon,lat=point(r.get('location'));pid=int(r['objectid']);dbh=float(r['dbh']) if r.get('dbh') else None
    except (ValueError,TypeError,KeyError):rejected+=1;continue
    batch.append((pid,lon,lat,r.get('genusspecies') or None,dbh,r.get('tpcondition') or None,r.get('updateddate') or None,r.get('planteddate') or None))
    if len(batch)>=2000:db.executemany('INSERT OR REPLACE INTO trees VALUES(?,?,?,?,?,?,?,?)',batch);batch.clear()
    if count%100000==0:print('Forestry',count,flush=True)
  if batch:db.executemany('INSERT OR REPLACE INTO trees VALUES(?,?,?,?,?,?,?,?)',batch)
  if count!=expected:raise ValueError('Incomplete forestry snapshot')
  db.execute('CREATE VIRTUAL TABLE tree_rtree USING rtree(id,min_lon,max_lon,min_lat,max_lat)');db.execute('INSERT INTO tree_rtree SELECT id,lon,lon,lat,lat FROM trees');db.commit()
  n=db.execute('SELECT count(*) FROM trees').fetchone()[0];conditions=dict(db.execute('SELECT condition,count(*) FROM trees GROUP BY condition'))
  db.close();db=None
  packed=tmp/'trees.sqlite.gz'
  with (tmp/'trees.sqlite').open('rb') as data,packed.open('wb') as out,gzip.GzipFile(fileobj=out,mode='wb',mtime=0) as gz:shutil.copyfileobj(data,gz,1024*1024)
  d={'schema_version':1,'name':meta['name'],'dataset_id':id,'source_url':HOST+'/d/'+id,'publisher':'NYC Parks','publisher_version':meta['rowsUpdatedAt'],'publisher_updated_at':datetime.fromtimestamp(meta['rowsUpdatedAt'],timezone.utc).isoformat(),'retrieved_at':datetime.now(timezone.utc).isoformat(),'source_rows':count,'records':n,'invalid_records':rejected,'duplicates':count-rejected-n,'conditions':conditions,'missing_fields':{k:missing[k]/count for k in fields},'coverage':'NYC citywide','database':'trees.sqlite.gz','database_bytes':(tmp/'trees.sqlite').stat().st_size,'compressed_bytes':packed.stat().st_size,'sha256':hashlib.sha256(packed.read_bytes()).hexdigest(),'limitations':['NYC Parks Full tree structures; not proof of current canopy shade or public pedestrian access.','Inventory condition and update dates are source values, not live observations.','Existing Nature scoring definitions remain unchanged; this index supplies independently queryable source evidence.']}
  if old and n<.7*old['records']:raise ValueError('Suspicious forestry record loss; retaining prior snapshot')
  if fetch(HOST+'/api/views/'+id+'.json').get('rowsUpdatedAt')!=meta['rowsUpdatedAt']:raise ValueError('Forestry changed during ingestion; retain prior snapshot and rerun')
  os.replace(packed,base/'trees.sqlite.gz');(tmp/'manifest.json').write_text(json.dumps(d,indent=2));os.replace(tmp/'manifest.json',base/'manifest.json');print('Forestry published',n,'bytes',d['compressed_bytes'],flush=True)
 finally:
  if db:db.close()
  shutil.rmtree(tmp,ignore_errors=True)

def context():
 specs=[('hydrography','pjs3-c3z5'),('waterfront_access','388s-pnvc'),('pedestrian_plazas','k5k6-6jex'),('construction','ezy6-djsf'),('seating','esmy-s8q5')]
 from shapely.geometry import shape,mapping
 from shapely import wkt,make_valid
 from shapely.ops import transform
 from pyproj import Transformer
 base=OUT/'context';base.mkdir(parents=True,exist_ok=True);manifest=[]
 prior=json.loads((base/'manifest.json').read_text()) if (base/'manifest.json').exists() else {}
 previous={s['id']:s for s in prior.get('sources',[])};changed=False
 for name,id in specs:
  meta=fetch(HOST+'/api/views/'+id+'.json');q={}
  if name=='construction':
   today=datetime.now(timezone.utc).date().isoformat();q['$where']=f"workstartdate<='{today}T23:59:59' AND workenddate>='{today}T00:00:00'"
  updated=datetime.fromtimestamp(meta['rowsUpdatedAt'],timezone.utc).isoformat();old=previous.get(name)
  if old and old['publisher_updated_at']==updated and old.get('query_scope',{})==q and (base/old['file']).exists():
   manifest.append(old);print(name,'publisher version and query scope unchanged',flush=True);continue
  changed=True
  expected=int(fetch(url(id,{'$select':'count(*) as n',**q}))[0]['n'])
  rows=fetch(url(id,{'$limit':100000,**q}));features=[];bad=0;seen_records=set();duplicates=0
  if len(rows)!=expected:raise ValueError('Incomplete '+name)
  for i,r in enumerate(rows):
   raw=r.get('the_geom')
   try:
    geom=shape(raw) if raw else wkt.loads(r['wkt']) if r.get('wkt') else None
    if geom is None or geom.is_empty:raise ValueError('missing geometry')
    if name=='construction' and geom.bounds[0]>100000:
     geom=transform(Transformer.from_crs(2263,4326,always_xy=True).transform,geom)
    if not geom.is_valid:geom=make_valid(geom)
    if geom.is_empty or not (-74.4<=geom.bounds[0]<=geom.bounds[2]<=-73.6 and 40.4<=geom.bounds[1]<=geom.bounds[3]<=41):raise ValueError('invalid bounds/CRS')
   except Exception:bad+=1;continue
   p={k:v for k,v in r.items() if k not in ['the_geom','wkt','shape_area','shape_leng']}
   # Publisher keys may repeat or be absent; do not collapse different source records onto one ID.
   signature=hashlib.sha256(json.dumps([p,mapping(geom)],sort_keys=True,separators=(',',':')).encode()).hexdigest()
   if signature in seen_records:duplicates+=1;continue
   seen_records.add(signature)
   p['feature_id']=name+':'+signature[:24]
   features.append({'type':'Feature','properties':p,'geometry':mapping(geom)})
  data={'type':'FeatureCollection','features':features};target=base/(name+'.geojson.gz')
  with target.open('wb') as out,gzip.GzipFile(fileobj=out,mode='wb',mtime=0) as z:z.write(json.dumps(data,separators=(',',':')).encode())
  item={'id':name,'dataset_id':id,'name':meta['name'],'source_url':HOST+'/d/'+id,'publisher_updated_at':datetime.fromtimestamp(meta['rowsUpdatedAt'],timezone.utc).isoformat(),'retrieved_at':datetime.now(timezone.utc).isoformat(),'source_rows':expected,'records':len(features),'invalid_geometries':bad,'coverage':'NYC source coverage; not every category covers every borough equally','query_scope':q,'crs_transform':'EPSG:2263 to EPSG:4326 for construction WKT' if name=='construction' else 'Published WGS84 geometry','file':target.name,'bytes':target.stat().st_size,'geometry_types':dict(Counter(f['geometry']['type'] for f in features)),'missing_fields':{k:sum(f['properties'].get(k) in (None,'') for f in features)/len(features) for k in list(features[0]['properties']) if k!='feature_id'} if features else {},'routing_usage':'context until explicit geometric linkage is built'}
  item['missing_fields']={k:sum(f['properties'].get(k) is None or str(f['properties'].get(k,'')).strip().lower() in ('','(null)','unset','unknown') for f in features)/len(features) for k in list(features[0]['properties']) if k!='feature_id'} if features else {}
  item['exact_duplicate_source_rows']=duplicates;item['source_record_identity']='derived SHA-256 of exact source attributes and geometry; original publisher keys retained as attributes, not treated as unique entities'
  manifest.append(item);print(name,len(features),'rejected',bad,'bytes',target.stat().st_size,flush=True)
 # The runtime manifest/database stay intact until index_urban_context publishes the complete next index.
 manifest.extend(s for s in prior.get('sources',[]) if s['id'].startswith('mta_'))
 (base/'source_manifest.json').write_text(json.dumps({'sources':manifest},indent=2))
 if not changed:print('All context publisher versions unchanged; indexed snapshot retained',flush=True)
if __name__=='__main__':
 import sys
 trees() if '--trees' in sys.argv else context()
