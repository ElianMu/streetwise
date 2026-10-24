"""Precompute the small routing-only view of the street score snapshot; no score changes."""
import gzip,hashlib,json,pathlib,sqlite3,tempfile,os,shutil
ROOT=pathlib.Path(__file__).resolve().parents[1]
def build():
 source=ROOT/'data/manhattan-streets.json'
 with source.open() as f:d=json.load(f)
 records={f['properties']['id']:{k:f['properties'].get(k) for k in ('name','source_segment_id','tree_km','park_pct')} for f in d['features']}
 with source.open('rb') as f:signature=hashlib.file_digest(f,'sha256').hexdigest()
 out={'metadata':{'source_sha256':signature,'data_version':d['metadata']['data_version'],'records':len(records),'method':'Exact field selection from street snapshot; scores and geometry unchanged'},'records':records}
 target=ROOT/'data/pedestrian/segment-evidence.json.gz'
 with target.open('wb') as f,gzip.GzipFile(fileobj=f,mode='wb',mtime=0) as z:z.write(json.dumps(out,separators=(',',':')).encode())
 print('Compact routing evidence',len(records),'records',target.stat().st_size,'bytes')
 base=ROOT/'data/urban/segments';base.mkdir(parents=True,exist_ok=True)
 fd,temp=tempfile.mkstemp(suffix='.sqlite',dir=ROOT.parent);os.close(fd)
 try:
  db=sqlite3.connect(temp);db.execute('CREATE TABLE segments(id TEXT PRIMARY KEY, feature TEXT)')
  db.executemany('INSERT INTO segments VALUES(?,?)',((f['properties']['id'],json.dumps(f,separators=(',',':'))) for f in d['features']));db.commit();db.close()
  packed=base/'segments.sqlite.gz'
  with open(temp,'rb') as data,packed.open('wb') as f,gzip.GzipFile(fileobj=f,mode='wb',mtime=0) as z:shutil.copyfileobj(data,z,1024*1024)
  m={'source_sha256':signature,'street_metadata':d['metadata'],'records':len(records),'database':'segments.sqlite.gz','database_bytes':pathlib.Path(temp).stat().st_size,'compressed_bytes':packed.stat().st_size,'sha256':hashlib.sha256(packed.read_bytes()).hexdigest()}
  (base/'manifest.json').write_text(json.dumps(m,indent=2));print('Indexed segment inspector',m['compressed_bytes'],'bytes')
 finally:pathlib.Path(temp).unlink(missing_ok=True)
if __name__=='__main__':build()
