"""Original official hydrography polygons → graph-aligned water proximity, offline only."""
import gzip,hashlib,json,math,pathlib
import numpy as np
from shapely.geometry import shape,Point
from shapely.affinity import scale
from shapely.strtree import STRtree
ROOT=pathlib.Path(__file__).resolve().parents[1];MX=111320*math.cos(math.radians(40.78));MY=110540

def build():
 source=ROOT/'data/urban/context/hydrography.geojson.gz'
 with gzip.open(source,'rt') as f:d=json.load(f)
 polygons=[scale(shape(f['geometry']),xfact=MX,yfact=MY,origin=(0,0)) for f in d['features']]
 index=STRtree(polygons)
 with gzip.open(ROOT/'data/pedestrian/manhattan-walk-graph.json.gz','rt') as f:g=json.load(f)
 values=[];distances=[]
 for i,geom in enumerate(g['geoms']):
  points=[]
  for a,b in zip(geom,geom[1:]):
   ax,ay=a[0]*MX,a[1]*MY;bx,by=b[0]*MX,b[1]*MY;n=max(1,math.ceil(math.hypot(bx-ax,by-ay)/25))
   points.extend(Point(ax+(bx-ax)*(j+.5)/n,ay+(by-ay)*(j+.5)/n) for j in range(n))
  if points:
   idx,ds=index.query_nearest(points,return_distance=True,all_matches=False)
   values.append(round(float(np.mean(ds<=100)),4));distances.append(round(float(np.mean(ds)),1))
  else:values.append(0);distances.append(None)
  if i%15000==0:print('Water proximity',i,'/',len(g['geoms']),flush=True)
 meta=json.loads((ROOT/'data/urban/context/manifest.json').read_text());source_meta=next(s for s in meta['sources'] if s['id']=='hydrography')
 doc={'metadata':{'network_version':g['metadata']['network_version'],'geometries':len(values),'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'source':source_meta,'method':'Published water polygons; metric samples every <=25 m; share within 100 m of water. Uses source geometry, not display simplification.','limitations':['Physical proximity to mapped water, not a verified waterfront entrance, view or public promenade.','Includes mapped lakes and ponds as well as rivers and coastal water. No line-of-sight, tide or flood prediction.','Hydrography vintage is source-bounded, not a live water observation.']},'within_100m_share':values,'mean_water_distance_m':distances}
 target=ROOT/'data/pedestrian/waterfront-features.json.gz'
 with target.open('wb') as f,gzip.GzipFile(fileobj=f,mode='wb',mtime=0) as z:z.write(json.dumps(doc,separators=(',',':')).encode())
 print('Water features',len(values),target.stat().st_size,flush=True)
if __name__=='__main__':build()
