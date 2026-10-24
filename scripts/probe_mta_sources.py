"""Read-only official MTA discovery on the normal CI ETL runner; no credentials or scraping."""
import json,os,pathlib,re,urllib.parse,urllib.request
HOST='https://data.ny.gov'
def fetch(url):
 with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'STREETWISE-open-data-research/1.0'}),timeout=60) as r:return json.load(r)
def build(out):
 out.mkdir(parents=True,exist_ok=True);discovery={}
 for term in ['MTA Bus Stops','MTA Subway Stations','MTA GTFS']:
  try:
   d=fetch(HOST+'/api/search/views.json?'+urllib.parse.urlencode({'q':term,'limit':20}))
   discovery[term]=[{'id':v['id'],'name':v['name'],'publisher':v.get('attribution'),'updated':v.get('rowsUpdatedAt'),'description':v.get('description','')[:600]} for r in d.get('results',[]) for v in [r.get('view',{})] if v.get('id')]
  except Exception as e:discovery[term]={'error':type(e).__name__+': '+str(e)[:120]}
 (out/'discovery.json').write_text(json.dumps(discovery,indent=2))
 ids=['39hk-dx4f','i9wp-a4ja']
 for rows in discovery.values():
  if isinstance(rows,list):
   for row in rows:
    if 'bus' in row['name'].lower() and 'stop' in row['name'].lower() and row['id'] not in ids:ids.append(row['id'])
 receipts=[]
 for id in ids[:7]:
  if not re.fullmatch('[a-z0-9]{4}-[a-z0-9]{4}',id):continue
  try:
   m=fetch(HOST+'/api/views/'+id+'.json');n=fetch(HOST+'/resource/'+id+'.json?'+urllib.parse.urlencode({'$select':'count(*) as n'}))
   records=fetch(HOST+'/resource/'+id+'.json?'+urllib.parse.urlencode({'$limit':50000}))
   doc={'metadata':m,'records':records,'source_url':HOST+'/d/'+id,'expected_records':int(n[0]['n']),'complete':len(records)==int(n[0]['n'])}
   (out/(id+'.json')).write_text(json.dumps(doc));receipts.append({'id':id,'name':m['name'],'records':len(records),'complete':doc['complete']});print(json.dumps(receipts[-1]),flush=True)
  except Exception as e:receipts.append({'id':id,'error':type(e).__name__+': '+str(e)[:140]});print(json.dumps(receipts[-1]),flush=True)
 (out/'receipts.json').write_text(json.dumps(receipts,indent=2))
if __name__=='__main__':build(pathlib.Path(os.environ.get('MTA_RESEARCH_OUTPUT','/tmp/streetwise-mta-research')))
