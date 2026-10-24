"""Stream official NYPD complaints into a bounded-memory, indexed offline snapshot.
Only complaint ID, occurrence/report dates, offence, law category, source borough and
published coordinates are retained; no victim/suspect demographics or addresses.
Raw source coordinates are approximate, not personal risk observations.
"""
import argparse,csv,gzip,hashlib,io,json,math,os,pathlib,shutil,sqlite3,tempfile,time,urllib.parse,urllib.request
from collections import Counter
from datetime import date,datetime,timedelta,timezone
ROOT=pathlib.Path(__file__).resolve().parents[1]
OUT=ROOT/'data/urban/crime'
HOST='https://data.cityofnewyork.us'
SOURCES=[('qgea-i56i','NYPD Complaint Data Historic'),('5uac-w243','NYPD Complaint Data Current (Year To Date)')]
FIELDS=['cmplnt_num','cmplnt_fr_dt','rpt_dt','ky_cd','ofns_desc','law_cat_cd','boro_nm','latitude','longitude']
MX=111320*math.cos(math.radians(40.78));MY=110540;CELL=200

def get(url,timeout=180):
    with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'STREETWISE-NYC-open-data/1.0'}),timeout=timeout) as r:return json.load(r)

def query(id,params):return HOST+'/resource/'+id+'.json?'+urllib.parse.urlencode(params)

def build(start='2025-01-01',force=False):
    OUT.mkdir(parents=True,exist_ok=True)
    metas=[get(HOST+'/api/views/'+id+'.json') for id,_ in SOURCES]
    signatures={m['id']:m.get('rowsUpdatedAt') for m in metas}
    prior=json.loads((OUT/'manifest.json').read_text()) if (OUT/'manifest.json').exists() else None
    if not force and prior and prior.get('schema_version')==2 and prior['publisher_versions']==signatures and prior['requested_start']==start:
        print('Publisher versions and requested window unchanged; retaining indexed snapshot',flush=True);return
    full=[]
    for id,_ in SOURCES:
        full.append(get(query(id,{'$select':'count(*) as n,min(cmplnt_fr_dt) as min_date,max(cmplnt_fr_dt) as max_date,max(rpt_dt) as max_report'}))[0])
    end=(date.fromisoformat(max(d['max_date'][:10] for d in full))+timedelta(days=1)).isoformat()
    where=f"cmplnt_fr_dt>='{start}T00:00:00' AND cmplnt_fr_dt<'{end}T00:00:00'"
    work=pathlib.Path(tempfile.mkdtemp(prefix='streetwise-crime-',dir=ROOT.parent))
    db=sqlite3.connect(work/'complaints.sqlite');db.execute('PRAGMA journal_mode=OFF');db.execute('PRAGMA cache_size=-4096')
    db.execute('CREATE TABLE incidents(id INTEGER PRIMARY KEY,day INTEGER NOT NULL,report_day INTEGER,offense INTEGER,law TEXT,borough TEXT,lon REAL,lat REAL,x REAL,y REAL,source TEXT)')
    sources=[];offenses={};quarantine=[];started=time.monotonic()
    try:
        for (id,label),meta,scope in zip(SOURCES,metas,full):
            expected=int(get(query(id,{'$select':'count(*) as n','$where':where}))[0]['n'])
            params={'$select':','.join(FIELDS),'$where':where,'$limit':2000000}
            url=HOST+'/resource/'+id+'.csv?'+urllib.parse.urlencode(params)
            missing=Counter();rejected=Counter();rows=0;kept=0;batch=[]
            print('Streaming',id,'expected',expected,flush=True)
            req=urllib.request.Request(url,headers={'User-Agent':'STREETWISE-NYC-open-data/1.0','Accept-Encoding':'gzip'})
            with urllib.request.urlopen(req,timeout=180) as response:
                raw=gzip.GzipFile(fileobj=response) if response.headers.get('Content-Encoding')=='gzip' else response
                for r in csv.DictReader(io.TextIOWrapper(raw,encoding='utf-8-sig',newline='')):
                    r={k:(None if v in ('','(null)') else v) for k,v in r.items()}
                    rows+=1
                    for f in FIELDS:missing[f]+=not r.get(f)
                    try:
                        pid=int(r['cmplnt_num']);day=date.fromisoformat(r['cmplnt_fr_dt'][:10]);reported=date.fromisoformat(r['rpt_dt'][:10]) if r.get('rpt_dt') else None
                        lon,lat=float(r['longitude']),float(r['latitude']);code=int(r['ky_cd'])
                    except (KeyError,ValueError,TypeError,OverflowError):rejected['invalid_or_missing_identity_date_coordinate_or_offense']+=1;continue
                    if not (start<=day.isoformat()<end):rejected['outside_requested_time']+=1;continue
                    if reported and reported<day:
                        rejected['report_before_occurrence']+=1;quarantine.append({'complaint_id':str(pid),'occurrence_date':day.isoformat(),'report_date':reported.isoformat(),'source':id,'borough':r.get('boro_nm'),'reason':'Report predates stated occurrence'});continue
                    if not (-74.30<lon<-73.68 and 40.45<lat<40.95):rejected['implausible_or_missing_NYC_coordinate']+=1;continue
                    borough=r.get('boro_nm') or 'UNKNOWN'
                    if borough not in ['MANHATTAN','BROOKLYN','QUEENS','BRONX','STATEN ISLAND']:borough='UNKNOWN'
                    offenses.setdefault(str(code),set()).add(r.get('ofns_desc') or 'UNKNOWN')
                    batch.append((pid,day.toordinal(),reported.toordinal() if reported else None,code,r.get('law_cat_cd') or 'UNKNOWN',borough,lon,lat,lon*MX,lat*MY,id));kept+=1
                    if len(batch)>=2000:
                        db.executemany('INSERT OR REPLACE INTO incidents VALUES(?,?,?,?,?,?,?,?,?,?,?)',batch);batch.clear()
                    if rows%100000==0:print(id,'read',rows,flush=True)
            if batch:db.executemany('INSERT OR REPLACE INTO incidents VALUES(?,?,?,?,?,?,?,?,?,?,?)',batch)
            if rows!=expected:raise ValueError(f'Incomplete source {id}: read {rows}, expected {expected}; retaining prior snapshot')
            sources.append({'dataset_id':id,'name':label,'publisher':'NYPD / NYC Open Data','url':HOST+'/d/'+id,
                'publisher_updated_at':datetime.fromtimestamp(meta['rowsUpdatedAt'],timezone.utc).isoformat(),'retrieved_at':datetime.now(timezone.utc).isoformat(),
                'source_total_records':int(scope['n']),'source_min_occurrence_date':scope['min_date'],'source_max_occurrence_date':scope['max_date'],
                'source_latest_report_date':scope['max_report'],'downloaded_rows':rows,'accepted_rows_before_dedup':kept,'rejected':dict(rejected),
                'missing_fields':{f:{'count':missing[f],'fraction':missing[f]/rows if rows else None} for f in FIELDS}})
            db.commit();print(id,'validated',rows,'accepted',kept,'rejected',dict(rejected),flush=True)
        if {m['id']:get(HOST+'/api/views/'+m['id']+'.json').get('rowsUpdatedAt') for m in metas}!=signatures:
            raise ValueError('Publisher changed during ingestion; retain prior snapshot and rerun')
        db.execute('CREATE VIRTUAL TABLE incident_rtree USING rtree(id,min_x,max_x,min_y,max_y)')
        db.execute('INSERT INTO incident_rtree SELECT id,x,x,y,y FROM incidents')
        db.execute('CREATE INDEX incident_time ON incidents(day,offense,law)')
        db.execute('CREATE TABLE grid_daily AS SELECT CAST(floor(x/200) AS INTEGER) gx,CAST(floor(y/200) AS INTEGER) gy,day,offense,law,count(*) n FROM incidents GROUP BY gx,gy,day,offense,law')
        db.execute('CREATE INDEX grid_time ON grid_daily(day,offense,law,gx,gy)')
        db.execute('CREATE INDEX grid_position ON grid_daily(gx,gy,day)')
        db.execute('ANALYZE');db.commit()
        total=db.execute('SELECT count(*) FROM incidents').fetchone()[0]
        boro=dict(db.execute('SELECT borough,count(*) FROM incidents GROUP BY borough'))
        dates=db.execute('SELECT min(day),max(day) FROM incidents').fetchone()
        missing_offenses=db.execute("SELECT count(*) FROM incidents WHERE offense IS NULL OR law='UNKNOWN'").fetchone()[0]
        manifest={'schema_version':2,'metric':'Historical Reported Complaint Density','requested_start':start,'available_start':date.fromordinal(dates[0]).isoformat(),
            'available_end_exclusive':(date.fromordinal(dates[1])+timedelta(days=1)).isoformat(),'default_start':max(date.fromordinal(dates[0]),date.fromordinal(dates[1])-timedelta(days=364)).isoformat(),
            'records':total,'by_borough':boro,'missing_offense_or_law':missing_offenses,'valid_coordinate_records':total,
            'temporal_quarantine_records':len(quarantine),'duplicate_source_ids':sum(s['accepted_rows_before_dedup'] for s in sources)-total,'publisher_versions':signatures,'sources':sources,
            'offenses':{k:sorted(v) for k,v in sorted(offenses.items(),key=lambda x:int(x[0]))},'grid_cell_m':CELL,'projection':{'mx':MX,'my':MY},
            'database':'complaints.sqlite.gz','license':'NYC Open Data Terms of Use','license_url':'https://www.nyc.gov/home/terms-of-use.page',
            'method':'Exact published points indexed by R*Tree; daily/200 m grid aggregates accelerate candidate edge costs. Final route statistics use published point-to-polyline distances, a common corridor and de-duplicated complaint IDs.',
            'limitations':['Reported complaints, not victimization rates or personal risk. No population/activity denominator.','Occurrence dates and approximate published block-level coordinates; not live street conditions.','Most serious recorded offense only; reporting and policing patterns affect counts.','Snapshot is source-bounded and delayed; later reports and corrections can change historical counts.','Bounding-box plausibility does not independently verify every coordinate or borough.','Unknown boroughs remain unknown; no demographic fields are retained.']}
        db.close();db=None
        packed=work/'complaints.sqlite.gz'
        with open(work/'complaints.sqlite','rb') as src,open(packed,'wb') as out,gzip.GzipFile(fileobj=out,mode='wb',mtime=0) as gz:shutil.copyfileobj(src,gz,1024*1024)
        manifest['compressed_bytes']=packed.stat().st_size;manifest['database_bytes']=(work/'complaints.sqlite').stat().st_size
        manifest['sha256']=hashlib.sha256(packed.read_bytes()).hexdigest()
        manifest['built_at']=datetime.now(timezone.utc).isoformat();manifest['build_seconds']=round(time.monotonic()-started,2)
        if prior and total<.7*prior['records']:raise ValueError('Suspicious count regression; retaining prior snapshot')
        if (OUT/'manifest.json').exists():
            history=ROOT.parent/'streetwise-data-history/crime'/prior['sha256'];history.mkdir(parents=True,exist_ok=True)
            shutil.copy2(OUT/'manifest.json',history/'manifest.json');shutil.copy2(OUT/'complaints.sqlite.gz',history/'complaints.sqlite.gz')
        (OUT/'quarantine.json').write_text(json.dumps(quarantine,indent=2));os.replace(packed,OUT/'complaints.sqlite.gz');(work/'manifest.json').write_text(json.dumps(manifest,indent=2));os.replace(work/'manifest.json',OUT/'manifest.json')
        print(json.dumps({'records':total,'by_borough':boro,'compressed_bytes':manifest['compressed_bytes'],'database_bytes':manifest['database_bytes'],'seconds':manifest['build_seconds']}),flush=True)
    finally:
        if db:db.close()
        shutil.rmtree(work,ignore_errors=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--start',default='2025-01-01');p.add_argument('--force',action='store_true');a=p.parse_args();date.fromisoformat(a.start);build(a.start,a.force)
