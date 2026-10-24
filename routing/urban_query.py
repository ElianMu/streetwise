"""Small indexed map/evidence queries. No complete city inventory is loaded into Python."""
import json,math,zlib
from .urban_store import connection,manifest

def bounds(values):
 if len(values)!=4 or not all(math.isfinite(x) for x in values) or not (-74.3<=values[0]<values[2]<=-73.68 and 40.45<=values[1]<values[3]<=40.95):raise ValueError('Urban query bounds must be within NYC')
 return values

def trees(box,zoom=15,limit=1800):
 w,s,e,n=bounds(box);features=[]
 with connection('trees') as db:
  if zoom<16:
   size=.004 if zoom<13 else .002 if zoom<15 else .001
   rows=list(db.execute('SELECT CAST(floor(t.lon/?) AS INTEGER),CAST(floor(t.lat/?) AS INTEGER),count(*) FROM tree_rtree r CROSS JOIN trees t ON t.id=r.id WHERE r.min_lon<=? AND r.max_lon>=? AND r.min_lat<=? AND r.max_lat>=? GROUP BY 1,2 ORDER BY 3 DESC LIMIT ?',(size,size,e,w,n,s,limit+1)))
   for x,y,count in rows[:limit]:features.append({'type':'Feature','geometry':{'type':'Point','coordinates':[(x+.5)*size,(y+.5)*size]},'properties':{'feature_id':f'tree-cell:{x}:{y}','record_kind':'aggregated_inventory_cell','tree_count':count,'cell_degrees':size,'source':'NYC Parks Forestry Tree Points','note':'Cell centre, not the location of an individual tree'}})
  else:
   rows=list(db.execute('SELECT t.id,t.lon,t.lat,t.species,t.dbh,t.condition,t.updated,t.planted FROM tree_rtree r CROSS JOIN trees t ON t.id=r.id WHERE r.min_lon<=? AND r.max_lon>=? AND r.min_lat<=? AND r.max_lat>=? LIMIT ?',(e,w,n,s,limit+1)))
   for id,lon,lat,species,dbh,condition,updated,planted in rows[:limit]:features.append({'type':'Feature','geometry':{'type':'Point','coordinates':[lon,lat]},'properties':{'feature_id':str(id),'record_kind':'inventory_tree','genusspecies':species,'dbh':dbh,'tpcondition':condition,'updateddate':updated,'planteddate':planted,'source':'NYC Parks Forestry Tree Points'}})
 m=manifest('trees');return {'type':'FeatureCollection','features':features,'metadata':{'records':m['records'],'truncated':len(rows)>limit,'source_url':m['source_url'],'publisher_updated_at':m['publisher_updated_at'],'note':'Inventory evidence, not measured canopy shade; aggregated at lower zoom'}}

def context(category,box,limit=1500):
 w,s,e,n=bounds(box);m=manifest('context');source=next((s for s in m['sources'] if s['id']==category),None)
 if not source:raise ValueError('Unknown indexed context category')
 with connection('context') as db:
  rows=list(db.execute('SELECT f.id,f.source_id,f.properties,f.geometry FROM feature_rtree r CROSS JOIN features f ON f.id=r.id WHERE r.min_lon<=? AND r.max_lon>=? AND r.min_lat<=? AND r.max_lat>=? AND f.category=? LIMIT ?',(e,w,n,s,category,limit+1)))
 features=[];used_bytes=0;byte_limited=False
 for id,sid,p,g in rows[:limit]:
  raw=zlib.decompress(g);used_bytes+=len(raw)+len(p)
  if used_bytes>1024*1024:byte_limited=True;break
  props=json.loads(p);props.update(feature_id=str(id),source_feature_id=sid,source_url=source['source_url'],publisher_updated_at=source['publisher_updated_at'])
  features.append({'type':'Feature','properties':props,'geometry':json.loads(raw)})
 return {'type':'FeatureCollection','features':features,'metadata':{'category':category,'source_records':source['records'],'fragments':len(features),'truncated':len(rows)>limit or byte_limited,'geometry_byte_limit':1024*1024,'source_url':source['source_url'],'publisher_updated_at':source['publisher_updated_at'],'note':m['method']}}
