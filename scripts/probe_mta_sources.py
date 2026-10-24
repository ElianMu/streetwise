"""Read-only official MTA discovery on the normal CI ETL runner; no credentials or scraping."""
import gzip,json,os,pathlib,re,urllib.parse,urllib.request
from datetime import datetime,timezone
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
 # Research compared the historical relationship table, a map view and ridership
 # data. Ingest only these three complete relevant official datasets, not truncated
 # samples of million-row histories or a map-view response mistaken for records.
 ids=['39hk-dx4f','i9wp-a4ja','ai5j-txmn']
 receipts=[]
 for id in ids[:7]:
  if not re.fullmatch('[a-z0-9]{4}-[a-z0-9]{4}',id):continue
  try:
   m=fetch(HOST+'/api/views/'+id+'.json');n=fetch(HOST+'/resource/'+id+'.json?'+urllib.parse.urlencode({'$select':'count(*) as n'}))
   records=fetch(HOST+'/resource/'+id+'.json?'+urllib.parse.urlencode({'$limit':50000}))
   # Ignore mutable download/view counters when comparing publisher snapshots.
   m={k:m[k] for k in ('id','name','attribution','description','rowsUpdatedAt','columns') if k in m}
   complete=isinstance(records,list) and all(isinstance(r,dict) for r in records) and len(records)==int(n[0]['n'])
   doc={'metadata':m,'records':records,'source_url':HOST+'/d/'+id,'expected_records':int(n[0]['n']),'complete':complete,'retrieved_at':datetime.now(timezone.utc).isoformat()}
   prior=pathlib.Path(__file__).resolve().parents[1]/'data/urban/transit-source-research'/(id+'.json.gz')
   if prior.exists():
    with gzip.open(prior,'rt') as f:old=json.load(f)
    if old.get('records')==records and old['metadata'].get('rowsUpdatedAt')==m.get('rowsUpdatedAt'):doc=old
   with (out/(id+'.json.gz')).open('wb') as f,gzip.GzipFile(fileobj=f,mode='wb',mtime=0) as z:z.write(json.dumps(doc,separators=(',',':')).encode())
   receipts.append({'id':id,'name':m['name'],'records':len(records),'complete':complete});print(json.dumps(receipts[-1]),flush=True)
  except Exception as e:receipts.append({'id':id,'error':type(e).__name__+': '+str(e)[:140]});print(json.dumps(receipts[-1]),flush=True)
 (out/'receipts.json').write_text(json.dumps(receipts,indent=2))
 if len(receipts)!=len(ids) or any(not r.get('complete') for r in receipts):raise RuntimeError('Official MTA acquisition incomplete; inspect receipts, do not publish partial data')
if __name__=='__main__':build(pathlib.Path(os.environ.get('MTA_RESEARCH_OUTPUT','/tmp/streetwise-mta-research')))
