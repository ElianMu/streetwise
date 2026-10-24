"""Register remote indexed datasets separately from legacy static tiles; no fictional tile counts."""
import json,pathlib
ROOT=pathlib.Path(__file__).resolve().parents[1]
def build():
 p=ROOT/'data/layers/catalog.json';c=json.loads(p.read_text());out=[]
 crime=json.loads((ROOT/'data/urban/crime/manifest.json').read_text());trees=json.loads((ROOT/'data/urban/trees/manifest.json').read_text());ctx=json.loads((ROOT/'data/urban/context/manifest.json').read_text())
 def add(id,name,cat,geom,remote,n,source,url,updated,attributes,note,default=False):
  out.append({'id':id,'name':name,'categories':[cat],'geometry':geom,'remote':remote,'status':'CONNECTED','feature_count':n,'coverage':'NYC source','source':source,'source_url':url,'last_updated':updated,'time_range':note,'attributes':attributes,'scoring':[],'used_in_scoring':False,'independent_metric':remote=='crime','default_visible':default,'layer_type':'indexed_query','min_zoom_view':12,'note':note})
 add('reported_complaints','Historical reported complaint density','safety','Polygon','crime',crime['records'],'NYPD complaints: Historic + Current YTD',crime['sources'][0]['url'],max(s['publisher_updated_at'] for s in crime['sources']),['count','density_per_km2','cell_m','from','to_exclusive','approximate_locations'],'Independent route objective; not part of Access & Safety. Map counts cover complete aggregate cells; route statistics separately count source points within 100 m. '+crime['available_start']+' to '+crime['available_end_exclusive']+' (exclusive). No current personal-risk prediction.')
 add('citywide_tree_inventory','Current citywide tree inventory','nature','Point','trees',trees['records'],'NYC Parks Forestry Tree Points',trees['source_url'],trees['publisher_updated_at'],['record_kind','genusspecies','dbh','tpcondition','updateddate','tree_count'],'Current Full-structure inventory. Low zoom shows aggregated cell centres, not individual tree positions. Not a canopy/shade measurement.')
 for s in ctx['sources']:
  cat='transit' if s['id'].startswith('mta_') else 'waterfront' if s['id'] in ['hydrography','waterfront_access'] else 'streets'
  note='Source geometry and date; no guarantee of current pedestrian access.'
  if s['id']=='construction':note='Permits whose work dates include build day; not proof of continuous closure or blocked sidewalk. '+str(s.get('query_scope'))
  if s['id'].startswith('mta_'):note='Official transit snapshot; no real-time arrivals, elevator status or verified step-free walking path. '+str(s.get('query_scope'))
  add('citywide_'+s['id'],s['name']+' · citywide',cat,next(iter(s['geometry_types'])),'context:'+s['id'],s['records'],s.get('publisher','NYC Open Data'),s['source_url'],s['publisher_updated_at'],list(s['missing_fields'])[:14],note,default=s['id'] in ['waterfront_access','construction'])
 c['remote_datasets']=out;p.write_text(json.dumps(c,indent=1));print('Registered',len(out),'indexed remote datasets')
if __name__=='__main__':build()
