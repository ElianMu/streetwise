"""Complete official MTA station/entrance/current-bus snapshots → indexed map evidence.
Bus source rows are route-stop relationships, not unique physical stops. Only the
same publisher stop_id with exactly identical coordinates is grouped; routes and
validity intervals remain explicit. Does not change the Transit Connectivity score.
"""
import argparse,collections,datetime,gzip,hashlib,json,pathlib
ROOT=pathlib.Path(__file__).resolve().parents[1];BASE=ROOT/'data/urban/context'
SPECS=[('mta_stations','39hk-dx4f','gtfs_latitude','gtfs_longitude'),('mta_entrances','i9wp-a4ja','entrance_latitude','entrance_longitude'),('mta_bus_stops','ai5j-txmn','latitude','longitude')]

def read_source(folder,id):
 p=folder/(id+'.json.gz')
 if p.exists():
  with gzip.open(p,'rt') as f:return json.load(f)
 return json.loads((folder/(id+'.json')).read_text())

def build(folder):
 manifest_path=BASE/'source_manifest.json';doc=json.loads(manifest_path.read_text());replace={s[0] for s in SPECS}
 sources=[s for s in doc['sources'] if s['id'] not in replace]
 for category,id,latkey,lonkey in SPECS:
  d=read_source(folder,id);rows=d['records'];m=d['metadata']
  if not d.get('complete') or not isinstance(rows,list) or len(rows)!=d['expected_records']:raise ValueError('Incomplete MTA snapshot '+id)
  features=[];seen=set();grouped={};invalid=0;duplicate=0;outside=0;today=datetime.datetime.now(datetime.timezone.utc).date().isoformat()
  for row in rows:
   try:
    lon,lat=float(row[lonkey]),float(row[latkey])
    if not (-74.3<=lon<=-73.68 and 40.45<=lat<=40.95):raise ValueError('outside NYC service region')
    g=row.get('georeference' if category!='mta_entrances' else 'entrance_georeference')
    if g and any(abs(a-b)>1e-6 for a,b in zip(g['coordinates'],[lon,lat])):raise ValueError('coordinate field conflict')
   except (ValueError,TypeError,KeyError):invalid+=1;continue
   p={k:v for k,v in row.items() if not k.startswith(':') and not k.endswith('georeference')}
   if category=='mta_bus_stops':
    if p.get('in_effect')!='true' or not p.get('valid_from','')[:10]<=today<=p.get('valid_to','')[:10]:raise ValueError('Current MTA bus view contains inactive rows; review validity semantics')
    key=(p['stop_id'],lon,lat)
    grouped.setdefault(key,[]).append(p);continue
   signature=hashlib.sha256(json.dumps([p,lon,lat],sort_keys=True,separators=(',',':')).encode()).hexdigest()
   if signature in seen:duplicate+=1;continue
   seen.add(signature);p['feature_id']=category+':'+(p['gtfs_stop_id'] if category=='mta_stations' else signature[:24]);p['name']=p['stop_name']
   features.append({'type':'Feature','properties':p,'geometry':{'type':'Point','coordinates':[lon,lat]}})
  if category=='mta_bus_stops':
   locations=collections.defaultdict(set)
   for (stop_id,lon,lat),usage in grouped.items():
    locations[stop_id].add((lon,lat));p={'stop_id':stop_id,'name':usage[0]['stop_name'],'stop_names':sorted({u['stop_name'] for u in usage}),'routes':sorted({u['route_id'] for u in usage}),'route_stop_rows':len(usage),'valid_from':min(u['valid_from'] for u in usage),'valid_to':max(u['valid_to'] for u in usage),'validity_intervals':sorted({(u['valid_from'],u['valid_to']) for u in usage}),'in_effect':'true','bundle':sorted({u.get('bundle','') for u in usage}),'feature_id':category+':'+stop_id+':'+hashlib.sha256(f'{lon},{lat}'.encode()).hexdigest()[:12]}
    features.append({'type':'Feature','properties':p,'geometry':{'type':'Point','coordinates':[lon,lat]}})
   conflicts=sum(len(v)>1 for v in locations.values())
  else:conflicts=0
  prior=next((s for s in doc['sources'] if s['id']==category),None)
  if prior and len(features)<.7*prior['records']:raise ValueError('Suspicious MTA record loss; retain prior snapshot for review')
  target=BASE/(category+'.geojson.gz')
  with target.open('wb') as out,gzip.GzipFile(fileobj=out,mode='wb',mtime=0) as z:z.write(json.dumps({'type':'FeatureCollection','features':features},separators=(',',':')).encode())
  fields=set().union(*(f['properties'] for f in features));missing={k:sum(f['properties'].get(k) in (None,'','NaN') for f in features)/len(features) for k in sorted(fields) if k!='feature_id'}
  s={'id':category,'dataset_id':id,'name':m['name'],'source_url':d['source_url'],'publisher':'Metropolitan Transportation Authority / Open Data NY','license':'Open Data NY Terms of Use','license_url':'https://data.ny.gov/download/77gx-ii52/application/pdf','publisher_updated_at':datetime.datetime.fromtimestamp(m['rowsUpdatedAt'],datetime.timezone.utc).isoformat(),'retrieved_at':d.get('retrieved_at') or '2026-10-24 (official CI acquisition)','source_rows':len(rows),'records':len(features),'invalid_geometries':invalid,'exact_duplicate_source_rows':duplicate,'coordinate_conflict_stop_ids':conflicts,'coverage':'All five NYC boroughs; bus service also extends just beyond the city boundary' if category=='mta_bus_stops' else 'All five NYC boroughs','query_scope':{'source':'complete published current view; bus route-stop rows grouped by published stop ID + exact coordinates' if category=='mta_bus_stops' else 'complete published snapshot'},'crs_transform':'Published WGS84 lat/lon cross-checked with source GeoJSON point','file':target.name,'bytes':target.stat().st_size,'geometry_types':{'Point':len(features)},'missing_fields':missing,'routing_usage':'Queryable official transit context; existing Transit Connectivity scoring snapshot unchanged','source_record_identity':'Published station stop ID; entrance attribute/geometry hash; bus published stop ID plus exact coordinates. No name-only entity matching.','limitations':['Station ADA flags do not establish a step-free walking path or currently working elevator.','Entrance data has a 2024 observation vintage; publisher update is not a new field survey.','Bus route-stop relationships are grouped, not added up as separate physical stops. No timetable or real-time arrivals/alerts are claimed.']}
  sources.append(s);print(category,len(features),'from',len(rows),'invalid',invalid,'exact_duplicates',duplicate,'coordinate_conflicts',conflicts,flush=True)
 doc['sources']=sources;manifest_path.write_text(json.dumps(doc,indent=2))
if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('--research-dir',type=pathlib.Path,default=ROOT/'data/urban/transit-source-research');build(parser.parse_args().research_dir)
